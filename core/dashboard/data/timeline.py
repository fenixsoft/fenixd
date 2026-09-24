"""core.dashboard.data.timeline — SPEC 生命周期时间轴（timeline 组）。

refactor-dashboard-data-module D3 分组：本模块承载时间轴重建职责域。
"""

import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

_LIFECYCLE_ORDER = {
    "drafted": 0,
    "reviewing": 0.5,
    "ready": 1,
    "implementing": 2,
    "bug-found": 2.5,
    "implemented": 3,
    "testing": 4,
    "verified": 5,
    "done": 6,
    "pushed": 7,
}


def _backtrack_reason(frm: str, to: str) -> str:
    """状态回退的规则兜底原因（Agent 记录的 error 优先，见 get_spec_timeline）。"""
    if to == "bug-found":
        return "验证发现 bug，退回修复"
    if frm == "testing" and to in ("implementing", "ready"):
        return "验证失败/中断，回退实现"
    if frm == "implemented" and to in ("implementing", "ready"):
        return "实现未通过，回退重做"
    if frm == "ready" and to == "ready":
        return "实现失败，重试"
    return "状态回退"


def _load_billing_config(project_root) -> dict:
    """从 llm.providers[i].billing 收集 per-provider 计价表（improve-provider-billing-config）。

    返回 {provider_name: {"enabled": bool, "prices": [...]}}——仅登记声明了 billing
    子对象且卡片开关开启的 provider（enabled 关闭的卡片不收集：表非空即等价于
    design D2 的「有任一开启卡片才进入计价分支」闸门，未开启卡片由匹配函数
    直接无表项 → None，计费关闭不下发 cost 字段）。读失败/旧形态（顶层
    llm.billing）/异常一律容错返回空表（fail-open 不计价不崩溃）。
    """
    try:
        # 跨组引用（config_admin 组的 read_effective_config）经门面延迟解析（D4）
        import core.dashboard.data as _facade

        _llm = _facade.read_effective_config(project_root).get("llm") or {}
        providers = _llm.get("providers") or []
    except Exception:
        return {}
    table: dict = {}
    for p in providers:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        billing = p.get("billing")
        if not isinstance(name, str) or not name or not isinstance(billing, dict):
            continue
        # 形态异常（enabled 非布尔等）容错：跳过该卡片，不计价不崩溃
        if (
            "enabled" in billing
            and billing["enabled"] is not None
            and not isinstance(billing["enabled"], bool)
        ):
            continue
        if not billing.get("enabled"):
            continue
        prices = billing.get("prices")
        table[name] = {
            "enabled": True,
            "prices": prices if isinstance(prices, list) else [],
        }
    return table


def _admin_events_for_spec(project_root, spec_name: str) -> list:
    """过滤当前 SPEC 关联的 admin 运维事件，输出 kind="admin" 时间轴节点。

    数据源复用 AdminStore.read_all()（既有带锁、容错读，缺失/损坏返回 []）：
    - 过滤：kind in {escalation, disposition} 且 spec 精确匹配目标 SPEC；
      缺 spec 字段（历史脏数据）跳过，不误挂到当前 SPEC。
    - 归并：同 admin_run_id 的 disposition 组内存在非 pending 最终处置时
      （result/status 非 pending），仅保留最新最终处置，避免时间轴出现
      「永久处置中」；无最终处置保留 pending；无 admin_run_id 的记录独立成节点
      （与运维记录页 best_by_run 归并语义一致，不引入置顶/_pin 页面概念）。
    - 输出节点字段：time=created、kind="admin"、record_kind、signal_type、
      severity、description；状态字段 escalation 取 handled、disposition 取 result。
    - 读取异常 fail-open 返回空列表，时间轴照常渲染 state/run 两类节点。
    """
    from core.admin_store import AdminStore, DISPOSITION, ESCALATION

    try:
        records = AdminStore(project_root).read_all()
    except Exception:
        return []
    if not records:
        return []
    spec_records = [
        r
        for r in records
        if r.get("kind") in (ESCALATION, DISPOSITION) and r.get("spec") == spec_name
    ]
    if not spec_records:
        return []

    # 按 admin_run_id 归并 disposition（轻量 best_by_run 语义）：
    # 非 pending 优先于 pending；同为非 pending 取最新；无 admin_run_id 独立。
    best_by_run: dict = {}
    for rec in spec_records:
        if rec.get("kind") != DISPOSITION:
            continue
        rid = rec.get("admin_run_id") or f"run-{id(rec)}"
        status = rec.get("result") or rec.get("status")
        is_pending = status == "pending"
        existing = best_by_run.get(rid)
        if existing is None:
            best_by_run[rid] = (is_pending, rec)
            continue
        if is_pending and not existing[0]:
            continue  # 已有最终处置，pending 被替代
        if not is_pending and existing[0]:
            best_by_run[rid] = (False, rec)
        elif (rec.get("created") or "") > (existing[1].get("created") or ""):
            best_by_run[rid] = (is_pending, rec)

    nodes: list[dict] = []
    for rec in spec_records:
        if rec.get("kind") == DISPOSITION:
            rid = rec.get("admin_run_id") or f"run-{id(rec)}"
            if best_by_run.get(rid, (False, None))[1] is not rec:
                continue  # 该 pending 已被最终处置替代
        node = {
            "time": rec.get("created") or "",
            "kind": "admin",
            "record_kind": rec.get("kind"),
            "signal_type": rec.get("signal_type"),
            "severity": rec.get("severity"),
            "description": rec.get("description") or "",
        }
        if rec.get("kind") == ESCALATION:
            node["handled"] = bool(rec.get("handled"))
        else:
            node["result"] = rec.get("result") or rec.get("status")
        nodes.append(node)
    return nodes


def _ocr_lane_summary(project_root, run_id: str) -> str:
    """ocr 车道 run 转录 start 事件的 message（审查对象摘要，车道可见性 1.1）。

    start 是车道 jsonl 首事件（maintenance_runs._write_impl_ocr_run_events：
    ``ocr 车道启动: <branch> <from8>..<to8>``），头扫前 20 行命中即停（与
    _first_run_event_ts 同模式——run 通用尾读口 _read_run_lines 读不到头部）。
    转录缺失/无 start/message 为空返回 ""（调用方静默省字段，不报错）。
    """
    try:
        import core.dashboard.data as _facade

        path = _facade._resolve_run_file(project_root, run_id)
        with path.open("rb") as f:
            for _ in range(20):
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(ev, dict) and ev.get("type") == "start":
                    return str(ev.get("message") or "").strip()
    except OSError:
        pass
    return ""


def get_spec_timeline(
    project_root, spec_name: str, created: str = "", entry: "dict | None" = None
) -> list:
    """构建 SPEC 生命周期时间轴（按时间排序）。

    数据源：
    - 事件日志（fenixd*.log）中的 `Transition: <spec> from → to` → 状态节点
    - `.fenix/runs/` 运行产物 → 运行节点（可点击展开 LLM 对话）

    日志读取窗口按 created 锚定（_read_log_window_from）：从 spec 创建时间读到
    文件尾，长周期 spec 的早期事件不再被尾部 1MB 尾窗静默截断；created 缺失
    （存量/归档条目）退化为全文件读取。

    每条:
    - 状态: {time, kind:"state", from, to, reason}  （回退节点带 reason）
    - 运行: {time, kind:"run", run_id, agent_type, status}

    可选 ``entry``（STATE 条目，调用方 spec_detail 透传）：提供时最新的
    「→ testing」状态节点附 ``ocr_gate: {status, detail}``——ocr 门当前状态，
    经 quality_gates.parse_quality_gates 公开入口与门禁 Card 同参合成（同源
    硬约束：MUST NOT 复制第二套三态判定）；缺省时任何节点不附该字段。
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    events: list[dict] = []
    errors_at: list[tuple] = []  # (timestamp, error) —— Agent 记录的 error，作为回退原因
    # (timestamp, new_status, err) —— update_spec 直写的 status 变更（打回路径，
    # 无 Transition 行；add-agent-prompt-files 事故：时间轴上看不到打回与原因）
    status_updates: list[tuple] = []
    verify_start_ts = ""  # 最近一轮 verify_engine「开始验证」日志时刻（报告只有完成时刻）

    if logs_dir.is_dir():
        try:
            log_files = sorted(logs_dir.glob("fenixd*.log"), reverse=True)
        except OSError:
            log_files = []
        # 状态转移正则只依赖循环不变的 spec_name，提到文件循环外只编译一次
        pat = re.compile(r"Transition: " + re.escape(spec_name) + r"\s+([\w-]+)\s*→\s*([\w-]+)")
        # fix-observability-gaps 3.1：Gate transition（小写 t，state_machine
        # transition_gate 前缀）旧正则 `Transition: ` 不命中（`pat.search
        # ('Gate transition: fix-foo verified → testing')` → False）；结构化
        # 写侧两条前缀同判，正则兜底只覆盖 `Transition: `（旧格式无 Gate 行）。
        gate_pat = re.compile(r"Gate transition: " + re.escape(spec_name) + r"\s+([\w-]+)\s*→\s*([\w-]+)")
        for lf in log_files:
            try:
                # created 锚定窗口（原尾部 1MB 尾窗对早期事件静默截断）；
                # 锚点早于文件首行 → 整文件，锚点晚于文件尾 → 仅尾块，量均有限
                # 跨组引用（log_index 组的 _read_log_window_from）经门面延迟解析（D4）
                import core.dashboard.data as _facade

                content = _facade._read_log_window_from(Path(project_root), lf, created).decode(
                    "utf-8", errors="replace"
                )
            except OSError:
                continue
            for line in content.split("\n"):
                if spec_name not in line:
                    continue
                try:
                    log_entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                # 合法 JSON 但非对象（裸字符串/数组等）的行取不到字段，跳过，
                # 避免 AttributeError 令整个时间轴接口失败
                if not isinstance(log_entry, dict):
                    continue
                # log_entry：行级局部名——MUST NOT 遮蔽函数参 entry（STATE 条目，
                # 注记块同参透传判据；遮蔽会让「不透传 entry」的调用点误附 ocr_gate）
                msg = log_entry.get("message", "")
                # message 为非字符串（数字/数组等异常 JSON 行）时 pat.search
                # 会抛 TypeError，跳过，避免令整个时间轴接口失败
                if not isinstance(msg, str):
                    continue
                ts = log_entry.get("timestamp", "")
                ctx = log_entry.get("context") or {}
                if not isinstance(ctx, dict):
                    ctx = {}
                # ── 结构化优先（fix-observability-gaps 3.1）──
                # 写侧（state_machine.transition / transition_gate）已带
                # 结构化 context（channel 键 = 写侧升级标记）。同一条日志行
                # 有 context 走结构化解（含 Gate transition 前缀）、无 context
                # 走正则兜底（历史日志），逐行互斥——同一行不产出两个状态节点。
                m = pat.search(msg) or gate_pat.search(msg)
                if m:
                    frm, to = m.group(1), m.group(2)
                    # 方向单源：backward 按生命周期序判定（与打回重建路径
                    # 同式），Transition 回退判定复用为该字段来源
                    backward = _LIFECYCLE_ORDER.get(to, 9) < _LIFECYCLE_ORDER.get(frm, 9)
                    reason = _backtrack_reason(frm, to) if backward else ""
                    node = {
                        "time": ts,
                        "kind": "state",
                        "from": frm,
                        "to": to,
                        "reason": reason,
                        "backward": backward,
                    }
                    if ctx.get("channel") is not None:
                        # 结构化 context 落入节点（channel/trigger_run_id/
                        # agent_type），供前端展示转换来源
                        node["channel"] = ctx.get("channel")
                        node["trigger_run_id"] = ctx.get("trigger_run_id")
                        node["agent_type"] = ctx.get("agent_type")
                    events.append(node)
                    continue  # 本行已消费为状态节点，不再进入 Updated SPEC 分支
                # 带引号全匹配（写点唯一于 state_machine.update_spec 的
                # f"Updated SPEC '{spec_name}'"）：子串匹配会让前缀名 spec
                # （如 add-foo）吸收姊妹 spec（add-foo-ui）的状态更新
                if "Updated SPEC" in msg and f"'{spec_name}'" in msg:
                    # 复用上方已 isinstance 归一化的 ctx 取 updates（非 dict 视为缺失）
                    updates = ctx.get("updates", {}) or {}
                    err = updates.get("error")
                    if err:
                        errors_at.append((ts, str(err)))
                    new_status = updates.get("status")
                    if new_status:
                        status_updates.append((ts, str(new_status), str(err) if err else ""))
                if "开始验证" in msg and f"'{spec_name}'" in msg:
                    # verify_engine 每轮开跑的唯一一行（多轮验证取最后一轮，
                    # 与每轮覆盖的 report.json 配对）
                    verify_start_ts = ts

    # 运行节点（含归档：旧 spec 的 run 产物被清理后时间轴仍可回看）。
    # improve-provider-billing-config（D2）：计价表非空（有任一声明 billing 的
    # 卡片）时进入计价分支，逐 run 按「实际网关卡片开关 + 行 model 匹配」现算
    # cost_usd（None 不下发）；表空时整条时间轴无成本字段（前端不渲染）。
    billing_table = _load_billing_config(project_root)
    # 跨组引用（runs 组）经门面延迟解析（D4）
    import core.dashboard.data as _facade

    runs = _facade.get_runs(project_root, spec_name, include_archive=True)
    for r in runs:
        insights = _facade._run_tail_insights(_facade._resolve_run_file(project_root, r["run_id"]))
        node = {
            "time": r["started"],
            "kind": "run",
            "run_id": r["run_id"],
            "agent_type": r["agent_type"],
            "status": r["status"],
            "spec": r.get("spec"),
            "duration_seconds": r.get("duration_seconds"),
            "summary": insights["summary"],
            "llm": insights["llm"],
            "reason": insights["reason"],
        }
        if r.get("agent_type") == "impl-ocr":
            # 车道可见性 1.1：审查对象摘要（转录 start 事件 message），缺失静默省字段
            lane_summary = _ocr_lane_summary(project_root, r["run_id"])
            if lane_summary:
                node["lane_summary"] = lane_summary
        if billing_table:
            model, provider = _facade._split_llm_marker(insights["llm"])
            cost = _facade.compute_run_cost(insights["usage"], model, provider, billing_table)
            if cost is not None:
                node["cost_usd"] = cost
        events.append(node)

    # ── 验证执行节点：verify_engine 是确定性引擎而非 agent run（不产生
    # runs/*.jsonl），时间轴原本不可见——full 模式 testing→verified 之间无节点
    # 打断折叠，观感是「实现完直接连跳已推送」（fix-provider-transient-backoff
    # 误读事故）。report.json 仅引擎验证写入（fast-track 的 agent 自验不产生），
    # 时间取日志「开始验证」行（引擎开始时刻，报告只有完成时刻）；日志行缺失
    # 退化用报告完成时刻（与 verified 转换同秒，靠 _timeline_sort_key 第三键
    # 精确时间排在 verified 之前）。多轮验证 report 每轮覆盖 → 只留最后一轮。
    report = _facade.parse_report(project_root, spec_name)
    if report.get("exists") and not report.get("error"):
        summary = report.get("summary") or {}
        rep_ts = str(report.get("timestamp", "") or "")
        # 时间优先取日志「开始验证」行（引擎开始时刻）；缺失退化报告完成时刻
        v_time = verify_start_ts or rep_ts
        if v_time:
            v_node: dict = {
                "time": v_time,
                "kind": "verify",
                "total": summary.get("total"),
                "passed": summary.get("passed"),
                "failed": summary.get("failed"),
                "warnings": summary.get("warnings"),
                "errors": summary.get("errors"),
            }
            if verify_start_ts and rep_ts:
                d = _ts_delta(rep_ts, verify_start_ts)
                if d is not None and d >= 0:
                    v_node["duration_seconds"] = int(d)
            if report.get("env_error"):
                v_node["env_error"] = str(report["env_error"])[:200]
            events.append(v_node)

    # ── 打回节点重建：update_spec 直写 status 的变更（无 Transition 行）补建状态节点 ──
    # transition() 成对写的 Updated SPEC 行（与 Transition 节点 Δt<2s 且目标相同）去重跳过；
    # 未匹配的按时间与 Transition 节点合流推演 current status 得 from（窗口截断推不出 → "?"），
    # reason 取同行 error（精确）；无 error 时回退 _backtrack_reason 兜底（允许 errors_at 就近覆盖）。
    trans_states = [e for e in events if e.get("kind") == "state"]
    unmatched: list[tuple] = []
    for ts, new_status, err in status_updates:
        paired = any(
            (d := _ts_delta(t2["time"], ts)) is not None and d < 2 and t2["to"] == new_status
            for t2 in trans_states
        )
        if not paired:
            unmatched.append((ts, new_status, err))
    if unmatched:
        merged = sorted(
            [(e["time"], 0, "t", e["to"], "") for e in trans_states]
            + [(ts, 1, "u", ns, err) for ts, ns, err in unmatched],
            key=lambda x: (str(x[0]), x[1]),
        )
        current: "str | None" = None
        for ts, _, tag, to, err in merged:
            if tag == "t":
                current = to
                continue
            frm = current if current is not None else "?"
            # 方向按生命周期序判定（与 Transition 路径同式）。前向节点不落
            # 「状态回退」兜底文案：无同行 err 时 reason 置空（可被折叠链
            # 合并，与 Transition 前向节点行为一致）——从结构上消除前向节点
            # 被 errors_at 就近覆写传染的通道；有同行 err 时 reason=err
            # （_precise_reason 保护不被覆写）。回退节点维持现状。
            backward = _LIFECYCLE_ORDER.get(to, 9) < _LIFECYCLE_ORDER.get(frm, 9)
            if backward:
                reason = err[:120] if err else _backtrack_reason(frm, to)
            else:
                reason = err[:120] if err else ""
            events.append(
                {
                    "time": ts,
                    "kind": "state",
                    "from": frm,
                    "to": to,
                    "reason": reason,
                    "backward": backward,
                    "_precise_reason": bool(err),
                }
            )
            current = to

    # admin 运维事件节点（escalation + disposition）：与 state/run 节点统一
    # 按事件时间排序（admin 在 _timeline_sort_key 中 rank=1，夹在 state/run 间）。
    # 折叠逻辑零改动：admin 节点非 state，天然打断连续前向状态折叠。
    events.extend(_admin_events_for_spec(project_root, spec_name))

    # 排序：解析时间戳 + 同秒内 state 先于 run（_timeline_sort_key 内注释说明根因）
    events.sort(key=_timeline_sort_key)

    # 连续的前向状态转换折叠为一次（回退/运行节点打断）
    events = _collapse_timeline(events)

    # ── testing 停等注记（add-timeline-ocr-lane-visibility 任务 1.2）──
    # 最新状态转移节点 to == "testing" 时附 ocr 门**当前**状态（表达进行时语义，
    # 非历史转移时刻状态）。同源硬约束：经 quality_gates.parse_quality_gates
    # 公开入口（MUST NOT import 私有 _code_review_status 绕过 entry/runs 解析），
    # entry/runs 与门禁 Card 同参透传——worktree 候选与指纹校验逐字同源，两处
    # 口径永不漂移。仅最新一个节点可携带（历史节点天然无注记）；entry 缺省
    # （既有调用点）与非 testing 节点不附字段；合成异常 fail-open 不影响时间轴。
    if entry is not None:
        latest_state = next((e for e in reversed(events) if e.get("kind") == "state"), None)
        if latest_state is not None and latest_state.get("to") == "testing":
            try:
                gates = _facade.parse_quality_gates(
                    project_root, spec_name, entry=entry, runs=runs
                )
                ocr = next(
                    (it for it in gates.get("items", []) if it.get("id") == "code-review"),
                    None,
                )
                if isinstance(ocr, dict):
                    latest_state["ocr_gate"] = {
                        "status": str(ocr.get("status") or ""),
                        "detail": str(ocr.get("detail") or ""),
                    }
            except Exception:  # noqa: BLE001 —— 注记缺失不影响时间轴渲染
                pass

    # 回退节点补充 Agent 记录的 error 作为原因（取时间最近的一条，10 分钟内）；
    # 打回重建节点（_precise_reason）reason 已是同行精确 error，不覆盖
    if errors_at:
        for e in events:
            if e.get("kind") != "state" or not e.get("reason") or e.get("_precise_reason"):
                continue
            deltas = [
                (d, err) for (ts, err) in errors_at if (d := _ts_delta(ts, e["time"])) is not None
            ]
            if deltas:
                d, err = min(deltas, key=lambda x: x[0])
                if d < 600:  # 10 分钟内匹配到 Agent 记录的 error
                    e["reason"] = err[:120]
    for e in events:
        e.pop("_precise_reason", None)  # 内部标记不外泄
    return events


def _collapse_timeline(events: list) -> list:
    """把连续的前向状态转换折叠为一次（from[首] → to[尾]）。

    规则：
    - 连续出现的「前向状态节点」（无 reason）合并为一个节点，展示整体跨度；
      如 drafted→ready / ready→implementing / … → 折叠为 drafted → implementing。
      折叠时携带 chain（完整状态序列，首尾与 from/to 一致）：前端展开渲染
      全部中间状态不省略（fast-track 连跳 implemented→testing→verified→
      done→pushed 若只显示一头一尾，会掩盖 testing/verified 等真实途经状态）。
    - 回退节点（带 reason，如 testing→bug-found）与运行节点保持独立，并打断合并。
    """
    out: list[dict] = []
    buf: list[dict] = []  # 待合并的前向状态节点缓冲

    def _flush() -> dict:
        # 折叠缓冲按构造只收前向节点（回退节点带 reason 天然打断），backward=false
        node = {
            "time": buf[0]["time"],
            "kind": "state",
            "from": buf[0]["from"],
            "to": buf[-1]["to"],
            "reason": "",
            "backward": False,
        }
        if len(buf) > 1:
            node["chain"] = [buf[0]["from"]] + [b["to"] for b in buf]
        # fix-observability-gaps 3.1：结构化 context（channel/trigger_run_id/
        # agent_type）随折叠链保留——取链上第一个非 None 的组成节点值
        # （混合窗口下链首可能是旧格式无 context 行，溯源到新格式行即保留）。
        for _ctx_key in ("channel", "trigger_run_id", "agent_type"):
            for _b in buf:
                if _b.get(_ctx_key) is not None:
                    node[_ctx_key] = _b[_ctx_key]
                    break
        return node

    for e in events:
        if e.get("kind") == "state" and not e.get("reason"):
            buf.append(e)
            continue
        # 遇到回退状态 / 运行节点 / 其它 → 先冲刷缓冲，再追加当前事件
        if buf:
            out.append(_flush())
            buf = []
        out.append(e)
    if buf:
        out.append(_flush())
    return out


def _parse_iso_ts(ts: str):
    """解析 ISO 时间戳（兼容 Z 后缀与 +00:00），失败返回 None。

    fix-deferred-findings D2：无时区后缀（naive）结果补 `tzinfo=utc`——与项目
    「全链时间戳 UTC」约定一致（有意行为变化：下游 astimezone()/timestamp()
    不再按本地时区解释）。
    """
    try:
        from datetime import datetime as _dt, timezone as _utz

        dt = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=_utz.utc)
        return dt
    except Exception:
        return None


def _timeline_sort_key(e: dict):
    """时间轴排序键：(秒截断时间, kind 次序, 精确时间)。

    不能直接对原始字符串排序：日志时间为微秒+Z（…31.212625Z），运行 started
    为秒级+00:00（…31+00:00），同一秒内 '+' < '.' 会把运行节点排到状态转移前。
    也不能只按解析后时间排序：run started 取自 run_id 的 int(time.time()) 秒
    截断，真实启动在该秒内、且必然晚于同秒发生的状态转移（先 transition 后
    spawn，见 pm_engine/dispatch.py），故同秒内 state 恒先于 run。
    admin 运维节点（add-timeline-admin-events）夹在中间：同秒内的真实时序是
    「状态转移（testing→bug-found）→ admin 处置完成 → 触发重派的 run 启动」，
    kind 次序显式映射为 state=0、admin=1、run=2（state/run 相对次序不变）。
    verify（验证执行节点）与 state 同 rank：退化场景（日志「开始验证」行缺失）
    节点取报告完成时刻、与 verified 转换同秒且真实次序在前（报告先落盘），
    须靠第三键精确时间排在 verified 之前；正常场景（引擎开始时刻）独占一秒，
    rank 不参与。
    解析失败的事件按原字符串排在末尾，保持稳定（fix-deferred-findings P0：
    `datetime.max` 的 tzinfo 参数必须是实例，无效时间戳事件不再抛 TypeError）。
    """
    dt = _parse_iso_ts(e.get("time", ""))
    if dt is None:
        from datetime import datetime as _dt, timezone as _tz

        return (_dt.max.replace(tzinfo=_tz.utc), 2, str(e.get("time", "")))
    kind_rank = {"state": 0, "verify": 0, "admin": 1, "run": 2}.get(e.get("kind"), 2)
    return (dt.replace(microsecond=0), kind_rank, dt)


def _ts_delta(a: str, b: str):
    """两个 ISO 时间戳的秒级差值（解析失败返回 None）。"""
    ta = _parse_iso_ts(a)
    tb = _parse_iso_ts(b)
    if ta is None or tb is None:
        return None
    return abs((ta - tb).total_seconds())


def _timeline_with_retry(timeline: list, project_root, entry: dict) -> list:
    """把 spec 当前实现重试轮次附到时间轴最后一个运行节点（retry-display）。

    重派计数是 spec 级状态（STATE.md `_retry_count`），run 产物无逐节点历史
    快照——只在最新 run 节点呈现当前值（>0 时），历史节点不伪造。分母取
    项目 config `agents.max_retries`（缺失/异常回退 3，与 dispatch 取值默认
    一致；read_effective_config 是受管键白名单视图，不含 max_retries）。
    """
    try:
        count = int(entry.get("_retry_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0 or not timeline:
        return timeline
    max_r = 3
    try:
        with (Path(project_root) / ".fenix" / "config.yaml").open("r", encoding="utf-8") as f:
            max_r = int(((yaml.safe_load(f) or {}).get("agents") or {}).get("max_retries") or 3)
    except (OSError, yaml.YAMLError, TypeError, ValueError):
        pass
    for e in reversed(timeline):
        if e.get("kind") == "run":
            e["retry_count"] = count
            e["retry_max"] = max_r
            break
    return timeline


def _cost_summary_from_timeline(timeline: list) -> dict:
    """汇总时间轴内可计价 run 的成本（add-model-billing-cost-display D4）。

    Returns: {"computed_usd": float|None, "priced_runs": int, "unpriced_runs": int}
    可计价 run 的成本求和；至少一个可计价 run 时 computed_usd 非 None（否则为
    None = 全部不可计价，界面展示「成本不可用」）。
    """
    total = 0.0
    priced = 0
    unpriced = 0
    for e in timeline:
        if e.get("kind") != "run":
            continue
        cost = e.get("cost_usd")
        if cost is None:
            unpriced += 1
        else:
            priced += 1
            total += cost
    return {
        "computed_usd": total if priced else None,
        "priced_runs": priced,
        "unpriced_runs": unpriced,
    }
