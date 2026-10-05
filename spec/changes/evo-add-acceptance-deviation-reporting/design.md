## Context

2026-10-06 核查：tasks.md:58 勾选与三条反向物证（emulator-camera-path-failure.log / injection-verify.md5 / cfc-roundtrip.log 600s 超时）成立；披露在 STATE.md:233 _impl_diagnosis 但非结构化。agents/implementer.md 第 6 条 DoD 无勾选纪律。扩展点：core/agent_runner/result_gate.py unattainable 通道（1619-1650）与 findings typed 条目已存在，新增类型属白名单内扩张；提示词同步走 core/agent_runner/prompt_builder.py 单源措辞。

## Goals / Non-Goals

- [x] 勾选纪律 + findings 验收偏差类型 + 硬门一致性校验 + 规划层消费
- [ ] 不做 MUST 词表机械扫描；不回改冻结 spec；不新增独立上报通道

## Technical Design

1. agents/implementer.md：第 6 条后追加勾选纪律（字面验收未满足不勾选；替代验收行内注明+findings 登记）。
2. core/agent_runner/result_gate.py：findings 白名单增加 acceptance-deviation（{task, literal, substitute}）；新增组合校验 success∧偏差∈completed_tasks→拒绝（[artifact-structural] 同型标签）。
3. core/agent_runner/prompt_builder.py：result_gate 单源措辞同步进实现者提示词，防两侧漂移。
4. agents/planner-plan.md：带偏差注解任务按替代方式出题；配套 tasks.md 行内注明规范。
5. 防护：无偏差条目 run 零新增开销；校验只在 success 路径触发，partial/unattainable 不受影响。

## Open Questions

- findings 验收偏差条目是否要求附证据路径（替代链 md5 文件）——首版建议必填，防口头替代。