# spec-timeline-admin-events Spec

## ADDED Requirements

### Requirement: SPEC 时间轴下发 admin 运维事件节点
`get_spec_timeline` SHALL 从 `.fenix/admin_alerts.json` 读取 `spec` 字段与当前 SPEC 名一致的 `escalation`（升级告警）与 `disposition`（运维处置）记录，为每条（归并后，见下）生成一个 `kind="admin"` 的时间轴节点。节点 SHALL 携带：时间（`created`）、`kind`（`"admin"`）、`record_kind`（`"escalation"` 或 `"disposition"`）、`signal_type`、`severity`、`description`、处置/处理状态（escalation 取 `handled`；disposition 取 `result`）。`signal` 类内部审计记录 SHALL NOT 下发到时间轴。

#### Scenario: 升级告警出现在时间轴
- **WHEN** `.fenix/admin_alerts.json` 中存在一条 `kind="escalation"`、`spec="add-timeline-admin-events"` 的记录
- **THEN** 该 SPEC 详情时间轴包含对应 `kind="admin"` 节点，`record_kind` 为 `"escalation"`，携带 severity 与 handled 状态

#### Scenario: 处置记录出现在时间轴
- **WHEN** 存在一条 `kind="disposition"`、`spec` 匹配且 `result` 非 pending 的记录
- **THEN** 时间轴包含对应 `kind="admin"` 节点，`record_kind` 为 `"disposition"`，携带 result 状态

#### Scenario: 其他 SPEC 的运维事件不串扰
- **WHEN** 存在 `spec` 字段为其他 SPEC 名的 admin 记录
- **THEN** 当前 SPEC 的时间轴不包含这些记录对应的节点

### Requirement: pending 处置记录被最终处置归并
同 `admin_run_id` 的 disposition 记录中，若存在非 pending 的最终处置（`result` 非 `"pending"`），pending（处置中）记录 SHALL 被最终记录替代，时间轴上仅保留最终处置节点；无最终处置时 pending 记录 SHALL 以「处置中」状态独立成节点。无 `admin_run_id` 的 pending 记录按独立事件保留。

#### Scenario: 最终处置替代处置中
- **WHEN** 同一 `admin_run_id` 先后产生 `result="pending"` 与 `result="resolved"` 两条 disposition
- **THEN** 时间轴上只有 `result="resolved"` 的一个 admin 节点

#### Scenario: 仅处置中时独立展示
- **WHEN** 某 `admin_run_id` 只有一条 `result="pending"` 的 disposition
- **THEN** 时间轴上呈现一个处置中（pending）状态的 admin 节点

### Requirement: admin 节点与既有节点统一按事件时间排序
admin 节点 SHALL 与 state、run 节点共用同一排序规则（`_timeline_sort_key`）：按事件时间排序；同一秒内按 state → admin → run 的次序排列。折叠规则（`_collapse_timeline`）行为不变：连续前向状态转移的折叠 SHALL 被 admin 节点打断，admin 节点自身不参与折叠。

#### Scenario: 时间轴整体按事件顺序排列
- **WHEN** SPEC 时间轴同时包含状态转移、admin 运维事件与运行节点
- **THEN** 全部节点按事件时间升序混合排列，admin 节点不堆积在首尾

#### Scenario: 同秒内次序确定
- **WHEN** 同一秒内先后发生状态转移、admin 处置、Agent 运行启动
- **THEN** 展示次序为 state、admin、run

### Requirement: 前端渲染 admin 节点为紧凑运维卡片
SPEC 详情时间轴 SHALL 为 `kind="admin"` 节点新增渲染分支：标题行包含时间、「运维处置」（disposition）或「升级告警」（escalation）标签、severity 着色 Tag（critical 红 / major 橙 / warning 及以下灰）、处置/处理状态 Tag（disposition：已解决绿、处置中蓝；escalation：已处理/未处理）；标题行下方展示一句话摘要（`description`，超长截断）。SHALL NOT 在时间轴卡片内渲染 `summary` markdown 全文（完整四段总结仍由运维记录页承载）。未知 `kind` 的节点 SHALL 走安全默认分支（按既有行为渲染或忽略），不报错。

#### Scenario: 处置节点紧凑展示
- **WHEN** 时间轴包含一条 `result="resolved"`、`severity="critical"` 的 disposition admin 节点
- **THEN** 卡片标题行显示时间、「运维处置」标签、红色 critical Tag、绿色已解决 Tag，下方一句话摘要，不含 summary 全文

#### Scenario: 升级告警节点展示处理状态
- **WHEN** 时间轴包含一条 `handled=true` 的 escalation admin 节点
- **THEN** 卡片显示「升级告警」标签与「已处理」状态 Tag

### Requirement: 运维事件源缺失时 fail-open
`.fenix/admin_alerts.json` 缺失、损坏或读取异常时，时间轴构建 SHALL 不报错，照常下发 state 与 run 两类节点（admin 事件为空）；admin 记录缺失 `spec` 字段时 SHALL 跳过该记录（不下发、不误挂到当前 SPEC）。

#### Scenario: 告警文件缺失不崩溃
- **WHEN** 项目 `.fenix/` 下不存在 `admin_alerts.json`
- **THEN** `get_spec_timeline` 正常返回仅含 state/run 节点的时间轴

#### Scenario: 损坏记录跳过
- **WHEN** `admin_alerts.json` 中某条记录缺少 `spec` 字段
- **THEN** 该记录被跳过，其余记录正常下发，接口不报错
