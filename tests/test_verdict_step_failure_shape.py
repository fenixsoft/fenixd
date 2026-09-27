"""步骤失败形态的失败清单派生守卫（verdict-step-failure-evidence-derivation）。

「步骤失败型场景」（assertion_results 空表 + 失败信号在场）的三个不变量：
  1. 归因未逐条覆盖框架派生清单 → triage 违规且文案含派生条目（fail-closed
     不弱化），驱动一次有内容的重试而非同形态空转；
  2. 归因逐条覆盖派生清单（以步骤名对应）→ 合规（空表不再空转驳回）；
  3. 重试链注入：步骤失败型违规条目附 derived_failed_assertions，驳回清单
     落盘后重试 prompt 直接给出应申报条目。

仿 tests/test_verify_verdict_multi_kind.py 的 TestMultiKindTriageRequirement
风格：进程内构造场景 dict 直接调 triage_violation，不起引擎。
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.verdict_check import (
    derive_default_failed_assertions,
    triage_violation,
    validate_report,
)

# 步骤失败形态基座：assertion_results 空表 + 失败步骤（引擎侧任一步骤原语
# 失败即跳过断言执行，故断言清单必为空表）
_STEP_FAILURE_SCENARIO = {
    "scenario_id": "web-1",
    "status": "fail",
    "classification": "product-bug",
    "step_results": [
        {"success": False, "action": "click", "target": ".submit-btn", "error": "元素未找到: .submit-btn"}
    ],
    "assertion_results": [],
    "visual_results": [],
    # evidence 只带 first_failed_step（failed_assertions 留空以维持检测③
    # 形态；evidence 非空性由另一维度满足，validate_report 不因证据空拦截）
    "evidence": {"first_failed_step": "步骤1: click .submit-btn 后无响应"},
}


def _with_triage(triage):
    sc = dict(_STEP_FAILURE_SCENARIO)
    sc["assertion_triage"] = triage
    return sc


# ── 1. 检测③派生清单覆盖校验（两态）────────────────────────────────


class TestStepFailureShapeTriage(unittest.TestCase):
    def test_uncovered_derived_list_violation(self):
        """空表+失败步骤+归因未覆盖派生清单 → 违规且文案含派生条目。"""
        scenario = _with_triage(
            [
                {"assertion": "页面标题渲染正常", "classification": "product-bug", "evidence": "标题存在"},
            ]
        )
        violation = triage_violation(scenario)
        self.assertIsNotNone(violation)
        # 文案携带派生条目（步骤名），重试 judge 据此拿到应申报条目
        self.assertIn("派生", violation)
        self.assertIn(".submit-btn", violation)
        self.assertIn("step_error", violation)
        # fail-closed 不弱化：validate_report 整体仍判不合规
        res = validate_report({"scenarios": [scenario]})
        self.assertFalse(res["ok"])

    def test_covered_derived_list_compliant(self):
        """归因逐条覆盖派生清单（以步骤名对应）→ 合规（空表不再空转驳回）。"""
        scenario = _with_triage(
            [
                {
                    "assertion": "click .submit-btn 后无响应",
                    "classification": "product-bug",
                    "evidence": "元素未找到: .submit-btn",
                },
            ]
        )
        self.assertIsNone(triage_violation(scenario))
        res = validate_report({"scenarios": [scenario]})
        self.assertTrue(res["ok"], res.get("violations"))

    def test_selector_only_mention_covers(self):
        """归因仅引用选择器（不复制步骤序号壳）也视为名称对应。"""
        scenario = _with_triage(
            [
                {"assertion": ".submit-btn 元素不存在", "classification": "product-bug", "evidence": "DOM snapshot"},
            ]
        )
        self.assertIsNone(triage_violation(scenario))

    def test_visual_only_derived_uncovered_violation(self):
        """空表+驱动视觉结论（无失败步骤）→ 同样走派生覆盖校验。"""
        scenario = {
            "scenario_id": "web-2",
            "status": "warning",
            "classification": "flaky",
            "step_results": [],
            "assertion_results": [],
            "visual_results": [
                {"baseline": "home.png", "status": "diff_detected", "ssim": 0.9, "pass": False}
            ],
            "evidence": {},
            "assertion_triage": [
                {"assertion": "无关归因", "classification": "flaky", "evidence": "x"},
            ],
        }
        violation = triage_violation(scenario)
        self.assertIsNotNone(violation)
        self.assertIn("visual:home.png", violation)

    def test_visual_bare_name_attribution_compliant(self):
        """归因以裸视觉名对应（不复制 visual: 前缀装饰）→ 合规。

        回归守卫：visual: 前缀是派生器自造的装饰，覆盖校验若要求归因逐字
        含整串，任何合法裸名归因都被误判未覆盖（验证链 BUG-01）。
        """
        scenario = {
            "scenario_id": "web-4",
            "status": "warning",
            "classification": "flaky",
            "step_results": [],
            "assertion_results": [],
            "visual_results": [
                {"baseline": "probe-visual-gamma", "status": "diff_detected"}
            ],
            "evidence": {"first_failed_step": "probe-visual-gamma 视觉比对 diff_detected"},
            "assertion_triage": [
                {
                    "assertion": "probe-visual-gamma 视觉比对与基线不一致",
                    "classification": "flaky",
                    "evidence": "ssim 0.9 低于门限",
                },
            ],
        }
        self.assertIsNone(triage_violation(scenario))
        res = validate_report({"scenarios": [scenario]})
        self.assertTrue(res["ok"], res.get("violations"))

    def test_visual_full_prefix_attribution_still_covers(self):
        """归因逐字引用完整标注（visual:home.png）→ 仍合规（完整 token 保留）。"""
        scenario = {
            "scenario_id": "web-5",
            "status": "warning",
            "classification": "flaky",
            "step_results": [],
            "assertion_results": [],
            "visual_results": [{"baseline": "home.png", "status": "diff_detected"}],
            "evidence": {},
            "assertion_triage": [
                {
                    "assertion": "visual:home.png 与基线不一致",
                    "classification": "flaky",
                    "evidence": "diff",
                },
            ],
        }
        self.assertIsNone(triage_violation(scenario))

    def test_visual_unrelated_attribution_still_violation(self):
        """归因不含视觉名也不含完整标注 → 仍判违规（fail-closed 不弱化）。"""
        scenario = {
            "scenario_id": "web-6",
            "status": "warning",
            "classification": "flaky",
            "step_results": [],
            "assertion_results": [],
            "visual_results": [{"baseline": "home.png", "status": "diff_detected"}],
            "evidence": {},
            "assertion_triage": [
                {"assertion": "首页渲染正常", "classification": "flaky", "evidence": "x"},
            ],
        }
        violation = triage_violation(scenario)
        self.assertIsNotNone(violation)
        self.assertIn("visual:home.png", violation)

    def test_generic_action_label_count_coverage(self):
        """引擎未回传 target（标注仅通用动作词）→ 条数覆盖即合规（粒度差兜底）。"""
        scenario = {
            "scenario_id": "cli-1",
            "status": "fail",
            "classification": "env",
            "step_results": [{"success": False, "action": "run", "error": "信号死亡"}],
            "assertion_results": [],
            "visual_results": [],
            "evidence": {},
            "assertion_triage": [
                {"assertion": "daemon 子进程信号死亡", "classification": "env", "evidence": "SIGKILL"},
            ],
        }
        self.assertIsNone(triage_violation(scenario))

    def test_detection_1_2_semantics_untouched(self):
        """检测①②语义不动：有引擎断言清单时仍按清单计数核验。"""
        scenario = {
            "scenario_id": "web-3",
            "status": "fail",
            "classification": "product-bug",
            "step_results": [{"success": True, "action": "click"}],
            "assertion_results": [
                {"type": "element_visible", "pass": False},
                {"type": "text_contains", "pass": False},
            ],
            "evidence": {"failed_assertions": [{"type": "element_visible"}, {"type": "text_contains"}]},
            "assertion_triage": [
                {"assertion": "element_visible", "classification": "product-bug", "evidence": "x"},
            ],
        }
        violation = triage_violation(scenario)
        self.assertIsNotNone(violation)
        self.assertIn("少于失败断言数", violation)


# ── 2. 派生 helper 形状 ────────────────────────────────────────────


class TestDeriveDefaultFailedAssertions(unittest.TestCase):
    def test_step_failure_entry_shape(self):
        """success=False 步骤 → step_error 条目（处方申报形状 + step_failure 标注）。"""
        entries = derive_default_failed_assertions(_STEP_FAILURE_SCENARIO)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["type"], "step_error")
        self.assertEqual(e["selector"], "步骤1(click .submit-btn)")
        self.assertEqual(e["expected"], "步骤成功")
        self.assertIn(".submit-btn", e["actual"])
        self.assertTrue(e["step_failure"])

    def test_visual_entry_and_no_signal_empty(self):
        """驱动视觉结论 → screenshot_mismatch 条目；无失败信号 → 空表。"""
        entries = derive_default_failed_assertions(
            {
                "step_results": [],
                "visual_results": [{"baseline": "home.png", "status": "diff_detected"}],
            }
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["type"], "screenshot_mismatch")
        self.assertEqual(entries[0]["selector"], "visual:home.png")
        self.assertTrue(entries[0]["step_failure"])
        self.assertEqual(derive_default_failed_assertions({"step_results": [], "visual_results": []}), [])
        self.assertEqual(derive_default_failed_assertions(None), [])

    def test_actual_clipped_to_300(self):
        """actual 文本 >300 字截断（与 planner-judge 处方 ≤300 字约束一致）。"""
        entries = derive_default_failed_assertions(
            {
                "step_results": [{"success": False, "action": "run", "error": "x" * 500}],
            }
        )
        self.assertLessEqual(len(entries[0]["actual"]), 301)


# ── 3. 重试链注入派生清单（1.2）──────────────────────────────────

from core.pm_engine.verification.verdict_evidence import (  # noqa: E402
    _attach_derived_failed_assertions,
    _write_verdict_violations,
)


class _FakePipeline:
    """最小 pipeline 桩：只提供 _write_verdict_violations 依赖的两个接口。"""

    def __init__(self, root: Path):
        self._root = root
        self._context = SimpleNamespace(
            logger=SimpleNamespace(warning=lambda *a, **k: None)
        )

    def _verdict_violations_path(self, spec_name: str) -> Path:
        return self._root / ".fenix" / "verify-progress" / spec_name / "verdict_violations.json"


class TestRetryInjectionOfDerivedList(unittest.TestCase):
    def test_attach_derived_to_step_failure_violation(self):
        """步骤失败型场景违规 → 附 derived_failed_assertions；其他场景原样。"""
        report = {"scenarios": [_with_triage([]), dict(_STEP_FAILURE_SCENARIO, scenario_id="ok-1",
                                                                assertion_results=[{"type": "x", "pass": True}])]}
        violations = [
            {"scenario_id": "web-1", "status": "fail", "reason": "assertion_triage 未逐条覆盖"},
            {"scenario_id": "ok-1", "status": "fail", "reason": "classification 缺失或取值非法"},
        ]
        enriched = _attach_derived_failed_assertions(report, violations)
        self.assertIn("derived_failed_assertions", enriched[0])
        self.assertEqual(
            enriched[0]["derived_failed_assertions"][0]["selector"],
            "步骤1(click .submit-btn)",
        )
        # 有引擎断言清单的场景不附派生清单（非步骤失败型形态）
        self.assertNotIn("derived_failed_assertions", enriched[1])

    def test_attach_without_report_is_noop(self):
        """report 缺席（重合成等调用方）→ 原样返回，幂等。"""
        violations = [{"scenario_id": "web-1", "status": "fail", "reason": "r"}]
        self.assertEqual(_attach_derived_failed_assertions(None, violations), violations)

    def test_write_verdict_violations_persists_derived_list(self):
        """_write_verdict_violations 落盘的驳回清单携带派生条目（重试 prompt 数据源）。"""
        report = {"scenarios": [_with_triage([])]}
        violations = [
            {"scenario_id": "web-1", "status": "fail", "reason": "assertion_triage 未逐条覆盖"}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = _FakePipeline(Path(tmp))
            _write_verdict_violations(pipeline, "demo", violations, report)
            path = pipeline._verdict_violations_path("demo")
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("derived_failed_assertions", data[0])

    def test_write_verdict_violations_without_report_unchanged(self):
        """不传 report（既有调用方如查重回炉）→ 落盘内容与旧语义一致。"""
        violations = [{"scenario_ids": ["a", "b"], "reason": "归因同文"}]
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = _FakePipeline(Path(tmp))
            _write_verdict_violations(pipeline, "demo", violations)
            data = json.loads(pipeline._verdict_violations_path("demo").read_text(encoding="utf-8"))
            self.assertEqual(data, violations)


if __name__ == "__main__":
    unittest.main()
