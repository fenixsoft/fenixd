## ADDED Requirements

### Requirement: 验收偏差勾选纪律

implementer 提示词约束：任务字面验收未满足时 MUST NOT 勾选完成；采用替代验证路径时 MUST 在该任务行内注明「以 X 替代验收」，并在 run 结果 findings 中登记验收偏差条目（含任务、字面验收、替代方式三要素）。

#### Scenario: 替代验收行内注明

- **WHEN** 实现者以替代路径的产物顶替任务字面验收
- **THEN** 任务行内注明替代方式，且 findings 含验收偏差条目；未注明时不得勾选

### Requirement: 验收偏差结构化上报与硬门

run 结果 findings 白名单增加验收偏差类型；框架校验：run 结果 success 且偏差任务出现在 completed_tasks 中时拒绝该结果；unattainable/partial 既有通道语义不变。

#### Scenario: 成功结果不得携带未申报偏差

- **WHEN** run 结果为 success 且存在验收偏差条目，对应任务在 completed_tasks 中
- **THEN** 产物硬门拒绝该结果，要求改走 partial/unattainable 或修正勾选

#### Scenario: 规划层消费偏差注解

- **WHEN** 规划层为带验收偏差注解的任务出验证场景
- **THEN** 按注解的替代方式出题，不按字面验收出场景链