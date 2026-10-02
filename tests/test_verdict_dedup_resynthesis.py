"""
批量归因查重拒绝 → 重合成回路（fix-verdict-dedup-resynthesis）

覆盖：
  1. 拒绝 → 落盘 violations + 重合成指令（含差异化素材）
  2. 重合成成功 → 回灌校验 → 采纳推进（cause=pass，清 violations/directive）
  3. 重合成再拒（连续 2 轮）→ blocked + admin 升级告警（MUST NOT 无限重试）
  4. frozen 让位 / 派发异常早退（不复读旧 report）/ 派发失败温和处置
  5. 重合成 prompt 注入：directive 段渲染（有/无文件两态）、rejection 段查重条目、
     judge 模板含归因文本契约段
  6. 集成链路：16:39 事故形态（模板归因 → 重合成差异化 → 采纳推进）；
     15:53 形态（真偷懒 → 重合成仍同文 → blocked 升级）
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.pm_engine.engine import PMEngine
from core.state_machine import StateMachine
from core.agent_runner.runner import AgentRunResult


class _FakeLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def debug(self, *a, **k): pass


def _same_text_scenario(sid, cls="env"):
    """模板偷懒形态：归因逐字同文（含步骤序号与断言引用）。"""
    return {
        "scenario_id": sid, "status": "fail", "classification": cls,
        "evidence": {"first_failed_step": "步骤1: 应用初始化失败（error 截断）"},
        "assertion_triage": [{
            "assertion": "应用可访问", "classification": cls,
            "evidence": "错误信息（截断）: 断言未通过",
        }],
    }


def _differentiated_scenario(sid, idx, cls="env"):
    """重合成产物形态：归因引用本场景局部数据（步骤序号/断言 label/完整 error）。"""
    return {
        "scenario_id": sid, "status": "fail", "classification": cls,
        "evidence": {
            "first_failed_step":
                f"步骤{idx + 1}: 应用初始化失败，场景 {sid} 在步骤 {idx + 1} 首次失败",
        },
        "assertion_triage": [{
            "assertion": f"断言-{idx}", "classification": cls,
            "evidence": f"场景 {sid} 断言 {idx} 的完整错误文本（未截断）",
        }],
    }


class ResynthesisHarness(unittest.TestCase):
    """重合成闭环测试基座：真实 PMEngine + StateMachine + mock agent_runner。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", _FakeLogger())
        self.agent_runner = mock.MagicMock()
        self.config = {}
        self.engine = PMEngine(self.sm, self.agent_runner, self.config,
                               self.tmpdir, _FakeLogger())
        self.sm.add_spec("demo", {"priority": 5})
        self.sm.update_spec("demo", {"status": "testing"})
        self.vp = self.tmpdir / ".fenix" / "verify-progress" / "demo"

    def _write_report(self, scenarios):
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "report.json").write_text(
            json.dumps({"scenarios": scenarios}, ensure_ascii=False),
            encoding="utf-8")

    def _read_report(self):
        return json.loads((self.vp / "report.json").read_text(encoding="utf-8"))

    def _success_result(self):
        return AgentRunResult("resynth-test", "demo", "planner-judge",
                              success=True, duration_seconds=0.0)

    def _escalation_signals(self):
        calls = []
        for c in self.engine._send_human_escalation_alert.call_args_list \
                if hasattr(self.engine._send_human_escalation_alert,
                           "call_args_list") else []:
            calls.append(c)
        return calls


# ── 1. 拒绝 → 落盘 violations + directive ──────────────────────────


class TestRejectionWritesArtifacts(ResynthesisHarness):
    def test_rejection_writes_violations_and_directive(self):
        """查重拒绝 → verdict_violations.json + directive（含差异化素材）落盘。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])
        seen = {}

        def _side_effect(spec, mode):
            # 派发瞬间取证：违规清单与指令须已在盘上（重合成 prompt 注入源）
            seen["violations"] = (self.vp / "verdict_violations.json").exists()
            seen["directive"] = \
                (self.vp / "dedup_resynthesis_directive.json").exists()
            self._write_report([
                _differentiated_scenario(f"s{i}", i) for i in range(3)])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect

        result = self.engine._verification._handle_attr_dedup_rejection(
            "demo", self._read_report(),
            [{"scenario_ids": ["s0", "s1", "s2"], "reason": "3 个场景归因文本完全相同"}])

        # 派发前落盘（重合成 prompt 注入源在，重合成才可能差异化）
        self.assertTrue(seen["violations"], "违规清单应落盘")
        self.assertTrue(seen["directive"], "重合成指令应落盘")
        # 重合成 run 已派发一次（产物差异化 → 采纳，无升级）
        self.assertEqual(self.agent_runner.run_planner.call_count, 1)
        self.assertTrue(result["ok"])
        # 采纳后清理
        self.assertFalse((self.vp / "verdict_violations.json").exists())
        self.assertFalse((self.vp / "dedup_resynthesis_directive.json").exists())


# ── 2. 重合成成功 → 回灌采纳 ────────────────────────────────────────


class TestResynthesisAdopts(ResynthesisHarness):
    def test_resynthesis_success_adopts_and_clears(self):
        """重合成产物差异化 → 回灌校验通过 → 采纳推进（cause=pass）。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])

        def _side_effect(spec, mode):
            # 重合成 judge「写回」差异化归因（各场景引用局部数据）
            self._write_report([
                _differentiated_scenario(f"s{i}", i) for i in range(3)])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect

        result = self.engine._verification._handle_attr_dedup_rejection(
            "demo", self._read_report(),
            [{"scenario_ids": ["s0", "s1", "s2"], "reason": "3 个场景归因文本完全相同"}])

        self.assertTrue(result["ok"])
        self.assertEqual(result["cause"], "pass")
        # 合规采纳：清 violations + 清 directive
        self.assertFalse((self.vp / "verdict_violations.json").exists())
        self.assertFalse((self.vp / "dedup_resynthesis_directive.json").exists())
        # 状态机不写 blocked（保持 testing，由调用方推进）
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "testing")
        # report.json 保留差异化产物
        report = self._read_report()
        self.assertTrue(report["scenarios"][0]["evidence"]["first_failed_step"]
                        .startswith("步骤1"))


# ── 3. 重合成再拒 → blocked + 告警 ──────────────────────────────────


class TestResynthesisEscalates(ResynthesisHarness):
    def test_two_resynthesis_rejections_escalate_blocked(self):
        """连续 2 轮重合成仍同文 → blocked + admin 告警，不无限重试。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])

        def _side_effect(spec, mode):
            # 重合成 judge 仍写回同文（真偷懒修不好）
            self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect

        with mock.patch.object(self.engine, "_send_human_escalation_alert") as alert:
            result = self.engine._verification._handle_attr_dedup_rejection(
                "demo", self._read_report(),
                [{"scenario_ids": ["s0", "s1", "s2"],
                  "reason": "3 个场景归因文本完全相同"}])

        # MUST NOT 无限重试：原始拒绝派发重合成 1 轮、重合成 #1 再拒派发第 2 轮、
        # 第 2 轮仍拒 → 升级（不再派第 3 轮）——call_count == 2 即预算生效
        self.assertEqual(self.agent_runner.run_planner.call_count, 2)
        # 升级：blocked + 告警 + error 带违规摘要
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("批量归因查重连续", entry.get("error") or "")
        alert.assert_called_once()
        kwargs = alert.call_args.kwargs or {}
        self.assertEqual(kwargs.get("signal_type"),
                         "verdict_dedup_resynthesis_exhausted")
        self.assertEqual(kwargs.get("severity"), "critical")

    def test_single_rejection_then_resynthesized_ok_no_escalation(self):
        """重合成 1 轮即修复 → 不升级（预算未触发）。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])

        def _side_effect(spec, mode):
            self._write_report([
                _differentiated_scenario(f"s{i}", i) for i in range(3)])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect
        with mock.patch.object(self.engine, "_send_human_escalation_alert") as alert:
            result = self.engine._verification._handle_attr_dedup_rejection(
                "demo", self._read_report(),
                [{"scenario_ids": ["s0", "s1", "s2"], "reason": "同文"}])
        self.assertTrue(result["ok"])
        alert.assert_not_called()


# ── 4. 让位 / 异常 / 派发失败 语义化分支 ────────────────────────────


class TestResynthesisDispatchBranches(ResynthesisHarness):
    def test_frozen_yields_without_state_write(self):
        """frozen 门拦截 → 让位（不写 blocked、不发告警）。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])
        self.agent_runner.run_planner.return_value = AgentRunResult(
            "t", "demo", "planner-judge", success=False, duration_seconds=0.0,
            error="spec frozen — 人工冻结")
        with mock.patch.object(self.engine, "_send_human_escalation_alert") as alert:
            result = self.engine._verification._handle_attr_dedup_rejection(
                "demo", self._read_report(),
                [{"scenario_ids": ["s0", "s1", "s2"], "reason": "同文"}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["cause"], "dispatch_frozen")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "testing", "frozen 让位不写状态")
        alert.assert_not_called()

    def test_cancel_yields(self):
        """取消旗标拦截 → 让位。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])
        self.agent_runner.run_planner.return_value = AgentRunResult(
            "t", "demo", "planner-judge", success=False, duration_seconds=0.0,
            error="cancelled by admin", cancelled=True)
        result = self.engine._verification._handle_attr_dedup_rejection(
            "demo", self._read_report(),
            [{"scenario_ids": ["s0", "s1", "s2"], "reason": "同文"}])
        self.assertEqual(result["cause"], "dispatch_cancelled")
        self.assertEqual(self.sm.read_one("demo")["status"], "testing")

    def test_dispatch_exception_early_exit_no_old_report_reread(self):
        """派发异常 → dispatch_exception 早退（禁止复读旧 report 打假 ERROR）。"""
        original = [{"scenario_id": "s0", "status": "fail", "classification": "env",
                     "evidence": {"first_failed_step": "旧轮残留"}}]
        self._write_report(original)
        self.agent_runner.run_planner.side_effect = RuntimeError("gateway boom")
        result = self.engine._verification._handle_attr_dedup_rejection(
            "demo", self._read_report(),
            [{"scenario_ids": ["s0"], "reason": "同文"}])
        self.assertEqual(result["cause"], "dispatch_exception")
        self.assertIn("gateway boom", result["dispatch_error"])
        # report.json 未被重读/改写（保持旧内容，无「重试后仍不合规」假 ERROR）
        report = self._read_report()
        self.assertEqual(report["scenarios"][0]["evidence"]["first_failed_step"],
                         "旧轮残留")
        self.assertEqual(self.sm.read_one("demo")["status"], "testing")

    def test_dispatch_failed_soft_handling(self):
        """派发失败（非 frozen/取消）→ dispatch_failed 温和处置。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])
        self.agent_runner.run_planner.return_value = AgentRunResult(
            "t", "demo", "planner-judge", success=False, duration_seconds=0.0,
            error="网关拒绝: budget exhausted")
        result = self.engine._verification._handle_attr_dedup_rejection(
            "demo", self._read_report(),
            [{"scenario_ids": ["s0", "s1", "s2"], "reason": "同文"}])
        self.assertEqual(result["cause"], "dispatch_failed")
        self.assertEqual(self.sm.read_one("demo")["status"], "testing")

    def test_report_missing_after_resynthesis(self):
        """重合成成功但产物不可读 → report_missing（fail-closed，非违规）。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(3)])

        def _side_effect(spec, mode):
            (self.vp / "report.json").unlink(missing_ok=True)
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect
        result = self.engine._verification._handle_attr_dedup_rejection(
            "demo", self._read_report(),
            [{"scenario_ids": ["s0", "s1", "s2"], "reason": "同文"}])
        self.assertEqual(result["cause"], "report_missing")


# ── 5. 重合成 prompt 注入 ──────────────────────────────────────────


class TestResynthesisPromptInjection(ResynthesisHarness):
    def _directive_section(self):
        return self.engine._verification._pm.agent_runner  # noqa: 占位防误用

    def _builder(self):
        from core.agent_runner.prompt_builder import PromptBuilder
        return PromptBuilder(self.engine)

    def test_directive_section_rendered_when_present(self):
        """directive 文件存在 → 注入段含被拒场景清单与差异化素材。"""
        self.vp.mkdir(parents=True, exist_ok=True)
        directive = {
            "spec": "demo", "rejection_round": 1, "resynthesis_attempts": 1,
            "violations": [{"scenario_ids": ["s0", "s1", "s2"],
                            "reason": "3 个场景归因文本完全相同"}],
            "scenarios": [
                {"scenario_id": "s0", "classification": "env",
                 "status": "fail", "first_failed_step": "步骤1: 初始化失败",
                 "failed_step_number": "1", "assertion_labels": ["应用可访问"]},
                {"scenario_id": "s1", "classification": "env",
                 "status": "fail", "first_failed_step": "步骤2: 初始化失败",
                 "failed_step_number": "2", "assertion_labels": ["筛选可用"]},
            ],
        }
        (self.vp / "dedup_resynthesis_directive.json").write_text(
            json.dumps(directive, ensure_ascii=False), encoding="utf-8")
        section = self._builder()._resynthesis_directive_section("demo")
        self.assertIn("轻量重合成", section)
        self.assertIn("s0", section)
        self.assertIn("步骤1: 初始化失败", section)
        self.assertIn("failed_step_number" if False else "失败步骤序号", section)
        self.assertIn("MUST NOT 套用共享模板串", section)

    def test_directive_section_empty_when_missing(self):
        """directive 文件缺失 → 空串（普通裁决轮零注入）。"""
        section = self._builder()._resynthesis_directive_section("demo")
        self.assertEqual(section, "")

    def test_directive_section_empty_when_corrupt(self):
        """directive 文件损坏 → 空串（fail-open）。"""
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "dedup_resynthesis_directive.json").write_text(
            "{not json", encoding="utf-8")
        section = self._builder()._resynthesis_directive_section("demo")
        self.assertEqual(section, "")

    def test_rejection_section_renders_dedup_entries(self):
        """rejection 段对查重违规条目（scenario_ids 列表）渲染 + 重合成纪律。"""
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "verdict_violations.json").write_text(
            json.dumps([{"scenario_ids": ["s0", "s1", "s2"],
                         "reason": "3 个场景归因文本完全相同"}],
                       ensure_ascii=False), encoding="utf-8")
        section = self._builder()._verdict_rejection_section("demo")
        self.assertIn("批量归因查重违规", section)
        self.assertIn("s0、s1、s2", section)
        self.assertIn("轻量重合成", section)
        self.assertIn("MUST NOT 套用共享模板串", section)

    def test_rejection_section_scenario_entry_unchanged(self):
        """rejection 段对既有单场景违规条目（scenario_id）渲染保持。"""
        self.vp.mkdir(parents=True, exist_ok=True)
        (self.vp / "verdict_violations.json").write_text(
            json.dumps([{"scenario_id": "s5", "status": "fail",
                         "reason": "evidence 为空"}],
                       ensure_ascii=False), encoding="utf-8")
        section = self._builder()._verdict_rejection_section("demo")
        self.assertIn("场景 `s5`", section)
        self.assertNotIn("批量归因查重违规", section)

    def test_judge_template_has_attribution_contract(self):
        """agents/planner-judge.md 含归因文本契约段（事前预防）。"""
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR
        template = (AGENT_PROMPT_DIR / "planner-judge.md").read_text(
            encoding="utf-8")
        self.assertIn("归因文本契约", template)
        self.assertIn("禁止把 error 截断成同一段", template)
        self.assertIn("逐场景引用局部数据代价为零", template)


# ── 6. 集成链路（5.1）：事故形态回放 ────────────────────────────────


class TestResynthesisIncidentReplay(ResynthesisHarness):
    def test_incident_1639_resynthesized_then_adopted(self):
        """16:39 形态：模板归因被拒 → 重合成差异化 → 采纳推进（不自锁）。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(5)])

        def _side_effect(spec, mode):
            self._write_report([
                _differentiated_scenario(f"s{i}", i) for i in range(5)])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect
        result = self.engine._verification._handle_attr_dedup_rejection(
            "demo", self._read_report(),
            [{"scenario_ids": [f"s{i}" for i in range(5)],
              "reason": "5 个场景归因文本完全相同"}])
        self.assertTrue(result["ok"])
        self.assertEqual(result["cause"], "pass")
        # 不自锁：spec 保持 testing 由调用方推进（非 blocked、非静默挂起）
        self.assertEqual(self.sm.read_one("demo")["status"], "testing")
        # 全程不触发全量验证重跑：只派发了 1 轮重合成 judge
        self.assertEqual(self.agent_runner.run_planner.call_count, 1)

    def test_incident_1553_lazy_template_escalated(self):
        """15:53 形态：真偷懒（23 连同文）→ 重合成仍同文 → blocked 升级。"""
        self._write_report([_same_text_scenario(f"s{i}") for i in range(23)])

        def _side_effect(spec, mode):
            self._write_report([_same_text_scenario(f"s{i}") for i in range(23)])
            return self._success_result()

        self.agent_runner.run_planner.side_effect = _side_effect
        with mock.patch.object(self.engine, "_send_human_escalation_alert") as alert:
            result = self.engine._verification._handle_attr_dedup_rejection(
                "demo", self._read_report(),
                [{"scenario_ids": [f"s{i}" for i in range(23)],
                  "reason": "23 个场景归因文本完全相同"}])
        self.assertFalse(result["ok"])
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "blocked", "真偷懒必须升级而非无限重试")
        self.assertIn("违规摘要", entry.get("error") or "")
        alert.assert_called_once()


# ── 7. in-place retry 派发前状态复查（fix-verdict-dedup-resynthesis D4）──


class TestRetryStatusRecheck(unittest.TestCase):
    """_should_give_up_before_retry 扩展：status 预期态 + frozen/hold + fail-open。"""

    def _runner(self, entry):
        from core.agent_runner import AgentRunner
        runner = AgentRunner.__new__(AgentRunner)
        runner.worktree_manager = mock.MagicMock()
        runner.worktree_manager.has_active_lock.return_value = False
        sm = mock.MagicMock()
        sm.read_one.return_value = entry
        runner.state_machine = sm
        runner.logger = mock.MagicMock()
        return runner

    def test_judge_blocked_yields(self):
        """judge 预期 testing，spec 已 blocked → 放弃重试让位。"""
        r = self._runner({"status": "blocked"})
        self.assertTrue(r._should_give_up_before_retry("s", "planner-judge"))

    def test_judge_testing_retries(self):
        """judge 预期 testing，spec 仍 testing → 照常重试（正常退避不受影响）。"""
        r = self._runner({"status": "testing"})
        self.assertFalse(r._should_give_up_before_retry("s", "planner-judge"))

    def test_implementer_implementing_retries(self):
        """implementer 预期 implementing，spec 仍 implementing → 照常重试。"""
        r = self._runner({"status": "implementing"})
        self.assertFalse(r._should_give_up_before_retry("s", "implementer"))

    def test_implementer_testing_yields(self):
        """implementer 预期 implementing，spec 被移出（如被转 testing）→ 让位。"""
        r = self._runner({"status": "testing"})
        self.assertTrue(r._should_give_up_before_retry("s", "implementer"))

    def test_frozen_yields(self):
        """frozen 让位（既有语义保持）。"""
        r = self._runner({"frozen": True, "status": "blocked"})
        self.assertTrue(r._should_give_up_before_retry("s", "planner-judge"))

    def test_cancelled_hold_yields(self):
        """_cancelled_hold 取消保持态 → 让位（自动重派不得复活有意保持的 spec）。"""
        r = self._runner({"_cancelled_hold": True, "status": "blocked"})
        self.assertTrue(r._should_give_up_before_retry("s", "planner-judge"))

    def test_checker_exception_fail_open(self):
        """检查自身异常 → fail-open（返回 False，保持既有重试语义）。"""
        r = self._runner({})
        r.state_machine.read_one.side_effect = RuntimeError("state read boom")
        self.assertFalse(r._should_give_up_before_retry("s", "planner-judge"))

    def test_unmapped_agent_type_no_status_judgment(self):
        """未映射 agent_type（如 administrator）不判 status——保持现状重试语义。"""
        r = self._runner({"status": "blocked"})
        self.assertFalse(r._should_give_up_before_retry("s", "administrator"))


class TestInPlaceRetryYields(ResynthesisHarness):
    """4.2 接线：退避结束后重派前复查命中 → 返回语义化失败，不再重派。"""

    def _runner(self, entry):
        from core.agent_runner import AgentRunner
        from tests.helpers import FakeLogger as FL
        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {
            "llm": {"providers": [
                {"name": "inferaiapi.com", "baseurl": "https://a.com",
                 "apikey": "k1"},
            ]},
            "agents": {
                "models": {"planner-judge": {
                    "provider": "inferaiapi.com", "model": "m1"}},
                "max_retries": 2,
                "transient_backoff_schedule": "1",
            },
        }
        wt = self.tmpdir / "wt"
        wt.mkdir(parents=True, exist_ok=True)
        runner.worktree_manager = mock.MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.has_active_lock.return_value = False
        runner.state_machine = mock.MagicMock()
        runner.state_machine.read_one.return_value = entry
        runner.project_root = self.tmpdir
        runner.logger = FL()
        runner._running_agents = {}
        runner._daily_run_count = 0
        runner._provider_circuit._daily_reset_date = None
        runner._provider_circuit._daily_provider_attempts = {}
        runner._provider_circuit._daily_provider_warned = {}
        runner._provider_circuit.provider_circuits = {}
        runner.__dict__["_v2_server_instance"] = mock.MagicMock()
        runner._v2_server._v2_inject_env.return_value = {}
        runner.__dict__["_token_accountant_instance"] = mock.MagicMock()
        runner._build_prompt = lambda *a, **k: "test prompt"
        (self.tmpdir / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        return runner

    class _TransientError(Exception):
        def __init__(self, msg):
            super().__init__(msg)
            self.stderr_lines = ["connection reset by peer"]
            self.exit_code = 1
            self.has_result = False

    def test_provider_transient_then_blocked_yields_no_respawn(self):
        """judge 瞬断进入退避，期间 spec 被置 blocked → 让位（无新 run 派发）。"""
        from core.agent_runner import AgentRunner  # noqa: F401
        runner = self._runner({"status": "blocked"})
        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            raise self._TransientError("connection reset by peer")

        runner._run_claude = fake_run_claude
        with mock.patch("time.sleep", lambda _: None):
            result = runner._execute_agent("spec-x", "planner-judge", "run-y")

        # 只派发 1 次：退避结束复查命中让位，不重派（不产生新的 transient_retry 轮）
        self.assertEqual(calls["n"], 1)
        self.assertFalse(result.success)
        self.assertIn("[retry-yielded]", result.error or "")
        self.assertIn("已被接管", result.error or "")

    def test_provider_transient_testing_keeps_retrying(self):
        """judge 瞬断进入退避，期间 spec 仍 testing → 照常原地重试。"""
        from core.agent_runner.prompt_builder import planner_result_path
        runner = self._runner({"status": "testing"})
        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise self._TransientError("connection reset by peer")
            # 退避重试轮：成功前写合法产物（planner 产物硬门要求）
            p = planner_result_path(runner.project_root, "spec-x", "planner-judge")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"status": "verified", "summary": "ok"}),
                         encoding="utf-8")
            return ("done", 1, "sess", _usage_ok())

        runner._run_claude = fake_run_claude
        with mock.patch("time.sleep", lambda _: None):
            result = runner._execute_agent("spec-x", "planner-judge", "run-y")

        self.assertGreater(calls["n"], 1, "testing 态正常退避重试不回退")
        self.assertTrue(result.success)


def _usage_ok() -> dict:
    return {"input_tokens": 1, "output_tokens": 2,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "cost_usd": None}


if __name__ == "__main__":
    unittest.main()
