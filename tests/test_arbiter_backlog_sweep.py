"""add-arbiter-backlog-sweep 2.1：存量回扫触发面测试。

覆盖 tasks 1.1 / 1.2 / 2.1 判定面：
- 存量冻结回扫派发（evo-refine 型现场：frozen=true + 同 spec pending
  机器升级告警 → 经既有 dedup/单飞/预算管线入队派发）；
- 回扫排除语义三态：frozen_until 非空定时冻结 / frozen 但无成对 pending
  告警的人工冻结形态 / enabled=false（另有告警已处理与触发面外 signal
  的派生排除位）；
- 幂等：二次回扫不重复派发（同签名 dedup）、回扫与事件触发先后命中
  同签名不重复派发、跨重启（新 lane 实例 + 处置台账已记账）不重复派发；
- 回扫入口每进程每跃迁至多一次：启动回扫幂等短路 / 热更新 False→True
  跃迁恰一次、重复观测不重扫、True→False→True 第二条跃迁再恰一次；
- 消费预演（1.2，全新进程 import 链 + 回扫入口注册自检）。

worker 为 daemon 线程：确定性等待以 queue.unfinished_tasks 轮询（有界），
不做无界 sleep。测试全程不触网、不真调网关。
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.admin_store import AdminStore, ESCALATION
from core.pm_engine.arbiter import (
    ArbiterLane,
    arbiter_failure_signature,
    arbiter_report_path,
    load_arbiter_ledger,
    reset_lane,
)


# ── 夹具助手（与 test_arbiter_lane 同范式）────────────────

class FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, component, message, context=None):
        self.records.append(("info", component, message))

    def warning(self, component, message, context=None):
        self.records.append(("warning", component, message))

    def error(self, component, message, context=None):
        self.records.append(("error", component, message))


class FakeRunner:
    """调查 run 门面替身：_run_agent 按脚本写报告/抛异常。"""

    def __init__(self, project_root, script=None):
        self.project_root = Path(project_root)
        self.script = script or {}
        self.run_agent_calls = []
        self._run_harness = {}
        self.shutting_down = False

    def _build_prompt(self, spec, agent_type, detail=None):
        return f"prompt[{agent_type}/{spec}]"

    def _get_agent_model_assignment(self, agent_type):
        return None

    def _get_config(self, key, default=None):
        return default

    def _run_was_interrupted(self, run_file):
        return False

    def _record_signal_kill_or_label(self, spec, error, exit_code,
                                     framework_terminate=False):
        return error

    def _run_agent(self, prompt, project_root, run_id, model_override,
                   env_overrides, max_turns=300, spec_name=None, agent_type=None):
        self.run_agent_calls.append(run_id)
        action = self.script.get("run")
        if action == "raise":
            raise RuntimeError("gateway stall")
        report = action or {}
        path = arbiter_report_path(self.project_root, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        usage = {"input_tokens": 100, "output_tokens": 50,
                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        return ("", 1, None, usage, None)


class FakeStateMachine:
    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.unfreeze_calls = []

    def read_all(self):
        return dict(self.entries)

    def unfreeze_spec(self, spec_name, status=None, project_root=None,
                      worktree_manager=None):
        self.unfreeze_calls.append((spec_name, status))
        entry = dict(self.entries.get(spec_name) or {})
        entry["frozen"] = False
        if status:
            entry["status"] = status
        self.entries[spec_name] = entry
        return True

    def add_spec(self, spec_name, entry):
        if spec_name in self.entries:
            return False
        self.entries[spec_name] = dict(entry)
        return True


RESOLVED_REPORT = {
    "outcome": "resolved", "summary": "s", "root_cause": "root",
    "scene_snapshot": "snap", "forensic_timeline": [],
    "actions_taken": ["a1"], "evidence_refs": ["ref1"],
    "status_after": "ready",
}


def make_lane(tmp_path, config=None, runner=None, sm=None):
    lane = ArbiterLane(tmp_path, FakeLogger())
    lane.set_runner(runner or FakeRunner(tmp_path))
    lane.set_state_machine(sm or FakeStateMachine())
    if config is not None:
        lane.config = lambda: {
            "enabled": config.get("enabled", True),
            "budget_wallclock_s": config.get("budget_wallclock_s", 1800),
            "budget_tokens": config.get("budget_tokens", 1000000),
            "max_consecutive_failures": config.get(
                "max_consecutive_failures", 2),
        }
    return lane


def drain(lane, timeout_s=15.0):
    """确定性等待 worker 清空队列（有界轮询，不无界 sleep）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if lane._queue.unfinished_tasks == 0 and not lane._active:
            return True
        time.sleep(0.01)
    return False


def blocking_lane(tmp_path, **kw):
    """调查 run 挂起替身：触发入队后停在 in-flight（_active），直到放行。

    用于 dedup/单飞判定面——worker 毫秒级消费会把触发瞬间吃完，
    qsize/get_nowait 断言有竞态；本替身把「已派发未终态」变成可观测的
    确定状态，investigations 记录即真实派发数。
    """
    import threading

    lane = make_lane(tmp_path, **kw)
    gate = threading.Event()
    investigations = []

    def fake_investigation(trig):
        investigations.append(trig)
        gate.wait(timeout=15.0)
        return {"ok": True, "run_id": "blk", "report": dict(RESOLVED_REPORT),
                "budget": {}}

    lane._run_investigation = fake_investigation
    return lane, gate, investigations


def write_pending_alert(project_root, spec, signal_type="verify_env_blocked",
                        severity="critical", handled=False):
    """真实 AdminStore 写一条机器升级告警（freeze_for_human 成对告警形态）。"""
    store = AdminStore(project_root)
    rec = store.append({
        "kind": ESCALATION,
        "signal_type": signal_type,
        "spec": spec,
        "severity": severity,
        "description": f"verify escalation for {spec}",
        "evidence": "ev",
        "recommended_action": "investigate",
    })
    if handled:
        store.mark_handled(rec["id"])
    return rec


def evo_refine_entries(extra=None):
    """evo-refine-midflight-outlier-dims 型现场形态（白名单①类原型案）。"""
    entry = {"status": "blocked", "frozen": True, "error": "冻结（verify escalation）"}
    entry.update(extra or {})
    return {"evo-refine-midflight-outlier-dims": entry}


@pytest.fixture(autouse=True)
def _lane_cleanup():
    yield
    reset_lane()


# ── 存量冻结回扫派发（evo-refine 型现场）────────────────

class TestBacklogSweepDispatch:
    def test_frozen_with_pending_alert_dispatches(self, tmp_path):
        """frozen=true + 同 spec pending 机器升级告警 → 入队派发。"""
        write_pending_alert(tmp_path, "evo-refine-midflight-outlier-dims")
        runner = FakeRunner(tmp_path, script={"run": dict(RESOLVED_REPORT)})
        sm = FakeStateMachine(evo_refine_entries())
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        summary = lane.sweep_backlog(source="startup")
        assert summary["status"] == "ok"
        assert summary["scanned"] == 1
        assert summary["dispatched"] == [
            arbiter_failure_signature("evo-refine-midflight-outlier-dims",
                                      "verify_env_blocked")
        ]
        assert drain(lane)
        # 调查 run 消费走既有管线（单飞 worker 串行），台账落处置终态
        assert len(runner.run_agent_calls) == 1
        assert runner.run_agent_calls[0].startswith("arbiter-evo-refine-")
        recs = load_arbiter_ledger(tmp_path)
        assert recs and recs[-1]["kind"] == "disposition"

    def test_sweep_binds_existing_pending_alert(self, tmp_path):
        """回扫触发带 alert_id（原位挂靠目标），处置成功终态化原告警。"""
        rec = write_pending_alert(tmp_path, "spec-a")
        runner = FakeRunner(tmp_path, script={"run": dict(RESOLVED_REPORT)})
        lane = make_lane(tmp_path, runner=runner,
                         sm=FakeStateMachine({"spec-a": {"frozen": True}}))
        summary = lane.sweep_backlog()
        assert summary["dispatched"]
        assert drain(lane)
        store = AdminStore(tmp_path)
        alert = [r for r in store.read_all() if r.get("id") == rec["id"]][0]
        assert alert.get("resolved_by") == "arbiter"

    def test_sweep_respects_budget_config(self, tmp_path):
        """回扫触发携带预算（走既有预算管线，不另建派发路径）。"""
        write_pending_alert(tmp_path, "spec-a")
        lane = make_lane(
            tmp_path,
            config={"budget_wallclock_s": 60, "budget_tokens": 5000},
            sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        captured = {}
        lane._run_investigation = lambda trig: (
            captured.update(trig) or {
                "ok": True, "run_id": "x", "report": dict(RESOLVED_REPORT),
                "budget": {}}
        )
        summary = lane.sweep_backlog()
        assert summary["dispatched"]
        assert drain(lane)
        assert captured["budget"] == {"wallclock_s": 60, "tokens": 5000}
        assert captured["source"] == "backlog-sweep"

    def test_sweep_skips_unsafe_spec_name(self, tmp_path):
        """spec 名路径不安全（内插防御）跳过，不派发不抛异常。"""
        write_pending_alert(tmp_path, "../evil")
        lane = make_lane(
            tmp_path,
            sm=FakeStateMachine({"../evil": {"frozen": True}}),
        )
        summary = lane.sweep_backlog()
        assert summary["dispatched"] == []
        assert lane._queue.qsize() == 0


# ── 回扫排除语义 ────────────────────────────────────────

class TestBacklogSweepExclusions:
    def test_frozen_until_scheduled_freeze_excluded(self, tmp_path):
        """frozen_until 非空定时冻结：scheduled-unfreeze 自愈在先，不回扫。"""
        write_pending_alert(tmp_path, "spec-a")
        lane = make_lane(
            tmp_path,
            sm=FakeStateMachine({
                "spec-a": {"frozen": True,
                           "frozen_until": "2026-11-01T00:00:00+00:00"},
            }),
        )
        summary = lane.sweep_backlog()
        assert summary["scanned"] == 0
        assert lane._queue.qsize() == 0

    def test_manual_freeze_shape_excluded(self, tmp_path):
        """frozen=true 但无成对 pending 告警（人工冻结形态）：不回扫。"""
        lane = make_lane(
            tmp_path,
            sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        summary = lane.sweep_backlog()
        assert summary["scanned"] == 0
        assert lane._queue.qsize() == 0

    def test_handled_alert_excluded(self, tmp_path):
        """成对告警已被处理（handled=true）：不再回扫派发。"""
        write_pending_alert(tmp_path, "spec-a", handled=True)
        lane = make_lane(
            tmp_path,
            sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        assert lane.sweep_backlog()["scanned"] == 0

    def test_out_of_surface_signal_excluded(self, tmp_path):
        """pending 告警 signal_type 在触发面白名单外：不回扫（留 narrative）。"""
        write_pending_alert(tmp_path, "spec-a", signal_type="impl_budget_exhausted")
        lane = make_lane(
            tmp_path,
            sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        assert lane.sweep_backlog()["scanned"] == 0

    def test_not_frozen_excluded(self, tmp_path):
        """有 pending 告警但 spec 未冻结：不回扫。"""
        write_pending_alert(tmp_path, "spec-a")
        lane = make_lane(tmp_path, sm=FakeStateMachine(
            {"spec-a": {"status": "ready", "frozen": False}}))
        assert lane.sweep_backlog()["scanned"] == 0

    def test_disabled_no_op(self, tmp_path):
        """enabled=false：回扫零扫描零派发零写入。"""
        write_pending_alert(tmp_path, "spec-a")
        lane = make_lane(
            tmp_path,
            config={"enabled": False},
            sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        summary = lane.sweep_backlog()
        assert summary["status"] == "disabled"
        assert lane._queue.qsize() == 0
        assert load_arbiter_ledger(tmp_path) == []


# ── 回扫幂等 ────────────────────────────────────────────

class TestBacklogSweepIdempotence:
    def test_second_sweep_same_signature_no_redispatch(self, tmp_path):
        """二次回扫：首个触发仍在飞/排队 → 同签名 dedup，不重复派发。"""
        write_pending_alert(tmp_path, "spec-a")
        lane, gate, investigations = blocking_lane(
            tmp_path, sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        first = lane.sweep_backlog()
        assert len(first["dispatched"]) == 1
        deadline = time.monotonic() + 5.0
        while not investigations and time.monotonic() < deadline:
            time.sleep(0.01)  # 等首个触发出队在飞（有界）
        second = lane.sweep_backlog()
        assert second["dispatched"] == []
        assert second["deduped"] == first["dispatched"]
        gate.set()
        assert drain(lane)
        assert len(investigations) == 1  # 全程只一次调查

    def test_sweep_vs_event_trigger_no_double_dispatch(self, tmp_path):
        """回扫与事件触发先后命中同签名：不产生第二次派发。"""
        write_pending_alert(tmp_path, "spec-a")
        runner = FakeRunner(tmp_path, script={"run": dict(RESOLVED_REPORT)})
        lane = make_lane(tmp_path, runner=runner,
                         sm=FakeStateMachine({"spec-a": {"frozen": True}}))
        assert len(lane.sweep_backlog()["dispatched"]) == 1
        # 事件触发（告警咽喉形态）后到：同签名 dedup 只补绑不派发
        outcome = lane.submit_for_alert(
            None, {"spec": "spec-a", "signal_type": "verify_env_blocked"},
            "alert-late",
        )
        assert outcome == "deduped"
        assert drain(lane)
        assert len(runner.run_agent_calls) == 1

    def test_sweep_after_restart_no_redispatch(self, tmp_path):
        """跨重启幂等：新 lane（进程内存 dedup 清空）+ 台账已记账 → 不再派发。

        模拟：上一进程回扫派发 → 调查终态（升级）落台账 → 重启后新 lane
        再回扫——签名已在既有处置台账，回扫不重复派发（不另记回扫簿，
        台账即持久幂等层）。
        """
        write_pending_alert(tmp_path, "spec-a")
        runner = FakeRunner(tmp_path, script={"run": {
            "outcome": "escalate", "summary": "s", "root_cause": "r",
            "scene_snapshot": "snap", "forensic_timeline": [],
            "evidence_refs": ["x"], "recommended_action": "ask human"}})
        first = make_lane(tmp_path, runner=runner,
                          sm=FakeStateMachine({"spec-a": {"frozen": True}}))
        assert len(first.sweep_backlog()["dispatched"]) == 1
        assert drain(first)
        kinds = [r["kind"] for r in load_arbiter_ledger(tmp_path)]
        assert "escalation" in kinds
        # 重启：全新 lane 实例（内存 dedup/单飞集合全空）
        runner2 = FakeRunner(tmp_path, script={"run": dict(RESOLVED_REPORT)})
        second = make_lane(tmp_path, runner=runner2,
                           sm=FakeStateMachine({"spec-a": {"frozen": True}}))
        summary = second.sweep_backlog(source="startup")
        assert summary["scanned"] == 0  # 台账命中 → 候选阶段即剔除
        assert summary["dispatched"] == []
        assert drain(second)
        assert runner2.run_agent_calls == []


# ── 回扫入口每进程每跃迁至多一次 ────────────────────────

class TestSweepEntryOncePerTransition:
    def test_startup_sweep_once_then_short_circuit(self, tmp_path):
        """启动回扫每进程至多一次：重复调用幂等短路。"""
        write_pending_alert(tmp_path, "spec-a")
        lane, gate, investigations = blocking_lane(
            tmp_path, sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        first = lane.sweep_on_startup()
        assert first["status"] == "ok" and len(first["dispatched"]) == 1
        second = lane.sweep_on_startup()
        assert second["status"] == "already-swept"
        gate.set()
        assert drain(lane)
        assert len(investigations) == 1

    def test_startup_disabled_primes_baseline_only(self, tmp_path):
        """启动时 disabled：只落跃迁基线零扫描（后续跃迁观察以此为起点）。"""
        write_pending_alert(tmp_path, "spec-a")
        lane = make_lane(
            tmp_path,
            config={"enabled": False},
            sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        assert lane.sweep_on_startup()["status"] == "disabled"
        assert drain(lane)
        assert lane._queue.unfinished_tasks == 0

    def test_hot_reload_transition_sweeps_exactly_once(self, tmp_path):
        """disabled→enabled 跃迁恰回扫一次；重复观测/稳态不重扫。"""
        write_pending_alert(tmp_path, "spec-a")
        lane, gate, investigations = blocking_lane(
            tmp_path, config={"enabled": False},
            sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        lane.sweep_on_startup()  # 基线 False
        lane.config = lambda: {
            "enabled": True, "budget_wallclock_s": 1800,
            "budget_tokens": 1000000, "max_consecutive_failures": 2,
        }
        first = lane.observe_enabled_transition()
        assert first["status"] == "ok" and len(first["dispatched"]) == 1
        # 稳态 enabled 重复观测：无跃迁不重扫
        again = lane.observe_enabled_transition()
        assert again["status"] == "no-transition"
        gate.set()
        assert drain(lane)
        assert len(investigations) == 1

    def test_each_transition_sweeps_at_most_once(self, tmp_path):
        """True→False→True 第二条跃迁再恰一次（每条跃迁至多一次）。"""
        write_pending_alert(tmp_path, "spec-a")
        lane, gate, investigations = blocking_lane(
            tmp_path, config={"enabled": True},
            sm=FakeStateMachine({"spec-a": {"frozen": True}}),
        )
        lane.sweep_on_startup()  # 基线 True，启动回扫
        lane.config = lambda: {
            "enabled": False, "budget_wallclock_s": 1800,
            "budget_tokens": 1000000, "max_consecutive_failures": 2,
        }
        down = lane.observe_enabled_transition()
        assert down["status"] == "no-transition"
        lane.config = lambda: {
            "enabled": True, "budget_wallclock_s": 1800,
            "budget_tokens": 1000000, "max_consecutive_failures": 2,
        }
        up = lane.observe_enabled_transition()
        # 首个触发仍 in-flight（gate 未放行）→ 第二条跃迁同签名 dedup，
        # 不产生第二次派发；每条跃迁各自至多回扫一次（返回形态可判）
        assert up["status"] == "ok"
        assert up["dispatched"] == [] and len(up["deduped"]) == 1
        gate.set()
        assert drain(lane)
        assert len(investigations) == 1


# ── 消费预演（1.2，全新进程 import 链 + 回扫入口注册自检）──

class TestConsumptionRehearsal:
    def test_fresh_process_import_chain_and_sweep_registration(self):
        """全新进程：import 链 + 回扫入口/接线/重启信号自检断言全绿。"""
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[1]
        code = f"""
import json, sys
sys.path.insert(0, {json.dumps(str(root))})
import core.agent_runner.runner  # 门面链
import core.agent_runner.maintenance_runs as mr
import core.pm_engine.arbiter as arb
import core.pm_engine.engine as engine_mod
import core.state_machine as sm
import core.admin_store as admin_store
from core.pm_engine.arbiter import ArbiterLane, arbiter_failure_signature
# 回扫入口注册面
assert hasattr(ArbiterLane, "sweep_on_startup")
assert hasattr(ArbiterLane, "sweep_backlog")
assert hasattr(ArbiterLane, "observe_enabled_transition")
assert hasattr(ArbiterLane, "_backlog_candidates")
assert hasattr(ArbiterLane, "_pending_machine_alerts")
# 启动装配接线（PMEngine.__init__ 源内含启动回扫调用）
import inspect
src = inspect.getsource(engine_mod.PMEngine.__init__)
assert "sweep_on_startup()" in src
# 热更新跃迁接线（fenixd 主循环热更新源内含跃迁观察调用）
fenixd_src = open({json.dumps(str(root / "fenixd.py"))}, encoding="utf-8").read()
assert "observe_enabled_transition()" in fenixd_src
assert "arbiter_failure_signature" in arb.__dict__
sig = arbiter_failure_signature("s", "verify_env_blocked")
assert sig == "s::verify_env_blocked"
# restart_request 信号为运行时瞬时产物（supervisor 消费即删除）——不进
# 常驻断言（2026-11-01：曾断言根路径文件存在，消费后永久失败=时间炸弹）
print("REHEARSAL-OK")
"""
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert "REHEARSAL-OK" in proc.stdout


# ── 机器证据三半边（2026-11-01 修复：告警半边随生命周期衰减）────────
# 实证：evo-refine 存量冻结的 escalation 告警已被告警生命周期自愈收口
# （handled=True），「frozen ∧ pending 告警」判据对陈旧欠账恒空转。
# 机器证据补两半：咽喉持久标记（freeze_for_human 写 _frozen_source/
# _frozen_signal_type）+ 遗留菜单文案回填（标记上线前的存量标本）。

class TestMachineEvidenceBackfill:
    def test_aged_alert_with_legacy_menu_error_swept(self, tmp_path):
        """告警已衰减（handled=True）+ 遗留机器冻结菜单文案 → 仍回扫。

        evo-refive 型陈旧欠账：冻结长期挂着，配对告警早被生命周期收口。
        """
        spec = "evo-refine-midflight-outlier-dims"
        write_pending_alert(tmp_path, spec, handled=True)  # 已衰减
        entries = evo_refine_entries(extra={
            "error": ("用户指令冻结：场景计划争议连续 2 轮，admin 处置未奏效，"
                      "转人工 — 冻结场景文件损坏或验收失败。处置选项：① 确认"
                      "场景集已过时 → 删除 test_scenarios.json 批准重新出题"),
        })
        runner = FakeRunner(tmp_path, script={"run": dict(RESOLVED_REPORT)})
        lane = make_lane(tmp_path, runner=runner, sm=FakeStateMachine(entries))
        summary = lane.sweep_backlog(source="startup")
        assert summary["dispatched"] == [
            arbiter_failure_signature(spec, "verify_env_blocked")
        ]
        assert drain(lane)

    def test_frozen_source_marker_swept_without_alert(self, tmp_path):
        """_frozen_source=machine 持久标记 → 无告警也回扫（管未来新冻结）。"""
        runner = FakeRunner(tmp_path, script={"run": dict(RESOLVED_REPORT)})
        lane = make_lane(tmp_path, runner=runner, sm=FakeStateMachine({
            "spec-a": {"status": "blocked", "frozen": True,
                       "_frozen_source": "machine",
                       "_frozen_signal_type": "blocked_stuck"},
        }))
        summary = lane.sweep_backlog()
        assert summary["dispatched"] == [
            arbiter_failure_signature("spec-a", "blocked_stuck")
        ]
        assert drain(lane)

    def test_human_freeze_form_excluded(self, tmp_path):
        """人工冻结形态（无告警/无标记/无菜单文案）→ 不回扫。"""
        runner = FakeRunner(tmp_path, script={"run": dict(RESOLVED_REPORT)})
        lane = make_lane(tmp_path, runner=runner, sm=FakeStateMachine({
            "spec-a": {"status": "blocked", "frozen": True,
                       "error": "用户指令冻结：人工暂停观察"},
        }))
        summary = lane.sweep_backlog()
        assert summary["dispatched"] == []
        assert drain(lane) is not None  # 队列空，无 run

    def test_throat_writes_machine_marker_and_unfreeze_clears(self, tmp_path):
        """freeze_for_human 咽喉写持久标记；unfreeze 清理；freeze_spec 不写。"""
        from core.state_machine import StateMachine
        state = tmp_path / ".fenix" / "STATE.md"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("# Fenix Project State\n## Specs\n", encoding="utf-8")
        sm = StateMachine(state, MagicMock())
        sm.add_spec("spec-a", {"status": "testing"})
        assert sm.freeze_for_human(
            "spec-a", error="e（原状态 testing）", signal_type="verify_env_blocked",
            severity="critical", description="d", evidence="e",
            recommended_action="r", alert_callback=None,
        ) is True
        entry = sm.read_all()["spec-a"]
        assert entry.get("_frozen_source") == "machine"
        assert entry.get("_frozen_signal_type") == "verify_env_blocked"
        # 人工冻结路径不写标记
        sm.add_spec("spec-b", {"status": "implementing"})
        sm.freeze_spec("spec-b", reason="人工暂停")
        assert sm.read_all()["spec-b"].get("_frozen_source") is None
        # 解冻清理标记（防 machine→人工 重冻结被误判）
        assert sm.unfreeze_spec("spec-a", status="testing") is True
        assert sm.read_all()["spec-a"].get("_frozen_source") is None
