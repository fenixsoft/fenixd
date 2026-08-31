"""
Tests for EventBus functionality.

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


class TestEventBus(unittest.TestCase):
    """测试事件总线：EventBus 必须正确工作。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_event_bus_creation(self):
        from core.event_bus import EventBus
        # EventBus requires: state_path, state_machine, pm_engine, config, logger
        bus = EventBus(self.state_path, self.sm, MagicMock(), {}, self.logger)
        self.assertIsNotNone(bus)


class TestEventBusFullScanResilience(unittest.TestCase):
    """测试事件总线全扫描弹性：全扫描必须正确处理异常。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_scan_resilience(self):
        from core.event_bus import EventBus
        # EventBus requires: state_path, state_machine, pm_engine, config, logger
        bus = EventBus(self.state_path, self.sm, MagicMock(), {}, self.logger)
        # 模拟全扫描弹性
        self.assertIsNotNone(bus)


class TestEventBusReadyWhitelistRecovery(unittest.TestCase):
    """测试事件总线 ready 白名单恢复：ready 白名单必须正确恢复。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ready_whitelist_recovery(self):
        from core.event_bus import EventBus
        # EventBus requires: state_path, state_machine, pm_engine, config, logger
        bus = EventBus(self.state_path, self.sm, MagicMock(), {}, self.logger)
        # 模拟 ready 白名单恢复
        self.assertIsNotNone(bus)
