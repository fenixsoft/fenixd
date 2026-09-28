# codefix-digest-cost-metrics 能力增量（delta）

## MODIFIED Requirements

### Requirement: 链级 rollup 数据可达性

链终局 rollup 的 run 归档计数 SHALL 覆盖链中全部 run 不漏样本，包括已被 retention 移入 .fenix/runs/archive/ 的终态 run；仅当顶层与归档两处皆缺时方按零贡献，且 SHALL NOT 中断链终局。

#### Scenario: 移档后 rollup 仍计得真实值

- **WHEN** 链末批合回触发 rollup 且链内 run 文件已仅存于 .fenix/runs/archive/
- **THEN** 结构化日志与 chain_rollup 落盘快照的 turns、tool_uses_total、text_turns 为真实值（非零）

#### Scenario: 双缺失维持零贡献

- **WHEN** 某 run 的归档文件在顶层与归档目录均不存在
- **THEN** 该 run 按零贡献，链终局正常完成不抛错