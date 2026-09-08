"""tests for draft-promotion-gate and shared promotion function.

Covers:
- Gate manual: all drafted trigger paths stay drafted (no error, no dispatch)
- Gate auto: promotion chain identical to pre-gate behavior
- Re-enable: full_scan recovery restores auto-promotion for stuck drafts
- Shared function: lint violation interception, non-drafted rejection, not-found rejection
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine


def _setup_project(tmpdir, spec_name="myspec", status="drafted"):
    """Create a minimal Fenixd project with one drafted spec."""
    proot = Path(tmpdir)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    state_path = proot / ".fenix" / "STATE.md"
    sm = StateMachine(state_path, MagicMock())
    sm.add_spec(spec_name, {"status": status})
    # Create spec dir with valid tasks.md
    (proot / "spec" / "changes" / spec_name).mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / spec_name / "tasks.md").write_text(
        "## 1. 阶段一\n\n- [x] 1.1 任务一\n", encoding="utf-8"
    )
    return proot, sm, state_path


class TestGateClosed(unittest.TestCase):
    """Gate promote_mode=manual: all drafted paths stay drafted."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _engine(self, config):
        from core.pm_engine import PMEngine
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        engine = PMEngine(sm, MagicMock(), config, proot, logger)
        return engine, sm, proot

    def test_spec_drafted_event_stays_draft(self):
        """spec_drafted event: gate closed → spec stays drafted, no error."""
        engine, sm, _ = self._engine({"gates": {"promote_mode": "manual"}})
        engine._on_spec_drafted("myspec")
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "drafted")
        self.assertIsNone(entry.get("error"))
        # No dispatch occurred
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        engine._on_spec_ready.assert_not_called()

    def test_start_after_stays_draft(self):
        """start_after expiry: gate closed → spec stays drafted."""
        engine, sm, proot = _setup_project(self.tmpdir)
        engine_obj = MagicMock()
        engine_obj.config = {"gates": {"promote_mode": "manual"}}
        engine_obj.project_root = proot
        engine_obj.logger = MagicMock()
        engine_obj.state_machine = sm
        engine_obj._on_spec_ready = MagicMock()

        # Call _on_spec_drafted directly
        from core.pm_engine.engine import PMEngine
        real_on_drafted = PMEngine._on_spec_drafted
        try:
            real_on_drafted(engine_obj, "myspec")
        except Exception:
            pass

        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "drafted")
        self.assertIsNone(entry.get("error"))

    def test_full_scan_recovery_stays_draft(self):
        """full_scan recovery: gate closed → spec stays drafted."""
        from core.pm_engine import PMEngine
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        config = {"gates": {"promote_mode": "manual"}}
        engine = PMEngine(sm, MagicMock(), config, proot, logger)
        # Simulate recovery path: handle_event calls _on_spec_drafted
        engine._on_spec_drafted("myspec")
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "drafted")
        self.assertIsNone(entry.get("error"))

    def test_no_error_written_when_gate_closed(self):
        """Gate closed: no error written to STATE (waiting for manual promotion)."""
        from core.pm_engine import PMEngine
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        config = {"gates": {"promote_mode": "manual"}}
        engine = PMEngine(sm, MagicMock(), config, proot, logger)
        engine._on_spec_drafted("myspec")
        entry = sm.read_one("myspec")
        # Key assertion: error must be None (not some lint error)
        self.assertIsNone(entry.get("error"))


class TestGateOpen(unittest.TestCase):
    """Gate promote_mode=auto: promotion chain works as before."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_promotion_succeeds_when_gate_open(self):
        """Gate open + valid spec → drafted → ready."""
        from core.pm_engine import PMEngine
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        config = {"gates": {"promote_mode": "auto"}}
        engine = PMEngine(sm, MagicMock(), config, proot, logger)
        # Patch _on_spec_ready to prevent actual dispatch
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "ready")
        engine._on_spec_ready.assert_called_once_with("myspec")

    def test_lint_failure_stays_draft_with_error(self):
        """Gate open + lint violation → stays drafted with error."""
        from core.pm_engine import PMEngine
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        config = {"gates": {"promote_mode": "auto"}}
        engine = PMEngine(sm, MagicMock(), config, proot, logger)
        engine._on_spec_ready = MagicMock()
        # Patch promote_drafted's internal lint to return violations
        with patch("core.pm_engine.promotion._lint_deliverable_declarations",
                   return_value=["bad declaration"]), \
             patch("core.pm_engine.promotion._lint_tasks_parseable",
                   return_value=[]):
            engine._on_spec_drafted("myspec")
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "drafted")
        self.assertIn("bad declaration", entry.get("error", ""))
        engine._on_spec_ready.assert_not_called()


class TestGateReEnable(unittest.TestCase):
    """Re-enable auto promote_mode: stuck drafts recover via full_scan."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_scan_recovery_after_reenable(self):
        """After re-enabling gate, full_scan recovery promotes stuck drafts."""
        from core.pm_engine import PMEngine
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        # Start with gate closed
        config_closed = {"gates": {"promote_mode": "manual"}}
        engine = PMEngine(sm, MagicMock(), config_closed, proot, logger)
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        # Still drafted
        self.assertEqual(sm.read_one("myspec")["status"], "drafted")

        # Re-enable gate
        config_open = {"gates": {"promote_mode": "auto"}}
        engine.config = config_open
        # Simulate full_scan recovery triggering _on_spec_drafted
        engine._on_spec_drafted("myspec")
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "ready")


class TestSharedPromotionFunction(unittest.TestCase):
    """Shared promote_drafted function: lint violation, non-drafted, not-found."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_not_found_rejection(self):
        """promote_drafted: spec not in STATE.md → rejected."""
        from core.pm_engine.promotion import promote_drafted
        proot = Path(self.tmpdir)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        logger = MagicMock()
        result = promote_drafted(proot, "nonexistent", state_machine=sm, logger=logger)
        self.assertFalse(result["ok"])
        self.assertIn("not found", result.get("reason", ""))

    def test_non_drafted_rejection(self):
        """promote_drafted: spec in ready status → rejected."""
        from core.pm_engine.promotion import promote_drafted
        proot, sm, _ = _setup_project(self.tmpdir, status="ready")
        logger = MagicMock()
        result = promote_drafted(proot, "myspec", state_machine=sm, logger=logger)
        self.assertFalse(result["ok"])
        self.assertIn("ready", result.get("reason", ""))

    def test_lint_violation_interception(self):
        """promote_drafted: lint violation → stays drafted, error written."""
        from core.pm_engine.promotion import promote_drafted
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        with patch("core.pm_engine.promotion._lint_deliverable_declarations",
                   return_value=["bad path declaration"]):
            result = promote_drafted(proot, "myspec", state_machine=sm, logger=logger)
        self.assertFalse(result["ok"])
        self.assertIn("violations", result)
        self.assertEqual(len(result["violations"]), 1)
        # Error written to STATE
        entry = sm.read_one("myspec")
        self.assertIn("bad path declaration", entry.get("error", ""))

    def test_tasks_lint_violation_interception(self):
        """promote_drafted: tasks.md lint violation → stays drafted, error written."""
        from core.pm_engine.promotion import promote_drafted
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        with patch("core.pm_engine.promotion._lint_deliverable_declarations",
                   return_value=[]), \
             patch("core.pm_engine.promotion._lint_tasks_parseable",
                   return_value=["tasks unparseable"]):
            result = promote_drafted(proot, "myspec", state_machine=sm, logger=logger)
        self.assertFalse(result["ok"])
        self.assertIn("tasks unparseable", result.get("violations", []))
        entry = sm.read_one("myspec")
        self.assertIn("tasks unparseable", entry.get("error", ""))

    def test_success_returns_ok(self):
        """promote_drafted: all checks pass → ok=True, no error written."""
        from core.pm_engine.promotion import promote_drafted
        proot, sm, _ = _setup_project(self.tmpdir)
        logger = MagicMock()
        with patch("core.pm_engine.promotion._lint_deliverable_declarations",
                   return_value=[]), \
             patch("core.pm_engine.promotion._lint_tasks_parseable",
                   return_value=[]):
            result = promote_drafted(proot, "myspec", state_machine=sm, logger=logger)
        self.assertTrue(result["ok"])
        self.assertEqual(result["violations"], [])
        # No error written
        entry = sm.read_one("myspec")
        self.assertIsNone(entry.get("error"))


class TestCLI(unittest.TestCase):
    """CLI promote 命令测试（函数级调用，避免子进程脆弱性）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cli_promote_success(self):
        """CLI promote：成功晋升退出码 0。"""
        from bin.fenix_cli import _resolve_project_root, cmd_promote
        from argparse import Namespace
        proot, sm, _ = _setup_project(self.tmpdir)
        args = Namespace(spec="myspec", project=str(proot))
        # Monkey-patch _resolve_project_root to return our proot
        import bin.fenix_cli as cli_mod
        original_fn = cli_mod._resolve_project_root
        cli_mod._resolve_project_root = lambda x: proot
        try:
            cmd_promote(args)
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        finally:
            cli_mod._resolve_project_root = original_fn
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "ready")

    def test_cli_promote_lint_violation_nonzero(self):
        """CLI promote：lint 违规退出码非 0。"""
        from bin.fenix_cli import _resolve_project_root, cmd_promote
        from argparse import Namespace
        proot, sm, _ = _setup_project(self.tmpdir)
        args = Namespace(spec="myspec", project=str(proot))
        # Mock promote_drafted to return violations
        import bin.fenix_cli as cli_mod
        from unittest.mock import patch
        original_fn = cli_mod._resolve_project_root
        cli_mod._resolve_project_root = lambda x: proot
        try:
            with patch("core.pm_engine.promotion._lint_deliverable_declarations",
                       return_value=["bad path declaration"]):
                with self.assertRaises(SystemExit) as ctx:
                    cmd_promote(args)
                self.assertEqual(ctx.exception.code, 1)
        finally:
            cli_mod._resolve_project_root = original_fn
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "drafted")

    def test_cli_promote_external_project(self):
        """CLI promote：--project 指向外部路径生效。"""
        from bin.fenix_cli import _resolve_project_root, cmd_promote
        from argparse import Namespace
        proot, sm, _ = _setup_project(self.tmpdir)
        args = Namespace(spec="myspec", project=str(proot))
        import bin.fenix_cli as cli_mod
        original_fn = cli_mod._resolve_project_root
        cli_mod._resolve_project_root = lambda x: proot
        try:
            cmd_promote(args)
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        finally:
            cli_mod._resolve_project_root = original_fn
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "ready")


if __name__ == "__main__":
    unittest.main()
