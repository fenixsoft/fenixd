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
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, SpecStatus
from core.agent_runner.liveness import (
    RUN_TERMINAL_EVENT_TYPES,
    sweep_runs_without_terminal_state,
)


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
        """任一终态事件（result/interrupted/error/cancelled）均不补写。"""
        samples = {
            "a-result": [{"type": "assistant"}, {"type": "result", "result": "ok"}],
            "b-interrupted": [{"type": "assistant"}, {"type": "interrupted", "reason": "shutdown"}],
            "c-error": [{"type": "assistant"}, {"type": "error", "error": "boom", "exit_code": 1}],
            "d-cancelled": [{"type": "assistant"}, {"type": "cancelled", "reason": "user"}],
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

        def fake_git_push(ref, *a, **k):
            push_calls.append(ref)
            time.sleep(0.3)  # 放大临界区窗口，强制并发第二流撞锁
            return True, ""

        self.engine._git_push_ref = fake_git_push
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(self.engine.approve_push, "spec-a") for _ in range(2)]
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

        def fake_git_push(ref, *a, **k):
            push_calls.append((ref,))
            time.sleep(0.3)
            return True, ""

        self.engine._git_push_ref = fake_git_push
        self.engine._resolve_push_branch = MagicMock(
            side_effect=lambda name, spec: f"fenix/{name}")
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(self.engine.approve_push, n) for n in ("spec-a", "spec-b")]
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
        # 隔离与 D6 正交的各闸门
        self.engine._read_verify_report = MagicMock(return_value={})
        self.engine._handle_env_blocked_inconclusive = MagicMock(return_value=False)
        self.engine._verifier_result_is_stale = MagicMock(return_value=False)
        self.engine._judge_bugs_declare_env = MagicMock(return_value=False)
        self.engine._ensure_verification_report = MagicMock(return_value=None)
        self.engine._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._check_verification_gate = MagicMock(return_value=None)
        self.engine._verify_verdict_evidence = MagicMock(return_value=True)
        self.result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_testing_spec(self, name="legacy-spec"):
        self.sm.add_spec(name, {"priority": 5})
        _push_spec_to(self.sm, name, "testing")

    def _write_result(self, spec, status):
        self.result_path.write_text(json.dumps({"spec": spec, "status": status}))

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

    def test_write_supervisor_runtime_reports_sigkill_wait(self):
        """supervisor 启动写 runtime 文件：sigkill_wait 与配置计算值一致。"""
        (self.fenix / "config.yaml").write_text(
            "admin:\n  shutdown_drain_seconds: 1800\n", encoding="utf-8")
        self.sup._write_supervisor_runtime()
        path = self.fenix / "supervisor_runtime.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["sigkill_wait"], 1800 + 120)
        self.assertTrue(data["started_at"])

    def test_write_supervisor_runtime_drain_zero_falls_back(self):
        """drain=0 → sigkill_wait 回退 60。"""
        self.sup._write_supervisor_runtime()
        data = json.loads((self.fenix / "supervisor_runtime.json").read_text())
        self.assertEqual(data["sigkill_wait"], 60)


class TestDrainConsistencyCheck(unittest.TestCase):
    def setUp(self):
        import fenixd as _fenixd_mod
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
        """drain=0（快速停机）不比对。"""
        self.daemon.config = {"admin": {"shutdown_drain_seconds": 0}}
        import pytest
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(self.mod, "PROJECT_ROOT", self.proot)
            self._check()
        self.logger.warning.assert_not_called()
        self.pm._append_project_log.assert_not_called()


if __name__ == "__main__":
    unittest.main()