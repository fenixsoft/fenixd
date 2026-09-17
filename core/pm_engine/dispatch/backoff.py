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

    def _schedule_instant_fail_recovery(self, spec_name: str, lock_held: bool = False) -> None:
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
            delay,
            self._on_instant_fail_recovery,
            args=(spec_name,),
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

    def _schedule_transient_recovery(self, spec_name: str, lock_held: bool = False) -> None:
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
        delay = float(self._pm._get_config("agents.transient_redispatch_delay_seconds", 600))
        delay = max(10.0, delay)  # 最小等待 10s，避免零值/负值
        timer = threading.Timer(
            delay,
            self._on_transient_recovery,
            args=(spec_name,),
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