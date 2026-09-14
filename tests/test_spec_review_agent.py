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


class _RecordingRunner:
    """FakeRunner：记录 run 启动那一刻的 STATE，并可选写结果文件 / 触达回调。

    用于回归「锚点在 run 启动前落盘」与「run 收工后机械收口」两处契约。
    """

    def __init__(self, sm, tmpdir, result=None, gate_err=None, success=True, on_run=None):
        self.sm = sm
        self.tmpdir = tmpdir
        self.result = result
        self.gate_err = gate_err
        self.success = success
        self.on_run = on_run
        self.run_id_seen = None
        self.reviewer_run_at_start = None

    def _check_agent_result_artifact(self, *a, **kw):
        return self.gate_err

    def run_spec_review(self, spec_name, run_id=None):
        # run 启动那一刻的 STATE 快照——锚点必须在此时已落盘
        self.run_id_seen = run_id
        self.reviewer_run_at_start = (self.sm.read_one(spec_name) or {}).get("reviewer_run")
        if self.on_run is not None:
            self.on_run()
        if self.result is not None:
            _write_result(self.tmpdir, spec_name, self.result)
        return MagicMock(success=self.success, run_id=run_id,
                         error=None if self.success else "boom")


class TestDispatchAnchorAndConsume(unittest.TestCase):
    """dispatch_review 接线回归：锚点先落盘（防重派窗口）+ run 收工后机械收口。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fresh(self):
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None})
        return sm

    def test_anchor_written_before_run_starts(self):
        """回归（双派发）：run 启动那一刻 reviewer_run 必须已非空且等于本 run。"""
        sm = self._fresh()
        runner = _RecordingRunner(sm, self.tmpdir, result={"status": "approved", "repairs": []})
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        self.assertTrue(mgr.dispatch_review("spec"))
        self.assertIsNotNone(runner.reviewer_run_at_start)
        self.assertEqual(runner.reviewer_run_at_start, runner.run_id_seen)

    def test_second_dispatch_rejected_while_inflight(self):
        """回归（双派发）：run 在飞期间（锚点已落）第二条派发通道必须被拒。"""
        sm = self._fresh()
        seen = {}
        holder = {}

        def during():
            seen["second"] = holder["mgr"].dispatch_review("spec")

        runner = _RecordingRunner(sm, self.tmpdir,
                                  result={"status": "approved", "repairs": []}, on_run=during)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        holder["mgr"] = mgr
        self.assertTrue(mgr.dispatch_review("spec"))
        self.assertFalse(seen["second"])

    def test_repaired_result_consumed_to_ready(self):
        """根因回归：run 收工后结果必须被消费（repaired → ready + 派发实现）。"""
        sm = self._fresh()
        engine = MagicMock()
        runner = _RecordingRunner(sm, self.tmpdir, result={
            "status": "repaired",
            "repairs": [{"path": "spec/changes/spec/tasks.md", "summary": "x"}]})
        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock())
        self.assertTrue(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry.get("reviewer_run"))
        engine._on_spec_ready.assert_called_once_with("spec")

    def test_rejected_result_consumed_to_blocked(self):
        """根因回归：rejected 结果必须被消费（→ blocked + 规范前缀）。"""
        sm = self._fresh()
        engine = MagicMock()
        runner = _RecordingRunner(sm, self.tmpdir, result={
            "status": "rejected",
            "findings": [{"severity": "blocking", "aspect": "hole", "detail": "x"}]})
        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock())
        self.assertTrue(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertTrue(str(entry.get("error", "")).startswith("spec-review-rejected:"))

    def test_run_failure_clears_anchor_and_counts_attempt(self):
        """run 执行失败：锚点清空、保持 reviewing、尝试计数递增（可重试）。"""
        sm = self._fresh()
        runner = _RecordingRunner(sm, self.tmpdir, success=False)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertEqual(entry["status"], "reviewing")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)

    def test_exhausted_attempts_blocks_not_stranded(self):
        """尝试耗尽：不得停在 reviewing 空转，须转 blocked（规范前缀）。"""
        sm = self._fresh()
        sm.update_spec("spec", {"_review_attempts": MAX_REVIEW_ATTEMPTS})
        runner = _RecordingRunner(sm, self.tmpdir, result={"status": "approved", "repairs": []})
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertTrue(str(entry.get("error", "")).startswith("spec-review-incomplete:"))


if __name__ == "__main__":
    unittest.main()