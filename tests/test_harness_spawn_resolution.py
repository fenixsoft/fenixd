"""spawn 解析 helper 契约（fix-spawn-attribution-hardening 任务 1.1/D1/A3）。

预检与 spawn-spec 构建消费同一 which 解析单源：win32 替换语义（PATHEXT
shim 绝对路径替换 argv[0]）、解析不到返回 None（fail-fast 路径）、POSIX
分支裸名逐位不变（Linux 零变化硬约束，快照金样本不失配）。
"""

import inspect
import os
from unittest.mock import patch

import pytest

from core.agent_runner.harness import (
    HarnessCliUnavailableError,
    resolve_harness_executable,
    spawn_argv0,
)
from core.platform import api as pal


def _which_none(name):
    return None


class TestResolveHarnessExecutable:
    """解析单源（shutil.which 透传）语义。"""

    def test_resolved_path_passthrough(self, monkeypatch):
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which",
            lambda name: "/usr/local/bin/claude" if name == "claude" else None,
        )
        assert resolve_harness_executable("claude") == "/usr/local/bin/claude"

    def test_unresolved_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which", _which_none)
        assert resolve_harness_executable("claude") is None

    def test_empty_executable_returns_none(self):
        # 防御：空可执行名不进 which（语义 None），不抛
        assert resolve_harness_executable("") is None


class TestSpawnArgv0:
    """spawn argv[0] 替换语义（仅 win32 生效）。"""

    def test_win32_cmd_shim_replaces_argv0(self, monkeypatch):
        # which 按 PATHEXT 解析到 .cmd shim → argv[0] 替换为绝对路径
        monkeypatch.setattr(pal, "IS_WINDOWS", True)
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which",
            lambda name: "C:\\npm\\claude.cmd" if name == "claude" else None,
        )
        assert spawn_argv0("claude") == "C:\\npm\\claude.cmd"

    def test_win32_unresolved_returns_none_fail_fast(self, monkeypatch):
        # 解析不到 → None（调用方走 HARNESS_CLI_UNAVAILABLE_MARKER fail-fast）
        monkeypatch.setattr(pal, "IS_WINDOWS", True)
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which", _which_none)
        assert spawn_argv0("claude") is None

    def test_posix_keeps_bare_name_even_when_unresolved(self, monkeypatch):
        # Linux 逐位不变硬约束：POSIX 分支不替换、不因 which 失败改变
        # spawn 形态（快照金样本逐位不变；可达性由预检层负责）
        monkeypatch.setattr(pal, "IS_WINDOWS", False)
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which", _which_none)
        assert spawn_argv0("claude") == "claude"

    def test_posix_keeps_bare_name_when_resolved(self, monkeypatch):
        monkeypatch.setattr(pal, "IS_WINDOWS", False)
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which",
            lambda name: "/usr/bin/claude",
        )
        assert spawn_argv0("claude") == "claude"


class TestSpawnSpecUsesResolvedArgv0:
    """adapter spawn-spec 构建消费同一 helper（任务 2.1 接线）。"""

    def _fixed_env(self):
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": "/fixture-home",
            "LANG": "C.UTF-8",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }

    def test_posix_spawn_spec_argv0_is_bare_name(self):
        from core.agent_runner.harness.claude_adapter import ClaudeAdapter
        from core.agent_runner.harness.protocol import SpawnRequest

        with patch.dict(os.environ, self._fixed_env(), clear=True):
            spec = ClaudeAdapter().build_spawn_spec(
                SpawnRequest("hi", cwd="/tmp", env_mode="inherit"))
        # POSIX 裸名逐位不变（快照金样本同形）
        assert spec.argv[0] == "claude"

    def test_win32_spawn_spec_argv0_replaced_by_which(self, monkeypatch):
        from core.agent_runner.harness.claude_adapter import ClaudeAdapter
        from core.agent_runner.harness.protocol import SpawnRequest

        monkeypatch.setattr(pal, "IS_WINDOWS", True)
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which",
            lambda name: "C:\\npm\\claude.cmd" if name == "claude" else None,
        )
        with patch.dict(os.environ, self._fixed_env(), clear=True):
            spec = ClaudeAdapter().build_spawn_spec(
                SpawnRequest("hi", cwd="C:\\proj", env_mode="inherit"))
        assert spec.argv[0] == "C:\\npm\\claude.cmd"
        # argv 其余段不受替换影响（-p 首参紧随）
        assert spec.argv[1] == "-p"

    def test_win32_spawn_spec_unresolved_raises_marker_error(
            self, monkeypatch):
        from core.agent_runner.harness import (
            HARNESS_CLI_UNAVAILABLE_MARKER,
        )
        from core.agent_runner.harness.claude_adapter import ClaudeAdapter
        from core.agent_runner.harness.protocol import SpawnRequest

        monkeypatch.setattr(pal, "IS_WINDOWS", True)
        monkeypatch.setattr(
            "core.agent_runner.harness.shutil.which", _which_none)
        with patch.dict(os.environ, self._fixed_env(), clear=True):
            with pytest.raises(HarnessCliUnavailableError) as excinfo:
                ClaudeAdapter().build_spawn_spec(
                    SpawnRequest("hi", cwd="C:\\proj", env_mode="inherit"))
        # fail-fast 消息带既有归因标记（dispatch 持态语义按标记识别）
        assert HARNESS_CLI_UNAVAILABLE_MARKER in str(excinfo.value)


class TestSingleSourceConsumption:
    """预检与 spawn 消费同一 helper（源级接线断言）。"""

    def test_precheck_consumes_same_resolver(self):
        from core.agent_runner.harness import precheck_harness_executable
        src = inspect.getsource(precheck_harness_executable)
        assert "resolve_harness_executable(" in src
        assert "shutil.which" not in src

    def test_spawn_spec_builder_consumes_same_helper(self):
        from core.agent_runner.harness.claude_adapter import ClaudeAdapter
        src = inspect.getsource(ClaudeAdapter.build_spawn_spec)
        assert "spawn_argv0(" in src
