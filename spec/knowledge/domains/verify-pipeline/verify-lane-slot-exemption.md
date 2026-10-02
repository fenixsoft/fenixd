# 验证车道槽位豁免
<!-- knowledge: capability=verify-lane-slot-exemption rev=1 sources=spec/archive/2026-09-27-add-verify-lane-throughput -->

并行出题（planner-plan）队列条目的实现槽位豁免契约：不与实现车道争抢 `max_concurrent`，以独立上限防失控。

## 现行规则

- 豁免对象：派发队列 `slots_full` 判定对并行 `planner-plan` 队列条目放行（与既有 `spec-review` 豁免同模式）——实现类 run 已占满 `max_concurrent` 槽位时，并行出题条目仍可派发，不因槽满滞留队列等待下一个轮询窗；出题 run 在飞期间不计入实现槽位计数。
- 独立并发上限：并行 planner-plan 同时在飞的 run 数上限为 1，达到上限时新派发条目按既有队列语义等待首个出题 run 结束，实现槽位状态不影响该等待。豁免上限为代码常量或配置项，与 `agents.max_concurrent` 解耦——调大实现并发不放大豁免上限。
- planner-judge 派发形态：planner-judge 为验证管线内同步派发（`_dispatch_judge_or_reuse` → `run_planner`），随 verifier 条目的 worker 执行、不过派发队列，不设独立队列条目；若后续 judge 独立成队列条目，沿用同模式豁免与上限。

## 溯源

- 2026-09-27 add-verify-lane-throughput（spec/archive/2026-09-27-add-verify-lane-throughput） — 新增并行出题条目的实现槽位豁免与独立并发上限 1（出题中位 36m 且几乎纯 LLM 生成，曾串行排在 implemented 之后并在槽满时滞留队列），验证车道出题不再与实现争抢槽位
