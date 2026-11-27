"""test_code_review_coverage_gate.py — 全仓审查覆盖缺口执行层测试
（evo-code-review-writeoff-coverage-enforcement 1.1/1.2/1.3 / 2.1）

覆盖：

- 非重派超阈值 → ``success=False`` + ``coverage_partial``/``coverage_gap``
  + run_metrics ``terminal="partial"`` + 告警落盘 + ``coverage_gap`` 锚写入
  （``attempts=1``）；同项目同类型未处置告警去重；
- 低于/等于阈值 → success 保持、不落新锚、无覆盖缺口信号；
- origin 为空 / 原 manifest 缺失 → 不按比例降格（维持既有 WARNING/锁定）；
- 重派 run 超阈值 → 锚不被改指、同 run 锚 attempts 原地递增；达
  ``CODE_REVIEW_COVERAGE_GAP_MAX_RESUME`` 清锚并升级告警；
- 异 run 陈旧锚不抑制本轮降格；
- 批次计划缺批对账能暴露并计入覆盖缺口告警正文，不改变终态判定；
  计划缺失只留痕「无计划可对账」；
- 窗口档不参与全仓覆盖守卫（不降格）。

run_code_review 经最小 runner 替身驱动（``_run_agent`` 替身写真实 out 产物，
聚合读取/落账/核销/锚/告警链路全走生产代码）；台账与锚断言走真实读侧。
"""

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.code_review import read_pending_writeoff, write_pending_writeoff
from core.agent_runner.maintenance_runs import (
    CODE_REVIEW_COVERAGE_GAP_SIGNAL,
    CODE_REVIEW_COVERAGE_GAP_UNRESOLVED_SIGNAL,
    run_code_review,
)


def _make_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="cr-covgate-"))
    (root / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    (root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return root


def _files(prefix: str, count: int) -> list:
    return [f"{prefix}/f{i}.py" for i in range(count)]


class _FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, tag, message):
        self.records.append(f"INFO {tag} {message}")

    def warning(self, tag, message):
        self.records.append(f"WARNING {tag} {message}")

    def error(self, tag, message):
        self.records.append(f"ERROR {tag} {message}")

    def has(self, needle: str) -> bool:
        return any(needle in r for r in self.records)


class _Runner:
    """最小 runner 替身：_run_agent 写真实 out 产物后返回成功。"""

    def __init__(self, proot, run_id, covered_files):
        self.project_root = Path(proot)
        self.logger = _FakeLogger()
        self.config = {}
        self._run_id = run_id
        self._covered = list(covered_files)
        self.metrics = []

    def _unique_code_review_run_id(self):
        return self._run_id

    def _build_prompt(self, run_id, agent_type, detail=None):
        return "prompt"

    def _get_agent_model_assignment(self, name):
        return None

    def _get_admin_model(self):
        return "test-model"

    def _run_agent(self, prompt, root, run_id, model_override, env_overrides,
                   max_turns=None, spec_name=None, agent_type=None):
        path = (self.project_root / ".fenix" / "code-review"
                / f"out-{run_id}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                json.dumps({"file": f, "findings": []}, ensure_ascii=False) + "\n"
                for f in self._covered),
            encoding="utf-8")
        return ("output", 3, "session", {}, None)

    def _extract_usage_info(self, x):
        return {}

    def _accumulate_code_review_tokens(self, run_id, usage):
        return None

    def _read_code_review_out(self, project_root, run_id):
        from core.agent_runner import maintenance_runs

        return maintenance_runs._read_code_review_out(self, project_root, run_id)

    # 显式签名镜像生产 _log_run_metrics（runner.py）：替身保真守卫禁 **kwargs
    # 宽容替身（**kwargs 会静默吸收实参数量不符）
    def _log_run_metrics(self, *, run_id, spec_name, agent_type,
                         duration_seconds, turns, usage_info, terminal,
                         provider=None, model=None, latency=None,
                         toolface=None):
        self.metrics.append(dict(
            run_id=run_id, spec_name=spec_name, agent_type=agent_type,
            duration_seconds=duration_seconds, turns=turns,
            usage_info=usage_info, terminal=terminal, provider=provider,
            model=model, latency=latency, toolface=toolface,
        ))


def _read_signals(proot, signal_type=None, kind=None):
    from core.admin_store import AdminStore

    recs = AdminStore(proot).read_all()
    out = []
    for rec in recs:
        if signal_type is not None and rec.get("signal_type") != signal_type:
            continue
        if kind is not None and rec.get("kind") != kind:
            continue
        out.append(rec)
    return out


def _write_origin_manifest(proot, run_id, files):
    (proot / ".fenix" / "code-review" / f"manifest-{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "scope": "full", "files": list(files)},
                   ensure_ascii=False),
        encoding="utf-8")


def _write_plan(proot, run_id, batches):
    (proot / ".fenix" / "code-review" / f"plan-{run_id}.json").write_text(
        json.dumps(batches, ensure_ascii=False), encoding="utf-8")


class _Base(unittest.TestCase):
    def setUp(self):
        self.proot = _make_repo()
        self.manifest = _files("src", 100)

    def tearDown(self):
        shutil.rmtree(str(self.proot), ignore_errors=True)

    def _run(self, run_id, covered, *, manifest=None, review_kind="manual_full",
             window_start=None, scope="full", redispatch_of=None):
        runner = _Runner(self.proot, run_id, covered)
        result = run_code_review(
            runner, list(self.manifest if manifest is None else manifest),
            review_kind=review_kind, window_start=window_start, scope=scope,
            redispatch_of=redispatch_of)
        return result, runner


class TestOverThresholdDemotion(_Base):
    def test_over_threshold_demotes_partial_writes_anchor_and_alert(self):
        covered = self.manifest[:50]  # 缺口 50/100 = 50%
        result, runner = self._run("code-review-1001", covered)
        self.assertFalse(result.success, "覆盖缺口超阈值 → success 降格")
        self.assertTrue(getattr(result, "coverage_partial", False))
        gap = getattr(result, "coverage_gap", None)
        self.assertIsNotNone(gap)
        self.assertEqual(gap["uncovered"], 50)
        self.assertEqual(gap["total"], 100)
        self.assertAlmostEqual(gap["ratio"], 0.5)
        self.assertEqual(len(gap["files"]), 5)
        self.assertIn("覆盖缺口降格 partial", result.error)
        self.assertIn("50/100", result.error)
        self.assertEqual(result.resolved, 0, "部分覆盖不核销")
        # run_metrics 终态降为 partial
        self.assertTrue(runner.metrics)
        self.assertEqual(runner.metrics[-1].get("terminal"), "partial")
        # WARNING 核销锁定仍留痕
        self.assertTrue(runner.logger.has("全仓快照核销锁定"))
        # 锚：非重派新写 coverage_gap 锚
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-1001")
        self.assertEqual(anchor.get("reason"), "coverage_gap")
        self.assertEqual(anchor.get("attempts"), 1)
        self.assertEqual(anchor.get("gap", {}).get("uncovered"), 50)
        # 告警落盘
        signals = _read_signals(self.proot, CODE_REVIEW_COVERAGE_GAP_SIGNAL)
        self.assertEqual(len(signals), 1)
        rec = signals[0]
        self.assertEqual(rec.get("severity"), "major")
        evidence = rec.get("evidence") or ""
        self.assertIn(f"项目名={self.proot.name}", evidence)
        self.assertIn("uncovered=50", evidence)
        self.assertIn("total=100", evidence)
        self.assertIn("gap_ratio=0.5000", evidence)

    def test_gap_alert_dedupes_same_project_unresolved(self):
        self._run("code-review-1011", self.manifest[:50])
        self._run("code-review-1012", self.manifest[:40])
        signals = _read_signals(self.proot, CODE_REVIEW_COVERAGE_GAP_SIGNAL)
        self.assertEqual(len(signals), 1, "同项目同类型未处置信号不重复写")

    def test_window_scope_never_demotes(self):
        # 窗口档不进全仓核销分支，即使覆盖缺口巨大也不降格/不落锚。
        result, runner = self._run(
            "code-review-1013", self.manifest[:10],
            review_kind="scheduled",
            window_start=datetime(2026, 11, 1, 2, 0, 0), scope="window")
        self.assertTrue(result.success)
        self.assertFalse(getattr(result, "coverage_partial", False))
        self.assertEqual(read_pending_writeoff(self.proot), {})
        self.assertEqual(runner.metrics[-1].get("terminal"), "success")


class TestThresholdBoundary(_Base):
    def test_equal_threshold_keeps_success_no_anchor_no_signal(self):
        covered = self.manifest[:98]  # 缺口 2/100 = 0.02（等于阈值不降格）
        result, runner = self._run("code-review-1021", covered)
        self.assertTrue(result.success)
        self.assertFalse(getattr(result, "coverage_partial", False))
        self.assertIsNone(getattr(result, "coverage_gap", None))
        self.assertEqual(read_pending_writeoff(self.proot), {})
        self.assertEqual(
            _read_signals(self.proot, CODE_REVIEW_COVERAGE_GAP_SIGNAL), [])
        self.assertEqual(runner.metrics[-1].get("terminal"), "success")

    def test_below_threshold_keeps_success(self):
        result, _runner = self._run(
            "code-review-1022", self.manifest[:99])  # 缺口 1%
        self.assertTrue(result.success)
        self.assertEqual(read_pending_writeoff(self.proot), {})
        self.assertEqual(
            _read_signals(self.proot, CODE_REVIEW_COVERAGE_GAP_SIGNAL), [])


class TestUnjudgeableCoverage(_Base):
    def test_empty_origin_never_demotes(self):
        # manifest 为空 → 完整性不可判：维持锁定，不降格、不落锚、不发信号。
        result, runner = self._run("code-review-1031", [], manifest=[])
        self.assertTrue(result.success)
        self.assertFalse(getattr(result, "coverage_partial", False))
        self.assertEqual(read_pending_writeoff(self.proot), {})
        self.assertEqual(
            _read_signals(self.proot, CODE_REVIEW_COVERAGE_GAP_SIGNAL), [])
        self.assertTrue(runner.logger.has("manifest 清单为空"))

    def test_missing_origin_manifest_on_redispatch_never_demotes(self):
        # 重派 run 的原 manifest 缺失 → 缺口不可判，宁锁不降格。
        result, runner = self._run(
            "code-review-1032", ["src/f0.py"], manifest=["src/f0.py"],
            redispatch_of="code-review-gone")
        self.assertTrue(result.success)
        self.assertFalse(getattr(result, "coverage_partial", False))
        self.assertEqual(read_pending_writeoff(self.proot), {})
        self.assertEqual(
            _read_signals(self.proot, CODE_REVIEW_COVERAGE_GAP_SIGNAL), [])
        self.assertTrue(runner.logger.has("原 manifest 缺失/损坏"))


class TestRedispatchAnchorMaintenance(_Base):
    def _seed_anchor(self, run_id, attempts, reason="coverage_gap"):
        write_pending_writeoff(self.proot, {
            "run_id": run_id, "reason": reason, "attempts": attempts,
            "at": "2026-11-20T00:00:00+00:00", "gap": {"uncovered": 50},
        })

    def test_redispatch_increments_attempts_without_repointing(self):
        _write_origin_manifest(self.proot, "code-review-2000", self.manifest)
        self._seed_anchor("code-review-2000", attempts=0)
        result, _runner = self._run(
            "code-review-2001", self.manifest[:50], manifest=self.manifest[:50],
            redispatch_of="code-review-2000")
        self.assertFalse(result.success)
        self.assertTrue(getattr(result, "coverage_partial", False))
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-2000",
                         "重派 run MUST NOT 改指锚（链根不变量）")
        self.assertEqual(anchor.get("attempts"), 1)

    def test_redispatch_reaching_max_clears_anchor_and_escalates(self):
        _write_origin_manifest(self.proot, "code-review-2010", self.manifest)
        self._seed_anchor("code-review-2010", attempts=1)
        result, runner = self._run(
            "code-review-2011", self.manifest[:50], manifest=self.manifest[:50],
            redispatch_of="code-review-2010")
        self.assertFalse(result.success)
        self.assertEqual(read_pending_writeoff(self.proot), {},
                         "达上限清锚停止自动续审")
        escalations = _read_signals(
            self.proot, CODE_REVIEW_COVERAGE_GAP_UNRESOLVED_SIGNAL)
        self.assertEqual(len(escalations), 1)
        self.assertEqual(escalations[0].get("kind"), "escalation")
        self.assertEqual(escalations[0].get("severity"), "critical")
        self.assertTrue(runner.logger.has("续审未收敛"))

    def test_stale_foreign_anchor_does_not_suppress_demotion(self):
        self._seed_anchor("code-review-old", attempts=5, reason="error_salvage")
        result, _runner = self._run("code-review-2021", self.manifest[:50])
        self.assertFalse(result.success, "异 run 陈旧锚不得抑制本轮降格")
        self.assertTrue(getattr(result, "coverage_partial", False))
        # 非重派 run 新写本轮锚（顶掉陈旧锚）
        self.assertEqual(read_pending_writeoff(self.proot).get("run_id"),
                         "code-review-2021")


class TestBatchPlanReconciliation(_Base):
    def test_plan_missing_batch_surfaces_without_changing_terminal(self):
        # 全覆盖（无缺口）但计划声明了一批 manifest 之外的文件 → 计划缺批
        # 仅留痕，不改变 success 终态、不落锚、不发覆盖缺口信号。
        _write_plan(self.proot, "code-review-3001",
                    [{"batch": "b1", "files": self.manifest},
                     {"batch": "b9", "files": ["docs/never-reviewed.md"]}])
        result, runner = self._run("code-review-3001", self.manifest)
        self.assertTrue(result.success)
        self.assertTrue(runner.logger.has("计划缺批"))
        self.assertTrue(runner.logger.has("b9"))
        self.assertEqual(read_pending_writeoff(self.proot), {})
        self.assertEqual(
            _read_signals(self.proot, CODE_REVIEW_COVERAGE_GAP_SIGNAL), [])

    def test_plan_missing_batch_included_in_gap_alert_body(self):
        _write_plan(self.proot, "code-review-3011",
                    [{"batch": "b1", "files": self.manifest[:50]},
                     {"batch": "b2", "files": self.manifest[50:]}])
        result, runner = self._run("code-review-3011", self.manifest[:50])
        self.assertFalse(result.success)
        self.assertTrue(runner.logger.has("计划缺批"))
        signals = _read_signals(self.proot, CODE_REVIEW_COVERAGE_GAP_SIGNAL)
        self.assertEqual(len(signals), 1)
        body = (signals[0].get("description") or "") + \
            (signals[0].get("evidence") or "")
        self.assertIn("计划缺批", body)
        self.assertIn("b2", body)

    def test_plan_missing_file_logs_but_does_not_block(self):
        result, runner = self._run("code-review-3021", self.manifest)
        self.assertTrue(result.success)
        self.assertTrue(runner.logger.has("无计划可对账"))

    def test_corrupt_plan_logs_no_plan_without_changing_terminal(self):
        (self.proot / ".fenix" / "code-review"
         / "plan-code-review-3031.json").write_text("{not-json", encoding="utf-8")
        result, runner = self._run("code-review-3031", self.manifest)
        self.assertTrue(result.success)
        self.assertTrue(runner.logger.has("无计划可对账"))


class TestGapAnchorArmsResumeScan(_Base):
    """覆盖缺口锚写回后，既有锚续审扫描即武装 redispatch（消费侧零改动）。"""

    def test_gap_anchor_arms_period_resume_scan(self):
        from core.admin_monitor import AdminMonitor

        # 1) 干净收尾但覆盖缺口 50% → 降格 + 写 coverage_gap 锚
        result, _runner = self._run("code-review-4000", self.manifest[:50])
        self.assertFalse(result.success)
        anchor = read_pending_writeoff(self.proot)
        self.assertEqual(anchor.get("run_id"), "code-review-4000")
        self.assertEqual(anchor.get("reason"), "coverage_gap")

        # 2) 既有周期锚扫描：锚在册即按「收集清单 − 锚链累计覆盖」剃余派发
        captures = []

        class _CaptureRunner:
            _running_agents = {}

            def run_code_review(self, manifest, **kwargs):
                captures.append({"manifest": list(manifest), **kwargs})
                return SimpleNamespace(
                    run_id="code-review-4001", success=True, inserted=0,
                    updated=0, resolved=0, shards=0, error="",
                    ratelimit_redispatch=None, stall_redispatch=None,
                    fail_face=None, review_429_storm=False)

        monitor = AdminMonitor(
            {
                "project": {"name": self.proot.name},
                "admin": {
                    "code_review": {"enabled": True, "scope": "full"},
                    "self_review": {"enabled": True, "run_at": "00:00"},
                    "code_review_fix": {"night_quiet_window": "off"},
                },
            },
            None,
            str(self.proot),
            _FakeLogger(),
            agent_runner=_CaptureRunner(),
            code_review_executor=None,
        )
        with mock.patch(
                "core.code_review.collect_manifest",
                return_value=list(self.manifest)), \
                mock.patch(
                    "core.code_review.compute_window",
                    return_value=(datetime(2026, 11, 20, 2, 0, 0), "self_review")), \
                mock.patch("core.code_review.read_code_review_state",
                           return_value={}), \
                mock.patch("core.code_review.save_code_review_state"):
            dispatch = monitor._run_writeoff_anchor_resume_checkpoint()

        self.assertEqual(dispatch.get("reason"), "writeoff_resume_dispatched")
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0].get("redispatch_of"), "code-review-4000")
        self.assertEqual(captures[0].get("manifest"), self.manifest[50:],
                         "续审只派未覆盖的剩余清单")


if __name__ == "__main__":
    unittest.main()
