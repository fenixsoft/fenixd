## Context

2026-10-06 核查：tasks.md:58 勾选与三条反向物证（emulator-camera-path-failure.log / injection-verify.md5 / cfc-roundtrip.log 600s 超时）成立；披露在 STATE.md:233 _impl_diagnosis 但非结构化。agents/implementer.md 第 6 条 DoD 无勾选纪律。扩展点：core/agent_runner/result_gate.py 的 unattainable 申报通道（parse_unattainable 消费在 1240-1290；success 完成度判据 _check_success_completion 1666、partial 一致性 _check_partial_consistency 1724）。注意：impl run 结果 schema 现无 findings 字段（_check_impl_result_artifact 1173 只校验 status/completed_tasks/unfinished/unattainable/mode）；typed findings 与合法值白名单的先例在 code-review 报告门（_validate_code_review_report 647、disposition 白名单 603-634）——本 SPEC 为 impl run 结果**新增** findings 数组字段并引入 acceptance-deviation 类型，非既有白名单内扩张；门禁归因标签 [artifact-structural] 前缀在 runner.py:4264。提示词同步走 core/agent_runner/prompt_builder.py 单源措辞（_result_gate_section 注入/校验同源惯例）。

## Goals / Non-Goals

- [x] 勾选纪律 + findings 验收偏差类型 + 硬门一致性校验 + 规划层消费
- [ ] 不做 MUST 词表机械扫描；不回改冻结 spec；不新增独立上报通道

## Technical Design

1. agents/implementer.md：第 6 条后追加勾选纪律（字面验收未满足不勾选；替代验收行内注明+findings 登记）。
2. core/agent_runner/result_gate.py：impl run 结果新增 findings 数组字段（条目 {type: "acceptance-deviation", task, literal, substitute}；_check_impl_result_artifact 同函数服务 implementer/fast-track 两车道，字段同义生效）；新增组合校验 success∧偏差任务∈completed_tasks→拒绝（复用 runner.py:4264 的 [artifact-structural] 门禁归因标签）；实现者提示词的结果模板段同步该字段说明（归任务 1.2）；partial/unattainable 路径不感知该字段、语义不变。
3. core/agent_runner/prompt_builder.py：result_gate 单源措辞同步进实现者提示词，防两侧漂移。
4. agents/planner-plan.md：带偏差注解任务按替代方式出题；配套 tasks.md 行内注明规范。
5. 防护：无偏差条目 run 零新增开销；校验只在 success 路径触发，partial/unattainable 不受影响。
6. 闭环语义（评审修补，防勾选死锁）：验收偏差条目只在「以替代产物顶替任务完成申报」发生的 run 内登记一次——该任务当轮 MUST NOT 勾选，经 unfinished 申报走 partial（unattainable 语义不变）；规划层按任务行注解以替代方式重出场景链后，后续实现轮以替代场景链为该任务验收基准，达标即可勾选且不再重复登记偏差条目（任务行注解为持久记录，随 merge-back 回主 spec 供规划层读取）；无可达成替代方式时走 unattainable 诚实退出。无此约定则偏差任务在 success 勾选清零判据（_check_success_completion，result_gate.py:1666）下永远无法闭环。

## Open Questions

- findings 验收偏差条目是否要求附证据路径（替代链 md5 文件）——首版建议必填，防口头替代。