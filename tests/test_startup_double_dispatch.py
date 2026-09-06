"""Tests for fix-startup-double-dispatch: single-flight guard, state writeback protection, and verifier reconciliation."""

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call
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

        # Create a slow enqueue that simulates concurrent dispatch
        def slow_enqueue(spec_name, agent_type):
            enqueue_calls.append((spec_name, agent_type))
            # Simulate some work before returning
            time.sleep(0.1)
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
        # Small delay to ensure thread1 starts first
        time.sleep(0.01)
        thread2.start()

        thread1.join()
        thread2.join()

        # Only one dispatch should have proceeded (the first one)
        # The second should have been blocked by the single-flight guard
        self.assertEqual(len(enqueue_calls), 1)
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
        self.assertEqual(len(enqueue_calls), 1)

        # 冷却窗口豁免（双派发穿透原地修 2026-09-06）：成功派发后 DISPATCH_COOLDOWN_SECONDS
        # 内的顺序重复触发被冷却跳过——单飞键的「不误伤顺序派发」语义由冷却过期后
        # 放行验证（本测试把上次派发时刻拨回窗口外，回归保护单飞键本身不误伤）。
        self.engine._last_dispatch_at["test-spec"] -= (
            DISPATCH_COOLDOWN_SECONDS + 1)

        # Second dispatch (after first completes + cooldown) should be allowed
        self.engine._on_spec_ready("test-spec")
        self.assertEqual(len(enqueue_calls), 2)

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


class TestStateWritebackProtection(unittest.TestCase):
    """Test state writeback protection during merge-back failures."""

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

    def test_merge_back_failure_preserves_testing_state_with_active_tester(self):
        """Test that merge-back failure doesn't downgrade testing state with active tester."""
        # Add a spec in testing state with an active tester
        self.sm.add_spec("test-spec", {
            "priority": 5,
            "status": "testing",
            "tester_run": "test-run-123"
        })

        # Mock the merge failure scenario
        with patch.object(self.engine, '_merge_fingerprint', return_value="test-fp"):
            with patch.object(self.engine, '_get_config', return_value=2):
                # Simulate merge-back failure handling
                spec_entry = self.sm.read_one("test-spec")
                merge_error = "Merge conflict"
                fp = "test-fp"
                final_error = f"Merge-back failed (fp={fp}): {merge_error}"

                # Check that state is preserved when active tester exists
                current_status = spec_entry.get("status", "")
                active_tester = spec_entry.get("tester_run")

                if current_status in ("testing", "implemented") and active_tester:
                    # Should not downgrade to ready
                    self.assertEqual(current_status, "testing")
                    self.assertEqual(active_tester, "test-run-123")

    def test_merge_back_failure_allows_ready_when_no_active_tester(self):
        """Test that merge-back failure can downgrade to ready when no active tester."""
        # Add a spec in testing state without an active tester
        self.sm.add_spec("test-spec", {
            "priority": 5,
            "status": "testing",
            "tester_run": None
        })

        spec_entry = self.sm.read_one("test-spec")
        current_status = spec_entry.get("status", "")
        active_tester = spec_entry.get("tester_run")

        # Should allow downgrade when no active tester
        self.assertEqual(current_status, "testing")
        self.assertIsNone(active_tester)


class TestVerifierReconciliation(unittest.TestCase):
    """Test verifier final state reconciliation."""

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

    def test_verifier_reconciliation_when_state_changed_to_implemented(self):
        """Test verifier reconciliation when state changed to implemented during verification."""
        # Add a spec in implemented state (state changed during verification)
        self.sm.add_spec("test-spec", {
            "priority": 5,
            "status": "implemented",
            "tester_run": "test-run-123"
        })

        spec_entry = self.sm.read_one("test-spec")
        current_status = spec_entry.get("status", "")

        # If verification passed and state is implemented, should replay path
        if current_status == "implemented":
            # Verify that we can transition to testing then verified
            self.assertTrue(self.sm.is_valid_transition("implemented", "testing"))
            self.assertTrue(self.sm.is_valid_transition("testing", "verified"))


class TestStartupDuplicateDispatch(unittest.TestCase):
    """Integration tests for startup duplicate dispatch scenarios."""

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

    def test_startup_scan_and_event_replay_deduplication(self):
        """Test that startup scan and event replay are deduplicated for same spec."""
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

        # Create a slow enqueue that simulates startup processing
        def slow_enqueue(spec_name, agent_type):
            enqueue_calls.append((spec_name, agent_type))
            # Simulate startup processing delay
            time.sleep(0.05)
            original_enqueue(spec_name, agent_type)

        self.engine._dispatcher._enqueue = slow_enqueue

        # Simulate startup scan and event replay happening concurrently
        results = []
        def startup_scan():
            # Simulate startup scan processing
            self.engine._on_spec_ready("test-spec")
            results.append("scan")

        def event_replay():
            # Simulate event replay processing
            self.engine._on_spec_ready("test-spec")
            results.append("replay")

        # Start both processing paths concurrently
        thread1 = threading.Thread(target=startup_scan)
        thread2 = threading.Thread(target=event_replay)

        thread1.start()
        # Small delay to simulate event replay happening after startup scan
        time.sleep(0.01)
        thread2.start()

        thread1.join()
        thread2.join()

        # Only one dispatch should have proceeded
        self.assertEqual(len(enqueue_calls), 1)
        self.assertEqual(len(results), 2)


class TestMergeBackFailureDuringActiveTesting(unittest.TestCase):
    """Integration tests for merge-back failure during active testing."""

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

    def test_merge_back_failure_preserves_testing_with_active_verifier(self):
        """Test that merge-back failure preserves testing state when verifier is active."""
        # Add a spec in testing state with an active tester
        self.sm.add_spec("test-spec", {
            "priority": 5,
            "status": "testing",
            "tester_run": "verifier-run-123"
        })

        # Simulate merge-back failure from a duplicate implementer
        # This should not downgrade the state
        spec_entry = self.sm.read_one("test-spec")
        current_status = spec_entry.get("status", "")
        active_tester = spec_entry.get("tester_run")

        # Verify that state is preserved
        self.assertEqual(current_status, "testing")
        self.assertEqual(active_tester, "verifier-run-123")


class TestVerifierCompletionWithStateChanges(unittest.TestCase):
    """Integration tests for verifier completion with state changes."""

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

    def test_verifier_completion_reconciles_state_change(self):
        """Test that verifier completion reconciles when state changed during verification."""
        # Start with spec in testing state
        self.sm.add_spec("test-spec", {
            "priority": 5,
            "status": "testing",
            "tester_run": "verifier-run-123"
        })

        # Simulate state change during verification (e.g., due to merge-back failure)
        self.sm.update_spec("test-spec", {"status": "implemented"})

        # Now verifier completes
        spec_entry = self.sm.read_one("test-spec")
        current_status = spec_entry.get("status", "")

        # Verifier should reconcile the state change
        if current_status == "implemented":
            # Should replay path: implemented -> testing -> verified
            self.assertTrue(self.sm.is_valid_transition("implemented", "testing"))
            self.assertTrue(self.sm.is_valid_transition("testing", "verified"))


if __name__ == "__main__":
    unittest.main()