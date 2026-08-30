# Design: add-recovery-legacy-check

## Context

run 生命周期有三层：同 dispatch 内 attempt 重试（复用 worktree + `claude --resume`，fix-fenix-token-waste 落地）、run 死亡恢复（孤儿清扫 → spec 回 ready → 重派，本 SPEC 的作用点）、daemon 重启（锁内存态丢失 → refresh_locks 进程表兜底）。恢复层目前直接 `worktree_manager.create()` 全新开工，死亡 run 的 worktree 被清扫器按「无进程 + 流文件陈旧」回收——add-fail-counter-budget 实证沉没 65 分钟未提交工作。跨派发 `--resume` 不可行（session 绑 provider 的 CLAUDE_CONFIG_DIR，failover 切换后必挂「No conversation found」），故本 SPEC 不做会话续跑，只做**文件级遗产的可见性与自主收编**。

## Goals / Non-Goals

- Goals：遗产保留（有界）、上下文注入、agent 自主收编/弃用、零新配置键
- Non-Goals：不做会话级续跑（跨 provider 必挂）；不担保遗产内容一致性（决策权归 agent）；不改派发互斥与锁语义；不做遗产 diff/智能合并

## Decisions

### D1 遗产注册挂在 worktree_manager，跟随 spec 生命周期
`worktree_manager` 新增 `register_legacy(spec, worktree_path, branch)`：恢复路径（refresh_locks 释放陈锁时若该 spec 随即进入恢复重派）调用注册。遗产记录为内存态 + 审计日志（不持久化——与既有锁同策略，daemon 重启后遗产按孤儿清扫兜底，宁可丢遗产不背陈状态）。清扫器对在册遗产豁免，直到后继 run 成功 merge（`_run_agent_worker` merge 成功处调用 `consume_legacy(spec)` 触发回收）或宽限期超时。

### D2 保留判定复用 refresh_locks 的释放时刻
死亡 run 的锁在 refresh_locks 中被释放的同一时刻注册遗产——单点改动、无新增扫描。宽限期跟随孤儿清扫既有周期（STALE_LOCK_IDLE_SECONDS 的同族常量），不引入独立定时器。

### D3 上下文注入点：implementer prompt 构建
`agent_runner` implementer prompt 构建处查询 `worktree_manager.get_legacy(spec)`，有则追加「遗产检查」段（路径/分支/脏文件快照 + 只读约束 + 收编或弃用的决策要求与响应格式）。脏文件快照在注入时现场 `git -C W1 status --short` 采集（O(1) 成本），截断 50 行。

### D4 收编的实现约定：复制进新 worktree，不跨 worktree 操作
agent 对遗产只读（cat/git log/diff），把要收编的文件内容写进自己 worktree 后按正常流程提交。禁止 agent 在 W1 内执行写操作——prompt 明示 + 新 run 的工作目录本就是新 worktree，物理隔离。提交信息要求含 `salvaged from <branch>` 便于溯源。

### D5 失败重试与遗产的交互
a2 若也死亡，其 worktree 同样成为遗产——遗产注册按 spec 覆盖式更新（仅保留最新一份，旧遗产直接回收），避免遗产链膨胀。

## Risks / Trade-offs

- agent 可能被遗产误导（半成品引入隐性 bug）→ 验证链照常全量验收，收编不豁免测试；弃用路径始终可用
- 遗产 worktree 占磁盘（宽限期内多留一份）→ 跟随清扫周期自动回收，量级可控
- 注入上下文增加 prompt 长度（脏文件 50 行封顶）→ 相对实现任务书基数可忽略

## Migration Plan

1. worktree_manager 遗产注册/豁免/回收 + refresh_locks 挂钩（一次提交）
2. prompt 注入段 + 收编/弃用响应格式
3. 单测（真实 add-fail-counter-budget 现场形态作夹具）
无配置变更、无数据迁移、对未死亡 run 零影响。

## Open Questions

（无）
