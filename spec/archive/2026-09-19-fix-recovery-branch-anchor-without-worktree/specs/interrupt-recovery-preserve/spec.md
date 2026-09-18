# spec-interrupt-recovery-preserve（delta）

## MODIFIED Requirements

### Requirement: 恢复保留分支续做

boot recovery（recover_interrupted）对 interrupted 的 implementing spec MUST 改判定：分支存在且相对 main 有提交（`git rev-parse main..branch` 非空）→ 保留 branch 与 implementer_run 引用、标记恢复续做；worktree 在场则原地续做，worktree 缺失则从该分支重建载体；仅确认零提交时才走现行清空重建路径。恢复续做的 spec 复用既有 resume 派发语义（含 attempt 校验与继承注记）。

保留判定的分支取值 MUST 同样支持事实查询回落：STATE `branch` 为空但该 spec 的在册 worktree（经 `git worktree list` 与命名约定解析）归属分支相对 main 有未合并提交时，MUST 判定为「保留并续做」，MUST NOT 因 STATE 字段为空而直接走清空路径。

分支取值的回落链 MUST 延伸至 **git 分支命名空间**（`recovery-branch-anchor` 能力的「锚点的 git 分支命名空间回落」）：STATE 缺失 **且** 无在册 worktree 时，MUST 按 `<prefix>/<spec>-*` 枚举候选分支（`<prefix>` 与分支**创建端同源**：创建端硬编码 `fenix/`，见 `core/worktree_manager.py:223/226`，故取 `fenix/` 或「配置 `worktree.implement_branch_prefix` ∪ `fenix/`」并集；MUST NOT 仅凭配置值取前缀）并按其排序规则选定；候选 MUST 经「完整 spec 名 + 分隔符边界」全等比较过滤（口径见 `recovery-branch-anchor`），MUST NOT 把前缀 glob 命中集合直接当候选。MUST NOT 因「worktree 已不在册」而认定该 spec 无分支锚点——实现 run 成功收口会清理其 worktree，此时分支仅以 refs 形式存在。

判定为「保留并续做」时，STATE 保留的 `branch` MUST 为回落链解析出的分支名（而非仅限 STATE 原值），并在 `_recovery_resume` 标记下按既有 resume 语义派发。

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

#### Scenario: STATE 与在册 worktree 均无锚点时回落分支命名空间

- **WHEN** interrupted spec 的 STATE `branch` 为 None、无任何在册 worktree，但其存在分支 `<prefix>/<spec>-<旧ts>` 且该分支相对 main 有未合并提交（含分支已 merge main 的情形）
- **THEN** 恢复 MUST 命中保留续做路径并保留该分支，MUST NOT 走清空重建

#### Scenario: 三处均无锚点才允许清空重建

- **WHEN** interrupted spec 的 STATE `branch` 为空、无在册 worktree、且分支命名空间枚举无候选
- **THEN** 走清空重建路径，并按 `recovery-branch-anchor` 的留痕要求打 WARNING

### Requirement: 清理协调

shutdown 与 boot 路径的 orphan worktree 清理（cleanup_orphans）MUST 跳过被保全引用覆盖的 worktree（`.fenix/interrupted_runs.json` 在册项与保留分支对应的 worktree），防止保全与清理两条链路对同一 worktree 处置不一致。

保护集的构造 MUST 同样回落事实查询：sidecar 条目未携带 worktree 引用（空串）时，MUST 以该 spec 经事实查询解析出的在册 worktree 路径补入保护集，MUST NOT 因 sidecar 条目为空而放行清理。

保护集 MUST NOT 退化为空集：构造来源至少包含 (a) sidecar 在册项、(b) sidecar 条目经事实查询回落的 worktree、(c) **STATE 中所有 `implementing` spec 经事实查询解析出的在册 worktree**。来源 (c) 的存在使「排水窗口内 run 自行收口、sidecar 未写」的场景不再导致无差别清理——该场景下 run 的后置收口（如 repair 的 re-merge-back）尚未完成，其 worktree 仍被恢复链需要。

任何删除 worktree 目录的路径（`cleanup_orphans` 与 `cleanup`）MUST 在目录被物理删除前对该 worktree 执行 `_snapshot_dirty_worktree` 生成快照引用并记入日志；MUST NOT 仅把留档挂在「`git worktree remove` 失败的 rmtree 兜底」分支上。快照生成失败降级 WARNING，不阻塞删除。

#### Scenario: 保全 worktree 不被误删

- **WHEN** 停机保全了某 spec 的 worktree 引用后执行 cleanup_orphans
- **THEN** 该 worktree 目录保留，重启后 resume 可原地续做

#### Scenario: 保护集从事实查询回落

- **WHEN** sidecar 条目存在但其 worktree 字段为空串，而该 spec 的在册 worktree 仍在
- **THEN** 该 worktree MUST 被纳入保护集并跳过清理，MUST NOT 被当成普通 orphan 删除

#### Scenario: sidecar 未写时在飞 spec 的 worktree 仍受保护

- **WHEN** 排水窗口内某 `implementing` spec 的 agent 进程自行退出（`drain_wait` 返回空，sidecar 未写），该 spec 在册 worktree 仍存在
- **THEN** 该 worktree MUST 经来源 (c) 纳入保护集，MUST NOT 被 cleanup_orphans 删除

#### Scenario: orphan 清理硬删前留档

- **WHEN** cleanup_orphans 对一个未受保护的 dirty worktree 执行强制删除
- **THEN** 删除前 MUST 生成该 worktree 的 dirty 快照引用并在日志留痕，事后可据快照 SHA 取证

#### Scenario: 强制删除成功路径同样留档

- **WHEN** `git worktree remove --force` 返回成功（未走 rmtree 兜底分支）
- **THEN** 该次删除 MUST 同样已在删除前完成快照留档，MUST NOT 因命令成功而跳过

### Requirement: 终止前保全

daemon 在排水窗口到期终止在跑 run 前，MUST 先把每个受影响 spec 的保全上下文（spec 名、run_id、branch、worktree 路径、相对 main 的提交数、原因与时间）写入 `.fenix/interrupted_runs.json`，再执行 terminate。写入失败降级为 WARNING 日志，不阻塞停机。

branch 与 worktree 路径的取值 MUST NOT 以 STATE 的 `branch` 字段为唯一来源：STATE 缺失或为空时 MUST 回落到 worktree_manager 的 spec → worktree 事实查询（以 `git worktree list --porcelain` 与 worktree 命名约定为真相，MUST NOT 依赖 `_active_worktrees` / `_wt_branches` 内存表——后者 daemon 重启即失）反查该 spec 的在册 worktree 与其分支，并经 `is_available` 三态单源校验。仅当 STATE 与该查询均无该 spec 的载体记录时，才允许写出 `branch: ""` / `worktree: ""` 的空保全条目。

sidecar 的写入条件 MUST NOT 仅覆盖「排水超时」：排水窗口结束后，若仍存在**收口未完成的 `implementing` spec**（其 agent 进程已在窗口内自行退出，但后置收口未落盘），MUST 同样为其写入保全条目，使该 spec 的 worktree 进入保护集并在重启后被恢复链接管。

#### Scenario: 终止前 sidecar 已落盘

- **WHEN** 排水超时对某在跑 run 执行 terminate
- **THEN** terminate 前 `.fenix/interrupted_runs.json` 已包含该 spec 的 branch 与 worktree 引用

#### Scenario: 首轮在飞 run 的保全条目含 branch 与 worktree

- **WHEN** 排水超时终止的是一个首轮 implementing run，其 worktree 已在册但 STATE 的 `branch` 尚未写入（run 未到终态）
- **THEN** sidecar 条目 MUST 含事实查询解析出的 branch 与 worktree 路径，MUST NOT 写为空串

#### Scenario: 排水内自行收口的 run 同样保全

- **WHEN** 排水窗口内某 `implementing` spec 的 agent 进程自行退出（`drain_wait` 返回空集），其后置收口未完成
- **THEN** sidecar MUST 含该 spec 的保全条目（branch 取自 STATE 或事实查询，worktree 取自在册记录）

## ADDED Requirements

### Requirement: 恢复期消费待 re-merge-back 标记

`recover_interrupted` 处理 status 为 `implementing` 的 spec 时，若该 spec 存在「待 re-merge-back」标记（见 `mergeback-inplace-repair` 的「repair 成功的待合并状态持久化」），MUST 走 **re-merge-back 路径**：把已含 main 合并的实现分支重新合并进主树，成功后转入 `implemented`；失败时按既有冲突处理路径与熔断计数处理。MUST NOT 重派 implementer——该分支的实现已终态成功，重派只会重复已完成的实现。

失败回落（re-merge-back 执行失败）MUST 清除该标记并回落到下述保留续做路径（保留 branch/implementer_run + 恢复续做标记），由该 spec 下一轮 run 的正常 merge-back 走既有冲突处理路径；MUST NOT 让 spec 停留在 `implementing`——周期恢复不处理 `implementing`（仅 boot 一次性扫描处理），停留即死锁到下次重启。「MUST NOT 重派 implementer」约束的是标记命中的成功路径，不禁止失败回落后的保留续做。

该标记缺失时（历史数据、异常未落盘）MUST 回落到既有的保留续做路径，行为与现状兼容，MUST NOT 因标记缺失而报错或阻塞恢复。

#### Scenario: 待合并标记命中时不重派 implementer

- **WHEN** daemon 重启后 recovery 发现某 implementing spec 带待 re-merge-back 标记
- **THEN** 框架对该 spec 执行 re-merge-back 而非派发 implementer，成功后该 spec 进入 `implemented`

#### Scenario: 标记缺失时回落保留续做

- **WHEN** 某 implementing spec 无该标记，但按 `recovery-branch-anchor` 的回落链解析出含未合并提交的分支
- **THEN** 按既有保留续做路径处理（保留 branch 并 resume），MUST NOT 因标记缺失而改变判定

#### Scenario: kick 合并失败不吞掉失败链

- **WHEN** 待合并标记命中的 re-merge-back 因主树前进产生新冲突而失败
- **THEN** 标记被清除、spec 回落既有保留续做路径（保留 branch/implementer_run），由下一轮 run 的正常 merge-back 进入既有 repair 或熔断计数；MUST NOT 静默清空该 spec 的状态，MUST NOT 让 spec 停留在 `implementing`
