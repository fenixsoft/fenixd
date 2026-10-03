"""
依赖级联同因组豁免单测（spec: add-attribution-dedup-cascade-exemption）

覆盖：
  1. 纯级联组豁免：≥3 个 dependency_skipped 同文场景不再判拒、留痕可审计
  2. 混合组语义不变：3 个真实 failed 同文＋级联场景仍拒、reason 不变
  3. 防伪标：judge 自行申报 dependency_skipped / 伪 gate-owned 键均不豁免
  4. 统一入口透传：_run_attribution_gate 合并标记 + 豁免 info 日志留痕
  5. D3 既有归一化细分豁免行为不回退
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.verdict_check import (
    ENGINE_CASCADE_EXEMPT_KEY,
    check_batch_attribution_dedup,
    check_batch_attribution_dedup_scenario,
    is_engine_cascade_scenario,
    merge_engine_cascade_markers,
)
from core.pm_engine.verification.verdict_evidence import _run_attribution_gate


# ── 场景构造助手 ────────────────────────────────────────────────────

_CASCADE_ERROR = (
    "依赖场景失败，未执行: gradle-setup"
    "（依赖失败传播，非本场景产品缺陷）"
)


def _engine_cascade_scenario(sid, depends_on=("gradle-setup",), classification="env"):
    """构造引擎依赖失败传播合成条目（core/verify_engine/engine.py 同形）。

    统一跳过文案 + 空步骤/断言/截图 → 归一化后天然同文（依赖级联形态）。
    """
    return {
        "scenario_id": sid,
        "description": f"场景 {sid}",
        "kind": "web",
        "status": "blocked-env",
        "error": _CASCADE_ERROR,
        "classification": classification,
        "evidence": {"error": _CASCADE_ERROR},
        "step_results": [],
        "assertion_results": [],
        "dependency_skipped": True,
        "skipped_depends_on": list(depends_on),
    }


def _real_failed_scenario(sid, step_no=2, assertion="项目列表行可见", cls="product-bug"):
    """构造真实 failed 场景（模板套用嫌疑形态：同文归因无引擎级联标记）。"""
    return {
        "scenario_id": sid,
        "status": "fail",
        "classification": cls,
        "evidence": {"first_failed_step": f"步骤{step_no}: 应用初始化失败"},
        "assertion_triage": [
            {
                "assertion": assertion,
                "classification": cls,
                "evidence": "错误信息（截断）: 断言未通过",
            }
        ],
    }


# ── 1. 纯级联组豁免 ────────────────────────────────────────────────


class TestPureCascadeGroupExemption(unittest.TestCase):
    """Scenario: 纯级联组（≥3 个 dependency_skipped 同文）不再判拒且留痕。"""

    def test_pure_cascade_group_not_rejected(self):
        """5 个引擎级联同文场景（宿主缺 Gradle 形态）→ 不判拒绝。"""
        report = {"scenarios": [
            _engine_cascade_scenario("s1"),
            _engine_cascade_scenario("s2"),
            _engine_cascade_scenario("s3"),
            _engine_cascade_scenario("s4"),
            _engine_cascade_scenario("s5"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertTrue(
            result["ok"], "纯依赖级联组同文是依赖失败传播的必然形态，不得判拒"
        )
        self.assertEqual(result["violations"], [])

    def test_exemption_trail_in_result(self):
        """豁免决策随查重结果结构留痕：原因（含场景数）＋场景清单。"""
        report = {"scenarios": [
            _engine_cascade_scenario("s1"),
            _engine_cascade_scenario("s2"),
            _engine_cascade_scenario("s3"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertEqual(len(result["exemptions"]), 1)
        exemption = result["exemptions"][0]
        self.assertEqual(
            exemption["reason"], "同因级联组豁免（3 场景，dependency_skipped）"
        )
        self.assertEqual(sorted(exemption["scenario_ids"]), ["s1", "s2", "s3"])

    def test_cascade_scenarios_accepted_not_requeued(self):
        """场景级判定：级联豁免场景置 accept 保留，不进回炉清单。"""
        report = {"scenarios": [
            _engine_cascade_scenario("s1"),
            _engine_cascade_scenario("s2"),
            _engine_cascade_scenario("s3"),
            _engine_cascade_scenario("s4"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertEqual(result["requeue_ids"], [])
        self.assertEqual(sorted(result["accept_ids"]), ["s1", "s2", "s3", "s4"])
        self.assertEqual(result["counts"], {"total": 4, "requeue": 0, "accept": 4})

    def test_batch_level_exemption_trail(self):
        """整批判定入口同样豁免且留痕（check_batch_attribution_dedup）。"""
        report = {"scenarios": [
            _engine_cascade_scenario("s1"),
            _engine_cascade_scenario("s2"),
            _engine_cascade_scenario("s3"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup(report)
        self.assertTrue(result["ok"])
        self.assertEqual(result["violations"], [])
        self.assertEqual(
            result["exemptions"][0]["reason"],
            "同因级联组豁免（3 场景，dependency_skipped）",
        )

    def test_signature_requires_structured_marker_not_text(self):
        """豁免锚点是结构化标记而非统一文案：无标记的同文模板串照拒。"""
        # 与引擎跳过文案逐字相同的归因，但没有引擎结构化标记（judge 重写
        # 条目时丢失标记的形态）→ 不豁免，凑满 ≥3 照拒。
        text = _CASCADE_ERROR
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "blocked-env",
             "classification": "env", "evidence": {"error": text}},
            {"scenario_id": "s2", "status": "blocked-env",
             "classification": "env", "evidence": {"error": text}},
            {"scenario_id": "s3", "status": "blocked-env",
             "classification": "env", "evidence": {"error": text}},
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertFalse(
            result["ok"], "无引擎结构化标记的同文（文案比对不作为豁免锚点）仍判拒"
        )
        self.assertEqual(result["exemptions"], [])


# ── 2. 混合组语义不变 ──────────────────────────────────────────────


class TestMixedGroupStillRejected(unittest.TestCase):
    """Scenario: 混合组（真实 failed 同文＋级联场景）仍拒，reason 不变。"""

    def test_mixed_group_still_rejected(self):
        """3 个真实 failed 同文＋2 个级联场景 → 照拒（阈值对非级联子集计数）。"""
        report = {"scenarios": [
            _real_failed_scenario("r1"),
            _real_failed_scenario("r2"),
            _real_failed_scenario("r3"),
            _engine_cascade_scenario("c1"),
            _engine_cascade_scenario("c2"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertFalse(result["ok"], "含真实 failed 同文的混合组仍是模板套用嫌疑")
        self.assertEqual(len(result["violations"]), 1)
        violation_ids = result["violations"][0]["scenario_ids"]
        self.assertEqual(sorted(violation_ids), ["r1", "r2", "r3"])
        self.assertNotIn("c1", violation_ids)
        self.assertNotIn("c2", violation_ids)

    def test_mixed_group_reason_unchanged(self):
        """违规 reason 文案维持现状（proposal 验收：混合组 reason 不变）。"""
        report = {"scenarios": [
            _real_failed_scenario("r1"),
            _real_failed_scenario("r2"),
            _real_failed_scenario("r3"),
            _engine_cascade_scenario("c1"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        reason = result["violations"][0]["reason"]
        self.assertIn("3 个场景归因文本完全相同", reason)
        self.assertIn("疑似批量套用硬编码归因", reason)
        self.assertIn("r1, r2, r3", reason)

    def test_mixed_group_requeue_excludes_cascade(self):
        """场景级回炉清单只含真实 failed 子集，级联场景按 accept 保留。"""
        report = {"scenarios": [
            _real_failed_scenario("r1"),
            _real_failed_scenario("r2"),
            _real_failed_scenario("r3"),
            _engine_cascade_scenario("c1"),
            _engine_cascade_scenario("c2"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertEqual(sorted(result["requeue_ids"]), ["r1", "r2", "r3"])
        self.assertIn("c1", result["accept_ids"])
        self.assertIn("c2", result["accept_ids"])

    def test_two_real_failed_plus_cascade_passes(self):
        """2 个真实 failed 同文＋级联场景 → 非级联子集不足阈值，放行。"""
        report = {"scenarios": [
            _real_failed_scenario("r1"),
            _real_failed_scenario("r2"),
            _engine_cascade_scenario("c1"),
            _engine_cascade_scenario("c2"),
            _engine_cascade_scenario("c3"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertTrue(result["ok"], "阈值仅对非级联子集计数（≥3 判据不变）")


# ── 3. 防伪标：judge 自行申报不豁免 ────────────────────────────────


class TestJudgeSelfDeclaredNotTrusted(unittest.TestCase):
    """Scenario: judge 报告自标 dependency_skipped 不构成豁免依据（防伪标逃逸）。"""

    def test_flag_without_engine_signature_not_exempted(self):
        """judge 只申报标记位（缺 skipped_depends_on）→ 不豁免，照拒。"""
        report = {"scenarios": [
            dict(_real_failed_scenario("s1"), dependency_skipped=True),
            dict(_real_failed_scenario("s2"), dependency_skipped=True),
            dict(_real_failed_scenario("s3"), dependency_skipped=True),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertFalse(result["ok"])
        self.assertEqual(result["exemptions"], [])

    def test_flag_on_real_failed_shape_contradiction_not_exempted(self):
        """伪标与执行形状矛盾（真实 failed 步骤/断言在位）→ 不豁免。"""
        def _fake(sid):
            sc = _real_failed_scenario(sid)
            sc["dependency_skipped"] = True
            sc["skipped_depends_on"] = ["dep-a"]
            # status 仍为 fail（非引擎合成态 blocked-env）→ 签名不成立
            return sc
        report = {"scenarios": [_fake("s1"), _fake("s2"), _fake("s3")]}
        merged = merge_engine_cascade_markers(report)
        self.assertEqual(merged, [], "签名矛盾（status != blocked-env）不得置标")
        result = check_batch_attribution_dedup_scenario(report)
        self.assertFalse(result["ok"])

    def test_forged_gate_key_cleared_by_merge(self):
        """judge 直写 gate-owned 键（绕过合并）→ 合并侧全量重算清除，照拒。"""
        report = {"scenarios": [
            dict(_real_failed_scenario("s1"), **{ENGINE_CASCADE_EXEMPT_KEY: True}),
            dict(_real_failed_scenario("s2"), **{ENGINE_CASCADE_EXEMPT_KEY: True}),
            dict(_real_failed_scenario("s3"), **{ENGINE_CASCADE_EXEMPT_KEY: True}),
        ]}
        merge_engine_cascade_markers(report)
        for sc in report["scenarios"]:
            self.assertNotIn(ENGINE_CASCADE_EXEMPT_KEY, sc)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertFalse(result["ok"])

    def test_full_engine_signature_is_exempted(self):
        """正向对照：完整引擎签名（标记位＋来源清单＋blocked-env）→ 豁免。"""
        report = {"scenarios": [
            _engine_cascade_scenario("s1"),
            _engine_cascade_scenario("s2"),
            _engine_cascade_scenario("s3"),
        ]}
        merged = merge_engine_cascade_markers(report)
        self.assertEqual(sorted(merged), ["s1", "s2", "s3"])
        self.assertTrue(check_batch_attribution_dedup_scenario(report)["ok"])

    def test_is_engine_cascade_scenario_signature_matrix(self):
        """签名三要素逐一缺失均不成立（is_engine_cascade_scenario 直测）。"""
        base = _engine_cascade_scenario("s1")
        self.assertTrue(is_engine_cascade_scenario(base))
        no_flag = dict(base)
        del no_flag["dependency_skipped"]
        self.assertFalse(is_engine_cascade_scenario(no_flag))
        no_deps = dict(base, skipped_depends_on=[])
        self.assertFalse(is_engine_cascade_scenario(no_deps))
        wrong_status = dict(base, status="fail")
        self.assertFalse(is_engine_cascade_scenario(wrong_status))
        self.assertFalse(is_engine_cascade_scenario("not-a-dict"))


# ── 4. 统一入口透传与豁免日志留痕 ──────────────────────────────────


class TestAttributionGateCascadeExemption(unittest.TestCase):
    """Scenario: _run_attribution_gate 查重前透传标记，豁免命中记 info 留痕。"""

    def _mk_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            pass
        pipeline = MagicMock()
        pipeline._context.logger = MagicMock()
        pipeline._context.project_root = Path(tempfile.mkdtemp())
        return pipeline

    def test_gate_exempts_pure_cascade_and_logs(self):
        """纯级联组经统一入口豁免：返回 ok 且 info 日志含豁免原因与场景清单。"""
        pipeline = self._mk_pipeline()
        report = {"scenarios": [
            _engine_cascade_scenario("s1"),
            _engine_cascade_scenario("s2"),
            _engine_cascade_scenario("s3"),
        ]}
        dedup = _run_attribution_gate(pipeline, "demo-spec", report, " ")
        self.assertIsNotNone(dedup)
        self.assertTrue(dedup["ok"])
        self.assertEqual(
            dedup["exemptions"][0]["reason"],
            "同因级联组豁免（3 场景，dependency_skipped）",
        )
        info_texts = [
            str(call.args[-1])
            for call in pipeline._context.logger.info.call_args_list
        ]
        self.assertTrue(
            any("同因级联组豁免" in t and "s1" in t and "s3" in t for t in info_texts),
            f"豁免 info 日志应含原因与场景清单: {info_texts}",
        )

    def test_gate_rejects_mixed_group_with_cascade_trail(self):
        """混合组经统一入口仍拒：真实 failed 子集判拒，级联子集单独豁免留痕。"""
        pipeline = self._mk_pipeline()
        report = {"scenarios": [
            _real_failed_scenario("r1"),
            _real_failed_scenario("r2"),
            _real_failed_scenario("r3"),
            _engine_cascade_scenario("c1"),
        ]}
        dedup = _run_attribution_gate(pipeline, "demo-spec", report, "（重试轮）")
        self.assertFalse(dedup["ok"])
        # 判拒只针对真实 failed 子集
        self.assertEqual(
            sorted(dedup["violations"][0]["scenario_ids"]), ["r1", "r2", "r3"]
        )
        # 豁免与判拒并存：级联子集的豁免决策单独留痕（可审计未混入判拒组）
        self.assertEqual(
            dedup["exemptions"][0]["scenario_ids"], ["c1"]
        )
        info_texts = [
            str(call.args[-1])
            for call in pipeline._context.logger.info.call_args_list
        ]
        self.assertTrue(
            any("同因级联组豁免（1 场景" in t and "c1" in t for t in info_texts),
            f"级联子集豁免日志应留痕: {info_texts}",
        )

    def test_gate_merges_marker_into_report_entries(self):
        """透传落点：合并后场景条目携带 gate-owned 豁免判据键（留痕可追溯）。"""
        pipeline = self._mk_pipeline()
        report = {"scenarios": [
            _engine_cascade_scenario("s1"),
            _engine_cascade_scenario("s2"),
            _engine_cascade_scenario("s3"),
        ]}
        _run_attribution_gate(pipeline, "demo-spec", report, "（重合成）")
        for sc in report["scenarios"]:
            self.assertIs(sc.get(ENGINE_CASCADE_EXEMPT_KEY), True)


# ── 5. D3 既有归一化细分豁免不回退 ─────────────────────────────────


class TestNormalizationSplitNonRegression(unittest.TestCase):
    """Scenario: 「步骤/断言各异」归一化拆分豁免行为不回退（2026-09-17 D3）。"""

    def test_cascade_varied_steps_still_passed(self):
        """共享根因＋各异步骤序号 → 归一化不同组 → 放行。"""
        def _sc(sid, step_no):
            sc = _real_failed_scenario(sid, step_no=step_no,
                                       assertion=f"断言{step_no}", cls="env")
            return sc
        report = {"scenarios": [
            _sc("s1", 1), _sc("s2", 2), _sc("s3", 3), _sc("s4", 4),
        ]}
        merge_engine_cascade_markers(report)
        self.assertTrue(check_batch_attribution_dedup(report)["ok"])

    def test_pure_template_still_rejected(self):
        """纯模板偷懒（同步骤同断言同文本，无引擎标记）→ 仍拒。"""
        report = {"scenarios": [
            _real_failed_scenario("s1", 2, "项目列表行可见", cls="env"),
            _real_failed_scenario("s2", 2, "项目列表行可见", cls="env"),
            _real_failed_scenario("s3", 2, "项目列表行可见", cls="env"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup(report)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["violations"][0]["scenario_ids"]), 3)

    def test_pass_scenarios_still_excluded(self):
        """pass 场景排除逻辑不变：豁免改造不影响既有排除分支。"""
        report = {"scenarios": [
            {"scenario_id": "p1", "status": "pass"},
            _engine_cascade_scenario("s1"),
            _engine_cascade_scenario("s2"),
            _engine_cascade_scenario("s3"),
        ]}
        merge_engine_cascade_markers(report)
        result = check_batch_attribution_dedup_scenario(report)
        self.assertTrue(result["ok"])
        self.assertNotIn("p1", result["accept_ids"])


if __name__ == "__main__":
    unittest.main()
