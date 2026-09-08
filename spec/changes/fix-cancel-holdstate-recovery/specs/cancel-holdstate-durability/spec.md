# cancel-holdstate-durability —— 人工取消保持的持久化与恢复尊重

## ADDED Requirements

### Requirement: 取消保持持久标记

run 被人工取消并进入 hold-state 时（dispatch.py implementer/fast-track/repair 与 verification.py planner-plan/planner-judge/legacy verifier 六处收尾分支），系统 MUST 在 spec entry 写入持久标记 `_cancelled_hold: true`（随 STATE.md 持久化、重启存活）。标记写入 MUST NOT 改变现有 hold-state 语义（status 不翻转、不动 retry/merge 计数、不入队重派、error 文案不变）。

#### Scenario: 取消收尾写入标记

- **WHEN** 任一 agent run 被人工取消并走 hold-state 收尾分支
- **THEN** 该 spec entry `_cancelled_hold` 为 true，status/error/计数与现有取消行为完全一致

### Requirement: 重启恢复尊重取消保持

`recover_interrupted` 遍历 INTERRUPTED_STATES 时 MUST 在状态分支处理之前检查 `_cancelled_hold`：命中则跳过复位、恢复重派与重启重验计数递增，spec 的 status/error/run 字段保持原样，并留痕 log。无标记 spec 的恢复行为 MUST 保持现状（implementing→ready 复位+恢复重派、testing 重验计数+复位）。

#### Scenario: 取消保持跨重启存活

- **WHEN** spec 处于取消保持（status=implementing、`_cancelled_hold`=true、error=取消文案）时 daemon 重启触发 recover_interrupted
- **THEN** 该 spec status 仍为 implementing、error 原样、`_cancelled_hold` 仍为 true，无「Recovered from interrupted state」改写，不产生恢复重派，重启重验计数不递增

#### Scenario: 无标记 spec 恢复回归不变

- **WHEN** spec 处于 implementing（无标记，run 异常中断）时 daemon 重启
- **THEN** 恢复行为与现状一致：复位 ready、error=Recovered from interrupted state、恢复重派触发

### Requirement: 显式复位解锁

`update_spec` 在 updates 显式携带 status 时 MUST 清除 `_cancelled_hold`（置 false/null）；隐式 updates（仅 error 等无 status 键）MUST NOT 清除标记。该规则覆盖 admin 处置复位、面板重派、unfreeze 等全部复位路径——任何把 spec 拉回可调度状态的显式写入即自然解锁。

#### Scenario: 显式复位后标记清除并恢复可调度

- **WHEN** 对处于取消保持的 spec 执行显式复位（update_spec 携带 status=ready，如 admin 处置路径）
- **THEN** `_cancelled_hold` 被清除，spec 按常规调度/恢复逻辑继续（后续重启恢复不再跳过）

#### Scenario: 仅写 error 的隐式更新不清标记

- **WHEN** 对处于取消保持的 spec 执行仅含 error 键的 update_spec（无 status 键）
- **THEN** `_cancelled_hold` 保持 true

### Requirement: 取消保持的监测豁免

`admin_monitor._detect_stuck` MUST 跳过 `_cancelled_hold` spec（有意等待态不产生 stuck 信号、不自动升级 Administrator）；`_detect_blocked_stuck` 与 `_detect_repeated_failures` 若会命中取消保持 spec，MUST 同样豁免。人工冻结（frozen）既有豁免不受影响。

#### Scenario: 取消保持不触发 stuck 自动升级

- **WHEN** spec 处于取消保持（implementing、无新 run 进度）超过 stuck 阈值时间
- **THEN** `_detect_stuck` 不产生 stuck 信号，无自动 Administrator 唤起
