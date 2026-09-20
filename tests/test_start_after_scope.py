"""
start_after scope 配置回归测试（add-start-after-scope-config）。

覆盖 tasks 5.2/5.3/5.4：
- 5.2 dispatch 档（缺省）行为：晋升/评审/恢复四点不阻塞 + 谓词缺省返回 False
- 5.3 实现派发口与 scope 无关：ready + 未来 start_after / manual 两档均不派发
- 5.4 fail-open：monkeypatch start_after_pending 抛异常，谓词不吞、调用点 warning
"""
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, start_after_blocks_promotion, start_after_pending

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── fixture ─────────────────────────────────────────────────────────

def _future_iso(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _make_engine(sm, proot, config=None):
    from core.pm_engine import PMEngine
    logger = MagicMock()
    runner = MagicMock()
    runner.worktree_manager = MagicMock()
    runner.worktree_manager.has_active_worktree.return_value = False
    runner.has_live_attempt.return_value = False
    engine = PMEngine(sm, runner, config, proot, logger)
    engine._process_queue = MagicMock()
    return engine, logger


def _setup_spec_project(tmpdir, spec_name="myspec", status="drafted",
                        start_after=None):
    """最小可解析项目：.fenix/STATE.md + spec/changes/<name>/tasks.md。"""
    proot = Path(tmpdir)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    state_path = proot / ".fenix" / "STATE.md"
    sm = StateMachine(state_path, MagicMock())
    entry = {"status": status}
    if start_after is not None:
        entry["start_after"] = start_after
    sm.add_spec(spec_name, entry)
    (proot / "spec" / "changes" / spec_name).mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / spec_name / "tasks.md").write_text(
        "## 1. 阶段一\n\n- [x] 1.1 任务一\n", encoding="utf-8"
    )
    return proot, sm, state_path


# dispatch 档配置（缺省，等价不配 start_after_scope）
_DISPATCH_CONFIG = {"gates": {"promote_mode": "auto", "spec_review_mode": "never"}}
_FULL_CONFIG = {"gates": {"promote_mode": "auto", "spec_review_mode": "never", "start_after_scope": "full"}}


# ── 5.2 dispatch 档行为 ─────────────────────────────────────────────

class TestDispatchModeBehavior(unittest.TestCase):
    """dispatch 档（缺省）：晋升/评审入口不受 start_after 阻塞（tasks 5.2）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_future_start_after_promoted(self):
        """(a) drafted + 未来 start_after + dispatch → 照常晋升 ready，_on_spec_ready 被调。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_future_iso())
        engine, _ = _make_engine(sm, proot, _DISPATCH_CONFIG)
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "ready",
                         "dispatch 档下定时 drafted 应晋升 ready")
        engine._on_spec_ready.assert_called_once_with("myspec")

    def test_manual_sentinel_promoted(self):
        """(b) drafted + manual + dispatch → 照常晋升 ready。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after="manual")
        engine, _ = _make_engine(sm, proot, _DISPATCH_CONFIG)
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "ready",
                         "dispatch 档下 manual 哨兵 drafted 应晋升 ready")
        engine._on_spec_ready.assert_called_once_with("myspec")

    def test_future_start_after_dispatches_review(self):
        """(c) reviewing + 未来 start_after + dispatch → 照常入队评审。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="reviewing", start_after=_future_iso())
        engine, _ = _make_engine(sm, proot, _DISPATCH_CONFIG)
        engine._on_spec_reviewing("myspec")
        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 1, "dispatch 档下定时 reviewing 应入队评审")

    def test_recover_one_drafted_not_skipped(self):
        """(d) drafted 分支在 dispatch 档下不早退：handle_event 被调，返回 True。"""
        state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(state_path, MagicMock())
        sm.add_spec("spec-d", {"status": "drafted"})
        from core.event_bus import EventBus
        pm = MagicMock()
        bus = EventBus(state_path, sm, pm, _DISPATCH_CONFIG, MagicMock())
        entry = {"status": "drafted", "start_after": _future_iso()}
        ok = bus._recover_one("spec-d", entry)
        self.assertTrue(ok, "dispatch 档 recovery drafted 分支应返回 True")
        pm.handle_event.assert_called_once_with("spec_drafted", "spec-d", entry)

    def test_recover_one_reviewing_not_skipped(self):
        """(d) reviewing 分支在 dispatch 档下不早退：handle_event 被调，返回 True。"""
        state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(state_path, MagicMock())
        sm.add_spec("spec-r", {"status": "reviewing"})
        from core.event_bus import EventBus
        pm = MagicMock()
        bus = EventBus(state_path, sm, pm, _DISPATCH_CONFIG, MagicMock())
        entry = {"status": "reviewing", "start_after": _future_iso()}
        ok = bus._recover_one("spec-r", entry)
        self.assertTrue(ok, "dispatch 档 recovery reviewing 分支应返回 True")
        pm.handle_event.assert_called_once_with("spec_reviewing", "spec-r", entry)

    def test_predicate_config_none_returns_false(self):
        """(e) config=None 时 start_after_blocks_promotion 返回 False（缺省 dispatch）。"""
        entry = {"start_after": _future_iso()}
        self.assertFalse(start_after_blocks_promotion(entry, None),
                         "config=None 等价 dispatch，不阻塞")

    def test_predicate_no_gates_returns_false(self):
        """(e) 无 gates 段时返回 False（缺省 dispatch）。"""
        entry = {"start_after": _future_iso()}
        self.assertFalse(start_after_blocks_promotion(entry, {}),
                         "无 gates 段不阻塞")

    def test_predicate_entry_none_returns_false(self):
        """(e2) entry is None 时返回 False（start_after_pending(None) 内部 (entry or {})）。"""
        self.assertFalse(start_after_blocks_promotion(None),
                         "entry=None 不阻塞，交由调用点自然处理")

    def test_full_mode_blocks_promotion对照(self):
        """(f) full 档对照组：future start_after 不晋升 drafted。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_future_iso())
        engine, _ = _make_engine(sm, proot, _FULL_CONFIG)
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "drafted",
                         "full 档下定时 drafted 应停留草稿态")
        engine._on_spec_ready.assert_not_called()

    def test_full_mode_blocks_reviewing对照(self):
        """(f) full 档对照组：future start_after 不入队 reviewing。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="reviewing", start_after=_future_iso())
        engine, _ = _make_engine(sm, proot, _FULL_CONFIG)
        initial_q = list(engine._dispatcher._run_queue)
        engine._on_spec_reviewing("myspec")
        self.assertEqual(list(engine._dispatcher._run_queue), initial_q,
                         "full 档下定时 reviewing 不应入队")

    def test_check_scheduling_deadlines放行_full档(self):
        """(f) pass-through 路径必须在 full 档写：check_scheduling_deadlines 对已过期
        drafted 正常放行（handler 内部 scope 守卫恒放行，因为 start_after 已过期）。"""
        from datetime import datetime, timedelta, timezone
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_past_iso())
        engine, _ = _make_engine(sm, proot, _FULL_CONFIG)
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "ready",
                         "已过期 start_after 在 full 档下仍应正常晋升")
        engine._on_spec_ready.assert_called_once_with("myspec")


# ── 5.3 实现派发口与 scope 无关 ──────────────────────────────────────

class TestDispatchScopeInvariance(unittest.TestCase):
    """实现派发口恒受 start_after 门约束，与 scope 无关（tasks 5.3）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ready_future_not_dispatched_dispatch_mode(self):
        """ready + 未来 start_after + dispatch → 不派发。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="ready", start_after=_future_iso())
        engine, _ = _make_engine(sm, proot, _DISPATCH_CONFIG)
        engine._on_spec_ready("myspec")
        engine._process_queue.assert_not_called()
        self.assertEqual(sm.read_one("myspec")["status"], "ready")

    def test_ready_future_not_dispatched_full_mode(self):
        """ready + 未来 start_after + full → 不派发。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="ready", start_after=_future_iso())
        engine, _ = _make_engine(sm, proot, _FULL_CONFIG)
        engine._on_spec_ready("myspec")
        engine._process_queue.assert_not_called()
        self.assertEqual(sm.read_one("myspec")["status"], "ready")

    def test_ready_manual_not_dispatched_dispatch_mode(self):
        """ready + manual + dispatch → 不派发（哨兵不自动实现恒成立）。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="ready", start_after="manual")
        engine, _ = _make_engine(sm, proot, _DISPATCH_CONFIG)
        engine._on_spec_ready("myspec")
        engine._process_queue.assert_not_called()
        self.assertEqual(sm.read_one("myspec")["status"], "ready")

    def test_ready_manual_not_dispatched_full_mode(self):
        """ready + manual + full → 不派发。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="ready", start_after="manual")
        engine, _ = _make_engine(sm, proot, _FULL_CONFIG)
        engine._on_spec_ready("myspec")
        engine._process_queue.assert_not_called()
        self.assertEqual(sm.read_one("myspec")["status"], "ready")


# ── 5.4 fail-open 用例 ─────────────────────────────────────────────

class TestFailOpen(unittest.TestCase):
    """fail-open：谓词不吞异常，调用点 try/except + warning（tasks 5.4）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_predicate_propagates_exception(self):
        """start_after_blocks_promotion 本身不吞异常（异常向上传播到调用点）。"""
        entry = {"start_after": _future_iso()}
        with patch("core.state_machine.start_after_pending",
                   side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError, msg="谓词 MUST NOT 吞异常"):
                start_after_blocks_promotion(entry, _FULL_CONFIG)

    def test_on_spec_drafted_fail_open(self):
        """_on_spec_drafted：判定异常走 try/except → warning 日志，不阻塞既有路径。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_future_iso())
        engine, logger = _make_engine(sm, proot, _FULL_CONFIG)
        with patch("core.state_machine.start_after_pending",
                   side_effect=RuntimeError("boom")):
            engine._on_spec_drafted("myspec")
        self.assertTrue(
            any("start_after 门控判定异常" in c.args[1]
                for c in logger.warning.call_args_list),
            "判定异常须记 warning 日志",
        )

    def test_on_spec_reviewing_fail_open(self):
        """_on_spec_reviewing：判定异常走 try/except → warning 日志，继续入队。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="reviewing", start_after=_future_iso())
        engine, logger = _make_engine(sm, proot, _FULL_CONFIG)
        with patch("core.state_machine.start_after_pending",
                   side_effect=RuntimeError("boom")):
            engine._on_spec_reviewing("myspec")
        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 1, "判定异常须 fail-open 继续入队评审")
        self.assertTrue(
            any("start_after 门控判定异常" in c.args[1]
                for c in logger.warning.call_args_list),
            "判定异常须记 warning 日志",
        )

    def test_recover_one_fail_open(self):
        """_recover_one drafted 分支：判定异常走 try/except → warning 日志，继续恢复。"""
        state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(state_path, MagicMock())
        sm.add_spec("spec-x", {"status": "drafted"})
        from core.event_bus import EventBus
        pm = MagicMock()
        logger = MagicMock()
        bus = EventBus(state_path, sm, pm, _FULL_CONFIG, logger)
        entry = {"status": "drafted", "start_after": _future_iso()}
        with patch("core.state_machine.start_after_pending",
                   side_effect=RuntimeError("boom")):
            ok = bus._recover_one("spec-x", entry)
        self.assertTrue(ok, "异常时不早退，走既有恢复路径")
        pm.handle_event.assert_called_once_with("spec_drafted", "spec-x", entry)
        self.assertTrue(
            any("start_after 判定异常" in c.args[1]
                for c in logger.warning.call_args_list),
            "判定异常须记 warning 日志",
        )


if __name__ == "__main__":
    unittest.main()
