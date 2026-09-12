"""dispatch.py — Dispatcher：派发队列/优先级与老化/并发闸/派发退避/_process_queue/_run_agent_worker（refactor-core-packages 阶段 6）。

SPEC 状态经门面回引 self._pm.state_machine（design D3 规则 3）；
组件内非自有状态/方法的 self.X 一律改写为 self._pm.X，保住门面
实例上的测试补丁缝与跨组件调用路径。

"""

from datetime import datetime, timezone
import json
import threading
import time
from pathlib import Path

from core.state_machine import ENV_BLOCK_ROUNDS_FIELD, start_after_pending


# ── 派发锁冲突退避（improve-run-lifecycle-governance D5）────────────────────
# 派发 implementer 遇「worktree already active」时不再硬试三连发：按此序列指数
# 退避安排下一次尝试，期间不消耗 _retry_count、不写 retries exhausted（attempt
# 配额只属于任务失败，不属于基础设施冲突）。可配 pm.dispatch_backoff_schedule。
DEFAULT_DISPATCH_BACKOFF_SCHEDULE = (30, 120, 600)

# ── repair 通道轮次上限（add-merge-back-repair-lane D5）────────────────────
# 同一 merge 失败事件链内 repair 最多 2 轮，超限回退 fallback 全新重派。
# 模块常量、**不新增配置键**（规避 dashboard UI 联动义务，design D5）。
MAX_REPAIR_ROUNDS_PER_FAILURE = 2


class Dispatcher:
    """派发队列组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

        # 队列与并发状态（design D3 规则 1：_queue_lock 与被保护的
        # _run_queue/_active_runs/_active_priorities 整体同迁，单锁语义不变）。
        self._queue_lock = threading.Lock()
        self._active_runs = 0
        # Pending (priority, spec_name, agent_type, enqueued_at) tuples。
        # enqueued_at 为入队时刻 time.time()，仅供内存态老化计时（design D3）：
        # 不持久化，daemon 重启重建队列即视为等待清零。
        self._run_queue = []
        self._active_priorities = set()  # 当前活动 priority 集合（宽松优先级下可含多个档）
        self._active_priority_counts: Dict[int, int] = {}  # priority → 活动 run 数
        # 派发锁冲突退避定时器（_schedule_backoff_retry 维护，死定时器惰性清理）。
        self._backoff_timers: list = []
        # 秒挂冷却恢复定时器（cli-retry-backoff 2.2）：{spec_name}，幂等排程防重复。
        # 冷却到期由定时器重入 _on_spec_ready，不依赖 30 分钟全量扫描兜底。
        self._instant_fail_timers: set = set()
        # fix-provider-transient-backoff（D4）：transient 恢复排程定时器：{spec_name}。
        # 瞬断终态触发后按 `transient_redispatch_delay_seconds`（缺省 600s）延迟重入
        # _on_spec_ready，同 instant_fail_timers 同款幂等去重。
        self._transient_timers: set = set()

    def _dispatch_backoff_schedule(self) -> list:
        """退避序列（秒）。可配 pm.dispatch_backoff_schedule，默认 [30, 120, 600]。

        配置容错：标量视作单元素序列；空/非法序列回退默认值。
        """
        sched = self._pm._get_config(
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
        spec = self._pm.state_machine.read_one(spec_name) or {}
        try:
            count = int(spec.get("_lock_conflict_count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        schedule = self._pm._dispatch_backoff_schedule()

        now = time.time()
        exhausted = count >= len(schedule)
        delay = schedule[-1] if exhausted else schedule[count]
        until = int(now + delay)
        from datetime import datetime as _dt, timezone as _tz
        until_iso = _dt.fromtimestamp(until, _tz.utc).isoformat()

        # 不翻转状态：spec 保持 ready，仅记录退避元数据
        self._pm.state_machine.update_spec(spec_name, {
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
            self._pm.logger.error(
                "pm_engine",
                f"Dispatch backoff exhausted for '{spec_name}' — lock still held, "
                f"escalating dispatch_stalled",
            )
            self._pm._signal_dispatch_stalled(spec_name, evidence)
            # 序列耗尽后不再自旋重试（定时器停止），spec 保持 ready 等待处置
            return

        self._pm.logger.info(
            "pm_engine",
            f"Dispatch lock conflict for '{spec_name}' — backoff {int(delay)}s "
            f"(attempt {count + 1}/{len(schedule)}), not counted against retries",
        )
        self._pm._schedule_backoff_retry(spec_name, delay)


    def _schedule_backoff_retry(self, spec_name: str, delay: float) -> None:
        """退避到期后重入 ``_on_spec_ready``（daemon 线程；关闭期间自然失效）。"""
        timer = threading.Timer(
            max(0.5, float(delay)),
            self._pm._on_spec_ready,
            args=(spec_name,),
        )
        timer.daemon = True
        with self._queue_lock:
            self._backoff_timers = [
                t for t in getattr(self, "_backoff_timers", []) if t.is_alive()
            ]
            self._backoff_timers.append(timer)
        timer.start()


    def _schedule_instant_fail_recovery(self, spec_name: str,
                                        lock_held: bool = False) -> None:
        """冷却到期后重入 ``_on_spec_ready``（cli-retry-backoff 2.2）。

        幂等：已为该 spec 排程恢复定时器则不再重复（``_instant_fail_timers`` 集合
        判重）。cooldown_until 以 ``time.monotonic`` 记（runner._now），差值为
        剩余秒；到期回调重新触发派发并顺带 process_queue。

        ``lock_held``：调用方已持 ``_queue_lock`` 时为 True（_process_queue 场景），
        跳过内部再取锁——threading.Lock 非重入，双重获取会死锁。
        """
        if lock_held:
            self._schedule_instant_fail_recovery_locked(spec_name)
            return
        with self._queue_lock:
            self._schedule_instant_fail_recovery_locked(spec_name)

    def _schedule_instant_fail_recovery_locked(self, spec_name: str) -> None:
        """锁内实现（调用方已持 _queue_lock）排程冷却恢复定时器。"""
        if spec_name in self._instant_fail_timers:
            return
        until = self._pm._instant_fail_cooldown_until(spec_name)
        if until <= 0:
            return
        delay = max(0.5, float(until) - time.monotonic())
        timer = threading.Timer(
            delay, self._on_instant_fail_recovery, args=(spec_name,),
        )
        timer.daemon = True
        self._instant_fail_timers.add(spec_name)
        timer.start()

    def _on_instant_fail_recovery(self, spec_name: str) -> None:
        """秒挂冷却到期回调：重新唤起派发（幂等，多定时器并发安全）。"""
        with self._queue_lock:
            self._instant_fail_timers.discard(spec_name)
        self._pm.logger.info(
            "pm_engine",
            f"秒挂冷却到期，恢复调度 '{spec_name}'（cli-retry-backoff 自动恢复）",
        )
        try:
            self._pm._on_spec_ready(spec_name)
        finally:
            self._pm._process_queue()

    # ── fix-provider-transient-backoff（D4）：transient 恢复排程 ──────────
    # 仿秒挂冷却（instant_fail_recovery）定时器模式：瞬断终态后按
    # `agents.transient_redispatch_delay_seconds`（缺省 600s）延迟重入
    # `_on_spec_ready` + `_process_queue`。与 _retry_count 正交——不清零、不递增。

    def _schedule_transient_recovery(self, spec_name: str,
                                    lock_held: bool = False) -> None:
        """瞬断终态后排程等待，到期重新触发派发（fix-provider-transient-backoff D4）。

        幂等：已为该 spec 排程恢复定时器则不再重复（``_transient_timers`` 集合
        判重）。等待时长按 ``agents.transient_redispatch_delay_seconds``
        （缺省 600s）配置。

        ``lock_held``：调用方已持 ``_queue_lock`` 时为 True，跳过内部再取锁。
        """
        if lock_held:
            self._schedule_transient_recovery_locked(spec_name)
            return
        with self._queue_lock:
            self._schedule_transient_recovery_locked(spec_name)

    def _schedule_transient_recovery_locked(self, spec_name: str) -> None:
        """锁内实现（fix-provider-transient-backoff）排程 transient 恢复定时器。"""
        if spec_name in self._transient_timers:
            return
        delay = float(self._pm._get_config(
            "agents.transient_redispatch_delay_seconds", 600))
        delay = max(10.0, delay)  # 最小等待 10s，避免零值/负值
        timer = threading.Timer(
            delay, self._on_transient_recovery, args=(spec_name,),
        )
        timer.daemon = True
        self._transient_timers.add(spec_name)
        timer.start()
        self._pm.logger.info(
            "pm_engine",
            f"Transient recovery scheduled for '{spec_name}' in {int(delay)}s "
            f"(fix-provider-transient-backoff)",
        )

    def _on_transient_recovery(self, spec_name: str) -> None:
        """瞬断冷却到期回调：重新唤起派发（幂等，多定时器并发安全）。"""
        with self._queue_lock:
            self._transient_timers.discard(spec_name)
        self._pm.logger.info(
            "pm_engine",
            f"Transient recovery fired for '{spec_name}' — resuming dispatch "
            f"(fix-provider-transient-backoff)",
        )
        try:
            self._pm._on_spec_ready(spec_name)
        finally:
            self._pm._process_queue()

    def _get_spec_priority(self, spec_name: str) -> int:
        """读取 SPEC 的 priority，缺省为 5。"""
        spec = self._pm.state_machine.read_one(spec_name)
        if spec and isinstance(spec.get("priority"), int):
            return spec["priority"]
        return 5


    def _enqueue(self, spec_name: str, agent_type: str):
        """Add a run request to the queue (thread-safe).

        条目结构：(priority, spec_name, agent_type, enqueued_at)。
        priority 从 STATE.md 读取（缺省 5）；enqueued_at = time.time() 供
        派发队列老化计时（design D3，内存态、不持久化）。
        """
        priority = self._pm._get_spec_priority(spec_name)
        entry = (priority, spec_name, agent_type, time.time())
        with self._queue_lock:
            # 去重：忽略 priority 差异，只看 (spec, agent)
            if not any(e[1] == spec_name and e[2] == agent_type for e in self._run_queue):
                self._run_queue.append(entry)
                self._pm.logger.debug(
                    "pm_engine",
                    f"Queued: {spec_name} ({agent_type}, P{priority})"
                )


    def _enqueue_front(self, spec_name: str, agent_type: str):
        """Insert a run request at the front of its priority bucket (thread-safe).

        在优先级调度下，「队首」语义改为同档优先：verifier 与 implementer
        属于同一 SPEC、同一 priority，插入后落回同一档且保持档内 FCFS。
        """
        priority = self._pm._get_spec_priority(spec_name)
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
            self._pm.logger.debug(
                "pm_engine",
                f"Queued at front of P{priority}: {spec_name} ({agent_type})"
            )


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
        cfg = self._pm.config or {}
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
        return max(0, base - self._pm._aging_bonus(enqueued_at, now))


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
        if self._pm.shutting_down:
            self._pm.logger.debug("pm_engine", "Shutting down — dispatch paused")
            return
        # fix-provider-transient-backoff D4：全局瞬断熔断冻结期间暂停一切新派发。
        # 与 instant_fail_cooled 同构：冷却到期自动恢复；在飞 run 不受影响。
        if self._pm._global_transient_break_active():
            self._pm.logger.debug(
                "pm_engine",
                "Global transient break active — dispatch paused "
                "(fix-provider-transient-backoff D4)",
            )
            return
        max_concurrent = self._pm._get_config("agents.max_concurrent", 2)

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
                    eff = self._pm._effective_priority(prio, enqueued_at, now)
                    spec = self._pm.state_machine.read_one(sname)
                    if not spec:
                        continue
                    status = spec.get("status")
                    if atype == "implementer" and status not in ("ready", "implementing"):
                        # implementing 允许派发 = 原地打回的修复重派（热修 2026-08-29）：
                        # 打回处置 _enqueue 时状态为 implementing，旧条件 status != "ready"
                        # 导致修复条目被永久静默跳过、链路停摆。入队点均在 run 终止后
                        # （打回处理器/零变更重试）且 _enqueue 按 (spec,type) 去重，无双派。
                        continue
                    if atype == "fast-track" and status not in ("ready", "implementing"):
                        # fast-track：ready 正常派发；implementing 允许 = 失败打回后的修复重派
                        #（入队点均在 run 终止后，与 implementer 同语义，无双派）。
                        continue
                    if atype == "verifier" and status != "implemented":
                        continue
                    if self._pm._dispatch_backoffed(spec):
                        continue
                    # add-spec-scheduling-controls D2：start_after 未到期静默跳过
                    #（不写 error 不翻状态，对齐退避门控的防自触发设计）；到期后由
                    # 60s 定时唤起 / full_scan 兜底恢复调度。
                    if start_after_pending(spec):
                        self._pm.logger.debug(
                            "pm_engine",
                            f"start_after 未到期，跳过 {atype} 派发 '{sname}'（定时拾取）",
                        )
                        continue
                    # cli-retry-backoff 2.2：秒挂冷却期内跳过 implementer/fast-track/
                    # repair 派发（不耗预算、不起进程），并排程到期自动恢复。
                    if atype in ("implementer", "fast-track", "repair") \
                            and self._pm._instant_fail_cooled(sname):
                        self._pm.logger.debug(
                            "pm_engine",
                            f"秒挂冷却中，跳过 {atype} 派发 '{sname}'",
                        )
                        self._schedule_instant_fail_recovery(sname, lock_held=True)
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
                    if self._pm._effective_priority(prio, enqueued_at, now) != target_prio:
                        continue
                    spec = self._pm.state_machine.read_one(sname)
                    if not spec:
                        continue
                    status = spec.get("status")
                    if atype == "implementer" and status not in ("ready", "implementing"):
                        # implementing 允许派发 = 原地打回的修复重派（热修 2026-08-29）：
                        # 打回处置 _enqueue 时状态为 implementing，旧条件 status != "ready"
                        # 导致修复条目被永久静默跳过、链路停摆。入队点均在 run 终止后
                        # （打回处理器/零变更重试）且 _enqueue 按 (spec,type) 去重，无双派。
                        continue
                    if atype == "fast-track" and status not in ("ready", "implementing"):
                        # fast-track：ready 正常派发；implementing 允许 = 失败打回后的修复重派
                        #（入队点均在 run 终止后，与 implementer 同语义，无双派）。
                        continue
                    if atype == "verifier" and status != "implemented":
                        continue
                    if self._pm._dispatch_backoffed(spec):
                        continue
                    # add-spec-scheduling-controls D2：start_after 未到期静默跳过
                    #（不写 error 不翻状态，对齐退避门控的防自触发设计）；到期后由
                    # 60s 定时唤起 / full_scan 兜底恢复调度。
                    if start_after_pending(spec):
                        self._pm.logger.debug(
                            "pm_engine",
                            f"start_after 未到期，跳过 {atype} 派发 '{sname}'（定时拾取）",
                        )
                        continue
                    # cli-retry-backoff 2.2：秒挂冷却期内跳过派发（与 best_valid_prio
                    # 扫描同判定，保证队列继续扫描后续条目不被冷却 spec 阻塞）。
                    if atype in ("implementer", "fast-track", "repair") \
                            and self._pm._instant_fail_cooled(sname):
                        self._schedule_instant_fail_recovery(sname, lock_held=True)
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
            if agent_type == "implementer" and self._pm._is_fix_spec(spec_name):
                carrier = self._pm._sibling_repair_active(
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
                    self._pm.logger.info(
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
                if self._pm._check_impl_budget_exhausted(spec_name):
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
                # add-spec-content-integrity-gate：派发前内容完整性闸门。
                # 空 spec 目录（无 proposal/design/tasks/specs）冻结派发，
                # 不烧预算；与预算闸门同层并列，复用回滚范式。
                if self._pm._check_spec_content_missing(spec_name):
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
                cur_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status")
                if cur_status != "implementing":
                    self._pm.state_machine.transition(spec_name, "implementing")
            elif agent_type == "fast-track":
                # fast-track：与 implementer 同语义，派发即进入 implementing；
                # 失败打回重派时状态已是 implementing，跳过同态转换。
                if self._pm._check_impl_budget_exhausted(spec_name):
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
                # add-spec-content-integrity-gate：内容完整性闸门（fast-track 分支，
                # 与 implementer 同层并列；空 spec 冻结派发，不烧预算）。
                if self._pm._check_spec_content_missing(spec_name):
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
                cur_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status")
                if cur_status != "implementing":
                    self._pm.state_machine.transition(spec_name, "implementing")
            elif agent_type == "verifier":
                self._pm.state_machine.transition(spec_name, "testing")

            self._pm.logger.info(
                "pm_engine",
                f"Dispatching {agent_type} for '{spec_name}' (P{priority})",
                {"active_runs": active_count},
            )

            t = threading.Thread(
                target=self._pm._run_agent_worker,
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
            if agent_type == "fast-track":
                # ── fast-track 单 run 全包：实现 → 场景设计 → 验证 → 判定 ──
                # 预算与 worktree 语义与 implementer 一致（impl- run_id/分支前缀），
                # 结果处理走 _run_fast_track_worker（守卫 + 硬校验 + 状态推进）。
                self._pm._increment_impl_run_budget_used(spec_name)
                self._run_fast_track_worker(spec_name)

            elif agent_type == "implementer":
                # add-fail-counter-budget D2：实现 run 启动即递增预算计数并持久化
                # （跨重启有效）。已启动的 run 即使随后触发预算闸门也会照常跑完 merge
                # （沉没成本不浪费），闸门只阻止「新一轮」自动重派。
                self._pm._increment_impl_run_budget_used(spec_name)
                wm = self._pm.agent_runner.worktree_manager
                # 派发前把 spec 目录提交进主树（fix-merge-back-deadlock 根因修复）：
                # 消除「spec 在主树 untracked + 分支 commit 同名路径」导致的 merge-back 冲突。
                wm.ensure_spec_committed(spec_name)
                # ── 中断恢复保留续做（interrupt-recovery-preserve D4/D5）──
                # recovery 保留的 spec（_recovery_resume 标记 + 保留分支）：在既有
                # 分支的 worktree 内 resume 续做（claude --resume 断点续跑），
                # 而非从零新建分支。载体三态经 wm.resolve_resume_site
                #（is_available 单源）解析：在场原地 / 缺失重建 / 不可用降级
                # 为普通全新派发。标记一次性消费：派发后清空，防后续 full_scan
                # 反复尝试续做。
                resume_wt = None
                dispatch_entry = self._pm.state_machine.read_one(spec_name) or {}
                resume_branch = (
                    dispatch_entry.get("branch")
                    if dispatch_entry.get("_recovery_resume") else None
                )
                if resume_branch:
                    site = wm.resolve_resume_site(spec_name, resume_branch)
                    if site[0] is not None:
                        resume_wt = site[0]
                    else:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Resume site unavailable for '{spec_name}' "
                            f"(branch '{resume_branch}') — degrade to fresh dispatch",
                        )
                if dispatch_entry.get("_recovery_resume"):
                    self._pm.state_machine.update_spec(
                        spec_name, {"_recovery_resume": None})
                if resume_wt is not None:
                    self._pm.logger.info(
                        "pm_engine",
                        f"Resume dispatch for '{spec_name}' on preserved branch "
                        f"'{resume_branch}' (worktree {resume_wt})",
                    )
                    # 继承痕迹登记（prompt 注入恢复续做说明，interrupt-recovery-preserve 2.3）
                    try:
                        wm.mark_reused(spec_name, resume_wt, resume_branch or "")
                    except Exception as e:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"mark_reused for resume '{spec_name}' failed（非阻塞）: {e}",
                        )
                # 主树 stash 已收拢进 merge_back_from_branch 的 guard 原子段
                # （fix-autostash-orphans）：锁内 stash→merge→pop，不再依赖
                # 派发前 stash + 成功路径 pop 的长窗口配对（曾致 7 次改动滞留 stash）。
                result = self._pm.agent_runner.run_implementer(
                    spec_name, pre_wt_path=resume_wt)
                # Read .fenix-run-result.json (worktree first, project root fallback)
                # to determine true status — file is more authoritative than
                # process exit code for semantic success/error.
                impl_result = self._pm._read_implementer_result(spec_name)
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
                if is_success and self._pm._implementer_zero_change(spec_name, result):
                    # ── 验证确认型 no-op 放行（2026-09-11 add-web-ui 事故原地修）──
                    # admin 把 env-blocked spec 复位 ready 而实现分支已 merge 进
                    # main 时，agent 验证确认「全部绿、无需改动」报成功是唯一正确
                    # 行为，被本哨误判空转 → 重派第二轮重蹈覆辙（$1.42 + 重建
                    # $1.30）。哨兵触发后先跑交付物守卫：交付物齐备 = 合法确认
                    # 完成，走正常成功收口（implemented → verifier）；
                    # 缺件仍按空转重派。守卫方法内自带无声明 spec 跳过。
                    # （分支零提交时 rev-list main..branch == 0 ⟺ 分支已并入 main，
                    # 无需另查 merge-base。）
                    if not self._pm._deliverable_gate_missing(spec_name, result):
                        self._pm.logger.warning(
                            "pm_engine",
                            f"零变更哨·确认型 no-op '{spec_name}' — 交付物齐备且分支"
                            f"零提交（已并入 main），走成功收口（不重派）"
                            f"run={result.run_id}",
                        )
                        self._pm.state_machine.transition(spec_name, "implemented")
                        self._pm.state_machine.update_spec(spec_name, {
                            "implementer_run": result.run_id,
                            "error": None,
                            "_zero_change_attempts": 0,
                        })
                        self._pm._enqueue_front(spec_name, "verifier")
                        return
                    attempts = 0
                    spec_entry = self._pm.state_machine.read_one(spec_name) or {}
                    try:
                        attempts = int(spec_entry.get("_zero_change_attempts", 0) or 0) + 1
                    except (TypeError, ValueError):
                        attempts = 1
                    # fix-zero-change-blindspot：区分「真空转」与「有工作未提交」。
                    # cleanup 前取证的 worktree_dirty 非空 = agent 确实动过文件
                    # （如用 Bash 写文件而非 Edit/Write），只是没 commit——不是空转，
                    # 重派文案须指导 commit，避免把真实工作当空转误报。
                    dirty = list(getattr(result, "worktree_dirty", None) or [])
                    if dirty:
                        err_note = (f"实现器报成功但分支零提交，worktree 有 "
                                    f"{len(dirty)} 个未提交修改（清单见日志）——不是空转；"
                                    f"重派时务必用 git commit 提交改动后再报完成")
                        self._pm.logger.warning(
                            "pm_engine",
                            f"零变更哨·未提交工作 '{spec_name}': {dirty[:10]}",
                        )
                    else:
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
                    self._pm.state_machine.update_spec(spec_name, updates)
                    self._pm.logger.error(
                        "pm_engine",
                        f"零变更成功哨触发 '{spec_name}'（第 {attempts} 次）— "
                        f"run={result.run_id}",
                    )
                    if attempts < 3:
                        self._pm._enqueue_front(spec_name, "implementer")
                    return

                # ── 交付物存在性守卫（add-implementer-deliverable-gate，D1/D3）──
                # 实现器宣称成功，但 SPEC 声明的核心交付物可能未真正落地
                # （v2-config-page 事故：agent 报成功但 config.json 未创建，0/11 验证全败）。
                # 在 merge 之前做纯文件系统存在性校验（校验基准为实现分支提交，
                # worktree 已在 run_implementer 内清理，仅分支留存），缺件则不合并、
                # 不推进状态，按失败重派并带精准缺件清单；连续 3 次封顶 → blocked 升级告警。
                if is_success:
                    missing = self._pm._deliverable_gate_missing(spec_name, result)
                    if missing:
                        # ── dispute 裁决通道（add-project-description 事故治理）──
                        # 实现 run 对缺件提出 deliverable-dispute 异议时不自动重派
                        # （误判场景重派必然同因失败，纯烧钱），blocked 交人工裁决。
                        # 质疑不得自动放行（防 agent 绕守卫），必须第三方裁决。
                        disputed = self._pm._disputed_deliverables(
                            impl_result, missing)
                        if disputed:
                            disp_q = "、".join(disputed)
                            updates: dict = {
                                "status": "blocked",
                                "tester_run": None,
                                "error": (
                                    f"交付物守卫缺件 [{disp_q}]，但实现 run 对其提出 "
                                    f"deliverable-dispute 异议（依据见该 run 的 "
                                    f".fenix-run-result.json findings 与旧分支成果）"
                                    f"— 已 blocked 待人工裁决，不自动重派"
                                ),
                            }
                            self._pm.state_machine.update_spec(spec_name, updates)
                            self._pm.logger.error(
                                "pm_engine",
                                f"交付物守卫缺件异议 '{spec_name}'（{disp_q}）— "
                                f"blocked 待裁决，不重派 run={result.run_id}",
                            )
                            return
                        # ── 缺件 LLM 终审与裁决机械执行（add-deliverable-declaration-triage）──
                        # 判缺件后不再直接打回/重派：先派 dispute-judge- run 语义终审
                        # （机械规则拦不住的声明 vs 现实矛盾由 LLM 裁决）。终审期间
                        # spec 置 blocked（error 含 run id 与「LLM 终审进行中」）阻断
                        # 轮询重派竞态（D5）。裁决机械执行（D4）：
                        #   typo → tasks.md 声明 path 修正 → 重跑守卫对账（4.4 防洗白）
                        #            → 通过则放行 merge；
                        #   reference → 声明软化（转软校验）；
                        #   missing → 既有打回/重派路径（带精准缺件清单）；
                        #   unclear → 既有 deliverable-dispute blocked 人工裁决话术。
                        adjudication = self._pm._adjudicate_deliverable_missing(
                            spec_name, result, impl_result, missing)
                        if adjudication.get("action") != "proceed":
                            return

                # ── tasks.md 收口复检门禁（add-tasksmd-relint-gate）──────────────
                # 2026-09-11 add-impl-terminal-nocommit-gate 事故：implementer 用 sed
                # 勾选 tasks.md 把任务行写成 `^- [x] 1.1 …`，分组完好任务行全灭，晋升
                # lint（立项期跑一次）穿透、收口期零校验 → dashboard 任务清单空白。
                # 此处为 merge 前事后复检：以实现分支 HEAD 的 tasks.md 为基准（merge 前
                # 主树版本 = 立项旧版本，读分支才反映中途编辑），违规 → 不合并不推进，
                # 走失败重派 + error 写违规明细与修正处方。读取失败/异常 → fail-open。
                if is_success:
                    try:
                        relint = self._pm._tasks_md_relint_from_branch(
                            spec_name, getattr(result, "branch", None))
                    except Exception as e:
                        self._pm.logger.warning(
                            "pm_engine",
                            f"tasks.md relint 执行异常（fail-open）'{spec_name}': {e}",
                        )
                        relint = []
                    if relint:
                        self._redispatch_tasks_relint(
                            spec_name, relint,
                            run_id=getattr(result, "run_id", "") or "")
                        return

                if is_success:
                    # ── impl-result per-spec 快照（fix-verified-gate-evidence-race D1）──
                    # implementer 成功即把已解析的结果 dict 原样原子快照到
                    # .fenix/verify-progress/<spec>/impl-result.json，供 verified→done
                    # 门禁 _task_completion_blocker 读取——门禁证据不再依赖跨 spec
                    # 共享文件 .fenix/.fenix-run-result.json（2026-09-07 事故：共享文件
                    # 被其它 spec 成功覆盖 → 门禁「无法证伪即放行」静默放行带未勾任务的
                    # spec）。快照写失败仅 WARNING 不阻塞（fail-open，门禁 fail-closed
                    # 兜底）；重派后新成功原子覆盖旧快照（幂等）。
                    # fast-track 车道同语义，写点在 _run_fast_track_flow 的 merge
                    # 成功收口处（2026-09-10 add-planready-artifact-gate 实证 fast-track
                    # 滞留 verified 同样存在跨 spec 覆盖窗口）。
                    if impl_result is not None:
                        try:
                            self._pm._write_impl_result_snapshot(spec_name, impl_result)
                        except Exception as e:
                            self._pm.logger.warning(
                                "pm_engine",
                                f"impl-result 快照写入失败 '{spec_name}'（非阻塞）: {e}",
                            )
                        # 消费后清理共享结果文件（D4，fast-track 车道同语义写点在
                        # _run_fast_track_flow）：本次采信消费 + 快照落盘之后删除
                        # 主树共享文件，仅当 stamp 严格匹配本 spec 时删除。删除失败
                        # 仅 WARNING 不阻塞（fail-open，残留由 stamp 严格校验兜底）。
                        self._pm._cleanup_shared_result_file(spec_name)
                    # 计数对账（fix-budget-counting-semantics D3）：守卫放行/merge
                    # 收工后回读 used 与正常收工 run 数比对，偏差记 WARNING。
                    self._pm._reconcile_impl_budget(spec_name)
                    # Merge worktree branch back into main tree before advancing state.
                    # worktree 已被 agent_runner 清理，但分支仍保留（success 路径不删分支），
                    # 所以用分支名直接 merge。
                    merge_ok = True
                    merge_error = ""
                    merge_info = None
                    conflict_files = []
                    if result.branch:
                        merge_info = wm.merge_back_from_branch(result.branch)
                        merge_ok, merge_error = merge_info  # 兼容 (bool, str) 解包
                        # guard 段内 pop 冲突自愈丢弃的用户改动清单（admin 告警用）
                        conflict_files = list(wm.last_stash_pop_conflicts)

                    if not merge_ok:
                        # ── 预演语义冲突直通 repair（add-merge-tree-rehearsal D2）──
                        # merge-tree 预演在主树零污染点检出语义冲突（rehearsed=True）：
                        # 未发生真合并，熔断语义上「merge 失败」并不成立——不经
                        # _merge_fp/_merge_streak 记账、不做 ready 降级，spec 保持
                        # in-flight 直接派 repair agent 在实现分支内把 main 合入解决。
                        # 轮次上限（_repair_round）超限时回退现行 fallback 重派兜底。
                        if getattr(merge_info, "rehearsed", False):
                            self._direct_rehearsed_to_repair(
                                spec_name, merge_info, result.branch, merge_error)
                            return
                        # merge 失败：指纹熔断（fix-fenix-token-waste）。
                        # 同一错误指纹连续失败 ≥ 阈值 → spec 进入 blocked 停止自动重试，
                        # 避免「根因不消除 → 全量重跑 → 再败」的无限烧钱循环。
                        spec_entry = self._pm.state_machine.read_one(spec_name)
                        max_r = self._pm._get_config("agents.max_retries", 3)
                        fp = self._pm._merge_fingerprint(merge_error)
                        prev_fp = spec_entry.get("_merge_fp")
                        try:
                            prev_streak = int(spec_entry.get("_merge_streak", 0) or 0)
                        except (TypeError, ValueError):
                            prev_streak = 0
                        streak = prev_streak + 1 if prev_fp == fp else 1
                        final_error = f"Merge-back failed (fp={fp}): {merge_error}"

                        # 状态回写保护（fix-startup-double-dispatch）：
                        # merge-back 失败回写 ready 前，检查 spec 当前状态——若已在
                        # testing/implemented 且存在活跃 tester run，不降级 ready，
                        # 只记录冲突并待验证结束后统一处置（避免覆写在飞验证态）。
                        current_status = (spec_entry or {}).get("status", "")
                        active_tester = (spec_entry or {}).get("tester_run")
                        if current_status in ("testing", "implemented") and active_tester:
                            self._pm.logger.warning(
                                "pm_engine",
                                f"Merge-back failed for '{spec_name}' but spec is in "
                                f"'{current_status}' with active tester run {active_tester} "
                                f"— not downgrading to ready, conflict logged",
                            )
                            # 记录冲突但不降级状态，保持 testing/implemented
                            self._pm.state_machine.update_spec(spec_name, {
                                "error": final_error,
                                "_merge_fp": fp,
                                "_merge_streak": streak,
                            })
                            return

                        breaker_threshold = self._pm._get_config("agents.merge_breaker_threshold", 2)
                        if streak >= breaker_threshold:
                            # 熔断触发：blocked 后 repair 通道一并停止
                            # （spec-merge-circuit-breaker：repair 不绕过熔断）。
                            self._pm.state_machine.transition(spec_name, "blocked")
                            self._pm.state_machine.update_spec(spec_name, {
                                "error": final_error,
                                "_merge_fp": fp,
                                "_merge_streak": streak,
                                "_retry_count": 0,
                            })
                            self._pm.logger.error(
                                "pm_engine",
                                f"Circuit breaker tripped for '{spec_name}' (fp={fp}) — spec blocked",
                            )
                        elif self._pm._should_enter_repair(
                                spec_name, merge_info, streak, breaker_threshold):
                            # ── repair 通道（add-merge-back-repair-lane）──
                            # 语义冲突失败且熔断未触发：派 repair agent 原地修复
                            #（把 main 合入分支解决冲突），而非 abort 后全新重派。
                            self._pm._dispatch_repair_lane(
                                spec_name, merge_info, result.branch,
                                fp=fp, streak=streak,
                            )
                        else:
                            try:
                                prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
                            except (TypeError, ValueError):
                                prev_retries = 0
                            retries = prev_retries + 1
                            self._pm.state_machine.update_spec(spec_name, {
                                "status": "ready",
                                "error": final_error,
                                "_merge_fp": fp,
                                "_merge_streak": streak,
                                "_retry_count": retries,
                            })
                            self._pm.logger.warning(
                                "pm_engine",
                                f"Retry {retries}/{max_r} for '{spec_name}' (merge-back failed)",
                            )
                    else:
                        # stash 恢复已在 merge_back_from_branch 的 guard 段内完成
                        # （fix-autostash-orphans），此处只推进状态。
                        self._pm.state_machine.transition(spec_name, "implemented")
                        self._pm.state_machine.update_spec(spec_name, {
                            "implementer_run": result.run_id,
                            # 记录真实实现分支（带时间戳后缀）：push 时按此分支推送，
                            # 否则回退 fenix/<spec> 不存在导致 auto-push 全部失败。
                            "branch": getattr(result, "branch", None) or None,
                            "error": None,
                            "_retry_count": 0,
                            "_merge_fp": None,
                            "_merge_streak": 0,
                            # 派发成功即清零锁冲突计数（improve-run-lifecycle-governance D5）
                            **self._pm._clear_dispatch_conflict(spec_name),
                        })
                        # pop 冲突自愈后：被丢弃的 stash 改动文件清单写入 error 字段，
                        # 触发 admin 告警（stash 条目保留、可 git stash show 找回，
                        # 不阻塞 merge-back 与状态推进）。须放在上面 update_spec(error=None)
                        # 之后，避免被清空。见 fix-stashpop-deadlock。
                        if conflict_files:
                            self._pm._report_stash_pop_conflict(
                                spec_name, conflict_files, merge_info=merge_info)
                        # 写侧确定性回写：把已完成的任务勾选同步进主树 tasks.md
                        # （add-task-progress-sync）。任何异常都不阻塞 run 终态主流程。
                        try:
                            self._pm._sync_task_progress(spec_name)
                        except Exception as e:
                            self._pm.logger.warning(
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
                            self._pm.logger.warning(
                                "pm_engine",
                                f"consume_legacy 失败 '{spec_name}'（非阻塞）: {e}",
                            )
                        # Immediately queue verifier at FRONT so it runs next
                        self._pm._enqueue_front(spec_name, "verifier")
                        self._pm.logger.info("pm_engine", f"Implement done, verifier queued for '{spec_name}'")
                else:
                    # ── 人工取消 hold-state（add-run-cancel D4）──────
                    # 被取消的 run（cancelled=True）：只更新 error 字段（含
                    # 「run 被人工取消」与 reason），不翻转 status、不动
                    # _retry_count/_merge_fp/_merge_streak、不入队重派。
                    # 后续重排完全交给既有机制（stuck 检测/恢复扫描）或
                    # 管理员人工操作（freeze 等）。
                    if getattr(result, "cancelled", False):
                        cancelled_err = (
                            f"run 被人工取消：{final_error}"
                            if final_error else "run 被人工取消"
                        )
                        self._pm.logger.warning(
                            "pm_engine",
                            f"run 被人工取消 '{spec_name}' — hold-state，"
                            f"不重试/不重派: {cancelled_err}",
                        )
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": cancelled_err,
                            # 取消保持持久标记（fix-cancel-holdstate-recovery D1）：
                            # 随 STATE.md 存活，重启恢复/监测链路据此跳过该 spec。
                            "_cancelled_hold": True,
                        })
                        return
                    # ── 死亡 run 豁免（fix-budget-counting-semantics D1）──────
                    # 无收工结果产出（.fenix-run-result.json 缺失）＝ run 异常
                    # 死亡（进程消失/零输出/网关链路耗尽）：回退本次启动的计数。
                    # 有收工结果的正常失败（impl_status=error）不豁免——既有
                    # 「正常失败仍计数」语义不变。
                    if impl_status is None:
                        self._pm._exempt_dead_run_budget(
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
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Provider circuit open for '{spec_name}' — holding state, "
                            f"no retry/state flip: {final_error}",
                        )
                        # 写入 error 供 dashboard/admin 可见，但不翻转状态、不增 retry
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": final_error,
                        })
                    elif final_error and "[provider-transient]" in final_error:
                        # fix-provider-transient-backoff（D4）：transient 终态——不走
                        # _retry_count 递增/清零路径，改排程等待后重派（复用
                        # instant_fail_recovery 定时器模式，`transient_redispatch_delay_seconds`
                        # 缺省 600s）。死亡 run 预算豁免行为保持不变。
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Provider transient for '{spec_name}' — scheduling "
                            f"delayed redispatch, no retry/state flip: {final_error}",
                        )
                        # 写入 error 供 dashboard 可见，但不翻转状态
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": final_error,
                        })
                        self._schedule_transient_recovery(spec_name)
                    else:
                        # Retry or mark error
                        spec_entry = self._pm.state_machine.read_one(spec_name)
                        try:
                            prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
                        except (TypeError, ValueError):
                            prev_retries = 0
                        retries = prev_retries + 1
                        max_r = self._pm._get_config("agents.max_retries", 3)
                        if retries >= max_r:
                            self._pm.state_machine.update_spec(spec_name, {
                                "status": "ready",
                                "error": final_error,
                                "_retry_count": 0,
                            })
                            self._pm.logger.error(
                                "pm_engine",
                                f"All retries exhausted for '{spec_name}'",
                            )
                            # 3.2 行动性同状态更新补发（fix-dispatch-orphan D1）：
                            # 失败落回 ready 后可能无后续事件触达（daemon 重启间隙 /
                            # 轮询节流），立即重新排队实现器，避免滞留为孤儿。
                            self._pm._enqueue(spec_name, "implementer")
                        else:
                            self._pm.state_machine.update_spec(spec_name, {
                                "status": "ready",
                                "error": final_error,
                                "_retry_count": retries,
                            })
                            self._pm.logger.warning(
                                "pm_engine",
                                f"Retry {retries}/{max_r} for '{spec_name}'",
                            )

            elif agent_type == "verifier":
                self._pm._run_verification_pipeline(spec_name)

        except Exception as e:
            self._pm.logger.error("pm_engine", f"Agent run exception: {e}")
            # 派发/执行异常必须回滚滞留中间态的 spec（fix: 伪 bug 卡死根因）。
            # 此前只记日志：日限额耗尽等异常使 run 从未启动，spec 却已滞留在
            # implementing/testing，无 run 痕迹、永久卡死。
            self._pm._rollback_failed_dispatch(spec_name, agent_type, e)
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
            self._pm._process_queue()


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
            spec_entry = self._pm.state_machine.read_one(spec_name)
            if not spec_entry:
                return
            status = spec_entry.get("status")
            backoff_until = int(datetime.now(timezone.utc).timestamp()) + 300
            if agent_type == "verifier" and status == "testing":
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "implemented",
                    "tester_run": None,
                    "error": f"Verification infrastructure failure (retryable): {exc}",
                    "_dispatch_backoff_until": backoff_until,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' testing → implemented (verifier never started): {exc}",
                )
                self._pm._enqueue(spec_name, "verifier")
            elif agent_type in ("implementer", "fast-track") and status == "implementing":
                # 死亡 run 豁免（fix-budget-counting-semantics D1）：异常路径＝
                # run 无收工结果产出（进程消失/零输出/网关链路耗尽），回退本次
                # 启动的预算计数。计数在 worker 启动处先行递增，此处补偿回退。
                self._pm._exempt_dead_run_budget(
                    spec_name, f"dispatch exception: {str(exc)[:80]}"
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "ready",
                    "implementer_run": None,
                    "tester_run": None,
                    "branch": None,
                    "error": None,
                    "_last_dispatch_error": f"Implementation dispatch failed (retryable): {exc}",
                    "_dispatch_backoff_until": backoff_until,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' implementing → ready "
                    f"({agent_type} never started): {exc}",
                )
                self._pm._enqueue(spec_name, agent_type)
        except Exception as e2:
            self._pm.logger.error("pm_engine", f"State rollback failed for '{spec_name}': {e2}")


    def _report_stash_pop_conflict(self, spec_name: str, conflict_files: list,
                                   merge_info=None) -> None:
        """pop 冲突自愈后上报被丢弃的 stash 改动文件清单（fix-stashpop-deadlock）。

        主树已通过 checkout HEAD + reset 自愈回到干净可写状态，merge 结果不丢失、
        状态正常推进到 implemented。上报走双通道（fix-mergeback-stashpop-silent-loss
        D1）：既有 spec.error 字段写入保持不变（向后兼容 dashboard 时间轴读侧）；
        另经 admin_store.append 直发一条 ``signal_type=stash_pop_conflict`` 告警——
        通知不再依赖瞬态 error 字段或日志指纹风暴规则。告警 description 含 spec 名、
        冲突文件清单、stash 条目去向（保留/drop + sha）、逐文件找回命令，以及
        merge-back 前的 WIP 重叠预检清单（若有）。

        error 文本格式（供 dashboard/admin 可读）：``stash pop conflict: files=[...]``
        """
        if not conflict_files:
            return
        msg = f"stash pop conflict: files={conflict_files}"
        try:
            self._pm.state_machine.update_spec(spec_name, {"error": msg})
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"stash pop conflict 上报失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' {msg} —— stash 保留，可用 git stash show 找回被丢弃改动",
        )
        # admin 告警直发（fix-mergeback-stashpop-silent-loss D1）：低频事件、
        # 无风暴风险，不加节流。任何异常都不阻塞 merge-back 主流程。
        try:
            from core.admin_store import AdminStore, SIGNAL
            # 条目去向从 worktree_manager 读（dispatch 层不持锁，读实例属性足够——
            # guard 段已结束、无并发写者）。
            try:
                fate = dict(self._pm.agent_runner.worktree_manager.last_stash_entry_fate)
            except Exception:
                fate = {"kept": True, "sha": ""}
            sha = fate.get("sha", "") or ""
            short_sha = sha[:12] if sha else ""
            if fate.get("kept"):
                fate_desc = (
                    f"stash 条目保留在栈中（栈顶 sha {short_sha}，"
                    f"git stash list 可见）" if short_sha else "stash 条目保留在栈中"
                )
            else:
                fate_desc = (
                    f"stash 版已被合并结果完全取代，条目已自动 drop"
                    f"（commit {short_sha}，gc 前可按 sha 找回）"
                    if short_sha else "stash 条目已被自动 drop"
                )
            recover_cmds = "; ".join(
                f"git show {sha}:{f}" for f in conflict_files
            ) if sha else "git stash show / git stash list 人工核对"
            overlap = list(getattr(merge_info, "wip_overlap", []) or [])
            overlap_desc = (
                f"；merge-back 前 WIP 重叠预检命中 {len(overlap)} 文件"
                f"（可能与本次丢弃相关）：{overlap}" if overlap else ""
            )
            description = (
                f"SPEC '{spec_name}' merge-back stash pop 冲突已自愈："
                f"{len(conflict_files)} 个文件的未提交改动被丢弃 "
                f"({', '.join(conflict_files)})。{fate_desc}{overlap_desc}。"
                f"逐文件找回：{recover_cmds}"
            )
            store = AdminStore(self._pm.project_root, self._pm.logger)
            store.append({
                "kind": SIGNAL,
                "signal_type": "stash_pop_conflict",
                "spec": spec_name,
                "severity": "major",
                "description": description,
                "evidence": {"conflict_files": list(conflict_files),
                             "stash_kept": bool(fate.get("kept")),
                             "stash_sha": sha, "wip_overlap": overlap},
                "recommended_action": (
                    "git stash list 查条目去向；按逐文件 git show <sha>:<file> 命令"
                    "核对内容，仍需要的改动手动落回工作区；确认零独有内容后 "
                    "git stash drop 清理"),
            })
            self._pm.logger.info(
                "pm_engine",
                f"stash_pop_conflict 告警已写入 admin store: '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"stash_pop_conflict 告警写入失败 '{spec_name}'（非阻塞）: {e}",
            )

    # ── 缺件 LLM 终审与裁决机械执行（add-deliverable-declaration-triage D3/D4）──

    def _build_dispute_judge_input(self, spec_name: str, impl_result,
                                   missing: list) -> dict:
        """组装 dispute-judge 输入（4.1）：缺件 + basename 候选 + spec 语境 + findings。

        Returns:
            dict：``{"spec", "missing": [{"path", "candidates"}],
            "spec_context": {"excerpts", "declared_entries"},
            "findings": [...]}``。任一部件读取失败静默降级（fail-open）。
        """
        from core.deliverables import match_basename_in_tree

        missing_entries = []
        for m in missing:
            candidates = []
            try:
                candidates = match_basename_in_tree(self._pm.project_root, m)
            except Exception:
                candidates = []
            missing_entries.append({"path": m, "candidates": candidates})

        findings = []
        if isinstance(impl_result, dict):
            findings = impl_result.get("findings") or []

        return {
            "spec": spec_name,
            "missing": missing_entries,
            "spec_context": self._dispute_spec_context(spec_name, missing),
            "findings": findings,
        }

    def _dispute_spec_context(self, spec_name: str, missing: list) -> dict:
        """spec 三文档语境摘录：含缺件路径的段落 + Deliverables 声明段全文。

        对 proposal.md/design.md/tasks.md/specs/*.md：以缺件路径为关键词抽取
        命中行 ±2 行上下文（每文档独立段落清单）；tasks.md 的声明段经
        ``extract_declared_entries`` 结构化摘录。读取失败静默跳过（fail-open）。
        """
        import re as _re
        from pathlib import Path as _Path

        spec_dir = _Path(self._pm.project_root) / "spec" / "changes" / spec_name
        docs = {}
        for name in ("proposal.md", "design.md", "tasks.md"):
            p = spec_dir / name
            if p.is_file():
                try:
                    docs[name] = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    pass
        specs_dir = spec_dir / "specs"
        if specs_dir.is_dir():
            try:
                for f in sorted(specs_dir.rglob("*.md")):
                    if f.is_file():
                        docs[f.name] = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass

        excerpts = {}
        for name, text in docs.items():
            lines = text.splitlines()
            hits: list = []
            for i, line in enumerate(lines):
                if any(m in line for m in missing):
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    block = "\n".join(lines[start:end])
                    if block not in hits:
                        hits.append(block)
            if hits:
                excerpts[name] = hits

        context: dict = {"excerpts": excerpts}
        try:
            from core.deliverables import extract_declared_entries
            entries = extract_declared_entries(spec_dir)
            if entries:
                context["declared_entries"] = entries
        except Exception:
            pass
        return context

    def _read_dispute_verdicts(self, spec_name: str, judge_run_id: str,
                               judge_result) -> "dict | None":
        """读取 dispute-judge 裁决 JSON（4.2 结果消费）。

        判据：run 未成功收工 / 结果文件缺失或 JSON 不合法 / 顶层 status 非
        success / verdicts 缺失或非列表 → 返回 None（调用方等价 ``unclear``，
        全部待裁缺件转人工）。

        Returns:
            合法裁决 JSON dict 或 None。
        """
        result_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "dispute_judge_result.json"
        )
        if judge_result is None or not getattr(judge_result, "success", False):
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge run 失败 '{spec_name}'（等价 unclear）: "
                f"{getattr(judge_result, 'error', '') or ''}",
            )
            return None
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果 JSON 不合法 '{spec_name}'（等价 unclear）",
            )
            return None
        if not isinstance(data, dict) or data.get("status") != "success":
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果 status 非 success '{spec_name}'（等价 unclear）",
            )
            return None
        verdicts = data.get("verdicts")
        if not isinstance(verdicts, list) or not verdicts:
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果缺 verdicts '{spec_name}'（等价 unclear）",
            )
            return None
        return data

    def _preclassify_missing(self, spec_name: str, result,
                             missing: list) -> dict:
        """守卫缺件确定性预分类（add-declaration-premechanize D4，Task 4.1-4.3）。

        在组装 judge 输入之前，对缺件清单做确定性分类：命中不可交付模式
        （gitignored / 仓库外）的条目直接机械软化 + 审计 + 重跑守卫；全清走
        放行分支且不派 judge run；剩余项才进入 dispute-judge。

        预分类异常全量回退既有 judge 流程（fail-open：不因解析/软化异常阻塞
        终审）。

        Returns:
            {"action": "proceed"} → 全部缺件已确定性软化，守卫重跑通过；
            {"action": "continue", "remaining": [...]} → 仍有剩余，带入 judge；
            {"action": "fallback"} → 预分类不可用，回退既有 judge 流程
            （missing 不变）。
        """
        from core.deliverables import classify_unsatisfiable, extract_declared_entries

        # 声明段无条目（存量 spec 正则提取）→ 不预分类，回退 judge
        spec_dir = self._pm.project_root / "spec" / "changes" / spec_name
        entries = extract_declared_entries(spec_dir)
        if not entries:
            return {"action": "fallback"}

        # 快照软化前 tasks.md 声明段（供审计 diff.before）
        before_text = ""
        tasks_path = spec_dir / "tasks.md"
        if tasks_path.exists():
            try:
                before_text = tasks_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                before_text = ""

        # 将条目列表转为 path → entry 映射（按 path 查找）
        entry_by_path: dict = {}
        for e in entries:
            if isinstance(e, dict) and e.get("path"):
                entry_by_path[e["path"]] = e

        # 分类：确定性命中 → deterministic；声明段无该条目或不命中 → 留在 remaining
        deterministic: list = []
        remaining: list = []
        for m in missing:
            entry = entry_by_path.get(m)
            if entry and classify_unsatisfiable(entry, self._pm.project_root):
                deterministic.append(m)
            else:
                remaining.append(m)

        if not deterministic:
            # 无可软化缺件 → 回退 judge 流程（remaining == missing）
            return {"action": "fallback"}

        # 逐条软化（单条异常留在 remaining 并 warning）
        diff_by_element: dict = {}
        for m in deterministic[:]:  # copy以便异常时移除
            entry = entry_by_path[m]
            try:
                from core.deliverables import soften_declared_kind
                diff = soften_declared_kind(spec_dir, m)
                diff_by_element[m] = diff
            except Exception as exc:
                # 单条软化异常：留在 remaining 清单（异常不阻塞其余）
                remaining.append(m)
                deterministic.remove(m)
                self._pm.logger.warning(
                    "pm_engine",
                    f"预分类软化异常 '{spec_name}'（{m} 回退 judge）: {exc}",
                )

        if not deterministic:
            # 全部软化异常 → 回退 judge
            return {"action": "fallback"}

        # 审计留痕（reasoning 前缀 guard-preclassify）
        try:
            from core.admin_store import DisputeAuditStore
            # after 已是软化后文本（soften_declared_kind 已写盘）
            after_text = ""
            if tasks_path.exists():
                after_text = tasks_path.read_text(encoding="utf-8")
            DisputeAuditStore(self._pm.project_root, self._pm.logger).append({
                "spec": spec_name,
                "trigger_run_id": "",
                "judge_run_id": "",
                "verdicts": [
                    {
                        "element": m,
                        "verdict": "reference",
                        "reasoning": "guard-preclassify: gitignored/outside-root",
                    }
                    for m in deterministic
                ],
                "diff": {
                    "before": before_text,
                    "after": after_text,
                },
            })
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"预分类审计写盘失败 '{spec_name}'（非阻塞）: {e}",
            )

        # 重跑守卫对账
        try:
            gate_result = self._pm._deliverable_gate_missing(spec_name, result)
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"预分类后守卫重跑异常 '{spec_name}'（回退 judge）: {e}",
            )
            # 异常回退：把已软化条目放回 remaining（soften 已写盘，无法回滚）
            remaining.extend(deterministic)
            return {"action": "fallback"}

        if not gate_result:
            # 全清 → 走「裁决执行后守卫重跑通过」放行分支
            self._pm.logger.warning(
                "pm_engine",
                f"预分类缺件全清 '{spec_name}' — 守卫重跑通过，放行 merge",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "status": "implementing",
                "error": None,
            })
            return {"action": "proceed"}

        # 仍有剩余 → remaining 带入 judge
        return {"action": "continue", "remaining": remaining}

    def _adjudicate_deliverable_missing(self, spec_name: str, result,
                                        impl_result, missing: list) -> dict:
        """缺件 LLM 终审 + 裁决机械执行（D3/D4，Tasks 4.1-4.4）。

        在既有 dispute 异议通道之后调用（实现 run 已对缺件提出 deliverable-dispute
        异议的 spec 走 blocked 人工，不进入终审）。

        预分类（add-declaration-premechanize D4，Task 4.1-4.3）：
        - 组装 judge 输入之前，先对缺件清单做确定性分类：命中不可交付模式
          （gitignored / 仓库外）的条目直接机械软化 kind → reference + 审计
          （reasoning 前缀 guard-preclassify）+ 重跑守卫；全清则走放行分支且
          不派 judge run；剩余项才进入既有 dispute-judge 流程。
        - 预分类异常（声明段解析失败/软化改写异常）→ 全量回退既有 judge 流程。

        流程：

        1. spec 置 blocked（error 含 dispute-judge run id 与「LLM 终审进行中」），
           阻断轮询/巡检重派竞态（D5）；
        2. 组装 judge 输入并派单轮 dispute-judge run（主树只读、无 worktree）；
        3. 读取裁决 JSON（4.2）：run 失败/超时/JSON 不合法/verdicts 缺失 →
           全部待裁缺件等价 unclear；
        4. 按裁决机械执行（4.3）：typo → tasks.md 声明 path 确定性替换为
           actual_path（同名去重）；reference → 条目 kind 软化；missing/unclear
           保持缺件处置；
        5. 防洗白闸门（4.4）：typo 修正 + reference 软化后重跑守卫对账——
           actual_path 在实现分支真实存在才放行 merge；仍缺失按缺件走既有
           打回路径（修正声明 ≠ 放行缺件）；
        6. typo/reference 裁决执行落 dispute 审计流（4.5）。

        Returns:
            dict：{"action": "proceed"} → 守卫重跑通过/缺件已软化，调用方继续
            merge 推进；{"action": "handled"} → 已终态处置（打回重派 / blocked
            人工 / 防洗白打回），调用方直接 return。
        """
        # ── 预分类（add-declaration-premechanize D4）：确定性缺件先行软化 ──
        # 在组装 judge 输入之前，先对缺件清单做确定性分类：命中不可交付模式
        # 的条目直接机械软化 + 审计 + 重跑守卫；全清走放行分支且不派 judge run；
        # 剩余项才进入 dispute-judge。预分类异常全量回退既有 judge 流程。
        preclassify_result = self._preclassify_missing(spec_name, result, missing)
        if preclassify_result.get("action") == "proceed":
            return preclassify_result
        # remaining 是预分类后仍存在的缺件清单；若预分类全清则 proceed，
        # 否则剩余项带入后续 judge 流程（judge 输入只含剩余项）。
        remaining = preclassify_result.get("remaining", missing)
        # judge 输入快照：typo_fixed_paths 构造需基于 judge 的输入清单
        # （后续 remaining 会被守卫重跑结果覆盖，不可再作 judge 输入引用）。
        judge_input_paths = list(remaining)

        judge_run_id = f"dispute-judge-{spec_name}-{int(time.time())}"
        # 1. 终审期间 spec 置 blocked（error 含 run id），阻断重派竞态
        self._pm.state_machine.update_spec(spec_name, {
            "status": "blocked",
            "tester_run": None,
            "error": (f"交付物守卫缺件 [{', '.join(remaining)}] — LLM 终审进行中"
                      f"（judge run {judge_run_id}）"),
        })
        self._pm.logger.warning(
            "pm_engine",
            f"交付物守卫缺件 '{spec_name}' 进入 LLM 终审（{judge_run_id}）",
        )

        # 2. 组装输入并派单轮 dispute-judge run（仅含预分类后剩余项）
        judge_input = self._build_dispute_judge_input(spec_name, impl_result, remaining)
        judge_result = None
        try:
            judge_result = self._pm.agent_runner.run_dispute_judge(
                spec_name, judge_input, run_id=judge_run_id)
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"dispute judge 派发异常 '{spec_name}'（等价 unclear）: {e}",
            )
            judge_result = None

        # 3. 结果消费：非法裁决 → 全部待裁缺件等价 unclear
        verdict_data = self._read_dispute_verdicts(spec_name, judge_run_id,
                                                   judge_result)
        verdict_by_element = {}
        if verdict_data is not None:
            for v in verdict_data.get("verdicts") or []:
                if isinstance(v, dict) and v.get("element"):
                    verdict_by_element[str(v["element"])] = v

        def _verdict_of(path: str) -> dict:
            v = verdict_by_element.get(path)
            if isinstance(v, dict) and v.get("verdict") in (
                    "typo", "reference", "missing", "unclear"):
                return v
            return {"verdict": "unclear"}

        # 4. 裁决机械执行：typo 修正 / reference 软化（逐条，失败等价 unclear）
        executed_verdicts: list = []
        diff_by_element: dict = {}
        for m in remaining:
            v = _verdict_of(m)
            verdict = v.get("verdict")
            try:
                if verdict == "typo":
                    actual_path = str(v.get("actual_path") or "").strip()
                    if not actual_path:
                        verdict_by_element[m] = {"verdict": "unclear"}
                        continue
                    from core.deliverables import replace_declared_path
                    diff = replace_declared_path(
                        self._pm.project_root / "spec" / "changes" / spec_name,
                        m, actual_path)
                    diff_by_element[m] = diff
                    executed_verdicts.append({"element": m, **v})
                    self._pm.logger.warning(
                        "pm_engine",
                        f"dispute judge 裁决 typo '{spec_name}': "
                        f"{m} → {actual_path}（声明段已修正）",
                    )
                elif verdict == "reference":
                    from core.deliverables import soften_declared_kind
                    diff = soften_declared_kind(
                        self._pm.project_root / "spec" / "changes" / spec_name, m)
                    diff_by_element[m] = diff
                    executed_verdicts.append({"element": m, **v})
                    self._pm.logger.warning(
                        "pm_engine",
                        f"dispute judge 裁决 reference '{spec_name}': "
                        f"{m} 已软化为 reference（转软校验）",
                    )
            except Exception as e:
                # 声明段修正失败（并发改写/格式漂移）→ 该条等价 unclear（D6）
                verdict_by_element[m] = {"verdict": "unclear"}
                self._pm.logger.warning(
                    "pm_engine",
                    f"dispute judge 裁决执行失败 '{spec_name}'（{m} 等价 unclear）: {e}",
                )

        # 5. 审计留痕（4.5）：typo/reference 裁决执行落 dispute 审计流
        if executed_verdicts:
            try:
                from core.admin_store import DisputeAuditStore
                DisputeAuditStore(self._pm.project_root, self._pm.logger).append({
                    "spec": spec_name,
                    "trigger_run_id": getattr(result, "run_id", "") or "",
                    "judge_run_id": judge_run_id,
                    "verdicts": verdict_data.get("verdicts")
                    if verdict_data else executed_verdicts,
                    "diff": {
                        k: {"before": d.get("before"), "after": d.get("after")}
                        for k, d in diff_by_element.items()
                    },
                })
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine", f"dispute 审计写盘失败 '{spec_name}'（非阻塞）: {e}",
                )

        # 6. 防洗白闸门（4.4）：修正后重跑守卫对账——actual_path 在实现分支
        # 真实存在才放行；仍缺失按缺件走既有打回路径（修正声明 ≠ 放行缺件）。
        remaining = self._pm._deliverable_gate_missing(spec_name, result)
        if not remaining:
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 裁决执行后守卫重跑通过 '{spec_name}' — 放行 merge",
            )
            # 终审期间置 blocked 属临时态：恢复 in-flight（implementing），
            # worker 合并路径的 implementing → implemented 转换才合法
            self._pm.state_machine.update_spec(spec_name, {
                "status": "implementing",
                "error": None,
            })
            return {"action": "proceed"}

        # 仍有缺件：分类 remaining 的归宿。remaining 可能含 typo 修正后的
        # actual_path（非原 element）——凡能追溯到「已执行 typo 修正」或
        # 「missing 裁决」的路径按既有打回路径处置（防洗白：修正声明 ≠ 放行
        # 缺件）；unclear 项（含裁决执行失败/判据不明）→ blocked 人工裁决。
        typo_fixed_paths = set()
        for m in judge_input_paths:
            v = _verdict_of(m)
            if v.get("verdict") == "typo":
                ap = str(v.get("actual_path") or "").strip()
                if ap:
                    typo_fixed_paths.add(ap)
        unclear_remaining = []
        for p in remaining:
            # typo 修正后的 actual_path：修正声明后文件仍不存在 = 防洗白 → 打回
            if p in typo_fixed_paths:
                continue
            v = _verdict_of(p)
            if v.get("verdict") == "unclear":
                unclear_remaining.append(p)
                continue
            # 非 unclear：missing 裁决的原 element 按缺件打回；既非原 element
            # 又非任何修正路径 → 裁决未覆盖，保守按 unclear 转人工（防 judge
            # 输出与清单不一致）。
            if p in judge_input_paths:
                continue
            unclear_remaining.append(p)
        if unclear_remaining:
            u_q = "、".join(unclear_remaining)
            self._pm.state_machine.update_spec(spec_name, {
                "status": "blocked",
                "tester_run": None,
                "error": (
                    f"交付物守卫缺件 [{u_q}] LLM 终审裁决 unclear/不可信 — "
                    f"已 blocked 待人工裁决，不自动重派（judge run {judge_run_id}）"
                ),
            })
            self._pm.logger.error(
                "pm_engine",
                f"交付物守卫缺件终审 unclear '{spec_name}'（{u_q}）— blocked 待人工",
            )
            return {"action": "handled"}

        # 真缺件 / typo 防洗白落空：既有打回/重派路径（带精准缺件清单）
        self._redispatch_for_missing(spec_name, result, remaining)
        return {"action": "handled"}

    def _redispatch_for_missing(self, spec_name: str, result, missing_list: list) -> None:
        """缺件打回/重派（add-implementer-deliverable-gate 既有路径，4.3 missing）。

        注册分支遗产（供后继 run 收编）→ 重试计数 → 重派 implementer；
        连续 ``agents.max_retries`` 次封顶 blocked。自 judge 终审进入的调用
        同样走此路径——judge 不放行不存在的文件（防洗白，D4）。
        """
        _wm = self._pm.agent_runner.worktree_manager
        _branch = getattr(result, "branch", None)
        if _branch and hasattr(_wm, "register_legacy"):
            _wm.register_legacy(spec_name, None, _branch)
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
        except (TypeError, ValueError):
            prev_retries = 0
        retries = prev_retries + 1
        max_r = self._pm._get_config("agents.max_retries", 3)
        missing_q = "、".join(missing_list)
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
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.error(
            "pm_engine",
            f"交付物守卫触发 '{spec_name}'（缺件 {missing_q}）— "
            f"run={getattr(result, 'run_id', '') or ''}",
        )
        if updates["status"] != "blocked":
            self._pm._enqueue_front(spec_name, "implementer")

    # ── tasks.md 收口复检门禁处置（add-tasksmd-relint-gate）─────────────────
    # 读取与判定逻辑在 VerificationPipeline._tasks_md_relint_from_branch /
    # _tasks_md_relint_from_worktree（经 PMEngine 门面 com 组件委托访问，
    # design D3 规则 3）；本处仅处置违规（重派/计数），不重复实现判定。

    def _redispatch_tasks_relint(self, spec_name: str, relint: list,
                                 *, agent_type: str = "implementer",
                                 run_id: str = "") -> None:
        """tasks.md 收口复检违规处置：不合并、不推进，按失败重派。

        error 写违规明细（逐条）与修正处方；连续计数沿用既有重派语义
        （``_retry_count`` 递增，``agents.max_retries`` 封顶 blocked），
        与交付物守卫缺件处置同构。
        """
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
        except (TypeError, ValueError):
            prev_retries = 0
        retries = prev_retries + 1
        max_r = self._pm._get_config("agents.max_retries", 3)
        detail = "；".join(relint)
        err_note = (
            f"tasks.md 收口复检违规 — 不合并不推进，重派修正（第 {retries} 次）："
            f"{detail}。修正处方：任务行行首必须为 `- [ ]` / `- [x]`；"
            f"若现为 `^- [x]` 即 sed 转义损伤，请改回 `- [` 并恢复 checkbox"
        )
        updates: dict = {
            "status": "ready",
            "error": err_note,
            "_retry_count": retries,
        }
        if retries >= max_r:
            updates["status"] = "blocked"
            updates["tester_run"] = None
            updates["error"] = (
                f"tasks.md 收口复检连续 {max_r} 次违规 — 已 blocked，"
                f"需人工修复 tasks.md（行首 `- [ ]`/`- [x]`）"
            )
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.error(
            "pm_engine",
            f"tasks.md relint 触发 '{spec_name}'（第 {retries} 次）— "
            f"run={run_id or 'n/a'}",
        )
        if updates["status"] != "blocked":
            self._pm._enqueue_front(spec_name, agent_type)

    # ── fast-track 单 run 全包 worker（add-fast-track-mode D1/D4/D5/D6）──

    def _run_fast_track_worker(self, spec_name: str) -> None:
        """处理 fast-track 单 run 结果：守卫 → 硬校验 → 状态推进。

        在 _run_agent_worker 的 fast-track 分支被同步调用（同线程，预算已递增）。
        完整路径：ensure_spec_committed → run_fast_track → guards → merge →
        hard-check → state advance；任一步骤失败按失败重派（与 implementer 同语义）。
        """
        wm = self._pm.agent_runner.worktree_manager
        try:
            wm.ensure_spec_committed(spec_name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track ensure_spec_committed 失败 '{spec_name}': {e}（非阻塞）",
            )

        try:
            result = self._pm.agent_runner.run_fast_track(spec_name)
        except Exception as e:
            self._pm._rollback_failed_dispatch(spec_name, "fast-track", e)
            return

        # verify-process-lifecycle（D3 dispatch 兜底）：runner success 返回后的
        # hand-off 边界内抛异常时，runner 的 finally 因 fast-track 属 handed_off
        # 而跳过收割——此处兜底收割 result.worktree_path 的 dev-server 注册条目，
        # 避免 keep/release 判定未执行而 dev-server 永久滞留。
        try:
            self._run_fast_track_flow(spec_name, result)
        except Exception:
            self._harvest_fast_track_worktree(spec_name, result)
            raise

    def _run_fast_track_flow(self, spec_name: str, result) -> None:
        """fast-track run 结果处理主体（守卫/校验/推进）。

        与 _run_fast_track_worker 分离，使 worker 可对其包 try/except 兜底收割
        （verify-process-lifecycle D3）。任一步骤失败按失败重派同语义返回。
        """
        # ── 人工取消 hold-state（add-run-cancel D4，fast-track 同语义）──
        # 被取消的 fast-track run 结果 cancelled=True：只写 error、不翻 status、
        # 不动 _retry_count/_merge_fp/_merge_streak、不入队重派；worktree
        # 保留语义不变（_keep_fast_track_worktree 幂等，runner 已在取消路径保留）。
        if getattr(result, "cancelled", False):
            ft_err = getattr(result, "error", None) or ""
            cancelled_err = (
                f"run 被人工取消：{ft_err}" if ft_err else "run 被人工取消"
            )
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track run 被人工取消 '{spec_name}' — hold-state，"
                f"不重试/不重派: {cancelled_err}",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "error": cancelled_err,
                # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                "_cancelled_hold": True,
            })
            return

        # ── 读取结果文件（fast-track 结果文件是强制的，缺文件 = 失败） ──
        ft_result = self._pm._read_implementer_result(spec_name)
        if ft_result is None:
            # ── 结果文件缺失分流（fix-fasttrack-resultfile-missing-redispatch D2）──
            # 两起事故：分支已提交的成果被当「run 死亡」discard 后从零重派
            # （add-turn-limit-anchor-c run1 / add-main-tree-deps-provision run1，
            # 均已全量提交仍判死亡）。结果文件缺失但实现分支相对 main 已有提交
            # → 不判死亡：不回退预算、不 reset ready，merge 分支 + 改写
            # .spec.yaml mode→full + enqueue 完整模式 verifier 补齐缺失的 verdict，
            # 随后走既有 verified→done 门。分支零提交/无 branch → 维持既有
            # 死亡豁免 + reset ready + 自动重派（原封不动）。
            # result.success 门：runner 仅在 success 时填 branch（runner.py:2644），
            # 失败/中断 run 的 branch 为空——显式保留该前置，对齐 spec WHEN 子句
            # 「正常收工（exit 0，result.success 为真、result.branch 非空）」。
            if (getattr(result, "success", False)
                    and self._pm._implementation_branch_has_commits(result)):
                self._handle_fast_track_missing_result_merge(spec_name, result)
                return
            self._keep_fast_track_worktree(spec_name, result)
            # 文案面向人：说明发生了什么 + 系统将自动重试（轮次由
            # _handle_fast_track_failure 按实际计数追加）。"fail-closed 不推进"
            # 类状态机术语曾让用户误读为 spec 被阻塞（2026-09-04 反馈）。
            self._handle_fast_track_failure(
                spec_name, result,
                "本轮实现中断：fast-track 结果文件未产出（run 异常结束），将自动重试",
            )
            return
        if not result.success or ft_result.get("status") != "success":
            self._keep_fast_track_worktree(spec_name, result)
            if result.success:
                # run 正常收工但结果文件顶层 status 非法：error 写明实际值与修法
                # 处方——不用无信息量兜底文案（add-agent-prompt-files 事故：
                # status 被写成 'verified'，兜底文案 'fast-track run failed' 让
                # 重派 run 不知错在哪，可能原样再犯）。
                status_val = ft_result.get("status")
                final_error = (
                    f"结果文件 status={status_val!r} 非法——顶层合同唯一合法值为 "
                    f"'success'（verified/bug-found 属于 verification.verdict）。"
                    f"修复：重写 .fenix-run-result.json 顶层 status 为 'success'"
                )
            else:
                final_error = (
                    ft_result.get("error") or result.error or "fast-track run failed"
                )
            self._handle_fast_track_failure(spec_name, result, final_error)
            return

        # ── 零变更成功哨 ──
        if self._pm._implementer_zero_change(spec_name, result):
            self._keep_fast_track_worktree(spec_name, result)
            self._handle_fast_track_zero_change(spec_name, result)
            return

        # ── 交付物守卫 ──
        missing = self._pm._deliverable_gate_missing(spec_name, result)
        if missing:
            self._keep_fast_track_worktree(spec_name, result)
            self._handle_fast_track_deliverable_gate(spec_name, result, missing)
            return

        # ── tasks.md 收口复检门禁（add-tasksmd-relint-gate）──────────────
        # 与 full 车道同语义的事后复检：fast-track 成功收口前以 worktree 内
        # tasks.md（最新版本，worktree 成功路径延迟清理仍在）为基准判定。
        # 违规 → 保留 worktree + 走失败重派（error 写违规明细与修正处方）。
        # 读取失败/无 path/异常 → fail-open 不拦（lint 既有 fail-open 语义）。
        try:
            relint = self._pm._tasks_md_relint_from_worktree(
                spec_name, getattr(result, "worktree_path", None))
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"tasks.md relint 执行异常（fail-open）'{spec_name}': {e}",
            )
            relint = []
        if relint:
            self._keep_fast_track_worktree(spec_name, result)
            self._redispatch_tasks_relint(
                spec_name, relint, agent_type="fast-track",
                run_id=getattr(result, "run_id", "") or "")
            return

        # ── 硬校验（merge 前执行，失败则不合并、按失败重派） ──
        verification = self._hard_check_fast_track(spec_name, ft_result)
        if verification is None:
            # worktree-reuse：打回保留 worktree，重派在同一目录继承上一轮成果
            self._keep_fast_track_worktree(spec_name, result)
            return  # _hard_check 已设 error + enqueue

        # ── 校验全通过：merge → 状态推进 ──
        # merge 失败时 _reconcile_and_merge 内部已处置（保留 worktree + 重派/熔断），
        # 必须早退——否则会继续走 advance_to_verified 把 error 踩成 None（伪 verified）。
        merged = self._reconcile_and_merge(spec_name, result)
        if not merged:
            return

        # ── impl-result per-spec 快照（fast-track 车道与 full 车道同语义）──
        # merge 成功即快照，供 verified→done 门禁 _task_completion_blocker 读取。
        # fast-track 的 verified→done 虽与本收口同周期同步执行，但 spec 可因门禁
        # 拦截（未勾任务）滞留 verified 跨周期——此窗口内共享文件
        # .fenix/.fenix-run-result.json 会被其它 spec 成功覆盖，无快照则门禁
        # fail-closed 误报「run 证据缺失」（2026-09-10 add-planready-artifact-gate
        # 实证）。快照写失败仅 WARNING 不阻塞（fail-open，门禁 fail-closed 兜底）；
        # 重派后新成功原子覆盖旧快照（幂等）。
        try:
            self._pm._write_impl_result_snapshot(spec_name, ft_result)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track impl-result 快照写入失败 '{spec_name}'（非阻塞）: {e}",
            )
        # ── 消费后清理共享结果文件（fix-fasttrack-resultfile-missing-redispatch D4）──
        # 本次采信消费 + 快照落盘之后删除主树共享 .fenix/.fenix-run-result.json
        # （仅当 stamp 严格匹配本 spec 即正是本文件被消费时删除），避免已消费
        # 残留跨 spec 存留对后续死亡判定/读侧的误拦与噪声。删除失败仅 WARNING
        # 不阻塞（fail-open，残留由 stamp 严格校验兜底拒绝）。
        self._pm._cleanup_shared_result_file(spec_name)

        if verification.get("verdict") == "bug-found":
            self._escalate_to_full_mode(spec_name, result, verification)
            return

        # ── verified → implemented → testing → verified → _on_spec_verified ──
        self._fast_track_advance_to_verified(spec_name, result)

    def _harvest_fast_track_worktree(self, spec_name: str, result) -> None:
        """fast-track 异常兜底（verify-process-lifecycle D3）：回收 dev-server。

        runner 的终态收割因 fast-track 属 handed_off（有意交接 dispatch 层）
        而跳过；本方法在 hand-off 边界内抛异常时兜底：停止
        result.worktree_path 的 dev-server 注册条目并扫杀游离进程。
        幂等：条目已不存在/进程已死时安全空转。
        """
        wt = getattr(result, "worktree_path", None)
        if not wt:
            return
        try:
            self._pm.agent_runner._v2_stop_for_worktree(Path(wt))
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"fast-track 兜底收割 V2 stop 失败 '{spec_name}': {e}")
        try:
            self._pm.agent_runner.worktree_manager._kill_worktree_strays(
                Path(wt).name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"fast-track 兜底收割 strays 失败 '{spec_name}': {e}")

    def _keep_fast_track_worktree(self, spec_name: str, result) -> None:
        """fast-track 打回/失败：保留 worktree 供重派继承（worktree-reuse）。

        runner 对 fast-track 成功路径延迟清理（worktree_kept=False 时由本层处置）；
        终态失败路径 runner 已保留（worktree_kept=True，此处幂等跳过）。
        """
        wt = getattr(result, "worktree_path", None)
        if wt is None or getattr(result, "worktree_kept", False):
            return
        try:
            self._pm.agent_runner._v2_stop_for_worktree(wt)
            self._pm.agent_runner.worktree_manager.keep_for_reuse(spec_name, wt)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track worktree 保留失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _release_fast_track_worktree(self, spec_name: str, result) -> None:
        """fast-track 校验通过且 merge 完成：回收 runner 延迟保留的 worktree。"""
        wt = getattr(result, "worktree_path", None)
        if wt is None:
            return
        try:
            self._pm.agent_runner._v2_stop_for_worktree(wt)
            self._pm.agent_runner.worktree_manager.cleanup(wt, success=True)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track worktree 延迟清理失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _reconcile_and_merge(self, spec_name: str, result) -> bool:
        """预算对账 + merge（fast-track 与 implementer 成功路径同语义）。

        Returns: merge 是否成功（失败时调用方必须早退，不得继续状态推进）。"""
        self._pm._reconcile_impl_budget(spec_name)
        wm = self._pm.agent_runner.worktree_manager
        branch = result.branch
        if branch:
            merge_info = wm.merge_back_from_branch(branch)
            merge_ok, merge_error = merge_info
            if not merge_ok:
                # worktree-reuse：merge 失败同样保留 worktree，重派继承后重试 merge
                self._keep_fast_track_worktree(spec_name, result)
                # ── 预演语义冲突直通 repair（add-merge-tree-rehearsal D2）──
                # 与 implementer 路径同语义：主树零污染检出语义冲突 → 不经 fp
                # 记账与 ready 降级，spec 保持 in-flight 直通 repair（轮次兜底在
                # _direct_rehearsed_to_repair 内）。
                if getattr(merge_info, "rehearsed", False):
                    self._direct_rehearsed_to_repair(
                        spec_name, merge_info, branch, merge_error)
                    return False
                spec_entry = self._pm.state_machine.read_one(spec_name) or {}
                max_r = self._pm._get_config("agents.max_retries", 3)
                fp = self._pm._merge_fingerprint(merge_error)
                prev_fp = spec_entry.get("_merge_fp")
                try:
                    prev_streak = int(spec_entry.get("_merge_streak", 0) or 0)
                except (TypeError, ValueError):
                    prev_streak = 0
                streak = prev_streak + 1 if prev_fp == fp else 1
                breaker_threshold = self._pm._get_config(
                    "agents.merge_breaker_threshold", 2)
                final_error = f"Merge-back failed (fp={fp}): {merge_error}"
                if streak >= breaker_threshold:
                    self._pm.state_machine.transition(spec_name, "blocked")
                    self._pm.state_machine.update_spec(spec_name, {
                        "error": final_error,
                        "_merge_fp": fp, "_merge_streak": streak, "_retry_count": 0,
                    })
                elif self._pm._should_enter_repair(
                        spec_name, merge_info, streak, breaker_threshold):
                    # ── repair 通道（add-merge-back-repair-lane；fast-track 接入）──
                    # 语义冲突失败且熔断未触发：派 repair agent 在实现分支上把
                    # main 合入原地修复，而非 ready+重派废弃整轮成果
                    #（2026-09-04 task-track 事故：112 turns 因混合冲突整单废弃）。
                    # 与 implementer 路径同序：熔断优先，repair 次之，普通重试兜底。
                    self._pm._dispatch_repair_lane(
                        spec_name, merge_info, branch,
                        fp=fp, streak=streak,
                    )
                else:
                    try:
                        retries = int(spec_entry.get("_retry_count", 0) or 0) + 1
                    except (TypeError, ValueError):
                        retries = 1
                    self._pm.state_machine.update_spec(spec_name, {
                        "status": "ready", "error": final_error,
                        "_merge_fp": fp, "_merge_streak": streak,
                        "_retry_count": retries,
                    })
                    self._pm._enqueue_front(spec_name, "fast-track")
                self._pm.logger.error(
                    "pm_engine",
                    f"fast-track merge-back failed '{spec_name}': {final_error}",
                )
                return False
        # merge 成功：回收 runner 延迟保留的 fast-track worktree（worktree-reuse）
        self._release_fast_track_worktree(spec_name, result)
        self._pm.state_machine.transition(spec_name, "implemented")
        self._pm.state_machine.update_spec(spec_name, {
            "implementer_run": result.run_id,
            "branch": result.branch, "error": None,
            "_retry_count": 0, "_merge_fp": None, "_merge_streak": 0,
            **self._pm._clear_dispatch_conflict(spec_name),
        })
        # 任务进度回写（与 implementer 成功路径一致，非阻塞）
        try:
            self._pm._sync_task_progress(spec_name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track 任务进度回写失败 '{spec_name}'（非阻塞）: {e}",
            )
        try:
            wm.consume_legacy(spec_name)
        except Exception:
            pass
        return True

    # ── repair 通道（add-merge-back-repair-lane D1/D2/D4/D5/D6）──────────────
    # merge-back 语义冲突失败后的原地修复通道。分层边界（design D1）：git 层
    # （worktree_manager）只做冲突分类与载体解析，**是否进入 repair、派发与轮次
    # 计数**在本层决策。修复方向反转（D2）：repair agent 在实现分支一侧把 main
    # 合入分支并解决冲突，主树在派发前已 abort 保持干净。

    def _direct_rehearsed_to_repair(self, spec_name: str, merge_info, branch: str,
                                    merge_error: str) -> None:
        """预演语义冲突直通 repair（add-merge-tree-rehearsal D2/D5）。

        implementer 与 fast-track 失败分支共用：merge-tree 预演已在主树零污染点
        检出语义冲突（``rehearsed=True``）——真合并从未发生，``_merge_fp``/
        ``_merge_streak`` 记账与 ready 降级在此路径均无意义（fp 熔断的职责——
        阻断「根因不消除→整轮重跑→再败」循环——由 repair 轮次上限承接）。
        spec 保持 in-flight，repair agent 在实现分支内把 main 合入解决冲突。

        轮次兜底（D5）：``_should_enter_repair`` 拒绝（已 blocked / ``_repair_round``
        超限）时回退现行 fallback 重派路径（prompt 注入冲突上下文），不产生无限
        repair 循环；repair 后 re-merge 失败链仍走既有 fp 熔断（本方法不动熔断语义）。
        """
        breaker_threshold = self._pm._get_config("agents.merge_breaker_threshold", 2)
        if self._pm._should_enter_repair(spec_name, merge_info, 0, breaker_threshold):
            self._pm.logger.info(
                "pm_engine",
                f"预演检出语义冲突直通 repair '{spec_name}'："
                f"{len(merge_info.conflict_paths)} path(s) "
                f"{getattr(merge_info, 'conflict_paths', [])} — 主树零污染，"
                f"不经 fp 记账（rehearsed）",
            )
            self._pm._dispatch_repair_lane(spec_name, merge_info, branch)
        else:
            self._pm.logger.info(
                "pm_engine",
                f"预演检出语义冲突但 repair 不可用 '{spec_name}'"
                f"（轮次超限/已 blocked）— 回退 fallback 重派（rehearsed，"
                f"prompt 注入冲突上下文）",
            )
            self._pm._fallback_after_repair(spec_name, branch, merge_error)

    def _should_enter_repair(self, spec_name: str, merge_info, streak: int,
                             breaker_threshold: int) -> bool:
        """merge-back 失败后是否进入 repair 通道（语义冲突 + 熔断未触发 + 未超轮次）。

        判定依据（spec-mergeback-inplace-repair）：
        - merge_info 携带结构化冲突分类（D1）；
        - 全部冲突路径均为构建产物且自愈成功时（success=True）不会走到这里——
          调用方仅在 ``not merge_ok`` 分支内调用；
        - 冲突含语义文件（has_semantic_conflict）→ 产物/ignored-DU 自愈均不适用；
        - 熔断未触发（streak < threshold）：blocked spec 不再派发 repair；
        - 同一失败链内 repair 未超轮次（_repair_round < MAX_REPAIR_ROUNDS_PER_FAILURE）。
        """
        # 兼容 (bool, str) 元组调用（merge_info 可能非 MergeConflictInfo）
        info_has_semantic = bool(getattr(merge_info, "has_semantic_conflict", False))
        if not info_has_semantic:
            return False
        try:
            spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        except Exception:
            spec_entry = {}
        if spec_entry.get("status") == "blocked":
            return False
        if streak >= breaker_threshold:
            return False
        try:
            repair_round = int(spec_entry.get("_repair_round", 0) or 0)
        except (TypeError, ValueError):
            repair_round = 0
        return repair_round < MAX_REPAIR_ROUNDS_PER_FAILURE

    def _dispatch_repair_lane(self, spec_name: str, merge_info, branch: str,
                              fp: str | None = None, streak: int = 0) -> None:
        """进入 repair 通道：三态解析载体 → 认领现场 → 派发 repair worker。

        载体三态（design D3，以 git 事实为判定基准）：
        (a) 原 worktree 存在 → 原地进入（保留 node_modules/构建缓存）；
        (b) worktree 已清但分支存在 → 换壳：在分支上新建 worktree；
        (c) 分支不存在 → 回退 fallback 全新重派（prompt 注入 merge 失败上下文）。

        轮次控制（D5/D6）：``_repair_round`` 在派发前递增并持久化，
        超限不派发（_should_enter_repair 已拦截，此处兜底回退）。
        """
        wm = self._pm.agent_runner.worktree_manager
        # cli-retry-backoff 2.2：秒挂冷却期内不派发 repair（repair agent 同样会秒挂）。
        # spec 保持原状，冷却到期由恢复定时器 / full_scan 重新唤起实现派发。
        if self._pm._instant_fail_cooled(spec_name):
            self._pm.logger.debug(
                "pm_engine",
                f"秒挂冷却中，跳过 repair 派发 '{spec_name}'（冷却期后恢复调度）",
            )
            self._schedule_instant_fail_recovery(spec_name)
            return
        try:
            repair_round = int(
                (self._pm.state_machine.read_one(spec_name) or {}).get("_repair_round", 0) or 0
            )
        except (TypeError, ValueError):
            repair_round = 0
        # 分支消亡 → fallback（三态 (c)）
        if not branch or not wm.branch_exists(branch):
            self._pm.logger.warning(
                "pm_engine",
                f"repair 载体分支 '{branch}' 不存在 — 回退 fallback 全新重派",
            )
            self._pm._fallback_after_repair(
                spec_name, None, getattr(merge_info, "error", "") or "",
            )
            return
        # 三态解析：原地 / 换壳
        wt_path, resolved_branch = wm.resolve_repair_site(spec_name, branch)
        if wt_path is None:
            self._pm.logger.warning(
                "pm_engine",
                f"repair 载体解析失败（分支 '{branch}' 不可用）— 回退 fallback",
            )
            self._pm._fallback_after_repair(
                spec_name, branch, getattr(merge_info, "error", "") or "",
            )
            return
        # 认领现场（D4）：_legacy take 摘出 + _spec_locks 注册，防 sweeper 宽限期回收
        self._pm._claim_repair_site(spec_name, wt_path, resolved_branch)
        # 轮次递增（D5/D6）：repair 轮计入该 spec 的实现预算（token 记名下）；
        # 连续计数 _merge_fp/_merge_streak 不被 repair 轮清零（熔断协同）。
        round_no = repair_round + 1
        try:
            self._pm.state_machine.update_spec(spec_name, {
                "_repair_round": round_no,
                "_repair_merge_error": getattr(merge_info, "error", "") or "",
                "_repair_merge_fp": fp,
            })
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"repair 轮次计数回写失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.warning(
            "pm_engine",
            f"进入 repair 通道 '{spec_name}'（第 {round_no}/{MAX_REPAIR_ROUNDS_PER_FAILURE} 轮）"
            f"worktree={wt_path} branch={resolved_branch}",
        )
        t = threading.Thread(
            target=self._pm._run_repair_worker,
            args=(spec_name, wt_path, resolved_branch, merge_info),
            daemon=True,
            name=f"fenix-repair-{spec_name}",
        )
        t.start()

    def _claim_repair_site(self, spec_name: str, wt_path, branch: str) -> None:
        """认领 repair 现场（add-merge-back-repair-lane D4）。

        与 fast-track 复用同款 take 动作：认领时从 ``_legacy`` 摘出（防 sweeper
        宽限期按孤儿回收正在使用的现场）；在 ``_spec_locks`` 注册 repair 锁
        （防 repair 进行中重复派发）。worktree 已在三态解析时登记进活动集
        （``_active_worktrees``/``_wt_branches``），sweeper 不再豁免该目录。
        """
        wm = self._pm.agent_runner.worktree_manager
        # 认领即摘出登记表（与 fast-track `_take_reusable_worktree` 同款 take）
        if hasattr(wm, "claim_legacy_for_repair"):
            wm.claim_legacy_for_repair(spec_name)
        elif spec_name in getattr(wm, "_legacy", {}):  # 兜底：直接摘出
            wm._legacy.pop(spec_name, None)
        if hasattr(wm, "_spec_locks"):
            wm._spec_locks.add(f"{spec_name}:repair")
        if branch:
            wm._wt_branches[str(wt_path)] = branch

    def _run_repair_worker(self, spec_name: str, wt_path, branch: str,
                           merge_info) -> None:
        """repair worker：派发 repair agent → re-merge-back → 状态推进。

        在守护线程内同步执行（与 implementer worker 同线程语义）。repair agent
        在实现分支一侧把 main 合入分支并解决冲突、commit；成功后框架对该分支
        重新执行 merge-back（分支已含 main 历史应快速前进）。

        熔断协同（D6）：re-merge-back 再失败时 ``_merge_fp``/``_merge_streak``
        连续累计（repair 轮不清零）；blocked 后不再派发 repair。
        """
        wm = self._pm.agent_runner.worktree_manager
        try:
            repair_ok = False
            repair_error = ""
            r = None
            try:
                r = self._pm.agent_runner.run_repair(
                    spec_name, wt_path,
                    conflict_summary=self._repair_conflict_summary(spec_name, merge_info),
                )
                # 读取 repair 结果文件（repair agent 在 worktree 写 .fenix-run-result.json）
                wt_result = Path(wt_path) / ".fenix-run-result.json"
                repair_ok = bool(r.success)
                if wt_result.exists():
                    try:
                        data = json.loads(wt_result.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            stamped = data.get("spec")
                            if stamped and stamped != spec_name:
                                repair_ok = False
                                repair_error = f"结果文件 spec 戳 '{stamped}' 与 '{spec_name}' 不符"
                            elif data.get("status") == "error":
                                repair_ok = False
                                repair_error = data.get("error") or "repair agent 显式报告失败"
                    except (json.JSONDecodeError, OSError) as e:
                        repair_ok = False
                        repair_error = f"repair 结果文件解析失败: {e}"
            except Exception as e:
                repair_ok = False
                repair_error = str(e)
                self._pm.logger.error(
                    "pm_engine",
                    f"repair agent 派发异常 '{spec_name}': {e}",
                )

            # ── 人工取消 hold-state（add-run-cancel D4，repair worker）──
            # repair run 被取消：spec 保持原状（implementing），只写 error，
            # 不动 _retry_count/_merge_fp/_merge_streak、不入队重派。
            if getattr(r, "cancelled", False):
                r_err = getattr(r, "error", None) or repair_error or ""
                cancelled_err = (
                    f"run 被人工取消：{r_err}" if r_err else "run 被人工取消"
                )
                self._pm.logger.warning(
                    "pm_engine",
                    f"repair run 被人工取消 — hold-state '{spec_name}'"
                    f"（保持原状）: {cancelled_err}",
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "error": cancelled_err,
                    # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                    "_cancelled_hold": True,
                })
                return

            if not repair_ok:
                # repair 失败/超时/显式失败 → 回退 fallback 全新重派（原分支按既有
                # 清扫策略处理：登记遗产供后继 run 参考）
                self._pm._fallback_after_repair(
                    spec_name, branch, repair_error,
                    merge_error=getattr(merge_info, "error", "") or "",
                )
                return

            # repair 成功：对分支重新执行 merge-back（分支已含 main 历史）
            self._pm._reconcile_impl_budget(spec_name)
            remerge_info = wm.merge_back_from_branch(branch)
            remerge_ok, remerge_error = remerge_info

            if remerge_ok:
                # 链成功：回收 repair worktree，推进 implemented
                try:
                    self._pm.agent_runner._v2_stop_for_worktree(wt_path)
                except Exception:
                    pass
                try:
                    wm.cleanup(wt_path, success=True)
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"repair worktree 清理失败 '{spec_name}'（非阻塞）: {e}",
                    )
                self._pm.state_machine.transition(spec_name, "implemented")
                self._pm.state_machine.update_spec(spec_name, {
                    "implementer_run": getattr(r, "run_id", None) or None,
                    "branch": branch,
                    "error": None,
                    "_retry_count": 0,
                    "_merge_fp": None,
                    "_merge_streak": 0,
                    "_repair_round": 0,
                    "_repair_merge_error": None,
                    **self._pm._clear_dispatch_conflict(spec_name),
                })
                try:
                    self._pm._sync_task_progress(spec_name)
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"repair 任务进度回写失败 '{spec_name}'（非阻塞）: {e}",
                    )
                try:
                    wm.consume_legacy(spec_name)
                except Exception:
                    pass
                self._pm._enqueue_front(spec_name, "verifier")
                self._pm.logger.info(
                    "pm_engine",
                    f"repair 链成功：'{spec_name}' re-merge-back 完成 → implemented",
                )
                return

            # re-merge-back 再失败：与首次 merge 失败同路径处理（熔断计数连续累计），
            # repair 轮不清零 _merge_fp/_merge_streak（spec-merge-circuit-breaker）。
            self._pm._handle_remerge_failure(spec_name, remerge_info, branch)

        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"repair worker 异常 '{spec_name}': {e}",
            )
            # verify-process-lifecycle（D3 dispatch 兜底）：hand-off 边界内异常
            # 时收割 repair 载体 worktree 的 dev-server 注册条目（run_repair 的
            # runner 收割因 repair 属 handed_off 而跳过）。幂等，双调无害。
            try:
                self._pm.agent_runner._v2_stop_for_worktree(Path(wt_path))
            except Exception:
                pass
            self._pm._fallback_after_repair(
                spec_name, branch, str(e),
                merge_error=getattr(merge_info, "error", "") or "",
            )
        finally:
            # 释放 repair 锁（_spec_locks 中 {spec}:repair 条目）
            try:
                wm._spec_locks.discard(f"{spec_name}:repair")
            except Exception:
                pass
            self._pm._process_queue()

    def _handle_remerge_failure(self, spec_name: str, remerge_info, branch: str) -> None:
        """repair 后的 re-merge-back 失败：熔断 → repair 下一轮 → fallback。

        与首次 merge-back 失败同判定基准（fp/streak 连续累计，repair 不重置），
        轮次超过上限回退 fallback。不重复 testing/implemented 保护检查——
        repair 链内 spec 保持 implementing，无在飞 tester。
        """
        merge_error = getattr(remerge_info, "error", "") or str(remerge_info)
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        fp = self._pm._merge_fingerprint(merge_error)
        prev_fp = spec_entry.get("_merge_fp")
        try:
            prev_streak = int(spec_entry.get("_merge_streak", 0) or 0)
        except (TypeError, ValueError):
            prev_streak = 0
        streak = prev_streak + 1 if prev_fp == fp else 1
        final_error = f"Merge-back failed (fp={fp}): {merge_error}"
        breaker_threshold = self._pm._get_config("agents.merge_breaker_threshold", 2)
        if streak >= breaker_threshold:
            self._pm.state_machine.transition(spec_name, "blocked")
            self._pm.state_machine.update_spec(spec_name, {
                "error": final_error,
                "_merge_fp": fp, "_merge_streak": streak, "_retry_count": 0,
            })
            self._pm.logger.error(
                "pm_engine",
                f"Circuit breaker tripped after repair for '{spec_name}' (fp={fp}) "
                f"— spec blocked (repair 不绕过熔断)",
            )
            return
        if self._pm._should_enter_repair(spec_name, remerge_info, streak, breaker_threshold):
            self._pm._dispatch_repair_lane(
                spec_name, remerge_info, branch, fp=fp, streak=streak,
            )
            return
        # 未触发熔断且不可 repair → fallback 全新重派
        self._pm._fallback_after_repair(spec_name, branch, merge_error)

    def _fallback_after_repair(self, spec_name: str, branch: str | None,
                               repair_error: str, merge_error: str = "") -> None:
        """repair 链失败回退：全新重派 implementer，prompt 注入 merge 失败上下文。

        - 清理 repair worktree（保留分支：按既有清扫策略登记遗产，供后继 run 参考）；
        - ``_repair_round`` 归零：fallback 后新 implementer 的 merge 失败开启新链
          （design D6）；
        - 状态置 ready + error（既有 _prev_error_section 会把它注入新 implementer
          prompt，即「prompt 注入当次 merge 失败上下文」）；
        - ``_merge_fp``/``_merge_streak`` **不清零**：repair 失败后 fallback 重派
          引发的 merge-back 失败与前序失败连续累计（熔断协同）。
        """
        wm = self._pm.agent_runner.worktree_manager
        # 清理 repair worktree（若有现场）：分支按既有清扫策略登记遗产
        try:
            if branch and wm.branch_exists(branch):
                wt_path = wm.find_worktree_path(branch)
                if wt_path is not None and wt_path.exists():
                    try:
                        self._pm.agent_runner._v2_stop_for_worktree(wt_path)
                    except Exception:
                        pass
                    wm.cleanup(wt_path, success=True)
                # 成功收工清理后仅分支留存（已解决的冲突成果随分支保留），
                # 登记为仅分支遗产供后继 run 参考收编（不丢失修复工作）
                wm.register_legacy(spec_name, None, branch)
            elif branch:
                wm.register_legacy(spec_name, None, branch)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fallback 清理 repair worktree 失败 '{spec_name}'（非阻塞）: {e}",
            )
        # 失败链收尾：归零轮次，回退 fallback
        try:
            prev_retries = int(
                (self._pm.state_machine.read_one(spec_name) or {}).get("_retry_count", 0) or 0
            )
        except (TypeError, ValueError):
            prev_retries = 0
        retries = prev_retries + 1
        base_error = merge_error or "merge-back failed"
        if repair_error:
            full_error = (
                f"repair 失败（{repair_error[:300]}）→ 回退全新重派。"
                f"原 merge 失败上下文：{base_error[:600]}"
            )
        else:
            full_error = base_error
        max_r = self._pm._get_config("agents.max_retries", 3)
        updates: dict = {
            "status": "ready",
            "error": full_error,
            "_repair_round": 0,
            "_repair_merge_error": None,
            "_retry_count": retries,
        }
        if retries >= max_r:
            updates["status"] = "blocked"
            updates["error"] = (
                f"实现尝试连续 {max_r} 次失败（含 repair 通道）— 已 blocked，"
                f"需人工检查。最近失败：{full_error[:400]}"
            )
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.error(
            "pm_engine",
            f"repair 链回退 fallback '{spec_name}'：{full_error[:200]}",
        )
        if updates["status"] == "ready":
            # 回退通道按 spec 实现模式选择（fast-track 接入 repair lane 配套）：
            # fast-track spec 的 repair 失败回 fast-track 重派，不硬派 implementer
            try:
                from core.spec_mode import read_spec_mode
                channel = (
                    "fast-track"
                    if read_spec_mode(self._pm.project_root, spec_name) == "fast-track"
                    else "implementer"
                )
            except Exception:
                channel = "implementer"
            self._pm._enqueue_front(spec_name, channel)

    def _repair_conflict_summary(self, spec_name: str, merge_info) -> dict:
        """构造 repair prompt 的冲突摘要（D5：spec 身份 + 冲突清单 + 方向说明）。

        不含原 worktree 地址类间接情报（agent 即在现场，冲突状态自查）。
        """
        try:
            repair_round = int(
                (self._pm.state_machine.read_one(spec_name) or {}).get("_repair_round", 0) or 0
            )
        except (TypeError, ValueError):
            repair_round = 0
        return {
            "spec": spec_name,
            "merge_error": getattr(merge_info, "error", "") or "",
            "conflict_paths": list(getattr(merge_info, "conflict_paths", []) or []),
            "has_semantic_conflict": bool(
                getattr(merge_info, "has_semantic_conflict", False)),
            "repair_round": repair_round,
        }

    def _hard_check_fast_track(self, spec_name: str, ft_result: dict):
        """对 fast-track 结果做框架侧硬校验；失败记原因并按失败重派。

        Returns:
            规整后的验证段 dict（含 verdict/bugs/scenarios），校验失败返回 None。
        """
        from core.fast_track_result import parse_fast_track_verification
        from core.verdict_check import validate_fast_track_result

        verification = parse_fast_track_verification(ft_result or {})
        if verification is None:
            err = "fast-track 结果文件非法（verification 段缺失或结构不完整）"
            self._pm.state_machine.update_spec(spec_name, {"error": err})
            self._pm._enqueue_front(spec_name, "fast-track")
            self._pm.logger.error(
                "pm_engine", f"fast-track 硬校验失败 '{spec_name}': {err}",
            )
            return None

        # 加载设计场景 ID（Phase 2 写入的 test_scenarios.json）
        scenarios_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "test_scenarios.json"
        )
        designed_ids: list = []
        if scenarios_path.exists():
            try:
                sc_data = json.loads(scenarios_path.read_text(encoding="utf-8"))
                if isinstance(sc_data, list):
                    designed_ids = [
                        s.get("id")
                        for s in sc_data
                        if isinstance(s, dict) and s.get("id")
                    ]
            except (OSError, json.JSONDecodeError):
                pass

        check = validate_fast_track_result(ft_result, designed_ids or None)
        if not check["ok"]:
            violations_str = "；".join(check["violations"])
            err = f"fast-track 硬校验失败（fail-closed）：{violations_str}"
            self._pm.state_machine.update_spec(spec_name, {"error": err})
            self._pm._enqueue_front(spec_name, "fast-track")
            self._pm.logger.error(
                "pm_engine",
                f"fast-track 硬校验不通过 '{spec_name}': {violations_str}",
            )
            return None

        return verification

    def _fast_track_advance_to_verified(self, spec_name: str, result) -> None:
        """fast-track 硬校验通过 + verdict=verified：implemented → testing → verified。"""
        # verified 洗白门禁（help-center 0/15 verified 事故防线）：fast-track
        # 结果文件 0 通过或 env 失败不得放行，升级 admin 处置
        if not self._pm._env_whitewash_gate(spec_name):
            return
        self._pm.state_machine.transition(spec_name, "testing")
        self._pm.state_machine.transition(spec_name, "verified")
        self._pm.state_machine.update_spec(spec_name, {
            "tester_run": result.run_id,
            "error": None,
            "_inconclusive_attempts": 0,
            # add-verify-parallel-backoff / design D2：fast-track verified 是
            # 既有清零点，降档并行度同轮复位（与 _inconclusive_attempts 同生命周期）。
            "_verify_parallel_override": None,
            "_verify_fail_rounds": 0,
            # fix-daemon-lifecycle-races D3：验证自然通过清零点（fast-track 同语义）。
            "_verify_redo_count": 0,
            # add-blocked-reverify-lane D3：env 阻塞轮次清零点（fast-track verified
            # 属「验证通过」唯一自动清零点语义，与全模式 verified 落定同款）。
            ENV_BLOCK_ROUNDS_FIELD: 0,
        })
        self._pm.logger.info(
            "pm_engine",
            f"fast-track verified: '{spec_name}' → 推进 verified",
        )
        self._pm._on_spec_verified(spec_name)

    def _rewrite_fast_track_to_full(self, spec_name: str) -> None:
        """把 .spec.yaml 的 mode 从 fast-track 改写为 full（升级路径复用）。

        供 ``_escalate_to_full_mode``（verdict=bug-found 升级）与
        ``_handle_fast_track_missing_result_merge``（结果文件缺失、分支已提交
        升级补验证）共用。写失败仅记 WARNING（非阻塞，mode 未改写时由 verifier
        车道语义处置）。
        """
        import yaml as _yaml
        # 1. .spec.yaml 写 mode: full
        yaml_path = (
            self._pm.project_root / "spec" / "changes"
            / spec_name / ".spec.yaml"
        )
        try:
            if yaml_path.is_file():
                data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("mode") == "fast-track":
                    data["mode"] = "full"
                    yaml_path.write_text(
                        _yaml.safe_dump(data, default_flow_style=False,
                                        sort_keys=False),
                        encoding="utf-8",
                    )
                    self._pm.logger.info(
                        "pm_engine",
                        f"fast-track 升级: .spec.yaml mode → full "
                        f"for '{spec_name}'",
                    )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track 升级 .spec.yaml 失败（非阻塞） '{spec_name}': {e}",
            )

    def _escalate_to_full_mode(
        self, spec_name: str, result, verification: dict,
    ) -> None:
        """fast-track verdict=bug-found 时升级为完整模式（add-fast-track-mode D5）。

        - mode 改写为 full（同步 .spec.yaml）
        - spec 保持 implemented，派发完整模式 verifier 流水线
        - 升级原因写入 spec entry error 字段
        - 保留已有实现成果，不丢回 ready 重跑 implementer
        """
        # 1. .spec.yaml 写 mode: full
        self._rewrite_fast_track_to_full(spec_name)
        # 2. 记录升级原因
        bugs_summary = "; ".join(
            b.get("description", "")[:80]
            for b in (verification.get("bugs") or [])
            if isinstance(b, dict)
        ) or "fast-track 判定 bug-found"
        self._pm.state_machine.update_spec(spec_name, {
            "error": f"fast-track 升级完整模式：{bugs_summary[:200]}",
        })
        # 3. 派发完整模式 verifier 流水线
        self._pm._enqueue(spec_name, "verifier")
        self._pm.logger.warning(
            "pm_engine",
            f"fast-track 升级完整模式 '{spec_name}'：verdict=bug-found，"
            f"实现保留，完整模式 verifier 流水线接管",
        )

    def _handle_fast_track_missing_result_merge(
        self, spec_name: str, result,
    ) -> None:
        """结果文件缺失但实现分支已有提交：merge + 升级完整模式补验证（D2）。

        触发因「结果文件缺失、分支已提交」而非 bug-found：不判 run 死亡——
        不回退预算、不 reset ready。merge 复用 ``_reconcile_and_merge``（失败时
        其内部已处置：保留 worktree + 重派/熔断，此处必须早退）；合并成功后改写
        .spec.yaml mode→full 并 enqueue 完整模式 verifier 补齐缺失的 verdict
        （复用 ``_escalate_to_full_mode`` 的 mode-改写 + enqueue 语义），后续走
        既有 verified→done 门。缺失的逐场景 fail-closed 校验整体移交完整模式
        verifier 的既有门（verify.yaml 契约 + verdict evidence），不损失校验强度。
        """
        # 预算对账 + merge（merge 失败内部已处置，必须早退）
        merged = self._reconcile_and_merge(spec_name, result)
        if not merged:
            return
        # 改写 mode=full + enqueue 完整模式 verifier（复用升级语义，触发因不同）
        self._rewrite_fast_track_to_full(spec_name)
        # 原因写入 spec entry（供人工审计：为何从 fast-track 转完整模式）
        self._pm.state_machine.update_spec(spec_name, {
            "error": "结果文件缺失，分支已提交，升级补验证",
        })
        self._pm._enqueue(spec_name, "verifier")
        self._pm.logger.warning(
            "pm_engine",
            f"fast-track 结果文件缺失、分支已提交 '{spec_name}'：merge 完成，"
            f"升级完整模式 verifier 补验证（不豁免预算、不 reset ready），"
            f"后续走既有 verified→done 门",
        )

    def _handle_fast_track_failure(
        self, spec_name: str, result, final_error: str,
    ) -> None:
        """fast-track run 失败处理：与 implementer 同语义（重派/重试计数/blocked）。"""
        # 死亡 run 豁免（无收工结果 = run 异常死亡）
        impl_status = None
        try:
            ft_result = self._pm._read_implementer_result(spec_name)
            impl_status = ft_result.get("status") if ft_result else None
        except Exception:
            pass
        if impl_status is None:
            self._pm._exempt_dead_run_budget(
                spec_name,
                f"fast-track no run-result (error={str(final_error)[:80]})",
            )
        # provider 熔断拦截
        if final_error and "provider circuit open" in final_error:
            self._pm.state_machine.update_spec(spec_name, {"error": final_error})
            return
        # 重试
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
        except (TypeError, ValueError):
            prev_retries = 0
        retries = prev_retries + 1
        max_r = self._pm._get_config("agents.max_retries", 3)
        if retries >= max_r:
            self._pm.state_machine.update_spec(spec_name, {
                "status": "ready", "error": f"{final_error}｜重试 {max_r}/{max_r} 已耗尽，重新排队",
                "_retry_count": 0,
            })
            self._pm.logger.error(
                "pm_engine", f"fast-track all retries exhausted '{spec_name}'",
            )
            self._pm._enqueue(spec_name, "fast-track")
        else:
            self._pm.state_machine.update_spec(spec_name, {
                "status": "ready",
                "error": f"{final_error}｜自动重试 {retries}/{max_r}",
                "_retry_count": retries,
            })
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track retry {retries}/{max_r} '{spec_name}'",
            )

    def _handle_fast_track_zero_change(self, spec_name: str, result) -> None:
        """fast-track 零变更哨处理：与 implementer 同逻辑。"""
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        attempts = 0
        try:
            attempts = int(spec_entry.get("_zero_change_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        dirty = list(getattr(result, "worktree_dirty", None) or [])
        if dirty:
            err_note = (f"fast-track 宣称成功但零提交，worktree 有 "
                        f"{len(dirty)} 个未提交修改——重派时务必 commit 后再报完成")
        else:
            err_note = ("fast-track 零变更报成功（疑似空转）— "
                        "不合并不推进，重派")
        updates: dict = {
            "status": "ready", "error": err_note + f"（第 {attempts} 次）",
            "_zero_change_attempts": attempts,
        }
        if attempts >= 3:
            updates["status"] = "blocked"
            updates["error"] = ("fast-track 连续 3 次零变更报成功 — blocked，需人工检查")
        self._pm.state_machine.update_spec(spec_name, updates)
        if attempts < 3:
            self._pm._enqueue_front(spec_name, "fast-track")

    def _handle_fast_track_deliverable_gate(
        self, spec_name: str, result, missing: list,
    ) -> None:
        """fast-track 交付物守卫触发：缺件重派，3 次封顶。"""
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            retries = int(spec_entry.get("_retry_count", 0) or 0) + 1
        except (TypeError, ValueError):
            retries = 1
        max_r = self._pm._get_config("agents.max_retries", 3)
        missing_q = "、".join(missing)
        err_note = f"fast-track 交付物守卫：缺件 [{missing_q}] — 重派补齐（第 {retries} 次）"
        updates: dict = {
            "status": "ready", "error": err_note, "_retry_count": retries,
        }
        if retries >= max_r:
            updates["status"] = "blocked"
            updates["error"] = (
                f"fast-track 交付物守卫连续 {max_r} 次缺件 [{missing_q}] — blocked"
            )
        self._pm.state_machine.update_spec(spec_name, updates)
        if updates["status"] != "blocked":
            self._pm._enqueue_front(spec_name, "fast-track")
