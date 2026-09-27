# ADR-040：死亡恢复 = 文件级遗产收编，不做跨派发会话续跑

date: 2026-09-06
status: accepted

## Context

run 死亡恢复原先直接全新开工，死亡 run 的 worktree 被「无进程 + 流文件陈旧」清扫，实证沉没 65 分钟未提交工作。跨派发 `--resume` 不可行：session 绑 provider 的 `CLAUDE_CONFIG_DIR`，failover 切换 provider 后必挂「No conversation found」——与 ADR-026「跨 attempt 不复用运行环境」同向。

## Decision

- 恢复车道只做文件级遗产的可见性与自主收编，不做会话级续跑、不做遗产 diff/智能合并。
- 遗产注册挂在 worktree_manager：锁释放时刻（refresh_locks）若该 spec 随即进入恢复重派则注册（内存态 + 审计日志，不持久化——宁可丢遗产不背陈状态，daemon 重启后按孤儿清扫兜底）；在册遗产获清扫器豁免，直至后继 run merge 成功回收或宽限期超时。
- 上下文注入点 = implementer prompt 构建：遗产路径/分支/脏文件快照（现场 `git status --short`，50 行封顶）+ 只读约束 + 收编或弃用的决策要求与响应格式。
- 收编实现约定：agent 对遗产只读（cat/git log/diff），把要收编的内容写进自己 worktree 后按正常流程提交，提交信息含 `salvaged from <branch>`；禁止跨 worktree 写操作。
- 遗产按 spec 覆盖式更新，仅保留最新一份，防遗产链膨胀；收编不豁免验证——验证链照常全量验收。

## Consequences

- 沉没工作获得有界挽回，收编/弃用决策权归 agent；遗产可能误导（半成品隐性 bug）由全量验证兜底，弃用路径始终可用。
- 遗产 worktree 在宽限期内多占一份磁盘，跟随清扫周期自动回收；不新增配置键与独立定时器。
