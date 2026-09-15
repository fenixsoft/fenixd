# observability-gaps

## ADDED Requirements

### Requirement: run 终止指标结构化落盘

每次 agent run 进入终态时，框架 MUST 记录一条结构化指标，字段至少含：`run_id`、`spec`、`agent_type`、`duration_seconds`、`turns`、token 用量（输入/输出等分项，可得时）、`cost_usd`（可得时）、`terminal`（终态类型）、`provider`。MUST NOT 仅依赖「由 run 文件 mtime 推算耗时」。

#### Scenario: 成功 run 记录耗时

- **WHEN** 一个 run 成功收尾
- **THEN** 产生一条含真实 `duration_seconds` 的结构化指标

#### Scenario: 失败 run 亦记录

- **WHEN** 一个 run 以失败/超时收尾
- **THEN** 同样产生含 `duration_seconds` 与 `terminal` 的指标

#### Scenario: 指标可被消费

- **WHEN** 查询某 spec 的历史耗时/成本
- **THEN** 可从落盘指标直接读取，无需事后扫描 run 产物文件

### Requirement: 状态转换日志带结构化上下文

`state_machine` 的每次状态转换 MUST 在日志中携带结构化 context，至少含：触发该转换的 `trigger_run_id`（可得时）、`agent_type`（可得时）、`channel`（区分自动调度/人工操作/恢复等来源）。

#### Scenario: 自动转换携带来源

- **WHEN** PM Engine 因收工触发 `implementing → implemented`
- **THEN** Transition 日志 context 含对应的 run_id 与 channel

#### Scenario: 人工转换可区分

- **WHEN** 用户经 Dashboard 执行冻结/晋升等操作触发状态变化
- **THEN** context 的 channel 标明为人工来源

### Requirement: 时间轴优先消费结构化转换事件

dashboard 时间轴 MUST 优先消费状态转换日志的结构化 context 来重建转移事件；对历史（无 context）日志的 message 正则匹配 MUST 保留为兜底，MUST NOT 因缺失 context 而丢失历史转移。

#### Scenario: 新事件走结构化

- **WHEN** 存在带 context 的 Transition 记录
- **THEN** 时间轴据其结构化字段渲染，不依赖 message 文本正则

#### Scenario: 历史事件走兜底

- **WHEN** 日志中仅有旧格式（无 context）的 Transition 行
- **THEN** 时间轴仍能通过正则兜底重建该事件

### Requirement: 审计保留窗口合理

`admin_state_history.json` 的保留窗口 MUST 不小于 24 小时（当前为 1 小时，导致跨日的状态反复不可复盘）。告警历史的保留上限 MUST 与运维可复盘需求相称，并在配置或文档中明确。

> 口径（2026-09-15 评审澄清）：该窗口指监视器对 `ready`/`implementing` 状态变化的保留时长——`_update_history`（`core/admin_monitor.py:1956-1982`）只记录这两个状态的变化，且会清理非活跃 spec 的记录。非这两个状态的转换不在本要求范围内（若需复盘，另立要求）。

#### Scenario: 跨日状态历史可见

- **WHEN** 查询过去 24 小时内某 spec（期间处于 ready/implementing）的状态变化历史
- **THEN** 历史条目仍在，未被 1 小时窗口裁掉

### Requirement: supervisor 日志不得双写

supervisor 的记录函数 MUST NOT 同时 print 与写文件到同一路径（当前 stdout 被重定向到同一日志文件，导致每行成对重复）。日志文件 MUST 每事件一行。

#### Scenario: 单行单事件

- **WHEN** supervisor 记录一条 "restarting daemon..." 
- **THEN** 该日志文件中该消息只出现一次
