"""验证报告产物闸门测试（add-verify-report-gate）。

覆盖三条路径：
  1. 报告缺失 + 结构化数据完整 → 框架合成报告 + 兜底告警
  2. 报告已存在 → 内容与 mtime 均不被改动（Agent 报告优先）
  3. 结构化数据缺失/不可解析 → 阻断（fail-closed）+ 人工升级告警

合成格式用 v2-shell-hash-router 事故（2026-08-29）的真实 report.json 与
.fenix-run-result.json 作为夹具，并验证能被 Dashboard 的 parse_verdict 解析。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SPEC = "v2-shell-hash-router"


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _GateTestBase(unittest.TestCase):
    """公共夹具：临时项目根 + PMEngine（不真实派发）。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.sm_path = self.project_root / "STATE.md"
        from core.state_machine import StateMachine
        self.sm = StateMachine(self.sm_path, self.logger)
        config = {"schedule": {"stuck_threshold_minutes": 60}}
        self.engine = PMEngine(
            self.sm, MagicMock(), config, self.project_root, self.logger,
        )
        # 默认摆一个 testing 中的 spec
        real_handle = self.engine.handle_event
        self.engine.handle_event = MagicMock()
        try:
            self.sm.add_spec(SPEC, {"priority": 5})
            self.sm.transition(SPEC, "ready")
            self.sm.transition(SPEC, "implementing")
            self.sm.transition(SPEC, "implemented")
            self.sm.transition(SPEC, "testing")
        finally:
            self.engine.handle_event = real_handle

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 数据摆放 helpers ──

    def _seed_structured_data(self, spec=SPEC, run_result=None, report=None):
        progress = self.project_root / ".fenix" / "verify-progress" / spec
        progress.mkdir(parents=True, exist_ok=True)
        rr = run_result if run_result is not None else _load_fixture(
            "v2-shell-hash-router-run-result.json")
        rp = report if report is not None else _load_fixture(
            "v2-shell-hash-router-report.json")
        (progress / ".fenix-run-result.json").write_text(
            json.dumps(rr, ensure_ascii=False), encoding="utf-8")
        (progress / "report.json").write_text(
            json.dumps(rp, ensure_ascii=False), encoding="utf-8")

    def _report_path(self, spec=SPEC):
        return (
            self.project_root / "openspec" / "changes" / spec
            / "verification-report.md"
        )

    def _alerts(self):
        from core.admin_store import AdminStore
        return AdminStore(self.project_root, self.logger).read_all()


class TestGateSynthesizesWhenMissing(_GateTestBase):
    """路径1：缺报告 + 数据完整 → 合成 + 告警。"""

    def test_gate_synthesizes_report_silently(self):
        self._seed_structured_data()
        self.assertFalse(self._report_path().exists())

        blocker = self.engine._ensure_verification_report(SPEC)

        self.assertIsNone(blocker)
        path = self._report_path()
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        # 兜底合成标记 + bug-found 关键章节（含根因/证据）
        self.assertIn("裁决 Agent 未写报告，已由框架合成", content)
        self.assertIn("## 结论：❌ 未通过（Bug Found）", content)
        self.assertIn("**状态：", content)
        self.assertIn("| 通过 | 0 |", content)
        self.assertIn("## 真实产品 Bug", content)
        self.assertIn("- 根因：", content)
        self.assertIn("- 证据：", content)
        # 2026-08-29 用户决策：合成兜底静默化，不产生人工升级告警
        alerts = [a for a in self._alerts()
                  if a.get("signal_type") == "verify_report_synthesized"]
        self.assertEqual(len(alerts), 0)

    def test_gate_idempotent_second_call_present(self):
        self._seed_structured_data()
        self.engine._ensure_verification_report(SPEC)
        # 第二次放行（报告已在 → 不再合成、无任何告警）
        blocker = self.engine._ensure_verification_report(SPEC)
        self.assertIsNone(blocker)
        alerts = [a for a in self._alerts()
                  if a.get("signal_type", "").startswith("verify_report")]
        self.assertEqual(len(alerts), 0)


class TestGatePreservesAgentReport(_GateTestBase):
    """路径2：报告已存在 → 内容与 mtime 均不变。"""

    def test_existing_report_untouched(self):
        path = self._report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        original = "# 验证报告：v2-shell-hash-router\n\nAgent 手写叙述内容。\n"
        path.write_text(original, encoding="utf-8")
        stat_before = path.stat()
        # 同步给结构化数据也齐备的场景——闸门仍须不动文件
        self._seed_structured_data()

        blocker = self.engine._ensure_verification_report(SPEC)

        self.assertIsNone(blocker)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        stat_after = path.stat()
        self.assertEqual(stat_before.st_mtime_ns, stat_after.st_mtime_ns)
        # 未产生任何告警
        alerts = [a for a in self._alerts()
                  if a.get("signal_type") in (
                      "verify_report_synthesized", "verify_report_missing")]
        self.assertEqual(alerts, [])


class TestGateBlocksWhenDataUnavailable(_GateTestBase):
    """路径3：结构化数据缺失/不可解析 → 阻断 + 告警，不写空报告。"""

    def _assert_blocked(self):
        blocker = self.engine._ensure_verification_report(SPEC)
        self.assertIsNotNone(blocker)
        self.assertIn("验证报告缺失且无法合成", blocker)
        self.assertFalse(self._report_path().exists())
        # error 字段记录因 + 人工升级告警
        entry = self.sm.read_one(SPEC) or {}
        self.assertEqual(entry.get("status"), "testing")  # 状态未推进
        alerts = [a for a in self._alerts()
                  if a.get("signal_type") == "verify_report_missing"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "major")

    def test_blocks_when_no_data_at_all(self):
        self._assert_blocked()

    def test_blocks_when_data_corrupt(self):
        progress = self.project_root / ".fenix" / "verify-progress" / SPEC
        progress.mkdir(parents=True, exist_ok=True)
        (progress / "report.json").write_text("{not json", encoding="utf-8")
        (progress / ".fenix-run-result.json").write_text("[]", encoding="utf-8")
        self._assert_blocked()

    def test_blocks_when_root_result_is_foreign_spec(self):
        # 项目根共享结果文件携带异 spec 残留 → 不可作为合成依据
        progress = self.project_root / ".fenix" / "verify-progress" / SPEC
        progress.mkdir(parents=True, exist_ok=True)
        (progress / "report.json").write_text("{not json", encoding="utf-8")
        (self.project_root / ".fenix-run-result.json").write_text(
            json.dumps({"status": "bug-found", "spec": "other-spec", "bugs": []}),
            encoding="utf-8",
        )
        self._assert_blocked()


class TestSynthesizedReportParsable(_GateTestBase):
    """任务 3.2：合成报告可被 Dashboard parse_verdict 正确解析。"""

    def _synthesize(self):
        from core.verify_report import synthesize_verification_report
        self._seed_structured_data()
        result = synthesize_verification_report(self.project_root, SPEC)
        self.assertTrue(result["ok"], result)
        return self._report_path().read_text(encoding="utf-8")

    def test_parse_verdict_extracts_fields(self):
        from core.dashboard.data import parse_verdict
        self._synthesize()
        verdict = parse_verdict(self.project_root, SPEC)
        self.assertTrue(verdict["exists"])
        self.assertIn("❌", verdict["status"])
        self.assertIn("Bug Found", verdict["status"])
        self.assertEqual(verdict["summary"]["passed"], "0")
        self.assertEqual(verdict["summary"]["failed"], "10")
        self.assertEqual(verdict["summary"]["product_bugs"], "2")
        self.assertIn("bug-found", verdict["status_detail"])
        # conclusion 是 judge 的结构化 summary 文本，非空
        self.assertIn("hash 路由", verdict["conclusion"])

    def test_synthesis_from_incident_fixtures(self):
        content = self._synthesize()
        # 真实事故数据的关键内容被忠实渲染
        self.assertIn("BUG-01（severity=critical）", content)
        self.assertIn("BUG-02（severity=minor）", content)
        self.assertIn("hash-route-default-overview", content)
        self.assertIn("| 失败 | 10 |", content)
        self.assertIn("| 产品 Bug | 2 |", content)

    def test_verified_report_shape(self):
        from core.dashboard.data import parse_verdict
        from core.verify_report import synthesize_verification_report
        self._seed_structured_data(
            run_result={"status": "verified", "spec": SPEC, "bugs": []},
            report={"summary": {"total": 10, "passed": 10, "warnings": 0,
                                "failed": 0, "errors": 0, "blocked_env": 0},
                    "scenarios": []},
        )
        result = synthesize_verification_report(self.project_root, SPEC)
        self.assertTrue(result["ok"])
        content = self._report_path().read_text(encoding="utf-8")
        self.assertIn("## 结论：✅ 通过（verified）", content)
        self.assertIn("| 通过 | 10 |", content)
        self.assertNotIn("## 真实产品 Bug", content)
        verdict = parse_verdict(self.project_root, SPEC)
        self.assertIn("✅", verdict["status"])
        self.assertEqual(verdict["summary"]["passed"], "10")


if __name__ == "__main__":
    unittest.main()
