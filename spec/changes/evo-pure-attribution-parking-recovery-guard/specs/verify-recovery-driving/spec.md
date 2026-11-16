# Capability: verify-recovery-driving

## Adjudications

### 纯归因模式须停泊在不可调度保持态

验证受理门拒收修复申报并转「无修复纯归因模式」时，spec MUST 停泊在不可调度保持态（复用既有 _frozen_hold 类字段）并留痕停泊原因，MUST NOT 停留在无驱动的可调度 testing 态。

- 停泊态 MUST NOT 被 orphaned_state 探测判为无驱动异常，MUST NOT 被 Recovery 恢复路径自动重派验证。
- 停泊退出锚点：人工处置、新修复 run 落地、场景集变更三者任一发生 MUST 解除停泊并恢复验证驱动。

### 恢复重派须防重放

Recovery 对 undriven testing 重派验证前，MUST 检查「场景集+产物指纹未变且末轮 judge 归因含未修复 test-defect」；命中且该失败结论已至少被复核重验一次时，MUST 跳过执行、沿用既有归因且不递增 judge rerun 计数。

- 失败结论仅在已复核重验至少一次后可沿用；首次情形 MUST 仍执行一次复核重验，不得直接沿用。
- 场景集或产物指纹变化时守卫不命中，重派行为与现状一致。

## Scenario

- 拒收转纯归因：spec 停泊、无 orphaned 告警、无 Recovery 重放、rerun 计数不变。
- 停泊后场景集变更或人工处置：解除停泊，正常重验。
- Recovery 命中防重放守卫（已复核过一次）：沿用归因，rerun 不递增，不再冻结。
- Recovery 首遇指纹未变（尚未复核过）：照常执行一次复核重验。