"""
tests/test_dashboard_hooks_api.py — Dashboard hooks API 测试（add-spec-hooks tasks 6.2）。

覆盖：
- 4.1 GET /api/hooks/audit：spec 过滤 / 时间倒序 / limit / 文件不存在空列表 / 项目不存在
- 4.2 POST /api/config hooks 段校验：events 非法 / 空 events / action 非法 /
     webhook 缺 url / shell 缺 command → 400 且不写入
"""
import json
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard.registry import Registry
from core.dashboard.server import DashboardHTTPServer, find_free_port
from tests.test_dashboard_api import make_project


class _TestServer:
    """在临时目录上启动 DashboardHTTPServer，线程后台运行（复用 test_dashboard_api 模式）。"""

    def __init__(self, registry: Registry, static_dir: Path):
        self.port = find_free_port(20000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), registry, static_dir)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path: str):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read())
        finally:
            conn.close()

    def post_json(self, path: str, payload: dict):
        import http.client
        body = json.dumps(payload).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(
                "POST", path, body=body,
                headers={"Content-Type": "application/json",
                         "Content-Length": str(len(body))},
            )
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, json.loads(data)
        finally:
            conn.close()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server_fx(tmp_path):
    proot = make_project(tmp_path)
    reg = Registry(config_path=str(tmp_path / "dash.yaml"))
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()


def _write_audit(proot: Path, lines: list):
    """写 .fenix/hook_audit.jsonl。lines 为记录 dict 列表，按序写入。"""
    path = proot / ".fenix" / "hook_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n",
        encoding="utf-8",
    )


class TestHooksAuditGet:
    def test_audit_all_desc(self, server_fx):
        proot, srv = server_fx
        _write_audit(proot, [
            {"ts": "2026-09-06T10:00:00Z", "spec": "s1", "event": "done", "action": "commit",
             "scope": "global", "status": "success", "detail": "ok", "duration_ms": 5},
            {"ts": "2026-09-06T10:01:00Z", "spec": "s2", "event": "blocked", "action": "shell",
             "scope": "spec", "status": "failure", "detail": "bad", "duration_ms": 6},
            {"ts": "2026-09-06T10:02:00Z", "spec": "s1", "event": "blocked", "action": "webhook",
             "scope": "global", "status": "success", "detail": "resp", "duration_ms": 7},
        ])
        st, data = srv.get("/api/hooks/audit?project=proj-a")
        assert st == 200
        assert [r["spec"] for r in data["audit"]] == ["s1", "s2", "s1"]
        assert [r["ts"] for r in data["audit"]] == [
            "2026-09-06T10:02:00Z", "2026-09-06T10:01:00Z", "2026-09-06T10:00:00Z"]

    def test_audit_spec_filter(self, server_fx):
        proot, srv = server_fx
        _write_audit(proot, [
            {"ts": "2026-09-06T10:00:00Z", "spec": "s1", "event": "done", "action": "commit",
             "scope": "global", "status": "success"},
            {"ts": "2026-09-06T10:01:00Z", "spec": "s2", "event": "blocked", "action": "shell",
             "scope": "spec", "status": "failure"},
        ])
        st, data = srv.get("/api/hooks/audit?project=proj-a&spec=s1")
        assert st == 200
        assert len(data["audit"]) == 1
        assert data["audit"][0]["spec"] == "s1"

    def test_audit_limit(self, server_fx):
        proot, srv = server_fx
        _write_audit(proot, [
            {"ts": f"2026-09-06T10:0{i}:00Z", "spec": f"s{i}", "event": "done", "action": "commit",
             "scope": "global", "status": "success"} for i in range(5)
        ])
        st, data = srv.get("/api/hooks/audit?project=proj-a&limit=2")
        assert st == 200
        assert len(data["audit"]) == 2
        assert data["audit"][0]["spec"] == "s4"

    def test_audit_missing_file_empty(self, server_fx):
        _, srv = server_fx
        st, data = srv.get("/api/hooks/audit?project=proj-a")
        assert st == 200
        assert data["audit"] == []

    def test_audit_unknown_project_empty(self, server_fx):
        _, srv = server_fx
        st, data = srv.get("/api/hooks/audit?project=nope")
        assert st == 200
        assert data["audit"] == []

    def test_audit_corrupt_lines_skipped(self, server_fx):
        proot, srv = server_fx
        path = proot / ".fenix" / "hook_audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"ts":"2026-09-06T10:00:00Z","spec":"s1","status":"success"}\n'
            "this is not json\n"
            '{"ts":"2026-09-06T10:02:00Z","spec":"s1","status":"success"}\n',
            encoding="utf-8",
        )
        st, data = srv.get("/api/hooks/audit?project=proj-a&spec=s1")
        assert st == 200
        assert len(data["audit"]) == 2


class TestConfigHooksValidation:
    """POST /api/config hooks 段校验（tasks 4.2）。"""

    def test_valid_hooks_saved(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"global": [{"id": "h1", "enabled": True, "events": ["done"], "action": "commit"}]},
        })
        assert st == 200, data
        raw = (proot / ".fenix" / "config.yaml").read_text(encoding="utf-8")
        assert "h1" in raw

    def test_invalid_events_400(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"global": [{"events": ["bogus"], "action": "commit"}]},
        })
        assert st == 400
        assert "hooks" in data["error"]
        raw = (proot / ".fenix" / "config.yaml").read_text(encoding="utf-8")
        assert "bogus" not in raw

    def test_empty_events_400(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"global": [{"events": [], "action": "commit"}]},
        })
        assert st == 400
        raw = (proot / ".fenix" / "config.yaml").read_text(encoding="utf-8")
        assert "events" not in raw.replace("events", "", 1) or "events: []" not in raw

    def test_invalid_action_400(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"global": [{"events": ["done"], "action": "explode"}]},
        })
        assert st == 400
        assert "action" in data["error"]

    def test_webhook_missing_url_400(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"global": [{"events": ["done"], "action": "webhook"}]},
        })
        assert st == 400
        assert "url" in data["error"]

    def test_shell_missing_command_400(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"specs": {"myspec": [{"events": ["blocked"], "action": "shell"}]}},
        })
        assert st == 400
        assert "command" in data["error"]

    def test_specs_bad_shape_400(self, server_fx):
        proot, srv = server_fx
        st, data = srv.post_json("/api/config?project=proj-a", {
            "hooks": {"specs": "not-an-object"},
        })
        assert st == 400
        assert "hooks.specs" in data["error"]

    def test_config_read_back_hooks(self, server_fx):
        _, srv = server_fx
        st, data = srv.get("/api/config?project=proj-a")
        assert st == 200
        assert "hooks" in data
        assert data["hooks"] == {"global": [], "specs": {}}
