"""fix-manual-invoke-signal-type-passthrough：手动唤起信号透传底层 signal_type。

覆盖两面：
- daemon 消费侧（fenixd._check_admin_invoke_requests）：反查该 spec 最近一条
  未处置（非 handled）SIGNAL/ESCALATION 记录的 signal_type，以
  underlying_signal_type 随信号透传（排除 manual-intervention 自产记录；
  查不到为 None）；顶层 signal_type 保持 manual-intervention。
- 处置收尾自动复位判定门（core/admin_monitor.
  disposition_signal_hits_auto_reset）：signal_type 或 underlying_signal_type
  任一命中 DISPOSITION_AUTO_RESET_SIGNAL_TYPES 即触发；底层类型不在集合
  不复位；store 落痕与节流语义零回归。
"""
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fenixd
from core.admin_monitor import AdminMonitor, disposition_signal_hits_auto_reset
from core.admin_store import (
    AdminStore,
    DISPOSITION,
    ESCALATION,
    SIGNAL,
)
from core.state_machine import ENV_BLOCK_ROUNDS_FIELD


# ── 替身 ─────────────────────────────────────────────────────────────

class _FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


@dataclass
class Disp:
    """最小 AdminDisposition 形状（与 agent_runner 返回契约对齐）。"""

    run_id: str = "admin-test-1"
    spec: Optional[str] = None
    success: bool = True
    problem: str = "env 阻塞"
    actions_taken: str = "修复端口"
    result: str = "resolved"
    summary: str = "已解决"
    escalate: bool = False
    error: str = ""
    recommended_action: str = ""


class _FakeRunner:
    """记录唤起信号并返回固定处置结果的 agent_runner 替身。"""

    def __init__(self, disp: Disp = None):
        self.calls = []
        self.disp = disp or Disp()

    def run_administrator(self, signal):
        self.calls.append(signal)
        return self.disp


class _FakeSM:
    """最小状态机替身：read_one/update_spec/transition/transition_gate。"""

    def __init__(self, specs: dict):
        self.specs = specs
        self.transition_calls = []
        self.gate_calls = []

    def read_one(self, spec):
        return self.specs.get(spec)

    def update_spec(self, spec, patch):
        self.specs.setdefault(spec, {}).update(patch)

    def transition(self, spec, status, *, trigger_run_id=None,
                   agent_type=None, channel="auto"):
        self.transition_calls.append((spec, status))
        self.specs[spec]["status"] = status

    def transition_gate(self, spec, status, *, trigger_run_id=None,
                        agent_type=None, channel="auto"):
        self.gate_calls.append((spec, status))
        self.specs[spec]["status"] = status


def _make_daemon(proot: Path, runner, store):
    """最小 FenixDaemon（__new__ 绕过 __init__），只装配手动唤起拾取路径属性。"""
    daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
    daemon.running = True
    daemon.agent_runner = runner
    daemon.admin_monitor = None  # None → agent_runner 直调回退分支
    daemon.admin_store = store
    daemon.logger = _FakeLogger()
    daemon._admin_executor = None  # None → 同步执行回退
    daemon._project_root = proot
    return daemon


def _pickup(monkeypatch, proot: Path, daemon, spec="myspec"):
    """写请求文件并执行一次主循环拾取。"""
    req = proot / ".fenix" / "admin_invoke_request.json"
    req.write_text(json.dumps({"spec": spec, "source": "manual"}), encoding="utf-8")
    monkeypatch.setattr(fenixd, "PROJECT_ROOT", proot)
    daemon._check_admin_invoke_requests()
    return req


def _make_monitor(tmp_path: Path, sm, runner):
    """构造最小 AdminMonitor（绕过真实的 __init__ 依赖）。"""
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    store = AdminStore(proot, _FakeLogger())
    monitor = AdminMonitor.__new__(AdminMonitor)
    monitor.config = {}
    monitor.admin_cfg = {"enabled": False, "interval_minutes": 30,
                         "cooldown_minutes": 5}
    monitor.state_machine = sm
    monitor.project_root = proot
    monitor.logger = _FakeLogger()
    monitor.store = store
    monitor.agent_runner = runner
    monitor.pm_engine = None
    return monitor


def _blocked_spec_entry(**extra):
    """blocked 态 spec entry（无 branch → 复位走 ready 路径，免 git mock）。"""
    entry = {
        "status": "blocked",
        "frozen": False,
        "error": "verify_env_blocked: 依赖缺失",
        ENV_BLOCK_ROUNDS_FIELD: 2,
    }
    entry.update(extra)
    return entry


# ═════════════════════════════════════════════════════════════════════
# daemon 消费侧透传（tasks 1.1）
# ═════════════════════════════════════════════════════════════════════


class TestDaemonPassthrough:

    def test_passthrough_underlying_type_when_unhandled_signal_exists(
        self, tmp_path, monkeypatch
    ):
        """spec 存在未处置 verify_env_blocked 信号 → 透传其类型，顶层不变。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        store.append({
            "kind": SIGNAL,
            "signal_type": "verify_env_blocked",
            "spec": "myspec",
            "handled": False,
        })
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        req = _pickup(monkeypatch, proot, daemon)

        assert not req.exists()  # 请求文件已消费
        assert len(runner.calls) == 1
        sig = runner.calls[0]
        assert sig["signal_type"] == "manual-intervention"  # 顶层保持不变
        assert sig["underlying_signal_type"] == "verify_env_blocked"
        assert sig["spec"] == "myspec"

    def test_default_none_when_no_unhandled_signal(self, tmp_path, monkeypatch):
        """无可反查信号 → underlying_signal_type 为 None，唤起不报错。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        req = _pickup(monkeypatch, proot, daemon)

        assert not req.exists()
        assert len(runner.calls) == 1
        sig = runner.calls[0]
        assert sig["signal_type"] == "manual-intervention"
        assert sig["underlying_signal_type"] is None

    def test_unhandled_signal_of_other_spec_not_matched(self, tmp_path, monkeypatch):
        """未处置信号属其他 spec → 不反查，缺省 None。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        store.append({
            "kind": SIGNAL,
            "signal_type": "verify_env_blocked",
            "spec": "other-spec",
            "handled": False,
        })
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        _pickup(monkeypatch, proot, daemon, spec="myspec")

        assert runner.calls[0]["underlying_signal_type"] is None

    def test_handled_records_not_matched(self, tmp_path, monkeypatch):
        """已处置（handled=True）记录不参与反查 → 缺省 None。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        store.append({
            "kind": SIGNAL,
            "signal_type": "verify_env_blocked",
            "spec": "myspec",
            "handled": True,
        })
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        _pickup(monkeypatch, proot, daemon)

        assert runner.calls[0]["underlying_signal_type"] is None

    def test_payload_carried_type_rescues_handled_escalation(
        self, tmp_path, monkeypatch
    ):
        """fix-escalation-autoinvoke-passthrough 回归：env 阻塞自动呼叫路径的
        升级记录 severity=warning 落库即按降噪分级标 handled（反查不可见），
        请求文件 payload 直传底层类型 → 透传生效，处置 resolved 后复位门命中。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        rec = store.append({
            "kind": ESCALATION,
            "signal_type": "verify_env_blocked",
            "spec": "myspec",
            "handled": False,
        })
        store.mark_handled(rec["id"])  # 模拟 warning 级降噪：写库即标 handled
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        req = proot / ".fenix" / "admin_invoke_request.json"
        req.write_text(json.dumps({
            "spec": "myspec",
            "source": "manual",
            "underlying_signal_type": "verify_env_blocked",
        }), encoding="utf-8")
        monkeypatch.setattr(fenixd, "PROJECT_ROOT", proot)
        daemon._check_admin_invoke_requests()

        assert not req.exists()
        assert len(runner.calls) == 1
        sig = runner.calls[0]
        assert sig["signal_type"] == "manual-intervention"
        assert sig["underlying_signal_type"] == "verify_env_blocked"

    def test_payload_value_outside_reset_set_falls_back_to_lookup(
        self, tmp_path, monkeypatch
    ):
        """payload 直传值不在复位集合 → 视为未提供回退反查（MUST 只透传
        复位门可消费的类型，与 store 反查同白名单）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        req = proot / ".fenix" / "admin_invoke_request.json"
        req.write_text(json.dumps({
            "spec": "myspec",
            "source": "manual",
            "underlying_signal_type": "warning_stale_triage",
        }), encoding="utf-8")
        monkeypatch.setattr(fenixd, "PROJECT_ROOT", proot)
        daemon._check_admin_invoke_requests()

        assert runner.calls[0]["underlying_signal_type"] is None

    def test_manual_intervention_leftover_skipped_latest_real_type_wins(
        self, tmp_path, monkeypatch
    ):
        """上次手动派发失败遗留的 manual-intervention 未处置 ESCALATION 被排除，
        取其下真实底层类型（按 created 取最新一条命中）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        # 旧：真实底层信号；新：手动通道自产（派发失败落 ESCALATION，未 handled）
        store.append({
            "kind": SIGNAL,
            "signal_type": "verify_env_blocked",
            "spec": "myspec",
            "handled": False,
            "created": "2026-01-01T00:00:00+00:00",
        })
        store.append({
            "kind": ESCALATION,
            "signal_type": "manual-intervention",
            "spec": "myspec",
            "handled": False,
            "created": "2026-01-02T00:00:00+00:00",
        })
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        _pickup(monkeypatch, proot, daemon)

        assert runner.calls[0]["underlying_signal_type"] == "verify_env_blocked"

    def test_manual_intervention_only_leftover_yields_none(
        self, tmp_path, monkeypatch
    ):
        """仅有 manual-intervention 未处置记录 → 不把 manual-intervention 当
        底层类型，透传 None。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        store.append({
            "kind": ESCALATION,
            "signal_type": "manual-intervention",
            "spec": "myspec",
            "handled": False,
            "created": "2026-01-02T00:00:00+00:00",
        })
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        _pickup(monkeypatch, proot, daemon)

        assert runner.calls[0]["underlying_signal_type"] is None

    def test_disposition_and_non_signal_kinds_not_matched(
        self, tmp_path, monkeypatch
    ):
        """kind=disposition 等其他记录不参与反查（仅 SIGNAL/ESCALATION）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        store.append({
            "kind": DISPOSITION,
            "signal_type": "verify_env_blocked",
            "spec": "myspec",
        })
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        _pickup(monkeypatch, proot, daemon)

        assert runner.calls[0]["underlying_signal_type"] is None

    def test_two_invocations_both_manual_intervention_and_no_throttle_swallow(
        self, tmp_path, monkeypatch
    ):
        """两次唤起：两次投递都发生（透传字段不参与节流、不吞并），信号顶层
        均为 manual-intervention，store 记录不被透传改写。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        store.append({
            "kind": SIGNAL,
            "signal_type": "verify_env_blocked",
            "spec": "myspec",
            "handled": False,
        })
        runner = _FakeRunner()
        daemon = _make_daemon(proot, runner, store)

        _pickup(monkeypatch, proot, daemon)
        _pickup(monkeypatch, proot, daemon)

        assert len(runner.calls) == 2
        for sig in runner.calls:
            assert sig["signal_type"] == "manual-intervention"
            assert sig["underlying_signal_type"] == "verify_env_blocked"
        # 落痕零回归：透传不写 store（直调回退分支无 disposition 落盘），
        # 被反查的底层信号记录原样保留（未 handled、类型未被改写）
        seeded = [r for r in store.read_all() if r.get("kind") == SIGNAL]
        assert len(seeded) == 1
        assert seeded[0]["signal_type"] == "verify_env_blocked"
        assert not seeded[0]["handled"]


# ═════════════════════════════════════════════════════════════════════
# 处置收尾自动复位判定门（tasks 2.1）
# ═════════════════════════════════════════════════════════════════════


class TestResetGateHelper:
    """disposition_signal_hits_auto_reset 判定单元。"""

    def test_top_level_hit(self):
        assert disposition_signal_hits_auto_reset(
            {"signal_type": "verify_env_blocked"}
        )

    def test_underlying_hit(self):
        assert disposition_signal_hits_auto_reset(
            {"signal_type": "manual-intervention",
             "underlying_signal_type": "blocked_stuck"}
        )

    def test_neither_hit(self):
        assert not disposition_signal_hits_auto_reset(
            {"signal_type": "manual-intervention",
             "underlying_signal_type": "orphaned_state"}
        )
        assert not disposition_signal_hits_auto_reset({})
        assert not disposition_signal_hits_auto_reset(None)

    def test_missing_signal_field_is_none(self):
        """agent_runner 不可用等场景可能缺字段，None 不命中。"""
        assert not disposition_signal_hits_auto_reset(
            {"underlying_signal_type": None}
        )


class TestResetGateEndToEnd:
    """经 _invoke_administrator（真实调用点前置检查）的复位行为。"""

    def test_resolved_with_underlying_env_type_resets(self, tmp_path):
        """透传 verify_env_blocked 的手动唤起处置成功（resolved）→ 命中自动
        复位：无 branch → transition(ready)，error 清空，阻塞轮次不清零。"""
        sm = _FakeSM({"demo": _blocked_spec_entry()})
        runner = _FakeRunner(Disp(result="resolved", spec="demo"))
        monitor = _make_monitor(tmp_path, sm, runner)
        signal = {
            "signal_type": "manual-intervention",
            "underlying_signal_type": "verify_env_blocked",
            "spec": "demo",
            "severity": "major",
            "description": "人工呼叫",
        }

        monitor._invoke_administrator(signal, None)

        entry = sm.read_one("demo")
        assert entry["status"] == "ready"
        assert entry.get("error") is None
        # 业务侧车字段不清零（生命周期累计语义）
        assert int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0) == 2
        assert sm.transition_calls == [("demo", "ready")]
        assert sm.gate_calls == []  # ready 路径，非 testing 直通道

    def test_resolved_with_underlying_not_in_set_no_reset(self, tmp_path):
        """underlying=orphaned_state（不属自动复位集合）→ 不触发复位路径；
        顶层 manual-intervention 也不命中 orphaned_state 独立路径——行为与
        改造前一致。"""
        sm = _FakeSM({"demo": _blocked_spec_entry()})
        runner = _FakeRunner(Disp(result="resolved", spec="demo"))
        monitor = _make_monitor(tmp_path, sm, runner)
        signal = {
            "signal_type": "manual-intervention",
            "underlying_signal_type": "orphaned_state",
            "spec": "demo",
            "severity": "major",
        }

        monitor._invoke_administrator(signal, None)

        assert sm.read_one("demo")["status"] == "blocked"
        assert sm.transition_calls == []
        assert sm.gate_calls == []

    def test_escalated_result_never_resets_even_with_underlying_hit(
        self, tmp_path
    ):
        """escalated（升级人工）不复位——透传命中也不豁免该语义。"""
        sm = _FakeSM({"demo": _blocked_spec_entry()})
        runner = _FakeRunner(Disp(result="escalated", spec="demo", escalate=True))
        monitor = _make_monitor(tmp_path, sm, runner)
        signal = {
            "signal_type": "manual-intervention",
            "underlying_signal_type": "verify_env_blocked",
            "spec": "demo",
            "severity": "major",
        }

        monitor._invoke_administrator(signal, None)

        assert sm.read_one("demo")["status"] == "blocked"
        assert sm.transition_calls == []

    def test_store_records_stay_manual_intervention_across_two_invocations(
        self, tmp_path
    ):
        """两次手动唤起：disposition 落痕均按 manual-intervention 记录（透传
        字段不落入 store、不参与节流判定、不产生吞并），底层信号记录原样
        保留。"""
        sm = _FakeSM({"demo": _blocked_spec_entry()})
        runner = _FakeRunner(Disp(result="resolved", spec="demo"))
        monitor = _make_monitor(tmp_path, sm, runner)
        # 造一条未处置底层信号（模拟唤起前的真实困境记录）
        monitor.store.append({
            "kind": SIGNAL,
            "signal_type": "verify_env_blocked",
            "spec": "demo",
            "handled": False,
        })
        signal = {
            "signal_type": "manual-intervention",
            "underlying_signal_type": "verify_env_blocked",
            "spec": "demo",
            "severity": "major",
        }

        monitor._invoke_administrator(signal, None)
        monitor._invoke_administrator(signal, None)

        dispositions = [r for r in monitor.store.read_all()
                        if r.get("kind") == DISPOSITION]
        assert len(dispositions) == 2  # 两次唤起各留痕，未被节流吞并
        for rec in dispositions:
            assert rec["signal_type"] == "manual-intervention"
            assert "underlying_signal_type" not in rec  # 透传字段不入 store
        # 被反查的底层信号记录未被手动通道消费/改写
        seeded = [r for r in monitor.store.read_all() if r.get("kind") == SIGNAL]
        assert len(seeded) == 1
        assert seeded[0]["signal_type"] == "verify_env_blocked"
        assert not seeded[0]["handled"]


# ═════════════════════════════════════════════════════════════════════
# 写入端直传（fix-escalation-autoinvoke-passthrough）
# ═════════════════════════════════════════════════════════════════════


class TestRequestInvokePayload:

    def test_underlying_type_written_into_payload(self, tmp_path, monkeypatch):
        """underlying_signal_type 非空 → 随 payload 原子写入请求文件。"""
        from core.signals import request_admin_invoke

        monkeypatch.setattr(
            "core.dashboard.data.state.parse_state",
            lambda proot: {"myspec": {"status": "blocked"}},
        )
        result = request_admin_invoke(
            tmp_path, "myspec", underlying_signal_type="verify_env_blocked"
        )
        assert result["ok"] is True
        payload = json.loads(
            (tmp_path / ".fenix" / "admin_invoke_request.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["underlying_signal_type"] == "verify_env_blocked"
        assert payload["spec"] == "myspec"

    def test_underlying_type_absent_key_omitted(self, tmp_path, monkeypatch):
        """不传 underlying_signal_type（dashboard 纯人工唤起）→ payload 无该键。"""
        from core.signals import request_admin_invoke

        monkeypatch.setattr(
            "core.dashboard.data.state.parse_state",
            lambda proot: {"myspec": {"status": "blocked"}},
        )
        result = request_admin_invoke(tmp_path, "myspec", prompt="看看")
        assert result["ok"] is True
        payload = json.loads(
            (tmp_path / ".fenix" / "admin_invoke_request.json").read_text(
                encoding="utf-8"
            )
        )
        assert "underlying_signal_type" not in payload
        assert payload["prompt"] == "看看"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
