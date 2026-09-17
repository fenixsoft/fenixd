"""types.py — 数据类定义（refactor-giant-classes D1/D5）。

`MergeConflictInfo`：merge-back 返回值，兼容 `(bool, str)` 解包的结构化冲突分类。
原样从 `core/worktree_manager.py` 搬移（design D7 不使用绝对行号锚定）。
"""


class MergeConflictInfo:
    """merge-back 返回值：兼容 ``(bool, str)`` 元组解包的结构化冲突分类。

    add-merge-back-repair-lane D1「git 层判定、调度层决策」：worktree_manager
    保持纯 git 操作层，merge-back 失败时在返回值里附带结构化冲突分类（冲突
    路径清单 + 是否仍有语义冲突），**是否进入 repair 通道由调度层决策**。

    既有调用方 ``success, err = merge_back_from_branch(...)`` 照常解包
    （``__iter__`` 按 ``(success, error)`` 顺序产出）；调度层可读取结构化
    字段（``conflict_paths`` / ``has_semantic_conflict``）判断是否派发
    repair agent。
    """

    __slots__ = (
        "success",
        "error",
        "conflict_paths",
        "self_heal_applicable",
        "self_heal_succeeded",
        "has_semantic_conflict",
        "rehearsed",
        "wip_overlap",
    )

    def __init__(
        self,
        success: bool,
        error: str,
        conflict_paths: list | None = None,
        self_heal_applicable: bool = False,
        self_heal_succeeded: bool = False,
        has_semantic_conflict: bool = False,
        rehearsed: bool = False,
        wip_overlap: list | None = None,
    ):
        self.success = bool(success)
        self.error = error
        self.conflict_paths = list(conflict_paths or [])
        self.self_heal_applicable = self_heal_applicable
        self.self_heal_succeeded = self_heal_succeeded
        self.has_semantic_conflict = has_semantic_conflict
        self.rehearsed = bool(rehearsed)
        # WIP 重叠预检（fix-mergeback-stashpop-silent-loss D3）：主树脏 tracked
        # 文件与分支改动文件的交集，空列表 = 无重叠。只预警不阻断。
        self.wip_overlap = list(wip_overlap or [])

    def __iter__(self):
        """兼容 (bool, str) 解包：既有调用方 ``success, err = ...`` 照常工作。"""
        yield self.success
        yield self.error

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        return (
            f"MergeConflictInfo(success={self.success}, error={self.error!r}, "
            f"conflict_paths={self.conflict_paths}, "
            f"self_heal={self.self_heal_applicable}/{self.self_heal_succeeded}, "
            f"semantic={self.has_semantic_conflict}, rehearsed={self.rehearsed}, "
            f"wip_overlap={self.wip_overlap})"
        )
