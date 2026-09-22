## ADDED Requirements

### Requirement: Administrator 处置优先消费 choices 注册表

`agents/administrator.md` 处置契约 MUST 增补：Administrator 处置桶 2 信号时，MUST 先读取该 signal_type 的注册表选项集；处置结论 MUST 优先表达为 `choice_id` + 依据（写入处置记录结构化字段）；仅当注册表无对应选项（处置超出既有裁决空间）时才允许自由处置，且 MUST 在处置记录中回填「建议注册表新增选项」字段（含建议 id/label/action 语义）。框架消费处置记录时，`choice_id` 与人工下拉选择走同一执行路径（同一动作映射、同一留痕格式），保证自动处置与人工处置收敛为同一裁决空间。

#### Scenario: 注册表可覆盖的处置走 choice_id
- **WHEN** Administrator 处置一条 impl_budget_exhausted 冻结信号且结论是接受现状推进
- **THEN** 处置记录含结构化 `choice_id=force_advance` 与依据说明，框架按该 choice 执行动作（与人工下拉执行路径一致）

#### Scenario: 超出注册表的处置回填建议
- **WHEN** Administrator 完成一次注册表未覆盖的处置（如需手工找回 stash 内容）
- **THEN** 处置记录含「建议注册表新增选项」字段，描述该处置的可选项化形态，供自省通道消费
