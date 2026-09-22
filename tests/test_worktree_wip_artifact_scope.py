"""tests/test_worktree_wip_artifact_scope.py — 产物路径判定器与 WIP 重叠闸门测试。

fix-artifact-paths-hardcoded-default D1/D2 测试策略：
  1. 判定矩阵：无配置时判定恒假（未裁决）/ 配置 dist/ 后为真 /
     fenix-newtab-*.zip 命中发布包 / *.zip MUST NOT 命中 src/vendor/pkg.zip /
     未以 / 结尾项被丢弃 / 绝对路径与 .. 项被丢弃 / 配置形态非法回退空集合 /
     空列表回退空集合 / has_build_artifacts=False 短路恒假 /
     is_artifact_config_unresolved 三态表
  2. WIP 重叠闸门：产物脏改动不计入重叠集合（只读口径不变），语义重叠仍计入，
     spec/changes/** 排除不受产物配置影响
  3. 预演闸分类：冲突全为配置产物放行，含语义路径返回 rehearsed=True 且
     conflict_paths 不含产物路径
  4. 链路切断（D3b 核心验收）：纯产物重叠 → checkout HEAD 对齐被调用、
     wip_overlap 为空、last_stash_pop_conflicts 为空；主树独有产物 → 对齐未
     被调用、仍走 stash/pop 往返；对齐失败 → 路径并入 wip_overlap 且不阻塞；
     语义重叠 → 对齐不接收该路径、闸门按 policy 照常处置
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from core.worktree_manager import WorktreeManager
from core.worktree_manager.artifact_paths import (
    ArtifactPathMatcher,
    is_artifact_config_unresolved,
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
    """判定矩阵：无配置默认恒假 / 配置前缀 / 通配 / 非法项丢弃 / 三态短路。"""

    def test_unconfigured_matcher_judges_all_false(self):
        """无配置（未裁决）时判定恒假——无任何内置默认路径。"""
        m = ArtifactPathMatcher()
        assert not m.is_artifact("core/dashboard/static/v3/dist/assets/a.js")
        assert not m.is_artifact("core/dashboard/static/dist/assets/a.js")
        assert not m.is_artifact("dist/index.html")
        assert not m.is_artifact("src/main.py")

    def test_root_dist_false_by_default(self):
        """无配置时根级 dist/x.js 判定为假。"""
        m = ArtifactPathMatcher()
        assert not m.is_artifact("dist/index.html")
        assert not m.is_artifact("dist/assets/a.js")

    def test_dist_as_last_segment_false(self):
        """无配置时 dist 为末段（非目录层级）判定为假。"""
        m = ArtifactPathMatcher()
        assert not m.is_artifact("core/dashboard/static/dist")

    def test_configured_prefix_hits_root_dist(self):
        """配置 'dist/' 后根级 dist/ 判定为真（has_build_artifacts=None + 非空路径 → 按配置）。"""
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

    def test_configured_prefix_does_not_introduce_default_set(self):
        """配置前缀不引入默认集合：core/dashboard/static 不再默认判真。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["dist/"]))
        assert not m.is_artifact("core/dashboard/static/v3/dist/assets/a.js"), \
            "仅配置 dist/ 不应引入旧默认集合"

    def test_normalize_drops_non_trailing_slash_prefix(self):
        """不含 * 且未以 / 结尾的项被丢弃并回退空集合（判定恒假）。"""
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

    def test_invalid_shape_falls_back_to_empty(self):
        """配置形态非法（字符串 / [123, None]）不抛异常且回退空集合（判定恒假）。"""
        m1 = ArtifactPathMatcher(normalize_artifact_patterns("dist/"))
        assert not m1.is_artifact("dist/index.html")
        m2 = ArtifactPathMatcher(normalize_artifact_patterns([123, None]))
        assert not m2.is_artifact("dist/index.html")

    def test_empty_list_judges_all_false(self):
        """空列表回退空集合（判定恒假）。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns([]))
        assert not m.is_artifact("core/dashboard/static/dist/x.js")
        assert not m.is_artifact("dist/index.html")

    def test_has_build_artifacts_false_short_circuits(self):
        """has_build_artifacts=False 时判定短路恒假（忽略 patterns）。"""
        m = ArtifactPathMatcher(
            normalize_artifact_patterns(["dist/", "*.zip"]),
            has_build_artifacts=False,
        )
        assert not m.is_artifact("dist/index.html")
        assert not m.is_artifact("release.zip")
        assert m.paths_in(["dist/index.html", "release.zip", "src/main.py"]) == []
        assert m.non_artifacts_in(["dist/index.html", "src/main.py"]) == ["dist/index.html", "src/main.py"]

    def test_paths_in_and_non_artifacts_in(self):
        """paths_in / non_artifacts_in 过滤。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns(["dist/", "*.zip"]))
        paths = ["dist/index.html", "fenix-newtab-v1.0.0.zip", "src/main.py"]
        assert m.paths_in(paths) == ["dist/index.html", "fenix-newtab-v1.0.0.zip"]
        assert m.non_artifacts_in(paths) == ["src/main.py"]


# ── 1b. is_artifact_config_unresolved 三态表 ─────────────────────────────────

class TestIsArtifactConfigUnresolved:
    """is_artifact_config_unresolved 三态判定表（fix-artifact-paths-hardcoded-default D2）。"""

    def test_defaults_none_with_empty_patterns(self):
        """缺省 + 空路径 → 未裁决。"""
        assert is_artifact_config_unresolved(None, []) is True

    def test_defaults_none_with_nonempty_patterns(self):
        """缺省 + 非空路径 → 已裁决（按配置）。"""
        assert is_artifact_config_unresolved(None, [("prefix", "dist/")]) is False

    def test_false_with_any_patterns(self):
        """has=False → 已裁决（无产物，无论路径）。"""
        assert is_artifact_config_unresolved(False, []) is False
        assert is_artifact_config_unresolved(False, [("prefix", "dist/")]) is False

    def test_true_with_nonempty_patterns(self):
        """has=True + 非空路径 → 已裁决。"""
        assert is_artifact_config_unresolved(True, [("prefix", "dist/")]) is False

    def test_true_with_empty_patterns(self):
        """has=True + 空路径 → 未裁决（标志与路径不一致）。"""
        assert is_artifact_config_unresolved(True, []) is True

    def test_non_boolean_fallback_to_missing(self):
        """非法布尔值（字符串、数字）→ 按缺省处理。"""
        assert is_artifact_config_unresolved("yes", []) is True
        assert is_artifact_config_unresolved(1, [("prefix", "dist/")]) is False


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

        wm = make_wm(root, build_artifact_paths=["dist/"], has_build_artifacts=True)
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
                has_build_artifacts=True,
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

        wm = make_wm(root, mergeback_wip_overlap_policy="auto", build_artifact_paths=["dist/"], has_build_artifacts=True)
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

        wm = make_wm(root, build_artifact_paths=["dist/"], has_build_artifacts=True)
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

        wm = make_wm(root, build_artifact_paths=["dist/", "fenix-newtab-*.zip"],
                      has_build_artifacts=True)
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

        wm = make_wm(root, build_artifact_paths=["dist/"], has_build_artifacts=True)
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
            has_build_artifacts=True,
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
            wm = make_wm(root, build_artifact_paths=["dist/"], has_build_artifacts=True)
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
            wm = make_wm(root, mergeback_wip_overlap_policy="auto", build_artifact_paths=["dist/"], has_build_artifacts=True)
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
            wm = make_wm(root, build_artifact_paths=["dist/"],
                          has_build_artifacts=True, mergeback_wip_overlap_policy="block")
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
    """判定器故障回退 + 配置驱动语义兼容。"""

    def test_invalid_build_artifact_paths_construct_without_error(self, tmp_path):
        """build_artifact_paths 非法形态构造不抛异常、判定恒假（回退空集合）。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / "core" / "dashboard" / "static" / "dist").mkdir(parents=True)
        (root / "core" / "dashboard" / "static" / "dist" / "x.js").write_text("x\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add dist artifact")

        wm_bad = make_wm(root, build_artifact_paths="not a list")
        assert not wm_bad._artifacts.is_artifact("core/dashboard/static/dist/x.js"), \
            "非法配置回退空集合（不再命中默认集合）"
        assert not wm_bad._artifacts.is_artifact("dist/x.js"), \
            "非法配置回退空集合（根级 dist 不命中）"

        wm_mixed = make_wm(root, build_artifact_paths=[123, None])
        assert not wm_mixed._artifacts.is_artifact("core/dashboard/static/dist/x.js")

    def test_no_build_artifact_paths_judges_all_false(self, tmp_path):
        """不传 build_artifact_paths 时判定恒假（未裁决，无任何内置默认路径）。"""
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
            assert not wm._artifacts.is_artifact(p), \
                f"未配置时判定恒假: {p}"
        assert is_artifact_config_unresolved(
            None, normalize_artifact_patterns(None)
        ), "未配置时 is_artifact_config_unresolved 应返回 True"

    def test_has_false_skips_path_matching(self, tmp_path):
        """has_build_artifacts=False 时判定短路恒假（忽略 patterns）。"""
        wm = make_wm(
            tmp_path,
            build_artifact_paths=["dist/"],
            has_build_artifacts=False,
        )
        assert not wm._artifacts.is_artifact("dist/index.html")
        assert is_artifact_config_unresolved(False, normalize_artifact_patterns(["dist/"])) is False
