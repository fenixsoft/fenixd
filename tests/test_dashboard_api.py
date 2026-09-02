"""
Tests for Dashboard server API functionality.

Split from test_dashboard.py as part of refactor-test-structure.
"""
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data
from core.dashboard.registry import Registry
from core.dashboard.server import (
    DashboardHTTPServer, DashboardHandler, find_free_port,
    serve, _find_dashboard_occupant, _is_dashboard_serve_cmd,
)


# ── 辅助：构造一个可用的 Fenixd 项目目录 ──────────────────────────────

def make_project(tmp_path: Path, name: str = "proj-a") -> Path:
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots").mkdir(parents=True, exist_ok=True)
    (proot / "openspec" / "changes" / "myspec" / "specs").mkdir(parents=True, exist_ok=True)

    (proot / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
        "### otherspec\n- status: done\n- priority: 1\n- created: 2026-02-01T00:00:00+00:00\n"
        "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )

    (proot / ".fenix" / "config.yaml").write_text("project:\n  name: fake\n", encoding="utf-8")

    (proot / "openspec" / "changes" / "myspec" / "tasks.md").write_text(
        "## 1. 阶段一\n\n"
        "- [x] 1.1 任务一\n"
        "- [ ] 1.2 任务二\n\n"
        "## 2. 阶段二\n\n"
        "- [ ] 2.1 任务三\n",
        encoding="utf-8",
    )

    (proot / "openspec" / "changes" / "myspec" / "specs" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: 功能\n\n"
        "#### Scenario: 场景一\n- **WHEN** x\n- **THEN** y\n\n"
        "#### Scenario: 场景二\n- **WHEN** a\n- **THEN** b\n",
        encoding="utf-8",
    )

    # 验证产物
    (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
        json.dumps({"total": 3, "done": 1, "current": "场景二"}), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "report.json").write_text(
        json.dumps({
            "summary": {"total": 2, "passed": 1, "failed": 1, "warnings": 0, "errors": 0},
            "scenarios": [
                {"scenario_id": "sc-1", "status": "pass", "description": "通过场景",
                 "assertion_results": [{"type": "element_visible", "pass": True}]},
                {"scenario_id": "sc-2", "status": "fail", "description": "失败场景",
                 "assertion_results": [{"type": "text_match", "pass": False,
                                        "message": "期望 '5' 实际 'x'"}],
                 "screenshots": ["fail.png"]},
            ],
        }), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "test_scenarios.json").write_text(
        json.dumps([{"id": "sc-1"}, {"id": "sc-2"}]), encoding="utf-8"
    )
    (proot / ".fenix" / "verify-progress" / "myspec" / "screenshots" / "fail.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    # 运行记录（一条已完成 + 一条运行中）
    (proot / ".fenix" / "runs" / "impl-myspec-1780000000.jsonl").write_text(
        json.dumps({"type": "system", "subtype": "init"}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "开始实现"}]}}, ensure_ascii=False) + "\n"
        + json.dumps({"type": "result", "result": "完成", "num_turns": 5}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "runs" / "verify-myspec-1780001000.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "playwright_cli", "input": {"action": "click"}}]}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 事件日志（时间戳必须是最近时间，get_recent_events 按分钟窗口过滤）
    from datetime import datetime, timezone
    (proot / ".fenix" / "logs" / "fenixd-2026.log").write_text(
        json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": "INFO",
                    "component": "pm_engine", "message": "scan"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (proot / "openspec" / "changes" / "myspec" / "verification-report.md").write_text(
        "# 验证报告\n\n## Bug 汇总\n- 严重缺陷：点击保存按钮无反应\n  根因：事件未绑定\n",
        encoding="utf-8",
    )
    return proot


# ── server.py ─────────────────────────────────────────────────────────

class _TestServer:
    """在临时目录上启动 DashboardHTTPServer，线程后台运行。"""

    def __init__(self, registry: Registry, static_dir: Path):
        self.port = find_free_port(20000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), registry, static_dir)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path: str, raw: bool = False):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            if raw:
                return resp.status, resp.getheader("Content-Type"), body
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def _req(self, method: str, path: str):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def post(self, path: str):
        return self._req("POST", path)

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

    def delete(self, path: str):
        return self._req("DELETE", path)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server_fx(tmp_path):
    proot = make_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()


class TestServerAPI:
    def test_index_served(self, server_fx):
        # 根路由直接服务 v3 dashboard 首页（/v3/dist/ 静态透传保留，兼容旧书签）
        import http.client
        _, srv = server_fx
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read()
            assert resp.status == 200
            assert resp.getheader("Content-Type") == "text/html"
            assert b"<!DOCTYPE html>" in body
        finally:
            conn.close()

    def test_static_root_fallback_to_v3_dist(self, server_fx):
        # v3 SPA 挂载在 / 时，相对资源（./umi.js）以根路径请求，
        # 静态服务需回退到 v3/dist/ 命中（/v3/dist/ 原路径仍透传）
        import http.client
        _, srv = server_fx
        dist = (Path(__file__).resolve().parents[1]
                / "core" / "dashboard" / "static" / "v3" / "dist")
        js_name = sorted(p.name for p in dist.glob("umi.*.js"))[0]
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            conn.request("GET", f"/{js_name}")
            resp = conn.getresponse()
            body = resp.read()
            assert resp.status == 200
            assert "javascript" in (resp.getheader("Content-Type") or "")
            assert len(body) > 0
        finally:
            conn.close()

    def test_api_projects(self, server_fx):
        proot, srv = server_fx
        status, data = srv.get("/api/projects")
        assert status == 200
        assert data["projects"][0]["name"] == "proj-a"
        assert data["projects"][0]["spec_count"] == 2

    def test_api_overview(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/overview")
        assert status == 200
        assert data["totals"]["spec_count"] == 2
        assert data["totals"]["active_runs"] == 1
        assert data["totals"]["status_counts"]["testing"] == 1

    def test_api_specs(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs?project=proj-a")
        assert status == 200
        specs = data["specs"]
        names = {s["name"] for s in specs}
        assert "myspec" in names and "otherspec" in names
        for s in specs:
            assert "created" in s
            assert "updated" in s
        spec_names_order = [s["name"] for s in specs]
        assert spec_names_order.index("otherspec") < spec_names_order.index("myspec")

    def test_api_spec_detail(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs/myspec?project=proj-a")
        assert status == 200
        assert data["status"] == "testing"
        assert len(data["tasks"]) == 2
        assert len(data["scenarios"]) == 2
        assert len(data["bugs"]) >= 1
        assert len(data["screenshots"]) == 1
        assert len(data["runs"]) == 2
        assert data["verify_progress"]["total"] == 3

    def test_api_spec_doc(self, server_fx):
        proot, srv = server_fx
        (proot / "openspec" / "changes" / "myspec" / "proposal.md").write_text(
            "# 背景\n\n- 列表项\n", encoding="utf-8"
        )
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=proposal")
        assert status == 200
        assert data["found"] is True
        assert "背景" in data["content"]
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=design")
        assert status == 200
        assert data == {"found": False, "content": "", "project": "proj-a", "spec": "myspec", "doc": "design"}
        status, _ = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=readme")
        assert status == 400
        status, _ = srv.get("/api/spec-doc?project=proj-a&spec=ghost&doc=proposal")
        assert status == 404
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=../../etc/passwd&doc=proposal")
        assert status == 404
        status, _ = srv.get("/api/spec-doc?project=ghost&spec=myspec&doc=proposal")
        assert status == 400

    def test_api_run(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/runs/impl-myspec-1780000000?project=proj-a")
        assert status == 200
        assert data["status"] == "done"
        assert data["events"][-1]["type"] == "result"

    def test_api_events(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/events?project=proj-a&minutes=10")
        assert status == 200
        assert len(data["events"]) == 1

    def test_unknown_project(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs?project=ghost")
        assert status == 200
        assert data["specs"] == []

    def test_screenshot_served(self, server_fx):
        _, srv = server_fx
        status, ctype, body = srv.get("/screenshots/proj-a/myspec/fail.png", raw=True)
        assert status == 200
        assert ctype == "image/png"

    def test_screenshot_path_traversal_blocked(self, server_fx):
        proot, srv = server_fx
        status, _, _ = srv.get(
            "/screenshots/proj-a/myspec/../../../STATE.md", raw=True
        )
        assert status in (403, 404)
        status, _, _ = srv.get("/screenshots/ghost/myspec/fail.png", raw=True)
        assert status in (403, 404)

    def test_corrupt_progress_does_not_500(self, tmp_path):
        proot = make_project(tmp_path)
        (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
            "{{{{ corrupted", encoding="utf-8"
        )
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}], "scan_dirs": []})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/specs/myspec?project=proj-a")
            assert status == 200
            assert data["verify_progress"]["error"] == "corrupt"
            status, data = srv.get("/api/overview")
            assert status == 200
        finally:
            srv.stop()

    def test_binds_localhost_only(self, tmp_path):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}], "scan_dirs": []})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            assert srv.httpd.server_address[0] in ("127.0.0.1", "localhost")
        finally:
            srv.stop()

    def test_find_free_port_probes_upward(self):
        occupied = find_free_port(20100)
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", occupied))
            s.listen(1)
            free = find_free_port(occupied)
            assert free != occupied


class TestProjectLifecycleAPI:
    """管理端点：start/stop/delete（mock tmux，验证返回、错误路径、SSE 广播）。"""

    def _make_server(self, tmp_path, registry):
        return _TestServer(registry, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_start_stop_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/projects/ghost/start")
            assert status == 400 and body["error"]
            status, body = srv.post("/api/projects/ghost/stop")
            assert status == 400 and body["error"]
            status, body = srv.delete("/api/projects/ghost")
            assert status == 400 and body["error"]
        finally:
            srv.stop()

    def test_start_stop_delete_flow_with_mocked_tmux(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        started, stopped, deleted = [], [], []
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root: started.append(root) or {"ok": True, "session": "s1", "already": False})
        monkeypatch.setattr("core.dashboard.server.stop_daemon",
                            lambda root: stopped.append(root) or {"ok": True, "session": "s1", "was_running": True})

        try:
            status, body = srv.post("/api/projects/proj-a/start")
            assert status == 200 and body["ok"] is True
            assert body["session"] == "s1"
            assert str(proot) in started
            status, body = srv.post("/api/projects/proj-a/stop")
            assert status == 200 and body["ok"] is True
            assert str(proot) in stopped
            status, body = srv.delete("/api/projects/proj-a")
            assert status == 200 and body["ok"] is True
            assert reg.is_ignored(str(proot))
            names = {p["name"] for p in reg.discover()}
            assert "proj-a" not in names
        finally:
            srv.stop()

    def test_lifecycle_tmux_error_returns_ok_false_not_500(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root: (_ for _ in ()).throw(RuntimeError("tmux gone")))
        try:
            status, body = srv.post("/api/projects/proj-a/start")
            assert status == 200 and body["ok"] is False and "tmux gone" in body["error"]
        finally:
            srv.stop()


class TestProjectDescribeAPI:
    """测试 /api/project/describe 端点"""

    def _make_server(self, tmp_path, registry):
        return _TestServer(registry, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_describe_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/project/describe?project=ghost")
            assert status == 400 and body["error"] == "unknown project"
        finally:
            srv.stop()

    def test_describe_project_not_found_returns_404(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(tmp_path / "nonexistent")}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/project/describe?project=proj-a")
            assert status == 404 and body["error"] == "project not found"
        finally:
            srv.stop()

    def test_describe_success_with_readme(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        # 创建 README.md
        (proot / "README.md").write_text("# 测试项目\n这是一个测试项目，用于演示功能。", encoding="utf-8")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        # Mock subprocess.run
        mock_result = type('MockResult', (), {
            'returncode': 0,
            'stdout': '这是一个由测试生成的项目简介，用于验证 describe 接口功能。',
            'stderr': ''
        })()
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        try:
            status, body = srv.post("/api/project/describe?project=proj-a")
            assert status == 200
            assert body["ok"] is True
            assert "description" in body
            assert body["description"] == "这是一个由测试生成的项目简介，用于验证 describe 接口功能。"

            # 验证配置已写入
            config_path = proot / ".fenix" / "config.yaml"
            assert config_path.exists()
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            assert config["project"]["description"] == "这是一个由测试生成的项目简介，用于验证 describe 接口功能。"
        finally:
            srv.stop()

    def test_describe_success_without_readme(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        # 不创建 README.md，创建 package.json 作为 fallback
        (proot / "package.json").write_text('{"name": "test-project", "version": "1.0.0"}', encoding="utf-8")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        # Mock subprocess.run
        mock_result = type('MockResult', (), {
            'returncode': 0,
            'stdout': '这是一个基于 package.json 生成的项目简介。',
            'stderr': ''
        })()
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        try:
            status, body = srv.post("/api/project/describe?project=proj-a")
            assert status == 200
            assert body["ok"] is True
            assert body["description"] == "这是一个基于 package.json 生成的项目简介。"
        finally:
            srv.stop()

    def test_describe_timeout_returns_error(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        (proot / "README.md").write_text("# 测试项目", encoding="utf-8")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        # Mock subprocess.run to raise TimeoutExpired
        import subprocess
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=120)
        monkeypatch.setattr("subprocess.run", mock_run)

        try:
            status, body = srv.post("/api/project/describe?project=proj-a")
            assert status == 200
            assert "error" in body
            assert "超时" in body["error"]

            # 验证配置未被修改
            config_path = proot / ".fenix" / "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            assert "description" not in config.get("project", {})
        finally:
            srv.stop()

    def test_describe_nonzero_exit_returns_error(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        (proot / "README.md").write_text("# 测试项目", encoding="utf-8")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        # Mock subprocess.run with non-zero exit code
        mock_result = type('MockResult', (), {
            'returncode': 1,
            'stdout': '',
            'stderr': 'Error: Claude CLI failed'
        })()
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        try:
            status, body = srv.post("/api/project/describe?project=proj-a")
            assert status == 200
            assert "error" in body
            assert "非零退出码" in body["error"]

            # 验证配置未被修改
            config_path = proot / ".fenix" / "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            assert "description" not in config.get("project", {})
        finally:
            srv.stop()

    def test_describe_empty_output_returns_error(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        (proot / "README.md").write_text("# 测试项目", encoding="utf-8")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        # Mock subprocess.run with empty output
        mock_result = type('MockResult', (), {
            'returncode': 0,
            'stdout': '',
            'stderr': ''
        })()
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        try:
            status, body = srv.post("/api/project/describe?project=proj-a")
            assert status == 200
            assert "error" in body
            assert "为空" in body["error"]

            # 验证配置未被修改
            config_path = proot / ".fenix" / "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            assert "description" not in config.get("project", {})
        finally:
            srv.stop()
