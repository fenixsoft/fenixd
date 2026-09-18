"""tests/test_artifact_paths_declaration.py — 产物配置声明（三态判定表）测试。

fix-artifact-paths-hardcoded-default（artifact-path-declaration 能力）测试策略：
  1. 判定完全由配置驱动，无内置默认路径（被删除符号不存在断言）
  2. 三态判定表逐格透传（缺省/true 非空/true 空/false/缺省配非空）
  3. is_artifact_config_unresolved 与判定器一致性（is_artifact 恒假 ⇔ 未裁决）
  4. normalize 空集合回退（非法形态不抛、判定恒假、不因任何默认集合判真）
"""

import importlib
import sys

import pytest

from core.worktree_manager.artifact_paths import (
    ArtifactPathMatcher,
    is_artifact_config_unresolved,
    normalize_artifact_patterns,
)


def test_removed_default_symbols_no_longer_exist():
    """被删除的内置默认符号（常量/函数）MUST 不再存在于代码库与模块命名空间。"""
    removed = [
        "DEFAULT_ARTIFACT_PREFIXES",
        "_DEFAULT_STATIC_ROOT",
        "_matches_default",
        "_match_default",
    ]
    # 模块命名空间（含私有名）
    module = sys.modules.get("core.worktree_manager.artifact_paths")
    assert module is not None, "artifact_paths 应已被导入"
    for name in removed:
        assert not hasattr(module, name), f"内置默认符号 {name} 必须已删除"

    # 包级 _is_build_artifact_path 亦删除（facade 无残留）
    assert not hasattr(
        sys.modules.get("core.worktree_manager"), "_is_build_artifact_path"
    ), "包级 _is_build_artifact_path 必须已删除"

    # 源码全仓检索：任何定义/引用均不得残留（含 re-export 形态）
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    forbidden = ["_matches_default", "_DEFAULT_STATIC_ROOT", "DEFAULT_ARTIFACT_PREFIXES"]
    for root, _dirs, files in os.walk(repo_root):
        if "/.git" in root or "/node_modules" in root or "/.claude" in root:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            for sym in forbidden:
                assert sym not in content, (
                    f"被删除符号 '{sym}' 残留于 {os.path.relpath(path, repo_root)}"
                )


# ── 三态判定表逐格 ───────────────────────────────────────────────────────

class TestTriStateAdjudicationTable:
    """三态判定表：| has_build_artifacts | build_artifact_paths | 判定 | 未裁决 |。"""

    def test_missing_has_with_empty_paths_is_unresolved_and_all_false(self):
        """缺省 + 空路径 → 未裁决，is_artifact 恒假。"""
        m = ArtifactPathMatcher(normalize_artifact_patterns([]))
        assert is_artifact_config_unresolved(None, []) is True
        assert not m.is_artifact("core/dashboard/static/dist/a.js")
        assert not m.is_artifact("dist/index.html")

    def test_missing_has_with_nonempty_paths_judges_by_config(self):
        """缺省 + 非空路径 → 已裁决（按配置判定）。"""
        patterns = normalize_artifact_patterns(["dist/"])
        assert is_artifact_config_unresolved(None, patterns) is False
        m = ArtifactPathMatcher(patterns)
        assert m.is_artifact("dist/index.html") is True
        assert not m.is_artifact("src/app.tsx")

    def test_false_with_any_paths_resolved_no_artifacts(self):
        """false + 任意路径 → 已裁决（无产物），判定恒假。"""
        for paths in ([], [("prefix", "dist/")]):
            assert is_artifact_config_unresolved(False, paths) is False
        m = ArtifactPathMatcher(
            normalize_artifact_patterns(["dist/", "*.zip"]), has_build_artifacts=False
        )
        assert not m.is_artifact("dist/index.html")
        assert not m.is_artifact("release.zip")
        assert not m.is_artifact("any/path/at/all.js")

    def test_true_with_nonempty_paths_resolved_by_config(self):
        """true + 非空路径 → 已裁决（按配置判定）。"""
        patterns = normalize_artifact_patterns(["dist/"])
        assert is_artifact_config_unresolved(True, patterns) is False
        m = ArtifactPathMatcher(patterns, has_build_artifacts=True)
        assert m.is_artifact("dist/index.html") is True
        assert not m.is_artifact("src/app.tsx")

    def test_true_with_empty_paths_unresolved(self):
        """true + 空路径 → 未裁决（标志与路径不一致）。"""
        assert is_artifact_config_unresolved(True, []) is True
        m = ArtifactPathMatcher(normalize_artifact_patterns([]), has_build_artifacts=True)
        assert not m.is_artifact("dist/index.html")

    def test_non_boolean_has_falls_back_to_missing(self):
        """非法布尔（字符串/数字）→ 按缺省处理，MUST NOT 让判定变宽。"""
        for bad in ("yes", 1, [], {}):
            assert is_artifact_config_unresolved(bad, []) is True
            assert is_artifact_config_unresolved(bad, [("prefix", "dist/")]) is False
        # 判定器同样按缺省处理：非空路径按配置（不因非法值短路或变宽）
        m = ArtifactPathMatcher(
            normalize_artifact_patterns(["dist/"]), has_build_artifacts="yes"
        )
        assert m.is_artifact("dist/index.html") is True
        assert not m.is_artifact("src/app.tsx")


# ── 已声明产物项目（spec Scenario） ───────────────────────────────────────

class TestDeclaredArtifactProject:
    """已声明带产物/无产物的项目按配置判定（spec 显式场景透传）。"""

    def test_declared_with_artifacts_judges_by_prefix(self):
        """has=true + build_artifact_paths=["dist/"] → dist/index.html 真、src/ 假。"""
        m = ArtifactPathMatcher(
            normalize_artifact_patterns(["dist/"]), has_build_artifacts=True
        )
        assert m.is_artifact("dist/index.html") is True
        assert not m.is_artifact("src/app.tsx")

    def test_declared_no_artifacts_never_true(self):
        """has=false → 任意路径均不判真。"""
        m = ArtifactPathMatcher(
            normalize_artifact_patterns(["dist/", "core/dashboard/static/dist/"]),
            has_build_artifacts=False,
        )
        for p in (
            "dist/index.html",
            "core/dashboard/static/dist/assets/a.js",
            "release-1.0.zip",
            "src/main.py",
        ):
            assert not m.is_artifact(p), f"has=false 时不应判真: {p}"

    def test_unconfigured_dashboard_artifact_no_longer_true(self):
        """未配置时 core/dashboard/static/v3/dist/assets 不再判真（wip-artifact-scope 场景）。"""
        m = ArtifactPathMatcher()
        assert not m.is_artifact("core/dashboard/static/v3/dist/assets/a.js")

    def test_configured_dashboard_prefix_judges_true(self):
        """配置 core/dashboard/static/ 前缀 + has=true → 该前缀下判定为真。"""
        m = ArtifactPathMatcher(
            normalize_artifact_patterns(["core/dashboard/static/"]),
            has_build_artifacts=True,
        )
        assert m.is_artifact("core/dashboard/static/dist/assets/a.js") is True


# ── normalize 空集合回退 ──────────────────────────────────────────────────

class TestNormalizeEmptyFallback:
    """normalize_artifact_patterns 回退空集合（不再回退默认集合）。"""

    def test_illegal_shape_returns_empty_and_never_default(self):
        """字符串 / [123, None] 等非法形态 → 空集合；判定恒假（不含默认集合）。"""
        for raw in ("dist/", "not a list", [123, None], {"dist/": 1}):
            patterns = normalize_artifact_patterns(raw)
            assert patterns == [], f"非法形态 {raw!r} 应回退空集合"
            m = ArtifactPathMatcher(patterns)
            assert not m.is_artifact("core/dashboard/static/dist/x.js"), \
                f"回退空集合不应命中默认路径: {raw!r}"
            assert not m.is_artifact("dist/index.html")

    def test_absolute_and_dotdot_dropped(self):
        """越界路径（绝对/含 ..）被丢弃 → 空集合，不因任何默认集合判真。"""
        patterns = normalize_artifact_patterns(["/abs/dist/", "../other/dist/"])
        assert patterns == []
        m = ArtifactPathMatcher(patterns)
        assert not m.is_artifact("/abs/dist/x.js")
        assert not m.is_artifact("../other/dist/x.js")

    def test_bad_has_does_not_widen_judgment(self):
        """配置形态非法（字符串）+ has=None → 判定器不抛、判定恒假。"""
        m1 = ArtifactPathMatcher(normalize_artifact_patterns("dist/"))
        assert not m1.is_artifact("dist/index.html")
        m2 = ArtifactPathMatcher(normalize_artifact_patterns([123, None]))
        assert not m2.is_artifact("dist/index.html")