# fail-counter-budget 增量规格（计数语义修正）

## MODIFIED Requirements

### Requirement: 实现尝试总预算
系统统计每 spec 的实现 run 次数用于预算判定，计数语义为：**run 正常收工时计数生效**（成功 → 收工 merge 路径；失败 → 失败收工路径）；run 异常死亡（进程消失、零输出、网关链路耗尽，无收工结果产出）时 MUST 回退本次启动的计数增量（`used -= 1`，下限 0），并递增 `_budget_exempt_runs` 侧车。侧车达到阈值（常量 6）时发提醒级 human-escalation-alerts 告警（一次性，不冻结）。

#### Scenario: 死亡 run 不消耗预算
- **GIVEN** 某 spec used=2/4，下一次实现 run 因网关故障异常死亡（无收工结果）
- **WHEN** 恢复链路判定死亡并重派
- **THEN** used 回退为 1/4
- **AND** `_budget_exempt_runs` 递增并留审计日志

#### Scenario: 死亡侧车阈值告警
- **GIVEN** 某 spec 连续异常死亡 6 次（`_budget_exempt_runs`=6）
- **THEN** 发送一次提醒级告警（含 spec 与死亡次数），不冻结 spec

#### Scenario: 正常失败仍计数
- **GIVEN** run 正常收工但验证打回（有收工结果产出）
- **THEN** 计数不回退（既有语义不变）

### Requirement: 计数持久化原子性
`_impl_run_budget_used` 的读改写 MUST 经 state_machine 单点原子更新（复用既有文件锁机制），写入后 MUST 回读校验，不匹配时重试一次并记审计日志。

#### Scenario: 并发派发计数不丢
- **GIVEN** 恢复扫描与派发并发更新同一 spec 计数
- **WHEN** 两方完成原子更新
- **THEN** 计数为两次增量的正确累加（无丢失）
