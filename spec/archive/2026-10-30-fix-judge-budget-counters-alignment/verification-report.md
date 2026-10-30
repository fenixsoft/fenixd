# 验证报告：fix-judge-budget-counters-alignment

> ⚠️ 本报告由框架于 2026-10-27T14:50:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-27T14:50:39.433382+00:00+run-result@mtime1793112639515743700

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.05M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| repair-gate-rejects-when-exhausted | 修复预算耗尽后受理门拒收 scenario-repaired 申报（无修复纯归因模式）：耗尽态下 judge 修复申报被拒、场景文件不改写、拒收路径返回 True 提前退出裁决采纳尾段。对应 SPEC「预算耗尽后排程重验轮不再修复」Scenario 与任务 1.1/1.2①。证据：tests/test_judge_repair_budget_alignment.py::TestRepairGateRejectsWhenExhausted（受理门实现 core/pm_engine/verification/pipeline.py:1917-1960） | pass | 0/3 | - |
| repair-rejection-survives-flat-tail | 耗尽态拒收不被平铺尾段吞掉：受理门拒收返回 True 后 spec 保持 testing，MUST NOT 穿透 plan-ready/bug-found 守卫落入 _apply_verified 假收敛为 verified（D1 拒收出口契约，防「洗白」类故障）。对应任务 1.2③。证据：tests/test_judge_repair_budget_alignment.py::TestRepairGateFlowLevel::test_exhausted_rejection_not_swallowed_by_flat_tail（尾段调用方 pipeline.py:3678-3679） | pass | 0/2 | - |
| repair-exhaustion-persists-across-restart | 耗尽状态跨 daemon 重启持久：预算耗尽排程重验后模拟重启（新 pipeline 实例重读 STATE），受理门仍拒收修复申报——耗尽状态以 STATE 持久字段 _scenario_repair_exhausted_rounds 为准而非进程内存。对应 SPEC「耗尽状态跨重启持久」Scenario 与任务 2.2①。证据：tests/test_judge_repair_budget_alignment.py::TestRepairGateRejectsWhenExhausted::test_exhaustion_persists_across_restart（字段定义 core/state_machine.py:640） | pass | 0/2 | - |
| repair-path-unchanged-when-budget-remaining | 未耗尽路径逐位不变：预算未耗尽时 scenario-repaired 申报照常受理（冻结记账+尾递归重入既有修复链路零变化）、非 scenario-repaired 状态原样透传不受受理门影响。对应任务 1.2② 与 SPEC 回归要求。证据：tests/test_judge_repair_budget_alignment.py::TestRepairGateRejectsWhenExhausted::test_not_exhausted_repair_path_unchanged、test_non_repaired_status_passthrough | pass | 0/3 | - |
| hardcap-freeze-alert-carries-repair-context | 硬上限冻结告警附修复预算上下文：judge 重跑触顶（>5）冻结时告警 evidence 含修复耗尽字段值、生命周期修复申报轮数（含耗尽后拒收轮数）与最近一次修复申报摘要（场景 id 级），recommended_action 按耗尽分叉指向人工修复/归因豁免路径。对应 SPEC「告警含修复历史摘要」Scenario 与任务 3.1。证据：tests/test_judge_repair_budget_alignment.py::TestHardCapFreezeRepairContext::test_freeze_alert_carries_repair_context（evidence 拼装 core/pm_engine/verification/judge_gate.py:537-555） | pass | 0/2 | - |
| hardcap-freeze-alert-degrades-without-history | 无修复历史时冻结告警文案退化到既有形态不报错：STATE 无修复计数字段时 evidence 以「无记录」呈现、recommended_action 走既有「检查反复重跑根因」分支；字段脏值（非整数/None）按 0 兜底不崩溃。对应任务 3.2。证据：tests/test_judge_repair_budget_alignment.py::TestHardCapFreezeRepairContext::test_freeze_without_repair_history_degrades、test_freeze_with_dirty_values_no_crash | pass | 0/3 | - |
| repair-counter-clear-points-aligned | 修复预算计数清零点与 _judge_rerun_count 同族对齐：人工 unfreeze_spec 清零修复耗尽/申报/拒收计数（修复通道重开、重新获得修复预算）、verified 落定清零、admin 处置复位不清零（防毒 spec 借复位重置计数无限循环）。对应 SPEC「人工解冻重置后修复通道重开」Scenario 与任务 2.2②③。证据：tests/test_judge_repair_budget_alignment.py::TestRepairCounterClearPoints（清零点实现 state_machine.py:2448 unfreeze_spec 与 verdict_evidence.py:1383-1394 verified 分支） | pass | 0/4 | - |
| repair-budget-field-single-source | 修复预算上下文字段单点定义静态契约：SCENARIO_REPAIR_EXHAUSTED_FIELD/_judge_repair_claim_rounds/_judge_repair_rejected_rounds/_judge_repair_last_summary 四字段在 core/state_machine.py 单点定义，judge_gate.py 与 pipeline.py 均经常量导入消费，键名与字段值严格一致不裸串漂移。证据：core/state_machine.py:640-659 常量定义、core/pm_engine/verification/judge_gate.py:33-39 导入 | pass | 0/2 | - |
| repair-alignment-full-suite-green | 新增单测文件全量总闸：tests/test_judge_repair_budget_alignment.py 12 用例全绿，覆盖受理门拒收/跨重启持久/未耗尽路径不变/平铺尾段不吞/告警上下文/清零点对齐六组行为。证据：tests/test_judge_repair_budget_alignment.py（Deliverables 声明的新增测试文件） | pass | 0/4 | - |
| judge-budget-regression-suite | 既有 judge 预算/修复相关用例回归全绿：test_pm_verification.py + test_unfreeze_judge_counter_reset.py + test_judge_efficiency.py 全部通过，未耗尽路径的修复-重执行-验收链路与重跑计数解冻重置既有语义逐位一致。对应任务 4.1。证据：tests/test_pm_verification.py 等既有测试文件（本地实测 95 passed, 1 xfailed） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

