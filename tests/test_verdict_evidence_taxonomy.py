"""add-verdict-evidence-taxonomy 单元测试（任务 4.1 / 4.2）。

覆盖：
  1. verdict_check 纯校验器：分类缺失→不合规；product-bug 误挂 warning 被强制
     failed；evidence 非空校验；旧格式 report.json（无 classification/evidence）
     仍能被 validate_report 标记为不合规（驱动补全）。
  2. pm_engine 采纳处：证据分类校验失败→重试→仍失败→blocked-env + 告警；
     product-bug 误挂 warning 被强制 failed 并标注 status_corrected；
     warning 连续 2 轮→triage 升级告警 + 下一轮优先复核注入（triage_recheck.json）。
  3. 消费方兼容：合成报告引用 evidence 而非重复渲染；parse_bugs 露出 classification；
     旧格式 report.json 解析不崩。
  4. 真实夹具（任务 4.2）：v2-config-page 00:14 报告（11 warning / 3 failed 无证据）
     —— 全部产出分类与证据后，属于产品缺陷的被强制 failed。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ───────────────────────── verdict_check 纯校验器 ─────────────────────────


class TestVerdictCheck(unittest.TestCase):
    """verdict_check.py 核心校验逻辑（不依赖 pm_engine / 文件 IO 为主）。"""

    def test_classification_missing_is_violation(self):
        from core.verdict_check import validate_report
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "fail", "assertion_results": []},
        ]}
        res = validate_report(report)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["violations"]), 1)
        self.assertEqual(res["violations"][0]["scenario_id"], "s1")

    def test_classification_illegal_value_is_violation(self):
        from core.verdict_check import validate_report
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "warning",
             "classification": "bogus", "evidence": {"first_failed_step": "x"}},
        ]}
        res = validate_report(report)
        self.assertFalse(res["ok"])
        self.assertIn("取值非法", res["violations"][0]["reason"])

    def test_pass_scenario_needs_no_classification(self):
        from core.verdict_check import validate_report
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "pass",
             "assertion_results": [{"type": "step", "pass": True}]},
        ]}
        res = validate_report(report)
        self.assertTrue(res["ok"])
        self.assertEqual(res["classified"], [])

    def test_valid_product_bug_passes(self):
        from core.verdict_check import validate_report
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "failed",
             "classification": "product-bug",
             "evidence": {"failed_assertions": [
                 {"type": "element_visible", "selector": ".x",
                  "expected": "可见", "actual": "不存在"}]},
             # add-interaction-contract-and-per-assert-triage：逐断言归因
             "assertion_triage": [
                 {"assertion": "element_visible .x",
                  "classification": "product-bug", "evidence": "元素不存在"}]},
        ]}
        res = validate_report(report)
        self.assertTrue(res["ok"])
        self.assertEqual(res["classified"], ["s1"])

    def test_evidence_empty_is_violation(self):
        from core.verdict_check import validate_report
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "fail",
             "classification": "test-defect", "evidence": {}},
        ]}
        res = validate_report(report)
        self.assertFalse(res["ok"])
        self.assertIn("evidence 为空", res["violations"][0]["reason"])

    def test_enforce_status_mapping_product_bug_mislabeled_warning(self):
        from core.verdict_check import enforce_status_mapping
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "warning",
             "classification": "product-bug",
             "evidence": {"first_failed_step": "x"}},
            {"scenario_id": "s2", "status": "warning",
             "classification": "env",
             "evidence": {"first_failed_step": "y"}},
        ]}
        mapped = enforce_status_mapping(report)
        corrected = {c["scenario_id"]: c["to_status"] for c in mapped["corrected"]}
        # product-bug 误挂 warning → 强制 failed；env 允许 warning 不动
        self.assertEqual(corrected.get("s1"), "failed")
        self.assertNotIn("s2", corrected)
        self.assertEqual(report["scenarios"][0]["status"], "failed")
        self.assertTrue(report["scenarios"][0].get("status_corrected"))
        self.assertEqual(report["scenarios"][1]["status"], "warning")

    def test_old_format_without_classification_fields_is_noncompliant(self):
        """旧格式 report.json（无 classification/evidence）必须被标记不合规，
        驱动框架补全，不能静默放行（spec 兼容性但需补全）。"""
        from core.verdict_check import validate_report
        old = {"scenarios": [
            {"scenario_id": "s1", "status": "fail",
             "assertion_results": [], "screenshots": []},
        ]}
        res = validate_report(old)
        self.assertFalse(res["ok"])


# ─────────────────────── pm_engine 采纳处集成 ───────────────────────


class _PMEngineBase(unittest.TestCase):
    """公共夹具：临时项目根 + PMEngine（不真实派发）。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.sm = StateMachine(self.project_root / "STATE.md", self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger)
        # 默认摆一个 testing 中的 spec
        real_handle = self.engine.handle_event
        self.engine.handle_event = MagicMock()
        try:
            self.sm.add_spec("v2-config-page", {"priority": 5})
            self.sm.transition("v2-config-page", "ready")
            self.sm.transition("v2-config-page", "implementing")
            self.sm.transition("v2-config-page", "implemented")
            self.sm.transition("v2-config-page", "testing")
        finally:
            self.engine.handle_event = real_handle

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed_report(self, report):
        vdir = self.project_root / ".fenix" / "verify-progress" / "v2-config-page"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8")

    def _alerts(self):
        from core.admin_store import AdminStore
        return AdminStore(self.project_root, self.logger).read_all()


class TestVerdictAdoption(_PMEngineBase):
    """采纳处：证据分类校验 / 映射重写 / warning 升级（任务 4.1）。"""

    def test_missing_classification_blocks_to_blocked_env_after_retry(self):
        """分类缺失→judge 重试一次→仍缺→blocked-env + 告警（design D2）。"""
        self._seed_report(_load_fixture("v2-config-page-report-0014.json"))
        # judge 重试仍返回「未补全」报告（与首次一致）
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=type("R", (), {"success": True, "error": None,
                                        "run_id": "j"})())
        ok = self.engine._verify_verdict_evidence("v2-config-page", retry_judge=True)
        self.assertFalse(ok)  # 校验器只判合规与否；blocked-env + 告警由调用方执行
        # 校验器确实重试了 judge 一次（首次不合规 + 一次重试）
        self.assertEqual(self.engine.agent_runner.run_planner.call_count, 1)
        # run_planner 返回值非 None 且 success → 校验器走完一轮重试路径（无异常）

    def test_product_bug_mislabeled_warning_forced_failed(self):
        """product-bug 误挂 warning：采纳处强制 failed + 标注 status_corrected。"""
        report = _load_fixture("v2-config-page-report-0014.json")
        mislabeled = None
        for sc in report["scenarios"]:
            if sc["status"] in ("fail", "warning"):
                sc["classification"] = "test-defect"
                sc["evidence"] = {"first_failed_step": "x"}
                # 逐断言归因（add-interaction-contract-and-per-assert-triage）：
                # 全部失败断言单独归类为非 product-bug，方可被豁免路径放行
                sc["assertion_triage"] = [{
                    "assertion": "step_failed",
                    "classification": "test-defect",
                    "evidence": "harness 缺陷",
                }]
        # 注入一个 LLM 漂移：product-bug 误挂 warning
        for sc in report["scenarios"]:
            if sc["status"] == "warning":
                sc["classification"] = "product-bug"
                sc["evidence"] = {"first_failed_step": "漂移悬置"}
                mislabeled = sc["scenario_id"]
                break
        assert mislabeled is not None
        self._seed_report(report)
        ok = self.engine._verify_verdict_evidence("v2-config-page", retry_judge=True)
        self.assertTrue(ok)
        reloaded = json.loads(
            (self.project_root / ".fenix" / "verify-progress" / "v2-config-page"
             / "report.json").read_text(encoding="utf-8"))
        drifted = next(s for s in reloaded["scenarios"]
                       if s.get("classification") == "product-bug")
        self.assertEqual(drifted["status"], "failed")
        self.assertTrue(drifted.get("status_corrected"))

    def test_warning_two_rounds_triggers_triage_alert_and_recheck_injection(self):
        """连续 2 轮 warning → triage 升级告警 + 下一轮优先复核注入（design D4/D5）。"""
        # 第 1 轮：2 个 warning 场景（flaky/env）
        r1 = {"scenarios": [
            {"scenario_id": "w1", "status": "warning", "classification": "flaky",
             "evidence": {"first_failed_step": "s1"}},
            {"scenario_id": "w2", "status": "warning", "classification": "env",
             "evidence": {"first_failed_step": "s2"}},
            {"scenario_id": "p1", "status": "pass",
             "assertion_results": [{"type": "step", "pass": True}]},
        ]}
        self._seed_report(r1)
        triage1 = self.engine._update_warning_streaks("v2-config-page")
        self.assertEqual(triage1, [])  # 第 1 轮不触发
        self.assertEqual(json.loads(
            (self.project_root / ".fenix" / "verify-progress" / "v2-config-page"
             / "warning_streaks.json").read_text())["w1"], 1)
        # 第 2 轮：同样的 warning 场景继续
        r2 = {"scenarios": [
            {"scenario_id": "w1", "status": "warning", "classification": "flaky",
             "evidence": {"first_failed_step": "s1"}},
            {"scenario_id": "w2", "status": "warning", "classification": "env",
             "evidence": {"first_failed_step": "s2"}},
        ]}
        self._seed_report(r2)
        triage2 = self.engine._update_warning_streaks("v2-config-page")
        self.assertEqual(set(triage2), {"w1", "w2"})
        # 触发升级告警
        self.engine._warning_stale_triage_alert("v2-config-page", triage2)
        alerts = [a for a in self._alerts()
                  if a.get("signal_type") == "warning_stale_triage"]
        self.assertEqual(len(alerts), 1)
        self.assertIn("w1", alerts[0]["description"])
        # 下一轮优先复核注入
        recheck = json.loads(
            (self.project_root / ".fenix" / "verify-progress" / "v2-config-page"
             / "triage_recheck.json").read_text())
        self.assertEqual(set(recheck), {"w1", "w2"})

    def test_pass_or_failed_clears_streak(self):
        """PASS / failed 场景清零连续计数（design D4）。"""
        r1 = {"scenarios": [
            {"scenario_id": "w1", "status": "warning", "classification": "flaky",
             "evidence": {"first_failed_step": "s1"}},
        ]}
        self._seed_report(r1)
        self.engine._update_warning_streaks("v2-config-page")  # 第1轮=1
        r2 = {"scenarios": [
            {"scenario_id": "w1", "status": "pass",
             "assertion_results": [{"type": "step", "pass": True}]},
        ]}
        self._seed_report(r2)
        self.engine._update_warning_streaks("v2-config-page")  # 清零
        streaks = json.loads(
            (self.project_root / ".fenix" / "verify-progress" / "v2-config-page"
             / "warning_streaks.json").read_text())
        self.assertEqual(streaks["w1"], 0)


# ─────────────────────── 消费方兼容（任务 3.1 / 4.2） ───────────────────────


class TestConsumerCompat(_PMEngineBase):
    """parse_bugs / 合成报告 引用 evidence（不重复渲染）。"""

    def test_parse_bugs_surfaces_classification(self):
        from core.dashboard.data import parse_bugs
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "fail",
             "classification": "product-bug",
             "evidence": {"failed_assertions": [
                 {"type": "element_visible", "selector": ".x",
                  "expected": "v", "actual": "a"}]},
             "assertion_results": [{"type": "element_visible", "pass": False,
                                    "message": "断言失败"}],
             "screenshots": ["/abs/s1.png"]},
        ]}
        self._seed_report(report)
        bugs = parse_bugs(self.project_root, "v2-config-page")
        self.assertEqual(len(bugs), 1)
        self.assertEqual(bugs[0]["classification"], "product-bug")
        self.assertIn("断言失败", bugs[0]["evidence"])

    def test_synthesized_report_references_evidence_not_rerender(self):
        from core.verify_report import synthesize_verification_report
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "fail", "classification": "product-bug",
             "evidence": {"failed_assertions": [
                 {"type": "element_visible", "selector": ".x",
                  "expected": "可见", "actual": "不存在"}]},
             "assertion_results": [{"type": "element_visible", "pass": False}],
             "screenshots": ["/abs/s1.png"]},
        ]}
        run_result = {"status": "bug-found", "spec": "v2-config-page", "bugs": [
            {"severity": "critical", "scenario_ids": ["s1"],
             "assertion_type": "element_visible",
             "description": "d", "root_cause": "rc",
             "evidence": {"message": "judge 侧稀疏证据"}},
        ]}
        self._seed_report(report)
        (self.project_root / ".fenix" / "verify-progress" / "v2-config-page"
         / ".fenix-run-result.json").write_text(
            json.dumps(run_result, ensure_ascii=False), encoding="utf-8")
        result = synthesize_verification_report(self.project_root, "v2-config-page")
        self.assertTrue(result["ok"])
        content = (self.project_root / "openspec" / "changes" / "v2-config-page"
                   / "verification-report.md").read_text(encoding="utf-8")
        # 引用 report.json 的结构化证据（selector/expected/actual），非 judge 稀疏证据
        self.assertIn("## 真实产品 Bug", content)
        self.assertIn(".x", content)
        self.assertIn("可见", content)
        self.assertIn("不存在", content)
        # 场景结果表含分类列
        self.assertIn("| 场景 | 状态 | 失败断言 | 分类 |", content)
        self.assertIn("product-bug", content)

    def test_old_format_report_parse_does_not_crash(self):
        """旧格式 report.json（无 classification/evidence）仍可由 parse_bugs 解析。"""
        from core.dashboard.data import parse_bugs
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "fail",
             "assertion_results": [], "screenshots": []},
        ]}
        self._seed_report(report)
        bugs = parse_bugs(self.project_root, "v2-config-page")
        # 旧格式（无 classification/evidence）仍能被解析，不崩溃；
        # 该 fail 场景按旧逻辑产 1 条 bug 行，classification 字段为 None（向后兼容）。
        self.assertEqual(len(bugs), 1)
        self.assertIsNone(bugs[0]["classification"])


# ─────────────────── 真实夹具：v2-config-page 00:14（任务 4.2） ───────────────────


class TestV2ConfigPageFixture(_PMEngineBase):
    """用真实 00:14 报告作夹具：11 warning / 3 failed 无证据 → 补全后产品缺陷被强制 failed。"""

    def test_all_nonpass_get_classified_and_product_bugs_forced_failed(self):
        from core.verdict_check import validate_report, enforce_status_mapping
        raw = _load_fixture("v2-config-page-report-0014.json")
        res = validate_report(raw)
        # 现状：3 failed + 11 warning 全无 classification/evidence → 不合规
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["violations"]), 14)

        # 模拟 judge 补全：给每个非 PASS 场景补 classification + evidence，
        # 其中 3 个 failed 均判为 product-bug（按 spec 现状「属于产品缺陷的被强制 failed」）
        enriched = json.loads(json.dumps(raw))
        for sc in enriched["scenarios"]:
            if sc["status"] in ("fail", "warning"):
                sc["classification"] = "product-bug"
                sc["evidence"] = {"failed_assertions": [
                    {"type": "step", "selector": "", "expected": "通过",
                     "actual": "未通过"}]}
                sc["assertion_results"] = [{"type": "step", "pass": False,
                                            "message": "断言失败"}]
                sc["screenshots"] = ["/abs/err.png"]
                # 逐断言归因（add-interaction-contract-and-per-assert-triage）：
                # 每条失败断言单独归类
                sc["assertion_triage"] = [{
                    "assertion": "step_failed",
                    "classification": "product-bug",
                    "evidence": "产品缺陷",
                }]
        res2 = validate_report(enriched)
        self.assertTrue(res2["ok"])

        mapped = enforce_status_mapping(enriched)
        forced = [c["scenario_id"] for c in mapped["corrected"]]
        # product-bug MUST → failed：原本 3 个 fail + 11 个 warning 共 14 个非 PASS
        # 全判 product-bug → 全部被强制为 failed（warning 也按映射重写）。
        failed = [s for s in enriched["scenarios"] if s["status"] == "failed"]
        self.assertEqual(len(failed), 14)
        self.assertTrue(all(f["classification"] == "product-bug" for f in failed))
        # 3 个原本 fail（非 failed）+ 11 个 warning 全部被强制改状态（corrected=14）
        self.assertEqual(len(forced), 14)


if __name__ == "__main__":
    unittest.main()
