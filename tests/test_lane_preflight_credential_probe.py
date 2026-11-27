"""evo-repair-lane-credential-probe-fix 回归测试。

覆盖两类修复：

- 1.2 默认链凭据降级试呼：env 三键全空 → CLI 短请求试呼且 TTL 内仅一次；
  试呼成功映射 healthy（verdict ok）、失败/超时映射 unhealthy（非 ok 且
  evidence/detail 附错误尾部）；试呼缓存为模块级共享单例。
- 1.3 车道环境不可用告警超龄话术：同一 dedup_key 未处理告警创建超 24
  小时 → recommended_action 切换为「需人工升级」；未超时保持原文；重复
  tick 幂等（零写、不计数）。

密闭性纪律：试呼一律 patch ``lane_preflight.subprocess.run``（不真发 CLI
请求、不依赖宿主凭据）；告警落盘用 tmp 目录真实 AdminStore（不出 tmp）。
"""
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.admin_store import AdminStore
from core.agent_runner import lane_preflight
from core.agent_runner.lane_preflight import (
    DEFAULT_CHAIN_TRIAL_TTL_S,
    FALLBACK_VERDICT_INDETERMINABLE,
    FALLBACK_VERDICT_MISSING,
    FALLBACK_VERDICT_OK,
    LANE_ENV_ALERT_SIGNAL,
    LANE_ENV_DEDUP_KEY,
    ensure_lane_env_alert,
    probe_default_chain_credentials,
    probe_lane_health,
)

_EMPTY_ENV = {
    "ANTHROPIC_BASE_URL": "",
    "ANTHROPIC_AUTH_TOKEN": "",
    "ANTHROPIC_API_KEY": "",
}


def _completed(returncode=0, stdout="ok", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class _TrialBase(unittest.TestCase):
    def setUp(self):
        lane_preflight.reset_default_chain_trial_cache()

    def tearDown(self):
        lane_preflight.reset_default_chain_trial_cache()

    def _probe_lane_health_hermetic(self, config=None):
        """①CLI 可达检查密闭（which 探针桩顶），只看②凭据判定面。"""
        with patch(
            "core.agent_runner.harness.precheck_harness_executable",
            lambda executable: None,
        ):
            return probe_lane_health(config if config is not None else {})


class TestDefaultChainCredentialTrial(_TrialBase):
    """1.2：env 三键全空时降级试呼的触发/缓存/映射。"""

    def test_env_empty_triggers_trial_exactly_once_within_ttl(self):
        """三键全空 → 触发试呼；TTL 内多次探针只试呼一次（进程级缓存）。"""
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return _completed(returncode=0, stdout="ok")

        with patch.dict("os.environ", _EMPTY_ENV), \
                patch("core.agent_runner.lane_preflight.subprocess.run",
                      side_effect=fake_run):
            v1, d1 = probe_default_chain_credentials({})
            v2, d2 = probe_default_chain_credentials({})

        self.assertEqual(v1, FALLBACK_VERDICT_OK)
        self.assertEqual(v2, FALLBACK_VERDICT_OK)
        self.assertEqual((v1, d1), (v2, d2))
        self.assertEqual(len(calls), 1, "TTL 内 MUST 仅试呼一次")
        args, kwargs = calls[0]
        self.assertEqual(args[0], "claude")
        self.assertIn("-p", args)
        self.assertEqual(kwargs.get("timeout"), lane_preflight.PROBE_HEALTH_TIMEOUT_S)
        # 设计意图口径：30 分钟 TTL
        self.assertEqual(DEFAULT_CHAIN_TRIAL_TTL_S, 1800.0)

    def test_trial_success_maps_healthy(self):
        """试呼成功 → verdict ok / LaneHealth.ok（合法回落放行）。"""
        with patch.dict("os.environ", _EMPTY_ENV), \
                patch("core.agent_runner.lane_preflight.subprocess.run",
                      return_value=_completed(returncode=0, stdout="ok")):
            verdict, detail = probe_default_chain_credentials({})
            health = self._probe_lane_health_hermetic()
        self.assertEqual(verdict, FALLBACK_VERDICT_OK)
        self.assertIn("试呼成功", detail)
        self.assertTrue(health.ok, health.reasons)
        self.assertEqual(health.fallback_verdicts.get("repair"),
                         FALLBACK_VERDICT_OK)

    def test_trial_failure_maps_unhealthy_with_error_tail(self):
        """试呼失败 → 非 ok / LaneHealth 不健康，evidence 含错误尾部。"""
        stderr_tail = "MISSING_CREDENTIAL: provider route has no api key"
        with patch.dict("os.environ", _EMPTY_ENV), \
                patch("core.agent_runner.lane_preflight.subprocess.run",
                      return_value=_completed(
                          returncode=1, stdout="", stderr=stderr_tail)):
            verdict, detail = probe_default_chain_credentials({})
            health = self._probe_lane_health_hermetic()
        self.assertNotEqual(verdict, FALLBACK_VERDICT_OK)
        self.assertIn("MISSING_CREDENTIAL", detail)
        self.assertFalse(health.ok)
        self.assertEqual(health.fallback_verdicts.get("repair"), verdict)
        joined = "；".join(health.reasons)
        self.assertIn("MISSING_CREDENTIAL", joined)
        self.assertIn("fallback=true", joined)

    def test_trial_timeout_maps_unhealthy(self):
        """试呼超时 → 非 ok 且 detail 标注超时（fail-open 不抛出）。"""
        with patch.dict("os.environ", _EMPTY_ENV), \
                patch("core.agent_runner.lane_preflight.subprocess.run",
                      side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)):
            verdict, detail = probe_default_chain_credentials({})
        self.assertEqual(verdict, FALLBACK_VERDICT_INDETERMINABLE)
        self.assertIn("超时", detail)

    def test_trial_exception_maps_unhealthy_with_error_tail(self):
        """试呼异常（如 CLI 缺失）→ 非 ok 且 detail 含异常尾部。"""
        with patch.dict("os.environ", _EMPTY_ENV), \
                patch("core.agent_runner.lane_preflight.subprocess.run",
                      side_effect=FileNotFoundError("claude: not found on PATH")):
            verdict, detail = probe_default_chain_credentials({})
        self.assertEqual(verdict, FALLBACK_VERDICT_INDETERMINABLE)
        self.assertIn("not found on PATH", detail)

    def test_complete_env_never_trials(self):
        """env 三键可判定（路由齐备/路由无凭据）时默认纯本地、零试呼。"""
        calls = []
        with patch.dict("os.environ", {
                "ANTHROPIC_BASE_URL": "https://gw.example/v1",
                "ANTHROPIC_AUTH_TOKEN": "",
                "ANTHROPIC_API_KEY": ""}, clear=False), \
                patch("core.agent_runner.lane_preflight.subprocess.run",
                      side_effect=lambda *a, **k: calls.append(a)):
            verdict, _ = probe_default_chain_credentials({})
        self.assertEqual(verdict, FALLBACK_VERDICT_MISSING)
        self.assertEqual(calls, [])


class TestLaneEnvAlertAging(_TrialBase):
    """1.3：车道环境不可用告警超 24 小时话术切换。"""

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp(prefix="lane-env-aging-")
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def _records(self):
        return [
            rec for rec in AdminStore(self.proot, None).read_all()
            if rec.get("signal_type") == LANE_ENV_ALERT_SIGNAL
        ]

    def _seed_alert(self, age_hours=0.0):
        created = (
            datetime.now(timezone.utc) - timedelta(hours=age_hours)
        ).isoformat()
        AdminStore(self.proot, None).append({
            "kind": lane_preflight.ESCALATION_KIND,
            "signal_type": LANE_ENV_ALERT_SIGNAL,
            "dedup_key": LANE_ENV_DEDUP_KEY,
            "spec": None,
            "severity": "major",
            "created": created,
            "description": "arbiter/repair 车道环境不可用",
            "evidence": "origin=seed",
            "recommended_action": (
                "修复车道环境后探针转 healthy 即自动恢复自主处置；本告警随"
                "恢复自动关闭，无需人工处置"),
        })

    def test_fresh_alert_keeps_original_wording(self):
        """未超 24 小时：recommended_action 保持原文（含无需人工处置）。"""
        self._seed_alert(age_hours=1.0)
        ensure_lane_env_alert(self.proot, None, reasons=["凭据不可判定"])
        recs = self._records()
        self.assertEqual(len(recs), 1, "单发语义：MUST NOT 新建重复告警")
        action = str(recs[0].get("recommended_action"))
        self.assertIn("无需人工处置", action)
        self.assertNotIn("需人工升级", action)

    def test_alert_older_than_24h_switches_to_manual_escalation(self):
        """超 24 小时：就地改写为「需人工升级」，不新增记录、不计数。"""
        self._seed_alert(age_hours=25.0)
        ensure_lane_env_alert(self.proot, None, reasons=["凭据不可判定"])
        recs = self._records()
        self.assertEqual(len(recs), 1)
        action = str(recs[0].get("recommended_action"))
        self.assertIn("需人工升级", action)
        self.assertIn("repair 回落链凭据不可判定已超 24 小时", action)
        self.assertNotIn("无需人工处置", action)
        self.assertIn("created", recs[0], "就地改写不得重建记录（created 保留）")

    def test_aged_alert_upgrade_is_idempotent(self):
        """超龄后重复 tick：不再改写（零写，mtime 不变）、hit_count 不变。"""
        self._seed_alert(age_hours=30.0)
        ensure_lane_env_alert(self.proot, None, reasons=["凭据不可判定"])
        rec = self._records()[0]
        self.assertIn("需人工升级", str(rec.get("recommended_action")))
        path = AdminStore(self.proot, None).alerts_path  # 主台账文件
        mtime_before = path.stat().st_mtime_ns
        ensure_lane_env_alert(self.proot, None, reasons=["凭据不可判定"])
        rec2 = self._records()[0]
        self.assertEqual(rec2.get("recommended_action"),
                         rec.get("recommended_action"))
        self.assertEqual(rec2.get("hit_count"), rec.get("hit_count"))
        self.assertEqual(path.stat().st_mtime_ns, mtime_before,
                         "已升级条目重复 tick MUST 零写")

    def test_handled_aged_alert_not_reused(self):
        """已人工处理的超龄告警不属在案未处理：MUST NOT 被改写。"""
        self._seed_alert(age_hours=30.0)
        store = AdminStore(self.proot, None)

        def mark(records):
            for rec in records:
                if rec.get("signal_type") == LANE_ENV_ALERT_SIGNAL:
                    rec["handled"] = True
            return True

        store.update_records(mark)
        ensure_lane_env_alert(self.proot, None, reasons=["凭据不可判定"])
        recs = self._records()
        # 已处理条目不抑制新 unhealthy 告警落地（admin_store is_inflight 同口径）
        self.assertEqual(len(recs), 2)
        self.assertNotIn("需人工升级",
                         str(recs[0].get("recommended_action")))
        self.assertNotIn("需人工升级",
                         str(recs[1].get("recommended_action")))


if __name__ == "__main__":
    unittest.main()
