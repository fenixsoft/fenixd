# verdict-attribution-dedup 规格

## ADDED Requirements

### Requirement: 依赖级联同因组豁免
批量归因查重 SHALL 把 dependency_skipped（依赖失败传播）场景单列为同因组：组内不参与「归一化后逐字相同 ≥3 即拒」判据，仅校验非样板字段。豁免锚点为框架按引擎执行结果结构化合并的 dependency_skipped 标记，judge 自行申报的同名字段不作为豁免依据。

#### Scenario: 纯级联组豁免
- **WHEN** 一组同文归因场景全部为 dependency_skipped（如宿主缺工具导致的依赖级联 blocked-env）
- **THEN** 不判拒绝、不触发重合成，验证照常收口

#### Scenario: 混合组仍拒
- **WHEN** 同文组含真实 failed 场景（非依赖跳过）且满足阈值
- **THEN** 照常判拒（模板套用嫌疑），reason 文案维持现状

#### Scenario: 伪标不豁免
- **WHEN** judge 报告条目自带 dependency_skipped 标记，但框架透传的引擎执行结果无对应依赖跳过记录
- **THEN** 不豁免，按普通同文组判据处理（防实现 run 伪标逃逸）

### Requirement: 豁免决策留痕
查重对级联组的豁免决策 SHALL 留痕（结果与日志体系区分「同因级联组豁免」与「模板套用嫌疑」），随查重结果结构返回并可追溯。

#### Scenario: 豁免留痕
- **WHEN** 查重命中纯级联组并豁免
- **THEN** 验证日志含豁免原因与场景清单（豁免不写违规记录、不触发拒绝收口链），可事后审计
