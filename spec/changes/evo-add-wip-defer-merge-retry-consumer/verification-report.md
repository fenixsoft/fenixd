# 验证报告：evo-add-wip-defer-merge-retry-consumer

> ⚠️ 本报告由框架于 2026-09-24T11:02:22Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-24T11:02:22.598388+00:00

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.13M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| wip-flag-structured-carrier-roundtrip | WIP 重叠闸门阻断落结构化载体：_report_mergeback_wip_overlap 同次 update_spec 增写 _wip_gate_deferred=True（STATE.md 往返后仍读回真布尔）+ 复用 _merge_retry_count/_merge_retry_first_at，同 spec 再次阻断首阻时刻沿用不重置，mergeback_wip_overlap major 告警照常落库（R1/任务1.1/1.2）— 出处：core/pm_engine/dispatch/rollback.py:347、rollback.py:404 落标志写点、core/state_machine.py:395 布尔往返清单 | pass | 0/6 | - |
| wip-status-guard-skip-and-clear | 两层守卫：_retry_merge_back_only 对 status≠implementing（人工/admin 已合并推进）条目跳过合并并清账（标志/计数/首阻全清、状态不改写）；周期扫描层对已推进条目（ready+标志残留）与仅带 _merge_retry_pending 的 spec_dir_inflight 顺延条目均不重试（R2 守卫/任务2.1a）— 出处：core/pm_engine/dispatch/queue.py:2092、queue.py:2111 status 守卫、queue.py:2244-2247 严格筛选 | pass | 0/7 | - |
| wip-consumer-auto-merge-closes-alert | 周期消费者端到端（spec Scenario「WIP 清理后自动合回」）：_recheck_wip_deferred_merges 对 implementing+带标志条目按分支 merge-only 重试成功 → _finalize_merge_success 推进 implemented、标志与顺延记账清账、verifier 入队，原 mergeback_wip_overlap major 告警写 result=resolved 处置记录显式闭环（R2/任务2.1b）— 出处：core/pm_engine/dispatch/queue.py:2218 周期复查、queue.py:2490 成功收尾、queue.py:2535 清账块、queue.py:2346 告警闭环 | pass | 0/8 | - |
| wip-retry-still-blocked-keeps-waiting | 重试仍被 WIP 阻断（异常路径）：计数 +1、首阻时刻沿用、状态保持 implementing 不降级、等待标志保留、error 叠加 deferred 取证形态、不落指纹熔断记账不误冻结 spec（R2 记账/任务2.1b）— 出处：core/pm_engine/dispatch/queue.py:2300 _record_wip_defer_retry_failure、design.md 风险与边界（熔断误记） | pass | 0/8 | - |
| wip-real-conflict-clears-flag-defers | 带标志条目落非 wip 失败（真内容冲突，异常路径）：等待到此结束——先清 _wip_gate_deferred 再交回既有可重试/真失败通道，不自动解决内容冲突，杜绝陈旧标志在恢复 run 在飞期间触发过早合并（design.md 风险与边界/R2 分支）— 出处：core/pm_engine/dispatch/queue.py:2184-2204 清标志再走既有路径、queue.py:1937 _handle_retryable_mergeback_failure | pass | 0/5 | - |
| wip-over-rounds-degrade-once | 有界降级·超轮数（spec Scenario「WIP 长期不清理降级」）：count=6（≥WIP_DEFER_MAX_ROUNDS）时复查停止自动重试（不发起 merge）、状态保持 implementing、现场标志保留供人工取证、降级 mergeback_wip_defer_stuck major 告警落库且同条目二次复查不重复降级（daemon 生命周期内至多一次）、error 更新为 stuck 形态（R3/任务2.1b）— 出处：core/pm_engine/dispatch/queue.py:40-41 常量、queue.py:2269 超限分支、queue.py:2287 once 记账、rollback.py:548 降级告警 | pass | 0/7 | - |
| wip-over-window-degrade-and-boundary | 有界降级·超窗口与未超限边界（spec Scenario「WIP 长期不清理降级」）：首阻起算 ≥90 分钟（first_at=now-91min）停止自动重试并降级 mergeback_wip_defer_stuck；对照 count=5（<6）未超限条目照常 merge-only 重试成功推进 implemented 且不降级（R3/任务2.1b）— 出处：core/pm_engine/dispatch/queue.py:2215 窗口判定、queue.py:2209 _wip_defer_over_limit、core/admin_monitor.py:50 同常量导入 | pass | 0/6 | - |
| orphaned-state-exempts-flagged-unexceeded | orphaned_state 等待期豁免（R4/任务2.3）：_wip_gate_deferred=True 且未超限（计数<6 且窗口<90 分钟）的 implementing 悬置条目（updated 30 分钟前，超 15 分钟缺省阈值）跳过孤儿探测不误召唤 admin；对照无标志同型条目照常成条 orphaned_state（对齐 _repair_awaiting_remerge 同型豁免先例）— 出处：core/admin_monitor.py:1930-1957 豁免块、admin_monitor.py:1909 先例 | pass | 0/3 | - |
| orphaned-state-exemption-expires-over-limits | 豁免自动失效（R4）：带标志但已超限的条目豁免不再生效——超轮数（count=6）与超窗口（首阻 91 分钟前）两种形态下 orphaned_state 探测恢复兜底成条，与 mergeback_wip_defer_stuck 降级告警汇合指向人工（R4/任务2.3）— 出处：core/admin_monitor.py:1939-1957 超限判定（WIP_DEFER_MAX_ROUNDS/WIP_DEFER_WINDOW_MINUTES 同一常量口径） | pass | 0/3 | - |
| boot-preserve-resume-clears-wip-flag | boot 复位写点①保留续做：真实 git 仓库（分支有提交）recover_interrupted 走保留续做路径落 ready+恢复标记后 _wip_gate_deferred 被清除——重启后恢复 run 在飞期间陈旧标志不会让周期消费者把半成品分支过早 merge 进主树（任务1.2/R2 不变式）— 出处：core/state_machine.py:1545 recover_interrupted、state_machine.py:2014 保留续做复位写点、state_machine.py:1970 _recovery_preserve_spec | pass | 0/5 | - |
| boot-clear-rebuild-clears-wip-flag | boot 复位写点②清空重建：真实 git 仓库（分支存在但零提交）recover_interrupted 走清空重建路径落 ready、branch 清空后 _wip_gate_deferred 一并复位 False——全新派发的条目不残留等待标志（任务1.2，对齐该处清 _repair_awaiting_remerge 先例）— 出处：core/state_machine.py:1743 清空重建复位写点 | pass | 0/5 | - |
| wiring-timer-and-single-source-constants | 接线与口径单一：fenixd.py 主循环 120 秒节拍计时器（wip_defer_check_ts >= 120）调用 _recheck_wip_deferred_merges 且 try/except 包裹不中断主循环；WIP_DEFER_WINDOW_MINUTES=90.0/WIP_DEFER_MAX_ROUNDS=6 运行时导入验证；admin_monitor 从 queue 导入同一常量（豁免失效与停止重试单一口径）；五交付文件 _wip_gate_deferred 接线齐全（任务1.1/1.2/2.2/2.3/R4 顺序）— 出处：fenixd.py:654 计时器声明、fenixd.py:803-811 触发点、core/admin_monitor.py:50 常量导入 | pass | 0/9 | - |
| new-suite-wip-defer-full-green | 新增回归套件全绿：tests/test_wip_defer_merge_retry.py 14 例全过（-v 输出含逐用例 PASSED 行，无 parametrize 无后缀），覆盖自动合回+告警闭环/状态守卫/超窗口超轮数降级/仍阻断记账/豁免与失效/boot 两复位写点（任务3.1/spec 三 Scenario）— 出处：tests/test_wip_defer_merge_retry.py:109-403 用例定义（本地实测 14 passed, 5 warnings in 0.51s） | pass | 0/3 | - |
| existing-guard-regression-green | 既有守卫面回归（回归点）：merge-back 顺延守卫/orphaned_state 探测/中断恢复保留续做/dispatch 修复四个被本 SPEC 触碰面的既有套件全数通过——_retry_merge_back_only 新增 status 守卫不破坏既有 spec_dir_inflight 直调与顺延定时器链（守卫拆两层约束），orphaned 豁免不破坏既有探测，boot 复位不破坏既有恢复语义 — 出处：tests/test_merge_back_spec_dir_guard.py、tests/test_orphaned_state_signal.py、tests/test_interrupt_recovery_preserve.py、tests/test_pm_engine_dispatch_fixes.py（本地实测 101 passed in 115.05s） | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

