"""tests/test_worktree_wip_artifact_scope.py — 产物路径判定器与 WIP 重叠闸门测试。

evo-merge-back-wip-artifact-scope D5 测试策略：
  1. 判定矩阵：默认前缀命中 / 根级 dist 默认为假 / 配置 dist/ 后为真 /
     fenix-newtab-*.zip 命中发布包 / *.zip MUST NOT 命中 src/vendor/pkg.zip /
     未以 / 结尾项被丢弃 / 绝对路径与 .. 项被丢弃 / 配置形态非法回退默认 /
     空列表等价默认
  2. WIP 重叠闸门：产物脏改动不计入重叠集合（只读口径不变），语义重叠仍计入，
     spec/changes/** 排除不受产物配置影响
  3. 预演闸分类：冲突全为配置产物放行，含语义路径返回 rehearsed=True 且
     conflict_paths 不含产物路径；包级 _is_build_artifact_path 保持默认语义
  4. 链路切断（D3b 核心验收）：纯产物重叠 → checkout HEAD 对齐被调用、
     wip_overlap 为空、last_stash_pop_conflicts 为空；主树独有产物 → 对齐未
     被调用、仍走 stash/pop 往返；对齐失败 → 路径并入 wip_overlap 且不阻塞；
     语义重叠 → 对齐不接收该路径、闸门按 policy 照常处置
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from core.worktree_manager import (
    WorktreeManager,
    _is_build_artifact_path,
)
from core.worktree_manager.artifact_paths import (
    ArtifactPathMatcher,
    DEFAULT_ARTIFACT_PREFIXES,
    normalize_artifact_patterns,
)

from test_agent_runner import FakeLogger
from test_worktree_merge_guard import git, init_repo


def make_wm(root: Path, **kwargs) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger(), **kwargs)


# ── 1. 判定矩阵 ─────────────────────────────────────────────────────────────

class TestArtifactPathMatcherMatrix:
    """判定矩阵：默认前缀 / 配置前缀 / 通配 / 非法项丢弃。"""

    def test_default_prefix_hits_dashboard_artifact(self):
        """默认前缀下 core/dashboard/static/**/dist/x.js 为真。"""
        m = ArtifactPathMatcher()
        assert m.is_artifact("core/dashboard/static/v3/dist/assets/a.js")
        assert m.is_artifact("core/dashboard/static/dist/assets/a.js")

    def test_root_dist_false_by_default(self):
        """根级 dist/x.js 默认判定为假。"""
        m = ArtifactPathMatcher()
        assert not m.is_artifact("dist/index.html")
        assert not m.is_artifact("dist/assets/a.js")

    def test_dist_as_last_segment_false(self):
        """dist 为末段（非目录层级）默认判定为假。"""
        m = ArtifactPathMatcher()
        assert not m.is_artifact("core/dashboard/static/dist")

    def test_configured_prefix_hits_root_dist(self):
        """配置 'dist/' 后根级 dist/ 判定为真。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["dist/"]))
        assert m.is_artifact("dist/index.html")
        assert m.is_artifact("dist/assets/a.js")

    def test_glob_hits_release_package(self):
        """配置 'fenix-newtab-*.zip' 命中发布包。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["fenix-newtab-*.zip"]))
        assert m.is_artifact("fenix-newtab-v1.0.0.zip")

    def test_glob_does_not_cross_directory(self):
        """'*.zip' MUST NOT 命中 src/vendor/pkg.zip（通配不跨目录）。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["*.zip"]))
        assert m.is_artifact("pkg.zip")  # 根级同名文件命中
        assert not m.is_artifact("src/vendor/pkg.zip")  # 子目录同名不命中

    def test_glob_with_slash_matches_full_path(self):
        """含 / 的模式按完整相对路径匹配（可命中多层路径）。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["dist/*.zip"]))
        assert m.is_artifact("dist/release.zip")
        assert not m.is_artifact("deep/nested/dist/release.zip")

    def test_configured_prefix_keeps_default_set(self):
        """配置前缀不丢失默认集合（实例前缀 + 默认前缀并存）。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["dist/"]))
        assert m.is_artifact("core/dashboard/static/v3/dist/assets/a.js")

    def test_normalize_drops_non_trailing_slash_prefix(self):
        """不含 * 且未以 / 结尾的项被丢弃并回退默认。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["dist"]))
        assert not m.is_artifact("dists/a.js")
        assert not m.is_artifact("dist/a.js")

    def test_normalize_drops_absolute_and_dotdot(self):
        """绝对路径与含 .. 的项被丢弃。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["/abs/dist/", "../other/dist/"]))
        assert not m.is_artifact("/abs/dist/x.js")
        assert not m.is_artifact("../other/dist/x.js")

    def test_normalize_drops_non_string_items(self):
        """非字符串项被丢弃。"""
        result = normalize_artifact_patterns([123, None, ["dist/"]])
        assert result == []

    def test_invalid_shape_falls_back_to_default(self):
        """配置形态非法（字符串 / [123, None]）不抛异常且回退默认。"""
        m1 = ArtifactPathMatcher(normalize_artifact_patterns("dist/"))
        assert not m1.is_artifact("dist/index.html")  # 字符串 → 回退默认
        m2 = ArtifactPathMatcher(normalize_artifact_patterns([123, None]))
        assert not m2.is_artifact("dist/index.html")

    def test_empty_list_equals_default(self):
        """空列表等价默认集合。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns([]))
        assert m.is_artifact("core/dashboard/static/dist/x.js")
        assert not m.is_artifact("dist/index.html")

    def test_paths_in_and_non_artifacts_in(self):
        """paths_in / non_artifacts_in 过滤。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["dist/", "*.zip"]))
        paths = ["dist/index.html", "fenix-newtab-v1.0.0.zip", "src/main.py"]
        assert m.paths_in(paths) == ["dist/index.html", "fenix-newtab-v1.0.0.zip"]
        assert m.non_artifacts_in(paths) == ["src/main.py"]

    def test_package_level_alias_default_semantics(self):
        """包级 _is_build_artifact_path 保持默认语义（与配置无关）。"""
        assert _is_build_artifact_path("core/dashboard/static/dist/x.js")
        assert not _is_build_artifact_path("dist/index.html")
        assert not _is_build_artifact_path("src/main.py")


# ── 2. WIP 重叠闸门（D3b） ──────────────────────────────────────────────────

class TestWipOverlapGateArtifactScope:
    """WIP 重叠集合排除配置产物 + D3b stash 前置对齐。"""

    def _seed_dist_and_src(self, root: Path, dist_content="DIST-BASE\n",
                           src_content="SRC-BASE\n"):
        (root / "dist").mkdir()
        (root / "dist" / "index.html").write_text(dist_content, encoding="utf-8")
        (root / "fenix-newtab-v1.0.0.zip").write_text("zip-base\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text(src_content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add dist + src")
        return git(root, "rev-parse", "HEAD").stdout.strip()

    def _branch_edits_paths(self, root: Path, branch: str, edits: dict, base_sha: str):
        git(root, "checkout", "-q", "-b", branch)
        for path, content in edits.items():
            (root / path).write_text(content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"[fenix] branch {branch} edits")
        git(root, "checkout", "-q", base_sha)

    def test_detect_wip_overlap_keeps_read_only_semantics(self, tmp_path):
        """主树脏 dist/index.html + 分支同改：_detect_wip_overlap 仍返回该路径
        （只读口径不变——产物排除在调用方 _wip_overlap_gate 切分）。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = self._seed_dist_and_src(root)
        self._branch_edits_paths(root, "fenix/impl", {"dist/index.html": "DIST-BRANCH\n"}, base_sha)
        (root / "dist" / "index.html").write_text("DIST-WIP\n", encoding="utf-8")

        wm = make_wm(root, build_artifact_paths=["dist/"])
        assert wm._detect_wip_overlap("fenix/impl") == ["dist/index.html"], \
            "只读口径不变：产物路径仍在 _detect_wip_overlap 返回集中"

    def test_gate_excludes_artifact_and_aligns_head(self, tmp_path):
        """纯产物重叠（已配置）→ _wip_overlap_gate 返回空、产物被 checkout HEAD 对齐、
        无 stash 产生。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = self._seed_dist_and_src(root)
        self._branch_edits_paths(
            root, "fenix/impl",
            {"dist/index.html": "DIST-BRANCH\n", "fenix-newtab-v1.0.0.zip": "zip-branch\n"},
            base_sha,
        )
        (root / "dist" / "index.html").write_text("DIST-WIP\n", encoding="utf-8")
        (root / "fenix-newtab-v1.0.0.zip").write_text("zip-wip\n", encoding="utf-8")

        with patch(
            "core.worktree_manager.mergeback.subprocess.run",
            wraps=subprocess.run,
        ) as mock_run:
            wm = make_wm(
                root,
                build_artifact_paths=["dist/", "fenix-newtab-*.zip"],
            )
            blocked, overlap = wm._wip_overlap_gate("fenix/impl")
            assert blocked is None
            assert overlap == [], f"纯产物重叠应被排除: {overlap}"
            # checkout HEAD -- 对齐调用以产物路径为参数
            checkout_calls = [
                c.args[0]
                for c in mock_run.call_args_list
                if isinstance(c.args[0], list) and c.args[0][:3] == ["git", "-C", root.__str__()] and
                c.args[0][3:5] == ["checkout", "HEAD"]
            ]
            assert len(checkout_calls) == 2, f"两个产物应各对齐一次: {checkout_calls}"
            flat = [item for call in checkout_calls for item in call]
            assert "dist/index.html" in flat and "fenix-newtab-v1.0.0.zip" in flat

    def test_semantic_overlap_still_gated(self, tmp_path):
        """语义文件（src/...）重叠仍计入闸门（产物配置不影响语义路径）。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = self._seed_dist_and_src(root)
        self._branch_edits_paths(
            root, "fenix/impl",
            {"src/main.py": "SRC-BRANCH\n", "dist/index.html": "DIST-BRANCH\n"},
            base_sha,
        )
        (root / "src" / "main.py").write_text("SRC-WIP\n", encoding="utf-8")
        (root / "dist" / "index.html").write_text("DIST-WIP\n", encoding="utf-8")

        wm = make_wm(root, build_artifact_paths=["dist/"])
        blocked, overlap = wm._wip_overlap_gate("fenix/impl")
        assert blocked is None  # 默认 auto 策略
        assert overlap == ["src/main.py"], f"语义重叠仍计入: {overlap}"

    def test_spec_changes_exclusion_unaffected_by_artifact_config(self, tmp_path):
        """spec/changes/** 排除不受产物配置影响（未声明时仍被排除）。"""
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
        (root / spec_task).write_text("- [x] 1.1 dirty-wip\n", encoding="utf-8")

        wm = make_wm(root, build_artifact_paths=["dist/"])
        assert wm._detect_wip_overlap("fenix/impl") == [], \
            "spec/changes/** 排除不受产物配置影响"


# ── 3. 预演闸分类 ───────────────────────────────────────────────────────────

class TestRehearsalArtifactClassification:
    """merge 预演闸：冲突全为配置产物放行，含语义路径返回 rehearsed=True。

    预演基于 ``git merge-tree --write-tree HEAD branch``——只有 HEAD 与 branch
    均改动同一文件（自 merge-base 起双方各改）才会产生冲突。故夹具先让 HEAD
    侧改一版，再派生分支改另一版，制造真实 modify/modify 冲突。
    """

    def _seed_dist_and_src(self, root: Path):
        (root / "dist").mkdir()
        (root / "dist" / "index.html").write_text("DIST-BASE\n", encoding="utf-8")
        (root / "fenix-newtab-v1.0.0.zip").write_text("zip-base\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("SRC-BASE\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add dist + src")
        return git(root, "rev-parse", "HEAD").stdout.strip()

    def _head_edits_then_branch_diverges(
        self, root: Path, branch: str, head_edits: dict, branch_edits: dict
    ):
        """HEAD 与 branch 自 merge-base 双方各改同一文件 → merge-tree 报冲突。

        顺序：先派生 branch 提交 branch_edits，checkout 回 base 后 HEAD 侧再提交
        head_edits——两者自 base 分叉（branch 非 HEAD 后代，否则 merge-tree 视为
        快进而零冲突）。
        """
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", branch)
        for path, content in branch_edits.items():
            (root / path).write_text(content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"[fenix] branch {branch} edits")
        git(root, "checkout", "-q", base_sha)
        for path, content in head_edits.items():
            (root / path).write_text(content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] HEAD edits")
        return base_sha

    def test_all_artifact_conflicts_pass(self, tmp_path):
        """冲突全为配置产物 → _rehearse_merge_from_branch 返回 None（放行真合并）。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_dist_and_src(root)
        self._head_edits_then_branch_diverges(
            root, "fenix/impl",
            head_edits={"dist/index.html": "DIST-HEAD\n",
                        "fenix-newtab-v1.0.0.zip": "zip-head\n"},
            branch_edits={"dist/index.html": "DIST-BRANCH\n",
                          "fenix-newtab-v1.0.0.zip": "zip-branch\n"},
        )

        wm = make_wm(root, build_artifact_paths=["dist/", "fenix-newtab-*.zip"])
        with patch(
            "core.worktree_manager.mergeback.G4MergebackMixin._merge_tree_supported",
            return_value=True,
        ):
            result = wm._rehearse_merge_from_branch("fenix/impl")
            assert result is None, f"全产物冲突应放行: {result}"

    def test_semantic_conflict_still_rehearsed(self, tmp_path):
        """含语义路径 → 返回 rehearsed=True 且 conflict_paths 不含产物路径。"""
        root = tmp_path / "repo"
        init_repo(root)
        self._seed_dist_and_src(root)
        self._head_edits_then_branch_diverges(
            root, "fenix/impl",
            head_edits={"src/main.py": "SRC-HEAD\n", "dist/index.html": "DIST-HEAD\n"},
            branch_edits={"src/main.py": "SRC-BRANCH\n", "dist/index.html": "DIST-BRANCH\n"},
        )

        wm = make_wm(root, build_artifact_paths=["dist/"])
        with patch(
            "core.worktree_manager.mergeback.G4MergebackMixin._merge_tree_supported",
            return_value=True,
        ):
            result = wm._rehearse_merge_from_branch("fenix/impl")
            assert result is not None
            assert result.rehearsed is True
            assert result.has_semantic_conflict is True
            assert "dist/index.html" not in result.conflict_paths, \
                f"conflict_paths 不应含产物路径: {result.conflict_paths}"
            assert "src/main.py" in result.conflict_paths

    def test_package_alias_default_semantics(self):
        """包级 _is_build_artifact_path('dist/index.html') 仍为 False（默认语义与配置无关）。"""
        assert not _is_build_artifact_path("dist/index.html")


# ── 4. 链路切断（D3b 核心验收） ──────────────────────────────────────────────

class TestD3bChainBreak:
    """D3b：产物重叠在 stash 之前对齐 HEAD，切断「产物→stash→pop 冲突→误报告警」链路。"""

    def _seed(self, root: Path):
        (root / "dist").mkdir()
        (root / "dist" / "index.html").write_text("DIST-BASE\n", encoding="utf-8")
        (root / "fenix-newtab-v1.0.0.zip").write_text("zip-base\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("SRC-BASE\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add files")
        return git(root, "rev-parse", "HEAD").stdout.strip()

    def _branch_edits(self, root: Path, branch: str, edits: dict, base_sha: str):
        git(root, "checkout", "-q", "-b", branch)
        for path, content in edits.items():
            (root / path).write_text(content, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"[fenix] branch {branch}")
        git(root, "checkout", "-q", base_sha)

    def test_pure_artifact_overlap_no_stash_no_pop_conflict(self, tmp_path):
        """纯产物重叠（分支同改，已配置）→ 对齐 HEAD、wip_overlap 空、
        走完整 merge-back 后 last_stash_pop_conflicts 为空。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = self._seed(root)
        self._branch_edits(
            root, "fenix/impl",
            {"dist/index.html": "DIST-BRANCH\n", "fenix-newtab-v1.0.0.zip": "zip-branch\n"},
            base_sha,
        )
        (root / "dist" / "index.html").write_text("DIST-WIP\n", encoding="utf-8")
        (root / "fenix-newtab-v1.0.0.zip").write_text("zip-wip\n", encoding="utf-8")

        wm = make_wm(
            root,
            build_artifact_paths=["dist/", "fenix-newtab-*.zip"],
        )
        info = wm.merge_back_from_branch("fenix/impl")
        success, err = info
        assert success, f"纯产物重叠不应阻塞 merge-back: {err}"
        assert info.wip_overlap == [], f"wip_overlap 应为空: {info.wip_overlap}"
        assert wm.last_stash_pop_conflicts == [], \
            f"无产物进 stash → pop 无冲突: {wm.last_stash_pop_conflicts}"
        # 主树干净（产物被对齐到 HEAD，无残留 WIP）
        st = git(root, "status", "--porcelain")
        assert not st.stdout.strip(), f"主树应干净: {st.stdout!r}"

    def test_main_tree_owned_artifact_not_aligned(self, tmp_path):
        """主树独有产物（分支未改）→ 对齐未被调用、该路径仍走 stash/pop 往返。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = self._seed(root)
        self._branch_edits(root, "fenix/impl", {"src/main.py": "SRC-BRANCH\n"}, base_sha)
        (root / "dist" / "index.html").write_text("DIST-WIP\n", encoding="utf-8")

        with patch(
            "core.worktree_manager.mergeback.subprocess.run",
            wraps=subprocess.run,
        ) as mock_run:
            wm = make_wm(root, build_artifact_paths=["dist/"])
            info = wm.merge_back_from_branch("fenix/impl")
            success, err = info
            assert success, f"merge 应成功: {err}"
            # 对齐命令未被调用（主树独有产物不应对齐 HEAD）
            checkout_calls = [
                c.args[0]
                for c in mock_run.call_args_list
                if isinstance(c.args[0], list) and c.args[0][:3] == ["git", "-C", root.__str__()] and
                c.args[0][3:5] == ["checkout", "HEAD"] and "dist/index.html" in c.args[0]
            ]
            assert checkout_calls == [], \
                f"主树独有产物不应被对齐 HEAD: {checkout_calls}"
            # 该路径经 stash 往返后回到主树（仍是未提交 WIP）
            assert (root / "dist" / "index.html").read_text(encoding="utf-8") == "DIST-WIP\n", \
                "主树独有产物应经 stash/pop 返回主树"

    def test_alignment_failure_falls_back_to_semantic(self, tmp_path):
        """对齐失败（git checkout HEAD 返回非 0）→ 路径并入 wip_overlap、merge-back 不阻塞。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = self._seed(root)
        self._branch_edits(
            root, "fenix/impl",
            {"dist/index.html": "DIST-BRANCH\n"}, base_sha,
        )
        (root / "dist" / "index.html").write_text("DIST-WIP\n", encoding="utf-8")

        class _FailedCheckout:
            """模拟 git checkout HEAD 对齐失败（其余 git 命令走真实执行）。"""

            def __init__(self, *a, **k):
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""
                if len(a) >= 1 and isinstance(a[0], list) and a[0][:5] == ["git", "-C", str(root), "checkout", "HEAD"]:
                    self.returncode = 1
                    self.stderr = "fatal: pathspec 'dist/index.html' did not match"

        real_run = subprocess.run
        with patch(
            "core.worktree_manager.mergeback.subprocess.run",
            side_effect=lambda *a, **k: _FailedCheckout(*a, **k) if (
                len(a) >= 1 and isinstance(a[0], list) and a[0][:5] == ["git", "-C", str(root), "checkout", "HEAD"]
            ) else real_run(*a, **k),
        ):
            wm = make_wm(root, build_artifact_paths=["dist/"])
            blocked, overlap = wm._wip_overlap_gate("fenix/impl")
            assert blocked is None, "对齐失败 MUST NOT 阻塞 merge-back"
            assert "dist/index.html" in overlap, \
                f"对齐失败路径应回落并入 wip_overlap: {overlap}"

    def test_semantic_overlap_not_aligned(self, tmp_path):
        """语义文件重叠 → 对齐未接收该路径、闸门按 policy 照常处置。"""
        root = tmp_path / "repo"
        init_repo(root)
        base_sha = self._seed(root)
        self._branch_edits(root, "fenix/impl", {"src/main.py": "SRC-BRANCH\n"}, base_sha)
        (root / "src" / "main.py").write_text("SRC-WIP\n", encoding="utf-8")

        with patch(
            "core.worktree_manager.mergeback.subprocess.run",
            wraps=subprocess.run,
        ) as mock_run:
            wm = make_wm(root, build_artifact_paths=["dist/"], mergeback_wip_overlap_policy="block")
            blocked, overlap = wm._wip_overlap_gate("fenix/impl")
            assert blocked is not None and blocked.wip_gate_blocked is True, \
                f"block 策略下语义重叠应阻塞: {blocked}"
            assert "src/main.py" in overlap
            checkout_calls = [
                c.args[0]
                for c in mock_run.call_args_list
                if isinstance(c.args[0], list) and c.args[0][:3] == ["git", "-C", root.__str__()] and
                c.args[0][3:5] == ["checkout", "HEAD"]
            ]
            assert checkout_calls == [], "语义路径不应被对齐"


# ── 5. 故障回退与兼容性 ──────────────────────────────────────────────────────

class TestFailSafeAndCompatibility:
    """判定器故障回退 + 与既有行为逐字节兼容。"""

    def test_invalid_build_artifact_paths_construct_without_error(self, tmp_path):
        """build_artifact_paths 非法形态构造不抛异常、行为等价默认。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / "core" / "dashboard" / "static" / "dist").mkdir(parents=True)
        (root / "core" / "dashboard" / "static" / "dist" / "x.js").write_text("x\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add dist artifact")

        wm_bad = make_wm(root, build_artifact_paths="not a list")
        assert wm_bad._artifacts.is_artifact("core/dashboard/static/dist/x.js"), \
            "非法配置应回退默认集合（dashboard 产物仍命中）"
        assert not wm_bad._artifacts.is_artifact("dist/x.js"), \
            "非法配置回退默认（根级 dist 不命中）"

        wm_mixed = make_wm(root, build_artifact_paths=[123, None])
        assert wm_mixed._artifacts.is_artifact("core/dashboard/static/dist/x.js")

    def test_no_build_artifact_paths_byte_compatible(self, tmp_path):
        """不传 build_artifact_paths 时行为与现行逐字节一致。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        paths = [
            "core/dashboard/static/v3/dist/assets/a.js",
            "core/dashboard/static/dist",
            "dist/index.html",
            "src/main.py",
        ]
        for p in paths:
            assert wm._artifacts.is_artifact(p) == _is_build_artifact_path(p), \
                f"实例判定器与包级默认语义不一致: {p}"
