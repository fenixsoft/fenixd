"""
Unit tests for Fenix Loop Engineering Framework core modules.

Run with: python3 -m pytest .fenix/tests/ -v
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add .fenix/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, StateParser, SpecStatus, VALID_TRANSITIONS
from core.config import ConfigLoader


# ═══════════════════════════════════════════════════════════════════
# StateMachine Tests (Task 2.5)
# ═══════════════════════════════════════════════════════════════════

class TestStateParser(unittest.TestCase):
    """Test STATE.md parsing and serialization."""

    def test_parse_single_spec(self):
        content = """# Fenix Project State
## Specs

### add-login
- status: ready
- priority: 1
- created: 2026-08-10T14:00:00+08:00
- updated: 2026-08-11T09:00:00+08:00
- implementer_run: null
- tester_run: null
- branch: null
- error: null
"""
        result = StateParser._parse_content(content)
        self.assertIn("add-login", result)
        self.assertEqual(result["add-login"]["status"], "ready")
        self.assertEqual(result["add-login"]["priority"], 1)
        self.assertIsNone(result["add-login"]["error"])

    def test_parse_multiple_specs(self):
        content = """## Specs

### spec-a
- status: ready
- priority: 1
- created: 2026-01-01T00:00:00Z
- updated: 2026-01-01T00:00:00Z
- implementer_run: null
- tester_run: null
- branch: null
- error: null

### spec-b
- status: done
- priority: 2
- created: 2026-01-02T00:00:00Z
- updated: 2026-01-02T00:00:00Z
- implementer_run: run-001
- tester_run: run-002
- branch: fenix/spec-b
- error: null
"""
        result = StateParser._parse_content(content)
        self.assertEqual(len(result), 2)
        self.assertEqual(result["spec-a"]["status"], "ready")
        self.assertEqual(result["spec-b"]["status"], "done")
        self.assertEqual(result["spec-b"]["branch"], "fenix/spec-b")

    def test_parse_empty_content(self):
        result = StateParser._parse_content("## Specs\n")
        self.assertEqual(result, {})

    def test_parse_null_values(self):
        content = """### test-spec
- status: ready
- priority: 1
- created: 2026-01-01T00:00:00Z
- updated: 2026-01-01T00:00:00Z
- implementer_run: None
- tester_run: null
- branch: none
- error: null
"""
        result = StateParser._parse_content(content)
        self.assertIsNone(result["test-spec"]["implementer_run"])
        self.assertIsNone(result["test-spec"]["tester_run"])

    def test_serialize_roundtrip(self):
        specs = {
            "test-spec": {
                "status": "ready",
                "priority": 3,
                "created": "2026-01-01T00:00:00Z",
                "updated": "2026-01-01T00:00:00Z",
                "implementer_run": None,
                "tester_run": None,
                "branch": None,
                "error": None,
            }
        }
        serialized = StateParser.serialize(specs)
        parsed = StateParser._parse_content(serialized)
        self.assertIn("test-spec", parsed)
        self.assertEqual(parsed["test-spec"]["status"], "ready")
        self.assertEqual(parsed["test-spec"]["priority"], 3)


class TestStateMachine(unittest.TestCase):
    """Test state machine transitions and operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_spec(self):
        self.assertTrue(self.sm.add_spec("test-spec", {"priority": 1}))
        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["status"], "drafted")
        self.assertEqual(spec["priority"], 1)

    def test_add_duplicate_spec(self):
        self.sm.add_spec("test-spec", {})
        self.assertFalse(self.sm.add_spec("test-spec", {}))

    def test_valid_transitions(self):
        self.sm.add_spec("test-spec", {"priority": 1})

        # drafted → ready (auto-review)
        self.assertTrue(self.sm.transition("test-spec", "ready"))
        self.assertEqual(self.sm.read_one("test-spec")["status"], "ready")

        # ready → implementing
        self.assertTrue(self.sm.transition("test-spec", "implementing"))

        # implementing → implemented
        self.assertTrue(self.sm.transition("test-spec", "implemented"))

        # implemented → testing
        self.assertTrue(self.sm.transition("test-spec", "testing"))

        # testing → verified
        self.assertTrue(self.sm.transition("test-spec", "verified"))

        # verified → done
        self.assertTrue(self.sm.transition("test-spec", "done"))

        # done → pushed (terminal)
        self.assertTrue(self.sm.transition("test-spec", "pushed"))

    def test_invalid_transition_rejected(self):
        self.sm.add_spec("test-spec", {})
        # drafted → implementing is invalid (must go through ready)
        self.assertFalse(self.sm.transition("test-spec", "implementing"))
        self.assertEqual(self.sm.read_one("test-spec")["status"], "drafted")

    def test_is_valid_transition(self):
        self.assertTrue(self.sm.is_valid_transition("drafted", "ready"))
        self.assertFalse(self.sm.is_valid_transition("drafted", "implementing"))
        self.assertFalse(self.sm.is_valid_transition("pushed", "done"))  # terminal

    def test_get_by_status(self):
        self.sm.add_spec("spec-a", {"priority": 1, "status": "ready"})
        self.sm.add_spec("spec-b", {"priority": 3, "status": "ready"})
        self.sm.add_spec("spec-c", {"priority": 2, "status": "done"})

        ready = self.sm.get_by_status("ready")
        self.assertEqual(len(ready), 2)
        # spec-a has priority 1, should be first
        self.assertEqual(ready[0][0], "spec-a")
        self.assertEqual(ready[1][0], "spec-b")

    def test_get_next_ready(self):
        self.sm.add_spec("low-prio", {"priority": 5, "status": "ready"})
        self.sm.add_spec("high-prio", {"priority": 1, "status": "ready"})

        next_spec = self.sm.get_next_ready()
        self.assertIsNotNone(next_spec)
        self.assertEqual(next_spec[0], "high-prio")

    def test_get_next_ready_empty(self):
        self.assertIsNone(self.sm.get_next_ready())

    def test_recover_interrupted(self):
        self.sm.add_spec("stuck-impl", {"status": "implementing"})
        self.sm.add_spec("stuck-test", {"status": "testing"})
        self.sm.add_spec("normal", {"status": "done"})

        recovered = self.sm.recover_interrupted()
        self.assertEqual(len(recovered), 2)
        self.assertIn("stuck-impl", recovered)
        self.assertIn("stuck-test", recovered)

        # Both should be back to ready
        self.assertEqual(self.sm.read_one("stuck-impl")["status"], "ready")
        self.assertEqual(self.sm.read_one("stuck-test")["status"], "ready")
        # Normal spec unchanged
        self.assertEqual(self.sm.read_one("normal")["status"], "done")

    def test_update_spec(self):
        self.sm.add_spec("test-spec", {})
        self.assertTrue(self.sm.update_spec("test-spec", {"priority": 1, "branch": "fenix/test"}))
        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["priority"], 1)
        self.assertEqual(spec["branch"], "fenix/test")

    def test_update_nonexistent(self):
        self.assertFalse(self.sm.update_spec("nonexistent", {"status": "ready"}))

    def test_transition_nonexistent(self):
        self.assertFalse(self.sm.transition("nonexistent", "ready"))

    def test_priority_sorting_same_priority(self):
        """Same priority uses created time (earlier first)."""
        self.sm.add_spec("later", {"priority": 3, "created": "2026-02-01T00:00:00Z", "status": "ready"})
        self.sm.add_spec("earlier", {"priority": 3, "created": "2026-01-01T00:00:00Z", "status": "ready"})

        ready = self.sm.get_ready_specs()
        self.assertEqual(ready[0][0], "earlier")
        self.assertEqual(ready[1][0], "later")

    def test_bug_found_path(self):
        """Test the bug-found transition path."""
        self.sm.add_spec("buggy", {"priority": 1})
        self.sm.transition("buggy", "ready")
        self.sm.transition("buggy", "implementing")
        self.sm.transition("buggy", "implemented")
        self.sm.transition("buggy", "testing")
        self.sm.transition("buggy", "bug-found")
        self.assertEqual(self.sm.read_one("buggy")["status"], "bug-found")
        # bug-found → implementing (retry)
        self.assertTrue(self.sm.transition("buggy", "implementing"))


class TestSpecStatus(unittest.TestCase):
    """Test status constants and transition definitions."""

    def test_all_statuses_defined(self):
        self.assertEqual(len(SpecStatus.ALL), 9)

    def test_valid_transitions_cover_all_states(self):
        for status in SpecStatus.ALL:
            self.assertIn(status, VALID_TRANSITIONS)

    def test_pushed_is_terminal(self):
        self.assertEqual(VALID_TRANSITIONS["pushed"], [])

    def test_implementing_can_revert(self):
        self.assertIn("ready", VALID_TRANSITIONS["implementing"])


# ═══════════════════════════════════════════════════════════════════
# Config Tests (Task 12.1 supplementary)
# ═══════════════════════════════════════════════════════════════════

class TestConfigLoader(unittest.TestCase):
    """Test configuration loading and validation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "config.yaml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_config(self, config_dict):
        import yaml
        with open(self.config_path, "w") as f:
            yaml.dump(config_dict, f)

    def test_load_valid_config(self):
        self._write_config({
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": 30, "daily_report_time": "09:00"},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50, "daily_run_limit": 50, "run_timeout_seconds": 1800},
            "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "echo OK", "build": "echo OK", "start": "echo OK"},
            "logging": {"dir": ".fenix/logs", "level": "INFO", "max_size_mb": 10, "backup_count": 5, "retain_days": 30},
        })
        config = ConfigLoader.load(self.config_path)
        self.assertEqual(ConfigLoader.get(config, "project.type"), "web")
        self.assertEqual(ConfigLoader.get(config, "agents.max_turns"), 50)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            ConfigLoader.load(Path("/nonexistent/config.yaml"))

    def test_missing_required_key(self):
        self._write_config({"project": {"name": "test"}})
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_invalid_project_type(self):
        self._write_config({
            "project": {"name": "test", "type": "invalid_type"},
            "schedule": {"poll_interval_minutes": 30},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
        })
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_invalid_poll_interval(self):
        self._write_config({
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": -5},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
        })
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_config_get_nested(self):
        self._write_config({
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": 30},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
        })
        config = ConfigLoader.load(self.config_path)
        self.assertEqual(ConfigLoader.get(config, "agents.max_turns"), 50)
        self.assertEqual(ConfigLoader.get(config, "nonexistent.key", "default"), "default")

    def test_max_concurrent_optional_default_when_missing(self):
        """agents.max_concurrent 为可选字段，缺失时加载成功（消费方自行取默认值）。"""
        cfg = self._base_config()
        del cfg["agents"]["max_concurrent"]
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        self.assertNotIn("max_concurrent", config["agents"])

    def test_max_retries_optional_default_when_missing(self):
        """agents.max_retries 为可选字段，缺失时加载成功。"""
        cfg = self._base_config()
        del cfg["agents"]["max_retries"]
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        self.assertNotIn("max_retries", config["agents"])

    def test_max_turns_optional_default_when_missing(self):
        """agents.max_turns 为可选字段，缺失时加载成功。"""
        cfg = self._base_config()
        del cfg["agents"]["max_turns"]
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        self.assertNotIn("max_turns", config["agents"])

    def test_max_concurrent_invalid_zero_rejected(self):
        """agents.max_concurrent 显式为 0 时被拒绝。"""
        cfg = self._base_config()
        cfg["agents"]["max_concurrent"] = 0
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_max_concurrent_invalid_negative_rejected(self):
        """agents.max_concurrent 显式为负数时被拒绝。"""
        cfg = self._base_config()
        cfg["agents"]["max_concurrent"] = -1
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    # ── 新增：llm.providers 校验 ──────────────────────────

    def _base_config(self):
        return {
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": 30},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
        }

    def test_llm_providers_valid(self):
        cfg = self._base_config()
        cfg["llm"] = {
            "providers": [
                {"name": "volc", "baseurl": "https://a.com", "apikey": "sk-1", "model": "m1"},
                {"name": "openrouter", "baseurl": "https://b.com", "apikey": "sk-2", "sdk_model": "claude-sonnet-5"},
            ]
        }
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        providers = ConfigLoader.get(config, "llm.providers", [])
        self.assertEqual(len(providers), 2)
        self.assertEqual(providers[0]["name"], "volc")
        self.assertEqual(providers[1].get("sdk_model"), "claude-sonnet-5")

    def test_llm_providers_not_list_raises(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": "not_a_list"}
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_llm_providers_missing_apikey_raises(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [{"name": "p1", "baseurl": "https://a.com"}]}
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_llm_providers_duplicate_name_raises(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "p1", "baseurl": "https://a.com", "apikey": "k1"},
            {"name": "p1", "baseurl": "https://b.com", "apikey": "k2"},
        ]}
        self._write_config(cfg)
        with self.assertRaises(ValueError) as ctx:
            ConfigLoader.load(self.config_path)
        self.assertIn("unique", str(ctx.exception))

    def test_llm_providers_absent_is_okay(self):
        """旧配置无 llm 段应正常加载（向后兼容）。"""
        self._write_config(self._base_config())
        config = ConfigLoader.load(self.config_path)
        self.assertIsNone(ConfigLoader.get(config, "llm.providers"))

    def test_llm_providers_env_valid(self):
        """provider 可携带自定义 env 字典（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS），应通过校验并完整读回。"""
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1",
             "env": {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000", "ANTHROPIC_TIMEOUT": "120"}},
        ]}
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        providers = ConfigLoader.get(config, "llm.providers", [])
        self.assertEqual(providers[0]["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "1000000")
        self.assertEqual(providers[0]["env"]["ANTHROPIC_TIMEOUT"], "120")

    def test_llm_providers_env_not_dict_raises(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1", "env": "oops"},
        ]}
        self._write_config(cfg)
        with self.assertRaises(ValueError) as ctx:
            ConfigLoader.load(self.config_path)
        self.assertIn("env", str(ctx.exception))

    def test_llm_providers_env_non_string_value_raises(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1",
             "env": {"MAX_CONTEXT": 1000000}},
        ]}
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    # ── 新增：agents.models 校验 ──────────────────────────

    def test_agent_models_valid(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": "volc", "model": "deepseek-v4-flash"},
            "planner-plan": {"provider": "volc", "model": "deepseek-v4-pro"},
        }
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        self.assertEqual(
            ConfigLoader.get(config, "agents.models.implementer.provider"),
            "volc"
        )

    def test_agent_models_unknown_provider_raises(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": "nonexistent", "model": "m1"},
        }
        self._write_config(cfg)
        with self.assertRaises(ValueError) as ctx:
            ConfigLoader.load(self.config_path)
        self.assertIn("unknown provider", str(ctx.exception))

    def test_agent_models_unknown_agent_type_raises(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1"},
        ]}
        cfg["agents"]["models"] = {
            "super-agent": {"provider": "volc", "model": "m1"},
        }
        self._write_config(cfg)
        with self.assertRaises(ValueError) as ctx:
            ConfigLoader.load(self.config_path)
        self.assertIn("known agent type", str(ctx.exception))

    def test_agent_models_empty_model_raises(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": "volc", "model": ""},
        }
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_agent_models_absent_is_okay(self):
        """未配置 agents.models 时应正常加载（向后兼容）。"""
        self._write_config(self._base_config())
        config = ConfigLoader.load(self.config_path)
        self.assertIsNone(ConfigLoader.get(config, "agents.models"))

    # ── 新增：approve_mode 校验 ────────────────────────────

    def test_approve_mode_manual_valid(self):
        cfg = self._base_config()
        cfg["gates"]["approve_mode"] = "manual"
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        self.assertEqual(ConfigLoader.get(config, "gates.approve_mode"), "manual")

    def test_approve_mode_auto_valid(self):
        cfg = self._base_config()
        cfg["gates"]["approve_mode"] = "auto"
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        self.assertEqual(ConfigLoader.get(config, "gates.approve_mode"), "auto")

    def test_approve_mode_invalid_raises(self):
        cfg = self._base_config()
        cfg["gates"]["approve_mode"] = "always"
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_approve_mode_default_manual(self):
        """未配置 approve_mode 时 get_approve_mode 应返回 'manual'。"""
        self._write_config(self._base_config())
        config = ConfigLoader.load(self.config_path)
        self.assertEqual(ConfigLoader.get_approve_mode(config), "manual")

    # ── 新增：get_agent_model_assignment ────────────────────

    def test_get_agent_model_assignment_returns_tuple(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1", "sdk_model": "claude-sonnet-5"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": "volc", "model": "deepseek-v4-flash"},
        }
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        self.assertIsNotNone(result)
        provider, model = result
        self.assertEqual(provider["name"], "volc")
        self.assertEqual(provider["baseurl"], "https://a.com")
        self.assertEqual(model, "deepseek-v4-flash")

    def test_get_agent_model_assignment_unassigned_returns_none(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": "volc", "model": "m1"},
        }
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        # planner-judge 未分配
        self.assertIsNone(ConfigLoader.get_agent_model_assignment(config, "planner-judge"))

    def test_get_agent_model_assignment_no_models_section(self):
        self._write_config(self._base_config())
        config = ConfigLoader.load(self.config_path)
        self.assertIsNone(ConfigLoader.get_agent_model_assignment(config, "implementer"))


# ═══════════════════════════════════════════════════════════════════
# Agent Runner Model Routing Tests
# ═══════════════════════════════════════════════════════════════════

class TestAgentRunnerModelRouting(unittest.TestCase):
    """测试 AgentRunner 的模型分配与 env 注入逻辑。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_runner(self, config: dict):
        from core.agent_runner import AgentRunner
        logger = MagicMock()
        logger.info = MagicMock()
        logger.warning = MagicMock()
        logger.error = MagicMock()
        logger.debug = MagicMock()
        wm = MagicMock()
        wm.create = MagicMock(return_value=self.project_root)
        wm.cleanup = MagicMock()
        wm.find_implementer_worktree = MagicMock(return_value=None)
        sm = MagicMock()
        return AgentRunner(config, wm, sm, self.project_root, logger)

    def test_get_agent_model_assignment_assigned(self):
        config = {
            "llm": {"providers": [
                {"name": "volc", "baseurl": "https://api.example.com", "apikey": "sk-test", "sdk_model": "claude-sonnet-5"},
            ]},
            "agents": {
                "max_concurrent": 2, "max_retries": 1, "max_turns": 50,
                "models": {"implementer": {"provider": "volc", "model": "deepseek-v4-flash"}},
            },
        }
        runner = self._make_runner(config)
        result = runner._get_agent_model_assignment("implementer")
        self.assertIsNotNone(result)
        provider, model = result
        self.assertEqual(provider["baseurl"], "https://api.example.com")
        self.assertEqual(provider["apikey"], "sk-test")
        self.assertEqual(model, "deepseek-v4-flash")

    def test_get_agent_model_assignment_unassigned(self):
        config = {"agents": {"max_concurrent": 2, "max_retries": 1, "max_turns": 50}}
        runner = self._make_runner(config)
        result = runner._get_agent_model_assignment("planner-judge")
        self.assertIsNone(result)

    def test_run_claude_env_overrides_per_call(self):
        """验证 _run_claude 每次调用使用独立 env 副本，多 agent_type 不串扰。"""
        config = {
            "llm": {"providers": [
                {"name": "p1", "baseurl": "https://a.com", "apikey": "key-a"},
                {"name": "p2", "baseurl": "https://b.com", "apikey": "key-b"},
            ]},
            "agents": {
                "max_concurrent": 2, "max_retries": 1, "max_turns": 50, "run_timeout_seconds": 10,
                "models": {
                    "implementer": {"provider": "p1", "model": "model-a"},
                    "planner-judge": {"provider": "p2", "model": "model-b"},
                },
                "subagent_model": "claude-sonnet-5",
            },
        }
        runner = self._make_runner(config)
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["env"] = dict(kwargs.get("env", {}))
            fake = MagicMock()
            fake.stdout = []
            fake.stderr = []
            fake.wait = MagicMock(return_value=0)
            fake.kill = MagicMock()
            return fake

        with patch("core.agent_runner.subprocess.Popen", side_effect=fake_popen):
            try:
                runner._run_claude("test prompt", self.project_root, "test-run-1",
                                   "claude-sonnet-5",
                                   {"ANTHROPIC_BASE_URL": "https://a.com",
                                    "ANTHROPIC_API_KEY": "key-a",
                                    "ANTHROPIC_MODEL": "model-a"})
            except Exception:
                pass

        self.assertEqual(captured["env"]["ANTHROPIC_BASE_URL"], "https://a.com")
        self.assertEqual(captured["env"]["ANTHROPIC_API_KEY"], "key-a")
        self.assertEqual(captured["env"]["ANTHROPIC_MODEL"], "model-a")

    def test_run_agent_injects_provider_env(self):
        """provider.env 自定义参数（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）应合并进 env_overrides。"""
        config = {
            "llm": {"providers": [
                {"name": "p1", "baseurl": "https://a.com", "apikey": "key-a",
                 "env": {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000"}},
            ]},
            "agents": {
                "max_concurrent": 2, "max_retries": 1, "max_turns": 50,
                "models": {"implementer": {"provider": "p1", "model": "model-a"}},
                "subagent_model": "claude-sonnet-5",
            },
        }
        runner = self._make_runner(config)
        runner._build_prompt = MagicMock(return_value="test prompt")
        runner._run_claude = MagicMock(return_value=("ok", 1))
        result = runner.run_implementer("test-spec")
        self.assertTrue(result.success)
        # _run_claude(prompt, cwd, run_id, model_override, env_overrides) —— env_overrides 是第 5 个位置参数
        env = runner._run_claude.call_args.args[4]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://a.com")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "key-a")
        self.assertEqual(env["ANTHROPIC_MODEL"], "model-a")
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "1000000")


# ═══════════════════════════════════════════════════════════════════
# Auto-Approve Tests
# ═══════════════════════════════════════════════════════════════════

class TestAutoApprove(unittest.TestCase):
    """测试 pm_engine 自动审批逻辑。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()

        # 初始化 git repo
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / "README.md").write_text("# test\n")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)

        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "done", "branch": "fenix/test-spec"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()
        self.sm.get_by_status = MagicMock(return_value={})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config: dict):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        logger.info = MagicMock()
        logger.warning = MagicMock()
        logger.error = MagicMock()
        logger.debug = MagicMock()
        ar = MagicMock()
        return PMEngine(self.sm, ar, config, self.project_root, logger)

    def test_get_approve_mode_default_manual(self):
        engine = self._make_engine({})
        self.assertEqual(engine._get_approve_mode(), "manual")

    def test_get_approve_mode_auto(self):
        engine = self._make_engine({"gates": {"approve_mode": "auto"}})
        self.assertEqual(engine._get_approve_mode(), "auto")

    def test_resolve_push_branch_from_state(self):
        engine = self._make_engine({})
        spec = {"branch": "fenix/custom-branch"}
        self.assertEqual(engine._resolve_push_branch("test-spec", spec), "fenix/custom-branch")

    def test_resolve_push_branch_default_prefix(self):
        engine = self._make_engine({"worktree": {"implement_branch_prefix": "fenix"}})
        self.assertEqual(engine._resolve_push_branch("test-spec", {}), "fenix/test-spec")

    def test_auto_approve_pushed_state_skips(self):
        """已处于 pushed 状态的 SPEC 不重复触发，直接返回 True。"""
        self.sm.read_one = MagicMock(return_value={"status": "pushed"})
        engine = self._make_engine({"gates": {"approve_mode": "auto"}})
        result = engine._auto_approve("test-spec")
        self.assertTrue(result)
        self.sm.transition.assert_not_called()

    def test_auto_approve_non_done_state_skips(self):
        """非 done 状态的 SPEC 不触发自动推送。"""
        self.sm.read_one = MagicMock(return_value={"status": "ready"})
        engine = self._make_engine({"gates": {"approve_mode": "auto"}})
        result = engine._auto_approve("test-spec")
        self.assertFalse(result)
        self.sm.transition.assert_not_called()

    def test_git_push_failure_returns_false(self):
        """推送不存在的远端应返回失败。"""
        engine = self._make_engine({})
        success, error = engine._git_push_branch("nonexistent-branch")
        self.assertFalse(success)
        self.assertTrue(len(error) > 0)

    def test_approve_push_success_transitions_to_pushed(self):
        """mock 成功推送后 transition 到 pushed。"""
        engine = self._make_engine({})
        self.sm.read_one = MagicMock(return_value={"status": "done"})
        with patch.object(engine, '_git_push_branch', return_value=(True, "")):
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            self.sm.transition.assert_called_once_with("test-spec", "pushed")

    def test_approve_push_failure_updates_error(self):
        """推送失败时不推进状态，但记录 error。"""
        engine = self._make_engine({})
        self.sm.read_one = MagicMock(return_value={"status": "done"})
        with patch.object(engine, '_git_push_branch', return_value=(False, "remote rejected")):
            result = engine.approve_push("test-spec")
            self.assertFalse(result)
            self.sm.transition.assert_not_called()
            self.sm.update_spec.assert_called_once()
            update_args = self.sm.update_spec.call_args[0]
            self.assertIn("error", update_args[1])
            self.assertIn("remote rejected", update_args[1]["error"])

    def test_on_spec_done_auto_mode_triggers_approve(self):
        """auto 模式下 _on_spec_done 应调用 _auto_approve。"""
        self.sm.read_one = MagicMock(return_value={"status": "done"})
        self.sm.read_all = MagicMock(return_value={"test-spec": {"status": "pushed"}})
        engine = self._make_engine({"gates": {"approve_mode": "auto"}})
        with patch.object(engine, '_auto_approve') as mock_approve:
            engine._on_spec_done("test-spec")
            mock_approve.assert_called_once_with("test-spec")

    def test_on_spec_done_manual_mode_skips(self):
        """manual 模式下 _on_spec_done 不调用 _auto_approve。"""
        self.sm.read_one = MagicMock(return_value={"status": "done"})
        self.sm.read_all = MagicMock(return_value={"test-spec": {"status": "pushed"}})
        engine = self._make_engine({"gates": {"approve_mode": "manual"}})
        with patch.object(engine, '_auto_approve') as mock_approve:
            engine._on_spec_done("test-spec")
            mock_approve.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# Dashboard Config I/O Tests
# ═══════════════════════════════════════════════════════════════════

class TestDashboardConfigIO(unittest.TestCase):
    """测试 dashboard data.py 中的配置读写。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_config_empty_returns_defaults(self):
        from core.dashboard.data import read_config
        result = read_config(self.project_root)
        self.assertFalse(result["raw_exists"])
        self.assertEqual(result["llm"], {})
        self.assertEqual(result["agents"], {"models": {}, "max_concurrent": 2})
        self.assertEqual(result["gates"], {"approve_mode": "manual"})

    def test_write_and_read_roundtrip(self):
        from core.dashboard.data import write_config, read_config
        patch = {
            "llm": {"providers": [
                {"name": "volc", "baseurl": "https://api.example.com",
                 "apikey": "sk-test", "model": "deepseek-v4-flash"},
            ]},
            "agents": {"models": {
                "implementer": {"provider": "volc", "model": "deepseek-v4-pro"},
            }},
            "gates": {"approve_mode": "auto"},
        }
        result = write_config(self.project_root, patch)
        self.assertTrue(result["ok"], result.get("error"))
        readback = read_config(self.project_root)
        self.assertTrue(readback["raw_exists"])
        self.assertEqual(len(readback["llm"]["providers"]), 1)
        self.assertEqual(readback["llm"]["providers"][0]["name"], "volc")
        self.assertEqual(readback["agents"]["models"]["implementer"]["provider"], "volc")
        self.assertEqual(readback["gates"]["approve_mode"], "auto")

    def test_write_preserves_non_managed_keys(self):
        """写入受管键时不应影响项目内的其他配置键。"""
        import yaml
        from core.dashboard.data import write_config
        config_path = self.project_root / ".fenix" / "config.yaml"
        full_config = {
            "project": {"name": "myproj", "type": "web"},
            "schedule": {"poll_interval_minutes": 30},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "gates": {"require_push_approval": True, "approve_mode": "manual"},
            "logging": {"dir": ".fenix/logs", "level": "INFO"},
        }
        with open(config_path, "w") as f:
            yaml.safe_dump(full_config, f)
        result = write_config(self.project_root, {"gates": {"approve_mode": "auto"}})
        self.assertTrue(result["ok"], result.get("error"))
        with open(config_path, "r") as f:
            updated = yaml.safe_load(f)
        self.assertEqual(updated["project"]["name"], "myproj")
        self.assertEqual(updated["schedule"]["poll_interval_minutes"], 30)
        self.assertEqual(updated["agents"]["max_concurrent"], 2)
        self.assertEqual(updated["gates"]["require_push_approval"], True)
        self.assertEqual(updated["gates"]["approve_mode"], "auto")
        self.assertIn("logging", updated)

    def test_write_validation_rejects_duplicate_provider(self):
        from core.dashboard.data import write_config
        bad_patch = {"llm": {"providers": [
            {"name": "dup", "baseurl": "https://a.com", "apikey": "k1"},
            {"name": "dup", "baseurl": "https://b.com", "apikey": "k2"},
        ]}}
        result = write_config(self.project_root, bad_patch)
        self.assertFalse(result["ok"])
        self.assertIn("unique", result["error"] or "")

    def test_write_atomic_no_partial_write(self):
        """校验失败时文件内容保持不变。"""
        import yaml
        from core.dashboard.data import write_config
        config_path = self.project_root / ".fenix" / "config.yaml"
        original = {"project": {"name": "orig", "type": "web"},
                    "gates": {"approve_mode": "manual"}}
        with open(config_path, "w") as f:
            yaml.safe_dump(original, f)
        bad_patch = {"gates": {"approve_mode": "invalid_mode"}}
        result = write_config(self.project_root, bad_patch)
        self.assertFalse(result["ok"])
        with open(config_path, "r") as f:
            after = yaml.safe_load(f)
        self.assertEqual(after["project"]["name"], "orig")
        self.assertEqual(after["gates"]["approve_mode"], "manual")


# ═══════════════════════════════════════════════════════════════════
# Agent Runner Tests (Task 5.6)
# ═══════════════════════════════════════════════════════════════════

class TestAgentRunResult(unittest.TestCase):
    """Test AgentRunResult data class."""

    def test_result_creation(self):
        from core.agent_runner import AgentRunResult
        result = AgentRunResult(
            run_id="test-001",
            spec_name="test-spec",
            agent_type="implementer",
            success=True,
            duration_seconds=42.5,
            turns_used=15,
            output="All tasks complete",
        )
        d = result.to_dict()
        self.assertEqual(d["run_id"], "test-001")
        self.assertEqual(d["success"], True)
        self.assertEqual(d["duration_seconds"], 42.5)

    def test_failed_result(self):
        from core.agent_runner import AgentRunResult
        result = AgentRunResult(
            run_id="test-002",
            spec_name="test-spec",
            agent_type="verifier",
            success=False,
            duration_seconds=10.0,
            error="Bug found: login redirect broken",
        )
        d = result.to_dict()
        self.assertEqual(d["success"], False)
        self.assertEqual(d["error"], "Bug found: login redirect broken")


# ═══════════════════════════════════════════════════════════════════
# Agent Runner Streaming Tests (agent-run-artifacts, tasks 1.1-1.4)
# ═══════════════════════════════════════════════════════════════════

class _FakeProc:
    """Minimal stand-in for subprocess.Popen: line streams + wait/kill."""

    def __init__(self, stdout_lines=(), stderr_lines=(), returncode=0, timeout=False):
        import io
        self.stdout = io.StringIO("\n".join(stdout_lines) + "\n")
        self.stderr = io.StringIO("\n".join(stderr_lines) + "\n")
        self._returncode = returncode
        self._timeout = timeout

    def wait(self, timeout=None):
        if self._timeout:
            raise subprocess.TimeoutExpired("claude", timeout)
        return self._returncode

    def kill(self):
        pass


class TestRunClaudeStreaming(unittest.TestCase):
    """_run_claude 流式落盘兼容性（agent-run-artifacts 1.1-1.4）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.config = {"agents": {"run_timeout_seconds": 5}}
        self.logger = MagicMock()
        from core.agent_runner import AgentRunner
        self.runner = AgentRunner(
            self.config, MagicMock(), MagicMock(), self.project_root, self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _artifact(self, run_id):
        return self.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"

    def _run(self, run_id, stdout_lines=(), stderr_lines=(), returncode=0, timeout=False):
        proc = _FakeProc(stdout_lines, stderr_lines, returncode, timeout)
        with patch("subprocess.Popen", return_value=proc):
            return self.runner._run_claude("prompt", Path(self.tmpdir), run_id)

    def test_normal_completion_restores_output_and_turns(self):
        run_id = "impl-demo-spec-1700000000"
        result_event = {
            "type": "result", "subtype": "success", "is_error": False,
            "result": "All tasks complete", "num_turns": 7, "session_id": "sess-1",
        }
        stdout = [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}}),
            json.dumps(result_event),
        ]
        output, turns = self._run(run_id, stdout_lines=stdout)
        self.assertEqual(output, "All tasks complete")
        self.assertEqual(turns, 7)
        artifact = self._artifact(run_id)
        self.assertTrue(artifact.exists())
        lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        self.assertEqual(lines[-1]["type"], "result")
        self.assertEqual(lines[-1]["num_turns"], 7)

    def test_timeout_writes_error_terminal_and_raises(self):
        run_id = "impl-hang-spec-1700000001"
        with self.assertRaises(RuntimeError):
            self._run(run_id, stdout_lines=[json.dumps({"type": "assistant", "message": {}})], timeout=True)
        artifact = self._artifact(run_id)
        lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        self.assertEqual(lines[-1]["type"], "error")
        self.assertIn("Timeout", lines[-1]["error"])

    def test_nonzero_exit_writes_error_and_raises(self):
        run_id = "impl-fail-spec-1700000002"
        with self.assertRaises(RuntimeError) as ctx:
            self._run(run_id, stderr_lines=["boom"], returncode=1)
        self.assertIn("boom", str(ctx.exception))
        artifact = self._artifact(run_id)
        lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        self.assertEqual(lines[-1]["type"], "error")
        self.assertEqual(lines[-1]["exit_code"], 1)

    def test_stderr_noise_fallback_parseable(self):
        run_id = "impl-noise-spec-1700000003"
        result_event = {"type": "result", "subtype": "success", "result": "ok", "num_turns": 2}
        stdout = [
            json.dumps({"type": "assistant", "message": {"content": []}}),
            json.dumps(result_event),
        ]
        output, turns = self._run(run_id, stdout_lines=stdout, stderr_lines=["non-json noise"])
        self.assertEqual(output, "ok")
        artifact = self._artifact(run_id)
        lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        self.assertTrue(any(
            l.get("type") == "stderr" and l.get("line") == "non-json noise" for l in lines
        ))
        # 文件整体仍可逐行 JSON 解析，且最后一行是 result
        self.assertEqual(lines[-1]["type"], "result")

    def test_running_artifact_grows_in_real_time(self):
        """运行期间产物文件实时增长：进程阻塞时文件已含已产生的事件。"""
        import threading as _t

        release = _t.Event()

        class BlockingProc(_FakeProc):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.wait_called = _t.Event()

            def wait(self, timeout=None):
                self.wait_called.set()
                if not release.wait(timeout or 10):
                    raise subprocess.TimeoutExpired("claude", timeout)
                return 0

        run_id = "impl-live-spec-1700000004"
        result_event = {"type": "result", "subtype": "success", "result": "done", "num_turns": 1}
        proc = BlockingProc(stdout_lines=[
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}}),
            json.dumps(result_event),
        ])
        results = {}

        def target():
            with patch("subprocess.Popen", return_value=proc):
                results["ret"] = self.runner._run_claude("prompt", Path(self.tmpdir), run_id)

        t = _t.Thread(target=target)
        t.start()
        self.assertTrue(proc.wait_called.wait(5))
        artifact = self._artifact(run_id)
        for _ in range(50):
            if artifact.exists() and artifact.read_text().strip():
                break
            time.sleep(0.05)
        first_lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        # 进程仍在运行（wait 未返回）时，产物文件已包含已产生的事件
        self.assertTrue(any(l.get("type") == "assistant" for l in first_lines))
        release.set()
        t.join(timeout=5)
        self.assertEqual(results["ret"][0], "done")

    def test_clean_old_runs_keeps_latest(self):
        from core.agent_runner import clean_old_runs
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        for i in range(25):
            p = runs_dir / f"run-{i}.jsonl"
            p.write_text("{}")
            os.utime(p, (i, i))
        removed = clean_old_runs(runs_dir, keep=20)
        self.assertEqual(removed, 5)
        self.assertEqual(len(list(runs_dir.glob("*.jsonl"))), 20)

    def test_clean_old_runs_skips_active(self):
        from core.agent_runner import clean_old_runs
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        for i in range(25):
            p = runs_dir / f"run-{i}.jsonl"
            p.write_text("{}")
            os.utime(p, (i, i))
        # run-24 最旧但处于活动状态 → 被排除在候选外（24 个候选，保留 20，删 4）
        removed = clean_old_runs(runs_dir, keep=20, active_ids={"run-24"})
        self.assertEqual(removed, 4)
        self.assertTrue((runs_dir / "run-24.jsonl").exists())


# ═══════════════════════════════════════════════════════════════════
# Logger Tests (Task 11.1 supplementary)
# ═══════════════════════════════════════════════════════════════════

class TestLogger(unittest.TestCase):
    """Test structured logger."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_dir = Path(self.tmpdir)
        from core.logger import Logger
        self.logger = Logger(self.log_dir, "DEBUG")

    def tearDown(self):
        self.logger.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_log_writes_json(self):
        self.logger.info("test_component", "Test message", {"key": "value"})
        log_file = self.log_dir / "fenixd.log"
        self.assertTrue(log_file.exists())

        with open(log_file) as f:
            lines = f.readlines()
        self.assertGreater(len(lines), 0)

        entry = json.loads(lines[0])
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["component"], "test_component")
        self.assertEqual(entry["message"], "Test message")
        self.assertEqual(entry["context"], {"key": "value"})

    def test_log_levels(self):
        self.logger.debug("c", "debug msg")
        self.logger.info("c", "info msg")
        self.logger.warning("c", "warn msg")
        self.logger.error("c", "error msg")

        log_file = self.log_dir / "fenixd.log"
        with open(log_file) as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 4)

    def test_tail(self):
        for i in range(10):
            self.logger.info("test", f"message {i}")
        entries = self.logger.tail(5)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[-1]["message"], "message 9")


# ═══════════════════════════════════════════════════════════════════
# EventBus Tests (Task 3.5)
# ═══════════════════════════════════════════════════════════════════

class TestEventBus(unittest.TestCase):
    """Test event bus status-to-event mapping."""

    def test_status_to_event_mapping(self):
        from core.event_bus import EventBus
        self.assertEqual(EventBus._status_to_event("ready"), "spec_ready")
        self.assertEqual(EventBus._status_to_event("implemented"), "spec_implemented")
        self.assertEqual(EventBus._status_to_event("verified"), "spec_verified")
        self.assertEqual(EventBus._status_to_event("bug-found"), "spec_bug_found")
        self.assertEqual(EventBus._status_to_event("done"), "spec_done")
        self.assertEqual(EventBus._status_to_event("drafted"), "spec_drafted")
        self.assertEqual(EventBus._status_to_event("unknown"), "")


class TestPMEngineBugFound(unittest.TestCase):
    """Test bug-found → fix SPEC creation logic (multi-round fix)."""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_buggy_spec(self, name="quick-links-folders"):
        """Create a spec stuck in bug-found state."""
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")
        self.sm.transition(name, "bug-found")

    def test_resolve_fix_name_none_exists(self):
        self.assertEqual(
            self.engine._resolve_fix_spec_name("quick-links-folders"),
            "fix-quick-links-folders",
        )

    def test_resolve_fix_name_fix_done(self):
        self.sm.add_spec("fix-quick-links-folders", {"status": "done", "priority": 6})
        self.assertEqual(
            self.engine._resolve_fix_spec_name("quick-links-folders"),
            "fix-fix-quick-links-folders",
        )

    def test_resolve_fix_name_fix_done_twice(self):
        # 两轮 fix 均已 done → 递归到第三轮
        self.sm.add_spec("fix-quick-links-folders", {"status": "done", "priority": 6})
        self.sm.add_spec("fix-fix-quick-links-folders", {"status": "done", "priority": 7})
        self.assertEqual(
            self.engine._resolve_fix_spec_name("quick-links-folders"),
            "fix-fix-fix-quick-links-folders",
        )

    def test_resolve_fix_name_in_progress(self):
        # 进行中的 fix SPEC → 返回 None（重复派发，跳过）
        self.sm.add_spec("fix-quick-links-folders", {"status": "testing", "priority": 6})
        self.assertIsNone(self.engine._resolve_fix_spec_name("quick-links-folders"))

    def test_bug_found_creates_second_fix_when_first_done(self):
        # 核心回归：原 SPEC 重新验证仍失败，而第一轮 fix 已 done
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {"status": "done", "priority": 6})

        self.engine._do_spec_bug_found("quick-links-folders")

        # 应创建第二轮 fix SPEC
        fix2 = self.sm.read_one("fix-fix-quick-links-folders")
        self.assertIsNotNone(fix2)
        self.assertEqual(fix2["status"], "ready")
        # 原 SPEC 应回到 implementing（而非卡在 bug-found）
        self.assertEqual(self.sm.read_one("quick-links-folders")["status"], "implementing")
        # 第二轮 fix 应被排队（队列条目结构：(priority, spec_name, agent_type)）
        queued_specs = [(e[1], e[2]) for e in self.engine._run_queue]
        self.assertIn(("fix-fix-quick-links-folders", "implementer"), queued_specs)

    def test_bug_found_writes_fix_spec_files(self):
        # 回归：fix SPEC 必须同时在磁盘上生成 proposal.md / tasks.md，
        # 否则 implementer Agent 找不到 SPEC 文件而卡在 implementing。
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {"status": "done", "priority": 6})

        self.engine._do_spec_bug_found("quick-links-folders")

        spec_dir = Path(self.tmpdir) / "openspec" / "changes" / "fix-fix-quick-links-folders"
        proposal_path = spec_dir / "proposal.md"
        tasks_path = spec_dir / "tasks.md"
        self.assertTrue(proposal_path.exists(), "proposal.md 未生成")
        self.assertTrue(tasks_path.exists(), "tasks.md 未生成")
        self.assertIn("quick-links-folders", proposal_path.read_text(encoding="utf-8"))
        self.assertIn("- [ ] 1.1", tasks_path.read_text(encoding="utf-8"))

    def test_bug_found_resets_reusable_fix(self):
        # fix SPEC 处于可重置状态（bug-found）→ 复用而非新建
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {"status": "bug-found", "priority": 6})

        self.engine._do_spec_bug_found("quick-links-folders")

        # 不应创建 fix-fix
        self.assertIsNone(self.sm.read_one("fix-fix-quick-links-folders"))
        # fix-quick-links-folders 应重置为 ready
        self.assertEqual(self.sm.read_one("fix-quick-links-folders")["status"], "ready")

    def test_bug_found_not_skipped_when_handle_event_guard_present(self):
        # 回归：handle_event 在调用 handler 前会 add ("spec_bug_found", name) 到
        # _handling_events。若 _on_spec_bug_found 复用同一 key，会被错误跳过。
        # 修复后 _on_spec_bug_found 用独立 key，不应被跳过。
        self._make_buggy_spec("quick-links-folders")
        self.engine._handling_events.add(("spec_bug_found", "quick-links-folders"))
        try:
            self.engine._on_spec_bug_found("quick-links-folders")
        finally:
            self.engine._handling_events.discard(("spec_bug_found", "quick-links-folders"))

        # 不应被防重入跳过：应创建 fix SPEC 并把原 SPEC 转回 implementing
        self.assertIsNotNone(self.sm.read_one("fix-quick-links-folders"))
        self.assertEqual(self.sm.read_one("quick-links-folders")["status"], "implementing")



# ═══════════════════════════════════════════════════════════════════
# Priority Parallel Scheduler Tests (add-parallelism)
# ═══════════════════════════════════════════════════════════════════

class TestPriorityScheduler(unittest.TestCase):
    """测试严格优先级并行调度器（pm_engine._process_queue）。

    通过 mock state_machine 与拦截线程启动来验证派发顺序与并行度。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        self.logger.info = MagicMock()
        self.logger.warning = MagicMock()
        self.logger.error = MagicMock()
        self.logger.debug = MagicMock()

        self.sm = MagicMock()
        self.agent_runner = MagicMock()
        self.config = {"agents": {"max_concurrent": 2}}
        self.engine = PMEngine(
            self.sm, self.agent_runner, self.config,
            self.project_root, self.logger,
        )

        # 拦截 worker 线程启动：不真的运行，只记录派发的条目
        self.dispatched = []  # [(priority, spec_name, agent_type)]
        self._orig_thread_start = threading.Thread.start

        def fake_start(thread_self):
            name = thread_self.name
            # 只记录 fenix worker 线程，跳过测试辅助线程
            if not name.startswith("fenix-"):
                # 对非 fenix 线程，调用真正的 start
                self._orig_thread_start(thread_self)
                return
            # 从 thread name 反推：fenix-{agent_type}-{spec_name}
            parts = name.split("-", 2)  # ["fenix", agent_type, spec_name]
            agent_type = parts[1]
            spec_name = parts[2]
            # 从 _active_priorities 推断（不变量：只含一个值）
            with self.engine._queue_lock:
                prios = list(self.engine._active_priorities)
            priority = prios[0] if prios else 5
            self.dispatched.append((priority, spec_name, agent_type))

        threading.Thread.start = fake_start

    def tearDown(self):
        threading.Thread.start = self._orig_thread_start
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_specs(self, specs):
        """设置 mock state_machine 的 read_one 返回值。

        specs: {spec_name: {"status": ..., "priority": ...}}
        """
        def read_one(name):
            return specs.get(name)
        self.sm.read_one = MagicMock(side_effect=read_one)

    def test_high_priority_dispatches_first(self):
        """高低优先级同时就绪时，高优先级先派发（P1 先于 P5）。"""
        self._set_specs({
            "spec-a": {"status": "ready", "priority": 1},
            "spec-b": {"status": "ready", "priority": 5},
        })
        self.sm.transition = MagicMock(return_value=True)

        # 入队（低的先入，高的后入，验证调度器不按 FIFO）
        self.engine._enqueue("spec-b", "implementer")  # P5
        self.engine._enqueue("spec-a", "implementer")  # P1

        self.engine._process_queue()

        # 并行度 2，但不同优先级不并行——应该只派发 P1
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.dispatched[0][1], "spec-a")
        self.assertEqual(self.dispatched[0][0], 1)

    def test_same_priority_parallel(self):
        """同优先级任务并行至并行度上限。"""
        self._set_specs({
            "spec-a": {"status": "ready", "priority": 3},
            "spec-b": {"status": "ready", "priority": 3},
            "spec-c": {"status": "ready", "priority": 3},
        })
        self.sm.transition = MagicMock(return_value=True)

        self.engine._enqueue("spec-a", "implementer")
        self.engine._enqueue("spec-b", "implementer")
        self.engine._enqueue("spec-c", "implementer")

        self.engine._process_queue()

        # 并行度 2 → 应该派发 2 个同优先级任务
        self.assertEqual(len(self.dispatched), 2)
        self.assertEqual(self.dispatched[0][0], 3)
        self.assertEqual(self.dispatched[1][0], 3)
        names = [d[1] for d in self.dispatched]
        self.assertIn("spec-a", names)
        self.assertIn("spec-b", names)
        # spec-c 还在队列里
        queued_specs = [e[1] for e in self.engine._run_queue]
        self.assertIn("spec-c", queued_specs)

    def test_different_priority_no_parallel(self):
        """不同优先级不并行：有高优先级运行时，即使有空槽也不派发低优先级。"""
        self._set_specs({
            "spec-high": {"status": "ready", "priority": 1},
            "spec-low": {"status": "ready", "priority": 5},
        })
        self.sm.transition = MagicMock(return_value=True)

        # 先手动设置一个 P1 正在运行（模拟场景）
        with self.engine._queue_lock:
            self.engine._active_runs = 1
            self.engine._active_priorities.add(1)

        # 队列里有 P5 就绪任务
        self.engine._enqueue("spec-low", "implementer")

        self.engine._process_queue()

        # 不应派发 P5（尽管有空闲槽位）
        self.assertEqual(len(self.dispatched), 0)
        self.assertEqual(self.engine._active_runs, 1)

    def test_same_bucket_fills_idle_slot(self):
        """同档任务在运行期间允许补齐并行度。"""
        self._set_specs({
            "spec-a": {"status": "ready", "priority": 2},
            "spec-b": {"status": "ready", "priority": 2},
        })
        self.sm.transition = MagicMock(return_value=True)

        # P2 已有 1 个在运行，1 个槽位空闲
        with self.engine._queue_lock:
            self.engine._active_runs = 1
            self.engine._active_priorities.add(2)

        self.engine._enqueue("spec-b", "implementer")

        self.engine._process_queue()

        # 同 P2 档应补齐空闲槽位
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.dispatched[0][1], "spec-b")
        self.assertEqual(self.dispatched[0][0], 2)

    def test_high_priority_no_preempt(self):
        """高优先级到达不抢占正在运行的低优先级，且期间不派发新的低优先级任务。

        严格优先级语义：当有更高优先级任务在队列中等待时，即使当前运行档
        （低优先级）有空闲槽位，也不再派发新的低优先级同档任务，
        以避免高优先级任务被不必要地延迟。
        """
        self._set_specs({
            "spec-low-running": {"status": "implementing", "priority": 5},
            "spec-high": {"status": "ready", "priority": 1},
            "spec-low2": {"status": "ready", "priority": 5},
        })
        self.sm.transition = MagicMock(return_value=True)

        # P5 已有 1 个在运行
        with self.engine._queue_lock:
            self.engine._active_runs = 1
            self.engine._active_priorities.add(5)

        # P1 和另一个 P5 都就绪
        self.engine._enqueue("spec-high", "implementer")  # P1
        self.engine._enqueue("spec-low2", "implementer")   # P5

        self.engine._process_queue()

        # 不应派发任何新任务：
        # - 有更高优先级 P1 在队列中等待 → 不再派发 P5 档的新任务
        # - 不抢占已在运行的 P5 任务（仍保持运行）
        self.assertEqual(len(self.dispatched), 0)
        self.assertEqual(self.engine._active_runs, 1)
        self.assertEqual(self.engine._active_priorities, {5})

        # spec-high 和 spec-low2 都仍在队列等待
        queued_specs = [e[1] for e in self.engine._run_queue]
        self.assertIn("spec-high", queued_specs)
        self.assertIn("spec-low2", queued_specs)

    def test_all_same_priority_fifo_parallel(self):
        """全部同优先级时按入队顺序并行，等价于 FIFO + 并发上限。"""
        self._set_specs({
            "spec-1": {"status": "ready", "priority": 5},
            "spec-2": {"status": "ready", "priority": 5},
            "spec-3": {"status": "ready", "priority": 5},
        })
        self.sm.transition = MagicMock(return_value=True)

        # 按 1, 2, 3 顺序入队
        self.engine._enqueue("spec-1", "implementer")
        self.engine._enqueue("spec-2", "implementer")
        self.engine._enqueue("spec-3", "implementer")

        self.engine._process_queue()

        # 并行度 2 → 前两个先派发，按入队顺序
        self.assertEqual(len(self.dispatched), 2)
        self.assertEqual(self.dispatched[0][1], "spec-1")
        self.assertEqual(self.dispatched[1][1], "spec-2")

    def test_max_concurrent_not_exceeded(self):
        """并行度上限不被突破。"""
        self._set_specs({
            f"spec-{i}": {"status": "ready", "priority": 3}
            for i in range(5)
        })
        self.sm.transition = MagicMock(return_value=True)

        for i in range(5):
            self.engine._enqueue(f"spec-{i}", "implementer")

        self.engine._process_queue()

        self.assertEqual(len(self.dispatched), 2)
        self.assertEqual(self.engine._active_runs, 2)

    def test_default_priority_is_5(self):
        """SPEC 无 priority 字段时，默认按 priority=5 处理。"""
        self._set_specs({
            "spec-high": {"status": "ready", "priority": 1},
            "spec-no-prio": {"status": "ready"},  # 无 priority 字段
        })
        self.sm.transition = MagicMock(return_value=True)

        self.engine._enqueue("spec-no-prio", "implementer")
        self.engine._enqueue("spec-high", "implementer")

        self.engine._process_queue()

        # 应只派发 P1（高优先级），spec-no-prio 默认 P5 不派发
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.dispatched[0][1], "spec-high")

    def test_verifier_immediately_after_implementer_same_bucket(self):
        """verifier 紧随 implementer 派发——同档 FCFS 顺序不回退。

        verifier 通过 _enqueue_front 入队，应在同一 priority 档内紧接
        implementer 之后（或同档最前面），保证验证顺序。
        """
        self._set_specs({
            "spec-a": {"status": "implemented", "priority": 3},
            "spec-b": {"status": "ready", "priority": 3},
            "spec-c": {"status": "ready", "priority": 3},
        })
        self.sm.transition = MagicMock(return_value=True)

        # spec-b 和 spec-c 的 implementer 先入队
        self.engine._enqueue("spec-b", "implementer")  # P3
        self.engine._enqueue("spec-c", "implementer")  # P3

        # 然后 spec-a 的 implementer 完成，verifier 通过 _enqueue_front 入队
        self.engine._enqueue_front("spec-a", "verifier")  # P3, 插到同档前面

        # 并行度 2，一次派发 2 个
        self.engine._process_queue()

        self.assertEqual(len(self.dispatched), 2)
        # verifier 应该被最先派发（因为 _enqueue_front 插到同档前面）
        self.assertEqual(self.dispatched[0][1], "spec-a")
        self.assertEqual(self.dispatched[0][2], "verifier")
        # 第二个是 spec-b
        self.assertEqual(self.dispatched[1][1], "spec-b")
        self.assertEqual(self.dispatched[1][2], "implementer")

    def test_invalid_status_entries_skipped(self):
        """状态不合法的队列条目被跳过（implementer 非 ready / verifier 非 implemented）。"""
        self._set_specs({
            "spec-bad": {"status": "implementing", "priority": 1},  # implementer 不能从 implementing 启动
            "spec-good": {"status": "ready", "priority": 5},
        })
        self.sm.transition = MagicMock(return_value=True)

        self.engine._enqueue("spec-bad", "implementer")  # P1，但状态不对
        self.engine._enqueue("spec-good", "implementer")  # P5，状态对

        self.engine._process_queue()

        # spec-bad 状态不合法被跳过；P5 是当前最高的合法优先级
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.dispatched[0][1], "spec-good")

    def test_e2e_priority_tiers_serial_and_parallel(self):
        """端到端：高优先级档完成后，低优先级档才启动；档内并行。

        场景：
        - 并行度 2
        - P1: 3 个就绪任务 (a, b, c)
        - P5: 2 个就绪任务 (x, y)
        期望：
        1. 先派发 P1 的 a, b（并行度满）
        2. a 完成 → 释放槽位 → 派发 P1 的 c（同档补齐）
        3. P1 全部完成后 → 派发 P5 的 x, y
        """
        specs = {
            "p1-a": {"status": "ready", "priority": 1},
            "p1-b": {"status": "ready", "priority": 1},
            "p1-c": {"status": "ready", "priority": 1},
            "p5-x": {"status": "ready", "priority": 5},
            "p5-y": {"status": "ready", "priority": 5},
        }
        self._set_specs(specs)
        self.sm.transition = MagicMock(return_value=True)

        # 全部入队（先 P5 后 P1，验证调度器不按 FIFO）
        self.engine._enqueue("p5-x", "implementer")
        self.engine._enqueue("p5-y", "implementer")
        self.engine._enqueue("p1-a", "implementer")
        self.engine._enqueue("p1-b", "implementer")
        self.engine._enqueue("p1-c", "implementer")

        # 第一轮派发：只派 P1 的 2 个（并行度 2）
        self.engine._process_queue()
        self.assertEqual(len(self.dispatched), 2)
        self.assertEqual(self.dispatched[0][0], 1)  # P1
        self.assertEqual(self.dispatched[1][0], 1)  # P1
        names = [d[1] for d in self.dispatched]
        self.assertIn("p1-a", names)
        self.assertIn("p1-b", names)
        self.assertEqual(self.engine._active_runs, 2)
        self.assertEqual(self.engine._active_priorities, {1})

        # 模拟 p1-a 完成（释放一个槽位，并触发 _process_queue）
        # 这模拟 _run_agent_worker 的 finally 块
        with self.engine._queue_lock:
            self.engine._active_runs -= 1
            if self.engine._active_runs == 0:
                self.engine._active_priorities.discard(1)
        self.engine._process_queue()

        # 第二轮：P1 档仍有 1 个在运行（p1-b），同档补齐 → 派发 p1-c
        self.assertEqual(len(self.dispatched), 3)
        self.assertEqual(self.dispatched[2][1], "p1-c")
        self.assertEqual(self.dispatched[2][0], 1)
        self.assertEqual(self.engine._active_runs, 2)

        # 模拟 p1-b 完成
        with self.engine._queue_lock:
            self.engine._active_runs -= 1
            if self.engine._active_runs == 0:
                self.engine._active_priorities.discard(1)
        self.engine._process_queue()

        # 第三轮：P1 档还剩 p1-c 在运行（active_runs=1），
        # 同档无更多就绪 → 本轮不派发（active_priorities={1}，
        # 不会跳到 P5）
        self.assertEqual(len(self.dispatched), 3)
        self.assertEqual(self.engine._active_runs, 1)
        self.assertEqual(self.engine._active_priorities, {1})

        # 模拟 p1-c 完成（P1 档全部排空）
        with self.engine._queue_lock:
            self.engine._active_runs -= 1
            if self.engine._active_runs == 0:
                self.engine._active_priorities.discard(1)
        self.engine._process_queue()

        # P1 全完成 → 开始派发 P5 档（并行度 2，一次派 2 个）
        self.assertEqual(len(self.dispatched), 5)
        self.assertEqual(self.dispatched[3][0], 5)
        self.assertEqual(self.dispatched[4][0], 5)
        p5_names = [d[1] for d in self.dispatched[3:]]
        self.assertIn("p5-x", p5_names)
        self.assertIn("p5-y", p5_names)

    def test_e2e_concurrent_process_queue_thread_safe(self):
        """多线程并发调用 _process_queue 不突破并行度上限。

        模拟多个 worker 同时完成、同时调用 _process_queue 的竞态场景。
        """
        import random

        specs = {f"spec-{i}": {"status": "ready", "priority": 2} for i in range(10)}
        self._set_specs(specs)
        self.sm.transition = MagicMock(return_value=True)

        for i in range(10):
            self.engine._enqueue(f"spec-{i}", "implementer")

        # 用 5 个线程并发调用 _process_queue
        errors = []
        def worker():
            try:
                self.engine._process_queue()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"并发出错: {errors}")
        # 并行度上限 2，active_runs 不应超过 2
        self.assertLessEqual(self.engine._active_runs, 2)
        # 总共派发了 2 个（并行度上限）
        self.assertEqual(len(self.dispatched), 2)


# ═══════════════════════════════════════════════════════════════════
# Dashboard Parallelism Config Tests (add-parallelism)
# ═══════════════════════════════════════════════════════════════════

class TestDashboardParallelismConfig(unittest.TestCase):
    """测试 Dashboard 配置中并行度（agents.max_concurrent）的读写。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_config_includes_max_concurrent(self):
        """read_config 应返回 agents.max_concurrent。"""
        import yaml
        from core.dashboard.data import read_config
        config_path = self.project_root / ".fenix" / "config.yaml"
        full_config = {
            "project": {"name": "p", "type": "web"},
            "agents": {"max_concurrent": 4, "max_retries": 3, "max_turns": 50},
        }
        with open(config_path, "w") as f:
            yaml.safe_dump(full_config, f)
        result = read_config(self.project_root)
        self.assertEqual(result["agents"]["max_concurrent"], 4)
        # models 也应存在（默认空）
        self.assertIn("models", result["agents"])

    def test_write_max_concurrent_preserves_other_agents_keys(self):
        """写并行度后 agents 下其它子键（subagent_model/max_retries/max_turns）保持不变。"""
        import yaml
        from core.dashboard.data import write_config
        config_path = self.project_root / ".fenix" / "config.yaml"
        original = {
            "project": {"name": "p", "type": "web"},
            "agents": {
                "max_concurrent": 2,
                "max_retries": 3,
                "max_turns": 50,
                "subagent_model": "claude-sonnet-5",
            },
            "llm": {"providers": [{"name": "p1", "baseurl": "https://a.com", "apikey": "k1"}]},
            "gates": {"approve_mode": "manual", "require_push_approval": True},
        }
        with open(config_path, "w") as f:
            yaml.safe_dump(original, f)

        result = write_config(self.project_root, {
            "agents": {"max_concurrent": 6},
        })
        self.assertTrue(result["ok"], result.get("error"))

        with open(config_path, "r") as f:
            updated = yaml.safe_load(f)
        # 并行度被更新
        self.assertEqual(updated["agents"]["max_concurrent"], 6)
        # 其它 agents 子键不变
        self.assertEqual(updated["agents"]["max_retries"], 3)
        self.assertEqual(updated["agents"]["max_turns"], 50)
        self.assertEqual(updated["agents"]["subagent_model"], "claude-sonnet-5")
        # llm 不变
        self.assertEqual(len(updated["llm"]["providers"]), 1)
        # gates 不变
        self.assertEqual(updated["gates"]["approve_mode"], "manual")
        self.assertEqual(updated["gates"]["require_push_approval"], True)

    def test_write_invalid_max_concurrent_rejected(self):
        """非法并行度（非正整数）POST 返回失败且不写盘。"""
        import yaml
        from core.dashboard.data import write_config
        config_path = self.project_root / ".fenix" / "config.yaml"
        original = {"agents": {"max_concurrent": 2}}
        with open(config_path, "w") as f:
            yaml.safe_dump(original, f)

        # 0 — 非法
        result = write_config(self.project_root, {"agents": {"max_concurrent": 0}})
        self.assertFalse(result["ok"])
        self.assertIn("max_concurrent", result["error"] or "")

        with open(config_path, "r") as f:
            after = yaml.safe_load(f)
        self.assertEqual(after["agents"]["max_concurrent"], 2)

    def test_write_negative_max_concurrent_rejected(self):
        """负数并行度被拒绝。"""
        from core.dashboard.data import write_config
        result = write_config(self.project_root, {"agents": {"max_concurrent": -1}})
        self.assertFalse(result["ok"])

    def test_write_max_concurrent_roundtrip(self):
        """并行度写后读回一致。"""
        from core.dashboard.data import write_config, read_config
        result = write_config(self.project_root, {
            "agents": {"max_concurrent": 8},
            "gates": {"approve_mode": "auto"},
        })
        self.assertTrue(result["ok"], result.get("error"))
        readback = read_config(self.project_root)
        self.assertEqual(readback["agents"]["max_concurrent"], 8)
        self.assertEqual(readback["gates"]["approve_mode"], "auto")

    def test_max_concurrent_default_when_missing(self):
        """配置文件无 max_concurrent 时 read_config 返回默认值 2。"""
        import yaml
        from core.dashboard.data import read_config
        config_path = self.project_root / ".fenix" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.safe_dump({"agents": {"max_retries": 3}}, f)
        result = read_config(self.project_root)
        self.assertEqual(result["agents"]["max_concurrent"], 2)


# ═══════════════════════════════════════════════════════════════════
# Dashboard SPEC 列表表格化测试（add-dashboard-spec-table）
# ═══════════════════════════════════════════════════════════════════

class TestSpecSummaryCreatedUpdated(unittest.TestCase):
    """spec_summary 应暴露 created/updated 字段（缺失为 None）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_spec_summary_includes_created_and_updated(self):
        from core.dashboard.data import spec_summary
        entry = {
            "status": "ready",
            "priority": 2,
            "created": "2026-08-10T14:00:00+08:00",
            "updated": "2026-08-11T09:00:00+08:00",
            "error": None,
        }
        result = spec_summary(str(self.project_root), "test-spec", entry)
        self.assertEqual(result["created"], "2026-08-10T14:00:00+08:00")
        self.assertEqual(result["updated"], "2026-08-11T09:00:00+08:00")
        self.assertIn("name", result)
        self.assertIn("status", result)

    def test_spec_summary_missing_created_returns_none(self):
        from core.dashboard.data import spec_summary
        entry = {
            "status": "drafted",
            "priority": 3,
            "error": None,
        }
        result = spec_summary(str(self.project_root), "old-spec", entry)
        self.assertIsNone(result["created"])
        self.assertIsNone(result["updated"])


class TestApiSpecsSortOrder(unittest.TestCase):
    """/api/specs 按 created 倒序（新在前），缺失 created 排最后。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / "openspec" / "changes").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_state(self, specs_text):
        state_path = self.project_root / "STATE.md"
        state_path.write_text("## Specs\n\n" + specs_text, encoding="utf-8")

    def _get_specs_sorted(self):
        """调用 _api_specs 的排序逻辑（通过 parse_state + spec_summary + sort）。"""
        from core.dashboard import data as dashboard_data
        specs = dashboard_data.parse_state(str(self.project_root))
        items = [
            dashboard_data.spec_summary(str(self.project_root), name, entry)
            for name, entry in specs.items()
        ]
        # 与 server.py 中相同的排序
        items.sort(key=lambda s: s.get("created") or "", reverse=True)
        return [s["name"] for s in items]

    def test_sorted_by_created_descending(self):
        self._write_state("""
### old-spec
- status: done
- priority: 1
- created: 2026-01-01T00:00:00Z
- updated: 2026-01-01T00:00:00Z
- error: null

### newest-spec
- status: implementing
- priority: 2
- created: 2026-08-10T00:00:00Z
- updated: 2026-08-10T00:00:00Z
- error: null

### middle-spec
- status: ready
- priority: 3
- created: 2026-05-01T00:00:00Z
- updated: 2026-05-01T00:00:00Z
- error: null
""")
        names = self._get_specs_sorted()
        self.assertEqual(names, ["newest-spec", "middle-spec", "old-spec"])

    def test_missing_created_sorted_last(self):
        self._write_state("""
### has-created
- status: ready
- priority: 1
- created: 2026-06-01T00:00:00Z
- updated: 2026-06-01T00:00:00Z
- error: null

### no-created
- status: done
- priority: 2
- error: null
""")
        names = self._get_specs_sorted()
        self.assertEqual(names[0], "has-created")
        self.assertEqual(names[-1], "no-created")

    def test_all_missing_created_stable(self):
        self._write_state("""
### spec-a
- status: ready
- priority: 1
- error: null

### spec-b
- status: done
- priority: 2
- error: null
""")
        names = self._get_specs_sorted()
        self.assertEqual(len(names), 2)


# ═══════════════════════════════════════════════════════════════════
# Worktree CWD & Merge-Back Tests (fix-worktree-agent-cwd)
# ═══════════════════════════════════════════════════════════════════

class TestRunClaudeCwd(unittest.TestCase):
    """_run_claude 的 Popen 应传入 cwd=worktree 路径（修复 implementer 不在 worktree 工作的 Bug）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.config = {"agents": {"run_timeout_seconds": 5}}
        self.logger = MagicMock()
        from core.agent_runner import AgentRunner
        self.runner = AgentRunner(
            self.config, MagicMock(), MagicMock(), self.project_root, self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_popen_receives_cwd_equal_to_worktree(self):
        """Popen 调用时 cwd 参数应等于传入的 worktree 路径。"""
        captured = {}
        wt_path = Path(self.tmpdir) / "impl-test-spec-1234567890"
        wt_path.mkdir(parents=True, exist_ok=True)

        def fake_popen(cmd, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            fake = MagicMock()
            fake.stdout = []
            fake.stderr = []
            fake.wait = MagicMock(return_value=0)
            fake.kill = MagicMock()
            return fake

        with patch("core.agent_runner.subprocess.Popen", side_effect=fake_popen):
            try:
                self.runner._run_claude("test prompt", wt_path, "test-run-cwd")
            except Exception:
                pass

        self.assertIn("cwd", captured)
        self.assertEqual(captured["cwd"], str(wt_path))

    def test_popen_cwd_is_not_project_root(self):
        """cwd 应该是 worktree 路径，不是 project_root（回归原 Bug：子进程继承 daemon cwd）。"""
        captured = {}
        wt_path = Path(self.tmpdir) / "impl-test-abc-9999999999"
        wt_path.mkdir(parents=True, exist_ok=True)

        def fake_popen(cmd, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            fake = MagicMock()
            fake.stdout = []
            fake.stderr = []
            fake.wait = MagicMock(return_value=0)
            fake.kill = MagicMock()
            return fake

        with patch("core.agent_runner.subprocess.Popen", side_effect=fake_popen):
            try:
                self.runner._run_claude("test", wt_path, "r2")
            except Exception:
                pass

        self.assertNotEqual(captured["cwd"], str(self.project_root))
        self.assertTrue(captured["cwd"].endswith("impl-test-abc-9999999999"))


class TestWorktreeMergeBack(unittest.TestCase):
    """worktree_manager 的 merge_back_from_branch 三种场景：成功 / 已合并（幂等） / 冲突。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir) / "main"
        self.project_root.mkdir()
        self.wt_base = Path(self.tmpdir) / "worktrees"

        # 初始化 git repo（主树）
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / "README.md").write_text("# main\n")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)

        self.logger = MagicMock()
        from core.worktree_manager import WorktreeManager
        self.wm = WorktreeManager(self.wt_base, self.project_root, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_merge_back_success(self):
        """分支上有新提交时，merge --no-ff 应成功合并到主树。"""
        # 创建 worktree 并在分支上提交
        wt_path = self.wm.create("test-spec", "implementer")
        self.assertIsNotNone(wt_path)
        (wt_path / "feature.txt").write_text("new feature\n")
        subprocess.run(["git", "add", "feature.txt"],
                       cwd=str(wt_path), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add feature"],
                       cwd=str(wt_path), capture_output=True)
        branch = self.wm.get_branch_name(wt_path)
        self.assertIsNotNone(branch)

        # cleanup（保留分支）
        self.wm.cleanup(wt_path, success=True)

        # merge-back
        success, error = self.wm.merge_back_from_branch(branch)
        self.assertTrue(success, f"merge failed: {error}")
        # 主树应包含 feature.txt
        self.assertTrue((self.project_root / "feature.txt").exists())
        # git log 中应有 merge commit（--no-ff）
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(self.project_root), capture_output=True, text=True,
        )
        lines = result.stdout.strip().split("\n")
        self.assertTrue(any("merge implementer branch" in l for l in lines))

    def test_merge_back_already_merged_idempotent(self):
        """分支已合并时，再次调用应幂等跳过（不产生新 merge commit，不报错）。"""
        wt_path = self.wm.create("test-spec2", "implementer")
        (wt_path / "a.txt").write_text("a\n")
        subprocess.run(["git", "add", "a.txt"],
                       cwd=str(wt_path), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add a"],
                       cwd=str(wt_path), capture_output=True)
        branch = self.wm.get_branch_name(wt_path)
        self.wm.cleanup(wt_path, success=True)

        # 第一次 merge
        ok1, err1 = self.wm.merge_back_from_branch(branch)
        self.assertTrue(ok1, err1)

        # 记录当前 HEAD
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.project_root), capture_output=True, text=True,
        ).stdout.strip()

        # 第二次 merge（已合并）
        ok2, err2 = self.wm.merge_back_from_branch(branch)
        self.assertTrue(ok2, f"second merge failed: {err2}")

        # HEAD 不应变化
        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.project_root), capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(head_before, head_after)
        self.assertEqual(err2, "already merged")

    def test_merge_back_conflict_returns_error(self):
        """merge 冲突时返回失败，并 abort 保持主树干净。"""
        # 先在主树改 README
        (self.project_root / "README.md").write_text("# main modified on main\n")
        subprocess.run(["git", "commit", "-a", "-q", "-m", "modify readme on main"],
                       cwd=str(self.project_root), capture_output=True)

        # 创建 worktree（基于当前 HEAD 的父提交 —— 制造冲突）
        # 简化方案：直接创建一个分支并在 worktree 中改 README
        wt_path = self.wm.create("conflict-spec", "implementer")
        self.assertIsNotNone(wt_path)
        # 在 worktree 中修改 README（与主树不同的修改，制造冲突）
        # 注意：worktree 是从 HEAD 创建的，HEAD 是刚才的 "modify readme on main"
        # 所以我们需要先在 worktree 上回退再改，或者换一个文件制造冲突
        # 用另一个文件更简单
        (wt_path / "shared.txt").write_text("worktree version\n")
        subprocess.run(["git", "add", "shared.txt"],
                       cwd=str(wt_path), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add shared from wt"],
                       cwd=str(wt_path), capture_output=True)

        # 在主树也加一个不同版本的 shared.txt（制造冲突）
        (self.project_root / "shared.txt").write_text("main version\n")
        subprocess.run(["git", "add", "shared.txt"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add shared from main"],
                       cwd=str(self.project_root), capture_output=True)

        branch = self.wm.get_branch_name(wt_path)
        self.wm.cleanup(wt_path, success=True)

        # merge-back 应失败
        success, error = self.wm.merge_back_from_branch(branch)
        self.assertFalse(success)
        self.assertTrue(len(error) > 0)

        # 主树应保持干净（merge --abort 成功）
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(self.project_root), capture_output=True, text=True,
        )
        self.assertEqual(status.stdout.strip(), "")
        # 不处于 merging 状态
        self.assertFalse((self.project_root / ".git" / "MERGE_HEAD").exists())

    def test_merge_back_empty_branch_fails(self):
        """空分支名应返回失败。"""
        success, error = self.wm.merge_back_from_branch("")
        self.assertFalse(success)
        self.assertIn("branch", error.lower())


class TestPMEngineMergeBackIntegration(unittest.TestCase):
    """pm_engine 在 implementer 成功后执行 merge-back，失败不推进到 implemented。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

        # 初始化 git repo
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / "README.md").write_text("# test\n")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)

        self.logger = MagicMock()
        from core.state_machine import StateMachine
        self.state_path = self.project_root / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        self.sm.add_spec("test-spec", {"priority": 3})
        self.sm.transition("test-spec", "ready")
        self.sm.transition("test-spec", "implementing")

        self.engine = PMEngine(self.sm, MagicMock(), {}, self.project_root, self.logger)
        self.engine._process_queue = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_merge_success_transitions_to_implemented(self):
        """merge-back 成功时，状态推进到 implemented 并排队 verifier。"""
        from core.agent_runner import AgentRunResult
        result = AgentRunResult(
            run_id="impl-test-spec-123", spec_name="test-spec",
            agent_type="implementer", success=True, duration_seconds=10,
            turns_used=5, branch="fenix/test-spec-123",
        )

        # mock agent_runner.run_implementer 返回成功结果
        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        # mock merge_back_from_branch 成功
        self.engine.agent_runner.worktree_manager = MagicMock()
        self.engine.agent_runner.worktree_manager.merge_back_from_branch = MagicMock(
            return_value=(True, "")
        )
        # mock _read_implementer_result 返回 success
        self.engine._read_implementer_result = MagicMock(
            return_value={"status": "success"}
        )
        # mock _enqueue_front
        self.engine._enqueue_front = MagicMock()

        self.engine._run_agent_worker("test-spec", "implementer", 3)

        # 状态应推进到 implemented
        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["status"], "implemented")
        # verifier 应被排队
        self.engine._enqueue_front.assert_called_once_with("test-spec", "verifier")

    def test_merge_failure_stays_in_ready(self):
        """merge-back 失败时，状态回退到 ready，不推进到 implemented，记录 error。"""
        from core.agent_runner import AgentRunResult
        result = AgentRunResult(
            run_id="impl-test-spec-456", spec_name="test-spec",
            agent_type="implementer", success=True, duration_seconds=10,
            turns_used=5, branch="fenix/test-spec-456",
        )

        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        self.engine.agent_runner.worktree_manager = MagicMock()
        self.engine.agent_runner.worktree_manager.merge_back_from_branch = MagicMock(
            return_value=(False, "Merge conflict: README.md")
        )
        self.engine._read_implementer_result = MagicMock(
            return_value={"status": "success"}
        )
        self.engine._enqueue_front = MagicMock()

        self.engine._run_agent_worker("test-spec", "implementer", 3)

        # 状态应为 ready（不是 implemented）
        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["status"], "ready")
        # error 应包含 merge 失败信息
        self.assertIn("Merge-back", spec.get("error", ""))
        # verifier 不应被排队
        self.engine._enqueue_front.assert_not_called()

    def test_no_branch_skips_merge(self):
        """结果中无 branch 字段时，跳过 merge（向后兼容），仍正常推进。"""
        from core.agent_runner import AgentRunResult
        result = AgentRunResult(
            run_id="impl-test-spec-789", spec_name="test-spec",
            agent_type="implementer", success=True, duration_seconds=10,
            turns_used=5, branch=None,
        )

        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        self.engine._read_implementer_result = MagicMock(
            return_value={"status": "success"}
        )
        self.engine._enqueue_front = MagicMock()

        self.engine._run_agent_worker("test-spec", "implementer", 3)

        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["status"], "implemented")


if __name__ == "__main__":
    unittest.main()
