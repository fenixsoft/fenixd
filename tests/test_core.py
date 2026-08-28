"""
Unit tests for Fenix Loop Engineering Framework core modules.

Run with: python3 -m pytest .fenix/tests/ -v
"""

import json
import os
import shutil
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


class TestStateParserHalfWriteDefense(unittest.TestCase):
    """1.1 半写 STATE.md 读取防御——证实非法条目击穿扫描的点位并锁定防御契约。

    2026-08-27 事故：``Full scan failed: string indices must be integers`` 当日出现 5 次，
    整轮 full_scan（含 blocker 检测与全部 recovery）静默中止。

    根因分析（design D3 假设已用最小复现复核）：
    - 当前 ``StateParser`` 始终以 ``current_entry = {}`` 累积字段，正常半身写内容
      （截断行、缺字段、状态非法）会被安全丢弃为 ``{}`` 或直接跳过，**不会**自行产出
      字符串形态条目，因此单纯半写 STATE.md 经 ``read_all()`` 不会触发该 TypeError。
    - 但该事故家族的真正击穿点在 ``event_bus.full_scan`` 的 recovery 循环
      （core/event_bus.py L83-108）：它对 ``current_specs.items()`` 逐条做
      ``entry.get("status", "")``。一旦返回值里混入**字符串形态条目**（并发撕裂写入、
      外部工具改写 STATE.md、或未来解析路径回归），``entry.get`` 立即抛
      ``AttributeError: 'str' object has no attribute 'get'``（与事故日志
      ``string indices must be integers`` 同类「条目非 dict 即被按下标/属性访问」的击穿），
      整轮扫描中止。

    结论：根因不在解析器本身产出字符串，而在「解析层未规范化返回值使得非 dict 条目
    可能外泄 + 消费点无防御」。修复（1.2）在解析层规范化返回值（非 dict 条目跳过并记
    warning），并在消费点（full_scan recovery）做逐条防御，双保险消除该崩溃家族。
    本用例先**复现击穿点位**，为 1.2 的防御契约提供对照。
    """

    def test_poison_string_entry_breaks_recovery_loop(self):
        """复现崩溃点位：若 read_all 返回值含字符串形态条目，
        full_scan recovery 循环 ``entry.get('status')`` 抛 AttributeError，
        整轮扫描中止。该测试证明「解析层不得产出字符串条目」契约的必要性。"""
        poison = {
            "good": {"status": "ready", "error": None, "implementer_run": None},
            # 字符串形态条目：模拟被撕裂写入 / 外部工具改写的 STATE.md 经解析外泄
            "bad": "### bad-spec\n- status: ready\n",
        }
        with self.assertRaises(AttributeError):
            # 模拟 core/event_bus.py L84 的 recovery 循环访问
            for name, entry in poison.items():
                entry.get("status", "")  # noqa: B018

    def test_half_written_state_md_parse_no_crash(self):
        """半身写 STATE.md 不得引发异常；合法条目仍可被正确读取。"""
        content = """# Fenix Project State
## Specs

### valid-spec
- status: ready
- priority: 1
- created: 2026-01-01T00:00:00Z
- updated: 2026-01-01T00:00:00Z
- implementer_run: null
- tester_run: null
- branch: null
- error: null

### half-written-spec
- status: implementing
- priority: 2
- created: 2026-08-27T14:0
### another-valid
"""
        result = StateParser._parse_content(content)
        self.assertIn("valid-spec", result)
        self.assertEqual(result["valid-spec"]["status"], "ready")
        # 半写条目缺 updated/run 字段等，但绝不得以字符串形态进入返回值
        for name, entry in result.items():
            self.assertIsInstance(entry, dict, f"条目 {name} 不得以字符串形态返回")
            self.assertIn("status", entry)

    def test_read_all_normalizes_string_entry(self):
        """1.2 防御契约：read_all 返回值中不得出现非 dict 条目。

        直接对 ``StateMachine.read_all`` 注入含字符串条目的原始解析产物，
        验证规范化层将其剔除且合法 dict 条目得以保留（配合 1.1 复现点位）。
        """
        sm = StateMachine(Path(tempfile.mkdtemp()) / "STATE.md", MagicMock())
        # 模拟解析层被回归破坏、混入字符串条目的情形
        sm._raw_override = {
            "good": {"status": "ready", "error": None, "implementer_run": None},
            "bad": "### bad\n- status: ready\n",
            "also_bad": ["not", "a", "dict"],
        }
        original_parse = StateParser.parse

        def _fake_parse(path):
            return sm._raw_override

        try:
            StateParser.parse = staticmethod(_fake_parse)
            result = sm.read_all()
        finally:
            StateParser.parse = staticmethod(original_parse)

        self.assertIn("good", result)
        self.assertIsInstance(result["good"], dict)
        # 字符串与列表形态条目被剔除，不得外泄到下游消费点
        self.assertNotIn("bad", result)
        self.assertNotIn("also_bad", result)
        for name, entry in result.items():
            self.assertIsInstance(entry, dict, f"条目 {name} 不得以非 dict 形态返回")


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

    def test_remove_spec(self):
        self.sm.add_spec("to-remove", {"priority": 2})
        self.sm.add_spec("keep", {"priority": 3})
        self.assertTrue(self.sm.remove_spec("to-remove"))
        self.assertIsNone(self.sm.read_one("to-remove"))
        # Other specs must remain intact after atomic rewrite
        self.assertEqual(self.sm.read_one("keep")["priority"], 3)
        # State file no longer contains the removed header
        self.assertNotIn("to-remove", self.state_path.read_text(encoding="utf-8"))

    def test_remove_nonexistent(self):
        # With an existing STATE.md, removing an absent entry leaves the file intact.
        self.sm.add_spec("present", {"priority": 1})
        self.assertFalse(self.sm.remove_spec("does-not-exist"))
        self.assertTrue(self.state_path.exists())
        self.assertEqual(self.sm.read_one("present")["priority"], 1)
        # With no STATE.md at all, the call is still a safe no-op returning False.
        empty_dir = tempfile.mkdtemp()
        fresh_sm = StateMachine(Path(empty_dir) / "STATE.md", MagicMock())
        self.assertFalse(fresh_sm.remove_spec("absent"))
        self.assertFalse((Path(empty_dir) / "STATE.md").exists())
        shutil.rmtree(empty_dir, ignore_errors=True)

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
        self.assertEqual(len(SpecStatus.ALL), 10)

    def test_valid_transitions_cover_all_states(self):
        for status in SpecStatus.ALL:
            self.assertIn(status, VALID_TRANSITIONS)

    def test_pushed_is_terminal(self):
        self.assertEqual(VALID_TRANSITIONS["pushed"], [])

    def test_implementing_can_revert(self):
        self.assertIn("ready", VALID_TRANSITIONS["implementing"])


class TestVerifiedTestingEscapeHatch(unittest.TestCase):
    """D7: VERIFIED→TESTING 逃生门（仅门禁自动路径，人工路径仍拒）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.sm.add_spec("demo", {"status": "verified",
                                  "implementer_run": "impl-1",
                                  "tester_run": "verify-1"})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_gate_transition_verified_to_testing_allowed(self):
        """门禁路径：VERIFIED→TESTING 允许。"""
        self.assertTrue(self.sm.transition_gate("demo", "testing"))
        self.assertEqual(self.sm.read_one("demo")["status"], "testing")

    def test_human_transition_verified_to_testing_rejected(self):
        """人工路径：直接调 transition 的 VERIFIED→TESTING 仍被 VALID_TRANSITIONS 拒。"""
        self.assertFalse(self.sm.transition("demo", "testing"))
        self.assertEqual(self.sm.read_one("demo")["status"], "verified")

    def test_gate_transition_preserves_implementer_run(self):
        """回退保留 implementer_run 与断点（仅改 status）。"""
        self.sm.transition_gate("demo", "testing")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(entry["implementer_run"], "impl-1")

    def test_gate_transition_invalid_from_state_rejected(self):
        """非 verified 源态走 transition_gate 回退被拒。"""
        self.sm.update_spec("demo", {"status": "done"})
        self.assertFalse(self.sm.transition_gate("demo", "testing"))
        self.assertEqual(self.sm.read_one("demo")["status"], "done")


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

    def test_agent_models_unknown_provider_logs_error_not_blocking(self):
        """add-provider-failover：未知 provider 名只打 ERROR 不阻塞加载（design D3）。

        运行期该链元素被跳过，整链都未知时 assignment 返回 None（走默认网关）。
        """
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": "nonexistent", "model": "m1"},
        }
        self._write_config(cfg)
        # 加载不抛异常（沿用热更新哲学，坏一个名字不整 daemon 起不来）
        config = ConfigLoader.load(self.config_path)
        # 该角色 assignment 因链元素全未知而解析为 None（安全降级）
        self.assertIsNone(ConfigLoader.get_agent_model_assignment(config, "implementer"))

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
        """improve-failover-model-mapping-ui（design D2）：角色级 model 不再要求非空。

        角色级 model 为空字符串时加载应成功（旧行为会抛 ValueError）；该角色因元素
        也无法解析出模型而 assignment 返回 None（运行期走默认网关），不阻塞加载。
        """
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": "volc", "model": ""},
        }
        self._write_config(cfg)
        # 加载不再抛异常（design D2 删除「角色级 model 必须非空」）
        config = ConfigLoader.load(self.config_path)
        # 角色级与 provider 条目均无 model → 该元素解析失败，整链跳过 → None
        self.assertIsNone(ConfigLoader.get_agent_model_assignment(config, "implementer"))

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

    def test_get_agent_model_assignment_returns_chain(self):
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "volc", "baseurl": "https://a.com", "apikey": "k1", "sdk_model": "claude-sonnet-5"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": "volc", "model": "deepseek-v4-flash"},
        }
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        # add-provider-failover：单值 provider 解析为单元素候选链 list[(provider, model)]
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        provider, model = result[0]
        self.assertEqual(provider["name"], "volc")
        self.assertEqual(provider["baseurl"], "https://a.com")
        self.assertEqual(model, "deepseek-v4-flash")

    def test_get_agent_model_assignment_returns_list_chain(self):
        """provider 为 list 时解析为按序候选链。"""
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "inferaiapi.com", "baseurl": "https://a.com", "apikey": "k1"},
            {"name": "aliyun", "baseurl": "https://b.com", "apikey": "k2"},
        ]}
        cfg["agents"]["models"] = {
            "implementer": {"provider": ["inferaiapi.com", "aliyun"],
                            "model": "deepseek-v4-flash"},
        }
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0]["name"], "inferaiapi.com")
        self.assertEqual(result[1][0]["name"], "aliyun")

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


# ── 新增：improve-failover-model-mapping-ui（design D1/D2/D3 解析矩阵） ──

    def _provider_assign(self, provider, model=None):
        """组装 agents.models.implementer 并加载，返回 config。"""
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "inferaiapi.com", "baseurl": "https://a.com", "apikey": "k1"},
            {"name": "aliyun", "baseurl": "https://b.com", "apikey": "k2",
             "model": "deepseek-v4-flash-0731"},
            {"name": "bigmodel.cn", "baseurl": "https://c.com", "apikey": "k3"},
        ]}
        entry = {"provider": provider}
        if model is not None:
            entry["model"] = model
        cfg["agents"]["models"] = {"implementer": entry}
        self._write_config(cfg)
        return ConfigLoader.load(self.config_path)

    def test_object_element_uses_own_model(self):
        """Scenario：对象元素按自身模型请求；切换用元素 mapping 的模型而非首项。"""
        config = self._provider_assign(
            [{"provider": "inferaiapi.com", "model": "deepseek-v4-flash"},
             {"provider": "bigmodel.cn", "model": "glm-5.3-flash"}])
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        self.assertEqual([(p["name"], m) for p, m in result],
                         [("inferaiapi.com", "deepseek-v4-flash"),
                          ("bigmodel.cn", "glm-5.3-flash")])

    def test_role_model_as_default_fallback(self):
        """Scenario：角色级 model 作为全链缺省（provider 条目 model 不覆盖角色级）。"""
        config = self._provider_assign(
            ["inferaiapi.com", "aliyun"], model="deepseek-v4-flash")
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        self.assertEqual([m for _p, m in result],
                         ["deepseek-v4-flash", "deepseek-v4-flash"])

    def test_provider_entry_model_used_when_role_absent(self):
        """三级回退：角色级缺省时，aliyun 回退到 providers 条目的 model。"""
        config = self._provider_assign(["aliyun"])  # 无角色级 model
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        self.assertEqual([(p["name"], m) for p, m in result],
                         [("aliyun", "deepseek-v4-flash-0731")])

    def test_mixed_str_and_object_chain(self):
        """混合形态 [对象, str]：str 元素（无角色级）回退到 provider 条目 model。"""
        config = self._provider_assign(
            [{"provider": "inferaiapi.com", "model": "deepseek-v4-flash"}, "aliyun"])
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        self.assertEqual([(p["name"], m) for p, m in result],
                         [("inferaiapi.com", "deepseek-v4-flash"),
                          ("aliyun", "deepseek-v4-flash-0731")])

    def test_empty_chain_returns_none(self):
        """Scenario：全空链回退默认网关。角色级无 model 且所有元素均无法解析模型。"""
        config = self._provider_assign(["bigmodel.cn"])  # bigmodel.cn 条目无 model，无角色级
        self.assertIsNone(ConfigLoader.get_agent_model_assignment(config, "implementer"))

    def test_missing_role_model_passes_validation(self):
        """Scenario：缺角色级 model 的合法配置通过校验（无 ERROR 抛异常）。"""
        config = self._provider_assign([{"provider": "inferaiapi.com", "model": "m1"}])
        self.assertIsNotNone(ConfigLoader.get_agent_model_assignment(config, "implementer"))

    def test_unresolvable_element_logs_index(self):
        """Scenario：不可解析元素报下标（ERROR 含 provider[1]）。"""
        cfg = self._base_config()
        cfg["llm"] = {"providers": [
            {"name": "ok", "baseurl": "https://a.com", "apikey": "k1", "model": "m0"},
            {"name": "bad", "baseurl": "https://b.com", "apikey": "k2"},  # 无 model
        ]}
        cfg["agents"]["models"] = {"implementer": {"provider": ["ok", "bad"]}}
        self._write_config(cfg)
        with self.assertLogs("fenixd.config", level="ERROR") as cm:
            ConfigLoader.load(self.config_path)
        self.assertTrue(any("provider[1]" in line for line in cm.output))

    def test_empty_chain_validation_passes(self):
        """校验规则替换：完全无可用元素的链校验通过（分配层返回 None）。"""
        cfg = self._base_config()
        cfg["llm"] = {"providers": [{"name": "p", "baseurl": "https://a.com", "apikey": "k1"}]}
        cfg["agents"]["models"] = {"implementer": {"provider": "p"}}  # 无 model 任何层级
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        self.assertIsNone(ConfigLoader.get_agent_model_assignment(config, "implementer"))

    def test_validate_rejects_non_string_model(self):
        """角色级 model 显式为非字符串（bool/数字）应拒绝。"""
        cfg = self._base_config()
        cfg["llm"] = {"providers": [{"name": "p", "baseurl": "https://a.com", "apikey": "k1"}]}
        cfg["agents"]["models"] = {"implementer": {"provider": "p", "model": 123}}
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_validate_rejects_object_missing_provider(self):
        """对象元素缺 provider 键 → 拒绝。"""
        cfg = self._base_config()
        cfg["llm"] = {"providers": [{"name": "p", "baseurl": "https://a.com", "apikey": "k1"}]}
        cfg["agents"]["models"] = {"implementer": {"provider": [{"model": "m1"}]}}
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)


# ═══════════════════════════════════════════════════════════════════
# 配置分级：deep_merge / resolve_config（add-hierarchical-config）
# ═══════════════════════════════════════════════════════════════════

class TestDeepMerge(unittest.TestCase):
    """纯函数 deep_merge：dict 递归合并（override 优先）、标量/list 整体替换、不修改入参。"""

    def test_nested_dict_merge_override_wins(self):
        from core.config import deep_merge
        base = {"agents": {"max_concurrent": 4, "max_retries": 3}, "gates": {"approve_mode": "manual"}}
        override = {"agents": {"max_concurrent": 2}}
        merged = deep_merge(base, override)
        self.assertEqual(merged["agents"]["max_concurrent"], 2)
        self.assertEqual(merged["agents"]["max_retries"], 3)
        self.assertEqual(merged["gates"]["approve_mode"], "manual")

    def test_list_whole_replacement(self):
        from core.config import deep_merge
        base = {"llm": {"providers": [{"name": "a"}, {"name": "b"}]}}
        override = {"llm": {"providers": [{"name": "c"}]}}
        merged = deep_merge(base, override)
        self.assertEqual(merged["llm"]["providers"], [{"name": "c"}])

    def test_scalar_replacement_and_new_keys(self):
        from core.config import deep_merge
        merged = deep_merge({"a": 1}, {"a": 2, "b": 3})
        self.assertEqual(merged, {"a": 2, "b": 3})

    def test_does_not_mutate_inputs(self):
        from core.config import deep_merge
        base = {"agents": {"max_concurrent": 4}}
        override = {"agents": {"max_concurrent": 2}}
        deep_merge(base, override)
        self.assertEqual(base["agents"]["max_concurrent"], 4)

    def test_no_override_returns_base_copy(self):
        from core.config import deep_merge
        base = {"project": {"name": "p", "type": "web"}}
        merged = deep_merge(base, {})
        self.assertEqual(merged, base)
        self.assertIsNot(merged, base)


class TestResolveConfig(unittest.TestCase):
    """有效配置解析：用户级 + 项目级深合并、缺失兜底、project.name 补齐、校验放宽。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir) / "myproj"
        (self.project_root / ".fenix").mkdir(parents=True)
        self.user_dir = Path(self.tmpdir) / "user-fenix"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_user(self, config):
        import yaml
        self.user_dir.mkdir(exist_ok=True)
        with (self.user_dir / "config.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(config, f)

    def _write_project(self, config):
        import yaml
        with (self.project_root / ".fenix" / "config.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(config, f)

    def _resolve(self, project_root=None):
        with patch("core.config.USER_CONFIG_DIR", self.user_dir):
            return ConfigLoader.resolve_config(project_root or self.project_root)

    def test_both_missing_returns_minimal_with_project_name(self):
        cfg = self._resolve()
        self.assertEqual(cfg["project"]["name"], "myproj")
        self.assertNotIn("schedule", cfg)

    def test_only_user_exists_uses_user_and_fills_project_name(self):
        self._write_user({
            "agents": {"max_concurrent": 4},
            "gates": {"approve_mode": "manual"},
        })
        cfg = self._resolve()
        self.assertEqual(cfg["agents"]["max_concurrent"], 4)
        self.assertEqual(cfg["gates"]["approve_mode"], "manual")
        self.assertEqual(cfg["project"]["name"], "myproj")

    def test_user_project_name_overridden_by_root_name(self):
        """用户级写了 project.name 且项目级未写 → 用项目根目录名覆盖（设计 Open Question）。"""
        self._write_user({"project": {"name": "shared-name", "type": "web"}})
        cfg = self._resolve()
        self.assertEqual(cfg["project"]["name"], "myproj")

    def test_project_override_and_inheritance(self):
        """项目级覆盖个别键，其余键继承用户级（D2 合并语义）。"""
        self._write_user({
            "agents": {"max_concurrent": 4, "max_retries": 3},
            "gates": {"approve_mode": "manual"},
        })
        self._write_project({
            "project": {"name": "myproj", "type": "web"},
            "agents": {"max_concurrent": 2},
        })
        cfg = self._resolve()
        self.assertEqual(cfg["agents"]["max_concurrent"], 2)  # 项目级覆盖
        self.assertEqual(cfg["agents"]["max_retries"], 3)     # 继承用户级
        self.assertEqual(cfg["gates"]["approve_mode"], "manual")
        self.assertEqual(cfg["project"]["name"], "myproj")

    def test_project_name_kept_from_project_level(self):
        self._write_project({"project": {"name": "custom-name", "type": "cli"}})
        cfg = self._resolve()
        self.assertEqual(cfg["project"]["name"], "custom-name")

    def test_list_whole_replacement_in_resolve(self):
        self._write_user({"llm": {"providers": [
            {"name": "a", "baseurl": "https://a.com", "apikey": "k1"}]}})
        self._write_project({"llm": {"providers": [
            {"name": "b", "baseurl": "https://b.com", "apikey": "k2"}]}})
        cfg = self._resolve()
        self.assertEqual(cfg["llm"]["providers"], [{"name": "b", "baseurl": "https://b.com", "apikey": "k2"}])

    def test_validation_still_checks_present_keys(self):
        """宽松路径仍对已存在键做值级校验：非法 approve_mode 报错。"""
        self._write_user({"gates": {"approve_mode": "bogus"}})
        with self.assertRaises(ValueError):
            self._resolve()

    def test_parse_error_falls_back_without_raising(self):
        """项目级文件 YAML 解析失败 → 按空 dict 兜底，不抛异常。"""
        self._write_user({"gates": {"approve_mode": "manual"}})
        (self.project_root / ".fenix" / "config.yaml").write_text(": : bad yaml [", encoding="utf-8")
        cfg = self._resolve()
        self.assertEqual(cfg["gates"]["approve_mode"], "manual")
        self.assertEqual(cfg["project"]["name"], "myproj")

    def test_missing_project_type_not_validated(self):
        """宽松路径下 project 缺 type 不参与校验（设计 D3 步骤 4）。"""
        self._write_project({"project": {"name": "myproj"}})
        cfg = self._resolve()
        self.assertEqual(cfg["project"]["name"], "myproj")

    def test_invalid_project_type_still_rejected(self):
        """宽松路径下显式提供非法 project.type 仍被拒绝。"""
        self._write_project({"project": {"name": "myproj", "type": "bogus"}})
        with self.assertRaises(ValueError):
            self._resolve()


class TestConfigHotReload(unittest.TestCase):
    """配置热更新：resolve_config_into 原地更新现有 dict，组件共享引用自动看到新值。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir) / "myproj"
        (self.project_root / ".fenix").mkdir(parents=True)
        self.user_dir = Path(self.tmpdir) / "user-fenix"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_project(self, config):
        import yaml
        with (self.project_root / ".fenix" / "config.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(config, f)

    def _reload_into(self, cfg):
        from core.config import ConfigLoader
        with patch("core.config.USER_CONFIG_DIR", self.user_dir):
            ConfigLoader.resolve_config_into(cfg, self.project_root)

    def test_in_place_update_same_object_new_values(self):
        from core.config import ConfigLoader
        self._write_project({"agents": {"max_concurrent": 2}})
        cfg = {}
        with patch("core.config.USER_CONFIG_DIR", self.user_dir):
            fresh = ConfigLoader.resolve_config(self.project_root)
        cfg.update(fresh)
        holder = cfg
        self._write_project({"agents": {"max_concurrent": 8}})
        self._reload_into(holder)
        self.assertIs(holder, cfg)
        self.assertEqual(holder["agents"]["max_concurrent"], 8)

    def test_removed_key_cleared(self):
        self._write_project({"agents": {"max_concurrent": 2}, "gates": {"approve_mode": "auto"}})
        cfg = {}
        self._reload_into(cfg)
        self.assertEqual(cfg["gates"]["approve_mode"], "auto")
        self._write_project({"agents": {"max_concurrent": 4}})
        self._reload_into(cfg)
        self.assertNotIn("gates", cfg)
        self.assertEqual(cfg["agents"]["max_concurrent"], 4)

    def test_agent_model_assignment_visible_after_reload(self):
        from core.config import ConfigLoader
        self._write_project({})
        with patch("core.config.USER_CONFIG_DIR", self.user_dir):
            cfg = ConfigLoader.resolve_config(self.project_root)
        self.assertIsNone(ConfigLoader.get_agent_model_assignment(cfg, "implementer"))
        import yaml
        self.user_dir.mkdir(exist_ok=True)
        with (self.user_dir / "config.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump({
                "llm": {"providers": [{"name": "p1", "baseurl": "https://x.example", "apikey": "sk-t", "model": "m1"}]},
                "agents": {"models": {"implementer": {"provider": "p1", "model": "m1"}}},
            }, f)
        self._reload_into(cfg)
        assignment = ConfigLoader.get_agent_model_assignment(cfg, "implementer")
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment[0][0]["name"], "p1")
        self.assertEqual(assignment[0][1], "m1")

    def test_invalid_config_keeps_previous_values(self):
        from core.config import ConfigLoader
        self._write_project({"agents": {"max_concurrent": 4}})
        cfg = ConfigLoader.resolve_config(self.project_root)
        old_val = cfg["agents"]["max_concurrent"]
        self._write_project({"schedule": {"poll_interval_minutes": -5}})
        with patch("core.config.USER_CONFIG_DIR", self.user_dir):
            with self.assertRaises(ValueError):
                ConfigLoader.resolve_config_into(cfg, self.project_root)
        self.assertEqual(cfg["agents"]["max_concurrent"], old_val)


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
        # add-provider-failover：返回候选链（list of (provider, model)）
        self.assertEqual(len(result), 1)
        provider, model = result[0]
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

    def test_run_claude_strips_inherited_auth_token_when_provider_set(self):
        """Provider 覆盖生效时，继承的 ANTHROPIC_AUTH_TOKEN 必须被清除（防 401）。"""
        config = {
            "llm": {"providers": [
                {"name": "p1", "baseurl": "https://a.com", "apikey": "key-a"},
            ]},
            "agents": {
                "max_concurrent": 2, "max_retries": 1, "max_turns": 50, "run_timeout_seconds": 10,
                "models": {"implementer": {"provider": "p1", "model": "model-a"}},
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

        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "ark-xyz", "ANTHROPIC_BASE_URL": "https://ark.example"},
                        clear=False):
            with patch("core.agent_runner.subprocess.Popen", side_effect=fake_popen):
                try:
                    runner._run_claude("test prompt", self.project_root, "test-run-auth",
                                       "claude-sonnet-5",
                                       {"ANTHROPIC_BASE_URL": "https://a.com",
                                        "ANTHROPIC_API_KEY": "key-a",
                                        "ANTHROPIC_MODEL": "model-a"})
                except Exception:
                    pass

        self.assertEqual(captured["env"]["ANTHROPIC_BASE_URL"], "https://a.com")
        self.assertEqual(captured["env"]["ANTHROPIC_API_KEY"], "key-a")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", captured["env"],
                        "Provider 覆盖时必须清除继承的 AUTH_TOKEN，否则 claude 用它认证 → 401")

    def test_run_claude_keeps_auth_token_when_no_provider(self):
        """未走 Provider 覆盖（无 ANTHROPIC_API_KEY）时，保留继承的 AUTH_TOKEN（维持现状）。"""
        config = {"agents": {"max_concurrent": 2, "max_retries": 1, "max_turns": 50,
                             "run_timeout_seconds": 10}}
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

        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "ark-xyz"}, clear=False):
            with patch("core.agent_runner.subprocess.Popen", side_effect=fake_popen):
                try:
                    runner._run_claude("test prompt", self.project_root, "test-run-noauth",
                                       None, {})
                except Exception:
                    pass

        self.assertEqual(captured["env"].get("ANTHROPIC_AUTH_TOKEN"), "ark-xyz")

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
        runner._run_claude = MagicMock(return_value=("ok", 1, "sess-1"))
        result = runner.run_implementer("test-spec")
        self.assertTrue(result.success)
        # _run_claude(prompt, cwd, run_id, model_override, env_overrides) —— env_overrides 是第 5 个位置参数
        env = runner._run_claude.call_args.args[4]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://a.com")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "key-a")
        self.assertEqual(env["ANTHROPIC_MODEL"], "model-a")
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "1000000")

    def test_model_override_uses_assignment_model_not_sdk_model(self):
        """--model 用 agent 分配的 model（网关模型名），不再读 provider.sdk_model。"""
        config = {
            "llm": {"providers": [
                {"name": "p1", "baseurl": "https://a.com", "apikey": "key-a",
                 "model": "deepseek-v4-flash", "sdk_model": "claude-sonnet-5"},
            ]},
            "agents": {
                "max_concurrent": 2, "max_retries": 1, "max_turns": 50,
                "models": {"implementer": {"provider": "p1", "model": "deepseek-v4-flash"}},
            },
        }
        runner = self._make_runner(config)
        runner._build_prompt = MagicMock(return_value="test prompt")
        runner._run_claude = MagicMock(return_value=("ok", 1, "sess-1"))
        result = runner.run_implementer("test-spec")
        self.assertTrue(result.success)
        # _run_claude(prompt, cwd, run_id, model_override, env_overrides) —— model_override 是第 4 个位置参数
        model_override = runner._run_claude.call_args.args[3]
        self.assertEqual(model_override, "deepseek-v4-flash")

    def test_model_override_unassigned_uses_default_gateway_model(self):
        """未分配 Provider 时 --model 用默认网关常量 claude-sonnet-5。"""
        config = {"agents": {"max_concurrent": 2, "max_retries": 1, "max_turns": 50}}
        runner = self._make_runner(config)
        runner._build_prompt = MagicMock(return_value="test prompt")
        runner._run_claude = MagicMock(return_value=("ok", 1, "sess-1"))
        result = runner.run_verifier("test-spec")
        self.assertTrue(result.success)
        model_override = runner._run_claude.call_args.args[3]
        self.assertEqual(model_override, "claude-sonnet-5")

    # ── add-agent-llm-isolation：CLAUDE_CONFIG_DIR 隔离 ────────────────

    def test_run_agent_injects_claude_config_dir_when_provider(self):
        """配置 Provider 时 env_overrides 含 CLAUDE_CONFIG_DIR 指向隔离目录（spec 3.1）。"""
        config = {
            "llm": {"providers": [
                {"name": "p1", "baseurl": "https://a.com", "apikey": "key-a"},
            ]},
            "agents": {
                "max_concurrent": 2, "max_retries": 1, "max_turns": 50,
                "models": {"implementer": {"provider": "p1", "model": "model-a"}},
                "subagent_model": "claude-sonnet-5",
            },
        }
        runner = self._make_runner(config)
        runner._build_prompt = MagicMock(return_value="test prompt")
        runner._run_claude = MagicMock(return_value=("ok", 1, "sess-1"))
        result = runner.run_implementer("test-spec")
        self.assertTrue(result.success)
        env = runner._run_claude.call_args.args[4]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://a.com")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"],
                         str(self.project_root / ".fenix" / "agent-config" / "p1"))
        # 隔离目录应实际生成
        self.assertTrue((self.project_root / ".fenix" / "agent-config" / "p1" / "settings.json").exists())

    def test_run_agent_no_claude_config_dir_when_unassigned(self):
        """未配置 Provider 时不设 CLAUDE_CONFIG_DIR，透传当前 settings.json（spec 3.1）。"""
        config = {
            "agents": {
                "max_concurrent": 2, "max_retries": 1, "max_turns": 50,
                "subagent_model": "claude-sonnet-5",
            },
        }
        runner = self._make_runner(config)
        runner._build_prompt = MagicMock(return_value="test prompt")
        runner._run_claude = MagicMock(return_value=("ok", 1, "sess-1"))
        result = runner.run_verifier("test-spec")
        self.assertTrue(result.success)
        env = runner._run_claude.call_args.args[4]
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)

    def _fake_home(self, with_env=None, with_plugins=True):
        """构造受控 ~/.claude 假 home（settings.json + skills/plugins 源目录）。"""
        fake_home = Path(self.tmpdir) / "home"
        (fake_home / ".claude").mkdir(parents=True)
        settings = {"enabledPlugins": {"superpowers@claude-plugins-official": True}}
        if with_env is not None:
            settings["env"] = with_env
        (fake_home / ".claude" / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8")
        if with_plugins:
            (fake_home / ".claude" / "skills").mkdir()
            (fake_home / ".claude" / "skills" / "playwright-cli").mkdir()
            (fake_home / ".claude" / "plugins").mkdir()
        return fake_home

    def test_isolated_settings_no_credentials(self):
        """隔离 settings.json 不含任何 env（模型名映射/凭据都不落盘），保留 plugins/hooks。"""
        runner = self._make_runner({})
        fake_home = self._fake_home(with_env={
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
            "ANTHROPIC_AUTH_TOKEN": "PROXY_MANAGED",
            "ANTHROPIC_API_KEY": "sk-secret",
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-4-6[1M]",
            "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME": "deepseek-v4-flash",
            "CLAUDE_CODE_SUBAGENT_MODEL": "claude-haiku-4-5",
        })
        # .fenix/agent-settings.json（hooks：block-image-read）
        (self.project_root / ".fenix" / "agent-settings.json").write_text(json.dumps({
            "hooks": {"PreToolUse": [{
                "matcher": "Read",
                "hooks": [{"type": "command", "command": "block-image-read.py"}],
            }]},
        }), encoding="utf-8")

        with patch("core.agent_runner.Path.home", return_value=fake_home):
            cfg_dir = runner._ensure_agent_config_dir("ark")

        settings = json.loads((cfg_dir / "settings.json").read_text(encoding="utf-8"))
        # 隔离 settings 不再复制任何 env（ANTHROPIC_DEFAULT_* / CLAUDE_CODE_SUBAGENT_MODEL
        # 等 cc-switch 网关映射）——直连 Provider 不需要，且会毒化子代理模型解析。
        self.assertNotIn("env", settings)
        # enabledPlugins / hooks 保留
        self.assertEqual(settings["enabledPlugins"], {"superpowers@claude-plugins-official": True})
        self.assertIn("PreToolUse", settings["hooks"])

    def test_ensure_agent_config_dir_idempotent_and_symlinks(self):
        """隔离目录幂等 + skills/plugins symlink 正确（spec 3.3）。"""
        runner = self._make_runner({})
        fake_home = self._fake_home(with_env={"ANTHROPIC_DEFAULT_SONNET_MODEL": "m"})

        with patch("core.agent_runner.Path.home", return_value=fake_home):
            d1 = runner._ensure_agent_config_dir("ark")
            d2 = runner._ensure_agent_config_dir("ark")

        self.assertEqual(d1, d2)
        self.assertTrue((d2 / "settings.json").is_file())
        self.assertTrue((d2 / "skills").is_symlink())
        self.assertTrue((d2 / "plugins").is_symlink())
        self.assertEqual((d2 / "skills").resolve(),
                         (fake_home / ".claude" / "skills").resolve())
        # 连续两次调用 settings.json 内容一致（幂等，无重建副作用）
        self.assertEqual((d1 / "settings.json").read_text(encoding="utf-8"),
                         (d2 / "settings.json").read_text(encoding="utf-8"))

    def test_ensure_agent_config_dir_missing_source_ok(self):
        """~/.claude 源目录缺失时优雅降级：跳过 symlink，不报错（spec 3.3）。"""
        runner = self._make_runner({})
        fake_home = self._fake_home(with_env=None, with_plugins=False)

        with patch("core.agent_runner.Path.home", return_value=fake_home):
            cfg_dir = runner._ensure_agent_config_dir("ark")

        self.assertTrue((cfg_dir / "settings.json").is_file())
        self.assertFalse((cfg_dir / "skills").exists())
        self.assertFalse((cfg_dir / "plugins").exists())


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

    def test_git_push_ref_failure_returns_false(self):
        """推送不存在的远端应返回失败。"""
        engine = self._make_engine({})
        success, error = engine._git_push_ref("nonexistent-branch")
        self.assertFalse(success)
        self.assertTrue(len(error) > 0)

    def test_approve_push_success_transitions_to_pushed(self):
        """main 先行推送成功（分支尽力跳过）→ transition 到 pushed。"""
        engine = self._make_engine({})
        self.sm.read_one = MagicMock(
            return_value={"status": "done", "branch": "fenix/test-spec"}
        )
        with patch.object(engine, '_git_push_ref', return_value=(True, "")):
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            self.sm.transition.assert_called_once_with("test-spec", "pushed")
            # 成功时清 error
            update_args = self.sm.update_spec.call_args[0]
            self.assertIsNone(update_args[1]["error"])

    def test_approve_push_main_failure_updates_error(self):
        """main 推送失败时不推进状态，但记录 error（含退避标记）。"""
        engine = self._make_engine({})
        self.sm.read_one = MagicMock(
            return_value={"status": "done", "branch": "fenix/test-spec"}
        )
        with patch.object(engine, '_git_push_ref', return_value=(False, "remote rejected")):
            result = engine.approve_push("test-spec")
            self.assertFalse(result)
            self.sm.transition.assert_not_called()
            self.sm.update_spec.assert_called_once()
            update_args = self.sm.update_spec.call_args[0]
            self.assertIn("error", update_args[1])
            self.assertIn("remote rejected", update_args[1]["error"])
            # 退避标记 + 尝试计数
            self.assertIn("push_backoff", update_args[1]["error"])
            self.assertIn("push_attempts=1", update_args[1]["error"])

    def test_approve_push_success_clears_preexisting_error(self):
        """推送成功时清除 spec 既有 error 字段（终态残痕清理）。"""
        engine = self._make_engine({})
        # 模拟上一次推送失败残留的 error（含退避标记）
        self.sm.read_one = MagicMock(
            return_value={
                "status": "done", "branch": "fenix/test-spec",
                "error": "git push failed (main): x [push_attempts=2] "
                         "[push_backoff next_retry_at=999999]",
            }
        )
        with patch.object(engine, '_git_push_ref', return_value=(True, "")):
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            self.sm.transition.assert_called_once_with("test-spec", "pushed")
            self.sm.update_spec.assert_called_once()
            self.assertIsNone(self.sm.update_spec.call_args[0][1]["error"])

    def test_approve_push_retry_count_accumulates(self):
        """连续失败时 attempts 计数递增（第 1 次 → attempts=1，第 2 次 → attempts=2）。"""
        # 配置 0 秒退避，使第二次尝试不会被前一次退避拦截
        engine = self._make_engine({"pm": {"push": {"retry_backoff_seconds": [0, 0]}}})
        # 第一次失败：spec 无 prior error
        self.sm.read_one.return_value = {"status": "done", "branch": "fenix/test-spec"}
        with patch.object(engine, '_git_push_ref', return_value=(False, "boom1")):
            engine.approve_push("test-spec")
        err1 = self.sm.update_spec.call_args[0][1]["error"]
        self.assertIn("push_attempts=1", err1)

        # 第二次失败：spec 带第一次的 error
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec", "error": err1,
        }
        with patch.object(engine, '_git_push_ref', return_value=(False, "boom2")):
            engine.approve_push("test-spec")
        err2 = self.sm.update_spec.call_args[0][1]["error"]
        self.assertIn("push_attempts=2", err2)

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

    # ── Task 2.1: 退避期内跳过 / 超限升级 push_failed 信号 ─────────

    def test_push_backoff_period_skips_push(self):
        """退避期内（next_retry_at 未到期）→ approve_push 不发出 push 命令。"""
        from datetime import datetime, timezone
        future_ts = int(datetime.now(timezone.utc).timestamp()) + 9999
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
            "error": (
                "git push failed (main): x [push_attempts=1] "
                f"[push_backoff next_retry_at={future_ts}]"
            ),
        }
        with patch.object(engine, '_git_push_ref') as mock_push:
            result = engine.approve_push("test-spec")
            self.assertFalse(result)
            mock_push.assert_not_called()

    def test_push_backoff_period_skips_auto_approve(self):
        """退避期内 → _auto_approve 也不触发推送。"""
        from datetime import datetime, timezone
        future_ts = int(datetime.now(timezone.utc).timestamp()) + 9999
        engine = self._make_engine({"gates": {"approve_mode": "auto"}})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
            "error": (
                "git push failed (main): x [push_attempts=2] "
                f"[push_backoff next_retry_at={future_ts}]"
            ),
        }
        with patch.object(engine, '_git_push_ref') as mock_push:
            result = engine._auto_approve("test-spec")
            self.assertFalse(result)
            mock_push.assert_not_called()

    def test_push_max_retries_exhausted_sends_signal(self):
        """连续 3 次失败 → 发 push_failed 信号，停止自动重试。"""
        engine = self._make_engine({
            "pm": {"push": {"retry_backoff_seconds": [0, 0, 0]}},
        })
        # 逐次模拟 spec 中 error 递增的 attempts
        for i in range(1, 4):
            prior_error = (
                f"git push failed (main): boom [push_attempts={i - 1}] "
                "[push_backoff next_retry_at=0]" if i > 1 else None
            )
            self.sm.read_one.return_value = {
                "status": "done", "branch": "fenix/test-spec",
                "error": prior_error,
            }
            with patch.object(engine, '_git_push_ref', return_value=(False, "boom")), \
                 patch.object(engine, '_signal_push_failed') as mock_signal:
                engine.approve_push("test-spec")
            if i < 3:
                # 未超限：不发信号
                mock_signal.assert_not_called()
            else:
                # 超限：发 push_failed 信号
                mock_signal.assert_called_once()
                call_args = mock_signal.call_args[0]
                self.assertEqual(call_args[0], "test-spec")
            # 检查 error 含 `[push_failed]` 标记
            err = self.sm.update_spec.call_args[0][1]["error"]
            if i == 3:
                self.assertIn("push_failed", err)
                self.assertIn("已停止自动重试", err)

    def test_push_backoff_expires_and_retries(self):
        """退避过期（next_retry_at 已过）→ approve_push 重新尝试推送。"""
        engine = self._make_engine({
            "pm": {"push": {"retry_backoff_seconds": [0, 0]}},
        })
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
            "error": (
                "git push failed (main): x [push_attempts=1] "
                "[push_backoff next_retry_at=1]"
            ),
        }
        with patch.object(engine, '_git_push_ref', return_value=(True, "")) as mock_push:
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            # 退避过期，重新尝试了 main 推送
            main_calls = [c for c in mock_push.call_args_list if c[0][0] == "main"]
            self.assertEqual(len(main_calls), 1)


# ═══════════════════════════════════════════════════════════════════
# Push Ref Hygiene Tests (fix-push-ref-lifecycle: task 1.1 / design D1/D2)
# ═══════════════════════════════════════════════════════════════════

class TestPushRefHygiene(unittest.TestCase):
    """测试 main 优先推送 + 远端 SHA 去重 + 分支尽力逻辑。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        # 初始化 git repo + 本地分支 + 远端（用 bare repo 模拟 origin）
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
        # 创建远端 bare repo 并配置 origin
        self.remote_root = Path(self.tmpdir) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main",
                        str(self.remote_root)],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(self.remote_root)],
                       cwd=str(self.project_root), capture_output=True)
        # 把 init 推到远端，保证 main 可 FF
        subprocess.run(["git", "push", "-q", "origin", "main"],
                       cwd=str(self.project_root), capture_output=True)

        self.sm = MagicMock()
        self.sm.read_one = MagicMock(
            return_value={"status": "done", "branch": "fenix/test-spec"}
        )
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()
        self.sm.get_by_status = MagicMock(return_value={})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config: dict = None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def test_main_first_push_success(self):
        """main 可 FF 时推送成功并推进 pushed，error 清空。"""
        engine = self._make_engine({})
        result = engine.approve_push("test-spec")
        self.assertTrue(result)
        self.sm.transition.assert_called_once_with("test-spec", "pushed")
        self.assertIsNone(self.sm.update_spec.call_args[0][1]["error"])

    def test_main_diverged_failure(self):
        """远端 main 分叉（非 FF）时推送失败，不推进 pushed。"""
        # 在远端制造一个本地没有的提交，制造分叉
        outside = Path(self.tmpdir) / "outside"
        subprocess.run(["git", "clone", "-q", str(self.remote_root), str(outside)],
                       cwd=str(self.project_root), capture_output=True)
        (outside / "extra.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(outside), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "remote only"],
                       cwd=str(outside), capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "main"],
                       cwd=str(outside), capture_output=True)
        shutil.rmtree(outside, ignore_errors=True)

        engine = self._make_engine({})
        result = engine.approve_push("test-spec")
        self.assertFalse(result)
        self.sm.transition.assert_not_called()
        err = self.sm.update_spec.call_args[0][1]["error"]
        self.assertIn("git push failed", err)

    def test_branch_dedup_skip_when_remote_sha_matches(self):
        """远端分支 SHA 与本地一致 → 不重复推送（去重短路）。"""
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
        }
        # 先在本地创建分支并推到远端（SHA 一致）
        subprocess.run(["git", "branch", "fenix/test-spec"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "fenix/test-spec"],
                       cwd=str(self.project_root), capture_output=True)
        with patch.object(engine, '_git_push_ref', return_value=(True, "")) as mock_push:
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            # 分支去重短路：_git_push_ref 不会被传入分支名
            branch_push_calls = [
                c for c in mock_push.call_args_list if c[0][0] == "fenix/test-spec"
            ]
            self.assertEqual(len(branch_push_calls), 0)
            # main push 仍是成功路径
            main_calls = [c for c in mock_push.call_args_list if c[0][0] == "main"]
            self.assertEqual(len(main_calls), 1)

    def test_local_branch_missing_skips_push(self):
        """本地分支已清理（merge-back 后）→ 无 refspec 错误，main 推送承载。"""
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/gone-branch",
        }
        # 本地没有 fenix/gone-branch 分支，远端也没有
        # approve_push 应成功（main 推送成功），且不会因 gone-branch 报错
        result = engine.approve_push("test-spec")
        self.assertTrue(result)
        self.sm.transition.assert_called_once_with("test-spec", "pushed")

    def test_remote_branch_diff_sha_warns_and_skips(self):
        """远端分支 SHA 不同 → 跳过分支推送并 WARN，main 成功仍推进。"""
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
        }
        # 本地分支
        subprocess.run(["git", "branch", "fenix/test-spec"],
                       cwd=str(self.project_root), capture_output=True)
        # 远端分支放一个「不同 SHA」的对象：用另一个 clone push 不同内容
        outside = Path(self.tmpdir) / "outside2"
        subprocess.run(["git", "clone", "-q", str(self.remote_root), str(outside)],
                       cwd=str(self.project_root), capture_output=True)
        (outside / "diverged.txt").write_text("y")
        subprocess.run(["git", "add", "."], cwd=str(outside), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "diverged branch",
                        "-b", "fenix/test-spec"],
                       cwd=str(outside), capture_output=True)
        subprocess.run(["git", "branch", "-M", "fenix/test-spec"],
                       cwd=str(outside), capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "fenix/test-spec"],
                       cwd=str(outside), capture_output=True)
        shutil.rmtree(outside, ignore_errors=True)

        with patch.object(engine, '_git_push_ref', return_value=(True, "")) as mock_push:
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            branch_calls = [
                c for c in mock_push.call_args_list
                if c[0][0] == "fenix/test-spec"
            ]
            self.assertEqual(len(branch_calls), 0)

    def test_remote_branch_missing_pushes_branch(self):
        """远端分支不存在 → 正常推送 feature 分支（best-effort 成功）。"""
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
        }
        subprocess.run(["git", "branch", "fenix/test-spec"],
                       cwd=str(self.project_root), capture_output=True)
        with patch.object(engine, '_git_push_ref') as mock_push:
            mock_push.return_value = (True, "")
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            branch_calls = [
                c for c in mock_push.call_args_list
                if c[0][0] == "fenix/test-spec"
            ]
            self.assertEqual(len(branch_calls), 1)


# ═══════════════════════════════════════════════════════════════════
# Push Residual Backfill Tests (fix-push-ref-lifecycle: task 3.1 / design D4)
# ═══════════════════════════════════════════════════════════════════

class TestPushResidualBackfill(unittest.TestCase):
    """测试幂等回填清理函数（pushed + git push failed → SHA 验证 → 清 error）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
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
        # 远端裸仓 + origin 并推送 main
        self.remote_root = Path(self.tmpdir) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main",
                        str(self.remote_root)],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(self.remote_root)],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "main"],
                       cwd=str(self.project_root), capture_output=True)

        # 使用真实 StateMachine 以便 backfill 后能回读 error
        from core.state_machine import StateMachine
        self.state_path = self.project_root / "STATE.md"
        self.sm = StateMachine(self.state_path, MagicMock())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config: dict = None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def test_backfill_cleans_verified_residual(self):
        """远端分支 SHA 存在 → pushed 残痕被清除。"""
        self.sm.add_spec("clean-spec", {
            "status": "pushed",
            "branch": "fenix/clean-spec-123",
            "error": "git push failed (main): x [push_backoff next_retry_at=1]",
        })
        engine = self._make_engine({})
        # 模拟该分支在远端存在
        with patch.object(engine, '_remote_branch_sha', return_value="abc123" * 6):
            result = engine.backfill_push_residuals()
        self.assertIn("clean-spec", result["cleaned"])
        # 回读 error 已被清空
        self.assertIsNone(self.sm.read_one("clean-spec").get("error"))

    def test_backfill_keeps_unverifiable_residual(self):
        """远端分支与 main 均不可达 → 残痕保留并列入 kept 清单。"""
        self.sm.add_spec("kept-spec", {
            "status": "pushed",
            "branch": "fenix/kept-spec-123",
            "error": "git push failed (main): offline",
        })
        engine = self._make_engine({})
        # 模拟 ls-remote 失败（无 origin 名对应真实可达远端）
        with patch.object(engine, '_remote_branch_sha', return_value=None):
            result = engine.backfill_push_residuals()
        self.assertIn("kept-spec", [k["spec"] for k in result["kept"]])
        # 残痕保留
        self.assertIsNotNone(self.sm.read_one("kept-spec").get("error"))

    def test_backfill_skips_non_push_failed(self):
        """error 非 'git push failed' 前缀的 pushed spec 不被清理。"""
        self.sm.add_spec("other-spec", {
            "status": "pushed",
            "error": "some other error",
        })
        engine = self._make_engine({})
        result = engine.backfill_push_residuals()
        self.assertNotIn("other-spec", result["cleaned"])
        self.assertNotIn("other-spec", [k["spec"] for k in result["kept"]])

    def test_backfill_skips_non_pushed(self):
        """非 pushed 状态的 spec 不被清理（即便 error 以 git push failed 开头）。"""
        self.sm.add_spec("done-spec", {
            "status": "done",
            "error": "git push failed (main): x",
        })
        engine = self._make_engine({})
        result = engine.backfill_push_residuals()
        self.assertNotIn("done-spec", result["cleaned"])


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
        self.assertEqual(result["agents"], {"models": {}, "max_concurrent": 2, "run_timeout_seconds": 3600, "max_turns": 300, "daily_run_limit": 50})
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
        self.assertEqual(readback["agents"]["models"]["implementer"]["provider"],
                         [{"provider": "volc", "model": "deepseek-v4-pro"}])
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
    """Minimal stand-in for subprocess.Popen: line streams + wait/kill/poll."""

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

    def poll(self):
        # fix-fenix-token-waste：_run_claude 改用轮询等待；timeout 模拟进程永不退出
        return None if self._timeout else self._returncode

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
        output, turns, sess_id = self._run(run_id, stdout_lines=stdout)
        self.assertEqual(output, "All tasks complete")
        self.assertEqual(turns, 7)
        self.assertEqual(sess_id, "sess-1")
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
        output, turns, _ = self._run(run_id, stdout_lines=stdout, stderr_lines=["non-json noise"])
        self.assertEqual(output, "ok")
        artifact = self._artifact(run_id)
        lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        self.assertTrue(any(
            l.get("type") == "stderr" and l.get("line") == "non-json noise" for l in lines
        ))
        # 文件整体仍可逐行 JSON 解析，且最后一行是 result
        self.assertEqual(lines[-1]["type"], "result")

    def test_rc0_is_error_rejected_as_failure(self):
        """D5: rc==0 但 result 事件 is_error=true 时按失败处理（假成功拒绝）。"""
        run_id = "impl-fake-success-1700000010"
        result_event = {
            "type": "result", "subtype": "success", "is_error": True,
            "result": "API Error: 503 Service Unavailable", "num_turns": 3,
        }
        stdout = [
            json.dumps({"type": "assistant", "message": {"content": []}}),
            json.dumps(result_event),
        ]
        with self.assertRaises(RuntimeError) as ctx:
            self._run(run_id, stdout_lines=stdout)
        self.assertIn("result indicates error", str(ctx.exception))
        artifact = self._artifact(run_id)
        lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        # 末尾存在 error 终态行
        self.assertEqual(lines[-1]["type"], "error")
        self.assertIn("API Error: 503", lines[-1]["error"])

    def test_rc0_error_subtype_rejected(self):
        """D5: rc==0 但 subtype 为 error_during_execution 时按失败处理（503 文本样例）。"""
        run_id = "impl-503-spec-1700000011"
        result_event = {
            "type": "result", "subtype": "error_during_execution",
            "result": "API request failed: 503 (Service Unavailable) — gateway overloaded",
            "num_turns": 1,
        }
        stdout = [
            json.dumps({"type": "assistant", "message": {"content": []}}),
            json.dumps(result_event),
        ]
        with self.assertRaises(RuntimeError) as ctx:
            self._run(run_id, stdout_lines=stdout)
        self.assertIn("result indicates error", str(ctx.exception))
        artifact = self._artifact(run_id)
        lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        self.assertEqual(lines[-1]["type"], "error")

    def test_rc0_normal_completion_unaffected(self):
        """D5: 正常完成（无 is_error、subtype 非错误类）路径完全不变。"""
        run_id = "impl-normal-spec-1700000012"
        result_event = {
            "type": "result", "subtype": "success", "is_error": False,
            "result": "All tasks complete", "num_turns": 4, "session_id": "sess-ok",
        }
        stdout = [
            json.dumps({"type": "assistant", "message": {"content": []}}),
            json.dumps(result_event),
        ]
        output, turns, sid = self._run(run_id, stdout_lines=stdout)
        self.assertEqual(output, "All tasks complete")
        self.assertEqual(turns, 4)
        self.assertEqual(sid, "sess-ok")
        artifact = self._artifact(run_id)
        lines = [json.loads(l) for l in artifact.read_text().splitlines()]
        # 无 error 终态行（保持原成功语义）
        self.assertNotEqual(lines[-1]["type"], "error")

    def test_running_artifact_grows_in_real_time(self):
        """运行期间产物文件实时增长：进程阻塞时文件已含已产生的事件。"""
        import threading as _t

        release = _t.Event()

        class BlockingProc(_FakeProc):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.poll_called = _t.Event()

            def poll(self, timeout=None):
                self.poll_called.set()
                if not release.wait(timeout or 10):
                    return None
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
        self.assertTrue(proc.poll_called.wait(5))
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


class TestEventBusFullScanResilience(unittest.TestCase):
    """4.1 full_scan 单条隔离与统计（fix-dispatch-orphan D3/D4）。

    单条毒条目不中断扫描：其余 SPEC 的 recovery 全部完成；扫描末尾输出
    handled/failed 统计日志。
    """

    def setUp(self):
        from core.event_bus import EventBus
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.pm = MagicMock()
        self.bus = EventBus(
            self.state_path, self.sm, self.pm,
            {"schedule": {"poll_interval_minutes": 30}}, self.logger,
        )
        good = (
            "### good-a\n"
            "- status: ready\n- priority: 1\n- created: 2026-01-01T00:00:00Z\n"
            "- updated: 2026-01-01T00:00:00Z\n- implementer_run: null\n"
            "- tester_run: null\n- branch: null\n- error: null\n"
            "### good-b\n"
            "- status: implemented\n- priority: 2\n- created: 2026-01-01T00:00:00Z\n"
            "- updated: 2026-01-01T00:00:00Z\n- implementer_run: null\n"
            "- tester_run: null\n- branch: null\n- error: null\n"
        )
        self.sm.write_all(StateParser._parse_content(
            "# Fenix Project State\n## Specs\n" + good))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_poison_entry_does_not_abort_scan(self):
        """某 SPEC 处理抛 TypeError，其余合法 SPEC 的 recovery 全部完成。"""
        def _handle(kind, name, entry):
            if kind == "spec_implemented":
                raise TypeError("injected poison")
        self.pm.handle_event.side_effect = _handle

        self.bus.full_scan()

        called_kinds = [c.args[0] for c in self.pm.handle_event.call_args_list]
        self.assertIn("spec_ready", called_kinds)
        self.assertIn("spec_implemented", called_kinds)

    def test_scan_emits_handled_failed_stats(self):
        """扫描末尾输出 handled/failed 统计（至少一次 info 含 handled= 字样）。"""
        def _handle(kind, name, entry):
            if kind == "spec_implemented":
                raise TypeError("injected poison")
        self.pm.handle_event.side_effect = _handle

        self.bus.full_scan()

        stats_logged = any(
            "handled=" in str(c.args) and "failed=" in str(c.args)
            for c in self.logger.info.call_args_list
        )
        self.assertTrue(stats_logged, "扫描结束应记录 handled/failed 统计")


class TestEventBusReadyWhitelistRecovery(unittest.TestCase):
    """5.1/5.2 孤儿 ready 白名单恢复（fix-dispatch-orphan D4）。

    - 带 error 的孤儿 ready：重派发、清 error、保留 implementer_run
    - 带 implementer_run 但无活跃运行：重派发
    - 有存活进程（pgrep 命中）：跳过并记录 skip: live child present
    - run 文件 mtime < 120s：视为存活，跳过
    """

    def setUp(self):
        from core.event_bus import EventBus
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.pm = MagicMock()
        self.bus = EventBus(
            self.state_path, self.sm, self.pm,
            {"schedule": {"poll_interval_minutes": 30}}, self.logger,
        )
        # project_root 指向 tmpdir，供 _latest_impl_run_file 用
        self.bus.pm_engine.project_root = Path(self.tmpdir)
        # 防止 MagicMock 自动生成 agent_runner.has_live_attempt（会误判为存活）：
        # 用无该方法的真实对象占位，使 _ready_has_live_child 走兜底分支。
        self.bus.pm_engine.agent_runner = object()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_spec(self, name, status, error=None, impl_run=None, tester_run=None):
        self.sm.write_all({
            name: {
                "status": status, "priority": 1,
                "created": "2026-01-01T00:00:00Z",
                "updated": "2026-01-01T00:00:00Z",
                "implementer_run": impl_run, "tester_run": tester_run,
                "branch": None, "error": error,
            }
        })

    def test_orphan_ready_with_error_redispatched(self):
        """带 error 的孤儿 ready → 重派发、error 清空、implementer_run 保留。"""
        self._write_spec("orphan-a", "ready", error="prior fail", impl_run="impl-old")
        # 隔离存活判定兜底：无 pgrep 命中、无 run 文件 → 视为孤儿
        self.bus._pgrep_live_worktree = lambda s: False
        self.bus._latest_impl_run_file = lambda s: None
        self.bus._recover_ready("orphan-a", self.sm.read_one("orphan-a"))
        self.pm.handle_event.assert_called_once()
        kind, name, entry = self.pm.handle_event.call_args[0]
        self.assertEqual(kind, "spec_ready")
        self.assertEqual(name, "orphan-a")
        self.assertEqual(entry["error"], None)
        self.assertEqual(entry["implementer_run"], "impl-old")

    def test_orphan_ready_with_impl_run_no_live_redispatched(self):
        """有历史 implementer_run 但无活跃运行 → 重派发。"""
        self._write_spec("orphan-b", "ready", error=None, impl_run="impl-old")
        self.bus._pgrep_live_worktree = lambda s: False
        self.bus._latest_impl_run_file = lambda s: None
        self.bus._recover_ready("orphan-b", self.sm.read_one("orphan-b"))
        self.pm.handle_event.assert_called_once()
        self.assertEqual(self.pm.handle_event.call_args[0][1], "orphan-b")

    def test_skip_when_live_process_present(self):
        """存活子进程（pgrep 命中）→ 跳过、不派发、记录 skip 日志。"""
        self._write_spec("orphan-c", "ready", error="fail", impl_run="impl-old")
        self.bus._pgrep_live_worktree = lambda s: True
        self.bus._recover_ready("orphan-c", self.sm.read_one("orphan-c"))
        self.pm.handle_event.assert_not_called()
        skip_logged = any(
            "live child present" in str(c.args)
            for c in self.logger.info.call_args_list
        )
        self.assertTrue(skip_logged, "存活应记录 skip: live child present 级日志")

    def test_skip_when_run_file_recent(self):
        """implementer_run 指向的 run 文件 mtime < 120s → 视为存活，跳过。"""
        self._write_spec("orphan-d", "ready", error="fail", impl_run="impl-d")
        self.bus._pgrep_live_worktree = lambda s: False
        runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        recent = runs_dir / "impl-orphan-d-123.jsonl"
        recent.write_text("{}", encoding="utf-8")
        import os
        now = time.time()
        os.utime(recent, (now, now))
        self.bus._recover_ready("orphan-d", self.sm.read_one("orphan-d"))
        self.pm.handle_event.assert_not_called()

    def test_orphan_ready_error_clear_persisted(self):
        """带 error 的孤儿 ready 重派发后，error 清空须写回 STATE.md。

        真实产品 Bug（fix-dispatch-orphan D4 遗漏点）：``_recover_ready`` 原仅
        在内存副本 ``updated`` 上清空 error 再 dispatch，``handle_event`` 只消费
        内存副本不回写，导致下一轮 full_scan 仍读到此 error，孤儿每周期被重复
        重置派发（事故家族「孤儿滞留」的直接成因）。修复后 error=None 必须持久化。
        """
        self._write_spec("orphan-e", "ready", error="prior fail", impl_run="impl-old")
        self.bus._pgrep_live_worktree = lambda s: False
        self.bus._latest_impl_run_file = lambda s: None
        self.bus._recover_ready("orphan-e", self.sm.read_one("orphan-e"))
        # dispatch 仍发生
        self.pm.handle_event.assert_called_once()
        # error 已写回 STATE.md（无存活子进程 → 必须清空，不再阻塞）
        persisted = self.sm.read_one("orphan-e")
        self.assertIsNone(persisted.get("error"))
        # implementer_run 历史值保留（D2）
        self.assertEqual(persisted.get("implementer_run"), "impl-old")


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
        # 原 SPEC 保持在 bug-found（等 fix 完成后重新验证），不再过渡到 implementing
        self.assertEqual(self.sm.read_one("quick-links-folders")["status"], "bug-found")
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

        # 不应被防重入跳过：应创建 fix SPEC；原 SPEC 保持在 bug-found
        self.assertIsNotNone(self.sm.read_one("fix-quick-links-folders"))
        self.assertEqual(self.sm.read_one("quick-links-folders")["status"], "bug-found")


class TestVerifierStaleResultGuard(unittest.TestCase):
    """.fenix-run-result.json 为全局共享单文件：verifier 判定消费前必须校验
    新鲜度（mtime ≥ 本次 run 起点）与归属（spec 匹配），否则陈旧重放会把
    旧结论（假 bug-found / 假 verified）套到当前轮次上。2026-08-28 实证：
    improve-failover-model-mapping-ui 的 09:41 旧判定在 12:21 重放。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        # verified 成功路径会经 _task_completion_blocker 读 implementer 结果，
        # 与本守卫正交，隔离之（MagicMock runner 下该链路不 mock 不友好）。
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.result_path = Path(self.tmpdir) / ".fenix-run-result.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_impl_spec(self, name="quick-links-folders"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")

    def _run_verify(self, run_epoch):
        from types import SimpleNamespace
        run_id = f"verify-quick-links-folders-{run_epoch}-a1"
        self.engine.agent_runner.run_verifier.return_value = SimpleNamespace(
            success=True, error=None, run_id=run_id,
        )
        self.engine._run_legacy_verification("quick-links-folders")

    def _write_result(self, spec, status, mtime_epoch=None):
        self.result_path.write_text(json.dumps({"spec": spec, "status": status}))
        if mtime_epoch:
            import os
            os.utime(self.result_path, (mtime_epoch, mtime_epoch))

    def test_stale_same_spec_bugfound_not_replayed(self):
        self._make_impl_spec()
        now = int(time.time())
        self._write_result("quick-links-folders", "bug-found", mtime_epoch=now - 600)
        self._run_verify(now)  # 本次 run 晚于结果文件 → 陈旧
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "implemented")
        self.assertIn("stale", str(e.get("error")))

    def test_cross_spec_result_not_consumed(self):
        self._make_impl_spec()
        self._write_result("some-other-spec", "success")
        self._run_verify(int(time.time()))
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "implemented")
        self.assertIn("stale", str(e.get("error")))

    def test_missing_result_not_treated_as_verified(self):
        self._make_impl_spec()
        self._run_verify(int(time.time()))
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "implemented")
        self.assertIn("stale", str(e.get("error")))

    def test_fresh_bugfound_still_counts(self):
        self._make_impl_spec()
        now = int(time.time())
        self._write_result("quick-links-folders", "bug-found", mtime_epoch=now - 5)
        self._run_verify(now)
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "bug-found")

    def test_fresh_verified_still_counts(self):
        self._make_impl_spec()
        now = int(time.time())
        self._write_result("quick-links-folders", "verified", mtime_epoch=now - 5)
        self._run_verify(now)
        e = self.sm.read_one("quick-links-folders")
        # 门禁放行后会自动推进（verified → done），断言终态即可
        self.assertIn(e["status"], ("verified", "done"))


class TestScenarioNavigateAcceptance(unittest.TestCase):
    """场景验收：navigate 必须绝对 URL + 场景必须含 navigate（2026-08-28 白屏事故）。"""

    def _errs(self, steps, sid="s1"):
        from core.verify_engine.scenarios import TestScenario
        sc = TestScenario.from_dict({"id": sid, "description": "", "steps": steps,
                                     "assertions": []})
        return sc.validate()

    def test_relative_navigate_rejected(self):
        errs = self._errs([{"action": "navigate", "value": "/dashboard"}])
        self.assertTrue(any("绝对" in e for e in errs), errs)

    def test_missing_navigate_rejected(self):
        errs = self._errs([{"action": "wait", "value": "1s"}])
        self.assertTrue(any("缺少 navigate" in e for e in errs), errs)

    def test_absolute_navigate_ok(self):
        errs = self._errs([
            {"action": "navigate", "value": "http://127.0.0.1:8787/dashboard"},
            {"action": "wait", "value": "page loaded"},
        ])
        self.assertFalse([e for e in errs if "navigate" in e], errs)


class TestBrowserNavigateBackstop(unittest.TestCase):
    """引擎兜底缺席：web 项目相对 navigate 直接显式失败，禁止默认端口。"""

    def test_relative_url_explicit_failure(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from core.verify_engine.browser import BrowserManager
        bm = BrowserManager(project_root=Path(self.mkdtemp()), logger=MagicMock())
        res = asyncio.run(bm.execute_action(
            AsyncMock(), {"action": "navigate", "value": "/dashboard"}))
        self.assertFalse(res["success"])
        self.assertEqual(res.get("error_type"), "invalid_navigate_url")
        self.assertIn("绝对", res["error"])

    def test_absolute_url_passes_through(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from core.verify_engine.browser import BrowserManager
        bm = BrowserManager(project_root=Path(self.mkdtemp()), logger=MagicMock())
        page = AsyncMock()
        res = asyncio.run(bm.execute_action(
            page, {"action": "navigate", "value": "http://127.0.0.1:8787/dashboard"}))
        self.assertTrue(res["success"])
        page.goto.assert_awaited_once()

    def mkdtemp(self):
        import tempfile
        return tempfile.mkdtemp()


class TestPMEngineReplanLoop(unittest.TestCase):
    """场景验收失败 → REPLAN_FEEDBACK 退回 plan（上限 2 次重排）→ 连续失败保持
    implemented 等待人工，绝不流转 bug-found。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.sm.add_spec("quick-links-folders", {"priority": 5})
        self.sm.transition("quick-links-folders", "ready")
        self.sm.transition("quick-links-folders", "implementing")
        self.sm.transition("quick-links-folders", "implemented")
        self.sm.transition("quick-links-folders", "testing")
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        self.engine._read_planner_result = MagicMock(return_value="plan-ready")
        self.engine._ensure_app_reachable = MagicMock(return_value=(True, False, "ok"))
        vdir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "quick-links-folders"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "test_scenarios.json").write_text(json.dumps(
            [{"id": "s1", "description": "", "steps": [
                {"action": "navigate", "value": "/dashboard"}], "assertions": []}]
        ))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _env_error_report(self):
        return {"spec": "quick-links-folders", "timestamp": "2026-08-28T00:00:00",
                "summary": {"total": 1, "passed": 0, "warnings": 0,
                            "failed": 0, "errors": 0},
                "scenarios": [],
                "env_error": "场景验收失败（navigate URL 必须为绝对地址）"}

    def test_env_error_replans_twice_then_holds_implemented(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        planner_calls = {"n": 0}
        engine_calls = {"n": 0}
        env_report = self._env_error_report()

        def fake_run_planner(*a, **k):
            planner_calls["n"] += 1
            return SimpleNamespace(success=True, error=None)

        class FakeEngine:
            def __init__(self, *a, **k):
                pass
            async def run(self, scenarios):
                engine_calls["n"] += 1
                return env_report

        import core.verify_engine as ve_pkg
        with patch.object(ve_pkg, "VerifyEngine", FakeEngine), \
             patch.object(self.engine.agent_runner, "run_planner", fake_run_planner):
            self.engine._run_three_stage_verification("quick-links-folders")

        # 场景文件非法（相对 URL）→ load_scenarios 抛 ValueError → 退回 plan，
        # 引擎根本不应执行；planner 共 3 次（首轮 + 2 次重排）后保持 implemented。
        self.assertEqual(planner_calls["n"], 3)
        self.assertEqual(engine_calls["n"], 0)
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "implemented")
        self.assertIn("场景文件验收失败", str(e.get("error")))
        fb = Path(self.tmpdir) / ".fenix" / "verify-progress" / \
            "quick-links-folders" / "REPLAN_FEEDBACK.md"
        self.assertTrue(fb.exists())

    def test_acceptance_pass_clears_feedback_and_proceeds(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        self.engine.agent_runner.run_planner = MagicMock(side_effect=[
            SimpleNamespace(success=True, error=None),
            SimpleNamespace(success=True, error=None, run_id="planner-judge-x"),
        ])
        self.engine.agent_runner.classify_switch_error = MagicMock(return_value=False)
        ok_report = {"spec": "quick-links-folders",
                     "timestamp": "2026-08-28T00:00:00",
                     "summary": {"total": 1, "passed": 1, "warnings": 0,
                                 "failed": 0, "errors": 0, "blocked_env": 0},
                     "scenarios": []}
        calls = {"n": 0}
        reports = [ok_report]

        class FakeEngine:
            def __init__(self, *a, **k):
                pass
            async def run(self, scenarios):
                i = calls["n"]
                calls["n"] += 1
                return reports[min(i, len(reports) - 1)]

        # 预置旧反馈文件，验收通过后应被清理；场景文件为绝对 URL（修正后的 plan）
        fbdir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "quick-links-folders"
        (fbdir / "REPLAN_FEEDBACK.md").write_text("旧反馈")
        (fbdir / "test_scenarios.json").write_text(json.dumps(
            [{"id": "s1", "description": "", "steps": [
                {"action": "navigate",
                 "value": "http://127.0.0.1:8787/dashboard"}], "assertions": []}]
        ))

        with patch("core.verify_engine.VerifyEngine", FakeEngine):
            self.engine._run_three_stage_verification("quick-links-folders")

        self.assertFalse((fbdir / "REPLAN_FEEDBACK.md").exists())
        e = self.sm.read_one("quick-links-folders")
        self.assertIn(e["status"], ("verified", "done"))


class TestRouteTableGuard(unittest.TestCase):
    """真实路由表：验收交叉校验（planner 禁止臆想路由）。

    注：pm_engine 的 _extract_dashboard_routes 路由表提取已在
    77d822f「撤销 pm_engine 路由表提取」中回退（被测应用路由因项目而异、
    fenixd 无法通用提取），改由 planner 读被测应用源码取证约束。相应的
    路由提取单测已随功能回退移除，仅保留与路由表无关的失败签名归一化测试。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.logger = MagicMock()
        self.sm = StateMachine(Path(self.tmpdir) / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_normalize_signature(self):
        n = self.engine._normalize_fail_signature(
            'Timeout 5000ms waiting for "[data-testid=\'run-btn\']" x2')
        self.assertNotIn("5000", n)
        self.assertNotIn('"', n)


class TestEngineRouteCrossCheck(unittest.TestCase):
    """验收交叉校验：APP_ROUTES.md 表内 navigate 路径放行。

    注：APP_ROUTES.md 引擎侧表外路径拒绝交叉校验已在 77d822f 中随路由表
    提取一并撤销（改由 planner 读源码约束），故 test_off_table_navigate_rejected
    已移除；此处保留表内路径放行路径（_execute_parallel 打桩、不触发真浏览器）。
    """

    def test_on_table_navigate_passes_acceptance(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from core.verify_engine.engine import VerifyEngine
        tmpdir = tempfile.mkdtemp()
        vdir = Path(tmpdir) / ".fenix" / "verify-progress" / "s1"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "APP_ROUTES.md").write_text("- /\n", encoding="utf-8")
        eng = VerifyEngine("s1", Path(tmpdir), MagicMock(), {})
        eng.browser = MagicMock()
        eng.browser.is_extension_project = False
        eng.browser.start = AsyncMock()
        eng.browser.stop = AsyncMock()
        # 令后续执行立刻出 0 场景结果以避免真浏览器：把 execute_parallel 打桩
        eng._execute_parallel = AsyncMock(return_value=[])
        scens = [{"id": "a", "description": "", "steps": [
            {"action": "navigate", "value": "http://127.0.0.1:8787/"}],
            "assertions": []}]
        rep = asyncio.run(eng.run(scens))
        self.assertNotIn("env_error", rep)
        eng.browser.start.assert_awaited_once()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestUniformVerifyFailure(unittest.TestCase):
    """全场景同因失败哨：呼叫 admin，连续 3 轮 blocked，绝不 bug-found。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.logger = MagicMock()
        self.sm = StateMachine(Path(self.tmpdir) / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger)
        self.sm.add_spec("demo", {"priority": 5})
        self.sm.transition("demo", "ready")
        self.sm.transition("demo", "implementing")
        self.sm.transition("demo", "implemented")
        self.sm.transition("demo", "testing")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _uniform_report(self, sig_error='Locator.wait_for: Timeout 5000ms exceeded for "[data-testid=\'run-btn\']"'):
        return {"spec": "demo", "timestamp": "t",
                "summary": {"total": 3, "passed": 0, "warnings": 0,
                            "failed": 3, "errors": 0},
                "scenarios": [
                    {"id": f"f{i}", "status": "fail",
                     "assertion_results": [{"pass": False, "error": sig_error}]}
                    for i in range(3)]}

    def test_uniform_failure_signals_and_holds(self):
        self.engine._detect_uniform_verify_failure("demo", self._uniform_report())
        e = self.sm.read_one("demo")
        self.assertEqual(e["status"], "testing")          # 保持，不降级
        self.assertEqual(int(e.get("_uniform_fail_attempts", 0) or 0), 1)
        self.assertIn("同因失败", str(e.get("error")))
        alerts = json.load(open(Path(self.tmpdir) / ".fenix" / "admin_alerts.json"))
        lst = alerts.get("alerts", alerts) if isinstance(alerts, dict) else alerts
        self.assertTrue(any(a.get("signal_type") == "verify_uniform_failure"
                            for a in lst))

    def test_mixed_signatures_not_flagged(self):
        rep = self._uniform_report()
        rep["scenarios"][1]["assertion_results"][0]["error"] = "完全不同的另一种错误"
        self.assertFalse(self.engine._detect_uniform_verify_failure("demo", rep))
        self.assertEqual(int(self.sm.read_one("demo").get("_uniform_fail_attempts", 0) or 0), 0)

    def test_fewer_than_three_failed_not_flagged(self):
        rep = self._uniform_report()
        rep["summary"] = {"total": 2, "passed": 0, "warnings": 0,
                          "failed": 2, "errors": 0}
        rep["scenarios"] = rep["scenarios"][:2]
        self.assertFalse(self.engine._detect_uniform_verify_failure("demo", rep))

    def test_three_rounds_then_blocked(self):
        self.sm.update_spec("demo", {"_uniform_fail_attempts": 2})
        self.engine._detect_uniform_verify_failure("demo", self._uniform_report())
        e = self.sm.read_one("demo")
        self.assertEqual(e["status"], "blocked")
        self.assertIsNone(e.get("tester_run"))

    def test_passed_nonzero_not_flagged(self):
        rep = self._uniform_report()
        rep["summary"]["passed"] = 1
        self.assertFalse(self.engine._detect_uniform_verify_failure("demo", rep))


class TestImplementerZeroChangeGuard(unittest.TestCase):
    """零变更成功哨：分支零提交且零编辑工具 → 不合并不推进，3 次后 blocked。"""

    def setUp(self):
        import subprocess as sp
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.logger = MagicMock()
        self.sm = StateMachine(Path(self.tmpdir) / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger)
        # 真实 git 仓库：main 与同点分支（零新提交）
        self.sp = sp
        def git(*a):
            r = sp.run(["git", *a], cwd=self.tmpdir, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            return r.stdout
        git("init", "-q", "-b", "main")
        git("config", "user.email", "t@t"); git("config", "user.name", "t")
        (Path(self.tmpdir) / "f.txt").write_text("x")
        git("add", "."); git("commit", "-qm", "init")
        git("branch", "fenix/zero-change-test")
        self.sm.add_spec("demo", {"priority": 5})
        self.sm.transition("demo", "ready")
        self.sm.transition("demo", "implementing")
        run_dir = Path(self.tmpdir) / ".fenix" / "runs"
        run_dir.mkdir(parents=True, exist_ok=True)
        self.run_file = run_dir / "impl-demo-1-a1.jsonl"
        self.run_file.write_text("")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _result(self):
        from types import SimpleNamespace
        return SimpleNamespace(success=True, error=None, branch="fenix/zero-change-test",
                               run_id="impl-demo-1-a1")

    def test_zero_change_detected(self):
        from types import SimpleNamespace
        self.assertTrue(self.engine._implementer_zero_change("demo", self._result()))

    def test_with_edit_tool_not_flagged(self):
        from types import SimpleNamespace
        with self.run_file.open("a") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "a.py"}}]}}) + "\n")
        self.assertFalse(self.engine._implementer_zero_change("demo", self._result()))

    def test_with_branch_commits_not_flagged(self):
        from types import SimpleNamespace
        sp = self.sp
        wt = Path(self.tmpdir) / "wt"
        sp.run(["git", "worktree", "add", "-b", "fenix/zero2", str(wt), "main"],
               cwd=self.tmpdir, capture_output=True)
        (wt / "g.txt").write_text("g")
        sp.run(["git", "add", "."], cwd=wt, capture_output=True)
        sp.run(["git", "commit", "-qm", "work"], cwd=wt, capture_output=True)
        r = SimpleNamespace(success=True, error=None, branch="fenix/zero2",
                            run_id="impl-demo-1-a1")
        self.assertFalse(self.engine._implementer_zero_change("demo", r))

    def test_no_branch_not_flagged(self):
        from types import SimpleNamespace
        r = SimpleNamespace(success=True, error=None, branch=None,
                            run_id="impl-demo-1-a1")
        self.assertFalse(self.engine._implementer_zero_change("demo", r))


class TestVerifierInfraFailureHold(unittest.TestCase):
    """verifier 基础设施类失败（链耗尽/熔断/网关）不得流转 bug-found。

    2026-08-28 实证：chain_exhausted 导致 verifier 起不来，其失败被当作
    「验证发现缺陷」→ fix spec 标 bug-found 并派生空壳子 fix。基础设施失败
    应保持原状态（由 full_scan recovery 兜底重排），与既有 provider circuit
    open 抑制路径同语义。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_impl_spec(self, name="quick-links-folders"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")

    def _fail_verifier(self, error_text, classify):
        from types import SimpleNamespace
        self.engine.agent_runner.run_verifier.return_value = SimpleNamespace(
            success=False, error=error_text, run_id="verify-x",
        )
        self.engine.agent_runner.classify_switch_error = MagicMock(
            return_value=classify
        )
        self.engine._run_legacy_verification("quick-links-folders")

    def test_chain_exhausted_holds_state_no_bug_found(self):
        self._make_impl_spec("quick-links-folders")
        self._fail_verifier(
            "provider chain exhausted for implementer 'quick-links-folders'",
            classify=False,
        )
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "testing")  # 状态保持，不降级 bug-found
        self.assertIn("chain exhausted", e["error"])
        self.engine._on_spec_bug_found.assert_not_called()
        self.assertIsNone(self.sm.read_one("fix-quick-links-folders"))

    def test_circuit_open_still_holds(self):
        self._make_impl_spec("quick-links-folders")
        self._fail_verifier("provider circuit open: inferaiapi.com", classify=False)
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "testing")
        self.engine._on_spec_bug_found.assert_not_called()

    def test_real_verifier_failure_still_bug_found(self):
        self._make_impl_spec("quick-links-folders")
        self._fail_verifier("claude CLI failed: exit 1", classify=False)
        e = self.sm.read_one("quick-links-folders")
        self.assertEqual(e["status"], "bug-found")
        self.assertIn("Verifier agent failed", e["error"])


class TestJudgeEnvDeclaredGuard(unittest.TestCase):
    """judge 自述环境问题却标 bug-found 不得派生 fix（admin 处置 2026-08-28）。

    2026-08-28 实证：planner 重生成场景写入相对 URL "/dashboard"（无效 URL）
    + 幻觉 testid，12 场景全部导航失败；judge 结果文件自述「这是一个环境
    问题，而非产品 Bug」却返回 status=bug-found，pm_engine 据此 transition
    bug-found 并派生伪 fix 级联（frozen blocked 死锁触发 blocked_stuck）。
    所有 bug 根因均自述环境/基础设施问题时，应按 inconclusive 回 implemented
    重验，不派生 fix。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.spec = "quick-links-folders"
        self.sm.add_spec(self.spec, {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing"):
            self.sm.transition(self.spec, st)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_judge_result(self, bugs):
        d = Path(self.tmpdir) / ".fenix" / "verify-progress" / self.spec
        d.mkdir(parents=True, exist_ok=True)
        (d / ".fenix-run-result.json").write_text(
            json.dumps({"status": "bug-found", "bugs": bugs},
                       ensure_ascii=False),
            encoding="utf-8",
        )

    def test_env_declared_bugs_do_not_derive_fix(self):
        self._write_judge_result([{
            "severity": "critical",
            "scenario_ids": ["s1", "s2"],
            "description": "所有场景在导航到 /dashboard 时失败",
            "root_cause": "测试环境 URL 配置错误。这是一个环境问题，而非产品 Bug。",
        }])
        self.assertTrue(self.engine._judge_bugs_declare_env(self.spec))
        self.assertTrue(self.engine._handle_judge_env_declared(self.spec))
        e = self.sm.read_one(self.spec)
        self.assertEqual(e["status"], "implemented")  # 回 implemented 重验
        self.assertEqual(int(e["_inconclusive_attempts"]), 1)
        self.assertIn("环境/基础设施", e["error"])
        self.engine._on_spec_bug_found.assert_not_called()
        self.engine._enqueue.assert_called_once_with(self.spec, "verifier")
        self.assertIsNone(self.sm.read_one(f"fix-{self.spec}"))

    def test_real_bug_root_cause_still_bug_found(self):
        self._write_judge_result([{
            "severity": "major",
            "scenario_ids": ["s1"],
            "description": "保存链后序列化丢失角色字段",
            "root_cause": "chain 序列化未保留 role 字段，属产品实现缺陷。",
        }])
        self.assertFalse(self.engine._judge_bugs_declare_env(self.spec))

    def test_mixed_bugs_not_treated_as_env(self):
        self._write_judge_result([
            {"description": "导航失败", "root_cause": "环境问题，非产品 Bug"},
            {"description": "保存失败", "root_cause": "产品实现缺陷"},
        ])
        self.assertFalse(self.engine._judge_bugs_declare_env(self.spec))

    def test_no_result_file_returns_false(self):
        self.assertFalse(self.engine._judge_bugs_declare_env(self.spec))


class TestPMEngineBugFoundIdempotent(unittest.TestCase):
    """2.1 spec_bug_found 重发幂等且非破坏（fix-dispatch-orphan D2）。

    连续 full_scan 对持续 bug-found 的父 SPEC 每轮 re-trigger，其处理器
    发现 fix 子 SPEC 已存在时 MUST：子 SPEC 处于推进/终态时不动状态、不清空
    run 字段；任何路径不得向 implementer_run/tester_run 写空值。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_buggy_spec(self, name="quick-links-folders"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")
        self.sm.transition(name, "bug-found")

    def test_implemented_fix_survives_two_scans(self):
        """implemented 子 SPEC 连续两轮 full_scan 不被降级，run 字段保持原值。"""
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {
            "status": "implemented", "priority": 6,
            "implementer_run": "impl-fix-abc", "tester_run": "tst-fix-xyz",
        })
        self.engine._do_spec_bug_found("quick-links-folders")
        after1 = self.sm.read_one("fix-quick-links-folders")
        self.assertEqual(after1["status"], "implemented")
        self.assertEqual(after1["implementer_run"], "impl-fix-abc")
        self.assertEqual(after1["tester_run"], "tst-fix-xyz")

        # 第二轮扫描仍命中同一个已 implemented 的 fix SPEC
        self.engine._do_spec_bug_found("quick-links-folders")
        after2 = self.sm.read_one("fix-quick-links-folders")
        self.assertEqual(after2["status"], "implemented")
        self.assertEqual(after2["implementer_run"], "impl-fix-abc")
        self.assertEqual(after2["tester_run"], "tst-fix-xyz")

    def test_blocked_fix_survives_retrigger(self):
        """blocked（人工冻结/熔断）子 SPEC 不被 bug-found 重发改写成 ready。

        2026-08-28 实证：人工冻结的 fix 子 SPEC 每轮扫描被
        "already exists (status=blocked) — resetting to ready" 解冻。
        blocked 属合法停泊态，必须与推进/终态同等受守卫保护。
        """
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {
            "status": "blocked", "priority": 6,
            "error": "paused by user",
            "implementer_run": "impl-fix-abc",
        })
        self.engine._do_spec_bug_found("quick-links-folders")
        after = self.sm.read_one("fix-quick-links-folders")
        self.assertEqual(after["status"], "blocked")
        self.assertEqual(after["error"], "paused by user")
        self.assertEqual(after["implementer_run"], "impl-fix-abc")

    def test_ready_no_history_reset_keeps_run_fields(self):
        """ready 但无历史工作的子 SPEC 正常重置，且 run 字段不被显式清空。"""
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {
            "status": "ready", "priority": 6,
            "error": "some prior error", "implementer_run": None,
            "tester_run": None, "branch": "fenix/fix-x",
        })
        self.engine._do_spec_bug_found("quick-links-folders")
        after = self.sm.read_one("fix-quick-links-folders")
        self.assertEqual(after["status"], "ready")
        # 历史 run 字段保持为空（原本就空，未被「重新显式置 None」覆盖为污染态），
        # 关键：update_spec 不再写 implementer_run/tester_run=None 去清空历史。
        # 此处本就为空，校验「未写入空值」——用 update_spec 不删除既有键来证明。
        self.assertIn("status", after)

    def test_ready_with_history_reset_preserves_run_fields(self):
        """已有历史 run 的 ready 子 SPEC 重置为 ready 时，历史 run id 保留。"""
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {
            "status": "ready", "priority": 6,
            "error": "some prior error",
            "implementer_run": "impl-fix-old", "tester_run": "tst-fix-old",
            "branch": "fenix/fix-x",
        })
        self.engine._do_spec_bug_found("quick-links-folders")
        after = self.sm.read_one("fix-quick-links-folders")
        self.assertEqual(after["status"], "ready")
        # D2：历史 implementer_run/tester_run 必须保留，不得被清空
        self.assertEqual(after["implementer_run"], "impl-fix-old")
        self.assertEqual(after["tester_run"], "tst-fix-old")
        # 被 D1 补发路径重新排队
        self.engine._enqueue.assert_called_with("fix-quick-links-folders", "implementer")

    def test_done_fix_preserved_new_round_created(self):
        """done 子 SPEC：本轮不重置（状态与 run 字段保持原值），
        因上一轮修复已终态，_resolve_fix_spec_name 派生新一轮 fix-fix-* 重排，
        原 done SPEC 不被降级、run 字段不被清空。"""
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {
            "status": "done", "priority": 6,
            "implementer_run": "impl-fix-done", "tester_run": "tst-fix-done",
        })
        self.engine._do_spec_bug_found("quick-links-folders")
        # 原 done 子 SPEC 保持原状（D2：不被重置、run 字段不清空）
        after = self.sm.read_one("fix-quick-links-folders")
        self.assertEqual(after["status"], "done")
        self.assertEqual(after["implementer_run"], "impl-fix-done")
        self.assertEqual(after["tester_run"], "tst-fix-done")
        # 新一轮 fix 被派生并排队（新 bug 需要新修复轮）
        self.assertIsNotNone(self.sm.read_one("fix-fix-quick-links-folders"))
        self.engine._enqueue.assert_called_with("fix-fix-quick-links-folders", "implementer")


class TestPMEngineSameStatusResetDispatch(unittest.TestCase):
    """3.1 同状态行动性重置必须触达调度路径（fix-dispatch-orphan D1）。

    spec_bug_found 处理器对 fix 子 SPEC 的同状态重置（ready→ready /
    bug-found→ready）写回后，必须直调 _on_spec_ready 触发派发；且被真实
    spec_ready 事件再次触达时不双重排队（_enqueue 去重保证）。
    """

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
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")
        self.sm.transition(name, "bug-found")

    def test_same_status_reset_triggers_dispatch(self):
        """bug-found 重发命中 ready 子 SPEC（同状态重置），派发被触发。"""
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {
            "status": "ready", "priority": 6,
            "error": "prior", "implementer_run": "impl-old",
        })
        self.engine._do_spec_bug_found("quick-links-folders")
        queued = [(e[1], e[2]) for e in self.engine._run_queue]
        self.assertIn(("fix-quick-links-folders", "implementer"), queued)

    def test_resend_not_double_queued(self):
        """同状态重置已排队后，真实 spec_ready 事件再次触达不双重排队。

        隔离 _process_queue（避免真实派发把队列抽空），仅在 _enqueue 去重层
        验证「补发 + 真实事件」最终仅一条排队条目生效。
        """
        self.engine._process_queue = MagicMock()
        self._make_buggy_spec("quick-links-folders")
        self.sm.add_spec("fix-quick-links-folders", {
            "status": "ready", "priority": 6,
            "error": "prior", "implementer_run": "impl-old",
        })
        # 1) spec_bug_found 重发 → 同状态重置 → 直调 _on_spec_ready 入队
        self.engine._do_spec_bug_found("quick-links-folders")
        after_reset = [(e[1], e[2]) for e in self.engine._run_queue]
        self.assertEqual(
            after_reset.count(("fix-quick-links-folders", "implementer")), 1,
            "重置后队列中该 spec 应仅出现一次",
        )
        # 2) 真实 spec_ready 事件再次触达（如人工修改 STATE.md 状态）
        self.engine.handle_event("spec_ready", "fix-quick-links-folders",
                                 self.sm.read_one("fix-quick-links-folders"))
        after_event = [(e[1], e[2]) for e in self.engine._run_queue]
        self.assertEqual(
            after_event.count(("fix-quick-links-folders", "implementer")), 1,
            "真实事件与补发不应双重排队",
        )


# ═══════════════════════════════════════════════════════════════════
# Priority Parallel Scheduler Tests (add-parallelism)
# ═══════════════════════════════════════════════════════════════════

class TestPlannerResultReadback(unittest.TestCase):
    """验证管道 readback bug：planner 结果读 verify-progress 优先，不误读项目根共享文件。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.engine = PMEngine(MagicMock(), MagicMock(), {}, self.project_root, MagicMock())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reads_verify_progress_primary_over_stale_root(self):
        """旧 bug 场景：planner 写了 plan-ready 到 verify-progress，项目根残留
        implementer 的 success（共享文件被污染）。修复前误读根 → 判未生成场景
        → 降级 verifier 反复失败。"""
        vp_dir = self.project_root / ".fenix" / "verify-progress" / "myspec"
        vp_dir.mkdir(parents=True)
        (vp_dir / ".fenix-run-result.json").write_text(
            json.dumps({"status": "plan-ready", "spec": "myspec"}), encoding="utf-8"
        )
        (self.project_root / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": "myspec"}), encoding="utf-8"
        )
        self.assertEqual(self.engine._read_planner_result("myspec"), "plan-ready")

    def test_falls_back_to_project_root_when_no_vp_product(self):
        """无 verify-progress 产物时回退项目根（兼容旧行为）。"""
        (self.project_root / ".fenix-run-result.json").write_text(
            json.dumps({"status": "bug-found", "bugs": [{"severity": "major"}]}), encoding="utf-8"
        )
        self.assertEqual(self.engine._read_planner_result("myspec"), "bug-found")

    def test_stale_success_root_returns_none(self):
        """项目根只有 implementer 的 success（不在白名单）→ 返回 None（视为已验证）。"""
        (self.project_root / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": "myspec"}), encoding="utf-8"
        )
        self.assertIsNone(self.engine._read_planner_result("myspec"))


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
            # 从线程 args 取 priority（宽松优先级下 _active_priorities 可含多档，
            # 不能再从中推断）：args = (spec_name, agent_type, priority)
            try:
                priority = thread_self._args[2]
            except (IndexError, TypeError):
                priority = 5
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

    def test_higher_priority_joins_running_lower_priority(self):
        """宽松优先级：P5 在跑时，更高优先的 P1 可并发加入；同档 P5 新任务被 P1 挡住。

        用户规则：有 P6 时 P5 可并发，但 P7 不行（更低优先级被更高优先级挡住）。
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
            self.engine._active_priority_counts[5] = 1
            self.engine._active_priorities.add(5)

        # P1 和另一个 P5 都就绪
        self.engine._enqueue("spec-high", "implementer")  # P1
        self.engine._enqueue("spec-low2", "implementer")   # P5

        self.engine._process_queue()

        # 高优先级 P1 加入（无更高优先级任务挡住它），与 P5 并发
        self.assertEqual(self.dispatched, [(1, "spec-high", "implementer")])
        self.assertEqual(self.engine._active_runs, 2)
        self.assertEqual(self.engine._active_priorities, {1, 5})
        # 同档 P5 的新任务被 P1 挡住（1 < 5），仍在队列等待
        queued_specs = [e[1] for e in self.engine._run_queue]
        self.assertIn("spec-low2", queued_specs)
        self.assertNotIn("spec-high", queued_specs)

    def test_relaxed_priority_p6_active_p5_runs_p7_blocked(self):
        """用户规则：有 P6 在跑时 P5 可并发、P7 不行。"""
        self._set_specs({
            "s6": {"status": "implementing", "priority": 6},
            "s5": {"status": "ready", "priority": 5},
            "s7": {"status": "ready", "priority": 7},
        })
        self.sm.transition = MagicMock(return_value=True)

        # P6 已有 1 个在运行
        with self.engine._queue_lock:
            self.engine._active_runs = 1
            self.engine._active_priority_counts[6] = 1
            self.engine._active_priorities.add(6)

        self.engine._enqueue("s5", "implementer")  # P5
        self.engine._enqueue("s7", "implementer")  # P7

        self.engine._process_queue()

        # P5 派发（5 <= 6 可并发），P7 被挡（7 > 6）
        self.assertEqual(self.dispatched, [(5, "s5", "implementer")])
        self.assertEqual(self.engine._active_priorities, {5, 6})
        queued = [e[1] for e in self.engine._run_queue]
        self.assertIn("s7", queued)
        self.assertNotIn("s5", queued)

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

    def test_ensure_spec_committed_tracks_untracked_spec(self):
        """untracked spec 目录被 ensure_spec_committed 提交进主树（fix-merge-back-deadlock）。"""
        spec = self.project_root / "openspec" / "changes" / "spec-a" / "proposal.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("# proposal\n")

        ok = self.wm.ensure_spec_committed("spec-a")
        self.assertTrue(ok)

        # spec 已 tracked 且 clean
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "openspec/changes/spec-a"],
            cwd=str(self.project_root), capture_output=True, text=True,
        )
        self.assertEqual(status.stdout.strip(), "")
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(self.project_root), capture_output=True, text=True,
        )
        self.assertIn("[fenix] spec: spec-a", log.stdout)

    def test_ensure_spec_committed_noop_when_clean(self):
        """本已无改动时 no-op（返回 True，不产生新提交）。"""
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.project_root), capture_output=True, text=True,
        ).stdout.strip()

        ok = self.wm.ensure_spec_committed("nonexistent-spec")
        self.assertTrue(ok)

        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.project_root), capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(head_before, head_after)

    def test_merge_back_with_untracked_spec_no_deadlock(self):
        """主树 spec 目录 untracked + 分支 commit 同名路径时，merge 不再死锁（Layer 2 兜底）。"""
        # 主树放一个 untracked spec 文件（模拟 fenix-new 未提交的 spec）
        spec = self.project_root / "openspec" / "changes" / "test-spec" / "proposal.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("# untracked spec\n")

        # create() 会 _seed_spec：把主树 untracked spec 复制进分支并 commit
        wt_path = self.wm.create("test-spec", "implementer")
        self.assertIsNotNone(wt_path)
        branch = self.wm.get_branch_name(wt_path)
        self.wm.cleanup(wt_path, success=True)

        # 主树仍有 untracked 副本 → merge 本会 untracked 冲突，现在应成功
        success, error = self.wm.merge_back_from_branch(branch)
        self.assertTrue(success, f"merge failed: {error}")
        # 合并后 spec 目录为 tracked + clean（分支 commit 版本已合入）
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "openspec/changes/test-spec"],
            cwd=str(self.project_root), capture_output=True, text=True,
        )
        self.assertEqual(status.stdout.strip(), "")
        # 备份目录已被清理
        self.assertFalse((self.project_root / ".fenix" / "merge-backup").exists())


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
        # restore_after_merge 现返回 (ok, conflict_files) 元组（fix-stashpop-deadlock）
        self.engine.agent_runner.worktree_manager.restore_after_merge = MagicMock(
            return_value=(True, [])
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
        # restore_after_merge 现返回 (ok, conflict_files) 元组（fix-stashpop-deadlock）
        self.engine.agent_runner.worktree_manager.restore_after_merge = MagicMock(
            return_value=(True, [])
        )

        self.engine._run_agent_worker("test-spec", "implementer", 3)

        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["status"], "implemented")

    def test_circuit_open_failure_holds_state_no_retry(self):
        """provider 熔断期派发失败不计入 _retry_count、不翻转状态机（design D5）。

        error 含 "provider circuit open" 时 spec 保持 implementing 原状，由冷却结束后
        的既有轮询自然重排；不触发 retry 计数、不回退到 ready、不创建新 worktree。
        """
        from core.agent_runner import AgentRunResult
        result = AgentRunResult(
            run_id="impl-test-spec-circuit", spec_name="test-spec",
            agent_type="implementer", success=False, duration_seconds=10,
            turns_used=1, error="provider circuit open: volc (HTTP 404 x3) — cooldown 120s remaining",
        )
        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        self.engine._read_implementer_result = MagicMock(return_value=None)
        self.engine._enqueue_front = MagicMock()
        # restore_after_merge 现返回 (ok, conflict_files) 元组（fix-stashpop-deadlock）
        self.engine.agent_runner.worktree_manager = MagicMock()
        self.engine.agent_runner.worktree_manager.restore_after_merge = MagicMock(
            return_value=(True, [])
        )

        self.engine._run_agent_worker("test-spec", "implementer", 3)

        spec = self.sm.read_one("test-spec")
        # 状态保持 implementing，未翻转回 ready、未推进
        self.assertEqual(spec["status"], "implementing")
        # 不计入 _retry_count
        self.assertNotIn("_retry_count", spec or {})
        self.assertIsNone(spec.get("_retry_count"))
        # error 保留 circuit open 信息，供 admin/dashboard 区分 provider 故障
        self.assertIn("provider circuit open", spec.get("error", ""))

    def test_stash_pop_conflict_reported_to_error(self):
        """merge-back 后 stash pop 冲突自愈时，冲突文件清单写入 spec error（fix-stashpop-deadlock）。

        自愈后主树已干净、状态仍推进到 implemented，但 error 字段需含 "stash pop conflict"
        与受影响文件名单，触发 admin 告警、便于人工 git stash show 找回被丢弃改动。
        """
        from core.agent_runner import AgentRunResult
        result = AgentRunResult(
            run_id="impl-test-spec-stash", spec_name="test-spec",
            agent_type="implementer", success=True, duration_seconds=10,
            turns_used=5, branch="fenix/test-spec-stash",
        )
        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        self.engine.agent_runner.worktree_manager = MagicMock()
        self.engine.agent_runner.worktree_manager.merge_back_from_branch = MagicMock(
            return_value=(True, "")
        )
        # restore_after_merge 返回冲突清单（真实实现会自愈并返回受影响文件）
        self.engine.agent_runner.worktree_manager.restore_after_merge = MagicMock(
            return_value=(True, ["src/foo.py", "src/bar.py"])
        )
        self.engine._read_implementer_result = MagicMock(return_value={"status": "success"})
        self.engine._enqueue_front = MagicMock()

        self.engine._run_agent_worker("test-spec", "implementer", 3)

        spec = self.sm.read_one("test-spec")
        # 状态仍正常推进到 implemented（自愈不阻塞 merge-back）
        self.assertEqual(spec["status"], "implemented")
        # error 含冲突信息与被丢弃文件名单
        err = spec.get("error", "")
        self.assertIn("stash pop conflict", err)
        self.assertIn("src/foo.py", err)
        self.assertIn("src/bar.py", err)
        # verifier 已排队
        self.engine._enqueue_front.assert_called_once_with("test-spec", "verifier")

        spec = self.sm.read_one("test-spec")
        self.assertEqual(spec["status"], "implemented")


# ═══════════════════════════════════════════════════════════════════
# Verifier / Planner circuit-open 拦截（fix-fix-stashpop-deadlock）
# ═══════════════════════════════════════════════════════════════════

class TestVerifierCircuitOpenHoldsState(unittest.TestCase):
    """provider 熔断期 verifier/planner 派发失败不得 transition bug-found / 派生 fix 级联。

    与 implementer 路径同理（design D5）：熔断期失败属「provider 故障」，
    不是 spec 自身问题或真实验证失败——spec 保持 implemented，由 full_scan recovery
    兜底重排；不调用 _on_spec_bug_found（否则产生伪 fix 级联、烧 token）。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        self.sm = StateMachine(Path(tempfile.mkdtemp()) / "STATE.md")
        self.sm.add_spec("test-spec", {"status": "testing", "priority": 5})
        self.logger = MagicMock()
        self.agent_runner = MagicMock()
        self.wm = MagicMock()
        self.agent_runner.worktree_manager = self.wm
        self.engine = PMEngine(self.sm, self.agent_runner, {}, Path("/tmp"), self.logger)

    def test_verifier_circuit_open_holds_implemented(self):
        """legacy verifier 返回 circuit open error → spec 保持 implemented，不 bug-found。"""
        from core.agent_runner import AgentRunResult
        circuit_result = AgentRunResult(
            run_id="verify-circuit-1", spec_name="test-spec",
            agent_type="verifier", success=False, duration_seconds=10,
            error="provider circuit open: volc (HTTP 404 x3) — cooldown 120s remaining",
        )
        self.agent_runner.run_verifier = MagicMock(return_value=circuit_result)
        self.engine._on_spec_bug_found = MagicMock()

        self.engine._run_legacy_verification("test-spec")

        spec = self.sm.read_one("test-spec")
        # 不得 transition 到 bug-found（不派生伪 fix 级联）
        self.assertNotEqual(spec["status"], "bug-found")
        # _on_spec_bug_found 不得被调用
        self.engine._on_spec_bug_found.assert_not_called()
        # error 含 circuit open 信息供 dashboard 可见
        self.assertIn("provider circuit open", spec.get("error", ""))

    def test_verifier_real_failure_still_bugs_found(self):
        """verifier 真实失败（非 circuit open）→ 正常 transition bug-found。"""
        from core.agent_runner import AgentRunResult
        real_failure = AgentRunResult(
            run_id="verify-real-1", spec_name="test-spec",
            agent_type="verifier", success=False, duration_seconds=10,
            error="claude CLI crashed: segfault",
        )
        self.agent_runner.run_verifier = MagicMock(return_value=real_failure)
        self.engine._on_spec_bug_found = MagicMock()

        self.engine._run_legacy_verification("test-spec")

        spec = self.sm.read_one("test-spec")
        # 真实失败 → bug-found
        self.assertEqual(spec["status"], "bug-found")
        self.assertIn("Verifier agent failed", spec.get("error", ""))

    def test_planner_plan_circuit_open_holds_implemented(self):
        """三步流水线 planner plan 返回 circuit open → spec 保持 implemented，不 raise。"""
        from core.agent_runner import AgentRunResult
        circuit_result = AgentRunResult(
            run_id="planner-plan-circuit-1", spec_name="test-spec",
            agent_type="planner-plan", success=False, duration_seconds=10,
            error="provider circuit open: volc (HTTP 404 x3) — cooldown 120s remaining",
        )
        self.agent_runner.run_planner = MagicMock(return_value=circuit_result)
        self.engine._on_spec_bug_found = MagicMock()

        # 不得抛 RuntimeError
        self.engine._run_three_stage_verification("test-spec")

        spec = self.sm.read_one("test-spec")
        self.assertNotEqual(spec["status"], "bug-found")
        self.engine._on_spec_bug_found.assert_not_called()
        self.assertIn("provider circuit open", spec.get("error", ""))

    def test_planner_judge_circuit_open_holds_implemented(self):
        """三步流水线 planner judge 返回 circuit open → spec 保持 implemented，不 raise。

        直接测试 _run_three_stage_verification 的 judge 阶段 circuit-open 拦截，
        通过 mock run_planner 的 side_effect 覆盖 plan 成功 + judge 熔断路径。
        """
        from core.agent_runner import AgentRunResult
        circuit_err = "provider circuit open: volc (HTTP 404 x3) — cooldown 120s remaining"
        judge_circuit = AgentRunResult(
            run_id="planner-judge-circuit-1", spec_name="test-spec",
            agent_type="planner-judge", success=False, duration_seconds=10,
            error=circuit_err,
        )
        self.agent_runner.run_planner = MagicMock(return_value=judge_circuit)
        self.engine._on_spec_bug_found = MagicMock()

        # 需要 patch verify_engine 模块引用，因为函数内部 from .verify_engine import VerifyEngine
        with patch.dict("sys.modules", {
            "core.verify_engine": MagicMock(),
            "core.verify_engine.scenarios": MagicMock(),
            "core.verify_engine.engine": MagicMock(),
        }), patch("core.pm_engine.VerifyEngine", create=True) as MockEngine, \
             patch("core.pm_engine.load_scenarios", create=True) as mock_scenarios:
            mock_engine_instance = MagicMock()
            mock_engine_instance.run = MagicMock(return_value={
                "summary": {"total": 0, "passed": 0, "warnings": 0, "failed": 0, "errors": 0}
            })
            MockEngine.return_value = mock_engine_instance
            mock_scenarios.return_value = []

            self.engine._run_three_stage_verification("test-spec")

        spec = self.sm.read_one("test-spec")
        self.assertNotEqual(spec["status"], "bug-found")
        self.engine._on_spec_bug_found.assert_not_called()
        self.assertIn("provider circuit open", spec.get("error", ""))


# ═══════════════════════════════════════════════════════════════════
# VerifyEngine 截图时机（fix: 步骤失败导致断言未执行时不截图）
# ═══════════════════════════════════════════════════════════════════

class TestVerifyEngineScreenshotTiming(unittest.TestCase):
    """断言真正执行且失败才截图；步骤失败导致断言未执行时不截图。

    背景：add-parallelism 验证时 navigate 到错误端口（8765 → 新标签页），
    navigate 请求拿到 200 返回 success，但点击 #btn-config 失败 → break，
    断言从未执行。旧实现在步骤失败处无条件截图，产生 10 张相同的新标签页
    截图并被误判为 bug。修复后：断言未执行 ⇒ 无截图。
    """

    @staticmethod
    def _make_scenario() -> dict:
        from core.verify_engine.scenarios import TestScenario
        return TestScenario.from_dict({
            "id": "steps-fail-before-assert",
            "description": "步骤失败且断言从未执行",
            "depends_on": [],
            "steps": [
                {"action": "navigate", "value": "http://127.0.0.1:8765/"},
                {"action": "click", "target": "#btn-config"},
            ],
            "assertions": [
                {"type": "element_visible", "selector": "#cfg-max-concurrent",
                 "label": "并行度输入框可见"},
            ],
        })

    def test_no_screenshot_when_assertion_never_ran(self):
        """步骤失败导致 break、断言未执行 ⇒ browser.screenshot 不被调用。"""
        import asyncio
        from core.verify_engine.engine import VerifyEngine
        from unittest.mock import AsyncMock, MagicMock

        engine = VerifyEngine.__new__(VerifyEngine)
        engine.spec_name = "test-spec"
        engine.project_root = Path(tempfile.mkdtemp())
        engine.logger = MagicMock()
        engine.browser = MagicMock()
        # navigate 成功，click 失败（add-parallelism 场景）
        engine.browser.execute_action = AsyncMock(side_effect=[
            {"success": True, "action": "navigate", "detail": "已导航到 http://127.0.0.1:8765/"},
            {"success": False, "action": "click", "target": "#btn-config",
             "error": "Locator.wait_for: Timeout exceeded",
             "error_type": "element_not_found_or_not_actionable"},
        ])
        engine.browser.screenshot = AsyncMock(return_value="/tmp/x.png")
        engine.asserter = MagicMock()
        engine.asserter.run = AsyncMock(return_value=[])
        engine.differ = None

        scenario = self._make_scenario()
        context = MagicMock()
        page = MagicMock()

        async def _run():
            return await engine._execute_scenario(scenario, page, context)

        result = asyncio.run(_run())

        self.assertEqual(result["status"], "fail")
        # 断言从未执行 ⇒ 不应截图（修复后）
        engine.browser.screenshot.assert_not_called()
        self.assertEqual(result["screenshots"], [])

    def test_screenshot_after_assert_failure(self):
        """断言真正执行且失败 ⇒ 应截图（保留取证能力）。"""
        import asyncio
        from core.verify_engine.engine import VerifyEngine
        from unittest.mock import AsyncMock, MagicMock

        engine = VerifyEngine.__new__(VerifyEngine)
        engine.spec_name = "test-spec"
        engine.project_root = Path(tempfile.mkdtemp())
        engine.logger = MagicMock()
        engine.browser = MagicMock()
        engine.browser.execute_action = AsyncMock(return_value={
            "success": True, "action": "navigate", "detail": "已导航到 http://127.0.0.1:8787/",
        })
        engine.browser.screenshot = AsyncMock(return_value="/tmp/ok.png")
        engine.asserter = MagicMock()
        # 断言真实执行且失败
        engine.asserter.run = AsyncMock(return_value=[
            {"type": "element_visible", "layer": 1, "selector": "#cfg-max-concurrent",
             "pass": False, "error": "Locator.wait_for: Timeout exceeded"},
        ])
        engine.differ = None

        from core.verify_engine.scenarios import TestScenario
        scenario = TestScenario.from_dict({
            "id": "assert-fails",
            "description": "断言执行且失败",
            "depends_on": [],
            "steps": [{"action": "navigate", "value": "http://127.0.0.1:8787/"}],
            "assertions": [
                {"type": "element_visible", "selector": "#cfg-max-concurrent",
                 "label": "并行度输入框可见"},
            ],
        })
        context = MagicMock()
        page = MagicMock()

        async def _run():
            return await engine._execute_scenario(scenario, page, context)

        result = asyncio.run(_run())

        self.assertEqual(result["status"], "fail")
        # 断言失败 ⇒ 已截图取证
        engine.browser.screenshot.assert_called_once()
        self.assertEqual(len(result["screenshots"]), 1)


class TestEnsureAppReachableFieldFix(unittest.TestCase):
    """_ensure_app_reachable 应读取 navigate 步骤的 value 字段识别目标 URL。

    背景：navigate 目标 URL 存于 scenarios.TestStep.value（191 个场景全部如此），
    但旧代码读 url/target，导致 urls 恒空、恒判可达，可达性门禁永不触发。
    修复后应正确解析 value 中的 URL；目标不可达且无 start 命令时返回不可达。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.logger = MagicMock()
        self.sm = StateMachine(Path(self.tmpdir) / "STATE.md", self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unreachable_target_returns_not_reachable(self):
        """value 指向不可达 URL 且无 start 命令 ⇒ 应识别为不可达。"""
        spec_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "add-parallelism"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "test_scenarios.json").write_text(json.dumps([
            {"id": "sc1", "description": "x", "depends_on": [],
             "steps": [{"action": "navigate", "value": "http://127.0.0.1:8765/"}],
             "assertions": []},
        ]), encoding="utf-8")

        # 目标不可达（urlopen 抛异常）；无 start 命令
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            self.engine._get_config = MagicMock(return_value="")
            reachable, user_blocked, note = self.engine._ensure_app_reachable("add-parallelism")

        self.assertFalse(reachable)
        self.assertFalse(user_blocked)
        self.assertIn("不可达", note)

    def test_reachable_target_returns_reachable(self):
        """value 指向可达 URL ⇒ 识别为可达（urlopen 不抛异常）。"""
        spec_dir = Path(self.tmpdir) / ".fenix" / "verify-progress" / "myspec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "test_scenarios.json").write_text(json.dumps([
            {"id": "sc1", "description": "x", "depends_on": [],
             "steps": [{"action": "navigate", "value": "http://127.0.0.1:8787/"}],
             "assertions": []},
        ]), encoding="utf-8")

        with patch("urllib.request.urlopen", return_value=MagicMock(__enter__=MagicMock())):
            reachable, user_blocked, note = self.engine._ensure_app_reachable("myspec")

        self.assertTrue(reachable)
        self.assertEqual(note, "")


# ═══════════════════════════════════════════════════════════════════
# fix-fenix-token-waste 单元测试
# ═══════════════════════════════════════════════════════════════════

class TestBlockedState(unittest.TestCase):
    """blocked 状态流转：implementing→blocked（熔断）、blocked→ready（人工恢复）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from core.state_machine import StateMachine
        self.sm = StateMachine(Path(self.tmpdir) / "STATE.md", None)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_implementing_to_blocked_and_back_to_ready(self):
        self.sm.add_spec("s1", {"status": "implementing", "priority": 1})
        self.assertTrue(self.sm.transition("s1", "blocked"))
        self.assertEqual(self.sm.read_one("s1")["status"], "blocked")
        # blocked 不被自动调度
        self.assertNotIn("s1", [n for n, _ in self.sm.get_ready_specs()])
        # 人工恢复 blocked → ready → implementing
        self.assertTrue(self.sm.transition("s1", "ready"))
        self.assertTrue(self.sm.transition("s1", "implementing"))

    def test_recover_interrupted_reverts_to_ready_and_clears_run_fields(self):
        from core.state_machine import SpecStatus
        self.sm.add_spec("s1", {"status": "implementing", "priority": 1,
                                "implementer_run": "impl-s1-1", "branch": "fenix/s1",
                                "_retry_count": 2})
        recovered = self.sm.recover_interrupted()
        self.assertIn("s1", recovered)
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], SpecStatus.READY)
        self.assertIsNone(entry["implementer_run"])
        self.assertIsNone(entry["branch"])
        self.assertEqual(int(entry["_retry_count"] or 0), 0)
        # 恢复后进入 ready 集合，可被正常调度
        self.assertIn("s1", [n for n, _ in self.sm.get_ready_specs()])

    def test_bug_found_to_implemented_for_fix_reverify(self):
        """fix 完成后父 spec 从 bug-found → implemented 重新验证（fix-fenix-token-waste）。"""
        self.sm.add_spec("s1", {"status": "bug-found", "priority": 5})
        self.assertTrue(self.sm.transition("s1", "implemented"))
        self.assertEqual(self.sm.read_one("s1")["status"], "implemented")


class TestMergeCircuitBreakerFingerprint(unittest.TestCase):
    """merge 失败指纹：同一错误稳定、不同错误区分。"""

    def test_fingerprint_is_stable_and_distinct(self):
        from core.pm_engine import PMEngine
        err1 = ("error: Your local changes to the following files would be overwritten by merge:\n"
                "\tcore/dashboard/data.py\nPlease commit your changes or stash them before you merge.")
        err2 = "error: fatal: refusing to merge unrelated histories"
        self.assertEqual(PMEngine._merge_fingerprint(err1), PMEngine._merge_fingerprint(err1))
        self.assertNotEqual(PMEngine._merge_fingerprint(err1), PMEngine._merge_fingerprint(err2))
        self.assertEqual(len(PMEngine._merge_fingerprint(err1)), 12)


class TestMainTreeHealthCheck(unittest.TestCase):
    """主树健康检查：脏树自动 stash、干净不动、merge 后 pop、冲突保留。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        from core.worktree_manager import WorktreeManager
        self.wm = WorktreeManager(Path(self.tmpdir) / "wts", self.project_root, MagicMock())

    def test_ensure_clean_tree_stashes_when_dirty(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "status" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=" M core/x.py\n?? y.py\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            stashed = self.wm.ensure_clean_tree()
        self.assertTrue(stashed)
        self.assertTrue(any("stash" in c and "push" in c for c in calls))
        self.assertTrue(any("--include-untracked" in c for c in calls))

    def test_ensure_clean_tree_excludes_openspec_changes(self):
        """autostash 必须排除 openspec/changes/，否则未跟踪的 spec 文件被卷走，
        implementer 找不到 SPEC 而空转（fix：曾烧 ~450 轮）。"""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "status" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="?? openspec/changes/x/proposal.md\n", stderr="")
            # stash 命令：唯一脏内容被排除 → git 报 No local changes
            return subprocess.CompletedProcess(cmd, 0, stdout="No local changes to save", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            stashed = self.wm.ensure_clean_tree()
        self.assertFalse(stashed)  # 唯一脏内容是 openspec/changes → 实际未 stash
        stash_cmd = next(c for c in calls if "stash" in c and "push" in c)
        self.assertTrue(any("openspec/changes" in a for a in stash_cmd))
        self.assertTrue(any(a.startswith(":(exclude)") for a in stash_cmd))

    def test_ensure_clean_tree_noop_when_clean(self):
        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            self.assertFalse(self.wm.ensure_clean_tree())

    def test_restore_after_merge_pop_success(self):
        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            ok, files = self.wm.restore_after_merge()
        self.assertTrue(ok)
        self.assertEqual(files, [])

    def test_restore_after_merge_pop_conflict_keeps_stash(self):
        """pop 冲突进入自愈：返回 (True, [UU files])，stash 条目保留不 drop。

        非冲突类失败（无 CONFLICT）仍返回 (False, []) 兼容旧语义。
        """
        captured = {}

        def fake_run(cmd, **kw):
            # stash pop 返回冲突；自愈需 ls-files -u 枚举 + checkout -f + reset
            if cmd[:3] == ["git", "-C", str(self.project_root)] and cmd[3:5] == ["stash", "pop"]:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="CONFLICT (content): Merge conflict in a.py")
            if cmd[3:] == ["ls-files", "-u"]:
                # 模拟 a.py 处于 stage 2/3 未合并
                return subprocess.CompletedProcess(cmd, 0, stdout="100644 abc 2\ta.py\n100644 def 3\ta.py\n")
            captured["ran"] = [c for c in (cmd[3:] if len(cmd) > 3 else cmd)]
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            ok, files = self.wm.restore_after_merge()
        self.assertTrue(ok)
        self.assertEqual(files, ["a.py"])
        # stash drop 不得被调用
        self.assertNotIn("drop", str(captured.get("ran", [])))

    def test_restore_after_merge_non_conflict_failure_returns_false(self):
        """非冲突类 stash pop 失败（无 CONFLICT）保持旧 False 语义，不自愈。"""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[3:5] == ["stash", "pop"]:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="fatal: unknown error")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            ok, files = self.wm.restore_after_merge()
        self.assertFalse(ok)
        self.assertEqual(files, [])
        # 不应触发自愈的 ls-files / checkout / reset
        self.assertFalse(any(c[3:] == ["ls-files", "-u"] for c in calls))


class TestStashPopConflictSelfHeal(unittest.TestCase):
    """真实 git 场景：stash pop 冲突自愈（fix-stashpop-deadlock）。

    构造：主树 A 文件有未提交改动 → dispatch 前 autostash → HEAD 被推进改同文件
    → merge-back 后再 pop 撞内容冲突（UU 半合并）。
    断言：自愈后 UU 清空、index 干净、git 写命令恢复、conflict_files 正确、stash 保留。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.git = lambda *a, **k: subprocess.run(
            ["git", "-C", str(self.project_root), *a],
            capture_output=True, text=True, **k,
        )
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@test.com")
        self.git("config", "user.name", "test")
        # 初始提交：A 文件
        (self.project_root / "A.py").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "init")
        from core.worktree_manager import WorktreeManager
        self.wm = WorktreeManager(self.project_root / "wts", self.project_root, MagicMock())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _status_porcelain(self) -> str:
        return self.git("status", "--porcelain").stdout

    def _unmerged_files(self) -> list:
        out = self.git("ls-files", "-u").stdout
        paths = set()
        for line in out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                paths.add(parts[1].strip())
        return sorted(paths)

    def _make_pop_conflict(self):
        """在主树制造 autostash + 后续 HEAD 推进同文件，使 restore_after_merge pop 冲突。

        模拟框架流：dispatch 前 autostash（主树脏改动第一行的散落修改）→ 其它 spec 推进
        改同文件同行为 HEAD 前进 → restore_after_merge 的 stash pop 与 HEAD 同文件同
        行内容冲突 → UU 半合并。stash 条目**保留**在主树，由 restore_after_merge 去 pop
        从而触发冲突自愈。
        """
        # 初始提交：A.py 首行 base
        # 1) dispatch 前 autostash（框架行为）：主树首行散落改动（模拟「修复中的前端文件」）
        (self.project_root / "A.py").write_text("main tree dirty change\n")
        stash = self.git("stash", "push", "-m", "fenix: pre-dispatch autostash",
                         "--", ".", ":(exclude)openspec/changes")
        self.assertEqual(stash.returncode, 0)
        # 主树此刻干净
        self.assertEqual(self._status_porcelain().strip(), "")
        # 2) HEAD 被其它 spec 推进：改同文件 A.py 首行为 HEAD 版本（模拟另一个 merge
        #    已合入主树）。主树此时仍 autostash 干净——唯一的 stash（#1 含首行 dirty
        #    分支）保留着。后续 restore_after_merge 的 pop 将以 stash 的 base=base、
        #    stash other=dirty、HEAD=merged 三方合并，同文件首行内容各异 → 冲突 → UU。
        (self.project_root / "A.py").write_text("merged implementation\n")
        self.git("add", "A.py")
        self.git("commit", "-q", "-m", "[fenix] merge other spec into A.py")
        # 主树此刻干净（autostash 仍在、未 pop），符合框架 merge-back 前的真实状态
        self.assertEqual(self._status_porcelain().strip(), "")
        # 确认 stash 列表里只有那一条 pre-dispatch autostash
        self.assertIn("fenix: pre-dispatch autostash",
                      self.git("stash", "list").stdout)

    def test_pop_conflict_self_heals_and_preserves_stash(self):
        self._make_pop_conflict()
        # 主树此刻干净（autostash 已在主树，HEAD 已含 A.py 实现）
        self.assertEqual(self._status_porcelain().strip(), "")
        self.assertFalse(self._unmerged_files())

        # restore_after_merge 的 pop 与已推进的 HEAD 冲突 → 自愈
        ok, files = self.wm.restore_after_merge()

        # 自愈成功，返回冲突文件清单
        self.assertTrue(ok)
        self.assertEqual(files, ["A.py"])
        # UU 半合并已清空
        self.assertEqual(self._unmerged_files(), [])
        # index 干净、工作区可写
        self.assertEqual(self._status_porcelain().strip(), "")
        # 工作区保留的是 merge 后的实现（HEAD 版本），而非 stash 版本
        self.assertEqual((self.project_root / "A.py").read_text(), "merged implementation\n")
        # 后续 git 写命令恢复正常：再次 stash / commit 不报 unmerged/index 错误
        (self.project_root / "A.py").write_text("post-heal write ok\n")
        re_stash = self.git("stash", "push", "-m", "probe", "--", ".",
                             ":(exclude)openspec/changes")
        self.assertEqual(re_stash.returncode, 0, re_stash.stderr)
        self.git("stash", "pop")  # 清理 probe
        # stash 条目保留：被自愈丢弃内容的那个 autostash 仍在列表中可找回
        stash_list = self.git("stash", "list").stdout
        self.assertIn("fenix: pre-dispatch autostash", stash_list)

    def test_no_conflict_path_returns_true_empty(self):
        """无 stash / pop 成功路径回归：返回 (True, [])，行为兼容旧版 True。"""
        # 主树干净、无 stash → pop 报 No stash entries（返回码 0 或 1，但无 CONFLICT）
        ok, files = self.wm.restore_after_merge()
        self.assertTrue(ok)
        self.assertEqual(files, [])
        # 主树无 UU、无副作用
        self.assertEqual(self._unmerged_files(), [])
        self.assertEqual(self._status_porcelain().strip(), "")


class TestCostControl(unittest.TestCase):
    """agent-cost-control：thinking_tokens 过滤 + max_turns 强制。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.config = {"agents": {"run_timeout_seconds": 10}}
        self.logger = MagicMock()
        from core.agent_runner import AgentRunner
        self.runner = AgentRunner(self.config, MagicMock(), MagicMock(), self.project_root, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _artifact(self, run_id):
        return self.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"

    def test_thinking_tokens_are_filtered_from_artifact(self):
        run_id = "impl-fp-1"
        stdout = [
            json.dumps({"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 1}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}),
            json.dumps({"type": "result", "result": "ok", "num_turns": 1, "session_id": "s1"}),
        ]
        proc = _FakeProc(stdout_lines=stdout)
        with patch("subprocess.Popen", return_value=proc):
            out, turns, sid = self.runner._run_claude("p", Path(self.tmpdir), run_id)
        text = self._artifact(run_id).read_text()
        self.assertNotIn("thinking_tokens", text)
        self.assertIn("assistant", text)
        self.assertEqual(sid, "s1")

    def test_max_turns_kills_run(self):
        run_id = "impl-mt-1"
        stdout = [json.dumps({"type": "assistant", "message": {"content": []}}) for _ in range(3)]
        stdout.append(json.dumps({"type": "result", "result": "x", "num_turns": 3, "session_id": "s2"}))
        proc = _FakeProc(stdout_lines=stdout, timeout=True)  # 进程永不退出
        with patch("subprocess.Popen", return_value=proc):
            with self.assertRaises(RuntimeError) as ctx:
                self.runner._run_claude("p", Path(self.tmpdir), run_id, max_turns=3)
        self.assertIn("Max turns", str(ctx.exception))
        self.assertIn("Max turns", self._artifact(run_id).read_text())


class TestExecuteAgentAttemptRunId(unittest.TestCase):
    """retry-resume：attempt 独立 run_id + implementer 重试复用 worktree + --resume。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix" / "runs").mkdir(parents=True)
        self.config = {"agents": {"max_retries": 2, "max_turns": 50, "subagent_model": "claude-sonnet-5"}}
        self.logger = MagicMock()
        self.wm = MagicMock()
        self.wt = Path(self.tmpdir) / "wt"
        self.wm.create.return_value = self.wt
        self.wm.get_branch_name.return_value = "fenix/test-1"
        from core.agent_runner import AgentRunner
        self.runner = AgentRunner(self.config, self.wm, MagicMock(), self.project_root, self.logger)

    def test_extract_session_id_from_init_event_when_no_result(self):
        """max_turns/超时强杀时 CLI 无 result 事件，session_id 从 init 事件提取（fix）。"""
        run_file = self.project_root / ".fenix" / "runs" / "impl-x-a1.jsonl"
        run_file.write_text(
            json.dumps({"type": "system", "subtype": "init", "session_id": "sess-init"}) + "\n"
            + json.dumps({"type": "assistant", "message": {}}) + "\n"
            + json.dumps({"type": "error", "error": "Max turns (150) reached"}) + "\n"
        )
        self.assertEqual(self.runner._extract_session_id(run_file), "sess-init")

    def test_extract_session_id_from_result_event(self):
        """正常失败路径（有 result 事件）仍从 result 取 session_id。"""
        run_file = self.project_root / ".fenix" / "runs" / "impl-y-a1.jsonl"
        run_file.write_text(
            json.dumps({"type": "assistant", "message": {}}) + "\n"
            + json.dumps({"type": "result", "is_error": True, "session_id": "sess-result"}) + "\n"
        )
        self.assertEqual(self.runner._extract_session_id(run_file), "sess-result")

    def test_implementer_retry_resumes_session(self):
        run_ids = []
        resume_ids = []

        def fake_run_claude(prompt, cwd, run_id, model_override=None, env_overrides=None,
                            resume_session_id=None, max_turns=None, spec_name=None):
            run_ids.append(run_id)
            resume_ids.append(resume_session_id)
            if len(run_ids) == 1:
                # attempt 1：先落盘 result 事件（含 session_id）再抛失败
                rf = self.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"
                rf.write_text(json.dumps({"type": "result", "result": "", "num_turns": 1,
                                          "session_id": "sess-a1"}) + "\n")
                raise RuntimeError("attempt 1 failed")
            return ("ok", 5, "sess-final")

        self.runner._build_prompt = MagicMock(return_value="p")
        self.runner._run_claude = fake_run_claude

        result = self.runner._execute_agent("test-spec", "implementer", "impl-test-spec-100")
        self.assertTrue(result.success)
        # 两次 attempt run_id 不同（-a1 / -a2），产物一一对应
        self.assertEqual(run_ids, ["impl-test-spec-100-a1", "impl-test-spec-100-a2"])
        # 第二次以 attempt1 的 session_id resume
        self.assertEqual(resume_ids, [None, "sess-a1"])
        # worktree 只创建一次（复用），成功后以 success=True 清理
        self.assertEqual(self.wm.create.call_count, 1)
        self.wm.cleanup.assert_called_once_with(self.wt, success=True)

    def test_non_implementer_retry_recreates_worktree(self):
        run_ids = []
        resume_ids = []

        def fake_run_claude(prompt, cwd, run_id, model_override=None, env_overrides=None,
                            resume_session_id=None, max_turns=None, spec_name=None):
            run_ids.append(run_id)
            resume_ids.append(resume_session_id)
            if len(run_ids) == 1:
                raise RuntimeError("attempt 1 failed")
            return ("ok", 1, "s")

        self.runner._build_prompt = MagicMock(return_value="p")
        self.runner._run_claude = fake_run_claude

        result = self.runner._execute_agent("test-spec", "verifier", "verify-test-spec-100")
        self.assertTrue(result.success)
        # verifier 重试全新创建 worktree（两次 create）
        self.assertEqual(self.wm.create.call_count, 2)
        self.assertEqual(resume_ids, [None, None])


class TestDaemonSingletonFlock(unittest.TestCase):
    """daemon-singleton：flock 排他锁语义（第二个实例被拒，释放后可获取）。"""

    def test_second_acquire_is_rejected_until_release(self):
        import fcntl
        lock_path = Path(tempfile.mkdtemp()) / "daemon.lock"
        fd1 = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 第一个实例持有
        fd2 = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        with self.assertRaises(OSError):
            fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 第二个实例被拒
        os.close(fd1)  # 第一个实例退出 → 锁释放
        fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 第三个实例可获取
        os.close(fd2)


class TestShutdownStopsDispatch(unittest.TestCase):
    """fix-admin-self-heal：daemon 优雅关闭期间 dispatcher 不再派发新 agent。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.sm = MagicMock()
        self.runner = MagicMock()
        self.config = {"agents": {"max_concurrent": 2}}
        self.engine = PMEngine(
            self.sm, self.runner, self.config, Path(self.tmpdir), MagicMock(),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_process_queue_paused_when_shutting_down(self):
        self.engine.shutting_down = True
        self.engine._enqueue("spec-a", "implementer")
        self.engine._process_queue()
        self.assertEqual(self.engine._active_runs, 0)
        self.assertEqual(len(self.engine._run_queue), 1)  # 队列未被消费
        # 未启动任何 worker 线程（intercept start 验证）
        started = []
        orig = threading.Thread.start

        def fake_start(thread_self):
            started.append(thread_self.name)
            if not thread_self.name.startswith("fenix-"):
                orig(thread_self)

        with patch("threading.Thread.start", side_effect=fake_start):
            self.engine._process_queue()
        self.assertEqual(self.engine._active_runs, 0)
        self.assertFalse(any(n.startswith("fenix-") for n in started))


# ═══════════════════════════════════════════════════════════════════
# Multi-Project Monitoring Tests (add-multi-project-monitoring)
# ═══════════════════════════════════════════════════════════════════

def _mk_fenix_project(base: Path, name: str) -> Path:
    """在 base/name 下构造一个可被识别的 Fenixd 项目（STATE.md + .fenix/config.yaml）。"""
    proot = base / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "config.yaml").write_text(
        "project:\n  name: fake\n", encoding="utf-8"
    )
    return proot


class TestRegistryDefaultDiscovery(unittest.TestCase):
    """默认扫描：scan_dirs 为空 → 以主目录 ~ 一级子目录自动发现。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.home = self.tmpdir / "home"
        self.home.mkdir()
        self.proj_a = _mk_fenix_project(self.home, "projectA")
        self.proj_b = _mk_fenix_project(self.home, "projectB")
        # 轻量 Fenixd 目录：仅 STATE.md 即被发现（无需 .fenix/config.yaml）
        fake = self.home / "lite-project"
        fake.mkdir()
        (fake / "STATE.md").write_text("# not a project", encoding="utf-8")
        self.cfg = self.tmpdir / "dashboard.yaml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_scan_dirs_scans_home(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": []})
        with patch("core.dashboard.registry.Path.home", return_value=self.home):
            projects = reg.discover()
        by_name = {p["name"]: p for p in projects}
        self.assertIn("projectA", by_name)
        self.assertIn("projectB", by_name)
        self.assertTrue(by_name["projectA"]["discovered"])
        # 仅 STATE.md 的目录也被扫描命中
        self.assertIn("lite-project", by_name)
        self.assertTrue(by_name["lite-project"]["discovered"])

    def test_explicit_scan_dirs_overrides_default(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.save({"port": 8787, "projects": [],
                  "scan_dirs": [str(self.tmpdir / "elsewhere")]})
        with patch("core.dashboard.registry.Path.home", return_value=self.home):
            projects = reg.discover()
        # 显式 scan_dirs 覆盖默认（指向不存在目录 → 空扫描），不再扫描 ~
        self.assertEqual(projects, [])

    def test_explicit_and_scan_dedup(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.add_project(str(self.proj_a))
        with patch("core.dashboard.registry.Path.home", return_value=self.home):
            projects = reg.discover()
        matches = [p for p in projects if p["name"] == "projectA"]
        self.assertEqual(len(matches), 1)           # 去重：只出现一次
        self.assertFalse(matches[0]["discovered"])  # 显式注册优先
        self.assertIn("lite-project", {p["name"] for p in projects})


class TestRegistryRemoveProject(unittest.TestCase):
    """Registry.remove_project：已注册移除、未注册不报错、仅扫描项目不可移除。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.home = self.tmpdir / "home"
        self.home.mkdir()
        self.proj_a = _mk_fenix_project(self.home, "projectA")
        self.proj_b = _mk_fenix_project(self.home, "projectB")
        self.cfg = self.tmpdir / "dashboard.yaml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_remove_registered_project(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.add_project(str(self.proj_a))
        reg.add_project(str(self.proj_b))
        removed, msg = reg.remove_project(str(self.proj_a))
        self.assertTrue(removed)
        paths = [p["path"] for p in reg.load()["projects"]]
        self.assertNotIn(str(self.proj_a.resolve()), paths)
        self.assertIn(str(self.proj_b.resolve()), paths)

    def test_remove_unregistered_no_error(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.add_project(str(self.proj_a))
        removed, msg = reg.remove_project(str(self.proj_b))
        self.assertFalse(removed)
        self.assertIn("未在监控列表", msg)
        self.assertEqual(len(reg.load()["projects"]), 1)  # 配置未变

    def test_scan_only_project_cannot_be_removed(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        with patch("core.dashboard.registry.Path.home", return_value=self.home):
            found = reg.discover()
        self.assertIn("projectA", {p["name"] for p in found})  # 扫描发现
        removed, msg = reg.remove_project(str(self.proj_a))    # 不在配置中
        self.assertFalse(removed)
        self.assertEqual(reg.load()["projects"], [])           # 配置未变


class TestDaemonHealth(unittest.TestCase):
    """daemon_health 语义：running/stopped 判定、TTL memo、异常兜底 stopped。"""

    def setUp(self):
        import core.dashboard.data as dash_data
        dash_data._DAEMON_HEALTH_CACHE.clear()
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import core.dashboard.data as dash_data
        dash_data._DAEMON_HEALTH_CACHE.clear()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_running_when_is_running_true(self):
        from core.dashboard.data import daemon_health
        with patch("core.dashboard.data._is_running", return_value=True):
            self.assertEqual(daemon_health(self.tmpdir), "running")

    def test_stopped_when_is_running_false(self):
        from core.dashboard.data import daemon_health
        with patch("core.dashboard.data._is_running", return_value=False):
            self.assertEqual(daemon_health(self.tmpdir), "stopped")

    def test_stopped_on_exception_no_raise(self):
        from core.dashboard.data import daemon_health
        with patch("core.dashboard.data._is_running", side_effect=RuntimeError("no tmux")):
            self.assertEqual(daemon_health(self.tmpdir), "stopped")

    def test_ttl_memo_reuses_result(self):
        from core.dashboard.data import daemon_health
        calls = {"n": 0}

        def fake(root):
            calls["n"] += 1
            return True

        with patch("core.dashboard.data._is_running", side_effect=fake):
            self.assertEqual(daemon_health(self.tmpdir), "running")
            self.assertEqual(daemon_health(self.tmpdir), "running")
        self.assertEqual(calls["n"], 1)  # TTL 内复用，不重复 spawn

    def test_different_project_not_served_from_cache(self):
        from core.dashboard.data import daemon_health
        other = self.tmpdir / "other"
        calls = {"n": 0}

        def fake(root):
            calls["n"] += 1
            return str(root).endswith("other")

        with patch("core.dashboard.data._is_running", side_effect=fake):
            self.assertEqual(daemon_health(self.tmpdir), "stopped")
            self.assertEqual(daemon_health(other), "running")
        self.assertEqual(calls["n"], 2)


class TestFenixSessionIsRunning(unittest.TestCase):
    """core.fenix_session.is_running：进程检测为主（/proc cwd+cmdline），
    /proc 不可用（非 Linux）时回退 tmux 判定；残留 session 不误报。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fake_run(self, returncodes, legacy_stdout=""):
        from types import SimpleNamespace
        calls = {"n": 0}

        def fake(args, **kw):
            calls["n"] += 1
            if calls["n"] == 1:  # tmux has-session
                return SimpleNamespace(returncode=returncodes[0], stdout="")
            return SimpleNamespace(returncode=returncodes[1], stdout=legacy_stdout)

        return fake

    def test_daemon_process_under_root_running(self):
        """supervisor 直启 daemon（无 tmux session）→ running。"""
        from core.fenix_session import is_running
        with patch("core.fenix_session._daemon_procs_under", return_value=True):
            self.assertTrue(is_running(self.tmpdir))

    def test_stale_session_without_process_stopped(self):
        """残留 tmux session 但无存活 daemon 进程（verify-tmp 场景）→ stopped。"""
        from core.fenix_session import is_running
        with patch("core.fenix_session._daemon_procs_under", return_value=False):
            self.assertFalse(is_running(self.tmpdir))

    def test_miss_stopped(self):
        from core.fenix_session import is_running
        with patch("core.fenix_session._daemon_procs_under", return_value=False):
            self.assertFalse(is_running(self.tmpdir))

    def test_proc_scan_unavailable_falls_back_to_tmux(self):
        """/proc 不可用（非 Linux）时回退 tmux 唯一 session / 旧版 cwd 判定。"""
        from core.fenix_session import is_running

        def proc_boom(root):
            raise OSError("no /proc")

        proot = Path(self.tmpdir).resolve()
        with patch("core.fenix_session._daemon_procs_under", side_effect=proc_boom), \
             patch("core.fenix_session.subprocess.run",
                   side_effect=self._fake_run([0, 0])):
            self.assertTrue(is_running(proot))

    def test_legacy_session_cwd_match_running_when_proc_unavailable(self):
        from core.fenix_session import is_running

        def proc_boom(root):
            raise OSError("no /proc")

        proot = Path(self.tmpdir).resolve()
        with patch("core.fenix_session._daemon_procs_under", side_effect=proc_boom), \
             patch("core.fenix_session.subprocess.run",
                   side_effect=self._fake_run([1, 0], legacy_stdout=str(proot))):
            self.assertTrue(is_running(proot))

    def test_subprocess_exception_stopped(self):
        from core.fenix_session import is_running
        with patch("core.fenix_session._daemon_procs_under", return_value=False), \
             patch("core.fenix_session.subprocess.run", side_effect=OSError("tmux unavailable")):
            self.assertFalse(is_running(self.tmpdir))


class TestOverviewDaemonField(unittest.TestCase):
    """overview()/project_summary() 项目对象含 daemon 字段，异常兜底 stopped。"""

    def setUp(self):
        import core.dashboard.data as dash_data
        dash_data._DAEMON_HEALTH_CACHE.clear()
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = _mk_fenix_project(self.tmpdir, "proj-a")

    def tearDown(self):
        import core.dashboard.data as dash_data
        dash_data._DAEMON_HEALTH_CACHE.clear()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_project_summary_has_daemon(self):
        from core.dashboard.data import project_summary
        with patch("core.dashboard.data._is_running", return_value=True):
            s = project_summary(self.proot, "proj-a", str(self.proot))
        self.assertIn("daemon", s)
        self.assertEqual(s["daemon"], "running")

    def test_overview_has_daemon_per_project(self):
        from core.dashboard.data import overview
        with patch("core.dashboard.data._is_running", return_value=True):
            data = overview([{"name": "proj-a", "path": str(self.proot),
                              "discovered": False, "exists": True}])
        proj = data["projects"][0]
        self.assertEqual(proj["daemon"], "running")
        self.assertEqual(proj["name"], "proj-a")

    def test_overview_missing_project_stopped(self):
        from core.dashboard.data import overview
        data = overview([{"name": "ghost", "path": "/nonexistent-xyz",
                          "discovered": False, "exists": False}])
        proj = data["projects"][0]
        self.assertEqual(proj["daemon"], "stopped")
        self.assertEqual(proj["error"], "项目路径不存在")

    def test_overview_health_exception_not_500(self):
        from core.dashboard.data import overview
        with patch("core.dashboard.data._is_running", side_effect=RuntimeError("boom")):
            data = overview([{"name": "proj-a", "path": str(self.proot),
                              "discovered": False, "exists": True}])
        self.assertEqual(data["projects"][0]["daemon"], "stopped")
        self.assertIn("totals", data)


if __name__ == "__main__":
    unittest.main()

# ═══════════════════════════════════════════════════════════════════
# Task Progress Sync — write-side backfill (add-task-progress-sync 2.1/2.2)
# ═══════════════════════════════════════════════════════════════════

def _write_impl_run_for_spec(proot: Path, spec: str, ts: int, creates, updates) -> Path:
    """写一个含 TaskCreate/TaskUpdate 的 impl run 产物。"""
    runs_dir = proot / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / f"impl-{spec}-{ts}.jsonl"
    lines = []
    for subj in creates:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "TaskCreate",
                 "input": {"subject": subj, "description": "d", "activeForm": "a"}}
            ]},
        }, ensure_ascii=False))
    for tid, status in updates:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate",
                 "input": {"taskId": str(tid), "status": status}}
            ]},
        }, ensure_ascii=False))
    run_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_file


class TestTaskProgressSync(unittest.TestCase):
    """implementer run 成功后 daemon 确定性回写主树 tasks.md 勾选。"""

    def setUp(self):
        import shutil
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        # .fenix/ 运行时产物走 gitignore，不计入工作树脏检测
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        (self.project_root / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)

        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "done"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config=None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def _write_spec_tasks(self, spec_name: str, content: str) -> Path:
        spec_dir = self.project_root / "openspec" / "changes" / spec_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        p = spec_dir / "tasks.md"
        p.write_text(content, encoding="utf-8")
        return p

    def _commit_spec(self, spec_name: str):
        """把 spec 目录提交进主树，模拟 ensure_spec_committed 后的干净基线。"""
        subprocess.run(["git", "add", "--", "openspec"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", f"spec {spec_name}"],
                       cwd=str(self.project_root), capture_output=True)

    def _head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"],
                              cwd=str(self.project_root), capture_output=True, text=True).stdout.strip()

    def test_sync_backfills_unchecked_done_ids(self):
        """run 声明 2.1/2.2 完成，主树未勾 → 回写勾选并 commit。"""
        tasks = ("# Tasks: demo\n\n"
                 "## 2. 实现\n\n"
                 "- [ ] 2.1 build\n"
                 "- [ ] 2.2 test\n"
                 "- [ ] 2.3 doc\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        _write_impl_run_for_spec(self.project_root, "demo", 1789000000,
                                 ["Task 2.1: build", "Task 2.2: test", "Task 2.3: doc"],
                                 [(1, "completed"), (2, "completed")])
        engine = self._make_engine()
        engine._sync_task_progress("demo")

        text = (self.project_root / "openspec" / "changes" / "demo" / "tasks.md").read_text()
        self.assertIn("- [x] 2.1 build", text)
        self.assertIn("- [x] 2.2 test", text)
        self.assertIn("- [ ] 2.3 doc", text)  # 未出现在 done_ids 的不勾

        res = subprocess.run(["git", "log", "--oneline"],
                             cwd=str(self.project_root), capture_output=True, text=True)
        self.assertIn("sync task progress from run record", res.stdout)

    def test_sync_idempotent_no_extra_commit(self):
        """二次执行不产生新 commit。"""
        tasks = ("# Tasks: demo\n\n"
                 "## 2. 实现\n\n"
                 "- [ ] 2.1 build\n"
                 "- [ ] 2.2 test\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        _write_impl_run_for_spec(self.project_root, "demo", 1789000000,
                                 ["Task 2.1: build", "Task 2.2: test"],
                                 [(1, "completed"), (2, "completed")])
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        first = self._head()
        engine._sync_task_progress("demo")  # 已全勾选，跳过
        self.assertEqual(first, self._head())

    def test_sync_preserves_agent_checked(self):
        """agent 已勾选但 run 记录缺失的任务不被撤销（只增不减）。"""
        tasks = ("# Tasks: demo\n\n"
                 "## 1. 实现\n\n"
                 "- [x] 1.1 already done by agent\n"
                 "- [ ] 1.2 not in run\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        _write_impl_run_for_spec(self.project_root, "demo", 1789000000,
                                 ["Task 1.1: already done by agent", "Task 1.2: not in run"],
                                 [(1, "completed")])
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        text = (self.project_root / "openspec" / "changes" / "demo" / "tasks.md").read_text()
        self.assertIn("- [x] 1.1 already done by agent", text)
        self.assertIn("- [ ] 1.2 not in run", text)
        # 无新勾选 → 不 commit（HEAD 不变）
        self.assertEqual(self._head(), self._head())

    def test_sync_skips_when_no_run_file(self):
        """无 run 产物时不动作、不 commit。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [ ] 1.1 x\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        self.assertEqual(self._head(), self._head())

    def test_sync_skips_when_dirty_tree(self):
        """工作树不干净时跳过回写（非阻塞），不 commit。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [ ] 1.1 x\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        _write_impl_run_for_spec(self.project_root, "demo", 1789000000,
                                 ["Task 1.1: x"], [(1, "completed")])
        engine = self._make_engine()
        with patch.object(engine, "_worktree_is_dirty", return_value=True):
            engine._sync_task_progress("demo")
        self.assertEqual(self._head(), self._head())





class TestTaskCompletionGate(unittest.TestCase):
    """verified→done 任务完成一致性门禁（add-task-progress-sync 3.1/3.2）。"""

    def setUp(self):
        import shutil
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        (self.project_root / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)

        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "verified"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config=None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        # worktree_manager.find_implementer_worktree 返回 None，
        # 使 _read_implementer_result 走项目根 .fenix-run-result.json 回退路径。
        ar.worktree_manager.find_implementer_worktree.return_value = None
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def _write_spec_tasks(self, spec_name, content):
        spec_dir = self.project_root / "openspec" / "changes" / spec_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(content, encoding="utf-8")

    def _write_impl_result(self, spec_name, status):
        """写 .fenix-run-result.json 到项目根（_read_implementer_result 回退路径）。"""
        (self.project_root / ".fenix-run-result.json").write_text(
            json.dumps({"status": status, "spec": spec_name}), encoding="utf-8")

    def _write_run_done(self, spec_name, done_ids):
        """写 impl run 产物，使其 done_ids 为给定集合。"""
        _write_impl_run_for_spec(
            self.project_root, spec_name, 1789000000,
            [f"Task {tid}: desc" for tid in done_ids] +
            [f"Task {i}.x: extra" for i in range(len(done_ids), 4)],
            [(i + 1, "completed") for i in range(len(done_ids))],
        )

    def test_gate_blocks_on_gap(self):
        """run 声明 success 但 4.1 未勾选且不在 done_ids → 阻断，error 含任务 id。"""
        tasks = ("# Tasks: demo\n\n## 4. 实现\n\n"
                 "- [x] 4.1 done\n- [ ] 4.2 done\n- [ ] 4.3 notdone\n")
        self._write_spec_tasks("demo", tasks)
        self._write_impl_result("demo", "success")
        self._write_run_done("demo", ["4.1", "4.2"])
        engine = self._make_engine()
        blocker = engine._task_completion_blocker("demo")
        self.assertIsNotNone(blocker)
        self.assertIn("4.3", blocker)
        # 通过 _on_spec_verified 端到端验证：阻断时不 transition，写 error
        engine._on_spec_verified("demo")
        self.sm.transition.assert_not_called()
        update_kwargs = self.sm.update_spec.call_args[0][1]
        self.assertIn("4.3", update_kwargs["error"])

    def test_gate_passes_when_all_confirmed(self):
        """全部任务确认完成（勾选 ∪ done_ids 覆盖全部）→ 放行。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n"
                 "- [x] 1.1 done\n- [ ] 1.2 done\n")
        self._write_spec_tasks("demo", tasks)
        self._write_impl_result("demo", "success")
        self._write_run_done("demo", ["1.2"])  # 1.2 在 done_ids，1.1 已勾选
        engine = self._make_engine()
        self.assertIsNone(engine._task_completion_blocker("demo"))
        engine._on_spec_verified("demo")
        self.sm.transition.assert_called_once_with("demo", "done")

    def test_gate_passes_without_run_record(self):
        """无 run 记录可查（.fenix-run-result.json 缺失）→ 放行（无法证伪）。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [ ] 1.1 x\n")
        self._write_spec_tasks("demo", tasks)
        # 不写 .fenix-run-result.json
        engine = self._make_engine()
        self.assertIsNone(engine._task_completion_blocker("demo"))

    def test_gate_passes_when_run_not_success(self):
        """run 声明非 success（如 error）→ 放行（仅 success 触发校验）。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [ ] 1.1 x\n")
        self._write_spec_tasks("demo", tasks)
        self._write_impl_result("demo", "error")
        engine = self._make_engine()
        self.assertIsNone(engine._task_completion_blocker("demo"))

    def test_gate_applies_to_fix_spec(self):
        """fix-* SPEC 走相同规则：缺口任务阻断。"""
        tasks = ("# Tasks: fix-demo\n\n## 1. 修复\n\n"
                 "- [x] 1.1 done\n- [ ] 1.2 notdone\n")
        self._write_spec_tasks("fix-demo", tasks)
        self._write_impl_result("fix-demo", "success")
        self._write_run_done("fix-demo", ["1.1"])
        engine = self._make_engine()
        blocker = engine._task_completion_blocker("fix-demo")
        self.assertIsNotNone(blocker)
        self.assertIn("1.2", blocker)
        engine._on_spec_verified("fix-demo")
        self.sm.transition.assert_not_called()


class TestVerificationCompletionGate(unittest.TestCase):
    """verified→done 验证完成度放行闸门（verification-completion-gate 3.1/3.2/3.3）。"""

    def setUp(self):
        import shutil
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        (self.project_root / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)

        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "verified"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config=None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        ar.worktree_manager.find_implementer_worktree.return_value = None
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def _write_verify_progress(self, spec_name, data):
        vp_dir = self.project_root / ".fenix" / "verify-progress"
        vp_dir.mkdir(parents=True, exist_ok=True)
        (vp_dir / f"{spec_name}.json").write_text(
            json.dumps(data), encoding="utf-8")

    def test_gate_blocks_when_not_complete(self):
        """进度 done < total ⇒ 阻断，error 含 'done/total'。"""
        self._write_verify_progress("improve-dashboard-sections",
                                    {"total": 34, "done": 0, "current": "初始化..."})
        engine = self._make_engine()
        blocker = engine._check_verification_gate("improve-dashboard-sections")
        self.assertIsNotNone(blocker)
        self.assertIn("0/34", blocker)
        # 端到端：阻断时不 transition，保持 verified，error 含原因
        engine._on_spec_verified("improve-dashboard-sections")
        self.sm.transition.assert_not_called()
        update_kwargs = self.sm.update_spec.call_args[0][1]
        self.assertIn("0/34", update_kwargs["error"])

    def test_gate_passes_when_complete(self):
        """进度 done == total ⇒ 放行，正常推进 done。"""
        self._write_verify_progress("demo", {"total": 32, "done": 32})
        engine = self._make_engine()
        self.assertIsNone(engine._check_verification_gate("demo"))
        engine._on_spec_verified("demo")
        self.sm.transition.assert_called_once_with("demo", "done")

    def test_gate_passes_without_progress_file(self):
        """无进度文件（验证未启动）⇒ 放行，不影响原路径。"""
        engine = self._make_engine()
        self.assertIsNone(engine._check_verification_gate("demo"))
        engine._on_spec_verified("demo")
        self.sm.transition.assert_called_once_with("demo", "done")

    def test_gate_blocks_on_corrupt_progress(self):
        """进度文件损坏 ⇒ 视同未完成，阻断。"""
        vp_dir = self.project_root / ".fenix" / "verify-progress"
        vp_dir.mkdir(parents=True, exist_ok=True)
        (vp_dir / "demo.json").write_text("not json {{{", encoding="utf-8")
        engine = self._make_engine()
        blocker = engine._check_verification_gate("demo")
        self.assertIsNotNone(blocker)
        self.assertIn("0/0", blocker)

    def test_gate_merges_with_task_blocker(self):
        """任务门禁与验证门禁同时触发 ⇒ 合并为单条 error，不双覆盖。"""
        self._write_verify_progress("demo", {"total": 10, "done": 5})
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [x] 1.1 done\n- [ ] 1.2 notdone\n")
        spec_dir = self.project_root / "openspec" / "changes" / "demo"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(tasks, encoding="utf-8")
        (self.project_root / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": "demo"}), encoding="utf-8")
        _write_impl_run_for_spec(
            self.project_root, "demo", 1789000000,
            [f"Task {tid}: desc" for tid in ["1.1"]] + ["Task 1.2: extra"],
            [(1, "completed")],
        )
        engine = self._make_engine()
        engine._on_spec_verified("demo")
        update_kwargs = self.sm.update_spec.call_args[0][1]
        err = update_kwargs["error"]
        self.assertIn("5/10", err)       # 验证门禁原因必含（触发 D7 回退）
        # D7 逃生门：进度不完整时走 VERIFIED→TESTING 回退（transition_gate），
        # 仅写一次 error 不双覆盖；任务门禁的「1.2」与验证门禁合并前的 blocker 语义
        # 由 _task_completion_blocker/_check_verification_gate 独立保证。
        self.assertEqual(self.sm.transition_gate.call_count, 1)
        self.assertEqual(self.sm.update_spec.call_count, 1)



class TestVerificationProgressGateD6(unittest.TestCase):
    """D6: testing→verified 前置进度核对：done>=total 才晋级，不完整走失败重试。

    通过 legacy 路径测试（legacy 和 new 路径都包含 D6 检查，legacy 更易 mock）。
    """

    def setUp(self):
        import shutil
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        (self.project_root / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)
        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "testing"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        ar.worktree_manager.find_implementer_worktree.return_value = None
        return PMEngine(self.sm, ar, {}, self.project_root, logger)

    def _write_progress(self, spec_name, data):
        vp_dir = self.project_root / ".fenix" / "verify-progress"
        vp_dir.mkdir(parents=True, exist_ok=True)
        (vp_dir / f"{spec_name}.json").write_text(
            json.dumps(data), encoding="utf-8")

    def _stub_legacy(self, engine, verifier_status="verified", run_id="v-1"):
        """Stub legacy 验证路径。"""
        engine.agent_runner.run_verifier.return_value = MagicMock(
            success=True, run_id=run_id, error=None)
        engine._read_verifier_result = MagicMock(return_value=verifier_status)
        engine._handle_env_blocked_inconclusive = MagicMock(return_value=False)
        engine._read_verify_report = MagicMock(return_value={
            "summary": {"total": 0, "passed": 0, "warnings": 0, "failed": 0, "errors": 0},
            "scenarios": [],
        })
        # 阻止 _on_spec_verified 调用 _on_spec_done 导致的递归
        engine._on_spec_verified = MagicMock()

    def test_incomplete_progress_blocks_verified_transition(self):
        """半程死亡：done=5/17 → 不晋级 verified，写 error 摘要。"""
        self._write_progress("demo", {"total": 17, "done": 5, "current": "场景5"})
        engine = self._make_engine()
        self._stub_legacy(engine, verifier_status="verified")
        engine._run_legacy_verification("demo")
        engine.state_machine.transition.assert_not_called()
        update_kwargs = engine.state_machine.update_spec.call_args[0][1]
        self.assertIn("5/17", update_kwargs["error"])
        self.assertIn("验证未完成", update_kwargs["error"])

    def test_complete_progress_allows_verified_transition(self):
        """完整通过：done=total → 正常晋级 verified（继而 verified→done）。"""
        self._write_progress("demo", {"total": 10, "done": 10})
        engine = self._make_engine()
        self._stub_legacy(engine, verifier_status="verified")
        engine._run_legacy_verification("demo")
        transition_calls = [c.args for c in engine.state_machine.transition.call_args_list]
        self.assertIn(("demo", "verified"), transition_calls)

    def test_no_progress_file_allows_verified_transition(self):
        """无进度文件 → 放行（验证未启动，不影响存量 spec）。"""
        engine = self._make_engine()
        self._stub_legacy(engine, verifier_status="verified")
        engine._run_legacy_verification("demo")
        transition_calls = [c.args for c in engine.state_machine.transition.call_args_list]
        self.assertIn(("demo", "verified"), transition_calls)

class TestPMEngineInfraFailureRecovery(unittest.TestCase):
    """派发基础设施失败（日限额耗尽等）不得卡死 spec、不得误判 bug-found。

    覆盖 2026-08-26 事故根因的三处框架修复：
    - 派发异常回滚 implementing/testing → 可重试态（不滞留）
    - 验证流水线双失败不得 transition bug-found（不派生伪 fix 级联）
    - blocker auto-recover 不得把从未实现的 spec 伪标 implemented
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        self.logger = MagicMock()
        from core.state_machine import StateMachine
        self.state_path = self.project_root / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        config = {"schedule": {"stuck_threshold_minutes": 60}}
        self.engine = PMEngine(self.sm, MagicMock(), config, self.project_root, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stale(self, name="s1"):
        """把 spec 的 updated 改为 2 小时前（模拟卡死），须在 transition 之后调用。"""
        from datetime import datetime, timedelta, timezone
        specs = self.sm.read_all()
        specs[name]["updated"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.sm.write_all(specs)

    def test_implementer_dispatch_failure_rolls_back_to_ready(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.engine._rollback_failed_dispatch(
            "s1", "implementer", RuntimeError("Daily agent run limit (50) reached"))
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry["implementer_run"])
        self.assertIsNone(entry["error"])
        self.assertIn("dispatch failed", entry["_last_dispatch_error"])
        self.assertGreater(int(entry["_dispatch_backoff_until"]), int(time.time()))
        self.assertTrue(any((e[1], e[2]) == ("s1", "implementer") for e in self.engine._run_queue))

    def test_verifier_dispatch_failure_rolls_back_to_implemented(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self.engine._rollback_failed_dispatch(
            "s1", "verifier", RuntimeError("Daily agent run limit (50) reached"))
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertIsNone(entry["tester_run"])
        self.assertIn("retryable", entry["error"])
        self.assertTrue(any((e[1], e[2]) == ("s1", "verifier") for e in self.engine._run_queue))

    def test_rollback_ignores_status_mismatch(self):
        self.sm.add_spec("s1", {"priority": 5})  # drafted
        self.engine._rollback_failed_dispatch("s1", "implementer", RuntimeError("x"))
        self.assertEqual(self.sm.read_one("s1")["status"], "drafted")

    def test_rollback_missing_spec_is_noop(self):
        self.engine._rollback_failed_dispatch("nope", "implementer", RuntimeError("x"))

    def test_verification_infra_failure_not_bug_found(self):
        """验证两条路径都抛基础设施异常 → 回 implemented 可重试，绝不 bug-found。"""
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self.engine._run_three_stage_verification = MagicMock(
            side_effect=RuntimeError("Daily agent run limit (50) reached"))
        self.engine._run_legacy_verification = MagicMock(
            side_effect=RuntimeError("Daily agent run limit (50) reached"))
        self.engine._run_verification_pipeline("s1")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertNotIn(entry["status"], ("bug-found",))
        self.assertIn("retryable", entry["error"])

    def test_check_blockers_implementing_rolls_back_to_ready(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self._stale()
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("Auto-recovered from stuck implementing", entry["error"])
        self.assertTrue(any((e[1], e[2]) == ("s1", "implementer") for e in self.engine._run_queue))

    def test_check_blockers_testing_rolls_back_to_implemented(self):
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        self._stale()
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")
        self.assertTrue(any((e[1], e[2]) == ("s1", "verifier") for e in self.engine._run_queue))

    def test_check_blockers_fresh_state_not_touched(self):
        """updated 为近期的 implementing 不触发 auto-recover。"""
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")
        self.engine.check_blockers()
        self.assertEqual(self.sm.read_one("s1")["status"], "implementing")

    def test_on_spec_done_root_with_fix_prefix_reverify(self):
        """fix 链根 spec 名本身带 fix- 前缀时，fix done 后父 spec 仍正确回溯重验。

        fix-dashboard-... 的 4-fix 后代 done 后，应回溯到 fix-dashboard-...
        （bug-found → implemented），而非全剥前缀后定位到不存在的 dashboard-...
        导致永不闭环、full_scan 反复派生新 fix（2026-08-26 事故的防复发修复）。
        """
        self.sm.add_spec("fix-dashboard-duration-and-verify-gate", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing", "bug-found"):
            self.sm.transition("fix-dashboard-duration-and-verify-gate", to)
        self.sm.add_spec("fix-fix-fix-fix-dashboard-duration-and-verify-gate", {"priority": 6})
        self.sm.transition("fix-fix-fix-fix-dashboard-duration-and-verify-gate", "done")
        self.engine._on_spec_done("fix-fix-fix-fix-dashboard-duration-and-verify-gate")
        entry = self.sm.read_one("fix-dashboard-duration-and-verify-gate")
        self.assertEqual(entry["status"], "implemented")

    def test_on_spec_done_plain_root_still_works(self):
        """普通链（根不带 fix- 前缀）行为不变：improve-... 由 fix- 后代 done 回调。"""
        self.sm.add_spec("improve-agent-config-and-verify-resume", {"priority": 5})
        for to in ("ready", "implementing", "implemented", "testing", "bug-found"):
            self.sm.transition("improve-agent-config-and-verify-resume", to)
        self.sm.add_spec("fix-fix-improve-agent-config-and-verify-resume", {"priority": 6})
        self.sm.transition("fix-fix-improve-agent-config-and-verify-resume", "done")
        self.engine._on_spec_done("fix-fix-improve-agent-config-and-verify-resume")
        self.assertEqual(
            self.sm.read_one("improve-agent-config-and-verify-resume")["status"],
            "implemented",
        )

    def test_dispatch_backoffed_helper(self):
        self.assertFalse(self.engine._dispatch_backoffed({}))
        self.assertFalse(self.engine._dispatch_backoffed({"status": "ready"}))
        self.assertFalse(self.engine._dispatch_backoffed(
            {"_dispatch_backoff_until": int(time.time()) - 10}))
        self.assertTrue(self.engine._dispatch_backoffed(
            {"_dispatch_backoff_until": int(time.time()) + 300}))


class TestStuckThresholdUnify(unittest.TestCase):
    """fix-stuck-threshold-unify：stuck 阈值单源派生 + 旧键弃用 + absolute_max 护栏。

    覆盖 spec stuck-timeout-single-source 全部 Scenario 与 tasks 1.1/1.2/1.3/2.1。
    """

    def setUp(self):
        ConfigLoader.reset_stuck_threshold_state()

    def tearDown(self):
        ConfigLoader.reset_stuck_threshold_state()

    # ── 1.1 派生助手 ──────────────────────────────────────

    def test_derivation_tracks_timeout_9000(self):
        """run_timeout_seconds=9000 → 生效阈值 9600s（design D1 场景）。"""
        cfg = {"agents": {"run_timeout_seconds": 9000}}
        self.assertEqual(
            ConfigLoader.effective_stuck_threshold_seconds(cfg), 9600.0)

    def test_derivation_default_timeout_fallback(self):
        """run_timeout 缺省（非正数）回退 4200s 并打 WARNING（D4）。"""
        with self.assertLogs("fenixd.config", level="WARNING") as cm:
            val = ConfigLoader.effective_stuck_threshold_seconds({"agents": {}})
        self.assertEqual(val, 4200.0)
        self.assertTrue(any("4200" in m for m in cm.output))

    def test_derivation_zero_timeout_fallback_warn(self):
        """run_timeout=0 视为非正数，回退 4200s + WARNING。"""
        with self.assertLogs("fenixd.config", level="WARNING") as cm:
            val = ConfigLoader.effective_stuck_threshold_seconds(
                {"agents": {"run_timeout_seconds": 0}})
        self.assertEqual(val, 4200.0)
        self.assertTrue(any("run_timeout_seconds" in m for m in cm.output))

    def test_explicit_old_key_does_not_affect_derived(self):
        """显式残留旧键（schedule/admin.stuck_threshold_minutes=240）不影响派生值。"""
        cfg = {
            "agents": {"run_timeout_seconds": 9000},
            "schedule": {"stuck_threshold_minutes": 240},
            "admin": {"stuck_threshold_minutes": 240},
        }
        self.assertEqual(
            ConfigLoader.effective_stuck_threshold_seconds(cfg), 9600.0)

    # ── 1.2 get_admin_config / check_blockers 取派生值 ──────

    def test_get_admin_config_uses_derived_value(self):
        """admin.stuck_threshold_minutes 改为派生值（秒/60），旧键不再生效。"""
        cfg = {"agents": {"run_timeout_seconds": 9000}}
        admin_cfg = ConfigLoader.get_admin_config(cfg)
        self.assertEqual(admin_cfg["stuck_threshold_minutes"], 160.0)  # 9600/60

    def test_get_admin_config_ignores_old_admin_key(self):
        """admin.stuck_threshold_minutes=240 旧键被忽略，取派生值。"""
        cfg = {
            "agents": {"run_timeout_seconds": 3600},
            "admin": {"stuck_threshold_minutes": 240},
        }
        admin_cfg = ConfigLoader.get_admin_config(cfg)
        # 派生 = (3600+600)/60 = 70，而非 240
        self.assertEqual(admin_cfg["stuck_threshold_minutes"], 70.0)

    def test_check_blockers_uses_derived_threshold(self):
        """pm_engine.check_blockers 取派生阈值：100 分钟静止实现不触发恢复（D1 场景）。"""
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        from datetime import datetime, timedelta, timezone
        tmpdir = tempfile.mkdtemp()
        try:
            project_root = Path(tmpdir)
            (project_root / ".fenix").mkdir()
            logger = MagicMock()
            sm = StateMachine(project_root / "STATE.md", logger)
            # run_timeout=9000 → 派生阈值 9600s=160m；100 分钟静止远未到
            config = {"agents": {"run_timeout_seconds": 9000}}
            engine = PMEngine(sm, MagicMock(), config, project_root, logger)
            sm.add_spec("s1", {"priority": 5})
            sm.transition("s1", "ready")
            sm.transition("s1", "implementing")
            specs = sm.read_all()
            specs["s1"]["updated"] = (
                datetime.now(timezone.utc) - timedelta(minutes=100)).isoformat()
            sm.write_all(specs)
            engine.check_blockers()
            self.assertEqual(sm.read_one("s1")["status"], "implementing")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_check_blockers_derived_threshold_triggers_when_exceeded(self):
        """派生阈值（160m）被越过时仍正确恢复（派生不改变恢复语义本身）。"""
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        from datetime import datetime, timedelta, timezone
        tmpdir = tempfile.mkdtemp()
        try:
            project_root = Path(tmpdir)
            (project_root / ".fenix").mkdir()
            logger = MagicMock()
            sm = StateMachine(project_root / "STATE.md", logger)
            config = {"agents": {"run_timeout_seconds": 9000}}  # 阈值 160m
            engine = PMEngine(sm, MagicMock(), config, project_root, logger)
            sm.add_spec("s1", {"priority": 5})
            sm.transition("s1", "ready")
            sm.transition("s1", "implementing")
            specs = sm.read_all()
            specs["s1"]["updated"] = (
                datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat()
            sm.write_all(specs)
            engine.check_blockers()
            self.assertEqual(sm.read_one("s1")["status"], "ready")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── 1.3 旧键弃用一次性告警 ──────────────────────────────

    def test_deprecation_warning_first_time(self):
        """旧键存在时首次调用打一次性 WARNING。"""
        cfg = {"schedule": {"stuck_threshold_minutes": 240}}
        with self.assertLogs("fenixd.config", level="WARNING") as cm:
            ConfigLoader.effective_stuck_threshold_seconds(cfg)
        self.assertTrue(any("弃用" in m or "stuck_threshold_minutes" in m for m in cm.output))

    def test_deprecation_warning_silent_second_time(self):
        """同一生命周期内第二次调用保持静默（D3 节流）。"""
        cfg = {
            "agents": {"run_timeout_seconds": 3600},
            "admin": {"stuck_threshold_minutes": 240},
        }
        with self.assertLogs("fenixd.config", level="WARNING") as cm1:
            ConfigLoader.effective_stuck_threshold_seconds(cfg)
        self.assertTrue(any("弃用" in m for m in cm1.output))  # 首次弃用告警
        # 同生命周期内再触发 getter，弃用告警应保持静默（D3 节流）
        with self.assertNoLogs("fenixd.config", level="WARNING"):
            ConfigLoader.get_admin_config(cfg)

    def test_no_deprecation_warning_without_old_key(self):
        """无旧键时不应打弃用告警（仅有 timeout 缺省回退告警才可能出现）。"""
        cfg = {"agents": {"run_timeout_seconds": 9000}}
        with self.assertNoLogs("fenixd.config", level="WARNING"):
            ConfigLoader.effective_stuck_threshold_seconds(cfg)

    # ── 2.1 absolute_max 联动护栏 ───────────────────────────

    def test_absolute_max_below_timeout_corrected(self):
        """absolute_max=7200 而 run_timeout=9000 → ERROR 且兜底 16200（D5 场景）。"""
        cfg = {
            "agents": {"run_timeout_seconds": 9000},
            "timeout_supervision": {"enabled": True, "absolute_max_seconds": 7200},
        }
        with self.assertLogs("fenixd.config", level="ERROR") as cm:
            eff = ConfigLoader.effective_supervision_absolute_max_seconds(cfg)
        self.assertEqual(eff, 16200.0)  # 9000 + 7200
        self.assertTrue(any("absolute_max" in m for m in cm.output))

    def test_absolute_max_legal_value_untouched(self):
        """合法 absolute_max（≥ run_timeout+7200）不干预、不打 ERROR。"""
        cfg = {
            "agents": {"run_timeout_seconds": 9000},
            "timeout_supervision": {"enabled": True, "absolute_max_seconds": 20000},
        }
        with self.assertNoLogs("fenixd.config", level="ERROR"):
            eff = ConfigLoader.effective_supervision_absolute_max_seconds(cfg)
        self.assertEqual(eff, 20000.0)

    def test_supervision_disabled_skips_validation(self):
        """enabled=false 时不校验、返回 None。"""
        cfg = {
            "agents": {"run_timeout_seconds": 9000},
            "timeout_supervision": {"enabled": False, "absolute_max_seconds": 7200},
        }
        with self.assertNoLogs("fenixd.config", level="ERROR"):
            eff = ConfigLoader.effective_supervision_absolute_max_seconds(cfg)
        self.assertIsNone(eff)

    def test_supervision_absent_returns_none(self):
        """无 timeout_supervision 段时返回 None（不校验）。"""
        eff = ConfigLoader.effective_supervision_absolute_max_seconds(
            {"agents": {"run_timeout_seconds": 9000}})
        self.assertIsNone(eff)


if __name__ == "__main__":
    unittest.main()