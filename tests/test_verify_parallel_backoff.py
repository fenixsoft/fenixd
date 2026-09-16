"""
Tests for add-verify-parallel-backoff：inconclusive 重验并行度自适应降档。

覆盖任务书：
- 1.1 pm_engine 写端：attempts≥2 重验分支写 `_verify_parallel_override`（首轮不写）
- 1.2 非 inconclusive 判定分支复位（存在才清）；升级/停验分支保留现场
- 2.1 verify_engine 读端：构造后以 override 覆盖 max_parallel
- 2.2 可观测：降档轮日志标记 + report 顶层 effective_parallel；正常轮无标记
- 3.1 unfreeze 解冻清零块同步清 override
- 3.2 fast-track verified / 全链 verified 落点同步清 override
"""
import asyncio
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.state_machine import StateMachine
from core.pm_engine import PMEngine


class _RecorderLogger:
    """记录消息的假 logger（engine 日志可观测断言用）。"""

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


class _FakeLogger(_RecorderLogger):
    """环境门禁测试的静默 logger（不记录）。"""
    pass


def _blocked_report(blocked_env=3, failed=0, errors=0, passed=0):
    return {
        "summary": {
            "total": blocked_env + failed + passed,
            "passed": passed,
            "warnings": blocked_env,
            "failed": failed,
            "errors": errors,
            "blocked_env": blocked_env,
        }
    }


def _make_pm_engine(tmpdir, max_parallel=5, inconclusive_max_attempts=3,
                    escalate_attempts=4):
    project_root = Path(tmpdir)
    logger = _FakeLogger()
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(
        sm, mock.MagicMock(),
        {"verify_engine": {
            "max_parallel": max_parallel,
            "inconclusive_max_attempts": inconclusive_max_attempts,
            "inconclusive_escalate_attempts": escalate_attempts,
        }},
        project_root, logger,
    )
    sm.add_spec("s1", {"priority": 5})
    sm.update_spec("s1", {"status": "implemented"})
    return engine, sm


# ── 1.1 写端：attempts≥2 递减写入，attempts==1 不写 ──────────────────────

class TestParallelBackoffWrite(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine, self.sm = _make_pm_engine(self.tmpdir, max_parallel=5)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_first_attempt_no_override(self):
        """首次 inconclusive 重验不降档：spec attrs 不含 _verify_parallel_override。"""
        self.assertTrue(
            self.engine._verification._handle_env_blocked_inconclusive("s1", _blocked_report()))
        spec = self.sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 1)
        self.assertNotIn("_verify_parallel_override", spec,
                         "首轮（attempt 1）白屏证据尚不存在，不得写入降档标记")

    def test_second_attempt_halves_parallel(self):
        """连续 blocked-env 第 2 轮：5 >> 1 = 2。"""
        self.sm.update_spec("s1", {"_inconclusive_attempts": 1})
        self.assertTrue(
            self.engine._verification._handle_env_blocked_inconclusive("s1", _blocked_report()))
        spec = self.sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 2)
        self.assertEqual(int(spec["_verify_parallel_override"]), 2, "5>>1=2")

    def test_third_attempt_floors_at_one(self):
        """连续 blocked-env 第 3 轮（仍在重验分支内）：5 >> 2 = 1（下限 1）。

        默认 inconclusive_max_attempts=3 时 attempts=3 已停验、不进入重验分支；
        用 max_attempts=4 使第 3 轮判定仍在重验分支，验证递减公式触底。
        """
        self.engine, self.sm = _make_pm_engine(
            self.tmpdir, max_parallel=5, inconclusive_max_attempts=4)
        self.sm.update_spec("s1", {"_inconclusive_attempts": 2})
        self.assertTrue(
            self.engine._verification._handle_env_blocked_inconclusive("s1", _blocked_report()))
        spec = self.sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 3)
        self.assertEqual(int(spec["_verify_parallel_override"]), 1, "5>>2=1")

    def test_low_config_bottoms_out(self):
        """配置 max_parallel=2 时第 2 轮直接触底 1。"""
        self.engine.config = {"verify_engine": {
            "max_parallel": 2,
            "inconclusive_max_attempts": 3,
            "inconclusive_escalate_attempts": 4,
        }}
        self.sm.update_spec("s1", {"_inconclusive_attempts": 1})
        self.assertTrue(
            self.engine._verification._handle_env_blocked_inconclusive("s1", _blocked_report()))
        spec = self.sm.read_one("s1")
        self.assertEqual(int(spec["_verify_parallel_override"]), 1, "配置值 2 直接触底 1")


# ── 1.2 复位端 + 3.x 清零点同步 ──────────────────────────────────────────

class TestParallelBackoffReset(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine, self.sm = _make_pm_engine(self.tmpdir, max_parallel=5)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_healthy_round_clears_override(self):
        """降档轮后出现真实失败（非 inconclusive）→ override 被清除。"""
        self.sm.update_spec("s1", {"_inconclusive_attempts": 1,
                                   "_verify_parallel_override": 2})
        report = _blocked_report(blocked_env=1, failed=2)
        self.assertFalse(
            self.engine._verification._handle_env_blocked_inconclusive("s1", report))
        spec = self.sm.read_one("s1")
        self.assertIsNone(spec.get("_verify_parallel_override"),
                          "健康轮（有效失败>0）应清除降档并行度，恢复配置并行度")

    def test_healthy_no_blocked_env_clears_override(self):
        """降档轮后 blocked_env=0（无环境性失联）→ override 被清除。"""
        self.sm.update_spec("s1", {"_inconclusive_attempts": 1,
                                   "_verify_parallel_override": 2})
        report = _blocked_report(blocked_env=0, failed=1)
        self.assertFalse(
            self.engine._verification._handle_env_blocked_inconclusive("s1", report))
        spec = self.sm.read_one("s1")
        self.assertIsNone(spec.get("_verify_parallel_override"))

    def test_clear_only_when_present(self):
        """无 override 的健康轮不产生残留（存在才清，避免无谓写盘）。"""
        report = _blocked_report(blocked_env=0, failed=1)
        self.assertFalse(
            self.engine._verification._handle_env_blocked_inconclusive("s1", report))
        spec = self.sm.read_one("s1")
        self.assertNotIn("_verify_parallel_override", spec)

    def test_escalation_keeps_override(self):
        """升级通道（attempts≥escalate）保留 override——冻结待人工时保留现场证据。"""
        self.engine, self.sm = _make_pm_engine(
            self.tmpdir, max_parallel=5, inconclusive_max_attempts=3,
            escalate_attempts=4)
        self.sm.update_spec("s1", {"_inconclusive_attempts": 3,
                                   "_verify_parallel_override": 1})
        self.assertTrue(
            self.engine._verification._handle_env_blocked_inconclusive("s1", _blocked_report()))
        spec = self.sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 4)
        self.assertEqual(int(spec["_verify_parallel_override"]), 1,
                         "升级分支不得清除降档现场证据")

    def test_stop_retry_keeps_override(self):
        """停验分支（attempts≥max）保留 override。"""
        self.sm.update_spec("s1", {"_inconclusive_attempts": 2,
                                   "_verify_parallel_override": 1})
        self.assertTrue(
            self.engine._verification._handle_env_blocked_inconclusive("s1", _blocked_report()))
        spec = self.sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 3)
        self.assertEqual(int(spec["_verify_parallel_override"]), 1,
                         "停验分支不得清除降档现场证据")


class TestParallelBackoffClearPoints(unittest.TestCase):
    """3.1 unfreeze / 3.2 fast-track verified / 全链 verified 清零点。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine, self.sm = _make_pm_engine(self.tmpdir, max_parallel=5)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unfreeze_clears_override(self):
        """人工解冻：_inconclusive_attempts 与 _verify_parallel_override 同轮清零。"""
        self.sm.update_spec("s1", {"_inconclusive_attempts": 4,
                                   "_verify_parallel_override": 1})
        self.sm.freeze_spec("s1", reason="测试冻结")
        self.sm.unfreeze_spec("s1", status="implemented")
        spec = self.sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 0)
        self.assertIsNone(spec.get("_verify_parallel_override"),
                          "解冻应同轮清降档并行度，重验从配置并行度开始")

    def test_fast_track_verified_clears_override(self):
        """fast-track verified：清零点同步清 _verify_parallel_override。"""
        self.engine._verification._env_whitewash_gate = mock.MagicMock(return_value=True)
        self.engine._on_spec_verified = mock.MagicMock()
        self.engine.state_machine.transition("s1", "testing")
        self.sm.update_spec("s1", {"_inconclusive_attempts": 2,
                                   "_verify_parallel_override": 1})
        result = SimpleNamespace(run_id="ft-run-1")
        self.engine._dispatcher._fast_track_advance_to_verified("s1", result)
        spec = self.sm.read_one("s1")
        self.assertEqual(spec["status"], "verified")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 0)
        self.assertIsNone(spec.get("_verify_parallel_override"),
                          "fast-track verified 应同轮清降档并行度")

    def test_full_chain_verified_clears_override(self):
        """全链 verified（非 fast-track）落点：_inconclusive_attempts 清零处同步清 override。"""
        from core.pm_engine.verification import VerdictReadResult

        verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        verify_dir.mkdir(parents=True, exist_ok=True)
        (verify_dir / "test_scenarios.json").write_text(json.dumps([
            {
                "id": "scn-a",
                "description": "场景A",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8787/#/projects/demo"},
                    {"action": "wait", "target": ".x", "description": "等待"},
                ],
                "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
            },
        ], ensure_ascii=False), encoding="utf-8")

        self.sm.add_spec("demo-spec", {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("demo-spec", st)
        self.sm.update_spec("demo-spec", {"_inconclusive_attempts": 2,
                                          "_verify_parallel_override": 1})

        self.engine._enqueue = mock.MagicMock()
        self.engine.agent_runner.run_planner = mock.MagicMock(
            return_value=SimpleNamespace(success=True, error=None,
                                         run_id="planner-judge-1"))
        self.engine._verification._apply_scenario_freeze = mock.MagicMock(return_value={})
        self.engine._verification._apply_interaction_contract = mock.MagicMock(return_value=None)
        self.engine._verification._verify_verdict_evidence = mock.MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._verification._update_warning_streaks = mock.MagicMock(return_value=[])
        self.engine._verification._ensure_app_reachable = mock.MagicMock(return_value=(True, False, ""))
        self.engine._verification._env_whitewash_gate = mock.MagicMock(return_value=True)
        self.engine._verification._ensure_verification_report = mock.MagicMock(return_value=None)
        self.engine._verification._check_verification_gate = mock.MagicMock(return_value=None)
        self.engine._verification._render_scenario_change_section_to_report = mock.MagicMock()
        self.engine._on_spec_verified = mock.MagicMock()
        self.engine._verification._read_verdict = mock.MagicMock(
            return_value=VerdictReadResult.success("verified"))

        runs = []

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                pass

            async def run(self, scenarios):
                runs.append(1)
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": 2, "passed": 1, "warnings": 0,
                        "failed": 1, "errors": 0, "blocked_env": 0,
                    },
                    "scenarios": [],
                }

        with mock.patch("importlib.reload", lambda m: m), \
                mock.patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")

        spec = self.sm.read_one("demo-spec")
        self.assertEqual(spec["status"], "verified")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 0)
        self.assertIsNone(spec.get("_verify_parallel_override"),
                          "全链 verified 落点应同轮清降档并行度")


# ── 2.1 读端：构造 VerifyEngine 后以 override 覆盖 max_parallel ──────────

class TestParallelBackoffRead(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine, self.sm = _make_pm_engine(self.tmpdir, max_parallel=5)
        self.verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        self.verify_dir.mkdir(parents=True, exist_ok=True)
        (self.verify_dir / "test_scenarios.json").write_text(json.dumps([
            {
                "id": "scn-a",
                "description": "场景A",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8787/#/projects/demo"},
                    {"action": "wait", "target": ".x", "description": "等待"},
                ],
                "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
            },
        ], ensure_ascii=False), encoding="utf-8")

        self.sm.add_spec("demo-spec", {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("demo-spec", st)

        self.engine._enqueue = mock.MagicMock()
        self.engine.agent_runner.run_planner = mock.MagicMock(
            return_value=SimpleNamespace(success=True, error=None,
                                         run_id="planner-judge-1"))
        self.engine._verification._apply_scenario_freeze = mock.MagicMock(return_value={})
        self.engine._verification._apply_interaction_contract = mock.MagicMock(return_value=None)
        self.engine._verification._verify_verdict_evidence = mock.MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._verification._update_warning_streaks = mock.MagicMock(return_value=[])
        self.engine._verification._ensure_app_reachable = mock.MagicMock(return_value=(True, False, ""))
        self.engine._verification._env_whitewash_gate = mock.MagicMock(return_value=True)
        self.engine._verification._ensure_verification_report = mock.MagicMock(return_value=None)
        self.engine._verification._check_verification_gate = mock.MagicMock(return_value=None)
        self.engine._verification._render_scenario_change_section_to_report = mock.MagicMock()
        self.engine._on_spec_verified = mock.MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_engine_parallel_overridden_from_spec_attrs(self):
        """spec attrs 含 _verify_parallel_override 时引擎有效并行度被覆盖。"""
        from core.pm_engine.verification import VerdictReadResult
        self.sm.update_spec("demo-spec", {"_verify_parallel_override": 2})
        self.engine._verification._read_verdict = mock.MagicMock(
            return_value=VerdictReadResult.success("verified"))

        captured = {}

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                self.max_parallel = 5  # 模拟 VerifyEngine.__init__ 从配置读取的默认值
                self._parallel_override_active = False

            async def run(self, scenarios):
                captured["max_parallel"] = self.max_parallel
                captured["active"] = getattr(self, "_parallel_override_active", False)
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": 2, "passed": 1, "warnings": 0,
                        "failed": 1, "errors": 0, "blocked_env": 0,
                    },
                    "scenarios": [],
                }

        with mock.patch("importlib.reload", lambda m: m), \
                mock.patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")

        self.assertEqual(captured["max_parallel"], 2,
                         "重验轮引擎 MUST 以 override 覆盖 max_parallel 配置值")
        self.assertTrue(captured["active"], "降档轮应打降档来源标记")

    def test_no_override_keeps_configured_parallel(self):
        """无 override 时引擎保持配置并行度，且不打降档标记。"""
        from core.pm_engine.verification import VerdictReadResult
        self.engine._verification._read_verdict = mock.MagicMock(
            return_value=VerdictReadResult.success("verified"))

        captured = {}

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                self.max_parallel = 5
                self._parallel_override_active = False

            async def run(self, scenarios):
                captured["max_parallel"] = self.max_parallel
                captured["active"] = getattr(self, "_parallel_override_active", False)
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": 2, "passed": 1, "warnings": 0,
                        "failed": 1, "errors": 0, "blocked_env": 0,
                    },
                    "scenarios": [],
                }

        with mock.patch("importlib.reload", lambda m: m), \
                mock.patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")

        self.assertEqual(captured["max_parallel"], 5)
        self.assertFalse(captured["active"], "正常轮不得打降档来源标记")


# ── 2.2 可观测：引擎启动日志 + report 顶层 effective_parallel ─────────────

class TestParallelBackoffObservability(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger = _RecorderLogger()
        from core.verify_engine import VerifyEngine
        self.engine = VerifyEngine(
            "s1", Path(self.tmpdir), self.logger,
            {"verify_engine": {"max_parallel": 5}})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _saved_report(self):
        report_path = (Path(self.tmpdir) / ".fenix" / "verify-progress"
                       / "s1" / "report.json")
        return json.loads(report_path.read_text(encoding="utf-8"))

    def test_normal_round_report_effective_parallel(self):
        """正常轮 report 顶层写 effective_parallel=配置值。"""
        asyncio.run(self.engine.run([]))
        report = self._saved_report()
        self.assertEqual(report["effective_parallel"], 5)

    def test_normal_round_log_no_marker(self):
        """正常轮日志无降档来源标记。"""
        asyncio.run(self.engine.run([]))
        self.assertFalse(
            any("inconclusive 降档" in m for m in self.logger.messages),
            "正常轮日志不得出现降档标记")
        start_lines = [m for m in self.logger.messages if "并行度=" in m]
        self.assertTrue(start_lines, "引擎启动日志应含并行度")
        self.assertIn("并行度=5", start_lines[0])

    def test_degraded_round_log_marker_and_report(self):
        """降档轮：日志含并行度 N（inconclusive 降档）标记，report effective_parallel=N。"""
        self.engine.max_parallel = 2
        self.engine._parallel_override_active = True
        asyncio.run(self.engine.run([]))
        start_lines = [m for m in self.logger.messages if "并行度=" in m]
        self.assertTrue(start_lines)
        self.assertIn("并行度=2（inconclusive 降档）", start_lines[0],
                      "降档轮日志须附降档来源标记")
        self.assertEqual(self._saved_report()["effective_parallel"], 2)
