"""test-dashboard-knowledge-api — 项目知识真相源只读 API 冒烟
（add-knowledge-atlas 3.2）。

覆盖（spec「后端只读 API」）：
- GET /api/knowledge/index：未初始化占位结构 / 初始化后 index_md + 域清单
- GET /api/knowledge/file：白名单内读取；``..`` 穿越 / 绝对路径 / 反斜杠 /
  越界前缀恒 400（先于存在性判断）；白名单内文件缺失 404
- 未知项目 404
（GET /api/knowledge/graph 已随 graphify 功能取消下线，对应用例移除——2026-09-29。）

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

    def test_adr_list_title_field(self, tmp_path):
        """ADR 列表标题字段（验证打回 BUG-01 修复）：title 取 ADR 文件首
        标题 ``# ADR-NNN：<标题>``（半/全角冒号），缺失时以 adr/index.md
        表格标题列兜底，两处皆无为 null。"""
        proot = make_project(tmp_path)
        k = proot / "spec" / "knowledge"
        (k / "adr").mkdir(parents=True)
        (k / "index.md").write_text("# 总目录\n", encoding="utf-8")
        (k / "adr" / "index.md").write_text(
            "# ADR 索引\n\n"
            "| 编号 | 标题 | 状态 | 摘要 |\n| --- | --- | --- | --- |\n"
            "| ADR-001 | zn-adr-one-title | superseded | 旧裁定 |\n"
            "| ADR-003 | zn-adr-three-title | superseded | 兜底裁定 |\n",
            encoding="utf-8",
        )
        (k / "adr" / "ADR-001-zn-one.md").write_text(
            "status: superseded\nSuperseded by: ADR-002\n日期: 2026-09-27\n\n"
            "# ADR-001: zn-adr-one-title\n\n## Context\nctx\n\n"
            "## Decision\n\n## Consequences\n",
            encoding="utf-8",
        )
        (k / "adr" / "ADR-002-zn-two.md").write_text(
            "status: accepted\n日期: 2026-09-27\n\n"
            "# ADR-002：zn-adr-two-title\n\n## Context\nctx\n\n"
            "## Decision\n\n## Consequences\n",
            encoding="utf-8",
        )
        # 无首标题：表格标题列兜底
        (k / "adr" / "ADR-003-zn-three.md").write_text(
            "status: superseded\nSuperseded by: ADR-002\n\n"
            "## Context\nctx\n\n## Decision\n\n## Consequences\n",
            encoding="utf-8",
        )
        # 无首标题且不在表格：null
        (k / "adr" / "ADR-004-zn-four.md").write_text(
            "status: accepted\n\n## Context\nctx\n\n## Decision\n\n## Consequences\n",
            encoding="utf-8",
        )
        srv = _server(tmp_path, proot)
        try:
            status, body = srv.get("/api/knowledge/index?project=proj-a")
            assert status == 200
            adrs = {a["file"]: a for a in body["adrs"]}
            assert adrs["ADR-001-zn-one.md"] == {
                "file": "ADR-001-zn-one.md",
                "title": "zn-adr-one-title",
                "status": "superseded",
                "superseded_by": "ADR-002",
            }
            assert adrs["ADR-002-zn-two.md"]["title"] == "zn-adr-two-title"
            assert adrs["ADR-003-zn-three.md"]["title"] == "zn-adr-three-title"
            assert adrs["ADR-004-zn-four.md"]["title"] is None
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
