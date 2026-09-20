# Spec Delta: robustness

## ADDED Requirements

### Requirement: 修复选中的代码审查问题

系统 SHALL 修复以下 code-review 台账选中的问题：

- `core/agent_runner/liveness.py:996` — float() 直接转换运行超时可能抛 TypeError

#### Scenario: 修复完成

- **WHEN** 修复提交
- **THEN** 对应问题不再出现在 code-review open 列表
