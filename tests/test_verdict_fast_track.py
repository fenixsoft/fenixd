"""add-fast-track-mode task 4.1：fast-track 统一结果文件硬校验单测。

覆盖三要素：
1. 结构完整：缺 verification / 缺 scenarios / verdict 非法 → fail-closed
2. 场景全量执行：设计集与执行集不一致（静默遗漏）→ 不通过
3. 逐场景证据：非 PASS 场景缺分类/证据 → 不通过
4. 豁免逃逸：status=exempt 但分类 product-bug → 不通过
5. 合法通过：全 pass / 非 PASS 带分类+证据 / exempt 带非 product-bug 分类
"""

import unittest

from core.verdict_check import validate_fast_track_result


def _pass_scenario(sid="s1", status="pass", classification=None, evidence=None):
    sc = {
        "scenario_id": sid,
        "description": f"场景 {sid}",
        "status": status,
        "assertion_results": [{"type": "step", "pass": status == "pass", "message": ""}],
        "screenshots": [f"/tmp/{sid}.png"],
    }
    if classification:
        sc["classification"] = classification
    if evidence is not None:
        sc["evidence"] = evidence
    return sc


def _result(scenarios, verdict="verified"):
    return {
        "status": "success",
        "spec": "demo",
        "mode": "fast-track",
        "summary": "ok",
        "verification": {"scenarios": scenarios, "verdict": verdict, "bugs": []},
    }


class TestValidateFastTrackResult(unittest.TestCase):
    def test_valid_all_pass(self):
        r = _result([_pass_scenario("s1"), _pass_scenario("s2")])
        out = validate_fast_track_result(r, designed_ids=["s1", "s2"])
        self.assertTrue(out["ok"], out)

    def test_valid_with_non_pass_classified(self):
        sc = _pass_scenario("s1", status="fail",
                            classification="product-bug",
                            evidence={"failed_assertions": [{"type": "x"}],
                                      "first_failed_step": "步骤1"})
        r = _result([sc], verdict="bug-found")
        out = validate_fast_track_result(r)
        self.assertTrue(out["ok"], out)

    def test_valid_exempt_non_product_bug(self):
        sc = _pass_scenario("s1", status="exempt", classification="env",
                            evidence={"first_failed_step": "环境不可达"})
        out = validate_fast_track_result(_result([sc]))
        self.assertTrue(out["ok"], out)

    def test_missing_verification_fails_closed(self):
        out = validate_fast_track_result({"status": "success"})
        self.assertFalse(out["ok"])
        self.assertTrue(any("verification" in v for v in out["violations"]))

    def test_missing_scenarios_fails_closed(self):
        out = validate_fast_track_result(
            {"status": "success", "verification": {"verdict": "verified"}})
        self.assertFalse(out["ok"])
        self.assertTrue(any("scenarios" in v for v in out["violations"]))

    def test_invalid_verdict_fails_closed(self):
        out = validate_fast_track_result(
            {"status": "success",
             "verification": {"scenarios": [_pass_scenario()], "verdict": "maybe"}})
        self.assertFalse(out["ok"])
        self.assertTrue(any("verdict" in v for v in out["violations"]))

    def test_non_pass_missing_evidence(self):
        sc = _pass_scenario("s1", status="fail")  # 无 classification/evidence
        out = validate_fast_track_result(_result([sc]))
        self.assertFalse(out["ok"])
        self.assertTrue(any("证据缺失" in v for v in out["violations"]))

    def test_silent_omission(self):
        r = _result([_pass_scenario("s1")])
        out = validate_fast_track_result(r, designed_ids=["s1", "s2"])
        self.assertFalse(out["ok"])
        self.assertTrue(any("静默遗漏" in v and "s2" in v for v in out["violations"]))

    def test_exempt_escape(self):
        sc = _pass_scenario("s1", status="exempt", classification="product-bug")
        out = validate_fast_track_result(_result([sc]))
        self.assertFalse(out["ok"])
        self.assertTrue(any("豁免逃逸" in v for v in out["violations"]))


if __name__ == "__main__":
    unittest.main()