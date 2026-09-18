"""
artifact_paths — 构建产物路径判定器。

**迁移背景**（evo-merge-back-wip-artifact-scope）：

判定语义从「全局常量 + 单条硬编码规则」改为「每个 WorktreeManager 实例持有一组
可配置前缀 + 一组包级默认前缀」的判定器。原 `_is_build_artifact_path()` 是包级
自由函数（`core/worktree_manager/__init__.py:74`），只有一条硬编码规则：路径以
`core/dashboard/static/` 开头、且其下任一层级含 `dist` 目录。该判定被复用在多条
语义不同的调用路径上，对「构建产物在仓库根」的项目形态（如根级 `dist/`、
`release-*.zip` 等发布产物）完全失效，故迁移为实例状态 + 可配置
前缀/后缀通配。

**调用点清单**（语义不同的调用路径）：

1. `mergeback._rehearse_merge_from_branch`：merge 预演闸，`non_artifact` 非空即判
   语义冲突 → 直通 repair 通道；
2. `mergeback` merge 冲突分类（`self_heal_applicable` / `has_semantic_conflict`）：
   产物自愈不适用 → abort + 分类为语义；
3. `dist_conflicts._resolve_build_artifact_conflicts` / `_artifact_paths` /
   `_rebuild_dist_after_merge`：产物冲突对齐、stray 清账、ref 产物枚举与
   `src_touched` 判定；
4. `mergeback._wip_overlap_gate`（D3b）：WIP 重叠子集中产物的 stash 前置对齐。

判定语义从全局常量改为实例状态后，继续放在 `__init__.py` 会把配置解析引入包
导入路径并制造 import 环（`mergeback` / `dist_conflicts` 已从包命名空间解析常量），
故独立成模块；本模块只依赖标准库（`pathlib` / `fnmatch`），可被任何调用方安全导入。
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any, List, Optional, Sequence, Tuple

# ── 包级常量 ─────────────────────────────────────────────────────────────

# 框架既有有效集合（向后兼容默认值）：static 根（不含尾斜杠，避免与
# DASHBOARD_STATIC_ROOT 常量重复定义——后者保留在 `__init__.py` 供既有引用）。
DEFAULT_ARTIFACT_PREFIXES: Tuple[str, ...] = ("core/dashboard/static",)

# 默认判定的内部静态根（带尾斜杠，逐字节复刻既有 `_is_build_artifact_path`
# 的 `DASHBOARD_STATIC_ROOT` 语义：尾斜杠保证 `core/dashboard/static-file` 之类
# 前缀同形但非 static 根的路径不被误判）。
_DEFAULT_STATIC_ROOT = "core/dashboard/static/"

logger = logging.getLogger("fenixd.worktree_manager.artifact_paths")


# ── 默认判定（既有语义的逐字节搬运） ─────────────────────────────────────

def _matches_default(path: str) -> bool:
    """构建产物路径判定：static 根下任一层级 dist 目录内的文件。

    既有 `_is_build_artifact_path`（`core/worktree_manager/__init__.py`）语义的
    原样搬入，作为「默认判定」的模块级实现；`core/worktree_manager/__init__.py`
    的 `_is_build_artifact_path` 将委托 `ArtifactPathMatcher().is_artifact(path)`，
    签名与返回值语义逐字节不变。
    """
    if not path.startswith(_DEFAULT_STATIC_ROOT):
        return False
    parts = path[len(_DEFAULT_STATIC_ROOT) :].split("/")
    return len(parts) >= 2 and "dist" in parts[:-1]


# ── 配置规范化 ───────────────────────────────────────────────────────────

def normalize_artifact_patterns(raw: Any) -> List[Tuple[str, str]]:
    """把配置值规范化为 ``(kind, pattern)`` 列表，``kind ∈ {"prefix", "glob"}``。

    **丢弃规则**（逐项，记 WARNING）：

    - 非列表的值整体拒绝（空列表）；非字符串项丢弃；
    - 不含 ``*`` 且未以 ``/`` 结尾的项丢弃（前缀形态 MUST 以 ``/`` 结尾，
      避免 `dist` 前缀意外匹配 `dists/`、`distfoo/`）；
    - 绝对路径（以 ``/`` 开头）或含 ``..`` 段的项丢弃。

    任何异常捕获后返回空列表（fail-safe 回退默认：``ArtifactPathMatcher``
    以空列表构造时只用默认集合，判定器自身故障 MUST NOT 让判定变宽或失效）。
    """
    try:
        if raw is None:
            return []

        if not isinstance(raw, list):
            logger.warning("build_artifact_paths: 配置非列表，回退默认: %r", raw)
            return []

        result: List[Tuple[str, str]] = []
        for item in raw:
            if not isinstance(item, str):
                logger.warning("build_artifact_paths: 非字符串项丢弃: %r", item)
                continue

            item = item.strip()
            if not item:
                continue

            if item.startswith("/") or ".." in item:
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
        logger.exception("build_artifact_paths: 解析异常，回退默认")
        return []


def validate_build_artifact_paths(value: Any) -> Optional[str]:
    """校验配置值的可落盘形态，返回错误提示（合法返回 None）。

    Dashboard write_config 前置校验用（evo-merge-back-wip-artifact-scope D6）：
    worktree.build_artifact_paths 误配后果是静默丢弃语义改动（高风险），故
    Dashboard 保存时**拒绝**非法项而非静默丢弃——与解析侧 normalize 的
    fail-safe（丢弃 + 回退默认）互补：解析侧保守、写入侧显式。

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
    """Dashboard 只读回显视图：worktree.build_artifact_paths（字符串列表）或空。

    read_config / read_effective_config 共用（evo-merge-back-wip-artifact-scope D6）：
    从原始 dict（read_config 的 raw 或 effective）提取 worktree.build_artifact_paths。
    非法形态（非列表/含非字符串项）回显空列表——与判定器 normalize_artifact_patterns
    的 fail-safe 语义一致：非法即回退默认集合，展示为「未配置」。
    """
    wm = raw.get("worktree") if isinstance(raw, dict) else None
    if isinstance(wm, dict):
        bap = wm.get("build_artifact_paths")
        if isinstance(bap, list) and all(isinstance(i, str) for i in bap):
            return {"build_artifact_paths": list(bap)}
    return {"build_artifact_paths": []}


# ── 判定器类 ─────────────────────────────────────────────────────────────

class ArtifactPathMatcher:
    """构建产物路径判定器（每实例一份，线程内只读）。

    **判定语义**：路径命中任一配置前缀、或命中任一配置通配（
    ``fnmatch.fnmatchcase`` 匹配完整相对路径）、或命中默认规则（向后兼容），
    即视为产物；否则为语义路径。

    **通配不跨目录**：``fnmatch.fnmatchcase`` 的 ``*`` 含 ``/``，故 MUST 追加
    约束——模式不含 ``/`` 时 MUST NOT 命中含 ``/`` 的路径（只匹配 basename）；
    模式含 ``/`` 时按完整相对路径匹配（可命中多层路径）。

    **故障回退**：配置为空/缺失/全非法时（如 ``normalize_artifact_patterns``
    返回空列表），只用默认集合——判定器自身故障 MUST NOT 让判定变宽或失效。
    """

    def __init__(
        self,
        patterns: Optional[List[Tuple[str, str]]] = None,
        defaults: Optional[Tuple[str, ...]] = None,
    ) -> None:
        """初始化判定器。

        Args:
            patterns: 规范化后的 ``(kind, pattern)`` 列表（来自
                ``normalize_artifact_patterns``）；None/空列表 → 只用默认集合。
            defaults: 默认判定使用的静态根集合（缺省
                ``DEFAULT_ARTIFACT_PREFIXES``），仅供 `_matches_default` 语义的
                委托判定（当前仅取首个元素作为静态根）。
        """
        self._defaults = defaults if defaults is not None else DEFAULT_ARTIFACT_PREFIXES
        self._prefixes: List[str] = []
        self._globs: List[str] = []

        for kind, pattern in (patterns or []):
            if kind == "prefix":
                self._prefixes.append(pattern)
            elif kind == "glob":
                self._globs.append(pattern)

    # ── 公开方法 ──────────────────────────────────────────────────────────

    def is_artifact(self, path: str) -> bool:
        """路径是否为构建产物。"""
        for prefix in self._prefixes:
            if path.startswith(prefix):
                return True

        for glob in self._globs:
            if self._match_glob(path, glob):
                return True

        return self._match_default(path)

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

    def _match_default(self, path: str) -> bool:
        """默认规则命中（向后兼容）：static 根下任一层级 dist 目录内的文件。

        委托模块级 `_matches_default`（逐字节复刻既有 `_is_build_artifact_path`）。
        """
        return _matches_default(path)