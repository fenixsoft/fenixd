"""backoff.py — B 退避/瞬时恢复排程（refactor-giant-classes D1/D3/D5）。

原为 Dispatcher 的 9 个方法（`core/pm_engine/dispatch/_legacy.py`），
原样搬移为 mixin（方法体零改动）。跨组协作仍经宿主实例 `self.<method>`。

D3 patch 缝隙：
- 本组使用 `time` 模块，经模块顶部导入即可——测试
  ``patch.object(_dispatch_mod.time, "time", _tick)`` 修改的是 time 模块对象
  的 ``time`` 属性，全进程共享，patch 依旧生效；
- `DEFAULT_DISPATCH_BACKOFF_SCHEDULE` 常量自包门面 core.pm_engine.dispatch 导入
  （__init__ 内常量定义先于子模块接入行，无环）。
"""

from __future__ import annotations

import math
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
        if isinstance(sched, bool):
            # bool 是 int 子类（code-review item 7b529d5446f4）：配 true 得
            # [1.0]（锁冲突高频自旋重试）、配 false 得 [0.0]（0.5 秒下限自旋）
            # 均被无声采信——按脏配置回默认并 WARNING 留痕，与
            # repair_lane._max_retries/_merge_breaker_threshold 同族归一口径
            # （item 637ed7beaee1）对齐。
            self._pm.logger.warning(
                "pm_engine",
                "配置 pm.dispatch_backoff_schedule 非法（布尔不合法），"
                f"回退默认 {list(DEFAULT_DISPATCH_BACKOFF_SCHEDULE)}: {sched!r}",
            )
            return list(DEFAULT_DISPATCH_BACKOFF_SCHEDULE)
        if isinstance(sched, (int, float)):
            sched = [sched]
        if not isinstance(sched, (list, tuple)) or not sched:
            return list(DEFAULT_DISPATCH_BACKOFF_SCHEDULE)
        out = []
        for x in sched:
            try:
                v = float(x)
            except (TypeError, ValueError, OverflowError):
                # OverflowError 同按脏值跳过（code-review item 64c2ae5ae4b9）：
                # YAML 任意精度巨型 int（如 10**400）送 float() 抛 OverflowError
                # 不在原捕获族内，沿 _handle_dispatch_lock_conflict 向派发主链
                # 外泄——口径对齐 _transient_redispatch_delay /
                # _infra_retry_redispatch_delay（item 851ba3eeed41）。下方
                # isfinite 守卫在 float() 转换之后，拦不住该异常。
                continue
            # code-review item e2d87491cc64：非有限浮点（.inf/.nan，YAML 合法
            # 字面量）按脏值跳过——``.inf`` 使 threading.Timer 永不到期（退避
            # 恢复通道失去唯一驱动），``int(now + delay)`` 对 inf 抛
            # OverflowError 沿派发主链外泄，``.nan`` 经 max(0.0, nan) 落 0.0
            # 造成零间隔自旋重试；isfinite 须在 max 夹紧之前施加（max 会把
            # nan 吸收成 0.0），口径对齐 infra_breaker cooldown_minutes 同构
            # 守卫（item d0a328355581）。
            if not math.isfinite(v):
                continue
            out.append(max(0.0, v))
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
        # code-review item af49c10825f7：count 走锁内原子递增（bump_counters
        # 返回写后值，与 queue.py:2259 _record_wip_defer_retry_failure 同款）：
        # 原先「read_one 读 → 算 +1 → update_spec 绝对写回」两段式读改写，
        # 退避恢复定时器与周期扫描并发进入同一 spec 时各持相同旧值写回、丢一次
        # 递增，退避档位推进变慢、dispatch_stalled 升级晚触发。写后值即本次
        # 冲突序号（1 起）：档位下标取 count-1、耗尽判定 idx >= len(schedule)，
        # 串行语义与原实现逐位等价；下方 update_spec 不再并写该字段（防并发
        # 写回互相覆盖丢增量）。
        # [fenix-ignore:172764d58cb8] 周期扫描与退避定时器同刻并发遇锁会各 bump
        # 一次（档位虚快推进），但后果仅是保守提前升级（dispatch_stalled 早触发、
        # spec 保持 ready、无错误派发）；竞态安全的同 episode 判重须跨读判据+
        # bump+update_spec 持进程锁（无锁时间窗判重有 TOCTOU），引入非重入锁序
        # 风险，故接受现状不判重。
        count = self._pm.state_machine.bump_counters(
            spec_name, {"_lock_conflict_count": 1}
        ).get("_lock_conflict_count", 0)
        schedule = self._pm._dispatch_backoff_schedule()

        now = time.time()
        idx = max(0, count - 1)
        exhausted = idx >= len(schedule)
        delay = schedule[-1] if exhausted else schedule[idx]
        until = int(now + delay)
        from datetime import datetime as _dt, timezone as _tz

        from core.timelib import from_epoch

        until_iso = from_epoch(until).isoformat()
        # 本轮写入值提为局部变量（code-review item 802d5955dd68）：序列耗尽分支
        # 组装 dispatch_stalled 证据时取本轮值，而非 read_one 的更新前旧快照
        # （旧快照取到的是上一轮冲突时间与上一轮退避文案）。
        conflict_at = _dt.now(_tz.utc).isoformat()
        error_text = (
            f"worktree already active (lock conflict); backoff until {until_iso}"
        )

        # 不翻转状态：spec 保持 ready，仅记录退避元数据
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "error": error_text,
                # _lock_conflict_count 已由上方 bump_counters 原子递增落盘，
                # 此处不再并写（防并发写回互相覆盖丢增量）
                "_dispatch_backoff_until": until,
                "_last_lock_conflict_at": conflict_at,
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
                f"lock conflicts={count} (backoff schedule {list(schedule)}s exhausted), "
                f"last conflict at {conflict_at}, "
                f"error={error_text[:120]}"
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
            f"(attempt {count}/{len(schedule)}), not counted against retries",
        )
        self._pm._schedule_backoff_retry(spec_name, delay)

    def _schedule_backoff_retry(self, spec_name: str, delay: float) -> None:
        """退避到期后重入 ``_on_spec_ready``（daemon 线程；关闭期间自然失效）。

        幂等判重（code-review item c996f928d3de）：登记前按 spec_name 查
        ``_backoff_timer_specs``，已存在未到期定时器则先 cancel 旧 Timer 再
        登记新 Timer——同 spec 同时至多一个待到期退避定时器。原先仅 is_alive
        惰性清理后直接 append，退避窗口内再次触发
        ``_handle_dispatch_lock_conflict``（周期扫描与事件回调并发进入）会叠加
        第二个 Timer，到期后 ``_on_spec_ready`` 被重复调用，重复派发尝试再遇锁
        冲突经 bump_counters 推进 ``_lock_conflict_count``，退避档位虚快推进、
        提前耗尽序列触发 dispatch_stalled。cancel 对已到期/在途回调是 no-op，
        不回退已发生的恢复（对齐同文件三条冷却通道 _schedule_recovery_timer
        的幂等判重形态）。
        """
        timer = threading.Timer(
            max(0.5, float(delay)),
            self._pm._on_spec_ready,
            args=(spec_name,),
        )
        timer.daemon = True
        with self._queue_lock:
            # 判重登记表（spec_name -> Timer）：仅本退避通道登记；merge-only
            # 重试定时器走 queue.py _schedule_merge_retry 同构站点共用
            # ``_backoff_timers``，不进本表、不受本判重约束。
            pending: dict = getattr(self, "_backoff_timer_specs", None)
            if pending is None:
                pending = self._backoff_timer_specs = {}
            stale = pending.pop(spec_name, None)
            self._backoff_timers = [t for t in getattr(self, "_backoff_timers", []) if t.is_alive()]
            # code-review item 879ad0f12602：对 stale 无条件 cancel（对齐
            # _schedule_recovery_timer_locked 的重排路径）——cancel 对未 start
            # 的 Timer 同样生效（run 见 finished 已置位即跳过回调）；原 is_alive()
            # 门控会漏掉「已登记尚未 start」（start 在锁外执行）的 stale 定时器，
            # 周期扫描与退避定时器同刻并发重排时残留双在飞定时器，违背本函数
            # 判重不变式（_on_spec_ready 重复触发、_lock_conflict_count 虚快推进）。
            if stale is not None:
                stale.cancel()
            self._backoff_timers.append(timer)
            pending[spec_name] = timer
        # code-review item 488e916852e4：对齐 queue.py:989 / repair_lane.py:305
        # 的线程启动守卫——start 失败（解释器关闭期 RuntimeError、线程资源
        # 耗尽等）时摘除本 timer 登记并记 WARNING，异常不再沿
        # _handle_dispatch_lock_conflict → _process_queue 外泄；本轮退避重试
        # 缺失，恢复依赖 daemon 重启后周期扫描兜底。
        try:
            timer.start()
        except Exception as e:  # noqa: BLE001 — 环境性启动失败按「未排程」处置
            with self._queue_lock:
                self._backoff_timers = [
                    t for t in getattr(self, "_backoff_timers", []) if t is not timer
                ]
                # 判重标记同步回滚（对齐 _schedule_recovery_timer_locked）：失败
                # 的 Timer 未运行，残留登记只占位（下轮排程会替换），摘除保持
                # 登记表与在飞定时器一致。
                if getattr(self, "_backoff_timer_specs", {}).get(spec_name) is timer:
                    self._backoff_timer_specs.pop(spec_name, None)
            self._pm.logger.warning(
                "pm_engine",
                f"backoff retry timer start failed for '{spec_name}' — 已摘除"
                f"登记（恢复依赖下轮周期扫描兜底）: {type(e).__name__}: {e}",
            )

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
        raw = self._pm._get_config(
            "agents.transient_redispatch_delay_seconds", 600
        )
        if isinstance(raw, bool):
            # bool 是 int 子类（code-review item 88ef37e3e57e，对齐
            # _dispatch_backoff_schedule 7b529d5446f4 布尔守卫）：
            # float(True)=1.0 会被 isfinite 守卫误判为合法延时（经 min_delay
            # 夹紧后偏离声明缺省），按脏配置回退缺省并 WARNING 留痕。
            self._pm.logger.warning(
                "pm_engine",
                "配置 agents.transient_redispatch_delay_seconds 非法（布尔不合法），"
                f"回退缺省 600s: {raw!r}",
            )
            return 600.0
        try:
            val = float(raw)
        except (TypeError, ValueError, OverflowError):
            # code-review item 851ba3eeed41：巨大 int（YAML 任意精度）送 float()
            # 抛 OverflowError 同按脏值回退缺省（口径同 infra_breaker threshold，
            # item 8c2855513307）。
            return 600.0
        # code-review item e2d87491cc64：非有限浮点（.inf/.nan）穿透按脏值回退
        # 缺省——``.inf`` 使瞬断重派 Timer 永不到期（恢复通道失去唯一驱动），
        # ``.nan`` 使排程退化为零间隔自旋；口径对齐 infra_breaker
        # cooldown_minutes 同构守卫（item d0a328355581）。
        if not math.isfinite(val):
            return 600.0
        return val

    def _schedule_recovery_timer(
        self,
        spec_name: str,
        timers: set,
        resolve_delay,
        min_delay: float,
        callback,
        scheduled_log: str | None = None,
        lock_held: bool = False,
        resolve_deadline=None,
        deadline_table: dict | None = None,
        handle_table: dict | None = None,
    ) -> None:
        """统一排程入口：按 ``lock_held`` 决定是否自取 ``_queue_lock``。

        ``lock_held``：调用方已持 ``_queue_lock`` 时为 True（_process_queue 场景），
        跳过内部再取锁——保持临界区原子性、避免冗余加锁（``_queue_lock`` 自
        fix-spec-review-blocking-dispatch BUG-01 起为 threading.RLock，同线程
        重入不会死锁）。
        ``resolve_deadline`` / ``deadline_table`` / ``handle_table``：截止对账
        通道（evo-add-instant-fail-cooldown-full-lane-gate 2.3），原样透传锁内
        实现；缺省 None 的通道保持既有幂等早退语义。
        """

        def _locked(spec: str) -> None:
            self._schedule_recovery_timer_locked(
                spec, timers, resolve_delay, min_delay, callback, scheduled_log,
                resolve_deadline=resolve_deadline,
                deadline_table=deadline_table,
                handle_table=handle_table,
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
        resolve_deadline=None,
        deadline_table: dict | None = None,
        handle_table: dict | None = None,
    ) -> None:
        """锁内实现（调用方已持 _queue_lock）：判重 → 计算延迟 → 排程定时器。

        - 已在 ``timers`` 中：未接入截止对账通道（``resolve_deadline`` /
          ``deadline_table`` 缺省 None）保持既有幂等早退；接入通道判重放宽为
          「截止时刻变化即按新截止重排」（evo-add-instant-fail-cooldown-full-
          lane-gate 2.3）——复诵翻倍/续写冷却把 cooldown_until 改写后，旧定时器
          按旧截止排程，不重排则翻倍窗无对应定时器（恢复只能靠周期扫描兜底）。
          截止未变化仍幂等早退（既有语义不变）；截止变化先 cancel 旧 Timer、
          摘判重标记后按新截止重排；
        - ``resolve_deadline``：``(spec_name) -> float | None``，返回该通道当前
          冷却截止单调秒（未设截止——None 或已清零的 0.0；真实冷却通道
          engine._instant_fail_cooldown_until / _signal_kill_cooldown_until
          未冷却时恒返回 0.0——两者均视为「通道未设截止」：此时旧定时器
          保留，到期自会兜底重入派发链）；
        - ``resolve_delay`` 返回 None 则本此不排程；
        - 延迟下限 ``min_delay``；
        - ``scheduled_log`` 非空时于定时器启动后记 INFO，模板可用
          ``{spec_name}`` / ``{delay}``（后者已取 int）占位。
        """
        if spec_name in timers:
            if resolve_deadline is None or deadline_table is None:
                return
            try:
                live_deadline = deadline_table.get(spec_name)
                current_deadline = resolve_deadline(spec_name)
            except Exception:
                return
            if (current_deadline is None or float(current_deadline) <= 0
                    or live_deadline is None
                    or float(live_deadline) == float(current_deadline)):
                # 截止未变化（或通道截止已解除——None 或已清零的 0.0）：
                # 幂等早退，旧定时器保留，到期自会重入派发链（闸门查询侧
                # 届时按现状判定）。
                return
            # 截止时刻变化（冷却被续写/翻倍）：cancel 旧 Timer、摘判重标记，
            # 落到下方按新截止重排。
            deadline_table[spec_name] = float(current_deadline)
            old_timer = (
                handle_table.pop(spec_name, None) if handle_table else None
            )
            if old_timer is not None:
                try:
                    old_timer.cancel()
                except Exception:  # noqa: BLE001 — 已到期/竞态取消失败无碍：
                    # 旧回调幂等（摘标记+重入派发链），至多多一次重入。
                    pass
            timers.discard(spec_name)
        raw_delay = resolve_delay(spec_name)
        if raw_delay is None:
            return
        delay = max(min_delay, float(raw_delay))
        timer = threading.Timer(delay, callback, args=(spec_name,))
        timer.daemon = True
        timers.add(spec_name)
        if resolve_deadline is not None and deadline_table is not None:
            try:
                current_deadline = resolve_deadline(spec_name)
            except Exception:
                current_deadline = None
            deadline_table[spec_name] = (
                float(current_deadline)
                if current_deadline is not None
                else time.monotonic() + delay
            )
        if handle_table is not None:
            handle_table[spec_name] = timer
        # code-review item 488e916852e4：对齐 queue.py:989 / repair_lane.py:305
        # 的线程启动守卫——start 失败（解释器关闭期 RuntimeError、线程资源
        # 耗尽等）时回滚判重标记并记 WARNING：否则该 spec 已入 timers 而定时器
        # 并未运行，后续调用因幂等早退被永久短路，退避/冷却通道失去唯一恢复
        # 驱动；异常亦不再沿 _queue_entry_ready → _process_queue 外泄。
        try:
            timer.start()
        except Exception as e:  # noqa: BLE001 — 环境性启动失败按「未排程」处置
            timers.discard(spec_name)
            if deadline_table is not None:
                deadline_table.pop(spec_name, None)
            if handle_table is not None:
                handle_table.pop(spec_name, None)
            self._pm.logger.warning(
                "pm_engine",
                f"recovery timer start failed for '{spec_name}' — 判重标记已"
                f"回滚（恢复依赖下轮周期扫描兜底）: {type(e).__name__}: {e}",
            )
            return
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
        跳过内部再取锁——保持临界区原子性、避免冗余加锁（``_queue_lock`` 自
        fix-spec-review-blocking-dispatch BUG-01 起为 threading.RLock，同线程
        重入不会死锁）。
        """
        self._schedule_recovery_timer(
            spec_name,
            timers=self._instant_fail_timers,
            resolve_delay=lambda spec: self._cooldown_remaining(
                spec, self._pm._instant_fail_cooldown_until),
            min_delay=0.5,
            callback=self._on_instant_fail_recovery,
            lock_held=lock_held,
            # evo-add-instant-fail-cooldown-full-lane-gate 2.3：截止对账通道——
            # 复诵翻倍续写 cooldown_until 后，排程按「截止时刻变化即重排」
            # 换上对应新截止的定时器。
            resolve_deadline=self._pm._instant_fail_cooldown_until,
            deadline_table=getattr(self, "_instant_fail_timer_deadlines", None),
            handle_table=getattr(self, "_instant_fail_timer_handles", None),
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
        跳过内部再取锁——保持临界区原子性、避免冗余加锁（``_queue_lock`` 自
        fix-spec-review-blocking-dispatch BUG-01 起为 threading.RLock，同线程
        重入不会死锁）。
        """
        self._schedule_recovery_timer(
            spec_name,
            timers=self._signal_kill_timers,
            resolve_delay=lambda spec: self._cooldown_remaining(
                spec, self._pm._signal_kill_cooldown_until),
            min_delay=0.5,
            callback=self._on_signal_kill_recovery,
            lock_held=lock_held,
            # 同款截止对账通道（evo-add-instant-fail-cooldown-full-lane-gate
            # 2.3，共用排程器参数化）：信号死法冷却被 record_signal_kill 续写
            # 截止时同样按新截止重排；截止未变化行为与既有幂等早退一致。
            resolve_deadline=self._pm._signal_kill_cooldown_until,
            deadline_table=getattr(self, "_signal_kill_timer_deadlines", None),
            handle_table=getattr(self, "_signal_kill_timer_handles", None),
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

    # ── evo-verify-infra-retry-lane（D5）：infra-retry 廉价重派排程 ────────
    # 仿瞬断恢复（transient recovery）定时器模式：prepare 失败/可达性 fail-fast
    # 短路轮经 infra-retry 车道决议 "redispatch" 后，延迟经既有 verifier 派发
    # 入口重新入队。定时器延迟（缺省 5s、下限 2s）盖过 worker finally 摘除
    # ``_active_verifies`` 单飞登记的窗口——worker 在飞期间直接 _enqueue 会被
    # 单飞守卫拒绝。与 _transient_timers 独立——两条恢复通道各自排程、互不覆盖。
    # MUST NOT 增减 _redispatch_same_cause_streak / _redispatch_cause_fp
    # （同因重派记账归既有链路，infra-retry 重派不是同因重派语义）。

    def _infra_retry_redispatch_delay(self, spec_name: str) -> float:
        """infra-retry 重派等待秒数（``verify.infra_retry_redispatch_delay_seconds``）。

        配置容错（与 _transient_redispatch_delay 同口径）：非法配置值回退缺省
        5s，不得中断重派排程。``spec_name`` 仅用于对齐 ``resolve_delay`` 签名
        （该通道等待时长与 spec 无关）。
        """
        raw = self._pm._get_config(
            "verify.infra_retry_redispatch_delay_seconds", 5
        )
        if isinstance(raw, bool):
            # bool 是 int 子类（code-review item 88ef37e3e57e，对齐
            # _dispatch_backoff_schedule 7b529d5446f4 布尔守卫）：
            # float(True)=1.0 会被 isfinite 守卫误判为合法延时（经 min_delay
            # 夹紧后偏离声明缺省），按脏配置回退缺省并 WARNING 留痕。
            self._pm.logger.warning(
                "pm_engine",
                "配置 verify.infra_retry_redispatch_delay_seconds 非法（布尔不合法），"
                f"回退缺省 5s: {raw!r}",
            )
            return 5.0
        try:
            val = float(raw)
        except (TypeError, ValueError, OverflowError):
            # 巨大 int（YAML 任意精度）送 float() 抛 OverflowError 同按脏值回退
            # 缺省（口径同 _transient_redispatch_delay，item 851ba3eeed41）。
            return 5.0
        if not math.isfinite(val):
            return 5.0
        return val

    def _schedule_infra_retry_redispatch(
        self, spec_name: str, lock_held: bool = False
    ) -> None:
        """infra-retry 车道决议 "redispatch" 后排程廉价重派（evo-verify-infra-retry-lane）。

        幂等：``_infra_retry_timers`` 集合判重（同 spec 同时至多一个待到期
        重派定时器，对齐 _schedule_recovery_timer 三条冷却通道同款形态）。
        到期回调 **不经** ``_on_spec_ready``（该入口只入队 implementer/
        fast-track，不适用 verifier 重派）——专用回调直接经既有派发入口
        ``_enqueue(spec, "verifier")`` 重新入队。

        ``lock_held``：调用方已持 ``_queue_lock`` 时为 True，跳过内部再取锁
        （保持临界区原子性、避免冗余加锁——``_queue_lock`` 自
        fix-spec-review-blocking-dispatch BUG-01 起为 threading.RLock，同线程
        重入不会死锁）。
        """
        self._schedule_recovery_timer(
            spec_name,
            timers=self._infra_retry_timers,
            resolve_delay=self._infra_retry_redispatch_delay,
            min_delay=2.0,  # 下限盖过 worker finally 摘除单飞登记的窗口
            callback=self._on_infra_retry_redispatch,
            scheduled_log=(
                "Infra-retry redispatch scheduled for '{spec_name}' in {delay}s "
                "(evo-verify-infra-retry-lane: cheap lane, no env-freeze round)"
            ),
            lock_held=lock_held,
        )

    def _on_infra_retry_redispatch(self, spec_name: str) -> None:
        """infra-retry 廉价重派到期回调：verifier 重新入队 + process_queue。

        MUST NOT 走 ``_fire_recovery_callback``（其重入 ``_on_spec_ready``，
        只入队 implementer/fast-track）；verifier 重派直接经既有派发入口
        ``_enqueue``。enqueue 拒绝（单飞守卫仍持登记等边缘时序）不重试——
        周期扫描兜底恢复，与既有冷却通道同口径。
        """
        with self._queue_lock:
            self._infra_retry_timers.discard(spec_name)
        self._pm.logger.info(
            "pm_engine",
            f"Infra-retry redispatch fired for '{spec_name}' — re-enqueueing "
            f"verifier (evo-verify-infra-retry-lane)",
        )
        try:
            self._pm._enqueue(spec_name, "verifier")
        finally:
            self._pm._process_queue()