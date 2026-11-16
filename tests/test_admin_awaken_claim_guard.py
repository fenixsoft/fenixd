"""test_admin_awaken_claim_guard.py — admin 唤起并发认领守卫测试
（evo-admin-awaken-inflight-claim-guard tasks 2.1/2.2）

覆盖矩阵（并发唤起 × 排队窗口 × worker 失败）：

并发唤起矩阵（2.1）
- 同 spec 首 run 已启动（store 有 pending DISPOSITION）→ 提交点复查命中
  既有 mutex-skip 语义回归（不派发、skipped 留痕、return False）；
- 同 spec 首 run 仍在共享池队列（TOCTOU 窗，认领条目在场）→ 认领命中
  被让位——无第二条 admin run、skipped 留痕、return False、R5 info 与
  命中计数留痕；
- 不同 spec 并行不受影响（认领 spec-a 在场，spec-b 照常派发）；
- invoke_manual（signal_rec=None）不被守卫拦截、不消费/不释放他属认领；
- daemon 级信号（spec=None）在他 spec 在飞 run（认领+pending 双形态）
  期间不被误让位（spec 门回归）。

认领释放与恢复（2.2）
- lane 实现体异常退出 → 终态 finally 释放认领，后续同 spec 唤起放行；
- 令牌校验：无令牌（人工通道形态）/令牌不匹配的 run 完成不释放他属
  自动认领；
- submit 抛出 → 同锁回滚登记、剥除令牌、回退同步执行照常完成；
- 同步回退分支（executor 未挂载）登记/释放同构配对：signal 携带令牌、
  worker 终态后认领集合清空；
- 让位保持未送达语义：return False、源记录不被闭环、首 run 收尾（认领
  释放）后下一巡检周期自然重评（再唤起放行）。

替身契约说明：走真实 ``maintenance_runs.run_administrator`` 门面的替身
（``_RealLaneStubRunner``）以 monkeypatch ``_run_administrator_impl`` 编程
终态，用于验证 1.3 终态释放门；纯记录型替身（``_StubRunner``）绕过真实
门面，等价「lane 未进入」形态，由提交点回滚/worker 外层兜底释放覆盖。
"""

import sys
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, DISPOSITION, ESCALATION
from core.agent_runner import maintenance_runs
from tests.helpers import FakeLogger, utcnow_iso


class _RecordingLogger:
    """记录型 logger：断言让位 INFO 留痕。"""

    def __init__(self):
        self.records = []

    def _rec(self, level):
        def _w(channel, msg, *extra):
            self.records.append((level, channel, msg))
        return _w

    def __getattr__(self, name):
        return self._rec(name)


class _StubRunner:
    """纯记录型替身：绕过真实 run_administrator 门面（不释放认领）。"""

    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(dict(signal))


class _RealLaneStubRunner:
    """走真实 run_administrator 门面的替身：impl 经 monkeypatch 编程终态。

    用于验证 1.3 终态释放门（成功/异常三路统一 finally）；impl 缺省形态
    返回 None（与既有纯记录型替身同语义，_worker 对 None disp 的既有容忍
    路径见 test_admin_dispatch_window_avoidance）。
    """

    def __init__(self):
        self.calls = []
        self.logger = FakeLogger()

    def run_administrator(self, signal):
        # 先拷贝快照：门面会 pop 派发上下文携带的内部令牌键，配对断言需要
        # 提交时形态
        self.calls.append(dict(signal))
        return maintenance_runs.run_administrator(self, signal)


class _BoomSubmitExecutor:
    """submit 即抛的 executor 替身（模拟已 shutdown 等投递失败形态）。"""

    def submit(self, fn):
        raise RuntimeError("executor already shut down")


def _make_monitor(tmp_path, runner, logger=None):
    class _SM:
        def read_all(self):
            return {}

        def read_one(self, name):
            return None

    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    store = AdminStore(proot, None)
    mon = AdminMonitor(
        {},
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


def _seed_pending(store, spec, run_id="admin-spec-a-1", signal_type="stuck"):
    """落一条在飞 pending DISPOSITION（模拟首 run 已启动、worker 在处置中）。"""
    store.append(
        {
            "kind": DISPOSITION,
            "status": "pending",
            "signal_type": signal_type,
            "spec": spec,
            "admin_run_id": run_id,
            "description": f"Administrator 处置中（run {run_id}）",
            "result": "pending",
        }
    )


def _seed_claim(spec, token="queued-token-1"):
    """登记排队认领条目（模拟首 run 已提交、仍在共享池队列的 TOCTOU 窗）。"""
    with _ADMIN_DISPATCH_CLAIM_LOCK:
        _ADMIN_DISPATCH_CLAIMED_SPECS[spec] = {
            "token": token,
            "claimed_at": time.time(),
        }


def _claim_of(spec):
    with _ADMIN_DISPATCH_CLAIM_LOCK:
        entry = _ADMIN_DISPATCH_CLAIMED_SPECS.get(spec)
        return dict(entry) if entry else None


def _dispositions(store):
    return [r for r in store.read_all() if r.get("kind") == DISPOSITION]


def _escalations(store):
    return [r for r in store.read_all() if r.get("kind") == ESCALATION]


def _skipped(store):
    return [d for d in _dispositions(store) if d.get("result") == "skipped"]


from core.admin_monitor import (  # noqa: E402 — 依赖上方模块级导入顺序可读性
    _ADMIN_DISPATCH_CLAIMED_SPECS,
    _ADMIN_DISPATCH_CLAIM_LOCK,
    _ADMIN_DISPATCH_CLAIM_STATS,
    _admin_dispatch_release_claim,
)


class TestConcurrentAwakenMatrix:
    """2.1 并发唤起矩阵：同 spec 排队窗让位 / 已启动互斥回归 / 豁免面。"""

    def test_first_run_started_mutex_skip_regression(self, tmp_path):
        """首 run 已启动（store pending DISPOSITION）→ 提交点复查命中既有
        mutex-skip 语义：不派发、skipped 留痕、return False。"""
        runner = _StubRunner()
        _, mon = _make_monitor(tmp_path, runner)
        _seed_pending(mon.store, "spec-a")

        ret = mon._invoke_administrator(_make_signal(), {"id": "sig-1"})

        assert ret is False, "复查命中 MUST 回传未送达（False）"
        assert runner.calls == [], "在飞 pending 在场 MUST NOT 再派发"
        skipped = _skipped(mon.store)
        assert len(skipped) == 1, "mutex-skip 形态留痕恰一条"
        assert "认领守卫" in str(skipped[0].get("action_taken"))
        assert _escalations(mon.store) == [], "让位 MUST NOT 落升级告警"

    def test_first_run_queued_claim_hit_yields(self, tmp_path):
        """首 run 仍在共享池队列（TOCTOU 窗，认领条目在场）→ 认领命中被
        让位：无第二条 admin run + R5 info 留痕与命中计数。"""
        runner = _StubRunner()
        logger = _RecordingLogger()
        _, mon = _make_monitor(tmp_path, runner, logger=logger)
        _seed_claim("spec-a", token="queued-token-1")
        before = _ADMIN_DISPATCH_CLAIM_STATS["yield"]

        ret = mon._invoke_administrator(_make_signal(), {"id": "sig-1"})

        assert ret is False, "TOCTOU 窗内第二唤起 MUST 让位（return False）"
        assert runner.calls == [], "认领在场 MUST NOT 产生第二条 admin run"
        assert len(_skipped(mon.store)) == 1, "让位须补 skipped 处置留痕"
        assert _claim_of("spec-a")["token"] == "queued-token-1", (
            "让位路径 MUST NOT 动他属认领条目")
        assert any(
            k == "info"
            and "evo-admin-awaken-inflight-claim-guard" in msg
            and "让位" in msg
            and "queued-token-1"[:8] in msg
            for k, _, msg in logger.records
        ), "R5：让位 info 须含守卫标识、让位对象标识（令牌前缀）与认领时刻"
        assert _ADMIN_DISPATCH_CLAIM_STATS["yield"] == before + 1, (
            "R5：让位命中计数须递增")

    def test_different_spec_parallel_unaffected(self, tmp_path):
        """不同 spec 之间互不影响：认领 spec-a 在场，spec-b 照常派发。"""
        runner = _StubRunner()
        _, mon = _make_monitor(tmp_path, runner)
        _seed_claim("spec-a")

        ret = mon._invoke_administrator(
            _make_signal(spec="spec-b"), {"id": "sig-1"})

        assert ret is None, "跨 spec 派发不走让位返回形态"
        assert len(runner.calls) == 1, "不同 spec 并行不受影响"
        assert runner.calls[0]["spec"] == "spec-b"
        assert _claim_of("spec-a") is not None, "他属认领不被波及"

    def test_invoke_manual_not_blocked_by_guard(self, tmp_path):
        """invoke_manual（signal_rec=None）不被守卫拦截：认领在场照常派发，
        且不释放他属自动认领。"""
        runner = _StubRunner()
        _, mon = _make_monitor(tmp_path, runner)
        _seed_claim("spec-a", token="auto-queued-token")

        mon.invoke_manual(_make_signal())

        assert len(runner.calls) == 1, "人工显式呼叫是设计内合法并行（R3）"
        assert "_admin_claim_token" not in runner.calls[0], (
            "人工通道不登记认领，signal 不携带令牌")
        assert _claim_of("spec-a")["token"] == "auto-queued-token", (
            "人工派发 MUST NOT 释放他属自动认领")

    @pytest.mark.parametrize("block_mode", ["claim", "pending"])
    def test_daemon_level_signal_not_blocked_by_other_spec(
            self, tmp_path, block_mode):
        """daemon 级信号（spec=None）在他 spec 在飞 run 期间不被误让位
        （spec 门回归）：认领与 pending DISPOSITION 双形态在场均放行。"""
        runner = _StubRunner()
        _, mon = _make_monitor(tmp_path, runner)
        if block_mode == "claim":
            _seed_claim("spec-a")
        else:
            _seed_pending(mon.store, "spec-a")

        ret = mon._invoke_administrator(
            _make_signal(spec=None, signal_type="daemon_errors"),
            {"id": "sig-daemon-1"},
        )

        assert ret is None, "daemon 级信号不走让位返回形态"
        assert len(runner.calls) == 1, (
            f"spec=None 哨兵不过滤（{block_mode} 形态），MUST NOT 被误让位")


class TestClaimReleaseAndRecovery:
    """2.2 认领释放与恢复：worker 终态释放 / 令牌校验 / 回滚与配对。"""

    def test_worker_exception_releases_claim_and_next_awaken_passes(
            self, tmp_path, monkeypatch):
        """lane 实现体异常退出 → 终态 finally 释放认领，后续同 spec 唤起
        放行（自然重评）。"""
        runner = _RealLaneStubRunner()
        _, mon = _make_monitor(tmp_path, runner)

        def _boom(_runner, _signal):
            raise RuntimeError("lane boom")

        monkeypatch.setattr(maintenance_runs, "_run_administrator_impl", _boom)
        mon._invoke_administrator(_make_signal(), {"id": "sig-1"})
        assert runner.calls, "异常路径前置：首唤起须已派发"
        assert _claim_of("spec-a") is None, "worker 异常退出认领须释放"

        # 后续同 spec 唤起放行（自然重评再武装）
        runner2 = _StubRunner()
        _, mon2 = _make_monitor(tmp_path, runner2)
        ret = mon2._invoke_administrator(_make_signal(), {"id": "sig-2"})
        assert ret is None and len(runner2.calls) == 1, (
            "认领释放后同 spec 唤起 MUST 放行")

    def test_manual_lane_completion_keeps_foreign_auto_claim(self, tmp_path,
                                                             monkeypatch):
        """令牌校验：无令牌（人工通道形态）run 完成不释放他属自动认领。"""
        _seed_claim("spec-a", token="auto-token-keep")
        runner = _RealLaneStubRunner()
        monkeypatch.setattr(
            maintenance_runs, "_run_administrator_impl",
            lambda _r, _s: None)

        maintenance_runs.run_administrator(runner, _make_signal())

        assert _claim_of("spec-a")["token"] == "auto-token-keep", (
            "人工/同步回退 run 未登记认领，MUST NOT 按键误删他属认领")

    def test_token_mismatch_release_is_noop(self, tmp_path):
        """令牌不匹配的释放为 no-op（属主令牌强制约定）。"""
        _seed_claim("spec-a", token="owner-token")
        assert _admin_dispatch_release_claim("spec-a", "wrong-token") is False
        assert _claim_of("spec-a")["token"] == "owner-token", (
            "不匹配释放 MUST NOT 误删他属认领")
        assert _admin_dispatch_release_claim("spec-a", "owner-token") is True
        assert _claim_of("spec-a") is None, "属主令牌匹配即释放"

    def test_submit_raise_rolls_back_claim(self, tmp_path):
        """submit 抛出 → 同锁回滚登记、剥除令牌、回退同步执行照常完成。"""
        runner = _StubRunner()
        _, mon = _make_monitor(tmp_path, runner)
        mon._code_review_executor = _BoomSubmitExecutor()

        ret = mon._invoke_administrator(_make_signal(), {"id": "sig-1"})

        assert _claim_of("spec-a") is None, "submit 抛出 MUST 回滚登记"
        assert len(runner.calls) == 1, "投递失败回退同步执行，唤起不丢"
        assert "_admin_claim_token" not in runner.calls[0], (
            "回滚后剥除令牌，同步 run 不再携带派发上下文内部键")

    def test_sync_fallback_claim_release_pairing(self, tmp_path, monkeypatch):
        """同步回退分支（executor 未挂载）登记/释放同构配对：signal 携带
        令牌进 worker，worker 终态后认领集合清空。"""
        runner = _RealLaneStubRunner()
        _, mon = _make_monitor(tmp_path, runner)
        assert mon._code_review_executor is None, "前置：executor 未挂载形态"
        monkeypatch.setattr(
            maintenance_runs, "_run_administrator_impl", lambda _r, _s: None)

        mon._invoke_administrator(_make_signal(), {"id": "sig-1"})

        assert len(runner.calls) == 1
        token = runner.calls[0].get("_admin_claim_token")
        assert token, "同步回退同样先登记：signal 须携带属主令牌（R2 配对）"
        assert _claim_of("spec-a") is None, (
            "worker 终态后认领释放（登记/释放同构配对）")

    def test_yield_keeps_undelivered_semantics_and_reevaluates(
            self, tmp_path):
        """让位保持未送达语义：return False、无新 pending、首 run 收尾后
        下一巡检周期自然重评（再唤起放行）。"""
        runner = _StubRunner()
        _, mon = _make_monitor(tmp_path, runner)
        _seed_claim("spec-a", token="first-run-token")

        ret = mon._invoke_administrator(_make_signal(), {"id": "sig-1"})
        assert ret is False, "未送达语义：调用方指纹备忘回滚依赖 False 透传"
        pending_after_yield = [
            d for d in _dispositions(mon.store)
            if d.get("status") == "pending" or d.get("result") == "pending"
        ]
        assert pending_after_yield == [], "让位 MUST NOT 落新在飞 pending"

        # 首 run 收尾（终态释放认领）→ 下一巡检周期自然重评放行
        assert _admin_dispatch_release_claim("spec-a", "first-run-token")
        ret2 = mon._invoke_administrator(_make_signal(), {"id": "sig-1"})
        assert ret2 is None and len(runner.calls) == 1, (
            "认领释放后自然重评：同 spec 唤起放行")
