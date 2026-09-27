# codefix-digest-cost-metrics

## ADDED Requirements

### Requirement: run 工具构成指标
引擎 run 的 context metrics SHALL 增加工具构成统计：tool_use 按工具名计数、无 tool_use 的 assistant 文本行计数，与既有 turns 并列落盘与打日志，使轮数可按「读代码/改代码/自检/纯文本」归因；metrics 落盘失败 SHALL NOT 阻断 run 终态（既有语义保留）。

#### Acceptance Scenario 1: 指标落盘
- WHEN 一个 run 终局并输出 context metrics
- THEN 日志与 metrics 落盘包含 tool_use 直方图与文本行计数，且 turns 语义不变

#### Acceptance Scenario 2: 落盘失败不阻断
- WHEN 指标落盘发生异常
- THEN run 终态不受影响，仅记日志（沿用 context metrics 落盘失败的既有处理）

### Requirement: 消化链级 rollup
code-fix 消化链（同一审查台账的批次链）走到末批或链终止时，框架 SHALL 输出链级 rollup：该链 run 总数、总轮数、总 tool_use 数、resolved/ignored 条数、条均轮数；数据 SHALL 来自框架自身记录（run 归档计数与台账核销），不依赖人工 grep 台账，且 SHALL 覆盖链中全部 run 不漏样本。

#### Acceptance Scenario 3: 链收尾 rollup
- WHEN 一条消化链的末批完成（is_chain_last_batch 判定命中）
- THEN 输出一行结构化链级 rollup（run 数/轮数/tool_use/条数/条均轮数），条目计数与台账核销一致

#### Acceptance Scenario 4: 链中途终局也有累计
- WHEN 消化链以失败或跳批中途终局
- THEN 输出截至当前的全部 run 累计 rollup，供自省引用