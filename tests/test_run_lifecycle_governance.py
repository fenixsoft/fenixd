"""run 生命周期治理（improve-run-lifecycle-governance）测试。

覆盖 tasks 1.1/1.2（锁一致性 D4）：worktree_manager.refresh_locks 进程表重建与
陈锁回收、agent_runner.has_live_attempt 存活探测三例。
"""

import os
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
        touch_run_stream(tmp_path, "s1", "impl-s1-100", age=STALE_LOCK_IDLE_SECONDS + 60)
        assert wm.has_active_worktree("s1") is False
        assert "s1:implementer" not in wm._spec_locks  # 陈锁已回收

    def test_registered_lock_with_growing_stream_kept(self, tmp_path):
        """进程扫描未命中但流仍在增长：保守视为持锁，不回收。"""
        wm = make_wm(tmp_path, alive=False)
        wm._spec_locks.add("s1:implementer")
        touch_run_stream(tmp_path, "s1", "impl-s1-100", age=5)
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
        touch_run_stream(tmp_path, "stale", "impl-stale-1", age=STALE_LOCK_IDLE_SECONDS + 1)
        touch_run_stream(tmp_path, "live", "impl-live-1", age=1)
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
        touch_run_stream(tmp_path, "s1", "impl-s1-1", age=STALE_LOCK_IDLE_SECONDS + 1)
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

    def test_live_child_process_detected(self, tmp_path):
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: True
        assert runner.has_live_attempt("s1") is True

    def test_dead_process_no_stream(self, tmp_path):
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: False
        assert runner.has_live_attempt("s1") is False

    def test_fallback_recent_stream_file(self, tmp_path):
        """进程扫描不可用（pgrep 失败）→ 回退 run 流文件 mtime < 120s。"""
        runner = self.make_runner(tmp_path)

        def _boom(spec):
            raise OSError("pgrep unavailable")

        runner._pgrep_live_attempt = _boom
        touch_run_stream(tmp_path, "s1", "impl-s1-7", age=10)
        assert runner.has_live_attempt("s1") is True

    def test_fallback_old_stream_file_not_alive(self, tmp_path):
        runner = self.make_runner(tmp_path)
        runner._pgrep_live_attempt = lambda spec: False
        touch_run_stream(tmp_path, "s1", "impl-s1-7", age=600)
        assert runner.has_live_attempt("s1") is False

    def test_pgrep_matches_worktree_literal(self, tmp_path):
        """pgrep 匹配串锚定 worktree 目录字面量（impl/verify 两前缀）。"""
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
            assert runner._pgrep_live_attempt("s1") is False
        finally:
            ar.subprocess.run = original
        assert seen == ["worktrees/impl-s1-", "worktrees/verify-s1-"]
