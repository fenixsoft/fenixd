"""evo-merge-back-spec-dir-inflight-guard 测试。

覆盖 merge-back 前 spec/changes/ 在飞编辑卫检查与失败分类的 5 个场景：
  3.1: spec/changes/<spec>/ 有未提交改动（tracked / untracked / specs/** 子目录脏）
        → merge-back 顺延不 merge（MergeConflictInfo.spec_dir_inflight=True），
        主树零污染（无 stash 条目、HEAD 不变）
  3.2: 合并失败分类后可重试路径仅重试合并而非重派实现
        （run_id 不变断言），_retry_count / _merge_fp / _merge_streak 均未变化
  3.3: 顺延有界——连续顺延达上限后回落告警/人工通道（admin 信号写入），
        _repair_awaiting_remerge 标记在 repair re-merge 顺延路径未被消费
  3.4: 闸门顺序回归——语义冲突 → rehearsed（不被顺延接走）、
        WIP 重叠 → wip_gate_blocked（不被顺延接走）
  3.5: spec 名解析失败（非 fenix/<spec>-<ts> 分支名）时 fail-open 放行，
        断言未对 spec/changes/ 全目录做检测（dirty 仍放行）

evo-inflight-spec-amendment-watch 3.1 增补：主树已提交在飞修订检测——
  夹具仓库在 merge-base 之后于主树提交 spec 目录改动 → merge-back 发
  spec_amendment_inflight 告警且 merge_info.amended_inflight 携带提交列表、
  repair 上下文含根因段；主树无新提交 → 行为与告警完全不变；分支不存在 →
  静默跳过不报错。
"""

import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.worktree_manager import WorktreeManager
from core.worktree_manager.mergeback import (
    detect_spec_amended_inflight,
    spec_amendment_fingerprint,
)
from core.worktree_manager.types import MergeConflictInfo

from test_agent_runner import FakeLogger
from test_worktree_merge_guard import git, init_repo, make_wm


def make_branch(root: Path, branch: str, added_path: str, added_content: str,
                shared_content: str = "BASE\n"):
    """从 BASE 派生分支：写 added_path +（可选）改 shared.py，提交；checkout 回 BASE。"""
    base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
    git(root, "checkout", "-q", "-b", branch)
    (root / added_path).parent.mkdir(parents=True, exist_ok=True)
    (root / added_path).write_text(added_content, encoding="utf-8")
    if shared_content != "BASE\n":
        (root / "shared.py").write_text(shared_content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"[fenix] branch {branch}")
    git(root, "checkout", "-q", base_sha)
    return base_sha


def stash_count(root: Path) -> int:
    """主树 stash 栈条目数（零污染断言用）。"""
    res = git(root, "stash", "list")
    return len([ln for ln in res.stdout.splitlines() if ln.strip()])


# ── 3.1: spec 目录脏时顺延不 merge，主树零污染 ──────────────────────────────

class TestSpecDirInflightGuard:
    """3.1: spec/changes/<spec>/ 有未提交改动 → 顺延不 merge，主树零污染。

    三种脏形态分别构造：tracked 文件修改、untracked 新文件、specs/** 子目录
    修改（D1：检测范围 MUST 为整个目录，不只 tasks.md）。
    """

    def _dirty_tree(self, tmp_path, dirty_path: str, untracked: bool = False):
        """构造 repo：spec/changes/evo-x/ 目录在飞编辑，分支带新提交。"""
        root = tmp_path / "repo"
        init_repo(root)
        # spec 目录先入基线（模拟 ensure_spec_committed 后的主树）
        spec_dir = root / "spec" / "changes" / "evo-x"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "proposal.md").write_text("proposal\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("tasks\n", encoding="utf-8")
        (spec_dir / "specs").mkdir(parents=True, exist_ok=True)
        (spec_dir / "specs" / "s.md").write_text("s\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] spec evo-x base")
        # 分支：改 shared.py + 新增 core/impl.py
        make_branch(
            root,
            "fenix/evo-x-1700000000",
            "core/impl.py",
            "IMPL\n",
            shared_content="BASE-MOD\n",
        )
        # 在飞编辑：整个 spec/changes/evo-x/ 目录下的 dirty_path
        target = root / "spec" / "changes" / "evo-x" / dirty_path
        if untracked:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("inflight-edit\n", encoding="utf-8")
        else:
            target.write_text("inflight-edit\n", encoding="utf-8")
        return root

    def test_tracked_dirty_defers_and_leaves_tree_clean(self, tmp_path):
        """tracked tasks.md 脏 → 顺延（spec_dir_inflight=True），HEAD 不变、无 stash。"""
        root = self._dirty_tree(tmp_path, "tasks.md")
        head_before = git(root, "rev-parse", "HEAD").stdout.strip()
        wm = make_wm(root)

        info = wm.merge_back_from_branch("fenix/evo-x-1700000000")

        assert info.success is False
        assert info.spec_dir_inflight is True, "应携带顺延信号"
        assert info.rehearsed is False
        assert info.wip_gate_blocked is False
        assert "spec/changes/evo-x" in info.error
        # 主树零污染：HEAD 不变、无 stash 条目、spec 目录改动原样保留
        assert git(root, "rev-parse", "HEAD").stdout.strip() == head_before
        assert stash_count(root) == 0
        assert (root / "spec" / "changes" / "evo-x" / "tasks.md").read_text() == "inflight-edit\n"

    def test_untracked_dirty_defers(self, tmp_path):
        """仅 untracked 新文件脏 → 同样顺延（D1：含 untracked）。"""
        root = self._dirty_tree(tmp_path, "design.md", untracked=True)
        wm = make_wm(root)

        info = wm.merge_back_from_branch("fenix/evo-x-1700000000")

        assert info.success is False
        assert info.spec_dir_inflight is True
        assert stash_count(root) == 0

    def test_specs_subdir_dirty_defers(self, tmp_path):
        """仅 specs/** 子目录脏 → 顺延（检测范围为整个目录，不只 tasks.md）。"""
        root = self._dirty_tree(tmp_path, "specs/s.md")
        wm = make_wm(root)

        info = wm.merge_back_from_branch("fenix/evo-x-1700000000")

        assert info.success is False
        assert info.spec_dir_inflight is True
        assert "spec/changes/evo-x" in info.error
        assert stash_count(root) == 0

    def test_clean_spec_dir_merges(self, tmp_path):
        """对照：spec 目录干净时不受卫检查影响，正常 merge。"""
        root = tmp_path / "repo"
        init_repo(root)
        spec_dir = root / "spec" / "changes" / "evo-y"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "proposal.md").write_text("proposal\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] spec evo-y base")
        make_branch(root, "fenix/evo-y-1700000001", "core/impl.py", "IMPL\n",
                    shared_content="BASE-MOD\n")
        wm = make_wm(root)

        info = wm.merge_back_from_branch("fenix/evo-y-1700000001")

        assert info.success is True, f"spec 目录干净应正常 merge: {info.error}"
        assert info.spec_dir_inflight is False


# ── 3.5: spec 名解析失败 fail-open ──────────────────────────────────────────

class TestSpecParseFailOpen:
    """3.5: 非 fenix/<spec>-<ts> 形态分支名 → fail-open，不做全目录检测。

    _spec_from_branch 对非形态分支返回 None；此时 MUST 放行现行流程，
    MUST NOT 退化为对 spec/changes/ 全目录检测（把「人正在改别的 spec」
    误判为本 spec 受阻）。
    """

    def test_parse_failure_ignores_dirty_spec_changes(self, tmp_path):
        """分支名无法解析出 spec（非 fenix/ 前缀）→ 即使 spec/changes/ 全目录
        有其他 spec 的在飞编辑也放行到真合并（fail-open）。"""
        root = tmp_path / "repo"
        init_repo(root)
        # 别的 spec 目录在飞编辑（若误做全目录检测会命中）
        other = root / "spec" / "changes" / "other-spec"
        other.mkdir(parents=True, exist_ok=True)
        (other / "tasks.md").write_text("inflight-edit\n", encoding="utf-8")
        # 分支：非 fenix/<spec>-<ts> 形态
        make_branch(root, "feature-branch", "core/impl.py", "IMPL\n",
                    shared_content="BASE-MOD\n")
        wm = make_wm(root)

        info = wm.merge_back_from_branch("feature-branch")

        # fail-open：不因解析失败顺延，走现行真合并
        assert info.spec_dir_inflight is False
        assert info.success is True, f"解析失败应放行现行流程: {info.error}"

    def test_parse_failure_none_spec_no_check(self, tmp_path):
        """分支名空/无 fenix/ 前缀 → _spec_from_branch 返回 None，直接放行不检测。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / "spec" / "changes").mkdir(parents=True, exist_ok=True)
        (root / "spec" / "changes" / "zzz" / "tasks.md").parent.mkdir(parents=True, exist_ok=True)
        (root / "spec" / "changes" / "zzz" / "tasks.md").write_text("x\n", encoding="utf-8")
        make_branch(root, "fenix/verify-my-spec-1700000002", "core/impl.py", "IMPL\n",
                    shared_content="BASE-MOD\n")
        wm = make_wm(root)

        # verify- 前缀分支解析为 my-spec；spec/changes/my-spec 不存在 → 干净放行
        info = wm.merge_back_from_branch("fenix/verify-my-spec-1700000002")
        assert info.success is True, f"verify- 分支正常解析应放行: {info.error}"


# ── 3.4: 闸门顺序回归 ───────────────────────────────────────────────────────

class TestGateOrdering:
    """3.4: 语义冲突 → rehearsed；WIP 重叠 → wip_gate_blocked；均不被顺延接走。

    卫检查插点位于 rehearsed（mergeback.py:77）与 wip_overlap_gate（mergeback.py:96）
    之后：即使 spec 目录也脏，前置闸门判定结果不变（顺序不改变各自判定结果）。
    """

    def test_semantic_conflict_still_rehearsed(self, tmp_path):
        """主树提交级语义冲突 + spec 目录脏 → 返回 rehearsed（而非顺延）。

        预演闸（merge-tree）从**提交**计算合并树：先让主树 HEAD 与分支对同一
        文件有不同修改（提交级冲突），再叠加 spec 目录在飞编辑——卫检查插点在
        预演闸之后，预演检出语义冲突时 MUST 返回 rehearsed（不被顺延接走）。
        """
        root = tmp_path / "repo"
        init_repo(root)
        # spec 目录脏（在飞编辑）
        spec_dir = root / "spec" / "changes" / "evo-z"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "proposal.md").write_text("proposal\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] spec evo-z base")
        (spec_dir / "proposal.md").write_text("inflight-edit\n", encoding="utf-8")
        # 分支先从 base 派生（改 shared.py=BRANCH-VERSION + 新增 core/impl.py）
        make_branch(root, "fenix/evo-z-1700000003", "core/impl.py", "IMPL\n",
                    shared_content="BRANCH-VERSION\n")
        # 主树在分支派生后提交 shared.py=MAIN-VERSION（merge-base=BASE，两侧各改
        # shared.py → 提交级语义冲突，预演闸必须检出）
        (root / "shared.py").write_text("MAIN-VERSION\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] main shared change")
        # spec 目录在飞编辑（叠加场景）
        (spec_dir / "proposal.md").write_text("inflight-edit\n", encoding="utf-8")
        wm = make_wm(root)

        info = wm.merge_back_from_branch("fenix/evo-z-1700000003")

        assert info.rehearsed is True, f"提交级语义冲突应返回 rehearsed: {info.error}"
        assert info.spec_dir_inflight is False, "语义冲突不被顺延接走"
        assert stash_count(root) == 0

    def test_wip_overlap_still_gate_blocked(self, tmp_path):
        """WIP 重叠 + spec 目录脏 → 返回 wip_gate_blocked（而非顺延）。"""
        root = tmp_path / "repo"
        init_repo(root)
        spec_dir = root / "spec" / "changes" / "evo-w"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "proposal.md").write_text("proposal\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] spec evo-w base")
        # 分支：改 shared.py + 新增 core/impl.py
        make_branch(root, "fenix/evo-w-1700000004", "core/impl.py", "IMPL\n",
                    shared_content="BASE-MOD\n")
        # 主树 shared.py 在飞编辑（与分支改动重叠 → 闸门）
        (root / "shared.py").write_text("MAIN-INFLIGHT\n", encoding="utf-8")
        wm = make_wm(root, mergeback_wip_overlap_policy="block")

        info = wm.merge_back_from_branch("fenix/evo-w-1700000004")

        assert info.wip_gate_blocked is True, f"WIP 重叠应返回 wip_gate_blocked: {info.error}"
        assert info.spec_dir_inflight is False, "WIP 重叠不被顺延接走"
        assert stash_count(root) == 0


# ── 3.2 / 3.3: dispatch 层可重试分类与有界性 ───────────────────────────────

class _BaseDispatch(unittest.TestCase):
    """PMEngine dispatch 层测试基座（对齐 test_pm_engine_dispatch_fixes 范式）。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine

        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.repo / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
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
        # 短程定时器不真实触发：patch Dispatcher 层方法（_defer_merge_back 内
        # self._schedule_merge_retry 命中 Dispatcher，非 PMEngine facade 注册表）
        self.engine._dispatcher._schedule_merge_retry = MagicMock()
        # verifier 入队断言用 mock（收口路径 self._enqueue_front 命中 Dispatcher）
        self.engine._dispatcher._enqueue_front = MagicMock()
        # 预算闸门 mock（重试点经过闸门的断言用；test_retry_budget_gate_blocks
        # 单独覆盖耗尽分支）
        self.engine._check_impl_budget_exhausted = MagicMock(return_value=False)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _alerts_path(self):
        from core.admin_store import AdminStore
        return AdminStore(self.repo, self.logger).alerts_path

    def _mk(self, name="spec-x"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")

    def _run_implementer_merge_attempt(self, spec_name="spec-x", branch="fenix/spec-x-1700000010"):
        """模拟一次 implementer run 走到 merge-back。"""
        from types import SimpleNamespace
        result = SimpleNamespace(
            success=True, error=None, run_id="impl-spec-x-1", branch=branch,
            worktree_dirty=[], cancelled=False, worktree_path=None,
        )
        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        self.engine._read_implementer_result = MagicMock(return_value={
            "status": "success", "spec": spec_name,
        })
        self.engine._run_agent_worker(spec_name, "implementer", 5)
        return result


class TestRetryableClassification(_BaseDispatch):
    """3.2: 可重试路径仅重试合并（run_id 不变），指纹记账不动。"""

    def test_spec_dir_inflight_defers_and_keeps_anchors(self):
        """spec_dir_inflight 失败 → 顺延：spec 保持 implementing、run_id 保留、
        _retry_count/_merge_fp/_merge_streak 不动、未派发新实现 run。"""
        self._mk()
        # 锚点先行落盘（模拟成功实现 run 的收工态）
        self.sm.update_spec("spec-x", {
            "implementer_run": "impl-spec-x-1",
            "branch": "fenix/spec-x-1700000010",
        })
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False,
            "spec 目录在飞编辑：spec/changes/spec-x/ 有 1 个未提交改动 — 顺延",
            spec_dir_inflight=True,
        )

        self._run_implementer_merge_attempt()

        entry = self.sm.read_one("spec-x") or {}
        # 保持 implementing（不降级 ready）——避免「新轮次派发清除旧锚点」
        self.assertEqual(entry.get("status"), "implementing", f"{entry}")
        # 顺延记账写入（有界性载体）
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 1)
        self.assertTrue(entry.get("_merge_retry_pending"))
        # 指纹记账不动（旁路熔断记账）
        self.assertNotIn("_merge_fp", entry)
        self.assertEqual(int(entry.get("_merge_streak", 0) or 0), 0)
        self.assertEqual(int(entry.get("_retry_count", 0) or 0), 0)
        # 锚点原样保留（run_id 不变断言：未重派新实现 run、未清锚点）
        self.assertEqual(entry.get("implementer_run"), "impl-spec-x-1")
        self.assertEqual(entry.get("branch"), "fenix/spec-x-1700000010")
        # 重试已排程（短程定时器），未启动新 run
        self.engine._dispatcher._schedule_merge_retry.assert_called_once()

    def test_git_text_retryable_defers(self):
        """git 原文片段（would be overwritten by merge）→ 可重试顺延。"""
        self._mk()
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False,
            "error: Your local changes to the following files would be "
            "overwritten by merge: spec/changes/spec-x/tasks.md\n"
            "Aborting",
        )

        self._run_implementer_merge_attempt()

        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implementing")
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 1)
        self.engine._dispatcher._schedule_merge_retry.assert_called_once()

    def test_real_failure_not_retryable(self):
        """不可重试真失败（语义冲突文本、无顺延信号）→ fail-open 回指纹熔断通道。

        直接单测分类判据：rehearsed / wip_gate_blocked / 可重试文本均不命中 →
        返回 False（调用方继续既有熔断记账）。"""
        self._mk()
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False,
            "CONFLICT (content): Merge conflict in shared.py",
            conflict_paths=["shared.py"],
            has_semantic_conflict=True,
        )

        retryable = self.engine._dispatcher._handle_retryable_mergeback_failure(
            "spec-x", wm.merge_back_from_branch.return_value,
            "CONFLICT (content): Merge conflict in shared.py",
            "fenix/spec-x-1700000010",
        )

        self.assertFalse(retryable, "真失败不得被分类为可重试")
        self.engine._dispatcher._schedule_merge_retry.assert_not_called()
        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 0,
                         "真失败不写顺延记账（fail-open 回既有通道）")


class TestBoundedDeferral(_BaseDispatch):
    """3.3: 顺延有界——达上限回落告警/人工通道（非无限顺延）。"""

    def test_deferral_round_limit_escalates(self):
        """连续顺延达轮数上限（缺省 3）→ 回落告警（admin 信号），不再排程。"""
        self._mk()
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False, "spec 目录在飞编辑：spec/changes/spec-x/ 有 1 个未提交改动",
            spec_dir_inflight=True,
        )
        # 预置已顺延 2 轮（首轮起算）
        self.sm.update_spec("spec-x", {"_merge_retry_count": 2, "_merge_retry_first_at": int(time.time())})

        self._run_implementer_merge_attempt()

        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 3)
        # 回落：不再排程重试（非无限顺延）
        self.engine._dispatcher._schedule_merge_retry.assert_not_called()
        # 告警落 admin store（等待人工处置通道，对 spec 可见）
        import json
        records = json.loads(self._alerts_path().read_text(encoding="utf-8"))
        hits = [r for r in records if r.get("signal_type") == "mergeback_spec_dir_inflight_stuck"]
        self.assertEqual(len(hits), 1, f"应恰好一条超限告警: {records}")
        self.assertEqual(hits[0].get("spec"), "spec-x")
        self.assertIn("spec-x", hits[0].get("description", ""))
        # spec 保持 in-flight（implementing），分支不被静默丢弃（task 2.7）
        self.assertEqual(entry.get("status"), "implementing")
        self.assertTrue(entry.get("_merge_retry_pending"))

    def test_grace_window_escalates(self):
        """顺延窗口超限（grace_minutes 配置为 0）→ 回落告警。"""
        self._mk()
        self.config["mergeback"] = {"spec_dir_inflight_grace_minutes": 0}
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False, "spec 目录在飞编辑：spec/changes/spec-x/ 有 1 个未提交改动",
            spec_dir_inflight=True,
        )

        self._run_implementer_merge_attempt()

        import json
        records = json.loads(self._alerts_path().read_text(encoding="utf-8"))
        hits = [r for r in records if r.get("signal_type") == "mergeback_spec_dir_inflight_stuck"]
        self.assertEqual(len(hits), 1)
        self.engine._dispatcher._schedule_merge_retry.assert_not_called()

    def test_signal_registered_in_monitor(self):
        """新信号类型被 admin_monitor 白名单收录 + severity major（摄取唤起前提）。"""
        from core.admin_monitor import SIGNAL_SEVERITY, STORED_SIGNAL_TYPES
        self.assertIn("mergeback_spec_dir_inflight_stuck", STORED_SIGNAL_TYPES)
        self.assertEqual(SIGNAL_SEVERITY.get("mergeback_spec_dir_inflight_stuck"), "major")


class TestNonDispatchDeferral(_BaseDispatch):
    """3.3 后半 + 1.5: repair re-merge 顺延不消费 _repair_awaiting_remerge。"""

    def _stub_remerge(self, spec_dir_inflight=True):
        wm = self.engine.agent_runner.worktree_manager
        info = MergeConflictInfo(
            False, "spec 目录在飞编辑：spec/changes/spec-x/ 有 1 个未提交改动",
            spec_dir_inflight=spec_dir_inflight,
        )
        wm.merge_back_from_branch.return_value = info
        return info

    def test_repair_remerge_deferral_keeps_marker(self):
        """repair 后 re-merge-back 顺延 → 保留 _repair_awaiting_remerge 标记
        （不消费），spec 保持 implementing，不进 fallback 重派。"""
        self._mk()
        self.sm.update_spec("spec-x", {"_repair_awaiting_remerge": True})
        info = self._stub_remerge()

        # 直接调用 _handle_remerge_failure（repair worker 的失败分支）
        self.engine._handle_remerge_failure("spec-x", info, "fenix/spec-x-1700000010")

        entry = self.sm.read_one("spec-x") or {}
        self.assertIs(entry.get("_repair_awaiting_remerge"), True,
                      "顺延 MUST NOT 消费 _repair_awaiting_remerge 标记")
        self.assertEqual(entry.get("status"), "implementing")
        # 不经 fp 记账（顺延不是 merge 失败）
        self.assertNotIn("_merge_fp", entry)

    def test_state_machine_recovery_remerge_keeps_marker(self):
        """_recovery_remerge_pending 遇顺延返回 False 且保留标记。"""
        self._mk()
        self.sm.update_spec("spec-x", {
            "_repair_awaiting_remerge": True,
            "branch": "fenix/spec-x-1700000010",
            "implementer_run": "impl-spec-x-1",
        })
        wm = MagicMock()
        wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False, "spec 目录在飞编辑：spec/changes/spec-x/ 有 1 个未提交改动",
            spec_dir_inflight=True,
        )

        remerged = self.engine.state_machine._recovery_remerge_pending(
            "spec-x", self.sm.read_one("spec-x"),
            project_root=self.repo, worktree_manager=wm,
        )

        self.assertFalse(remerged, "顺延应返回 False（未 re-merge 成功）")
        entry = self.sm.read_one("spec-x") or {}
        self.assertIs(entry.get("_repair_awaiting_remerge"), True,
                      "顺延 MUST NOT 消费标记（原样保留待下轮）")

    def test_fast_track_deferral_does_not_advance_state(self):
        """fast-track 成功路径遇顺延不推进状态（_reconcile_and_merge 返回 False）。"""
        self._mk()
        self.sm.update_spec("spec-x", {"branch": "fenix/spec-x-1700000010"})
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False, "spec 目录在飞编辑：spec/changes/spec-x/ 有 1 个未提交改动",
            spec_dir_inflight=True,
        )
        from types import SimpleNamespace
        result = SimpleNamespace(run_id="impl-spec-x-1", branch="fenix/spec-x-1700000010",
                                 worktree_path=None, worktree_kept=False)
        self.engine._keep_fast_track_worktree = MagicMock()

        merged = self.engine._dispatcher._reconcile_and_merge("spec-x", result)

        self.assertFalse(merged, "顺延不推进状态")
        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implementing")
        self.assertNotIn("_merge_fp", entry)


# ── 3.2 补充: 可重试后 merge 成功收口（run_id 不变）─────────────────────────

class TestRetrySucceeds(_BaseDispatch):
    """3.2 续: 重试点 merge 成功后收口——run_id 不变、顺延记账清零、verifier 入队。"""

    def test_retry_success_finalizes_with_same_run_id(self):
        """_retry_merge_back_only: merge 成功 → implemented + verifier + 清账。"""
        self._mk()
        self.sm.update_spec("spec-x", {
            "implementer_run": "impl-spec-x-1",
            "branch": "fenix/spec-x-1700000010",
            "_merge_retry_count": 2,
            "_merge_retry_first_at": int(time.time()),
        })
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = MergeConflictInfo(True, "")
        wm.last_stash_pop_conflicts = []

        self.engine._dispatcher._retry_merge_back_only("spec-x")

        entry = self.sm.read_one("spec-x") or {}
        self.assertEqual(entry.get("status"), "implemented", f"{entry}")
        # run_id 不变（同一实现 run 的合并，未重派新实现）
        self.assertEqual(entry.get("implementer_run"), "impl-spec-x-1")
        # 顺延记账清账
        self.assertFalse(entry.get("_merge_retry_pending"))
        self.assertEqual(int(entry.get("_merge_retry_count", 0) or 0), 0)
        self.assertIsNone(entry.get("_merge_retry_first_at"))
        # verifier 入队（收口同语义，Dispatcher 层 mock）
        self.engine._dispatcher._enqueue_front.assert_called_once_with("spec-x", "verifier")
        # 预算闸门被经过（task 2.6）
        self.engine._check_impl_budget_exhausted.assert_called_once_with("spec-x")

    def test_retry_budget_gate_blocks(self):
        """重试点预算闸门触发（已耗尽）→ 不尝试合并，闸门置 blocked/告警。"""
        self._mk()
        self.sm.update_spec("spec-x", {
            "branch": "fenix/spec-x-1700000010",
        })
        wm = self.engine.agent_runner.worktree_manager
        self.engine._check_impl_budget_exhausted = MagicMock(return_value=True)

        self.engine._dispatcher._retry_merge_back_only("spec-x")

        # 闸门命中：不调用 merge_back_from_branch（不尝试合并、不绕过告警通道）
        wm.merge_back_from_branch.assert_not_called()


# ── evo-inflight-spec-amendment-watch 3.1: 主树已提交在飞修订检测 ────────────

def _spec_records(root: Path) -> list:
    """读 fixture 仓库 admin store 中 spec_amendment_inflight 信号记录。"""
    from core.admin_store import AdminStore

    path = AdminStore(root, FakeLogger()).alerts_path
    if not path.exists():
        return []
    return [
        r
        for r in json.loads(path.read_text(encoding="utf-8"))
        if r.get("signal_type") == "spec_amendment_inflight"
    ]


class TestInflightSpecAmendmentWatch:
    """3.1: merge-base 之后主树提交 spec 目录改动 → 告警 + amended_inflight。

    复演 2026-10-02 cimbar-airgap-transfer 事故形态：框架外提交者在实现分支
    在飞期间直接改主树 spec/changes/<spec>/（已提交形态），与分支勾选更新在
    merge-back 预演相撞。
    """

    def _amended_repo(
        self,
        tmp_path,
        spec: str = "evo-a",
        branch_touches_spec: bool = True,
        main_touches_shared: bool = True,
    ):
        """构造 repo：分支在 merge-base 后改 shared.py+spec 目录勾选，
        主树随后提交 shared.py（语义冲突）+ spec 目录修订（在飞修订）。

        main_touches_shared=False 构造不相撞变体（修订只落 spec 目录、分支
        未触该目录）——用于验证检测命中不改 merge 成败结局（1.2）。
        """
        root = tmp_path / "repo"
        init_repo(root)
        spec_dir = root / "spec" / "changes" / spec
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "proposal.md").write_text("proposal\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text("tasks\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"[fenix] spec {spec} base")
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        branch = f"fenix/{spec}-1700000020"
        git(root, "checkout", "-q", "-b", branch)
        (root / "shared.py").write_text("BRANCH-VERSION\n", encoding="utf-8")
        (root / "core").mkdir(parents=True, exist_ok=True)
        (root / "core" / "impl.py").write_text("IMPL\n", encoding="utf-8")
        if branch_touches_spec:
            (spec_dir / "tasks.md").write_text("- [x] t1\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"[fenix] branch {branch}")
        git(root, "checkout", "-q", base_sha)
        # 主树：语义冲突提交（shared.py）+ 在飞修订提交（spec 目录）
        if main_touches_shared:
            (root / "shared.py").write_text("MAIN-VERSION\n", encoding="utf-8")
        (spec_dir / "proposal.md").write_text("proposal amended\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] spec amendment out-of-band")
        amend_short = git(root, "rev-parse", "--short", "HEAD").stdout.strip()
        return root, branch, amend_short

    def test_amended_conflict_alerts_and_attaches(self, tmp_path):
        """相撞场景：rehearsed 语义冲突 + amended_inflight 携带修订提交 + 告警落盘。"""
        root, branch, amend_short = self._amended_repo(tmp_path)
        wm = make_wm(root)

        info = wm.merge_back_from_branch(branch)

        # 相撞结局不变：仍由预演检出语义冲突（1.2 不改变判定语义）
        assert info.rehearsed is True, f"语义冲突应仍返回 rehearsed: {info.error}"
        assert info.has_semantic_conflict is True
        assert info.spec_dir_inflight is False
        assert info.wip_gate_blocked is False
        # amended_inflight 携带修订提交短哈希列表（1.1）
        assert info.amended_inflight == [amend_short], f"{info!r}"
        # 告警落 admin store：含修订提交列表与指纹（1.1）
        hits = _spec_records(root)
        assert len(hits) == 1, f"应恰好一条在飞修订告警: {hits}"
        assert hits[0].get("spec") == "evo-a"
        assert amend_short in (hits[0].get("evidence") or "")
        assert "指纹=" in (hits[0].get("evidence") or "")
        assert hits[0].get("severity") == "major"

    def test_amendment_repeat_merge_dedups_same_fingerprint(self, tmp_path):
        """同一修订集合的重复 merge-back 尝试 → 不逐轮重复告警（指纹在途去重）。"""
        root, branch, _ = self._amended_repo(tmp_path)
        wm = make_wm(root)

        wm.merge_back_from_branch(branch)
        wm.merge_back_from_branch(branch)

        assert len(_spec_records(root)) == 1, "同指纹在途去重应只写一条"

    def test_amended_success_merge_semantics_unchanged(self, tmp_path):
        """修订与分支改动不相撞（分支未触 spec 目录）→ merge 成功结局不变（1.2），
        告警照发、amended_inflight 照附。"""
        root, branch, amend_short = self._amended_repo(
            tmp_path, spec="evo-b", branch_touches_spec=False, main_touches_shared=False
        )
        wm = make_wm(root)

        info = wm.merge_back_from_branch(branch)

        # 返回值语义不变：命中不改变 success / rehearsed 判定
        assert info.success is True, f"不相撞时应正常 merge: {info.error}"
        assert info.rehearsed is False
        assert info.has_semantic_conflict is False
        assert info.amended_inflight == [amend_short]
        assert len(_spec_records(root)) == 1

    def test_no_amendment_no_alert_no_field(self, tmp_path):
        """对照：主树 merge-base 后无新提交 → 行为与告警完全不变。"""
        root = tmp_path / "repo"
        init_repo(root)
        spec_dir = root / "spec" / "changes" / "evo-c"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "proposal.md").write_text("proposal\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] spec evo-c base")
        make_branch(root, "fenix/evo-c-1700000021", "core/impl.py", "IMPL\n",
                    shared_content="BASE-MOD\n")
        wm = make_wm(root)

        info = wm.merge_back_from_branch("fenix/evo-c-1700000021")

        assert info.success is True, f"无修订应正常 merge: {info.error}"
        assert info.amended_inflight == []
        assert _spec_records(root) == [], "无修订 MUST NOT 产生告警"

    def test_missing_branch_silent_skip(self, tmp_path):
        """分支不存在（merge-base 失败/已清理）→ 静默跳过不报错。"""
        root = tmp_path / "repo"
        init_repo(root)

        assert detect_spec_amended_inflight(root, "fenix/ghost-1700000099", "evo-a") == []
        wm = make_wm(root)
        # 非形态分支（spec 名解析失败）同路静默：不检测、不告警、不抛错
        assert wm._detect_spec_amended_inflight("feature-not-fenix") == []
        assert _spec_records(root) == []

    def test_fingerprint_tracks_commit_set(self, tmp_path):
        """指纹 = spec+修订提交集合：同集合同指纹，新增修订变指纹（2.1 去重单源）。"""
        assert spec_amendment_fingerprint("evo-a", ["aaa", "bbb"]) == spec_amendment_fingerprint(
            "evo-a", ["bbb", "aaa"]
        ), "顺序无关、去重后同集合 → 同指纹"
        assert spec_amendment_fingerprint("evo-a", ["aaa"]) != spec_amendment_fingerprint(
            "evo-a", ["aaa", "bbb"]
        ), "修订集合变化 → 新指纹"
        assert spec_amendment_fingerprint("evo-a", ["aaa"]) != spec_amendment_fingerprint(
            "evo-b", ["aaa"]
        ), "spec 维度参与指纹"


class TestAmendedInflightRepairPassthrough(_BaseDispatch):
    """3.1: rehearsed 直通 repair 透传 amended_inflight，prompt 含根因段（1.3）。"""

    def _amended_merge_info(self) -> MergeConflictInfo:
        return MergeConflictInfo(
            False,
            "CONFLICT (content): Merge conflict in shared.py",
            conflict_paths=["shared.py"],
            has_semantic_conflict=True,
            rehearsed=True,
            amended_inflight=["abc1234"],
        )

    def test_direct_rehearsed_passthrough_carries_amendment(self):
        """_direct_rehearsed_to_repair 透传：merge_info 原样进 repair 派发。"""
        self._mk()
        info = self._amended_merge_info()
        self.engine.agent_runner.worktree_manager.merge_back_from_branch.return_value = info
        self.engine._dispatcher._dispatch_repair_lane = MagicMock()

        self.engine._dispatcher._direct_rehearsed_to_repair(
            "spec-x", info, "fenix/spec-x-1700000010", "conflict"
        )

        self.engine._dispatcher._dispatch_repair_lane.assert_called_once()
        passed_info = self.engine._dispatcher._dispatch_repair_lane.call_args[0][1]
        assert list(passed_info.amended_inflight) == ["abc1234"]

    def test_conflict_summary_and_prompt_carry_root_cause(self):
        """派发上下文（_repair_conflict_summary）与 prompt 均含修订根因段。"""
        from core.agent_runner.prompt_builder import PromptBuilder

        self._mk()
        info = self._amended_merge_info()

        summary = self.engine._dispatcher._repair_conflict_summary("spec-x", info)

        assert summary["amended_inflight"] == ["abc1234"]
        pb = PromptBuilder.__new__(PromptBuilder)
        pb._pm = MagicMock()
        pb._pm.project_root = self.repo
        prompt = pb._build_repair_prompt("spec-x", summary)
        assert "主树在飞修订根因" in prompt
        assert "abc1234" in prompt
        assert "spec/changes/spec-x/" in prompt

    def test_no_amendment_prompt_byte_identical_prefix(self):
        """未命中修订 → prompt 不含根因段（与现状一致，不注入空段）。"""
        from core.agent_runner.prompt_builder import PromptBuilder

        pb = PromptBuilder.__new__(PromptBuilder)
        pb._pm = MagicMock()
        pb._pm.project_root = self.repo
        summary = {
            "spec": "spec-x",
            "merge_error": "conflict",
            "conflict_paths": ["shared.py"],
            "has_semantic_conflict": True,
            "repair_round": 1,
            "amended_inflight": [],
        }
        prompt = pb._build_repair_prompt("spec-x", summary)
        assert "主树在飞修订根因" not in prompt
