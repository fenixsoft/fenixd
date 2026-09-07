"""multi-kind 场景模型与 Runner 分派/惰性 setup 测试（add-verify-multi-kind-runner PR1）。

覆盖 spec verify-runner-engine / multi-kind-scenario-model：
  - Scenario.kind 缺省 web、from_dict 透传、to_dict 序列化
  - 非法 kind 拒绝（不静默按 web 处理）
  - per-kind 词表校验（cli/api 各自词表与必填字段）
  - 引擎按 kind 分派 Runner（调度器零 per-kind 执行分支）
  - lazy setup/teardown：仅对实际出现的 kind 执行
  - 验收失败不启动任何 Runner
"""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_engine import runner as runner_module
from core.verify_engine.engine import VerifyEngine
from core.verify_engine.scenarios import (
    TestScenario as Scenario,  # 别名防 pytest 把数据类当测试类收集
    VALID_KINDS, KIND_ACTIONS, KIND_ASSERTIONS,
    CLI_ASSERTIONS, API_ASSERTIONS, VALID_ACTIONS, VALID_ASSERTIONS,
    validate_scenario,
)
from core.verify_engine.web_runner import WebRunner


def _scenario(sid="s1", kind=None, steps=None, assertions=None, **kw):
    d = {"id": sid, "steps": steps or [], "assertions": assertions or []}
    if kind:
        d["kind"] = kind
    d.update(kw)
    return d


# ── 1. kind 字段与缺省兼容 ───────────────────────────────────────

class TestKindField(unittest.TestCase):
    def test_default_kind_is_web(self):
        s = Scenario.from_dict(_scenario())
        self.assertEqual(s.kind, "web")

    def test_from_dict_passes_kind(self):
        s = Scenario.from_dict(_scenario(kind="cli"))
        self.assertEqual(s.kind, "cli")
        s2 = Scenario.from_dict(_scenario(kind="api"))
        self.assertEqual(s2.kind, "api")

    def test_to_dict_serializes_kind(self):
        s = Scenario.from_dict(_scenario(kind="cli"))
        self.assertEqual(s.to_dict()["kind"], "cli")
        # 缺省 web 也序列化（报告/冻结集透传依赖）
        s2 = Scenario.from_dict(_scenario())
        self.assertEqual(s2.to_dict()["kind"], "web")

    def test_kind_values_enum(self):
        self.assertEqual(VALID_KINDS, {"web", "cli", "api"})

    def test_unknown_kind_rejected(self):
        s = Scenario.from_dict(_scenario(kind="desktop"))
        errs = s.validate()
        self.assertTrue(any("未知 kind" in e for e in errs), errs)
        self.assertIn("desktop", errs[0])


# ── 2. per-kind 词表 ─────────────────────────────────────────────

class TestPerKindVocabulary(unittest.TestCase):
    def test_web_vocab_unchanged(self):
        # web 词表内容不变（等价重构不变量）
        self.assertEqual(VALID_ACTIONS, KIND_ACTIONS["web"])
        self.assertEqual(VALID_ASSERTIONS, KIND_ASSERTIONS["web"])

    def test_cli_vocab_singleton_run(self):
        self.assertEqual(KIND_ACTIONS["cli"], {"run"})
        self.assertEqual(
            KIND_ASSERTIONS["cli"],
            {"exit_code", "file_exists", "output_match", "file_content",
             "json_output", "dir_contains"},
        )

    def test_api_vocab_http_and_sse(self):
        self.assertEqual(KIND_ACTIONS["api"], {"http_request", "sse_connect"})
        self.assertEqual(
            KIND_ASSERTIONS["api"],
            {"status_code", "json_path", "response_header", "body_contains",
             "json_schema", "latency_under", "sse_event_matches",
             "sse_event_count"},
        )

    def test_cross_vocab_step_rejected(self):
        """kind: api 场景出现 click（web 词表）步骤 → 验收拒绝。"""
        s = Scenario.from_dict(_scenario(
            kind="api",
            steps=[{"action": "click", "target": ".x"}],
        ))
        errs = s.validate()
        self.assertTrue(any("click" in e for e in errs), errs)
        # 错误消息带「支持: …」词表速查
        self.assertTrue(any("http_request" in e for e in errs), errs)

    def test_cli_run_requires_command(self):
        s = Scenario.from_dict(_scenario(kind="cli", steps=[{"action": "run"}]))
        errs = s.validate()
        self.assertTrue(any("command" in e for e in errs), errs)

    def test_api_http_request_requires_method_and_url(self):
        s = Scenario.from_dict(_scenario(
            kind="api", steps=[{"action": "http_request"}]))
        errs = s.validate()
        self.assertTrue(any("method" in e for e in errs), errs)
        self.assertTrue(any("url" in e for e in errs), errs)

    def test_cli_assertion_required_fields(self):
        s = Scenario.from_dict(_scenario(
            kind="cli",
            steps=[{"action": "run", "command": "true"}],
            assertions=[{"type": "dir_contains"}],
        ))
        errs = s.validate()
        self.assertTrue(any("glob" in e for e in errs), errs)

    def test_web_scenario_without_navigate_rejected(self):
        s = Scenario.from_dict(_scenario(
            steps=[{"action": "wait", "value": "1s"}]))
        errs = s.validate()
        self.assertTrue(any("缺少 navigate" in e for e in errs), errs)
        # 同样缺步骤的 cli 场景不受 navigate 硬要求约束
        s2 = Scenario.from_dict(_scenario(
            kind="cli", steps=[{"action": "run", "command": "true"}]))
        self.assertEqual(s2.validate(), [])


# ── 3. 调度分派与 lazy setup ─────────────────────────────────────

class _RecordingRunner(runner_module.VerifyRunner):
    """测试专用 cli 假 Runner：记录 setup/teardown/execute 调用。"""

    kind = "cli"
    setup_calls = 0
    teardown_calls = 0
    execute_ids = []

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.setup_calls = 0
        self.teardown_calls = 0
        self.execute_ids = []

    def validate(self, scenario):
        return validate_scenario(scenario)

    async def setup(self):
        self.setup_calls += 1

    async def teardown(self):
        self.teardown_calls += 1

    async def execute(self, scenario):
        self.execute_ids.append(scenario.id)
        return {
            "scenario_id": scenario.id,
            "description": scenario.description,
            "status": "pass",
            "step_results": [],
            "assertion_results": [],
            "visual_results": [],
            "screenshots": [],
        }

    async def probe_env(self, candidates):
        return {"healthy": True, "detail": "cli 无降级探针"}


class TestEngineDispatch(unittest.TestCase):
    """引擎按 kind 查注册表分派；仅对实际出现的 kind 执行 setup/teardown。"""

    @classmethod
    def setUpClass(cls):
        cls._orig_cli = runner_module.RUNNER_REGISTRY.get("cli")
        runner_module.RUNNER_REGISTRY["cli"] = _RecordingRunner

    @classmethod
    def tearDownClass(cls):
        if cls._orig_cli is None:
            runner_module.RUNNER_REGISTRY.pop("cli", None)
        else:
            runner_module.RUNNER_REGISTRY["cli"] = cls._orig_cli

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)

    def _engine(self):
        return VerifyEngine("spec-a", self.tmp, mock.MagicMock(), {})

    def test_lazy_setup_cli_only_no_browser(self):
        """纯 cli 场景集：只 setup cli Runner，web Runner 不 setup（零浏览器）。"""
        scenarios = [
            Scenario.from_dict(_scenario(
                "c1", kind="cli", steps=[{"action": "run", "command": "true"}])),
            Scenario.from_dict(_scenario(
                "c2", kind="cli", steps=[{"action": "run", "command": "false"}])),
        ]
        with mock.patch.object(WebRunner, "setup", new=AsyncMock()) as web_setup, \
                mock.patch.object(WebRunner, "teardown", new=AsyncMock()) as web_td:
            engine = self._engine()
            report = asyncio.run(engine.run(scenarios))

        web_setup.assert_not_called()
        web_td.assert_not_called()
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["summary"]["passed"], 2)
        cli_runner = engine._runners["cli"]
        self.assertEqual(cli_runner.setup_calls, 1)
        self.assertEqual(cli_runner.teardown_calls, 1)
        self.assertEqual(cli_runner.execute_ids, ["c1", "c2"])
        # 纯 cli 轮次不启动浏览器：web Runner 从未被创建
        self.assertNotIn("web", engine._runners)
        self.assertIsNone(engine.browser)

    def test_mixed_set_both_runners_setup(self):
        """混合集（web+cli）：两 Runner 都 setup；web 浏览器启一次供全部场景。"""
        scenarios = [
            Scenario.from_dict(_scenario(
                "c1", kind="cli", steps=[{"action": "run", "command": "true"}])),
            Scenario.from_dict(_scenario(
                "w1", steps=[{"action": "navigate", "value": "http://127.0.0.1:9"}]),
            ),
        ]
        web_execute = AsyncMock(return_value={
            "scenario_id": "w1", "description": "", "status": "pass",
            "step_results": [], "assertion_results": [],
            "visual_results": [], "screenshots": [],
        })
        with mock.patch.object(WebRunner, "setup", new=AsyncMock()) as web_setup, \
                mock.patch.object(WebRunner, "teardown", new=AsyncMock()) as web_td, \
                mock.patch.object(WebRunner, "execute", new=web_execute):
            engine = self._engine()
            report = asyncio.run(engine.run(scenarios))

        web_setup.assert_awaited_once()
        web_td.assert_awaited_once()
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(engine._runners["cli"].setup_calls, 1)
        self.assertIsNotNone(engine.browser, "web runner 创建后应暴露浏览器句柄")

    def test_acceptance_failure_no_runner_setup(self):
        """验收失败：不启动任何 Runner、不执行场景，返回带 env_error 空报告。"""
        scenarios = [
            Scenario.from_dict(_scenario(
                "bad", kind="cli",
                steps=[{"action": "run"}],  # 缺 command
            )),
        ]
        with mock.patch.object(WebRunner, "setup", new=AsyncMock()) as web_setup, \
                mock.patch.object(WebRunner, "teardown", new=AsyncMock()):
            engine = self._engine()
            report = asyncio.run(engine.run(scenarios))

        web_setup.assert_not_called()
        self.assertTrue(report.get("env_error"))
        self.assertEqual(report["summary"]["total"], 0)
        # 验收门创建 runner 只为校验；setup 不得执行
        self.assertEqual(engine._runners["cli"].setup_calls, 0)
        self.assertNotIn("web", engine._runners)

    def test_unknown_kind_acceptance_error(self):
        """未知 kind：验收报错打回（不静默按 web 处理）。"""
        scenarios = [
            Scenario.from_dict(_scenario("x", kind="desktop")),
        ]
        engine = self._engine()
        report = asyncio.run(engine.run(scenarios))
        self.assertTrue(report.get("env_error"))
        self.assertIn("desktop", report["env_error"])

    def test_dispatch_by_kind_no_branch(self):
        """调度分派：cli 场景走 cli Runner.execute，web 场景走 web Runner.execute。"""
        scenarios = [
            Scenario.from_dict(_scenario(
                "c1", kind="cli", steps=[{"action": "run", "command": "true"}])),
            Scenario.from_dict(_scenario(
                "w1", steps=[{"action": "navigate", "value": "http://127.0.0.1:9"}]),
            ),
        ]
        web_execute = AsyncMock(return_value={
            "scenario_id": "w1", "description": "", "status": "pass",
            "step_results": [], "assertion_results": [],
            "visual_results": [], "screenshots": [],
        })
        with mock.patch.object(WebRunner, "setup", new=AsyncMock()), \
                mock.patch.object(WebRunner, "teardown", new=AsyncMock()), \
                mock.patch.object(WebRunner, "execute", new=web_execute):
            engine = self._engine()
            asyncio.run(engine.run(scenarios))

        web_execute.assert_awaited_once()
        self.assertEqual(web_execute.await_args.args[0].id, "w1")
        self.assertEqual(engine._runners["cli"].execute_ids, ["c1"])

    def test_runner_setup_failure_is_env_error(self):
        """Runner setup 失败（依赖缺失等）＝验证环境错误，不判 bug-found。"""
        class BoomRunner(_RecordingRunner):
            async def setup(self):
                raise RuntimeError("httpx 不可用")

        runner_module.RUNNER_REGISTRY["cli"] = BoomRunner
        try:
            scenarios = [
                Scenario.from_dict(_scenario(
                    "c1", kind="cli", steps=[{"action": "run", "command": "true"}])),
            ]
            engine = self._engine()
            report = asyncio.run(engine.run(scenarios))
            self.assertTrue(report.get("env_error"))
            self.assertIn("cli", report["env_error"])
        finally:
            runner_module.RUNNER_REGISTRY["cli"] = _RecordingRunner


if __name__ == "__main__":
    unittest.main()