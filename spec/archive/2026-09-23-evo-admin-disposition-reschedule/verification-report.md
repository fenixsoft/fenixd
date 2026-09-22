# 验证报告：evo-admin-disposition-reschedule

> ⚠️ 本报告由框架于 2026-09-18T12:00:43Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T12:00:42.958465+00:00

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.11M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| unhandled-signal-for-returns-escalated | unhandled_signal_for 正向：未处理且 escalated 的 kind=signal 记录被返回（spec/signal_type 严格相等）。出处：core/admin_store.py:523 unhandled_signal_for；用例 tests/test_admin_disposition_reschedule.py::TestUnhandledSignalFor::test_returns_unhandled_escalated_signal | pass | 0/2 | - |
| unhandled-signal-for-returns-latest | unhandled_signal_for 多命中取最新：多条同 (spec, signal_type) 记录返回 created 倒序最新一条。出处：core/admin_store.py:523-556；用例 tests/test_admin_disposition_reschedule.py::TestUnhandledSignalFor::test_returns_latest_match | pass | 0/2 | - |
| unhandled-signal-for-skips-throttled | unhandled_signal_for 异常路径：escalated=False 的节流沉淀记录不返回（从未实际唤起不重派）。出处：core/admin_store.py:546；用例 tests/test_admin_disposition_reschedule.py::TestUnhandledSignalFor::test_throttled_sediment_not_returned | pass | 0/2 | - |
| unhandled-signal-for-spec-strict-equality | unhandled_signal_for 异常路径：spec 严格相等不做宽松匹配（spec-b 与 None 均不命中 spec-a）。出处：core/admin_store.py:550-554；用例 tests/test_admin_disposition_reschedule.py::TestUnhandledSignalFor::test_spec_mismatch_not_returned | pass | 0/2 | - |
| unhandled-signal-for-handled-none | unhandled_signal_for 异常路径：handled=true 的信号记录不返回（已处理不重派）。出处：core/admin_store.py:544；用例 tests/test_admin_disposition_reschedule.py::TestUnhandledSignalFor::test_handled_signal_not_returned | pass | 0/2 | - |
| unhandled-signal-for-type-isolation | unhandled_signal_for 交互隔离：不同 signal_type 互不影响，未落记录的 type 返回 None。出处：core/admin_store.py:548；用例 tests/test_admin_disposition_reschedule.py::TestUnhandledSignalFor::test_signal_type_isolated | pass | 0/2 | - |
| unhandled-signal-for-escalation-kind-excluded | unhandled_signal_for kind 边界：kind=escalation 记录不参与信号回溯（与 unhandled_for 分工，二者不互相污染）。出处：core/admin_store.py:542-543；用例 tests/test_admin_disposition_reschedule.py::TestUnhandledSignalFor::test_escalation_records_not_matched | pass | 0/2 | - |
| reschedule-interrupted-run-redispatches | 重派闭环正向（spec 场景 1）：信号未处理 + 中断 run 超时 → 重派新 run（新 pending disposition 生成、admin_run_id 变更），原 pending 追加 status=superseded 记录（reschedule_count=1、actions_taken 含 signal id still unhandled），无 interrupted 终结、无人工升级。出处：core/admin_monitor.py:1759-1856 _recover_orphaned_dispositions 已知中断分支；用例 tests/test_admin_disposition_reschedule.py::TestRescheduleIntegration::test_signal_unhandled_interrupted_run_reschedules | pass | 0/2 | - |
| reschedule-no-signal-keeps-interrupted | 回归兼容（spec 场景 2 / task 2.6）：无未处理信号记录 → 维持原「终结 interrupted」行为，不重派不升级。出处：core/admin_monitor.py:1857-1878；用例 tests/test_admin_disposition_reschedule.py::TestRescheduleIntegration::test_no_signal_keeps_interrupted_termination | pass | 0/2 | - |
| reschedule-escalated-false-keeps-interrupted | 回归护栏：仅节流沉淀（escalated=False）信号不触发重派，仍终结 interrupted。出处：core/admin_monitor.py:1760-1761（unhandled_signal_for 命中前置）；用例 tests/test_admin_disposition_reschedule.py::TestRescheduleIntegration::test_signal_not_escalated_keeps_interrupted_termination | pass | 0/2 | - |
| reschedule-over-limit-escalates-human | 重派超限升级（spec 场景 3 / task 2.3）：连续 3 次中断（reschedule_count 0→1→2）→ 第 3 次不再重派，产生 kind=escalation severity=critical（description 注明中断/重派次数），该 run 追加非 pending escalated 终结记录；再次巡检不重复升级。出处：core/admin_monitor.py:1763-1814；用例 tests/test_admin_disposition_reschedule.py::TestRescheduleIntegration::test_reschedule_limit_escalates | pass | 0/2 | - |
| reschedule-inflight-run-dedup | 并发去重（spec 场景 4 / task 2.1）：同 (spec, signal_type) 已有在飞 admin run（存在 pending disposition）→ _has_active_admin_run_for 为真，跳过重派不产生新 run，原中断 run 回落终结 interrupted。出处：core/admin_monitor.py:1625-1656 _has_active_admin_run_for；用例 tests/test_admin_disposition_reschedule.py::TestRescheduleIntegration::test_inflight_run_dedup_skips_reschedule | pass | 0/2 | - |
| reschedule-reinterrupted-counts-up | 重派后再次中断计数递增（spec 场景 5 / task 3.5）：新 run 再次中断 → by_run 归并未因非 pending 兄弟记录误判 final，按 reschedule_count=1→2 再判定再重派，不升级。出处：core/admin_monitor.py:1658-1678 _reschedule_count_for + 1708-1722 by_run 归并；用例 tests/test_admin_disposition_reschedule.py::TestRescheduleIntegration::test_rescheduled_run_reinterrupted_counts_up | pass | 0/2 | - |
| reschedule-superseded-not-reprocessed | 重派幂等回归点：superseded 终结后下轮巡检不再处理原 run（只重派一次）。出处：core/admin_monitor.py:1822-1848 superseded 留痕 + by_run final 判定；用例 tests/test_admin_disposition_reschedule.py::TestRescheduleIntegration::test_superseded_run_not_reprocessed_next_round | pass | 0/2 | - |
| reschedule-regression-suite | 全量回归（task 3.6）：test_admin + test_admin_store_corruption + test_admin_dispatch_escalation 存量零引入（168 passed）。出处：tasks.md 3.6 | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

