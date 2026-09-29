"""run 生命周期治理（improve-run-lifecycle-governance）测试。

覆盖 tasks 1.1/1.2（锁一致性 D4）：worktree_manager.refresh_locks 进程表重建与
陈锁回收、agent_runner.has_live_attempt 存活探测三例。
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from core.agent_runner import AgentRunner
from core.worktree_manager import (
    PROCESS_SCAN_CACHE_SECONDS,
    STALE_LOCK_IDLE_SECONDS,
    WorktreeManager,
)

from test_agent_runner import FakeLogger


def make_wm(tmp_path: Path, alive=False) -> WorktreeManager:
    """构造 WorktreeManager，进程扫描用注入替身（默认无任何进程存活）。"""
    base = tmp_path / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(
        base, tmp_path, FakeLogger(), process_scanner=lambda spec: alive
    )


def touch_run_stream(tmp_path: Path, spec: str, run_id: str, age: float) -> Path:
    """写入一个 run 流文件并把它的时间戳拨到 age 秒前。"""
    runs = tmp_path / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f"{run_id}.jsonl"
    p.write_text('{"type":"system"}\n', encoding="utf-8")
    ts = time.time() - age
    os.utime(p, (ts, ts))
    return p


def touch_run_stream_tail(tmp_path: Path, spec: str, run_id: str, age: float, lines: list) -> Path:
    """写入一个 run 流文件（自定义行序列）并把时间戳拨到 age 秒前。

    供 fix-orphan-ready-recovery-liveness 末行终态判据用例使用：
    ``lines`` 为 JSON 对象列表，逐行写入（末行即判据对象）。
    """
    runs = tmp_path / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f"{run_id}.jsonl"
    p.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    ts = time.time() - age
    os.utime(p, (ts, ts))
    return p


class TestRefreshLocks:
    """1.1 refresh_locks：进程表重建 + 陈锁回收。"""

    def test_registered_lock_with_live_process_held(self, tmp_path):
        wm = make_wm(tmp_path, alive=True)
        wm._spec_locks.add("s1:implementer")
        assert wm.has_active_worktree("s1") is True
        assert wm.refresh_locks() == []  # 有进程：锁保留
        assert "s1:implementer" in wm._spec_locks

    def test_stale_lock_reclaimed_and_dispatch_allowed(self, tmp_path):
        wm = make_wm(tmp_path, alive=False)
        wm._spec_locks.add("s1:implementer")
        # 流文件早已停止增长（超过判定窗口）
        touch_run_stream(tmp_path, "s1", "impl-s1-1789000100", age=STALE_LOCK_IDLE_SECONDS + 60)
        assert wm.has_active_worktree("s1") is False
        assert "s1:implementer" not in wm._spec_locks  # 陈锁已回收

    def test_registered_lock_with_growing_stream_kept(self, tmp_path):
        """进程扫描未命中但流仍在增长：保守视为持锁，不回收。"""
        wm = make_wm(tmp_path, alive=False)
        wm._spec_locks.add("s1:implementer")
        touch_run_stream(tmp_path, "s1", "impl-s1-1789000100", age=5)
        assert wm.has_active_worktree("s1") is True
        assert "s1:implementer" in wm._spec_locks

    def test_daemon_restart_lock_rebuilt_from_process_table(self, tmp_path):
        """daemon 重启模拟：内存锁丢失但进程表有存活 agent → 视为仍持锁。"""
        wm = make_wm(tmp_path, alive=True)
        wm._spec_locks.clear()  # 重启后内存锁为空
        assert wm.has_active_worktree("s1") is True
        # 重建登记，后续判定回到内存快路径
        assert "s1:implementer" in wm._spec_locks
        assert "s1:verifier" in wm._spec_locks

    def test_daemon_restart_no_process_no_lock(self, tmp_path):
        wm = make_wm(tmp_path, alive=False)
        wm._spec_locks.clear()
        assert wm.has_active_worktree("s1") is False

    def test_refresh_locks_releases_only_stale(self, tmp_path):
        wm = make_wm(tmp_path, alive=False)
        wm._spec_locks.update({"stale:implementer", "live:implementer"})
        touch_run_stream(tmp_path, "stale", "impl-stale-1789000001", age=STALE_LOCK_IDLE_SECONDS + 1)
        touch_run_stream(tmp_path, "live", "impl-live-1789000002", age=1)
        # live spec 的进程扫描命中：换一个按 spec 名区分的替身
        wm._process_scanner = lambda spec: spec == "live"
        released = wm.refresh_locks()
        assert released == ["stale:implementer"]
        assert "stale:implementer" not in wm._spec_locks
        assert "live:implementer" in wm._spec_locks

    def test_refresh_locks_no_locks_noop(self, tmp_path):
        wm = make_wm(tmp_path, alive=False)
        assert wm.refresh_locks() == []

    def test_process_scan_cache_prevents_scanner_storm(self, tmp_path):
        """同一 spec 的扫描在缓存窗口内只发生一次。"""
        calls = []

        def scanner(spec):
            calls.append(spec)
            return False

        wm = make_wm(tmp_path, alive=False)
        wm._process_scanner = scanner
        wm._spec_locks.add("s1:implementer")
        touch_run_stream(tmp_path, "s1", "impl-s1-1789000001", age=STALE_LOCK_IDLE_SECONDS + 1)
        wm.has_active_worktree("s1")
        wm.has_active_worktree("s1")
        assert len(calls) == 1
        assert PROCESS_SCAN_CACHE_SECONDS > 0


class TestHasLiveAttempt:
    """1.2 has_live_attempt：存活子进程 / 已死进程 / 回退路径三例。"""

    def make_runner(self, tmp_path: Path) -> AgentRunner:
        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {}
        runner.worktree_manager = None
        runner.state_machine = None
        runner.project_root = tmp_path
        runner.logger = FakeLogger()
        runner._running_agents = {}
        return runner

    @pytest.mark.parametrize(
        "pgrep_alive, expected",
        [(True, True), (False, False)],
        ids=["live-child-detected", "dead-process-no-stream"],
    )
    def test_pgrep_probe_result(self, tmp_path, pgrep_alive, expected):
        """存活子进程 / 已死进程：pgrep 探针结果直通判定。"""
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: pgrep_alive
        assert runner.has_live_attempt("s1") is expected

    @pytest.mark.parametrize(
        "pgrep_stub, stream_age, expected",
        [
            ("raise", 10, True),    # pgrep 不可用 → 回退新近流文件判存活
            ("false", 600, False),  # pgrep 判死 + 流文件陈旧 → 不存活
        ],
        ids=["recent-stream-fallback", "stale-stream-not-alive"],
    )
    def test_fallback_stream_file(self, tmp_path, pgrep_stub, stream_age, expected):
        """进程扫描回退路径：run 流文件 mtime 判定（窗口 120s）。"""
        runner = self.make_runner(tmp_path)

        if pgrep_stub == "raise":
            def _boom(spec):
                raise OSError("pgrep unavailable")

            runner._pgrep_live_attempt = _boom
        else:
            runner._pgrep_live_attempt = lambda spec: False
        touch_run_stream(tmp_path, "s1", "impl-s1-1789000007", age=stream_age)
        assert runner.has_live_attempt("s1") is expected

    def test_pgrep_matches_worktree_literal(self, tmp_path):
        """pgrep 匹配串锚定 worktree 目录字面量（impl/verify/repair 三前缀）。"""
        seen = []

        class FakeCompleted:
            def __init__(self, rc, out):
                self.returncode = rc
                self.stdout = out
                self.stderr = ""

        def fake_run(cmd, **kwargs):
            seen.append(cmd[cmd.index("-f") + 1])
            return FakeCompleted(1, "")

        runner = self.make_runner(tmp_path)
        import core.agent_runner as ar
        original = ar.subprocess.run
        ar.subprocess.run = fake_run
        try:
            assert runner._liveness._pgrep_live_attempt("s1") is False
        finally:
            ar.subprocess.run = original
        assert seen == [
            "worktrees/impl-s1-",
            "worktrees/verify-s1-",
            "worktrees/repair-s1-",
        ]

    # ── fix-orphan-ready-recovery-liveness 3.1/3.2/3.3 ──────────────

    @pytest.mark.parametrize(
        "tail_line",
        [
            {"type": "result"},
            {"type": "error"},
            {"type": "interrupted"},
            {"type": "cancelled"},
            # 本次事故形态：daemon SIGTERM 后 runner 收口补写的 error 终态行
            {"type": "error", "error": "Exit code: 143", "exit_code": 143},
        ],
        ids=["result", "error", "interrupted", "cancelled", "accident-exit-143"],
    )
    def test_terminal_tail_not_alive(self, tmp_path, tail_line):
        """3.1 末行终态 ⇒ 不存活：mtime 在 120s 窗口内 + 末行终态 + pgrep 判否。

        复现 fix-orphan-ready-recovery-liveness 事故：daemon 主动 SIGTERM 杀掉在飞
        run，runner 补写 error 终态行，重启后首轮恢复不得再把它误判为 live child。
        """
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: False
        touch_run_stream_tail(
            tmp_path, "s1", "impl-s1-1789000008", age=10,
            lines=[
                {"type": "init"},
                {"type": "assistant", "message": {"content": []}},
                tail_line,
            ],
        )
        assert runner.has_live_attempt("s1") is False

    def test_non_terminal_tail_fresh_still_alive(self, tmp_path):
        """3.2 fail-open 方向①：末行为非终态事件（system）且 mtime 新鲜 → 仍存活。"""
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: False
        touch_run_stream_tail(
            tmp_path, "s1", "impl-s1-1789000009", age=10,
            lines=[{"type": "system"}, {"type": "system"}],
        )
        assert runner.has_live_attempt("s1") is True

    def test_corrupt_json_tail_still_alive(self, tmp_path):
        """3.2 fail-open 方向②：末行损坏 JSON → 仍存活（活 run 不被误杀）。"""
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: False
        runs = tmp_path / ".fenix" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        p = runs / "impl-s1-1789000010.jsonl"
        p.write_text('{"type":"init"}\n{{,,broken json\n', encoding="utf-8")
        ts = time.time() - 10
        os.utime(p, (ts, ts))
        assert runner.has_live_attempt("s1") is True

    def test_empty_stream_still_alive(self, tmp_path):
        """3.2 fail-open 方向③：空文件 → 仍存活（活 run 不被误杀）。"""
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: False
        runs = tmp_path / ".fenix" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        p = runs / "impl-s1-1789000011.jsonl"
        p.write_text("", encoding="utf-8")
        ts = time.time() - 10
        os.utime(p, (ts, ts))
        assert runner.has_live_attempt("s1") is True

    def test_superseded_tail_still_alive(self, tmp_path):
        """3.3 superseded 末行 ⇒ 仍存活（design D1：属弃置标记非终结，防双派发）。"""
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: False
        touch_run_stream_tail(
            tmp_path, "s1", "impl-s1-1789000012", age=10,
            lines=[
                {"type": "init"},
                {"type": "superseded", "reason": "artifact-gate in-place retry"},
            ],
        )
        assert runner.has_live_attempt("s1") is True, \
            "superseded 属弃置标记非终结：原地重试弃置旧产物文件，run 在新 sub_run_id 文件继续，判死会致退避窗口内双派发"


# ── 2.1/2.2 派发锁冲突退避 + dispatch_stalled 信号 ────────────────────────────

import unittest
from unittest.mock import MagicMock

from core.pm_engine import PMEngine
from core.state_machine import StateMachine
from core.admin_store import AdminStore


class LockConflictFixture(unittest.TestCase):
    """check_blockers / 派发退避共用 fixture（真实 StateMachine + mock runner）。"""

    def setUp(self):
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md", self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        # 本夹具建模「孤儿/陈锁」场景：锁在册但无存活 attempt（活 run 持锁的
        # 静默跳过语义见 TestDispatchLockLiveAttempt）。
        self.runner.has_live_attempt.return_value = False
        self.config = {}
        self.engine = PMEngine(self.sm, self.runner, self.config,
                               self.project_root, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_ready_spec(self, name="s1"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        return self.sm.read_one(name)


class TestDispatchLockBackoff(LockConflictFixture):
    def test_first_conflict_schedules_backoff_without_retry_cost(self, tmp_path=None):
        self.make_ready_spec("s1")
        self.runner.worktree_manager.has_active_worktree.return_value = True
        self.engine._on_spec_ready("s1")
        entry = self.sm.read_one("s1")
        # spec 保持 ready：不消耗 attempt 配额、不写 retries exhausted
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(int(entry.get("_retry_count", 0) or 0), 0)
        self.assertNotIn("retries exhausted", str(entry.get("error")))
        # error 字段注明下次尝试时间，退避窗口已设置
        self.assertIn("backoff until", entry["error"])
        self.assertGreater(int(entry["_dispatch_backoff_until"]), time.time() - 1)
        self.assertEqual(int(entry["_lock_conflict_count"]), 1)

    def test_conflict_escalates_through_schedule(self):
        self.make_ready_spec("s1")
        self.runner.worktree_manager.has_active_worktree.return_value = True
        delays = []
        self.engine._schedule_backoff_retry = lambda spec, delay: delays.append(delay)
        for expected in (30.0, 120.0, 600.0):
            self.engine._on_spec_ready("s1")
        self.assertEqual(delays, [30.0, 120.0, 600.0])

    def test_exhausted_schedule_emits_dispatch_stalled_once(self):
        self.make_ready_spec("s1")
        self.runner.worktree_manager.has_active_worktree.return_value = True
        self.engine._schedule_backoff_retry = lambda spec, delay: None
        for _ in range(3):  # 用完 [30, 120, 600]
            self.engine._on_spec_ready("s1")
        # 第 4 次：序列耗尽 → 信号
        self.engine._on_spec_ready("s1")
        from core.admin_store import AdminStore
        recs = AdminStore(self.project_root, self.logger).read_all()
        stalled = [r for r in recs if r.get("signal_type") == "dispatch_stalled"]
        self.assertEqual(len(stalled), 1)
        self.assertEqual(stalled[0].get("severity"), "major")
        self.assertEqual(stalled[0].get("spec"), "s1")
        self.assertIn("exhausted", stalled[0].get("evidence") or "")
        # spec 保持 ready 等待处置，而非伪装成任务失败
        self.assertEqual(self.sm.read_one("s1")["status"], "ready")

    def test_signal_dedup_within_cooldown(self):
        self.make_ready_spec("s1")
        self.runner.worktree_manager.has_active_worktree.return_value = True
        self.engine._schedule_backoff_retry = lambda spec, delay: None
        for _ in range(6):  # 两次耗尽循环
            self.engine._on_spec_ready("s1")
        from core.admin_store import AdminStore
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            len([r for r in recs if r.get("signal_type") == "dispatch_stalled"]), 1,
            "冷却期内重复冲突只写一条 dispatch_stalled",
        )

    def test_live_attempt_holding_lock_skips_conflict(self):
        """活 run 持锁 ≠ 冲突：有存活 attempt 时静默跳过，不计退避、不发信号。

        fix-admin-run-blocks-mainloop 事故（2026-09-01）：外部 drafted 写入触发
        spec_ready 二次派发，与活 run 撞锁把退避链重计至耗尽，误报
        dispatch_stalled 并循环呼叫 Administrator。
        """
        self.make_ready_spec("s1")
        self.runner.worktree_manager.has_active_worktree.return_value = True
        self.runner.has_live_attempt.return_value = True
        before = self.sm.read_one("s1")["updated"]
        self.engine._on_spec_ready("s1")
        entry = self.sm.read_one("s1")
        # 不写冲突元数据、不改状态、不触发任何退避计时
        self.assertEqual(entry["status"], "ready")
        self.assertNotIn("_lock_conflict_count", entry)
        self.assertNotIn("_dispatch_backoff_until", entry)
        self.assertEqual(entry["updated"], before)
        self.assertEqual(self.engine._backoff_timers, [])

    def test_backoff_window_suppresses_respin(self):
        """退避期内重复 spec_ready：静默跳过，不追加写 STATE（防自触发热循环）。"""
        self.make_ready_spec("s1")
        self.runner.worktree_manager.has_active_worktree.return_value = False
        spec = self.sm.read_one("s1")
        spec["_dispatch_backoff_until"] = int(time.time()) + 300
        self.sm.write_all({"s1": spec})
        before = self.sm.read_one("s1")["updated"]
        self.engine._on_spec_ready("s1")
        after = self.sm.read_one("s1")["updated"]
        self.assertEqual(before, after)

    def test_success_resets_conflict_count(self):
        self.make_ready_spec("s1")
        spec = self.sm.read_one("s1")
        spec["_lock_conflict_count"] = 2
        spec["_dispatch_backoff_until"] = int(time.time()) + 60
        self.sm.write_all({"s1": spec})
        fields = self.engine._recovery._clear_dispatch_conflict("s1")
        self.sm.update_spec("s1", fields)
        entry = self.sm.read_one("s1")
        self.assertEqual(int(entry["_lock_conflict_count"]), 0)
        self.assertIn(entry["_dispatch_backoff_until"], (None, "", "null"))


# ── 3.1 auto-recovery 一致性 + 5.1/5.2 闭环复查与假就绪巡检 ──────────────────

from datetime import datetime, timedelta, timezone


class RecoveryWatchFixture(LockConflictFixture):
    def _stale(self, name="s1", hours=3):
        # hours=3：stuck 缺省回退阈值 9600s=160min（RUN_TIMEOUT_FALLBACK 9000+600 宽限），
        # 2h 已落入阈值之下，故默认取 3h 保证落在阈值之上
        specs = self.sm.read_all()
        specs[name]["updated"] = (
            datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        self.sm.write_all(specs)

    def watch_due(self, name="s1"):
        watch = dict(self.engine._recovery._recovery_watch)
        watch[name]["due"] = time.time() - 1
        self.engine._recovery._recovery_watch = watch
        self.engine._recovery._save_recovery_watch()


class TestAutoRecoveryLiveChildGuard(RecoveryWatchFixture):
    """3.1 卡死自动恢复前必须核验无存活子进程。"""

    def test_live_child_defers_recovery_and_keeps_tracking(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.update_spec("s1", {"implementer_run": "impl-s1-1"})
        self._stale()
        self.runner.has_live_attempt.return_value = True
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        # 不重置状态、不清空跟踪字段
        self.assertEqual(entry["status"], "implementing")
        self.assertEqual(entry["implementer_run"], "impl-s1-1")
        self.assertIsNone(entry.get("branch", None) if entry.get("branch") else None)
        deferred = any(
            "recovery deferred, live child present" in str(c.args)
            for c in self.logger.warning.call_args_list
        )
        self.assertTrue(deferred)

    def test_no_live_child_recovers_normally(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self._stale()
        self.runner.has_live_attempt.return_value = False
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("Auto-recovered from stuck implementing", entry["error"])
        # 恢复成功 → 登记闭环复查观察项（5.1）
        self.assertIn("s1", self.engine._recovery._recovery_watch)

    def test_probe_non_bool_return_treated_as_absent(self):
        """探针返回非布尔（如未配置的测试替身）→ 保守按无存活，恢复照常。"""
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self._stale()
        self.runner.has_live_attempt.return_value = "yes"  # 非布尔
        self.engine.check_blockers()
        self.assertEqual(self.sm.read_one("s1")["status"], "ready")

    def test_defer_registers_watch_no_deadloop(self):
        """defer 也登记观察项：逾期后复查仍卡死 → 信号而非无限 defer。"""
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self._stale()
        self.runner.has_live_attempt.return_value = True
        self.engine.check_blockers()  # defer #1
        self.engine.check_blockers()  # defer #2（无观察项到期，不重复信号）
        self.assertEqual(
            len([r for r in AdminStore(self.project_root, self.logger).read_all()
                 if r.get("signal_type") == "dispatch_stalled"]), 0)
        self.watch_due()
        self.runner.has_live_attempt.return_value = True
        self.runner.worktree_manager.has_active_worktree.return_value = False
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])  # 观察项到期接管 → 信号，不再 defer


class TestRecoveryWatch(RecoveryWatchFixture):
    """5.1 恢复动作后的闭环复查。"""

    def test_watch_persisted_for_restart(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self._stale()
        self.runner.has_live_attempt.return_value = False
        self.engine.check_blockers()
        path = self.project_root / ".fenix" / "recovery_watch.json"
        self.assertTrue(path.exists())
        # 模拟 daemon 重启：新 engine 实例从磁盘续查
        engine2 = PMEngine(self.sm, self.runner, self.config,
                           self.project_root, self.logger)
        self.assertIn("s1", engine2._recovery_watch)

    def test_watch_passes_when_spec_left_ready(self):
        self.engine.register_recovery_watch("s1", "test")
        self.watch_due()
        self.sm.update_spec("s1", {"status": "implemented"}) if self.sm.read_one("s1") \
            else self.sm.add_spec("s1", {"status": "implemented", "priority": 5})
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)

    def test_watch_passes_when_dispatch_active(self):
        self.make_ready_spec("s1")
        self.engine.register_recovery_watch("s1", "test")
        self.watch_due()
        self.runner.worktree_manager.has_active_worktree.return_value = True
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])

    def test_watch_fails_when_still_fake_ready(self):
        """滞留 ready 且就地派发未成立 → dispatch_stalled 信号（不得静默关闭）。

        post-recovery-patrol D4：观察窗口到达、spec 仍 ready 且无活跃派发时
        先就地重新派发；派发被闸门拦下（本用例内容完整性闸门命中——tmpdir
        无 spec 目录）→ 关闭观察项 + dispatch_stalled。
        """
        self.make_ready_spec("s1")
        self.engine.register_recovery_watch("s1", "test")
        self.watch_due()
        self.runner.worktree_manager.has_active_worktree.return_value = False
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        recs = AdminStore(self.project_root, self.logger).read_all()
        stalled = [r for r in recs if r.get("signal_type") == "dispatch_stalled"]
        self.assertEqual(len(stalled), 1)
        self.assertIn("recovery", stalled[0].get("evidence"))
        # 观察项已关闭（不再是挂起复查，交给 signal 通道处置）
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)

    def test_watch_registered_implementing_rolled_back_to_ready_redispatches(self):
        """登记时 implementing、窗口内回退 ready：判未恢复 → 就地派发成立 → 关闭不告警。

        复现 2026-09-12 fix-root-init-import-shadow 事故形态：旧实现以
        status != status_at_register（implementing→ready）误判「已恢复推进」并
        静默关闭观察项。post-recovery-patrol 收紧判据后按声明语义判为尚未恢复
        推进，先就地重新派发；派发成立 → 关闭观察项且不产生任何告警。
        """
        # 登记时 implementing（defer 卡死形态；live child 存活）
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.engine.register_recovery_watch(
            "s1", "auto-recovery deferred (live child present)")
        self.assertEqual(
            self.engine._recovery._recovery_watch["s1"]["status_at_register"],
            "implementing",
        )
        self.watch_due()
        # 窗口内因中断回退为 ready 且无活跃派发（live child 已死）
        self.sm.update_spec("s1", {"status": "ready"})
        self.runner.worktree_manager.has_active_worktree.return_value = False
        # 让就地派发真正成立：闸门放行（本夹具无 spec 目录，内容闸门默认会拦）
        self.engine._check_impl_budget_exhausted = MagicMock(return_value=False)
        self.engine._check_spec_content_missing = MagicMock(return_value=False)
        # 队列处理 mock 掉，避免 worker 线程异步副作用干扰断言（入队即成立）
        self.engine._process_queue = MagicMock()

        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        # 观察项关闭且不产生任何告警
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"], [])
        # 就地派发成立：spec 已入队
        self.assertTrue(any(
            (e[1], e[2]) == ("s1", "implementer")
            for e in self.engine._dispatcher._run_queue
        ))

    def test_watch_inplace_dispatch_blocked_by_budget_signals(self):
        """就地派发被预算闸门拦下 → 关闭观察项并发出 dispatch_stalled（不得静默关闭）。"""
        self.make_ready_spec("s1")
        self.engine.register_recovery_watch("s1", "test")
        self.watch_due()
        self.runner.worktree_manager.has_active_worktree.return_value = False
        self.engine._check_impl_budget_exhausted = MagicMock(return_value=True)

        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)
        recs = AdminStore(self.project_root, self.logger).read_all()
        stalled = [r for r in recs if r.get("signal_type") == "dispatch_stalled"]
        self.assertEqual(len(stalled), 1)
        # 未被静默丢弃：dispatch_stalled 信号带证据
        self.assertIn("recovery", stalled[0].get("evidence"))
        # 预算拦截前提下不得入队
        self.assertFalse(any(
            (e[1], e[2]) == ("s1", "implementer")
            for e in self.engine._dispatcher._run_queue
        ))


class TestReadyStallPatrol(RecoveryWatchFixture):
    """5.2 假就绪巡检 + 信号指纹去重。"""

    def test_ready_stall_beyond_threshold_reported(self):
        self.make_ready_spec("s1")
        self._stale(hours=1)  # ready 滞留 60 分钟 > 20 分钟阈值
        self.runner.worktree_manager.has_active_worktree.return_value = False
        result = self.engine.check_blockers()
        stalled = [b for b in result["blockers"] if b["spec"] == "s1"]
        self.assertEqual(len(stalled), 1)
        self.assertIn("假就绪滞留", stalled[0]["reason"])
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertTrue(
            any(r.get("signal_type") == "dispatch_stalled" for r in recs))

    def test_fresh_ready_not_reported(self):
        self.make_ready_spec("s1")
        result = self.engine.check_blockers()
        self.assertEqual([b for b in result["blockers"]], [])

    def test_backoffed_ready_not_reported(self):
        """退避期内的 spec 是有意等待，不算假就绪滞留。"""
        self.make_ready_spec("s1")
        self.sm.update_spec("s1", {
            "_dispatch_backoff_until": int(time.time()) + 300})
        self._stale(hours=1)
        result = self.engine.check_blockers()
        self.assertEqual([b for b in result["blockers"] if b["spec"] == "s1"], [])

    def test_start_after_pending_ready_not_reported(self):
        """start_after 定时拾取门未到期的 ready spec 是有意等待，不算假就绪滞留。

        回归：2026-09-11 add-main-tree-deps-provision 被误报 dispatch_stalled——
        daemon 每轮按 start_after_pending 正确 skip 派发，但假就绪巡检未豁免
        start_after 未到期的 spec，30 分钟即被误判滞留并呼叫 Administrator。
        """
        self.make_ready_spec("s1")
        self.sm.update_spec("s1", {
            "start_after": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()})
        self._stale(hours=1)
        self.runner.worktree_manager.has_active_worktree.return_value = False
        result = self.engine.check_blockers()
        self.assertEqual([b for b in result["blockers"] if b["spec"] == "s1"], [])
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"], [])

    def test_expired_start_after_still_reported(self):
        """start_after 已到期（等于/早于 now 不阻塞拾取）→ 照常巡检不豁免。"""
        self.make_ready_spec("s1")
        self.sm.update_spec("s1", {
            "start_after": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()})
        self._stale(hours=1)
        result = self.engine.check_blockers()
        stalled = [b for b in result["blockers"] if b["spec"] == "s1"]
        self.assertEqual(len(stalled), 1)
        self.assertIn("假就绪滞留", stalled[0]["reason"])

    def test_dependency_pending_ready_not_reported(self):
        """依赖未满足的 ready spec 是有意等待，不算假就绪滞留。

        回归：2026-09-17 refactor-facade-delegation 被误报 dispatch_stalled——
        depends_on 的两条依赖（refactor-giant-classes / refactor-long-functions）
        仍在 implementing 且活 run 在跑，daemon 每轮 dispatch 已按
        _dependencies_satisfied 正确 skip、等待事件定向唤醒；但假就绪巡检未豁免
        依赖未满足的 spec，21 分钟即被判滞留，信号文案还固定述为「worktree 锁
        冲突 / 退避计划耗尽」（该 spec 从未获得过 worktree 锁，属误述）。
        """
        self.make_ready_spec("s1")
        self.sm.add_spec("dep-x", {"status": "implementing", "priority": 5})
        self.sm.update_spec("s1", {"depends_on": "dep-x"})
        self._stale(hours=1)
        self.runner.worktree_manager.has_active_worktree.return_value = False
        result = self.engine.check_blockers()
        self.assertEqual([b for b in result["blockers"] if b["spec"] == "s1"], [])
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"], [])

    def test_satisfied_dependency_still_reported(self):
        """依赖已到接受态 → 不豁免，照常巡检（豁免只覆盖真正在等待的 spec）。"""
        self.make_ready_spec("s1")
        self.sm.add_spec("dep-x", {"status": "pushed", "priority": 5})
        self.sm.update_spec("s1", {"depends_on": "dep-x"})
        self._stale(hours=1)
        result = self.engine.check_blockers()
        stalled = [b for b in result["blockers"] if b["spec"] == "s1"]
        self.assertEqual(len(stalled), 1)
        self.assertIn("假就绪滞留", stalled[0]["reason"])

    def test_no_dependency_ready_still_reported(self):
        """无依赖的 ready 滞留照常上报（豁免不得泛化为「所有 ready 都不报」）。"""
        self.make_ready_spec("s1")
        self._stale(hours=1)
        result = self.engine.check_blockers()
        self.assertEqual(
            len([b for b in result["blockers"] if b["spec"] == "s1"]), 1)

    def test_queued_ready_not_reported(self):
        """已入队等待派发的 ready spec 不算假就绪滞留（派发已成立，仅未起 run）。

        回归：2026-09-17 18:25 一批 start_after 到点的 P5 spec 被误报——
        `_spec_has_recent_run_activity` 以 run 流文件 mtime 为「派发活动」代理，
        看不见「已入队、正等并发槽/优先级窗口」的等待：老化开窗最坏
        initial+floor×step = 10+4×10 = 50 分钟（本项目配置），远长于 20 分钟
        巡检阈值。实证：8 条 P5 spec 18:00:33 入队、18:50:59 才获派发（实耗
        50.4 分钟），18:25 巡检即判滞留并呼唤 Administrator；其中两条随后正常
        起 run，证明派发链路健康。
        """
        self.make_ready_spec("s1")
        self._stale(hours=1)
        self.runner.worktree_manager.has_active_worktree.return_value = False
        entry = (5, "s1", "implementer", time.time() - 60)
        with self.engine._queue_lock:
            self.engine._run_queue.append(entry)
        result = self.engine.check_blockers()
        self.assertEqual([b for b in result["blockers"] if b["spec"] == "s1"], [])
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"], [])

    def test_dequeued_still_reported(self):
        """队列里没有该 spec 的条目 → 不豁免，照常上报（豁免只覆盖在队条目）。"""
        self.make_ready_spec("s1")
        self._stale(hours=1)
        self.runner.worktree_manager.has_active_worktree.return_value = False
        # 队列里有别人（或空）——s1 不在其中
        with self.engine._queue_lock:
            self.engine._run_queue.append((5, "other", "implementer", time.time()))
        result = self.engine.check_blockers()
        stalled = [b for b in result["blockers"] if b["spec"] == "s1"]
        self.assertEqual(len(stalled), 1)
        self.assertIn("假就绪滞留", stalled[0]["reason"])

    def test_recent_run_activity_not_reported(self):
        self.make_ready_spec("s1")
        self._stale(hours=1)
        touch_run_stream(self.project_root, "s1", "impl-s1-1789000001", age=60)
        result = self.engine.check_blockers()
        self.assertEqual([b for b in result["blockers"] if b["spec"] == "s1"], [])

    def test_live_child_ready_not_reported(self):
        """有存活 attempt 的 ready spec 不算假就绪（2026-09-06 事故回归）。

        daemon 重启把 implementing 恢复为 ready 后，旧 run 流写侧已随旧进程
        死亡（流 mtime 陈旧），但子进程仍持锁干活——流活动代理失真时，
        存活探测必须兜住，否则活 run 被误报 dispatch_stalled 循环呼叫 admin。
        """
        self.make_ready_spec("s1")
        self._stale(hours=1)
        self.runner.has_live_attempt.return_value = True
        result = self.engine.check_blockers()
        self.assertEqual([b for b in result["blockers"] if b["spec"] == "s1"], [])
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"], [])

    def test_same_fingerprint_not_re_signaled_within_cooldown(self):
        """冷却期内反复检出同一滞留：只有首次拉起，后续仅日志。"""
        self.make_ready_spec("s1")
        self._stale(hours=1)
        self.engine.check_blockers()
        self.engine.check_blockers()
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            len([r for r in recs if r.get("signal_type") == "dispatch_stalled"]), 1)


class TestAdminMonitorContinuesWithoutInProgress(unittest.TestCase):
    """5.2 「无 in-progress SPEC」不得提前返回、跳过非运行态巡检。"""

    def setUp(self):
        from core.admin_monitor import AdminMonitor
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        (self.tmpdir / ".fenix").mkdir(exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", self.logger)
        self.monitor = AdminMonitor(
            {"admin": {"enabled": True, "interval_minutes": 5,
                       "escalation_cooldown_minutes": 15}},
            self.sm, self.tmpdir, self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_blocked_stuck_detected_without_in_progress(self):
        # 只有 blocked spec，无任何 in-progress
        self.sm.write_all({"b1": {
            "status": "blocked", "priority": 5,
            "updated": (datetime.now(timezone.utc)
                        - timedelta(hours=3)).isoformat(),
        }})
        signals = self.monitor.run_once()
        self.assertTrue(
            any(s.get("signal_type") == "blocked_stuck" for s in signals),
            "无 in-progress 时仍须执行非运行态巡检",
        )

    def test_stored_dispatch_stalled_signal_ingested(self):
        """pm_engine 写入 store 的 dispatch_stalled 由监视器摄取唤起。"""
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self.tmpdir, self.logger)
        rec = store.append({
            "kind": SIGNAL, "signal_type": "dispatch_stalled",
            "spec": "s1", "severity": "major",
            "description": "stalled", "evidence": "ev",
        })
        self.sm.write_all({})
        self.monitor._invoke_administrator = MagicMock()
        signals = self.monitor.run_once()
        self.assertTrue(
            any(s.get("signal_type") == "dispatch_stalled" for s in signals))
        self.monitor._invoke_administrator.assert_called_once()
        # 已 escalated 的记录不重复唤起
        self.monitor._invoke_administrator.reset_mock()
        self.monitor.run_once()
        self.monitor._invoke_administrator.assert_not_called()


# ── 3.2 超时续期基准 + 4.1–4.3 超时活性监督 ──────────────────────────────────

import core.agent_runner as agent_runner_module


def bare_runner(tmp_path: Path) -> AgentRunner:
    """构造带续期基准注册表的最小 AgentRunner（不跑真实 CLI）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = tmp_path
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._liveness._extension_baselines = {}
    return runner


def make_run_file(tmp_path: Path, run_id: str, lines: list) -> Path:
    runs = tmp_path / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f"{run_id}.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class TestExtensionBaseline(unittest.TestCase):
    """3.2 续期基准登记 / 读取 / run 结束自清理。"""

    def setUp(self):
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        self.runner = bare_runner(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_note_sets_baseline(self):
        make_run_file(self.tmpdir, "impl-s1-1-a1", ['{"type":"system"}'])
        before = time.time()
        self.runner.note_run_extension("s1", "impl-s1-1-a1", 1, before + 1800)
        baseline = self.runner.get_extension_baseline("s1")
        self.assertIsNotNone(baseline)
        self.assertGreaterEqual(baseline, before - 1)

    def test_no_entry_returns_none(self):
        self.assertIsNone(self.runner.get_extension_baseline("s1"))

    def test_stale_run_stream_invalidates_entry(self):
        """run 流停止增长（run 已结束）→ 基准失效并移除，回退 updated 起点。"""
        p = make_run_file(self.tmpdir, "impl-s1-1-a1", ['{"type":"system"}'])
        self.runner.note_run_extension("s1", "impl-s1-1-a1", 1, time.time() + 1800)
        self.assertIsNotNone(self.runner.get_extension_baseline("s1"))
        old = time.time() - agent_runner_module.LIVE_ATTEMPT_STREAM_WINDOW_SECONDS - 60
        os.utime(p, (old, old))
        self.assertIsNone(self.runner.get_extension_baseline("s1"))
        self.assertNotIn("s1", self.runner._liveness._extension_baselines)

    def test_missing_run_stream_invalidates_entry(self):
        self.runner.note_run_extension("s1", "impl-s1-404-a1", 1, time.time())
        self.assertIsNone(self.runner.get_extension_baseline("s1"))


class TestPmEngineUsesExtensionBaseline(RecoveryWatchFixture):
    """3.2 pm_engine stuck 计算读续期基准；无条目时行为与现状一致。"""

    def make_stale_implementing(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self._stale(hours=3)  # 须落在 stuck 缺省回退阈值 160min 之上
        self.runner.has_live_attempt.return_value = False

    def test_fresh_baseline_suppresses_stuck_blocker(self):
        self.make_stale_implementing()
        # 刚续期 5 分钟：虽然 updated 已 2 小时前，也不得判 stuck
        self.runner.get_extension_baseline = MagicMock(
            return_value=time.time() - 300)
        result = self.engine.check_blockers()
        self.assertEqual(
            [b for b in result["blockers"] if b["spec"] == "s1"], [])
        self.assertEqual(self.sm.read_one("s1")["status"], "implementing")

    def test_no_baseline_keeps_updated_based_detection(self):
        self.make_stale_implementing()
        self.runner.get_extension_baseline = MagicMock(return_value=None)
        result = self.engine.check_blockers()
        stuck = [b for b in result["blockers"] if b["spec"] == "s1"]
        self.assertEqual(len(stuck), 1)
        self.assertGreaterEqual(stuck[0]["elapsed_minutes"], 170)

    def test_baseline_probe_exception_falls_back(self):
        """基准探针异常/返回非数值 → 回退 updated 计算，不抛出。"""
        self.make_stale_implementing()
        self.runner.get_extension_baseline = MagicMock(
            side_effect=RuntimeError("boom"))
        result = self.engine.check_blockers()
        self.assertEqual(len(
            [b for b in result["blockers"] if b["spec"] == "s1"]), 1)


class TestLivenessSnapshot(unittest.TestCase):
    """4.1 run jsonl 活性快照：空窗口 / 高活动 / 循环重复 三类。"""

    def setUp(self):
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        self.runner = bare_runner(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_window_zero_events(self):
        p = make_run_file(self.tmpdir, "impl-s1-1-a1",
                          [f'{{"type":"assistant","timestamp":"{iso(time.time()-3600)}"}}'])
        snap = self.runner._liveness._liveness_snapshot(p, 600)
        self.assertEqual(snap["events_in_window"], 0)
        self.assertGreater(snap["last_event_age"], 600)
        self.assertEqual(snap["tool_use"], 0)

    def test_high_activity_counts_tools(self):
        now = time.time()
        lines = [
            f'{{"type":"system","timestamp":"{iso(now-10)}"}}',
            json.dumps({"type": "assistant", "timestamp": iso(now - 8),
                        "message": {"content": [
                            {"type": "tool_use", "name": "Edit"},
                            {"type": "text", "text": "editing file"},
                        ]}}),
            json.dumps({"type": "assistant", "timestamp": iso(now - 5),
                        "message": {"content": [
                            {"type": "tool_use", "name": "Bash"},
                        ]}}),
        ]
        p = make_run_file(self.tmpdir, "impl-s1-2-a1", lines)
        snap = self.runner._liveness._liveness_snapshot(p, 600)
        self.assertEqual(snap["events_in_window"], 2)
        self.assertEqual(snap["tool_use"], 2)
        self.assertEqual(snap["tool_counts"], {"Edit": 1, "Bash": 1})
        self.assertLessEqual(snap["last_event_age"], 6)
        self.assertEqual(snap["last_output"], "editing file")

    def test_repeated_tool_calls_aggregated(self):
        now = time.time()
        lines = [
            json.dumps({"type": "assistant", "timestamp": iso(now - i),
                        "message": {"content": [
                            {"type": "tool_use", "name": "Bash"}]}})
            for i in range(5)
        ]
        p = make_run_file(self.tmpdir, "impl-s1-3-a1", lines)
        snap = self.runner._liveness._liveness_snapshot(p, 600)
        self.assertEqual(snap["tool_use"], 5)
        self.assertEqual(snap["tool_counts"], {"Bash": 5})

    def test_missing_timestamps_fall_back_to_mtime(self):
        p = make_run_file(self.tmpdir, "impl-s1-4-a1", ['{"type":"stderr"}'])
        snap = self.runner._liveness._liveness_snapshot(p, 600)
        self.assertIsNotNone(snap["last_event_age"])
        self.assertLess(snap["last_event_age"], 600)
        self.assertEqual(snap["events_in_window"], 0)

    def test_missing_stream_reports_unavailable(self):
        snap = self.runner._liveness._liveness_snapshot(
            self.tmpdir / "nope" / "missing.jsonl", 600)
        self.assertFalse(snap["stream_available"])
        self.assertEqual(snap["events_in_window"], 0)


class TestJudgeLiveness(unittest.TestCase):
    """4.2 轻量 LLM 判定：可解析 → verdict；解析失败/异常 → stagnant + 证据。"""

    def setUp(self):
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        self.runner = bare_runner(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parseable_output_returns_verdict(self):
        # judge 子进程原语已由 subprocess.run 换为 Popen+communicate
        # （item d916fd3aa78b：进程组启动防超时孤儿），打桩点同步换到
        # subprocess.Popen——仍打桩 run 会放行真实 claude -p 致用例挂死。
        class FakeProc:
            def __init__(self, stdout):
                self._stdout = stdout
                self.returncode = 0
                self.pid = 2 ** 24  # 假 pid：killpg 清场路径（仅超时分支）不可达

            def communicate(self, input=None, timeout=None):
                return self._stdout, ""

        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(cmd)
            return FakeProc(json.dumps({"result":
                             '{"verdict": "advancing", "evidence": "files edited"}'}))

        original = agent_runner_module.subprocess.Popen
        agent_runner_module.subprocess.Popen = fake_popen
        try:
            verdict = self.runner._liveness._judge_liveness({}, "s1", "impl-s1-1-a1")
        finally:
            agent_runner_module.subprocess.Popen = original
        self.assertEqual(verdict["verdict"], "advancing")
        self.assertEqual(verdict["evidence"], "files edited")
        self.assertEqual(calls[0][0], "claude")
        self.assertEqual(calls[0][1], "-p")

    def test_unparseable_output_is_stagnant_with_marker(self):
        class FakeProc:
            def __init__(self):
                self.returncode = 0
                self.pid = 2 ** 24

            def communicate(self, input=None, timeout=None):
                return "完全无关的自然语言输出，没有 JSON", ""

        original = agent_runner_module.subprocess.Popen
        agent_runner_module.subprocess.Popen = lambda cmd, **kw: FakeProc()
        try:
            verdict = self.runner._judge_liveness({}, "s1", "r1")
        finally:
            agent_runner_module.subprocess.Popen = original
        self.assertEqual(verdict["verdict"], "stagnant")
        self.assertIn("liveness judge unavailable", verdict["evidence"])

    def test_exception_is_stagnant_with_marker(self):
        def _boom(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 120)

        original = agent_runner_module.subprocess.Popen
        agent_runner_module.subprocess.Popen = _boom
        try:
            verdict = self.runner._judge_liveness({}, "s1", "r1")
        finally:
            agent_runner_module.subprocess.Popen = original
        self.assertEqual(verdict["verdict"], "stagnant")
        self.assertIn("liveness judge unavailable", verdict["evidence"])


class TestSupervisionDeadlineAction(unittest.TestCase):
    """4.3 封顶决策矩阵：disabled / 绝对上限 / 次数上限 / 零事件 / 续期 / 停滞。"""

    def setUp(self):
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        self.runner = bare_runner(self.tmpdir)
        self.run_file = make_run_file(
            self.tmpdir, "impl-s1-1-a1",
            [json.dumps({"type": "assistant",
                         "timestamp": iso(time.time() - 30),
                         "message": {"content": [
                             {"type": "tool_use", "name": "Edit"}]}})])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def decision(self, extensions=0, started_ago=7200, judge=None):
        return self.runner._supervision_deadline_action(
            self.run_file, "s1", "impl-s1-1-a1",
            time.time() - started_ago, extensions, judge=judge)

    def test_disabled_is_pure_wall_clock_kill(self):
        self.runner.config = {
            "agents": {"timeout_supervision": {"enabled": False}}}
        d = self.decision()
        self.assertEqual(d["action"], "kill")
        self.assertIn("supervision disabled", d["reason"])

    def test_absolute_cap_terminates_unconditionally(self):
        self.runner.config = {
            "agents": {"timeout_supervision": {
                "absolute_max_seconds": 7200, "max_extensions": 2}}}
        # run_timeout 缺省回退 9000 后，absolute_max 地板 = 9000 + 2×1800 = 12600，
        # started_ago 须越过地板才触发无条件终止
        d = self.decision(extensions=0, started_ago=14000)
        self.assertEqual(d["action"], "kill")
        self.assertIn("absolute_max_seconds", d["reason"])

    def test_extension_budget_exhausted_terminates(self):
        d = self.decision(extensions=2, started_ago=6000)
        self.assertEqual(d["action"], "kill")
        self.assertIn("extension budget exhausted", d["reason"])

    def test_zero_events_in_window_kills_without_llm(self):
        # 窗口内零事件：最后事件时间戳远早于 judge_window
        make_run_file(
            self.tmpdir, "impl-s1-1-a1",
            [json.dumps({"type": "assistant",
                         "timestamp": iso(time.time() - 3600)})])
        judge = MagicMock(side_effect=AssertionError("judge must not be called"))
        d = self.decision(extensions=0, started_ago=3700, judge=judge)
        self.assertEqual(d["action"], "kill")
        self.assertIn("zero substantive run events", d["reason"])
        judge.assert_not_called()

    def test_advancing_verdict_extends(self):
        judge = MagicMock(return_value={
            "verdict": "advancing", "evidence": "still editing"})
        d = self.decision(extensions=0, started_ago=3700, judge=judge)
        self.assertEqual(d["action"], "extend")
        self.assertEqual(d["extension_index"], 1)
        self.assertEqual(d["extension_seconds"], 1800)
        self.assertEqual(d["evidence"], "still editing")

    def test_stagnant_verdict_terminates_with_evidence(self):
        judge = MagicMock(return_value={
            "verdict": "stagnant", "evidence": "same bash call looped"})
        d = self.decision(extensions=0, started_ago=3700, judge=judge)
        self.assertEqual(d["action"], "kill")
        self.assertEqual(d["reason"], "judged stagnant")
        self.assertEqual(d["evidence"], "same bash call looped")

    # test_absolute_max_raised_to_cover_extension_budget 已并入
    # test_run_lifecycle_hardening.py::TestSupervisionAbsoluteMaxFloor（floor
    # 派生三分支并组，2026-09-07 审查）。

    def test_defaults_enable_supervision(self):
        sup = self.runner._supervision_settings()
        self.assertTrue(sup["enabled"])
        self.assertEqual(sup["max_extensions"], 2)
        self.assertEqual(sup["extension_seconds"], 1800)
        self.assertEqual(sup["judge_window"], 600)

    def test_legacy_top_level_key_fallback(self):
        self.runner.config = {"timeout_supervision": {"enabled": False}}
        self.assertFalse(self.runner._supervision_settings()["enabled"])


# ── fix-orphan-ready-recovery-liveness 3.11 去重有界性 ────────────────────


class TestRecoverOrphanReadyDedupBoundedness(unittest.TestCase):
    """3.11：recover_orphan_ready 重复触发不导致 _run_queue 膨胀。

    锁定 design D4 的真实吸收点：_enqueue 按 (spec, agent_type) 去重，
    已入队等待并发槽的 SPEC 不会被 60 秒重试重复入队。防后续有人删掉
    _enqueue 去重后误以为冷却已兜住。
    """

    def setUp(self):
        self.tmpdir = Path(__import__("tempfile").mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md", self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        self.runner.has_live_attempt.return_value = False
        self.config = {}
        self.engine = PMEngine(self.sm, self.runner, self.config,
                               self.project_root, self.logger)
        self.engine._process_queue = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dedup_absorbs_repeated_triggers(self):
        """ready SPEC 已在 _run_queue 中 → 重复 recover_orphan_ready →
        _run_queue 中 (spec, "implementer") 条目数恒为 1。"""
        from core.event_bus import EventBus

        # 写入 STATE.md 一个 ready 态孤儿 SPEC
        self.sm.add_spec("s1", {"status": "ready", "error": "dispatch stalled"})
        # 手动预入队（模拟已在等待并发槽）
        self.engine._run_queue.append((5, "s1", "implementer", time.time()))
        bus = EventBus(self.sm.state_path, self.sm, self.engine, {}, self.logger)

        for _ in range(3):
            # 每轮清除冷却，确保 _on_spec_ready 能到达 _enqueue（不被 cooldown 吞掉）
            self.engine._last_dispatch_at.pop("s1", None)
            bus.recover_orphan_ready()

        entries = [(e[1], e[2]) for e in self.engine._run_queue]
        self.assertEqual(
            entries.count(("s1", "implementer")),
            1,
            "60秒间隔重复触发的入队请求应被 _enqueue 的 (spec, agent_type) 去重吸收",
        )


