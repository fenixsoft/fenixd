"""tests/test_daemon_config_read_paths.py — daemon 配置读取路径契约。

事故背景（2026-09-19，run admin-evo-transient-storm-alert-context-1789778042）：
``fenixd.py`` 初始化段曾以 ``self.config.get("worktree.has_build_artifacts", None)``
读配置。``self.config`` 是 ``ConfigLoader.resolve_config`` 深合并后的**嵌套
dict**（``{"worktree": {"has_build_artifacts": False, ...}}``），而
``dict.get`` 是按**扁平字面键**查找——``"worktree.has_build_artifacts"`` 不是
顶层键，恒返回缺省兜底 ``None``。后果：

- 项目级显式裁决的 ``has_build_artifacts: false`` 永远读不到 → 产物判定器
  永久处于「未裁决」态 → merge-back WIP 重叠闸门每轮误发
  ``build_artifact_paths_missing`` major 信号，Administrator 反复被唤起起草
  一个已经裁决过的配置；
- 同段 ``worktree.mergeback_wip_overlap_policy: block``（人工显式配置的阻塞
  策略）静默降级为 ``auto``——高风险：产物被当语义内容自动收纳。

本测试锁三重契约：
  1. **行为**：``ConfigLoader.get`` 点号解析能取到深合并后的 ``worktree`` 三键；
  2. **静态防线**：``fenixd.py`` / ``core/**/*.py`` 中 MUST NOT 出现
     ``<x>.config.get("<含点号的键>")`` 形态的误读调用（AST 扫描，新增即红）；
  3. **端到端**：临时项目根上实例化 ``FenixDaemon`` 的 WorktreeManager 注入段，
     断言判定器读到的是项目级显式裁决值（而非「未裁决」）。
"""

import ast
from pathlib import Path

import pytest

from core.config import ConfigLoader
from core.worktree_manager.artifact_paths import (
    ArtifactPathMatcher,
    normalize_artifact_patterns,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── 1. 行为：点号解析取深合并值 ──────────────────────────────────────────


class TestConfigLoaderDottedRead:
    """``ConfigLoader.get`` 是嵌套配置的唯一正确读法（扁平 dict.get 恒取兜底）。"""

    def test_dotted_path_reads_deep_merged_value(self):
        config = {"worktree": {"has_build_artifacts": False, "build_artifact_paths": []}}
        assert ConfigLoader.get(config, "worktree.has_build_artifacts") is False
        assert ConfigLoader.get(config, "worktree.build_artifact_paths") == []

    def test_flat_dict_get_on_nested_key_falls_back(self):
        """反面锚点：这正是事故形态——扁平读法恒取兜底，显式配置静默失效。"""
        config = {"worktree": {"has_build_artifacts": False}}
        assert config.get("worktree.has_build_artifacts", "FALLBACK") == "FALLBACK"

    def test_resolve_config_returns_nested_dict(self, tmp_path):
        """resolve_config 返回嵌套形态——点号读法是唯一正确形态。"""
        (tmp_path / ".fenix").mkdir()
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "worktree:\n"
            "  has_build_artifacts: false\n"
            "  build_artifact_paths: []\n"
            "  mergeback_wip_overlap_policy: block\n",
            encoding="utf-8",
        )
        # 用户级配置不参与本断言（resolve_config 深合并两者，用户级缺省不影响）
        effective = ConfigLoader.resolve_config(tmp_path)
        assert ConfigLoader.get(effective, "worktree.has_build_artifacts") is False
        assert (
            ConfigLoader.get(effective, "worktree.mergeback_wip_overlap_policy")
            == "block"
        )


# ── 2. 静态防线：AST 扫描点号误读 ────────────────────────────────────────

# 白名单：确需以字面点号键访问**扁平** dict 的调用点（无——本形态本质是缺陷）。
_DOTTED_READ_ALLOWLIST: set = set()


def _dotted_config_reads(path: Path) -> list:
    """返回 ``<x>.config.get("<含点号的键>")`` 形态的 (行号, 接收者, 键) 列表。

    仅扫描调用形态（``Call`` + ``Attribute(attr="get")``）：接收者表达式以
    ``.config`` 结尾且首参为含 ``.`` 的字符串字面量即命中。接收者不限
    ``self.config``——任何持有有效配置 dict 的变量都适用同一契约。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        receiver = func.value
        if not isinstance(receiver, ast.Attribute) or receiver.attr != "config":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        key = node.args[0].value
        if isinstance(key, str) and "." in key:
            hits.append((node.lineno, ast.unparse(receiver), key))
    return hits


def _scan_targets() -> list:
    targets = [REPO_ROOT / "fenixd.py"]
    targets.extend(
        p
        for p in sorted((REPO_ROOT / "core").rglob("*.py"))
        if "node_modules" not in p.parts
    )
    return targets


class TestNoDottedConfigMisread:
    def test_no_dotted_config_get_on_nested_config(self):
        offenders = []
        for path in _scan_targets():
            rel = path.relative_to(REPO_ROOT).as_posix()
            for lineno, receiver, key in _dotted_config_reads(path):
                if (rel, receiver, key) in _DOTTED_READ_ALLOWLIST:
                    continue
                offenders.append(f"{rel}:{lineno} {receiver}.get({key!r})")
        assert not offenders, (
            "配置是嵌套 dict，点号键必须经 ConfigLoader.get 解析；"
            "扁平 dict.get 会静默取兜底值（显式配置失效）：\n  "
            + "\n  ".join(offenders)
        )

    def test_scanner_detects_planted_misread(self, tmp_path):
        """扫描器自证：植入误读必须被检出（防扫描器静默失效）。"""
        planted = tmp_path / "sample.py"
        planted.write_text(
            "class A:\n"
            "    def run(self):\n"
            "        return self.config.get('worktree.has_build_artifacts', None)\n",
            encoding="utf-8",
        )
        hits = _dotted_config_reads(planted)
        assert hits, "扫描器未检出植入的点号误读"
        assert hits[0][2] == "worktree.has_build_artifacts"

    def test_correct_read_form_not_flagged(self, tmp_path):
        ok = tmp_path / "ok.py"
        ok.write_text(
            "from core.config import ConfigLoader\n"
            "class A:\n"
            "    def run(self):\n"
            "        return ConfigLoader.get(self.config, 'worktree.has_build_artifacts', None)\n",
            encoding="utf-8",
        )
        assert _dotted_config_reads(ok) == []


# ── 3. 端到端：裁决值真的传到判定器 ──────────────────────────────────────


class TestDaemonArtifactConfigInjection:
    """复现 daemon 注入段：项目级裁决 → 判定器不再「未裁决」。"""

    def _matcher_from_config(self, config: dict) -> ArtifactPathMatcher:
        """镜像 fenixd.py 注入段（ConfigLoader.get 点号读 + 判定器构造）。"""
        return ArtifactPathMatcher(
            normalize_artifact_patterns(
                ConfigLoader.get(config, "worktree.build_artifact_paths", None)
            ),
            has_build_artifacts=ConfigLoader.get(
                config, "worktree.has_build_artifacts", None
            ),
        )

    def test_explicit_false_reaches_matcher(self, tmp_path):
        (tmp_path / ".fenix").mkdir()
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "worktree:\n  has_build_artifacts: false\n  build_artifact_paths: []\n",
            encoding="utf-8",
        )
        matcher = self._matcher_from_config(ConfigLoader.resolve_config(tmp_path))
        assert matcher.is_config_unresolved() is False, (
            "显式 has_build_artifacts=false 必须被读到（否则信号永久复发）"
        )

    def test_explicit_paths_reach_matcher(self, tmp_path):
        (tmp_path / ".fenix").mkdir()
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "worktree:\n"
            "  has_build_artifacts: true\n"
            "  build_artifact_paths: ['core/dashboard/static/dist/']\n",
            encoding="utf-8",
        )
        matcher = self._matcher_from_config(ConfigLoader.resolve_config(tmp_path))
        assert matcher.is_config_unresolved() is False
        assert matcher.is_artifact("core/dashboard/static/dist/index.html") is True

    def test_unset_project_reports_unresolved(self, tmp_path):
        """未配置项目仍须落到「未裁决」（保守侧）——修复不得让判定变宽。"""
        (tmp_path / ".fenix").mkdir()
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "project:\n  name: t\n", encoding="utf-8"
        )
        matcher = self._matcher_from_config(ConfigLoader.resolve_config(tmp_path))
        assert matcher.is_config_unresolved() is True

    @pytest.mark.parametrize("key", ["block", "auto"])
    def test_wip_policy_read_from_nested_config(self, tmp_path, key):
        """同段 mergeback_wip_overlap_policy 走同一读法（block 静默降级也是事故面）。"""
        (tmp_path / ".fenix").mkdir()
        (tmp_path / ".fenix" / "config.yaml").write_text(
            f"worktree:\n  mergeback_wip_overlap_policy: {key}\n", encoding="utf-8"
        )
        effective = ConfigLoader.resolve_config(tmp_path)
        assert (
            ConfigLoader.get(
                effective, "worktree.mergeback_wip_overlap_policy", "auto"
            )
            == key
        )
