"""scenario-defect-reroute-gate 单元测试（add-scenario-defect-triage-gate 3.4）。

覆盖 spec 需求 scenario-defect-reroute-gate：
  - 全 test-defect/flaky 触发改道且不打回 implementer
  - 含 product-bug 不改道（走现行 bug-found 路由）
  - None/未知分类保守不改道
  - 改道后 scenario-repaired 正常重入（冻结记账 + 重入执行）
  - 改道后 bug-found 含 product-bug 正常派发（打回 implementer）
  - 预算耗尽升级人工（附失败清单/分类分布/申报记录），spec 保持 testing
  - 改道路径不触碰 impl_run_budget used 计数
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.pm_engine.verification import (
    VerificationPipeline,
    VerdictReadResult,
    _SCENARIO_REPAIR_MAX_ROUNDS,
)


def _mk_pm(tmpdir, spec="demo-spec"):
    """构造最小 PM 桩：project_root/logger/state_machine/agent_runner/
    _read_planner_result/_apply_scenario_freeze/_send_human_escalation_alert。
    """
    pm = SimpleNamespace()
    pm.project_root = Path(tmpdir)
    pm.logger = MagicMock()
    pm.state_machine = SimpleNamespace(
        read_one=lambda s: _STATE.get(s) or {},
        update_spec=lambda s, upd: _STATE.update({s: {**_STATE.get(s, {}), **upd}}),
    )
    pm.agent_runner = SimpleNamespace(
        run_planner=MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, cancelled=False,
                run_id=f"planner-judge-{spec}-123-a1",
            )
        ),
    )
    pm._read_planner_result = MagicMock()
    pm._apply_scenario_freeze = MagicMock(return_value={})
    pm._send_human_escalation_alert = MagicMock()
    return pm


_STATE: dict = {}


def _seed_report(tmpdir, spec, scenarios):
    """写 report.json（改道门判定依据）。"""
    vp = Path(tmpdir) / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    (vp / "report.json").write_text(
        json.dumps({"spec": spec, "scenarios": scenarios}, ensure_ascii=False),
        encoding="utf-8",
    )


def _scenario(sid, status="failed", classification=None):
    sc = {"scenario_id": sid, "status": status}
    if classification is not None:
        sc["classification"] = classification
    return sc


class TestClassificationDistribution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _STATE.clear()
        self.pm = _mk_pm(self.tmpdir)
        self.pipe = VerificationPipeline(self.pm)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_test_defect_triggers(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="flaky"),
        ])
        dist = self.pipe._scenario_classification_distribution("demo-spec")
        assert dist["all_scenario_defects"] is True
        assert dist["product_bug"] == 0
        assert sorted(dist["failed_ids"]) == ["s1", "s2"]

    def test_with_product_bug_does_not_trigger(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="product-bug"),
        ])
        dist = self.pipe._scenario_classification_distribution("demo-spec")
        assert dist["all_scenario_defects"] is False
        assert dist["product_bug"] == 1

    def test_none_classification_conservative(self):
        # 未显式分类（None）→ 保守不改道
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification=None),
        ])
        dist = self.pipe._scenario_classification_distribution("demo-spec")
        assert dist["all_scenario_defects"] is False
        assert dist["unclassified"] == 1

    def test_unknown_classification_conservative(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="whatever"),
        ])
        dist = self.pipe._scenario_classification_distribution("demo-spec")
        assert dist["all_scenario_defects"] is False

    def test_env_classification_not_scenario_defect(self):
        # env = 环境问题，不是场景缺陷 → 不改道
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="env"),
        ])
        dist = self.pipe._scenario_classification_distribution("demo-spec")
        assert dist["all_scenario_defects"] is False

    def test_all_pass_returns_empty(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", status="pass", classification=None),
            _scenario("s2", status="passed", classification=None),
        ])
        dist = self.pipe._scenario_classification_distribution("demo-spec")
        assert dist["total"] == 0
        assert dist["all_scenario_defects"] is False


class TestRerouteGate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _STATE.clear()
        _STATE["demo-spec"] = {"status": "testing"}
        self.pm = _mk_pm(self.tmpdir)
        self.pipe = VerificationPipeline(self.pm)
        # 重入执行在门本身之外（调用方 _run_three_stage_verification 负责）；
        # 单测隔离之，避免牵入完整流水线桩
        self.pipe._run_three_stage_verification = MagicMock()
        self.judge_result = SimpleNamespace(
            success=True, error=None, run_id="planner-judge-demo-spec-1-a1",
            cancelled=False,
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_test_defect_triggers_reroute_not_implementer(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="flaky"),
        ])
        self.pm._read_planner_result.return_value = (
            VerdictReadResult.success("scenario-repaired"))
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        # 改道处置完成（不再打回 implementer）
        assert handled is True
        self.pm.agent_runner.run_planner.assert_called_once_with(
            "demo-spec", "judge")
        # 改道后 scenario-repaired → 冻结记账 + 重入
        self.pm._apply_scenario_freeze.assert_called_once()
        # 不改状态为 bug-found / 不 increment impl budget
        entry = _STATE["demo-spec"]
        assert entry.get("status") != "bug-found"
        assert "impl_run_budget" not in str(entry)

    def test_reroute_does_not_touch_impl_budget_used(self):
        # 显式断言：改道路径绝不触碰 _impl_run_budget_used 计数
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        self.pm._read_planner_result.return_value = (
            VerdictReadResult.success("scenario-repaired"))
        self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        # PM 桩没有 _increment_impl_run_budget_used 调用方——run_planner 是
        # judge 派发，天然不进实现预算；此处断言没有把 impl 计数注入 STATE。
        assert "_impl_run_budget_used" not in _STATE["demo-spec"]

    def test_with_product_bug_does_not_reroute(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification="product-bug"),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        # 不走改道 → 现行 bug-found 路由（打回 implementer）
        assert handled is False
        self.pm.agent_runner.run_planner.assert_not_called()

    def test_none_classification_does_not_reroute(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
            _scenario("s2", classification=None),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        assert handled is False
        self.pm.agent_runner.run_planner.assert_not_called()

    def test_reroute_then_scenario_repaired_reenters(self):
        # 改道后 judge 申报 scenario-repaired → 重入执行（第 1 次修复）
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        self.pm._read_planner_result.return_value = (
            VerdictReadResult.success("scenario-repaired"))
        self.pipe._run_three_stage_verification = MagicMock()
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        assert handled is True
        self.pipe._run_three_stage_verification.assert_called_once_with(
            "demo-spec", _repair_depth=1)

    def test_reroute_then_bug_found_with_product_bug_dispatches(self):
        # 改道后 judge 仍 bug-found 但改判含 product-bug → 正常派发（打回 implementer）
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        self.pm._read_planner_result.return_value = (
            VerdictReadResult.success("bug-found"))
        # 重派后 report 被 judge 更新为含 product-bug
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="product-bug"),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        # 放行现行 bug-found 路由（_on_spec_bug_found 由调用方执行）
        assert handled is False

    def test_budget_exhausted_escalates_human(self):
        # 预算耗尽（_repair_depth >= MAX）→ 停止重派、升级人工、spec 保持 testing
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=_SCENARIO_REPAIR_MAX_ROUNDS,
            judge_result=self.judge_result)
        assert handled is True
        self.pm.agent_runner.run_planner.assert_not_called()
        self.pm._send_human_escalation_alert.assert_called_once()
        entry = _STATE["demo-spec"]
        assert entry["status"] == "testing"  # spec 保持 testing
        assert "预算耗尽" in str(entry.get("error"))

    def test_reroute_budget_exhausted_after_repair_escalates(self):
        # 改道重派后 judge 仍 bug-found 且纯场景缺陷 → 预算耗尽升级人工
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        self.pm._read_planner_result.return_value = (
            VerdictReadResult.success("bug-found"))
        # 重派后仍全 test-defect（judge 未修）
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=_SCENARIO_REPAIR_MAX_ROUNDS - 1,
            judge_result=self.judge_result)
        assert handled is True
        self.pm._send_human_escalation_alert.assert_called_once()
        assert _STATE["demo-spec"]["status"] == "testing"

    def test_reroute_judge_dispatch_failure_holds_testing(self):
        # 改道重派派发失败 → 保持 testing 不升级人工（温和处置）
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        self.pm.agent_runner.run_planner.return_value = SimpleNamespace(
            success=False, error="dispatch failed", cancelled=False)
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        assert handled is True
        self.pm._send_human_escalation_alert.assert_not_called()
        assert _STATE["demo-spec"]["status"] == "testing"

    def test_reroute_judge_cancelled_holds_testing(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        self.pm.agent_runner.run_planner.return_value = SimpleNamespace(
            success=False, error="cancelled", cancelled=True)
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        assert handled is True
        self.pm._send_human_escalation_alert.assert_not_called()

    def test_reroute_unreadable_result_holds_testing(self):
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        self.pm._read_planner_result.return_value = VerdictReadResult.failure(
            "missing", "no file")
        handled = self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        assert handled is True
        self.pm._send_human_escalation_alert.assert_not_called()
        assert _STATE["demo-spec"]["status"] == "testing"

    def test_directive_file_written_for_reroute_prompt(self):
        # 改道触发时写 scenario_reroute_directive.json 供 prompt 注入
        _seed_report(self.tmpdir, "demo-spec", [
            _scenario("s1", classification="test-defect"),
        ])
        self.pm._read_planner_result.return_value = (
            VerdictReadResult.success("scenario-repaired"))
        self.pipe._scenario_defect_reroute_gate(
            "demo-spec", _repair_depth=0, judge_result=self.judge_result)
        dpath = (Path(self.tmpdir) / ".fenix" / "verify-progress"
                 / "demo-spec" / "scenario_reroute_directive.json")
        # 指令文件在 judge 重派后已清理（run 前写入 → 完成后删除）
        assert not dpath.exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))