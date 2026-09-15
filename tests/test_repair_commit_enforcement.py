"""fix-repair-commit-enforcement — repair git 事实复核 + prompt 契约 单测。

覆盖 SPEC tasks 5.1/5.2/5.3：
  - 5.1: 四态覆盖——分支 tip 未前进 → 判未完成并回退；有未合并条目 → 判未完成；
         有 MERGE_HEAD → 判未完成；真提交 → 放行 re-merge-back
  - 5.2: prompt 契约——「先提交后测试」顺序 + 定向回归/有界超时措辞 +
         开场清理残留 merge 步骤
  - 5.3: 回退上下文——因 tip 未前进回退时，注入的 merge 失败上下文含
         「未提交/分支 tip 未前进」具体事实而非笼统原因

基于真实 git 仓库 fixture（与 test_mergeback_repair_lane / test_repair_remerge_pending
同构），不启动真实 daemon。
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

from core.pm_engine import PMEngine
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
    base = git(root, "rev-parse", "HEAD").stdout.strip()
    git(root, "branch", "-M", "main")
    return base


def make_conflict_branch(root: Path, branch: str, shared_content: str = "BRANCH\n"):
    """从 main 派生分支：改 shared.py（制造语义冲突），提交后 checkout 回 main。"""
    git(root, "checkout", "-q", "-b", branch)
    (root / "shared.py").write_text(shared_content, encoding="utf-8")
    git(root, "add", "-A", "--", "shared.py")
    git(root, "commit", "-q", "-m", f"[fenix] branch {branch}")
    git(root, "checkout", "-q", "main")


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, CapturingLogger())


def _success_result(spec: str):
    from core.agent_runner import AgentRunResult
    return AgentRunResult(
        run_id=f"repair-{spec}-1", spec_name=spec, agent_type="repair",
        success=True, duration_seconds=1.0, branch=f"fenix/{spec}-123",
    )


# ── 5.1: 四态覆盖 ─────────────────────────────────────────────────────────


class TestRepairGitFactsFourStates(unittest.TestCase):
    """fix-repair-commit-enforcement 5.1: _run_repair_worker 四态——
    分支 tip 未前进 / 有未合并条目 / 有 MERGE_HEAD / 真提交。

    每个子测试构造 worktree 现场并跑 _run_repair_worker，断言：复核通过→implemented
    或复核失败→status=ready 且 error 含具体事实。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir) / "repo"
        self.spec = "demo"
        init_repo(self.root)
        spec_dir = self.root / "spec" / "changes" / self.spec
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.logger = CapturingLogger()
        from core.state_machine import StateMachine
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.root, self.logger)
        self.wm = make_wm(self.root)
        self.engine.agent_runner.worktree_manager = self.wm
        self.engine._process_queue = MagicMock()
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.transition(self.spec, "ready")
        self.sm.transition(self.spec, "implementing")
        # 记录 merge_back_from_branch 返回值（同 TestRepairWorker 风格）
        self.branch = self._conflicted_branch()
        self.merge_info = self.wm.merge_back_from_branch(self.branch)
        self.assertFalse(self.merge_info.success)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _conflicted_branch(self) -> str:
        branch = f"fenix/{self.spec}-123"
        make_conflict_branch(self.root, branch, "BRANCH-IMPL\n")
        (self.root / "shared.py").write_text("MAIN-IMPL\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main shared.py")
        return branch

    def _set_base_tip(self):
        """模拟 _dispatch_repair_lane 记录基准 tip（实际由 wm.branch_tip 获取）。"""
        base_tip = git(self.root, "rev-parse", self.branch).stdout.strip()
        self.sm.update_spec(self.spec, {"_repair_base_tip": base_tip})

    def _make_wt(self) -> Path:
        """换壳建 repair worktree（三态 b）。"""
        wt, _ = self.wm.resolve_repair_site(self.spec, self.branch)
        self.assertIsNotNone(wt)
        return wt

    # ── 态 1: 分支 tip 未前进 → 判未完成 ─────────────────────────────────

    def test_tip_not_advanced_declares_incomplete(self):
        """repair agent 声称成功但分支 tip 未前进（无提交）→ 判未完成并 fallback。"""
        wt = self._make_wt()
        self._set_base_tip()
        # repair agent 什么都不做（tip 未变），只写成功结果文件
        (wt / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": self.spec}), encoding="utf-8")
        self.engine.agent_runner.run_repair = MagicMock(return_value=_success_result(self.spec))
        self.engine._run_repair_worker(self.spec, wt, self.branch, self.merge_info)
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "ready",
                         "tip 未前进 → 复核失败 → fallback ready")
        self.assertIn("分支 tip 未前进", entry["error"],
                       "错误文本须含「分支 tip 未前进」具体事实")
        self.assertIn("可能只暂存未提交", entry["error"])
        # base tip SHA 出现在错误信息里
        base_tip = self.sm.read_one(self.spec).get("_repair_base_tip") or ""
        # fallback 清零了 _repair_base_tip
        self.assertIsNone(self.sm.read_one(self.spec).get("_repair_base_tip"))

    # ── 态 2: 有未合并条目 → 判未完成 ────────────────────────────────────

    def test_unmerged_files_declares_incomplete(self):
        """worktree 有未解决冲突（git ls-files -u 非空）→ 判未完成。"""
        wt = self._make_wt()
        self._set_base_tip()
        # 在 worktree 里发起 merge（冲突不解决）→ 有 unmerged
        proc = subprocess.run(
            ["git", "-C", str(wt), "merge", "-q", "main"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0, "merge 应产生冲突")
        # 写成功结果文件
        (wt / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": self.spec}), encoding="utf-8")
        self.engine.agent_runner.run_repair = MagicMock(return_value=_success_result(self.spec))
        self.engine._run_repair_worker(self.spec, wt, self.branch, self.merge_info)
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "ready",
                         "有未合并条目 → 复核失败 → fallback ready")
        self.assertIn("未解决冲突残留", entry["error"],
                       "错误文本须含「未解决冲突残留」具体事实")

    # ── 态 3: 有 MERGE_HEAD → 判未完成 ───────────────────────────────────

    def test_merge_head_declares_incomplete(self):
        """worktree 有未完成 merge（MERGE_HEAD 存在）→ 判未完成。

        构造方法：merge → add -A 解决（清除 unmerged）→ 不 commit →
        MERGE_HEAD 残留。
        """
        wt = self._make_wt()
        self._set_base_tip()
        # 在 worktree 里发起 merge（冲突）
        subprocess.run(
            ["git", "-C", str(wt), "merge", "-q", "main"],
            capture_output=True, text=True,
        )
        # 解决冲突（stage，清除 unmerged）
        subprocess.run(
            ["git", "-C", str(wt), "add", "-A"],
            capture_output=True, text=True,
        )
        # 不 commit → MERGE_HEAD 仍在
        # 验证现场：unmerged 为空、MERGE_HEAD 存在
        facts = self.wm.repair_site_facts(wt)
        self.assertEqual(facts["unmerged"], [], "unmerged 应已清除（stage 后）")
        self.assertTrue(facts["merge_head"], "MERGE_HEAD 应仍存在（未 commit）")
        # 写成功结果文件
        (wt / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": self.spec}), encoding="utf-8")
        self.engine.agent_runner.run_repair = MagicMock(return_value=_success_result(self.spec))
        self.engine._run_repair_worker(self.spec, wt, self.branch, self.merge_info)
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "ready",
                         "有 MERGE_HEAD → 复核失败 → fallback ready")
        self.assertIn("未完成 merge（MERGE_HEAD）", entry["error"],
                       "错误文本须含「MERGE_HEAD」具体事实")

    # ── 态 4: 真提交 → 放行 re-merge-back → implemented ─────────────────

    def test_real_commit_passes_and_advances(self):
        """真提交（git merge 提交）→ tip 前进、无冲突残留、无 MERGE_HEAD →
        复核通过 → re-merge-back → implemented。"""
        wt = self._make_wt()
        self._set_base_tip()
        # 真 merge 提交（自动解决：-X theirs）
        subprocess.run(
            ["git", "-C", str(wt), "merge", "-q", "main", "-X", "theirs",
             "-m", f"[fenix] {self.spec}: resolve merge conflicts"],
            capture_output=True, text=True,
        )
        # 验证现场：无冲突残留、无 MERGE_HEAD、分支 tip 已前进
        # （linked worktree 内提交会推进共享 refs/heads/<branch>，主仓库
        # `git rev-parse <branch>` 直接可见）
        facts = self.wm.repair_site_facts(wt)
        self.assertEqual(facts["unmerged"], [])
        self.assertFalse(facts["merge_head"])
        base_tip = self.sm.read_one(self.spec).get("_repair_base_tip")
        now_tip = git(self.root, "rev-parse", self.branch).stdout.strip()
        self.assertIsNotNone(base_tip)
        self.assertNotEqual(now_tip, base_tip, "分支 tip 应已前进（merge commit）")
        # 写成功结果文件
        (wt / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": self.spec}), encoding="utf-8")
        self.engine.agent_runner.run_repair = MagicMock(return_value=_success_result(self.spec))
        self.engine._run_repair_worker(self.spec, wt, self.branch, self.merge_info)
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "implemented",
                         "真提交 → 复核通过 → re-merge-back → implemented")
        # _repair_base_tip 已清零（任务 1.4）
        self.assertIsNone(entry.get("_repair_base_tip"),
                          "re-merge 成功 → _repair_base_tip 清零")


# ── 5.1 + 5.3: 补充态——_check_repair_commit_facts 单独单测（纯函数/独立方法）──


class TestCheckRepairCommitFacts(unittest.TestCase):
    """fix-repair-commit-enforcement D5: 判定逻辑可测试的纯组合判定。

    直接测试 _check_repair_commit_facts 的四态输入输出（不经过 _run_repair_worker
    完整链路），验证返回值与错误文本。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir) / "repo"
        self.spec = "demo"
        init_repo(self.root)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        from core.state_machine import StateMachine
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", CapturingLogger())
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.root, CapturingLogger())
        self.wm = make_wm(self.root)
        self.engine.agent_runner.worktree_manager = self.wm
        # spec 必须在册：_set_base_tip 的 update_spec 对不存在的 spec 是 no-op
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.transition(self.spec, "ready")
        self.sm.transition(self.spec, "implementing")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_base_tip(self, branch: str):
        base_tip = git(self.root, "rev-parse", branch).stdout.strip()
        self.sm.update_spec(self.spec, {"_repair_base_tip": base_tip})

    # ── 全 ok → (True, "") ───────────────────────────────────────────────

    def test_all_ok_returns_true(self):
        """worktree 干净 + tip 前进 + 基准可判 → (True, "")。"""
        branch = f"fenix/{self.spec}-1"
        make_conflict_branch(self.root, branch, "A\n")
        (self.root / "shared.py").write_text("B\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main")
        self._set_base_tip(branch)
        wt, _ = self.wm.resolve_repair_site(self.spec, branch)
        self.assertIsNotNone(wt)
        # 真提交
        subprocess.run(
            ["git", "-C", str(wt), "merge", "-q", "main", "-X", "theirs",
             "-m", "merge"], capture_output=True, text=True,
        )
        ok, err = self.engine._check_repair_commit_facts(self.spec, wt, branch)
        self.assertTrue(ok)
        self.assertEqual(err, "")

    # ── tip 未前进 → (False, 含「分支 tip 未前进」) ──────────────────────

    def test_tip_not_advanced_returns_false_with_detail(self):
        """分支 tip 未前进 → (False, error 含「分支 tip 未前进」和 SHA)。"""
        branch = f"fenix/{self.spec}-1"
        make_conflict_branch(self.root, branch, "A\n")
        (self.root / "shared.py").write_text("B\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main")
        self._set_base_tip(branch)
        wt, _ = self.wm.resolve_repair_site(self.spec, branch)
        self.assertIsNotNone(wt)
        # 什么都没做（tip 未变）
        ok, err = self.engine._check_repair_commit_facts(self.spec, wt, branch)
        self.assertFalse(ok)
        self.assertIn("分支 tip 未前进", err)
        self.assertIn("可能只暂存未提交", err)

    # ── 有未合并条目 → (False, 含「未解决冲突残留」) ──────────────────────

    def test_unmerged_files_returns_false_with_detail(self):
        """worktree 有 unmerged → (False, error 含「未解决冲突残留」和计数）。"""
        branch = f"fenix/{self.spec}-1"
        make_conflict_branch(self.root, branch, "A\n")
        (self.root / "shared.py").write_text("B\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main")
        wt, _ = self.wm.resolve_repair_site(self.spec, branch)
        self.assertIsNotNone(wt)
        # 冲突未解决
        subprocess.run(
            ["git", "-C", str(wt), "merge", "-q", "main"],
            capture_output=True, text=True,
        )
        # 不设 base tip（未合并条目优先于 tip 校验）
        ok, err = self.engine._check_repair_commit_facts(self.spec, wt, branch)
        self.assertFalse(ok)
        self.assertIn("未解决冲突残留", err)
        self.assertIn("1 个文件", err)

    # ── 有 MERGE_HEAD → (False, 含「未完成 merge」) ──────────────────────

    def test_merge_head_returns_false_with_detail(self):
        """MERGE_HEAD 存在 → (False, error 含「未完成 merge（MERGE_HEAD）」)。"""
        branch = f"fenix/{self.spec}-1"
        make_conflict_branch(self.root, branch, "A\n")
        (self.root / "shared.py").write_text("B\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main")
        wt, _ = self.wm.resolve_repair_site(self.spec, branch)
        self.assertIsNotNone(wt)
        # 冲突 → stage（清除 unmerged）→ MERGE_HEAD 残留
        subprocess.run(
            ["git", "-C", str(wt), "merge", "-q", "main"],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "-C", str(wt), "add", "-A"],
            capture_output=True, text=True,
        )
        ok, err = self.engine._check_repair_commit_facts(self.spec, wt, branch)
        self.assertFalse(ok)
        self.assertIn("未完成 merge（MERGE_HEAD）", err)

    # ── 基准 tip 缺失 → 保守放行（仅查冲突残留 + MERGE_HEAD）────────────

    def test_missing_base_tip_skips_tip_check(self):
        """_repair_base_tip 缺失 → 跳过 tip 前进校验，只查冲突残留 + MERGE_HEAD。
        worktree 干净 → 保守放行 (True, "")。"""
        branch = f"fenix/{self.spec}-1"
        make_conflict_branch(self.root, branch, "A\n")
        (self.root / "shared.py").write_text("B\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main")
        # 不设置 _repair_base_tip（模拟老状态迁移）
        wt, _ = self.wm.resolve_repair_site(self.spec, branch)
        self.assertIsNotNone(wt)
        ok, err = self.engine._check_repair_commit_facts(self.spec, wt, branch)
        self.assertTrue(ok, "基准 tip 缺失 → 保守放行")
        self.assertEqual(err, "")


# ── 5.2: prompt 契约断言 ──────────────────────────────────────────────────


class TestRepairPromptContract(unittest.TestCase):
    """fix-repair-commit-enforcement 5.2: prompt 契约——
    「先提交后测试」顺序 + 定向回归/有界超时措辞 + 开场清理残留 merge 步骤。
    """

    def setUp(self):
        from core.agent_runner.prompt_builder import PromptBuilder
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.pb = PromptBuilder(MagicMock())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_prompt(self, spec="demo", repair_round=1):
        conflict_summary = {
            "spec": spec,
            "merge_error": "CONFLICT (content): Merge conflict in shared.py",
            "conflict_paths": ["shared.py"],
            "has_semantic_conflict": True,
            "repair_round": repair_round,
        }
        return self.pb._build_prompt(spec, "repair", detail=conflict_summary)

    def test_commit_before_test_order(self):
        """步骤 5（commit）在步骤 6（测试）之前。"""
        prompt = self._make_prompt()
        # 「提交冲突解决」出现在「定向回归」之前
        commit_pos = prompt.find("**提交冲突解决（强制终点，先于测试）**")
        test_pos = prompt.find("定向回归（提交之后）")
        self.assertGreater(commit_pos, 0, "应包含提交步骤")
        self.assertGreater(test_pos, 0, "应包含定向回归步骤")
        self.assertLess(commit_pos, test_pos, "提交必须在测试之前")

    def test_directed_test_and_timeout_phrasing(self):
        """prompt 包含「定向回归」和「有界超时」措辞。"""
        prompt = self._make_prompt()
        self.assertIn("定向回归", prompt, "须含「定向回归」措辞")
        self.assertIn("有界超时", prompt, "须含「有界超时」措辞")
        self.assertIn("timeout 600", prompt, "须含定向回归示例 timeout 600")
        # 「不要以全量套件作为提交前置」以否定形式出现在限制中
        self.assertIn("不要以全量套件作为提交前置", prompt)

    def test_openscreen_cleanup_merge_step(self):
        """步骤 1 为开场清理残留 merge。"""
        prompt = self._make_prompt()
        self.assertIn("开场清理残留 merge", prompt, "须包含开场清理残留 merge 步骤")
        self.assertIn("git merge --abort", prompt, "须含 git merge --abort 指引")
        self.assertIn("MERGE_HEAD", prompt, "须提 MERGE_HEAD 检测")

    def test_commit_mandatory_before_any_test(self):
        """「提交是本轮 repair 的强制终点，必须在运行任何测试之前完成」。"""
        prompt = self._make_prompt()
        self.assertIn("提交是本轮 repair 的强制终点，必须在运行任何测试之前完成", prompt)

    def test_no_finish_without_commit_if_test_incomplete(self):
        """「测试无法在窗口内跑完时，MUST 提交已解决的合并」。"""
        prompt = self._make_prompt()
        self.assertIn("测试无法在窗口内跑完时，MUST 提交已解决的合并", prompt,
                       "须含测试不完也必须提交的硬门")


# ── 5.3: 回退上下文断言 ──────────────────────────────────────────────────


class TestFallbackContextInjection(unittest.TestCase):
    """fix-repair-commit-enforcement 5.3: 因 tip 未前进回退时，注入的
    merge 失败上下文含「未提交/分支 tip 未前进」具体事实而非笼统原因。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir) / "repo"
        self.spec = "demo"
        init_repo(self.root)
        spec_dir = self.root / "spec" / "changes" / self.spec
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.logger = CapturingLogger()
        from core.state_machine import StateMachine
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.root, self.logger)
        self.wm = make_wm(self.root)
        self.engine.agent_runner.worktree_manager = self.wm
        self.engine._process_queue = MagicMock()
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.transition(self.spec, "ready")
        self.sm.transition(self.spec, "implementing")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tip_not_advanced_error_contains_specific_fact(self):
        """tip 未前进回退时，error 文本含具体事实（SHA/计数）而非笼统「merge-back failed」。"""
        branch = f"fenix/{self.spec}-123"
        make_conflict_branch(self.root, branch, "BRANCH-IMPL\n")
        (self.root / "shared.py").write_text("MAIN-IMPL\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "[fenix] main shared.py")
        merge_info = self.wm.merge_back_from_branch(branch)
        wt, _ = self.wm.resolve_repair_site(self.spec, branch)
        self.assertIsNotNone(wt)
        # 设置基准 tip（模拟 _dispatch_repair_lane 行为）
        base_tip = git(self.root, "rev-parse", branch).stdout.strip()
        self.sm.update_spec(self.spec, {"_repair_base_tip": base_tip})
        # repair agent 什么都不做，只写成功结果文件
        (wt / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": self.spec}), encoding="utf-8")
        from core.agent_runner import AgentRunResult
        ok_result = AgentRunResult(
            run_id=f"repair-{self.spec}-1", spec_name=self.spec, agent_type="repair",
            success=True, duration_seconds=1.0, branch=branch,
        )
        self.engine.agent_runner.run_repair = MagicMock(return_value=ok_result)
        self.engine._run_repair_worker(self.spec, wt, branch, merge_info)
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "ready")
        err = entry.get("error", "")
        # 必须含具体事实，不是笼统原因
        self.assertIn("分支 tip 未前进", err, "error 须含「分支 tip 未前进」具体事实")
        self.assertIn("可能只暂存未提交", err)
        # 必须含 repair 失败字样（_fallback_after_repair 拼出的 full_error）
        self.assertIn("repair 失败", err, "error 须以「repair 失败」开头（full_error 格式）")
        self.assertNotEqual(err, "merge-back failed",
                            "不得以笼统原因「merge-back failed」重派")


if __name__ == "__main__":
    unittest.main()
