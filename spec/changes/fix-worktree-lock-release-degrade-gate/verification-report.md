# 验证报告：fix-worktree-lock-release-degrade-gate

> ⚠️ 本报告由框架于 2026-10-27T08:46:06Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-27T08:46:05.732516+00:00+run-result@mtime1793090765785687285

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.39M |
| 本链增量 Token（输出） | 0.09M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| terminal-release-failure-terminal-immediate-reacquire | 失败终态收尾即释锁：run 到达失败类终态（框架终态单源 RUN_TERMINAL_EVENT_TYPES 口径，core/agent_runner/liveness.py:149）收尾链对经 create() 持锁（owner run 归属）的 spec:agent_type 锁发起 owner 校验释放（core/agent_runner/runner.py:5482-5495），释放后同 spec 同 agent_type 的新派发立即正常 acquire、不出现「Worktree already active」早退。验收 spec worktree-lock-terminal-release「supersede 后锁即时释放」正向路径（用例 TestTerminalStateRelease::test_terminal_release_allows_immediate_reacquire） | pass | 0/2 | - |
| terminal-release-owner-mismatch-noop-guard | 终态释放不误放他人锁：owner run 归属与持锁 run 不符的 release_spec_lock 调用为 no-op（返回 False + DEBUG「owner mismatch」留痕），他人持有的锁保持被持有，正主释放才生效（core/worktree_manager/lifecycle.py:570 释放 API 可选 owner 参数、:593-605 owner 校验段）。验收 spec worktree-lock-terminal-release「终态释放不误放他人锁」（用例 TestTerminalStateRelease::test_owner_mismatch_release_is_noop） | pass | 0/2 | - |
| terminal-release-defer-lane-idempotent-contract | 不传 owner 维持既有幂等释放语义（code-fix defer 车道零改动契约）：首次释放成功、二次释放 False；且本链未经 create() 持锁（继承/repair 载体，lock_owner_run_id=None）的失败终态不发释放——他人锁保持不被误放（core/worktree_manager/lifecycle.py:570 缺省 owner 维持既有幂等语义；用例 TestTerminalStateRelease::test_release_without_owner_keeps_idempotent_semantics 与 TestTerminalStateRelease::test_inherited_carrier_without_owner_never_releases） | pass | 0/3 | - |
| terminal-release-cancelled-terminal-releases | cancelled 终态同属 RUN_TERMINAL_EVENT_TYPES 失败类终态集，收尾链同样释放 spec:agent_type 锁——终态单源口径一致性（非成功 result/error/interrupted/cancelled/frozen-terminated/gate-blocked 全集释放，成功终态不释放走既有清理路径；core/agent_runner/liveness.py:149；用例 TestTerminalStateRelease::test_cancelled_terminal_releases_lock） | pass | 0/2 | - |
| lock-terminal-release-suite-all-green | 本 SPEC 新增测试文件全量通过：锁 owner 化（_spec_lock_owners 归属映射，core/worktree_manager/lifecycle.py:157）/终态释放/acquire 陈锁清扫/降级熔断四组 23 例同进程全绿，防单用例通过但同组其他用例回归的漏网（tests/test_worktree_lock_terminal_release.py 全文件，实测输出汇总行「23 passed」） | pass | 0/4 | - |
| stale-sweep-dead-owner-tail-swept-and-acquired | 死锁主陈锁清扫放行（判据①记录终态行）：持锁 run 记录（.fenix/runs/<run_id>.jsonl 非归档）末行属死亡判据集（RUN_TERMINAL_EVENT_TYPES ∪ {superseded}，弃置件即死——2026-10-26 事故正是尾行 superseded 的陈锁）时，acquire「already active」早退前清扫陈锁（discard + WARNING「Stale lock swept」，core/worktree_manager/lifecycle.py:272；判据源 core/worktree_manager/locks.py:205 _stale_lock_owner_dead）并放行本次派发、新派发正常 acquire（用例 TestAcquireStaleLockSweep::test_1_dead_owner_terminal_tail_swept_and_acquired、TestAcquireStaleLockSweep::test_1b_dead_owner_superseded_tail_swept） | pass | 0/3 | - |
| stale-sweep-inflight-owner-keeps-early-exit | 存活持锁主不错杀（保守侧=宁可慢清扫不可错杀活锁）：记录在飞且末行非死亡判据行时维持既有「Worktree already active」早退不清扫（core/worktree_manager/lifecycle.py:282）；记录缺失但锁龄年轻（构建窗口内）维持早退；末行损坏不可解析 fail-open 判活维持早退。验收 spec「存活持锁主维持早退」三种不确定判据形态（用例 TestAcquireStaleLockSweep::test_2_inflight_owner_keeps_early_exit、TestAcquireStaleLockSweep::test_3b_missing_record_young_lock_kept、TestAcquireStaleLockSweep::test_unreadable_tail_fail_open_keeps_lock） | pass | 0/4 | - |
| stale-sweep-missing-record-age-cap-swept | 陈锁清扫判据②锁龄上限：run 记录不存在且锁龄超过 early give-up cap（1200s，镜像常量 STALE_LOCK_SWEEP_LOCK_AGE_CAP_SECONDS，core/worktree_manager/constants.py:42）时清扫放行；owner=None 登记锁（core/worktree_manager/locks.py:55 _register_spec_locks 无 run 上下文写点、:74-84 owner=None 语义）超龄同样按锁龄判据清扫——异常泄漏路径（无 owner 可核对存活）的死锁兜底（用例 TestAcquireStaleLockSweep::test_3_missing_record_over_cap_swept、TestAcquireStaleLockSweep::test_4b_owner_none_over_cap_swept） | pass | 0/3 | - |
| stale-sweep-owner-none-young-lock-kept | owner=None 登记锁年轻则保守不清扫：缺 owner=无法核对持锁 run 存活，退回锁龄判据——锁龄未超 cap 时维持既有早退不误删（core/worktree_manager/locks.py:74-84；用例 TestAcquireStaleLockSweep::test_4_owner_none_young_lock_not_swept） | pass | 0/2 | - |
| stale-sweep-tail-reader-helper | 清扫判据①消费端 file_tail_event_type 尾读助手：返回 run 记录末行事件类型；记录缺失/空文件/末行损坏不可解析返回 None（判活侧保守）；超尾读窗口的大文件经窗口回退路径仍能取到末行类型（core/agent_runner/liveness.py:310；用例 TestFileTailEventType 全部 4 例） | pass | 0/5 | - |
| degrade-gate-first-degrade-keeps-legacy-dispatch | 首次降级维持既有行为：同一 spec 新验证流程（三阶段）首次失败降级仍派发 legacy verifier + WARNING，spec 级连续降级计数（_legacy_degrade_streak，持久化于 spec STATE 条目，core/state_machine.py:655-656）+1 并持久化降级原因（core/pm_engine/engine.py:2891-2899）；state_machine 缺失（裸实例）fail-open 放行降级（保守侧=现状）；既有「第 N 次降级」模块级计数在放行的降级上仍累计（可观测不变）。验收 spec legacy-degrade-prerequisite-gate「首次降级维持既有」（用例 TestLegacyDegradeGate::test_first_degrade_passes_and_counts、TestLegacyDegradeGate::test_state_machine_missing_fails_open、TestLegacyDegradeGate::test_existing_module_counter_still_counts_dispatched_degrades） | pass | 0/4 | - |
| degrade-gate-second-degrade-circuit-breaks | 连续第 2 次降级熔断：同一 spec 连续第 2 次到达「新验证流程失败 → 降级」决策点时不再自动派发 legacy verifier（派发次数保持 1），SPEC 转 blocked + human-escalation-alert（signal_type=verify_env_blocked，core/pm_engine/engine.py:2957），告警文案含「第 1 次降级」「第 2 次降级」两次原因链与建议动作（core/pm_engine/engine.py:2932、2961）——杜绝第三轮静默降级。验收 spec legacy-degrade-prerequisite-gate「连续第 2 次降级转人工」（用例 TestLegacyDegradeGate::test_second_consecutive_degrade_breaks_to_blocked） | pass | 0/2 | - |
| degrade-gate-unfreeze-resets-streak | 计数清零口径·人工解冻：熔断 blocked 后 unfreeze_spec 清零集含降级计数双字段（core/state_machine.py:2440-2441），解冻后 _legacy_degrade_streak=0 且重新获得「首次放行」降级机会（解冻后再失败仍派发 legacy 而非直接熔断）。验收 spec「计数清零口径」人工解冻分支（用例 TestLegacyDegradeGate::test_unfreeze_resets_streak_and_restores_degrade_budget） | pass | 0/2 | - |
| degrade-gate-zeroing-points-source-contract | 计数清零口径·另两清零点源码契约：验证轮成功推进清零表 VERIFIED_RESET_FIELDS 收编 _legacy_degrade_streak=0 与 _legacy_degrade_last_reason=None（core/pm_engine/verification/fastlane.py:85，用例 test_verified_reset_fields_clear_streak 断言）；admin 处置复位表 _RETRY_COUNTER_RESETS 同样收编双字段（core/dashboard/data/admin_actions.py:1684、1716-1718，D4 三清零点之三）——单元用例之外再以直接 import 被测源码的契约检查双保险，逐项打印 OK 并以退出码仲裁（命令实测输出 4 行 OK、exit 0） | pass | 0/7 | - |
| regression-adaptive-backoff-behavior | 回归：既有 worktree adaptive backoff 行为不回归——锁互斥等待轮次、预算耗尽 give-up、人工接管（frozen/cancelled/status moved-out）即时让位、等待期接管、非锁失败保留 attempt 重试、verifier fallback 计数 16 例全绿（tests/test_worktree_acquire_backoff.py，实测「16 passed」；design Non-Goals：不改锁互斥语义与在飞期 adaptive backoff 行为） | pass | 0/2 | - |
| regression-worktree-reuse-claim | 回归：worktree 继承/复用语义不回归——keep-then-create 复用、implementer 认领 reuse record、宽限期后回收、陈旧 worktree 回退新建、部分收敛继承语义 10 例全绿（tests/test_worktree_reuse.py，实测「10 passed」；本次改动触及同文件相邻写点须证无回归） | pass | 0/2 | - |
| regression-engine-degrade-path | 回归：既有 engine 验证/降级路径测试全绿（首次降级语义逐位一致——熔断只拦第 2 次，不动首次降级行为）（tests/test_pm_verification.py，实测「75 passed, 1 xfailed」；-q 安静模式 + N passed 汇总断言口径） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景

