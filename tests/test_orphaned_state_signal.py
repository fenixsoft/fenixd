"""orphaned-state-signal — 状态无驱动探测与恢复（add-control-plane-silent-failure-guards 防线四）。

对应 spec/changes/add-control-plane-silent-failure-guards/specs/orphaned-state-signal/
的 R1-R4 与 验收标准：

- 状态悬置（>短阈值）+ 无 run + 无进程 + 无待派发 → orphaned_state 信号；
- 长 run 在跑 / 存活子进程 / 有意等待（_cancelled_hold / backoff / start_after）
  → 不误报；
- event_bus._recover_one 对无驱动 testing 有恢复出口（重触发 verifier，复用
  implemented 分支防重入守卫）；
- 节流生效（冷却窗内只唤起一次）；
- 回归（4.5）：事故场景（复位失败致 spec 悬置 testing 无 verifier）在分钟级
  阈值内被 orphaned_state 捕获，早于 stuck（160 分钟）。
"""

import json
import threading
import time
from pathlib import Path
from unittest import mock

from core.admin_monitor import (
    ORPHANED_RUN_GRACE_SECONDS,
    _has_recent_spec_run,
    inprocess_verify_active,
    spec_is_undriven,
)
from core.pm_engine.dispatch.queue import agent_worker_thread_name
from tests.helpers import FakeLogger, iso_ago


def _sm(specs: dict):
    class FakeSM:
        def __init__(self, specs):
            self._specs = specs

        def read_all(self):
            return self._specs

        def read_one(self, name):
            return self._specs.get(name)

        def update_spec(self, name, updates):
            if name in self._specs:
                self._specs[name].update(updates)
            return True

        def transition_gate(self, name, new_status,
                            *, trigger_run_id=None, agent_type=None, channel="auto"):
            self.update_spec(name, {"status": new_status})
            return True

        def transition(self, name, new_status,
                       *, trigger_run_id=None, agent_type=None, channel="auto"):
            if (self._specs.get(name) or {}).get("status") in (
                    "implementing",
            ) and new_status == "ready":
                self.update_spec(name, {"status": new_status})
                return True
            return True
    return FakeSM(specs)


def _make_monitor(tmp_path, specs, runner=None):
    from core.admin_store import AdminStore
    from core.admin_monitor import AdminMonitor
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    mon = AdminMonitor(
        {}, _sm(specs), proot, FakeLogger(),
        store=AdminStore(proot, FakeLogger()),
        agent_runner=runner,
    )
    return proot, mon


class _Runner:
    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        return mock.MagicMock(
            run_id="admin-orphan-1", spec=signal.get("spec"), success=True,
            problem=signal.get("description", ""), actions_taken="测试处置",
            result="resolved", summary="已复位", escalate=False,
            recommended_action="", family_waiver=False,
        )


def _write_run(proot: Path, run_id: str, mtime=None):
    runs = proot / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f"{run_id}.jsonl"
    p.write_text(json.dumps({"type": "system", "subtype": "init"}) + "\n",
                 encoding="utf-8")
    if mtime is not None:
        os_utime(proot, p, mtime)
    return p


def os_utime(_proot, p, mtime):
    import os
    os.utime(p, (mtime, mtime))


class TestDetectOrphanedState:

    def _detect(self, tmp_path, specs, runs=None, pgrep=False, now=None):
        proot, mon = _make_monitor(tmp_path, specs)
        if runs:
            for run_id, mtime in runs.items():
                _write_run(proot, run_id, mtime)
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=pgrep):
            return mon._detect_orphaned_state(specs, now or time.time())

    def test_suspended_undriven_produces_signal(self, tmp_path):
        """状态悬置 + 无 run + 无进程 → orphaned_state 信号。"""
        specs = {"demo": {"status": "testing",
                          "updated": iso_ago(20), "branch": "fenix/x"}}
        signals = self._detect(tmp_path, specs)
        assert len(signals) == 1
        assert signals[0]["signal_type"] == "orphaned_state"
        assert signals[0]["spec"] == "demo"
        assert signals[0]["severity"] == "major"

    def test_implementing_also_detected(self, tmp_path):
        specs = {"demo": {"status": "implementing",
                          "updated": iso_ago(20), "branch": "fenix/x"}}
        signals = self._detect(tmp_path, specs)
        assert [s["signal_type"] for s in signals] == ["orphaned_state"]

    def test_short_elapsed_not_detected(self, tmp_path):
        """未超短阈值（<15 分钟）→ 不产生。"""
        specs = {"demo": {"status": "testing", "updated": iso_ago(5)}}
        assert self._detect(tmp_path, specs) == []

    def test_long_running_run_suppresses(self, tmp_path):
        """长 run 在跑（run 文件 mtime 在宽限窗内）→ 不误报。"""
        specs = {"demo": {"status": "testing", "updated": iso_ago(20)}}
        signals = self._detect(tmp_path, specs,
                               runs={"verify-demo-1700000001": time.time()})
        assert signals == []

    def test_live_process_suppresses(self, tmp_path):
        """存活 agent 子进程 → 不误报。"""
        specs = {"demo": {"status": "testing", "updated": iso_ago(20)}}
        assert self._detect(tmp_path, specs, pgrep=True) == []

    def test_frozen_suppresses(self, tmp_path):
        """人工冻结是有意等待 → 不误报（与 blocked_stuck 同豁免）。"""
        specs = {"demo": {"status": "testing", "updated": iso_ago(20),
                          "frozen": True}}
        assert self._detect(tmp_path, specs) == []

    def test_cancelled_hold_suppresses(self, tmp_path):
        """_cancelled_hold 有意等待 → 不误报。"""
        specs = {"demo": {"status": "testing", "updated": iso_ago(20),
                          "_cancelled_hold": True}}
        assert self._detect(tmp_path, specs) == []

    def test_start_after_suppresses(self, tmp_path):
        """start_after 定时未到（有意等待拾取）→ 不误报。"""
        specs = {"demo": {"status": "testing", "updated": iso_ago(20),
                          "start_after": iso_ago(-30)}}
        assert self._detect(tmp_path, specs) == []

    def test_dispatch_backoff_suppresses(self, tmp_path):
        """派发退避未到期（_dispatch_backoff_until 在未来）→ 不误报。"""
        specs = {"demo": {"status": "testing", "updated": iso_ago(20),
                          "_dispatch_backoff_until": str(time.time() + 600)}}
        assert self._detect(tmp_path, specs) == []

    def test_not_in_progress_status_ignored(self, tmp_path):
        """非 implementing/testing 状态不参与。"""
        specs = {"demo": {"status": "ready", "updated": iso_ago(20)}}
        assert self._detect(tmp_path, specs) == []


class TestOrphanedHandoffToStuck:
    """与 stuck 的交接（hand-off）：orphaned 只覆盖短阈值到 stuck 阈值窗口。
    超 stuck 阈值（160 分钟）后由既有 stuck 检测接管，避免双信号双唤起。"""

    def test_early_window_captured_by_orphaned(self, tmp_path):
        """事故回归（4.5）：20 分钟无驱动 → orphaned_state 捕获，stuck 未触发。"""
        specs = {"demo": {"status": "testing", "updated": iso_ago(20)}}
        proot, mon = _make_monitor(tmp_path, specs)
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            signals = mon._detect(specs, time.time())
        types = [s["signal_type"] for s in signals]
        assert "orphaned_state" in types
        assert "stuck" not in types  # stuck 需 ~160 分钟，远未到达

    def test_long_elapsed_handed_to_stuck(self, tmp_path):
        """200 分钟悬置 → 只 stuck 触发，orphaned 让位（防双唤起）。"""
        specs = {"demo": {"status": "implementing", "updated": iso_ago(200)}}
        proot, mon = _make_monitor(tmp_path, specs)
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            signals = mon._detect(specs, time.time())
        types = [s["signal_type"] for s in signals]
        assert "stuck" in types
        assert "orphaned_state" not in types


class TestOrphanedThrottle:
    """R4 节流：冷却窗内同 spec 同类信号只唤起一次。"""

    def test_cooldown_deduplicates_invocation(self, tmp_path):
        specs = {"demo": {"status": "testing", "updated": iso_ago(20)}}
        runner = _Runner()
        proot, mon = _make_monitor(tmp_path, specs, runner=runner)
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            mon.run_once()
            mon.run_once()
        invoked = [c for c in runner.calls
                   if c.get("signal_type") == "orphaned_state"]
        assert len(invoked) == 1, f"冷却窗内应只唤起 1 次，实际 {len(invoked)}"


class TestTestingRecovery:
    """R3 恢复出口：event_bus._recover_one 对无驱动 testing 不再静默留白。"""

    def _bus(self, proot, entry):
        from core.event_bus import EventBus
        bus = EventBus.__new__(EventBus)
        recorded = []

        class _PM:
            project_root = proot

            def handle_event(self, event_kind, spec_name, spec_entry):
                recorded.append((event_kind, spec_name))

        bus.pm_engine = _PM()
        bus.logger = FakeLogger()
        return bus, recorded

    def test_undriven_testing_retriggers_verify(self, tmp_path):
        """无驱动 testing → recovery 重触发 spec_implemented（verifier 重新入队）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        entry = {"status": "testing", "updated": iso_ago(20)}
        bus, recorded = self._bus(proot, entry)
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            bus._recover_testing("demo", entry)
        assert recorded == [("spec_implemented", "demo")]

    def test_driven_testing_not_retriggered(self, tmp_path):
        """有活动 run（verifier 在跑）→ 不重触发（防重验风暴）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        _write_run(proot, "verify-demo-1700000001", time.time())
        entry = {"status": "testing", "updated": iso_ago(20)}
        bus, recorded = self._bus(proot, entry)
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            bus._recover_testing("demo", entry)
        assert recorded == []

    def test_paused_testing_not_retriggered(self, tmp_path):
        """_inconclusive_attempts>0（暂停自动重验）→ 不重触发。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        entry = {"status": "testing", "updated": iso_ago(20),
                 "_inconclusive_attempts": 2}
        bus, recorded = self._bus(proot, entry)
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            bus._recover_testing("demo", entry)
        assert recorded == []

    def test_queued_testing_not_retriggered(self, tmp_path):
        """verifier 条目已在派发队列（等并发槽）→ 不重触发（2026-09-18 修复）。

        实证：本 SPEC 'fix-verify-serving-disk-reclaim' 07:55 入队后，08:07 与
        08:30 两轮本出口各重触发一次 spec_implemented，而条目一直在队列——重派
        被 `_enqueue` 去重吸收，只是刷日志。条件 ④ 后不再重触发。
        """
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        entry = {"status": "testing", "updated": iso_ago(20)}
        bus, recorded = self._bus(proot, entry)
        bus.pm_engine._queued_for_dispatch = lambda name: name == "demo"
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            bus._recover_testing("demo", entry)
        assert recorded == []


def _live_verifier_thread(spec: str):
    """造一个名为 fenix-verifier-<spec> 的活线程（Event 阻塞，测试终了回收）。

    线程名取自命名单点 agent_worker_thread_name（与 queue.py Thread 构造同源
    ——命名漂移时本装置与判定同步失效，测试可抓）。
    """
    started = threading.Event()
    stop = threading.Event()

    def _run():
        started.set()
        stop.wait(10)

    t = threading.Thread(
        target=_run, name=agent_worker_thread_name(spec, "verifier"),
        daemon=True,
    )
    return t, started, stop


class TestInprocessVerifyActive:
    """条件⑤ helper（evo-inprocess-verify-activity-signal 1.1/2.1/2.2）：
    in-process 验证活性 = 线程探测（主，零时间窗）OR 进度 mtime 独立窗口（辅）。

    线程名取自命名单点 agent_worker_thread_name（与 queue.py Thread 构造同源），
    进度文件 mtime 两态用 os.utime 造。
    """

    def _write_progress(self, proot: Path, spec: str, mtime=None) -> Path:
        d = proot / ".fenix" / "verify-progress"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{spec}.json"
        p.write_text(json.dumps({"total": 1, "done": 0, "current": "x"}),
                     encoding="utf-8")
        if mtime is not None:
            os_utime(proot, p, mtime)
        return p

    # ── 2.1 线程两态 ────────────────────────────────────────────

    def test_live_thread_means_driven(self, tmp_path):
        """存在活 verifier 线程 → helper True，spec_is_undriven 判有驱动。"""
        spec = "demo-live-thread"
        t, started, stop = _live_verifier_thread(spec)
        t.start()
        assert started.wait(10)
        try:
            assert inprocess_verify_active(tmp_path, spec) is True
            with mock.patch("core.admin_monitor._pgrep_live_worktree",
                            return_value=False):
                assert spec_is_undriven(tmp_path, spec,
                                        {"status": "testing"}) is False
        finally:
            stop.set()
            t.join(10)

    def test_thread_exited_matches_legacy_four_conditions(self, tmp_path):
        """线程退出后判定与现状四条件口径完全一致（无新增豁免）。"""
        spec = "demo-dead-thread"
        # 同名线程已结束（join 回收）→ 线程臂不豁免
        t, started, stop = _live_verifier_thread(spec)
        t.start()
        started.wait(10)
        stop.set()
        t.join(10)
        assert inprocess_verify_active(tmp_path, spec) is False
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            assert spec_is_undriven(tmp_path, spec,
                                    {"status": "testing"}) is True

    # ── 2.2 进度 mtime 两态与窗口边界 ───────────────────────────

    def test_fresh_progress_mtime_exempted(self, tmp_path):
        """进度文件 mtime 新鲜（线程不在）→ 豁免（辅证臂独立成立）。"""
        spec = "demo-mtime-fresh"
        self._write_progress(tmp_path, spec, time.time())
        assert inprocess_verify_active(tmp_path, spec) is True

    def test_stale_progress_beyond_window_not_exempted(self, tmp_path):
        """mtime 超独立窗口（900s）→ 不豁免，spec_is_undriven 判无驱动。"""
        spec = "demo-mtime-stale"
        self._write_progress(tmp_path, spec, time.time() - 901)
        assert inprocess_verify_active(tmp_path, spec) is False
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            assert spec_is_undriven(tmp_path, spec,
                                    {"status": "testing"}) is True

    def test_missing_progress_file_not_exempted(self, tmp_path):
        """文件缺失 → 不豁免（线程也不在）。"""
        assert inprocess_verify_active(tmp_path, "demo-missing") is False

    def test_explicit_window_boundary(self, tmp_path):
        """window_seconds 参数化边界：窗口内 True / 超窗 False。"""
        spec = "demo-mtime-window"
        self._write_progress(tmp_path, spec, time.time() - 130)
        assert inprocess_verify_active(tmp_path, spec,
                                       window_seconds=120) is False
        assert inprocess_verify_active(tmp_path, spec,
                                       window_seconds=200) is True

    def test_batch_gap_beyond_120s_grace_still_exempted(self, tmp_path):
        """对照（关键约束）：mtime 距今 300s——超出条件①的 120s run 宽限
        （单场景长批间隔实测 4-5 分钟），但落独立窗口 900s 内 → 条件⑤豁免。
        独立窗口 MUST NOT 沿用 120s 宽限，否则「正在长跑」被误判停滞。"""
        spec = "demo-batch-gap"
        self._write_progress(tmp_path, spec, time.time() - 300)
        # 对照①：同 mtime 在 120s run 宽限下判「无活动 run 文件」
        assert _has_recent_spec_run(
            tmp_path, spec, time.time(), ORPHANED_RUN_GRACE_SECONDS) is False
        # 条件⑤独立窗口判「有驱动」
        assert inprocess_verify_active(tmp_path, spec) is True
        with mock.patch("core.admin_monitor._pgrep_live_worktree",
                        return_value=False):
            assert spec_is_undriven(tmp_path, spec,
                                    {"status": "testing"}) is False

    def test_thread_probe_wins_over_stale_mtime(self, tmp_path):
        """线程探测为主判据：线程活、mtime 停滞（超窗）→ 仍豁免（零时间窗）。"""
        spec = "demo-thread-long-scene"
        self._write_progress(tmp_path, spec, time.time() - 3600)
        t, started, stop = _live_verifier_thread(spec)
        t.start()
        assert started.wait(10)
        try:
            assert inprocess_verify_active(tmp_path, spec) is True
        finally:
            stop.set()
            t.join(10)


class TestOrphanedResetAfterDisposition:
    """R3 复位直通道：Administrator 处置成功（resolved）后框架自动复位。"""

    def test_testing_reset_reenqueues_verifier(self, tmp_path):
        """testing 孤儿 → transition_gate(testing) 幂等 + verifier 入队重验。"""
        proot, mon = _make_monitor(tmp_path, {})
        sm = _sm({"demo": {"status": "testing", "updated": iso_ago(20)}})
        mon.state_machine = sm
        enqueued = []

        class _PM:
            def handle_event(self, event_kind, spec_name, spec_entry):
                enqueued.append((event_kind, spec_name))

        mon.pm_engine = _PM()
        signal = {"signal_type": "orphaned_state", "spec": "demo"}
        mon._reset_orphaned_after_disposition(signal)
        assert enqueued == [("spec_implemented", "demo")]
        assert sm.read_one("demo")["status"] == "testing"

    def test_implementing_reset_to_ready(self, tmp_path):
        """implementing 孤儿 → transition(ready) 重实现。"""
        proot, mon = _make_monitor(tmp_path, {})
        sm = _sm({"demo": {"status": "implementing", "updated": iso_ago(20)}})
        mon.state_machine = sm
        enqueued = []

        class _PM:
            def handle_event(self, event_kind, spec_name, spec_entry):
                enqueued.append((event_kind, spec_name))

        mon.pm_engine = _PM()
        signal = {"signal_type": "orphaned_state", "spec": "demo"}
        mon._reset_orphaned_after_disposition(signal)
        assert enqueued == []
        assert sm.read_one("demo")["status"] == "ready"

    # ── 2.3 在飞验证复核（evo-inprocess-verify-activity-signal 1.3）────

    @staticmethod
    def _reset_setup(proot, spec):
        sm = _sm({spec: {"status": "testing", "updated": iso_ago(20),
                         "error": "orphaned"}})
        transitions = []
        orig_gate = sm.transition_gate

        def _counting_gate(name, new_status, **kw):
            transitions.append((name, new_status))
            return orig_gate(name, new_status, **kw)

        sm.transition_gate = _counting_gate
        enqueued = []

        class _PM:
            def handle_event(self, event_kind, spec_name, spec_entry):
                enqueued.append((event_kind, spec_name))

        return sm, transitions, _PM(), enqueued

    def test_testing_reset_skips_reenqueue_while_verify_inflight(self, tmp_path):
        """verifier 线程活跃 → 跳过 handle_event 重派（第三放大器出口堵口），
        复位语义保留：transition_gate 幂等 + 清 error 照常，无重复 transition。"""
        spec = "demo-inflight-verify"
        proot, mon = _make_monitor(tmp_path, {})
        sm, transitions, pm, enqueued = self._reset_setup(proot, spec)
        mon.state_machine = sm
        mon.pm_engine = pm
        t, started, stop = _live_verifier_thread(spec)
        t.start()
        assert started.wait(10)
        try:
            mon._reset_orphaned_after_disposition(
                {"signal_type": "orphaned_state", "spec": spec})
            assert enqueued == []  # 跳过重派，无重复批
            assert transitions == [(spec, "testing")]  # 无重复 transition
            assert sm.read_one(spec)["status"] == "testing"  # 复位语义保留
            assert sm.read_one(spec)["error"] is None  # 清 error 照常
        finally:
            stop.set()
            t.join(10)

    def test_testing_reset_reenqueues_when_no_verify_inflight(self, tmp_path):
        """无在飞验证 → 复位重派照常入队（transition + handle_event 各一次）。"""
        spec = "demo-no-verify"
        proot, mon = _make_monitor(tmp_path, {})
        sm, transitions, pm, enqueued = self._reset_setup(proot, spec)
        mon.state_machine = sm
        mon.pm_engine = pm
        mon._reset_orphaned_after_disposition(
            {"signal_type": "orphaned_state", "spec": spec})
        assert enqueued == [("spec_implemented", spec)]
        assert transitions == [(spec, "testing")]
        assert sm.read_one(spec)["error"] is None