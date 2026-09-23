"""code_review.py — Dashboard 读取器（add-code-review-agent-and-quality-tab）。

纯读侧封装：把 ``core.code_review`` 的台账读函数与进度函数转导为
Dashboard 端点友好形态（状态过滤 + severity 排序）。写路径（items/status、
generate-spec）由 routes 层直接调 ``core.code_review``（与 evolution
items 的 accept/reject 端点同构），本模块不承载写逻辑。
"""

import json
from pathlib import Path

from core.code_review import normalize_severity, read_items, read_progress

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
    except (TypeError, ValueError, OverflowError):
        # OverflowError：非有限浮点（int(float('inf'))）。json.loads 默认接受
        # Infinity/-Infinity 字面量，LLM 产出台账行 line: Infinity 时会走到这里
        # ——不捕获会穿透本函数使列表端点 500（code-review item 7ff80c561c99）。
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
    # severity 读侧归一（2026-09-23）：写侧 normalize_severity 只能治愈新写入/
    # upsert 刷新的条目，台账存量漂移行（ocr 透传的 high/medium/low）在本处
    # 统一映射，使排序与前端过滤/色系按四档生效——零数据迁移，漂移行随下次
    # 被审查 upsert 在盘上自然刷新。rec 为本函数私有加载产物，就地改写安全。
    for rec in rows:
        rec["severity"] = normalize_severity(rec.get("severity"))
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


def read_code_review_fix_progress(project_root) -> dict:
    """转导 ``core.code_fix.read_progress``（自动修复进度，task 8.1）。

    缺失/损坏由 core 层兜底返回缺省态（``running=false, phase="idle",
    total=0, done=0``），不抛异常——读侧 MUST NOT 500。

    条级字段（add-code-fix-item-level-progress 4.1）：``item_done`` /
    ``current_item`` / ``batch_total`` 原样透传（字段缺失补 null，对齐既有
    缺省态兜底口径）；``worktree``/``run_id`` 是读侧定位 out 产物的内部
    索引，MUST NOT 外泄给前端。
    """
    from core.code_fix import read_progress as _fix_read_progress

    data = _fix_read_progress(project_root)
    out = dict(data)
    for key in ("item_done", "current_item", "batch_total"):
        out[key] = data.get(key)
    out.pop("worktree", None)
    out.pop("run_id", None)
    return out


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