"""agent.harness 配置面测试（add-harness-adapter-layer 6.5）。

覆盖 tasks.md 6.5 三场景 + 热更新语义：
- 缺省：无配置 / 空 agent 段 / 空串 → claude（零行为变化基线）
- 非法值回退：回退缺省 + 告警日志（不静默、不抛异常——配置面容错）
- dsh fail-fast：工厂抛 HarnessNotDeployedError「dsh adapter 未部署」；
  dispatch 前置健康检查拦截派发（不启动进程、不进 inner、不耗预算）；
  settings 保存路径（config_admin.write_config）拒绝 dsh 落盘
- 热更新：dispatch 现读现配——同 runner 实例配置被改后下次 dispatch 用新值；
  在飞 run 持旧 adapter 引用不受影响（set_current_adapter 换新不 inplace 改旧）
"""

from pathlib import Path
import logging
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import yaml

from core.agent_runner.harness import (
    VALID_HARNESS_VALUES,
    ClaudeAdapter,
    HarnessNotDeployedError,
    get_current_adapter,
    resolve_adapter,
    resolve_adapter_from_config,
    set_current_adapter,
)
from core.config import ConfigLoader


class TestHarnessDefault(unittest.TestCase):
    """缺省场景：任何未配置形态都回 claude（变更前行为）。"""

    def test_empty_config(self):
        self.assertEqual(ConfigLoader.get_harness({}), "claude")

    def test_missing_agent_section(self):
        self.assertEqual(ConfigLoader.get_harness({"agents": {"models": {}}}), "claude")

    def test_empty_and_whitespace_values(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                self.assertEqual(
                    ConfigLoader.get_harness({"agent": {"harness": raw}}), "claude")

    def test_value_normalization(self):
        self.assertEqual(
            ConfigLoader.get_harness({"agent": {"harness": " CLAUDE "}}), "claude")
        self.assertEqual(
            ConfigLoader.get_harness({"agent": {"harness": "DSH"}}), "dsh")

    def test_vocab_single_source(self):
        self.assertEqual(VALID_HARNESS_VALUES, ("claude", "dsh"))


class TestHarnessIllegalFallback(unittest.TestCase):
    """非法值：回退缺省 + 告警日志（配置面容错，不抛异常）。"""

    def test_falls_back_to_claude_with_warning(self):
        with self.assertLogs("fenixd.config", level=logging.WARNING) as captured:
            got = ConfigLoader.get_harness({"agent": {"harness": "bash"}})
        self.assertEqual(got, "claude")
        joined = "\n".join(captured.output)
        self.assertIn("bash", joined)
        self.assertIn("claude/dsh", joined)

    def test_factory_rejects_unknown_value(self):
        # 工厂侧不做容错（归一化语义在 ConfigLoader）：未知值 fail-fast
        with self.assertRaises(ValueError):
            resolve_adapter("bash")


class TestDshFailFast(unittest.TestCase):
    """dsh 未部署阶段 fail-fast：工厂 / dispatch 健康检查 / settings 保存三面。"""

    def test_factory_raises_not_deployed(self):
        with self.assertRaises(HarnessNotDeployedError) as ctx:
            resolve_adapter("dsh")
        self.assertIn("dsh adapter 未部署", str(ctx.exception))
        self.assertIn("add-dsh-adapter-integration", str(ctx.exception))

    def test_factory_claude_returns_adapter(self):
        self.assertIsInstance(resolve_adapter("claude"), ClaudeAdapter)

    def test_resolve_from_config_dsh(self):
        with self.assertRaises(HarnessNotDeployedError):
            resolve_adapter_from_config({"agent": {"harness": "dsh"}})

    def test_resolve_from_config_default(self):
        self.assertIsInstance(resolve_adapter_from_config({}), ClaudeAdapter)


class _RunnerBase(unittest.TestCase):
    """AgentRunner 最小装配（同 test_interaction_contract 基线形态）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="harness-cfg-")
        self.proot = Path(self.tmpdir)
        from core.agent_runner import AgentRunner
        wm = MagicMock()
        sm = MagicMock()
        sm.read_one.return_value = None
        self.runner = AgentRunner({"agent": {"harness": "dsh"}}, wm, sm, self.proot,
                                  MagicMock())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestDispatchHealthCheck(_RunnerBase):
    """dispatch 前置健康检查：dsh 拒派且零副作用。"""

    def test_dsh_config_blocks_dispatch_without_spawning(self):
        with patch("subprocess.Popen") as popen, \
                patch.object(self.runner, "_execute_agent_inner") as inner:
            result = self.runner._execute_agent("demo-spec", "implementer", "run-1")
        self.assertFalse(result.success)
        self.assertIn("dsh adapter 未部署", result.error or "")
        self.assertEqual(result.duration_seconds, 0.0)
        # 零副作用：不启动进程、不进执行内核（不建 worktree / 不耗 spec 预算）
        popen.assert_not_called()
        inner.assert_not_called()

    def test_heat_reload_new_value_applies_next_dispatch(self):
        # 现读现配：同一 runner 实例的 config dict 被改后，下次 dispatch 走新值
        with patch.object(self.runner, "_execute_agent_inner") as inner:
            blocked = self.runner._execute_agent("demo-spec", "implementer", "run-1")
            self.assertFalse(blocked.success)
            inner.assert_not_called()

            self.runner.config["agent"]["harness"] = "claude"
            self.runner._execute_agent("demo-spec", "implementer", "run-2")
            inner.assert_called_once()

    def test_inflight_run_keeps_old_adapter_reference(self):
        # 在飞不受影响：set_current_adapter 换新实例，不 inplace 改旧——
        # 在飞 run 在 _run_agent 开头捕获的旧 adapter 引用继续可用
        old = get_current_adapter()
        try:
            fresh = ClaudeAdapter()
            set_current_adapter(fresh)
            self.assertIsNot(get_current_adapter(), old)
            # 旧实例引用仍自洽（识别 patterns 可用）
            self.assertTrue(old.process_patterns())
        finally:
            # 还原进程级持有，避免泄漏到其他测试
            set_current_adapter(old)


class TestSettingsWriteGate(unittest.TestCase):
    """settings 保存路径（config_admin.write_config）：dsh / 非法值被拦。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="harness-wcfg-")
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir()
        (self.root / ".fenix" / "config.yaml").write_text(
            yaml.safe_dump({"agents": {"models": {}}}))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dsh_write_rejected(self):
        from core.dashboard.data import config_admin
        r = config_admin.write_config(self.root, {"agent": {"harness": "dsh"}},
                                      scope="project")
        self.assertFalse(r["ok"])
        self.assertIn("未部署", r["error"])
        # 未落盘
        on_disk = yaml.safe_load((self.root / ".fenix" / "config.yaml").read_text())
        self.assertNotIn("agent", on_disk)

    def test_illegal_value_rejected(self):
        from core.dashboard.data import config_admin
        r = config_admin.write_config(self.root, {"agent": {"harness": "bash"}},
                                      scope="project")
        self.assertFalse(r["ok"])
        self.assertIn("claude/dsh", r["error"])

    def test_claude_write_persists(self):
        from core.dashboard.data import config_admin
        r = config_admin.write_config(self.root, {"agent": {"harness": "claude"}},
                                      scope="project")
        self.assertTrue(r["ok"], r.get("error"))
        on_disk = yaml.safe_load((self.root / ".fenix" / "config.yaml").read_text())
        self.assertEqual(on_disk.get("agent"), {"harness": "claude"})


if __name__ == "__main__":
    unittest.main()
