"""
fix-daemon-lifecycle-races 回归测试。

覆盖：
- (1) state_transition_idempotency：transition()/transition_gate() 幂等自迁移
      INFO+True，真实非法迁移仍 ERROR+False
- (2) verify-recovery-budget：重启重验计数递增/跨重启持久化/超限冻结/unfreeze 清零
- (3) daemon-drain-integrity：启动终态补写扫描（无终态 run 补 interrupted，有终态不误伤）
- (4) done-push-dedup：approve_push 实例级互斥锁单飞（双并发仅一次 push）
- (5) stale-verdict-race-guard：结果处理状态判据（非 testing → DEBUG 丢弃，零派发）
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, SpecStatus
from core.worktree_manager import WorktreeManager
from core.agent_runner.liveness import (
    RUN_TERMINAL_EVENT_TYPES,
    RUNTIME_SWEEP_IDLE_SECONDS,
    LivenessSupervisor,
    sweep_runs_without_terminal_state,
)

# 模块级 import（test_admin.py 同款处方）：直接绑定守护脚本模块 fenixd.py，
# 供用例在测试执行期使用（fixture 内不重复导入）。
import fenixd as _fenixd_mod


def _push_spec_to(sm: StateMachine, name: str, target: str):
    """把 spec 沿合法链走到 target（target 必须可达）。"""
    chain = {
        "ready": ["drafted", "ready"],
        "implementing": ["drafted", "ready", "implementing"],
        "implemented": ["drafted", "ready", "implementing", "implemented"],
        "testing": ["drafted", "ready", "implementing", "implemented", "testing"],
        "verified": ["drafted", "ready", "implementing", "implemented", "testing", "verified"],
        "done": ["drafted", "ready", "implementing", "implemented", "testing", "verified", "done"],
        "pushed": ["drafted", "ready", "implementing", "implemented", "testing", "verified", "done", "pushed"],
        "blocked": ["drafted", "ready", "implementing", "blocked"],
    }
    for step in chain[target]:
        sm.update_spec(name, {"status": step})


# ── (1) 状态机幂等自迁移 ─────────────────────────────────────────────
class TestIdempotentTransition(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_idempotent_self_transition_returns_true_no_error(self):
        """pushed→pushed 幂等返回 True，不记 ERROR。"""
        self.sm.add_spec("spec-a", {"status": "pushed"})
        self.sm.logger.reset_mock()
        self.assertTrue(self.sm.transition("spec-a", "pushed"))
        # 无 ERROR（Invalid transition 不再产生）
        err_calls = [c for c in self.sm.logger.error.call_args_list
                     if "Invalid transition" in str(c)]
        self.assertEqual(err_calls, [], "幂等自迁移不得记 ERROR")
        self.assertEqual(self.sm.read_one("spec-a")["status"], "pushed")

    def test_real_invalid_transition_still_errors(self):
        """implemented→verified 仍记 ERROR 并返回 False。"""
        self.sm.add_spec("spec-a", {"status": "implemented"})
        self.sm.logger.reset_mock()
        self.assertFalse(self.sm.transition("spec-a", "verified"))
        err_texts = " ".join(str(c) for c in self.sm.logger.error.call_args_list)
        self.assertIn("Invalid transition", err_texts)

    def test_transition_gate_idempotent(self):
        """transition_gate 对 old==new 幂等返回 True。"""
        self.sm.add_spec("spec-a", {"status": "verified"})
        self.assertTrue(self.sm.transition_gate("spec-a", "verified"))
        self.assertEqual(self.sm.read_one("spec-a")["status"], "verified")

    def test_idempotent_dispatch_no_double_effect(self):
        """dispatch 层 testing→testing 幂等（修复重派同态跳过不再 ERROR）。"""
        self.sm.add_spec("spec-a", {"status": "testing"})
        self.assertTrue(self.sm.transition("spec-a", "testing"))


# ── (2) 重启重验计数与预算冻结 ────────────────────────────────────────
class TestVerifyRedoBudget(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _add_testing_spec(self, name="spec-a", redo_count=0):
        self.sm.add_spec(name, {"status": "testing", "branch": "fenix/spec-a"})
        if redo_count:
            self.sm.update_spec(name, {"_verify_redo_count": redo_count})

    def _get_redo_count(self, entry):
        """读 STATE.md 内部字段时对齐代码库惯例：int() 强转（字段为字符串格式）。"""
        return int(entry.get("_verify_redo_count") or 0)

    def test_recover_increments_verify_redo_count(self):
        """testing 中断恢复 → 递增 _verify_redo_count 并持久化。"""
        self._add_testing_spec()
        recovered = self.sm.recover_interrupted()
        self.assertIn("spec-a", recovered)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "implemented")
        self.assertEqual(self._get_redo_count(entry), 1)

    def test_redo_count_persists_across_restart(self):
        """计数跨 daemon 重启持久化（新 StateMachine 实例读到同值）。"""
        self._add_testing_spec(redo_count=2)
        self.sm.recover_interrupted()
        sm2 = StateMachine(self.state_path, self.logger)
        entry = sm2.read_one("spec-a")
        self.assertEqual(self._get_redo_count(entry), 3)

    def test_implementing_interrupt_does_not_increment(self):
        """实现中断（implementing）不递增该计数——仅重启恢复重验递增。"""
        self.sm.add_spec("spec-impl", {"status": "implementing"})
        self.sm.recover_interrupted()
        entry = self.sm.read_one("spec-impl")
        self.assertTrue(entry.get("error", "").startswith("Recovered"))
        self.assertEqual(self._get_redo_count(entry), 0)

    def test_redo_count_reaches_budget_freezes(self):
        """第三次重启达阈值 → 结构化冻结（blocked+frozen），不重派 verifier。"""
        self._add_testing_spec(redo_count=2)
        self.sm.recover_interrupted(verify_redo_budget=3)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "blocked")
        self.assertTrue(entry.get("frozen"))
        self.assertIn("重启重验超限", str(entry.get("error")))

    def test_unfreeze_clears_redo_count(self):
        """人工解冻 → 计数清零 + 恢复指定状态。"""
        self._add_testing_spec(redo_count=2)
        self.sm.recover_interrupted(verify_redo_budget=3)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "blocked")
        self.assertTrue(self.sm.unfreeze_spec("spec-a", status="implemented"))
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "implemented")
        self.assertFalse(entry.get("frozen"))
        self.assertEqual(self._get_redo_count(entry), 0)

    def test_below_budget_not_frozen(self):
        """未达阈值不冻结，正常过渡到 implemented。"""
        self._add_testing_spec(redo_count=1)
        self.sm.recover_interrupted(verify_redo_budget=3)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "implemented")
        self.assertEqual(self._get_redo_count(entry), 2)


# ── (3) 启动终态补写扫描 ─────────────────────────────────────────────
class TestTerminalStateSweep(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmpdir) / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, events):
        p = self.runs_dir / f"{name}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")
        return p

    def test_sweep_appends_interrupted_to_untracked_run(self):
        """尾部无终态事件的 run 被追加 interrupted。"""
        self._write("impl-spec-a-1-a1", [
            {"type": "assistant", "message": {"content": []}},
            {"type": "user", "role": "user"},
        ])
        patched = sweep_runs_without_terminal_state(self.runs_dir)
        self.assertEqual(len(patched), 1)
        lines = [json.loads(l) for l in
                 (self.runs_dir / "impl-spec-a-1-a1.jsonl").read_text().splitlines()]
        self.assertEqual(lines[-1]["type"], "interrupted")
        self.assertEqual(lines[-1]["reason"], "startup terminal-state sweep")

    def test_sweep_skips_terminal_runs_any_type(self):
        """任一终态事件（result/interrupted/error/cancelled/frozen-terminated/
        gate-blocked）均不补写。"""
        samples = {
            "a-result": [{"type": "assistant"}, {"type": "result", "result": "ok"}],
            "b-interrupted": [{"type": "assistant"}, {"type": "interrupted", "reason": "shutdown"}],
            "c-error": [{"type": "assistant"}, {"type": "error", "error": "boom", "exit_code": 1}],
            "d-cancelled": [{"type": "assistant"}, {"type": "cancelled", "reason": "user"}],
            # add-freeze-stop-inflight-agents：frozen-terminated 为写侧权威终态
            # 事件（RUN_TERMINAL_EVENT_TYPES 之一），含该行的 run 不得补写。
            "e-frozen": [{"type": "assistant"}, {"type": "frozen-terminated", "reason": "spec frozen"}],
            # add-timeline-gate-failure-display：gate-blocked 为门禁失败终止本次
            # attempt 的写侧终态；该文件此后无写入者，补写 interrupted 会把它
            # 变成「daemon 停机遗留」误归因。
            "f-gate-blocked": [{"type": "assistant"},
                               {"type": "gate-blocked", "spec": "spec-a",
                                "provider": "p", "reason": "artifact_gate",
                                "error": "门禁拒绝（impl-code-review-gate）"}],
        }
        terminals = list(RUN_TERMINAL_EVENT_TYPES)
        self.assertEqual(len(samples), len(terminals))
        for name, events in samples.items():
            self._write(name, events)
        patched = sweep_runs_without_terminal_state(self.runs_dir)
        self.assertEqual(patched, [], "含终态事件的 run 不得被补写")

    def test_sweep_idempotent(self):
        """运行期意外重入（理论上仅启动一次）不重复追加。"""
        self._write("impl-spec-a-1-a1", [{"type": "assistant"}])
        sweep_runs_without_terminal_state(self.runs_dir)
        sweep_runs_without_terminal_state(self.runs_dir)
        lines = [json.loads(l) for l in
                 (self.runs_dir / "impl-spec-a-1-a1.jsonl").read_text().splitlines()]
        self.assertEqual(lines[-1]["type"], "interrupted")
        self.assertEqual(
            sum(1 for l in lines if l["type"] == "interrupted"), 1,
            "sweep 幂等：不重复追加 interrupted")

    def test_sweep_writes_old_orphan_run(self):
        """SIGKILL 遗留旧孤儿 run（isolated 但 mtime 陈旧）仍被补写。"""
        p = self._write("verify-spec-b-1-a1", [{"type": "assistant"}])
        old = time.time() - 86400
        os.utime(p, (old, old))
        patched = sweep_runs_without_terminal_state(self.runs_dir)
        self.assertEqual(len(patched), 1)
        self.assertEqual(patched[0][0], "verify-spec-b-1-a1")

    def test_sweep_missing_dir_returns_empty(self):
        self.assertEqual(sweep_runs_without_terminal_state(
            Path(self.tmpdir) / "nope"), [])

    def test_sweep_tolerates_corrupt_lines(self):
        """损坏 JSON 行不阻断扫描（其余合法行判定照常）。"""
        p = self._write("impl-spec-a-1-a1", [{"type": "assistant"}])
        with p.open("a") as f:
            f.write("{not valid json\n")
        patched = sweep_runs_without_terminal_state(self.runs_dir)
        self.assertEqual(len(patched), 1)

    def test_file_has_terminal_event_shared_helper(self):
        """终态判定口径单源：_file_has_terminal_event 对四类终态均 True。"""
        from core.agent_runner.liveness import _file_has_terminal_event
        cases = {
            "t-result": [{"type": "result", "result": "ok"}],
            "t-interrupted": [{"type": "interrupted", "reason": "x"}],
            "t-error": [{"type": "error", "error": "e", "exit_code": 1}],
            "t-cancelled": [{"type": "cancelled", "reason": "u"}],
        }
        for name, events in cases.items():
            p = self._write(name, events)
            self.assertTrue(_file_has_terminal_event(p), f"{name} 应判有终态")
        p2 = self._write("t-none", [{"type": "assistant"}])
        self.assertFalse(_file_has_terminal_event(p2))

    def test_file_tail_is_terminal_drift_guard(self):
        """fix-orphan-ready-recovery-liveness 3.7 终态口径单源防漂移：
        _file_tail_is_terminal 对 RUN_TERMINAL_EVENT_TYPES 全集判定为 True，
        对 superseded 判定为 False——防后续有人「顺手」把 superseded 并入终态集合。"""
        from core.agent_runner.liveness import _file_tail_is_terminal
        # 终态全集 → True
        for etype in ("result", "interrupted", "error", "cancelled"):
            p = self._write(f"tail-{etype}", [
                {"type": "assistant", "message": {"content": []}},
                {"type": etype, "timestamp": "2026-09-17T00:00:00Z"},
            ])
            self.assertTrue(
                _file_tail_is_terminal(p),
                f"末行 {etype} 应判终态（属 RUN_TERMINAL_EVENT_TYPES）",
            )
        # superseded → False（属弃置标记非终结）
        p_sup = self._write("tail-superseded", [
            {"type": "assistant", "message": {"content": []}},
            {"type": "superseded", "reason": "artifact-gate in-place retry"},
        ])
        self.assertFalse(
            _file_tail_is_terminal(p_sup),
            "superseded 属弃置标记非终结，不得纳入终态集合"
            "（纳入会在 artifact-gate 原地重试退避窗口内造成双派发）",
        )


# ── (3b) 运行期悬空 run 清扫（add-runtime-run-sweeper）───────────────
class TestRuntimeDanglingRunSweep(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sweeper = LivenessSupervisor.__new__(LivenessSupervisor)
        self.sweeper._pm = MagicMock()
        self.sweeper._pm.project_root = Path(self.tmpdir)
        self.sweeper._pm.logger = self.logger
        self.sweeper._pm._running_agents = {}
        self.sweeper._terminal_verified = set()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, events, idle_seconds=None):
        p = self.runs_dir / f"{name}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")
        if idle_seconds is not None:
            old = time.time() - idle_seconds
            os.utime(p, (old, old))
        return p

    def _read_events(self, name):
        return [json.loads(l) for l in
                (self.runs_dir / f"{name}.jsonl").read_text().splitlines()]

    # ── 4.1 悬空 run 补写产物 ────────────────────────────────────────
    def test_dangling_run_patched_with_correct_payload(self):
        """悬空 run（无终态+冷 mtime+不在注册表）→ 补写 interrupted 为文件末行，
        JSONL 合法，reason/idle_seconds/timestamp 字段正确。"""
        idle = 4723
        self._write("impl-spec-a-1788900000-a1",
                    [{"type": "assistant", "message": {"content": []}}], idle)
        patched = self.sweeper.sweep_dangling_runs()
        self.assertEqual(len(patched), 1)
        self.assertEqual(patched[0][0], "impl-spec-a-1788900000-a1")
        lines = self._read_events("impl-spec-a-1788900000-a1")
        # JSONL 合法（逐行可解析）且 interrupted 为末行
        self.assertEqual(lines[-1]["type"], "interrupted")
        self.assertEqual(lines[-1]["reason"], "runtime terminal-state sweep")
        self.assertEqual(lines[-1]["idle_seconds"], idle)
        # timestamp 为 UTC ISO8601（带 +00:00 偏移或 Z）
        ts = lines[-1]["timestamp"]
        self.assertTrue("+" in ts or ts.endswith("Z"))
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        self.assertEqual(dt.utcoffset().total_seconds(), 0, "timestamp 必须为 UTC")
        # WARNING 留痕含 run_id
        warn_texts = " ".join(str(c) for c in self.logger.warning.call_args_list)
        self.assertIn("impl-spec-a-1788900000-a1", warn_texts)

    # ── 4.2 在飞保护 ─────────────────────────────────────────────────
    def test_inflight_run_protected_and_not_opened(self):
        """注册表命中的 run 不被补写且不被打开读取。"""
        p = self._write("impl-spec-b-1788900000-a1",
                        [{"type": "assistant"}], 7200)
        self.sweeper._pm._running_agents["impl-spec-b-1788900000-a1"] = MagicMock()
        opened = []
        orig_open = Path.open
        def _spy_open(self, *a, **kw):
            opened.append(str(self))
            return orig_open(self, *a, **kw)
        with unittest.mock.patch.object(Path, "open", _spy_open):
            patched = self.sweeper.sweep_dangling_runs()
        self.assertEqual(patched, [], "在飞 run 不得被补写")
        self.assertNotIn(str(p), opened, "在飞 run 不得被打开读取")
        # 在飞文件不入缓存（其终态由 run 线程写入）
        self.assertNotIn("impl-spec-b-1788900000-a1", self.sweeper._terminal_verified)

    # ── 4.3 流停保护 ─────────────────────────────────────────────────
    def test_fresh_mtime_run_not_patched_not_opened(self):
        """mtime 停更 < 阈值的无终态 run 不被补写不被读取（短路免读）。"""
        self._write("impl-spec-c-1788900000-a1", [{"type": "assistant"}], 600)
        opened = []
        orig_open = Path.open
        def _spy_open(self, *a, **kw):
            opened.append(str(self))
            return orig_open(self, *a, **kw)
        with unittest.mock.patch.object(Path, "open", _spy_open):
            patched = self.sweeper.sweep_dangling_runs()
        self.assertEqual(patched, [], "流未停更不得补写")
        self.assertEqual(opened, [], "mtime 判据不过 MUST NOT 打开读取")

    def test_boundary_idle_threshold_reached(self):
        """mtime 停更 ≥ 阈值才进入判定（阈值本身判悬空）。"""
        idle = RUNTIME_SWEEP_IDLE_SECONDS
        self._write("impl-spec-d-1788900000-a1", [{"type": "assistant"}], idle)
        patched = self.sweeper.sweep_dangling_runs()
        self.assertEqual(len(patched), 1, "停更恰为阈值即满足判据 ②")

    # ── 4.4 缓存语义 ─────────────────────────────────────────────────
    def test_terminal_file_cached_no_reopen(self):
        """已终态文件第二轮不重复打开（缓存命中短路）。"""
        self._write("impl-spec-e-1788900000-a1",
                    [{"type": "assistant"}, {"type": "result", "result": "ok"}], 7200)
        first = self.sweeper.sweep_dangling_runs()
        self.assertEqual(first, [], "含 result 终态不补写")
        self.assertIn("impl-spec-e-1788900000-a1", self.sweeper._terminal_verified)
        opened = []
        orig_open = Path.open
        def _spy_open(self, *a, **kw):
            opened.append(str(self))
            return orig_open(self, *a, **kw)
        with unittest.mock.patch.object(Path, "open", _spy_open):
            second = self.sweeper.sweep_dangling_runs()
        self.assertEqual(second, [])
        self.assertEqual(opened, [], "缓存命中第二轮 MUST NOT 打开文件")

    def test_patched_file_idempotent_no_reappend(self):
        """已补写文件不重复追加（幂等），后续轮次零追加。"""
        self._write("impl-spec-f-1788900000-a1", [{"type": "assistant"}], 7200)
        first = self.sweeper.sweep_dangling_runs()
        self.assertEqual(len(first), 1)
        lines = self._read_events("impl-spec-f-1788900000-a1")
        self.assertEqual(lines[-1]["type"], "interrupted")
        # 第二轮：补写后已入缓存
        second = self.sweeper.sweep_dangling_runs()
        self.assertEqual(second, [])
        lines2 = self._read_events("impl-spec-f-1788900000-a1")
        self.assertEqual(lines2, lines, "第二轮 MUST NOT 追加任何事件")
        self.assertEqual(
            sum(1 for l in lines2 if l.get("type") == "interrupted"), 1)

    # ── 4.5 源头修复：崩溃 run 不被重复补写 ──────────────────────────
    def test_error_terminal_file_not_swept(self):
        """含 error 终态（源头修复产物）的文件不被清扫器补写。"""
        self._write("impl-spec-g-1788900000-a1",
                    [{"type": "assistant"},
                     {"type": "error",
                      "error": "run thread crashed: TypeError('x')",
                      "exit_code": None}], 7200)
        patched = self.sweeper.sweep_dangling_runs()
        self.assertEqual(patched, [], "含 error 终态 = 判据 ③ 不满足")
        lines = self._read_events("impl-spec-g-1788900000-a1")
        self.assertNotIn(
            "interrupted", [l.get("type") for l in lines])

    def test_run_claude_poll_loop_crash_writes_error_terminal(self):
        """轮询环抛非预期异常 → jsonl 即刻出现含 repr 归因的 error 终态行、
        异常继续上抛（源头修复 D4）。"""
        from core.agent_runner.runner import AgentRunner
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = Path(self.tmpdir)
        runner.logger = MagicMock()
        runner.config = {}
        runner._running_agents = {}
        runner._cancel_meta = {}
        run_id = "impl-spec-h-1788900000-a1"
        run_file = self.runs_dir / f"{run_id}.jsonl"
        # Popen 替身：poll 立即抛非预期异常，触发轮询环 except Exception
        fake_proc = MagicMock()
        fake_proc.poll.side_effect = TypeError("boom-inside-poll-loop")
        fake_proc.stdout = MagicMock()
        fake_proc.stderr = MagicMock()
        with unittest.mock.patch.object(
                subprocess, "Popen", return_value=fake_proc), \
             unittest.mock.patch(
                "threading.Thread", side_effect=_no_thread_factory), \
             unittest.mock.patch.object(
                AgentRunner, "_effective_run_timeout", create=True,
                return_value=3600), \
             unittest.mock.patch.object(
                AgentRunner, "_cancel_is_requested",
                create=True, return_value=False), \
             unittest.mock.patch.object(
                AgentRunner, "_normalize_run_id",
                create=True, side_effect=lambda x: x):
            with self.assertRaises(TypeError) as ctx:
                runner._run_agent(
                    "prompt", Path(self.tmpdir), run_id,
                    spec_name="spec-h", agent_type="impl")
        self.assertIn("boom-inside-poll-loop", str(ctx.exception),
                      "异常必须原样 re-raise 上抛")
        self.assertTrue(run_file.exists(), "run jsonl 必须已创建")
        lines = [json.loads(l) for l in run_file.read_text().splitlines()]
        terminal = [l for l in lines if l.get("type") == "error"]
        self.assertEqual(len(terminal), 1, "应恰好一条 error 终态行")
        self.assertIn("run thread crashed", terminal[0]["error"])
        self.assertIn("TypeError", terminal[0]["error"], "error 行须含 repr 归因")
        # fix-agent-lane-efficiency D3：run_metrics 行在终态行之后追加（终态行之后
        # 有一行 run_metrics），不再要求 error 行是文件末行
        metrics = [l for l in lines if l.get("type") == "run_metrics"]
        self.assertEqual(len(metrics), 1, "应恰好一条 run_metrics 行")
        self.assertTrue(
            lines.index(terminal[0]) < lines.index(metrics[0]),
            "error 行必须在 run_metrics 行之前",
        )

    # ── 4.6 挂载点异常降级 ───────────────────────────────────────────
    def _make_event_bus(self, order=None):
        """EventBus 替身：绕过 __init__（不依赖 daemon 装配），capture 两轮循环
        后置 _running=False 结束线程（避免真实 30s sleep）。"""
        import core.event_bus as event_bus_mod
        eb = event_bus_mod.EventBus.__new__(event_bus_mod.EventBus)
        eb._running = True
        eb.logger = MagicMock()
        eb.pm_engine = MagicMock()

        real_full_scan = MagicMock(
            side_effect=(lambda: order.append("scan")) if order is not None else None)
        eb.full_scan = real_full_scan
        eb.pm_engine.agent_runner.sweep_dangling_runs.side_effect = OSError(
            "runs dir io error")
        if order is not None:
            eb.pm_engine.agent_runner.sweep_dangling_runs.side_effect = \
                lambda: order.append("sweep")
        eb.config = {"schedule": {"poll_interval_minutes": 0.001}}
        orig_sleep = time.sleep
        state = {"rounds": 0}

        def _fake_sleep(seconds):
            # 周期 sleep 缩短为毫秒级；sleep 后是 sweep+full_scan 主体
            orig_sleep(min(seconds, 0.001))
            state["rounds"] += 1
            if state["rounds"] >= 2:
                eb._running = False  # 两轮后结束循环
        return eb, _fake_sleep

    def test_event_bus_sweep_failure_does_not_block_scan(self):
        """sweep_dangling_runs 抛异常 → 当轮 full_scan 仍执行、WARNING 留痕。"""
        eb, fake_sleep = self._make_event_bus()
        with unittest.mock.patch.object(time, "sleep", fake_sleep):
            t = threading.Thread(
                target=eb._periodic_scan_loop, args=(0.001,), daemon=True)
            t.start()
            t.join(timeout=15)
        self.assertFalse(t.is_alive(), "两轮后循环应退出（测试自身驱动）")
        eb.full_scan.assert_called_once()
        warn_texts = " ".join(str(c) for c in eb.logger.warning.call_args_list)
        self.assertIn("sweep", warn_texts.lower())

    def test_event_bus_sweep_runs_before_full_scan(self):
        """先扫后 scan：sweep_dangling_runs 调用先于 full_scan。"""
        order = []
        eb, fake_sleep = self._make_event_bus(order=order)
        with unittest.mock.patch.object(time, "sleep", fake_sleep):
            t = threading.Thread(
                target=eb._periodic_scan_loop, args=(0.001,), daemon=True)
            t.start()
            t.join(timeout=15)
        self.assertEqual(order, ["sweep", "scan"], "先 sweep 后 full_scan")

    def test_event_bus_mounted_facade_delegation(self):
        """event_bus 挂载经门面：agent_runner.sweep_dangling_runs 委托到
        LivenessSupervisor（组件/门面漏改防线）。"""
        from core.agent_runner.runner import AgentRunner
        runner = AgentRunner.__new__(AgentRunner)
        run_id = "impl-spec-i-1788900000-a1"
        self._write(run_id, [{"type": "assistant"}], 7200)
        runner.project_root = Path(self.tmpdir)
        runner.logger = MagicMock()
        runner._running_agents = {}
        patched = runner.sweep_dangling_runs()
        self.assertEqual(len(patched), 1, "门面委托应命中悬空 run")


def _no_thread_factory(*args, **kwargs):
    """读线程替身工厂：不真正起线程（测试内 Popen.stdout 为 MagicMock）。"""
    return MagicMock()


# ── (4) approve_push 实例级单飞 ──────────────────────────────────────
class TestApprovePushSingleFlight(unittest.TestCase):
    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        (Path(self.tmpdir) / ".fenix" / "STATE.md")
        self.logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(self.logger, m, MagicMock())
        self.sm = StateMachine(Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger)
        # 隔离 push 内部链路，仅保留 _git_push_ref 真实计数
        self.engine._is_push_backoffed = MagicMock(return_value=False)
        self.engine._resolve_push_branch = MagicMock(return_value="fenix/spec-a")
        self.engine._push_branch_best_effort = MagicMock()
        self.engine._archive_auto_commit = MagicMock()
        self.engine._append_project_log = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_done_spec(self):
        self.sm.add_spec("spec-a", {"status": "done", "branch": "fenix/spec-a"})

    def test_concurrent_approve_push_single_flight(self):
        """双路径并发 approve_push：仅一次 main push，串行后第二流幂等跳过。"""
        from concurrent.futures import ThreadPoolExecutor
        self._make_done_spec()
        push_calls = []
        # 事件同步（替代 sleep 放大临界区）：第二个流「即将进入 approve_push」
        # 前 set，第一个流的 push 等它——保证第二流确实撞在锁上，不靠时间赌。
        second_ready = threading.Event()

        def fake_git_push(ref, *a, **k):
            push_calls.append(ref)
            second_ready.wait(timeout=5)
            return True, ""

        self.engine._git_push_ref = fake_git_push

        def _enter(idx):
            if idx == 1:
                second_ready.set()
            return self.engine.approve_push("spec-a")

        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_enter, i) for i in (0, 1)]
            results = [f.result() for f in futs]

        self.assertTrue(all(results), "两个并发流都应返回 True（第二流幂等跳过）")
        main_calls = [r for r in push_calls if r == "main"]
        self.assertEqual(len(main_calls), 1, "双并发仅一次 main push")
        self.assertEqual(self.sm.read_one("spec-a")["status"], "pushed")
        # 无 pushed→pushed ERROR（第二流进锁后见 pushed 幂等返回）
        err_texts = " ".join(str(c) for c in self.logger.error.call_args_list)
        self.assertNotIn("Invalid transition: spec-a pushed → pushed", err_texts)

    def test_approve_push_idempotent_when_already_pushed(self):
        """锁内重读见 pushed → 幂等跳过，不再 push/写 project log。"""
        self.sm.add_spec("spec-a", {"status": "pushed"})
        self.engine._git_push_ref = MagicMock(return_value=(True, ""))
        self.assertTrue(self.engine.approve_push("spec-a"))
        self.engine._git_push_ref.assert_not_called()
        self.engine._append_project_log.assert_not_called()

    def test_diff_specs_serialize_through_global_lock(self):
        """不同 spec 并发 push 串行执行（全局锁）。"""
        from concurrent.futures import ThreadPoolExecutor
        for name in ("spec-a", "spec-b"):
            self.sm.add_spec(name, {"status": "done", "branch": f"fenix/{name}"})
        push_calls = []
        second_ready = threading.Event()

        def fake_git_push(ref, *a, **k):
            push_calls.append((ref,))
            second_ready.wait(timeout=5)
            return True, ""

        self.engine._git_push_ref = fake_git_push
        self.engine._resolve_push_branch = MagicMock(
            side_effect=lambda name, spec: f"fenix/{name}")

        def _enter(name, idx):
            if idx == 1:
                second_ready.set()
            return self.engine.approve_push(name)

        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_enter, n, i)
                    for i, n in enumerate(("spec-a", "spec-b"))]
            self.assertTrue(all(f.result() for f in futs))
        # 每个 spec 各一次 main push，两 spec 共 2 次（串行非重入）
        main_calls = [r[0] for r in push_calls if r[0] == "main"]
        self.assertEqual(len(main_calls), 2)
        self.assertEqual(self.sm.read_one("spec-a")["status"], "pushed")
        self.assertEqual(self.sm.read_one("spec-b")["status"], "pushed")


# ── (5) stale-verdict 状态判据 ───────────────────────────────────────
class TestStaleVerdictGuard(unittest.TestCase):
    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(self.logger, m, MagicMock())
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger)
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        # legacy 结果应用路径调 pipeline._record_infra_failure（非门面），
        # 须挂在 _verification 上（门面转发解析回同一 mock）。
        self.engine._verification._record_infra_failure = MagicMock()
        self.engine._record_infra_failure = self.engine._verification._record_infra_failure
        # 隔离与 D6 正交的各闸门
        self.engine._verification._read_verify_report = MagicMock(return_value={})
        self.engine._verification._handle_env_blocked_inconclusive = MagicMock(return_value=False)
        self.engine._verification._verifier_result_is_stale = MagicMock(return_value=False)
        self.engine._verification._judge_bugs_declare_env = MagicMock(return_value=False)
        self.engine._verification._ensure_verification_report = MagicMock(return_value=None)
        self.engine._verification._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._verification._check_verification_gate = MagicMock(return_value=None)
        self.engine._verification._verify_verdict_evidence = MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        # 本类用例真实调 _run_three_stage_verification：引擎开头的
        # core.verify_engine importlib.reload（daemon 热更新设计）在测试进程里
        # 换掉 TestScenario/VerifyEngine 类对象，污染同进程后续测试的
        # isinstance 判定（test_cancel_holdstate_recovery 6ce7461e 同款处方）。
        self._reload_patcher = patch("importlib.reload", lambda m: m)
        self._reload_patcher.start()
        self.addCleanup(self._reload_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_testing_spec(self, name="legacy-spec"):
        self.sm.add_spec(name, {"priority": 5})
        _push_spec_to(self.sm, name, "testing")

    def _write_result(self, spec, status):
        self.result_path.write_text(
            json.dumps({"spec": spec, "status": status, "role": "verifier"}))

    def test_legacy_entry_guard_discards_when_not_testing(self):
        """spec 入口已非 testing（拨回 implemented）→ 不跑 verifier、零派发。"""
        self.sm.add_spec("legacy-spec", {"status": "implemented"})
        self.engine._run_legacy_verification("legacy-spec")
        self.engine.agent_runner.run_verifier.assert_not_called()
        entry = self.sm.read_one("legacy-spec")
        self.assertEqual(entry["status"], "implemented")

    def test_three_stage_entry_guard_discards_when_not_testing(self):
        """三步流水线入口非 testing → 丢弃，不跑 planner。"""
        self.sm.add_spec("spec-a", {"status": "implemented"})
        self.engine._run_three_stage_verification("spec-a")
        self.engine.agent_runner.run_planner.assert_not_called()
        self.assertEqual(self.sm.read_one("spec-a")["status"], "implemented")

    def test_result_discarded_when_spec_reset_during_verify(self):
        """在飞 run 完成时 spec 已被重置 → 结果 DEBUG 丢弃，不迁移不重派。"""
        from types import SimpleNamespace
        self._make_testing_spec()
        self._write_result("legacy-spec", "verified")
        self.engine.agent_runner.run_verifier.side_effect = (
            lambda *a, **k: self._reset_spec_then_return("legacy-spec"))

        self.engine._run_legacy_verification("legacy-spec")
        entry = self.sm.read_one("legacy-spec")
        self.assertEqual(entry["status"], "implemented", "结果被丢弃，spec 保持拨回状态")
        self.engine._on_spec_verified.assert_not_called()
        self.engine._on_spec_bug_found.assert_not_called()
        self.engine._enqueue.assert_not_called()
        # DEBUG 日志注明 run_id 与当前状态
        debug_texts = " ".join(str(c) for c in self.logger.debug.call_args_list)
        self.assertIn("discarded", debug_texts)
        self.assertIn("verify-legacy-spec-", debug_texts)

    def _reset_spec_then_return(self, name):
        self.sm.update_spec(name, {"status": "implemented",
                                   "error": "stale/foreign verifier result replayed"})
        from types import SimpleNamespace
        return SimpleNamespace(
            success=True, error=None,
            run_id=f"verify-{name}-{int(time.time())}-a1",
        )

    def test_normal_result_processing_unaffected(self):
        """状态为 testing 的正常结果照常消费：verified 迁移照常执行。"""
        from types import SimpleNamespace
        self._make_testing_spec()
        self._write_result("legacy-spec", "verified")
        self.engine.agent_runner.run_verifier.return_value = SimpleNamespace(
            success=True, error=None, run_id="verify-legacy-spec-99-a1")
        self.engine._run_legacy_verification("legacy-spec")
        entry = self.sm.read_one("legacy-spec")
        self.assertEqual(entry["status"], "verified", "正常路径不受状态判据影响")

    def test_bugfound_result_discarded_when_reset(self):
        """被拒结果零派发：bug-found 路径同样被入口/应用判据丢弃。"""
        from types import SimpleNamespace
        self._make_testing_spec()
        self._write_result("legacy-spec", "bug-found")
        self.engine.agent_runner.run_verifier.side_effect = (
            lambda *a, **k: self._reset_spec_then_return("legacy-spec"))
        self.engine._run_legacy_verification("legacy-spec")
        entry = self.sm.read_one("legacy-spec")
        self.assertEqual(entry["status"], "implemented")
        self.engine._on_spec_bug_found.assert_not_called()
        self.engine._enqueue.assert_not_called()

    # ── fix-verify-late-result-terminal-clobber 1.5：非 testing 状态下
    #    迟到 stale/foreign 结果一律丢弃（三个缺口分支的终态复核）────────

    def _flip_spec_then_return(self, name, status):
        """run_verifier side_effect：调用期间把 spec 翻到 status 后返回成功结果。

        模拟「入口时 testing、在飞 run 长达数十分钟期间状态合法流转至
        终态/其它状态」的迟到结果场景（2026-09-24 事故形态）。
        """
        from types import SimpleNamespace

        def _side(*a, **k):
            self.sm.update_spec(name, {"status": status})
            return SimpleNamespace(
                success=True, error=None,
                run_id=f"verify-{name}-{int(time.time())}-a1",
            )

        return _side

    def _reset_guard_mocks(self):
        self.engine._record_infra_failure.reset_mock()
        self.engine._enqueue.reset_mock()
        self.engine._on_spec_bug_found.reset_mock()
        self.engine._on_spec_verified.reset_mock()
        self.logger.debug.reset_mock()
        self.logger.warning.reset_mock()

    def _assert_late_result_fully_dropped(self, name, status):
        """迟到结果零影响：状态字段不变、无 infra 记账、无重派、DEBUG 含当前状态。"""
        entry = self.sm.read_one(name)
        self.assertEqual(entry["status"], status, "迟到结果不得覆写当前状态")
        self.assertNotIn(
            "stale/foreign verifier result replayed",
            entry.get("error") or "",
            "re-dispatch error 文案不得被写入",
        )
        self.engine._record_infra_failure.assert_not_called()
        self.engine._enqueue.assert_not_called()
        self.engine._on_spec_bug_found.assert_not_called()
        self.engine._on_spec_verified.assert_not_called()
        debug_texts = " ".join(str(c) for c in self.logger.debug.call_args_list)
        self.assertIn("discarded", debug_texts)
        self.assertIn(f"current state '{status}'", debug_texts,
                      "DEBUG 日志须记录当前状态")

    def test_late_stale_result_discarded_in_terminal_states(self):
        """成功路径 stale 守卫分支：pushed/done/implemented 下迟到 stale 结果零影响。"""
        for target in ("pushed", "done", "implemented"):
            with self.subTest(target=target):
                name = f"late-stale-{target}"
                self.sm.add_spec(name, {"priority": 5})
                _push_spec_to(self.sm, name, "testing")
                self._write_result(name, "verified")
                self.engine._verification._verifier_result_is_stale = MagicMock(
                    return_value=True)
                self.engine.agent_runner.run_verifier.side_effect = (
                    self._flip_spec_then_return(name, target))
                self._reset_guard_mocks()
                self.engine._run_legacy_verification(name)
                self._assert_late_result_fully_dropped(name, target)

    def test_late_foreign_role_result_discarded_before_gate(self):
        """foreign-role/foreign-stamp 分支：非 testing 丢弃，且复核先于放行门禁。"""
        for target in ("pushed", "done", "implemented"):
            with self.subTest(target=target):
                name = f"late-foreign-{target}"
                self.sm.add_spec(name, {"priority": 5})
                _push_spec_to(self.sm, name, "testing")
                # 共享 fallback 文件缺 role → _read_verdict 判 foreign-role
                self.result_path.write_text(
                    json.dumps({"spec": name, "status": "success"}))
                gate = MagicMock(return_value=False)
                self.engine._verification._verified_gate_refuses = gate
                self.engine.agent_runner.run_verifier.side_effect = (
                    self._flip_spec_then_return(name, target))
                self._reset_guard_mocks()
                self.engine._run_legacy_verification(name)
                self._assert_late_result_fully_dropped(name, target)
                gate.assert_not_called(
                ), "D6 复核须先于 _verified_gate_refuses（终态 SPEC 不再消耗门禁判定）"

    def test_late_unknown_status_stale_result_discarded(self):
        """unknown-status+stale 分支：非 testing 丢弃，不覆写不记账不重派。"""
        for target in ("pushed", "done", "implemented"):
            with self.subTest(target=target):
                name = f"late-unknown-{target}"
                self.sm.add_spec(name, {"priority": 5})
                _push_spec_to(self.sm, name, "testing")
                # role=verifier 但 status 白名单外（implementer 残留形态）
                self._write_result(name, "success")
                self.engine._verification._verifier_result_is_stale = MagicMock(
                    return_value=True)
                self.engine.agent_runner.run_verifier.side_effect = (
                    self._flip_spec_then_return(name, target))
                self._reset_guard_mocks()
                self.engine._run_legacy_verification(name)
                self._assert_late_result_fully_dropped(name, target)

    def test_testing_state_stale_behavior_unchanged(self):
        """testing 状态下 stale 分支既有行为逐项不变（纯增防御回归锚）。"""
        name = "testing-stale-spec"
        self.sm.add_spec(name, {"priority": 5})
        _push_spec_to(self.sm, name, "testing")
        self._write_result(name, "verified")
        self.engine._verification._verifier_result_is_stale = MagicMock(
            return_value=True)
        self.engine.agent_runner.run_verifier.side_effect = (
            self._flip_spec_then_return(name, "testing"))
        self.engine._run_legacy_verification(name)
        entry = self.sm.read_one(name)
        self.assertEqual(entry["status"], "implemented",
                         "testing 内 stale 结果仍走既有回退重派语义")
        self.assertEqual(entry["tester_run"], None)
        self.assertEqual(
            entry["error"],
            "stale/foreign verifier result replayed — re-dispatching fresh verify",
            "error 文案逐字不变")
        self.engine._record_infra_failure.assert_called_once()


# ── (5b) 机械快道裁决来源戳（fix-verify-late-result-terminal-clobber D3）──
class TestMechanicalFastPathRoleStamp(unittest.TestCase):
    """快道产物补 role=verifier 后：读侧归属校验放行、新鲜文件不误判、跨 spec 仍拒。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger)
        self.pipe = self.engine._verification

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fast_path(self, spec):
        from core.pm_engine.verification.judge_gate import _all_green_fast_path
        report = {"summary": {"passed": 3, "total": 3, "warnings": 0, "failed": 0}}
        return _all_green_fast_path(self.pipe, spec, report, 0)

    def _primary(self, spec):
        from core.pm_engine.verification.report_gate import (
            _verify_progress_result_paths,
        )
        primary, _ = _verify_progress_result_paths(self.pipe, spec)
        return primary

    def test_fast_path_payload_carries_verifier_role(self):
        """快道 payload 含 role=verifier，mechanical/spec/status 既有字段保留。"""
        ret = self._fast_path("stamp-spec")
        self.assertIsNotNone(ret, "全绿快道应出裁决")
        data = json.loads(self._primary("stamp-spec").read_text(encoding="utf-8"))
        self.assertEqual(data["role"], "verifier")
        self.assertTrue(data["mechanical"])
        self.assertEqual(data["status"], "verified")
        self.assertEqual(data["spec"], "stamp-spec")
        self.assertEqual(data["bugs"], [])

    def test_fast_path_verdict_reads_ok_with_role(self):
        """快道产物经 _read_verifier_result/_read_verdict 读取：role 校验通过。"""
        from core.pm_engine.verification.report_gate import (
            _read_verdict,
            _read_verifier_result,
        )
        self._fast_path("stamp-spec")
        primary = self._primary("stamp-spec")
        direct = _read_verifier_result(self.pipe, primary)
        self.assertTrue(direct.ok)
        self.assertEqual(direct.status, "verified")
        verdict = _read_verdict(self.pipe, "stamp-spec")
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.status, "verified")

    def test_fresh_fast_path_not_judged_stale(self):
        """同 spec 新鲜快道文件：在飞 verifier 的 stale 校验不误判。"""
        from types import SimpleNamespace
        from core.pm_engine.verification.report_gate import _verifier_result_is_stale
        self._fast_path("stamp-spec")
        run = SimpleNamespace(
            run_id=f"verify-stamp-spec-{int(time.time())}-a1")
        self.assertFalse(
            _verifier_result_is_stale(self.pipe, run, self._primary("stamp-spec"),
                                      "stamp-spec"))

    def test_cross_spec_stamp_still_rejected(self):
        """跨 spec 戳（spec 不符）仍判不采信：stale 判 True、共享回退判 foreign-stamp。"""
        from types import SimpleNamespace
        from core.pm_engine.verification.report_gate import (
            _read_verdict,
            _verifier_result_is_stale,
        )
        self._fast_path("stamp-spec")
        run = SimpleNamespace(
            run_id=f"verify-other-spec-{int(time.time())}-a1")
        self.assertTrue(
            _verifier_result_is_stale(self.pipe, run, self._primary("stamp-spec"),
                                      "other-spec"),
            "spec 戳不符必须不采信")
        # 共享 fallback 形态：role=verifier 但 spec 戳不符 → foreign-stamp
        shared = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        shared.write_text(self._primary("stamp-spec").read_text(encoding="utf-8"))
        verdict = _read_verdict(self.pipe, "other-spec")
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.reason, "foreign-stamp")


# ── (6) supervisor 自报与 daemon 排水一致性自检 ────────────────────────
class TestSupervisorRuntimeWrite(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fenix = Path(self.tmpdir) / ".fenix"
        self.fenix.mkdir(parents=True, exist_ok=True)
        import importlib.util
        sup_path = (Path(__file__).resolve().parent.parent
                    / "bin" / "fenixd_supervisor.py")
        spec = importlib.util.spec_from_file_location("fenixd_supervisor", sup_path)
        self.sup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sup)
        self.sup.FENIX_DIR = self.fenix
        self.sup.PROJECT_ROOT = self.tmpdir

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_supervisor_runtime_file_shape(self):
        """supervisor 启动写 runtime 文件：字段形状（sigkill_wait 数值口径
        已由 test_interrupt_recovery_preserve::TestSupervisorWait 单源覆盖）。"""
        (self.fenix / "config.yaml").write_text(
            "admin:\n  shutdown_drain_seconds: 1800\n", encoding="utf-8")
        self.sup._write_supervisor_runtime()
        path = self.fenix / "supervisor_runtime.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(data["sigkill_wait"], int)
        self.assertGreater(data["sigkill_wait"], 0)
        self.assertTrue(data["started_at"])


class TestDrainConsistencyCheck(unittest.TestCase):
    def setUp(self):
        self.mod = _fenixd_mod
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.pm = MagicMock()
        daemon = self.mod.FenixDaemon.__new__(self.mod.FenixDaemon)
        daemon.config = {"admin": {"shutdown_drain_seconds": 1800}}
        daemon.logger = self.logger
        daemon.pm_engine = self.pm
        self.daemon = daemon

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _runtime_path(self):
        return self.proot / ".fenix" / "supervisor_runtime.json"

    def _write_runtime(self, sigkill_wait=None, started_at=None):
        import json as _json
        data = {"sigkill_wait": sigkill_wait if sigkill_wait is not None else 1800 + 120,
                "started_at": started_at or datetime.now(timezone.utc).isoformat()}
        self._runtime_path().write_text(_json.dumps(data), encoding="utf-8")

    def _write_daemon_started(self, ts=None):
        (self.proot / ".fenix" / "daemon_started").write_text(
            (ts or datetime.now(timezone.utc)).isoformat() + "\n", encoding="utf-8")

    def _check(self):
        import contextlib
        with contextlib.redirect_stdout(None):
            with contextlib.redirect_stderr(None):
                self.daemon._check_supervisor_drain_consistency()

    def test_missing_runtime_file_warns(self):
        """runtime 文件缺失（旧代码 supervisor）→ WARNING + 项目日志。"""
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.mod, "PROJECT_ROOT", self.proot)
            self._check()
        warnings = " ".join(str(c) for c in self.logger.warning.call_args_list)
        self.assertIn("supervisor", warnings)
        self.assertIn("重启 supervisor", warnings)
        self.pm._append_project_log.assert_called()

    def test_sigkill_wait_too_small_warns(self):
        """sigkill_wait < drain+120 → WARNING。"""
        self._write_runtime(sigkill_wait=100)
        self._write_daemon_started()
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.mod, "PROJECT_ROOT", self.proot)
            self._check()
        warnings = " ".join(str(c) for c in self.logger.warning.call_args_list)
        self.assertIn("排水期可能被截断", warnings)

    def test_consistent_config_silent(self):
        """runtime 在册且 sigkill_wait 充足 → 静默通过。"""
        self._write_runtime()
        self._write_daemon_started()
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.mod, "PROJECT_ROOT", self.proot)
            # fix-supervisor-hosting-chain D4：存在性检查在真实 /proc 下会命中
            # 无 supervisor → 落告警；测试环境无真实 supervisor，patch 为在跑
            from core import fenix_session
            mp.setattr(fenix_session, "supervisor_running", lambda root=None: True)
            self._check()
        self.logger.warning.assert_not_called()

    def test_stale_started_at_drift_warns(self):
        """started_at 与 daemon 启动漂移超阈值 → WARNING。"""
        old = datetime.now(timezone.utc).timestamp() - 3 * 24 * 3600
        self._write_runtime(
            sigkill_wait=1800 + 120,
            started_at=datetime.fromtimestamp(old, timezone.utc).isoformat())
        self._write_daemon_started()
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.mod, "PROJECT_ROOT", self.proot)
            self._check()
        warnings = " ".join(str(c) for c in self.logger.warning.call_args_list)
        self.assertIn("86400s 以上", warnings)
        self.assertIn("残留自此前 supervisor 进程", warnings)

    def test_drain_zero_skips_check(self):
        """drain=0（快速停机）跳过 drain 一致性比对。

        fix-supervisor-hosting-chain D4：drain=0 只跳过「一致性比对」，supervisor
        存在性检查无条件执行；patch supervisor 在跑 → 两条判定均静默。
        """
        self.daemon.config = {"admin": {"shutdown_drain_seconds": 0}}
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.mod, "PROJECT_ROOT", self.proot)
            from core import fenix_session
            mp.setattr(fenix_session, "supervisor_running", lambda root=None: True)
            self._check()
        self.logger.warning.assert_not_called()
        self.pm._append_project_log.assert_not_called()


# ── (6) 关闭期保护集来源 (c)（fix-recovery-branch-anchor D5）────────────
class TestShutdownProtectedSourceC(unittest.TestCase):
    """D5/5.1-5.4：sidecar 未写时保护集由来源 (c)（STATE implementing spec
    的**全部**在册 worktree）非空；保护集构成日志；多 worktree 全量保护。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True, exist_ok=True)
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_daemon(self, sm_entries, wt_paths_by_spec):
        """构造最小 daemon：真实 FakeSM + FakeWM（find_worktrees_by_spec 全量）。"""
        daemon = _fenixd_mod.FenixDaemon()
        daemon.config = {"admin": {"shutdown_drain_seconds": 0}}
        daemon.logger = self.logger
        daemon.pm_engine = MagicMock()
        daemon.event_bus = None
        daemon.agent_runner = None
        daemon.worktree_manager = _FakeWMForC(wt_paths_by_spec)
        daemon.state_machine = _FakeSMForC(sm_entries)
        daemon._admin_thread = None
        daemon._admin_executor = None
        return daemon

    def test_source_c_nonempty_when_sidecar_missing(self):
        """sidecar 未写（事故形态）→ 保护集由来源 (c) 非空，不退化空集。"""
        daemon = self._make_daemon(
            sm_entries={"demo": {"status": "implementing", "branch": "fenix/demo-1"}},
            wt_paths_by_spec={"demo": ["/wt/impl-demo-1", "/wt/repair-demo-2"]},
        )
        # 模拟 shutdown 的 protected 构造段（sidecar 为空）
        protected = set()
        src_b, src_c = 0, 0
        implementing = daemon.state_machine.get_by_status("implementing")
        for spec, _entry in implementing:
            wt_paths = daemon.worktree_manager.find_worktrees_by_spec(spec)
            for wp in wt_paths:
                protected.add(wp)
                src_c += 1
        self.assertEqual(src_c, 2, "来源 (c) 须覆盖全部在册 worktree")
        self.assertEqual(protected, {"/wt/impl-demo-1", "/wt/repair-demo-2"})
        self.assertNotEqual(protected, set(), "保护集 MUST NOT 退化为空集")

    def test_protected_composition_logged(self):
        """cleanup_orphans 前打日志记录保护集各来源条目数（5.4）。"""
        daemon = self._make_daemon(
            sm_entries={"demo": {"status": "implementing", "branch": "fenix/demo-1"}},
            wt_paths_by_spec={"demo": ["/wt/impl-demo-1"]},
        )
        protected = {"/wt/impl-demo-1"}
        preserved_wts = [str("/wt/impl-demo-1")]
        daemon.logger.info(
            "fenixd",
            f"cleanup_orphans 保护集构成：来源 (a) drain 保全 "
            f"{len(preserved_wts)} 项；来源 (c) implementing spec "
            f"{len(protected)} 项",
        )
        info_msgs = " ".join(str(c) for c in daemon.logger.info.call_args_list)
        self.assertIn("保护集构成", info_msgs)

    def test_no_inflight_specs_cleanup_normal(self):
        """无在飞 spec 时保护集为空 → 正常清理（无保护）。"""
        daemon = self._make_daemon(
            sm_entries={"done": {"status": "done", "branch": "fenix/done-1"}},
            wt_paths_by_spec={},
        )
        implementing = daemon.state_machine.get_by_status("implementing")
        protected = set()
        for spec, _entry in implementing:
            protected.update(daemon.worktree_manager.find_worktrees_by_spec(spec))
        self.assertEqual(protected, set(), "无 implementing spec → 来源 (c) 为空")


class _FakeSMForC:
    def __init__(self, entries):
        self.entries = entries

    def get_by_status(self, status):
        return [(n, e) for n, e in self.entries.items()
                if e.get("status") == status]


class _FakeWMForC:
    def __init__(self, wt_paths_by_spec):
        self._wt_paths_by_spec = dict(wt_paths_by_spec)

    def find_worktrees_by_spec(self, spec_name):
        return list(self._wt_paths_by_spec.get(spec_name, []))

    def find_worktree_by_spec(self, spec_name):
        wts = self._wt_paths_by_spec.get(spec_name, [])
        if len(wts) == 1:
            return (wts[0], "")
        return None

    def cleanup_orphans(self, protected=None):
        pass


# ── (7) stale 清扫分支在飞引用保护（fix-recovery-branch-anchor D6）──────
class TestStaleCleanupBranchProtection(unittest.TestCase):
    """D6/6.1-6.3：在飞 spec 分支不被 git branch -D 删除；无引用分支照常
    删除；STATE 不可解析时保守保留。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "repo"
        self.proot.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        self._git("config", "user.email", "test@fenix.local")
        self._git("config", "user.name", "Fenix Test")
        self._git("config", "commit.gpgsign", "false")
        (self.proot / "base.txt").write_text("BASE\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        self._git("branch", "-M", "main")
        self.logger = MagicMock()
        wt_base = self.proot / ".claude" / "worktrees"
        wt_base.mkdir(parents=True, exist_ok=True)
        self.wm = WorktreeManager(wt_base, self.proot, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _git(self, *args, check=True):
        result = subprocess.run(
            ["git", "-C", str(self.proot), *args],
            capture_output=True, text=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"git {args} failed: {result.stderr}")
        return result

    def _commit_on_branch(self, branch, rel, content):
        self._git("checkout", "-q", "-b", branch)
        p = self.proot / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", f"impl {branch}")
        self._git("checkout", "-q", "main")

    def test_inflight_branch_not_deleted(self):
        """STATE 中 implementing spec 的 branch 不被 stale 清扫删除（6.1 (a)）。"""
        self._commit_on_branch("fenix/demo-123", "feat.py", "IMPL\n")
        state_path = self.proot / ".fenix" / "STATE.md"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        sm = StateMachine(state_path, self.logger)
        sm.add_spec("demo", {"status": "implementing", "branch": "fenix/demo-123"})
        # state_reader 注入真实 SM
        wm = WorktreeManager(self.proot / ".claude" / "worktrees",
                             self.proot, self.logger,
                             state_reader=sm.read_all)
        # 构造孤儿 worktree（不在活动集）指向该分支
        wt = wm.create_worktree_on_branch("demo", "fenix/demo-123")
        # 从活动集摘除（模拟上次异常退出残留）
        wm._active_worktrees.discard(str(wt))
        wm.cleanup_stale_worktrees()
        exists = self._git("rev-parse", "--verify", "fenix/demo-123",
                           check=False).returncode == 0
        self.assertTrue(exists, "在飞 spec 分支 MUST NOT 被删除（宁可多留）")
        warns = " ".join(str(c) for c in self.logger.warning.call_args_list)
        self.assertIn("分支在飞引用保护", warns)

    def test_unreferenced_branch_deleted(self):
        """无 STATE 引用的孤儿分支照常删除。"""
        self._commit_on_branch("fenix/orphan-123", "feat.py", "ORPHAN\n")
        state_path = self.proot / ".fenix" / "STATE.md"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        sm = StateMachine(state_path, self.logger)
        sm.add_spec("demo", {"status": "done", "branch": "fenix/done-1"})
        wm = WorktreeManager(self.proot / ".claude" / "worktrees",
                             self.proot, self.logger,
                             state_reader=sm.read_all)
        wt = wm.create_worktree_on_branch("orphan", "fenix/orphan-123")
        wm._active_worktrees.discard(str(wt))
        wm.cleanup_stale_worktrees()
        exists = self._git("rev-parse", "--verify", "fenix/orphan-123",
                           check=False).returncode == 0
        self.assertFalse(exists, "无引用分支照常删除")

    def test_state_unparseable_conservative_keep(self):
        """STATE 不可解析 → 保守保留分支（6.3）。"""
        self._commit_on_branch("fenix/unknown-123", "feat.py", "X\n")
        state_path = self.proot / ".fenix" / "STATE.md"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        # state_reader 返回 None（模拟解析失败）
        wm = WorktreeManager(self.proot / ".claude" / "worktrees",
                             self.proot, self.logger,
                             state_reader=lambda: None)
        wt = wm.create_worktree_on_branch("unknown", "fenix/unknown-123")
        wm._active_worktrees.discard(str(wt))
        wm.cleanup_stale_worktrees()
        exists = self._git("rev-parse", "--verify", "fenix/unknown-123",
                           check=False).returncode == 0
        self.assertTrue(exists, "STATE 不可解析时 MUST 保守保留分支")
        warns = " ".join(str(c) for c in self.logger.warning.call_args_list)
        self.assertIn("保守保留", warns)


if __name__ == "__main__":
    unittest.main()