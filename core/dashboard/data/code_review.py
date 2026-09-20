"""code_review.py — Dashboard 读取器（add-code-review-agent-and-quality-tab）。

纯读侧封装：把 ``core.code_review`` 的台账读函数与进度函数转导为
Dashboard 端点友好形态（状态过滤 + severity 排序）。写路径（items/status、
generate-spec）由 routes 层直接调 ``core.code_review``（与 evolution
items 的 accept/reject 端点同构），本模块不承载写逻辑。
"""

from core.code_review import read_items, read_progress

_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


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
    except (TypeError, ValueError):
        import re

        m = re.search(r"\d+", str(value))
        return int(m.group(0)) if m else 1


def read_code_review_items(project_root, statuses=None):
    """读台账并按状态过滤（默认仅 open），按 severity 排序返回列表。

    statuses: None → 仅 ``open``（默认视图）；显式传入列表（含空列表）→ 严格
    按该集合过滤——空列表返回空结果而非回退 open（code-review item
    6eec934d7fc9：路由把 ``?status=,,`` 解析为 [] 时不应意外返回全部 open）。
    """
    items = read_items(project_root)
    wanted = {"open"} if statuses is None else set(statuses)
    rows = [rec for rec in items.values() if rec.get("status") in wanted]
    rows.sort(
        key=lambda r: (
            _SEVERITY_ORDER.get(str(r.get("severity")), 9),
            str(r.get("file") or ""),
            _line_key(r.get("line")),
        )
    )
    return rows


def read_code_review_progress(project_root) -> dict:
    """转导 ``core.code_review.read_progress``（进度结构保持一致）。"""
    return read_progress(project_root)