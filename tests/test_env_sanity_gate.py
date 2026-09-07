"""verify-environment-sanity-gate 的单元与回归测试。

覆盖三条 capability：
1. env_gate 纯函数分类（候选判定 / 探针上下行分支 / HTTP 与推流探针）；
2. VerifyEngine 后置分类（_post_classify_environment）与报告汇总
   （blocked-env 计入 warning、独立 blocked_env 字段）；
3. PMEngine 放行门禁（_handle_env_blocked_inconclusive）：真失败不降级、
   全批 blocked-env → inconclusive 重派、连续超限停机，以及今日噪声轮
   fixture（13/14 mock 假阴性）的回归断言。
"""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore
from core.pm_engine import PMEngine
from core.state_machine import StateMachine
from core.verify_engine import env_gate as eg
from core.verify_engine.engine import VerifyEngine

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "report_0827_noise.json"


class _SpecsSM:
    """admin_monitor 用——仅读 all 的最小状态机替身。"""

    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs


def _make_runs(proot: Path, entries: list):
    """写入 run 产物；entries: [(run_id, terminal)]，terminal in (error/done)。"""
    runs_dir = proot / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for run_id, terminal in entries:
        lines = []
        if terminal == "error":
            lines.append({"type": "error", "message": "boom", "num_turns": 3})
        else:
            lines.append({"type": "result", "result": "完成", "num_turns": 3})
        (runs_dir / f"{run_id}.jsonl").write_text(
            "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
            encoding="utf-8",
        )


class _FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


class _FakeBrowser:
    def __init__(self, base_url="", is_extension=False):
        self.base_url = base_url
        self.is_extension_project = is_extension


# ── env_gate 纯函数 ─────────────────────────────────────────────

class TestWaitTimeoutError(unittest.TestCase):
    def test_playwright_zero_tolerance_markers(self):
        for err in (
            "Timeout 3000ms exceeded.",
            "Timeout 5000ms exceeded.",
            "timeout waiting for locator: #app",
            "waiting for locator '.card' to be visible",
            "wait_for_selector: TimeoutError",
        ):
            self.assertTrue(eg.is_wait_timeout_error(err), err)

    def test_engine_wait_step_markers(self):
        for err in (
            "wait 超时: Timeout 10000ms exceeded.",
            "元素未出现：did not appear",
            "locator does not exist: #data",
        ):
            self.assertTrue(eg.is_wait_timeout_error(err), err)

    def test_business_errors_are_not_timeouts(self):
        for err in (
            "",
            None,
            "Expected '温暖' but got '寒冷'",
            "text mismatch: expected 3 items, got 0",
            "assertion failed: value 12 != 13",
            "API returned 500 with payload {err: boom}",
            "click intercepted by another element",
        ):
            self.assertFalse(eg.is_wait_timeout_error(err), repr(err))


class TestMockApiCandidate(unittest.TestCase):
    def _scenario(self, steps=None, assertions=None):
        return {"status": "fail", "step_results": steps or [], "assertion_results": assertions or []}

    def test_has_mock_api_step_true_when_present(self):
        s = self._scenario(steps=[
            {"action": "navigate", "success": True},
            {"action": "mock_api", "target": "https://x/**", "success": True},
        ])
        self.assertTrue(eg.has_mock_api_step(s))

    def test_has_mock_api_step_false_when_absent(self):
        s = self._scenario(steps=[{"action": "navigate", "success": True}])
        self.assertFalse(eg.has_mock_api_step(s))
        self.assertFalse(eg.has_mock_api_step({"step_results": "not-a-list"}))
        self.assertFalse(eg.has_mock_api_step({}))

    def test_candidate_mock_plus_wait_timeout(self):
        s = self._scenario(
            steps=[{"action": "mock_api", "success": True}],
            assertions=[{"pass": False, "error": "Timeout 5000ms exceeded."}],
        )
        self.assertTrue(eg.is_env_candidate(s))

    def test_candidate_step_wait_timeout_too(self):
        s = self._scenario(
            steps=[
                {"action": "mock_api", "success": True},
                {"action": "wait", "success": False, "error": "wait 超时: Timeout 10000ms exceeded."},
            ],
            assertions=[],
        )
        self.assertTrue(eg.is_env_candidate(s))

    def test_not_candidate_without_mock(self):
        s = self._scenario(
            steps=[{"action": "navigate", "success": True}],
            assertions=[{"pass": False, "error": "Timeout 5000ms exceeded."}],
        )
        self.assertFalse(eg.is_env_candidate(s))

    def test_not_candidate_mock_with_business_error(self):
        s = self._scenario(
            steps=[{"action": "mock_api", "success": True}],
            assertions=[{"pass": False, "error": "Expected '温暖' but got '寒冷'"}],
        )
        self.assertFalse(eg.is_env_candidate(s))

    def test_not_candidate_only_passed_items(self):
        s = self._scenario(
            steps=[{"action": "mock_api", "success": True}],
            assertions=[{"pass": True, "error": None}],
        )
        self.assertFalse(eg.is_env_candidate(s))


class TestFinalizeScenarioStatus(unittest.TestCase):
    def test_non_fail_status_unchanged_regardless_of_probe(self):
        for status in ("pass", "warning", "error"):
            for healthy in (True, False):
                self.assertEqual(
                    eg.finalize_scenario_status({"status": status}, healthy), status
                )

    def test_probe_healthy_keeps_fail(self):
        candidate = {
            "status": "fail",
            "step_results": [{"action": "mock_api", "success": True}],
            "assertion_results": [{"pass": False, "error": "Timeout 5000ms exceeded."}],
        }
        self.assertEqual(eg.finalize_scenario_status(candidate, probe_healthy=True), "fail")

    def test_probe_down_candidate_degrades(self):
        candidate = {
            "status": "fail",
            "step_results": [{"action": "mock_api", "success": True}],
            "assertion_results": [{"pass": False, "error": "Timeout 5000ms exceeded."}],
        }
        self.assertEqual(eg.finalize_scenario_status(candidate, probe_healthy=False), "blocked-env")

    def test_probe_down_non_candidate_stays_fail(self):
        s = {
            "status": "fail",
            "step_results": [{"action": "navigate", "success": True}],
            "assertion_results": [{"pass": False, "error": "Timeout 5000ms exceeded."}],
        }
        self.assertEqual(eg.finalize_scenario_status(s, probe_healthy=False), "fail")


class _FakeResp:
    """忠实模拟 http.client.HTTPResponse 的上下文管理器，status 为整数。"""

    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestProbeHttpHealth(unittest.TestCase):
    def test_healthy_endpoint(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(200)):
            self.assertTrue(eg.probe_http_health("http://127.0.0.1:8080", timeout=0.5))

    def test_all_endpoints_down(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            self.assertFalse(eg.probe_http_health("http://127.0.0.1:8080", timeout=0.5))

    def test_redirect_counts_healthy(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(302)):
            self.assertTrue(eg.probe_http_health("https://example.com", timeout=0.5))

    def test_http_error_status_is_down(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(500)):
            self.assertFalse(eg.probe_http_health("http://127.0.0.1:8080", timeout=0.5))

    def test_extension_scheme_conservatively_healthy(self):
        with mock.patch("urllib.request.urlopen") as m:
            self.assertTrue(
                eg.probe_http_health("chrome-extension://abc123/index.html", timeout=0.5)
            )
            m.assert_not_called()

    def test_empty_base_conservatively_healthy(self):
        self.assertTrue(eg.probe_http_health("", timeout=0.5))


class TestProbePushHealth(unittest.TestCase):
    def _run(self, loader):
        return asyncio.run(eg.probe_push_health(loader))

    async def _loader_ok(self):
        class L:
            async def navigate(self):
                return True

            async def wait_selector(self, sel, timeout_ms):
                return True

        return L()

    async def _loader_wait_raises(self):
        class L:
            async def navigate(self):
                return True

            async def wait_selector(self, sel, timeout_ms):
                raise TimeoutError("wait 超时")

        return L()

    async def _loader_nav_fails(self):
        class L:
            async def navigate(self):
                return False

        return L()

    def test_push_ok(self):
        self.assertTrue(self._run(asyncio.run(self._loader_ok())))

    def test_push_interrupted(self):
        self.assertFalse(self._run(asyncio.run(self._loader_wait_raises())))

    def test_navigate_failure_means_interrupted(self):
        self.assertFalse(self._run(asyncio.run(self._loader_nav_fails())))

    def test_loader_without_methods_conservatively_healthy(self):
        class L:
            pass

        self.assertTrue(self._run(L()))


# ── VerifyEngine 后置分类与报告 ─────────────────────────────────

class TestEnginePostClassify(unittest.TestCase):
    def setUp(self):
        self.engine = object.__new__(VerifyEngine)
        self.engine.logger = _FakeLogger()

    def _scenario(self, scenario_id, status="fail", mock_api=True, wait_error=True):
        steps = [{"action": "navigate", "success": True, "detail": "已导航到 http://127.0.0.1:5199/index.html"}]
        if mock_api:
            steps.append({"action": "mock_api", "target": "https://api.x/**", "success": True})
        if wait_error:
            steps.append({"action": "wait", "success": False, "error": "wait 超时: Timeout 10000ms exceeded."})
        return {
            "scenario_id": scenario_id,
            "status": status,
            "step_results": steps,
            "assertion_results": [{"pass": False, "error": "Timeout 5000ms exceeded."}]
            if wait_error
            else [{"pass": True}],
        }

    def test_no_candidates_skips_probe(self):
        self.engine.browser = _FakeBrowser(base_url="http://127.0.0.1:1/")
        results = [self._scenario("p1", status="pass", wait_error=False)]
        with mock.patch("core.verify_engine.engine.probe_http_health") as m:
            out = asyncio.run(self.engine._post_classify_environment([], results))
        m.assert_not_called()
        self.assertEqual(out["blocked_env"], 0)
        self.assertEqual(results[0]["status"], "pass")

    def test_probe_down_classifies_candidates_only(self):
        self.engine.browser = _FakeBrowser(base_url="http://127.0.0.1:1/")
        cand1 = self._scenario("c1")
        cand2 = self._scenario("c2")
        genuine = self._scenario("g1", mock_api=False, wait_error=True)
        results = [cand1, cand2, genuine]
        with mock.patch(
            "core.verify_engine.engine.probe_http_health", return_value=False
        ) as m:
            out = asyncio.run(self.engine._post_classify_environment([], results))
        m.assert_called_once()
        self.assertEqual(out["blocked_env"], 2)
        self.assertEqual(cand1["status"], "blocked-env")
        self.assertTrue(cand1["env_blocked"])
        self.assertEqual(cand2["status"], "blocked-env")
        self.assertEqual(genuine["status"], "fail", "非候选场景不得降级")
        self.assertEqual(self.engine._env_probe["healthy"], False)

    def test_probe_healthy_keeps_fail(self):
        self.engine.browser = _FakeBrowser(base_url="http://127.0.0.1:1/")
        cand = self._scenario("c1")
        with mock.patch(
            "core.verify_engine.engine.probe_http_health", return_value=True
        ) as m:
            out = asyncio.run(self.engine._post_classify_environment([], [cand]))
        m.assert_called_once()
        self.assertEqual(out["blocked_env"], 0)
        self.assertEqual(cand["status"], "fail")
        self.assertNotIn("env_blocked", cand)

    def test_probe_runs_once_and_is_memoized(self):
        self.engine.browser = _FakeBrowser(base_url="http://127.0.0.1:1/")
        cand = self._scenario("c1")
        with mock.patch(
            "core.verify_engine.engine.probe_http_health", return_value=False
        ) as m:
            asyncio.run(self.engine._post_classify_environment([], [cand]))
            asyncio.run(self.engine._post_classify_environment([], [cand]))
        m.assert_called_once()
        self.assertIsNotNone(self.engine._env_probe)

    def test_report_counts_blocked_env(self):
        engine = object.__new__(VerifyEngine)
        engine.spec_name = "s1"
        engine.logger = _FakeLogger()
        results = [
            {"scenario_id": "p", "status": "pass", "step_results": [], "assertion_results": []},
            {"scenario_id": "w", "status": "warning", "step_results": [], "assertion_results": []},
            {"scenario_id": "f", "status": "fail", "step_results": [], "assertion_results": []},
            {"scenario_id": "b1", "status": "blocked-env", "env_blocked": True, "step_results": [], "assertion_results": []},
            {"scenario_id": "b2", "status": "blocked-env", "env_blocked": True, "step_results": [], "assertion_results": []},
        ]
        report = engine._build_report(results)
        s = report["summary"]
        self.assertEqual(s["total"], 5)
        self.assertEqual(s["passed"], 1)
        self.assertEqual(s["failed"], 1)
        # blocked-env 计入 warning 但不计入 fail
        self.assertEqual(s["warnings"], 1 + 2)
        self.assertEqual(s["blocked_env"], 2)


# ── PMEngine 放行门禁 ───────────────────────────────────────────

class TestEnvBlockedInconclusive(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = _FakeLogger()
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        config = {"verify_engine": {"inconclusive_max_attempts": 3}}
        self.engine = PMEngine(self.sm, mock.MagicMock(), config, self.project_root, self.logger)
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.update_spec("s1", {"status": "implemented"})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _report(self, blocked_env=3, failed=0, errors=0, passed=0):
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

    def _queued_verifier(self):
        return any((e[1] == "s1" and e[2] == "verifier") for e in self.engine._dispatcher._run_queue)

    def test_genuine_failure_not_inconclusive(self):
        # 既有真实失败（非环境性）存在时若 blocked_env>0 也不得拦截
        report = self._report(blocked_env=1, failed=2)
        self.assertFalse(self.engine._verification._handle_env_blocked_inconclusive("s1", report))
        self.assertEqual(self.sm.read_one("s1")["status"], "implemented")

    def test_no_blocked_env_not_inconclusive(self):
        report = self._report(blocked_env=0, failed=1)
        self.assertFalse(self.engine._verification._handle_env_blocked_inconclusive("s1", report))

    def test_all_blocked_inconclusive_reenqueues(self):
        self.engine._dispatcher._run_queue.clear()
        report = self._report(blocked_env=3)
        self.assertTrue(self.engine._verification._handle_env_blocked_inconclusive("s1", report))
        spec = self.sm.read_one("s1")
        # 保持 implemented（verifier 派发门禁要求），error 标注重验次数
        self.assertEqual(spec["status"], "implemented")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 1)
        self.assertIn("环境性失联", spec["error"])
        self.assertIn("第 1/3 次重验", spec["error"])
        self.assertTrue(self._queued_verifier(), "应重新排队 verifier 进行新 attempt")

    def test_attempts_exhausted_holds_backoff(self):
        self.sm.update_spec("s1", {"_inconclusive_attempts": 2})
        report = self._report(blocked_env=3)
        self.assertTrue(self.engine._verification._handle_env_blocked_inconclusive("s1", report))
        spec = self.sm.read_one("s1")
        self.assertEqual(int(spec["_inconclusive_attempts"]), 3)
        self.assertIn("连续 3 轮", spec["error"])
        self.assertIn("请人工检查", spec["error"])
        self.assertGreaterEqual(int(spec["_dispatch_backoff_until"]), int(datetime.now(timezone.utc).timestamp()))
        self.assertEqual(self.sm.read_one("s1")["status"], "implemented")

    # ── 今日噪声轮 fixture 回归（task 1.4）──────────────────

    def test_fixture_noise_round_overall_inconclusive(self):
        """2026-08-27 13/14 假阴性轮：≥12 场景转 blocked-env、整体 inconclusive。"""
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        scenarios = fixture["scenarios"]

        engine = object.__new__(VerifyEngine)
        engine.spec_name = "mock-api-dashboard-sample"
        engine.logger = _FakeLogger()
        engine.browser = _FakeBrowser(base_url="http://127.0.0.1:1/")
        with mock.patch(
            "core.verify_engine.engine.probe_http_health", return_value=False
        ):
            probe_out = asyncio.run(engine._post_classify_environment([], scenarios))

        self.assertGreaterEqual(
            probe_out["blocked_env"], 12,
            "期望 ≥12 场景转 blocked-env（mock 假阴性），实际 %d" % probe_out["blocked_env"],
        )

        report = engine._build_report(scenarios)
        self.assertEqual(report["summary"]["total"], 14)
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertEqual(report["summary"]["failed"], 0, "全部失败应为环境性失联")
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["blocked_env"], 13)

        # PMEngine 门禁 → inconclusive（跳过 bug-found / repeated_failures 信号）
        self.sm.add_spec("mock-api-dashboard-sample", {"priority": 5})
        self.sm.update_spec("mock-api-dashboard-sample", {"status": "implemented"})
        self.engine._dispatcher._run_queue.clear()
        gate = self.engine._handle_env_blocked_inconclusive("mock-api-dashboard-sample", report)
        self.assertTrue(gate)
        spec = self.sm.read_one("mock-api-dashboard-sample")
        self.assertIn("环境性失联", spec["error"])
        self.assertIn("第 1/3 次重验", spec["error"])
        queued = any(
            e[1] == "mock-api-dashboard-sample" and e[2] == "verifier"
            for e in self.engine._dispatcher._run_queue
        )
        self.assertTrue(queued, "inconclusive 后应重队 verifier 新 attempt")

    def test_legacy_report_without_blocked_env_field_is_compatible(self):
        """旧版 report 无 blocked_env 字段 → 读为 0 → 不触发 inconclusive（design D5）。"""
        legacy = {
            "data_summary": {"scenarios": [{"status": "fail"}]},
            "summary": {"total": 1, "passed": 0, "warnings": 0, "failed": 1, "errors": 0},
        }
        self.assertFalse(self.engine._handle_env_blocked_inconclusive("s1", legacy))
        self.assertEqual(self.sm.read_one("s1")["status"], "implemented")


# ── 重验通道不烧信号预算（spec Scenario：连续 inconclusive 不唤醒 Administrator）──

class TestInconclusiveDoesNotBurnSignalBudget(unittest.TestCase):
    """两次连续 inconclusive 轮次不产生 error 终态 run → repeated_failures 不累积。

    admin_monitor 只统计窗口内终态为 error 的 run 产物；inconclusive 门禁在 judge
    前返回、不写 error run，因此连续重验不唤醒 Administrator。
    """

    def _monitor(self, tmp, specs, proot):
        mon = AdminMonitor(
            {}, _SpecsSM(specs), proot, _FakeLogger(),
            store=AdminStore(proot, _FakeLogger()),
        )
        return mon

    def test_two_consecutive_inconclusive_rounds_no_signal(self, ):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            proot = tmpdir / "proj"
            proot.mkdir(parents=True, exist_ok=True)
            # 两次 inconclusive 重验：spec 处于 testing（进行中），产物仅成功轮次
            _make_runs(proot, [
                ("planner-plan-noisy-1780000001", "done"),
                ("planner-plan-noisy-1780000002", "done"),
            ])
            mon = self._monitor(proot, {
                "noisy": {"status": "testing", "updated": datetime.now(timezone.utc).isoformat()},
            }, proot)
            signals = mon.run_once()
            self.assertFalse(
                any(s["signal_type"] == "repeated_failures" for s in signals),
                f"连续 inconclusive 不得产生 repeated_failures 信号，实际: {signals}",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_control_error_runs_still_detect(self):
        """对照：真失败 run（error 终态）仍被检测到（证明检测链路本身有效）。"""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            proot = tmpdir / "proj"
            proot.mkdir(parents=True, exist_ok=True)
            _make_runs(proot, [
                ("planner-judge-noisy-1780000001", "error"),
                ("planner-judge-noisy-1780000002", "error"),
                ("planner-judge-noisy-1780000003", "error"),
            ])
            mon = self._monitor(proot, {
                "noisy": {"status": "testing", "updated": datetime.now(timezone.utc).isoformat()},
            }, proot)
            signals = mon.run_once()
            self.assertTrue(
                any(s["signal_type"] == "repeated_failures" for s in signals),
                "控制组：3 个 error 终态 run 应触发 repeated_failures",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()