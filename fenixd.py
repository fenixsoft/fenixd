#!/usr/bin/env python3
"""
fenixd — Fenix Loop Engineering Daemon
=======================================
Background daemon that orchestrates the four Fenix Agents:
  1. Requirement Agent (user-interactive, via Claude Code Skill)
  2. Implementer Agent (automatic, Ralph-mode, worktree-isolated)
  3. Verifier Agent (automatic, independent validation)
  4. PM Engine (priority, scheduling, reporting)

Architecture:
  config.yaml → ConfigLoader
       ↓
  EventBus ← inotify on STATE.md
       ↓
  PM Engine (priority + scheduling)
       ↓
  AgentRunner → claude subprocess → WorktreeManager
       ↓
  Logger ← all components
"""

import os
import sys
import signal
import threading
import time
import json
import fcntl
from pathlib import Path

# Ensure .fenix/ is on the Python path
# 使用 .absolute()（不跟随软链接）：框架文件经项目内 .fenix/ 软链接调用，
# 这样 FENIX_DIR 始终指向项目内的 .fenix/，而非框架真实安装目录。
FENIX_DIR = Path(__file__).absolute().parent
PROJECT_ROOT = FENIX_DIR.parent
sys.path.insert(0, str(FENIX_DIR))

from core.config import ConfigLoader
from core.logger import Logger
from core.state_machine import StateMachine
from core.event_bus import EventBus
from core.worktree_manager import WorktreeManager
from core.agent_runner import AgentRunner
from core.v2_dev_server import cleanup_orphans as v2_cleanup_orphans
from core.admin_store import AdminStore
from core.admin_monitor import AdminMonitor
from core.pm_engine import PMEngine


class FenixDaemon:
    """Main daemon process for the Fenix Loop Engineering Framework."""

    def __init__(self):
        self.running = False
        self.config = None
        self.logger = None
        self.state_machine = None
        self.event_bus = None
        self.worktree_manager = None
        self.agent_runner = None
        self.admin_store = None
        self.admin_monitor = None
        self._admin_thread = None
        self.pm_engine = None

    def initialize(self):
        """Load config and initialize all components."""
        # 1. Load configuration（有效配置：用户级 ~/.fenix/config.yaml + 项目级
        #    .fenix/config.yaml 深合并；任一或全部缺失都允许，内置默认兜底）
        self.config = ConfigLoader.resolve_config(PROJECT_ROOT)

        # 2. Initialize logger
        log_dir = PROJECT_ROOT / self.config.get("logging.dir", ".fenix/logs")
        log_level = self.config.get("logging.level", "INFO")
        self.logger = Logger(log_dir, log_level)
        self.logger.info("fenixd", "Initializing Fenix Loop Engineering Framework...")

        # 3. Initialize StateMachine
        state_path = PROJECT_ROOT / "STATE.md"
        self.state_machine = StateMachine(state_path, self.logger)
        self.logger.info("fenixd", "StateMachine initialized")

        # 4. Initialize WorktreeManager
        wt_base = PROJECT_ROOT / self.config.get("worktree.base_dir", ".claude/worktrees")
        self.worktree_manager = WorktreeManager(wt_base, PROJECT_ROOT, self.logger)
        self.logger.info("fenixd", "WorktreeManager initialized")

        # 5. Initialize AgentRunner
        self.agent_runner = AgentRunner(
            self.config,
            self.worktree_manager,
            self.state_machine,
            PROJECT_ROOT,
            self.logger,
        )
        self.logger.info("fenixd", "AgentRunner initialized")

        # 5.5. Initialize AdminStore + AdminMonitor（零成本健康监视 + 困境唤起）
        self.admin_store = AdminStore(PROJECT_ROOT, self.logger)
        self.admin_monitor = AdminMonitor(
            self.config,
            self.state_machine,
            PROJECT_ROOT,
            self.logger,
            store=self.admin_store,
            agent_runner=self.agent_runner,
        )
        if self.admin_monitor.enabled:
            self.logger.info(
                "fenixd",
                "AdminMonitor initialized "
                f"(interval: {self.admin_monitor.interval_minutes}m, "
                f"cooldown: {self.admin_monitor.cooldown_minutes}m)",
            )
        else:
            self.logger.info("fenixd", "AdminMonitor disabled (admin.enabled: false)")

        # 6. Initialize PMEngine
        self.pm_engine = PMEngine(
            self.state_machine,
            self.agent_runner,
            self.config,
            PROJECT_ROOT,
            self.logger,
        )
        self.logger.info("fenixd", "PMEngine initialized")

        # 7. Initialize EventBus (last, as it triggers the PM Engine)
        self.event_bus = EventBus(
            state_path,
            self.state_machine,
            self.pm_engine,
            self.config,
            self.logger,
        )
        self.logger.info("fenixd", "EventBus initialized")

        self.logger.info("fenixd", "All components initialized successfully")

        # 记录启动时配置文件 mtime，供主循环热更新检测基线
        self._config_snapshot = self._config_mtimes()

    def start(self):
        """Start the daemon main loop."""
        self.running = True
        self.logger.info("fenixd", f"fenixd starting (PID: {os.getpid()})")

        # Scan initial state
        self.logger.info("fenixd", "Performing initial STATE.md scan...")

        # 启动清理孤儿 worktree（fix-fenix-token-waste）：上次异常退出的残留。
        # 锁治理（improve-run-lifecycle-governance D4）：清理前先以进程表重建在册锁
        # —— 孤儿 attempt 进程仍存活的 worktree 会被跳过并重建登记，不被误删。
        self.worktree_manager.refresh_locks()
        self.worktree_manager.cleanup_stale_worktrees()

        # add-worktree-test-server（D2 启动清扫）：上次异常退出遗留的 dev-server 进程
        # 在 daemon 重启时早已失活（worktree 已清），需按命令行标记回收端口。
        v2_cleanup_orphans(self.logger)

        # 恢复上次异常退出遗留的中断状态（implementing/testing → ready）。
        # recover_interrupted 此前定义了但从未被调用，导致 daemon 重启后卡死的
        # spec 永远不被重新调度（fix-fenix-token-waste）。
        self.state_machine.recover_interrupted()

        self.event_bus.full_scan()

        # Start event bus monitoring
        self.event_bus.start()

        # 启动 Administrator 监视线程（admin.enabled 时；间隔见 admin.interval_minutes）
        if self.admin_monitor and self.admin_monitor.enabled:
            self._admin_thread = threading.Thread(
                target=self._admin_monitor_loop,
                name="fenixd-admin-monitor",
                daemon=True,
            )
            self._admin_thread.start()
            self.logger.info("fenixd", "Admin monitor thread started")

        # Main loop — keep the process alive + 配置热更新轮询
        self.logger.info("fenixd", "Entering main loop")
        config_check_ts = time.time()
        recovery_watch_ts = time.time()
        try:
            while self.running:
                time.sleep(1)
                # 手动唤起 Admin 文件信号拾取（add-spec-manual-admin-invoke）：
                # dashboard 写入 .fenix/admin_invoke_request.json，主循环下一轮
                # （≤2s）扫描并立即唤起 Administrator，处理完即删。
                try:
                    self._check_admin_invoke_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"admin_invoke pickup failed: {e}")
                # 配置热更新：每 30s 检查配置文件 mtime，变更则原地重载
                if time.time() - config_check_ts >= 30:
                    config_check_ts = time.time()
                    try:
                        self._maybe_reload_config()
                    except Exception as e:
                        self.logger.error("fenixd", f"Config hot-reload failed: {e}")
                # 恢复闭环复查（improve-run-lifecycle-governance D6）：每分钟检查
                # 到期的观察项——followup 窗口（默认 15m）短于全量扫描间隔，
                # 不能只依赖 event_bus 的 full_scan 触发。
                if time.time() - recovery_watch_ts >= 60:
                    recovery_watch_ts = time.time()
                    try:
                        self.pm_engine.check_recovery_watch()
                    except Exception as e:
                        self.logger.error(
                            "fenixd", f"Recovery watch check failed: {e}")
        except KeyboardInterrupt:
            self.logger.info("fenixd", "Received interrupt signal")
        finally:
            self.shutdown()

    def _config_mtimes(self):
        """两个配置文件的当前 mtime（不存在计为 None）。"""
        from core.config import USER_CONFIG_DIR
        mtimes = []
        for p in (USER_CONFIG_DIR / "config.yaml", PROJECT_ROOT / ".fenix" / "config.yaml"):
            try:
                mtimes.append(p.stat().st_mtime_ns)
            except OSError:
                mtimes.append(None)
        return tuple(mtimes)

    def _maybe_reload_config(self):
        """配置文件 mtime 变化时热加载：原地更新共享 config dict，组件自动看到新值。

        校验失败保留旧值并告警；成功则刷新 admin_cfg 快照。
        """
        current = self._config_mtimes()
        if current == getattr(self, "_config_snapshot", None):
            return
        ConfigLoader.resolve_config_into(self.config, PROJECT_ROOT)
        # admin_monitor 的 admin_cfg 是启动快照，同步刷新
        if self.admin_monitor is not None:
            from core.config import ConfigLoader as _CL
            self.admin_monitor.admin_cfg = _CL.get_admin_config(self.config)
        self._config_snapshot = current
        self.logger.info(
            "fenixd",
            "Configuration hot-reloaded (user/project config.yaml changed)",
        )

    def _admin_monitor_loop(self):
        """周期运行健康检查（间隔 admin.interval_minutes）。"""
        interval = max(float(self.admin_monitor.interval_minutes), 0.5)
        while self.running:
            time.sleep(interval * 60)
            if not self.running:
                break
            try:
                self.admin_monitor.run_once()
            except Exception as e:
                self.logger.error("admin_monitor", f"Admin monitor check failed: {e}")

    def _check_admin_invoke_requests(self):
        """主循环每轮扫描手动唤起 Admin 的文件信号并立即唤起 Administrator。

        dashboard 的 /api/spec-admin-invoke 会原子写入
        .fenix/admin_invoke_request.json（含 spec/source/created）；本方法在
        主循环（1s 粒度）中检测其存在：读取→删除→构造 manual-intervention 信号
        调 agent_runner.run_administrator。与 admin_monitor 自动检测共存：二者
        各自走 store 记录与节流锚点，互不吞并。

        调用异常时不丢痕——写一条 failed disposition 到 admin_store 记录原因，
        供前端时间线/告警可见，且请求文件已删避免反复重试。
        """
        req_path = PROJECT_ROOT / ".fenix" / "admin_invoke_request.json"
        if not req_path.exists():
            return
        try:
            with req_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # 损坏的信号文件：删除避免每轮报错卡死
            try:
                req_path.unlink()
            except OSError:
                pass
            return
        # 先读后删：删除失败（被并发消费）则本次跳过，下一轮再试
        try:
            req_path.unlink()
        except OSError:
            return

        spec = payload.get("spec")
        if not spec:
            self.logger.warning("fenixd", "admin_invoke 请求缺少 spec，忽略")
            return

        signal = {
            "signal_type": "manual-intervention",
            "spec": spec,
            "severity": "major",
            "source": payload.get("source", "manual"),
            "created": payload.get("created"),
            "description": f"人工呼叫：检查 SPEC {spec} 出现什么问题并尝试处置",
        }
        self.logger.info(
            "fenixd",
            f"手动唤起 Administrator 处置 SPEC {spec}（manual-intervention）",
        )
        # fix-manual-admin-disposition-finalize：走 AdminMonitor 公共入口而非直接调
        # run_administrator——后者开头落的 pending disposition 需要在返回后由
        # _invoke_administrator 落最终记录终结。此前这里丢弃返回值，pending 永无
        # 终态、处置叙述从不入告警时间线，dashboard 显示「处置中」致用户反复重呼。
        try:
            if self.admin_monitor is not None:
                self.admin_monitor.invoke_manual(signal)
            else:
                self.agent_runner.run_administrator(signal)
        except Exception as e:
            self.logger.error(
                "fenixd",
                f"手动唤起 Administrator 失败（SPEC {spec}）：{e}",
            )
            # 不丢痕：写 failed disposition 记录，供 admin 活动区/告警可见
            try:
                from core.admin_store import DISPOSITION
                self.admin_store.append({
                    "kind": DISPOSITION,
                    "status": "failed",
                    "signal_type": "manual-intervention",
                    "spec": spec,
                    "admin_run_id": None,
                    "description": f"手动唤起 Administrator 处理 SPEC {spec} 时出错：{e}",
                    "result": "failed",
                })
            except Exception:
                pass

    def shutdown(self):
        """Graceful shutdown."""
        self.logger.info("fenixd", "Shutting down...")
        self.running = False

        # 关闭期间禁止派发新 agent（fix-admin-self-heal）：
        # 否则 wait_for_running_agents 等待期间 dispatcher 持续起新 agent，
        # 造成「杀一个又起一个」的关闭死循环
        if self.pm_engine:
            self.pm_engine.shutting_down = True

        if self._admin_thread:
            self._admin_thread.join(timeout=5)
        if self.event_bus:
            self.event_bus.stop()
        if self.agent_runner:
            # fix-graceful-shutdown-agents：wait_for_running_agents 已改为 terminate 流程
            # （SIGTERM→interrupted 标记→≤10s 缓冲→SIGKILL），默认 grace 窗口即收口，
            # 不传 timeout 以沿用 AGENT_TERMINATE_GRACE_SECONDS，确保总关停 ≪ supervisor 60s
            self.agent_runner.wait_for_running_agents()
            # add-worktree-test-server（D2 关闭回收）：agent 收尾后回收全部在册 dev-server，
            # 释放端口，避免遗留进程占用。
            try:
                self.agent_runner._v2_stop_all()
            except Exception as e:
                self.logger.error("fenixd", f"V2 dev-server cleanup on shutdown failed: {e}")
        if self.worktree_manager:
            self.worktree_manager.cleanup_orphans()

        self.logger.info("fenixd", "fenixd stopped")
        sys.exit(0)


# 单实例锁：fd 保持全局引用，进程生命周期内持有，退出时 OS 自动释放
_LOCK_FD = None


def _acquire_singleton_lock() -> None:
    """获取 daemon 单实例 flock 排他锁（fix-fenix-token-waste）。

    同一项目重复启动第二个实例时打印提示并立即退出（非零码），
    防止双 daemon 并发读取 STATE.md 造成双派发。
    """
    global _LOCK_FD
    lock_path = FENIX_DIR / "daemon.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        print(
            f"Fenixd 已在运行（单实例锁被持有: {lock_path}），本实例退出",
            file=sys.stderr,
        )
        sys.exit(1)
    _LOCK_FD = fd


def main():
    """Entry point for fenixd."""
    _acquire_singleton_lock()
    daemon = FenixDaemon()

    # Register signal handlers
    signal.signal(signal.SIGTERM, lambda s, f: daemon.shutdown())
    signal.signal(signal.SIGINT, lambda s, f: daemon.shutdown())

    try:
        daemon.initialize()
        daemon.start()
    except Exception as e:
        print(f"FATAL: Failed to start fenixd: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
