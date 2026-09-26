# parallel-scenario-planning 能力增量（add-verify-lane-throughput）

> 出题（planner-plan）与实现（implementer）并行的派发契约：spec 进入 ready 态即派发出题 run，testing 进入时若场景集已就绪则阶段 1 直接短路。出题输入不变（SPEC 文档 + 被测应用现有源码），产物路径与校验不变（同一 `test_scenarios.json`、同一冻结复用分支）。

## ADDED Requirements

### Requirement: ready 态触发出题并行派发

spec 状态迁移至 `ready` 时，pm_engine MUST 触发该 spec 的 planner-plan 派发（与实现车道独立、并行在飞）。并行出题 run 的输入、prompt、产物路径（`.fenix/verify-progress/<spec>/test_scenarios.json`）与既有 testing 阶段串行出题完全一致；产物随既有 verify-progress 拷回机制落主树。并行出题 run 失败时 MUST 沿既有 planner 失败处理路径（transient 重试/升级）处理，MUST NOT 影响实现车道的派发与状态机。spec 后续发生状态回退（ready→drafted 打回、blocked、冻结）时，在飞并行出题 run MUST 被按既有取消路径停止，且其半成品场景集 MUST NOT 在后续验证轮被采信（以冻结复用分支的既有校验为准）。

#### Scenario: ready 即出题、与 impl 并行

- **WHEN** 某 spec 通过 spec-review 进入 `ready` 态，且其此前从未生成过场景集（`test_scenarios.json` 不存在）
- **THEN** pm_engine 派发该 spec 的 planner-plan run，此刻实现车道派发与否不影响出题 run 启动；planner-plan run 与后续 implementer run 可同时处于在飞状态

#### Scenario: spec 打回时停掉并行出题

- **WHEN** 并行出题 run 在飞期间该 spec 被 spec-review 打回（ready→drafted）或人工冻结
- **THEN** 该出题 run 被停止（既有取消路径），产生的半成品场景集在 spec 重新就绪后的新一轮出题中不被直接采信

### Requirement: testing 进入时场景集就绪短路

spec 进入 `testing` 时，若 `.fenix/verify-progress/<spec>/test_scenarios.json` 已存在且通过既有冻结复用分支的全部校验（文件可解析、契约版本匹配、指纹有效），验证管线 MUST 直接短路阶段 1 出题、进入场景执行，MUST NOT 再次派发 planner-plan（零重复出题）。校验不通过（损坏/契约不匹配）时 MUST 走既有回落出题通道串行重出，行为与现状一致。并行出题仍在飞（产物未落全）时，管线 MUST 等待其完成（有界）或先按既有取消路径停止再串行重出，MUST NOT 与在飞出题 run 并发写同一产物文件。就绪短路与场景冻结复用（scenario-reuse-on-reenter）共存：并行出题产出的场景集在首轮验证完成后同样进入冻结通道，修复轮重验按冻结复用语义执行。

#### Scenario: 场景集先于实现就绪

- **WHEN** 并行出题在 implementing 阶段完成落盘，spec 于 implemented 后进入 testing
- **THEN** 阶段 1 不派发任何 planner-plan run，验证管线直接进入场景执行；从 implemented 到首个场景执行开始的等待不含出题时长

#### Scenario: 并行产物损坏回落串行出题

- **WHEN** testing 进入时并行出题产物存在但 JSON 损坏或契约版本不匹配
- **THEN** 验证管线按既有回落通道删除/隔离坏产物并串行派发 planner-plan 重出，验证轮不因并行产物损坏而失败

#### Scenario: 无并行产物时行为与现状一致

- **WHEN** 某 spec ready 时不满足并行出题触发条件（如既有场景集已冻结复用）或并行出题被配置关闭
- **THEN** testing 进入后按既有串行出题路径执行，端到端行为与未引入本能力前一致

#### Scenario: testing 进入时并行出题仍在飞

- **WHEN** spec 进入 testing 时并行出题 run 尚未完成（`test_scenarios.json` 未落全）
- **THEN** 管线等待该 run 完成（有界超时）或先取消再走既有回落串行重出；同一 spec 任意时刻至多一个 planner-plan run 处于可写 `test_scenarios.json` 的状态，不出现双写
