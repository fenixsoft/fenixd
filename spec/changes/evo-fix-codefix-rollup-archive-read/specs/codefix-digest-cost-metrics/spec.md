# codefix-digest-cost-metrics 能力增量（delta）

## MODIFIED Requirements

### Requirement: 消化链级 rollup

code-fix 消化链（同一审查台账的批次链）走到末批或链终止时，框架 SHALL 输出链级 rollup：该链 run 总数、总轮数、总 tool_use 数、resolved/ignored 条数、条均轮数；数据 SHALL 来自框架自身记录（run 归档计数与台账核销），不依赖人工 grep 台账。run 归档计数 SHALL 覆盖链中全部 run 不漏样本，包括已被 retention 移入 .fenix/runs/archive/ 的终态 run（读取先顶层 .fenix/runs/<run_id>.jsonl，缺失回退归档副本）；仅当顶层与归档两处皆缺时方按零贡献，且 SHALL NOT 中断链终局。

#### Scenario: 移档后 rollup 仍计得真实值

- **WHEN** 链末批合回触发 rollup 且链内 run 文件已仅存于 .fenix/runs/archive/
- **THEN** 结构化日志与 chain_rollup 落盘快照的 turns、tool_uses_total、text_turns 为真实值（非零）

#### Scenario: 双缺失维持零贡献

- **WHEN** 某 run 的归档文件在顶层与归档目录均不存在
- **THEN** 该 run 按零贡献，链终局正常完成不抛错