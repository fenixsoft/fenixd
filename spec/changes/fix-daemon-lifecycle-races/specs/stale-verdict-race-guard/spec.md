# stale-verdict-race-guard

## ADDED Requirements

### Requirement: 在飞 verify 结果状态判据

verifier / planner-judge 结果处理入口 SHALL 前置判据：处理时 spec 状态非 testing（如 stale-result 防护已拨回 implemented）→ 结果按 DEBUG 级丢弃（日志注明 run_id 与当前状态），不执行状态迁移、不触发 fallback 回退重派。正常路径（结果到达时 spec 处于 testing）MUST 不受影响。

#### Scenario: 状态被拨回后旧结果静默丢弃

- **WHEN** stale-result 防护将 testing 拨回 implemented 重派 fresh verify，随后在飞旧 planner-judge 完成
- **THEN** 旧结果被 DEBUG 丢弃，无 `implemented→verified` / `implemented→done` ERROR、无假 done 日志、无 fallback 重派整轮 verifier

#### Scenario: 正常结果处理不受影响

- **WHEN** spec 处于 testing 状态，planner-judge 正常完成返回 verified 裁决
- **THEN** 结果正常消费：testing→verified 迁移照常执行，行为与现状一致

### Requirement: 拆除失败迁移 fallback 重派

结果处理被状态判据拒绝后，现有 fallback（将 spec 转回 testing 并重新派发 verifier 的路径）MUST 移除或降级为 DEBUG 丢弃的一部分，确保被拒结果不产生任何派发动作。

#### Scenario: 被拒结果零派发

- **WHEN** verify 结果在状态判据处被丢弃
- **THEN** 无新的 verifier run 被派发（可通过派发日志与 active_runs 计数断言）
