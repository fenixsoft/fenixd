# fix-cancel-holdstate-recovery

## Why

人工取消 run 后的 hold-state 是纯隐式状态：收尾分支只写 `error`（「run 被人工取消：…」），status 不翻转（停 implementing/testing），无任何持久标记。daemon 重启时 `recover_interrupted` 只看 status∈INTERRUPTED_STATES，把被取消保持的 spec 复位 ready 并立即自动重派——人工「随根因修复一并重派」的决策被静默覆盖。2026-09-08 实证：`add-verify-contract-autodraft` 11:43 人工取消，12:20 all-done hook 重启后被自动重派（预算无谓 +1），用户意图落空。此外取消保持的 spec 滞留 implementing 且无 run 进度，会被 `_detect_stuck` 判卡死自动升级 Administrator——保持态会被监测链路二次打破。

## What Changes

- 六处取消 hold-state 收尾分支（dispatch.py：implementer / fast-track / repair；verification.py：planner-plan / planner-judge / legacy verifier）写 spec entry 持久标记 `_cancelled_hold: true`（随 STATE.md 重启存活）
- `recover_interrupted` 遇 `_cancelled_hold` spec 跳过复位与恢复重派（status/error/run 字段原样，log 留痕；重启重验计数不递增）
- `update_spec` 显式携带 status 时顺带清除标记——admin 处置复位、面板重派、unfreeze 等全部复位路径天然解锁
- `admin_monitor._detect_stuck` 对 `_cancelled_hold` spec 豁免（取消保持是有意等待态，不自动升级）
- 新增单测：跨重启存活、显式复位解锁、无标记回归、监测豁免

## Capabilities

### New Capabilities

- `cancel-holdstate-durability`: 人工取消保持的持久化（标记字段）、重启恢复尊重（跳过复位与重派）、显式复位解锁、运行期监测豁免

### Modified Capabilities

（无——取消语义出自 add-run-cancel，其 specs 已归档且无活跃 spec 级定义）

## Impact

- `core/state_machine.py`（recover_interrupted / update_spec）
- `core/pm_engine/dispatch.py`（3 处取消收尾）
- `core/pm_engine/verification.py`（3 处取消收尾）
- `core/admin_monitor.py`（stuck 检测豁免）
- `tests/test_cancel_holdstate_recovery.py`（新增）
- 无配置/UI 变更；行为变化仅影响「被人工取消」的 spec：重启后不再被自动重派，需人工/admin 显式复位才继续
