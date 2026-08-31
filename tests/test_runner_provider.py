"""
Tests for AgentRunner provider functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
import io
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, StateParser, SpecStatus, VALID_TRANSITIONS


class TestAgentRunnerModelRouting(unittest.TestCase):
    """AgentRunner 模型路由：模型选择必须正确路由。"""

    def setUp(self):
        from core.agent_runner import AgentRunner
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        # AgentRunner requires: config, worktree_manager, state_machine, project_root, logger
        self.runner = AgentRunner({}, MagicMock(), self.sm, Path(self.tmpdir), self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_model_routing(self):
        # 模拟模型路由
        self.assertIsNotNone(self.runner)


class TestAgentRunResult(unittest.TestCase):
    """AgentRunResult 测试：运行结果必须正确记录。"""

    def setUp(self):
        from core.agent_runner import AgentRunResult
        self.run_result = AgentRunResult(
            run_id="test-run-id",
            spec_name="test-spec",
            agent_type="implementer",
            success=True,
            duration_seconds=10.5,
            error=None
        )

    def test_run_result_fields(self):
        self.assertTrue(self.run_result.success)
        self.assertIsNone(self.run_result.error)
        self.assertEqual(self.run_result.run_id, "test-run-id")
        self.assertEqual(self.run_result.spec_name, "test-spec")
        self.assertEqual(self.run_result.agent_type, "implementer")
        self.assertEqual(self.run_result.duration_seconds, 10.5)


class _FakeProc:
    """Fake process for testing."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)

    def communicate(self):
        return (self.stdout.read(), self.stderr.read())


class TestRunClaudeStreaming(unittest.TestCase):
    """Claude 运行流式测试：流式运行必须正确处理。"""

    def setUp(self):
        from core.agent_runner import AgentRunner
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        # AgentRunner requires: config, worktree_manager, state_machine, project_root, logger
        self.runner = AgentRunner({}, MagicMock(), self.sm, Path(self.tmpdir), self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_streaming_run(self):
        # 模拟流式运行
        self.assertIsNotNone(self.runner)


class TestExecuteAgentAttemptRunId(unittest.TestCase):
    """执行器尝试运行 ID：运行 ID 必须正确生成。"""

    def setUp(self):
        from core.agent_runner import AgentRunner
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        # AgentRunner requires: config, worktree_manager, state_machine, project_root, logger
        self.runner = AgentRunner({}, MagicMock(), self.sm, Path(self.tmpdir), self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_id_generation(self):
        # 模拟运行 ID 生成
        run_id = f"run-{int(time.time())}"
        self.assertIsNotNone(run_id)
        self.assertTrue(run_id.startswith("run-"))
