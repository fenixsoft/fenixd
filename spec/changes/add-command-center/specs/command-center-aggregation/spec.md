## ADDED Requirements

### Requirement: KPI 四指标派生

指挥中心聚合层 SHALL 提供跨项目 KPI 指标派生（`GET /api/command-center/kpi`），全部基于 7×24 小时滚动窗（UTC，锚定当前时刻），四项口径如下，MUST NOT 引入其他口径：

1. `delivered_specs_7d`（7 日交付 SPEC 数）：`spec/archive/` 下目录名日期前缀（`YYYY-MM-DD-<name>` 形态）落在窗内的归档 SPEC 数，加活跃 STATE.md 中 `status=pushed` 的条目数，按 SPEC 名跨两源去重。
2. `human_intervention_rate_7d`（人工介入率）：窗内 `handled_at` 落窗的人工处置 escalation 告警数 ÷ 窗内终态 run 数（人工路径含 alert-resolve 与「标记已处理」两条，auto-self-heal 收口不计；复用 `get_resolved_alerts` 既有记录读取口径剔除其自愈部分）；分母为 0 时 SHALL 返回 `null`。
3. `run_success_rate_7d`（7 日 run 成功率）：窗内终态为 success 的 run 数 ÷ 窗内终态（success + failed）run 数，终态判定复用 `core.dashboard.data.runs.classify_run` 既有口径；窗内无终态 run 时 SHALL 返回 `null`。
4. `cost_per_spec_7d`（单 SPEC 成本）：窗内 run 成本合计（复用 run metric 既有成本口径）÷ `delivered_specs_7d`；分母为 0 时 SHALL 返回 `null`。

响应 SHALL 额外携带 `gateway_health` 字段：网关配置态只读派生（复用既有项目配置只读读取路径，输出 `configured` 布尔与已配置 provider 数；`core.dashboard.llm_health` 为按需主动探测工具、无缓存结果可供复用，MUST NOT 调用之，MUST NOT 发起任何网络探测）。

#### Scenario: 四指标在混合 fixture 上正确派生
- **WHEN** registry 含两个项目：项目 A 的 STATE.md 有 1 条 `pushed`、归档目录含 `2026-10-24-x` 与 `2026-09-01-old`；项目 A 窗内终态 run 为 8 success + 2 failed、成本合计 10.0，窗内人工裁决 escalation 2 条；项目 B 数据全空（测试冻结 now 使 `2026-10-24` 落窗）
- **THEN** `delivered_specs_7d=2`（归档 1 + pushed 1，`2026-09-01-old` 出窗不计；跨两源按 SPEC 名去重后无重名）
- **THEN** `run_success_rate_7d=0.8`；`human_intervention_rate_7d=0.2`；`cost_per_spec_7d=10.0/2`
- **THEN** `gateway_health` 字段存在且为配置态派生（全程未发起任何网络探测）

#### Scenario: 分母为零返回 null
- **WHEN** 窗内无任何终态 run（新建空项目）
- **THEN** `human_intervention_rate_7d`、`run_success_rate_7d`、`cost_per_spec_7d` 均为 `null`，`delivered_specs_7d=0`

### Requirement: 组织网格数据派生

聚合层 SHALL 提供组织网格数据（`GET /api/command-center/org`）：车道卡按部门分区（zone）归组，分区与车道花名册为模块级静态常量（MUST NOT 做成用户配置项），预置分区：需求线（planner、spec-review）、交付线（implementer、code-fix）、质量线（code-review、judge、testing）、运营线（administrator、self-review、scan、ocr）；运行中观测到花名册外的 lane 时 SHALL 归入「其他」分区。

每张车道卡 SHALL 包含：`lane`、`zone`、`status`（`working`=该 lane 存在在飞 run，复用 runs.py 既有在飞判定口径；否则 `idle`）、`runs_today`（UTC 日界）、`success_rate_7d`、`cost_7d`、`activity_14d`（按日 run 计数数组，长度 14，旧→新）、`last_activity_ts`、`attributable`（`{project, spec}` 或 `null`：取该 lane 最近一条在飞 run 的归属 SPEC，不可得 MUST 为 `null`，供前端钻取 `/projects/:name/:spec`）。花名册内车道即使窗内零 run 也 MUST 出卡（编制内岗位可见）。

响应 SHALL 携带静态汇报线 `edges`（模块常量）：planner→implementer、implementer→code-review、code-review→judge、code-fix→code-review。

#### Scenario: 花名册卡与观测数据合并
- **WHEN** run metric 观测仅覆盖 implementer（今日 2 run、7 日成功 0.75、成本 1.2、14 日活动数组非全零、有在飞 run）与一个未登记 lane `mock-lane`
- **THEN** 响应含全部花名册车道卡（planner 等零 run 车道 status=idle 且计数为 0）
- **THEN** implementer 卡 `status=working`、字段值与观测一致；`mock-lane` 出现在「其他」分区

#### Scenario: 汇报线为静态常量
- **WHEN** 任意两次请求 /api/command-center/org
- **THEN** 两次响应的 `edges` 完全一致且等于模块常量（4 条边）

### Requirement: 交付流水线派生

聚合层 SHALL 提供交付流水线数据（`GET /api/command-center/pipeline`）：跨项目收集活跃 SPEC，按 STATE.md 状态归入五列：`drafted`、`ready`、`implementing`、`verifying`、`pushed`。五列为桶映射、MUST 覆盖 `core.state_machine.SpecStatus` 全量（含侧挂 blocked），卡片携带原生 `status`，列归属按下表派生：`drafted`←{drafted, reviewing}（单证评审属需求阶段）；`ready`←{ready}；`implementing`←{implementing, bug-found, blocked}（侧挂暂停归在制列）；`verifying`←{implemented, testing, verified}；`pushed`←{done, pushed}（终态未归档仍为活跃 SPEC）。每卡 SHALL 含 `project`、`spec`、`status`（原生状态），implementing 列卡在存在在飞 run 时 SHALL 附 `running`（含 lane 与开始时间）。支持可选 `project` 参数收窄到单项目，响应回显 `project` 与 `projects` 全集（与 collab-graph 聚合同一注入模式）。

#### Scenario: 五列归组与项目筛选
- **WHEN** 两项目分别有 drafted×1、implementing×2（其一有在飞 run、其一原生 status=blocked）、testing×1、pushed×1，请求不带 project 参数
- **THEN** 五列卡片数分别为 1/0/3/1/1，implementing 列在飞卡带 `running`（含 lane 与开始时间），blocked 卡保留原生 `status=blocked`
- **WHEN** 以 `project=A` 再请求
- **THEN** 仅返回项目 A 的卡，响应 `project=="A"` 且 `projects` 仍为全集

### Requirement: 执行台账派生

聚合层 SHALL 提供执行台账数据（`GET /api/command-center/ledger`）：跨项目最近 50 条 run 按开始时间倒序，每行含 `project`、`spec`、`lane`、`outcome`（classify_run 口径）、`duration`、`tokens`、`cost`、`started_at`、`trigger`（调度/派发记录可得则带，不可得 MUST 为 `null`，MUST NOT 硬造默认值）。支持可选 `project` 参数。

#### Scenario: 台账行与排序
- **WHEN** 项目 A 有 3 条 run（开始时间 T1<T2<T3）、项目 B 有 1 条 run（T4，T1<T4<T3）
- **THEN** 不带筛选的响应共 4 行且顺序为 T3、T4、T2、T1
- **THEN** 每行字段齐全，无法取得 trigger 的行 `trigger=null`

### Requirement: 裁决收件箱装配

聚合层 SHALL 提供裁决收件箱数据（`GET /api/command-center/inbox`）：收集未终态且告警记录携带 choices 快照的 admin_alerts 条目，每卡含告警 id、`project`、`spec`、`signal_type`、严重度、`narrative`（adjudication_narrative 既有产物，可得则带）、`choices`（MUST 读告警记录内快照，MUST NOT 回读注册表演进态——与 add-human-adjudication-choices D2「历史告警不回写」语义一致）、`created_at` 与溯源字段（spec/run 链接）。按严重度降序、created_at 降序排列。本能力为只读装配：MUST NOT 新增裁决执行端点，执行复用既有 `POST /api/alert-resolve`。

#### Scenario: 待决卡片装配与排序
- **WHEN** admin_alerts 含：高严重度带 3 选项快照的未决告警、低严重度带选项快照的未决告警、已终态告警、无 choices 快照的知情类告警
- **THEN** 响应仅含前两条，高严重度在前；每卡 `choices` 与其告警记录内快照逐字段一致
- **THEN** 响应不包含任何执行动作端点引用，前端执行走既有 alert-resolve

#### Scenario: 项目筛选
- **WHEN** 以 `project=A` 请求
- **THEN** 仅返回项目 A 的待决卡
