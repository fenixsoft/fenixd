# 纯归因停泊与 Recovery 重派防重放

<!-- knowledge: capability=verify-recovery-driving rev=1
     sources=spec/changes/evo-pure-attribution-parking-recovery-guard -->

judge 拒收修复申报转「无修复纯归因模式」后，testing 态 spec 的驱动语义：停泊在不可调度保持态等待三种退出锚点，Recovery 恢复路径对指纹未变的重放轮跳过执行沿用既有归因——堵死「停泊失败无驱动→重派重放→rerun 计数递增→必然再触顶冻结」的结构性不可收敛回环。

## 规则

- 纯归因停泊态：受理门拒收修复申报转纯归因时，spec 停泊在不可调度保持态（置位 `_frozen_hold` 并留痕停泊原因），不停留在无驱动的可调度 testing 态。
- 停泊不置 `frozen` 字段：一切派发由 frozen 挡、blocked_stuck 豁免、unfreeze 流程、dashboard 用户冻结标签、冻结清理豁免等冻结连带语义均为用户冻结专用；停泊是框架有意等待态，二者不同面。停泊态不亮冻结标签，核查走受理门拒收分支既有 error 留痕与停泊位字段。
- 停泊的不可调度性不靠 `_frozen_hold` 字段自身（该字段单独置位按既有字段注释不挡任何链路），由无驱动共享判定 `spec_is_undriven` 单点的停泊检查达成——admin_monitor 孤儿探测与 event_bus Recovery 恢复同源消费，禁两调用点各写一份；停泊判定本身收口 `spec_is_parked` 单点（`_frozen_hold` 置位且 `frozen` 不在场）。
- 停泊态不被 orphaned_state 探测判为无驱动异常，不被 Recovery 恢复路径自动重派验证；judge rerun 计数在停泊期不变。
- Recovery 重派防重放守卫：重派验证前检查「场景集+产物指纹未变 且 末轮 judge 归因含未修复 test-defect」——命中且该失败结论已至少被复核重验一次时，跳过执行、沿用既有归因、不递增 judge rerun 计数；场景集或产物指纹变化时守卫不命中，重派行为与无守卫一致。
- 失败结论仅在已复核重验至少一次后可沿用：首次情形必须仍执行一次复核重验，不得直接沿用（缓存不得加固失败结论）；「已复核重验至少一次」以跨 daemon 重启持久的 STATE 字段记账，进程内变量不满足。
- 退出锚点三者任一发生即解除停泊、恢复验证驱动：人工处置（unfreeze）、新修复 run 落地、场景集变更。
- 停泊态经 unfreeze 退出不触发 `_resolve_preserved_branch` 保留分支续做（停泊非「冻结终止现场保全」，`frozen` 不在场），按普通解冻清理 + 重派退出。

## 代码锚点

- 停泊写点：`core/pm_engine/verification/pipeline.py`（受理门拒收转纯归因分支置停泊位并留痕原因）
- 停泊判定单点：`core/state_machine.py` `spec_is_parked`；停泊退出锚点观测：`core/state_machine.py` update_spec 载荷锚点信号判定
- 无驱动共享判定：`core/admin_monitor.py` `spec_is_undriven`（孤儿探测与 Recovery 恢复同源消费）
- 防重放守卫：`core/event_bus.py` `_replay_guard_should_skip`（指纹未变 + 末轮归因 test-defect + 已复核记账三判据）

## 溯源

- 2026-11-16 evo-pure-attribution-parking-recovery-guard（spec/changes/evo-pure-attribution-parking-recovery-guard/） — 新建本页：纯归因停泊态（复用 `_frozen_hold` 零新增 schema、frozen 不置位、spec_is_parked/spec_is_undriven 单点）、Recovery 防重放守卫（指纹+末轮归因+已复核记账，首次复核豁免）与三退出锚点
