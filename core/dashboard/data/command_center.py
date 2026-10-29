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
# 2026-10-28 用户定稿重划五线：设计线（场景生成/验证）、self-review→质量线、
# evolution→运营线；**testing（tester）与 scan 取消出卡**（fenixd 测试在实现/
# 修复 run 内部执行、扫描由代码评审承担，两车道从未派发）；ocr 未划线
# （观测到才落「其他」）。
ZONE_DEMAND = "需求线"
ZONE_DESIGN = "设计线"
ZONE_DELIVERY = "交付线"
ZONE_QUALITY = "质量线"
ZONE_OPS = "运营线"
# 花名册外观测 lane 的兜底分区
OTHER_ZONE = "其他"

ROSTER = {
    ZONE_DEMAND: ("planner", "spec-review"),
    ZONE_DESIGN: ("planner-plan", "planner-judge"),
    ZONE_DELIVERY: ("implementer", "code-fix", "verifier"),
    ZONE_QUALITY: ("judge", "code-review", "self-review"),
    ZONE_OPS: ("administrator", "evolution"),
}

# lane → zone 反查表（花名册派生，勿手工维护第二份）
LANE_ZONE = {lane: zone for zone, lanes in ROSTER.items() for lane in lanes}

# 观测 lane → 编制内 lane 归并（2026-10-28 用户定稿）：dispute-judge 计入
# 质量裁决（judge）、repair 计入修复（code-fix）。仅组织网格聚合消费；
# 时间线/拓扑屏保持原生 agent_type（各有角色映射单源）。
LANE_ALIASES = {
    "dispute-judge": "judge",
    "repair": "code-fix",
}

# 时间窗（2026-10-28 时间下拉「今日/7 日/全量」）：today=UTC 日界起；
# 7d=近 7 天；all=未归档全部（仅活跃产物，无时间下界）。窗口同时约束
# 车道卡三格（run 计数/成功率/成本）与产品团队汇总；需求数量（活跃 SPEC）
# 与 14 日 sparkline 不随窗变。
WINDOW_TODAY = "today"
WINDOW_7D = "7d"
WINDOW_ALL = "all"
ORG_WINDOWS = (WINDOW_TODAY, WINDOW_7D, WINDOW_ALL)

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


def _window_runs(proot: Path, since_epoch: float, include_archive: bool = True) -> list:
    """入窗 run 行（get_runs 既有元数据口径：status/started/duration/
    agent_type/spec；live+archive 同 stem 活跃副本优先去重）。include_archive
    False 时仅活跃产物（「全量=未归档」窗选口径）。"""
    files = _run_files_since(proot, since_epoch)
    if not files:
        return []
    import core.dashboard.data as _facade

    return _facade.get_runs(proot, None, include_archive=include_archive, files=files)


# ── 成本口径（复用 topology/timeline 既有成本单点） ───────────────────────

# 已留痕过的脏 usage 值形态（str 截断为键；防逐 run/逐端点 debug 刷屏）
_COERCE_INT_LOGGED: set = set()


def _coerce_int(value) -> int:
    """usage 分项容错整数转换（读侧 MUST NOT 500 契约，code-review item
    7160f2bb14fe）：None/空按 0；非数值形态（LLM 产物手改/脏写如
    "12,345"、"nan"）按 0 计，同一值形态仅 debug 留痕一次。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError：非有限浮点（json.loads 默认接受 Infinity 字面量），
        # 与 code_review._line_key 同款容错口径
        key = str(value)[:64]
        if key not in _COERCE_INT_LOGGED:
            _COERCE_INT_LOGGED.add(key)
            logger.debug(
                "command_center: non-numeric usage value %r coerced to 0", value
            )
        return 0


def _run_cost_and_tokens(proot: Path, run_id: str, billing: dict) -> tuple:
    """单 run (cost, tokens)：run_tail_insights → compute_run_cost 既有口径。

    cost：按计价表现算，不可计价（无 usage/卡片关闭/无匹配价格行）为 None；
    tokens：result 事件 usage 四分项合计（分项经 :func:`_coerce_int` 容错，
    脏值不拖垮聚合端点），usage 缺失为 None。
    """
    import core.dashboard.data as _facade

    insights = _facade.run_tail_insights(_facade.resolve_run_file(proot, run_id))
    model, provider = _facade.split_llm_marker(insights.get("llm") or "")
    cost = _facade.compute_run_cost(insights.get("usage"), model, provider, billing)
    usage = insights.get("usage")
    tokens = None
    if isinstance(usage, dict):
        tokens = sum(_coerce_int(usage.get(k)) for k in _USAGE_TOKEN_KEYS)
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
       处理」，auto-self-heal 收口的 SIGNAL 不计——AdminStore.read_all
       全量读后按 _resolved_records 同源口径过滤，不走展示切片）；分母
       0 → null；
    3. ``run_success_rate_7d``：窗内终态 success（classify_run=done）数 ÷
       窗内终态（done + error）数；分母 0 → null；
    4. ``cost_per_spec_7d``：窗内 run 成本合计（run_tail_insights →
       compute_run_cost 既有成本口径，不可计价 run 不贡献）÷
       delivered_specs_7d；分母 0 → null；窗内无任一 run 可计价 → null
       （对齐 aggregate_org 的全未计价 → None 红线口径）。

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
    cost_priced = False  # 窗内是否有任一 run 计价（对齐 lane 卡 cost_priced 门）
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
                    cost_priced = True

        # ② 人工处置 escalation（handled 且 kind=escalation；auto-self-heal
        # 收口的 SIGNAL 不计）。分子统计不走 get_resolved_alerts 展示切片
        # （先过滤后 [:limit]，已解决记录积累超限时窗内条目被静默低估）：
        # 直接 AdminStore.read_all 全量读后按 _resolved_records 同源口径
        # 过滤，再按 handled_at 落窗计数（code-review item bdb78a42b473）。
        try:
            from core.admin_store import AdminStore, ESCALATION

            for rec in AdminStore(proot).read_all():
                if not rec.get("handled") or rec.get("kind") != ESCALATION:
                    continue  # 未处理条目与自愈收口 SIGNAL 不计人工介入
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
        # 全未计价（计价表未配置/窗内 run 全不可计价）→ None，杜绝「$0.00/spec」
        # 假零，与 aggregate_org 的全未计价红线口径对齐（code-review item 982f3a108e92）
        # [fenix-ignore:937217517372] cost_priced 标志 + 未计价返回 None 已在此落地，本条重报不成立
        "cost_per_spec_7d": (
            round(cost_total / delivered_total, 6)
            if delivered_total and cost_priced
            else None
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
    """车道卡统计骨架（编制内零 run 车道同款出卡）。计数器为窗口中性命名
    （runs/success/success_denom/cost），窗口语义由 aggregate_org 统一注入。"""
    return {
        "lane": lane,
        "zone": zone,
        "status": "idle",
        "runs": 0,
        "success": 0,
        "success_denom": 0,
        "cost": 0.0,
        "cost_priced": False,
        "duration": 0.0,  # 窗口内 run 时长合计（秒；get_runs duration_seconds 口径）
        "activity_14d": [0] * 14,
        "last_activity_dt": None,
        "inflight": [],  # [(started_dt, project, spec, run_id)]，归属取最新
    }


def aggregate_org(registry_projects, project=None, *, now=None, window=WINDOW_TODAY) -> dict:
    """组织网格数据（specs「组织网格数据派生」Requirement）。

    车道卡 = 花名册全量（零 run 也出卡）∪ 观测 lane（花名册外落「其他」
    分区）。卡片字段：lane/zone/status（working=存在在飞 run，复用 runs.py
    在飞判定口径）/runs（窗内计数，窗口见下）/success_rate（分母对齐
    aggregate_kpi ``run_success_rate_7d`` 同款口径 done/(done+error)）/
    cost/activity_14d（长度 14 按日计数恒 14 日口径，旧→新；mtime 粗筛入窗
    文件后按 started 落桶）/last_activity_ts/attributable（最近在飞 run 归属
    {project, spec} 或 null）/attributables（2026-10-29 多 spec 并行：在飞
    归属列表 [{project, spec, run_id}]，started 降序、同 (project, spec) 去
    重取最新；run_id 供点击 spec 名打开运行记录弹窗）。

    窗口 ``window``（2026-10-28 时间下拉）：today=UTC 日界起（默认）；
    7d=近 7 天；all=未归档全部（不限时间扫 live+归档 run 产物，剔除已归档
    SPEC 名下 run）。窗口同时约束 run 计数/成功率/成本、需求数量（按 SPEC
    created）与产品团队汇总；非法值防御性回落 today。

    响应携带 ``edges``（:data:`EDGES` 常量快照）、``projects`` 回显（与
    collab-graph 同一注入与筛选模式）、``summary``（产品团队汇总卡：需求数量
    =窗口内创建的活跃 SPEC 数；runs_total/duration_total/cost_total=窗口内
    全车道合计，时长为秒（run_metrics 指标口径，回退 mtime 推算），全未计价
    → None）与 ``window`` 回显。
    """
    now_dt = _now_utc(now)
    day_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    win7_start = now_dt - timedelta(days=7)
    win14_start = now_dt - timedelta(days=14)
    win14_epoch = win14_start.timestamp()
    if window not in ORG_WINDOWS:
        window = WINDOW_TODAY
    win_start = {
        WINDOW_TODAY: day_start,
        WINDOW_7D: win7_start,
        WINDOW_ALL: None,
    }[window]
    # 「全量=未归档」：不限时间扫全部 run 产物（终态 run 会移入 runs/archive/，
    # 故必须并入归档产物），并剔除已归档 SPEC（STATE.archive.md 清单）名下
    # 的 run；today/7d 仍扫 14 日文件（sparkline 口径上限，同时覆盖两窗起点）
    scan_epoch = 0 if window == WINDOW_ALL else win14_epoch

    stats: dict = {lane: _new_lane_stat(lane, zone) for lane, zone in LANE_ZONE.items()}
    projects_out = _echo_projects(registry_projects)

    for p in _scoped_projects(registry_projects, project):
        name = p["name"]
        proot = Path(p["path"])
        rows = _window_runs(proot, scan_epoch, include_archive=True)
        if not rows:
            continue
        import core.dashboard.data as _facade

        billing = _facade.load_billing_config(proot)
        # 已归档 SPEC（STATE.archive.md 清单）名下的 run 全窗剔除——归档
        # SPEC 是完结历史，不进现役车道统计（含「全量=未归档」窗）
        archived_names = set(_facade.parse_archived_state(proot))
        for r in rows:
            if archived_names and str(r.get("spec") or "") in archived_names:
                continue
            raw_lane = r.get("agent_type") or "agent"
            lane = LANE_ALIASES.get(raw_lane, raw_lane)
            st = stats.get(lane)
            if st is None:
                # 花名册外观测 lane：落「其他」分区（花名册外车道不丢）
                st = stats[lane] = _new_lane_stat(lane, OTHER_ZONE)
            started = _parse_ts(r.get("started"))
            if started is not None:
                if win_start is None or started >= win_start:
                    st["runs"] += 1
                    st7 = r.get("status")
                    # 成功率分母对齐 aggregate_kpi run_success_rate_7d 同款
                    # 口径：done/(done+error)；cancelled/interrupted 等其他
                    # 终态不计入分母，避免同名指标双口径
                    if st7 == "done":
                        st["success"] += 1
                        st["success_denom"] += 1
                    elif st7 == "error":
                        st["success_denom"] += 1
                    # run 时长（秒；优先 run_metrics 指标日志，回退 mtime 推算）
                    st["duration"] += float(r.get("duration_seconds") or 0)
                    # 成本（窗内 run；计价表存在才读产物尾窗，未计价不贡献）
                    if billing:
                        cost, _tok = _run_cost_and_tokens(proot, r["run_id"], billing)
                        if cost is not None:
                            st["cost"] += cost
                            st["cost_priced"] = True
                # 14 日活动桶：旧→新，index 13 = 今天（UTC 日界）
                idx = 13 - (now_dt.date() - started.date()).days
                if 0 <= idx <= 13:
                    st["activity_14d"][idx] += 1
                if st["last_activity_dt"] is None or started > st["last_activity_dt"]:
                    st["last_activity_dt"] = started
            if r.get("status") in IN_FLIGHT_STATUSES:
                st["inflight"].append(
                    (started, name, str(r.get("spec") or ""), str(r.get("run_id") or ""))
                )

    # 需求规划（planner）派生口径（2026-10-28 用户定稿）：每个需求固定计 1 次
    # 需求规划派发，代表 /fenix-new 时 AI 与人类讨论的过程——不消费真实
    # planner- run 产物（fenixd 需求人工提，该车道零真实派发）。窗口口径与
    # 需求数量一致（按 SPEC created）。
    import core.dashboard.data as _facade

    spec_count = 0
    for p in _scoped_projects(registry_projects, project):
        for entry in _facade.parse_state(Path(p["path"])).values():
            created = _parse_ts((entry or {}).get("created"))
            if win_start is None or (created is not None and created >= win_start):
                spec_count += 1
    if "planner" in stats:
        stats["planner"]["runs"] = spec_count
        # 成功率固定 100%、成本固定 $0（2026-10-28 用户定稿）：规划为人机
        # 讨论派生计数，无失败语义、不计价。spec_count=0 时 denom=0 →
        # 成功率按红线显示「—」；cost_priced 置 True 使 0 成本按「$0.00」
        # 真实零显示（非「—」）。
        stats["planner"]["success"] = spec_count
        stats["planner"]["success_denom"] = spec_count
        stats["planner"]["cost_priced"] = True
        stats["planner"]["cost"] = 0.0
        # 时长随派生计数复位（观测循环累加的真实 planner run 时长不混入），
        # 避免「runs=派生计数、duration=真实观测」混口径卡片，并使
        # summary.duration_total 与派生计数对应；activity_14d/last_activity/
        # inflight/status 保留真实观测口径属有意行为——在飞与活动动向反映
        # 车道真实状态，不随人工派生计数抹除（code-review item 58c5d2886806）。
        stats["planner"]["duration"] = 0.0

    cards: list = []
    # 花名册序优先（zone 序 + 区内 lane 序），花名册外观测 lane 按名排序殿后
    roster_lanes = [lane for lanes in ROSTER.values() for lane in lanes]
    ordered = roster_lanes + sorted(
        (lane for lane in stats if lane not in LANE_ZONE)
    )
    for lane in ordered:
        st = stats[lane]
        inflight = st["inflight"]
        # 在飞归属列表（2026-10-29 多 spec 并行滚动显示）：spec/started/run_id
        # 齐备才收（spec 段为空——admin/evo 等无 SPEC 车道——不可得）；同
        # (project, spec) 去重取最新（瞬态重试多 run 同 spec），started 降序
        # （最新在前）。attributable 兼容字段保留旧形态（最新一条，无 run_id）。
        latest: dict = {}
        for started_dt, pname, spec, run_id in inflight:
            if not spec or started_dt is None or not run_id:
                continue
            key = (pname, spec)
            prev = latest.get(key)
            if prev is None or started_dt > prev[0]:
                latest[key] = (started_dt, pname, spec, run_id)
        attributables = [
            {"project": pname, "spec": spec, "run_id": run_id}
            for _, pname, spec, run_id in sorted(
                latest.values(), key=lambda t: t[0], reverse=True
            )
        ]
        attributable = (
            {"project": attributables[0]["project"], "spec": attributables[0]["spec"]}
            if attributables
            else None
        )
        cards.append(
            {
                "lane": lane,
                "zone": st["zone"],
                "status": "working" if inflight else "idle",
                "runs": st["runs"],
                "success_rate": (
                    round(st["success"] / st["success_denom"], 6)
                    if st["success_denom"]
                    else None
                ),
                "cost": round(st["cost"], 6) if st["cost_priced"] else None,
                "activity_14d": st["activity_14d"],
                "last_activity_ts": (
                    st["last_activity_dt"].isoformat() if st["last_activity_dt"] else None
                ),
                "attributable": attributable,
                "attributables": attributables,
            }
        )

    # 分区输出保持 ROSTER 固定序，「其他」仅在有观测 lane 时出现
    zones: list = []
    for zone in (*ROSTER.keys(), OTHER_ZONE):
        zone_cards = [c for c in cards if c["zone"] == zone]
        if zone_cards:
            zones.append({"zone": zone, "cards": zone_cards})

    # 产品团队汇总（2026-10-28 用户追加「产品团队」卡数据源）：需求数量=
    # 窗口内创建的活跃 SPEC 数（parse_state created 时间过滤；created 缺失/
    # 脏值仅在全量窗计入）；运行总数/总成本=窗口内全车道合计（含 planner
    # 派生计数；全未计价 → None，读侧按「—」红线显示）。
    runs_total = sum(c["runs"] for c in cards)
    costs = [c["cost"] for c in cards if c["cost"] is not None]
    duration_total = round(sum(st["duration"] for st in stats.values()), 1)

    return {
        "project": project,
        "projects": projects_out,
        "window": window,
        "summary": {
            "spec_count": spec_count,
            "runs_total": runs_total,
            "duration_total": duration_total,
            "cost_total": round(sum(costs), 6) if costs else None,
        },
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
