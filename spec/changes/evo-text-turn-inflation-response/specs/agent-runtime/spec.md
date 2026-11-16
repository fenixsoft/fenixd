# agent-runtime Specification

## ADDED Requirements

### Requirement: run_metrics 用量回填

终态落盘 run_metrics 时，若逐消息累计用量全零，SHALL 从 run 末结果的真实用量回填 input_tokens/output_tokens 等计量字段并标注计量来源；逐消息累计非零时 SHALL 不覆盖。

#### Scenario: 网关逐消息零用量被终局回填

- **WHEN** 某 run 全部逐消息用量累计为零且 run 末结果携带真实用量
- **THEN** 落盘 run_metrics 的计量字段为真实值且来源标记为终局回填，与正常逐消息累计可区分

### Requirement: planner-plan 输出纪律约束

planner-plan 提示词模板 SHALL 含明确的输出纪律条款（约束逐轮叙述性输出、要求结论式精简表达），形态与既有 planner-judge 模板的简洁性条款一致；SHALL 不改动模板交付要求与其余段落。

#### Scenario: 模板含输出纪律条款

- **WHEN** 加载 planner-plan 提示词模板
- **THEN** 模板含输出纪律条款，且既有交付物要求原样保留