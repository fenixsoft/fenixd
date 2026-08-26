"""admin_store / admin_monitor / run_administrator / Dashboard alerts API 测试。

对应 openspec/changes/add-administrator-agent 的 tasks 4.1-4.3。
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.admin_store import AdminStore, SIGNAL, ESCALATION, DISPOSITION
from core.admin_monitor import AdminMonitor
from core.agent_runner import AdminDisposition, AgentRunner
from core.dashboard.registry import Registry
from core.dashboard.server import DashboardHTTPServer, find_free_port


# ── 辅助 ────────────────────────────────────────────────

def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def iso_ago(minutes: float) -> str:
    return datetime.fromtimestamp(time.time() - minutes * 60, tz=timezone.utc).isoformat()


class FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        return AdminDisposition(
            run_id="admin-test-1",
            spec=signal.get("spec"),
            success=True,
            problem=signal.get("description", ""),
            actions_taken="测试处置",
            result="resolved",
            summary="诊断结论：测试困境；处置时间线：测试处置；结果：已解决。",
        )


def make_runs(proot: Path, entries: list):
    """写入 run 产物文件；entries: [(run_id, terminal)]，terminal in (error/done/running)。"""
    runs_dir = proot / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for run_id, terminal in entries:
        lines = []
        if terminal == "error":
            lines.append({"type": "system", "subtype": "init"})
            lines.append({"type": "error", "message": "boom", "num_turns": 3})
        elif terminal == "done":
            lines.append({"type": "system", "subtype": "init"})
            lines.append({"type": "result", "result": "完成", "num_turns": 3})
        else:  # running
            lines.append({"type": "assistant",
                          "message": {"content": [{"type": "text", "text": "..."}]}})
        (runs_dir / f"{run_id}.jsonl").write_text(
            "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
            encoding="utf-8",
        )


def make_monitor(tmp_path, specs: dict, config=None, runner=None):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    mon = AdminMonitor(
        config or {},
        FakeSM(specs),
        proot,
        FakeLogger(),
        store=AdminStore(proot, FakeLogger()),
        agent_runner=runner,
    )
    return proot, mon


# ── 4.2 admin_store 读写 + 标记已处理 ───────────────────



class TestAdminStore:
    def test_append_fills_defaults(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        rec = store.append({"kind": ESCALATION, "description": "x"})
        assert rec["id"]
        assert rec["created"]
        assert rec["handled"] is False
        assert rec["handled_at"] is None
        assert rec["severity"] == "major"
        assert rec["spec"] is None

    def test_read_all_newest_first(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck", "description": "first"})
        time.sleep(0.01)
        store.append({"kind": ESCALATION, "signal_type": "stuck", "description": "second"})
        recs = store.read_all()
        assert len(recs) == 2
        assert recs[0]["description"] == "second"  # 最新的在前

    def test_unhandled_only_escalations(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck"})
        esc = store.append({"kind": ESCALATION, "signal_type": "stuck"})
        store.append({"kind": DISPOSITION, "signal_type": "stuck"})
        un = store.unhandled()
        assert len(un) == 1
        assert un[0]["id"] == esc["id"]

    def test_mark_handled(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        esc = store.append({"kind": ESCALATION, "signal_type": "stuck"})
        assert store.mark_handled(esc["id"]) is True
        assert store.unhandled() == []
        recs = store.read_all()
        assert recs[0]["handled"] is True
        assert recs[0]["handled_at"]
        # 重复标记返回 False
        assert store.mark_handled(esc["id"]) is False

    def test_mark_handled_ignores_non_escalation(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        sig = store.append({"kind": SIGNAL, "signal_type": "stuck"})
        assert store.mark_handled(sig["id"]) is False

    def test_latest_signal_within_window(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck", "spec": "s1"})
        assert store.latest_signal("s1", "stuck", 15) is not None
        assert store.latest_signal("s1", "stuck", 0) is None        # 冷却关闭
        assert store.latest_signal("s2", "stuck", 15) is None       # 其它 spec
        assert store.latest_signal(None, "stuck", 15) is None       # 该信号带 spec，不匹配 daemon 级

    def test_latest_signal_old_record_ignored(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck", "spec": "s1",
                      "created": iso_ago(60)})  # append 保留显式 created
        assert store.latest_signal("s1", "stuck", 15) is None

    def test_corrupt_file_returns_empty(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck"})
        (tmp_path / ".fenix" / "admin_alerts.json").write_text("not json{", encoding="utf-8")
        assert store.read_all() == []
        assert store.unhandled() == []

    def test_unhandled_for_matches_spec_and_type(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "s1"})
        assert store.unhandled_for("s1", "stuck") is not None
        assert store.unhandled_for("s2", "stuck") is None
        assert store.unhandled_for("s1", "flapping") is None


# ── 4.1 admin_monitor 检测规则 ──────────────────────────

class TestAdminMonitorDetection:
    def test_repeated_failures(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        make_runs(proot, [
            ("impl-spec-a-1780000001", "error"),
            ("impl-spec-a-1780000002", "error"),
            ("impl-spec-a-1780000003", "error"),
            ("impl-spec-a-1780000000", "done"),  # 成功 run 不计数
        ])
        signals = mon.run_once()
        sig = next((s for s in signals if s["signal_type"] == "repeated_failures"), None)
        assert sig is not None
        assert sig["spec"] == "spec-a"

    def test_repeated_failures_below_threshold(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        make_runs(proot, [
            ("impl-spec-a-1780000001", "error"),
            ("impl-spec-a-1780000002", "error"),
        ])
        signals = mon.run_once()
        assert all(s["signal_type"] != "repeated_failures" for s in signals)

    def test_flapping(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        # 预写历史：10 分钟窗口内 4 次 ready↔implementing 变更（3 次切换）
        hist = proot / ".fenix" / "admin_state_history.json"
        hist.parent.mkdir(parents=True, exist_ok=True)
        base = time.time()
        changes = [
            [base - 500, "ready"], [base - 400, "implementing"],
            [base - 300, "ready"], [base - 200, "implementing"],
        ]
        hist.write_text(json.dumps(
            {"spec-a": {"last_status": "implementing", "changes": changes}}), encoding="utf-8")
        signals = mon.run_once()
        assert any(s["signal_type"] == "flapping" for s in signals)

    def test_stuck(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},  # 2 小时无进展
        })
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_stuck_skipped_with_recent_progress(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        })
        make_runs(proot, [("impl-spec-a-1780000000", "running")])  # 最近有 run 活动
        signals = mon.run_once()
        assert all(s["signal_type"] != "stuck" for s in signals)

    def test_merge_streak(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "ready", "updated": utcnow_iso(), "_merge_streak": 3},
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},  # 触发检测前置条件
        })
        signals = mon.run_once()
        assert any(s["signal_type"] == "merge_streak" for s in signals)

    def test_blocked_stuck(self, tmp_path):
        """blocked 超时未处理 → 唤起 admin（fix-admin-self-heal）。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "blocked", "updated": iso_ago(40)},
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},  # 触发检测前置条件
        })
        signals = mon.run_once()
        assert any(s["signal_type"] == "blocked_stuck" for s in signals)

    def test_blocked_recent_not_detected(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "blocked", "updated": utcnow_iso()},  # 刚 blocked
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        })
        signals = mon.run_once()
        assert all(s["signal_type"] != "blocked_stuck" for s in signals)

    def test_daemon_errors(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        log_dir = proot / ".fenix" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "fenixd.log").write_text(
            json.dumps({"level": "INFO", "message": "ok"}) + "\n"
            + "".join(json.dumps({"level": "ERROR", "message": f"e{i}"}) + "\n" for i in range(4)),
            encoding="utf-8",
        )
        signals = mon.run_once()
        assert any(s["signal_type"] == "daemon_errors" for s in signals)

    def test_healthy_no_signal(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        make_runs(proot, [("impl-spec-a-1780000000", "running")])
        signals = mon.run_once()
        assert signals == []

    def test_no_in_progress_skips(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "done", "updated": utcnow_iso()},
        })
        make_runs(proot, [("impl-spec-a-1780000001", "error")])
        signals = mon.run_once()
        assert signals == []

    def test_disabled_monitor_no_action(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, config={"admin": {"enabled": False}})
        assert mon.enabled is False
        assert mon.run_once() == []


# ── 4.1 节流 / 冷却 ─────────────────────────────────────

class TestAdminMonitorThrottle:
    def test_throttle_prevents_repeated_invoke(self, tmp_path):
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon.run_once()
        assert len(runner.calls) == 1
        # 同信号在冷却窗口内：第二次只记录、不再唤起
        mon.run_once()
        assert len(runner.calls) == 1

    def test_unhandled_escalation_suppresses_invoke(self, tmp_path):
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon.store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "spec-a"})
        mon.run_once()
        assert runner.calls == []

    def test_no_runner_escalates(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=None)
        mon.run_once()
        un = mon.store.unhandled()
        assert len(un) == 1
        assert un[0]["kind"] == ESCALATION
        assert un[0]["recommended_action"]

    def test_disposition_recorded_after_invoke(self, tmp_path):
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon.run_once()
        kinds = [r["kind"] for r in mon.store.read_all()]
        assert DISPOSITION in kinds
        disp = next(r for r in mon.store.read_all() if r["kind"] == DISPOSITION)
        assert disp["result"] == "resolved"
        assert disp["admin_run_id"] == "admin-test-1"

    def test_disposition_recorded_with_summary(self, tmp_path):
        """_invoke_administrator 把 disp.summary 透传到 admin_alerts.json 的处置记录。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(120)},
        }, runner=runner)
        mon.run_once()
        disp = next(r for r in mon.store.read_all() if r["kind"] == DISPOSITION)
        assert disp["summary"] == "诊断结论：测试困境；处置时间线：测试处置；结果：已解决。"


# ── run_administrator：处置文件读取 + 陈旧清理 ──────────

class TestRunAdministrator:
    def test_run_administrator_writes_pending_disposition(self, tmp_path):
        """唤起前落 pending disposition，保证 admin 被杀也有记录（fix-admin-self-heal）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._build_prompt = lambda *a, **k: "prompt"

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns):
            return "output", 5, "sess"

        runner._run_claude = fake_run_claude
        runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})
        recs = AdminStore(proot, FakeLogger()).read_all()
        pendings = [r for r in recs if r.get("kind") == DISPOSITION and r.get("status") == "pending"]
        assert len(pendings) == 1
        assert pendings[0]["spec"] == "spec-a"
        assert pendings[0]["admin_run_id"].startswith("admin-spec-a-")

    def test_orphaned_pending_escalates(self, tmp_path):
        """pending disposition 超时无最终结果 → 升级人工（admin 被 kill 场景）。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-1",
        })
        # 把 created 改成 20 分钟前（超过 cooldown 15m）
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")
        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 1
        assert "处置中断" in esc[0]["description"]

    def test_orphaned_pending_with_interrupted_marker_resolved_no_escalation(self, tmp_path):
        """run 含 interrupted 标记 + pending 超时 → 终结且不升级人工（已知 daemon 中断）。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-1",
        })
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")

        # 写入含 interrupted 标记的 run 文件（agent_runner 关闭时写入）
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "runs" / "admin-spec-a-1.jsonl").write_text(
            json.dumps({"type": "assistant", "message": {"content": []}}) + "\n"
            + json.dumps({"type": "interrupted", "reason": "daemon shutdown",
                          "by": "agent_runner"}) + "\n",
            encoding="utf-8",
        )

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 0  # 不升级人工
        # 应追加 interrupted 终结记录
        assert any(r.get("admin_run_id") == "admin-spec-a-1"
                   and (r.get("status") or r.get("result")) == "interrupted"
                   for r in recs)

    def test_orphaned_pending_without_marker_escalates(self, tmp_path):
        """run 无 interrupted 标记（文件缺失）→ 维持升级兜底。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-2",
        })
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")
        # 不写 run 文件 → 无证据 → 升级兜底

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 1  # 升级人工
        # 升级同时追加终结记录（防循环告警）
        assert any(r.get("admin_run_id") == "admin-spec-a-2"
                   and (r.get("status") or r.get("result")) == "escalated"
                   for r in recs)

    def test_orphaned_pending_marker_preempts_re_escalation(self, tmp_path):
        """interrupted 终结后下轮巡检不再处理（终结即 final，去重）。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-3",
        })
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "runs" / "admin-spec-a-3.jsonl").write_text(
            json.dumps({"type": "interrupted", "reason": "daemon shutdown",
                        "by": "agent_runner"}) + "\n",
            encoding="utf-8",
        )

        mon._recover_orphaned_dispositions()  # 第一次：终结不升级
        mon._recover_orphaned_dispositions()  # 第二次：已终结，跳过
        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 0
        interrupted = [r for r in recs if (r.get("status") or r.get("result")) == "interrupted"]
        assert len(interrupted) == 1  # 终结只发生一次

    def test_pending_with_final_result_not_escalated(self, tmp_path):
        """有最终结果的 pending 不升级。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        store = AdminStore(proot, FakeLogger())
        store.append({"kind": DISPOSITION, "status": "pending", "result": "pending",
                      "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-x"})
        store.append({"kind": DISPOSITION, "status": "done", "result": "resolved",
                      "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-x"})
        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        assert not any(r.get("kind") == ESCALATION for r in recs)

    def test_escalated_orphan_not_re_escalated(self, tmp_path):
        """孤儿升级人工后不再重复升级（升级即终结，避免循环告警）。

        回归：add-hierarchical-config 孤儿 run 因升级不终结 pending，escalation
        被 handled 后每次巡检又生成新升级，导致同一条告警反复出现。
        """
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-1",
        })
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")

        mon._recover_orphaned_dispositions()
        # 模拟人工已处理该升级（handled 后 unhandled_for 节流失效，循环 bug 触发点）
        esc = [r for r in store.read_all() if r.get("kind") == ESCALATION]
        assert len(esc) == 1
        assert store.mark_handled(esc[0]["id"]) is True
        mon._recover_orphaned_dispositions()  # 再次巡检：不得重复升级
        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 1  # 升级只发生一次
        # 升级应终结 pending：同 run 存在非 pending 记录
        rid = rec["admin_run_id"]
        assert any(r.get("admin_run_id") == rid and (r.get("status") or r.get("result")) != "pending"
                   for r in recs)

    def test_restart_request_failure_escalates(self, tmp_path):
        """restart_request 过期未清除 → 重启失败 → 升级人工。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        rr = proot / ".fenix" / "restart_request"
        rr.parent.mkdir(parents=True, exist_ok=True)
        rr.write_text("restart", encoding="utf-8")
        os.utime(rr, (time.time() - 60 * 30, time.time() - 60 * 30))  # 30 分钟前
        result = mon._detect_restart_failure(time.time())
        assert result == ["restart_failed"]
        recs = AdminStore(proot, FakeLogger()).read_all()
        assert any(r.get("kind") == ESCALATION and r.get("signal_type") == "restart_failed"
                   for r in recs)

    def test_restart_request_fresh_not_escalated(self, tmp_path):
        """restart_request 刚发出（窗口内）不升级。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        })
        rr = proot / ".fenix" / "restart_request"
        rr.parent.mkdir(parents=True, exist_ok=True)
        rr.write_text("restart", encoding="utf-8")  # mtime = now
        assert mon._detect_restart_failure(time.time()) == []

    def test_clear_stale_disposition(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        disp_path = proot / ".fenix" / "admin_disposition.json"
        disp_path.write_text(json.dumps({"spec": "old", "result": "stale"}), encoding="utf-8")
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._clear_admin_disposition()
        assert not disp_path.exists()

    def test_run_administrator_reads_disposition(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._build_prompt = lambda *a, **k: "prompt"

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns):
            (proot / ".fenix" / "admin_disposition.json").write_text(json.dumps({
                "spec": "spec-a",
                "problem": "卡死",
                "actions_taken": ["kill", "reset"],
                "result": "resolved",
                "escalate": False,
            }), encoding="utf-8")
            return "output", 5, "sess"

        runner._run_claude = fake_run_claude
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.success is True
        assert disp.actions_taken == "kill\nreset"
        assert disp.result == "resolved"
        assert disp.escalate is False
        assert disp.spec == "spec-a"

    def test_run_administrator_passes_summary(self, tmp_path):
        """admin_disposition 的 summary 透传到 AdminDisposition（叙述总结）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._build_prompt = lambda *a, **k: "prompt"
        summary = "根因是工作树状态陈旧；已清理并重新调度；无需人工介入。"

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns):
            (proot / ".fenix" / "admin_disposition.json").write_text(json.dumps({
                "spec": "spec-a",
                "problem": "卡死",
                "actions_taken": ["clean", "reset"],
                "result": "resolved",
                "escalate": False,
                "summary": summary,
            }), encoding="utf-8")
            return "output", 5, "sess"

        runner._run_claude = fake_run_claude
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.summary == summary

    def test_run_administrator_summary_default_empty(self, tmp_path):
        """旧处置文件无 summary → AdminDisposition.summary 为空字符串（不报错）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._build_prompt = lambda *a, **k: "prompt"

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns):
            (proot / ".fenix" / "admin_disposition.json").write_text(json.dumps({
                "spec": "spec-a", "result": "resolved",
            }), encoding="utf-8")
            return "output", 5, "sess"

        runner._run_claude = fake_run_claude
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.summary == ""

    def test_read_admin_disposition_summary_normalized(self, tmp_path):
        """_read_admin_disposition 把列表/非字符串 summary 归一化为字符串。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        disp_path = proot / ".fenix" / "admin_disposition.json"
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot

        # 列表 → 用换行符拼接（每条独立一行，design D5）
        disp_path.write_text(json.dumps({
            "summary": ["诊断：根因是构建缓存损坏", "处置：清理缓存", "结果：恢复"],
        }), encoding="utf-8")
        assert runner._read_admin_disposition()["summary"] == "诊断：根因是构建缓存损坏\n处置：清理缓存\n结果：恢复"

        # 缺失 → 空字符串
        disp_path.write_text(json.dumps({"actions_taken": "x"}), encoding="utf-8")
        assert runner._read_admin_disposition()["summary"] == ""

        # 非字符串 → str 化
        disp_path.write_text(json.dumps({"summary": 123}), encoding="utf-8")
        assert runner._read_admin_disposition()["summary"] == "123"

        # 损坏文件 → 空 dict（调用方兜底）
        disp_path.write_text("not json{", encoding="utf-8")
        assert runner._read_admin_disposition() == {}

    def test_run_administrator_failure_falls_back(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._build_prompt = lambda *a, **k: "prompt"

        def failing_run_claude(*a, **k):
            raise RuntimeError("claude 崩溃")

        runner._run_claude = failing_run_claude
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.success is False
        assert "claude 崩溃" in disp.error
        # 失败时无处置文件 → 用信号详情兜底
        assert disp.problem == "卡死"

    def test_run_administrator_injects_provider_env_when_assigned(self, tmp_path):
        """agents.models.administrator 已分配 → --model 用分配模型并注入 provider env（直连）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: (
            {"name": "volc", "baseurl": "https://v.com", "apikey": "sk-v"},
            "deepseek-v4-flash",
        ) if agent_type == "administrator" else None
        runner._build_prompt = lambda *a, **k: "prompt"

        captured = {}
        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns):
            captured["model"] = model_override
            captured["env"] = env_overrides
            (proot / ".fenix" / "admin_disposition.json").write_text(
                json.dumps({"spec": "spec-a", "result": "resolved"}), encoding="utf-8")
            return "output", 5, "sess"

        runner._run_claude = fake_run_claude
        runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})
        assert captured["model"] == "deepseek-v4-flash"
        assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://v.com"
        assert captured["env"]["ANTHROPIC_API_KEY"] == "sk-v"
        assert captured["env"]["ANTHROPIC_MODEL"] == "deepseek-v4-flash"
        assert "CLAUDE_CONFIG_DIR" in captured["env"]

    def test_run_administrator_legacy_fallback_when_unassigned(self, tmp_path):
        """未分配 administrator → 走 admin.agent_model → 默认网关，不注入 provider env。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-opus-4"
        runner._get_agent_model_assignment = lambda agent_type: None
        runner._build_prompt = lambda *a, **k: "prompt"

        captured = {}
        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns):
            captured["model"] = model_override
            captured["env"] = env_overrides
            (proot / ".fenix" / "admin_disposition.json").write_text(
                json.dumps({"spec": "spec-a", "result": "resolved"}), encoding="utf-8")
            return "output", 5, "sess"

        runner._run_claude = fake_run_claude
        runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})
        assert captured["model"] == "claude-opus-4"
        assert "ANTHROPIC_BASE_URL" not in captured["env"]
        assert "ANTHROPIC_API_KEY" not in captured["env"]


# ── 4.3 Dashboard alerts API ────────────────────────────

class _AlertTestServer:
    def __init__(self, reg, static_dir):
        self.port = find_free_port(30000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), reg, static_dir)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def post(self, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def alerts_fx(tmp_path):
    proot = tmp_path / "proj-alerts"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
    store = AdminStore(proot, FakeLogger())
    store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "spec-a",
                  "severity": "critical", "description": "卡死"})
    store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "spec-a",
                  "description": "已处置"})
    store.append({"kind": ESCALATION, "signal_type": "flapping", "spec": "spec-b",
                  "severity": "major", "description": "抖动"})
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787,
              "projects": [{"name": "proj-alerts", "path": str(proot)}],
              # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, store, srv
    srv.stop()


@pytest.fixture()
def activities_fx(tmp_path):
    """运维记录 API 测试数据：排序/置顶/缺 summary 降级。"""
    proot = tmp_path / "proj-act"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
    store = AdminStore(proot, FakeLogger())
    # 旧记录：无 summary（降级测试），时间最早
    store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "spec-old",
                  "action_taken": "清理缓存", "result": "resolved", "escalate": False,
                  "created": iso_ago(60)})
    # 新记录：有 summary，时间最晚
    store.append({"kind": DISPOSITION, "signal_type": "flapping", "spec": "spec-new",
                  "action_taken": "重置状态", "result": "resolved", "escalate": False,
                  "summary": "诊断结论：状态机空转；处置：重置；结果：恢复。",
                  "created": iso_ago(10)})
    # 升级关联：disposition escalate + 未处理 escalation 同 admin_run_id（应置顶）
    store.append({"kind": DISPOSITION, "signal_type": "merge_streak", "spec": "spec-esc",
                  "action_taken": "尝试清理", "result": "escalated", "escalate": True,
                  "summary": "诊断结论：merge 冲突无法自动解决；需人工决策。",
                  "admin_run_id": "admin-spec-esc-1", "created": iso_ago(30)})
    esc = store.append({"kind": ESCALATION, "signal_type": "merge_streak", "spec": "spec-esc",
                        "severity": "critical", "admin_run_id": "admin-spec-esc-1",
                        "created": iso_ago(29)})
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787,
              "projects": [{"name": "proj-act", "path": str(proot)}],
              # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, store, srv
    srv.stop()


class TestDashboardAlertsAPI:
    def test_api_alerts_project(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, data = srv.get("/api/alerts?project=proj-alerts")
        assert status == 200
        assert data["project"] == "proj-alerts"
        assert len(data["alerts"]) == 3
        assert data["summary"]["unhandled_count"] == 2
        assert data["summary"]["max_severity"] == "critical"

    def test_api_alerts_aggregated(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, data = srv.get("/api/alerts")
        assert status == 200
        assert data["total_unhandled"] == 2
        assert len(data["alerts"]) == 2
        assert all("project" in a for a in data["alerts"])
        assert any(a["project"] == "proj-alerts" for a in data["alerts"])

    def test_api_alerts_mark_handled(self, alerts_fx):
        proot, store, srv = alerts_fx
        esc = store.unhandled()[0]
        status, data = srv.post(f"/api/alerts/{esc['id']}/handled?project=proj-alerts")
        assert status == 200
        assert data["ok"] is True
        _, d2 = srv.get("/api/alerts?project=proj-alerts")
        assert d2["summary"]["unhandled_count"] == 1
        assert d2["summary"]["latest"]["handled"] is False  # 剩的那条仍未处理

    def test_api_alerts_mark_handled_unknown(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, _ = srv.post("/api/alerts/nonexistent-id/handled?project=proj-alerts")
        assert status == 404

    def test_api_alerts_mark_handled_unknown_project(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, _ = srv.post("/api/alerts/abc/handled?project=nope")
        assert status == 400

    def test_api_alerts_unknown_project(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, data = srv.get("/api/alerts?project=nope")
        assert status == 200
        assert "error" in data


# ── 4.2 /api/admin-activities（运维记录 API） ───────────

class TestDashboardAdminActivitiesAPI:
    def test_admin_activities_only_dispositions(self, activities_fx):
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities?project=proj-act")
        assert status == 200
        assert len(data["activities"]) == 3  # 只有 disposition，不含 escalation
        assert all("actions_taken" in a and "result" in a for a in data["activities"])

    def test_admin_activities_unhandled_pinned(self, activities_fx):
        """未处理升级关联的处置置顶并标记 handled=False + escalation_id。"""
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities?project=proj-act")
        assert status == 200
        acts = data["activities"]
        assert acts[0]["spec"] == "spec-esc"           # 关联未处理升级 → 置顶
        assert acts[0]["handled"] is False
        assert acts[0]["escalation_id"] is not None
        assert acts[0]["escalate"] is True
        # 其余按时间倒序且 handled=True
        rest = acts[1:]
        assert all(a["handled"] is True for a in rest)
        assert [a["spec"] for a in rest] == ["spec-new", "spec-old"]

    def test_admin_activities_sorted_desc(self, tmp_path):
        """无升级干扰时按时间倒序。"""
        proot = tmp_path / "proj-sort"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        (proot / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        store = AdminStore(proot, FakeLogger())
        store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "oldest",
                      "created": iso_ago(60)})
        store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "middle",
                      "created": iso_ago(30)})
        store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "newest",
                      "created": iso_ago(10)})
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-sort", "path": str(proot)}],
                  # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/admin-activities?project=proj-sort")
            assert status == 200
            assert [a["spec"] for a in data["activities"]] == ["newest", "middle", "oldest"]
        finally:
            srv.stop()

    def test_admin_activities_missing_summary_degrade(self, activities_fx):
        """旧记录无 summary 时正常返回，结构化字段齐全（界面降级依据）。"""
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities?project=proj-act")
        assert status == 200
        old = next(a for a in data["activities"] if a["spec"] == "spec-old")
        assert not old.get("summary")
        # action_taken 归一化为 actions_taken
        assert old["actions_taken"] == "清理缓存"
        assert old["result"] == "resolved"

    def test_admin_activities_pending_dedup(self, tmp_path):
        """同 admin_run_id 的 pending + 最终记录归并：只显示最终，不出现"永久处置中"。"""
        proot = tmp_path / "proj-dedup"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        (proot / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        store = AdminStore(proot, FakeLogger())
        # run A：pending + 最终 → 只显示最终
        store.append({"kind": DISPOSITION, "status": "pending", "result": "pending",
                      "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "run-a",
                      "created": iso_ago(30)})
        store.append({"kind": DISPOSITION, "status": None, "result": "resolved",
                      "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "run-a",
                      "actions_taken": "已处置", "created": iso_ago(10)})
        # run B：只有 pending（admin 仍在处置/被中断）→ 显示处置中
        store.append({"kind": DISPOSITION, "status": "pending", "result": "pending",
                      "signal_type": "flapping", "spec": "spec-b", "admin_run_id": "run-b",
                      "created": iso_ago(5)})
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-dedup", "path": str(proot)}],
                  # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/admin-activities?project=proj-dedup")
            assert status == 200
            acts = data["activities"]
            specs = [a["spec"] for a in acts]
            assert "spec-a" in specs and specs.count("spec-a") == 1  # 归并后只有一条
            a_run = next(a for a in acts if a["spec"] == "spec-a")
            assert a_run["result"] == "resolved"                      # 以最终为准
            assert a_run.get("status") != "pending"
            b_run = next(a for a in acts if a["spec"] == "spec-b")
            assert b_run["result"] == "pending"                       # 无最终 → 显示处置中
        finally:
            srv.stop()

    def test_admin_activities_empty_list(self, tmp_path):
        """无任何记录 → 空列表且不报错。"""
        proot = tmp_path / "proj-empty"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        (proot / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-empty", "path": str(proot)}],
                  # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/admin-activities?project=proj-empty")
            assert status == 200
            assert data["activities"] == []
        finally:
            srv.stop()

    def test_admin_activities_aggregated_by_project(self, activities_fx):
        """缺省 project → 跨项目聚合，按项目分组。"""
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities")
        assert status == 200
        groups = {g["name"]: g for g in data["projects"]}
        assert "proj-act" in groups
        assert len(groups["proj-act"]["activities"]) == 3
        assert all(a["project"] == "proj-act" for a in groups["proj-act"]["activities"])

    def test_admin_activities_unknown_project(self, activities_fx):
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities?project=nope")
        assert status == 200
        assert "error" in data
