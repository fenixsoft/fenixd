# impl-wip-checkpoint 能力规格

## ADDED Requirements

### Requirement: 排水超时收口锚点提交（锚点 A）

规划性重启排水窗口到期仍有残留在跑 run 时，daemon 关停序列 MUST 在所有在飞 agent 进程终止完成后（`wait_for_running_agents()` 返回后）、worktree 清理（`cleanup_orphans`）之前，对保全集（preserved_wts）中每个已注册 worktree 执行一次 WIP checkpoint 提交（`git add -A` + commit）。WIP 提交 MUST NOT 在进程仍存活时执行（`_preserve_interrupted_runs` 仅写 sidecar 元数据，不提交）。

#### Scenario: 排水超时后中断分支必有可恢复提交
- **WHEN** 排水窗口到期且存在残留 run，其 worktree 内有未提交改动（10 个文件 modified、分支无 ahead 提交）
- **THEN** 关停序列在 terminate 完成后对该 worktree 产生一个 WIP 提交，分支变为 ahead of main ≥1
- **THEN** 下一 daemon 启动时 `_recovery_preserve_spec` 判定走保留分支续做（resume），不再降级清空重建

#### Scenario: worktree 静默才提交
- **WHEN** 锚点 A 执行时刻
- **THEN** 所有在飞 agent 进程已终止（SIGTERM→interrupted 标记→≤10s 缓冲→SIGKILL 收口完成后），不存在并发写盘竞态

#### Scenario: 空变更幂等跳过
- **WHEN** 被保全 worktree 无未提交改动（agent 已自行提交或工作区干净）
- **THEN** 不产生空 WIP 提交，收口序列继续

### Requirement: transient 原地退避前锚点提交（锚点 B）

runner attempt 循环判定瞬断并将写入 `transient_retry` 记录后、进入 `time.sleep(backoff)` 前，MUST 对当前 attempt 使用的 worktree 执行一次 WIP checkpoint 提交。此刻子进程已退出、worktree 静默。

#### Scenario: 退避窗口内 daemon 死亡不丢已做工作
- **WHEN** attempt 因瞬断失败进入退避 sleep（如 30s），daemon 在 sleep 窗口内死亡重启
- **THEN** 该 worktree 分支上已存在 WIP 提交（含此前全部已改内容），新 daemon recovery 对该分支判定保留续做，而非降级重建
- **THEN** 后续 attempt 以 `claude --resume` 在原 worktree 续跑时，WIP 提交的存在不影响会话续做

#### Scenario: 无 worktree 的 agent 类型跳过
- **WHEN** 瞬断重试发生于无 worktree 载体的 agent 类型/attempt 阶段
- **THEN** 跳过锚点 B，仅写 transient_retry 记录（现行行为逐字节不变）

### Requirement: WIP 提交物性

WIP checkpoint 提交 MUST：尊重 worktree 的 gitignore 规则（`.fenix/`、`dist/` 等 ignored 内容不入提交）；提交消息携带机器可识别的固定前缀（如 `fenix(wip):`）与触发锚点标识；git 操作限时（15s 级超时）。

#### Scenario: ignored 内容不入提交
- **WHEN** worktree 内存在 gitignore 命中的改动（如 `.fenix/` 运行时产物、构建产物）
- **THEN** WIP 提交仅包含 git 跟踪范围内的文件，ignored 内容保持未跟踪

### Requirement: merge-back 前塌缩

成功收口在 merge_back 之前 MUST 将实现分支上的 WIP 前缀提交塌缩：识别分支上全部 `fenix(wip):` 前缀提交，`git reset --soft` 至基点后以塌缩前最终提交消息重建成单提交，使主树合并后历史无 WIP 残留。无 WIP 提交时 MUST 为零动作（逐字节现行行为）。

#### Scenario: WIP 与最终提交塌缩成单提交
- **WHEN** 实现分支历史为 `base → fenix(wip): #1 → fenix(wip): #2 → 最终实现提交`，实现成功进入 merge-back
- **THEN** merge-back 所见分支历史为 `base → 单提交`（消息取自最终实现提交），主树合并后历史无 `fenix(wip):` 条目
- **THEN** 分支上改动的文件内容逐字节不变（soft reset 不触碰工作区）

#### Scenario: 无 WIP 提交零动作
- **WHEN** 实现分支上不存在 `fenix(wip):` 前缀提交（常规成功路径）
- **THEN** merge-back 流程与现行行为逐字节一致

#### Scenario: 只有 WIP 无最终提交（恢复续做后收口）
- **WHEN** 恢复续做的 run 成功收口，分支历史为 `base → fenix(wip): #1 → 恢复轮最终提交`
- **THEN** 塌缩后 merge-back 见单提交，消息取自恢复轮最终提交

### Requirement: 失败降级不阻塞收口

任一锚点的 WIP 提交失败（git 超时、冲突、锁竞争等）MUST 降级为 WARNING 日志留痕并继续既有收口/重试流程，MUST NOT 阻断 daemon 关停、attempt 循环或 merge-back。

#### Scenario: git 操作超时降级
- **WHEN** 锚点 A/B 的 git 提交超过时限（如 worktree 文件系统卡顿）
- **THEN** 记录 WARNING（含 spec/branch/错误摘要），收口或退避流程按无 WIP 提交的现行行为继续

### Requirement: 无配置化开关

锚点提交与塌缩行为 MUST 无条件下生效，不新增配置键（遵守「新增配置项必须带 Dashboard 界面」项目约束）。

#### Scenario: 行为不依赖配置
- **WHEN** daemon 以任意既有配置启动并发生锚点场景
- **THEN** 锚点提交与塌缩行为一致生效，无配置项参与判定
