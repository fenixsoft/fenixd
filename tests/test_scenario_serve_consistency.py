"""tests/test_scenario_serve_consistency.py — 场景 kind 集 × 契约 serve 能力一致性测试。

evo-add-scenario-serve-consistency-preflight 三组测试义务：
  3.1 静态检查：scan_contract 交叉规则（serve 缺失 × api/web kind × start 兜底），
      既有三条规则与单参调用行为不变；
  3.2 挂载路径：冻结复用与并行产物路径的出题产物同样过契约静态检查，kind
      不匹配打回（_write_verify_contract_missing 通道，不触发 replan）；新鲜
      出题验收路径既有行为不回归；
  3.3 前置探测：verify_contract_missing 免唤起判定从「契约可解析」收紧为
      「serve/start 能力可覆盖在途场景 kind 需求」。

背景事故（2026-10-10 pack2-live-stream-player）：场景集含 api/web 而 verify.yaml
无 serve 段，缺口推迟到验证执行期才 fail-fast（3 轮空转 + blocked 约 51 分钟），
且 3 条 verify_contract_missing 信号被宽松前置探测错误闭环。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, SIGNAL
from core.pm_engine import PMEngine
from core.state_machine import StateMachine
from core.verify_engine.scenario_static_check import (
    SERVE_MISSING_RULE_ID,
    START_FALLBACK_PLACEHOLDER,
    scan_contract,
    start_fallback_valid,
)

# ── 共用夹具 ──────────────────────────────────────────────────────────────

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


# ═════════════════════════════════════════════════════════════════════════
# 3.1 静态检查：scan_contract serve 缺失交叉规则
# ═════════════════════════════════════════════════════════════════════════


class TestScanContractServeCrossRule(unittest.TestCase):
    """scan_contract 交叉规则（本 SPEC D1）：口径同 serving.py:1098-1099。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_api_web_kinds_no_serve_placeholder_start_reports(self):
        """kind 含 api/web + 无 serve + start 占位 → 报 serve 缺失（high）。"""
        findings = scan_contract(
            self.tmp,
            scenario_kinds={"api", "cli"},
            start_cmd=START_FALLBACK_PLACEHOLDER,
        )
        rules = {f["rule_id"]: f for f in findings}
        self.assertIn(SERVE_MISSING_RULE_ID, rules)
        self.assertEqual(rules[SERVE_MISSING_RULE_ID]["severity"], "high")
        self.assertIn("api", rules[SERVE_MISSING_RULE_ID]["message"])

    def test_web_kind_no_contract_file_reports(self):
        """契约文件整体缺失（serve=None）+ web 场景 + start 缺失 → 报。"""
        findings = scan_contract(
            self.tmp, scenario_kinds={"web"}, start_cmd=None
        )
        self.assertEqual([f["rule_id"] for f in findings], [SERVE_MISSING_RULE_ID])

    def test_start_non_placeholder_no_report(self):
        """start 非占位（commands.start 兜底存量形态）→ 不报，存量零迁移。"""
        findings = scan_contract(
            self.tmp, scenario_kinds={"api", "web"}, start_cmd="npm start"
        )
        self.assertEqual(findings, [])

    def test_pure_cli_kinds_no_report(self):
        """纯 cli + 无 serve（cimbar 历史形态）→ 不报。"""
        for start in (None, START_FALLBACK_PLACEHOLDER, "npm start"):
            findings = scan_contract(
                self.tmp, scenario_kinds={"cli"}, start_cmd=start
            )
            self.assertEqual(findings, [], f"kinds=cli, start={start!r} 应不报")

    def test_empty_kinds_no_report(self):
        """kind 集为空 → 交叉规则不触发。"""
        findings = scan_contract(
            self.tmp, scenario_kinds=set(), start_cmd=START_FALLBACK_PLACEHOLDER
        )
        self.assertEqual(findings, [])

    def test_no_kinds_arg_behavior_unchanged(self):
        """不传 kind 集（既有单参调用）→ 行为与现状一致（恒空，无契约时）。"""
        self.assertEqual(scan_contract(self.tmp), [])
        # 传了 start_cmd 但未传 kind 集：同样跳过交叉规则（既有调用方零迁移）
        self.assertEqual(scan_contract(self.tmp, start_cmd=None), [])

    def test_serve_missing_legacy_rules_stay_early_return(self):
        """serve 缺失时既有三条规则维持早退（不误报无 serve 契约）。"""
        findings = scan_contract(
            self.tmp,
            scenario_kinds={"api", "web"},
            start_cmd=START_FALLBACK_PLACEHOLDER,
        )
        self.assertEqual(
            {f["rule_id"] for f in findings},
            {SERVE_MISSING_RULE_ID},
            "serve 缺失时只应有交叉规则 finding，不得混入既有三条规则",
        )

    def test_serve_present_legacy_rules_unchanged(self):
        """serve 段存在时既有三条规则行为不变（含 serve_entry_missing）。"""
        _write(self.tmp, ".fenix/verify.yaml", "serve:\n  kind: command\n  cmd: node dist/server.js\n")
        findings = scan_contract(
            self.tmp, scenario_kinds={"api", "web"}, start_cmd=None
        )
        rules = {f["rule_id"] for f in findings}
        self.assertIn("serve_entry_missing", rules)
        self.assertNotIn(SERVE_MISSING_RULE_ID, rules, "serve 存在不得报 serve 缺失")

    def test_serve_present_healthy_contract_no_findings(self):
        """契约健康（入口存在 + {port} 注入）+ api/web kind → 空 findings。"""
        _write(self.tmp, "dist/server.js", "x")
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            "serve:\n  kind: command\n  cmd: node dist/server.js {port}\n",
        )
        findings = scan_contract(
            self.tmp, scenario_kinds={"api", "web"}, start_cmd=None
        )
        self.assertEqual(findings, [])

    def test_start_fallback_valid_sentinel_variants(self):
        """占位哨兵判定口径同 serving.py:1098-1099（strip 后比对）。"""
        self.assertFalse(start_fallback_valid(None))
        self.assertFalse(start_fallback_valid(""))
        self.assertFalse(start_fallback_valid("   "))
        self.assertFalse(start_fallback_valid(START_FALLBACK_PLACEHOLDER))
        self.assertFalse(
            start_fallback_valid(f"  {START_FALLBACK_PLACEHOLDER}  ")
        )
        self.assertTrue(start_fallback_valid("npm start"))
        self.assertTrue(start_fallback_valid("python3 -m http.server {port}"))


# ═════════════════════════════════════════════════════════════════════════
# 3.2 挂载路径：冻结复用 / 并行产物 / 新鲜出题验收
# ═════════════════════════════════════════════════════════════════════════


def _make_pipe(root: Path, config: dict | None = None):
    """PMEngine + VerificationPipeline 轻量装配（test_verify_lane_throughput 同款）。"""
    logger = MagicMock()
    sm = StateMachine(root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, root, logger)
    pipe = engine._verification
    pipe._escalate_env_blocked = MagicMock()
    return pipe, engine, sm


class _PipeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        self.pipe, self.engine, self.sm = _make_pipe(self.tmp)
        self.spec = "my-spec"

    def _findings_path(self) -> Path:
        return (
            self.tmp / ".fenix" / "verify-progress" / self.spec / "contract_findings.json"
        )


class TestGateMountFrozenAndParallel(_PipeCase):
    """冻结复用 / 并行产物路径的出题产物消费前统一过契约静态检查。"""

    def test_frozen_product_kind_mismatch_blocked(self):
        """冻结集含 web + 无 serve + start 占位 → 打回（信号 + 升级 + True）。"""
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO])
        with patch(
            "core.pm_engine.verification.scenario_gate._write_verify_contract_missing"
        ) as mock_sig:
            blocked = self.pipe._run_contract_static_check(self.spec)
        self.assertTrue(blocked, "kind 不匹配应打回")
        mock_sig.assert_called_once()
        self.assertEqual(mock_sig.call_args.args[1], self.spec)
        self.pipe._escalate_env_blocked.assert_called_once()
        # findings 落盘供 admin 处置 prompt 注入
        payload = json.loads(self._findings_path().read_text(encoding="utf-8"))
        self.assertIn(SERVE_MISSING_RULE_ID, {f["rule_id"] for f in payload})

    def test_parallel_product_path_blocked_same_gate(self):
        """并行产物消费（标记 completed、产物在盘）→ 同一门打回；消费行为本身不变。"""
        _write_scenarios(self.tmp, self.spec, [API_SCENARIO])
        self.sm.add_spec(self.spec, {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition(self.spec, st)
        self.engine._write_parallel_plan_marker(self.spec, {"status": "completed"})
        vp = self.tmp / ".fenix" / "verify-progress" / self.spec
        # 既有消费行为不回归：产物有效 → 标记 consumed、返回 True
        self.assertTrue(self.pipe._consume_parallel_plan_product(self.spec, vp))
        self.assertEqual(
            self.engine._read_parallel_plan_marker(self.spec).get("status"), "consumed"
        )
        # 消费后、冻结加载前的统一挂点：同一产物被 serve 一致性门打回
        with patch(
            "core.pm_engine.verification.scenario_gate._write_verify_contract_missing"
        ):
            self.assertTrue(self.pipe._run_contract_static_check(self.spec))
        self.pipe._escalate_env_blocked.assert_called_once()

    def test_no_scenarios_product_noop(self):
        """产物未落盘（纯新鲜出题轮的消费前挂点）→ 零情报放行、不写 findings。"""
        self.assertFalse(self.pipe._run_contract_static_check(self.spec))
        self.assertFalse(self._findings_path().exists())
        self.pipe._escalate_env_blocked.assert_not_called()

    def test_valid_contract_not_blocked(self):
        """契约 serve 段有效（static）+ web 冻结集 → 放行（False）。"""
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO])
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            "serve:\n  kind: static\n  root: dist\n",
        )
        self.assertFalse(self.pipe._run_contract_static_check(self.spec))
        self.pipe._escalate_env_blocked.assert_not_called()

    def test_start_fallback_legacy_shape_not_blocked(self):
        """无 serve 但 start 非占位（执行期兜底存量形态）→ 放行。"""
        _write_scenarios(self.tmp, self.spec, [API_SCENARIO])
        self.pipe2, _, _ = _make_pipe(
            self.tmp, config={"commands": {"start": "npm start"}}
        )
        self.pipe2._escalate_env_blocked = MagicMock()
        with patch(
            "core.pm_engine.verification.scenario_gate._write_verify_contract_missing"
        ) as mock_sig:
            self.assertFalse(self.pipe2._run_contract_static_check(self.spec))
        mock_sig.assert_not_called()

    def test_unparsable_scenarios_fail_open(self):
        """场景文件不可解析 → fail-open 放行，不阻断验证。"""
        _write(self.tmp, f".fenix/verify-progress/{self.spec}/test_scenarios.json", "{oops")
        self.assertFalse(self.pipe._run_contract_static_check(self.spec))
        self.pipe._escalate_env_blocked.assert_not_called()

    def test_gate_exception_fail_open(self):
        """scan_contract 自身异常 → fail-open 放行（检查器缺陷不阻断验证）。"""
        _write_scenarios(self.tmp, self.spec, [WEB_SCENARIO])
        with patch(
            "core.verify_engine.scenario_static_check.scan_contract",
            side_effect=RuntimeError("checker boom"),
        ):
            self.assertFalse(self.pipe._run_contract_static_check(self.spec))
        self.pipe._escalate_env_blocked.assert_not_called()


class TestThreeStageMountWiring(_PipeCase):
    """pipeline.py 消费前挂点接线：门打回 → 终止流水线（不触发冻结加载/出题）。"""

    def _to_testing(self):
        self.sm.add_spec(self.spec, {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition(self.spec, st)

    def test_gate_block_aborts_before_frozen_load(self):
        """serve 一致性门打回 → 直接 return，_load_frozen_or_escalate 不可达。"""
        self._to_testing()
        pipe = self.pipe
        pipe._reload_verify_engine_modules = MagicMock()
        pipe._consume_parallel_plan_product = MagicMock(return_value=True)
        pipe._run_contract_static_check = MagicMock(return_value=True)
        pipe._load_frozen_or_escalate = MagicMock()
        pipe._run_three_stage_verification(self.spec)
        pipe._run_contract_static_check.assert_called_once_with(self.spec)
        pipe._load_frozen_or_escalate.assert_not_called()

    def test_gate_pass_continues_to_frozen_load(self):
        """门放行 → 照常进入冻结加载（既有流程零变化）。aborted=True 让流水线
        在冻结加载后立即收口（本测试只锁定挂点放行后的可达性）。"""
        self._to_testing()
        pipe = self.pipe
        pipe._reload_verify_engine_modules = MagicMock()
        pipe._consume_parallel_plan_product = MagicMock(return_value=True)
        pipe._run_contract_static_check = MagicMock(return_value=False)
        pipe._load_frozen_or_escalate = MagicMock(return_value=(None, True))
        pipe._run_three_stage_verification(self.spec)
        pipe._load_frozen_or_escalate.assert_called_once()

    def test_fresh_path_mount_guards_return(self):
        """新鲜出题验收路径挂点同样以返回值守卫（源级锁定，防回退为裸调用）。"""
        import inspect

        import core.pm_engine.verification.pipeline as pipeline_mod

        src = inspect.getsource(pipeline_mod)
        self.assertEqual(
            src.count("if self._run_contract_static_check(spec_name):"),
            2,
            "两处挂点（消费前统一挂点 + 新鲜出题验收路径）都应以其返回值守卫 return",
        )


class TestFreshPathNonRegression(_PipeCase):
    """新鲜出题验收路径既有行为不回归：通过门放行 + findings 照常落盘。"""

    def test_fresh_product_with_serve_contract_passes(self):
        """planner 刚写出的产物（文件在盘）+ 健康契约 → 放行且 findings 落盘。"""
        _write_scenarios(self.tmp, self.spec, [API_SCENARIO])
        _write(self.tmp, "dist/server.js", "x")
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            "serve:\n  kind: command\n  cmd: node dist/server.js {port}\n",
        )
        with patch(
            "core.pm_engine.verification.scenario_gate._write_verify_contract_missing"
        ) as mock_sig:
            self.assertFalse(self.pipe._run_contract_static_check(self.spec))
        mock_sig.assert_not_called()
        self.assertTrue(self._findings_path().exists(), "findings 应照常落盘（可为空表）")

    def test_legacy_three_rules_still_lodged_not_blocking(self):
        """既有三条规则维持留痕不阻断：入口缺失报 finding 但不打回。"""
        _write_scenarios(self.tmp, self.spec, [API_SCENARIO])
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            "serve:\n  kind: command\n  cmd: node missing_entry.js {port}\n",
        )
        with patch(
            "core.pm_engine.verification.scenario_gate._write_verify_contract_missing"
        ) as mock_sig:
            blocked = self.pipe._run_contract_static_check(self.spec)
        self.assertFalse(blocked, "既有规则只留痕不阻断")
        mock_sig.assert_not_called()
        payload = json.loads(self._findings_path().read_text(encoding="utf-8"))
        self.assertIn("serve_entry_missing", {f["rule_id"] for f in payload})
        self.pipe._escalate_env_blocked.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════
# 3.3 前置探测：verify_contract_missing 免唤起判定收紧
# ═════════════════════════════════════════════════════════════════════════

_YAML_NO_SERVE = "prepare:\n  - run: npm run build\n"
_YAML_WITH_SERVE = (
    "prepare:\n  - run: npm run build\n"
    "serve:\n  kind: static\n  root: dist\n"
)


class _RecLogger:
    """记录型 logger（与既有前置探测测试同构）。"""

    def __init__(self):
        self.warnings = []
        self.errors = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a):
        self.warnings.append(" ".join(str(x) for x in a))

    def error(self, *a):
        self.errors.append(" ".join(str(x) for x in a))


class _NonTerminalSM:
    def read_one(self, spec):
        return {"status": "implemented"}

    def read_all(self):
        return {}


def _make_monitor(tmp: Path, config: dict | None = None):
    logger = _RecLogger()
    store = AdminStore(tmp, logger)
    mon = AdminMonitor(
        config or {},
        _NonTerminalSM(),
        tmp,
        logger,
        store=store,
        agent_runner=MagicMock(),
    )
    return mon, store, logger


class TestPreprobeCapabilityGate(unittest.TestCase):
    """_preprobe_signal_satisfied 对 verify_contract_missing 的能力覆盖判定。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        self.mon, self.store, self.logger = _make_monitor(self.tmp)
        self.spec = "spec-a"

    def _inflight(self, kinds: list) -> None:
        _write_scenarios(
            self.tmp,
            self.spec,
            [
                {**WEB_SCENARIO, "id": f"s-web-{i}"} if k == "web"
                else {**API_SCENARIO, "id": f"s-api-{i}"} if k == "api"
                else {**CLI_SCENARIO, "id": f"s-cli-{i}"}
                for i, k in enumerate(kinds)
            ],
        )

    def test_parseable_but_no_serve_with_api_inflight_not_satisfied(self):
        """契约可解析但无 serve + 在途含非 cli kind → 不 auto-resolve。"""
        _write(self.tmp, ".fenix/verify.yaml", _YAML_NO_SERVE)
        self._inflight(["cli", "api"])
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_contract_missing", self.spec),
            False,
        )

    def test_serve_added_recovers_auto_resolve(self):
        """契约补齐 serve 段后 → 恢复免唤起。"""
        self._inflight(["cli", "api"])
        _write(self.tmp, ".fenix/verify.yaml", _YAML_NO_SERVE)
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_contract_missing", self.spec),
            False,
        )
        _write(self.tmp, ".fenix/verify.yaml", _YAML_WITH_SERVE)
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_contract_missing", self.spec),
            True,
        )

    def test_non_placeholder_start_with_pure_cli_satisfied(self):
        """start 非占位且场景全 cli → 判满足。"""
        mon, _, _ = _make_monitor(
            self.tmp, config={"commands": {"start": "python3 serve.py"}}
        )
        _write(self.tmp, ".fenix/verify.yaml", _YAML_NO_SERVE)
        self._inflight(["cli", "cli"])
        self.assertIs(
            mon._preprobe_signal_satisfied("verify_contract_missing", self.spec),
            True,
        )

    def test_non_placeholder_start_covers_api_inflight(self):
        """start 非占位（执行期兜底存量形态）+ 在途含 api → 判满足。"""
        mon, _, _ = _make_monitor(
            self.tmp, config={"commands": {"start": "python3 serve.py"}}
        )
        _write(self.tmp, ".fenix/verify.yaml", _YAML_NO_SERVE)
        self._inflight(["api"])
        self.assertIs(
            mon._preprobe_signal_satisfied("verify_contract_missing", self.spec),
            True,
        )

    def test_missing_scenarios_file_degrades_to_existence(self):
        """场景文件缺失（kind 集按空集）→ 退化为 serve/start 存在性判定。"""
        _write(self.tmp, ".fenix/verify.yaml", _YAML_NO_SERVE)
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_contract_missing", self.spec),
            False,
            "空 kind 集退化为存在性判定：无 serve 且 start 占位 → 不满足",
        )
        _write(self.tmp, ".fenix/verify.yaml", _YAML_WITH_SERVE)
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_contract_missing", self.spec),
            True,
        )

    def test_missing_contract_still_not_satisfied(self):
        """契约文件缺失/不可解析（contract=None）→ 维持不满足（语义不变）。"""
        self._inflight(["cli"])
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_contract_missing", self.spec),
            False,
        )

    def test_regression_missing_semantics_unchanged(self):
        """共用分支 verify_regression_missing 语义（regression 段存在性）不变。"""
        self._inflight(["api"])
        _write(self.tmp, ".fenix/verify.yaml", _YAML_WITH_SERVE)
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_regression_missing", self.spec),
            False,
            "无 regression 段 → 不满足（既有语义）",
        )
        _write(
            self.tmp,
            ".fenix/verify.yaml",
            _YAML_WITH_SERVE + "regression:\n  cmd: pytest tests/ -q\n  output: r.xml\n",
        )
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_regression_missing", self.spec),
            True,
        )

    def test_no_spec_falls_back_to_existence(self):
        """未传 spec（缺省 None）→ kind 集空集，退化为存在性判定。"""
        _write(self.tmp, ".fenix/verify.yaml", _YAML_WITH_SERVE)
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_contract_missing"), True
        )
        _write(self.tmp, ".fenix/verify.yaml", _YAML_NO_SERVE)
        self.assertIs(
            self.mon._preprobe_signal_satisfied("verify_contract_missing"), False
        )


class TestPreprobeIntakeWiring(unittest.TestCase):
    """摄取循环接线：spec 直传 → 能力缺口未补时不 auto-resolve、照常唤起。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        self.spec = "spec-a"

    def _seed(self, store):
        return store.append(
            {
                "kind": SIGNAL,
                "signal_type": "verify_contract_missing",
                "spec": self.spec,
                "severity": "major",
                "description": "请求起草验证契约",
                "evidence": "项目名=x",
                "recommended_action": "",
            }
        )

    def test_capability_gap_keeps_signal_open(self):
        """可解析但无 serve + 在途 api → 不闭环，照常唤起（2026-10-10 事故形态）。"""
        mon, store, logger = _make_monitor(self.tmp)
        rec = self._seed(store)
        _write(self.tmp, ".fenix/verify.yaml", _YAML_NO_SERVE)
        _write_scenarios(self.tmp, self.spec, [API_SCENARIO])
        with patch.object(mon, "_invoke_administrator") as mock_invoke:
            mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 1, "能力缺口未补齐应照常唤起")
        recs = {r["id"]: r for r in store.read_all()}
        self.assertFalse(recs[rec["id"]].get("handled"), "不得 pre-probe 闭环")
        self.assertTrue(recs[rec["id"]].get("escalated"), "唤起路径应 mark_escalated")

    def test_capability_present_closes_without_invocation(self):
        """契约补齐 serve 段 → 前置探测闭环免唤起（既有免唤起语义恢复）。"""
        mon, store, logger = _make_monitor(self.tmp)
        rec = self._seed(store)
        _write(self.tmp, ".fenix/verify.yaml", _YAML_WITH_SERVE)
        _write_scenarios(self.tmp, self.spec, [API_SCENARIO])
        with patch.object(mon, "_invoke_administrator") as mock_invoke:
            mon._detect_family_explosion()
            self.assertEqual(mock_invoke.call_count, 0, "诉求已满足应免唤起")
        recs = {r["id"]: r for r in store.read_all()}
        self.assertTrue(recs[rec["id"]].get("handled"), "探测通过应置 handled")
        self.assertTrue(recs[rec["id"]].get("escalated"), "下一 tick 不再重捞")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
