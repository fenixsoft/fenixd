"""tests/test_mergeback_archive_residue_selfheal.py — evo-mergeback-archive-residue-selfheal 回归。

覆盖 spec（mergeback-archive-residue-selfheal）Scenario：

  1. 归档半程主树 + 待 merge-back 分支：判据命中 → 框架补提交归档收尾 +
     立即重放合并成功，零 admin 会话（无 mergeback_spec_dir_inflight_stuck）；
  2. 混合源码 WIP 脏文件：判据未命中，行为与现状一致（顺延→熔断告警）；
  3. 单侧半提交形态（仅 changes 删除态 / 仅 archive 新增）：不自动收尾走熔断；
  4. 补提交失败：熔断且告警 evidence 留痕（失败原因）；
  5. 单次尝试上限：daemon 生命周期内每条目至多自动尝试一次；
  6. 补提交 add 仅含精确残留路径：其它 spec 在途草案不入提交；
  7. 补提交前重查：归档自身收口已完成则跳过补提交直接重放（无重复提交）；
  8. 周期消费者（_recheck_inflight_deferred_merges）：只接手已超熔断阈值且仍
     _merge_retry_pending 的条目（Timer 链缺失/重启残留场景，含自愈间接生效）；
     未超阈值条目跳过（防与存活 Timer 链双驱动）；WIP 车道条目与非
     implementing 条目不越界；接手重试每条目至多一次。

消费侧测试基于 PMEngine dispatch 层测试基座（对齐 test_wip_defer_merge_retry
范式，真 git 仓库 + 真 StateMachine + mock worktree_manager）。
"""

import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.admin_store import SIGNAL
from core.state_machine import StateMachine
from core.worktree_manager.types import MergeConflictInfo

from test_agent_runner import FakeLogger
from test_run_lifecycle_hardening import init_git_repo


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
        check=check,
    )


# ══════════════════════════════════════════════════════════════════════════
# 基座：真 git 仓库 + 真 StateMachine + mock worktree_manager
# ══════════════════════════════════════════════════════════════════════════


class _BaseSelfheal(unittest.TestCase):
    ARCHIVE_TS = 1788451452

    def setUp(self):
        from core.pm_engine import PMEngine

        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)
        init_git_repo(self.repo, {
            "spec/changes/spec-x/spec.md": "# X\n",
            "spec/changes/spec-x/tasks.md": "# T\n",
            "core/keep.py": "KEEP = 1\n",
        })
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = FakeLogger()
        self.sm = StateMachine(self.repo / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.repo, self.logger)
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

    # ── 现场构造 ──

    def _mk_spec(self, name="spec-x", count=3, first_at=None, status="implementing",
                 pending=True, wip_flag=False):
        """构造顺延中的 spec 条目（经 STATE.md 真实往返）。count=3 即已超轮数阈值。"""
        fields = {
            "priority": 5,
            "status": status,
            "implementer_run": f"impl-{name}-1",
            "branch": f"fenix/{name}-1700000010",
            "_merge_retry_pending": pending,
            "_merge_retry_count": count,
            "_merge_retry_first_at": (
                first_at if first_at is not None else int(time.time())
            ),
        }
        if wip_flag:
            fields["_wip_gate_deferred"] = True
        self.sm.add_spec(name, fields)

    def _move_to_archive(self, name="spec-x"):
        """模拟归档半程：shutil.move 移入 archive（未暂存 D + 未跟踪 ?? 宽形态）。"""
        arch = self.repo / "spec" / "archive" / f"{name}-{self.ARCHIVE_TS}"
        arch.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.repo / "spec" / "changes" / name), str(arch))
        return arch

    def _git_mv_to_archive(self, name="spec-x"):
        """模拟已 staged 的归档移动（git R 重命名行天然成对形态）。"""
        rel_arch = f"spec/archive/{name}-{self.ARCHIVE_TS}"
        (self.repo / "spec" / "archive").mkdir(parents=True, exist_ok=True)
        git(self.repo, "mv", f"spec/changes/{name}", rel_arch)
        return self.repo / rel_arch

    def _defer(self, name="spec-x", merge_error="merge-back blocked: spec dir inflight"):
        """直接驱动 _defer_merge_back 熔断判定（count 已在阈值上即触发熔断分支）。"""
        merge_info = MergeConflictInfo(False, merge_error, spec_dir_inflight=True)
        self.engine._dispatcher._defer_merge_back(
            name, merge_info, f"fenix/{name}-1700000010", merge_error,
        )

    def _records(self, kind=None, signal_type=None):
        from core.admin_store import AdminStore

        store = AdminStore(self.repo, self.logger)
        return [
            r for r in store.read_all()
            if (kind is None or r.get("kind") == kind)
            and (signal_type is None or r.get("signal_type") == signal_type)
        ]

    def _stuck_alerts(self):
        return self._records(kind=SIGNAL, signal_type="mergeback_spec_dir_inflight_stuck")

    def _commit_subjects(self):
        return git(self.repo, "log", "--format=%s").stdout.strip().splitlines()

    def _head_files(self):
        # --no-renames：禁用 rename 检测，删除侧确定性呈现为 D 行
        # （rename 检测开着时 --name-only 只列新路径，旧路径断言会失配）
        return git(
            self.repo, "show", "--name-status", "--no-renames", "--format=", "HEAD",
        ).stdout


# ── Scenario 1：归档半程自动收尾 + 重放成功 + 零 admin 会话 ─────────────────


class TestSelfhealAutoCommitAndReplay(_BaseSelfheal):
    def test_half_state_auto_commits_and_replays_without_admin_signal(self):
        """判据命中：补提交归档收尾 + 重放合并成功，无 stuck 告警、记账清账。"""
        self._mk_spec(count=3)
        self._move_to_archive()
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")

        self._defer()

        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implemented", f"{entry}")
        # 顺延记账清账（_finalize_merge_success 收口）
        self.assertFalse(entry.get("_merge_retry_pending"))
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 0)
        self.assertIsNone(entry.get("_merge_retry_first_at"))
        # 补提交落库：消息含目标 spec 名（归档收尾形态）
        self.assertIn(
            "[fenix] archive: spec-x 归档入库", self._commit_subjects(), self._commit_subjects(),
        )
        # 提交内容横跨两侧：archive 新增侧 + changes 删除侧
        head = self._head_files()
        self.assertIn(f"spec/archive/spec-x-{self.ARCHIVE_TS}/spec.md", head)
        self.assertIn("spec/changes/spec-x/spec.md", head)
        # 零 admin 会话：不产生 stuck 告警
        self.assertEqual(len(self._stuck_alerts()), 0, f"{self._records()}")
        # 立即重放了既有 merge-back 路径
        self.wm.merge_back_from_branch.assert_called_once_with("fenix/spec-x-1700000010")

    def test_staged_rename_form_auto_heals(self):
        """git R 重命名行（已 staged 归档移动）天然成对：同样自动收尾。"""
        self._mk_spec(count=3)
        self._git_mv_to_archive()
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")

        self._defer()

        self.assertEqual(
            (self.sm.read_one("spec-x") or {}).get("status"), "implemented",
        )
        self.assertEqual(len(self._stuck_alerts()), 0)
        self.assertIn("[fenix] archive: spec-x 归档入库", self._commit_subjects())

    def test_dirty_tree_already_clean_replays_without_commit(self):
        """重查时主树已干净（如收口已被他人完成）：跳过补提交直接重放。"""
        self._mk_spec(count=3)
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")
        commits_before = git(self.repo, "log", "--format=%H").stdout.strip().splitlines()

        self._defer()

        commits_after = git(self.repo, "log", "--format=%H").stdout.strip().splitlines()
        self.assertEqual(len(commits_after), len(commits_before), "无残留时不得补提交")
        self.assertEqual(
            (self.sm.read_one("spec-x") or {}).get("status"), "implemented",
        )
        self.assertEqual(len(self._stuck_alerts()), 0)


# ── Scenario 2/3：判据未命中维持熔断（混合源码 WIP / 单侧半提交形态）────────


class TestCriteriaMissStaysFused(_BaseSelfheal):
    def _assert_fused(self, expect_in_evidence):
        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implementing", "熔断保持 implementing 等人工")
        self.assertTrue(entry.get("_merge_retry_pending"))
        alerts = self._stuck_alerts()
        self.assertEqual(len(alerts), 1, f"{self._records()}")
        evidence = alerts[0].get("evidence") or ""
        self.assertIn("判据未命中", evidence, evidence)
        for frag in expect_in_evidence:
            self.assertIn(frag, evidence, evidence)
        # 未重放合并、未补提交
        self.wm.merge_back_from_branch.assert_not_called()
        self.assertEqual(self._commit_subjects(), ["initial"])

    def test_mixed_source_wip_not_healed(self):
        """归档残留 + 源码 WIP 混合脏文件：判非归档残留，维持熔断。"""
        self._mk_spec(count=3)
        self._move_to_archive()
        (self.repo / "core" / "keep.py").write_text("KEEP = 2\n", encoding="utf-8")
        self.wm.merge_back_from_branch.side_effect = AssertionError("不得重放合并")

        self._defer()

        self._assert_fused(["core/keep.py"])

    def test_changes_deletion_only_not_healed(self):
        """仅 changes 删除态（单侧半提交）：不授权自动收尾，走熔断。"""
        self._mk_spec(count=3)
        shutil.rmtree(self.repo / "spec" / "changes" / "spec-x")
        self.wm.merge_back_from_branch.side_effect = AssertionError("不得重放合并")

        self._defer()

        self._assert_fused(["仅单侧"])

    def test_archive_add_only_not_healed(self):
        """仅 archive 新增（单侧半提交，changes 侧在场未动）：不授权，走熔断。"""
        self._mk_spec(count=3)
        arch = self.repo / "spec" / "archive" / f"spec-x-{self.ARCHIVE_TS}"
        arch.mkdir(parents=True)
        (arch / "spec.md").write_text("# X\n", encoding="utf-8")
        self.wm.merge_back_from_branch.side_effect = AssertionError("不得重放合并")

        self._defer()

        self._assert_fused(["仅单侧"])

    def test_non_spec_untracked_file_blocks_heal(self):
        """类外未跟踪脏文件（如临时产物）：同样否决自愈（全落 spec/ 才授权）。"""
        self._mk_spec(count=3)
        self._move_to_archive()
        (self.repo / "scratch.txt").write_text("noise\n", encoding="utf-8")
        self.wm.merge_back_from_branch.side_effect = AssertionError("不得重放合并")

        self._defer()

        self._assert_fused(["scratch.txt"])


# ── Scenario 4/5：补提交失败熔断留痕 / 单次尝试上限 ─────────────────────────


class TestCommitFailureAndAttemptCap(_BaseSelfheal):
    def test_commit_failure_falls_to_fuse_with_evidence(self):
        """补提交失败：走原熔断，告警 evidence 留痕失败原因，不重放。

        用真实 git 失败注入（预置 .git/index.lock——并发 git 操作的实况形态，
        git add 对其必败），不 mock _git_commit/_heal_commit_archive_residue。
        """
        self._mk_spec(count=3)
        self._move_to_archive()
        (self.repo / ".git" / "index.lock").write_text("", encoding="utf-8")
        self.wm.merge_back_from_branch.side_effect = AssertionError("补提交失败不得重放")

        self._defer()

        alerts = self._stuck_alerts()
        self.assertEqual(len(alerts), 1, f"{self._records()}")
        evidence = alerts[0].get("evidence") or ""
        self.assertIn("补提交失败", evidence, evidence)
        self.assertIn("index.lock", evidence, evidence)
        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implementing")

    def test_selfheal_attempted_once_per_entry(self):
        """单次尝试上限：重放失败后再入熔断不再评估/重试，告警去重仍 1 条。"""
        self._mk_spec(count=3)
        self._move_to_archive()
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False, "merge-back blocked: spec dir inflight", spec_dir_inflight=True,
        )

        self._defer()  # 第一次：补提交 + 重放失败 → 熔断告警
        calls_after_first = self.wm.merge_back_from_branch.call_count
        self.assertGreaterEqual(calls_after_first, 1, "首次已尝试重放")
        commits_after_first = self._commit_subjects()
        self.assertEqual(len(self._stuck_alerts()), 1)

        self._defer()  # 第二次：自愈已尝试过 → 不再评估/重放，告警去重
        self.assertEqual(
            self.wm.merge_back_from_branch.call_count, calls_after_first,
            "单条至多自动尝试一次，不得再重放",
        )
        self.assertEqual(self._commit_subjects(), commits_after_first, "不得重复补提交")
        self.assertEqual(len(self._stuck_alerts()), 1, "告警去重幂等")


# ── Scenario 6/7：精确路径 add / 重查防重复提交 ─────────────────────────────


class TestPreciseAddAndRecheck(_BaseSelfheal):
    def test_commit_add_is_exact_residue_paths_excludes_other_draft(self):
        """补提交 add 仅含精确残留路径：其它 spec 在途草案不入提交。"""
        self._mk_spec(count=3)
        self._move_to_archive()
        draft = self.repo / "spec" / "changes" / "spec-y"
        draft.mkdir(parents=True)
        (draft / "draft.md").write_text("# draft\n", encoding="utf-8")
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")

        self._defer()

        head = self._head_files()
        self.assertIn(f"spec/archive/spec-x-{self.ARCHIVE_TS}/spec.md", head)
        self.assertNotIn("spec-y", head, "其它 spec 在途草案不得卷进归档收尾提交")
        # 草案仍留在工作区未跟踪（未被吞）
        st = git(self.repo, "status", "--porcelain", "-uall").stdout
        self.assertIn("?? spec/changes/spec-y/draft.md", st)
        self.assertEqual(len(self._stuck_alerts()), 0)

    def test_recheck_skips_commit_when_archive_flow_already_committed(self):
        """补提交前重查：归档自身收口已完成 → 跳过补提交直接重放，无重复提交。"""
        self._mk_spec(count=3)
        arch = self._move_to_archive()
        from core.archive_commit import commit_archive_move

        done = commit_archive_move(
            self.repo, "spec-x", arch,
            distill=lambda proot, name: {"dispatched": False, "reason": "test"},
        )
        self.assertTrue(done["committed"], done)
        commits_before = git(self.repo, "log", "--format=%H").stdout.strip().splitlines()
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")

        self._defer()

        commits_after = git(self.repo, "log", "--format=%H").stdout.strip().splitlines()
        self.assertEqual(
            len(commits_after), len(commits_before), "收口已在场时不得重复补提交",
        )
        self.assertEqual(
            (self.sm.read_one("spec-x") or {}).get("status"), "implemented",
        )
        self.assertEqual(len(self._stuck_alerts()), 0)


# ── Scenario 8：spec_dir_inflight 顺延周期消费者 ────────────────────────────


class TestInflightDeferredConsumer(_BaseSelfheal):
    def test_timer_chain_missing_picks_up_and_heals(self):
        """Timer 链缺失（重启后 pending 残留）：节拍内接手，自愈间接生效。"""
        self._mk_spec(count=4)
        self._move_to_archive()
        # 首次重试仍被脏树阻断 → 再入 _defer_merge_back 熔断分支 → 自愈收尾 →
        # 重放合并成功
        self.wm.merge_back_from_branch.side_effect = [
            MergeConflictInfo(False, "merge-back blocked: spec dir inflight",
                              spec_dir_inflight=True),
            MergeConflictInfo(True, ""),
        ]

        self.engine._dispatcher._recheck_inflight_deferred_merges()

        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implemented", f"{entry}")
        self.assertFalse(entry.get("_merge_retry_pending"))
        self.assertIn("[fenix] archive: spec-x 归档入库", self._commit_subjects())
        self.assertEqual(len(self._stuck_alerts()), 0, f"{self._records()}")

    def test_skips_below_threshold_entries_no_double_drive(self):
        """未超阈值条目由 60s Timer 链驱动：消费者跳过防双驱动。"""
        self._mk_spec(count=1, first_at=int(time.time()))
        self.wm.merge_back_from_branch.side_effect = AssertionError(
            "未超阈值条目不得由消费者接手（Timer 链存活）",
        )

        self.engine._dispatcher._recheck_inflight_deferred_merges()

        self.wm.merge_back_from_branch.assert_not_called()

    def test_skips_wip_flagged_and_advanced_entries(self):
        """WIP 车道条目与非 implementing 条目：消费者不越界。"""
        self._mk_spec(name="spec-w", count=4, wip_flag=True)
        self._mk_spec(name="spec-a", count=4, status="ready")
        self.wm.merge_back_from_branch.side_effect = AssertionError(
            "WIP 车道/已推进条目不得由本消费者接手",
        )

        self.engine._dispatcher._recheck_inflight_deferred_merges()

        self.wm.merge_back_from_branch.assert_not_called()

    def test_single_recheck_attempt_per_entry(self):
        """接手重试每条目至多一次：失败维持熔断告警，不无限节拍重试。"""
        self._mk_spec(count=4)
        # 源码脏文件 → 自愈判据未命中 → 纯重试，重试失败走熔断告警
        (self.repo / "core" / "keep.py").write_text("KEEP = 2\n", encoding="utf-8")
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False, "error: Your local changes would be overwritten",
            spec_dir_inflight=True,
        )

        self.engine._dispatcher._recheck_inflight_deferred_merges()
        calls_after_first = self.wm.merge_back_from_branch.call_count
        self.assertGreaterEqual(calls_after_first, 1)
        self.assertEqual(len(self._stuck_alerts()), 1, f"{self._records()}")

        self.engine._dispatcher._recheck_inflight_deferred_merges()
        self.assertEqual(
            self.wm.merge_back_from_branch.call_count, calls_after_first,
            "接手重试每条目至多一次",
        )
        self.assertEqual(len(self._stuck_alerts()), 1, "熔断告警去重幂等")

    def test_over_window_entry_picked_up(self):
        """超窗口（grace_minutes）但轮数未超的条目：同判式接手。"""
        self._mk_spec(count=1, first_at=int(time.time() - 91 * 60))
        self.wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")

        self.engine._dispatcher._recheck_inflight_deferred_merges()

        self.assertGreaterEqual(self.wm.merge_back_from_branch.call_count, 1)


# ── 共享辅助契约：engine 委托 + 成对校验判据 ────────────────────────────────


class TestSharedScanAndPairing(_BaseSelfheal):
    def test_engine_delegates_to_shared_scan(self):
        """engine._archive_move_residue 委托共享辅助：三元组契约零变化。"""
        from core.archive_commit import scan_archive_residue

        self._move_to_archive()
        scan = scan_archive_residue(self.repo)
        has, names, paths = self.engine._archive_move_residue()
        self.assertEqual((has, names, paths), (scan.found, scan.spec_names, scan.residue_paths))
        self.assertTrue(has)
        self.assertIn("spec-x", names)
        self.assertEqual(scan.error, None)

    def test_pairing_assessment_forms(self):
        """成对校验判据：成对授权；单侧/类外脏文件/空扫描否决。"""
        from core.archive_commit import (
            ArchiveResidueScan,
            assess_archive_residue_selfheal,
        )

        # 成对（删除侧 + archive 新增侧同 spec 名）
        paired = ArchiveResidueScan(
            True, ["spec-x"],
            ["spec/changes/spec-x/spec.md", "spec/archive/spec-x-1/spec.md"],
            [
                {"path": "spec/changes/spec-x/spec.md", "side": "changes",
                 "deleted": True, "added": False, "renamed": False,
                 "spec": "spec-x", "pair_complete": False},
                {"path": "spec/archive/spec-x-1/spec.md", "side": "archive",
                 "deleted": False, "added": True, "renamed": False,
                 "spec": "spec-x", "pair_complete": False},
            ],
            [], None,
        )
        ok, _ = assess_archive_residue_selfheal(paired)
        self.assertTrue(ok)

        # 仅单侧（半提交形态）
        half = ArchiveResidueScan(
            True, ["spec-x"], ["spec/changes/spec-x/spec.md"],
            [{"path": "spec/changes/spec-x/spec.md", "side": "changes",
              "deleted": True, "added": False, "renamed": False,
              "spec": "spec-x", "pair_complete": False}],
            [], None,
        )
        ok, reason = assess_archive_residue_selfheal(half)
        self.assertFalse(ok)
        self.assertIn("仅单侧", reason)

        # 类外脏文件（混合源码 WIP）
        mixed = ArchiveResidueScan(True, [], [], [], ["core/keep.py"], None)
        ok, reason = assess_archive_residue_selfheal(mixed)
        self.assertFalse(ok)
        self.assertIn("core/keep.py", reason)

        # 探测失败 fail-open
        broken = ArchiveResidueScan(False, [], [], [], [], "git status 异常: boom")
        ok, reason = assess_archive_residue_selfheal(broken)
        self.assertFalse(ok)
        self.assertIn("boom", reason)


if __name__ == "__main__":
    unittest.main()
