# Verification Report: improve-run-lifecycle-governance

对照三个 capability 的每个 Scenario 核对实现覆盖（tasks 6.2）。测试文件：
`tests/test_run_lifecycle_governance.py`（新增 58 例），回归见下方 6.1。

## 1. agent-run-timeout-supervision（D1–D3，tasks 4.1–4.4 / 3.2）

| Scenario | 覆盖 | 结论 |
| --- | --- | --- |
| 到达时限且流仍在活动 → 先 LLM 判定不直接杀 | `TestSupervisionDeadlineAction::test_advancing_verdict_extends`（judge 被调用且返回 advancing → extend）；`_supervision_deadline_action` 判定顺序硬上限在前、活性在后 | ✅ |
| 判定不可用时的失败安全 → stagnant + 「liveness judge unavailable」 | `TestJudgeLiveness::test_unparseable_output_is_stagnant_with_marker` / `test_exception_is_stagnant_with_marker`；证据写入 run 文件 error 行与 daemon 日志 | ✅ |
| 判定 advancing → 续期 extension_seconds 并广播续期顺延 stuck 基准 | `TestSupervisionDeadlineAction::test_advancing_verdict_extends`；`TestExtensionBaseline`（note/get/失效）；`TestPmEngineUsesExtensionBaseline::test_fresh_baseline_suppresses_stuck_blocker`；`_run_claude` 续期时写 `timeout_extension` 事件 + `note_run_extension` | ✅ |
| 判定 stagnant → 携带证据硬杀 | `test_stagnant_verdict_terminates_with_evidence`；`_run_claude` 超时分支把 evidence 拼入 timeout_error 并 `append_run_error` | ✅ |
| 续期次数耗尽 → 「extension budget exhausted」跳过 LLM | `test_extension_budget_exhausted_terminates`（judge 不被触达，矩阵在活性判定前返回） | ✅ |
| enabled=false → 回归纯墙钟，无 LLM 调用 | `test_disabled_is_pure_wall_clock_kill`；`_supervision_deadline_action` 在 enabled=false 时直接 kill | ✅ |

绝对上限（`absolute_max_seconds`，无独立 Scenario 但属 Requirement 封顶条款）：
`test_absolute_cap_terminates_unconditionally`、`test_absolute_max_raised_to_cover_extension_budget`
（配置偏小时抬到 run_timeout + 续期总额，保证续期预算不被截断）。
配置默认与文档注释：`config.template.yaml` agents.timeout_supervision 段（tasks 4.4）。

## 2. recovery-state-consistency（D4+D5，tasks 1.1/1.2/2.1/2.2/3.1）

| Scenario | 覆盖 | 结论 |
| --- | --- | --- |
| 恢复时子进程实际仍在运行 → defer + 保留跟踪字段 | `TestAutoRecoveryLiveChildGuard::test_live_child_defers_recovery_and_keeps_tracking`（状态、implementer_run、branch 均保留） | ✅ |
| 无存活子进程时恢复照常执行 | `test_no_live_child_recovers_normally`、`test_probe_non_bool_return_treated_as_absent` | ✅ |
| daemon 重启后孤儿进程仍持锁 → 不双派发 | `TestRefreshLocks::test_daemon_restart_lock_rebuilt_from_process_table`；`fenixd.start()` 先 `refresh_locks()` 再清理 | ✅ |
| 在册锁对应进程已消失 → 释放陈锁 | `test_stale_lock_reclaimed_and_dispatch_allowed`、`test_refresh_locks_releases_only_stale`（进程扫描未命中 + 流 mtime 超 120s 才回收；流仍在增长则保守保留） | ✅ |
| 首次遇锁进入退避队列 → 保持 ready、不耗 attempt 配额 | `TestDispatchLockBackoff::test_first_conflict_schedules_backoff_without_retry_cost`、`test_conflict_escalates_through_schedule`（[30,120,600]） | ✅ |
| 退避预算耗尽仍持锁 → Administrator 信号、非伪装任务失败 | `test_exhausted_schedule_emits_dispatch_stalled_once`（severity major、含证据）、`test_signal_dedup_within_cooldown`、`test_backoff_window_suppresses_respin`（防写 STATE 自触发热循环） | ✅ |

## 3. post-recovery-patrol（D6，tasks 5.1/5.2）

| Scenario | 覆盖 | 结论 |
| --- | --- | --- |
| 复查发现仍卡在假就绪 → dispatch_stalled 且可追溯恢复动作 | `TestRecoveryWatch::test_watch_fails_when_still_fake_ready`（evidence 含恢复动作 reason）；`test_defer_registers_watch_no_deadloop`（defer 也登记，防死循环） | ✅ |
| 复查确认已恢复推进 → 关闭观察项不告警 | `test_watch_passes_when_spec_left_ready`、`test_watch_passes_when_dispatch_active` | ✅ |
| 无 in-progress 但有假 ready 滞留 → 报告且不提前返回 | `TestReadyStallPatrol::test_ready_stall_beyond_threshold_reported`；`TestAdminMonitorContinuesWithoutInProgress::test_blocked_stuck_detected_without_in_progress` | ✅ |
| 冷却期内重复检测同一滞留 → 仅首次拉起 | `test_same_fingerprint_not_re_signaled_within_cooldown`（指纹 = hash(status+error 摘要)，冷却 30 分钟可配） | ✅ |

观察项持久化（Requirement 附带的重启续查）：`test_watch_persisted_for_restart`
（镜像到 `.fenix/recovery_watch.json`，新 engine 实例续读）。

## 4. tasks 5.3 冒烟结论

dashboard 零改动：pm_engine 经 `AdminStore.append` 写入的 `dispatch_stalled`
信号在既有 admin activity view 数据源 `core.dashboard.data.get_alerts` 直接可见；
AdminMonitor 摄取（`STORED_SIGNAL_TYPES`）唤起 Administrator 后，处置记录以
`get_admin_activities` 时间线可见（冒烟脚本验证 signal → 唤起 → disposition 全链落库）。

## 5. 全量回归（tasks 6.1）

- `python3 -m pytest tests/ -q`：**757 passed, 0 failed**（首轮发现 6 例
  test_provider_failover 桩签名缺 `spec_name` 形参导致的失败，已修桩后全绿）。
- 重点套件：tests/test_core.py、tests/test_agent_runner.py、tests/test_admin.py、
  tests/test_provider_failover.py、tests/test_provider_circuit.py、
  tests/test_run_lifecycle_governance.py 均通过。
