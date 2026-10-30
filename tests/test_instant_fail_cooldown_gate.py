"""Tests for evo-add-instant-fail-cooldown-full-lane-gate.

秒挂冷却全车道门控与到期复诵：
- 1.1/1.2/3.1 门控面扩展：planner-plan/verifier 入闸（不 pop、不耗预算、INFO
  留痕）、到期自动重入调度、implementer/fast-track/repair 不回归；
- 1.3/3.1 admin spec 作用域门控与 spec=null 全局放行；
- 2.1/2.2/3.2 到期复诵：窗内新失败翻倍且冷却起点重置、严格大于判定、翻倍
  3 次/2400s 封顶、窗内零新失败清零恢复、INFO 续冷却留痕、指纹记账；
- 2.3 恢复定时器判重放宽：截止时刻变化即按新截止重排（cancel 旧 Timer），
  截止未变化保持幂等早退（信号死法通道同款参数化）。
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore
from core.pm_engine import PMEngine
from core.pm_engine.dispatch import Dispatcher
from core.state_machine import StateMachine

from tests.helpers import FakeLogger, make_runner


class RecordingLogger:
    """记录型 logger（info/debug/warning/error 分桶，供留痕断言）。"""

    def __init__(self):
        self.infos = []
        self.debugs = []
        self.warnings = []
        self.errors = []

    def info(self, *args):
        self.infos.append(args)

    def debug(self, *args):
        self.debugs.append(args)

    def warning(self, *args):
        self.warnings.append(args)

    def error(self, *args):
        self.errors.append(args)

    def info_texts(self):
        return [" ".join(str(a) for a in args) for args in self.infos]


def _make_gate_runner(tmp_path, now=1000.0, overrides=None):
    """构造时间可控的最小 AgentRunner（冷却阈值缩小便于断言）。"""
    runner = make_runner(tmp_path)
    cfg = {
        "agents.instant_fail_cooldown_after": 2,
        "agents.instant_fail_cooldown_seconds": 100,
    }
    if overrides:
        cfg.update(overrides)
    runner._get_config = lambda key, default=None: cfg.get(key, default)
    holder = {"now": float(now)}
    runner._now = lambda: holder["now"]
    return runner, holder


def _make_engine_dispatcher(tmp_path, runner, logger):
    """真实 PMEngine + Dispatcher 装配（闸门链全真，仅重排程与在飞评审打桩）。"""
    fenix = Path(tmp_path) / ".fenix"
    fenix.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(fenix / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), {}, Path(tmp_path), logger)
    engine.agent_runner = runner
    engine._should_defer_for_reviewer = lambda spec, sname: False
    dispatcher = Dispatcher(engine)
    scheduled = []
    dispatcher._schedule_instant_fail_recovery = (
        lambda sname, lock_held=False: scheduled.append(sname)
    )
    return engine, dispatcher, scheduled


def _enter_cooldown(runner, holder, spec="spec-a", at=1000.0):
    """两次秒挂（cooldown_after=2）→ 进入冷却 [at, at+100]。"""
    holder["now"] = float(at)
    runner._record_instant_fail(spec, 5.0)
    runner._record_instant_fail(spec, 5.0)
    assert runner.is_instant_fail_cooldown(spec) is True
    return runner._instant_fail[spec]


# ═══════════════════════════════════════════════════════════════════════════
# 1.1/1.2/3.1 门控面扩展
# ═══════════════════════════════════════════════════════════════════════════


class TestGateSurfaceQueue:
    """秒挂闸门覆盖 planner-plan/verifier；既有车道不回归；INFO 留痕。"""

    def _setup(self, tmp_path):
        logger = RecordingLogger()
        runner, holder = _make_gate_runner(tmp_path)
        engine, dispatcher, scheduled = _make_engine_dispatcher(
            tmp_path, runner, logger)
        _enter_cooldown(runner, holder)
        return runner, holder, engine, dispatcher, scheduled, logger

    def test_planner_plan_skipped_not_popped(self, tmp_path):
        """冷却生效时 planner-plan 派发被跳过：状态原封（不 pop）、排程恢复、
        INFO 留痕含 spec 名与车道。"""
        runner, holder, engine, dispatcher, scheduled, logger = self._setup(tmp_path)
        until_before = runner.instant_fail_cooldown_until("spec-a")
        spec = {"name": "spec-a", "status": "ready", "priority": 5}
        assert dispatcher._queue_entry_ready(spec, "spec-a", "planner-plan") is False
        # 既有队列语义：不 pop、不耗预算——冷却态原封不动
        assert runner.instant_fail_cooldown_until("spec-a") == until_before
        assert runner._instant_fail_counts("spec-a") == 2
        assert scheduled == ["spec-a"]
        infos = [t for t in logger.info_texts()
                 if "spec-a" in t and "planner-plan" in t]
        assert infos and "秒挂冷却" in infos[0] and "剩余" in infos[0]
        # 旧口径是 DEBUG：新留痕 MUST NOT 只出现在 debug 桶
        assert not any("秒挂冷却" in " ".join(str(a) for a in d)
                       for d in logger.debugs)

    def test_verifier_skipped_with_info(self, tmp_path):
        """冷却生效时 verifier 派发被跳过并留 INFO 留痕（验证链冷却到期恢复）。"""
        runner, holder, engine, dispatcher, scheduled, logger = self._setup(tmp_path)
        spec = {"name": "spec-a", "status": "implemented", "priority": 5}
        assert dispatcher._queue_entry_ready(spec, "spec-a", "verifier") is False
        assert runner._instant_fail_counts("spec-a") == 2
        assert scheduled == ["spec-a"]
        infos = [t for t in logger.info_texts()
                 if "spec-a" in t and "verifier" in t]
        assert infos and "剩余" in infos[0]

    def test_expired_auto_reenters_dispatch(self, tmp_path):
        """冷却到期（窗内零新失败）→ 闸门放行，自动重入调度且计数清零。"""
        runner, holder, engine, dispatcher, scheduled, logger = self._setup(tmp_path)
        holder["now"] = runner.instant_fail_cooldown_until("spec-a") + 1.0
        spec = {"name": "spec-a", "status": "implemented", "priority": 5}
        assert dispatcher._queue_entry_ready(spec, "spec-a", "verifier") is True
        assert runner._instant_fail_counts("spec-a") == 0
        spec_impl = {"name": "spec-a", "status": "ready", "priority": 5}
        assert dispatcher._queue_entry_ready(spec_impl, "spec-a", "planner-plan") is True

    def test_implementer_fast_track_still_gated(self, tmp_path):
        """implementer/fast-track 既有过闸行为不回归（仍跳过 + INFO）。"""
        runner, holder, engine, dispatcher, scheduled, logger = self._setup(tmp_path)
        spec = {"name": "spec-a", "status": "ready", "priority": 5}
        assert dispatcher._queue_entry_ready(spec, "spec-a", "implementer") is False
        assert dispatcher._queue_entry_ready(spec, "spec-a", "fast-track") is False
        assert runner._instant_fail_counts("spec-a") == 2
        assert any("implementer" in t and "秒挂冷却" in t
                   for t in logger.info_texts())

    def test_non_cooled_spec_dispatchable_all_lanes(self, tmp_path):
        """未冷却 spec 各车道照常放行（门控不误伤）。"""
        runner, holder, engine, dispatcher, scheduled, logger = self._setup(tmp_path)
        ready = {"name": "spec-b", "status": "ready", "priority": 5}
        implemented = {"name": "spec-b", "status": "implemented", "priority": 5}
        assert dispatcher._queue_entry_ready(ready, "spec-b", "implementer") is True
        assert dispatcher._queue_entry_ready(ready, "spec-b", "planner-plan") is True
        assert dispatcher._queue_entry_ready(implemented, "spec-b", "verifier") is True

    def test_repair_lane_predicate_unchanged(self, tmp_path):
        """repair 车道（不经队列、直查 _instant_fail_cooled）判定不回归。"""
        runner, holder, engine, dispatcher, scheduled, logger = self._setup(tmp_path)
        assert engine._instant_fail_cooled("spec-a") is True
        assert engine._instant_fail_cooled("spec-b") is False


# ═══════════════════════════════════════════════════════════════════════════
# 1.3/3.1 admin spec 作用域门控
# ═══════════════════════════════════════════════════════════════════════════


class TestAdminGate:
    """管理员仅 spec 作用域纳管；daemon_errors 全局信号（spec=null）放行。"""

    def _monitor(self, tmp_path, runner, logger=None):
        logger = logger or RecordingLogger()
        proot = Path(tmp_path) / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        mon = AdminMonitor(
            {}, None, proot, logger,
            store=AdminStore(proot, logger),
            agent_runner=runner,
        )
        return mon, logger

    def test_spec_scoped_invoke_skipped_with_info(self, tmp_path):
        """spec 作用域处置唤起被门控：_invoke_administrator 返回 False（未派发）
        并留 INFO（spec 名、剩余冷却秒数）。"""
        logger = RecordingLogger()
        runner, holder = _make_gate_runner(tmp_path)
        _enter_cooldown(runner, holder)
        mon, logger = self._monitor(tmp_path, runner, logger)
        signal = {
            "signal_type": "stuck",
            "spec": "spec-a",
            "severity": "major",
            "description": "困境",
            "evidence": "evidence",
            "recommended_action": "检查",
        }
        assert mon._invoke_administrator(signal, None) is False
        infos = [t for t in logger.info_texts()
                 if "spec-a" in t and "秒挂冷却" in t]
        assert infos and "剩余" in infos[0]

    def test_global_signal_gate_no_ops(self, tmp_path):
        """spec=null 全局信号：门控恒放行，且不触发 runner 判定（自救通道不被
        任一 spec 的冷却拦截）。"""
        runner = MagicMock()
        runner.is_instant_fail_cooldown = MagicMock(return_value=True)
        mon, _ = self._monitor(tmp_path, runner)
        assert mon._instant_fail_gate(None) == (False, 0)
        assert mon._instant_fail_gate("") == (False, 0)
        runner.is_instant_fail_cooldown.assert_not_called()

    def test_spec_scoped_gate_reports_remaining(self, tmp_path):
        """spec 作用域判定命中时返回剩余冷却秒数（INFO 留痕素材）。"""
        runner = MagicMock()
        runner.is_instant_fail_cooldown = MagicMock(return_value=True)
        runner.instant_fail_cooldown_until = MagicMock(
            return_value=time.monotonic() + 123.0)
        mon, _ = self._monitor(tmp_path, runner)
        cooled, remaining = mon._instant_fail_gate("spec-a")
        assert cooled is True
        assert 120 <= remaining <= 123
        runner.is_instant_fail_cooldown.assert_called_once_with("spec-a")

    def test_runner_unavailable_fails_open(self, tmp_path):
        """runner 不可用/判定异常 fail-open 放行（与 engine 同构）。"""
        mon, _ = self._monitor(tmp_path, None)
        assert mon._instant_fail_gate("spec-a") == (False, 0)
        runner = MagicMock()
        runner.is_instant_fail_cooldown = MagicMock(
            side_effect=RuntimeError("boom"))
        mon2, _ = self._monitor(tmp_path, runner)
        assert mon2._instant_fail_gate("spec-a") == (False, 0)


# ═══════════════════════════════════════════════════════════════════════════
# 2.1/2.2/3.2 到期复诵与冷却翻倍
# ═══════════════════════════════════════════════════════════════════════════


class TestReciteDoubling:
    """到期先复诵后消费：窗内新失败翻倍、严格大于判定、封顶、清零恢复。"""

    def test_entry_records_new_state_fields(self, tmp_path):
        """2.1：进入冷却增记冷却起点/当前时长/翻倍次数/末次失败/指纹字段。"""
        runner, holder = _make_gate_runner(tmp_path)
        st = _enter_cooldown(runner, holder, at=1000.0)
        assert st["cooldown_started_at"] == 1000.0
        assert st["cooldown_seconds"] == 100.0
        assert st["doublings"] == 0
        assert st["last_fail_at"] == 1000.0
        assert st["count"] == 2
        assert st["cooldown_until"] == 1100.0

    def test_record_during_window_rewrites_until_only(self, tmp_path):
        """窗内新失败沿用既有续写语义（重写截止），但不动起点/时长/翻倍次数
        ——翻倍算术的基准不被失败续写重置。"""
        runner, holder = _make_gate_runner(tmp_path)
        st = _enter_cooldown(runner, holder, at=1000.0)
        holder["now"] = 1050.0
        runner._record_instant_fail("spec-a", 5.0)
        assert st["cooldown_until"] == 1150.0  # 1050 + base 100（既有续写）
        assert st["cooldown_started_at"] == 1000.0
        assert st["cooldown_seconds"] == 100.0
        assert st["doublings"] == 0
        assert st["last_fail_at"] == 1050.0

    def test_recite_doubles_and_reschedules_deadline(self, tmp_path):
        """2.2：窗内有新失败 → 到期不清零，翻倍 ×2 续写截止、起点重置。"""
        runner, holder = _make_gate_runner(tmp_path)
        st = _enter_cooldown(runner, holder, at=1000.0)
        holder["now"] = 1050.0
        runner._record_instant_fail("spec-a", 5.0)
        holder["now"] = 1150.0
        assert runner.is_instant_fail_cooldown("spec-a") is True  # 复诵：1050 > 1000
        assert st["doublings"] == 1
        assert st["cooldown_seconds"] == 200.0
        assert st["cooldown_until"] == 1350.0
        assert st["cooldown_started_at"] == 1150.0
        assert runner.instant_fail_cooldown_until("spec-a") == 1350.0

    def test_trigger_batch_does_not_self_recite(self, tmp_path):
        """严格大于：引发本次冷却的失败批次与起点同刻，到期不复诵、正常清零。"""
        runner, holder = _make_gate_runner(tmp_path)
        _enter_cooldown(runner, holder, at=1000.0)
        holder["now"] = 1100.0
        assert runner.is_instant_fail_cooldown("spec-a") is False
        assert runner._instant_fail_counts("spec-a") == 0

    def test_zero_new_failures_recovers(self, tmp_path):
        """窗内零新失败 → 到期清零恢复，行为与现网到期恢复一致。"""
        runner, holder = _make_gate_runner(tmp_path)
        _enter_cooldown(runner, holder, at=1000.0)
        holder["now"] = 1100.5
        assert runner.is_instant_fail_cooldown("spec-a") is False
        assert "spec-a" not in runner._instant_fail

    def test_doubling_capped_at_three(self, tmp_path):
        """翻倍上限 3 次：第 4 次复诵不再递增时长，按当前时长继续冷却。"""
        runner, holder = _make_gate_runner(tmp_path)
        st = _enter_cooldown(runner, holder, at=1000.0)
        # 三轮「窗内新失败 → 到期复诵」：100 → 200 → 400 → 800
        for fail_at, expire_at in ((1050.0, 1150.0), (1250.0, 1350.0),
                                   (1550.0, 1650.0)):
            holder["now"] = fail_at
            runner._record_instant_fail("spec-a", 5.0)
            holder["now"] = expire_at
            assert runner.is_instant_fail_cooldown("spec-a") is True
        assert st["doublings"] == 3
        assert st["cooldown_seconds"] == 800.0
        # 第 4 次复诵：翻倍次数不再递增，时长保持 800
        holder["now"] = 2000.0
        runner._record_instant_fail("spec-a", 5.0)
        holder["now"] = 2100.0
        assert runner.is_instant_fail_cooldown("spec-a") is True
        assert st["doublings"] == 3
        assert st["cooldown_seconds"] == 800.0

    def test_duration_capped_at_2400(self, tmp_path):
        """单次冷却封顶 2400s：×2 超 2400 即按 2400 续写。"""
        runner, holder = _make_gate_runner(
            tmp_path, overrides={"agents.instant_fail_cooldown_seconds": 1300})
        st = _enter_cooldown(runner, holder, at=1000.0)
        assert st["cooldown_seconds"] == 1300.0
        holder["now"] = 2000.0
        runner._record_instant_fail("spec-a", 5.0)
        holder["now"] = 3300.0
        assert runner.is_instant_fail_cooldown("spec-a") is True
        assert st["doublings"] == 1
        assert st["cooldown_seconds"] == 2400.0  # min(1300×2, 2400)
        until_capped = st["cooldown_until"]
        # 已达封顶：后续复诵按 2400 继续冷却，不再递增
        holder["now"] = until_capped - 700.0
        runner._record_instant_fail("spec-a", 5.0)
        holder["now"] = until_capped
        assert runner.is_instant_fail_cooldown("spec-a") is True
        assert st["cooldown_seconds"] == 2400.0

    def test_recite_info_log(self, tmp_path):
        """续冷却留痕可断言：INFO 含 spec 名、剩余秒数、翻倍进度。"""
        logger = RecordingLogger()
        runner, holder = _make_gate_runner(tmp_path)
        runner.logger = logger
        _enter_cooldown(runner, holder, at=1000.0)
        holder["now"] = 1050.0
        runner._record_instant_fail("spec-a", 5.0)
        holder["now"] = 1150.0
        assert runner.is_instant_fail_cooldown("spec-a") is True
        infos = [t for t in logger.info_texts()
                 if "spec-a" in t and "复诵" in t]
        assert infos and "剩 200s" in infos[0] and "1/3" in infos[0]

    def test_fingerprint_recorded_and_normalized(self, tmp_path):
        """2.1：指纹对路径/端口/run id 归一化——同骨架不同数字同指纹；
        空错误原文无指纹。"""
        runner, holder = _make_gate_runner(tmp_path)
        runner._record_instant_fail(
            "s1", 5.0,
            error="conn failed /tmp/fenix/wt-run-1791953098 port 8080 refused")
        fp1 = runner._instant_fail["s1"]["fingerprint"]
        assert fp1
        runner._record_instant_fail(
            "s2", 5.0,
            error="conn failed /tmp/fenix/wt-run-1791953999 port 9090 refused")
        fp2 = runner._instant_fail["s2"]["fingerprint"]
        assert fp1 == fp2
        # 不同骨架 → 不同指纹
        runner._record_instant_fail("s3", 5.0, error="quota exceeded (429)")
        assert runner._instant_fail["s3"]["fingerprint"] != fp1
        # 空原文 → 空指纹（缺失不阻塞恢复）
        runner._record_instant_fail("s4", 5.0)
        assert runner._instant_fail["s4"]["fingerprint"] == ""


# ═══════════════════════════════════════════════════════════════════════════
# 2.3 恢复定时器判重放宽（截止时刻变化即重排）
# ═══════════════════════════════════════════════════════════════════════════


class TestRecoveryTimerReschedule:
    """共用排程器：接入截止对账通道后「截止变化即重排、未变幂等早退」。"""

    def _schedule(self, dispatcher, spec, deadlines, timers, table, handles,
                  fired):
        dispatcher._schedule_recovery_timer(
            spec,
            timers=timers,
            resolve_delay=lambda s: max(0.5, deadlines[s] - time.monotonic()),
            min_delay=0.5,
            callback=lambda s: fired.append(s),
            resolve_deadline=lambda s: deadlines[s],
            deadline_table=table,
            handle_table=handles,
        )

    def test_reschedules_on_deadline_change(self, tmp_path):
        fenix = Path(tmp_path) / ".fenix"
        fenix.mkdir(parents=True, exist_ok=True)
        logger = RecordingLogger()
        engine = PMEngine(
            StateMachine(fenix / "STATE.md", logger), MagicMock(), {},
            Path(tmp_path), logger)
        dispatcher = Dispatcher(engine)
        deadlines = {"s": time.monotonic() + 300.0}
        fired = []
        timers = dispatcher._instant_fail_timers
        table = dispatcher._instant_fail_timer_deadlines
        handles = dispatcher._instant_fail_timer_handles

        self._schedule(dispatcher, "s", deadlines, timers, table, handles, fired)
        assert "s" in timers
        assert table["s"] == deadlines["s"]
        first = handles["s"]
        assert first.is_alive()

        # 截止未变化 → 幂等早退（不重排、不换句柄）
        self._schedule(dispatcher, "s", deadlines, timers, table, handles, fired)
        assert handles["s"] is first

        # 截止变化（复诵翻倍续写）→ cancel 旧 Timer、按新截止重排
        deadlines["s"] = time.monotonic() + 900.0
        self._schedule(dispatcher, "s", deadlines, timers, table, handles, fired)
        assert handles["s"] is not first
        assert table["s"] == deadlines["s"]
        assert first.finished.is_set()  # 旧定时器已取消，不再按旧截止触发
        assert "s" in timers

    def test_signal_kill_channel_same_relaxation(self, tmp_path):
        """信号死法通道同款参数化：截止未变幂等早退，续写后按新截止重排。"""
        fenix = Path(tmp_path) / ".fenix"
        fenix.mkdir(parents=True, exist_ok=True)
        logger = RecordingLogger()
        engine = PMEngine(
            StateMachine(fenix / "STATE.md", logger), MagicMock(), {},
            Path(tmp_path), logger)
        dispatcher = Dispatcher(engine)
        deadlines = {"s": time.monotonic() + 300.0}
        fired = []
        timers = dispatcher._signal_kill_timers
        table = dispatcher._signal_kill_timer_deadlines
        handles = dispatcher._signal_kill_timer_handles

        self._schedule(dispatcher, "s", deadlines, timers, table, handles, fired)
        first = handles["s"]
        self._schedule(dispatcher, "s", deadlines, timers, table, handles, fired)
        assert handles["s"] is first
        deadlines["s"] = time.monotonic() + 600.0
        self._schedule(dispatcher, "s", deadlines, timers, table, handles, fired)
        assert handles["s"] is not first
        assert table["s"] == deadlines["s"]
        assert first.finished.is_set()

    def test_transient_channel_keeps_pure_idempotence(self, tmp_path):
        """未接入截止对账的通道（瞬断/infra-retry）保持既有幂等早退语义。"""
        fenix = Path(tmp_path) / ".fenix"
        fenix.mkdir(parents=True, exist_ok=True)
        logger = RecordingLogger()
        engine = PMEngine(
            StateMachine(fenix / "STATE.md", logger), MagicMock(), {},
            Path(tmp_path), logger)
        dispatcher = Dispatcher(engine)
        fired = []
        dispatcher._schedule_recovery_timer(
            "s",
            timers=dispatcher._transient_timers,
            resolve_delay=lambda s: 600.0,
            min_delay=10.0,
            callback=lambda s: fired.append(s),
        )
        assert "s" in dispatcher._transient_timers
        dispatcher._schedule_recovery_timer(
            "s",
            timers=dispatcher._transient_timers,
            resolve_delay=lambda s: 600.0,
            min_delay=10.0,
            callback=lambda s: fired.append(s),
        )
        # 仍只有一个判重登记（无截止通道下第二个调用幂等早退）
        assert list(dispatcher._transient_timers) == ["s"]

    def test_cleared_deadline_zero_keeps_old_timer(self, tmp_path):
        """通道截止被清除（resolve_deadline 返回 0.0 而非 None）时幂等早退：
        旧定时器不被取消也不重排（对齐真实冷却通道未冷却恒返 0.0 的表示）。"""
        fenix = Path(tmp_path) / ".fenix"
        fenix.mkdir(parents=True, exist_ok=True)
        logger = RecordingLogger()
        engine = PMEngine(
            StateMachine(fenix / "STATE.md", logger), MagicMock(), {},
            Path(tmp_path), logger)
        dispatcher = Dispatcher(engine)
        deadlines = {"s": time.monotonic() + 300.0}
        fired = []
        timers = dispatcher._instant_fail_timers
        table = dispatcher._instant_fail_timer_deadlines
        handles = dispatcher._instant_fail_timer_handles

        self._schedule(dispatcher, "s", deadlines, timers, table, handles, fired)
        first = handles["s"]
        assert "s" in timers
        assert table["s"] == deadlines["s"]
        old_deadline = deadlines["s"]

        # 冷却截止被清除（如 runner._finalize_success 摘除条目）：真实通道
        # resolve_deadline 未冷却时恒返 0.0、resolve_delay 因 until<=0 返 None
        # → 须视为「截止已解除」幂等早退，旧定时器保留到期自会重入派发链。
        deadlines["s"] = 0.0
        dispatcher._schedule_recovery_timer(
            "s",
            timers=timers,
            resolve_delay=lambda s: (
                max(0.5, deadlines[s] - time.monotonic())
                if deadlines[s] > 0 else None
            ),
            min_delay=0.5,
            callback=lambda s: fired.append(s),
            resolve_deadline=lambda s: deadlines[s],
            deadline_table=table,
            handle_table=handles,
        )
        assert handles["s"] is first          # 旧定时器句柄未被替换
        assert first.is_alive()               # 未被 cancel
        assert list(timers) == ["s"]          # 判重标记保留，未重排新定时器
        assert table["s"] == old_deadline     # deadline_table 保留旧正截止


# ═══════════════════════════════════════════════════════════════════════════
# evo-instant-fail-storm-alert-closeout 1.2/2.2/3.2：秒挂死亡取证与写入点埋点
# ═══════════════════════════════════════════════════════════════════════════


class TestInstantFailForensics:
    """秒挂死亡取证快照（启动 stderr 尾部 + worktree 状态）与写入点埋点。

    - 1.2 写入点 attach_trigger 埋点：新告警携带 terminal-only 收口条件；
    - 2.2 取证快照：随风暴告警 evidence 留痕、有界、失败路径不阻断计数。
    """

    def _storm_alerts(self, tmp_path):
        store = AdminStore(Path(tmp_path), RecordingLogger())
        return [r for r in store.read_all()
                if r.get("signal_type") == "instant_fail_storm"]

    def test_write_point_attaches_terminal_trigger(self, tmp_path):
        """1.2：写入点 attach_trigger 埋点 → 新告警携带终态收口条件。"""
        runner, holder = _make_gate_runner(tmp_path)
        _enter_cooldown(runner, holder)
        alerts = self._storm_alerts(tmp_path)
        assert len(alerts) == 1
        trigger = alerts[0].get("trigger")
        assert trigger is not None, "写入点必须埋点（自动收口盘点的消费前提）"
        assert trigger["condition"] == "spec_delivered_adjudicated"
        assert trigger["type"] == "instant_fail_storm"
        assert trigger["spec"] == "spec-a"

    def test_alert_evidence_carries_forensics(self, tmp_path):
        """2.2：风暴告警 evidence 留存 stderr 尾部与 worktree 状态快照。"""
        import subprocess as sp

        runner, holder = _make_gate_runner(tmp_path)
        wt = tmp_path / "wt-spec-a"
        wt.mkdir()
        sp.run(["git", "init", "-q", "-b", "main", str(wt)], check=True)
        sp.run(["git", "-C", str(wt), "config", "user.email", "t@t.co"],
               check=True)
        sp.run(["git", "-C", str(wt), "config", "user.name", "t"], check=True)
        (wt / "half-done.txt").write_text("wip", encoding="utf-8")
        for _ in range(2):
            runner._record_instant_fail(
                "spec-a", 5.0, error="boom",
                stderr_tail="ECONNREFUSED 127.0.0.1:443", worktree_path=wt)
        alerts = self._storm_alerts(tmp_path)
        assert len(alerts) == 1
        ev = alerts[0]["evidence"]
        assert "stderr_tail=ECONNREFUSED 127.0.0.1:443" in ev
        assert "worktree[" in ev
        assert "dirty=1" in ev and "half-done.txt" in ev

    def test_forensics_bounded(self, tmp_path):
        """有界留存：超长 stderr 不撑爆告警 evidence（design：不落大对象）。"""
        runner, holder = _make_gate_runner(tmp_path)
        long_tail = "x" * 5000
        for _ in range(2):
            runner._record_instant_fail(
                "spec-a", 5.0, error="boom", stderr_tail=long_tail)
        alerts = self._storm_alerts(tmp_path)
        assert len(alerts) == 1
        assert len(alerts[0]["evidence"]) < 1500

    def test_forensics_failure_does_not_block_counting(self, tmp_path):
        """失败路径不阻断计数：worktree 缺失 + 空 stderr 仍正常进冷却，
        evidence 不写占位噪音。"""
        runner, holder = _make_gate_runner(tmp_path)
        missing = tmp_path / "no-such-wt"
        for _ in range(2):
            runner._record_instant_fail(
                "spec-a", 5.0, error="e", stderr_tail="", worktree_path=missing)
        assert runner.is_instant_fail_cooldown("spec-a") is True
        assert runner._instant_fail["spec-a"]["count"] == 2
        alerts = self._storm_alerts(tmp_path)
        assert len(alerts) == 1
        assert "stderr_tail" not in alerts[0]["evidence"]

    def test_forensics_kept_on_state_entry(self, tmp_path):
        """取证素材随 per-spec 状态留存（末次死亡覆盖写）。"""
        runner, holder = _make_gate_runner(tmp_path)
        runner._record_instant_fail("spec-a", 5.0, error="e1",
                                    stderr_tail="first death",
                                    worktree_path=None)
        runner._record_instant_fail("spec-a", 5.0, error="e2",
                                    stderr_tail="second death",
                                    worktree_path=None)
        st = runner._instant_fail["spec-a"]
        assert "second death" in st["last_forensics"]
