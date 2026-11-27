"""evo-lane-probe-steady-noise-governance 回归测试。

覆盖（tasks 3.1/3.2）：

- 3.1 探针稳态边沿发射：首判即时告警 / 同判稳态静默（含 unhealthy 同判但
  reasons/verdicts 漂移须按新边沿发射）/ 每小时心跳恰一条 / 结论变化即时
  告警 / 恢复边沿播报；并断言判定返回值与回落冻结闸拦截语义不回归。
- 3.2 告警生命周期对齐：人工 handled 后同判稳态经 _lane_preflight_consume
  与 arbiter infra 失败路径两登记调用方均不重开、判定变化（形态漂移/env
  变化）重开、AdminStore update 改写路径不被闸拦截。

密闭性纪律：探针 CLI 可达腿一律 patch ``precheck_harness_executable``，
凭据腿由 env 形态驱动（不发真实 CLI 请求、不依赖宿主凭据）；试呼 patch
``lane_preflight.subprocess.run``；告警落盘用 tmp 目录真实 AdminStore；
稳态记忆进程级单例在 setUp/tearDown 强制复位（防同进程测试间串扰）。
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.admin_store import AdminStore
from core.agent_runner import lane_preflight
from core.agent_runner.lane_preflight import (
    FALLBACK_VERDICT_INDETERMINABLE,
    FALLBACK_VERDICT_MISSING,
    FALLBACK_VERDICT_OK,
    LANE_ENV_ALERT_SIGNAL,
    LANE_STEADY_EVENT_EDGE,
    LANE_STEADY_EVENT_HEARTBEAT,
    LANE_STEADY_HEARTBEAT_INTERVAL_S,
    LaneHealth,
    ensure_lane_env_alert,
    observe_lane_conclusion,
    probe_lane_health,
    reset_lane_steady_state,
)

# env 形态（probe_default_chain_credentials 四形态判定口径）：
# - MISSING：有路由无凭据（reasons 文本内嵌 baseurl，可作形态漂移变量）
# - INDETERMINABLE：路由凭据均无痕迹（试呼取证，verdict 词表翻转分支）
# - OK：路由凭据齐备（healthy 边沿）
_MISSING_ENV = {
    "ANTHROPIC_BASE_URL": "https://gw-one.example/v1",
    "ANTHROPIC_AUTH_TOKEN": "",
    "ANTHROPIC_API_KEY": "",
}
_MISSING_ENV_DRIFTED = {
    "ANTHROPIC_BASE_URL": "https://gw-two.example/v1",
    "ANTHROPIC_AUTH_TOKEN": "",
    "ANTHROPIC_API_KEY": "",
}
_INDETERMINABLE_ENV = {
    "ANTHROPIC_BASE_URL": "",
    "ANTHROPIC_AUTH_TOKEN": "",
    "ANTHROPIC_API_KEY": "",
}
_OK_ENV = {
    "ANTHROPIC_BASE_URL": "https://gw-one.example/v1",
    "ANTHROPIC_AUTH_TOKEN": "",
    "ANTHROPIC_API_KEY": "sk-test",
}


class _CollectorLogger:
    """WARNING/INFO 收集器（探针/自检消费点发射断言用）。"""

    def __init__(self):
        self.warnings = []
        self.infos = []

    def warning(self, component, message):
        self.warnings.append((component, message))

    def info(self, component, message):
        self.infos.append((component, message))


def _probe(config=None, env=None, logger=None, monotonic=None):
    """密闭探针：①CLI 可达腿桩顶，②凭据腿由 env 形态驱动。"""
    import contextlib

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.dict(
            "os.environ", env if env is not None else _MISSING_ENV))
        stack.enter_context(patch(
            "core.agent_runner.harness.precheck_harness_executable",
            lambda executable: None,
        ))
        if monotonic is not None:
            stack.enter_context(patch(
                "core.agent_runner.lane_preflight.time.monotonic",
                side_effect=lambda: monotonic[0],
            ))
        return probe_lane_health(config if config is not None else {}, logger)


class _SteadyIsolation(unittest.TestCase):
    """稳态记忆进程级单例复位密闭（防同进程其他测试串扰）。"""

    def setUp(self):
        reset_lane_steady_state()
        lane_preflight.reset_default_chain_trial_cache()

    def tearDown(self):
        reset_lane_steady_state()
        lane_preflight.reset_default_chain_trial_cache()


class TestProbeSteadyEdgeEmission(_SteadyIsolation):
    """3.1：探针稳态边沿发射五分支。"""

    def test_first_judgement_emits_warning_immediately(self):
        """首判（进程首拍）即时发射一条 WARNING，结论标记为边沿。"""
        logger = _CollectorLogger()
        health = _probe(env=_MISSING_ENV, logger=logger)
        self.assertFalse(health.ok)
        self.assertEqual(health.steady_event, LANE_STEADY_EVENT_EDGE)
        self.assertEqual(health.steady_duration_s, 0.0)
        self.assertEqual(len(logger.warnings), 1, "首判 MUST 即时发射恰一条")
        component, message = logger.warnings[0]
        self.assertEqual(component, "agent_runner")
        self.assertIn("车道前置探针 unhealthy", message)

    def test_same_conclusion_steady_beat_is_silent(self):
        """同判稳态拍不再逐拍重打（R1 降噪主缺陷面）。"""
        logger = _CollectorLogger()
        _probe(env=_MISSING_ENV, logger=logger)
        self.assertEqual(len(logger.warnings), 1)
        health2 = _probe(env=_MISSING_ENV, logger=logger)
        self.assertEqual(health2.steady_event, "")
        self.assertEqual(len(logger.warnings), 1, "同判稳态 MUST 静默")

    def test_same_verdict_reasons_drift_is_new_edge(self):
        """unhealthy 同判但 reasons 漂移（baseurl 形态变化）按新边沿发射。"""
        logger = _CollectorLogger()
        _probe(env=_MISSING_ENV, logger=logger)
        health2 = _probe(env=_MISSING_ENV_DRIFTED, logger=logger)
        self.assertEqual(health2.steady_event, LANE_STEADY_EVENT_EDGE)
        self.assertEqual(len(logger.warnings), 2, "形态漂移 MUST 新边沿发射")
        first_msg = logger.warnings[0][1]
        second_msg = logger.warnings[1][1]
        self.assertIn("gw-one.example", first_msg)
        self.assertIn("gw-two.example", second_msg)

    def test_unhealthy_verdict_flip_is_new_edge(self):
        """verdict 词表翻转（missing→indeterminable，试呼取证翻转）新边沿。"""
        logger = _CollectorLogger()
        health1 = _probe(env=_MISSING_ENV, logger=logger)
        self.assertEqual(
            health1.fallback_verdicts.get("repair"), FALLBACK_VERDICT_MISSING)
        with patch(
            "core.agent_runner.lane_preflight.subprocess.run",
            return_value=SimpleNamespace(
                returncode=1, stdout="", stderr="trial boom"),
        ):
            health2 = _probe(env=_INDETERMINABLE_ENV, logger=logger)
        self.assertEqual(
            health2.fallback_verdicts.get("repair"),
            FALLBACK_VERDICT_INDETERMINABLE)
        self.assertEqual(health2.steady_event, LANE_STEADY_EVENT_EDGE)
        self.assertEqual(len(logger.warnings), 2, "verdict 翻转 MUST 新边沿")

    def test_heartbeat_once_per_hour_with_duration(self):
        """同判稳态每小时至多 1 条心跳，携带稳态持续时长；窗口内静默。"""
        logger = _CollectorLogger()
        clock = [1000.0]
        _probe(env=_MISSING_ENV, logger=logger, monotonic=clock)
        self.assertEqual(len(logger.warnings), 1)  # 首判边沿
        clock[0] += LANE_STEADY_HEARTBEAT_INTERVAL_S / 2
        health_mid = _probe(env=_MISSING_ENV, logger=logger, monotonic=clock)
        self.assertEqual(health_mid.steady_event, "")
        self.assertEqual(len(logger.warnings), 1, "心跳窗口内 MUST 静默")
        clock[0] += LANE_STEADY_HEARTBEAT_INTERVAL_S / 2
        health_hb = _probe(env=_MISSING_ENV, logger=logger, monotonic=clock)
        self.assertEqual(
            health_hb.steady_event, LANE_STEADY_EVENT_HEARTBEAT)
        self.assertGreaterEqual(
            health_hb.steady_duration_s, LANE_STEADY_HEARTBEAT_INTERVAL_S)
        self.assertEqual(len(logger.warnings), 2, "每小时心跳恰一条")
        self.assertIn("同判稳态心跳", logger.warnings[1][1])
        self.assertIn("分钟", logger.warnings[1][1])
        clock[0] += 1.0
        _probe(env=_MISSING_ENV, logger=logger, monotonic=clock)
        self.assertEqual(len(logger.warnings), 2, "心跳后窗口内仍静默")

    def test_conclusion_change_to_healthy_is_edge_without_warning(self):
        """结论变化（unhealthy→healthy）即时推进边沿；恢复播报不走探针体
        WARNING（由自检消费点 INFO 恢复留痕承担），再劣化即新边沿重发。"""
        logger = _CollectorLogger()
        _probe(env=_MISSING_ENV, logger=logger)
        self.assertEqual(len(logger.warnings), 1)
        healthy = _probe(env=_OK_ENV, logger=logger)
        self.assertTrue(healthy.ok)
        self.assertEqual(healthy.steady_event, LANE_STEADY_EVENT_EDGE)
        self.assertEqual(len(logger.warnings), 1, "恢复边沿零 WARNING")
        again = _probe(env=_MISSING_ENV, logger=logger)
        self.assertEqual(again.steady_event, LANE_STEADY_EVENT_EDGE)
        self.assertEqual(len(logger.warnings), 2, "再劣化 MUST 新边沿重发")

    def test_probe_return_and_gate_contract_unchanged(self):
        """判定返回值与回落冻结闸消费契约不回归（ok/reasons/verdicts）。"""
        unhealthy = _probe(env=_MISSING_ENV)
        self.assertFalse(unhealthy.ok)
        self.assertTrue(unhealthy.reasons)
        self.assertEqual(
            unhealthy.fallback_verdicts,
            {"arbiter": FALLBACK_VERDICT_MISSING,
             "repair": FALLBACK_VERDICT_MISSING},
        )
        joined = "；".join(unhealthy.reasons)
        self.assertIn("fallback=true", joined)
        self.assertIn("回落冻结闸拦截", joined)
        healthy = _probe(env=_OK_ENV)
        self.assertTrue(healthy.ok)
        self.assertEqual(healthy.reasons, [])
        self.assertEqual(
            healthy.fallback_verdicts,
            {"arbiter": FALLBACK_VERDICT_OK, "repair": FALLBACK_VERDICT_OK},
        )


class TestConsumePointDualEmissionAlignment(_SteadyIsolation):
    """3.1/1.2：自检消费点与探针体双发射点对齐（R3 同拍至多一条）。"""

    def _consume(self, logger, health, ensure_mock=None, stub=None):
        from fenixd import FenixDaemon

        if stub is None:
            stub = SimpleNamespace(
                logger=logger, _lane_preflight_ever_unhealthy=False)
        patches = [
            patch("core.pm_engine.arbiter.get_lane", return_value=None),
            patch(
                "core.agent_runner.lane_preflight.resolve_lane_env_alert",
                return_value=0,
            ),
        ]
        if ensure_mock is not None:
            patches.append(patch(
                "core.agent_runner.lane_preflight.ensure_lane_env_alert",
                ensure_mock,
            ))
        else:
            patches.append(patch(
                "core.agent_runner.lane_preflight.ensure_lane_env_alert",
                MagicMock(),
            ))
        with patches[0], patches[1], patches[2]:
            FenixDaemon._lane_preflight_consume(stub, health, "periodic")
        return stub

    def test_probe_claimed_beat_not_reemitted_by_consume(self):
        """探针体已领取的本拍（边沿），消费点复查得静默——无双行。"""
        logger = _CollectorLogger()
        health = _probe(env=_MISSING_ENV, logger=logger)
        self.assertEqual(len(logger.warnings), 1)  # 探针体边沿发射
        self._consume(logger, health)
        self.assertEqual(
            len(logger.warnings), 1, "消费点 MUST NOT 同拍重复发射")
        steady_event, _ = observe_lane_conclusion(health)
        self.assertEqual(steady_event, "", "复查属同判稳态静默拍")

    def test_unclaimed_beat_emitted_by_consume_once(self):
        """本拍事件未被领取（手工构造 LaneHealth 绕过探针体）→ 消费点按
        边沿发射恰一条，且告警登记生命周期照常执行。"""
        logger = _CollectorLogger()
        ensure_mock = MagicMock()
        health = LaneHealth(
            ok=False, reasons=["凭据缺失形态"], fallback_verdicts={})
        self._consume(logger, health, ensure_mock=ensure_mock)
        self.assertEqual(len(logger.warnings), 1)
        self.assertIn("车道前置自检 unhealthy", logger.warnings[0][1])
        self.assertEqual(ensure_mock.call_count, 1, "告警登记不因降噪缺位")

    def test_recovery_edge_announced_by_consume_info(self):
        """恢复边沿播报（保留并升格既有 ever_unhealthy INFO 恢复留痕）。"""
        logger = _CollectorLogger()
        stub = self._consume(logger, LaneHealth(ok=False, reasons=["x"]))
        self.assertTrue(stub._lane_preflight_ever_unhealthy)
        stub = self._consume(
            logger, LaneHealth(ok=True, reasons=[], fallback_verdicts={}),
            stub=stub)
        self.assertTrue(
            any("车道前置自检 healthy" in msg for _, msg in logger.infos),
            "恢复边沿 MUST INFO 播报")
        self.assertFalse(
            stub._lane_preflight_ever_unhealthy, "恢复后基线复位")


class TestLaneEnvAlertSteadyGate(unittest.TestCase):
    """3.2：告警生命周期对齐三分支（tmp 目录真实 AdminStore）。"""

    def setUp(self):
        reset_lane_steady_state()
        lane_preflight.reset_default_chain_trial_cache()
        self._tmp = tempfile.TemporaryDirectory(prefix="lane-steady-gate-")
        self.proot = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        reset_lane_steady_state()
        lane_preflight.reset_default_chain_trial_cache()

    def _records(self):
        return [
            rec for rec in AdminStore(self.proot, None).read_all()
            if rec.get("signal_type") == LANE_ENV_ALERT_SIGNAL
        ]

    def _handle_all(self):
        """人工处置（dashboard mark_handled 同路径：handled=True+handled_at）。"""
        store = AdminStore(self.proot, None)
        ids = [
            str(rec.get("id")) for rec in self._records()
            if not rec.get("handled") and rec.get("id")
        ]
        for alert_id in ids:
            self.assertTrue(store.mark_handled(alert_id))

    def _ensure(self, reasons=None, origin="preflight"):
        ensure_lane_env_alert(
            self.proot, None,
            reasons=reasons if reasons is not None else ["凭据缺失形态A"],
            origin=origin,
        )

    def _enter_steady(self):
        """进入同判稳态（真实探针拍：env 驱动 missing 形态）。"""
        return _probe(env=_MISSING_ENV)

    def test_handled_same_steady_not_reopened_by_both_callers(self):
        """人工 handled 后同判稳态：自检消费点（startup/periodic）与 arbiter
        infra 失败路径两登记调用方均不重开（一次性终态登记）。"""
        self._enter_steady()
        self._ensure(origin="startup")
        recs = self._records()
        self.assertEqual(len(recs), 1)
        self._handle_all()
        # 同判稳态持续期：自检消费点 periodic 拍登记 → 闸抑制
        self._ensure(origin="periodic")
        self.assertEqual(len(self._records()), 1, "periodic 拍 MUST NOT 重开")
        # arbiter run infra 失败路径：origin/reasons 文本均不同 → 闸仍按
        # episode 连续性抑制（同一稳态期间不因登记调用方而异）
        self._ensure(
            reasons=["MISSING_CREDENTIAL: provider route has no api key"],
            origin="arbiter-run-infra-failed",
        )
        recs = self._records()
        self.assertEqual(len(recs), 1, "arbiter infra 路径 MUST NOT 重开")
        self.assertTrue(recs[0].get("handled"), "原人工终态不被触碰")

    def test_form_drift_reopens_by_new_edge(self):
        """判定变化（环境形态漂移）→ 新边沿 → 闸放行重新登记。"""
        self._enter_steady()
        self._ensure(origin="startup")
        self._handle_all()
        _probe(env=_MISSING_ENV_DRIFTED)  # 形态漂移 → episode 推进
        self._ensure(origin="periodic", reasons=["凭据缺失形态B"])
        recs = self._records()
        self.assertEqual(
            len(recs), 2, "判定改变 MUST 按新边沿重新登记")
        unhandled = [r for r in recs if not r.get("handled")]
        self.assertEqual(len(unhandled), 1)
        self.assertIn("形态B", str(unhandled[0].get("evidence")))

    def test_recovery_then_redegrade_reopens(self):
        """恢复（healthy 边沿）中断稳态后同形态再劣化 → 新 episode 重登记
        （稳态记忆进程级 episode 判据：恢复即中断，不再误抑制新事故）。"""
        self._enter_steady()
        self._ensure(origin="startup")
        self._handle_all()
        _probe(env=_OK_ENV)  # 恢复边沿
        _probe(env=_MISSING_ENV)  # 同形态再劣化 → 新 episode
        self._ensure(origin="periodic")
        recs = self._records()
        self.assertEqual(len(recs), 2, "恢复后再劣化 MUST 重新登记")
        self.assertTrue(
            any(not r.get("handled") for r in recs), "新事故在案未处理")

    def test_update_rewrite_path_not_intercepted_by_gate(self):
        """闸抑制 append 重开的同时 MUST NOT 拦截 update 定位改写路径
        （超龄话术切换照常生效，与 evo-repair-lane-credential-probe-fix
        1.3 正交叠加）。"""
        self._enter_steady()
        self._ensure(origin="startup")
        recs = self._records()
        self.assertEqual(len(recs), 1)
        # 台账条目回拨为超龄（>24h），保持未处理
        store = AdminStore(self.proot, None)

        def backdate(records):
            for rec in records:
                if rec.get("signal_type") == LANE_ENV_ALERT_SIGNAL:
                    from datetime import datetime, timedelta, timezone
                    rec["created"] = (
                        datetime.now(timezone.utc) - timedelta(hours=25)
                    ).isoformat()
            return True

        store.update_records(backdate)
        path = store.alerts_path
        mtime_before = path.stat().st_mtime_ns
        # 同判稳态再登记拍：闸抑制 append（不产生重复条目），但超龄话术
        # 切换（update_records 改写）不被闸拦截
        self._ensure(origin="periodic")
        recs = self._records()
        self.assertEqual(
            len(recs), 1, "同判稳态期间闸抑制 append 重开")
        action = str(recs[0].get("recommended_action"))
        self.assertIn("需人工升级", action, "update 改写路径 MUST 不被拦截")
        self.assertNotIn("无需人工处置", action)
        self.assertGreater(
            path.stat().st_mtime_ns, mtime_before, "改写确已落盘")


if __name__ == "__main__":
    unittest.main()
