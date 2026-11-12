# ADR-351：验证车道大屏可见性走读侧聚合、不写侧合成 run 文件

date: 2026-11-12
status: accepted

## Context

新版三段验证流水线（VerifyEngine 进程内执行、无 LLM）全程不产 `verify-` 前缀 run 文件，而指挥中心 verifier 车道卡统计唯一来源是该前缀 run（车道前缀映射），验证活动在大屏恒不可见。补可见性有两条路：写侧在验证执行时合成 `verify-` run 文件，或读侧聚合验证自有的产物现场（`.fenix/verify-progress/` 终态 report 与进度摘要）。`verify-` 前缀已被三类消费方消费——`_cancel_lane_runs` 按前缀取消车道 run、verify 单飞在飞集合、admin_monitor 失败计数；写侧合成 run 须逐一防误触发（车道取消、单飞占位、失败告警皆可能被合成物点燃），改动面与风险大。

## Decision

- 验证车道可见性走**读侧聚合**：org 聚合在项目循环内直读 `.fenix/verify-progress/` 两类产物，折入 verifier 车道卡既有字段；**不写侧合成任何 run 文件**，不触碰 `verify-` 前缀 run 的写路径与既有消费方，org 响应契约零新增键。
- 不把 planner-plan/planner-judge run 归并进 verifier 卡——它们同时服务规划与判定，归并口径失真。
- 读侧不造历史：report.json 每轮原子覆盖、无轮次历史产物，runs 计「窗内有终态验证产物的 SPEC 数」；车道卡语义是活动可见性、非审计台账，轮次审计走 spec-runs/时间轴既有通道。
- 后续任何「让不产 run 文件的车道在大屏可见」需求，默认沿用读侧聚合其自有产物现场的通道；改走写侧合成 run 前缀须显式新裁定，并逐一处置该前缀全部既有消费方。

## Consequences

- run 文件命名空间保持单一语义（agent 派发执行记录），取消/单飞/失败计数消费方零触碰零风险。
- 聚合层新增一个无缓存数据源，靠 mtime 粗筛控读放大（与 run 聚合同一口径）；可见性粒度受产物形态约束——同 SPEC 多轮不可分辨、轮次历史不可回放（由既有通道承担），在飞判定依赖进度文件 mtime 新鲜窗兜底。
