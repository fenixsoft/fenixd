# 设计：recovery watch 过渡窗口豁免

## Context

2026-09-12 21:13:33Z（worktree 清理）→ 21:13:37Z（implementer succeed）→ 21:14:02Z（merge 完成）窗口内，recovery watch 于 21:13:57Z 复查：状态不在 RECOVERY_PROGRESS_STATUSES、worktree 已清理（active_dispatch=False）→ 误判 stale → dispatch_stalled → 无效 admin run（1789247771，9 rounds）。admin 结案定性『竞态误报，5 秒后自愈』。engine.py 假就绪巡检（BLOCKER CHECK，ready_stall_threshold 20min）存在同类盲区。

## Goals / Non-Goals

- **Goals**：过渡窗口内不产生 dispatch_stalled 误报；真实 stale 检测能力不降。
- **Non-Goals**：不缩短/改动 15min 复查间隔语义；不改 dispatch_stalled 兜底（真实 stale 仍升级）；不引入新的状态字段。

## Decisions

### D1：优先采用 pending-merge 检查，不依赖新状态字段

**选择**：在判定前查询 worktree_manager 是否存在该 spec 的待合并分支（succeed 后 merge 前窗口），存在即跳过。

**理由**：直接刻画『正在过渡』这一事实，无需改动状态机；worktree_manager 已维护分支生命周期（has_active_worktree 同类可扩展）。

### D2：缓冲窗口作为次选/兜底

**选择**：若 pending-merge 查询不可用（worktree 已清理完成、merge 分支已消失），用『implementer succeed 时间戳 + 缓冲秒数』顺延。

**理由**：覆盖 pending-merge 查询无法覆盖的边界（清理后 merge 前），双保险。