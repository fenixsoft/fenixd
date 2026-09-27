# ADR-026：断点续跑以进度数据注入，不复用运行环境

date: 2026-09-02
status: accepted

## Context

验证场景数超出单 attempt 轮次预算时，每次重试都新建 worktree、agent 上下文全新，已完成的数十个场景全部作废重跑。备选「复用上次 worktree 保留运行环境」被否：worktree 每 attempt 重建是既定安全策略（干净基线），且 agent 上下文无法跨进程保留，环境复用收益有限、状态管理复杂。

## Decision

- worktree 每 attempt 重建、跨 attempt 不复用运行环境与 agent 上下文，是验证（及一般 agent）车道的既定安全基线。
- 断点续跑以数据注入实现：进度文件（done/total/当前场景序号）在提示词构造时读取注入，attempt 从断点场景继续；场景总数沿用断点值不重数，done 单调不减。
- 进度文件缺失、done=0 或损坏按全新开始处理，移除或忽略损坏文件，不阻塞 attempt。
- 与 implementer 的 `--resume` 续跑分属不同机制：resume 在同一 attempt 内复用本地会话上下文；attempt 之间一律走数据注入，环境一律重建。

## Consequences

- 重试只补未完成场景，不重复烧已完成部分；避免环境复用的状态管理复杂度。
- 断点真实性依赖 agent 如实写进度，由提示词强制与结果校验兜底；attempt 预算上限放宽属配置面调整，不改变本机制。
