# 重规划场景消费门
<!-- knowledge: capability=scenario-replan-consumption-gate rev=1 sources=spec/archive/2026-09-15-fix-frozen-scenario-orphan-reservoir -->

场景验收失败退回 plan 重跑前的反馈消费硬门与分级升级通道：planner 未消化上轮错误清单就拒绝再次重跑，杜绝坏产物原样复发。

## 现行规则

- 重跑前反馈消费硬门：场景验收失败退回 plan 重跑时，系统将本轮错误清单与上一轮比对——错误清单与上一轮相同（含一字不差）或上一轮错误全部复现 → 判定「planner 未消费反馈」，拒绝再次派发重跑（日志含 ERROR 留痕）；仅当上轮错误出现实质性消除（错误数减少或错误主体变化）时才允许在重排预算内继续重跑，重跑 prompt 内联当前错误清单。
- 分级升级通道：消费硬门拒绝重跑后走分级升级而非直接转人工——第一级阻塞 spec 并自动呼叫 Administrator 处置场景文件；admin 修复后重验通过则恢复正常流转（`_env_block_rounds` 归零）；admin 处置后重验仍失败达到阈值（连续 2 轮）时结构化冻结并升级人工，人工裁决项为「是否删除冻结场景集批准重新出题」，告警附上一轮 planner run 的实际成本（tokens/费用/时长）作重出题裁决参考。升级复用 `_escalate_env_blocked` 骨架（blocked → admin → 阈值冻结 → 人工），不另起通道。
- admin 修复过 schema 门且双文件一致：admin 处置场景文件的修复写入必须经过写端结构校验门，且必须保持 `test_scenarios.json` 与 `scenarios.json`（持久化集）的一致清理——修复或删除任一文件中的坏条目时，另一文件中的同源条目同步处理，防止储库复活；admin 处置 prompt 明示这两条约束，处置结果记录两个文件的清理情况。

## 溯源

- 2026-09-15 fix-frozen-scenario-orphan-reservoir（spec/archive/2026-09-15-fix-frozen-scenario-orphan-reservoir） — 新增重跑前反馈消费硬门、分级升级通道（拒绝派发 → admin 自动处置 → 人工裁决重出题）与 admin 修复过写端门/双文件一致约束（此前 planner 坏产物原样复发，重复成本全数支付且每轮外溢为 admin/人工往返）
