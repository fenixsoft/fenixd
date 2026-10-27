"""fix-judge-budget-counters-alignment：场景修复预算与重跑硬上限双计数口径对齐。

覆盖四组行为：

1. 修复通道受理门（无修复纯归因模式）：``_scenario_repair_exhausted_rounds
   >= 1``（STATE 持久字段，跨 episode / 跨 daemon 重启）时 judge 的
   scenario-repaired 申报一律拒收——场景文件不改写、不触发重执行重入、
   裁决产物照常保留（test-defect 仅记录），spec 保持 testing（拒收返回
   True 提前退出裁决采纳尾段，平铺 ``_apply_verified`` 不吞拒收态）。
2. 未耗尽路径逐位不变：既有修复路径（冻结记账 + 尾递归重入）零变化。
3. 受理门写点计数留痕：生命周期修复申报轮数（受理与拒收均计）、耗尽后
   拒收轮数单独计数；清零点与 ``_judge_rerun_count`` 同族（verified 落定 +
   人工 unfreeze_spec；admin 处置复位不清零）。
4. 硬上限冻结告警附修复预算上下文：evidence 拼入耗尽字段值/申报轮数
   （含耗尽后拒收）/最近申报摘要；recommended_action 按耗尽与否分叉；
   无修复历史时文案退化到既有形态不报错。
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine
from core.pm_engine.verification import VerdictReadResult


def _make_pipe(tmpdir: str, sm: StateMachine):
    """构造最小 VerificationPipeline 桩（类 test_pm_verification
    .TestScenarioRepairReverifySchedule._make_pipe）。"""
    from core.pm_engine.verification import VerificationPipeline
    pm = SimpleNamespace()
    pm.project_root = Path(tmpdir)
    pm.logger = MagicMock()
    pm.state_machine = sm
    pm.agent_runner = MagicMock()
    pm._send_human_escalation_alert = MagicMock()
    pm._enqueue = MagicMock()
    pm._process_queue = MagicMock()
    return VerificationPipeline(pm)


def _make_testing_spec(sm: StateMachine, name: str = "demo-spec") -> None:
    sm.add_spec(name, {"priority": 5})
    sm.transition(name, "ready")
    sm.transition(name, "implementing")
    sm.transition(name, "implemented")
    sm.transition(name, "testing")


class TestRepairGateRejectsWhenExhausted(unittest.TestCase):
    """受理门：耗尽态（STATE 持久字段 >= 1）拒收 scenario-repaired 申报。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", MagicMock())
        _make_testing_spec(self.sm)
        self.verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        self.verify_dir.mkdir(parents=True)
        # 场景文件（judge 原地修复通道的改写目标）
        self.scenarios_path = self.verify_dir / "test_scenarios.json"
        self.scenarios_content = json.dumps([
            {
                "id": "scn-a",
                "description": "场景A",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8787/#/projects/demo"},
                    {"action": "wait", "target": ".x", "description": "等待"},
                ],
                "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
            },
        ], ensure_ascii=False)
        self.scenarios_path.write_text(self.scenarios_content, encoding="utf-8")
        # judge 裁决产物（report.json，含 test-defect 记录）——受理门拒收
        # 后照常保留（仅记录，不删除不改写）
        self.report_path = self.verify_dir / "report.json"
        self.report_content = json.dumps({
            "spec": "demo-spec",
            "summary": {"total": 1, "passed": 0, "failed": 1, "warnings": 0},
            "scenarios": [
                {
                    "scenario_id": "scn-a",
                    "status": "failed",
                    "classification": "test-defect",
                    "evidence": {"first_failed_step": "wait .x"},
                },
            ],
        }, ensure_ascii=False)
        self.report_path.write_text(self.report_content, encoding="utf-8")
        self.sm.update_spec("demo-spec", {"_scenario_repair_exhausted_rounds": 1})
        self.pipe = _make_pipe(self.tmpdir, self.sm)
        self.pipe._apply_scenario_freeze = MagicMock(return_value={})
        self.pipe._run_three_stage_verification = MagicMock()
        self.pipe._apply_verified = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_gate_rejects_repair_when_exhausted(self):
        """耗尽态申报 → 拒收：文件不改写、产物保留、计数留痕、WARNING 留痕。"""
        rv = self.pipe._handle_scenario_repaired("demo-spec", "scenario-repaired", 0)
        # 提前退出裁决采纳尾段：MUST 返回 True（调用方 MUST return）
        self.assertTrue(rv)
        # 场景文件不改写、不触发重执行重入
        self.pipe._apply_scenario_freeze.assert_not_called()
        self.pipe._run_three_stage_verification.assert_not_called()
        self.assertEqual(
            self.scenarios_path.read_text(encoding="utf-8"), self.scenarios_content)
        # 裁决产物照常保留：test-defect 记录在案（门不删除不改写产物）
        self.assertEqual(
            self.report_path.read_text(encoding="utf-8"), self.report_content)
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["scenarios"][0]["classification"], "test-defect")
        entry = self.sm.read_one("demo-spec")
        # error 留痕（拒收文案），spec 保持 testing
        self.assertIn("纯归因", str(entry.get("error")))
        self.assertIn("拒收", str(entry.get("error")))
        self.assertEqual(entry["status"], "testing")
        # 计数留痕：生命周期申报 +1、耗尽后拒收 +1、最近申报摘要留痕
        # （取自裁决产物 report.json 非 PASS 场景 id，场景 id 级截断）
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(int(entry.get("_judge_repair_rejected_rounds") or 0), 1)
        self.assertEqual(entry.get("_judge_repair_last_summary"), "scn-a")
        # WARNING 留痕（修复预算已耗尽，转纯归因）
        warnings = [
            str(c.args[-1] if c.args else "")
            for c in self.pipe._context.logger.warning.call_args_list
        ]
        self.assertTrue(any("修复预算已耗尽" in w and "纯归因" in w for w in warnings))

    def test_rejection_returns_true_not_false(self):
        """拒收 MUST NOT 返回 False——返回 False 会穿透平铺尾段落 _apply_verified。"""
        for depth in (0, 1, 2):
            rv = self.pipe._handle_scenario_repaired("demo-spec", "scenario-repaired", depth)
            self.assertTrue(rv)
        self.pipe._apply_verified.assert_not_called()

    def test_exhaustion_persists_across_restart(self):
        """跨重启持久：新 pipeline 实例（daemon 重启模拟）读 STATE 仍拒收。"""
        # 模拟重启：全新 VerificationPipeline 实例读同一 STATE.md
        fresh_pipe = _make_pipe(self.tmpdir, self.sm)
        fresh_pipe._apply_scenario_freeze = MagicMock(return_value={})
        fresh_pipe._run_three_stage_verification = MagicMock()
        rv = fresh_pipe._handle_scenario_repaired("demo-spec", "scenario-repaired", 0)
        self.assertTrue(rv)
        fresh_pipe._apply_scenario_freeze.assert_not_called()
        fresh_pipe._run_three_stage_verification.assert_not_called()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertIn("纯归因", str(entry.get("error")))
        # 耗尽字段未被清除（仍 >= 1）
        self.assertGreaterEqual(
            int(entry.get("_scenario_repair_exhausted_rounds") or 0), 1)

    def test_not_exhausted_repair_path_unchanged(self):
        """未耗尽 → 既有修复路径逐位不变：冻结记账 + 尾递归重入。"""
        self.sm.update_spec("demo-spec", {"_scenario_repair_exhausted_rounds": 0})
        rv = self.pipe._handle_scenario_repaired("demo-spec", "scenario-repaired", 0)
        self.assertTrue(rv)
        self.pipe._apply_scenario_freeze.assert_called_once_with("demo-spec")
        self.pipe._run_three_stage_verification.assert_called_once()
        self.assertEqual(
            self.pipe._run_three_stage_verification.call_args.kwargs.get("_repair_depth"), 1)
        entry = self.sm.read_one("demo-spec")
        # 受理路径不写拒收 error、状态不被受理门改动
        self.assertEqual(entry["status"], "testing")
        self.assertNotIn("纯归因", str(entry.get("error") or ""))
        # 计数留痕：受理 +1，拒收不计数
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 1)
        self.assertEqual(int(entry.get("_judge_repair_rejected_rounds") or 0), 0)

    def test_non_repaired_status_passthrough(self):
        """非 scenario-repaired 状态 → 返回 False（调用方继续后续分支），零副作用。"""
        self.assertEqual(
            self.pipe._handle_scenario_repaired("demo-spec", "verified", 0), False)
        self.pipe._apply_scenario_freeze.assert_not_called()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), 0)


class TestRepairGateFlowLevel(unittest.TestCase):
    """全流程级：耗尽态拒收后平铺尾段不吞拒收态（spec 不被置 verified）。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        self.verify_dir.mkdir(parents=True)
        (self.verify_dir / "test_scenarios.json").write_text(json.dumps([
            {
                "id": "scn-a",
                "description": "场景A",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8787/#/projects/demo"},
                    {"action": "wait", "target": ".x", "description": "等待"},
                ],
                "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
            },
        ], ensure_ascii=False), encoding="utf-8")
        _make_testing_spec(self.sm)
        self.engine._enqueue = MagicMock()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id="planner-judge-demo-spec-1-a1")
        )
        self.engine._verification._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._verification._apply_interaction_contract = MagicMock(return_value=None)
        self.engine._verification._run_contract_static_check = MagicMock(return_value=False)
        self.engine._verification._verify_verdict_evidence = MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._verification._update_warning_streaks = MagicMock(return_value=[])
        self.engine._verification._ensure_app_reachable = MagicMock(return_value=(True, False, ""))
        self.engine._verification._apply_verified = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exhausted_rejection_not_swallowed_by_flat_tail(self):
        """耗尽态 judge 申报 scenario-repaired → 拒收；spec 保持 testing，
        平铺尾段（_apply_verified）不吞拒收态。"""
        self.sm.update_spec("demo-spec", {"_scenario_repair_exhausted_rounds": 1})
        self.engine._verification._read_verdict = MagicMock(
            return_value=VerdictReadResult.success("scenario-repaired"))

        class FakeEngine:
            def __init__(self, *a, **k):
                pass

            async def run(self, scenarios):
                return {
                    "spec": "demo-spec",
                    "summary": {"total": 1, "passed": 0, "warnings": 0,
                                "failed": 1, "errors": 0, "blocked_env": 0},
                    "scenarios": [],
                }

        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")
        # 拒收：不重写场景、不重入执行、不假收敛 verified
        self.engine._verification._apply_scenario_freeze.assert_not_called()
        self.engine._verification._apply_verified.assert_not_called()
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertIn("纯归因", str(entry.get("error")))


class TestHardCapFreezeRepairContext(unittest.TestCase):
    """硬上限冻结告警附修复预算上下文（judge_gate._judge_hard_cap_freeze）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", MagicMock())
        _make_testing_spec(self.sm)
        self.pipe = _make_pipe(self.tmpdir, self.sm)
        self.freeze = MagicMock()
        self.sm.freeze_for_human = self.freeze

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_freeze_alert_carries_repair_context(self):
        """触顶冻结时 evidence 含耗尽字段值/申报轮数（含拒收）/最近申报摘要；
        recommended_action 指向人工修复/归因豁免路径。"""
        self.sm.update_spec("demo-spec", {
            "_scenario_repair_exhausted_rounds": 1,
            "_judge_repair_claim_rounds": 4,
            "_judge_repair_rejected_rounds": 1,
            "_judge_repair_last_summary": "scn-a、scn-b",
        })
        from core.pm_engine.verification.judge_gate import _judge_hard_cap_freeze
        _judge_hard_cap_freeze(self.pipe, "demo-spec", 6)
        self.assertTrue(self.freeze.called)
        kwargs = self.freeze.call_args.kwargs
        evidence = str(kwargs.get("evidence"))
        self.assertIn("耗尽=1", evidence)
        self.assertIn("修复申报=4", evidence)
        self.assertIn("拒收 1", evidence)
        self.assertIn("scn-a、scn-b", evidence)
        action = str(kwargs.get("recommended_action"))
        self.assertIn("人工修复", action)
        self.assertIn("归因豁免", action)
        # 冻结语义不变：blocked + 冻结旗标
        self.assertEqual(kwargs.get("signal_type"), "judge_rerun_cap")
        self.assertEqual(kwargs.get("extra_updates"), {"_judge_cap_frozen": True})

    def test_freeze_without_repair_history_degrades(self):
        """无修复历史：文案退化到既有形态（不报错、不引KeyError）。"""
        from core.pm_engine.verification.judge_gate import _judge_hard_cap_freeze
        _judge_hard_cap_freeze(self.pipe, "demo-spec", 6)
        kwargs = self.freeze.call_args.kwargs
        evidence = str(kwargs.get("evidence"))
        self.assertIn("耗尽=0", evidence)
        self.assertIn("修复申报=0", evidence)
        self.assertIn("无记录", evidence)
        action = str(kwargs.get("recommended_action"))
        self.assertIn("检查验证为何反复重跑", action)
        self.assertNotIn("归因豁免", action)

    def test_freeze_with_dirty_values_no_crash(self):
        """脏值（非数值串）按 0 兜底，不抛 TypeError/ValueError。"""
        self.sm.update_spec("demo-spec", {
            "_scenario_repair_exhausted_rounds": "garbage",
            "_judge_repair_claim_rounds": "garbage",
        })
        from core.pm_engine.verification.judge_gate import _judge_hard_cap_freeze
        _judge_hard_cap_freeze(self.pipe, "demo-spec", 6)
        self.assertTrue(self.freeze.called)


class TestRepairCounterClearPoints(unittest.TestCase):
    """受理门计数留痕字段清零点与 _judge_rerun_count 同族：
    verified 落定 + 人工 unfreeze_spec；admin 处置复位不清零。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", MagicMock())
        _make_testing_spec(self.sm)
        self.sm.update_spec("demo-spec", {
            "_scenario_repair_exhausted_rounds": 1,
            "_judge_repair_claim_rounds": 4,
            "_judge_repair_rejected_rounds": 2,
            "_judge_repair_last_summary": "scn-a、scn-b",
        })
        self.pipe = _make_pipe(self.tmpdir, self.sm)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _assert_counters(self, claims, rejected, summary_present):
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_judge_repair_claim_rounds") or 0), claims)
        self.assertEqual(int(entry.get("_judge_repair_rejected_rounds") or 0), rejected)
        if summary_present:
            self.assertEqual(entry.get("_judge_repair_last_summary"), "scn-a、scn-b")
        else:
            self.assertFalse(entry.get("_judge_repair_last_summary"))

    def test_unfreeze_clears_repair_counters(self):
        """人工解冻 → 三字段清零（同一原子写，与 _judge_rerun_count 成对）。"""
        self.sm.unfreeze_spec("demo-spec")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(
            int(entry.get("_scenario_repair_exhausted_rounds") or 0), 0)
        self._assert_counters(0, 0, summary_present=False)
        # 解冻重开修复通道：受理门放行（重新获得修复预算）
        pipe = _make_pipe(self.tmpdir, self.sm)
        pipe._apply_scenario_freeze = MagicMock(return_value={})
        pipe._run_three_stage_verification = MagicMock()
        rv = pipe._handle_scenario_repaired("demo-spec", "scenario-repaired", 0)
        self.assertTrue(rv)
        pipe._apply_scenario_freeze.assert_called_once()
        pipe._run_three_stage_verification.assert_called_once()

    def test_admin_reset_does_not_clear_repair_counters(self):
        """admin 处置复位（中间转换）不清零——生命周期累计语义。"""
        self.sm.update_spec("demo-spec", {
            "status": "testing", "error": None,
            "_dispatch_backoff_until": 0,
        })
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(
            int(entry.get("_scenario_repair_exhausted_rounds") or 0), 1)
        self._assert_counters(4, 2, summary_present=True)

    def test_verified_clears_repair_counters(self):
        """verified 落定清零三字段（_record_verdict_adoption verified 分支）。"""
        from core.pm_engine.verification.verdict_evidence import _record_verdict_adoption
        with patch("core.verify_report.record_verdict_round"), \
                patch("core.verify_report.verdict_failed_ids", return_value=[]), \
                patch("core.verify_report._sum_verify_chain_tokens", return_value=None):
            _record_verdict_adoption(self.pipe, "demo-spec", "verified", report={})
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(
            int(entry.get("_scenario_repair_exhausted_rounds") or 0), 0)
        self._assert_counters(0, 0, summary_present=False)


if __name__ == "__main__":
    unittest.main()
