"""types.py — 数据类定义（refactor-giant-classes D1/D5）。

`MergeConflictInfo`：merge-back 返回值，兼容 `(bool, str)` 解包的结构化冲突分类。
原样从 `core/worktree_manager.py` 搬移（design D7 不使用绝对行号锚定）。

`WipOccupantInfo`：WIP overlap 占用者识别结果（add-mergeback-wip-active-coordination
1.1/D1），随 defer 批进度/日志/台账留痕。
"""

import time


class WipOccupantInfo:
    """WIP overlap 占用者识别结果（add-mergeback-wip-active-coordination 1.1/D1）。

    D1 识别数据源纯机械：在飞实现车道 run 列表 × 各 run 分支相对主树 HEAD 的
    改动文件集，与 overlap 文件集求交。命中 → ``holder=True``（``holders`` 列出
    run/spec/分支/命中文件，可追溯）；零命中 → ``holder=False``（无主陈旧 WIP）。

    已知盲区（D1，须随识别证据留痕）：本数据源只覆盖 **worktree 分支型**在飞
    车道；持有者直接改主树不入分支的形态（admin/人工会话、主树内构建产物）
    分支 diff 必零命中，一律按无主走宽限升级——升级仅为告警，误判影响有界。
    ``describe()`` / ``to_dict()`` 产出的证据文本/结构均携带该注记。
    """

    BLIND_SPOT_NOTE = (
        "识别数据源只覆盖 worktree 分支型在飞车道（implementer/code-fix run 的"
        "分支 diff）；持有者直接改主树不入分支的形态（admin/人工会话、主树内"
        "构建产物）分支 diff 必零命中，一律按无主走宽限升级"
    )

    __slots__ = ("holder", "holders", "overlap", "identified_at", "source")

    def __init__(
        self,
        holder: bool,
        holders: list | None = None,
        overlap: list | None = None,
        identified_at: str = "",
        source: str = "worktree-branch-diff",
    ):
        self.holder = bool(holder)
        # 命中明细：[{"run_ids": [...], "spec": str, "branch": str,
        #             "worktree": str, "files": [命中文件,...]}]
        self.holders = list(holders or [])
        self.overlap = [str(p) for p in (overlap or [])]
        self.identified_at = identified_at or time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        self.source = source

    def holder_run_ids(self) -> list:
        """全部命中车道的 run_id 并集（去重保序，供 per-run 终态监听注册）。"""
        seen: list = []
        for h in self.holders:
            for rid in h.get("run_ids") or []:
                rid = str(rid)
                if rid and rid not in seen:
                    seen.append(rid)
        return seen

    def describe(self) -> str:
        """单行识别摘要（随 defer 批进度 current / 日志留痕）。"""
        if self.holder:
            parts = []
            for h in self.holders:
                parts.append(
                    f"spec={h.get('spec') or '?'} branch={h.get('branch') or '?'}"
                    f" run={','.join(h.get('run_ids') or []) or '?'}"
                    f" 命中{len(h.get('files') or [])}文件"
                )
            return f"占用者=在飞车道（{'；'.join(parts)}；{self.BLIND_SPOT_NOTE}）"
        return (
            f"占用者=无主陈旧 WIP（数据源={self.source}；{self.BLIND_SPOT_NOTE}）"
        )

    def to_dict(self) -> dict:
        """结构化留痕形态（随 defer 台账 owner_* 字段落盘）。"""
        return {
            "holder": self.holder,
            "holders": [dict(h) for h in self.holders],
            "overlap": list(self.overlap),
            "identified_at": self.identified_at,
            "source": self.source,
            "blind_spot_note": self.BLIND_SPOT_NOTE,
        }

    def __repr__(self) -> str:
        return (
            f"WipOccupantInfo(holder={self.holder}, holders={self.holders}, "
            f"overlap={self.overlap}, identified_at={self.identified_at!r}, "
            f"source={self.source!r})"
        )


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
        "wip_gate_blocked",
        "spec_dir_inflight",
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
        wip_gate_blocked: bool = False,
        spec_dir_inflight: bool = False,
    ):
        self.success = bool(success)
        self.error = error
        self.conflict_paths = list(conflict_paths or [])
        self.self_heal_applicable = self_heal_applicable
        self.self_heal_succeeded = self_heal_succeeded
        self.has_semantic_conflict = has_semantic_conflict
        self.rehearsed = bool(rehearsed)
        # WIP 重叠预检（fix-mergeback-stashpop-silent-loss D3）：主树脏 tracked
        # 文件与分支改动文件的交集，空列表 = 无重叠。
        self.wip_overlap = list(wip_overlap or [])
        # WIP 重叠闸门阻塞（evo-merge-back-wip-overlap-gate D1）：True = merge-back
        # 被前置闸门按阻塞策略中止（不 stash、不 merge、不 pop，主树零污染）。
        # dispatch 层据此旁路 _merge_fp/_merge_streak 熔断记账与 ready 降级，
        # spec 保持 in-flight 只发告警等待人工处置（对照 rehearsed 同类豁免）。
        self.wip_gate_blocked = bool(wip_gate_blocked)
        # spec 目录在飞编辑顺延（evo-merge-back-spec-dir-inflight-guard D1）：
        # True = merge-back 前检测到 spec/changes/<spec>/ 存在未提交改动（含
        # untracked），不进入 merge（主树零污染），返回顺延信号。
        # dispatch 层据此旁路熔断记账，spec 保持 in-flight 只重试合并（不重派
        # 实现 run），由外部提交动作解除；有界顺延超限回落告警+人工通道。
        self.spec_dir_inflight = bool(spec_dir_inflight)

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
            f"wip_overlap={self.wip_overlap}, "
            f"wip_gate_blocked={self.wip_gate_blocked}, "
            f"spec_dir_inflight={self.spec_dir_inflight})"
        )
