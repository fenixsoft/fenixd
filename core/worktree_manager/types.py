"""types.py — 数据类定义（refactor-giant-classes D1/D5）。

`MergeConflictInfo`：merge-back 返回值，兼容 `(bool, str)` 解包的结构化冲突分类。
原样从 `core/worktree_manager.py` 搬移（design D7 不使用绝对行号锚定）。

`WipOccupantInfo`：WIP overlap 占用者识别结果（add-mergeback-wip-active-coordination
1.1/D1），随 defer 批进度/日志/台账留痕。
"""

import copy
import time


class WipOccupantInfo:
    """WIP overlap 占用者识别结果（add-mergeback-wip-active-coordination 1.1/D1）。

    D1 识别数据源纯机械：在飞实现车道 run 列表 × 各 run 分支相对主树 HEAD 的
    改动文件集，与 overlap 文件集求交。命中 → ``holder=True``（``holders`` 列出
    run/spec/分支/命中文件，可追溯）；零命中 → ``holder=False``（无主陈旧 WIP）。

    已知盲区（须随识别证据留痕）：本数据源主覆盖 **worktree 分支型**在飞
    车道；持有者直接改主树不入分支的形态（admin/人工会话、主树内构建产物）
    分支 diff 必零命中。该盲区由只读「主树活交互会话」探测补充归因
    （evo-add-maintree-interactive-session-attribution 1.2，source=
    ``SOURCE_MAINTREE_SESSION``）：散件与活会话有相关性信号（最近提交人
    启发路径交 / transcript 活跃且路径提及）时判为会话占用者，探测零命中/
    源缺失仍按无主走宽限升级——升级仅为告警，误判影响有界。
    ``describe()`` / ``to_dict()`` 产出的证据文本/结构均携带该注记。
    """

    # 识别源常量：在飞车道分支 diff（既有）/ 主树活交互会话只读探测（1.2）。
    SOURCE_LANE_DIFF = "worktree-branch-diff"
    SOURCE_MAINTREE_SESSION = "maintree-interactive-session"

    BLIND_SPOT_NOTE = (
        "识别数据源主覆盖 worktree 分支型在飞车道（implementer/code-fix run 的"
        "分支 diff）；持有者直接改主树不入分支的形态（admin/人工会话、主树内"
        "构建产物）分支 diff 必零命中——该形态由只读「主树活交互会话」探测"
        "（source=maintree-interactive-session）补充归因，探测零命中/源缺失"
        "时仍按无主走宽限升级"
    )

    __slots__ = ("holder", "holders", "overlap", "identified_at", "source")

    def __init__(
        self,
        holder: bool,
        holders: list | None = None,
        overlap: list | None = None,
        identified_at: str = "",
        source: str = SOURCE_LANE_DIFF,
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
        """全部命中车道的 run_id 并集（去重保序，供 per-run 终态监听注册）。

        会话归因形态（``is_session_attribution()``）的 holders 无 run_ids
        （会话不是框架 run），本方法自然返回空列表——defer 消费侧据此不注册
        终态回调（事件驱动重试缺席、既有轮询兜底在场）。
        """
        seen: list = []
        for h in self.holders:
            for rid in h.get("run_ids") or []:
                rid = str(rid)
                if rid and rid not in seen:
                    seen.append(rid)
        return seen

    def is_session_attribution(self) -> bool:
        """会话归因形态判定：命中且识别源为主树活交互会话只读探测。"""
        return self.holder and self.source == self.SOURCE_MAINTREE_SESSION

    def occupant_kind(self) -> str:
        """归因形态标签（盘点/台账结构化留痕用）：在飞车道 | 会话 | 无主。"""
        if self.holder:
            return (
                "interactive-session"
                if self.is_session_attribution()
                else "inflight-lane"
            )
        return "orphan"

    def describe(self) -> str:
        """单行识别摘要（随 defer 批进度 current / 日志留痕）。"""
        if self.is_session_attribution():
            parts = []
            for h in self.holders:
                clue = h.get("session") or {}
                signals = ",".join(
                    str(s) for s in (clue.get("signals") or [])
                ) or "?"
                parts.append(
                    f"会话={clue.get('identity') or '未识别身份'}"
                    f" 信号={signals}"
                    f" 命中{len(h.get('files') or [])}文件"
                )
            # 兜底：holder=True 语义上应伴随非空 holders，构造不当（holders
            # 为空）时显式标注，避免产出带空分隔符的畸形摘要。
            if not parts:
                parts.append("无命中明细")
            return (
                f"占用者=主树活交互会话（{'；'.join(parts)}；"
                f"只读探测归因，非无主盲区）"
            )
        if self.holder:
            parts = []
            for h in self.holders:
                parts.append(
                    f"spec={h.get('spec') or '?'} branch={h.get('branch') or '?'}"
                    f" run={','.join(h.get('run_ids') or []) or '?'}"
                    f" 命中{len(h.get('files') or [])}文件"
                )
            # 兜底：holder=True 语义上应伴随非空 holders，构造不当（holders
            # 为空）时显式标注，避免产出带空分隔符的畸形摘要。
            if not parts:
                parts.append("无命中明细")
            return f"占用者=在飞车道（{'；'.join(parts)}；{self.BLIND_SPOT_NOTE}）"
        return (
            f"占用者=无主陈旧 WIP（数据源={self.source}；{self.BLIND_SPOT_NOTE}）"
        )

    def to_dict(self) -> dict:
        """结构化留痕形态（随 defer 台账 owner_* 字段落盘）。

        快照不可变（code-review item 2d8edcef77ce）：holders 逐条深拷贝，嵌套
        run_ids/files 列表与原对象断开引用——调用方落盘前后对 holders 做去重/
        裁剪，不再连带改动已产出的台账结构。
        """
        return {
            "holder": self.holder,
            "holders": copy.deepcopy(self.holders),
            "overlap": list(self.overlap),
            "identified_at": self.identified_at,
            "source": self.source,
            "occupant_kind": self.occupant_kind(),
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
        "amended_inflight",
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
        amended_inflight: list | None = None,
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
        # 已提交在飞修订检测（evo-inflight-spec-amendment-watch 1.1）：merge-back
        # 前检测到 spec/changes/<spec>/ 相对 merge-base 在主树出现的新已提交修订
        # 时，携带修订提交短哈希列表（时间正序）；空列表 = 未命中/未检测。仅附带
        # 情报，MUST NOT 改变 success/has_semantic_conflict 语义（1.2）——相撞
        # 仍由预演检出并按既有 rehearsed 链路转 repair，本字段只给 repair 车道
        # 透传根因（dispatch 层消费）。
        self.amended_inflight = list(amended_inflight or [])

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
            f"spec_dir_inflight={self.spec_dir_inflight}, "
            f"amended_inflight={self.amended_inflight})"
        )
