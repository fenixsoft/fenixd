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
import os
import shutil
import sys
import tempfile
import threading
import time
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

    def test_start_after_manual_sentinel_always_pending(self):
        # add-spec-manual-activation D1：哨兵 manual = 永不到期（等价「永远 pending」）。
        # 远期 now 亦真，验证不依赖时间。
        entry = {"start_after": "manual"}
        self.assertTrue(self.start_after_pending(entry, datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)))
        self.assertTrue(self.start_after_pending(entry, datetime(2036, 1, 1, 0, 0, tzinfo=timezone.utc)))

    def test_start_after_manual_case_variants(self):
        # 大小写不敏感 + strip 容错人工手改 STATE.md
        for variant in ("Manual", "MANUAL", " manual "):
            self.assertTrue(
                self.start_after_pending({"start_after": variant}, None),
                f"variant {variant!r} should be pending",
            )

    def test_start_after_manual_prefix_like_not_misjudged(self):
        # 前缀相似但非哨兵 → 回退 parse_utc fail-open → False（非法值不阻塞）
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        self.assertFalse(self.start_after_pending({"start_after": "manual-x"}, now))
        self.assertFalse(self.start_after_pending({"start_after": "manuel"}, now))

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
    # add-spec-content-integrity-gate 接入 dispatch 后同层新增的派发前闸门：
    # 本替身不设 pm.project_root，漏桩即 AttributeError（bb9de76c 起 4.1/4.3
    # 两例红灯）——调度门控测试只验 start_after，内容维度按「有内容」放行。
    pm._check_spec_content_missing = lambda n: False

    d = Dispatcher.__new__(Dispatcher)
    d._pm = pm
    pm._dispatcher_instance = d
    # fix-spec-review-blocking-dispatch：与生产同用可重入锁——_process_queue
    # 持锁期间 _should_defer_for_reviewer → is_review_in_flight 会再取同一把
    # 锁（engine.py:3516），非可重入 Lock 同线程二次 acquire 死锁。
    d._queue_lock = threading.RLock()
    d._run_queue = run_queue
    d._active_runs = 0
    d._active_priorities = set()
    d._active_priority_counts = {}
    # fix-spec-review-blocking-dispatch 1.1：评审在飞集合（__new__ 绕过 __init__，
    # 须手动补生产 __init__ 里初始化的字段，否则 is_review_in_flight 读不到）。
    d._active_reviews = set()
    # read_one 由调用方注入（entry_reader: spec_name -> entry dict）
    class _SM:
        def read_one(self, name):
            return entry_reader(name) or {}
        def transition(self, name, status,
                       *, trigger_run_id=None, agent_type=None, channel="auto"):
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
        # __new__ 绕过 __init__：补单飞守卫锁（_on_spec_ready 的「检查+登记」原子化依赖）
        pm._dispatch_guard_lock = threading.Lock()
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
        req = self.proot / ".fenix" / "scheduling_kick" / "myspec.json"
        self.assertTrue(req.exists(), "清空 start_after 必须写唤醒信号（新目录形态）")
        payload = json.loads(req.read_text(encoding="utf-8"))
        self.assertEqual(payload["spec"], "myspec")
        self.assertEqual(payload["action"], "clear-start-after")
        # 返回值如实回报信号写入结果（D3）
        self.assertEqual(result["scheduling_kick"], {"ok": True, "error": None})

    def test_clear_start_after_multi_spec_no_conflict(self):
        """连续清空两个 SPEC：两个信号文件并存，无冲突丢弃（fix-scheduling-kick-single-slot）。"""
        from core.dashboard.data import set_spec_start_after
        # 添加一个额外的非终态 spec（donespec 是终态 done，set_spec_start_after 会拒绝）
        self.sm.add_spec("extra", {"priority": 3, "status": "ready", "depends_on": None})
        self.sm.update_spec("myspec", {"start_after": "2026-09-30T00:00:00+00:00"})
        self.sm.update_spec("extra", {"start_after": "2026-09-30T00:00:00+00:00"})
        r1 = set_spec_start_after(self.proot, "myspec", None)
        r2 = set_spec_start_after(self.proot, "extra", None)
        self.assertTrue(r1["ok"] and r2["ok"], "两个清空都必须成功（原事故形态：第二个被静默丢弃）")
        kdir = self.proot / ".fenix" / "scheduling_kick"
        files = sorted(p.name for p in kdir.glob("*.json"))
        self.assertEqual(files, ["extra.json", "myspec.json"], "两 SPEC 信号文件并存")
        # 同一 SPEC 重复清空幂等覆盖（不增文件数）
        set_spec_start_after(self.proot, "myspec", None)
        files = sorted(p.name for p in kdir.glob("*.json"))
        self.assertEqual(files, ["extra.json", "myspec.json"])

    def test_set_start_after_no_kick_signal(self):
        from core.dashboard.data import set_spec_start_after
        result = set_spec_start_after(
            self.proot, "myspec",
            (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["scheduling_kick"], None, "设置定时不写唤醒信号（字段为 null）")
        self.assertFalse(
            (self.proot / ".fenix" / "scheduling_kick" / "myspec.json").exists(),
            "设置定时不需要唤醒（到期唤起走 check_scheduling_deadlines）")

    # ── 拾取侧（daemon 主循环）──
    #
    # 按绝对路径直载 fenixd.py（tests/test_config.py 同款处方）：以独立模块名
    # `fenixd_scheduling_kick_under_test` 加载，不注册进 `sys.modules['fenixd']`，
    # 与全量回归中其他测试的 fenixd 导入互不串扰（模块隔离）。

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
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "myspec.json").write_text(
            json.dumps({"spec": "myspec", "action": "clear-start-after",
                        "created": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, ["myspec"], "拾取信号后必须唤起 _on_spec_ready")
        self.assertEqual(processed, [True], "唤起后必须立即 _process_queue")
        self.assertFalse((kdir / "myspec.json").exists(), "信号消费后删除")

    def test_kick_request_unknown_spec_dropped(self):
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        daemon = self._fake_daemon(pm)
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "ghost.json").write_text(
            json.dumps({"spec": "ghost", "created": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, [], "不存在的 spec 不派发")
        self.assertFalse((kdir / "ghost.json").exists(), "信号仍删除防反复报错")

    def test_kick_request_corrupt_deleted_without_exception(self):
        pm = self._make_pm()
        daemon = self._fake_daemon(pm)
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "corrupt.json").write_text("{ not valid json !!!", encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertFalse((kdir / "corrupt.json").exists())
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
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "myspec.json").write_text(
            json.dumps({"spec": "myspec", "created": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, ["myspec"], "drafted spec 拾取走晋升链")

    def test_kick_request_multi_dir_entries_same_round(self):
        """同轮多信号逐条消费、互不干扰（fix-scheduling-kick-single-slot 目录形态）。"""
        from core.state_machine import SpecStatus
        self.sm.update_spec("myspec", {"status": SpecStatus.READY})
        self.sm.update_spec("donespec", {"status": SpecStatus.READY})
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        pm._process_queue = lambda: None
        daemon = self._fake_daemon(pm)
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        for name in ("myspec", "donespec"):
            (kdir / f"{name}.json").write_text(
                json.dumps({"spec": name, "created": now}), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(sorted(calls), ["donespec", "myspec"], "两信号同轮消费")
        self.assertEqual(list(kdir.glob("*.json")), [], "全部消费后删除")

    def test_kick_request_single_exception_not_blocking_others(self):
        """单条信号唤起异常不中断同轮其余信号（task 4.2）。"""
        from core.state_machine import SpecStatus
        self.sm.update_spec("myspec", {"status": SpecStatus.READY})
        self.sm.update_spec("donespec", {"status": SpecStatus.READY})
        pm = self._make_pm()
        calls = []
        def boom(spec):
            if spec == "donespec":
                raise RuntimeError("boom")
            calls.append(spec)
        pm._on_spec_ready = boom
        pm._process_queue = lambda: None
        daemon = self._fake_daemon(pm)
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        for name in ("myspec", "donespec"):
            (kdir / f"{name}.json").write_text(
                json.dumps({"spec": name, "created": now}), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, ["myspec"], "异常 spec 不影响其它信号")
        # 异常者信号保留留待下轮（先唤起后删）；myspec 已消费删除
        self.assertTrue((kdir / "donespec.json").exists(), "唤起异常的信号保留留待下轮重试")
        self.assertFalse((kdir / "myspec.json").exists())

    def test_kick_request_legacy_single_file_consumed(self):
        """旧单文件路径兼容消费（D5）：阈值内旧文件按既有语义消费并删除。"""
        from core.state_machine import SpecStatus
        self.sm.update_spec("myspec", {"status": SpecStatus.READY})
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        pm._process_queue = lambda: None
        daemon = self._fake_daemon(pm)
        legacy = self.proot / ".fenix" / "scheduling_kick_request.json"
        legacy.write_text(json.dumps({
            "spec": "myspec", "action": "clear-start-after",
            "created": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, ["myspec"], "旧单文件信号仍被消费")
        self.assertFalse(legacy.exists(), "旧文件消费后删除")

    def test_kick_request_legacy_stale_only_removed(self):
        """旧单文件超阈值（D4）：仅删除不唤起（防 daemon 长期停机后的病态派发）。"""
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        daemon = self._fake_daemon(pm)
        legacy = self.proot / ".fenix" / "scheduling_kick_request.json"
        stale = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        legacy.write_text(json.dumps({"spec": "myspec", "created": stale}), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertEqual(calls, [], "陈旧旧文件 MUST NOT 唤起")
        self.assertFalse(legacy.exists(), "陈旧旧文件仅删除")

    def test_kick_request_non_json_residue_not_deleted(self):
        """目录内非 .json 残留（写入中断临时文件）消费扫描不得删除（task 4.1/6.8）。"""
        pm = self._make_pm()
        daemon = self._fake_daemon(pm)
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        residue = kdir / "myspec.json.tmp.12345"
        residue.write_text("partial", encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._check_scheduling_kick_requests()
        self.assertTrue(residue.exists(), "消费扫描不得删除非 .json 残留")
        # 陈旧回收终将其清走（mtime 超阈值）
        os.utime(residue, (time.time() - 7200, time.time() - 7200))
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._reclaim_stale_scheduling_kicks()
        self.assertFalse(residue.exists(), "陈旧回收清走非 .json 残留")

    # ── 陈旧回收（task 6.5/6.7：_reclaim_stale_scheduling_kicks 分档）──

    def _write_kick(self, name, created_ts, kdir=None):
        kdir = kdir or self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        p = kdir / f"{name}.json"
        p.write_text(json.dumps({"spec": name, "created": created_ts}), encoding="utf-8")
        return p

    def test_reclaim_stale_only_deletes(self):
        """created 超阈值条目仅删不唤起（task 6.5）。"""
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        daemon = self._fake_daemon(pm)
        stale = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        self._write_kick("myspec", stale)
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._reclaim_stale_scheduling_kicks()
        self.assertEqual(calls, [], "陈旧条目 MUST NOT 唤起")
        self.assertFalse(
            (self.proot / ".fenix" / "scheduling_kick" / "myspec.json").exists(),
            "陈旧条目仅删除")

    def test_reclaim_fresh_kick_then_delete(self):
        """阈值内条目先消费（唤起）再删除（task 6.5）。"""
        from core.state_machine import SpecStatus
        self.sm.update_spec("myspec", {"status": SpecStatus.READY})
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        pm._process_queue = lambda: None
        daemon = self._fake_daemon(pm)
        self._write_kick("myspec", datetime.now(timezone.utc).isoformat())
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._reclaim_stale_scheduling_kicks()
        self.assertEqual(calls, ["myspec"], "阈值内条目被唤起（先消费）")
        self.assertFalse(
            (self.proot / ".fenix" / "scheduling_kick" / "myspec.json").exists(),
            "消费后删除")

    def test_reclaim_missing_created_only_deletes(self):
        """created 缺失条目仅删（task 6.5）。"""
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        daemon = self._fake_daemon(pm)
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "myspec.json").write_text(json.dumps({"spec": "myspec"}), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._reclaim_stale_scheduling_kicks()
        self.assertEqual(calls, [], "created 缺失按陈旧处理（仅删）")
        self.assertFalse((kdir / "myspec.json").exists())

    def test_reclaim_legacy_file_stale_only_deletes(self):
        """陈旧回收对旧单文件路径同样生效（task 6.7）：超阈值 → 仅删不唤起。"""
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        daemon = self._fake_daemon(pm)
        legacy = self.proot / ".fenix" / "scheduling_kick_request.json"
        stale = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        legacy.write_text(json.dumps({"spec": "myspec", "created": stale}), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._reclaim_stale_scheduling_kicks()
        self.assertEqual(calls, [], "陈旧旧文件 MUST NOT 唤起")
        self.assertFalse(legacy.exists(), "陈旧旧文件仅删除")

    def test_reclaim_legacy_file_fresh_consumed(self):
        """陈旧回收对旧单文件路径同样生效（task 6.7）：阈值内 → 先消费后删除。"""
        from core.state_machine import SpecStatus
        self.sm.update_spec("myspec", {"status": SpecStatus.READY})
        pm = self._make_pm()
        calls = []
        pm._on_spec_ready = lambda n: calls.append(n)
        pm._process_queue = lambda: None
        daemon = self._fake_daemon(pm)
        legacy = self.proot / ".fenix" / "scheduling_kick_request.json"
        legacy.write_text(json.dumps({
            "spec": "myspec", "created": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._reclaim_stale_scheduling_kicks()
        self.assertEqual(calls, ["myspec"], "阈值内旧文件被唤起")
        self.assertFalse(legacy.exists(), "旧文件消费后删除")

    def test_reclaim_corrupt_deleted(self):
        """对账中损坏 JSON 删除防卡死（task 4.3 同判据）。"""
        pm = self._make_pm()
        daemon = self._fake_daemon(pm)
        kdir = self.proot / ".fenix" / "scheduling_kick"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "corrupt.json").write_text("{ bad", encoding="utf-8")
        with mock.patch.object(self._fenixd_mod, "PROJECT_ROOT", self.proot):
            daemon._reclaim_stale_scheduling_kicks()
        self.assertFalse((kdir / "corrupt.json").exists())


class TestManualActivation(unittest.TestCase):
    """add-spec-manual-activation 10.1：哨兵 manual 全链行为。

    覆盖：
    - 谓词：manual 恒 pending（不依赖时间）、大小写/空白变体、前缀相似不误判；
    - 持久化：set_spec_start_after('manual') 经 STATE.md 往返后
      get_spec_start_after 返回 "manual"（哨兵不被折叠为 None）；
    - 激活动作：activate_spec 置 null + 写 scheduling_kick 信号；
    - 调度门控：manual 的 spec 经 queue/_on_spec_ready 均不被拾取；
    - check_scheduling_deadlines 多轮调用不唤起（D3，不误判到期）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = make_spec_scheduling_project(Path(self.tmpdir))
        self.sm = make_state_machine(self.proot)
        (self.proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 谓词层（对齐 1.3 用例） ──

    def test_sentinel_always_pending(self):
        from core.state_machine import start_after_pending
        entry = {"start_after": "manual"}
        self.assertTrue(start_after_pending(entry, datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)))
        # 远期 now 亦真：验证不依赖时间
        self.assertTrue(start_after_pending(entry, datetime(2036, 1, 1, 0, 0, tzinfo=timezone.utc)))

    def test_sentinel_case_and_whitespace_variants(self):
        from core.state_machine import start_after_pending
        for variant in ("Manual", "MANUAL", " manual ", "  Manual  "):
            self.assertTrue(
                start_after_pending({"start_after": variant}, None),
                f"variant {variant!r} should be pending",
            )

    def test_prefix_like_not_misjudged(self):
        from core.state_machine import start_after_pending
        now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
        # 前缀相似但非哨兵 → 回退 parse_utc fail-open → False（非法值不阻塞）
        self.assertFalse(start_after_pending({"start_after": "manual-x"}, now))
        self.assertFalse(start_after_pending({"start_after": "manuel"}, now))

    # ── 持久化与读侧 ──

    def test_set_manual_roundtrip_not_collapsed(self):
        from core.dashboard.data import get_spec_start_after, set_spec_start_after
        result = set_spec_start_after(self.proot, "myspec", "manual")
        self.assertTrue(result["ok"])
        self.assertEqual(result["start_after"], "manual")
        # 经 STATE.md 往返后 get_spec_start_after 返回 "manual"（不被折叠为 None）
        entry = self.sm.read_one("myspec")
        self.assertEqual(entry.get("start_after"), "manual")
        self.assertEqual(get_spec_start_after(entry), "manual")
        # 设为待激活不写 kick 信号（这是暂停调度，不是恢复调度）
        self.assertFalse(
            (self.proot / ".fenix" / "scheduling_kick" / "myspec.json").exists(),
            "设为待激活不写 kick 信号",
        )

    def test_set_manual_case_insensitive(self):
        from core.dashboard.data import get_spec_start_after, set_spec_start_after
        result = set_spec_start_after(self.proot, "myspec", "MANUAL")
        self.assertTrue(result["ok"])
        self.assertEqual(get_spec_start_after(self.sm.read_one("myspec")), "manual")

    # ── 激活动作 ──

    def test_activate_spec_clears_and_wakes(self):
        from core.dashboard.data import activate_spec, get_spec_start_after
        self.sm.update_spec("myspec", {"start_after": "manual"})
        result = activate_spec(self.proot, "myspec")
        self.assertTrue(result["ok"])
        self.assertTrue(result["found"])
        self.assertEqual(result["start_after"], None)
        self.assertEqual(result["scheduling_kick"], {"ok": True, "error": None})
        entry = self.sm.read_one("myspec")
        self.assertIsNone(entry.get("start_after"))
        self.assertIsNone(get_spec_start_after(entry))
        req = self.proot / ".fenix" / "scheduling_kick" / "myspec.json"
        self.assertTrue(req.exists(), "激活动作必须写唤醒信号（新目录形态）")
        payload = json.loads(req.read_text(encoding="utf-8"))
        self.assertEqual(payload["spec"], "myspec")

    def test_activate_spec_not_manual_rejected(self):
        from core.dashboard.data import activate_spec
        self.sm.update_spec("myspec", {"start_after": None})
        result = activate_spec(self.proot, "myspec")
        self.assertFalse(result["ok"])
        self.assertTrue(result["found"])
        self.assertIn("并非待激活态", result.get("reason", ""))
        # STATE 零变更
        self.assertIsNone(self.sm.read_one("myspec").get("start_after"))

    def test_activate_spec_unknown_spec(self):
        from core.dashboard.data import activate_spec
        result = activate_spec(self.proot, "nosuch")
        self.assertFalse(result["ok"])
        self.assertFalse(result["found"])

    # ── 调度门控（D2：全派发入口经 start_after_pending 单点覆盖） ──

    def test_manual_not_dispatched_by_queue(self):
        from core.pm_engine import PMEngine
        self.sm.update_spec("myspec", {"start_after": "manual"})
        queue = [(5, "myspec", "implementer", 0.0)]
        called = []
        pm = PMEngine.__new__(PMEngine)
        pm._run_agent_worker = lambda *a, **k: called.append(a)
        d = make_min_dispatcher(pm, queue, lambda n: self.sm.read_all().get(n))
        d._process_queue()
        self.assertFalse(called, "哨兵 manual 的 spec 不得派发（静默跳过）")
        self.assertEqual(len(d._run_queue), 1, "条目保持排队，不丢失")

    def test_manual_not_dispatched_by_on_spec_ready(self):
        from core.pm_engine import PMEngine
        self.sm.update_spec("myspec", {"start_after": "manual", "status": "ready"})
        called = []

        class _FakeAgentRunner:
            class _WM:
                def has_active_worktree(self, n): return False
            worktree_manager = _WM()
            def has_live_attempt(self, n): return False

        pm = PMEngine.__new__(PMEngine)
        pm.state_machine = self.sm
        pm.agent_runner = _FakeAgentRunner()
        pm.logger = _SilentLogger()
        pm.shutting_down = False
        pm._pending_dispatches = set()
        pm._dispatch_guard_lock = threading.Lock()  # __new__ 绕过 __init__：补单飞守卫锁
        pm._last_dispatch_at = {}
        pm._dispatch_backoffed = lambda spec: False
        pm._dependencies_satisfied = lambda n: True
        pm.project_root = self.proot
        pm._enqueue = lambda n, at: called.append((n, at))
        pm._on_spec_ready("myspec")
        self.assertEqual(called, [], "manual 未激活时 _on_spec_ready 不得入队")
        # 激活（清哨兵）后立即入队
        self.sm.update_spec("myspec", {"start_after": None})
        pm._on_spec_ready("myspec")
        self.assertEqual(called, [("myspec", "implementer")], "激活后立即恢复调度")

    # ── check_scheduling_deadlines 不误判哨兵到期（D3） ──

    def test_deadlines_never_wake_manual(self):
        from core.pm_engine import PMEngine
        self.sm.update_spec("myspec", {"start_after": "manual"})
        pm = PMEngine.__new__(PMEngine)
        pm.state_machine = self.sm
        pm.project_root = self.proot
        pm.logger = _SilentLogger()
        pm._on_spec_ready = mock.Mock()
        pm._on_spec_drafted = mock.Mock()
        pm._pending_dispatches = set()
        for _ in range(3):
            result = pm.check_scheduling_deadlines()
            self.assertEqual(result["signaled"], [], "manual 不得被到期检测唤起")
        pm._on_spec_ready.assert_not_called()
        pm._on_spec_drafted.assert_not_called()
        self.assertEqual(self.sm.read_one("myspec").get("start_after"), "manual")


if __name__ == "__main__":
    unittest.main()