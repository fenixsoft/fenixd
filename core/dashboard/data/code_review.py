"""code_review.py — Dashboard 读取器（add-code-review-agent-and-quality-tab）。

纯读侧封装：把 ``core.code_review`` 的台账读函数与进度函数转导为
Dashboard 端点友好形态（状态过滤 + severity 排序）。写路径（items/status、
generate-spec）由 routes 层直接调 ``core.code_review``（与 evolution
items 的 accept/reject 端点同构），本模块不承载写逻辑。
"""

from core.code_review import read_items, read_progress

_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


def read_code_review_items(project_root, statuses=None):
    """读台账并按状态过滤（默认仅 open），按 severity 排序返回列表。

    statuses: None → 仅 ``open``；列表 → 该集合内的状态（如
    ["open", "in_spec"] 供「清除归属」后的视图刷新）。
    """
    items = read_items(project_root)
    wanted = set(statuses) if statuses else {"open"}
    rows = [rec for rec in items.values() if rec.get("status") in wanted]
    rows.sort(
        key=lambda r: (
            _SEVERITY_ORDER.get(str(r.get("severity")), 9),
            str(r.get("file") or ""),
            int(r.get("line") or 1),
        )
    )
    return rows


def read_code_review_progress(project_root) -> dict:
    """转导 ``core.code_review.read_progress``（进度结构保持一致）。"""
    return read_progress(project_root)