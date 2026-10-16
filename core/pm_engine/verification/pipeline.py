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
from datetime import datetime, timezone
import functools
import json
import re
import subprocess
import time

# judge-scenario-repair：judge 原地场景修复预算（_SCENARIO_REPAIR_MAX_ROUNDS）
# 单点定义见 core.state_machine（与 escalation.py 同源，防两侧调参漂移）。

# D9：`ensure_main_tree_deps` / `run_prepare_steps` / `load_verify_contract` /
# `rewrite_scenarios_origin` 不再在此模块顶层绑定——调用点经包命名空间
# （`import core.pm_engine.verification as _facade`）延迟解析，使
# `patch("core.pm_engine.verification.<name>")` 语义保持（见 __init__.py）。
# 本模块不再从 verify_contract 顶层绑定任何名字（此前的 5 个服务器/依赖
# 名为单体拆分遗留死导入，已移除）。

# fix-verdict-read-failclosed D3：与 runner 产物硬门共用同一 status 白名单单一来源
# （prompt_builder 定义、两侧 import，避免双实现漂移）。
# fix-verdict-read-failclosed D3：PLANNER_RESULT_STATUS_WHITELIST 随裁决读取
# 迁至 report_gate.py（verification/report_gate.py 消费）。
# fix-verdict-retry-misattribution D3：frozen 门 error 文案与 runner.py 派发门共用
# 同一导出常量（防文案改动使匹配失效），取消判定沿用 AgentRunResult.cancelled 结构化
# 字段（非字符串匹配）。
from core.agent_runner.runner import FROZEN_TERMINATED_ERROR_PREFIX

# code-review item 17e5cb41806e：provider 熔断判定文案与生产源
# （provider_circuit._circuit_open_error）共用同一导出常量（与上方
# FROZEN_TERMINATED_ERROR_PREFIX 同一约定，防 provider_circuit 侧措辞
# 调整使本文件多处子串匹配静默失效、熔断轮误走 blocked fail-closed）。
from core.agent_runner.provider_circuit import PROVIDER_CIRCUIT_ERROR_MARKER

# code-review item b3d583fb6c4f：应用不可达门禁写入 tester_run 的伪标记（非真实
# run_id）。消费方口径已核（2026-10）：event_bus._recover_testing 有意不按
# tester_run 硬挡（docstring 明示本标记形态）；event_bus implemented 分支 /
# family / queue 仅做 truthy 判空或置 None 清锚；dashboard summary 原样透传、
# 前端无消费（无按值关联 AgentRun 或链接渲染）；state_machine.transition 的
# trigger_run_id 仅作流水留痕不回查 run。下游若新增「按 tester_run 关联
# AgentRun / 渲染链接」逻辑，须按本常量值豁免。
TESTER_RUN_BLOCKED_APP_UNREACHABLE = "blocked:app-unreachable"

from core.timelib import from_epoch

# add-blocked-reverify-lane D3：env 阻塞轮次计数清零点收敛后与 state_machine
# 共用同一字段常量（防字符串漂移；唯一清零点=verified 落定与 unfreeze_spec）。
from core.state_machine import (
    ENV_BLOCK_ROUNDS_FIELD,
    FREEZE_ERROR_PREFIX,
    VERIFY_INFRA_ROUNDS_FIELD,
    VERIFY_INFRA_RETRY_STREAK_FIELD,
    SCENARIO_REPAIR_EXHAUSTED_FIELD,
    # env 豁免 STATE 字段/修订生命周期字段单源（evo-fix-env-exemption-gate-
    # conflict-and-scenario-revision-exit：与 admin_actions/escalation 同源）
    ENV_EXEMPTIONS_FIELD,
    SCENARIO_REVISION_PENDING_FIELD,
    # judge-scenario-repair：修复预算单点定义在 state_machine（与 escalation.py 同源）
    _SCENARIO_REPAIR_MAX_ROUNDS,
)

# refactor-verification-module 阶段3.3：infra 失败归因/历史/回拨组已迁 infra_classify.py。
# reclassify_infra_rounds 由 verification/__init__ 从 infra_classify 再导出，门面
# 不保留类内委托（消费方走 engine.py 同名方法）。
from core.pm_engine.verification.infra_classify import (
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
)

# refactor-verification-module 阶段3.4：场景冻结/交互契约/静态检查组已迁 scenario_gate.py，
# 7 个方法以薄委托保留在门面（见类内同名方法）。
from core.pm_engine.verification.scenario_gate import (
    _apply_interaction_contract,
    _apply_scenario_freeze,
    _render_scenario_change_section_to_report,
    _run_contract_static_check,
    _run_scenario_static_check,
    _write_verify_contract_missing,
    atomic_write_text,
)

# add-pipeline-throughput-governance 4.x：bug-found 小缺陷 fastlane（三条件判定
# /code-fix 承接/子集重验）独立模块，经门面转发注册表暴露为管线方法。
from core.pm_engine.verification.fastlane import (
    evaluate_fastlane,
    dispatch_minor_defect_fastlane,
    fastlane_decision_path,
    FASTLANE_STREAK_FIELD,
)

# refactor-verification-module 阶段3.6：judge 派发门/重跑上限/降级上下文组已迁 judge_gate.py，
# 8 个方法与 _MAX_JUDGE_RERUNS 常量以薄委托保留在门面（见类内同名方法）。
from core.pm_engine.verification.judge_gate import (
    _MAX_JUDGE_RERUNS,
    _all_green_fast_path,
    _clear_degrade_context,
    _judge_charge_verdict_retry,
    _judge_dispatch_gate,
    _judge_hard_cap_freeze,
    _judge_rerun_count,
    _last_planner_cost_usd,
    _last_planner_run_cost,
    _write_degrade_context,
)

def _parallel_plan_scenario_def(sc) -> dict:
    """场景元素 → 定义视图 dict（add-verify-lane-throughput 4.2 内部助手）。

    生产路径场景元素是 ``load_scenarios`` 产出的 TestScenario 对象（属性访问
    、``to_dict()`` 序列化），dict 仅见于测试/合成路径。裁剪与合成只读定义
    字段（id/description/depends_on）作指纹与出处判定，本助手把两种形态归一
    为 dict 视图；非法元素返回 {}（调用方按未标记处理，fail-closed 照跑）。
    """
    if isinstance(sc, dict):
        return sc
    to_dict = getattr(sc, "to_dict", None)
    if callable(to_dict):
        try:
            d = to_dict()
            return d if isinstance(d, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


# 场景定义视图 → sid 的无 id 兜底常量（code-review item b81fe155c73b）：裁剪侧
# （_prune_rescan_scenarios 的缓存键/执行集标识）与合成侧
# （_merge_cached_scenario_results 的排序查表）此前各写一份兜底（"#{i}" vs ""），
# 同一无 id 场景两处键不同、报告顺序与裁剪决策可能错位——收敛本助手单点维护。
_SCENARIO_SID_FALLBACK_FMT = "#{i}"


def _parallel_plan_scenario_sid(d: dict, index: int) -> str:
    """场景定义视图 → sid（裁剪缓存键与合成排序共用的单源口径）。

    scenario_id 缺省回退 id，两者皆缺回退位置标识 ``#{index}``（裸 str(None)
    会生成字面量 "None" 键，可写盘但永不被消费侧命中）。两侧调用点遍历的是
    同一 full 场景列表、枚举序一致，位置兜底因此可对位。
    """
    return str(
        d.get("scenario_id") or d.get("id") or _SCENARIO_SID_FALLBACK_FMT.format(i=index)
    )


# refactor-verification-module 阶段3.5：serving 工作树/实例/端口组已迁 serving.py，
# 18 个方法以薄委托保留在门面（见类内同名方法）。
from core.pm_engine.verification.serving import (
    _current_instance_base_url,
    _current_verify_round,
    _dist_probe_block_report,
    _ensure_app_reachable,
    _ensure_serving_worktree,
    _evict_spec_serving,
    _finalize_static,
    _open_boot_log,
    _port_responds,
    _probe_dist_freshness,
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
    _clear_inconclusive_reverify_flag,
    _env_whitewash_gate,
    _escalate_env_blocked,
    _escalate_scenario_defect_reroute,
    _escalate_scenario_repair_exhausted,
    _handle_env_blocked_inconclusive,
    _handle_env_exemption_handshake,
    _handle_judge_env_declared,
    _handle_verdict_env_exemption_inconclusive,
    _judge_bugs_declare_env,
    _schedule_scenario_repair_reverify,
    _SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS,
    _scenario_defect_reroute_gate,
    _speculative_bug_found_gate,
    _update_warning_streaks,
    _verdict_env_exemption_level2,
    _warning_stale_triage_alert,
    _write_inconclusive_loop_signal,
)
from core.pm_engine.verification.legacy import (
    _discard_if_not_testing,
    _run_legacy_verification,
)
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

# 常量归属 branch_guard 组，此处 re-export（code-review item c852ab20c86e：
# 自文件末尾上移至顶部 import 区与 serving 常量同址集中，末尾只留模块级
# 常量定义）
from core.pm_engine.verification.branch_guard import ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS


# ── 冻结场景损坏升级文案单源（code-review item 928d8348a5be）────────────
def _corrupt_freeze_options(
    spec_name: str, extra: str = "", reason: str = "冻结场景文件损坏或验收失败"
) -> str:
    """「冻结场景文件损坏或验收失败」处置选项文案（_load_frozen_or_escalate
    五个升级点复用单源，防内联复制漂移）；extra 拼接在②之后的附加条目
    （如迁移轮的第③条回退指引）；reason 为首句原因（code-review item
    a81f30195697：空集分支以「冻结场景文件为空（无任何场景）」复用同一
    ①②选项单源，防内联副本漂移）。
    """
    return (
        f"{reason}。处置选项：① 确认场景集已过时 → "
        f"删除 .fenix/verify-progress/{spec_name}/test_scenarios.json "
        "批准重新出题；② 文件可修复 → 修复后保持冻结。" + extra
    )


# ── 场景修订 re-entry（evo-fix-env-exemption-gate-conflict-… 2.2）────────
# 定义于 pipeline 门面（消费 pipeline._context 的 enqueue/state_machine/logger，
# 与其余 lifecycle 助手同范式），经下方绑定 dict 挂为 pipeline 方法供
# escalation 升级停车入口调用（pipeline._scenario_revision_reentry）。
def _scenario_revision_reentry(pipeline, spec_name: str) -> bool:
    """修订 re-entry 先于升级：场景修订待重验时先放行一次重验，不升级停车。

    ``revise_scenario_reverify`` 执行器落修订场景、置
    ``SCENARIO_REVISION_PENDING_FIELD`` 旗标并重入验证车道；若修订后首轮仍
    失败、再度到达升级停车入口（级二豁免握手停车），本守卫消费旗标并追加
    一次重验——给修订后的场景集一次收敛机会（修订 re-entry 先于升级）。
    旗标单次消费：追加轮再失败则正常升级停车（修订不无限续命）；verified
    落定与人工复位同样清旗标。

    Returns: True=已接管（调用方 MUST NOT 再停车/落 verdict）；False=无待
    重验修订（调用方按既有路径继续）。
    """
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    pending = str(entry.get(SCENARIO_REVISION_PENDING_FIELD) or "").strip().lower()
    if pending not in ("true", "1", "yes"):
        return False
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            SCENARIO_REVISION_PENDING_FIELD: False,
            "status": "implemented",
            "tester_run": None,
            "error": (
                "场景修订后重验仍未收敛：修订 re-entry 先于升级，"
                "追加一次重验（再失败将升级停车转人工）"
            ),
            "_in_inconclusive_reverify": True,
        },
    )
    pipeline._context.logger.warning(
        "pm_engine",
        f"'{spec_name}' 场景修订 re-entry 先于升级：消费待重验旗标，"
        f"追加一次重验",
    )
    pipeline._context.enqueue(spec_name, "verifier")
    return True


class VerificationPipeline:
    """验证流水线组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm, context: "PipelineContext | None" = None):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）
        # refactor-verification-module D1：显式依赖注入。context 可选——
        # 缺省时由 pm 推导（保持既有 VerificationPipeline(pm) 位置调用可用，
        # 任务 1.8 构造签名兼容基线）。注入后经 context 访问外部依赖，
        # MUST NOT 再直接回引 self._pm.<private>。
        self._context = context if context is not None else PipelineContext.from_pm(pm)

    # ── 门面转发注册表（refactor-facade-delegation D2 / facade-inventory.md）──
    # 实例式转发（85 个）：{门面方法名: 模块级函数}，函数以 pipe（self）为首参。
    # 注册表以源码内联 dict 声明（静态可读），`__getattr__` 命中时返回
    # functools.partial(func, self)（不注入多余 self）。
    _FORWARDER_REGISTRY: dict[str, object] = {
        "_read_verify_report": _read_verify_report,
        "_ensure_verification_report": _ensure_verification_report,
        "_check_verification_gate": _check_verification_gate,
        "_verifier_result_is_stale": _verifier_result_is_stale,
        "_read_verifier_result": _read_verifier_result,
        "_read_planner_result": _read_planner_result,
        "_read_verdict": _read_verdict,
        "_branch_commit_count": _branch_commit_count,
        "_implementation_branch_has_commits": _implementation_branch_has_commits,
        "_implementer_zero_change": _implementer_zero_change,
        "_deliverable_gate_missing": _deliverable_gate_missing,
        "_tasks_md_relint_from_branch": _tasks_md_relint_from_branch,
        "_tasks_md_relint_from_worktree": _tasks_md_relint_from_worktree,
        "_disputed_deliverables": _disputed_deliverables,
        "_verifier_error_is_infra": _verifier_error_is_infra,
        "enrich_failure_class": enrich_failure_class,
        "_record_infra_failure": _record_infra_failure,
        "_detect_uniform_verify_failure": _detect_uniform_verify_failure,
        "_fail_history_path": _fail_history_path,
        "_read_fail_history": _read_fail_history,
        "_append_fail_history": _append_fail_history,
        "_clear_fail_history": _clear_fail_history,
        "_scenario_classification_distribution": _scenario_classification_distribution,
        "_failed_scenario_ids": _failed_scenario_ids,
        "_apply_scenario_freeze": _apply_scenario_freeze,
        "_apply_interaction_contract": _apply_interaction_contract,
        "_render_scenario_change_section_to_report": _render_scenario_change_section_to_report,
        "_write_verify_contract_missing": _write_verify_contract_missing,
        "_run_scenario_static_check": _run_scenario_static_check,
        "_run_contract_static_check": _run_contract_static_check,
        "_ensure_serving_worktree": _ensure_serving_worktree,
        "_serve_static_in_main": _serve_static_in_main,
        "_serve_static_in_worktree": _serve_static_in_worktree,
        "_serve_command_in_worktree": _serve_command_in_worktree,
        "_serve_command_in_main": _serve_command_in_main,
        "_finalize_static": _finalize_static,
        "_remove_serving_worktree": _remove_serving_worktree,
        "_register_serving_instance": _register_serving_instance,
        "_unregister_serving_instance": _unregister_serving_instance,
        "_evict_spec_serving": _evict_spec_serving,
        "_current_instance_base_url": _current_instance_base_url,
        "_ensure_app_reachable": _ensure_app_reachable,
        "_open_boot_log": _open_boot_log,
        "_read_boot_log_tail": _read_boot_log_tail,
        "_rewrite_scenario_port": _rewrite_scenario_port,
        "_serving_port_for_spec": _serving_port_for_spec,
        "_current_verify_round": _current_verify_round,
        "_handle_env_blocked_inconclusive": _handle_env_blocked_inconclusive,
        "_write_inconclusive_loop_signal": _write_inconclusive_loop_signal,
        # fix-env-exemption-exit-reachability D3：inconclusive 重验旗标单一
        # 清除助手（judge 非全 env 结论三处路由点共用）
        "_clear_inconclusive_reverify_flag": _clear_inconclusive_reverify_flag,
        "_env_whitewash_gate": _env_whitewash_gate,
        "_escalate_env_blocked": _escalate_env_blocked,
        # fix-verdict-env-exemption-handshake：裁决豁免握手（级二判据/同源
        # inconclusive 处置/尾段拦截）与 serving dist 新鲜度探针
        "_verdict_env_exemption_level2": _verdict_env_exemption_level2,
        "_handle_verdict_env_exemption_inconclusive": (
            _handle_verdict_env_exemption_inconclusive
        ),
        "_handle_env_exemption_handshake": _handle_env_exemption_handshake,
        # evo-fix-env-exemption-gate-conflict-… 2.2：场景修订 re-entry 先于
        # 升级（升级停车入口消费待重验旗标）
        "_scenario_revision_reentry": _scenario_revision_reentry,
        "_probe_dist_freshness": _probe_dist_freshness,
        "_dist_probe_block_report": _dist_probe_block_report,
        "_update_warning_streaks": _update_warning_streaks,
        "_warning_stale_triage_alert": _warning_stale_triage_alert,
        "_scenario_defect_reroute_gate": _scenario_defect_reroute_gate,
        "_escalate_scenario_defect_reroute": _escalate_scenario_defect_reroute,
        "_handle_judge_env_declared": _handle_judge_env_declared,
        "_judge_bugs_declare_env": _judge_bugs_declare_env,
        "_speculative_bug_found_gate": _speculative_bug_found_gate,
        "_run_legacy_verification": _run_legacy_verification,
        "_verify_verdict_evidence": _verify_verdict_evidence,
        "_verdict_violations_evidence": _verdict_violations_evidence,
        "_write_verdict_violations": _write_verdict_violations,
        "_clear_verdict_violations": _clear_verdict_violations,
        "_verdict_violations_path": _verdict_violations_path,
        "_resynthesis_directive_path": _resynthesis_directive_path,
        "_read_resynthesis_directive": _read_resynthesis_directive,
        "_clear_resynthesis_directive": _clear_resynthesis_directive,
        "_resynthesis_directive_scenarios": _resynthesis_directive_scenarios,
        "_write_resynthesis_directive": _write_resynthesis_directive,
        "_escalate_dedup_resynthesis": _escalate_dedup_resynthesis,
        "_handle_attr_dedup_rejection": _handle_attr_dedup_rejection,
        "_handle_scenario_requeue": _handle_scenario_requeue,
        "_clear_requeue_manifest": _clear_requeue_manifest,
        "_record_verdict_adoption": _record_verdict_adoption,
        "_persist_verdict_cache": _persist_verdict_cache,
        "_verified_verdict_persisted": _verified_verdict_persisted,
        "_verified_gate_refuses": _verified_gate_refuses,
        "_judge_charge_verdict_retry": _judge_charge_verdict_retry,
        "_judge_dispatch_gate": _judge_dispatch_gate,
        "_judge_hard_cap_freeze": _judge_hard_cap_freeze,
        "_judge_rerun_count": _judge_rerun_count,
        "_all_green_fast_path": _all_green_fast_path,
        "_last_planner_cost_usd": _last_planner_cost_usd,
        "_last_planner_run_cost": _last_planner_run_cost,
        "_write_degrade_context": _write_degrade_context,
        "_clear_degrade_context": _clear_degrade_context,
        # add-pipeline-throughput-governance 4.x：bug-found 小缺陷 fastlane
        "_evaluate_fastlane": evaluate_fastlane,
        "_dispatch_minor_defect_fastlane": dispatch_minor_defect_fastlane,
        "_fastlane_decision_path": fastlane_decision_path,
    }

    # 静态式转发（5 个，首参非 pipe）：MUST NOT 进入 _FORWARDER_REGISTRY——
    # partial(func, self) 对无 self 首参函数会多注一个 self 直接 TypeError；
    # 以类级别名（staticmethod 别名）保留 `Cls.<名>` 与 `self.<名>` 两条解析路径
    # （design D7）。

    def __getattr__(self, name: str):
        """懒惰兜底：既有测试以 `VerificationPipeline.__new__` 部分构造（只设
        `_pm`，绕过 `__init__`），首次访问 `_context` 时由 `_pm` 推导并缓存，
        保持「测试零修改」约束（design D10：context 由 pm 内部推导亦成立）。

        增量扩展（refactor-facade-delegation D2）：`_context` 分支优先；
        未命中时查询门面转发注册表，返回 partial(func, self)；未知名
        MUST `raise AttributeError`（hasattr/getattr(..., default) 语义正确）。"""
        if name == "_context":
            ctx = PipelineContext.from_pm(self._pm)
            self._context = ctx
            return ctx
        func = type(self)._FORWARDER_REGISTRY.get(name)
        if func is not None:
            return functools.partial(func, self)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def __dir__(self):
        """IDE 补全增强（refactor-facade-delegation Open Question / tasks 5.1）：
        返回既有属性 + 注册表键，缓解 `__getattr__` 委托下 dir() 不显示转发名。"""
        return sorted(set(super().__dir__()) | set(type(self)._FORWARDER_REGISTRY))

    # ── report_gate 薄委托（refactor-verification-module D2b 规则 2：runner.py
    # 内部调用点 MUST 保持 self.<方法名> 形式，实现委托至模块级函数）──

    # ── branch_guard 薄委托（见 report_gate 注释 D2b 规则 2）──

    # D7 类级别名：取代 @staticmethod def 转发壳（无签名无 docstring，双份签名消除）
    _extract_replan_error_items = staticmethod(_bg_extract_replan_error_items)

    _replan_errors_unconsumed = staticmethod(_bg_replan_errors_unconsumed)

    # ── infra_classify 薄委托（见 report_gate 注释 D2b 规则 2）──

    _normalize_fail_signature = staticmethod(_normalize_fail_signature)

    # ── serving 薄委托（见 report_gate 注释 D2b 规则 2）──

    _port_responds = staticmethod(_port_responds)

    # ── escalation 薄委托 ──

    # ── legacy 薄委托 ──

    # ── verdict_evidence 薄委托 ──

    # ── judge_gate 薄委托（见 report_gate 注释 D2b 规则 2）──

    def _check_entry_status(self, spec_name: str) -> bool:
        """入口状态判据（fix-daemon-lifecycle-races D6）：非 testing 返回 False。

        返回 True 表示 spec 处于 testing，可继续本流水线；False 表示结果应丢弃
        （DEBUG 注明当前状态，不执行任何迁移/回退/派发）。覆盖 stale-result 防护
        拨回 implemented、并发双路径中先到者已推进、以及一切状态漂移变体。
        """
        _entry_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
        if _entry_status != "testing":
            self._context.logger.debug(
                "pm_engine",
                f"Verify result discarded for '{spec_name}': spec is "
                f"'{_entry_status}', not testing at pipeline entry — dropped",
            )
            return False
        return True

    def _reload_verify_engine_modules(self) -> None:
        """重新加载验证引擎模块，确保使用最新代码（D4：局部 import 留在函数体内）。

        fenixd 作为常驻进程运行，Python 会缓存已导入的模块，实现者更新代码后
        缓存不会自动失效，必须显式重新加载。注意：子模块必须先于父包重新加载
        （依赖顺序）。

        第二循环（fix-fix-fix-fix 遗留；表述修正见 code-review item
        bf4ff4bcf5f6）：对各模块再做一次 importlib.import_module——对
        sys.modules 中已存在的模块它只返回既有条目、绝不重读磁盘，因此
        **不具备**「reload 失败后从磁盘恢复」的能力；实际作用仅为失败可见性
        探测（import 失败记 WARNING）且幂等无副作用。reload 失败时 sys.modules
        留存旧代码属已知局限（上循环 WARNING 留痕「将沿用旧代码」）。测试靠
        patch("core.verify_engine.VerifyEngine") 生效正因 import 在函数体内于
        调用时执行——提取时 MUST 保留 import 于本方法体内（D4）。
        """
        import importlib
        import sys

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

        # 第二循环：失败可见性探测（code-review item bf4ff4bcf5f6 修正表述）。
        # import_module 对 sys.modules 已存在的模块只返回既有条目、不重读磁盘，
        # 此处**不能**恢复 reload 失败留存的旧代码（reload 失败已在上循环
        # WARNING 留痕）；作用仅为幂等探测 import 可用性，并对失败记 WARNING
        # 而非静默 pass。
        for mod_name in _verify_modules:
            try:
                # 条件放宽（code-review item eb64219d5fa8）：旧守卫 `not in sys.modules`
                # 使本循环永远无法恢复「importlib.reload 失败」的模块（失败的 reload
                # 会把旧条目留在 sys.modules 中），与方法 docstring 声称的「reload 后
                # 重导入」矛盾。改为对**所有**目标模块尝试 import_module（已存在则
                # 直接返回既有模块，幂等无副作用），并对失败记 WARNING 而非静默 pass
                # （静默会让调用方继续跑陈旧/半加载的引擎代码——正是本方法要防的形态）。
                importlib.import_module(mod_name)
            except Exception as e:
                self._context.logger.warning(
                    "pm_engine",
                    f"模块重导入失败 {mod_name}（继续，可能残留陈旧代码）: "
                    f"{type(e).__name__}: {e}",
                )

    def _handle_verdict_evidence_rejection(self, spec_name: str, verdict_ret: dict) -> None:
        """裁决证据分类校验失败处置（add-verdict-evidence-taxonomy D1-D5）。

        judge 已在 report.json 增强每个非 PASS 场景的 classification/evidence。
        此处确定性校验：不合规 → 走既有 judge 重试一次（同 run_planner 调用）；
        二次仍不合规 → cause=violations，blocked-env + 告警（与 verify-report-gate
        阻断语义一致，宁可不推进也不带病采纳）。重试派发被 frozen/取消拦截 =
        人工已接管 → 静默让位（零写入零告警）；派发失败/异常/产物丢失 → 温和
        处置不发 verdict_evidence_invalid。合规后按分类-状态映射强制重写 status（D3）。
        """
        cause = verdict_ret.get("cause", "violations")
        violations = verdict_ret.get("violations") or []
        dispatch_error = verdict_ret.get("dispatch_error") or ""
        if cause == "requeue_error":
            # ── 回炉闭环自身异常折算（code-review item 6d5db0d31b）──
            # _rejection_closure 处置自身异常（如 directive 计数字段损坏时
            # int() 抛 ValueError）折算为此独立 cause。异常发生在闭环内部，
            # _escalate_dedup_resynthesis 未到达——spec 既未 blocked 也无
            # admin 升级记录，仍停留 testing。此处按真实状态记日志对账
            # （不宣称「已 blocked」），零写入零告警，等下轮重验或 stuck
            # 探测兜底。
            self._context.logger.warning(
                "pm_engine",
                f"批量归因查重回炉闭环自身异常 '{spec_name}' — 未升级（spec 仍"
                f" testing，无 blocked/admin 升级记录），保持原状等待下轮重验: "
                f"{dispatch_error}",
            )
            return
        if cause == "batch_attribution_dedup":
            # ── 批量归因查重拒绝采纳（fix-verdict-dedup-resynthesis D1/D2）──
            # 查重拒绝已由 _verify_verdict_evidence 内部完成「落盘违规 →
            # 派发重合成 judge → 回灌校验」闭环；本分支仅剩的语义是「重合成
            # 预算耗尽已升级 blocked」——_handle_attr_dedup_rejection 已置
            # blocked + admin 告警，此处仅 WARNING 对账，不重复写 error。
            # report.json 实际已在盘上（judge 自己写的），拒绝的是状态机
            # 采纳而非落盘——不再「保持 testing 静默等待」（170 分钟自锁
            # 与全量重跑罚金的根因已消除）。
            # 元素形态非受控保证（code-review item 93d4fac73764）：与下方
            # 失败历史处同口径加 isinstance 守卫，非 dict 时降级为空串对账，
            # 不以 AttributeError 中断本分支。
            detail = (
                violations[0].get("reason")
                if isinstance(violations, list)
                and violations
                and isinstance(violations[0], dict)
                else ""
            )
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
            # 写 error 前二次核对（code-review item 0a515935ee9b）：重试派发
            # 距 _dispatch_judge_or_reuse 内 D6 检查可能已隔数分钟，窗口内
            # spec 被人工复位/冻结接管时该写点会覆写较新状态 error——非
            # testing 时 DEBUG 丢弃（与 report_missing 分支同口径）。
            _apply_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
            if _apply_status != "testing":
                self._context.logger.debug(
                    "pm_engine",
                    f"裁决重试 judge 派发失败但 spec 已非 testing（当前 "
                    f"'{_apply_status}'）'{spec_name}' — 丢弃，不写 error",
                )
                return
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
            # 写 error 前二次核对（code-review item 0a515935ee9b）：重试派发
            # 距 _dispatch_judge_or_reuse 内 D6 检查可能已隔数分钟，窗口内
            # spec 被人工复位/冻结接管时该写点会覆写较新状态 error——非
            # testing 时 DEBUG 丢弃（与 report_missing 分支同口径）。
            _apply_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
            if _apply_status != "testing":
                self._context.logger.debug(
                    "pm_engine",
                    f"裁决重试 judge 异常早退但 spec 已非 testing（当前 "
                    f"'{_apply_status}'）'{spec_name}' — 丢弃，不写 error",
                )
                return
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
            # 写 blocked 前二次核对（code-review item 5d28c6b0fe51）：judge 重试
            # 为长耗时操作，窗口内 spec 可能已被人工复位/冻结接管——非 testing
            # 时 DEBUG 丢弃，不覆盖较新状态（同入口 _apply_status 判据口径）。
            _apply_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
            if _apply_status != "testing":
                self._context.logger.debug(
                    "pm_engine",
                    f"裁决重试产物不可读但 spec 已非 testing（当前 "
                    f"'{_apply_status}'）'{spec_name}' — 丢弃，不阻断",
                )
                return
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
            # 告警通道自身失败不得抛穿 blocked 收口（code-review item
            # ccd3ffdf1a59）：上方 update_spec blocked 已落盘为 fail-closed
            # 终态，notifier 异常若上抛会沿 engine except e2 回滚整轮——
            # ERROR 留痕后继续原控制流（return）。
            try:
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
            except Exception as e:
                self._context.logger.error(
                    "pm_engine",
                    f"blocked 升级告警发送失败（非阻塞，blocked 已落盘）"
                    f"'{spec_name}': {type(e).__name__}: {e}",
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
        # 写 blocked 前二次核对（code-review item 5d28c6b0fe51）：judge 重试为
        # 长耗时操作，窗口内 spec 可能已被人工复位/冻结接管——非 testing 时
        # DEBUG 丢弃，不覆盖较新状态（同入口 _apply_status 判据口径）。核对
        # 先于失败历史侧车写入（code-review item de5187db298b）：spec 已被人工
        # 复位/接管时结果整体丢弃，失败历史不得先行落账污染升级分型与轮间
        # diff（与 report_missing 分支同口径）。
        _apply_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
        if _apply_status != "testing":
            self._context.logger.debug(
                "pm_engine",
                f"裁决证据二次违规但 spec 已非 testing（当前 "
                f"'{_apply_status}'）'{spec_name}' — 丢弃，不阻断",
            )
            return
        # 本轮回合计入失败历史侧车（cause_type=evidence-invalid），供升级闸门
        # 分型与轮间 diff（fix-verdict-retry-misattribution D6）。
        # 统一口径（code-review item eb8d814fcb3b）：violations 元素形态非受控
        # 保证（可能混入非 dict 元素），下方文案/告警宣称的违规数与失败历史
        # 入账场景数同源——均基于过滤后的 dict 条目，防「宣称数 > 入账数」
        # 人工对账失败侧车时对不上。
        dict_violations = [v for v in violations if isinstance(v, dict)]
        self._append_fail_history(
            spec_name,
            "evidence-invalid",
            [
                v.get("scenario_id") or v.get("id") or "?"
                for v in dict_violations
            ],
        )
        self._context.logger.error(
            "pm_engine",
            f"裁决证据分类二次校验仍失败 '{spec_name}' — 阻断推进为 blocked-env"
            f"（{len(dict_violations)} 项违规）",
        )
        self._context.state_machine.update_spec(
            spec_name,
            {
                "status": "blocked",
                "error": (
                    f"验证裁决证据分类校验连续失败：report.json 非 PASS 场景缺 "
                    f"classification/evidence，重试一次仍不合规"
                    f"（{len(dict_violations)} 项违规），已 blocked 等待人工裁决"
                ),
            },
        )
        # 告警通道自身失败不得抛穿 blocked 收口（code-review item
        # ccd3ffdf1a59）：update_spec blocked 已落盘，notifier 异常若上抛
        # 会沿 engine except e2 回滚整轮——ERROR 留痕后继续原控制流。
        try:
            self._context.escalation_notifier(
                spec_name=spec_name,
                signal_type="verdict_evidence_invalid",
                severity="critical",
                description=(
                    f"'{spec_name}' 验证裁决证据分类校验连续失败"
                    f"（{len(dict_violations)} 项违规），已 blocked 等待人工裁决"
                ),
                evidence=self._verdict_violations_evidence(spec_name, violations),
                recommended_action=(
                    "检查 planner-judge 是否遵守 prompt 第4步（对全部非 PASS 场景补 "
                    "classification/evidence）；人工重置后重跑验证"
                ),
            )
        except Exception as e:
            self._context.logger.error(
                "pm_engine",
                f"blocked 升级告警发送失败（非阻塞，blocked 已落盘）"
                f"'{spec_name}': {type(e).__name__}: {e}",
            )
        return

    def _read_verdict_guarded(self, spec_name: str, run_result=None):
        """_read_verdict + 共享回退陈旧护栏（code-review item eb76bcf8e306）。

        judge 主车道读取裁决：per-spec primary 缺失、_read_verdict 实际落到
        主树共享回退文件时，补一道 _verifier_result_is_stale 复核（与 legacy
        车道同款判据/签名形态）——同一 spec 此前 legacy 轮写入的共享裁决
        （role=verifier、spec 戳匹配、mtime 早于本轮 run 起点）不再仅凭
        role/spec 戳被直接采信，命中即转「不可读」交由调用方既有的
        重派 judge 一次 → 二次仍不可读 blocked 链，不新增处置分支。
        primary 存在（本轮 judge 正常写出产物）或无共享文件时零改动直通；
        run_result 缺省（兼容旧调用形态）或其 run_id 不可解析时按
        _verifier_result_is_stale 既有退化语义放行（WARNING 留痕）。
        """
        verifier_result = self._read_verdict(spec_name)
        if not verifier_result.ok or run_result is None:
            return verifier_result
        from core.pm_engine.verification.report_gate import (
            verify_progress_result_paths,
        )

        primary, shared = verify_progress_result_paths(self, spec_name)
        if primary.exists() or not shared.exists():
            return verifier_result
        if self._verifier_result_is_stale(run_result, shared, spec_name):
            self._context.logger.warning(
                "pm_engine",
                f"共享回退裁决陈旧/归属不明 '{spec_name}' — 按不可读处置"
                f"（走重派 judge 一次链）: {shared}",
            )
            return VerdictReadResult.failure("stale-shared", f"{shared}")
        return verifier_result

    def _read_verdict_failclosed(self, spec_name: str, judge_run=None):
        """裁决读取与 fail-closed 防护（fix-verdict-read-failclosed D4）。

        judge_run：本轮 judge run 结果（供 _read_verdict_guarded 对共享回退
        命中做 mtime 陈旧复核，code-review item eb76bcf8e306）；缺省时跳过
        该复核（仅 role/spec 戳校验，兼容既有调用形态）。

        本段承载：warning streak 升级、_read_verdict 结构化三态读取、结果应用处
        最终状态核对（D6）、裁决不可读重派一次→二次仍不可读 blocked + critical
        告警（重派 judge 的派发异常同样折算为二次不可读归因，不外溢）。
        任一失败路径返回 None（丢弃）；成功返回 (verifier_result, verifier_status)。
        """
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
        # 主树共享回退须过 role/spec 戳校验——implementer 残留不采信；
        # eb76bcf8e306：共享回退命中再补 mtime 陈旧复核，与 legacy 车道对齐）
        verifier_result = self._read_verdict_guarded(spec_name, judge_run)
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
            return None
        # ── 裁决不可读 → fail-closed（fix-verdict-read-failclosed D4）──
        # 结果文件缺失/非法 JSON/status 白名单外一律不得晋级 verified（历史事故：
        # add-verify-contract-autodraft 裸换行非法 JSON → None → else 分支 →
        # verified → done → auto-push）。处置：重派 judge 一次 → 复读；二次仍不可读
        # → blocked + critical 告警（含解析错误原文与结果文件完整路径），不推进
        # bug-found、不派生 fix。重试前复用入口状态判据（非 testing 丢弃，与
        # stale-result 防护同构，不新增竞态面）。
        if not verifier_result.ok:
            retry_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
            if retry_status == "testing":
                self._context.logger.warning(
                    "pm_engine",
                    f"裁决结果不可读 '{spec_name}'（reason={verifier_result.reason}）"
                    f"— 重派 judge 一次后复读: {verifier_result.detail}",
                )
                # 轮内记账（code-review item 68d9074a2c0f，judge_gate.py 调用点
                # 规则）：此路径直接 run_planner 不经 gate，与 _verify_verdict_evidence
                # 重派路径同口径——反复不可读的结果文件若不记账可绕过轮内 2 次
                # 与全局 5 次重裁决阈值。空 violations 必然落入 "real" 分支
                # （记轮内 +1 与生命周期 _judge_real_dispatches）。
                self._judge_charge_verdict_retry(spec_name, [])
                # 派发异常兜底（code-review item 8a3261d1caac）：run_planner 内部
                # 抛错不得外溢到 engine 层 legacy 降级旁路——本方法 docstring 承诺
                # 任一失败路径走 fail-closed 丢弃/blocked。与 verdict_evidence 同款
                # 「dispatch_exception 归因，禁止复读旧产物」：retry_judge 置 None
                # 跳过让位/复读分支，异常归因写入 retry_failure，复用下方既有
                # retry_failure 留痕与 blocked 归因路径。
                try:
                    retry_judge = self._pm.agent_runner.run_planner(spec_name, "judge")
                except Exception as e:
                    retry_judge = None
                    retry_failure = f"dispatch_exception: {type(e).__name__}: {e}"
                    self._context.logger.warning(
                        "pm_engine",
                        f"重派 judge 派发异常 '{spec_name}' — 按二次不可读 "
                        f"fail-closed 处置: {retry_failure}",
                    )
                else:
                    # 派发未抛异常：此处仅占位清空——成功/失败归因统一由下方
                    # retry_judge.success 分支处置（非让位类失败在「通用失败
                    # 留痕」处承接 retry_judge.error，见 code-review item
                    # 6afab3e3a4d4）。
                    retry_failure = ""
                # ── 结果侧让位（code-review item 93fa1398fed0）──
                # 重派 judge 被冻结终止/人工取消/provider 熔断时按让位语义处置
                # （判定/写字段单源：_yield_on_agent_failure），与
                # _dispatch_judge_or_reuse（frozen/cancelled/circuit-open）
                # 及 _handle_verdict_evidence_rejection（dispatch_frozen/
                # dispatch_cancelled）同口径：不携旧「不可读」结论落入下方
                # blocked 写入、不发 critical 告警。冻结 hold 保持原
                # status=testing，下方 != "testing" 守卫拦不住该覆写，须在此
                # 显式让位（人工已接管不写 blocked 不发告警）。
                if retry_judge is not None and not retry_judge.success:
                    yield_reason, _yield_err = self._yield_on_agent_failure(
                        spec_name, retry_judge)
                    if yield_reason == "frozen_terminated":
                        self._context.logger.info(
                            "pm_engine",
                            f"重派 judge run 因 spec 冻结被终止 '{spec_name}' — "
                            f"让位：写 hold 保全现场，不写 blocked、不发告警: "
                            f"{retry_judge.error or ''}",
                        )
                        return None
                    if yield_reason == "cancelled":
                        self._context.logger.info(
                            "pm_engine",
                            f"重派 judge run 被人工取消 '{spec_name}' — 让位："
                            f"写取消保持标记（保持 testing），不写 blocked、"
                            f"不发告警: {retry_judge.error or ''}",
                        )
                        return None
                    if yield_reason == "provider_circuit":
                        self._context.logger.warning(
                            "pm_engine",
                            f"Provider circuit open — 重派 judge 被抑制 "
                            f"'{spec_name}'，保持 testing 等待下轮重验: "
                            f"{retry_judge.error}",
                        )
                        return None
                    # ── 通用失败留痕（code-review item 6afab3e3a4d4）──
                    # 非让位类重派失败（网关 5xx/超时等通用 run 失败）：MUST NOT
                    # 把根因整体丢弃成「重派 judge 一次后仍不可读」的旧产物解析
                    # 错误——真实失败原因入 blocked error/evidence，供人工排障归因。
                    retry_failure = retry_judge.error or ""
                    self._context.logger.warning(
                        "pm_engine",
                        f"重派 judge 失败（非让位类）'{spec_name}' — 按二次不可读 "
                        f"fail-closed 处置，真实根因入 blocked 留痕: {retry_failure}",
                    )
                if retry_judge is not None and retry_judge.success:
                    verifier_result = self._read_verdict_guarded(spec_name, retry_judge)
                    verifier_status = verifier_result.status if verifier_result.ok else None
                    # 重派成功且裁决可读同样须核对（code-review item
                    # db9a50bcf07a）：重派 judge 常态 15-50 分钟，窗口内 spec
                    # 可能已被人工复位（stale-result 防护拨回）或冻结接管后又
                    # 重入 testing——stale 裁决直落 return 会交由下游
                    # _apply_bug_found/_apply_verified 的 transition 覆写新一轮
                    # 状态。与下方二次不可读分支 _apply_status 判据同口径：
                    # 非 testing 时 DEBUG 丢弃本次结果，不交下游。
                    _apply_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
                    if _apply_status != "testing":
                        self._context.logger.debug(
                            "pm_engine",
                            f"裁决重派后可读但 spec 已非 testing（当前 "
                            f"'{_apply_status}'）'{spec_name}' — 丢弃，不阻断",
                        )
                        return None
                    # ── 重派轮产物证据分类校验（code-review item cbef6c3847ca）──
                    # 主路径（_run_three_stage_verification 阶段3+）在进入本函数前
                    # 已对 judge 产物强制 _verify_verdict_evidence（不合规重派一次、
                    # 二次仍不合规 blocked）；本 D4 重派轮新写盘的 report.json 若只
                    # 复读不校验，不合规 classification/evidence 会绕过该防线直接
                    # 进入 _apply_bug_found/_apply_verified 采纳尾段（下游改道门/
                    # speculative 门按缺失 classification 保守放行）——「宁可不推进
                    # 也不带病采纳」语义在该路径失效。此处与主路径同构补一道校验：
                    # 不合格走既有 _handle_verdict_evidence_rejection 处置链（其内部
                    # 已完成让位/温和/blocked 各 cause 分型，所有出口均为零采纳，
                    # 与本函数失败路径 return None 丢弃语义同向），处置后按丢弃收口。
                    verdict_ret = self._verify_verdict_evidence(spec_name, retry_judge=True)
                    if not verdict_ret["ok"]:
                        self._handle_verdict_evidence_rejection(spec_name, verdict_ret)
                        return None
                    # 校验合规会按分类-状态映射强制重写 report.json 的 status
                    # （verdict_evidence D3 采纳收口），复读一次使 verifier_status
                    # 与盘上产物一致（与主路径「先校验后读取」顺序对齐）；复读
                    # 失败（校验与复读间产物被破坏的窄窗口）落入下方二次不可读
                    # fail-closed 分支 blocked，不推进采纳。
                    verifier_result = self._read_verdict_guarded(spec_name, retry_judge)
                    verifier_status = verifier_result.status if verifier_result.ok else None
            else:
                # 非 testing 丢弃（code-review item 3219564e2f22）：本节 docstring
                # 明言「重试前复用入口状态判据（非 testing 丢弃，与 stale-result
                # 防护同构）」，但旧实现仅「非 testing 就不重派」，随后仍无条件走
                # fail-closed blocked 写入——spec 已离开 testing（admin 复位为
                # implemented / 解冻）时该 blocked 会覆盖更新的状态。与上方
                # _apply_status 判据同口径：非 testing 直接丢弃本次结果、不写状态。
                self._context.logger.debug(
                    "pm_engine",
                    f"裁决不可读但 spec 已非 testing（当前 '{retry_status}'）"
                    f"'{spec_name}' — 丢弃本次结果，不阻断",
                )
                return None
            if not verifier_result.ok:
                # 写 blocked 前二次核对（code-review item 5d28c6b0fe51）：重派
                # judge 常态 15-50 分钟，窗口内 spec 可能已被人工复位/冻结接管
                # （frozen 门被此重派路径有意绕过；结果侧 frozen 终止/取消/
                # 熔断已在重派返回处显式让位）——非 testing 时 DEBUG 丢弃，
                # 不覆盖较新状态（同上方 _apply_status 判据口径）。
                _apply_status = (self._context.state_machine.read_one(spec_name) or {}).get("status", "")
                if _apply_status != "testing":
                    self._context.logger.debug(
                        "pm_engine",
                        f"裁决二次仍不可读但 spec 已非 testing（当前 "
                        f"'{_apply_status}'）'{spec_name}' — 丢弃，不阻断",
                    )
                    return None
                # 重派失败真实根因入 blocked（code-review item 6afab3e3a4d4）：
                # 通用失败（非让位类）时 error/evidence 携带 retry_judge.error，
                # 避免人工排障只见旧产物解析错误而误导归因。
                _retry_failure_note = (
                    f"；重派 judge 失败原因: {retry_failure}" if retry_failure else ""
                )
                self._context.logger.error(
                    "pm_engine",
                    f"裁决结果二次仍不可读 '{spec_name}' — 阻断为 blocked"
                    f"（reason={verifier_result.reason}）: {verifier_result.detail}"
                    f"{_retry_failure_note}",
                )
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "blocked",
                        "error": (
                            f"验证裁决结果文件不可读（重派 judge 一次后仍不可读，"
                            f"reason={verifier_result.reason}）：{verifier_result.detail}"
                            f"{_retry_failure_note}"
                        ),
                    },
                )
                # result_file 取实际读取路径（code-review item ff325de4988d /
                # 359da5d900bd）：_read_verdict 在 primary 缺失时回退主树共享
                # 文件，evidence 若硬编码 primary 路径，在共享回退文件损坏或
                # 重派窗口内 primary 产物刚被写出的场景下即与实际不可读产物
                # 位置错位、误导人工排障——blocked 写点处按 primary.exists()
                # 现场解析一次再生成 evidence（本函数唯一解析点）。
                from core.pm_engine.verification.report_gate import (
                    verify_progress_result_paths,
                )

                _vfp_primary, _vfp_shared = verify_progress_result_paths(self, spec_name)
                _blocked_result_path = _vfp_primary if _vfp_primary.exists() else _vfp_shared
                # 告警通道自身失败不得抛穿 blocked 收口（code-review item
                # ccd3ffdf1a59）：update_spec blocked 已落盘，notifier 异常
                # 若上抛会沿 engine except e2 回滚整轮——ERROR 留痕后继续
                # 原控制流（return None）。
                try:
                    self._context.escalation_notifier(
                        spec_name=spec_name,
                        signal_type="verdict_result_unreadable",
                        severity="critical",
                        description=(
                            f"'{spec_name}' 验证裁决结果文件不可读，已 blocked 等待人工裁决"
                            f"（reason={verifier_result.reason}）"
                        ),
                        evidence=(
                            f"spec={spec_name}; result_file={_blocked_result_path}; "
                            f"parse_error={verifier_result.detail}"
                            + (f"; retry_failure={retry_failure}" if retry_failure else "")
                        ),
                        recommended_action=(
                            "检查 planner-judge 是否以合法 JSON 写入结果文件（字符串内换行/"
                            "引号/控制字符须转义，建议以代码 json.dump 生成而非手工拼接）；"
                            "修复文件后重置验证或重跑"
                        ),
                    )
                except Exception as e:
                    self._context.logger.error(
                        "pm_engine",
                        f"blocked 升级告警发送失败（非阻塞，blocked 已落盘）"
                        f"'{spec_name}': {type(e).__name__}: {e}",
                    )
                return None
        return verifier_result, verifier_status

    # ── B9: bug-found 应用（编排骨架，等价搬移）────────────────────────
    # D1 B9 段落：5 道守卫 → infra 归因（前置到 transition 之前）→ transition
    # → spawn 抑制守卫。
    # 旧锚点 verifier_status=='bug-found' 分支体，此处提取为独立方法（D4）。
    def _apply_bug_found(self, spec_name: str, judge_result, report,
                         _repair_depth: int) -> None:
        """处理 verifier_status=='bug-found' 分支：归因门禁 → infra 归因（前置）→ transition → spawn 抑制。

        等价搬移自 _run_three_stage_verification 的 bug-found 分支体，保持控制流逐条等价。
        内部多个 return 为提前退出主函数语义；调用者 MUST 在 return 之后显式 return。
        """
        # fix-env-exemption-exit-reachability D3：judge 申报结论非全 env
        # （bug-found 路由）→ 清除 inconclusive 重验旗标，恢复 judge 生命周期
        # 正计（正常路由的 judge 消耗照旧计入 _judge_rerun_count 生命周期账）。
        self._clear_inconclusive_reverify_flag(spec_name)
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
            # 写点前状态复核（code-review item 5cbe3d1c8e6d，与 plan-ready
            # 分支同口径收敛于 _discard_if_not_testing）：_read_verdict_failclosed
            # 入口核对到本写点之间隔着场景缺陷改道门/报告合成等多次文件读，
            # 窗口内 spec 被人工冻结/复位接管时 DEBUG 丢弃，不覆写较新状态
            # 的 error/tester_run（阻断分支不经 transition，无 TOCTOU 保护）。
            if _discard_if_not_testing(self, spec_name, judge_result, "bug-found"):
                return
            # tester_run 与 _apply_verified 同类阻断分支同口径（code-review item
            # 28e2f027965e）：阻断轮亦留 run 关联，dashboard/排障不错失采纳路径。
            self._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": judge_result.run_id,
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
        # ── 统一失败归因入口（evo-infra-failure-budget-exempt R1/R3）──
        # MUST 在 bug-found transition 之前（code-review item b7f63a96e628，
        # 与 legacy 路径 12bd5b177792 同构）：enrich_failure_class 比上游
        # 早期 infra 判定点（仅 provider circuit open / chain exhausted /
        # 网关切换类错误）多匹配 worktree/merge conflict/tree dirty 标记，
        # judge error 含这些文本时判 infra——若先流转 bug-found 再归因，
        # infra 分支「不流转 bug-found、不派生 fix」即失效（spec 停在
        # bug-found 却不派生 fix）。三态分类后，product/unknown 照常流转
        # bug-found（unknown 按 product 保守处置，照常累计
        # _verify_fail_rounds）；infra 拦截：按 infra 记账（预算退款 +
        # _verify_infra_rounds + _infra_failure_count + 台账），不流转
        # bug-found、不派生 fix，由 full_scan recovery 兜底重排。
        failure_class = self.enrich_failure_class(
            spec_name,
            error_text=getattr(judge_result, "error", "") or "",
        )
        if failure_class == "infra":
            self._context.logger.warning(
                "pm_engine",
                f"归因入口判 infra：'{spec_name}' 按 infra 记账，"
                f"不流转 bug-found、不派生 fix",
            )
            # 退款锚点回退 implementer_run（不传 run_id，87cfffac1d3c 契约）：
            # judge attempt run id 作锚点会使每个 attempt 各自退款一次、按实现
            # run 的幂等去重失效；attempt id 经 ledger_run_id 只进失败台账，
            # 与 legacy/escalation 合规调用点同口径。
            self._record_infra_failure(
                spec_name,
                "infra at attribution entry (judge)",
                ledger_run_id=getattr(judge_result, "run_id", "") or "",
            )
            return
        # fix-observability-gaps 2.2：planner-judge 判定 bug-found（自动来源）
        # transition 返回值校验（与 spec_review.py consume_review_result 同款）：
        # 前置守卫链与 transition 之间存在 TOCTOU 窗口（报告闸门/洗白门禁/
        # ocr gate 多次读文件），窗口内 spec 被人工冻结/复位致非法转移被拒时，
        # 保留原状——不覆写 error/tester_run、不派生子 fix（伪 fix 级联防护）。
        accepted = self._context.state_machine.transition(
            spec_name, "bug-found",
            trigger_run_id=judge_result.run_id, agent_type="planner-judge", channel="auto",
        )
        if not accepted:
            self._context.logger.warning(
                "pm_engine",
                f"bug-found transition 被拒（转移非法，疑似冻结/并发接管）"
                f"'{spec_name}' — 保留原状，不覆写字段、不派生 fix",
            )
            return
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
        # ── 守卫二（fix-repair-lane-dedup / design 守卫二）spawn 抑制已移除
        # （code-review item e1d3410c1e73，原「跳过派生子 fix」死分支）：其
        # ready/implementing 判据在现行状态机下结构性不可达——VALID_TRANSITIONS
        # 中 bug-found 的唯一入边是 TESTING（另有 bug-found→bug-found 幂等短路
        # 返回 True），transition(spec_name, "bug-found") 返回 True 时转移前
        # 状态只可能是 testing 或 bug-found，与 ready/implementing（重实现在飞）
        # 在单 spec 语义下互斥，分支永不执行；原「读 transition 前状态使抑制
        # 生效」的快照与注释同与状态机现实不符，一并移除。
        # 到达 bug-found 归因（全部门禁已过、归因已前置到 transition 之前
        # 且非 infra）＝ product 类——unknown 按 product 保守处置，台账
        # failure_class 记 product。
        # ── bug-found 小缺陷 fastlane（add-pipeline-throughput-governance 4.1/4.2）──
        # 三条件全满足（失败场景数=1 + judge 影响面≤3 文件 + 无争议）→ code-fix
        # 轻量修复 + 子集重验，不派生 fix SPEC；任一不满足 / 承接失败 / 判定异常
        # → 既有 bug-found→fix SPEC 整轮路径原样。判定与路径选择全程落盘
        # （fastlane_decision.json + 日志）可追溯；连续 2 次失败强制回落整轮。
        try:
            _fastlane_decision = self._evaluate_fastlane(spec_name)
            if _fastlane_decision.get("eligible"):
                _fastlane_lane = self._dispatch_minor_defect_fastlane(
                    spec_name, _fastlane_decision
                )
                if _fastlane_lane.get("dispatched"):
                    return
        except Exception as _fastlane_err:
            self._context.logger.warning(
                "pm_engine",
                f"fastlane 判定/承接异常 '{spec_name}'（回落整轮 fix SPEC 路径）: "
                f"{_fastlane_err!r}",
            )
        self._context.on_spec_bug_found(
            spec_name,
            failure_class="product",
            run_id=getattr(judge_result, "run_id", "") or "",
        )

    # ── B10: verified 应用（编排骨架，等价搬移）────────────────────────
    # D1 B10 段落：进度核对 / 报告闸 / 洗白门 → transition（7 计数器归零）→ 采纳落盘。
    def _apply_verified(self, spec_name: str, judge_result, report) -> None:
        """处理 verifier_status!='bug-found'（verified）分支：进度核对 → transition → 7 计数器归零。

        等价搬移自 _run_three_stage_verification 的 verified 分支体。
        内部 return 为提前退出主函数语义；调用者 MUST 在 return 之后显式 return。
        """
        # ── 裁决 env 豁免握手（verdict-env-exemption-handshake，judge 采纳尾段）──
        # 进度核对/报告闸门/洗白门禁/transition 之前的拦截点：级二命中（裁决
        # 后失败全部为环境性）时 MUST NOT 落 verified——无 admin 放行处置记录
        # 转 inconclusive 重验（该轮不再到达洗白门禁，同一轮两道裁决后防线
        # 不叠加动作）；查得放行记录保留处置回链后放行。级二不命中零改动
        # 直通（含全绿快道合成报告——无豁免对象，快道不受影响）。
        # 传 None（code-review item 90032212ad27）：级二判定与放行回链均以盘上
        # judge 增强后的 report.json 为准（引擎内存 report 只有 status、无
        # assertion_triage/classification，直传会让每个失败场景落 non_env、
        # 级二恒不命中；且放行分支会把内存 report save_report 覆写盘上裁决
        # 产物）——入参非 None 会跳过 load_report，故 MUST 传 None 走读盘，
        # 与 legacy 车道（_read_verify_report 读盘传入）口径一致。
        if self._handle_env_exemption_handshake(spec_name, None):
            return
        # fix-env-exemption-exit-reachability D3：verified 放行（握手查得新鲜
        # 放行处置记录）= judge 申报结论非全 env 之一 → 清除 inconclusive 重验
        # 旗标恢复正计（级二命中时握手已提前 return，旗标保留到人工处置）。
        self._clear_inconclusive_reverify_flag(spec_name)
        # D6: testing→verified 前置进度核对：done>=total 才晋级
        vblocker = self._check_verification_gate(spec_name)
        if vblocker:
            # 写点前状态复核（code-review item 5cbe3d1c8e6d，与 plan-ready
            # 分支同口径收敛于 _discard_if_not_testing）：入口核对到本写点
            # 之间隔着豁免握手/进度核对等多次文件读，窗口内 spec 被人工
            # 冻结/复位接管时 DEBUG 丢弃，不覆写较新状态的 error/tester_run
            # （阻断分支不经 transition，无 TOCTOU 保护）。
            if _discard_if_not_testing(self, spec_name, judge_result, "verified"):
                return
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
            # 写点前状态复核（code-review item 5cbe3d1c8e6d，与上方进度核对
            # 写点及 plan-ready 分支同款 _discard_if_not_testing）。
            if _discard_if_not_testing(self, spec_name, judge_result, "verified"):
                return
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
        # add-impl-ocr-parallel-lane（任务 4.2）：testing 出口 ocr join 门禁。
        # defer → 车道未就绪，spec 停留 testing（车道完成回调唤醒重评，tester
        # 不重派）；reject → gate 档打回已在门禁内完成。两支都不再继续推进。
        # 门禁经 context 成员委托 Dispatcher（D10 惯例，不回引门面私有）；
        # 桩 context 未接线时缺省恒放行。
        ocr_decision = self._context.ocr_join_gate(spec_name, "planner-judge")
        if ocr_decision != "pass":
            return
        # fix-observability-gaps 2.2：planner-judge 判定 verified（自动来源）
        # transition 返回值校验（与 spec_review.py consume_review_result 同款）：
        # 前置守卫链与 transition 之间存在 TOCTOU 窗口（进度核对/报告闸门/
        # 洗白门禁/ocr gate 多次读文件），窗口内 spec 被人工冻结/复位致非法
        # 转移被拒时，保留原状——不覆写字段、不推进采纳/auto-push 链。
        accepted = self._context.state_machine.transition(
            spec_name, "verified",
            trigger_run_id=judge_result.run_id, agent_type="planner-judge", channel="auto",
        )
        if not accepted:
            self._context.logger.warning(
                "pm_engine",
                f"verified transition 被拒（转移非法，疑似冻结/并发接管）"
                f"'{spec_name}' — 保留原状，不覆写字段、不推进收尾",
            )
            return
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
                # evo-verify-infra-retry-lane D2：infra-retry 专用连续重派计数
                # 随验证 PASS 清零（D2 两个清零点之一，与上面 env 阻塞轮同点同
                # 生命周期；另一清零点=unfreeze_spec 清零清单，同一原子写）。
                VERIFY_INFRA_RETRY_STREAK_FIELD: 0,
                # evo-fix-env-exemption-gate-conflict-… 2.2：豁免生命周期随
                # verified 落定收口——豁免只在被验周期内生效（场景级豁免若跨
                # 周期残留，会把后续无关 env 失败在 TTL 窗口内一并洗白）；
                # 修订待重验旗标同点清除（修订后场景已收敛，不再留给下一
                # episode 的升级入口消费）。
                ENV_EXEMPTIONS_FIELD: None,
                SCENARIO_REVISION_PENDING_FIELD: False,
                # minor-defect-fastlane：verified 收口同步清零 fastlane 连败计数
                # （code-review item efbdab0801f3）。streak 此前仅在 fastlane
                # 收敛点清零（fastlane.py：transition 与 _apply_verified 全部
                # 成功后）——正常整轮 verified 不经该点，跨验证周期残留的旧
                # 连击会让后续 fastlane 首败即被误判逼近熔断阈值、提前回落
                # 整轮。与收敛点清零并存幂等（fastlane 收敛亦经本函数）。
                FASTLANE_STREAK_FIELD: 0,
            },
        )
        # 裁决采纳后落盘 verdict 稳定性轮次（judge-rerun-stability R1）
        self._record_verdict_adoption(spec_name, "verified", report)
        # 失败历史侧车随 verified 终态清空（fix-verdict-retry-misattribution D6）
        self._clear_fail_history(spec_name)
        # 本轮场景集变更小节追加到验证报告（spec 需求 2.3）
        self._render_scenario_change_section_to_report(spec_name)
        self._context.on_spec_verified(spec_name)

    # ── B1: 冻结加载 + 损坏升级（等价搬移）─────────────────────────────
    # D1 B1 段落：加载冻结场景集；若损坏则 escalate env_blocked 并返回 aborted 标记，
    # 调用者 MUST return 终止本流水线。
    def _load_frozen_or_escalate(self, spec_name: str, verify_dir) -> tuple:
        """加载冻结场景文件，损坏时升级 env_blocked 并返回 (None, True)；正常返回 (frozen, False)。

        等价搬移自 _run_three_stage_verification 的冻结加载 + 腐化升级段落。
        frozen 为列表（冻结场景集）或 None（无冻结、走出题）；aborted=True
        表示损坏已升级，调用者 MUST return 终止流水线。

        evo-frozen-scenario-contract-versioning（本 SPEC）：冻结集按条目级
        contract_version 路由契约迁移——读原始 JSON → 版本路由 → 迁移 →
        写回 → 最后才 load_scenarios 验收（**迁移 MUST 先于验收执行**，否则
        旧集先被判 corrupt 直接升级人工）。全场景过时（aborted=
        'all_scenarios_stale'）自动删除冻结文件并回落出题通道；未登记迁移段
        （aborted='no_migration_path'）与其余损坏维持既有 corrupt →
        env_blocked 人工通道（fail-closed）。写回失败轮（code-review item
        4f886aa7c126）另经实例属性 _stage2_scenarios_override 随行携带内存
        迁移集，供 _execute_stage2 本轮一次性消费。
        """
        # D4：import 留在函数体内（core.verify_engine.scenarios 在
        # _reload_verify_engine_modules 的 reload 清单内，函数体内调用时解析
        # 才能拿到最新模块）
        from core.verify_engine.scenarios import (
            CURRENT_CONTRACT_VERSION,
            TestScenario,
            frozen_contract_version,
            load_scenarios,
            migrate_frozen_contract,
            migrate_scenario_schema,
            prepare_scenarios_for_write,
            validate_scenario_dicts,
        )

        # 写回失败标记（code-review item 10c5c089ee92）：契约迁移写回失败时，
        # 步骤 4 改以内存迁移结果走验收——盘上此刻仍是未迁移旧场景集，读盘
        # 会把迁移本要修正的旧端口/URL 原样跑完整轮。
        write_back_failed = False
        # 写回失败轮随行携带的阶段2 内存迁移集（code-review item 4f886aa7c126）：
        # 步骤 4 产出的内存 frozen 若只用于验收，_execute_stage2 仍无条件
        # load_scenarios 读盘，本轮消费的还是未迁移旧集。经实例属性携带
        # （返回二元组契约被测试解包消费，扩元组属签名变更）、stage2 一次性
        # 读取消费，见 _execute_stage2 消费点。以 spec_name 键控 dict 承载
        # （code-review item e1b9182aa7dc：watch/scan 线程锁外派发，同一
        # pipeline 实例可并发跑不同 spec 的验证轮，标量属性会跨轮串扰）。
        self.__dict__.setdefault("_stage2_scenarios_override", {})[spec_name] = None

        # ── 场景冻结复用（scenario-reuse-on-reenter，2026-09-04）──
        # 冻结集一经生成即跨轮一致的量尺：重入验证（打回/修复轮/重试）直接
        # 复用，绝不重新出题——planner 单轮 2h/30M token 级成本只支付一次。
        # 冻集变更的唯一通道：admin 裁决（扩展/豁免）或人工删除冻结文件批准
        # 重新出题，以及本 SPEC 的契约自动迁移（机械补齐，无人工介入）。
        path = verify_dir / "test_scenarios.json"
        if not path.is_file():
            return None, False
        # ── 步骤 1：读冻结文件原始 JSON 数组（未过 load_scenarios 验收）──
        # 文件不可解析（JSON 语法错）不属契约漂移 → 沿用既有 corrupt →
        # env_blocked（维持人工，D2.3）。
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            self._context.logger.error(
                "pm_engine",
                f"冻结场景文件解析失败 '{spec_name}'（不属契约漂移，维持人工）: "
                f"{type(e).__name__}: {e}",
            )
            self._escalate_env_blocked(
                spec_name,
                [
                    _corrupt_freeze_options(spec_name),
                    f"解析异常：{type(e).__name__}: {str(e)[:300]}",
                ],
                title="场景计划争议",
            )
            return None, True
        if not isinstance(raw, list):
            # 根节点非数组不属契约漂移 → 维持既有 corrupt → env_blocked
            self._escalate_env_blocked(
                spec_name,
                [
                    _corrupt_freeze_options(spec_name),
                    f"场景文件格式错误: 期望 JSON 数组，实际为 {type(raw).__name__}",
                ],
                title="场景计划争议",
            )
            return None, True

        # ── 步骤 2：集内 contract_version 最小值路由（缺失/非整型=1）──
        # 取 min 保守迁移（任一旧条目都走迁移）；>= 当前版本 → 幂等零操作
        # （不迁移、不写回、不备份，D4）。
        set_version = frozen_contract_version(raw)
        migrated = False
        if set_version < CURRENT_CONTRACT_VERSION:
            migrated = True
            # 步骤 3：迁移前备份原文件（回退口 D4 配套；随下次成功迁移覆盖）
            try:
                (verify_dir / f"test_scenarios.json.contract-v{set_version}.bak").write_text(
                    path.read_text(encoding="utf-8"), encoding="utf-8"
                )
            except OSError as e:
                self._context.logger.warning(
                    "pm_engine",
                    f"冻结契约迁移备份失败 '{spec_name}'（不阻断迁移）: {e}",
                )
            base_url = self._current_instance_base_url(spec_name)
            # 迁移段内部异常兜底（code-review item 07488d9c8b8b）：登记迁移段
            # 对未预见条目形态抛异常时（当前唯一 _migrate_contract_to_v2 已
            # 自防御，风险面向后续迁移段演进），与本函数其余损坏路径同口径
            # 收敛 corrupt → env_blocked 人工通道（fail-closed）——裸调上抛
            # 会沿 _run_three_stage_verification 到 engine 层按整轮失败处置
            # （可触发 legacy 降级再验），违背本函数 docstring 契约。
            try:
                result = migrate_frozen_contract(raw, base_url=base_url)
            except Exception as e:  # noqa: BLE001 — 与下方写回失败兜底同口径
                _entry_brief = ", ".join(
                    str(item.get("id") or item.get("name") or "?")
                    for item in raw[:5]
                    if isinstance(item, dict)
                )
                self._context.logger.error(
                    "pm_engine",
                    f"冻结契约迁移异常 '{spec_name}'（维持人工通道）: "
                    f"{type(e).__name__}: {e}",
                )
                self._escalate_env_blocked(
                    spec_name,
                    [
                        _corrupt_freeze_options(spec_name),
                        f"契约迁移异常: {type(e).__name__}: {str(e)[:300]}"
                        f"（条目摘要：共 {len(raw)} 条，contract_version="
                        f"{set_version}，前几条: {_entry_brief or '无'}）",
                    ],
                    title="场景计划争议",
                )
                return None, True
            if result["aborted"] == "all_scenarios_stale":
                # D3：全场景过时（含空集）→ 删除冻结文件、本轮回落到既有
                # 出题分支——不置 blocked/env_blocked、不递归调用
                # _run_three_stage_verification（返回 (None, False) 由主循环
                # 以 frozen=None 走 planner 出题通道）。
                try:
                    path.unlink()
                except OSError as e:
                    self._context.logger.error(
                        "pm_engine",
                        f"契约升级全场景过时 '{spec_name}' 旧冻结文件删除失败"
                        f"（下轮重试删除）: {e}",
                    )
                self._context.logger.info(
                    "pm_engine",
                    f"契约升级全场景过时、已自动重新出题 '{spec_name}'，"
                    f"旧场景数={len(raw)}，旧 contract_version={set_version}",
                )
                return None, False
            if result["aborted"] == "no_migration_path":
                # D5 fail-closed：未登记版本段不猜不跳过 → 维持既有
                # corrupt → env_blocked 人工通道
                self._context.logger.error(
                    "pm_engine",
                    f"冻结契约迁移无路径 '{spec_name}'（contract_version="
                    f"{set_version} → {CURRENT_CONTRACT_VERSION} 未登记迁移段）"
                    "— 维持人工通道",
                )
                self._escalate_env_blocked(
                    spec_name,
                    [
                        _corrupt_freeze_options(spec_name),
                        f"契约迁移无可用路径（contract_version={set_version} → "
                        f"{CURRENT_CONTRACT_VERSION} 未登记迁移段，fail-closed）",
                    ],
                    title="场景计划争议",
                )
                return None, True
            if result["pending_replan"]:
                # 部分迁移：被剔除场景不参与本轮，剩余场景继续（D2.3）
                self._context.logger.warning(
                    "pm_engine",
                    f"冻结契约迁移部分成功 '{spec_name}'："
                    f"{len(result['pending_replan'])} 个场景无法定位 URL，"
                    f"待重排（本轮剔除）: {result['pending_replan']}",
                )
            # 写回冻结文件（数组形态 + 条目盖 schema_version/contract_version
            # 戳）；写回失败 ERROR 留痕并照常以内存迁移结果继续（不退回
            # corrupt，下次加载再迁一次即幂等，D4 写回原子性）。
            write_back = None
            try:
                write_back = prepare_scenarios_for_write(result["migrated"])
                # tmp+replace 原子写（共用 scenario_gate 助手）：裸写中途中断
                # 会留截断 JSON，下轮 _load_frozen_or_escalate 按「解析失败 →
                # 人工通道」误处置（code-review item 157daf7507c0）。
                atomic_write_text(
                    path,
                    json.dumps(write_back, ensure_ascii=False, indent=2),
                )
            except Exception as e:  # noqa: BLE001 — D4：写回失败不改变本轮内存结果
                # prepare 已产出内存结果、仅写盘失败 → 以内存结果验收；
                # prepare 自身失败（无内存结果）→ 保持读盘旧集（唯一可行来源）。
                write_back_failed = write_back is not None
                self._context.logger.error(
                    "pm_engine",
                    f"冻结契约迁移写回失败 '{spec_name}'（以内存迁移结果继续，"
                    f"下次加载再迁）: {type(e).__name__}: {e}",
                )
            # 迁移日志与审计（spec R3）：场景总数/成功迁移数/移除过时数/
            # contract_version 变更
            self._context.logger.info(
                "pm_engine",
                f"冻结契约迁移完成 '{spec_name}': 场景总数={len(raw)}，"
                f"成功迁移数={len(result['migrated'])}，移除过时数="
                f"{len(result['pending_replan'])}，contract_version "
                f"{set_version}→{CURRENT_CONTRACT_VERSION}",
            )

        # ── 步骤 4：以最终场景集走既有验收（读盘 = 写回后的文件）──
        # 写回失败（item 10c5c089ee92）改以内存迁移结果收尾：与 load_scenarios
        # 同源管线（schema 迁移 + 读端校验 + 反序列化），校验失败同样走下方
        # ValueError corrupt → env_blocked 通道，不另设旁路。
        try:
            if write_back_failed:
                raw_mem = migrate_scenario_schema(write_back)
                mem_errors = validate_scenario_dicts(raw_mem)
                if mem_errors:
                    raise ValueError(
                        f"场景文件包含 {len(mem_errors)} 个错误:\n"
                        + "\n".join(f"  - {e}" for e in mem_errors)
                    )
                frozen = [TestScenario.from_dict(item) for item in raw_mem]
                # 写回失败轮随行携带内存迁移集（item 4f886aa7c126）：阶段2
                # 本轮消费它而非盘上未迁移旧集（消费点见 _execute_stage2）。
                self.__dict__.setdefault("_stage2_scenarios_override", {})[spec_name] = frozen
            else:
                frozen = load_scenarios(path)
        except ValueError as e:
            # 迁移后仍失败（合成 navigate 可能仍不满足其他规则）→ 既有
            # corrupt → env_blocked；迁移过的集附第③条回退指引（D4 风险：
            # MUST NOT 静默吞掉或再自动重出题，可能掩盖真实场景缺陷）。
            detail = str(e)
            base_opts = _corrupt_freeze_options(spec_name)
            if migrated:
                base_opts += (
                    "③ 如需恢复迁移前集合：删除 "
                    f".fenix/verify-progress/{spec_name}/test_scenarios.json 与 "
                    f"test_scenarios.json.contract-v{set_version}.bak 的对应项后由 planner "
                    "重出题 / 或把 .bak 恢复为原文件。"
                )
            self._escalate_env_blocked(
                spec_name,
                [
                    base_opts,
                    f"验收差异清单：{detail[:600]}" if detail else "验收差异清单：无",
                ],
                title="场景计划争议",
            )
            return None, True
        except Exception as e:
            self._context.logger.error(
                "pm_engine",
                f"冻结场景文件加载异常 '{spec_name}': {type(e).__name__}: {e}",
            )
            self._escalate_env_blocked(
                spec_name,
                [
                    _corrupt_freeze_options(spec_name),
                    f"load_scenarios 非验收路径异常: {type(e).__name__}: {e}",
                ],
                title="场景计划争议",
            )
            return None, True
        if not frozen:
            # 空集不出现在迁移后（空文件/全过时已被 all_scenarios_stale
            # 分支删除回落到出题），防御性维持既有 corrupt 语义（reason 换
            # 空集首句，①②选项复用单源——code-review item a81f30195697）
            self._escalate_env_blocked(
                spec_name,
                [
                    _corrupt_freeze_options(
                        spec_name, reason="冻结场景文件为空（无任何场景）"
                    ),
                ],
                title="场景计划争议",
            )
            return None, True
        return frozen, False

    # ── B8: scenario-repaired 重入（等价搬移）─────────────────────────
    # D1 B8 段落：修复预算 / 冻结记账 / 空集拒绝 / 递归调用。
    # 返回 True 表示已处理（调用者 MUST return）；返回 False 表示非
    # scenario-repaired 状态，调用者继续后续分支。
    def _handle_scenario_repaired(self, spec_name: str, verifier_status: str,
                                  _repair_depth: int) -> bool:
        """处理 scenario-repaired 通道：预算检查 → 冻结记账 → 空集拒绝 → 尾递归重入。

        等价搬移自 _run_three_stage_verification B8 段落，保持尾递归调用原样。
        返回 True 表示调用者 MUST return（已重入或预算耗尽/空集拒绝提前退出）；
        返回 False 表示非 scenario-repaired，调用者继续后续分支。
        """
        if verifier_status != "scenario-repaired":
            return False
        # fix-env-exemption-exit-reachability D3：scenario-repaired 重入决策点
        # = judge 申报结论非全 env 之一 → 清除 inconclusive 重验旗标恢复正计。
        self._clear_inconclusive_reverify_flag(spec_name)
        if _repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS:
            # ── fix-recovery-path-blockers D3/D4/D5：预算耗尽两态处置 ──
            # 先读跨轮持久计数、再分两条不同文案写（MUST NOT 先写旧文案再
            # 补写新文案——后者会把首次排程的「下次重验时刻」立即覆盖掉，
            # Dashboard/CLI 直读 error 字段，可观测目标即落空）。计数生命周期：
            # verified 落定 + 人工 unfreeze_spec 两处清零；admin 处置复位 /
            # 中间转换不清零（D4，防「毒 spec 借复位重置计数无限循环」）。
            try:
                exhausted_rounds = int(
                    (self._context.state_machine.read_one(spec_name) or {}).get(
                        SCENARIO_REPAIR_EXHAUSTED_FIELD, 0
                    )
                    or 0
                )
            except (TypeError, ValueError):
                exhausted_rounds = 0
            if exhausted_rounds == 0:
                # 首次耗尽：落显式重验日程（排程定时器 + _dispatch_backoff_until
                # 兜底）+ 计数递增为 1，保持 testing；MUST NOT 升级人工、
                # MUST NOT 原地重入（设计 D3：立即原地重入会绕过
                # _SCENARIO_REPAIR_MAX_ROUNDS 的防护语义）。
                retry_at = int(time.time()) + _SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS
                retry_iso = from_epoch(retry_at).isoformat()
                _schedule_scenario_repair_reverify(self, spec_name)
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": (
                            f"judge 场景原地修复预算耗尽（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮）"
                            f"— 已排程重验（{retry_iso}），不再消耗实现预算"
                        ),
                        SCENARIO_REPAIR_EXHAUSTED_FIELD: 1,
                    },
                )
                self._context.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' judge 场景修复预算耗尽 "
                    f"（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮）— 已排程重验"
                    f"（{retry_iso}），不再重入",
                )
            else:
                # 再次耗尽（已给过一次重验仍不收敛）：走既有升级通道呼叫人工，
                # 保持 testing，不排程（升级通道见 _escalate_scenario_repair_exhausted）。
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": (
                            f"judge 场景原地修复预算耗尽（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮）"
                            f"且重验后仍不收敛 — 升级人工裁决，spec 保持 testing"
                        ),
                    },
                )
                self._context.logger.error(
                    "pm_engine",
                    f"'{spec_name}' judge 场景修复预算再次耗尽 "
                    f"（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮）— 升级人工，不再排程",
                )
                _escalate_scenario_repair_exhausted(self, spec_name)
            return True
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
            return True
        self._context.logger.info(
            "pm_engine",
            f"[阶段3+] judge 场景原地修复采纳 '{spec_name}' — 重入执行"
            f"（第 {_repair_depth + 1}/{_SCENARIO_REPAIR_MAX_ROUNDS} 次修复）",
        )
        # 尾递归调用保持原样——调用者 MUST return 以终止当前调用
        self._run_three_stage_verification(spec_name, _repair_depth=_repair_depth + 1)
        return True

    # ── 修复轮重验场景集裁剪（add-verify-lane-throughput 4.2，design 决策 6）──
    # 前提三条件（任一不满足即全量，fail-open）：非首轮（_verify_fail_rounds>0）、
    # 缓存有有效 PASS 条目、上轮 report.json 可读出失败集。执行集 = 失败 ∪
    # 失效（四元组不匹配/出处缺失/出处触碰 fix diff）∪ 其 depends_on 递归闭包
    # （前置链上溯 + 下游依赖方下探，与 fastlane.subset_scenario_ids 同口径）；
    # 其余场景采信缓存判定（合成报告时标注 cached_source）。
    def _fix_diff_files(self, head_at_write: str):
        """head_at_write..HEAD 的修复 diff 文件集；无法计算返回 None（fail-closed）。"""
        # commit 形态校验（code-review item 2a2c27eff327）：head_at_write 来自
        # .fenix 下可写的 verdict 缓存 _meta，直接拼 git argv 会被形如
        # --output=/path 的值当作选项解析（受限任意路径写）。非 commit 形态按
        # 「无法计算」返回 None，与既有 fail-closed 语义一致。
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", head_at_write):
            return None
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", f"{head_at_write}..HEAD"],
                cwd=str(self._context.project_root),
                capture_output=True,
                text=True,
                # 固化解码口径（code-review item de067b5e1d70）：随 locale 的
                # 默认编码遇非 ASCII 路径（core.quotepath=false 原样输出字节）
                # 抛 UnicodeDecodeError，不在下方 (OSError, SubprocessError)
                # 捕获清单内——穿透兜底使裁剪静默退化全量。与仓库既有
                # encoding="utf-8", errors="replace" 惯例对齐。
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if out.returncode == 0:
                return {ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()}
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    def _prune_rescan_scenarios(self, spec_name: str, scenarios: list):
        """计算本轮实际执行子集与可采信缓存条目（4.2 主体）。

        返回 (executed_scenarios, cached_results, note)：
        - executed_scenarios：传给引擎的场景列表（全量或裁剪子集）；
        - cached_results：{sid: 上轮 PASS 场景判定}——非空即本轮发生了裁剪，
          引擎跑完后由 _merge_cached_scenario_results 合成全量报告；
        - note：决策说明（日志用）。

        任一前提不满足 / 中途异常 → 原样全量返回（fail-open，缓存消费绝不
        产生新增打回，见 4.3）。

        场景元素兼容两种形态：``load_scenarios`` 产物是 TestScenario 对象
        （生产路径），dict 仅见于测试/合成路径——定义读取经
        ``_parallel_plan_scenario_def`` 归一，**传给引擎的元素保持原对象**
        （dfn= definition 视图，仅作指纹/出处/依赖读取）。
        """
        from core.verdict_check import (
            _is_non_pass,
            compute_build_fingerprint,
            compute_verify_config_fingerprint,
            extract_scenario_source_files,
            load_verdict_cache,
            verdict_cache_entry_valid,
        )

        full = [sc for sc in (scenarios or []) if sc is not None]
        defs = [_parallel_plan_scenario_def(sc) for sc in full]
        ids = [_parallel_plan_scenario_sid(d, i) for i, d in enumerate(defs)]

        def _full(note: str):
            return full, {}, note

        try:
            entry = self._context.state_machine.read_one(spec_name) or {}
            try:
                fail_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
            except (TypeError, ValueError):
                fail_rounds = 0
            if fail_rounds <= 0:
                return _full("首轮验证（fail_rounds=0），全量执行")

            cache = load_verdict_cache(self._context.project_root, spec_name)
            entries = {k: v for k, v in cache.items() if k != "_meta"}
            if not entries:
                return _full("无 verdict 缓存，全量执行")

            prev_path = (
                Path(self._context.project_root)
                / ".fenix"
                / "verify-progress"
                / spec_name
                / "report.json"
            )
            try:
                prev = json.loads(prev_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                return _full("上轮 report.json 不可读，全量执行")
            prev_scenarios = prev.get("scenarios") if isinstance(prev, dict) else None
            if not isinstance(prev_scenarios, list):
                return _full("上轮 report 无场景列表，全量执行")
            prev_by_id = {
                str(sc.get("scenario_id")): sc
                for sc in prev_scenarios
                if isinstance(sc, dict) and sc.get("scenario_id") is not None
            }
            failed_ids = {
                sid
                for sid, sc in prev_by_id.items()
                if _is_non_pass(sc.get("status"))
            }

            build_fp = compute_build_fingerprint(self._context.project_root)
            config_fp = compute_verify_config_fingerprint(self._context.project_root)
            meta = cache.get("_meta") if isinstance(cache.get("_meta"), dict) else {}
            head_at_write = str(meta.get("head_at_write") or "")
            fix_files = self._fix_diff_files(head_at_write) if head_at_write else None

            cached_results = {}
            seed_executed = set(failed_ids)
            for sc, d, sid in zip(full, defs, ids):
                if sid in seed_executed:
                    continue  # 失败场景恒重跑
                centry = entries.get(sid)
                if not verdict_cache_entry_valid(centry, d, build_fp, config_fp):
                    seed_executed.add(sid)  # 四元组不匹配/分量缺失 → 失效
                    continue
                prev_sc = prev_by_id.get(sid)
                if not isinstance(prev_sc, dict) or prev_sc.get("status") not in (
                    "pass",
                    "passed",
                ):
                    seed_executed.add(sid)  # 无上轮 PASS 判定可采信
                    continue
                if fix_files is None:
                    seed_executed.add(sid)  # 修复 diff 不可算（fail-closed）
                    continue
                source_files = extract_scenario_source_files(d.get("description"))
                if not source_files:
                    seed_executed.add(sid)  # 出处标注缺失（fail-closed：存疑即照跑）
                    continue
                if source_files & fix_files:
                    seed_executed.add(sid)  # 失效条件②：fix diff 触碰出处文件
                    continue
                cached_results[sid] = prev_sc

            if not cached_results:
                return _full("无可采信缓存条目，全量执行")

            # depends_on 递归闭包：执行集须含失败∪失效场景的前置链与下游依赖方
            dep_map = {
                sid: [str(x) for x in (d.get("depends_on") or [])] for d, sid in zip(defs, ids)
            }
            closure = set(seed_executed)
            frontier = list(seed_executed)
            known = set(ids)
            while frontier:
                sid = frontier.pop()
                for dep in dep_map.get(sid, []):
                    if dep and dep not in closure and dep in known:
                        closure.add(dep)
                        frontier.append(dep)
            # 下游下探（与 fastlane.subset_scenario_ids 同款不动点迭代，
            # code-review item d8cd847d55c5）：以闭包内任一场景为 depends_on
            # 前置的场景并入执行集。build 指纹只哈希依赖清单（不含源码），代码
            # 修复不改清单时依赖方缓存四元组仍有效、出处文件未被 fix diff 触碰
            # 即被采信免跑——修复波及未在场景出处标注中声明的共享行为时依赖方
            # 漏验。与 fastlane 子集口径（「下游纳入防修复波及依赖方而漏验」）
            # 对齐同一不动点语义；新增下游成员不再反向上溯其前置（fastlane
            # 同款，前置已随失败集上溯入集）。下探只扩大执行集（被征用的缓存
            # 采信让位于真实执行），fail-open 全量兜底不变。
            changed = True
            while changed:
                changed = False
                for sid in known:
                    if sid in closure:
                        continue
                    if any(dep in closure for dep in dep_map.get(sid, [])):
                        closure.add(sid)
                        changed = True
            # 被闭包征用为前置/下游的缓存场景改为真实执行（其采信资格让位）
            for sid in list(cached_results):
                if sid in closure:
                    del cached_results[sid]

            if not cached_results:
                return _full("闭包征用后无可采信缓存条目，全量执行")
            executed = [sc for sc, sid in zip(full, ids) if sid in closure]
            # executed 允许为空（fail_rounds>0 但上轮全 pass 的收敛态）：全缓存
            # 采信零执行出报告（任务 4.2 字面语义），由调用方走零执行合成路径。
            note = (
                f"修复轮重验裁剪：执行 {len(executed)}/{len(full)}"
                f"（缓存采信 {len(cached_results)}，失败 {len(failed_ids & closure)}）"
            )
            return executed, cached_results, note
        except Exception as e:  # noqa: BLE001 — 裁剪层任何异常不得阻断验证
            return full, {}, f"裁剪异常（fail-open 全量执行）: {type(e).__name__}: {e}"

    def _merge_cached_scenario_results(
        self, spec_name: str, report: dict, full_scenarios: list, cached_results: dict
    ) -> dict:
        """裁剪执行后合成全量报告并覆写 report.json（4.2 收尾）。

        执行结果 + 缓存采信条目（沿用上轮 PASS 场景完整判定，标注
        ``cached_source="verdict_cache"``）；摘要按引擎 _build_report 同口径
        重算（blocked-env 计入 warnings）。覆写必须在 engine.run 之后——引擎
        只写了子集报告。写盘失败不抛（fail-open：子集 report.json 已在盘，
        judge 按子集裁决，采信条目本轮缺席仅损失效率）。
        """
        from core.verdict_check import save_report

        merged = {
            str(sc.get("scenario_id")): sc
            for sc in (report.get("scenarios") or [])
            if isinstance(sc, dict)
        }
        for sid, prev in cached_results.items():
            if sid in merged:
                continue  # 引擎实际跑了（防御，以执行结果为准）
            cc = dict(prev)
            cc["cached_source"] = "verdict_cache"
            merged[sid] = cc
        ordered = []
        for i, sc in enumerate(full_scenarios):
            d = _parallel_plan_scenario_def(sc)
            sid = _parallel_plan_scenario_sid(d, i)
            if sid in merged:
                ordered.append(merged.pop(sid))
        ordered.extend(merged.values())  # 防御：报告多出的 sid 保留尾部

        summary = {
            "total": len(ordered),
            "passed": 0,
            "warnings": 0,
            "failed": 0,
            "errors": 0,
            "blocked_env": 0,
        }
        for sc in ordered:
            st = sc.get("status")
            if st in ("pass", "passed"):
                summary["passed"] += 1
            elif st == "warning":
                summary["warnings"] += 1
            elif st in ("fail", "failed"):
                summary["failed"] += 1
            elif st == "error":
                summary["errors"] += 1
            elif st == "blocked-env":
                summary["blocked_env"] += 1
        summary["warnings"] += summary["blocked_env"]
        report["scenarios"] = ordered
        report["summary"] = summary
        report["resumed_from_cache"] = sorted(cached_results)
        report["pruned_execution"] = {
            "executed": len(ordered) - len(cached_results),
            "resumed": len(cached_results),
        }
        try:
            save_report(self._context.project_root, spec_name, report)
        except Exception as e:  # noqa: BLE001 — save_report 的序列化异常同样 fail-open
            self._context.logger.warning(
                "pm_engine",
                f"裁剪合成全量报告写盘失败 '{spec_name}'（沿用子集报告）: "
                f"{type(e).__name__}: {e}",
            )
        self._context.logger.info(
            "pm_engine",
            f"[阶段2] 裁剪重验合成全量报告 '{spec_name}': 执行 "
            f"{len(ordered) - len(cached_results)} + 缓存采信 {len(cached_results)}"
            f" = {len(ordered)} 场景",
        )
        return report

    # ── B3: 阶段2 引擎执行段（等价搬移，不含 env_error 回写段）──────
    # D1 B3 段落（D2：引擎执行段可提，env_error 回写段含 continue/break 留循环体）。
    # 加载场景 → 应用可达性自愈 → 静态缺陷扫描 → VerifyEngine 创建/运行。
    # D4：VerifyEngine / load_scenarios 的 import 保留在本方法体内（运行时函数体内），
    # 测试靠 patch("core.verify_engine.VerifyEngine") 在本方法执行时生效。
    def _salvage_top_level_dict(self, scenarios_path):
        """顶层 dict 包裹形态机械拯救（evo-scenario-product-toplevel-contract 2.2）。

        验收失败归因点专用单点接入：test_scenarios.json 顶层为「dict 且含
        scenarios 数组」时解包 → 重过既有全部场景校验 → 以解包后的纯数组
        原子重写落地（非仅内存采纳——fastlane/verdict_evidence/冻结装载等
        其余 load_scenarios 读端与冻结层顶层读端按既有语义自然恢复，故其余
        读端一律不接本助手）。解包前顶层键与条目数 WARNING 留痕（design D4：
        解包属框架改写 agent 产物，须可审计；契约已双侧明示，dict 包裹即
        agent 违约，解包只作一次性止损，不弱化契约约束）。

        不可拯救 / 解包后仍非法 / 落地写失败 → 返回 None，调用方照常按原
        错误进入 replan（design D1：解包后仍不合法 MUST 照常拒收）。
        """
        from core.verify_engine.scenarios import salvage_scenarios_file

        try:
            scenarios, info = salvage_scenarios_file(scenarios_path)
        except (ValueError, OSError) as e:
            # 不可拯救形态留 info 痕（早退路径不零痕迹），调用方按原错误走 replan
            self._context.logger.info(
                "pm_engine",
                f"场景文件顶层拯救不适用 '{scenarios_path}': "
                f"{type(e).__name__}: {str(e)[:200]}",
            )
            return None
        self._context.logger.warning(
            "pm_engine",
            f"场景文件顶层拯救 '{scenarios_path}': 解包前顶层键 "
            f"{info['top_keys']}、{info['entry_count']} 条场景解包重验通过，"
            "已以纯数组原子重写落地（顶层 dict 包裹违反顶层交付契约，"
            "机械解包仅一次性止损）",
        )
        return scenarios

    def _replan_feedback_text(self, replan_feedback: str, spec_name: str) -> str:
        """渲染 REPLAN_FEEDBACK.md 全文（evo-scenario-product-toplevel-contract 2.2）。

        按失败类别生成收尾指引：格式类（场景文件顶层形状/条目结构非法，
        经 _replan_error_format_class 侧车按失败发生阶段判定，不解析错误
        文本——design D3）给「最小修复」指引（错误类别 + 修复动作），
        MUST NOT 指示全量重建——「一层包裹错误放大成 25 场景全量重建」即
        本 SPEC 要杜绝的浪费形态；内容类缺失（场景整体缺失等）保留
        「重新输出全部场景」既有指示，行为不回归。侧车按 spec_name 键控
        读取（code-review item e1b9182aa7dc 并发验证轮隔离）。
        """
        if self.__dict__.get("_replan_error_format_class", {}).get(spec_name, False):
            tail = (
                "\n\n本轮失败类别：**格式类**（场景文件顶层形状或条目结构非法）。\n"
                "最小修复：保持已合法的场景条目原样，只修正上方逐条错误指向的"
                "顶层形状或报错条目——test_scenarios.json 顶层必须是纯 JSON 数组，"
                'MUST NOT 用 {"scenarios": […]} 之类 dict 包裹；修正后整体重写'
                "文件一次（保持合法 JSON 数组），MUST NOT 全量重建场景；"
                "navigate 的 value 必须为绝对 URL。\n"
            )
        else:
            tail = "\n\n重新输出全部场景；navigate 的 value 必须为绝对 URL。\n"
        return (
            "# 场景验收反馈（上一轮未通过，必须逐条修正）\n\n"
            + replan_feedback
            + tail
        )

    # ── B3: 阶段2 引擎执行段（等价搬移，不含 env_error 回写段）──────
    # D1 B3 段落（D2：引擎执行段可提，env_error 回写段含 continue/break 留循环体）。
    # 加载场景 → 应用可达性自愈 → 静态缺陷扫描 → VerifyEngine 创建/运行。
    # D4：VerifyEngine / load_scenarios 的 import 保留在本方法体内（运行时函数体内），
    # 测试靠 patch("core.verify_engine.VerifyEngine") 在本方法执行时生效。
    def _execute_stage2(self, spec_name: str, verify_dir, scenarios_path,
                        skip_prune: bool = False):
        """阶段2 引擎执行段（等价搬移自循环体内 B3）。

        返回五元组 (env_error, report, app_reachable, reach_note, aborted)：
        - aborted=True：应用不可达 fail-fast，调用者 MUST return 终止流水线
        - env_error 非 None：环境错误，调用者走 replan 回写段
        - env_error=None, report 非 None：引擎执行完成，调用者继续 B4 门禁
        - skip_prune=True：跳过修复轮缓存裁剪（_prune_rescan_scenarios），
          以传入场景集原样作为本轮执行集（fastlane 子集重验用，兑现模块
          docstring「绕过缓存逻辑」不变量）
        - _stage2_scenarios_override（实例属性，code-review item 4f886aa7c126）：
          冻结契约迁移写回失败轮由 _load_frozen_or_escalate 随行携带的内存
          迁移集，本方法一次性读取消费后即清位——盘上该轮仍是未迁移旧集，
          读盘会把迁移本要修正的旧端口/URL 原样跑完整轮
        """
        import asyncio
        from core.verify_engine import VerifyEngine
        from core.verify_engine.scenarios import load_scenarios

        env_error = None
        report = None
        app_reachable = True
        reach_note = ""
        user_blocked = False
        # user_blocked 侧车（code-review item ad95fc9cdbdd）：B4 应用不可达门禁
        # 须与本处 fail-fast 共享同一「需用户参与」预留判定位。返回五元组契约
        # 已被 fastlane 子集重验解包消费，扩元组属跨文件签名变更（超本组边界），
        # 故经实例属性携带、门禁调用点读取（缺省 False 兜底）。以 spec_name
        # 键控 dict 承载（code-review item e1b9182aa7dc：并发验证轮隔离，
        # 理由同 _stage2_scenarios_override 注）。轮次入口 pop 清残留
        # （code-review item 88d58ec1565d）：读侧缺省 False 兜底，清键与置
        # False 等价，防已归档/删除 spec 的条目常驻累积。
        self.__dict__.get("_stage2_user_blocked", {}).pop(spec_name, None)

        # 写回失败轮消费内存迁移集（code-review item 4f886aa7c126）：
        # _load_frozen_or_escalate 契约迁移写回失败时盘上仍是未迁移旧集，
        # 下方两处 load_scenarios 读盘会把迁移本要修正的旧端口/URL 原样跑
        # 完整轮——该轮改消费随行携带的内存迁移集（已过同源验收 + from_dict
        # 解析，与 load_scenarios 产物同构）。一次性读取即清位，防 replan
        # 循环后续轮误消费陈旧 override。
        _override_cache = self.__dict__.setdefault("_stage2_scenarios_override", {})
        scenarios_override = _override_cache.get(spec_name)
        _override_cache.pop(spec_name, None)  # 一次性读取即清位（pop 连键清理，防整份场景列表滞留常驻累积——code-review item 88d58ec1565d）

        # ── 阶段2: 验证引擎执行 ──
        self._context.logger.info("pm_engine", f"[阶段2] 验证引擎执行: {spec_name}")

        # 场景文件验收失败（相对 URL/结构非法）＝ 明确的环境错误：
        # 退回 plan 阶段重新生成，不走 raise 穿透、更不判 bug-found。
        # 格式类失败分类侧车（evo-scenario-product-toplevel-contract 2.2）：仿
        # _stage2_user_blocked 先例经实例属性携带（五元组返回契约冻结）——
        # 场景文件结构验收阶段（顶层形状/条目结构 ValueError）为格式类，
        # REPLAN_FEEDBACK 据此给「最小修复」指引；分类按失败发生阶段判定，
        # 不解析错误文本（design D3）。以 spec_name 键控 dict 承载
        # （code-review item e1b9182aa7dc：并发验证轮隔离，理由同上）。
        # 入口 pop 清残留（code-review item 88d58ec1565d）：读侧缺省 False
        # 兜底，清键与置 False 等价。
        self.__dict__.get("_replan_error_format_class", {}).pop(spec_name, None)
        try:
            if scenarios_override is not None:
                scenarios = scenarios_override
            else:
                scenarios = load_scenarios(scenarios_path)
        except ValueError as e:
            # 顶层拯救助手（evo-scenario-product-toplevel-contract 2.2）：判定
            # 失败前先尝试「dict 且含 scenarios 数组」唯一形态的机械解包——
            # 解包重过全部校验通过即以纯数组原子重写落地（其余读端与冻结层
            # 顶层读端按既有语义自然恢复）并留痕，本次验收视同通过；其余形态
            # 照常按原错误进入 replan。拯救单点接入本归因点，其余读端不接助手。
            scenarios = self._salvage_top_level_dict(scenarios_path)
            if scenarios is None:
                env_error = f"场景文件验收失败: {e}"
                self.__dict__.setdefault("_replan_error_format_class", {})[spec_name] = True
        # ── 空集独立拒绝（code-review item cc5036090a52）──
        # load_scenarios 对空数组验收通过并返回 []（不拒空集），空集防线此前
        # 完全依赖 _apply_scenario_freeze 的 aborted 结构化信号；freeze 异常被
        # 调用点吞为 None（fail-open 放行）时防线缺席——0 场景经 engine.run([])
        # 产出无 env_error 的全绿报告，会被洗白门 fail-open 放行判 verified。
        # 此处不依赖 freeze 返回值，对加载结果独立拒绝：空集同走 env_error →
        # replan / 预算耗尽显式结束通道（与 freeze aborted 消费口径一致），
        # 空集任何情况下不进引擎执行。
        if env_error is None and isinstance(scenarios, list) and not scenarios:
            env_error = "场景文件验收通过但为空集（0 场景）— 拒绝以空集进入阶段2 执行"

        if env_error is None:
            # ── 阶段2.5: 应用可达性自愈（最终用户验证必选）──
            # 场景执行前确保应用可被浏览器访问；不可达时自动启动 commands.start、
            # 端口冲突换端口重试。自愈失败由下方验证门禁兜底，不静默判定通过。
            app_reachable, user_blocked, reach_note = self._ensure_app_reachable(spec_name)
            self.__dict__.setdefault("_stage2_user_blocked", {})[spec_name] = user_blocked
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
            #
            # evo-verify-infra-retry-lane：本调用点是 infra_retry 标记的**全仓
            # 唯一传点**（D6 决策单点化）——prepare 失败/可达性 fail-fast（0 场景
            # 执行短路）在升级通道入口先咨询 infra-retry 限次决议：未达缺省 2 次
            # 预算即旁路返回 "redispatch"（不计 env 冻结轮、不写 blocked/status、
            # 不呼叫 admin），经既有 verifier 派发入口（D5）廉价重派；超预算落穿
            # 恢复全价升级。场景执行期的 env 阻塞（_handle_env_blocked_inconclusive）
            # 不带此标记，仍走既有全价升级——车道只覆盖 0 场景执行的确定性短路轮。
            if not app_reachable and not user_blocked:
                self._context.logger.error(
                    "pm_engine",
                    f"[阶段2] 应用不可达，本轮 fail-fast（场景执行数=0）'{spec_name}': "
                    f"{reach_note}",
                )
                decision = self._escalate_env_blocked(
                    spec_name,
                    [reach_note],
                    title="验证环境阻塞（应用不可达）",
                    infra_retry=True,
                )
                if decision == "redispatch":
                    # ── infra-retry 车道收口（D5）：经既有 verifier 派发入口
                    # 重新入队，不绕派发队列直调。接线缺失（schedule_infra_
                    # retry_redispatch=None）或派发异常 fail-open 回落 context
                    # 直接 enqueue——本轮仍按 aborted 收口，记账/决议已在上游
                    # 完成，不因机械路径故障升级为全价轮。
                    self._context.logger.warning(
                        "pm_engine",
                        f"[阶段2] infra-retry 车道命中，廉价重派验证 '{spec_name}'"
                        f"（{reach_note}）",
                    )
                    schedule = getattr(
                        self._context, "schedule_infra_retry_redispatch", None
                    )
                    try:
                        if schedule is not None:
                            schedule(spec_name)
                        else:
                            self._context.enqueue(spec_name, "verifier")
                    except Exception as exc:
                        self._context.logger.error(
                            "pm_engine",
                            f"[阶段2] infra-retry 重派触发失败，回落直接入队 "
                            f"'{spec_name}': {exc}",
                        )
                        self._context.enqueue(spec_name, "verifier")
                return None, None, False, "", True

            # 自愈可能改写场景文件端口（场景声明端口 → 框架分配端口）：
            # 上方 load 先于自愈，内存场景仍持声明端口，改写只落文件、对本次
            # 执行无效 → 全场景对失联端口 navigate 整轮伪失败
            # （add-v3-spec-detail-page：24 场景导航 localhost:8000 全灭）。
            # 故自愈后必须重读场景文件再执行。
            # 写回失败轮例外（item 4f886aa7c126）：盘上是未迁移旧集，重读即
            # 回退迁移——保持内存迁移集执行；自愈端口改写只落盘上旧集，本轮
            # 不反映，下轮写回成功后由自愈再改写。
            if scenarios_override is None:
                try:
                    scenarios = load_scenarios(scenarios_path)
                except ValueError as e:
                    env_error = f"自愈改写后场景文件验收失败: {e}"
                    # 同属场景文件结构验收阶段 → 格式类（design D3 按失败
                    # 发生阶段判定；该读点文件已过首载拯救/校验，一般仅
                    # 自愈改写引入的形状损伤会走到这里）。
                    self.__dict__.setdefault("_replan_error_format_class", {})[spec_name] = True
                # 空集独立拒绝（code-review item cc5036090a52）：同首载点，
                # 自愈改写后重读得空集（0 场景）同样 MUST NOT 进引擎执行。
                if env_error is None and isinstance(scenarios, list) and not scenarios:
                    env_error = (
                        "自愈改写后场景文件为空集（0 场景）— 拒绝以空集进入阶段2 执行"
                    )

        if env_error is None:
            # ── 场景静态缺陷扫描（add-scenario-defect-triage-gate D3）──
            # 在场景集冻结完成后、执行前调用：findings 只作情报落盘
            # （scenario_static_findings.json）+ judge prompt 定向注入，
            # fail-open——任何异常记 WARNING，不阻断验证执行。
            self._run_scenario_static_check(spec_name)

            # ── 修复轮重验场景集裁剪（add-verify-lane-throughput 4.2）──
            # 失败∪受影响∪前置链照跑，其余采信缓存判定；任一前提不满足
            # 即原样全量（fail-open，绝不因裁剪产生新增打回）。
            if skip_prune:
                # fastlane 子集重验（subset_reverify）显式绕过缓存逻辑（模块
                # docstring 不变量）：子集场景集原样作为本轮执行集，不消费
                # verdict 缓存——代码修复不改 package.json → 构建指纹不变，
                # 未触达文件的并入下游场景会被上轮 PASS 缓存采信免跑，修复
                # 波及回归漏验。
                executed_scenarios, cached_results, prune_note = scenarios, {}, (
                    "fastlane 子集重验：显式跳过缓存裁剪，子集全量执行"
                )
            else:
                executed_scenarios, cached_results, prune_note = self._prune_rescan_scenarios(
                    spec_name, scenarios
                )
            self._context.logger.info("pm_engine", f"[阶段2] {prune_note} '{spec_name}'")

            if not executed_scenarios and cached_results:
                # ── 零执行全缓存采信（add-verify-lane-throughput 4.2）──
                # 裁剪后执行集为空（上轮已全 pass 的收敛态）：不构造引擎、
                # 不启动浏览器，直接以全缓存条目合成全量报告（执行 0 + 采信 N）。
                self._context.logger.info(
                    "pm_engine",
                    f"[阶段2] 裁剪后零执行（全缓存采信 {len(cached_results)} 场景）"
                    f"'{spec_name}' — 跳过引擎直接合成报告",
                )
                empty_report = {
                    "spec": spec_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "effective_parallel": self._context.config_reader(
                        "verify.max_parallel", 5
                    ),
                    "summary": {"total": 0, "passed": 0, "warnings": 0,
                                "failed": 0, "errors": 0, "blocked_env": 0},
                    "scenarios": [],
                }
                report = self._merge_cached_scenario_results(
                    spec_name, empty_report, scenarios, cached_results
                )
                return None, report, app_reachable, reach_note, False

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
                    # evo-fix-verify-parallel-override-type 2.2：留痕补字段来源
                    # ——值取自 spec attrs（read_one 条目），repr 不退化
                    # （写侧守卫＋parse 归一后正常轮到不了这里，仅兜锁外内存
                    # 写等旁路坏值；不把布尔语义映射为特定并行度）。
                    self._context.logger.warning(
                        "pm_engine",
                        f"降档并行度解析失败 '{spec_name}' "
                        f"(_verify_parallel_override={_parallel_override!r}，"
                        f"取自 spec attrs)，沿用配置并行度",
                    )
            # 契约统一供给 base_url（design verify-runner-engine base_url 统一供给）：
            # 取代「从候选场景 navigate 步骤文本正则考古」——serve 流程已知
            # 实例地址，直接分发各 Runner（web/api URL origin 改写依据、
            # 环境门探针定位依据）。无实例形态（纯 cli）为空串无害空操作。
            engine.base_url = self._current_instance_base_url(spec_name)
            # ── serving dist 新鲜度探针（serving-dist-freshness-probe 2.2）──
            # 场景开跑前执行一次（场景间不重复）：判滞后先自动重建（构建契约
            # 与 merge-back 同源）；重建失败 MUST NOT 以陈旧 dist 静默开跑——
            # 合成全批 blocked-env 报告，该轮按环境性失联语义走既有
            # blocked-env/inconclusive 路径处置（重验轮探针先行，重建成功即
            # 真实复跑；穷尽走 B7 升级通道），供豁免握手与 admin 升级链消费。
            probe_err = self._probe_dist_freshness(spec_name)
            if probe_err:
                block_report = self._dist_probe_block_report(
                    spec_name, executed_scenarios, probe_err
                )
                return None, block_report, app_reachable, reach_note, False
            report = asyncio.run(engine.run(executed_scenarios))
            env_error = report.get("env_error")
            if env_error is None and cached_results:
                # 裁剪生效：合成「执行结果+缓存采信」全量报告并覆写
                # report.json（engine.run 只写了子集）。env 轮不合成——
                # 环境错误轮走 replan/降级链，子集报告足以承载。
                # 4.3：合成链任何异常 → 沿用引擎子集报告（fail-open），
                # 缓存消费全链零新增打回（judge 按子集照常裁决）。
                try:
                    report = self._merge_cached_scenario_results(
                        spec_name, report, scenarios, cached_results
                    )
                except Exception as e:  # noqa: BLE001
                    self._context.logger.warning(
                        "pm_engine",
                        f"裁剪合成全量报告异常（沿用子集报告）'{spec_name}': "
                        f"{type(e).__name__}: {e}",
                    )

        return env_error, report, app_reachable, reach_note, False

    # ── B4: 阶段2 门禁 + 全绿快道（等价搬移）──────────────────────────
    # D1 B4 段落：汇总日志 / 不可达门禁 / 失联门禁 / 同因哨 / 全绿快道。
    # 返回 (fail_count, judge_result, aborted)：aborted=True 表示门禁触发，
    # 调用者 MUST return 终止流水线；judge_result 非 None 为快道合成结果，
    # None 表示未命中快道、需真实派发 judge。
    def _run_stage2_gates(self, spec_name: str, report, app_reachable: bool,
                          reach_note: str, user_blocked: bool = False) -> tuple:
        """阶段2 门禁链 + 全绿快道（等价搬移自 _run_three_stage_verification B4）。

        汇总日志 → 不可达门禁 → 环境性失联门禁 → 全场景同因哨 → 全绿快道。
        任一门禁触发即 (_, None, True) 返回，调用者 MUST return。
        user_blocked：阶段2.5 可达性自愈的「需用户参与」预留判定位（与
        _execute_stage2 fail-fast 同源，code-review item ad95fc9cdbdd）；
        True 时应用不可达门禁不自动判 blocked。
        """
        # code-review item e12b871aced5：summary 形状防御——三个 report 来源
        # （engine.run / 裁剪合成 / dist 探针块报告）正常均含 summary 全键，
        # 改 .get 取值只兜上游报告结构演进/测试替身注入精简 report 的退化
        # 形态（缺键按 0 计，不再 KeyError 沿主流程穿透）；正常路径数值不变。
        summary = report.get("summary") or {}
        fail_count = summary.get("failed", 0) + summary.get("errors", 0)
        self._context.logger.info(
            "pm_engine",
            f"[阶段2] 完成: {summary.get('total', 0)}场景, "
            f"{summary.get('passed', 0)}通过, "
            f"{summary.get('warnings', 0)}警告, "
            f"{fail_count}失败",
        )

        # ── 阶段2 验证门禁：应用不可达且场景全失败时不判定 verified ──
        # 最终用户验证为必选项：若自愈后应用仍不可达、0 场景通过，则本次验证
        # 并未真正触达最终用户可见功能，不得静默判定 verified/done；将问题与
        # 已尝试的解决方案写入 error 暴露（而非 "0通过/31失败" 却标完成）。
        if (
            not app_reachable
            and summary.get("passed", 0) == 0
            and fail_count == summary.get("total", 0)
        ):
            # 「需用户参与」型不可达让位（code-review item ad95fc9cdbdd）：
            # user_blocked 预留判定位与阶段2.5 fail-fast 处（_execute_stage2
            # 「需用户参与（收验证码/登录）」守卫）共享——该型不可达将来实现后
            # 同样不得被本门禁自动判 blocked：DEBUG 留痕后跳过升级，交由下方
            # 环境性失联门禁/同因哨与 judge 按报告处置。当前 user_blocked 恒
            # False，此分支不触发（埋线对齐）。
            if user_blocked:
                self._context.logger.debug(
                    "pm_engine",
                    f"验证门禁: '{spec_name}' 应用不可达但属用户参与型"
                    f"（user_blocked）— 不自动判 blocked，跳过本门禁: {reach_note}",
                )
            else:
                # ── 纵深防御写点（code-review item eceab97ec436）：当前主流程
                # 不可达——唯一调用点 _run_three_stage_verification 的
                # app_reachable 实参来自 _execute_stage2，其 fail-fast 段
                # （「not app_reachable and not user_blocked」→ aborted=True）
                # 已把该组合短路，能到达本门禁的 not app_reachable 必伴随
                # user_blocked=True（走上方让位分支）。保留本写点作 fail-fast
                # 条件将来放宽时的兜底；注意其升级语义与 fail-fast 车道已分叉
                # （不走 infra-retry 限次决议、写伪 tester_run 标记），启用前
                # 应先对齐口径。
                self._context.state_machine.update_spec(
                    spec_name,
                    {
                        # 伪标记非真实 run_id（消费方豁免口径见常量定义处）。
                        "tester_run": TESTER_RUN_BLOCKED_APP_UNREACHABLE,
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
                return fail_count, None, True

        # ── 阶段2.6 环境性失联门禁（verify-environment-sanity-gate / design D2）──
        # 全批 blocked-env → inconclusive：回 testing 重派新 attempt，不判 bug-found、
        # 不产生 repeated_failures 信号。阻断后直接 return（跳过 judge / 终态判定）。
        if self._handle_env_blocked_inconclusive(spec_name, report):
            return fail_count, None, True

        # ── 阶段2.7 全场景同因失败哨（2026-08-28）──
        # pass=0 且全部失败场景错误签名一致 → 疑环境/场景问题，呼叫 admin 介入
        # 判断；不判 bug-found、不派生 fix；连续 3 轮同因自动 blocked。
        if self._detect_uniform_verify_failure(spec_name, report):
            return fail_count, None, True

        # ── 阶段3 快道：全绿机械 verified（judge 效率治理 2026-09-06）──
        # 0 失败且 0 警告时 judge 无信息增量（无分类对象；洗白门禁仅在
        # 「0 通过或 env 失败」可触发，全绿恒无违规）——跳过 LLM 裁决
        # （常态 15-50 分钟），合成结果文件后走与 judge 完全同源的采纳
        # 尾段（进度核对/报告闸门/洗白门禁/transition）。tester_run 记
        # mechanical-all-green 留痕。
        judge_result = self._all_green_fast_path(spec_name, report, fail_count)
        return fail_count, judge_result, False

    # ── agent run 失败三让位单源（code-review item 04f7f14b2b54）──────
    # 首次派发（下方 _dispatch_judge_or_reuse）与裁决复读重派（fail-closed
    # 重派段）的 frozen_terminated / cancelled / provider 熔断三让位分支此前
    # 近乎逐行复制、仅日志措辞不同，靠注释约束同源易漂移——判定口径与写字段
    # 集合收敛本助手单点维护，调用点只保留各自差异化的日志文案。
    def _yield_on_agent_failure(self, spec_name: str, result) -> tuple:
        """judge/planner run 失败三让位（frozen/cancelled/provider 熔断）单源。

        返回 (让位原因, 写入 spec 的 error 文本)：原因 ∈ {"frozen_terminated",
        "cancelled", "provider_circuit"}；(None, "") 表示非让位类失败，调用点
        按各自车道语义处置（首次派发 raise → legacy 降级；重派路径写 blocked
        留痕）。

        判定口径：frozen_terminated/cancelled 用 ``is True``（防 MagicMock
        替身自动生成 truthy 属性误判让位，生产结果为显式 bool）；熔断按
        PROVIDER_CIRCUIT_ERROR_MARKER 子串匹配（与 FROZEN_TERMINATED_ERROR_PREFIX
        同一约定，防措辞漂移使匹配静默失效）。

        写字段集合（与让位语义「不写 blocked、不发告警」兼容）：
        - frozen_terminated → mark_frozen_hold（补 hold 标记：不落 _frozen_hold
          则解冻后 unfreeze_spec 的续做判定 _resolve_preserved_branch →
          _recovery_resume 不触发，重派侧 code-review item b7f86878b739；
          mark_frozen_hold 不改 status、不清锚点，保持原状）；
        - cancelled → error + _cancelled_hold 持久标记（fix-cancel-holdstate-
          recovery D1：只留 testing 原状不落标记，恢复链路 event_bus 派发早退 /
          admin_monitor 不按取消保持语义处置）；
        - provider_circuit → error + _record_infra_failure（evo-infra-failure-
          budget-exempt R2：熔断属 infra，归因入口前早退点挂预算退款与记账，
          与阶段1 circuit-open 同款；保持 testing 等待下轮重验，不按结构性
          失败处置为 blocked）。
        """
        if getattr(result, "frozen_terminated", False) is True:
            j_err = result.error or ""
            frozen_err = (
                f"judge run 因 spec 冻结被终止（进度已保全，解冻后续做）"
                f"{': ' + j_err if j_err else ''}"
            )
            self._context.state_machine.mark_frozen_hold(spec_name, frozen_err)
            return "frozen_terminated", frozen_err
        if getattr(result, "cancelled", False) is True:
            c_err = result.error or ""
            cancelled_err = f"run 被人工取消：{c_err}" if c_err else "run 被人工取消"
            self._context.state_machine.update_spec(
                spec_name,
                {
                    "error": cancelled_err,
                    # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                    "_cancelled_hold": True,
                },
            )
            return "cancelled", cancelled_err
        if PROVIDER_CIRCUIT_ERROR_MARKER in (result.error or ""):
            self._context.state_machine.update_spec(
                spec_name,
                {
                    "error": result.error,
                },
            )
            # 退款锚点回退 implementer_run（不传 run_id，87cfffac1d3c 契约）：
            # 本分支被 judge 首派/重派与 plan 首派三条车道共用，result 均为
            # attempt run 结果——attempt run id 作锚点会使每个 attempt 各自
            # 退款一次、按实现 run 的幂等去重失效；attempt id 经
            # ledger_run_id 只进失败台账，与 legacy/escalation 合规调用点同口径。
            self._record_infra_failure(
                spec_name,
                result.error,
                ledger_run_id=getattr(result, "run_id", "") or "",
            )
            return "provider_circuit", result.error
        return None, ""

    # ── B5: judge 派发与失败三让位 + D6 二次状态核对（等价搬移）──────
    # D1 B5 段落：_judge_dispatch_gate / judge 失败三让位分支 / D6 二次状态核对。
    # 返回 judge_result（成功）或 None（让位/核对不过，调用者 MUST return）。
    def _dispatch_judge_or_reuse(self, spec_name: str, judge_result) -> object:
        """judge 派发与失败三让位 + D6 二次状态核对（等价搬移自 B5）。

        快道未命中（judge_result None）→ 真实派发 judge（含稳定性复用门）；
        失败三让位（取消 hold-state / circuit 熔断 / 冻结让位）静默退出；
        无让位则 raise RuntimeError（触发外层 legacy 降级，与既有一致）。
        D6：judge run 完成时刻再核 spec 状态，非 testing 静默丢弃。
        """
        if judge_result is None:
            # ── 阶段3: Planner 判定结果 ──
            self._context.logger.info("pm_engine", f"[阶段3] Planner 判定: {spec_name}")
            # ── judge-rerun-stability R1：稳定性复用 + 重跑上限前置守卫 ──
            # 连续两轮 verdict 一致且 spec 戳/report.json 未变 → 复用上次结果
            # 不新起 judge run（叫停 add-web-ui 类 11 次空转重派）；judge run
            # 总数超上限（_MAX_JUDGE_RERUNS=5）→ blocked 转人工裁决。
            gate = self._judge_dispatch_gate(spec_name)
            if gate is False:
                return None  # 硬上限：已 blocked 等待人工裁决
            if gate is None:
                judge_result = self._pm.agent_runner.run_planner(spec_name, "judge")
            else:
                judge_result = gate  # 稳定性复用合成结果

        if not judge_result.success:
            # ── 失败三让位（判定/写字段单源：_yield_on_agent_failure，与
            # fail-closed 重派路径同口径）── frozen_terminated（spec 级 >
            # run 级，在 cancelled 之前）/ cancelled / provider 熔断的让位
            # 处置（含 hold 标记补写与 infra 记账）见助手；此处仅保留首次
            # 派发车道的日志文案（熔断期不得 raise → legacy 降级 → bug-found
            # → 伪 fix 级联）。
            yield_reason, yield_err = self._yield_on_agent_failure(
                spec_name, judge_result)
            if yield_reason == "frozen_terminated":
                self._context.logger.warning(
                    "pm_engine",
                    f"Planner judge run 因 spec 冻结被终止 — hold-state "
                    f"'{spec_name}'（保持原状）: {yield_err}",
                )
                return None
            if yield_reason == "cancelled":
                self._context.logger.warning(
                    "pm_engine",
                    f"Planner judge run 被人工取消 — hold-state '{spec_name}' "
                    f"(保持 testing): {yield_err}",
                )
                return None
            if yield_reason == "provider_circuit":
                self._context.logger.warning(
                    "pm_engine",
                    f"Provider circuit open — planner judge suppressed for "
                    f"'{spec_name}', holding testing (recovery re-dispatch): "
                    f"{yield_err}",
                )
                return None
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
                return None
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
            return None
        return judge_result

    # ── 并行出题产物消费（add-verify-lane-throughput 1.3）──────────────────

    # 在飞并行出题的有界等待：轮询间隔与超时（配置键
    # verify.parallel_planning_wait_timeout，秒）。超时即取消在飞 run 转串行
    # 重出，杜绝「并行出题 run 与串行重出同时可写 test_scenarios.json」。
    _PARALLEL_PLAN_WAIT_POLL_SECONDS = 5.0
    _PARALLEL_PLAN_WAIT_TIMEOUT_DEFAULT = 900

    def _consume_parallel_plan_product(self, spec_name: str, verify_dir) -> bool:
        """testing 进入时消费并行出题产物（就绪短路 / 损坏回落 / 在飞等待）。

        返回 False 表示并行出题在飞且状态已迁移（人工接管），调用方 MUST
        return 丢弃本流水线；返回 True 表示可继续正常流程（产物有效 → 下方
        冻结复用分支直接命中 = 零出题短路；产物缺失/损坏已隔离 → frozen=None
        走既有串行出题回落通道）。

        判定全部以并行出题状态标记（parallel_plan.json）为准，无标记/已消费
        → 行为与现状一致（frozen 复用或串行出题，零新逻辑）。任何异常
        fail-open 返回 True（回落正常流程，绝不因消费校验故障打断验证轮）。
        """
        try:
            lane = self._context.parallel_plan_lane
            marker = lane.read_marker(spec_name) or {}
            status = marker.get("status")
            if status in (None, "consumed"):
                return True
            if status == "dispatched":
                # ── 在飞：有界等待（spec Scenario「testing 进入时并行出题仍在飞」）──
                deadline = time.monotonic() + self._parallel_plan_wait_timeout()
                prefix = f"planner-plan-{spec_name}-"
                _liveness_gap_logged = False
                while time.monotonic() < deadline:
                    # 等待期间状态迁移（人工接管）→ 丢弃本流水线（D6 同语义）
                    _wait_status = (
                        self._context.state_machine.read_one(spec_name) or {}
                    ).get("status")
                    if _wait_status != "testing":
                        self._context.logger.debug(
                            "pm_engine",
                            f"Parallel plan wait aborted for '{spec_name}' "
                            f"(current state '{_wait_status}') — spec no longer "
                            f"in testing, pipeline dropped",
                        )
                        return False
                    # 标记重读前置（code-review item 7eb06bcdfd58）：产物就绪
                    # （status != dispatched，如 completed）即短路退出等待循环，
                    # 无论存活探测是否可用——下方 hasattr 缺失分支旧实现直接
                    # sleep+continue 跳过标记重读，run 已正常写出产物仍空转到
                    # 超时出口才兜底消费（缺省 900 秒/轮固定白等）。
                    marker = lane.read_marker(spec_name) or {}
                    status = marker.get("status")
                    if status != "dispatched":
                        break
                    # run 已死（daemon 重启丢队列/attempt 收尾未写标记）→ 停等。
                    # 停等前重读一次标记：run 写出 completed 标记与从
                    # 在飞登记表移除之间存在竞窗，沿用上一轮轮询读到的
                    # 陈旧 dispatched 会走超时分支，对刚完成的有效产物执行
                    # stop+quarantine 并触发一次不必要的串行重出。重读后按最新
                    # 状态分流：completed 落下方产物消费分支，仅确仍 dispatched
                    # 才取消并隔离。
                    # code-review item f0aa2cd44923：存活探测落空（runner 桩/
                    # 代差未暴露 is_run_alive）≠ run 已死。旧代码 None or {}
                    # 落空即按存活集为空 break 停等 → 取消在飞 run + 隔离半成品，
                    # 把接线故障误判成 run 死亡。ERROR 留痕（每次等待至多一条）
                    # 后跳过存活分支继续轮询：真 run 正常写出 completed 标记
                    # 仍按产物就绪消费；真死亡/超时由下方超时出口按既有语义
                    # 兜底（取消转串行）。
                    # code-review item 305dcbb105c3：判活改查 AgentRunner 公开
                    # 接口 is_run_alive，不读 _running_agents 私有登记表。
                    if not hasattr(self._pm.agent_runner, "is_run_alive"):
                        if not _liveness_gap_logged:
                            _liveness_gap_logged = True
                            self._context.logger.error(
                                "pm_engine",
                                f"并行出题在飞等待存活探测不可用 '{spec_name}' — "
                                f"agent_runner 未暴露 is_run_alive（接线缺口/桩），"
                                f"跳过「run 已死」判定继续轮询，不取消在飞 run",
                            )
                        time.sleep(self._PARALLEL_PLAN_WAIT_POLL_SECONDS)
                        continue
                    if not self._pm.agent_runner.is_run_alive(prefix):
                        marker = lane.read_marker(spec_name) or {}
                        break
                    time.sleep(self._PARALLEL_PLAN_WAIT_POLL_SECONDS)
                if marker.get("status") == "dispatched":
                    # 超时出口同样重读一次标记（与 run 死亡分支同款防护）：run
                    # 可能在最后一次轮询读取与超时判定之间刚写出 completed 标记，
                    # 按最新状态分流，仅确仍 dispatched 才取消并隔离，否则落下
                    # 走产物消费/回落通道。
                    marker = lane.read_marker(spec_name) or {}
                    if marker.get("status") == "dispatched":
                        # 超时（或 run 死亡未写标记）：取消在飞 run、隔离半成品、
                        # 转串行重出（既有回落通道）。
                        lane.stop(spec_name, "并行出题等待超时，取消后转串行重出")
                        lane.quarantine(
                            spec_name, "testing 等待并行出题超时，半成品隔离"
                        )
                        lane.write_marker(
                            spec_name,
                            {"status": "discarded", "reason": "wait_timeout"},
                        )
                        self._context.logger.warning(
                            "pm_engine",
                            f"并行出题等待超时 '{spec_name}' — 已取消在飞 run 并"
                            f"隔离半成品，转串行重出",
                        )
                        return True
                status = marker.get("status")
            if status == "completed":
                # ── 产物就绪：过既有校验（可解析 + load_scenarios 验收）→ 短路 ──
                ok, reason = self._validate_parallel_product(spec_name, verify_dir)
                if ok:
                    lane.write_marker(
                        spec_name, {"status": "consumed", "consumed_scenarios": reason}
                    )
                    self._context.logger.info(
                        "pm_engine",
                        f"[阶段1] 并行出题产物就绪，短路出题直接进场景执行 "
                        f"'{spec_name}'（{reason} 个场景）",
                    )
                    return True
                # 损坏/契约不匹配：隔离坏产物 + 串行重出（既有回落通道，
                # 场景 Scenario「并行产物损坏回落串行出题」）
                lane.quarantine(spec_name, f"产物校验不过: {reason}")
                lane.write_marker(
                    spec_name, {"status": "discarded", "reason": str(reason)[:200]}
                )
                self._context.logger.warning(
                    "pm_engine",
                    f"并行出题产物校验不过 '{spec_name}' — 已隔离并转串行重出: "
                    f"{reason}",
                )
                return True
            # failed / cancelled / frozen / discarded：产物已被车道隔离，走串行
            self._context.logger.info(
                "pm_engine",
                f"并行出题未产出可用场景 '{spec_name}'（status={status}）— "
                f"按既有串行出题路径执行",
            )
            return True
        except Exception as e:  # fail-open：消费校验异常不阻断验证轮
            self._context.logger.warning(
                "pm_engine",
                f"并行出题产物消费异常 '{spec_name}'（回落正常流程）: "
                f"{type(e).__name__}: {e}",
            )
            return True

    def _parallel_plan_wait_timeout(self) -> float:
        raw = self._context.config_reader(
            "verify.parallel_planning_wait_timeout",
            self._PARALLEL_PLAN_WAIT_TIMEOUT_DEFAULT,
        )
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return float(self._PARALLEL_PLAN_WAIT_TIMEOUT_DEFAULT)

    def _validate_parallel_product(self, spec_name: str, verify_dir) -> tuple:
        """并行产物就绪校验（同一文件、既有校验口径：可解析 + 验收通过）。

        Returns: (True, 场景数) 或 (False, 失败原因)。import 留函数体内（D4：
        scenarios 模块在 _reload_verify_engine_modules reload 清单内）。
        """
        from core.verify_engine.scenarios import load_scenarios

        path = verify_dir / "test_scenarios.json"
        if not path.is_file():
            return False, "产物文件缺失"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            return False, f"JSON 不可解析: {type(e).__name__}"
        if not isinstance(raw, list):
            return False, f"根节点非数组（{type(raw).__name__}）"
        try:
            scenarios = load_scenarios(path)
        except ValueError as e:
            return False, f"场景验收失败: {str(e)[:200]}"
        return True, len(scenarios)

    def _run_three_stage_verification(self, spec_name: str, _repair_depth: int = 0):
        """三步验证流水线主逻辑。"""
        # 入口状态判据：非 testing → 丢弃本流水线结果（D6，见 _check_entry_status）
        if not self._check_entry_status(spec_name):
            return

        # 重新加载验证引擎模块（D4：VerifyEngine/load_scenarios 的 import 保持
        # 在运行时函数体内——_execute_stage2 方法体内执行，测试靠
        # patch("core.verify_engine.VerifyEngine") 生效）。
        self._reload_verify_engine_modules()

        # ── 阶段1+2: Planner↔场景验收闭环（2026-08-28）──
        # 场景验收（绝对 navigate URL/完整性）失败 → 写 REPLAN_FEEDBACK.md 退回
        # plan 阶段重新生成，上限 2 次重排；连续失败保持 implemented + error
        # 可见（验收失败属环境/任务书问题，绝非产品缺陷，绝不流转 bug-found）。
        verify_dir = self._context.project_root / ".fenix" / "verify-progress" / spec_name
        replan_left = 2
        # 记录初始预算：预算耗尽分支渲染已执行重排次数（彼时 replan_left 恒为 0，
        # 直接插值会恒显示「0 次用尽」，与实际已重排次数不符）。
        initial_replan_budget = replan_left
        replan_feedback = None
        # fix-replan-feedback-injection：上一轮验收错误原文——连续两轮一字不差说明
        # planner 未消费反馈（重跑即纯烧钱），升级为 ERROR 提示人工关注。
        prev_replan_error = None
        report = None
        app_reachable = True
        reach_note = ""
        # ── 并行出题产物消费（add-verify-lane-throughput 1.3）──
        # 先于冻结加载：产物就绪且过既有校验 → 标记 consumed，下方冻结复用
        # 分支直接命中（零出题短路）；产物缺失/损坏 → 已隔离，frozen=None 走
        # 既有串行出题回落通道；并行出题仍在飞 → 有界等待或取消后串行重出，
        # 全程保证任意时刻至多一个 planner-plan run 可写 test_scenarios.json。
        # 返回 False = 等待期间状态已迁移（人工接管），丢弃本流水线。
        if not self._consume_parallel_plan_product(spec_name, verify_dir):
            return

        # ── 契约 serve 一致性门（evo-add-scenario-serve-consistency-preflight 1.2）──
        # 消费前统一挂点，覆盖冻结复用与并行产物两条短路路径：test_scenarios.json
        # 在盘（冻结集或并行产物）即先过契约静态检查再消费，kind 集与契约能力
        # 不匹配时 serve 缺失打回（_write_verify_contract_missing 信号通道 +
        # env 阻塞升级，返回 True → 终止本轮流水线，不触发 planner replan）。
        # 产物未落盘（纯新鲜出题轮）此处零情报放行，主路径挂点在出题验收后。
        if self._run_contract_static_check(spec_name):
            return

        # ── 场景冻结加载 + 损坏升级（见 _load_frozen_or_escalate）──
        frozen, _frozen_aborted = self._load_frozen_or_escalate(spec_name, verify_dir)
        if _frozen_aborted:
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
                    # 早退前清侧车（code-review item 88d58ec1565d）：本轮到不了
                    # _execute_stage2 消费点，写回失败轮随行携带的整份内存迁移
                    # 集在此 pop，防滞留实例字典至下轮（常驻进程累积）。
                    self.__dict__.get("_stage2_scenarios_override", {}).pop(
                        spec_name, None
                    )
                    return
                # 覆盖完整 → 落入下方阶段2（共享执行段）
            else:
                if replan_feedback is not None:
                    fb = verify_dir / "REPLAN_FEEDBACK.md"
                    try:
                        fb.parent.mkdir(parents=True, exist_ok=True)
                        # 按失败类别生成收尾指引（evo-scenario-product-toplevel-
                        # contract 2.2）：格式类给「最小修复」指引，内容类保留
                        # 「重新输出全部场景」（见 _replan_feedback_text）。
                        fb.write_text(
                            self._replan_feedback_text(replan_feedback, spec_name),
                            encoding="utf-8",
                        )
                    except OSError as e:
                        # 反馈写入失败不中止验证轮（code-review item
                        # 18400c48083e）：磁盘满/权限等 OSError 若上抛会被外层
                        # engine 捕获整轮回滚，而反馈缺失仅降低重排针对性
                        # （planner 照常重出题）——WARNING 留痕后继续重排流程
                        # （与下方验收通过处 unlink 捕 OSError 同口径）。
                        self._context.logger.warning(
                            "pm_engine",
                            f"REPLAN_FEEDBACK.md 写入失败 '{spec_name}'"
                            f"（非阻塞，重排继续，仅丢失针对性反馈）: "
                            f"{type(e).__name__}: {e}",
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
                    # ── 失败三让位（判定/写字段单源：_yield_on_agent_failure，
                    # code-review item d2bce687564b，与 judge 车道
                    # _dispatch_judge_or_reuse 同口径）── frozen_terminated
                    # （spec 级 > run 级，在 cancelled 之前；助手补
                    # mark_frozen_hold 锚点，解冻时 unfreeze_spec 据此走
                    # _resolve_preserved_branch 续做恢复，原 code-review item
                    # 3a96e083bf0d 的让位语义不变）/ cancelled（error +
                    # _cancelled_hold 保持标记，add-run-cancel D4）/ provider
                    # 熔断（error + infra 记账，fix-fix-stashpop-deadlock +
                    # evo-infra-failure-budget-exempt R2）的写字段集合均由
                    # 助手单点承载；此处仅保留 plan 车道的日志文案（不得
                    # raise → legacy 降级 → bug-found → 伪 fix 级联）。
                    yield_reason, yield_err = self._yield_on_agent_failure(
                        spec_name, plan_result)
                    if yield_reason == "frozen_terminated":
                        self._context.logger.warning(
                            "pm_engine",
                            f"Planner plan run 因 spec 冻结被终止 — hold-state "
                            f"'{spec_name}'（进度已保全，解冻后续做，不降级不重派）: "
                            f"{yield_err}",
                        )
                        return
                    if yield_reason == "cancelled":
                        self._context.logger.warning(
                            "pm_engine",
                            f"Planner plan run 被人工取消 — hold-state '{spec_name}' "
                            f"(保持 testing): {yield_err}",
                        )
                        return
                    if yield_reason == "provider_circuit":
                        self._context.logger.warning(
                            "pm_engine",
                            f"Provider circuit open — planner suppressed for '{spec_name}', "
                            f"holding testing (recovery re-dispatch): {yield_err}",
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
                    # 时长统一空值守卫（code-review item 30f5b0c0c57e）：与下方
                    # _write_degrade_context 的 `or 0` 同口径，防 duration_seconds
                    # 可空（或测试以替身注入）时 f-string 除法 TypeError。
                    _dur = plan_result.duration_seconds or 0
                    _dur_min = _dur / 60
                    self._context.state_machine.update_spec(
                        spec_name,
                        {
                            "error": (
                                f"Planner 场景生成无效（status={plan_status_text}，run="
                                f"{plan_result.run_id}，{_dur_min:.1f}min）"
                                f"— 降级旧版验证流程"
                            ),
                        },
                    )
                    self._context.logger.error(
                        "pm_engine",
                        f"Planner 未生成有效场景 '{spec_name}'（status={plan_status_text}，"
                        f"run={plan_result.run_id}，白烧 "
                        f"{_dur_min:.1f}min）— 降级旧版 verifier",
                    )
                    # add-planready-artifact-gate D3：降级前落盘上下文
                    # （供 verify_report 合成路径注入降级标注，G3）。
                    self._write_degrade_context(
                        spec_name,
                        reason=(f"Planner 未生成有效场景，status={plan_status_text}"),
                        run_id=plan_result.run_id,
                        duration_seconds=_dur,
                    )
                    raise RuntimeError(f"Planner 未生成有效场景，status={plan_status_text}")

                # add-planready-artifact-gate D3：plan-ready 校验通过（新一轮验证
                # 正常启动）→ 删除陈旧 degrade_context.json，防旧降级事实污染后续
                # 正常报告（成功时才清理，失败/重验路径历史留痕）。
                self._clear_degrade_context(spec_name)

                # ── 契约 serve 一致性门（planner-contract-findings D4 +
                # evo-add-scenario-serve-consistency-preflight 1.2）──
                # planner-plan 产物验收通过后（出题完成处）：对验证契约做只读
                # 一致性检查并落盘 contract_findings.json（既有三条规则 fail-open
                # 留痕不阻断出题）；serve 缺失 cross finding 打回——走
                # _write_verify_contract_missing 通道阻断场景执行、派发
                # Administrator 起草，不触发 planner replan（重排出题无助于
                # 契约缺口）。
                if self._run_contract_static_check(spec_name):
                    return

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
                        # 内容类缺失（写前预校验整批拒绝，design D3）：保留
                        # 全量重建指示，不按格式类生成最小修复指引。
                        self.__dict__.setdefault("_replan_error_format_class", {})[spec_name] = False
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
                    # 比照 env_error 退回的预算耗尽分支（本方法 env_error 段
                    # replan_left<=0 分支：预算耗尽即置 implemented + error 显式结束）：
                    # 置 implemented + error 显式结束本轮，ERROR 留痕。
                    self._context.state_machine.update_spec(
                        spec_name,
                        {
                            "status": "implemented",
                            "tester_run": None,
                            "error": (
                                f"场景写前预校验整批拒绝且重排预算耗尽"
                                f"（已重排 {initial_replan_budget - replan_left} 次）: "
                                f"{reject_detail[:280]}"
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
                        # 内容类缺失（交互契约覆盖缺口，design D3 同空集兜底
                        # 口径）：比照上方空集分支复位格式类侧车——上一验证
                        # 轮格式类失败置 True 后预算耗尽 return 残留 True 时，
                        # 本分支发生在 _execute_stage2 复位点之前，不复位会把
                        # 内容类反馈渲染成「最小修复」指引（code-review item
                        # 9d08c65949f2）。
                        self.__dict__.setdefault("_replan_error_format_class", {})[spec_name] = False
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
                    # 与 serving 层同口径（serving._ensure_serving_worktree 调用
                    # 侧的 static_scope 读取）：worktree 作用域下 serve.root 的
                    # 存在性以 serving worktree 侧为准（code-review item
                    # 1846f874b03c），主树侧缺失不在此判死
                    static_scope=str(
                        self._context.config_reader("verify.static_scope", "main") or "main"
                    )
                    .strip()
                    .lower(),
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
                # 早退前清侧车（code-review item 88d58ec1565d）：同覆盖缺口
                # 早退口径——本轮到不了 _execute_stage2 消费点。
                self.__dict__.get("_stage2_scenarios_override", {}).pop(
                    spec_name, None
                )
                return

            # ── 阶段2: 验证引擎执行（见 _execute_stage2，D2：env_error 回写段留循环体）──
            scenarios_path = (
                self._context.project_root
                / ".fenix"
                / "verify-progress"
                / spec_name
                / "test_scenarios.json"
            )
            env_error, report, app_reachable, reach_note, _stage2_aborted = self._execute_stage2(
                spec_name, verify_dir, scenarios_path
            )
            if _stage2_aborted:
                return

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
                                f"场景验收连续失败（退回 plan "
                                f"{initial_replan_budget - replan_left} 次仍不通过）: "
                                f"{env_error[:280]}"
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

        # ── B4: 阶段2 门禁 + 全绿快道（见 _run_stage2_gates）──
        fail_count, judge_result, _gates_aborted = self._run_stage2_gates(
            spec_name, report, app_reachable, reach_note,
            user_blocked=self.__dict__.get("_stage2_user_blocked", {}).get(spec_name, False),
        )
        if _gates_aborted:
            return
        # ── B5: judge 派发与失败三让位 + D6 二次状态核对（见 _dispatch_judge_or_reuse）──
        judge_result = self._dispatch_judge_or_reuse(spec_name, judge_result)
        if judge_result is None:
            return

        # ── 阶段3+ 裁决证据分类校验与重试（add-verdict-evidence-taxonomy D1-D5；
        #    fix-verdict-retry-misattribution D1/D2/D5/D7）──
        verdict_ret = self._verify_verdict_evidence(spec_name, retry_judge=True)
        if not verdict_ret["ok"]:
            self._handle_verdict_evidence_rejection(spec_name, verdict_ret)
            return
        # ── 阶段3+ 裁决采纳（judge 通道）──
        verdict_read = self._read_verdict_failclosed(spec_name, judge_run=judge_result)
        if verdict_read is None:
            return
        verifier_result, verifier_status = verdict_read
        # ── 阶段3+ 场景原地修复通道（judge-scenario-repair，见 _handle_scenario_repaired）──
        if self._handle_scenario_repaired(spec_name, verifier_status, _repair_depth):
            return
        # code-review bcb9a3b4d640：plan-ready 裁决＝验证未完成，不按通过收口
        # （与 legacy 车道 06ca08e65666 防线对齐）。judge 读侧白名单含 plan-ready
        # （与 planner-plan 读取路径共享单一来源，MUST NOT 改白名单本身），judge
        # 输出契约漂移产出 plan-ready 时若落入下方 else → _apply_verified，会在
        # 进度核对/报告闸门/洗白门禁可能全过的报告上被假收敛为 verified——
        # plan-ready＝场景已（重）生成、执行阶段尚未真实跑过。比照 legacy
        # 「验证未完成」分支：保持 testing 留 error、WARNING 留痕，由
        # full_scan recovery 兜底重排重验。scenario-repaired/bug-found 已由
        # 上方专门分支消费，此守卫只拦 plan-ready，落到此后的平铺尾段即纯
        # verified。
        if verifier_status == "plan-ready":
            # 写点前状态复核（code-review item 07b2d311e10d，与 legacy
            # 「验证未完成」分支同口径收敛于 _discard_if_not_testing）：
            # _read_verdict_failclosed 入口核对到本写点之间隔着证据校验/
            # 不可读重派（judge 重派常态 15-50 分钟）与场景修复通道等长
            # 耗时步骤，窗口内 spec 可能被人工复位/冻结接管/并发 attempt
            # 接管——非 testing 时 DEBUG 丢弃，不覆写较新状态的
            # error/tester_run。
            if _discard_if_not_testing(self, spec_name, judge_result, verifier_status):
                return
            self._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": judge_result.run_id,
                    "error": (
                        f"验证未完成：裁决 status={verifier_status}"
                        f"（场景计划裁决不按通过收口），保持 testing 待重验"
                    ),
                },
            )
            self._context.logger.warning(
                "pm_engine",
                f"验证未完成 '{spec_name}'：plan-ready 裁决不按通过收口"
                f"（status={verifier_status}），保持 testing 待重验",
            )
            return
        if verifier_status == "bug-found":
            self._apply_bug_found(spec_name, judge_result, report, _repair_depth)
            return
        self._apply_verified(spec_name, judge_result, report)
        return


# ── env 阻塞复位判定（add-blocked-reverify-lane D2）────────────────
# 决定 env 阻塞 spec 在 admin 处置完成后走哪条复位路径：BLOCKED→TESTING 重验
# 直通道（实现分支已合并）还是既有 BLOCKED→READY 全量重实现。模块级函数（非
# VerificationPipeline 方法）：admin_monitor 处置收尾消费点直接 import 复用，
# 两处共享同一守卫判定，避免语义漂移。

# env 族信号类型：仅这些信号触发的 blocking 复位才适用重验直通道判定，其余
# 信号（如 blocked_stuck 等）的复位语义不动。
ENV_BLOCK_SIGNAL_TYPES = ("verify_env_blocked", "verify_env_inconclusive")
