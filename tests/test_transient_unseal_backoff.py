"""evo-fix-transient-break-unseal-backoff：解封渐进恢复专项测试。

覆盖 tasks 2.1：
- 解封不立即全量放行（hold 先行）
- 首场解封 hold=基数而非 0
- hold 随解封次数渐进且封顶（多指纹取最大）
- 探针失败额外 +1（下场 hold 相应加长）
- 探针通过后错峰放行（单条节拍准入，无同拍全量）
- 探针失败重熔断且次数+1
- 稳定窗后衰减复位
- 配置键热更新生效
- 无外部触发时 hold/观察窗到期仍能主动唤醒派发（真实定时器端到端，
  回归 fix-provider-transient-backoff 之前的惰性停摆缺口）

态序口径（design D3）：冻结 > post-unseal hold > 探针观察窗 > 错峰放行 > open。
"""

import time

import pytest

from core.agent_runner.provider_circuit import (
    TRANSIENT_UNSEAL_BACKOFF_BASE_SECONDS,
    TRANSIENT_UNSEAL_PROBE_WINDOW_SECONDS,
    ProviderCircuit,
)
from tests.helpers import FakeLogger

FP_TEXT = "unrecognized model deepseek-v4"
FP = ProviderCircuit.normalize_transient_fingerprint(FP_TEXT)
FP_B_TEXT = "connection refused by gateway"
FP_B = ProviderCircuit.normalize_transient_fingerprint(FP_B_TEXT)


class TestUnsealBackoffBase:
    """解封节奏态机（ProviderCircuit 单元，假时钟）。"""

    class _FakePM:
        def __init__(self, config=None, engine=None):
            self.config = config or {}
            self.project_root = None
            self.logger = FakeLogger()
            # now=None → _now() 返回真实单调钟（真实定时器端到端用例）
            self.now = 1000.0
            self._pm_engine_ref = engine

        def _now(self):
            if self.now is None:
                return time.monotonic()
            return self.now

        def _get_config(self, key, default=None):
            from core.config import ConfigLoader
            return ConfigLoader.get(self.config, key, default)

    def _make(self, config=None, engine=None):
        pm = self._FakePM(config=config, engine=engine)
        return ProviderCircuit(pm), pm

    def _trigger(self, pc, text=FP_TEXT, t0=1000.0, step=100.0):
        """窗口内三次同指纹记账 → 触发全局熔断。"""
        pc.record_transient_error(text, now=t0)
        pc.record_transient_error(text, now=t0 + step)
        assert pc.record_transient_error(text, now=t0 + 2 * step) is True

    # ── 解封不立即全量放行 / 首场 hold=基数 ─────────────────────────────

    def test_unseal_enters_hold_not_immediate_release(self):
        """熔断到期 → 进入 post-unseal hold（而非 open 全量放行），hold 期准入拒绝。"""
        pc, pm = self._make()
        self._trigger(pc)
        assert pc.transient_unseal_gate(now=1500) == "frozen"
        # 冷却到期（600s）→ 解封即 hold，不是 open
        assert pc.transient_unseal_gate(now=1801) == "hold"
        # hold 期内单条准入也拒绝（积压整队持有）
        assert pc.admit_unseal_dispatch(now=1810) is False

    def test_first_unseal_hold_equals_base_not_zero(self):
        """首场解封 hold = 基数×1（60s），而非 0（design D2 计数规则）。"""
        pc, pm = self._make()
        self._trigger(pc)
        assert pc.transient_unseal_gate(now=1801) == "hold"
        assert pc._transient_hold_until == pytest.approx(1801 + 60)
        assert pc.transient_unseal_count(FP, now=1801) == 1

    def test_hold_scales_with_unseal_count_and_caps(self):
        """hold 随解封次数渐进（基数×N）且封顶（design D5 保守档可配）。"""
        pc, pm = self._make({
            "agents": {
                "transient_unseal_backoff_base_seconds": 30,
                "transient_unseal_backoff_max_seconds": 100,
                "transient_break_cooldown_seconds": 50,
                # 观察窗禁用：hold 直接到期判定，简化多场推进
                "transient_unseal_probe_window_seconds": 0,
            },
        })
        # 第 1 场：count=1 → hold=30
        self._trigger(pc, t0=1000.0)  # 冻结至 1250
        assert pc.transient_unseal_gate(now=1300) == "hold"
        assert pc._transient_hold_until == pytest.approx(1300 + 30)
        # 第 2 场：count=2 → hold=60
        self._trigger(pc, t0=1400.0)  # 冻结至 1650
        assert pc.transient_unseal_gate(now=1700) == "hold"
        assert pc._transient_hold_until == pytest.approx(1700 + 60)
        # 第 3 场：count=3 → hold=90
        self._trigger(pc, t0=1800.0)  # 冻结至 2050
        assert pc.transient_unseal_gate(now=2100) == "hold"
        assert pc._transient_hold_until == pytest.approx(2100 + 90)
        # 第 4 场：count=4 → 30×4=120 → 封顶 100
        self._trigger(pc, t0=2200.0)  # 冻结至 2450
        assert pc.transient_unseal_gate(now=2500) == "hold"
        assert pc._transient_hold_until == pytest.approx(2500 + 100)

    def test_multi_fingerprint_hold_takes_max(self):
        """多指纹并存时 hold 取各指纹次数最大值（design D2）。"""
        pc, pm = self._make()
        # 第 1 场：仅指纹 A → A.count=1
        self._trigger(pc, text=FP_TEXT, t0=1000.0)
        assert pc.transient_unseal_gate(now=1801) == "hold"
        # 第 2 场：A 再记 2 次 + 指纹 B 记 3 次触发（A 另有冻结期记账 1 次）
        pc.record_transient_error(FP_TEXT, now=1900)
        pc.record_transient_error(FP_TEXT, now=1950)
        pc.record_transient_error(FP_B_TEXT, now=2000)
        pc.record_transient_error(FP_B_TEXT, now=2050)
        assert pc.record_transient_error(FP_B_TEXT, now=2100) is True
        pc.record_transient_error(FP_TEXT, now=2200)  # 冻结中记账（早退分支）
        # 到期解封：A=1+1=2、B=0+1=1 → hold = 60×max(2,1) = 120
        assert pc.transient_unseal_gate(now=2701) == "hold"
        assert pc._transient_hold_until == pytest.approx(2701 + 120)
        assert pc.transient_unseal_count(FP, now=2701) == 2
        assert pc.transient_unseal_count(FP_B, now=2701) == 1

    # ── 探针放行 / 错峰放行 ──────────────────────────────────────────

    def test_probe_single_admission_then_staggered_release(self):
        """hold 期满 → 仅单条探针准入；探针通过 → 错峰节拍放行（无同拍全量）。"""
        pc, pm = self._make({
            "agents": {
                "transient_unseal_release_stagger_seconds": 30,
            },
        })
        self._trigger(pc)
        assert pc.transient_unseal_gate(now=1801) == "hold"
        # hold 期满（60s）→ 探针待放行
        assert pc.transient_unseal_gate(now=1862) == "probe"
        # 首条准入 = 探针；同拍第二准入拒绝（其余积压仍持有）
        assert pc.admit_unseal_dispatch(now=1862) is True
        assert pc.admit_unseal_dispatch(now=1862.5) is False
        assert pc.transient_unseal_gate(now=1863) == "observe"
        # 观察窗内无同指纹新记账 → 期满（1862+120=1982）探针通过 → 错峰放行
        assert pc.transient_unseal_gate(now=1983) == "release"
        # 错峰节拍：当拍一条，同拍即转入 release-wait
        assert pc.admit_unseal_dispatch(now=1983) is True
        assert pc.admit_unseal_dispatch(now=1984) is False
        # 下一拍（30s 后）准入一条
        assert pc.admit_unseal_dispatch(now=2013.5) is True
        assert pc.admit_unseal_dispatch(now=2014) is False

    def test_release_drained_exits_stagger_state(self):
        """积压放完（队列空回调）→ 退出错峰态，后续派发恢复常态节奏。"""
        pc, pm = self._make()
        self._trigger(pc)
        pc.transient_unseal_gate(now=1801)
        pc.transient_unseal_gate(now=1862)
        assert pc.admit_unseal_dispatch(now=1862) is True
        assert pc.transient_unseal_gate(now=1983) == "release"
        assert pc.admit_unseal_dispatch(now=1983) is True
        pc.note_release_drained()
        assert pc.transient_unseal_gate(now=1984) == "open"
        assert pc.admit_unseal_dispatch(now=1984.5) is True

    # ── 探针失败：重熔断 + 解封次数额外 +1 ───────────────────────────

    def test_probe_failure_refreezes_and_bumps_count(self):
        """探针观察窗内同指纹新记账 → 判败：按现行规则重熔断、次数额外 +1。"""
        pc, pm = self._make()
        self._trigger(pc)
        assert pc.transient_unseal_gate(now=1801) == "hold"  # 解封 count=1
        assert pc.transient_unseal_gate(now=1862) == "probe"
        assert pc.admit_unseal_dispatch(now=1862) is True
        # 探针 run 的 provider 调用同指纹再失败（观察窗内记账）
        pc.record_transient_error(FP_TEXT, now=1900)
        # 观察窗期满判定 → 重熔断（frozen），按现行 cooldown 配置
        assert pc.transient_unseal_gate(now=1983) == "frozen"
        # 次数 = 解封 1 + 探针失败 1 = 2（加速升级）
        assert pc.transient_unseal_count(FP, now=1983) == 2
        # 重熔断按现行 600s 冷却（冻结至 2583）；下一场解封 count=3
        # → hold = 60×3 = 180（探针失败加速升级，下场 hold 相应加长）
        pc.record_transient_error(FP_TEXT, now=2100)  # 冻结期记账（早退分支）
        assert pc.transient_unseal_gate(now=2584) == "hold"
        assert pc._transient_hold_until == pytest.approx(2584 + 180)
        assert pc.transient_unseal_count(FP, now=2584) == 3

    def test_probe_failure_by_other_fingerprint_not_marked(self):
        """观察窗内**非**待判指纹的新记账不判探针失败（同指纹口径）。"""
        pc, pm = self._make()
        self._trigger(pc, text=FP_TEXT)
        pc.transient_unseal_gate(now=1801)
        pc.transient_unseal_gate(now=1862)
        assert pc.admit_unseal_dispatch(now=1862) is True
        pc.record_transient_error(FP_B_TEXT, now=1900)  # 异指纹
        assert pc.transient_unseal_gate(now=1983) == "release"  # 探针通过

    # ── 稳定窗衰减复位 ───────────────────────────────────────────────

    def test_stable_window_decay_resets_count(self):
        """稳定观察窗（无新熔断）后解封次数衰减复位（减一/窗，非直接清零）。"""
        pc, pm = self._make({
            "agents": {"transient_unseal_stable_window_seconds": 1800},
        })
        # 两场解封 → count=2（hot=第二场解封时刻）
        self._trigger(pc, t0=1000.0)
        pc.transient_unseal_gate(now=1801)
        self._trigger(pc, t0=1900.0)
        pc.transient_unseal_gate(now=2701)
        assert pc.transient_unseal_count(FP, now=2701 + 1799) == 2
        # 满一稳定窗 → 减一
        assert pc.transient_unseal_count(FP, now=2701 + 1800) == 1
        # 满两窗 → 清零
        assert pc.transient_unseal_count(FP, now=2701 + 3600) == 0
        # 衰减复位后下一场解封 hold 回到基数水平
        self._trigger(pc, t0=6000.0)
        assert pc.transient_unseal_gate(now=6801) == "hold"
        assert pc._transient_hold_until == pytest.approx(6801 + 60)
        assert pc.transient_unseal_count(FP, now=6801) == 1

    # ── 配置键生效 / 禁用开关 ────────────────────────────────────────

    def test_config_hot_update_takes_effect(self):
        """修改 agents.transient_unseal_* 任一键 → 下一场 hold/观察窗随之生效。"""
        pc, pm = self._make()
        self._trigger(pc)
        assert pc.transient_unseal_gate(now=1801) == "hold"
        assert pc._transient_hold_until == pytest.approx(1801 + 60)
        # 热更新基数与观察窗（配置对象原地修改，等价 30s 热更新后的生效值）
        pm.config["agents"] = {
            "transient_unseal_backoff_base_seconds": 10,
            "transient_unseal_probe_window_seconds": 5,
            "transient_break_cooldown_seconds": 300,
        }
        self._trigger(pc, t0=1900.0)  # 冻结至 2100+300=2400
        assert pc.transient_unseal_gate(now=2401) == "hold"
        assert pc._transient_hold_until == pytest.approx(2401 + 20)  # 10×count2
        # hold 期满 → 观察窗用新值 5s
        assert pc.transient_unseal_gate(now=2430) == "probe"
        assert pc.admit_unseal_dispatch(now=2430) is True
        assert pc.transient_unseal_gate(now=2436) == "release"  # 2430+5 已期满

    def test_disabled_base_releases_immediately_legacy_semantics(self):
        """base=0（禁用）→ 到期即全量放行（既有语义），不记忆解封次数。"""
        pc, pm = self._make({
            "agents": {"transient_unseal_backoff_base_seconds": 0},
        })
        self._trigger(pc)
        assert pc.transient_unseal_gate(now=1801) == "open"
        assert pc.transient_unseal_count(FP, now=1801) == 0

    def test_defaults_are_conservative(self):
        """缺省值 = design D5 保守档（60/600/120/1800/30）。"""
        pc, pm = self._make()
        cfg = pc._unseal_cfg()
        assert cfg["base"] == TRANSIENT_UNSEAL_BACKOFF_BASE_SECONDS == 60
        assert cfg["cap"] == 600
        assert cfg["probe_window"] == TRANSIENT_UNSEAL_PROBE_WINDOW_SECONDS == 120
        assert cfg["stable"] == 1800
        assert cfg["stagger"] == 30

    # ── 队列闸门态序（queue 首道闸消费口径，1.2）────────────────────

    def test_dispatch_queue_gate_order_freeze_over_hold(self):
        """queue 首道闸按态序消费：frozen/hold/observe/release-wait 均整队持有。"""
        from core.pm_engine.dispatch import Dispatcher

        class _GatePM:
            def __init__(self, gate):
                self.gate = gate
                self.shutting_down = False
                self.logger = FakeLogger()
                self.drained = False

            def _transient_unseal_gate(self):
                return self.gate

            def _transient_unseal_admit(self):
                return True

            def _transient_unseal_note_drained(self):
                self.drained = True

        for gate in ("frozen", "hold", "observe", "release-wait"):
            pm = _GatePM(gate)
            d = Dispatcher(pm)
            d._run_queue.append((5, "spec-x", "implementer", 0.0))
            d._process_queue()
            # 整队持有：条目不得被 pop（gate 短路先于任何派发扫描）
            assert len(d._run_queue) == 1, gate

    def test_dispatch_queue_release_wait_drains_when_empty(self):
        """release-wait 且队列空 → 通知退出错峰态（放完回调）。"""
        from core.pm_engine.dispatch import Dispatcher

        class _GatePM:
            def __init__(self):
                self.shutting_down = False
                self.logger = FakeLogger()
                self.drained = False

            def _transient_unseal_gate(self):
                return "release-wait"

            def _transient_unseal_note_drained(self):
                self.drained = True

        pm = _GatePM()
        d = Dispatcher(pm)
        d._process_queue()
        assert pm.drained is True

    # ── 无外部触发仍能主动唤醒（真实定时器端到端）───────────────────

    def test_unseal_pace_self_drives_without_external_trigger(self):
        """hold/观察窗到期 MUST 主动唤醒派发（回归惰性停摆缺口，design D3）。

        触发熔断后不做任何人为查询/准入，仅靠 threading.Timer 定时器链驱动：
        冻结到期唤醒 → gate 查询（解封→hold）→ hold 到期唤醒（→探针观察）→
        观察窗到期唤醒（→探针通过→错峰放行）。
        """
        driven = []
        holder = {}

        class _Engine:
            def _process_queue(self):
                # 模拟真实派发闸门：唤醒即查询 gate（查询即推进态机）
                driven.append(holder["pc"].transient_unseal_gate())

        pc, pm = self._make(
            {
                "agents": {
                    "transient_break_cooldown_seconds": 1,
                    "transient_unseal_backoff_base_seconds": 1,
                    "transient_unseal_probe_window_seconds": 1,
                    "transient_unseal_release_stagger_seconds": 1,
                },
            },
            engine=_Engine(),
        )
        holder["pc"] = pc
        pm.now = None  # 真实单调钟（与真实定时器同源）
        self._trigger_real(pc)
        # 不做任何外部触发，等待定时器链自驱穿越全部到期锚点
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if any(g == "release" for g in driven):
                break
            time.sleep(0.1)
        try:
            assert any(g == "hold" for g in driven), f"hold 未被自驱唤醒: {driven}"
            assert any(g == "probe" for g in driven), f"probe 未被自驱唤醒: {driven}"
            assert any(g == "release" for g in driven), (
                f"release 未被自驱唤醒: {driven}"
            )
        finally:
            # 终止错峰定时器链（防测试后链继续空转至 horizon）
            pc.note_release_drained()
            t = pc._unseal_wake_timer
            if t is not None:
                t.cancel()

    def _trigger_real(self, pc):
        """真实时钟版熔断触发（now=None → _now() 单调钟）。"""
        pc.record_transient_error(FP_TEXT)
        pc.record_transient_error(FP_TEXT)
        assert pc.record_transient_error(FP_TEXT) is True
