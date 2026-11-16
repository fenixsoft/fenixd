"""evo-pure-attribution-parking-recovery-guard：纯归因停泊态与 Recovery 重派防重放。

覆盖 tasks.md 3.1 三组行为：

1. 拒收→停泊（1.1/1.2）：受理门拒收转「无修复纯归因模式」置 `_frozen_hold`
   停泊位（`frozen` 不置位）、error 留痕停泊原因；停泊态经
   ``admin_monitor.spec_is_undriven`` 共享判定单点豁免——orphaned_state 探测
   不判无驱动、``event_bus._recover_testing`` 不 re-trigger verify、judge
   rerun 计数不动（上游拦截零派发即零递增）。
2. 退出锚点（2.2）：unfreeze 人工处置（停泊态不走 `_resolve_preserved_branch`
   保留分支续做，普通解冻清理 + 重派退出）；新修复/验证 run 落地与场景修订
   写回信号经 ``update_spec`` 咽喉同一原子写解除停泊。
3. 防重放守卫（2.1）：命中沿用不派发（rerun 计数不动）、首见记账照常复核、
   指纹变化重新记账照常重派、非 test-defect 归因与产物缺失不命中。
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import (
    StateMachine,
    FROZEN_HOLD_FIELD,
    REPLAY_GUARD_FP_FIELD,
    REPLAY_GUARD_REVERIFIED_FIELD,
    spec_is_parked,
    _park_exit_signal,
)


def _make_pipe(tmpdir: str, sm: StateMachine):
    """构造最小 VerificationPipeline 桩（同 test_judge_repair_budget_alignment
    ._make_pipe 形态）。"""
    from core.pm_engine.verification import VerificationPipeline

    pm = SimpleNamespace()
    pm.project_root = Path(tmpdir)
    pm.logger = MagicMock()
    pm.state_machine = sm
    pm.agent_runner = MagicMock()
    pm._send_human_escalation_alert = MagicMock()
    pm._enqueue = MagicMock()
    pm._process_queue = MagicMock()
    return VerificationPipeline(pm)


def _make_testing_spec(sm: StateMachine, name: str = "demo-spec") -> None:
    sm.add_spec(name, {"priority": 5})
    sm.transition(name, "ready")
    sm.transition(name, "implementing")
    sm.transition(name, "implemented")
    sm.transition(name, "testing")


def _make_parked(sm: StateMachine, name: str = "demo-spec") -> None:
    """构造纯归因停泊态条目（受理门拒收后的形态：_frozen_hold 置位、frozen 不在场）。"""
    _make_testing_spec(sm, name)
    sm.update_spec(name, {FROZEN_HOLD_FIELD: True})


def _write_prev_judge_result(tmpdir: Path, spec: str, classification: str) -> None:
    """落 prev-judge-result.json（runner._archive_prev_judge_result 归档位）。"""
    vp = Path(tmpdir) / ".fenix" / "verify-progress" / spec
    vp.mkdir(parents=True, exist_ok=True)
    (vp / "prev-judge-result.json").write_text(
        json.dumps(
            {
                "status": "bug-found",
                "verification": {
                    "verdict": "bug-found",
                    "scenarios": [
                        {
                            "scenario_id": "scn-a",
                            "status": "failed",
                            "classification": classification,
                        },
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class TestParkingHelpers(unittest.TestCase):
    """spec_is_parked / _park_exit_signal 单点判定。"""

    def test_spec_is_parked_shapes(self):
        self.assertTrue(spec_is_parked({"_frozen_hold": True}))
        self.assertTrue(spec_is_parked({"_frozen_hold": True, "frozen": False}))
        # 真冻结终止（frozen 在场）不是停泊
        self.assertFalse(spec_is_parked({"_frozen_hold": True, "frozen": True}))
        self.assertFalse(spec_is_parked({"_frozen_hold": False}))
        self.assertFalse(spec_is_parked({}))
        self.assertFalse(spec_is_parked(None))
        self.assertFalse(spec_is_parked("not-a-dict"))

    def test_park_exit_signal_shapes(self):
        self.assertTrue(_park_exit_signal({"implementer_run": "impl-1"}))
        self.assertTrue(_park_exit_signal({"tester_run": "verify-1"}))
        self.assertTrue(
            _park_exit_signal({"_scenario_revision_reverify_pending": True})
        )
        # 清锚写点（None）与无关更新不算落地
        self.assertFalse(_park_exit_signal({"implementer_run": None}))
        self.assertFalse(_park_exit_signal({"error": "x"}))
        self.assertFalse(_park_exit_signal(None))


class TestAcceptanceGateParksSpec(unittest.TestCase):
    """1.1：受理门拒收转纯归因 → 置 _frozen_hold 停泊位（frozen 不置位）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", MagicMock())
        _make_testing_spec(self.sm)
        vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / "demo-spec"
        vp.mkdir(parents=True)
        (vp / "report.json").write_text(
            json.dumps(
                {
                    "status": "bug-found",
                    "scenarios": [
                        {
                            "scenario_id": "scn-a",
                            "status": "failed",
                            "classification": "test-defect",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.sm.update_spec("demo-spec", {"_scenario_repair_exhausted_rounds": 1})
        self.pipe = _make_pipe(self.tmpdir, self.sm)
        self.pipe._apply_scenario_freeze = MagicMock(return_value={})
        self.pipe._run_three_stage_verification = MagicMock()
        self.pipe._apply_verified = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rejection_parks_spec(self):
        """耗尽态拒收 → 停泊位写入、frozen 不置位、error 留痕停泊原因。"""
        rv = self.pipe._handle_scenario_repaired("demo-spec", "scenario-repaired", 0)
        self.assertTrue(rv)
        # 不触发重执行重入
        self.pipe._run_three_stage_verification.assert_not_called()
        entry = self.sm.read_one("demo-spec")
        # 停泊位：_frozen_hold 置位且 frozen 不在场（spec_is_parked 单点判定）
        self.assertTrue(entry.get(FROZEN_HOLD_FIELD))
        self.assertFalse(entry.get("frozen"))
        self.assertTrue(spec_is_parked(entry))
        # spec 保持 testing，error 留痕停泊原因与退出锚点
        self.assertEqual(entry["status"], "testing")
        err = str(entry.get("error") or "")
        self.assertIn("拒收", err)
        self.assertIn("停泊", err)
        self.assertIn("退出锚点", err)
        warnings = [
            str(c.args[-1] if c.args else "")
            for c in self.pipe._context.logger.warning.call_args_list
        ]
        self.assertTrue(any("转纯归因停泊" in w for w in warnings))

    def test_repeated_rejection_stays_parked(self):
        """重复拒收停泊幂等：仍为停泊态、不派发。"""
        for _ in range(2):
            rv = self.pipe._handle_scenario_repaired(
                "demo-spec", "scenario-repaired", 0)
            self.assertTrue(rv)
        self.pipe._run_three_stage_verification.assert_not_called()
        entry = self.sm.read_one("demo-spec")
        self.assertTrue(spec_is_parked(entry))
        self.assertEqual(entry["status"], "testing")


class TestUndrivenParkingExemption(unittest.TestCase):
    """1.2：停泊态经 spec_is_undriven 共享判定单点豁免（无驱动告警与 Recovery
    恢复同源消费）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parked_entry_not_undriven(self):
        from core.admin_monitor import spec_is_undriven

        entry = {"status": "testing", FROZEN_HOLD_FIELD: True}
        # 停泊判定在最前（早于 pgrep/runs 扫描）——无需环境桩即早退
        self.assertFalse(spec_is_undriven(self.tmpdir, "spec-a", entry))

    def test_plain_undriven_testing_still_detected(self):
        from core.admin_monitor import spec_is_undriven

        entry = {"status": "testing"}
        with patch("core.admin_monitor._pgrep_live_worktree", return_value=False):
            self.assertTrue(spec_is_undriven(self.tmpdir, "spec-a", entry))


class TestRecoverTestingParkingSkip(unittest.TestCase):
    """1.2：_recover_testing 对停泊态不 re-trigger verify、rerun 计数不动。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        _make_parked(self.sm)
        self.sm.update_spec("demo-spec", {"_judge_rerun_count": 3})
        from core.event_bus import EventBus

        self.pm = MagicMock()
        self.pm.project_root = self.tmpdir
        self.bus = EventBus(self.state_path, self.sm, self.pm, {}, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parked_spec_not_redispatched(self):
        entry = self.sm.read_one("demo-spec")
        self.bus._recover_testing("demo-spec", entry)
        self.pm.handle_event.assert_not_called()
        # judge rerun 计数不动（上游拦截零派发即零递增）
        self.assertEqual(
            int(self.sm.read_one("demo-spec").get("_judge_rerun_count") or 0), 3)


class TestReplayGuard(unittest.TestCase):
    """2.1：Recovery 重派防重放守卫三态。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        _make_testing_spec(self.sm)
        self.spec = "demo-spec"
        # 指纹基建输入：场景集（spec 戳分量）+ 构建清单（产物指纹分量）
        vp = Path(self.tmpdir) / ".fenix" / "verify-progress" / self.spec
        vp.mkdir(parents=True)
        (vp / "scenarios.json").write_text(
            json.dumps([{"id": "scn-a", "description": "场景A"}]),
            encoding="utf-8",
        )
        (Path(self.tmpdir) / "requirements.txt").write_text(
            "pytest\n", encoding="utf-8")
        self._write_fingerprints()
        from core.event_bus import EventBus

        self.pm = MagicMock()
        self.pm.project_root = self.tmpdir
        self.bus = EventBus(self.state_path, self.sm, self.pm, {}, self.logger)
        self.entry = self.sm.read_one(self.spec)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_fingerprints(self):
        from core.verify_report import compute_spec_stamp
        from core.verdict_check import compute_build_fingerprint

        self.stamp = compute_spec_stamp(self.tmpdir, self.spec)
        self.build = compute_build_fingerprint(self.tmpdir)
        self.assertTrue(self.stamp)
        self.assertTrue(self.build)

    def _arm_guard(self, *, stamp=None, build=None, reverified=1):
        self.sm.update_spec(
            self.spec,
            {
                REPLAY_GUARD_FP_FIELD: json.dumps(
                    {"stamp": stamp if stamp is not None else self.stamp,
                     "build": build if build is not None else self.build},
                    ensure_ascii=False, sort_keys=True,
                ),
                REPLAY_GUARD_REVERIFIED_FIELD: reverified,
            },
        )

    def _run_recover(self):
        with patch("core.admin_monitor._pgrep_live_worktree", return_value=False):
            with patch.object(self.bus, "_admin_inflight_guard", return_value=False):
                self.bus._recover_testing(self.spec, self.entry)

    def test_guard_hit_skips_replay_and_keeps_rerun_count(self):
        """已复核过 + 指纹未变 + test-defect 归因 → 跳过重派、沿用归因、rerun 不动。"""
        self.sm.update_spec(self.spec, {"_judge_rerun_count": 4})
        _write_prev_judge_result(Path(self.tmpdir), self.spec, "test-defect")
        self._arm_guard(reverified=1)
        self._run_recover()
        self.pm.handle_event.assert_not_called()
        entry = self.sm.read_one(self.spec)
        self.assertEqual(int(entry.get("_judge_rerun_count") or 0), 4)
        infos = [str(c) for c in self.logger.info.call_args_list]
        self.assertTrue(any("防重放守卫命中" in c for c in infos))

    def test_first_sighting_reverifies_and_records(self):
        """首见指纹（尚未复核）→ 照常复核一次 + 持久记账 reverified=1。"""
        _write_prev_judge_result(Path(self.tmpdir), self.spec, "test-defect")
        self._run_recover()
        self.pm.handle_event.assert_called_once_with(
            "spec_implemented", self.spec, self.entry)
        entry = self.sm.read_one(self.spec)
        stored = json.loads(entry.get(REPLAY_GUARD_FP_FIELD))
        self.assertEqual(stored, {"stamp": self.stamp, "build": self.build})
        self.assertEqual(int(entry.get(REPLAY_GUARD_REVERIFIED_FIELD) or 0), 1)

    def test_fingerprint_change_rearms_and_dispatches(self):
        """指纹变化 → 守卫不命中：重新记账 + 照常重派（行为与现状一致）。"""
        _write_prev_judge_result(Path(self.tmpdir), self.spec, "test-defect")
        self._arm_guard(stamp="stale-stamp", build="stale-build", reverified=1)
        self._run_recover()
        self.pm.handle_event.assert_called_once()
        entry = self.sm.read_one(self.spec)
        stored = json.loads(entry.get(REPLAY_GUARD_FP_FIELD))
        self.assertEqual(stored, {"stamp": self.stamp, "build": self.build})
        self.assertEqual(int(entry.get(REPLAY_GUARD_REVERIFIED_FIELD) or 0), 1)

    def test_second_trigger_after_first_reverify_skips(self):
        """首见复核后再触发（指纹未变）→ 命中沿用，不再派发。"""
        _write_prev_judge_result(Path(self.tmpdir), self.spec, "test-defect")
        self._run_recover()  # 首见：复核 + 记账
        self.pm.handle_event.assert_called_once()
        self.pm.handle_event.reset_mock()
        self._run_recover()  # 二次触发：指纹未变 + 已复核 → 跳过
        self.pm.handle_event.assert_not_called()

    def test_no_test_defect_attribution_dispatches(self):
        """归因无 test-defect（如 product-bug）→ 守卫不命中，照常重派。"""
        _write_prev_judge_result(Path(self.tmpdir), self.spec, "product-bug")
        self._arm_guard(reverified=1)
        self._run_recover()
        self.pm.handle_event.assert_called_once()

    def test_missing_prev_result_dispatches(self):
        """prev-judge-result.json 缺失 → 判据不可得 fail-open，照常重派。"""
        self._arm_guard(reverified=1)
        self._run_recover()
        self.pm.handle_event.assert_called_once()

    def test_build_fingerprint_absent_dispatches(self):
        """产物指纹不可得（无构建清单）→ 无法刻画「未变」，fail-open 放行。"""
        _write_prev_judge_result(Path(self.tmpdir), self.spec, "test-defect")
        os.remove(Path(self.tmpdir) / "requirements.txt")
        self._run_recover()
        self.pm.handle_event.assert_called_once()


class TestParkingExitAnchors(unittest.TestCase):
    """2.2：三退出锚点解除停泊。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_new_impl_run_landing_clears_parking(self):
        _make_parked(self.sm)
        self.sm.update_spec("demo-spec", {"implementer_run": "impl-demo-1"})
        entry = self.sm.read_one("demo-spec")
        self.assertFalse(entry.get(FROZEN_HOLD_FIELD))
        self.assertEqual(entry.get("implementer_run"), "impl-demo-1")
        infos = [str(c) for c in self.logger.info.call_args_list]
        self.assertTrue(any("Parking exit anchor" in c for c in infos))

    def test_verifier_run_landing_clears_parking(self):
        _make_parked(self.sm)
        self.sm.update_spec("demo-spec", {"tester_run": "verify-demo-1"})
        self.assertFalse(self.sm.read_one("demo-spec").get(FROZEN_HOLD_FIELD))

    def test_scenario_revision_writeback_clears_parking(self):
        _make_parked(self.sm)
        self.sm.update_spec(
            "demo-spec", {"_scenario_revision_reverify_pending": True})
        entry = self.sm.read_one("demo-spec")
        self.assertFalse(entry.get(FROZEN_HOLD_FIELD))
        self.assertTrue(entry.get("_scenario_revision_reverify_pending"))

    def test_unrelated_update_keeps_parking(self):
        _make_parked(self.sm)
        self.sm.update_spec("demo-spec", {"error": "普通留痕"})
        entry = self.sm.read_one("demo-spec")
        self.assertTrue(entry.get(FROZEN_HOLD_FIELD))
        self.assertTrue(spec_is_parked(entry))

    def test_unfreeze_parked_skips_preserved_branch(self):
        """停泊态 unfreeze：不走保留分支续做，普通清理 + 重派退出。"""
        _make_parked(self.sm)
        self.sm.update_spec(
            "demo-spec",
            {
                REPLAY_GUARD_FP_FIELD: json.dumps({"stamp": "s", "build": "b"}),
                REPLAY_GUARD_REVERIFIED_FIELD: 1,
            },
        )
        with patch.object(
            self.sm, "_resolve_preserved_branch", return_value=(None, None)
        ) as resume_probe:
            ok = self.sm.unfreeze_spec(
                "demo-spec", status="testing",
                project_root=Path(self.tmpdir), worktree_manager=MagicMock(),
            )
        self.assertTrue(ok)
        resume_probe.assert_not_called()
        entry = self.sm.read_one("demo-spec")
        # 普通解冻清理：停泊位清、无续做标记、status 用调用方给定值
        self.assertFalse(entry.get(FROZEN_HOLD_FIELD))
        self.assertFalse(entry.get("_recovery_resume"))
        self.assertEqual(entry["status"], "testing")
        self.assertIsNone(entry.get("error"))
        # 防重放记账随人工解冻清零（人工处置=新验证 episode）
        self.assertEqual(
            int(entry.get(REPLAY_GUARD_REVERIFIED_FIELD) or 0), 0)
        infos = [str(c) for c in self.logger.info.call_args_list]
        self.assertTrue(any("Unfreeze parking exit" in c for c in infos))

    def test_unfreeze_real_freeze_still_resumes(self):
        """对照组：真冻结终止（frozen 在场）→ 保留分支续做路径保持不变。"""
        _make_parked(self.sm)
        self.sm.update_spec(
            "demo-spec", {"frozen": True, "branch": "fenix/demo-spec-1"})
        with patch.object(
            self.sm, "_resolve_preserved_branch",
            return_value=("fenix/demo-spec-1", "/tmp/wt"),
        ) as resume_probe:
            ok = self.sm.unfreeze_spec(
                "demo-spec", status="testing",
                project_root=Path(self.tmpdir), worktree_manager=MagicMock(),
            )
        self.assertTrue(ok)
        resume_probe.assert_called_once()
        entry = self.sm.read_one("demo-spec")
        self.assertTrue(entry.get("_recovery_resume"))
        self.assertFalse(entry.get(FROZEN_HOLD_FIELD))
        self.assertEqual(entry.get("branch"), "fenix/demo-spec-1")


if __name__ == "__main__":
    unittest.main()
