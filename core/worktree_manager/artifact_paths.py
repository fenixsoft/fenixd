"""
artifact_paths — 构建产物路径判定器。

**迁移背景**（evo-merge-back-wip-artifact-scope →
fix-artifact-paths-hardcoded-default）：

判定语义从「全局常量 + 单条硬编码规则」改为「每个 WorktreeManager 实例持有的
可配置前缀 + 可配置通配」判定器。fix-artifact-paths-hardcoded-default 进一步
**删除全部内置默认集合**——判定完全由配置驱动（`worktree.has_build_artifacts`
× `worktree.build_artifact_paths`），无任何硬编码项目路径。原
`DEFAULT_ARTIFACT_PREFIXES` / `_DEFAULT_STATIC_ROOT` / `_matches_default()`
（static 根下任一层级含 dist 目录的默认规则）一并移除：未配置时判定恒假
（「未裁决」语义，见 `is_artifact_config_unresolved`），不再回退到某个内置路径。

**调用点清单**（语义不同的调用路径）：

1. `mergeback._rehearse_merge_from_branch`：merge 预演闸，`non_artifact` 非空即判
   语义冲突 → 直通 repair 通道；
2. `mergeback` merge 冲突分类（`self_heal_applicable` / `has_semantic_conflict`）：
   产物自愈不适用 → abort + 分类为语义；
3. `dist_conflicts._resolve_build_artifact_conflicts` / `_artifact_paths` /
   `_rebuild_dist_after_merge`：产物冲突对齐、stray 清账、ref 产物枚举与
   `src_touched` 判定；
4. `mergeback._wip_overlap_gate`：WIP 重叠子集中产物的 stash 前置对齐。

本模块只依赖标准库（`pathlib` / `fnmatch`），可被任何调用方安全导入。
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any, List, Optional, Sequence, Tuple

logger = logging.getLogger("fenixd.worktree_manager.artifact_paths")


# ── 配置规范化 ───────────────────────────────────────────────────────────

def normalize_artifact_patterns(raw: Any) -> List[Tuple[str, str]]:
    """把配置值规范化为 ``(kind, pattern)`` 列表，``kind ∈ {"prefix", "glob"}``。

    **丢弃规则**（逐项，记 WARNING）：

    - 非列表的值整体拒绝（空列表）；非字符串项丢弃；
    - 不含 ``*`` 且未以 ``/`` 结尾的项丢弃（前缀形态 MUST 以 ``/`` 结尾，
      避免 `dist` 前缀意外匹配 `dists/`、`distfoo/`）；
    - 绝对路径（以 ``/`` 开头）或含 ``..`` 段的项丢弃。

    任何异常捕获后返回空列表（fail-safe **回退空集合**：空集合 = 判定恒假，
    即未裁决的保守侧——判定器自身故障 MUST NOT 让判定变宽或失效）。
    """
    try:
        if raw is None:
            return []

        if not isinstance(raw, list):
            logger.warning("build_artifact_paths: 配置非列表，回退空集合: %r", raw)
            return []

        result: List[Tuple[str, str]] = []
        for item in raw:
            if not isinstance(item, str):
                logger.warning("build_artifact_paths: 非字符串项丢弃: %r", item)
                continue

            item = item.strip()
            if not item:
                continue

            if item.startswith("/") or ".." in item.split("/"):
                logger.warning("build_artifact_paths: 绝对路径或含 .. 项丢弃: %r", item)
                continue

            if "*" in item:
                # 通配形态（含 *）：按完整相对路径匹配
                result.append(("glob", item))
                continue

            if not item.endswith("/"):
                logger.warning(
                    "build_artifact_paths: 前缀项未以 / 结尾，丢弃: %r", item
                )
                continue

            # 前缀形态（不含 *，以 / 结尾）
            result.append(("prefix", item))

        return result
    except Exception:
        logger.exception("build_artifact_paths: 解析异常，回退空集合")
        return []


def validate_build_artifact_paths(value: Any) -> Optional[str]:
    """校验配置值的可落盘形态，返回错误提示（合法返回 None）。

    Dashboard write_config 前置校验用（evo-merge-back-wip-artifact-scope D6）：
    worktree.build_artifact_paths 误配后果是静默丢弃语义改动（高风险），故
    Dashboard 保存时**拒绝**非法项而非静默丢弃——与解析侧 normalize 的
    fail-safe（丢弃 + 回退空集合）互补：解析侧保守、写入侧显式。

    与 ``normalize_artifact_patterns`` 同一判定权威：顶层须为字符串列表；逐项
    strip 后仍会被 normalize 丢弃的项（非字符串、绝对路径、含 ``..``、不含
    ``*`` 又未以 ``/`` 结尾）即非法。返回的提示含丢弃项与合法形态示例，供
    前端回显；合法返回 None。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return (
            f"worktree.build_artifact_paths must be a list of strings: {value!r}"
        )
    if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
        return (
            f"worktree.build_artifact_paths must be a list of strings: {value!r}"
        )
    kept = [pat for _, pat in normalize_artifact_patterns(value)]
    discarded = [item for item in value if item.strip() not in kept]
    if discarded:
        return (
            f"worktree.build_artifact_paths 含非法项（将被静默丢弃）：{discarded!r}。"
            f"合法形态示例：目录前缀以 '/' 结尾（如 'dist/'、'build/'），通配含 '*'"
            f"（如 'release-*.zip'）；非字符串/绝对路径/含 '..' 段/未以 '/' "
            f"结尾的前缀均非法。保留项：{kept!r}"
        )
    return None


def worktree_config_view(raw: Any) -> dict:
    """Dashboard 只读回显视图：worktree.build_artifact_paths + has_build_artifacts。

    read_config / read_effective_config 共用（evo-merge-back-wip-artifact-scope D6 /
    fix-artifact-paths-hardcoded-default D5）：从原始 dict（read_config 的 raw 或
    effective）提取两键。build_artifact_paths 非法形态回显空列表；has_build_artifacts
    缺省/非法值回显 None（三态语义——Must 回显 None 区分「未裁决」与「已声明无产物」，
    MUST NOT 缺省填充 false，否则前端开关无法区分两态）。
    """
    wm = raw.get("worktree") if isinstance(raw, dict) else None
    result: dict = {"build_artifact_paths": []}
    if isinstance(wm, dict):
        bap = wm.get("build_artifact_paths")
        if isinstance(bap, list) and all(isinstance(i, str) for i in bap):
            result["build_artifact_paths"] = list(bap)
        # has_build_artifacts：仅显式布尔值透传（回显 true/false），其余一律 None
        hba = wm.get("has_build_artifacts")
        if isinstance(hba, bool):
            result["has_build_artifacts"] = hba
        else:
            result["has_build_artifacts"] = None
    else:
        result["has_build_artifacts"] = None
    return result


# ── 未裁决判定（三态表，fix-artifact-paths-hardcoded-default D2） ─────────

def is_artifact_config_unresolved(
    has_build_artifacts: Any, patterns: Sequence[Tuple[str, str]]
) -> bool:
    """判定项目产物配置是否「未裁决」（三态表，缺省为保守侧）。

    三态判定表（`fix-artifact-paths-hardcoded-default` design D2）：

    | `has_build_artifacts` | 规范化后 patterns | 判定        | 是否未裁决 |
    |-----------------------|--------------------|-------------|-----------|
    | 缺省 None              | 空                 | 恒假        | 是         |
    | 缺省 None              | 非空               | 按配置      | 否         |
    | `false`                | 任意               | 恒假        | 否         |
    | `true`                 | 非空               | 按配置      | 否         |
    | `true`                 | 空                 | 恒假        | 是（标志与路径不一致） |

    非布尔值一律按缺省（None）处理——MUST NOT 因非法值让判定变宽；`patterns`
    取 ``normalize_artifact_patterns`` 的产物（非法项已被丢弃），故「非法/全非法」
    与「未配置」在未裁决判定上同归保守侧。

    Args:
        has_build_artifacts: 配置键 `worktree.has_build_artifacts` 的原始值。
        patterns: ``normalize_artifact_patterns`` 的输出（``(kind, pattern)`` 列表）。
    """
    if has_build_artifacts is False:
        # 已裁决：显式声明无产物（无论路径是否配置）
        return False
    # 缺省（None）或非法（非布尔）→ 按缺省处理；`true` 配空路径同样未裁决
    return not patterns


# ── 判定器类 ─────────────────────────────────────────────────────────────

class ArtifactPathMatcher:
    """构建产物路径判定器（每实例一份，线程内只读）。

    **判定语义**：完全由配置驱动——路径命中任一配置前缀、或命中任一配置通配
    （``fnmatch.fnmatchcase`` 匹配完整相对路径），即视为产物；否则为语义路径。
    **无任何内置默认路径**（`fix-artifact-paths-hardcoded-default` D1）。

    `has_build_artifacts=False`（已声明无产物）时判定短路恒假；未裁决（None）与
    判定正常按 patterns 走（patterns 为空时恒假——未裁决的保守侧）。

    **通配不跨目录**：``fnmatch.fnmatchcase`` 的 ``*`` 含 ``/``，故 MUST 追加
    约束——模式不含 ``/`` 时 MUST NOT 命中含 ``/`` 的路径（只匹配 basename）；
    模式含 ``/`` 时按完整相对路径匹配（可命中多层路径）。

    **故障回退**：配置为空/缺失/全非法时（``normalize_artifact_patterns``
    返回空列表），判定集合为空——判定器自身故障 MUST NOT 让判定变宽或失效。
    """

    def __init__(
        self,
        patterns: Optional[List[Tuple[str, str]]] = None,
        has_build_artifacts: Optional[bool] = None,
    ) -> None:
        """初始化判定器。

        Args:
            patterns: 规范化后的 ``(kind, pattern)`` 列表（来自
                ``normalize_artifact_patterns``）；None/空列表 → 判定集合为空
                （判定恒假，未裁决的保守侧）。
            has_build_artifacts: 项目是否存在构建产物的三态标志：None（未裁决）
                → 按 patterns 判定（空 patterns 恒假）；False（已声明无产物）
                → 判定短路恒假（忽略 patterns）；True → 按 patterns 判定。
                非布尔值按 None（缺省）处理（MUST NOT 让判定变宽）。
        """
        self._has_build_artifacts = has_build_artifacts
        self._patterns: List[Tuple[str, str]] = list(patterns or [])
        self._prefixes: List[str] = []
        self._globs: List[str] = []

        for kind, pattern in (patterns or []):
            if kind == "prefix":
                self._prefixes.append(pattern)
            elif kind == "glob":
                self._globs.append(pattern)

    # ── 未裁决查询 ─────────────────────────────────────────────────────────

    def is_config_unresolved(self) -> bool:
        """本项目（实例所归属的 WorktreeManager）产物配置是否「未裁决」。

        委托模块级 `is_artifact_config_unresolved`（三态表唯一权威）——patterns
        取构造时注入的规范化列表（None/空列表与空判定集合等价）。
        """
        return is_artifact_config_unresolved(self._has_build_artifacts, self._patterns)

    # ── 公开方法 ──────────────────────────────────────────────────────────

    def is_artifact(self, path: str) -> bool:
        """路径是否为构建产物（已声明无产物时恒假）。"""
        if self._has_build_artifacts is False:
            return False

        for prefix in self._prefixes:
            if path.startswith(prefix):
                return True

        for glob in self._globs:
            if self._match_glob(path, glob):
                return True

        return False

    def paths_in(self, paths: Sequence[str]) -> List[str]:
        """过滤出产物路径。"""
        return [p for p in paths if self.is_artifact(p)]

    def non_artifacts_in(self, paths: Sequence[str]) -> List[str]:
        """过滤出语义路径（非产物）。"""
        return [p for p in paths if not self.is_artifact(p)]

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _match_glob(self, path: str, glob: str) -> bool:
        """通配匹配，附带跨目录约束。

        - 模式不含 ``/``：只匹配不含 ``/`` 的路径（仓库根级相对路径）——
        fnmatch 的 ``*`` 含 ``/``，若不限制会把任意深度的同名文件误判为产物；
        - 模式含 ``/``：按完整相对路径匹配（可命中多层路径）。
        """
        if "/" not in glob:
            # 模式不含 / → MUST NOT 命中含 / 的路径
            if "/" in path:
                return False
            return fnmatch.fnmatchcase(path, glob)
        # 模式含 / → 按完整相对路径匹配
        return fnmatch.fnmatchcase(path, glob)