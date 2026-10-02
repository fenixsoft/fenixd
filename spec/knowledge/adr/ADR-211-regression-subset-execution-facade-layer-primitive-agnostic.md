# ADR-211：回归用例子集执行承载于 run_regression 门面，原语层不感知子集

date: 2026-10-03
status: accepted

## Context

定向重试轮需要只重跑失败用例子集。子集是回归**调用方**（code-fix 编排）的诉求：若把子集语义下沉进 `core.regression.run_regression` 原语，全部既有调用点（验证链、周期回归、fast-track）都暴露在不相关参数面前，原语契约被迫膨胀。同时 pytest 命令改写存在静默失效陷阱：多位置参数是收集目标**并集**，把 nodeids 追加在命令尾部会使子集跑法静默退化成全量——比不用子集更糟（烧了全量的钱还误以为跑的是子集）。

## Decision

- 子集执行承载于门面 `core/agent_runner/maintenance_runs.run_regression` 的可选参数（`subset_nodeids`）；`core.regression` 原语层不感知子集，既有调用点不传参时语义逐字不变。后续需要子集回归的车道一律经门面参数表达，MUST NOT 为绕开门面而给原语加子集参数。
- 子集命令改写固定为「取代既有收集位置参数」语义：首个收集目标位放全部 nodeids、其余收集目标删除、非收集旗标（`-q`/`--junit-xml` 等）逐字保留。MUST NOT 在命令尾部追加 nodeids。
- 改写不可安全进行时一律回退全量（fail-closed）：命令非 pytest 形态、子集为空、无既有收集目标、token 含 shell 控制操作符或命令替换记号。宁可退全量，不可跑错集。

## Consequences

- 原语层零改动、既有调用点零迁移；pytest 命令形态知识（带值选项清单、shell 操作符判定）集中收口在门面层，超出清单的命令形态按 fail-closed 兜底为全量——子集优化对非常规 verify.yaml 契约静默失效但不致跑错。
- 主机级套件锁与执行根语义对子集执行逐字不变：子集只改收集范围，不改隔离与互斥约束。
