"""fix-verdict-retry-misattribution 单元测试（任务 5.1）。

覆盖（对 2026-09-08 事故链的可复放回归）：
  1. `_verify_verdict_evidence` 语义化返回：frozen 拦截 / 取消拦截 / 异常早退 /
     派发失败 / 真二次违规 / report 缺失 —— cause 判定与明细透传。
  2. 调用方采纳处按 cause 分支：frozen/cancelled 零写入零告警；dispatch_failed
     温和处置不发 verdict_evidence_invalid；violations 保留 blocked + 告警
     （evidence 含 violations 明细）；未知 cause fail-closed。
  3. 首轮 judge_result.success=False 的 frozen 让位分支：不 raise、不改状态。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.runner import FROZEN_TERMINATED_ERROR_PREFIX


def _run_res(**kw):
    """构造 AgentRunResult 风格命名空间（结构化字段与 runner 对齐）。"""
    defaults = dict(success=True, error=None, run_id="j", cancelled=False)
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class _VerifyVerdictBase(unittest.TestCase):
    """公共夹具：临时项目根 + PMEngine（不真实派发）+ 裁决证据校验。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger)
        self.sm.add_spec("my-spec", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("my-spec", to)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _report_path(self):
        return (
            self.project_root / ".fenix" / "verify-progress"
            / "my-spec" / "report.json"
        )

    def _seed_noncompliant_report(self):
        """两个 fail 场景缺 classification/evidence → validate_report 非合规。"""
        self._report_path().parent.mkdir(parents=True, exist_ok=True)
        self._report_path().write_text(json.dumps({
            "scenarios": [
                {"scenario_id": "s1", "status": "fail"},
                {"scenario_id": "s2", "status": "fail"},
            ],
        }, ensure_ascii=False), encoding="utf-8")

    def _seed_compliant_report(self):
        """全 PASS → validate_report 合规。"""
        self._report_path().parent.mkdir(parents=True, exist_ok=True)
        self._report_path().write_text(json.dumps({
            "scenarios": [
                {"scenario_id": "s1", "status": "pass",
                 "assertion_results": [{"type": "step", "pass": True}]},
            ],
        }, ensure_ascii=False), encoding="utf-8")

    def _verify(self, retry_judge=True):
        return self.engine._verification._verify_verdict_evidence(
            "my-spec", retry_judge=retry_judge)


# ────────────────── _verify_verdict_evidence cause 判定 ──────────────────


class TestVerifyVerdictEvidenceCauses(_VerifyVerdictBase):
    """四条 False 路径语义拆分 + 合规/真违规判定（design D1）。"""

    def test_frozen_gate_yields_dispatch_frozen(self):
        """复放 2026-09-08T09:28：重试 judge 被 frozen 门拦截 → dispatch_frozen，
        携带首轮 violations，不按二次违规处置。"""
        self._seed_noncompliant_report()
        # _verify_verdict_evidence 内部仅调用一次 run_planner（即重试轮）
        self.engine.agent_runner.run_planner = MagicMock(return_value=_run_res(
            success=False, run_id="j2",
            error=f"{FROZEN_TERMINATED_ERROR_PREFIX} — auto-retry "
                  f"terminated (attempt 1/3)"))
        ret = self._verify(retry_judge=True)
        self.assertFalse(ret["ok"])
        self.assertEqual(ret["cause"], "dispatch_frozen")
        self.assertTrue(
            ret["dispatch_error"].startswith(FROZEN_TERMINATED_ERROR_PREFIX))
        self.assertEqual(len(ret["violations"]), 2, "首轮 violations 原样携带")
        self.assertEqual(self.engine.agent_runner.run_planner.call_count, 1)

    def test_cancel_interception_yields_dispatch_cancelled(self):
        """取消旗标拦截（cancelled 结构化字段）→ dispatch_cancelled，同语义让位。"""
        self._seed_noncompliant_report()
        self.engine.agent_runner.run_planner = MagicMock(return_value=_run_res(
            success=False, cancelled=True, error="cancelled by admin"))
        ret = self._verify(retry_judge=True)
        self.assertFalse(ret["ok"])
        self.assertEqual(ret["cause"], "dispatch_cancelled")
        self.assertEqual(len(ret["violations"]), 2)

    def test_dispatch_exception_early_returns_without_rereading_report(self):
        """run_planner 抛异常 → dispatch_exception 立即早退；不落至 load_report
        复读第一轮违规旧文件（断言重试异常后无「重试后仍不合规」ERROR 留痕）。"""
        self._seed_noncompliant_report()

        def _boom(spec_name, agent_type):
            raise RuntimeError("provider 5xx")

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_boom)
        # 追踪 load_report 调用次数：合规首轮 1 次 + 重试异常早退 0 次
        import core.verdict_check as _vc
        real_load = _vc.load_report
        calls = []

        def _spy(*a, **kw):
            calls.append(a)
            return real_load(*a, **kw)

        with patch("core.verdict_check.load_report", side_effect=_spy):
            ret = self._verify(retry_judge=True)
        self.assertFalse(ret["ok"])
        self.assertEqual(ret["cause"], "dispatch_exception")
        self.assertIn("5xx", ret["dispatch_error"])
        self.assertEqual(len(calls), 1, "异常早退 MUST NOT 复读第一轮旧 report.json")
        # 无「重试后仍不合规」假 ERROR
        error_msgs = [str(c[0]) for c in self.logger.error.call_args_list]
        self.assertFalse(
            any("重试后" in m for m in error_msgs),
            f"异常早退 MUST NOT 打出「重试后仍不合规」假 ERROR: {error_msgs}")

    def test_dispatch_failed_preserves_original_error(self):
        """网关拒绝/预算闸门等其它派发失败 → dispatch_failed 携带原始 error。"""
        self._seed_noncompliant_report()
        self.engine.agent_runner.run_planner = MagicMock(return_value=_run_res(
            success=False, error="gateway refused (402)", cancelled=False))
        ret = self._verify(retry_judge=True)
        self.assertFalse(ret["ok"])
        self.assertEqual(ret["cause"], "dispatch_failed")
        self.assertIn("402", ret["dispatch_error"])

    def test_true_second_violation_yields_violations_with_details(self):
        """重试 judge 成功但新产物仍违规 → cause=violations + 原始明细。"""
        self._seed_noncompliant_report()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=_run_res(run_id="j2"))
        ret = self._verify(retry_judge=True)
        self.assertFalse(ret["ok"])
        self.assertEqual(ret["cause"], "violations")
        self.assertGreater(len(ret["violations"]), 0)
        self.assertIn("scenario_id", ret["violations"][0])
        self.assertIn("reason", ret["violations"][0])

    def test_report_missing_after_retry(self):
        """重试成功但 report.json 不可读 → cause=report_missing（产物缺失非违规）。"""
        self._seed_noncompliant_report()

        def _side_effect(spec_name, agent_type):
            # 重试轮 run_planner 前先把 report.json 删掉，返回成功
            self._report_path().unlink(missing_ok=True)
            return _run_res(run_id="j2")

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_side_effect)
        ret = self._verify(retry_judge=True)
        self.assertFalse(ret["ok"])
        self.assertEqual(ret["cause"], "report_missing")

    def test_compliant_first_round_cause_pass(self):
        """首轮合规 → cause=pass（不触发重试）。"""
        self._seed_compliant_report()
        ret = self._verify(retry_judge=True)
        self.assertTrue(ret["ok"])
        self.assertEqual(ret["cause"], "pass")
        self.assertEqual(self.engine.agent_runner.run_planner.call_count, 0)

    def test_first_round_violations_without_retry_budget(self):
        """无重试预算的首轮不合规 → cause=violations（沿用首轮判定）。"""
        self._seed_noncompliant_report()
        ret = self._verify(retry_judge=False)
        self.assertFalse(ret["ok"])
        self.assertEqual(ret["cause"], "violations")
        self.assertEqual(len(ret["violations"]), 2)


# ──────────────────── 调用方采纳处 cause 分支 ────────────────────


class _AdoptionBase(unittest.TestCase):
    """驱动 _run_three_stage_verification 至阶段3+ 采纳处（不真实派发）。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger)
        self.verify_dir = (
            self.project_root / ".fenix" / "verify-progress" / "demo-spec")
        self.verify_dir.mkdir(parents=True)
        (self.verify_dir / "test_scenarios.json").write_text(json.dumps([
            {
                "id": "scn-a",
                "description": "场景A",
                "steps": [
                    {"action": "navigate",
                     "value": "http://localhost:8787/#/projects/demo"},
                    {"action": "wait", "target": ".x", "description": "等待"},
                ],
                "assertions": [{"type": "element_visible",
                                "selector": ".x", "label": "可见"}],
            },
        ], ensure_ascii=False), encoding="utf-8")
        self.sm.add_spec("demo-spec", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("demo-spec", to)
        self.engine._enqueue = MagicMock()
        self.engine._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._apply_interaction_contract = MagicMock(return_value=None)
        self.engine._update_warning_streaks = MagicMock(return_value=[])
        self.engine._ensure_app_reachable = MagicMock(
            return_value=(True, False, ""))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_with_judge(self, judge_result, verdict_ret):
        """FakeEngine 产出 1 过 1 败报告 → judge_result 由调用方给定 →
        裁决证据校验结果 verdict_ret 由调用方给定 → 跑完采纳处。"""
        # run_planner 按 agent_type 分流：阶段1 plan 必须成功（走常规出题），
        # 阶段3 judge 返回调用方给定的 judge_result。
        def _run_planner(spec_name, agent_type):
            if agent_type == "plan":
                return _run_res(run_id="p0")
            return judge_result

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_run_planner)
        self.engine._verify_verdict_evidence = MagicMock(
            return_value=verdict_ret)

        class FakeEngine:
            def __init__(self, *a, **kw):
                pass

            async def run(self, scenarios):
                return {
                    "spec": "demo-spec",
                    "summary": {"total": 2, "passed": 1, "warnings": 0,
                                "failed": 1, "errors": 0, "blocked_env": 0},
                    "scenarios": [],
                }

        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")

    def _alerts(self):
        from core.admin_store import AdminStore
        return AdminStore(self.project_root, self.logger).read_all()


class TestAdoptionCallerFrozenCancelledYield(_AdoptionBase):
    """dispatch_frozen / dispatch_cancelled → 零写入零告警让位。"""

    def _assert_untouched(self):
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing", "frozen/cancelled 让位不改状态")
        self.assertFalse(
            entry.get("_cancelled_hold", False),
            "让位路径不得触 _cancelled_hold（保持 False）")
        self.assertFalse(
            (entry.get("error") or "").__contains__("裁决证据"),
            "让位路径不得写裁决证据相关 error")
        alerts = [a for a in self._alerts()]
        self.assertEqual(alerts, [], "frozen/cancelled 让位零告警")

    def test_frozen_gate_zero_write_zero_alert(self):
        """复放 09:28：重试派发被 frozen 门拦截 → 不写 blocked、不发告警。"""
        frozen = _run_res(
            success=False, run_id="j1",
            error=f"{FROZEN_TERMINATED_ERROR_PREFIX} — auto-retry "
                  f"terminated (attempt 1/3)")
        self._run_with_judge(
            judge_result=_run_res(run_id="j0"),
            verdict_ret={"ok": False, "cause": "dispatch_frozen",
                         "violations": [{"scenario_id": "s1",
                                         "status": "fail",
                                         "reason": "classification 缺失"}],
                         "dispatch_error": frozen.error},
        )
        self._assert_untouched()

    def test_cancel_flag_zero_write_zero_alert(self):
        """取消旗标拦截 → 同语义零写入零告警。"""
        self._run_with_judge(
            judge_result=_run_res(run_id="j0"),
            verdict_ret={"ok": False, "cause": "dispatch_cancelled",
                         "violations": [], "dispatch_error": "cancelled by admin"},
        )
        self._assert_untouched()


class TestAdoptionCallerViolations(_AdoptionBase):
    """cause=violations → 保留 blocked + verdict_evidence_invalid（evidence 增强）。"""

    def test_violations_blocks_and_alerts_with_details(self):
        violations = [
            {"scenario_id": "s1", "status": "fail",
             "reason": "classification 缺失或取值非法"},
            {"scenario_id": "s2", "status": "fail", "reason": "evidence 为空"},
        ]
        self._run_with_judge(
            judge_result=_run_res(run_id="j0"),
            verdict_ret={"ok": False, "cause": "violations",
                         "violations": violations, "dispatch_error": ""},
        )
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("重试一次仍不合规", entry["error"],
                      "violations 路径保留「重试一次仍不合规」表述（重试确实发生）")
        alerts = [a for a in self._alerts()
                  if a.get("signal_type") == "verdict_evidence_invalid"]
        self.assertEqual(len(alerts), 1)
        evidence = alerts[0]["evidence"]
        self.assertIn("s1", evidence, "告警 evidence 可读出每条违规 scenario_id")
        self.assertIn("classification 缺失或取值非法", evidence,
                      "告警 evidence 携带每条违规 reason")
        self.assertIn("violations_total=2", evidence)


class TestAdoptionCallerDispatchFailed(_AdoptionBase):
    """dispatch_failed → 温和处置：写 error、不写 blocked、不发
    verdict_evidence_invalid（派发故障不得冒充二次违规）。"""

    def test_dispatch_failed_no_invalid_alert(self):
        self._run_with_judge(
            judge_result=_run_res(run_id="j0"),
            verdict_ret={"ok": False, "cause": "dispatch_failed",
                         "violations": [], "dispatch_error": "gateway refused"},
        )
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing", "派发失败不动 status")
        self.assertIn("gateway refused", entry.get("error") or "")
        alerts = [a for a in self._alerts()
                  if a.get("signal_type") == "verdict_evidence_invalid"]
        self.assertEqual(alerts, [],
                         "dispatch_failed MUST NOT 发 verdict_evidence_invalid")


class TestAdoptionCallerUnknownCause(_AdoptionBase):
    """未知 cause → 按 violations 保守处置（fail-closed）+ ERROR 留痕。"""

    def test_unknown_cause_fail_closed(self):
        self._run_with_judge(
            judge_result=_run_res(run_id="j0"),
            verdict_ret={"ok": False, "cause": "future-cause",
                         "violations": [{"scenario_id": "s1", "status": "fail",
                                         "reason": "未知 cause 时按违规兜底"}],
                         "dispatch_error": ""},
        )
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked", "未知 cause 不静默放行")
        error_msgs = [str(c[0]) for c in self.logger.error.call_args_list]
        self.assertTrue(
            any("未知 cause" in m for m in error_msgs),
            "未知 cause 须 ERROR 留痕")


class TestFirstRoundJudgeFrozen(_AdoptionBase):
    """首轮 judge_result.success=False 且为 frozen 门失败 → 让位不 raise（design D4）。"""

    def test_first_round_frozen_yields_without_raise(self):
        frozen = _run_res(
            success=False, run_id="j0",
            error=f"{FROZEN_TERMINATED_ERROR_PREFIX} — auto-retry "
                  f"terminated (attempt 1/3)")
        # 阶段1 plan 成功；阶段3 judge 返回 frozen 门失败
        def _run_planner(spec_name, agent_type):
            if agent_type == "plan":
                return _run_res(run_id="p0")
            return frozen

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_run_planner)
        self.engine._verify_verdict_evidence = MagicMock(
            return_value={"ok": True, "cause": "pass",
                          "violations": [], "dispatch_error": ""})

        class FakeEngine:
            def __init__(self, *a, **kw):
                pass

            async def run(self, scenarios):
                return {
                    "spec": "demo-spec",
                    "summary": {"total": 2, "passed": 1, "warnings": 0,
                                "failed": 1, "errors": 0, "blocked_env": 0},
                    "scenarios": [],
                }

        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")
        # 不 raise、不重派、不改状态；frozen 让位后 spec 保持 testing
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.engine.agent_runner.run_planner.assert_called_once()
        self.engine._verify_verdict_evidence.assert_not_called()


if __name__ == "__main__":
    unittest.main()
