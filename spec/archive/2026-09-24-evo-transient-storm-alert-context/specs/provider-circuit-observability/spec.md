# Requirement: 瞬断风暴告警上下文与自动核销

## Requirement 1: 失败 attempt 聚合注入

系统触发全局熔断（transient 达阈值）时，MUST 在告警上下文（ERROR 日志 + transient_break_storm 升级信号）中附窗口内失败 attempt 的聚合清单（run_id / spec / 时间戳 / provider），与归一化指纹并列。

### Scenario: 风暴告警含 attempt 清单

- **GIVEN** 600s 窗口内 5 次瞬断失败（分属 evo-scenario-defect-reroute-stoploss / fix-recovery-path-blockers / add-dashboard-live-session，provider inferaiapi.com）
- **WHEN** 触发全局熔断
- **THEN** ERROR 日志与升级告警上下文 MUST 含窗口内 attempt 聚合列表（run_id/time/provider/spec），可据此定位风暴来源模型/provider 与波及 run

## Requirement 2: 熔断自然过期自动核销

全局熔断自然过期（dispatch resumed）时，系统 MUST 自动核销对应的 transient_break_storm 告警：标记 handled=True、记录核销原因（熔断自然过期）留审计。幂等：无对应告警或已核销时零操作。

### Scenario: 过期自动核销

- **GIVEN** transient_break_storm 告警已产生、全局熔断自然过期（实证：13:32:32Z
  「Global transient break expired — dispatch resumed」，即派发闸门查询
  `is_global_transient_break` 首次观察到 `now >= _transient_break_until` 的时点）
- **WHEN** 熔断过期处理流程执行（过期分支内联核销）
- **THEN** 对应告警被自动标记 handled=True + handled_by="auto-resolve" + 核销原因
  「熔断自然过期」落审计（经既有 AdminStore.auto_resolve 通道），不再留未处理升级记录

### Scenario: 无对应告警时不误伤

- **GIVEN** 全局熔断过期，但窗口内无 corresponding transient_break_storm 告警
  （如告警被 15 分钟节流未产生、或告警已由人工/Dashboard 标记 handled）
- **WHEN** 过期流程执行
- **THEN** 零操作、零写回：MUST NOT 创建新记录、MUST NOT 改写已 handled 条目

## Requirement 3: 不生成新告警类型

自动核销复用既有告警生命周期通道（alert admin store），MUST NOT 引入新的告警 kind；核销动作为审计记录而非关闭信号。

## Requirement 4: 过期核销的候选选择

过期核销 MUST 选中「窗口内最新的**未处理** transient_break_storm 告警」：候选获取通道
（`AdminStore.latest_signal`）不做 handled 过滤，窗口内更新的已处理条目会抢先命中，而写回
通道（`AdminStore.auto_resolve`）对已处理条目恒跳过；故实现 MUST 在候选上显式判定
`handled is not True`，否则核销静默失效。

### Scenario: 最新同类告警已处理时核销仍生效

- **GIVEN** 窗口内存在一条较新的已处理 transient_break_storm 告警（人工/Dashboard 或
  上一轮熔断自动核销产生），同时存在一条较早的未处理同类告警
- **WHEN** 熔断过期流程执行
- **THEN** 系统 MUST 选中并核销那条未处理告警（handled=True + handled_by="auto-resolve"），
  MUST NOT 因候选被已处理条目抢占而零写回、MUST NOT 改写已处理条目的任何字段