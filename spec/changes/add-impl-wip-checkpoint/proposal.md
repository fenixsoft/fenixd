# add-impl-wip-checkpoint

## Why

2026-09-09 `impl-fix-verdict-retry-misattribution` 首轮实现运行 63 分钟（10 个文件已改、未提交）因 daemon 重启被杀，中断时分支零提交，击穿 09-05 上线的 interrupt-recovery-preserve 恢复机制的前置条件（branch ahead of main），降级清空重建，第二轮从零重烧 39.9min/$17.90。排水配置已修（shutdown_drain_seconds 0→1800），但仍有两个丢失面：排水窗口超时残留 run 被 terminate（fenixd.py shutdown 链）、transient 原地退避 sleep 期间 daemon 死亡（事故中的 19s 窗口）。两者根因相同：**中断时刻分支上没有提交**。

## What Changes

- 新增**锚点 A**：排水超时收口路径的 WIP checkpoint 提交——`wait_for_running_agents()` 完成后（所有在飞进程已死、worktree 静默）、`cleanup_orphans(protected)` 之前，对保全集 worktree 逐个 `git add -A && git commit`。
- 新增**锚点 B**：transient 原地退避前的 WIP checkpoint 提交——runner attempt 循环写完 `transient_retry` 记录后、`time.sleep(backoff)` 前（子进程已死、worktree 静默）对当前 worktree 提交。
- 新增**塌缩语义**：merge-back 是普通 merge 非 squash，WIP 提交会污染主树历史；成功收口在 merge_back 前识别 WIP 前缀提交并 `git reset --soft` 塌缩成单提交（备选方案：接受入史——决策点见 design.md）。
- 与 recovery 的闭环：锚点提交落上后，`_recovery_preserve_spec` 的 ahead>0 前置自然满足，现有 `claude --resume` 续做通道自动接管，**不新建恢复协议**。
- 无新增配置键（锚点行为无条件下生效，遵守「新增配置项必须带 Dashboard 界面」项目约束）。
- 范围外：shutdown-kill 瞬断误判守卫另行处理，本 SPEC 不动瞬断判定逻辑。

## Capabilities

### New Capabilities

- `impl-wip-checkpoint`: implementer/fast-track 运行级 WIP checkpoint 锚点提交——框架在两个可证明 agent 不在写盘的生命周期锚点自动提交工作区，使中断后分支必有可恢复提交；含 merge-back 前的塌缩语义，保证主树历史无 WIP 残留。

### Modified Capabilities

（无——interrupt-recovery-preserve 的恢复协议需求不变，本能力只是让它的高价值路径更常被命中。）

## Impact

- `fenixd.py`（shutdown 收口序列：锚点 A 插入点）
- `core/agent_runner/runner.py`（attempt 循环 transient 退避路径：锚点 B；run 产物/结果处理）
- merge-back 塌缩：`core/worktree_manager.py` 或其 pm_engine 调用方（成功收口 choke point）
- recovery 链（`core/state_machine.py` `_recovery_preserve_spec`）行为不变，命中路径更常被走到——需回归覆盖
- 测试：锚点 A/B 单测、塌缩单测、空变更幂等、全量回归
