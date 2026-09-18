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
    # 镜像真实仓库：.fenix/ 运行时目录不入库（产物配置未裁决信号等运行时写入
    # 均落 .fenix/，测试断言「主树干净」必须不受其干扰——真实仓库 .gitignore
    # 以 .fenix/* 整体排除）。
    (root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    return git(root, "rev-parse", "HEAD").stdout.strip()


def make_wm(root: Path, **kwargs) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, CapturingLogger(), **kwargs)


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
        (root / "spec" / "changes" / "x").mkdir(parents=True, exist_ok=True)
        (root / "spec" / "changes" / "x" / "spec.md").write_text("spec\n", encoding="utf-8")

        wm = make_wm(root)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, f"merge 应成功，实际失败: {err}"

        # 不创建备份目录
        assert not (root / ".fenix" / "merge-backup").exists()
        # untracked 文件仍在原地
        assert (root / "notes" / "scratch.txt").exists()
        assert (root / "spec" / "changes" / "x" / "spec.md").exists()

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

    DIST = "core/dashboard/static/dist"

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

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/", "core/dashboard/static/v3/dist/"], has_build_artifacts=True)
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"dist 冲突应自愈，实际失败: {err}"

        # dist 冲突根治 A：对齐 HEAD 版（merge 时 dist 永远以主树为准，
        # 分支重建的最终一致性由 merge 后从 src 重建刷新）——ccc 在、aaa/bbb 不在
        assert (d / "umi.ccc.js").exists()
        assert not (d / "umi.aaa.js").exists()
        assert not (d / "umi.bbb.js").exists()
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

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/", "core/dashboard/static/v3/dist/"], has_build_artifacts=True)
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert not success, "混入语义冲突时不应自愈"
        # dist 冲突根治 A：分类清单只含语义文件——dist 路径不再污染冲突分类
        # 与失败指纹（task-track 09:19 事故：1 条语义 + 9 条产物 → 整单连坐）
        assert info.conflict_paths == ["shared.py"]
        assert info.has_semantic_conflict is True
        # 主树回到干净状态（abort 生效，可重试）
        assert git(root, "status", "--porcelain").stdout.strip() == ""

    # ─────────────────── 目录重命名场景（add-dashboard-incremental-data 事故） ───────────────────

    OLD_DIST = "core/dashboard/static/v3/dist"
    SRC_PAGE = "core/dashboard/static/src/pages/list.tsx"

    def _seed_old_dist(self, root: Path):
        d = root / self.OLD_DIST
        d.mkdir(parents=True)
        (d / "umi.aaa.js").write_text("UMI-BUNDLE-V1;COMMON-PAYLOAD\n", encoding="utf-8")
        (d / "p__overview.aaa.async.js").write_text("P-OVERVIEW-V1;COMMON\n", encoding="utf-8")
        (d / "index.html").write_text("INDEX-V1\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] seed v3 dist")

    def test_directory_rename_artifact_conflicts_self_heal(self, tmp_path):
        """主树重命名 dist 目录（v3/dist→dist）+ 分支在旧路径重建产物 → 自愈且保留主树布局。

        复演 add-dashboard-incremental-data：分支 fork 于重命名前，产物全部落在旧路径，
        merge-back 时 rename/rename + rename/delete + content 冲突爆发。自愈应识别
        全部冲突路径均为产物（按目录层次容错），且布局被主树移动后对齐主树版——
        不复活已删除的旧目录，分支的非产物改动（src）照常合入。
        """
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_old_dist(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()

        # 分支：在旧路径重建产物（hash 变名）+ 改 index.html + 新增 src 页面
        git(root, "checkout", "-q", "-b", "fenix/impl")
        git(root, "rm", "-q", f"{self.OLD_DIST}/umi.aaa.js",
            f"{self.OLD_DIST}/p__overview.aaa.async.js")
        d = root / self.OLD_DIST
        (d / "umi.bbb.js").write_text("UMI-BUNDLE-V2;COMMON-PAYLOAD\n", encoding="utf-8")
        (d / "p__overview.bbb.async.js").write_text("P-OVERVIEW-V2;COMMON\n", encoding="utf-8")
        (d / "index.html").write_text("INDEX-V2-BRANCH\n", encoding="utf-8")
        src = root / self.SRC_PAGE
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("BRANCH-SRC\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch rebuild at old path")
        git(root, "checkout", "-q", base)

        # 主树：目录重命名 v3/dist → dist，并在新路径重建
        git(root, "mv", self.OLD_DIST, self.DIST)
        d = root / self.DIST
        git(root, "rm", "-q", "-f", f"{self.DIST}/umi.aaa.js",
            f"{self.DIST}/p__overview.aaa.async.js")
        (d / "umi.ccc.js").write_text("UMI-BUNDLE-V1R;COMMON-PAYLOAD\n", encoding="utf-8")
        (d / "p__overview.ccc.async.js").write_text("P-OVERVIEW-V1R;COMMON\n", encoding="utf-8")
        (d / "index.html").write_text("INDEX-V2-MAIN\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] main: flatten v3 dist layout")

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/", "core/dashboard/static/v3/dist/"], has_build_artifacts=True)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, f"产物冲突应自愈，实际失败: {err}"

        # 主树布局保留：新路径产物在（主树版），旧目录不复活
        assert (d / "umi.ccc.js").exists()
        assert (d / "index.html").read_text(encoding="utf-8") == "INDEX-V2-MAIN\n"
        assert not (root / self.OLD_DIST).exists(), "旧目录不应被分支侧产物复活"
        # 分支的非产物改动照常合入
        assert (root / self.SRC_PAGE).read_text(encoding="utf-8") == "BRANCH-SRC\n"
        # 工作区干净（merge 已提交）
        assert git(root, "status", "--porcelain").stdout.strip() == ""


class TestDistConflictRootCure:
    """dist 冲突根治（2026-09-04 task-track / help-center 连环事故治理）。

    A. 产物冲突无条件对齐 HEAD：不再要求「全部冲突都是产物」——混合冲突
       （1 条语义 + N 条产物）不再连坐整单废弃；语义分类只看非产物路径，
       失败指纹不再被 dist hash 噪声污染。
    B. merge-back 成功路径从合并后 src 确定性重建 dist：自愈对齐的 dist 是
       分支时点 src 的构建物，与合并后 src 必然漂移——重建是唯一收口。
    """

    DIST = "core/dashboard/static/dist"
    SRC_PAGE = "core/dashboard/static/src/pages/list.tsx"

    def _seed(self, root: Path):
        d = root / self.DIST
        d.mkdir(parents=True)
        (d / "umi.aaa.js").write_text("V1\n", encoding="utf-8")
        (d / "keep.js").write_text("K\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] seed dist")

    def _branch_rebuild(self, root: Path, base: str, chunk: str = "umi.bbb.js",
                        with_src: bool = False):
        """分支侧重建 dist（rename + 新增 chunk），可选带 src 变更。"""
        git(root, "checkout", "-q", "-b", "fenix/impl")
        git(root, "mv", f"{self.DIST}/umi.aaa.js", f"{self.DIST}/{chunk}")
        d = root / self.DIST
        (d / "p__page.bbb.async.js").write_text("P-BRANCH\n", encoding="utf-8")
        (d / "index.html").write_text("INDEX-BRANCH\n", encoding="utf-8")
        if with_src:
            src = root / self.SRC_PAGE
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text("BRANCH-SRC\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch rebuild")
        git(root, "checkout", "-q", base)

    # ── A：混合冲突不再连坐 ──────────────────────────────────────

    def test_branch_only_dist_adds_dropped(self, tmp_path):
        """分支干净 add 的新产物（非冲突）不复活——merge 后 staged dist == HEAD 集合。

        旧实现只对「主树移动过布局」场景收口 stray；新范式下 dist 一律以 HEAD
        为准、由重建刷新，clean-add 的旧 hash chunk 同样不进入 merge 提交。
        """
        root = tmp_path / "repo"
        init_repo(root)
        self._seed(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()

        # 分支：rename aaa→bbb（与主树 rename 打架）+ 干净 add 新 chunk
        self._branch_rebuild(root, base)
        # 主树：rename aaa→ccc
        git(root, "mv", f"{self.DIST}/umi.aaa.js", f"{self.DIST}/umi.ccc.js")
        git(root, "commit", "-q", "-m", "[fenix] main rebuild")

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/"], has_build_artifacts=True)
        info = wm.merge_back_from_branch("fenix/impl")
        success, _ = info
        assert success, "纯产物冲突应自愈"
        d = root / self.DIST
        assert (d / "umi.ccc.js").exists(), "HEAD 版保留"
        assert not (d / "umi.bbb.js").exists(), "分支版不复活"
        assert not (d / "p__page.bbb.async.js").exists(), "分支干净 add 的新产物同样不复活"
        assert (d / "keep.js").read_text(encoding="utf-8") == "K\n"
        assert git(root, "status", "--porcelain").stdout.strip() == ""

    # ── B：merge 后从 src 确定性重建 ─────────────────────────────

    def _fake_build(self, monkeypatch, wm, write_dist=None, fail=False):
        """patch _run_dist_build：记录调用、可选模拟构建产物 / 失败。"""
        calls = {"n": 0}

        def fake():
            calls["n"] += 1
            if fail:
                return False
            if write_dist:
                for rel, content in write_dist.items():
                    p = Path(wm.project_root) / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content, encoding="utf-8")
            return True

        monkeypatch.setattr(wm, "_run_dist_build", fake, raising=False)
        return calls

    def test_merge_touching_static_src_rebuilds_and_amends(self, tmp_path, monkeypatch):
        """merge 触碰 static src → 重建被调用，重建产物 amend 进 merge 提交。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()
        self._branch_rebuild(root, base, with_src=True)
        # 主树不动 dist（分支 src/dist 无冲突，纯干净 merge 但触碰 src）

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/"], has_build_artifacts=True)
        calls = self._fake_build(
            monkeypatch, wm,
            write_dist={f"{self.DIST}/index.html": "INDEX-REBUILT\n",
                        f"{self.DIST}/umi.aaa.js": "V1-REBUILT\n",
                        f"{self.DIST}/umi.bbb.js": "BRANCH-CHUNK-REBUILT\n"},
        )
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"干净 merge 应成功: {err}"
        assert calls["n"] == 1, "触碰 static src 的 merge 应触发一次重建"
        # 重建产物 amend 进 merge commit：HEAD 树里是重建版
        head_index = git(root, "show", f"HEAD:{self.DIST}/index.html").stdout
        assert head_index == "INDEX-REBUILT\n"
        # 分支侧 chunk 在重建产物中复活（重建以合并后 src 为准，与 HEAD 对齐无关）
        head_chunk = git(root, "show", f"HEAD:{self.DIST}/umi.bbb.js").stdout
        assert head_chunk == "BRANCH-CHUNK-REBUILT\n"
        # 工作区干净（amend 收口，无 staged/unstaged 残留）
        assert git(root, "status", "--porcelain").stdout.strip() == ""

    def test_merge_without_static_src_skips_rebuild(self, tmp_path, monkeypatch):
        """merge 未触碰 static src（纯后端 spec）→ 不触发重建。"""
        root = tmp_path / "repo"
        init_repo(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "shared.py").write_text("BRANCH\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] backend only")
        git(root, "checkout", "-q", base)

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/"], has_build_artifacts=True)
        calls = self._fake_build(monkeypatch, wm)
        success, err = wm.merge_back_from_branch("fenix/impl")
        assert success, err
        assert calls["n"] == 0, "未触碰 static src 不应重建"

    def test_rebuild_failure_keeps_merge_and_clean_tree(self, tmp_path, monkeypatch):
        """重建失败：merge 提交保留、dist 回到提交版、主树干净、不抛异常。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()
        self._branch_rebuild(root, base, with_src=True)

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/"], has_build_artifacts=True)
        calls = self._fake_build(monkeypatch, wm, fail=True)
        info = wm.merge_back_from_branch("fenix/impl")
        success, _ = info
        assert success, "重建失败不应否定 merge 本身"
        assert calls["n"] == 1
        # HEAD 保留 merge commit；dist 为提交时状态，主树干净可重试
        assert git(root, "status", "--porcelain").stdout.strip() == ""

    def test_self_heal_path_triggers_rebuild(self, tmp_path, monkeypatch):
        """自愈完成 merge 的路径同样触发重建（对齐 HEAD 只是过场，重建才是终态）。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()
        self._branch_rebuild(root, base, with_src=True)
        # 主树：rename aaa→ccc（制造产物冲突；分支 src 照常干净合入）
        git(root, "mv", f"{self.DIST}/umi.aaa.js", f"{self.DIST}/umi.ccc.js")
        git(root, "commit", "-q", "-m", "[fenix] main rebuild")

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/"], has_build_artifacts=True)
        calls = self._fake_build(
            monkeypatch, wm,
            write_dist={f"{self.DIST}/index.html": "INDEX-REBUILT\n"},
        )
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"产物冲突应自愈: {err}"
        assert calls["n"] == 1, "自愈 merge 触碰 src 时应触发重建"
        head_index = git(root, "show", f"HEAD:{self.DIST}/index.html").stdout
        assert head_index == "INDEX-REBUILT\n"
        assert git(root, "status", "--porcelain").stdout.strip() == ""

    def test_already_merged_skips_rebuild(self, tmp_path, monkeypatch):
        """already merged 早退路径不触发重建（HEAD^1 diff 是旧 merge，不可误判）。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed(root)
        base = git(root, "rev-parse", "HEAD").stdout.strip()
        self._branch_rebuild(root, base)
        git(root, "merge", "-q", "--no-ff", "fenix/impl",
            "-m", "[fenix] merge implementer branch fenix/impl")

        wm = make_wm(root, build_artifact_paths=["core/dashboard/static/dist/"], has_build_artifacts=True)
        calls = self._fake_build(monkeypatch, wm)
        info = wm.merge_back_from_branch("fenix/impl")
        success, _ = info
        assert success
        assert calls["n"] == 0, "already merged 早退不应重建"


class TestDistBuildContractDriven:
    """_run_dist_build 契约驱动（不预设 nodejs 项目）：构建内容从 verify.yaml prepare 读取。"""

    def test_contract_prepare_steps_run(self, tmp_path):
        init_repo(tmp_path)
        (tmp_path / ".fenix").mkdir(exist_ok=True)
        (tmp_path / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: touch built.txt\n", encoding="utf-8")
        wm = make_wm(tmp_path)
        assert wm._run_dist_build() is True
        assert (tmp_path / "built.txt").exists(), "prepare 步骤应真实执行"

    def test_contract_empty_prepare_is_noop_success(self, tmp_path):
        """契约存在但未声明 prepare =「无构建步骤」，直接成功。"""
        init_repo(tmp_path)
        (tmp_path / ".fenix").mkdir(exist_ok=True)
        (tmp_path / ".fenix" / "verify.yaml").write_text(
            "serve:\n  kind: static\n  root: site\n", encoding="utf-8")
        wm = make_wm(tmp_path)
        assert wm._run_dist_build() is True

    def test_contract_prepare_failure_returns_false(self, tmp_path):
        init_repo(tmp_path)
        (tmp_path / ".fenix").mkdir(exist_ok=True)
        (tmp_path / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: exit 3\n", encoding="utf-8")
        wm = make_wm(tmp_path)
        assert wm._run_dist_build() is False

    def test_no_contract_falls_back_to_legacy_npm(self, tmp_path, monkeypatch):
        """契约缺失回退历史行为：DASHBOARD_STATIC_ROOT 下 npm run build。"""
        init_repo(tmp_path)
        wm = make_wm(tmp_path)
        static_dir = tmp_path / "core" / "dashboard" / "static"
        static_dir.mkdir(parents=True)
        (static_dir / "package.json").write_text("{}", encoding="utf-8")
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            seen["cwd"] = kw.get("cwd")

            class R:
                returncode = 0
            return R()

        monkeypatch.setattr("core.worktree_manager.subprocess.run", fake_run)
        assert wm._run_dist_build() is True
        assert seen["cmd"] == ["npm", "run", "build"]
        assert Path(seen["cwd"]) == static_dir

    def test_no_contract_no_package_json_skips(self, tmp_path):
        init_repo(tmp_path)
        wm = make_wm(tmp_path)
        assert wm._run_dist_build() is False


class TestSupersededStashDrop:
    """fix-mergeback-stashpop-silent-loss D2：pop 冲突自愈后被取代条目自动 drop。

    三个 spec scenario：
      1. stash 版被合并结果完全取代（树级 diff 全 0）→ 条目自动 drop
      2. stash 版有独立差异 → 条目保留（端到端 pop 冲突自愈路径）
      3. pop 后 sha 被新条目顶掉 → 放弃 drop
    """

    def _branch_modifies_shared(self, root: Path, branch_content: str):
        """从 BASE 派生分支 fenix/impl 修改 shared.py，checkout 回 BASE。返回 BASE sha。"""
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "shared.py").write_text(branch_content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch modifies shared.py")
        git(root, "checkout", "-q", base_sha)
        return base_sha

    def _make_conflicting_stash(self, root: Path, wip_content: str) -> str:
        """构造「HEAD 已含合并结果 + 主树 WIP 已 autostash」的判定现场。

        _drop_superseded_stash_entry 的判定语义是「stash 版 vs 合并后 HEAD 版」，
        因此先写 WIP（≠ 当前 BASE，保证主树脏可 autostash）→ ensure_clean_tree
        stash → 再推进 HEAD 到分支（等价 merge 结果已入 HEAD）。stash 提交树
        即 WIP 时刻工作区快照，此后 stash 版与推进后的 HEAD 版可逐 blob 对比。
        """
        (root / "shared.py").write_text(wip_content, encoding="utf-8")
        wm_probe = make_wm(root)
        assert wm_probe.ensure_clean_tree() is True
        st = git(root, "stash", "list").stdout
        assert "fenix: pre-dispatch autostash" in st
        git(root, "merge", "--no-ff", "fenix/impl",
            "-m", "[fenix] merge impl (simulated)")
        assert (root / "shared.py").read_text(encoding="utf-8") == "MERGED\n"
        return git(root, "rev-parse", "--verify", "stash@{0}").stdout.strip()

    def test_stash_subsumed_by_merge_result_is_dropped(self, tmp_path):
        """scenario 1: stash 版 == 合并后 HEAD 版（树级 diff 全 0）→ 条目自动 drop。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._branch_modifies_shared(root, "MERGED\n")
        # WIP 与分支版一致：stash 提交树中 shared.py == 合并后 HEAD 版
        sha = self._make_conflicting_stash(root, "MERGED\n")

        wm = make_wm(root)
        assert wm._drop_superseded_stash_entry(sha, ["shared.py"]) is True

        lst = git(root, "stash", "list")
        assert "fenix: pre-dispatch autostash" not in lst.stdout, \
            f"被取代条目应被 drop，实际栈: {lst.stdout!r}"
        drop_logs = [w for w in wm.logger.warnings
                     if "auto-dropped" in w and sha[:12] in w]
        assert drop_logs, f"应记录含 drop sha 的日志: {wm.logger.warnings}"

    def test_clean_pop_no_drop_side_effect(self, tmp_path):
        """scenario 1 补充：pop 干净成功（无 UU）→ 不触发 drop 判定、内容完整回贴。"""
        root = tmp_path / "repo"
        init_repo(root)
        # 分支修改 shared.py 并新增 tracked extra.py
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "shared.py").write_text("MERGED\n", encoding="utf-8")
        (root / "extra.py").write_text("BASE-EXTRA\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch +extra")
        git(root, "checkout", "-q", base_sha)
        # 主树 WIP：extra.py 改成与分支版相同内容（无冲突语义，pop 干净）
        (root / "extra.py").write_text("BASE-EXTRA\n", encoding="utf-8")
        # extra.py 与 BASE 内容相同 → 主树不脏；改用 shared.py 制造脏（与 BASE 不同）
        (root / "shared.py").write_text("WIP\n", encoding="utf-8")
        wm = make_wm(root)
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"merge 应成功，实际失败: {err}"
        # WIP 与分支版不同 → 有独立差异 → 条目保留（闸门收纳路径用独立前缀
        # WIP_GATE_STASH_PREFIX，与 AUTOSTASH_MSG_PREFIX 隔离——reclaim_stale_
        # autostash 按子串匹配只回收后者，故意保留待找回的条目不会被 60s 巡检抢走）
        lst = git(root, "stash", "list")
        assert "fenix: wip-overlap gate stash" in lst.stdout
        assert (root / "extra.py").read_text(encoding="utf-8") == "BASE-EXTRA\n"

    def test_stash_with_unique_diff_is_preserved(self, tmp_path):
        """scenario 2: stash 版与合并后 HEAD 版树级 diff 非空 → 条目保留 + 找回命令。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._branch_modifies_shared(root, "MERGED\n")
        sha = self._make_conflicting_stash(root, "WIP-UNIQUE\n")

        wm = make_wm(root)
        assert wm._drop_superseded_stash_entry(sha, ["shared.py"]) is False

        lst = git(root, "stash", "list")
        assert "fenix: pre-dispatch autostash" in lst.stdout, \
            f"有独立差异的条目应保留，实际栈: {lst.stdout!r}"

    def test_restore_conflict_preserves_entry_and_logs_recover_cmd(self, tmp_path):
        """scenario 2 端到端：真实 pop 冲突自愈路径，条目保留且日志含找回命令。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._branch_modifies_shared(root, "MERGED\n")
        sha = self._make_conflicting_stash(root, "WIP-UNIQUE\n")

        wm = make_wm(root)
        ok, conflict_files = wm.restore_after_merge()
        assert ok is True
        assert conflict_files == ["shared.py"], f"应检出 UU 冲突文件: {conflict_files}"
        # 主树为合并结果、干净可写
        assert (root / "shared.py").read_text(encoding="utf-8") == "MERGED\n"
        st = git(root, "status", "--porcelain")
        assert not st.stdout.strip(), f"主树应干净: {st.stdout!r}"
        # 有独立差异 → 条目保留
        lst = git(root, "stash", "list")
        assert "fenix: pre-dispatch autostash" in lst.stdout, \
            f"有差异条目应保留，实际栈: {lst.stdout!r}"
        # 日志含逐文件找回命令
        keep_logs = [w for w in wm.logger.warnings
                     if f"git show {sha}:shared.py" in w]
        assert keep_logs, f"应记录逐文件找回命令: {wm.logger.warnings}"

    def test_sha_no_longer_top_aborts_drop(self, tmp_path, monkeypatch):
        """scenario 3: drop 前栈顶核对发现 sha 被新条目顶掉 → 放弃 drop。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._branch_modifies_shared(root, "MERGED\n")
        sha = self._make_conflicting_stash(root, "MERGED\n")

        wm = make_wm(root)
        # 模拟「自愈期间有新条目入栈」：drop 前的栈顶核对返回不同 sha
        orig_run = subprocess.run

        def fake_run(cmd, **kw):
            if "rev-parse" in cmd and any("stash@{0}" in a for a in cmd):
                class R:
                    returncode = 0
                    stdout = "f" * 40 + "\n"
                    stderr = ""
                return R()
            return orig_run(cmd, **kw)

        import core.worktree_manager as twm
        monkeypatch.setattr(twm.subprocess, "run", fake_run)
        assert wm._drop_superseded_stash_entry(sha, ["shared.py"]) is False

        # 条目保留
        lst = git(root, "stash", "list")
        assert "fenix: pre-dispatch autostash" in lst.stdout, \
            f"放弃 drop 后条目应保留，实际栈: {lst.stdout!r}"
        skip_logs = [w for w in wm.logger.warnings if "已变化" in w]
        assert skip_logs, f"应记录跳过原因: {wm.logger.warnings}"

    def test_unknown_pinned_sha_skips_drop(self, tmp_path):
        """sha 未知（pop 前 rev-parse 失败）→ 保守保留条目。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._branch_modifies_shared(root, "MERGED\n")
        sha = self._make_conflicting_stash(root, "MERGED\n")

        wm = make_wm(root)
        assert wm._drop_superseded_stash_entry("", ["shared.py"]) is False
        lst = git(root, "stash", "list")
        assert "fenix: pre-dispatch autostash" in lst.stdout


class TestWipOverlapPrecheck:
    """fix-mergeback-stashpop-silent-loss D3：merge-back 前 WIP 重叠预检。

    两个 spec scenario：
      1. 脏 tracked 文件与分支改动相交 → WARNING + wip_overlap 非空
      2. 无交集 → 零 WARNING、流程与现状一致
    """

    def _branch_touches(self, root: Path, edits: dict):
        """从 BASE 派生分支 fenix/impl 修改若干 tracked 文件，checkout 回 BASE。"""
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        for path, content in edits.items():
            p = root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch edits")
        git(root, "checkout", "-q", base_sha)

    def test_overlap_warns_and_populates_wip_overlap(self, tmp_path):
        """scenario 1: 脏文件 core/a.py 与分支改动都含 core/a.py → WARNING + 非空。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / "core").mkdir()
        (root / "core" / "a.py").write_text("BASE-A\n", encoding="utf-8")
        (root / "core" / "b.py").write_text("BASE-B\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add core files")
        self._branch_touches(root, {
            "core/a.py": "BRANCH-A\n",
            "core/b.py": "BRANCH-B\n",
        })

        # 主树 WIP：改 core/a.py（与分支相交）与 core/b.py（不相交的另一个）
        (root / "core" / "a.py").write_text("WIP-A\n", encoding="utf-8")

        wm = make_wm(root)
        overlap = wm._detect_wip_overlap("fenix/impl")
        assert overlap == ["core/a.py"], f"应仅含相交文件: {overlap}"
        warn_logs = [w for w in wm.logger.warnings
                     if "WIP overlap" in w and "core/a.py" in w]
        assert warn_logs, f"应记录含重叠清单的 WARNING: {wm.logger.warnings}"

        # 端到端：merge_back_from_branch 返回的 MergeConflictInfo 携带重叠清单
        (root / "core" / "a.py").write_text("WIP-A\n", encoding="utf-8")
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"merge 应成功（预检不阻断），实际失败: {err}"
        assert info.wip_overlap == ["core/a.py"], \
            f"MergeConflictInfo.wip_overlap 应非空: {info.wip_overlap}"

    def test_no_overlap_is_silent_and_unchanged(self, tmp_path):
        """scenario 2: 无交集 → 零重叠 WARNING、merge 成功、wip_overlap 空。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / "core").mkdir()
        (root / "core" / "a.py").write_text("BASE-A\n", encoding="utf-8")
        (root / "core" / "b.py").write_text("BASE-B\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add core files")
        self._branch_touches(root, {"core/a.py": "BRANCH-A\\n"})

        # 主树 WIP：只改不相交的 core/b.py
        (root / "core" / "b.py").write_text("WIP-B\\n", encoding="utf-8")

        wm = make_wm(root)
        overlap = wm._detect_wip_overlap("fenix/impl")
        assert overlap == [], f"无交集应返回空: {overlap}"
        overlap_warns = [w for w in wm.logger.warnings if "WIP overlap" in w]
        assert not overlap_warns, f"不应有重叠 WARNING: {wm.logger.warnings}"

        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"merge 应成功，实际失败: {err}"
        assert info.wip_overlap == [], \
            f"无重叠时 wip_overlap 应为空: {info.wip_overlap}"
        # 流程与现状一致：merge 结果正常落主树，autostash 正常恢复
        assert (root / "core" / "a.py").read_text(encoding="utf-8") == "BRANCH-A\\n"
        assert (root / "core" / "b.py").read_text(encoding="utf-8") == "WIP-B\\n"

    def test_clean_tree_produces_no_warning(self, tmp_path):
        """主树干净 → 预检零开销静默、零 WARNING。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / "core").mkdir()
        (root / "core" / "a.py").write_text("BASE-A\\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add core/a.py")
        self._branch_touches(root, {"core/a.py": "BRANCH-A\\n"})

        wm = make_wm(root)
        assert wm._detect_wip_overlap("fenix/impl") == []
        overlap_warns = [w for w in wm.logger.warnings if "WIP overlap" in w]
        assert not overlap_warns


class TestWipOverlapGate:
    """evo-merge-back-wip-overlap-gate：merge-back 前 WIP 重叠闸门。

    tasks 2.1-2.4 四个 spec scenario：
      1. 重叠 + 阻塞策略 → merge-back 中止且 wip_gate_blocked=True、主树可写、
         无文件被丢弃、无 stash 被创建
      2. 默认（收纳）策略 → 重叠改动被收纳、merge 成功、WIP 在 stash 中找到
         （pop 冲突保留条目）且 merge 后主树 WIP 恢复（不同 hunk 干净恢复）
      3. 仅 spec/changes/** 重叠 → 闸门不阻塞、不收纳，沿用现行行为
      4. 无重叠 / 主树干净 → 行为与既有用例逐字节一致（含显式配置阻塞策略时）
    """

    def _branch_edits_core_a(self, root: Path, content: str) -> str:
        """分支 fenix/impl 修改 core/a.py 为 content，checkout 回 BASE。返回 BASE sha。"""
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "core" / "a.py").write_text(content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch edits core/a.py")
        git(root, "checkout", "-q", base_sha)
        return base_sha

    def _seed_core_a(self, root: Path, content: str = "BASE-A\n"):
        (root / "core").mkdir()
        (root / "core" / "a.py").write_text(content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add core/a.py")

    # ───────────────────────── tasks 2.1: 阻塞策略 ─────────────────────────

    def test_block_policy_aborts_merge_with_zero_pollution(self, tmp_path):
        """重叠 + 阻塞策略 → 中止、wip_gate_blocked=True、主树零污染。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_core_a(root)
        base_sha = self._branch_edits_core_a(root, "BRANCH-A\n")
        # 主树 WIP 与分支重叠（同路径）
        (root / "core" / "a.py").write_text("WIP-A\n", encoding="utf-8")

        wm = make_wm(root, mergeback_wip_overlap_policy="block")
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert not success, f"阻塞策略下 merge-back 应中止: {err}"
        assert info.wip_gate_blocked is True, "应返回可区分的 wip_gate_blocked=True"
        assert info.wip_overlap == ["core/a.py"], f"重叠清单应含 core/a.py: {info.wip_overlap}"

        # 主树零污染：不 stash、不 merge、不 pop
        st = git(root, "stash", "list")
        assert not st.stdout.strip(), f"阻塞不应创建任何 stash: {st.stdout!r}"
        assert git(root, "rev-parse", "HEAD").stdout.strip() == base_sha, \
            "阻塞不应推进 HEAD（不 merge）"
        # 无文件被丢弃：WIP 仍在工作区
        assert (root / "core" / "a.py").read_text(encoding="utf-8") == "WIP-A\n"
        # 主树保持可写（后续 git 写操作可用，无 index 半合并）
        (root / "core" / "write.txt").write_text("ok\n", encoding="utf-8")
        git(root, "add", "core/write.txt")
        git(root, "commit", "-q", "-m", "[fenix] main tree still writable")
        # WIP 原样保留在工作区（唯一脏项 core/a.py 未被触碰、未被丢弃）
        assert git(root, "status", "--porcelain").stdout.strip() == "M core/a.py"

    # ───────────────────────── tasks 2.2: 默认收纳策略 ─────────────────────────

    def test_default_auto_policy_preserves_wip_on_pop_conflict(self, tmp_path):
        """收纳策略 + pop 冲突：merge 成功、条目保留在 stash（可 git show 找回）。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_core_a(root)
        self._branch_edits_core_a(root, "BRANCH-A\n")
        # 主树 WIP 与分支同路径（内容不同 → pop 必冲突）
        (root / "core" / "a.py").write_text("WIP-A\n", encoding="utf-8")

        wm = make_wm(root)  # 默认 auto
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"收纳策略下 merge 应成功: {err}"
        assert info.wip_gate_blocked is False

        # merge 结果落主树；主树干净可写（无 UU 残留）
        assert (root / "core" / "a.py").read_text(encoding="utf-8") == "BRANCH-A\n"
        st = git(root, "status", "--porcelain")
        assert not st.stdout.strip(), f"主树应干净可写: {st.stdout!r}"
        # 未提交内容可在 stash 中找到（闸门专用前缀，独立于 autostash）
        lst = git(root, "stash", "list")
        assert "fenix: wip-overlap gate stash" in lst.stdout, \
            f"闸门收纳条目应保留在栈中: {lst.stdout!r}"
        show = git(root, "show", "stash@{0}:core/a.py")
        assert show.stdout == "WIP-A\n", f"stash 应保有 WIP 内容: {show.stdout!r}"

    def test_default_auto_policy_recovers_wip_after_merge(self, tmp_path):
        """收纳策略：重叠改动被收纳（stash 可找回）+ merge 成功 + 非重叠 WIP 恢复。

        主树 WIP 同时含：core/a.py（与分支重叠，pop 冲突 → 条目保留在 stash 可
        找回）与 notes/scratch.txt（不重叠，pop 干净 → merge 后已恢复）。同一次
        merge-back 同时验证「未提交内容可在 stash 中找到」与「主树 WIP 已恢复」。
        """
        root = tmp_path / "repo"
        init_repo(root)
        (root / "core").mkdir()
        (root / "core" / "a.py").write_text("L1-BASE\nL2-BASE\n", encoding="utf-8")
        (root / "notes").mkdir()
        (root / "notes" / "scratch.txt").write_text("SCRATCH-BASE\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add core/a.py + notes/scratch.txt")
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "core" / "a.py").write_text("BRANCH-A\nL2-BASE\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch edits core/a.py")
        git(root, "checkout", "-q", base_sha)
        # 主树 WIP：core/a.py（与分支重叠）+ notes/scratch.txt（不重叠）
        (root / "core" / "a.py").write_text("L1-BASE\nL2-WIP-A\n", encoding="utf-8")
        (root / "notes" / "scratch.txt").write_text("SCRATCH-WIP\n", encoding="utf-8")

        wm = make_wm(root)  # 默认 auto
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"收纳策略下 merge 应成功: {err}"
        # 重叠文件：分支改动合入；pop 冲突 → 条目保留（未提交内容可在 stash 找回）
        assert (root / "core" / "a.py").read_text(encoding="utf-8") == \
            "BRANCH-A\nL2-BASE\n", "重叠文件以合并结果为准"
        lst = git(root, "stash", "list")
        assert "fenix: wip-overlap gate stash" in lst.stdout, \
            f"闸门收纳条目应保留在栈中: {lst.stdout!r}"
        show = git(root, "show", "stash@{0}:core/a.py")
        assert show.stdout == "L1-BASE\nL2-WIP-A\n", \
            f"stash 应保有重叠文件的 WIP 内容: {show.stdout!r}"
        # 非重叠 WIP：merge 后已恢复（pop 干净恢复，保持未提交——这是用户改动的本义）
        assert (root / "notes" / "scratch.txt").read_text(encoding="utf-8") == \
            "SCRATCH-WIP\n", "非重叠 WIP 应在 merge 后恢复"
        # 无 UU 半合并残留（core/a.py 冲突已自愈、可写）；恢复的 WIP 以未提交修改呈现
        st = git(root, "status", "--porcelain")
        lines = st.stdout.splitlines()
        assert not any(
            l.startswith("U") or l.startswith("AA") or l.startswith("DD") for l in lines
        ), f"不应有 UU 残留: {st.stdout!r}"
        assert any(l.lstrip().startswith("M notes/scratch.txt") for l in lines), \
            f"notes WIP 应恢复为未提交修改: {st.stdout!r}"

    # ───────────────────────── tasks 2.3: 闸门作用域排除 spec/changes ─────────────────────────

    def test_spec_changes_overlap_not_gated(self, tmp_path):
        """仅 spec/changes/** 重叠 → 闸门不阻塞、不收纳（沿用现行行为）。"""
        root = tmp_path / "repo"
        init_repo(root)
        spec_task = "spec/changes/demo/tasks.md"
        (root / "spec" / "changes" / "demo").mkdir(parents=True)
        (root / spec_task).write_text("- [ ] 1.1 base\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add spec tasks")
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / spec_task).write_text("- [x] 1.1 done\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch edits spec tasks")
        git(root, "checkout", "-q", base_sha)
        # 主树 WIP：改同一 tasks.md（叠加重叠，但应被闸门判定排除）
        (root / spec_task).write_text("- [x] 1.1 dirty-wip\n", encoding="utf-8")

        # 即使显式配置阻塞策略，spec/changes 重叠也不触发闸门
        wm = make_wm(root, mergeback_wip_overlap_policy="block")
        assert wm._detect_wip_overlap("fenix/impl") == [], \
            "闸门作用域应排除 spec/changes/**"
        info = wm.merge_back_from_branch("fenix/impl")
        assert info.wip_gate_blocked is False, \
            "spec/changes 重叠 MUST NOT 触发闸门阻塞"
        # 沿用现行行为：该前缀被 stash 排除（收纳对它无效），merge 走既有失败路径
        # （git 保护拒绝 "local changes would be overwritten"），不新增 stash/阻塞语义
        st = git(root, "stash", "list")
        assert not st.stdout.strip(), f"不应新增任何 stash: {st.stdout!r}"

    # ───────────────────────── tasks 2.4: 无重叠 / 主树干净回归 ─────────────────────────

    def test_no_overlap_ignores_block_policy(self, tmp_path):
        """无重叠（主树干净 tracked 态）→ 即使配置 block 策略也逐字节现行行为。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_core_a(root)
        self._branch_edits_core_a(root, "BRANCH-A\n")

        wm = make_wm(root, mergeback_wip_overlap_policy="block")
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"无重叠时 merge 应正常完成: {err}"
        assert info.wip_gate_blocked is False
        assert info.wip_overlap == []
        # 结果与既有用例逐字节一致：分支改动合入、主树干净
        assert (root / "core" / "a.py").read_text(encoding="utf-8") == "BRANCH-A\n"
        assert git(root, "status", "--porcelain").stdout.strip() == ""
        # 无 stash 产生（主树 tracked 干净 → 无 autostash）
        assert not git(root, "stash", "list").stdout.strip()

    def test_clean_tree_no_gate_no_warning(self, tmp_path):
        """主树干净 → 闸门零介入、零 WARNING（与既有 precheck 语义一致）。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_core_a(root)
        self._branch_edits_core_a(root, "BRANCH-A\n")

        wm = make_wm(root)
        gate_blocked, overlap = wm._wip_overlap_gate("fenix/impl")
        assert gate_blocked is None
        assert overlap == []
        gate_warns = [w for w in wm.logger.warnings if "WIP overlap gate" in w]
        assert not gate_warns, f"主树干净不应有闸门 WARNING: {wm.logger.warnings}"
