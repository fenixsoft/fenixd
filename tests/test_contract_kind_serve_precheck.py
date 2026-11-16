"""tests/test_contract_kind_serve_precheck.py — 出题产物按 kind 集前置校验契约段位。

evo-verify-contract-serve-sync-precheck 测试义务：

  2.1 三场景：
    - 产物 kind 集含 api/web 且契约无 serve 段 → 写盘时出信号（info 一次性）；
    - 契约段位齐备（serve 段健康 / commands.start 非占位兜底）→ 零信号；
    - 契约缺失或解析失败 / 检查器异常 → fail-open 放行落盘（不阻断不 replan）。

  2.2 回归锚：
    - 消费期静态门保留为最后防线（打回行为不变，且不受前置去重抑制——
      前置 info 记录在账时门照常出 major 记录并打回）；
    - 实现期信号 info 级一次性不召唤 Administrator（摄取循环对 info 记录
      零唤起；对照：消费期 major 记录照常被摄取召唤）；
    - 同 spec 同缺口不重复发信号（写盘点/验收点跨挂点单条；处置后复位
      允许再次提示）。

  挂点接线：新鲜出题产物写盘点（plan-ready 后）与并行产物验收点
  （_validate_parallel_product 通过后）均调用前置校验。

背景事故（2026-11-11 web-browser-client）：出题 run 把场景集从纯 cli 扩为
api/cli/web，契约仍为纯 cli 形态，缺口到实现合并消费期才被 serve 一致性门
打回（1 个 admin run 857s 代起草 serve/ready，验证推迟约 13 分钟）。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, SIGNAL
from core.pm_engine import PMEngine
from core.state_machine import StateMachine
from tests.helpers import FakeLogger

from test_admin import FakeRunner, FakeSM

# ── 共用夹具（test_scenario_serve_consistency 同款）──────────────────────

WEB_SCENARIO = {
    "id": "scn-web-1",
    "kind": "web",
    "description": "web 场景 出处 core/feature.py:10",
    "steps": [{"action": "navigate", "value": "http://127.0.0.1:8765/"}],
    "assertions": [{"type": "element_visible", "selector": ".x", "label": "可见"}],
}

API_SCENARIO = {
    "id": "scn-api-1",
    "kind": "api",
    "description": "api 场景 出处 core/feature.py:11",
    "steps": [
        {
            "action": "http_request",
            "method": "GET",
            "url": "http://127.0.0.1:8765/api/x",
        }
    ],
    "assertions": [{"type": "status_code", "expected": 200}],
}

CLI_SCENARIO = {
    "id": "scn-cli-1",
    "kind": "cli",
    "description": "cli 场景 出处 core/feature.py:12",
    "steps": [{"action": "run", "command": "python3 scripts/probe.py"}],
}


def _write(tmp: Path, rel: str, text: str) -> None:
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _write_scenarios(tmp: Path, spec: str, scenarios: list) -> None:
    _write(
        tmp,
        f".fenix/verify-progress/{spec}/test_scenarios.json",
        json.dumps(scenarios, ensure_ascii=False),
    )


def _make_pipe(root: Path, config: dict | None = None):
    """PMEngine + VerificationPipeline 轻量装配（test_scenario_serve_consistency 同款）。"""
    logger = MagicMock()
    sm = StateMachine(root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, root, logger)
    pipe = engine._verification
    pipe._escalate_env_blocked = MagicMock()
    return pipe, engine, sm


def _contract_signals(proot: Path) -> list:
    store = AdminStore(proot)
    return [
        r
        for r in store.read_all()
        if r.get("kind") == SIGNAL
        and r.get("signal_type") == "verify_contract_missing"
    ]


class _Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        self.spec = "my-spec"
        self.pipe, self.engine, self.sm = _make_pipe(self.tmp)

    def _vp(self) -> Path:
        return self.tmp / ".fenix" / "verify-progress" / self.spec


# ═════════════════════════════════════════════════════════════════════════
# 2.1 场景一：kind 集含 api/web 且契约无 serve 段 → 写盘时出信号（info 一次性）
# ═════════════════════════════════════════════════════════════════════════


class TestPreflightEmitsSignal(_Case):
    def test_api_web_kinds_no_serve_emits_info_signal(self):
        """产物 kind 集含 web/cli + 无契约（serve 缺失）→ 写盘点出 info 信号。"""
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO, CLI_SCENARIO])
        # 模拟写盘点调用（产物已落盘）：零参数形态（kind 集从产物现读）
        hit = self.pipe._preflight_contract_serve_sync(self.spec)
        self.assertTrue(hit, "kind 集含 web 且无 serve 段应命中")
        sigs = _contract_signals(self.tmp)
        self.assertEqual(len(sigs), 1, "应恰出一条 verify_contract_missing 记录")
        sig = sigs[0]
        # 实现期语义：info 级、沉淀不召唤（escalated=True 消费「写入即待唤起」）、
        # 未处置（has_unhandled_signal 去重锚点在账）
        self.assertEqual(sig.get("severity"), "info")
        self.assertIs(sig.get("escalated"), True)
        self.assertFalse(sig.get("handled"))
        self.assertEqual(sig.get("spec"), self.spec)
        # 1.3 定向补段情报：kind 集 + 契约文件路径 + 缺失段位清单
        evidence = str(sig.get("evidence") or "")
        self.assertIn("scenario_kinds=cli、web", evidence)
        self.assertIn(".fenix/verify.yaml", evidence)
        self.assertIn("missing_segments=serve", evidence)
        # 情报提示不拦截：文案注明勿复位 spec 状态
        self.assertIn("勿复位 spec 状态", str(sig.get("recommended_action") or ""))

    def test_explicit_kinds_arg_same_signal(self):
        """显式传 kind 集（验收点复用形态，产物读盘非必需）→ 同一出 info 信号。"""
        hit = self.pipe._preflight_contract_serve_sync(
            self.spec, scenario_kinds={"api", "cli"}
        )
        self.assertTrue(hit)
        sigs = _contract_signals(self.tmp)
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].get("severity"), "info")
        self.assertIn("scenario_kinds=api、cli", str(sigs[0].get("evidence") or ""))

    def test_pure_cli_kinds_zero_signal(self):
        """纯 cli 产物（无实例形态）+ 无契约 → 零信号放行。"""
        _write_scenarios(self.tmp, self.spec, [CLI_SCENARIO])
        self.assertFalse(self.pipe._preflight_contract_serve_sync(self.spec))
        self.assertEqual(_contract_signals(self.tmp), [])


# ═════════════════════════════════════════════════════════════════════════
# 2.1 场景二：契约段位齐备 → 零信号
# ═════════════════════════════════════════════════════════════════════════


class TestPreflightContractComplete(_Case):
    def test_healthy_serve_zero_signal(self):
        """serve 段健康（入口存在 + {port} 注入）+ web 产物 → 零信号。"""
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO])
        _write(self.tmp, "dist/server.js", "x")
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            "serve:\n  kind: command\n  cmd: node dist/server.js {port}\n",
        )
        self.assertFalse(self.pipe._preflight_contract_serve_sync(self.spec))
        self.assertEqual(_contract_signals(self.tmp), [])

    def test_start_fallback_valid_zero_signal(self):
        """无 serve 但 commands.start 非占位（执行期兜底存量形态）→ 零信号。"""
        _write_scenarios(self.tmp, self.spec, [API_SCENARIO])
        self.pipe2, _, _ = _make_pipe(
            self.tmp, config={"commands": {"start": "npm start"}}
        )
        self.assertFalse(self.pipe2._preflight_contract_serve_sync(self.spec))
        self.assertEqual(_contract_signals(self.tmp), [])


# ═════════════════════════════════════════════════════════════════════════
# 2.1 场景三：契约缺失/解析失败/检查器异常 → fail-open 放行落盘
# ═════════════════════════════════════════════════════════════════════════


class TestPreflightFailOpen(_Case):
    def test_broken_contract_yaml_no_raise_write_proceeds(self):
        """契约解析失败（坏 YAML）→ 前置校验不抛、产物写盘照常进行。"""
        _write(self.tmp, ".fenix/verify.yaml", "{oops 不合法 YAML")
        # 先落一个「在飞期间被改坏」的契约，再按写盘点语境调用：无论扫描器
        # fail-open 返回空还是按 serve=None 出情报，调用方均不得被抛穿。
        for kinds in ({"api", "web"}, {"cli"}):
            with self.subTest(kinds=sorted(kinds)):
                hit = self.pipe._preflight_contract_serve_sync(
                    self.spec, scenario_kinds=kinds
                )
                self.assertIsInstance(hit, bool)
        # 产物写盘（前置校验只提示不拦截的落盘侧证据）
        from core.verify_engine.scenarios import write_scenarios_array

        write_scenarios_array([WEB_SCENARIO], self._vp() / "test_scenarios.json")
        self.assertTrue((self._vp() / "test_scenarios.json").is_file())

    def test_checker_exception_fail_open(self):
        """扫描器自身异常 → WARNING 吞掉返回 False，不阻断落盘。"""
        with patch(
            "core.verify_engine.scenario_static_check.scan_contract",
            side_effect=RuntimeError("checker boom"),
        ):
            self.assertFalse(
                self.pipe._preflight_contract_serve_sync(
                    self.spec, scenario_kinds={"web"}
                )
            )
        self.assertEqual(_contract_signals(self.tmp), [])

    def test_missing_product_zero_param_fail_open(self):
        """零参数形态 + 产物缺失/不可解析 → 零情报放行（False）。"""
        self.assertFalse(self.pipe._preflight_contract_serve_sync(self.spec))
        _write(self._vp() / "test_scenarios.json", "", "{oops")
        self.assertFalse(self.pipe._preflight_contract_serve_sync(self.spec))
        self.assertEqual(_contract_signals(self.tmp), [])


# ═════════════════════════════════════════════════════════════════════════
# 2.2 回归锚一：消费期静态门保留为最后防线（行为不变、不受前置去重抑制）
# ═════════════════════════════════════════════════════════════════════════


class TestConsumptionGateRegression(_Case):
    def test_gate_still_blocks_with_front_record_in_ledger(self):
        """前置 info 记录在账（未处置）时，消费期门照常打回 + 出 major 记录。"""
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO])
        # 前置挂点先命中（写盘点语义）：info 一次性记录在账
        self.assertTrue(self.pipe._preflight_contract_serve_sync(self.spec))
        # 消费期门（最后防线）：同缺口 MUST NOT 被前置去重抑制
        with patch(
            "core.pm_engine.verification.scenario_gate._write_verify_contract_missing"
        ) as mock_sig:
            blocked = self.pipe._run_contract_static_check(self.spec)
        self.assertTrue(blocked, "消费期门打回行为不变")
        mock_sig.assert_called_once()
        self.pipe._escalate_env_blocked.assert_called_once()
        # 门自身走 major 通道落记录（真实写入验证摄取召唤形态）
        self.pipe._write_verify_contract_missing(self.spec, "门打回", "evidence")
        sigs = _contract_signals(self.tmp)
        self.assertEqual(len(sigs), 2, "前置 info 记录 + 消费期 major 记录并存")
        by_sev = {s.get("severity"): s for s in sigs}
        self.assertEqual(by_sev["major"].get("escalated") or None, None,
                         "major 记录不得带 escalated（摄取召唤语义保留）")

    def test_channel_default_severity_major_unchanged(self):
        """通道 severity 参数化默认 major：消费期既有调用点零变化。"""
        self.pipe._write_verify_contract_missing(self.spec, "note", "evidence")
        sigs = _contract_signals(self.tmp)
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].get("severity"), "major")
        self.assertIs(sigs[0].get("escalated"), None, "缺省不得设 escalated")


# ═════════════════════════════════════════════════════════════════════════
# 2.2 回归锚二：info 级一次性不召唤 Administrator（摄取循环零唤起）
# ═════════════════════════════════════════════════════════════════════════


def _make_monitor_on(proot: Path, specs: dict, runner):
    """AdminMonitor 装配在既有项目根（与 pipe 共享同一 store）。"""
    return AdminMonitor(
        {},
        FakeSM(specs),
        proot,
        FakeLogger(),
        store=AdminStore(proot, FakeLogger()),
        agent_runner=runner,
    )


class TestInfoNoInvocation(_Case):
    def _preflight_hit(self):
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO])
        self.assertTrue(self.pipe._preflight_contract_serve_sync(self.spec))

    def test_info_record_not_invoked_by_ingest(self):
        """前置 info 记录（真实缺口在途）→ 摄取循环零唤起（沉淀不召唤）。"""
        self._preflight_hit()
        runner = FakeRunner()
        mon = _make_monitor_on(
            self.tmp,
            {self.spec: {"status": "implementing", "error": None,
                         "updated": "2026-11-16T00:00:00"}},
            runner,
        )
        mon._detect_family_explosion()
        self.assertEqual(runner.calls, [], "info 记录不得召唤 Administrator")
        sigs = _contract_signals(self.tmp)
        self.assertEqual(len(sigs), 1)
        self.assertFalse(sigs[0].get("handled"), "记录保持未处置（去重锚点在账）")

    def test_major_gate_record_still_invoked_by_ingest(self):
        """对照锚：消费期 major 记录（未 escalated）→ 摄取循环照常召唤。"""
        self.pipe._write_verify_contract_missing(self.spec, "门打回", "evidence")
        runner = FakeRunner()
        mon = _make_monitor_on(
            self.tmp,
            {self.spec: {"status": "testing", "error": None,
                         "updated": "2026-11-16T00:00:00"}},
            runner,
        )
        mon._detect_family_explosion()
        self.assertEqual(len(runner.calls), 1, "major 记录照常召唤（最后防线不变）")
        self.assertEqual(runner.calls[0].get("severity"), "major")


# ═════════════════════════════════════════════════════════════════════════
# 2.2 回归锚三：同 spec 同缺口不重复发信号（跨挂点单条；处置后复位再提示）
# ═════════════════════════════════════════════════════════════════════════


class TestDedupSingleSignal(_Case):
    def test_cross_hook_dedup_single_record(self):
        """写盘点 + 验收点跨挂点同 spec 同缺口 → 恰一条未处理记录。"""
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO, API_SCENARIO])
        self.assertTrue(self.pipe._preflight_contract_serve_sync(self.spec))
        # 第二次（模拟另一挂点/同缺口重入）：在账即不成条
        self.assertTrue(self.pipe._preflight_contract_serve_sync(self.spec))
        unhandled = [s for s in _contract_signals(self.tmp) if not s.get("handled")]
        self.assertEqual(len(unhandled), 1, "同缺口在账期间不得重复成条")

    def test_handled_resets_allowing_new_signal(self):
        """记录被处置（handled）后复位 → 允许再次提示（新记录）。"""
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO])
        self.assertTrue(self.pipe._preflight_contract_serve_sync(self.spec))
        store = AdminStore(self.tmp)
        rec = [r for r in store.read_all()
               if r.get("kind") == SIGNAL and not r.get("handled")][0]
        store.mark_signal_handled(rec.get("id"))
        # 处置后同缺口再现 → 允许再次成条
        self.assertTrue(self.pipe._preflight_contract_serve_sync(self.spec))
        unhandled = [s for s in _contract_signals(self.tmp) if not s.get("handled")]
        self.assertEqual(len(unhandled), 1)
        self.assertNotEqual(unhandled[0].get("id"), rec.get("id"))


# ═════════════════════════════════════════════════════════════════════════
# 挂点接线：新鲜出题写盘点 / 并行产物验收点
# ═════════════════════════════════════════════════════════════════════════


class TestHookWiring(_Case):
    def _to_testing(self):
        self.sm.add_spec(self.spec, {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition(self.spec, st)

    def test_fresh_plan_write_point_invokes_preflight(self):
        """新鲜出题路径：plan-ready 确认后、消费期门之前调用前置校验。"""
        self._to_testing()
        pipe = self.pipe
        pipe._reload_verify_engine_modules = MagicMock()
        pipe._consume_parallel_plan_product = MagicMock(return_value=True)
        pipe._read_planner_result = MagicMock(
            return_value=SimpleNamespace(ok=True, status="plan-ready",
                                         reason="", detail="")
        )
        pipe._clear_degrade_context = MagicMock()
        # 消费前统一挂点放行（False）→ 出题轮 → 写盘点前置校验 → 门打回收口（True）
        pipe._run_contract_static_check = MagicMock(side_effect=[False, True])
        pipe._preflight_contract_serve_sync = MagicMock()
        pipe._run_three_stage_verification(self.spec)
        pipe._preflight_contract_serve_sync.assert_called_once_with(self.spec)
        # 消费期门两处挂点均可达：消费前统一挂点（放行）+ plan-ready 后（打回收口）
        self.assertEqual(pipe._run_contract_static_check.call_count, 2)
        pipe._run_contract_static_check.assert_called_with(self.spec)

    def test_parallel_acceptance_point_invokes_preflight(self):
        """并行产物路径：_validate_parallel_product 通过后调用前置校验。"""
        self._to_testing()
        _write_scenarios(self.tmp, self.spec, [API_SCENARIO])
        self.engine._write_parallel_plan_marker(self.spec, {"status": "completed"})
        vp = self._vp()
        self.pipe._preflight_contract_serve_sync = MagicMock()
        self.assertTrue(self.pipe._consume_parallel_plan_product(self.spec, vp))
        self.pipe._preflight_contract_serve_sync.assert_called_once_with(self.spec)
        self.assertEqual(
            self.engine._read_parallel_plan_marker(self.spec).get("status"),
            "consumed",
            "前置校验不得阻断消费短路",
        )


if __name__ == "__main__":
    unittest.main()
