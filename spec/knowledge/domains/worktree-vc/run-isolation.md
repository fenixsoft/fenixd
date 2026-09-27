<!-- knowledge: capability=run-isolation rev=1 sources=spec/archive/evo-worktree-conflict-recovery-1789359846 -->

# run 工作树隔离与冲突恢复

worktree 创建撞锁时的归属诊断与恢复：先判定锁持有人是活动 run 还是残留，残留自动清理重试，活动并发结构化降级，且不误伤预算记账。

## 现行规则

- 锁归属诊断（活动 vs 残留）：worktree 创建遇锁冲突（`lock_key in _spec_locks`）时 MUST 先判定锁持有人状态，MUST NOT 直接失败——活动 run（进程表存在指向该 spec worktree 的存活 claude 进程）判并发，`reason=parallel-run`，不重试、不清理；残留（进程表无匹配进程、run 流不新鲜、且不处于 create 构建窗口）进入「残留清理重试」；内存锁在册但 sidecar 无记录时 MUST 判活动（fail-closed），MUST NOT 判残留。
- 存活判据以进程表信号为主，MUST NOT 单凭 run 流转录缺失：流新鲜度查询只覆盖 `impl-`/`verify-` 前缀，而 `planner-plan`/`planner-judge`/`spec-review`/`admin`/`evo` 的 run 流前缀均不匹配，且 planner 的 worktree 目录仍为 `impl-` 前缀——单凭该信号会把正在运行的 planner 判为残留。worktree 活跃记录持久化 run_id 与创建时间，供诊断读取。
- 残留清理重试：判定残留时先安全清理后重试创建一次，重试仍失败才降级，原因 `stale-recovery-failed`。清理满足既有删除约定：删除前对该 worktree 快照留档（`_snapshot_dirty_worktree`）；跳过保护集（`.fenix/interrupted_runs.json` 在册项与活动集在册项）；经 `git worktree remove --force` 并 `prune`，MUST NOT 直接 rmtree 目录树。非冲突类失败（git 命令失败/超时）不进清理重试，原因 `env-failure`；锁龄处于 create 构建窗口（worktree add + seed + deps 供给未完成）时判活动保留，不误判残留。
- 降级诊断化：降级到 legacy verifier 时以既有 `degrade_context.json` 通道落盘结构化原因（`reason` 取值 `parallel-run` | `stale-recovery-failed` | `env-failure`，含 spec 与活跃 run id），经 `verify_report` 注入后 Dashboard 可见；不新建平行的日志/信号通道。原因覆盖异常驱动的降级路径（planner-plan 失败、planner-judge 失败），并从 worktree 冲突点经 `AgentRunResult.error` 传递到降级落盘点，不得丢弃为裸串 `Failed to create worktree`。
- 锁冲突不按死亡 run 归因：锁冲突属基础设施状态，MUST NOT 判为「run 异常死亡」而回退预算或计入 retry（dispatch 死亡 run 豁免判据 `impl_status is None` 不得命中）；处置口径与 `provider circuit open` 先例一致。派发层既有的锁冲突退避与 `dispatch_stalled` 升级语义保持不变，create 层不排定重试定时器、不写 STATE 退避字段。

## 溯源

- 2026-09-14 evo-worktree-conflict-recovery-1789359846 — 新增锁归属诊断（活动/残留判定与 sidecar 缺记 fail-closed）、残留清理重试（快照留档/保护集/force remove）、降级原因结构化通道与锁冲突不按死亡 run 归因
