"""add-verify-lane-throughput 单元测试（Tasks 1.4 / 2.2 / 3.4 / 4.4）。

覆盖四组单测义务：
  - 1.4 并行出题：ready 触发派发（含 fast-track/既有产物/在飞去重跳过）、
    车道 worker 收尾（completed/failed 隔离/删除弃置）、回退停派；
  - 2.2 槽位豁免：实现槽满时 planner-plan 条目放行、独立在飞上限 1、
    回退态条目滞留、worker 收尾释放登记；
  - 3.4 judge 治理：轮内真实派发计数、阈值停派+人工升级（只发一次）、
    验证轮重置、fast-track 命中计数、证据扩充记账、summary 读侧字段；
  - 4.4 verdict 缓存：定义指纹/构建指纹/配置指纹/出处提取/四元组校验、
    写侧 PASS 条目与 _meta、修复轮裁剪与合成、全链 fail-open。
"""

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.pm_engine.dispatch import Dispatcher
from core.state_machine import StateMachine
from core.verdict_check import (
    compute_build_fingerprint,
    compute_verify_config_fingerprint,
    extract_scenario_source_files,
    is_expandable_evidence_violation,
    load_verdict_cache,
    scenario_definition_fingerprint,
    save_verdict_cache,
    verdict_cache_entry_valid,
)

VALID_SCENARIO = {
    "id": "scn-a",
    "description": "场景A 出处 core/feature.py:10",
    "steps": [
        {"action": "navigate", "value": "http://localhost:8000/#/projects/demo"},
        {"action": "wait", "target": ".x", "description": "等待"},
    ],
    "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
}


def _make_engine():
    """构造真 StateMachine + PMEngine（既有 verdict 测试同款轻量基建）。"""
    tmpdir = tempfile.mkdtemp()
    root = Path(tmpdir)
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = MagicMock()
    sm = StateMachine(root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), {}, root, logger)
    return engine, sm, root


class _EngineCase(unittest.TestCase):
    def setUp(self):
        self.engine, self.sm, self.root = _make_engine()
        self.sm.add_spec("my-spec", {"priority": 5})
        self.vp = self.root / ".fenix" / "verify-progress" / "my-spec"
        self.vp.mkdir(parents=True, exist_ok=True)
        self.dispatcher = self.engine._dispatcher

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


# ── 1.4 并行出题：触发 / 车道收尾 / 回退停派 ──────────────────────────────


class TestParallelPlanningTrigger(_EngineCase):
    """任务 1.1/1.2：ready 触发派发与各跳过分支。"""

    def test_trigger_enqueues_planner_plan_for_ready_spec(self):
        self.sm.transition("my-spec", "ready")
        self.dispatcher._enqueue = MagicMock()
        self.engine._trigger_parallel_planning("my-spec")
        self.dispatcher._enqueue.assert_called_once_with("my-spec", "planner-plan")

    def test_trigger_skipped_when_existing_scenarios_present(self):
        self.sm.transition("my-spec", "ready")
        (self.vp / "test_scenarios.json").write_text("[]", encoding="utf-8")
        self.dispatcher._enqueue = MagicMock()
        self.engine._trigger_parallel_planning("my-spec")
        self.dispatcher._enqueue.assert_not_called()

    def test_trigger_skipped_for_fast_track_mode(self):
        self.sm.transition("my-spec", "ready")
        spec_dir = self.root / "spec" / "changes" / "my-spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / ".spec.yaml").write_text("mode: fast-track\n", encoding="utf-8")
        self.dispatcher._enqueue = MagicMock()
        self.engine._trigger_parallel_planning("my-spec")
        self.dispatcher._enqueue.assert_not_called()

    def test_trigger_skipped_when_marker_inflight_or_consumed(self):
        self.sm.transition("my-spec", "ready")
        self.dispatcher._enqueue = MagicMock()
        for status in ("dispatched", "completed", "consumed"):
            # dispatched 形态须带新鲜 dispatched_at（fix_scope=test，回归重试轮）：
            # 真实在飞标记由车道起点写入时必带该时间戳（_run_parallel_plan_lane）；
            # item 46fcea7e4842 起 dispatched_at 缺失/非法按「无主残留」回收重派
            # （fail-open 为有意设计），缺时间戳的标记不再表达「在飞」语义
            marker = {"status": status}
            if status == "dispatched":
                marker["dispatched_at"] = datetime.now(timezone.utc).isoformat()
            self.engine._write_parallel_plan_marker("my-spec", marker)
            self.engine._trigger_parallel_planning("my-spec")
        self.dispatcher._enqueue.assert_not_called()

    def test_trigger_skipped_when_lane_already_active(self):
        self.sm.transition("my-spec", "ready")
        self.dispatcher._enqueue = MagicMock()
        self.dispatcher._active_parallel_plans.add("my-spec")
        self.engine._trigger_parallel_planning("my-spec")
        self.dispatcher._enqueue.assert_not_called()

    def test_trigger_disabled_by_config_switch(self):
        self.sm.transition("my-spec", "ready")
        self.dispatcher._enqueue = MagicMock()
        self.engine._get_config = MagicMock(return_value=False)
        self.engine._trigger_parallel_planning("my-spec")
        self.dispatcher._enqueue.assert_not_called()

    def test_trigger_swallows_exceptions(self):
        # 任何异常吞并 WARNING，不向调用方传播（不影响实现车道）
        with patch("core.spec_mode.read_spec_mode", side_effect=RuntimeError("boom")):
            self.engine._trigger_parallel_planning("my-spec")  # 不抛


class TestParallelPlanLane(_EngineCase):
    """任务 1.1/1.2：车道 worker 收尾与产物隔离。"""

    def _to_ready(self):
        self.sm.transition("my-spec", "ready")

    def test_lane_success_writes_completed_marker(self):
        self._to_ready()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(success=True, run_id="planner-plan-1", error=None)
        )
        self.engine._run_parallel_plan_lane("my-spec")
        marker = self.engine._read_parallel_plan_marker("my-spec")
        self.assertEqual(marker.get("status"), "completed")
        self.assertEqual(marker.get("run_id"), "planner-plan-1")
        self.engine.agent_runner.run_planner.assert_called_once_with("my-spec", "plan")

    def test_lane_failure_quarantines_product(self):
        self._to_ready()

        def _run_writes_product(spec_name, mode):
            # planner run 语义：执行中自写产物，返回失败
            (self.vp / "test_scenarios.json").write_text("[{}]", encoding="utf-8")
            return SimpleNamespace(
                success=False, run_id="planner-plan-1", error="boom",
                frozen_terminated=False, cancelled=False,
            )

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_run_writes_product)
        self.engine._run_parallel_plan_lane("my-spec")
        marker = self.engine._read_parallel_plan_marker("my-spec")
        self.assertEqual(marker.get("status"), "failed")
        self.assertFalse(
            (self.vp / "test_scenarios.json").exists(),
            "失败产物必须被隔离（半成品不被后续验证轮采信）",
        )
        self.assertTrue((self.vp / "test_scenarios.json.parallel-discarded").exists())

    def test_lane_skips_when_spec_regressed_to_drafted(self):
        # 回退 drafted：零写入（不写 marker、不派 run）
        self.engine.agent_runner.run_planner = MagicMock()
        self.engine._run_parallel_plan_lane("my-spec")
        self.engine.agent_runner.run_planner.assert_not_called()
        self.assertFalse((self.vp / "parallel_plan.json").exists())

    def test_lane_discards_product_when_spec_deleted(self):
        self._to_ready()

        def _remove_midrun(spec_name, mode):
            self.sm.remove_spec("my-spec")  # run 期间 spec 被删除，半成品残留
            (self.vp / "test_scenarios.json").write_text("[{}]", encoding="utf-8")
            return SimpleNamespace(success=True, run_id="r1", error=None)

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_remove_midrun)
        self.engine._run_parallel_plan_lane("my-spec")
        marker = self.engine._read_parallel_plan_marker("my-spec")
        self.assertEqual(marker.get("status"), "discarded")
        self.assertTrue((self.vp / "test_scenarios.json.parallel-discarded").exists())

    def test_lane_discards_product_when_spec_reverted_midrun(self):
        # 回退竞窗收尾兜底（code-review item b4b98c69a4e1）：_stop_parallel_planning
        # 的 cancel_run 落在 attempt 登记前时 not_running（旗标未登记），run 照常
        # 跑完——收尾不得写 completed（否则下次 ready 重入被 marker 挡住不重派、
        # 对旧版 spec 出的题被 testing 直接消费），按任务 1.2 隔离半成品。
        self._to_ready()
        self.engine.state_machine.read_one = MagicMock(
            side_effect=[
                {"status": "ready", "priority": 5},  # 派发前重查：状态合法
                {"status": "drafted", "priority": 5},  # run 收尾重查：已回退
            ]
        )

        def _run_writes_product(spec_name, mode):
            (self.vp / "test_scenarios.json").write_text("[{}]", encoding="utf-8")
            return SimpleNamespace(success=True, run_id="r1", error=None)

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_run_writes_product)
        self.engine._run_parallel_plan_lane("my-spec")
        marker = self.engine._read_parallel_plan_marker("my-spec")
        self.assertEqual(marker.get("status"), "discarded", "回退态 MUST NOT 写 completed")
        self.assertIn("drafted", marker.get("reason", ""))
        self.assertFalse((self.vp / "test_scenarios.json").exists())
        self.assertTrue((self.vp / "test_scenarios.json.parallel-discarded").exists())

    def test_lane_defers_to_consumer_takeover_discarded_marker(self):
        # 消费侧接管竞窗（code-review item b4b98c69a4e1）：run 在飞期间 marker
        # 被翻成 discarded（testing 等待超时 / 收尾竞窗 run-death 误判转串行）
        # ——收尾不得以 completed 覆写接管方标记（否则 testing 消费判定错乱），
        # 也不得隔离产物（串行重出即将覆写同路径，盲隔离误删串行产物）。
        self._to_ready()

        def _flip_marker_midrun(spec_name, mode):
            self.engine._write_parallel_plan_marker(
                "my-spec", {"status": "discarded", "reason": "wait_timeout"}
            )
            (self.vp / "test_scenarios.json").write_text("[{}]", encoding="utf-8")
            return SimpleNamespace(success=True, run_id="r1", error=None)

        self.engine.agent_runner.run_planner = MagicMock(side_effect=_flip_marker_midrun)
        self.engine._run_parallel_plan_lane("my-spec")
        marker = self.engine._read_parallel_plan_marker("my-spec")
        self.assertEqual(marker.get("status"), "discarded", "MUST NOT 覆写接管方标记")
        self.assertEqual(marker.get("reason"), "wait_timeout", "接管方标记原样保留")
        self.assertTrue(
            (self.vp / "test_scenarios.json").exists(), "产物留给串行路径覆写，MUST NOT 隔离"
        )

    def test_stop_parallel_planning_cancels_and_dequeues(self):
        self._to_ready()
        self.dispatcher._enqueue("my-spec", "planner-plan")
        # 在飞 run 以完整 run 级 id 登记（run_planner 构造形如
        # planner-plan-<spec>-<epoch>，attempt 附加 -a<n> 后缀）。取消键 MUST
        # 为带 epoch 的 run 级 id（code-review item 794e218ce816）：裸键与
        # 消费点不收敛、取消静默失效。
        self.engine.agent_runner._running_agents = {
            "planner-plan-my-spec-1790291005-a1": MagicMock(),
            "planner-plan-other-spec-1790291006": MagicMock(),
        }
        self.engine.agent_runner.cancel_run = MagicMock(
            return_value={"status": "cancel_requested"}
        )
        self.engine._stop_parallel_planning("my-spec", "spec 状态回退 drafted")
        self.engine.agent_runner.cancel_run.assert_called_once()
        self.assertEqual(
            self.engine.agent_runner.cancel_run.call_args.args[0],
            "planner-plan-my-spec-1790291005",
        )
        self.assertFalse(
            any(
                e[1] == "my-spec" and e[2] == "planner-plan"
                for e in self.dispatcher._run_queue
            ),
            "回退停派必须摘除在队 planner-plan 条目",
        )

    def test_frozen_marker_not_retriggered_but_retryable_states_are(self):
        # failed/cancelled/frozen 标记允许 ready 重入再试（与实现车道重派同语义）
        self._to_ready()
        self.engine._write_parallel_plan_marker("my-spec", {"status": "failed"})
        self.dispatcher._enqueue = MagicMock()
        self.engine._trigger_parallel_planning("my-spec")
        self.dispatcher._enqueue.assert_called_once_with("my-spec", "planner-plan")


# ── 2.2 槽位豁免与独立上限 ────────────────────────────────────────────────


def _make_fake_pm(spec_table):
    """构造 Dispatcher 所需的最小 fake pm（显式返回值，避开 MagicMock 真值陷阱）。"""
    pm = MagicMock()
    pm.shutting_down = False
    pm._global_transient_break_active.return_value = False
    pm._get_config.return_value = 2  # agents.max_concurrent
    pm._effective_priority.side_effect = lambda prio, enq, now: prio
    pm._dispatch_backoffed.return_value = False
    pm._start_after_blocks_entry.return_value = False
    pm._instant_fail_cooled.return_value = False
    pm._signal_kill_cooled.return_value = False
    pm._should_defer_for_reviewer.return_value = False
    pm._is_fix_spec.return_value = False
    pm._get_spec_priority.return_value = 5
    pm.state_machine.read_one.side_effect = lambda name: spec_table.get(name)
    return pm


class TestQueueSlotExemption(unittest.TestCase):
    """任务 2.2：实现槽满时并行出题条目放行、上限与回退滞留。"""

    def setUp(self):
        self.spec_table = {
            "plan-spec": {"name": "plan-spec", "status": "ready", "priority": 5},
            "impl-spec": {"name": "impl-spec", "status": "ready", "priority": 5},
        }
        self.pm = _make_fake_pm(self.spec_table)
        self.q = Dispatcher(self.pm)

    def test_planner_plan_dispatched_when_impl_slots_full(self):
        self.q._active_runs = 2  # 实现槽满
        self.q._enqueue("impl-spec", "implementer")
        self.q._enqueue("plan-spec", "planner-plan")
        self.q._process_queue()
        # planner-plan 放行：登记在飞、零实现槽占用
        self.assertIn("plan-spec", self.q._active_parallel_plans)
        self.assertEqual(self.q._active_runs, 2, "豁免车道不得增减实现槽计数")
        # implementer 条目照旧滞留
        self.assertTrue(
            any(e[2] == "implementer" for e in self.q._run_queue),
            "槽满时实现条目必须滞留",
        )

    def test_parallel_plan_cap_limits_inflight_to_one(self):
        self.q._active_runs = 2
        self.spec_table["plan-2"] = {"name": "plan-2", "status": "ready", "priority": 5}
        self.q._active_parallel_plans.add("other-spec")  # 已有 1 个在飞 → 上限满
        self.q._enqueue("plan-spec", "planner-plan")
        self.q._process_queue()
        self.assertNotIn("plan-spec", self.q._active_parallel_plans)
        self.assertTrue(
            any(e[1] == "plan-spec" and e[2] == "planner-plan" for e in self.q._run_queue),
            "上限满时条目滞留队列待重判",
        )

    def test_exemption_cap_independent_of_max_concurrent(self):
        # 豁免上限是车道常量：即便实现并发调大（槽位充足），并行出题在飞
        # 上限仍为 1，不随 agents.max_concurrent 伸缩（2.2 解耦语义）
        self.q._active_runs = 2
        self.spec_table["plan-2"] = {"name": "plan-2", "status": "ready", "priority": 5}
        self.pm._get_config.side_effect = (
            lambda key, default=None: 8 if key == "agents.max_concurrent" else default
        )
        self.q._active_parallel_plans.add("inflight-a")
        self.q._enqueue("plan-spec", "planner-plan")
        self.q._enqueue("plan-2", "planner-plan")
        self.q._process_queue()
        self.assertEqual(
            self.q._active_parallel_plans, {"inflight-a"},
            "max_concurrent=8 槽位充足，上限 1 仍拦住第二个 planner-plan",
        )
        queued = [e[1] for e in self.q._run_queue]
        self.assertIn("plan-spec", queued)
        self.assertIn("plan-2", queued)

    def test_planner_plan_entry_held_when_spec_drafted(self):
        self.spec_table["plan-spec"]["status"] = "drafted"  # 回退态
        self.q._enqueue("plan-spec", "planner-plan")
        self.q._process_queue()
        self.assertNotIn("plan-spec", self.q._active_parallel_plans)
        self.assertTrue(
            any(e[1] == "plan-spec" for e in self.q._run_queue),
            "回退态条目滞留不派发（任务 1.2）",
        )

    def test_planner_plan_dispatch_does_not_transition_state(self):
        self.q._enqueue("plan-spec", "planner-plan")
        self.q._process_queue()
        self.pm.state_machine.transition.assert_not_called()
        self.assertEqual(self.pm.state_machine.update_spec.call_args_list, [])

    def test_worker_release_discards_registration(self):
        self.q._active_parallel_plans.add("plan-spec")
        # worker 主体经 pm 吸收（MagicMock），仅验证 finally 释放登记
        self.q._run_agent_worker("plan-spec", "planner-plan", 5)
        self.assertNotIn("plan-spec", self.q._active_parallel_plans)


# ── 1.3 testing 进入消费并行产物 ──────────────────────────────────────────


class TestParallelPlanConsume(_EngineCase):
    """任务 1.3：消费判定（无标记/就绪短路/损坏回落/在飞停等）。"""

    def setUp(self):
        super().setUp()
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("my-spec", st)
        self.pipeline = self.engine._verification
        # 判活已改走 AgentRunner 公开接口 is_run_alive（code-review item
        # 305dcbb105c3）：MagicMock 自动属性恒真值会让「run 已死」分支永不
        # 命中，在飞等待轮询到 900s 超时上限（pytest-timeout 假死）。替身
        # 须显式对齐新接口，False = 无存活 run（与旧 `_running_agents = {}`
        # 同语义）。
        self.engine.agent_runner.is_run_alive = MagicMock(return_value=False)

    def _marker(self, status):
        self.engine._write_parallel_plan_marker("my-spec", {"status": status})

    def test_no_marker_returns_true_unchanged(self):
        self.assertTrue(self.pipeline._consume_parallel_plan_product("my-spec", self.vp))
        self.assertEqual(self.engine._read_parallel_plan_marker("my-spec"), {})

    def test_completed_valid_product_marks_consumed(self):
        self._marker("completed")
        (self.vp / "test_scenarios.json").write_text(
            json.dumps([VALID_SCENARIO], ensure_ascii=False), encoding="utf-8"
        )
        self.assertTrue(self.pipeline._consume_parallel_plan_product("my-spec", self.vp))
        self.assertEqual(
            self.engine._read_parallel_plan_marker("my-spec").get("status"), "consumed"
        )

    def test_completed_corrupt_product_quarantines_and_serial(self):
        self._marker("completed")
        (self.vp / "test_scenarios.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(self.pipeline._consume_parallel_plan_product("my-spec", self.vp))
        self.assertEqual(
            self.engine._read_parallel_plan_marker("my-spec").get("status"), "discarded"
        )
        self.assertFalse((self.vp / "test_scenarios.json").exists())

    def test_dispatched_dead_run_times_out_to_serial(self):
        # 在飞但 run 已死（daemon 重启）：立即停等 → 取消+隔离+转串行
        self._marker("dispatched")
        (self.vp / "test_scenarios.json").write_text("[{}]", encoding="utf-8")
        self.engine._stop_parallel_planning = MagicMock()
        with patch.object(
            type(self.pipeline), "_PARALLEL_PLAN_WAIT_POLL_SECONDS", 0.01
        ):
            self.assertTrue(self.pipeline._consume_parallel_plan_product("my-spec", self.vp))
        self.engine._stop_parallel_planning.assert_called_once()
        self.assertEqual(
            self.engine._read_parallel_plan_marker("my-spec").get("status"), "discarded"
        )

    def test_dispatched_state_migrated_returns_false(self):
        # 等待期间状态已迁移（人工接管）→ 丢弃本流水线
        self._marker("dispatched")
        self.sm.update_spec("my-spec", {"status": "blocked"})
        self.assertFalse(self.pipeline._consume_parallel_plan_product("my-spec", self.vp))

    def test_failed_marker_goes_serial(self):
        self._marker("failed")
        self.assertTrue(self.pipeline._consume_parallel_plan_product("my-spec", self.vp))
        self.assertEqual(
            self.engine._read_parallel_plan_marker("my-spec").get("status"), "failed"
        )


# ── 3.4 judge 轮内治理 ────────────────────────────────────────────────────


class TestJudgeRoundGovernance(_EngineCase):
    """任务 3.1/3.2：轮内计数、阈值停派升级、轮重置、扩充记账、fast-track 统计。"""

    def setUp(self):
        super().setUp()
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition("my-spec", st)
        self.pipeline = self.engine._verification
        self.notifier = MagicMock()
        self.pipeline._context.escalation_notifier = self.notifier
        # spec 戳数据源（is_verdict_stable 需要 spec.md + scenarios.json）
        specs_dir = self.root / "spec" / "changes" / "my-spec" / "specs" / "cap-a"
        specs_dir.mkdir(parents=True, exist_ok=True)
        (specs_dir / "spec.md").write_text("# Spec\ncontent", encoding="utf-8")
        (self.vp / "scenarios.json").write_text("{}", encoding="utf-8")
        # 判定上下文锚（report.json 在盘 = 可治理；gate 依其 mtime 识别重执行）
        (self.vp / "report.json").write_text("{}", encoding="utf-8")

    def test_first_two_dispatches_pass_gate_and_count(self):
        self.assertIsNone(self.pipeline._judge_dispatch_gate("my-spec"))
        self.assertIsNone(self.pipeline._judge_dispatch_gate("my-spec"))
        entry = self.sm.read_one("my-spec")
        self.assertEqual(int(entry["_judge_round_real"]), 2)
        self.assertEqual(int(entry["_judge_real_dispatches"]), 2)

    def test_third_dispatch_stopped_with_escalation_once(self):
        self.pipeline._judge_dispatch_gate("my-spec")
        self.pipeline._judge_dispatch_gate("my-spec")
        self.assertFalse(
            self.pipeline._judge_dispatch_gate("my-spec"),
            "轮内达阈值后第 3 次派发必须被阻止",
        )
        self.assertEqual(self.notifier.call_count, 1, "人工升级每轮只发一次")
        kwargs = self.notifier.call_args.kwargs
        self.assertEqual(kwargs.get("signal_type"), "judge_round_rerun_cap")
        # spec 保持 testing 可重试（MUST NOT 冻结/销毁产物）
        self.assertEqual(self.sm.read_one("my-spec")["status"], "testing")
        # 再次进入 gate：仅 INFO 留痕，不重复告警
        self.assertFalse(self.pipeline._judge_dispatch_gate("my-spec"))
        self.assertEqual(self.notifier.call_count, 1)

    def test_round_counters_reset_on_new_verify_round(self):
        self.pipeline._judge_dispatch_gate("my-spec")
        self.pipeline._judge_dispatch_gate("my-spec")
        self.sm.update_spec("my-spec", {"_verify_fail_rounds": 1})  # bug-found 修复 → 新轮
        self.assertIsNone(
            self.pipeline._judge_dispatch_gate("my-spec"),
            "新验证轮计数重置，首次派发放行",
        )
        entry = self.sm.read_one("my-spec")
        self.assertEqual(int(entry["_judge_round_real"]), 1)
        self.assertEqual(int(entry["_judge_real_dispatches"]), 3, "生命周期计数跨轮累计")

    def test_report_rer_execution_resets_round_counters(self):
        # scenario-repair 重入语义：同轮内 report.json 重执行（mtime 变化）
        # → 新判定上下文，轮内计数重置，重派不受阈值拦截
        self.pipeline._judge_dispatch_gate("my-spec")
        self.pipeline._judge_dispatch_gate("my-spec")
        report = self.vp / "report.json"
        report.write_text("{}", encoding="utf-8")
        import os

        os.utime(report, ns=(10**18, 10**18))  # 强制新 mtime
        self.assertIsNone(
            self.pipeline._judge_dispatch_gate("my-spec"),
            "report 重执行 → 新判定上下文，第 3 次派发放行",
        )
        self.assertEqual(int(self.sm.read_one("my-spec")["_judge_round_real"]), 1)

    def test_fasttrack_hit_counted_not_real_dispatch(self):
        from core.verify_report import (
            compute_spec_stamp,
            VERDICT_STABILITY_FILENAME,
        )

        stamp = compute_spec_stamp(self.root, "my-spec")
        report_mtime = (self.vp / "report.json")
        report_mtime.write_text("{}", encoding="utf-8")
        data = {
            "stamp": stamp,
            "report_mtime_ns": report_mtime.stat().st_mtime_ns,
            "rounds": [
                {"status": "bug-found", "failed_ids": ["s1"], "at": "2026-09-01"},
                {"status": "bug-found", "failed_ids": ["s1"], "at": "2026-09-02"},
            ],
            "updated_at": "2026-09-02T00:00:00Z",
        }
        (self.vp / VERDICT_STABILITY_FILENAME).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        result = self.pipeline._judge_dispatch_gate("my-spec")
        self.assertIsNotNone(result, "verdict 稳定 → 返回合成复用结果（fast-track 命中）")
        entry = self.sm.read_one("my-spec")
        self.assertEqual(int(entry["_judge_fasttrack_hits"]), 1)
        self.assertEqual(
            int(entry.get("_judge_real_dispatches", 0) or 0), 0, "命中不计真实派发"
        )

    def test_expansion_charged_for_expandable_violations_only_once(self):
        violations = [{"scenario_id": "s1", "status": "fail", "reason": "evidence 为空"}]
        self.assertEqual(
            self.pipeline._judge_charge_verdict_retry("my-spec", violations), "expansion"
        )
        entry = self.sm.read_one("my-spec")
        self.assertEqual(int(entry["_judge_round_expanded"]), 1)
        self.assertEqual(int(entry["_judge_round_real"]), 0, "扩充不计真实派发")
        # 名额耗尽 → 真实派发
        self.assertEqual(
            self.pipeline._judge_charge_verdict_retry("my-spec", violations), "real"
        )
        self.assertEqual(int(self.sm.read_one("my-spec")["_judge_round_real"]), 1)

    def test_non_expandable_violations_count_as_real(self):
        violations = [
            {"scenario_id": "s1", "status": "fail", "reason": "classification 缺失或取值非法"}
        ]
        self.assertEqual(
            self.pipeline._judge_charge_verdict_retry("my-spec", violations), "real"
        )
        self.assertEqual(int(self.sm.read_one("my-spec")["_judge_round_real"]), 1)

    def test_expandable_classifier_wordlist(self):
        self.assertTrue(is_expandable_evidence_violation("evidence 为空"))
        self.assertFalse(is_expandable_evidence_violation("report.json 非对象"))
        self.assertFalse(is_expandable_evidence_violation("assertion_triage 第 1 条 evidence 为空"))
        self.assertFalse(is_expandable_evidence_violation(None))


class TestJudgeSummaryFields(_EngineCase):
    """任务 3.3：读侧 summary 字段（缺失 None、有值 int）。"""

    def test_summary_fields_fail_open_and_present(self):
        from core.dashboard.data.summary import spec_summary

        entry = self.sm.read_one("my-spec") or {}
        summary = spec_summary(self.root, "my-spec", entry)
        self.assertIsNone(
            summary.get("judge_fasttrack_hits"), "历史 spec 无记录 → None（缺失容错）"
        )
        self.assertIsNone(summary.get("judge_real_dispatches"))
        self.sm.update_spec("my-spec", {"_judge_fasttrack_hits": 4, "_judge_real_dispatches": 2})
        entry = self.sm.read_one("my-spec") or {}
        summary = spec_summary(self.root, "my-spec", entry)
        self.assertEqual(summary.get("judge_fasttrack_hits"), 4)
        self.assertEqual(summary.get("judge_real_dispatches"), 2)


# ── 4.4 verdict 缓存四元组 ────────────────────────────────────────────────


class TestScenarioDefinitionFingerprint(unittest.TestCase):
    def test_volatile_keys_excluded(self):
        base = dict(VALID_SCENARIO)
        a = scenario_definition_fingerprint(base)
        b = scenario_definition_fingerprint(
            {**base, "status": "pass", "evidence": "x", "classification": "flaky",
             "assertion_triage": [], "cached_source": "verdict_cache",
             "attribution_level": "evidence-backed", "assertion_results": [{"pass": True}]}
        )
        self.assertEqual(a, b, "judge/执行易变字段不得影响定义指纹")

    def test_definition_change_changes_fingerprint(self):
        a = scenario_definition_fingerprint(dict(VALID_SCENARIO))
        b = scenario_definition_fingerprint(
            {**VALID_SCENARIO, "description": "改了描述"}
        )
        self.assertNotEqual(a, b)

    def test_non_dict_returns_empty(self):
        self.assertEqual(scenario_definition_fingerprint(None), "")


class TestBuildConfigFingerprints(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_fingerprint_stable_and_sensitive(self):
        self.assertEqual(compute_build_fingerprint(self.tmp), "", "无清单 → fail-closed 空串")
        (self.tmp / "package.json").write_text("{}")
        fp1 = compute_build_fingerprint(self.tmp)
        self.assertTrue(fp1)
        self.assertEqual(fp1, compute_build_fingerprint(self.tmp), "同内容稳定")
        (self.tmp / "package-lock.json").write_text('{"v":2}')
        self.assertNotEqual(fp1, compute_build_fingerprint(self.tmp), "清单变化 → 指纹变化")

    def test_verify_config_fingerprint(self):
        self.assertEqual(compute_verify_config_fingerprint(self.tmp), "")
        (self.tmp / ".fenix").mkdir()
        (self.tmp / ".fenix" / "verify.yaml").write_text("timeout: 30\n")
        fp = compute_verify_config_fingerprint(self.tmp)
        self.assertTrue(fp)
        (self.tmp / ".fenix" / "verify.yaml").write_text("timeout: 60\n")
        self.assertNotEqual(fp, compute_verify_config_fingerprint(self.tmp))


class TestExtractSourceFilesAndQuad(unittest.TestCase):
    def test_extract_source_files(self):
        desc = "校验列表页。见 core/dashboard/x.py:12 与 ui/a.ts:3，另 ./b.py:1"
        self.assertEqual(
            extract_scenario_source_files(desc),
            {"core/dashboard/x.py", "ui/a.ts", "b.py"},
        )
        self.assertEqual(extract_scenario_source_files("无出处标注"), set())
        self.assertEqual(extract_scenario_source_files(None), set())

    def test_quad_validation(self):
        sc = dict(VALID_SCENARIO)
        entry = {
            "definition_fingerprint": scenario_definition_fingerprint(sc),
            "build_fingerprint": "b1",
            "verify_config_fingerprint": "c1",
        }
        self.assertTrue(verdict_cache_entry_valid(entry, sc, "b1", "c1"))
        self.assertFalse(verdict_cache_entry_valid(entry, sc, "b2", "c1"), "构建指纹不匹配")
        self.assertFalse(verdict_cache_entry_valid(entry, sc, "b1", "c2"), "配置指纹不匹配")
        self.assertFalse(verdict_cache_entry_valid(entry, sc, "", "c1"), "分量缺失 fail-closed")
        self.assertFalse(verdict_cache_entry_valid(None, sc, "b1", "c1"))
        changed = {**sc, "steps": []}
        self.assertFalse(
            verdict_cache_entry_valid(entry, changed, "b1", "c1"), "场景定义变化 → 失效"
        )

    def test_save_injects_meta_and_load_skips(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            save_verdict_cache(tmp, "s", {"s1": {"status": "pass"}})
            data = load_verdict_cache(tmp, "s")
            self.assertIn("_meta", data)
            self.assertIn("head_at_write", data["_meta"])
            entries = {k: v for k, v in data.items() if k != "_meta"}
            self.assertEqual(list(entries), ["s1"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestPersistVerdictCachePassEntries(_EngineCase):
    """任务 4.1：写侧 PASS 条目 + 四元组分量（定义指纹从冻结场景文件重放）。"""

    def _expected_defp(self, file_dict):
        # 读侧 prune 对 load_scenarios 产物（TestScenario）取 to_dict 投影——
        # 期望指纹必须经同一往返，而非原始 dict 投影
        from core.verify_engine.scenarios import TestScenario

        return scenario_definition_fingerprint(TestScenario.from_dict(file_dict).to_dict())

    def test_pass_entries_written_with_quad(self):
        # 四元组建档前提：构建清单 + 验证配置在盘（缺失则指纹空串 fail-closed）
        (self.root / "package.json").write_text("{}")
        (self.root / ".fenix" / "verify.yaml").write_text("timeout: 30\n")
        file_scenarios = [
            {**VALID_SCENARIO, "id": "s1", "description": "d1"},
            {**VALID_SCENARIO, "id": "s2", "description": "d2"},
            {**VALID_SCENARIO, "id": "s3", "description": "d3"},
        ]
        (self.vp / "test_scenarios.json").write_text(
            json.dumps(file_scenarios, ensure_ascii=False), encoding="utf-8"
        )
        report = {
            "scenarios": [
                {"scenario_id": "s1", "status": "pass", "description": "d1"},
                {"scenario_id": "s2", "status": "fail", "classification": "product-bug",
                 "evidence": "ev", "assertion_triage": [], "description": "d2"},
                {"scenario_id": "s3", "status": "pass", "description": "d3"},
            ]
        }
        self.pipeline = self.engine._verification
        self.pipeline._persist_verdict_cache("my-spec", report)
        data = load_verdict_cache(self.root, "my-spec")
        self.assertEqual(data["s1"]["status"], "pass", "PASS 条目必须入缓存（读侧才有据可采信）")
        self.assertEqual(
            data["s1"]["definition_fingerprint"],
            self._expected_defp(file_scenarios[0]),
            "定义指纹必须取自冻结场景文件重放（TestScenario 投影），非判定 dict 投影",
        )
        self.assertIn("build_fingerprint", data["s1"])
        self.assertIn("verify_config_fingerprint", data["s1"])
        # 端到端：写侧条目须能被读侧四元组校验采信（回归判定 dict 投影失配）
        from core.verify_engine.scenarios import TestScenario

        build_fp = compute_build_fingerprint(self.root)
        config_fp = compute_verify_config_fingerprint(self.root)
        self.assertTrue(
            verdict_cache_entry_valid(
                data["s1"],
                TestScenario.from_dict(file_scenarios[0]).to_dict(),
                build_fp,
                config_fp,
            ),
            "写侧条目 × 读侧 TestScenario 投影必须四元组全等",
        )
        self.assertIn("s2", data, "non-PASS 条目沿用既有行为")
        self.assertEqual(
            data["s2"]["definition_fingerprint"],
            self._expected_defp(file_scenarios[1]),
        )
        self.assertEqual(data["s3"]["status"], "pass")
        self.assertIn("_meta", data)


# ── 4.2 修复轮裁剪与合成 / 4.3 fail-open ──────────────────────────────────


def _testscenario_defp(file_dict):
    """读侧口径的期望定义指纹：load_scenarios 产物（TestScenario）的 to_dict 投影。

    prune 读侧与写侧重放（_round_definition_fingerprints）都从冻结文件 load
    出 TestScenario 再投影——原始 dict 投影（id/steps/kind 键集不同）必然失配。
    """
    from core.verify_engine.scenarios import TestScenario

    return scenario_definition_fingerprint(TestScenario.from_dict(file_dict).to_dict())


class TestPruneRescanScenarios(_EngineCase):
    def setUp(self):
        super().setUp()
        self.sm.transition("my-spec", "implemented")
        self.sm.transition("my-spec", "testing")
        self.pipeline = self.engine._verification
        # 四元组可成立的最低条件：构建清单 + 验证配置在盘
        (self.root / "package.json").write_text("{}")
        (self.root / ".fenix" / "verify.yaml").write_text("timeout: 30\n")
        self.sc1 = {"scenario_id": "s1", "description": "失败场景 出处 core/a.py:1"}
        self.sc2 = {"scenario_id": "s2", "description": "通过场景 出处 core/b.py:2"}
        self.scenarios = [self.sc1, self.sc2]
        prev = {
            "scenarios": [
                {"scenario_id": "s1", "status": "fail", "classification": "product-bug"},
                {"scenario_id": "s2", "status": "pass", "evidence": "ok"},
            ]
        }
        (self.vp / "report.json").write_text(
            json.dumps(prev, ensure_ascii=False), encoding="utf-8"
        )
        entry = {
            "status": "pass",
            "definition_fingerprint": scenario_definition_fingerprint(self.sc2),
            "build_fingerprint": compute_build_fingerprint(self.root),
            "verify_config_fingerprint": compute_verify_config_fingerprint(self.root),
        }
        save_verdict_cache(
            self.root, "my-spec",
            {"s2": entry, "_meta": {"head_at_write": "head123"}},
        )
        self.sm.update_spec("my-spec", {"_verify_fail_rounds": 1})

    def test_first_round_full_execution(self):
        self.sm.update_spec("my-spec", {"_verify_fail_rounds": 0})
        executed, cached, note = self.pipeline._prune_rescan_scenarios("my-spec", self.scenarios)
        self.assertEqual([sc["scenario_id"] for sc in executed], ["s1", "s2"])
        self.assertEqual(cached, {})

    def test_prune_keeps_failed_and_trusts_valid_cache(self):
        with patch.object(self.pipeline, "_fix_diff_files", return_value=set()):
            executed, cached, _ = self.pipeline._prune_rescan_scenarios(
                "my-spec", self.scenarios
            )
        self.assertEqual([sc["scenario_id"] for sc in executed], ["s1"])
        self.assertEqual(list(cached), ["s2"])

    def test_source_file_touched_by_fix_diff_invalidates(self):
        with patch.object(
            self.pipeline, "_fix_diff_files", return_value={"core/b.py"}
        ):
            executed, cached, _ = self.pipeline._prune_rescan_scenarios(
                "my-spec", self.scenarios
            )
        self.assertEqual(cached, {}, "fix diff 触碰出处文件 → 失效条件②")
        self.assertEqual(len(executed), 2)

    def test_missing_source_annotation_fails_closed(self):
        self.scenarios[1] = {"scenario_id": "s2", "description": "无出处标注"}
        entry = {
            "status": "pass",
            "definition_fingerprint": scenario_definition_fingerprint(self.scenarios[1]),
            "build_fingerprint": compute_build_fingerprint(self.root),
            "verify_config_fingerprint": compute_verify_config_fingerprint(self.root),
        }
        save_verdict_cache(self.root, "my-spec", {"s2": entry, "_meta": {"head_at_write": "h"}})
        with patch.object(self.pipeline, "_fix_diff_files", return_value=set()):
            executed, cached, _ = self.pipeline._prune_rescan_scenarios(
                "my-spec", self.scenarios
            )
        self.assertEqual(cached, {}, "出处标注缺失 → 存疑即照跑")
        self.assertEqual(len(executed), 2)

    def test_unavailable_fix_diff_fails_closed(self):
        with patch.object(self.pipeline, "_fix_diff_files", return_value=None):
            executed, cached, _ = self.pipeline._prune_rescan_scenarios(
                "my-spec", self.scenarios
            )
        self.assertEqual(cached, {}, "修复 diff 不可算 → fail-closed 全跑")

    def test_depends_on_closure_recruits_prerequisites(self):
        sc3 = {"scenario_id": "s3", "description": "前置 出处 core/c.py:3"}
        self.sc1["depends_on"] = ["s3"]
        entry3 = {
            "status": "pass",
            "definition_fingerprint": scenario_definition_fingerprint(sc3),
            "build_fingerprint": compute_build_fingerprint(self.root),
            "verify_config_fingerprint": compute_verify_config_fingerprint(self.root),
        }
        save_verdict_cache(
            self.root, "my-spec",
            {
                "s2": {
                    "status": "pass",
                    "definition_fingerprint": scenario_definition_fingerprint(self.sc2),
                    "build_fingerprint": compute_build_fingerprint(self.root),
                    "verify_config_fingerprint": compute_verify_config_fingerprint(self.root),
                },
                "s3": entry3,
                "_meta": {"head_at_write": "h"},
            },
        )
        with patch.object(self.pipeline, "_fix_diff_files", return_value=set()):
            executed, cached, _ = self.pipeline._prune_rescan_scenarios(
                "my-spec", [self.sc1, self.sc2, sc3]
            )
        ids = {sc["scenario_id"] for sc in executed}
        self.assertIn("s3", ids, "失败场景的 depends_on 前置必须照跑（闭包）")
        self.assertNotIn("s3", cached)

    def test_corrupt_cache_falls_open_to_full(self):
        (self.vp / "verdict_cache.json").write_text("{bad", encoding="utf-8")
        executed, cached, _ = self.pipeline._prune_rescan_scenarios("my-spec", self.scenarios)
        self.assertEqual(len(executed), 2)
        self.assertEqual(cached, {})

    def test_merge_synthesizes_full_report_and_overwrites(self):
        subset_report = {
            "spec": "my-spec",
            "summary": {"total": 1, "passed": 0, "warnings": 0, "failed": 1,
                        "errors": 0, "blocked_env": 0},
            "scenarios": [
                {"scenario_id": "s1", "status": "fail", "classification": "product-bug"}
            ],
        }
        prev_s2 = {"scenario_id": "s2", "status": "pass", "evidence": "ok"}
        merged = self.pipeline._merge_cached_scenario_results(
            "my-spec", subset_report, self.scenarios, {"s2": prev_s2}
        )
        ids = [sc["scenario_id"] for sc in merged["scenarios"]]
        self.assertEqual(ids, ["s1", "s2"], "合成报告保持冻结序")
        self.assertEqual(merged["scenarios"][1].get("cached_source"), "verdict_cache")
        self.assertEqual(merged["summary"]["total"], 2)
        self.assertEqual(merged["summary"]["passed"], 1)
        self.assertEqual(merged["summary"]["failed"], 1)
        self.assertEqual(merged.get("resumed_from_cache"), ["s2"])
        on_disk = json.loads(
            (self.vp / "report.json").read_text(encoding="utf-8")
        )
        self.assertEqual([sc["scenario_id"] for sc in on_disk["scenarios"]], ["s1", "s2"])

    def test_merge_blocked_env_counts_into_warnings(self):
        subset_report = {
            "spec": "my-spec",
            "summary": {"total": 1, "passed": 0, "warnings": 1, "failed": 0,
                        "errors": 0, "blocked_env": 1},
            "scenarios": [{"scenario_id": "s1", "status": "blocked-env"}],
        }
        merged = self.pipeline._merge_cached_scenario_results(
            "my-spec", subset_report, [self.sc1], {}
        )
        self.assertEqual(merged["summary"]["warnings"], 1)
        self.assertEqual(merged["summary"]["blocked_env"], 1)

    def _write_all_pass_prev_and_full_cache(
        self, defs, fingerprint_of=scenario_definition_fingerprint
    ):
        """上轮全 pass + 按 defs 形状写四元组缓存（零执行收敛态的前置）。

        ``fingerprint_of`` 须与被测读侧的投影口径同形：prune 层直喂 raw dict
        → 默认 raw 投影；_execute_stage2 层经 load_scenarios → TestScenario
        to_dict 投影（传 ``_testscenario_defp``）。
        """
        prev = {
            "scenarios": [
                {"scenario_id": "s1", "status": "pass", "evidence": "ok"},
                {"scenario_id": "s2", "status": "pass", "evidence": "ok"},
            ]
        }
        (self.vp / "report.json").write_text(
            json.dumps(prev, ensure_ascii=False), encoding="utf-8"
        )

        def _entry(d):
            return {
                "status": "pass",
                "definition_fingerprint": fingerprint_of(d),
                "build_fingerprint": compute_build_fingerprint(self.root),
                "verify_config_fingerprint": compute_verify_config_fingerprint(self.root),
            }

        save_verdict_cache(
            self.root, "my-spec",
            {"s1": _entry(defs[0]), "s2": _entry(defs[1]),
             "_meta": {"head_at_write": "head123"}},
        )

    def test_zero_execution_trusts_all_cache(self):
        # 上轮全 pass 收敛态：无失败、无失效、无闭包 → 执行集允许为空，
        # 全缓存采信零执行出报告（任务 4.2 字面语义）
        self._write_all_pass_prev_and_full_cache([self.sc1, self.sc2])
        with patch.object(self.pipeline, "_fix_diff_files", return_value=set()):
            executed, cached, _ = self.pipeline._prune_rescan_scenarios(
                "my-spec", self.scenarios
            )
        self.assertEqual(executed, [])
        self.assertEqual(set(cached), {"s1", "s2"})

    def test_stage2_zero_execution_skips_engine(self):
        # _execute_stage2 零执行合成：不构造引擎（构造即测试失败）、直接
        # 产出全缓存合成报告并覆写 report.json
        from core.verdict_check import save_report

        file_scenarios = [
            {**VALID_SCENARIO, "id": "s1", "description": "失败场景 出处 core/a.py:1"},
            {**VALID_SCENARIO, "id": "s2", "description": "通过场景 出处 core/b.py:2"},
        ]
        scenarios_file = self.vp / "test_scenarios.json"
        scenarios_file.write_text(
            json.dumps(file_scenarios, ensure_ascii=False), encoding="utf-8"
        )
        # 缓存定义指纹须按读侧口径（TestScenario to_dict 投影）写入
        self._write_all_pass_prev_and_full_cache(file_scenarios, _testscenario_defp)
        prev = {
            "scenarios": [
                {"scenario_id": "s1", "status": "pass", "evidence": "ok"},
                {"scenario_id": "s2", "status": "pass", "evidence": "ok"},
            ]
        }
        save_report(self.root, "my-spec", prev)
        with patch.object(self.pipeline, "_fix_diff_files", return_value=set()), \
             patch.object(
                 self.pipeline, "_ensure_app_reachable", return_value=(True, False, "")
             ), \
             patch.object(self.pipeline, "_run_scenario_static_check"), \
             patch(
                 "core.verify_engine.VerifyEngine",
                 side_effect=AssertionError("零执行路径不得构造引擎"),
             ):
            env_error, report, _reachable, _note, aborted = (
                self.pipeline._execute_stage2("my-spec", self.vp, scenarios_file)
            )
        self.assertIsNone(env_error)
        self.assertFalse(aborted)
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["summary"]["passed"], 2)
        self.assertEqual(report["pruned_execution"], {"executed": 0, "resumed": 2})
        self.assertEqual(
            report["scenarios"][0].get("cached_source"), "verdict_cache"
        )


if __name__ == "__main__":
    unittest.main()
