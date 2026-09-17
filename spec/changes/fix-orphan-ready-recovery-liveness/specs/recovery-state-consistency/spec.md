# Spec Delta: recovery-state-consistency

## MODIFIED Requirements

### Requirement: 卡死自动恢复前必须核验无存活子进程

BLOCKER CHECK 与 full_scan recovery 对运行态/ready 态 SPEC 执行恢复动作（重置状态、清空 run 跟踪、重新派发）之前，系统 MUST 先探测该 spec 是否仍存在存活的 attempt 子进程；存在则 MUST 跳过本次恢复并保留全部跟踪字段。

「无存活子进程」判定 MUST 以**进程事实**为第一判据（进程表中存在指向该 spec worktree 的 agent 进程）。仅当进程表无命中时，系统 MAY 回退到 run 流文件新鲜度作为辅助判据；该回退判据 MUST 满足：

- 新鲜度窗口内的流文件，其**末条事件**为终态（`result` / `error` / `interrupted` / `cancelled`）时 MUST NOT 计为「存活」——末行终态即代表该 run 已明确终结，不得以「文件近期有写入」反推「进程仍在运行」。
- 终态口径 MUST 复用框架既有单一真源 `core/agent_runner/liveness.RUN_TERMINAL_EVENT_TYPES`，MUST NOT 另立集合或字面量列表。
- **`superseded` MUST NOT 视为终态**：它是原地重试弃置旧产物文件的标记，run 在新 sub_run_id 产物文件继续，把其视为终结会造成原地重试窗口内的双派发。
- 末行解析失败 / 文件不可读 / 末行非终态时 MUST 视为「仍存活」（fail-open 到保守侧）——误判活 run 为死会引发双派发，代价高于误判死 run 为活。

#### Scenario: 恢复时子进程实际仍在运行

- **WHEN** 某 spec 触发恢复判定，但其 attempt 进程经进程表核验仍在运行
- **THEN** 系统 MUST 不重置状态、不清空 `implementer_run`，仅记录「recovery deferred, live child present」或「skip: live child present」并等待下一轮检查

#### Scenario: 无存活子进程时恢复照常执行

- **WHEN** 某 spec 触发恢复判定且核验确认无存活子进程，其历史 run 流文件 mtime 落在新鲜度窗口内但**末条事件为终态**
- **THEN** 系统 MUST 判定该 spec 无存活子进程，按现行恢复流程继续执行恢复动作，MUST NOT 因「流文件近期有写入」而跳过

#### Scenario: daemon 主动停机杀死的 run 不阻塞重启后恢复

- **WHEN** daemon 收到 SIGTERM 杀掉在飞 run，runner 向该 run 流文件补写 `error` 终态行，随后 daemon 重启并在新鲜度窗口内（缺省 120 秒）执行首轮恢复扫描
- **THEN** 该 run 的流文件 MUST NOT 被计为存活依据，该 spec MUST 在本轮恢复中被正常重派，MUST NOT 被记录为「live child present」

#### Scenario: 原地重试弃置产物不被误判为终结

- **WHEN** 原地重试通道向旧产物文件补写 `superseded` 标记、新 sub_run_id 产物文件尚未产生（退避 sleep 窗口内），此时发生恢复判定
- **THEN** 系统 MUST 将该流文件计为「仍存活」并跳过恢复，MUST NOT 判为孤儿而触发重派

#### Scenario: 末行解析异常时保守视为存活

- **WHEN** 流文件末尾存在损坏/不可解析的行，无法确定末条事件类型
- **THEN** 系统 MUST 按「仍存活」处理并跳过恢复，MUST NOT 因解析失败判为死 run

### Requirement: worktree 锁支持按进程表重建与陈锁回收

worktree 锁登记 MUST 能以真实进程表为准重建：当 daemon 重启导致内存锁丢失时，若发现有 claude 进程的工作目录/`--add-dir` 参数指向某 spec 的活跃 worktree，`has_active_worktree` MUST 返回 true；反之在册锁对应无任何存活进程时 MUST 被视为陈锁并释放。

「无匹配进程但对应 run 流文件仍在增长」的保守持锁分支（`worktree_manager._latest_stream_mtime`）与「无存活子进程」判定（本 delta 的第一条 Requirement）属同一类谬误的两个实现点；本次修改**仅覆盖存活探测侧**，锁侧的流新鲜度判定保持现状并以下游 SPEC 承接专门治理（见 design D5 的三处同型点处置表）。

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
