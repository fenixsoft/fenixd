# Proposal: pure-attribution-parking-recovery-guard

## Why

验证链「无修复纯归因模式」存在结构性不可收敛回环：judge 拒收修复申报转纯归因后（场景文件不改写、不重入执行），spec 停在 testing 态且无任何驱动（core/pm_engine/verification/pipeline.py:1877-1990 受理门拒收后仅留痕，不排程不升级）；orphaned_state 探测把「testing 无驱动」当异常告警；Recovery 恢复路径（core/event_bus.py:640-678，守卫仅 inconclusive/undriven/admin 在飞三项）对 undriven testing 无条件重派全量验证——重放同一未修复缺陷，judge rerun 计数照常 +1（core/pm_engine/verification/judge_gate.py:717-760 派发判定处 delta=+1，清零点仅 verified+unfreeze），必然再次触顶冻结。2026-11-12 web-browser-client 一天冻结 3 次（05:05/07:15/14:28Z），触发窗口两小时内 rerun 0→6、末轮为 Recovery 自动重派而非 judge 主动复判；窗口 34 场景全量执行 6 轮、judge 5 run 实测 403.7K in/119.1K out，STATE 累计 5.04M/1.24M tokens。回环跨 spec 复发：Recovery re-triggering verify 另见 client-ux-and-input-latency（11-08）、single-app-realdevice-retest（11-09）、m3-audio-clipboard-textinput（11-12）。

## What Changes

- 纯归因停泊态：受理门拒收转纯归因时，将 spec 停泊在不可调度保持态（复用 state_machine 既有 _frozen_hold 字段，state_machine.py:341）而非留在可调度 testing，留痕停泊原因；停泊态不被 orphaned_state 探测判为无驱动异常、不被 Recovery 重派。
- Recovery 重派防重放守卫：re-triggering verify 前检查「场景集+产物指纹未变且末轮 judge 归因含未修复 test-defect」——命中且该失败结论已至少被复核重验一次时，跳过执行、沿用既有归因、不递增 rerun 计数；首次情形不沿用、照常复核一次（与「缓存不得加固失败结论」治理原则对齐）。
- 停泊退出锚点：人工处置、新修复 run 落地或场景集变更任一发生即解除停泊，恢复正常验证驱动。

## Capabilities

### New Capabilities

- `verify-recovery-driving`: 纯归因停泊态与 Recovery 重派防重放——testing 无驱动场景的停泊、守卫与退出语义。

### Modified Capabilities

（无——改动收敛在验证受理门拒收分支、事件总线恢复守卫与状态机既有字段的使用侧）

## Impact

- 代码：core/pm_engine/verification/pipeline.py（受理门拒收分支置停泊）、core/event_bus.py（orphaned/Recovery 守卫扩展）、core/state_machine.py（停泊退出锚点与计数豁免接线）；tests/test_pure_attribution_parking.py（新建）。
- 兼容性：正常修复轮、人工 unfreeze 清零（2026-11-10-fix-unfreeze-judge-counter-reset 已归档）与首次复核重验行为零变化；仅「无修复纯归因+指纹未变」一类重放被拦。
- 风险面：停泊可能掩盖需人工介入的真悬置——停泊原因留痕、退出锚点三条件保证可复活；首次复核豁免防止失败结论被无验证沿用。