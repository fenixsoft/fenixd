# spec-interrupt-recovery-preserve

## ADDED Requirements

### Requirement: 规划性重启排水

daemon 收到 SIGTERM 且 `.fenix/restart_request` 在册时，MUST 进入排水模式：保持「关闭期间禁止新派发」语义，并等待在跑 run 到终态，等待上限为 `admin.shutdown_drain_seconds`（缺省 1800，0 = 不等待、保持现行快速停机）。排水窗口到期仍有在跑 run 时，按现行 terminate 流程（SIGTERM→interrupted 标记→grace→SIGKILL）收口。非计划 SIGTERM（restart_request 不在册）MUST 保持现行快速停机语义逐字节不变。supervisor（bin/fenixd_supervisor.py）在重启路径上的 SIGKILL 等待时长 MUST 可配，且缺省值不小于 daemon 排水窗口加固定余量，保证排水期不被 SIGKILL 截断。

#### Scenario: 排水等待在跑 run 终态

- **WHEN** restart_request 在册，daemon 收到 SIGTERM，此时有 1 个在跑 implementer run
- **THEN** daemon 不立即终止该 run，保持新派发禁用，等待其自然终态后退出；supervisor 在等待期内不 SIGKILL

#### Scenario: 排水窗口超时按现行流程收口

- **WHEN** 排水窗口到期仍有 run 未终态
- **THEN** 对残留 run 执行现行 terminate 流程（interrupted 标记），daemon 退出并重启

#### Scenario: 非计划 SIGTERM 行为零变化

- **WHEN** 无 restart_request 时 daemon 收到 SIGTERM（外部 kill / 崩溃处理）
- **THEN** 停机路径与现状一致（快速 terminate，总关停 ≪ 旧 supervisor 60s），不进入排水

### Requirement: 终止前保全

daemon 在排水窗口到期终止在跑 run 前，MUST 先把每个受影响 spec 的保全上下文（spec 名、run_id、branch、worktree 路径、相对 main 的提交数、原因与时间）写入 `.fenix/interrupted_runs.json`，再执行 terminate。写入失败降级为 WARNING 日志，不阻塞停机。

#### Scenario: 终止前 sidecar 已落盘

- **WHEN** 排水超时对某在跑 run 执行 terminate
- **THEN** terminate 前 `.fenix/interrupted_runs.json` 已包含该 spec 的 branch 与 worktree 引用

### Requirement: 恢复保留分支续做

boot recovery（recover_interrupted）对 interrupted 的 implementing spec MUST 改判定：分支存在且相对 main 有提交（`git rev-parse main..branch` 非空）→ 保留 branch 与 implementer_run 引用、标记恢复续做；worktree 在场则原地续做，worktree 缺失则从该分支重建载体；仅确认零提交时才走现行清空重建路径。恢复续做的 spec 复用既有 resume 派发语义（含 attempt 校验与继承注记）。

#### Scenario: 有提交分支保留并续做

- **WHEN** daemon 重启后 recovery 发现 interrupted spec 的分支含未合并提交
- **THEN** STATE 保留 branch/implementer_run，spec 按 resume 续做而非从零重派

#### Scenario: 零提交分支走现行清空

- **WHEN** interrupted spec 的分支不存在或相对 main 零提交
- **THEN** 按现行行为清空 implementer_run/branch 并新建重派，行为逐字节兼容

#### Scenario: worktree 缺失时从分支重建

- **WHEN** 保留分支的 worktree 目录已被清理
- **THEN** 恢复在该分支上创建新 worktree 续做，不静默改走全新分支

### Requirement: 清理协调

shutdown 与 boot 路径的 orphan worktree 清理（cleanup_orphans）MUST 跳过被保全引用覆盖的 worktree（`.fenix/interrupted_runs.json` 在册项与保留分支对应的 worktree），防止保全与清理两条链路对同一 worktree 处置不一致。

#### Scenario: 保全 worktree 不被误删

- **WHEN** 停机保全了某 spec 的 worktree 引用后执行 cleanup_orphans
- **THEN** 该 worktree 目录保留，重启后 resume 可原地续做

### Requirement: worktree 可用性单源

worktree_manager MUST 暴露统一的 worktree 可用性查询（目录存在 + git worktree 注册有效 + 分支可解析，三态：可用 / 可从分支重建 / 不可用），recovery、resume 派发、复用认领共用该查询，禁止各链路自行拼装目录/分支判断。attempt 层复用校验（fix-resume-stale-worktree，2026-09-05 已落地）MUST 收敛到同一查询。

#### Scenario: 三链路判定一致

- **WHEN** 同一 spec 的 worktree 目录被外部删除但分支仍在
- **THEN** recovery、resume 派发、复用认领三条链路经单源查询得到一致判定（可从分支重建），不存在任一链路按旧目录路径盲派发
