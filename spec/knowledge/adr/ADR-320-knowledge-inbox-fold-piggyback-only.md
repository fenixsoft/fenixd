# ADR-320：知识候选区折叠 piggyback-only，无独立 fold 派发形态

date: 2026-11-03
status: accepted

## Context

交互会话产出的排查/立项结论经 `spec/knowledge/_inbox/` 自由格式投递后，需要收敛进真相源能力页。候选区可能长期非空：安静周（无 SPEC 归档）没有任何蒸馏触发点，积压滞留；若因此把「`_inbox` 非空」做成独立派发条件或为折叠单开一种 run 形态，就要动派发语义、新增 run 形态及其单飞/台账/恢复全套配套，回归面远大于折叠本身，而折叠在能力上本就是蒸馏（能力页维护）的一部分。

## Decision

折叠触发为 piggyback-only：distill 车道每轮入口先消化 `_inbox/` 存量条目（逐条折叠、实时校验、成功移 `done/`、失败滞留重试），再处理当轮 SPEC 蒸馏；`_inbox` 非空不构成独立派发条件，不设 fold-only run 形态。安静周的积压滞留为设计内行为，可见性由 audit 周期轮积压提醒兜底（`log.md` lint 行 + dashboard KnowledgeTab 积压计数，不走 AdminStore 人工告警）。

## Consequences

派发层零新增：无新 run 形态、无新触发点，distill 既有单飞、pending 台账与重启恢复链原样复用；折叠代码只活在 distill 车道内。代价：安静周积压最长滞留到下一轮 SPEC 归档蒸馏才被消化，折叠时效与 SPEC 归档节律绑定；可见性依赖 audit 提醒链路，提醒失效则积压静默。后续折叠类需求（如折叠优先级、批量上限）必须在 distill 车道内扩展实现，另立派发通道须显式 supersede 本裁定。
