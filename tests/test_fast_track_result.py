"""add-fast-track-mode task 2.2：fast-track 统一结果文件解析器单测。

覆盖：
1. 合法 fast-track 结果文件解析（验证段结构）
2. fail-closed：缺失 verification / 缺失 scenarios / verdict 非法 / 场景结构缺件
3. passed/failed 双词表（code-review item eddd21925cd6：解析门与
   verdict_check._FAST_TRACK_SCENARIO_STATUSES 单点对齐；未知词仍 fail-closed）
4. 判定查询（is_verified）
"""

import unittest

from core.fast_track_result import (
    VERDICT_BUG_FOUND,
    VERDICT_VERIFIED,
    parse_fast_track_verification,
    is_verified,
)


def _sample_result(verdict=VERDICT_VERIFIED, scenarios=None):
    return {
        "status": "success",
        "spec": "demo",
        "mode": "fast-track",
        "summary": "done",
        "verification": {
            "scenarios": scenarios or [
                {
                    "scenario_id": "s1",
                    "description": "第一场景",
                    "status": "pass",
                    "assertion_results": [{"type": "step", "pass": True, "message": ""}],
                    "screenshots": ["/tmp/s1.png"],
                }
            ],
            "verdict": verdict,
            "bugs": [] if verdict == VERDICT_VERIFIED else [
                {"severity": "major", "scenario_ids": ["s1"], "description": "bug"}
            ],
        },
    }


class TestParseFastTrackResult(unittest.TestCase):
    def test_parses_verified(self):
        verification = parse_fast_track_verification(_sample_result())
        self.assertIsNotNone(verification)
        self.assertEqual(verification["verdict"], VERDICT_VERIFIED)
        self.assertEqual(len(verification["scenarios"]), 1)
        self.assertTrue(is_verified(verification))

    def test_parses_bug_found(self):
        verification = parse_fast_track_verification(_sample_result(VERDICT_BUG_FOUND))
        self.assertIsNotNone(verification)
        self.assertEqual(verification["verdict"], VERDICT_BUG_FOUND)
        self.assertEqual(len(verification["bugs"]), 1)
        self.assertFalse(is_verified(verification))

    def test_missing_verification_fails_closed(self):
        self.assertIsNone(parse_fast_track_verification({"status": "success", "spec": "s"}))

    def test_missing_scenarios_fails_closed(self):
        r = _sample_result()
        r["verification"] = {"verdict": VERDICT_VERIFIED, "bugs": []}
        self.assertIsNone(parse_fast_track_verification(r))

    def test_empty_scenarios_fails_closed(self):
        r = _sample_result()
        r["verification"]["scenarios"] = []
        self.assertIsNone(parse_fast_track_verification(r))

    def test_invalid_verdict_fails_closed(self):
        r = _sample_result()
        r["verification"]["verdict"] = "maybe"
        self.assertIsNone(parse_fast_track_verification(r))

    def test_invalid_scenario_struct_fails_closed(self):
        r = _sample_result()
        r["verification"]["scenarios"] = [{"scenario_id": "s1", "status": "pass"}]  # 缺 description
        self.assertIsNone(parse_fast_track_verification(r))

    def test_passed_failed_variants_accepted(self):
        """双词表（item eddd21925cd6）：passed/failed 属合法解析状态。

        verdict_check 侧（item 244fa0af2fba）对 passed/failed 的容错以解析门
        放行为前提——解析门先拒则校验侧容错恒不可达，全过报告会被误判
        「结果文件非法」而整轮重派。
        """
        scenarios = [
            {"scenario_id": "s1", "description": "过态变体", "status": "passed"},
            {"scenario_id": "s2", "description": "败态变体", "status": "failed"},
        ]
        verification = parse_fast_track_verification(_sample_result(scenarios=scenarios))
        self.assertIsNotNone(verification)
        statuses = [sc["status"] for sc in verification["scenarios"]]
        self.assertEqual(statuses, ["passed", "failed"])

    def test_unknown_status_fails_closed(self):
        """拼写错误/未知词不因双词表扩容而放行（fail-closed 保持）。"""
        for bad in ("pased", "succes", "PASS"):
            r = _sample_result()
            r["verification"]["scenarios"] = [
                {"scenario_id": "s1", "description": "未知态", "status": bad},
            ]
            self.assertIsNone(
                parse_fast_track_verification(r), msg=f"status={bad!r} 应判非法"
            )

    def test_non_dict_input_fails_closed(self):
        self.assertIsNone(parse_fast_track_verification(None))
        self.assertIsNone(parse_fast_track_verification([]))


if __name__ == "__main__":
    unittest.main()