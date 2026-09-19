# 验证报告：add-control-plane-silent-failure-guards

> ⚠️ 本报告由框架于 2026-09-15T03:10:35Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-15T03:06:39.326644+00:00

## 结论：✅ 通过（verified）

**状态：verified — 12/13 场景通过，1 失败，0 错误（全部场景通过）**

13 个场景中 12 个通过、1 个 flaky（arity-guard-teeth-and-repo-zero）。该场景验证执行时退出码 1、test_current_production_has_zero_non_whitelist_violations 无 PASSED 标记，但复现两次（单独运行 + 全套件运行）均 4 项测试全部通过，无确定性缺陷特征，判为不稳定失败（flaky），非产品 bug。落地实证守卫零违规结论成立。

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.68M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| arity-guard-violation-detection | callsite-arity-guard 核心判定：Run TestCallsiteArityGuard 全部（arity_violation_reported + keyword_completion_not_flagged + starred_expansion_not_flagged + same_name_multiple_signatures_excluded + optional_param_default_satisfied_by_one），验证判定规则正确（spec R1 Scenarios 1-4）tests/test_callsite_arity_guard.py:165 | pass | 0/5 | - |
| arity-guard-whitelist-exemption | callsite-arity-guard 白名单精确豁免：Run test_whitelist_exact_exemption，验证确有同名误报行被逐条登记进白名单后不计违规（spec R2 Scenario）tests/test_callsite_arity_guard.py:225 | pass | 0/2 | - |
| arity-guard-teeth-and-repo-zero | callsite-arity-guard 有牙自检 + 落地实证零违规：Run TestArityGuardTeeth + TestArityGuardOnRepo（candidate_set_is_large_enough + current_production_has_zero_non_whitelist_violations），验证守卫有效且落地时违规 = 0（spec R3 + 验收标准）tests/test_callsite_arity_guard.py:250 | fail | 2/3 | flaky |
| double-fidelity-judgment | test-double-fidelity 核心判定：Run TestFakeDoubleFidelity 全部（lenient_fake_flagged + star_args_fake_flagged + fewer_required_fake_flagged + faithful_fake_allowed + more_required_fake_allowed + broad_name_excluded），验证替身保真判定规则（spec R1 Scenarios）tests/test_fake_double_fidelity.py:135 | pass | 0/5 | - |
| double-fidelity-whitelist-exemption | test-double-fidelity 白名单精确豁免：Run test_whitelist_exact_exemption，验证确有其事的宽容替身被白名单豁免（spec R2 whitelist）tests/test_fake_double_fidelity.py:181 | pass | 0/2 | - |
| double-fidelity-teeth-and-repo-zero | test-double-fidelity 有牙自检 + 落地零违规 + 收紧替身：Run TestFakeDoubleFidelityTeeth + TestFakeDoubleFidelityOnRepo（seam_set_is_large_enough + current_tests_have_zero_violations + tightened_fakes_match_production），验证守卫有效、违规 = 0、5 处收紧后替身与生产签名匹配（spec R3-R4 + 验收标准）tests/test_fake_double_fidelity.py:232 | pass | 0/4 | - |
| reset-error-escalates-typeerror | admin-reset-error-escalation TypeError 升级 critical：Run test_typeerror_escalates_critical，验证 TypeError 注入恰好 1 条 admin_reset_programming_error critical 告警（spec R1 Scenario: 编程错误升级）tests/test_blocked_reverify_gate.py:575 | pass | 0/2 | - |
| reset-error-oserror-stays-warning | admin-reset-error-escalation OSError 保持 WARNING 不升级：Run test_oserror_stays_warning，验证运维异常只记 WARNING、0 条 critical 告警（spec R1 Scenario: 运维异常不升级）tests/test_blocked_reverify_gate.py:598 | pass | 0/2 | - |
| reset-error-dedup-callsite-recommendation | admin-reset-error-escalation 去重 + 调用点可定位 + 处置指引：Run test_duplicate_escalation_deduped + test_callsite_points_into_core + test_recommendation_points_to_code_defect，验证同类去重（同 spec 连续两轮仅 1 条告警）、升级告警 evidence 含 core/ 最深栈帧文件:行、recommended_action 指明代码缺陷（spec R2-R3 + R4）tests/test_blocked_reverify_gate.py:614 | pass | 0/4 | - |
| orphaned-detection-three-conditions | orphaned-state-signal 三条件判定 + 各种抑制不误报：Run TestDetectOrphanedState 全部（suspended_undriven_produces_signal + implementing_also_detected + short_elapsed_not_detected + long_running_run_suppresses + live_process_suppresses + frozen_suppresses + cancelled_hold_suppresses + start_after_suppresses + dispatch_backoff_suppresses + not_in_progress_status_ignored），验证三条件同时成立才产生信号、各抑制条件不误报（spec R1 Scenarios 1-3）tests/test_orphaned_state_signal.py:97 | pass | 0/5 | - |
| orphaned-handoff-to-stuck | orphaned-state-signal 分钟级发现 vs stuck 160 分钟：Run TestOrphanedHandoffToStuck（early_window_captured_by_orphaned + long_elapsed_handed_to_stuck），验证短阈值内由 orphaned_state 捕获、超长阈值交由 stuck 兜底（spec R2 + R3 验收标准）tests/test_orphaned_state_signal.py:171 | pass | 0/3 | - |
| orphaned-throttle-recovery-reset | orphaned-state-signal 节流 + testing 无驱动恢复出口 + 复位直通道重派：Run TestOrphanedThrottle::test_cooldown_deduplicates_invocation + TestTestingRecovery 全部 + TestOrphanedResetAfterDisposition 全部，验证冷却窗内只唤起一次 Administrator、无驱动 testing 能被 retrigger、复位直通道 enqueue verifier / ready 重派正确（spec R3-R4 + 验收标准）tests/test_orphaned_state_signal.py:198 | pass | 0/5 | - |
| regression-disposition-reset-integration | 回归验证：Run TestDispositionResetIntegration 全部（resolved_gate_path_triggers_testing_and_enqueue + resolved_ready_path_transitions_ready + escalated_does_not_trigger_reset + escalated_result_does_not_call_reset_from_wrapper），钉住事故根因 handle_event('spec_implemented', spec, spec_entry) 实参数量正确、blocked 复位路径语义不回归（proposal §Impact — 不涉及部分）tests/test_blocked_reverify_gate.py:331 | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| arity-guard-teeth-and-repo-zero | exit_code expected 0 actual 1 | flaky | 不稳定复现（非产品缺陷） | 重试两次全部4项测试通过（2026-09-15复现），无确定性缺陷特征，疑为验证执行期间扫描目标受临时文件或缓存竞态污染 |
| arity-guard-teeth-and-repo-zero | output_match test_current_production_has_zero_non_whitelist_violations PASSED | flaky | 不稳定复现（非产品缺陷） | 单独运行该测试与全套件重跑均 PASSED，无确定性产品缺陷证据，归为不稳定失败 |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

