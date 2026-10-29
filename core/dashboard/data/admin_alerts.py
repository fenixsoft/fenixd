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
        elif (
            not item.get("handled")
            and item.get("choices")
            and not item.get("narrative")
        ):
            # 侧车缺失且本体已带 narrative 的存量告警（旧同步实现写入）不标
            # pending——已有叙事可渲染，标了即是「生成中」假态
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


def _unhandled_records(records: list) -> list:
    """未处理升级告警过滤单点（kind=escalation 且未 handled，最新在前）。

    AdminStore.unhandled 同款过滤在**已读记录**上的单点复刻：单函数读路径
    （get_unhandled_alerts）与 alerts_overview 单读聚合共用（code-review
    item d3d6a32a1091，聚合路径免对同项目二次全量读盘）；口径变更须与
    AdminStore.unhandled 同步。
    """
    from core.admin_store import ESCALATION

    return [
        r for r in records if r.get("kind") == ESCALATION and not r.get("handled")
    ]


def get_unhandled_alerts(project_root) -> list:
    """读取项目未处理的升级告警（最新在前）。含叙事侧车合并（3.3）。"""
    from core.admin_store import AdminStore

    return _merge_narrative_sidecars(
        project_root, _unhandled_records(AdminStore(project_root).read_all())
    )


def _resolved_records(records: list) -> list:
    """已处理告警过滤单点（ESCALATION 全量 + 自愈收口 SIGNAL，最新在前）。

    get_resolved_alerts docstring 的 5.3 口径（handled 且 kind=escalation，
    或 kind=signal 且 handled_by="auto-self-heal"——人工 mark_signal_handled
    的信号不进本视图）在**已读记录**上的单点实现：单函数读路径与
    alerts_overview 单读聚合共用（code-review item d3d6a32a1091）。
    """
    from core.admin_store import AUTO_SELF_HEAL_BY, ESCALATION, SIGNAL

    return [
        r
        for r in records
        if r.get("handled")
        and (
            r.get("kind") == ESCALATION
            or (r.get("kind") == SIGNAL and r.get("handled_by") == AUTO_SELF_HEAL_BY)
        )
    ]


def get_resolved_alerts(project_root, limit: int = 50) -> list:
    """读取项目已处理的升级告警（最新在前，add-alert-auto-resolve D5）。

    供管理员视图「已解决」折叠区展示：含 handled_by（区分自动解决/人工处理/
    已自愈）、resolve_note（解除/处置依据）与 handled_at。仍走
    AdminStore.read_all 既有读取路径（不绕锁、不改存储格式）。已解决告警同样
    合并侧车 narrative（历史完整性：人工已处置后补叙照常落盘，3.2）。

    add-alert-self-heal-marking 5.3：自愈收口的 signal 条目一并透出（
    handled_by="auto-self-heal" 才纳入——人工 mark_signal_handled 的信号不进
    本视图，不扩既有语义），配合待处理视图的既有 handled 过滤实现「待处理
    不再出现已自愈条目、已处理视图自然收纳」。
    """
    from core.admin_store import AdminStore

    return _merge_narrative_sidecars(
        project_root, _resolved_records(AdminStore(project_root).read_all())[:limit]
    )


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


def _summary_from_unhandled(unhandled: list) -> dict:
    """告警摘要派生单点：{unhandled_count, max_severity, latest}。

    alerts_summary 与 alerts_overview 单读聚合共用（code-review item
    d3d6a32a1091）；语义与拆分前逐字段一致。
    """
    if not unhandled:
        return {"unhandled_count": 0, "max_severity": None, "latest": None}
    sev_rank = {"critical": 3, "major": 2, "minor": 1}
    # str(...) or ""：severity 脏形态（列表/对象等不可哈希值）查表前归一，
    # 与 command_center._SEVERITY_RANK 消费点同口径
    top = max(unhandled, key=lambda a: sev_rank.get(str(a.get("severity") or ""), 0))
    return {
        "unhandled_count": len(unhandled),
        "max_severity": top.get("severity"),
        "latest": unhandled[0],
    }


def alerts_summary(project_root) -> dict:
    """项目告警摘要：{unhandled_count, max_severity, latest}。

    max_severity 取未处理告警中最高严重度（critical > major > minor）；
    latest 为最新一条未处理告警。无未处理时三者为空/0。
    """
    return _summary_from_unhandled(get_unhandled_alerts(project_root))


def alerts_overview(project_root, resolved_limit: int = 50) -> dict:
    """按项目单读聚合入口：一次 read_all 派生 summary/unhandled/resolved 三视图。

    为 ``_api_alerts`` 缺省跨项目聚合分支而设（code-review item
    d3d6a32a1091）：此前该分支对每个项目先后调用 alerts_summary /
    get_unhandled_alerts / get_resolved_alerts，三者各自独立读同一
    admin.jsonl，一次请求产生 3×项目数 次全量文件读。本入口只读一次，
    在同一份记录列表上经既有过滤/摘要助手（_unhandled_records /
    _resolved_records / _summary_from_unhandled）派生三视图，与单函数
    读路径逐字段同语义；叙事侧车合并同样只做一次。

    返回 ``{"summary": …, "unhandled": […], "resolved": […]}``；resolved
    截断上限与 get_resolved_alerts 缺省一致（resolved_limit=50，先过滤
    后截断）。注意 summary["latest"] 与 unhandled[0] 为同一记录对象
    （序列化结果不受影响）。
    """
    from core.admin_store import AdminStore

    merged = _merge_narrative_sidecars(
        project_root, AdminStore(project_root).read_all()
    )
    unhandled = _unhandled_records(merged)
    return {
        "summary": _summary_from_unhandled(unhandled),
        "unhandled": unhandled,
        "resolved": _resolved_records(merged)[:resolved_limit],
    }


def merge_dispositions_by_run(records) -> dict:
    """DISPOSITION 记录按 admin_run_id 挑代表记录（best_by_run 归并单点）。

    「pending 让位于非 pending、同态取 created 最新」的归并本体此前在
    get_admin_activities 与 timeline._admin_events_for_spec 各有一份逐行
    副本（code-review item 55336c2a40af 收敛为本单点，两视图共同委托，
    勿再复制第二份）；status 优先口径与单源 _merge_admin_runs
    （core/admin_monitor.py）一致。

    规则：pending 是 admin 唤起时的标记记录，同 run 一旦产生最终
    disposition（status/result != "pending"）即以最终为准（避免界面出现
    「永久处置中」）；同为非 pending（或同为 pending）取 created 最新
    （字典序即时间序，写侧 UTC 单一后缀族）；无 admin_run_id 的记录以
    ``f"run-{id(rec)}"`` 独立成组；非 DISPOSITION 记录跳过。

    返回 ``{admin_run_id: (is_pending, rec)}``——消费方式两视图各异：
    运维记录页逐组取 rec 造 item；SPEC 时间轴按记录原序以
    ``best_by_run[rid][1] is rec`` 过滤被替代的旧记录。置顶/_pin 与
    spec 过滤等视图差异留在各消费方，不入本助手。
    """
    from core.admin_store import DISPOSITION

    best_by_run: dict = {}
    for rec in records:
        if rec.get("kind") != DISPOSITION:
            continue
        rid = rec.get("admin_run_id") or f"run-{id(rec)}"
        # status 优先与单源 _merge_admin_runs（core/admin_monitor.py）一致
        status = rec.get("status") or rec.get("result")
        is_pending = status == "pending"
        existing = best_by_run.get(rid)
        if existing is None:
            best_by_run[rid] = (is_pending, rec)
            continue
        # 非 pending 优先于 pending；同态取 created 最新
        if is_pending and not existing[0]:
            continue
        if not is_pending and existing[0]:
            best_by_run[rid] = (False, rec)
        # [fenix-ignore:e40a6011ce77] created 写侧恒一：AdminStore 三个写口共用 _normalize_entry 的 setdefault("created", _utcnow_iso())（UTC +00:00 单一后缀族），全部写入点核实无显式传值/改写，同后缀族字典序即时间序
        # str(...) or ""：对 created 脏形态（数字等）与字符串同批混排设防，
        # 与 AdminStore.read_all 同口径，避免异类型比较抛 TypeError
        elif str(rec.get("created") or "") > str(existing[1].get("created") or ""):
            best_by_run[rid] = (is_pending, rec)
    return best_by_run


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
    from core.admin_store import AdminStore, ESCALATION

    records = AdminStore(project_root).read_all()

    # 未处理升级 → 关联 disposition（按 admin_run_id 匹配）
    unhandled_by_run: dict = {}
    for rec in records:
        if rec.get("kind") == ESCALATION and not rec.get("handled") and rec.get("admin_run_id"):
            unhandled_by_run.setdefault(rec["admin_run_id"], rec.get("id"))

    activities = []
    # 按 admin_run_id 归并：pending 让位于非 pending、同态取 created 最新，
    # 避免页面出现"永久处置中"（归并本体单源 merge_dispositions_by_run，
    # SPEC 时间轴 admin 节点同款委托，勿在此复制第二份）。
    best_by_run = merge_dispositions_by_run(records)

    for _is_pending, rec in best_by_run.values():
        item = dict(rec)
        esc_id = unhandled_by_run.get(rec.get("admin_run_id"))
        item["handled"] = esc_id is None
        item["escalation_id"] = esc_id
        item["actions_taken"] = rec.get("actions_taken") or rec.get("action_taken") or ""
        item["_pin"] = esc_id is not None
        # add-harness-brand-projection 3.2：admin 车道 run 的品牌透出（与 runs
        # 列表同口径：run_metrics 旁路行的 harness 键，经 load_run_metric 双源
        # 查找）；存量记录/指标行缺键时不下发，前端走回退链缺省 claude。
        admin_run_id = rec.get("admin_run_id")
        if admin_run_id:
            from core.dashboard.data.runs import load_run_metric

            try:
                metric = load_run_metric(project_root, str(admin_run_id))
            except (OSError, ValueError):
                metric = None
            if metric and metric.get("harness"):
                item["harness"] = str(metric["harness"])
        activities.append(item)

    # 未处理升级关联置顶，组内按时间倒序
    activities.sort(
        key=lambda a: (a["_pin"], str(a.get("created") or "")), reverse=True
    )
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
    # str(...) or ""：对 created 脏形态（null/数字等）设防，与 read_all 同口径
    records.sort(key=lambda r: str(r.get("created") or ""), reverse=True)
    return records
