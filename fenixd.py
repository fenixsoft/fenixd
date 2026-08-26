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
        # 1. Load configuration
        config_path = FENIX_DIR / "config.yaml"
        self.config = ConfigLoader.load(config_path)

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

    def start(self):
        """Start the daemon main loop."""
        self.running = True
        self.logger.info("fenixd", f"fenixd starting (PID: {os.getpid()})")

        # Scan initial state
        self.logger.info("fenixd", "Performing initial STATE.md scan...")

        # 启动清理孤儿 worktree（fix-fenix-token-waste）：上次异常退出的残留
        self.worktree_manager.cleanup_stale_worktrees()

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

        # Main loop — keep the process alive
        self.logger.info("fenixd", "Entering main loop")
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("fenixd", "Received interrupt signal")
        finally:
            self.shutdown()

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
            self.agent_runner.wait_for_running_agents(timeout=300)
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
