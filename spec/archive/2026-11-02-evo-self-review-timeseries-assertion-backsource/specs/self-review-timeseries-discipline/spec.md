# self-review-timeseries-discipline 变更

## ADDED Requirements

### Requirement: 时序聚合断言必须回源

自省条目凡含时序聚合断言（连续 N 晚/逐晚上行/回落/钉值/下界/合计/均值），落笔前 MUST 逐项回源当晚原始汇总行（daemon 日志 run_metrics/延迟汇总行）或归档档案重算。

#### Scenario: 断言落笔前逐项回源

- **WHEN** 自省条目拟写时序聚合断言（如「连续 N 晚上行」「max 三连钉」「停滞 ≥X 秒」）
- **THEN** 每项断言先对照当晚原始汇总行或档案重算核实，核对一致后方可落笔

#### Scenario: 断言句同附每晚原始数字与口径

- **WHEN** 时序聚合断言落笔
- **THEN** 断言句内同附每晚原始数字与口径（整晚总量还是单车道分量），凑不出每晚数字时不得保留聚合断言

### Requirement: 转引必须重源

引用前轮条目中的数字视为转引，MUST 重新回源当晚原始数据，不得沿用前轮条目文本。

#### Scenario: 转引前轮数字重新回源

- **WHEN** 条目引用前轮条目中的时序数字
- **THEN** MUST 重新回源当晚原始数据核实，不得以单车道分量充当整晚总量

### Requirement: 无法回源时降级

#### Scenario: 回源不能时降级或标注

- **WHEN** 某聚合断言无法回源（原始汇总行不可得或重算不一致）
- **THEN** 降级为定性描述或显式标注「未核实」，MUST NOT 保留数值断言原样落笔

### Requirement: 条款落位与契约守护

时序聚合回源纪律与既有「归因证据边界」条款（agents/self-review.md「含调查评估」清单内）同区并列，同为自省写作前置检查项；关键词契约测试守护两类纪律同时存在。

#### Scenario: 模板含两类纪律条款

- **WHEN** agents/self-review.md 被读取
- **THEN** 既有「归因证据边界」条款与新增「时序聚合断言回源」条款同时存在、同区并列

#### Scenario: 契约测试拦截静默丢失

- **WHEN** 后续模板改写静默删除任一纪律条款
- **THEN** tests/test_self_review_timeseries_discipline.py 关键词契约测试失败，阻止回退
