"""test_admin_dispatch_window_avoidance.py — admin 唤起断窗/瞬断冻结避让测试
（evo-add-night-window-inflight-guard tasks 2.1/3.2）

覆盖：
- 瞬断冻结态 / 夜间断窗期内到达唤起时机 → 本轮跳过、不唤起 admin 会话、
  留痕跳过原因（自动路径补 result="skipped" 处置记录）；
- 窗外且非冻结 → 唤起行为与现状一致（零跳过记录）；
- 人工显式触发（invoke_manual，signal_rec=None）在断窗/冻结期内同政策避让：
  仅日志留痕、不补处置记录、不增 retry_count、不落升级告警；
- 窗配置 off 显式禁用 / runner 替身缺冻结探针（半初始化实例）→ fail-open
  照常唤起。

时间注入沿 tests/test_code_fix_night_quiet_window.py 既有形态 patch 模块
time 属性（core.admin_monitor.time.localtime）。窗配置显式写进 config
（conftest 会话级把运行时缺省常量压成 off，防墙钟敏感 flakes）。
"""

import sys
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, DISPOSITION, ESCALATION
from tests.helpers import FakeLogger, utcnow_iso


def _local(h, m, s=0):
    """注入用本地时刻 struct（2026-10-06 周二，tm_yday=279）。"""
    return time.struct_time((2026, 10, 6, h, m, s, 1, 279, -1))


class _RecordingLogger:
    """记录型 logger：断言跳过原因 INFO 留痕。"""

    def __init__(self):
        self.records = []

    def _rec(self, level):
        def _w(channel, msg, *extra):
            self.records.append((level, channel, msg))
        return _w

    def __getattr__(self, name):
        return self._rec(name)


class _StubRunner:
    """可编程 AgentRunner 替身：唤起计数 + 冻结探针可编程。

    无 is_global_transient_break_active 属性的形态用 del 探针字段模拟
    （半初始化/测试替身缺方法 → fail-open 未冻结）。
    """

    def __init__(self, frozen=False, with_probe=True):
        self.calls = []
        self._frozen = frozen
        if with_probe:
            self.is_global_transient_break_active = lambda: self._frozen

    def run_administrator(self, signal):
        self.calls.append(signal)


class _RetrySpyStore(AdminStore):
    """spy store：记录 bump_dispatch_retry 调用（断言跳过路径不增 retry_count）。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.bump_calls = []

    def bump_dispatch_retry(self, alert_id: str, max_retries: int = 1) -> bool:
        self.bump_calls.append((alert_id, max_retries))
        return super().bump_dispatch_retry(alert_id, max_retries=max_retries)


_WINDOW_CFG = {
    "admin": {"code_review_fix": {"night_quiet_window": "04:15-04:45"}},
}


def _make_monitor(tmp_path, runner, config=None, logger=None):
    class _SM:
        def read_all(self):
            return {}

        def read_one(self, name):
            return None

    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    store = _RetrySpyStore(proot, None)
    mon = AdminMonitor(
        config if config is not None else dict(_WINDOW_CFG),
        _SM(),
        proot,
        logger if logger is not None else FakeLogger(),
        store=store,
        agent_runner=runner,
    )
    return proot, mon


def _make_signal(spec="spec-a", signal_type="blocked_stuck"):
    return {
        "signal_type": signal_type,
        "spec": spec,
        "severity": "major",
        "description": f"困境 {signal_type}",
        "evidence": "原信号 evidence 文本",
        "recommended_action": "检查根因",
    }


def _dispositions(store):
    return [r for r in store.read_all() if r.get("kind") == DISPOSITION]


def _escalations(store):
    return [r for r in store.read_all() if r.get("kind") == ESCALATION]


class TestAutoPathAvoidance:
    """自动巡检路径（signal_rec 非 None）：断窗/冻结期内跳过唤起并留痕。"""

    @pytest.mark.parametrize("frozen,clock,reason_kw", [
        (True, (10, 0), "瞬断冻结"),
        (False, (4, 30), "静默窗"),
    ])
    def test_blocked_state_skips_invocation(
            self, tmp_path, monkeypatch, frozen, clock, reason_kw):
        """冻结态（窗外）/断窗期（非冻结）→ 不唤起 + skipped 处置留痕 +
        零升级告警 + 不增 retry_count。"""
        runner = _StubRunner(frozen=frozen)
        logger = _RecordingLogger()
        _, mon = _make_monitor(tmp_path, runner, logger=logger)
        monkeypatch.setattr(
            "core.admin_monitor.time.localtime", lambda: _local(*clock))
        signal_rec = {"id": "sig-test-1"}

        mon._invoke_administrator(_make_signal(), signal_rec)

        assert runner.calls == [], "避让期内 MUST NOT 唤起 admin 会话"
        assert mon.store.bump_calls == [], "跳过属非失败路径，不增 retry_count"
        assert _escalations(mon.store) == [], "跳过 MUST NOT 落升级告警"
        skipped = [d for d in _dispositions(mon.store)
                   if d.get("result") == "skipped"]
        assert len(skipped) == 1, "自动路径须补 skipped 处置留痕恰一条"
        assert reason_kw in str(skipped[0].get("action_taken")), (
            f"处置记录须含跳过原因（{reason_kw}）")
        assert any(
            k == "info" and "避让" in msg for k, _, msg in logger.records
        ), "跳过原因须 INFO 留痕"

    def test_outside_window_and_not_frozen_invokes_normally(
            self, tmp_path, monkeypatch):
        """窗外且非冻结：唤起行为与现状一致——零 skipped、零升级。"""
        runner = _StubRunner(frozen=False)
        _, mon = _make_monitor(tmp_path, runner)
        monkeypatch.setattr(
            "core.admin_monitor.time.localtime", lambda: _local(10, 0))

        mon._invoke_administrator(_make_signal(), {"id": "sig-test-1"})

        assert len(runner.calls) == 1, "窗外正常信号须照常唤起"
        assert _escalations(mon.store) == []
        assert [d for d in _dispositions(mon.store)
                if d.get("result") == "skipped"] == []

    def test_window_disabled_config_invokes_normally(
            self, tmp_path, monkeypatch):
        """窗配置 off 显式禁用：窗内时刻也不避让（与 code-fix 车道同语义）。"""
        runner = _StubRunner(frozen=False)
        cfg = {"admin": {"code_review_fix": {"night_quiet_window": "off"}}}
        _, mon = _make_monitor(tmp_path, runner, config=cfg)
        monkeypatch.setattr(
            "core.admin_monitor.time.localtime", lambda: _local(4, 30))

        mon._invoke_administrator(_make_signal(), {"id": "sig-test-1"})

        assert len(runner.calls) == 1, "窗禁用时断窗避让不生效"

    def test_missing_freeze_probe_fails_open(self, tmp_path, monkeypatch):
        """替身缺冻结探针方法（半初始化实例）：按未冻结处理，不误伤唤起。"""
        runner = _StubRunner(with_probe=False)
        _, mon = _make_monitor(tmp_path, runner)
        monkeypatch.setattr(
            "core.admin_monitor.time.localtime", lambda: _local(10, 0))

        mon._invoke_administrator(_make_signal(), {"id": "sig-test-1"})

        assert len(runner.calls) == 1, "缺探针须 fail-open 照常唤起"


class TestManualPathAvoidance:
    """人工显式触发（invoke_manual / signal_rec=None）：同政策避让。"""

    @pytest.mark.parametrize("frozen,clock", [
        (True, (10, 0)),
        (False, (4, 30)),
    ])
    def test_manual_invoke_avoids_without_disposition_or_escalation(
            self, tmp_path, monkeypatch, frozen, clock):
        """断窗/冻结期内人工唤起同样跳过：仅日志留痕、不补处置记录
        （无虚报锚点）、不增 retry_count、不落升级告警。"""
        runner = _StubRunner(frozen=frozen)
        logger = _RecordingLogger()
        _, mon = _make_monitor(tmp_path, runner, logger=logger)
        monkeypatch.setattr(
            "core.admin_monitor.time.localtime", lambda: _local(*clock))

        mon.invoke_manual(_make_signal())

        assert runner.calls == [], "避让期内人工唤起同样 MUST NOT 派发"
        assert mon.store.bump_calls == [], "人工路径跳过同样不增 retry_count"
        assert _escalations(mon.store) == [], "人工路径跳过不落升级告警"
        assert [d for d in _dispositions(mon.store)
                if d.get("result") == "skipped"] == [], (
            "人工通道无虚报锚点，不补处置记录（沿冷却跳过先例）")
        assert any(
            k == "info" and "避让" in msg for k, _, msg in logger.records
        ), "跳过原因须 INFO 留痕"

    def test_manual_invoke_outside_window_proceeds(
            self, tmp_path, monkeypatch):
        """窗外且非冻结：人工唤起照常派发。"""
        runner = _StubRunner(frozen=False)
        _, mon = _make_monitor(tmp_path, runner)
        monkeypatch.setattr(
            "core.admin_monitor.time.localtime", lambda: _local(10, 0))

        mon.invoke_manual(_make_signal())

        assert len(runner.calls) == 1
