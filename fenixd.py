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
import time
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
        self.event_bus.full_scan()

        # Start event bus monitoring
        self.event_bus.start()

        # Main loop — keep the process alive
        self.logger.info("fenixd", "Entering main loop")
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("fenixd", "Received interrupt signal")
        finally:
            self.shutdown()

    def shutdown(self):
        """Graceful shutdown."""
        self.logger.info("fenixd", "Shutting down...")
        self.running = False

        if self.event_bus:
            self.event_bus.stop()
        if self.agent_runner:
            self.agent_runner.wait_for_running_agents(timeout=300)
        if self.worktree_manager:
            self.worktree_manager.cleanup_orphans()

        self.logger.info("fenixd", "fenixd stopped")
        sys.exit(0)


def main():
    """Entry point for fenixd."""
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
