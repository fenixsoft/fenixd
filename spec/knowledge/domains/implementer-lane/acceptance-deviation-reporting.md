# 验收偏差上报与消费闭环

<!-- knowledge: capability=acceptance-deviation-reporting rev=1
     sources=spec/archive/2026-10-14-evo-add-acceptance-deviation-reporting -->

实现任务字面验收未满足时的诚实申报机制：implementer 勾选纪律约束替代验收的登记方式，run 结果 findings 结构化上报并由产物硬门拦截「假 success」，规划层按行内注解以替代方式重出场景链完成闭环。

## 规则

- 勾选纪律（implementer 提示词硬规则）：任务字面验收未满足时 MUST NOT 勾选完成；采用替代验证路径时 MUST 在该任务行内注明「以 X 替代验收」，并在 run 结果 findings 中登记验收偏差条目。未注明或未登记时，不得以替代产物申报任务完成。
- findings 条目形状：`{type: "acceptance-deviation", task, literal, substitute, evidence}`——task 为 tasks.md 任务 id，literal 为字面验收，substitute 为替代方式，evidence 为替代证据路径（必填，防口头替代）。findings 非数组、条目非对象、type 不在 impl findings 白名单、acceptance-deviation 条目缺任一要素，均按结构类拒绝。
- impl run 结果 `findings` 为数组字段，白名单当前仅 `acceptance-deviation` 一个合法 type；findings 缺省或为空数组时零拦截，无偏差 run 零新增开销。
- 硬门组合校验：run 结果 status=success 且偏差条目任务出现在 `completed_tasks` 中 → 产物硬门拒绝该结果，拒绝文案含「验收偏差」与任务 id，指引三条出路——改走 partial（unfinished 申报）/按替代场景链补验后重报/unattainable 诚实退出；归因为结构类（`[artifact-structural]`，无 task-gate 前缀，不降级）。偏差任务不在 completed_tasks 时判据不命中。
- 诚实退出通道不感知 findings：partial 结果携带偏差条目照常放行，unattainable 语义不变；校验只在 success 路径触发。
- 闭环语义：验收偏差条目只在「以替代产物顶替任务完成申报」发生的 run 内登记一次，该任务当轮 MUST NOT 勾选（经 unfinished 申报走 partial）；任务行注解为持久记录，随 merge-back 回主 spec 供规划层读取；规划层按注解以替代方式重出场景链后，后续实现轮以替代场景链为该任务验收基准，达标即可勾选且不再重复登记偏差条目（后续 success 轮硬门放行）；无可达成替代方式时走 unattainable 诚实退出。
- 规划层消费：planner-plan 对带「以 X 替代验收」注解的任务 MUST 按注解的替代方式出验证场景，MUST NOT 按字面验收出场景链；注解缺失或语义不明时仍按字面验收出题。
- 双车道同义生效：run 末产物门 `_check_impl_result_artifact`（`core/agent_runner/result_gate.py`）同时服务 implementer 与 fast-track 两车道，findings 字段与偏差硬门对两车道同义生效。
- 措辞单源：勾选纪律措辞、findings 白名单、注解短语由 `core/agent_runner/prompt_builder.py` 与 `result_gate.py` 共享同一常量对象（`ACCEPTANCE_DEVIATION_TYPE` / `IMPL_FINDINGS_TYPE_WHITELIST` / `ACCEPTANCE_DEVIATION_ANNOTATION`），提示词注入（`acceptance_deviation_discipline_section()`）与硬门校验同源，改单源即两侧生效。

## 关键行为

1. 实现轮：实现者以替代产物顶替某任务 → 任务行内注明「以 X 替代验收」+ findings 登记偏差条目（含 evidence）+ 当轮不勾选（unfinished 申报）→ run 以 partial 收尾，硬门放行。
2. 规划轮：任务行注解随 merge-back 回主 spec，planner-plan 按注解的替代方式重出该任务验证场景链。
3. 后续实现轮：以替代场景链为验收基准，达标 → 勾选 + success 收尾，不再登记偏差条目，硬门放行，任务闭环。
4. 无可达成替代方式 → unattainable 诚实退出。
5. 越界路径拦截：若实现者勾选偏差任务且 run 报 success，产物硬门当场拒绝并原地退避重试（同 session/worktree resume），实现者下一轮改走 partial 或修正勾选。

## 溯源

- 2026-10-14 evo-add-acceptance-deviation-reporting（spec/archive/2026-10-14-evo-add-acceptance-deviation-reporting） — 新增本页：implementer 勾选纪律与「以 X 替代验收」行内注解、impl run 结果 findings 字段与 acceptance-deviation 白名单（evidence 必填）、success∧偏差任务∈completed_tasks 硬门、替代场景链闭环语义与规划层消费
