"""fix-merge-untracked-guard 测试。

覆盖 merge-back 前 untracked 冲突防护的 6 个 spec scenario，全部基于真实 git 仓库 fixture：
  scenario 1: 主树 untracked 与分支新增路径重合 → 移开备份、merge 成功
  scenario 2: 主树 untracked 与分支路径无交集 → 不移动、不创建备份目录
  scenario 3: merge 失败 → abort 后备份移回原路径、目录清空
  scenario 4: 分支新增路径集合为空（纯修改分支）→ 零开销跳过、不创建备份
  scenario 5: 备份副本与合入版本字节一致 → 备份目录被删
  scenario 6: 备份副本与合入版本字节不一致 → 备份保留 + warning 日志含路径清单

复演 2026-08-29 v2-vendor-amis-sdk 死锁根因：主树 untracked 产物（core/dashboard/static/v2/sdk.js）
与 implementer 分支同路径冲突。
"""

import subprocess
from pathlib import Path

import pytest

from core.worktree_manager import WorktreeManager

from test_agent_runner import FakeLogger


class CapturingLogger(FakeLogger):
    """记录 warning 文本，供一致性保护告警断言使用。"""

    def __init__(self):
        self.warnings = []

    def warning(self, *a, **k):
        # worktree_manager 调用签名：warning(component, message, context=None)
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.warnings.append(msg)


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
    """初始化 git 仓库并做基线提交（shared.py 恒为 'BASE\n'）。返回 BASE 提交 sha。"""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    return git(root, "rev-parse", "HEAD").stdout.strip()


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, CapturingLogger())


def make_branch(root: Path, branch: str, added_path: str, added_content: str,
                shared_content: str = "BASE\n"):
    """从 BASE 派生分支：写 added_path +（可选）改 shared.py，提交；checkout 回 BASE。

    返回 BASE sha（main tree 的 HEAD 起点）。
    """
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


class TestMergeUntrackedGuard:
    # ───────────────────────── scenario 1 / 5: 重合路径移开 + 一致性 ─────────────────────────

    def test_untracked_on_branch_added_path_is_moved_and_merged(self, tmp_path):
        """scenario 1: 主树 untracked 与分支新增路径重合时被移开，merge 成功。"""
        root = tmp_path / "repo"
        init_repo(root)

        added_path = "core/dashboard/static/v2/sdk.js"
        # 分支新增同路径文件（内容 = 主树 untracked 副本，一致）
        make_branch(root, "fenix/impl", added_path, "SDK-CONTENT\n")

        # 主树 untracked 产物（与 v2-vendor-amis-sdk 同构），在 checkout 回 BASE 后写入
        (root / added_path).parent.mkdir(parents=True, exist_ok=True)
        (root / added_path).write_text("SDK-CONTENT\n", encoding="utf-8")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, f"merge 应成功，实际失败: {err}"

        # 主树工作区为分支版本（文件回到原路径、内容为分支内容）
        assert (root / added_path).read_text(encoding="utf-8") == "SDK-CONTENT\n"
        # 备份目录被清理（一致副本 → 删）
        backups = list((root / ".fenix" / "merge-backup").glob("*")) \
            if (root / ".fenix" / "merge-backup").exists() else []
        assert not backups, f"一致副本不应残留备份，实际: {backups}"

    # ───────────────────────── scenario 2: 无交集不移动 ─────────────────────────

    def test_no_intersection_leaves_untracked_in_place(self, tmp_path):
        """scenario 2: 主树 untracked 与分支路径无交集时不被移动，不创建备份目录。"""
        root = tmp_path / "repo"
        init_repo(root)

        make_branch(root, "fenix/impl",
                     "core/dashboard/static/v2/sdk.js", "SDK\n")

        # 主树 untracked 文件，路径不在分支新增集合内
        (root / "notes").mkdir(parents=True, exist_ok=True)
        (root / "notes" / "scratch.txt").write_text("scratch\n", encoding="utf-8")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, f"merge 应成功，实际失败: {err}"

        # 非冲突 untracked 留在原地
        assert (root / "notes" / "scratch.txt").exists()
        assert (root / "notes" / "scratch.txt").read_text(encoding="utf-8") == "scratch\n"
        # 未创建备份目录
        assert not (root / ".fenix" / "merge-backup").exists()

    # ───────────────────────── scenario 3: merge 失败恢复 ─────────────────────────

    def test_merge_failure_restores_backup(self, tmp_path):
        """scenario 3: merge 因冲突失败，abort 后备份文件移回原路径、目录清空。"""
        root = tmp_path / "repo"
        init_repo(root)

        added_path = "core/dashboard/static/v2/sdk.js"
        # 分支新增同路径文件 + 修改 shared.py 与 main 冲突
        make_branch(root, "fenix/impl", added_path, "SDK-BRANCH\n",
                    shared_content="BRANCH-CONFLICT\n")

        # 主树 HEAD 也修改 shared.py（制造真实冲突）
        (root / "shared.py").write_text("MAIN-CONFLICT\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] main conflict change")
        # 主树 untracked 产物（将被备份移开）
        (root / added_path).parent.mkdir(parents=True, exist_ok=True)
        (root / added_path).write_text("SDK-MAINTREE\n", encoding="utf-8")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert not success, "merge 应因冲突失败"

        # 备份文件移回原路径
        assert (root / added_path).exists()
        assert (root / added_path).read_text(encoding="utf-8") == "SDK-MAINTREE\n"
        # 备份目录清空移除
        assert not (root / ".fenix" / "merge-backup").exists()
        # 主树回到 merge 前状态（shared.py 为 main 内容，无冲突残留）
        assert (root / "shared.py").read_text(encoding="utf-8") == "MAIN-CONFLICT\n"

    # ───────────────────────── scenario 4: 纯修改分支零开销 ─────────────────────────

    def test_pure_modify_branch_no_backup(self, tmp_path):
        """scenario 4: 分支只修改既有 tracked 文件、无新增，主树 untracked 存在也不创建备份。"""
        root = tmp_path / "repo"
        init_repo(root)

        # 纯修改既有文件，无新增
        make_branch(root, "fenix/impl", "shared.py", "BRANCH\n",
                    shared_content="BRANCH\n")

        # 主树有若干 untracked 文件
        (root / "notes").mkdir(parents=True, exist_ok=True)
        (root / "notes" / "scratch.txt").write_text("scratch\n", encoding="utf-8")
        (root / "openspec" / "changes" / "x").mkdir(parents=True, exist_ok=True)
        (root / "openspec" / "changes" / "x" / "spec.md").write_text("spec\n", encoding="utf-8")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, f"merge 应成功，实际失败: {err}"

        # 不创建备份目录
        assert not (root / ".fenix" / "merge-backup").exists()
        # untracked 文件仍在原地
        assert (root / "notes" / "scratch.txt").exists()
        assert (root / "openspec" / "changes" / "x" / "spec.md").exists()

    # ───────────────────────── scenario 5: 一致副本清理备份 ─────────────────────────

    def test_identical_backup_dropped_after_merge(self, tmp_path):
        """scenario 5: 备份副本与合入版本一致 → 备份目录被删（冗余污染，如三次复现案例）。"""
        root = tmp_path / "repo"
        init_repo(root)

        added_path = "core/dashboard/static/v2/sdk.js"
        # 分支新增同路径文件（内容 = 主树 untracked 副本，完全一致）
        make_branch(root, "fenix/impl", added_path, "IDENTICAL\n")

        # 主树 untracked 副本 = 分支版本（完全一致）
        (root / added_path).parent.mkdir(parents=True, exist_ok=True)
        (root / added_path).write_text("IDENTICAL\n", encoding="utf-8")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, f"merge 应成功，实际失败: {err}"

        # 一致副本 → 备份目录被删
        assert not (root / ".fenix" / "merge-backup").exists(), "一致副本应删备份"

    # ───────────────────────── scenario 6: 不一致副本保留并告警 ─────────────────────────

    def test_inconsistent_backup_retained_with_warning(self, tmp_path):
        """scenario 6: 备份副本与合入版本不一致 → 保留备份且 warning 含路径清单。"""
        root = tmp_path / "repo"
        init_repo(root)

        added_path = "core/dashboard/static/v2/sdk.js"
        # 分支新增同路径文件
        make_branch(root, "fenix/impl", added_path, "BRANCH-VERSION\n")

        # 主树 untracked 副本与分支版本不同（有价值改动）
        (root / added_path).parent.mkdir(parents=True, exist_ok=True)
        (root / added_path).write_text("MAINTREE-VALUABLE\n", encoding="utf-8")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, f"merge 应成功，实际失败: {err}"

        # 不一致副本 → 备份目录保留
        backups = list((root / ".fenix" / "merge-backup").glob("*"))
        assert backups, "不一致副本应保留备份目录"
        backup = backups[0]
        assert (backup / added_path).exists()
        # 主树工作区为分支版本（合入生效）
        assert (root / added_path).read_text(encoding="utf-8") == "BRANCH-VERSION\n"
        # warning 日志含不一致路径清单与备份位置
        warns = wm.logger.warnings
        assert warns, "应出现 warning 日志"
        joined = "\n".join(warns)
        assert added_path in joined, f"warning 应含不一致路径 {added_path}: {joined}"
        assert str(backup) in joined, f"warning 应含备份位置 {backup}: {joined}"


class TestBuildArtifactConflictSelfHeal:
    """构建产物冲突自愈（add-v3-spec-quick-switch 4 次重试耗尽事故治理）。

    实现分支各自重建 dist → 内容哈希文件名跨分支 rename/delete 打架，不是语义
    冲突：全部冲突位于 dist/ 前缀时整目录对齐分支版并完成 merge；混入语义冲突
    时不自愈、保持原失败路径。
    """

    DIST = "core/dashboard/static/v3/dist"

    def _seed_dist(self, root: Path):
        d = root / self.DIST
        d.mkdir(parents=True)
        (d / "umi.aaa.js").write_text("V1\n", encoding="utf-8")
        (d / "keep.js").write_text("K\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] seed dist")

    def test_dist_rename_rename_conflict_self_heals(self, tmp_path):
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_dist(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()
        d = root / self.DIST

        # 分支：umi.aaa.js → umi.bbb.js（分支侧重建）
        git(root, "checkout", "-q", "-b", "fenix/impl")
        git(root, "mv", f"{self.DIST}/umi.aaa.js", f"{self.DIST}/umi.bbb.js")
        git(root, "commit", "-q", "-m", "[fenix] branch dist rebuild")
        git(root, "checkout", "-q", base)

        # 主树：umi.aaa.js → umi.ccc.js（另一分支合入后的重建）
        git(root, "mv", f"{self.DIST}/umi.aaa.js", f"{self.DIST}/umi.ccc.js")
        git(root, "commit", "-q", "-m", "[fenix] main dist rebuild")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, f"dist 冲突应自愈，实际失败: {err}"

        # dist 对齐分支版：bbb 在、aaa/ccc 不在；非冲突文件 keep.js 保留
        assert (d / "umi.bbb.js").exists()
        assert not (d / "umi.aaa.js").exists()
        assert not (d / "umi.ccc.js").exists()
        assert (d / "keep.js").read_text(encoding="utf-8") == "K\n"
        # 工作区干净（merge 已提交）
        assert git(root, "status", "--porcelain").stdout.strip() == ""

    def test_mixed_conflict_not_self_healed(self, tmp_path):
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_dist(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()

        # 分支：dist rename + 改 shared.py
        git(root, "checkout", "-q", "-b", "fenix/impl")
        git(root, "mv", f"{self.DIST}/umi.aaa.js", f"{self.DIST}/umi.bbb.js")
        (root / "shared.py").write_text("BRANCH\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch work")
        git(root, "checkout", "-q", base)

        # 主树：dist rename + 改 shared.py（不同内容 → 语义冲突）
        git(root, "mv", f"{self.DIST}/umi.aaa.js", f"{self.DIST}/umi.ccc.js")
        (root / "shared.py").write_text("MAIN\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] main work")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert not success, "混入语义冲突时不应自愈"
        # 主树回到干净状态（abort 生效，可重试）
        assert git(root, "status", "--porcelain").stdout.strip() == ""
