"""core.dashboard.data.topology — SPEC 协作拓扑派生（add-spec-topology-bigscreen）。

以既有 timeline/runs 数据源（daemon 日志事件 + ``.fenix/runs/`` 运行产物 +
report.json + STATE 条目）为唯一输入，派生 nodes/edges/kpis 图数据，供只读
端点 ``GET /api/specs/<spec>/topology`` 消费；前端零拓扑推导（design D2）。

本模块纯只读：不新增数据源、不写任何文件、不改归档链路——归档 SPEC（run
产物已随 ``archive_spec_runs`` 清理）自然退化为「状态骨架 + archived: true +
空 run 节点集」，不报错（specs/topology-derivation 归档降级 Requirement）。

节点 kind 枚举 ``run|verify|user|pm|approve|delivery``；边 type 枚举
``handoff|dispatch|retry|approve``。角色归列以
``core/agent_runner/run_files.py`` 的 ``RUN_ID_AGENT_PREFIXES`` 为权威源
（agent_type 值域 → 七阶段列映射），attempt/瞬态重试后缀归并语义复用
``strip_run_id_suffixes``（单源，不复制剥离规则）。
"""

import json
import re
from pathlib import Path

from core import timelib
from core.agent_runner.run_files import run_spec_part, strip_run_id_suffixes

# ── 七阶段列（管线视图列序 = 本表顺序；specs/topology-derivation 归列映射）──
STAGES = ("demand", "plan", "dev", "review", "test", "ops", "delivery")
STAGE_LABELS = {
    "demand": "需求",
    "plan": "规划",
    "dev": "开发",
    "review": "审查/修复",
    "test": "测试/验证",
    "ops": "运维",
    "delivery": "交付",
}

# ── 协作时序泳道（泳道行序 = 本表顺序；交付终点不单设泳道，lane=None）──────
LANES = ("user", "pm", "demand", "plan", "dev", "review", "test", "ops")
LANE_LABELS = {
    "user": "用户",
    "pm": "PMEngine",
    "demand": "需求评审",
    "plan": "规划",
    "dev": "开发",
    "review": "审查/修复",
    "test": "测试/验证",
    "ops": "运维",
}

# agent_type → (stage, lane, role)。agent_type 值域以前缀表为权威
# （RUN_ID_AGENT_PREFIXES），本表只做「角色 → 列」映射、不重复前缀判定；
# 前缀表新增 agent_type 而本表未同步时落 _ROLE_UNKNOWN 兜底（开发列 +
# role: unknown），MUST NOT 丢节点。
_ROLE_TABLE = {
    "spec-review": ("demand", "demand", "需求评审"),
    "dispute-judge": ("demand", "demand", "争议裁决"),
    "planner": ("plan", "plan", "规划"),
    "planner-plan": ("plan", "plan", "生成场景"),
    "planner-judge": ("plan", "plan", "判定结果"),
    "implementer": ("dev", "dev", "开发"),
    "impl-ocr": ("review", "review", "代码审查"),
    "repair": ("review", "review", "修复"),
    "code-review": ("review", "review", "代码审查"),
    "code-fix": ("review", "review", "代码修复"),
    "tester": ("test", "test", "测试"),
    "verifier": ("test", "test", "验证"),
    "administrator": ("ops", "ops", "运维"),
}
# 未识别前缀（infer_run_agent_type 的 "agent" 泛型兜底与一切未知值）：落开发列
# 且 role 固定字面量 "unknown"（specs Scenario「未知前缀不丢节点」）。
_ROLE_UNKNOWN = ("dev", "dev", "unknown")

# fix 家族 SPEC 命名（pm_engine/family.py _resolve_fix_spec_name 递归前缀）：
# fix-<spec>、fix-fix-<spec>…。父 SPEC 拓扑并入家族 run（🔧 角标呈现修复环）；
# 归属判定恒为 run_spec_part 精确全等（防前缀兄弟 spec 串入）。

# attempt（-a<n>）与瞬态重试（-r<n>）尾段逐段剥除（与 RUN_ID_SUFFIX_RE 同值域，
# 逐段从右解析取序号；base 归并仍以 strip_run_id_suffixes 单源为准）。
_ATTEMPT_SEG_RE = re.compile(r"-a(\d+)$")
_TRANSIENT_SEG_RE = re.compile(r"-r(\d+)$")


def split_attempt(run_id: str) -> tuple:
    """run_id → ``(base_run_id, attempt, transient_retry)``。

    base 与 ``strip_run_id_suffixes`` 同一函数对象（单源）；attempt 取尾部
    attempt 段最大序号（缺省 1），transient_retry 取尾部 -r<n>（缺省 None）。
    解析只读 run_id 字符串，不触产物文件。
    """
    base = strip_run_id_suffixes(run_id)
    attempt = 1
    transient = None
    rid = run_id
    while True:
        m = _ATTEMPT_SEG_RE.search(rid)
        if m is not None:
            attempt = max(attempt, int(m.group(1)))
            rid = rid[: m.start()]
            continue
        m = _TRANSIENT_SEG_RE.search(rid)
        if m is not None:
            transient = int(m.group(1))
            rid = rid[: m.start()]
            continue
        break
    return base, attempt, transient


def stage_lane_role(agent_type: str) -> tuple:
    """agent_type → ``(stage, lane, role)``；未识别落开发列 role=unknown。"""
    return _ROLE_TABLE.get(agent_type, _ROLE_UNKNOWN)


# ── 日志事件扫描（transitions + 验证轮次；timeline 组同源数据） ─────────────


def _scan_spec_log_events(project_root, spec_name: str, created: str):
    """扫 daemon 日志（含轮转备份，旧→新），收集该 SPEC 的派生事件。

    返回 ``(transitions, verify_starts)``：
    - transitions: 未折叠状态转移 ``[{time, from, to, channel}]``（含 Gate
      transition 前缀；channel 为写侧结构化 context 的来源标记，缺省 None）；
    - verify_starts: verify_engine「开始验证」行时刻全集（多轮验证逐轮派生的
      唯一依据——timeline 只保留最后一轮，本处保留全部）。

    读取窗口按 created 锚定（read_log_window_from，与时间轴同参同源）；行解析
    失败/非对象/非字符串 message 一律跳过，不令派生整体失败（与
    get_spec_timeline 的防护口径一致）。
    """
    import core.dashboard.data as _facade

    logs_dir = Path(project_root) / ".fenix" / "logs"
    transitions: list = []
    verify_starts: list = []
    if not logs_dir.is_dir():
        return transitions, verify_starts
    try:
        log_files = _facade.rotated_log_files(logs_dir)
    except OSError:
        return transitions, verify_starts
    pat = re.compile(
        r"Transition: " + re.escape(spec_name) + r"\s+([\w-]+)\s*→\s*([\w-]+)"
    )
    gate_pat = re.compile(
        r"Gate transition: " + re.escape(spec_name) + r"\s+([\w-]+)\s*→\s*([\w-]+)"
    )
    for lf in log_files:
        try:
            content = _facade.read_log_window_from(
                Path(project_root), lf, created
            ).decode("utf-8", errors="replace")
        except OSError:
            continue
        for line in content.split("\n"):
            if spec_name not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            msg = ev.get("message", "")
            if not isinstance(msg, str):
                continue
            ts = ev.get("timestamp", "")
            m = pat.search(msg) or gate_pat.search(msg)
            if m:
                ctx = ev.get("context") or {}
                if not isinstance(ctx, dict):
                    ctx = {}
                transitions.append(
                    {
                        "time": ts,
                        "from": m.group(1),
                        "to": m.group(2),
                        "channel": ctx.get("channel"),
                    }
                )
                continue
            if "开始验证" in msg and f"'{spec_name}'" in msg:
                verify_starts.append(ts)
    return transitions, verify_starts


def _delta_seconds(a: str, b: str, signed: bool = False):
    """ISO 时间戳秒差（timelib 单源；解析失败 None；signed=True 返回 a-b）。"""
    ta = timelib.parse_ts(str(a or ""))
    tb = timelib.parse_ts(str(b or ""))
    if ta is None or tb is None:
        return None
    delta = (ta - tb).total_seconds()
    return delta if signed else abs(delta)


def _verify_nodes(verify_starts: list, report: dict) -> list:
    """多轮验证逐轮节点（specs「多轮验证逐轮呈现」Requirement）。

    - 每行「开始验证」一个节点；历史轮仅时长（下一轮开始时刻为终点），
      MUST NOT 伪造统计；
    - 末轮与现存 report.json 配对（报告时刻不早于末轮开始才算同轮产物——
      每轮覆盖写，报告早于本轮开始属上轮残留/在飞轮次，不挂统计）携带
      场景通过/失败统计与时长（报告完成时刻为终点，负值丢弃）；
    - 日志行缺失退化为单节点（报告完成时刻 + 统计），与 get_spec_timeline
      的降级口径一致；report.json 缺失/损坏时节点无统计字段。
    """
    rep_ts = ""
    summary = {}
    if report.get("exists") and not report.get("error"):
        rep_ts = str(report.get("timestamp", "") or "")
        raw_summary = report.get("summary")
        if isinstance(raw_summary, dict):
            summary = raw_summary
    nodes: list = []
    if not verify_starts:
        # 降级：无「开始验证」日志行（窗口截断/旧日志）但报告存在 → 单节点
        if rep_ts:
            node = {
                "id": "verify:1",
                "kind": "verify",
                "stage": "test",
                "lane": "test",
                "role": "验证执行",
                "label": "验证执行",
                "time": rep_ts,
            }
            node.update(_verify_stats(summary, report))
            nodes.append(node)
        return nodes
    last_start = verify_starts[-1]
    paired = False
    if rep_ts:
        d = _delta_seconds(rep_ts, last_start, signed=True)
        # 报告时刻 >= 末轮开始（含同秒）→ 末轮产物；解析失败不配对（不伪造）
        paired = d is not None and d >= 0
    for i, start in enumerate(verify_starts):
        is_last = i == len(verify_starts) - 1
        node = {
            "id": f"verify:{i + 1}",
            "kind": "verify",
            "stage": "test",
            "lane": "test",
            "role": "验证执行",
            "label": "验证执行",
            "time": start,
        }
        # 轮次时长：历史轮以下一轮开始为终点；末轮以报告完成时刻为终点（配对时）
        end = verify_starts[i + 1] if not is_last else (rep_ts if paired else "")
        if end:
            d = _delta_seconds(end, start, signed=True)
            if d is not None and d >= 0:
                node["duration_seconds"] = int(d)
        if is_last and paired:
            node.update(_verify_stats(summary, report))
        nodes.append(node)
    return nodes


def _verify_stats(summary: dict, report: dict) -> dict:
    """验证统计字段（仅现存 report.json 配对的节点携带；缺失键不下发）。"""
    stats = {}
    for k in ("total", "passed", "failed", "warnings", "errors"):
        if summary.get(k) is not None:
            stats[k] = summary.get(k)
    if report.get("env_error"):
        stats["env_error"] = str(report["env_error"])[:200]
    return stats


# ── 交付终点自适应（specs「交付终点自适应」Requirement） ────────────────────


def _approval_record_time(spec_dir) -> str:
    """持久人工批准留痕检测，返回批准时刻（无留痕返回 ""）。

    判定基准（任务 1.5 / design D6）：**持久可确证**的人工批准记录。实测边界：
    - ``.fenix/approve_push_request.json`` 为消费即清的瞬态信号（消费即删，
      无法事后确证）——不构成持久留痕；
    - PROJECT_LOG 推送文案无来源区分、pushed 转移 context 恒 ``channel="auto"``
      ——日志不可确证触发方。
    唯一持久载体：SPEC 目录内 ``approve-push-record.json``（``{"time": ISO}``）。
    随 SPEC 目录迁移进归档仍可确证（resolve_spec_dir 归档回退）。当前系统无
    任何写入方（「批准记录持久化」未另行立项），故存量 SPEC 恒返回 ""——
    拓扑恒渲染自动推送终点，MUST NOT 虚构人工批准节点。
    """
    if not spec_dir:
        return ""
    path = Path(spec_dir) / "approve-push-record.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    t = data.get("time")
    return t if isinstance(t, str) and t else ""


# ── run 产物收集（本 SPEC + fix 家族） ─────────────────────────────────────


def _family_run_paths(project_root, spec_name: str) -> list:
    """预扫描本 SPEC 与 fix 家族（fix-<spec>、fix-fix-<spec>…）的 run 产物路径。

    家族归属判定 = ``run_spec_part(run_id)`` 精确匹配（get_runs 同款全等口径，
    防前缀兄弟 spec 串入）。预过滤后交 ``get_runs(files=...)`` 装载元数据——
    免去全宿主 run 逐个读指标的 O(N) 放大（get_runs files 参数的既定用法）。
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return []
    fam_re = re.compile(rf"^(?:{re.escape(spec_name)}|(?:fix-)+{re.escape(spec_name)})$")
    out: list = []
    for d in (runs_dir, runs_dir / "archive"):
        try:
            entries = list(d.glob("*.jsonl"))
        except OSError:
            continue
        for p in entries:
            try:
                if fam_re.fullmatch(run_spec_part(p.stem)):
                    out.append(p)
            except (OSError, ValueError):
                continue
    return out


def _work_sort_key(n: dict):
    """工作节点（run/verify）时序排序键：解析时间优先，缺失排末尾（稳定）。

    同秒（同 base 的多 attempt 产物共享 run_id 内嵌首派发时刻，真实起点
    _first_run_event_ts 不入 meta）以 attempt 序号破平——attempt 链的 retry
    边方向、泳道错行次序都依赖 a1 → a2 → a3 的确定顺序。
    """
    dt = timelib.parse_ts(str(n.get("time") or ""))
    if dt is None:
        from datetime import datetime as _dt, timezone as _tz

        return (
            _dt.max.replace(tzinfo=_tz.utc),
            2,
            int(n.get("attempt") or 0),
            str(n.get("time") or ""),
        )
    # 同秒时 run 先于 verify（派发先于其触发的验证动作），与时间轴
    # _timeline_sort_key 的 kind 次序语义一致
    rank = 1 if n.get("kind") == "verify" else 0
    return (dt.replace(microsecond=0), rank, int(n.get("attempt") or 0), dt)


# ── 主入口 ─────────────────────────────────────────────────────────────────


def derive_topology(project_root, spec_name: str, entry: "dict | None" = None) -> dict:
    """派生 SPEC 协作拓扑（``GET /api/specs/<spec>/topology`` 数据源）。

    返回::

        {
          "spec", "status", "archived",
          "kpis": {total_duration, total_cost_usd, dispatched, completed, retried},
          "nodes": [...], "edges": [...],
          "transitions": [...],   # PMEngine 状态转移（不折叠）
          "admin_events": [...],  # 运维事件（timeline 同源）
          "user_actions": [...],  # 用户泳道人工动作标记
        }

    entry（STATE 条目，活跃或归档清单）提供 status/created/total_duration；
    调用方（topology_routes）已经归档清单回退解析。
    """
    import core.dashboard.data as _facade

    proot = Path(project_root)
    entry = entry or {}
    archived = _facade.is_spec_archived(proot, spec_name)
    spec_dir = _facade.resolve_spec_dir(proot, spec_name)
    created = str(entry.get("created") or "")
    transitions, verify_starts = _scan_spec_log_events(proot, spec_name, created)
    report = _facade.parse_report(proot, spec_name)
    billing_table = _facade.load_billing_config(proot)

    nodes: list = []
    edges: list = []
    edge_keys: set = set()

    def add_edge(src: str, dst: str, etype: str) -> None:
        key = (src, dst, etype)
        if src != dst and key not in edge_keys:
            edge_keys.add(key)
            edges.append({"from": src, "to": dst, "type": etype})

    # ── 特殊节点：用户入口（需求列）与 PMEngine（规划列调度节点） ──
    first_ts = created or (transitions[0]["time"] if transitions else "")
    nodes.append(
        {
            "id": "user",
            "kind": "user",
            "stage": "demand",
            "lane": "user",
            "role": "用户",
            "label": "用户 / fenix-new",
            "time": first_ts,
        }
    )
    nodes.append(
        {
            "id": "pm",
            "kind": "pm",
            "stage": "plan",
            "lane": "pm",
            "role": "PMEngine",
            "label": "PMEngine",
            "time": transitions[0]["time"] if transitions else first_ts,
        }
    )
    add_edge("user", "pm", "handoff")

    # ── run 节点（本 SPEC + fix 家族；每份产物文件一个节点，attempt 链由
    #    retry 边串联；归档 SPEC 产物已清理 → 自然为空集） ──
    run_paths = _family_run_paths(proot, spec_name)
    runs = _facade.get_runs(proot, None, include_archive=True, files=run_paths) if run_paths else []
    fam_re = re.compile(rf"^(?:fix-)+{re.escape(spec_name)}$")
    run_nodes: list = []
    for r in runs:
        run_id = r["run_id"]
        agent_type = r["agent_type"]
        stage, lane, role = stage_lane_role(agent_type)
        base, attempt, transient = split_attempt(run_id)
        # run_tail_insights 逐 run 读取（summary/llm/reason，timeline run 节点
        # 同源同参；成本按计价表现算，不可计价不下发 cost_usd）
        insights = _facade.run_tail_insights(_facade.resolve_run_file(proot, run_id))
        node = {
            "id": f"run:{run_id}",
            "kind": "run",
            "stage": stage,
            "lane": lane,
            "role": role,
            "label": "未知 Agent" if role == "unknown" else f"{role} Agent",
            "run_id": run_id,
            "base_run_id": base,
            "attempt": attempt,
            "agent_type": agent_type,
            "status": r["status"],
            "time": r["started"],
            "duration_seconds": r.get("duration_seconds"),
            # harness（品牌投影真相源，get_runs 行字段；存量 run 缺省 claude）
            "harness": r.get("harness"),
            # 实际驱动的 LLM / 终态原因 / 总结（timeline run 节点同源同参）
            "llm": insights["llm"],
            "summary": insights["summary"],
            "reason": insights["reason"],
        }
        if transient is not None:
            # 瞬态重试段（-r<n>，runner 原地重试子循环）——展示层口径随节点透出
            node["transient_retry"] = transient
        spec_part = r.get("spec") or ""
        node["spec"] = spec_part
        if fam_re.fullmatch(spec_part):
            # fix 家族子 SPEC 的 run：🔧 角标（管线视图呈现修复环）
            node["fix"] = True
        if billing_table:
            model, provider = _facade.split_llm_marker(insights["llm"])
            cost = _facade.compute_run_cost(insights["usage"], model, provider, billing_table)
            if cost is not None:
                node["cost_usd"] = cost
        run_nodes.append(node)

    run_nodes.sort(key=_work_sort_key)
    nodes.extend(run_nodes)

    # ── 验证执行节点（多轮逐轮） ──
    verify_nodes = _verify_nodes(verify_starts, report)
    nodes.extend(verify_nodes)

    # ── 交付终点（自适应 approve / delivery） ──
    approval_time = _approval_record_time(spec_dir)
    pushed_ts = next(
        (t["time"] for t in reversed(transitions) if t.get("to") == "pushed"), ""
    )
    if approval_time:
        endpoint = {
            "id": "delivery",
            "kind": "approve",
            "stage": "delivery",
            "lane": None,
            "role": "人工批准",
            "label": "人工批准推送",
            "time": approval_time,
        }
        endpoint_type = "approve"
    else:
        endpoint = {
            "id": "delivery",
            "kind": "delivery",
            "stage": "delivery",
            "lane": None,
            "role": "交付",
            "label": "自动推送",
            "time": pushed_ts,
        }
        endpoint_type = "handoff"
    nodes.append(endpoint)

    # ── 边：dispatch（PMEngine → 各逻辑 run 首节点）/ retry（attempt 链）/
    #    handoff（全局时序链 + 终点汇入） ──
    groups: dict = {}
    for n in run_nodes:
        groups.setdefault(n["base_run_id"], []).append(n)
    for members in groups.values():
        # members 已按全局时序排序（run_nodes.sort 先行）
        add_edge("pm", members[0]["id"], "dispatch")
        for prev, cur in zip(members, members[1:]):
            # 重试边仅连同 base run_id 的 attempt 链节点（members 即按 base
            # 分组）；不同 base 的独立重派走下方全局 handoff 链，不在此出现
            add_edge(prev["id"], cur["id"], "retry")
    work = sorted(run_nodes + verify_nodes, key=_work_sort_key)
    for prev, cur in zip(work, work[1:]):
        prev_base = prev.get("base_run_id")
        cur_base = cur.get("base_run_id")
        if prev_base is not None and prev_base == cur_base:
            continue  # attempt 链相邻段已由 retry 边覆盖
        add_edge(prev["id"], cur["id"], "handoff")
    if work:
        add_edge(work[-1]["id"], "delivery", endpoint_type)
    else:
        # 无任何工作节点（归档骨架/零 run）：终点自 PMEngine 汇入，图不断链
        add_edge("pm", "delivery", endpoint_type)

    # ── KPI（specs「KPI 口径」Requirement；attempt 链归并计数） ──
    dispatched = len(groups)
    completed = sum(
        1 for members in groups.values() if any(n["status"] == "done" for n in members)
    )
    retried = sum(
        1
        for members in groups.values()
        if len(members) > 1 or any(n["status"] in ("superseded", "stale") for n in members)
    )
    # total_duration：done/pushed 优先读 STATE 固化快照（不随产物清理归零），
    # 其余实时求和——与 summary._spec_total_duration 列表/详情共用口径一致
    persisted = None
    if entry.get("status") in ("done", "pushed"):
        raw = entry.get("total_duration")
        if raw is not None:
            try:
                persisted = int(raw)
            except (TypeError, ValueError):
                persisted = None
    if persisted is None:
        total_duration = sum(int(n.get("duration_seconds") or 0) for n in run_nodes)
    else:
        total_duration = persisted
    # total_cost_usd：全部 run 不可计价时为 null（与 cost_summary_from_timeline
    # 同语义：至少一个可计价 run 才求和非 None）
    priced = [n["cost_usd"] for n in run_nodes if n.get("cost_usd") is not None]
    total_cost_usd = sum(priced) if priced else None

    # ── 用户泳道人工动作标记（创建 + 持久批准留痕） ──
    user_actions: list = []
    if created:
        user_actions.append({"time": created, "action": "创建 SPEC"})
    if approval_time:
        user_actions.append({"time": approval_time, "action": "审批推送"})

    return {
        "spec": spec_name,
        "status": entry.get("status"),
        "archived": archived,
        "kpis": {
            "total_duration": total_duration,
            "total_cost_usd": total_cost_usd,
            "dispatched": dispatched,
            "completed": completed,
            "retried": retried,
        },
        "nodes": nodes,
        "edges": edges,
        "transitions": transitions,
        "admin_events": _facade.admin_events_for_spec(proot, spec_name),
        "user_actions": user_actions,
    }
