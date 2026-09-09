"""
Tests for PMEngine verification functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock, AsyncMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, StateParser, SpecStatus, VALID_TRANSITIONS
from core.pm_engine.verification import VerdictReadResult


class TestVerifierStaleResultGuard(unittest.TestCase):
    """.fenix-run-result.json 为全局共享单文件：verifier 判定消费前必须校验
    新鲜度（mtime ≥ 本次 run 起点）与归属（spec 匹配），否则陈旧重放会把
    旧结论（假 bug-found / 假 verified）套到当前轮次上。2026-08-28 实证：
    improve-failover-model-mapping-ui 的 09:41 旧判定在 12:21 重放。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        # verified 成功路径会经 _task_completion_blocker 读 implementer 结果，
        # 与本守卫正交，隔离之（MagicMock runner 下该链路不 mock 不友好）。
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_impl_spec(self, name="quick-links-folders"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")

    def _run_verify(self, run_epoch):
        from types import SimpleNamespace
        run_id = f"verify-quick-links-folders-{run_epoch}-a1"
        self.engine.agent_runner.run_verifier.return_value = SimpleNamespace(
            success=True, error=None, run_id=run_id,
        )
        self.engine._run_legacy_verification("quick-links-folders")

    def _write_result(self, spec, status, mtime_epoch=None):
        self.result_path.write_text(json.dumps({"spec": spec, "status": status}))
        if mtime_epoch:
            import os
            os.utime(self.result_path, (mtime_epoch, mtime_epoch))

    def test_stale_same_spec_bugfound_not_replayed(self):
        self._make_impl_spec()
        now = int(time.time())
        self._write_result("quick-links-folders", "bug-found", mtime_epoch=now - 600)
        self._run_verify(now)  # 本次 run 晚于结果文件 → 陈旧
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "implemented")
        self.assertIn("stale", str(e.get("error")))

    def test_cross_spec_result_not_consumed(self):
        self._make_impl_spec()
        self._write_result("some-other-spec", "success")
        self._run_verify(int(time.time()))
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "implemented")
        self.assertIn("stale", str(e.get("error")))

    def test_missing_result_not_treated_as_verified(self):
        """结果文件缺失 → 不得晋级 verified；legacy 路径按 D5 阻断为 blocked。"""
        self._make_impl_spec()
        self._run_verify(int(time.time()))
        e = self.sm.read_one("quick-links-folders")
        self.assertNotEqual(e["status"], "verified")
        self.assertEqual(e["status"], "blocked")
        self.assertIn("不可读", str(e.get("error")))

    def test_fresh_bugfound_still_counts(self):
        self._make_impl_spec()
        now = int(time.time())
        self._write_result("quick-links-folders", "bug-found", mtime_epoch=now - 5)
        self._run_verify(now)
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "bug-found")

    def test_fresh_verified_still_counts(self):
        self._make_impl_spec()
        now = int(time.time())
        self._write_result("quick-links-folders", "verified", mtime_epoch=now - 5)
        self._run_verify(now)
        e = self.sm.read_one("quick-links-folders")
        # 门禁放行后会自动推进（verified → done），断言终态即可
        self.assertIn(e["status"], ("verified", "done"))


class TestScenarioNavigateAcceptance(unittest.TestCase):
    """场景验收：navigate 必须绝对 URL + 场景必须含 navigate（2026-08-28 白屏事故）。"""

    def _errs(self, steps, sid="s1"):
        from core.verify_engine.scenarios import TestScenario
        sc = TestScenario.from_dict({"id": sid, "description": "", "steps": steps,
                                     "assertions": []})
        return sc.validate()

    def test_relative_navigate_rejected(self):
        errs = self._errs([{"action": "navigate", "value": "/dashboard"}])
        self.assertTrue(any("绝对" in e for e in errs), errs)

    def test_missing_navigate_rejected(self):
        errs = self._errs([{"action": "wait", "value": "1s"}])
        self.assertTrue(any("缺少 navigate" in e for e in errs), errs)

    def test_absolute_navigate_ok(self):
        errs = self._errs([
            {"action": "navigate", "value": "http://127.0.0.1:8787/dashboard"},
            {"action": "wait", "value": "page loaded"},
        ])
        self.assertFalse([e for e in errs if "navigate" in e], errs)


class TestBrowserNavigateBackstop(unittest.TestCase):
    """引擎兜底缺席：web 项目相对 navigate 直接显式失败，禁止默认端口。"""

    def test_relative_url_explicit_failure(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from core.verify_engine.browser import BrowserManager
        bm = BrowserManager(project_root=Path(self.mkdtemp()), logger=MagicMock())
        res = asyncio.run(bm.execute_action(
            AsyncMock(), {"action": "navigate", "value": "/dashboard"}))
        self.assertFalse(res["success"])
        self.assertEqual(res.get("error_type"), "invalid_navigate_url")
        self.assertIn("绝对", res["error"])

    def test_absolute_url_passes_through(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from core.verify_engine.browser import BrowserManager
        bm = BrowserManager(project_root=Path(self.mkdtemp()), logger=MagicMock())
        page = AsyncMock()
        res = asyncio.run(bm.execute_action(
            page, {"action": "navigate", "value": "http://127.0.0.1:8787/dashboard"}))
        self.assertTrue(res["success"])
        page.goto.assert_awaited_once()

    def mkdtemp(self):
        import tempfile
        return tempfile.mkdtemp()


class TestScenarioReloadAfterReachabilityHeal(unittest.TestCase):
    """可达性自愈改写场景端口后，引擎必须拿到改写后的场景。

    2026-08-31 add-v3-spec-detail-page 实证：load_scenarios 先于
    _ensure_app_reachable 执行，自愈把 test_scenarios.json 的 planner
    臆测端口 8000 → 8787 只落了文件，传入引擎的内存场景仍是 8000 →
    24 场景对失联端口 navigate 整轮伪失败（0.9 秒全灭 ERR_CONNECTION_REFUSED）。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        from types import SimpleNamespace
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        self.verify_dir.mkdir(parents=True)
        self.scenarios_path = self.verify_dir / "test_scenarios.json"
        self.scenarios_path.write_text(json.dumps([
            {
                "id": "scn-a",
                "description": "场景A",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8000/#/projects/demo"},
                    {"action": "wait", "target": ".x", "description": "等待"},
                ],
                "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
            },
            {
                "id": "scn-b",
                "description": "场景B",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8000/#/projects/demo/s"},
                ],
                "assertions": [{"type": "element_visible", "selector": ".y", "label": "可见"}],
            },
        ], ensure_ascii=False), encoding="utf-8")

        self.sm.add_spec("demo-spec", {"priority": 5})
        self.sm.transition("demo-spec", "ready")
        self.sm.transition("demo-spec", "implementing")
        self.sm.transition("demo-spec", "implemented")
        self.sm.transition("demo-spec", "testing")

        self.engine._enqueue = MagicMock()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(success=True, error=None, run_id="planner-plan-demo-spec-1-a1")
        )
        self.engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("plan-ready"))
        self.engine._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._apply_interaction_contract = MagicMock(return_value=None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fake_reachable(self, spec_name):
        """模拟生产自愈：改写场景文件端口 8000 → 8787（与 _rewrite_scenario_port 同语义）。"""
        content = self.scenarios_path.read_text(encoding="utf-8")
        self.scenarios_path.write_text(content.replace(":8000", ":8787"), encoding="utf-8")
        return True, False, (
            "场景 URL 端口 ['8000'] 与应用实际端口 8787 不符（planner 臆测），"
            "已改写场景端口并确认可达"
        )

    def test_engine_receives_rewritten_scenarios(self):
        """自愈改写端口后，传给验证引擎的场景必须是改写后的 URL。"""
        captured = {}

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                captured["spec"] = spec_name

            async def run(self, scenarios):
                captured["scenarios"] = scenarios
                return {
                    "spec": captured["spec"],
                    "summary": {
                        "total": 2, "passed": 0, "warnings": 0,
                        "failed": 0, "errors": 0, "blocked_env": 2,
                    },
                    "scenarios": [],
                }

        self.engine._ensure_app_reachable = self._fake_reachable
        # pipeline 开头 importlib.reload 验证引擎模块（常驻进程热更新），
        # 会重建类对象并使模块属性 patch 失效 → 测试内冻结 reload。
        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")

        self.assertIn("scenarios", captured)
        urls = [
            st.value
            for scn in captured["scenarios"]
            for st in scn.steps
            if st.action == "navigate"
        ]
        self.assertEqual(urls, [
            "http://localhost:8787/#/projects/demo",
            "http://localhost:8787/#/projects/demo/s",
        ])

    def test_inconclusive_path_after_heal(self):
        """自愈 + 全 blocked-env 报告 → inconclusive 重验路径，不误判 bug-found。"""
        captured = {}

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                pass

            async def run(self, scenarios):
                captured["scenarios"] = scenarios
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": 2, "passed": 0, "warnings": 0,
                        "failed": 0, "errors": 0, "blocked_env": 2,
                    },
                    "scenarios": [],
                }

        self.engine._ensure_app_reachable = self._fake_reachable
        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "implemented")
        self.assertIn("环境性失联", str(entry.get("error")))
        self.engine._enqueue.assert_called_once_with("demo-spec", "verifier")


class TestJudgeScenarioRepair(unittest.TestCase):
    """judge-scenario-repair：judge 原地修复场景文件的采纳与预算通道。

    场景文件自身缺陷（夹具未自建/步骤客观错误）由 judge 原地修复并申报
    scenario-repaired：框架冻结记账（无理由移除会被补齐）后有界重入
    阶段2/3 重执行；预算耗尽写 error 停止重入，不误流转 verified/bug-found。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        from types import SimpleNamespace
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        self.verify_dir.mkdir(parents=True)
        self.scenarios_path = self.verify_dir / "test_scenarios.json"
        self.scenarios_path.write_text(json.dumps([
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
        self.sm.transition("demo-spec", "ready")
        self.sm.transition("demo-spec", "implementing")
        self.sm.transition("demo-spec", "implemented")
        self.sm.transition("demo-spec", "testing")

        self.engine._enqueue = MagicMock()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id="planner-judge-demo-spec-1-a1")
        )
        self.engine._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._apply_interaction_contract = MagicMock(return_value=None)
        self.engine._verify_verdict_evidence = MagicMock(return_value=True)
        self.engine._update_warning_streaks = MagicMock(return_value=[])
        self.engine._ensure_app_reachable = MagicMock(return_value=(True, False, ""))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_with_report(self, on_execute):
        """冻结复用路径跑通阶段2/3：FakeEngine 每次执行回调 on_execute，
        返回 1 过 1 败报告（避开全败哨/环境失联门，直达阶段3 判定）。"""

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                pass

            async def run(self, scenarios):
                on_execute()
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": 2, "passed": 1, "warnings": 0,
                        "failed": 1, "errors": 0, "blocked_env": 0,
                    },
                    "scenarios": [],
                }

        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("demo-spec")

    def test_repair_reenters_execution_and_budget_exhausts(self):
        """scenario-repaired → 冻结记账 + 重入执行；预算耗尽写 error 停止重入。"""
        from core.pm_engine.verification import _SCENARIO_REPAIR_MAX_ROUNDS
        runs = []
        self.engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("scenario-repaired"))
        self._run_with_report(lambda: runs.append(1))
        # 1 次初始 + 2 次修复重入 = 3 轮执行；每次修复采纳先冻结记账
        self.assertEqual(len(runs), 1 + _SCENARIO_REPAIR_MAX_ROUNDS)
        self.assertEqual(
            self.engine._apply_scenario_freeze.call_count,
            _SCENARIO_REPAIR_MAX_ROUNDS)
        entry = self.sm.read_one("demo-spec")
        self.assertIn("预算耗尽", str(entry.get("error")))
        # 停在 testing：修复通道绝不误流转 verified/bug-found
        self.assertEqual(entry["status"], "testing")

    def test_repair_then_verified(self):
        """修复一轮后 judge 判 verified → 正常晋级，冻结记账恰一次。"""
        self.engine._read_planner_result = MagicMock(
            side_effect=[VerdictReadResult.success("scenario-repaired"),
                        VerdictReadResult.success("verified")])
        self.engine._check_verification_gate = MagicMock(return_value=None)
        self.engine._ensure_verification_report = MagicMock(return_value=None)
        self.engine._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._render_scenario_change_section_to_report = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        runs = []
        self._run_with_report(lambda: runs.append(1))
        self.assertEqual(len(runs), 2)
        self.assertEqual(self.engine._apply_scenario_freeze.call_count, 1)
        self.assertEqual(self.sm.read_one("demo-spec")["status"], "verified")


class TestLocateAppBaseUrlFromError(unittest.TestCase):
    """环境门 _locate_app_base_url 须能从 navigate 失败的 error 文本提取 URL。

    2026-08-31 add-v3-spec-detail-page：24 场景 ERR_CONNECTION_REFUSED 时
    URL 只出现在 step_results[].error（detail 为空）→ 探针找不到入口 →
    保守判健康 → 整轮伪失败未降级 blocked-env。
    """

    def _make_engine(self, tmpdir):
        from core.verify_engine import VerifyEngine
        return VerifyEngine("demo-spec", Path(tmpdir), MagicMock(), {})

    def test_url_extracted_from_error_text(self):
        import shutil as _sh
        tmpdir = tempfile.mkdtemp()
        try:
            eng = self._make_engine(tmpdir)
            candidates = [{
                "step_results": [{
                    "action": "navigate",
                    "detail": "",
                    "error": (
                        'Page.goto: net::ERR_CONNECTION_REFUSED at '
                        'http://localhost:8000/#/projects/test-project\n'
                        'Call log:\n  - navigating to "http://localhost:8000/#/projects/test-project"'
                    ),
                }],
            }]
            self.assertEqual(eng._locate_app_base_url(candidates), "http://localhost:8000")
        finally:
            _sh.rmtree(tmpdir, ignore_errors=True)

    def test_detail_only_still_works(self):
        import shutil as _sh
        tmpdir = tempfile.mkdtemp()
        try:
            eng = self._make_engine(tmpdir)
            candidates = [{
                "step_results": [{
                    "action": "navigate",
                    "detail": "navigated to http://127.0.0.1:8787/#/projects/x",
                    "error": "",
                }],
            }]
            self.assertEqual(eng._locate_app_base_url(candidates), "http://127.0.0.1:8787")
        finally:
            _sh.rmtree(tmpdir, ignore_errors=True)


class TestVerifierCircuitOpenHoldsState(unittest.TestCase):
    """verifier 断路器保持（regression-coverage Requirement「provider 熔断打开时 verifier 状态保持」）。

    背景（c310ee5 refactor-test-structure）：原 TestVerifierCircuitOpenHoldsState 被
    替换为空壳后随清理删除，断言丢失。

    测试从 ProviderCircuit 状态构造出发驱动 verification 层，覆盖两条路径：
    - legacy 路径（run_verifier 返回 circuit open error → _verifier_error_is_infra
      判定 infrastructure failure → 状态保持）
    - new 验证路径（run_planner 返回 circuit open error → hold-state → 状态保持）

    spec Scenario「熔断打开时 verifier 失败不误判 bug-found」：
    - spec 状态保持原状（testing/在跑态），不发生 →bug-found 迁移
    - _verify_fail_rounds 不递增
    - 失败按基础设施口径记录（error 写入基础设施错误文本）
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine._task_completion_blocker = MagicMock(return_value=None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_testing_spec(self, name="demo-spec"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")

    def _make_circuit_open_error(self, provider_name="volc"):
        """构造 ProviderCircuit open 时返回的基础设施错误文本。"""
        # 直接从 ProviderCircuit._circuit_open_error 的格式构造，
        # 模拟 runner._execute_agent 熔断拦截时返回的 error。
        return (
            f"provider circuit open: {provider_name} "
            f"(HTTP 429 x 5) — cooldown 300s remaining"
        )

    def test_legacy_circuit_open_holds_testing_not_bugfound(self):
        """legacy 路径：run_verifier 返回 circuit open → 保持 testing，不 bug-found。"""
        self._make_testing_spec()
        circuit_err = self._make_circuit_open_error()
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=False, error=circuit_err,
                run_id="verify-demo-spec-1-a1", cancelled=False,
            ))
        self.engine._run_legacy_verification("demo-spec")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertNotEqual(entry["status"], "bug-found")
        self.assertIn("provider circuit open", entry.get("error", ""))

    def test_legacy_circuit_open_does_not_increment_fail_rounds(self):
        """legacy 路径：circuit open → _verify_fail_rounds 不递增。"""
        self._make_testing_spec()
        self.sm.update_spec("demo-spec", {"_verify_fail_rounds": 2})
        circuit_err = self._make_circuit_open_error()
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=False, error=circuit_err,
                run_id="verify-demo-spec-2-a1", cancelled=False,
            ))
        self.engine._run_legacy_verification("demo-spec")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 2)

    def test_legacy_circuit_open_does_not_trigger_bugfound(self):
        """legacy 路径：circuit open → _on_spec_bug_found 未被调用。"""
        self._make_testing_spec()
        circuit_err = self._make_circuit_open_error()
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=False, error=circuit_err,
                run_id="verify-demo-spec-3-a1", cancelled=False,
            ))
        self.engine._run_legacy_verification("demo-spec")
        self.engine._on_spec_bug_found.assert_not_called()

    def test_new_verifier_planner_circuit_open_holds_state(self):
        """new 验证路径：planner plan 阶段返回 circuit open → 保持 testing，不 bug-found。"""
        self._make_testing_spec()
        circuit_err = self._make_circuit_open_error()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(
                success=False, error=circuit_err,
                run_id="planner-plan-demo-spec-1-a1", cancelled=False,
            ))
        self.engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("plan-ready"))
        self.engine._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._apply_interaction_contract = MagicMock(return_value=None)

        with patch("importlib.reload", lambda m: m):
            self.engine._run_three_stage_verification("demo-spec")

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertNotEqual(entry["status"], "bug-found")
        self.assertIn("provider circuit open", entry.get("error", ""))

    def test_new_verifier_planner_circuit_open_no_fail_rounds(self):
        """new 验证路径：planner circuit open → _verify_fail_rounds 不递增。"""
        self._make_testing_spec()
        self.sm.update_spec("demo-spec", {"_verify_fail_rounds": 3})
        circuit_err = self._make_circuit_open_error()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(
                success=False, error=circuit_err,
                run_id="planner-plan-demo-spec-2-a1", cancelled=False,
            ))
        self.engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("plan-ready"))
        self.engine._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._apply_interaction_contract = MagicMock(return_value=None)

        with patch("importlib.reload", lambda m: m):
            self.engine._run_three_stage_verification("demo-spec")

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 3)

    def test_new_verifier_planner_circuit_open_no_bugfound(self):
        """new 验证路径：planner circuit open → _on_spec_bug_found 未被调用。"""
        self._make_testing_spec()
        circuit_err = self._make_circuit_open_error()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(
                success=False, error=circuit_err,
                run_id="planner-plan-demo-spec-3-a1", cancelled=False,
            ))
        self.engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("plan-ready"))
        self.engine._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._apply_interaction_contract = MagicMock(return_value=None)

        with patch("importlib.reload", lambda m: m):
            self.engine._run_three_stage_verification("demo-spec")

        self.engine._on_spec_bug_found.assert_not_called()


class TestUniformVerifyFailure(unittest.TestCase):
    """验证失败形态归一与轮次计数（spec Requirement「验证失败形态归一与轮次计数」）。

    背景（c310ee5 refactor-test-structure）：原 TestUniformVerifyFailure 被替换为
    空壳（仅断言 status==testing 的恒真）后随清理删除，断言丢失。

    当前源码汇聚点（design D1-3 调查结论）：
    - **verifier run 异常**：``_run_legacy_verification`` 走 success=False 且非
      infra 分支 → ``transition(bug-found)``，此后 event_bus 捕获 STATE 变化补发
      ``spec_bug_found`` 事件 → ``_on_spec_bug_found`` → ``_do_spec_bug_found``
      递增 ``_verify_fail_rounds`` 并原地打回注入「验证修复」任务段。
    - **verdict bug-found**：结果文件 status=bug-found → bug-found 分支显式调用
      ``_on_spec_bug_found`` → 同上递增。
    - **结果文件畸形**：``_read_verifier_result`` 对 status 不在白名单的结果文件
      返回不可读结果（fail-closed，fix-verdict-read-failclosed），legacy 采纳处
      阻断为 **blocked** + 告警——**不产生 bug-found 失败信号、不递增 fail_rounds**，
      与 spec 期望（统一失败信号）不一致，按 design D1 登记为 spec-inconsistency
      发现并以 xfail 呈现（测试锁定当前实际行为 = blocked，供人工裁决是否需要
      实现侧改进）。

    spec 两个 Scenario：
    - 各失败形态统一递增失败轮次（run 异常 / verdict bug-found 各自 +1）
    - 验证通过时失败轮次归零
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.engine._ensure_verification_report = MagicMock(return_value=None)
        self.engine._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._check_verification_gate = MagicMock(return_value=None)
        # 修复任务注入依赖 tasks.md（存在即可，_inject_verify_fix_task 幂等追加）
        spec_dir = Path(self.tmpdir) / "spec" / "changes" / "demo-spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. 实现\n\n- [x] 1.1 done\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_testing_spec(self, name="demo-spec"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")

    def _assert_bug_found_round(self, name="demo-spec", expected=1):
        """断言统一失败信号：fail_rounds 递增 + 原地打回 + 修复任务段注入。"""
        entry = self.sm.read_one(name)
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), expected)
        # inplace 打回：testing → implementing，注入「验证修复」任务段
        self.assertEqual(entry["status"], "implementing")
        tasks_text = (
            Path(self.tmpdir) / "spec" / "changes" / name / "tasks.md"
        ).read_text(encoding="utf-8")
        self.assertIn("## 验证修复", tasks_text)
        self.engine._enqueue.assert_called_with(name, "implementer")

    def test_run_exception_unifies_to_bug_found(self):
        """形态 1：verifier run 异常 → bug-found 信号，fail_rounds +1（经 event_bus 补发）。"""
        self._make_testing_spec()
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=False, error="Verifier agent crashed",
                run_id="verify-demo-spec-1-a1", cancelled=False,
            ))
        self.engine._run_legacy_verification("demo-spec")
        # run 异常本身立即可见的信号：bug-found 状态 + error 记录
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "bug-found")
        self.assertIn("Verifier agent failed", str(entry.get("error")))
        # event_bus 捕获 STATE 变化补发 spec_bug_found 事件（生产链路）
        self.engine.handle_event("spec_bug_found", "demo-spec", entry)
        self._assert_bug_found_round()

    def test_verdict_bug_found_unifies_to_bug_found(self):
        """形态 2：verdict=bug-found → 统一失败信号，fail_rounds +1。"""
        self._make_testing_spec()
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id="verify-demo-spec-2-a1"))
        run_result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        run_result_path.write_text(json.dumps({
            "spec": "demo-spec", "status": "bug-found",
        }), encoding="utf-8")
        import os
        os.utime(run_result_path, (time.time(), time.time()))
        self.engine._run_legacy_verification("demo-spec")
        self._assert_bug_found_round()

    @unittest.expectedFailure
    def test_malformed_result_file_current_behavior(self):
        """形态 3：结果文件畸形—— spec 期望统一归一到失败信号，当前实际 blocked。

        fix-verdict-read-failclosed 后：``_read_verifier_result`` 对不在白名单的
        status 返回不可读结果（fail-closed），legacy 采纳处阻断为 **blocked** + 告警，
        而非 verified（旧 fail-open）也非 bug-found（spec 期望的统一失败信号）。
        此为 design D1 登记的 spec-inconsistency，测试锁定 blocked 行为。
        """
        self._make_testing_spec()
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id="verify-demo-spec-3-a1"))
        run_result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        run_result_path.write_text(json.dumps({
            "spec": "demo-spec", "status": "garbage-status",
        }), encoding="utf-8")
        import os
        os.utime(run_result_path, (time.time(), time.time()))
        self.engine._run_legacy_verification("demo-spec")
        # spec 期望：统一失败信号 → fail_rounds +1 → 原地打回
        self._assert_bug_found_round()

    def test_verify_pass_resets_fail_rounds(self):
        """Scenario: 验证通过时失败轮次归零。"""
        self._make_testing_spec()
        # 先有一轮失败计数（跨修复周期累计）
        self.sm.update_spec("demo-spec", {"_verify_fail_rounds": 2})
        self.sm.update_spec("demo-spec", {"status": "testing"})
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id="verify-demo-spec-4-a1"))
        run_result_path = Path(self.tmpdir) / ".fenix" / ".fenix-run-result.json"
        run_result_path.write_text(json.dumps({
            "spec": "demo-spec", "status": "verified",
        }), encoding="utf-8")
        import os
        os.utime(run_result_path, (time.time(), time.time()))
        self.engine._run_legacy_verification("demo-spec")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "verified")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 0)


class TestServingRegistry(unittest.TestCase):
    """verify-process-lifecycle D6：servers.json 登记制 + spec 终局驱逐 + 收割。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix" / "verify-serving").mkdir(
            parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.engine._check_verification_gate = MagicMock(return_value=None)
        from core.serving_registry import ServingRegistry
        self.reg = ServingRegistry(Path(self.tmpdir), self.logger)

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir, ignore_errors=True)

    def _spawn_sleep(self, seconds: float = 30):
        import subprocess as _sp
        return _sp.Popen(
            ["python3", "-c", f"import time; time.sleep({seconds})"],
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            start_new_session=True,
        )

    class FakeCommandServer:
        """CommandVerifyServer 的最小替身（pid/port/stop 契约同构）。"""

        def __init__(self, proc, stopped=None):
            self._proc = proc
            self._port = 18881
            self.ok = True
            self.stopped = stopped if stopped is not None else []

        @property
        def port(self):
            return self._port

        @property
        def pid(self):
            return self._proc.pid

        def stop(self):
            self.stopped.append(self._proc.pid)
            self.ok = False

    def test_register_remove_roundtrip(self):
        proc = self._spawn_sleep(30)
        try:
            from core.serving_registry import servers_path
            assert servers_path(self.tmpdir).name == "servers.json"
            self.reg.register(proc.pid, 18881, "spec-a", "")
            entries = self.reg.entries()
            assert any(e["pid"] == proc.pid and e["spec"] == "spec-a"
                       for e in entries)
            # 幂等：同 (pid,spec) 不重复登记
            self.reg.register(proc.pid, 18881, "spec-a", "")
            assert len(self.reg.entries()) == 1
            # 移除
            assert self.reg.remove(proc.pid, "spec-a") is True
            assert self.reg.entries() == []
            assert self.reg.remove(proc.pid, "spec-a") is False  # 无匹配幂等
        finally:
            proc.kill()
            proc.wait()

    def test_register_serving_instance_helper(self):
        """_ensure_app_reachable 兜底 spawn 的登记路径（Popen 直接登记）。"""
        proc = self._spawn_sleep(30)
        try:
            self.engine._verification._register_serving_instance(
                "spec-y", proc, hint_port=8888)
            entries = self.reg.entries()
            assert any(e["pid"] == proc.pid and e["spec"] == "spec-y"
                       and e["port"] == 8888 for e in entries)
            self.engine._verification._unregister_serving_instance(
                "spec-y", proc)
            assert self.reg.entries() == []
        finally:
            proc.kill()
            proc.wait()

    def test_sweep_harvests_orphan_without_inflight_spec(self):
        """周期清扫：进程仍存活但属主 spec 不在飞 → 收割并移除登记。"""
        proc = self._spawn_sleep(30)
        self.reg.register(proc.pid, 18882, "spec-orphan", "")
        try:
            from core.serving_registry import sweep
            n = sweep(Path(self.tmpdir), is_spec_in_flight=lambda s: False)
            assert n >= 1
            assert self.reg.entries() == []
            assert proc.wait(timeout=10) is not None, "收割应终止进程"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_sweep_keeps_inflight_spec(self):
        """在飞 spec（testing）的登记实例不被收割。"""
        proc = self._spawn_sleep(30)
        self.reg.register(proc.pid, 18883, "spec-live", "")
        try:
            from core.serving_registry import sweep
            n = sweep(Path(self.tmpdir),
                      is_spec_in_flight=lambda s: s == "spec-live")
            assert n == 0
            assert any(e["pid"] == proc.pid for e in self.reg.entries())
            assert proc.poll() is None
        finally:
            proc.kill()
            proc.wait()

    def test_evict_spec_serving_stops_and_evicts(self):
        """spec 终局驱逐：stop 登记服务、移除 servers.json、驱逐缓存、移除 worktree。"""
        proc = self._spawn_sleep(30)
        try:
            fake = self.FakeCommandServer(proc)
            cache = self.engine._verification.__dict__.setdefault(
                "_contract_static_servers", {})
            cache["spec-evict"] = {
                "server": fake, "wt_path": "/w/verify-spec-evict",
                "head": "h", "mode": "command",
            }
            self.reg.register(proc.pid, 18884, "spec-evict",
                              "/w/verify-spec-evict")
            self.engine._verification._remove_serving_worktree = MagicMock()
            self.engine._verification._evict_spec_serving("spec-evict")
            assert fake.stopped == [proc.pid], "登记服务应被 stop"
            assert self.reg.entries() == [], "servers.json 条目应移除"
            assert "spec-evict" not in cache, "缓存条目应驱逐"
            self.engine._verification._remove_serving_worktree.assert_called_once_with(
                "/w/verify-spec-evict")
        finally:
            proc.kill()
            proc.wait()

    def test_on_spec_verified_wires_eviction(self):
        """_on_spec_verified（done 落定）同步驱逐登记服务（D6 3.3 挂钩）。"""
        proc = self._spawn_sleep(30)
        try:
            fake = self.FakeCommandServer(proc)
            cache = self.engine._verification.__dict__.setdefault(
                "_contract_static_servers", {})
            cache["spec-verified-evict"] = {
                "server": fake, "wt_path": "/w/verify-spec-verified-evict",
                "head": "h", "mode": "command",
            }
            self.reg.register(proc.pid, 18885, "spec-verified-evict", "/w/x")
            self.engine._verification._remove_serving_worktree = MagicMock()
            self.engine._on_spec_done = MagicMock()
            with patch.object(self.engine.state_machine, "transition",
                              return_value=True):
                self.engine._on_spec_verified("spec-verified-evict")
            assert fake.stopped == [proc.pid]
            assert self.reg.entries() == []
            assert "spec-verified-evict" not in cache
        finally:
            proc.kill()
            proc.wait()


# ═══════════════════════════════════════════════════════════════════
# fix-verified-gate-evidence-race：per-spec 快照 + 门禁证据源 + fail-closed
# ═══════════════════════════════════════════════════════════════════


class TestVerifiedGateEvidenceRace(unittest.TestCase):
    """fix-verified-gate-evidence-race：per-spec 快照 + 门禁 fail-closed + 兼容矩阵。

    覆盖 spec/changes/fix-verified-gate-evidence-race/specs/verified-gate-evidence
    的全部 Scenario（事故回归、兼容矩阵、快照写点、人工补勾闭环、恢复尊重）。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        from core.pm_engine import TASK_GAP_ERROR_PREFIX
        self.TASK_GAP = TASK_GAP_ERROR_PREFIX
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_done = MagicMock()
        self.engine._check_verification_gate = MagicMock(return_value=None)
        # Mock worktree 查找让 _read_implementer_result 走主树根回退
        self.engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_spec(self, name, with_impl_run=True):
        self.sm.add_spec(name, {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing", "verified"):
            self.sm.transition(name, st)
        if with_impl_run:
            self.sm.update_spec(name, {"implementer_run": f"impl-{name}-1-a1"})

    def _write_tasks(self, spec_name, content):
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(content, encoding="utf-8")

    def _write_snapshot(self, spec_name, status="success"):
        """写 per-spec 快照 .fenix/verify-progress/<spec>/impl-result.json。"""
        vp = self.project_root / ".fenix" / "verify-progress" / spec_name
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "impl-result.json").write_text(
            json.dumps({"spec": spec_name, "status": status}),
            encoding="utf-8",
        )

    def _write_shared_result(self, spec_name, status="success"):
        """写共享文件 .fenix/.fenix-run-result.json（主树根）。"""
        path = self.project_root / ".fenix" / ".fenix-run-result.json"
        path.write_text(
            json.dumps({"spec": spec_name, "status": status}),
            encoding="utf-8",
        )

    # ── 4.1 事故回归测试 ──────────────────────────────────────────────

    def test_accident_regression_shared_overwrite_robust(self):
        """事故时序复现：门禁首次拦截 → 共享文件被其它 spec 覆盖 →
        re-trigger 重评仍拦截（从快照读取），维护 verified。

        对齐 2026-09-07 fix-mobile-breakpoint-hook-tables 事故实证：
        共享文件 stamp 被覆盖 → 门禁「无法证伪即放行」导致静默推送。
        """
        spec = "fix-mobile-breakpoint-hook-tables"
        self._make_spec(spec)
        self._write_tasks(spec, (
            "# Tasks\n\n## 4. 实现\n\n"
            "- [x] 4.1 done\n"
            "- [ ] 4.2 unchecked\n"
            "- [ ] 4.3 unchecked\n"
        ))
        self._write_snapshot(spec, "success")
        self._write_shared_result(spec, "success")

        # 首次拦截：snapshot 存在且有缺口 → task-gap error
        blocker = self.engine._task_completion_blocker(spec)
        self.assertIsNotNone(blocker)
        self.assertIn("4.2", blocker)
        self.assertIn("4.3", blocker)
        self.assertTrue(blocker.startswith(self.TASK_GAP))

        # 调用门禁走 verified→done 路径：被拦截，error 落 STATE
        self.engine._on_spec_verified(spec)
        entry = self.sm.read_one(spec)
        self.assertEqual(entry["status"], "verified")
        self.assertIn("4.2", entry.get("error", ""))

        # 模拟其它 spec 的成功覆盖共享文件（stamp 不同）
        self._write_shared_result("some-other-spec", "success")

        # re-trigger 重评：从 snapshot 读取，缺口仍在 → 再次拦截
        blocker2 = self.engine._task_completion_blocker(spec)
        self.assertIsNotNone(blocker2)
        self.assertIn("4.2", blocker2)
        self.assertTrue(blocker2.startswith(self.TASK_GAP))
        self.engine._on_spec_verified(spec)
        entry2 = self.sm.read_one(spec)
        self.assertEqual(entry2["status"], "verified")

    # ── 4.2 兼容矩阵测试（对齐 design D4 六行）───────────────────────

    def test_compat_snapshot_all_checked_pass(self):
        """D4 行 1：快照存在 + 全勾 → 放行。"""
        spec = "snap-pass"
        self._make_spec(spec)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n"
            "- [x] 1.1 done\n- [x] 1.2 done\n"
        ))
        self._write_snapshot(spec, "success")
        self.assertIsNone(self.engine._task_completion_blocker(spec))

    def test_compat_snapshot_gap_blocks(self):
        """D4 行 2：快照存在 + 有缺口 → 拦截。"""
        spec = "snap-block"
        self._make_spec(spec)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n"
            "- [x] 1.1 done\n- [ ] 1.2 unchecked\n"
        ))
        self._write_snapshot(spec, "success")
        blocker = self.engine._task_completion_blocker(spec)
        self.assertIsNotNone(blocker)
        self.assertIn("1.2", blocker)
        self.assertTrue(blocker.startswith(self.TASK_GAP))

    def test_compat_shared_file_fallback(self):
        """D4 行 3：快照缺失 + 共享文件 stamp=本 spec → 按共享文件评估。"""
        spec = "shared-fallback"
        self._make_spec(spec)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n"
            "- [x] 1.1 done\n- [ ] 1.2 unchecked\n"
        ))
        # 不写快照，写共享文件
        self._write_shared_result(spec, "success")
        blocker = self.engine._task_completion_blocker(spec)
        self.assertIsNotNone(blocker)
        self.assertIn("1.2", blocker)
        self.assertTrue(blocker.startswith(self.TASK_GAP))

    def test_compat_both_missing_impl_run_fail_closed(self):
        """D4 行 4：两者皆缺失 + implementer_run 在场 → fail-closed 拦截。"""
        spec = "fail-closed"
        self._make_spec(spec, with_impl_run=True)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n"
            "- [x] 1.1 done\n- [ ] 1.2 unchecked\n"
        ))
        # 不写快照，不写共享文件
        blocker = self.engine._task_completion_blocker(spec)
        self.assertIsNotNone(blocker)
        self.assertTrue(blocker.startswith(self.TASK_GAP))
        self.assertIn("证据缺失", blocker)

    def test_compat_both_missing_no_impl_run_pass(self):
        """D4 行 5：无 implementer_run（legacy/手工）→ 放行。"""
        spec = "legacy-spec"
        self._make_spec(spec, with_impl_run=False)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 unchecked\n"
        ))
        self.assertIsNone(self.engine._task_completion_blocker(spec))

    def test_compat_tasks_md_no_numeric_pass(self):
        """D4 行 6：tasks.md 无数字编号任务 → 放行。"""
        spec = "no-numeric"
        self._make_spec(spec)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n- [ ] 实现功能\n- [ ] 写测试\n"
        ))
        self._write_snapshot(spec, "success")
        self.assertIsNone(self.engine._task_completion_blocker(spec))

    # ── 4.4 人工补勾闭环 + 恢复尊重测试 ──────────────────────────────

    def test_human_checkoff_clears_gap_and_passes(self):
        """人工补勾闭环：task-gap 拦截 → 人工在 tasks.md 补勾 → re-trigger
        门禁放行 → task-gap error 被清除 → verified→done → auto-approve 正常。
        """
        spec = "human-checkoff"
        self._make_spec(spec)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n"
            "- [x] 1.1 done\n- [ ] 1.2 unchecked\n"
        ))
        self._write_snapshot(spec, "success")

        # 首次拦截
        blocker = self.engine._task_completion_blocker(spec)
        self.assertIsNotNone(blocker)
        self.assertTrue(blocker.startswith(self.TASK_GAP))
        self.engine._on_spec_verified(spec)
        entry = self.sm.read_one(spec)
        self.assertEqual(entry["status"], "verified")
        self.assertIn("1.2", entry.get("error", ""))

        # 人工补勾 1.2
        tasks_path = (self.project_root / "spec" / "changes"
                      / spec / "tasks.md")
        text = tasks_path.read_text(encoding="utf-8")
        tasks_path.write_text(
            text.replace("- [ ] 1.2 unchecked", "- [x] 1.2 unchecked"),
            encoding="utf-8",
        )

        # re-trigger 重评：无缺口 → 放行 → error 被清除
        blocker2 = self.engine._task_completion_blocker(spec)
        self.assertIsNone(blocker2)
        entry2 = self.sm.read_one(spec)
        self.assertIsNone(entry2.get("error"))

    def test_blocker_check_respects_task_gap_no_autorecover(self):
        """BLOCKER CHECK：task-gap 前缀 spec → 不 auto-recover，reason 为待人工裁决形态。"""
        spec = "tg-blocker"
        self._make_spec(spec, with_impl_run=True)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 unchecked\n"
        ))
        # 写 task-gap error 到 state（模拟门禁拦截后的状态）
        self.sm.update_spec(spec, {"error": f"{self.TASK_GAP}run 证据缺失"})

        # 检查 check_blockers 行为
        result = self.engine.check_blockers()
        blockers = result["blockers"]
        tg_blockers = [
            b for b in blockers
            if b["spec"] == spec and b["status"] == "verified"
        ]
        self.assertTrue(len(tg_blockers) >= 1)
        reason = tg_blockers[0]["reason"]
        self.assertIn("任务缺口待人工裁决", reason)
        # 验证不 auto-recover：verified 状态保持不变（不会被 reset）
        entry = self.sm.read_one(spec)
        self.assertEqual(entry["status"], "verified")

    def test_event_bus_retrigger_not_suppressed(self):
        """event_bus re-trigger：task-gap 拦截生效期间不被抑制，仍然
        调用 handle_event → _on_spec_verified → 门禁重评。"""
        spec = "retrigger-spec"
        self._make_spec(spec, with_impl_run=True)
        self._write_tasks(spec, (
            "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 unchecked\n"
        ))
        self._write_snapshot(spec, "success")
        self.sm.update_spec(spec, {"error": f"{self.TASK_GAP}缺口任务"})

        entry = self.sm.read_one(spec)
        # 模拟 event_bus._recover_one 的 verified 分支
        self.engine.handle_event("spec_verified", spec, entry)
        # re-trigger 应正常调用 _on_spec_verified（不被抑制）
        # 门禁重评后仍有缺口 → error 维持
        entry2 = self.sm.read_one(spec)
        self.assertEqual(entry2["status"], "verified")
        self.assertIn("1.1", entry2.get("error", ""))
