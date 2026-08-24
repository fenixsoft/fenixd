"""
Unit tests for Fenix Loop Engineering Framework core modules.

Run with: python3 -m pytest .fenix/tests/ -v
"""

import json
import os
import subprocess
import sys
import tempfile
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
        # 第二轮 fix 应被排队
        self.assertIn(("fix-fix-quick-links-folders", "implementer"), self.engine._run_queue)

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


if __name__ == "__main__":
    unittest.main()
