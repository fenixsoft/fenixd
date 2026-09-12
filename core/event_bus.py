"""
event_bus.py — File-system event monitoring for fenixd.

Watches STATE.md for changes using inotify (Linux) and dispatches
internal events to the PM Engine. Includes periodic full-scan fallback.
"""

import hashlib
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Set


class EventBus:
    """
    Monitor STATE.md for changes and dispatch events to PM Engine.

    Uses polling + checksum comparison for cross-platform compatibility
    (with optional inotify support on Linux).
    """

    def __init__(self, state_path: Path, state_machine, pm_engine, config, logger,
                 hook_dispatcher=None):
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
        self._last_checksum = None
        self._known_specs: Dict[str, str] = {}  # spec_name → status (last known)

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
        poll_interval = self.config.get("schedule", {}).get("poll_interval_minutes", 30)
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
        self.logger.info("event_bus", "Stopped")

    def full_scan(self):
        """Perform a complete scan of STATE.md, dispatch events, and run blocker check.
        Also recovers actionable states that may have been missed on daemon restart.

        韧性（fix-dispatch-orphan D3/D4）：单条 SPEC 的处理异常只跳过该条并记日志，
        不中止整轮扫描；扫描末尾输出 handled/failed 统计。
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

    def _recover_one(self, name: str, entry: dict) -> bool:
        """对单个 SPEC 执行 recovery 动作；返回 True 表示处理成功（含有意跳过）。

        单条异常在此捕获并记 error（含 spec 名），调用方据此计入 failed 统计，
        但不中止整轮扫描。
        """
        try:
            status = entry.get("status", "")
            if status == "drafted":
                self.logger.info("event_bus", f"Recovery: re-triggering promote for '{name}'")
                self.pm_engine.handle_event("spec_drafted", name, entry)
            elif status == "implemented":
                # Skip if already had a tester run (already verified, avoid re-trigger loop)
                if entry.get("tester_run"):
                    self.logger.debug("event_bus", f"Skipping recovery for '{name}': already verified")
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

    def _recover_ready(self, name: str, entry: dict):
        """recovery 的 ready 分支（fix-dispatch-orphan D4 白名单）。

        存活判定（有存活 agent 子进程 / 未超时活跃 worktree 锁）由
        ``_ready_has_live_child`` 给出；存活则跳过并记「skip: live child present」，
        不重置状态、不清字段；否则重新派发前清 error、保留 implementer_run。
        """
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
        updated = {k: v for k, v in entry.items() if k != "error"}
        updated["error"] = None
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

    def _ready_has_live_child(self, spec_name: str) -> bool:
        """判定 SPEC 是否仍有存活的 agent 子进程（D4 白名单存活依据）。

        接口选型（fix-dispatch-orphan 5.1）：优先复用姊妹变更
        improve-run-lifecycle-governance 落地的 ``agent_runner.has_live_attempt(spec)``；
        该接口当前尚未合入（core/agent_runner.py 中不存在），按 design D4 兜底实现：
        pgrep 匹配 ``.claude/worktrees/{impl,verify}-<spec>-*`` 的 claude 进程 +
        STATE.md 中 implementer_run 指向的最新 run 文件 mtime < 120s。

        不重复造锁机制（锁归姊妹变更）；此处仅做「进程表 + run 文件 mtime」的
        轻量存活探测，与姊妹变更语义一致即满足白名单需求。
        """
        # 1) 优先：若姊妹变更已落地 has_live_attempt，直接复用
        agent_runner = getattr(self.pm_engine, "agent_runner", None)
        if agent_runner is not None and hasattr(agent_runner, "has_live_attempt"):
            try:
                if agent_runner.has_live_attempt(spec_name):
                    return True
            except Exception:
                pass

        # 2) 兜底：pgrep 匹配 worktree 下的 claude 进程
        if self._pgrep_live_worktree(spec_name):
            return True

        # 3) 兜底：implementer_run 指向的最新 run 文件 mtime < 120s（视为活跃）
        run_file = self._latest_impl_run_file(spec_name)
        if run_file is not None and self._run_file_recent(run_file, 120):
            return True

        return False

    @staticmethod
    def _pgrep_live_worktree(spec_name: str) -> bool:
        """pgrep 匹配 ``.claude/worktrees/{impl,verify}-<spec>-*`` 的 claude 进程。"""
        try:
            for prefix in ("impl", "verify"):
                pattern = f"{prefix}-{spec_name}-"
                res = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True, text=True, timeout=5,
                )
                if res.returncode == 0 and res.stdout.strip():
                    return True
        except (subprocess.SubprocessError, OSError):
            return False
        return False

    def _latest_impl_run_file(self, spec_name: str) -> Optional[Path]:
        """STATE.md implementer_run 指向的最新 run 文件（复用 dashboard 解析）。"""
        try:
            from core.dashboard.data import find_impl_run_file
            project_root = getattr(self.pm_engine, "project_root", None)
            if project_root is None:
                return None
            return find_impl_run_file(Path(project_root), spec_name)
        except Exception:
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
        """Poll STATE.md for changes using checksum comparison."""
        while self._running:
            try:
                if not self.state_path.exists():
                    time.sleep(2)
                    continue

                current_hash = self._file_checksum()
                if current_hash != self._last_checksum:
                    self._last_checksum = current_hash
                    self.logger.debug("event_bus", "STATE.md changed, dispatching...")
                    current_specs = self.state_machine.read_all()
                    self._dispatch_changes(current_specs)
            except Exception as e:
                self.logger.error("event_bus", f"Watch error: {e}")

            time.sleep(2)  # Poll every 2 seconds

    def _periodic_scan_loop(self, interval_minutes: int):
        """Periodic full scan as fallback. 每轮热读 poll_interval（配置热更新生效）。"""
        while self._running:
            try:
                interval = float(
                    self.config.get("schedule", {}).get("poll_interval_minutes", interval_minutes)
                )
            except (TypeError, ValueError):
                interval = interval_minutes
            time.sleep(max(interval, 0.5) * 60)
            if self._running:
                self.logger.debug("event_bus", "Periodic scan triggered")
                # ── 运行期悬空 run 清扫（add-runtime-run-sweeper 3.1/3.2）──
                # 每轮 full_scan() **前**调用：先扫后 scan，让当轮 full_scan
                # 消费最新终态事实。经既有 pm_engine → agent_runner 引用，
                # 无新增构造参数。异常降级 WARNING 不阻断当轮扫描。
                try:
                    self.pm_engine.agent_runner.sweep_dangling_runs()
                except Exception as e:
                    self.logger.warning(
                        "event_bus",
                        f"Runtime dangling-run sweep failed (scan continues): "
                        f"{type(e).__name__}: {e}",
                    )
                self.full_scan()

    def _file_checksum(self) -> str:
        """Compute MD5 checksum of STATE.md."""
        if not self.state_path.exists():
            return ""
        try:
            content = self.state_path.read_bytes()
            return hashlib.md5(content).hexdigest()
        except Exception:
            return ""

    def _update_known_state(self):
        """Update internal snapshot of known SPEC states."""
        specs = self.state_machine.read_all()
        self._known_specs = {
            name: entry.get("status", "drafted")
            for name, entry in specs.items()
        }

    def _dispatch_changes(self, current_specs: dict):
        """Compare current state against known state and dispatch events."""
        events = []

        # Check for new or changed SPECs
        for name, entry in current_specs.items():
            new_status = entry.get("status", "drafted")
            old_status = self._known_specs.get(name)

            if old_status is None:
                # New SPEC appeared — dispatch event based on its current status
                # （add-spec-hooks D1：新 spec 进入状态同样产生 hook 事件，from=None）
                self._dispatch_hook(name, None, new_status, entry)
                event_kind = EventBus._status_to_event(new_status)
                if event_kind:
                    events.append((event_kind, name, entry))
            elif old_status != new_status:
                # Status changed
                self._dispatch_hook(name, old_status, new_status, entry)
                event_kind = self._status_to_event(new_status)
                if event_kind:
                    events.append((event_kind, name, entry))

        # Update known state
        self._known_specs = {
            name: entry.get("status", "drafted")
            for name, entry in current_specs.items()
        }

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
        }
        return mapping.get(status, "")

    def _dispatch_hook(self, spec_name: str, old_status, new_status: str,
                       entry: dict) -> None:
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
