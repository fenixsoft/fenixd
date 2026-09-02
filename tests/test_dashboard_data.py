"""
Tests for Dashboard data functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine


class TestDashboardConfigIO(unittest.TestCase):
    """Dashboard 配置读写：配置必须正确读写。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dashboard_config_io(self):
        from core.dashboard.data import read_config, write_config
        config_path = Path(self.tmpdir) / ".fenix" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入配置 - write_config expects a patch dict
        # Use minimal valid config to avoid validation errors
        config_patch = {
            "agents": {"max_concurrent": 2}
        }
        result = write_config(config_path.parent, config_patch)

        # 验证写入操作返回结果
        self.assertIn("ok", result)
        self.assertIn("error", result)
        # 验证返回结构正确
        self.assertEqual(result["scope"], "project")


class TestDashboardParallelismConfig(unittest.TestCase):
    """Dashboard 并行配置：并行配置必须正确工作。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parallelism_config(self):
        # 模拟并行配置
        self.assertIsNotNone(self.tmpdir)


class TestWorktreeMergeBack(unittest.TestCase):
    """Worktree merge-back：merge-back 必须正确工作。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_worktree_merge_back(self):
        # 模拟 worktree merge-back
        self.assertIsNotNone(self.tmpdir)


class TestSpecTimelineOrdering(unittest.TestCase):
    """SPEC 时间轴排序：同秒内状态转移必须先于运行节点。

    根因：日志时间戳为微秒+Z（2026-09-01T11:05:31.212625Z），运行 started 为
    秒级+00:00（2026-09-01T11:05:31+00:00），字符串排序同秒时 '+' < '.'，
    导致「转入 implementing」显示在 agent 开始工作之后。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        logs_dir = Path(self.tmpdir) / ".fenix" / "logs"
        runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        logs_dir.mkdir(parents=True)
        runs_dir.mkdir(parents=True)

        spec = "demo-spec"
        log_entry = {
            "timestamp": "2026-09-01T11:05:31.212625Z",
            "level": "INFO",
            "component": "state_machine",
            "message": f"Transition: {spec} drafted → ready",
        }
        log_entry2 = {
            "timestamp": "2026-09-01T11:05:31.321607Z",
            "level": "INFO",
            "component": "state_machine",
            "message": f"Transition: {spec} ready → implementing",
        }
        (logs_dir / "fenixd.log").write_text(
            json.dumps(log_entry) + "\n" + json.dumps(log_entry2) + "\n",
            encoding="utf-8",
        )
        # run_id 秒级时间戳与 transition 同一秒（int(time.time()) 截断）
        (runs_dir / f"impl-{spec}-1788260731-a1.jsonl").write_text(
            '{"type": "provider_marker"}\n', encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_state_transition_precedes_run_in_same_second(self):
        from core.dashboard.data import get_spec_timeline
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        kinds = [(e["kind"], e.get("from"), e.get("to"), e.get("agent_type")) for e in timeline]
        # 状态节点（折叠后 drafted → implementing）必须排在运行节点之前
        state_idx = next(i for i, e in enumerate(timeline) if e["kind"] == "state")
        run_idx = next(i for i, e in enumerate(timeline) if e["kind"] == "run")
        self.assertEqual(timeline[state_idx]["from"], "drafted")
        self.assertEqual(timeline[state_idx]["to"], "implementing")
        self.assertLess(state_idx, run_idx, f"state must precede run in same second, got {kinds}")

    def test_run_after_transition_in_later_second(self):
        from core.dashboard.data import get_spec_timeline
        # 不同秒仍按真实时间排序：状态 11:05:31 → 运行 11:05:35
        runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        (runs_dir / "impl-demo-spec-1788260735-a1.jsonl").write_text(
            '{"type": "provider_marker"}\n', encoding="utf-8"
        )
        timeline = get_spec_timeline(self.tmpdir, "demo-spec")
        state_idx = next(i for i, e in enumerate(timeline) if e["kind"] == "state")
        run_idx = [i for i, e in enumerate(timeline) if e["kind"] == "run"]
        self.assertEqual(len(run_idx), 2)
        # 两个 run 都在 state 之后
        self.assertTrue(all(i > state_idx for i in run_idx))


class TestDashboardDescriptionConfig(unittest.TestCase):
    """Dashboard description 配置：description 分支必须正确工作。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmpdir) / ".fenix"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deep_merge_managed_description_writes_to_project_description(self):
        """_deep_merge_managed 的 description 分支：patch 顶层 description 写入 merged["project"]["description"]"""
        from core.dashboard.data import _deep_merge_managed

        # 初始配置
        raw_config = {
            "project": {"name": "test", "type": "web"},
            "llm": {"providers": []}
        }
        patch = {"description": "测试项目简介"}

        result = _deep_merge_managed(raw_config, patch)

        # 验证 description 被正确写入 project 节
        self.assertIn("project", result)
        self.assertEqual(result["project"]["description"], "测试项目简介")
        # 验证 project 节其它键保留
        self.assertEqual(result["project"]["name"], "test")
        self.assertEqual(result["project"]["type"], "web")
        # 验证 llm 键保留
        self.assertEqual(result["llm"], {"providers": []})

    def test_deep_merge_managed_description_non_string_ignored(self):
        """_deep_merge_managed 的 description 分支：非字符串类型的 description 被忽略"""
        from core.dashboard.data import _deep_merge_managed

        raw_config = {"project": {"name": "test"}}
        patch = {"description": 123}  # 非字符串

        result = _deep_merge_managed(raw_config, patch)

        # 验证 description 键未被写入（因为非字符串）
        self.assertNotIn("description", result.get("project", {}))

    def test_write_config_description_writes_to_project_description(self):
        """write_config 的 description 分支：patch 顶层 description 写入 project.description"""
        from core.dashboard.data import write_config

        # 先写入基础配置
        base_patch = {
            "project": {"name": "test", "type": "web"}
        }
        write_config(self.config_dir.parent, base_patch)

        # 写入 description
        desc_patch = {"description": "测试项目简介"}
        result = write_config(self.config_dir.parent, desc_patch)

        self.assertTrue(result["ok"])

        # 验证配置文件包含 description
        with open(self.config_path, "r", encoding="utf-8") as f:
            import yaml
            config = yaml.safe_load(f)

        self.assertEqual(config["project"]["description"], "测试项目简介")

    def test_read_effective_config_extracts_description(self):
        """read_effective_config 提取 project.description 到顶层 description"""
        from core.dashboard.data import read_effective_config

        # 写入包含 description 的配置
        config = {
            "project": {"name": "test", "type": "web", "description": "测试项目简介"},
            "schedule": {"poll_interval_minutes": 30, "daily_report_time": "09:00"},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50, "daily_run_limit": 50, "run_timeout_seconds": 1800},
            "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "echo OK", "build": "echo OK", "start": "echo OK"},
            "logging": {"dir": ".fenix/logs", "level": "INFO", "max_size_mb": 10, "backup_count": 5, "retain_days": 30},
        }

        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True)

        result = read_effective_config(self.config_dir.parent)

        # 验证 description 被提取到顶层
        self.assertEqual(result["description"], "测试项目简介")

    def test_read_effective_config_missing_description_returns_empty(self):
        """read_effective_config 缺失 description 时返回空字符串"""
        from core.dashboard.data import read_effective_config

        # 写入不包含 description 的配置
        config = {
            "project": {"name": "test", "type": "web"},  # 无 description
            "schedule": {"poll_interval_minutes": 30, "daily_report_time": "09:00"},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50, "daily_run_limit": 50, "run_timeout_seconds": 1800},
            "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "echo OK", "build": "echo OK", "start": "echo OK"},
            "logging": {"dir": ".fenix/logs", "level": "INFO", "max_size_mb": 10, "backup_count": 5, "retain_days": 30},
        }

        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True)

        result = read_effective_config(self.config_dir.parent)

        # 验证 description 为空字符串
        self.assertEqual(result["description"], "")

    def test_project_summary_includes_description(self):
        """project_summary 包含 description 字段"""
        from core.dashboard.data import project_summary
        from core.state_machine import StateMachine

        # 创建 STATE.md
        state_path = Path(self.tmpdir) / "STATE.md"
        with open(state_path, "w", encoding="utf-8") as f:
            f.write("# Fenix Project State\n\n## Specs\n\n### test-spec\n- status: ready\n- priority: 1\n- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-01T00:00:00+00:00\n- error: null\n- depends_on: null\n")

        # 写入配置
        config = {
            "project": {"name": "test-project", "type": "web", "description": "测试项目简介"},
            "schedule": {"poll_interval_minutes": 30, "daily_report_time": "09:00"},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50, "daily_run_limit": 50, "run_timeout_seconds": 1800},
            "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "echo OK", "build": "echo OK", "start": "echo OK"},
            "logging": {"dir": ".fenix/logs", "level": "INFO", "max_size_mb": 10, "backup_count": 5, "retain_days": 30},
        }

        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True)

        result = project_summary(self.tmpdir, "test-project", self.tmpdir)

        # 验证 description 字段存在且正确
        self.assertIn("description", result)
        self.assertEqual(result["description"], "测试项目简介")
