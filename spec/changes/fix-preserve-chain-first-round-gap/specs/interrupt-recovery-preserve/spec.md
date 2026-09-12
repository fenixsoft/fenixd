# spec-interrupt-recovery-preserve（delta）

## MODIFIED Requirements

### Requirement: 终止前保全

daemon 在排水窗口到期终止在跑 run 前，MUST 先把每个受影响 spec 的保全上下文（spec 名、run_id、branch、worktree 路径、相对 main 的提交数、原因与时间）写入 `.fenix/interrupted_runs.json`，再执行 terminate。写入失败降级为 WARNING 日志，不阻塞停机。

branch 与 worktree 路径的取值 MUST NOT 以 STATE 的 `branch` 字段为唯一来源：STATE 缺失或为空时 MUST 回落到 worktree_manager 的 spec → worktree 事实查询（以 `git worktree list --porcelain` 与 worktree 命名约定为真相，MUST NOT 依赖 `_active_worktrees` / `_wt_branches` 内存表——后者 daemon 重启即失）反查该 spec 的在册 worktree 与其分支，并经 `is_available` 三态单源校验。仅当 STATE 与该查询均无该 spec 的载体记录时，才允许写出 `branch: ""` / `worktree: ""` 的空保全条目。

#### Scenario: 终止前 sidecar 已落盘

- **WHEN** 排水超时对某在跑 run 执行 terminate
- **THEN** terminate 前 `.fenix/interrupted_runs.json` 已包含该 spec 的 branch 与 worktree 引用

#### Scenario: 首轮在飞 run 的保全条目含 branch 与 worktree

- **WHEN** 排水超时终止的是一个首轮 implementing run，其 worktree 已在册但 STATE 的 `branch` 尚未写入（run 未到终态）
- **THEN** sidecar 条目 MUST 含事实查询解析出的 branch 与 worktree 路径，MUST NOT 写为空串

### Requirement: 恢复保留分支续做

boot recovery（recover_interrupted）对 interrupted 的 implementing spec MUST 改判定：分支存在且相对 main 有提交（`git rev-parse main..branch` 非空）→ 保留 branch 与 implementer_run 引用、标记恢复续做；worktree 在场则原地续做，worktree 缺失则从该分支重建载体；仅确认零提交时才走现行清空重建路径。恢复续做的 spec 复用既有 resume 派发语义（含 attempt 校验与继承注记）。

保留判定的分支取值 MUST 同样支持事实查询回落：STATE `branch` 为空但该 spec 的在册 worktree（经 `git worktree list` 与命名约定解析）归属分支相对 main 有未合并提交时，MUST 判定为「保留并续做」，MUST NOT 因 STATE 字段为空而直接走清空路径。

#### Scenario: 有提交分支保留并续做

- **WHEN** daemon 重启后 recovery 发现 interrupted spec 的分支含未合并提交
- **THEN** STATE 保留 branch/implementer_run，spec 按 resume 续做而非从零重派

#### Scenario: 零提交分支走现行清空

- **WHEN** interrupted spec 的分支不存在或相对 main 零提交
- **THEN** 按现行行为清空 implementer_run/branch 并新建重派，行为逐字节兼容

#### Scenario: worktree 缺失时从分支重建

- **WHEN** 保留分支的 worktree 目录已被清理
- **THEN** 恢复在该分支上创建新 worktree 续做，不静默改走全新分支

#### Scenario: STATE branch 为空但在册 worktree 有提交

- **WHEN** interrupted spec 的 STATE `branch` 为 None，但其在册 worktree 指向的分支相对 main 有未合并提交
- **THEN** 恢复判定为保留续做，MUST NOT 清空 branch/worktree 后从零重派

### Requirement: 清理协调

shutdown 与 boot 路径的 orphan worktree 清理（cleanup_orphans）MUST 跳过被保全引用覆盖的 worktree（`.fenix/interrupted_runs.json` 在册项与保留分支对应的 worktree），防止保全与清理两条链路对同一 worktree 处置不一致。

保护集的构造 MUST 同样回落事实查询：sidecar 条目未携带 worktree 引用（空串）时，MUST 以该 spec 经事实查询解析出的在册 worktree 路径补入保护集，MUST NOT 因 sidecar 条目为空而放行清理。

任何删除 worktree 目录的路径（`cleanup_orphans` 与 `cleanup`）MUST 在目录被物理删除前对该 worktree 执行 `_snapshot_dirty_worktree` 生成快照引用并记入日志；MUST NOT 仅把留档挂在「`git worktree remove` 失败的 rmtree 兜底」分支上。快照生成失败降级 WARNING，不阻塞删除。

#### Scenario: 保全 worktree 不被误删

- **WHEN** 停机保全了某 spec 的 worktree 引用后执行 cleanup_orphans
- **THEN** 该 worktree 目录保留，重启后 resume 可原地续做

#### Scenario: 保护集从事实查询回落

- **WHEN** sidecar 条目存在但其 worktree 字段为空串，而该 spec 的在册 worktree 仍在
- **THEN** 该 worktree MUST 被纳入保护集并跳过清理，MUST NOT 被当成普通 orphan 删除

#### Scenario: orphan 清理硬删前留档

- **WHEN** cleanup_orphans 对一个未受保护的 dirty worktree 执行强制删除
- **THEN** 删除前 MUST 生成该 worktree 的 dirty 快照引用并在日志留痕，事后可据快照 SHA 取证

#### Scenario: 强制删除成功路径同样留档

- **WHEN** `git worktree remove --force` 返回成功（未走 rmtree 兜底分支）
- **THEN** 该次删除 MUST 同样已在删除前完成快照留档，MUST NOT 因命令成功而跳过
