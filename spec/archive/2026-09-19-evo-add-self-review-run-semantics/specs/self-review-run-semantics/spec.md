# self-review-run-semantics 增量规格

## ADDED Requirements

### Requirement: result 型终态的业务失败语义解析
自省 run 分类时，对终态类型为 `result` 的 run MUST 进一步解析其 result 内容：命中设计固化的业务失败标记清单（含『SPEC 内容缺失』『无法实现』『预算耗尽』『零交付 / 零产出』等价不变量），或同一 run 关联 budget-exhausted / spec-missing 类结构性信号时，MUST 判为 failed（或设计的废弃类目）而非 succeeded。不得仅凭进程正常终止判定业务成功。

#### Scenario: 盲派 run 计为失败
- **WHEN** implementer run 终态为 result、result 文本含『SPEC 内容缺失，无法实现』
- **THEN** 自省统计判为 failed，不再计 succeeded

#### Scenario: 真实成功 run 不受影响
- **WHEN** run 终态为 result、result 文本为正常收尾总结且无业务失败标记
- **THEN** 照常计 succeeded

#### Scenario: 双源交叉误判护栏
- **WHEN** result 文本本身未含完整标记短语但同一 run 存在 budget-exhausted/spec-missing 结构性信号
- **THEN** 按信号判失败（护栏）；反向（文本含标记但无信号）按文本判失败（保守）

### Requirement: 失败类别可追溯
分类为业务失败的 run MUST 在统计/样本输出中保留可追溯依据（run_id + 命中标记或信号摘要），便于审计与回源。

#### Scenario: 样本输出含依据
- **WHEN** 自省摘要列出失败 run 样本
- **THEN** 各项含 run_id 与命中的业务失败依据摘要