"""
Tests for Dashboard help documentation API (add-dashboard-help-center D1/D2).

覆盖：
- GET /api/help/docs 清单正常路径（README 置顶、编号有序、标题解析）
- GET /api/help/doc  单篇正文正常路径
- 目录穿越（`..`）/ 非 .md / 不存在文档 → 拒绝（400/404）
- docs/help/ 缺失 → 清单空列表 / 单篇 404
- 目录为空 → 清单空列表
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import server as server_mod
from core.dashboard.registry import Registry
from core.dashboard.server import HELP_DOC_NAME_RE

# _TestServer 已收敛至 tests/conftest.py（get 接口签名一致）
from conftest import _TestServer


@pytest.fixture()
def server_fx(tmp_path, monkeypatch):
    from core.dashboard.server import STATIC_DIR
    proot = tmp_path / "proj-a"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    reg = Registry(config_path=tmp_path / "dashboard.yaml")
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": []})
    srv = _TestServer(reg, STATIC_DIR)
    yield proot, srv
    srv.stop()


@pytest.fixture()
def help_dir(tmp_path):
    """临时帮助文档目录，monkeypatch 掉模块常量 HELP_DOCS_DIR。"""
    d = tmp_path / "help-ct"
    d.mkdir(parents=True)
    (d / "README.md").write_text(
        "# 帮助中心\n\n指向 [快速上手](01-quick-start.md)。\n",
        encoding="utf-8",
    )
    (d / "01-quick-start.md").write_text(
        "# 快速上手\n\n正文内容。\n",
        encoding="utf-8",
    )
    (d / "02-concepts.md").write_text(
        "先写一段无标题说明再加标题\n\n# 核心概念\n\n内容。\n",
        encoding="utf-8",
    )
    (d / "03-lifecycle.md").write_text(
        "# SPEC 生命周期\n\n## 状态\n\n",
        encoding="utf-8",
    )
    (d / "notes.txt").write_text("非 md 文件，应被清单跳过", encoding="utf-8")
    return d


@pytest.fixture(autouse=True)
def _point_help_dir(tmp_path, monkeypatch):
    """autouse：默认把 HELP_DOCS_DIR 指向临时目录。

    显式传 help_dir 的用例在原 fixture 基础上再覆盖；其它用例沿用 tmp_path 下
    一个空的 help 目录（模拟 docs/help/ 存在但为空 → 空清单）。
    """
    d = tmp_path / "help"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", d)
    return d


# ── 清单端点 GET /api/help/docs ─────────────────────────────────────

class TestHelpDocsList:
    def test_list_normal(self, server_fx, help_dir, monkeypatch):
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        _, srv = server_fx
        status, data = srv.get("/api/help/docs")
        assert status == 200
        names = [d["name"] for d in data["docs"]]
        # README 置顶，其余按文件名（NN- 编号自然有序）
        assert names[0] == "README.md"
        assert names[1:] == ["01-quick-start.md", "02-concepts.md", "03-lifecycle.md"]
        # 非 .md 文件不进入清单
        assert "notes.txt" not in names

    def test_titles_parsed_from_first_h1(self, server_fx, help_dir, monkeypatch):
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        _, srv = server_fx
        status, data = srv.get("/api/help/docs")
        assert status == 200
        by_name = {d["name"]: d["title"] for d in data["docs"]}
        assert by_name["README.md"] == "帮助中心"
        assert by_name["01-quick-start.md"] == "快速上手"
        # 02 文档首个 H1 前有普通文字 → 仍取首个 H1
        assert by_name["02-concepts.md"] == "核心概念"
        assert by_name["03-lifecycle.md"] == "SPEC 生命周期"

    def test_list_explicit_order_and_unknown_append(self, server_fx, help_dir, monkeypatch):
        # 显式顺序表（HELP_DOC_ORDER）优先于文件名字典序；未列入的文档
        # 按文件名字典序追加在有序文档之后
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        monkeypatch.setattr(server_mod, "HELP_DOC_ORDER", ["03-lifecycle.md", "README.md", "01-quick-start.md"])
        _, srv = server_fx
        status, data = srv.get("/api/help/docs")
        assert status == 200
        names = [d["name"] for d in data["docs"]]
        # 顺序表内按表序；02-concepts.md 不在表内 → 追加在末尾（字典序）
        assert names == ["03-lifecycle.md", "README.md", "01-quick-start.md", "02-concepts.md"]

    def test_list_missing_dir_empty(self, server_fx, tmp_path, monkeypatch):
        missing = tmp_path / "no-such-help"
        assert not missing.exists()
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", missing)
        _, srv = server_fx
        status, data = srv.get("/api/help/docs")
        assert status == 200
        assert data["docs"] == []

    def test_list_empty_dir_empty(self, server_fx, _point_help_dir):
        _, srv = server_fx
        status, data = srv.get("/api/help/docs")
        assert status == 200
        assert data["docs"] == []

    def test_list_doc_without_title_falls_back_to_name(self, server_fx, help_dir, monkeypatch):
        # 03 文档只含 H1，标题正常；补一个无 H1 的文件验证回退
        (help_dir / "04-no-title.md").write_text("只有正文没有标题", encoding="utf-8")
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        _, srv = server_fx
        status, data = srv.get("/api/help/docs")
        assert status == 200
        by_name = {d["name"]: d["title"] for d in data["docs"]}
        assert by_name["04-no-title.md"] == "04-no-title"


# ── 单篇正文 GET /api/help/doc?name=<file> ───────────────────────────

class TestHelpDocContent:
    def test_doc_normal(self, server_fx, help_dir, monkeypatch):
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        _, srv = server_fx
        status, data = srv.get("/api/help/doc?name=01-quick-start.md")
        assert status == 200
        assert data["name"] == "01-quick-start.md"
        assert data["title"] == "快速上手"
        assert "正文内容" in data["content"]

    def test_doc_traversal_rejected(self, server_fx, help_dir, monkeypatch):
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        _, srv = server_fx
        for bad in [
            "../README.md",
            "..%2FREADME.md",
            "a/../README.md",
            "sub/README.md",       # 含路径分隔符但以 .md 结尾
            "01-quick-start.md/..",
            "",
        ]:
            status, data = srv.get(f"/api/help/doc?name={bad}")
            assert status == 400, f"{bad!r} should be rejected, got {status} {data}"

    def test_doc_non_md_rejected(self, server_fx, help_dir, monkeypatch):
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        _, srv = server_fx
        for bad in ["notes.txt", "README", "README.md.bak", "a.b", "x.md.exe"]:
            status, data = srv.get(f"/api/help/doc?name={bad}")
            assert status == 400, f"{bad!r} should be rejected, got {status} {data}"

    def test_doc_not_found(self, server_fx, help_dir, monkeypatch):
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        _, srv = server_fx
        # 白名单内但文件不存在 → 404
        status, data = srv.get("/api/help/doc?name=99-missing.md")
        assert status == 404
        assert "not found" in data["error"].lower()

    def test_doc_missing_dir_404(self, server_fx, tmp_path, monkeypatch):
        missing = tmp_path / "no-such-help"
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", missing)
        _, srv = server_fx
        status, data = srv.get("/api/help/doc?name=README.md")
        assert status == 404

    def test_doc_urlencoded_name_ok(self, server_fx, help_dir, monkeypatch):
        import urllib.parse
        monkeypatch.setattr(server_mod, "HELP_DOCS_DIR", help_dir)
        _, srv = server_fx
        # 名字含下划线/数字（白名单字符），URL 编码后仍正常
        status, data = srv.get(f"/api/help/doc?name={urllib.parse.quote('01-quick-start.md')}")
        assert status == 200
        assert data["name"] == "01-quick-start.md"


# ── 白名单正则（HELP_DOC_NAME_RE）───

class TestNameWhitelist:
    def test_valid_names(self):
        for name in ["README.md", "01-quick-start.md", "a_b-c.d.md", "10-faq.md"]:
            assert HELP_DOC_NAME_RE.match(name), name

    def test_invalid_names(self):
        for name in ["../x.md", "a/b.md", "x.txt", ".md", "README", "x.md.exe",
                     "a\nb.md", "x%2Fy.md", ""]:
            assert not HELP_DOC_NAME_RE.match(name), name