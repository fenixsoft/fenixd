"""worktree spec 锁 owner 化 / 终态释放 / 陈锁存活清扫 / 降级熔断测试。

（fix-worktree-lock-release-degrade-gate）

背景（2026-10-26 事故）：planner-plan run 被 supersede 后内存 spec 锁
（``spec:agent_type``）不释放，7169s 后重出题派发按 adaptive backoff early
give-up 0.013s 秒败 → 新验证流程静默降级 legacy verifier（仅第 2 次降级
提示）→ legacy 通道 verdict 协议失配，39 分钟验证两轮作废。锁泄漏把「一次性
失败」放大为「验证通道静默劣化」。

覆盖（tasks 1.2 / 2.2 / 3.2）：
- 终态释放：失败终态收尾后同 agent_type 立即可 acquire；owner 不符释放为
  no-op + DEBUG；无 owner（继承载体）不发释放；cancelled 终态同样释放。
- acquire 陈锁存活清扫：①死锁主（末行终态 / superseded 弃置件）→ 清扫放行；
  ②在飞持锁主 → 维持早退不错杀；③记录缺失且锁龄超 early give-up cap →
  清扫放行；④owner=None 登记锁年轻 → 不清扫（超龄才清扫）。
- release_spec_lock owner 语义：不传 owner 维持既有幂等（defer 车道契约）。
- 连续降级熔断：首次放行 + 计数持久化；连续第 2 次 blocked + 升级告警、
  不派发 legacy；解冻清零后重获降级机会。
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.liveness import file_tail_event_type
from core.agent_runner.runner import AgentRunner, _AttemptState
from core.pm_engine import engine as pm_engine_module
from core.state_machine import (
    LEGACY_DEGRADE_LAST_REASON_FIELD,
    LEGACY_DEGRADE_STREAK_FIELD,
    StateMachine,
)
from core.worktree_manager import WorktreeManager


class CapturingLogger:
    """记录 warning/info/debug/error 文本，供断言使用（既有测试惯例）。"""

    def __init__(self):
        self.warnings = []
        self.infos = []
        self.debugs = []
        self.errors = []

    def debug(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.debugs.append(msg)

    def info(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.infos.append(msg)

    def warning(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.warnings.append(msg)

    def error(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.errors.append(msg)


def init_repo(root: Path):
    import subprocess

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True, check=True)

    root.mkdir(parents=True, exist_ok=True)
    git("init", "-q")
    git("config", "user.email", "test@fenix.local")
    git("config", "user.name", "Fenix Test")
    git("config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "[fenix] base")
    git("branch", "-M", "main")


def make_runner(wm, logger):
    """裸装配 runner：仅终态收尾链所需协作件（既有 __new__ 惯例）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.worktree_manager = wm
    runner.logger = logger
    # 终态收尾链的旁路协作件（宿主变更登记 / dev-server 停机）打桩，
    # 本文件关注点仅 spec 锁释放。
    runner._dispatch_host_change_rollback_on_failure = mock.MagicMock()
    runner._v2_stop_for_worktree = mock.MagicMock()
    return runner


def finalize_failure(runner, spec, agent_type, st, attempt=3, max_retries=3,
                     cancelled_flag=False):
    """以终态形态调用 _finalize_failure_keep（attempt 预算耗尽 = 失败终态）。"""
    return runner._finalize_failure_keep(
        spec_name=spec, agent_type=agent_type,
        attempt=attempt, attempt_run_id=f"{st.lock_owner_run_id or 'run'}-x",
        max_retries=max_retries, start_time=time.time(),
        turns=0, usage_info={}, provider_name=None, model=None,
        error="boom", cancelled_flag=cancelled_flag,
        shutdown_interrupted=False, st=st, handed_off=set(),
    )


class LockSweepTestBase(unittest.TestCase):
    """共用夹具：临时 git 仓库 + WorktreeManager + runs 目录。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fenix-lock-release-"))
        self.repo = self.tmp / "repo"
        init_repo(self.repo)
        self.logger = CapturingLogger()
        self.wm = WorktreeManager(
            base_dir=self.tmp / "worktrees",
            project_root=self.repo,
            logger=self.logger,
        )
        self.runs_dir = self.repo / ".fenix" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_run_tail(self, run_id, tail_type):
        """写一个末行为指定事件类型的 run 记录。"""
        f = self.runs_dir / f"{run_id}.jsonl"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "dispatch", "run_id": run_id}) + "\n")
            if tail_type is not None:
                fh.write(json.dumps({"type": tail_type}) + "\n")
        return f


class TestTerminalStateRelease(LockSweepTestBase):
    """任务 1.2：run 终态释放 worktree spec 锁。"""

    def test_terminal_release_allows_immediate_reacquire(self):
        """终态收尾后同 spec 同 agent_type 的新派发可立即 acquire。"""
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-1")
        self.assertIsNotNone(wt)
        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"))

        runner = make_runner(self.wm, self.logger)
        st = _AttemptState()
        st.wt_path = wt
        st.lock_owner_run_id = "run-1"
        finalize_failure(runner, "spec-a", "implementer", st)

        self.assertFalse(self.wm.has_active_lock("spec-a", "implementer"),
                         "失败终态收尾必须释放 spec 锁")
        # 同键立即重派可正常 acquire，不出现 already-active 早退
        wt2 = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNotNone(wt2)
        self.assertNotIn(
            "Worktree already active", " ".join(self.logger.warnings))

    def test_owner_mismatch_release_is_noop(self):
        """owner 不符的释放为 no-op + DEBUG，他人持有的锁不受影响。"""
        self.wm.create("spec-a", "implementer", owner_run_id="run-1")
        # 释放方报了别的 owner：不得误放
        released = self.wm.release_spec_lock(
            "spec-a", "implementer", owner_run_id="run-2")
        self.assertFalse(released)
        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"))
        self.assertIn("owner mismatch", " ".join(self.logger.debugs))
        # 正主释放才生效
        self.assertTrue(self.wm.release_spec_lock(
            "spec-a", "implementer", owner_run_id="run-1"))
        self.assertFalse(self.wm.has_active_lock("spec-a", "implementer"))

    def test_release_without_owner_keeps_idempotent_semantics(self):
        """不传 owner 维持既有幂等语义（code-fix defer 车道零改动契约）。"""
        self.wm.create("spec-a", "implementer", owner_run_id="run-1")
        self.assertTrue(self.wm.release_spec_lock("spec-a", "implementer"))
        self.assertFalse(self.wm.release_spec_lock("spec-a", "implementer"))

    def test_inherited_carrier_without_owner_never_releases(self):
        """本链从未经 create 持锁（继承/repair 载体）终态不发释放——
        不传 owner 的释放会误放他人锁，禁用。"""
        # 他人持有的锁（owner=other-run）
        self.wm._spec_locks.add("spec-a:implementer")
        self.wm._spec_lock_owners["spec-a:implementer"] = "other-run"
        self.wm._lock_since["spec-a:implementer"] = time.time()

        runner = make_runner(self.wm, self.logger)
        st = _AttemptState()
        st.wt_path = None
        st.lock_owner_run_id = None
        finalize_failure(runner, "spec-a", "implementer", st)

        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"),
                        "无 owner 归属的终态不得发释放（他人锁保持）")

    def test_cancelled_terminal_releases_lock(self):
        """取消终态（RUN_TERMINAL_EVENT_TYPES 口径）同样释放。"""
        wt = self.wm.create("spec-b", "verifier", owner_run_id="run-9")
        self.assertIsNotNone(wt)
        runner = make_runner(self.wm, self.logger)
        st = _AttemptState()
        st.wt_path = wt
        st.lock_owner_run_id = "run-9"
        finalize_failure(runner, "spec-b", "verifier", st, cancelled_flag=True)
        self.assertFalse(self.wm.has_active_lock("spec-b", "verifier"))


class TestAcquireStaleLockSweep(LockSweepTestBase):
    """任务 2.1/2.2：acquire 陈锁存活清扫（判据双源）。"""

    def hold(self, spec, agent_type, owner, age=None):
        """手工登记一把在册锁（绕过 git 建树，聚焦清扫判定）。"""
        key = f"{spec}:{agent_type}"
        self.wm._spec_locks.add(key)
        self.wm._lock_since[key] = time.time() - (age or 0)
        if owner is not None:
            self.wm._spec_lock_owners[key] = owner
        return key

    def test_1_dead_owner_terminal_tail_swept_and_acquired(self):
        """①末行终态 → 清扫放行（WARNING 留痕）。"""
        self.write_run_tail("run-1", "error")
        self.hold("spec-a", "implementer", owner="run-1")
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNotNone(wt, "死锁主（末行终态）陈锁必须清扫放行")
        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"))
        self.assertIn("Stale lock swept", " ".join(self.logger.warnings))

    def test_1b_dead_owner_superseded_tail_swept(self):
        """①末行 superseded 弃置件 → 判死清扫（10-26 事故形态）。"""
        self.write_run_tail("run-1", "superseded")
        self.hold("spec-a", "implementer", owner="run-1")
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNotNone(wt, "superseded 弃置件即死，陈锁必须清扫放行")

    def test_2_inflight_owner_keeps_early_exit(self):
        """②记录在飞且末行非死亡判据行 → 维持早退不错杀。"""
        self.write_run_tail("run-1", "dispatch")
        self.hold("spec-a", "implementer", owner="run-1")
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNone(wt, "在飞持锁主必须维持早退")
        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"),
                        "在飞锁不得被清扫")
        self.assertIn("Worktree already active",
                      " ".join(self.logger.warnings))

    def test_3_missing_record_over_cap_swept(self):
        """③记录不存在且锁龄超 early give-up cap → 清扫放行。"""
        self.hold("spec-a", "implementer", owner="run-ghost", age=1300)
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNotNone(wt, "记录缺失 + 锁龄超 cap 必须清扫放行")

    def test_3b_missing_record_young_lock_kept(self):
        """记录不存在但锁龄年轻（构建窗口内）→ 维持早退不误删。"""
        self.hold("spec-a", "implementer", owner="run-ghost", age=10)
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNone(wt)
        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"))

    def test_4_owner_none_young_lock_not_swept(self):
        """④owner=None 登记锁年轻 → 不清扫（缺 owner 退回锁龄判据）。"""
        self.wm._register_spec_locks("spec-a")
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNone(wt)
        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"))

    def test_4b_owner_none_over_cap_swept(self):
        """owner=None 登记锁超龄 → 按锁龄判据清扫放行。"""
        self.wm._register_spec_locks("spec-a")
        for key in ("spec-a:implementer", "spec-a:verifier"):
            self.wm._lock_since[key] = time.time() - 1300
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNotNone(wt, "owner 未知 + 锁龄超 cap 必须清扫放行")

    def test_unreadable_tail_fail_open_keeps_lock(self):
        """末行损坏不可解析 → fail-open 判活，维持早退。"""
        f = self.runs_dir / "run-1.jsonl"
        f.write_text('{"type": "dispatch"}\n{corrupt json\n', encoding="utf-8")
        self.hold("spec-a", "implementer", owner="run-1")
        wt = self.wm.create("spec-a", "implementer", owner_run_id="run-2")
        self.assertIsNone(wt, "末行不可解析必须保守判活")
        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"))


class TestFileTailEventType(unittest.TestCase):
    """liveness.file_tail_event_type 尾读助手（清扫判据①消费端）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fenix-tail-type-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, lines):
        f = self.tmp / "run-x.jsonl"
        f.write_text("".join(json.dumps(l) + "\n" for l in lines),
                     encoding="utf-8")
        return f

    def test_returns_last_line_type(self):
        f = self._write([{"type": "dispatch"}, {"type": "superseded"}])
        self.assertEqual(file_tail_event_type(f), "superseded")

    def test_missing_or_empty_returns_none(self):
        self.assertIsNone(file_tail_event_type(self.tmp / "nope.jsonl"))
        f = self.tmp / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        self.assertIsNone(file_tail_event_type(f))

    def test_corrupt_tail_returns_none(self):
        f = self.tmp / "bad.jsonl"
        f.write_text('{"type": "dispatch"}\n{corrupt\n', encoding="utf-8")
        self.assertIsNone(file_tail_event_type(f))

    def test_large_file_windowed_read(self):
        """超尾读窗口的文件仍能取到末行类型（窗口回退路径）。"""
        f = self.tmp / "big.jsonl"
        with f.open("w", encoding="utf-8") as fh:
            for i in range(2000):
                fh.write(json.dumps({"type": "stream", "i": i,
                                     "pad": "x" * 64}) + "\n")
            fh.write(json.dumps({"type": "result"}) + "\n")
        self.assertEqual(file_tail_event_type(f), "result")


class TestLegacyDegradeGate(unittest.TestCase):
    """任务 3.1/3.2：新验证流程连续降级熔断与计数清零。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fenix-degrade-gate-"))
        self.logger = CapturingLogger()
        self.sm = StateMachine(self.tmp / ".fenix" / "STATE.md", self.logger)
        self.sm.add_spec("spec-a", {"priority": 5})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _engine(self):
        eng = pm_engine_module.PMEngine.__new__(pm_engine_module.PMEngine)
        eng.config = {}
        eng._get_config = mock.MagicMock(return_value=True)
        eng.logger = self.logger
        eng.state_machine = self.sm
        eng._run_three_stage_verification = mock.MagicMock(
            side_effect=RuntimeError("worktree gave up: parallel run"))
        eng._run_legacy_verification = mock.MagicMock()
        eng._send_human_escalation_alert = mock.MagicMock()
        eng._rollback_failed_dispatch = mock.MagicMock()
        return eng

    def _streak(self):
        entry = self.sm.read_one("spec-a") or {}
        return int(entry.get(LEGACY_DEGRADE_STREAK_FIELD, 0) or 0)

    def test_first_degrade_passes_and_counts(self):
        """首次降级维持既有行为：派发 legacy + 计数 +1。"""
        eng = self._engine()
        eng._run_verification_pipeline("spec-a")
        eng._run_legacy_verification.assert_called_once_with("spec-a")
        self.assertEqual(self._streak(), 1)
        entry = self.sm.read_one("spec-a")
        self.assertIn("worktree gave up",
                      str(entry.get(LEGACY_DEGRADE_LAST_REASON_FIELD)))
        self.assertNotEqual(entry.get("status"), "blocked")

    def test_second_consecutive_degrade_breaks_to_blocked(self):
        """连续第 2 次：不派发 legacy，SPEC blocked + 升级告警含原因链。"""
        eng = self._engine()
        eng._run_verification_pipeline("spec-a")  # 第 1 次：放行
        eng._run_verification_pipeline("spec-a")  # 第 2 次：熔断
        self.assertEqual(eng._run_legacy_verification.call_count, 1,
                         "第二次降级 MUST NOT 派发 legacy verifier")
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry.get("status"), "blocked")
        self.assertIn("连续 2 次", str(entry.get("error")))
        # 升级告警文案含两次降级原因链
        eng._send_human_escalation_alert.assert_called_once()
        kwargs = eng._send_human_escalation_alert.call_args.kwargs
        self.assertEqual(kwargs["signal_type"], "verify_env_blocked")
        desc = kwargs["description"] + kwargs["recommended_action"]
        self.assertIn("第 1 次降级", desc)
        self.assertIn("第 2 次降级", desc)

    def test_unfreeze_resets_streak_and_restores_degrade_budget(self):
        """解冻清零后重新获得「首次放行」的完整体验。"""
        eng = self._engine()
        eng._run_verification_pipeline("spec-a")
        eng._run_verification_pipeline("spec-a")  # 熔断 blocked
        self.assertEqual(self.sm.read_one("spec-a")["status"], "blocked")

        self.assertTrue(self.sm.unfreeze_spec("spec-a"))
        self.assertEqual(self._streak(), 0, "人工解冻必须清零降级计数")

        # 解冻后重新获得首次降级机会（派发 legacy 而非直接熔断）
        eng.logger.warnings.clear()
        eng._run_verification_pipeline("spec-a")
        self.assertEqual(eng._run_legacy_verification.call_count, 2)

    def test_verified_reset_fields_clear_streak(self):
        """验证轮成功推进清零点：VERIFIED_RESET_FIELDS 含降级计数双字段。"""
        from core.pm_engine.verification.fastlane import VERIFIED_RESET_FIELDS

        self.assertEqual(VERIFIED_RESET_FIELDS[LEGACY_DEGRADE_STREAK_FIELD], 0)
        self.assertIsNone(
            VERIFIED_RESET_FIELDS[LEGACY_DEGRADE_LAST_REASON_FIELD])

    def test_state_machine_missing_fails_open(self):
        """state_machine 缺失（裸实例）→ fail-open 放行降级（保守侧=现状）。"""
        eng = self._engine()
        del eng.state_machine
        eng._run_verification_pipeline("spec-a")
        eng._run_legacy_verification.assert_called_once_with("spec-a")

    def test_existing_module_counter_still_counts_dispatched_degrades(self):
        """既有「第 N 次降级」模块级计数在放行的降级上仍累计（可观测不变）。"""
        orig = pm_engine_module._NEW_VERIFIER_FALLBACK_COUNT
        pm_engine_module._NEW_VERIFIER_FALLBACK_COUNT = 0
        self.addCleanup(setattr, pm_engine_module,
                        "_NEW_VERIFIER_FALLBACK_COUNT", orig)
        eng = self._engine()
        eng._run_verification_pipeline("spec-a")
        eng._run_verification_pipeline("spec-a")  # 熔断：不派发、不计数
        self.assertEqual(pm_engine_module._NEW_VERIFIER_FALLBACK_COUNT, 1)


if __name__ == "__main__":
    unittest.main()
