"""core.dashboard.data.evolution_items — 建议改进项读取助手（evolution_items 组）。

refactor-dashboard-data-module D3 分组：本模块承载 evolution_items 职责域。
包含 6.4/6.5 草稿/分析文档读取与白名单校验。
"""

from pathlib import Path

# ── 建议改进项读取助手（add-framework-self-evolution 6.4/6.5）────────

# 草稿文档白名单（doc 参数；spec → specs/<capability>/spec.md）
EVOLUTION_DOC_WHITELIST = ("proposal", "design", "tasks", "spec")

# spec 之外三项 doc → 文件名映射（草稿路径与 SPEC 回退路径共用，单点维护）
EVOLUTION_DOC_FILES = {
    "proposal": "proposal.md",
    "design": "design.md",
    "tasks": "tasks.md",
}


def read_evolution_items(project_root, project_filter=None) -> list:
    """读 ``.fenix/evolution/items.jsonl`` 生成摘要列表（6.4）。

    摘要字段：id / project / date_section / section / title / 三项判定 /
    status / has_draft（草稿目录是否存在）/ spec_name / created_at /
    decided_at / doc_source。

    ``doc_source`` 取值：``"draft"``（草稿目录存在）、``"spec"``（草稿不存在
    但 spec_name 能解析出 SPEC 目录）、``None``（两者皆无）。前端据此决定
    「查看」弹窗是否渲染文档页签。

    按 created_at 倒序；文件缺失返回空列表；单行 JSON 损坏由
    read_items 容错跳过（MUST NOT 让整个列表 500）。
    """
    from core.evolution import (
        read_items,
        draft_dir,
        resolve_accepted_spec_dir,
    )

    items = read_items(project_root)
    out = []
    for rec in items.values():
        if not isinstance(rec, dict):
            continue
        if project_filter and rec.get("project") != project_filter:
            continue
        eid = rec.get("id")
        has_draft = bool(eid) and draft_dir(project_root, str(eid)).is_dir()
        if has_draft:
            doc_source = "draft"
        elif (
            rec.get("spec_name")
            and resolve_accepted_spec_dir(project_root, str(rec["spec_name"])) is not None
        ):
            doc_source = "spec"
        else:
            doc_source = None
        out.append(
            {
                "id": eid,
                "project": rec.get("project"),
                "date_section": rec.get("date_section"),
                "section": rec.get("section"),
                "title": rec.get("title"),
                "verdict": rec.get("verdict"),
                "status": rec.get("status"),
                "has_draft": has_draft,
                "spec_name": rec.get("spec_name"),
                "doc_source": doc_source,
                "created_at": rec.get("created_at"),
                "decided_at": rec.get("decided_at"),
            }
        )
    out.sort(key=lambda x: (x.get("created_at") or ""), reverse=True)
    return out


def read_evolution_analysis(project_root, item_id_) -> dict:
    """读取某条目的分析结论全文（6.5）。

    返回 ``{"found": True, "content": analysis_md}`` 或
    ``{"not_found": True}``（item_id 未知 → 端点 404）。
    """
    from core.evolution import read_items

    items = read_items(project_root)
    rec = items.get(item_id_)
    if rec is None:
        return {"not_found": True}
    return {"found": True, "content": rec.get("analysis_md") or ""}


def read_evolution_draft(project_root, item_id_, doc) -> dict:
    """读取草稿文档（6.5），草稿优先、SPEC 位置回退（evo-item-retention-doc-tracking D6）。

    - ``doc`` 非白名单 → ``{"invalid_doc": True}``（端点 400，MUST NOT 读取
      草稿目录与 SPEC 目录之外的任何文件）；
    - ``item_id`` 未知 → ``{"not_found": True}``（端点 404）；
    - 草稿目录内目标文件存在 → 读草稿（既有行为不变，``pending`` 等条目零
      影响）；草稿缺失但条目记录含 ``spec_name`` 时，以 ``spec_name`` 为权威
      名解析 SPEC 目录（活跃 ``spec/changes/<spec_name>/`` 优先、归档
      ``spec/archive/`` 回退），从该目录读取对应文档——使已被同意立项、草稿
      已随接受删除的条目仍可查看其文档（spec 文档取
      ``specs/<capability>/spec.md``，capability 取条目记录 spec.capability，
      缺失时回退到唯一的能力子目录）；
    - 两条路径均无该文档 → ``{"found": False}``（端点 200 + 空态）。

    读取路径 MUST 由 item_id / spec_name 推导；解析后的目标路径 MUST 仍位于
    所解析目录内（草稿：``_safe_draft_dir`` 校验；SPEC：``is_relative_to``
    校验），越界一律拒绝（返回 ``invalid_doc``），MUST NOT 接受任意路径参数。
    """
    from core.evolution import (
        read_items,
        _safe_draft_dir,
        resolve_accepted_spec_dir,
    )

    if doc not in EVOLUTION_DOC_WHITELIST:
        return {"invalid_doc": True}
    items = read_items(project_root)
    rec = items.get(item_id_)
    if rec is None:
        return {"not_found": True}

    def _read_target(target: Path, base: Path) -> dict:
        """目标文件读取（含越界校验）；base 为解析后目录。"""
        resolved = target.resolve()
        if not resolved.is_relative_to(base.resolve()):
            return {"invalid_doc": True}
        if not resolved.is_file():
            return {"found": False}
        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError:
            return {"found": False}
        return {"found": True, "content": content}

    def _record_capability(rec: dict) -> str:
        """提取条目记录的 spec.capability（非 dict 或缺失时返回空串）。"""
        spec = rec.get("spec") if isinstance(rec.get("spec"), dict) else None
        return (spec.get("capability") or "") if spec else ""

    # 1. 草稿目录优先（既有行为）
    d = _safe_draft_dir(project_root, item_id_)
    if d is not None and d.is_dir():
        if doc == "spec":
            capability = _record_capability(rec)
            # capability 为空时令 rel 落空（跳过草稿读取、走 SPEC 回退），与
            # SPEC 回退路径的空值处理对齐，避免构造出 specs//spec.md 双斜杠路径
            rel = f"specs/{capability}/spec.md" if capability else None
        else:
            rel = EVOLUTION_DOC_FILES[doc]
        if rel is not None:
            result = _read_target(d / rel, d)
            if result.get("found") or result.get("invalid_doc"):
                return result

    # 2. SPEC 位置回退：草稿缺失但条目记录含 spec_name
    if rec.get("spec_name"):
        spec_dir = resolve_accepted_spec_dir(project_root, str(rec["spec_name"]))
        if spec_dir is not None:
            if doc == "spec":
                # capability 取条目记录 spec.capability；缺失或目录不存在时
                # 回退到唯一的能力子目录
                capability = _record_capability(rec)
                if capability:
                    sub = spec_dir / "specs" / capability
                    if sub.is_dir():
                        rel = f"specs/{capability}/spec.md"
                    else:
                        rel = None
                else:
                    rel = None
                if rel is None:
                    try:
                        caps = (
                            sorted(p.name for p in (spec_dir / "specs").iterdir() if p.is_dir())
                            if (spec_dir / "specs").is_dir()
                            else []
                        )
                    except OSError:
                        caps = []  # 目录扫描期 IO/权限错误降级为空态，与 _read_target 一致
                    if len(caps) == 1:
                        rel = f"specs/{caps[0]}/spec.md"
                    else:
                        # <capability> 子目录不存在已由上方 is_dir 判定，无第三种
                        # 解析来源，直接落空态（与函数底部返回同形），不再构造
                        # 注定读不到的 rel 路径
                        return {"found": False}
            else:
                rel = EVOLUTION_DOC_FILES[doc]
            result = _read_target(spec_dir / rel, spec_dir)
            if result.get("found") or result.get("invalid_doc"):
                return result

    return {"found": False}
