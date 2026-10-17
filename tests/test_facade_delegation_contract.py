"""facade-delegation 契约测试（refactor-facade-delegation design D4 / tasks 1.4）。

锁定门面转发层收敛后的组织契约（spec「facade-forwarder-contract」各 Scenario）：

1. 三个宿主类的注册表内每个名字逐名可解析，且解析结果与子模块实现是同一函数；
2. 未知名 `raise AttributeError`、`hasattr` 语义正确、dunder 名不转发；
3. `patch.object(facade, X)` 与 `patch.object(facade.<子对象>, X)` 两种缝隙均生效；
4. 静态式组（D7 类级别名）：`Cls.<名> is <目标函数>`、实例路径调用不注入 `self`；
5. 类直调组（design D1 约束 4）：收敛后类直调点返回结果与收敛前一致；
6. 覆盖性硬门：枚举「原转发方法名全集」逐名断言可解析（facade-inventory.md 为权威清单）。
"""

import functools
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import core.agent_runner.runner as runner_mod
import core.pm_engine.engine as engine_mod
import core.pm_engine.verification.pipeline as pipeline_mod
from core.agent_runner import AgentRunner
from core.pm_engine import PMEngine
from core.pm_engine.dispatch import Dispatcher
from core.pm_engine.family import FamilyGovernor
from core.pm_engine.budget import ImplBudget
from core.pm_engine.recovery import RecoveryWatch
from core.pm_engine.reporting import ReportBuilder
from core.pm_engine.spec_integrity import SpecIntegrityGate
from core.pm_engine.verification import VerificationPipeline
from core.agent_runner.liveness import LivenessSupervisor
from core.agent_runner.provider_circuit import ProviderCircuit
from core.agent_runner.prompt_builder import PromptBuilder
from core.agent_runner.v2_server import V2ServerManager
from core.agent_runner.token_budget import TokenAccountant
from core.agent_runner.session import SessionTracker

# ── 原转发方法名全集（阶段 0 AST 清点，facade-inventory.md 权威对应）──

# VerificationPipeline 实例组：{方法名: 模块级函数名}（85 个）
PIPELINE_INST_TARGETS = {
        "_read_verify_report": "_read_verify_report",
        "_ensure_verification_report": "_ensure_verification_report",
        "_check_verification_gate": "_check_verification_gate",
        "_verifier_result_is_stale": "_verifier_result_is_stale",
        "_read_verifier_result": "_read_verifier_result",
        "_read_planner_result": "_read_planner_result",
        "_read_verdict": "_read_verdict",
        "_branch_commit_count": "_branch_commit_count",
        "_implementation_branch_has_commits": "_implementation_branch_has_commits",
        "_implementer_zero_change": "_implementer_zero_change",
        "_deliverable_gate_missing": "_deliverable_gate_missing",
        "_tasks_md_relint_from_branch": "_tasks_md_relint_from_branch",
        "_tasks_md_relint_from_worktree": "_tasks_md_relint_from_worktree",
        "_disputed_deliverables": "_disputed_deliverables",
        "_verifier_error_is_infra": "_verifier_error_is_infra",
        "enrich_failure_class": "enrich_failure_class",
        "_record_infra_failure": "_record_infra_failure",
        "_detect_uniform_verify_failure": "_detect_uniform_verify_failure",
        "_fail_history_path": "_fail_history_path",
        "_read_fail_history": "_read_fail_history",
        "_append_fail_history": "_append_fail_history",
        "_clear_fail_history": "_clear_fail_history",
        "_scenario_classification_distribution": "_scenario_classification_distribution",
        "_failed_scenario_ids": "_failed_scenario_ids",
        "_apply_scenario_freeze": "_apply_scenario_freeze",
        "_apply_interaction_contract": "_apply_interaction_contract",
        "_render_scenario_change_section_to_report": "_render_scenario_change_section_to_report",
        "_write_verify_contract_missing": "_write_verify_contract_missing",
        "_run_scenario_static_check": "_run_scenario_static_check",
        "_run_contract_static_check": "_run_contract_static_check",
        "_ensure_serving_worktree": "_ensure_serving_worktree",
        "_serve_static_in_main": "_serve_static_in_main",
        "_serve_static_in_worktree": "_serve_static_in_worktree",
        "_serve_command_in_worktree": "_serve_command_in_worktree",
        "_serve_command_in_main": "_serve_command_in_main",
        "_finalize_static": "_finalize_static",
        "_remove_serving_worktree": "_remove_serving_worktree",
        "_register_serving_instance": "_register_serving_instance",
        "_unregister_serving_instance": "_unregister_serving_instance",
        "_evict_spec_serving": "_evict_spec_serving",
        "_current_instance_base_url": "_current_instance_base_url",
        "_ensure_app_reachable": "_ensure_app_reachable",
        "_open_boot_log": "_open_boot_log",
        "_read_boot_log_tail": "_read_boot_log_tail",
        "_rewrite_scenario_port": "_rewrite_scenario_port",
        "_serving_port_for_spec": "_serving_port_for_spec",
        "_current_verify_round": "_current_verify_round",
        "_handle_env_blocked_inconclusive": "_handle_env_blocked_inconclusive",
        "_write_inconclusive_loop_signal": "_write_inconclusive_loop_signal",
        "_env_whitewash_gate": "_env_whitewash_gate",
        "_escalate_env_blocked": "_escalate_env_blocked",
        "_update_warning_streaks": "_update_warning_streaks",
        "_warning_stale_triage_alert": "_warning_stale_triage_alert",
        "_scenario_defect_reroute_gate": "_scenario_defect_reroute_gate",
        "_escalate_scenario_defect_reroute": "_escalate_scenario_defect_reroute",
        "_handle_judge_env_declared": "_handle_judge_env_declared",
        "_judge_bugs_declare_env": "_judge_bugs_declare_env",
        "_speculative_bug_found_gate": "_speculative_bug_found_gate",
        "_run_legacy_verification": "_run_legacy_verification",
        "_verify_verdict_evidence": "_verify_verdict_evidence",
        "_verdict_violations_evidence": "_verdict_violations_evidence",
        "_write_verdict_violations": "_write_verdict_violations",
        "_clear_verdict_violations": "_clear_verdict_violations",
        "_verdict_violations_path": "_verdict_violations_path",
        "_resynthesis_directive_path": "_resynthesis_directive_path",
        "_read_resynthesis_directive": "_read_resynthesis_directive",
        "_clear_resynthesis_directive": "_clear_resynthesis_directive",
        "_resynthesis_directive_scenarios": "_resynthesis_directive_scenarios",
        "_write_resynthesis_directive": "_write_resynthesis_directive",
        "_escalate_dedup_resynthesis": "_escalate_dedup_resynthesis",
        "_handle_attr_dedup_rejection": "_handle_attr_dedup_rejection",
        "_handle_scenario_requeue": "_handle_scenario_requeue",
        "_clear_requeue_manifest": "_clear_requeue_manifest",
        "_record_verdict_adoption": "_record_verdict_adoption",
        "_persist_verdict_cache": "_persist_verdict_cache",
        "_verified_verdict_persisted": "_verified_verdict_persisted",
        "_verified_gate_refuses": "_verified_gate_refuses",
        "_judge_dispatch_gate": "_judge_dispatch_gate",
        "_judge_hard_cap_freeze": "_judge_hard_cap_freeze",
        "_judge_rerun_count": "_judge_rerun_count",
        "_all_green_fast_path": "_all_green_fast_path",
        "_last_planner_cost_usd": "_last_planner_cost_usd",
        "_last_planner_run_cost": "_last_planner_run_cost",
        "_write_degrade_context": "_write_degrade_context",
        "_clear_degrade_context": "_clear_degrade_context",
    }

# VerificationPipeline 静态组：{方法名: 模块级函数名}（4 个，D7 类级别名；
# e3841db4c1c7 删除死函数 _load_frozen_scenarios 后由 5 减至 4）
PIPELINE_STATIC_TARGETS = {
    "_extract_replan_error_items": "_bg_extract_replan_error_items",
    "_replan_errors_unconsumed": "_bg_replan_errors_unconsumed",
    "_normalize_fail_signature": "_normalize_fail_signature",
    "_port_responds": "_port_responds"
}

# AgentRunner 实例组：{方法名: 目标}（52 个；"sub.method"=子对象委托，"name"=self 首参模块函数）
RUNNER_INST_TARGETS = {
        "run_administrator": "run_administrator",
        "run_self_review": "run_self_review",
        "run_evolution": "run_evolution",
        "_get_admin_model": "_get_admin_model",
        "_build_prompt": "_prompt_builder._build_prompt",
        "_check_agent_result_artifact": "_check_agent_result_artifact",
        "_check_impl_result_artifact": "_check_impl_result_artifact",
        "_check_success_completion": "_check_success_completion",
        "_check_partial_consistency": "_check_partial_consistency",
        "_check_taskupdate_crosscheck": "_check_taskupdate_crosscheck",
        "_build_legacy_section": "_prompt_builder._build_legacy_section",
        "_legacy_dirty_snapshot": "_prompt_builder._legacy_dirty_snapshot",
        "_scenario_freeze_section": "_prompt_builder._scenario_freeze_section",
        "_interaction_contract_section": "_prompt_builder._interaction_contract_section",
        "_triage_recheck_section": "_prompt_builder._triage_recheck_section",
        "_verdict_rejection_section": "_prompt_builder._verdict_rejection_section",
        "_circuit_state": "_provider_circuit._circuit_state",
        "is_circuit_open": "_provider_circuit.is_circuit_open",
        "is_switch_cooldown": "_provider_circuit.is_switch_cooldown",
        "_record_switch_cooldown": "_provider_circuit._record_switch_cooldown",
        "_write_provider_marker": "_provider_circuit._write_provider_marker",
        "_record_daily_provider_attempt": "_provider_circuit._record_daily_provider_attempt",
        "_circuit_open_error": "_provider_circuit._circuit_open_error",
        "_record_provider_4xx": "_provider_circuit._record_provider_4xx",
        "_record_provider_probe": "_provider_circuit._record_provider_probe",
        "record_transient_break": "_provider_circuit.record_transient_error",
        "is_global_transient_break_active": "_provider_circuit.is_global_transient_break",
        "is_signal_kill_cooldown": "_provider_circuit.is_signal_kill_cooldown",
        "signal_kill_cooldown_until": "_provider_circuit.signal_kill_cooldown_until",
        "_signal_kill_counts": "_provider_circuit.signal_kill_counts",
        "_record_signal_kill": "_provider_circuit.record_signal_kill",
        "_accumulate_token_usage": "_token_accountant._accumulate_token_usage",
        "_check_token_budget": "_token_accountant._check_token_budget",
        "_send_token_alert": "_token_accountant._send_token_alert",
        "_record_verify_progress_tokens": "_token_accountant._record_verify_progress_tokens",
        "_v2_ensure_state": "_v2_server._v2_ensure_state",
        "_v2_launch_for_worktree": "_v2_server._v2_launch_for_worktree",
        "_v2_inject_env": "_v2_server._v2_inject_env",
        "_v2_stop_for_worktree": "_v2_server._v2_stop_for_worktree",
        "_v2_stop_all": "_v2_server._v2_stop_all",
        "has_live_attempt": "_liveness.has_live_attempt",
        "sweep_dangling_runs": "_liveness.sweep_dangling_runs",
        "_pgrep_live_attempt": "_liveness._pgrep_live_attempt",
        "_stream_recent": "_liveness._stream_recent",
        "note_run_extension": "_liveness.note_run_extension",
        "get_extension_baseline": "_liveness.get_extension_baseline",
        "_liveness_snapshot": "_liveness._liveness_snapshot",
        "_judge_liveness": "_liveness._judge_liveness",
        "_supervision_settings": "_liveness._supervision_settings",
        "_supervision_judge_timeout": "_liveness._supervision_judge_timeout",
        "_supervision_deadline_action": "_liveness._supervision_deadline_action",
        "wait_for_running_agents": "_liveness.wait_for_running_agents",
    }

# AgentRunner 静态组：{方法名: (解析方式, 全限定目标)}（15 个：D7 类级别名 12 + 目标非 self 首参模块函数 3）
RUNNER_STATIC_TARGETS = {
    "_entry_is_tool_result": [
        "module",
        "_entry_is_tool_result"
    ],
    "_format_gap_list": [
        "module",
        "_format_gap_list"
    ],
    "_invalid_completed_ids": [
        "module",
        "_invalid_completed_ids"
    ],
    "_read_init_tools": [
        "module",
        "_read_init_tools"
    ],
    "parse_api_error_status": [
        "class",
        "ProviderCircuit.parse_api_error_status"
    ],
    "classify_switch_error": [
        "class",
        "ProviderCircuit.classify_switch_error"
    ],
    "classify_transient_error": [
        "class",
        "ProviderCircuit.classify_transient_error"
    ],
    "_summarize_snapshot": [
        "class",
        "LivenessSupervisor._summarize_snapshot"
    ],
    "_parse_verdict_json": [
        "class",
        "LivenessSupervisor._parse_verdict_json"
    ],
    "_resumable_session_id": [
        "class",
        "SessionTracker._resumable_session_id"
    ],
    "_extract_session_id": [
        "class",
        "SessionTracker._extract_session_id"
    ],
    "_extract_usage_info": [
        "class",
        "SessionTracker._extract_usage_info"
    ],
    # 目标不以 self 为首参（partial 会多注 self → MUST 类级别名，design D7 精神）
    "_read_admin_disposition": [
        "module",
        "_read_admin_disposition"
    ],
    "_read_self_review_out": [
        "module",
        "_read_self_review_out"
    ],
    "_check_artifact_json_file": [
        "module",
        "_check_artifact_json_file"
    ]
}

# PMEngine 实例组：{方法名: 目标}（100 个；"sub.method"=子对象委托）
ENGINE_INST_TARGETS = {
        "_resolve_fix_spec_name": "_family._resolve_fix_spec_name",
        "_ensure_fix_spec_files": "_family._ensure_fix_spec_files",
        "_family_width": "_family._family_width",
        "_consume_family_waiver": "_family._consume_family_waiver",
        "_family_gate_blocked": "_family._family_gate_blocked",
        "_same_root_siblings": "_family._same_root_siblings",
        "_sibling_repair_active": "_family._sibling_repair_active",
        "_sibling_has_live_agent": "_family._sibling_has_live_agent",
        "_has_non_terminal_child_fix": "_family._has_non_terminal_child_fix",
        "_signal_family_explosion": "_family._signal_family_explosion",
        "_do_spec_bug_found": "_family._do_spec_bug_found",
        "_do_legacy_fix_spec_bug_found": "_family._do_legacy_fix_spec_bug_found",
        "_inject_verify_fix_task": "_family._inject_verify_fix_task",
        "_send_human_escalation_alert": "_family._send_human_escalation_alert",
        "_impl_run_budget": "_budget._impl_run_budget",
        "_increment_impl_run_budget_used": "_budget._increment_impl_run_budget_used",
        "_budget_exempt_alert_threshold": "_budget._budget_exempt_alert_threshold",
        "_exempt_dead_run_budget": "_budget._exempt_dead_run_budget",
        "_exempt_infra_run_budget": "_budget._exempt_infra_run_budget",
        "_alert_budget_exempt_loop": "_budget._alert_budget_exempt_loop",
        "_reconcile_impl_budget": "_budget._reconcile_impl_budget",
        "_count_normal_completed_impl_runs": "_budget._count_normal_completed_impl_runs",
        "_impl_run_budget_used": "_budget._impl_run_budget_used",
        "_check_impl_budget_exhausted": "_budget._check_impl_budget_exhausted",
        "_check_spec_content_missing": "_spec_integrity.check_spec_content_missing",
        "_read_verify_report": "_verification._read_verify_report",
        "_handle_env_blocked_inconclusive": "_verification._handle_env_blocked_inconclusive",
        "_ensure_app_reachable": "_verification._ensure_app_reachable",
        "_rewrite_scenario_port": "_verification._rewrite_scenario_port",
        "_current_verify_round": "_verification._current_verify_round",
        "_apply_scenario_freeze": "_verification._apply_scenario_freeze",
        "_run_scenario_static_check": "_verification._run_scenario_static_check",
        "_scenario_defect_reroute_gate": "_verification._scenario_defect_reroute_gate",
        "_apply_interaction_contract": "_verification._apply_interaction_contract",
        "_render_scenario_change_section_to_report": "_verification._render_scenario_change_section_to_report",
        "_run_three_stage_verification": "_verification._run_three_stage_verification",
        "_verifier_error_is_infra": "_verification._verifier_error_is_infra",
        "enrich_failure_class": "_verification.enrich_failure_class",
        "_verifier_result_is_stale": "_verification._verifier_result_is_stale",
        "_implementer_zero_change": "_verification._implementer_zero_change",
        "_implementation_branch_has_commits": "_verification._implementation_branch_has_commits",
        "_deliverable_gate_missing": "_verification._deliverable_gate_missing",
        "_tasks_md_relint_from_branch": "_verification._tasks_md_relint_from_branch",
        "_tasks_md_relint_from_worktree": "_verification._tasks_md_relint_from_worktree",
        "_disputed_deliverables": "_verification._disputed_deliverables",
        "_adjudicate_deliverable_missing": "_dispatcher._adjudicate_deliverable_missing",
        "_preclassify_orphan": "_dispatcher._preclassify_orphan",
        "_detect_uniform_verify_failure": "_verification._detect_uniform_verify_failure",
        "_run_legacy_verification": "_verification._run_legacy_verification",
        "_verify_verdict_evidence": "_verification._verify_verdict_evidence",
        "_speculative_bug_found_gate": "_verification._speculative_bug_found_gate",
        "_env_whitewash_gate": "_verification._env_whitewash_gate",
        "_escalate_env_blocked": "_verification._escalate_env_blocked",
        "_record_infra_failure": "_verification._record_infra_failure",
        "_update_warning_streaks": "_verification._update_warning_streaks",
        "_warning_stale_triage_alert": "_verification._warning_stale_triage_alert",
        "_ensure_verification_report": "_verification._ensure_verification_report",
        "_check_verification_gate": "_verification._check_verification_gate",
        "_read_verifier_result": "_verification._read_verifier_result",
        "_read_planner_result": "_verification._read_planner_result",
        "_read_verdict": "_verification._read_verdict",
        "_judge_bugs_declare_env": "_verification._judge_bugs_declare_env",
        "_handle_judge_env_declared": "_verification._handle_judge_env_declared",
        "_verdict_violations_path": "_verification._verdict_violations_path",
        "_write_verdict_violations": "_verification._write_verdict_violations",
        "_clear_verdict_violations": "_verification._clear_verdict_violations",
        "_read_fail_history": "_verification._read_fail_history",
        "_append_fail_history": "_verification._append_fail_history",
        "_clear_fail_history": "_verification._clear_fail_history",
        "_failed_scenario_ids": "_verification._failed_scenario_ids",
        "_dispatch_backoff_schedule": "_dispatcher._dispatch_backoff_schedule",
        "_handle_dispatch_lock_conflict": "_dispatcher._handle_dispatch_lock_conflict",
        "_schedule_backoff_retry": "_dispatcher._schedule_backoff_retry",
        "_get_spec_priority": "_dispatcher._get_spec_priority",
        "_enqueue": "_dispatcher._enqueue",
        "_enqueue_front": "_dispatcher._enqueue_front",
        "_aging_bonus": "_dispatcher._aging_bonus",
        "_effective_priority": "_dispatcher._effective_priority",
        "_process_queue": "_dispatcher._process_queue",
        "_run_agent_worker": "_dispatcher._run_agent_worker",
        "_rollback_failed_dispatch": "_dispatcher._rollback_failed_dispatch",
        "_report_stash_pop_conflict": "_dispatcher._report_stash_pop_conflict",
        "_run_fast_track_worker": "_dispatcher._run_fast_track_worker",
        "_should_enter_repair": "_dispatcher._should_enter_repair",
        "_dispatch_repair_lane": "_dispatcher._dispatch_repair_lane",
        "_claim_repair_site": "_dispatcher._claim_repair_site",
        "_run_repair_worker": "_dispatcher._run_repair_worker",
        "_check_repair_commit_facts": "_dispatcher._check_repair_commit_facts",
        "_handle_remerge_failure": "_dispatcher._handle_remerge_failure",
        "_fallback_after_repair": "_dispatcher._fallback_after_repair",
        "_recovery_watch_path": "_recovery._recovery_watch_path",
        "_load_recovery_watch": "_recovery._load_recovery_watch",
        "_save_recovery_watch": "_recovery._save_recovery_watch",
        "register_recovery_watch": "_recovery.register_recovery_watch",
        "check_recovery_watch": "_recovery.check_recovery_watch",
        "_signal_dispatch_stalled": "_recovery._signal_dispatch_stalled",
        "_clear_dispatch_conflict": "_recovery._clear_dispatch_conflict",
        "generate_report": "_reporting.generate_report",
        "generate_daily_report": "_reporting.generate_daily_report",
        "get_pushable_specs": "_reporting.get_pushable_specs",
    }

# PMEngine 静态组：{方法名: 全限定目标}（10 个，D7 类级别名）
ENGINE_STATIC_TARGETS = {
    "_fix_prefix_depth": "FamilyGovernor._fix_prefix_depth",
    "_fix_strip_all": "FamilyGovernor._fix_strip_all",
    "_is_fix_spec": "FamilyGovernor._is_fix_spec",
    "_same_root": "FamilyGovernor._same_root",
    "_run_file_died": "ImplBudget._run_file_died",
    "_normalize_fail_signature": "VerificationPipeline._normalize_fail_signature",
    "_dispatch_backoffed": "Dispatcher._dispatch_backoffed",
    "_spec_fingerprint": "RecoveryWatch._spec_fingerprint",
    "_is_push_backoffed": "ReportBuilder._is_push_backoffed",
    "_get_push_retry_count": "ReportBuilder._get_push_retry_count"
}

RUNNER_SUBOBJECT_CLASS = {
    "_liveness": "LivenessSupervisor",
    "_provider_circuit": "ProviderCircuit",
    "_prompt_builder": "PromptBuilder",
    "_v2_server": "V2ServerManager",
    "_token_accountant": "TokenAccountant"
}
ENGINE_SUBOBJECT_CLASS = {
    "_verification": "VerificationPipeline",
    "_dispatcher": "Dispatcher",
    "_family": "FamilyGovernor",
    "_budget": "ImplBudget",
    "_recovery": "RecoveryWatch",
    "_reporting": "ReportBuilder",
    "_spec_integrity": "SpecIntegrityGate"
}

STDLIB_KEEP = ["_now", "_normalize_run_id"]  # AgentRunner stdlib 调用形态，MUST NOT 转注册表
RUNNER_WRAPPERS = ["_salvage_spec_review_result"]  # 薄包装真方法（非纯转发，引用 self.project_root + 常量），保留显式方法


def _resolve_target(module, target: str):
    """把注册表 target 解析为实际函数对象。

    注意：branch_guard 的模块级函数以 `@staticmethod` 装饰（模块级 staticmethod
    会把函数包成 staticmethod 对象），对这类目标须取 `__func__` 还原裸函数，
    才能与类级别名（`staticmethod(目标.__func__)`）做 `is` 同一对象断言。
    """
    if "." in target:
        cls_name, meth = target.split(".", 1)
        cls = getattr(module, cls_name)
        return getattr(cls, meth)
    obj = getattr(module, target)
    if isinstance(obj, staticmethod):
        return obj.__func__
    return obj


def _underlying(attr):
    """取可调用对象的底层函数：partial → .func；bound method → .__func__。"""
    if isinstance(attr, functools.partial):
        return attr.func
    return getattr(attr, "__func__", attr)


def _make_pipeline():
    """部分构造 pipeline（__new__ 绕过 __init__，tests 既有模式）。"""
    pipe = VerificationPipeline.__new__(VerificationPipeline)
    pipe._pm = SimpleNamespace(project_root=Path(tempfile.mkdtemp()),
                               logger=MagicMock(), state_machine=MagicMock())
    return pipe


def _make_runner():
    """部分构造 runner（__new__ + 最小属性，tests 既有模式）。"""
    r = AgentRunner.__new__(AgentRunner)
    r.config = {}
    r.project_root = Path(tempfile.mkdtemp())
    r.logger = MagicMock()
    r.state_machine = None
    r.worktree_manager = None
    r._running_agents = {}
    r._daily_run_count = 0
    return r


def _make_engine():
    """部分构造 engine（__new__ + 最小属性）。"""
    e = PMEngine.__new__(PMEngine)
    e.project_root = Path(tempfile.mkdtemp())
    e.logger = MagicMock()
    e.state_machine = MagicMock()  # PipelineContext.from_pm 需要（子对象惰性构造）
    return e


class TestPipelineRegistry(unittest.TestCase):
    """VerificationPipeline 实例组：逐名可解析且 is 同一模块函数。"""

    def test_inst_names_resolve_to_module_functions(self):
        pipe = _make_pipeline()
        for name, target in PIPELINE_INST_TARGETS.items():
            with self.subTest(name=name):
                attr = getattr(pipe, name)
                self.assertTrue(callable(attr), f"{name} 不可调用")
                self.assertIs(_underlying(attr), _resolve_target(pipeline_mod, target),
                              f"{name} 底层函数不是 {target}")

    def test_static_names_are_class_attrs_not_partial(self):
        """5 个静态式 MUST 是类级别名（staticmethod），实例路径不注入 self。"""
        pipe = _make_pipeline()
        for name, target in PIPELINE_STATIC_TARGETS.items():
            with self.subTest(name=name):
                self.assertIn(name, vars(VerificationPipeline),
                              f"{name} 不是类属性")
                class_attr = getattr(VerificationPipeline, name)
                target_func = _resolve_target(pipeline_mod, target)
                self.assertIs(class_attr, target_func,
                              f"Cls.{name} 不是目标函数 {target}")
                # 实例路径解析到同一对象（staticmethod 描述符），不得经 partial
                inst_attr = getattr(pipe, name)
                self.assertIs(_underlying(inst_attr), target_func,
                              f"self.{name} 底层不是 {target}")
                self.assertNotIsInstance(inst_attr, functools.partial,
                                      f"self.{name} 不得是 partial（会多注入 self）")

    def test_instance_call_does_not_inject_self(self):
        """pipeline.py 内实例路径调用（如 self._extract_replan_error_items(env_error)）实参不被追加 self。"""
        pipe = _make_pipeline()
        items = pipe._extract_replan_error_items("line 1\nline 2")
        self.assertIsInstance(items, list)

    def test_class_direct_calls(self):
        """D1 约束 4 实测类直调点：VerificationPipeline._normalize_fail_signature 等。"""
        # 与 infra_classify._normalize_fail_signature 语义一致：数字→N、去引号、折叠空白
        self.assertEqual(VerificationPipeline._normalize_fail_signature("err 123: 'x'\n  y"),
                         "err N: x y")
        prev = ["x"]
        self.assertTrue(VerificationPipeline._replan_errors_unconsumed(prev, ["x", "y"]))
        self.assertFalse(VerificationPipeline._replan_errors_unconsumed([], []))
        self.assertEqual(VerificationPipeline._extract_replan_error_items(""), [])

    def test_unknown_and_dunder(self):
        pipe = _make_pipeline()
        with self.assertRaises(AttributeError):
            pipe.definitely_not_a_method
        with self.assertRaises(AttributeError):
            pipe.__custom_dunder_x__
        self.assertFalse(hasattr(pipe, "definitely_not_a_method"))

    def test_patch_object_gap(self):
        """patch.object(facade, X) 缝隙：mock 写实例 __dict__ 遮蔽 __getattr__，退出恢复。"""
        pipe = _make_pipeline()
        with patch.object(pipe, "_read_verify_report", return_value={"ok": 1}) as m:
            self.assertEqual(pipe._read_verify_report("s"), {"ok": 1})
            self.assertIs(pipe._read_verify_report, m)
        # 退出后恢复转发
        self.assertTrue(callable(pipe._read_verify_report))


class TestRunnerRegistry(unittest.TestCase):
    """AgentRunner 实例组：逐名可解析且 is 同一子对象方法 / 模块函数。"""

    def test_inst_names_resolve(self):
        r = _make_runner()
        for name, target in RUNNER_INST_TARGETS.items():
            with self.subTest(name=name):
                attr = getattr(r, name)
                self.assertTrue(callable(attr), f"{name} 不可调用")
                if "." in target:
                    sub, meth = target.split(".", 1)
                    cls = getattr(runner_mod, RUNNER_SUBOBJECT_CLASS[sub])
                    self.assertIs(_underlying(attr), getattr(cls, meth),
                                  f"{name} 底层不是 {target}")
                else:
                    self.assertIs(_underlying(attr), getattr(runner_mod, target),
                                  f"{name} 底层不是模块函数 {target}")

    def test_static_names_are_class_attrs(self):
        r = _make_runner()
        for name, (how, target) in RUNNER_STATIC_TARGETS.items():
            with self.subTest(name=name):
                self.assertIn(name, vars(AgentRunner), f"{name} 不是类属性")
                class_attr = getattr(AgentRunner, name)
                if how == "module":
                    target_func = getattr(runner_mod, target)
                else:
                    cls_name, meth = target.split(".", 1)
                    target_func = getattr(getattr(runner_mod, cls_name), meth)
                self.assertIs(class_attr, target_func,
                              f"Cls.{name} 不是目标函数 {target}")
                inst_attr = getattr(r, name)
                self.assertIs(_underlying(inst_attr), target_func,
                              f"self.{name} 底层不是 {target}")
                self.assertNotIsInstance(inst_attr, functools.partial,
                                      f"self.{name} 不得是 partial")

    def test_stdlib_methods_kept(self):
        """_now / _normalize_run_id 保留为显式真方法（类属性），MUST NOT 转注册表。"""
        for name in STDLIB_KEEP:
            with self.subTest(name=name):
                self.assertIn(name, vars(AgentRunner), f"{name} 应保留为显式类方法")
                self.assertIn("def " + name, inspect.getsource(getattr(AgentRunner, name)),
                              f"{name} 应是源码定义的函数而非别名")

    def test_real_static_methods_kept(self):
        """真静态方法（非转发）保留：_denoise_stderr / _parse_event_timestamp 等。"""
        for name in ("_denoise_stderr", "_parse_event_timestamp",
                     "_parse_transient_backoff_schedule", "_signal_kill_label"):
            with self.subTest(name=name):
                self.assertIn(name, vars(AgentRunner))
                self.assertIn("def " + name, inspect.getsource(getattr(AgentRunner, name)))

    def test_wrappers_kept_as_real_methods(self):
        """薄包装真方法（非纯转发）保留为显式方法：_salvage_spec_review_result。"""
        for name in RUNNER_WRAPPERS:
            with self.subTest(name=name):
                self.assertIn(name, vars(AgentRunner))
                self.assertIn("def " + name, inspect.getsource(getattr(AgentRunner, name)))

    def test_class_direct_calls(self):
        """D1 约束 4 类直调点：parse_api_error_status / classify_switch_error / _entry_is_tool_result。"""
        self.assertEqual(AgentRunner.parse_api_error_status("HTTP 404"), 404)
        self.assertFalse(AgentRunner.classify_switch_error("HTTP 404"))
        self.assertIsInstance(AgentRunner._entry_is_tool_result({}), bool)

    def test_unknown_and_dunder(self):
        r = _make_runner()
        with self.assertRaises(AttributeError):
            r.definitely_not_a_method
        with self.assertRaises(AttributeError):
            r.__custom_dunder_x__
        self.assertFalse(hasattr(r, "definitely_not_a_method"))

    def test_patch_object_gap(self):
        r = _make_runner()
        with patch.object(r, "_build_prompt", return_value="x") as m:
            self.assertEqual(r._build_prompt({}), "x")
            self.assertIs(r._build_prompt, m)
        self.assertTrue(callable(r._build_prompt))

    def test_lazy_property_trigger(self):
        """惰性 property 经 __getattr__ 首访触发构造（部分构造实例安全）。"""
        r = _make_runner()
        _ = r._liveness  # 构造
        self.assertIn("_liveness_instance", r.__dict__)
        self.assertTrue(callable(r.has_live_attempt))


class TestEngineRegistry(unittest.TestCase):
    """PMEngine 实例组：逐名可解析且 is 同一子对象方法。"""

    def test_inst_names_resolve(self):
        e = _make_engine()
        for name, target in ENGINE_INST_TARGETS.items():
            with self.subTest(name=name):
                attr = getattr(e, name)
                self.assertTrue(callable(attr), f"{name} 不可调用")
                sub, meth = target.split(".", 1)
                # 子对象自身可能是门面（VerificationPipeline 已收敛为注册表委托，
                # 目标方法非类属性）；以「子对象实例访问同一方法名」比对底层函数，
                # 保证门面委托与直接子对象访问解析到同一实现。
                sub_obj = getattr(e, sub)
                self.assertIs(_underlying(attr), _underlying(getattr(sub_obj, meth)),
                              f"{name} 底层不是 {target}")

    def test_static_names_are_class_attrs(self):
        e = _make_engine()
        for name, target in ENGINE_STATIC_TARGETS.items():
            with self.subTest(name=name):
                self.assertIn(name, vars(PMEngine), f"{name} 不是类属性")
                cls_name, meth = target.split(".", 1)
                if cls_name == "VerificationPipeline":
                    target_func = getattr(VerificationPipeline, meth)
                else:
                    target_func = getattr(getattr(engine_mod, cls_name), meth)
                self.assertIs(getattr(PMEngine, name), target_func,
                              f"Cls.{name} 不是目标函数 {target}")
                inst_attr = getattr(e, name)
                self.assertIs(_underlying(inst_attr), target_func,
                              f"self.{name} 底层不是 {target}")
                self.assertNotIsInstance(inst_attr, functools.partial,
                                      f"self.{name} 不得是 partial")

    def test_class_direct_calls(self):
        """D1 约束 4 类直调点：PMEngine._is_fix_spec。"""
        self.assertTrue(PMEngine._is_fix_spec("fix-x"))
        self.assertFalse(PMEngine._is_fix_spec("my-spec"))

    def test_unknown_and_dunder(self):
        e = _make_engine()
        with self.assertRaises(AttributeError):
            e.definitely_not_a_method
        with self.assertRaises(AttributeError):
            e.__custom_dunder_x__
        self.assertFalse(hasattr(e, "definitely_not_a_method"))

    def test_patch_object_gap(self):
        e = _make_engine()
        with patch.object(e, "_enqueue", return_value=None) as m:
            self.assertIsNone(e._enqueue("s", "impl"))
            self.assertIs(e._enqueue, m)
        self.assertTrue(callable(e._enqueue))

    def test_patch_subobject_gap(self):
        """patch.object(facade.<子对象>, X) 缝隙（203 处子对象赋值正交兼容）。"""
        e = _make_engine()
        with patch.object(e._verification, "_read_verify_report", return_value={}) as m:
            self.assertEqual(e._verification._read_verify_report("s"), {})
            self.assertIs(e._verification._read_verify_report, m)


class TestCoverageHardGate(unittest.TestCase):
    """覆盖性硬门：枚举原转发方法名全集（收敛对象 267 名 + 2 stdlib 保留名），逐名可解析。"""

    def test_all_names_resolve(self):
        pipe = _make_pipeline()
        r = _make_runner()
        e = _make_engine()
        total = 0
        for name in list(PIPELINE_INST_TARGETS) + list(PIPELINE_STATIC_TARGETS):
            with self.subTest(where="pipeline", name=name):
                self.assertTrue(callable(getattr(pipe, name)))
                total += 1
        for name in (list(RUNNER_INST_TARGETS) + list(RUNNER_STATIC_TARGETS)
                     + STDLIB_KEEP + RUNNER_WRAPPERS):
            with self.subTest(where="runner", name=name):
                self.assertTrue(callable(getattr(r, name)))
                total += 1
        for name in list(ENGINE_INST_TARGETS) + list(ENGINE_STATIC_TARGETS):
            with self.subTest(where="engine", name=name):
                self.assertTrue(callable(getattr(e, name)))
                total += 1
        # 收敛对象 267 = 237 实例式 + 30 静态式；+2 stdlib 保留 + 1 薄包装真方法 = 270
        # （deliverable-dispute-orphan-preclassify：+1 实例式 _preclassify_orphan → 271）
        # （e3841db4c1c7：删除 _load_frozen_scenarios 静态转发 → 270）
        # （f355cfaf723f：删除 _family_waiver_set 实例转发——生产零调用，豁免位
        # 读取已收口进 _consume_family_waiver 锁内 → 269）
        self.assertEqual(total, 269, f"全集枚举数量错误: {total}")

    def test_counts_match_inventory(self):
        self.assertEqual(len(PIPELINE_INST_TARGETS), 85)
        self.assertEqual(len(PIPELINE_STATIC_TARGETS), 4)
        self.assertEqual(len(RUNNER_INST_TARGETS), 52)
        self.assertEqual(len(RUNNER_STATIC_TARGETS), 15)
        self.assertEqual(len(ENGINE_INST_TARGETS), 100)
        self.assertEqual(len(ENGINE_STATIC_TARGETS), 10)

    def test_hasattr_semantics(self):
        for obj in (_make_pipeline(), _make_runner(), _make_engine()):
            self.assertFalse(hasattr(obj, "definitely_not_a_method"))

    def test_subobject_assignment_gap(self):
        """203 处子对象赋值（engine._verification.X = Mock）正交兼容。"""
        e = _make_engine()
        stub = MagicMock(return_value={"mocked": True})
        e._verification._read_verify_report = stub
        self.assertEqual(e._read_verify_report("s"), {"mocked": True})

    def test_patch_object_facade_gap_all_three(self):
        """design D3 缝隙专项（tasks 5.2）：patch.object(facade, X) 三类全验证。

        mock 写实例 __dict__ 遮蔽 __getattr__；退出删属性即恢复转发。
        """
        # pipeline
        pipe = _make_pipeline()
        with patch.object(pipe, "_read_verify_report", return_value={"p": 1}) as m:
            self.assertEqual(pipe._read_verify_report("s"), {"p": 1})
            self.assertIs(pipe._read_verify_report, m)
        self.assertTrue(callable(pipe._read_verify_report))
        # runner
        r = _make_runner()
        with patch.object(r, "_build_prompt", return_value="x") as m:
            self.assertEqual(r._build_prompt({}), "x")
            self.assertIs(r._build_prompt, m)
        self.assertTrue(callable(r._build_prompt))
        # engine
        e = _make_engine()
        with patch.object(e, "_enqueue", return_value=None) as m:
            self.assertIsNone(e._enqueue("s", "impl"))
            self.assertIs(e._enqueue, m)
        self.assertTrue(callable(e._enqueue))

    def test_patch_subobject_gap(self):
        """patch.object(facade.<子对象>, X) 缝隙（子对象赋值 203 处同族）。"""
        e = _make_engine()
        with patch.object(e._verification, "_read_verify_report", return_value={}) as m:
            self.assertEqual(e._verification._read_verify_report("s"), {})
            self.assertIs(e._verification._read_verify_report, m)
        r = _make_runner()
        with patch.object(r._provider_circuit, "record_transient_error", return_value=True) as m:
            self.assertTrue(r._provider_circuit.record_transient_error("x", 1))
            self.assertIs(r._provider_circuit.record_transient_error, m)

    def test_now_monkeypatch_gap(self):
        """monkeypatch.setattr(runner, "_now", ...) 缝隙：_now 是真方法，可被实例替换。"""
        r = _make_runner()
        r._now = lambda: 42.0
        self.assertEqual(r._now(), 42.0)


if __name__ == "__main__":
    unittest.main()
