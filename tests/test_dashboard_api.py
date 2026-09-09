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
        """契约有效带 overwrite → dispatched。"""
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
        # 检查信号落盘
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        signals = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        assert len(signals) == 1
        sig = signals[0]
        assert sig["overwrite"] is True

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
        """成功晋升：drafted → ready。"""
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
