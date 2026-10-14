"""verifier 进程级基础设施死亡分流（evo-add-verifier-infra-death-triage）回归测试。

覆盖 tasks.md 3.1 / 3.2 验收：

3.1 ENOENT/启动期秒死形态全链：
- 0 轮 0 token 死亡不判 bug-found（不原地打回、不消耗实现预算）；
- 限次内廉价重派且不计 env 冻结轮、不呼叫 admin；
- 超限转 blocked+frozen+admin（freeze_for_human 暂挂）；
- 重派成功后台账清零（与验证 PASS 同点，无平行台账）；
- runner 终局失败结果 turns_used 回填后口径一致。

3.2 不回归面：
- 有 assistant 轮次且存活达秒挂阈值的真实验证失败仍走既有 bug-found 路径；
- verified 方向防伪闸门不受影响（闸门在分流上游，命中即零动作）；
- env 阻塞后置分类语义不变（错误词表不扩列，unknown 仍按 product 保守处置）；
- new-flow planner 死亡 raise → 降级 legacy 语义与双路径失败守卫不回归
  （core/verify_engine/engine.py:2825-2829 精神保留）。
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.result_gate import AgentRunResult
from core.agent_runner.runner import AgentRunner
from core.state_machine import (
    StateMachine,
    ENV_BLOCK_ROUNDS_FIELD,
    VERIFY_INFRA_RETRY_STREAK_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
)
from core.pm_engine.verification import VerdictReadResult
from core.pm_engine.verification.infra_classify import (
    VERIFIER_DEATH_SURVIVAL_THRESHOLD_SECONDS,
    annotate_death_fingerprint,
    is_verifier_process_death,
)

_ENOENT_ERR = (
    "All 3 attempts failed. Last error: [Errno 2] No such file or "
    "directory: '/tmp/.fenix-patch-xyz': posix_spawn failed"
)


def _death_result(spec="demo-spec", epoch=1, error=_ENOENT_ERR,
                  turns=0, duration=8.0):
    """verifier 终局失败结果替身（0 轮秒死形态，对齐 _exhausted_result 回填后形状）。"""
    return SimpleNamespace(
        success=False, error=error,
        run_id=f"verify-{spec}-{epoch}-a1",
        cancelled=False, frozen_terminated=False,
        turns_used=turns, duration_seconds=duration,
    )


class _LegacyTriageBase(unittest.TestCase):
    """公共夹具：testing 态 spec + PMEngine + 重派/告警捕获桩。"""

    SPEC = "demo-spec"

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(
            Path(self.tmpdir) / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        # human 升级告警捕获桩（context.escalation_notifier 经此转发）
        self.engine._send_human_escalation_alert = MagicMock()
        # 重派触发器捕获桩（防真实定时器；断言「限内重派已排程」）
        self.schedule_mock = MagicMock()
        self.engine._verification._context.schedule_infra_retry_redispatch = (
            self.schedule_mock
        )
        self.verify_dir = (
            Path(self.tmpdir) / ".fenix" / "verify-progress" / self.SPEC)
        self.verify_dir.mkdir(parents=True, exist_ok=True)
        self.fail_history_path = self.verify_dir / "fail_history.json"
        self.invoke_path = (
            Path(self.tmpdir) / ".fenix" / "admin_invoke_request.json")
        self._make_testing_spec()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_testing_spec(self, name=None):
        name = name or self.SPEC
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")

    def _run_legacy_with(self, verifier_result):
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=verifier_result)
        self.engine._run_legacy_verification(self.SPEC)


class TestProcessDeathTriageFullChain(_LegacyTriageBase):
    """tasks 3.1：ENOENT/启动期秒死形态——分流→限次重派→超限暂挂→成功清零。"""

    def test_enoent_death_not_bugfound_and_redispatches(self):
        """0 轮秒死：不判 bug-found、不计 env 冻结轮、廉价重派已排程、infra 记账。"""
        self.sm.update_spec(self.SPEC, {"_verify_fail_rounds": 2})
        self._run_legacy_with(_death_result(epoch=1))

        entry = self.sm.read_one(self.SPEC)
        # 不判 bug-found：保持 testing，不消耗实现尝试预算（fail_rounds 不动）
        self.assertEqual(entry["status"], "testing")
        self.assertNotEqual(entry["status"], "bug-found")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 2)
        self.engine._on_spec_bug_found.assert_not_called()
        # 限次内廉价重派：经既有 verifier 派发入口排程，不计 env 冻结轮
        self.schedule_mock.assert_called_once_with(self.SPEC)
        self.assertEqual(int(entry.get(ENV_BLOCK_ROUNDS_FIELD, 0) or 0), 0)
        self.assertIs(entry.get("frozen"), False)
        # 不呼叫 admin：无 invoke 请求文件、无 human 升级告警
        self.assertFalse(self.invoke_path.exists())
        self.engine._send_human_escalation_alert.assert_not_called()
        # infra 记账单点入账：专用计数 +1、观测账 +1、失败台账含 infra 条目
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 1)
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0)), 1)
        history = json.loads(self.fail_history_path.read_text(encoding="utf-8"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["failure_class"], "infra")
        # 错误指纹仅辅助标注：ENOENT 指纹入台账 reason 留痕（run_id 字段）
        self.assertEqual(history[0]["run_id"], "verify-demo-spec-1-a1")

    def test_zero_turns_long_run_is_death(self):
        """存活很长但终局 0 assistant 轮＝全无产出，同样命中死亡分流。"""
        self._run_legacy_with(_death_result(epoch=2, turns=0, duration=600.0))
        entry = self.sm.read_one(self.SPEC)
        self.assertEqual(entry["status"], "testing")
        self.schedule_mock.assert_called_once_with(self.SPEC)

    def test_short_survival_with_turns_is_death(self):
        """存活上界低于秒挂阈值即全部 attempt 秒挂（turns 为不可观测口径亦命中）。"""
        self._run_legacy_with(
            _death_result(epoch=3, turns=0, duration=8.0))
        entry = self.sm.read_one(self.SPEC)
        self.assertEqual(entry["status"], "testing")
        self.schedule_mock.assert_called_once_with(self.SPEC)

    def test_death_over_budget_freezes_for_human(self):
        """超限（专用计数达缺省 2 次预算）：blocked+frozen+admin 信号，不 bug-found。"""
        self.sm.update_spec(
            self.SPEC, {VERIFY_INFRA_RETRY_STREAK_FIELD: 2})
        self._run_legacy_with(_death_result(epoch=4))

        entry = self.sm.read_one(self.SPEC)
        self.assertEqual(entry["status"], "blocked")
        self.assertIs(entry.get("frozen"), True)
        self.assertIn("进程级基础设施死亡", str(entry.get("error")))
        # 不 bug-found、不重派、不原地打回
        self.assertNotEqual(entry["status"], "bug-found")
        self.schedule_mock.assert_not_called()
        self.engine._on_spec_bug_found.assert_not_called()
        # admin 信号（human 升级告警）已发，severity=critical
        self.engine._send_human_escalation_alert.assert_called_once()
        kwargs = self.engine._send_human_escalation_alert.call_args.kwargs
        self.assertEqual(kwargs["signal_type"], "verifier_infra_death")
        self.assertEqual(kwargs["severity"], "critical")
        # 专用计数已随决议 +1（单点入账，无二次记账）
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 3)

    def test_redispatch_success_clears_streak(self):
        """重派后验证 PASS：专用台账清零（与验证 PASS 同点，无平行台账）。"""
        self._run_legacy_with(_death_result(epoch=5))
        entry = self.sm.read_one(self.SPEC)
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 1)

        # ── 重派轮：verifier 正常收工且裁决 verified ──
        epoch = int(time.time())
        primary = self.verify_dir / ".fenix-run-result.json"
        primary.write_text(json.dumps({
            "spec": self.SPEC, "status": "verified",
        }, ensure_ascii=False), encoding="utf-8")
        import os
        os.utime(str(primary), (time.time(), time.time()))
        v = self.engine._verification
        v._read_verdict = MagicMock(
            return_value=VerdictReadResult.success("verified"))
        v._check_verification_gate = MagicMock(return_value=None)
        v._ensure_verification_report = MagicMock(return_value=None)
        v._env_whitewash_gate = MagicMock(return_value=True)
        v._handle_env_blocked_inconclusive = MagicMock(return_value=False)
        v._handle_env_exemption_handshake = MagicMock(return_value=False)
        v._record_verdict_adoption = MagicMock()
        v._render_scenario_change_section_to_report = MagicMock()
        self._run_legacy_with(SimpleNamespace(
            success=True, error=None,
            run_id=f"verify-{self.SPEC}-{epoch}-a1",
            cancelled=False, turns_used=12, duration_seconds=600.0,
        ))

        entry = self.sm.read_one(self.SPEC)
        self.assertEqual(entry["status"], "verified")
        # 台账清零点与验证 PASS 同点：后续 infra 死亡重新计数
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 0)
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0)), 0)


class TestTurnsUsedBackfill(unittest.TestCase):
    """tasks 3.1：runner 终局失败结果 turns_used 回填后口径一致。"""

    @staticmethod
    def _runner_stub():
        runner = AgentRunner.__new__(AgentRunner)
        runner._cancel_clear = MagicMock()
        runner._log_run_metrics = MagicMock()
        runner._accumulate_token_usage = MagicMock()
        runner._record_verify_progress_tokens = MagicMock()
        return runner

    def test_exhausted_result_backfills_real_turns(self):
        """全重试耗尽终态：turns_used=真实累计轮数（原恒缺省 0）。"""
        res = AgentRunner._exhausted_result(
            self._runner_stub(), "demo-spec", "verifier",
            "verify-demo-spec-1", 3, time.time(),
            error="boom", turns=7,
        )
        self.assertFalse(res.success)
        self.assertEqual(res.turns_used, 7)

    def test_exhausted_result_zero_turns_remains_zero(self):
        """全 attempt 秒挂（0 轮）：turns_used=0——消费层据此判进程级死亡。"""
        res = AgentRunner._exhausted_result(
            self._runner_stub(), "demo-spec", "verifier",
            "verify-demo-spec-2", 3, time.time(),
            error="boom", turns=0,
        )
        self.assertEqual(res.turns_used, 0)

    def test_structured_attribution_passthrough(self):
        """verifier 车道终态透传 stderr_tail/exit_code（对齐 spec-review 回填）。"""
        res = AgentRunner._exhausted_result(
            self._runner_stub(), "demo-spec", "verifier",
            "verify-demo-spec-3", 3, time.time(),
            error="boom", turns=0, stderr_tail="tail-line", exit_code=2,
        )
        self.assertEqual(res.stderr_tail, "tail-line")
        self.assertEqual(res.exit_code, 2)
        # 缺省不传保持 None（既有构造点零感知）
        res2 = AgentRunner._exhausted_result(
            self._runner_stub(), "demo-spec", "verifier",
            "verify-demo-spec-4", 3, time.time(), error="boom", turns=1,
        )
        self.assertIsNone(res2.stderr_tail)
        self.assertIsNone(res2.exit_code)

    def test_agent_run_result_defaults_unchanged(self):
        """AgentRunResult 既有构造点（不传新参）行为不变。"""
        res = AgentRunResult("r1", "s", "verifier", False, 1.0)
        self.assertEqual(res.turns_used, 0)
        self.assertIsNone(res.stderr_tail)
        self.assertIsNone(res.exit_code)


class TestDeathPredicateUnit(unittest.TestCase):
    """进程级死亡判定纯函数单测（命中条件 / 保守缺省 / 指纹标注）。"""

    def test_zero_turns_hits(self):
        self.assertTrue(is_verifier_process_death(
            SimpleNamespace(turns_used=0, duration_seconds=600.0)))

    def test_short_survival_hits(self):
        self.assertTrue(is_verifier_process_death(
            SimpleNamespace(turns_used=4,
                            duration_seconds=VERIFIER_DEATH_SURVIVAL_THRESHOLD_SECONDS - 1)))

    def test_real_failure_does_not_hit(self):
        self.assertFalse(is_verifier_process_death(
            SimpleNamespace(turns_used=7, duration_seconds=480.0)))

    def test_missing_or_dirty_calibers_conservative(self):
        # 缺属性 / None / 脏值：口径未知不命中（回落既有归因链）
        self.assertFalse(is_verifier_process_death(SimpleNamespace()))
        self.assertFalse(is_verifier_process_death(
            SimpleNamespace(turns_used=None, duration_seconds=None)))
        self.assertFalse(is_verifier_process_death(
            SimpleNamespace(turns_used="many", duration_seconds="8s")))
        self.assertFalse(is_verifier_process_death(None))

    def test_fingerprint_annotation_only(self):
        self.assertEqual(
            annotate_death_fingerprint("[Errno 2] No such file or directory: 'x'"),
            "startup-error-fingerprint:no such file")
        self.assertEqual(
            annotate_death_fingerprint("provider circuit open"),
            "process-death:no-fingerprint")


class TestNonRegression(_LegacyTriageBase):
    """tasks 3.2：不回归面——真实验证失败/verified 闸门/env 后置分类语义不变。"""

    def test_real_failure_with_turns_still_bug_found(self):
        """有 assistant 轮次且存活达秒挂阈值的进程失败仍走既有 bug-found 路径。"""
        self._run_legacy_with(
            _death_result(epoch=6, error="real verifier crash",
                          turns=7, duration=480.0))
        entry = self.sm.read_one(self.SPEC)
        self.assertEqual(entry["status"], "bug-found")
        self.assertIn("Verifier agent failed", str(entry.get("error")))
        # 不走死亡分流：无重派、无 infra 记账
        self.schedule_mock.assert_not_called()
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 0)
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0)), 0)

    def test_verified_gate_upstream_of_triage(self):
        """verified 放行门在分流上游：门命中即零动作（不重派/不冻结/不记账）。"""
        self.engine._verification._verified_gate_refuses = MagicMock(
            return_value=True)
        self.sm.update_spec(self.SPEC, {VERIFY_INFRA_RETRY_STREAK_FIELD: 2})
        self._run_legacy_with(_death_result(epoch=7))

        entry = self.sm.read_one(self.SPEC)
        self.assertEqual(entry["status"], "testing")
        self.schedule_mock.assert_not_called()
        self.engine._send_human_escalation_alert.assert_not_called()
        # 防伪闸门优先：专用计数不被死亡分流推进
        self.assertEqual(int(entry.get(VERIFY_INFRA_RETRY_STREAK_FIELD, 0)), 2)
        self.assertNotIn(VERIFY_INFRA_ROUNDS_FIELD, entry)

    def test_env_vocabulary_not_extended(self):
        """非目标「不做错误词表扩列」：ENOENT 文本经归因入口仍判 unknown。"""
        failure_class = self.engine._verification.enrich_failure_class(
            self.SPEC, error_text=_ENOENT_ERR)
        self.assertEqual(failure_class, "unknown")


class TestNewFlowDegradeSemantics(_LegacyTriageBase):
    """tasks 2.3：new-flow planner 死亡 raise → 降级 legacy 语义与双路径守卫不回归。"""

    def _run_pipeline(self):
        self.engine._run_verification_pipeline(self.SPEC)

    def test_planner_death_still_degrades_to_legacy(self):
        """新流程 planner 死亡 raise → 降级 legacy（既有重试语义不动）。"""
        degrade = MagicMock()
        self.engine._run_three_stage_verification = MagicMock(
            side_effect=RuntimeError("Planner plan 失败: planner died instantly"))
        self.engine._run_legacy_verification = degrade
        self._run_pipeline()
        degrade.assert_called_once_with(self.SPEC)

    def test_dual_path_failure_guard_no_bugfound(self):
        """双路径都失败：_rollback_failed_dispatch 收口，不 bug-found
        （core/verify_engine/engine.py:2825-2829 守卫语义保留）。"""
        self.engine._run_three_stage_verification = MagicMock(
            side_effect=RuntimeError("planner died"))
        self.engine._run_legacy_verification = MagicMock(
            side_effect=RuntimeError("legacy verifier died too"))
        rollback = MagicMock()
        self.engine._rollback_failed_dispatch = rollback
        self._run_pipeline()
        rollback.assert_called_once()
        self.assertEqual(rollback.call_args.args[0], self.SPEC)
        self.assertEqual(rollback.call_args.args[1], "verifier")
        entry = self.sm.read_one(self.SPEC)
        self.assertEqual(entry["status"], "testing")
        self.engine._on_spec_bug_found.assert_not_called()
        # 双路径异常守卫路径不经死亡分流记账（legacy 未真正消费结果对象）
        self.schedule_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
