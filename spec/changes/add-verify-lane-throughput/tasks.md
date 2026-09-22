## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/pm_engine/verification/judge_gate.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/dashboard/data/summary.py
  kind: modify
- path: tests/test_verify_lane_throughput.py
  kind: new
```

## 1. 出题并行派发

- [ ] 1.1 在 spec 进入 ready 态（且无既有可用场景集）时注册并派发 planner-plan 并行车道的 pm_engine 逻辑：输入/prompt/产物路径与既有串行出题一致，run 失败走既有 planner 失败路径且不影响实现车道派发
- [ ] 1.2 spec 状态回退（打回 drafted、冻结、删除）时停止在飞并行出题 run，并使其半成品场景集不被后续验证轮直接采信（以既有冻结复用分支校验为准）
- [ ] 1.3 testing 进入时接通「场景集就绪即短路阶段 1」：`test_scenarios.json` 过既有校验则零出题直接进场景执行，校验不过按既有回落通道串行重出
- [ ] 1.4 单测（落 `tests/test_verify_lane_throughput.py`）覆盖：ready 触发派发、并行在飞共存、打回停止不采信、就绪短路零重复出题、损坏回落串行、无并行产物时行为与现状一致

## 2. 验证车道槽位豁免

- [ ] 2.1 派发队列 slots_full 判定对 planner-plan / planner-judge 放行（复用 spec-review 豁免模式），并为两类车道各加独立豁免并发上限（同类型在飞 ≤1），上限与 `agents.max_concurrent` 解耦
- [ ] 2.2 单测（落 `tests/test_verify_lane_throughput.py`）覆盖：实现槽满时验证车道放行、同类型上限内排队、`max_concurrent` 调整不改变豁免上限

## 3. judge 重裁决治理

- [ ] 3.1 judge_gate 增加（spec, 验证轮）维度真实派发计数与验证轮重置逻辑；本轮计数达 2 仍需再派时停止派发，发人工升级告警（复用既有 human-escalation-alert 通道，含历次结论摘要），spec 保持可重试状态
- [ ] 3.2 低置信可补类型（缺 evidence/截断）优先证据扩充路径：局部补证重判，每轮至多 1 次，扩充不计入重派计数；不可补类型按重裁决计数处理
- [ ] 3.3 读侧 summary 新增 `judge_fasttrack_hits` / `judge_real_dispatches` 字段（按验证轮累计，历史 spec 空值 fail-open 兼容，不改前端）
- [ ] 3.4 单测（落 `tests/test_verify_lane_throughput.py`）覆盖：停派升级、新轮计数重置、扩充不计次、统计累计、空值兼容

## 4. verdict 缓存重验

- [ ] 4.1 实现缓存键四元组（场景 id / 场景内容指纹 / 被测构建指纹 / 验证配置指纹）全等校验与三类失效条件（场景定义变化、修复 diff 触碰场景出处关联文件、验证配置变化）；出处标注缺失或指纹不可算的场景 fail-closed 照跑
- [ ] 4.2 实现修复轮重验场景集裁剪（失败场景 ∪ 受影响场景 ∪ depends_on 前置链递归），缓存采信判定写入报告并标注来源，裁剪后空执行集按零执行出报告
- [ ] 4.3 缓存读取/指纹/裁剪任何异常 fail-open 回落全量执行（WARNING 日志），零新增打回或失败终态
- [ ] 4.4 单测（落 `tests/test_verify_lane_throughput.py`）覆盖：四元组失效、出处交集失效、fail-closed 照跑、裁剪后报告完整、缓存损坏回落全量

## 5. 分片出题（低优先级）

- [ ] 5.1 场景集按 SPEC 功能组分片、多 run 并行出题与框架合并去重（id 冲突后到者重编号并记 WARNING）；若实现期发现与豁免上限/编排冲突，按 unattainable 申报收敛（附 reason/evidence）
