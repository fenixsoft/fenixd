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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.dashboard.data import find_impl_run_file, parse_run_task_done
from core.pm_engine.family import FamilyGovernor
from core.pm_engine.budget import ImplBudget
from core.pm_engine.verification import VerificationPipeline
from core.pm_engine.family import (
    MAX_VERIFY_FAIL_ROUNDS,
)
from core.pm_engine.budget import (
    DEFAULT_IMPL_RUN_BUDGET,
    IMPL_RUN_BUDGET_USED_FIELD,
    BUDGET_EXEMPT_ALERT_THRESHOLD,
)
from core.state_machine import (
    BUDGET_EXEMPT_ALERTED_FIELD,
    BUDGET_EXEMPT_RUNS_FIELD,
)

# ── 派发锁冲突退避（improve-run-lifecycle-governance D5）────────────────────
# 派发 implementer 遇「worktree already active」时不再硬试三连发：按此序列指数
# 退避安排下一次尝试，期间不消耗 _retry_count、不写 retries exhausted（attempt
# 配额只属于任务失败，不属于基础设施冲突）。可配 pm.dispatch_backoff_schedule。
DEFAULT_DISPATCH_BACKOFF_SCHEDULE = (30, 120, 600)
# dispatch_stalled 信号的建议处置（与 admin_monitor.SIGNAL_RECOMMENDATION 同义；
# pm_engine 不反向依赖 admin_monitor，这里单独常量避免循环导入）
SIGNAL_RECOMMENDATION_DISPATCH_STALLED = (
    "检查持锁进程是否为孤儿（ps/pgrep 确认后 kill），清理残留 worktree 锁后让 spec 重新派发"
)

# ── 恢复闭环复查 / 假就绪巡检（improve-run-lifecycle-governance D6）──────────
# auto-recovery（含 defer）后登记观察项，followup_check_minutes 后复查该 spec
# 是否真实恢复推进；条目镜像到 .fenix/recovery_watch.json 供 daemon 重启续查。
RECOVERY_WATCH_FILE = "recovery_watch.json"
DEFAULT_FOLLOWUP_CHECK_MINUTES = 15
# 假就绪巡检：ready 滞留超过该阈值且期间无派发活动 → 阻塞项（design D6）
DEFAULT_READY_STALL_THRESHOLD_MINUTES = 20
# 同 spec 同指纹的巡检/滞留信号冷却（分钟）：指纹未变且冷却期内只记日志
DEFAULT_SIGNAL_COOLDOWN_MINUTES = 30
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

    def __init__(self, state_machine, agent_runner, config: dict,
                 project_root: Path, logger):
        self.state_machine = state_machine
        self.agent_runner = agent_runner
        self.config = config
        self.project_root = project_root
        self.logger = logger

        self._active_runs = 0
        # Pending (priority, spec_name, agent_type, enqueued_at) tuples。
        # enqueued_at 为入队时刻 time.time()，仅供内存态老化计时（design D3）：
        # 不持久化，daemon 重启重建队列即视为等待清零。
        self._run_queue = []
        self._active_priorities = set()  # 当前活动 priority 集合（宽松优先级下可含多个档）
        self._active_priority_counts: Dict[int, int] = {}  # priority → 活动 run 数
        self._handling_events = set()  # 防重入：正在处理的 (event_kind, spec_name)
        self._queue_lock = threading.Lock()  # 保护 _run_queue / _active_runs / _active_priorities

        # 优雅关闭标志（fix-admin-self-heal）：daemon 关闭期间禁止派发新 agent，
        # 否则 shutdown 的 wait_for_running_agents 会陷入「杀一个又起一个」的死循环
        self.shutting_down = False

        # Blocker detection state
        self._last_blocker_check = None
        self._last_blocker_report_time = None

        # 恢复闭环复查（improve-run-lifecycle-governance D6）：
        # {spec: {"fingerprint", "due", "registered_at", "reason"}}，镜像到
        # .fenix/recovery_watch.json，daemon 重启后续查。
        self._recovery_watch: dict = {}
        self._load_recovery_watch()
        # 巡检信号指纹去重（D6）：{spec: (fingerprint, raised_at_monotonic)}
        self._signal_fingerprints: dict = {}

    # ── Event Handlers ─────────────────────────────────────────────

    def handle_event(self, event_kind: str, spec_name: str, spec_entry: dict):
        """
        Handle an internal event from the EventBus.
        This is the main scheduling entry point.
        """
        # 防重入：同一 (event, spec) 正在处理中则跳过，打破 event bus 二次派发回路
        event_key = (event_kind, spec_name)
        if event_key in self._handling_events:
            self.logger.debug(
                "pm_engine",
                f"Skipping duplicate event: {event_kind} for '{spec_name}'",
            )
            return
        self._handling_events.add(event_key)

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
            }

            handler = handlers.get(event_kind)
            if handler:
                handler(spec_name)

            # Process any queued runs
            self._process_queue()
        finally:
            self._handling_events.discard(event_key)

    def _on_spec_drafted(self, spec_name: str):
        """Auto-promote drafted → ready, then immediately schedule implementer."""
        self.logger.info("pm_engine", f"Auto-promoting '{spec_name}': drafted → ready")
        self.state_machine.transition(spec_name, "ready")
        # 直接调用 _on_spec_ready 排队实现，不依赖事件循环
        self._on_spec_ready(spec_name)

    def _on_spec_ready(self, spec_name: str):
        """Schedule implementer for ready SPEC (if dependencies are satisfied)."""
        # 优雅关闭期间不再派发（fix-admin-self-heal）
        if self.shutting_down:
            return
        # 防双派发：该 spec 已有活动 implementer worktree 时跳过。
        # 背景（fix-fenix-token-waste）：启动扫描与 event_bus 都会触发 spec_ready，
        # 第二次派发因 worktree 锁失败会把 spec 打回 ready，形成空转反馈环。
        if self.agent_runner.worktree_manager.has_active_worktree(spec_name):
            # 锁治理（improve-run-lifecycle-governance D5）：锁冲突进入退避计划，
            # 不硬试、不消耗 attempt 配额（2026-08-27 add-spec-context-menu 事故：
            # 孤儿 resume 持锁，派发 ~15s 内三连发耗尽 retries exhausted，spec 假死）。
            self._handle_dispatch_lock_conflict(spec_name)
            return
        # 退避期内静默跳过（不写 STATE，避免「写 error → 触发 spec_ready 事件」
        # 的自触发热循环）；退避到期后由排定的定时器 / 周期扫描重试。
        spec = self.state_machine.read_one(spec_name) or {}
        if self._dispatch_backoffed(spec):
            self.logger.debug(
                "pm_engine",
                f"Skipping '{spec_name}': dispatch backoff active",
            )
            return
        if not self._dependencies_satisfied(spec_name):
            self.logger.info(
                "pm_engine",
                f"Skipping '{spec_name}': dependencies not satisfied",
            )
            return
        self._enqueue(spec_name, "implementer")

    # ── 派发锁冲突退避（improve-run-lifecycle-governance D5）──────────────────

    def _dispatch_backoff_schedule(self) -> list:
        """退避序列（秒）。可配 pm.dispatch_backoff_schedule，默认 [30, 120, 600]。

        配置容错：标量视作单元素序列；空/非法序列回退默认值。
        """
        sched = self._get_config(
            "pm.dispatch_backoff_schedule",
            list(DEFAULT_DISPATCH_BACKOFF_SCHEDULE),
        )
        if isinstance(sched, (int, float)):
            sched = [sched]
        if not isinstance(sched, (list, tuple)) or not sched:
            return list(DEFAULT_DISPATCH_BACKOFF_SCHEDULE)
        out = []
        for x in sched:
            try:
                out.append(max(0.0, float(x)))
            except (TypeError, ValueError):
                continue
        return out or list(DEFAULT_DISPATCH_BACKOFF_SCHEDULE)

    def _handle_dispatch_lock_conflict(self, spec_name: str) -> None:
        """派发遇 worktree 锁冲突：按退避序列安排下次尝试（design D5）。

        - 不递增 ``_retry_count``、不写 retries exhausted：锁冲突是基础设施状态
          而非任务失败，attempt 配额不被消耗；
        - spec 保持 ready，error 字段记录「backoff until <time>」供 Dashboard 可读；
        - 按 ``pm.dispatch_backoff_schedule`` 逐档递增安排下次尝试（定时器重入
          ``_on_spec_ready``，daemon 重启后由周期扫描兜底）；
        - 序列耗尽仍持锁 → 发 dispatch_stalled 信号（severity major）上报，spec
          保持 ready 等待处置，不再自旋重试。
        """
        spec = self.state_machine.read_one(spec_name) or {}
        try:
            count = int(spec.get("_lock_conflict_count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        schedule = self._dispatch_backoff_schedule()

        now = time.time()
        exhausted = count >= len(schedule)
        delay = schedule[-1] if exhausted else schedule[count]
        until = int(now + delay)
        from datetime import datetime as _dt, timezone as _tz
        until_iso = _dt.fromtimestamp(until, _tz.utc).isoformat()

        # 不翻转状态：spec 保持 ready，仅记录退避元数据
        self.state_machine.update_spec(spec_name, {
            "error": f"worktree already active (lock conflict); backoff until {until_iso}",
            "_lock_conflict_count": count + 1,
            "_dispatch_backoff_until": until,
            "_last_lock_conflict_at": _dt.now(_tz.utc).isoformat(),
        })

        if exhausted:
            evidence = (
                f"lock conflicts={count + 1} (backoff schedule {list(schedule)}s exhausted), "
                f"last conflict at {spec.get('_last_lock_conflict_at') or 'n/a'}, "
                f"error={str(spec.get('error') or '')[:120]}"
            )
            self.logger.error(
                "pm_engine",
                f"Dispatch backoff exhausted for '{spec_name}' — lock still held, "
                f"escalating dispatch_stalled",
            )
            self._signal_dispatch_stalled(spec_name, evidence)
            # 序列耗尽后不再自旋重试（定时器停止），spec 保持 ready 等待处置
            return

        self.logger.info(
            "pm_engine",
            f"Dispatch lock conflict for '{spec_name}' — backoff {int(delay)}s "
            f"(attempt {count + 1}/{len(schedule)}), not counted against retries",
        )
        self._schedule_backoff_retry(spec_name, delay)

    def _schedule_backoff_retry(self, spec_name: str, delay: float) -> None:
        """退避到期后重入 ``_on_spec_ready``（daemon 线程；关闭期间自然失效）。"""
        timer = threading.Timer(
            max(0.5, float(delay)),
            self._on_spec_ready,
            args=(spec_name,),
        )
        timer.daemon = True
        with self._queue_lock:
            self._backoff_timers = [
                t for t in getattr(self, "_backoff_timers", []) if t.is_alive()
            ]
            self._backoff_timers.append(timer)
        timer.start()

    # ── 恢复闭环复查 / 假就绪巡检（improve-run-lifecycle-governance D6）───────

    def _recovery_watch_path(self) -> Path:
        return self.project_root / ".fenix" / RECOVERY_WATCH_FILE

    def _load_recovery_watch(self) -> None:
        """重启后从 .fenix/recovery_watch.json 续查观察项（损坏/缺失按空兜底）。"""
        try:
            data = json.loads(self._recovery_watch_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self._recovery_watch = {
                k: v for k, v in data.items() if isinstance(v, dict)
            }

    def _save_recovery_watch(self) -> None:
        try:
            path = self._recovery_watch_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self._recovery_watch, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self.logger.warning(
                "pm_engine", f"Failed to persist recovery watch: {e}",
            )

    def register_recovery_watch(self, spec_name: str, reason: str) -> None:
        """登记恢复观察项：followup_check_minutes 后复查 spec 是否真实恢复推进。

        auto-recovery 与 recovery deferred（存活子进程仍在）都会登记——后者防止
        「defer → 下轮仍卡死 → 再 defer」无限循环（tasks 3.1）。
        """
        minutes = float(self._get_config(
            "pm.recovery.followup_check_minutes", DEFAULT_FOLLOWUP_CHECK_MINUTES) or
            DEFAULT_FOLLOWUP_CHECK_MINUTES)
        entry = self.state_machine.read_one(spec_name) or {}
        self._recovery_watch[spec_name] = {
            "fingerprint": self._spec_fingerprint(entry),
            "due": time.time() + max(0.5, minutes) * 60,
            "registered_at": time.time(),
            "reason": reason,
            # 登记时的状态：复查通过条件 = 已离开该状态或已有活跃派发
            # （auto-recovery 登记时是 ready/implemented；defer 登记时是
            # implementing/testing 等卡死态——离开它才算恢复推进）。
            "status_at_register": entry.get("status"),
        }
        self._save_recovery_watch()
        self.logger.info(
            "pm_engine",
            f"Recovery watch registered for '{spec_name}' "
            f"(recheck in {minutes:.0f}m): {reason}",
        )

    def check_recovery_watch(self) -> list:
        """到期复查观察项（daemon 周期调用 + BLOCKER CHECK 内调用）。

        通过条件（spec Scenario）：spec 已离开 ready 或已有活跃派发（worktree
        在跑）→ 关闭观察项且不告警；否则触发 dispatch_stalled 信号唤起
        Administrator，并关闭观察项（后续由巡检指纹冷却与处置接管）。

        Returns: 本次发出的信号 spec 列表（审计/测试用）。
        """
        raised = []
        now = time.time()
        for spec_name, item in list(self._recovery_watch.items()):
            if now < float(item.get("due") or 0):
                continue
            self._recovery_watch.pop(spec_name, None)
            self._save_recovery_watch()
            entry = self.state_machine.read_one(spec_name)
            if not entry:
                continue  # spec 已消失（被人工清理）：观察项静默关闭
            status = entry.get("status")
            active_dispatch = False
            try:
                active_dispatch = bool(
                    self.agent_runner.worktree_manager.has_active_worktree(spec_name))
            except Exception:
                active_dispatch = False
            if status != item.get("status_at_register") or active_dispatch:
                self.logger.info(
                    "pm_engine",
                    f"Recovery watch passed for '{spec_name}' "
                    f"(status={status}, active_dispatch={active_dispatch})",
                )
                continue
            evidence = (
                f"auto-recovery/defer at {item.get('registered_at')} "
                f"({item.get('reason')}); spec still ready with no active dispatch "
                f"after followup window, status={status}, "
                f"error={str(entry.get('error') or '')[:120]}"
            )
            self.logger.error(
                "pm_engine",
                f"Recovery watch failed for '{spec_name}' — still stalled in ready, "
                f"escalating dispatch_stalled",
            )
            self._signal_dispatch_stalled(spec_name, evidence)
            raised.append(spec_name)
        return raised

    @staticmethod
    def _spec_fingerprint(entry: dict) -> str:
        """spec 状态指纹 = hash(status + error 摘要)（D6 信号去重依据）。"""
        basis = f"{entry.get('status')}|{str(entry.get('error') or '')[:120]}"
        return hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:12]

    def _signal_dispatch_stalled(self, spec_name: str, evidence: str,
                                 fingerprint: str | None = None) -> None:
        """退避耗尽仍持锁 / 恢复复查未通过 / 假就绪滞留 → dispatch_stalled 信号（D5/D6）。

        写入 admin store（kind=SIGNAL, severity major），由 AdminMonitor 摄取唤起
        Administrator。双重去重避免反复拉起：
          - 指纹去重（D6）：同 spec 同一状态指纹在
            ``pm.recovery.signal_cooldown_minutes``（默认 30）内只记日志；
            指纹变化或冷却结束方可再次写入。
          - admin_alerts 去重：store 内冷却期内已有同类信号时同样抑制。
        """
        from core.admin_store import AdminStore, SIGNAL
        entry = self.state_machine.read_one(spec_name) or {}
        fp = fingerprint or self._spec_fingerprint(entry)
        cooldown = float(self._get_config(
            "pm.recovery.signal_cooldown_minutes", DEFAULT_SIGNAL_COOLDOWN_MINUTES) or
            DEFAULT_SIGNAL_COOLDOWN_MINUTES) * 60
        prev = self._signal_fingerprints.get(spec_name)
        now = time.time()
        if prev and prev[0] == fp and (now - prev[1]) < cooldown:
            self.logger.info(
                "pm_engine",
                f"dispatch_stalled for '{spec_name}' suppressed (same fingerprint "
                f"{fp} within {int(cooldown / 60)}m cooldown) — logged only",
            )
            return
        self._signal_fingerprints[spec_name] = (fp, now)

        store_cooldown = float(
            self._get_config("admin.escalation_cooldown_minutes", 15) or 15)
        store = AdminStore(self.project_root, self.logger)
        try:
            if store.latest_signal(spec_name, "dispatch_stalled", store_cooldown) is not None:
                self.logger.info(
                    "pm_engine",
                    f"dispatch_stalled for '{spec_name}' suppressed "
                    f"(cooldown {store_cooldown:.0f}m)",
                )
                return
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"dispatch_stalled dedup check failed '{spec_name}' (proceeding): {e}",
            )
        try:
            store.append({
                "kind": SIGNAL,
                "signal_type": "dispatch_stalled",
                "spec": spec_name,
                "severity": "major",
                "description": (
                    f"'{spec_name}' 派发长期被 worktree 锁冲突滞留，"
                    f"退避计划耗尽仍未获得锁"
                ),
                "evidence": evidence,
                "recommended_action": SIGNAL_RECOMMENDATION_DISPATCH_STALLED,
            })
            self.logger.warning(
                "pm_engine",
                f"dispatch_stalled signal recorded for '{spec_name}'",
            )
        except Exception as e:
            self.logger.error(
                "pm_engine",
                f"Failed to record dispatch_stalled for '{spec_name}': {e}",
            )

    def _clear_dispatch_conflict(self, spec_name: str) -> dict:
        """派发成功后清零锁冲突计数与退避窗口（返回 update 字段供合并写入）。"""
        return {
            "_lock_conflict_count": 0,
            "_dispatch_backoff_until": None,
            "_last_lock_conflict_at": None,
        }

    def _on_spec_implemented(self, spec_name: str):
        """Schedule verifier for implemented SPEC."""
        self._enqueue(spec_name, "verifier")

    def _on_spec_verified(self, spec_name: str):
        """Mark verified SPEC as done."""
        # 防重入：使用独立 key，避免与 handle_event 的 ("spec_verified", spec_name)
        # 冲突（handle_event 在调用 handler 前已 add 该 key，若共用会导致本方法被跳过）
        event_key = ("_guard:verified", spec_name)
        if event_key in self._handling_events:
            self.logger.debug("pm_engine", f"Skipping duplicate verified for '{spec_name}'")
            return
        self._handling_events.add(event_key)
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
                if vblocker:
                    self.logger.warning(
                        "pm_engine",
                        f"验证进度不完整 '{spec_name}'，门禁逃生门回退 testing 重新验证: {vblocker}",
                    )
                    # 保留 implementer_run 与既有 progress 断点（D7），仅置 error 摘要
                    self.state_machine.update_spec(spec_name, {
                        "error": f"验证进度不完整，回退重新验证: {vblocker}",
                    })
                    self.state_machine.transition_gate(spec_name, "testing")
                    return
                self.logger.warning(
                    "pm_engine",
                    f"验证放行门禁拦截 '{spec_name}'（保持 verified）: {blocker}",
                )
                self.state_machine.update_spec(spec_name, {
                    "error": blocker,
                })
                return

            self.logger.info("pm_engine", f"Verification passed: '{spec_name}' → done")
            self.state_machine.transition(spec_name, "done")
            # 同步触发 spec_done 处理（fix done → 自动重新验证父 SPEC）。
            # 背景：daemon 启动时 full_scan 在 EventBus watcher 启动前同步调度，
            # 阻塞完成整个 fix 生命周期，使 verified→done 变化在快照初始化前发生，
            # spec_done 事件被吞掉，父 SPEC 永远不被重新验证。这里提供同步直接
            # 调用路径（框架原则：状态转换不能只依赖异步事件轮询）。
            # 幂等：父 SPEC 若已非 implementing，transition 校验失败自动跳过；
            # _enqueue 亦有去重。事件总线后续若重复发出 spec_done 亦无害。
            self._on_spec_done(spec_name)
        finally:
            self._handling_events.discard(event_key)

    def _on_spec_bug_found(self, spec_name: str):
        """Create or reset a fix SPEC for the bug and immediately schedule it."""
        # 防重入：使用独立 key，避免与 handle_event 的 ("spec_bug_found", spec_name)
        # 冲突（handle_event 在调用 handler 前已 add 该 key，若共用会导致本方法被跳过）
        event_key = ("_guard:bug_found", spec_name)
        if event_key in self._handling_events:
            self.logger.debug("pm_engine", f"Skipping duplicate bug_found for '{spec_name}'")
            return
        self._handling_events.add(event_key)
        try:
            self._do_spec_bug_found(spec_name)
        finally:
            self._handling_events.discard(event_key)



    # ── fix 族谱收敛治理（fix-family-convergence-governor / design D4）──
















    # ── 原地打回辅助：任务注入与升级告警 ──────────────────────────────

    _VERIFY_FIX_SECTION_RE = re.compile(r"^## 验证修复\b.*$", re.MULTILINE)








    # ── 预算计数对账（fix-budget-counting-semantics D3，日志级）──────






    def _on_spec_done(self, spec_name: str):
        """SPEC is done — log, re-verify parent if this was a fix SPEC.

        若 gates.approve_mode == "auto"，自动执行 git push 并推进到 pushed。
        """
        spec = self.state_machine.read_one(spec_name) or {}
        status = spec.get("status", "")

        self.logger.info(
            "pm_engine",
            f"SPEC '{spec_name}' is done — awaiting push approval",
        )

        self._append_project_log(
            f"✅ SPEC completed: **{spec_name}** — awaiting push approval"
        )

        # 自动审批：approve_mode=auto 且状态为 done 时触发
        # （若已 pushed 则 _auto_approve 内部幂等跳过，不重复推送）
        approve_mode = self._get_approve_mode()
        if approve_mode == "auto" and status == "done":
            self._auto_approve(spec_name)

        # ── legacy：存量 fix-* SPEC 完成 → 父 SPEC 自动重验（D4 过渡期兼容）──
        # 仅对 fix-* 链条生效；新裁决不再产生 fix-* 派生，待存量链收敛后自然耗尽。
        # If this is a fix SPEC, re-trigger verification of the original SPEC
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
                self.state_machine.transition(original, "implemented")
                self.state_machine.update_spec(original, {
                    "error": f"Re-verifying after fix: {spec_name}",
                })
                self._enqueue(original, "verifier")

    def _find_implementer_worktree(self, spec_name: str) -> Optional[Path]:
        """Find the active implementer worktree for a SPEC, or None."""
        wt_mgr = getattr(self.agent_runner, 'worktree_manager', None)
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
            root_result = self.project_root / ".fenix-run-result.json"
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
                # 共享结果文件护栏：文件携带的 spec 与当前 spec 不符时，
                # 视作其它 spec 的残留（主树 .fenix-run-result.json 是共享文件，
                # 任何 spec 成功都会覆盖写它），避免「CLI 成功退出却被残留文件
                # 误判为失败 → 无谓重试」（admin 处置 add-spec-context-menu 根因）。
                stamped = data.get("spec")
                if isinstance(stamped, str) and stamped and stamped != spec_name:
                    self.logger.warning(
                        "pm_engine",
                        f"Ignoring stale result file {result_path}: "
                        f"spec='{stamped}' != '{spec_name}'",
                    )
                    return None
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return None

    # ── 任务进度写侧回写（add-task-progress-sync） ───────────────────
    #
    # implementer run 成功后，从 run 产物确定性解析已完成任务集，把主树
    # tasks.md 对应 id 的 `- [ ]` 改成 `- [x]`，不撤销任何既有勾选（只增不减）。

    _TASK_LINE_RE = re.compile(r"^(\s*-\s+)\[(\s|x)\](\s+)(\d+\.\d+)(.*)$")

    def _sync_task_progress(self, spec_name: str):
        """把已成功完成的任务勾选确定性回写进主树 tasks.md 并 commit。

        幂等：已勾选的条目跳过；无 run 产物 / 解析为空 / 工作树不干净时
        直接返回（不报错、不产生空 commit）。任何异常由调用方捕获，不阻塞主流程。
        """
        tasks_path = self.project_root / "openspec" / "changes" / spec_name / "tasks.md"
        if not tasks_path.exists():
            self.logger.debug("pm_engine", f"任务回写跳过（无 tasks.md）：{spec_name}")
            return

        run_file = find_impl_run_file(self.project_root, spec_name)
        if run_file is None:
            self.logger.debug("pm_engine", f"任务回写跳过（无 run 产物）：{spec_name}")
            return

        rd = parse_run_task_done(run_file)
        done_ids = rd.get("done_ids") or set()
        if not done_ids:
            self.logger.debug("pm_engine", f"任务回写跳过（done_ids 为空）：{spec_name}")
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
        changed = False
        new_lines = []
        for line in lines:
            m = self._TASK_LINE_RE.match(line)
            if m and m.group(4) in done_ids and m.group(2) != "x":
                # `- [ ]` → `- [x]`，仅当该 id 在 done_ids 且当前未勾选
                new_lines.append(f"{m.group(1)}[x]{m.group(3)}{m.group(4)}{m.group(5)}")
                changed = True
            else:
                new_lines.append(line)
        if not changed:
            self.logger.debug("pm_engine", f"任务回写跳过（无新勾选）：{spec_name}")
            return

        tasks_path.write_text("\n".join(new_lines), encoding="utf-8")
        commit_msg = f"[fenix] {spec_name}: sync task progress from run record"
        ok, err = self._git_commit([str(tasks_path)], commit_msg)
        if not ok:
            self.logger.warning("pm_engine", f"任务回写 commit 失败 '{spec_name}': {err}")
            return
        self.logger.info(
            "pm_engine",
            f"任务进度回写成功 '{spec_name}'：勾选 {len(done_ids)} 个任务",
        )

    def _worktree_is_dirty(self) -> bool:
        """主树工作区是否存在未提交改动（add-task-progress-sync 回写的安全闸门）。"""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return True  # 无法判断时保守视为脏，跳过回写
            return bool(result.stdout.strip())
        except Exception:
            return True

    def _git_commit(self, paths: list, message: str) -> tuple:
        """在 project_root 对指定路径执行 git add + commit。

        Returns: (success: bool, error_message: str)
        """
        try:
            add = subprocess.run(
                ["git", "add", "--"] + paths,
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=60,
            )
            if add.returncode != 0:
                return False, add.stderr.strip() or f"git add exit {add.returncode}"
            commit = subprocess.run(
                ["git", "commit", "-m", message, "--"] + paths,
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=120,
            )
            if commit.returncode != 0:
                return False, commit.stderr.strip() or f"git commit exit {commit.returncode}"
            return True, ""
        except subprocess.TimeoutExpired:
            return False, "git commit timed out"
        except Exception as e:
            return False, str(e)

    def _task_completion_blocker(self, spec_name: str) -> str | None:
        """verified→done 任务完成一致性门禁（add-task-progress-sync）。

        返回 None 表示门禁通过（可推进到 done）；返回非空字符串表示缺口描述，
        此时应阻断 auto approve / verified→done，把缺口写入 error 字段供人工裁决。

        判定规则：
        - 无 run 记录可查（.fenix-run-result.json 缺失/无效）→ 放行（无法证伪即放行）。
        - run 声明 success，但存在「tasks.md 未勾选 且 不在 run done_ids」的任务
          → 阻断，返回缺口清单（任务 id 列表）。
        - 全部任务可确认完成（勾选 ∪ done_ids 覆盖全部）→ 放行。
        - fix-* SPEC 走完全相同规则。
        """
        result = self._read_implementer_result(spec_name)
        # 无法证伪即放行（无 run 记录 / 非 implementer 产物）
        if not result:
            return None
        impl_status = result.get("status")
        # 仅当 run 声明 success 时才做一致性校验；其它状态（error/缺失）放行。
        if impl_status != "success":
            return None

        tasks_path = self.project_root / "openspec" / "changes" / spec_name / "tasks.md"
        if not tasks_path.exists():
            return None

        # 解析 tasks.md 的勾选状态与全部任务 id
        checked_ids: set = set()
        all_ids: list = []
        try:
            for line in tasks_path.read_text(encoding="utf-8").split("\n"):
                m = re.match(r"^- \[(x| )\] (\d+\.\d+)", line)
                if m:
                    tid = m.group(2)
                    all_ids.append(tid)
                    if m.group(1) == "x":
                        checked_ids.add(tid)
        except (OSError, UnicodeDecodeError):
            return None

        # 解析 run 记录的完成任务 id
        run_file = find_impl_run_file(self.project_root, spec_name)
        done_ids: set = set()
        if run_file is not None:
            done_ids = parse_run_task_done(run_file).get("done_ids") or set()

        # 缺口：未勾选 且 不在 done_ids 中的任务
        gap = [tid for tid in all_ids if tid not in checked_ids and tid not in done_ids]
        if gap:
            return "未完成任务：" + "、".join(gap)
        return None





    # ── judge 自述环境问题守卫（不派生 fix）────────────────────────

    _ENV_INFRA_MARKERS = (
        "环境问题", "环境配置", "环境故障", "测试环境",
        "非产品", "不是产品", "而非产品",
    )



    # ── 裁决证据分类校验 / 采纳（add-verdict-evidence-taxonomy D1-D5）──







    # ── Queue Management ───────────────────────────────────────────

    def _get_spec_priority(self, spec_name: str) -> int:
        """读取 SPEC 的 priority，缺省为 5。"""
        spec = self.state_machine.read_one(spec_name)
        if spec and isinstance(spec.get("priority"), int):
            return spec["priority"]
        return 5

    def _enqueue(self, spec_name: str, agent_type: str):
        """Add a run request to the queue (thread-safe).

        条目结构：(priority, spec_name, agent_type, enqueued_at)。
        priority 从 STATE.md 读取（缺省 5）；enqueued_at = time.time() 供
        派发队列老化计时（design D3，内存态、不持久化）。
        """
        priority = self._get_spec_priority(spec_name)
        entry = (priority, spec_name, agent_type, time.time())
        with self._queue_lock:
            # 去重：忽略 priority 差异，只看 (spec, agent)
            if not any(e[1] == spec_name and e[2] == agent_type for e in self._run_queue):
                self._run_queue.append(entry)
                self.logger.debug(
                    "pm_engine",
                    f"Queued: {spec_name} ({agent_type}, P{priority})"
                )

    def _enqueue_front(self, spec_name: str, agent_type: str):
        """Insert a run request at the front of its priority bucket (thread-safe).

        在优先级调度下，「队首」语义改为同档优先：verifier 与 implementer
        属于同一 SPEC、同一 priority，插入后落回同一档且保持档内 FCFS。
        """
        priority = self._get_spec_priority(spec_name)
        entry = (priority, spec_name, agent_type, time.time())
        with self._queue_lock:
            # Remove existing duplicate (ignoring priority)
            self._run_queue = [
                e for e in self._run_queue
                if not (e[1] == spec_name and e[2] == agent_type)
            ]
            # 插入到同优先级档的最前面（保持同一档内的顺序）
            insert_idx = 0
            for i, e in enumerate(self._run_queue):
                if e[0] == priority:
                    insert_idx = i
                    break
                if e[0] > priority:
                    insert_idx = i
                    break
                insert_idx = i + 1
            self._run_queue.insert(insert_idx, entry)
            self.logger.debug(
                "pm_engine",
                f"Queued at front of P{priority}: {spec_name} ({agent_type})"
            )

    # ── 派发队列老化（dispatch-queue-aging / design D3）─────────

    def _aging_bonus(self, enqueued_at: float, now: float) -> int:
        """队列等待老化收益：条目等待越久，参与比较的优先级档越高。

        方向说明：本项目 priority 数值越小代表越重要、越早派发。放宽规则为
        「任务 X 可派发当且仅当 min(active_priorities) >= X」——因此等待条目的
        *比较档位* 必须随等待降低（effective = base - bonus）才能在 P4/P5 家族
        持续占用下给 P6 打开派发窗口（spec Scenario: P6 条目获得窗口）。设计
        文档中的字面 `base + …` 公式与自身 Scenario 相悖（只会让 P6 更晚派发），
        本实现以行为需求为准：effective = max(0, base - bonus)。

        config: pm.dispatch.aging.
            enabled (默认 false) —— 关闭时恒返回 0，行为与现状完全一致；
            initial_wait_minutes (默认 30) —— 等待不足此值不老化的零窗口；
            step_down_minutes (默认 15) —— 每满一档老化时间降一级比较；
            floor_levels (默认 4) —— 单条目等效降级总量上限（P6 最低可比至 P2，
              仍天然低于新到的 P1，高优家族先占）。
        """
        from core.config import ConfigLoader
        cfg = self.config or {}
        a = dict(ConfigLoader.get(cfg, "pm.dispatch.aging", {}) or {})
        enabled = a.get("enabled", False)
        if not enabled:
            return 0
        # 注意：不能用 `or 默认值` 取参 —— 配置 0（initial_wait/step_down）合法且常见，
        # 0 为假值会被误替换为默认值。
        iw = a.get("initial_wait_minutes")
        sw = a.get("step_down_minutes")
        fl = a.get("floor_levels")
        initial_wait = max(0.0, float(iw if iw is not None else 30)) * 60.0
        step_down = max(0.0, float(sw if sw is not None else 15)) * 60.0
        floor_levels = max(0, int(fl if fl is not None else 4))
        elapsed = max(0.0, now - (enqueued_at or now))
        if step_down <= 0 or elapsed < initial_wait:
            return 0
        steps = int((elapsed - initial_wait) // step_down)
        return min(floor_levels, max(0, steps))

    def _effective_priority(self, base: int, enqueued_at: float, now: float) -> int:
        """条目参与优先级判定时的有效档位（activity 追踪仍用 base，活动任务不老化）。"""
        return max(0, base - self._aging_bonus(enqueued_at, now))

    def _process_queue(self):
        """Process the run queue — relaxed-priority parallel scheduling.

        调度规则（宽松优先级并行，fix-fenix-token-waste 后按用户要求调整）：
        - 任务 X 可派发当且仅当没有比 X 更重要的活动任务
          （即 min(active_priorities) >= X）：有 P6 在跑时 P5 可并发、P7 不行。
        - 同一档内多个任务可并行至 max_concurrent；不同档可并发（只要满足上述规则）。
        - 不抢占：已在运行的任务不会被新到的高优先级中断。
        - 每轮派发队列中最高优先级的合法就绪条目。

        队列老化（dispatch-queue-aging / design D3）：比较用 effective 档位
        （base - 等待老化收益）；派发后活动集合 _active_priorities 记 base 原值
        —— 活动任务不参与老化降级（spec Scenario: 持久运行的 P4 不会被降级）；
        同级（effective 相等）条目保持「先入队先派发」的队首顺序（先入队者
        老化收益 ≥ 后入队者，队首扫描天然保持同级 FCFS，spec Scenario: 同级
        顺序稳定）。老化仅内存态 —— enqueued_at 随进程存活，daemon 重启重建
        队列即从零计时。
        """
        # 优雅关闭期间不再派发（fix-admin-self-heal）
        if self.shutting_down:
            self.logger.debug("pm_engine", "Shutting down — dispatch paused")
            return
        max_concurrent = self._get_config("agents.max_concurrent", 2)

        # 本轮调用内已被守卫三抑制的条目（spec, agent_type）。
        # 被抑制条目保持 queued（后到抑制），但绝不能阻塞其后的条目派发
        # —— 否则队首一个被抑制条目就会让整条队列停摆（2026-08-28 实证：
        # 双 ready 同根兄弟互相判对方 actionable，P6/P7 全线无法派发）。
        suppressed = set()

        while True:
            entry_to_dispatch = None

            with self._queue_lock:
                if self._active_runs >= max_concurrent:
                    return
                if not self._run_queue:
                    return
                now = time.time()

                # 找队列中所有状态合法条目的最高 effective 档位
                # （先不 pop，只扫描以确定 queued_best）
                best_valid_prio = None
                for entry in self._run_queue:
                    prio, sname, atype, enqueued_at = entry
                    if (sname, atype) in suppressed:
                        continue
                    eff = self._effective_priority(prio, enqueued_at, now)
                    spec = self.state_machine.read_one(sname)
                    if not spec:
                        continue
                    status = spec.get("status")
                    if atype == "implementer" and status not in ("ready", "implementing"):
                        # implementing 允许派发 = 原地打回的修复重派（热修 2026-08-29）：
                        # 打回处置 _enqueue 时状态为 implementing，旧条件 status != "ready"
                        # 导致修复条目被永久静默跳过、链路停摆。入队点均在 run 终止后
                        # （打回处理器/零变更重试）且 _enqueue 按 (spec,type) 去重，无双派。
                        continue
                    if atype == "verifier" and status != "implemented":
                        continue
                    if self._dispatch_backoffed(spec):
                        continue
                    if best_valid_prio is None or eff < best_valid_prio:
                        best_valid_prio = eff
                if best_valid_prio is None:
                    return  # 无就绪条目

                # 确定当前应派发的目标档位（宽松优先级）：
                # 任务 X 可派发当且仅当没有比 X 更重要的活动任务
                # （即 min(active) >= X；有 P6 在跑时 P5 可并发、P7 不行）。
                # 无活动任务时派发就绪条目中最高优先级档。
                if self._active_priorities:
                    min_active = min(self._active_priorities)
                    if best_valid_prio > min_active:
                        # 队列中最优就绪任务比活动任务更低优先（数值更大）：
                        # 被更高优先的活动任务挡住，本轮不派发
                        return
                target_prio = best_valid_prio

                # 从队列头部开始找第一个 effective == target 且状态合法的条目。
                # 队首即同档最老条目（enqueued_at 单调不减）：同级 FCFS 不被老化扰动。
                dispatch_idx = None
                for i, entry in enumerate(self._run_queue):
                    prio, sname, atype, enqueued_at = entry
                    if (sname, atype) in suppressed:
                        continue
                    if self._effective_priority(prio, enqueued_at, now) != target_prio:
                        continue
                    spec = self.state_machine.read_one(sname)
                    if not spec:
                        continue
                    status = spec.get("status")
                    if atype == "implementer" and status not in ("ready", "implementing"):
                        # implementing 允许派发 = 原地打回的修复重派（热修 2026-08-29）：
                        # 打回处置 _enqueue 时状态为 implementing，旧条件 status != "ready"
                        # 导致修复条目被永久静默跳过、链路停摆。入队点均在 run 终止后
                        # （打回处理器/零变更重试）且 _enqueue 按 (spec,type) 去重，无双派。
                        continue
                    if atype == "verifier" and status != "implemented":
                        continue
                    if self._dispatch_backoffed(spec):
                        continue
                    dispatch_idx = i
                    break

                if dispatch_idx is None:
                    # 目标档位无就绪条目（可能有但状态不合法），本轮不派发
                    return

                entry_to_dispatch = self._run_queue.pop(dispatch_idx)
                self._active_runs += 1
                # 活动追踪记 base 原值：活动任务不老化
                # （spec Scenario: 持久运行的 P4 不会被降级，min_active 语义不变）。
                base_prio = entry_to_dispatch[0]
                self._active_priority_counts[base_prio] = (
                    self._active_priority_counts.get(base_prio, 0) + 1
                )
                self._active_priorities.add(base_prio)
                active_count = self._active_runs

            priority, spec_name, agent_type, my_enqueued_at = entry_to_dispatch

            # ── 守卫三：派发互斥（fix-repair-lane-dedup / design 守卫三，legacy）──
            # 仅存量 fix-* SPEC 可达（非 fix 父 SPEC 现已走原地打回，不进入此分支）。
            # fix spec 实现器派发前检查同根兄弟是否存在活跃修复活动；
            # 存在则回滚 entry 到队列、跳过本轮派发（先到先得，后到抑制）。
            # 被抑制条目记入 suppressed 后继续扫描后队：抑制自己 ≠ 阻塞他人。
            if agent_type == "implementer" and self._is_fix_spec(spec_name):
                carrier = self._sibling_repair_active(
                    spec_name, my_enqueued_at=my_enqueued_at
                )
                if carrier:
                    # 回滚：把已 pop 的 entry 放回队列
                    with self._queue_lock:
                        self._run_queue.insert(0, entry_to_dispatch)
                        self._active_runs -= 1
                        cnt = self._active_priority_counts.get(base_prio, 0) - 1
                        if cnt <= 0:
                            self._active_priority_counts.pop(base_prio, None)
                            self._active_priorities.discard(base_prio)
                        else:
                            self._active_priority_counts[base_prio] = cnt
                    self.logger.info(
                        "pm_engine",
                        f"守卫三：'{spec_name}' 同根兄弟 '{carrier}' 存在活跃修复"
                        f"——跳过本轮派发，保持 ready",
                    )
                    suppressed.add((spec_name, agent_type))
                    continue

            # Update state to in-progress
            if agent_type == "implementer":
                # add-fail-counter-budget D2：派发前预算闸门。
                # 已启动（_run_agent_worker 内已自增计数）的 run 不受此处影响，
                # 仍会跑完 merge；本闸门只在「即将开启新一轮」时校验，避免无限重派。
                # 闸门触发 → 不派发、状态置 blocked + 人工裁决告警，并回滚队列占用。
                if self._check_impl_budget_exhausted(spec_name):
                    with self._queue_lock:
                        self._run_queue.insert(0, entry_to_dispatch)
                        self._active_runs -= 1
                        cnt = self._active_priority_counts.get(base_prio, 0) - 1
                        if cnt <= 0:
                            self._active_priority_counts.pop(base_prio, None)
                        else:
                            self._active_priority_counts[base_prio] = cnt
                        self._active_priorities.discard(base_prio)
                    continue
                # 修复重派时状态已是 implementing（同态转换非法），跳过 transition
                cur_status = (self.state_machine.read_one(spec_name) or {}).get("status")
                if cur_status != "implementing":
                    self.state_machine.transition(spec_name, "implementing")
            elif agent_type == "verifier":
                self.state_machine.transition(spec_name, "testing")

            self.logger.info(
                "pm_engine",
                f"Dispatching {agent_type} for '{spec_name}' (P{priority})",
                {"active_runs": active_count},
            )

            t = threading.Thread(
                target=self._run_agent_worker,
                args=(spec_name, agent_type, priority),
                daemon=True,
                name=f"fenix-{agent_type}-{spec_name}",
            )
            t.start()

    def _run_agent_worker(self, spec_name: str, agent_type: str, priority: int):
        """Worker thread body: run the agent and handle result.

        Always decrements _active_runs and re-triggers queue processing
        in finally, so slots are released even on exceptions.
        priority 参数用于 finally 中从 _active_priorities 移除对应档位。
        """
        try:
            if agent_type == "implementer":
                # add-fail-counter-budget D2：实现 run 启动即递增预算计数并持久化
                # （跨重启有效）。已启动的 run 即使随后触发预算闸门也会照常跑完 merge
                # （沉没成本不浪费），闸门只阻止「新一轮」自动重派。
                self._increment_impl_run_budget_used(spec_name)
                wm = self.agent_runner.worktree_manager
                # 派发前把 spec 目录提交进主树（fix-merge-back-deadlock 根因修复）：
                # 消除「spec 在主树 untracked + 分支 commit 同名路径」导致的 merge-back 冲突。
                wm.ensure_spec_committed(spec_name)
                # 主树健康检查（fix-fenix-token-waste）：dispatch 前自动 stash 主树脏改动，
                # 保证 merge-back 有干净基线；成功后 restore_after_merge 恢复原改动。
                stashed = wm.ensure_clean_tree()
                result = self.agent_runner.run_implementer(spec_name)
                # Read .fenix-run-result.json (worktree first, project root fallback)
                # to determine true status — file is more authoritative than
                # process exit code for semantic success/error.
                impl_result = self._read_implementer_result(spec_name)
                impl_status = None
                impl_error = None
                if impl_result:
                    impl_status = impl_result.get("status")
                    if impl_status == "error":
                        impl_error = impl_result.get("error") or result.error
                    elif impl_status != "success":
                        impl_error = result.error
                is_success = result.success and (
                    impl_status is None or impl_status == "success"
                )
                final_error = impl_error or result.error

                # ── 零变更成功哨（2026-08-28）─────────────────────────
                # 实现器宣称成功但分支零新提交且全程零 Edit/Write 工具调用
                # ＝ 疑似输出截断/空转（CLI 把截断包装成 result/success + exit 0，
                # is_error 三闸失明）。不合并、不推进状态，按失败重派；
                # 连续 3 次零变更 → blocked 交人工。
                if is_success and self._implementer_zero_change(spec_name, result):
                    attempts = 0
                    spec_entry = self.state_machine.read_one(spec_name) or {}
                    try:
                        attempts = int(spec_entry.get("_zero_change_attempts", 0) or 0) + 1
                    except (TypeError, ValueError):
                        attempts = 1
                    err_note = ("实现器零变更报成功（疑似输出截断/空转）— "
                                "不合并不推进，重派实现")
                    updates: dict = {
                        "status": "ready",
                        "error": err_note + f"（第 {attempts} 次）",
                        "_zero_change_attempts": attempts,
                    }
                    if attempts >= 3:
                        updates["status"] = "blocked"
                        updates["tester_run"] = None
                        updates["error"] = ("实现器连续 3 次零变更报成功 — 已 blocked，"
                                            "需人工检查任务书/上下文/网关稳定性")
                    self.state_machine.update_spec(spec_name, updates)
                    self.logger.error(
                        "pm_engine",
                        f"零变更成功哨触发 '{spec_name}'（第 {attempts} 次）— "
                        f"run={result.run_id}",
                    )
                    if attempts < 3:
                        self._enqueue_front(spec_name, "implementer")
                    return

                # ── 交付物存在性守卫（add-implementer-deliverable-gate，D1/D3）──
                # 实现器宣称成功，但 SPEC 声明的核心交付物可能未真正落地
                # （v2-config-page 事故：agent 报成功但 config.json 未创建，0/11 验证全败）。
                # 在 merge 之前做纯文件系统存在性校验（校验基准为实现分支提交，
                # worktree 已在 run_implementer 内清理，仅分支留存），缺件则不合并、
                # 不推进状态，按失败重派并带精准缺件清单；连续 3 次封顶 → blocked 升级告警。
                if is_success:
                    missing = self._deliverable_gate_missing(spec_name, result)
                    if missing:
                        spec_entry = self.state_machine.read_one(spec_name) or {}
                        prev_retries = 0
                        try:
                            prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
                        except (TypeError, ValueError):
                            prev_retries = 0
                        retries = prev_retries + 1
                        max_r = self._get_config("agents.max_retries", 3)
                        missing_q = "、".join(missing)
                        err_note = (f"交付物守卫：缺件 [{missing_q}] — 不合并不推进，"
                                    f"重派实现补齐（第 {retries} 次）")
                        updates: dict = {
                            "status": "ready",
                            "error": err_note,
                            "_retry_count": retries,
                        }
                        if retries >= max_r:
                            updates["status"] = "blocked"
                            updates["tester_run"] = None
                            updates["error"] = (
                                f"交付物守卫连续 {max_r} 次缺件 [{missing_q}] — 已 blocked，"
                                f"需人工检查任务书声明与实际落地差异"
                            )
                        self.state_machine.update_spec(spec_name, updates)
                        self.logger.error(
                            "pm_engine",
                            f"交付物守卫触发 '{spec_name}'（缺件 {missing_q}）— "
                            f"run={result.run_id}",
                        )
                        if updates["status"] != "blocked":
                            self._enqueue_front(spec_name, "implementer")
                        return

                if is_success:
                    # 计数对账（fix-budget-counting-semantics D3）：守卫放行/merge
                    # 收工后回读 used 与正常收工 run 数比对，偏差记 WARNING。
                    self._reconcile_impl_budget(spec_name)
                    # Merge worktree branch back into main tree before advancing state.
                    # worktree 已被 agent_runner 清理，但分支仍保留（success 路径不删分支），
                    # 所以用分支名直接 merge。
                    merge_ok = True
                    merge_error = ""
                    if result.branch:
                        merge_ok, merge_error = wm.merge_back_from_branch(result.branch)

                    if not merge_ok:
                        # merge 失败：指纹熔断（fix-fenix-token-waste）。
                        # 同一错误指纹连续失败 ≥ 阈值 → spec 进入 blocked 停止自动重试，
                        # 避免「根因不消除 → 全量重跑 → 再败」的无限烧钱循环。
                        spec_entry = self.state_machine.read_one(spec_name)
                        max_r = self._get_config("agents.max_retries", 3)
                        fp = self._merge_fingerprint(merge_error)
                        prev_fp = spec_entry.get("_merge_fp")
                        try:
                            prev_streak = int(spec_entry.get("_merge_streak", 0) or 0)
                        except (TypeError, ValueError):
                            prev_streak = 0
                        streak = prev_streak + 1 if prev_fp == fp else 1
                        final_error = f"Merge-back failed (fp={fp}): {merge_error}"
                        breaker_threshold = self._get_config("agents.merge_breaker_threshold", 2)
                        if streak >= breaker_threshold:
                            self.state_machine.transition(spec_name, "blocked")
                            self.state_machine.update_spec(spec_name, {
                                "error": final_error,
                                "_merge_fp": fp,
                                "_merge_streak": streak,
                                "_retry_count": 0,
                            })
                            self.logger.error(
                                "pm_engine",
                                f"Circuit breaker tripped for '{spec_name}' (fp={fp}) — spec blocked",
                            )
                        else:
                            try:
                                prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
                            except (TypeError, ValueError):
                                prev_retries = 0
                            retries = prev_retries + 1
                            self.state_machine.update_spec(spec_name, {
                                "status": "ready",
                                "error": final_error,
                                "_merge_fp": fp,
                                "_merge_streak": streak,
                                "_retry_count": retries,
                            })
                            self.logger.warning(
                                "pm_engine",
                                f"Retry {retries}/{max_r} for '{spec_name}' (merge-back failed)",
                            )
                    else:
                        # 恢复 dispatch 前自动 stash 的主树改动（冲突时保留 stash，不阻塞）
                        conflict_files = []
                        if stashed:
                            _ok, conflict_files = wm.restore_after_merge()
                        self.state_machine.transition(spec_name, "implemented")
                        self.state_machine.update_spec(spec_name, {
                            "implementer_run": result.run_id,
                            # 记录真实实现分支（带时间戳后缀）：push 时按此分支推送，
                            # 否则回退 fenix/<spec> 不存在导致 auto-push 全部失败。
                            "branch": getattr(result, "branch", None) or None,
                            "error": None,
                            "_retry_count": 0,
                            "_merge_fp": None,
                            "_merge_streak": 0,
                            # 派发成功即清零锁冲突计数（improve-run-lifecycle-governance D5）
                            **self._clear_dispatch_conflict(spec_name),
                        })
                        # pop 冲突自愈后：被丢弃的 stash 改动文件清单写入 error 字段，
                        # 触发 admin 告警（stash 条目保留、可 git stash show 找回，
                        # 不阻塞 merge-back 与状态推进）。须放在上面 update_spec(error=None)
                        # 之后，避免被清空。见 fix-stashpop-deadlock。
                        if conflict_files:
                            self._report_stash_pop_conflict(spec_name, conflict_files)
                        # 写侧确定性回写：把已完成的任务勾选同步进主树 tasks.md
                        # （add-task-progress-sync）。任何异常都不阻塞 run 终态主流程。
                        try:
                            self._sync_task_progress(spec_name)
                        except Exception as e:
                            self.logger.warning(
                                "pm_engine",
                                f"任务进度回写未成功 '{spec_name}'（非阻塞）: {e}",
                            )
                        # 恢复重派遗产回收（add-recovery-legacy-check 1.3）：后继 run 成功
                        # merge 后，该 spec 的遗产已被收编/不再需要，consume_legacy 触发回收。
                        # worktree 物理回收在 run_implementer 的 cleanup（成功路径保留分支、
                        # 由 merge 前已清理）完成后由既有路径处理；此处仅清内存态遗产登记，
                        # 使清扫器不再对其豁免。
                        try:
                            wm.consume_legacy(spec_name)
                        except Exception as e:
                            self.logger.warning(
                                "pm_engine",
                                f"consume_legacy 失败 '{spec_name}'（非阻塞）: {e}",
                            )
                        # Immediately queue verifier at FRONT so it runs next
                        self._enqueue_front(spec_name, "verifier")
                        self.logger.info("pm_engine", f"Implement done, verifier queued for '{spec_name}'")
                else:
                    # ── 死亡 run 豁免（fix-budget-counting-semantics D1）──────
                    # 无收工结果产出（.fenix-run-result.json 缺失）＝ run 异常
                    # 死亡（进程消失/零输出/网关链路耗尽）：回退本次启动的计数。
                    # 有收工结果的正常失败（impl_status=error）不豁免——既有
                    # 「正常失败仍计数」语义不变。
                    if impl_status is None:
                        self._exempt_dead_run_budget(
                            spec_name,
                            f"no run-result file (error={str(final_error)[:80]})",
                        )
                    # ── provider 熔断拦截（fix-stashpop-deadlock：provider-fault-fuse） ──
                    # 熔断期派发失败（error 含 "provider circuit open"）属「provider 故障」，
                    # 不是 spec 自身问题：不计入 _retry_count / _merge_streak、不翻转状态机、
                    # 不创建新 worktree/autostash（design D5）。spec 保持 implementing 原状，
                    # 由冷却结束后的既有轮询/事件机制自然重排；持续过久由 admin_monitor
                    # 按 stuck 规则唤起人工（充值/换模型）。
                    if final_error and "provider circuit open" in final_error:
                        self.logger.warning(
                            "pm_engine",
                            f"Provider circuit open for '{spec_name}' — holding state, "
                            f"no retry/state flip: {final_error}",
                        )
                        # 写入 error 供 dashboard/admin 可见，但不翻转状态、不增 retry
                        self.state_machine.update_spec(spec_name, {
                            "error": final_error,
                        })
                    else:
                        # Retry or mark error
                        spec_entry = self.state_machine.read_one(spec_name)
                        try:
                            prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
                        except (TypeError, ValueError):
                            prev_retries = 0
                        retries = prev_retries + 1
                        max_r = self._get_config("agents.max_retries", 3)
                        if retries >= max_r:
                            self.state_machine.update_spec(spec_name, {
                                "status": "ready",
                                "error": final_error,
                                "_retry_count": 0,
                            })
                            self.logger.error(
                                "pm_engine",
                                f"All retries exhausted for '{spec_name}'",
                            )
                            # 3.2 行动性同状态更新补发（fix-dispatch-orphan D1）：
                            # 失败落回 ready 后可能无后续事件触达（daemon 重启间隙 /
                            # 轮询节流），立即重新排队实现器，避免滞留为孤儿。
                            self._enqueue(spec_name, "implementer")
                        else:
                            self.state_machine.update_spec(spec_name, {
                                "status": "ready",
                                "error": final_error,
                                "_retry_count": retries,
                            })
                            self.logger.warning(
                                "pm_engine",
                                f"Retry {retries}/{max_r} for '{spec_name}'",
                            )

            elif agent_type == "verifier":
                self._run_verification_pipeline(spec_name)

        except Exception as e:
            self.logger.error("pm_engine", f"Agent run exception: {e}")
            # 派发/执行异常必须回滚滞留中间态的 spec（fix: 伪 bug 卡死根因）。
            # 此前只记日志：日限额耗尽等异常使 run 从未启动，spec 却已滞留在
            # implementing/testing，无 run 痕迹、永久卡死。
            self._rollback_failed_dispatch(spec_name, agent_type, e)
        finally:
            # Release the concurrency slot and try to dispatch more work
            with self._queue_lock:
                self._active_runs -= 1
                # 宽松优先级：按优先级计数释放，仅当该档最后一个 run 结束才移除该档，
                # 避免多档并发时把仍活动的档位误移除（fix：多档并发）
                cnt = self._active_priority_counts.get(priority, 0) - 1
                if cnt <= 0:
                    self._active_priority_counts.pop(priority, None)
                    self._active_priorities.discard(priority)
                else:
                    self._active_priority_counts[priority] = cnt
            self._process_queue()

    @staticmethod
    def _dispatch_backoffed(spec: dict) -> bool:
        """判断 spec 是否处于派发退避期（派发基础设施失败后防振荡）。

        返回 True 表示本轮不可派发；条目保留在队列中，退避过期后自然恢复，
        配合 periodic full_scan 的 recovery 兜底最多延迟一个扫描周期。
        """
        until = spec.get("_dispatch_backoff_until")
        if not until:
            return False
        try:
            return float(until) > datetime.now(timezone.utc).timestamp()
        except (TypeError, ValueError):
            return False

    def _rollback_failed_dispatch(self, spec_name: str, agent_type: str, exc: Exception):
        """派发/执行异常时回滚滞留中间态的 spec 到可重试态（fix: 伪 bug 卡死）。

        - implementer 失败：implementing → ready，清空 run 字段；error 置 None 以便
          full_scan 的 spec_ready recovery 再次拾起（错误详情记入 _last_dispatch_error）。
        - verifier 失败：testing → implemented，清 tester_run；实现保留（不重实现）。
        设置 _dispatch_backoff_until（5 分钟）吸收 inotify 触发的即时重派振荡；
        重试由队列条目 + full_scan recovery 兜底（最长 30 分钟窗口）。
        """
        try:
            spec_entry = self.state_machine.read_one(spec_name)
            if not spec_entry:
                return
            status = spec_entry.get("status")
            backoff_until = int(datetime.now(timezone.utc).timestamp()) + 300
            if agent_type == "verifier" and status == "testing":
                self.state_machine.update_spec(spec_name, {
                    "status": "implemented",
                    "tester_run": None,
                    "error": f"Verification infrastructure failure (retryable): {exc}",
                    "_dispatch_backoff_until": backoff_until,
                })
                self.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' testing → implemented (verifier never started): {exc}",
                )
                self._enqueue(spec_name, "verifier")
            elif agent_type == "implementer" and status == "implementing":
                # 死亡 run 豁免（fix-budget-counting-semantics D1）：异常路径＝
                # run 无收工结果产出（进程消失/零输出/网关链路耗尽），回退本次
                # 启动的预算计数。计数在 worker 启动处先行递增，此处补偿回退。
                self._exempt_dead_run_budget(
                    spec_name, f"dispatch exception: {str(exc)[:80]}"
                )
                self.state_machine.update_spec(spec_name, {
                    "status": "ready",
                    "implementer_run": None,
                    "tester_run": None,
                    "branch": None,
                    "error": None,
                    "_last_dispatch_error": f"Implementation dispatch failed (retryable): {exc}",
                    "_dispatch_backoff_until": backoff_until,
                })
                self.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' implementing → ready (implementer never started): {exc}",
                )
                self._enqueue(spec_name, "implementer")
        except Exception as e2:
            self.logger.error("pm_engine", f"State rollback failed for '{spec_name}': {e2}")

    def _report_stash_pop_conflict(self, spec_name: str, conflict_files: list) -> None:
        """pop 冲突自愈后上报被丢弃的 stash 改动文件清单（fix-stashpop-deadlock）。

        主树已通过 checkout HEAD + reset 自愈回到干净可写状态，merge 结果不丢失、
        状态正常推进到 implemented；此处仅把「被丢弃的 stash 改动文件」写入 spec 的
        error 字段（覆盖 None），利用既有 admin_monitor distressed 规则触发告警，
        提示人工用 ``git stash show`` 找回内容。零新增持久化状态。

        error 文本格式（供 dashboard/admin 可读）：``stash pop conflict: files=[...]``
        """
        if not conflict_files:
            return
        msg = f"stash pop conflict: files={conflict_files}"
        try:
            self.state_machine.update_spec(spec_name, {"error": msg})
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"stash pop conflict 上报失败 '{spec_name}'（非阻塞）: {e}",
            )
        self.logger.error(
            "pm_engine",
            f"'{spec_name}' {msg} —— stash 保留，可用 git stash show 找回被丢弃改动",
        )

    @staticmethod
    def _merge_fingerprint(error: str) -> str:
        """对 merge 错误计算稳定指纹（fix-fenix-token-waste）。

        归一化：整体去空白后取 sha1 前 12 位。git 对同一根因的报错逐字节一致，
        因此可用字符串归一化哈希；不同根因会得到不同指纹。
        """
        norm = "".join((error or "").split())
        return hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:12]

    # ── Verification Pipeline ─────────────────────────────────────

    # ── 环境性失联门禁（verify-environment-sanity-gate）───────────



    def _run_verification_pipeline(self, spec_name: str):
        """执行三步验证流水线。

        步骤1: Planner Agent 生成测试场景
        步骤2: VerifyEngine 并行执行场景（DOM断言 + 视觉对比）
        步骤3: Planner Agent 判定结果

        新流程失败时自动降级到旧版 verifier。
        """
        use_new_flow = self._get_config("agents.use_new_verifier", True)

        if not use_new_flow:
            self._run_legacy_verification(spec_name)
            return

        try:
            self._run_three_stage_verification(spec_name)
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"新验证流程失败 '{spec_name}': {e}，降级到旧版 verifier",
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

    # ── 应用可达性自愈（最终用户验证必选）────────────────────────



    # ── 场景集冻结（add-verify-scenario-freeze）────────────────────────



    # ── 交互契约覆盖（add-interaction-contract-and-per-assert-triage 1.3）──











    # ── Reporting ──────────────────────────────────────────────────

    def generate_report(self) -> str:
        """Generate a project status report."""
        all_specs = self.state_machine.read_all()

        if not all_specs:
            return "📋 No SPECs yet. Create one with /fenix:new"

        # Count by status
        counts = {}
        for entry in all_specs.values():
            s = entry.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        lines = [
            f"## Fenix Project Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "### Summary",
        ]

        status_icons = {
            "drafted": "📝",
            "ready": "📌",
            "implementing": "🔨",
            "implemented": "🧪",
            "testing": "🔍",
            "verified": "✅",
            "bug-found": "🐛",
            "done": "🎯",
            "pushed": "🚀",
        }

        for name, entry in sorted(all_specs.items(),
                                   key=lambda x: x[1].get("priority", 999)):
            status = entry.get("status", "unknown")
            icon = status_icons.get(status, "❓")
            priority = entry.get("priority", "?")
            lines.append(f"- {icon} **{name}** (P{priority}): {status}")

        lines.append("")
        lines.append("### Stats")
        lines.append(f"- Total: {len(all_specs)}")
        for status, count in sorted(counts.items()):
            icon = status_icons.get(status, "❓")
            lines.append(f"- {icon} {status}: {count}")

        return "\n".join(lines)

    def generate_daily_report(self):
        """Generate daily report and append to PROJECT_LOG.md."""
        report = self.generate_report()

        log_path = self.project_root / "PROJECT_LOG.md"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n\n{report}\n")

        self.logger.info("pm_engine", "Daily report generated")

    # ── Push Gate ──────────────────────────────────────────────────

    def get_pushable_specs(self):
        """Get all done SPECs awaiting push approval."""
        return self.state_machine.get_by_status("done")

    # ── Push backoff helpers (design D3) ───────────────────────────

    @staticmethod
    def _is_push_backoffed(spec: dict) -> bool:
        """判断 spec 是否在 push 退避期内（error 含 next_retry_at 且未到期）。

        退避标记约定：error 文本中包含 `[push_backoff next_retry_at=<unix_ts>]`。
        设计原则（D3）：退避期内 recovery 重放直接跳过，不发 push 命令。
        """
        error = spec.get("error") or ""
        m = re.search(r"\[push_backoff next_retry_at=(\d+)\]", error)
        if not m:
            return False
        try:
            return float(m.group(1)) > datetime.now(timezone.utc).timestamp()
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _get_push_retry_count(spec: dict) -> int:
        """从 error 文本中提取 push 连续重试次数。"""
        error = spec.get("error") or ""
        m = re.search(r"\[push_attempts=(\d+)\]", error)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                pass
        return 0

    def _signal_push_failed(self, spec_name: str, detail: str):
        """推送超限升级为 push_failed 困境信号（severity=major）写入 admin store。"""
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self.project_root, self.logger)
        try:
            store.append({
                "kind": SIGNAL,
                "signal_type": "push_failed",
                "spec": spec_name,
                "severity": "major",
                "description": (f"SPEC '{spec_name}' 自动推送连续失败达到上限，"
                                f"已停止自动重试，需人工介入"),
                "evidence": detail,
                "recommended_action": ("检查远端仓库权限与分支状态；"
                                       "手动 git push origin main 后把 spec 标为 pushed"),
            })
            self.logger.error(
                "pm_engine",
                f"push_failed 信号已写入 admin store: '{spec_name}'",
            )
        except Exception as e:
            self.logger.error(
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
                capture_output=True, text=True, timeout=30,
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
                capture_output=True, text=True, timeout=10,
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
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return True, ""
            error = (
                result.stderr.strip()
                or result.stdout.strip()
                or f"exit code {result.returncode}"
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
        """
        spec = self.state_machine.read_one(spec_name)
        if not spec or spec.get("status") != "done":
            self.logger.warning(
                "pm_engine", f"Cannot push '{spec_name}': not in done state"
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
        self.logger.info(
            "pm_engine", f"Pushing main for '{spec_name}' (main-first)"
        )
        main_ok, main_err = self._git_push_ref("main")

        if not main_ok:
            self._handle_push_failure(spec_name, spec, main_err, "main")
            return False

        self.logger.info("pm_engine", f"Main push succeeded for '{spec_name}'")

        # ── D1: 分支尽力推送（best-effort，失败不阻断 pushed） ──
        branch = self._resolve_push_branch(spec_name, spec)
        self._push_branch_best_effort(spec_name, branch)

        # ── 推送成功 → 推进 pushed，清 error + 退避标记 ──
        self.state_machine.transition(spec_name, "pushed")
        self.state_machine.update_spec(spec_name, {"error": None})
        self._append_project_log(
            f"🚀 SPEC pushed: **{spec_name}** (main pushed, branch: {branch})"
        )
        self.logger.info(
            "pm_engine",
            f"SPEC pushed: {spec_name} (main ok, branch={branch})",
        )
        return True

    def _handle_push_failure(
        self, spec_name: str, spec: dict, error_msg: str, ref: str
    ):
        """处理推送失败：记录退避/重试状态；超限升级 push_failed 信号（D3）。"""
        max_retries = int(
            self._get_config("pm.push.max_retries", 3) or 3
        )
        backoff_seconds = [300, 900]  # 默认指数退避：5 分钟、15 分钟
        cfg_backoff = self._get_config("pm.push.retry_backoff_seconds")
        if isinstance(cfg_backoff, list) and len(cfg_backoff) >= 2:
            backoff_seconds = cfg_backoff

        attempts = self._get_push_retry_count(spec) + 1
        error_base = f"git push failed ({ref}): {error_msg}"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        if attempts >= max_retries:
            # 超限：发 push_failed 信号，停止自动重试
            detail = (
                f"连续 {attempts} 次推送失败（{ref}），"
                f"已达上限 {max_retries}，已停止自动重试"
            )
            self._signal_push_failed(spec_name, detail)
            final_error = (
                f"{error_base} [push_attempts={attempts}] "
                f"[push_failed — 已停止自动重试]"
            )
            self.state_machine.update_spec(spec_name, {"error": final_error})
            spec["error"] = final_error  # 同步本地引用供后续读取
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
            self.state_machine.update_spec(spec_name, {"error": final_error})
            spec["error"] = final_error  # 同步本地引用供后续读取
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

        self.logger.info(
            "pm_engine", f"Auto-approving '{spec_name}' (approve_mode=auto)"
        )
        return self.approve_push(spec_name)

    # ── 残痕回填（design D4）────────────────────────────────────

    def backfill_push_residuals(self) -> dict:
        """幂等回填清理：遍历 pushed 终态且 error 以 'git push failed' 开头的 spec。

        用 D2 的 SHA 比对验证内容已在远端后清 error；验证不到的保留并列日志。
        供手动调用 + tests 覆盖。

        验证口径（design D4）：优先比对 spec 自身分支在远端的 SHA（内容确定已在
        远端即清痕）；若分支已不可查，则回退比对 main（main 承载内容亦视为已推送）。

        Returns:
            {"cleaned": [spec_name, ...], "kept": [{"spec": name, "error": msg}, ...]}
        """
        cleaned = []
        kept = []
        all_specs = self.state_machine.read_all() or {}
        for name, entry in all_specs.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("status") != "pushed":
                continue
            error = str(entry.get("error") or "")
            if not error.startswith("git push failed"):
                continue

            # D2/D4: 优先用 spec 自身分支的远端 SHA 验证内容已在远端
            branch = entry.get("branch") or f"fenix/{name}"
            verified = False
            verify_note = ""
            remote_branch = self._remote_branch_sha(f"refs/heads/{branch}")
            if remote_branch:
                verified = True
                verify_note = f"branch SHA {remote_branch[:12]}"
            else:
                # 回退：main 在远端即视为内容已推送
                remote_main = self._remote_branch_sha("refs/heads/main")
                if remote_main:
                    verified = True
                    verify_note = f"main SHA {remote_main[:12]}"

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
                ["git", "for-each-ref", "--format=%(refname:short)",
                 "--sort=-committerdate", f"refs/heads/{plain}-*"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=30,
            )
            if res.returncode == 0:
                sep = plain + "-"
                for cand in res.stdout.splitlines():
                    cand = cand.strip()
                    if cand.startswith(sep) and cand[len(sep):].isdigit():
                        return cand
        except Exception:
            pass
        return plain

    # ── Helpers ────────────────────────────────────────────────────

    def _append_project_log(self, message: str):
        """Append a timestamped message to PROJECT_LOG.md."""
        log_path = self.project_root / "PROJECT_LOG.md"
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

    def _stuck_elapsed_minutes(self, spec_name: str, now: datetime,
                               updated: datetime) -> float:
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
                f"Live-attempt probe failed for '{spec_name}' "
                f"(treating as no live child): {e}",
            )
            return False
        return result is True

    def _ready_stall_threshold_minutes(self) -> float:
        """假就绪巡检阈值：pm.recovery.ready_stall_threshold_minutes（默认 20）。"""
        try:
            return max(0.0, float(self._get_config(
                "pm.recovery.ready_stall_threshold_minutes",
                DEFAULT_READY_STALL_THRESHOLD_MINUTES)))
        except (TypeError, ValueError):
            return float(DEFAULT_READY_STALL_THRESHOLD_MINUTES)

    def _spec_has_recent_run_activity(self, spec_name: str, window_minutes: float) -> bool:
        """窗口内该 spec 是否有任何 run 产物活动（impl/verify/planner/admin）。

        「期间无成功派发」的代理判据：窗口内没有任何 run 流文件被写入即视为
        无派发活动（失败的 run 也算活动——有活动说明调度仍在工作，不是假就绪）。
        """
        runs_dir = self.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return False
        cutoff = time.time() - max(0.0, window_minutes) * 60
        try:
            for prefix in ("impl", "verify", "planner-plan", "planner-judge", "admin"):
                for p in runs_dir.glob(f"{prefix}-{spec_name}-*.jsonl"):
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
        if not deps or deps == "null":
            return True

        # deps is a comma-separated list of SPEC names
        dep_names = [d.strip() for d in str(deps).split(",") if d.strip()]
        if not dep_names:
            return True

        for dep_name in dep_names:
            dep_spec = self.state_machine.read_one(dep_name)
            if not dep_spec:
                self.logger.warning("pm_engine", f"Dependency '{dep_name}' not found for '{spec_name}'")
                return False
            dep_status = dep_spec.get("status", "")
            if dep_status not in ("done", "pushed", "implemented", "verified"):
                self.logger.info(
                    "pm_engine",
                    f"'{spec_name}' blocked: dependency '{dep_name}' is '{dep_status}' (need done/pushed/implemented/verified)",
                )
                return False

        return True

    # ── Blocker Detection & Health Reporting ───────────────────────

    def check_blockers(self) -> dict:
        """
        Scan all SPECs for blocking/stuck conditions and generate a health report.
        Called periodically by the EventBus full-scan cycle.

        Returns a dict with blocker details if any found.
        """
        self._last_blocker_check = datetime.now(timezone.utc)
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
                try:
                    u = datetime.fromisoformat(
                        (entry.get("updated") or "").replace("Z", "+00:00"))
                    v_elapsed = int((now - u).total_seconds() / 60)
                except (ValueError, TypeError):
                    v_elapsed = 0
                blockers.append({
                    "spec": name,
                    "status": status,
                    "reason": f"卡在 verified 状态 {v_elapsed} 分钟（应为瞬态，需要推进到 done）",
                    "error": entry.get("error") or "No error recorded",
                    "elapsed_minutes": v_elapsed,
                })
                continue

            # Check if stuck in an active state
            if status in ("implementing", "testing"):
                try:
                    updated_str = entry.get("updated", "")
                    if updated_str:
                        updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        elapsed = self._stuck_elapsed_minutes(
                            name, now, updated)
                        if elapsed > stuck_threshold_minutes:
                            blockers.append({
                                "spec": name,
                                "status": status,
                                "reason": f"Stuck in '{status}' for {int(elapsed)} minutes (threshold: {stuck_threshold_minutes}m)",
                                "error": entry.get("error") or "No error recorded",
                                "elapsed_minutes": int(elapsed),
                            })
                except (ValueError, TypeError):
                    pass

            # Check for persistent errors
            error = entry.get("error")
            if error and status == "ready":
                try:
                    retries = int(entry.get("_retry_count", 0) or 0)
                except (TypeError, ValueError):
                    retries = 0
                if retries > 0:
                    warnings.append({
                        "spec": name,
                        "status": status,
                        "reason": f"Failed {retries} retry attempts, last error: {error[:100]}",
                    })

            # Check for ready-but-starving (never been picked up)
            if status == "ready":
                try:
                    updated_str = entry.get("updated", "")
                    if updated_str:
                        updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        elapsed = (now - updated).total_seconds() / 60
                        if elapsed > stuck_threshold_minutes * 2:
                            warnings.append({
                                "spec": name,
                                "status": status,
                                "reason": f"Waiting in ready queue for {int(elapsed)} minutes — possible queue starvation",
                                "elapsed_minutes": int(elapsed),
                            })
                        # 假就绪巡检（improve-run-lifecycle-governance D6）：ready 滞留
                        # 超过 ready_stall_threshold_minutes 且期间无派发活动 → 阻塞项。
                        # 退避期内的 spec（_dispatch_backoff_until 未到期）有意等待，不算滞留。
                        stall_threshold = self._ready_stall_threshold_minutes()
                        if (elapsed > stall_threshold
                                and not self._dispatch_backoffed(entry)
                                and not self._spec_has_recent_run_activity(
                                    name, stall_threshold)):
                            blockers.append({
                                "spec": name,
                                "status": status,
                                "reason": (
                                    f"假就绪滞留：ready 超过 {int(elapsed)} 分钟且期间无"
                                    f"派发活动（阈值 {stall_threshold:.0f}m）"
                                ),
                                "error": entry.get("error") or "No error recorded",
                                "elapsed_minutes": int(elapsed),
                            })
                except (ValueError, TypeError):
                    pass

        # Log and auto-recover
        if blockers:
            self.logger.warning(
                "pm_engine",
                f"BLOCKER CHECK: {len(blockers)} blocking, {len(warnings)} warnings",
                {"blockers": blockers, "warnings": warnings},
            )
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
                        spec_name, "auto-recovery deferred (live child present)")
                    continue
                self.logger.info(
                    "pm_engine",
                    f"Auto-recovering stuck SPEC: {spec_name} (was {stuck_status})",
                )
                if stuck_status == "implementing":
                    # 实现卡住且可能从未运行（implementer_run=null）：不得伪标 implemented
                    # 直接推给 verifier——「无实现即验证」会产出伪 bug 并派生 fix 级联
                    # （本事故 5 代 fix 链的肇因）。回 ready 重新排队实现器。
                    # 死亡 run 豁免（fix-budget-counting-semantics D1）：恢复链路在此
                    # 确认 run 异常死亡（滞留 implementing 超阈值且无存活子进程＝无收工
                    # 结果产出），回退本次启动的预算计数并递增豁免侧车。
                    self._exempt_dead_run_budget(
                        spec_name,
                        f"auto-recovery: stuck implementing "
                        f"{b['elapsed_minutes']}m, no live child (no run-result)",
                    )
                    self.state_machine.update_spec(spec_name, {
                        "status": "ready",
                        "implementer_run": None,
                        "tester_run": None,
                        "branch": None,
                        "error": f"Auto-recovered from stuck implementing ({b['elapsed_minutes']} min)",
                    })
                    self._enqueue(spec_name, "implementer")
                    self.register_recovery_watch(
                        spec_name, f"auto-recovered from stuck {stuck_status}")
                elif stuck_status == "testing":
                    # 验证卡住：实现已完成，回 implemented 重新派发 verifier
                    self.state_machine.update_spec(spec_name, {
                        "status": "implemented",
                        "tester_run": None,
                        "error": f"Auto-recovered from stuck testing ({b['elapsed_minutes']} min)",
                    })
                    self._enqueue(spec_name, "verifier")
                    self.register_recovery_watch(
                        spec_name, f"auto-recovered from stuck {stuck_status}")
                # verified：full_scan 已周期性重触发 spec_verified 走放行门禁
                # 幂等重试；此处不得回滚到 implemented —— 否则每轮全量重跑
                # verifier，形成验证烧钱循环。仅上报，等门禁条件满足。

        return {"blockers": blockers, "warnings": warnings, "checked_at": now.isoformat()}

    def _write_blocker_report(self, blockers: list, warnings: list):
        """Write a blocker report to PROJECT_LOG.md, throttled to once per hour."""
        now = datetime.now(timezone.utc)

        # Throttle: don't write more than once per hour
        if self._last_blocker_report_time:
            elapsed = (now - self._last_blocker_report_time).total_seconds()
            if elapsed < 3600:
                return

        self._last_blocker_report_time = now

        lines = [
            f"\n### ⚠️ Blocker Report — {now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
        ]

        if blockers:
            lines.append(f"**{len(blockers)} blocker(s) detected:**")
            lines.append("")
            for b in blockers:
                lines.append(f"- 🔴 **{b['spec']}**: {b['reason']}")
                lines.append(f"  - Status: `{b['status']}`, Elapsed: {b['elapsed_minutes']} minutes")
                lines.append(f"  - Last error: {b['error'][:120]}")
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

        lines.append(f"*Next check: ~{self._get_config('schedule.poll_interval_minutes', 30)} minutes*")
        lines.append("")

        # Append to project log
        log_path = self.project_root / "PROJECT_LOG.md"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

        self.logger.info("pm_engine", "Blocker report written to PROJECT_LOG.md")

    def get_health_summary(self) -> str:
        """Return a human-readable one-line health summary for /fenix-status."""
        all_specs = self.state_machine.read_all()
        if not all_specs:
            return "📋 尚无 SPEC"

        total = len(all_specs)
        done = sum(1 for e in all_specs.values() if e.get("status") in ("done", "pushed"))
        active = sum(1 for e in all_specs.values() if e.get("status") in ("implementing", "testing"))
        blocked = sum(1 for e in all_specs.values()
                      if e.get("status") == "ready" and e.get("error"))

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


    # ── 组合组件委托（阶段 4：family/budget 已迁组件，门面保持调用路径）──

    def _resolve_fix_spec_name(self, spec_name: str):
        return self._family._resolve_fix_spec_name(spec_name)

    def _ensure_fix_spec_files(self, fix_spec_name: str, parent_spec_name: str):
        return self._family._ensure_fix_spec_files(fix_spec_name, parent_spec_name)

    @staticmethod
    def _fix_prefix_depth(name: str) -> int:
        return FamilyGovernor._fix_prefix_depth(name)

    @staticmethod
    def _fix_strip_all(name: str) -> str:
        return FamilyGovernor._fix_strip_all(name)

    def _family_width(self, child_name: str) -> int:
        return self._family._family_width(child_name)

    def _family_waiver_set(self, spec_name: str) -> bool:
        return self._family._family_waiver_set(spec_name)

    def _consume_family_waiver(self, spec_name: str) -> bool:
        return self._family._consume_family_waiver(spec_name)

    def _family_gate_blocked(self, parent_name: str, child_name: str) -> bool:
        return self._family._family_gate_blocked(parent_name, child_name)

    @staticmethod
    def _is_fix_spec(name: str) -> bool:
        return FamilyGovernor._is_fix_spec(name)

    @staticmethod
    def _same_root(name_a: str, name_b: str) -> bool:
        return FamilyGovernor._same_root(name_a, name_b)

    def _same_root_siblings(self, spec_name: str) -> list:
        return self._family._same_root_siblings(spec_name)

    def _sibling_repair_active(self, spec_name: str, my_enqueued_at: float = None) -> str:
        return self._family._sibling_repair_active(spec_name, my_enqueued_at)

    def _sibling_has_live_agent(self, spec_name: str) -> bool:
        return self._family._sibling_has_live_agent(spec_name)

    def _has_non_terminal_child_fix(self, spec_name: str) -> str:
        return self._family._has_non_terminal_child_fix(spec_name)

    def _signal_family_explosion(self, parent_name: str, child_name: str, detail: str):
        return self._family._signal_family_explosion(parent_name, child_name, detail)

    def _do_spec_bug_found(self, spec_name: str):
        return self._family._do_spec_bug_found(spec_name)

    def _do_legacy_fix_spec_bug_found(self, spec_name: str):
        return self._family._do_legacy_fix_spec_bug_found(spec_name)

    def _inject_verify_fix_task(self, spec_name: str, fail_rounds: int):
        return self._family._inject_verify_fix_task(spec_name, fail_rounds)

    def _send_human_escalation_alert(
        self, spec_name: str, signal_type: str, severity: str,
        description: str, evidence: str, recommended_action: str,
        trigger: Optional[dict] = None,
    ):
        return self._family._send_human_escalation_alert(spec_name, signal_type, severity, description, evidence, recommended_action, trigger)

    # ── 实现尝试总预算（add-fail-counter-budget D2/D4）──────────────
    def _impl_run_budget(self) -> int:
        return self._budget._impl_run_budget()

    def _increment_impl_run_budget_used(self, spec_name: str) -> int:
        return self._budget._increment_impl_run_budget_used(spec_name)

    def _budget_exempt_alert_threshold(self) -> int:
        return self._budget._budget_exempt_alert_threshold()

    def _exempt_dead_run_budget(self, spec_name: str, reason: str) -> None:
        return self._budget._exempt_dead_run_budget(spec_name, reason)

    def _alert_budget_exempt_loop(self, spec_name: str, exempt: int) -> None:
        return self._budget._alert_budget_exempt_loop(spec_name, exempt)

    def _reconcile_impl_budget(self, spec_name: str) -> None:
        return self._budget._reconcile_impl_budget(spec_name)

    def _count_normal_completed_impl_runs(self, spec_name: str) -> int:
        return self._budget._count_normal_completed_impl_runs(spec_name)

    @staticmethod
    def _run_file_died(path: Path) -> bool:
        return ImplBudget._run_file_died(path)

    def _impl_run_budget_used(self, spec_name: str) -> int:
        return self._budget._impl_run_budget_used(spec_name)

    def _check_impl_budget_exhausted(self, spec_name: str) -> bool:
        return self._budget._check_impl_budget_exhausted(spec_name)

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

    def _read_verify_report(self, spec_name: str) -> dict:
        return self._verification._read_verify_report(spec_name)

    def _handle_env_blocked_inconclusive(self, spec_name: str, report: dict) -> bool:
        return self._verification._handle_env_blocked_inconclusive(spec_name, report)

    def _ensure_app_reachable(self, spec_name: str) -> tuple:
        return self._verification._ensure_app_reachable(spec_name)

    def _rewrite_scenario_port(self, scenarios_path: Path, old_port: int, new_port: int):
        return self._verification._rewrite_scenario_port(scenarios_path, old_port, new_port)

    def _current_verify_round(self, spec_name: str) -> int:
        return self._verification._current_verify_round(spec_name)

    def _apply_scenario_freeze(self, spec_name: str) -> dict:
        return self._verification._apply_scenario_freeze(spec_name)

    def _apply_interaction_contract(self, spec_name: str) -> dict:
        return self._verification._apply_interaction_contract(spec_name)

    def _render_scenario_change_section_to_report(self, spec_name: str) -> None:
        return self._verification._render_scenario_change_section_to_report(spec_name)

    def _run_three_stage_verification(self, spec_name: str):
        return self._verification._run_three_stage_verification(spec_name)

    def _verifier_error_is_infra(self, error_text: str) -> bool:
        return self._verification._verifier_error_is_infra(error_text)

    def _verifier_result_is_stale(self, result, result_path: Path, spec_name: str) -> bool:
        return self._verification._verifier_result_is_stale(result, result_path, spec_name)

    def _implementer_zero_change(self, spec_name: str, result) -> bool:
        return self._verification._implementer_zero_change(spec_name, result)

    def _deliverable_gate_missing(self, spec_name: str, result) -> list:
        return self._verification._deliverable_gate_missing(spec_name, result)

    @staticmethod
    def _normalize_fail_signature(text: str) -> str:
        return VerificationPipeline._normalize_fail_signature(text)

    def _detect_uniform_verify_failure(self, spec_name: str, report: dict) -> bool:
        return self._verification._detect_uniform_verify_failure(spec_name, report)

    def _run_legacy_verification(self, spec_name: str):
        return self._verification._run_legacy_verification(spec_name)

    def _verify_verdict_evidence(self, spec_name: str, retry_judge: bool = False) -> bool:
        return self._verification._verify_verdict_evidence(spec_name, retry_judge)

    def _update_warning_streaks(self, spec_name: str) -> list:
        return self._verification._update_warning_streaks(spec_name)

    def _warning_stale_triage_alert(self, spec_name: str, scenario_ids: list) -> None:
        return self._verification._warning_stale_triage_alert(spec_name, scenario_ids)

    def _ensure_verification_report(self, spec_name: str) -> str | None:
        return self._verification._ensure_verification_report(spec_name)

    def _check_verification_gate(self, spec_name: str) -> str | None:
        return self._verification._check_verification_gate(spec_name)

    def _read_verifier_result(self, result_path: Path) -> str | None:
        return self._verification._read_verifier_result(result_path)

    def _read_planner_result(self, spec_name: str) -> str | None:
        return self._verification._read_planner_result(spec_name)

    def _judge_bugs_declare_env(self, spec_name: str) -> bool:
        return self._verification._judge_bugs_declare_env(spec_name)

    def _handle_judge_env_declared(self, spec_name: str) -> bool:
        return self._verification._handle_judge_env_declared(spec_name)

    def _verdict_violations_path(self, spec_name: str) -> Path:
        return self._verification._verdict_violations_path(spec_name)

    def _write_verdict_violations(self, spec_name: str, violations: list) -> None:
        return self._verification._write_verdict_violations(spec_name, violations)

    def _clear_verdict_violations(self, spec_name: str) -> None:
        return self._verification._clear_verdict_violations(spec_name)

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

