# agent-cost-control Spec

## ADDED Requirements

### Requirement: max_turns 强制执行
Fenixd SHALL 读取配置 `agents.max_turns`，并将其作为 claude CLI 的单次运行轮次上限传入（如 `--max-turns`）。未配置时 SHALL 使用默认值 50。单次 implementer/verifier/planner 运行的轮次 SHALL 不超过该上限；达到上限自动终止并触发重试逻辑，不得无界运行。

#### Scenario: max_turns 生效
- **WHEN** 配置 `agents.max_turns: 50`，implementer 被派发
- **THEN** 传给 claude CLI 的命令包含轮次上限 50

#### Scenario: 达到上限自动终止
- **WHEN** 某 implementer 运行轮次达到 max_turns
- **THEN** 进程自动终止，按失败路径进入重试逻辑，不再无界运行

### Requirement: thinking_tokens 遥测过滤
Fenixd SHALL 在读取 claude CLI stream-json 输出时丢弃 `system`/`thinking_tokens` 遥测事件，不写入 `.fenix/runs/` 产物文件。产物文件 MUST 不包含任何 `thinking_tokens` 事件行，其余事件（assistant/user/result/error）MUST 完整保留。

#### Scenario: 产物不含遥测噪音
- **WHEN** implementer 运行过程中产生 thinking_tokens 事件
- **THEN** `.fenix/runs/<run_id>.jsonl` 中不含 `subtype: thinking_tokens` 的行，其余事件完整保留

#### Scenario: 其余事件不受影响
- **WHEN** implementer 运行产生 assistant/user/result/error 事件
- **THEN** 这些事件照常写入产物文件
