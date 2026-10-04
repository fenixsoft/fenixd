## ADDED Requirements

### Requirement: 自省摘要既有条目段状态可分辨

自省派发 prompt 的「近 3 日既有条目」段 MUST 依据收集是否实际执行输出可分辨的陈述：未收集（read_todo 关闭）与收集为空不得共用同一文案。

#### Scenario: read_todo 关闭时输出未收集陈述

- **WHEN** admin.self_review.read_todo 为 false 且自省 prompt 组装
- **THEN** {todo_entries} 段为「未收集」语义的固定陈述（明确归因 read_todo 关闭），不含「近3日窗口内无既有条目」字样

#### Scenario: read_todo 开启且窗口内确无条目

- **WHEN** read_todo=true 且 _collect_recent_entries 收集结果为空
- **THEN** 段文案保持「近3日窗口内无既有条目」（此时为真收集后的可核实结论）

#### Scenario: read_todo 开启且有条目

- **WHEN** read_todo=true 且窗口内存在既有条目
- **THEN** 注入带 ID 标注的条目清单（行为与现状一致）