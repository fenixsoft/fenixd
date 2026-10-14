"""
engine.py — PMEngine 门面（Project Management Engine for fenixd）.

Handles SPEC auto-review, Agent scheduling, priority management,
concurrency control, daily reporting, and the single human gate (push approval).
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.timelib import parse_ts
from core.archive_commit import archive_residue_spec, scan_archive_residue
from core.dashboard.data import (
    find_impl_run_file,
    get_runs,
    parse_run_task_done,
    record_project_event,
)
from core.agent_runner.run_files import (
    RUN_ID_AGENT_PREFIXES,
    infer_run_agent_type,
    run_spec_part,
    strip_run_id_suffixes,
)
from core.run_task_track import (
    _TASK_CHECKBOX_RE,
    parse_tasks_md,
    parse_unattainable as _parse_unattainable,
)
from core.verify_scenarios import VERIFY_FIX_SECTION_RE
from core.worktree_manager.shape import branch_shape_is_verifier
from core.pm_engine.family import FamilyGovernor
from core.pm_engine.budget import ImplBudget
from core.pm_engine.spec_integrity import SpecIntegrityGate
from core.pm_engine.verification import VerificationPipeline
from core.pm_engine.dispatch import Dispatcher
from core.pm_engine.recovery import RecoveryWatch
from core.pm_engine.reporting import ReportBuilder
from core.pm_engine.dispatch import (
    DEFAULT_DISPATCH_BACKOFF_SCHEDULE,
)
from core.pm_engine import TASK_GAP_ERROR_PREFIX  # noqa: E402
from core.pm_engine.recovery import (
    SIGNAL_RECOMMENDATION_DISPATCH_STALLED,
    RECOVERY_WATCH_FILE,
    DEFAULT_FOLLOWUP_CHECK_MINUTES,
    DEFAULT_SIGNAL_COOLDOWN_MINUTES,
)
from core.state_machine import (
    FREEZE_ERROR_PREFIX,
    FROZEN_FIELD,
    FROZEN_UNTIL_FIELD,
    PUSH_ATTEMPTS_FIELD,
    PUSH_BACKOFF_NEXT_RETRY_AT_FIELD,
    START_AFTER_FIELD,
    SpecStatus,
    parse_orig_status,
    parse_utc,
    start_after_pending,
)

# 假就绪巡检：ready 滞留超过该阈值且期间无派发活动 → 阻塞项（design D6）
DEFAULT_READY_STALL_THRESHOLD_MINUTES = 20

# ── 同因重派熔断易变段剔除正则（fix-redispatch-loop-governance D3/D3.1）──
# 归因文案指纹计算前的易变段剔除（见 PMEngine._redispatch_cause_fingerprint）：
# 1. run_id 形态 impl-<spec>-<epoch>[-aN][-rN]（spec 名可含连字符，贪婪消费到
#    尾部至少一个「-数字」段即 epoch，再可选 -aN/-rN 后缀）；
# 2. 9 位以上数字（时间戳 / epoch / pid）；
# 3. worktree 路径（…/.claude/worktrees/impl-… 形态）。
# 1. run_id 形态（可选带 run=/run_id= 标签）impl-<spec>-<epoch>[-aN][-rN]
#   （spec 名可含连字符，贪婪消费到尾部至少一个「-数字」段即 epoch，再可选
#   -aN/-rN 后缀）；标签仅在接受显式分隔符（=_:\s 或空白）后消费，避免把
#   「running」这类普通词吞掉（防归一化过度 → 不同因误判同因）。
_REDISPATCH_RUN_ID_RE = re.compile(
    r"(?:(?:run|run_id)\s*[=_:\s-]+\s*)?impl-[A-Za-z0-9._-]+(?:-[0-9]+){1,}"
    r"(?:-[a-z][0-9]+)?(?:-r[0-9]+)?"
)
_REDISPATCH_TIMESTAMP_RE = re.compile(r"\b\d{9,}\b")
_REDISPATCH_WT_PATH_RE = re.compile(r"(?:/[\w.-]*)*/\.claude(?:/[\w.-]+)*")

# 依赖闸门接受态（fix-dispatch-wakeup-gap D2 单点口径）：依赖 SPEC 转入这些
# 状态之一时，等待中的 dependents 视为「依赖满足」——EventBus 据此定向唤醒
# dependents 重评（dispatch-dependency-wakeup 1.1），_dependencies_satisfied
# 依此判定。接受态集合单点定义，杜绝「闸门说满足、唤醒说不够」的双口径漂移；
# 未来引入新终态只需改此处。
DEPENDENCY_ACCEPTED_STATUSES = ("done", "pushed", "implemented", "verified")

# 派发冷却窗口（双派发穿透原地修 2026-09-06）：成功派发后该窗口内同 spec 的重复
# _on_spec_ready 触发一律跳过。窗口需覆盖 dispatch→create 拿锁的亚秒窗口与失败
# 回写 ready 外溢的秒级重入；合法重试（Retry/full_scan 周期/退避定时器）间隔为
# 分钟级，不受影响。
DISPATCH_COOLDOWN_SECONDS = 10
# 派发冷却登记 _last_dispatch_at 无界增长防护（code-review item 8c6c06bb595e）：
# spec 归档/删除后条目无删除路径，daemon 常驻数月 + spec 数千规模下缓慢增长；
# 超上限时在写入入口按时间淘汰最旧（近似 LRU，被淘汰 spec 的冷却判据必已远超窗口）。
_LAST_DISPATCH_AT_MAX = 10000


# ── 派发前同源草案收敛检查（evo-deliverable-declaration-drift-align D3）──────
# SUPERSEDED.md 显式点名解析（「以显式点名为唯一判据」）：被取代目录名以 inline
# code（反引号）或路径形态出现在该页正文中（现行实例「**生效实现落点**：
# ``spec/changes/evo-merge-back-wip-overlap-gate-575976/``」即此形态）。MUST NOT
# 依赖 ``.spec.yaml`` 的 capability 字段——实测全仓 ``.spec.yaml`` 无 capability
# 键，文档自述的「capability + name 归一」不可实现。
_SUPERSEDED_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def _parse_superseded_named_targets(text: str) -> list:
    """从 SUPERSEDED.md 正文解析显式点名的目录名（inline code / 路径形态）。

    ``spec/changes/<name>/`` 路径形态与裸 ``<name>`` inline code 归一为目录名；
    排除 ``spec/changes/`` 前缀之外的无斜杠 token（非 spec 目录点名）、空 token
    与不含目录名字符集（字母数字/连字符/点）的 token（如中文叙述夹带的反引号
    片段）。

    Returns:
        点名目录名列表（去重、保序）；无点名/解析异常返回 []。
    """
    names: list = []
    if not text:
        return names
    for tok in _SUPERSEDED_INLINE_CODE_RE.findall(text):
        tok = tok.strip().strip("/")
        if tok.startswith("spec/changes/"):
            rest = tok[len("spec/changes/"):]
            if not rest:
                continue
            name = rest.split("/", 1)[0]
        elif "/" not in tok and tok and tok != "SUPERSEDED.md":
            name = tok
        else:
            continue
        # 目录名字符集校验（spec 目录名形态：字母数字开头，仅字母数字/连字符/点）
        if not re.fullmatch(r"[A-Za-z0-9][\w.-]*", name or ""):
            continue
        if name and name not in names:
            names.append(name)
    return names


def _scan_superseded_docs(project_root) -> dict:
    """扫描 spec/changes/ 下所有 SUPERSEDED.md 并解析显式点名（D3 第 1/2 条）。

    Returns:
        {目录名: {"superseded": bool, "named_targets": [目录名, ...]}}（保序）；
        spec/changes/ 不存在/不可读 → {}。
    """
    changes_dir = Path(project_root) / "spec" / "changes"
    out: dict = {}
    if not changes_dir.is_dir():
        return out
    for d in sorted(changes_dir.iterdir()):
        if not d.is_dir():
            continue
        sup = d / "SUPERSEDED.md"
        info: dict = {"superseded": False, "named_targets": []}
        if sup.is_file():
            try:
                text = sup.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                text = ""
            info["superseded"] = True
            info["named_targets"] = _parse_superseded_named_targets(text)
        out[d.name] = info
    return out


def _superseded_name_peers(spec_name: str, scan: dict) -> list:
    """名字归一识别平级同名草案（D3 第 3 条：仅识别，不拦截）。

    本 spec 目录名去掉数字后缀（``_NUM_SUFFIX_RE``，同源 core/evolution.py:1498；
    ``-<6位 id>`` / ``-_575976`` 均由此产生，见 evolution.py:1040-1042）后与其
    它目录名相等的 → 平级同名草案清单。两侧含义不同（对方含 SUPERSEDED.md=生效
    落点不拦本方；本方含 SUPERSEDED.md=拦截本方）统一由调用方以「本方是否含
    SUPERSEDED.md」裁定，MUST NOT 单凭归一命中拦截生效落点（被点名的生效落点
    与收敛源按名字归一会互为命中，误拦会把生效草案永久冻住）。

    Returns:
        平级同名草案目录名列表（保序）。
    """
    from core.evolution import _NUM_SUFFIX_RE

    base = _NUM_SUFFIX_RE.sub("", spec_name, count=1)
    peers: list = []
    for name in scan:
        if name == spec_name:
            continue
        if _NUM_SUFFIX_RE.sub("", name, count=1) == base:
            peers.append(name)
    return peers


# evo-add-worktree-acquire-backoff 1.3：新验证流程降级累计计数器。
# MUST 为模块级——PMEngine 按 run 重建实例，实例级计数恒为 1、无法统计
# 降级频率；WARNING 附「第 N 次降级」供日志保留窗内统计降级频率。
_NEW_VERIFIER_FALLBACK_COUNT = 0


class PMEngine:
    """
    Project Management Engine — the brain of fenixd.

    Responsibilities:
      - Auto-promote drafted → ready
      - Schedule implementer for ready SPECs
      - Schedule verifier for implemented SPECs
      - Handle bug-found → create fix SPECs
      - Enforce concurrency limits
      - Generate project reports
      - Manage the push approval gate
      - Periodic blocker detection and health reporting
    """

    # ── 门面转发注册表（refactor-facade-delegation D2 / facade-inventory.md）──
    # 实例式转发（100 个）：{门面方法名: (子对象属性名, 目标方法名)}。子对象
    # 属性为惰性 property（`_verification`/`_dispatcher`/`_family`/`_budget`/
    # `_recovery`/`_reporting`/`_spec_integrity`，正常查找命中不触发
    # `__getattr__`），`__getattr__` 经 `getattr(self, 子对象属性名)` 触发惰性
    # 构造后返回 `getattr(子对象, 目标方法名)`。注册表以源码内联 dict 声明
    # （静态可读）；未知名 / dunder 名 MUST `raise AttributeError`。
    _FORWARDER_REGISTRY: dict[str, object] = {
        "_resolve_fix_spec_name": ("_family", "_resolve_fix_spec_name"),
        "_ensure_fix_spec_files": ("_family", "_ensure_fix_spec_files"),
        "_family_width": ("_family", "_family_width"),
        "_family_waiver_set": ("_family", "_family_waiver_set"),
        "_consume_family_waiver": ("_family", "_consume_family_waiver"),
        "_family_gate_blocked": ("_family", "_family_gate_blocked"),
        "_same_root_siblings": ("_family", "_same_root_siblings"),
        "_sibling_repair_active": ("_family", "_sibling_repair_active"),
        "_sibling_has_live_agent": ("_family", "_sibling_has_live_agent"),
        "_has_non_terminal_child_fix": ("_family", "_has_non_terminal_child_fix"),
        "_signal_family_explosion": ("_family", "_signal_family_explosion"),
        "_do_spec_bug_found": ("_family", "_do_spec_bug_found"),
        "_do_legacy_fix_spec_bug_found": ("_family", "_do_legacy_fix_spec_bug_found"),
        "_inject_verify_fix_task": ("_family", "_inject_verify_fix_task"),
        "_send_human_escalation_alert": ("_family", "_send_human_escalation_alert"),
        "_impl_run_budget": ("_budget", "_impl_run_budget"),
        "_increment_impl_run_budget_used": ("_budget", "_increment_impl_run_budget_used"),
        "_budget_exempt_alert_threshold": ("_budget", "_budget_exempt_alert_threshold"),
        "_exempt_dead_run_budget": ("_budget", "_exempt_dead_run_budget"),
        "_exempt_infra_run_budget": ("_budget", "_exempt_infra_run_budget"),
        "_alert_budget_exempt_loop": ("_budget", "_alert_budget_exempt_loop"),
        "_reconcile_impl_budget": ("_budget", "_reconcile_impl_budget"),
        "_count_normal_completed_impl_runs": ("_budget", "_count_normal_completed_impl_runs"),
        "_impl_run_budget_used": ("_budget", "_impl_run_budget_used"),
        "_check_impl_budget_exhausted": ("_budget", "_check_impl_budget_exhausted"),
        "_check_spec_content_missing": ("_spec_integrity", "check_spec_content_missing"),
        "_read_verify_report": ("_verification", "_read_verify_report"),
        "_handle_env_blocked_inconclusive": ("_verification", "_handle_env_blocked_inconclusive"),
        "_ensure_app_reachable": ("_verification", "_ensure_app_reachable"),
        "_rewrite_scenario_port": ("_verification", "_rewrite_scenario_port"),
        "_current_verify_round": ("_verification", "_current_verify_round"),
        "_apply_scenario_freeze": ("_verification", "_apply_scenario_freeze"),
        "_run_scenario_static_check": ("_verification", "_run_scenario_static_check"),
        "_scenario_defect_reroute_gate": ("_verification", "_scenario_defect_reroute_gate"),
        "_apply_interaction_contract": ("_verification", "_apply_interaction_contract"),
        "_render_scenario_change_section_to_report": ("_verification", "_render_scenario_change_section_to_report"),
        "_run_three_stage_verification": ("_verification", "_run_three_stage_verification"),
        # verified 应用收口（ocr join 停等唤醒续做 queue._resume_verified_after_ocr
        # 调用）：经门面单跳（design D3 规则 3），组件不直引 _verification 私有链。
        "_apply_verified": ("_verification", "_apply_verified"),
        # spec 终局 serving 驱逐单跳（code-review item c75a912b260f）：
        # _on_spec_verified 的 done 落定回收经门面，不直穿 _verification 私有链。
        "_evict_spec_serving": ("_verification", "_evict_spec_serving"),
        "_verifier_error_is_infra": ("_verification", "_verifier_error_is_infra"),
        "enrich_failure_class": ("_verification", "enrich_failure_class"),
        "_verifier_result_is_stale": ("_verification", "_verifier_result_is_stale"),
        "_implementer_zero_change": ("_verification", "_implementer_zero_change"),
        "_implementation_branch_has_commits": ("_verification", "_implementation_branch_has_commits"),
        "_deliverable_gate_missing": ("_verification", "_deliverable_gate_missing"),
        "_tasks_md_relint_from_branch": ("_verification", "_tasks_md_relint_from_branch"),
        "_tasks_md_relint_from_worktree": ("_verification", "_tasks_md_relint_from_worktree"),
        "_disputed_deliverables": ("_verification", "_disputed_deliverables"),
        "_adjudicate_deliverable_missing": ("_dispatcher", "_adjudicate_deliverable_missing"),
        "_preclassify_orphan": ("_dispatcher", "_preclassify_orphan"),
        "_preclassify_drift": ("_dispatcher", "_preclassify_drift"),
        "_detect_uniform_verify_failure": ("_verification", "_detect_uniform_verify_failure"),
        "_run_legacy_verification": ("_verification", "_run_legacy_verification"),
        "_verify_verdict_evidence": ("_verification", "_verify_verdict_evidence"),
        "_speculative_bug_found_gate": ("_verification", "_speculative_bug_found_gate"),
        "_env_whitewash_gate": ("_verification", "_env_whitewash_gate"),
        "_escalate_env_blocked": ("_verification", "_escalate_env_blocked"),
        "_record_infra_failure": ("_verification", "_record_infra_failure"),
        "_update_warning_streaks": ("_verification", "_update_warning_streaks"),
        "_warning_stale_triage_alert": ("_verification", "_warning_stale_triage_alert"),
        "_ensure_verification_report": ("_verification", "_ensure_verification_report"),
        "_check_verification_gate": ("_verification", "_check_verification_gate"),
        "_read_verifier_result": ("_verification", "_read_verifier_result"),
        "_read_planner_result": ("_verification", "_read_planner_result"),
        "_read_verdict": ("_verification", "_read_verdict"),
        "_judge_bugs_declare_env": ("_verification", "_judge_bugs_declare_env"),
        "_handle_judge_env_declared": ("_verification", "_handle_judge_env_declared"),
        "_verdict_violations_path": ("_verification", "_verdict_violations_path"),
        "_write_verdict_violations": ("_verification", "_write_verdict_violations"),
        "_clear_verdict_violations": ("_verification", "_clear_verdict_violations"),
        "_read_fail_history": ("_verification", "_read_fail_history"),
        "_append_fail_history": ("_verification", "_append_fail_history"),
        "_clear_fail_history": ("_verification", "_clear_fail_history"),
        "_failed_scenario_ids": ("_verification", "_failed_scenario_ids"),
        "_dispatch_backoff_schedule": ("_dispatcher", "_dispatch_backoff_schedule"),
        "_handle_dispatch_lock_conflict": ("_dispatcher", "_handle_dispatch_lock_conflict"),
        "_schedule_backoff_retry": ("_dispatcher", "_schedule_backoff_retry"),
        # 评审 content 短退避接线（code-review item f5dde260460c）：
        # SpecReviewManager._enqueue_review_retry 经门面 getattr 取这两个名字，
        # 未注册则恒得 None、退避链路死置（生产回到秒级连发烧光重试预算）。
        # 判重集合挂 _dispatcher（QQQueueMixin.__init__ 初始化）存续，排程器
        # 在 BBackoffMixin——与 _enqueue/_process_queue 同款注册表转发。
        "_schedule_recovery_timer": ("_dispatcher", "_schedule_recovery_timer"),
        "_review_content_backoff_timers": (
            "_dispatcher",
            "_review_content_backoff_timers",
        ),
        "_get_spec_priority": ("_dispatcher", "_get_spec_priority"),
        "_enqueue": ("_dispatcher", "_enqueue"),
        "_enqueue_front": ("_dispatcher", "_enqueue_front"),
        # 车道在队条目摘除单跳（code-review item c75a912b260f）：
        # _stop_parallel_planning / _reclaim_verify_lane 摘在队条目经门面，
        # 不直穿 _dispatcher 私有链。
        "_remove_queued_entry": ("_dispatcher", "_remove_queued_entry"),
        "_aging_bonus": ("_dispatcher", "_aging_bonus"),
        "_effective_priority": ("_dispatcher", "_effective_priority"),
        "_process_queue": ("_dispatcher", "_process_queue"),
        "_run_agent_worker": ("_dispatcher", "_run_agent_worker"),
        "_rollback_failed_dispatch": ("_dispatcher", "_rollback_failed_dispatch"),
        "_report_stash_pop_conflict": ("_dispatcher", "_report_stash_pop_conflict"),
        "_run_fast_track_worker": ("_dispatcher", "_run_fast_track_worker"),
        # fast-track 重启恢复重入单跳（code-review item c75a912b260f）。
        "_resume_fast_track_after_restart": (
            "_dispatcher",
            "_resume_fast_track_after_restart",
        ),
        "_should_enter_repair": ("_dispatcher", "_should_enter_repair"),
        "_dispatch_repair_lane": ("_dispatcher", "_dispatch_repair_lane"),
        "_claim_repair_site": ("_dispatcher", "_claim_repair_site"),
        "_run_repair_worker": ("_dispatcher", "_run_repair_worker"),
        "_check_repair_commit_facts": ("_dispatcher", "_check_repair_commit_facts"),
        "_handle_remerge_failure": ("_dispatcher", "_handle_remerge_failure"),
        "_fallback_after_repair": ("_dispatcher", "_fallback_after_repair"),
        # fix-fasttrack-implemented-deadstate 2.1：在飞 impl-ocr 车道公开判定
        # （_is_idle 第五维 + fast-track 恢复三条件③共用，带参/无参双口径）。
        "ocr_lane_busy": ("_dispatcher", "ocr_lane_busy"),
        "_recovery_watch_path": ("_recovery", "_recovery_watch_path"),
        "_load_recovery_watch": ("_recovery", "_load_recovery_watch"),
        "_save_recovery_watch": ("_recovery", "_save_recovery_watch"),
        "register_recovery_watch": ("_recovery", "register_recovery_watch"),
        "check_recovery_watch": ("_recovery", "check_recovery_watch"),
        "_signal_dispatch_stalled": ("_recovery", "_signal_dispatch_stalled"),
        "_clear_dispatch_conflict": ("_recovery", "_clear_dispatch_conflict"),
        "generate_report": ("_reporting", "generate_report"),
        "generate_daily_report": ("_reporting", "generate_daily_report"),
        "get_pushable_specs": ("_reporting", "get_pushable_specs"),
        # dev-server 收割单跳（code-review item 227d772b3847）：repair 车道三处
        # 收割点改经门面，不再穿透 agent_runner 私有链——与 _apply_verified
        # （525fd816c134）同一收敛方向，私有方法重命名只在注册表一处断链。
        "_stop_devserver_for_worktree": ("agent_runner", "_v2_stop_for_worktree"),
    }

    def __getattr__(self, name: str):
        """门面转发统一委托（refactor-facade-delegation D1/D2）。

        注册表内实例式转发经此解析；未知名 / dunder 名 `raise AttributeError`
        （hasattr/getattr(..., default) 语义正确）。惰性 property 是类属性，
        正常查找命中，不会走到这里。"""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}")
        target = type(self)._FORWARDER_REGISTRY.get(name)
        if target is None:
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}")
        sub_attr, meth = target
        return getattr(getattr(self, sub_attr), meth)

    def __dir__(self):
        """IDE 补全增强（refactor-facade-delegation Open Question / tasks 5.1）：
        返回既有属性 + 注册表键，缓解 `__getattr__` 委托下 dir() 不显示转发名。"""
        return sorted(set(super().__dir__()) | set(type(self)._FORWARDER_REGISTRY))

    def __init__(self, state_machine, agent_runner, config: dict, project_root: Path, logger):
        self.state_machine = state_machine
        self.agent_runner = agent_runner
        self.config = config
        self.project_root = project_root
        self.logger = logger

        # 评审在飞查询回路注入（fix-spec-review-blocking-dispatch 3.7）：_
        # active_reviews 由 DispatchQueue 持有，reviewer_in_flight（agent_runner
        # 侧组件）需经 pm_engine 门面查询（agent_runner 不持 pm_engine）。
        # 显式约定回引字段（_pm_engine_ref），与 worktree_manager 的
        # state_reader 注入同族；测试以 MagicMock 替代 agent_runner 时赋值无害。
        try:
            agent_runner._pm_engine_ref = self
        except Exception:
            pass

        # evo-add-run-stop-loss 1.3（B 装配）：并行出题标记读取回调注入——
        # runner 的 in-place retry 让位判据（_parallel_plan_marker_discarded）
        # 经此回调读并行出题状态标记（_read_parallel_plan_marker），让让位
        # 判据在真实派发链路生效；runner 不引入对 pm_engine 的模块依赖
        # （沿 _pm_engine_ref 显式回引字段先例，测试以 MagicMock 替代
        # agent_runner 时赋值无害）。
        try:
            agent_runner._parallel_plan_marker_reader = (
                self._read_parallel_plan_marker)
        except Exception:
            pass

        self._handling_events = set()  # 防重入：正在处理的 (event_kind, spec_name)
        # 队列/并发状态与锁随 Dispatcher 组件同迁（design D3 规则 1，单锁语义不变）

        # 优雅关闭标志（fix-admin-self-heal）：daemon 关闭期间禁止派发新 agent，
        # 否则 shutdown 的 wait_for_running_agents 会陷入「杀一个又起一个」的死循环
        self.shutting_down = False

        # Blocker detection state
        self._last_blocker_report_time = None

        # 派发单飞守卫（fix-startup-double-dispatch）：跟踪正在派发中的 spec，
        # 防止启动扫描与事件回放对同一 spec 的重复派发
        self._pending_dispatches: set = set()
        # 单飞/防重入守卫互斥锁（code-review 5ecd0d3047d1）：_pending_dispatches 与
        # _handling_events 的「检查 + 登记」两步须在本锁内一次完成——EventBus 监听
        # 线程、full_scan 扫描线程、退避定时器与主循环可并发进入，裸 set 的
        # check-then-act 分离存在双派发竞态窗口（对齐 approve_push 的 _push_lock
        # 实例锁先例）。锁内仅做 set 操作、不外呼，不可重入无死锁风险。
        self._dispatch_guard_lock = threading.Lock()
        # 主树散件 WIP 盘点器（evo-add-maintree-stray-wip-sweep 2.1）：懒创建
        # （首次 sweep 时按 agent_runner.worktree_manager 句柄装配），first_seen
        # 注册表随实例进程内持有（D5）。
        self._stray_wip_sweeper = None
        # 派发冷却登记（双派发穿透原地修 2026-09-06）：spec -> 上次成功派发时刻。
        # 单飞键只覆盖「同时在飞」——dispatch 流程 <50ms 返回后标记即释放，而锁要等
        # run 线程执行 create() 才可见：full_scan 与 STATE 监听/spec_ready 双通道在
        # ~50ms 内连发两派、失败回写 ready 的 Retry 外溢 ~1s 内触发第三派，均在
        # has_active_worktree 可见之前穿透（2026-09-06 add-spec-scheduling-controls
        # 事故）。冷却窗口内重复触发跳过，是 dispatch→create 窗口的兜底防线。
        self._last_dispatch_at: dict = {}

        # done→pushed 全链单飞锁（fix-daemon-lifecycle-races D5）：approve_push
        # 的全临界区（status 重读 → git push → transition(pushed)）持本锁执行，
        # check-then-act 原子化。并发第二流在锁上排队，进入后见 pushed 即幂等
        # 跳过——消除双 git push main / 重复 project log / pushed→pushed ERROR。
        # 全局锁而非 per-spec 锁：不同 spec 并发 push main 的竞态同样需要串行。
        self._push_lock = threading.Lock()

        # 恢复闭环复查注册表随 RecoveryWatch 组件同迁（design D3 规则 1）；
        # 此处触发加载（.fenix/recovery_watch.json → 组件内存态）。
        self._recovery._load_recovery_watch()

        # 链路级 infra 熔断器（evo-run-failure-classification-circuitbreaker D2）：
        # 连续 infra 失败达阈值 → 熔断评审链路停止派发，冷却后自动恢复。状态持久化
        # .fenix/admin_infra_breaker.json（daemon 重启后恢复）；懒加载在 __init__
        # 尾部创建，供 _on_spec_reviewing 短路与 SpecReviewManager 计数共用。
        from core.pm_engine.infra_breaker import InfraCircuitBreaker

        self.infra_breaker = InfraCircuitBreaker(self.project_root, self.config, self.logger)

        # 组合组件预热（code-review item 97824267c225）：六个惰性 property 的
        # 「__dict__ 判空 → 构造 → 回写」两步之间无锁，属非原子 check-then-act。
        # __init__ 只显式触达了 _recovery（上方 _load_recovery_watch），_dispatcher
        # 等的首次触达落在多线程运行期（EventBus 监听线程先于 initial full_scan
        # 启动，可与主循环并发首触同一 property）——双线程各建一个实例时后写者
        # 覆盖 __dict__ 缓存而先到者继续持旧实例，两实例的 _queue_lock/_run_queue
        # 互不同一：入队进旧列表即丢失、锁互斥失效（同型于 5ecd0d3047d1 收敛的
        # check-then-act 分离竞态）。对齐 _recovery 预热先例，在单线程 __init__
        # 期逐一显式触达一次完成构造；property 的惰性路径保留，测试以
        # PMEngine.__new__ 绕过 __init__ 的实例仍安全。
        self._family
        self._budget
        self._spec_integrity
        self._verification
        self._dispatcher
        self._reporting

    # ── Event Handlers ─────────────────────────────────────────────

    def handle_event(self, event_kind: str, spec_name: str, spec_entry: dict):
        """
        Handle an internal event from the EventBus.
        This is the main scheduling entry point.
        """
        # 防重入：同一 (event, spec) 正在处理中则跳过，打破 event bus 二次派发回路。
        # 检查与登记在同一把实例级互斥锁内原子完成（code-review 5ecd0d3047d1），
        # 消除并发 check-then-act 竞态窗口；锁内仅做 set 操作，不外呼。
        event_key = (event_kind, spec_name)
        with self._dispatch_guard_lock:
            already_handling = event_key in self._handling_events
            if not already_handling:
                self._handling_events.add(event_key)
        if already_handling:
            self.logger.debug(
                "pm_engine",
                f"Skipping duplicate event: {event_kind} for '{spec_name}'",
            )
            return

        try:
            self.logger.info(
                "pm_engine",
                f"Handling event: {event_kind} for '{spec_name}'",
            )

            handlers = {
                "spec_drafted": self._on_spec_drafted,
                "spec_ready": self._on_spec_ready,
                "spec_implemented": self._on_spec_implemented,
                "spec_verified": self._on_spec_verified,
                "spec_bug_found": self._on_spec_bug_found,
                "spec_done": self._on_spec_done,
                "spec_reviewing": self._on_spec_reviewing,
            }

            handler = handlers.get(event_kind)
            if handler:
                handler(spec_name)

            # Process any queued runs
            self._process_queue()
        finally:
            self._handling_events.discard(event_key)

    def _on_spec_drafted(self, spec_name: str):
        """Auto-promote drafted → ready, then immediately schedule implementer.

        Gates: if gates.promote_mode is 'manual', spec stays drafted
        (no promotion, no error, no dispatch) — awaiting manual promotion.
        """
        # 并行出题回退停派（add-verify-lane-throughput 1.2）：spec 出现 drafted
        # 事件即视为状态回退（打回 drafted 或初次创建——初次创建时无在飞并行
        # 出题，本调用为幂等 no-op），摘除在队条目并终止在飞并行出题 run。
        self._stop_parallel_planning(spec_name, "spec 状态回退 drafted")
        # add-start-after-scope-config D1：start_after 定时拾取门控（对齐
        # _on_spec_ready 既有守卫，engine.py:552）——本入口受
        # gates.start_after_scope 条件门控：full 时行为同 fix-start-after-premature-pickup
        # （drafted + 未到期/哨兵的 SPEC 不得被任何自动通道晋升——扫描
        # （_dispatch_changes）、恢复（_recover_one）、以及本文件的
        # _on_spec_drafted → _on_spec_reviewing 同 handler 直调均汇聚于此，覆盖面以
        # handler 入口为界）；dispatch 时回到 fix-start-after-premature-pickup 之前的
        # 旧行为（立即晋升，仅实现派发等到期）。守卫置于 promote_mode 闸口之外：
        # manual 晋升模式与定时拾取门互不替代（1.5 人工放行豁免见 D1 末条——CLI
        # promote / Dashboard 晋升按钮直调共享函数 promote_drafted，不经本方法）。
        # 有意放行（D1 通道 ③④）：check_scheduling_deadlines（60s 到期唤起）与
        # _check_scheduling_kick_requests（清空/激活 kick 信号）在调用本方法前已
        # 确认到期/激活——到期后 start_after_pending 返回 False、清空/激活后字段
        # 置 null 亦返回 False，故此处正常放行，无需特判。
        try:
            from core.state_machine import start_after_blocks_promotion

            entry = self.state_machine.read_one(spec_name)
            # entry 为 None（SPEC 已删除/归档）时 MUST NOT 早退——promote_drafted
            # 自带 not-found 拒绝与日志，是既有语义，守卫不得抢先吞掉（D2 落点约定）。
            if entry is not None and start_after_blocks_promotion(entry, self.config):
                self.logger.debug(
                    "pm_engine",
                    f"Skipping '{spec_name}': start_after pending (scheduled pickup)",
                )
                return
        except Exception as e:
            # fail-open：判定异常不吞既有晋升能力（对齐 _recover_ready 既有守卫）
            self.logger.warning(
                "pm_engine",
                f"start_after 门控判定异常 '{spec_name}'（fail-open 放行）: {e}",
            )

        from core.config import ConfigLoader
        from core.pm_engine.promotion import promote_drafted

        # 草稿晋升闸口（add-draft-promotion-gate D1）：manual 时 drafted SPEC
        # 停留草稿态，不软化、不 lint、不写 error、不派发。等待人工通过
        # Dashboard 按钮、CLI promote 或 /fenix-ready 放行。
        if ConfigLoader.get_promote_mode(self.config) != "auto":
            self.logger.info(
                "pm_engine",
                f"草稿晋升为 manual，SPEC '{spec_name}' 停留 drafted 等待人工放行",
            )
            return

        # 共享晋升函数：软化 + lint + 判定（D2 提取）
        result = promote_drafted(
            self.project_root,
            spec_name,
            state_machine=self.state_machine,
            logger=self.logger,
            config=self.config,
        )
        if not result["ok"]:
            # lint 违规或非 drafted 拒绝：error 已由 promote_drafted 写入 STATE（lint 违规），
            # 或返回拒绝原因（非 drafted）。两种情况都不派发。
            return
        # 全部通过：根据 next_status 分流
        # transition 返回值必须接收（code-review item ec560df1bb0d，对齐
        # check_blockers 0b464aaa47b8 / _on_spec_verified dc13e7dc5cb3 /
        # approve_push f3173b3164ee 口径）：promote_drafted 判定到真实转移之间
        # 存在竞窗（外部改动/并发晋升致转移被拒），被拒时不得直调收口派发——
        # 靠下游 _process_queue 候选筛选兜底属口径不一致残留，在此断链。
        next_status = result.get("next_status", "ready")
        if next_status == "ready":
            self.logger.info("pm_engine", f"Auto-promoting '{spec_name}': drafted → ready")
            # fix-observability-gaps 2.2：自动晋升来源（无 run，channel=auto）
            moved = self.state_machine.transition(
                spec_name, "ready",
                trigger_run_id=None, agent_type="pm-engine", channel="auto",
            )
            if not moved:
                self.logger.warning(
                    "pm_engine",
                    f"Promotion transition '{spec_name}' drafted→ready rejected "
                    f"(state changed externally) — skip implementer dispatch",
                )
                return
            # 直接调用 _on_spec_ready 排队实现，不依赖事件循环
            self._on_spec_ready(spec_name)
        elif next_status == "reviewing":
            self.logger.info("pm_engine", f"Auto-promoting '{spec_name}': drafted → reviewing")
            # fix-observability-gaps 2.2：自动晋升来源
            moved = self.state_machine.transition(
                spec_name, "reviewing",
                trigger_run_id=None, agent_type="pm-engine", channel="auto",
            )
            if not moved:
                self.logger.warning(
                    "pm_engine",
                    f"Promotion transition '{spec_name}' drafted→reviewing rejected "
                    f"(state changed externally) — skip spec-review dispatch",
                )
                return
            # 派发评审 run
            self._on_spec_reviewing(spec_name)
        else:
            self.logger.error("pm_engine", f"未知 next_status: {next_status}")

    # 晋升 lint（deliverables 声明形态 / tasks.md 可解析性）唯一实现在
    # core/pm_engine/promotion.py 的模块级 _lint_deliverable_declarations /
    # _lint_tasks_parseable，由 promote_drafted 调用；此处不再保留副本。

    def _on_spec_reviewing(self, spec_name: str):
        """处理 spec_reviewing 事件：评审条目入队（异步、不阻塞调用方线程）。

        改造（fix-spec-review-blocking-dispatch 2.1/2.2）：评审派发不再在调用方
        线程同步阻塞执行——``_enqueue(spec_name, "spec-review")`` 只写队列即返回，
        真正的 run 由 ``_process_queue`` → ``_run_agent_worker`` 的 spec-review
        分支在独立 worker 线程执行（与 implementer 完全同构，design D1）。调用方
        线程（MainThread / fenixd-watcher / fenixd-scanner / 定时拾取）立即恢复，
        主循环不再被分钟级评审 run 钉死（2026-09-19 事故：daemon 27 分钟不进
        主循环、五个文件信号消费者全部停摆）。
        """
        # add-start-after-scope-config D1：start_after 定时拾取门控（对齐
        # _on_spec_ready 既有守卫）——本入口受 gates.start_after_scope 条件门控：
        # full 时 reviewing + 未到期/哨兵的 SPEC 不得被派发评审 run（同
        # fix-start-after-premature-pickup 行为）；dispatch 时回到旧行为（立即派发）。
        # 守卫插在方法体最前面（早于双判据单飞与熔断短路）。有意放行
        # （D1 通道 ③④）：到期 / 清空 / 激活后 start_after_pending 返回 False
        # 正常放行。人工重评（SpecReviewManager.re_review）与评审否决后自动复评
        # 改造后均改为入队（spec_review.py:393/:880，tasks 2.6/2.7），与本入口
        # 同走 `_enqueue`——队列去重吸收重复触发，不再有「绕过守卫」的通道。
        try:
            from core.state_machine import start_after_blocks_promotion

            entry = self.state_machine.read_one(spec_name)
            # entry 读不到（SPEC 已删除/归档）时跳过守卫判定（不早退），交由既有
            # 链自然处理（D2 落点约定）。
            if entry is not None and start_after_blocks_promotion(entry, self.config):
                self.logger.debug(
                    "pm_engine",
                    f"Skipping '{spec_name}': start_after pending (scheduled pickup)",
                )
                return
        except Exception as e:
            # fail-open：判定异常不吞既有评审派发能力（对齐 _recover_ready 既有守卫）
            self.logger.warning(
                "pm_engine",
                f"start_after 门控判定异常 '{spec_name}'（fail-open 放行）: {e}",
            )
        # ── 双判据单飞守卫（fix-spec-review-blocking-dispatch 2.2 / design D4）──
        # 异步化后调用方立即返回，旧守卫 `_review_dispatches`（靠「同步阻塞整个
        # 评审期」成立）已移除——它派发即释放，窗口敞开。两组互补判据任一命中即
        # 拒绝本次派发，贯穿评审 run 从入队到收口的全生命周期：
        #   ① `_active_reviews` 命中（条目已入队 / 已出队未收口）——经
        #      DispatchQueue 暴露的只读查询 `is_review_in_flight`；
        #   ② STATE 的 `reviewer_run` 非空且 run 确在飞（`reviewer_in_flight`
        #      在飞结论 in_flight==True）——覆盖「锚点已落盘但 run 尚未注册进
        #      进程表」的窗口。陈旧锚点（stale）判为无在飞评审放行入队，由
        #      dispatch_review 入口清理后继续派发（防 stale 卡死 reviewing）。
        if self.is_review_in_flight(spec_name):
            self.logger.debug(
                "pm_engine", f"Skipping duplicate review dispatch: '{spec_name}'"
            )
            return
        entry = self.state_machine.read_one(spec_name) or {}
        reviewer_run = entry.get("reviewer_run")
        if reviewer_run:
            try:
                in_flight, reason = self.agent_runner.reviewer_in_flight(
                    spec_name, reviewer_run
                )
            except Exception as e:
                # 判定异常 fail-open 放行（对齐既有门控容错；异常是否构成在飞由
                # dispatch_review 入口重判兜底）
                self.logger.warning(
                    "pm_engine",
                    f"在飞评审判定异常 '{spec_name}'（fail-open 放行）: {e}",
                )
                in_flight, reason = False, None
            if in_flight:
                self.logger.info("pm_engine", f"已有在飞评审 run: {spec_name}")
                return
            if reason == "stale":
                self.logger.warning(
                    "pm_engine",
                    f"陈旧评审锚点（run 已终态）按无在飞评审放行; "
                    f"待派发清理: {spec_name} run={reviewer_run}",
                )
        # 链路级熔断短路（evo-run-failure-classification-circuitbreaker D2）：
        # spec-review 链路熔断窗口内直接返回不派发；冷却到期自动恢复重试。
        cond = self.infra_breaker.condition("spec-review")
        if cond == "broken":
            remaining = self.infra_breaker.cooldown_remaining("spec-review")
            self.logger.info("pm_engine", f"评审派发熔断短路: '{spec_name}'，冷却剩余 {remaining}s")
            return
        if cond == "recovered":
            # 冷却到期自动恢复：落恢复 SIGNAL 记录（D3，恰好一条）
            self._emit_infra_breaker_event(
                "recovered", spec_name, "", self.infra_breaker.get_state("spec-review")
            )
        # 入队评审（只写队列即返回）+ 立即触发队列处理（tasks 1.11：「晋升即
        # 评审」不依赖 30 分钟周期扫描兜底；handle_event 尾部已有一次
        # _process_queue，此处补一次覆盖 re_review / 复评等直入队入口）。
        self._enqueue(spec_name, "spec-review")
        self._process_queue()

    def _on_spec_ready(self, spec_name: str):
        """Schedule implementer for ready SPEC (if dependencies are satisfied)."""
        # 优雅关闭期间不再派发（fix-admin-self-heal）
        if self.shutting_down:
            return

        # 派发冷却窗口（双派发穿透原地修 2026-09-06）：成功派发后短窗口内同 spec
        # 的重复触发（STATE 监听 + spec_ready 双通道、失败回写 Retry 外溢）直接跳过。
        # 此刻锁尚未由 run 线程 create() 加上，has_active_worktree 不可见。跳过不写
        # STATE（避免「写 error → 触发 spec_ready 事件」的自触发热循环），重派由
        # Retry/full_scan 周期兜底。
        last_dispatch = self._last_dispatch_at.get(spec_name)
        if last_dispatch is not None and (time.time() - last_dispatch) < DISPATCH_COOLDOWN_SECONDS:
            self.logger.debug(
                "pm_engine",
                f"Skipping dispatch for '{spec_name}': cooldown window active",
            )
            return

        # 派发单飞守卫（fix-startup-double-dispatch）：原子检查并登记是否已在派发中
        # 同一 spec 的并发 spec_ready 处理只放行一个；单飞标记须在 worktree 锁
        # 创建之前占位，封死启动窗口。检查与登记在同一把实例级互斥锁内完成
        # （code-review 5ecd0d3047d1），消除多线程并发触发时的 check-then-act
        # 竞态窗口；锁内仅做 set 操作，不外呼。
        with self._dispatch_guard_lock:
            already_pending = spec_name in self._pending_dispatches
            if not already_pending:
                # 标记为正在派发（在任何异步操作之前）
                self._pending_dispatches.add(spec_name)
        if already_pending:
            self.logger.debug(
                "pm_engine",
                f"Skipping duplicate dispatch for '{spec_name}': already pending",
            )
            return

        try:
            # 防双派发：该 spec 已有活动 implementer worktree 时跳过。
            # 背景（fix-fenix-token-waste）：启动扫描与 event_bus 都会触发 spec_ready，
            # 第二次派发因 worktree 锁失败会把 spec 打回 ready，形成空转反馈环。
            if self.agent_runner.worktree_manager.has_active_worktree(spec_name):
                # 活 run 持锁 ≠ 冲突：有存活 attempt 子进程时静默跳过，不计冲突、
                # 不进退避（与 full_scan recovery 的「live child present」白名单同语义，
                # 复用其 D4 接口 has_live_attempt）。
                # 背景（fix-admin-run-blocks-mainloop 事故 2026-09-01）：外部 drafted 写入
                # 触发 spec_ready 二次派发，与活 run 撞锁把退避链重计至耗尽，误报
                # dispatch_stalled 并循环呼叫 Administrator。
                try:
                    live = self.agent_runner.has_live_attempt(spec_name)
                except Exception:
                    live = False
                if live:
                    self.logger.debug(
                        "pm_engine",
                        f"Skipping '{spec_name}': worktree lock held by live attempt",
                    )
                    return
                # 锁治理（improve-run-lifecycle-governance D5）：锁冲突进入退避计划，
                # 不硬试、不消耗 attempt 配额（2026-08-27 add-spec-context-menu 事故：
                # 孤儿 resume 持锁，派发 ~15s 内三连发耗尽 retries exhausted，spec 假死）。
                self._handle_dispatch_lock_conflict(spec_name)
                return
            # 退避期内静默跳过（不写 STATE，避免「写 error → 触发 spec_ready 事件」
            # 的自触发热循环）；退避到期后由排定的定时器 / 周期扫描重试。
            spec = self.state_machine.read_one(spec_name) or {}
            # frozen 复核（alert-noise-governance 2.2）：冻结 spec 不进派发——
            # daemon 重启后 _diff_specs 空快照会把 frozen=True 的 ready spec
            # 整批回放 spec_ready，缺本守卫即重放「派发→闸门拦截→冻结」并每
            # 轮产一条闸门 ERROR（2026-09-22 实证 9 轮重放 18 条 ERROR）。
            # 位于闸门内容校验（dispatch._process_queue 内）之前，冻结 spec 不
            # 再重放拦截流程；复用 _frozen_state 助手保持 legacy 文本契约兼容
            # （recovery.py in-place redispatch 同款先例）。命中 INFO 留痕、
            # 零 STATE 写入（防「写 error → 触发 spec_ready」自触发热循环）。
            # 人工 kick 冻结 spec 走同一入口，冻结 spec 的人工重派本就该先解
            # 冻（「补内容后人工 unfreeze_spec」契约），本留痕保证操作者可见
            # 跳过原因。
            if self._frozen_state(spec):
                self.logger.info(
                    "pm_engine",
                    f"Skipping dispatch for '{spec_name}': frozen spec "
                    f"(awaiting manual unfreeze, frozen-replay guard)",
                )
                return
            if self._dispatch_backoffed(spec):
                self.logger.debug(
                    "pm_engine",
                    f"Skipping '{spec_name}': dispatch backoff active",
                )
                return
            # add-spec-scheduling-controls D2：start_after 未到期静默跳过（对齐退避
            # 门控的「不写 error 不翻状态」防自触发设计）。
            # 派发入口全覆盖核对结论（任务清单 2.2，2026-09-06）：
            #   - event_bus full_scan recovery（_recover_ready）与 STATE.md watcher
            #     状态变更 → handle_event("spec_ready") → 本方法；
            #   - boot recovery（recover_interrupted 重置为 ready）→ full_scan →
            #     _recover_ready → 本方法（recovery.py 无独立派发入口，只重置状态）；
            #   - _on_spec_drafted 晋升后同步直调 → 本方法；
            #   - _schedule_backoff_retry / _on_instant_fail_recovery 定时器回调 → 本方法；
            #   - family._do_spec_bug_found 的 fix 唤起 → 本方法。
            # 其余绕过本方法的直入队列路径（_enqueue 的 implementer/fast-track/
            # repair/verifier 条目，如 auto-recovery 的 ready 重派、失败重派）在
            # dispatch._process_queue 候选筛选处等价过谓词（两处 start_after_pending）。
            if start_after_pending(spec):
                self.logger.debug(
                    "pm_engine",
                    f"Skipping '{spec_name}': start_after pending (scheduled pickup)",
                )
                return
            if not self._dependencies_satisfied(spec_name):
                self.logger.info(
                    "pm_engine",
                    f"Skipping '{spec_name}': dependencies not satisfied",
                )
                return
            # ── 派发前在飞评审校验（evo-spec-concurrency-flight-guard D2 +
            # fix-spec-review-blocking-dispatch 3.5 放宽）──
            # 同 spec 存在在飞 spec-review run 时顺延本次派发：不创建实现 run、
            # 不写 STATE/error、不更新 _last_dispatch_at（顺延不计冷却起点），
            # 待评审收尾经既有 _on_spec_ready 重触发通道（spec_review.py 收口
            # 调用）重判。陈旧锚点（run 已终态但结果未消费/历史残留）判为
            # 「无在飞评审」放行并记 WARNING（D0 第 4 条，fail-open 防自造死锁）。
            # 3.5：前置条件由「reviewer_run 非空」放宽为「reviewer_run 非空 或
            # _active_reviews 命中」——评审条目已入队、锚点尚未落盘的窗口内，
            # 实现派发 MUST NOT 因锚点为空而穿透（spec-concurrency-governance
            # Requirement 2 的「顺延」语义；缺口由 reviewer_in_flight 的
            # "queued" 前置判据闭合：空锚点 + 在飞登记 → in_flight=True）。
            reviewer_run = spec.get("reviewer_run")
            if reviewer_run or self.is_review_in_flight(spec_name):
                try:
                    in_flight, reason = self.agent_runner.reviewer_in_flight(
                        spec_name, reviewer_run
                    )
                except Exception as e:
                    # 判定异常 fail-open（D0 第 5 条，对齐既有门控容错）
                    self.logger.warning(
                        "pm_engine",
                        f"在飞评审判定异常 '{spec_name}'（fail-open 放行）: {e}",
                    )
                    in_flight, reason = False, None
                if in_flight:
                    self.logger.info(
                        "pm_engine",
                        f"在飞评审 run，派发顺延: {spec_name} run={reviewer_run}",
                    )
                    return
                if reason == "stale":
                    self.logger.warning(
                        "pm_engine",
                        f"陈旧评审锚点（run 已终态）按无在飞评审放行; "
                        f"待既有恢复路径清理: {spec_name} run={reviewer_run}",
                    )
            # 派发前同源草案收敛检查（evo-deliverable-declaration-drift-align
            # D3）：本 spec 目录自身含 SUPERSEDED.md（已被取代，不再作为独立
            # 实现入口）→ 禁止派发、置 blocked（error=同源草案收敛义务未满足，
            # 附 SUPERSEDED.md 路径），待收敛（该 SUPERSEDED.md 移除或目录删除）
            # 后由后续周期重评恢复。被 SUPERSEDED.md 显式点名为生效落点的一侧
            # （自身无 SUPERSEDED.md）MUST NOT 被拦截。旁路直入队列的条目
            # （定时重派/恢复车道）由 _process_queue 候选筛选处以同口径兜底。
            try:
                convergence = self._check_superseded_convergence(spec_name)
            except Exception as e:
                # 检查异常 fail-open：不因检查故障阻塞派发（保守放行，
                # 与其它派发前闸门的 fail-open 取向一致）
                convergence = {"blocked": False, "error": None}
                self.logger.warning(
                    "pm_engine",
                    f"同源草案收敛检查异常 '{spec_name}'（fail-open 放行）: {e}",
                )
            if convergence.get("blocked"):
                # 写前重读复核（code-review item f9e6461bbd96，对齐
                # check_blockers auto-recovery「竞争后到者视为无需操作」先例，
                # 上游先例 check_scheduling_deadlines 定时解冻）：轮首 read_one
                # 快照到此处隔着冻结/退避/依赖/在飞评审判据与
                # _check_superseded_convergence 的全目录文件 IO 扫描，窗口内
                # 队列 worker 可能已消费早前入队的 implementer 条目并把 spec
                # 转入 implementing；盲写会把合法进度覆写回 blocked（worktree
                # 锁仍被在飞 run 持有，run 收尾与 STATE 失配）。状态已非 ready
                # 即让位于在飞进度，跳过本次收敛拦截、不派发；收敛义务由后续
                # full_scan / spec_ready 周期重评兜底。
                fresh = self.state_machine.read_one(spec_name) or {}
                if fresh.get("status") != "ready":
                    self.logger.info(
                        "pm_engine",
                        f"同源草案收敛拦截竞争后到者：'{spec_name}' 状态已为 "
                        f"'{fresh.get('status')}'，让位于在飞进度，跳过本次 "
                        f"blocked 拦截与派发（收敛义务留待后续周期重评）",
                    )
                    return
                self.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "blocked",
                        "tester_run": None,
                        "error": convergence.get("error") or "同源草案收敛义务未满足",
                    },
                )
                self.logger.error(
                    "pm_engine",
                    f"同源草案收敛义务拦截派发 '{spec_name}'（含 SUPERSEDED.md）— "
                    f"已 blocked，收敛后恢复（{convergence.get('superseded_path')}）",
                )
                return
            # add-fast-track-mode（task 3.1）：按 .spec.yaml mode 选择派发类型。
            # fast-track spec 派发 fast-track agent（单 run 全包），其余派 implementer。
            from core.spec_mode import read_spec_mode

            agent_type = (
                "fast-track"
                if read_spec_mode(self.project_root, spec_name) == "fast-track"
                else "implementer"
            )
            self._enqueue(spec_name, agent_type)
            # 冷却起点（双派发穿透原地修 2026-09-06）：以实际入队时刻计时
            now_ts = time.time()
            # 写入与淘汰一并纳入 _dispatch_guard_lock（code-review item
            # a5e5a15dcfa1）：不同 spec 的 _on_spec_ready 可由多线程并发进入
            # （单飞守卫只按 spec 去重），淘汰循环迭代键集合期间他线程写入会使
            # dict 尺寸变化抛 RuntimeError 并穿透本方法中断当轮事件处理；锁内
            # 仅做 dict 操作，与 _pending_dispatches/_handling_events 同款口径。
            with self._dispatch_guard_lock:
                self._last_dispatch_at[spec_name] = now_ts
                # 无界增长防护（code-review item 8c6c06bb595e）：写入口顺带淘汰——
                # 超 _LAST_DISPATCH_AT_MAX 时移除时间最旧条目（近似 LRU；被淘汰 spec
                # 的冷却判据必已远超窗口，无副作用）。
                if len(self._last_dispatch_at) > _LAST_DISPATCH_AT_MAX:
                    for _stale in sorted(
                        self._last_dispatch_at, key=self._last_dispatch_at.get
                    )[: len(self._last_dispatch_at) - _LAST_DISPATCH_AT_MAX]:
                        self._last_dispatch_at.pop(_stale, None)
            # 并行出题触发（add-verify-lane-throughput 1.1）：spec 进入 ready 且
            # 满足触发条件即注册 planner-plan 并行条目，出题与实现车道并行在飞；
            # 触发失败只 WARNING，不影响刚完成的实现派发。
            self._trigger_parallel_planning(spec_name)
            # 返回 True 表示成功入队（post-recovery-patrol D4：就地派发的
            # 「派发成立」判据）。既有调用方均忽略返回值，无兼容影响。
            return True
        finally:
            # 派发完成（成功或失败），从 pending 中移除，允许未来派发
            self._pending_dispatches.discard(spec_name)

    # ── 并行出题车道（add-verify-lane-throughput 1.1/1.2）──────────────────

    # 并行出题产物就绪状态标记（车道侧车道产物，随 verify-progress 拷回机制落
    # 主树）：.fenix/verify-progress/<spec>/parallel_plan.json。状态机：
    #   dispatched（run 已派发在飞）→ completed（run 成功收工，产物待消费校验）
    #   / failed / cancelled / frozen（run 失败/取消/冻结终止，产物已隔离）
    #   → consumed（验证管线首轮消费校验通过，后续按冻结复用既有语义）。
    PARALLEL_PLAN_MARKER_FILENAME = "parallel_plan.json"

    def _parallel_plan_marker_path(self, spec_name: str) -> Path:
        return (
            self.project_root / ".fenix" / "verify-progress" / spec_name
            / self.PARALLEL_PLAN_MARKER_FILENAME
        )

    def _read_parallel_plan_marker(self, spec_name: str) -> dict:
        """读并行出题状态标记；缺失/损坏返回 {}（fail-open，消费侧按无标记走）。"""
        p = self._parallel_plan_marker_path(spec_name)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_parallel_plan_marker(self, spec_name: str, payload: dict) -> None:
        """原子写并行出题状态标记；写失败仅 WARNING（观测增强，不阻断车道）。"""
        p = self._parallel_plan_marker_path(spec_name)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # mkstemp 唯一临时名（code-review item bd99064af8ee）：固定 .tmp 名下
            # 并行出题车道 worker 与验证管线 write_marker（verification/context）
            # 两写方交错 open+write 会互相截断/混写，原子 rename 落盘损坏 JSON
            # 且读侧 fail-open 丢标记——对齐 _write_impl_result_snapshot 同款
            # tempfile + fsync + os.replace 手法。
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent)
            )
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False, indent=1))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(str(tmp_path), str(p))
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        except (OSError, ValueError) as e:
            self.logger.warning(
                "pm_engine",
                f"并行出题状态标记写入失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _quarantine_parallel_product(self, spec_name: str, reason: str) -> None:
        """隔离并行出题半成品/失败产物（任务 1.2：不被后续验证轮直接采信）。

        重命名保留现场（test_scenarios.json → .parallel-discarded），重命名失败
        退 unlink；两皆失败仅 WARNING——消费侧（pipeline 冻结复用分支校验）对
        残留坏产物仍会按「并行产物损坏回落串行出题」兜底（任务 1.3）。
        """
        scenarios_path = (
            self.project_root / ".fenix" / "verify-progress" / spec_name
            / "test_scenarios.json"
        )
        if not scenarios_path.is_file():
            return
        try:
            scenarios_path.rename(scenarios_path.with_name("test_scenarios.json.parallel-discarded"))
        except OSError:
            try:
                scenarios_path.unlink()
            except OSError as e:
                self.logger.warning(
                    "pm_engine",
                    f"并行出题失败产物隔离失败 '{spec_name}'（消费侧校验兜底）: {e}",
                )
                return
        self.logger.warning(
            "pm_engine",
            f"并行出题产物已隔离（不被采信）'{spec_name}': {reason}",
        )

    def _trigger_parallel_planning(self, spec_name: str) -> None:
        """spec 进入 ready 态时注册并派发 planner-plan 并行出题（任务 1.1）。

        触发条件（全部满足才入队，缺一回退现状串行出题）：
        - 配置开关 ``verify.parallel_planning``（默认开启）；
        - full 模式 spec（fast-track 单 run 全包含场景设计步，并行出题与其
          内部设计会双写同一产物文件，不参与）；
        - 无既有可用场景集（``test_scenarios.json`` 不存在）；
        - 状态标记非 dispatched/completed/consumed（在飞/待消费/已消费不重派；
          failed/cancelled/frozen 允许 ready 重入时再试，与实现车道重派同语义）；
        - 同 spec 无在飞并行出题 run（``_active_parallel_plans`` 防重）。

        派发主体是派发队列的 ``planner-plan`` 条目（槽位豁免车道，2.1）：输入/
        prompt/产物路径与既有 testing 阶段串行出题完全一致；run 失败走既有
        planner 失败路径（本车道收尾隔离产物），MUST NOT 影响实现车道派发与
        状态机——本方法任何异常吞并 WARNING，不向调用方传播。
        """
        try:
            if not self._get_config("verify.parallel_planning", True):
                return
            from core.spec_mode import read_spec_mode

            if read_spec_mode(self.project_root, spec_name) == "fast-track":
                return
            scenarios_path = (
                self.project_root / ".fenix" / "verify-progress" / spec_name
                / "test_scenarios.json"
            )
            if scenarios_path.is_file():
                return
            marker = self._read_parallel_plan_marker(spec_name)
            if marker.get("status") in ("dispatched", "completed", "consumed"):
                return
            if spec_name in self._active_parallel_plans:
                return
            # 经门面单跳（code-review item 1fdb2783df6f）：_FORWARDER_REGISTRY 已
            # 登记 "_enqueue" → ("_dispatcher", "_enqueue")，直穿 _dispatcher 私有
            # 链会在 _enqueue 改名/搬迁时在此处单独断链（门面化目的即断链只发生
            # 在注册表一处）。
            self._enqueue(spec_name, "planner-plan")
            self.logger.info(
                "pm_engine",
                f"并行出题已注册（ready 触发，与实现并行）: {spec_name}",
            )
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"并行出题触发失败 '{spec_name}'（不影响实现车道）: {e}",
            )

    def _run_parallel_plan_lane(self, spec_name: str) -> None:
        """并行出题车道 worker 主体（由派发队列 planner-plan 条目唤起）。

        执行与既有串行出题完全一致的 ``run_planner(spec, "plan")``；产物
        （``test_scenarios.json``）由 planner run 自写，消费在 testing 进入
        （pipeline 并行产物校验，任务 1.3）。状态标记全程落盘，供消费侧判定
        「在飞等待 / 产物校验 / 失败回落串行」。
        """
        scenarios_path = (
            self.project_root / ".fenix" / "verify-progress" / spec_name
            / "test_scenarios.json"
        )
        marker = {
            "status": "dispatched",
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }
        # 派发前重查（与队列候选判定同口径；窗口内状态回退/产物已就绪即放弃）
        spec = self.state_machine.read_one(spec_name) or {}
        if spec.get("status") not in ("ready", "implementing", "implemented"):
            self.logger.info(
                "pm_engine",
                f"并行出题放弃（状态已回退 '{spec.get('status')}'，零写入）: {spec_name}",
            )
            return
        if not self._get_config("verify.parallel_planning", True):
            return
        if scenarios_path.is_file():
            return
        self._write_parallel_plan_marker(spec_name, marker)
        try:
            result = self.agent_runner.run_planner(spec_name, "plan")
        except Exception as e:
            self._write_parallel_plan_marker(
                spec_name, {"status": "failed", "error": str(e)[:300]}
            )
            self._quarantine_parallel_product(spec_name, f"并行出题异常: {e}")
            return
        # run 收尾后状态重查：spec 已删除/回退 → 产物按半成品隔离（任务 1.2）
        spec = self.state_machine.read_one(spec_name) or {}
        if not spec:
            self._write_parallel_plan_marker(
                spec_name, {"status": "discarded", "run_id": getattr(result, "run_id", "")}
            )
            self._quarantine_parallel_product(spec_name, "spec 已删除")
            return
        if spec.get("status") in ("drafted", "blocked"):
            # 回退收尾兜底（code-review item b4b98c69a4e1）：_stop_parallel_planning
            # 的 cancel_run 与 run 真正登记/收尾之间存在竞窗。evo-add-run-stop-loss
            # 1.1 后 not_running 分支也登记取消旗标（复活 attempt 被启动守卫拦截），
            # 但旗标系进程内存态——daemon 重启即丢，且旗标只拦本 run 的复活/重派
            # attempt，不拦车道收尾语义本身——此处仍不得写 completed：否则下次
            # ready 重入被 marker 挡住不重派，对旧版 spec 出的题被 testing 直接
            # 消费。按任务 1.2「回退即停」隔离半成品（discarded 标记同时是 runner
            # 侧 in-place retry 让位判据的输入，evo-add-run-stop-loss 1.2）。
            self._write_parallel_plan_marker(
                spec_name,
                {
                    "status": "discarded",
                    "run_id": getattr(result, "run_id", ""),
                    "reason": f"spec 状态已回退 '{spec.get('status')}'",
                },
            )
            self._quarantine_parallel_product(
                spec_name, f"spec 状态已回退 '{spec.get('status')}'，并行出题产物隔离"
            )
            return
        if (self._read_parallel_plan_marker(spec_name) or {}).get("status") == "discarded":
            # 消费侧已接管翻牌（code-review item b4b98c69a4e1）：testing 等待
            # 超时/收尾竞窗的 run-death 误判把 marker 翻成 discarded 并转串行
            # 重出。此时不得以 completed 覆写接管方标记（否则本次/下次 testing
            # 的消费判定错乱），也不得再隔离产物——串行重出即将覆写同路径，
            # 盲隔离可能误删串行产物。并行产物由串行路径覆写，无需额外处置。
            self.logger.info(
                "pm_engine",
                f"并行出题标记已被消费侧接管（discarded），放弃 completed 登记: "
                f"{spec_name} run={getattr(result, 'run_id', '')}",
            )
            return
        if getattr(result, "success", False):
            self._write_parallel_plan_marker(
                spec_name,
                {
                    "status": "completed",
                    "run_id": getattr(result, "run_id", ""),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.logger.info(
                "pm_engine",
                f"并行出题完成（产物待 testing 消费校验）: {spec_name} "
                f"run={getattr(result, 'run_id', '')}",
            )
            return
        if getattr(result, "frozen_terminated", False) is True:
            status = "frozen"
        elif getattr(result, "cancelled", False):
            status = "cancelled"
        else:
            status = "failed"
        self._write_parallel_plan_marker(
            spec_name,
            {
                "status": status,
                "run_id": getattr(result, "run_id", ""),
                "error": (getattr(result, "error", "") or "")[:300],
            },
        )
        self._quarantine_parallel_product(spec_name, f"并行出题 {status}")

    def _cancel_lane_runs(
        self, spec_name: str, agent_type: str, reason: str, by: str
    ) -> list[str]:
        """终止归属 ``spec_name`` 的活跃 ``agent_type`` 车道 run（两车道共享骨架）。

        收敛 ``_stop_parallel_planning`` 与 ``_reclaim_verify_lane`` 的机械重复
        （code-review item 79291d62b9e3）：list(...) 快照迭代 ``_running_agents``
        （对齐 cancel_run/轮询环的快照口径）；经 ``infer_run_agent_type`` 过滤
        本车道；归属复核以 ``run_spec_part`` 全等为准（防 startswith 裸前缀误中
        同根后代 spec 的 run）；取消键经 ``strip_run_id_suffixes`` 取完整 run 级
        id（含 epoch）——裸 spec 级键经 ``_normalize_run_id`` 归一后与消费点的
        带 epoch 键不收敛，取消静默失效（code-review item 794e218ce816）。
        仅取消本车道 ``agent_type`` 的 run，不波及其它车道。

        Returns:
            取消登记成功（``cancel_requested``）的完整 run 级 id 列表。
        """
        cancelled: list[str] = []
        runner = getattr(self, "agent_runner", None)
        if runner is None:
            return cancelled
        # list(...) 快照迭代（对齐 cancel_run/轮询环的快照口径）
        for aid in list(getattr(runner, "_running_agents", {}).keys()):
            lane_type, _ = infer_run_agent_type(aid)
            if lane_type != agent_type:
                continue
            # 归属复核以 run_spec_part 全等为准（防 startswith 裸前缀
            # 误中同根后代 spec 的 run）
            if run_spec_part(aid) != spec_name:
                continue
            # 完整 run 级 id：剥 attempt/瞬态重试后缀，保留 epoch
            run_level_id = strip_run_id_suffixes(aid)
            if run_level_id in cancelled:
                continue
            ret = runner.cancel_run(run_level_id, reason=reason, by=by)
            if ret.get("status") == "cancel_requested":
                cancelled.append(run_level_id)
        return cancelled

    def _stop_parallel_planning(self, spec_name: str, reason: str) -> None:
        """spec 状态回退（打回 drafted / 删除）时停止并行出题（任务 1.2）。

        两段：①摘除在队 planner-plan 条目（纯队列操作）；②终止在飞并行出题
        run——经既有取消原语 ``cancel_run``（旗标登记 + 属主线程 terminate），
        目标 run 由本车道派发、本车道属主停止（cancel_run 文档的调用方限制指
        transition/recovery/gate/freeze 等旁链不得越权终止他人 run；车道对自己
        派发的 run 做生命周期收尾正是该原语的本职用法，任务 1.2 明示「既有取消
        路径」）。取消键 MUST 为完整 run 级 id（含 epoch，形如
        ``planner-plan-<spec>-<epoch>``）：裸 ``planner-plan-<spec>`` 经
        ``_normalize_run_id`` 归一（不剥 epoch）后与消费点的带 epoch 键不收敛，
        取消静默失效（code-review item 794e218ce816，照 ``_reclaim_verify_lane``
        同款约束）。冻结回退不经此处：freeze 后 runner 轮询环按 spec frozen 态
        自动终止在飞 run（add-freeze-stop-inflight-agents 既有机制）。
        """
        try:
            removed = self._remove_queued_entry(spec_name, "planner-plan")
            cancelled = self._cancel_lane_runs(
                spec_name, "planner-plan", reason=reason, by="parallel-plan-lane"
            )
            if removed or cancelled:
                self.logger.info(
                    "pm_engine",
                    f"并行出题已停止（{reason}）: {spec_name} "
                    f"(queued_removed={removed}, cancelled={cancelled})",
                )
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"并行出题停止失败 '{spec_name}'（消费侧校验兜底）: {e}",
            )

    def _reclaim_verify_lane(self, spec_name: str) -> None:
        """verified 终态收敛点回收在飞 verify 车道（fix-verify-late-result-terminal-clobber D2）。

        两段（照搬 ``_stop_parallel_planning`` 范式）：①摘除在队 verifier 条目；
        ②对归属本 spec 的活跃 verify run 逐个 ``cancel_run`` 终止（车道对自己
        派发的 run 做生命周期收尾属该原语的本职用法）。

        取消键 MUST 为**完整 run 级 id（含 epoch，如 ``verify-<spec>-<epoch>``）**，
        MUST NOT 传裸 ``verify-<spec>``：cancel_run 的旗标登记键经
        ``_normalize_run_id`` 归一（只剥 ``-a<n>``/``-r<n>`` 后缀，不剥 epoch），
        消费点（attempt 循环/轮询环）以带 epoch 的 run 级 id 归一后做精确集合
        判定——裸键登记后与消费键不收敛，取消**静默失效**且返回值仍显
        ``cancel_requested``（``_stop_parallel_planning`` 的裸键先例即此，本车道
        MUST NOT 照搬）。归属复核以 ``run_spec_part(aid) == spec_name`` 为准
        （登记侧 startswith 裸前缀匹配会误中同根后代 spec 的 run，如
        ``verify-fix-a-b-<epoch>`` 命中 ``verify-fix-a`` 前缀；family.py 同款
        「精确前缀归属守卫」教训），且仅取消 verifier 车道 run，不波及其它
        agent_type。旗标按含 epoch 的完整键登记，天然不波及门禁回退后重派的
        新 epoch verify run 与人工重验 run。

        调用方（_on_spec_verified）整体 try/except 兜底：取消失败由结果应用侧
        D6 复核兜底丢弃迟到结果（防御纵深），不影响 done → push 主链。
        """
        removed = self._remove_queued_entry(spec_name, "verifier")
        cancelled = self._cancel_lane_runs(
            spec_name,
            "verifier",
            reason="spec verified — reclaim in-flight verify lane",
            by="verify-lane",
        )
        if removed or cancelled:
            self.logger.info(
                "pm_engine",
                f"verify 车道已回收（verified 终态收敛）: {spec_name} "
                f"(queued_removed={removed}, cancelled={cancelled})",
            )

    def _merge_ready_fallback(
        self, spec_name: str, run_id: str | None, agent_type: str, branch: str | None
    ) -> bool:
        """合并收尾 ready 态兜底（evo-spec-concurrency-flight-guard D3）。

        实现 run 合并完成后推进 ``implemented`` 前调用：若 spec 当前 status=ready
        （评审收尾竞态把已接管的 spec 回退过），先补记合法转移 ``ready→implementing``
        ，再由调用方推进 ``implementing→implemented``——消除 ``ready→implemented``
        非法转移 ERROR（16:29:24Z 事故实证，83 分钟状态矛盾）。

        判据以**调用点即证据**（本方法仅由三条实现合并收尾路径调用：queue.py
        implementer 主路径 / repair_lane.py re-merge / fast_track.py 单 run），
        MUST NOT 以分支名字面匹配单独充当判据——分支仅作防御性次级校验。

        Returns: True 表示已补记 implementing（status 曾是 ready 且次级校验通过）；
        False 表示未触发（status 非 ready，branch 不满足 fenix/ 次级校验，或
        ready→implementing 转移被拒——此时 ready→implemented 依然被拒 = 真实异常
        暴露，不静默放行）。
        """
        spec = self.state_machine.read_one(spec_name)
        if not spec or spec.get("status") != "ready":
            return False
        # 次级校验（防御性，不是唯一判据）：实现分支属本 spec 的 `fenix/` 前缀
        # 且非 verifier 族形状（shape.py 结构消歧单源，worktree_manager/lifecycle
        # cleanup 同款判定）。裸前缀 startswith("fenix/verify-") 会把 verify-
        # 开头 spec 名的实现分支（fenix/verify-dsh-plugins-live-<ts>）误判为
        # 验证分支、合并兜底被拒（admin-global-1791999865 同型）。
        # 不满足 → 不兜底，维持既有转移（ready→implemented 仍被拒 = 暴露真实异常）。
        if (
            not branch
            or not branch.startswith("fenix/")
            or branch_shape_is_verifier(branch, spec_hint=spec_name)
        ):
            self.logger.warning(
                "pm_engine",
                f"ready 态合并兜底次级校验未通过，不补记 implementing"
                f"（status=ready 但 branch={branch} 非实现分支）: {spec_name} run={run_id}",
            )
            return False
        # transition 返回值必须接收（code-review item 024acdd0437a，对齐
        # _on_spec_done 0b464aaa47b8 / approve_push f3173b3164ee 口径）：上方
        # read_one 快照到转移之间隔着竞窗，转移被拒时不得照记成功——否则落
        # 「ready 态合并兜底：补记 implementing」假成功 WARNING 与项目日志，
        # 调用方据 True 继续 implementing→implemented 也会被拒，事后对账被
        # 误导。被拒记 WARNING、返回 False 暴露真实异常，不静默放行。
        moved = self.state_machine.transition(
            spec_name, "implementing",
            trigger_run_id=run_id, agent_type=agent_type, channel="auto",
        )
        if not moved:
            self.logger.warning(
                "pm_engine",
                f"ready 态合并兜底 — transition '{spec_name}' "
                f"ready→implementing rejected (state changed externally) — "
                f"不落兜底日志、返回 False",
            )
            return False
        self.logger.warning(
            "pm_engine",
            f"ready 态合并兜底：补记 implementing（评审收尾竞态回退残留）"
            f"'{spec_name}' run={run_id} branch={branch}",
        )
        try:
            self._append_project_log(
                f"⚠️ ready 态合并兜底：'{spec_name}' 补记 implementing"
                f"（run={run_id}，评审收尾竞态回退残留）"
            )
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"合并兜底项目日志失败 '{spec_name}'（非阻断，兜底本身已生效）: {e}",
            )
        return True

    def _check_superseded_convergence(self, spec_name: str) -> dict:
        """派发前同源草案收敛检查（evo-deliverable-declaration-drift-align D3）。

        implementer/fast-track 派发前 MUST 检查本 spec 目录自身是否含
        SUPERSEDED.md（已被取代，不再作为独立实现入口）：命中 → 禁止派发、
        spec 置 blocked（error=同源草案收敛义务未满足，附 SUPERSEDED.md 路径），
        待收敛（该 SUPERSEDED.md 移除或目录删除）后恢复派发（D3 第 5 条）。

        拦截面只限「本 spec 目录自身含 SUPERSEDED.md」——该标记由收敛动作主动
        写入（先例：commit 023346ff / 42af955e），语义明确「本目录不再作为独立
        实现入口」。名字归一（去 ``-\d+$`` 后缀，同源 ``_NUM_SUFFIX_RE``，
        core/evolution.py:1498）仅用于识别平级同名草案；MUST NOT 单凭归一命中
        拦截生效落点（被 SUPERSEDED.md 显式点名为生效落点的一侧自始不受拦截——
        被点名的生效落点与收敛源按名字归一会互为命中，误拦会把生效草案永久
        冻住）。

        Args:
            spec_name: spec 目录名（spec/changes/<spec_name>/）。

        Returns:
            {"blocked": bool, "error": str|None, "superseded_path": str|None,
             "peers": [平级同名草案目录名], "named_by": [点名本 spec 的收敛源]}。
            blocked=True 时调用方 MUST 置 blocked 并跳过派发。
        """
        project_root = self.project_root
        spec_dir = Path(project_root) / "spec" / "changes" / spec_name
        sup_path = spec_dir / "SUPERSEDED.md"
        scan = _scan_superseded_docs(project_root)
        peers = _superseded_name_peers(spec_name, scan)
        named_by = [
            name
            for name, info in scan.items()
            if spec_name in (info.get("named_targets") or [])
        ]
        if sup_path.is_file():
            try:
                rel = sup_path.relative_to(project_root).as_posix()
            except ValueError:
                rel = str(sup_path)
            return {
                "blocked": True,
                "error": f"同源草案收敛义务未满足: {rel}",
                "superseded_path": rel,
                "peers": peers,
                "named_by": named_by,
            }
        return {
            "blocked": False,
            "error": None,
            "superseded_path": None,
            "peers": peers,
            "named_by": named_by,
        }

    # ── 定时调度到期检测（add-spec-scheduling-controls D3）────────────────────

    @staticmethod
    def _frozen_state(entry: dict) -> bool:
        """冻结态判定（state_machine 侧）：frozen 结构化标记或 legacy 文本契约。"""
        if not isinstance(entry, dict):
            return False
        if entry.get(FROZEN_FIELD) is True:
            return True
        return entry.get("status") == SpecStatus.BLOCKED and (entry.get("error") or "").startswith(
            FREEZE_ERROR_PREFIX
        )

    def check_scheduling_deadlines(self) -> dict:
        """定时调度到期检测（add-spec-scheduling-controls D3）。

        daemon 主循环每 60s 独立计时段调用（对齐 recovery watch 模式；
        不做进程内一次性 Timer——周期即兜底，daemon 重启天然恢复检测）：

        1. 冻结 spec 的 ``frozen_until`` ≤ now → 自动解冻：恢复冻结前状态
           （``parse_orig_status`` 从冻结 error 解析「原状态 X」，缺失回退
           ready）、清空 error 与 ``frozen_until``，全部经
           ``StateMachine.unfreeze_spec`` 官方通道。**写前重读 STATE 确认仍
           处于冻结态**——定时器与周期扫描竞争时后到者视为无需操作，解冻幂等
           （spec scheduled-spec-unfreeze「幂等竞争」）。自动解冻落项目日志 +
           事件流，携带「定时解冻」来源标记（与人工解冻可区分）。
        2. 非终态 spec 的 ``start_after`` 已到期且状态可派发（ready → 唤起
           ``_on_spec_ready`` 精触发；drafted → ``_on_spec_drafted`` 晋升链
           同步唤起）——补齐 full_scan 间隔（缺省 30 分钟）内的时间窗；周期
           扫描仍为兜底，二者先后到达均只触发一次正常派发。

        逐条异常捕获记日志不中断整轮。Returns: {"unfrozen": [...], "signaled": [...]}
        """
        unfrozen: list = []
        signaled: list = []
        now = datetime.now(timezone.utc)
        for name, entry in self.state_machine.read_all().items():
            if not isinstance(entry, dict):
                continue
            # ── 1) frozen_until 到期自动解冻（幂等：写前重读确认仍冻结）──
            until_raw = entry.get(FROZEN_UNTIL_FIELD)
            if until_raw:
                until = parse_utc(until_raw)
                if until is not None and until <= now:
                    fresh = self.state_machine.read_one(name) or {}
                    if not self._frozen_state(fresh):
                        continue  # 竞争后到者：已解冻/非冻结，跳过
                    orig = parse_orig_status(fresh.get("error"))
                    before = fresh.get(FROZEN_UNTIL_FIELD)
                    try:
                        self.state_machine.unfreeze_spec(name, status=orig)
                    except Exception as e:
                        self.logger.error(
                            "pm_engine",
                            f"定时解冻写回失败 '{name}'（留待下轮重试）: {e}",
                        )
                        continue
                    unfrozen.append(name)
                    try:
                        self._append_project_log(
                            f"⏰ 定时解冻 SPEC: **{name}**"
                            f"（原状态 {orig}，frozen_until {before} 到期自动恢复）"
                        )
                        record_project_event(
                            self.project_root,
                            "pm_engine",
                            f"定时解冻 SPEC '{name}'（原状态 {orig}）",
                            context={"source": "scheduled-unfreeze", "frozen_until": before},
                        )
                    except Exception as e:
                        self.logger.warning(
                            "pm_engine",
                            f"定时解冻事件记录失败 '{name}'（非阻塞）: {e}",
                        )
                    self.logger.info(
                        "pm_engine",
                        f"Scheduled unfreeze '{name}': frozen_until {before} "
                        f"expired → restored to {orig}",
                    )
            # ── 2) start_after 到期唤起派发（仅登记过定时字段的 spec）──
            sa = entry.get(START_AFTER_FIELD)
            # 哨兵 `manual` 经 parse_utc 判 None 天然跳过到期检测，MUST NOT 改为
            # `sa != None` 之类判据——否则哨兵被判到期误唤起（D3 要求保留该行为，
            # 勿改此分支）。见 core/state_machine.py START_AFTER_MANUAL 常量注释。
            if sa is None or parse_utc(sa) is None:
                continue  # 无定时字段（或非法/哨兵）→ 无到期检测需求
            if start_after_pending(entry, now):
                continue  # 尚未到期
            status = entry.get("status")
            if status not in (SpecStatus.DRAFTED, SpecStatus.READY):
                continue
            try:
                if status == SpecStatus.DRAFTED:
                    # drafted 走晋升链（lint 拦截/error 写回由 _on_spec_drafted 自理）
                    self._on_spec_drafted(name)
                else:
                    self._on_spec_ready(name)
                signaled.append(name)
            except Exception as e:
                self.logger.warning(
                    "pm_engine",
                    f"start_after 到期唤起 '{name}' 失败（非阻塞）: {e}",
                )
        # 唤起后立即处理派发队列，使「到期精确触发」不依赖后续其它事件驱动
        # （periodic full_scan 仍为兜底；_process_queue 幂等，空队列直接返回）。
        if signaled:
            try:
                self._process_queue()
            except Exception as e:
                self.logger.warning(
                    "pm_engine",
                    f"start_after 唤起后派发队列处理失败（非阻塞，full_scan 兜底）: {e}",
                )
        return {"unfrozen": unfrozen, "signaled": signaled}

    # ── 派发锁冲突退避（improve-run-lifecycle-governance D5）──────────────────

    # ── 恢复闭环复查 / 假就绪巡检（improve-run-lifecycle-governance D6）───────

    def _on_spec_implemented(self, spec_name: str):
        """Schedule verifier for implemented SPEC."""
        # fast-track 单 run 全包（实现→场景设计→验证→判定），不设 verifier 车道
        # （fasttrack-orphan-planner-race）：fast-track 收尾仍会触发本事件，若照常
        # 入队 verifier，与 _fast_track_advance_to_verified 竞态会派出孤儿 planner
        # run 对已终态 spec 白跑（2026-09-08 fix-verify-cli-cwd-isolation：已 pushed
        # 后场景生成 run 白跑 14min）。读侧容错缺省 full，存量 spec 零影响。
        from core.spec_mode import is_fast_track

        if is_fast_track(self.project_root, spec_name):
            # fix-fasttrack-implemented-deadstate Cap 1：短路之前先判恢复形态
            # ——implemented 死态（重启恢复）三条件全成立时重入收尾推进，
            # 否则维持既有短路（孤儿 planner 防线不变）。
            if self._fasttrack_recovery_reentry(spec_name):
                return
            self.logger.debug(
                "pm_engine",
                f"Skipping verifier enqueue for fast-track '{spec_name}' "
                "(单 run 全包，验证在 fast-track run 内完成)",
            )
            return
        self._enqueue(spec_name, "verifier")

    def _implementer_run_transcript_expired(self, implementer_run) -> bool:
        """实现者 run 流转录新鲜度判定（恢复三条件②，fix-fasttrack-implemented-deadstate D1）。

        转录文件（``.fenix/runs/<implementer_run>.jsonl``）mtime 超过
        ``ORPHANED_RUN_GRACE_SECONDS``（admin_monitor 孤儿探针同源宽限语义：
        活 run 心跳持续刷新转录 mtime，超窗即 run 已死）或文件不存在
        （run 未在写）→ True（run 已死）。``implementer_run`` 为空保守返回
        False（条件①已挡，不在此误判）。
        """
        if not implementer_run:
            return False
        run_file = self.project_root / ".fenix" / "runs" / f"{implementer_run}.jsonl"
        try:
            mtime = run_file.stat().st_mtime
        except OSError:
            return True  # 转录不存在 = run 未在写 → 已死
        from core.admin_monitor import ORPHANED_RUN_GRACE_SECONDS

        return (time.time() - mtime) > ORPHANED_RUN_GRACE_SECONDS

    def _fasttrack_recovery_reentry(self, spec_name: str) -> bool:
        """fast-track implemented 死态恢复形态判定与重入（Cap 1 / D1）。

        恢复三条件同时成立才放行恢复重入，任一不成立维持既有短路（孤儿
        planner 防线不变，debug 留痕）：

        ① 双形态（code-review item 3766612aca27 扩展）：
           - implemented 死态（原形态）：``status == "implemented"`` 且
             ``implementer_run`` 非空（收尾流已过 merge 点）；
           - testing 搁浅态：``status == "testing"`` 且 ``implementer_run``
             非空且无 pending 停等标记（``_ocr_join_wait``）——首次收尾段在
             testing 转移之后抛异常（如 ``_ocr_current_fingerprint``）搁浅，
             无车道无标记无唤醒者，且 VALID_TRANSITIONS 不允许
             testing→implemented 回滚重走，只能直接重跑收尾段。
        ② 实现者 run 转录 mtime 超 ``ORPHANED_RUN_GRACE_SECONDS`` 宽限窗
           （``_implementer_run_transcript_expired``）→ run 已死；
        ③ ``ocr_lane_busy(spec_name)`` 为假（公开方法带参判定，不直读
           ``_ocr_lane_inflight``）→ 收尾重入不与在飞车道竞态；判定异常按
           在飞处理（不重入，宁紧勿松）。

        Returns:
            True = 恢复形态成立且已触发重入（``_resume_fast_track_after_restart``）；
            False = 维持既有短路。
        """
        entry = self.state_machine.read_one(spec_name) or {}
        implementer_run = entry.get("implementer_run")
        status = entry.get("status")
        # testing 搁浅态：无 pending 停等标记是必要条件——有标记说明车道完成
        # 回调（_on_impl_ocr_lane_finished）唤醒路径在场，不经本恢复入口。
        form_stranded_testing = (
            status == "testing"
            and bool(implementer_run)
            and not entry.get("_ocr_join_wait")
        )
        cond_status = (
            (status == "implemented" and bool(implementer_run))
            or form_stranded_testing
        )
        cond_dead = self._implementer_run_transcript_expired(implementer_run)
        try:
            cond_no_lane = not self.ocr_lane_busy(spec_name)
        except Exception:  # noqa: BLE001 — 车道判定不可得按在飞处理，不重入
            cond_no_lane = False
        if not (cond_status and cond_dead and cond_no_lane):
            self.logger.debug(
                "pm_engine",
                f"fast-track 短路维持 '{spec_name}'（恢复判据 "
                f"status_ok={cond_status}/run_dead={cond_dead}/no_lane={cond_no_lane} "
                "不全成立，非恢复形态）",
            )
            return False
        self.logger.info(
            "pm_engine",
            f"fast-track 恢复重入 '{spec_name}'："
            + (
                "testing 搁浅态（无车道无停等标记，"
                if form_stranded_testing
                else "implemented 死态（"
            )
            + f"run 转录超宽限={cond_dead}，无在飞车道={cond_no_lane}）→ 重入"
            "收尾推进 (testing → ocr join 门禁 → verified)",
        )
        try:
            if form_stranded_testing:
                # testing 搁浅态：已过 implemented→testing 转移点（VALID_TRANSITIONS
                # 不允许回滚重走），跳过转移、仅重跑收尾段。
                self._resume_fast_track_after_restart(
                    spec_name, already_testing=True
                )
            else:
                self._resume_fast_track_after_restart(spec_name)
        except Exception as e:  # noqa: BLE001 — 重入失败不崩溃，事件周期重发兜底
            self.logger.warning(
                "pm_engine",
                f"fast-track 恢复重入失败 '{spec_name}'（非阻塞，等下次事件重发）: "
                f"{type(e).__name__}: {e}",
            )
        return True

    def _on_spec_verified(self, spec_name: str):
        """Mark verified SPEC as done."""
        # 防重入：使用独立 key，避免与 handle_event 的 ("spec_verified", spec_name)
        # 冲突（handle_event 在调用 handler 前已 add 该 key，若共用会导致本方法被跳过）
        event_key = ("_guard:verified", spec_name)
        # 检查 + 登记在实例锁内原子完成（同 handle_event，code-review item
        # e92ccf866b55），消除并发 check-then-act 竞态
        with self._dispatch_guard_lock:
            already_handling = event_key in self._handling_events
            if not already_handling:
                self._handling_events.add(event_key)
        if already_handling:
            self.logger.debug("pm_engine", f"Skipping duplicate verified for '{spec_name}'")
            return
        try:
            # verified→done 一致性门禁（add-task-progress-sync）：
            # run 声明 success 但存在「未勾选且不在 done_ids」的任务时，阻断自动推送，
            # 把缺口写入 error 字段供人工裁决；全部可确认完成时放行；无 run 记录放行。
            blocker = self._task_completion_blocker(spec_name)
            # 验证完成度闸门（verification-completion-gate）：
            # 验证流程已启动但 done < total → 阻断放行，保留 verified 状态。
            # 与任务完成门禁结论一致时合并为单个拦截原因，不出现双 error 覆盖。
            vblocker = self._check_verification_gate(spec_name)
            if vblocker:
                blocker = (blocker + "; " if blocker else "") + vblocker
            if blocker:
                # 验证完成度闸门（vblocker）触发时走 D7 逃生门：VERIFIED→TESTING
                # 自动回退重新派发验证器，断点续跑（保留 implementer_run 与 progress），
                # 消除「verified 无出口」死锁。仅进度不完整走此路径；任务缺口
                # （blocker 但非 vblocker）保持 verified 供人工裁决，不自动回退。
                # blocker == vblocker（同串）即任务缺口闸门已放行、仅剩进度不完整；
                # 两闸门同中时 blocker 为 "task-gap:…; " + vblocker 合并文案，走下方
                # 保持 verified 分支携带完整合并结论供人工裁决。
                if vblocker and blocker == vblocker:
                    self.logger.warning(
                        "pm_engine",
                        f"验证进度不完整 '{spec_name}'，门禁逃生门回退 testing 重新验证: {vblocker}",
                    )
                    # transition_gate 返回值必须接收（code-review item dc13e7dc5cb3，
                    # 对齐 _on_spec_done 的 0b464aaa47b8 口径）：自 blocker 计算
                    # 到转移之间存在竞窗（外部冻结/清除错误/状态被改），转移被拒
                    # 时不得写 error——先转移、成功后再写，否则 error 落在非
                    # testing 状态的 spec 上且不回退，误导事后对账。
                    # fix-observability-gaps 2.1：门禁逃生门 transition_gate 也必须带 context
                    moved = self.state_machine.transition_gate(
                        spec_name, "testing",
                        trigger_run_id=None, agent_type=None, channel="auto",
                    )
                    if not moved:
                        self.logger.warning(
                            "pm_engine",
                            f"门禁逃生门 — gate transition '{spec_name}' "
                            f"→testing rejected (state changed externally) — "
                            f"skip error write",
                        )
                        return
                    # 保留 implementer_run 与既有 progress 断点（D7），仅置 error 摘要
                    self.state_machine.update_spec(
                        spec_name,
                        {
                            "error": f"验证进度不完整，回退重新验证: {vblocker}",
                        },
                    )
                    return
                self.logger.warning(
                    "pm_engine",
                    f"验证放行门禁拦截 '{spec_name}'（保持 verified）: {blocker}",
                )
                # 写前重读复核（code-review item 49044ee6e490，对齐同方法逃生门
                # dc13e7dc5cb3 与 check_blockers 313f93a4c7c1「竞争后到者视为
                # 无需操作」先例）：自 blocker 计算到写 error 之间存在竞窗（人工
                # CLI/Dashboard 已把 verified 推进 done 等），状态非 verified 时
                # 不得写——否则 task-gap 拦截文案落在 done spec 的 error 字段上，
                # 误导事后对账与看板展示。
                fresh = self.state_machine.read_one(spec_name) or {}
                if fresh.get("status") != "verified":
                    self.logger.info(
                        "pm_engine",
                        f"门禁拦截竞争后到者：'{spec_name}' 状态已为 "
                        f"'{fresh.get('status')}'，让位于外部进度，"
                        f"跳过本次 error 写入（缺口留待后续周期重评）",
                    )
                    return
                self.state_machine.update_spec(
                    spec_name,
                    {
                        "error": blocker,
                    },
                )
                return

            self.logger.info("pm_engine", f"Verification passed: '{spec_name}' → done")
            # fix-daemon-lifecycle-races D4：transition() 对 old==new 幂等返回 True，
            # 事件回放（done→done）时此处仍会进入——total_duration 重算为同值覆盖无害，
            # _evict_spec_serving 幂等，project log 由 _on_spec_done 防重入（_guard:done）
            # 去重。无需额外前置判断。
            # fix-observability-gaps 2.2：验证通过→done，自动来源（验证引擎非 agent run）
            if self.state_machine.transition(
                    spec_name, "done",
                    trigger_run_id=None, agent_type=None, channel="auto"):
                # verify-process-lifecycle D6（spec 终局驱逐）：done 落定后同步
                # 回收该 spec 的被测实例——stop 登记服务 + 驱逐缓存 + 移除 serving
                # worktree（幂等；主树 static 共享实例保留）。
                try:
                    self._evict_spec_serving(spec_name)
                except Exception as e:
                    self.logger.warning(
                        "pm_engine",
                        f"spec 终局 serving 驱逐失败 '{spec_name}'（非阻塞）: {e}",
                    )
                # fix-verify-late-result-terminal-clobber D2：verify 车道终局
                # 回收（摘在队 verifier 条目 + 按完整 run 级 id 取消在飞 run）。
                # 仅 done 落定后执行——D7 逃生门（回退 testing 断点续跑）与
                # 「blocker 保持 verified」路径在本方法前段提前 return，不会
                # 拆掉门禁要求续跑的在飞车道。整体 try/except 兜底：取消失败
                # 由结果应用侧 D6 复核兜底丢弃迟到结果（防御纵深），不影响
                # done → push 主链。
                try:
                    self._reclaim_verify_lane(spec_name)
                except Exception as e:
                    self.logger.warning(
                        "pm_engine",
                        f"verify 车道终局回收失败 '{spec_name}'（非阻塞）: {e}",
                    )
                # add-done-duration-persist（D1/D2）：done 落定时刻把总耗时快照进
                # STATE.md，使耗时不再依赖易失的 run 产物（run 产物只增不减，
                # 但快照保证耗时独立于产物回读路径）。
                # 求和口径与 spec_summary 一致（duration_seconds 求和、含归档），
                # 保证写入值 = 当时列表页显示值。done→done 幂等返回 True，重复事件
                # 回放会重复求和覆盖，但求和口径不变结果相同（见上方 D4 注释）。
                total_duration = sum(
                    int(r.get("duration_seconds") or 0)
                    for r in get_runs(self.project_root, spec_name, include_archive=True)
                )
                self.state_machine.update_spec(spec_name, {"total_duration": total_duration})
                # 同步触发 spec_done 处理（fix done → 自动重新验证父 SPEC）。
                # 背景：daemon 启动时 full_scan 在 EventBus watcher 启动前同步调度，
                # 阻塞完成整个 fix 生命周期，使 verified→done 变化在快照初始化前发生，
                # spec_done 事件被吞掉，父 SPEC 永远不被重新验证。这里提供同步直接
                # 调用路径（框架原则：状态转换不能只依赖异步事件轮询）。
                # 幂等：父 SPEC 若已非 implementing，transition 校验失败自动跳过；
                # _enqueue 亦有去重。事件总线后续若重复发出 spec_done 亦无害。
                # 置于 transition 成功分支内：转移被拒（如外部冻结/改判 blocked）
                # 时 spec 并非 done，不得落完成日志或提前触发父 SPEC 重验。
                self._on_spec_done(spec_name)
        finally:
            self._handling_events.discard(event_key)

    def _on_spec_bug_found(self, spec_name: str, failure_class: str = "product", run_id: str = ""):
        """Create or reset a fix SPEC for the bug and immediately schedule it."""
        # 防重入：使用独立 key，避免与 handle_event 的 ("spec_bug_found", spec_name)
        # 冲突（handle_event 在调用 handler 前已 add 该 key，若共用会导致本方法被跳过）
        event_key = ("_guard:bug_found", spec_name)
        # 检查 + 登记在实例锁内原子完成（同 handle_event，code-review item
        # e92ccf866b55），消除并发 check-then-act 竞态
        with self._dispatch_guard_lock:
            already_handling = event_key in self._handling_events
            if not already_handling:
                self._handling_events.add(event_key)
        if already_handling:
            self.logger.debug("pm_engine", f"Skipping duplicate bug_found for '{spec_name}'")
            return
        try:
            self._do_spec_bug_found(spec_name, failure_class=failure_class, run_id=run_id)
        finally:
            self._handling_events.discard(event_key)

    # ── fix 族谱收敛治理（fix-family-convergence-governor / design D4）──

    # ── 原地打回辅助：任务注入与升级告警 ──────────────────────────────

    # 单一来源见 core.verify_scenarios.VERIFY_FIX_SECTION_RE（code-review
    # 18825900bb22：原此处各持一份同源拷贝，标题文案调整漏改一侧会与
    # is_repair_round 判定分叉）。属性名保留：family.py 经
    # ``self._pm._VERIFY_FIX_SECTION_RE`` 引用。
    _VERIFY_FIX_SECTION_RE = VERIFY_FIX_SECTION_RE

    # ── 预算计数对账（fix-budget-counting-semantics D3，日志级）──────

    def _on_spec_done(self, spec_name: str):
        """SPEC is done — log, re-verify parent if this was a fix SPEC.

        若 gates.approve_mode == "auto"，自动执行 git push 并推进到 pushed。
        防重入（fix-daemon-lifecycle-races D5）：verify 成功后的同步直调
        （_on_spec_verified → 本方法）与 event_bus spec_done 事件双路径并发进入，
        用 _guard:done 键去重——同一 spec 的 done 处理只执行一次，重复 project
        log（✅ SPEC completed）不再产生；push 幂等由 approve_push 实例锁兜底。
        """
        event_key = ("_guard:done", spec_name)
        # 检查 + 登记在实例锁内原子完成（同 handle_event，code-review item
        # e92ccf866b55），消除并发 check-then-act 竞态
        with self._dispatch_guard_lock:
            already_handling = event_key in self._handling_events
            if not already_handling:
                self._handling_events.add(event_key)
        if already_handling:
            self.logger.debug(
                "pm_engine",
                f"Skipping duplicate spec_done for '{spec_name}'",
            )
            return
        try:
            spec = self.state_machine.read_one(spec_name) or {}
            status = spec.get("status", "")

            self.logger.info(
                "pm_engine",
                f"SPEC '{spec_name}' is done — awaiting push approval",
            )

            # （b21d8f2d8247 同口径）报告可丢，主链不可断：PROJECT_LOG 不可写
            # 不得中断 done 处理（含下方 _auto_approve 收口）
            try:
                self._append_project_log(
                    f"✅ SPEC completed: **{spec_name}** — awaiting push approval"
                )
            except Exception as e:
                self.logger.warning(
                    "pm_engine",
                    f"done 收口项目日志失败 '{spec_name}'（非阻断，done 处理继续）: {e}",
                )

            # 自动审批：approve_mode=auto 且状态为 done 时触发
            # （若已 pushed 则 _auto_approve 内部幂等跳过，不重复推送）
            approve_mode = self._get_approve_mode()
            if approve_mode == "auto" and status == "done":
                self._auto_approve(spec_name)

            # ── legacy：存量 fix-* SPEC 完成 → 父 SPEC 自动重验（D4 过渡期兼容）──
            # 仅对 fix-* 链条生效；新裁决不再产生 fix-* 派生，待存量链收敛后自然耗尽。
            # If this is a fix SPEC, re-trigger verification of the original SPEC
            # （置于 try 块内：_guard:done 去重窗口须覆盖方法全部副作用，含本段
            # transition/update_spec/_enqueue，见 fix-daemon-lifecycle-races D5）
            if spec_name.startswith("fix-"):
                # 剥离 fix- 前缀逐级生成的候选根名；取「最深且存在」的候选，避免
                # 全剥光后根名本身也带 fix- 前缀（如 fix-dashboard-...）时定位失败，
                # 导致父 SPEC 的 bug-found 永不闭环、full_scan 反复派生新 fix。
                original = None
                name = spec_name
                candidates = []
                while name.startswith("fix-"):
                    name = name[4:]
                    candidates.append(name)
                for cand in reversed(candidates):
                    if self.state_machine.read_one(cand):
                        original = cand
                        break
                if original is None:
                    self.logger.warning(
                        "pm_engine",
                        f"Fix done — no original SPEC found for '{spec_name}', skipping re-verify",
                    )
                    return
                original_spec = self.state_machine.read_one(original)
                if original_spec:
                    current_status = original_spec.get("status", "")
                    # 幂等保护：若父SPEC已在 testing（验证中），说明已有verifier在处理，跳过
                    # 注：父 spec 现在保持在 bug-found 等 fix（不再放置为 implementing）
                    if current_status == "testing":
                        self.logger.info(
                            "pm_engine",
                            f"Fix done — original '{original}' already in 'testing', "
                            f"skipping duplicate re-verify",
                        )
                        return
                    self.logger.info("pm_engine", f"Fix done — re-verifying original: {original}")
                    # 使用 transition 做状态转换；若当前状态无法直接转到 implemented，跳过
                    # （不再用 update_spec 兜底，那正是竞态覆写的根因）
                    if not self.state_machine.is_valid_transition(current_status, "implemented"):
                        self.logger.info(
                            "pm_engine",
                            f"Fix done — cannot transition '{original}' from '{current_status}' "
                            f"to implemented, skipping",
                        )
                        return
                    # transition 返回值必须接收（code-review item 0b464aaa47b8，
                    # 对齐 approve_push 的 f3173b3164ee 口径）：上方
                    # is_valid_transition 预检与真实转移之间存在竞窗，状态被
                    # 外部改动（人工冻结剥离/改判 blocked 等）致转移被拒时，
                    # 不得写 "Re-verifying after fix" error、不得入队
                    # verifier——否则 error 落在非 implemented 状态的 spec 上，
                    # 且为不可派发状态的 spec 留下每轮扫描被跳过却不淘汰的
                    # 滞留条目（同 family.py 收敛入队注释所述形态）。
                    moved = self.state_machine.transition(
                        original, "implemented",
                        trigger_run_id=None, agent_type=None, channel="auto",
                    )
                    if not moved:
                        self.logger.warning(
                            "pm_engine",
                            f"Fix done — transition '{original}' "
                            f"{current_status}→implemented rejected "
                            f"(state changed externally) — skip error write "
                            f"and verifier enqueue",
                        )
                        return
                    self.state_machine.update_spec(
                        original,
                        {
                            "error": f"Re-verifying after fix: {spec_name}",
                        },
                    )
                    # fast-track 父 SPEC 分流（code-review item 1d98994a6cdd，
                    # _on_spec_implemented 同款守卫）：fast-track 单 run 全包不设
                    # verifier 车道（fasttrack-orphan-planner-race）——queue.
                    # _entry_ready 的 verifier 候选口径接受 implemented/testing，
                    # 直接入队会真实派出 verifier 车道 run 与 fast-track 收尾推进
                    # 竞态。先试恢复重入（implemented 死态恢复三条件），否则维持
                    # 短路不落 verifier 条目。
                    from core.spec_mode import is_fast_track

                    if is_fast_track(self.project_root, original):
                        if self._fasttrack_recovery_reentry(original):
                            return
                        self.logger.debug(
                            "pm_engine",
                            f"Skipping verifier enqueue for fast-track '{original}' "
                            "(单 run 全包，验证在 fast-track run 内完成)",
                        )
                        return
                    self._enqueue(original, "verifier")
        finally:
            self._handling_events.discard(event_key)

    def _find_implementer_worktree(self, spec_name: str) -> Optional[Path]:
        """Find the active implementer worktree for a SPEC, or None."""
        wt_mgr = getattr(self.agent_runner, "worktree_manager", None)
        if wt_mgr is None:
            return None
        return wt_mgr.find_implementer_worktree(spec_name)

    def _read_implementer_result(self, spec_name: str) -> Optional[dict]:
        """读取 implementer 写入的 .fenix-run-result.json，优先从活跃 worktree 读取。

        Returns the parsed dict, or None if not found/invalid.
        """
        result_path = None
        # Try worktree first
        wt_path = self._find_implementer_worktree(spec_name)
        if wt_path:
            wt_result = wt_path / ".fenix-run-result.json"
            if wt_result.exists():
                result_path = wt_result
                self.logger.debug(
                    "pm_engine",
                    f"Reading implementer result from worktree: {wt_result}",
                )
        # Fallback to project root
        if result_path is None:
            root_result = self.project_root / ".fenix" / ".fenix-run-result.json"
            if root_result.exists():
                result_path = root_result
                self.logger.debug(
                    "pm_engine",
                    f"Reading implementer result from project root: {root_result}",
                )
        if result_path is None:
            return None
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # 共享结果文件护栏（fail-closed，fix-fasttrack-resultfile-missing
                # -redispatch D3）：文件携带的 spec 字段必须**严格**等于当前 spec
                # 才采信——spec 缺失/为空/非字符串/与当前 spec 不符一律 ignore
                # 返回 None。主树 .fenix/.fenix-run-result.json 是跨 spec 共享单例，
                # 任何 spec 成功都会覆盖写它；无 stamp 残留（旧格式/异常）不得被
                # 误采信为当前 spec 的结果（2026-09-12 事故：无 stamp 残留被
                # fail-open 采信致死亡判定误判）。worktree 文件同规则收紧
                # （worktree 复用也可能带旧 spec 残留）。
                stamped = data.get("spec")
                if stamped != spec_name:
                    self.logger.warning(
                        "pm_engine",
                        f"Ignoring stale result file {result_path}: "
                        f"spec={stamped!r} != '{spec_name}' (fail-closed)",
                    )
                    return None
                # 顶层 status 与 verification.verdict 混淆归一化（add-agent-prompt-files
                # 事故 2026-09-03）：agent 把 verdict 值写到顶层 status（如
                # status="verified" 且 verification.verdict=verified），语义上完全成功
                # 的 run 被判失败整轮作废重派。verdict 语义本就由内层承载，顶层合同
                # 唯一合法值是 "success"——status ∈ verdict 值域时确定性映射，不吞
                # 真失败（其他非法值仍走失败分支并带处方）。
                if data.get("status") in ("verified", "bug-found"):
                    data["status"] = "success"
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _partial_attribution(self, spec_name: str, impl_result: dict, result=None) -> str:
        """partial 结果的失败归因构造（fix-impl-tasks-completion-gate D6）。

        partial 是「诚实申报未完成」的合法终态，其失败归因 MUST 非空且由
        ``unfinished`` 清单与 ``completed_tasks`` 反推的缺口 id 构成——MUST NOT
        沿用为 None 的 ``result.error``（成功进程的 error 为 None，沿用会产出
        「失败但无归因」的空壳处置，违背 admin 处置非空壳约定）。归因同时是
        重派 prompt 的缺口注入来源。缺口口径统一走
        ``core.run_task_track.gap_from_result``（与产物硬门同源），MUST NOT
        读主树 tasks.md 勾选。

        Args:
            spec_name: spec 名（tasks.md 缺口兜底用）。
            impl_result: 实现者结果 dict（顶层含 status/unfinished/completed_tasks）。
            result: 可选 AgentRunResult（优先取 result.error 作为前缀上下文）。

        Returns:
            非空归因文案。
        """
        unfinished = impl_result.get("unfinished")
        if isinstance(unfinished, list) and unfinished:
            gap = [str(t) for t in unfinished]
        else:
            # 防御：unfinished 缺失/非数组时由结果文件 completed_tasks 反推缺口
            # （core.run_task_track.gap_from_result，与产物硬门同源）。MUST NOT
            # 回退主树 tasks.md 勾选——主树 [x] 只在成功/merge-back 路径回写，
            # partial 收敛走不到，读它会产出「已完成任务也算未完成」的假归因
            # （fix-robustness-edge-cases 事故 2026-09-17）。
            try:
                from core.run_task_track import gap_from_result

                gap = gap_from_result(impl_result, self.project_root, spec_name)
            except Exception:
                gap = []
        if gap:
            shown = "、".join(gap[:20])
            if len(gap) > 20:
                shown += f" 等共 {len(gap)} 项"
            return f"实现者申报未完成（status=partial）：{shown}"
        return "实现者申报未完成（status=partial）"

    def _write_impl_result_snapshot(self, spec_name: str, result_dict: dict) -> None:
        """把 implementer 成功结果 dict 原子快照到 .fenix/verify-progress/<spec>/impl-result.json。

        复用 family.py prev-impl-result.json 同款手法：tempfile + os.replace 原子写。
        快照用于 verified→done 门禁证据源（fix-verified-gate-evidence-race D1/D2），
        优先级高于共享文件 .fenix/.fenix-run-result.json。
        快照写失败仅记 WARNING，不阻塞派发主流程（fail-open；快照缺失由门禁
        fail-closed 兜底，见 _task_completion_blocker D2）。
        重派后新成功自然覆盖旧快照（os.replace 天然幂等）。
        """
        vp_dir = self.project_root / ".fenix" / "verify-progress" / spec_name
        try:
            vp_dir.mkdir(parents=True, exist_ok=True)
            snap_path = vp_dir / "impl-result.json"
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".impl-result.{spec_name}.",
                suffix=".tmp",
                dir=str(vp_dir),
            )
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(result_dict, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(str(tmp_path), str(snap_path))
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        except (OSError, TypeError, ValueError) as e:
            # 补捕 TypeError/ValueError（code-review item 9e35ac5c6b56）：json.dump
            # 遇不可序列化对象/非法代理对不在 OSError 之列，不捕则违背 docstring
            # 承诺的 fail-open——快照写失败仅记 WARNING，不阻塞派发主流程
            self.logger.warning(
                "pm_engine",
                f"impl-result 快照写入失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _cleanup_shared_result_file(self, spec_name: str) -> None:
        """消费后清理主树共享结果文件（fix-fasttrack-resultfile-missing-redispatch D4）。

        在本次采信消费 + ``_write_impl_result_snapshot`` 落盘 per-spec 快照**之后**
        调用。仅当共享文件 .fenix/.fenix-run-result.json 的 stamp 严格匹配当前 spec
        （即本次采信消费的正是该文件）时才删除；stamp 缺失/不符时不动
        （可能是其它 spec 的在途文件，误删会伤及多读者）。删除失败仅记 WARNING
        不阻塞主流程（fail-open，残留由 stamp 严格校验在后续读取时拒绝）。
        """
        shared = self.project_root / ".fenix" / ".fenix-run-result.json"
        tmp: Optional[Path] = None
        try:
            if not shared.exists():
                return
            data = json.loads(shared.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("spec") != spec_name:
                return  # 非本 spec 的文件（其它 spec 在途残留）→ 不动
            # TOCTOU 消除（code-review item c1cfce1c1c75）：校验通过后不经
            # unlink 直删——read 与 unlink 两步之间并发实现 run 可能已把共享
            # 路径覆写为其它 spec 的在途结果，unlink 会误删他 spec 文件。改为
            # 先同目录 rename 到唯一临时名（原子摘除共享路径），再复核临时名
            # 内容 stamp 仍为本 spec 才删除；复核不符说明摘到的已是覆写后的
            # 他 spec 文件，原样还回共享路径不动。
            tmp = shared.with_name(
                f"{shared.name}.cleanup-{os.getpid()}-{time.time_ns()}"
            )
            try:
                os.rename(str(shared), str(tmp))
            except OSError:
                tmp = None  # 摘除失败 = 未动任何文件，无需清理临时名
                raise
            check = json.loads(tmp.read_text(encoding="utf-8"))
            if not isinstance(check, dict) or check.get("spec") != spec_name:
                # 共享路径在校验后被覆写为其它 spec 的在途结果 → 还回不动
                if not shared.exists():
                    os.replace(str(tmp), str(shared))
                else:  # 已有更新的在途文件在位 → 仅丢弃陈旧副本
                    tmp.unlink()
                tmp = None
                return  # 其它 spec 的文件 → 不动
            tmp.unlink()
            tmp = None
            self.logger.info(
                "pm_engine",
                f"已消费共享结果文件已清理 '{spec_name}'：{shared}",
            )
        except (json.JSONDecodeError, OSError) as e:
            # 摘除后中途失败：尽量把临时名还回共享路径，避免本 spec 结果蒸发
            # 且不留垃圾临时文件（还回失败时 WARNING 文案携带残留路径供排查）
            if tmp is not None and tmp.exists():
                try:
                    if not shared.exists():
                        os.replace(str(tmp), str(shared))
                    else:
                        tmp.unlink()
                except OSError:
                    pass
            if isinstance(e, json.JSONDecodeError):
                return  # 损坏/无 stamp 文件由读取侧 fail-closed 拒绝，此处不动
            self.logger.warning(
                "pm_engine",
                f"共享结果文件清理失败 '{spec_name}'（非阻塞，残留由 stamp " f"严格校验兜底）: {e}",
            )

    def _read_impl_result_for_gate(self, spec_name: str) -> Optional[dict]:
        """门禁证据读取（fix-verified-gate-evidence-race D2）：per-spec 快照优先。

        优先级：
        1. 快照 .fenix/verify-progress/<spec>/impl-result.json（stamp=本 spec 才采信）；
        2. 快照缺失/stamp 不符 → 回退共享文件路径（``_read_implementer_result``
           既有 worktree/root 行为不变，仅门禁内部改读序，不影响 dispatch 语义）。

        2026-09-07 事故：共享文件 .fenix/.fenix-run-result.json 是跨 spec 共享的，
        被其它 spec 成功覆盖后门禁「无法证伪即放行」静默放行带未勾任务的 spec。
        快照是同 spec 的持久证据，不随共享文件覆盖而蒸发。
        """
        # 1) per-spec 快照优先
        snap_path = (
            self.project_root / ".fenix" / "verify-progress" / spec_name / "impl-result.json"
        )
        if snap_path.exists():
            try:
                data = json.loads(snap_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    stamped = data.get("spec")
                    if isinstance(stamped, str) and stamped and stamped != spec_name:
                        self.logger.warning(
                            "pm_engine",
                            f"Ignoring stale impl-result snapshot {snap_path}: "
                            f"spec='{stamped}' != '{spec_name}'",
                        )
                    elif data.get("spec") == spec_name:
                        # status 归一化与 _read_implementer_result 同语义
                        if data.get("status") in ("verified", "bug-found"):
                            data["status"] = "success"
                        return data
            except (json.JSONDecodeError, OSError):
                pass
        # 2) 快照缺失/stamp 不符 → 共享文件兜底（现有行为不变）
        return self._read_implementer_result(spec_name)

    # ── 任务进度写侧回写（add-task-progress-sync） ───────────────────
    #
    # implementer run 成功后，从 run 产物确定性解析已完成任务集，把主树
    # tasks.md 对应 id 的 `- [ ]` 改成 `- [x]`，不撤销任何既有勾选（只增不减）。

    _TASK_LINE_RE = re.compile(r"^(\s*-\s+)\[(\s|x)\](\s+)(\d+\.\d+[a-z]?)(.*)$")

    def _sync_task_progress(self, spec_name: str):
        """把已成功完成的任务勾选确定性回写进主树 tasks.md 并 commit。

        三级回退（fix-implementer-task-progress D2）：
        1. done_ids 非空 → 按 tasks.md 编号精确对齐（既有行为不变）；
        2. done_ids 空但 flat_done 非空（subject 无编号 run）→ 弱一致性校验通过时
           按创建序勾选 tasks.md 扁平任务序列前 max(flat_done)+1 个未完成项；
           弱校验：归并比至多 1:5（未完成项数 ≤ created_count*5），拦截创建数与
           任务清单明显不匹配的场景（run 只建了零星任务时 flat 序映射不可信）；
        3. 两者皆空 → 跳过（不误写）。

        幂等：已勾选的条目跳过（只增不减）；无 run 产物 / 工作树不干净时
        直接返回（不报错、不产生空 commit）。任何异常由调用方捕获，不阻塞主流程。
        """
        tasks_path = self.project_root / "spec" / "changes" / spec_name / "tasks.md"
        if not tasks_path.exists():
            self.logger.debug("pm_engine", f"任务回写跳过（无 tasks.md）：{spec_name}")
            return

        run_file = find_impl_run_file(self.project_root, spec_name)
        if run_file is None:
            self.logger.debug("pm_engine", f"任务回写跳过（无 run 产物）：{spec_name}")
            return

        rd = parse_run_task_done(run_file)
        done_ids = rd.get("done_ids") or set()
        flat_done = rd.get("flat_done") or set()
        created_count = int(rd.get("created_count") or 0)
        if not done_ids and not flat_done:
            self.logger.debug("pm_engine", f"任务回写跳过（done_ids/flat_done 皆空）：{spec_name}")
            return

        # 工作树不干净时跳过（如 merge-back 冲突恢复期），留待下个调度周期重试
        if self._worktree_is_dirty():
            self.logger.debug("pm_engine", f"任务回写跳过（工作树不干净）：{spec_name}")
            return

        try:
            text = tasks_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        lines = text.split("\n")
        # 写侧接受域单点对齐（code-review item 382e6930d3c1）：tasks.md 数字
        # 任务勾选行的单一实现点是门禁侧共用的 core.run_task_track.
        # _TASK_CHECKBOX_RE（D2，_task_completion_blocker 注释同款「禁止第二套
        # 正则漂移」对写侧同样生效）。此前 _TASK_LINE_RE 自带缩进/变距容忍，
        # 接受域比门禁侧宽——缩进勾选行写侧能勾、门禁侧 parse_tasks_md 视作
        # 无任务（all_ids 空 → 门禁恒放行），完成度一致性门禁对该形态静默
        # 失效。故 _TASK_LINE_RE 只承担行结构捕获（组序被
        # tests/test_task_track.py::test_writeback_checks_suffixed_lines 锁定，
        # 不可改组布局），接受域一律以共享正则放行为准：写侧只勾门禁侧看得见
        # 的行，两侧不再漂移。
        task_lines = []
        for i, ln in enumerate(lines):
            gate_m = _TASK_CHECKBOX_RE.match(ln)
            m = self._TASK_LINE_RE.match(ln)
            # 末位交叉校验：两口径须解析出同一 id（防任一侧正则演进后对同一行
            # 截断出不同 id——「解析得出、判定判非法」互斥结论同型防御，见
            # run_task_track._TASK_ID_FULL_RE 注释）
            if gate_m is not None and m is not None and gate_m.group(2) == m.group(4):
                task_lines.append((i, m))
        changed = False
        checked_count = 0  # 本轮实际翻转的行数（日志上报口径）

        if done_ids:
            # 第 1 级：done_ids 精确对齐（既有行为不变）
            for i, m in task_lines:
                if m and m.group(4) in done_ids and m.group(2) != "x":
                    # `- [ ]` → `- [x]`，仅当该 id 在 done_ids 且当前未勾选
                    lines[i] = f"{m.group(1)}[x]{m.group(3)}{m.group(4)}{m.group(5)}"
                    changed = True
                    checked_count += 1
        else:
            # 第 2 级：flat 回退（subject 无编号 run），弱一致性校验 + 按创建序勾选
            unchecked = [(i, m) for i, m in task_lines if m and m.group(2) != "x"]
            if not unchecked:
                self.logger.debug("pm_engine", f"任务回写跳过（无未完成项）：{spec_name}")
                return
            # [fenix-ignore:7970cdb07339] 前缀勾选在 tasks.md 存在遗留未勾任务时确有勾错对象风险，
            # 但「1:5 弱校验 + 前缀 max(flat_done)+1」语义被 tests/test_task_progress_protocol.py
            # 锁定（27 未勾/6 创建须放行勾前 4），subject 无编号的 run 产物没有可靠
            # 信号区分遗留任务，按条目建议收紧即破坏锁定行为（上轮已实测回归）——
            # 维持原设计，勾错风险由 1:5 弱校验兜底
            if len(unchecked) > created_count * 5:
                self.logger.debug(
                    "pm_engine",
                    f"任务回写跳过（flat 弱校验不符：created={created_count} "
                    f"未完成={len(unchecked)}）：{spec_name}",
                )
                return
            # 前 max(flat_done)+1 个未完成项勾选（max 保证已汇报完成的任务全覆盖；
            # 宁多勾不勾错——flat 回退仅增不减既有勾选）
            bound = min(max(flat_done) + 1, len(unchecked))
            for i, m in unchecked[:bound]:
                lines[i] = f"{m.group(1)}[x]{m.group(3)}{m.group(4)}{m.group(5)}"
                changed = True
                checked_count += 1

        if not changed:
            self.logger.debug("pm_engine", f"任务回写跳过（无新勾选）：{spec_name}")
            return

        # 原子写（临时文件 + replace），异常由调用方捕获不阻塞主流程
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".tasks.{spec_name}.",
                suffix=".tmp",
                dir=str(tasks_path.parent),
            )
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(str(tmp_path), str(tasks_path))
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        except OSError as e:
            self.logger.warning("pm_engine", f"任务回写写入失败 '{spec_name}': {e}")
            return
        commit_msg = f"[fenix] {spec_name}: sync task progress from run record"
        ok, err = self._git_commit([str(tasks_path)], commit_msg)
        if not ok:
            self.logger.warning("pm_engine", f"任务回写 commit 失败 '{spec_name}': {err}")
            return
        # 勾选数按本轮实际翻转行数上报（code-review item c7092742360e，对齐 flat
        # 兜底分支 c9632f1ba5fb 的实际写入数 bound 口径）：done_ids 分支取
        # len(done_ids) 在重跑场景（部分行已勾选被跳过）虚大于真实改动数。
        self.logger.info(
            "pm_engine",
            f"任务进度回写成功 '{spec_name}'：勾选 {checked_count} 个任务"
            f"（{'done_ids 精确' if done_ids else 'flat 兜底'}）",
        )

    def _worktree_is_dirty(self) -> bool:
        """主树已跟踪内容是否存在未提交改动（add-task-progress-sync 回写的安全闸门）。

        只看已跟踪内容（``--untracked-files=no``，code-review item 1cab71ff17b4）：
        未跟踪散件（spec/knowledge 在途产物、主树常驻 WIP 散件）与本回写的
        merge-back 基线冲突无关；计入脏会让任务勾选回写被无关散件无限期阻塞，
        docstring 所称「留待下个调度周期重试」在该形态下永不成立。
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=str(self.project_root),
                capture_output=True,
                # errors="replace"（code-review item 022c2e4ced2a，与
                # core/regression.py 加固先例同款）：git 输出含非 UTF-8 字节时
                # 严格解码抛 UnicodeDecodeError 逃出宽 except，误判推送/工作树。
                text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                return True  # 无法判断时保守视为脏，跳过回写
            return bool(result.stdout.strip())
        except Exception:
            return True

    def _git_commit(self, paths: list, message: str, repo_root=None) -> tuple:
        """在 ``repo_root``（缺省 ``project_root``）对指定路径执行 git add + commit。

        ``repo_root``（fix-relocation-writeback-layer Task 1.2）：声明修正的写回层
        为 worktree 命中时，改写发生在该 worktree 内，提交 MUST 落在**该 worktree
        的分支**——故提交根随落点（同源原则）。缺省 ``None`` 保持既有行为（主树
        提交，调用点不回归）。``paths`` 为相对该根的路径。

        Returns: (success: bool, error_message: str)
        """
        root = str(repo_root) if repo_root else str(self.project_root)
        try:
            add = subprocess.run(
                ["git", "add", "--"] + paths,
                cwd=root,
                capture_output=True,
                # errors="replace"（code-review item 022c2e4ced2a，与
                # core/regression.py 加固先例同款）：git 输出含非 UTF-8 字节时
                # 严格解码抛 UnicodeDecodeError 逃出宽 except，误判推送/工作树。
                text=True, encoding="utf-8", errors="replace",
                timeout=60,
            )
            if add.returncode != 0:
                return False, add.stderr.strip() or f"git add exit {add.returncode}"
            commit = subprocess.run(
                ["git", "commit", "-m", message, "--"] + paths,
                cwd=root,
                capture_output=True,
                # errors="replace"（code-review item 022c2e4ced2a，与
                # core/regression.py 加固先例同款）：git 输出含非 UTF-8 字节时
                # 严格解码抛 UnicodeDecodeError 逃出宽 except，误判推送/工作树。
                text=True, encoding="utf-8", errors="replace",
                timeout=120,
            )
            if commit.returncode != 0:
                return False, commit.stderr.strip() or f"git commit exit {commit.returncode}"
            return True, ""
        except subprocess.TimeoutExpired:
            return False, "git commit timed out"
        except Exception as e:
            return False, str(e)

    def _task_completion_blocker(self, spec_name: str) -> str | None:
        """verified→done 任务完成一致性门禁（add-task-progress-sync + fix-verified-gate-evidence-race）。

        返回 None 表示门禁通过（可推进到 done）；返回带 ``TASK_GAP_ERROR_PREFIX``
        前缀的字符串表示缺口拦截，此时应阻断 auto approve / verified→done，
        把缺口写入 error 字段供人工裁决。

        证据源优先级（fix-verified-gate-evidence-race D2）：
        1. per-spec 快照 .fenix/verify-progress/<spec>/impl-result.json（stamp=本 spec）；
        2. 快照缺失时主树共享结果文件（stamp=本 spec）（存量在飞 spec 兼容）；
        3. 两者皆缺失：
           - STATE.implementer_run 为空（legacy/手工）→ 放行；
           - implementer_run 在场 → fail-closed 拦截。

        tasks.md 缺失或不含数字编号任务时直接放行（无 gap 概念，现状不变）。
        放行路径自动清除既有 task-gap: error（人工补勾感知路径）。
        """
        result = self._read_impl_result_for_gate(spec_name)

        if result is None:
            # 两者皆缺失 → fail-closed 分支（D2 规则 3）
            spec_entry = self.state_machine.read_one(spec_name) or {}
            if not spec_entry.get("implementer_run"):
                # legacy / 手工 spec：无 run 记录 → 放行（现状不变）
                return None
            # implementer_run 在场 → 检查 tasks.md 是否有未勾数字任务
            # fix-impl-tasks-completion-gate D2：与产物硬门共用同一解析实现点
            # （core.run_task_track.parse_tasks_md），禁止第二套正则漂移。
            all_ids, checked_ids = parse_tasks_md(self.project_root, spec_name)
            has_unchecked_numeric = any(tid not in checked_ids for tid in all_ids)
            if not has_unchecked_numeric:
                return None  # 全勾 / 无数字任务 → 无缺口可拦
            return TASK_GAP_ERROR_PREFIX + "run 证据缺失（快照与共享文件均无），需人工确认"

        # 证据存在 → 检查 impl_status
        impl_status = result.get("status")
        if impl_status == "partial":
            # fix-impl-tasks-completion-gate D6：partial 轮之后 MUST NOT 放行到
            # done——partial 自带 unfinished 缺口证据（快照/共享文件残留 partial
            # 时把带未完成任务的 spec 静默推进 done 正是本 SPEC 消除的事故形态）。
            # fail-closed：归因带 TASK_GAP_ERROR_PREFIX，与人工回炉入口
            # （task-reflow）同语义可处置。缺口口径走统一实现点
            # ``core.run_task_track.gap_from_result``（与产物硬门同源），
            # MUST NOT 回退主树 tasks.md 勾选。
            #
            # ── 诚实退出豁免（2026-09-16 改进②）──
            # 若缺口全部 ⊆ 结果文件的 ``unattainable`` 申报（实现者机械声明
            # 「确实无法由 agent 完成」，如人工运维门控任务），不再拦截：放行到
            # done，并把申报内容落一条可见的人工待办告警。部分未申报的仍按
            # fail-closed 拦截。
            #
            # fix-redispatch-loop-governance D2b：收敛判据单点在
            # ``core.run_task_track.honest_exit_convergence_gap``（内部即
            # gap_from_result + parse_unattainable）——含非法申报项（非 dict /
            # task 非合法 id / 缺 reason）时判不收敛（fail-closed），MUST NOT
            # 「合法项生效、非法项静默忽略」（产物硬门正常时非法申报已被拦，
            # 但「只卡第一次」降级放行后非法条目可抵达本收敛点，部分采信等于
            # 开了洗白窗口）。
            from core.run_task_track import (
                gap_from_result as _gap_from_result,
            )
            from core.run_task_track import (
                honest_exit_convergence_gap as _honest_convergence_gap,
            )

            # code-review item 833f70ceec3a：与 rollback._honest_exit_gap（同一
            # 收敛判据的另一调用点，"判定异常一律按失败处置"）同口径的
            # fail-closed 包裹——result dict 来自 agent 写的 .fenix-run-result.json
            # （半受信输入），解析异常不得从 _on_spec_verified 穿透中断当轮
            # verified 收口，按失败处置返回带异常摘要的拦截串（走 task-gap
            # blocker 通道供人工裁决）。
            try:
                converged_gap = _honest_convergence_gap(
                    result, self.project_root, spec_name
                )
            except Exception as e:  # noqa: BLE001 — 判定异常按失败处置（fail-closed）
                self.logger.warning(
                    "pm_engine",
                    f"unattainable 收敛判定异常 '{spec_name}'（fail-closed 拦截）: "
                    f"{type(e).__name__}: {e}",
                )
                return (
                    TASK_GAP_ERROR_PREFIX
                    + "unattainable 收敛判定异常（按失败处置）："
                    + f"{type(e).__name__}: {e}"
                )
            if converged_gap:
                self._note_unattainable_todos(spec_name, result, converged_gap)
                self._clear_task_gap_error(spec_name)
                return None  # 缺口全部已诚实申报 → 放行
            gap = _gap_from_result(result, self.project_root, spec_name)
            # D2b 审计：非法申报项在归因文案中显式标注（不静默）。
            _unat_ids, _inv = _parse_unattainable(result)
            _inv_note = f"（且含 {len(_inv)} 个非法 unattainable 申报项）" if _inv else ""
            return (
                TASK_GAP_ERROR_PREFIX
                + "实现者申报未完成（partial）："
                + "、".join(gap[:20])
                + (f" 等共 {len(gap)} 项" if len(gap) > 20 else "")
                + _inv_note
            )
        if impl_status != "success":
            return None  # 非 success（error/其它）→ 放行（现状不变）

        tasks_path = self.project_root / "spec" / "changes" / spec_name / "tasks.md"
        if not tasks_path.exists():
            return None

        # 解析 tasks.md 的勾选状态与全部任务 id（D2 共用实现点）
        all_ids, checked_ids = parse_tasks_md(self.project_root, spec_name)

        # 解析 run 记录的完成任务 id
        run_file = find_impl_run_file(self.project_root, spec_name)
        done_ids: set = set()
        if run_file is not None:
            done_ids = parse_run_task_done(run_file).get("done_ids") or set()

        # 缺口：未勾选 且 不在 done_ids 中的任务
        gap = [tid for tid in all_ids if tid not in checked_ids and tid not in done_ids]
        if gap:
            return TASK_GAP_ERROR_PREFIX + "未完成任务：" + "、".join(gap)

        # ── 无缺口：清除既有 task-gap error（人工补勾的感知路径）──
        # 重评门禁时 snapshot 持久在，缺口已消除 → 放行并显式清除此前写入
        # 的 task-gap: 标记，使 error 字段不再残留过期结论。
        self._clear_task_gap_error(spec_name)
        return None

    def _clear_task_gap_error(self, spec_name: str) -> None:
        """放行路径清除既有 task-gap: error（人工补勾的感知路径，D2）。

        仅当 error 字段以 TASK_GAP_ERROR_PREFIX 开头时清除，不误删其它 error。
        """
        try:
            spec_entry = self.state_machine.read_one(spec_name) or {}
        except Exception:
            return
        err = spec_entry.get("error")
        if isinstance(err, str) and err.startswith(TASK_GAP_ERROR_PREFIX):
            self.state_machine.update_spec(spec_name, {"error": None})
            self.logger.info(
                "pm_engine",
                f"task-gap 已补勾，清除 error：'{spec_name}'",
            )

    def _note_unattainable_todos(self, spec_name: str, result: dict,
                                 gap: "list | None" = None) -> None:
        """诚实退出（改进②）：把 unattainable 申报落一条可见的人工待办告警。

        门禁放行「缺口全部已申报」的 partial 时调用——不静默放行：写 admin
        escalation 告警（含任务 id 与 reason），使 /fenix-approve 环节可见
        「哪些任务交给了人工」。告警写失败仅 debug 不阻断放行。
        """
        try:
            ids, _invalid = _parse_unattainable(result)
            items = result.get("unattainable") or []
            detail = []
            for it in items:
                if isinstance(it, dict) and it.get("task") in ids:
                    detail.append(f"{it.get('task')}: {str(it.get('reason'))[:120]}")
            from core.admin_store import AdminStore, ESCALATION
            store = AdminStore(self.project_root, self.logger)
            # append 返回值必须接收（code-review item 372d1c5a3735，对齐
            # item 2570ca391771 契约）：下限保护拒写时返回 None、记录未落盘，
            # 不得照记「已写入」成功日志误导事后对账。
            written = store.append({
                "kind": ESCALATION,
                "signal_type": "impl_unattainable_tasks",
                "spec": spec_name,
                "severity": "warning",
                "description": (
                    f"实现者诚实申报 {len(ids)} 个任务无法由 agent 完成，"
                    f"门禁已放行——这些任务需人工完成/确认"
                ),
                "evidence": "；".join(detail)[:600],
                "recommended_action": (
                    "在 /fenix-approve 前确认这些任务所需的人工动作（如重启 daemon、"
                    "审批、外部资源），完成后再推送"
                ),
            })
            if written is not None:
                self.logger.warning(
                    "pm_engine",
                    f"诚实退出放行 '{spec_name}'：unattainable={sorted(ids)} "
                    f"（已写人工待办告警）",
                )
            else:
                self.logger.warning(
                    "pm_engine",
                    f"诚实退出放行 '{spec_name}'：unattainable={sorted(ids)} "
                    f"（人工待办告警未落盘，下限保护拒写）",
                )
        except Exception as e:
            self.logger.debug(
                "pm_engine",
                f"unattainable 待办告警写入失败（不阻断放行）: {e}",
            )

    # ── judge 自述环境问题守卫（不派生 fix）────────────────────────

    _ENV_INFRA_MARKERS = (
        "环境问题",
        "环境配置",
        "环境故障",
        "测试环境",
        "非产品",
        "不是产品",
        "而非产品",
    )

    # ── 派发队列老化（dispatch-queue-aging / design D3）─────────

    @staticmethod
    def _merge_fingerprint(error: str) -> str:
        """对 merge 错误计算稳定指纹（fix-fenix-token-waste）。

        归一化：整体去空白后取 sha1 前 12 位。git 对同一根因的报错逐字节一致，
        因此可用字符串归一化哈希；不同根因会得到不同指纹。
        """
        norm = "".join((error or "").split())
        return hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:12]

    @staticmethod
    def _redispatch_cause_fingerprint(error: str) -> str:
        """对失败归因文案计算稳定指纹（同因重派熔断，fix-redispatch-loop-governance D3/D3.1）。

        与 ``_merge_fingerprint`` 同族手法 + 显式剔除**易变段**：

        - run_id（``impl-<spec>-<epoch>[-aN][-rN]`` 形态）——每轮必然变化；
        - 9 位以上数字（时间戳 / epoch / pid）——每轮必然变化；
        - worktree 路径（``…/.claude/worktrees/impl-…`` 形态）——轮次不同路径不同。

        剔除后整体去空白取 sha1 前 12 位。保留原因主干：**同缺口的连续 partial**
        （归因文案「实现者申报未完成（status=partial）：X」，缺口相同则逐字节一致）
        得到同一指纹；不同根因（缺口不同 / 归因不同）得到不同指纹——「每轮都在变
        的原因不该熔断，每轮不变的原因才该」（design D3）。归一化过度会把不同原因
        判为同因 →「不同因不误熔断」回归用例锁定边界（TestSameCauseCircuitBreaker）。
        """
        text = (error or "")
        # 先剔 worktree 路径（最大易变块，内部含 run_id/时间戳——先整体移除避免
        # 残留碎片如 `//spec` 污染指纹），再剔独立 run_id 与 9 位以上数字时间戳。
        text = _REDISPATCH_WT_PATH_RE.sub("", text)
        text = _REDISPATCH_RUN_ID_RE.sub("", text)
        text = _REDISPATCH_TIMESTAMP_RE.sub("", text)
        norm = "".join(text.split())
        return hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:12]

    # ── 环境性失联门禁（verify-environment-sanity-gate）───────────

    # ── worktree 竞争类异常判据（evo-add-verify-dispatch-single-flight 3.2）──
    # 新验证流程失败按异常文本分流降级策略：竞争类（worktree 锁碰撞的 gave up
    # 终态签名，文案签名自 fix-restart-dual-dispatch 沿用、
    # evo-add-worktree-acquire-backoff 保持不变）先重入新流程一次再降级——
    # 竞争是瞬时资源冲突，peer 排空后重试即成功，直接降级会把整条三步链
    # （出题/执行/judge，实测 $1.86/835s）作废换 legacy 接管（$1.36/568s）双烧。
    # 判不准 fail-open 回直接降级（保守侧＝现状）。fragment 判据只锚定终态
    # 签名原文，MUST NOT 用宽泛词（如单独 "gave up"）。
    _WORKTREE_CONTENTION_ERROR_FRAGMENTS = (
        "gave up: parallel run or manual freeze",
    )
    # 验证管线 worktree 碰撞面（主 verifier 条目＋管线内同步派发的 judge/
    # 出题 run）；重试前逐一复查，任一仍活跃即不重试。
    _PIPELINE_WORKTREE_LOCK_AGENT_TYPES = ("verifier", "planner-judge", "planner-plan")

    def _is_worktree_contention_error(self, error: Exception) -> bool:
        """判定验证管线异常是否 worktree 竞争类（降级分流判据，3.2）。"""
        text = str(error or "")
        return any(frag in text for frag in self._WORKTREE_CONTENTION_ERROR_FRAGMENTS)

    def _worktree_locks_released(self, spec_name: str) -> bool:
        """重试前校验本 spec 验证管线碰撞面的 worktree 锁已全部释放。

        design 决策 5：派发在飞集合对同 spec 自指（本 run 自身条目必然在飞
        登记），无 peer 判别力；lifecycle 锁侧 has_active_lock 按
        spec:agent_type 记账才是「是否有其它 run 持锁」的权威判据。锁仍活跃
        → 不重试（必然再撞锁白烧一轮），按非竞争路径直接降级。句柄缺失/
        判定异常 fail-open 放行重试（竞争判据已先行命中，重试成本一次封顶）。
        """
        try:
            wm = getattr(self.agent_runner, "worktree_manager", None)
            if wm is None or not hasattr(wm, "has_active_lock"):
                return True
            return not any(
                wm.has_active_lock(spec_name, agent_type)
                for agent_type in self._PIPELINE_WORKTREE_LOCK_AGENT_TYPES
            )
        except Exception:
            return True

    def _run_verification_pipeline(self, spec_name: str):
        """执行三步验证流水线。

        步骤1: Planner Agent 生成测试场景
        步骤2: VerifyEngine 并行执行场景（DOM断言 + 视觉对比）
        步骤3: Planner Agent 判定结果

        新流程失败时自动降级到旧版 verifier；worktree 竞争类失败先重入新
        流程一次，仍败才降级（evo-add-verify-dispatch-single-flight 3.2）。
        """
        use_new_flow = self._get_config("agents.use_new_verifier", True)

        if not use_new_flow:
            self._run_legacy_verification(spec_name)
            return

        try:
            self._run_three_stage_verification(spec_name)
        except Exception as e:
            degrade_error = e
            if self._is_worktree_contention_error(e) and self._worktree_locks_released(
                spec_name
            ):
                self.logger.warning(
                    "pm_engine",
                    f"验证管线 worktree 竞争类失败 '{spec_name}': {e} — 锁已"
                    f"释放，先重入新流程一次再考虑降级"
                    f"（evo-add-verify-dispatch-single-flight 3.2）",
                )
                try:
                    self._run_three_stage_verification(spec_name)
                    return
                except Exception as e_retry:
                    degrade_error = e_retry
                    self.logger.warning(
                        "pm_engine",
                        f"竞争类重试仍失败 '{spec_name}': {e_retry}"
                        f"（首次失败: {e}）— 转降级通道"
                        f"（evo-add-verify-dispatch-single-flight 3.2）",
                    )
            # evo-add-worktree-acquire-backoff 1.3：模块级累计计数（实例按
            # run 重建，实例级计数恒为 1），WARNING 附「第 N 次降级」。
            global _NEW_VERIFIER_FALLBACK_COUNT
            _NEW_VERIFIER_FALLBACK_COUNT += 1
            self.logger.warning(
                "pm_engine",
                f"新验证流程失败 '{spec_name}': {degrade_error}，降级到旧版 verifier"
                f"（第 {_NEW_VERIFIER_FALLBACK_COUNT} 次降级）",
            )
            try:
                self._run_legacy_verification(spec_name)
            except Exception as e2:
                self.logger.error(
                    "pm_engine",
                    f"旧版 verifier 也失败了 '{spec_name}': {e2}",
                )
                # 两条验证路径都抛异常 = 验证基础设施未能运行（run 未启动），
                # 与产品 bug 无关：不得 transition bug-found（那会派生伪 fix 级联，
                # 本事故烧 token 的直接原因）。回 implemented + 退避重试。
                self._rollback_failed_dispatch(spec_name, "verifier", e2)

    # ── Push backoff helpers (design D3) ───────────────────────────

    def _signal_push_failed(self, spec_name: str, detail: str):
        """推送超限升级为 push_failed 困境信号（severity=major）写入 admin store。"""
        from core.admin_store import AdminStore, SIGNAL

        try:
            # AdminStore 构造纳入 try（code-review item 105c8965ec12，对齐
            # _note_unattainable_todos 手法）：构造若抛异常不得从 _push_lock
            # 临界区穿透，否则 _handle_push_failure 后续的退避计数/next_retry_at
            # 落盘（update_spec）被整体跳过——push 失败退避状态丢失。
            store = AdminStore(self.project_root, self.logger)
            # append 返回值必须接收（code-review item 372d1c5a3735，对齐
            # item 2570ca391771 契约）：下限保护拒写时返回 None、记录未落盘，
            # 不得照记「已写入」成功日志误导事后对账。
            written = store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "push_failed",
                    "spec": spec_name,
                    "severity": "major",
                    "description": (
                        f"SPEC '{spec_name}' 自动推送连续失败达到上限，"
                        f"已停止自动重试，需人工介入"
                    ),
                    "evidence": detail,
                    "recommended_action": (
                        "检查远端仓库权限与分支状态；"
                        "手动 git push origin main 后把 spec 标为 pushed"
                    ),
                }
            )
            if written is not None:
                self.logger.error(
                    "pm_engine",
                    f"push_failed 信号已写入 admin store: '{spec_name}'",
                )
            else:
                # 拒写仅降级 WARNING（报告可丢，主链不可断）：push 退避状态
                # 落盘不受本告警写入故障影响
                self.logger.warning(
                    "pm_engine",
                    f"push_failed 信号未落盘（下限保护拒写）: '{spec_name}'",
                )
        except Exception as e:
            # 告警写入失败降级 WARNING（报告可丢，主链不可断）：push 退避状态
            # 落盘不受本告警写入故障影响
            self.logger.warning(
                "pm_engine",
                f"push_failed 信号写入 admin store 失败: {e}",
            )

    # ── 推送核心：main 先行 + 分支尽力 (design D1/D2) ─────────────

    def _remote_branch_sha(self, ref: str) -> str | None:
        """查询远端分支/引用的 SHA（git ls-remote）。

        返回 SHA 字符串或 None（远端不存在 / 查询失败）。
        """
        try:
            result = subprocess.run(
                ["git", "ls-remote", "origin", ref],
                cwd=str(self.project_root),
                capture_output=True,
                # errors="replace"（code-review item 022c2e4ced2a，与
                # core/regression.py 加固先例同款）：git 输出含非 UTF-8 字节时
                # 严格解码抛 UnicodeDecodeError 逃出宽 except，误判推送/工作树。
                text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) == 2:
                        return parts[0]
            return None
        except Exception:
            return None

    def _local_branch_sha(self, branch: str) -> str | None:
        """获取本地分支 HEAD 的 SHA（git rev-parse）。"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "refs/heads/" + branch],
                cwd=str(self.project_root),
                capture_output=True,
                # errors="replace"（code-review item 022c2e4ced2a，与
                # core/regression.py 加固先例同款）：git 输出含非 UTF-8 字节时
                # 严格解码抛 UnicodeDecodeError 逃出宽 except，误判推送/工作树。
                text=True, encoding="utf-8", errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None

    def _git_push_ref(self, ref: str) -> tuple:
        """在 project_root 执行 git push origin <ref>。

        Returns: (success: bool, error_message: str)
        """
        try:
            result = subprocess.run(
                ["git", "push", "origin", ref],
                cwd=str(self.project_root),
                capture_output=True,
                # errors="replace"（code-review item 022c2e4ced2a，与
                # core/regression.py 加固先例同款）：git 输出含非 UTF-8 字节时
                # 严格解码抛 UnicodeDecodeError 逃出宽 except，误判推送/工作树。
                text=True, encoding="utf-8", errors="replace",
                timeout=120,
            )
            if result.returncode == 0:
                return True, ""
            error = (
                result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            )
            return False, error
        except subprocess.TimeoutExpired:
            return False, "git push timed out after 120s"
        except Exception as e:
            return False, str(e)

    def approve_push(self, spec_name: str) -> bool:
        """Approve and push a done SPEC (main 先行 + 分支尽力 + SHA 去重)。

        推送顺序（design D1）：
          1. git push origin main — 成功判据（非 FF → 失败走退避升级，禁止 force）
          2. feature 分支尽力推送 — 本地存在时推送，失败不影响 pushed 判定
        退避（design D3）：连续失败按指数退避延迟重试；超限发 push_failed 信号并停止。
        成功（含去重判定）→ 清 error、推 pushed。

        单飞（fix-daemon-lifecycle-races D5）：全临界区在实例级 ``_push_lock`` 内
        执行——重读 spec status → git push → transition(pushed) 原子化。verify
        成功后的同步直调（_on_spec_verified）与 event_bus spec_done 事件双路径
        并发进入时，第二流在锁上排队，进入后见 pushed 即幂等跳过（返回 True），
        不再双 push / 重复 project log / 触发 pushed→pushed ERROR。
        """
        # 全临界区持锁（check-then-act 原子化）。锁内不调用任何会再次获取
        # _push_lock 的路径（approve_push 自身不可重入调用），锁范围最小化。
        with self._push_lock:
            spec = self.state_machine.read_one(spec_name)
            if not spec:
                self.logger.warning("pm_engine", f"Cannot push '{spec_name}': SPEC not found")
                return False
            status = spec.get("status", "")
            if status == "pushed":
                # 幂等跳过：已 pushed（并发/回放先到），不重复 push 与 project log
                self.logger.info(
                    "pm_engine",
                    f"Push idempotent skip: '{spec_name}' already pushed "
                    f"(concurrent path or replay)",
                )
                return True
            if status != "done":
                self.logger.warning(
                    "pm_engine", f"Cannot push '{spec_name}': not in done state " f"(is '{status}')"
                )
                return False

            # ── D3: 退避期内跳过 ──
            if self._is_push_backoffed(spec):
                self.logger.info(
                    "pm_engine",
                    f"Push backoff active for '{spec_name}' — skipping (recovery replay)",
                )
                return False

            # ── D1: main 推送（成功判据） ──
            self.logger.info("pm_engine", f"Pushing main for '{spec_name}' (main-first)")
            main_ok, main_err = self._git_push_ref("main")

            if not main_ok:
                self._handle_push_failure(spec_name, spec, main_err, "main")
                return False

            self.logger.info("pm_engine", f"Main push succeeded for '{spec_name}'")

            # ── D1: 分支尽力推送（best-effort，失败不阻断 pushed） ──
            branch = self._resolve_push_branch(spec_name, spec)
            self._push_branch_best_effort(spec_name, branch)

            # ── 陈旧代码预检（evo-add-key-path-stale-code-preflight 2.1）──
            # 收尾步以进程内代码执行；磁盘代码较进程新（_code_stale）时在此
            # 请求重启（一条 WARNING + daemon 侧 .fenix/restart_request 防重），
            # 把修复装载延迟从小时级压到分钟级。收尾本身照常完成——预检不改
            # 变返回值与产物，重启由 supervisor 通道（2s 轮询）异步进行。
            from core.code_stale_flag import request_restart

            request_restart(
                lambda msg: self.logger.warning("pm_engine", msg),
                "verification-report 收尾提交",
            )

            # ── push 收口报告入库（evo-add-push-closeout-verification-report-commit）──
            # 闭合「报告落盘 ∈ (实现 merge, pushed)」入库窗口：验证裁决放行出口的
            # commit-on-write 在 merge 之前已跑完，晚于 merge 落盘（或落盘后有修改）
            # 的报告此后再无挂点（merge-back 与归档守卫均显式豁免 spec/changes）。
            # 本点是其后唯一 per-spec 必经收口点；插在归档收口之前是刻意选择——
            # 报告 commit 落本地后即被 _archive_auto_commit 尾部的 _git_push_ref
            # ("main") 顺带推上 origin，直达远端而非滞留本地 main 领先 origin 等下
            # 一次任意 push。失败语义对齐 verify_report 既有取向「报告可丢，主链不
            # 可断」：git add/commit 失败由 _commit_verification_report 内部捕获
            # （WARNING 落 verify_report 通道，含 spec 名与 stderr 摘要，本处不加
            # 前缀）、非 git 仓库静默跳过（无 WARNING）、已入库无变化幂等静默；
            # 外层再全兜底（仅兜函数本身向外抛的异常，记 push-closeout 前缀）——
            # 任何异常均不阻断 pushed 落定。
            try:
                from core.verify_report import _commit_verification_report

                _commit_verification_report(self.project_root, spec_name, self.logger)
            except Exception as e:  # noqa: BLE001 — 报告可丢，主链不可断
                self.logger.warning(
                    "pm_engine",
                    f"push-closeout 报告入库异常 '{spec_name}'"
                    f"（不阻断 pushed 落定）: {e}",
                )

            # ── 归档收口（archive-auto-commit）：代码 push 之后追加归档提交 ──
            # main 与分支推送成功后在流程尾部一次性收口当天全部归档移动
            # 残留（独立 commit + push）。失败仅 WARNING 不阻塞 spec 终态，残留留给
            # 下次 push 重试。零残留零动作。
            try:
                self._archive_auto_commit()
            except Exception as e:
                self.logger.warning(
                    "pm_engine",
                    f"归档收口执行异常（残留留给下次 push 重试，不阻塞 pushed）: {e}",
                )

            # ── 推送成功 → 推进 pushed，清 error + 退避标记 ──
            # fix-observability-gaps 2.2：推送收口自动来源
            # transition 返回值必须接收（code-review item f3173b3164ee）：
            # 状态已被外部改动（人工冻结/清除错误后回非 done 态）致
            # done→pushed 被拒时，不得清退避记账、不得写成功日志。
            moved = self.state_machine.transition(
                spec_name, "pushed",
                trigger_run_id=None, agent_type=None, channel="auto",
            )
            if not moved:
                self.logger.warning(
                    "pm_engine",
                    f"Push transition done→pushed rejected for '{spec_name}' "
                    f"(state changed externally) — skip backoff reset, "
                    f"wait next re-evaluation",
                )
                return False
            # push 成功 = 退避/重试计数的唯一清零点（code-review item
            # bbba88d8e6af）：字段化后与 error 文本标记同清，避免 spec 复回
            # done 时带陈旧退避期与计数。
            self.state_machine.update_spec(
                spec_name,
                {
                    "error": None,
                    PUSH_ATTEMPTS_FIELD: None,
                    PUSH_BACKOFF_NEXT_RETRY_AT_FIELD: None,
                },
            )
            # （b21d8f2d8247 同口径）报告可丢，主链不可断：pushed 已落定，
            # PROJECT_LOG 不可写/磁盘满不得中断 push 收口并向外传播
            try:
                self._append_project_log(
                    f"🚀 SPEC pushed: **{spec_name}** (main pushed, branch: {branch})"
                )
            except Exception as e:
                self.logger.warning(
                    "pm_engine",
                    f"push 收口项目日志失败 '{spec_name}'（非阻断，pushed 已落定）: {e}",
                )
            self.logger.info(
                "pm_engine",
                f"SPEC pushed: {spec_name} (main ok, branch={branch})",
            )
            return True

    # ── 归档自动提交（archive-auto-commit）──────────────────────────

    def _archive_move_residue(self) -> tuple:
        """检测 ``spec/changes/`` 下的归档移动残留（archive-auto-commit）。

        扫描实现已抽取为共享辅助 ``core.archive_commit.scan_archive_residue``
        （evo-mergeback-archive-residue-selfheal 1.1：push 尾部归档收口与
        merge-back 顺延链自愈评估共用同一特征扫描，避免两处判据漂移）；本方法
        保留原三元组契约 ``(found, spec_names, residue_paths)``，engine 内既有
        调用点（_archive_auto_commit）与测试零改动。判定失败时按「无残留」
        处理（fail-open：不因检测异常阻塞 push 主流程）。
        """
        scan = scan_archive_residue(self.project_root)
        if scan.error:
            self.logger.warning(
                "pm_engine",
                f"归档残留检测失败（按无残留处理，不阻塞 push）: {scan.error}",
            )
        return scan.found, scan.spec_names, scan.residue_paths

    @staticmethod
    def _archive_residue_spec(rel_path: str) -> str:
        """从 spec/changes/ / spec/archive/ 相对路径提取涉及 spec 名（委托共享辅助）。"""
        return archive_residue_spec(rel_path)

    def _archive_auto_commit(self) -> None:
        """归档收口：push 流程尾部一次性提交 spec/changes/ 的归档移动残留。

        archive-auto-commit spec：
        - 有残留 → ``git add -- spec``（限定 spec/ 目录，绝不 add -A；归档
          产物横跨 spec/changes 删除侧与 spec/archive 新增侧）+
          单 commit（``[fenix] archive: <spec 名列表> 归档入库``）+ push main；
        - 无残留 → 零动作（无空提交、无多余 push）；
        - commit/push 失败 → WARNING（含 stderr 摘要）并继续，spec 终态不受影响，
          残留留给下次 push 重试；提交内容不含 spec/ 之外的任何路径。
        """
        has_residue, spec_names, residue_paths = self._archive_move_residue()
        if not has_residue:
            return
        label = "、".join(spec_names) if spec_names else "spec"
        commit_msg = f"[fenix] archive: {label} 归档入库"
        # 收窄 add 范围到**实际残留路径**（code-review item 88209fa06ce0）：旧实现
        # `git add -- spec` 会把 spec/ 下所有未提交/未跟踪改动（其它 spec 的在途
        # 草案等）卷进「[fenix] archive: …」提交，与提交语义不符。残留清单本身已
        # 精确（只认 changes 删除侧与 archive 新增侧），据此逐路径提交。残留路径
        # 为空（理论不可达，has_residue 为真必有路径）时回退 catalog 级 add 兜底。
        _paths = residue_paths or ["spec"]
        ok, err = self._git_commit(_paths, commit_msg)
        if not ok:
            self.logger.warning(
                "pm_engine",
                f"归档收口 commit 失败（残留留给下次 push 重试，不阻塞 spec 终态）: {err}",
            )
            return
        self.logger.info(
            "pm_engine",
            f"归档收口 commit 成功: {commit_msg}",
        )
        push_ok, push_err = self._git_push_ref("main")
        if not push_ok:
            self.logger.warning(
                "pm_engine",
                f"归档收口 push 失败（残留已本地 commit，下次 push 携带）: {push_err}",
            )
        else:
            self.logger.info(
                "pm_engine",
                "归档收口 push 成功（spec/changes 归档产物已入库）",
            )

    def _handle_push_failure(self, spec_name: str, spec: dict, error_msg: str, ref: str):
        """处理推送失败：记录退避/重试状态；超限升级 push_failed 信号（D3）。"""
        # 配置非法值防御（code-review item 752b5436252d，与
        # _ready_stall_threshold_minutes 同款）：非数字字符串裸 int() 抛
        # ValueError/TypeError，从 _push_lock 内穿透 approve_push 一路炸到
        # _on_spec_done 调用方，中断 push 退避与升级链路——回退默认值。
        try:
            raw_max_retries = self._get_config("pm.push.max_retries", 3)
            # 显式判 None（code-review item 95c429d664e3）：`or 3` 会把合法的 0
            # （首次失败即停止自动重试）吞成默认 3，仅缺省时才回退默认值。
            max_retries = 3 if raw_max_retries is None else int(raw_max_retries)
        # 补捕 OverflowError（code-review item e09138583cd4）：.inf 解析为 float
        # 后 int() 抛 OverflowError 不在原元组，异常仍从 _push_lock 内穿透
        # approve_push 炸到 _on_spec_done——与 infra_breaker 归一先例同口径。
        except (TypeError, ValueError, OverflowError):
            max_retries = 3
        backoff_seconds = [300, 900]  # 默认指数退避：5 分钟、15 分钟
        cfg_backoff = self._get_config("pm.push.retry_backoff_seconds")
        if isinstance(cfg_backoff, list) and len(cfg_backoff) >= 2:
            # 元素类型防御（code-review item 6d4cfd57f4f4，与上方 max_retries
            # 同款）：逐元素 int() 转换，任一非法整体回退默认值——否则非数字
            # delay 在下方 now_ts + delay 处抛 TypeError 从 _push_lock 内穿透
            # approve_push 炸到 _on_spec_done 调用方。int() 保持整数格式
            # （reporting.py 按 next_retry_at=(\d+) 正则解析）。
            try:
                backoff_seconds = [int(x) for x in cfg_backoff]
            # 补捕 OverflowError（code-review item e09138583cd4）：元素为 .inf 时
            # int() 抛 OverflowError，同上从 _push_lock 内穿透中断退避记账。
            except (TypeError, ValueError, OverflowError):
                backoff_seconds = [300, 900]
            # 数值范围防御（code-review item b7a3cda88ddc，与 _ready_stall_
            # threshold_minutes 的 max(0.0, ...) 钳制、reporting.py 负值钳 0
            # 先例同口径）：负 delay 使 next_retry = now_ts + delay 落在过去
            # 时刻，_is_push_backoffed 按 next_retry > now 判定恒 False，退避
            # 窗口静默失效——push 失败后每个轮询周期立即重试直至烧光
            # max_retries 提前升级 push_failed。任一元素为负整体回退默认值。
            if any(x < 0 for x in backoff_seconds):
                self.logger.warning(
                    "pm_engine",
                    f"pm.push.retry_backoff_seconds 含负值 {cfg_backoff}，"
                    "回退默认退避 [300, 900]",
                )
                backoff_seconds = [300, 900]

        attempts = self._get_push_retry_count(spec) + 1
        error_base = f"git push failed ({ref}): {error_msg}"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        if attempts >= max_retries:
            # 超限：发 push_failed 信号，停止自动重试
            detail = (
                f"连续 {attempts} 次推送失败（{ref}），" f"已达上限 {max_retries}，已停止自动重试"
            )
            self._signal_push_failed(spec_name, detail)
            final_error = (
                f"{error_base} [push_attempts={attempts}] " f"[push_failed — 已停止自动重试]"
            )
            # 超限分支文本无退避标记 → 退避截止字段同语义清空
            self.state_machine.update_spec(
                spec_name,
                {
                    "error": final_error,
                    # 字段化双活（code-review item bbba88d8e6af）：重试计数
                    # 同步落专用字段，「清除错误」整段清 error 文本不再归零；
                    # 文本标记保留（展示语义 + 存量读侧回退）。
                    PUSH_ATTEMPTS_FIELD: attempts,
                    PUSH_BACKOFF_NEXT_RETRY_AT_FIELD: None,
                },
            )
            self.logger.error(
                "pm_engine",
                f"Push retries exhausted for '{spec_name}' ({attempts}/{max_retries})",
            )
        else:
            # 退避：延迟到 next_retry_at 再重试
            delay = backoff_seconds[min(attempts - 1, len(backoff_seconds) - 1)]
            next_retry = now_ts + delay
            final_error = (
                f"{error_base} [push_attempts={attempts}] "
                f"[push_backoff next_retry_at={next_retry}]"
            )
            self.state_machine.update_spec(
                spec_name,
                {
                    "error": final_error,
                    # 字段化双活（code-review item bbba88d8e6af）：退避截止
                    # 与重试计数同步落专用字段，「清除错误」整段清 error 文本
                    # 不再连根抹掉 → 退避期/计数归零；文本标记保留（展示
                    # 语义 + 存量读侧回退）。
                    PUSH_ATTEMPTS_FIELD: attempts,
                    PUSH_BACKOFF_NEXT_RETRY_AT_FIELD: next_retry,
                },
            )
            self.logger.warning(
                "pm_engine",
                f"Push failed for '{spec_name}' ({ref}): {error_msg}; "
                f"attempt {attempts}/{max_retries}, next retry at +{delay}s",
            )

    def _push_branch_best_effort(self, spec_name: str, branch: str):
        """尽力推送 feature 分支（D1/D2）：不阻断 pushed 判定。

        - 本地分支不存在 → 跳过（merge-back 已清理，main 承载内容）
        - 远端 SHA 与本地一致 → 去重跳过（已推送）
        - 远端不存在或 SHA 不同 → 尝试推送，失败仅 WARN
        """
        local_sha = self._local_branch_sha(branch)
        if not local_sha:
            self.logger.info(
                "pm_engine",
                f"Local branch '{branch}' missing for '{spec_name}' "
                f"— skipping best-effort push (main carries content)",
            )
            return

        remote_sha = self._remote_branch_sha(f"refs/heads/{branch}")

        # D2: SHA 一致 → 已推送
        if remote_sha and remote_sha == local_sha:
            self.logger.info(
                "pm_engine",
                f"Branch '{branch}' already on remote with same SHA "
                f"({remote_sha[:12]}) — skipping push for '{spec_name}'",
            )
            return

        # D2: 远端存在但 SHA 不同 → 跳过并 WARN
        if remote_sha and remote_sha != local_sha:
            self.logger.warning(
                "pm_engine",
                f"Branch '{branch}' remote SHA ({remote_sha[:12]}) differs "
                f"from local ({local_sha[:12]}) — skipping branch push for "
                f"'{spec_name}' (main carries content)",
            )
            return

        # 远端不存在或查询失败 → 尝试推送
        self.logger.info(
            "pm_engine",
            f"Pushing branch '{branch}' for '{spec_name}' (best-effort)",
        )
        ok, err = self._git_push_ref(branch)
        if not ok:
            self.logger.warning(
                "pm_engine",
                f"Best-effort branch push failed for '{spec_name}' "
                f"(branch={branch}): {err} — main push succeeded",
            )
        else:
            self.logger.info(
                "pm_engine",
                f"Branch push succeeded for '{spec_name}' (branch={branch})",
            )

    def _auto_approve(self, spec_name: str):
        """自动审批：auto 模式下 done → 自动 push → pushed。

        幂等：已 pushed 直接返回 True；退避期内跳过不重试。
        """
        spec = self.state_machine.read_one(spec_name)
        if not spec:
            return False
        status = spec.get("status", "")
        if status == "pushed":
            return True
        if status != "done":
            self.logger.warning(
                "pm_engine",
                f"_auto_approve: '{spec_name}' is '{status}', not done — skipping",
            )
            return False

        # D3: 退避期内跳过（recovery 不重放）
        if self._is_push_backoffed(spec):
            self.logger.info(
                "pm_engine",
                f"_auto_approve: push backoff active for '{spec_name}' — skipping",
            )
            return False

        self.logger.info("pm_engine", f"Auto-approving '{spec_name}' (approve_mode=auto)")
        return self.approve_push(spec_name)

    # ── 残痕回填（design D4）────────────────────────────────────

    def backfill_push_residuals(self) -> dict:
        """幂等回填清理：遍历 pushed 终态且 error 以 'git push failed' 开头的 spec。

        用 D2 的 SHA 比对验证内容已在远端后清 error；验证不到的保留并列日志。
        供手动调用 + tests 覆盖。

        验证口径（design D4）：本地分支仍在时，优先将 spec 自身分支的远端 SHA
        与本地 SHA 做相等比对（内容确定已在远端即清痕）；本地分支已被 merge-back
        清理后无从比对，降级为远端引用存在性检查；仍验证不到时回退比对本地
        main 与远端 main 的 SHA（相等即清痕；取不到本地 main 保守保留残留）。

        Returns:
            {"cleaned": [spec_name, ...], "kept": [{"spec": name, "error": msg}, ...]}
        """
        cleaned = []
        kept = []
        # 与 _resolve_push_branch 同口径：兜底分支名前缀走配置而非硬编码
        prefix = self._get_config("worktree.implement_branch_prefix", "fenix")
        all_specs = self.state_machine.read_all() or {}
        for name, entry in all_specs.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("status") != "pushed":
                continue
            error = str(entry.get("error") or "")
            if not error.startswith("git push failed"):
                continue

            # D2/D4: 优先用 spec 自身分支的 SHA 比对验证内容已在远端。
            # 本地分支仍在时做真实 SHA 相等比对——远端同名引用若停在上次
            # 推送失败残留的旧 SHA，不得误清（code-review item 30039c4e9a5d）；
            # 本地分支已被 merge-back 清理后无从比对，降级为存在性检查。
            branch = entry.get("branch") or f"{prefix}/{name}"
            verified = False
            verify_note = ""
            local_branch = self._local_branch_sha(branch)
            remote_branch = self._remote_branch_sha(f"refs/heads/{branch}")
            if local_branch:
                if remote_branch and remote_branch == local_branch:
                    verified = True
                    verify_note = f"branch SHA match {remote_branch[:12]}"
            elif remote_branch:
                verified = True
                verify_note = f"branch on remote {remote_branch[:12]}"
            else:
                # 回退：本地 main 与远端 main SHA 相等（内容确定已在远端）才
                # 清痕；取不到本地 main 时保守保留残留
                # （code-review item d988f397ed1e）
                local_main = self._local_branch_sha("main")
                remote_main = self._remote_branch_sha("refs/heads/main")
                if local_main and remote_main and remote_main == local_main:
                    verified = True
                    verify_note = f"main SHA match {remote_main[:12]}"

            if verified:
                self.state_machine.update_spec(name, {"error": None})
                cleaned.append(name)
                self.logger.info(
                    "pm_engine",
                    f"Backfill: cleaned push residual for '{name}' "
                    f"(verified on remote: {verify_note})",
                )
            else:
                kept.append({"spec": name, "error": error})
                self.logger.warning(
                    "pm_engine",
                    f"Backfill: cannot verify '{name}' on remote — "
                    f"keeping residual (error: {error[:80]})",
                )

        if kept:
            self.logger.warning(
                "pm_engine",
                f"Backfill: {len(kept)} spec(s) could not be verified remotely: "
                + ", ".join(k["spec"] for k in kept),
            )
        else:
            self.logger.info(
                "pm_engine",
                f"Backfill: {len(cleaned)} spec(s) cleaned, 0 kept",
            )
        return {"cleaned": cleaned, "kept": kept}

    # ── 旧接口保留（向后兼容单分支推送） ─────────────────────────

    def _resolve_push_branch(self, spec_name: str, spec: dict) -> str:
        """解析 SPEC 的推送分支名。

        优先使用 STATE.md 中的 branch 字段；缺失时从本地 refs 解析最近的
        实现分支（worktree 分支名为 {prefix}/{spec_name}-<时间戳后缀>，
        fix-fix-add-dashboard-spec-doc-tabs 前的存量 done SPEC 分支名从未
        写回 STATE，需按 refs 恢复）；仍无则按 {prefix}/{spec_name} 构造。
        """
        branch = spec.get("branch")
        if branch and isinstance(branch, str) and branch.strip():
            return branch.strip()
        prefix = self._get_config("worktree.implement_branch_prefix", "fenix")
        plain = f"{prefix}/{spec_name}"
        try:
            res = subprocess.run(
                [
                    "git",
                    "for-each-ref",
                    "--format=%(refname:short)",
                    "--sort=-committerdate",
                    f"refs/heads/{plain}-*",
                ],
                cwd=str(self.project_root),
                capture_output=True,
                # errors="replace"（code-review item 022c2e4ced2a，与
                # core/regression.py 加固先例同款）：git 输出含非 UTF-8 字节时
                # 严格解码抛 UnicodeDecodeError 逃出宽 except，误判推送/工作树。
                text=True, encoding="utf-8", errors="replace",
                timeout=30,
            )
            if res.returncode == 0:
                sep = plain + "-"
                for cand in res.stdout.splitlines():
                    cand = cand.strip()
                    if cand.startswith(sep) and cand[len(sep) :].isdigit():
                        return cand
        except Exception:
            pass
        return plain

    # ── Helpers ────────────────────────────────────────────────────

    def _append_project_log(self, message: str):
        """Append a timestamped message to PROJECT_LOG.md（.fenix/ 下）."""
        log_path = self.project_root / ".fenix" / "PROJECT_LOG.md"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n- [{timestamp}] {message}")

    def _get_approve_mode(self) -> str:
        """Return the approve_mode, defaulting to 'manual'."""
        from core.config import ConfigLoader

        return ConfigLoader.get_approve_mode(self.config)

    def _get_config(self, key: str, default=None):
        """Get a nested config value."""
        from core.config import ConfigLoader

        return ConfigLoader.get(self.config, key, default)

    # ── 恢复一致性辅助（improve-run-lifecycle-governance D4/D6）──────────────

    def _stuck_elapsed_minutes(self, spec_name: str, now: datetime, updated: datetime) -> float:
        """卡死耗时（分钟）：优先读 agent_runner 的续期基准，回退 STATE updated。

        超时监督续期（improve-run-lifecycle-governance 3.2 / D3）会通过
        ``agent_runner.note_run_extension`` 登记新的 stuck 基准——否则刚被续期
        的长任务因 updated 停留在派发时刻，下一轮 BLOCKER CHECK 就被误判 stuck
        并触发 auto-recovery（绕过整个监督机制）。无注册表条目（未续期 / 接口
        不可用 / run 已结束）时按 updated 计算，行为与现状一致。
        """
        getter = getattr(self.agent_runner, "get_extension_baseline", None)
        if callable(getter):
            try:
                baseline_ts = getter(spec_name)
            except Exception as e:
                self.logger.debug(
                    "pm_engine",
                    f"Extension baseline probe failed for '{spec_name}': {e}",
                )
                baseline_ts = None
            if isinstance(baseline_ts, (int, float)) and baseline_ts > 0:
                try:
                    return (now.timestamp() - float(baseline_ts)) / 60.0
                except (TypeError, ValueError):
                    pass
        return (now - updated).total_seconds() / 60.0

    def _attempt_still_alive(self, spec_name: str) -> bool:
        """核验 spec 是否仍有存活的 attempt 子进程（auto-recovery 前置门禁）。

        优先复用 ``agent_runner.has_live_attempt``（进程表 + 流新鲜度）；接口不可
        用或返回非布尔（如测试替身）时保守按「无存活」处理，保持既有恢复行为。
        """
        checker = getattr(self.agent_runner, "has_live_attempt", None)
        if not callable(checker):
            return False
        try:
            result = checker(spec_name)
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"Live-attempt probe failed for '{spec_name}' " f"(treating as no live child): {e}",
            )
            return False
        return result is True

    def _queued_for_dispatch(self, spec_name: str) -> bool:
        """spec 是否已有待派发条目（假就绪巡检豁免用）。

        「派发活动」的第二个真相源：``_spec_has_recent_run_activity`` 以 run 流
        文件 mtime 为代理，无法看见「已入队、正在等并发槽/优先级窗口」的等待
        ——该窗口由队列老化开窗时序与 ``agents.max_concurrent`` 共同决定，实测
        可达 50 分钟（远长于 20 分钟的巡检阈值），期间该 spec **确实已派发成立**，
        仅尚未起 run。

        与 ``family._sibling_repair_active`` 读队列同范式（同一 ``_queue_lock``
        保护、同一 ``_run_queue`` 元组布局）；异常一律 fail-open 返回 False
        （保持既有上报行为，不因本豁免故障而掩掉真阳性）。

        注意豁免边界：本门只覆盖「排队中」，队列被永久饿死（如高优家族长时间
        占满并行度）仍由既有的「Waiting in ready queue … possible queue
        starvation」警告（阈值 2× stuck）可见——本条豁免不得泛化为「有活跃
        run 就不报」。
        """
        try:
            with self._queue_lock:
                return any(e[1] == spec_name for e in self._run_queue)
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"Queue probe failed for '{spec_name}' (treating as not queued): {e}",
            )
            return False

    def _ready_stall_threshold_minutes(self) -> float:
        """假就绪巡检阈值：pm.recovery.ready_stall_threshold_minutes（默认 20）。"""
        try:
            return max(
                0.0,
                float(
                    self._get_config(
                        "pm.recovery.ready_stall_threshold_minutes",
                        DEFAULT_READY_STALL_THRESHOLD_MINUTES,
                    )
                ),
            )
        except (TypeError, ValueError):
            return float(DEFAULT_READY_STALL_THRESHOLD_MINUTES)

    def _spec_has_recent_run_activity(self, spec_name: str, window_minutes: float) -> bool:
        """窗口内该 spec 是否有任何 run 产物活动（前缀取 RUN_ID_AGENT_PREFIXES 全集）。

        「期间无成功派发」的代理判据：窗口内没有任何 run 流文件被写入即视为
        无派发活动（失败的 run 也算活动——有活动说明调度仍在工作，不是假就绪）。
        """
        runs_dir = self.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return False
        cutoff = time.time() - max(0.0, window_minutes) * 60
        try:
            # 前缀唯一真源（code-review item bc67babca3c5）：直接消费 run_files
            # 的 RUN_ID_AGENT_PREFIXES（前缀自带尾「-」），不再维护本地子集——
            # 新增 agent 类型自动纳入，impl-ocr-<spec>-<ts> 等独立前缀形态的
            # run id 也因此被 glob 覆盖。
            for prefix, _agent_type in RUN_ID_AGENT_PREFIXES:
                for p in runs_dir.glob(f"{prefix}{spec_name}-*.jsonl"):
                    # 精确归属守卫（范式见 recovery.py）：spec 名互为前缀时
                    # glob 命中不得直接认定——fix-x 不得被 fix-x-y 的活动豁免
                    if run_spec_part(p.stem) != spec_name:
                        continue
                    try:
                        if p.stat().st_mtime >= cutoff:
                            return True
                    except OSError:
                        continue
        except OSError:
            return False
        return False

    def _dependencies_satisfied(self, spec_name: str) -> bool:
        """Check if all dependencies of a SPEC are in a terminal complete state."""
        spec = self.state_machine.read_one(spec_name)
        if not spec:
            return True

        deps = spec.get("depends_on")
        # "null" 字面量已在 StateParser.parse 归一为 None
        # （code-review 56f1aefd2823），此处只需判空。
        if not deps:
            return True

        # deps is a comma-separated list of SPEC names
        dep_names = [d.strip() for d in str(deps).split(",") if d.strip()]
        if not dep_names:
            return True

        for dep_name in dep_names:
            dep_spec = self.state_machine.read_one(dep_name)
            if not dep_spec:
                self.logger.warning(
                    "pm_engine", f"Dependency '{dep_name}' not found for '{spec_name}'"
                )
                return False
            dep_status = dep_spec.get("status", "")
            if dep_status not in DEPENDENCY_ACCEPTED_STATUSES:
                self.logger.info(
                    "pm_engine",
                    f"'{spec_name}' blocked: dependency '{dep_name}' is '{dep_status}' (need done/pushed/implemented/verified)",
                )
                return False

        return True

    def _dependencies_pending(self, spec_name: str) -> bool:
        """依赖未满足的静默判定（假就绪巡检豁免用，与 ``_dependencies_satisfied`` 同口径）。

        与 ``_dependencies_satisfied`` 共用同一 ``DEPENDENCY_ACCEPTED_STATUSES``、
        同一 STATE 读取与同一逗号分隔解析；差别只有两点：不打印
        「blocked: dependency ...」日志（巡检每周期调用，重复 INFO 会形成刷屏），
        以及把「依赖缺失」与「依赖未到接受态」统一折叠为 True。

        语义：spec 配置了依赖且至少一个依赖当前不在接受态 → True；依赖条目缺失
        （读不到）同样按未满足处理（与 ``_dependencies_satisfied`` 的 fail-closed
        一致）。无依赖 / ``null`` / 名列表为空 → False（无需等待）。
        """
        spec = self.state_machine.read_one(spec_name) or {}
        deps = spec.get("depends_on")
        # "null" 字面量已在 StateParser.parse 归一为 None
        # （code-review 56f1aefd2823），此处只需判空。
        if not deps:
            return False
        dep_names = [d.strip() for d in str(deps).split(",") if d.strip()]
        if not dep_names:
            return False
        for dep_name in dep_names:
            dep_spec = self.state_machine.read_one(dep_name)
            if not dep_spec:
                return True
            if dep_spec.get("status", "") not in DEPENDENCY_ACCEPTED_STATUSES:
                return True
        return False

    def _wakeup_dependents(self, dep_name: str, dependents: list) -> None:
        """依赖满足定向唤醒（dispatch-dependency-wakeup D1-D3）。

        ``dep_name`` 转入依赖闸门接受态后，EventBus 反查出的等待中 dependents
        逐个重评：复用既有 ``_dependencies_satisfied``（同一接受态集合、同一
        STATE.md 读取口径，不另立判据），通过且处于可派发态（ready）时走与
        ``spec_ready`` **同源**的派发入口 ``_on_spec_ready``——预算/内容完整性/
        冻结/依赖/冷却/去重/优先级/并发闸门全部自动生效，幂等不在唤醒路径上
        重新实现（D3）。全部重评后立即处理派发队列，使「事件到达即唤醒」的
        入队当轮完成，不依赖下一轮 full_scan。

        - 幂等与去重（1.4）：已有活跃派发（worktree 持锁）或已在飞派发
          （``_pending_dispatches``）的 dependent 跳过，不重复入队；
        - 异常隔离（1.5）：单个 dependent 的任一异常捕获降级 WARNING，不中断
          其余 dependent 的重评（沿用 full-scan-resilience 单条隔离口径）。
        """
        if not dependents:
            return  # 无 dependents：零副作用、零日志（1.4）
        self.logger.info(
            "pm_engine",
            f"Dependency wakeup: '{dep_name}' entered accepted status, "
            f"rechecking {len(dependents)} dependent(s)",
        )
        for name in dependents:
            try:
                # 幂等与去重（1.4）：已在飞派发中 → 跳过
                if name in self._pending_dispatches:
                    continue
                # 已有活跃派发（worktree 持锁 / 活 run 占用）→ 跳过，不重复入队
                try:
                    if self.agent_runner.worktree_manager.has_active_worktree(name):
                        continue
                except Exception:
                    pass
                # 仅处于可派发态（ready）的 dependent 值得唤醒；其它状态由
                # 各自事件路径接管（implemented→verifier 等），不在此重复。
                spec = self.state_machine.read_one(name)
                if not spec or spec.get("status") != "ready":
                    continue
                if not self._dependencies_satisfied(name):
                    continue
                # 与 spec_ready 事件同源的派发入口：全部既有闸门在此生效
                self._on_spec_ready(name)
            except Exception as e:
                self.logger.warning(
                    "pm_engine",
                    f"Dependency wakeup failed for dependent '{name}' "
                    f"(dep '{dep_name}'): {type(e).__name__}: {e}",
                )
        # 入队后立即处理队列，使唤醒在事件到达当轮完成派发（对齐
        # check_scheduling_deadlines 的「唤起后立即处理队列」模式）。
        try:
            self._process_queue()
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"Dependency wakeup queue process failed (dep '{dep_name}')"
                f"（非阻塞，full_scan 兜底）: {e}",
            )

    # ── Blocker Detection & Health Reporting ───────────────────────

    def check_blockers(self) -> dict:
        """
        Scan all SPECs for blocking/stuck conditions and generate a health report.
        Called periodically by the EventBus full-scan cycle.

        Returns a dict with blocker details if any found.
        """
        all_specs = self.state_machine.read_all()

        from core.config import ConfigLoader

        stuck_threshold_minutes = ConfigLoader.effective_stuck_threshold_seconds(self.config) / 60.0
        now = datetime.now(timezone.utc)

        # 恢复闭环复查（D6）：到期的观察项先复查——本轮 auto-recovery 是否真的
        # 让 spec 恢复推进；未恢复则发 dispatch_stalled 信号。
        try:
            self.check_recovery_watch()
        except Exception as e:
            self.logger.error("pm_engine", f"Recovery watch check failed: {e}")

        blockers = []
        warnings = []

        for name, entry in all_specs.items():
            # 与 backfill_push_residuals 同款防御（code-review item
            # 60a0039e3313）：STATE 解析异常产出的非 dict 条目直接跳过，
            # 不让 entry.get 抛 AttributeError 中断整轮 blocker 扫描。
            if not isinstance(entry, dict):
                continue
            status = entry.get("status", "drafted")

            # Terminal states — skip
            if status in ("done", "pushed"):
                continue

            # Transient state — verified should auto-transition to done;
            # if stuck here, flag as blocker
            if status == "verified":
                # 必须与其余 blocker 构造点同为 dict：此前 append 字符串导致
                # _write_blocker_report 按 b['spec'] 取值抛 TypeError，
                # 全量扫描中断、auto-recovery 永不执行。
                # code-review item 1d8af1b35663：updated 缺失/非法时无法判定
                # 滞留时长，跳过本轮（与 implementing/testing 分支解析失败静默
                # 跳过同口径），不按 0 分钟照报。
                try:
                    # updated 先 str 归一（code-review item 6e8033e77960，与
                    # error 字段同款）：外部直改的非字符串值直接进 .replace 会
                    # 抛 AttributeError（不在捕获列表内），中断整轮巡检。
                    updated_raw = str(entry.get("updated") or "")
                    u = parse_ts(updated_raw)  # 收拢 parse_ts（SPEC-B 批③）；None 由下方 TypeError 捕获同路 continue
                    v_elapsed = int((now - u).total_seconds() / 60)
                except (ValueError, TypeError):
                    continue
                # fix-verified-gate-evidence-race D3：error 带 task-gap: 前缀的卡
                # verified spec 属「任务缺口待人工裁决」，blocker 条目 reason 改述
                # 为裁决形态并携带缺口摘要（去前缀），供 admin 工作台直接定位；
                # 不得按「瞬态」语义改述（下方案例 4.4 断言依赖此措辞）。
                stored_error = entry.get("error") or "No error recorded"
                if isinstance(stored_error, str) and stored_error.startswith(TASK_GAP_ERROR_PREFIX):
                    gap_summary = stored_error[len(TASK_GAP_ERROR_PREFIX) :].strip()
                    blockers.append(
                        {
                            "spec": name,
                            "status": status,
                            "reason": (f"任务缺口待人工裁决：{gap_summary or '详情见 error 字段'}"),
                            "error": stored_error,
                            "elapsed_minutes": v_elapsed,
                        }
                    )
                    continue
                # code-review item 1d8af1b35663：与 implementing/testing 同口径
                # 的滞留宽限阈值——超 stuck 阈值才列 blocker，避免 verified→
                # done 转移前后瞬态窗口的每轮噪音上报。
                if v_elapsed > stuck_threshold_minutes:
                    blockers.append(
                        {
                            "spec": name,
                            "status": status,
                            "reason": f"卡在 verified 状态 {v_elapsed} 分钟（应为瞬态，需要推进到 done）",
                            "error": stored_error,
                            "elapsed_minutes": v_elapsed,
                        }
                    )
                continue

            # Check if stuck in an active state
            if status in ("implementing", "testing"):
                try:
                    updated_str = str(entry.get("updated") or "")  # str 归一防非串值 AttributeError（item 6e8033e77960）
                    if updated_str:
                        updated = parse_ts(updated_str)  # 收拢 parse_ts（SPEC-B 批③）
                        elapsed = self._stuck_elapsed_minutes(name, now, updated)
                        if elapsed > stuck_threshold_minutes:
                            blockers.append(
                                {
                                    "spec": name,
                                    "status": status,
                                    "reason": f"Stuck in '{status}' for {int(elapsed)} minutes (threshold: {stuck_threshold_minutes}m)",
                                    "error": entry.get("error") or "No error recorded",
                                    "elapsed_minutes": int(elapsed),
                                }
                            )
                except (ValueError, TypeError):
                    pass

            # Check for persistent errors
            # 与 backfill_push_residuals 同款 str 归一（code-review item
            # 4f927e30d717）：STATE 解析异常可产出非字符串且为真的 error，
            # 直接下标切片会抛 TypeError 中断整轮 blocker 扫描。
            error = str(entry.get("error") or "")
            if error and status == "ready":
                try:
                    retries = int(entry.get("_retry_count", 0) or 0)
                except (TypeError, ValueError):
                    retries = 0
                if retries > 0:
                    warnings.append(
                        {
                            "spec": name,
                            "status": status,
                            "reason": f"Failed {retries} retry attempts, last error: {error[:100]}",
                        }
                    )

            # Check for ready-but-starving (never been picked up)
            if status == "ready":
                try:
                    updated_str = str(entry.get("updated") or "")  # str 归一防非串值 AttributeError（item 6e8033e77960）
                    if updated_str:
                        updated = parse_ts(updated_str)  # 收拢 parse_ts（SPEC-B 批③）
                        elapsed = (now - updated).total_seconds() / 60
                        if elapsed > stuck_threshold_minutes * 2:
                            warnings.append(
                                {
                                    "spec": name,
                                    "status": status,
                                    "reason": f"Waiting in ready queue for {int(elapsed)} minutes — possible queue starvation",
                                    "elapsed_minutes": int(elapsed),
                                }
                            )
                        # 假就绪巡检（improve-run-lifecycle-governance D6）：ready 滞留
                        # 超过 ready_stall_threshold_minutes 且期间无派发活动 → 阻塞项。
                        # 退避期内的 spec（_dispatch_backoff_until 未到期）有意等待，不算滞留。
                        # start_after 定时拾取门未到期的 spec 同样是有意等待
                        # （scheduled-spec-pickup）：daemon 每轮正确 skip 派发
                        # （start_after pending），巡检不得把它误报为假就绪滞留
                        # （2026-09-11 add-main-tree-deps-provision 实证）。
                        # 依赖未满足的 spec 同理（dispatch-dependency-wakeup）：daemon
                        # 每轮 dispatch 已按 _dependencies_satisfied 正确 skip，等待
                        # 依赖转入接受态由事件定向唤醒（_wakeup_dependents），不依赖
                        # 巡检告警——等待中的依赖既不会因告警提前满足，也不会因告警被
                        # 重新派发，误报只会唤起无效 Administrator run。
                        # （2026-09-17 refactor-facade-delegation 实证：依赖两条 refactor
                        # 活 run 在跑、spec 从未获得过 worktree 锁，却被固定文案信号误述
                        # 为「worktree 锁冲突 / 退避计划耗尽」。）
                        # 存活 attempt 亦不算（与 D4 auto-recovery 的 live-child 豁免同语义）：
                        # daemon 重启后 recovery 把 implementing 恢复为 ready，而旧 run 的
                        # 流写侧已随旧进程死亡——「流 mtime = 派发活动」代理判据失真，
                        # 不豁免会把「活 run 被重建锁保护、恢复检查正确 skip」的 spec
                        # 误报为 dispatch_stalled 循环呼叫 Administrator（2026-09-06
                        # add-verify-multi-kind-runner 事故）。
                        # 已在派发队列中等待的 spec 同理（dispatch-queue-aging 时序）：
                        # 入队已成立（_on_spec_ready 返回 True），只是受并发槽与优先级
                        # 窗口约束尚未起 run；老化开窗最坏要 initial+floor×step 分钟
                        # （本项目配置 10+4×10 = 50 分钟），远长于 20 分钟阈值，期间
                        # 流文件判据恒为假 → 每轮巡检必报。2026-09-17 实证：8 条
                        # start_after 18:00 到点的 P5 spec 入队后 50.4 分钟才获派发，
                        # 18:25 巡检即把这批**已入队**的 spec 判为假就绪滞留并唤起
                        # Administrator；其中两条（evo-sigterm-source-tracking-cooldown
                        # / evo-supervision-timeout-config-consistency）在 18:50:59
                        # 派发成立，证明派发链路健康，告警纯属观测盲区。
                        # 队列被真正饿死（无并发窗口）仍由既有「Waiting in ready queue」
                        # 警告（阈值 2×stuck）可见，本豁免不掩盖饿死形态。
                        stall_threshold = self._ready_stall_threshold_minutes()
                        if (
                            elapsed > stall_threshold
                            and not self._dispatch_backoffed(entry)
                            and not start_after_pending(entry)
                            and not self._dependencies_pending(name)
                            and not self._spec_has_recent_run_activity(name, stall_threshold)
                            and not self._attempt_still_alive(name)
                            and not self._queued_for_dispatch(name)
                        ):
                            blockers.append(
                                {
                                    "spec": name,
                                    "status": status,
                                    "reason": (
                                        f"假就绪滞留：ready 超过 {int(elapsed)} 分钟且期间无"
                                        f"派发活动（阈值 {stall_threshold:.0f}m）"
                                    ),
                                    "error": entry.get("error") or "No error recorded",
                                    "elapsed_minutes": int(elapsed),
                                }
                            )
                except (ValueError, TypeError):
                    pass

        # Log and auto-recover
        # warning-only 轮次同样落 WARNING（code-review item 11f659e8a71a）：
        # 队列饥饿形态 blockers 为空而 warnings 非空，若整段日志被 `if blockers:`
        # 门住，本轮 warning 每轮算出、每轮丢弃，上方注释承诺的「Waiting in
        # ready queue … possible queue starvation」（阈值 2×stuck）饿死观测
        # 通道失效。报告仍仅在有 blocker 时落（报告以 blockers 为主结构）。
        if blockers or warnings:
            self.logger.warning(
                "pm_engine",
                f"BLOCKER CHECK: {len(blockers)} blocking, {len(warnings)} warnings",
                {"blockers": blockers, "warnings": warnings},
            )
        if blockers:
            self._write_blocker_report(blockers, warnings)

            # Auto-recovery: reset stuck SPECs to previous state so they get retried
            for b in blockers:
                spec_name = b["spec"]
                stuck_status = b["status"]
                if stuck_status == "ready":
                    # 假就绪滞留（D6）：不重置状态（本就 ready），上报信号唤醒处置。
                    self._signal_dispatch_stalled(
                        spec_name,
                        f"ready stall {b['elapsed_minutes']}m without dispatch activity; "
                        f"error={str(b.get('error') or '')[:120]}",
                    )
                    continue
                # ── 恢复一致性（improve-run-lifecycle-governance D4）：重置前必须
                # 核验该 spec 是否仍有存活的 attempt 子进程。存活则跳过本次恢复并
                # 保留全部跟踪字段——2026-08-27 事故：BLOCKER CHECK 对仍有存活
                # resume 子进程的 spec 执行 auto-recovery，把 spec 重置为 ready 并
                # 清空跟踪，与真实运行态失配后卡死近 1 小时。
                if self._attempt_still_alive(spec_name):
                    self.logger.warning(
                        "pm_engine",
                        f"recovery deferred, live child present: '{spec_name}' "
                        f"(was {stuck_status}, {b['elapsed_minutes']} min) — "
                        f"tracking fields preserved",
                    )
                    # defer 也登记观察项：子进程意外长寿/僵死时由闭环复查接管，
                    # 不进入「每轮 defer」死循环。
                    self.register_recovery_watch(
                        spec_name, "auto-recovery deferred (live child present)"
                    )
                    continue
                # fix-verified-gate-evidence-race D3：task-gap 前缀的 blocker 是
                # 门禁结论（任务缺口待人工裁决），recovery 不得触发 auto-recover
                # 状态突变——缺口不因恢复而消失，恢复只会造成状态机扰动。持续列
                # 入 blocker 清单即告警通道；人工补勾后由 event_bus re-trigger
                # 门禁放行（确定性重评，幂等）。
                if isinstance(b.get("error"), str) and b.get("error").startswith(
                    TASK_GAP_ERROR_PREFIX
                ):
                    self.logger.info(
                        "pm_engine",
                        f"task-gap blocker，不 auto-recover：'{spec_name}' "
                        f"(reason={b.get('reason')})",
                    )
                    continue
                if stuck_status == "implementing":
                    # 写前重读复核（code-review item 313f93a4c7c1，对齐
                    # check_scheduling_deadlines 定时解冻「竞争后到者视为无需
                    # 操作」的幂等先例）：轮首快照到本分支之间隔着逐 spec 文件
                    # 系统探针（_attempt_still_alive 等），窗口内该 run 可能已
                    # 合法收工完成 implementing→implemented 转移，盲写会把合法
                    # 进度覆写回 ready 并孤儿化 run 结果——状态不再是卡死态即
                    # 跳过本轮恢复（含下方的预算豁免，均以复核确认为前提）。
                    fresh = self.state_machine.read_one(spec_name) or {}
                    if fresh.get("status") != "implementing":
                        self.logger.info(
                            "pm_engine",
                            f"auto-recovery 竞争后到者：'{spec_name}' 状态已为 "
                            f"'{fresh.get('status')}'，跳过本轮恢复",
                        )
                        continue
                    self.logger.info(
                        "pm_engine",
                        f"Auto-recovering stuck SPEC: {spec_name} (was {stuck_status})",
                    )
                    # 实现卡住且可能从未运行（implementer_run=null）：不得伪标 implemented
                    # 直接推给 verifier——「无实现即验证」会产出伪 bug 并派生 fix 级联
                    # （本事故 5 代 fix 链的肇因）。回 ready 重新排队实现器。
                    # 死亡 run 豁免（fix-budget-counting-semantics D1）：恢复链路在此
                    # 确认 run 异常死亡（滞留 implementing 超阈值且无存活子进程＝无收工
                    # 结果产出），回退本次启动的预算计数并递增豁免侧车。
                    # fix-run-hang-amplification D2：run_reason 传入豁免判据，
                    # 此路径为基础设施性死亡（无存活子进程/无 run-result），应豁免。
                    self._exempt_dead_run_budget(
                        spec_name,
                        f"auto-recovery: stuck implementing "
                        f"{b['elapsed_minutes']}m, no live child (no run-result)",
                        run_reason=f"auto-recovery: stuck implementing " f"{b['elapsed_minutes']}m",
                    )
                    self.logger.info(
                        "pm_engine",
                        f"budget_exempt_audit: spec={spec_name}, "
                        f"auto-recovery stuck implementing, "
                        f"elapsed_minutes={b['elapsed_minutes']}",
                    )
                    # （fix-fasttrack-recovery-resume D5 区分注释）本处清锚点属**有意
                    # 重置**——判据已确认「滞留 implementing 超阈值且无存活子进程」
                    # （上方 _attempt_still_alive 已核验）即 run 已死，拉回 ready 全新
                    # 派发。MUST NOT 消费 `_recovery_resume`：它不由本路径产出，且此时
                    # 不存在可续做的在飞 run——消费会使随后的正常派发失去续做判定资格。
                    self.state_machine.update_spec(
                        spec_name,
                        {
                            "status": "ready",
                            "implementer_run": None,
                            "tester_run": None,
                            "branch": None,
                            "error": f"Auto-recovered from stuck implementing ({b['elapsed_minutes']} min)",
                        },
                    )
                    # add-fast-track-mode（task 3.1）：实现态恢复按 mode 派发对应 agent
                    from core.spec_mode import read_spec_mode

                    _at = (
                        "fast-track"
                        if read_spec_mode(self.project_root, spec_name) == "fast-track"
                        else "implementer"
                    )
                    self._enqueue(spec_name, _at)
                    self.register_recovery_watch(
                        spec_name, f"auto-recovered from stuck {stuck_status}"
                    )
                elif stuck_status == "testing":
                    # 写前重读复核（code-review item 313f93a4c7c1，与上方
                    # implementing 分支及 check_scheduling_deadlines 定时解冻
                    # 先例同口径）：状态已不是 testing（如 verifier 竞争收工）
                    # 即跳过本轮恢复，防盲写覆写合法进度。
                    fresh = self.state_machine.read_one(spec_name) or {}
                    if fresh.get("status") != "testing":
                        self.logger.info(
                            "pm_engine",
                            f"auto-recovery 竞争后到者：'{spec_name}' 状态已为 "
                            f"'{fresh.get('status')}'，跳过本轮恢复",
                        )
                        continue
                    # [fenix-ignore:b33341a8f31b] 问题已修复（commit bffc1407）：下方已按 is_fast_track 分流短路，fast-track spec 走 _fasttrack_recovery_reentry 恢复收尾、不再回 implemented+入队 verifier，当前树问题不成立
                    # code-review item b33341a8f31b：fast-track 分流——单 run 全包
                    # 不设 verifier 车道（与 _on_spec_implemented 同一防线，
                    # fasttrack-orphan-planner-race），回 implemented + 入队
                    # verifier 会与 _fast_track_advance_to_verified 竞态、对已终态
                    # spec 派出孤儿 planner run 白跑。走恢复重入收尾（testing 搁浅
                    # 形态由 _fasttrack_recovery_reentry 判定并分派
                    # _resume_fast_track_after_restart(already_testing=True)）；其
                    # 三条件不全成立时维持短路（宁紧勿松），不得落入下方 verifier
                    # 车道，留痕待下轮复查重评。
                    from core.spec_mode import is_fast_track

                    if is_fast_track(self.project_root, spec_name):
                        if self._fasttrack_recovery_reentry(spec_name):
                            self.register_recovery_watch(
                                spec_name, f"auto-recovered from stuck {stuck_status}"
                            )
                        else:
                            self.logger.info(
                                "pm_engine",
                                f"testing 卡死恢复跳过（fast-track 无 verifier 车道）:"
                                f" '{spec_name}' ({b['elapsed_minutes']} min) — "
                                f"恢复重入判据不全成立，维持短路待下轮复查",
                            )
                        continue
                    # code-review item 54075e1dda03：ocr join 停等豁免——fresh
                    # （上方写前重读快照，item 923637148926：轮首 entry 快照
                    # 可能滞后于标记落盘致豁免判据为假、误走重置）带
                    # ``_ocr_join_wait`` 且 ocr 车道在飞（``ocr_lane_busy``）时，
                    # spec 处于 queue._ocr_join_await_lane 承诺的「MUST 停止推进
                    # （tester 不重派）」停等态，此处 reset implemented+重派
                    # verifier 会打断该契约（唤醒回调 _on_impl_ocr_lane_finished
                    # 见状态非 testing 即幂等空转，损失整轮重验证），跳过本轮
                    # 恢复、留痕待车道完成回调唤醒 join 重评（与
                    # _fasttrack_recovery_reentry / admin_monitor 孤儿探针把
                    # _ocr_join_wait 当合法等待判据同口径）。
                    # 豁免 MUST 以车道在飞为条件而非停等标记单边：daemon 重启后
                    # 在飞登记（_ocr_lane_inflight）即丢、车道线程已死，停等标记
                    # 无 boot 恢复路径——标记单边豁免会把这类 spec 永久钉在
                    # testing。ocr_lane_busy 判定异常按在飞处理（宁紧勿松）。
                    # 本豁免的安全性依赖如下隐式阈值序（特此声明，无处校验）：
                    # 车道硬超时 verify.impl_code_review_lane_timeout_sec（缺省
                    # 2400s，ConfigLoader.get_impl_code_review_lane_timeout_sec）
                    # MUST < stuck 阈值 effective_stuck_threshold_seconds（=
                    # agents.run_timeout_seconds+600s，回退 9600s）——车道先于本
                    # 分支阈值超时收尾并触发回调/停等清账；运行方若把车道超时配到
                    # ≥ stuck 阈值，停等 spec 会在超阈值后被本分支每轮 defer，
                    # 直到车道硬超时兜底为止。
                    if fresh.get("_ocr_join_wait"):
                        try:
                            _lane_busy = self.ocr_lane_busy(spec_name)
                        except Exception:  # noqa: BLE001 — 判定异常按在飞（宁紧勿松）
                            _lane_busy = True
                        if _lane_busy:
                            self.logger.info(
                                "pm_engine",
                                f"testing 卡死恢复豁免（ocr join 停等中）: "
                                f"'{spec_name}' ({b['elapsed_minutes']} min) — "
                                f"车道在飞，待完成回调唤醒 join 重评",
                            )
                            continue
                    self.logger.info(
                        "pm_engine",
                        f"Auto-recovering stuck SPEC: {spec_name} (was {stuck_status})",
                    )
                    # 验证卡住：实现已完成，回 implemented 重新派发 verifier
                    self.state_machine.update_spec(
                        spec_name,
                        {
                            "status": "implemented",
                            "tester_run": None,
                            "error": f"Auto-recovered from stuck testing ({b['elapsed_minutes']} min)",
                        },
                    )
                    self._enqueue(spec_name, "verifier")
                    self.register_recovery_watch(
                        spec_name, f"auto-recovered from stuck {stuck_status}"
                    )
                elif stuck_status == "verified":
                    # verified：full_scan 已周期性重触发 spec_verified 走放行门禁
                    # 幂等重试；此处不得回滚到 implemented —— 否则每轮全量重跑
                    # verifier，形成验证烧钱循环。仅上报，等门禁条件满足。
                    self.logger.info(
                        "pm_engine",
                        f"verified 卡死仅上报不恢复：'{spec_name}' "
                        f"({b['elapsed_minutes']} min) — 等 spec_verified 门禁重触发放行",
                    )

        return {"blockers": blockers, "warnings": warnings, "checked_at": now.isoformat()}

    def _write_blocker_report(self, blockers: list, warnings: list):
        """Write a blocker report to PROJECT_LOG.md, throttled to once per hour."""
        now = datetime.now(timezone.utc)

        # Throttle: don't write more than once per hour
        if self._last_blocker_report_time:
            elapsed = (now - self._last_blocker_report_time).total_seconds()
            if elapsed < 3600:
                return

        lines = [
            f"\n### ⚠️ Blocker Report — {now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
        ]

        if blockers:
            lines.append(f"**{len(blockers)} blocker(s) detected:**")
            lines.append("")
            for b in blockers:
                lines.append(f"- 🔴 **{b['spec']}**: {b['reason']}")
                lines.append(
                    f"  - Status: `{b['status']}`, Elapsed: {b['elapsed_minutes']} minutes"
                )
                # str 归一后再切片（code-review item 4f927e30d717）：blocker
                # 条目的 error 可能是 STATE 解析异常产出的非字符串值。
                lines.append(f"  - Last error: {str(b['error'] or '')[:120]}")
                lines.append("")

        if warnings:
            lines.append(f"**{len(warnings)} warning(s):**")
            lines.append("")
            for w in warnings:
                lines.append(f"- 🟡 **{w['spec']}**: {w['reason']}")
                lines.append("")

        if not blockers and not warnings:
            lines.append("✅ No blockers detected. All SPECs progressing normally.")
            lines.append("")

        lines.append(
            f"*Next check: ~{self._get_config('schedule.poll_interval_minutes', 30)} minutes*"
        )
        lines.append("")

        # Append to project log
        # （b21d8f2d8247）报告可丢，恢复链路不可断：.fenix 不可写/磁盘满时写
        # PROJECT_LOG 失败不得向 check_blockers 传播中断本轮全部 auto-recovery
        # （与 _signal_push_failed 的异常包裹同口径），降级 WARNING。
        log_path = self.project_root / ".fenix" / "PROJECT_LOG.md"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError as e:
            self.logger.warning(
                "pm_engine",
                f"Blocker report write to PROJECT_LOG.md failed "
                f"(auto-recovery loop unaffected; 节流窗口未消耗，"
                f"下一轮立即重试报告): {e}",
            )
            return

        # 节流时间戳写盘成功后才消耗（code-review item e7c4e355a4a2）：写失败
        # 不占用 1 小时节流窗口，避免瞬态故障恢复后报告通道空窗到节流过期。
        self._last_blocker_report_time = now
        self.logger.info("pm_engine", "Blocker report written to PROJECT_LOG.md")

    def get_health_summary(self) -> str:
        """Return a human-readable one-line health summary for /fenix-status."""
        all_specs = self.state_machine.read_all()
        if not all_specs:
            return "📋 尚无 SPEC"

        # 与 check_blockers 同款防御（code-review item 0796da56864e）：
        # STATE 解析异常产出的非 dict 条目直接过滤，不让 e.get 抛
        # AttributeError 使 /fenix-status 健康摘要整体不可用。
        all_specs = {k: v for k, v in all_specs.items() if isinstance(v, dict)}

        total = len(all_specs)
        done = sum(1 for e in all_specs.values() if e.get("status") in ("done", "pushed"))
        active = sum(
            1 for e in all_specs.values() if e.get("status") in ("implementing", "testing")
        )
        blocked = sum(
            1 for e in all_specs.values() if e.get("status") == "ready" and e.get("error")
        )

        parts = [f"📦 {total} 个 SPEC"]
        if done:
            parts.append(f"✅ {done} 完成")
        if active:
            parts.append(f"🔨 {active} 进行中")
        if blocked:
            parts.append(f"⚠️ {blocked} 阻塞")

        return " | ".join(parts)

    # ── 组合组件（refactor-core-packages 阶段 4）────────────────────────

    @property
    def _family(self) -> FamilyGovernor:
        """组合组件（refactor-core-packages 阶段 4）：FamilyGovernor。

        惰性构造：测试以 ``PMEngine.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_family_instance")
        if inst is None:
            inst = FamilyGovernor(self)
            self.__dict__["_family_instance"] = inst
        return inst

    @property
    def _budget(self) -> ImplBudget:
        """组合组件（refactor-core-packages 阶段 4）：ImplBudget。

        惰性构造：测试以 ``PMEngine.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_budget_instance")
        if inst is None:
            inst = ImplBudget(self)
            self.__dict__["_budget_instance"] = inst
        return inst

    @property
    def _spec_integrity(self) -> SpecIntegrityGate:
        """组合组件（add-spec-content-integrity-gate D5）：SpecIntegrityGate。

        惰性构造：测试以 ``PMEngine.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_spec_integrity_instance")
        if inst is None:
            inst = SpecIntegrityGate(self)
            self.__dict__["_spec_integrity_instance"] = inst
        return inst

    # ── 组合组件委托（阶段 4：family/budget 已迁组件，门面保持调用路径）──

    _fix_prefix_depth = staticmethod(FamilyGovernor._fix_prefix_depth)

    _fix_strip_all = staticmethod(FamilyGovernor._fix_strip_all)

    _is_fix_spec = staticmethod(FamilyGovernor._is_fix_spec)

    _same_root = staticmethod(FamilyGovernor._same_root)

    # ── infra 熔断告警（evo-run-failure-classification-circuitbreaker D3）──────────
    def _emit_infra_breaker_event(
        self,
        event: str,
        spec_name: str,
        reason: str,
        state: dict,
    ):
        """落 run_infra_failure 告警记录（evo-run-failure-classification-circuitbreaker D3）。

        event:
          - "triggered"：熔断触发 → kind=ESCALATION（critical，attach_trigger，
            不唤起 Administrator——评审链路 infra 对 admin 无杠杆，唤起即烧 token
            空转），**恰好落一条**（触发由 record_failure 返回 True 门控）。
          - "recovered"：冷却到期自动恢复 → kind=SIGNAL（供审计；spec=None
            为链路级恢复，不绑定特定 spec）。

        evidence 含链路/指纹/次数/时间窗（汇总口径）。
        """
        from core.admin_store import AdminStore, ESCALATION, SIGNAL
        from core.alert_lifecycle import attach_trigger

        # 告警落盘整体 fail-open（code-review item 41e2ac64d94a，对齐
        # _signal_push_failed / _write_blocker_report 的包裹手法）：AdminStore
        # 构造与 store.append 此前完全裸奔，磁盘满/权限等 OSError 会从 recovered
        # 分支穿透 _on_spec_reviewing 与 handle_event（handler 调用无 except）
        # 炸到 EventBus 调用方，中断当轮评审入队——报告可丢，主链不可断
        # （b21d8f2d8247 同口径）。
        try:
            store = AdminStore(self.project_root, self.logger)
            count = int(state.get("count", 0)) if state else 0
            # 冷却总时长（秒→分钟，取整）
            # 配置非法值防御（code-review item e3e50d960b1b，与 _handle_push_failure
            # 的 max_retries 同款）：非数字字符串裸 int() 抛 ValueError/TypeError，
            # 从 recovered 分支穿透 handle_event 炸到调用方，中断当轮事件处理且
            # 每次冷却到期复现——回退默认值 30。
            try:
                raw_cooldown = self._get_config(
                    "admin.run_infra_breaker.cooldown_minutes", 30
                )
                # 显式判 None（code-review item 95c429d664e3）：`or 30` 会把
                # 合法的 cooldown_minutes=0（不冷却）吞成默认 30，仅缺省才回退。
                cooldown_minutes = 30 if raw_cooldown is None else int(raw_cooldown)
            # 补捕 OverflowError（code-review item e09138583cd4）：.inf 配置
            # int() 抛 OverflowError 不在原元组，异常从 recovered 分支穿透
            # _on_spec_reviewing 中断当轮评审入队（infra_breaker 先例同口径）。
            except (TypeError, ValueError, OverflowError):
                cooldown_minutes = 30
            now_epoch = time.time()
            window_str = f"{count} 次连续 infra 失败；冷却 {cooldown_minutes} 分钟"
            evidence = (
                f"link=spec-review; count={count}; cooldown={cooldown_minutes}min; " f"{window_str}"
            )
            if event == "triggered":
                entry = {
                    "kind": ESCALATION,
                    "signal_type": "run_infra_failure",
                    "spec": spec_name,
                    "severity": "critical",
                    "description": (
                        f"spec-review 链路连续 infra 失败 {count} 次（阈值 {self._get_config('admin.run_infra_breaker.threshold', 3)}），"
                        f"已触发熔断（冷却 {cooldown_minutes} 分钟）。"
                        f"原因：{reason}"
                    ),
                    "evidence": evidence,
                    "recommended_action": (
                        "冷却到期后自动恢复重试。若持续失败请检查 provider 配额/余额、"
                        "模型链配置与 run_timeout 设置"
                    ),
                }
                attach_trigger(entry)
                # append 返回值必须接收（code-review item 372d1c5a3735，对齐
                # item 2570ca391771 契约）：下限保护拒写时返回 None、记录未落盘，
                # 不得照记成功日志误导事后对账。
                written = store.append(entry)
                if written is not None:
                    self.logger.warning(
                        "pm_engine",
                        f"run_infra_failure triggered: spec={spec_name} count={count}",
                    )
                else:
                    self.logger.warning(
                        "pm_engine",
                        f"run_infra_failure triggered 告警未落盘（下限保护拒写）: "
                        f"spec={spec_name} count={count}",
                    )
            else:
                # recovered：落 SIGNAL 档（链路级恢复，不绑定 spec）
                entry = {
                    "kind": SIGNAL,
                    "signal_type": "run_infra_failure",
                    "spec": None,
                    "severity": "critical",
                    "description": (
                        f"spec-review 链路 infra 熔断冷却到期，已自动恢复重试"
                        f"（冷却前连续失败 {count} 次）"
                    ),
                    "evidence": evidence,
                    "recommended_action": "后续若再次连续 infra 失败将重新熔断",
                }
                # add-alert-self-heal-marking 4.1：triggered 分支已埋点，
                # recovered SIGNAL 档补齐同一埋点（自愈族在册类型）
                attach_trigger(entry)
                written = store.append(entry)
                if written is not None:
                    self.logger.info(
                        "pm_engine",
                        f"run_infra_failure recovered: link=spec-review count={count}",
                    )
                else:
                    self.logger.warning(
                        "pm_engine",
                        f"run_infra_failure recovered 告警未落盘（下限保护拒写）: "
                        f"link=spec-review count={count}",
                    )
        except Exception as e:
            # 告警写失败降级 WARNING 不中断当轮事件处理（熔断判定/评审入队主链
            # 不受影响，报告可丢）
            self.logger.warning(
                "pm_engine",
                f"run_infra_failure 告警写入失败（熔断主链不受影响）: {e}",
            )

    # ── 实现尝试总预算（add-fail-counter-budget D2/D4 / add-spec-status-modal-budget D3）──────────────

    def reclassify_infra_rounds(
        self, spec_name: str, n: int, audit_reason: str, actor: str = "admin"
    ) -> dict:
        """admin 回拨 infra 误计入轮次（evo-infra-failure-budget-exempt R3）。

        核心实现见 verification.reclassify_infra_rounds（原子改写
        _verify_fail_rounds = max(0, current-n) + 解冻 + 审计留痕，幂等）。
        dashboard/CLI/admin_monitor 入口统一委托本方法。
        """
        from core.pm_engine.verification import reclassify_infra_rounds as _recl

        return _recl(
            self.project_root,
            self.state_machine,
            self.logger,
            spec_name,
            n,
            audit_reason,
            actor=actor,
        )

    _run_file_died = staticmethod(ImplBudget._run_file_died)

    # ── 组合组件（refactor-core-packages 阶段 5）────────────────────────

    @property
    def _verification(self) -> VerificationPipeline:
        """组合组件（refactor-core-packages 阶段 5）：VerificationPipeline。

        惰性构造：测试以 ``PMEngine.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_verification_instance")
        if inst is None:
            inst = VerificationPipeline(self)
            self.__dict__["_verification_instance"] = inst
        return inst

    # ── 组合组件委托（阶段 5：验证域已迁组件，门面保持调用路径）──────────

    # 链式别名（design D7 链式依赖）：目标为 VerificationPipeline 同名的类级别名，
    # MUST 显式写全限定，指向收敛后仍存在的 pipeline 类属性（非被删转发）。
    _normalize_fail_signature = staticmethod(VerificationPipeline._normalize_fail_signature)

    # ── 失败历史侧车门面（fix-verdict-retry-misattribution D6 + R3）──

    @property
    def _last_scenario_diff(self):
        return self._verification._last_scenario_diff

    @_last_scenario_diff.setter
    def _last_scenario_diff(self, value):
        self._verification._last_scenario_diff = value

    @_last_scenario_diff.deleter
    def _last_scenario_diff(self):
        del self._verification._last_scenario_diff

    @property
    def _last_interaction_contract(self):
        return self._verification._last_interaction_contract

    @_last_interaction_contract.setter
    def _last_interaction_contract(self, value):
        self._verification._last_interaction_contract = value

    @_last_interaction_contract.deleter
    def _last_interaction_contract(self):
        del self._verification._last_interaction_contract

    # ── 组合组件（refactor-core-packages 阶段 6）────────────────────────

    @property
    def _dispatcher(self) -> Dispatcher:
        """组合组件（refactor-core-packages 阶段 6）：Dispatcher。

        惰性构造：测试以 ``PMEngine.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_dispatcher_instance")
        if inst is None:
            inst = Dispatcher(self)
            self.__dict__["_dispatcher_instance"] = inst
        return inst

    @property
    def _recovery(self) -> RecoveryWatch:
        """组合组件（refactor-core-packages 阶段 6）：RecoveryWatch。

        惰性构造：测试以 ``PMEngine.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_recovery_instance")
        if inst is None:
            inst = RecoveryWatch(self)
            self.__dict__["_recovery_instance"] = inst
        return inst

    @property
    def _reporting(self) -> ReportBuilder:
        """组合组件（refactor-core-packages 阶段 6）：ReportBuilder。

        惰性构造：测试以 ``PMEngine.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_reporting_instance")
        if inst is None:
            inst = ReportBuilder(self)
            self.__dict__["_reporting_instance"] = inst
        return inst

    # ── 组合组件委托（阶段 6：dispatch/recovery/reporting 已迁组件）──────

    _dispatch_backoffed = staticmethod(Dispatcher._dispatch_backoffed)

    def _instant_fail_cooled(self, spec_name: str) -> bool:
        """秒挂冷却判定（cli-retry-backoff 2.2）：冷却期内跳过派发。

        委托到 agent_runner.is_instant_fail_cooldown；runner 不可用或判定异常时
        fail-open（返回 False，不阻塞派发），保证冷却机制故障不放大为调度故障。
        """
        runner = getattr(self, "agent_runner", None)
        checker = getattr(runner, "is_instant_fail_cooldown", None)
        if not callable(checker):
            return False
        try:
            return checker(spec_name) is True
        except Exception:
            return False

    def _signal_kill_cooled(self, spec_name: str) -> bool:
        """信号死法冷却判定（evo-sigterm-source-tracking-cooldown）：冷却期内跳过该 spec 重派。

        与 _instant_fail_cooled 同构（fail-open）；覆盖 admin/impl 处置 run 路由
        ——冷却只作用于该 spec 的重派，MUST NOT 触发全局瞬断熔断。
        """
        runner = getattr(self, "agent_runner", None)
        checker = getattr(runner, "is_signal_kill_cooldown", None)
        if not callable(checker):
            return False
        try:
            return checker(spec_name) is True
        except Exception:
            return False

    def _signal_kill_cooldown_until(self, spec_name: str) -> float:
        """返回 spec 的信号死法冷却到期单调秒（未冷却/无条目返回 0）。

        委托到 agent_runner.signal_kill_cooldown_until；runner 不可用或判定
        异常时 fail-open（返回 0，不排程恢复定时器）。
        """
        runner = getattr(self, "agent_runner", None)
        m = getattr(runner, "signal_kill_cooldown_until", None)
        if not callable(m):
            return 0.0
        try:
            return float(m(spec_name))
        except Exception:
            return 0.0

    def _global_transient_break_active(self) -> bool:
        """全局瞬断熔断判定（fix-provider-transient-backoff D4）：熔断期冻结全部新派发。

        委托到 agent_runner.is_global_transient_break_active；runner 不可用或判定
        异常时 fail-open（返回 False，不阻塞派发），保证熔断机制故障不放大为
        调度故障（与 _instant_fail_cooled 同构）。
        """
        runner = getattr(self, "agent_runner", None)
        checker = getattr(runner, "is_global_transient_break_active", None)
        if not callable(checker):
            return False
        try:
            return checker() is True
        except Exception:
            return False

    def _transient_unseal_gate(self) -> str:
        """解封节奏闸态（evo-fix-transient-break-unseal-backoff 1.2）：首道闸态序单点。

        态序 冻结 > post-unseal hold > 探针观察窗 > 错峰放行（短路顺序即优先级，
        见 ProviderCircuit.transient_unseal_gate）。runner 不可用或判定异常时
        fail-open 返回 "open"（节奏机制故障不放大为调度故障，与
        _global_transient_break_active 同构）。
        """
        runner = getattr(self, "agent_runner", None)
        gate = getattr(runner, "transient_unseal_gate", None)
        if not callable(gate):
            return "open"
        try:
            return str(gate()) or "open"
        except Exception:
            return "open"

    def _transient_unseal_admit(self) -> bool:
        """解封节奏单条派发准入（探针单条 / 错峰节拍）。fail-open 放行。"""
        runner = getattr(self, "agent_runner", None)
        admit = getattr(runner, "admit_unseal_dispatch", None)
        if not callable(admit):
            return True
        try:
            return admit() is not False
        except Exception:
            return True

    def _transient_unseal_recredit(self) -> None:
        """解封节奏准入退还（pop 后闸门回滚条目、零 run 启动时，code-review
        item d2e6133109ff）。runner 不可用或异常静默——退还失败不放大为调度
        故障（对齐 _transient_unseal_admit 的 fail-open 策略）。"""
        runner = getattr(self, "agent_runner", None)
        recredit = getattr(runner, "recredit_unseal_dispatch", None)
        if not callable(recredit):
            return
        try:
            recredit()
        except Exception:
            pass

    def _transient_unseal_note_drained(self) -> None:
        """错峰积压放完回调（队列空时退出错峰态）。异常静默，不阻断派发。"""
        runner = getattr(self, "agent_runner", None)
        note = getattr(runner, "note_unseal_release_drained", None)
        if not callable(note):
            return
        try:
            note()
        except Exception:
            pass

    def _effective_run_timeout(self, agent_type: str | None = None) -> float:
        """agent run 生效超时（per-agent-timeout-override 3.2）：override → 全局回退。

        （liveness 组件经门面回引调用；runner 不可用时以全局配置兜底。）
        """
        runner = getattr(self, "agent_runner", None)
        m = getattr(runner, "_effective_run_timeout", None)
        if callable(m):
            try:
                return m(agent_type)
            except Exception:
                pass
        from core.config import ConfigLoader

        return ConfigLoader.effective_run_timeout_seconds(self.config, agent_type)

    def _instant_fail_cooldown_until(self, spec_name: str) -> float:
        """返回 spec 的秒挂冷却到期单调秒（未冷却/无条目返回 0）。

        委托到 agent_runner.instant_fail_cooldown_until（code-review item
        97cdbf2893f7：与 _signal_kill_cooldown_until 同走公开方法，不再下钻
        runner 私有 dict）；runner 不可用或判定异常时 fail-open（返回 0，
        不排程恢复定时器）。
        """
        runner = getattr(self, "agent_runner", None)
        m = getattr(runner, "instant_fail_cooldown_until", None)
        if not callable(m):
            return 0.0
        try:
            return float(m(spec_name))
        except Exception:
            return 0.0

    def reclaim_stale_autostash_if_idle(self) -> bool:
        """滞留 autostash 兜底回收（fix-autostash-orphans）。

        仅当无活跃 run 时执行：有 worker 在跑时 pop 用户改动会让主树变脏，
        干扰其 merge-back 基线（虽然 guard 会重新 stash，但没必要抢跑）。
        """
        if self._active_runs > 0:
            return False
        return self.agent_runner.worktree_manager.reclaim_stale_autostash()

    def sweep_maintree_stray_wip(self):
        """主树散件 WIP 周期盘点（evo-add-maintree-stray-wip-sweep 2.1）。

        engine 包装方法（对齐 reclaim_stale_autostash_if_idle 先例）：由
        engine 供在飞 run_ids（run 注册表，识别归因入参）与 WorktreeManager
        句柄（主树锁 + 归因器）。盘点器实例按 WorktreeManager 句柄身份缓存
        （first_seen 注册表进程内持有，D5；wm 句柄更换即重建）。

        刻意**不设** ``_active_runs > 0`` 空闲预检（design D2）：sweep 是
        只读观察者，必须能看到在飞实现车道做归因——加了空闲预检就永远看不到
        在飞车道、全部按无主升级，告警语义失真（有 run 时零触碰盘点同样安全，
        与 merge-back 互斥由 worktree_manager 主树锁非阻塞 acquire 兜住）。
        """
        runner = self.agent_runner
        wm = runner.worktree_manager
        running = getattr(runner, "_running_agents", None) or {}
        # list(...) 快照迭代（code-review item d1351000e5b5，对齐
        # _cancel_lane_runs 的快照口径）：登记表由 worker 线程并发登记/收口，
        # 活视图迭代遇字典变长抛 RuntimeError 中断本轮盘点——sweep 刻意不设
        # 空闲预检、恰以在飞车道为归因对象，最需盘点的时刻最易触发。
        run_ids = [str(rid) for rid in list(running.keys())]
        sweeper = self._stray_wip_sweeper
        if sweeper is None or getattr(sweeper, "worktree_manager", None) is not wm:
            from core.worktree_manager.stray_wip import MainTreeStrayWipSweeper

            sweeper = MainTreeStrayWipSweeper(
                self.project_root, wm, config=self.config, logger=self.logger,
            )
            self._stray_wip_sweeper = sweeper
        return sweeper.sweep(running_run_ids=run_ids)

    _spec_fingerprint = staticmethod(RecoveryWatch._spec_fingerprint)

    _is_push_backoffed = staticmethod(ReportBuilder._is_push_backoffed)

    _get_push_retry_count = staticmethod(ReportBuilder._get_push_retry_count)

    @property
    def _queue_lock(self):
        return self._dispatcher._queue_lock

    @_queue_lock.setter
    def _queue_lock(self, value):
        self._dispatcher._queue_lock = value

    @_queue_lock.deleter
    def _queue_lock(self):
        del self._dispatcher._queue_lock

    @property
    def _run_queue(self):
        return self._dispatcher._run_queue

    @_run_queue.setter
    def _run_queue(self, value):
        self._dispatcher._run_queue = value

    @_run_queue.deleter
    def _run_queue(self):
        del self._dispatcher._run_queue

    @property
    def _active_runs(self):
        return self._dispatcher._active_runs

    @_active_runs.setter
    def _active_runs(self, value):
        self._dispatcher._active_runs = value

    @_active_runs.deleter
    def _active_runs(self):
        del self._dispatcher._active_runs

    @property
    def _active_reviews(self):
        # 评审在飞集合透传（fix-spec-review-blocking-dispatch 1.1）：与
        # _active_runs/_active_priorities 同族——测试与调用方多以属性路径
        # 访问队列态，缺该透传即 AttributeError。
        return self._dispatcher._active_reviews

    @_active_reviews.setter
    def _active_reviews(self, value):
        self._dispatcher._active_reviews = value

    @_active_reviews.deleter
    def _active_reviews(self):
        del self._dispatcher._active_reviews

    @property
    def _active_parallel_plans(self):
        # 并行出题在飞集合透传（add-verify-lane-throughput 2.1）：与
        # _active_reviews 同族——测试与触发点以属性路径访问队列态。
        return self._dispatcher._active_parallel_plans

    @_active_parallel_plans.setter
    def _active_parallel_plans(self, value):
        self._dispatcher._active_parallel_plans = value

    @_active_parallel_plans.deleter
    def _active_parallel_plans(self):
        del self._dispatcher._active_parallel_plans

    def is_review_in_flight(self, spec_name: str) -> bool:
        """评审在飞只读查询（fix-spec-review-blocking-dispatch 3.7）。

        DispatchQueue 持有 `_active_reviews`（评审条目已入队/已出队未收口的
        在飞登记），`reviewer_in_flight`（LivenessSupervisor 侧）与
        `_on_spec_reviewing` 均经此门面通路查询——agent_runner 不持 pm_engine，
        PMEngine __init__ 显式注入 `_pm_engine_ref` 回引（与 worktree_manager
        的 state_reader 注入同族，非即兴跨层引用）。锁读保持与 _active_runs
        同锁语义。
        """
        with self._queue_lock:
            return spec_name in self._active_reviews

    def has_queued_review(self) -> bool:
        """是否存在已入队未收口的评审登记（``_active_reviews`` 非空，只读）。

        fix-state-atomicity-and-selfheal-restart D3：评审在飞的**完整生命周期由两段
        拼成**，缺一即漏判——

        ①「评审条目已入队/已出队、``reviewer_run`` 锚点尚未落盘」的窗口只体现在
           ``_active_reviews``（``dispatch/queue.py`` 评审派发分支登记），此时
           STATE 里还没有任何锚点可枚举；
        ② 锚点落盘后该登记即被释放（``dispatch_review`` 前 discard），此后由
           ``reviewer_run`` 锚点 + ``reviewer_in_flight`` 接力。

        本查询给第①段一个 O(1) 只读入口（与 ``is_review_in_flight`` 同锁语义），
        MUST NOT 用它替代第②段——单靠 ``_active_reviews`` 会漏掉评审 run 的绝大
        部分生命周期（登记释放早于锚点落盘）。

        Returns: True 表示存在未收口的评审登记。
        """
        with self._queue_lock:
            return bool(self._active_reviews)

    def review_anchors(self) -> dict:
        """STATE 中 ``reviewer_run`` 非空的 spec → run_id（只读候选枚举）。

        fix-state-atomicity-and-selfheal-restart D3：陈旧自愈的空闲判定
        （fenixd ``_is_idle``，1s 粒度轮询）须把「未收口的在飞评审 run」计入
        非空闲，而状态机里评审在飞的**唯一落点**是 ``reviewer_run`` 锚点。

        本方法只做**候选收窄**：把「可能持有在飞评审」的 spec 圈出来，避免轮询侧
        对 STATE 全量条目逐条做在飞复核（每次复核要摸进程表与 run 流文件）。在飞
        **结论**仍由既有判据给出（``is_review_in_flight`` 覆盖入队/出队窗口 +
        ``LivenessSupervisor.reviewer_in_flight`` 覆盖进程/流/陈旧锚点分层），
        本方法 MUST NOT 自行判定在飞，也 MUST NOT 触碰
        ``_active_runs`` / ``_active_reviews`` 语义。

        Returns: ``{spec_name: reviewer_run}``（无锚点为空 dict）。STATE 不可读时
        返回空 dict 记 WARNING——调用方另有保守处理，且「读不出候选」不等于
        「有在飞」，不在此处代判。
        """
        anchors: dict = {}
        try:
            specs = self.state_machine.read_all()
        except Exception as e:  # noqa: BLE001 — 候选枚举失败不抛出（调用方保守兜底）
            self.logger.warning("pm_engine", f"review_anchors 读取 STATE 失败: {e}")
            return anchors
        for name, entry in specs.items():
            # 与 check_blockers / backfill_push_residuals 同款防御：STATE 坏条目
            # （非 dict）跳过，不让 1s 粒度轮询的空闲判定持续抛 AttributeError。
            if not isinstance(entry, dict):
                continue
            run_id = entry.get("reviewer_run")
            if run_id:
                anchors[name] = run_id
        return anchors

    @property
    def _active_priorities(self):
        return self._dispatcher._active_priorities

    @_active_priorities.setter
    def _active_priorities(self, value):
        self._dispatcher._active_priorities = value

    @_active_priorities.deleter
    def _active_priorities(self):
        del self._dispatcher._active_priorities

    @property
    def _active_priority_counts(self):
        return self._dispatcher._active_priority_counts

    @_active_priority_counts.setter
    def _active_priority_counts(self, value):
        self._dispatcher._active_priority_counts = value

    @_active_priority_counts.deleter
    def _active_priority_counts(self):
        del self._dispatcher._active_priority_counts

    @property
    def _backoff_timers(self):
        return self._dispatcher._backoff_timers

    @_backoff_timers.setter
    def _backoff_timers(self, value):
        self._dispatcher._backoff_timers = value

    @_backoff_timers.deleter
    def _backoff_timers(self):
        del self._dispatcher._backoff_timers

    @property
    def _recovery_watch(self):
        return self._recovery._recovery_watch

    @_recovery_watch.setter
    def _recovery_watch(self, value):
        self._recovery._recovery_watch = value

    @_recovery_watch.deleter
    def _recovery_watch(self):
        del self._recovery._recovery_watch

    @property
    def _signal_fingerprints(self):
        return self._recovery._signal_fingerprints

    @_signal_fingerprints.setter
    def _signal_fingerprints(self, value):
        self._recovery._signal_fingerprints = value

    @_signal_fingerprints.deleter
    def _signal_fingerprints(self):
        del self._recovery._signal_fingerprints
