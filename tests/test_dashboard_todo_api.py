"""Dashboard /api/todo 端点测试（设置页「自省」面板 todo.md 查看与编辑）。

todo.md 为项目级文件（<项目根>/.fenix/todo.md），端点路径固定、
不接受任意路径参数：缺 project 400、项目未知 404、content 非字符串 400。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def todo_server(tmp_path):
    """DashboardHTTPServer 测试实例（复用 test_dashboard_api 的夹具）。"""
    from test_dashboard_api import _TestServer, make_project
    from core.dashboard.registry import Registry
    proot = make_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()


class TestTodoAPI:
    """GET/POST /api/todo — todo.md 读取与整文件覆写。"""

    def test_get_missing_file_returns_empty(self, todo_server):
        proot, srv = todo_server
        status, data = srv.get("/api/todo?project=proj-a")
        assert status == 200
        assert data["project"] == "proj-a"
        assert data["content"] == ""
        assert data["exists"] is False

    def test_get_returns_saved_content(self, todo_server):
        proot, srv = todo_server
        (proot / ".fenix" / "todo.md").write_text(
            "## 2026-09-04\n\n### 浪费\n- 证据：某条目\n", encoding="utf-8")
        status, data = srv.get("/api/todo?project=proj-a")
        assert status == 200
        assert data["exists"] is True
        assert "### 浪费" in data["content"]
        assert "某条目" in data["content"]

    def test_post_creates_and_saves(self, todo_server):
        proot, srv = todo_server
        status, data = srv.post_json(
            "/api/todo?project=proj-a", {"content": "## 2026-09-05\n\n### 可改进\n- 新条目\n"})
        assert status == 200 and data["ok"] is True
        saved = proot / ".fenix" / "todo.md"
        assert saved.is_file()
        assert "新条目" in saved.read_text(encoding="utf-8")

    def test_post_overwrites_existing(self, todo_server):
        proot, srv = todo_server
        (proot / ".fenix" / "todo.md").write_text("旧内容\n", encoding="utf-8")
        srv.post_json("/api/todo?project=proj-a", {"content": "全量覆写\n"})
        assert (proot / ".fenix" / "todo.md").read_text(encoding="utf-8") == "全量覆写\n"

    def test_get_requires_project(self, todo_server):
        _, srv = todo_server
        status, _ = srv.get("/api/todo")
        assert status == 400

    def test_post_requires_project(self, todo_server):
        _, srv = todo_server
        status, _ = srv.post_json("/api/todo", {"content": "x"})
        assert status == 400

    def test_unknown_project_404(self, todo_server):
        _, srv = todo_server
        status, _ = srv.get("/api/todo?project=ghost")
        assert status == 404
        status, _ = srv.post_json("/api/todo?project=ghost", {"content": "x"})
        assert status == 404

    def test_post_content_must_be_string(self, todo_server):
        _, srv = todo_server
        for bad in (123, None, ["x"], {"c": 1}):
            status, _ = srv.post_json("/api/todo?project=proj-a", {"content": bad})
            assert status == 400, f"content={bad!r} 应被拒绝"
