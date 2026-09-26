"""锁让路退避取得 worktree 与降级计数测试（evo-add-worktree-acquire-backoff）。

背景（proposal）：同 spec:agent_type 锁被并行 run 持有时 create 返回 None，
runner 仅 sleep(5) 一次即判放弃（gave up），一个瞬间事件就把整条新验证流程
炸进降级（日志保留窗内同签名 9 次、跨 7 个日期）。改动：
- 锁活跃导致的 create 失败改短退避等待重试（30s/60s/120s），等持锁方排空，
  重试耗尽才返回既有 gave up 错误，且退避不消耗 attempt 重试额度；
- frozen / _cancelled_hold / status 迁出预期态保持立即让位不进退避；退避
  每轮重探前复查三种人工接管态，等待期间命中即让位、不得照常取得；
- 新验证流程降级 WARNING 附模块级累计「第 N 次降级」。

覆盖（tasks 2.1 四类场景）：
- 退避期内锁释放 → 取得 worktree
- 重试耗尽仍锁活跃 → 既有 gave up 错误
- frozen/_cancelled_hold/status 迁出 → 立即让位（含退避等待期间转入）
- 降级 WARNING 计数递增（跨实例累计）
"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.runner import AgentRunner, _AttemptState
from core.pm_engine import engine as pm_engine_module


class CapturingLogger:
    """记录 warning/info 文本，供断言使用（同 test_dual_dispatch_and_freeze 惯例）。"""

    def __init__(self):
        self.warnings = []
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.infos.append(msg)

    def warning(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.warnings.append(msg)

    def error(self, *a, **k):
        pass


def make_runner(entry, create_results, lock_states):
    """裸装配 runner（同 TestRetryStatusRecheck 的 __new__ 惯例）。

    create_results / lock_states 为按调用次序消费的 side_effect 序列；
    entry 为 state_machine.read_one 恒定返回值（每轮人工接管复查同态）。
    """
    runner = AgentRunner.__new__(AgentRunner)
    runner.worktree_manager = mock.MagicMock()
    runner.worktree_manager.create.side_effect = list(create_results)
    runner.worktree_manager.has_active_lock.side_effect = list(lock_states)
    sm = mock.MagicMock()
    sm.read_one.return_value = entry
    runner.state_machine = sm
    runner.logger = CapturingLogger()
    runner._log_run_metrics = mock.MagicMock()
    return runner


def prepare_wt(runner):
    """以 implementer 首轮 attempt 形参调用 _prepare_worktree。"""
    return runner._prepare_worktree(
        "spec-a", "implementer", 1, "run-1", 3, time.time(), 0, {},
        "p", "m", None, "run-1", _AttemptState(), set())


# ── 场景 1：退避期内锁释放 → 取得 worktree ──────────────────────────


class TestLockReleaseAcquires(unittest.TestCase):
    """spec scenario「持锁方排空后取得 worktree」。"""

    def test_acquire_after_first_backoff_round(self):
        wt = Path("/tmp/fenix-wt-spec-a")
        runner = make_runner(
            {"status": "implementing"},
            create_results=[None, wt],   # 首次撞锁失败，退避一轮后取得
            lock_states=[True],          # 首次失败后锁活跃
        )
        with mock.patch.object(time, "sleep") as sleeper:
            path, why = runner._create_worktree_with_backoff(
                "spec-a", "implementer")
        self.assertEqual(path, wt)
        self.assertIsNone(why)
        # 只等了退避序列第一档，锁释放后下一轮 create 即取得
        sleeper.assert_called_once_with(30)
        self.assertEqual(runner.worktree_manager.create.call_count, 2)
        self.assertTrue(any("acquired after lock wait" in i
                            for i in runner.logger.infos))

    def test_acquire_after_multi_round_wait(self):
        """持锁方多轮不排空：按 30s/60s 序列逐档等待直至取得。"""
        wt = Path("/tmp/fenix-wt-spec-b")
        runner = make_runner(
            {"status": "implementing"},
            create_results=[None, None, wt],
            lock_states=[True, True],
        )
        with mock.patch.object(time, "sleep") as sleeper:
            path, why = runner._create_worktree_with_backoff(
                "spec-a", "implementer")
        self.assertEqual(path, wt)
        self.assertIsNone(why)
        self.assertEqual([c.args[0] for c in sleeper.call_args_list],
                         [30, 60])

    def test_backoff_logs_wait_rounds(self):
        wt = Path("/tmp/fenix-wt-spec-c")
        runner = make_runner(
            {"status": "implementing"},
            create_results=[None, wt],
            lock_states=[True],
        )
        with mock.patch.object(time, "sleep"):
            runner._create_worktree_with_backoff("spec-a", "implementer")
        waits = [w for w in runner.logger.warnings
                 if "blocked by active spec lock" in w]
        self.assertEqual(len(waits), 1)
        self.assertIn("evo-add-worktree-acquire-backoff", waits[0])


# ── 场景 2：重试耗尽仍锁活跃 → 既有 gave up 错误 ────────────────────


class TestBackoffExhausted(unittest.TestCase):
    """spec scenario「重试耗尽仍锁活跃」。"""

    def test_exhaustion_returns_lock_backoff_exhausted(self):
        runner = make_runner(
            {"status": "implementing"},
            create_results=[None, None, None, None],
            # 锁探针调用次数 = 入口 1 次 + 每轮重探失败后各 1 次（共 4 次）
            lock_states=[True, True, True, True],
        )
        with mock.patch.object(time, "sleep") as sleeper:
            path, why = runner._create_worktree_with_backoff(
                "spec-a", "implementer")
        self.assertIsNone(path)
        self.assertEqual(why, "lock-backoff-exhausted")
        # 完整走完 30s/60s/120s 退避序列
        self.assertEqual([c.args[0] for c in sleeper.call_args_list],
                         [30, 60, 120])

    def test_prepare_worktree_returns_gave_up_error(self):
        """退避耗尽经 _prepare_worktree 返回既有 gave up 终态（签名不变）。"""
        runner = make_runner(
            {"status": "implementing"},
            create_results=[None, None, None, None],
            # 锁探针调用次数 = 入口 1 次 + 每轮重探失败后各 1 次（共 4 次）
            lock_states=[True, True, True, True],
        )
        with mock.patch.object(time, "sleep"):
            wt_path, reuse, early, cont = prepare_wt(runner)
        self.assertIsNone(wt_path)
        self.assertFalse(cont)
        self.assertIsNotNone(early)
        self.assertFalse(early.success)
        # 既有错误文案签名保持（test_self_review_midflight 依赖）
        self.assertEqual(
            early.error,
            "Failed to create worktree (gave up: parallel run or manual freeze)")


# ── 场景 3：人工接管态立即让位（含退避等待期间转入）─────────────────


class TestHumanTakeoverImmediateYield(unittest.TestCase):
    """frozen/_cancelled_hold/status 迁出 → 立即让位，不进退避不等待。"""

    def _assert_immediate_yield(self, entry):
        runner = make_runner(entry, create_results=[None], lock_states=[])
        with mock.patch.object(time, "sleep") as sleeper:
            path, why = runner._create_worktree_with_backoff(
                "spec-a", "implementer")
        self.assertIsNone(path)
        self.assertEqual(why, "human-takeover")
        sleeper.assert_not_called()
        # 只探一次 create、未走锁探针——立即让位
        runner.worktree_manager.create.assert_called_once()
        runner.worktree_manager.has_active_lock.assert_not_called()
        return runner

    def test_frozen_yields_immediately(self):
        runner = self._assert_immediate_yield(
            {"frozen": True, "status": "implementing"})
        self.assertTrue(any("manually frozen" in w
                            for w in runner.logger.warnings))

    def test_cancelled_hold_yields_immediately(self):
        self._assert_immediate_yield(
            {"_cancelled_hold": True, "status": "implementing"})

    def test_status_moved_out_yields_immediately(self):
        self._assert_immediate_yield({"status": "blocked"})

    def test_prepare_worktree_frozen_gives_up_without_wait(self):
        """frozen 经 _prepare_worktree 返回 gave up 终态，全程零 sleep。"""
        runner = make_runner({"frozen": True, "status": "implementing"},
                             create_results=[None], lock_states=[])
        with mock.patch.object(time, "sleep") as sleeper:
            _, _, early, cont = prepare_wt(runner)
        self.assertIsNotNone(early)
        self.assertFalse(cont)
        self.assertFalse(early.success)
        self.assertIn("gave up: parallel run or manual freeze", early.error)
        sleeper.assert_not_called()


class TestTakeoverDuringBackoffWait(unittest.TestCase):
    """spec scenario「退避期间人工接管」：每轮重探前复查，命中即让位。"""

    def _runner_with_takeover_at_round2(self, takeover_entry):
        runner = AgentRunner.__new__(AgentRunner)
        wm = mock.MagicMock()
        wm.create.side_effect = [None, None]  # 即便再探会成功，也不得再探
        wm.has_active_lock.side_effect = [True, True]
        runner.worktree_manager = wm
        sm = mock.MagicMock()
        sm.read_one.side_effect = [
            {"status": "implementing"},           # 首次失败后探查：正常
            dict(takeover_entry),                 # 等待后复查：已接管
        ]
        runner.state_machine = sm
        runner.logger = CapturingLogger()
        runner._log_run_metrics = mock.MagicMock()
        return runner

    def test_frozen_during_wait_yields_without_acquire(self):
        runner = self._runner_with_takeover_at_round2(
            {"frozen": True, "status": "blocked"})
        with mock.patch.object(time, "sleep") as sleeper:
            path, why = runner._create_worktree_with_backoff(
                "spec-a", "implementer")
        self.assertIsNone(path)
        self.assertEqual(why, "human-takeover")
        self.assertEqual([c.args[0] for c in sleeper.call_args_list], [30])
        # 复查命中后不得再探 create（不照常取得 worktree）
        self.assertEqual(runner.worktree_manager.create.call_count, 1)
        self.assertTrue(any("yields during lock backoff" in w
                            for w in runner.logger.warnings))

    def test_status_moved_out_during_wait_yields(self):
        """等待期间 status 迁出预期态（含并行 run 完成后的迁移）→ 让位。"""
        runner = self._runner_with_takeover_at_round2({"status": "testing"})
        with mock.patch.object(time, "sleep") as sleeper:
            path, why = runner._create_worktree_with_backoff(
                "spec-a", "implementer")
        self.assertIsNone(path)
        self.assertEqual(why, "human-takeover")
        self.assertEqual([c.args[0] for c in sleeper.call_args_list], [30])
        self.assertEqual(runner.worktree_manager.create.call_count, 1)


# ── 场景 2'：非锁失败保持既有 attempt 层语义 ────────────────────────


class TestNonLockFailurePreservesAttemptRetry(unittest.TestCase):
    """非锁、非人工接管的 create 失败不进退避，保持既有 attempt 重试。"""

    def test_non_lock_failure_do_continue(self):
        runner = make_runner({"status": "implementing"},
                             create_results=[None], lock_states=[False])
        with mock.patch.object(time, "sleep") as sleeper:
            wt_path, reuse, early, cont = prepare_wt(runner)
        self.assertIsNone(early)
        self.assertTrue(cont, "既有语义：attempt < max_retries 时 do_continue 重试")
        sleeper.assert_called_once_with(5)

    def test_lock_released_but_create_still_fails(self):
        """锁已释放但 create 仍失败（git 错误等）→ 不再空转退避。"""
        runner = make_runner({"status": "implementing"},
                             create_results=[None, None],
                             lock_states=[True, False])
        with mock.patch.object(time, "sleep") as sleeper:
            path, why = runner._create_worktree_with_backoff(
                "spec-a", "implementer")
        self.assertIsNone(path)
        self.assertEqual(why, "create-failed")
        self.assertEqual([c.args[0] for c in sleeper.call_args_list], [30])


# ── 场景 4：降级 WARNING 附模块级累计计数 ───────────────────────────


class TestVerifierFallbackCounter(unittest.TestCase):
    """spec scenario「降级可统计」：WARNING 含累计「第 N 次降级」。"""

    def setUp(self):
        self._orig = pm_engine_module._NEW_VERIFIER_FALLBACK_COUNT
        pm_engine_module._NEW_VERIFIER_FALLBACK_COUNT = 0
        self.addCleanup(setattr, pm_engine_module,
                        "_NEW_VERIFIER_FALLBACK_COUNT", self._orig)

    def _engine(self):
        eng = pm_engine_module.PMEngine.__new__(pm_engine_module.PMEngine)
        eng.config = {}
        eng._get_config = mock.MagicMock(return_value=True)
        eng.logger = CapturingLogger()
        eng._run_three_stage_verification = mock.MagicMock(
            side_effect=RuntimeError("worktree gave up"))
        eng._run_legacy_verification = mock.MagicMock()
        return eng

    def _fallback_warnings(self, eng):
        return [w for w in eng.logger.warnings
                if "降级到旧版 verifier" in w]

    def test_warning_counts_incrementally(self):
        eng = self._engine()
        eng._run_verification_pipeline("spec-a")
        eng._run_verification_pipeline("spec-a")
        text = self._fallback_warnings(eng)
        self.assertEqual(len(text), 2)
        self.assertIn("第 1 次降级", text[0])
        self.assertIn("第 2 次降级", text[1])

    def test_counter_survives_instance_rebuild(self):
        """PMEngine 按 run 重建实例，计数仍跨实例累计（实例级恒为 1 的教训）。"""
        eng1 = self._engine()
        eng1._run_verification_pipeline("spec-a")
        eng2 = self._engine()
        eng2._run_verification_pipeline("spec-b")
        text = self._fallback_warnings(eng2)
        self.assertEqual(len(text), 1)
        self.assertIn("第 2 次降级", text[0])
        # 降级后仍走旧版 verifier 兜底（既有降级语义不变）
        eng2._run_legacy_verification.assert_called_once_with("spec-b")

    def test_no_fallback_no_count(self):
        """新流程成功不计数、不降级。"""
        eng = self._engine()
        eng._run_three_stage_verification = mock.MagicMock()
        eng._run_verification_pipeline("spec-a")
        self.assertEqual(pm_engine_module._NEW_VERIFIER_FALLBACK_COUNT, 0)
        eng._run_legacy_verification.assert_not_called()


if __name__ == "__main__":
    unittest.main()
