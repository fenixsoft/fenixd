# 验证报告：fix-run-hang-amplification

> ⚠️ 本报告由框架于 2026-09-13T12:38:16Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 29/29 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 29/29 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 29 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 5.36M |
| 本链增量 Token（输出） | 0.09M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| hang-discrimination-heartbeat-only-not-advancing | 测试心跳不计入进度证据（hang-discrimination） | pass | 0/4 | - |
| hang-discrimination-zero-substantive-events-triggers-stagnation | 测试零实质事件触发停滞守卫（hang-discrimination） | pass | 0/3 | - |
| hang-discrimination-zero-output-shortcircuit | 测试可观测零产出短路（hang-discrimination） | pass | 0/4 | - |
| hang-discrimination-unobservable-output-no-shortcircuit | 测试输出文件不可观测时不短路（hang-discrimination） | pass | 0/2 | - |
| hang-discrimination-repeated-calls-not-criterion | 测试重复调用形态不作为判据（hang-discrimination） | pass | 0/3 | - |
| run-budget-continuity-no-reset-on-retry | 测试新 attempt 不重置为满额预算（run-budget-continuity） | pass | 0/3 | - |
| run-budget-continuity-spec-budget-exhaustion | 测试 spec 级预算耗尽进入终态（run-budget-continuity） | pass | 0/3 | - |
| run-budget-continuity-inherit-diagnosis | 测试继承上轮诊断（run-budget-continuity） | pass | 0/2 | - |
| run-budget-continuity-first-attempt-no-inherit | 测试首个 attempt 无继承（run-budget-continuity） | pass | 0/2 | - |
| run-budget-continuity-diagnosis-auditable | 测试诊断摘要可审计且非转录原文（run-budget-continuity） | pass | 0/2 | - |
| baseline-blocked-gate-suite-hang-abort | 测试套件挂起时中止并报出测试标识（baseline-blocked-gate） | pass | 0/3 | - |
| baseline-blocked-gate-normal-suite-unaffected | 测试正常套件不受影响（baseline-blocked-gate） | pass | 0/2 | - |
| baseline-blocked-gate-failure-baseline-reproduce | 测试失败在基线复现归为存量（baseline-blocked-gate） | pass | 0/3 | - |
| baseline-blocked-gate-failure-only-current | 测试失败仅本次出现归为本次引入（baseline-blocked-gate） | pass | 0/2 | - |
| baseline-blocked-gate-mixed-failure-not-exempt | 测试混合情形不得整体放行（baseline-blocked-gate） | pass | 0/2 | - |
| baseline-blocked-gate-no-rerun-after-triage | 测试归类后不再反复重跑（baseline-blocked-gate） | pass | 0/2 | - |
| baseline-blocked-gate-triage-evidence-auditable | 测试收口证据可审计（baseline-blocked-gate） | pass | 0/2 | - |
| baseline-blocked-gate-hooks-missing-skip | 测试 hooks 缺失时跳过（baseline-blocked-gate） | pass | 0/3 | - |
| concurrent-suite-isolation-port-no-preemption | 测试并发取端口不产生被抢占（concurrent-suite-isolation） | pass | 0/2 | - |
| concurrent-suite-isolation-bind-failure-retry | 测试绑定失败可重试（concurrent-suite-isolation） | pass | 0/2 | - |
| concurrent-suite-isolation-port-env-override | 测试端口可经环境变量覆盖（concurrent-suite-isolation） | pass | 0/3 | - |
| concurrent-suite-isolation-no-pseudo-failures | 测试并发全量套件不产生伪失败（concurrent-suite-isolation） | pass | 0/2 | - |
| concurrent-suite-isolation-strategy-observable | 测试隔离策略可观测（concurrent-suite-isolation） | pass | 0/2 | - |
| agent-run-timeout-supervision-still-active | 测试到达时限且流仍在活动时启动评估（agent-run-timeout-supervision） | pass | 0/2 | - |
| agent-run-timeout-supervision-zero-output-shortcircuit | 测试可观测零产出时确定性短路（agent-run-timeout-supervision） | pass | 0/2 | - |
| agent-run-timeout-supervision-judge-unavailable-failsafe | 测试判定不可用时的失败安全（agent-run-timeout-supervision） | pass | 0/3 | - |
| agent-run-timeout-supervision-advancing-extends | 测试判定为仍在有效推进则续期（agent-run-timeout-supervision） | pass | 0/3 | - |
| agent-run-timeout-supervision-stagnant-kills | 测试判定为停滞则携带证据硬杀（agent-run-timeout-supervision） | pass | 0/4 | - |
| agent-run-timeout-supervision-heartbeat-insufficient | 测试心跳不足以支撑 advancing（agent-run-timeout-supervision） | pass | 0/3 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

