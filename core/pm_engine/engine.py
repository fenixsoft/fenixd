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

from core.dashboard.data import (
    find_impl_run_file,
    get_runs,
    parse_run_task_done,
    record_project_event,
)
from core.pm_engine.family import FamilyGovernor
from core.pm_engine.budget import ImplBudget
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
    FREEZE_ERROR_PREFIX,
    FROZEN_FIELD,
    FROZEN_UNTIL_FIELD,
    START_AFTER_FIELD,
    SpecStatus,
    parse_orig_status,
    parse_utc,
    start_after_pending,
)

# 假就绪巡检：ready 滞留超过该阈值且期间无派发活动 → 阻塞项（design D6）
DEFAULT_READY_STALL_THRESHOLD_MINUTES = 20

# 派发冷却窗口（双派发穿透原地修 2026-09-06）：成功派发后该窗口内同 spec 的重复
# _on_spec_ready 触发一律跳过。窗口需覆盖 dispatch→create 拿锁的亚秒窗口与失败
# 回写 ready 外溢的秒级重入；合法重试（Retry/full_scan 周期/退避定时器）间隔为
# 分钟级，不受影响。
DISPATCH_COOLDOWN_SECONDS = 10

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

        self._handling_events = set()  # 防重入：正在处理的 (event_kind, spec_name)
        # 队列/并发状态与锁随 Dispatcher 组件同迁（design D3 规则 1，单锁语义不变）

        # 优雅关闭标志（fix-admin-self-heal）：daemon 关闭期间禁止派发新 agent，
        # 否则 shutdown 的 wait_for_running_agents 会陷入「杀一个又起一个」的死循环
        self.shutting_down = False

        # Blocker detection state
        self._last_blocker_check = None
        self._last_blocker_report_time = None

        # 派发单飞守卫（fix-startup-double-dispatch）：跟踪正在派发中的 spec，
        # 防止启动扫描与事件回放对同一 spec 的重复派发
        self._pending_dispatches: set = set()
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
        """Auto-promote drafted → ready, then immediately schedule implementer.

        Gates: if gates.promote_mode is 'manual', spec stays drafted
        (no promotion, no error, no dispatch) — awaiting manual promotion.
        """
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
        )
        if not result["ok"]:
            # lint 违规或非 drafted 拒绝：error 已由 promote_drafted 写入 STATE（lint 违规），
            # 或返回拒绝原因（非 drafted）。两种情况都不派发。
            return
        # 全部通过：transition drafted → ready + 直接排队实现
        self.logger.info("pm_engine", f"Auto-promoting '{spec_name}': drafted → ready")
        self.state_machine.transition(spec_name, "ready")
        # 直接调用 _on_spec_ready 排队实现，不依赖事件循环
        self._on_spec_ready(spec_name)

    def _lint_deliverable_declarations(self, spec_name: str) -> list:
        """Deliverables 声明形态 lint（晋升前拦截，fail-open）。"""
        from core.deliverables import lint_declared

        spec_dir = self.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return []
        try:
            return lint_declared(spec_dir, self.project_root)
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"Deliverables lint 异常 '{spec_name}'（非阻塞放行）: {e}",
            )
            return []

    def _lint_tasks_parseable(self, spec_name: str) -> list:
        """tasks.md 可解析性 lint（晋升前拦截，fail-open，task-track D2）。"""
        from core.deliverables import lint_tasks_parseable

        spec_dir = self.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return []
        try:
            return lint_tasks_parseable(spec_dir, self.project_root)
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"tasks.md 可解析性 lint 异常 '{spec_name}'（非阻塞放行）: {e}",
            )
            return []

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
        if last_dispatch is not None \
                and (time.time() - last_dispatch) < DISPATCH_COOLDOWN_SECONDS:
            self.logger.debug(
                "pm_engine",
                f"Skipping dispatch for '{spec_name}': cooldown window active",
            )
            return

        # 派发单飞守卫（fix-startup-double-dispatch）：原子检查是否已在派发中
        # 同一 spec 的并发 spec_ready 处理只放行一个；单飞标记须在 worktree 锁
        # 创建之前占位，封死启动窗口
        if spec_name in self._pending_dispatches:
            self.logger.debug(
                "pm_engine",
                f"Skipping duplicate dispatch for '{spec_name}': already pending",
            )
            return

        # 标记为正在派发（在任何异步操作之前）
        self._pending_dispatches.add(spec_name)

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
            self._last_dispatch_at[spec_name] = time.time()
        finally:
            # 派发完成（成功或失败），从 pending 中移除，允许未来派发
            self._pending_dispatches.discard(spec_name)

    # ── 定时调度到期检测（add-spec-scheduling-controls D3）────────────────────

    @staticmethod
    def _frozen_state(entry: dict) -> bool:
        """冻结态判定（state_machine 侧）：frozen 结构化标记或 legacy 文本契约。"""
        if not isinstance(entry, dict):
            return False
        if entry.get(FROZEN_FIELD) is True:
            return True
        return (
            entry.get("status") == SpecStatus.BLOCKED
            and (entry.get("error") or "").startswith(FREEZE_ERROR_PREFIX)
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
                            self.project_root, "pm_engine",
                            f"定时解冻 SPEC '{name}'（原状态 {orig}）",
                            context={"source": "scheduled-unfreeze",
                                     "frozen_until": before},
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
            if sa is None or parse_utc(sa) is None:
                continue  # 无定时字段（或非法）→ 无到期检测需求
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
        #（periodic full_scan 仍为兜底；_process_queue 幂等，空队列直接返回）。
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
            self.logger.debug(
                "pm_engine",
                f"Skipping verifier enqueue for fast-track '{spec_name}' "
                "(单 run 全包，验证在 fast-track run 内完成)",
            )
            return
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
            # fix-daemon-lifecycle-races D4：transition() 对 old==new 幂等返回 True，
            # 事件回放（done→done）时此处仍会进入——total_duration 重算为同值覆盖无害，
            # _evict_spec_serving 幂等，project log 由 _on_spec_done 防重入（_guard:done）
            # 去重。无需额外前置判断。
            if self.state_machine.transition(spec_name, "done"):
                # verify-process-lifecycle D6（spec 终局驱逐）：done 落定后同步
                # 回收该 spec 的被测实例——stop 登记服务 + 驱逐缓存 + 移除 serving
                # worktree（幂等；主树 static 共享实例保留）。
                try:
                    self._verification._evict_spec_serving(spec_name)
                except Exception as e:
                    self.logger.warning(
                        "pm_engine",
                        f"spec 终局 serving 驱逐失败 '{spec_name}'（非阻塞）: {e}",
                    )
                # add-done-duration-persist（D1/D2）：done 落定时刻把总耗时快照进
                # STATE.md，使耗时不再依赖易失的 run 产物（run 产物只增不减，
                # 但快照保证耗时独立于产物回读路径）。
                # 求和口径与 spec_summary 一致（duration_seconds 求和、含归档），
                # 保证写入值 = 当时列表页显示值。仅在转换成功后写入，重复事件回放
                # （done→done 非法转换返回 False）不会重复覆盖。
                total_duration = sum(
                    int(r.get("duration_seconds") or 0)
                    for r in get_runs(self.project_root, spec_name,
                                      include_archive=True)
                )
                self.state_machine.update_spec(spec_name,
                                               {"total_duration": total_duration})
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
        防重入（fix-daemon-lifecycle-races D5）：verify 成功后的同步直调
        （_on_spec_verified → 本方法）与 event_bus spec_done 事件双路径并发进入，
        用 _guard:done 键去重——同一 spec 的 done 处理只执行一次，重复 project
        log（✅ SPEC completed）不再产生；push 幂等由 approve_push 实例锁兜底。
        """
        event_key = ("_guard:done", spec_name)
        if event_key in self._handling_events:
            self.logger.debug(
                "pm_engine",
                f"Skipping duplicate spec_done for '{spec_name}'",
            )
            return
        self._handling_events.add(event_key)
        try:
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
        finally:
            self._handling_events.discard(event_key)

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
                # 共享结果文件护栏：文件携带的 spec 与当前 spec 不符时，
                # 视作其它 spec 的残留（主树 .fenix/.fenix-run-result.json 是共享文件，
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
                prefix=f".impl-result.{spec_name}.", suffix=".tmp",
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
        except OSError as e:
            self.logger.warning(
                "pm_engine",
                f"impl-result 快照写入失败 '{spec_name}'（非阻塞）: {e}",
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
            self.project_root / ".fenix" / "verify-progress"
            / spec_name / "impl-result.json"
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

    _TASK_LINE_RE = re.compile(r"^(\s*-\s+)\[(\s|x)\](\s+)(\d+\.\d+)(.*)$")

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
            self.logger.debug(
                "pm_engine", f"任务回写跳过（done_ids/flat_done 皆空）：{spec_name}")
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
        task_lines = [
            (i, self._TASK_LINE_RE.match(ln))
            for i, ln in enumerate(lines)
        ]
        changed = False

        if done_ids:
            # 第 1 级：done_ids 精确对齐（既有行为不变）
            for i, m in task_lines:
                if m and m.group(4) in done_ids and m.group(2) != "x":
                    # `- [ ]` → `- [x]`，仅当该 id 在 done_ids 且当前未勾选
                    lines[i] = f"{m.group(1)}[x]{m.group(3)}{m.group(4)}{m.group(5)}"
                    changed = True
        else:
            # 第 2 级：flat 回退（subject 无编号 run），弱一致性校验 + 按创建序勾选
            unchecked = [(i, m) for i, m in task_lines if m and m.group(2) != "x"]
            if not unchecked:
                self.logger.debug(
                    "pm_engine", f"任务回写跳过（无未完成项）：{spec_name}")
                return
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

        if not changed:
            self.logger.debug("pm_engine", f"任务回写跳过（无新勾选）：{spec_name}")
            return

        # 原子写（临时文件 + replace），异常由调用方捕获不阻塞主流程
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".tasks.{spec_name}.", suffix=".tmp",
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
        level = len(done_ids) if done_ids else min(max(flat_done) + 1, created_count)
        self.logger.info(
            "pm_engine",
            f"任务进度回写成功 '{spec_name}'：勾选 {level} 个任务"
            f"（{'done_ids 精确' if done_ids else 'flat 兜底'}）",
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
            tasks_path = (
                self.project_root / "spec" / "changes" / spec_name / "tasks.md"
            )
            if not tasks_path.exists():
                return None
            has_unchecked_numeric = False
            try:
                for line in tasks_path.read_text(encoding="utf-8").split("\n"):
                    m = re.match(r"^- \[(x| )\] (\d+\.\d+)", line)
                    if m and m.group(1) != "x":
                        has_unchecked_numeric = True
                        break
            except (OSError, UnicodeDecodeError):
                return None
            if not has_unchecked_numeric:
                return None  # 全勾 / 无数字任务 → 无缺口可拦
            return (
                TASK_GAP_ERROR_PREFIX
                + "run 证据缺失（快照与共享文件均无），需人工确认"
            )

        # 证据存在 → 检查 impl_status
        impl_status = result.get("status")
        if impl_status != "success":
            return None  # 非 success（error/其它）→ 放行（现状不变）

        tasks_path = self.project_root / "spec" / "changes" / spec_name / "tasks.md"
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





    # ── judge 自述环境问题守卫（不派生 fix）────────────────────────

    _ENV_INFRA_MARKERS = (
        "环境问题", "环境配置", "环境故障", "测试环境",
        "非产品", "不是产品", "而非产品",
    )



    # ── 裁决证据分类校验 / 采纳（add-verdict-evidence-taxonomy D1-D5）──







    # ── Queue Management ───────────────────────────────────────────




    # ── 派发队列老化（dispatch-queue-aging / design D3）─────────








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



    # ── Push Gate ──────────────────────────────────────────────────


    # ── Push backoff helpers (design D3) ───────────────────────────



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
                self.logger.warning(
                    "pm_engine", f"Cannot push '{spec_name}': SPEC not found"
                )
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
                    "pm_engine", f"Cannot push '{spec_name}': not in done state "
                                 f"(is '{status}')"
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

    # ── 归档自动提交（archive-auto-commit）──────────────────────────

    def _archive_move_residue(self) -> tuple:
        """检测 ``spec/changes/`` 下的归档移动残留（archive-auto-commit）。

        归档移动（soft_delete_spec 用 shutil.move 把 spec 目录移入 archive）在 git
        视角表现为两类残留：
        - 被归档 spec 目录的**删除**：`spec/changes/<spec>/...` 的 D 状态行；
        - **archive 下新增/修改**：`spec/archive/<spec>-<ts>/...` 的
          未跟踪（??）/A/M 状态行（rename 检测 R 的行任一侧命中同样计入）。

        返回 ``(has_residue: bool, spec_names: list[str])``。判定失败时按
        「无残留」处理（fail-open：不因检测异常阻塞 push 主流程）。
        """
        try:
            result = subprocess.run(
                # -uall：未跟踪目录不折叠，逐文件列出，归档新增 spec 名才能解析
                ["git", "status", "--porcelain", "-uall"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=30,
            )
        except Exception as e:
            self.logger.warning(
                "pm_engine",
                f"归档残留检测失败（按无残留处理，不阻塞 push）: {e}",
            )
            return False, []
        if result.returncode != 0:
            self.logger.warning(
                "pm_engine",
                f"git status 失败，按无归档残留处理: "
                f"{(result.stderr or result.stdout).strip()[:200]}",
            )
            return False, []

        names: list[str] = []
        found = False
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            xy = line[:2]
            rest = line[3:].strip()
            # rename 行形态：`R  old -> new`，两侧都要参与归档判定
            candidates = [rest]
            if " -> " in rest:
                candidates = [p.strip() for p in rest.split(" -> ")]
            for path in candidates:
                # 归档产物横跨两处：删除侧 spec/changes/<spec>/、新增侧 spec/archive/...
                # （archive 已平级化到 spec/ 下，不再嵌套于 changes/）
                in_changes = path.startswith("spec/changes/")
                in_archive = path.startswith("spec/archive/")
                if not (in_changes or in_archive):
                    continue
                deleted = "D" in xy
                added = xy.startswith("??") or ("A" in xy or "M" in xy)
                if deleted or (in_archive and added):
                    found = True
                    names.append(self._archive_residue_spec(path))
        return found, list(dict.fromkeys(n for n in names if n))

    @staticmethod
    def _archive_residue_spec(rel_path: str) -> str:
        """从 spec/changes/ 相对路径提取涉及 spec 名。

        - 删除侧：`spec/changes/<spec>/...` → `<spec>`
        - 归档新增侧：`spec/archive/.../...` → `<spec>`。归档目录命名两种：
          软删除 `<spec>-<Unix秒>[-(ms|-n)]`（剥离尾部纯数字段）、
          归档 `YYYY-MM-DD-<spec>`（剥离日期前缀）
        """
        if rel_path.startswith("spec/archive/"):
            seg = rel_path[len("spec/archive/"):].split("/", 1)[0]
            # 软删除命名：<spec>-<Unix秒>[-(ms|-n)]；剥离尾部纯数字段
            m = re.match(r"^(.*?)(?:-\d{10,13}(?:-\d{1,6})*)$", seg)
            if m:
                return m.group(1)
            # 归档命名：YYYY-MM-DD-<spec>；剥离日期前缀
            m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", seg)
            return m.group(1) if m else seg
        if rel_path.startswith("spec/changes/"):
            return rel_path[len("spec/changes/"):].split("/", 1)[0]
        return ""

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
        has_residue, spec_names = self._archive_move_residue()
        if not has_residue:
            return
        label = "、".join(spec_names) if spec_names else "spec"
        commit_msg = f"[fenix] archive: {label} 归档入库"
        ok, err = self._git_commit(["spec"], commit_msg)
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
                # fix-verified-gate-evidence-race D3：error 带 task-gap: 前缀的卡
                # verified spec 属「任务缺口待人工裁决」，blocker 条目 reason 改述
                # 为裁决形态并携带缺口摘要（去前缀），供 admin 工作台直接定位；
                # 不得按「瞬态」语义改述（下方案例 4.4 断言依赖此措辞）。
                stored_error = entry.get("error") or "No error recorded"
                if (
                    isinstance(stored_error, str)
                    and stored_error.startswith(TASK_GAP_ERROR_PREFIX)
                ):
                    gap_summary = stored_error[len(TASK_GAP_ERROR_PREFIX):].strip()
                    blockers.append({
                        "spec": name,
                        "status": status,
                        "reason": (
                            f"任务缺口待人工裁决：{gap_summary or '详情见 error 字段'}"
                        ),
                        "error": stored_error,
                        "elapsed_minutes": v_elapsed,
                    })
                    continue
                blockers.append({
                    "spec": name,
                    "status": status,
                    "reason": f"卡在 verified 状态 {v_elapsed} 分钟（应为瞬态，需要推进到 done）",
                    "error": stored_error,
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
                        # 存活 attempt 亦不算（与 D4 auto-recovery 的 live-child 豁免同语义）：
                        # daemon 重启后 recovery 把 implementing 恢复为 ready，而旧 run 的
                        # 流写侧已随旧进程死亡——「流 mtime = 派发活动」代理判据失真，
                        # 不豁免会把「活 run 被重建锁保护、恢复检查正确 skip」的 spec
                        # 误报为 dispatch_stalled 循环呼叫 Administrator（2026-09-06
                        # add-verify-multi-kind-runner 事故）。
                        stall_threshold = self._ready_stall_threshold_minutes()
                        if (elapsed > stall_threshold
                                and not self._dispatch_backoffed(entry)
                                and not self._spec_has_recent_run_activity(
                                    name, stall_threshold)
                                and not self._attempt_still_alive(name)):
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
                # fix-verified-gate-evidence-race D3：task-gap 前缀的 blocker 是
                # 门禁结论（任务缺口待人工裁决），recovery 不得触发 auto-recover
                # 状态突变——缺口不因恢复而消失，恢复只会造成状态机扰动。持续列
                # 入 blocker 清单即告警通道；人工补勾后由 event_bus re-trigger
                # 门禁放行（确定性重评，幂等）。
                if (
                    isinstance(b.get("error"), str)
                    and b.get("error").startswith(TASK_GAP_ERROR_PREFIX)
                ):
                    self.logger.info(
                        "pm_engine",
                        f"task-gap blocker，不 auto-recover：'{spec_name}' "
                        f"(reason={b.get('reason')})",
                    )
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
                    # add-fast-track-mode（task 3.1）：实现态恢复按 mode 派发对应 agent
                    from core.spec_mode import read_spec_mode
                    _at = (
                        "fast-track"
                        if read_spec_mode(self.project_root, spec_name) == "fast-track"
                        else "implementer"
                    )
                    self._enqueue(spec_name, _at)
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
        log_path = self.project_root / ".fenix" / "PROJECT_LOG.md"
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

    # ── 实现尝试总预算（add-fail-counter-budget D2/D4 / add-spec-status-modal-budget D3）──────────────
    def _impl_run_budget(self, spec_name: str | None = None) -> int:
        return self._budget._impl_run_budget(spec_name)

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

    def _run_scenario_static_check(self, spec_name: str) -> None:
        return self._verification._run_scenario_static_check(spec_name)

    def _scenario_defect_reroute_gate(self, spec_name: str, _repair_depth: int,
                                      judge_result) -> bool:
        return self._verification._scenario_defect_reroute_gate(
            spec_name, _repair_depth, judge_result)

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

    def _disputed_deliverables(self, impl_result, missing) -> list:
        return self._verification._disputed_deliverables(impl_result, missing)

    def _adjudicate_deliverable_missing(self, spec_name: str, result,
                                        impl_result, missing: list) -> dict:
        """缺件 LLM 终审 + 裁决机械执行（add-deliverable-declaration-triage D3/D4）。"""
        return self._dispatcher._adjudicate_deliverable_missing(
            spec_name, result, impl_result, missing)

    @staticmethod
    def _normalize_fail_signature(text: str) -> str:
        return VerificationPipeline._normalize_fail_signature(text)

    def _detect_uniform_verify_failure(self, spec_name: str, report: dict) -> bool:
        return self._verification._detect_uniform_verify_failure(spec_name, report)

    def _run_legacy_verification(self, spec_name: str):
        return self._verification._run_legacy_verification(spec_name)

    def _verify_verdict_evidence(self, spec_name: str, retry_judge: bool = False) -> dict:
        return self._verification._verify_verdict_evidence(spec_name, retry_judge)

    def _speculative_bug_found_gate(self, spec_name: str) -> bool:
        """归因分级门禁（add-verdict-credibility-gate / D2 / Task 2.2）。"""
        return self._verification._speculative_bug_found_gate(spec_name)

    def _env_whitewash_gate(self, spec_name: str) -> bool:
        return self._verification._env_whitewash_gate(spec_name)

    def _escalate_env_blocked(self, spec_name: str, violations: list) -> None:
        return self._verification._escalate_env_blocked(spec_name, violations)

    def _update_warning_streaks(self, spec_name: str) -> list:
        return self._verification._update_warning_streaks(spec_name)

    def _warning_stale_triage_alert(self, spec_name: str, scenario_ids: list) -> None:
        return self._verification._warning_stale_triage_alert(spec_name, scenario_ids)

    def _ensure_verification_report(self, spec_name: str) -> str | None:
        return self._verification._ensure_verification_report(spec_name)

    def _check_verification_gate(self, spec_name: str) -> str | None:
        return self._verification._check_verification_gate(spec_name)

    def _read_verifier_result(self, result_path: Path) -> "VerdictReadResult":
        return self._verification._read_verifier_result(result_path)

    def _read_planner_result(self, spec_name: str) -> "VerdictReadResult":
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

    # ── 失败历史侧车门面（fix-verdict-retry-misattribution D6）──
    def _read_fail_history(self, spec_name: str) -> list:
        return self._verification._read_fail_history(spec_name)

    def _append_fail_history(self, spec_name: str, cause_type: str,
                             failed_scenarios: list) -> None:
        return self._verification._append_fail_history(
            spec_name, cause_type, failed_scenarios)

    def _clear_fail_history(self, spec_name: str) -> None:
        return self._verification._clear_fail_history(spec_name)

    def _failed_scenario_ids(self, spec_name: str) -> list:
        return self._verification._failed_scenario_ids(spec_name)

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

    def _dispatch_backoff_schedule(self) -> list:
        return self._dispatcher._dispatch_backoff_schedule()

    def _handle_dispatch_lock_conflict(self, spec_name: str) -> None:
        return self._dispatcher._handle_dispatch_lock_conflict(spec_name)

    def _schedule_backoff_retry(self, spec_name: str, delay: float) -> None:
        return self._dispatcher._schedule_backoff_retry(spec_name, delay)

    def _get_spec_priority(self, spec_name: str) -> int:
        return self._dispatcher._get_spec_priority(spec_name)

    def _enqueue(self, spec_name: str, agent_type: str):
        return self._dispatcher._enqueue(spec_name, agent_type)

    def _enqueue_front(self, spec_name: str, agent_type: str):
        return self._dispatcher._enqueue_front(spec_name, agent_type)

    def _aging_bonus(self, enqueued_at: float, now: float) -> int:
        return self._dispatcher._aging_bonus(enqueued_at, now)

    def _effective_priority(self, base: int, enqueued_at: float, now: float) -> int:
        return self._dispatcher._effective_priority(base, enqueued_at, now)

    def _process_queue(self):
        return self._dispatcher._process_queue()

    def _run_agent_worker(self, spec_name: str, agent_type: str, priority: int):
        return self._dispatcher._run_agent_worker(spec_name, agent_type, priority)

    @staticmethod
    def _dispatch_backoffed(spec: dict) -> bool:
        return Dispatcher._dispatch_backoffed(spec)

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
        """返回 spec 的秒挂冷却到期单调秒（未冷却/无条目返回 0）。"""
        runner = getattr(self, "agent_runner", None)
        table = getattr(runner, "_instant_fail", None)
        if not isinstance(table, dict):
            return 0.0
        st = table.get(spec_name) or {}
        try:
            return float(st.get("cooldown_until") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _rollback_failed_dispatch(self, spec_name: str, agent_type: str, exc: Exception):
        return self._dispatcher._rollback_failed_dispatch(spec_name, agent_type, exc)

    def _report_stash_pop_conflict(self, spec_name: str, conflict_files: list,
                                   merge_info=None) -> None:
        return self._dispatcher._report_stash_pop_conflict(
            spec_name, conflict_files, merge_info=merge_info)

    def _run_fast_track_worker(self, spec_name: str) -> None:
        """fast-track 单 run 全包 worker（add-fast-track-mode D1/D4/D5/D6）。"""
        return self._dispatcher._run_fast_track_worker(spec_name)

    def _should_enter_repair(self, spec_name: str, merge_info, streak: int,
                             breaker_threshold: int) -> bool:
        """merge-back 语义冲突失败是否进入 repair 通道（add-merge-back-repair-lane）。"""
        return self._dispatcher._should_enter_repair(
            spec_name, merge_info, streak, breaker_threshold)

    def _dispatch_repair_lane(self, spec_name: str, merge_info, branch: str,
                              fp: str | None = None, streak: int = 0) -> None:
        """进入 repair 通道（载体三态解析 + 认领现场 + 派发 repair worker）。"""
        return self._dispatcher._dispatch_repair_lane(
            spec_name, merge_info, branch, fp=fp, streak=streak)

    def _claim_repair_site(self, spec_name: str, wt_path, branch: str) -> None:
        """认领 repair 现场（_legacy take 摘出 + _spec_locks 注册）。"""
        return self._dispatcher._claim_repair_site(spec_name, wt_path, branch)

    def _run_repair_worker(self, spec_name: str, wt_path, branch: str, merge_info) -> None:
        """repair worker：派发 repair agent → re-merge-back → 状态推进。"""
        return self._dispatcher._run_repair_worker(spec_name, wt_path, branch, merge_info)

    def _handle_remerge_failure(self, spec_name: str, remerge_info, branch: str) -> None:
        """repair 后 re-merge-back 失败处理（熔断连续累计 + 下一轮 repair/fallback）。"""
        return self._dispatcher._handle_remerge_failure(spec_name, remerge_info, branch)

    def _fallback_after_repair(self, spec_name: str, branch: str | None,
                               repair_error: str, merge_error: str = "") -> None:
        """repair 链失败回退：全新重派 implementer（prompt 注入 merge 失败上下文）。"""
        return self._dispatcher._fallback_after_repair(
            spec_name, branch, repair_error, merge_error=merge_error)

    def _recovery_watch_path(self) -> Path:
        return self._recovery._recovery_watch_path()

    def _load_recovery_watch(self) -> None:
        return self._recovery._load_recovery_watch()

    def _save_recovery_watch(self) -> None:
        return self._recovery._save_recovery_watch()

    def register_recovery_watch(self, spec_name: str, reason: str) -> None:
        return self._recovery.register_recovery_watch(spec_name, reason)

    def check_recovery_watch(self) -> list:
        return self._recovery.check_recovery_watch()

    def reclaim_stale_autostash_if_idle(self) -> bool:
        """滞留 autostash 兜底回收（fix-autostash-orphans）。

        仅当无活跃 run 时执行：有 worker 在跑时 pop 用户改动会让主树变脏，
        干扰其 merge-back 基线（虽然 guard 会重新 stash，但没必要抢跑）。
        """
        if self._active_runs > 0:
            return False
        return self.agent_runner.worktree_manager.reclaim_stale_autostash()

    @staticmethod
    def _spec_fingerprint(entry: dict) -> str:
        return RecoveryWatch._spec_fingerprint(entry)

    def _signal_dispatch_stalled(self, spec_name: str, evidence: str,
                                 fingerprint: str | None = None) -> None:
        return self._recovery._signal_dispatch_stalled(spec_name, evidence, fingerprint)

    def _clear_dispatch_conflict(self, spec_name: str) -> dict:
        return self._recovery._clear_dispatch_conflict(spec_name)

    def generate_report(self) -> str:
        return self._reporting.generate_report()

    def generate_daily_report(self):
        return self._reporting.generate_daily_report()

    def get_pushable_specs(self):
        return self._reporting.get_pushable_specs()

    @staticmethod
    def _is_push_backoffed(spec: dict) -> bool:
        return ReportBuilder._is_push_backoffed(spec)

    @staticmethod
    def _get_push_retry_count(spec: dict) -> int:
        return ReportBuilder._get_push_retry_count(spec)

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

