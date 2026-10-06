# ADR-251：项目级产物的信号必须项目级单例，禁按命中 spec 数量放大

date: 2026-10-07
status: accepted

## Context

信号节流按 (spec, signal_type) 判定，对不同 spec 不互斥。验证契约这类项目级产物一个项目只有一份（`.fenix/verify.yaml`），同一缺陷形态（模板态挂着从未裁决）会同时命中项目内全部 ready/implementing spec——检测器若按命中 spec 逐个产出信号，N 个 spec 就放大为 N 条信号、N 次 Administrator 唤起，而它们对应的处置是同一份契约的同一件事。

## Decision

条件归属项目级产物（一份/项目）的检测器，信号必须项目级单例：同项目多 spec 命中只产出一条信号（spec 字段取首个命中 spec），不按 spec 数量放大唤起。「条件是否归属项目级」以产物的份数为准，不以信号的 spec 字段为准——信号携带 spec 字段只是唤起与节流的挂靠点，不代表处置对象是那一份 spec。

## Consequences

- 项目级缺陷单次唤起、单次处置，无按 spec 数量的放大成本。
- 逐 spec 语义的信号（如某 spec 自身的阻塞）不受本裁定约束，仍按 (spec, signal_type) 节流逐 spec 产出。
- 后续新增针对项目级产物的检测器沿用此形态；反向地，消费项目级信号时不得由 spec 字段推断「只有该 spec 受影响」。
