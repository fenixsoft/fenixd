"""
Shared test helpers and fixtures for Fenix test suite.

This module contains shared utilities, fixtures, and helper functions
used across multiple test modules.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock


class _FakeProc:
    """Fake process for testing subprocess calls."""
    
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
    
    def communicate(self):
        return (self.stdout, self.stderr)
    
    def poll(self):
        return self.returncode


class _FakeHub:
    """Fake hub for testing dashboard server."""
    
    def __init__(self):
        self.connections = []
    
    def connect(self, sid):
        self.connections.append(sid)
    
    def disconnect(self, sid):
        self.connections = [c for c in self.connections if c != sid]


def create_temp_project(tmpdir=None):
    """Create a temporary project directory with basic structure."""
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp()
    
    project_root = Path(tmpdir)
    
    # Create basic directory structure
    (project_root / "spec" / "changes").mkdir(parents=True, exist_ok=True)
    (project_root / "core").mkdir(parents=True, exist_ok=True)
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    
    # Create STATE.md (in .fenix/ subdirectory)
    state_path = project_root / ".fenix" / "STATE.md"
    state_path.write_text("# Fenix Project State\n## Specs\n", encoding="utf-8")
    
    return project_root


def create_test_spec(project_root, spec_name, status="ready", priority=1):
    """Create a test spec in the project."""
    from core.state_machine import StateMachine
    
    state_path = project_root / ".fenix" / "STATE.md"
    logger = MagicMock()
    sm = StateMachine(state_path, logger)
    
    sm.add_spec(spec_name, {"priority": priority, "status": status})
    return sm


def cleanup_temp_dir(tmpdir):
    """Safely cleanup a temporary directory."""
    if tmpdir and os.path.exists(tmpdir):
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── 逐字节相同助手收编（审查报告第 4 项）──────────────────────────
# 仅收编各测试文件间逐字节相同、且无模块级 logger 语义绑定的副本；
# 语义有微差的（如 test_provider_failover 的记录型 FakeLogger / 本地 make_runner）
# 保留在原文件。

class FakeLogger:
    """四方法静默 logger（test_admin / test_agent_runner / test_cost_observability /
    test_provider_circuit 四处原逐字节相同副本）。"""

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_runner(proot: Path, config: dict | None = None):
    """构造最小 AgentRunner 实例（绕过真实 __init__ 的 worktree/state_machine 依赖）。

    自 test_provider_circuit.py / test_provider_failover.py 的同名助手收编；
    两者函数体逐字节相同，但原实现绑定各自模块级 FakeLogger——failover 版为
    记录型 logger（其断言依赖 logger.records），语义有微差，保留在原文件。
    """
    from core.agent_runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._daily_reset_date = None
    runner._daily_provider_attempts = {}
    runner._daily_provider_warned = {}
    runner.provider_circuits = {}
    return runner


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def iso_ago(minutes: float) -> str:
    return datetime.fromtimestamp(time.time() - minutes * 60, tz=timezone.utc).isoformat()
