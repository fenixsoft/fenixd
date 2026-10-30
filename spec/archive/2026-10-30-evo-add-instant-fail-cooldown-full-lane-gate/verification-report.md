# 验证报告：evo-add-instant-fail-cooldown-full-lane-gate

> ⚠️ 本报告由框架于 2026-10-14T18:20:46Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-14T18:20:45.289646+00:00+run-result@mtime1792002045328094952

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.23M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| gate-planner-plan-skip-info-reenter | 冷却门控覆盖出题派发（spec 场景：冷却期内 planner 派发被跳过）：spec 进入秒挂冷却后，planner-plan 队列条目判定被跳过（_queue_entry_ready 返回 False＝条目保留队列不 pop、attempt 预算不耗），同时排程到期恢复定时器；跳过留痕为 INFO 级且含 spec 名/被拦车道/剩余冷却秒数，旧 DEBUG 口径不再出现；冷却到期（窗内零新失败）后闸门放行、planner-plan 自动重入调度且计数清零。出处 core/pm_engine/dispatch/queue.py:768-781（秒挂闸门）、:60-61（INSTANT_FAIL_GATED_ATYPES 常量集合） | pass | 0/2 | - |
| gate-verifier-skip-info-reenter | 冷却门控覆盖验证派发（spec 场景：冷却期内 verifier 派发被跳过）：spec 处于秒挂冷却时 verifier 队列条目在 implemented/testing 两种状态下均被跳过（返回 False＝不 pop 不耗预算）、排程到期恢复定时器，跳过留痕 INFO 级含 spec 名/车道/剩余秒数；冷却到期后 verifier 放行、验证链恢复推进且计数清零。出处 core/pm_engine/dispatch/queue.py:768-781（闸门）、:731-739（verifier 状态守卫，implemented/testing 同走 _queue_entry_ready 过闸） | pass | 0/2 | - |
| gate-legacy-lanes-no-regression | 门控面既有行为不回归（spec 场景：门控面既有行为不回归）：冷却生效时 implementer/fast-track 队列条目仍被跳过且 INFO 留痕、状态原封；repair 车道直查 _instant_fail_cooled 谓词不回归；闸门常量集合恰为 implementer/fast-track/planner-plan/verifier 四车道（repair/spec-review 不在集合——repair 不经队列、spec-review 为已知范围裁剪）；未冷却 spec 各车道照常放行（门控不误伤）；到期后 implementer/fast-track 放行行为不变。出处 core/pm_engine/dispatch/queue.py:768-781（闸门）、:60-61（常量集合）、core/pm_engine/dispatch/repair_lane.py:269（repair 直查） | pass | 0/2 | - |
| admin-spec-scoped-gate-info | 管理员 spec 作用域处置唤起被门控（spec 场景：spec 作用域处置唤起被门控）：spec 处于秒挂冷却时，_instant_fail_gate 返回（True, 剩余>0），该 spec 作用域的 Administrator 处置唤起被跳过（_invoke_administrator 返回 False＝未派发）并留 INFO 留痕（spec 名、剩余冷却秒数）；跳过不落处置痕、不消耗冷却态，冷却到期后按既有升级语义恢复。出处 core/admin_monitor.py:4338（_instant_fail_gate 判定）、:4881/:5210/:6229（与 signal-kill 冷却检查同点位的三处并列判定） | pass | 0/2 | - |
| admin-global-signal-pass-failopen | 全局自救通道保持放行（spec 场景：全局自救通道保持放行）：daemon_errors 全局信号（spec=null/空串）唤起恒放行——_instant_fail_gate 对空 spec 恒返回 (False, 0) 且不触发 runner 判定（不被任一 spec 的冷却拦截）；runner 缺失或判定异常时 fail-open 放行（与 pm_engine._instant_fail_cooled 同构），不锁死故障期自救通道。出处 core/admin_monitor.py:4338-4372（空 spec 短路与 fail-open 分支） | pass | 0/2 | - |
| recite-entry-state-fields | 到期复诵的状态基底（spec 场景：到期即重派故障循环被抑制的前置）：_record_instant_fail 进入冷却时增记冷却起点/当前冷却时长/翻倍次数（独立于秒挂连击 count，进入时为 0）/末次失败时刻/归一化故障指纹五个字段；窗内新失败沿用既有续写语义——只重写 cooldown_until 与末次失败时刻，不动起点/时长/翻倍次数（复诵算术的基准不被失败续写重置）。出处 core/agent_runner/runner.py:7943-7971（记账临界区）、:228-235（复诵常量与字段语义） | pass | 0/2 | - |
| recite-double-reschedule-info | 到期复诵翻倍（spec 场景：到期即重派故障循环被抑制）：窗内仍有新秒挂（末次失败时刻严格晚于冷却起点，含非门控车道喂入）时，冷却到期不清零——翻倍次数 +1（1/3）、冷却时长 100s→200s、cooldown_until 按翻倍时长续写、冷却起点重置为续写时刻，并留 INFO 续冷却留痕（含「复诵」「翻倍 1/3」与剩余秒数）；恢复定时器随后按新截止重排。出处 core/agent_runner/runner.py:8045-8086（先复诵后消费）、:8108-8123（到期复诵判定与 INFO 留痕） | pass | 0/2 | - |
| recite-strict-gt-recover-zero-new | 复诵严格大于判定与正常恢复（spec 场景：故障消失后正常恢复）：引发本次冷却的失败批次与冷却起点同刻——到期不复诵、清零恢复（计数归零、从 0 重新累计）；窗内零新失败到期 → 条目整体 pop、恢复派发，行为与现网到期恢复一致。出处 core/agent_runner/runner.py:8064-8068（last_fail_at <= cooldown_started_at 即清零）、:8108-8123 | pass | 0/2 | - |
| recite-doubling-capped-three | 翻倍有上限（spec 场景：翻倍有上限）：连续三轮「窗内新失败 → 到期复诵」使时长 100→200→400→800 后，第四轮复诵不再递增翻倍次数（保持 3/3）与冷却时长（保持 800s），按当前时长继续冷却并在到期后按复诵语义重判——保证最坏情况必恢复派发、不饿死。出处 core/agent_runner/runner.py:8073-8081（_INSTANT_FAIL_MAX_DOUBLINGS 上限分支）、:234（上限常量 =3） | pass | 0/2 | - |
| recite-duration-capped-2400 | 单次冷却时长封顶 2400s（spec 场景：翻倍有上限的时长维度）：基准 1300s 冷却复诵翻倍时按 min(1300×2, 2400)=2400s 续写；已达封顶后继续复诵保持 2400s 不再递增，按封顶时长继续冷却。出处 core/agent_runner/runner.py:8075-8081（min(×2, _INSTANT_FAIL_COOLDOWN_CAP_SECONDS)）、:235（封顶常量 =2400） | pass | 0/2 | - |
| recite-fingerprint-normalized | 归一化故障指纹记账（spec 场景：到期即重派故障循环被抑制的留痕素材）：错误原文经路径/run id/端口归一化后，同骨架不同数字（不同 worktree run id、不同端口）产生相同指纹，不同骨架（如 quota 429）指纹不同；空错误原文指纹为空、缺失不阻塞恢复（翻倍判定以「窗内有无新失败」为准）。出处 core/agent_runner/runner.py:7889-7905（_instant_fail_fingerprint，对齐 admin_monitor._error_fingerprint 归一集） | pass | 0/2 | - |
| recovery-timer-deadline-reschedule | 恢复定时器判重放宽（spec 场景：到期即重派故障循环被抑制的定时器面）：共用排程器 _schedule_recovery_timer 接入截止对账后——秒挂通道截止变化（复诵翻倍续写）即 cancel 旧 Timer、按新截止重排（旧句柄 finished、deadline_table 更新），截止未变化保持幂等早退（句柄不变）；信号死法通道同款参数化且既有行为不回归；未接入截止对账的瞬断通道保持纯幂等早退。出处 core/pm_engine/dispatch/backoff.py:292-346（判重放宽与重排实现）、:354-365（deadline/handle 登记表） | pass | 0/2 | - |
| gate-log-source-audit | 门控跳过留痕可观测——源码留痕审计（spec 场景：门控生效可从日志核验）：queue.py 秒挂闸门跳过走 logger.info（含「秒挂冷却中，跳过」「剩余」与到期自动重判提示，不再 DEBUG-only）；闸门集合恰为四车道且不含 repair；admin_monitor 三个并列点位均调用 _instant_fail_gate（spec 作用域）；runner 复诵常量 _INSTANT_FAIL_MAX_DOUBLINGS=3 / 封顶 2400 在位；backoff 截止变化重排实现（resolve_deadline 参数 + old_timer.cancel）在位。出处 core/pm_engine/dispatch/queue.py:764-781、core/admin_monitor.py:4881/5210/6229、core/agent_runner/runner.py:234-235、core/pm_engine/dispatch/backoff.py:321-346 | pass | 0/2 | - |
| new-suite-full-22-passed | 交付测试套件全绿：tests/test_instant_fail_cooldown_gate.py 全量 22 用例（门控面扩展 TestGateSurfaceQueue、管理员纳管 TestAdminGate、到期复诵 TestReciteDoubling、恢复定时器重排 TestRecoveryTimerReschedule 四组）经 pytest -v 全部 PASSED（实测汇总行「22 passed」）。出处 tests/test_instant_fail_cooldown_gate.py:1-491 | pass | 0/2 | - |
| regression-dispatch-suites | 既有派发时序回归（tasks 3.3）：test_pm_dispatch.py + test_verify_dispatch_single_flight.py + test_admin_dispatch_dedup.py 全绿（实测汇总行「83 passed」），门控面扩展到 planner-plan/verifier 不破坏既有派发时序与 admin 派发去重语义。出处 tests/test_pm_dispatch.py、tests/test_verify_dispatch_single_flight.py、tests/test_admin_dispatch_dedup.py | pass | 0/2 | - |
| regression-backoff-sigterm-throughput | 复诵定时器适配回归（tasks 3.3 MUST 项）：test_transient_backoff.py（§6.1 直测 _record_instant_fail 计数/重置语义）+ test_sigterm_source_tracking.py（信号死法冷却恢复定时器——2.3 改的是两通道共用排程器）+ test_verify_lane_throughput.py 全绿（实测汇总行「140 passed」）。出处 tests/test_transient_backoff.py、tests/test_sigterm_source_tracking.py、tests/test_verify_lane_throughput.py | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

