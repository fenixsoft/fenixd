"""tests/test_wip_defer_merge_retry.py — evo-add-wip-defer-merge-retry-consumer 回归。

覆盖 spec（wip-defer-merge-retry）Scenario：
  1. WIP 清理后自动合回：周期复查 merge-only 重试成功 → implemented 推进 +
     标志清账 + mergeback_wip_overlap 告警显式闭环（result=resolved 处置记录）；
  2. 人工已合并/推进的 spec 不被重复合并（_retry_merge_back_only 状态守卫 +
     周期扫描严格筛选）；
  3. 等待超窗口/超轮数 → 停止自动重试、降级 mergeback_wip_defer_stuck 告警
     （daemon 生命周期内每条目至多一次）；
  4. 重试仍被 WIP 阻断 → 计数 +1、保持 implementing、不落指纹熔断记账；
  5. 带标志未超限条目豁免 orphaned_state 探测，超限后豁免自动失效恢复探测；
  6. boot 复位写点（保留续做 / 清空重建）清除标志——重启后恢复 run 在飞期间
     不触发 merge-only 重试。

消费侧测试基于 PMEngine dispatch 层测试基座（对齐 test_merge_back_spec_dir_guard
范式，worktree_manager mock）；豁免测试对齐 test_orphaned_state_signal 范式；
boot 复位测试基于真实 git 仓库 fixture（对齐 test_interrupt_recovery_preserve）。
"""

import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.admin_store import AdminStore, DISPOSITION, SIGNAL
from core.state_machine import StateMachine
from core.worktree_manager.types import MergeConflictInfo

from test_agent_runner import FakeLogger
from test_orphaned_state_signal import _make_monitor
from tests.helpers import iso_ago


# ══════════════════════════════════════════════════════════════════════════
# 消费者基座（PMEngine dispatch 层，对齐 test_merge_back_spec_dir_guard._BaseDispatch）
# ══════════════════════════════════════════════════════════════════════════


class _BaseWipDefer(unittest.TestCase):
    """周期消费者测试基座：真 StateMachine + mock worktree_manager。"""

    def setUp(self):
        from core.pm_engine import PMEngine

        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)
        self.logger = FakeLogger()
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

    def _mk_flagged(self, status="implementing", count=0, first_at=None):
        """构造带 WIP 等待标志的 spec 条目（经 STATE.md 真实往返）。"""
        self.sm.add_spec("spec-x", {
            "priority": 5,
            "status": status,
            "implementer_run": "impl-spec-x-1",
            "branch": "fenix/spec-x-1700000010",
            "_wip_gate_deferred": True,
            "_merge_retry_count": count,
            "_merge_retry_first_at": (
                first_at if first_at is not None else int(time.time())
            ),
        })

    def _records(self, kind=None, signal_type=None):
        store = AdminStore(self.repo, self.logger)
        return [
            r for r in store.read_all()
            if (kind is None or r.get("kind") == kind)
            and (signal_type is None or r.get("signal_type") == signal_type)
        ]


# ── Scenario 1：WIP 清理后自动合回 + 告警闭环 ────────────────────────────────


class TestAutoMergeOnWipClear(_BaseWipDefer):
    def test_deferred_entry_auto_merges_and_closes_alert(self):
        """带标志条目重叠已干净：merge-only 成功 → implemented + 清账 + 闭环。"""
        self._mk_flagged(count=2)
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")

        self.engine._dispatcher._recheck_wip_deferred_merges()

        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implemented", f"{entry}")
        # 标志与等待记账清账（_finalize_merge_success 清账块）
        self.assertFalse(entry.get("_wip_gate_deferred"))
        self.assertFalse(entry.get("_merge_retry_pending"))
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 0)
        self.assertIsNone(entry.get("_merge_retry_first_at"))
        # verifier 入队（既有成功收尾语义）
        self.engine._dispatcher._enqueue_front.assert_called_once_with("spec-x", "verifier")
        # mergeback_wip_overlap 告警显式闭环（result=resolved 处置记录）
        resolved = [
            r for r in self._records(kind=DISPOSITION, signal_type="mergeback_wip_overlap")
            if r.get("result") == "resolved"
        ]
        self.assertEqual(len(resolved), 1, f"{self._records()}")

    def test_scan_ignores_entry_without_flag(self):
        """无标志条目不进入周期复查（严格筛选第二层）。"""
        self.sm.add_spec("spec-y", {
            "priority": 5,
            "status": "implementing",
            "branch": "fenix/spec-y-1",
            "_merge_retry_pending": True,
            "_merge_retry_count": 1,
            "_merge_retry_first_at": int(time.time()),
        })
        self.engine._dispatcher._recheck_wip_deferred_merges()
        self.wm.merge_back_from_branch.assert_not_called()


# ── Scenario 2：人工已推进不重复合并（状态守卫）──────────────────────────────


class TestStatusGuard(_BaseWipDefer):
    def test_advanced_entry_skipped_and_cleared(self):
        """status 非 implementing：跳过合并并清账（人工/admin 已推进）。"""
        self._mk_flagged()
        self.sm.transition(
            "spec-x", "implemented",
            trigger_run_id="impl-spec-x-1", agent_type="implementer", channel="auto",
        )
        self.engine._dispatcher._retry_merge_back_only("spec-x")

        self.wm.merge_back_from_branch.assert_not_called()
        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implemented", "状态不被重试路径改写")
        self.assertFalse(entry.get("_wip_gate_deferred"))
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 0)
        self.assertIsNone(entry.get("_merge_retry_first_at"))

    def test_scan_skips_advanced_flagged_entry(self):
        """周期扫描只认 implementing：已推进条目即使标志残留也不重试。"""
        self._mk_flagged(status="ready")
        self.engine._dispatcher._recheck_wip_deferred_merges()
        self.wm.merge_back_from_branch.assert_not_called()


# ── Scenario 3：超窗口/超轮数停止自动重试并降级 ──────────────────────────────


class TestBoundedDegrade(_BaseWipDefer):
    def test_over_rounds_stops_retry_and_degrades_once(self):
        """超轮数（≥6）：不尝试合并、现场标志保留、降级告警至多一次。"""
        self._mk_flagged(count=6)
        self.engine._dispatcher._recheck_wip_deferred_merges()

        self.wm.merge_back_from_branch.assert_not_called()
        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implementing")
        self.assertTrue(entry.get("_wip_gate_deferred"), "现场标志保留供人工")
        stuck = self._records(kind=SIGNAL, signal_type="mergeback_wip_defer_stuck")
        self.assertEqual(len(stuck), 1, f"{self._records()}")
        # 第二轮复查不重复降级（daemon 生命周期内每条目至多一次）
        self.engine._dispatcher._recheck_wip_deferred_merges()
        self.assertEqual(
            len(self._records(kind=SIGNAL, signal_type="mergeback_wip_defer_stuck")), 1,
        )

    def test_over_window_stops_retry_and_degrades(self):
        """超窗口（≥90 分钟，自首阻起算）：同样停止重试并降级。"""
        self._mk_flagged(count=1, first_at=int(time.time() - 91 * 60))
        self.engine._dispatcher._recheck_wip_deferred_merges()

        self.wm.merge_back_from_branch.assert_not_called()
        self.assertEqual(
            len(self._records(kind=SIGNAL, signal_type="mergeback_wip_defer_stuck")), 1,
        )

    def test_within_limits_retries(self):
        """未超限：正常走 merge-only 重试（不降级）。"""
        self._mk_flagged(count=5)
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")
        self.engine._dispatcher._recheck_wip_deferred_merges()
        self.wm.merge_back_from_branch.assert_called_once_with("fenix/spec-x-1700000010")
        self.assertEqual(
            len(self._records(signal_type="mergeback_wip_defer_stuck")), 0,
        )


# ── Scenario 4：重试仍被阻断 → 计数 +1，不落指纹熔断 ─────────────────────────


class TestRetryStillBlockedAccounting(_BaseWipDefer):
    def test_blocked_again_increments_and_keeps_waiting(self):
        self._mk_flagged(count=0)
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False,
            "Merge-back blocked by WIP overlap precheck (policy=block): "
            "1 main-tree tracked file(s) with uncommitted changes overlap "
            "branch 'fenix/spec-x-1700000010' changes: ['shared.py']",
            wip_overlap=["shared.py"],
            wip_gate_blocked=True,
        )

        self.engine._dispatcher._recheck_wip_deferred_merges()

        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implementing", "等待态不降级")
        self.assertTrue(entry.get("_wip_gate_deferred"))
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 1, "失败计数 +1")
        self.assertNotIn("_merge_fp", entry, "wip 阻断不落指纹熔断记账")
        self.assertEqual(
            len(self._records(signal_type="mergeback_wip_defer_stuck")), 0,
        )


# ══════════════════════════════════════════════════════════════════════════
# orphaned_state 豁免（2.3，对齐 test_orphaned_state_signal 范式）
# ══════════════════════════════════════════════════════════════════════════


class TestOrphanedStateExemption:
    def _detect(self, tmp_path, specs):
        proot, mon = _make_monitor(tmp_path, specs)
        import time as _time

        from unittest import mock

        with mock.patch(
            "core.admin_monitor._pgrep_live_worktree", return_value=False,
        ):
            return mon._detect_orphaned_state(specs, _time.time())

    def _flagged_entry(self, count=2, first_age_seconds=300):
        import time as _time

        return {
            "status": "implementing",
            "updated": iso_ago(30),
            "branch": "fenix/demo-123",
            "implementer_run": "impl-demo-111",
            "_wip_gate_deferred": True,
            "_merge_retry_count": count,
            "_merge_retry_first_at": int(_time.time() - first_age_seconds),
        }

    def test_flagged_within_limits_exempt(self, tmp_path):
        """带标志未超限：orphaned_state 不误报（周期消费者负责驱动）。"""
        specs = {"demo": self._flagged_entry()}
        assert self._detect(tmp_path, specs) == []

    def test_over_rounds_exemption_expires(self, tmp_path):
        """超轮数（≥6）：豁免自动失效，孤儿探测恢复兜底。"""
        specs = {"demo": self._flagged_entry(count=6, first_age_seconds=300)}
        signals = self._detect(tmp_path, specs)
        assert [s["signal_type"] for s in signals] == ["orphaned_state"]

    def test_over_window_exemption_expires(self, tmp_path):
        """超窗口（≥90 分钟）：豁免自动失效，孤儿探测恢复兜底。"""
        specs = {"demo": self._flagged_entry(count=1, first_age_seconds=91 * 60)}
        signals = self._detect(tmp_path, specs)
        assert [s["signal_type"] for s in signals] == ["orphaned_state"]

    def test_unflagged_entry_not_exempt(self, tmp_path):
        """无标志条目不受豁免（implementing 悬置照常探测）。"""
        entry = self._flagged_entry()
        entry.pop("_wip_gate_deferred")
        specs = {"demo": entry}
        signals = self._detect(tmp_path, specs)
        assert [s["signal_type"] for s in signals] == ["orphaned_state"]


# ══════════════════════════════════════════════════════════════════════════
# boot 复位写点清除标志（1.2，真实 git 仓库 fixture，对齐
# test_interrupt_recovery_preserve 范式）
# ══════════════════════════════════════════════════════════════════════════


def git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", "main")


def add_commit(root: Path, rel: str, content: str, msg: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)


def make_wm(root: Path):
    from core.worktree_manager import WorktreeManager

    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


def make_state_machine(root: Path, specs: dict) -> StateMachine:
    state_path = root / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(state_path, FakeLogger())
    for name, entry in specs.items():
        sm.add_spec(name, entry)
    return sm


def _flagged_spec_entry():
    import time as _time

    return {
        "status": "implementing",
        "branch": "fenix/demo-123",
        "implementer_run": "impl-demo-111",
        "_wip_gate_deferred": True,
        "_merge_retry_count": 2,
        "_merge_retry_first_at": int(_time.time()),
    }


class TestBootResetClearsFlag:
    def test_preserve_resume_clears_flag(self, tmp_path):
        """保留续做复位写点（implementing→READY）：标志清除（STATE.md 往返）。"""
        root = tmp_path / "repo"
        init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/demo-123")
        add_commit(root, "feat.py", "IMPL\n", "[fenix] demo: impl")
        git(root, "checkout", "-q", "main")
        sm = make_state_machine(root, {"demo": _flagged_spec_entry()})

        recovered = sm.recover_interrupted(
            project_root=root, worktree_manager=make_wm(root),
        )

        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["_recovery_resume"] is True, "保留续做路径本身不变"
        assert not entry.get("_wip_gate_deferred"), (
            "boot 保留续做复位写点须清标志——否则恢复 run 在飞期间周期消费者"
            "会把半成品分支过早 merge 进主树"
        )

    def test_clear_and_rebuild_clears_flag(self, tmp_path):
        """清空重建复位写点（零提交分支）：标志清除，不残留污染下一轮。"""
        root = tmp_path / "repo"
        init_repo(root)
        # 分支存在但相对 main 零提交 → 清空重建路径
        git(root, "branch", "fenix/demo-123")
        sm = make_state_machine(root, {"demo": _flagged_spec_entry()})

        recovered = sm.recover_interrupted(
            project_root=root, worktree_manager=make_wm(root),
        )

        assert "demo" in recovered
        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry["branch"] is None
        assert not entry.get("_wip_gate_deferred"), "清空重建不得残留等待标志"
