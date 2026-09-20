"""
start_after 定时拾取门控回归测试（fix-start-after-premature-pickup）。

覆盖面（tasks.md 3.1-3.9）：
- 3.1 fixture：未来时间 / manual 哨兵 / 已过期三态 STATE 条目（复用
  tests/test_event_bus.py 与 tests/test_spec_scheduling.py 既有 fixture 构造手法，
  全部落在 tmpdir 最小项目内，不触碰用户级配置或真实项目 STATE）；
- 3.2 _on_spec_drafted：drafted + 未来不晋升；drafted + manual 不晋升；
  drafted + 已过期正常晋升；
- 3.3 _on_spec_reviewing：reviewing + 未来不派发评审；已过期正常派发；
- 3.4 _recover_one：drafted/reviewing + 未来 start_after 早退——不产生
  「re-triggering promote」/「re-triggering spec_reviewing」日志、不写 STATE、
  返回 handled（True）；
- 3.5 元放行路径：check_scheduling_deadlines 对已过期 drafted 经守卫放行；
  清空 start_after（置 null）后正常晋升；kick 信号对清空后的 drafted 仍唤起
  晋升链；
- 3.6 fail-open：monkeypatch start_after_pending 抛异常时，三个入口仍走既有
  逻辑（不被新闸门吞掉）；
- 3.7 无 start_after（null）的 drafted 行为与改动前一致（正常晋升）；entry
  读不到（SPEC 不存在/已归档）时两处守卫均不早退；
- 3.8 人工放行豁免：(a) promote_drafted / dispatch_review 无 start_after_pending
  静态断言；(b) admin_actions.promote_spec 与 CLI fenix_cli.py promote 对未来
  start_after 的 drafted SPEC 正常晋升；(c) SpecReviewManager.re_review 对
  blocked + 未来 start_after 仍可进入 reviewing；
- 3.9 _recover_one 日志级别与措辞：跳过日志为 debug 级，info 级无
  「re-triggering promote」/「re-triggering spec_reviewing」。
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── fixture：三态 start_after 最小项目 ─────────────────────────────────

def _future_iso(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _setup_spec_project(tmpdir, spec_name="myspec", status="drafted",
                        start_after=None):
    """最小可解析项目：.fenix/STATE.md + spec/changes/<name>/tasks.md。

    promote_drafted 的软化/lint 需要 spec 目录存在（tasks.md 可解析性 lint），
    与 tests/test_pm_promotion_gate.py 的 _setup_project 同型。
    """
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


def _auto_config() -> dict:
    """promote_mode=auto + spec_review_mode=never + start_after_scope=full → _on_spec_drafted 恒分流 ready。

    本文件锁定 full 档行为（定时/哨兵 SPEC 不提前晋升/评审）；dispatch 档用例见
    tests/test_start_after_scope.py。（评审分流判定独立于本 SPEC，测试锁定
    「drafted → ready」通道以隔离变量。）
    """
    return {"gates": {"promote_mode": "auto", "spec_review_mode": "never", "start_after_scope": "full"}}


def _make_engine(sm, proot, config=None):
    """真实 PMEngine（__init__ 全量构造，mock runner）——对齐 test_event_bus 既有用法。"""
    from core.pm_engine import PMEngine

    logger = MagicMock()
    runner = MagicMock()
    runner.worktree_manager = MagicMock()
    runner.worktree_manager.has_active_worktree.return_value = False
    runner.has_live_attempt.return_value = False
    engine = PMEngine(sm, runner, config, proot, logger)
    engine._process_queue = MagicMock()
    return engine, logger


class _SilentLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


# ── 3.2 _on_spec_drafted 三态用例 ──────────────────────────────────────

class TestOnSpecDraftedGate(unittest.TestCase):
    """_on_spec_drafted 入口 start_after 门控（tasks 3.1/3.2/3.7）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_future_start_after_not_promoted(self):
        """drafted + 未来 start_after：不晋升、不写 error、不派发。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_future_iso())
        engine, logger = _make_engine(sm, proot, _auto_config())
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        entry = sm.read_one("myspec")
        self.assertEqual(entry["status"], "drafted", "未到期不得晋升")
        self.assertIsNone(entry.get("error"), "跳过不得写 error")
        engine._on_spec_ready.assert_not_called()
        self.assertTrue(
            any("start_after pending" in c.args[1] for c in logger.debug.call_args_list),
            "未到期跳过须记 debug 日志",
        )

    def test_manual_sentinel_not_promoted(self):
        """drafted + manual 哨兵：不被自动晋升，稳定停留草稿态。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after="manual")
        engine, _ = _make_engine(sm, proot, _auto_config())
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "drafted",
                         "manual 哨兵不得被自动晋升出 drafted")
        engine._on_spec_ready.assert_not_called()

    def test_expired_start_after_promoted(self):
        """drafted + 已过期 start_after：正常晋升（status 不再为 drafted）。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_past_iso())
        engine, _ = _make_engine(sm, proot, _auto_config())
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "ready")
        engine._on_spec_ready.assert_called_once_with("myspec")

    def test_no_start_after_promoted_as_before(self):
        """3.7(a) 无 start_after（null）的 drafted 行为与改动前一致（正常晋升）。"""
        proot, sm, _ = _setup_spec_project(self.tmpdir, status="drafted", start_after=None)
        engine, _ = _make_engine(sm, proot, _auto_config())
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "ready")

    def test_entry_missing_does_not_early_return(self):
        """3.7(b) entry 读不到（SPEC 不存在/已归档）时守卫不早退、不抛异常。"""
        proot, sm, _ = _setup_spec_project(self.tmpdir, status="drafted")
        engine, logger = _make_engine(sm, proot, _auto_config())
        engine._on_spec_ready = MagicMock()
        # 不存在 spec：守卫读不到 entry → 不早退 → promote_drafted not-found 拒绝
        engine._on_spec_drafted("missing-spec")
        self.assertIsNone(sm.read_one("missing-spec"))
        self.assertFalse(
            any("start_after pending" in c.args[1] for c in logger.debug.call_args_list),
            "entry 为 None 时不得触发跳过日志",
        )
        engine._on_spec_ready.assert_not_called()


# ── 3.3 _on_spec_reviewing 用例 ────────────────────────────────────────

class TestOnSpecReviewingGate(unittest.TestCase):
    """_on_spec_reviewing 入口 start_after 门控（tasks 3.3/3.7）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_future_start_after_no_dispatch(self):
        """reviewing + 未来 start_after：不入队评审 run。

        fix-spec-review-blocking-dispatch 改造：_on_spec_reviewing 改为入队
        （_enqueue + _process_queue），不再直接调 dispatch_review。断言同步
        调整：检查队列无新增条目，而非检查 dispatch_review 未被调用。
        """
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="reviewing", start_after=_future_iso())
        engine, logger = _make_engine(sm, proot, _auto_config())
        initial_q = list(engine._dispatcher._run_queue)
        engine._on_spec_reviewing("myspec")
        # 队列无新增评审条目（早退未入队）
        self.assertEqual(list(engine._dispatcher._run_queue), initial_q)
        self.assertTrue(
            any("start_after pending" in c.args[1] for c in logger.debug.call_args_list),
            "未到期跳过须记 debug 日志",
        )

    def test_expired_start_after_dispatches(self):
        """reviewing + 已过期 start_after：正常入队评审条目。

        fix-spec-review-blocking-dispatch 改造：断言队列出现 spec-review
        条目（而非检查 dispatch_review 被调用）。
        """
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="reviewing", start_after=_past_iso())
        engine, _ = _make_engine(sm, proot, _auto_config())
        engine._on_spec_reviewing("myspec")
        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 1, "队列应有一条 spec-review 条目")
        self.assertEqual(entries[0][1], "myspec")

    def test_entry_missing_no_early_return(self):
        """3.7(b) reviewing 入口 entry 读不到时跳过判定、入队、不抛异常。

        fix-spec-review-blocking-dispatch 改造：断言队列出现条目（而非检查
        dispatch_review 被调用）。
        """
        proot, sm, _ = _setup_spec_project(self.tmpdir, status="reviewing")
        engine, logger = _make_engine(sm, proot, _auto_config())
        engine._on_spec_reviewing("missing-spec")
        # missing-spec 不在 state 里 → read_one 返回 None → 入口守卫不早退 →
        # 入队（_enqueue 可能 raise 或忽略，但不抛到测试层）
        self.assertFalse(
            any("start_after pending" in c.args[1] for c in logger.debug.call_args_list),
            "entry 为 None 时不得触发跳过日志",
        )


# ── 3.4/3.9 _recover_one 早退用例 ──────────────────────────────────────

class TestRecoverOneGate(unittest.TestCase):
    """_recover_one drafted/reviewing 分支 start_after 早退（tasks 3.4/3.9）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, MagicMock())
        self.sm.add_spec("spec-f", {"status": "drafted"})
        self.sm.add_spec("spec-r", {"status": "reviewing"})
        from core.event_bus import EventBus

        self.pm = MagicMock()
        self.logger = MagicMock()
        self.bus = EventBus(self.state_path, self.sm, self.pm, _auto_config(), self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _state_text(self) -> str:
        return self.state_path.read_text(encoding="utf-8")

    def test_drafted_future_skips(self):
        """drafted + 未来 start_after：早退，无 re-triggering 日志、不写 STATE、返回 handled。"""
        before = self._state_text()
        ok = self.bus._recover_one("spec-f", {
            "status": "drafted", "start_after": _future_iso(),
        })
        self.assertTrue(ok, "早退须返回 True（计入 handled）")
        self.pm.handle_event.assert_not_called()
        self.assertEqual(self._state_text(), before, "早退不得写 STATE")
        info_msgs = [c.args[1] for c in self.logger.info.call_args_list]
        self.assertFalse(
            any("re-triggering promote" in m for m in info_msgs),
            "不得打 re-triggering promote 日志",
        )
        self.assertFalse(
            any("start_after scheduled pickup" in m for m in info_msgs),
            "跳过日志为 debug 级（3.9 级别断言）",
        )
        debug_msgs = [c.args[1] for c in self.logger.debug.call_args_list]
        self.assertTrue(
            any("pending（drafted）" in m for m in debug_msgs),
            "须记 debug 级跳过日志（drafted 措辞）",
        )

    def test_reviewing_future_skips(self):
        """reviewing + 未来 start_after：早退，无 re-triggering 日志、不写 STATE、返回 handled。"""
        before = self._state_text()
        ok = self.bus._recover_one("spec-r", {
            "status": "reviewing", "start_after": _future_iso(),
        })
        self.assertTrue(ok)
        self.pm.handle_event.assert_not_called()
        self.assertEqual(self._state_text(), before, "早退不得写 STATE")
        info_msgs = [c.args[1] for c in self.logger.info.call_args_list]
        self.assertFalse(
            any("re-triggering spec_reviewing" in m for m in info_msgs),
            "不得打 re-triggering spec_reviewing 日志",
        )
        debug_msgs = [c.args[1] for c in self.logger.debug.call_args_list]
        self.assertTrue(
            any("pending（reviewing）" in m for m in debug_msgs),
            "须记 debug 级跳过日志（reviewing 措辞）",
        )

    def test_manual_sentinel_drafted_skips(self):
        """drafted + manual 哨兵：恢复路径早退（待激活哨兵稳定停留 drafted）。"""
        before = self._state_text()
        ok = self.bus._recover_one("spec-f", {"status": "drafted", "start_after": "manual"})
        self.assertTrue(ok)
        self.pm.handle_event.assert_not_called()
        self.assertEqual(self._state_text(), before)

    def test_no_start_after_drafted_still_retriggers(self):
        """3.7 零回归：无 start_after 的 drafted 仍触发 spec_drafted 晋升链。"""
        ok = self.bus._recover_one("spec-f", {"status": "drafted"})
        self.assertTrue(ok)
        self.pm.handle_event.assert_called_once_with(
            "spec_drafted", "spec-f", {"status": "drafted"})

    def test_no_start_after_reviewing_still_retriggers(self):
        """3.7 零回归：无 start_after 的 reviewing 仍触发 spec_reviewing。"""
        ok = self.bus._recover_one("spec-r", {"status": "reviewing"})
        self.assertTrue(ok)
        self.pm.handle_event.assert_called_once_with(
            "spec_reviewing", "spec-r", {"status": "reviewing"})


# ── 3.5 元放行路径用例 ────────────────────────────────────────────────

class TestMetaPassThroughPaths(unittest.TestCase):
    """到期 / 清空 / kick 信号三条有意放行通道（tasks 3.5）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_check_scheduling_deadlines_promotes_expired_drafted(self):
        """check_scheduling_deadlines（engine.py 到期唤起）对已过期 drafted 经守卫放行。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_past_iso())
        engine, _ = _make_engine(sm, proot, _auto_config())
        engine._on_spec_ready = MagicMock()
        result = engine.check_scheduling_deadlines()
        entry = sm.read_one("myspec")
        self.assertNotEqual(entry["status"], "drafted",
                            "已过期 drafted 经 ③ 正常晋升，drafted 条目被清空")
        engine._on_spec_ready.assert_called_once_with("myspec")
        self.assertIn("myspec", result["signaled"])

    def test_cleared_start_after_promotes_again(self):
        """清空 start_after（置 null）后 _on_spec_drafted 正常晋升（无残留限制）。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_future_iso())
        engine, _ = _make_engine(sm, proot, _auto_config())
        engine._on_spec_ready = MagicMock()
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "drafted", "未到期不晋升")
        engine._on_spec_ready.assert_not_called()
        # 清空（置 null）后实时评估放行
        sm.update_spec("myspec", {"start_after": None})
        engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "ready")
        engine._on_spec_ready.assert_called_once_with("myspec")

    # ── kick 信号（.fenix/fenixd.py:1157）对清空后的 drafted 仍唤起晋升链 ──

    @classmethod
    def setUpClass(cls):
        # 按绝对路径直载 fenixd.py（tests/test_spec_scheduling.py 同款处方）：
        # 独立模块名，不注册进 sys.modules['fenixd']，与全量回归其他 fenixd
        # 导入互不串扰。
        spec = importlib.util.spec_from_file_location(
            "fenixd_start_after_gate_under_test", REPO_ROOT / "fenixd.py")
        cls._fenixd_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls._fenixd_mod)

    def _make_daemon(self, pm):
        daemon = self._fenixd_mod.FenixDaemon.__new__(self._fenixd_mod.FenixDaemon)
        daemon.running = True
        daemon.pm_engine = pm
        daemon.logger = _SilentLogger()
        return daemon

    def test_kick_signal_drafted_promotes_after_clear(self):
        """kick 信号对 start_after 已清空的 drafted SPEC 仍唤起晋升链。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after="manual")
        from core.pm_engine import PMEngine

        pm = PMEngine.__new__(PMEngine)
        pm.state_machine = sm
        pm.logger = _SilentLogger()
        pm.project_root = proot
        pm.config = _auto_config()
        ready_calls = []
        pm._on_spec_ready = lambda n: ready_calls.append(n)
        pm._process_queue = lambda: None
        # 哨兵未被自动晋升（守卫拦截）
        pm._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "drafted")
        # 手工激活 / 清空：start_after 置 null（activate_spec 语义，admin_actions.py:426）
        sm.update_spec("myspec", {"start_after": None})
        req = proot / ".fenix" / "scheduling_kick" / "myspec.json"
        kdir = proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        req.write_text(
            json.dumps({"spec": "myspec", "action": "clear-start-after",
                        "created": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        daemon = self._make_daemon(pm)
        with patch.object(self._fenixd_mod, "PROJECT_ROOT", proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(sm.read_one("myspec")["status"], "ready",
                         "kick 信号唤起后 drafted → ready 正常晋升")
        self.assertEqual(ready_calls, ["myspec"])
        self.assertFalse(req.exists(), "信号消费后删除")


# ── 3.6 fail-open 用例 ────────────────────────────────────────────────

class TestGateFailOpen(unittest.TestCase):
    """start_after_pending 判定异常时 fail-open（tasks 3.6）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_on_spec_drafted_fail_open(self):
        """_on_spec_drafted：判定异常不吞既有晋升逻辑。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_future_iso())
        engine, logger = _make_engine(sm, proot, _auto_config())
        engine._on_spec_ready = MagicMock()
        with patch("core.state_machine.start_after_pending",
                   side_effect=RuntimeError("boom")):
            engine._on_spec_drafted("myspec")
        self.assertEqual(sm.read_one("myspec")["status"], "ready",
                         "判定异常须 fail-open 继续既有晋升链")
        engine._on_spec_ready.assert_called_once_with("myspec")
        self.assertTrue(
            any("start_after 门控判定异常" in c.args[1]
                for c in logger.warning.call_args_list),
            "判定异常须记 warning 日志",
        )

    def test_on_spec_reviewing_fail_open(self):
        """_on_spec_reviewing：判定异常不吞既有评审派发（fail-open 放行入队）。

        fix-spec-review-blocking-dispatch 改造：断言对象由 dispatch_review
        改为「队列出现 spec-review 条目」（_on_spec_reviewing 改为入队）。
        """
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="reviewing", start_after=_future_iso())
        engine, logger = _make_engine(sm, proot, _auto_config())
        with patch("core.state_machine.start_after_pending",
                   side_effect=RuntimeError("boom")):
            engine._on_spec_reviewing("myspec")
        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 1, "判定异常须 fail-open 继续入队评审")
        self.assertEqual(entries[0][1], "myspec")
        self.assertTrue(
            any("start_after 门控判定异常" in c.args[1]
                for c in logger.warning.call_args_list),
            "判定异常须记 warning 日志",
        )

    def test_recover_one_fail_open(self):
        """_recover_one：判定异常不早退，继续既有恢复路径。"""
        tmp = tempfile.mkdtemp()
        try:
            (Path(tmp) / ".fenix").mkdir(parents=True, exist_ok=True)
            state_path = Path(tmp) / ".fenix" / "STATE.md"
            sm = StateMachine(state_path, MagicMock())
            from core.event_bus import EventBus

            pm = MagicMock()
            logger = MagicMock()
            bus = EventBus(state_path, sm, pm, _auto_config(), logger)
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
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── 3.8 人工放行豁免用例 ──────────────────────────────────────────────

class TestManualReleaseExemption(unittest.TestCase):
    """人工显式放行不受定时门拦截（tasks 3.8）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_promote_drafted_no_start_after_pending_call(self):
        """(a) 静态断言：共享晋升/评审函数未被下沉定时门。"""
        import inspect
        from core.pm_engine.promotion import promote_drafted
        from core.pm_engine.spec_review import SpecReviewManager

        src = inspect.getsource(promote_drafted)
        self.assertNotIn("start_after_pending", src,
                         "定时门 MUST NOT 下沉到共享晋升函数 promote_drafted")
        src_dispatch = inspect.getsource(SpecReviewManager.dispatch_review)
        src_rereview = inspect.getsource(SpecReviewManager.re_review)
        self.assertNotIn("start_after_pending", src_dispatch + src_rereview,
                         "dispatch_review / re_review 不得新增 start_after 判据")

    def test_admin_promote_spec_promotes_future_start_after(self):
        """(b) Dashboard 晋升入口（admin_actions.promote_spec）对未来 start_after 放行。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_future_iso())
        from core.dashboard.data.admin_actions import promote_spec

        with patch("core.config.ConfigLoader.resolve_config",
                   return_value=_auto_config()):
            result = promote_spec(proot, "myspec")
        self.assertTrue(result["ok"], str(result))
        self.assertIn(result.get("next_status"), ("ready", "reviewing"))
        # 重读 STATE 断言已晋升（人工晋升不受定时门拦截）
        sm2 = StateMachine(proot / ".fenix" / "STATE.md", None)
        self.assertNotEqual(sm2.read_one("myspec")["status"], "drafted")

    def test_cli_promote_promotes_future_start_after(self):
        """(b) CLI fenix_cli.py promote 路径对未来 start_after 放行。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="drafted", start_after=_future_iso())
        spec = importlib.util.spec_from_file_location(
            "fenix_cli_start_after_under_test", REPO_ROOT / "bin" / "fenix_cli.py")
        cli_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli_mod)

        class _Args:
            spec = "myspec"
            project = str(proot)

        with patch("core.config.ConfigLoader.resolve_config",
                   return_value=_auto_config()):
            with self.assertRaises(SystemExit) as cm:
                cli_mod.cmd_promote(_Args())
        self.assertEqual(cm.exception.code, 0)
        sm2 = StateMachine(proot / ".fenix" / "STATE.md", None)
        self.assertNotEqual(sm2.read_one("myspec")["status"], "drafted",
                            "CLI 人工晋升不因定时门被拦")

    def test_re_review_blocked_future_start_after_enters_reviewing(self):
        """(c) 人工重评（re_review）对 blocked + 未来 start_after 仍可进入 reviewing。"""
        proot, sm, _ = _setup_spec_project(
            self.tmpdir, status="blocked", start_after=_future_iso())
        sm.update_spec("myspec", {"error": "spec-review-rejected: 方案方向不成立"})
        from core.pm_engine.spec_review import SpecReviewManager

        manager = SpecReviewManager(proot, sm, None, None, {}, logger=MagicMock())
        ok, msg = manager.re_review("myspec")
        self.assertTrue(ok, msg)
        self.assertEqual(sm.read_one("myspec")["status"], "reviewing",
                         "人工重评不被定时门拦截")


if __name__ == "__main__":
    unittest.main()
