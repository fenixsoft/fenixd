# agent-runtime Specification

## ADDED Requirements

### Requirement: run_metrics 用量回填

终态落盘 run_metrics 时（转录行与同块日志侧行同源同值），若逐消息累计用量全零（实际累计载体 total_input_tokens 与 total_cache_read_tokens 均 0），SHALL 从 run 末结果的真实用量回填既有计量字段（input_tokens、cache_read_input_tokens，派生 per_turn_input_tokens 由回填值重算）并标注计量来源；context_peak_tokens 为逐轮峰值 SHALL 不回填臆造；逐消息累计非零时 SHALL 不覆盖；run 末结果无用量时字段保持零且不异常。

#### Scenario: 网关逐消息零用量被终局回填

- **WHEN** 某 run 全部逐消息用量累计为零且 run 末结果携带真实用量
- **THEN** 落盘 run_metrics 的计量字段为真实值且来源标记为终局回填，与正常逐消息累计可区分

### Requirement: planner-plan 输出纪律约束

planner-plan 提示词模板 SHALL 含明确的输出纪律条款（约束逐轮叙述性输出、要求结论式精简表达），形态与既有 planner-judge 模板的简洁性条款一致；SHALL 不改动模板交付要求与其余段落。

#### Scenario: 模板含输出纪律条款

- **WHEN** 加载 planner-plan 提示词模板
- **THEN** 模板含输出纪律条款，且既有交付物要求原样保留