"""
Tests for PMEngine recovery functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, StateParser, SpecStatus, VALID_TRANSITIONS
from core.pm_engine.verification import VerdictReadResult


class TestPMEngineInfraFailureRecovery(unittest.TestCase):
    """派发基础设施失败（日限额耗尽等）不得卡死 spec、不得误判 bug-found。

    覆盖 2026-08-26 事故根因的三处框架修复：
    - 派发异常回滚 implementing/testing → 可重试态（不滞留）
    - 验证流水线双失败不得 transition bug-found（不派生伪 fix 级联）
    - blocker auto-recover 不得把从未实现的 spec 伪标 implemented
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        self.logger = MagicMock()
        from core.state_machine import StateMachine
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        # stuck 阈值由 agents.run_timeout_seconds 单源派生（config.py D1/D4，
        # 缺省回退 9600s=160min），旧键 schedule.stuck_threshold_minutes 已弃用
        # 不再生效——本组测试的 stale（3h）只要落在阈值之上即可，无需配键。
        config = {}
        self.engine = PMEngine(self.sm, MagicMock(), config, self.project_root, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stale(self, name="s1"):
        """把 spec 的 updated 改为 3 小时前（模拟卡死），须在 transition 之后调用。"""
        from datetime import datetime, timedelta, timezone
        specs = self.sm.read_all()
        specs[name]["updated"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        self.sm.write_all(specs)

    def test_implementer_dispatch_failure_rolls_back_to_ready(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.engine._rollback_failed_dispatch(
            "s1", "implementer", RuntimeError("Daily agent run limit (50) reached"))
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry["implementer_run"])
        self.assertIsNone(entry["error"])
        self.assertIn("dispatch failed", entry["_last_dispatch_error"])
        self.assertGreater(int(entry["_dispatch_backoff_until"]), int(time.time()))
        self.assertTrue(any((e[1], e[2]) == ("s1", "implementer") for e in self.engine._dispatcher._run_queue))

    def test_verifier_dispatch_failure_rolls_back_to_implemented(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self.engine._rollback_failed_dispatch(
            "s1", "verifier", RuntimeError("Daily agent run limit (50) reached"))
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertIsNone(entry["tester_run"])
        self.assertIsNone(entry["error"])
        self.assertIn("dispatch failed", entry["_last_dispatch_error"])
        self.assertTrue(any((e[1], e[2]) == ("s1", "verifier") for e in self.engine._dispatcher._run_queue))

    def test_rollback_ignores_status_mismatch(self):
        self.sm.add_spec("s1", {"priority": 5})  # drafted
        self.engine._rollback_failed_dispatch("s1", "implementer", RuntimeError("x"))
        self.assertEqual(self.sm.read_one("s1")["status"], "drafted")

    def test_rollback_missing_spec_is_noop(self):
        self.engine._rollback_failed_dispatch("nope", "implementer", RuntimeError("x"))

    def test_verification_infra_failure_not_bug_found(self):
        """验证两条路径都抛基础设施异常 → 回 implemented 可重试，绝不 bug-found。"""
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self.engine._verification._run_three_stage_verification = MagicMock(
            side_effect=RuntimeError("Daily agent run limit (50) reached"))
        self.engine._verification._run_legacy_verification = MagicMock(
            side_effect=RuntimeError("Daily agent run limit (50) reached"))
        self.engine._run_verification_pipeline("s1")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertNotIn(entry["status"], ("bug-found",))
        self.assertIsNone(entry["error"])
        self.assertIn("retryable", entry["_last_dispatch_error"])

    def test_check_blockers_implementing_rolls_back_to_ready(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self._stale()
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("Auto-recovered from stuck implementing", entry["error"])
        self.assertTrue(any((e[1], e[2]) == ("s1", "implementer") for e in self.engine._dispatcher._run_queue))

    def test_check_blockers_testing_rolls_back_to_implemented(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self._stale()
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertTrue(any((e[1], e[2]) == ("s1", "verifier") for e in self.engine._dispatcher._run_queue))

    def test_check_blockers_fresh_state_not_touched(self):
        """updated 为近期的 implementing 不触发 auto-recover。"""
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.engine.check_blockers()
        self.assertEqual(self.sm.read_one("s1")["status"], "implementing")

    def test_on_spec_done_root_with_fix_prefix_reverify(self):
        """fix 链根 spec 名本身带 fix- 前缀时，fix done 后父 spec 仍正确回溯重验。

        fix-dashboard-... 的 4-fix 后代 done 后，应回溯到 fix-dashboard-...
        （bug-found → implemented），而非全剥前缀后定位到不存在的 dashboard-...
        导致永不闭环、full_scan 反复派生新 fix（2026-08-26 事故的防复发修复）。
        """
        self.sm.add_spec("fix-dashboard-duration-and-verify-gate", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing", "bug-found"):
            self.sm.transition("fix-dashboard-duration-and-verify-gate", to)
        self.sm.add_spec("fix-fix-fix-fix-dashboard-duration-and-verify-gate", {"priority": 6})
        self.sm.transition("fix-fix-fix-fix-dashboard-duration-and-verify-gate", "done")
        self.engine._on_spec_done("fix-fix-fix-fix-dashboard-duration-and-verify-gate")
        entry = self.sm.read_one("fix-dashboard-duration-and-verify-gate")
        self.assertEqual(entry["status"], "implemented")

    def test_on_spec_done_plain_root_still_works(self):
        """普通链（根不带 fix- 前缀）行为不变：improve-... 由 fix- 后代 done 回调。"""
        self.sm.add_spec("improve-agent-config-and-verify-resume", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing", "bug-found"):
            self.sm.transition("improve-agent-config-and-verify-resume", to)
        self.sm.add_spec("fix-fix-improve-agent-config-and-verify-resume", {"priority": 6})
        self.sm.transition("fix-fix-improve-agent-config-and-verify-resume", "done")
        self.engine._on_spec_done("fix-fix-improve-agent-config-and-verify-resume")
        self.assertEqual(
            self.sm.read_one("improve-agent-config-and-verify-resume")["status"],
            "implemented",
        )

    def test_dispatch_backoffed_helper(self):
        self.assertFalse(self.engine._dispatch_backoffed({}))
        self.assertFalse(self.engine._dispatch_backoffed({"status": "ready"}))
        self.assertFalse(self.engine._dispatch_backoffed(
            {"_dispatch_backoff_until": int(time.time()) - 10}))
        self.assertTrue(self.engine._dispatch_backoffed(
            {"_dispatch_backoff_until": int(time.time()) + 300}))


class TestPMEngineDependencyWakeupAndRecoveryPatrol(unittest.TestCase):
    """fix-dispatch-wakeup-gap：依赖定向唤醒 + 恢复复查就地派发（PMEngine 层集成）。

    与 test_event_bus / test_run_lifecycle_governance 的单元覆盖互补：
    这里用真实 PMEngine 断言两条唤醒路径的行为终态（入队 / dispatch_stalled）。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from core.state_machine import StateMachine
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        self.runner.worktree_manager.has_active_worktree.return_value = False
        self.runner.has_live_attempt.return_value = False
        self.engine = PMEngine(self.sm, self.runner, {},
                               self.project_root, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dependency_wakeup_dispatches_within_event_round(self):
        """B 转 pushed：A（depends_on B）在事件当轮被唤醒入队，不等 full_scan。"""
        from core.event_bus import EventBus
        self.sm.add_spec("A", {"status": "ready", "depends_on": "B", "priority": 5})
        self.sm.add_spec("B", {"status": "implementing"})
        # 内容完整性闸门：tmpdir 无 spec 目录会冻结派发，mock 放行聚焦唤醒语义
        self.engine._check_spec_content_missing = MagicMock(return_value=False)
        self.engine._check_impl_budget_exhausted = MagicMock(return_value=False)
        self.engine._process_queue = MagicMock()  # 入队即成立，避免 worker 副作用

        bus = EventBus(self.state_path, self.sm, self.engine, {}, self.logger)
        bus._update_known_state()
        self.sm.update_spec("B", {"status": "pushed"})
        bus._dispatch_changes(self.sm.read_all())

        self.assertTrue(any(
            (e[1], e[2]) == ("A", "implementer")
            for e in self.engine._dispatcher._run_queue
        ), "依赖满足后 dependent 应在事件当轮入队（无需下一轮 full_scan）")

    def test_recovery_patrol_redispatches_regressed_ready(self):
        """恢复复查：登记 implementing → 窗口内回退 ready → 就地重新派发成立。

        复现 2026-09-12 fix-root-init-import-shadow 事故形态（登记时
        implementing、窗口内回退 ready），断言不再静默关闭而是就地派发。
        """
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.engine.register_recovery_watch(
            "s1", "auto-recovery deferred (live child present)")
        # 观察项到期
        watch = dict(self.engine._recovery._recovery_watch)
        watch["s1"]["due"] = time.time() - 1
        self.engine._recovery._recovery_watch = watch
        # 窗口内回退 ready 且无活跃派发
        self.sm.update_spec("s1", {"status": "ready"})
        # 闸门放行让就地派发成立（tmpdir 无 spec 目录，内容闸门默认会拦）
        self.engine._check_impl_budget_exhausted = MagicMock(return_value=False)
        self.engine._check_spec_content_missing = MagicMock(return_value=False)
        self.engine._process_queue = MagicMock()

        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)
        from core.admin_store import AdminStore
        self.assertEqual(
            [r for r in AdminStore(self.project_root, self.logger).read_all()
             if r.get("signal_type") == "dispatch_stalled"], [])
        self.assertTrue(any(
            (e[1], e[2]) == ("s1", "implementer")
            for e in self.engine._dispatcher._run_queue
        ))


class TestPMEngineReplanLimit(unittest.TestCase):
    """replan 循环上限退回 + 成功后计数不残留（回归测试补回，spec
    add-lost-semantics-regression-tests Requirement「replan 循环上限退回保护」）。

    背景（c310ee5 refactor-test-structure）：原 TestPMEngineReplanLoop 被替换为
    空壳（仅 mock 断言）后随清理删除，断言丢失；生产侧旧属性
    ``_replan_count``/``_max_replans`` 已不存在——当前 replan 上限为
    ``verification._run_three_stage_verification`` 内的局部变量
    ``replan_left``（初始 2）：场景验收失败时写 ``REPLAN_FEEDBACK.md``
    退回 planner 重新出题，``replan_left`` 递减；归零后 spec 回 implemented +
    error「场景验收连续失败」，**不再发起新一轮 planner run**（不无界重派）。
    因为 ``replan_left`` 是局部变量，每次重新进入验证管线都从 2 起算，
    天然满足「成功后计数不残留、后续独立失败从零起算」。

    测试按 spec 两个 Scenario：
    - 达到上限后停止重派（planner 调用次数被封顶、spec 状态可观测）
    - replan 计数在成功后不残留（重新进入时预算恢复满额）
    """

    def setUp(self):
        from types import SimpleNamespace
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.verify_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "s1"
        self.verify_dir.mkdir(parents=True, exist_ok=True)
        self.scenarios_path = self.verify_dir / "test_scenarios.json"
        # 每轮 planner 都「成功」收工且产出 plan-ready，但场景文件验收恒失败
        # （相对 URL 触发 load_scenarios 的 ValueError → env_error → replan）
        self.planner_calls = []
        self._ns = SimpleNamespace

        def _fake_planner(spec_name, kind):
            self.planner_calls.append((spec_name, kind))
            return SimpleNamespace(
                success=True, error=None,
                run_id=f"planner-plan-{spec_name}-{len(self.planner_calls)}-a1",
                duration_seconds=0.0,
            )

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_fake_planner)
        self.engine._verification._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("plan-ready"))
        self.engine._verification._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._verification._apply_interaction_contract = MagicMock(return_value=None)
        # evo-add-scenario-serve-consistency-preflight：契约 serve 一致性门在
        # 本类无 serve 夹具下必打回（行为专属覆盖见 test_scenario_serve_consistency），
        # 此处放行以保持本类原有关注点
        self.engine._verification._run_contract_static_check = MagicMock(return_value=False)
        self.engine._enqueue = MagicMock()

        self.sm.add_spec("s1", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("s1", to)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_invalid_scenarios(self, variant: int = 0):
        """相对 URL 场景 → load_scenarios 验收失败（env_error 触发 replan）。

        ``variant`` 使每轮错误不同（消费硬门 D5 只拦截「与上轮相同/超集」的
        错误清单）——预算上限测试需要各轮独立错误才能走到 replan_left 归零；
        消费硬门行为由 test_frozen_scenario_reservoir.py 单独覆盖。
        """
        self.scenarios_path.write_text(json.dumps([
            {
                "id": f"scn-a{variant}",
                "description": f"相对URL场景{variant}",
                "steps": [{"action": "navigate", "value": f"/dashboard{variant}"}],
                "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
            },
        ], ensure_ascii=False), encoding="utf-8")

    def _write_valid_scenarios(self):
        """绝对 URL 场景 → 验收通过（planner 产出合格结果）。"""
        self.scenarios_path.write_text(json.dumps([
            {
                "id": "scn-a",
                "description": "合法场景",
                "steps": [
                    {"action": "navigate", "value": "http://127.0.0.1:8787/dashboard"},
                    {"action": "wait", "value": "page loaded"},
                ],
                "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
            },
        ], ensure_ascii=False), encoding="utf-8")

    def test_replan_exhausts_after_upper_limit(self):
        """Scenario: replan 达到上限后停止重派。

        planner 连续产出不合格场景 → replan_left 从 2 递减到 0 后 spec 回
        implemented + error，不再发起新一轮 planner run（调用次数封顶）。

        关键：场景文件不在 setUp 中预创建——fake planner 在被调用时写入，
        以避免 ``_load_frozen_scenarios`` 在 while 循环之前把非法文件识别为
        "corrupt" 并走 escalate 路径（冻结检查发生在 replan 循环之前）。
        """
        # 第一次 planner run 前场景文件不存在 → _load_frozen_scenarios 返回 None → 进入 replan 循环
        def _planner_exhaust(spec_name, kind):
            self.planner_calls.append((spec_name, kind))
            # 每轮给不同错误（v0/v1/v2……）——消费硬门只拦「与上轮相同/超集」，
            # 预算上限测试要走到 replan_left 归零必须各轮错误独立。
            self._write_invalid_scenarios(variant=len(self.planner_calls))
            return self._ns(
                success=True, error=None,
                run_id=f"planner-plan-{spec_name}-{len(self.planner_calls)}-a1",
                duration_seconds=0.0,
            )

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_planner_exhaust)

        with patch("importlib.reload", lambda m: m):
            self.engine._run_three_stage_verification("s1")

        # 初始 1 次 + replan 2 次 = 3 次 planner run（上限封顶，不再重派）
        self.assertEqual(len(self.planner_calls), 3)
        # 最终状态为上限退回形态：回 implemented（可人工介入），带 error 记录
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertIn("场景验收连续失败", str(entry.get("error")))
        self.assertIn("退回 plan", str(entry.get("error")))
        # 状态转换有日志/状态记录可断言：REPLAN_FEEDBACK.md 至少写过一轮
        self.assertTrue((self.verify_dir / "REPLAN_FEEDBACK.md").exists())
        # 不得流转 bug-found（验收失败属环境/任务书问题，绝非产品缺陷）
        self.assertNotEqual(entry["status"], "bug-found")

    def test_replan_stops_when_scenario_accepted(self):
        """反方向：planner 产出合格结果后验证管线正常推进（replan 循环可退出）。"""
        def _planner_valid(spec_name, kind):
            self.planner_calls.append((spec_name, kind))
            self._write_valid_scenarios()  # 首次产出合格场景
            return self._ns(
                success=True, error=None,
                run_id=f"planner-plan-{spec_name}-{len(self.planner_calls)}-a1",
                duration_seconds=0.0,
            )

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_planner_valid)

        captured = {}

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                captured["spec"] = spec_name

            async def run(self, scenarios):
                captured["scenarios"] = scenarios
                return {
                    "spec": "s1",
                    "summary": {
                        "total": 1, "passed": 1, "warnings": 0,
                        "failed": 0, "errors": 0, "blocked_env": 0,
                    },
                    "scenarios": [],
                }

        self.engine._verification._ensure_app_reachable = MagicMock(return_value=(True, False, ""))
        self.engine._verification._verify_verdict_evidence = MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._verification._update_warning_streaks = MagicMock(return_value=[])
        self.engine._verification._check_verification_gate = MagicMock(return_value=None)
        self.engine._verification._ensure_verification_report = MagicMock(return_value=None)
        self.engine._verification._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._verification._render_scenario_change_section_to_report = MagicMock()
        self.engine._on_spec_verified = MagicMock()

        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("s1")

        # 一次 planner run 即通过（无 replan），场景真正执行
        self.assertEqual(len(self.planner_calls), 1)
        self.assertEqual(self.sm.read_one("s1")["status"], "verified")

    def test_replan_budget_resets_on_reentry(self):
        """Scenario: replan 计数在成功后不残留。

        replan_left 是每次进入验证管线的局部变量：一轮 replan 消耗后成功退出，
        下一轮独立失败从满额（2 次）起算——计数不跨轮残留。

        同样：场景文件不在 setUp 中预创建，由 fake planner 在被调用时写入，
        避免 _load_frozen_scenarios 走 corrupt 路径。
        """
        first_run = {"calls": 0}
        planner_valid = self.engine.agent_runner.run_planner  # 初始 MagicMock

        def _planner_budget(spec_name, kind):
            first_run["calls"] += 1
            if first_run["calls"] == 1:
                self._write_invalid_scenarios()  # 首次产出不合格 → 触发 replan
            else:
                self._write_valid_scenarios()  # 第二轮产出合格
            return self._ns(
                success=True, error=None,
                run_id=f"planner-plan-{spec_name}-{first_run['calls']}-a1",
                duration_seconds=0.0,
            )

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_planner_budget)

        captured = {}

        class FakeEngine:
            def __init__(self, spec_name, project_root, logger=None, config=None,
                         scenario_root=None):
                pass

            async def run(self, scenarios):
                captured["ran"] = True
                return {
                    "spec": "s1",
                    "summary": {
                        "total": 1, "passed": 1, "warnings": 0,
                        "failed": 0, "errors": 0, "blocked_env": 0,
                    },
                    "scenarios": [],
                }

        self.engine._verification._ensure_app_reachable = MagicMock(return_value=(True, False, ""))
        self.engine._verification._verify_verdict_evidence = MagicMock(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        self.engine._verification._update_warning_streaks = MagicMock(return_value=[])
        self.engine._verification._check_verification_gate = MagicMock(return_value=None)
        self.engine._verification._ensure_verification_report = MagicMock(return_value=None)
        self.engine._verification._env_whitewash_gate = MagicMock(return_value=True)
        self.engine._verification._render_scenario_change_section_to_report = MagicMock()
        self.engine._on_spec_verified = MagicMock()

        with patch("importlib.reload", lambda m: m), \
                patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("s1")

        # 第一轮：1 次 replan 后成功（共 2 次 planner run），spec verified
        self.assertEqual(first_run["calls"], 2)
        self.assertEqual(self.sm.read_one("s1")["status"], "verified")

        # 第二轮：重新进入验证管线（testing → 验证），预算恢复满额。
        # 若 replan 计数残留（从 0 起算）则只允许 1 次 planner run 即封顶；
        # 当前实现是局部变量 → 仍可从满额 2 次 replan 起算（共 3 次）。
        # verified → testing 非法转换（VALID_TRANSITIONS: verified→done），
        # 测试用 update_spec 直接置位（生产由 dispatcher 派发前拨回 testing）。
        self.sm.update_spec("s1", {"status": "testing"})
        # 删掉上一轮残留的场景文件，否则 _load_frozen_scenarios 返回旧冻结
        self.scenarios_path.unlink(missing_ok=True)

        from types import SimpleNamespace as _NS

        def _planner_budget_r2(spec_name, kind):
            first_run["calls"] += 1
            # 每轮独立错误（v5/v6/v7……）——消费硬门只拦与上轮相同的错误清单，
            # 预算归零测试需各轮错误独立才能走到 replan_left 耗尽。
            self._write_invalid_scenarios(variant=first_run["calls"])
            return _NS(
                success=True, error=None,
                run_id=f"planner-plan-{spec_name}-{first_run['calls']}-a1",
                duration_seconds=0.0,
            )

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_planner_budget_r2)

        with patch("importlib.reload", lambda m: m):
            self.engine._run_three_stage_verification("s1")

        # 第二轮：独立失败从零起算 → 3 次 planner run（初始 + 2 次 replan）
        self.assertEqual(first_run["calls"], 5)
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertIn("场景验收连续失败", str(entry.get("error")))
