<!-- knowledge: capability=impl-wip-checkpoint rev=1 sources=spec/archive/2026-09-15-add-impl-wip-checkpoint -->

# 实现期 WIP 检查点

两个关键静默窗口（关停排水超时、瞬断退避）前的 WIP 提交保全，以及 merge-back 前的 WIP 历史塌缩——保证中断可恢复、合并历史干净。

## 现行规则

- 锚点 A（排水超时收口）：规划性重启排水窗口到期仍有残留在跑 run 时，daemon 关停序列在所有在飞 agent 进程终止完成后（`wait_for_running_agents()` 返回后）、worktree 清理（`cleanup_orphans`）之前，对保全集中每个已注册 worktree 执行一次 WIP checkpoint 提交（`git add -A` + commit）。WIP 提交不在进程仍存活时执行（`_preserve_interrupted_runs` 仅写 sidecar 元数据，不提交）；被保全 worktree 无未提交改动时不产生空提交。
- 锚点 B（transient 原地退避前）：runner attempt 循环判定瞬断并写入 `transient_retry` 记录后、进入退避 sleep 前，对当前 attempt 使用的 worktree 执行一次 WIP checkpoint 提交（此刻子进程已退出、worktree 静默）；无 worktree 载体的 agent 类型/attempt 阶段跳过锚点 B，仅写 transient_retry 记录。
- WIP 提交物性：尊重 worktree 的 gitignore 规则（`.fenix/`、`dist/` 等 ignored 内容不入提交）；提交消息携带机器可识别的固定前缀 `fenix(wip):` 与触发锚点标识；git 操作限时（15s 级超时）。
- merge-back 前塌缩：成功收口在 merge_back 之前将实现分支上的 WIP 前缀提交塌缩——识别分支上全部 `fenix(wip):` 前缀提交，`git reset --soft` 至基点后以塌缩前最终提交消息重建成单提交，使主树合并后历史无 WIP 残留；分支上改动的文件内容逐字节不变（soft reset 不触碰工作区）。无 WIP 提交时零动作（常规成功路径 merge-back 行为不变）。
- 失败降级：任一锚点的 WIP 提交失败（git 超时、冲突、锁竞争等）降级为 WARNING 日志留痕并继续既有收口/重试流程，不阻断 daemon 关停、attempt 循环或 merge-back。
- 无配置开关：锚点提交与塌缩无条件下生效，不新增配置键（遵守「新增配置项必须带 Dashboard 界面」项目约束）。

## 关键行为

- 排水超时/瞬断退避 → WIP 提交上分支（分支 ahead of main ≥1）→ daemon 重启或续做轮按保留分支续做（resume），不再降级清空重建 → 收口时 WIP 提交塌缩成单提交再 merge-back。

## 溯源

- 2026-09-15 2026-09-15-add-impl-wip-checkpoint — 确立锚点 A/B 两个 WIP 检查点、提交物性契约（gitignore/前缀/限时）、merge-back 前塌缩与失败降级
