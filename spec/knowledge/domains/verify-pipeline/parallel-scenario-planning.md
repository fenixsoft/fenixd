# 并行场景规划
<!-- knowledge: capability=parallel-scenario-planning rev=1 sources=spec/archive/2026-09-27-add-verify-lane-throughput -->

出题（planner-plan）与实现（implementer）并行的派发契约：spec 进入 ready 即出题，testing 进入时场景集已就绪则直接短路阶段 1，把出题时长从验证关键路径上摘除。

## 现行规则

- ready 态触发出题并行派发：spec 迁移至 `ready` 时 pm_engine 派发该 spec 的 planner-plan run，与实现车道独立、并行在飞；出题输入（SPEC 文档 + 被测应用现有源码）、prompt、产物路径（`.fenix/verify-progress/<spec>/test_scenarios.json`）与串行出题完全一致，产物随既有 verify-progress 拷回机制落主树。
- 失败与回退隔离：并行出题 run 失败沿既有 planner 失败处理路径（transient 重试/升级），不影响实现车道的派发与状态机；spec 状态回退（ready→drafted 打回、blocked、冻结）时在飞出题 run 按既有取消路径停止，其半成品场景集在后续验证轮不被直接采信（以冻结复用分支的既有校验为准）。
- testing 进入就绪短路：进入 `testing` 时若场景集已存在且通过冻结复用分支的全部校验（可解析、契约版本匹配、指纹有效），验证管线直接短路阶段 1 出题、进入场景执行，不再派发 planner-plan（零重复出题）；校验不通过（损坏/契约不匹配）时走既有回落通道串行重出。
- 单写者约束：并行出题仍在飞（产物未落全）时，管线有界等待其完成，或先按既有取消路径停止再串行重出；同一 spec 任意时刻至多一个 planner-plan run 处于可写 `test_scenarios.json` 的状态，不出现双写。
- 与场景冻结复用共存：并行出题产出的场景集在首轮验证完成后同样进入冻结通道，修复轮重验按冻结复用语义执行。

## 溯源

- 2026-09-27 add-verify-lane-throughput — 新增 ready 态并行出题派发与 testing 进入就绪短路（此前出题串行排在 implemented 之后，中位 36 分钟纯 LLM 生成全部落在验证关键路径上）
