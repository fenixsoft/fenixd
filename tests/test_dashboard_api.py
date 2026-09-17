"""
Tests for Dashboard server API functionality.

Split from test_dashboard.py as part of refactor-test-structure.
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 共享夹具已收敛至 tests/conftest.py（make_project / _TestServer / server_fx）
from conftest import _TestServer, make_project  # noqa: E402

from core.dashboard import data as dash_data
from core.dashboard.registry import Registry
from core.dashboard.server import find_free_port


# ── server.py ─────────────────────────────────────────────────────────
class TestServerAPI:
    def test_index_served(self, server_fx):
        # 根路由直接服务 dashboard 首页（v3 SPA，自 static/ 上移后 dist/ 不再有 v3 层级）
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

    def test_static_root_fallback_to_dist(self, server_fx):
        # v3 SPA 挂载在 / 时，相对资源（./umi.js）以根路径请求，
        # 静态服务需回退到 dist/ 命中
        import http.client
        _, srv = server_fx
        dist = (Path(__file__).resolve().parents[1]
                / "core" / "dashboard" / "static" / "dist")
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
        (proot / "spec" / "changes" / "myspec" / "proposal.md").write_text(
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


class TestSpecSchedulingAPI:
    """定时拾取 / 冻结配置路由（add-spec-scheduling-controls，同款夹具）。

    夹具 make_project：myspec=testing（非终态）、otherspec=done（终态）。
    """

    def test_start_after_set_and_reload(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": "2026-09-07T01:00:00+00:00"},
        )
        assert status == 200
        assert body["ok"] is True
        assert body["start_after"] == "2026-09-07T01:00:00+00:00"
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") == "2026-09-07T01:00:00+00:00"

    def test_start_after_null_clears(self, server_fx):
        proot, srv = server_fx
        srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": "2026-09-07T01:00:00+00:00"},
        )
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": None},
        )
        assert status == 200
        assert body["start_after"] is None
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") is None

    def test_start_after_invalid_rejected(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": "明天早上"},
        )
        assert status == 400
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") is None  # STATE 不变

    def test_start_after_terminal_rejected(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=otherspec",
            {"value": "2026-09-07T01:00:00+00:00"},
        )
        assert status == 403
        entry = dash_data.parse_state(proot)["otherspec"]
        assert entry.get("start_after") is None

    @pytest.fixture()
    def frozen_spec(self, server_fx):
        """已冻结 myspec 的 server（freeze-config 组共享前置，原各用例首行 freeze）。"""
        proot, srv = server_fx
        status, _ = srv.post("/api/spec-freeze?project=proj-a&spec=myspec")
        assert status == 200
        yield proot, srv

    def test_freeze_config_permanent(self, frozen_spec):
        proot, srv = frozen_spec
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "permanent"},
        )
        assert status == 200
        assert body["mode"] == "permanent"
        assert body["frozen_until"] is None
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("status") == "blocked"
        assert entry.get("frozen_until") is None

    def test_freeze_config_scheduled(self, frozen_spec):
        proot, srv = frozen_spec
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "scheduled", "until": until},
        )
        assert status == 200
        assert body["unfrozen"] is False
        assert body["frozen_until"] == until
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("status") == "blocked"  # 冻结态保持
        assert entry.get("frozen_until") == until

    def test_freeze_config_scheduled_past_immediate_unfreeze(self, frozen_spec):
        proot, srv = frozen_spec
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "scheduled", "until": past},
        )
        assert status == 200
        assert body["unfrozen"] is True
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("status") == "testing"  # 恢复原状态
        assert entry.get("frozen_until") is None  # 不残留

    def test_freeze_config_unfreeze(self, frozen_spec):
        proot, srv = frozen_spec
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "unfreeze"},
        )
        assert status == 200
        assert body["unfrozen"] is True
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("status") == "testing"
        assert entry.get("error") is None

    @pytest.mark.parametrize("payload", [
        {"mode": "bogus"},                          # 非法 mode
        {"mode": "scheduled", "until": "下周一"},    # 非法 until
    ])
    def test_freeze_config_invalid_payload_rejected(self, frozen_spec, payload):
        proot, srv = frozen_spec
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            payload,
        )
        assert status == 400

    def test_freeze_config_non_frozen_rejected(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "permanent"},
        )
        assert status == 409


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

    def test_restart_writes_restart_request_signal(self, tmp_path, monkeypatch):
        """restart 走 supervisor 优雅重启协议：写 .fenix/restart_request 文件信号，
        不直接调用 start/stop_daemon。"""
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        lifecycle_calls = []
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root: lifecycle_calls.append(("start", root)) or {"ok": True})
        monkeypatch.setattr("core.dashboard.server.stop_daemon",
                            lambda root: lifecycle_calls.append(("stop", root)) or {"ok": True})

        try:
            status, body = srv.post("/api/projects/proj-a/restart")
            assert status == 200 and body["ok"] is True
            assert (proot / ".fenix" / "restart_request").exists(), \
                "restart 必须写 restart_request 信号（supervisor 优雅重启协议）"
            assert lifecycle_calls == [], "restart 不应直接调用 start/stop_daemon"
        finally:
            srv.stop()

    def test_restart_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/projects/ghost/restart")
            assert status == 400 and body["error"]
        finally:
            srv.stop()


class TestConfigSyncFromUserAPI:
    """POST /api/config/sync-from-user：把用户级 page 页签受管键覆盖写入项目级。"""

    def _make_server(self, tmp_path, registry):
        return _TestServer(registry, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_sync_writes_project_config_and_echoes(self, tmp_path, monkeypatch):
        import yaml
        proot = make_project(tmp_path)
        user_dir = tmp_path / "user-fenix"
        user_dir.mkdir()
        with open(user_dir / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"gates": {"promote_mode": "manual", "approve_mode": "auto"}}, f)
        monkeypatch.setattr("core.dashboard.data.USER_CONFIG_PATH", user_dir / "config.yaml")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "approval"})
            assert status == 200 and body["saved"] is True
            assert body["synced"] == {"gates": {"promote_mode": "manual", "approve_mode": "auto"}}
            proj_cfg = yaml.safe_load((proot / ".fenix" / "config.yaml").read_text(encoding="utf-8"))
            assert proj_cfg["gates"]["promote_mode"] == "manual"
        finally:
            srv.stop()

    def test_sync_unknown_page_returns_400(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        user_dir = tmp_path / "user-fenix"
        user_dir.mkdir()
        monkeypatch.setattr("core.dashboard.data.USER_CONFIG_PATH", user_dir / "config.yaml")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "bogus"})
            assert status == 400 and "未知页面标识" in body["error"]
        finally:
            srv.stop()

    def test_sync_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=ghost",
                          {"page": "approval"})
            assert status == 400 and body["error"]
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

    def test_describe_prompt_contains_project_identity(self, server_fx, monkeypatch):
        """prompt 必须携带项目名与路径，否则 README 主题重叠的项目（如 fenix-desktop
        与 fenixd）会生成彼此的简介。"""
        proot, srv = server_fx
        (proot / "README.md").write_text(
            "# 同一个框架\n这是两个不同项目共用的说明文案。", encoding="utf-8"
        )

        mock_result = type('MockResult', (), {'returncode': 0, 'stdout': '简介', 'stderr': ''})()
        captured = {}

        def fake_run(args, **kwargs):
            captured['args'] = args
            return mock_result

        monkeypatch.setattr("subprocess.run", fake_run)

        status, body = srv.post("/api/project/describe?project=proj-a")
        assert status == 200 and body["ok"] is True
        prompt = captured['args'][2]  # ["claude", "-p", prompt]
        assert "proj-a" in prompt, "prompt 未包含项目名"
        assert str(proot) in prompt, "prompt 未包含项目路径"

    def test_describe_success_with_readme(self, server_fx, monkeypatch):
        proot, srv = server_fx
        # 创建 README.md
        (proot / "README.md").write_text("# 测试项目\n这是一个测试项目，用于演示功能。", encoding="utf-8")

        # Mock subprocess.run
        mock_result = type('MockResult', (), {
            'returncode': 0,
            'stdout': '这是一个由测试生成的项目简介，用于验证 describe 接口功能。',
            'stderr': ''
        })()
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

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

    def test_describe_success_without_readme(self, server_fx, monkeypatch):
        proot, srv = server_fx
        # 不创建 README.md，创建 package.json 作为 fallback
        (proot / "package.json").write_text('{"name": "test-project", "version": "1.0.0"}', encoding="utf-8")

        # Mock subprocess.run
        mock_result = type('MockResult', (), {
            'returncode': 0,
            'stdout': '这是一个基于 package.json 生成的项目简介。',
            'stderr': ''
        })()
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        status, body = srv.post("/api/project/describe?project=proj-a")
        assert status == 200
        assert body["ok"] is True
        assert body["description"] == "这是一个基于 package.json 生成的项目简介。"

    @pytest.mark.parametrize("mock_kind,expected_frag", [
        ("timeout", "超时"),
        ("nonzero", "非零退出码"),
        ("empty", "为空"),
    ])
    def test_describe_error_returns_error_and_keeps_config(self, server_fx, monkeypatch, mock_kind, expected_frag):
        """超时 / 非零退出码 / 空输出 → 200 + error 且不写 description。"""
        import subprocess
        proot, srv = server_fx
        (proot / "README.md").write_text("# 测试项目", encoding="utf-8")

        if mock_kind == "timeout":
            def mock_run(*args, **kwargs):
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=120)
        elif mock_kind == "nonzero":
            mock_result = type('MockResult', (), {
                'returncode': 1, 'stdout': '', 'stderr': 'Error: Claude CLI failed'})()
            mock_run = lambda *args, **kwargs: mock_result
        else:  # empty
            mock_result = type('MockResult', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
            mock_run = lambda *args, **kwargs: mock_result
        monkeypatch.setattr("subprocess.run", mock_run)

        status, body = srv.post("/api/project/describe?project=proj-a")
        assert status == 200
        assert "error" in body
        assert expected_frag in body["error"]

        # 验证配置未被修改
        config_path = proot / ".fenix" / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        assert "description" not in config.get("project", {})

    # ── verify-yaml-autodraft tests ──────────────────────────────────────────

    def test_autodraft_unknown_project_returns_404(self, server_fx):
        """未知项目 404，不写任何信号。"""
        _, srv = server_fx
        status, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=nonexistent",
            {"overwrite": False},
        )
        assert status == 404
        assert body.get("error") == "project not found"

    def test_autodraft_missing_contract_dispatches_signal(self, server_fx):
        """契约缺失 → dispatched + 信号落盘含 source 标注。"""
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": False},
        )
        assert status == 200
        assert body["ok"] is True
        assert body["status"] == "dispatched"
        assert "AI 起草请求" in body["message"]
        # 检查信号落盘
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        signals = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        assert len(signals) == 1
        sig = signals[0]
        assert sig["source"] == "ui-manual"
        assert sig["spec"] is None
        assert sig["overwrite"] is False
        assert "项目名=proj-a" in sig["evidence"]

    def test_autodraft_valid_contract_no_overwrite_skipped(self, server_fx):
        """契约有效无 overwrite → skipped 且零信号。"""
        proot, srv = server_fx
        # 写入有效契约
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        status, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": False},
        )
        assert status == 200
        assert body["status"] == "skipped"
        assert "契约已有效" in body["message"]
        # 检查零信号
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        signals = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        assert len(signals) == 0

    def test_autodraft_valid_contract_with_overwrite_dispatches(self, server_fx):
        """契约有效带 overwrite → dispatched + 写入 verify_contract_redraft 信号。"""
        proot, srv = server_fx
        # 写入有效契约
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        status, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert status == 200
        assert body["status"] == "dispatched"
        # 检查信号落盘：覆盖重起草改写 verify_contract_redraft，不再旁路 missing
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        redraft = [r for r in records if r.get("signal_type") == "verify_contract_redraft"]
        missing = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        assert len(redraft) == 1
        assert len(missing) == 0
        sig = redraft[0]
        assert sig["overwrite"] is True
        assert sig["source"] == "ui-manual"
        assert "项目名=proj-a" in sig["evidence"]
        assert "覆盖确认=是" in sig["evidence"]

    def test_autodraft_redraft_signal_severity_major(self, server_fx):
        """redraft 信号 severity=major（与 SPEC Requirement 一致）。"""
        proot, srv = server_fx
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        sig = next(r for r in records if r.get("signal_type") == "verify_contract_redraft")
        assert sig["severity"] == "major"

    def test_autodraft_inflight_dedup_no_duplicate_write(self, server_fx):
        """在途去重：同类型未消费信号已存在 → 二次触发不落盘 + message 注明在途。"""
        proot, srv = server_fx
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        # 第一次触发：写入 redraft 信号
        _, body1 = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert body1["status"] == "dispatched"
        # 第二次触发：在途信号存在 → 不重复写，message 含在途提示
        status, body2 = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert status == 200
        assert body2["status"] == "dispatched"
        assert "已有在途" in body2["message"]
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        redraft = [r for r in records if r.get("signal_type") == "verify_contract_redraft"]
        assert len(redraft) == 1, "同类型在途信号存在时不得重复落盘"

    def test_autodraft_handled_signal_does_not_suppress(self, server_fx):
        """已消费（handled）信号不抑制新触发 → 正常写入新信号。"""
        proot, srv = server_fx
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        # 第一次触发落盘
        srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        # 模拟 Administrator 已处置：把该信号标记 handled
        alerts_path = proot / ".fenix" / "admin_alerts.json"
        import json as _json
        records = _json.loads(alerts_path.read_text(encoding="utf-8"))
        for rec in records:
            if rec.get("signal_type") == "verify_contract_redraft":
                rec["handled"] = True
        alerts_path.write_text(
            _json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # 再次触发：handled 不抑制 → 新信号落盘
        _, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert body["status"] == "dispatched"
        assert "已有在途" not in body["message"]
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        redraft = [r for r in records if r.get("signal_type") == "verify_contract_redraft"]
        assert len(redraft) == 2, "已 handled 信号不抑制新触发"

    def test_autodraft_missing_inflight_does_not_suppress_redraft(self, server_fx):
        """异类型互不抑制：missing 在途不挡 redraft。"""
        proot, srv = server_fx
        # 无契约触发 → missing 信号落盘（在途）
        _, body1 = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": False},
        )
        assert body1["status"] == "dispatched"
        # 契约被修正为可解析 + 用户确认覆盖 → redraft 信号正常落盘
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        _, body2 = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert body2["status"] == "dispatched"
        assert "已有在途" not in body2["message"]
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        missing = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        redraft = [r for r in records if r.get("signal_type") == "verify_contract_redraft"]
        assert len(missing) == 1
        assert len(redraft) == 1, "missing 在途不得抑制 redraft"

    def test_autodraft_signal_record_completeness(self, server_fx):
        """信号记录字段完整性：signal_type/source/overwrite/evidence 项目名。"""
        proot, srv = server_fx
        status, _ = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert status == 200
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        sig = next(r for r in records if r.get("signal_type") == "verify_contract_missing")
        # 字段完整性
        assert sig["signal_type"] == "verify_contract_missing"
        assert sig["source"] == "ui-manual"
        assert sig["overwrite"] is True
        assert "项目名=proj-a" in sig["evidence"]
        assert sig["spec"] is None
        assert sig["kind"] == "signal"


# ── SPEC 人工晋升（add-draft-promotion-gate D4/D5） ──────────────────
class TestSpecPromoteAPI:
    """POST /api/spec-promote：drafted → ready 人工晋升。"""

    def _make_drafted_project(self, tmp_path, spec_name="draft-spec"):
        """构造含 drafted spec 的项目（复用 make_project 后改状态）。"""
        proot = make_project(tmp_path, name="proj-a")
        # 添加一个 drafted spec
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(spec_name, {"status": "drafted"})
        # 创建 spec 目录与 tasks.md（声明段合法）
        (proot / "spec" / "changes" / spec_name).mkdir(parents=True, exist_ok=True)
        (proot / "spec" / "changes" / spec_name / "tasks.md").write_text(
            "## 1. 阶段一\n\n- [x] 1.1 任务一\n", encoding="utf-8"
        )
        return proot

    def test_promote_success(self, tmp_path):
        """成功晋升：drafted → reviewing（default auto 分流，无 .spec.yaml 保守进入评审）。"""
        proot = self._make_drafted_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, body = srv.post("/api/spec-promote?project=proj-a&spec=draft-spec")
            assert status == 200
            assert body["ok"] is True
            assert body["next_status"] == "reviewing"
            entry = dash_data.parse_state(proot)["draft-spec"]
            assert entry["status"] == "reviewing"
        finally:
            srv.stop()

    def test_promote_never_mode_goes_ready(self, tmp_path):
        """spec_review_mode: never → 跳过评审直通 ready（全通道恢复旧行为）。"""
        proot = self._make_drafted_project(tmp_path)
        # 写入项目配置（never 模式）
        (proot / ".fenix" / "config.yaml").write_text(
            "gates:\n  spec_review_mode: never\n", encoding="utf-8"
        )
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, body = srv.post("/api/spec-promote?project=proj-a&spec=draft-spec")
            assert status == 200
            assert body["ok"] is True
            assert body.get("next_status") == "ready"
            entry = dash_data.parse_state(proot)["draft-spec"]
            assert entry["status"] == "ready"
        finally:
            srv.stop()

    def test_promote_not_found(self, tmp_path):
        """spec 不存在 → 404。"""
        proot = self._make_drafted_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, _ = srv.post("/api/spec-promote?project=proj-a&spec=ghost")
            assert status == 404
        finally:
            srv.stop()

    def test_promote_unknown_project(self, tmp_path):
        """project 不存在 → 404。"""
        proot = self._make_drafted_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, _ = srv.post("/api/spec-promote?project=ghost&spec=draft-spec")
            assert status == 404
        finally:
            srv.stop()

    def test_promote_non_drafted_rejected(self, tmp_path):
        """非 drafted 状态拒绝：spec 保持原状态且 STATE 不变更。"""
        proot = self._make_drafted_project(tmp_path)
        # 先把 draft-spec 晋升为 ready
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.transition("draft-spec", "ready")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, body = srv.post("/api/spec-promote?project=proj-a&spec=draft-spec")
            assert status == 200
            assert body["ok"] is False
            assert "ready" in body["reason"]
            entry = dash_data.parse_state(proot)["draft-spec"]
            assert entry["status"] == "ready"  # 状态不变更
        finally:
            srv.stop()

    def test_promote_lint_violation_writes_state_error(self, tmp_path):
        """lint 违规：返回 violations，STATE error 写入，SPEC 停留 drafted。"""
        proot = self._make_drafted_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            # Mock promote_drafted to return violations（直接注入违规，避免依赖 lint 实现）
            import core.dashboard.data as dash_data
            original_fn = dash_data.promote_spec
            def mock_promote(pr, sn):
                return {"ok": False, "found": True, "violations": ["bad path declaration"]}
            dash_data.promote_spec = mock_promote
            try:
                status, body = srv.post("/api/spec-promote?project=proj-a&spec=draft-spec")
                assert status == 200
                assert body["ok"] is False
                assert body["violations"] == ["bad path declaration"]
            finally:
                dash_data.promote_spec = original_fn
        finally:
            srv.stop()


# ── SPEC 重新评审 API（add-spec-review-gate 4.5 / 7.8） ──────────────

class TestSpecReReviewAPI:
    """POST /api/spec-re-review：评审相关 blocked → reviewing 重新评审。"""

    def _make_blocked_project(self, tmp_path, spec_name="blocked-spec",
                              error="spec-review-rejected: 方向性风险"):
        """构造含评审相关 blocked spec 的项目。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(spec_name, {"status": "blocked", "error": error})
        return proot

    def _server(self, tmp_path, proot):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        return _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_re_review_success(self, tmp_path):
        """评审相关 blocked → 重新评审成功（blocked → reviewing）。"""
        proot = self._make_blocked_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=blocked-spec")
            assert status == 200
            assert body["ok"] is True
            entry = dash_data.parse_state(proot)["blocked-spec"]
            assert entry["status"] == "reviewing"
        finally:
            srv.stop()

    def test_re_review_spec_not_found(self, tmp_path):
        """spec 不存在 → 404。"""
        proot = self._make_blocked_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, _ = srv.post("/api/spec-re-review?project=proj-a&spec=ghost")
            assert status == 404
        finally:
            srv.stop()

    def test_re_review_project_not_found(self, tmp_path):
        """project 不存在 → 404。"""
        proot = self._make_blocked_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, _ = srv.post("/api/spec-re-review?project=ghost&spec=blocked-spec")
            assert status == 404
        finally:
            srv.stop()

    def test_re_review_non_review_blocked_rejected(self, tmp_path):
        """非评审前缀 blocked（如熔断）→ 400 + 明确原因，状态不变。"""
        proot = self._make_blocked_project(tmp_path, error="merge-breaker: 熔断")
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=blocked-spec")
            assert status == 400
            assert "评审" in body["error"]
            entry = dash_data.parse_state(proot)["blocked-spec"]
            assert entry["status"] == "blocked"
        finally:
            srv.stop()

    def test_re_review_frozen_rejected(self, tmp_path):
        """冻结态 blocked → 400 拒绝（冻结保护双层之一）。"""
        proot = self._make_blocked_project(tmp_path)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("blocked-spec", {"frozen": True})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=blocked-spec")
            assert status == 400
            assert "冻结" in body["error"]
            entry = dash_data.parse_state(proot)["blocked-spec"]
            assert entry["frozen"] is True
            assert entry["status"] == "blocked"
        finally:
            srv.stop()

    def test_re_review_incomplete_prefix_allowed(self, tmp_path):
        """spec-review-incomplete: 前缀同样可重新评审（两类 blocked 均开放）。"""
        proot = self._make_blocked_project(tmp_path,
                                            error="spec-review-incomplete: 结果文件缺失")
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=blocked-spec")
            assert status == 200
            assert body["ok"] is True
            entry = dash_data.parse_state(proot)["blocked-spec"]
            assert entry["status"] == "reviewing"
        finally:
            srv.stop()

    def test_re_review_non_blocked_state_rejected(self, tmp_path):
        """非 blocked 状态（ready/drafted）→ 400 拒绝（开放条件要求状态为 blocked）。
        代办：Agent 场景按状态枚举全表列置——评审开放条件四类拒绝（非 blocked /
        非评审前缀 / 冻结 / 幂等重复调用）在 TestReReviewConditions 已覆盖单元层，
        此处验证 HTTP 层对非 blocked 的拒绝语义。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec("ready-spec", {"status": "ready"})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=ready-spec")
            assert status == 400
            assert body["error"]
            assert dash_data.parse_state(proot)["ready-spec"]["status"] == "ready"
        finally:
            srv.stop()


# ── SPEC 审批推送 API（add-spec-approve-push-modal Task 5.2/5.3） ────

class TestSpecTaskReflowAPI:
    """POST /api/spec-task-reflow：task-gap 滞留 verified SPEC 回炉的 HTTP 语义。

    fix-impl-tasks-completion-gate D8/7.2：错误语义对齐 spec-error-clear /
    spec-freeze-config 家族（project/spec 404、拒绝返回明确原因、成功 ok:true）。
    """

    def _make_verified_taskgap_project(self, tmp_path, spec_name="stuck-spec"):
        """构造含 verified + task-gap error 的 spec 项目。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(spec_name, {
            "status": "verified",
            "error": "task-gap:未完成任务：4.5、5.1",
        })
        return proot

    def _server(self, tmp_path, proot):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        return _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_reflow_success(self, tmp_path):
        """合规形态（verified + task-gap 前缀 + 未冻结）→ ok:true、status=ready。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200
            assert body["ok"] is True
            assert body["status"] == "ready"
            entry = dash_data.parse_state(proot)["stuck-spec"]
            assert entry["status"] == "ready"
            assert entry["error"] in (None, "")
        finally:
            srv.stop()

    def test_reflow_project_404(self, tmp_path):
        """project 不存在 → 404。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=nope&spec=stuck-spec")
            assert status == 404
        finally:
            srv.stop()

    def test_reflow_spec_404(self, tmp_path):
        """spec 不存在 → 404（不产生状态写入）。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=ghost")
            assert status == 404
            assert "not found" in body.get("error", "").lower() or \
                "not found" in body.get("message", "").lower()
        finally:
            srv.stop()

    def test_reflow_non_verified_rejected(self, tmp_path):
        """非 verified 状态 → 明确拒绝原因（status 不变）。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("stuck-spec", {"status": "ready"})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200
            assert body["ok"] is False
            assert "当前状态为 'ready'" in body["reason"]
            assert dash_data.parse_state(proot)["stuck-spec"]["status"] == "ready"
        finally:
            srv.stop()

    def test_reflow_error_not_task_gap_rejected(self, tmp_path):
        """verified 但 error 非 task-gap 前缀 → 明确拒绝原因。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("stuck-spec", {"error": "spec-review-rejected: x"})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200
            assert body["ok"] is False
            assert "task-gap" in body["reason"]
        finally:
            srv.stop()

    def test_reflow_frozen_rejected(self, tmp_path):
        """冻结态 → 明确拒绝原因。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("stuck-spec", {"frozen": True})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200
            assert body["ok"] is False
            assert "冻结" in body["reason"]
        finally:
            srv.stop()

    def test_reflow_idempotent_second_call_rejected(self, tmp_path):
        """幂等重复调用：第二次（已复位 ready）→ 拒绝且无重复日志。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200 and body["ok"] is True
            log_path = proot / ".fenix" / "PROJECT_LOG.md"
            log_before = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            status2, body2 = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status2 == 200
            assert body2["ok"] is False
            log_after = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            assert log_after == log_before
        finally:
            srv.stop()


class TestSpecApprovePushAPI:
    """POST /api/spec-approve-push：done SPEC 审批推送的 HTTP 全分支语义。"""

    def _make_done_project(self, tmp_path, spec_name="done-spec"):
        """构造含 done spec 的项目。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(spec_name, {"status": "done"})
        return proot

    def _server_for(self, proot, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        return _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_approve_push_success_200(self, tmp_path, monkeypatch):
        """成功：200 + {ok: true, project, spec, created}。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # fix-supervisor-hosting-chain D8：消费方判据升级为托管态（managed）——
        # 测试环境无真实 supervisor，patch 托管态以验证成功写入路径
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status == 200
            assert body["ok"] is True
            assert body["project"] == "proj-a"
            assert body["spec"] == "done-spec"
            assert isinstance(body["created"], str)
        finally:
            srv.stop()

    def test_approve_push_spec_not_found_404(self, tmp_path, monkeypatch):
        """spec 不存在 → 404。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=ghost")
            assert status == 404
        finally:
            srv.stop()

    def test_approve_push_unknown_project_404(self, tmp_path, monkeypatch):
        """project 不存在 → 404。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=ghost&spec=done-spec")
            assert status == 404
        finally:
            srv.stop()

    def test_approve_push_non_done_ready_403(self, tmp_path, monkeypatch):
        """status=ready → 403，文案含「仅 done 状态可审批推送」与当前状态。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec("ready-spec", {"status": "ready"})
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=ready-spec")
            assert status == 403
            assert "仅 done 状态可审批推送" in body["error"]
            assert "ready" in body["error"]
        finally:
            srv.stop()

    def test_approve_push_pushed_403(self, tmp_path, monkeypatch):
        """status=pushed → 403，文案含「已推送」。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec("pushed-spec", {"status": "pushed"})
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=pushed-spec")
            assert status == 403
            assert "已推送" in body["error"]
        finally:
            srv.stop()

    def test_approve_push_daemon_down_409(self, tmp_path, monkeypatch):
        """daemon 未运行 → 409，文案含「daemon 未运行」。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: False)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status == 409
            assert "daemon 未运行" in body["error"]
        finally:
            srv.stop()

    def test_approve_push_conflict_409(self, tmp_path, monkeypatch):
        """已有未消费信号 → 409 冲突。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # fix-supervisor-hosting-chain D8：消费方判据升级为托管态，成功路径须
        # 托管态为 managed（测试环境无真实 supervisor）
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status1, body1 = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status1 == 200
            assert body1["ok"] is True
            status2, body2 = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status2 == 409
            assert "已有进行中的审批推送请求" in body2["error"]
        finally:
            srv.stop()

    def test_approve_push_body_keys_aligned_with_budget(self, tmp_path, monkeypatch):
        """响应体键断言对齐 budget/promote API 测试风格：ok/project/spec 三键必须存在。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # fix-supervisor-hosting-chain D8：托管态 managed 才走成功写入路径
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status == 200
            assert "ok" in body
            assert "project" in body
            assert "spec" in body
            assert "created" in body
        finally:
            srv.stop()

    def test_approve_push_missing_spec_query_404(self, tmp_path, monkeypatch):
        """缺少 spec query 参数 → 404。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a")
            assert status == 404
        finally:
            srv.stop()

    def test_approve_push_idempotent_two_calls_second_409(self, tmp_path, monkeypatch):
        """Task 5.3：连续两次调用（中间不消费）→ 第二次 409。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # fix-supervisor-hosting-chain D8：托管态 managed 才走成功写入路径
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status1, _ = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status1 == 200
            status2, body2 = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status2 == 409
            assert body2["error"]
        finally:
            srv.stop()


# ── keep-alive 错误路径连接卫生（BUG-01 回归锁，refactor-giant-classes 修复轮） ──
class TestKeepAliveErrorPathHygiene:
    """keep-alive 连接复用下错误路径响应写序/请求体排空（BUG-01 回归锁）。

    验证场景 api-post-chain-spec-evolution / api-spec-detail-doc-error-paths
    在 httpx/http.client 连接复用（keep-alive）下暴露的两个缺陷：
    - POST handler 错误路径（project/spec 校验失败）未消费请求体 → 残留字节
      被同连接下一请求当请求行读取，解析为 ``{...}POST ...`` 非法命令 → 501；
    - ``_get_spec_doc`` 适配器对已自写 ``_error`` 的 handler 再包 ``_json(None)``
      → 双重响应残留 200+null 污染同连接下一请求。
    修复后同连接连续请求均返回正确状态且连接不脱同步（will_close=False）。
    """

    def test_post_error_paths_keep_alive_connection_clean(self, server_fx):
        """三个错误路径 POST 走同一 keep-alive 连接，均返回正确状态且不脱同步。"""
        _, srv = server_fx
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            steps = [
                ("/api/spec-error-clear", 404),
                ("/api/spec-error-clear?project=no-such-project-xyz&spec=x", 404),
                ("/api/evolution/reject", 400),
            ]
            for i, (path, expect) in enumerate(steps):
                body = b"{}"
                conn.request(
                    "POST", path, body=body,
                    headers={"Content-Type": "application/json",
                             "Content-Length": str(len(body))},
                )
                resp = conn.getresponse()
                data = resp.read()
                assert resp.status == expect, (
                    f"step{i+1} {path}: 期望{expect} 实际{resp.status} {data[:80]!r}"
                )
                assert resp.will_close is False, (
                    f"step{i+1} {path}: 连接被关闭/脱同步（残留 body 污染）"
                )
        finally:
            conn.close()

    def test_spec_doc_error_paths_keep_alive_no_double_write(self, server_fx):
        """GET spec-doc 错误路径单响应；同连接下一请求不被残留 200+null 污染。"""
        _, srv = server_fx
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            conn.request("GET", "/api/spec-doc")
            resp = conn.getresponse()
            data = resp.read()
            assert resp.status == 400
            assert b"unknown project" in data

            # 同连接第二请求：不得读到上一请求的双重写残留（200+null）
            conn.request("GET", "/api/spec-doc?project=no-such-project-xyz&spec=x&doc=proposal")
            resp = conn.getresponse()
            data = resp.read()
            assert resp.status == 400
            assert b"unknown project" in data

            # 连接仍健康：正常端点可用
            conn.request("GET", "/api/events?project=proj-a")
            resp = conn.getresponse()
            data = resp.read()
            assert resp.status == 200
        finally:
            conn.close()

    def test_spec_doc_success_path_keep_alive(self, server_fx):
        """成功路径 spec-doc 与错误路径交替走同连接，互不污染。"""
        proot, srv = server_fx
        (proot / "spec" / "changes" / "myspec" / "proposal.md").write_text(
            "# 背景\n\n- 列表项\n", encoding="utf-8"
        )
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            # 错误路径（未注册项目 → 400）
            conn.request("GET", "/api/spec-doc?project=no-such-project-xyz&spec=x&doc=proposal")
            resp = conn.getresponse()
            assert resp.status == 400
            resp.read()
            # 成功路径（同连接）
            conn.request("GET", "/api/spec-doc?project=proj-a&spec=myspec&doc=proposal")
            resp = conn.getresponse()
            data = resp.read()
            assert resp.status == 200
            assert "背景".encode("utf-8") in data
        finally:
            conn.close()
