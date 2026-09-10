"""
verdict-attribution-evidence-gate + attribution-freshness-governance 单测
（spec: verdict-attribution-evidence-gate / attribution-freshness-governance）

覆盖：
  1. 三级归因判定矩阵（evidence-backed / speculative / pending-visual）
  2. 纯推测打回被抑制（should_suppress_bug_found）
  3. 白屏归因方向改判（enforce_blank_screenshot_direction）
  4. 多模态与文本 judge 行为同构（规则只读证据构成，不读模型能力）
  5. 跨轮缓存归因打标（tag_cached_attributions）
  6. 批量归因查重 2/3 场景边界两侧 + 真同因误伤路径
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.verdict_check import (
    ATTRIBUTION_LEVEL_EVIDENCE_BACKED,
    ATTRIBUTION_LEVEL_SPECULATIVE,
    ATTRIBUTION_LEVEL_PENDING_VISUAL,
    compute_attribution_level,
    should_suppress_bug_found,
    enforce_blank_screenshot_direction,
    validate_attribution_levels,
    check_batch_attribution_dedup,
    tag_cached_attributions,
    scenario_fingerprint,
)


def _scenario(sid, status="fail", classification="product-bug",
              evidence=None, screenshot_labels=None, screenshots=None,
              assertion_triage=None):
    """构造最小非 PASS 场景。"""
    return {
        "scenario_id": sid,
        "status": status,
        "classification": classification,
        "evidence": evidence or {},
        "screenshot_labels": screenshot_labels or {},
        "screenshots": screenshots or [],
        "assertion_triage": assertion_triage or [],
    }


def _triage(assertion="元素缺失", classification="product-bug", evidence="按钮未渲染"):
    return [{"assertion": assertion, "classification": classification,
             "evidence": evidence}]


# ── 1. 三级归因判定矩阵 ─────────────────────────────────────────


class TestAttributionLevelMatrix(unittest.TestCase):
    """Scenario: 三级判定的全部组合（规则与 judge 模型能力无关）。"""

    def test_no_evidence_no_reference_speculative(self):
        """无截图、无算法标签、无结构化字段 → speculative。"""
        sc = _scenario("s1", evidence={})
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_SPECULATIVE)

    def test_failed_assertion_triage_evidence_backed(self):
        """引用了失败断言文本（assertion_triage 非空 evidence）→ evidence-backed。"""
        sc = _scenario("s2", assertion_triage=_triage())
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)

    def test_screenshots_evidence_backed(self):
        """有截图路径 + 失败断言归因 → evidence-backed。"""
        sc = _scenario("s3", screenshots=["/tmp/a.png"],
                       assertion_triage=_triage())
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)

    def test_first_failed_step_plus_triage_evidence_backed(self):
        """有 first_failed_step + 失败断言归因 → evidence-backed。"""
        sc = _scenario("s4", evidence={"first_failed_step": "navigate"},
                       assertion_triage=_triage())
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)

    def test_blank_screenshot_label_evidence_backed(self):
        """白屏算法标签 → evidence-backed（标签本身即结构化证据）。"""
        sc = _scenario("s5", screenshot_labels={"blank_screenshot": True,
                                                "pixel_std": 0.001})
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)

    def test_low_contrast_label_evidence_backed(self):
        sc = _scenario("s6", screenshot_labels={"low_contrast": True})
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)

    def test_visual_assertion_no_screenshot_pending_visual(self):
        """涉及视觉断言但无截图/标签 → pending-visual。"""
        sc = _scenario("s7",
                       evidence={"first_failed_step": "样式断言失败"},
                       assertion_triage=_triage(
                           assertion="样式类断言 screenshot_mismatch",
                           evidence="视觉差异"))
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_PENDING_VISUAL)

    def test_first_failed_step_without_triage_speculative(self):
        """有 first_failed_step 但无失败断言归因 → 纯推理链 → speculative。"""
        sc = _scenario("s8", evidence={"first_failed_step": "navigate"},
                       assertion_triage=[])
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_SPECULATIVE)


# ── 2. 纯推测打回被抑制 ─────────────────────────────────────────


class TestSpeculativeSuppression(unittest.TestCase):
    """Scenario: 推测级归因不得作为打回 implementer 的依据。"""

    def test_all_speculative_suppressed(self):
        report = {"scenarios": [
            _scenario("s1", evidence={}),
            _scenario("s2", evidence={}),
        ]}
        # 先算级再判（与流水线同序）
        validate_attribution_levels(report)
        self.assertTrue(should_suppress_bug_found(report))

    def test_evidence_backed_not_suppressed(self):
        report = {"scenarios": [
            _scenario("s1", evidence={}),
            _scenario("s2", screenshots=["/tmp/x.png"],
                      assertion_triage=_triage()),
        ]}
        validate_attribution_levels(report)
        self.assertFalse(should_suppress_bug_found(report))

    def test_pending_visual_not_suppressed(self):
        """pending-visual 不阻塞（允许随裁决输出，人工可区分）。"""
        report = {"scenarios": [
            _scenario("s1", evidence={"first_failed_step": "样式断言失败"},
                      assertion_triage=_triage(
                          assertion="screenshot_mismatch", evidence="视觉差异")),
        ]}
        validate_attribution_levels(report)
        self.assertFalse(should_suppress_bug_found(report))

    def test_env_only_no_driver_not_suppressed(self):
        """全部 env/flaky（非驱动场景）不构成打回依据 → 不抑制。"""
        report = {"scenarios": [
            _scenario("s1", classification="env", evidence={}),
            _scenario("s2", classification="env", evidence={}),
        ]}
        validate_attribution_levels(report)
        self.assertFalse(should_suppress_bug_found(report))

    def test_all_pass_not_suppressed(self):
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "pass"},
            {"scenario_id": "s2", "status": "pass"},
        ]}
        self.assertFalse(should_suppress_bug_found(report))


# ── 3. 白屏归因方向改判 ─────────────────────────────────────────


class TestBlankScreenshotDirection(unittest.TestCase):
    """Scenario: 白屏标签约束归因方向。"""

    def test_product_bug_forced_to_env(self):
        sc = _scenario("s1", classification="product-bug",
                       screenshot_labels={"blank_screenshot": True})
        self.assertEqual(enforce_blank_screenshot_direction(sc), "env")

    def test_already_env_not_changed(self):
        sc = _scenario("s1", classification="env",
                       screenshot_labels={"blank_screenshot": True})
        self.assertIsNone(enforce_blank_screenshot_direction(sc))

    def test_no_blank_label_not_changed(self):
        sc = _scenario("s1", classification="product-bug",
                       screenshot_labels={})
        self.assertIsNone(enforce_blank_screenshot_direction(sc))

    def test_registry_data_layer_attribution_forced_env(self):
        """归因到数据层（registry/项目列表类）→ 强制 env。"""
        sc = _scenario("s1", classification="product-bug",
                       screenshot_labels={"blank_screenshot": True},
                       assertion_triage=_triage(
                           assertion="项目列表为空", evidence="registry ignored"))
        self.assertEqual(enforce_blank_screenshot_direction(sc), "env")


# ── 4. 多模态与文本 judge 行为同构 ──────────────────────────────


class TestJudgeCapabilityIndependence(unittest.TestCase):
    """Scenario: 分级对纯文本 judge 与多模态 judge 同构。

    分级规则只读证据构成（screenshot_labels / screenshots / triage），
    不读 judge 模型能力字段——同一场景无论谁裁决结果一致。
    """

    def test_same_scenario_same_level(self):
        sc = _scenario("s1", evidence={})
        # 文本 judge 与多模态 judge 的产物结构相同（都是 evidence 构成），
        # 但多模态会附读图结论（额外截图标签）——无标签时同样降级 speculative
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_SPECULATIVE)
        # 多模态额外读图并产出 blank_screenshot 标签 → evidence-backed
        sc2 = _scenario("s1", screenshot_labels={"blank_screenshot": True})
        self.assertEqual(compute_attribution_level(sc2),
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)

    def test_multimodal_extra_read_cannot_escape_downgrade(self):
        """多模态的额外读图结论只能提升级别，不能绕过无证据降级。"""
        # 无任何证据时，即使 judge 声称「看到画面」也不能提升级别
        sc = _scenario("s1", evidence={"第一帧正常": "看到页面渲染"})
        # 无截图无标签无结构化字段 → 仍为 speculative（自由文本不构成结构化证据）
        self.assertEqual(compute_attribution_level(sc),
                         ATTRIBUTION_LEVEL_SPECULATIVE)


# ── 5. 跨轮缓存归因打标 ─────────────────────────────────────────


class TestCachedAttributionTagging(unittest.TestCase):
    """Scenario: 指纹命中归因带缓存标 + 纯缓存归因触发门禁。"""

    def _mk_scenario_with_assertion(self, sid):
        """构造含失败断言的场景（指纹稳定）。"""
        return {
            "scenario_id": sid,
            "status": "fail",
            "classification": "product-bug",
            "evidence": {"first_failed_step": "navigate"},
            "assertion_results": [{"type": "element_visible",
                                   "pass": False, "expected": "可见",
                                   "actual": "不可见"}],
            "assertion_triage": _triage(),
            "screenshot_labels": {},
            "screenshots": [],
        }

    def test_fingerprint_hit_tagged(self):
        sc = self._mk_scenario_with_assertion("s1")
        fp = scenario_fingerprint(sc)
        report = {"scenarios": [sc]}
        cache = {"s1": {"fingerprint": fp, "classification": "product-bug",
                        "evidence": {"first_failed_step": "navigate"},
                        "source_round": 2}}
        validate_attribution_levels(report)
        tagged = tag_cached_attributions(report, cache, "spec")
        self.assertIn("s1", tagged)
        self.assertTrue(sc.get("cached_from_previous_round"))
        self.assertEqual(sc.get("cached_source_round"), 2)

    def test_pure_cached_attribution_downgraded_to_speculative(self):
        """纯缓存归因（无本轮新增 evidence-backed 证据）→ speculative。"""
        sc = self._mk_scenario_with_assertion("s1")
        # 本轮无截图、无算法标签（缓存复用场景的 evidence 是 judge 原样写回的）
        fp = scenario_fingerprint(sc)
        report = {"scenarios": [sc]}
        cache = {"s1": {"fingerprint": fp, "classification": "product-bug",
                        "evidence": {"first_failed_step": "navigate"}}}
        validate_attribution_levels(report)
        tag_cached_attributions(report, cache, "spec")
        self.assertEqual(sc.get("attribution_level"),
                         ATTRIBUTION_LEVEL_SPECULATIVE)
        self.assertTrue(sc.get("cached_override_level"))

    def test_fingerprint_miss_not_tagged(self):
        sc = self._mk_scenario_with_assertion("s1")
        report = {"scenarios": [sc]}
        # 指纹不匹配（缓存条目指纹不同）
        cache = {"s1": {"fingerprint": "different-fp",
                        "classification": "product-bug",
                        "evidence": {"first_failed_step": "navigate"}}}
        validate_attribution_levels(report)
        tagged = tag_cached_attributions(report, cache, "spec")
        self.assertNotIn("s1", tagged)
        self.assertFalse(sc.get("cached_from_previous_round", False))


# ── 6. 批量归因查重边界 ─────────────────────────────────────────


class TestBatchAttributionDedup(unittest.TestCase):
    """Scenario: ≥3 场景逐字相同 → 拒绝；2 场景 → 放行。"""

    def test_two_identical_not_rejected(self):
        """2 个场景相同 → 边界下放行（threshold=3）。"""
        report = {"scenarios": [
            _scenario("s1", evidence={"first_failed_step": "x"}),
            _scenario("s2", evidence={"first_failed_step": "x"}),
        ]}
        result = check_batch_attribution_dedup(report)
        self.assertTrue(result["ok"])

    def test_three_identical_rejected(self):
        """3 个场景逐字相同 → 拒绝。"""
        report = {"scenarios": [
            _scenario("s1", evidence={"first_failed_step": "x"}),
            _scenario("s2", evidence={"first_failed_step": "x"}),
            _scenario("s3", evidence={"first_failed_step": "x"}),
        ]}
        result = check_batch_attribution_dedup(report)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["violations"]), 1)
        self.assertIn("s1", result["violations"][0]["scenario_ids"])
        self.assertIn("s3", result["violations"][0]["scenario_ids"])

    def test_whitespace_normalized_before_compare(self):
        """归一化空白后逐字相同才算（"a  b" == "a b"）。"""
        report = {"scenarios": [
            _scenario("s1", evidence={"first_failed_step": "x   y"}),
            _scenario("s2", evidence={"first_failed_step": "x y"}),
            _scenario("s3", evidence={"first_failed_step": "x y"}),
        ]}
        result = check_batch_attribution_dedup(report)
        self.assertFalse(result["ok"])

    def test_different_attributions_passed(self):
        """真同因但文本有区分 → 放行（避免误伤正常多场景同因）。"""
        report = {"scenarios": [
            _scenario("s1", evidence={"first_failed_step": "navigate 失败 (s1)"}),
            _scenario("s2", evidence={"first_failed_step": "navigate 失败 (s2)"}),
            _scenario("s3", evidence={"first_failed_step": "navigate 失败 (s3)"}),
        ]}
        result = check_batch_attribution_dedup(report)
        self.assertTrue(result["ok"])

    def test_pass_scenarios_excluded(self):
        """PASS 场景不参与查重。"""
        report = {"scenarios": [
            {"scenario_id": "p1", "status": "pass"},
            {"scenario_id": "s1", "status": "fail",
             "evidence": {"first_failed_step": "x"}},
        ]}
        result = check_batch_attribution_dedup(report)
        self.assertTrue(result["ok"])


# ── 7. validate_attribution_levels 写入 report.json ─────────────


class TestValidateAttributionLevels(unittest.TestCase):
    """attribution_level 字段持久化进 report.json 场景。"""

    def test_levels_written_to_scenarios(self):
        report = {"scenarios": [
            _scenario("s1", evidence={}),
            _scenario("s2", screenshots=["/tmp/x.png"],
                      assertion_triage=_triage()),
            _scenario("s3", classification="env", evidence={}),
            {"scenario_id": "p1", "status": "pass"},
        ]}
        result = validate_attribution_levels(report)
        self.assertTrue(result["ok"])
        by_id = {s["scenario_id"]: s for s in report["scenarios"]}
        self.assertEqual(by_id["s1"]["attribution_level"],
                         ATTRIBUTION_LEVEL_SPECULATIVE)
        self.assertEqual(by_id["s2"]["attribution_level"],
                         ATTRIBUTION_LEVEL_EVIDENCE_BACKED)
        # env 场景也分级（非 PASS 都要）
        self.assertIn("attribution_level", by_id["s3"])
        # pass 场景不写级（无需归因）
        self.assertNotIn("attribution_level", by_id["p1"])


if __name__ == "__main__":
    unittest.main()
