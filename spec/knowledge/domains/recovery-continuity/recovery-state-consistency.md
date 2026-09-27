<!-- knowledge: capability=recovery-state-consistency rev=2 sources=spec/archive/2026-09-02-improve-run-lifecycle-governance,spec/archive/2026-09-22-fix-orphan-ready-recovery-liveness -->

# 恢复前存活核验与锁一致性

恢复动作执行前以进程事实核验无存活子进程，worktree 锁按进程表重建与回收陈锁，派发遇锁冲突走指数退避不烧 attempt 配额。

## 现行规则

- 恢复动作前核验：BLOCKER CHECK 与 full_scan recovery 对运行态/ready 态 SPEC 执行恢复动作（重置状态、清空 run 跟踪、重新派发）之前，先探测该 spec 是否仍存在存活的 attempt 子进程；存在则跳过本次恢复并保留全部跟踪字段（记录「recovery deferred, live child present」/「skip: live child present」），等待下一轮检查。
- 「无存活子进程」以进程事实为第一判据：进程表中存在指向该 spec worktree 的 agent 进程即存活；仅当进程表无命中时 MAY 回退 run 流文件新鲜度作为辅助判据。回退判据：新鲜度窗口内的流文件末条事件为终态（`result`/`error`/`interrupted`/`cancelled`）时不计为存活——daemon 主动停机杀死的 run 由 runner 补写 `error` 终态行，重启后在新鲜度窗口内（缺省 120 秒）的首轮恢复扫描不被挡；末行解析失败/文件不可读/末行非终态时保守视为存活（fail-open 到保守侧——误判活 run 为死引发双派发，代价高于误判死 run 为活）。
- 终态口径复用框架单一真源 `core/agent_runner/liveness.RUN_TERMINAL_EVENT_TYPES`，不另立集合或字面量列表；`superseded` 不视为终态——它是原地重试弃置旧产物文件的标记，run 在新 sub_run_id 产物文件继续，视为终结会造成原地重试窗口内的双派发。
- worktree 锁按进程表重建与陈锁回收：daemon 重启导致内存锁丢失后，若存在工作目录/`--add-dir` 参数指向某 spec 活跃 worktree 的 claude 进程，`has_active_worktree` 返回 true（识别为仍持锁并跳过派发，不创建第二个并发 worktree）；在册锁对应无任何存活进程且流文件已停止增长超过判定窗口时，视为陈锁并释放、允许正常派发。锁侧「无匹配进程但流文件仍在增长」的保守持锁分支维持现状，由下游 SPEC 专门治理。
- 派发遇锁冲突指数退避：implementer 派发因 worktree 已有活跃实现者被拒（`worktree already active`）时，进入指数退避的重试计划（按 `pm.dispatch_backoff_schedule` 默认递增间隔安排下一次尝试），spec 保持 ready；重试期间不消耗 `_retry_count`、不将 spec 记为 retries exhausted（日志级别不得记为错误耗尽）；退避序列耗尽仍无法获得锁时，以 Administrator 信号上报异常滞留状态（spec 保持 ready 等待处置），不把原因伪装成普通任务失败、不静默循环。

## 溯源

- 2026-09-02 improve-run-lifecycle-governance — 新增恢复前存活子进程核验、worktree 锁按进程表重建与陈锁回收、锁冲突指数退避不消耗 attempt 配额
- 2026-09-22 fix-orphan-ready-recovery-liveness — 存活核验扩至 BLOCKER CHECK 与 full_scan recovery 的 ready 态；流文件末条终态不计存活、`superseded` 例外、解析失败保守存活
