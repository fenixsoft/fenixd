<!-- knowledge: capability=interrupt-recovery-preserve rev=3 sources=spec/archive/2026-09-11-add-interrupt-recovery-preserve,spec/archive/2026-09-18-fix-preserve-chain-first-round-gap,spec/archive/2026-09-19-fix-recovery-branch-anchor-without-worktree -->

# 中断恢复保全与保留分支续做

daemon 计划性重启时保全在飞 run 现场（sidecar 条目 + worktree 保护集），重启后对有成果的 interrupted spec 保留分支续做，仅确认零提交才清空重建。

## 现行规则

### 规划性重启排水

- daemon 收到 SIGTERM 且 `.fenix/restart_request` 在册时进入排水模式：关闭期间禁止新派发，等待在跑 run 到终态，上限 `admin.shutdown_drain_seconds`（缺省 1800，0 = 不等待保持快速停机）；到期仍有在跑 run 按现行 terminate 流程（SIGTERM→interrupted 标记→grace→SIGKILL）收口。非计划 SIGTERM（restart_request 不在册）保持快速停机语义。
- supervisor（bin/fenixd_supervisor.py）重启路径上的 SIGKILL 等待时长可配，缺省不小于 daemon 排水窗口加固定余量，排水期不被 SIGKILL 截断。

### 终止前保全

- 排水窗口到期终止在跑 run 前，把每个受影响 spec 的保全上下文（spec 名、run_id、branch、worktree 路径、相对 main 的提交数、原因与时间）写入 `.fenix/interrupted_runs.json` 再 terminate；写入失败降 WARNING 不阻塞停机。
- branch/worktree 取值不以 STATE `branch` 为唯一来源：STATE 缺失或为空时回落 worktree_manager 的 spec→worktree 事实查询（`git worktree list --porcelain` + worktree 命名约定为真相，不依赖 `_active_worktrees`/`_wt_branches` 内存表——重启即失）反查在册 worktree 与分支，经 `is_available` 三态单源校验；仅当 STATE 与事实查询均无载体记录才允许空保全条目。
- 写入条件不限于排水超时：排水窗口结束后仍存在收口未完成的 `implementing` spec（agent 进程已在窗口内自行退出，但后置收口未落盘）时，同样为其写保全条目，使其 worktree 进入保护集并在重启后被恢复链接管。

### 恢复保留分支续做

- boot recovery（recover_interrupted）对 interrupted 的 implementing spec：分支存在且相对 main 有提交（`git rev-parse main..branch` 非空）→ 保留 branch 与 implementer_run 引用并标记恢复续做；worktree 在场原地续做，缺失则从该分支重建载体；仅确认零提交才走清空重建路径。续做 spec 复用既有 resume 派发语义（含 attempt 校验与继承注记）。
- 分支取值支持事实查询回落：STATE `branch` 为空但该 spec 在册 worktree 归属分支相对 main 有未合并提交时，判定保留续做，不因 STATE 字段为空走清空路径；回落链延伸至 git 分支命名空间枚举（三层回落与全等边界口径见 recovery-branch-anchor）。判定保留时 STATE 写入的 `branch` 为回落链解析出的分支名（不限于 STATE 原值），在 `_recovery_resume` 标记下按 resume 语义派发。

### 清理协调

- shutdown 与 boot 路径的 orphan worktree 清理（cleanup_orphans）跳过被保全引用覆盖的 worktree。保护集构造同样回落事实查询：sidecar 条目 worktree 字段为空串时，以该 spec 经事实查询解析出的在册 worktree 补入，不因条目为空放行清理。保护集不为空集，来源至少含：(a) sidecar 在册项；(b) sidecar 条目的事实查询回落项；(c) STATE 中所有 `implementing` spec 经事实查询解析出的在册 worktree——覆盖「排水窗口内 run 自行收口、sidecar 未写」场景（其后置收口如 repair 的 re-merge-back 尚未完成，worktree 仍被恢复链需要）。
- 任何删除 worktree 目录的路径（cleanup_orphans 与 cleanup）在物理删除前对该 worktree 执行 `_snapshot_dirty_worktree` 生成快照引用并记日志（`git worktree remove --force` 成功路径同样留档，不挂在 rmtree 兜底分支上）；快照生成失败降 WARNING 不阻塞删除。

### 恢复期消费待 re-merge-back 标记

- recover_interrupted 处理 `implementing` spec 时若带「待 re-merge-back」标记（mergeback-inplace-repair 的 repair 成功待合并持久化），走 re-merge-back 路径：把已含 main 合并的实现分支重新合并进主树，成功转 `implemented`；失败按既有冲突处理路径与熔断计数处理。不重派 implementer——该分支实现已终态成功，重派只会重复已完成的实现。
- 失败回落：re-merge-back 失败时清除标记并回落保留续做路径（保留 branch/implementer_run + 恢复续做标记），由下一轮 run 的正常 merge-back 走既有冲突处理；spec 不得停留在 `implementing`——周期恢复不处理 implementing（仅 boot 一次性扫描处理），停留即死锁到下次重启。
- 标记缺失（历史数据、异常未落盘）时回落既有保留续做路径，不因标记缺失报错或阻塞恢复。

### worktree 可用性单源

- worktree_manager 暴露统一的 worktree 可用性查询（目录存在 + git worktree 注册有效 + 分支可解析，三态：可用/可从分支重建/不可用），recovery、resume 派发、复用认领三链路共用，禁止各自拼装目录/分支判断；attempt 层复用校验收敛到同一查询。

## 溯源

- 2026-09-11 add-interrupt-recovery-preserve（spec/archive/2026-09-11-add-interrupt-recovery-preserve） — 新增规划性排水、终止前保全、保留分支续做、清理协调与 worktree 可用性单源
- 2026-09-18 fix-preserve-chain-first-round-gap（spec/archive/2026-09-18-fix-preserve-chain-first-round-gap） — 保全与保留判定的分支取值补 worktree 事实查询回落（首轮在飞 run 的保全条目不再空 branch）；orphan 清理硬删前快照留档扩展到强制删除成功路径
- 2026-09-19 fix-recovery-branch-anchor-without-worktree（spec/archive/2026-09-19-fix-recovery-branch-anchor-without-worktree） — 保留判定回落链延伸至 git 分支命名空间；保护集增加来源 (c)；sidecar 写入扩展到排水内自行收口但收口未完成的 spec；新增恢复期消费待 re-merge-back 标记
