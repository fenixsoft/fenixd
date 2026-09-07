"""
Tests for PMEngine reporting/planner/scheduler functionality.

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

from core.state_machine import StateMachine, StateParser, SpecStatus, VALID_TRANSITIONS


class TestPriorityScheduler(unittest.TestCase):
    """优先级调度器：优先级调度必须正确工作。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_priority_scheduling(self):
        # 添加不同优先级的 spec
        self.sm.add_spec("low-priority", {"priority": 10})
        self.sm.add_spec("high-priority", {"priority": 1})
        self.sm.add_spec("medium-priority", {"priority": 5})

        # 标记为 ready
        self.sm.update_spec("low-priority", {"status": "ready"})
        self.sm.update_spec("high-priority", {"status": "ready"})
        self.sm.update_spec("medium-priority", {"status": "ready"})

        # 验证优先级排序
        ready_specs = self.sm.get_ready_specs()
        self.assertEqual(ready_specs[0][0], "high-priority")
        self.assertEqual(ready_specs[1][0], "medium-priority")
        self.assertEqual(ready_specs[2][0], "low-priority")

    def test_priority_scheduling_dense_ids(self):
        """密集优先级（1/2/3）按 priority 升序（原 TestApiSpecsSortOrder 并入：
        二者断言同一 get_by_status 排序实现，get_ready_specs 即其 READY 透传）。"""
        self.sm.add_spec("spec-c", {"priority": 3, "status": "ready"})
        self.sm.add_spec("spec-a", {"priority": 1, "status": "ready"})
        self.sm.add_spec("spec-b", {"priority": 2, "status": "ready"})

        ready_specs = self.sm.get_ready_specs()
        self.assertEqual(ready_specs[0][0], "spec-a")
        self.assertEqual(ready_specs[1][0], "spec-b")
        self.assertEqual(ready_specs[2][0], "spec-c")


class TestSpecSummaryCreatedUpdated(unittest.TestCase):
    """Spec 摘要创建/更新时间：创建和更新时间必须正确记录。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_created_updated_times(self):
        self.sm.add_spec("test-spec", {"priority": 1})
        entry = self.sm.read_one("test-spec")
        
        # 验证创建时间存在
        self.assertIn("created", entry)
        self.assertIsNotNone(entry["created"])
        
        # 更新 spec
        self.sm.update_spec("test-spec", {"priority": 2})
        entry = self.sm.read_one("test-spec")
        
        # 验证更新时间存在
        self.assertIn("updated", entry)
        self.assertIsNotNone(entry["updated"])
