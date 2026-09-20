# agent-run-artifacts — 上下文经济性指标字段（增量）

## ADDED Requirements

### Requirement: run 转录的上下文经济性指标字段

`.fenix/runs/<run_id>.jsonl` 的终态（`result` / `error` / `cancelled` 行之后）SHALL 追加一行结构化指标事件 `{"type": "run_metrics", ...}`，至少含 `turns`（assistant 事件数）、`context_peak_tokens`（对话上下文峰值估算）、`input_tokens`、`cache_read_input_tokens`、`per_turn_input_tokens`。该行的写入 MUST 为纯读侧追加，MUST NOT 改变既有事件（`result` / `error` / `cancelled`）的写入顺序与内容，MUST NOT 使既有逐行解析（含 Dashboard 读取、读侧末行判定）失效。

#### Scenario: 指标行在终态之后追加
- **WHEN** 任意 run 结束并写入终态行
- **THEN** 转录中出现 `type: "run_metrics"` 行，且既有 `result` / `error` / `cancelled` 行内容与顺序不变

#### Scenario: 既有读侧不受影响
- **WHEN** Dashboard / 读侧按既往方式读取转录
- **THEN** 读取结果与新增指标行之前一致（新增行不参与既有语义判定）
