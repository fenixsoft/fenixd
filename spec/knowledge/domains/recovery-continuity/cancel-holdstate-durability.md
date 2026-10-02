<!-- knowledge: capability=cancel-holdstate-durability rev=1 sources=spec/archive/2026-09-14-fix-cancel-holdstate-recovery -->

# 取消保持的持久化与恢复尊重

人工取消使 run 进入 hold-state 时在 spec entry 落持久标记，保证取消保持跨 daemon 重启存活，且不被自动恢复与自动监测打断。

## 现行规则

- run 被人工取消并走 hold-state 收尾分支时（dispatch 侧 implementer / fast-track / repair 与 verification 侧 planner-plan / planner-judge / legacy verifier 共六处），在 spec entry 写入 `_cancelled_hold: true`，随 STATE.md 持久化、重启存活。
- 标记写入不改变 hold-state 语义：status 不翻转、不动 retry/merge 计数、不入队重派、error 文案不变。
- `recover_interrupted` 遍历 INTERRUPTED_STATES 时在状态分支处理之前检查 `_cancelled_hold`：命中则跳过复位、恢复重派与重启重验计数递增，spec 的 status/error/run 字段保持原样并留痕 log。
- 无标记 spec 的重启恢复不受影响：implementing→ready 复位并恢复重派、testing 递增重验计数并复位。
- `update_spec` 在 updates 显式携带 status 时清除 `_cancelled_hold`；隐式 updates（仅 error 等无 status 键）不清除。该规则覆盖 admin 处置复位、面板重派、unfreeze 等全部复位路径——任何把 spec 拉回可调度状态的显式写入即自然解锁。
- `admin_monitor._detect_stuck` 跳过 `_cancelled_hold` spec：有意等待态不产生 stuck 信号、不自动升级 Administrator；`_detect_blocked_stuck` 与 `_detect_repeated_failures` 对取消保持 spec 同样豁免。人工冻结（frozen）的既有豁免不受影响。

## 溯源

- 2026-09-14 fix-cancel-holdstate-recovery（spec/archive/2026-09-14-fix-cancel-holdstate-recovery） — 新增取消保持持久标记、重启恢复尊重、显式复位解锁与监测豁免
