"""judge 效率治理（2026-09-06）回归测试：全绿快道 / 跨轮裁决缓存 / 重试定向纪律。

覆盖（原地修改，无 SPEC）：
A. 全绿快道 _all_green_fast_path：0 失败 0 警告 → 合成 verified 结果文件 +
   mechanical-all-green stub；有失败/警告 → None（走常规 judge）
E. 跨轮裁决缓存：指纹稳定且对失败变化敏感、缓存读写 roundtrip、
   _verdict_cache_section 命中注入 / 未命中零注入
D. _verdict_rejection_section 强化：重试定向纪律文案在位
B/C. 模板守卫：agents/planner-judge.md 效率纪律 / 复现预算分级 / 不写 md /
   重试定向 / 跨轮复用各强制段在位（防漂移）
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.prompt_builder import PromptBuilder
from core.pm_engine.verification import VerificationPipeline
from core.verdict_check import (
    load_verdict_cache,
    save_verdict_cache,
    scenario_fingerprint,
)


def _mk_scenario(sid, status, failed=None, classification=None):
    sc = {
        "scenario_id": sid,
        "status": status,
        "assertion_results": [
            {"type": "exit_code", "layer": 1, "expected": 0,
             "actual": 1, "pass": False}
        ] + (failed or []),
    }
    if classification:
        sc["classification"] = classification
        sc["evidence"] = {"first_failed_step": "步骤1 失败"}
        sc["assertion_triage"] = [
            {"assertion": "exit_code 0", "classification": classification,
             "evidence": "命令解析错误"}]
    return sc


class TestScenarioFingerprint(unittest.TestCase):
    def test_stable_for_identical_failure(self):
        a = _mk_scenario("s1", "fail")
        b = _mk_scenario("s1", "fail")
        self.assertEqual(scenario_fingerprint(a), scenario_fingerprint(b))

    def test_sensitive_to_failure_change(self):
        a = _mk_scenario("s1", "fail")
        b = _mk_scenario("s1", "fail", failed=[
            {"type": "exit_code", "layer": 1, "expected": 0, "actual": 2,
             "pass": False}])
        self.assertNotEqual(scenario_fingerprint(a), scenario_fingerprint(b))

    def test_ignores_judge_products(self):
        """judge 产物（evidence/triage）不参与指纹——轮间重写不影响命中。"""
        a = _mk_scenario("s1", "fail", classification="test-defect")
        b = _mk_scenario("s1", "fail", classification="product-bug")
        self.assertEqual(scenario_fingerprint(a), scenario_fingerprint(b))

    def test_malformed_fails_open(self):
        """真正畸形输入（非 dict）fail-open 返回空串；退化但合法输入正常出指纹。"""
        self.assertEqual(scenario_fingerprint(None), "")
        self.assertEqual(scenario_fingerprint("not-a-dict"), "")
        # 无失败断言的退化场景：合法出指纹（scenario_id 在 payload 内防跨场景碰撞）
        self.assertTrue(scenario_fingerprint({"scenario_id": "x"}))


class TestVerdictCacheRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pr = Path(self.tmp)

    def test_save_load_roundtrip(self):
        cache = {"s1": {"fingerprint": "abc", "classification": "test-defect",
                        "evidence": {"x": 1}, "assertion_triage": []}}
        save_verdict_cache(self.pr, "spec", cache)
        self.assertEqual(load_verdict_cache(self.pr, "spec"), cache)

    def test_missing_returns_empty(self):
        self.assertEqual(load_verdict_cache(self.pr, "ghost"), {})


class TestAllGreenFastPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pr = Path(self.tmp)
        self.pipeline = VerificationPipeline.__new__(VerificationPipeline)
        self.pipeline._pm = SimpleNamespace(
            project_root=self.pr, logger=MagicMock())

    def _report(self, passed, warnings, total):
        return {"summary": {"passed": passed, "warnings": warnings,
                            "total": total}}

    def test_all_green_returns_stub_and_writes_result(self):
        result = self.pipeline._all_green_fast_path("s1", self._report(16, 0, 16), 0)
        self.assertIsNotNone(result)
        self.assertEqual(result.run_id, "mechanical-all-green")
        self.assertTrue(result.success)
        payload = json.loads((self.pr / ".fenix" / "verify-progress" / "s1"
                              / ".fenix-run-result.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "verified")
        self.assertTrue(payload["mechanical"])

    def test_failures_return_none(self):
        self.assertIsNone(
            self.pipeline._all_green_fast_path("s1", self._report(9, 0, 16), 5))

    def test_warnings_return_none(self):
        self.assertIsNone(
            self.pipeline._all_green_fast_path("s1", self._report(14, 2, 16), 0))

    def test_overwrites_stale_result_file(self):
        """上一轮 judge 残留结果必须被覆盖（防 _read_planner_result 读旧裁决）。"""
        stale = (self.pr / ".fenix" / "verify-progress" / "s1"
                 / ".fenix-run-result.json")
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text('{"status": "bug-found"}', encoding="utf-8")
        self.pipeline._all_green_fast_path("s1", self._report(16, 0, 16), 0)
        payload = json.loads(stale.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "verified")


class TestVerdictCacheSection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pr = Path(self.tmp)
        self.pb = PromptBuilder(SimpleNamespace(project_root=self.pr))

    def _write_report(self, scenarios):
        d = self.pr / ".fenix" / "verify-progress" / "spec"
        d.mkdir(parents=True, exist_ok=True)
        (d / "report.json").write_text(
            json.dumps({"scenarios": scenarios}, ensure_ascii=False),
            encoding="utf-8")

    def test_hit_injects_reuse_list(self):
        sc = _mk_scenario("s1", "fail", classification="test-defect")
        self._write_report([sc])
        save_verdict_cache(self.pr, "spec", {
            "s1": {"fingerprint": scenario_fingerprint(sc),
                   "classification": "test-defect",
                   "evidence": sc["evidence"],
                   "assertion_triage": sc["assertion_triage"]}})
        section = self.pb._verdict_cache_section("spec")
        self.assertIn("跨轮已裁决场景", section)
        self.assertIn("`s1`", section)
        self.assertIn("test-defect", section)

    def test_fingerprint_miss_no_injection(self):
        sc = _mk_scenario("s1", "fail", failed=[
            {"type": "exit_code", "layer": 1, "expected": 0, "actual": 9,
             "pass": False}])
        self._write_report([sc])
        save_verdict_cache(self.pr, "spec", {
            "s1": {"fingerprint": "stale-fp", "classification": "test-defect",
                   "evidence": {}, "assertion_triage": []}})
        self.assertEqual(self.pb._verdict_cache_section("spec"), "")

    def test_no_cache_zero_injection(self):
        self._write_report([_mk_scenario("s1", "fail")])
        self.assertEqual(self.pb._verdict_cache_section("spec"), "")


class TestRejectionSectionDiscipline(unittest.TestCase):
    def test_retry_scope_discipline_present(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pr = Path(tmp)
        d = pr / ".fenix" / "verify-progress" / "spec"
        d.mkdir(parents=True, exist_ok=True)
        (d / "verdict_violations.json").write_text(json.dumps([
            {"scenario_id": "s1", "status": "fail", "reason": "缺 assertion_triage"},
        ]), encoding="utf-8")
        pb = PromptBuilder(SimpleNamespace(project_root=pr))
        section = pb._verdict_rejection_section("spec")
        self.assertIn("重试定向纪律", section)
        self.assertIn("原样保留", section)
        self.assertIn("禁止重新复现", section)


class TestJudgeTemplateGuard(unittest.TestCase):
    """模板守卫：效率纪律各强制段在位（防后续编辑漂移）。"""

    def setUp(self):
        self.text = Path(__file__).resolve().parent.parent.joinpath(
            "agents", "planner-judge.md").read_text(encoding="utf-8")

    def test_efficiency_rules_present(self):
        self.assertIn("效率纪律", self.text)
        self.assertIn("最终回复 ≤10 行", self.text)
        self.assertIn("不写 verification-report.md", self.text)

    def test_reproduction_tiering_present(self):
        self.assertIn("复现预算分级", self.text)
        self.assertIn("Bash 复现 ≤3 次", self.text)

    def test_retry_scope_and_cache_rules_present(self):
        self.assertIn("重试定向纪律", self.text)
        self.assertIn("跨轮已裁决场景", self.text)


if __name__ == "__main__":
    unittest.main()
