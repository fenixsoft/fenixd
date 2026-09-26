# verify-lane-slot-exemption 能力增量（add-verify-lane-throughput）

> 槽位豁免契约（对象 = 入队的并行 planner-plan 条目）：并行出题车道不再与实现车道争抢 `max_concurrent` 槽位（对齐 spec-review 先例），同时以独立豁免上限防失控。planner-judge 现状为验证管线内同步派发（随 verifier 条目执行、不过派发队列），本期不建独立队列条目。

## ADDED Requirements

### Requirement: 验证车道豁免实现槽位钳制

现状锚定：验证链中过派发队列、受 `slots_full` 钳制的是入队条目（verifier 归实现车道）；planner-judge 派发是验证管线内同步调用（`_dispatch_judge_or_reuse` → `run_planner`），随 verifier 条目的 worker 执行，不单独过队列。本能力的豁免对象是 **parallel-scenario-planning 新增的并行 `planner-plan` 队列条目**。

派发队列的 `slots_full` 判定 MUST 对并行 `planner-plan` 条目放行（与既有 `spec-review` 豁免同模式）：当实现类 run 已占满 `max_concurrent` 槽位时，并行出题条目仍可派发，MUST NOT 因槽满而滞留队列等待下一个轮询窗。豁免 MUST 附独立并发上限：并行 planner-plan 同时在飞的 run 数上限为 1，达到上限时新派发条目按既有队列语义等待，MUST NOT 派发。豁免上限为代码常量或配置项，MUST 与 `agents.max_concurrent` 解耦（调大实现并发不放大豁免上限）。planner-judge 本期维持管线内同步派发、不建独立队列条目（管线随 verifier 条目启动后即不再受额外槽位检查，现状成立）；若后续 judge 独立成队列条目，沿用同模式豁免与上限。

#### Scenario: 槽满时 judge 仍可派发

- **WHEN** 3 个实现 run 占满 `max_concurrent: 3` 的全部槽位，某 spec 进入 ready 需要派发并行 planner-plan，且当前无其他并行 planner-plan 在飞
- **THEN** 出题 run 立即派发，不进入槽满等待；该 run 在飞期间不计入实现槽位计数

#### Scenario: 豁免上限内排队

- **WHEN** 某并行 planner-plan run 已在飞，此时另一 spec 进入 ready 也触发出题派发
- **THEN** 第二个出题派发条目等待首个出题 run 结束后才派发（上限 1），实现槽位状态不影响该等待

#### Scenario: 实现并发上调不放大豁免

- **WHEN** 运维将 `agents.max_concurrent` 从 3 调整为 5
- **THEN** 验证车道豁免并发上限保持不变（并行 planner-plan 为 1），派发行为除实现槽扩容外无变化
