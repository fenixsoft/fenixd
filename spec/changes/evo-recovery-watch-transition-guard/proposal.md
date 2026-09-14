## Why

2026-09-12 21:13:37Z implementer（add-framework-self-evolution a2）成功后，recovery watch 于 21:13:57Z 复查读到过渡态误判 stale，升级 dispatch_stalled（fenixd.log 5584-5597），21:16:11Z 唤起 1 个无效 admin run（1789247771, 9 rounds）；21:14:02Z merge 完成系统即自愈（仅差 5 秒，admin 结案定性『竞态误报』）。根因：recovery watch 通过条件 = 状态 ∈ RECOVERY_PROGRESS_STATUSES（implemented/testing/verified/done/pushed）**或** worktree 存在（core/pm_engine/recovery.py check_recovery_watch），而 implementer 成功后 worktree 先清理（21:13:33Z）再 merge（21:14:02Z）——过渡窗口内两条件皆不成立 → 误判。engine.py 假就绪巡检（BLOCKER CHECK，ready_stall_threshold 20min）同样无过渡窗口豁免。竞态与 spec 无关，可在任何 spec 上复发，每次产生无效 admin run。

## What Changes

- recovery watch 与假就绪巡检在判定 stale 前增加『过渡窗口』检查：spec 存在待合并分支（worktree_manager pending merge）或 implementer succeed 时间戳在缓冲窗口（设计固化秒数）内时，跳过/顺延本次判定。
- 或等价：implementer succeed 信号到达时重置/顺延该 spec 的 recovery watch 计时器。
- 无 dashboard UI、无新配置键。

## Capabilities

### New Capabilities
- `recovery-watch-transition-guard`: 状态过渡窗口内不误判 stale（pending merge / succeed 缓冲顺延）

### Modified Capabilities
无 requirement 级修改：既有 recovery 语义（15min 复查、dispatch_stalled 兜底）不变，仅在判定前置条件处新增过渡豁免。

## Impact

- **core/pm_engine/recovery.py**：check_recovery_watch 判定前增加 pending-merge / transition 缓冲检查。
- **core/pm_engine/engine.py**：假就绪巡检（BLOCKER CHECK）增加同源豁免。
- **core/agent_runner/worktree_manager.py**：暴露『待合并分支』查询（若尚未暴露，沿用 has_active_worktree 同风格）。
- **tests/**：过渡窗口不误报 + 真实 stale 仍报断言。