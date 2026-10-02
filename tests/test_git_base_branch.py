"""evo-fix-resume-base-branch-portability — 共享基线分支解析器与调用点单测。

覆盖 SPEC tasks 1.2 / 4.3 / 5.2 / 6.2：
  - 1.2: resolve_base_branch 解析顺序（origin/HEAD → 本地 main → master →
    回退 "main"）、非 git 目录回退、按 project_root 缓存命中（monkeypatch
    子进程计数）；
  - 4.3: 调用点用例——master 主干仓中零提交 + dirty 现场终态零提交门抛
    ``[terminal-no-commit]``、有提交时不抛；legacy 快照返回提交清单；
  - 5.2: ``_ahead_commit_count`` 级语义——master 主干无 remote 仓 1 提交
    分支计数为 1（``_preserve_interrupted_runs`` /
    ``_preserve_implementing_specs`` 保全条目的 ``ahead_commits`` 字段来源，
    修复前该仓 ahead 恒 0、保留续做判定不命中）；
  - 6.2: branch_guard ``_branch_commit_count``——master 主干 1 提交分支返回
    1、真零提交分支返回 0（零变更哨可判零变更）、main 主干结果不变。

基于真实 tmp git 仓 fixture（``git init`` + ``branch -M`` 改名，不依赖
init 缺省分支名），不启动真实 daemon/子进程。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.git_base_branch as gbb
from core.git_base_branch import resolve_base_branch, reset_cache


def git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def make_repo(root: Path, trunk: str = "main"):
    """建 tmp git 仓，主干分支经 branch -M 改名为 trunk（不依赖缺省分支名）。"""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "base.txt").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", trunk)
    return root


def add_commit(root: Path, rel: str, content: str, msg: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)


def make_impl_branch(root: Path, trunk: str, name: str, commits: int = 1):
    """自主干建实现分支并落 commits 个提交，随后切回主干。"""
    git(root, "checkout", "-q", "-b", name)
    for i in range(commits):
        add_commit(root, f"feat-{i}.py", f"IMPL {i}\n", f"[fenix] impl {i}")
    git(root, "checkout", "-q", trunk)


def attach_origin(root: Path, head_target: str) -> Path:
    """bare clone 为 origin 并把 origin/HEAD 指向 head_target（无网络）。"""
    origin = root.parent / (root.name + "-origin.git")
    git(root.parent, "clone", "-q", "--bare", str(root), str(origin))
    git(root, "remote", "add", "origin", str(origin))
    git(root, "fetch", "-q", "origin")
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD",
        f"refs/remotes/origin/{head_target}")
    return origin


class _TmpRepoCase(unittest.TestCase):
    """公共 setUp/tearDown：tmp 目录 + 缓存隔离。"""

    def setUp(self):
        reset_cache()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(reset_cache)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


# ── 1.2: resolve_base_branch ─────────────────────────────────────────────────


class TestResolveBaseBranch(_TmpRepoCase):
    """1.2: 解析顺序、回退与缓存全场景。"""

    def test_master_trunk_no_remote(self):
        """仅 master 主干无 remote（本事故仓库形态）→ master。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        self.assertEqual(resolve_base_branch(root), "master")

    def test_main_trunk(self):
        """main 主干（fenixd 自身形态）→ main，既有口径零漂移。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="main")
        self.assertEqual(resolve_base_branch(root), "main")

    def test_both_trunks_prefers_main(self):
        """双主干并存 → main（固定解析顺序）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        git(root, "branch", "main")
        self.assertEqual(resolve_base_branch(root), "main")

    def test_origin_head_non_main_preferred(self):
        """origin/HEAD 指向非 main 分支 → 返回该分支名。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="trunk")
        attach_origin(root, "trunk")
        self.assertEqual(resolve_base_branch(root), "trunk")

    def test_origin_head_main(self):
        """origin/HEAD 指向 origin/main → main（与 fenixd 现行为一致）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="main")
        attach_origin(root, "main")
        self.assertEqual(resolve_base_branch(root), "main")

    def test_non_git_dir_falls_back_without_raise(self):
        """非 git 目录 → 回退 "main"，不抛异常。"""
        plain = Path(self.tmp) / "plain"
        plain.mkdir(parents=True, exist_ok=True)
        self.assertEqual(resolve_base_branch(plain), "main")

    def test_cache_hit_skips_subprocess(self):
        """按 project_root 缓存：二次调用不再起子进程，reset_cache 后重探。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        real_run = gbb.subprocess.run
        calls = {"n": 0}

        def counting(*a, **k):
            calls["n"] += 1
            return real_run(*a, **k)

        with patch.object(gbb.subprocess, "run", counting):
            self.assertEqual(resolve_base_branch(root), "master")
            first = calls["n"]
            self.assertGreater(first, 0)
            self.assertEqual(resolve_base_branch(root), "master")
            self.assertEqual(calls["n"], first, "缓存命中 MUST 不再起子进程")
            reset_cache()
            self.assertEqual(resolve_base_branch(root), "master")
            self.assertGreater(calls["n"], first, "reset_cache 后 MUST 重新探测")

    def test_timeout_falls_back_not_raise(self):
        """git 子进程超时 → 回退常量，不抛异常（D3 超时口径）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="master")

        def hanging(*a, **k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=0.01)

        with patch.object(gbb.subprocess, "run", hanging):
            self.assertEqual(resolve_base_branch(root), "main")


# ── 4.3: 终态零提交门调用点 ──────────────────────────────────────────────────


class TestTerminalNoCommitGateMaster(_TmpRepoCase):
    """4.3: master 主干仓的 _check_terminal_no_commit_gate 行为。"""

    def _runner(self, root: Path):
        # 绕过 __init__ 的测试构造（AgentRunner 类注释明示的既有模式）：
        # 门方法仅触达 project_root 与转录归因（转录缺失 fail-open 降级）。
        from core.agent_runner.runner import AgentRunner
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = root
        return runner

    def test_zero_commit_dirty_raises_gate_error(self):
        """master 主干零提交 + dirty 现场 → 抛 [terminal-no-commit] 门错误。"""
        from core.agent_runner.runner import AgentArtifactGateError
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        make_impl_branch(root, "master", "fenix/fix-x-123", commits=0)
        dirty = root / "uncommitted.py"
        dirty.write_text("WIP\n", encoding="utf-8")
        runner = self._runner(root)
        with self.assertRaises(AgentArtifactGateError) as ctx:
            runner._check_terminal_no_commit_gate(
                "fix-x", "implementer", root, "fenix/fix-x-123",
                ["uncommitted.py"], "impl-fix-x-1")
        self.assertIn("[terminal-no-commit]", str(ctx.exception))

    def test_branch_with_commit_does_not_raise(self):
        """master 主干有未合并提交 → 门放行（不抛）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        make_impl_branch(root, "master", "fenix/fix-x-123", commits=1)
        runner = self._runner(root)
        runner._check_terminal_no_commit_gate(
            "fix-x", "implementer", root, "fenix/fix-x-123",
            ["uncommitted.py"], "impl-fix-x-1")


# ── 4.3: legacy 提交快照调用点 ───────────────────────────────────────────────


class TestLegacySnapshotMaster(_TmpRepoCase):
    """4.3: master 主干仓的 _legacy_branch_snapshot 返回提交清单。"""

    def test_snapshot_lists_commits_on_master_trunk(self):
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        make_impl_branch(root, "master", "fenix/fix-y-456", commits=1)
        from core.agent_runner.prompt_builder import PromptBuilder
        pb = PromptBuilder(SimpleNamespace(project_root=root))
        snap = pb._legacy_branch_snapshot("fenix/fix-y-456")
        self.assertIn("[fenix] impl 0", snap, f"快照 MUST 含提交清单: {snap}")
        self.assertFalse(snap.startswith("（快照采集失败"), snap)

    def test_main_trunk_snapshot_unchanged(self):
        """main 主干快照结果不变（既有口径零漂移）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="main")
        make_impl_branch(root, "main", "fenix/fix-y-456", commits=1)
        from core.agent_runner.prompt_builder import PromptBuilder
        pb = PromptBuilder(SimpleNamespace(project_root=root))
        snap = pb._legacy_branch_snapshot("fenix/fix-y-456")
        self.assertIn("[fenix] impl 0", snap)


# ── 5.2: _ahead_commit_count 级语义（fenixd 侧公开路径）─────────────────────


class TestAheadCommitCountFenixd(_TmpRepoCase):
    """5.2: master 主干无 remote 仓的 ahead 计数（经 fenixd 公开路径）。

    该值为 ``_preserve_interrupted_runs`` / ``_preserve_implementing_specs``
    保全条目 ``ahead_commits`` 字段的来源：修复前本形态下
    ``git rev-list --count main..<branch>`` 恒非零退出、ahead 恒按 0 口径，
    中断恢复的保留续做判定不命中。
    """

    def test_one_commit_branch_counts_one(self):
        import fenixd
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        make_impl_branch(root, "master", "fenix/fix-z-789", commits=1)
        with patch.object(fenixd, "PROJECT_ROOT", root):
            self.assertEqual(fenixd._preserve_base_branch(), "master")
            self.assertEqual(fenixd._ahead_commit_count("fenix/fix-z-789"), 1)

    def test_zero_commit_branch_counts_zero(self):
        import fenixd
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        make_impl_branch(root, "master", "fenix/fix-z-789", commits=0)
        with patch.object(fenixd, "PROJECT_ROOT", root):
            self.assertEqual(fenixd._ahead_commit_count("fenix/fix-z-789"), 0)


# ── 6.2: branch_guard._branch_commit_count 调用点 ────────────────────────────


class TestBranchGuardCommitCount(_TmpRepoCase):
    """6.2: 零变更哨/验证分支守卫共用单一来源的跨基线行为。"""

    def _count(self, root: Path, branch: str):
        from core.pm_engine.verification.branch_guard import _branch_commit_count
        pipeline = SimpleNamespace(
            _context=SimpleNamespace(project_root=root))
        return _branch_commit_count(pipeline, SimpleNamespace(branch=branch))

    def test_master_trunk_one_commit_returns_one(self):
        """master 主干 1 提交分支 → 1（修复前恒 None、哨漏报空转）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        make_impl_branch(root, "master", "fenix/fix-z-789", commits=1)
        self.assertEqual(self._count(root, "fenix/fix-z-789"), 1)

    def test_master_trunk_zero_commit_returns_zero(self):
        """真零提交分支 → 0（零变更哨可判零变更，非 None 漏报）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        make_impl_branch(root, "master", "fenix/fix-z-789", commits=0)
        self.assertEqual(self._count(root, "fenix/fix-z-789"), 0)

    def test_main_trunk_unchanged(self):
        """main 主干结果不变（既有口径零漂移）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="main")
        make_impl_branch(root, "main", "fenix/fix-z-789", commits=1)
        self.assertEqual(self._count(root, "fenix/fix-z-789"), 1)

    def test_missing_branch_returns_none(self):
        """分支不存在 → rev-list 非零退出 → None（fail-open 语义保留）。"""
        root = make_repo(Path(self.tmp) / "repo", trunk="master")
        self.assertIsNone(self._count(root, "fenix/nope-1"))


if __name__ == "__main__":
    unittest.main()
