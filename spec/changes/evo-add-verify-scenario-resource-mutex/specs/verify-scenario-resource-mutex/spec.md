## ADDED Requirements

### Requirement: 场景资源组互斥

场景 schema 增加可选 resource_group 字段（缺省空=不受限）；并行执行时同组场景互斥——组内已有在飞场景时其余同组场景顺延到下一批；批日志与验证报告记录互斥等待标记与有效并发度；跨组与未标记场景调度行为不变。

#### Scenario: 同组场景串行

- **WHEN** 同一 resource_group 的多个场景被调度进同一批
- **THEN** 仅一个在飞执行，其余顺延至后续批次，报告含等待标记

#### Scenario: 跨组并行

- **WHEN** 不同 resource_group 的场景（或与未标记场景混合）被调度进同一批
- **THEN** 各组互不等待，同批并行执行，调度与并行度不受互斥影响

#### Scenario: 未标记场景零变化

- **WHEN** 场景未标记 resource_group
- **THEN** 调度、并行度与报告格式与既有行为完全一致

### Requirement: flaky 豁免附并行上下文

flaky 分类与豁免记录要求附同窗并行场景清单（含有效并行度）；验证报告的豁免条目缺该上下文时标记为证据不全。

#### Scenario: 豁免含并行清单

- **WHEN** 验证轮产生 flaky 豁免
- **THEN** 豁免条目附同窗并行场景清单，供复核归因