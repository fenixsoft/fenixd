# Spec Delta: recovery-state-consistency

## ADDED Requirements

### Requirement: 卡死自动恢复前必须核验无存活子进程
BLOCKER CHECK 对 implementing 等运行态 spec 执行 auto-recovery（重置为 ready、清空 run 跟踪）之前，系统 MUST 先探测该 spec 是否仍存在存活的 attempt 子进程；存在则 MUST 跳过本次恢复并保留全部跟踪字段。

#### Scenario: 恢复时子进程实际仍在运行
- **WHEN** 某 spec 触发 stuck 阈值，但其 attempt 进程（如 resume 后的子进程）经进程表/流文件活性核验仍在运行
- **THEN** 系统 MUST 不重置状态、不清空 implementer_run，仅记录「recovery deferred, live child present」并等待下一轮检查

#### Scenario: 无存活子进程时恢复照常执行
- **WHEN** 某 spec 触发 stuck 阈值且核验确认无存活子进程
- **THEN** 系统 MUST 按现行 auto-recovery 流程重置该 spec

### Requirement: worktree 锁支持按进程表重建与陈锁回收
worktree 锁登记 MUST 能以真实进程表为准重建：当 daemon 重启导致内存锁丢失时，若发现有 claude 进程的工作目录/--add-dir 参数指向某 spec 的活跃 worktree，`has_active_worktree` MUST 返回 true；反之在册锁对应无任何存活进程时 MUST 被视为陈锁并释放。

#### Scenario: daemon 重启后孤儿进程仍持锁
- **WHEN** daemon 重启后收到某 ready spec 的派发请求，内存锁已丢失但进程表中存在指向该 spec worktree 的存活 agent 进程
- **THEN** 系统 MUST 识别为仍持锁并跳过派发，不创建第二个并发 worktree

#### Scenario: 在册锁对应的进程已消失
- **WHEN** 锁登记在册，但针对该 worktree 的进程扫描未发现任何匹配进程且流文件已停止增长超过判定窗口
- **THEN** 系统 MUST 释放该锁并允许正常派发

### Requirement: 派发遇锁冲突采用退避重试且不消耗 attempt 配额
派发 implementer 时因 worktree 已有活跃实现者被拒绝的情况下，系统 MUST 进入指数退避的重试计划（不立即连续硬试），重试期间不消耗 `_retry_count`、不将 spec 标记为 retries exhausted；退避计划耗尽仍无法获得锁时 MUST 上报告警而不是静默循环。

#### Scenario: 首次遇锁进入退避队列
- **WHEN** 某 ready spec 的派发因 `worktree already active` 被拒
- **THEN** 该 spec MUST 保持 ready 并按 `pm.dispatch_backoff_schedule`（默认递增间隔）安排下一次尝试，期间日志级别不得将其记为错误耗尽

#### Scenario: 退避预算耗尽仍持锁则升级告警
- **WHEN** 退避序列全部用完而锁仍未释放
- **THEN** 系统 MUST 通过 Administrator 信号上报该异常滞留状态，spec 保持 ready 等待处置，而非把原因伪装成普通任务失败
