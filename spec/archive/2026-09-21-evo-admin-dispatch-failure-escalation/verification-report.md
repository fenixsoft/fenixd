# 验证报告：evo-admin-dispatch-failure-escalation

> ⚠️ 本报告由框架于 2026-09-15T10:30:57Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-15T10:30:57.318765+00:00

## 结论：✅ 通过（verified）

**状态：verified — 19/19 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 19/19 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 19 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.37M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dispatch-typeerror-upgrade-critical | D1 核心验证：TypeError 注入 → 恰好 1 条 admin_dispatch_programming_error critical 升级记录（含异常类型/调用点/原信号），用例 tests/test_admin_dispatch_escalation.py::TestDispatchProgrammingErrorEscalation::test_typeerror_escalates_programming_error | pass | 0/2 | - |
| dispatch-oserror-not-programming | D1 分流：OSError 注入 → 不归类为编程错误，保持原 signal_type 升级记录，用例 tests/test_admin_dispatch_escalation.py::TestDispatchProgrammingErrorEscalation::test_oserror_not_classified_as_programming_error | pass | 0/2 | - |
| dispatch-dedup-unhandled | D1 去重：同类 admin_dispatch_programming_error 未处理告警存在时，重复注入跳过不落盘（unhandled_for 去重模式），用例 tests/test_admin_dispatch_escalation.py::TestDispatchProgrammingErrorEscalation::test_unhandled_dedup_same_error_not_double | pass | 0/2 | - |
| dispatch-retry-cooldown-success | D2 重试闭环：冷却到期后重试一次成功 → 升级记录标记 handled（resolve_note=后续派发成功），无残留 critical，用例 tests/test_admin_dispatch_escalation.py::TestDispatchFailureRetry::test_retry_fires_after_cooldown | pass | 0/2 | - |
| dispatch-retry-still-failure-bump | D2 重试失败 bump：重试仍失败 → bump 既有记录 retry_count 至 1（上限 DISPATCH_RETRY_MAX），不追加新记录；达上限后再扫不再重试，用例 tests/test_admin_dispatch_escalation.py::TestDispatchFailureRetry::test_retry_failure_bumps_count_no_new_record | pass | 0/2 | - |
| dispatch-retry-success-closes-alerts | D2 重试成功闭环：重试成功（run_administrator 正常返回）→ 既有升级记录被 handled，resolve_note=后续派发成功，用例 tests/test_admin_dispatch_escalation.py::TestDispatchFailureRetry::test_retry_success_closes_failure_alerts | pass | 0/2 | - |
| dispatch-frozen-spec-skip-retry | D2 frozen 跳过：frozen spec 的派发失败升级记录不触发重试（_retry_due_dispatch_failures 尊重冻结语义），用例 tests/test_admin_dispatch_escalation.py::TestDispatchFailureRetry::test_retry_frozen_spec_skipped | pass | 0/2 | - |
| dispatch-subsequent-dispatch-closes | D2 后续派发闭环：非重试路径的后续正常派发成功 → 既有派发失败升级记录也被闭环（resolve_note=后续派发成功），用例 tests/test_admin_dispatch_escalation.py::TestDispatchFailureRetry::test_subsequent_dispatch_closes_existing_alerts | pass | 0/2 | - |
| dispatch-no-residual-critical | D2 恢复终态：恢复后派发成功 → 无残留未处理 critical 派发失败升级（闭环覆盖全流程回归点），用例 tests/test_admin_dispatch_escalation.py::TestDispatchFailureRetry::test_no_residual_critical_after_success | pass | 0/2 | - |
| dispatch-manual-no-retry-fields | D2 manual 不重试：manual 派发（signal_rec=None）失败只落升级不重试（不带 next_retry_at），用例 tests/test_admin_dispatch_escalation.py::TestDispatchFailureRetry::test_manual_dispatch_no_retry_flag | pass | 0/2 | - |
| dispatch-stash-pop-conflict-replay | D1 验收：回放 stash_pop_conflict dict evidence → 派发失败 → 恰好 1 条 admin_dispatch_programming_error critical 升级记录（含异常类型与调用点），用例 tests/test_admin_dispatch_escalation.py::TestReplayStashPopConflictDictEvidence::test_dict_evidence_stash_pop_conflict_escalates | pass | 0/2 | - |
| dispatch-valueerror-classified | D1 分类：ValueError（含 JSONDecodeError 子类）→ 归类编程错误，用例 tests/test_admin_dispatch_escalation.py::TestDispatchProgrammingErrorEscalation::test_valueerror_also_classified_as_programming_error | pass | 0/2 | - |
| dispatch-agent-runner-none-bump | D2 agent_runner 不可用：重试时 agent_runner=None → bump 后结束，不落新记录，用例 tests/test_admin_dispatch_escalation.py::TestDispatchFailureRetry::test_agent_runner_none_retry_bumps_not_new_record | pass | 0/2 | - |
| dispatch-signal-type-label | D1 标签归类：admin_dispatch_programming_error signal_type 精确匹配，可被标准严重度/推荐动作模型识别，用例 tests/test_admin_dispatch_escalation.py::TestReplayStashPopConflictDictEvidence::test_signal_type_label_for_dashboard | pass | 0/2 | - |
| prompt-str-field-evidence-dict | D3 序列化防回退：evidence dict + recommended_action dict → _str_field 正常构建提示词、不抛 replace 错误，用例 tests/test_agent_prompt_files.py::TestFileLoadAndPlaceholders::test_dispatch_chain_structured_evidence_and_recommendation | pass | 0/2 | - |
| prompt-str-field-regression-guard | D3 回归守卫：原始 stash_pop_conflict dict evidence → 提示词正常构建，conflict_files 关键键值可辨识（回归 fix-alert-evidence-render-crash），用例 tests/test_agent_prompt_files.py::TestFileLoadAndPlaceholders::test_administrator_structured_evidence_rendered | pass | 0/2 | - |
| cli-seed-dispatch-escalation-record | 跨 kind 数据准备：向被测项目 scheduling-showcase 写入一条 admin_dispatch_programming_error 升级记录（kind=escalation, severity=critical, signal_type=admin_dispatch_programming_error），供 api/web 场景经 depends_on 串接消费 | pass | 0/3 | - |
| api-alerts-signal-type | API 端点验证：GET /api/alerts?project=scheduling-showcase 返回 200，alerts 数组含 signal_type=admin_dispatch_programming_error 记录（kind=escalation, severity=critical）。注：/api/admin-activities 只返回 disposition 记录，escalation 只能通过 /api/alerts（AdminStore.read_all）查看 | pass | 0/4 | - |
| web-alerts-signal-render | Web 渲染验证：/activities 页面（hash 路由 #/activities，app.tsx:112）切换到「人工告警」视图，AlertPanel（activities/index.tsx:297）渲染 severity=critical 升级记录，显示「严重」标签与 description 文本「Administrator 派发期编程错误」 | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 19 个（第 1 轮）。

- 首轮写入 19 个场景

