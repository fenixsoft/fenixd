# 验证报告：evo-recovery-watch-status-recheck

> ⚠️ 本报告由框架于 2026-09-18T20:03:03Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T20:03:03.764142+00:00

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.42M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| recheck-inflight-retry-defer | 框架内重试在途→顺延不升级（spec Scenario: 框架内重试在途不升级[误报复现]/重试痕迹在归档目录仍算证据/顺延不丢观察项）：TestInflightRetryDefer 5 用例，覆盖末事件 superseded/transient_retry 未超 inflight_retry_minutes 时顺延不升级、观察项持久化到 .fenix/recovery_watch.json（due 推进）、痕迹仅存 .fenix/runs/archive/ 时仍检、归档前缀歧义守卫（他 spec 前缀命中不算证据）。出处 tests/test_recovery_watch_status_recheck.py:95-166 | pass | 0/6 | - |
| recheck-retry-window-timeout-upgrades | 重试窗口超时→仍升级（异常路径：末事件距 now 超过 inflight_retry_minutes 缺省 5 分钟即不再豁免）：TestInflightRetryWindowTimeout 1 用例，断言 raised==['s1']、观察项弹出、dispatch_stalled 记录 1 条。出处 tests/test_recovery_watch_status_recheck.py:169-185 | pass | 0/2 | - |
| recheck-blocked-closes-watch | 复查时已 blocked（含 frozen）→ 关闭观察项不升级（spec Scenario: 复查时已 blocked 不升级；blocked 由 admin_monitor._detect_blocked_stuck 独立通道告警，避免双通道重复）：TestBlockedDelegatedToBlockedStuck 2 用例，断言观察项弹出、无 dispatch_stalled 记录。出处 tests/test_recovery_watch_status_recheck.py:187-221 | pass | 0/3 | - |
| recheck-no-evidence-still-upgrades | 无正向证据的非 ready 停滞态仍升级（spec Scenario: 无正向证据的 implementing 仍升级/确为 ready 滞留仍升级；MUST NOT 仅因 status 非 ready 顺延，保持 recovery.py:35-39 刻意设计与 test_defer_registers_watch_no_deadloop 到期即信号不变量，回归 3fad3350 语义）：TestNoEvidenceStillUpgrades 2 用例，implementing 无痕迹与 ready 滞留均升级且各产生 1 条 dispatch_stalled。出处 tests/test_recovery_watch_status_recheck.py:224-257 | pass | 0/3 | - |
| recheck-defer-boundedness | 顺延有界性（spec Scenario: 顺延累计超限回落升级/顺延不丢观察项）：累计顺延超 defer_limit_minutes 缺省 30 即回落升级（含过渡窗口同样受门）；未超限时重试在途照常顺延不误伤：TestDeferBoundedness 3 用例。出处 tests/test_recovery_watch_status_recheck.py:260-313 | pass | 0/4 | - |
| recheck-conservative-failure | 二次复查读失败→保守升级（spec Scenario: 二次复查读失败保守升级；重读 status/运行痕迹异常时按保守方向升级，不静默关闭观察项，防止本机制漏报真滞留）：TestConservativeFailure 2 用例，覆盖升级前重读 read_one 抛异常、归属流末行非法 JSON 不可解析。出处 tests/test_recovery_watch_status_recheck.py:316-359 | pass | 0/3 | - |
| recheck-regression-transition-guard | 回归：既有过渡窗口判据全量保持（spec 边界：D2(a) 流缓冲 60s / D1 待合并 grace 缺省 5min 及其有界回落不变）：tests/test_recovery_watch_transition_guard.py 26 用例全绿，抽查 succeed 缓冲顺延、顺延持久化、grace 超限回落三个代表用例。出处 tests/test_recovery_watch_transition_guard.py:75-357 | pass | 0/4 | - |
| recheck-regression-lifecycle-governance | 回归：运行生命周期治理含 test_defer_registers_watch_no_deadloop 到期即信号不变量（implementing + 无活跃派发 + 无运行痕迹必须升级，spec 关键不变量）与 ready 滞留升级语义：tests/test_run_lifecycle_governance.py 78 用例全绿（含 parametrize 展开），抽查不变量用例、就地重派被预算闸门拦下用例与 parametrize 后缀用例。出处 tests/test_run_lifecycle_governance.py:489/603/147 | pass | 0/6 | - |
| recheck-regression-pm-recovery | 回归：pm_engine 恢复相关全量（spec 2.9：tests/test_pm_recovery.py 保持全绿，覆盖派发失败回滚、check_blockers 巡检、恢复巡逻重派与 replan 预算等既有断言不回归）：16 用例全绿，抽查恢复巡逻重派与基建故障非缺陷两用例。出处 tests/test_pm_recovery.py:58-441 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

