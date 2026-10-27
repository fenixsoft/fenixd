"""core.dashboard.data.command_center — 指挥中心跨项目聚合（add-command-center）。

面向管理层演示的第三块大屏数据层（与 collab_graph / topology 同构：data
模块 + routes mixin + server.py 注册 mixin）。跨项目聚合五类只读数据：

- ``aggregate_kpi``       KPI 四指标（7×24h UTC 滚动窗，口径见 specs
                          command-center-aggregation「KPI 四指标派生」）；
- ``aggregate_org``       组织网格（部门分区车道卡 + 静态汇报线）；
- ``aggregate_pipeline``  交付流水线（SPEC 状态五列看板）；
- ``aggregate_ledger``    执行台账（跨项目最近 50 条 run）；
- ``aggregate_inbox``     裁决收件箱（admin_alerts 未决带 choices 快照条目
                          的只读装配，执行复用既有 POST /api/alert-resolve）。

约定（design D1–D6）：

- 全部入口签名沿用 ``aggregate_*(registry_projects, project=None)`` 注入
  模式——数据层不持有 registry 引用；``project`` 收窄到单项目。
- 部门分区（:data:`ROSTER`）与汇报线（:data:`EDGES`）为模块级静态常量，
  MUST NOT 做成用户配置项（design D2）；花名册外观测 lane 落「其他」分区。
- 窗口指标全部即时聚合（design D3）：run 文件按 mtime 粗筛入窗后再读
  （窗口外文件不读内容），run 元数据复用 ``get_runs`` 既有 memo 缓存。
- ``gateway_health`` 为网关**配置态**只读派生（复用
  ``read_effective_config`` 既有项目配置读取路径）；``llm_health`` 是按需
  主动探测工具、无缓存结果，MUST NOT 调用（本模块零网络探测）。

本模块纯只读：不写任何运行时状态、不新增 POST 端点。
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import timelib

# fenixd. 层级字面量（tests/test_logger_no_bypass.py：core/ 禁 __name__ 旁路）
logger = logging.getLogger("fenixd.dashboard.data.command_center")

# ── 静态常量（design D2：模块级、冻结、非配置项） ─────────────────────────

# 部门分区花名册：zone →（编制内 lane 全集，固定序）。零 run 的编制内车道
# 也 MUST 出卡（specs「花名册卡与观测数据合并」Requirement：编制内岗位可见）。
ZONE_DEMAND = "需求线"
ZONE_DELIVERY = "交付线"
ZONE_QUALITY = "质量线"
ZONE_OPS = "运营线"
# 花名册外观测 lane 的兜底分区
OTHER_ZONE = "其他"

ROSTER = {
    ZONE_DEMAND: ("planner", "spec-review"),
    ZONE_DELIVERY: ("implementer", "code-fix"),
    ZONE_QUALITY: ("code-review", "judge", "testing"),
    ZONE_OPS: ("administrator", "self-review", "scan", "ocr"),
}

# lane → zone 反查表（花名册派生，勿手工维护第二份）
LANE_ZONE = {lane: zone for zone, lanes in ROSTER.items() for lane in lanes}

# 静态汇报线（冻结结构）：planner→implementer、implementer→code-review、
# code-review→judge、code-fix→code-review。响应经 ``_edges_snapshot``
# 逐次深拷贝下发——外部改写响应只作用于拷贝，不污染常量（两次请求恒等）。
EDGES = (
    {"from": "planner", "to": "implementer"},
    {"from": "implementer", "to": "code-review"},
    {"from": "code-review", "to": "judge"},
    {"from": "code-fix", "to": "code-review"},
)


def edges_snapshot() -> list:
    """:data:`EDGES` 常量的逐条拷贝（响应下发单点；保持常量冻结）。"""
    return [dict(e) for e in EDGES]


# ── 交付流水线五列桶映射（specs「交付流水线派生」Requirement） ─────────────
# 桶映射 MUST 覆盖 core.state_machine.SpecStatus 全量（含侧挂 blocked）：
# drafted←{drafted, reviewing}（单证评审属需求阶段）；ready←{ready}；
# implementing←{implementing, bug-found, blocked}（侧挂暂停归在制列）；
# verifying←{implemented, testing, verified}；pushed←{done, pushed}
# （终态未归档仍为活跃 SPEC）。
PIPELINE_COLUMNS = (
    ("drafted", ("drafted", "reviewing")),
    ("ready", ("ready",)),
    ("implementing", ("implementing", "bug-found", "blocked")),
    ("verifying", ("implemented", "testing", "verified")),
    ("pushed", ("done", "pushed")),
)

_STATUS_TO_COLUMN = {
    status: col for col, statuses in PIPELINE_COLUMNS for status in statuses
}

# 台账行数上限（specs「执行台账派生」Requirement：最近 50 条）
LEDGER_CAP = 50

# 在飞 run 状态（与 collab_graph.IN_FLIGHT_STATUSES 同口径：classify_run 的
# 非终态读侧枚举——running=末行非终态事件、empty=零事件产物；get_runs 的
# stale 转换已把停更尸体剔除，不进本枚举）
IN_FLIGHT_STATUSES = ("running", "empty")

# 严重度排序权重（与 admin_alerts._summary_from_unhandled 同口径）
_SEVERITY_RANK = {"critical": 3, "major": 2, "minor": 1}

# spec/archive/ 目录名日期前缀：``YYYY-MM-DD-<name>``（archive_spec 的落位
# 形态）；<name> 允许含连字符（首个日期段后全为 SPEC 名）
_ARCHIVE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")

# usage 四分项键（tokens 合计口径，与 compute_run_cost 的四分项一致）
_USAGE_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


# ── 窗口工具（7×24h UTC 滚动窗，锚定当前时刻） ───────────────────────────


def _now_utc(now=None) -> datetime:
    """测试可注入的当前时刻归一（aware UTC）。

    ``now`` 缺省 → 真实当前时刻；float/int 按 epoch 秒；datetime 原样
    （naive 按 UTC 钉住）。与 run_activity 的 ``now`` 注入参数同动机。
    """
    if now is None:
        return timelib.now_utc()
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return timelib.from_epoch(float(now))


def _parse_ts(value) -> "datetime | None":
    """ISO 串 → aware UTC；缺失/解析失败返回 None（排序键按失败垫底处理）。"""
    if not value:
        return None
    return timelib.parse_ts(str(value))


def _run_files_since(proot: Path, since_epoch: float) -> list:
    """mtime 粗筛入窗 run 产物（design D3：窗口外文件不读内容）。

    产物 mtime = run 终止/最后写入时刻 ≥ 启动时刻——mtime 早于窗口起点的
    run 必然已在窗内结束，其内容无需参与窗口聚合。含活跃目录与 archive/
    归档副本；``<run_id>.dsh-events.jsonl`` 旁路 dump 不是 run 产物，按
    get_runs 同款 stem 后缀排除。
    """
    runs_dir = Path(proot) / ".fenix" / "runs"
    kept: list = []
    for d in (runs_dir, runs_dir / "archive"):
        try:
            entries = list(d.glob("*.jsonl"))
        except OSError:
            continue
        for p in entries:
            if p.stem.endswith(".dsh-events"):
                continue
            try:
                if p.stat().st_mtime >= since_epoch:
                    kept.append(p)
            except OSError:
                continue
    return kept


def _window_runs(proot: Path, since_epoch: float) -> list:
    """入窗 run 行（get_runs 既有元数据口径：status/started/duration/
    agent_type/spec；live+archive 同 stem 活跃副本优先去重）。"""
    files = _run_files_since(proot, since_epoch)
    if not files:
        return []
    import core.dashboard.data as _facade

    return _facade.get_runs(proot, None, include_archive=True, files=files)


# ── 成本口径（复用 topology/timeline 既有成本单点） ───────────────────────


def _run_cost_and_tokens(proot: Path, run_id: str, billing: dict) -> tuple:
    """单 run (cost, tokens)：run_tail_insights → compute_run_cost 既有口径。

    cost：按计价表现算，不可计价（无 usage/卡片关闭/无匹配价格行）为 None；
    tokens：result 事件 usage 四分项合计，usage 缺失为 None。
    """
    import core.dashboard.data as _facade

    insights = _facade.run_tail_insights(_facade.resolve_run_file(proot, run_id))
    model, provider = _facade.split_llm_marker(insights.get("llm") or "")
    cost = _facade.compute_run_cost(insights.get("usage"), model, provider, billing)
    usage = insights.get("usage")
    tokens = None
    if isinstance(usage, dict):
        tokens = sum(int(usage.get(k) or 0) for k in _USAGE_TOKEN_KEYS)
    return cost, tokens


def _gateway_health(proot: Path) -> dict:
    """网关配置态只读派生（单项目）：configured 布尔 + 已配置 provider 数。

    复用 read_effective_config 既有项目配置只读读取路径；「已配置」按
    provider 卡片声明齐备（name/baseurl/apikey/model 四要素非空）判定。
    MUST NOT 调用 core.dashboard.llm_health（按需主动探测工具，本模块
    零网络探测）。
    """
    import core.dashboard.data as _facade

    try:
        providers = (_facade.read_effective_config(proot).get("llm") or {}).get(
            "providers"
        ) or []
    except Exception:  # noqa: BLE001 —— 配置读失败按未配置容错（fail-open）
        return {"configured": False, "providers": 0}
    n = 0
    for p in providers:
        if (
            isinstance(p, dict)
            and p.get("name")
            and p.get("baseurl")
            and p.get("apikey")
            and p.get("model")
        ):
            n += 1
    return {"configured": n > 0, "providers": n}


def _scoped_projects(registry_projects, project=None) -> list:
    """聚合数据范围项目清单：project 显式指定时仅保留同名项目（fixture 也
    照常聚合）；缺省滤掉 exists=False 的未就绪项目。"""
    out = []
    for p in registry_projects or []:
        name = p.get("name")
        if not name:
            continue
        if project is not None and name != project:
            continue
        if project is None and not p.get("exists"):
            continue
        out.append(p)
    return out


def _echo_projects(registry_projects) -> list:
    """响应 ``projects`` 回显全集（筛选收窄前的聚合范围内项目名序）。

    与 collab-graph 注入模式同源；流水线屏的项目筛选下拉以它为数据源
    （specs「交付流水线派生」Scenario：筛选后 projects 仍为全集）。""" 
    return [p.get("name") for p in (registry_projects or []) if p.get("name")]


# ── KPI 四指标（GET /api/command-center/kpi 数据源） ──────────────────────


def aggregate_kpi(registry_projects, project=None, *, now=None) -> dict:
    """跨项目 KPI 四指标 + 网关配置态（specs「KPI 四指标派生」Requirement）。

    四项口径（7×24h UTC 滚动窗，锚定当前时刻；MUST NOT 引入其他口径）：

    1. ``delivered_specs_7d``：spec/archive/ 目录名日期前缀落窗的归档 SPEC
       数 + 活跃 STATE.md status=pushed 条目数，按 SPEC 名跨两源去重
       （项目内去重；「历史 pushed 无终态时间戳」混入口径为 design 风险节
       明示接受项，不做时间戳猜测）；
    2. ``human_intervention_rate_7d``：窗内 handled_at 落窗的人工处置
       escalation 数 ÷ 窗内终态 run 数（人工路径=alert-resolve 与「标记已
       处理」，auto-self-heal 收口的 SIGNAL 不计——复用 get_resolved_alerts
       既有读取口径后按 kind=escalation 剔除其自愈部分）；分母 0 → null；
    3. ``run_success_rate_7d``：窗内终态 success（classify_run=done）数 ÷
       窗内终态（done + error）数；分母 0 → null；
    4. ``cost_per_spec_7d``：窗内 run 成本合计（run_tail_insights →
       compute_run_cost 既有成本口径，不可计价 run 不贡献）÷
       delivered_specs_7d；分母 0 → null。

    ``now`` 仅测试注入（冻结当前时刻）。
    """
    now_dt = _now_utc(now)
    win_start = now_dt - timedelta(days=7)
    win_start_epoch = win_start.timestamp()
    now_epoch = now_dt.timestamp()

    delivered_total = 0
    terminal_7d = 0
    success_7d = 0
    failed_7d = 0
    cost_total = 0.0
    human_interventions = 0
    gateway = {"configured": False, "providers": 0}
    projects_out = _echo_projects(registry_projects)

    for p in _scoped_projects(registry_projects, project):
        name = p["name"]
        proot = Path(p["path"])

        # ① delivered：窗内归档目录名日期前缀 + 活跃 pushed，按 SPEC 名去重
        delivered = _delivered_spec_names(proot, win_start, now_dt)
        import core.dashboard.data as _facade

        for spec_name, entry in _facade.parse_state(proot).items():
            if entry.get("status") == "pushed":
                delivered.add(spec_name)
        delivered_total += len(delivered)

        # ② 终态 run 计数（窗内）
        rows = _window_runs(proot, win_start_epoch)
        for r in rows:
            st = r.get("status")
            if st in ("running", "empty", "stale"):
                continue  # 非终态（stale 为读侧兜底枚举，不计终态）
            terminal_7d += 1
            if st == "done":
                success_7d += 1
            elif st == "error":
                failed_7d += 1

        # ④ 窗内成本合计（复用既有成本口径；不可计价 run 不贡献）
        billing = _facade.load_billing_config(proot)
        if billing:
            for r in rows:
                cost, _tok = _run_cost_and_tokens(proot, r["run_id"], billing)
                if cost is not None:
                    cost_total += cost

        # ② 人工处置 escalation（get_resolved_alerts 既有口径剔除自愈部分）
        try:
            from core.admin_store import ESCALATION

            for rec in _facade.get_resolved_alerts(proot, limit=500):
                if rec.get("kind") != ESCALATION:
                    continue  # auto-self-heal 收口的 SIGNAL 不计
                handled_at = _parse_ts(rec.get("handled_at"))
                if handled_at is not None and win_start <= handled_at <= now_dt:
                    human_interventions += 1
        except Exception:  # noqa: BLE001 —— 告警读失败不拖垮 KPI 聚合
            logger.exception("command_center kpi: resolved alerts read failed: %s", name)

        # 网关配置态（跨项目累计 provider 数；任一项目已配置即 configured）
        gh = _gateway_health(proot)
        gateway["providers"] += gh["providers"]
        gateway["configured"] = gateway["configured"] or gh["configured"]

    denom_rate = terminal_7d
    denom_success = success_7d + failed_7d
    return {
        "project": project,
        "projects": projects_out,
        "delivered_specs_7d": delivered_total,
        "human_intervention_rate_7d": (
            round(human_interventions / denom_rate, 6) if denom_rate else None
        ),
        "run_success_rate_7d": (
            round(success_7d / denom_success, 6) if denom_success else None
        ),
        "cost_per_spec_7d": (
            round(cost_total / delivered_total, 6) if delivered_total else None
        ),
        "gateway_health": gateway,
    }


def _delivered_spec_names(proot: Path, win_start: datetime, now_dt: datetime) -> set:
    """spec/archive/ 下日期前缀落窗的归档 SPEC 名集合（ day 粒度入窗）。"""
    names: set = set()
    archive_root = proot / "spec" / "archive"
    try:
        entries = list(archive_root.iterdir())
    except OSError:
        return names
    for d in entries:
        m = _ARCHIVE_PREFIX_RE.match(d.name)
        if not m:
            continue
        try:
            day = datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        if win_start.date() <= day.date() <= now_dt.date():
            names.add(m.group(2))
    return names


# ── 组织网格（GET /api/command-center/org 数据源） ────────────────────────


def _new_lane_stat(lane: str, zone: str) -> dict:
    """车道卡统计骨架（编制内零 run 车道同款出卡）。"""
    return {
        "lane": lane,
        "zone": zone,
        "status": "idle",
        "runs_today": 0,
        "success_7d": 0,
        "success_denom_7d": 0,
        "cost_7d": 0.0,
        "cost_priced": False,
        "activity_14d": [0] * 14,
        "last_activity_dt": None,
        "inflight": [],  # [(started_dt, project, spec)]，attributable 取最新
    }


def aggregate_org(registry_projects, project=None, *, now=None) -> dict:
    """组织网格数据（specs「组织网格数据派生」Requirement）。

    车道卡 = 花名册全量（零 run 也出卡）∪ 观测 lane（花名册外落「其他」
    分区）。卡片字段：lane/zone/status（working=存在在飞 run，复用 runs.py
    在飞判定口径）/runs_today（UTC 日界）/success_rate_7d（分母对齐
    aggregate_kpi ``run_success_rate_7d`` 同款口径 done/(done+error)）/
    cost_7d/activity_14d（长度 14 按日计数，旧→新；mtime 粗筛入窗文件后按 started
    落桶）/last_activity_ts/attributable（最近在飞 run 归属 {project, spec}
    或 null，供钻取 /projects/:name/:spec）。

    响应携带静态汇报线 ``edges``（:data:`EDGES` 常量快照）与 ``projects``
    回显（与 collab-graph 同一注入与筛选模式）。
    """
    now_dt = _now_utc(now)
    day_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    win7_start = now_dt - timedelta(days=7)
    win14_start = now_dt - timedelta(days=14)
    win14_epoch = win14_start.timestamp()

    stats: dict = {lane: _new_lane_stat(lane, zone) for lane, zone in LANE_ZONE.items()}
    projects_out = _echo_projects(registry_projects)

    for p in _scoped_projects(registry_projects, project):
        name = p["name"]
        proot = Path(p["path"])
        rows = _window_runs(proot, win14_epoch)
        if not rows:
            continue
        import core.dashboard.data as _facade

        billing = _facade.load_billing_config(proot)
        for r in rows:
            lane = r.get("agent_type") or "agent"
            st = stats.get(lane)
            if st is None:
                # 花名册外观测 lane：落「其他」分区（花名册外车道不丢）
                st = stats[lane] = _new_lane_stat(lane, OTHER_ZONE)
            started = _parse_ts(r.get("started"))
            if started is not None:
                if started >= day_start:
                    st["runs_today"] += 1
                if started >= win7_start:
                    st7 = r.get("status")
                    # 成功率分母对齐 aggregate_kpi run_success_rate_7d 同款
                    # 口径：done/(done+error)；cancelled/interrupted 等其他
                    # 终态不计入分母，避免同名指标双口径
                    if st7 == "done":
                        st["success_7d"] += 1
                        st["success_denom_7d"] += 1
                    elif st7 == "error":
                        st["success_denom_7d"] += 1
                # 14 日活动桶：旧→新，index 13 = 今天（UTC 日界）
                idx = 13 - (now_dt.date() - started.date()).days
                if 0 <= idx <= 13:
                    st["activity_14d"][idx] += 1
                if st["last_activity_dt"] is None or started > st["last_activity_dt"]:
                    st["last_activity_dt"] = started
            if r.get("status") in IN_FLIGHT_STATUSES:
                st["inflight"].append(
                    (started, name, str(r.get("spec") or ""))
                )
            # 7 日成本（窗内 run；计价表存在才读产物尾窗，未计价不贡献）
            if billing and started is not None and started >= win7_start:
                cost, _tok = _run_cost_and_tokens(proot, r["run_id"], billing)
                if cost is not None:
                    st["cost_7d"] += cost
                    st["cost_priced"] = True

    cards: list = []
    # 花名册序优先（zone 序 + 区内 lane 序），花名册外观测 lane 按名排序殿后
    roster_lanes = [lane for lanes in ROSTER.values() for lane in lanes]
    ordered = roster_lanes + sorted(
        (lane for lane in stats if lane not in LANE_ZONE)
    )
    for lane in ordered:
        st = stats[lane]
        inflight = st["inflight"]
        attributable = None
        if inflight:
            # 最近在飞 run 的归属 SPEC（spec 段为空——admin/evo 等无 SPEC
            # 车道——不可得，MUST 为 null）
            started_dt, pname, spec = max(
                inflight, key=lambda t: t[0] or datetime.min.replace(tzinfo=timezone.utc)
            )
            if spec and started_dt is not None:
                attributable = {"project": pname, "spec": spec}
        cards.append(
            {
                "lane": lane,
                "zone": st["zone"],
                "status": "working" if inflight else "idle",
                "runs_today": st["runs_today"],
                "success_rate_7d": (
                    round(st["success_7d"] / st["success_denom_7d"], 6)
                    if st["success_denom_7d"]
                    else None
                ),
                "cost_7d": round(st["cost_7d"], 6) if st["cost_priced"] else None,
                "activity_14d": st["activity_14d"],
                "last_activity_ts": (
                    st["last_activity_dt"].isoformat() if st["last_activity_dt"] else None
                ),
                "attributable": attributable,
            }
        )

    # 分区输出保持 ROSTER 固定序，「其他」仅在有观测 lane 时出现
    zones: list = []
    for zone in (*ROSTER.keys(), OTHER_ZONE):
        zone_cards = [c for c in cards if c["zone"] == zone]
        if zone_cards:
            zones.append({"zone": zone, "cards": zone_cards})

    return {
        "project": project,
        "projects": projects_out,
        "zones": zones,
        "edges": edges_snapshot(),
    }


# ── 交付流水线（GET /api/command-center/pipeline 数据源） ─────────────────


def aggregate_pipeline(registry_projects, project=None, *, now=None) -> dict:
    """交付流水线五列看板（specs「交付流水线派生」Requirement）。

    跨项目收集活跃 SPEC（parse_state 既有读取路径），按 :data:
    `PIPELINE_COLUMNS` 桶映射归五列（覆盖 SpecStatus 全量）；卡片携带原生
    status，implementing 列卡存在在飞 run 时附 ``running``（lane + 开始
    时间，复用 get_runs 在飞判定口径）。未登记状态防御性跳过（debug 留痕）。
    """
    del now  # 预留：流水线无窗口口径（在飞判定用真实时刻）
    columns = [{"key": key, "cards": []} for key, _statuses in PIPELINE_COLUMNS]
    col_by_key = {c["key"]: c for c in columns}
    projects_out = _echo_projects(registry_projects)

    for p in _scoped_projects(registry_projects, project):
        name = p["name"]
        proot = Path(p["path"])
        import core.dashboard.data as _facade

        # 在飞 run 按 SPEC 归组（活跃目录产物即可：在飞 run 不可能已归档）
        inflight_by_spec: dict = {}
        for r in _facade.get_runs(proot):
            if r.get("status") not in IN_FLIGHT_STATUSES:
                continue
            inflight_by_spec.setdefault(str(r.get("spec") or ""), []).append(r)

        for spec_name, entry in _facade.parse_state(proot).items():
            status = entry.get("status")
            col_key = _STATUS_TO_COLUMN.get(status)
            if col_key is None:
                # 桶映射外状态（STATE 脏形态/state_machine 演进代差）：防御
                # 跳过不硬归列，debug 留痕
                logger.debug(
                    "command_center pipeline: unbucketed status %r (spec=%s)",
                    status,
                    spec_name,
                )
                continue
            card = {"project": name, "spec": spec_name, "status": status}
            if col_key == "implementing":
                runs = inflight_by_spec.get(spec_name) or []

                def _start_key(r):
                    return _parse_ts(r.get("started")) or datetime.min.replace(
                        tzinfo=timezone.utc
                    )

                if runs:
                    latest = max(runs, key=_start_key)
                    card["running"] = {
                        "lane": latest.get("agent_type"),
                        "started_at": latest.get("started"),
                    }
            col_by_key[col_key]["cards"].append(card)

    return {
        "project": project,
        "projects": projects_out,
        "columns": columns,
    }


# ── 执行台账（GET /api/command-center/ledger 数据源） ─────────────────────


def aggregate_ledger(registry_projects, project=None, *, now=None) -> dict:
    """跨项目最近 50 条 run 台账（specs「执行台账派生」Requirement）。

    行字段：project/spec/lane/outcome（classify_run 口径，get_runs status
    同源）/duration/tokens/cost/started_at/trigger（调度/派发记录既有数据
    缺口——design 风险节明示口径允许 null，不硬造默认值）。tokens/cost 仅
    对入选的最近 LEDGER_CAP 条读产物尾窗（成本/tokens 既有口径），全量行
    只取 memo 化元数据。
    """
    del now  # 台账无窗口口径
    import core.dashboard.data as _facade

    merged: list = []
    billings: dict = {}
    proots: dict = {}
    projects_out = _echo_projects(registry_projects)
    for p in _scoped_projects(registry_projects, project):
        name = p["name"]
        proot = Path(p["path"])
        proots[name] = proot
        billings[name] = _facade.load_billing_config(proot)
        for r in _facade.get_runs(proot, None, include_archive=True):
            merged.append(
                {
                    "project": name,
                    "spec": str(r.get("spec") or ""),
                    "lane": r.get("agent_type"),
                    "outcome": r.get("status"),
                    "duration": r.get("duration_seconds"),
                    "started_at": r.get("started"),
                    "_started_dt": _parse_ts(r.get("started")),
                    "_run_id": r.get("run_id"),
                }
            )

    # 开始时间倒序（解析失败垫底），截最近 LEDGER_CAP 条
    merged.sort(
        key=lambda row: row["_started_dt"]
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    merged = merged[:LEDGER_CAP]

    rows: list = []
    for row in merged:
        billing = billings.get(row["project"]) or {}
        cost = tokens = None
        if billing and row["_run_id"]:
            cost, tokens = _run_cost_and_tokens(
                proots[row["project"]], row["_run_id"], billing
            )
        rows.append(
            {
                "project": row["project"],
                "spec": row["spec"],
                "lane": row["lane"],
                "outcome": row["outcome"],
                "duration": row["duration"],
                "tokens": tokens,
                "cost": round(cost, 6) if cost is not None else None,
                "started_at": row["started_at"],
                # 调度/派发记录既有数据缺口：口径允许 null，不硬造默认值
                "trigger": None,
            }
        )

    return {
        "project": project,
        "projects": projects_out,
        "rows": rows,
    }


# ── 裁决收件箱（GET /api/command-center/inbox 数据源） ────────────────────


def aggregate_inbox(registry_projects, project=None, *, now=None) -> dict:
    """裁决收件箱只读装配（specs「裁决收件箱装配」Requirement）。

    收集未终态（get_unhandled_alerts 既有读取口径）且告警记录携带 choices
    快照的 admin_alerts 条目；``choices`` 只读告警记录内快照（MUST NOT 回
    读注册表演进态——add-human-adjudication-choices D2「历史告警不回写」语
    义）；``narrative`` 为 adjudication_narrative 既有产物，读路径已合并侧
    车，可得则带。按严重度降序、created_at 降序排列。纯装配：不新增裁决
    执行端点，执行复用既有 POST /api/alert-resolve。
    """
    del now  # 收件箱无窗口口径
    import core.dashboard.data as _facade

    projects_out = _echo_projects(registry_projects)
    cards: list = []
    for p in _scoped_projects(registry_projects, project):
        name = p["name"]
        proot = Path(p["path"])
        try:
            records = _facade.get_unhandled_alerts(proot)
        except Exception:  # noqa: BLE001 —— 单项目告警读失败不拖垮装配
            logger.exception("command_center inbox: alerts read failed: %s", name)
            continue
        for rec in records:
            choices = rec.get("choices")
            if not choices:
                continue  # 无 choices 快照的知情类告警不进收件箱
            cards.append(
                {
                    "id": rec.get("id"),
                    "project": name,
                    "spec": rec.get("spec"),
                    "run_id": rec.get("run_id"),
                    "kind": rec.get("kind"),
                    "signal_type": rec.get("signal_type"),
                    "severity": rec.get("severity"),
                    "narrative": rec.get("narrative"),
                    "narrative_pending": rec.get("narrative_pending"),
                    # 快照逐字段透传（MUST NOT 回读注册表演进态）
                    "choices": choices,
                    "created_at": rec.get("created"),
                }
            )

    # 严重度降序 + created_at 降序：两次稳定排序（created 降序先排，严重度
    # 降序后排——同严重度内保持 created 降序）
    cards.sort(key=lambda c: str(c.get("created_at") or ""), reverse=True)
    cards.sort(
        key=lambda c: _SEVERITY_RANK.get(str(c.get("severity") or ""), 0), reverse=True
    )

    return {
        "project": project,
        "projects": projects_out,
        "cards": cards,
    }
