# admin-narrative-summary Spec

## ADDED Requirements

### Requirement: Administrator 处置后撰写叙述性总结
Administrator SHALL 在每次处置完成后，向 `.fenix/admin_disposition.json` 写入 `summary` 字段：一段人类可读的叙述性总结。`summary` SHALL 包含：诊断结论（问题是什么、根因）、处置时间线（做了什么、顺序）、最终结果、以及对人类决策的建议（如需人工介入）。`summary` 随处置记录落盘到 `.fenix/admin_alerts.json` 的 disposition 记录中，供 Dashboard 展示。

#### Scenario: 正常处置包含叙述总结
- **WHEN** Administrator 完成一次处置并写入 disposition
- **THEN** disposition 含非空 `summary` 字段，内容包含问题、处置动作、结果

#### Scenario: 需人工决策时给出明确建议
- **WHEN** Administrator 无法自主处置（escalate=true）
- **THEN** `summary` 明确说明为何需人工介入，并给出具体建议动作

#### Scenario: 旧记录无 summary 不崩溃
- **WHEN** 界面读取无 `summary` 字段的旧 disposition 记录
- **THEN** 界面降级显示结构化字段（actions_taken/result），不报错
