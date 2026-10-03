# ADR-221：agent_runner 读 pm_engine 状态一律构造注入回调，禁模块级依赖

date: 2026-10-04
status: accepted

## Context

agent_runner 需要读取 pm_engine 的车道状态（如并行出题标记是否已 discarded）来决定重派让位。在 runner 内直接 import pm_engine 会把 run 执行层与管线编排层焊死：模块循环依赖、测试无法在进程内轻量装配、车道状态语义变更直接波及 runner。产物硬门（result_gate）已有按构造注入回调的既有先例，本次让位判据沿同一约定实现。

## Decision

agent_runner 对 pm_engine 状态的读取一律走构造注入回调：PMEngine 装配侧注入 reader（沿 result_gate 注入约定），runner 侧只持字段引用，MUST NOT 引入对 pm_engine 的模块依赖。回调未注入（缺省 None）、读取异常、数据缺失或损坏一律按无数据处理（fail-open），MUST NOT 因读不到编排层状态而阻断 run 的既有行为（正常重试与派发照常）。

## Consequences

- 依赖方向单向固化：编排层可感知 run 层，run 层对编排层只经注入回读；后续 runner 需要任何车道状态时扩注入回调，禁加 import。
- fail-open 语义意味着让位类决策在「回调缺席」的环境下退化为无让位——依赖其兜底的场景（隔离标记让位）在直跑 runner 的测试或工具路径中天然不生效，须由装配侧保证注入。
- 判据测试可进程内装配假 reader 精确驱动，不需要构造 PMEngine。
