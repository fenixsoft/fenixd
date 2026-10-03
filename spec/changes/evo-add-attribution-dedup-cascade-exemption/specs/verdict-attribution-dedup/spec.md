# verdict-attribution-dedup 规格

## ADDED Requirements

### Requirement: 依赖级联同因组豁免
批量归因查重 SHALL 把 dependency_skipped（依赖失败传播）场景单列为同因组：组内不参与「归一化后逐字相同 ≥3 即拒」判据，仅校验非样板字段。

#### Scenario: 纯级联组豁免
- **WHEN** 一组同文归因场景全部为 dependency_skipped（如宿主缺工具导致的依赖级联 blocked-env）
- **THEN** 不判拒绝、不触发重合成，验证照常收口

#### Scenario: 混合组仍拒
- **WHEN** 同文组含真实 failed 场景（非依赖跳过）且满足阈值
- **THEN** 照常判拒（模板套用嫌疑），reason 文案维持现状

### Requirement: 豁免决策留痕
查重对级联组的豁免决策 SHALL 留痕（拒绝 reason 体系区分「同因级联组豁免」与「模板套用嫌疑」），经既有收口链透传可追溯。

#### Scenario: 豁免留痕
- **WHEN** 查重命中纯级联组并豁免
- **THEN** 收口记录含豁免原因与场景清单，日志可追溯