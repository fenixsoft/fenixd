"""test-dashboard-knowledge-api — 项目知识真相源只读 API 冒烟
（add-knowledge-atlas 3.2）。

覆盖（spec「后端只读 API」）：
- GET /api/knowledge/index：未初始化占位结构 / 初始化后 index_md + 域清单
- GET /api/knowledge/file：白名单内读取；``..`` 穿越 / 绝对路径 / 反斜杠 /
  越界前缀恒 400（先于存在性判断）；白名单内文件缺失 404
- GET /api/knowledge/graph：缺失 404 结构化错误；存在下发 text/html
- 未知项目 404

装配对齐 test_dashboard_architecture_api.py：_TestServer 起真实 HTTP
实例（conftest），Registry 指向 tmp 项目；全程零写路径，不触蒸馏管线。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import _TestServer, make_project  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402


def _registry(tmp_path, proot):
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    return reg


def _server(tmp_path, proot):
    static = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
    return _TestServer(_registry(tmp_path, proot), static)


def _write_knowledge(proot: Path):
    """布防一份最小合法真相源（index + 一域一页 + ADR）。"""
    k = proot / "spec" / "knowledge"
    (k / "domains" / "pickup").mkdir(parents=True)
    (k / "index.md").write_text(
        "# 总目录\n\n- [拣选域](domains/pickup/_domain.md)\n", encoding="utf-8"
    )
    (k / "domains" / "pickup" / "_domain.md").write_text(
        "# 拣选域\n\n- [定时拣选](scheduled-spec-pickup.md)\n", encoding="utf-8"
    )
    (k / "domains" / "pickup" / "scheduled-spec-pickup.md").write_text(
        "# 定时拣选\n\n<!-- knowledge: capability=scheduled-spec-pickup rev=1\n"
        "     sources=spec/archive/x -->\n\n规则。\n",
        encoding="utf-8",
    )
    (k / "adr").mkdir()
    (k / "adr" / "index.md").write_text("- [ADR-001](ADR-001-x.md) accepted\n", encoding="utf-8")


class TestKnowledgeIndexAPI:
    def test_uninitialized_placeholder(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/knowledge/index?project=proj-a")
            assert status == 200
            assert body["initialized"] is False
            assert body["index_md"] is None
            assert body["domains"] == []
        finally:
            srv.stop()

    def test_initialized_lists_domains(self, tmp_path):
        proot = make_project(tmp_path)
        _write_knowledge(proot)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/knowledge/index?project=proj-a")
            assert status == 200
            assert body["initialized"] is True
            assert "总目录" in body["index_md"]
            assert body["domains"] == [
                {"name": "pickup",
                 "pages": ["scheduled-spec-pickup.md"],
                 "nav_exists": True}
            ]
        finally:
            srv.stop()

    def test_unknown_project_404(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, _ = srv.get("/api/knowledge/index?project=nope")
            assert status == 404
        finally:
            srv.stop()


class TestKnowledgeFileAPI:
    def test_reads_whitelisted_file(self, tmp_path):
        proot = make_project(tmp_path)
        _write_knowledge(proot)
        srv = _server(tmp_path, proot)
        try:
            from urllib.parse import quote
            status, body = srv.get(
                "/api/knowledge/file?project=proj-a&path="
                + quote("domains/pickup/scheduled-spec-pickup.md")
            )
            assert status == 200
            assert body["path"] == "domains/pickup/scheduled-spec-pickup.md"
            assert "scheduled-spec-pickup" in body["content"]
        finally:
            srv.stop()

    def test_path_traversal_always_400(self, tmp_path):
        """``..`` / 绝对路径 / 反斜杠 / 越界前缀恒 400（不泄露存在性）。"""
        proot = make_project(tmp_path)
        _write_knowledge(proot)
        srv = _server(tmp_path, proot)
        try:
            from urllib.parse import quote
            for bad in [
                "domains/../../secret.md",
                "../spec/knowledge/index.md",
                "..%2F..%2Fetc%2Fpasswd",
                "/etc/passwd",
                "domains\\pickup\\x.md",
                "spec/archive/x/proposal.md",  # 白名单外前缀
                "graph/graph.html",            # 白名单外前缀
                "",
            ]:
                status, _ = srv.get(
                    "/api/knowledge/file?project=proj-a&path=" + quote(bad)
                )
                assert status == 400, f"path={bad!r} 应 400，实际 {status}"
        finally:
            srv.stop()

    def test_missing_file_404(self, tmp_path):
        proot = make_project(tmp_path)
        _write_knowledge(proot)
        srv = _server(tmp_path, proot)
        try:
            from urllib.parse import quote
            status, body = srv.get(
                "/api/knowledge/file?project=proj-a&path="
                + quote("adr/ADR-999-nope.md")
            )
            assert status == 404
            assert "error" in body
        finally:
            srv.stop()


class TestKnowledgeGraphAPI:
    def test_missing_structured_error(self, tmp_path):
        proot = make_project(tmp_path)
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/knowledge/graph?project=proj-a")
            assert status == 404
            assert body["code"] == "knowledge_graph_not_generated"
        finally:
            srv.stop()

    def test_present_serves_html(self, tmp_path):
        proot = make_project(tmp_path)
        g = proot / "spec" / "knowledge" / "graph"
        g.mkdir(parents=True)
        (g / "graph.html").write_text(
            "<!DOCTYPE html><html><body>knowledge graph</body></html>",
            encoding="utf-8",
        )
        srv = _server(tmp_path, proot)
        try:
            status, ctype, raw = srv.get("/api/knowledge/graph?project=proj-a", raw=True)
            assert status == 200
            assert ctype.startswith("text/html")
            assert b"knowledge graph" in raw
        finally:
            srv.stop()
