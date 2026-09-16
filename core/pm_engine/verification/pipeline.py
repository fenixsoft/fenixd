"""pipeline.py — VerificationPipeline 门面组装 + 三阶段验证主流程（refactor-verification-module D2/D4）。

本模块承载 VerificationPipeline 门面骨架与 `_run_three_stage_verification`
（1165 行大函数，**整体搬移不拆分**，内部逻辑不动）。全部职责组已按 D2 分组
表迁入独立子模块（report_gate / branch_guard / infra_classify / scenario_gate /
serving / judge_gate / escalation / legacy / verdict_evidence），本模块以
薄委托方法保留全部既有 `self.<方法名>` 调用形态。

SPEC 状态经门面回引 self._context.state_machine（design D3 规则 3）；本轮缓存态
_last_scenario_diff / _last_interaction_contract 随组件同迁（design D3 规则 1），
门面经 property 委托保持原路径可用。

"""

from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request

from core.serving_registry import ServingRegistry
from core.proc_utils import find_free_port

# judge-scenario-repair：judge 原地场景修复预算（上限重入轮数）。
# 场景文件自身缺陷（夹具未自建/步骤客观错误/依赖序缺失）由 judge 原地修复
# 后重执行，不再「env 伪失败→原样重验」空转；上限与阶段1 replan_left 对齐。
_SCENARIO_REPAIR_MAX_ROUNDS = 2

from core.pm_engine.verification.judge_gate import _MAX_JUDGE_RERUNS

# D9：`ensure_main_tree_deps` / `run_prepare_steps` / `load_verify_contract` /
# `rewrite_scenarios_origin` 不再在此模块顶层绑定——调用点经包命名空间
# （`import core.pm_engine.verification as _facade`）延迟解析，使
# `patch("core.pm_engine.verification.<name>")` 语义保持（见 __init__.py）。
from core.verify_contract import (
    CommandVerifyServer,
    entry_preflight_error,
    provision_worktree_node_modules,
    resolve_deps_mode,
    StaticVerifyServer,
)

# fix-verdict-read-failclosed D3：与 runner 产物硬门共用同一 status 白名单单一来源
# （prompt_builder 定义、两侧 import，避免双实现漂移）。
# fix-verdict-read-failclosed D3：planner_result_status_whitelist 随裁决读取
# 迁至 report_gate.py（verification/report_gate.py 消费）。
# fix-verdict-retry-misattribution D3：frozen 门 error 文案与 runner.py 派发门共用
# 同一导出常量（防文案改动使匹配失效），取消判定沿用 AgentRunResult.cancelled 结构化
# 字段（非字符串匹配）。
from core.agent_runner.runner import FROZEN_TERMINATED_ERROR_PREFIX

# add-blocked-reverify-lane D3：env 阻塞轮次计数清零点收敛后与 state_machine
# 共用同一字段常量（防字符串漂移；唯一清零点=verified 落定与 unfreeze_spec）。
from core.state_machine import (
    ENV_BLOCK_ROUNDS_FIELD,
    FREEZE_ERROR_PREFIX,
    INFRA_FAILURE_COUNT_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
    INFRA_REFUNDED_RUN_IDS_FIELD,
)

# refactor-verification-module 阶段3.3：infra 失败归因/历史/回拨组已迁 infra_classify.py，
# reclassify_infra_rounds（模块级函数）与类内方法以薄委托保留在门面（见类内同名方法）。
from core.pm_engine.verification.infra_classify import (
    RECLASSIFY_SIGNAL_TYPE,
    _append_fail_history,
    _clear_fail_history,
    _detect_uniform_verify_failure,
    _failed_scenario_ids,
    _fail_history_path,
    _normalize_fail_signature,
    _read_fail_history,
    _record_infra_failure,
    _scenario_classification_distribution,
    _verifier_error_is_infra,
    enrich_failure_class,
    reclassify_infra_rounds,
)

# refactor-verification-module 阶段3.4：场景冻结/交互契约/静态检查组已迁 scenario_gate.py，
# 7 个方法以薄委托保留在门面（见类内同名方法）。
from core.pm_engine.verification.scenario_gate import (
    _apply_interaction_contract,
    _apply_scenario_freeze,
    _load_frozen_scenarios,
    _render_scenario_change_section_to_report,
    _run_contract_static_check,
    _run_scenario_static_check,
    _write_verify_contract_missing,
)

# refactor-verification-module 阶段3.6：judge 派发门/重跑上限/降级上下文组已迁 judge_gate.py，
# 8 个方法与 _MAX_JUDGE_RERUNS 常量以薄委托保留在门面（见类内同名方法）。
from core.pm_engine.verification.judge_gate import (
    _MAX_JUDGE_RERUNS,
    _all_green_fast_path,
    _clear_degrade_context,
    _judge_dispatch_gate,
    _judge_hard_cap_freeze,
    _judge_rerun_count,
    _last_planner_cost_usd,
    _last_planner_run_cost,
    _write_degrade_context,
)

# refactor-verification-module 阶段3.5：serving 工作树/实例/端口组已迁 serving.py，
# 18 个方法以薄委托保留在门面（见类内同名方法）。
from core.pm_engine.verification.serving import (
    _current_instance_base_url,
    _current_verify_round,
    _ensure_app_reachable,
    _ensure_serving_worktree,
    _evict_spec_serving,
    _finalize_static,
    _open_boot_log,
    _port_responds,
    _read_boot_log_tail,
    _register_serving_instance,
    _remove_serving_worktree,
    _rewrite_scenario_port,
    _serve_command_in_main,
    _serve_command_in_worktree,
    _serve_static_in_main,
    _serve_static_in_worktree,
    _serving_port_for_spec,
    _unregister_serving_instance,
)

# refactor-verification-module 阶段3.7：escalation/legacy/verdict_evidence 三组已迁。
from core.pm_engine.verification.escalation import (
    _env_whitewash_gate,
    _escalate_env_blocked,
    _escalate_scenario_defect_reroute,
    _handle_env_blocked_inconclusive,
    _handle_judge_env_declared,
    _judge_bugs_declare_env,
    _scenario_defect_reroute_gate,
    _speculative_bug_found_gate,
    _update_warning_streaks,
    _warning_stale_triage_alert,
    _write_inconclusive_loop_signal,
)
from core.pm_engine.verification.legacy import _run_legacy_verification
from core.pm_engine.verification.verdict_evidence import (
    _clear_requeue_manifest,
    _clear_resynthesis_directive,
    _clear_verdict_violations,
    _escalate_dedup_resynthesis,
    _handle_attr_dedup_rejection,
    _handle_scenario_requeue,
    _persist_verdict_cache,
    _read_resynthesis_directive,
    _record_verdict_adoption,
    _resynthesis_directive_path,
    _resynthesis_directive_scenarios,
    _verified_gate_refuses,
    _verified_verdict_persisted,
    _verify_verdict_evidence,
    _verdict_violations_evidence,
    _verdict_violations_path,
    _write_resynthesis_directive,
    _write_verdict_violations,
)

# refactor-verification-module 阶段3：verification/ 子包已成立，
# core.pm_engine.verification.context 自然可解析。
from core.pm_engine.verification.context import PipelineContext

# refactor-verification-module 阶段3.1：裁决读取/报告闸门组已迁 report_gate.py，
# VerdictReadResult 与 7 个读取/闸门函数以薄委托方法保留在门面（见类内同名方法）。
from core.pm_engine.verification.report_gate import (
    VerdictReadResult,
    _check_verification_gate,
    _ensure_verification_report,
    _read_planner_result,
    _read_verdict,
    _read_verifier_result,
    _read_verify_report,
    _verifier_result_is_stale,
)

# refactor-verification-module 阶段3.2：分支门/交付物门组已迁 branch_guard.py，
# 模块级函数 re-export（被 engine.py / admin_monitor / test_pm_verification 消费）；
# 类内方法以薄委托保留在门面（见类内同名方法）。
from core.pm_engine.verification.branch_guard import (
    _branch_commit_count,
    _branch_merged_into_tree,
    _deliverable_gate_missing,
    _disputed_deliverables,
    _extract_replan_error_items as _bg_extract_replan_error_items,
    _implementation_branch_has_commits,
    _implementer_zero_change,
    _replan_errors_unconsumed as _bg_replan_errors_unconsumed,
    _tasks_md_relint_from_branch,
    _tasks_md_relint_from_worktree,
    resolve_env_blocked_reset_path,
)

# 常量归属 serving 组，此处 re-export
from core.pm_engine.verification.serving import (
    LEGACY_START_PROBE_ATTEMPTS,
    LEGACY_START_PROBE_INTERVAL_SECONDS,
    POST_READY_SETTLE_SECONDS,
)


class VerificationPipeline:
    """验证流水线组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm, context: "PipelineContext | None" = None):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）
        # refactor-verification-module D1：显式依赖注入。context 可选——
        # 缺省时由 pm 推导（保持既有 VerificationPipeline(pm) 位置调用可用，
        # 任务 1.8 构造签名兼容基线）。注入后经 context 访问外部依赖，
        # MUST NOT 再直接回引 self._pm.<private>。
        self._context = context if context is not None else PipelineContext.from_pm(pm)

    def __getattr__(self, name: str):
        """懒惰兜底：既有测试以 `VerificationPipeline.__new__` 部分构造（只设
        `_pm`，绕过 `__init__`），首次访问 `_context` 时由 `_pm` 推导并缓存，
        保持「测试零修改」约束（design D10：context 由 pm 内部推导亦成立）。"""
        if name == "_context":
            ctx = PipelineContext.from_pm(self._pm)
            self._context = ctx
            return ctx
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    # ── report_gate 薄委托（refactor-verification-module D2b 规则 2：runner.py
    # 内部调用点 MUST 保持 self.<方法名> 形式，实现委托至模块级函数）──

    def _read_verify_report(self, spec_name: str) -> dict:
        return _read_verify_report(self, spec_name)

    def _ensure_verification_report(self, spec_name: str) -> str | None:
        return _ensure_verification_report(self, spec_name)

    def _check_verification_gate(self, spec_name: str) -> str | None:
        return _check_verification_gate(self, spec_name)

    def _verifier_result_is_stale(self, result, result_path, spec_name: str) -> bool:
        return _verifier_result_is_stale(self, result, result_path, spec_name)

    def _read_verifier_result(self, result_path):
        return _read_verifier_result(self, result_path)

    def _read_planner_result(self, spec_name: str):
        return _read_planner_result(self, spec_name)

    def _read_verdict(self, spec_name: str):
        return _read_verdict(self, spec_name)

    # ── branch_guard 薄委托（见 report_gate 注释 D2b 规则 2）──

    def _branch_commit_count(self, result) -> Optional[int]:
        return _branch_commit_count(self, result)

    def _implementation_branch_has_commits(self, result) -> bool:
        return _implementation_branch_has_commits(self, result)

    def _implementer_zero_change(self, spec_name: str, result) -> bool:
        return _implementer_zero_change(self, spec_name, result)

    def _deliverable_gate_missing(self, spec_name: str, result) -> list:
        return _deliverable_gate_missing(self, spec_name, result)

    def _tasks_md_relint_from_branch(self, spec_name: str, branch) -> list:
        return _tasks_md_relint_from_branch(self, spec_name, branch)

    def _tasks_md_relint_from_worktree(self, spec_name: str, worktree_path) -> list:
        return _tasks_md_relint_from_worktree(self, spec_name, worktree_path)

    def _disputed_deliverables(self, impl_result, missing) -> list:
        return _disputed_deliverables(self, impl_result, missing)

    @staticmethod
    def _extract_replan_error_items(env_error: str) -> list[str]:
        # 模块级函数与静态方法同名：经模块别名解析（branch_guard 已导入同名函数）
        return _bg_extract_replan_error_items(env_error)

    @staticmethod
    def _replan_errors_unconsumed(prev_items: list, cur_items: list) -> bool:
        return _bg_replan_errors_unconsumed(prev_items, cur_items)

    # ── infra_classify 薄委托（见 report_gate 注释 D2b 规则 2）──

    def _verifier_error_is_infra(self, error_text: str) -> bool:
        return _verifier_error_is_infra(self, error_text)

    def enrich_failure_class(
        self, spec_name: str, error_text: str = "", result=None, result_path=None
    ) -> str:
        return enrich_failure_class(self, spec_name, error_text, result, result_path)

    def _record_infra_failure(self, spec_name: str, reason: str, run_id: str = "") -> None:
        return _record_infra_failure(self, spec_name, reason, run_id)

    def _detect_uniform_verify_failure(self, spec_name: str, report: dict) -> bool:
        return _detect_uniform_verify_failure(self, spec_name, report)

    def _fail_history_path(self, spec_name: str) -> Path:
        return _fail_history_path(self, spec_name)

    def _read_fail_history(self, spec_name: str) -> list:
        return _read_fail_history(self, spec_name)

    def _append_fail_history(
        self,
        spec_name: str,
        cause_type: str,
        failed_scenarios: list,
        failure_class: str = "",
        run_id: str = "",
    ) -> None:
        return _append_fail_history(
            self, spec_name, cause_type, failed_scenarios, failure_class, run_id
        )

    def _clear_fail_history(self, spec_name: str) -> None:
        return _clear_fail_history(self, spec_name)

    def _scenario_classification_distribution(self, spec_name: str) -> dict:
        return _scenario_classification_distribution(self, spec_name)

    def _failed_scenario_ids(self, spec_name: str) -> list:
        return _failed_scenario_ids(self, spec_name)

    @staticmethod
    def _normalize_fail_signature(text: str) -> str:
        return _normalize_fail_signature(text)

    # ── scenario_gate 薄委托（见 report_gate 注释 D2b 规则 2）──

    def _apply_scenario_freeze(self, spec_name: str) -> dict:
        return _apply_scenario_freeze(self, spec_name)

    def _apply_interaction_contract(self, spec_name: str) -> dict:
        return _apply_interaction_contract(self, spec_name)

    @staticmethod
    def _load_frozen_scenarios(verify_dir):
        return _load_frozen_scenarios(verify_dir)

    def _render_scenario_change_section_to_report(self, spec_name: str) -> None:
        return _render_scenario_change_section_to_report(self, spec_name)

    def _write_verify_contract_missing(
        self, spec_name: str, note: str, evidence=None, recommended_action=None
    ) -> None:
        return _write_verify_contract_missing(self, spec_name, note, evidence, recommended_action)

    def _run_scenario_static_check(self, spec_name: str) -> None:
        return _run_scenario_static_check(self, spec_name)

    def _run_contract_static_check(self, spec_name: str) -> None:
        return _run_contract_static_check(self, spec_name)

    # ── serving 薄委托（见 report_gate 注释 D2b 规则 2）──

    def _ensure_serving_worktree(self, spec_name: str, contract, mode: str):
        return _ensure_serving_worktree(self, spec_name, contract, mode)

    def _serve_static_in_main(self, contract, scenarios_path) -> tuple:
        return _serve_static_in_main(self, contract, scenarios_path)

    def _serve_static_in_worktree(self, spec_name, contract, scenarios_path) -> tuple:
        return _serve_static_in_worktree(self, spec_name, contract, scenarios_path)

    def _serve_command_in_worktree(self, spec_name, contract, scenarios_path) -> tuple:
        return _serve_command_in_worktree(self, spec_name, contract, scenarios_path)

    def _serve_command_in_main(self, spec_name, contract, scenarios_path) -> tuple:
        return _serve_command_in_main(self, spec_name, contract, scenarios_path)

    def _finalize_static(self, srv, contract, scenarios_path, scope_label) -> tuple:
        return _finalize_static(self, srv, contract, scenarios_path, scope_label)

    def _remove_serving_worktree(self, wt_path) -> None:
        return _remove_serving_worktree(self, wt_path)

    def _register_serving_instance(
        self, spec_name: str, server, wt_path=None, hint_port=None
    ) -> None:
        return _register_serving_instance(self, spec_name, server, wt_path, hint_port)

    def _unregister_serving_instance(self, spec_name: str, server) -> None:
        return _unregister_serving_instance(self, spec_name, server)

    def _evict_spec_serving(self, spec_name: str) -> None:
        return _evict_spec_serving(self, spec_name)

    def _current_instance_base_url(self, spec_name: str) -> str:
        return _current_instance_base_url(self, spec_name)

    def _ensure_app_reachable(self, spec_name: str) -> tuple:
        return _ensure_app_reachable(self, spec_name)

    @staticmethod
    def _port_responds(port: int) -> bool:
        return _port_responds(port)

    def _open_boot_log(self, spec_name: str):
        return _open_boot_log(self, spec_name)

    def _read_boot_log_tail(self, spec_name: str, handle) -> str:
        return _read_boot_log_tail(self, spec_name, handle)

    def _rewrite_scenario_port(self, scenarios_path, old_port: int, new_port: int):
        return _rewrite_scenario_port(self, scenarios_path, old_port, new_port)

    def _serving_port_for_spec(self, spec_name: str):
        return _serving_port_for_spec(self, spec_name)

    def _current_verify_round(self, spec_name: str) -> int:
        return _current_verify_round(self, spec_name)

    # ── escalation 薄委托 ──
    def _handle_env_blocked_inconclusive(self, spec_name: str, report: dict) -> bool:
        return _handle_env_blocked_inconclusive(self, spec_name, report)

    def _write_inconclusive_loop_signal(
        self, spec_name: str, attempts: int, blocked_env: int, report: dict
    ) -> bool:
        return _write_inconclusive_loop_signal(self, spec_name, attempts, blocked_env, report)

    def _env_whitewash_gate(self, spec_name: str) -> bool:
        return _env_whitewash_gate(self, spec_name)

    def _escalate_env_blocked(
        self, spec_name: str, violations: list, title: str = "验证环境阻塞"
    ) -> None:
        return _escalate_env_blocked(self, spec_name, violations, title)

    def _update_warning_streaks(self, spec_name: str) -> list:
        return _update_warning_streaks(self, spec_name)

    def _warning_stale_triage_alert(self, spec_name: str, scenario_ids: list) -> None:
        return _warning_stale_triage_alert(self, spec_name, scenario_ids)

    def _scenario_defect_reroute_gate(
        self, spec_name: str, _repair_depth: int = 0, judge_result=None
    ) -> bool:
        return _scenario_defect_reroute_gate(self, spec_name, _repair_depth, judge_result)

    def _escalate_scenario_defect_reroute(
        self, spec_name: str, dist: dict, _repair_depth: int = 0
    ) -> None:
        return _escalate_scenario_defect_reroute(self, spec_name, dist, _repair_depth)

    def _handle_judge_env_declared(self, spec_name: str) -> None:
        return _handle_judge_env_declared(self, spec_name)

    def _judge_bugs_declare_env(self, spec_name: str) -> bool:
        return _judge_bugs_declare_env(self, spec_name)

    def _speculative_bug_found_gate(self, spec_name: str) -> bool:
        return _speculative_bug_found_gate(self, spec_name)

    # ── legacy 薄委托 ──
    def _run_legacy_verification(self, spec_name: str) -> None:
        return _run_legacy_verification(self, spec_name)

    # ── verdict_evidence 薄委托 ──
    def _verify_verdict_evidence(self, spec_name: str, retry_judge=False):
        return _verify_verdict_evidence(self, spec_name, retry_judge)

    def _verdict_violations_evidence(self, spec_name: str, violations: list) -> list:
        return _verdict_violations_evidence(self, spec_name, violations)

    def _write_verdict_violations(self, spec_name: str, violations: list) -> None:
        return _write_verdict_violations(self, spec_name, violations)

    def _clear_verdict_violations(self, spec_name: str) -> None:
        return _clear_verdict_violations(self, spec_name)

    def _verdict_violations_path(self, spec_name: str) -> Path:
        return _verdict_violations_path(self, spec_name)

    def _resynthesis_directive_path(self, spec_name: str) -> Path:
        return _resynthesis_directive_path(self, spec_name)

    def _read_resynthesis_directive(self, spec_name: str) -> dict | None:
        return _read_resynthesis_directive(self, spec_name)

    def _clear_resynthesis_directive(self, spec_name: str) -> None:
        return _clear_resynthesis_directive(self, spec_name)

    def _resynthesis_directive_scenarios(self, report: dict, violations: list) -> list:
        return _resynthesis_directive_scenarios(self, report, violations)

    def _write_resynthesis_directive(
        self,
        spec_name: str,
        report: dict,
        violations: list,
        rejection_round: int,
        resynthesis_attempts: int,
    ) -> None:
        return _write_resynthesis_directive(
            self, spec_name, report, violations, rejection_round, resynthesis_attempts
        )

    def _escalate_dedup_resynthesis(
        self, spec_name: str, rejection_round: int, violations: list
    ) -> None:
        return _escalate_dedup_resynthesis(self, spec_name, rejection_round, violations)

    def _handle_attr_dedup_rejection(
        self, spec_name: str, report: dict, dedup_violations: list
    ) -> dict:
        return _handle_attr_dedup_rejection(self, spec_name, report, dedup_violations)

    def _handle_scenario_requeue(self, spec_name: str, report: dict, dedup: dict) -> dict:
        return _handle_scenario_requeue(self, spec_name, report, dedup)

    def _clear_requeue_manifest(self, spec_name: str) -> None:
        return _clear_requeue_manifest(self, spec_name)

    def _record_verdict_adoption(self, spec_name: str, status: str, report: dict) -> None:
        return _record_verdict_adoption(self, spec_name, status, report)

    def _persist_verdict_cache(self, spec_name: str, report: dict) -> None:
        return _persist_verdict_cache(self, spec_name, report)

    def _verified_verdict_persisted(self, spec_name: str) -> bool:
        return _verified_verdict_persisted(self, spec_name)

    def _verified_gate_refuses(self, spec_name: str, target: str) -> bool:
        return _verified_gate_refuses(self, spec_name, target)

    # ── judge_gate 薄委托（见 report_gate 注释 D2b 规则 2）──

    def _judge_dispatch_gate(self, spec_name: str) -> str | None:
        return _judge_dispatch_gate(self, spec_name)

    def _judge_hard_cap_freeze(self, spec_name: str, count: int) -> None:
        return _judge_hard_cap_freeze(self, spec_name, count)

    def _judge_rerun_count(self, spec_name: str, delta: int = 0) -> int:
        return _judge_rerun_count(self, spec_name, delta)

    def _all_green_fast_path(self, spec_name: str, report: dict, fail_count: int):
        return _all_green_fast_path(self, spec_name, report, fail_count)

    def _last_planner_cost_usd(self, spec_name: str) -> float | None:
        return _last_planner_cost_usd(self, spec_name)

    def _last_planner_run_cost(self, spec_name: str) -> str:
        return _last_planner_run_cost(self, spec_name)

    def _write_degrade_context(
        self, spec_name: str, reason: str, run_id: str, duration_seconds: float
    ) -> None:
        return _write_degrade_context(self, spec_name, reason, run_id, duration_seconds)

    def _clear_degrade_context(self, spec_name: str) -> None:
        return _clear_degrade_context(self, spec_name)

    def _run_three_stage_verification(self, spec_name: str, _repair_depth: int = 0):
        """三步验证流水线主逻辑。"""
        # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）：入口状态
        # 非 testing → DEBUG 丢弃本流水线结果（注明当前状态），不执行任何迁移/
        # 回退/派发。覆盖 stale-result 防护拨回 implemented、并发双路径中先到者
        # 已推进、以及一切状态漂移变体。正常路径（dispatch 刚置 testing）不受影响。
        _entry_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
        if _entry_status != "testing":
            self._context.logger.debug(
                "pm_engine",
                f"Verify result discarded for '{spec_name}': spec is "
                f"'{_entry_status}', not testing at pipeline entry — dropped",
            )
            return

        import asyncio
        import importlib
        import sys

        # 重新加载验证引擎模块，确保使用最新代码
        # fenixd 作为常驻进程运行，Python 会缓存已导入的模块，
        # 实现者更新代码后缓存不会自动失效，必须显式重新加载
        # 注意：子模块必须先于父包重新加载（依赖顺序）
        #
        # 额外保障机制（fix-fix-fix-fix）：
        # importlib.reload 不会更新其他模块中已导入的名称引用，
        # 因此在 reload 之后显式重新导入核心类，确保使用最新版本。
        _verify_modules = [
            "core.verify_engine.visual_diff",
            "core.verify_engine.browser",
            # admin 修 2026-09-06：web_runner 持有 `from .browser import
            # BrowserManager` 的旧类引用（reload 不会更新其他模块已导入的
            # 名称），不 reload 它则 browser.py 的更新经 WebRunner 实例化
            # 路径完全不生效（add-spec-hooks admin 处置实测：browser 首帧
            # 等待修复被旧 BrowserManager 类屏蔽）。须先于 engine reload。
            "core.verify_engine.web_runner",
            # admin 修 2026-09-07：三个 runner 一并 reload——此前 cli/api
            # runner 不在列表内，其代码修复同样不生效；配合 runner.py 的
            # 同模块重注册放行（否则装饰器对已注册 kind raise、reload 整体
            # 失败且被下方静默吞掉，sys.modules 留存旧类）。
            "core.verify_engine.cli_runner",
            "core.verify_engine.api_runner",
            "core.verify_engine.assertions",
            "core.verify_engine.scenarios",
            "core.verify_engine.scenario_static_check",
            "core.verify_engine.engine",
            "core.verify_engine",
        ]
        for mod_name in _verify_modules:
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception as e:
                    # reload 失败绝不可静默：sys.modules 将留存旧代码，admin
                    # 的引擎修复看似已生效实则被旧类屏蔽（本类根因曾静默潜伏
                    # 至 fix-mobile-touch-disclosure 轮才暴露）。降级告警留痕。
                    self._context.logger.warning(
                        "pm_engine",
                        f"verify_engine 模块热重载失败 '{mod_name}'（将沿用旧代码）: "
                        f"{type(e).__name__}: {e}",
                    )

        # 额外保障：强制从磁盘重新导入核心模块
        # Python 的 import 系统会检查 sys.modules，但如果 reload 失败，
        # 下面的 import 会使用已更新的 sys.modules 条目
        for mod_name in _verify_modules:
            try:
                if mod_name not in sys.modules:
                    importlib.import_module(mod_name)
            except Exception:
                pass

        from core.verify_engine import VerifyEngine
        from core.verify_engine.scenarios import load_scenarios

        # ── 阶段1+2: Planner↔场景验收闭环（2026-08-28）──
        # 场景验收（绝对 navigate URL/完整性）失败 → 写 REPLAN_FEEDBACK.md 退回
        # plan 阶段重新生成，上限 2 次重排；连续失败保持 implemented + error
        # 可见（验收失败属环境/任务书问题，绝非产品缺陷，绝不流转 bug-found）。
        verify_dir = self._context.project_root / ".fenix" / "verify-progress" / spec_name
        replan_left = 2
        replan_feedback = None
        # fix-replan-feedback-injection：上一轮验收错误原文——连续两轮一字不差说明
        # planner 未消费反馈（重跑即纯烧钱），升级为 ERROR 提示人工关注。
        prev_replan_error = None
        report = None
        app_reachable = True
        reach_note = ""
        # ── 场景冻结复用（scenario-reuse-on-reenter，2026-09-04）──
        # 冻结集一经生成即跨轮一致的量尺：重入验证（打回/修复轮/重试）直接
        # 复用，绝不重新出题——planner 单轮 2h/30M token 级成本只支付一次。
        # 冻集变更的唯一通道：admin 裁决（扩展/豁免）或人工删除冻结文件批准
        # 重新出题。首次进入（无冻结文件）走下方 planner 设计闭环。
        frozen = self._load_frozen_scenarios(verify_dir)
        if isinstance(frozen, tuple) and frozen[0] == "corrupt":
            self._context.logger.error(
                "pm_engine",
                f"冻结场景文件验收失败 '{spec_name}' — 场景一经冻结跨轮一致，"
                f"变更须 admin 裁决，不自动重新出题",
            )
            # frozen-scenario-schema-migration 1.2：升级告警附字段级差异清单
            # （场景 id/下标/缺失字段），admin 可凭差异精准修复冻结文件，
            # 不再给笼统 corrupt 盲修。
            detail = frozen[1] if len(frozen) > 1 else ""
            self._escalate_env_blocked(
                spec_name,
                [
                    "冻结场景文件损坏或验收失败。处置选项：① 确认场景集已过时 → "
                    f"删除 .fenix/verify-progress/{spec_name}/test_scenarios.json "
                    "批准重新出题；② 文件可修复 → 修复后保持冻结。",
                    f"验收差异清单：{detail[:600]}" if detail else "验收差异清单：无",
                ],
                title="场景计划争议",
            )
            return
        while True:
            if frozen is not None:
                # ── 冻结复用：跳过整段出题，覆盖缺口按计划争议升级 ──
                self._context.logger.info(
                    "pm_engine",
                    f"[阶段1] 场景冻结复用（{len(frozen)} 个场景），跳过重新出题: " f"{spec_name}",
                )
                cov = self._apply_interaction_contract(spec_name)
                if cov is not None and not cov.get("ok"):
                    self._context.logger.error(
                        "pm_engine",
                        f"冻结场景覆盖缺口 '{spec_name}'（修复新增可交互元素？）"
                        f"— 场景变更须 admin 裁决，不自动重排: {cov.get('uncovered')}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [
                            f"冻结场景未覆盖可交互元素: {cov.get('uncovered')}。"
                            "处置选项：① 扩展冻结场景集；② 声明纯展示；"
                            "③ 删除冻结文件批准重新出题。"
                        ],
                        title="场景计划争议",
                    )
                    return
                # 覆盖完整 → 落入下方阶段2（共享执行段）
            else:
                if replan_feedback is not None:
                    fb = verify_dir / "REPLAN_FEEDBACK.md"
                    fb.parent.mkdir(parents=True, exist_ok=True)
                    fb.write_text(
                        "# 场景验收反馈（上一轮未通过，必须逐条修正）\n\n"
                        + replan_feedback
                        + "\n\n重新输出全部场景；navigate 的 value 必须为绝对 URL。\n",
                        encoding="utf-8",
                    )
                # ── 阶段1 派 run 前状态重查（fasttrack-orphan-planner-race）──
                # D6 入口检查只覆盖 pipeline 进入时刻；竞态窗口内 fast-track
                # advance（_fast_track_advance_to_verified）可能已把 spec 推过
                # verified/done/pushed——此刻再派 planner run 即成孤儿
                # （2026-09-08 fix-verify-cli-cwd-isolation：已 pushed 后场景生成
                # run 白跑 14min）。非 testing 一律丢弃，与 D6 同语义（注明当前
                # 状态，不迁移不回退不派发）；replan 重排轮次同样经过本检查点。
                _stage1_status = (self._context.state_machine.read_one(spec_name) or {}).get(
                    "status", ""
                )
                if _stage1_status != "testing":
                    self._context.logger.warning(
                        "pm_engine",
                        f"[阶段1] Planner 派发前状态重查丢弃 '{spec_name}': spec is "
                        f"'{_stage1_status}', not testing at planner dispatch — "
                        "dropped (orphan-planner guard)",
                    )
                    return
                self._context.logger.info("pm_engine", f"[阶段1] Planner 生成场景: {spec_name}")
                # 路由地图前置生成（add-planner-efficiency：planner-route-map 1.1）：
                # 阶段1 进入处接入，对 impl worktree 生成/复用路由地图（HEAD 键控、
                # fail-open——生成器缺失/失败不阻塞）。planner 出题 prompt 组装前
                # 的最终保障在 runner 的 worktree 创建点，此处为前置早生成。
                self._pm.agent_runner.ensure_planner_route_map(spec_name)
                plan_result = self._pm.agent_runner.run_planner(spec_name, "plan")

                if not plan_result.success:
                    # ── 人工取消 hold-state（add-run-cancel D4）──
                    # planner run 被取消：spec 保持 testing 原状，只写 error，
                    # 不流转 bug-found、不降级 legacy、不入队。
                    if getattr(plan_result, "cancelled", False):
                        p_err = plan_result.error or ""
                        cancelled_err = f"run 被人工取消：{p_err}" if p_err else "run 被人工取消"
                        self._context.state_machine.update_spec(
                            spec_name,
                            {
                                "error": cancelled_err,
                                # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                                "_cancelled_hold": True,
                            },
                        )
                        self._context.logger.warning(
                            "pm_engine",
                            f"Planner plan run 被人工取消 — hold-state '{spec_name}' "
                            f"(保持 testing): {cancelled_err}",
                        )
                        return
                    # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
                    # 熔断期 planner 派发失败属「provider 故障」，不是验证逻辑失败：
                    # 不得 raise（会触发 legacy 降级 → bug-found → 伪 fix 级联），
                    # 保持 spec 在 implemented（由 full_scan recovery 兜底重排）。
                    if plan_result.error and "provider circuit open" in plan_result.error:
                        self._context.state_machine.update_spec(
                            spec_name,
                            {
                                "error": plan_result.error,
                            },
                        )
                        # evo-infra-failure-budget-exempt R2：provider 熔断属 infra，
                        # 在归因入口前早退的既有 infra 判定点挂预算退款与记账
                        # （否则 provider infra 轮仍耗实现预算，与目标 2 不符）。
                        self._record_infra_failure(
                            spec_name,
                            plan_result.error,
                            run_id=getattr(plan_result, "run_id", "") or "",
                        )
                        self._context.logger.warning(
                            "pm_engine",
                            f"Provider circuit open — planner suppressed for '{spec_name}', "
                            f"holding implemented: {plan_result.error}",
                        )
                        return
                    raise RuntimeError(f"Planner plan 失败: {plan_result.error}")

                # 验证 Planner 是否成功生成场景文件
                plan_read = self._read_planner_result(spec_name)
                # fix-verdict-read-failclosed：plan 结果不可读（缺失/非法/白名单外）
                # 与「非 plan-ready」同判——阶段1 本就 fail-closed（≠plan-ready 即
                # 降级 legacy），不可读绝不等于「场景已生成」（fail-open 的反面）。
                if not plan_read.ok or plan_read.status != "plan-ready":
                    # fix-planner-invalid-output-alert：planner run 成功收工却无有效产出
                    # ＝ 整轮 planner 时长/成本白烧，必须显式留痕（error 字段 + ERROR 级
                    # 日志），否则只在降级 WARNING 里一笔带过，浪费不可见。
                    plan_status_text = (
                        f"不可读({plan_read.reason}: {plan_read.detail})"
                        if not plan_read.ok
                        else f"'{plan_read.status}'"
                    )
                    self._context.state_machine.update_spec(
                        spec_name,
                        {
                            "error": (
                                f"Planner 场景生成无效（status={plan_status_text}，run="
                                f"{plan_result.run_id}，{plan_result.duration_seconds / 60:.1f}min）"
                                f"— 降级旧版验证流程"
                            ),
                        },
                    )
                    self._context.logger.error(
                        "pm_engine",
                        f"Planner 未生成有效场景 '{spec_name}'（status={plan_status_text}，"
                        f"run={plan_result.run_id}，白烧 "
                        f"{plan_result.duration_seconds / 60:.1f}min）— 降级旧版 verifier",
                    )
                    # add-planready-artifact-gate D3：降级前落盘上下文
                    # （供 verify_report 合成路径注入降级标注，G3）。
                    self._write_degrade_context(
                        spec_name,
                        reason=(f"Planner 未生成有效场景，status={plan_status_text}"),
                        run_id=plan_result.run_id,
                        duration_seconds=plan_result.duration_seconds or 0,
                    )
                    raise RuntimeError(f"Planner 未生成有效场景，status={plan_status_text}")

                # add-planready-artifact-gate D3：plan-ready 校验通过（新一轮验证
                # 正常启动）→ 删除陈旧 degrade_context.json，防旧降级事实污染后续
                # 正常报告（成功时才清理，失败/重验路径历史留痕）。
                self._clear_degrade_context(spec_name)

                # ── 契约只读一致性检查（planner-contract-findings，design D4）──
                # planner-plan 产物验收通过后（出题完成处）：对验证契约做只读
                # 一致性检查并落盘 contract_findings.json（fail-open，不阻断
                # 出题——契约检查与场景生成相互独立）。
                self._run_contract_static_check(spec_name)

                # ── 场景集冻结（add-verify-scenario-freeze）──
                # 首轮写入 / 修复轮 diff 校验（design D3：确定性，planner 不可绕过）。
                # 在场景执行前应用：以持久化集约束 planner 产出，缺场景补齐后继续验证。
                # （冻结复用路径不经过此处——冻结集即原班场景，无需再约束产出。）
                try:
                    freeze_result = self._apply_scenario_freeze(spec_name)
                except Exception as e:
                    # 冻结逻辑属辅助治理，绝不阻断验证主流程
                    self._context.logger.warning(
                        "pm_engine",
                        f"场景集冻结处理跳过 '{spec_name}'（异常不阻断验证）: {e}",
                    )
                    freeze_result = None
                if isinstance(freeze_result, dict) and freeze_result.get("aborted"):
                    # ── 空集显式兜底（evo-planner-scenario-schema-alignment 3.5/3.7）──
                    # 写回合法子集后「全部非法」不再触发阶段2 load_scenarios 报错
                    # （既有退回路径依赖的正是该报错），空集信号经结构化返回值承载：
                    # 0 场景经 engine.run([]) 产出无 env_error 的全绿报告，会被洗白
                    # 门 fail-open 放行判 verified——MUST NOT 以 0 场景进入阶段2。
                    reject_detail = "、".join(freeze_result.get("rejected") or [])
                    fb_text = (
                        f"场景写前预校验整批拒绝：本轮 planner 产出全部非法"
                        f"（写盘前逐条预检，未生成任何可执行场景），共 "
                        f"{freeze_result.get('total', 0)} 条。逐条原因："
                        f"{reject_detail[:600]}。请按 prompt 注入段「场景断言/"
                        f"操作必填字段」的必填字段与合法样例修正后重新输出全部场景。"
                    )
                    if replan_left > 0:
                        replan_feedback = fb_text
                        replan_left -= 1
                        self._context.logger.error(
                            "pm_engine",
                            f"场景集为空（写前预校验整批拒绝）'{spec_name}' — "
                            f"退回 plan 阶段（剩余重排 {replan_left} 次）: "
                            f"{reject_detail[:200]}",
                        )
                        continue
                    # 3.7 预算耗尽分支：MUST NOT 落入下方「预算耗尽即继续验证」
                    # fall-through（对空集即等于携 0 场景进入阶段2 执行与裁决）。
                    # 比照 env_error 退回的预算耗尽分支（verification.py:1929-1943）：
                    # 置 implemented + error 显式结束本轮，ERROR 留痕。
                    self._context.state_machine.update_spec(
                        spec_name,
                        {
                            "status": "implemented",
                            "tester_run": None,
                            "error": (
                                f"场景写前预校验整批拒绝且重排预算耗尽（{replan_left} "
                                f"次用尽）: {reject_detail[:280]}"
                            ),
                        },
                    )
                    self._context.logger.error(
                        "pm_engine",
                        f"场景集为空且重排预算耗尽 '{spec_name}' — 显式结束本轮"
                        f"（保持 implemented 等待人工），0 场景不进入阶段2: "
                        f"{reject_detail[:200]}",
                    )
                    return

                # ── 交互契约覆盖校验（add-interaction-contract-and-per-assert-triage 1.3）──
                # 可交互元素既无场景覆盖又无纯展示声明 → 写反馈退回 plan 补齐
                # （复用场景验收退回路径）；重排预算耗尽后不阻断验证，违规留痕。
                contract = self._apply_interaction_contract(spec_name)
                if contract is not None and not contract.get("ok"):
                    if replan_left > 0:
                        replan_feedback = contract.get("feedback") or ""
                        replan_left -= 1
                        self._context.logger.warning(
                            "pm_engine",
                            f"交互契约覆盖不完整 '{spec_name}' — 退回 plan 阶段"
                            f"（剩余重排 {replan_left} 次）: {contract.get('uncovered')}",
                        )
                        continue
                    self._context.logger.error(
                        "pm_engine",
                        f"交互契约重排预算耗尽 '{spec_name}' — 违规留痕继续验证: "
                        f"{contract.get('uncovered')}",
                    )

            # ── 契约消费期轻量自证（design D2）──
            # mtime 变化后的首验轮执行（serve 段合法性 + 现有实例 ready 鉴别力
            # 自检，不执行 prepare、不起实例）；自证失败 = 契约错误 fail-fast，
            # 不进入场景执行（场景执行数=0），走 verify_contract_missing 信号
            # 通道呼叫 Administrator。契约缺失/纯 cli 形态返回 None 天然放行。
            selfcheck_err = None
            try:
                from core.verify_contract import selfcheck_contract_light

                selfcheck_err = selfcheck_contract_light(
                    self._context.project_root,
                    self._context.logger,
                    base_url=self._current_instance_base_url(spec_name),
                )
            except Exception as e:
                # 自证自身异常 fail-open：不因自证代码缺陷牵连验证主流程
                self._context.logger.warning(
                    "pm_engine", f"契约轻量自证跳过 '{spec_name}'（异常不阻断验证）: {e}"
                )
            if selfcheck_err:
                self._context.logger.error(
                    "pm_engine",
                    f"契约轻量自证失败 '{spec_name}' — fail-fast 阻断场景执行: " f"{selfcheck_err}",
                )
                self._write_verify_contract_missing(
                    spec_name,
                    f"{selfcheck_err}（契约消费期轻量自证失败，场景执行数为 0）",
                    f"项目根={self._context.project_root}; 自证类型=轻量(mtime 门+serve 段)"
                    f"+ready 鉴别力",
                    recommended_action=(
                        "Administrator 修正 .fenix/verify.yaml 验证契约：按错误信息"
                        "中的段落与原因修正（serve 段字段/static root 目录/ready 探针"
                        "配置），修正后 git 提交 → spec 复位 ready 触发重验证"
                    ),
                )
                self._escalate_env_blocked(
                    spec_name,
                    [selfcheck_err],
                    title="验证环境阻塞（契约轻量自证失败）",
                )
                return

            # ── 阶段2: 验证引擎执行 ──
            self._context.logger.info("pm_engine", f"[阶段2] 验证引擎执行: {spec_name}")
            scenarios_path = (
                self._context.project_root
                / ".fenix"
                / "verify-progress"
                / spec_name
                / "test_scenarios.json"
            )
            # 场景文件验收失败（相对 URL/结构非法）＝ 明确的环境错误：
            # 退回 plan 阶段重新生成，不走 raise 穿透、更不判 bug-found。
            env_error = None
            report = None
            try:
                scenarios = load_scenarios(scenarios_path)
            except ValueError as e:
                env_error = f"场景文件验收失败: {e}"

            if env_error is None:
                # ── 阶段2.5: 应用可达性自愈（最终用户验证必选）──
                # 场景执行前确保应用可被浏览器访问；不可达时自动启动 commands.start、
                # 端口冲突换端口重试。自愈失败由下方验证门禁兜底，不静默判定通过。
                app_reachable, user_blocked, reach_note = self._ensure_app_reachable(spec_name)
                self._context.logger.info(
                    "pm_engine",
                    f"[阶段2] 应用可达性: {'OK' if app_reachable else '不可达'} — {reach_note or '无 navigate 依赖'}",
                )

                # ── 可达性自愈失败即本轮 fail-fast（add-verify-unreachable-failfast D1）──
                # 自愈失败（就绪探针超时 / prepare 失败 / 契约缺失）属确定性环境错误，
                # 继续跑整轮场景只会空转烧钱、由判定链末段兜底还易误拒。此处直接短路：
                # 场景执行数=0、不重读场景、不创建/运行 VerifyEngine、不退回 plan 重排，
                # 复用既有 _escalate_env_blocked 升级通道（落 blocked → 自动呼叫
                # Administrator → 连续 2 轮冻结转人工）。evidence 用 reach_note（已由
                # add-verify-preflight-gate D3 内嵌 boot.log 尾部）。user_blocked 守卫：
                # 「需用户参与（收验证码/登录）」预留判定位恒 False，将来实现后不得被
                # 短路自动判 blocked，故显式含 not user_blocked。
                if not app_reachable and not user_blocked:
                    self._context.logger.error(
                        "pm_engine",
                        f"[阶段2] 应用不可达，本轮 fail-fast（场景执行数=0）'{spec_name}': "
                        f"{reach_note}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [reach_note],
                        title="验证环境阻塞（应用不可达）",
                    )
                    return

                # 自愈可能改写场景文件端口（场景声明端口 → 框架分配端口）：
                # 上方 load 先于自愈，内存场景仍持声明端口，改写只落文件、对本次
                # 执行无效 → 全场景对失联端口 navigate 整轮伪失败
                # （add-v3-spec-detail-page：24 场景导航 localhost:8000 全灭）。
                # 故自愈后必须重读场景文件再执行。
                try:
                    scenarios = load_scenarios(scenarios_path)
                except ValueError as e:
                    env_error = f"自愈改写后场景文件验收失败: {e}"

            if env_error is None:
                # ── 场景静态缺陷扫描（add-scenario-defect-triage-gate D3）──
                # 在场景集冻结完成后、执行前调用：findings 只作情报落盘
                # （scenario_static_findings.json）+ judge prompt 定向注入，
                # fail-open——任何异常记 WARNING，不阻断验证执行。
                self._run_scenario_static_check(spec_name)

                # 场景执行根：worktree 轮传入 serving worktree 根（CLI 步骤
                # 缺省 cwd 以此为准，seed 写入落验证树而非主树）；
                # 无 worktree 轮不传（回退主树 project_root，行为不变）。
                scenario_root = None
                _sv_cache = self.__dict__.get("_contract_static_servers", {})
                _sv_entry = _sv_cache.get(spec_name)
                if isinstance(_sv_entry, dict):
                    _wt_path = _sv_entry.get("wt_path")
                    if _wt_path:
                        scenario_root = Path(_wt_path)
                engine = VerifyEngine(
                    spec_name,
                    self._context.project_root,
                    self._context.logger,
                    self._pm.config,
                    scenario_root=scenario_root,
                )
                # add-verify-parallel-backoff / design D1（读端）：spec attrs 的
                # `_verify_parallel_override` 非空时覆盖 max_parallel 配置值——
                # 该字段仅由 inconclusive 重验链路（连续 blocked-env 降档）写入、
                # 健康轮自动复位，构造签名不变，既有测试兼容。降档来源标记随
                # 引擎启动日志与 report 顶层 effective_parallel 透出（D3）。
                _parallel_override = (self._context.state_machine.read_one(spec_name) or {}).get(
                    "_verify_parallel_override"
                )
                if _parallel_override is not None:
                    try:
                        engine.max_parallel = int(_parallel_override)
                        engine._parallel_override_active = True
                    except (TypeError, ValueError):
                        self._context.logger.warning(
                            "pm_engine",
                            f"降档并行度解析失败 '{spec_name}' "
                            f"(_verify_parallel_override={_parallel_override!r})，"
                            f"沿用配置并行度",
                        )
                # 契约统一供给 base_url（design verify-runner-engine base_url 统一供给）：
                # 取代「从候选场景 navigate 步骤文本正则考古」——serve 流程已知
                # 实例地址，直接分发各 Runner（web/api URL origin 改写依据、
                # 环境门探针定位依据）。无实例形态（纯 cli）为空串无害空操作。
                engine.base_url = self._current_instance_base_url(spec_name)
                report = asyncio.run(engine.run(scenarios))
                env_error = report.get("env_error")

            if env_error:
                # ── 重跑消费硬门（fix-frozen-scenario-orphan-reservoir D5）──
                # 验收失败退回 plan 重跑前，先比对上一轮错误清单：本轮错误与上轮
                # 相同或为上轮超集 → planner 未消费反馈，**不再 continue 重跑**
                # （重跑即纯烧钱），直接走 _escalate_env_blocked 分级升级
                # （blocked → admin 自动处置 → 阈值冻结转人工）。
                # 错误实质性消除（数量减少或主体变化）→ 预算内照常重跑。
                cur_items = self._extract_replan_error_items(env_error)
                prev_items = (
                    self._extract_replan_error_items(prev_replan_error)
                    if prev_replan_error
                    else None
                )
                if self._replan_errors_unconsumed(prev_items, cur_items):
                    self._context.logger.error(
                        "pm_engine",
                        f"场景验收错误与上轮相同或为上轮超集 '{spec_name}' — "
                        f"planner 未消费反馈（{len(prev_items)} 条错误一条未消），"
                        f"拒绝重跑，升级 admin 自动处置: {env_error[:200]}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [
                            f"场景验收连续失败且 planner 未消费反馈（错误清单与上一轮"
                            f"相同或为上轮超集，重跑即纯烧钱）。处置选项：① 修复场景"
                            f"文件（test_scenarios.json 写回须过结构校验门，且与 "
                            f"scenarios.json 同源坏条目同步清理，双文件一致）；"
                            f"② 删除冻结集批准重新出题。"
                        ],
                        title="场景计划争议",
                    )
                    return
                prev_replan_error = env_error
                if replan_left <= 0:
                    self._context.state_machine.update_spec(
                        spec_name,
                        {
                            "status": "implemented",
                            "tester_run": None,
                            "error": (
                                f"场景验收连续失败（退回 plan 2 次仍不通过）: " f"{env_error[:280]}"
                            ),
                        },
                    )
                    self._context.logger.error(
                        "pm_engine",
                        f"场景验收连续失败 '{spec_name}' — 保持 implemented 等待人工: "
                        f"{env_error}",
                    )
                    return
                if frozen is not None:
                    # 冻结复用路径：执行期场景异常不重新出题（量尺一致原则），
                    # 升级 admin 裁决
                    self._context.logger.error(
                        "pm_engine",
                        f"冻结场景执行异常 '{spec_name}' — 不重新出题，升级 admin "
                        f"裁决: {env_error}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [f"冻结场景执行环境异常: {str(env_error)[:200]}"],
                        title="场景计划争议",
                    )
                    return
                replan_feedback = env_error
                replan_left -= 1
                self._context.logger.warning(
                    "pm_engine",
                    f"场景验收未通过 '{spec_name}' — 退回 plan 阶段"
                    f"（剩余重排 {replan_left} 次）: {env_error}",
                )
                continue

            # 验收通过：清理反馈文件（下次全新验证不受旧反馈干扰）
            try:
                (verify_dir / "REPLAN_FEEDBACK.md").unlink()
            except OSError:
                pass
            break

        fail_count = report["summary"]["failed"] + report["summary"]["errors"]
        self._context.logger.info(
            "pm_engine",
            f"[阶段2] 完成: {report['summary']['total']}场景, "
            f"{report['summary']['passed']}通过, "
            f"{report['summary']['warnings']}警告, "
            f"{fail_count}失败",
        )

        # ── 阶段2 验证门禁：应用不可达且场景全失败时不判定 verified ──
        # 最终用户验证为必选项：若自愈后应用仍不可达、0 场景通过，则本次验证
        # 并未真正触达最终用户可见功能，不得静默判定 verified/done；将问题与
        # 已尝试的解决方案写入 error 暴露（而非 "0通过/31失败" 却标完成）。
        if (
            not app_reachable
            and report["summary"]["passed"] == 0
            and fail_count == report["summary"]["total"]
        ):
            self._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": "blocked:app-unreachable",
                    "error": f"验证无法执行（最终用户验证未完成）: {reach_note or '应用不可达'}",
                },
            )
            self._context.logger.error(
                "pm_engine",
                f"验证门禁: '{spec_name}' 应用不可达，未判定 verified — {reach_note}",
            )
            # 死端修复（admin 2026-09-07，notes-standalone-sync 卡 testing 事故）：
            # 此前的裸 return 使 spec 永久滞留 testing——blocked:app-unreachable
            # 标记全库无消费者，且冻结场景集路径（scenario-reuse-on-reenter）
            # 不会重新出题，BLOCKER CHECK 的 auto-recovery 只会原样重验并再次
            # 撞门禁，形成每 stuck_threshold 一次的无效静默重试循环。按冻结
            # 复用路径同款语义升级：blocked + 自动呼叫 Administrator 处置验证
            # 基建（场景 URL/serve 配置属 admin 职权，planner 无法自愈）。
            self._escalate_env_blocked(
                spec_name,
                [
                    f"应用不可达，验证无法执行（冻结场景集下自动重验无效，需 admin "
                    f"修正场景 URL/serve 配置）: {(reach_note or '应用不可达')[:200]}"
                ],
                title="验证环境阻塞",
            )
            return

        # ── 阶段2.6 环境性失联门禁（verify-environment-sanity-gate / design D2）──
        # 全批 blocked-env → inconclusive：回 testing 重派新 attempt，不判 bug-found、
        # 不产生 repeated_failures 信号。阻断后直接 return（跳过 judge / 终态判定）。
        if self._handle_env_blocked_inconclusive(spec_name, report):
            return

        # ── 阶段2.7 全场景同因失败哨（2026-08-28）──
        # pass=0 且全部失败场景错误签名一致 → 疑环境/场景问题，呼叫 admin 介入
        # 判断；不判 bug-found、不派生 fix；连续 3 轮同因自动 blocked。
        if self._detect_uniform_verify_failure(spec_name, report):
            return

        # ── 阶段3 快道：全绿机械 verified（judge 效率治理 2026-09-06）──
        # 0 失败且 0 警告时 judge 无信息增量（无分类对象；洗白门禁仅在
        # 「0 通过或 env 失败」可触发，全绿恒无违规）——跳过 LLM 裁决
        # （常态 15-50 分钟），合成结果文件后走与 judge 完全同源的采纳
        # 尾段（进度核对/报告闸门/洗白门禁/transition）。tester_run 记
        # mechanical-all-green 留痕。
        judge_result = self._all_green_fast_path(spec_name, report, fail_count)
        if judge_result is None:
            # ── 阶段3: Planner 判定结果 ──
            self._context.logger.info("pm_engine", f"[阶段3] Planner 判定: {spec_name}")
            # ── judge-rerun-stability R1：稳定性复用 + 重跑上限前置守卫 ──
            # 连续两轮 verdict 一致且 spec 戳/report.json 未变 → 复用上次结果
            # 不新起 judge run（叫停 add-web-ui 类 11 次空转重派）；judge run
            # 总数超上限（_MAX_JUDGE_RERUNS=5）→ blocked 转人工裁决。
            gate = self._judge_dispatch_gate(spec_name)
            if gate is False:
                return  # 硬上限：已 blocked 等待人工裁决
            if gate is None:
                judge_result = self._pm.agent_runner.run_planner(spec_name, "judge")
            else:
                judge_result = gate  # 稳定性复用合成结果

        if not judge_result.success:
            # ── 人工取消 hold-state（add-run-cancel D4，judge 同语义）──
            # judge run 被取消：spec 保持 testing 原状，只写 error。
            if getattr(judge_result, "cancelled", False):
                j_err = judge_result.error or ""
                cancelled_err = f"run 被人工取消：{j_err}" if j_err else "run 被人工取消"
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": cancelled_err,
                        # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                        "_cancelled_hold": True,
                    },
                )
                self._context.logger.warning(
                    "pm_engine",
                    f"Planner judge run 被人工取消 — hold-state '{spec_name}' "
                    f"(保持 testing): {cancelled_err}",
                )
                return
            # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
            # 同阶段1：熔断期 planner judge 失败属「provider 故障」，
            # 不得 raise → legacy 降级 → bug-found → 伪 fix 级联。
            if judge_result.error and "provider circuit open" in judge_result.error:
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": judge_result.error,
                    },
                )
                # evo-infra-failure-budget-exempt R2：judge 熔断同属 infra，
                # 归因入口前早退点挂预算退款与记账（与阶段1 circuit-open 同款）。
                self._record_infra_failure(
                    spec_name,
                    judge_result.error,
                    run_id=getattr(judge_result, "run_id", "") or "",
                )
                self._context.logger.warning(
                    "pm_engine",
                    f"Provider circuit open — planner judge suppressed for "
                    f"'{spec_name}', holding implemented: {judge_result.error}",
                )
                return
            # ── 首轮 frozen 让位分支（fix-verdict-retry-misattribution D4）──
            # judge 首次派发于冻结前、run 在飞期间 spec 被人工冻结、run 完成返回
            # frozen 失败：与 cancelled「保持 testing 只写 error」及 circuit-open
            # 「抑制」同型——INFO 留痕后静默退出，不 raise、不重派、不改状态。
            # 判据与 runner.py 派发门共用导出常量（design D3 文案同源）。
            if (judge_result.error or "").startswith(FROZEN_TERMINATED_ERROR_PREFIX):
                self._context.logger.info(
                    "pm_engine",
                    f"Planner judge run 完成时 spec 已冻结 — 让位退出 '{spec_name}'"
                    f"（在飞 run 结果按 frozen 处置，不重派不改状态）: "
                    f"{judge_result.error}",
                )
                return
            raise RuntimeError(f"Planner judge 失败: {judge_result.error}")

        # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
        # judge run 完成时刻再次核对 spec 状态：在飞旧 verify run 完成时若 spec
        # 已被重置（stale-result 防护拨回 implemented / 并发新 attempt 已接管），
        # 结果按 DEBUG 静默丢弃——不走失败迁移、不触发 fallback 重派整轮 verifier
        # （02:13 事故：implemented→verified 被拒后回退转 testing 重派）。
        _apply_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
        if _apply_status != "testing":
            self._context.logger.debug(
                "pm_engine",
                f"Stale/foreign verify result discarded for '{spec_name}' "
                f"(run {judge_result.run_id}, current state '{_apply_status}', "
                f"result verified) — spec no longer in testing, result dropped",
            )
            return

        # ── 阶段3+ 裁决证据分类校验与重试（add-verdict-evidence-taxonomy D1-D5；
        #    fix-verdict-retry-misattribution D1/D2/D5/D7）──
        # judge 已在 report.json 增强每个非 PASS 场景的 classification/evidence。
        # 此处确定性校验：不合规 → 走既有 judge 重试一次（同 run_planner 调用）；
        # 二次仍不合规 → cause=violations，blocked-env + 告警（与 verify-report-gate
        # 阻断语义一致，宁可不推进也不带病采纳）。重试派发被 frozen/取消拦截 =
        # 人工已接管 → 静默让位（零写入零告警）；派发失败/异常/产物丢失 → 温和
        # 处置不发 verdict_evidence_invalid。合规后按分类-状态映射强制重写 status（D3）。
        verdict_ret = self._verify_verdict_evidence(spec_name, retry_judge=True)
        if not verdict_ret["ok"]:
            cause = verdict_ret.get("cause", "violations")
            violations = verdict_ret.get("violations") or []
            dispatch_error = verdict_ret.get("dispatch_error") or ""
            if cause == "batch_attribution_dedup":
                # ── 批量归因查重拒绝采纳（fix-verdict-dedup-resynthesis D1/D2）──
                # 查重拒绝已由 _verify_verdict_evidence 内部完成「落盘违规 →
                # 派发重合成 judge → 回灌校验」闭环；本分支仅剩的语义是「重合成
                # 预算耗尽已升级 blocked」——_handle_attr_dedup_rejection 已置
                # blocked + admin 告警，此处仅 WARNING 对账，不重复写 error。
                # report.json 实际已在盘上（judge 自己写的），拒绝的是状态机
                # 采纳而非落盘——不再「保持 testing 静默等待」（170 分钟自锁
                # 与全量重跑罚金的根因已消除）。
                detail = violations[0].get("reason") if violations else ""
                self._context.logger.warning(
                    "pm_engine",
                    f"批量归因查重拒绝采纳 '{spec_name}'（重合成预算耗尽）— "
                    f"已 blocked 等待人工裁决: {detail}",
                )
                return
            if cause in ("dispatch_frozen", "dispatch_cancelled"):
                # ── 让位语义（design D2 / fix-verdict-retry-misattribution）──
                # frozen 门/取消旗标 = 人工已接管：零写入（不 update_spec——不写
                # status/error、不触 _cancelled_hold）、不发任何人工升级告警；
                # 留痕已在上游方法内以 INFO 完成，此处补充采纳侧结论供日志对账。
                self._context.logger.info(
                    "pm_engine",
                    f"裁决证据校验重试派发被"
                    f"{'取消旗标' if cause == 'dispatch_cancelled' else 'frozen 门'}"
                    f"拦截 '{spec_name}' — 让位：spec 保持 testing 原状，"
                    f"不写 blocked、不发告警（cause={cause}）",
                )
                return
            if cause == "dispatch_failed":
                # ── 派发故障温和处置（design D1）──
                # 网关拒绝/预算闸门等：写 error 留痕但不动 status、不写 blocked、
                # 不发 verdict_evidence_invalid（「二次违反证据契约」语义不得被
                # 派发故障冒用）；spec 保持 testing 等待下轮重验。
                self._context.logger.warning(
                    "pm_engine",
                    f"裁决重试 judge 派发失败 '{spec_name}' — 保持 testing，"
                    f"留 error 待下轮重验: {dispatch_error}",
                )
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": f"裁决重试 judge 派发失败（非证据不合规）：{dispatch_error}",
                    },
                )
                return
            if cause == "dispatch_exception":
                # ── 异常早退（design D1 / D7）──
                # 上游已确保不复读旧 report.json、不打「重试后仍不合规」；此处
                # 同样不按违规处置——留 error 保持 testing，异常多属瞬态。
                self._context.logger.error(
                    "pm_engine",
                    f"裁决证据校验重试异常早退 '{spec_name}' — 保持 testing，"
                    f"留 error 待下轮重验: {dispatch_error}",
                )
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": (
                            f"裁决重试 judge 异常（非证据不合规，未复检旧产物）："
                            f"{dispatch_error}"
                        ),
                    },
                )
                return
            if cause == "report_missing":
                # ── 重试成功但产物不可读（design D1）──
                # fail-closed：无法确定性校验合规即不推进，阻断交人工；信号沿用
                # 裁决结果不可读通道，不发 verdict_evidence_invalid（非违规判定）。
                self._context.logger.error(
                    "pm_engine",
                    f"裁决重试 judge 成功但 report.json 不可读 '{spec_name}' — "
                    f"阻断为 blocked（fail-closed，不按违规处置）",
                )
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "blocked",
                        "error": (
                            f"验证裁决重试后 report.json 不可读（产物缺失，非证据不合规），"
                            f"已 blocked 等待人工裁决"
                        ),
                    },
                )
                self._context.escalation_notifier(
                    spec_name=spec_name,
                    signal_type="verdict_result_unreadable",
                    severity="critical",
                    description=(
                        f"'{spec_name}' 裁决重试后 report.json 不可读，已 blocked "
                        f"等待人工裁决（非证据不合规）"
                    ),
                    evidence=(
                        f"spec={spec_name}; cause=report_missing; report="
                        f".fenix/verify-progress/{spec_name}/report.json"
                    ),
                    recommended_action=(
                        "检查 judge 重试轮是否覆写/破坏了 report.json（产物门禁外的"
                        "缺失路径）；修复产物后重置验证或重跑"
                    ),
                )
                return
            if cause != "violations":
                # ── 未知 cause 保守处置（design risk：fail-closed）──
                # 前向兼容防护：枚举之外的 cause 值按 violations 同等保守处置
                # （blocked + 告警），并 ERROR 留痕——不静默放行。
                self._context.logger.error(
                    "pm_engine",
                    f"裁决证据校验未知 cause '{cause}' '{spec_name}' — 按 violations "
                    f"保守处置（fail-closed）: {verdict_ret}",
                )
            # ── cause=violations（真·二次违规）：保留既有语义 blocked + 告警 ──
            # 本轮回合计入失败历史侧车（cause_type=evidence-invalid），供升级闸门
            # 分型与轮间 diff（fix-verdict-retry-misattribution D6）。
            self._append_fail_history(
                spec_name,
                "evidence-invalid",
                [
                    v.get("scenario_id") or v.get("id") or "?"
                    for v in violations
                    if isinstance(v, dict)
                ],
            )
            self._context.logger.error(
                "pm_engine",
                f"裁决证据分类二次校验仍失败 '{spec_name}' — 阻断推进为 blocked-env"
                f"（{len(violations)} 项违规）",
            )
            self._context.state_machine.update_spec(
                spec_name,
                {
                    "status": "blocked",
                    "error": (
                        f"验证裁决证据分类校验连续失败：report.json 非 PASS 场景缺 "
                        f"classification/evidence，重试一次仍不合规（{len(violations)} 项"
                        f"违规），已 blocked 等待人工裁决"
                    ),
                },
            )
            self._context.escalation_notifier(
                spec_name=spec_name,
                signal_type="verdict_evidence_invalid",
                severity="critical",
                description=(
                    f"'{spec_name}' 验证裁决证据分类校验连续失败（{len(violations)} 项"
                    f"违规），已 blocked 等待人工裁决"
                ),
                evidence=self._verdict_violations_evidence(spec_name, violations),
                recommended_action=(
                    "检查 planner-judge 是否遵守 prompt 第4步（对全部非 PASS 场景补 "
                    "classification/evidence）；人工重置后重跑验证"
                ),
            )
            return

        # ── 阶段3+ warning 连续悬置追踪与升级（design D4 / D5）──
        # 裁决采纳处更新连续计数侧车；达 2 轮的 warning 场景发 triage 升级告警，
        # 并写入下一轮 planner prompt 的优先复核清单（triage_recheck.json）。
        try:
            triage_hits = self._update_warning_streaks(spec_name)
            if triage_hits:
                self._warning_stale_triage_alert(spec_name, triage_hits)
        except Exception as e:
            self._context.logger.warning(
                "pm_engine",
                f"warning_streaks 更新跳过（异常不阻断采纳）'{spec_name}': {e}",
            )

        # 读取判定结果（fix-verdict-read-failclosed：结构化三态；
        # evo-verifier-result-single-source R1：统一走 _read_verdict 入口，
        # 主树共享回退须过 role/spec 戳校验——implementer 残留不采信）
        verifier_result = self._read_verdict(spec_name)
        verifier_status = verifier_result.status if verifier_result.ok else None
        # ── 结果状态判据（fix-daemon-lifecycle-races D6，结果应用处最终核对）──
        # 前道守卫之后的取证校验/重试窗口内 spec 亦可能漂移，此处兜底：非 testing
        # → DEBUG 丢弃，不迁移/不派生/不重派。
        _apply_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
        if _apply_status != "testing":
            self._context.logger.debug(
                "pm_engine",
                f"Stale/foreign verify result discarded for '{spec_name}' "
                f"(current state '{_apply_status}', result {verifier_status}) — "
                f"spec no longer in testing, result dropped",
            )
            return
        # ── 裁决不可读 → fail-closed（fix-verdict-read-failclosed D4）──
        # 结果文件缺失/非法 JSON/status 白名单外一律不得晋级 verified（历史事故：
        # add-verify-contract-autodraft 裸换行非法 JSON → None → else 分支 →
        # verified → done → auto-push）。处置：重派 judge 一次 → 复读；二次仍不可读
        # → blocked + critical 告警（含解析错误原文与结果文件完整路径），不推进
        # bug-found、不派生 fix。重试前复用入口状态判据（非 testing 丢弃，与
        # stale-result 防护同构，不新增竞态面）。
        if not verifier_result.ok:
            verdict_result_path = (
                self._context.project_root
                / ".fenix"
                / "verify-progress"
                / spec_name
                / ".fenix-run-result.json"
            )
            retry_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
            if retry_status == "testing":
                self._context.logger.warning(
                    "pm_engine",
                    f"裁决结果不可读 '{spec_name}'（reason={verifier_result.reason}）"
                    f"— 重派 judge 一次后复读: {verifier_result.detail}",
                )
                retry_judge = self._pm.agent_runner.run_planner(spec_name, "judge")
                if retry_judge.success:
                    verifier_result = self._read_verdict(spec_name)
                    verifier_status = verifier_result.status if verifier_result.ok else None
            if not verifier_result.ok:
                self._context.logger.error(
                    "pm_engine",
                    f"裁决结果二次仍不可读 '{spec_name}' — 阻断为 blocked"
                    f"（reason={verifier_result.reason}）: {verifier_result.detail}",
                )
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "blocked",
                        "error": (
                            f"验证裁决结果文件不可读（重派 judge 一次后仍不可读，"
                            f"reason={verifier_result.reason}）：{verifier_result.detail}"
                        ),
                    },
                )
                self._context.escalation_notifier(
                    spec_name=spec_name,
                    signal_type="verdict_result_unreadable",
                    severity="critical",
                    description=(
                        f"'{spec_name}' 验证裁决结果文件不可读，已 blocked 等待人工裁决"
                        f"（reason={verifier_result.reason}）"
                    ),
                    evidence=(
                        f"spec={spec_name}; result_file={verdict_result_path}; "
                        f"parse_error={verifier_result.detail}"
                    ),
                    recommended_action=(
                        "检查 planner-judge 是否以合法 JSON 写入结果文件（字符串内换行/"
                        "引号/控制字符须转义，建议以代码 json.dump 生成而非手工拼接）；"
                        "修复文件后重置验证或重跑"
                    ),
                )
                return
        # ── 阶段3+ 场景原地修复通道（judge-scenario-repair）──
        # 测试场景文件自身也可能有缺陷（夹具未自建/步骤客观错误/依赖序缺失）。
        # judge 原地修复场景文件并申报 scenario-repaired：框架经冻结 diff 记账
        # （无理由移除会被确定性补齐——judge 无法靠删场景凑通过）后有界重入
        # 阶段2/3——serving 实例在同函数缓存中存续，重执行秒级。与既有通道
        # 分工：机械缺陷原地修（省一次完整出题）；覆盖级缺陷走交互契约退回
        # plan；测试 harness 代码缺陷走 bug-found fix 链。
        if verifier_status == "scenario-repaired":
            if _repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS:
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": (
                            f"judge 场景原地修复预算耗尽（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮）"
                            f"— 保持 testing 等待下一轮重验，若仍场景缺陷将按既有升级路径处置"
                        ),
                    },
                )
                self._context.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' judge 场景修复预算耗尽 "
                    f"（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮）— 不再重入",
                )
                return
            try:
                freeze_result = self._apply_scenario_freeze(spec_name)
            except Exception as e:
                # 冻结记账属辅助治理，异常不阻断修复重入
                self._context.logger.warning(
                    "pm_engine",
                    f"修复轮场景冻结记账跳过 '{spec_name}'（异常不阻断）: {e}",
                )
                freeze_result = None
            if isinstance(freeze_result, dict) and freeze_result.get("aborted"):
                # ── 空集显式兜底（evo-planner-scenario-schema-alignment 3.7）──
                # judge 原地修复后场景集为空（写前预校验整批拒绝）：MUST 拒绝
                # 本次重入、保持原状并留痕，MUST NOT 以空集或未过滤文件继续
                # 进入阶段2（0 场景报告会被洗白门 fail-open 放行判 verified）。
                reject_detail = "、".join(freeze_result.get("rejected") or [])[:400]
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": (
                            f"judge 原地修复后场景集为空（写前预校验整批拒绝，共 "
                            f"{freeze_result.get('total', 0)} 条）— 拒绝本次重入，"
                            f"保持 testing 待人工/下轮处置: {reject_detail}"
                        ),
                    },
                )
                self._context.logger.error(
                    "pm_engine",
                    f"judge 场景修复后无合法场景 '{spec_name}' — 拒绝重入，"
                    f"0 场景不进入阶段2: {reject_detail}",
                )
                return
            self._context.logger.info(
                "pm_engine",
                f"[阶段3+] judge 场景原地修复采纳 '{spec_name}' — 重入执行"
                f"（第 {_repair_depth + 1}/{_SCENARIO_REPAIR_MAX_ROUNDS} 次修复）",
            )
            return self._run_three_stage_verification(spec_name, _repair_depth=_repair_depth + 1)
        if verifier_status == "bug-found":
            # ── 归因分级门禁（add-verdict-credibility-gate / design D2 / Task 2.2）──
            # 打回依据全部为 speculative（推测级）时抑制 bug-found 打回：
            # 转重验一次或写 error「归因证据不足待人工复核」，不得带推测
            # 信号打回 implementer（B2/B7：宁可多一次重验也不可带假信号打回，
            # 本次事故直接教训）。
            if self._speculative_bug_found_gate(spec_name):
                return
            # judge 自述环境问题守卫：judge 自己把根因描述为环境/基础设施问题时，
            # 属「验证没能发生」而非「验证发现了缺陷」，不得流转 bug-found
            # 派生伪 fix 级联（admin 处置 2026-08-28 failover 相对 URL 伪失败实证）。
            if self._judge_bugs_declare_env(spec_name) and self._handle_judge_env_declared(
                spec_name
            ):
                return
            # ── 场景缺陷改道门（add-scenario-defect-triage-gate D1/D2/D3）──
            # judge 申报 bug-found 后、打回 implementer 前，读 report.json 场景
            # classification 分布：非 PASS 场景全部显式 test-defect/flaky 且
            # product-bug=0 → 纯场景缺陷清单，拒绝打回 implementer（不再烧实现轮
            # 修场景文件——add-spec-status-modal-budget 事故的直接教训），定向重派
            # judge 一次走 scenario-repaired 原地修复通道。None/未知值/含任一
            # product-bug 一律不走改道（保守，D1）。重派计入 _SCENARIO_REPAIR_
            # MAX_ROUNDS 预算（与 scenario-repaired 重入共用 _repair_depth）。
            if self._scenario_defect_reroute_gate(spec_name, _repair_depth, judge_result):
                return
            # 验证报告产物闸门（add-verify-report-gate）：裁决 Agent 漏写报告时
            # 由框架合成兜底，合成失败则阻断推进（下游修复引用的路径必然可读）
            report_blocker = self._ensure_verification_report(spec_name)
            if report_blocker:
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": report_blocker,
                    },
                )
                self._context.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止推进 bug-found — {report_blocker}",
                )
                return
            # ── verified 一次性放行门（judge-rerun-stability R2）──
            # 已 verified 且场景集未变 → 拒绝降级为 bug-found（人工 reset
            # 回 testing 后 legacy/planner 误判防护；与 D6 stale-result 防护
            # 正交共存——D6 处理非 testing 的 stale 丢弃，R2 处理 testing 内的
            # 历史 verified 防降级）。
            if self._verified_gate_refuses(spec_name, "bug-found"):
                return
            self._context.state_machine.transition(spec_name, "bug-found")
            self._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": judge_result.run_id,
                    "error": "Verification found bugs — see verification report",
                    # 明确非环境性失联：复位 inconclusive 计数（环境恢复后从零重算）
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：bug-found 属健康轮
                    # 判定（非 inconclusive），降档并行度同轮复位。
                    "_verify_parallel_override": None,
                },
            )
            # 裁决采纳后落盘 verdict 稳定性轮次（judge-rerun-stability R1）
            self._record_verdict_adoption(spec_name, "bug-found", report)
            # 本轮场景集变更小节追加到验证报告（spec 需求 2.3）
            self._render_scenario_change_section_to_report(spec_name)
            self._context.logger.warning(
                "pm_engine",
                f"Verifier found bugs in '{spec_name}', transitioning to bug-found",
            )
            # ── 守卫二：spawn 抑制（fix-repair-lane-dedup / design 守卫二）──
            # 被验对象为 fix spec 且自身 ready/implementing（重实现已在飞）时，
            # 跳过派生子 fix——由在飞重实现承载修复。
            if self._context.is_fix_spec(spec_name):
                cur = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
                if cur in ("ready", "implementing"):
                    self._context.logger.info(
                        "pm_engine",
                        f"守卫二：'{spec_name}' 为 fix spec 且自身 {cur}"
                        f"（重实现在飞）——跳过派生子 fix",
                    )
                    self._context.state_machine.update_spec(
                        spec_name,
                        {
                            "error": "修复由在飞重实现承载，跳过派生子 fix",
                        },
                    )
                    return
            # ── 统一失败归因入口（evo-infra-failure-budget-exempt R1/R3）──
            # 归因入口处调用 enrich_failure_class：三态分类后，product/unknown
            # 照常流转 bug-found（unknown 按 product 保守处置，照常累计
            # _verify_fail_rounds）；infra 兜底拦截（既有 infra 判定点已早退，
            # 此处为防御性兜底——如误入则按 infra 记账、不派生 fix）。
            failure_class = self.enrich_failure_class(
                spec_name,
                error_text=getattr(judge_result, "error", "") or "",
            )
            if failure_class == "infra":
                # 防御性兜底：归因入口误判 infra（不应发生，既有 infra 判定点
                # 已早退）——按 infra 记账（预算退款 + _verify_infra_rounds +
                # _infra_failure_count + 台账），不流转 bug-found、不派生 fix。
                self._context.logger.warning(
                    "pm_engine",
                    f"归因入口兜底：'{spec_name}' 判定 infra（误入 bug-found "
                    f"分支），按 infra 记账处理不派生 fix",
                )
                self._record_infra_failure(
                    spec_name,
                    "infra at attribution entry (fallback)",
                    run_id=getattr(judge_result, "run_id", "") or "",
                )
                return
            # 到达 bug-found 归因（全部门禁已过、非 infra）＝ product 类——
            # unknown 按 product 保守处置，台账 failure_class 记 product。
            self._context.on_spec_bug_found(
                spec_name,
                failure_class="product",
                run_id=getattr(judge_result, "run_id", "") or "",
            )
        else:
            # D6: testing→verified 前置进度核对：done>=total 才晋级
            vblocker = self._check_verification_gate(spec_name)
            if vblocker:
                # 不完整：按 verifier 失败处理，写 error 摘要，不晋级 verified
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "tester_run": judge_result.run_id,
                        "error": vblocker,
                    },
                )
                self._context.logger.warning(
                    "pm_engine",
                    f"验证未完成 '{spec_name}'，阻止晋级 verified: {vblocker}",
                )
                return
            # 验证报告产物闸门（add-verify-report-gate）
            report_blocker = self._ensure_verification_report(spec_name)
            if report_blocker:
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "tester_run": judge_result.run_id,
                        "error": report_blocker,
                    },
                )
                self._context.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止晋级 verified — {report_blocker}",
                )
                return
            # verified 洗白门禁（help-center 0/15 verified 事故防线）：
            # 0 通过或 env 失败不得放行，升级 admin 处置
            if not self._env_whitewash_gate(spec_name):
                return
            self._context.state_machine.transition(spec_name, "verified")
            self._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": judge_result.run_id,
                    "error": None,
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：verified 属健康轮，
                    # 降档并行度同轮复位（与 _inconclusive_attempts 同生命周期）。
                    "_verify_parallel_override": None,
                    # add-fail-counter-budget D1：验证 PASS 是 _verify_fail_rounds
                    # 的唯一归零点——跨修复周期累计的失败计数在此清零并持久化，
                    # 打回重派/修复收工等中间转换不再归零（见 _do_spec_bug_found）。
                    "_verify_fail_rounds": 0,
                    # evo-infra-failure-budget-exempt R3：_verify_infra_rounds 与
                    # _verify_fail_rounds 同生命周期——验证 PASS 唯一归零点两处同写，
                    # 避免跨周期累计导致 dashboard 展示失真。
                    VERIFY_INFRA_ROUNDS_FIELD: 0,
                    # fix-daemon-lifecycle-races D3：验证自然通过（verified 落定）是
                    # _verify_redo_count（重启恢复重验计数）的清零点，与
                    # _verify_fail_rounds 清零点对齐；人工 unfreeze_spec 亦清零。
                    "_verify_redo_count": 0,
                    # add-blocked-reverify-lane D3：env 阻塞轮次唯一自动清零点=验证
                    # 通过（与 _verify_fail_rounds PASS 唯一归零点同语义）；处置复位/
                    # 恢复/fix 链等中间转换不清零。
                    ENV_BLOCK_ROUNDS_FIELD: 0,
                },
            )
            # 裁决采纳后落盘 verdict 稳定性轮次（judge-rerun-stability R1）
            self._record_verdict_adoption(spec_name, "verified", report)
            # 失败历史侧车随 verified 终态清空（fix-verdict-retry-misattribution D6）
            self._clear_fail_history(spec_name)
            # 本轮场景集变更小节追加到验证报告（spec 需求 2.3）
            self._render_scenario_change_section_to_report(spec_name)
            self._context.on_spec_verified(spec_name)


# ── env 阻塞复位判定（add-blocked-reverify-lane D2）────────────────
# 决定 env 阻塞 spec 在 admin 处置完成后走哪条复位路径：BLOCKED→TESTING 重验
# 直通道（实现分支已合并）还是既有 BLOCKED→READY 全量重实现。模块级函数（非
# VerificationPipeline 方法）：admin_monitor 处置收尾消费点直接 import 复用，
# 两处共享同一守卫判定，避免语义漂移。

# env 族信号类型：仅这些信号触发的 blocking 复位才适用重验直通道判定，其余
# 信号（如 blocked_stuck 等）的复位语义不动。
ENV_BLOCK_SIGNAL_TYPES = ("verify_env_blocked", "verify_env_inconclusive")

# git 合并判定超时（常量归属 branch_guard 组，此处 re-export）
from core.pm_engine.verification.branch_guard import ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS
