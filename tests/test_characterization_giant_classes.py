"""characterization tests: 锁定三个巨型类的关键方法当前行为。

覆盖 design 文档中标注的盲区：
- WorktreeManager G5: _run_dist_build / _rebuild_dist_after_merge
- WorktreeManager G6: _purge_ignored_brought_in / _resolve_ignored_modify_delete_conflicts
- WorktreeManager G4: _detect_wip_overlap
- Dispatcher B 组: _on_instant_fail_recovery / _on_transient_recovery
- Dispatcher V 组: _build_dispute_judge_input / _read_dispute_verdicts

所有测试锁定当前行为（baseline），用于重构后行为等价验证。
"""

import json
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.worktree_manager import WorktreeManager, DASHBOARD_STATIC_ROOT


class CapturingLogger:
    """记录 warning/info/error 日志，供断言使用。"""

    def __init__(self):
        self.warnings = []
        self.infos = []
        self.errors = []

    def warning(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.warnings.append(msg)

    def info(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.infos.append(msg)

    def error(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.errors.append(msg)

    def debug(self, *a, **k):
        pass


def git(root: Path, *args, check=True):
    """在 main tree 仓库执行 git 命令。"""
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path) -> str:
    """初始化 git 仓库并做基线提交。返回 BASE 提交 sha。"""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    return git(root, "rev-parse", "HEAD").stdout.strip()


def make_branch(root: Path, branch: str, added_path: str, added_content: str,
                shared_content: str = "BASE\n"):
    """从 BASE 派生分支。"""
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


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, CapturingLogger())


# ══════════════════════════════════════════════════════════════════════════════
# WorktreeManager G4: _detect_wip_overlap
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectWipOverlap:
    """G4: _detect_wip_overlap 行为锁定。"""

    def test_no_dirty_files_returns_empty(self, tmp_path):
        """无脏 tracked 文件 → 返回空列表。"""
        root = tmp_path / "repo"
        base_sha = init_repo(root)
        make_branch(root, "fenix/impl", "new.txt", "branch-content\n")
        wm = make_wm(root)
        result = wm._detect_wip_overlap("fenix/impl")
        assert result == []

    def test_dirty_file_not_on_branch_returns_empty(self, tmp_path):
        """主树脏 tracked 文件不在分支改动集合 → 返回空列表。"""
        root = tmp_path / "repo"
        init_repo(root)
        make_branch(root, "fenix/impl", "on-branch.txt", "branch\n")
        # 主树修改不与分支重叠的文件
        (root / "independent.txt").write_text("MAIN\n", encoding="utf-8")
        git(root, "add", "independent.txt")
        git(root, "commit", "-q", "-m", "[fenix] main change", "--allow-empty")
        # 使 shared.py 脏（tracked 修改，不提交）
        (root / "shared.py").write_text("DIRTY\n", encoding="utf-8")
        wm = make_wm(root)
        # 分支只改了 on-branch.txt，dirty 是 shared.py → 无重叠
        result = wm._detect_wip_overlap("fenix/impl")
        assert result == []

    def test_dirty_overlap_returns_sorted_list(self, tmp_path):
        """主树脏 tracked 文件与分支改动重合 → 返回排序重叠清单。"""
        root = tmp_path / "repo"
        base_sha = init_repo(root)
        # 分支新增 + 修改 shared.py
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "overlap-a.txt").write_text("A\n", encoding="utf-8")
        (root / "overlap-b.txt").write_text("B\n", encoding="utf-8")
        (root / "shared.py").write_text("BRANCH\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch")
        git(root, "checkout", "-q", base_sha)
        # 主树也创建同路径 tracked 文件，再修改使之脏（overlap-a/b + shared.py 均 tracked 且脏）
        for name in ("overlap-a.txt", "overlap-b.txt", "shared.py"):
            content = {"overlap-a.txt": "MAIN-A\n",
                       "overlap-b.txt": "MAIN-B\n",
                       "shared.py": "MAIN-CONFLICT\n"}[name]
            (root / name).write_text(content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] main seeded")
        # 使全部三个文件脏（tracked 修改）
        for name, dirty in (("overlap-a.txt", "MAIN-A2\n"),
                            ("overlap-b.txt", "MAIN-B2\n"),
                            ("shared.py", "MAIN-CONFLICT2\n")):
            (root / name).write_text(dirty, encoding="utf-8")
        wm = make_wm(root)
        result = wm._detect_wip_overlap("fenix/impl")
        assert sorted(result) == ["overlap-a.txt", "overlap-b.txt", "shared.py"]

    def test_no_branch_overlap_returns_empty(self, tmp_path):
        """分支与主树无共同改动 → 返回空列表。"""
        root = tmp_path / "repo"
        base_sha = init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "branch-only.txt").write_text("B\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch only")
        git(root, "checkout", "-q", base_sha)
        # 主树修改（不提交，tracked dirty）
        (root / "main-only.txt").write_text("M\n", encoding="utf-8")
        git(root, "add", "main-only.txt")
        git(root, "commit", "-q", "-m", "[fenix] main only")
        # 再改 main-only 使其脏
        (root / "main-only.txt").write_text("DIRTY\n", encoding="utf-8")
        wm = make_wm(root)
        result = wm._detect_wip_overlap("fenix/impl")
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# WorktreeManager G5: _run_dist_build / _rebuild_dist_after_merge
# ══════════════════════════════════════════════════════════════════════════════


class TestRunDistBuild:
    """G5: _run_dist_build 行为锁定。"""

    def test_no_contract_no_package_json_returns_false(self, tmp_path):
        """无契约 + 无 package.json → False + warning 日志。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        result = wm._run_dist_build()
        assert result is False
        assert any("no package.json" in w for w in wm.logger.warnings)

    def test_no_contract_npm_success_returns_true(self, tmp_path):
        """无契约 + 有 package.json + npm run build 成功 → True。"""
        root = tmp_path / "repo"
        init_repo(root)
        # 创建 static/package.json
        static_dir = root / "core" / "dashboard" / "static"
        static_dir.mkdir(parents=True)
        (static_dir / "package.json").write_text('{"scripts":{"build":"echo ok"}}', encoding="utf-8")
        wm = make_wm(root)
        # patch npm 为成功。回退构建已改 Popen + 进程组清扫（item
        # 23fb5d47f396），替身须随行：仍 patch 旧 subprocess.run 会静默
        # 漏拦、替身失真致真实 npm 上屏（call_args 为 None）。
        mock_proc = MagicMock(returncode=0)
        mock_proc.communicate.return_value = ("ok", "")
        with patch("core.worktree_manager.subprocess.Popen", return_value=mock_proc) as m:
            result = wm._run_dist_build()
            assert result is True
            # 验证调用 npm run build
            cmd = m.call_args[0][0]
            assert "npm" in cmd and "build" in cmd

    def test_no_contract_npm_failure_returns_false(self, tmp_path):
        """无契约 + 有 package.json + npm run build 失败 → False。"""
        root = tmp_path / "repo"
        init_repo(root)
        static_dir = root / "core" / "dashboard" / "static"
        static_dir.mkdir(parents=True)
        (static_dir / "package.json").write_text('{"scripts":{"build":"exit 1"}}', encoding="utf-8")
        wm = make_wm(root)
        # 替身随 Popen（item 23fb5d47f396）同上款：失败路径 returncode=1
        mock_proc = MagicMock(returncode=1)
        mock_proc.communicate.return_value = ("", "build error")
        with patch("core.worktree_manager.subprocess.Popen", return_value=mock_proc):
            result = wm._run_dist_build()
            assert result is False

    def test_contract_no_prepare_returns_true(self, tmp_path):
        """有契约但无 prepare 段 → True（不执行构建）。"""
        root = tmp_path / "repo"
        init_repo(root)
        # 创建 .fenix/verify.yaml 无 prepare
        (root / ".fenix").mkdir(parents=True)
        (root / ".fenix" / "verify.yaml").write_text("serve:\n  kind: static\n  root: .\n", encoding="utf-8")
        wm = make_wm(root)
        result = wm._run_dist_build()
        assert result is True

    def test_contract_with_prepare_success_returns_true(self, tmp_path):
        """有契约 + prepare 成功 → True。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / ".fenix").mkdir(parents=True)
        (root / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo build-ok\n", encoding="utf-8"
        )
        wm = make_wm(root)
        with patch("core.verify_contract.run_prepare_steps", return_value=None), \
             patch("core.verify_contract.ensure_main_tree_deps"), \
             patch("core.verify_contract.read_config_deps_mode", return_value="prefer-offline"), \
             patch("core.verify_contract.resolve_deps_mode", return_value="prefer-offline"):
            result = wm._run_dist_build()
            assert result is True

    def test_contract_with_prepare_failure_returns_false(self, tmp_path):
        """有契约 + prepare 失败 → False + warning。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / ".fenix").mkdir(parents=True)
        (root / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: exit 1\n", encoding="utf-8"
        )
        wm = make_wm(root)
        with patch("core.verify_contract.run_prepare_steps", return_value="prepare failed"), \
             patch("core.verify_contract.ensure_main_tree_deps"), \
             patch("core.verify_contract.read_config_deps_mode", return_value="prefer-offline"), \
             patch("core.verify_contract.resolve_deps_mode", return_value="prefer-offline"):
            result = wm._run_dist_build()
            assert result is False
            assert any("prepare 失败" in w for w in wm.logger.warnings)


class TestRebuildDistAfterMerge:
    """G5: _rebuild_dist_after_merge 行为锁定。"""

    def test_no_static_src_touched_returns_early(self, tmp_path):
        """merge 后未触碰 static 根下源文件 → 不构建、不报错。"""
        root = tmp_path / "repo"
        base_sha = init_repo(root)
        # 分支只改 shared.py（非 static 路径）
        make_branch(root, "fenix/impl", "shared.py", "BRANCH\n")
        git(root, "merge", "--no-ff", "-q", "-m", "merge", "fenix/impl")
        wm = make_wm(root)
        with patch.object(wm, "_run_dist_build") as mock_build:
            wm._rebuild_dist_after_merge()
            mock_build.assert_not_called()

    def test_build_success_amend(self, tmp_path):
        """merge 触碰 static 源 → 构建成功 → git commit --amend。"""
        root = tmp_path / "repo"
        base_sha = init_repo(root)
        # 分支新增 static 下源文件
        make_branch(root, "fenix/impl", "core/dashboard/static/src/index.js", "console.log('hi')")
        git(root, "merge", "--no-ff", "-q", "-m", "merge", "fenix/impl")
        wm = make_wm(root)
        # mock _run_dist_build 返回成功
        with patch.object(wm, "_run_dist_build", return_value=True), \
             patch("core.worktree_manager.subprocess.run") as mock_sub:
            # mock git diff / add / status / commit --amend
            def side_effect(args, **kw):
                if "diff" in args:
                    # git diff --name-only HEAD^1 HEAD 返回 static 源文件
                    return MagicMock(returncode=0, stdout="core/dashboard/static/src/index.js\n")
                if "status" in args:
                    # status --porcelain 返回非空（有变更）
                    return MagicMock(returncode=0, stdout="A  core/dashboard/static/src/index.js\n")
                if "commit" in args and "amend" in args:
                    # commit --amend 成功
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")
            mock_sub.side_effect = side_effect
            wm._rebuild_dist_after_merge()
            # 应调用过 git add + git commit --amend
            add_call = any("add" in c[0][0] for c in mock_sub.call_args_list)
            commit_call = any("--amend" in c[0][0]
                              for c in mock_sub.call_args_list)
            assert add_call, "应调用 git add"
            assert commit_call, "应调用 git commit --amend"

    def test_build_failure_keeps_existing_dist(self, tmp_path):
        """merge 触碰 static 源 → 构建失败 → 不 amend，保留现有产物。"""
        root = tmp_path / "repo"
        base_sha = init_repo(root)
        make_branch(root, "fenix/impl", "core/dashboard/static/src/app.js", "App()")
        git(root, "merge", "--no-ff", "-q", "-m", "merge", "fenix/impl")
        wm = make_wm(root)
        with patch.object(wm, "_run_dist_build", return_value=False), \
             patch("core.worktree_manager.subprocess.run") as mock_sub:
            def side_effect(args, **kw):
                if "diff" in args:
                    return MagicMock(returncode=0, stdout="core/dashboard/static/src/app.js\n")
                return MagicMock(returncode=0, stdout="", stderr="")
            mock_sub.side_effect = side_effect
            wm._rebuild_dist_after_merge()
            # 不应调用 git add / commit
            add_calls = [c for c in mock_sub.call_args_list if "add" in c.args[0]]
            assert not add_calls, "构建失败不应调用 git add"
            assert any("dist rebuild failed" in e for e in wm.logger.errors)


# ══════════════════════════════════════════════════════════════════════════════
# WorktreeManager G6: _purge_ignored_brought_in / _resolve_ignored_modify_delete_conflicts
# ══════════════════════════════════════════════════════════════════════════════


class TestPurgeIgnoredBroughtIn:
    """G6: _purge_ignored_brought_in 行为锁定。"""

    def test_no_added_files_returns_early(self, tmp_path):
        """merge 未新增文件 → 零操作。"""
        root = tmp_path / "repo"
        old_head = init_repo(root)
        make_branch(root, "fenix/impl", "shared.py", "BRANCH\n")
        git(root, "merge", "--no-ff", "-q", "-m", "merge", "fenix/impl")
        wm = make_wm(root)
        with patch("core.worktree_manager.subprocess.run") as mock_sub:
            # git diff --diff-filter=A 返回空
            mock_sub.return_value = MagicMock(returncode=0, stdout="")
            wm._purge_ignored_brought_in(old_head)
            # 只应调用 diff，不应调用 rm
            rm_calls = [c for c in mock_sub.call_args_list if "rm" in str(c)]
            assert not rm_calls, "无新增时不应调用 git rm"

    def test_ignored_added_file_is_purged(self, tmp_path):
        """merge 新增被 ignore 的文件 → git rm --cached 移出索引。"""
        root = tmp_path / "repo"
        old_head = init_repo(root)
        # 设置 .gitignore 忽略 *.draft
        (root / ".gitignore").write_text("*.draft\n", encoding="utf-8")
        git(root, "add", ".gitignore")
        git(root, "commit", "-q", "-m", "[fenix] gitignore")
        git(root, "checkout", "-q", old_head)  # 回到 base
        old_head = git(root, "rev-parse", "HEAD").stdout.strip()
        # 分支新增 draft 文件
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "run.draft").write_text("DRAFT\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add draft")
        git(root, "checkout", "-q", old_head)
        git(root, "merge", "--no-ff", "-q", "-m", "merge", "fenix/impl")
        wm = make_wm(root)
        # 模拟 git diff 返回新增文件
        with patch("core.worktree_manager.subprocess.run") as mock_sub:
            def side_effect(args, **kw):
                # 对齐批量口径实现（item 2eecaa4ef78d）：tracked 集与 ignore
                # 判定均收敛为单条批量调用，且「出现在 -z 输出即命中」。
                if "diff" in args and "--diff-filter=A" in args:
                    return MagicMock(returncode=0, stdout="run.draft\n")
                if "ls-files" in args:
                    return MagicMock(returncode=0, stdout="run.draft\0")
                if "check-ignore" in args:
                    return MagicMock(returncode=0, stdout="run.draft\0")  # 被 ignore
                if "rm" in args:
                    return MagicMock(returncode=0, stdout="", stderr="")
                if "commit" in args:
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")
            mock_sub.side_effect = side_effect
            wm._purge_ignored_brought_in(old_head)
            # 应调用 rm + commit
            rm_calls = [c for c in mock_sub.call_args_list if "rm" in str(c)]
            commit_calls = [c for c in mock_sub.call_args_list if "commit" in str(c)]
            assert rm_calls, "应调用 git rm --cached"
            assert commit_calls, "应调用 git commit"
            assert any("Purged ignored drafts" in i for i in wm.logger.infos)

    def test_non_ignored_added_file_skipped(self, tmp_path):
        """merge 新增的文件未被 ignore → 跳过（不 rm）。"""
        root = tmp_path / "repo"
        old_head = init_repo(root)
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "normal.txt").write_text("NORMAL\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add normal")
        git(root, "checkout", "-q", old_head)
        git(root, "merge", "--no-ff", "-q", "-m", "merge", "fenix/impl")
        wm = make_wm(root)
        with patch("core.worktree_manager.subprocess.run") as mock_sub:
            def side_effect(args, **kw):
                if "diff" in args and "--diff-filter=A" in args:
                    return MagicMock(returncode=0, stdout="normal.txt\n")
                if "ls-files" in args and "--error-unmatch" in args:
                    return MagicMock(returncode=0, stdout="normal.txt\n")
                if "check-ignore" in args:
                    return MagicMock(returncode=1, stdout="")  # 未被 ignore
                return MagicMock(returncode=0, stdout="", stderr="")
            mock_sub.side_effect = side_effect
            wm._purge_ignored_brought_in(old_head)
            rm_calls = [c for c in mock_sub.call_args_list if "rm" in c.args[0]]
            assert not rm_calls, "未被 ignore 的文件不应调用 git rm"


class TestResolveIgnoredModifyDeleteConflicts:
    """G6: _resolve_ignored_modify_delete_conflicts 行为锁定。"""

    def test_no_conflicts_returns_false(self, tmp_path):
        """status 无冲突 → False。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        with patch("core.worktree_manager.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0, stdout="M  modified.txt\n")
            assert wm._resolve_ignored_modify_delete_conflicts() is False

    def test_du_conflict_self_heal_success(self, tmp_path):
        """DU 冲突（主树删除、分支修改）+ 被 ignore → rm --cached + commit 成功 → True。"""
        root = tmp_path / "repo"
        init_repo(root)
        # 创建 .gitignore 忽略 runtime.draft
        (root / ".gitignore").write_text("runtime.draft\n", encoding="utf-8")
        git(root, "add", ".gitignore")
        git(root, "commit", "-q", "-m", "[fenix] gitignore")
        wm = make_wm(root)
        with patch("core.worktree_manager.subprocess.run") as mock_sub:
            def side_effect(args, **kw):
                if "status" in args:
                    # DU 冲突（主树删除、分支修改）
                    return MagicMock(returncode=0, stdout="DU runtime.draft\n")
                if "rm" in args:
                    return MagicMock(returncode=0, stdout="", stderr="")
                if "check-ignore" in args:
                    return MagicMock(returncode=0, stdout="")  # 被 ignore
                if "commit" in args:
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")
            mock_sub.side_effect = side_effect
            assert wm._resolve_ignored_modify_delete_conflicts() is True

    def test_non_du_conflict_returns_false(self, tmp_path):
        """非 DU 冲突（如 UU）→ False，不自愈。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        with patch("core.worktree_manager.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0, stdout="UU conflict.txt\n")
            assert wm._resolve_ignored_modify_delete_conflicts() is False

    def test_du_conflict_not_ignored_abort(self, tmp_path):
        """DU 冲突但路径未被 ignore → abort + False。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        with patch("core.worktree_manager.subprocess.run") as mock_sub:
            def side_effect(args, **kw):
                if "status" in args:
                    return MagicMock(returncode=0, stdout="DU deliverable.md\n")
                if "rm" in args:
                    return MagicMock(returncode=0, stdout="", stderr="")
                if "check-ignore" in args:
                    return MagicMock(returncode=1, stdout="")  # 未被 ignore
                if "merge" in args and "--abort" in args:
                    return MagicMock(returncode=0, stdout="", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")
            mock_sub.side_effect = side_effect
            assert wm._resolve_ignored_modify_delete_conflicts() is False
            # 验证调用了 merge --abort
            abort_calls = [c for c in mock_sub.call_args_list if "--abort" in c.args[0]]
            assert abort_calls, "未被 ignore 的 DU 冲突应调用 merge --abort"


# ══════════════════════════════════════════════════════════════════════════════
# Dispatcher B 组: _on_instant_fail_recovery / _on_transient_recovery
# ══════════════════════════════════════════════════════════════════════════════


def make_dispatcher(pm=None):
    """构造 Dispatcher 实例（pm 可选）。"""
    from core.pm_engine.dispatch import Dispatcher
    if pm is None:
        pm = MagicMock()
        pm.logger = MagicMock()
    return Dispatcher(pm)


class TestInstantFailRecovery:
    """B 组: _on_instant_fail_recovery 行为锁定。"""

    def test_removes_from_timers_and_calls_pm(self):
        """秒挂冷却到期：移除 timer、调用 pm._on_spec_ready + _process_queue。"""
        d = make_dispatcher()
        d._instant_fail_timers.add("spec-x")
        d._on_instant_fail_recovery("spec-x")
        assert "spec-x" not in d._instant_fail_timers
        d._pm._on_spec_ready.assert_called_once_with("spec-x")
        d._pm._process_queue.assert_called_once()

    def test_idempotent_when_not_in_timers(self):
        """幂等：不在 timer 集合中时仍正常执行。"""
        d = make_dispatcher()
        d._on_instant_fail_recovery("spec-y")
        d._pm._on_spec_ready.assert_called_once_with("spec-y")
        d._pm._process_queue.assert_called_once()


class TestTransientRecovery:
    """B 组: _on_transient_recovery 行为锁定。"""

    def test_removes_from_timers_and_calls_pm(self):
        """瞬断冷却到期：移除 timer、调用 pm._on_spec_ready + _process_queue。"""
        d = make_dispatcher()
        d._transient_timers.add("spec-z")
        d._on_transient_recovery("spec-z")
        assert "spec-z" not in d._transient_timers
        d._pm._on_spec_ready.assert_called_once_with("spec-z")
        d._pm._process_queue.assert_called_once()

    def test_idempotent_when_not_in_timers(self):
        """幂等：不在 timer 集合中时仍正常执行。"""
        d = make_dispatcher()
        d._on_transient_recovery("spec-w")
        d._pm._on_spec_ready.assert_called_once_with("spec-w")
        d._pm._process_queue.assert_called_once()

    def test_schedule_transient_recovery_idempotent(self):
        """排程幂等：同一 spec 不重复排程。"""
        d = make_dispatcher()
        d._pm._get_config = MagicMock(return_value=600)
        d._schedule_transient_recovery("spec-a")
        d._schedule_transient_recovery("spec-a")
        # _transient_timers 应只有一个条目
        assert len(d._transient_timers) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Dispatcher V 组: _build_dispute_judge_input / _read_dispute_verdicts
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildDisputeJudgeInput:
    """V 组: _build_dispute_judge_input 行为锁定。"""

    def test_missing_paths_default_kind(self):
        """缺失路径默认 kind=new，结构正确。"""
        d = make_dispatcher()
        d._pm.project_root = Path("/tmp/fake")
        with patch("core.deliverables.match_basename_in_tree", return_value=["candidates/a.py"]):
            result = d._build_dispute_judge_input("my-spec", {}, ["src/main.py"])
        assert result["spec"] == "my-spec"
        assert len(result["missing"]) == 1
        entry = result["missing"][0]
        assert entry["path"] == "src/main.py"
        assert entry["kind"] == "new"
        assert entry["candidates"] == ["candidates/a.py"]

    def test_kind_by_path_override(self):
        """kind_by_path 覆盖默认 kind。"""
        d = make_dispatcher()
        d._pm.project_root = Path("/tmp/fake")
        kind_map = {"docs/readme.md": "modify"}
        with patch("core.deliverables.match_basename_in_tree", return_value=[]):
            result = d._build_dispute_judge_input("s", {}, ["docs/readme.md"], kind_by_path=kind_map)
        assert result["missing"][0]["kind"] == "modify"

    def test_findings_from_impl_result(self):
        """findings 从 impl_result 透传。"""
        d = make_dispatcher()
        d._pm.project_root = Path("/tmp/fake")
        impl_result = {"findings": [{"type": "bug", "file": "x.py"}]}
        with patch("core.deliverables.match_basename_in_tree", return_value=[]):
            result = d._build_dispute_judge_input("s", impl_result, [])
        assert result["findings"] == [{"type": "bug", "file": "x.py"}]


class TestReadDisputeVerdicts:
    """V 组: _read_dispute_verdicts 行为锁定。"""

    def _make_pm_with_result(self, tmp_path, spec, data=None):
        """在 tmp_path 写入 dispute_judge_result.json。"""
        pm = MagicMock()
        pm.project_root = tmp_path
        pm.logger = MagicMock()
        result_dir = tmp_path / ".fenix" / "verify-progress" / spec
        result_dir.mkdir(parents=True, exist_ok=True)
        result_file = result_dir / "dispute_judge_result.json"
        if data is not None:
            result_file.write_text(json.dumps(data), encoding="utf-8")
        return pm, result_file

    def test_judge_run_failed_returns_none(self, tmp_path):
        """judge_result 为 None 或 success=False → None。"""
        pm = MagicMock()
        pm.project_root = tmp_path
        pm.logger = MagicMock()
        from core.pm_engine.dispatch import Dispatcher
        d = Dispatcher(pm)
        judge_result_none = None
        assert d._read_dispute_verdicts("s1", "run-1", judge_result_none) is None
        judge_result_fail = MagicMock(success=False, error="crash")
        assert d._read_dispute_verdicts("s1", "run-1", judge_result_fail) is None

    def test_invalid_json_returns_none(self, tmp_path):
        """结果文件 JSON 不合法 → None。"""
        pm, result_file = self._make_pm_with_result(tmp_path, "s2")
        result_file.write_text("{invalid json", encoding="utf-8")
        from core.pm_engine.dispatch import Dispatcher
        d = Dispatcher(pm)
        judge_result = MagicMock(success=True)
        assert d._read_dispute_verdicts("s2", "run-2", judge_result) is None

    def test_status_not_success_returns_none(self, tmp_path):
        """结果 status 非 success → None。"""
        pm, _ = self._make_pm_with_result(tmp_path, "s3", {"status": "partial", "verdicts": []})
        from core.pm_engine.dispatch import Dispatcher
        d = Dispatcher(pm)
        judge_result = MagicMock(success=True)
        assert d._read_dispute_verdicts("s3", "run-3", judge_result) is None

    def test_valid_verdicts_returns_data(self, tmp_path):
        """合法结果（status=success + verdicts 非空）→ 返回 data。"""
        verdicts = [{"path": "x.py", "verdict": "keep"}]
        # 01d1335a9902 契约：结果文件须带 run_id（写侧 runner 收工补写），
        # 读侧按 judge_run_id 严格匹配——夹具补齐 stamp 才走合法路径。
        pm, _ = self._make_pm_with_result(tmp_path, "s4", {
            "run_id": "run-4", "status": "success", "verdicts": verdicts})
        from core.pm_engine.dispatch import Dispatcher
        d = Dispatcher(pm)
        judge_result = MagicMock(success=True)
        result = d._read_dispute_verdicts("s4", "run-4", judge_result)
        assert result is not None
        assert result["status"] == "success"
        assert result["verdicts"] == verdicts

    def test_missing_verdicts_returns_none(self, tmp_path):
        """verdicts 缺失或非列表 → None。"""
        pm, _ = self._make_pm_with_result(tmp_path, "s5", {"status": "success"})
        from core.pm_engine.dispatch import Dispatcher
        d = Dispatcher(pm)
        judge_result = MagicMock(success=True)
        assert d._read_dispute_verdicts("s5", "run-5", judge_result) is None
