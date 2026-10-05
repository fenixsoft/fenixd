"""
Tests for evo-add-verify-scenario-resource-mutex：场景资源组互斥与豁免并行上下文。

覆盖任务书：
- 1.1 scenarios.py：TestScenario.resource_group 字段 round-trip、非 str 归一、
  未知键兼容（viewport 可选字段扩展先例口径）
- 1.2 engine.py：_execute_parallel 同 resource_group 在飞互斥（同组串行/
  跨组并行/未标记零变化三类调度用例，范本 tests/test_verify_parallel_backoff.py）、
  批日志互斥标记、报告等待标记与实测并发新键（resource_mutex）
- 2.2 engine.py 场景结果附同窗并行上下文（parallel_context）+
  verify_report.py 豁免条目缺上下文落「证据不全」标记
- 既有 report 顶层 effective_parallel 语义回归（正常轮=配置值）
"""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.verify_engine import VerifyEngine
from core.verify_engine.scenarios import TestScenario as _TestScenario
from core.verify_report import render_verification_report


class _RecorderLogger:
    """记录消息的假 logger（engine 日志可观测断言用，范本同款）。"""

    def __init__(self):
        self.messages = []

    def _log(self, tag, msg):
        self.messages.append(f"[{tag}] {msg}")

    def debug(self, tag, msg, *a, **k):
        self._log(tag, msg)

    def info(self, tag, msg, *a, **k):
        self._log(tag, msg)

    def warning(self, tag, msg, *a, **k):
        self._log(tag, msg)

    def error(self, tag, msg, *a, **k):
        self._log(tag, msg)


class _MutexProbeRunner:
    """按 resource_group 记录在飞峰值的假 Runner（互斥语义探针）。

    事件循环单线程，inflight 递增/递减与峰值比较之间无 await，无竞态。
    """

    def __init__(self):
        self.group_inflight: dict = {}
        self.max_inflight_by_group: dict = {}
        self.exec_count: dict = {}

    async def execute(self, scenario) -> dict:
        grp = scenario.resource_group or "-"
        # 组内在飞计数（与并发池全局在飞分开记——峰值断言的是组内互斥）
        self.group_inflight[grp] = self.group_inflight.get(grp, 0) + 1
        self.max_inflight_by_group[grp] = max(
            self.max_inflight_by_group.get(grp, 0), self.group_inflight[grp]
        )
        self.exec_count[scenario.id] = self.exec_count.get(scenario.id, 0) + 1
        try:
            # 让出事件循环：同批场景真实重叠在飞（否则并发断言退化为顺序假象）
            await asyncio.sleep(0.02)
            return {
                "scenario_id": scenario.id,
                "description": scenario.description,
                "kind": scenario.kind,
                "status": "pass",
                "step_results": [],
                "assertion_results": [],
                "visual_results": [],
                "screenshots": [],
            }
        finally:
            self.group_inflight[grp] -= 1

    def validate(self, scenario) -> list:
        return []

    async def setup(self):
        pass

    async def teardown(self):
        pass


class _EngineHarness(unittest.TestCase):
    """VerifyEngine + 假 Runner 装置（范本 test_verify_parallel_backoff 同款）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger = _RecorderLogger()
        self.runner = _MutexProbeRunner()
        self.engine = VerifyEngine(
            "s1", Path(self.tmpdir), self.logger, {"verify_engine": {"max_parallel": 5}}
        )
        self.engine._runners["web"] = self.runner

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_scenarios(self, scenarios) -> dict:
        report = asyncio.run(self.engine.run(scenarios))
        return json.loads(
            (Path(self.tmpdir) / ".fenix" / "verify-progress" / "s1" / "report.json")
            .read_text(encoding="utf-8")
        )

    def scenario_by_id(self, report, sid) -> dict:
        return next(r for r in report["scenarios"] if r["scenario_id"] == sid)


# ── 1.1 schema：round-trip 与归一 ────────────────────────────────────────


class TestResourceGroupSchema(unittest.TestCase):
    def test_round_trip(self):
        """resource_group 缺省空串；标记后 from_dict/to_dict 透传。"""
        sc = _TestScenario.from_dict(
            {"id": "a", "steps": [], "resource_group": "heavy-build"}
        )
        self.assertEqual(sc.resource_group, "heavy-build")
        d = sc.to_dict()
        self.assertEqual(d["resource_group"], "heavy-build")

    def test_default_omitted_in_to_dict(self):
        """缺省（空串）不写键：存量场景序列化零漂移。"""
        d = _TestScenario.from_dict({"id": "a", "steps": []}).to_dict()
        self.assertNotIn("resource_group", d)

    def test_non_string_normalized_empty(self):
        """非 str 形态（dict/bool/数字/null）一律归一空串=不受限（_parse_viewport
        严格口径）：不制造新验收失败模式，坏形态按未标记放行。"""
        for bad in ({"a": 1}, True, 3, None, ["x"]):
            sc = _TestScenario.from_dict({"id": "a", "steps": [], "resource_group": bad})
            self.assertEqual(sc.resource_group, "", f"形态 {bad!r} 应归一空串")

    def test_strip_whitespace(self):
        sc = _TestScenario.from_dict({"id": "a", "steps": [], "resource_group": "  g  "})
        self.assertEqual(sc.resource_group, "g")

    def test_unknown_keys_still_ignored(self):
        """未知键兼容：字段扩展后 from_dict 仍忽略未知键、不崩。"""
        sc = _TestScenario.from_dict(
            {"id": "a", "steps": [], "future_field": {"x": 1}, "resource_group": "g"}
        )
        self.assertEqual(sc.id, "a")
        self.assertEqual(sc.resource_group, "g")


# ── 1.2 调度：同组串行 / 跨组并行 / 未标记零变化 ─────────────────────────


class TestSameGroupMutex(_EngineHarness):
    def _mixed_set(self):
        """g1×3 + g2×2 + 未标记×2：推演批 1=[a1,b1,c1,c2] 批 2=[a2,b2] 批 3=[a3]。"""
        return [
            _TestScenario(id="a1", resource_group="g1"),
            _TestScenario(id="a2", resource_group="g1"),
            _TestScenario(id="a3", resource_group="g1"),
            _TestScenario(id="b1", resource_group="g2"),
            _TestScenario(id="b2", resource_group="g2"),
            _TestScenario(id="c1"),
            _TestScenario(id="c2"),
        ]

    def test_same_group_serialized(self):
        """同组场景串行：组内在飞峰值恒 1，其余顺延后续批。"""
        report = self.run_scenarios(self._mixed_set())
        self.assertEqual(self.runner.max_inflight_by_group.get("g1"), 1)
        self.assertEqual(self.runner.max_inflight_by_group.get("g2"), 1)
        # 顺延场景最终仍执行恰好一次（defer 只挪批、不丢场景）
        self.assertEqual(self.runner.exec_count.get("a3"), 1)

    def test_cross_group_parallel(self):
        """跨组与未标记场景同批并行：各组互不等待，未标记组并发不受限。"""
        report = self.run_scenarios(self._mixed_set())
        # 未标记场景 c1/c2 同批在飞（峰值 2），调度与并行度不受互斥影响
        self.assertGreaterEqual(self.runner.max_inflight_by_group.get("-"), 2)
        c1 = self.scenario_by_id(report, "c1")
        self.assertEqual(c1["parallel_context"]["peers"], ["a1", "b1", "c2"])
        self.assertEqual(c1["parallel_context"]["observed_parallel"], 4)

    def test_defer_markers_and_batches(self):
        """等待标记与顺延批次数落场景结果（新键承载）。"""
        report = self.run_scenarios(self._mixed_set())
        a1 = self.scenario_by_id(report, "a1")
        a2 = self.scenario_by_id(report, "a2")
        a3 = self.scenario_by_id(report, "a3")
        b2 = self.scenario_by_id(report, "b2")
        # 各组首场景不被顺延
        self.assertNotIn("mutex_waited", a1)
        self.assertNotIn("resource_group", self.scenario_by_id(report, "c1"))
        # 同组后续场景带等待标记与批次计数
        self.assertTrue(a2["mutex_waited"])
        self.assertEqual(a2["mutex_wait_batches"], 1)
        self.assertEqual(a3["mutex_wait_batches"], 2)
        self.assertEqual(b2["mutex_wait_batches"], 1)
        self.assertEqual(a2["resource_group"], "g1")

    def test_report_resource_mutex_key(self):
        """report 顶层 resource_mutex 新键：累计顺延批次 + 全轮最大实测并发；
        既有 effective_parallel 语义不变（恒写配置值 5）。"""
        report = self.run_scenarios(self._mixed_set())
        self.assertEqual(report["effective_parallel"], 5)
        self.assertEqual(report["resource_mutex"]["deferred_total"], 4)
        self.assertEqual(report["resource_mutex"]["observed_parallel"], 4)

    def test_batch_log_mutex_marker(self):
        """批日志含互斥顺延标记与在飞组清单。"""
        self.run_scenarios(self._mixed_set())
        self.assertTrue(
            any("资源组互斥" in m and "a2" in m for m in self.logger.messages),
            "批日志应记录互斥顺延场景",
        )
        self.assertTrue(
            any("实测并行度=" in m for m in self.logger.messages),
            "批日志应记录实测并行度",
        )

    def test_unmarked_set_zero_change(self):
        """全部未标记：调度零变化——同批并行、顶层无 resource_mutex 键、
        无互斥批日志、场景无组标记。"""
        scs = [_TestScenario(id=f"s{i}") for i in range(4)]
        report = self.run_scenarios(scs)
        self.assertNotIn("resource_mutex", report)
        self.assertEqual(self.runner.max_inflight_by_group.get("-"), 4)
        self.assertFalse(any("资源组互斥" in m for m in self.logger.messages))
        for r in report["scenarios"]:
            self.assertNotIn("resource_group", r)
            self.assertNotIn("mutex_waited", r)

    def test_wait_not_counted_into_execution(self):
        """defer 只挪批不改判失败归因：被顺延场景最终照常执行且结果为 pass
        （等待发生在 execute 启动前，不计入场景超时）。"""
        report = self.run_scenarios(self._mixed_set())
        for sid in ("a2", "a3", "b2"):
            self.assertEqual(self.scenario_by_id(report, sid)["status"], "pass")
            self.assertEqual(self.runner.exec_count.get(sid), 1)


# ── 2.2 豁免条目缺并行上下文 → 「证据不全」标记 ──────────────────────────


class TestExemptEvidenceMarker(unittest.TestCase):
    def _report(self, scenarios):
        return {"scenarios": scenarios}

    def test_scenario_row_marked_when_context_missing(self):
        """场景级 flaky/env 分类行缺 parallel_context → 分类列落标记。"""
        old = {
            "scenario_id": "s-old",
            "description": "d",
            "status": "warning",
            "classification": "flaky",
        }
        md = render_verification_report("spec", None, self._report([old]))
        self.assertIn("flaky（证据不全）", md)

    def test_scenario_row_unmarked_with_context(self):
        """附 parallel_context 的豁免行零标记（与无豁免行为一致）。"""
        new = {
            "scenario_id": "s-new",
            "description": "d",
            "status": "warning",
            "classification": "env",
            "parallel_context": {"batch": 1, "peers": ["x"], "observed_parallel": 3},
        }
        md = render_verification_report("spec", None, self._report([new]))
        self.assertIn("| env |", md)
        self.assertNotIn("证据不全", md)

    def test_assertion_exempt_row_marked_when_context_missing(self):
        """断言级豁免清单：缺上下文场景的条目归类列落标记。"""
        old = {
            "scenario_id": "s-old",
            "status": "warning",
            "classification": "flaky",
            "assertion_triage": [
                {"assertion": "a=1", "classification": "flaky", "reason": "r"}
            ],
        }
        md = render_verification_report("spec", None, self._report([old]))
        self.assertIn("flaky（证据不全）", md)

    def test_assertion_exempt_row_unmarked_with_context(self):
        new = {
            "scenario_id": "s-new",
            "status": "warning",
            "classification": "flaky",
            "parallel_context": {"batch": 2, "peers": [], "observed_parallel": 1},
            "assertion_triage": [
                {"assertion": "a=1", "classification": "env", "reason": "r"}
            ],
        }
        md = render_verification_report("spec", None, self._report([new]))
        self.assertNotIn("证据不全", md)

    def test_product_bug_rows_never_marked(self):
        """product-bug 非豁免：缺上下文也不落豁免证据标记（豁免标记仅针对
        flaky/env 分类行与断言级豁免清单）。"""
        sc = {
            "scenario_id": "s-bug",
            "description": "d",
            "status": "fail",
            "classification": "product-bug",
        }
        md = render_verification_report("spec", None, self._report([sc]))
        self.assertNotIn("证据不全", md)


# ── 1.2 回归：既有 effective_parallel 语义（范本口径）────────────────────


class TestEffectiveParallelRegression(_EngineHarness):
    def test_effective_parallel_is_config_value_with_mutex(self):
        """互斥轮 effective_parallel 仍写配置值（实测并发只在 resource_mutex
        新键承载，顶层既有键语义不变）。"""
        report = self.run_scenarios([
            _TestScenario(id="a1", resource_group="g1"),
            _TestScenario(id="a2", resource_group="g1"),
        ])
        self.assertEqual(report["effective_parallel"], 5)
        # 互斥轮实测并发 1（组内串行）与配置值 5 在不同键中各司其职
        self.assertEqual(report["resource_mutex"]["observed_parallel"], 1)

    def test_degraded_round_effective_parallel_is_override(self):
        """降档轮 effective_parallel=override 值（tests/test_verify_parallel_backoff
        口径沿用：互斥改动不侵入该键）。"""
        self.engine.max_parallel = 2
        self.engine._parallel_override_active = True
        report = self.run_scenarios([_TestScenario(id="x", resource_group="g")])
        self.assertEqual(report["effective_parallel"], 2)


if __name__ == "__main__":
    unittest.main()
