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
from core import fenix_session  # noqa: E402 —— 供 restart-daemon hook 成功路径 mock


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


class TestRecoverTestingAdminGuard(unittest.TestCase):
    """_recover_testing 派发前 admin 并发守卫（fix-recovery-path-blockers D2/2.3）。

    守卫经两条无需新注入的通路探测并联：(a) AdminStore + 模块级
    ``_spec_has_active_admin_run``（与 AdminMonitor 同源归并）；(b)
    ``agent_runner.running_run_ids()`` 中存在 ``admin-<spec>-`` 前缀 run。
    任一成立 → 跳过 spec_implemented 重验派发；判定异常 fail-open 放行。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        from core.event_bus import EventBus
        self.pm = MagicMock()
        self.pm.project_root = self.tmpdir
        self.bus = EventBus(self.state_path, self.sm, self.pm, {}, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_inflight_admin_skips_recovery_dispatch(self):
        """在飞 admin run（守卫命中）→ handle_event 不被调用、日志含跳过说明。"""
        entry = {"status": "testing", "updated": "2026-09-18T00:00:00+00:00"}
        with patch("core.admin_monitor._pgrep_live_worktree", return_value=False):
            with patch.object(self.bus, "_admin_inflight_guard", return_value=True) as guard:
                self.bus._recover_testing("spec-a", entry)
        guard.assert_called_once_with("spec-a")
        self.pm.handle_event.assert_not_called()
        info_calls = [str(c) for c in self.logger.info.call_args_list]
        self.assertTrue(
            any("admin 处置在飞" in c for c in info_calls),
            f"日志应含跳过说明: {info_calls}",
        )

    def test_no_inflight_admin_dispatches_once(self):
        """无在飞 admin → handle_event 被调用一次。"""
        entry = {"status": "testing", "updated": "2026-09-18T00:00:00+00:00"}
        with patch("core.admin_monitor._pgrep_live_worktree", return_value=False):
            with patch.object(self.bus, "_admin_inflight_guard", return_value=False):
                self.bus._recover_testing("spec-b", entry)
        self.pm.handle_event.assert_called_once_with(
            "spec_implemented", "spec-b", entry
        )

    def test_inflight_guard_via_adminstore_pathway(self):
        """经 AdminStore 通路（非 pm_engine.admin_monitor 引用）判定在飞。"""
        from core.admin_store import AdminStore, DISPOSITION
        store = AdminStore(self.tmpdir, self.logger)
        store.append({
            "kind": DISPOSITION,
            "signal_type": "verify_env_blocked",  # 非 orphaned_state 的在飞处置
            "spec": "spec-c",
            "admin_run_id": "admin-spec-c-1780000001",
            "status": "pending",
            "description": "在飞处置",
        })
        self.pm.agent_runner = None  # 切断通路(b)，验证通路(a)独立判定
        entry = {"status": "testing", "updated": "2026-09-18T00:00:00+00:00"}
        with patch("core.admin_monitor._pgrep_live_worktree", return_value=False):
            self.bus._recover_testing("spec-c", entry)
        self.pm.handle_event.assert_not_called()

    def test_inflight_guard_via_running_run_ids_pathway(self):
        """经 agent_runner 进程表通路判定在飞（admin-<spec>- 前缀 run 存活）。"""
        self.pm.agent_runner = MagicMock()
        self.pm.agent_runner.running_run_ids.return_value = ["admin-spec-d-1780000002"]
        entry = {"status": "testing", "updated": "2026-09-18T00:00:00+00:00"}
        with patch("core.admin_monitor._pgrep_live_worktree", return_value=False):
            self.bus._recover_testing("spec-d", entry)
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
        from core import fenix_session
        config = {"project": {"name": "t"},
                  "hooks": {"global": [{"id": "h1", "enabled": True,
                                        "events": ["blocked"], "action": "restart-daemon"}]}}
        eng = HookEngine(Path(self.tmpdir), config, logger=None)
        bus = self._bus(eng.dispatch)
        bus._update_known_state()
        self.sm.update_spec("s1", {"status": "blocked"})
        # restart-daemon hook 写请求前校验 supervisor_running（fix-supervisor-hosting-chain D4）；
        # 测试 tmpdir 假项目无 supervisor，须 mock 为托管状态使 hook 走成功路径。
        with patch.object(fenix_session, "supervisor_running", return_value=True):
            bus._dispatch_changes(self.sm.read_all())
        # hook 在守护线程内执行：轮询等待而非固定 sleep
        deadline = time.monotonic() + 3.0
        req = Path(self.tmpdir) / ".fenix" / "restart_request"
        while time.monotonic() < deadline and not req.exists():
            time.sleep(0.02)
        self.assertTrue(req.exists())
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


class TestDependencyWakeup(unittest.TestCase):
    """dispatch-dependency-wakeup 3.4/3.5：EventBus 检出依赖转入接受态 → 触发唤醒。

    触发判定（EventBus 层，MagicMock pm 断言调用）：接受态集合与
    PMEngine._dependencies_satisfied 单点一致（DEPENDENCY_ACCEPTED_STATUSES）；
    非接受态转移、无 dependents 均不触发（零副作用、零调用）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.sm.add_spec("A", {"status": "ready", "depends_on": "B", "priority": 5})
        self.sm.add_spec("B", {"status": "implementing"})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _bus(self):
        from core.event_bus import EventBus
        pm = MagicMock()
        bus = EventBus(self.state_path, self.sm, pm, {}, self.logger)
        return bus, pm

    def test_wakeup_when_dep_enters_accepted_status(self):
        """B 由 implementing（非接受态）转 pushed → 反查出 A 并触发唤醒（立即入队）。"""
        bus, pm = self._bus()
        bus._update_known_state()
        self.sm.update_spec("B", {"status": "pushed"})
        bus._dispatch_changes(self.sm.read_all())
        pm._wakeup_dependents.assert_called_once_with("B", ["A"])

    def test_no_wakeup_when_dep_not_accepted(self):
        """B 转 blocked 或仍 implementing → A 不被唤醒（不重评、不入队）。"""
        bus, pm = self._bus()
        bus._update_known_state()
        # blocked：非接受态
        self.sm.update_spec("B", {"status": "blocked"})
        bus._dispatch_changes(self.sm.read_all())
        pm._wakeup_dependents.assert_not_called()
        # implementing：仍非接受态
        self.sm.update_spec("B", {"status": "implementing"})
        bus._dispatch_changes(self.sm.read_all())
        pm._wakeup_dependents.assert_not_called()

    def test_wakeup_when_dep_enters_other_accepted_statuses(self):
        """接受态集合全部覆盖：B 转 done / verified / implemented 同样触发唤醒。"""
        bus, pm = self._bus()
        bus._update_known_state()
        for accepted in ("done", "verified", "implemented"):
            self.sm.update_spec("B", {"status": accepted})
            bus._dispatch_changes(self.sm.read_all())
        calls = [c.args for c in pm._wakeup_dependents.call_args_list]
        self.assertEqual(
            sorted(c[0] for c in calls),
            ["B", "B", "B"],
        )
        for c in calls:
            self.assertEqual(c, ("B", ["A"]))

    def test_no_dependents_zero_side_effect(self):
        """无任何 SPEC 依赖 D → 零调用、零日志（D 转入接受态仅常规事件）。"""
        self.sm.add_spec("D", {"status": "implementing"})  # 无人依赖它
        bus, pm = self._bus()
        bus._update_known_state()
        self.sm.update_spec("D", {"status": "pushed"})
        bus._dispatch_changes(self.sm.read_all())
        pm._wakeup_dependents.assert_not_called()

    def test_dependents_reverse_lookup_precise(self):
        """反查精确匹配：B2/BB 不因子串误配为 B 的 dependent。"""
        self.sm.add_spec("A2", {"status": "ready", "depends_on": "B2", "priority": 5})
        bus, pm = self._bus()
        bus._update_known_state()
        self.sm.update_spec("B", {"status": "pushed"})
        bus._dispatch_changes(self.sm.read_all())
        pm._wakeup_dependents.assert_called_once_with("B", ["A"])


class TestDependencyWakeupIdempotency(unittest.TestCase):
    """3.5 幂等与去重（PMEngine 层）：已有活跃派发 / 已在飞派发的 dependent
    不得重复入队；ready 且依赖满足的 dependent 唤醒后入队一次（冷却兜底）。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        self.runner.worktree_manager.has_active_worktree.return_value = False
        self.runner.has_live_attempt.return_value = False
        self.engine = PMEngine(self.sm, self.runner, {},
                               self.project_root, self.logger)
        self.sm.add_spec("A", {"status": "ready", "depends_on": "B", "priority": 5})
        self.sm.add_spec("B", {"status": "implementing"})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _accept_b(self):
        self.sm.update_spec("B", {"status": "pushed"})

    def test_dependent_with_active_worktree_not_reenqueued(self):
        """A 已有活跃派发（worktree 持锁）→ 唤醒时跳过，不重复入队。"""
        self._accept_b()
        self.runner.worktree_manager.has_active_worktree.return_value = True
        self.engine._wakeup_dependents("B", ["A"])
        self.assertEqual(self.engine._run_queue, [])

    def test_dependent_in_flight_dispatch_not_reenqueued(self):
        """A 已在飞派发（_pending_dispatches）→ 唤醒时跳过，不重复入队。"""
        self._accept_b()
        self.engine._pending_dispatches.add("A")
        try:
            self.engine._wakeup_dependents("B", ["A"])
            self.assertEqual(self.engine._run_queue, [])
        finally:
            self.engine._pending_dispatches.discard("A")

    def test_dependent_ready_enqueued_once(self):
        """A ready 且依赖满足 → 唤醒入队一次；重复唤醒（依赖再转接受态）不重复入队。"""
        self._accept_b()
        self.engine._process_queue = MagicMock()  # 避免 worker 线程异步副作用
        self.engine._wakeup_dependents("B", ["A"])
        self.engine._wakeup_dependents("B", ["A"])
        entries = [(e[1], e[2]) for e in self.engine._run_queue]
        self.assertEqual(entries.count(("A", "implementer")), 1)

    def test_dependent_dependency_unsatisfied_not_enqueued(self):
        """B 尚未转入接受态 → 重评不通过，A 不被入队（等待中保持等待）。"""
        self.engine._process_queue = MagicMock()
        self.engine._wakeup_dependents("B", ["A"])
        self.assertEqual(self.engine._run_queue, [])

    def test_event_bus_to_engine_wakeup_integration(self):
        """端到端：EventBus 检出 B→pushed → PMEngine 重评 → A 立即入队（无需 full_scan）。"""
        from core.event_bus import EventBus
        self.engine._process_queue = MagicMock()  # 入队即成立，避免 worker 副作用
        bus = EventBus(self.state_path, self.sm, self.engine, {}, self.logger)
        bus._update_known_state()
        self._accept_b()
        bus._dispatch_changes(self.sm.read_all())
        entries = [(e[1], e[2]) for e in self.engine._run_queue]
        self.assertIn(("A", "implementer"), entries)


class TestEventBusSpecReviewGate(unittest.TestCase):
    """add-spec-review-gate 7.2：reviewing → spec_reviewing 事件映射与 recovery。"""

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

    def test_status_to_event_maps_reviewing(self):
        """_status_to_event 映射 reviewing → spec_reviewing。"""
        from core.event_bus import EventBus
        self.assertEqual(EventBus._status_to_event("reviewing"), "spec_reviewing")

    def test_recover_one_reviewing_branch(self):
        """_recover_one 对 reviewing 走评审恢复分支（spec_reviewing 事件，
        MUST NOT 复用 drafted 分支的晋升链调用）。"""
        ok = self.bus._recover_one("spec-x", {"status": "reviewing"})
        self.assertTrue(ok)
        self.pm.handle_event.assert_called_once_with(
            "spec_reviewing", "spec-x", {"status": "reviewing"})

    def test_recover_one_drafted_still_promotes(self):
        """drafted 分支语义不受影响（仍触发 spec_drafted 晋升链）。"""
        ok = self.bus._recover_one("spec-d", {"status": "drafted"})
        self.assertTrue(ok)
        self.pm.handle_event.assert_called_once_with(
            "spec_drafted", "spec-d", {"status": "drafted"})


# ── fix-orphan-ready-recovery-liveness 2.1/2.2/3.4/3.5/3.6/3.10 ──
# 孤儿 ready 短周期精触发（recover_orphan_ready）测试。
# 真实 StateMachine + 真实 PMEngine（mock runner），确保 _dispatch_backoffed /
# _on_spec_ready / _enqueue 全链路行为可断言。


class TestRecoverOrphanReady(unittest.TestCase):
    """fix-orphan-ready-recovery-liveness 2.1/2.2：孤儿 ready 短周期精触发。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        self.runner.worktree_manager.has_active_worktree.return_value = False
        self.runner.has_live_attempt.return_value = False
        from core.pm_engine import PMEngine
        from core.event_bus import EventBus
        self.engine = PMEngine(self.sm, self.runner, {}, self.project_root, self.logger)
        self.engine._process_queue = MagicMock()  # 防止 worker 线程异步副作用
        self.bus = EventBus(self.state_path, self.sm, self.engine, {}, self.logger)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _orphan_ready(self, name="spec-orphan", **extra):
        """向 STATE.md 写入一个 ready 态孤儿 SPEC（error 非空、无 start_after、无 _cancelled_hold）。"""
        entry = {"status": "ready", "error": "dispatch stalled"}
        entry.update(extra)
        self.sm.add_spec(name, entry)

    # ── 3.4：孤儿 ready 经精触发重派 ────────────────────────────────

    def test_orphan_ready_redispatched(self):
        """error 非空 + 无存活子进程 + 无 start_after → handle_event('spec_ready') 被调用，
        state_machine.update_spec 收到 {'error': None}。"""
        self._orphan_ready()
        with patch.object(self.engine, "handle_event") as mock_handle:
            self.bus.recover_orphan_ready()
        mock_handle.assert_called_once()
        args = mock_handle.call_args[0]
        self.assertEqual(args[0], "spec_ready")
        self.assertEqual(args[1], "spec-orphan")
        # update_spec 被调用（error 从非空清为 None）
        specs = self.sm.read_all()
        self.assertIsNone(specs["spec-orphan"].get("error"))

    def test_start_after_not_due_skips(self):
        """start_after 未到期 → 不触发重派。"""
        import datetime as _dt
        future = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1)).isoformat()
        self._orphan_ready(start_after=future)
        with patch.object(self.engine, "handle_event") as mock_handle:
            self.bus.recover_orphan_ready()
        mock_handle.assert_not_called()

    def test_cancelled_hold_skips(self):
        """_cancelled_hold=True → 不触发重派。"""
        self._orphan_ready(_cancelled_hold=True)
        with patch.object(self.engine, "handle_event") as mock_handle:
            self.bus.recover_orphan_ready()
        mock_handle.assert_not_called()

    # ── 3.5：稳态零 STATE 写入 ─────────────────────────────────────

    def test_steady_state_zero_write(self):
        """error 已为空的健康 ready SPEC → update_spec / write_all 零调用。"""
        self._orphan_ready(error=None)
        with patch.object(self.sm, "update_spec") as mock_update, \
             patch.object(self.sm, "write_all") as mock_write:
            self.bus.recover_orphan_ready()
        mock_update.assert_not_called()
        mock_write.assert_not_called()

    # ── 3.6：单条异常隔离 ─────────────────────────────────────────

    def test_single_spec_exception_isolated(self):
        """某条 ready SPEC 恢复抛异常 → 其余照常完成，异常记 error 日志、不向上抛。"""
        self._orphan_ready(name="spec-good")
        self._orphan_ready(name="spec-bad")
        real_recover = self.bus._recover_ready

        def flaky(name, entry):
            if name == "spec-bad":
                raise RuntimeError("boom")
            return real_recover(name, entry)

        self.bus._recover_ready = flaky
        # recover_orphan_ready 不抛
        self.bus.recover_orphan_ready()
        # error 日志包含异常信息
        error_calls = [c for c in self.logger.error.call_args_list
                       if "spec-bad" in str(c)]
        self.assertTrue(len(error_calls) > 0)

    # ── 3.10：有意等待早退 ────────────────────────────────────────

    def test_backoff_early_exit_no_write(self):
        """ready + _dispatch_backoff_until 未到期 → 零写入、零重派、error 不被清空。"""
        import time as _time
        self._orphan_ready(_dispatch_backoff_until=int(_time.time() + 3600))
        with patch.object(self.sm, "update_spec") as mock_update, \
             patch.object(self.sm, "write_all") as mock_write, \
             patch.object(self.engine, "handle_event") as mock_handle:
            self.bus.recover_orphan_ready()
        mock_update.assert_not_called()
        mock_write.assert_not_called()
        mock_handle.assert_not_called()

    def test_cancelled_hold_early_exit_no_write(self):
        """ready + _cancelled_hold=True → 零写入、零重派。"""
        self._orphan_ready(_cancelled_hold=True)
        with patch.object(self.sm, "update_spec") as mock_update, \
             patch.object(self.sm, "write_all") as mock_write, \
             patch.object(self.engine, "handle_event") as mock_handle:
            self.bus.recover_orphan_ready()
        mock_update.assert_not_called()
        mock_write.assert_not_called()
        mock_handle.assert_not_called()

    def test_backoff_expired_resumes_recovery(self):
        """_dispatch_backoff_until 已过期 → 正常恢复路径。"""
        import time as _time
        self._orphan_ready(_dispatch_backoff_until=int(_time.time() - 60))
        with patch.object(self.engine, "handle_event") as mock_handle:
            self.bus.recover_orphan_ready()
        mock_handle.assert_called_once()
        self.assertEqual(mock_handle.call_args[0][0], "spec_ready")

    # ── 4.3 实测发现的恢复链路存活兜底缺陷（_ready_has_live_child ③）──────
    # daemon 真实环境观察（2026-09-17）发现：孤儿 ready 恢复走 _recover_ready →
    # _ready_has_live_child 时，agent_runner.has_live_attempt 已正确返回 False
    # （修正生效），但该方法的**自有兜底 ③**（_run_file_recent 只看 mtime）把
    # daemon 主动 SIGTERM 补写的终态 run（mtime 新鲜 + 末行 error）误判为存活，
    # 恢复被静默跳过——与 has_live_attempt 修正同口径后，兜底 ③ MUST 排除末行
    # 终态文件。

    def _ready_spec_with_run_file(self, runs_tail: str, *, mtime_age: float = 10):
        """写 ready SPEC + implementer_run 指向的 run 文件（可指定末行与 mtime 年龄）。"""
        import os as _os
        import time as _time
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"impl-spec-run-{int(_time.time())}"
        run_file = runs_dir / f"{run_id}.jsonl"
        lines = [
            {"type": "init"},
            {"type": "result", "result": "ok"} if runs_tail == "result" else
            {"type": "error", "error": "Exit code: 143", "exit_code": 143} if runs_tail == "error" else
            {"type": "system"},
        ]
        run_file.write_text(
            "".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8"
        )
        ts = _time.time() - mtime_age
        _os.utime(run_file, (ts, ts))
        self.sm.add_spec("spec-run", {
            "status": "ready", "error": "dispatch stalled",
            "implementer_run": run_id,
        })
        return run_file

    def test_ready_has_live_child_runs_tail_terminal_not_alive(self):
        """兜底 ③：run 文件 mtime 新鲜但末行终态（error/result）→ 不判存活。"""
        from core.agent_runner.liveness import LIVE_ATTEMPT_STREAM_WINDOW_SECONDS
        for tail in ("error", "result"):
            self._ready_spec_with_run_file(tail)
            self.assertFalse(
                self.bus._ready_has_live_child("spec-run"),
                f"末行 {tail} 终态 + mtime 新鲜不得判为存活（恢复不能被刚死的 run 挡住）",
            )
            # 清掉再构造下一组
            (self.project_root / ".fenix" / "STATE.md").unlink(missing_ok=True)
        self.assertTrue(LIVE_ATTEMPT_STREAM_WINDOW_SECONDS > 0)

    def test_ready_has_live_child_runs_tail_non_terminal_alive(self):
        """兜底 ③ fail-open：run 文件 mtime 新鲜且末行为非终态（system）→ 仍判存活。"""
        self._ready_spec_with_run_file("system")
        self.assertTrue(
            self.bus._ready_has_live_child("spec-run"),
            "末行非终态且 mtime 新鲜应视为存活（活 run 不被误杀）",
        )
