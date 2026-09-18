"""add-merge-tree-rehearsal 测试：merge-back 前置预演（merge-tree 只读预演闸）。

覆盖 specs 全部 Scenario：
- 真合并前预演闸：零冲突预演放行（现行流程逐字节不变）、预演零副作用
  （主树无未合并条目 / 无 MERGE_HEAD / 无 stash 栈变化 / 工作区干净）
- 语义冲突零污染直通 repair：主树零污染直通、spec 保持 in-flight、_merge_streak
  无增量、repair 轮次上限兜底（回退 fallback 不产生无限 repair 循环）
- 产物冲突保持现行自愈：全部冲突为产物 / 被忽略的 DU 运行时草稿 → 放行真合并，
  既有自愈收口，不派发 repair
- git 版本探测回退：旧版 git（探测失败）→ 预演闸跳过 + 一次性 WARNING，行为回退现行
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.worktree_manager as worktree_manager
from core.pm_engine import PMEngine
from core.pm_engine.dispatch import MAX_REPAIR_ROUNDS_PER_FAILURE
from core.worktree_manager import MergeConflictInfo, WorktreeManager


class CapturingLogger:
    """记录 warning/error 文本，供断言使用。"""

    def __init__(self):
        self.warnings = []
        self.errors = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.warnings.append(msg)

    def error(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.errors.append(msg)


def git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", "main")
    return git(root, "rev-parse", "HEAD").stdout.strip()


def make_conflict_branch(root: Path, branch: str,
                         shared_content: str = "BRANCH\n") -> str:
    """从 main 派生分支：改 shared.py（制造语义冲突），提交后 checkout 回 main。

    只 stage shared.py——避免把 untracked 的 spec/ 卷进分支提交。
    """
    git(root, "checkout", "-q", "-b", branch)
    (root / "shared.py").write_text(shared_content, encoding="utf-8")
    git(root, "add", "-A", "--", "shared.py")
    git(root, "commit", "-q", "-m", f"[fenix] branch {branch}")
    git(root, "checkout", "-q", "main")
    return git(root, "rev-parse", "HEAD").stdout.strip()


def make_wm(root: Path, **kwargs) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, CapturingLogger(), **kwargs)


def _reset_rehearsal_probe():
    """重置类级探测缓存（进程内一次性探测，测试间相互独立）。"""
    WorktreeManager._rehearsal_probe_done = False
    WorktreeManager._rehearsal_supported = False


class TestRehearsalGate(unittest.TestCase):
    """git 层预演闸：零冲突放行 / 零副作用 / 语义直通 / 产物自愈 / ignored-DU。"""

    def setUp(self):
        _reset_rehearsal_probe()
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir) / "repo"
        init_repo(self.root)
        # 产物自愈用例（_branch_with_artifact_conflict / test_artifact_conflict_*）依赖
        # 「core/dashboard/static/dist 判真」，语义反转后须显式声明产物配置（未声明
        # 判定恒假=未裁决，产物冲突会退化为语义冲突）。
        self.wm = make_wm(
            self.root,
            build_artifact_paths=["core/dashboard/static/dist/"],
            has_build_artifacts=True,
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        _reset_rehearsal_probe()

    def _branch_with_clean_add(self, branch: str) -> str:
        """分支干净新增文件（与 main 无冲突），提交后回 main。"""
        git(self.root, "checkout", "-q", "-b", branch)
        (self.root / "add.txt").write_text("ADDED\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", f"[fenix] branch {branch}")
        git(self.root, "checkout", "-q", "main")
        return branch

    def _branch_with_semantic_conflict(self, branch: str) -> str:
        """分支改 shared.py + main 侧再改 shared.py（内容不同 → 语义冲突）。"""
        make_conflict_branch(self.root, branch, "BRANCH-IMPL\n")
        (self.root / "shared.py").write_text("MAIN-IMPL\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main shared.py change")
        return branch

    def _branch_with_artifact_conflict(self, branch: str) -> str:
        """分支与 main 都重建 dist（内容哈希文件名 rename 冲突，产物自愈适用）。"""
        dist = "core/dashboard/static/dist"
        d = self.root / dist
        d.mkdir(parents=True)
        (d / "umi.aaa.js").write_text("V1\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] seed dist")
        # 分支侧重建
        git(self.root, "checkout", "-q", "-b", branch)
        git(self.root, "mv", f"{dist}/umi.aaa.js", f"{dist}/umi.bbb.js")
        git(self.root, "commit", "-q", "-m", "[fenix] branch dist rebuild")
        git(self.root, "checkout", "-q", "main")
        # main 侧重建（不同名字 → rename/rename 冲突，但全产物 → 自愈）
        git(self.root, "mv", f"{dist}/umi.aaa.js", f"{dist}/umi.ccc.js")
        git(self.root, "commit", "-q", "-m", "[fenix] main dist rebuild")
        return branch

    # ── Scenario: 零冲突预演放行 ──────────────────────────────────────────

    def test_zero_conflict_pass_through_real_merge(self):
        """分支与 main 无潜在冲突 → 现行真合并流程原样执行。"""
        branch = self._branch_with_clean_add("fenix/clean-1")
        info = self.wm.merge_back_from_branch(branch)
        self.assertTrue(info.success, f"零冲突 merge 应成功: {info.error}")
        self.assertFalse(info.rehearsed)
        # 真合并产物在（放行现行流程，而非直通）
        self.assertTrue((self.root / "add.txt").exists())
        # 工作区干净（真合并已提交）
        self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")

    def test_zero_conflict_no_rehearsal_error(self):
        """零冲突放行：返回的 info 不含冲突路径与语义分类。"""
        branch = self._branch_with_clean_add("fenix/clean-2")
        info = self.wm.merge_back_from_branch(branch)
        self.assertTrue(info.success)
        self.assertEqual(info.conflict_paths, [])
        self.assertFalse(info.has_semantic_conflict)

    # ── Scenario: 预演零副作用 ─────────────────────────────────────────────

    def test_rehearsal_zero_side_effects(self):
        """预演执行完成（无论结论如何）→ 主树无未合并条目、无 MERGE_HEAD、
        无 stash 栈变化、工作区干净。"""
        branch = self._branch_with_semantic_conflict("fenix/sem-1")
        info = self.wm.merge_back_from_branch(branch)
        self.assertTrue(info.rehearsed)
        # 主树完全未被 stash/merge/abort 触碰
        self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")
        self.assertEqual(git(self.root, "ls-files", "-u").stdout.strip(), "")
        self.assertFalse((self.root / ".git" / "MERGE_HEAD").exists())
        self.assertEqual(git(self.root, "stash", "list").stdout.strip(), "")
        # 分支提交原样保留（未合入也未丢弃）
        self.assertEqual(
            git(self.root, "rev-parse", "fenix/sem-1").stdout.strip(),
            git(self.root, "rev-parse", "fenix/sem-1^{commit}").stdout.strip(),
        )

    # ── Scenario: 语义冲突直通 repair（git 层返回 rehearsed 标记）────────────

    def test_semantic_conflict_rehearsed_direct(self):
        """预演检出语义冲突 → 跳过 stash/merge/abort 全序列，返回 rehearsed
        标记的结构化冲突分类（冲突路径清单只含语义文件）。"""
        branch = self._branch_with_semantic_conflict("fenix/sem-2")
        info = self.wm.merge_back_from_branch(branch)
        self.assertFalse(info.success)
        self.assertTrue(info.rehearsed)
        self.assertTrue(info.has_semantic_conflict)
        self.assertFalse(info.self_heal_applicable)
        # 冲突清单只含语义路径（与 abort 后分类口径一致，产物路径不污染）
        self.assertEqual(info.conflict_paths, ["shared.py"])

    def test_semantic_conflict_workspace_untouched(self):
        """语义冲突直通：主树工作区文件内容未变（无 autostash 收拢/弹回）。"""
        branch = self._branch_with_semantic_conflict("fenix/sem-3")
        info = self.wm.merge_back_from_branch(branch)
        self.assertTrue(info.rehearsed)
        # 主树 shared.py 保持 main 侧内容（未被分支侧覆盖/还原）
        self.assertEqual(
            (self.root / "shared.py").read_text(encoding="utf-8"), "MAIN-IMPL\n")

    # ── Scenario: 产物冲突走自愈真合并 ─────────────────────────────────────

    def test_artifact_conflict_pass_through_self_heal(self):
        """预演检出冲突且全部路径属于产物目录 → 放行真合并，产物自愈收口。"""
        branch = self._branch_with_artifact_conflict("fenix/art-1")
        info = self.wm.merge_back_from_branch(branch)
        self.assertTrue(info.success, f"产物冲突应自愈: {info.error}")
        self.assertFalse(info.rehearsed)
        self.assertTrue(info.self_heal_succeeded)
        # 主树布局保留（对齐 HEAD 版），工作区干净
        d = self.root / "core" / "dashboard" / "static" / "dist"
        self.assertTrue((d / "umi.ccc.js").exists())
        self.assertFalse((d / "umi.aaa.js").exists())
        self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")

    def test_ignored_du_pass_through_self_heal(self):
        """预演检出冲突全部为被忽略的 DU 运行时草稿 → 放行真合并走 ignored 自愈。"""
        (self.root / ".gitignore").write_text("*.log\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] gitignore logs")
        branch = "fenix/ig-1"
        (self.root / "runtime.log").write_text("V1\n", encoding="utf-8")
        git(self.root, "add", "-f", "runtime.log")
        git(self.root, "commit", "-q", "-m", "[fenix] track runtime.log")
        git(self.root, "checkout", "-q", "-b", branch)
        (self.root / "runtime.log").write_text("V2-BRANCH\n", encoding="utf-8")
        git(self.root, "add", "-f", "runtime.log")
        git(self.root, "commit", "-q", "-m", "[fenix] branch modifies runtime.log")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "rm", "-q", "runtime.log")
        git(self.root, "commit", "-q", "-m", "[fenix] main deletes runtime.log")

        info = self.wm.merge_back_from_branch(branch)
        self.assertTrue(info.success, f"ignored-DU 应自愈: {info.error}")
        self.assertFalse(info.rehearsed)
        # 工作区干净（merge 已提交，采纳主树删除）
        self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")


class TestRehearsedDispatch(unittest.TestCase):
    """调度层 rehearsed 直通：implementer/fast-track 直通 repair、无 fp 增量、
    spec 保持 in-flight、轮次兜底、re-merge 失败链熔断保持。"""

    def setUp(self):
        _reset_rehearsal_probe()
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.root = self.pr / "repo"
        self.spec = "demo"
        init_repo(self.root)
        self.spec_dir = self.root / "spec" / "changes" / self.spec
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        (self.spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.logger = CapturingLogger()
        from core.state_machine import StateMachine
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.root, self.logger)
        self.wm = make_wm(self.root)
        self.engine.agent_runner.worktree_manager = self.wm
        # 拦截队列处理（避免 repair/verifier 派发真实线程干扰断言）
        self.engine._process_queue = MagicMock()
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.transition(self.spec, "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        _reset_rehearsal_probe()

    def _make_semantic_conflict_branch(self) -> str:
        branch = f"fenix/{self.spec}-123"
        make_conflict_branch(self.root, branch, "BRANCH-IMPL\n")
        (self.root / "shared.py").write_text("MAIN-IMPL\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main shared.py change")
        return branch

    def _mock_implementer_success(self, branch: str):
        from core.agent_runner import AgentRunResult
        result = AgentRunResult(
            run_id=f"impl-{self.spec}-1", spec_name=self.spec,
            agent_type="implementer", success=True, duration_seconds=1.0,
            branch=branch,
        )
        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        (self.root / ".fenix" / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": self.spec}), encoding="utf-8")

    def _make_ft_result(self, branch: str):
        from core.agent_runner import AgentRunResult
        return AgentRunResult(
            run_id=f"impl-{self.spec}-1", spec_name=self.spec,
            agent_type="fast-track", success=True, duration_seconds=1.0,
            branch=branch,
        )

    # ── Scenario: 语义冲突直通 repair（implementer 路径）────────────────────

    def test_implementer_rehearsed_direct_repair_no_fp(self):
        """预演语义冲突 → 直通 repair：不经 _merge_fp/_merge_streak 记账、
        不降级 ready、spec 保持 implementing。"""
        branch = self._make_semantic_conflict_branch()
        self._mock_implementer_success(branch)
        self.engine._dispatcher._dispatch_repair_lane = MagicMock()
        self.sm.transition(self.spec, "implementing")
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        # 直通 repair，而非普通重试
        self.engine._dispatcher._dispatch_repair_lane.assert_called_once()
        # spec 保持 in-flight（不降级 ready）
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "implementing")
        # 不经 fp 记账：_merge_fp/_merge_streak 无增量（直通路径从不写入）
        self.assertIsNone(entry.get("_merge_fp"))
        self.assertIsNone(entry.get("_merge_streak"))

    def test_rehearsed_error_not_persisted_to_spec(self):
        """直通 repair 不把预演冲突错误写进 spec.error（与 abort 后路径可区分）。"""
        branch = self._make_semantic_conflict_branch()
        self._mock_implementer_success(branch)
        self.engine._dispatcher._dispatch_repair_lane = MagicMock()
        self.sm.transition(self.spec, "implementing")
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        entry = self.sm.read_one(self.spec)
        # 预演直通不经 ready 降级，error 字段不携带 merge 失败上下文
        self.assertNotIn("rehearsal", entry.get("error") or "")

    # ── Scenario: 语义冲突直通 repair（fast-track 路径）─────────────────────

    def test_fast_track_rehearsed_direct_repair(self):
        """fast-track 预演语义冲突 → 直通 repair，不经 fp 记账、spec 保持 in-flight。"""
        branch = self._make_semantic_conflict_branch()
        self.sm.transition(self.spec, "implementing")
        self.engine._dispatcher._dispatch_repair_lane = MagicMock()
        merged = self.engine._dispatcher._reconcile_and_merge(
            self.spec, self._make_ft_result(branch))
        self.assertFalse(merged)
        self.engine._dispatcher._dispatch_repair_lane.assert_called_once()
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "implementing")
        self.assertIsNone(entry.get("_merge_fp"))
        # repair 调用携带实现分支（repair agent 在分支上 merge main 原地修复）
        call_args = self.engine._dispatcher._dispatch_repair_lane.call_args
        self.assertEqual(call_args.args[2], branch)

    # ── Scenario: repair 轮次上限仍兜底 ────────────────────────────────────

    def test_rehearsed_round_limit_falls_back(self):
        """直通 repair 连续超过 _repair_round 上限仍无法消化冲突 →
        回退现行 fallback 重派路径，不产生无限 repair 循环。"""
        branch = self._make_semantic_conflict_branch()
        self._mock_implementer_success(branch)
        self.sm.update_spec(self.spec, {
            "status": "implementing",
            "_repair_round": MAX_REPAIR_ROUNDS_PER_FAILURE,
        })
        self.engine._dispatcher._dispatch_repair_lane = MagicMock()
        self.engine._dispatcher._fallback_after_repair = MagicMock()
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        # 轮次超限：不派 repair，回退 fallback 重派
        self.engine._dispatcher._dispatch_repair_lane.assert_not_called()
        self.engine._dispatcher._fallback_after_repair.assert_called_once()

    def test_rehearsed_blocked_spec_falls_back(self):
        """blocked spec 的预演语义冲突不派 repair（_should_enter_repair 拦截）。"""
        branch = self._make_semantic_conflict_branch()
        self._mock_implementer_success(branch)
        self.sm.update_spec(self.spec, {"status": "blocked"})
        self.engine._dispatcher._dispatch_repair_lane = MagicMock()
        self.engine._dispatcher._fallback_after_repair = MagicMock()
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        self.engine._dispatcher._dispatch_repair_lane.assert_not_called()

    # ── Scenario: repair 后 re-merge 失败链保持现行 fp 熔断 ────────────────

    def test_remerge_failure_keeps_fp_breaker(self):
        """repair 后 re-merge 预演语义冲突再失败 → 仍走既有 fp 熔断链
        （repair 轮不清零 _merge_fp/_merge_streak）。"""
        error_text = ("Semantic merge conflicts detected by pre-merge rehearsal "
                      "(1 path(s))")
        fp = self.engine._merge_fingerprint(error_text)
        self.sm.update_spec(self.spec, {
            "status": "implementing",
            "_merge_fp": fp,
            "_merge_streak": 1,
            "_repair_round": 1,
        })
        remerge_info = MergeConflictInfo(
            False, error_text, conflict_paths=["shared.py"],
            has_semantic_conflict=True, rehearsed=True)
        self.engine._handle_remerge_failure(self.spec, remerge_info, "fenix/demo-123")
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "blocked")
        self.assertEqual(int(entry["_merge_streak"] or 0), 2)


class TestRehearsalProbe(unittest.TestCase):
    """git 版本探测：一次性探测缓存、旧版回退、单次 WARNING、不反复探测。"""

    def setUp(self):
        _reset_rehearsal_probe()
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir) / "repo"
        init_repo(self.root)
        self.wm = make_wm(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        _reset_rehearsal_probe()

    def test_probe_supported_on_real_git(self):
        """真实 git（≥ 2.38）探测通过；缓存命中不重复探测。"""
        self.assertTrue(self.wm._merge_tree_supported())
        self.assertTrue(WorktreeManager._rehearsal_probe_done)
        # 二次调用命中类级缓存（无额外探测、无额外日志）
        self.assertTrue(self.wm._merge_tree_supported())

    def test_old_git_probe_failure_warns_once(self):
        """探测失败（unknown option）→ 单次 WARNING + 预演闸跳过 + 行为回退现行。"""
        real_run = worktree_manager.subprocess.run

        def fake_run(cmd, *a, **k):
            if "merge-tree" in cmd:
                class R:
                    returncode = 129
                    stderr = "error: unknown option `--write-tree'"
                    stdout = ""
                return R()
            return real_run(cmd, *a, **k)

        worktree_manager.subprocess.run = fake_run
        try:
            # 探测失败 → 不支持
            self.assertFalse(self.wm._merge_tree_supported())
            # 单次 WARNING（含一次性说明）
            warns = [w for w in self.wm.logger.warnings if "merge-tree" in w]
            self.assertEqual(len(warns), 1)
            self.assertIn("git ≥ 2.38", warns[0])
            # 不反复探测、不刷屏：二次调用无新 WARNING
            self.assertFalse(self.wm._merge_tree_supported())
            warns2 = [w for w in self.wm.logger.warnings if "merge-tree" in w]
            self.assertEqual(len(warns2), 1)
            # 预演闸跳过：语义冲突也走现行 abort 路径（无 rehearsed 标记）
            branch = "fenix/old-git-1"
            make_conflict_branch(self.root, branch, "BRANCH\n")
            (self.root / "shared.py").write_text("MAIN\n", encoding="utf-8")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-q", "-m", "[fenix] main shared.py change")
            info = self.wm.merge_back_from_branch(branch)
            self.assertFalse(info.rehearsed, "旧版 git 不应预演")
            self.assertFalse(info.success)
            self.assertTrue(info.has_semantic_conflict)
            # abort 后主树干净（现行行为）
            self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")
        finally:
            worktree_manager.subprocess.run = real_run


if __name__ == "__main__":
    unittest.main()
