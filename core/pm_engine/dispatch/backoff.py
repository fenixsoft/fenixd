"""backoff.py — B 退避/瞬时恢复排程（refactor-giant-classes D1/D3/D5）。

原为 Dispatcher 的 9 个方法（`core/pm_engine/dispatch/_legacy.py`），
原样搬移为 mixin（方法体零改动）。跨组协作仍经宿主实例 `self.<method>`。

D3 patch 缝隙：
- 本组使用 `time` 模块，经模块顶部导入即可——测试
  ``patch.object(_dispatch_mod.time, "time", _tick)`` 修改的是 time 模块对象
  的 ``time`` 属性，全进程共享，patch 依旧生效；
- `DEFAULT_DISPATCH_BACKOFF_SCHEDULE` 常量自 `_legacy` 命名空间导入
  （常量定义先于 mixin 绑定，无环）。
"""

from __future__ import annotations

import threading
import time

from core.pm_engine.dispatch import (  # noqa: E402
    DEFAULT_DISPATCH_BACKOFF_SCHEDULE,
)


class BBackoffMixin:
    """B 退避/瞬时恢复排程（design D1 表 B B 组）。"""

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
        spec = self._pm.state_machine.read_one(spec_name)
        if not spec:
            # 条目缺失/读取为空（并发删除场景，code-review item 978b9c796502）：
            # 仿 _rollback_failed_dispatch 的同款守卫——仅 INFO 留痕后直接返回，
            # 不再写退避元数据，也不对不存在的 spec 排程重试定时器。
            self._pm.logger.info(
                "pm_engine",
                f"Dispatch lock conflict for '{spec_name}' — spec entry missing/"
                f"empty, skipping backoff write and retry scheduling",
            )
            return
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

        from core.timelib import from_epoch

        until_iso = from_epoch(until).isoformat()

        # 不翻转状态：spec 保持 ready，仅记录退避元数据
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "error": f"worktree already active (lock conflict); backoff until {until_iso}",
                "_lock_conflict_count": count + 1,
                "_dispatch_backoff_until": until,
                "_last_lock_conflict_at": _dt.now(_tz.utc).isoformat(),
            },
        )

        if exhausted:
            # 序列耗尽后不再排程任何恢复定时器——此处语义是等待人工处置而非
            # 自动恢复（code-review item debc02bc8d43）。上方 update_spec 已写入
            # 的 _dispatch_backoff_until 未来时刻在本分支不再对应任何重试，该
            # 窗口同时有意承担探测器静默职责：_dispatch_backoffed/
            # _dispatch_lock_conflict_pending 在窗内判「退避中」而早退，
            # orphaned_state 等滞留探测随之静默；error 文案亦按等待人工口径记录。
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
            self._backoff_timers = [t for t in getattr(self, "_backoff_timers", []) if t.is_alive()]
            self._backoff_timers.append(timer)
        timer.start()

    # ── 冷却恢复排程参数化共用实现（code-review item 71e4594e6d49）─────────
    # 三条冷却恢复通道（秒挂 / 信号死法 / 瞬断）的排程与到期回调收敛为以下
    # helper，通道差异全部显式成参数而非隐身拷贝：
    # - ``timers``：通道判重集合（幂等排程）；
    # - ``resolve_delay``：``(spec_name) -> float | None``，返回原始等待秒数，
    #   None 表示本此不排程（秒挂/信号死法：未设冷却截止；瞬断恒返回配置值）；
    # - ``min_delay``：排程下限（秒挂/信号死法 0.5s、瞬断 10s，有意差异）；
    # - ``callback`` / ``scheduled_log``：到期回调与可选排程 INFO 文案模板。

    def _cooldown_remaining(self, spec_name: str, cooldown_until_fn) -> float | None:
        """读冷却截止（``time.monotonic`` 秒，runner._now 口径）的剩余秒数。

        未设冷却截止（``<= 0``）返回 None——调用方据此跳过本次排程。
        """
        until = cooldown_until_fn(spec_name)
        if until <= 0:
            return None
        return float(until) - time.monotonic()

    def _transient_redispatch_delay(self, spec_name: str) -> float:
        """瞬断重派等待秒数（``agents.transient_redispatch_delay_seconds``）。

        配置容错（与 _dispatch_backoff_schedule 同口径）：非法配置值回退
        缺省 600s，不得中断瞬断恢复排程。``spec_name`` 仅用于对齐
        ``resolve_delay`` 签名（该通道等待时长与 spec 无关）。
        """
        try:
            return float(
                self._pm._get_config("agents.transient_redispatch_delay_seconds", 600)
            )
        except (TypeError, ValueError):
            return 600.0

    def _schedule_recovery_timer(
        self,
        spec_name: str,
        timers: set,
        resolve_delay,
        min_delay: float,
        callback,
        scheduled_log: str | None = None,
        lock_held: bool = False,
    ) -> None:
        """统一排程入口：按 ``lock_held`` 决定是否自取 ``_queue_lock``。

        ``lock_held``：调用方已持 ``_queue_lock`` 时为 True（_process_queue 场景），
        跳过内部再取锁——threading.Lock 非重入，双重获取会死锁。
        """

        def _locked(spec: str) -> None:
            self._schedule_recovery_timer_locked(
                spec, timers, resolve_delay, min_delay, callback, scheduled_log,
            )

        if lock_held:
            _locked(spec_name)
            return
        with self._queue_lock:
            _locked(spec_name)

    def _schedule_recovery_timer_locked(
        self,
        spec_name: str,
        timers: set,
        resolve_delay,
        min_delay: float,
        callback,
        scheduled_log: str | None = None,
    ) -> None:
        """锁内实现（调用方已持 _queue_lock）：判重 → 计算延迟 → 排程定时器。

        - 已在 ``timers`` 中则幂等早退；
        - ``resolve_delay`` 返回 None 则本此不排程；
        - 延迟下限 ``min_delay``；
        - ``scheduled_log`` 非空时于定时器启动后记 INFO，模板可用
          ``{spec_name}`` / ``{delay}``（后者已取 int）占位。
        """
        if spec_name in timers:
            return
        raw_delay = resolve_delay(spec_name)
        if raw_delay is None:
            return
        delay = max(min_delay, float(raw_delay))
        timer = threading.Timer(delay, callback, args=(spec_name,))
        timer.daemon = True
        timers.add(spec_name)
        timer.start()
        if scheduled_log is not None:
            self._pm.logger.info(
                "pm_engine",
                scheduled_log.format(spec_name=spec_name, delay=int(delay)),
            )

    def _fire_recovery_callback(
        self, spec_name: str, timers: set, fired_log: str,
    ) -> None:
        """冷却到期回调共用体：摘判重标记 → 记日志 → 重入派发 + process_queue。"""
        with self._queue_lock:
            timers.discard(spec_name)
        self._pm.logger.info("pm_engine", fired_log)
        try:
            self._pm._on_spec_ready(spec_name)
        finally:
            self._pm._process_queue()

    def _schedule_instant_fail_recovery(self, spec_name: str, lock_held: bool = False) -> None:
        """冷却到期后重入 ``_on_spec_ready``（cli-retry-backoff 2.2）。

        幂等：已为该 spec 排程恢复定时器则不再重复（``_instant_fail_timers`` 集合
        判重）。cooldown_until 以 ``time.monotonic`` 记（runner._now），差值为
        剩余秒；到期回调重新触发派发并顺带 process_queue。

        ``lock_held``：调用方已持 ``_queue_lock`` 时为 True（_process_queue 场景），
        跳过内部再取锁——threading.Lock 非重入，双重获取会死锁。
        """
        self._schedule_recovery_timer(
            spec_name,
            timers=self._instant_fail_timers,
            resolve_delay=lambda spec: self._cooldown_remaining(
                spec, self._pm._instant_fail_cooldown_until),
            min_delay=0.5,
            callback=self._on_instant_fail_recovery,
            lock_held=lock_held,
        )

    def _schedule_instant_fail_recovery_locked(self, spec_name: str) -> None:
        """锁内实现（调用方已持 _queue_lock）排程冷却恢复定时器。"""
        self._schedule_instant_fail_recovery(spec_name, lock_held=True)

    def _on_instant_fail_recovery(self, spec_name: str) -> None:
        """秒挂冷却到期回调：重新唤起派发（幂等，多定时器并发安全）。"""
        self._fire_recovery_callback(
            spec_name,
            self._instant_fail_timers,
            f"秒挂冷却到期，恢复调度 '{spec_name}'（cli-retry-backoff 自动恢复）",
        )

    # ── evo-sigterm-source-tracking-cooldown：信号死法冷却恢复排程 ─────────
    # 仿秒挂冷却（instant_fail_recovery）定时器模式：信号死法冷却到期后重入
    # `_on_spec_ready` + `_process_queue`。与 _instant_fail_timers 独立——两条
    # 冷却通道各自排程恢复，互不覆盖冷却截止（取更晚者生效）。

    def _schedule_signal_kill_recovery(self, spec_name: str,
                                       lock_held: bool = False) -> None:
        """信号死法冷却到期后重入 ``_on_spec_ready``。

        幂等：已为该 spec 排程恢复定时器则不再重复（``_signal_kill_timers``
        集合判重）。cooldown_until 以 ``time.monotonic`` 记（runner._now），
        差值为剩余秒；到期回调重新触发派发并顺带 process_queue。

        ``lock_held``：调用方已持 ``_queue_lock`` 时为 True（_process_queue 场景），
        跳过内部再取锁——threading.Lock 非重入，双重获取会死锁。
        """
        self._schedule_recovery_timer(
            spec_name,
            timers=self._signal_kill_timers,
            resolve_delay=lambda spec: self._cooldown_remaining(
                spec, self._pm._signal_kill_cooldown_until),
            min_delay=0.5,
            callback=self._on_signal_kill_recovery,
            lock_held=lock_held,
        )

    def _schedule_signal_kill_recovery_locked(self, spec_name: str) -> None:
        """锁内实现（调用方已持 _queue_lock）排程信号冷却恢复定时器。"""
        self._schedule_signal_kill_recovery(spec_name, lock_held=True)

    def _on_signal_kill_recovery(self, spec_name: str) -> None:
        """信号死法冷却到期回调：重新唤起派发（幂等，多定时器并发安全）。"""
        self._fire_recovery_callback(
            spec_name,
            self._signal_kill_timers,
            f"信号死法冷却到期，恢复调度 '{spec_name}'"
            f"（evo-sigterm-source-tracking-cooldown 自动恢复）",
        )

    # ── fix-provider-transient-backoff（D4）：transient 恢复排程 ──────────
    # 仿秒挂冷却（instant_fail_recovery）定时器模式：瞬断终态后按
    # `agents.transient_redispatch_delay_seconds`（缺省 600s）延迟重入
    # `_on_spec_ready` + `_process_queue`。与 _retry_count 正交——不清零、不递增。

    def _schedule_transient_recovery(self, spec_name: str, lock_held: bool = False) -> None:
        """瞬断终态后排程等待，到期重新触发派发（fix-provider-transient-backoff D4）。

        幂等：已为该 spec 排程恢复定时器则不再重复（``_transient_timers`` 集合
        判重）。等待时长按 ``agents.transient_redispatch_delay_seconds``
        （缺省 600s）配置。

        ``lock_held``：调用方已持 ``_queue_lock`` 时为 True，跳过内部再取锁。
        """
        self._schedule_recovery_timer(
            spec_name,
            timers=self._transient_timers,
            resolve_delay=self._transient_redispatch_delay,
            min_delay=10.0,  # 最小等待 10s，避免零值/负值
            callback=self._on_transient_recovery,
            scheduled_log=(
                "Transient recovery scheduled for '{spec_name}' in {delay}s "
                "(fix-provider-transient-backoff)"
            ),
            lock_held=lock_held,
        )

    def _schedule_transient_recovery_locked(self, spec_name: str) -> None:
        """锁内实现（fix-provider-transient-backoff）排程 transient 恢复定时器。"""
        self._schedule_transient_recovery(spec_name, lock_held=True)

    def _on_transient_recovery(self, spec_name: str) -> None:
        """瞬断冷却到期回调：重新唤起派发（幂等，多定时器并发安全）。"""
        self._fire_recovery_callback(
            spec_name,
            self._transient_timers,
            f"Transient recovery fired for '{spec_name}' — resuming dispatch "
            f"(fix-provider-transient-backoff)",
        )