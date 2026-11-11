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


def _auto_exec_grace_minutes(project_root) -> int:
    """auto_exec.grace_minutes 读侧解析（fail-open 回落缺省 30 分钟）。

    倒计时下发用的窗口宽即策略引擎判定所用的同一配置单源
    （ConfigLoader.get_auto_exec_config）；解析失败按缺省兜底——视图是
    观测面，配置不可读不得让告警读路径 5xx。
    """
    try:
        from pathlib import Path

        from core.config import ConfigLoader

        cfg = ConfigLoader.get_auto_exec_config(
            ConfigLoader.resolve_config(Path(project_root))
        )
        return int(cfg.get("grace_minutes") or 30)
    except Exception:
        return 30


def _merge_auto_exec_fields(records: list, grace_minutes: int) -> list:
    """读时合并自动执行投影（add-adjudication-auto-exec 5.1，无 schema 变更）。

    每条 ESCALATION 记录附 ``auto_exec`` 投影（复用策略引擎读侧单点
    ``auto_exec_projection``）：``executed``（handled_by=auto-policy →
    前端「自动执行」徽标派生键，与人工闭环不混同）、
    ``recommended_choice``/``risk_tier``（推荐明确性与档位徽标）、
    ``anchor_at``/``due_at``（grace 否决窗倒计时，锚=推荐落账时刻）、
    ``skip_reason``（推荐不明确说明）；另附 ``created_at``（记录 created
    透传，前端现值时间基准）。非 escalation 记录不附（处置/信号记录无
    自动执行语义，载荷不膨胀）；单条投影异常 fail-open 置 None（前端按
    无投影渲染，读路径不 5xx）。
    """
    from core.admin_auto_exec import auto_exec_projection
    from core.admin_store import ESCALATION

    out: list = []
    for rec in records:
        if not isinstance(rec, dict):
            out.append(rec)
            continue
        item = dict(rec)
        if item.get("kind") == ESCALATION:
            try:
                proj = auto_exec_projection(item, grace_minutes=grace_minutes)
                proj["created_at"] = str(item.get("created") or "")
                item["auto_exec"] = proj
            except Exception:
                item["auto_exec"] = None
        out.append(item)
    return out


def get_alerts(project_root) -> list:
    """读取项目全部 Administrator 告警/处置记录（最新在前）。缺失/损坏返回 []。

    返回前合并叙事侧车（upgrade-narrative-to-investigation 3.3）：含补叙
    narrative 字段与未完成告警的 narrative_pending 占位标记；ESCALATION
    记录另附自动执行投影 ``auto_exec``（add-adjudication-auto-exec 5.1，
    徽标与 grace 倒计时派生键）。
    """
    from core.admin_store import AdminStore

    return _merge_auto_exec_fields(
        _merge_narrative_sidecars(project_root, AdminStore(project_root).read_all()),
        _auto_exec_grace_minutes(project_root),
    )


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
    """读取项目未处理的升级告警（最新在前）。含叙事侧车合并（3.3）与
    自动执行投影（add-adjudication-auto-exec 5.1，grace 倒计时数据源）。"""
    from core.admin_store import AdminStore

    return _merge_auto_exec_fields(
        _merge_narrative_sidecars(
            project_root, _unhandled_records(AdminStore(project_root).read_all())
        ),
        _auto_exec_grace_minutes(project_root),
    )


def _resolved_records(records: list) -> list:
    """已处理告警过滤单点（ESCALATION 全量 + 自动化收口 SIGNAL，最新在前）。

    get_resolved_alerts docstring 的 5.3 口径（handled 且 kind=escalation，
    或 kind=signal 且 handled_by 属自动化收口词表——人工 mark_signal_handled
    的信号不进本视图）在**已读记录**上的单点实现：单函数读路径与
    alerts_overview 单读聚合共用（code-review item d3d6a32a1091）。

    add-provider-validation-alert-governance 4.3：自动化收口词表扩入
    ``superseded``（同根因批量失效标记）——已失效告警进「已解决」折叠区
    呈现（携带失效注记与撤销入口），而非从面板凭空消失（误失效不可见即
    不可纠错）。
    """
    from core.admin_store import AUTO_SELF_HEAL_BY, ESCALATION, SIGNAL, SUPERSEDED_BY

    return [
        r
        for r in records
        if r.get("handled")
        and (
            r.get("kind") == ESCALATION
            or (
                r.get("kind") == SIGNAL
                and r.get("handled_by") in (AUTO_SELF_HEAL_BY, SUPERSEDED_BY)
            )
        )
    ]


def get_resolved_alerts(project_root, limit: int = 50) -> list:
    """读取项目已处理的升级告警（最新在前，add-alert-auto-resolve D5）。

    供管理员视图「已解决」折叠区展示：含 handled_by（区分自动解决/人工处理/
    已自愈）、resolve_note（解除/处置依据）与 handled_at；ESCALATION 记录
    另附自动执行投影（add-adjudication-auto-exec 5.1，``executed`` 徽标供
    已解决区区分机器执行与人工处置）。仍走
    AdminStore.read_all 既有读取路径（不绕锁、不改存储格式）。已解决告警同样
    合并侧车 narrative（历史完整性：人工已处置后补叙照常落盘，3.2）。

    add-alert-self-heal-marking 5.3：自愈收口的 signal 条目一并透出（
    handled_by="auto-self-heal" 才纳入——人工 mark_signal_handled 的信号不进
    本视图，不扩既有语义），配合待处理视图的既有 handled 过滤实现「待处理
    不再出现已自愈条目、已处理视图自然收纳」。
    """
    from core.admin_store import AdminStore

    return _merge_auto_exec_fields(
        _merge_narrative_sidecars(
            project_root, _resolved_records(AdminStore(project_root).read_all())[:limit]
        ),
        _auto_exec_grace_minutes(project_root),
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


def revert_superseded_alert(project_root, alert_id: str) -> bool:
    """人工撤销 superseded 失效标记，恢复未处理态（task 4.3 撤销入口）。

    直通 ``AdminStore.revert_supersede``（仅 handled_by=superseded 的记录
    生效，其余终态拒回退——判定在 store 单点）。返回是否撤销成功。
    """
    from core.admin_store import AdminStore

    return AdminStore(project_root).revert_supersede(alert_id)


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

    直连 read_all + _unhandled_records + _summary_from_unhandled，不经
    get_unhandled_alerts 的叙事侧车合并（code-review item 90e30c16a030）：
    摘要只消费 count/severity/latest，合并出的 narrative/narrative_pending
    本就被丢弃，Dashboard 高频轮询无需为此扫描侧车目录。
    """
    from core.admin_store import AdminStore

    return _summary_from_unhandled(
        _unhandled_records(AdminStore(project_root).read_all())
    )


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


def _chain_subject(signature: str) -> dict:
    """链签名 → 归组投影（add-escalation-chain-admin-arbiter 5.2）。

    三形态（chain_signature 单源）：``<spec>::<信号>``（spec 粒度）、
    ``null:<主体键>::<信号>``（spec=null 主体键粒度）、``global::<信号>``
    （类型级退化）。返回 ``{"spec", "subject", "granularity"}``——视图按
    签名本身归组，本投影只提供展示字段（spec=null 按主体键展示）。
    """
    head = str(signature or "").split("::", 1)[0]
    if head.startswith("null:"):
        return {
            "spec": "",
            "subject": head[len("null:"):],
            "granularity": "subject",
        }
    if head == "global":
        return {"spec": "", "subject": "", "granularity": "type"}
    return {"spec": head, "subject": "", "granularity": "spec"}


def _safe_int(v) -> int:
    """宽松 int 归一（损坏值归 0，链视图 fail-open 口径）。

    与 summary._int_or_zero / timeline 重派计数同款兜底（code-review item
    262689521310）：load_chain_state 只做 dict() 保真不归一值类型，状态
    文件值被手改/半损坏为非数值真值（or 0 挡不住）时裸 int() 抛
    ValueError/TypeError 会让视图 5xx，违背观测面 fail-open 承诺——归 0。
    """
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return 0


def _chain_run_id_index(project_root) -> dict:
    """链台账事件 chain_id → 最新非空 run_id（在办件 run 标识联查）。

    redesign-chain-panel-ui 1.1：链在办件登记（mark_in_flight）仅五字段
    无 run 标识；run_id 从链上下文**尽力提取**——链事件台账（
    load_arbiter_ledger 单源读侧，kind=chain-* 五段事件自带 run_id，
    admin 相=admin run id、arbiter 相=arbiter_run_id）按 chain_id 归并，
    append-only 后写覆盖即最新事件。

    台账读取/解析任何异常 fail-open 返回空索引（run 标识缺失前端显「—」，
    不阻断视图，亦不伪 0）。
    """
    try:
        from core.pm_engine.arbiter import load_arbiter_ledger

        entries = load_arbiter_ledger(project_root)
    except Exception:
        return {}
    best: dict = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        if not str(e.get("kind") or "").startswith("chain-"):
            continue
        cid = str(e.get("chain_id") or "")
        rid = str(e.get("run_id") or "")
        if cid and rid:
            best[cid] = rid
    return best


def chain_overview(project_root) -> dict:
    """处置链单读聚合（add-escalation-chain-admin-arbiter 5.2，只读）。

    为 Dashboard 处置链视图而设：一次读齐链状态文件与 admin 告警存储两源
    （配额上限即时解析项目级配置，与链头热更新同源），派生四视图——

    - ``in_flight``：链在办件（admin_monitor 兜底看护同源，phase=admin/arbiter；
      redesign-chain-panel-ui 1.1 富化——problem 摘要/配额计数/run 标识，
      见下方富化段注记）；
    - ``signatures``：配额水位（逐签名 attempts/rulings + cap + exhausted
      标记；redesign-chain-panel-ui 附 esc_total/esc_pending 链上结果计数）；
    - ``escalations``：链关联上升件全量（链终点直写、携带 ``chain.signature``
      关联键；含已收口，close_cause=closed-by-chain/migrated 区分）；
    - ``queue``：未收口上升件（escalations 的未 handled 子集，人工队列）。

    fail-open：状态文件缺失/损坏按空态派生（load_chain_state 兜底）、配置
    解析失败回落缺省 cap（quota_config 同语义）、admin 存储读失败上升件置
    空——视图是观测面，读路径异常不得反向扰动链运行，也不得让页面 5xx。

    spec=null 信号按主体键归组：签名即归组键，signatures 条目附 subject
    投影（_chain_subject）供前端在无 spec 归属时按主体键展示。

    redesign-chain-panel-ui 1.1 在办富化（D2 后端下发，前端零联查）：每件
    在办附 ``problem``（同签名最近上升件 description 截断 160 字符，无上升
    件 None）、``admin_attempts_used``/``admin_cap``/``arbiter_rulings``/
    ``arbiter_cap``（链状态文件签名条目联查；签名无计数条目时 used 置
    None——前端显「—」不伪 0）、``run_id``（链台账事件按 chain_id 联查
    _chain_run_id_index，admin 相回落同 spec 最新 pending disposition 的
    admin_run_id，均不可得 None）。联查询数据缺失一律置 None 不阻断视图。
    signatures 条目附 ``esc_total``/``esc_pending``（同签名上升件总数与
    待人工数，spec 分组组头聚合与链上结果标签的联查基础）。
    """
    from core.admin_store import AdminStore
    from core.pm_engine.escalation_chain import ChainQuotaStore, load_chain_state

    state = load_chain_state(project_root)
    cfg = ChainQuotaStore(project_root).quota_config()
    admin_cap = int(cfg.get("admin_attempts") or 0)
    arbiter_cap = int(cfg.get("arbiter_rulings") or 0)
    in_flight = [dict(x) for x in state["in_flight"]]

    # 上升件读取提前到 signatures 构建前：在办 problem 摘要、签名 esc 计数
    # 两组联查（redesign-chain-panel-ui 1.1）都以 escalations 为数据基础，
    # 单次 read_all 派生全部视图（读失败置空，四视图空态不变）
    escalations = []
    try:
        records = AdminStore(project_root).read_all()
    except Exception:
        records = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        chain_ref = rec.get("chain")
        if not isinstance(chain_ref, dict) or not str(chain_ref.get("signature") or ""):
            continue
        escalations.append(dict(rec))
    # 自动执行投影（add-adjudication-auto-exec 5.1）：链上升件行附
    # ``auto_exec``（executed 徽标 / grace 倒计时 / 推荐档位），queue 为
    # escalations 同对象子集自然继承。投影异常单条置 None 不阻断视图
    # （观测面 fail-open，同本函数既有联查口径）。
    try:
        from core.admin_auto_exec import auto_exec_projection

        _grace = _auto_exec_grace_minutes(project_root)
        for row in escalations:
            try:
                proj = auto_exec_projection(row, grace_minutes=_grace)
                proj["created_at"] = str(row.get("created") or "")
                row["auto_exec"] = proj
            except Exception:
                row["auto_exec"] = None
    except Exception:
        pass
    queue = [r for r in escalations if not r.get("handled")]

    # 同签名链上结果计数与 problem 摘要索引（redesign-chain-panel-ui 1.1）：
    # esc 计数=escalations 逐条归桶；problem 取该签名**最近**上升件描述
    # （created 字符串比较取最大——脏值按空串比较兜底，仅求可判定先后），
    # 截断 160 字符（行卡 2 行 clamp 的摘要形态，前端不做二次截断）
    esc_stats: dict = {}
    problem_idx: dict = {}
    for r in escalations:
        chain_ref = r.get("chain")
        sig = (
            str(chain_ref.get("signature") or "")
            if isinstance(chain_ref, dict)
            else ""
        )
        if not sig:
            continue
        st = esc_stats.setdefault(sig, {"esc_total": 0, "esc_pending": 0})
        st["esc_total"] += 1
        if not r.get("handled"):
            st["esc_pending"] += 1
        desc = str(r.get("description") or "")
        cur = problem_idx.get(sig)
        if desc and (cur is None or str(r.get("created") or "") >= cur[0]):
            problem_idx[sig] = (str(r.get("created") or ""), desc[:160])

    signatures = []
    for sig, ent in sorted(state["signatures"].items()):
        if not isinstance(ent, dict):
            ent = {}
        attempts = _safe_int(ent.get("admin_attempts") or 0)
        rulings = _safe_int(ent.get("arbiter_rulings") or 0)
        esc = esc_stats.get(sig) or {"esc_total": 0, "esc_pending": 0}
        signatures.append(
            {
                "signature": sig,
                **_chain_subject(sig),
                "admin_attempts": attempts,
                "admin_cap": admin_cap,
                "arbiter_rulings": rulings,
                "arbiter_cap": arbiter_cap,
                "exhausted": attempts >= admin_cap and rulings >= arbiter_cap,
                "last_seen": str(ent.get("last_seen") or ""),
                "last_spec_status": str(ent.get("last_spec_status") or ""),
                "esc_total": esc["esc_total"],
                "esc_pending": esc["esc_pending"],
            }
        )

    # 在办富化（redesign-chain-panel-ui 1.1）：run_id 先走链台账事件索引，
    # admin 相回落同 spec 最新 pending disposition 的 admin_run_id（旧数据
    # 台账事件缺 run_id 的兜底；merge_dispositions_by_run 单源归并）。
    # 任何联查异常按缺数据处理（字段置 None），不得阻断视图
    run_idx = _chain_run_id_index(project_root)
    pending_run_idx: dict = {}
    try:
        for rid, (is_pending, rec) in merge_dispositions_by_run(records).items():
            spec = str(rec.get("spec") or "")
            if is_pending and spec:
                pending_run_idx[spec] = str(rid)
    except Exception:
        pending_run_idx = {}
    for item in in_flight:
        sig = str(item.get("signature") or "")
        ent = state["signatures"].get(sig)
        found = problem_idx.get(sig)
        item["problem"] = found[1] if found else None
        if isinstance(ent, dict):
            item["admin_attempts_used"] = _safe_int(ent.get("admin_attempts") or 0)
            item["arbiter_rulings"] = _safe_int(ent.get("arbiter_rulings") or 0)
        else:
            # 签名无计数条目（链外残留登记/状态文件半损坏）：置 None 前端
            # 显「—」，不伪 0（伪 0 会被读成「尚未尝试」）
            item["admin_attempts_used"] = None
            item["arbiter_rulings"] = None
        item["admin_cap"] = admin_cap
        item["arbiter_cap"] = arbiter_cap
        item["run_id"] = (
            run_idx.get(str(item.get("chain_id") or ""))
            or pending_run_idx.get(str(item.get("spec") or ""))
            or None
        )

    return {
        "summary": {
            "in_flight": len(in_flight),
            "signatures": len(signatures),
            "quota_exhausted": sum(1 for s in signatures if s["exhausted"]),
            "escalations": len(escalations),
            "queue": len(queue),
        },
        "in_flight": in_flight,
        "signatures": signatures,
        "escalations": escalations,
        "queue": queue,
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
