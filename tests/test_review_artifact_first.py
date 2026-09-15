"""tests for run-failure-artifact-first: 评审失败判定先查已落盘产物。

Covers (evo-run-failure-artifact-first):
- 2.1 exit code 1 + 产物已落盘 approved → 走消费分支、_review_attempts 不递增、
      状态推进 ready
- 2.2 产物缺失 / status=failed / 快照不一致 → 维持既有重试语义（attempt 递增）
- 2.3 回放 1789368468 场景（402 + approved 产物）→ 不再抛掉结论
- 1.3 _classify_run_failure infra 指纹识别（402/403/429/quota/budget/余额/
      rate limit → infra；None/空 → content）
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


class _FailingRunner:
    """run 执行失败（exit code 非 0）的 runner 桩。

    result 非 None 时在 run 调用期间（attempt_started_at 之后）落盘产物，
    满足 _artifact_landed_valid 的 mtime 新鲜度校验；on_run 回调供测试注入
    快照不一致（如删除 SPEC 目录内文件）。
    """

    def __init__(self, tmpdir, error="boom", result=None, on_run=None,
                 salvage_result=False):
        self.tmpdir = tmpdir
        self.error = error
        self.result = result
        self.on_run = on_run
        self.salvage_result = salvage_result
        self.run_calls = 0

    def _check_agent_result_artifact(self, spec_name, agent_type,
                                     run_started_at=None, wt_path=None):
        return None

    def _salvage_spec_review_result(self, spec_name, run_id):
        return self.salvage_result

    def run_spec_review(self, spec_name, run_id=None):
        self.run_calls += 1
        if self.on_run is not None:
            self.on_run()
        if self.result is not None:
            _write_result(self.tmpdir, spec_name, self.result)
        return MagicMock(success=False, run_id=run_id, error=self.error)


class TestArtifactFirstConsumption(unittest.TestCase):
    """2.1/2.3：exit code 1 + 产物已落盘 → 消费产物、attempt 不递增。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fresh(self):
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None})
        return sm

    def _manager(self, sm=None, runner=None):
        sm = sm or self._fresh()
        runner = runner or _FailingRunner(self.tmpdir)
        engine = MagicMock()
        return SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock()), sm, engine

    def test_exit1_with_approved_artifact_consumes(self):
        """2.1：exit code 1 + 产物已落盘 approved → 消费、状态 ready、attempt 不递增。"""
        sm = self._fresh()
        runner = _FailingRunner(
            self.tmpdir, error="boom",
            result={"status": "approved", "repairs": [], "findings": [],
                    "summary": "ok"})
        mgr, _, engine = self._manager(sm, runner)
        self.assertTrue(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertEqual(int(entry.get("_review_attempts", 0)), 0)
        engine._on_spec_ready.assert_called_once_with("spec")
        # 不得重派：run 只执行一次
        self.assertEqual(runner.run_calls, 1)

    def test_exit1_with_repaired_artifact_consumes(self):
        """2.1 补充：repaired 产物同样按产物消费。"""
        sm = self._fresh()
        runner = _FailingRunner(
            self.tmpdir, error="boom",
            result={"status": "repaired",
                    "repairs": [{"path": "spec/changes/spec/tasks.md",
                                 "summary": "fixed"}]})
        mgr, _, engine = self._manager(sm, runner)
        self.assertTrue(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 0)

    def test_replay_1789368468_402_with_approved_artifact(self):
        """2.3：回放 2026-09-14 事故（402 余额不足 + approved 产物）→ 不再抛掉结论。"""
        sm = self._fresh()
        runner = _FailingRunner(
            self.tmpdir, error="API Error: 402 余额不足",
            result={"status": "approved", "repairs": [], "findings": [],
                    "summary": "ok"})
        mgr, _, engine = self._manager(sm, runner)
        self.assertTrue(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        # 结论被消费而非作废
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 0)
        engine._on_spec_ready.assert_called_once_with("spec")


class TestArtifactFirstRetryFallback(unittest.TestCase):
    """2.2：产物缺失 / status=failed / 快照不一致 → 维持既有重试语义。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fresh(self):
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None})
        return sm

    def test_missing_artifact_retries(self):
        """2.2：产物缺失 → 既有重试（attempt 递增、保持 reviewing）。"""
        sm = self._fresh()
        runner = _FailingRunner(self.tmpdir, error="boom")
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)

    def test_status_failed_retries(self):
        """2.2：结果文件 status=failed（评审器自判失败）→ 非合法产物，走重试。"""
        sm = self._fresh()
        runner = _FailingRunner(
            self.tmpdir, error="boom",
            result={"status": "failed", "findings": []})
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)

    def test_snapshot_inconsistency_retries(self):
        """2.2：快照不一致（SPEC 目录内文件被删除）→ 产物不可信，走重试。"""
        sm = self._fresh()

        def during():
            # run 期间删除 SPEC 目录内文件 → 快照比对检出「被删除」
            (self.tmpdir / "spec" / "changes" / "spec" / "tasks.md").unlink()

        runner = _FailingRunner(
            self.tmpdir, error="boom",
            result={"status": "approved", "repairs": []}, on_run=during)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)


class TestClassifyRunFailure(unittest.TestCase):
    """1.3：_classify_run_failure infra 指纹识别。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _manager(self):
        sm = _mk_project(self.tmpdir)
        runner = _FailingRunner(self.tmpdir)
        return SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())

    def test_infra_fingerprints(self):
        """infra 指纹：402/403/429/quota/budget/余额/rate limit（大小写不敏感）。"""
        mgr = self._manager()
        cases = [
            "API Error: 402 余额不足",          # 402
            "Error 403 Forbidden",             # 403
            "HTTP 429 Too Many Requests",      # 429
            "quota exceeded",                  # quota
            "budget exhausted",                # budget
            "余额不足",                         # 余额
            "insufficient balance",            # insufficient balance
            "Rate Limit reached",              # rate limit（大小写不敏感）
        ]
        for reason in cases:
            category, fingerprint = mgr._classify_run_failure(reason)
            self.assertEqual(category, "infra", f"reason={reason!r}")
            self.assertTrue(fingerprint, f"reason={reason!r} 应有指纹")

    def test_content_fingerprints(self):
        """content：无 infra 指纹 / None / 空串 → content。"""
        mgr = self._manager()
        cases = [None, "", "结果文件缺失", "评审 run 执行失败: 转录截断",
                 "写文件失败: /tmp/x"]
        for reason in cases:
            category, _ = mgr._classify_run_failure(reason)
            self.assertEqual(category, "content", f"reason={reason!r}")

    def test_infra_suffix_written_to_error_and_evidence(self):
        """1.3：infra 标记以 [infra: <指纹>] 后缀透出，spec-review-incomplete: 前缀保留。"""
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None})
        runner = _FailingRunner(self.tmpdir, error="API Error: 402 余额不足")
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        err = str(entry.get("error", ""))
        self.assertTrue(err.startswith("spec-review-incomplete:"), err)
        self.assertIn("[infra: ", err)
        self.assertIn("402", err)

    def test_content_failure_no_infra_suffix(self):
        """content 失败：error 无 [infra: ...] 后缀，前缀保留。"""
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None})
        runner = _FailingRunner(self.tmpdir, error="结果文件缺失")
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        err = str(entry.get("error", ""))
        self.assertTrue(err.startswith("spec-review-incomplete:"), err)
        self.assertNotIn("[infra:", err)

    def test_infra_freeze_evidence_includes_fingerprint(self):
        """infra 达上限冻结：evidence 透出 infra_fingerprint。"""
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None, "_review_attempts": MAX_REVIEW_ATTEMPTS})
        runner = _FailingRunner(self.tmpdir, error="API Error: 402 余额不足")
        mgr = SpecReviewManager(self.tmpdir, sm, runner, MagicMock(), {}, MagicMock())
        with unittest.mock.patch.object(mgr.state_machine, "freeze_for_human") as freeze:
            mgr._handle_review_failure("spec", "API Error: 402 余额不足")
        freeze.assert_called_once()
        err = str(freeze.call_args.kwargs["error"])
        self.assertIn("[infra: ", err)
        self.assertIn("402", err)
        evidence = freeze.call_args.kwargs["evidence"]
        self.assertIn("infra_fingerprint=", evidence)


if __name__ == "__main__":
    unittest.main()
