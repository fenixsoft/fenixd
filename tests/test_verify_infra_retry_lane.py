"""infra-retry 廉价重试车道（evo-verify-infra-retry-lane）回归测试。

覆盖 tasks.md 3.1 验收：
- prepare/可达性失败（0 场景执行短路）→ infra-retry：env 冻结轮不递增、
  不写 blocked/status、不呼叫 admin、限内重派（经既有 verifier 派发入口）；
- 连败达阈值（缺省 2 次预算耗尽）→ 恢复既有全价升级（blocked + admin）；
- infra 轮观测账与 env 冻结轮/豁免语义互不污染；
- infra-retry 通道不增减 _redispatch_same_cause_streak/_redispatch_cause_fp（D5）；
- 历史全价 env 轮（_verify_infra_rounds>0）不吃重试预算（专用计数分离，D2）；
- unfreeze_spec 后专用计数从零起算（D2）；验证 PASS 同点清零（D2）；
- 预算可配（verify_engine.infra_retry_max）；
- Dispatcher 侧重派回调经既有 verifier 派发入口 _enqueue（D5），幂等排程。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import (
    StateMachine,
    ENV_BLOCK_ROUNDS_FIELD,
    VERIFY_INFRA_RETRY_STREAK_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
)
from core.pm_engine.verification import VerdictReadResult

_PREPARE_FAIL_NOTE = "验证契约 prepare 失败: npm ERR! exit 1"


class TestInfraRetryLane(unittest.TestCase):
    """infra-retry 车道行为回归（pipeline fail-fast 短路轮驱动）。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.config = {}
        self.engine = PMEngine(
            self.sm, MagicMock(), self.config, Path(self.tmpdir), self.logger,
        )
        self.verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        self.verify_dir.mkdir(parents=True)
        (self.verify_dir / "test_scenarios.json").write_text(json.dumps([
            {
                "id": "scn-a",
                "description": "场景A",
                "steps": [
                    {"action": "navigate", "value": "http://localhost:8787/#/demo"},
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
        self.engine._verification._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._verification._apply_interaction_contract = MagicMock(return_value=None)
        # evo-add-scenario-serve-consistency-preflight：契约 serve 一致性门在
        # 本类无 serve 夹具下必打回（行为专属覆盖见 test_scenario_serve_consistency），
        # 此处放行以保持 infra-retry 车道关注点
        self.engine._verification._run_contract_static_check = MagicMock(return_value=False)
        self.engine._verification._verify_verdict_evidence = MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._verification._update_warning_streaks = MagicMock(return_value=[])
        self.engine._verification._read_verdict = MagicMock(
            return_value=VerdictReadResult.success("verified"))
        self.engine._verification._check_verification_gate = MagicMock(return_value=None)
        self.engine._verification._ensure_verification_report = MagicMock(return_value=None)
        self.engine._verification._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._verification._render_scenario_change_section_to_report = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        # human 升级告警 mock 掉（断言「不呼叫」与 escalate 轮的呼叫形态）
        self.engine._send_human_escalation_alert = MagicMock()
        # 重派触发器整体覆写为捕获桩：断言「限内重派已排程」且不启动真实定时器
        self.schedule_mock = MagicMock()
        self.engine._verification._context.schedule_infra_retry_redispatch = (
            self.schedule_mock
        )
        self.invoke_path = Path(self.tmpdir) / ".fenix" / "admin_invoke_request.json"
        self.fail_history_path = self.verify_dir / "fail_history.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fake_engine(self, runs, failed=0):
        """VerifyEngine 替身：短路轮两者都必须为 0；可达轮按 failed 出账。"""

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                runs.append(("__init__", spec_name))

            async def run(self, scenarios):
                runs.append(("run", len(scenarios)))
                total = 2
                return {
                    "spec": "demo-spec",
                    "summary": {
                        "total": total, "passed": total - failed, "warnings": 0,
                        "failed": failed, "errors": 0, "blocked_env": 0,
                    },
                    "scenarios": [],
                }

        return FakeEngine

    def _run_failfast_round(self, runs):
        """驱动一轮可达性 fail-fast（_ensure_app_reachable 打桩为 prepare 失败）。"""
        self.engine._verification._ensure_app_reachable = MagicMock(
            return_value=(False, False, _PREPARE_FAIL_NOTE))
        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", self._fake_engine(runs)):
            self.engine._run_three_stage_verification("demo-spec")

    def _run_verified_round(self, runs):
        """驱动一轮全绿验证（可达 + 0 failed + verdict verified）→ _apply_verified。"""
        self.engine._verification._ensure_app_reachable = MagicMock(
            return_value=(True, False, "已自动启动应用服务"))
        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine",
                      self._fake_engine(runs, failed=0)):
            self.engine._run_three_stage_verification("demo-spec")

    # ── 限内重派：廉价车道全语义 ─────────────────────────────────────────

    def test_failfast_redispatch_lane_cheap(self):
        """首次 prepare 失败 → infra-retry：不 blocked、env 轮不递增、无 admin 呼叫、重派已排程。"""
        runs = []
        self._run_failfast_round(runs)

        # 场景执行数=0：不创建、不运行 VerifyEngine（0 成本短路轮）
        self.assertEqual(runs, [], "fail-fast 轮不得创建/运行 VerifyEngine")
        entry = self.sm.read_one("demo-spec")
        # 不写 blocked/status：保持 testing、不冻结
        self.assertEqual(entry["status"], "testing")
        self.assertIs(entry.get("frozen"), False)
        # env 冻结轮不递增（旁路在升级通道入口早退）
        self.assertEqual(int(entry.get(ENV_BLOCK_ROUNDS_FIELD, 0) or 0), 0)
        self.assertIsNone(entry.get("error"))
        # 无 admin 自动呼叫请求文件、无 human 升级告警
        self.assertFalse(self.invoke_path.exists(), "廉价重试轮不得产生 admin 呼叫请求")
        self.engine._send_human_escalation_alert.assert_not_called()
        # 限内重派已排程（经既有 verifier 派发入口，D5）
        self.schedule_mock.assert_called_once_with("demo-spec")
        # 专用计数 +1；观测账 _verify_infra_rounds 照常入账（记账唯一入点）
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 1)
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0)), 1)
        # 失败台账含 infra 条目（R3 回拨参考口径不因车道改变）
        history = json.loads(self.fail_history_path.read_text(encoding="utf-8"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["failure_class"], "infra")

    def test_exhausted_budget_recovers_full_price_escalation(self):
        """连败 3 次：前 2 次重派，第 3 次（预算耗尽）恢复全价升级 blocked + admin。"""
        runs = []
        for i in range(3):
            self._run_failfast_round(runs)
            entry = self.sm.read_one("demo-spec")
            self.assertEqual(
                int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), i + 1)
            if i < 2:
                # 前 2 轮：重派、无升级痕迹
                self.assertEqual(entry["status"], "testing", f"round{i+1} 应走廉价重派")
                self.assertFalse(self.invoke_path.exists())
                self.assertEqual(self.schedule_mock.call_count, i + 1)
        # 第 3 轮：预算耗尽 → 全价
        self.schedule_mock.assert_called_with("demo-spec")
        self.assertEqual(self.schedule_mock.call_count, 2, "仅前 2 轮重派")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("验证环境阻塞（应用不可达）", str(entry.get("error")))
        # 全价轮才开始计 env 冻结轮（车道轮不贡献）
        self.assertEqual(int(entry.get(ENV_BLOCK_ROUNDS_FIELD, 0) or 0), 1)
        self.assertTrue(self.invoke_path.exists(), "达预算轮应产生 admin 呼叫请求")
        self.engine._send_human_escalation_alert.assert_called_once_with(
            spec_name="demo-spec",
            signal_type="verify_env_blocked",
            severity="warning",
            description=ANY,
            evidence=ANY,
            recommended_action=ANY,
        )

    def test_configurable_budget_via_verify_engine_infra_retry_max(self):
        """verify_engine.infra_retry_max=1 → 首轮重派、次轮即升级。"""
        self.engine.config = {"verify_engine": {"infra_retry_max": 1}}
        runs = []
        self._run_failfast_round(runs)
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 1)
        self._run_failfast_round(runs)
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked", "预算=1 时第 2 轮即全价升级")

    # ── 两本账互不污染 ───────────────────────────────────────────────────

    def test_lane_ledgers_isolated_from_env_rounds_and_same_cause(self):
        """连续 2 次重派：infra 观测账累加，env 冻结轮/fail 轮/同因重派账零污染。"""
        runs = []
        self._run_failfast_round(runs)
        self._run_failfast_round(runs)
        entry = self.sm.read_one("demo-spec")
        # 观测账照常累加（两车道共用唯一入账点）
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0)), 2)
        # env 冻结轮 / fail 轮 / 冻结位：零污染
        self.assertEqual(int(entry.get(ENV_BLOCK_ROUNDS_FIELD, 0) or 0), 0)
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0) or 0), 0)
        self.assertIs(entry.get("frozen"), False)
        # D5：同因重派记账不增不减（车道重派不是同因重派语义）
        self.assertNotIn("_redispatch_same_cause_streak", entry)
        self.assertNotIn("_redispatch_cause_fp", entry)
        self.assertEqual(entry["status"], "testing")

    def test_historical_full_price_env_rounds_do_not_eat_retry_budget(self):
        """历史 _verify_infra_rounds>0（全价 env 轮观测账）→ 首次短路失败仍获完整 2 次预算。"""
        self.sm.update_spec("demo-spec", {VERIFY_INFRA_ROUNDS_FIELD: 5})
        runs = []
        self._run_failfast_round(runs)
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing", "历史观测账不得吃掉重试预算")
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 1)
        self.schedule_mock.assert_called_once_with("demo-spec")

    # ── 专用计数清零点 ───────────────────────────────────────────────────

    def test_unfreeze_spec_resets_streak(self):
        """unfreeze_spec 清零清单含专用计数：达预算冻结→解冻后从零起算。"""
        self.sm.update_spec("demo-spec", {VERIFY_INFRA_RETRY_STREAK_FIELD: 2})
        self.sm.unfreeze_spec("demo-spec")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 0)
        # 解冻后首轮短路失败重新获完整预算（streak=1 ≤ 2 → 重派）
        runs = []
        self._run_failfast_round(runs)
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 1)

    def test_verified_pass_resets_streak(self):
        """验证 PASS 是专用计数清零点之一（与 _verify_fail_rounds 归零点同语义）。"""
        self.sm.update_spec("demo-spec", {VERIFY_INFRA_RETRY_STREAK_FIELD: 2})
        runs = []
        self._run_verified_round(runs)
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "verified")
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 0)


class TestInfraRetryRedispatchDispatch(unittest.TestCase):
    """Dispatcher 侧重派机械路径（D5）：定时器回调经既有 verifier 派发入口入队。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)
        self.sm.add_spec("demo-spec", {"priority": 5})
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._process_queue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_callback_reenqueues_verifier_via_dispatch_entry(self):
        """_on_infra_retry_redispatch → _enqueue(spec, "verifier") + process_queue。"""
        self.engine._dispatcher._on_infra_retry_redispatch("demo-spec")
        self.engine._enqueue.assert_called_once_with("demo-spec", "verifier")
        self.engine._process_queue.assert_called_once()

    def test_schedule_is_idempotent_per_spec(self):
        """同 spec 重复排程只保留一个待到期定时器（_infra_retry_timers 判重）。"""
        dispatcher = self.engine._dispatcher
        dispatcher._schedule_infra_retry_redispatch("demo-spec")
        dispatcher._schedule_infra_retry_redispatch("demo-spec")
        self.assertEqual(dispatcher._infra_retry_timers, {"demo-spec"})


if __name__ == "__main__":
    unittest.main()
