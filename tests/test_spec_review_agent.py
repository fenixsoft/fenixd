"""tests for spec-review-agent: result consumption, write-boundary, recovery.

Covers:
- Three-status mechanical consumption (approved/repaired → ready, rejected → blocked)
- Retry counting & exhausted → blocked with spec-review-incomplete: prefix
- Re-review entry conditions (4 rejection classes)
- Write-boundary validation classes
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine
from core.pm_engine.spec_review import SpecReviewManager, MAX_REVIEW_ATTEMPTS


def _mk_project(tmpdir: Path, spec_name="spec"):
    """Create a minimal project with a drafted spec and spec dir."""
    (tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(tmpdir / ".fenix" / "STATE.md", MagicMock())
    sm.add_spec(spec_name, {"status": "reviewing", "reviewer_run": f"spec-review-{spec_name}-123"})
    (tmpdir / "spec" / "changes" / spec_name).mkdir(parents=True, exist_ok=True)
    (tmpdir / "spec" / "changes" / spec_name / "tasks.md").write_text(
        "# Tasks\n- [ ] 1.1 do it\n", encoding="utf-8"
    )
    return sm


def _write_result(tmpdir: Path, spec_name: str, data: dict):
    """Write a review result file to the spec-review dir."""
    result_path = tmpdir / ".fenix" / "spec-review" / spec_name / ".fenix-run-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return result_path


class _FakeRunner:
    """Minimal agent_runner stub exposing hard-gate API."""

    def __init__(self, gate_err=None):
        self.gate_err = gate_err

    def _check_agent_result_artifact(self, *a, **kw):
        return self.gate_err

    def run_spec_review(self, spec_name, run_id=None):
        return MagicMock(success=True, run_id=f"spec-review-{spec_name}-999")


class TestConsumeReviewResult(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _manager(self, sm=None, runner=None):
        sm = sm or _mk_project(self.tmpdir)
        runner = runner or _FakeRunner()
        engine = MagicMock()
        engine._on_spec_ready = MagicMock()
        return SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock()), sm, engine

    def _set_status(self, sm, status):
        sm.update_spec("spec", {"status": status})

    def test_approved_goes_ready(self):
        _write_result(self.tmpdir, "spec", {"status": "approved", "repairs": [],
                                            "findings": [], "summary": "ok"})
        mgr, sm, engine = self._manager()
        mgr.consume_review_result("spec")
        self.assertEqual(sm.read_one("spec")["status"], "ready")
        engine._on_spec_ready.assert_called_once_with("spec")

    def test_repaired_goes_ready(self):
        _write_result(self.tmpdir, "spec", {"status": "repaired", "repairs": [
            {"path": "spec/changes/spec/tasks.md", "summary": "fixed"}]})
        mgr, sm, engine = self._manager()
        ok = mgr.consume_review_result("spec")
        self.assertTrue(ok)
        self.assertEqual(sm.read_one("spec")["status"], "ready")

    def test_rejected_goes_blocked_with_prefix(self):
        _write_result(self.tmpdir, "spec", {"status": "rejected",
                                            "findings": [{"severity": "blocking",
                                                          "aspect": "hole",
                                                          "detail": "缺关键路径",
                                                          "evidence": "proposal.md"}]})
        mgr, sm, engine = self._manager()
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertTrue(str(entry.get("error", "")).startswith("spec-review-rejected:"))

    def test_gate_failure_retries_not_blocked(self):
        """Gate failure → attempt counted, spec stays reviewing, not blocked yet."""
        _mk_project(self.tmpdir)
        runner = _FakeRunner(gate_err="结果文件缺失")
        mgr, sm, engine = self._manager(runner=runner)
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)  # failure handler counts 1

    def test_exhausted_attempts_blocks_with_incomplete(self):
        """Attempts exhausted → blocked with spec-review-incomplete: prefix."""
        _mk_project(self.tmpdir)
        runner = _FakeRunner(gate_err="结果文件缺失")
        mgr, sm, engine = self._manager(runner=runner)
        # Simulate attempts already exhausted
        sm.update_spec("spec", {"_review_attempts": MAX_REVIEW_ATTEMPTS})
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertTrue(str(entry.get("error", "")).startswith("spec-review-incomplete:"))

    def test_recheck_clears_attempts_on_success(self):
        _mk_project(self.tmpdir)
        mgr, sm, engine = self._manager()
        sm.update_spec("spec", {"_review_attempts": 2})
        _write_result(self.tmpdir, "spec", {"status": "approved", "repairs": []})
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(int(entry.get("_review_attempts", -1)), 0)


class TestReReviewConditions(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _blocked_spec(self, error="spec-review-rejected: 方向性错误"):
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"status": "blocked", "error": error, "reviewer_run": None})
        mgr, _, _ = self._manager(sm)
        return mgr, sm

    def _manager(self, sm=None):
        sm = sm or _mk_project(self.tmpdir)
        runner = _FakeRunner()
        engine = MagicMock()
        return SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock()), sm, engine

    def test_non_review_blocked_rejected(self):
        mgr, sm = self._blocked_spec(error="merge-breaker: 熔断")
        ok, msg = mgr.re_review("spec")
        self.assertFalse(ok)
        self.assertEqual(sm.read_one("spec")["status"], "blocked")

    def test_frozen_rejected(self):
        mgr, sm = self._blocked_spec()
        sm.update_spec("spec", {"frozen": True})
        ok, msg = mgr.re_review("spec")
        self.assertFalse(ok)
        self.assertTrue(sm.read_one("spec")["frozen"])
        self.assertEqual(sm.read_one("spec")["status"], "blocked")

    def test_non_blocked_rejected(self):
        mgr, sm, _ = self._manager()
        sm.update_spec("spec", {"status": "ready"})
        ok, msg = mgr.re_review("spec")
        self.assertFalse(ok)
        self.assertEqual(sm.read_one("spec")["status"], "ready")

    def test_valid_review_blocked_succeeds(self):
        mgr, sm = self._blocked_spec()
        ok, msg = mgr.re_review("spec")
        self.assertTrue(ok)
        self.assertEqual(sm.read_one("spec")["status"], "reviewing")

    def test_idempotent_defense(self):
        """Second invoke after first success rejected (status no longer blocked)."""
        mgr, sm = self._blocked_spec()
        ok1, _ = mgr.re_review("spec")
        self.assertTrue(ok1)
        ok2, msg = mgr.re_review("spec")
        self.assertFalse(ok2)


class TestWriteBoundary(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _manager(self):
        sm = _mk_project(self.tmpdir)
        runner = _FakeRunner()
        engine = MagicMock()
        return SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock()), sm

    def test_repairs_path_outside_rejected(self):
        """repairs path outside spec dir → boundary violation."""
        mgr, _ = self._manager()
        data = {"status": "repaired",
                "repairs": [{"path": "core/state_machine.py", "summary": "x"}]}
        err = mgr._check_write_boundary("spec", data)
        self.assertIsNotNone(err)
        self.assertIn("越界", err)

    def test_approved_with_changes_rejected(self):
        """approved with non-empty repairs → inconsistent."""
        mgr, _ = self._manager()
        data = {"status": "approved",
                "repairs": [{"path": "spec/changes/spec/tasks.md", "summary": "x"}]}
        err = mgr._check_write_boundary("spec", data)
        self.assertIsNotNone(err)
        self.assertIn("approved", err)

    def test_repaired_without_repairs_rejected(self):
        mgr, _ = self._manager()
        data = {"status": "repaired", "repairs": []}
        err = mgr._check_write_boundary("spec", data)
        self.assertIsNotNone(err)
        self.assertIn("repaired", err)


if __name__ == "__main__":
    unittest.main()