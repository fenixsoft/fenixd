"""
fix-verify-late-result-terminal-clobber 回归：verified 终态收敛点回收在飞 verify 车道。

覆盖（tasks 2.4）：
- 在飞 verifier run（完整 epoch run id）登记后 SPEC 推进 done → 取消旗标
  与轮询环消费键收敛（``_cancel_is_requested(<在飞 run id>)`` 为真，
  非仅 ``cancel_run`` 返回值），且不落裸 ``verify-<spec>`` 键
- 在队 verifier 条目被摘除（含无在飞 run 场景）
- 收尾异常（cancel_run 抛错）不影响 verified → done 主流程
- 归属复核：同根后代 spec 与其它 agent_type 的在飞 run 不被波及
- D7 逃生门（验证进度不完整回退 testing）与任务缺口 blocker（保持 verified）
  均不触发收尾（在飞 run 存活、无残留取消旗标、在队条目保留）
"""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine
from core.agent_runner.runner import AgentRunner


def _push_spec_to(sm: StateMachine, name: str, target: str):
    """把 spec 沿合法链走到 target（直写 status，与 test_daemon_lifecycle_races 同口径）。"""
    if sm.read_one(name) is None:
        sm.add_spec(name, {"priority": 5})
    chain = {
        "testing": ["drafted", "ready", "implementing", "implemented", "testing"],
        "verified": [
            "drafted", "ready", "implementing", "implemented", "testing", "verified",
        ],
    }
    for step in chain[target]:
        sm.update_spec(name, {"status": step})


class TestVerifyLaneTerminalReclaim(unittest.TestCase):
    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger)
        # 门禁全放行：聚焦车道收尾本身（D7 用例单独覆写 vblocker）
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.engine._verification._check_verification_gate = MagicMock(return_value=None)
        self.engine._verification._evict_spec_serving = MagicMock()
        self.engine._on_spec_done = MagicMock()
        # 真实取消原语（__new__ 绕过 __init__，runner 测试既有处方；
        # 取消旗标集合/锁为惰性 property，注册表手工置备）
        self.runner = AgentRunner.__new__(AgentRunner)
        self.runner._running_agents = {}
        self.runner.logger = self.logger
        self.runner.project_root = Path(self.tmpdir)
        self.engine.agent_runner = self.runner

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _register_inflight(self, run_id: str) -> str:
        self.runner._running_agents[run_id] = MagicMock()
        return run_id

    def _enqueue_verifier(self, spec: str):
        self.engine._dispatcher._enqueue(spec, "verifier")

    def _queue_has_verifier(self, spec: str) -> bool:
        return any(
            e[1] == spec and e[2] == "verifier"
            for e in self.engine._dispatcher._run_queue
        )

    def _verified_to_done(self, name: str):
        _push_spec_to(self.sm, name, "verified")
        self.engine._on_spec_verified(name)

    def test_inflight_run_cancel_flag_converges_with_poll_loop(self):
        """在飞 run 取消旗标与消费键收敛（_cancel_is_requested 为真），队列条目摘除。"""
        spec = "lane-spec"
        rid = self._register_inflight(f"verify-{spec}-{int(time.time())}-a1")
        self._enqueue_verifier(spec)
        self._verified_to_done(spec)
        self.assertEqual(self.sm.read_one(spec)["status"], "done")
        # 关键断言：轮询环消费视角（传在飞 run 的完整 run 级 id）旗标为真——
        # 断言登记键与消费键收敛，MUST NOT 只断言 cancel_run 返回值
        self.assertTrue(
            self.runner._cancel_is_requested(rid),
            "取消旗标须以完整 run 级 id（含 epoch）登记并与消费键收敛",
        )
        self.assertNotIn(
            f"verify-{spec}",
            self.runner._cancel_requested,
            "MUST NOT 落裸 verify-<spec> 键（与消费点不收敛、取消静默失效）",
        )
        self.assertFalse(self._queue_has_verifier(spec), "在队 verifier 条目应被摘除")

    def test_queued_entry_removed_even_without_inflight_run(self):
        """无在飞 run 时仅摘除在队条目。"""
        spec = "queue-only-spec"
        self._enqueue_verifier(spec)
        self._verified_to_done(spec)
        self.assertEqual(self.sm.read_one(spec)["status"], "done")
        self.assertFalse(self._queue_has_verifier(spec))

    def test_runner_exception_does_not_block_done(self):
        """cancel_run 抛异常 → WARNING 兜底，verified → done 流转不受影响。"""
        spec = "boom-spec"
        self._register_inflight(f"verify-{spec}-{int(time.time())}-a1")
        self._enqueue_verifier(spec)
        self.runner.cancel_run = MagicMock(side_effect=RuntimeError("cancel boom"))
        self._verified_to_done(spec)
        self.assertEqual(
            self.sm.read_one(spec)["status"], "done",
            "收尾异常不得向 verified 主流程传播",
        )
        warning_texts = " ".join(str(c) for c in self.logger.warning.call_args_list)
        self.assertIn(spec, warning_texts, "WARNING 须含 spec")

    def test_descendant_and_other_agent_runs_not_cancelled(self):
        """归属复核：同根后代 spec 与其它 agent_type 的在飞 run 不被波及。"""
        spec = "fix-a"
        epoch = int(time.time())
        own = self._register_inflight(f"verify-{spec}-{epoch}-a1")
        descendant = self._register_inflight(f"verify-{spec}-b-{epoch}-a1")
        other_type = self._register_inflight(f"impl-{spec}-{epoch}-a1")
        self._verified_to_done(spec)
        self.assertTrue(self.runner._cancel_is_requested(own), "本 spec 的 verify run 应被取消")
        self.assertFalse(
            self.runner._cancel_is_requested(descendant),
            "同根后代 spec（fix-a-b）的在飞 run 不得被波及",
        )
        self.assertFalse(
            self.runner._cancel_is_requested(other_type),
            "其它 agent_type 的 run 不得被波及",
        )

    def test_d7_escape_hatch_keeps_lane_alive(self):
        """D7 逃生门回退 testing 时不收尾：在飞 run 存活、无取消旗标、在队条目保留。"""
        spec = "d7-spec"
        rid = self._register_inflight(f"verify-{spec}-{int(time.time())}-a1")
        self._enqueue_verifier(spec)
        self.engine._verification._check_verification_gate = MagicMock(
            return_value="验证未完成：1/3")
        _push_spec_to(self.sm, spec, "verified")
        self.engine._on_spec_verified(spec)
        self.assertEqual(
            self.sm.read_one(spec)["status"], "testing",
            "验证进度不完整应经 D7 逃生门回退 testing")
        self.assertFalse(
            self.runner._cancel_is_requested(rid),
            "门禁要求续跑的在飞车道不得被拆（无残留取消旗标）")
        self.assertTrue(self._queue_has_verifier(spec), "在队条目不得被摘除")

    def test_task_gap_blocker_keeps_verified_without_reclaim(self):
        """任务缺口 blocker（保持 verified 人工裁决）路径同样不收尾。"""
        spec = "gap-spec"
        rid = self._register_inflight(f"verify-{spec}-{int(time.time())}-a1")
        self._enqueue_verifier(spec)
        self.engine._task_completion_blocker = MagicMock(
            return_value="任务缺口: 1 项未完成")
        _push_spec_to(self.sm, spec, "verified")
        self.engine._on_spec_verified(spec)
        self.assertEqual(self.sm.read_one(spec)["status"], "verified")
        self.assertFalse(self.runner._cancel_is_requested(rid))
        self.assertTrue(self._queue_has_verifier(spec))


if __name__ == "__main__":
    unittest.main()
