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
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
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

    def test_event_bus_accepts_hook_dispatcher(self):
        """构造参数新增可选 hook_dispatcher（add-spec-hooks 3.1），旧调用不受影响。"""
        from core.event_bus import EventBus
        bus = EventBus(self.state_path, self.sm, MagicMock(), {}, self.logger,
                       hook_dispatcher=MagicMock())
        self.assertIsNotNone(bus.hook_dispatcher)


class TestRecoverOneInconclusiveHold(unittest.TestCase):
    """B6：inconclusive 暂停期 recovery 不得 re-trigger verify。

    事故（fenixd-registry-ignored-false-attribution-loop 后续）：全批
    blocked-env → inconclusive 连续超限 → _handle_env_blocked_inconclusive
    写 error + _inconclusive_attempts 暂停自动重验，但 recovery 的 implemented
    分支只查 tester_run（暂停时恰被置 None）→ 每个扫描周期无视暂停标记强行
    re-trigger，add-spec-status-modal-budget 实证每小时重验 9 轮（第 3→11 轮）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        from core.event_bus import EventBus
        self.pm = MagicMock()
        self.bus = EventBus(self.state_path, self.sm, self.pm, {}, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_held_by_inconclusive_attempts(self):
        """暂停标记存在 → 跳过 re-trigger（不发 spec_implemented）。"""
        ok = self.bus._recover_one("spec-a", {
            "status": "implemented", "tester_run": None,
            "_inconclusive_attempts": 3,
        })
        self.assertTrue(ok)
        self.pm.handle_event.assert_not_called()

    def test_retrigger_without_hold_marker(self):
        """无暂停标记（正常 implemented 未验证）→ 维持既有 re-trigger。"""
        ok = self.bus._recover_one("spec-b", {
            "status": "implemented", "tester_run": None,
        })
        self.assertTrue(ok)
        self.pm.handle_event.assert_called_once_with(
            "spec_implemented", "spec-b", {"status": "implemented", "tester_run": None})

    def test_zero_attempts_does_not_hold(self):
        """attempts=0（清零残留）不算暂停 → re-trigger。"""
        ok = self.bus._recover_one("spec-c", {
            "status": "implemented", "tester_run": None,
            "_inconclusive_attempts": 0,
        })
        self.assertTrue(ok)
        self.pm.handle_event.assert_called_once()

    def test_tester_run_present_skips_as_before(self):
        """已有 tester_run → 既有跳过逻辑不受影响。"""
        ok = self.bus._recover_one("spec-d", {
            "status": "implemented", "tester_run": "verify-x",
        })
        self.assertTrue(ok)
        self.pm.handle_event.assert_not_called()


class TestEventBusHookDispatch(unittest.TestCase):
    """add-spec-hooks 3.1/6.3：EventBus 状态 diff 触发 hook 分发。

    覆盖：状态 diff 触发分发（含 _status_to_event 不覆盖的中间态）、
    未注入 dispatcher 行为不变、跨进程写入（直接改 STATE.md）被捕获、
    启动快照语义（重启不重发存量）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.sm.add_spec("s1", {"status": "drafted"})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _bus(self, dispatcher=None):
        from core.event_bus import EventBus
        return EventBus(self.state_path, self.sm, MagicMock(), {},
                        self.logger, hook_dispatcher=dispatcher)

    def test_hook_dispatched_on_status_diff(self):
        from core.event_bus import EventBus
        from core.hook_engine import HookEngine
        config = {"project": {"name": "t"},
                  "hooks": {"global": [{"id": "h1", "enabled": True,
                                        "events": ["blocked"], "action": "restart-daemon"}]}}
        eng = HookEngine(Path(self.tmpdir), config, logger=None)
        bus = self._bus(eng.dispatch)
        bus._update_known_state()
        self.sm.update_spec("s1", {"status": "blocked"})
        bus._dispatch_changes(self.sm.read_all())
        time.sleep(0.8)
        self.assertTrue((Path(self.tmpdir) / ".fenix" / "restart_request").exists())
        # 审计记录写了一条 success
        from core.hook_engine import read_hook_audit
        recs = read_hook_audit(self.tmpdir)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["status"], "success")

    def test_mid_state_dispatched_even_without_pm_event(self):
        """implementing 不在 _status_to_event 映射中，但 hook 通道必须触发。"""
        from core.event_bus import EventBus
        captured = []
        def dispatcher(spec, old, new, entry):
            captured.append((spec, old, new))
        bus = self._bus(dispatcher)
        bus._update_known_state()
        self.sm.update_spec("s1", {"status": "implementing"})
        bus._dispatch_changes(self.sm.read_all())
        self.assertEqual(captured, [("s1", "drafted", "implementing")])

    def test_no_dispatcher_unchanged(self):
        """未注入 dispatcher：状态 diff 仍正常派发 PM Engine 事件，hook 无副作用。"""
        from core.event_bus import EventBus
        pm = MagicMock()
        bus = EventBus(self.state_path, self.sm, pm, {}, self.logger)
        bus._update_known_state()
        self.sm.update_spec("s1", {"status": "ready"})
        bus._dispatch_changes(self.sm.read_all())
        # PM Engine 收到 spec_ready
        handle_calls = [c.args for c in pm.handle_event.call_args_list]
        self.assertTrue(any("spec_ready" in c for c in handle_calls), handle_calls)

    def test_cross_process_write_captured(self):
        """跨进程写入（绕过 state_machine 直接改 STATE.md）也被捕获分发。"""
        from core.event_bus import EventBus
        captured = []
        def dispatcher(spec, old, new, entry):
            captured.append((spec, old, new))
        bus = self._bus(dispatcher)
        bus._update_known_state()
        # 第一拍：daemon 侧正常写 → done，bus 快照随之更新
        self.sm.update_spec("s1", {"status": "done"})
        bus._dispatch_changes(self.sm.read_all())
        self.assertEqual(captured, [("s1", "drafted", "done")])
        # 第二拍：模拟 dashboard 进程直写 STATE.md（绕过 StateMachine）→ verified
        content = self.state_path.read_text(encoding="utf-8")
        self.state_path.write_text(content.replace("- status: done", "- status: verified"),
                                   encoding="utf-8")
        bus._dispatch_changes(self.sm.read_all())
        self.assertEqual(captured[-1], ("s1", "done", "verified"))

    def test_startup_snapshot_no_resend(self):
        """启动快照语义：start() 记录初始状态后，存量 spec 不当作新事件重发。"""
        from core.event_bus import EventBus
        captured = []
        def dispatcher(spec, old, new, entry):
            captured.append((spec, old, new))
        # spec 已是 done（存量）
        self.sm.update_spec("s1", {"status": "done"})
        bus = self._bus(dispatcher)
        bus._update_known_state()  # 等价于 start() 内的初始快照
        bus._dispatch_changes(self.sm.read_all())
        self.assertEqual(captured, [])

    def test_dispatcher_exception_isolated(self):
        """hook dispatcher 抛异常不得影响 PM Engine 派发。"""
        from core.event_bus import EventBus
        pm = MagicMock()
        def bad_dispatcher(spec, old, new, entry):
            raise RuntimeError("boom")
        bus = EventBus(self.state_path, self.sm, pm, {}, self.logger,
                       hook_dispatcher=bad_dispatcher)
        bus._update_known_state()
        self.sm.update_spec("s1", {"status": "ready"})
        bus._dispatch_changes(self.sm.read_all())
        handle_calls = [c.args for c in pm.handle_event.call_args_list]
        self.assertTrue(any("spec_ready" in c for c in handle_calls), handle_calls)
