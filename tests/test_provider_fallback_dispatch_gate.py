"""provider-fallback-dispatch-gate 回归测试（五场景 + 回归保护断言）。

能力一（回落角色预检与派发冻结）：probe② 回落角色默认链凭据可判定
检查、_run_agent 共享 spawn 前置段回落首派发冻结、单条告警（按角色去
重）、热重载解冻、显式放行键兜底。能力二（版本白名单全车道）：版本
前置检查挂共享前置段覆盖直调车道、adapter 级缓存复用。

密闭性纪律（同 test_arbiter_lane_resilience）：闸级测试探针结论一律
预种/patch（patch lane_preflight.probe_lane_health），MUST NOT 依赖宿主
CLI/凭据环境；探针级测试 os.environ 经 monkeypatch 控制；fenixd 接线
用例真实 AdminStore 落盘不出 tmp。
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.agent_runner import AgentRunner
from core.agent_runner.harness import HarnessHealthError
from core.agent_runner.lane_preflight import (
    FALLBACK_VERDICT_INDETERMINABLE,
    FALLBACK_VERDICT_MISSING,
    FALLBACK_VERDICT_OK,
    LANE_INFRA_FINGERPRINTS,
    PROVIDER_FALLBACK_ALERT_SIGNAL,
    LaneHealth,
    ensure_provider_fallback_alert,
    probe_default_chain_credentials,
    probe_lane_health,
    provider_fallback_dedup_key,
    resolve_provider_fallback_alert,
)
from core.admin_store import AdminStore
from core.config import ConfigLoader

# dispatch 族车道（3.2 回归保护基准：DNS 连通预检白名单排除不扩）
_DISPATCH_PROBE_LANES_BASELINE = frozenset({
    "evolution", "code-review", "code-fix", "administrator", "self-review",
    "arbiter",
})

_EXPLICIT_CHAIN_CONFIG = {
    "llm": {"providers": [{
        "name": "p1", "baseurl": "https://gw.example/v1",
        "apikey": "sk-test", "model": "m1",
    }]},
    "agents": {"models": {"repair": {"provider": "p1"}}},
}


def _seed_health(verdicts):
    """预种探针结论（密闭：verdicts 为 role→verdict 映射）。"""
    reasons = [
        f"{role} 回落 harness 默认链凭据{'缺失' if v == FALLBACK_VERDICT_MISSING else '不可判定'}"
        f"（fallback=true）——首派发将被回落冻结闸拦截"
        for role, v in verdicts.items() if v != FALLBACK_VERDICT_OK
    ]
    return LaneHealth(ok=not reasons, reasons=reasons,
                      fallback_verdicts=dict(verdicts))


class _RunnerBase(unittest.TestCase):
    """AgentRunner 最小装配（同 test_harness_config 基线形态）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="fb-gate-")
        self.proot = Path(self.tmpdir)
        wm = MagicMock()
        sm = MagicMock()
        sm.read_one.return_value = None
        self.runner = AgentRunner({}, wm, sm, self.proot, MagicMock())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _patch_probe(self, verdicts):
        """预种闸消费的探针结论（lane_preflight 模块内单源引用）。"""
        health = _seed_health(verdicts)
        return patch(
            "core.agent_runner.lane_preflight.probe_lane_health",
            return_value=health,
        )

    def _alert_records(self):
        store = AdminStore(self.proot, None)
        return [
            rec for rec in store.read_all()
            if rec.get("signal_type") == PROVIDER_FALLBACK_ALERT_SIGNAL
        ]


class TestFallbackDispatchGate(_RunnerBase):
    """场景一/二：回落角色首派发被拦截且告警单条；显式链角色不受影响。"""

    def test_fallback_role_first_dispatch_blocked_with_single_alert(self):
        """repair 回落默认链凭据缺失 → 闸拦截 + 单条告警（含角色与回落链）。

        后续命中 bump 既有条目 hit_count 而非新建（spec：更新该告警计数
        而非新建）。
        """
        with self._patch_probe({"repair": FALLBACK_VERDICT_MISSING,
                                "arbiter": FALLBACK_VERDICT_OK}):
            reject = self.runner._provider_fallback_dispatch_gate("repair")
        self.assertIsNotNone(reject)
        self.assertIn("[provider-fallback-frozen]", reject)
        self.assertIn("repair", reject)
        # 拦截不建 runs 产物（首派发零产物零进程——消费点在 _run_agent 开头）
        self.assertFalse((self.proot / ".fenix" / "runs").exists())
        # 单条告警落地：含角色名与回落链描述
        records = self._alert_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].get("dedup_key"), provider_fallback_dedup_key("repair"))
        self.assertIn("repair", str(records[0].get("description")))
        self.assertIn("fallback_chain", str(records[0].get("evidence")))
        # 后续命中：计数 bump、仍单条
        with self._patch_probe({"repair": FALLBACK_VERDICT_MISSING}):
            self.runner._provider_fallback_dispatch_gate("repair")
        records = self._alert_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].get("hit_count"), 2)

    def test_run_agent_consumes_gate_and_raises_without_run_file(self):
        """_run_agent 开头消费闸：拦截经 RuntimeError 走既有失败语义。"""
        self.runner._provider_fallback_dispatch_gate = MagicMock(
            return_value="[provider-fallback-frozen] repair 首派发已冻结拦截")
        with self.assertRaises(RuntimeError) as ctx:
            self.runner._run_agent("prompt", self.proot, "repair-run-1",
                                   spec_name="s", agent_type="repair")
        self.assertIn("[provider-fallback-frozen]", str(ctx.exception))
        # 拦截点先于产物落盘：run jsonl 不存在
        self.assertFalse(
            (self.proot / ".fenix" / "runs" / "repair-run-1.jsonl").exists())

    def test_explicit_chain_role_bypasses_gate(self):
        """显式链角色旁路：闸放行且不落告警（显式链不误伤）。"""
        self.runner.config = dict(_EXPLICIT_CHAIN_CONFIG)
        # 链配置在场时闸不消费探针（预种坏结论也不影响放行）
        with self._patch_probe({"repair": FALLBACK_VERDICT_MISSING}):
            reject = self.runner._provider_fallback_dispatch_gate("repair")
        self.assertIsNone(reject)
        self.assertEqual(self._alert_records(), [])
        self.assertEqual(
            ConfigLoader.get_agent_model_assignment(
                _EXPLICIT_CHAIN_CONFIG, "repair")[0][0]["name"], "p1")

    def test_non_probe_role_unaffected(self):
        """探针角色集外的角色（如 impl）不受回落冻结影响。"""
        with self._patch_probe({"repair": FALLBACK_VERDICT_MISSING,
                                "arbiter": FALLBACK_VERDICT_MISSING}):
            self.assertIsNone(
                self.runner._provider_fallback_dispatch_gate("impl"))
            self.assertIsNone(
                self.runner._provider_fallback_dispatch_gate(None))


class TestThawAndAllowKey(_RunnerBase):
    """场景三/五：热重载凭据可用后解冻；放行配置项旁路。"""

    def test_hot_reload_credentials_available_unfreezes(self):
        """TTL 重探自然感知：凭据变为可用后闸放行且在案告警自动关闭。"""
        with self._patch_probe({"arbiter": FALLBACK_VERDICT_MISSING}):
            self.assertIsNotNone(
                self.runner._provider_fallback_dispatch_gate("arbiter"))
        self.assertEqual(len(self._alert_records()), 1)
        # TTL 内复用缓存结论：配置改好（预种 ok）仍拦截（缓存语义不变）
        with self._patch_probe({"arbiter": FALLBACK_VERDICT_OK}):
            self.assertIsNotNone(
                self.runner._provider_fallback_dispatch_gate("arbiter"))
        # TTL 重探（invalidate 模拟过期）：verdict ok → 放行 + 告警自动关闭
        cache = self.runner.__dict__["_provider_fallback_gate_cache"]
        cache.invalidate()
        with self._patch_probe({"arbiter": FALLBACK_VERDICT_OK}):
            self.assertIsNone(
                self.runner._provider_fallback_dispatch_gate("arbiter"))
        records = self._alert_records()
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].get("handled"))
        self.assertIn("auto-resolve", str(records[0].get("handled_by") or ""))

    def test_allow_key_bypasses_freeze(self):
        """放行配置项兜底：闸对回落派发放行（design Risks 误判兜底）。"""
        self.runner.config = {"agents": {
            "allow_harness_default_fallback": True}}
        with self._patch_probe({"repair": FALLBACK_VERDICT_INDETERMINABLE}):
            self.assertIsNone(
                self.runner._provider_fallback_dispatch_gate("repair"))
        self.assertEqual(self._alert_records(), [])
        self.assertTrue(ConfigLoader.get(
            self.runner.config, "agents.allow_harness_default_fallback", False))

    def test_allow_key_resolves_existing_alert(self):
        """放行键打开同时自动关闭在案告警（解冻对称语义）。"""
        ensure_provider_fallback_alert(
            self.proot, None, role="repair", chain_desc="d", verdict="missing")
        self.assertEqual(len(self._alert_records()), 1)
        self.runner.config = {"agents": {
            "allow_harness_default_fallback": True}}
        with self._patch_probe({"repair": FALLBACK_VERDICT_INDETERMINABLE}):
            self.assertIsNone(
                self.runner._provider_fallback_dispatch_gate("repair"))
        self.assertTrue(self._alert_records()[0].get("handled"))


class TestVersionGateDirectLanes(_RunnerBase):
    """场景四：直调车道版本漂移被拦截；adapter 级缓存复用不起子进程。"""

    def _dsh_adapter(self, calls):
        adapter = MagicMock()
        adapter.name = "dsh"

        def _check(**kwargs):
            calls.append(kwargs)
            raise HarnessHealthError("dsh 版本超白名单")
        adapter.check_health = _check
        return adapter

    def test_direct_lane_version_drift_blocked_before_spawn(self):
        """spec-review 直调车道：版本漂移在 spawn 前拦截（Popen 未调）。"""
        calls = []
        adapter = self._dsh_adapter(calls)
        with patch("core.agent_runner.runner.get_current_adapter",
                   return_value=adapter), \
                patch("subprocess.Popen") as popen:
            with self.assertRaises(RuntimeError) as ctx:
                self.runner._run_agent("prompt", self.proot, "sr-run-1",
                                       spec_name="spec-x",
                                       agent_type="spec-review")
        self.assertIn("[harness-health-gate]", str(ctx.exception))
        self.assertIn("dsh 版本超白名单", str(ctx.exception))
        popen.assert_not_called()
        # adapter 级缓存：二次 spawn 复用失败结论，不再起探测子进程
        with patch("core.agent_runner.runner.get_current_adapter",
                   return_value=adapter):
            with self.assertRaises(RuntimeError) as ctx2:
                self.runner._run_agent("prompt", self.proot, "sr-run-2",
                                       spec_name="spec-x",
                                       agent_type="spec-review")
        self.assertIn("[harness-health-gate]", str(ctx2.exception))
        self.assertEqual(len(calls), 1)

    def test_adapter_without_check_health_passes_through(self):
        """claude 通道无 check_health 成员：零动作放行（duck-typing 同口径）。"""
        adapter = MagicMock()
        adapter.name = "claude"
        del adapter.check_health  # MagicMock 去掉成员，对齐 claude adapter
        self.assertIsNone(self.runner._shared_adapter_health_gate(adapter))

    def test_dispatch_family_check_health_unchanged(self):
        """回归：_execute_agent 前置段既有 check_health 拦截行为保持。"""
        calls = []
        adapter = self._dsh_adapter(calls)
        with patch("core.agent_runner.runner.resolve_adapter_from_config",
                   return_value=adapter), \
                patch("core.agent_runner.runner.precheck_harness_executable",
                      return_value=None):
            result = self.runner._execute_agent("spec-a", "impl", "run-x")
        self.assertFalse(result.success)
        self.assertIn("dsh 版本超白名单", str(result.error))
        self.assertEqual(len(calls), 1)


class TestRegressionProtections(_RunnerBase):
    """3.2 回归保护断言（排除行为不变 + 合法回落语义保留）。"""

    def test_dispatch_probe_lanes_whitelist_not_expanded(self):
        """DNS 连通预检白名单不扩：dispatch 族排除维持现状。"""
        self.assertEqual(
            self.runner._DISPATCH_PROBE_LANES, _DISPATCH_PROBE_LANES_BASELINE)
        # dispatch 族恒返回 None（不探测）；维护车道白名单行为不变
        for lane in ("spec", "impl", "verifier", "dispute-judge", "spec-review"):
            self.assertIsNone(self.runner._dispatch_probe_lane(lane, "user-spec"))
        self.assertEqual(
            self.runner._dispatch_probe_lane("arbiter", "user-spec"), "arbiter")
        self.assertEqual(
            self.runner._dispatch_probe_lane(None, "code-review"), "code-review")

    def test_maintenance_lane_connectivity_preflight_untouched(self):
        """维护车道连通预检行为不变：白名单车道仍走 _dispatch_connectivity_preflight。"""
        self.runner._dispatch_connectivity_preflight = MagicMock()
        with patch.object(AgentRunner, "_provider_fallback_dispatch_gate",
                          return_value=None), \
                patch("core.agent_runner.runner.get_current_adapter",
                      return_value=MagicMock(name="claude")), \
                patch.object(AgentRunner, "_shared_adapter_health_gate",
                             return_value=None):
            # evolution（维护白名单车道）触发预检；spec（dispatch 族）不触发
            self._run_agent_expect_popen_guard("evolution")
        self.runner._dispatch_connectivity_preflight.assert_called_once()
        self.runner._dispatch_connectivity_preflight.reset_mock()
        with patch.object(AgentRunner, "_provider_fallback_dispatch_gate",
                          return_value=None), \
                patch("core.agent_runner.runner.get_current_adapter",
                      return_value=MagicMock(name="claude")), \
                patch.object(AgentRunner, "_shared_adapter_health_gate",
                             return_value=None), \
                patch("subprocess.Popen", side_effect=AssertionError("stop")):
            with self.assertRaises(AssertionError):
                self.runner._run_agent("p", self.proot, "impl-run-1",
                                       spec_name="user-spec", agent_type="impl")
        self.runner._dispatch_connectivity_preflight.assert_not_called()

    def _run_agent_expect_popen_guard(self, agent_type):
        """跑到连通预检点即止：Popen 哨兵中断（预检在 Popen 之前）。"""
        with patch("subprocess.Popen",
                   side_effect=AssertionError("reached-popen")):
            with self.assertRaises(AssertionError):
                self.runner._run_agent("p", self.proot, f"{agent_type}-run-1",
                                       spec_name="user-spec",
                                       agent_type=agent_type)


class TestProbeDefaultChainCredentials(unittest.TestCase):
    """探针级：默认链凭据三值判定与 probe② fallback 标记输出。"""

    def test_verdict_ok_when_env_route_complete(self):
        env = {"ANTHROPIC_BASE_URL": "https://gw.example/v1",
               "ANTHROPIC_API_KEY": "sk"}
        with patch.dict("os.environ", env, clear=False):
            verdict, detail = probe_default_chain_credentials({})
        self.assertEqual(verdict, FALLBACK_VERDICT_OK)
        self.assertIn("gw.example", detail)

    def test_verdict_missing_when_route_without_key(self):
        """11-09 事故形态：有路由无 key（「无 key 的默认路由」）。"""
        env = {"ANTHROPIC_BASE_URL": "https://gw.example/v1"}
        patch_env = patch.dict("os.environ", env, clear=False)
        with patch_env, patch.dict("os.environ", {
                "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_API_KEY": ""}):
            verdict, detail = probe_default_chain_credentials({})
        self.assertEqual(verdict, FALLBACK_VERDICT_MISSING)
        self.assertIn("ANTHROPIC_BASE_URL", detail)

    def test_verdict_indeterminable_when_no_route_trace(self):
        """无路由痕迹 → 降级试呼（单测密闭：试呼桩顶掉，不真发 CLI 请求）。"""
        from core.agent_runner import lane_preflight

        with patch.dict("os.environ", {
                "ANTHROPIC_BASE_URL": "", "ANTHROPIC_AUTH_TOKEN": "",
                "ANTHROPIC_API_KEY": ""}), \
                patch.object(
                    lane_preflight, "_trial_default_chain_credentials",
                    return_value=(
                        FALLBACK_VERDICT_INDETERMINABLE,
                        "单测密闭：未发起真实试呼")):
            lane_preflight.reset_default_chain_trial_cache()
            try:
                verdict, detail = probe_default_chain_credentials({})
            finally:
                lane_preflight.reset_default_chain_trial_cache()
        self.assertEqual(verdict, FALLBACK_VERDICT_INDETERMINABLE)
        self.assertIn("单测密闭", detail)

    def test_verdict_indeterminable_for_dsh_profile_default(self):
        verdict, detail = probe_default_chain_credentials(
            {"agent": {"harness": "dsh"}})
        self.assertEqual(verdict, FALLBACK_VERDICT_INDETERMINABLE)
        self.assertIn("dsh", detail)

    def test_probe_lane_health_reports_fallback_verdicts(self):
        """probe② 输出带 fallback 标记的明确结果（不再静默跳过）。"""
        env = {"ANTHROPIC_BASE_URL": "https://gw.example/v1"}
        with patch.dict("os.environ", env, clear=False), \
                patch.dict("os.environ",
                           {"ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_API_KEY": ""}):
            health = probe_lane_health({"agent": {"harness": "claude"}})
        self.assertFalse(health.ok)
        self.assertEqual(health.fallback_verdicts.get("repair"),
                         FALLBACK_VERDICT_MISSING)
        self.assertTrue(any(
            "fallback=true" in r and "repair" in r for r in health.reasons))

    def test_probe_lane_health_explicit_chain_behavior_unchanged(self):
        """显式链角色探针行为不变：不进 fallback_verdicts 表。"""
        env = {"ANTHROPIC_BASE_URL": "https://gw.example/v1",
               "ANTHROPIC_API_KEY": "sk"}
        with patch.dict("os.environ", env, clear=False):
            health = probe_lane_health(_EXPLICIT_CHAIN_CONFIG)
        self.assertNotIn("repair", health.fallback_verdicts)

    def test_legal_fallback_semantics_preserved(self):
        """D3 修订仅拦不可判定回落：回落到可用链仍放行（verdict ok 无 reason）。"""
        env = {"ANTHROPIC_BASE_URL": "https://gw.example/v1",
               "ANTHROPIC_API_KEY": "sk"}
        with patch.dict("os.environ", env, clear=False):
            health = probe_lane_health({"agent": {"harness": "claude"}})
            fallback_reasons = [r for r in health.reasons if "fallback=true" in r]
        self.assertEqual(fallback_reasons, [])
        self.assertEqual(health.fallback_verdicts.get("repair"),
                         FALLBACK_VERDICT_OK)

    def test_infra_fingerprints_untouched(self):
        """失败分级指纹集保持（探针扩展不触碰 classify 语义）。"""
        self.assertIn("MISSING_CREDENTIAL", LANE_INFRA_FINGERPRINTS)


if __name__ == "__main__":
    unittest.main()
