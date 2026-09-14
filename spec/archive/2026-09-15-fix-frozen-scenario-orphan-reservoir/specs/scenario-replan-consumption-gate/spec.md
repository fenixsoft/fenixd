# scenario-replan-consumption-gate 能力规范

## ADDED Requirements

### Requirement: 重跑前反馈消费硬门
场景验收失败退回 plan 重跑时，planner 新产物必须消除上一轮错误清单中的全部错误，方可持续重跑。系统在验收失败时 MUST 将本轮错误清单与上一轮比对：错误清单与上一轮相同（含「一字不差」情形）或上一轮错误全部复现时，MUST 判定为「planner 未消费反馈」，拒绝再次派发重跑；仅当上轮错误出现实质性消除（错误数减少或错误主体变化）时才允许在重排预算内继续重跑。

#### Scenario: 新产物与上轮错误一字不差时拒绝重跑
- **WHEN** 第 N 轮场景验收失败的错误清单与第 N-1 轮完全相同
- **THEN** 不再派发 planner 重跑，直接进入分级升级通道，日志含 ERROR「planner 未消费反馈」

#### Scenario: 错误实质性消除时允许预算内重跑
- **WHEN** 第 N 轮错误数少于第 N-1 轮（如 8 错降至 2 错）
- **THEN** 允许在剩余重排预算内继续重跑，重跑 prompt 内联当前错误清单

### Requirement: 分级升级通道
消费硬门拒绝重跑后，系统 MUST 走分级升级而非直接转人工：第一级阻塞 spec 并自动呼叫 Administrator 处置场景文件；admin 修复后重验通过则恢复正常流转；admin 处置后重验仍失败达到阈值（连续 2 轮）时 MUST 结构化冻结并升级人工，人工裁决项为「是否删除冻结场景集批准重新出题」。升级人工的告警 MUST 附带上一轮 planner run 的实际成本（tokens/费用/时长）作为重出题裁决参考。既有 `_escalate_env_blocked` 骨架（blocked → admin → 阈值冻结 → 人工）MUST 复用，不另起通道。

#### Scenario: 消费门拒绝后升级 admin 而非人工
- **WHEN** 消费硬门判定 planner 未消费反馈且拒绝重跑
- **THEN** spec 置 blocked 并自动派发 admin 处置 run，不直接产生人工升级告警

#### Scenario: admin 修复后重验通过恢复流转
- **WHEN** admin 修复场景文件且重验的验收通过
- **THEN** spec 解除阻塞恢复正常状态机流转，_env_block_rounds 归零

#### Scenario: 两轮未修复后冻结升级人工并附成本
- **WHEN** admin 处置后重验仍失败，连续第 2 轮阻塞
- **THEN** spec 结构化冻结并升级人工，告警描述含上轮 planner run 的 tokens/费用/时长，处置选项标注「删除冻结集重新出题将重付出题成本」

### Requirement: admin 修复过 schema 门且双文件一致
admin 处置场景文件时，修复写入 MUST 经过写端结构校验门（scenario-write-schema-gate 能力），且 MUST 保持 `test_scenarios.json` 与 `scenarios.json`（持久化集）的一致清理——修复或删除任一文件中的坏条目时，另一文件中的同源条目 MUST 同步处理，防止储库复活。admin 处置 prompt MUST 明示这两条约束。

#### Scenario: admin 清理保持双文件一致
- **WHEN** admin 从 `test_scenarios.json` 移除孤儿条目
- **THEN** `scenarios.json` 中的同源条目被同步移除，处置结果记录两个文件的清理情况

#### Scenario: admin 修复写入被 schema 门校验
- **WHEN** admin 将修复后的场景列表写回任一场景文件
- **THEN** 写入经过结构校验，含非法条目的修复被拒绝并反馈 admin 重修
