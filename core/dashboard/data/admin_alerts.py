"""core.dashboard.data.admin_alerts — Administrator 告警/处置记录读取（admin_alerts 组）。

refactor-dashboard-data-module D3 分组：本模块承载 admin 告警职责域。
读取/标记升级告警、告警摘要、运维活动记录。
"""

# ── Administrator 告警（.fenix/admin_alerts.json） ─────────────────


def _merge_narrative_sidecars(project_root, records: list) -> list:
    """按 alert_id 合并叙事侧车（upgrade-narrative-to-investigation 3.3）。

    补叙异步生成后落 ``.fenix/admin_alerts_narrative/<alert_id>.json`` 侧车
    （admin_alerts.json 记录本体不可变）；本助手在告警读出后按 id 合并回
    ``narrative`` 字段，形态与既有 ``{"text", "model", "at"}`` 一致——前端
    AlertNarrative 零 schema 变更。终态侧车（生成失败/熔断跳过）与补叙侧车
    同构同目录，读侧无差别合并（失败告警渲染失败说明而非悬挂占位）。

    侧车缺失（无补叙也无终态侧车）且未 handled 的裁决类告警（choices 非空
    ——叙事覆盖面口径，桶 0 无 choices 本就不生成）附 ``narrative_pending:
    True`` 供前端渲染「调查生成中」占位。单条合并永不抛出；侧车目录缺失/
    损坏条目 fail-open 跳过。
    """
    if not records:
        return records
    try:
        from core.adjudication_narrative import load_narrative_sidecars

        sidecars = load_narrative_sidecars(project_root)
    except Exception:
        sidecars = {}
    merged: list = []
    for rec in records:
        if not isinstance(rec, dict):
            merged.append(rec)
            continue
        item = dict(rec)
        payload = sidecars.get(str(item.get("id") or ""))
        if payload:
            item["narrative"] = {
                "text": payload.get("text") or "",
                "model": payload.get("model"),
                "at": payload.get("at") or "",
            }
            item.pop("narrative_pending", None)
        elif not item.get("handled") and item.get("choices"):
            item["narrative_pending"] = True
        merged.append(item)
    return merged


def get_alerts(project_root) -> list:
    """读取项目全部 Administrator 告警/处置记录（最新在前）。缺失/损坏返回 []。

    返回前合并叙事侧车（upgrade-narrative-to-investigation 3.3）：含补叙
    narrative 字段与未完成告警的 narrative_pending 占位标记。
    """
    from core.admin_store import AdminStore

    return _merge_narrative_sidecars(project_root, AdminStore(project_root).read_all())


def get_unhandled_alerts(project_root) -> list:
    """读取项目未处理的升级告警（最新在前）。含叙事侧车合并（3.3）。"""
    from core.admin_store import AdminStore

    return _merge_narrative_sidecars(project_root, AdminStore(project_root).unhandled())


def get_resolved_alerts(project_root, limit: int = 50) -> list:
    """读取项目已处理的升级告警（最新在前，add-alert-auto-resolve D5）。

    供管理员视图「已解决」折叠区展示：含 handled_by（区分自动解决/人工处理）、
    resolve_note（解除/处置依据）与 handled_at。仍走 AdminStore.read_all 既有
    读取路径（不绕锁、不改存储格式）。已解决告警同样合并侧车 narrative
    （历史完整性：人工已处置后补叙照常落盘，3.2）。
    """
    from core.admin_store import AdminStore, ESCALATION

    resolved = [
        r
        for r in AdminStore(project_root).read_all()
        if r.get("kind") == ESCALATION and r.get("handled")
    ]
    return _merge_narrative_sidecars(project_root, resolved[:limit])


def mark_alert_handled(project_root, alert_id: str) -> bool:
    """标记某条告警为已处理。返回是否找到并更新。

    按 kind 分派（code-review item 08f4820799eb）：ESCALATION 走
    ``mark_handled``（既有人工告警闭环锚点），SIGNAL 走
    ``mark_signal_handled``——alert-resolve 对不可裁决信号的 400 文案指引
    「标记已处理」（POST /api/alerts/<id>/handled），旧实现仅匹配
    ESCALATION，对 SIGNAL 记录恒 False → 404，形成处置死胡同。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root)
    alert = next((r for r in store.read_all() if r.get("id") == alert_id), None)
    if alert is None:
        return False
    if alert.get("kind") == SIGNAL:
        return store.mark_signal_handled(alert_id)
    return store.mark_handled(alert_id)


def mark_all_alerts_handled(project_root) -> int:
    """将项目所有未处理升级告警标记为已处理。返回处理数量。"""
    from core.admin_store import AdminStore

    return AdminStore(project_root).mark_all_handled()


def alerts_summary(project_root) -> dict:
    """项目告警摘要：{unhandled_count, max_severity, latest}。

    max_severity 取未处理告警中最高严重度（critical > major > minor）；
    latest 为最新一条未处理告警。无未处理时三者为空/0。
    """
    unhandled = get_unhandled_alerts(project_root)
    if not unhandled:
        return {"unhandled_count": 0, "max_severity": None, "latest": None}
    sev_rank = {"critical": 3, "major": 2, "minor": 1}
    top = max(unhandled, key=lambda a: sev_rank.get(a.get("severity"), 0))
    return {
        "unhandled_count": len(unhandled),
        "max_severity": top.get("severity"),
        "latest": unhandled[0],
    }


def get_admin_activities(project_root, spec=None) -> list:
    """返回 Administrator 处置活动记录（运维记录时间线数据源）。

    从 admin_alerts.json 过滤 kind=disposition，按时间倒序；与未处理升级
    escalation 关联（同 admin_run_id）的记录置顶，并标记 handled=False +
    escalation_id（供前端 mark-handled）。旧记录无 summary 时原样返回，
    界面降级显示结构化字段（design D1，向后兼容）。

    spec 非空时（add-admin-invoke-dialog）在归并/置顶逻辑完成后按
    `rec.get("spec") == spec` 过滤，仅返回该 SPEC 相关记录（置顶语义先于
    过滤生效，保证未处理升级置顶后仍被正确过滤）。
    """
    from core.admin_store import AdminStore, DISPOSITION, ESCALATION

    records = AdminStore(project_root).read_all()

    # 未处理升级 → 关联 disposition（按 admin_run_id 匹配）
    unhandled_by_run: dict = {}
    for rec in records:
        if rec.get("kind") == ESCALATION and not rec.get("handled") and rec.get("admin_run_id"):
            unhandled_by_run.setdefault(rec["admin_run_id"], rec.get("id"))

    activities = []
    # 按 admin_run_id 归并：pending 是 admin 唤起时的标记记录，同 run 一旦产生
    # 最终 disposition（result != pending）即以最终为准，避免页面出现"永久处置中"。
    best_by_run: dict = {}
    for rec in records:
        if rec.get("kind") != DISPOSITION:
            continue
        rid = rec.get("admin_run_id") or f"run-{id(rec)}"
        # status 优先与单源 _merge_admin_runs（core/admin_monitor.py，勿二次漂移）一致；
        # timeline.py 的同款归并副本同此约定。
        status = rec.get("status") or rec.get("result")
        is_pending = status == "pending"
        existing = best_by_run.get(rid)
        if existing is None:
            best_by_run[rid] = (is_pending, rec)
            continue
        # 非 pending 优先于 pending；同为非 pending 取最新
        if is_pending and not existing[0]:
            continue
        if not is_pending and existing[0]:
            best_by_run[rid] = (False, rec)
        elif (rec.get("created") or "") > (existing[1].get("created") or ""):
            best_by_run[rid] = (is_pending, rec)

    for _is_pending, rec in best_by_run.values():
        item = dict(rec)
        esc_id = unhandled_by_run.get(rec.get("admin_run_id"))
        item["handled"] = esc_id is None
        item["escalation_id"] = esc_id
        item["actions_taken"] = rec.get("actions_taken") or rec.get("action_taken") or ""
        item["_pin"] = esc_id is not None
        activities.append(item)

    # 未处理升级关联置顶，组内按时间倒序
    activities.sort(key=lambda a: (a["_pin"], a.get("created") or ""), reverse=True)
    for a in activities:
        a.pop("_pin", None)

    # add-admin-invoke-dialog：可选 spec 过滤（置顶语义先行，过滤后生效）
    if spec is not None:
        activities = [a for a in activities if a.get("spec") == spec]

    return activities


def get_archived_activities(project_root, spec=None) -> list:
    """读取归档的处置/告警记录（add-alerts-archive-and-overview-cache 2.1）。

    逐行读 `.fenix/admin_alerts_archive.jsonl`（JSONL，每行一条完整记录；
    存储原序即时间正序），损坏行容错跳过；按 created 时间倒序返回。spec
    非空时仅返回该 SPEC 相关记录。不与活跃 admin_alerts.json 合并——归档
    数据不进入任何缺省读路径（读侧时间线语义不变），仅经 `archived=1`
    出口消费。缺失/不可读返回 []。
    """
    from core.admin_store import AdminStore

    records = AdminStore(project_root).read_archive()
    if spec is not None:
        records = [r for r in records if r.get("spec") == spec]
    # or ""：对 "created": null 设防，避免 None 与 str 比较抛 TypeError
    records.sort(key=lambda r: r.get("created") or "", reverse=True)
    return records
