"""code_review.py — Dashboard 读取器（add-code-review-agent-and-quality-tab）。

纯读侧封装：把 ``core.code_review`` 的台账读函数与进度函数转导为
Dashboard 端点友好形态（状态过滤 + severity 排序）。写路径（items/status、
generate-spec）由 routes 层直接调 ``core.code_review``（与 evolution
items 的 accept/reject 端点同构），本模块不承载写逻辑。
"""

import json
from pathlib import Path

from core.code_review import (
    normalize_severity,
    read_items,
    read_progress,
    read_request_result,
)

_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}
_STATUS_ORDER = {"open": 0, "in_spec": 1, "resolved": 2, "ignored": 3}
# 排序字段/方向白名单（2026-09-24 台账 server-side 分页配套，quality 页两列
# 排序下沉后端）：外部 query 输入只能落到这两张枚举表——MUST NOT 把 query 值
# 直接当排序键消费。权重表即前端受控排序的档位次序。
_SORT_FIELDS = {"severity": _SEVERITY_ORDER, "status": _STATUS_ORDER}
_SORT_DIRECTIONS = {"asc": 1, "desc": -1}


def _line_key(value) -> int:
    """排序用 line 键的容错转换（code-review item 742aaa115975 / 8ee57272c6be）。

    台账中 line 若非数字（历史/手写/未来写入方），裸 int() 会抛异常使整个列表
    端点 500——违背 read_items「列表端点依赖容错」的契约。提取首个整数段，失败
    回退 1（行号仅用于稳定排序，非事实字段）。与 core.code_review._coerce_line
    同口径但本模块不反向依赖其私有函数。
    """
    if isinstance(value, bool) or value is None:
        return 1
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError：非有限浮点（int(float('inf'))）。json.loads 默认接受
        # Infinity/-Infinity 字面量，LLM 产出台账行 line: Infinity 时会走到这里
        # ——不捕获会穿透本函数使列表端点 500（code-review item 7ff80c561c99）。
        import re

        m = re.search(r"\d+", str(value))
        return int(m.group(0)) if m else 1


def read_code_review_items(project_root, statuses=None, sort_by=None, sort_order=None):
    """读台账并按状态过滤（默认仅 open），按 severity 排序返回列表。

    statuses: None → 仅 ``open``（默认视图）；显式传入列表（含空列表）→ 严格
    按该集合过滤——空列表返回空结果而非回退 open（code-review item
    6eec934d7fc9：路由把 ``?status=,,`` 解析为 [] 时不应意外返回全部 open）。
    sort_by/sort_order: server-side 排序（2026-09-24 台账分页配套）——
    ``severity``|``status`` × ``asc``|``desc``；白名单外值回退默认排序
    （severity 升序，即 sort_by/sort_order 均缺省的历史行为）。同键条目沿用
    (file, line) 稳定次序，desc 反转主键权重（次级键保持升序，未知档位在
    asc/desc 两向恒排末尾）。
    """
    items = read_items(project_root)
    wanted = {"open"} if statuses is None else set(statuses)
    # rows 为完整台账记录 dict（evo-code-review-snapshot-writeoff-integrity
    # 2.3/R4 契约确认）：resolution 字段随行自动透传给 routes→前端，前端据此
    # 展示核销来源徽标（code-fix-auto=已修复 / snapshot_closed=快照关闭 /
    # 缺失按快照关闭口径解读）。本读侧不做 resolution 归一/回填——存量
    # resolution=None 的历史 resolved 条目按原样透出，由前端按快照关闭口径
    # 解读（存量不回填改写，design 决策 3）。
    rows = [rec for rec in items.values() if rec.get("status") in wanted]
    # severity 读侧归一（2026-09-23）：写侧 normalize_severity 只能治愈新写入/
    # upsert 刷新的条目，台账存量漂移行（ocr 透传的 high/medium/low）在本处
    # 统一映射，使排序与前端过滤/色系按四档生效——零数据迁移，漂移行随下次
    # 被审查 upsert 在盘上自然刷新。rec 为本函数私有加载产物，就地改写安全。
    for rec in rows:
        rec["severity"] = normalize_severity(rec.get("severity"))
    field = sort_by if sort_by in _SORT_FIELDS else "severity"
    sign = _SORT_DIRECTIONS.get(str(sort_order or "asc").lower(), 1)
    rows.sort(
        key=lambda r: (
            # 未知档位缺省权重按 sign 翻转（sign*9）：有效键恒为 sign*(sign*9)=9，
            # 大于任一方向下全部已知档位的有效权重（asc 最大 3 / desc 最大 0），
            # 使「未知档位恒排末尾」在 asc/desc 两向都成立（code-review item
            # c3e99570788b）；已知档位查表命中，权重不受影响。
            sign * _SORT_FIELDS[field].get(str(r.get(field)), sign * 9),
            str(r.get("file") or ""),
            _line_key(r.get("line")),
        )
    )
    return rows


def read_code_review_progress(project_root) -> dict:
    """转导 ``core.code_review.read_progress``（进度结构保持一致）。"""
    return read_progress(project_root)


def read_code_review_fix_progress(project_root) -> dict:
    """转导 ``core.code_fix.read_progress``（自动修复进度，task 8.1）。

    缺失/损坏由 core 层兜底返回缺省态（``running=false, phase="idle",
    total=0, done=0``），不抛异常——读侧 MUST NOT 500。

    条级字段（add-code-fix-item-level-progress 4.1）：``item_done`` /
    ``current_item`` / ``batch_total`` 原样透传——全键在场由
    ``core.code_fix.read_progress`` 白名单合并保证，本函数只剔内部
    索引键；``worktree``/``run_id`` 是读侧定位 out 产物的内部
    索引，MUST NOT 外泄给前端。
    """
    from core.code_fix import read_progress as _fix_read_progress

    data = _fix_read_progress(project_root)
    out = dict(data)
    # item_done/current_item/batch_total 无需补键：read_progress 白名单合并
    # 保证 FIX_PROGRESS_DEFAULT 全键在场，_synthesize_item_progress 又无条件
    # 重算前两者——dict(data) 拷贝的值即最终值（code-review item 3193447da0ae）。
    out.pop("worktree", None)
    out.pop("run_id", None)
    return out


def read_code_review_request_result(project_root) -> dict:
    """读手动触发 code-review 的受理判定结果（add-code-review-trigger-ack 2.1）。

    只读透传 daemon 消费端写回的 ``.fenix/code_review_request_result.json``
    （``{requested_at, status, reason, message, finished_at}``，``status``
    为 started/dropped/failed 三值）。文件缺失/损坏/非 dict → 缺省态全
    null 形态（``core.code_review.read_request_result`` 兜底，读侧 MUST
    NOT 500，形态对齐 read_code_fix_request_result 的只读透传口径）。
    前端以 ``requested_at`` 与本次触发返回的 ``requested_at`` 一致回链判定
    是否本次结果，陈旧残留 MUST NOT 被当作本次反馈。
    """
    return read_request_result(project_root)


def read_code_fix_request_result(project_root) -> dict:
    """读手动「立即自动修复」触发判定结果（add-code-fix-manual-trigger 2.2）。

    只读透传 daemon 消费端写回的 ``.fenix/code_fix_request_result.json``
    （``{request_created, triggered, reason, message, finished_at}``）；
    文件缺失/损坏/非 dict → 缺省态 ``{}``（读侧 MUST NOT 500，形态对齐
    read_code_review_fix_progress）。前端以 ``request_created`` 与本次触发
    返回的 ``requested_at`` 回链判定是否本次结果。
    """
    path = Path(project_root) / ".fenix" / "code_fix_request_result.json"
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}