"""
event_bus.py — File-system event monitoring for fenixd.

Watches STATE.md for changes using inotify (Linux) and dispatches
internal events to the PM Engine. Includes periodic full-scan fallback.
"""

import hashlib
import math
import re
import threading
import time
from pathlib import Path
from typing import Dict, Optional

# 依赖闸门接受态（fix-dispatch-wakeup-gap D2 单点口径）：与
# PMEngine._dependencies_satisfied 共用同一常量，杜绝「闸门说满足、唤醒说
# 不够」的双口径漂移——EventBus 仅据此识别「转入接受态」这一事实。
from core.pm_engine.engine import DEPENDENCY_ACCEPTED_STATUSES  # noqa: E402

# ── admin run id 的 spec 段全等判定（code-review item 91607da92bcd）──────────
# run id 由 maintenance_runs._unique_admin_run_id 构造为 ``admin-<spec>-<epoch>``
# （epoch = 纯数字秒级时间戳，现 10 位；撞名退避追加 ``-<n>``；在跑进程表键还
# 可能带 ``-a<n>``/``-r<n>`` attempt/瞬态重试后缀）。spec 名可含连字符且互为
# 前缀（fix-x 与 fix-x-2），``startswith("admin-<spec>-")`` 会把 fix-x-2 的
# run 记到 fix-x 头上，令 fix-x 的 verifier 重验派发被错误互斥且无自愈；故以
# 「epoch 段 ≥10 位数字」锚定 id 边界、贪婪取最长 spec 段后做**全等**比较
# （spec 名自身以连字符+数字结尾，如 fix-2，不会被误剥进 id 段）。
_ADMIN_RUN_ID_RE = re.compile(
    r"^admin-(?P<spec>.+)-\d{10,}(?:-\d+)*(?:-[a-z]\d+)*$"
)


def _admin_run_id_matches_spec(run_id, spec: str) -> bool:
    """run id 是否为该 spec 的 admin run（解析 spec 段全等，非前缀匹配）。"""
    m = _ADMIN_RUN_ID_RE.match(str(run_id))
    return m is not None and m.group("spec") == spec


class EventBus:
    """
    Monitor STATE.md for changes and dispatch events to PM Engine.

    Uses polling + checksum comparison for cross-platform compatibility
    (with optional inotify support on Linux).
    """

    def __init__(
        self, state_path: Path, state_machine, pm_engine, config, logger, hook_dispatcher=None
    ):
        self.state_path = Path(state_path)
        self.state_machine = state_machine
        self.pm_engine = pm_engine
        self.config = config
        self.logger = logger
        # add-spec-hooks D1/D8：可选 hook 分发回调（HookEngine.dispatch）。
        # 未注入则行为与现状一致——状态机与 EventBus 不产生对 hook 引擎的硬依赖。
        self.hook_dispatcher = hook_dispatcher

        self._running = False
        self._watch_thread = None
        self._scan_thread = None
        self._initial_scan_thread = None
        self._last_checksum = None
        self._known_specs: Dict[str, str] = {}  # spec_name → status (last known)
        # 并发保护（code-review item c076ad6c840c）：``_known_specs`` 的
        # 「读旧值 → diff → 整体重写」是一段 read-modify-write 临界区，由三条
        # 线程共享——``_watch_loop``、``_periodic_scan_loop``（→ _dispatch_changes）、
        # ``fenixd-initial-scan``。无锁时两个重叠轮次会（a）读到同一 old_status 而
        # **重复派发**同一状态迁移（重复 spec_* 事件 / hook 回调），或（b）一方的
        # ``_update_known_state`` 重写覆盖另一方刚建立的快照，使迁移双方都观测不到、
        # 事件被静默丢弃到下一轮全扫。``_dispatch_changes`` 对 PM Engine 非幂等，
        # 故整段临界区持锁（见 _state_lock）。
        self._state_lock = threading.RLock()

    def start(self):
        """Start monitoring STATE.md for changes."""
        self._running = True

        # Record initial state
        self._update_known_state()

        # Start the inotify/polling watcher
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            name="fenixd-watcher",
            daemon=True,
        )
        self._watch_thread.start()
        self.logger.info("event_bus", "File watcher started")

        # Start periodic full scan
        # 非 dict 按空段降级（code-review item 762ab9cd9ab7）：``or {}`` 只兜住
        # YAML 空值（None），手改 YAML 使整段为列表/标量（``schedule: [1]``）时
        # 真值非 dict，对其 .get 抛 AttributeError 冲出 start() 使 daemon 启动
        # 失败。config._validate 的 _segment_or_empty 只在局部降级、不修正
        # effective dict，故读取方自防——与 _periodic_scan_loop 对同源读取的
        # 容错口径一致（段级类型损坏按段降级），回退默认 30 分钟。
        schedule = self.config.get("schedule")
        if not isinstance(schedule, dict):
            schedule = {}
        poll_interval = schedule.get("poll_interval_minutes", 30)
        self._scan_thread = threading.Thread(
            target=self._periodic_scan_loop,
            args=(poll_interval,),
            name="fenixd-scanner",
            daemon=True,
        )
        self._scan_thread.start()
        self.logger.info("event_bus", f"Periodic scanner started (interval: {poll_interval}m)")

    def stop(self):
        """Stop monitoring."""
        self._running = False
        # 收口加速（fix-supervisor-hosting-chain 验证修复 BUG-01）：两线程均为
        # daemon 线程（进程退出由 OS 兜底回收），join(timeout) 仅作为「放过当前
        # 轮」的宽容窗。旧值 5s 对分钟级轮询的 scan 线程是纯白等（线程正睡在
        # poll_interval 长 sleep 中），累计再叠加 admin 线程 join 使非计划 SIGTERM
        # 快速停机实测 10s+——逼近 dashboard stop/install 端点 30s 超时线并直接
        # 击穿 12s 安装托管等待窗。watch 2s 一轮保留 2s 宽容；scan 长 sleep 只需
        # 极短等待（其当前轮要么已回到循环头部检查 _running，要么本就在 sleep）。
        if self._watch_thread:
            self._watch_thread.join(timeout=2)
        if self._scan_thread:
            self._scan_thread.join(timeout=0.5)
        # 启动期初扫线程（fix-spec-review-blocking-dispatch 4.3）：daemon=True，
        # 收口语义快速 join 放过当前轮（不阻塞 shutdown；进程退出由 OS 兜底）。
        if self._initial_scan_thread and self._initial_scan_thread.is_alive():
            self._initial_scan_thread.join(timeout=1)
        self.logger.info("event_bus", "Stopped")

    def _snapshot_baseline(self):
        """基线快照：仅 ``_update_known_state``（同步、毫秒级）。

        fix-spec-review-blocking-dispatch 4.1：``full_scan`` 拆分为「基线快照」
        与「扫描主体」两段。基线快照 MUST 在 ``event_bus.start()`` 之后、任何
        后台扫描之前**同步**完成——``_update_known_state`` 建立 ``_known_specs``
        基线，否则后台首扫 / watcher 的 ``_dispatch_changes`` 会把全部存量 SPEC
        判为「新出现」并重放 hook 事件（2026-09-07 事故：15+ pushed spec 的
        commit-push hook 连环触发）。``event_bus.start()`` 本身已同步调用
        ``_update_known_state()``，本方法属**显式化该不变量**的
        冗余加固（design D5），不是唯一保障。
        """
        self._update_known_state()

    def start_initial_scan(self):
        """把初扫主体提交到后台线程（fix-spec-review-blocking-dispatch 4.2/4.3）。

        fenixd.start() 在 ``event_bus.start()``（基线快照 + watcher/scanner 启动）
        之后调用：扫描主体在独立 daemon 线程执行（命名对齐 ``fenixd-*`` 同族），
        立即返回，MUST NOT 阻塞调用方进入主循环。扫描异常由 ``_run_full_scan_body``
        内部逐段捕获（单条 SPEC 失败只跳过该条），线程级异常不向上冒泡。
        线程句柄由 EventBus 持有（``_initial_scan_thread``），``stop()`` 收口语义
        覆盖它。
        """
        self._initial_scan_thread = threading.Thread(
            target=self._run_full_scan_body,
            name="fenixd-initial-scan",
            daemon=True,
        )
        self._initial_scan_thread.start()
        self.logger.info("event_bus", "Initial async scan started")

    def full_scan(self):
        """Perform a complete scan of STATE.md, dispatch events, and run blocker check.

        同步入口（fix-spec-review-blocking-dispatch 4.1 兼容契约）：「基线快照 +
        扫描主体」两段顺序执行。既有调用方语义逐字不变——``_periodic_scan_loop``
        继续整调用同步版；``fenixd.start()`` MUST NOT 调用异步版
        （否则后台扫描线程永被同步等待吞掉）；启动初扫请用 ``start_initial_scan``。

        韧性（fix-dispatch-orphan D3/D4）：单条 SPEC 的处理异常只跳过该条并记日志，
        不中止整轮扫描；扫描末尾输出 handled/failed 统计。
        """
        self._snapshot_baseline()
        self._run_full_scan_body()

    def _run_full_scan_body(self):
        """full_scan 扫描主体（fix-spec-review-blocking-dispatch 4.1/4.2）。

        从 ``full_scan``（同步入口）中抽取为独立方法，由 ``start_initial_scan``
        提交到后台 daemon 线程异步执行（不阻塞 fenixd.start() 进入主循环）。
        ``_periodic_scan_loop`` 继续整调用同步版 ``full_scan``（= 基线快照 +
        扫描主体），无二次异步（4.5）。

        韧性（fix-dispatch-orphan D3/D4）：单条 SPEC 的处理异常只跳过该条并记
        日志，不中止整轮扫描；扫描末尾输出 handled/failed 统计。
        """
        self.logger.debug("event_bus", "Performing full scan...")
        try:
            current_specs = self.state_machine.read_all()
        except Exception as e:
            # 读取阶段异常：无论如何不得静默中止（事故家族 Full scan failed）
            self.logger.error("event_bus", f"Full scan read failed: {e}")
            return

        # dispatch_changes 内部已逐条捕获 PM Engine 异常，此处整体包裹兜底
        try:
            self._dispatch_changes(current_specs)
        except Exception as e:
            self.logger.error("event_bus", f"Full scan dispatch failed: {e}")

        # Recovery：逐条隔离，单条异常只跳过该条并记 error，其余 SPEC 继续
        handled = 0
        failed = 0
        for name, entry in current_specs.items():
            if not isinstance(entry, dict):
                # 解析层已规范化（1.2），此处双保险：非 dict 条目直接跳过
                self.logger.warning(
                    "event_bus",
                    f"Recovery 跳过非法条目 '{name}'（非 dict），以防扫描崩溃",
                )
                failed += 1
                continue
            ok = self._recover_one(name, entry)
            if ok:
                handled += 1
            else:
                failed += 1

        # blocker 检测同样整体包裹，单条异常不影响 recovery 已完成的动作
        try:
            self.pm_engine.check_blockers()
        except Exception as e:
            self.logger.error("event_bus", f"Blocker check failed: {e}")

        # 扫描统计可观测：handled = 成功处理的条目数，failed = 跳过/失败的条目数
        self.logger.info(
            "event_bus",
            f"Full scan complete: handled={handled}, failed={failed}, "
            f"total={len(current_specs)}",
        )

        # 自动修复周期兜底激活（add-code-review-auto-fix，task 7.2 / design D4
        # 路径二）：每轮 full scan 末尾触发一次编排检查点，覆盖 daemon 重启、
        # 异常中断后的续做。经可选的 code_fix_orchestrator（未装配时静默跳过，
        # 形态对齐既有可选组件调用）；异常记 WARNING 不阻断扫描。
        _fix_orch = getattr(self, "code_fix_orchestrator", None)
        if _fix_orch is not None:
            try:
                _fix_orch.checkpoint()
            except Exception as e:  # noqa: BLE001 — 兜底激活失败不影响扫描
                self.logger.warning("event_bus", f"code-fix checkpoint failed: {e}")

    def _recover_one(self, name: str, entry: dict) -> bool:
        """对单个 SPEC 执行 recovery 动作；返回 True 表示处理成功（含有意跳过）。

        单条异常在此捕获并记 error（含 spec 名），调用方据此计入 failed 统计，
        但不中止整轮扫描。
        """
        try:
            status = entry.get("status", "")
            if status == "drafted":
                # add-start-after-scope-config 2.4：start_after 定时拾取早退
                # （与 _recover_ready 既有早退同源）——本分支受
                # gates.start_after_scope 条件约束：full 时未到期/哨兵的 SPEC 不被
                # 恢复路径晋升（否则每轮扫描生产「re-triggering promote」噪音事件并
                # 提前拾取，实证 add-project-detail-tabs 提前 42 分钟）；dispatch 时
                # 回到旧行为（照常恢复晋升）。
                # 级别偏离登记：_recover_ready 同类跳过现为 info，本处取
                # debug 是为避免每个定时 SPEC 每 60s 一条噪音；_recover_ready 保持
                # 不动（Non-Goals，本 SPEC 不顺带改）。
                if self._start_after_blocks(name, entry, "drafted"):
                    return True
                self.logger.info("event_bus", f"Recovery: re-triggering promote for '{name}'")
                self.pm_engine.handle_event("spec_drafted", name, entry)
            elif status == "reviewing":
                # add-start-after-scope-config 2.5：同源早退（reviewing 分支，受
                # scope 条件约束），措辞复用 _recover_ready 既有串 + 分支后缀，
                # debug 级，MUST NOT 打「re-triggering spec_reviewing」日志、
                # 不写 STATE。
                if self._start_after_blocks(name, entry, "reviewing"):
                    return True
                self.logger.info(
                    "event_bus", f"Recovery: re-triggering spec_reviewing for '{name}'"
                )
                self.pm_engine.handle_event("spec_reviewing", name, entry)
            elif status == "implemented":
                # Skip if already had a tester run (already verified, avoid re-trigger loop)
                if entry.get("tester_run"):
                    self.logger.debug(
                        "event_bus", f"Skipping recovery for '{name}': already verified"
                    )
                    return True
                # B6（fenixd-registry-ignored-false-attribution-loop 后续）：
                # inconclusive 暂停期（_handle_env_blocked_inconclusive /
                # judge 自述环境暂停）写 _inconclusive_attempts 暂停自动重验，
                # 暂停时 tester_run 恰被置 None——本分支若只查 tester_run 会在
                # 每个扫描周期无视暂停标记强行 re-trigger（add-spec-status-
                # modal-budget 实证每小时重验 9 轮）。暂停唯一出路是人工处置后
                # 解冻/清计数，与「暂停自动重验」语义一致。
                try:
                    attempts = int(entry.get("_inconclusive_attempts", 0) or 0)
                except (TypeError, ValueError):
                    attempts = 0
                if attempts > 0:
                    self.logger.info(
                        "event_bus",
                        f"Skipping recovery for '{name}': inconclusive 暂停自动重验中"
                        f"（_inconclusive_attempts={attempts}），等待人工处置",
                    )
                    return True
                self.logger.info("event_bus", f"Recovery: re-triggering verify for '{name}'")
                self.pm_engine.handle_event("spec_implemented", name, entry)
            elif status == "testing":
                self._recover_testing(name, entry)
            elif status == "ready":
                self._recover_ready(name, entry)
            elif status == "bug-found":
                self.logger.info("event_bus", f"Recovery: re-triggering bug_found for '{name}'")
                self.pm_engine.handle_event("spec_bug_found", name, entry)
            elif status == "verified":
                # Skip if already done (verified→done transition already happened)
                # ── fix-verified-gate-evidence-race D3：re-trigger 心跳保留 ──
                # task-gap 拦截生效期间，re-trigger 每 30 分钟重评门禁——快照持久
                # 后重评是确定性的（有缺口幂等再拦、人工补勾后放行 + 清 error），
                # 不触发状态突变。re-trigger 是人工修复的感知心跳，不是危害源；
                # 不因 task-gap 前缀抑制，否则人工补勾后 spec 永远卡在 verified。
                self.logger.info("event_bus", f"Recovery: re-triggering verified→done for '{name}'")
                self.pm_engine.handle_event("spec_verified", name, entry)
            return True
        except Exception as e:
            self.logger.error(
                "event_bus",
                f"Recovery failed for spec '{name}': {type(e).__name__}: {e}",
            )
            return False

    def _start_after_blocks(self, name: str, entry: dict, status_label: str) -> bool:
        """start_after 定时拾取早退判定（_recover_one drafted/reviewing 单点共用）。

        惰导入 ``start_after_blocks_promotion``（导入失败同样 fail-open）→ 命中
        记 debug 级跳过日志（含状态标签后缀）并返回 True（调用方早退、计入
        handled）；判定异常记 warning 后返回 False（调用方继续既有恢复路径）。
        返回 True 表示「须早退」。
        """
        try:
            from core.state_machine import start_after_blocks_promotion

            if start_after_blocks_promotion(entry, self.config):
                self.logger.debug(
                    "event_bus",
                    f"Recovery: skip '{name}' — start_after scheduled pickup "
                    f"pending（{status_label}）",
                )
                return True
        except Exception as e:
            # fail-open：无法判定时不阻塞既有恢复路径，记日志（2.3）
            self.logger.warning(
                "event_bus",
                f"start_after 判定异常 '{name}'（fail-open 放行）: {e}",
            )
        return False

    def _recover_testing(self, name: str, entry: dict):
        """testing 无驱动恢复出口（add-control-plane-silent-failure-guards 4.3）。

        事故根因（proposal.md §Why）：spec 落入 testing 后 verifier 入队静默
        丢失（handle_event 实参不符 TypeError），运行期无人驱动、只能等 daemon
        重启回退 ready——testing 态在 recovery 分支中无任何出口。本方法补齐：

        - 复用 implemented 分支的防重入守卫：`_inconclusive_attempts
          > 0`（暂停自动重验）跳过；`tester_run` 的重验风暴防护由无驱动判定的
          「run 文件活跃度 + 存活子进程」检查吸收——verifier 在跑 = 该 spec
          有近期写活动的 run 文件/存活子进程 → 非无驱动 → 跳过（等效于
          implemented 分支「已有 tester run 即跳过」）。注意不可按 implemented
          分支原样查 tester_run 硬挡：env 阻塞会写入 tester_run="blocked:app-
          unreachable" 标记，硬挡会让事故形态（复位后 testing 无驱动）永不恢复。
        - 无驱动判定与 admin_monitor._detect_orphaned_state 共用
          `spec_is_undriven` 同一口径（R1 三条件 + 2026-09-18 补的条件 ④
          「无排队中的派发条目」），防止双路径重复触发；pm_engine 注入见调用点。
        """
        try:
            attempts = int(entry.get("_inconclusive_attempts", 0) or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts > 0:
            self.logger.info(
                "event_bus",
                f"Skipping recovery for '{name}': inconclusive 暂停自动重验中"
                f"（_inconclusive_attempts={attempts}），等待人工处置",
            )
            return
        project_root = getattr(self.pm_engine, "project_root", None)
        if project_root is None:
            self.logger.debug(
                "event_bus",
                f"Skipping recovery for '{name}': 无 project_root，无法判定无驱动",
            )
            return
        from core.admin_monitor import spec_is_undriven

        # 注入 pm_engine（2026-09-18）：条件 ④「无排队中的派发条目」——本恢复
        # 出口同样受「已入队待槽」盲区影响（该出口的 `spec_implemented` 重派会被
        # `_enqueue` 去重吸收、队列非空时 `_process_queue` 直接返回，于是同一 spec
        # 每 12 分钟被重复 re-trigger 一次刷日志）。判定口径与 admin_monitor
        # 孤儿探测共用同一函数，勿在此另写一份。
        if not spec_is_undriven(project_root, name, entry, pm_engine=self.pm_engine):
            self.logger.debug(
                "event_bus",
                f"Skipping recovery for '{name}': testing 有驱动/有意等待中",
            )
            return
        # fix-recovery-path-blockers D2：verifier 重验派发与在飞 admin run 互斥。
        # admin 正在写 STATE/场景文件（test_scenarios.json）时重验会读半成品产物；
        # 守卫覆盖该 spec 的**任意** signal_type 处置。在飞判定为真 → 跳过本次
        # 重验派发（spec 保持 testing 原样）并记 INFO。
        if self._admin_inflight_guard(name):
            self.logger.info(
                "event_bus",
                f"Skipping recovery for '{name}': admin 处置在飞，"
                f"verifier 重验派发互斥（fix-recovery-path-blockers D2）",
            )
            return
        self.logger.info(
            "event_bus",
            f"Recovery: re-triggering verify for undriven testing '{name}'",
        )
        self.pm_engine.handle_event("spec_implemented", name, entry)

    def _admin_inflight_guard(self, spec: str) -> bool:
        """verifier 派发前置守卫：该 spec 是否有在飞/待派发的 Administrator run。

        fix-recovery-path-blockers D2：派发互斥守卫，取用面按 design D2——
        PMEngine/PipelineContext 均**不持有** admin_monitor 引用，守卫经两条
        **无需新注入**的通路探测并联：

          (a) ``AdminStore(project_root, logger)`` 纯路径构造（admin_store.py），
              读 ``read_all()`` 后套模块级 ``_spec_has_active_admin_run`` 归并
              判定（与 AdminMonitor._has_active_admin_run_for_spec 同源，勿二次
              漂移）——覆盖「pending 但进程已死」的残骸形态；
          (b) ``agent_runner.running_run_ids()`` 中存在 spec 段与该 spec
              **全等**的 ``admin-<spec>-<epoch>`` run（``_admin_run_id_matches_spec``
              解析判定，前缀匹配在 spec 名互为前缀时会记错账）——admin run 经
              ``_run_claude`` 注册进 ``_running_agents``，本通路只覆盖**进程
              存活**的 admin run。

        任一成立 → 返回 True（调用方跳过本次重验派发）；两路皆异常 → fail-open
        返回 False 放行并记 WARNING（守卫故障不阻断恢复路径）。
        """
        project_root = getattr(self.pm_engine, "project_root", None)
        admin_found = False
        # 通路 (a)：AdminStore 纯路径构造 + 同源归并判定
        if project_root is not None:
            try:
                from core.admin_store import AdminStore
                from core.admin_monitor import _spec_has_active_admin_run

                store = AdminStore(project_root, self.logger)
                admin_found = _spec_has_active_admin_run(store, spec, logger=self.logger)
            except Exception as e:
                self.logger.warning(
                    "event_bus",
                    f"admin 在飞判定通路(a)异常 fail-open '{spec}': "
                    f"{type(e).__name__}: {e}",
                )
        # 通路 (b)：进程表侧口径（互补：只含进程存活的 admin run）
        if not admin_found:
            agent_runner = getattr(self.pm_engine, "agent_runner", None)
            if agent_runner is not None:
                try:
                    running = agent_runner.running_run_ids()
                    admin_found = any(
                        _admin_run_id_matches_spec(rid, spec) for rid in running
                    )
                except Exception as e:
                    self.logger.warning(
                        "event_bus",
                        f"admin 在飞判定通路(b)异常 fail-open '{spec}': "
                        f"{type(e).__name__}: {e}",
                    )
        return admin_found

    def _recover_ready(self, name: str, entry: dict):
        """recovery 的 ready 分支（fix-dispatch-orphan D4 白名单）。

        存活判定（有存活 agent 子进程 / 未超时活跃 worktree 锁）由
        ``_ready_has_live_child`` 给出；存活则跳过并记「skip: live child present」，
        不重置状态、不清字段；否则重新派发前清 error、保留 implementer_run。

        frozen 复核（alert-noise-governance 2.1）：frozen=True 的条目在读到后、
        清 error 前直接跳过（INFO 留痕、零 STATE 写入）——外部回置把冻结 spec
        的 status 打回 ready 时，恢复链不得清 error/重派（见方法体内注释）。
        """
        # frozen 复核（alert-noise-governance 2.1，frozen-replay-escalation-guard
        # 登记链）：外部 STATE 回置可能只改 status 不动 frozen 字段（「部分回
        # 置」腿），冻结 spec 被打回 ready 后若无此守卫，本恢复路径每 60s 清
        # error 并重派，同日重放「就绪→派发→闸门拦截→冻结」循环（2026-09-22
        # 实证：9 轮重放、18 条闸门 ERROR）。命中即 INFO 跳过（含 spec 名与
        # 原因）；早退路径零 STATE 写入（本函数仅在 error 非空时写 STATE）。
        # 复用 pm_engine._frozen_state 保持 legacy 文本契约兼容（recovery.py
        # in-place redispatch 同款先例）；判定异常 fail-open 不阻塞既有恢复。
        try:
            # 仅认真实 True（is True）：pm_engine 为 MagicMock 替身时返回值是
            # Mock 对象（truthy），直接 bool() 会把全部 ready 误判为冻结
            frozen = self.pm_engine._frozen_state(entry) is True
        except Exception:
            frozen = False
        if frozen:
            self.logger.info(
                "event_bus",
                f"Recovery: skip '{name}' — frozen spec awaiting manual "
                f"unfreeze (frozen-replay guard, zero STATE write)",
            )
            return

        # start_after 定时拾取门未到期的 spec（scheduled-spec-pickup）：不是孤儿
        # ——daemon 每轮 dispatch 已按 start_after_pending 正确 skip，recovery 再
        # 重触发只会生产噪音事件（实证 2026-09-11 add-main-tree-deps-provision 每
        # 30 分钟被误标孤儿 ready 重触发一次）。未到期直接跳过，到期后自然拾取。
        try:
            from core.state_machine import start_after_pending

            if start_after_pending(entry):
                self.logger.info(
                    "event_bus",
                    f"Recovery: skip '{name}' — start_after scheduled pickup pending",
                )
                return
        except Exception:
            pass  # 无法判定时不阻塞既有恢复路径（fail-open）

        # 白名单判定：存在存活 agent 子进程 → 视为正在工作，跳过并保留状态
        if self._ready_has_live_child(name):
            self.logger.info(
                "event_bus",
                f"Recovery: skip '{name}' — live child present",
            )
            return
        # 无存活子进程：孤儿 ready 必须重新派发。重派发前清 error 字段
        # （避免旧 error 一直阻塞），但保留 implementer_run 作为历史记录（D2）。
        # 关键：error 清空必须写回 STATE.md，否则下轮 full_scan 仍读到此 error，
        # 该孤儿每 30 分钟被重复重置派发（事故家族「孤儿滞留」的直接成因，
        # 与白名单反转想消除的盲区同源）。dispatch 只消费内存副本 updated，
        # 不会回写，因此此处显式持久化 error=None（补 D4 遗漏点）。
        # 该写回仅在 error **非空**时执行（fix-orphan-ready-recovery-liveness D4）：
        # 对已为 None 的字段写 None 本即空操作，但按 60 秒精触发粒度重复执行
        # 会让每个健康 ready SPEC 每 60 秒产生一次 STATE.md 全量重写 + 一条
        # Updated SPEC 日志——「error 清空必须写回」的论证只对 error 非空成立，
        # 稳态（error 已空）应零写入。
        updated = {k: v for k, v in entry.items() if k != "error"}
        updated["error"] = None
        if entry.get("error") is not None:
            try:
                self.state_machine.update_spec(name, {"error": None})
            except Exception as e:
                # 写回失败不阻断派发：本就靠后续扫描兜底，仅记日志
                self.logger.error(
                    "event_bus",
                    f"Recovery: failed to persist error-clear for orphan '{name}': {e}",
                )
        self.logger.info(
            "event_bus",
            f"Recovery: re-triggering implement for orphan ready '{name}' "
            f"(error cleared, implementer_run preserved)",
        )
        self.pm_engine.handle_event("spec_ready", name, updated)

    def recover_orphan_ready(self):
        """孤儿 ready 短周期精触发（fix-orphan-ready-recovery-liveness D3/D4）。

        逐条扫描 ``ready`` 态 SPEC，对确无驱动的条目走与既有 full_scan 恢复
        **完全同源**的 ``_recover_ready`` 处理路径——不复制判据、不新增第二
        实现点，恢复延迟从「最坏一个扫描周期（30 分钟）」降到「最坏一个精触发
        周期（60 秒）」。full_scan 仍为兜底，``schedule.poll_interval_minutes``
        语义不变。

        入口先过两道「有意等待」早退（design D3），二者 MUST 零 STATE 写入、
        MUST NOT 打印「re-triggering implement for orphan ready」日志：

        - ``_cancelled_hold`` 为真（人工取消保持）→ 跳过；
        - ``self.pm_engine._dispatch_backoffed(entry)`` 为真（``_dispatch_backoff_until``
          未到期）→ 跳过——``error`` 承载退避原因（``_handle_dispatch_lock_conflict``
          写入的「backoff until」），精触发不得抹掉它。

        任一闸门判定异常 MUST 按「不早退」fail-open（保底恢复不被新闸门吞掉），
        记日志后继续走既有恢复路径。

        **核对结论（2026-09-17，以代码为准）——精触发未绕过任何闸门**：
        恢复侧既有门 = ``start_after_pending``（本文件 ``_recover_ready`` 内）、
        存活子进程（``_ready_has_live_child``）与 frozen 复核（alert-noise-
        governance 2.1：frozen=True 跳过恢复、零 STATE 写入——有意等待态，
        冻结 spec 的唯一出路是补内容后人工 unfreeze_spec）；派发侧既有门（``_on_spec_ready``）
        = 关闭中 / 10 秒冷却 / 单飞 /
        ``has_active_worktree`` / ``_dispatch_backoffed`` / ``start_after`` / 依赖，
        精触发经 ``_on_spec_ready → _enqueue → _process_queue`` 全链路生效。
        方位校正：``_instant_fail_cooled`` 与并发闸 ``max_concurrent`` 不在
        ``_on_spec_ready`` 内、而在 ``_process_queue`` 的候选筛选与调度处，经上述链路
        同样生效，判定为「未被绕过」。另须纠正的原表述：``_recover_ready`` 与
        ``_on_spec_ready`` 均**不读** ``_cancelled_hold``，故该守卫即本入口的
        早退闸门（复用既有标记，非新判据）。

        **有界性核对（design D4，真实吸收点是队列去重而非冷却窗口）**：重复
        恢复尝试由 ``_enqueue`` 按 ``(spec_name, agent_type)`` 去重吸收——已入队等待并发槽的 SPEC
        不会被 60 秒重试重复入队。``_pending_dispatches`` 单飞与 ``_last_dispatch_at``
        10 秒冷却（``DISPATCH_COOLDOWN_SECONDS = 10``）
        只吸收**秒级**重复触发，**不足以**吸收 60 秒间隔的重试——故有界性依赖
        队列去重与本入口的两道有意等待早退闸门，MUST NOT 依赖冷却窗口（后续
        删去重或误以为冷却兜住都会破坏有界性）。

        稳态（error 为空、无存活子进程）经 ``_recover_ready`` 零 STATE 写入
        （D4），不会产生「写 error → 触发 spec_ready 事件」的自激。

        统计口径（code-review item 42bc50bb86b2）：``handled`` 沿用
        ``_recover_one``/``_run_full_scan_body`` 既有语义——**含有意跳过**：
        进入 ``_recover_ready`` 后因 frozen / start_after 未到期 / 存活子进程
        零动作早退的条目同样计入 handled（``_recover_one`` docstring 明示
        「True 表示处理成功（含有意跳过）」），故 handled>0 不等于「发生了
        恢复动作」；入口两道有意等待早退（取消保持 / 派发退避）则不计数。
        """
        try:
            current_specs = self.state_machine.read_all()
        except Exception as e:
            self.logger.error(
                "event_bus",
                f"Orphan ready recovery read failed: {e}",
            )
            return
        handled = 0
        failed = 0
        for name, entry in current_specs.items():
            if not isinstance(entry, dict):
                failed += 1
                continue
            if entry.get("status") != "ready":
                continue
            try:
                # 有意等待早退 ①：人工取消保持（_cancelled_hold）
                if entry.get("_cancelled_hold"):
                    continue
                # 有意等待早退 ②：派发退避期（_dispatch_backoff_until 未到期）。
                # 读既有判据 _dispatch_backoffed，异常 fail-open 到「不早退」。
                if self.pm_engine._dispatch_backoffed(entry):
                    continue
            except Exception as e:
                self.logger.error(
                    "event_bus",
                    f"Orphan ready early-exit gate failed for '{name}' "
                    f"(fail-open, proceeding with recovery): {e}",
                )
            try:
                self._recover_ready(name, entry)
                handled += 1
            except Exception as e:
                self.logger.error(
                    "event_bus",
                    f"Orphan ready recovery failed for '{name}': {e}",
                )
                failed += 1
        if handled or failed:
            self.logger.info(
                "event_bus",
                f"Orphan ready recovery complete: handled={handled}, "
                f"failed={failed}, total={len(current_specs)}",
            )

    def _ready_has_live_child(self, spec_name: str) -> bool:
        """判定 SPEC 是否仍有存活的 agent 子进程（D4 白名单存活依据）。

        接口选型（fix-dispatch-orphan 5.1）：优先复用姊妹变更
        improve-run-lifecycle-governance 落地的 ``agent_runner.has_live_attempt(spec)``。

        兜底实现（fix-orphan-ready-recovery-liveness 补丁）：曾以纯 mtime 回退
        （run 文件 mtime < 120s → 视为活跃）；该兜底不检查末行终态，导致 daemon
        主动 SIGTERM 杀掉的 run（流文件新鲜但末行已是 error 终态）被误判为存活，
        阻塞恢复（2026-09-17 事故）。现兜底 ③ 已加入 ``_file_tail_is_terminal``
        判定——末行已为终态的文件不得作为存活依据（与 ``has_live_attempt``
        的 ``_stream_recent`` 修正同口径，共用 ``RUN_TERMINAL_EVENT_TYPES`` 单源）。

        不重复造锁机制（锁归姊妹变更）；此处仅做「进程表 + run 文件存活判定」的
        轻量存活探测，与姊妹变更语义一致即满足白名单需求。
        """
        # 1) 优先：若姊妹变更已落地 has_live_attempt，直接复用
        agent_runner = getattr(self.pm_engine, "agent_runner", None)
        if agent_runner is not None and hasattr(agent_runner, "has_live_attempt"):
            try:
                if agent_runner.has_live_attempt(spec_name):
                    return True
            except Exception as e:
                # 探测异常不再静默（code-review item 586896a04cd5）：探测坏掉时
                # 静默降级到更弱的兜底，可能把真有驱动的 ready/testing 误判为
                # 无驱动（或反之），且无任何「为何卡在恢复路径」的痕迹。
                self.logger.warning(
                    "event_bus",
                    f"has_live_attempt 探测异常 '{spec_name}'（降级兜底）: "
                    f"{type(e).__name__}: {e}",
                )

        # 2) 兜底：pgrep 匹配 worktree 下的 claude 进程
        if self._pgrep_live_worktree(spec_name):
            return True

        # 3) 兜底：implementer_run 指向的最新 run 文件 mtime < 120s 且末行非终态
        #    （fix-orphan-ready-recovery-liveness：曾仅判 mtime，导致 daemon 主动
        #    SIGTERM 补写的终态 run 在 120s 窗口内被误判为存活；现已加入
        #    ``_file_tail_is_terminal`` 判定，与 ``has_live_attempt`` 的
        #    ``_stream_recent`` 修正同口径）
        run_file = self._latest_impl_run_file(spec_name)
        if run_file is not None and self._run_file_recent(run_file, 120):
            from core.agent_runner.liveness import _file_tail_is_terminal
            if not _file_tail_is_terminal(run_file):
                return True

        return False

    @staticmethod
    def _pgrep_live_worktree(spec_name: str) -> bool:
        """pgrep 匹配 ``.claude/worktrees/{impl,verify,repair}-<spec>-*`` 的 claude 进程。

        orphaned-state-probe-calibration 1.4：从「同语义孪生」改为直接复用
        admin_monitor._pgrep_live_worktree——修复 repair- 前缀失明时只改一处，
        避免孪生漂移（实测：admin_monitor 曾先行补 repair 而本处遗漏会
        造成恢复链与检测链口径不一致）。行为与 admin_monitor 完全一致：
        pgrep -f "{impl,verify,repair}-<spec>-" 任一命中即判存活。

        处置记录（书面 defer，fix-robustness-edge-cases 1.1）：cmdline 子串
        匹配在 spec 名互为前缀时误判活性，判定对象是 worktree 目录名而非 run
        流文件，不在本 SPEC 字面范围；误判方向 fail-open 不误杀。承接方：待
        worktree 活性 SPEC。
        """
        from core.admin_monitor import _pgrep_live_worktree as _impl

        return _impl(spec_name)

    def _latest_impl_run_file(self, spec_name: str) -> Optional[Path]:
        """STATE.md implementer_run 指向的最新 run 文件（复用 dashboard 解析）。

        解析失败记 WARNING 后返回 None（code-review item 586896a04cd5）：旧实现
        静默吞异常，「探测坏掉」（API 改名/run 文件损坏/权限）与「确实无 run」
        不可区分，使判定静默降级而无迹可查。
        """
        try:
            from core.run_task_track import find_impl_run_file

            project_root = getattr(self.pm_engine, "project_root", None)
            if project_root is None:
                return None
            return find_impl_run_file(Path(project_root), spec_name)
        except Exception as e:
            self.logger.warning(
                "event_bus",
                f"_latest_impl_run_file 解析异常 '{spec_name}'（按无 run 处理）: "
                f"{type(e).__name__}: {e}",
            )
            return None

    @staticmethod
    def _run_file_recent(run_file: Path, seconds: int) -> bool:
        """run 文件 mtime 在 seconds 内视为活跃。"""
        try:
            mtime = run_file.stat().st_mtime
            return (time.time() - mtime) < seconds
        except OSError:
            return False

    # ── Internal ──────────────────────────────────────────────────

    def _watch_loop(self):
        """Poll STATE.md for changes using checksum comparison.

        持续失败退避（code-review item 2f1dd6067c88）：STATE.md 长期不可读
        （权限损坏/磁盘故障）时，read_all/dispatch 异常仅记日志、`_last_checksum`
        保持旧值（事件不丢，该设计保留），但固定 2s 重试会各刷一条 error
        （约 1800 条/小时）。连续失败按 2→4→…→60s 指数退避（封顶 60s），
        任一轮正常走完（含 checksum 未变化的空轮）即复位。
        """
        fail_backoff = 2.0
        while self._running:
            try:
                if not self.state_path.exists():
                    time.sleep(2)
                    continue

                current_hash = self._file_checksum()
                if current_hash != self._last_checksum:
                    self.logger.debug("event_bus", "STATE.md changed, dispatching...")
                    # `_last_checksum` MUST 在 read_all/dispatch **成功之后**才提交
                    # （code-review item d7151c041831 / 15f8ddcb4713）：旧实现先提交
                    # checksum 再读盘/派发，若读盘抛异常（外层 except 只记日志），
                    # 该次状态变化事件被静默丢弃、且下轮 checksum 已相同不再触发
                    # ——一次变更永久丢失（仅 30 分钟全扫兜底）。改为成功后提交：
                    # 失败时 checksum 保持旧值，下一 tick 自然重试。
                    current_specs = self.state_machine.read_all()
                    self._dispatch_changes(current_specs)
                    self._last_checksum = current_hash
            except Exception as e:
                self.logger.error("event_bus", f"Watch error: {e}")
                # 连续失败拉长重试间隔（见 docstring 说明），避免长期故障下的
                # 重试风暴；事件不丢语义不变——失败轮 checksum 保持旧值。
                time.sleep(min(fail_backoff, 60.0))
                fail_backoff = min(fail_backoff * 2, 60.0)
                continue

            fail_backoff = 2.0
            time.sleep(2)  # Poll every 2 seconds

    def _periodic_scan_loop(self, interval_minutes: int):
        """Periodic full scan as fallback. 每轮热读 poll_interval（配置热更新生效）。"""
        while self._running:
            try:
                interval = float(
                    self.config.get("schedule", {}).get("poll_interval_minutes", interval_minutes)
                )
            except (TypeError, ValueError, AttributeError):
                # AttributeError：schedule 键存在但值为 null（YAML 空值）时首个
                # .get 返回 None，对其再 .get 即抛——不捕获会冲出循环杀死线程。
                interval = interval_minutes
            # 非有限/非数值脏值统一回退缺省（code-review item 0033524fcb73）：
            # except 的回退值 interval_minutes 源自 start() 未校验的同一配置键，
            # 手改 YAML 写成 "abc" 时字符串原样透传，下方 max() 抛 TypeError；
            # .nan 经 float() 解析为 nan、比较恒 False 穿透 max()，sleep(nan)
            # 抛 ValueError——两条路都会冲出循环杀死扫描线程，周期兜底全扫、
            # 悬空 run 清扫与 code-fix checkpoint 全部静默失效。isfinite 一并
            # 拒绝 ±inf（YAML .inf / 1e400 溢出字面量），与 config.py 既有
            # isfinite 防御范式同口径。
            if not isinstance(interval, (int, float)) or not math.isfinite(interval):
                interval = 30.0
            time.sleep(max(float(interval), 0.5) * 60)
            if self._running:
                self.logger.debug("event_bus", "Periodic scan triggered")
                # ── 运行期悬空 run 清扫（add-runtime-run-sweeper 3.1/3.2）──
                # 每轮 full_scan() **前**调用：先扫后 scan，让当轮 full_scan
                # 消费最新终态事实。经既有 pm_engine → agent_runner 引用，
                # 无新增构造参数。异常降级 WARNING 不阻断当轮扫描。
                # 级别偏离登记（code-review item 2f038f160eed）：与下方 full_scan
                # 失败的 error 有意分档——清扫失败只令悬空 run 滞留一个周期
                # （下轮自动重试，当轮扫描不受影响）；full_scan 失败则整轮恢复
                # 链失效，故取 error。
                try:
                    self.pm_engine.agent_runner.sweep_dangling_runs()
                except Exception as e:
                    self.logger.warning(
                        "event_bus",
                        f"Runtime dangling-run sweep failed (scan continues): "
                        f"{type(e).__name__}: {e}",
                    )
                # 基线快照段（_update_known_state → read_all）无异常保护，STATE.md
                # 并发撕裂/瞬时 I/O 故障抛 OSError 等会冲出循环杀死扫描线程，
                # 30 分钟兜底全扫、悬空清扫与 code-fix checkpoint 全部失效——
                # 对齐 _run_full_scan_body 读取阶段「不得静默中止」口径降级记 error。
                try:
                    self.full_scan()
                except Exception as e:
                    self.logger.error(
                        "event_bus",
                        f"Periodic full scan failed (scan continues): "
                        f"{type(e).__name__}: {e}",
                    )

    def _file_checksum(self) -> str:
        """Compute MD5 checksum of STATE.md.

        读取失败记 WARNING 并返回 ``""``（code-review item 6070d3553ede）：旧实现
        静默吞异常且与「文件缺失」共用 ``""`` 哨兵，使不可读/半写的 STATE.md 与
        被删除无法区分、I/O 故障无任何诊断，且瞬态失败会造成 hash 抖动让 watcher
        误判文件变更。此处留痕异常类型（哨兵语义保持不变——文件确实缺失时
        调用方按空内容处理是正确的）。
        """
        if not self.state_path.exists():
            return ""
        try:
            content = self.state_path.read_bytes()
            return hashlib.md5(content).hexdigest()
        except Exception as e:
            self.logger.warning(
                "event_bus",
                f"STATE.md 校验和读取失败（按空内容处理）: {type(e).__name__}: {e}",
            )
            return ""

    def _update_known_state(self):
        """Update internal snapshot of known SPEC states（持 _state_lock 串行化）。"""
        # 读快照必须在临界区内取得（0d392c7aaec3）：「锁外 read_all → 锁内整体
        # 重写」存在窗口，窗口内另一线程经 _diff_specs 刚写入的快照会被本线程
        # 用旧快照整体覆盖（更新丢失），违背文件头 :46-53 声明的读-改-写原子
        # 不变式。read_all 为纯盘读解析、不持其他锁，锁内调用无死锁风险
        # （RLock 亦允许既有持锁调用方重入）。
        with self._state_lock:
            specs = self.state_machine.read_all()
            self._known_specs = {
                name: entry.get("status", "drafted") for name, entry in specs.items()
            }

    def _dispatch_changes(self, current_specs: dict):
        """Compare current state against known state and dispatch events.

        「读快照 → diff → 重写快照」整段持 ``_state_lock``（RLock 允许重入：
        收尾阶段的 ``pm_engine`` 回调若再读 ``_known_specs`` 不会自锁）。
        PM Engine 处理与依赖唤醒放在锁外执行——它们可能耗时且会回调状态机，
        不应阻塞 watch/scan 的另一条线程超过必要时间。
        """
        with self._state_lock:
            events, accepted_names = self._diff_specs(current_specs)

        # Dispatch events to PM Engine
        for event_kind, spec_name, spec_entry in events:
            self.logger.info(
                "event_bus",
                f"Event: {event_kind} for '{spec_name}'",
            )
            try:
                self.pm_engine.handle_event(event_kind, spec_name, spec_entry)
            except Exception as e:
                self.logger.error(
                    "event_bus",
                    f"PM Engine failed to handle {event_kind}: {e}",
                )

        # 1.1/1.2/1.5：依赖定向唤醒——为每个转入接受态的 SPEC 反查 dependents
        # 并经 PMEngine 门面触发重评（D5：EventBus 只识别事实，派发决策留在
        # PMEngine；复用已读入的 current_specs 字典，不额外读盘的百量级遍历）。
        for accepted_name in accepted_names:
            try:
                dependents = EventBus._find_dependents(current_specs, accepted_name)
                if dependents:
                    self.pm_engine._wakeup_dependents(accepted_name, dependents)
                # 无 dependents → 零副作用、零日志（Task 1.4）
            except Exception as e:
                # 1.5 异常隔离：单条异常本轮内捕获降级为 WARNING，MUST NOT 中断
                # 其他事件派发（full-scan-resilience 同口径）。
                self.logger.warning(
                    "event_bus",
                    f"Dependency wakeup skipped for '{accepted_name}': " f"{type(e).__name__}: {e}",
                )

    def _diff_specs(self, current_specs: dict):
        """纯函数段：与已知快照 diff 出事件与依赖唤醒候选，并原子重写快照。

        MUST 在 ``_state_lock`` 内调用（调用方 ``_dispatch_changes`` 已持锁）。
        Returns: ``(events, accepted_names)``。
        """
        events = []
        # 依赖唤醒候选（dispatch-dependency-wakeup 1.1/1.2）：本轮转入依赖闸门
        # 接受态的 SPEC 名列表（old → new 变化者，且 new ∈ 接受态集合）。
        accepted_names = []

        # Check for new or changed SPECs
        for name, entry in current_specs.items():
            if not isinstance(entry, dict):
                # 非 dict 条目跳过（code-review item d392b921a012，与
                # _find_dependents / full_scan recovery 段双保险同口径）：坏条目
                # 只损失自身事件，不再中止整轮 diff 并令 watch 通道每 2s 重复失败
                continue
            new_status = entry.get("status", "drafted")
            old_status = self._known_specs.get(name)

            if old_status is None:
                # New SPEC appeared — dispatch event based on its current status
                # （add-spec-hooks D1：新 spec 进入状态同样产生 hook 事件，from=None）
                self._dispatch_hook(name, None, new_status, entry)
                event_kind = EventBus._status_to_event(new_status)
                if event_kind:
                    events.append((event_kind, name, entry))
                # 1.1：新 SPEC 以接受态初次出现（登记时即 done/pushed/...，如
                # 合并入树/存量规格）同样视为「转入接受态」，触发 dependents 重评。
                if new_status in DEPENDENCY_ACCEPTED_STATUSES:
                    accepted_names.append(name)
            elif old_status != new_status:
                # Status changed
                self._dispatch_hook(name, old_status, new_status, entry)
                event_kind = self._status_to_event(new_status)
                if event_kind:
                    events.append((event_kind, name, entry))
                # 1.1：转入依赖接受态 → 候选触发 dependents 重评
                if new_status in DEPENDENCY_ACCEPTED_STATUSES:
                    accepted_names.append(name)

        # Update known state：非 dict 条目沿用旧已知状态（无则不登记），与上方
        # 循环的跳过口径一致，避免快照重写处对坏条目二次引爆
        # （code-review item d392b921a012）
        next_known = {}
        for name, entry in current_specs.items():
            if isinstance(entry, dict):
                next_known[name] = entry.get("status", "drafted")
            elif name in self._known_specs:
                next_known[name] = self._known_specs[name]
        self._known_specs = next_known
        return events, accepted_names

    @staticmethod
    def _find_dependents(current_specs: dict, dep_name: str) -> list:
        """反查 dependents（dispatch-dependency-wakeup 1.2）。

        遍历本轮已读入的 ``current_specs`` 字典，匹配 ``depends_on`` 字段含
        ``dep_name`` 的条目（复用内存字典，无额外 IO；百量级规模不建索引）。
        非 dict 条目直接跳过。

        ``depends_on`` 的规范形态是逗号分隔的 SPEC 名列表（见
        PMEngine._dependencies_satisfied 的解析口径）；此处沿用逐名解析做
        **精确匹配**，避免「B」被「B2」子串误配。
        """
        dependents = []
        for name, entry in current_specs.items():
            if name == dep_name or not isinstance(entry, dict):
                continue
            deps = entry.get("depends_on")
            if not deps or deps == "null":
                continue
            dep_names = [d.strip() for d in str(deps).split(",") if d.strip()]
            if dep_name in dep_names:
                dependents.append(name)
        return dependents

    @staticmethod
    def _status_to_event(status: str) -> str:
        """Map a SPEC status to an internal event type."""
        mapping = {
            "drafted": "spec_drafted",
            "ready": "spec_ready",
            "implemented": "spec_implemented",
            "verified": "spec_verified",
            "bug-found": "spec_bug_found",
            "done": "spec_done",
            "reviewing": "spec_reviewing",
        }
        return mapping.get(status, "")

    def _dispatch_hook(self, spec_name: str, old_status, new_status: str, entry: dict) -> None:
        """状态 diff → hook 分发（add-spec-hooks D1）。

        与 PM Engine 事件并列的独立通道：hook 订阅任意状态（含 PM Engine
        不关心 implementing/testing/blocked/pushed 等中间态），因此每条
        old_status != new_status 都调用。未注入 hook_dispatcher 时零开销。
        hook 引擎抛异常不得影响状态机写入路径（单条捕获，只记日志）。
        """
        if self.hook_dispatcher is None:
            return
        try:
            self.hook_dispatcher(spec_name, old_status, new_status, entry)
        except Exception as e:
            self.logger.error(
                "event_bus",
                f"Hook dispatch failed for '{spec_name}' "
                f"{old_status} → {new_status}: {type(e).__name__}: {e}",
            )
