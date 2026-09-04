# fail-counter-budget 增量规格

## ADDED Requirements

### Requirement: 验证失败计数仅在 PASS 时归零
`_verify_fail_rounds` MUST 仅在验证裁决 PASS（推进 verified/done 路径）时归零；原地打回重派、修复轮完成、实现收工等任何中间转换 MUST NOT 归零该计数。

#### Scenario: 修复重派保留计数
- **GIVEN** spec 第 2 轮验证失败（计数 2），修复 implementer 重派并完成
- **WHEN** 再次验证失败
- **THEN** 计数递增为 3，触发既有升级闸门冻结

#### Scenario: 验证通过归零
- **GIVEN** spec 计数 2
- **WHEN** 验证 PASS 推进 verified
- **THEN** 计数归零并持久化

### Requirement: 实现尝试总预算
系统 MUST 统计每 spec 跨修复周期的实现 run 启动次数（`_impl_run_budget_used`），达到配置预算（`agents.impl_run_budget`，缺省 4）时：状态置 blocked + human-escalation-alerts 告警（含 spec、已耗次数、最近一次失败摘要），不再自动重派。

#### Scenario: 预算耗尽冻结
- **GIVEN** 某 spec 累计启动第 4 次实现 run 并再次失败收工
- **WHEN** 框架计算是否重派
- **THEN** 不重派，状态 blocked，告警注明「实现尝试预算耗尽（4/4）」

#### Scenario: 计数跨修复周期累计
- **GIVEN** 首次实现 1 次 + 修复轮实现 2 次
- **WHEN** 第 3 轮修复重派前检查
- **THEN** 使用计数为 3，允许第 4 次；第 4 次失败后触发冻结

### Requirement: 预算配置与界面
`agents.impl_run_budget` 为新增配置键，MUST 同步提供 Dashboard 配置页编辑能力（数值输入、校验范围 1-10、保存生效走既有配置热更新链路）。

#### Scenario: 界面修改预算
- **WHEN** 管理员在配置页将该值改为 6 并保存
- **THEN** 配置热更新后新预算生效，后续 spec 按 6 计数
