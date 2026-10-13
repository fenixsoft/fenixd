"""agent.harness 配置面测试（add-harness-adapter-layer 6.5）。

覆盖 tasks.md 6.5 三场景 + 热更新语义：
- 缺省：无配置 / 空 agent 段 / 空串 → claude（零行为变化基线）
- 非法值回退：回退缺省 + 告警日志（不静默、不抛异常——配置面容错）
- dsh 生命周期（add-dsh-adapter-integration 后）：工厂注册 DshAdapter
  （解除 SPEC-1 未部署 fail-fast）；dispatch 前置健康检查不通过拦截派发
  （不启动进程、不进 inner、不耗预算、错误含修复指引）；settings 保存路径
  （config_admin.write_config）允许 dsh 落盘
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
    DshAdapter,
    HarnessHealthError,
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


class TestDshLifecycle(unittest.TestCase):
    """dsh 生命周期：工厂注册（5.1 解除 SPEC-1 fail-fast）/ dispatch 健康
    检查拦截 / settings 保存面。"""

    def test_factory_dsh_registered(self):
        # add-dsh-adapter-integration 5.1：工厂注册 DshAdapter（就绪性由
        # dispatch 前置健康检查把关，工厂本体不做 IO 探测）；MUST NOT 静默
        # 回退 claude 代跑。
        adapter = resolve_adapter("dsh")
        self.assertIsInstance(adapter, DshAdapter)
        self.assertEqual(adapter.name, "dsh")
        self.assertNotIsInstance(adapter, ClaudeAdapter)

    def test_factory_claude_returns_adapter(self):
        self.assertIsInstance(resolve_adapter("claude"), ClaudeAdapter)

    def test_resolve_from_config_dsh(self):
        adapter = resolve_adapter_from_config({"agent": {"harness": "dsh"}})
        self.assertIsInstance(adapter, DshAdapter)

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
    """dispatch 前置健康检查：健康检查不通过拒派且零副作用（5.1/5.2）。"""

    def test_dsh_health_check_blocks_dispatch_without_spawning(self):
        # add-dsh-adapter-integration 5.1：dsh 就绪性由健康检查把关——检查
        # 不通过（版本不符/未挂载 Bundle）fail-fast 拒派，错误含修复指引，
        # MUST NOT 静默回退 claude 代跑。
        with patch("subprocess.Popen") as popen, \
                patch.object(DshAdapter, "check_health",
                             side_effect=HarnessHealthError(
                                 "dsh 版本 '0.9.9' 不在兼容白名单 "
                                 "['0.2.0-rc.2']——请安装 0.2.0-rc.2，或将 "
                                 "agent.harness 改回 claude")), \
                patch.object(self.runner, "_execute_agent_inner") as inner:
            result = self.runner._execute_agent("demo-spec", "implementer", "run-1")
        self.assertFalse(result.success)
        self.assertIn("白名单", result.error or "")
        self.assertIn("claude", result.error or "")
        self.assertEqual(result.duration_seconds, 0.0)
        # 零副作用：不启动进程、不进执行内核（不建 worktree / 不耗 spec 预算）
        popen.assert_not_called()
        inner.assert_not_called()

    def test_dsh_healthy_check_passes_dispatch_to_inner(self):
        # 健康检查通过 → dispatch 放行进执行内核（全链走 DshAdapter，不回退）
        prev_adapter = get_current_adapter()
        try:
            with patch.object(DshAdapter, "check_health", return_value=None) as hc, \
                    patch.object(self.runner, "_execute_agent_inner") as inner:
                self.runner._execute_agent("demo-spec", "implementer", "run-1")
            hc.assert_called_once()
            inner.assert_called_once()
            self.assertIsInstance(get_current_adapter(), DshAdapter)
        finally:
            # _execute_agent 装配的是进程级当前 adapter：不还原会把 DshAdapter
            # 泄漏给同进程后续直调 _run_agent 的用例（get_current_adapter 的
            # claude 惰性回退被顶掉 → DshSpawnConfigError，2026-10-14 回归实证）
            set_current_adapter(prev_adapter)

    def test_heat_reload_new_value_applies_next_dispatch(self):
        # 现读现配：同一 runner 实例的 config dict 被改后，下次 dispatch 走新值。
        # dsh 健康门用受控失败替身——本机装有健康 dsh（版本在白名单）时真实
        # 检查会放行，首派发直入 inner，assertFalse 前提失效（2026-10-14 回归
        # 实证）；替身同时保证本用例不 touch 进程级 adapter。
        with patch.object(DshAdapter, "check_health",
                          side_effect=HarnessHealthError("受控失败：健康门替身")), \
                patch.object(self.runner, "_execute_agent_inner") as inner:
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

    def test_dsh_write_persists(self):
        # add-dsh-adapter-integration 交付后：DshAdapter 已注册，dsh 按词表
        # 放行落盘（就绪性由 dispatch 前置健康检查把关，不再此处拦截）
        from core.dashboard.data import config_admin
        r = config_admin.write_config(self.root, {"agent": {"harness": "dsh"}},
                                      scope="project")
        self.assertTrue(r["ok"], r.get("error"))
        on_disk = yaml.safe_load((self.root / ".fenix" / "config.yaml").read_text())
        self.assertEqual(on_disk.get("agent"), {"harness": "dsh"})

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
