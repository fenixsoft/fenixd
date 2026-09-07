"""
Tests for PMEngine recovery functionality.

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


class TestPMEngineInfraFailureRecovery(unittest.TestCase):
    """派发基础设施失败（日限额耗尽等）不得卡死 spec、不得误判 bug-found。

    覆盖 2026-08-26 事故根因的三处框架修复：
    - 派发异常回滚 implementing/testing → 可重试态（不滞留）
    - 验证流水线双失败不得 transition bug-found（不派生伪 fix 级联）
    - blocker auto-recover 不得把从未实现的 spec 伪标 implemented
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        self.logger = MagicMock()
        from core.state_machine import StateMachine
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        # stuck 阈值由 agents.run_timeout_seconds 单源派生（config.py D1/D4，
        # 缺省回退 4200s=70min），旧键 schedule.stuck_threshold_minutes 已弃用
        # 不再生效——本组测试的 stale（2h）只要落在阈值之上即可，无需配键。
        config = {}
        self.engine = PMEngine(self.sm, MagicMock(), config, self.project_root, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stale(self, name="s1"):
        """把 spec 的 updated 改为 2 小时前（模拟卡死），须在 transition 之后调用。"""
        from datetime import datetime, timedelta, timezone
        specs = self.sm.read_all()
        specs[name]["updated"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.sm.write_all(specs)

    def test_implementer_dispatch_failure_rolls_back_to_ready(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.engine._rollback_failed_dispatch(
            "s1", "implementer", RuntimeError("Daily agent run limit (50) reached"))
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry["implementer_run"])
        self.assertIsNone(entry["error"])
        self.assertIn("dispatch failed", entry["_last_dispatch_error"])
        self.assertGreater(int(entry["_dispatch_backoff_until"]), int(time.time()))
        self.assertTrue(any((e[1], e[2]) == ("s1", "implementer") for e in self.engine._dispatcher._run_queue))

    def test_verifier_dispatch_failure_rolls_back_to_implemented(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self.engine._rollback_failed_dispatch(
            "s1", "verifier", RuntimeError("Daily agent run limit (50) reached"))
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertIsNone(entry["tester_run"])
        self.assertIn("retryable", entry["error"])
        self.assertTrue(any((e[1], e[2]) == ("s1", "verifier") for e in self.engine._dispatcher._run_queue))

    def test_rollback_ignores_status_mismatch(self):
        self.sm.add_spec("s1", {"priority": 5})  # drafted
        self.engine._rollback_failed_dispatch("s1", "implementer", RuntimeError("x"))
        self.assertEqual(self.sm.read_one("s1")["status"], "drafted")

    def test_rollback_missing_spec_is_noop(self):
        self.engine._rollback_failed_dispatch("nope", "implementer", RuntimeError("x"))

    def test_verification_infra_failure_not_bug_found(self):
        """验证两条路径都抛基础设施异常 → 回 implemented 可重试，绝不 bug-found。"""
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self.engine._run_three_stage_verification = MagicMock(
            side_effect=RuntimeError("Daily agent run limit (50) reached"))
        self.engine._run_legacy_verification = MagicMock(
            side_effect=RuntimeError("Daily agent run limit (50) reached"))
        self.engine._run_verification_pipeline("s1")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertNotIn(entry["status"], ("bug-found",))
        self.assertIn("retryable", entry["error"])

    def test_check_blockers_implementing_rolls_back_to_ready(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self._stale()
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("Auto-recovered from stuck implementing", entry["error"])
        self.assertTrue(any((e[1], e[2]) == ("s1", "implementer") for e in self.engine._dispatcher._run_queue))

    def test_check_blockers_testing_rolls_back_to_implemented(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self._stale()
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertTrue(any((e[1], e[2]) == ("s1", "verifier") for e in self.engine._dispatcher._run_queue))

    def test_check_blockers_fresh_state_not_touched(self):
        """updated 为近期的 implementing 不触发 auto-recover。"""
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.engine.check_blockers()
        self.assertEqual(self.sm.read_one("s1")["status"], "implementing")

    def test_on_spec_done_root_with_fix_prefix_reverify(self):
        """fix 链根 spec 名本身带 fix- 前缀时，fix done 后父 spec 仍正确回溯重验。

        fix-dashboard-... 的 4-fix 后代 done 后，应回溯到 fix-dashboard-...
        （bug-found → implemented），而非全剥前缀后定位到不存在的 dashboard-...
        导致永不闭环、full_scan 反复派生新 fix（2026-08-26 事故的防复发修复）。
        """
        self.sm.add_spec("fix-dashboard-duration-and-verify-gate", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing", "bug-found"):
            self.sm.transition("fix-dashboard-duration-and-verify-gate", to)
        self.sm.add_spec("fix-fix-fix-fix-dashboard-duration-and-verify-gate", {"priority": 6})
        self.sm.transition("fix-fix-fix-fix-dashboard-duration-and-verify-gate", "done")
        self.engine._on_spec_done("fix-fix-fix-fix-dashboard-duration-and-verify-gate")
        entry = self.sm.read_one("fix-dashboard-duration-and-verify-gate")
        self.assertEqual(entry["status"], "implemented")

    def test_on_spec_done_plain_root_still_works(self):
        """普通链（根不带 fix- 前缀）行为不变：improve-... 由 fix- 后代 done 回调。"""
        self.sm.add_spec("improve-agent-config-and-verify-resume", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing", "bug-found"):
            self.sm.transition("improve-agent-config-and-verify-resume", to)
        self.sm.add_spec("fix-fix-improve-agent-config-and-verify-resume", {"priority": 6})
        self.sm.transition("fix-fix-improve-agent-config-and-verify-resume", "done")
        self.engine._on_spec_done("fix-fix-improve-agent-config-and-verify-resume")
        self.assertEqual(
            self.sm.read_one("improve-agent-config-and-verify-resume")["status"],
            "implemented",
        )

    def test_dispatch_backoffed_helper(self):
        self.assertFalse(self.engine._dispatch_backoffed({}))
        self.assertFalse(self.engine._dispatch_backoffed({"status": "ready"}))
        self.assertFalse(self.engine._dispatch_backoffed(
            {"_dispatch_backoff_until": int(time.time()) - 10}))
        self.assertTrue(self.engine._dispatch_backoffed(
            {"_dispatch_backoff_until": int(time.time()) + 300}))
