# facade-inventory：三处门面转发全集（阶段 0 权威清单）

> 生成方式：`python3 .history/inventory_facade.py`（AST 扫描，判据=函数体仅一条 `return`（允许前置 docstring），返回值为 `self.<子对象>.<方法>(...)` / 模块级函数调用 / 兄弟类静态方法调用；向 stdlib 的调用不计入）。
> 本清单是收敛对象与契约测试覆盖性硬门的**逐名权威来源**：任何转发方法名未登记于此即视为扫描遗漏。

## 汇总

| 门面 | 实例式（首参 `self`/`pipe`） | 静态式（首参非 `self`/`pipe`） | 合计 | stdlib 保留真方法 |
|---|---|---|---|---|
| PMEngine（`core/pm_engine/engine.py`） | 100 | 10 | 110 | 0 |
| VerificationPipeline（`core/pm_engine/verification/pipeline.py`） | 85 | 5 | 90 | 0 |
| AgentRunner（`core/agent_runner/runner.py`） | 52 | 15 | 67 | 2 |

合计：实例式 **237**（PMEngine 100 / VerificationPipeline 85 / AgentRunner 52）＋ 静态式 **30**（10/5/15）＝ **267** 收敛对象；stdlib 保留真方法 2（均在 AgentRunner：`_now`、`_normalize_run_id`）。

> 注：design 正文表格为成稿时实测（AgentRunner 实例式 51、静态式 12），本清单为阶段 0 实测——① AgentRunner 实例式 52 含其后新增 signal-kill 冷却族 4 个转发；② 3 个目标不以 `self` 为首参的模块函数（`_read_admin_disposition` / `_read_self_review_out` / `_check_artifact_json_file`）MUST 以类级别名收敛（partial 会多注 self），故静态式 15（design 12 + 3）；③ `_salvage_spec_review_result` 为薄包装真方法（引用 `self.project_root` + 常量参数，非纯转发），保留为显式方法。design 明示「逐名权威清单以阶段 0 落盘的 facade-inventory.md 为准」。

## PMEngine（`core/pm_engine/engine.py`）

实例组注册表目标为惰性 property：`_verification`/`_dispatcher`/`_family`/`_budget`/`_recovery`/`_reporting`/`_spec_integrity`（`@property`，首访经 `__getattr__` 触发构造）。

### 实例式转发（首参 `self`/`pipe`）

| 方法名 | 转发目标 | 形态 |
|---|---|---|
| _resolve_fix_spec_name | `_family._resolve_fix_spec_name` | 子对象委托
| _ensure_fix_spec_files | `_family._ensure_fix_spec_files` | 子对象委托
| _family_width | `_family._family_width` | 子对象委托
| _family_waiver_set | `_family._family_waiver_set` | 子对象委托
| _consume_family_waiver | `_family._consume_family_waiver` | 子对象委托
| _family_gate_blocked | `_family._family_gate_blocked` | 子对象委托
| _same_root_siblings | `_family._same_root_siblings` | 子对象委托
| _sibling_repair_active | `_family._sibling_repair_active` | 子对象委托
| _sibling_has_live_agent | `_family._sibling_has_live_agent` | 子对象委托
| _has_non_terminal_child_fix | `_family._has_non_terminal_child_fix` | 子对象委托
| _signal_family_explosion | `_family._signal_family_explosion` | 子对象委托
| _do_spec_bug_found | `_family._do_spec_bug_found` | 子对象委托
| _do_legacy_fix_spec_bug_found | `_family._do_legacy_fix_spec_bug_found` | 子对象委托
| _inject_verify_fix_task | `_family._inject_verify_fix_task` | 子对象委托
| _send_human_escalation_alert | `_family._send_human_escalation_alert` | 子对象委托
| _impl_run_budget | `_budget._impl_run_budget` | 子对象委托
| _increment_impl_run_budget_used | `_budget._increment_impl_run_budget_used` | 子对象委托
| _budget_exempt_alert_threshold | `_budget._budget_exempt_alert_threshold` | 子对象委托
| _exempt_dead_run_budget | `_budget._exempt_dead_run_budget` | 子对象委托
| _exempt_infra_run_budget | `_budget._exempt_infra_run_budget` | 子对象委托
| _alert_budget_exempt_loop | `_budget._alert_budget_exempt_loop` | 子对象委托
| _reconcile_impl_budget | `_budget._reconcile_impl_budget` | 子对象委托
| _count_normal_completed_impl_runs | `_budget._count_normal_completed_impl_runs` | 子对象委托
| _impl_run_budget_used | `_budget._impl_run_budget_used` | 子对象委托
| _check_impl_budget_exhausted | `_budget._check_impl_budget_exhausted` | 子对象委托
| _check_spec_content_missing | `_spec_integrity.check_spec_content_missing` | 子对象委托
| _read_verify_report | `_verification._read_verify_report` | 子对象委托
| _handle_env_blocked_inconclusive | `_verification._handle_env_blocked_inconclusive` | 子对象委托
| _ensure_app_reachable | `_verification._ensure_app_reachable` | 子对象委托
| _rewrite_scenario_port | `_verification._rewrite_scenario_port` | 子对象委托
| _current_verify_round | `_verification._current_verify_round` | 子对象委托
| _apply_scenario_freeze | `_verification._apply_scenario_freeze` | 子对象委托
| _run_scenario_static_check | `_verification._run_scenario_static_check` | 子对象委托
| _scenario_defect_reroute_gate | `_verification._scenario_defect_reroute_gate` | 子对象委托
| _apply_interaction_contract | `_verification._apply_interaction_contract` | 子对象委托
| _render_scenario_change_section_to_report | `_verification._render_scenario_change_section_to_report` | 子对象委托
| _run_three_stage_verification | `_verification._run_three_stage_verification` | 子对象委托
| _verifier_error_is_infra | `_verification._verifier_error_is_infra` | 子对象委托
| enrich_failure_class | `_verification.enrich_failure_class` | 子对象委托
| _verifier_result_is_stale | `_verification._verifier_result_is_stale` | 子对象委托
| _implementer_zero_change | `_verification._implementer_zero_change` | 子对象委托
| _implementation_branch_has_commits | `_verification._implementation_branch_has_commits` | 子对象委托
| _deliverable_gate_missing | `_verification._deliverable_gate_missing` | 子对象委托
| _tasks_md_relint_from_branch | `_verification._tasks_md_relint_from_branch` | 子对象委托
| _tasks_md_relint_from_worktree | `_verification._tasks_md_relint_from_worktree` | 子对象委托
| _disputed_deliverables | `_verification._disputed_deliverables` | 子对象委托
| _adjudicate_deliverable_missing | `_dispatcher._adjudicate_deliverable_missing` | 子对象委托
| _detect_uniform_verify_failure | `_verification._detect_uniform_verify_failure` | 子对象委托
| _run_legacy_verification | `_verification._run_legacy_verification` | 子对象委托
| _verify_verdict_evidence | `_verification._verify_verdict_evidence` | 子对象委托
| _speculative_bug_found_gate | `_verification._speculative_bug_found_gate` | 子对象委托
| _env_whitewash_gate | `_verification._env_whitewash_gate` | 子对象委托
| _escalate_env_blocked | `_verification._escalate_env_blocked` | 子对象委托
| _record_infra_failure | `_verification._record_infra_failure` | 子对象委托
| _update_warning_streaks | `_verification._update_warning_streaks` | 子对象委托
| _warning_stale_triage_alert | `_verification._warning_stale_triage_alert` | 子对象委托
| _ensure_verification_report | `_verification._ensure_verification_report` | 子对象委托
| _check_verification_gate | `_verification._check_verification_gate` | 子对象委托
| _read_verifier_result | `_verification._read_verifier_result` | 子对象委托
| _read_planner_result | `_verification._read_planner_result` | 子对象委托
| _read_verdict | `_verification._read_verdict` | 子对象委托
| _judge_bugs_declare_env | `_verification._judge_bugs_declare_env` | 子对象委托
| _handle_judge_env_declared | `_verification._handle_judge_env_declared` | 子对象委托
| _verdict_violations_path | `_verification._verdict_violations_path` | 子对象委托
| _write_verdict_violations | `_verification._write_verdict_violations` | 子对象委托
| _clear_verdict_violations | `_verification._clear_verdict_violations` | 子对象委托
| _read_fail_history | `_verification._read_fail_history` | 子对象委托
| _append_fail_history | `_verification._append_fail_history` | 子对象委托
| _clear_fail_history | `_verification._clear_fail_history` | 子对象委托
| _failed_scenario_ids | `_verification._failed_scenario_ids` | 子对象委托
| _dispatch_backoff_schedule | `_dispatcher._dispatch_backoff_schedule` | 子对象委托
| _handle_dispatch_lock_conflict | `_dispatcher._handle_dispatch_lock_conflict` | 子对象委托
| _schedule_backoff_retry | `_dispatcher._schedule_backoff_retry` | 子对象委托
| _get_spec_priority | `_dispatcher._get_spec_priority` | 子对象委托
| _enqueue | `_dispatcher._enqueue` | 子对象委托
| _enqueue_front | `_dispatcher._enqueue_front` | 子对象委托
| _aging_bonus | `_dispatcher._aging_bonus` | 子对象委托
| _effective_priority | `_dispatcher._effective_priority` | 子对象委托
| _process_queue | `_dispatcher._process_queue` | 子对象委托
| _run_agent_worker | `_dispatcher._run_agent_worker` | 子对象委托
| _rollback_failed_dispatch | `_dispatcher._rollback_failed_dispatch` | 子对象委托
| _report_stash_pop_conflict | `_dispatcher._report_stash_pop_conflict` | 子对象委托
| _run_fast_track_worker | `_dispatcher._run_fast_track_worker` | 子对象委托
| _should_enter_repair | `_dispatcher._should_enter_repair` | 子对象委托
| _dispatch_repair_lane | `_dispatcher._dispatch_repair_lane` | 子对象委托
| _claim_repair_site | `_dispatcher._claim_repair_site` | 子对象委托
| _run_repair_worker | `_dispatcher._run_repair_worker` | 子对象委托
| _check_repair_commit_facts | `_dispatcher._check_repair_commit_facts` | 子对象委托
| _handle_remerge_failure | `_dispatcher._handle_remerge_failure` | 子对象委托
| _fallback_after_repair | `_dispatcher._fallback_after_repair` | 子对象委托
| _recovery_watch_path | `_recovery._recovery_watch_path` | 子对象委托
| _load_recovery_watch | `_recovery._load_recovery_watch` | 子对象委托
| _save_recovery_watch | `_recovery._save_recovery_watch` | 子对象委托
| register_recovery_watch | `_recovery.register_recovery_watch` | 子对象委托
| check_recovery_watch | `_recovery.check_recovery_watch` | 子对象委托
| _signal_dispatch_stalled | `_recovery._signal_dispatch_stalled` | 子对象委托
| _clear_dispatch_conflict | `_recovery._clear_dispatch_conflict` | 子对象委托
| generate_report | `_reporting.generate_report` | 子对象委托
| generate_daily_report | `_reporting.generate_daily_report` | 子对象委托
| get_pushable_specs | `_reporting.get_pushable_specs` | 子对象委托

### 静态式转发（首参非 `self`/`pipe`）

| 方法名 | 转发目标 | 收敛方式 |
|---|---|---|
| _fix_prefix_depth | `_fix_prefix_depth` | 类级别名（D7） |
| _fix_strip_all | `_fix_strip_all` | 类级别名（D7） |
| _is_fix_spec | `_is_fix_spec` | 类级别名（D7） |
| _same_root | `_same_root` | 类级别名（D7） |
| _run_file_died | `_run_file_died` | 类级别名（D7） |
| _normalize_fail_signature | `_normalize_fail_signature` | 类级别名（D7） |
| _dispatch_backoffed | `_dispatch_backoffed` | 类级别名（D7） |
| _spec_fingerprint | `_spec_fingerprint` | 类级别名（D7） |
| _is_push_backoffed | `_is_push_backoffed` | 类级别名（D7） |
| _get_push_retry_count | `_get_push_retry_count` | 类级别名（D7） |

## VerificationPipeline（`core/pm_engine/verification/pipeline.py`）

### 实例式转发（首参 `self`/`pipe`）

| 方法名 | 转发目标 | 形态 |
|---|---|---|
| _read_verify_report | `_read_verify_report`（模块级函数） | 模块函数 |
| _ensure_verification_report | `_ensure_verification_report`（模块级函数） | 模块函数 |
| _check_verification_gate | `_check_verification_gate`（模块级函数） | 模块函数 |
| _verifier_result_is_stale | `_verifier_result_is_stale`（模块级函数） | 模块函数 |
| _read_verifier_result | `_read_verifier_result`（模块级函数） | 模块函数 |
| _read_planner_result | `_read_planner_result`（模块级函数） | 模块函数 |
| _read_verdict | `_read_verdict`（模块级函数） | 模块函数 |
| _branch_commit_count | `_branch_commit_count`（模块级函数） | 模块函数 |
| _implementation_branch_has_commits | `_implementation_branch_has_commits`（模块级函数） | 模块函数 |
| _implementer_zero_change | `_implementer_zero_change`（模块级函数） | 模块函数 |
| _deliverable_gate_missing | `_deliverable_gate_missing`（模块级函数） | 模块函数 |
| _tasks_md_relint_from_branch | `_tasks_md_relint_from_branch`（模块级函数） | 模块函数 |
| _tasks_md_relint_from_worktree | `_tasks_md_relint_from_worktree`（模块级函数） | 模块函数 |
| _disputed_deliverables | `_disputed_deliverables`（模块级函数） | 模块函数 |
| _verifier_error_is_infra | `_verifier_error_is_infra`（模块级函数） | 模块函数 |
| enrich_failure_class | `enrich_failure_class`（模块级函数） | 模块函数 |
| _record_infra_failure | `_record_infra_failure`（模块级函数） | 模块函数 |
| _detect_uniform_verify_failure | `_detect_uniform_verify_failure`（模块级函数） | 模块函数 |
| _fail_history_path | `_fail_history_path`（模块级函数） | 模块函数 |
| _read_fail_history | `_read_fail_history`（模块级函数） | 模块函数 |
| _append_fail_history | `_append_fail_history`（模块级函数） | 模块函数 |
| _clear_fail_history | `_clear_fail_history`（模块级函数） | 模块函数 |
| _scenario_classification_distribution | `_scenario_classification_distribution`（模块级函数） | 模块函数 |
| _failed_scenario_ids | `_failed_scenario_ids`（模块级函数） | 模块函数 |
| _apply_scenario_freeze | `_apply_scenario_freeze`（模块级函数） | 模块函数 |
| _apply_interaction_contract | `_apply_interaction_contract`（模块级函数） | 模块函数 |
| _render_scenario_change_section_to_report | `_render_scenario_change_section_to_report`（模块级函数） | 模块函数 |
| _write_verify_contract_missing | `_write_verify_contract_missing`（模块级函数） | 模块函数 |
| _run_scenario_static_check | `_run_scenario_static_check`（模块级函数） | 模块函数 |
| _run_contract_static_check | `_run_contract_static_check`（模块级函数） | 模块函数 |
| _ensure_serving_worktree | `_ensure_serving_worktree`（模块级函数） | 模块函数 |
| _serve_static_in_main | `_serve_static_in_main`（模块级函数） | 模块函数 |
| _serve_static_in_worktree | `_serve_static_in_worktree`（模块级函数） | 模块函数 |
| _serve_command_in_worktree | `_serve_command_in_worktree`（模块级函数） | 模块函数 |
| _serve_command_in_main | `_serve_command_in_main`（模块级函数） | 模块函数 |
| _finalize_static | `_finalize_static`（模块级函数） | 模块函数 |
| _remove_serving_worktree | `_remove_serving_worktree`（模块级函数） | 模块函数 |
| _register_serving_instance | `_register_serving_instance`（模块级函数） | 模块函数 |
| _unregister_serving_instance | `_unregister_serving_instance`（模块级函数） | 模块函数 |
| _evict_spec_serving | `_evict_spec_serving`（模块级函数） | 模块函数 |
| _current_instance_base_url | `_current_instance_base_url`（模块级函数） | 模块函数 |
| _ensure_app_reachable | `_ensure_app_reachable`（模块级函数） | 模块函数 |
| _open_boot_log | `_open_boot_log`（模块级函数） | 模块函数 |
| _read_boot_log_tail | `_read_boot_log_tail`（模块级函数） | 模块函数 |
| _rewrite_scenario_port | `_rewrite_scenario_port`（模块级函数） | 模块函数 |
| _serving_port_for_spec | `_serving_port_for_spec`（模块级函数） | 模块函数 |
| _current_verify_round | `_current_verify_round`（模块级函数） | 模块函数 |
| _handle_env_blocked_inconclusive | `_handle_env_blocked_inconclusive`（模块级函数） | 模块函数 |
| _write_inconclusive_loop_signal | `_write_inconclusive_loop_signal`（模块级函数） | 模块函数 |
| _env_whitewash_gate | `_env_whitewash_gate`（模块级函数） | 模块函数 |
| _escalate_env_blocked | `_escalate_env_blocked`（模块级函数） | 模块函数 |
| _update_warning_streaks | `_update_warning_streaks`（模块级函数） | 模块函数 |
| _warning_stale_triage_alert | `_warning_stale_triage_alert`（模块级函数） | 模块函数 |
| _scenario_defect_reroute_gate | `_scenario_defect_reroute_gate`（模块级函数） | 模块函数 |
| _escalate_scenario_defect_reroute | `_escalate_scenario_defect_reroute`（模块级函数） | 模块函数 |
| _handle_judge_env_declared | `_handle_judge_env_declared`（模块级函数） | 模块函数 |
| _judge_bugs_declare_env | `_judge_bugs_declare_env`（模块级函数） | 模块函数 |
| _speculative_bug_found_gate | `_speculative_bug_found_gate`（模块级函数） | 模块函数 |
| _run_legacy_verification | `_run_legacy_verification`（模块级函数） | 模块函数 |
| _verify_verdict_evidence | `_verify_verdict_evidence`（模块级函数） | 模块函数 |
| _verdict_violations_evidence | `_verdict_violations_evidence`（模块级函数） | 模块函数 |
| _write_verdict_violations | `_write_verdict_violations`（模块级函数） | 模块函数 |
| _clear_verdict_violations | `_clear_verdict_violations`（模块级函数） | 模块函数 |
| _verdict_violations_path | `_verdict_violations_path`（模块级函数） | 模块函数 |
| _resynthesis_directive_path | `_resynthesis_directive_path`（模块级函数） | 模块函数 |
| _read_resynthesis_directive | `_read_resynthesis_directive`（模块级函数） | 模块函数 |
| _clear_resynthesis_directive | `_clear_resynthesis_directive`（模块级函数） | 模块函数 |
| _resynthesis_directive_scenarios | `_resynthesis_directive_scenarios`（模块级函数） | 模块函数 |
| _write_resynthesis_directive | `_write_resynthesis_directive`（模块级函数） | 模块函数 |
| _escalate_dedup_resynthesis | `_escalate_dedup_resynthesis`（模块级函数） | 模块函数 |
| _handle_attr_dedup_rejection | `_handle_attr_dedup_rejection`（模块级函数） | 模块函数 |
| _handle_scenario_requeue | `_handle_scenario_requeue`（模块级函数） | 模块函数 |
| _clear_requeue_manifest | `_clear_requeue_manifest`（模块级函数） | 模块函数 |
| _record_verdict_adoption | `_record_verdict_adoption`（模块级函数） | 模块函数 |
| _persist_verdict_cache | `_persist_verdict_cache`（模块级函数） | 模块函数 |
| _verified_verdict_persisted | `_verified_verdict_persisted`（模块级函数） | 模块函数 |
| _verified_gate_refuses | `_verified_gate_refuses`（模块级函数） | 模块函数 |
| _judge_dispatch_gate | `_judge_dispatch_gate`（模块级函数） | 模块函数 |
| _judge_hard_cap_freeze | `_judge_hard_cap_freeze`（模块级函数） | 模块函数 |
| _judge_rerun_count | `_judge_rerun_count`（模块级函数） | 模块函数 |
| _all_green_fast_path | `_all_green_fast_path`（模块级函数） | 模块函数 |
| _last_planner_cost_usd | `_last_planner_cost_usd`（模块级函数） | 模块函数 |
| _last_planner_run_cost | `_last_planner_run_cost`（模块级函数） | 模块函数 |
| _write_degrade_context | `_write_degrade_context`（模块级函数） | 模块函数 |
| _clear_degrade_context | `_clear_degrade_context`（模块级函数） | 模块函数 |

### 静态式转发（首参非 `self`/`pipe`）

| 方法名 | 转发目标 | 收敛方式 |
|---|---|---|
| _extract_replan_error_items | `_bg_extract_replan_error_items` | 类级别名（D7） |
| _replan_errors_unconsumed | `_bg_replan_errors_unconsumed` | 类级别名（D7） |
| _normalize_fail_signature | `_normalize_fail_signature` | 类级别名（D7） |
| _load_frozen_scenarios | `_load_frozen_scenarios` | 类级别名（D7） |
| _port_responds | `_port_responds` | 类级别名（D7） |

## AgentRunner（`core/agent_runner/runner.py`）

实例组注册表目标为惰性 property：`_liveness`/`_provider_circuit`/`_prompt_builder`/`_v2_server`/`_token_accountant`（`@property`）。

### 实例式转发（首参 `self`/`pipe`）

| 方法名 | 转发目标 | 形态 |
|---|---|---|
| run_administrator | `run_administrator`（模块级函数） | 模块函数 |
| _read_admin_disposition | `_read_admin_disposition`（模块级函数） | 模块函数 |
| run_self_review | `run_self_review`（模块级函数） | 模块函数 |
| _read_self_review_out | `_read_self_review_out`（模块级函数） | 模块函数 |
| run_evolution | `run_evolution`（模块级函数） | 模块函数 |
| _get_admin_model | `_get_admin_model`（模块级函数） | 模块函数 |
| _salvage_spec_review_result | `salvage_result_from_transcript`（模块级函数） | 模块函数 |
| _build_prompt | `_prompt_builder._build_prompt` | 子对象委托
| _check_artifact_json_file | `_check_artifact_json_file`（模块级函数） | 模块函数 |
| _check_agent_result_artifact | `_check_agent_result_artifact`（模块级函数） | 模块函数 |
| _check_impl_result_artifact | `_check_impl_result_artifact`（模块级函数） | 模块函数 |
| _check_success_completion | `_check_success_completion`（模块级函数） | 模块函数 |
| _check_partial_consistency | `_check_partial_consistency`（模块级函数） | 模块函数 |
| _check_taskupdate_crosscheck | `_check_taskupdate_crosscheck`（模块级函数） | 模块函数 |
| _build_legacy_section | `_prompt_builder._build_legacy_section` | 子对象委托
| _legacy_dirty_snapshot | `_prompt_builder._legacy_dirty_snapshot` | 子对象委托
| _scenario_freeze_section | `_prompt_builder._scenario_freeze_section` | 子对象委托
| _interaction_contract_section | `_prompt_builder._interaction_contract_section` | 子对象委托
| _triage_recheck_section | `_prompt_builder._triage_recheck_section` | 子对象委托
| _verdict_rejection_section | `_prompt_builder._verdict_rejection_section` | 子对象委托
| _circuit_state | `_provider_circuit._circuit_state` | 子对象委托
| is_circuit_open | `_provider_circuit.is_circuit_open` | 子对象委托
| is_switch_cooldown | `_provider_circuit.is_switch_cooldown` | 子对象委托
| _record_switch_cooldown | `_provider_circuit._record_switch_cooldown` | 子对象委托
| _write_provider_marker | `_provider_circuit._write_provider_marker` | 子对象委托
| _record_daily_provider_attempt | `_provider_circuit._record_daily_provider_attempt` | 子对象委托
| _circuit_open_error | `_provider_circuit._circuit_open_error` | 子对象委托
| _record_provider_4xx | `_provider_circuit._record_provider_4xx` | 子对象委托
| _record_provider_probe | `_provider_circuit._record_provider_probe` | 子对象委托
| record_transient_break | `_provider_circuit.record_transient_error` | 子对象委托
| is_global_transient_break_active | `_provider_circuit.is_global_transient_break` | 子对象委托
| is_signal_kill_cooldown | `_provider_circuit.is_signal_kill_cooldown` | 子对象委托
| signal_kill_cooldown_until | `_provider_circuit.signal_kill_cooldown_until` | 子对象委托
| _signal_kill_counts | `_provider_circuit.signal_kill_counts` | 子对象委托
| _record_signal_kill | `_provider_circuit.record_signal_kill` | 子对象委托
| _accumulate_token_usage | `_token_accountant._accumulate_token_usage` | 子对象委托
| _check_token_budget | `_token_accountant._check_token_budget` | 子对象委托
| _send_token_alert | `_token_accountant._send_token_alert` | 子对象委托
| _record_verify_progress_tokens | `_token_accountant._record_verify_progress_tokens` | 子对象委托
| _v2_ensure_state | `_v2_server._v2_ensure_state` | 子对象委托
| _v2_launch_for_worktree | `_v2_server._v2_launch_for_worktree` | 子对象委托
| _v2_inject_env | `_v2_server._v2_inject_env` | 子对象委托
| _v2_stop_for_worktree | `_v2_server._v2_stop_for_worktree` | 子对象委托
| _v2_stop_all | `_v2_server._v2_stop_all` | 子对象委托
| has_live_attempt | `_liveness.has_live_attempt` | 子对象委托
| sweep_dangling_runs | `_liveness.sweep_dangling_runs` | 子对象委托
| _pgrep_live_attempt | `_liveness._pgrep_live_attempt` | 子对象委托
| _stream_recent | `_liveness._stream_recent` | 子对象委托
| note_run_extension | `_liveness.note_run_extension` | 子对象委托
| get_extension_baseline | `_liveness.get_extension_baseline` | 子对象委托
| _liveness_snapshot | `_liveness._liveness_snapshot` | 子对象委托
| _judge_liveness | `_liveness._judge_liveness` | 子对象委托
| _supervision_settings | `_liveness._supervision_settings` | 子对象委托
| _supervision_judge_timeout | `_liveness._supervision_judge_timeout` | 子对象委托
| _supervision_deadline_action | `_liveness._supervision_deadline_action` | 子对象委托
| wait_for_running_agents | `_liveness.wait_for_running_agents` | 子对象委托
| running_run_ids | ``（模块级函数） | 模块函数 |

### 静态式转发（首参非 `self`/`pipe`）

| 方法名 | 转发目标 | 收敛方式 |
|---|---|---|
| _entry_is_tool_result | `_entry_is_tool_result` | 类级别名（D7） |
| _format_gap_list | `_format_gap_list` | 类级别名（D7） |
| _invalid_completed_ids | `_invalid_completed_ids` | 类级别名（D7） |
| _read_init_tools | `_read_init_tools` | 类级别名（D7） |
| parse_api_error_status | `parse_api_error_status` | 类级别名（D7） |
| classify_switch_error | `classify_switch_error` | 类级别名（D7） |
| classify_transient_error | `classify_transient_error` | 类级别名（D7） |
| _summarize_snapshot | `_summarize_snapshot` | 类级别名（D7） |
| _parse_verdict_json | `_parse_verdict_json` | 类级别名（D7） |
| _resumable_session_id | `_resumable_session_id` | 类级别名（D7） |
| _extract_session_id | `_extract_session_id` | 类级别名（D7） |
| _extract_usage_info | `_extract_usage_info` | 类级别名（D7） |

### stdlib 调用形态（保留为显式真方法，不计入收敛）

| 方法名 | 目标 | 依据 |
|---|---|---|
| `_normalize_run_id` | `sub` | 向 stdlib 调用，非子模块转发（spec 判据排除） |
| `_now` | `monotonic` | 向 stdlib 调用，非子模块转发（spec 判据排除） |

## 排除项（非转发）

- 三类的 `@property` 局部状态 getter（body 是 `return self._x` 或局部计算，无子模块调用），不构成双份签名，排除：
  - PMEngine：`_last_scenario_diff`/`_last_interaction_contract`/`_queue_lock`/`_run_queue`/`_active_runs`/`_active_priorities`/`_active_priority_counts`/`_backoff_timers`/`_recovery_watch`/`_signal_fingerprints` 及全部子对象惰性 property 本体（`_verification` 等）
  - AgentRunner：`provider_circuits`/`_daily_provider_attempts`/`_daily_provider_warned`/`_daily_reset_date`/`_v2_servers`/`_v2_used_ports`/`_v2_run_seq`/`_extension_baselines` 及全部惰性 property 本体（`_liveness` 等）
  - VerificationPipeline：无 property 转发

## 类直调审计（Task 1.2）

全仓（`tests/` + `core/` + `scripts/` + `fenixd.py`，排除 `.history/` / `.fenix/verify-serving/` / 其它 worktree）以 `Cls.<转发名>(...)` 正则扫描，命中如下。收敛后 MUST 全部仍可解析（D7 类级别名 / stdlib 保留真方法）：

| 类直调点 | 位置 | 收敛方式 |
|---|---|---|
| `VerificationPipeline._normalize_fail_signature(text)` | 生产：`core/pm_engine/engine.py` `PMEngine._normalize_fail_signature` 内 | D7 类级别名（pipeline 侧）→ engine 侧链式别名 |
| `AgentRunner._entry_is_tool_result(entry)` | 生产：`core/agent_runner/runner.py` 延迟样本采集路径 | D7 类级别名 |
| `VerificationPipeline._replan_errors_unconsumed(...)` | `tests/test_frozen_scenario_reservoir.py`（6 处） | D7 类级别名 |
| `VerificationPipeline._extract_replan_error_items(...)` | `tests/test_frozen_scenario_reservoir.py`（3 处） | D7 类级别名 |
| `AgentRunner._normalize_run_id(...)` | `tests/test_run_cancel.py` | 保留真方法（stdlib 调用形态） |
| `AgentRunner.parse_api_error_status(...)` | `tests/test_provider_circuit.py` | D7 类级别名 |
| `AgentRunner.classify_switch_error(...)` | `tests/test_provider_failover.py` / `tests/test_provider_circuit.py` | D7 类级别名 |
| `PMEngine._is_fix_spec(...)` | `tests/test_repair_lane_dedup.py` | D7 类级别名 |

> 其余 `Cls.<名>(...)` 命中均为真静态方法（非转发）或 `__new__` 部分构造，不涉及收敛：`AgentRunner._parse_event_timestamp` / `_denoise_stderr` / `_parse_transient_backoff_schedule` / `_signal_kill_label`（真静态方法，函数体非单条转发 return）、`PMEngine._frozen_state`（真静态方法）、`AgentRunner.__new__`（构造协议）。

## 真方法保留审计（Task 1.3）

| 名字 | 形态 | 处置 |
|---|---|---|
| `AgentRunner._now` | `return time.monotonic()`（stdlib 调用，`@staticmethod` 无） | 保留显式真方法，MUST NOT 纳入注册表 |
| `AgentRunner._normalize_run_id` | `return re.sub(...)`（stdlib 调用，`@staticmethod`） | 保留显式真方法，MUST NOT 纳入注册表 |
| `AgentRunner._denoise_stderr` / `_parse_event_timestamp` / `_parse_transient_backoff_schedule` / `_signal_kill_label` | 真静态方法（函数体多行，非单条转发 return） | 保留显式类属性，MUST NOT 转别名 |
| `PMEngine._frozen_state` | 真静态方法（函数体多行） | 保留显式类属性，MUST NOT 转别名 |