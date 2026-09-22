# verify-lane-slot-exemption 能力增量（add-verify-lane-throughput）

> planner-plan / planner-judge 派发的槽位豁免契约：验证车道不再与实现车道争抢 `max_concurrent` 槽位（对齐 spec-review 先例），同时以独立豁免上限防失控。

## ADDED Requirements

### Requirement: 验证车道豁免实现槽位钳制

派发队列的 `slots_full` 判定 MUST 对 `planner-plan` 与 `planner-judge` 车道放行（与既有 `spec-review` 豁免同模式）：当实现类 run 已占满 `max_concurrent` 槽位时，验证车道派发条目仍可派发，MUST NOT 因槽满而滞留队列等待下一个轮询窗。豁免 MUST 附独立并发上限：同类型验证车道同时在飞的 run 数上限为 1（planner-plan 与 planner-judge 各自独立计数），达到上限时该类型新派发条目按既有队列语义等待，MUST NOT 派发。豁免上限为代码常量或配置项，MUST 与 `agents.max_concurrent` 解耦（调大实现并发不放大豁免上限）。

#### Scenario: 槽满时 judge 仍可派发

- **WHEN** 3 个实现 run 占满 `max_concurrent: 3` 的全部槽位，某 spec 验证轮完成需要派发 planner-judge，且当前无其他 planner-judge 在飞
- **THEN** judge run 立即派发，不进入槽满等待；该 judge run 在飞期间不计入实现槽位计数

#### Scenario: 豁免上限内排队

- **WHEN** 某 planner-judge run 已在飞，此时另一 spec 的验证轮也到达 judge 派发点
- **THEN** 第二个 judge 派发条目等待首个 judge 结束后才派发（上限 1），实现槽位状态不影响该等待

#### Scenario: 实现并发上调不放大豁免

- **WHEN** 运维将 `agents.max_concurrent` 从 3 调整为 5
- **THEN** 验证车道豁免并发上限保持不变（各 1），派发行为除实现槽扩容外无变化
