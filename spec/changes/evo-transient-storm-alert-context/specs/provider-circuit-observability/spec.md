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

- **GIVEN** transient_break_storm 告警已产生、全局熔断于 13:32:32Z 自然过期
- **WHEN** 熔断过期处理流程执行
- **THEN** 对应告警被自动标记 handled + 核销原因「熔断自然过期」落审计，不再留未处理升级记录

## Requirement 3: 不生成新告警类型

自动核销复用既有告警生命周期通道（alert admin store），MUST NOT 引入新的告警 kind；核销动作为审计记录而非关闭信号。