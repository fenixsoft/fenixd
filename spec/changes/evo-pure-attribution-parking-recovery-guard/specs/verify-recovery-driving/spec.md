# Capability: verify-recovery-driving

纯归因停泊态与 Recovery 重派防重放——testing 无驱动场景的停泊、守卫与退出语义。

## ADDED Requirements

### Requirement: 纯归因模式须停泊在不可调度保持态

验证受理门拒收修复申报并转「无修复纯归因模式」时，spec MUST 停泊在不可调度保持态（复用既有 `_frozen_hold` 字段置位并留痕停泊原因），MUST NOT 停留在无驱动的可调度 testing 态。

- 停泊置位 MUST NOT 置 `frozen` 字段：一切派发由 `frozen` 挡、blocked_stuck 豁免、unfreeze 流程与 dashboard 用户冻结标签等冻结连带语义为用户冻结专用；停泊是框架有意等待态，二者语义不同面。
- `_frozen_hold` 单独置位按既有字段注释不挡任何链路（state_machine.py:341 段：恢复链路不因它跳过）；停泊的不可调度性由无驱动共享判定 `spec_is_undriven` 单点的停泊检查达成——admin_monitor 孤儿探测与 event_bus `_recover_testing` 同源消费，MUST NOT 两调用点各写一份。
- 停泊态 MUST NOT 被 orphaned_state 探测判为无驱动异常，MUST NOT 被 Recovery 恢复路径自动重派验证。
- 停泊退出锚点：人工处置（unfreeze）、新修复 run 落地、场景集变更三者任一发生 MUST 解除停泊并恢复验证驱动；停泊态 spec 经 unfreeze 退出 MUST NOT 触发 `_resolve_preserved_branch` 保留分支续做（停泊非「冻结终止现场保全」），按普通解冻清理 + 重派退出。

#### Scenario: 拒收转纯归因后停泊且无自动扰动
- **WHEN** 受理门拒收 scenario-repaired 申报转纯归因，spec 置 `_frozen_hold` 停泊位（`frozen` 不置位）并留痕停泊原因
- **THEN** orphaned_state 探测不产生无驱动告警、Recovery 不重派验证、judge rerun 计数不变；停泊原因经 error/停泊字段可核查

#### Scenario: 退出锚点解除停泊
- **WHEN** 停泊态 spec 发生 unfreeze 人工处置、新修复 run 落地或场景集写回任一退出锚点
- **THEN** 停泊解除并恢复正常验证驱动；unfreeze 退出不走保留分支续做，按普通解冻清理 + 重派执行

#### Scenario: 停泊态不误触冻结续做
- **WHEN** 停泊态 spec（`_frozen_hold=True` 且 `frozen` 不在场）经续做判定路径
- **THEN** 不按「曾被冻结终止、现场已保全」解析保留分支续做（`_resolve_preserved_branch` 不触发）

### Requirement: 恢复重派须防重放

Recovery 对 undriven testing 重派验证前，MUST 检查「场景集+产物指纹未变且末轮 judge 归因含未修复 test-defect」；命中且该失败结论已至少被复核重验一次时，MUST 跳过执行、沿用既有归因且不递增 judge rerun 计数。

- 失败结论仅在已复核重验至少一次后可沿用；首次情形 MUST 仍执行一次复核重验，不得直接沿用（与「缓存不得加固失败结论」治理原则对齐）。
- 「已复核重验至少一次」MUST 以跨 daemon 重启持久的载体记账（跨轮持久 STATE 字段或跨轮缓存产物）；进程内变量不满足。
- 场景集或产物指纹变化时守卫不命中，重派行为与现状一致。

#### Scenario: Recovery 命中防重放守卫（已复核过一次）
- **WHEN** undriven testing 的场景集与产物指纹未变、末轮归因含未修复 test-defect、且该结论已复核重验至少一次，Recovery 触发重派
- **THEN** 跳过执行、沿用既有归因、judge rerun 计数不递增，不因重放再次触顶冻结

#### Scenario: Recovery 首遇指纹未变（尚未复核过）
- **WHEN** 指纹未变且末轮归因含未修复 test-defect，但该失败结论尚未被复核重验过
- **THEN** 照常执行一次复核重验，不沿用既有归因

#### Scenario: 指纹变化不命中守卫
- **WHEN** 场景集或产物指纹相对末轮归因已变化
- **THEN** 守卫不命中，重派行为与现状一致
