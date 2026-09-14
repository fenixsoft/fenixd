# run-isolation 增量规格

## ADDED Requirements

### Requirement: 锁归属诊断（活动 vs 残留）

worktree 创建遇锁冲突（`lock_key in _spec_locks`）时，框架 MUST 先判定锁持有人状态，MUST NOT 直接失败：

- 活动 run（进程表存在指向该 spec worktree 的 claude 进程）→ 判并发，`reason=parallel-run`，MUST NOT 重试、MUST NOT 清理；
- 残留（进程表无匹配进程、run 流不新鲜、且不处于 create 构建窗口）→ 判残留，进入「残留清理重试」；
- **内存锁在册但 sidecar 无记录时 MUST 判活动（fail-closed）**，MUST NOT 判残留。

存活判据 MUST 以进程表信号为主，MUST NOT 单凭 run 流转录缺失：run 流新鲜度查询只覆盖 `impl-`/`verify-` 前缀，而 `planner-plan`/`planner-judge`/`spec-review`/`admin`/`evo` 的 run 流前缀均不匹配（实测 105/165 条），且 planner 的 worktree 目录仍为 `impl-` 前缀——单凭该信号会把正在运行的 planner 判为残留。

worktree 活跃记录 MUST 持久化 run_id 与创建时间，供诊断读取。

#### Scenario: 活动 run 持锁判并发

- **WHEN** `create()` 撞锁且进程表存在指向该 spec worktree 的存活 claude 进程
- **THEN** 判定为并发（`reason=parallel-run`），不清理、不重试，按现有语义失败返回

#### Scenario: planner 活动 run 不因流前缀不一致被判残留

- **WHEN** 持锁者是 `planner-plan`/`planner-judge`（其 run 流转录前缀非 `impl-`/`verify-`，故流新鲜度查询不命中）
- **THEN** 框架 MUST 依进程表信号判为活动，MUST NOT 清理其 worktree

#### Scenario: 无 sidecar 记录时 fail-closed

- **WHEN** 内存锁在册但 sidecar 无该锁记录（历史锁/手工加锁）
- **THEN** MUST 判活动并照常拒绝创建，MUST NOT 判残留触发清理

### Requirement: 残留清理重试

判定为残留时，框架 MUST 安全清理后重试创建一次；重试仍失败才允许降级，降级原因 `stale-recovery-failed`。

清理 MUST 满足既有删除约定：删除前对该 worktree 执行快照留档（`_snapshot_dirty_worktree`）；MUST 跳过保护集（`.fenix/interrupted_runs.json` 在册项与活动集在册项）；MUST 经 `git worktree remove --force` 并 `prune`，MUST NOT 直接 rmtree 目录树。

非冲突类失败（git 命令失败/超时）MUST NOT 进入清理重试，原因记 `env-failure`。

#### Scenario: 残留锁清理后重试成功

- **WHEN** 锁为残留（持锁者无对应进程且非构建窗口）
- **THEN** 先快照留档、清理该 worktree 并释放该锁，重试创建成功，不留降级

#### Scenario: 保护集内 worktree 不被清理

- **WHEN** 残留锁对应的 worktree 仍被 `.fenix/interrupted_runs.json` 在册项或活动集覆盖
- **THEN** MUST 跳过清理（不删目录），按清理失败路径处理并留痕

#### Scenario: 构建窗口内不误判残留

- **WHEN** 锁龄处于 create 构建窗口（worktree add + seed + deps 供给未完成）
- **THEN** MUST 判活动并保留，MUST NOT 清理

### Requirement: 降级诊断化

降级到 legacy verifier 时，框架 MUST 以既有 `degrade_context.json` 通道落盘结构化原因（`reason` 取值 `parallel-run` | `stale-recovery-failed` | `env-failure`，含 spec 与活跃 run id），经 `verify_report` 注入后 Dashboard 可见；MUST NOT 新建平行的日志/信号通道。

原因 MUST 覆盖异常驱动的降级路径（planner-plan 失败、planner-judge 失败），并使原因从 worktree 冲突点经 `AgentRunResult.error` 传递到降级落盘点（MUST NOT 在传递中丢弃为裸串 `Failed to create worktree`）。

#### Scenario: 活动 run 冲突的降级带结构化原因

- **WHEN** 活动 run 持锁导致 planner 阶段失败并降级到 legacy verifier
- **THEN** `degrade_context.json` 的 `reason` MUST 为 `parallel-run` 且含活跃 run id，Dashboard 可读

#### Scenario: 原因不在传递链中丢失

- **WHEN** worktree 创建因锁冲突失败
- **THEN** `AgentRunResult.error` MUST 携带冲突原因（非裸串），降级落盘的原因 MUST 由该字段派生

### Requirement: 锁冲突不按死亡 run 归因

锁冲突属基础设施状态，MUST NOT 被判定为「run 异常死亡」而回退预算或计入 retry（判据见 `dispatch.py` 死亡 run 豁免 `impl_status is None`）；处置口径与 `provider circuit open` 先例一致。

派发层既有的锁冲突退避与 `dispatch_stalled` 升级语义 MUST 保持不变，create 层 MUST NOT 排定重试定时器或写 STATE 退避字段。

#### Scenario: 锁冲突不触发死亡 run 豁免

- **WHEN** 某 spec 因 worktree 锁冲突导致本轮未产出 run-result
- **THEN** budget 审计日志 MUST NOT 出现该 spec 的「死亡 run」豁免记录（或以可区分原因排除），retry 计数 MUST NOT 因该冲突递增

#### Scenario: 派发层退避语义不变

- **WHEN** implementer 派发遇活动 worktree 锁
- **THEN** 仍走既有退避序列（不消耗 attempt 配额，序列耗尽发 `dispatch_stalled`），本变更加入的判定 MUST NOT 改变该行为

## 验收标准

- 残留锁冲突 → 自动清理（先留档、跳保护集）+ 重试成功（不留降级）。
- 活动锁冲突 → 降级原因字段为 `parallel-run` 且含活跃 run id；`planner-plan` 场景同样判活动。
- 锁冲突不落入死亡 run 预算豁免。
- 单测覆盖锁归属判定（含前缀盲区与 fail-closed 缺省）与清理重试。
