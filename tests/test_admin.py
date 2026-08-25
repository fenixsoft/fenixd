"""admin_store / admin_monitor / run_administrator / Dashboard alerts API 测试。

对应 openspec/changes/add-administrator-agent 的 tasks 4.1-4.3。
"""

import json
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


# ── run_administrator：处置文件读取 + 陈旧清理 ──────────

class TestRunAdministrator:
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
        runner._build_prompt = lambda *a, **k: "prompt"

        def fake_run_claude(prompt, cwd, run_id, model_override, max_turns):
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
        assert disp.actions_taken == "kill；reset"
        assert disp.result == "resolved"
        assert disp.escalate is False
        assert disp.spec == "spec-a"

    def test_run_administrator_failure_falls_back(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
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
              "scan_dirs": []})
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
