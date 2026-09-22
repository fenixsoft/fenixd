"""Tests for fix-startup-double-dispatch: single-flight guard.

历史说明：本文件曾同时覆盖「state writeback protection」与「verifier
reconciliation」，但原实现仅复刻生产判定条件后回读自写状态（恒真断言），
且其代理的 implemented→testing→verified 回放已在 core/pm_engine/verification.py
被拆除（见「拆除旧 reconcile」注释）。2026-09-07 审查后裁撤该 5 条，
生产 dispatch.py 的 merge-back 状态回写保护路径待专项真覆盖补齐。
保留：单飞守卫（pending 键占位/清理/顺序放行）4 条。
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import threading
import time

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine
from core.pm_engine.engine import PMEngine, DISPATCH_COOLDOWN_SECONDS


class TestSingleFlightGuard(unittest.TestCase):
    """Test the single-flight dispatch guard to prevent duplicate dispatches."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        self.config = {"schedule": {"stuck_threshold_minutes": 60}}
        self.engine = PMEngine(self.sm, MagicMock(), self.config, self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_single_flight_guard_prevents_concurrent_dispatch(self):
        """Test that the single-flight guard prevents concurrent dispatches for the same spec."""
        # Add a spec in ready state
        self.sm.add_spec("test-spec", {"priority": 5, "status": "ready"})

        # Mock the worktree manager to allow dispatch
        self.engine.agent_runner.worktree_manager.has_active_worktree.return_value = False
        self.engine.agent_runner.has_live_attempt.return_value = False
        self.engine._dependencies_satisfied = MagicMock(return_value=True)
        self.engine._dispatch_backoffed = MagicMock(return_value=False)

        # Track enqueue calls
        enqueue_calls = []
        original_enqueue = self.engine._dispatcher._enqueue

        # Create a slow enqueue that holds the critical section until thread2
        # has actually entered, instead of racing on time.sleep ordering.
        first_entered = threading.Event()
        second_started = threading.Event()

        def slow_enqueue(spec_name, agent_type):
            enqueue_calls.append((spec_name, agent_type))
            if not first_entered.is_set():
                first_entered.set()          # thread1 已进入临界区
                second_started.wait(timeout=5)  # 等 thread2 已启动再放行
            original_enqueue(spec_name, agent_type)

        self.engine._dispatcher._enqueue = slow_enqueue

        # Start two concurrent dispatches
        results = []
        def dispatch_worker():
            self.engine._on_spec_ready("test-spec")
            results.append("done")

        thread1 = threading.Thread(target=dispatch_worker)
        thread2 = threading.Thread(target=dispatch_worker)

        thread1.start()
        self.assertTrue(first_entered.wait(timeout=5), "thread1 未进入临界区")
        thread2.start()          # 事件同步，替代 sleep(0.01) 赌先后
        second_started.set()

        thread1.join(timeout=10)
        thread2.join(timeout=10)

        # Only one dispatch should have proceeded (the first one)
        # The second should have been blocked by the single-flight guard
        # （add-verify-lane-throughput 1.1：主车道派发成功后附加一次
        # planner-plan 并行出题车道入队，不属单飞守卫管辖，过滤后断言）
        impl_calls = [c for c in enqueue_calls if c[1] != "planner-plan"]
        self.assertEqual(len(impl_calls), 1)
        self.assertEqual(len(results), 2)

    def test_single_flight_guard_allows_sequential_dispatch(self):
        """Test that sequential dispatches are allowed after the first completes."""
        self.sm.add_spec("test-spec", {"priority": 5, "status": "ready"})
        self.engine.agent_runner.worktree_manager.has_active_worktree.return_value = False
        self.engine.agent_runner.has_live_attempt.return_value = False
        self.engine._dependencies_satisfied = MagicMock(return_value=True)
        self.engine._dispatch_backoffed = MagicMock(return_value=False)

        # Mock _enqueue to track calls
        original_enqueue = self.engine._dispatcher._enqueue
        enqueue_calls = []
        def mock_enqueue(spec_name, agent_type):
            enqueue_calls.append((spec_name, agent_type))
            original_enqueue(spec_name, agent_type)
        self.engine._dispatcher._enqueue = mock_enqueue

        # First dispatch
        self.engine._on_spec_ready("test-spec")
        # （1.1 并行出题车道：ready 派发成功附加 planner-plan 入队，过滤后断言主车道）
        impl_calls = [c for c in enqueue_calls if c[1] != "planner-plan"]
        self.assertEqual(len(impl_calls), 1)

        # 冷却窗口豁免（双派发穿透原地修 2026-09-06）：成功派发后 DISPATCH_COOLDOWN_SECONDS
        # 内的顺序重复触发被冷却跳过——单飞键的「不误伤顺序派发」语义由冷却过期后
        # 放行验证（本测试把上次派发时刻拨回窗口外，回归保护单飞键本身不误伤）。
        self.engine._last_dispatch_at["test-spec"] -= (
            DISPATCH_COOLDOWN_SECONDS + 1)

        # Second dispatch (after first completes + cooldown) should be allowed
        self.engine._on_spec_ready("test-spec")
        impl_calls = [c for c in enqueue_calls if c[1] != "planner-plan"]
        self.assertEqual(len(impl_calls), 2)

    def test_single_flight_guard_cleanup_on_success(self):
        """Test that the single-flight guard cleans up after successful dispatch."""
        self.sm.add_spec("test-spec", {"priority": 5, "status": "ready"})
        self.engine.agent_runner.worktree_manager.has_active_worktree.return_value = False
        self.engine.agent_runner.has_live_attempt.return_value = False
        self.engine._dependencies_satisfied = MagicMock(return_value=True)
        self.engine._dispatch_backoffed = MagicMock(return_value=False)

        # Mock _enqueue
        self.engine._dispatcher._enqueue = MagicMock()

        # Dispatch should succeed and clean up
        self.engine._on_spec_ready("test-spec")
        # After dispatch completes, spec should not be in pending dispatches
        self.assertNotIn("test-spec", self.engine._pending_dispatches)

    def test_single_flight_guard_cleanup_on_failure(self):
        """Test that the single-flight guard cleans up even when dispatch fails."""
        self.sm.add_spec("test-spec", {"priority": 5, "status": "ready"})
        self.engine.agent_runner.worktree_manager.has_active_worktree.return_value = False
        self.engine.agent_runner.has_live_attempt.return_value = False
        self.engine._dependencies_satisfied = MagicMock(return_value=True)
        self.engine._dispatch_backoffed = MagicMock(return_value=False)

        # Mock _enqueue to raise an exception
        def failing_enqueue(spec_name, agent_type):
            raise Exception("Test error")
        self.engine._dispatcher._enqueue = failing_enqueue

        # Dispatch should fail but still clean up
        with self.assertRaises(Exception):
            self.engine._on_spec_ready("test-spec")
        self.assertNotIn("test-spec", self.engine._pending_dispatches)


if __name__ == "__main__":
    unittest.main()
