"""
Tests for AgentRunner 数据结构（AgentRunResult）。

Split from test_core.py as part of refactor-test-structure.
审查清理（2026-09-07）：原 TestAgentRunnerModelRouting.test_model_routing /
TestRunClaudeStreaming.test_streaming_run 仅 assertIsNotNone(runner)（同义反复），
TestExecuteAgentAttemptRunId.test_run_id_generation 只断言本地 f-string 生成值的
前缀（未触任何源码符号），均已删除；保留对 AgentRunResult 字段契约的真实断言。
"""
import unittest


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
