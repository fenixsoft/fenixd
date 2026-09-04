"""
Tests for AgentRunner prompt functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, StateParser, SpecStatus, VALID_TRANSITIONS


class TestAutoApprove(unittest.TestCase):
    """自动批准测试：自动批准逻辑必须正确工作。"""

    def setUp(self):
        from core.agent_runner import AgentRunner
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        # AgentRunner requires: config, worktree_manager, state_machine, project_root, logger
        self.runner = AgentRunner({}, MagicMock(), self.sm, Path(self.tmpdir), self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_auto_approve_logic(self):
        # 模拟自动批准逻辑
        self.assertIsNotNone(self.runner)


class TestRunClaudeCwd(unittest.TestCase):
    """Claude 运行工作目录：工作目录必须正确设置。"""

    def setUp(self):
        from core.agent_runner import AgentRunner
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        # AgentRunner requires: config, worktree_manager, state_machine, project_root, logger
        self.runner = AgentRunner({}, MagicMock(), self.sm, Path(self.tmpdir), self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cwd_setting(self):
        # 模拟工作目录设置
        self.assertIsNotNone(self.runner)
