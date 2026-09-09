"""
SPEC 定时调度测试（add-spec-scheduling-controls）。

覆盖面：
- 1.1 状态机层共享基础：parse_utc / start_after_pending / parse_orig_status
  纯函数 + start_after/frozen_until 字段持久化（serialize/parse 白名单）；
- 2.1/2.2 start_after 门控：未到期跳过、不写 STATE、到期放行、非法格式
  与过去时间等价无限制（dispatch 候选筛选 + _on_spec_ready 入口）；
- 2.3 定时解冻：到期自动解冻恢复原状态、清 frozen_until、幂等、重启扫描
  兜底、设置过去时间立即解冻、「定时解冻」来源标记；
- 1.2/6.3 冻结双轨回归：StateMachine.freeze_spec → dashboard 解冻 →
  status 正确恢复（半死态消除）。

fixture 说明：最小可解析项目 = .fenix/STATE.md（调度相关测试只依赖
STATE 读写）；dispatch 门控测试用 PMEngine.__new__ 绕过 __init__。
"""
import json
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_spec_scheduling_project(tmp_path: Path) -> Path:
    """最小可解析项目：仅 .fenix/STATE.md（调度测试只依赖 STATE 读写）。"""
    proot = tmp_path / "proj-a"
    proot.mkdir(parents=True, exist_ok=True)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: ready\n- priority: 2\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n"
        "- start_after: null\n- frozen_until: null\n"
        "- frozen: null\n\n"
        "### donespec\n- status: done\n- priority: 1\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n"
        "- start_after: null\n- frozen_until: null\n"
        "- frozen: null\n",
        encoding="utf-8",
    )
    return proot


def make_state_machine(proot: Path):
    from core.state_machine import StateMachine
    return StateMachine(proot / ".fenix" / "STATE.md", None)


class TestSharedTimeTools(unittest.TestCase):
    """1.1 状态机层共享基础：parse_utc / start_after_pending / parse_orig_status。"""

    def setUp(self):
        from core.state_machine import (
            parse_orig_status, parse_utc, start_after_pending,
        )
        self.parse_utc = parse_utc
        self.start_after_pending = start_after_pending
        self.parse_orig_status = parse_orig_status

    def test_parse_utc_basic(self):
        dt = self.parse_utc("2026-09-07T01:00:00+00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 1)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_utc_z_suffix(self):
        dt = self.parse_utc("2026-09-07T01:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 1)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_utc_with_offset_normalizes(self):
        # UTC+8 的本地 09:00 → UTC 01:00
        dt = self.parse_utc("2026-09-07T09:00:00+08:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 1)

    def test_parse_utc_naive_treated_as_utc(self):
        dt = self.parse_utc("2026-09-07T01:00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_utc_invalid_returns_none(self):
        for bad in ("明天早上", "下周一", "2026-13-99", "", None, 12345):
            self.assertIsNone(self.parse_utc(bad), f"should reject {bad!r}")

    def test_parse_utc_accepts_datetime_input(self):
        dt = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(self.parse_utc(dt), dt)

    def test_start_after_pending_future(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        entry = {"start_after": "2026-09-07T01:00:00+00:00"}
        self.assertTrue(self.start_after_pending(entry, now))

    def test_start_after_missing_is_not_pending(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        self.assertFalse(self.start_after_pending({}, now))
        self.assertFalse(self.start_after_pending({"start_after": None}, now))

    def test_start_after_past_equivalent_no_limit(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        entry = {"start_after": "2026-09-06T09:00:00+00:00"}
        self.assertFalse(self.start_after_pending(entry, now))
        exact = {"start_after": now.isoformat()}
        self.assertFalse(self.start_after_pending(exact, now))

    def test_start_after_invalid_parse_is_not_pending(self):
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        # 解析失败视为不阻塞（fail-open，脏值不卡死调度）
        self.assertFalse(self.start_after_pending({"start_after": "明天早上"}, now))

    def test_parse_orig_status_ok(self):
        self.assertEqual(
            self.parse_orig_status("用户指令冻结：原状态 testing · 人工确认"),
            "testing",
        )
        self.assertEqual(
            self.parse_orig_status("用户指令冻结：原状态 ready"),
            "ready",
        )

    def test_parse_orig_status_missing_falls_back_ready(self):
        self.assertEqual(self.parse_orig_status(""), "ready")
        self.assertEqual(self.parse_orig_status("用户指令冻结："), "ready")
        self.assertEqual(self.parse_orig_status(None), "ready")
        self.assertEqual(self.parse_orig_status("其他错误无原状态"), "ready")


class TestSchedulingFieldsPersistence(unittest.TestCase):
    """1.1 状态机层：start_after/frozen_until 经 serialize/parse 白名单持久化。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_spec_scheduling_project(Path(self.tmpdir))
        self.sm = make_state_machine(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_and_reload_roundtrip(self):
        iso = "2026-09-07T01:00:00+00:00"
        self.assertTrue(self.sm.update_spec("myspec", {"start_after": iso}))
        # 重新实例化（模拟 daemon 重启），字段必须仍能读回
        sm2 = make_state_machine(self.proot)
        entry = sm2.read_one("myspec")
        self.assertEqual(entry.get("start_after"), iso)

    def test_update_and_reload_frozen_until_roundtrip(self):
        iso = "2026-09-08T01:00:00+00:00"
        self.assertTrue(self.sm.update_spec("myspec", {"frozen_until": iso}))
        sm2 = make_state_machine(self.proot)
        self.assertEqual(sm2.read_one("myspec").get("frozen_until"), iso)

    def test_null_fields_persist_as_none(self):
        self.assertTrue(self.sm.update_spec("myspec", {"start_after": None}))
        sm2 = make_state_machine(self.proot)
        self.assertIsNone(sm2.read_one("myspec").get("start_after"))

    def test_add_spec_passthrough_new_fields(self):
        self.assertTrue(self.sm.add_spec("newspec", {
            "status": "drafted",
            "start_after": "2026-09-09T00:00:00+00:00",
        }))
        sm2 = make_state_machine(self.proot)
        self.assertEqual(
            sm2.read_one("newspec").get("start_after"),
            "2026-09-09T00:00:00+00:00",
        )


# ── 最小 PMEngine/Dispatcher 夹具（dispatch 门控测试用） ───────────────

class _SilentLogger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


def make_min_dispatcher(pm, run_queue, entry_reader):
    """构建最小 Dispatcher 实例（绕过 __init__，不依赖 agent_runner）。"""
    from core.pm_engine import PMEngine
    from core.pm_engine.dispatch import Dispatcher

    pm.shutting_down = False
    pm.config = {}
    pm.logger = _SilentLogger()
    pm._get_config = lambda k, d=None: d
    pm._get_spec_priority = lambda n: 5
    pm._effective_priority = lambda base, enq, now: base
    pm._aging_bonus = lambda enq, now: 0
    pm._dispatch_backoffed = lambda spec: False
    pm._instant_fail_cooled = lambda n: False
    pm._is_fix_spec = lambda n: False
    pm._sibling_repair_active = lambda n, enqueued_at=None: None
    pm._check_impl_budget_exhausted = lambda n: False

    d = Dispatcher.__new__(Dispatcher)
    d._pm = pm
    pm._dispatcher_instance = d
    d._queue_lock = threading.Lock()
    d._run_queue = run_queue
    d._active_runs = 0
    d._active_priorities = set()
    d._active_priority_counts = {}
    # read_one 由调用方注入（entry_reader: spec_name -> entry dict）
    class _SM:
        def read_one(self, name):
            return entry_reader(name) or {}
        def transition(self, name, status):
            return True
    pm.state_machine = _SM()
    return d


class TestStartAfterDispatchGate(unittest.TestCase):
    """2.1/6.1 start_after 门控：未到期跳过不写 STATE、到期拾取、非法/过去等价无限制。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_spec_scheduling_project(Path(self.tmpdir))
        self.sm = make_state_machine(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _state_path(self) -> str:
        return (self.proot / ".fenix" / "STATE.md").read_text(encoding="utf-8")

    def test_scan_skips_pending_start_after_without_state_write(self):
        future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.sm.update_spec("myspec", {"start_after": future_iso})
        before = self._state_path()
        queue = [(5, "myspec", "implementer", 0.0)]
        called = []

        from core.pm_engine import PMEngine
        pm = PMEngine.__new__(PMEngine)
        pm._run_agent_worker = lambda *a, **k: called.append(a)
        d = make_min_dispatcher(pm, queue, lambda n: self.sm.read_all().get(n))
        d._process_queue()

        self.assertFalse(called, "未到期 spec 不得派发")
        self.assertEqual(len(d._run_queue), 1, "条目保持排队，不丢失")
        # 不写 STATE（状态/error 均无变化）
        self.assertEqual(self._state_path(), before, "跳过不得写 STATE")

    def test_scan_dispatches_matured_start_after(self):
        past_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.sm.update_spec("myspec", {"start_after": past_iso})
        queue = [(5, "myspec", "implementer", 0.0)]
        called = []

        from core.pm_engine import PMEngine
        pm = PMEngine.__new__(PMEngine)
        pm._run_agent_worker = lambda *a, **k: called.append(a)
        d = make_min_dispatcher(pm, queue, lambda n: self.sm.read_all().get(n))
        d._process_queue()

        self.assertEqual(called, [("myspec", "implementer", 5)],
                         "已到期的 start_after 不残留任何限制，正常派发")

    def test_invalid_and_missing_start_after_not_blocking(self):
        queue = [(5, "myspec", "implementer", 0.0)]
        called = []

        from core.pm_engine import PMEngine
        pm = PMEngine.__new__(PMEngine)
        pm._run_agent_worker = lambda *a, **k: called.append(a)
        d = make_min_dispatcher(pm, queue, lambda n: {
            "myspec": {"status": "ready", "start_after": "明天早上"},
        }.get(n))
        d._process_queue()
        self.assertEqual(len(called), 1, "非法 start_after 视作不阻塞")

    def test_on_spec_ready_gate_pending(self):
        from core.state_machine import StateMachine
        future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

        class _FakeAgentRunner:
            class _WM:
                def has_active_worktree(self, n): return False
            worktree_manager = _WM()
            def has_live_attempt(self, n): return False

        from core.pm_engine import PMEngine
        pm = PMEngine.__new__(PMEngine)
        sm = self.sm
        pm.state_machine = sm
        pm.agent_runner = _FakeAgentRunner()
        pm.logger = _SilentLogger()
        pm.shutting_down = False
        pm._pending_dispatches = set()
        # __new__ 绕过 __init__：补派发冷却登记（engine.py 派发冷却窗口依赖）
        pm._last_dispatch_at = {}
        pm._dispatch_backoffed = lambda spec: False
        pm._dependencies_satisfied = lambda n: True
        pm.project_root = self.proot
        pm._enqueue = lambda n, at: called.append((n, at))

        sm.update_spec("myspec", {"start_after": future_iso, "status": "ready"})
        called = []
        pm._on_spec_ready("myspec")
        self.assertEqual(called, [], "start_after 未到期时 _on_spec_ready 不得入队")

        # 到期后（过去时间等价无限制）→ 正常入队
        sm.update_spec("myspec", {"start_after": None})
        pm._on_spec_ready("myspec")
        self.assertEqual(called, [("myspec", "implementer")], "清除定时后立即恢复调度")


class TestCheckSchedulingDeadlines(unittest.TestCase):
    """2.3/6.2 定时解冻：到期自动解冻、幂等、重启扫描兜底、「定时解冻」来源标记。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_spec_scheduling_project(Path(self.tmpdir))
        # 时间轴「定时解冻」标记依赖 events 日志
        (self.proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
        self.sm = make_state_machine(self.proot)
        # 冻结 + 设置已过期的 frozen_until
        self.sm.freeze_spec("myspec", "人工确认")
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.sm.update_spec("myspec", {"frozen_until": past_iso})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_pm(self):
        from core.pm_engine import PMEngine
        pm = PMEngine.__new__(PMEngine)
        pm.state_machine = self.sm
        pm.project_root = self.proot
        pm.logger = _SilentLogger()
        pm._on_spec_ready = mock.Mock()
        pm._on_spec_drafted = mock.Mock()
        pm._pending_dispatches = set()
        return pm

    def test_auto_unfreeze_restores_orig_and_clears_residuals(self):
        pm = self._make_pm()
        result = pm.check_scheduling_deadlines()
        self.assertIn("myspec", result["unfrozen"])
        entry = self.sm.read_one("myspec")
        self.assertEqual(entry.get("status"), "ready", "恢复冻结前状态（原状态 ready）")
        self.assertFalse(entry.get("frozen"))
        self.assertIsNone(entry.get("error"))
        self.assertIsNone(entry.get("frozen_until"))

    def test_idempotent_second_call_noop(self):
        pm = self._make_pm()
        pm.check_scheduling_deadlines()
        result = pm.check_scheduling_deadlines()
        self.assertEqual(result["unfrozen"], [], "已解冻后再次扫描视为无需操作（幂等）")
        entry = self.sm.read_one("myspec")
        self.assertEqual(entry.get("status"), "ready")

    def test_daemon_restart_scan_fallback(self):
        # 模拟 daemon 重启：全新 StateMachine 实例（内存定时器丢失），
        # 周期扫描（check_scheduling_deadlines）仍能检测到到期的 frozen_until。
        sm2 = make_state_machine(self.proot)
        from core.pm_engine import PMEngine
        pm = PMEngine.__new__(PMEngine)
        pm.state_machine = sm2
        pm.project_root = self.proot
        pm.logger = _SilentLogger()
        pm._pending_dispatches = set()
        result = pm.check_scheduling_deadlines()
        self.assertIn("myspec", result["unfrozen"])
        self.assertEqual(sm2.read_one("myspec").get("status"), "ready")

    def test_timeline_records_scheduled_unfreeze_marker(self):
        pm = self._make_pm()
        pm.check_scheduling_deadlines()
        log_text = (self.proot / ".fenix" / "logs" / "fenixd.log").read_text(
            encoding="utf-8")
        self.assertIn("定时解冻", log_text, "事件流记录含「定时解冻」来源标记")
        self.assertIn("scheduled-unfreeze", log_text)
        # 项目日志（运维记录）同样可追溯
        project_log = (self.proot / ".fenix" / "PROJECT_LOG.md")
        self.assertTrue(project_log.exists())
        self.assertIn("定时解冻", project_log.read_text(encoding="utf-8"))

    def test_past_frozen_until_config_immediate_unfreeze(self):
        # 设置过去时间 → 立即解冻（等价到期），不等待 tick/扫描
        from core.dashboard.data import configure_spec_freeze
        past_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        r = configure_spec_freeze(self.proot, "myspec", "scheduled", until=past_iso)
        self.assertTrue(r.get("unfrozen"))
        entry = self.sm.read_one("myspec")
        self.assertEqual(entry.get("status"), "ready")
        self.assertIsNone(entry.get("frozen_until"))


class TestFreezeDualTrackRegression(unittest.TestCase):
    """1.2/6.3 冻结双轨回归：两条冻结→解冻路径 status 均正确恢复（半死态消除）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_spec_scheduling_project(Path(self.tmpdir))
        self.sm = make_state_machine(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unfreeze_restores_status_and_clears_residuals(self):
        """1.1/2.3 解冻双通道合一（原 TestStateMachineUnfreezeClearsResiduals +
        路径 A 合并）：SM.unfreeze_spec 与 dashboard unfreeze_spec（委托前者）
        均恢复 status 并清 error/frozen_until 残留（半死态消除）。

        背景：此前 update_spec 直写会因冻结保护剥离 status，残留
        「error 清空但 status 仍 blocked」半死态。
        """
        from core.dashboard.data import unfreeze_spec

        for channel, unfreeze in (
            ("sm", lambda: self.sm.unfreeze_spec("myspec", status="ready")),
            ("dashboard", lambda: unfreeze_spec(self.proot, "myspec")),
        ):
            with self.subTest(channel=channel):
                self.assertTrue(self.sm.freeze_spec("myspec", "原状态 ready"))
                self.assertTrue(self.sm.update_spec(
                    "myspec", {"frozen_until": "2026-09-08T01:00:00+00:00"}))
                entry = self.sm.read_one("myspec")
                self.assertTrue(entry.get("frozen"))
                self.assertEqual(entry.get("status"), "blocked")
                self.assertIsNotNone(entry.get("frozen_until"))

                self.assertTrue(unfreeze())
                entry = self.sm.read_one("myspec")
                self.assertEqual(entry.get("status"), "ready",
                                 "半死态消除：status 恢复原状态")
                self.assertFalse(entry.get("frozen"))
                self.assertIsNone(entry.get("error"))
                self.assertIsNone(entry.get("frozen_until"))

    def test_dashboard_freeze_then_sm_unfreeze_restores_status(self):
        # 路径 B：dashboard freeze_spec 冻结 → StateMachine.unfreeze_spec 解冻
        from core.dashboard.data import freeze_spec
        r = freeze_spec(self.proot, "myspec")
        self.assertTrue(r["ok"])
        entry = self.sm.read_one("myspec")
        self.assertEqual(entry.get("status"), "blocked")
        self.assertTrue(entry.get("frozen"), "dashboard 冻结须写结构化 frozen 标记，daemon 才能感知停止调度")
        self.assertTrue(entry.get("error", "").startswith("用户指令冻结："))
        self.assertIn("ready", entry.get("error", ""), "冻结 error 记录原状态")

        self.assertTrue(self.sm.unfreeze_spec("myspec", status="ready"))
        entry = self.sm.read_one("myspec")
        self.assertEqual(entry.get("status"), "ready")
        self.assertFalse(entry.get("frozen"))
        self.assertIsNone(entry.get("error"))

    def test_dashboard_freeze_sets_frozen_marker_for_daemon(self):
        # daemon 感知停止调度 = 读到 frozen 标记 / blocked+前缀 → _frozen_state 判定
        from core.dashboard.data import freeze_spec
        from core.pm_engine.engine import PMEngine
        freeze_spec(self.proot, "myspec")
        self.assertTrue(PMEngine._frozen_state(self.sm.read_one("myspec")),
                        "daemon 侧冻结态判定必须命中")

    def test_structured_freeze_marker_distinguishes_bare_blocked(self):
        """blocked 语义以结构化冻结为准（原 test_state_machine.TestBlockedState
        裸写 status=blocked 的写法并入为对照断言）：daemon 侧 _frozen_state
        只认 frozen 标记或 legacy 文本契约（blocked + 「用户指令冻结：」前缀），
        裸 blocked 不被感知为冻结，也就不会停止调度。"""
        from core.pm_engine.engine import PMEngine

        # 裸写 blocked（原 TestBlockedState 的写法）：无 frozen 标记、error 无前缀
        self.sm.update_spec("myspec", {"status": "blocked"})
        self.assertFalse(
            PMEngine._frozen_state(self.sm.read_one("myspec")),
            "裸写 blocked 不得被感知为冻结")

        # 结构化冻结：frozen=True + blocked + 冻结前缀 error（state_machine FROZEN_FIELD 契约）
        self.sm.update_spec("myspec", {
            "frozen": True,
            "status": "blocked",
            "error": "用户指令冻结：原状态 ready",
        })
        self.assertTrue(
            PMEngine._frozen_state(self.sm.read_one("myspec")),
            "结构化冻结必须命中冻结态判定")


class TestSchedulingKickSignal(unittest.TestCase):
    """清空 start_after 立即唤醒派发（文件信号，与 cancel_run_request 同构）。

    事故（2026-09-08）：dashboard 清空 start_after 后 status 恒为 ready，
    event_bus watcher 只盯 status 不发事件、check_scheduling_deadlines 只管
    「时间流逝到期」，最后靠 30min 一轮 recovery full_scan 才捞起——「清空=
    立即恢复调度」缺了即时唤醒。修复（API 侧）：set_spec_start_after 清空
    分支写 .fenix/scheduling_kick_request.json，daemon 主循环（1s 粒度）拾取
    后 _on_spec_ready + _process_queue。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_spec_scheduling_project(Path(self.tmpdir))
        self.sm = make_state_machine(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 写入侧（dashboard data 层）──

    def test_clear_start_after_writes_kick_signal(self):
        from core.dashboard.data import set_spec_start_after
        self.sm.update_spec("myspec", {
            "start_after": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        })
        result = set_spec_start_after(self.proot, "myspec", None)
        self.assertTrue(result["ok"])
        req = self.proot / ".fenix" / "scheduling_kick_request.json"
        self.assertTrue(req.exists(), "清空 start_after 必须写唤醒信号")
        payload = json.loads(req.read_text(encoding="utf-8"))
        self.assertEqual(payload["spec"], "myspec")
        self.assertEqual(payload["action"], "clear-start-after")

    def test_clear_start_after_conflict_keeps_existing_signal(self):
        from core.dashboard.data import set_spec_start_after
        req = self.proot / ".fenix" / "scheduling_kick_request.json"
        req.write_text(json.dumps({"spec": "other"}), encoding="utf-8")
        result = set_spec_start_after(self.proot, "myspec", None)
        self.assertTrue(result["ok"], "信号冲突不阻塞清空本身（STATE 已写）")
        payload = json.loads(req.read_text(encoding="utf-8"))
        self.assertEqual(payload["spec"], "other", "已有未消费信号不被覆盖")

    def test_set_start_after_no_kick_signal(self):
        from core.dashboard.data import set_spec_start_after
        result = set_spec_start_after(
            self.proot, "myspec",
            (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        )
        self.assertTrue(result["ok"])
        self.assertFalse(
            (self.proot / ".fenix" / "scheduling_kick_request.json").exists(),
            "设置定时不需要唤醒（到期唤起走 check_scheduling_deadlines）")

    # ── 拾取侧（daemon 主循环）──
    #
    # 按绝对路径直载 fenixd.py（tests/test_config.py 同款处方）：仓库根
    # __init__.py 会在测试执行期把 `import fenixd` 截胡成同名包（sys.path
    # 顺序随收集/执行阶段漂移），函数内延迟 import 不稳定，故不使用。

    @classmethod
    def setUpClass(cls):
        import importlib.util
        repo_root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "fenixd_scheduling_kick_under_test", repo_root / "fenixd.py")
        cls._fenixd_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls._fenixd_mod)

    def _fake_daemon(self, pm):
        daemon = self._fenixd_mod.FenixDaemon.__new__(self._fenixd_mod.FenixDaemon)
        daemon.running = True
        daemon.pm_engine = pm
        daemon.logger = _SilentLogger()
        return daemon

    def _make_pm(self):
        from core.pm_engine import PMEngine
        pm = PMEngine.__new__(PMEngine)
        pm.state_machine = self.sm
        pm.logger = _SilentLogger()
        pm.project_root = self.proot
        pm._pending_dispatches = set()
        pm._last_dispatch_at = {}
        pm._dispatch_backoffed = lambda spec: False
        pm._dependencies_satisfied = lambda n: True
        pm.shutting_down = False
        return pm

    def test_kick_request_pickup_invokes_on_spec_ready(self):
        from core.state_machine import SpecStatus
        self.sm.update_spec("myspec", {"status": SpecStatus.READY})
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        processed = []
        pm._process_queue = lambda: processed.append(True)
        daemon = self._fake_daemon(pm)
        req = self.proot / ".fenix" / "scheduling_kick_request.json"
        req.write_text(json.dumps({"spec": "myspec", "action": "clear-start-after"}),
                       encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, ["myspec"], "拾取信号后必须唤起 _on_spec_ready")
        self.assertEqual(processed, [True], "唤起后必须立即 _process_queue")
        self.assertFalse(req.exists(), "信号消费后删除")

    def test_kick_request_unknown_spec_dropped(self):
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        daemon = self._fake_daemon(pm)
        req = self.proot / ".fenix" / "scheduling_kick_request.json"
        req.write_text(json.dumps({"spec": "ghost"}), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, [], "不存在的 spec 不派发")
        self.assertFalse(req.exists(), "信号仍删除防反复报错")

    def test_kick_request_corrupt_deleted_without_exception(self):
        pm = self._make_pm()
        daemon = self._fake_daemon(pm)
        req = self.proot / ".fenix" / "scheduling_kick_request.json"
        req.write_text("{ not valid json !!!", encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertFalse(req.exists())
        pm._on_spec_ready.assert_not_called() if hasattr(pm._on_spec_ready, "assert_not_called") else None

    def test_kick_request_drafts_spec_promotes(self):
        """drafted spec 清空定时 → 走晋升链（_on_spec_drafted），与到期拾取同语义。"""
        from core.state_machine import SpecStatus
        self.sm.update_spec("myspec", {"status": SpecStatus.DRAFTED})
        pm = self._make_pm()
        calls = []
        pm._on_spec_drafted = lambda n: calls.append(n)
        pm._process_queue = lambda: None
        daemon = self._fake_daemon(pm)
        req = self.proot / ".fenix" / "scheduling_kick_request.json"
        req.write_text(json.dumps({"spec": "myspec"}), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, ["myspec"], "drafted spec 拾取走晋升链")


if __name__ == "__main__":
    unittest.main()