"""
tests/test_recovery_watch_transition_guard.py — evo-recovery-watch-transition-guard 测试。

3.1 过渡窗口不误报 + 3.2 真实 stale 仍报 + 3.3 三态断言 + 前缀歧义守卫 + 有界性
"""

import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.pm_engine import PMEngine
from core.state_machine import StateMachine
from core.admin_store import AdminStore
from core.pm_engine.recovery import (
    DEFAULT_TRANSITION_BUFFER_SECONDS,
    DEFAULT_TRANSITION_GRACE_MINUTES,
)
from core.worktree_manager import WorktreeManager


class RecoveryWatchTransitionGuardFixture(unittest.TestCase):
    """夹具：真实 StateMachine + MagicMock worktree_manager（与既有夹具同源）"""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        # 显式关闭活跃派发（与既有 test_run_lifecycle_governance.py 同源口径）：
        # MagicMock.has_active_worktree 默认返回 MagicMock（bool 为 True），
        # 导致 check_recovery_watch 误判 spec 有活跃派发而跳过 stale 判定。
        self.runner.worktree_manager.has_active_worktree.return_value = False
        self.engine = PMEngine(
            self.sm, self.runner, {},
            self.project_root, self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 辅助方法 ─────────────────────────────────────────────────────

    def _create_spec_ready(self, name="s1"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        return self.sm.read_one(name)

    def _set_stream_mtime(self, name, seconds_ago):
        """设置 impl 流文件的 mtime 为 seconds_ago 秒前"""
        import os
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(exist_ok=True)
        stream = runs_dir / f"impl-{name}-1789999999.jsonl"
        stream.write_text('{"type":"start"}\n', encoding="utf-8")
        target = time.time() - seconds_ago
        os.utime(stream, (target, target))
        return stream

    def _watch_due(self, name="s1"):
        """把观察项 due 推前到已过期"""
        self.engine._recovery._recovery_watch[name]["due"] = time.time() - 1
        self.engine._recovery._save_recovery_watch()


class TestTransitionGuardDefer(RecoveryWatchTransitionGuardFixture):
    """3.1 / 3.3：过渡窗口复查不误报 + 顺延在册断言"""

    def test_succeed_in_buffer_defer_not_redispatched(self):
        """成功-合并窗口：succeed 痕迹在 60s 内 → 顺延不误报 dispatch_stalled"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # succeed 痕迹：30s 前写入 run 流（在 60s buffer 内）
        self._set_stream_mtime("s1", 30)
        raised = self.engine.check_recovery_watch()
        # 顺延：不应产生 dispatch_stalled，观察项仍在且 due 已推进
        self.assertEqual(raised, [])
        self.assertIn("s1", self.engine._recovery._recovery_watch)
        new_due = self.engine._recovery._recovery_watch["s1"]["due"]
        self.assertGreater(new_due, time.time())
        self.assertLessEqual(new_due, time.time() + DEFAULT_TRANSITION_BUFFER_SECONDS + 2)

    def test_pending_merge_in_grace_defer(self):
        """有未合并分支且 grace 内 → 顺延不误报 dispatch_stalled"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self.runner.worktree_manager.has_pending_merge.return_value = True
        self.runner.worktree_manager.pending_merge_since.return_value = int(time.time())
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertIn("s1", self.engine._recovery._recovery_watch)
        new_due = self.engine._recovery._recovery_watch["s1"]["due"]
        self.assertGreater(new_due, time.time())

    def test_deferred_watch_persisted_to_json(self):
        """顺延后观察项持久化在 .fenix/recovery_watch.json（防裸 continue 丢弃）"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self._set_stream_mtime("s1", 30)
        self.engine.check_recovery_watch()
        import json
        watch_path = self.project_root / ".fenix" / "recovery_watch.json"
        data = json.loads(watch_path.read_text(encoding="utf-8"))
        self.assertIn("s1", data)
        self.assertGreater(data["s1"]["due"], time.time())

    def test_defer_no_active_watch_item(self):
        """due 未到期的观察项不受过渡窗口影响（正常跳过）"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._set_stream_mtime("s1", 30)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertIn("s1", self.engine._recovery._recovery_watch)


class TestRealStaleStillReported(RecoveryWatchTransitionGuardFixture):
    """3.2：真实 stale 仍升级 dispatch_stalled"""

    def test_no_transition_signal_reports_stale(self):
        """无未合并分支、无 succeed 痕迹 → 正常报 dispatch_stalled"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        recs = AdminStore(self.project_root, self.logger).read_all()
        stalled = [r for r in recs if r.get("signal_type") == "dispatch_stalled"]
        self.assertEqual(len(stalled), 1)
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)

    def test_pending_merge_grace_expired_reports_stale(self):
        """有未合并分支但年龄超 grace → 豁免过期 → 正常报 stale"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self.runner.worktree_manager.has_pending_merge.return_value = True
        # 年龄 6min > grace 5min
        self.runner.worktree_manager.pending_merge_since.return_value = int(time.time() - 6*60)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])

    def test_pending_merge_grace_exact_boundary_reports_stale(self):
        """年龄恰好 = grace + 1s → now >= grace_deadline → 回落（不豁免）"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self.runner.worktree_manager.has_pending_merge.return_value = True
        grace_ts = int(time.time() - DEFAULT_TRANSITION_GRACE_MINUTES*60 - 1)
        self.runner.worktree_manager.pending_merge_since.return_value = grace_ts
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])

    def test_succeed_outside_buffer_reports_stale(self):
        """succeed 痕迹在 60s 外，且无 pending → 正常报 stale"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self._set_stream_mtime("s1", 120)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])


class TestGraceBoundedness(RecoveryWatchTransitionGuardFixture):
    """3.3 有界性断言（1.4）：年龄超过 grace → 回落告警"""

    def test_grace_expired_falls_back(self):
        """年龄 10min > grace 5min → 回落 → 报 stale"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self.runner.worktree_manager.has_pending_merge.return_value = True
        self.runner.worktree_manager.pending_merge_since.return_value = int(time.time() - 10*60)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])

    def test_age_start_uses_max_commit_and_succeed(self):
        """年龄起点取 max(提交时间, succeed 痕迹时间)：
        分支提交 243s 前，succeed 30s 前 → age_start=30s_ago → grace 未超 → 豁免"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self.runner.worktree_manager.has_pending_merge.return_value = True
        self.runner.worktree_manager.pending_merge_since.return_value = int(time.time() - 243)
        self._set_stream_mtime("s1", 30)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertIn("s1", self.engine._recovery._recovery_watch)

    def test_succeed_pushes_grace_deadline_later(self):
        """succeed 痕迹使 grace_deadline 从 succeed 起算而非提交时间"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # 提交 4min 前，succeed 30s 前 → age_start = max(4min, 30s) = 4min
        # grace = 5min → 4min < 5min → 豁免
        self.runner.worktree_manager.has_pending_merge.return_value = True
        self.runner.worktree_manager.pending_merge_since.return_value = int(time.time() - 4*60)
        self._set_stream_mtime("s1", 30)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])


class TestWorktreeManagerPendingMerge(unittest.TestCase):
    """3.3 has_pending_merge 三态 + 前缀歧义守卫（真实 WorktreeManager）"""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = MagicMock()
        self.wm = WorktreeManager(
            base_dir=self.project_root / ".claude" / "worktrees",
            project_root=self.project_root,
            logger=self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_pending_merge_false_when_no_branch(self):
        """无分支 → has_pending_merge False"""
        self.assertFalse(self.wm.has_pending_merge("s1"))

    def test_pending_merge_false_when_empty_repo(self):
        """空仓库 → has_pending_merge False"""
        self.assertFalse(self.wm.has_pending_merge("s1"))

    def test_impl_branch_owned_by_spec_exact_match(self):
        """精确归属：fenix/s1-<ts> 对 spec s1 → True"""
        ts = int(time.time())
        self.assertTrue(WorktreeManager._impl_branch_owned_by_spec(f"fenix/s1-{ts}", "s1"))

    def test_impl_branch_owned_by_spec_prefix_mismatch(self):
        """前缀歧义：fenix/a-b-c-<ts> 对 spec a-b → False"""
        ts = int(time.time())
        self.assertFalse(WorktreeManager._impl_branch_owned_by_spec(f"fenix/a-b-c-{ts}", "a-b"))

    def test_impl_branch_owned_by_spec_verify_excluded(self):
        """验证分支排除：fenix/verify-s1-<ts> → False"""
        ts = int(time.time())
        self.assertFalse(WorktreeManager._impl_branch_owned_by_spec(f"fenix/verify-s1-{ts}", "s1"))

    def test_impl_branch_owned_by_spec_no_ts(self):
        """无时间戳段：fenix/s1 → False（非规范命名）"""
        self.assertFalse(WorktreeManager._impl_branch_owned_by_spec("fenix/s1", "s1"))


class TestMockSubstituteRegression(RecoveryWatchTransitionGuardFixture):
    """3.4 mock 替身回归：MagicMock worktree_manager 下不误豁免"""

    def test_mock_pending_merge_is_true_falsy(self):
        """MagicMock.has_pending_merge() is True → False（is 严格判定）→ 不豁免"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # has_pending_merge 返回 MagicMock → bool(MagicMock())=True，但 is True=False
        self.runner.worktree_manager.has_pending_merge.return_value = MagicMock()
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])

    def test_mock_pending_since_non_numeric(self):
        """pending_merge_since 返回非数字 → 豁免（有界性无法度量）→ 保守不豁免"""
        self._create_spec_ready("s1")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self.runner.worktree_manager.has_pending_merge.return_value = True
        self.runner.worktree_manager.pending_merge_since.return_value = MagicMock()
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])


class TestTransitionDeferralLogic(unittest.TestCase):
    """_transition_defer_due 辅助方法逻辑测试"""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        self.engine = PMEngine(
            self.sm, self.runner, {},
            self.project_root, self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_stream_mtime(self, name, seconds_ago):
        import os
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(exist_ok=True)
        stream = runs_dir / f"impl-{name}-1789999999.jsonl"
        stream.write_text('{"type":"start"}\n', encoding="utf-8")
        target = time.time() - seconds_ago
        os.utime(stream, (target, target))

    def test_succeed_in_buffer_returns_deferred(self):
        """succeed 痕迹在 60s 内 → 返回 now+buffer"""
        self._set_stream_mtime("s1", 30)
        now = time.time()
        defer = self.engine._recovery._transition_defer_due("s1", now)
        self.assertIsNotNone(defer)
        self.assertAlmostEqual(defer, now + DEFAULT_TRANSITION_BUFFER_SECONDS, delta=2)

    def test_succeed_outside_buffer_returns_none(self):
        """succeed 痕迹在 60s 外 → 返回 None"""
        self._set_stream_mtime("s1", 120)
        defer = self.engine._recovery._transition_defer_due("s1", time.time())
        self.assertIsNone(defer)

    def test_pending_merge_in_grace_returns_deferred(self):
        """pending merge + age 在 grace 内 → 返回 deferred"""
        self.runner.worktree_manager.has_pending_merge.return_value = True
        self.runner.worktree_manager.pending_merge_since.return_value = int(time.time())
        now = time.time()
        defer = self.engine._recovery._transition_defer_due("s1", now)
        self.assertIsNotNone(defer)
        self.assertAlmostEqual(defer, now + DEFAULT_TRANSITION_BUFFER_SECONDS, delta=2)

    def test_pending_merge_outside_grace_returns_none(self):
        """pending merge + age 超 grace → 返回 None（有界性回落）"""
        self.runner.worktree_manager.has_pending_merge.return_value = True
        self.runner.worktree_manager.pending_merge_since.return_value = int(time.time() - 10*60)
        defer = self.engine._recovery._transition_defer_due("s1", time.time())
        self.assertIsNone(defer)

    def test_no_signals_returns_none(self):
        """无 pending、无 succeed → 返回 None"""
        self.runner.worktree_manager.has_pending_merge.return_value = False
        defer = self.engine._recovery._transition_defer_due("s1", time.time())
        self.assertIsNone(defer)

    def test_mock_has_pending_merge_return_value_fails_is_check(self):
        """has_pending_merge 返回 MagicMock → is True 为 False → 不豁免"""
        self.runner.worktree_manager.has_pending_merge.return_value = MagicMock()
        defer = self.engine._recovery._transition_defer_due("s1", time.time())
        self.assertIsNone(defer)

    def test_defer_capped_by_grace_deadline(self):
        """顺延推进的 due 不得晚于 grace 截止"""
        self.runner.worktree_manager.has_pending_merge.return_value = True
        # 提交 3min 前，succeed 30s 前 → age_start = 30s_ago → grace = now+270s
        self.runner.worktree_manager.pending_merge_since.return_value = int(time.time() - 3*60)
        self._set_stream_mtime("s1", 30)
        now = time.time()
        defer = self.engine._recovery._transition_defer_due("s1", now)
        # grace_cutoff = max(3min_ago, 30s_ago) + 5min = 30s_ago + 5min ≈ now+270s
        # deferred = min(now+60, now+270) = now+60
        self.assertAlmostEqual(defer, now + DEFAULT_TRANSITION_BUFFER_SECONDS, delta=2)


if __name__ == "__main__":
    unittest.main()
