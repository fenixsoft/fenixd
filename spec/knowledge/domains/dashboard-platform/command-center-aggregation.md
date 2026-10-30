# 指挥中心后端聚合

<!-- knowledge: capability=command-center-aggregation rev=1
     sources=spec/archive/2026-10-31-add-command-center -->

面向管理层演示叙事（组织、交付、裁决、执行四个切面）的第三块大屏数据面：对 dashboard 托管项目跨项目聚合出 KPI 四指标、组织网格、交付流水线、执行台账与裁决收件箱，全部只读。

## 规则

- **五个只读端点**：`GET /api/command-center/{kpi,org,pipeline,ledger,inbox}`，由 `core/dashboard/routes/command_center_routes.py` mixin 注册；聚合实现单文件 `core/dashboard/data/command_center.py`，跨项目聚合入口沿用 `aggregate_*(registry_projects, project=None)` 注入模式（与 topology/collab-graph 同构）。端点只读无副作用，本能力 MUST NOT 新增任何裁决执行端点。
- **可选项目筛选**：全部端点支持可选 `project` 参数收窄到单项目；响应回显 `project` 与 `projects` 全集。未知项目返回 200 + `{error: 'project not found'}` 错误字典（大屏按 200 消费的有意契约，非 404）。
- **夹具与失效项目剔除**：缺省跨项目聚合剔除 `fixture=True` 登记项目与路径已不存在（exists=False）的 Registry 条目；夹具项目仅可显式 `project` 寻址。
- **KPI 七日滚动窗口径**：`/kpi` 全部指标基于 7×24 小时滚动窗（UTC，锚定当前时刻），MUST NOT 引入其他口径：
  - `delivered_specs_7d`（7 日交付 SPEC 数）：归档目录名日期前缀（`YYYY-MM-DD-<name>`）落窗的归档 SPEC 数 + 活跃 STATE.md 中 `status=pushed` 条目数，按 SPEC 名跨两源去重；pushed 条目无终态时间戳，不做时间戳猜测，「窗内归档 + 当前 pushed」即口径。
  - `human_intervention_rate_7d`（人工介入率）：窗内 `handled_at` 落窗的人工处置 escalation 告警数 ÷ 窗内终态 run 数；人工路径含 alert-resolve 与「标记已处理」两条，auto-self-heal 收口不计（复用 `get_resolved_alerts` 既有读取口径剔除其自愈部分）。
  - `run_success_rate_7d`（7 日 run 成功率）：窗内 success 终态 run 数 ÷ 窗内（success + failed）终态 run 数，终态判定复用 `classify_run` 既有口径。
  - `cost_per_spec_7d`（单 SPEC 成本）：窗内 run 成本合计（复用 run metric 既有成本口径）÷ `delivered_specs_7d`。
  - 三个比率/均值指标分母为 0 时返回 `null`（0 冒充被禁止），`delivered_specs_7d` 空窗为 0。
- **网关健康为配置态派生**：`/kpi` 响应携带 `gateway_health`（`configured` 布尔 + 已配置 provider 数），复用项目配置只读读取路径；`core.dashboard.llm_health` 是按需主动探测工具、无缓存结果，MUST NOT 调用，KPI 链路 MUST NOT 发起任何网络探测。
- **窗口聚合即时计算**：窗口指标从既有 run 文件与目录名即时聚合，不建预聚合缓存表或定时任务；复用 run metric index 既有 memo 缓存，并按 run 文件 mtime 粗筛入窗文件，窗外文件不读内容。
- **组织网格静态花名册**：`/org` 车道卡按分区（zone）归组，分区与车道花名册为模块级静态常量 ROSTER，MUST NOT 做成用户配置项。预置分区：需求线（planner、spec-review）、交付线（implementer、code-fix）、质量线（code-review、judge、testing）、运营线（administrator、self-review、scan、ocr）；观测到花名册外 lane 归入「其他」分区，编制内外车道都不丢。
- **车道卡字段**：`lane`、`zone`、`status`（`working`=该 lane 存在在飞 run，复用 runs.py 既有在飞判定；否则 `idle`）、`runs_today`（UTC 日界）、`success_rate_7d`、`cost_7d`、`activity_14d`（长度 14 的按日 run 计数数组，旧→新，按开始时间落桶）、`last_activity_ts`、`attributable`（`{project, spec}` 或 `null`：取该 lane 最近一条在飞 run 的归属 SPEC，不可得 MUST 为 `null`，供前端钻取）。花名册内车道即使窗内零 run 也出卡。
- **汇报线为静态常量**：`/org` 响应 `edges` 恒为模块常量 4 条：planner→implementer、implementer→code-review、code-review→judge、code-fix→code-review。
- **交付流水线五列桶映射**：`/pipeline` 跨项目收集活跃 SPEC 按五列归组，桶映射 MUST 覆盖 `SpecStatus` 全量（含侧挂 blocked）：`drafted`←{drafted, reviewing}（单证评审属需求阶段）；`ready`←{ready}；`implementing`←{implementing, bug-found, blocked}（侧挂暂停归在制列）；`verifying`←{implemented, testing, verified}；`pushed`←{done, pushed}（终态未归档仍为活跃 SPEC）。每卡携带原生 `status`；implementing 列卡存在在飞 run 时附 `running`（含 lane 与开始时间）。
- **执行台账**：`/ledger` 跨项目最近 50 条 run（LEDGER_CAP=50）按开始时间倒序，每行含 `project`、`spec`、`lane`、`outcome`（classify_run 口径）、`duration`、`tokens`、`cost`、`started_at`、`trigger`；trigger 调度/派发记录不可得时 MUST 为 `null`，MUST NOT 硬造默认值。
- **裁决收件箱只装配**：`/inbox` 收集未终态且告警记录携带 choices 快照的 admin_alerts 条目，按严重度降序、created_at 降序排列；每卡含告警 id、project、spec、run/kind 溯源、signal_type、severity、`narrative`（adjudication_narrative 侧车合并产物，可得则带，缺失时 `narrative_pending=true`）、`choices`、`created_at`。`choices` MUST 读告警记录内快照，MUST NOT 回读裁决注册表演进态（历史告警不回写语义）；卡片响应定形（additionalProperties false），不携带任何执行动作端点引用，裁决执行唯一通道复用既有 `POST /api/alert-resolve`。

## 溯源

- 2026-10-31 add-command-center（spec/archive/2026-10-31-add-command-center） — 新增本能力：五个只读聚合端点（KPI 四指标 7 日窗精确口径、组织网格静态花名册与汇报线常量、流水线五列桶映射覆盖全量 SpecStatus、台账 50 条倒序 trigger 允许 null、收件箱只读装配复用 alert-resolve）
