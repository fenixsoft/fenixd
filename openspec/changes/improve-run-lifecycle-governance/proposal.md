# Proposal: improve-run-lifecycle-governance

## Why

2026-08-27 `add-spec-context-menu` 实证了一条完整的调度治理失效链：attempt 跑满 3600s 墙钟被硬杀（当时已接近完成 E2E 验证）；resume 子进程持 worktree 锁继续运行；BLOCKER CHECK 在其启动 36 秒后判定「stuck ≥60m」执行 auto-recovery，把 spec 重置为 ready 并清空运行跟踪，却不知有存活的 resume 子进程；此后所有派发被防双派发护栏以 `worktree already active` 跳过（且重试仅 ~15 秒即耗尽），巡检组件只盯 in-progress 状态而对假 ready 盲视，spec 卡死近 1 小时直到孤儿进程自然超时才自愈——全程需人工诊断。三个环节均无自动化兜底。

## What Changes

- **超时监督**：implementer/tester 等 agent run 到达墙钟时限时不再直接硬杀。先从 run jsonl 流提取近期活动证据（最近事件时间戳、tool_use 频度），交给一个独立的判定 LLM 判断「是否仍在有效推进」；判定为推进中则按配置续期（单次时长与次数均有上限封顶），判定停滞或超出绝对上限仍硬杀并记录证据。
- **恢复一致性**：BLOCKER CHECK 的 auto-recovery 在重置 implementing 类状态前，必须先探测该 spec 是否存在存活的 attempt 子进程与活跃 worktree 锁；存活则跳过恢复并保留跟踪。worktree 锁登记支持从进程表重建（daemon 重启后不丢）。派发遇到锁冲突时改用指数退避重试且不消耗 attempt 配额，替代现状的 ~5 秒 ×3 瞬时耗尽。
- **恢复后闭环复查**：任何 auto-recovery 动作完成后，在可配置的观察窗口内复查该 spec 是否真实恢复推进；巡检范围扩展到 ready-but-blocked 假状态（ready 且长时间零派发日志 → 触发 Administrator 信号），消除「No in-progress SPECs」盲区。

## Capabilities

### New Capabilities
- `agent-run-timeout-supervision`: agent run 超时的活性判定与受限续期（Liveness-based timeout extension with bounded extensions）
- `recovery-state-consistency`: 自动恢复与活跃子进程/worktree 锁的一致性约束、锁的进程表重建、派发锁冲突退避
- `post-recovery-patrol`: 恢复动作后的闭环复查与假就绪态巡检告警

### Modified Capabilities

<!-- 无：retry-resume、admin-health-monitor、priority-parallel-scheduler 等既有能力的需求不变，
     本变更仅新增并行能力；provider-fault-fuse 不涉及本次三缺陷 -->

## Impact

- **代码**：`core/agent_runner.py`（超时路径 L1181–1326 区域：deadline 监控、活性快照、续期决策）、`core/pm_engine.py`（auto-recovery 分支 `_on_spec_ready` L108-128 与 stuck 处理）、`core/worktree_manager.py`（锁登记/释放、进程表重建接口）、巡检组件（admin_monitor / event_bus BLOCKER CHECK）
- **配置**：`.fenix/config.yaml` 新增 `agents.timeout_supervision.*`（开关、单次续期秒数、最大续期次数、判定窗口）与 `pm.recovery.followup_check_minutes` 等键；热更新机制已存在，无需改动加载器以外的新设施
- **测试**：`tests/` 下 agent_runner、pm_engine、admin_monitor 相关用例扩展（含模拟孤儿进程场景）
- **成本**：判定调用使用现有网关的便宜模型（复用 admin/fallback 模型路由），每次判定 token 开销极小；风险面是续期上限设置不当导致的运行时长延长，通过绝对上限封顶控制
