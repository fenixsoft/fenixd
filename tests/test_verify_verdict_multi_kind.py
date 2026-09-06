"""multi-kind verdict 链回归夹具（multi-kind-report-compat：verdict 链零改动回归）。

不改 verdict_check.py 的前提下，验证 cli/api 失败场景走与 web 同规则的
三个不变量：
  1. 非 PASS 场景缺 assertion_triage → 判「逐断言归因违规」（与 web 同规则）
  2. 全失败断言非 product-bug 才可豁免；单条 product-bug 断言阻止场景级豁免
  3. CLI/API 断言失败附命令输出/HTTP 响应体证据（非截图）→ 证据合规检查通过，
     不因缺截图判 inconclusive
"""

import unittest

from core.verdict_check import (
    triage_violation,
    has_product_bug_assertion,
    is_scenario_exemptible,
    validate_report,
)


# ── 1. 非 PASS 场景缺 triage 判违规（与 web 同规则）────────────────

class TestMultiKindTriageRequirement(unittest.TestCase):
    def test_cli_failure_missing_triage_violation(self):
        """cli 场景 status_code/output_match 断言失败且无 assertion_triage → 违规。"""
        scenario = {
            "scenario_id": "cli-1", "status": "fail",
            "classification": "product-bug",
            "evidence": {"failed_assertions": [
                {"type": "output_match", "stream": "stdout",
                 "expected": "ok", "actual": "boom"}]},
            # 无 assertion_triage
        }
        violation = triage_violation(scenario)
        self.assertIsNotNone(violation)
        self.assertIn("assertion_triage", violation)

    def test_api_failure_missing_triage_violation(self):
        """api 场景 status_code 断言失败且无 triage → 违规（与 web 场景同规则）。"""
        scenario = {
            "scenario_id": "api-1", "status": "fail",
            "classification": "test-defect",
            "evidence": {"failed_assertions": [
                {"type": "status_code", "expected": 201, "actual": 500}]},
        }
        self.assertIsNotNone(triage_violation(scenario))

    def test_cli_failure_with_triage_ok(self):
        scenario = {
            "scenario_id": "cli-2", "status": "fail",
            "classification": "product-bug",
            "evidence": {"failed_assertions": [
                {"type": "output_match", "expected": "ok", "actual": "boom"}]},
            "assertion_triage": [
                {"assertion": "output_match",
                 "classification": "product-bug",
                 "evidence": "命令输出为 'boom'，期望含 'ok'"},
            ],
        }
        self.assertIsNone(triage_violation(scenario))


# ── 2. product-bug 拦截豁免 ────────────────────────────────────────

class TestMultiKindProductBugExemption(unittest.TestCase):
    def test_cli_all_non_product_bug_exemptible(self):
        """cli 场景全失败断言归类 test-defect（无 product-bug）→ 场景级可豁免。"""
        scenario = {
            "scenario_id": "cli-3", "status": "fail",
            "classification": "test-defect",
            "assertion_triage": [
                {"assertion": "exit_code", "classification": "test-defect",
                 "evidence": "期望 0 实际 1（环境差异）"},
            ],
        }
        self.assertFalse(has_product_bug_assertion(scenario))
        self.assertTrue(is_scenario_exemptible(scenario))

    def test_api_single_product_bug_blocks_exemption(self):
        """api 场景单条 product-bug 断言阻止场景级豁免（不因其余 test-defect 放行）。"""
        scenario = {
            "scenario_id": "api-2", "status": "fail",
            "classification": "product-bug",
            "assertion_triage": [
                {"assertion": "status_code", "classification": "product-bug",
                 "evidence": "GET /api/specs 期望 200 实际 500"},
                {"assertion": "latency_under", "classification": "test-defect",
                 "evidence": "慢环境"},
            ],
        }
        self.assertTrue(has_product_bug_assertion(scenario))
        self.assertFalse(is_scenario_exemptible(scenario))

    def test_cli_layer3_failure_triage_product_bug(self):
        """cli output_match 失败归类 product-bug → 进入既有修复循环路径。"""
        scenario = {
            "scenario_id": "cli-4", "status": "fail",
            "classification": "product-bug",
            "evidence": {"failed_assertions": [
                {"type": "output_match", "expected": "ok", "actual": "boom"}]},
            "assertion_triage": [
                {"assertion": "output_match", "classification": "product-bug",
                 "evidence": "命令输出缺失期望字段"},
            ],
        }
        self.assertTrue(has_product_bug_assertion(scenario))
        # validate_report 放行（证据引用命令输出，非截图）
        res = validate_report({"scenarios": [scenario]})
        self.assertTrue(res["ok"], res.get("violations"))


# ── 3. 无截图证据合规（命令输出/HTTP 响应体替代截图）────────────────

class TestMultiKindEvidenceWithoutScreenshots(unittest.TestCase):
    def test_cli_evidence_command_output_ok(self):
        """cli 失败场景：triage 证据引用命令输出（字符串）→ 合规，不因缺截图判 inconclusive。"""
        scenario = {
            "scenario_id": "cli-5", "status": "fail",
            "classification": "product-bug",
            "evidence": {
                "failed_assertions": [
                    {"type": "output_match", "expected": "ok", "actual": "boom"}],
                # 无 screenshots 键——CLI/API 场景合法形态
            },
            "assertion_triage": [
                {"assertion": "output_match", "classification": "product-bug",
                 "evidence": "命令输出（stdout）：boom\nstderr：（空）"},
            ],
        }
        res = validate_report({"scenarios": [scenario]})
        self.assertTrue(res["ok"], res.get("violations"))

    def test_api_evidence_response_body_ok(self):
        """api 失败场景：triage 证据引用 HTTP 响应体 → 合规（无截图也合规）。"""
        scenario = {
            "scenario_id": "api-3", "status": "fail",
            "classification": "product-bug",
            "evidence": {
                "failed_assertions": [
                    {"type": "status_code", "expected": 201, "actual": 500}],
            },
            "assertion_triage": [
                {"assertion": "status_code", "classification": "product-bug",
                 "evidence": "响应体：{\"error\": \"boom\"}"},
            ],
        }
        res = validate_report({"scenarios": [scenario]})
        self.assertTrue(res["ok"], res.get("violations"))


if __name__ == "__main__":
    unittest.main()