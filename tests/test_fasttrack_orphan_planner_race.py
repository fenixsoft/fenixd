"""fast-track 收尾竞态孤儿 planner run 回归测试（2026-09-08 事故）。

事故：fix-verify-cli-cwd-isolation 已 pushed，19:35 仍有 planner-plan 孤儿 run
在跑。根因双缺口：

1) fast-track spec 收尾仍经 implemented 中间态触发 spec_implemented 事件，
   ``_on_spec_implemented`` 无差别入队 verifier——与
   ``_fast_track_advance_to_verified`` 竞态派出孤儿 planner。平时靠 event_bus
   2s 轮询粒度吞掉快进事件维持不变量，收尾被慢操作拖过窗口即击穿。
2) 三段验证入口检查（fix-daemon-lifecycle-races D6）只查一次，阶段1 派
   planner run 前不再查——竞态窗口内状态从 testing 漂到 verified 后照派。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.pm_engine.verification import VerdictReadResult
from core.state_machine import StateMachine


class _OrphanRaceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md", self.logger)
        self.agent_runner = MagicMock()
        self.engine = PMEngine(
            self.sm, self.agent_runner, {}, self.project_root, self.logger
        )
        # 本类用例真实调 _run_three_stage_verification：引擎开头的
        # core.verify_engine importlib.reload（daemon 热更新设计）在测试进程里
        # 换掉 TestScenario/VerifyEngine 类对象，污染同进程后续测试的
        # isinstance 判定（test_cancel_holdstate_recovery 6ce7461e 同款处方）。
        from unittest.mock import patch as _patch
        self._reload_patcher = _patch("importlib.reload", lambda m: m)
        self._reload_patcher.start()
        self.addCleanup(self._reload_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_spec_mode(self, name, mode):
        d = self.project_root / "spec" / "changes" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text(
            f"schema: spec-driven\ncreated: 2026-09-08\nmode: {mode}\n",
            encoding="utf-8",
        )


class TestOnSpecImplementedFastTrackSkip(_OrphanRaceTestBase):
    """修复 B：fast-track spec 的 spec_implemented 不入队 verifier。"""

    def test_fast_track_not_enqueued(self):
        self._write_spec_mode("ft-spec", "fast-track")
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_implemented("ft-spec")
        self.engine._enqueue.assert_not_called()

    def test_full_mode_still_enqueued(self):
        self._write_spec_mode("full-spec", "full")
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_implemented("full-spec")
        self.engine._enqueue.assert_called_once_with("full-spec", "verifier")

    def test_missing_yaml_defaults_to_full(self):
        # .spec.yaml 缺失 = 存量 full 模式 spec（读侧容错缺省 full），行为不回归
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_implemented("ghost-spec")
        self.engine._enqueue.assert_called_once_with("ghost-spec", "verifier")


class TestStage1StatusRecheckBeforePlanner(_OrphanRaceTestBase):
    """修复 A：阶段1 派 planner run 前重查 spec 状态，非 testing 即丢弃。"""

    def test_planner_not_dispatched_when_spec_left_testing(self):
        # 复现事故时序：入口检查时 spec=testing（通过 D6），阶段1 派 run 前
        # 状态已被 fast-track advance 推到 verified——此时再派 planner 即孤儿。
        calls = {"n": 0}

        def fake_read_one(name):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"status": "testing"}
            return {"status": "verified"}

        self.engine.state_machine.read_one = MagicMock(side_effect=fake_read_one)
        # 修复缺失时流程会走远（run_planner 被调 → 后续路径）——配置合法返回值
        # 让失败收敛到断言点（run_planner 未被调用），不被无关异常污染。
        plan_result = MagicMock()
        plan_result.success = True
        plan_result.duration_seconds = 120.0
        self.agent_runner.run_planner.return_value = plan_result
        self.engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.failure(
                "unknown-status", "status='plan-invalid'"))

        try:
            self.engine._run_three_stage_verification("race-spec")
        except Exception:
            pass  # 修复缺失时下游路径可能抛错——断言点在 run_planner 未被调用

        self.agent_runner.run_planner.assert_not_called()
        self.agent_runner.ensure_planner_route_map.assert_not_called()

    def test_planner_still_dispatched_when_status_holds_testing(self):
        # 正常 full 模式不回归：状态保持 testing → 阶段1 照常出题。
        # run_planner 返回成功后经 _read_planner_result 非法值 raise 早退，
        # 不深入阶段2（本测试只关注阶段1 派发闸门语义）。
        self.engine.state_machine.read_one = MagicMock(
            return_value={"status": "testing"}
        )
        plan_result = MagicMock()
        plan_result.success = True
        plan_result.duration_seconds = 120.0
        self.agent_runner.run_planner.return_value = plan_result
        self.engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.failure(
                "unknown-status", "status='plan-invalid'"))

        with self.assertRaises(RuntimeError):
            self.engine._run_three_stage_verification("ok-spec")

        self.agent_runner.run_planner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
