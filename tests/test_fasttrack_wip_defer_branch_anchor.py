"""tests/test_fasttrack_wip_defer_branch_anchor.py — fix-fasttrack-wip-defer-branch-anchor 回归。

覆盖 spec（fasttrack-branch-anchor）Scenario：
  1. WIP 阻断后周期消费者自动合回：fast-track run 成功 → `_reconcile_and_merge`
     merge 前统一提前落 `branch`/`implementer_run` 锚点；merge-back 被重叠闸门
     阻塞（wip_gate_blocked=True）后 STATE 仍含锚点，重叠清理后周期消费者单拍
     完成 merge-only 重试（implemented 推进 + 清账 + 告警闭环），无
     `mergeback_branch_anchor_missing` 告警；
  2. spec_dir_inflight 顺延重试可合并：fast-track merge-back 撞 spec 目录在飞
     → `_defer_merge_back` 顺延，排程的 merge-only 重试按 STATE 锚点执行合并
     成功，不再回锚点缺失出口；
  3. 锚点写入失败非阻塞：锚点 update_spec 抛异常 → merge-back 主流程照常执行、
     仅 WARNING 留痕；
  4. 锚点供给来自提前落盘（成功收口写点之前），spec 无需预置锚点字段。

消费侧基座对齐 test_wip_defer_merge_retry._BaseWipDefer 范式
（真 StateMachine + mock worktree_manager）。
"""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, DISPOSITION, SIGNAL
from core.state_machine import StateMachine
from core.worktree_manager.types import MergeConflictInfo

from test_agent_runner import FakeLogger


class _RecordingLogger(FakeLogger):
    """记录 warning 的 FakeLogger 变体（锚点写失败非阻塞断言用）。"""

    def __init__(self):
        self.warnings = []

    def warning(self, *a, **k):
        self.warnings.append(" ".join(str(x) for x in a))


class _BaseFastTrackAnchor(unittest.TestCase):
    """fast-track 锚点提前落盘回归基座：真 StateMachine + mock worktree_manager。"""

    def setUp(self):
        from core.pm_engine import PMEngine

        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)
        self.logger = _RecordingLogger()
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.repo / ".fenix" / "STATE.md", self.logger)
        self.config = {}
        self.engine = PMEngine(self.sm, MagicMock(), self.config, self.repo, self.logger)
        wm = MagicMock()
        wm.ensure_spec_committed.return_value = True
        wm.last_stash_pop_conflicts = []
        wm.has_active_worktree.return_value = False
        wm.find_implementer_worktree.return_value = None
        wm.consume_legacy = MagicMock()
        self.engine.agent_runner.worktree_manager = wm
        self.engine._verification._implementer_zero_change = MagicMock(return_value=False)
        self.engine._verification._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._tasks_md_relint_from_branch = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._write_impl_result_snapshot = MagicMock()
        self.engine._cleanup_shared_result_file = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()
        self.engine._record_impl_diagnosis = MagicMock()
        self.engine._note_unattainable_todos = MagicMock()
        self.engine._process_queue = MagicMock()
        self.engine.handle_event = MagicMock()
        self.engine._dispatcher._schedule_merge_retry = MagicMock()
        self.engine._dispatcher._enqueue_front = MagicMock()
        self.engine._check_impl_budget_exhausted = MagicMock(return_value=False)
        self.wm = self.engine.agent_runner.worktree_manager

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mk_impl(self, name="spec-x"):
        """构造 implementing 态 spec（无预置锚点——锚点由提前落点供给）。"""
        self.sm.add_spec(name, {"priority": 5, "status": "implementing"})

    def _ft_result(self, branch="fenix/spec-x-1700000010", run_id="ft-spec-x-1"):
        return SimpleNamespace(branch=branch, run_id=run_id, worktree_path=None)

    def _records(self, kind=None, signal_type=None):
        store = AdminStore(self.repo, self.logger)
        return [
            r for r in store.read_all()
            if (kind is None or r.get("kind") == kind)
            and (signal_type is None or r.get("signal_type") == signal_type)
        ]

    def _anchor_missing_alerts(self):
        return self._records(signal_type="mergeback_branch_anchor_missing")


# ── Scenario 1：WIP 阻断后周期消费者自动合回（锚点来自提前落盘） ─────────────


class TestWipBlockedAnchorAndAutoMerge(_BaseFastTrackAnchor):
    def test_wip_blocked_keeps_premerge_anchor_and_consumer_merges(self):
        """fast-track WIP 阻断 → STATE 含 branch/implementer_run 锚点；周期消费
        者单拍 merge-only 成功走 _finalize_merge_success，无锚点缺失告警。"""
        self._mk_impl()
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False,
            "Merge-back blocked by WIP overlap precheck (policy=block): "
            "1 main-tree tracked file(s) with uncommitted changes overlap "
            "branch 'fenix/spec-x-1700000010' changes: ['restart_request']",
            wip_overlap=["restart_request"],
            wip_gate_blocked=True,
        )

        merged = self.engine._dispatcher._reconcile_and_merge("spec-x", self._ft_result())

        self.assertFalse(merged, "WIP 阻断分支返回 False（调用方早退）")
        entry = self.sm.read_one("spec-x") or {}
        # 锚点在 merge 前已统一提前落盘（阻塞后仍保留）
        self.assertEqual(entry.get("branch"), "fenix/spec-x-1700000010", f"{entry}")
        self.assertEqual(entry.get("implementer_run"), "ft-spec-x-1", f"{entry}")
        self.assertEqual(entry.get("status"), "implementing", "WIP 阻断不降级")
        self.assertTrue(entry.get("_wip_gate_deferred"), "阻塞等待标志已登记")
        # WIP 阻断告警保留（闸门语义不变）
        self.assertEqual(len(self._records(signal_type="mergeback_wip_overlap")), 1)

        # 主树重叠改动清理后：周期消费者单拍完成 merge-only 重试
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")
        self.engine._dispatcher._recheck_wip_deferred_merges()

        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implemented", f"{entry}")
        self.assertFalse(entry.get("_wip_gate_deferred"), "标志清账")
        self.assertIsNone(entry.get("_merge_retry_first_at"))
        self.engine._dispatcher._enqueue_front.assert_called_once_with("spec-x", "verifier")
        # 核心断言：不再回锚点缺失出口（mergeback_branch_anchor_missing 死循环告警消除）
        self.assertEqual(len(self._anchor_missing_alerts()), 0, f"{self._records()}")
        resolved = [
            r for r in self._records(kind=DISPOSITION, signal_type="mergeback_wip_overlap")
            if r.get("result") == "resolved"
        ]
        self.assertEqual(len(resolved), 1, "WIP 阻断告警显式闭环")


# ── Scenario 2：spec_dir_inflight 顺延后按 STATE 锚点重试合并 ────────────────


class TestSpecDirInflightDeferRetryByAnchor(_BaseFastTrackAnchor):
    def test_deferred_retry_merges_by_state_anchor(self):
        """fast-track 撞 spec 目录在飞 → 顺延记账 + 排程重试；重试按 STATE 锚点
        （提前落盘供给）完成 merge-only，不回锚点缺失出口。"""
        self._mk_impl()
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False,
            "spec dir inflight: spec/changes/spec-x edited by admin session",
            spec_dir_inflight=True,
        )

        merged = self.engine._dispatcher._reconcile_and_merge("spec-x", self._ft_result())

        self.assertFalse(merged, "顺延分支返回 False（调用方早退）")
        entry = self.sm.read_one("spec-x") or {}
        # 锚点在 merge 前已统一提前落盘（顺延后仍保留）
        self.assertEqual(entry.get("branch"), "fenix/spec-x-1700000010", f"{entry}")
        self.assertEqual(entry.get("implementer_run"), "ft-spec-x-1", f"{entry}")
        self.assertEqual(entry.get("status"), "implementing", "顺延不降级")
        self.assertTrue(entry.get("_merge_retry_pending"), "顺延记账已写")
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 1)
        self.engine._dispatcher._schedule_merge_retry.assert_called_once()

        # 排程的 merge-only 重试触发（Timer 回调体）：按 STATE 锚点执行合并
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")
        retried = self.engine._dispatcher._retry_merge_back_only("spec-x")

        self.assertTrue(retried, "merge-only 重试成功")
        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implemented", f"{entry}")
        self.assertFalse(entry.get("_merge_retry_pending"))
        self.wm.merge_back_from_branch.assert_called_with("fenix/spec-x-1700000010")
        # 核心断言：不再回锚点缺失出口
        self.assertEqual(len(self._anchor_missing_alerts()), 0, f"{self._records()}")


# ── Scenario 3：锚点写入失败非阻塞 ──────────────────────────────────────────


class TestAnchorWriteFailureNonBlocking(_BaseFastTrackAnchor):
    def test_anchor_write_failure_does_not_block_merge(self):
        """锚点 update_spec 抛异常 → 仅 WARNING，merge-back 主流程照常执行。"""
        self._mk_impl()
        orig_update = self.sm.update_spec
        # 仅首次含 branch 的 update（=merge 前锚点写点）失败：成功收口写点
        # （merge 后）的 branch 重写照常放行，聚焦验证「锚点写入失败非阻塞」。
        state = {"anchor_calls": 0}

        def _boom(spec_name, updates, *a, **kw):
            if "branch" in (updates or {}) and state["anchor_calls"] == 0:
                state["anchor_calls"] += 1
                raise OSError("disk full")
            return orig_update(spec_name, updates, *a, **kw)

        self.sm.update_spec = _boom
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")

        merged = self.engine._dispatcher._reconcile_and_merge("spec-x", self._ft_result())

        self.assertTrue(merged, "锚点写失败不阻塞 merge-back 主流程")
        self.wm.merge_back_from_branch.assert_called_once_with("fenix/spec-x-1700000010")
        warnings = [r for r in self.logger.warnings if "锚点提前落盘失败" in r]
        self.assertEqual(len(warnings), 1, f"{self.logger.warnings}")


# ── Scenario 4：锚点供给来自提前落盘而非收口写点（供给点前移实证） ───────────


class TestAnchorSuppliedBeforeMergeCall(_BaseFastTrackAnchor):
    def test_anchor_written_before_merge_back_invocation(self):
        """锚点写点先于 merge_back_from_branch 调用（与 _ocr_base_commit 同批）。"""
        self._mk_impl()
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")
        events = []
        real_update = self.sm.update_spec
        real_merge = self.wm.merge_back_from_branch

        def _track_update(spec_name, updates, *a, **kw):
            if "branch" in (updates or {}):
                events.append(("anchor_write", dict(updates)))
            return real_update(spec_name, updates, *a, **kw)

        def _track_merge(branch):
            events.append(("merge_call", branch))
            return real_merge(branch)

        self.sm.update_spec = _track_update
        self.wm.merge_back_from_branch = MagicMock(side_effect=_track_merge)

        self.engine._dispatcher._reconcile_and_merge("spec-x", self._ft_result())

        self.assertIn(("anchor_write", {
            "branch": "fenix/spec-x-1700000010",
            "implementer_run": "ft-spec-x-1",
        }), events, f"{events}")
        self.assertIn(("merge_call", "fenix/spec-x-1700000010"), events, f"{events}")
        # 锚点写入严格先于 merge 调用（合并失败链可依赖锚点已在 STATE）
        self.assertLess(
            [e[0] for e in events].index("anchor_write"),
            [e[0] for e in events].index("merge_call"),
            f"{events}",
        )


if __name__ == "__main__":
    unittest.main()
