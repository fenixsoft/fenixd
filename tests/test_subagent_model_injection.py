"""tests/test_subagent_model_injection.py — fix-agent-lane-efficiency D1：子代理模型注入测试。

断言直连 provider 时隔离 settings 含 provider 模型映射、配置键覆盖生效、
默认网关路径零写入，且已存在旧 settings.json 时新映射仍生效（幂等重建路径）。
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))


def _make_runner(tmp_path: Path, config: dict | None = None):
    """构建一个最小化的 AgentRunner 实例，仅保留 _build_isolated_settings 测试所需字段。"""
    if config is None:
        config = {}
    runner = MagicMock()
    runner.project_root = tmp_path
    runner.config = config
    runner._build_isolated_settings = __import__(
        "core.agent_runner.runner", fromlist=["AgentRunner"]
    ).AgentRunner._build_isolated_settings.__get__(runner)
    runner._ensure_agent_config_dir = __import__(
        "core.agent_runner.runner", fromlist=["AgentRunner"]
    ).AgentRunner._ensure_agent_config_dir.__get__(runner)
    runner.ISOLATED_SETTINGS_SCHEMA_VERSION = __import__(
        "core.agent_runner.runner", fromlist=["AgentRunner"]
    ).AgentRunner.ISOLATED_SETTINGS_SCHEMA_VERSION
    return runner


class TestSubagentModelInjection:
    """直连 provider 时隔离 settings.json 含子代理模型映射。"""

    def test_direct_provider_env_mapping(self, tmp_path):
        """Scenario: 直连 provider 时子代理模型被映射到 provider 模型。"""
        runner = _make_runner(tmp_path)
        settings = runner._build_isolated_settings("deepseek-v4-flash")
        env = settings.get("env") or {}
        assert env.get("CLAUDE_CODE_SUBAGENT_MODEL") == "deepseek-v4-flash"
        assert env.get("ANTHROPIC_DEFAULT_OPUS_MODEL") == "deepseek-v4-flash"
        assert env.get("ANTHROPIC_DEFAULT_SONNET_MODEL") == "deepseek-v4-flash"
        assert env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "deepseek-v4-flash"
        # 非陈旧 cc-switch 名
        assert "claude-opus-4-8" not in json.dumps(env)

    def test_override_takes_precedence(self, tmp_path):
        """Scenario: agents.subagent_model_override 非空时覆盖 provider model。"""
        config = {"agents": {"subagent_model_override": "glm-5.3-flash"}}
        runner = _make_runner(tmp_path, config)
        settings = runner._build_isolated_settings("deepseek-v4-flash")
        env = settings.get("env") or {}
        assert env.get("CLAUDE_CODE_SUBAGENT_MODEL") == "glm-5.3-flash"
        assert env.get("ANTHROPIC_DEFAULT_OPUS_MODEL") == "glm-5.3-flash"

    def test_default_gateway_no_env_mapping(self, tmp_path):
        """Scenario: 未分配 provider 车道行为不变（零 env 写入）。"""
        runner = _make_runner(tmp_path)
        settings = runner._build_isolated_settings("")
        assert "env" not in settings

    def test_empty_override_falls_back_to_provider(self, tmp_path):
        """Scenario: override 为空串时退回到 provider model。"""
        config = {"agents": {"subagent_model_override": ""}}
        runner = _make_runner(tmp_path, config)
        settings = runner._build_isolated_settings("deepseek-v4-flash")
        env = settings.get("env") or {}
        assert env.get("CLAUDE_CODE_SUBAGENT_MODEL") == "deepseek-v4-flash"

    def test_whitespace_override_treated_as_empty(self, tmp_path):
        """Scenario: override 为空白串时退回到 provider model。"""
        config = {"agents": {"subagent_model_override": "   "}}
        runner = _make_runner(tmp_path, config)
        settings = runner._build_isolated_settings("deepseek-v4-flash")
        env = settings.get("env") or {}
        assert env.get("CLAUDE_CODE_SUBAGENT_MODEL") == "deepseek-v4-flash"


class TestIdempotentRebuild:
    """已存在的旧 settings.json（无 env 段）被原子重写为含 provider 模型映射。"""

    def test_old_settings_json_rewritten(self, tmp_path):
        """Scenario: 已存在旧 settings.json 被更新。"""
        cfg_dir = tmp_path / ".fenix" / "agent-config" / "testprov"
        cfg_dir.mkdir(parents=True)
        old_settings = {"enabledPlugins": {"superpowers@claude-plugins-official": True}}
        (cfg_dir / "settings.json").write_text(
            json.dumps(old_settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        runner = _make_runner(tmp_path)
        runner._ensure_agent_config_dir("testprov", "deepseek-v4-flash")
        new_content = json.loads((cfg_dir / "settings.json").read_text(encoding="utf-8"))
        assert "env" in new_content
        assert new_content["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "deepseek-v4-flash"
        assert new_content.get("_schema_version") == runner.ISOLATED_SETTINGS_SCHEMA_VERSION

    def test_symlinks_not_destroyed(self, tmp_path):
        """Scenario: 已存在旧 settings.json 被更新时，symlink 不被破坏。"""
        cfg_dir = tmp_path / ".fenix" / "agent-config" / "testprov"
        cfg_dir.mkdir(parents=True)
        old_settings = {"enabledPlugins": {}}
        (cfg_dir / "settings.json").write_text(
            json.dumps(old_settings), encoding="utf-8"
        )
        # 创建一个假的 skills symlink
        skills_dir = tmp_path / "fake_skills"
        skills_dir.mkdir()
        try:
            (cfg_dir / "skills").symlink_to(skills_dir, target_is_directory=True)
        except OSError:
            pytest.skip("symlink not supported in this environment")
        runner = _make_runner(tmp_path)
        runner._ensure_agent_config_dir("testprov", "deepseek-v4-flash")
        assert (cfg_dir / "skills").is_symlink()


class TestConfigKeyConflict:
    """subagent_model_override 为唯一活键；subagent_model 不被读取。"""

    def test_subagent_model_not_fallback(self, tmp_path):
        """Scenario: 配置文件只有 agents.subagent_model（死键），override 返回空串。"""
        config = {"agents": {"subagent_model": "claude-sonnet-5"}}
        runner = _make_runner(tmp_path, config)
        from core.config import ConfigLoader
        assert ConfigLoader.get_subagent_model_override(config) == ""
        settings = runner._build_isolated_settings("deepseek-v4-flash")
        env = settings.get("env") or {}
        assert env.get("CLAUDE_CODE_SUBAGENT_MODEL") == "deepseek-v4-flash"

    def test_override_wins_over_dead_key(self, tmp_path):
        """Scenario: 同时存在 subagent_model（死键）和 subagent_model_override（活键）。"""
        config = {
            "agents": {
                "subagent_model": "claude-sonnet-5",
                "subagent_model_override": "glm-5.3-flash",
            }
        }
        runner = _make_runner(tmp_path, config)
        from core.config import ConfigLoader
        assert ConfigLoader.get_subagent_model_override(config) == "glm-5.3-flash"
        settings = runner._build_isolated_settings("deepseek-v4-flash")
        env = settings.get("env") or {}
        assert env.get("CLAUDE_CODE_SUBAGENT_MODEL") == "glm-5.3-flash"
