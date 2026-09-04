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
    (project_root / "openspec" / "changes").mkdir(parents=True, exist_ok=True)
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
