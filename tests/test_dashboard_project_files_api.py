"""test-dashboard-project-files-api — 项目文件浏览三通道后端测试
（add-project-home-tab 5.1）。

覆盖（specs/project-home-tab/spec.md「路径越界防护与项目校验」/「git 属性
展示」/「文件内容查看与下载」/「README 渲染」/「非 git 项目空态」）：

- list 根目录形态：目录先行 + 名称不分大小写升序、latest/branch/readme 附带、
  条目级 last_commit（含无历史条目 null）、gitignored（node_modules / .fenix /
  自定义 ignore 目录）不入列表、未跟踪文件（--others）入列表
- list 子目录导航：多级 path、目录内条目、文件路径请求 list → 404（非目录
  不经列表通道）、集合外路径（gitignored）→ 404
- 截断：221 条目目录 → 200 + truncated_count
- 路径防护：``..`` 越界 / 绝对路径 / ``.git`` 内路径一律 400（泛化文案
  Invalid path，响应体不回显路径细节）
- content：文本内容与 lines/bytes、256 KiB 截断（bytes 恒 stat 实值）、
  二进制（NUL 判定）binary=true 无 content、目录 400、缺失 404
- download：attachment 头 + RFC 5987 filename*（含中文名百分号编码）+
  nosniff + Content-Length 实值 + 字节回读一致
- 非 git 项目：non_git=true 空 entries、branch/latest/readme 全 null
- 项目校验：未知项目 404、缺 project 参数 400
- 缓存失效：``.git/index`` mtime 翻转（git add）后新文件即刻可见

夹具对齐 test_dashboard_architecture_api.py：Registry + _TestServer 进程内
装配（不落真端口冲突），``git symbolic-ref`` 固定分支名消除 init 缺省分支
的版本差异。数据模块缓存以项目根绝对路径为键，tmp_path 隔离天然不串。
"""

import subprocess
import sys
import urllib.parse
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


def _git(proot: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=str(proot), capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _git_commit_all(proot: Path, message: str = "init") -> None:
    _git(proot, "add", "-A")
    _git(proot, "commit", "-q", "-m", message)


def _repo_with_fixture_tree(proot: Path) -> None:
    """init git 仓（分支固定 main）+ 提交一批覆盖性文件：
    嵌套目录 / 根文件 / 中文文件名 / 二进制文件 / .gitignore（含 .fenix 与
    node_modules）；另留一个未跟踪文件（--others 口径）与一个 gitignored
    目录内容。"""
    _git(proot, "init", "-q")
    # 固定分支名：git init 缺省分支名随版本/配置漂移（master/main）
    _git(proot, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(proot, "config", "user.email", "test@example.com")
    _git(proot, "config", "user.name", "test")

    (proot / ".gitignore").write_text(
        ".fenix/\nnode_modules/\nignored/\ndist/\n", encoding="utf-8"
    )
    (proot / "README.md").write_text("# 测试仓库\n\n正文。\n", encoding="utf-8")
    (proot / "notes.txt").write_text("第一行\n第二行\n", encoding="utf-8")
    (proot / "说明.md").write_text("# 中文名文件\n", encoding="utf-8")
    nested = proot / "core" / "dashboard"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "server.py").write_text("print('server')\n", encoding="utf-8")
    bindir = proot / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    _git_commit_all(proot, "init")

    # 未跟踪（不在索引但非 ignored）→ ls-files --others 应列出
    (proot / "untracked.txt").write_text("fresh\n", encoding="utf-8")
    # gitignored 目录内容 → 永不入列表
    ig = proot / "node_modules" / "pkg"
    ig.mkdir(parents=True, exist_ok=True)
    (ig / "x.js").write_text("// js\n", encoding="utf-8")


BINARY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_list_root_shape_and_order(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/list?project=proj-a")
    assert status == 200
    assert body["non_git"] is False
    assert body["branch"] == "main"
    assert body["readme"] == "README.md"
    latest = body["latest"]
    assert latest is not None
    assert latest["author"] == "test"
    assert 0 < len(latest["hash"]) <= 10
    assert "T" in latest["time"]  # ISO 时间

    names = [e["name"] for e in body["entries"]]
    dirs = [e["name"] for e in body["entries"] if e["dir"]]
    files = [e["name"] for e in body["entries"] if not e["dir"]]
    # 目录先行 + 各组名称不分大小写升序（make_project 自带 spec/ 等未跟踪
    # 目录也在集合内，故断言顺序不变量与成员而非全量等值）
    assert names == dirs + files
    assert dirs == sorted(dirs, key=str.lower)
    assert files == sorted(files, key=str.lower)
    for must in ("bin", "core", "notes.txt", "README.md", "untracked.txt", "说明.md"):
        assert must in names, f"{must} 应在根目录条目内"
    # gitignored 与 .git 永不入列表；.gitignore 本身是已提交可见文件
    for banned in ("node_modules", "ignored", ".fenix", ".git"):
        assert banned not in names
    assert ".gitignore" in names
    # gitignored 内容目录被排除的自证：条目全集里不含其子路径
    assert all(not n.startswith("node_modules") for n in names)

    by_name = {e["name"]: e for e in body["entries"]}
    # 已提交条目带最近提交属性；未跟踪条目无历史 → null
    assert by_name["notes.txt"]["last_commit"]["message"] == "init"
    assert by_name["notes.txt"]["last_commit"]["hash"]
    assert by_name["untracked.txt"]["last_commit"] is None
    # 目录条目取该目录下最近提交
    assert by_name["core"]["dir"] is True
    assert by_name["core"]["last_commit"]["message"] == "init"


def test_list_subdirectory_navigation(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/list?project=proj-a&path=core")
    assert status == 200
    assert [e["name"] for e in body["entries"]] == ["dashboard"]
    # 子目录查询不附带 latest/readme（仅根目录附带）
    assert body["latest"] is None
    assert body["readme"] is None

    status, body = srv.get("/api/project-files/list?project=proj-a&path=core/dashboard")
    assert status == 200
    entry = body["entries"][0]
    assert entry["name"] == "server.py" and entry["dir"] is False
    assert entry["last_commit"]["message"] == "init"


def test_list_unknown_and_file_paths_404(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    # 集合外目录（不存在）
    status, body = srv.get("/api/project-files/list?project=proj-a&path=ghost")
    assert status == 404 and body["error"] == "path not found"
    # 文件路径请求 list → 非目录不经列表通道
    status, body = srv.get("/api/project-files/list?project=proj-a&path=notes.txt")
    assert status == 404
    # gitignored 目录在磁盘存在但不在集合 → 404（列表不服务 gitignored）
    status, body = srv.get("/api/project-files/list?project=proj-a&path=node_modules")
    assert status == 404


def test_list_truncation_at_200(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    big = proot / "many"
    big.mkdir()
    for i in range(221):
        (big / f"f{i:03d}.txt").write_text("x\n", encoding="utf-8")
    _git_commit_all(proot, "add many files")
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/list?project=proj-a&path=many")
    assert status == 200
    assert body["truncated_count"] == 21
    assert len(body["entries"]) == 200
    # 截断保序：200 项为升序前缀（目录先行，本目录全为文件）
    assert [e["name"] for e in body["entries"]] == sorted(
        (e["name"] for e in body["entries"]), key=str.lower
    )
    assert body["entries"][0]["name"] == "f000.txt"


def test_list_path_escape_400(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    for bad in ("../../x", "/etc/passwd", ".git/config", "core/../../out"):
        q = urllib.parse.quote(bad, safe="")
        status, body = srv.get(f"/api/project-files/list?project=proj-a&path={q}")
        assert status == 400, f"path={bad!r} 应 400，实得 {status}"
        # 泛化文案：不回显路径细节
        assert body["error"] == "Invalid path"
        assert "proj" not in body["error"] and bad not in body["error"]


def test_content_text_truncation_binary(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    # 文本：内容与行数
    status, body = srv.get("/api/project-files/content?project=proj-a&path=notes.txt")
    assert status == 200
    assert body == {
        "content": "第一行\n第二行\n", "lines": 2, "bytes": len("第一行\n第二行\n".encode()),
        "truncated": False, "binary": False,
    }

    # 256 KiB 截断：内容 262144 字节、bytes 恒 stat 实值
    big = proot / "big.txt"
    big.write_text("a" * (300 * 1024), encoding="utf-8")
    _git_commit_all(proot, "add big file")
    status, body = srv.get("/api/project-files/content?project=proj-a&path=big.txt")
    assert status == 200
    assert body["truncated"] is True and body["binary"] is False
    assert len(body["content"]) == 256 * 1024
    assert body["bytes"] == 300 * 1024

    # 二进制：NUL 判定，无 content
    status, body = srv.get("/api/project-files/content?project=proj-a&path=bin/logo.png")
    assert status == 200
    assert body["binary"] is True and body["content"] is None
    assert body["bytes"] == len(BINARY_PNG)


def test_content_dir_400_and_missing_404(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/content?project=proj-a&path=core")
    assert status == 400 and body["error"] == "path is a directory"

    status, body = srv.get("/api/project-files/content?project=proj-a&path=ghost.txt")
    assert status == 404 and body["error"] == "file not found"

    # 越界同样 400（content 通道共用 containment 单点）
    status, body = srv.get(
        "/api/project-files/content?project=proj-a&path="
        + urllib.parse.quote("../../etc/passwd", safe="")
    )
    assert status == 400 and body["error"] == "Invalid path"


def test_download_headers_and_roundtrip(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    path = urllib.parse.quote("notes.txt", safe="")
    status, headers, body = srv.get_ex(
        f"/api/project-files/download?project=proj-a&path={path}"
    )
    assert status == 200
    assert headers["Content-Type"] == "application/octet-stream"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Disposition"] == "attachment; filename*=UTF-8''notes.txt"
    expect = (proot / "notes.txt").read_bytes()
    assert headers["Content-Length"] == str(len(expect))
    assert body == expect

    # 中文名 RFC 5987 百分号编码
    path = urllib.parse.quote("说明.md", safe="")
    status, headers, _body = srv.get_ex(
        f"/api/project-files/download?project=proj-a&path={path}"
    )
    assert status == 200
    assert headers["Content-Disposition"] == (
        "attachment; filename*=UTF-8''%E8%AF%B4%E6%98%8E.md"
    )


def test_download_dir_400_and_escape(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/download?project=proj-a&path=core")
    assert status == 400 and body["error"] == "path is a directory"

    status, body = srv.get(
        "/api/project-files/download?project=proj-a&path="
        + urllib.parse.quote("../secret", safe="")
    )
    assert status == 400 and body["error"] == "Invalid path"


def test_non_git_project_empty_shape(tmp_path):
    proot = make_project(tmp_path)  # 不 init git
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/list?project=proj-a")
    assert status == 200
    assert body["non_git"] is True
    assert body["entries"] == []
    assert body["branch"] is None and body["latest"] is None and body["readme"] is None
    assert "truncated_count" not in body


def test_project_validation(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/list?project=ghost-proj")
    assert status == 404 and body["error"] == "project not found"

    status, body = srv.get("/api/project-files/list")
    assert status == 400


def test_cache_invalidated_by_index_mtime(tmp_path):
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/list?project=proj-a")
    assert status == 200
    assert "later.txt" not in [e["name"] for e in body["entries"]]

    # 新文件 + git add（翻 .git/index mtime）→ 缓存失效，即刻可见（不等 30s TTL）
    (proot / "later.txt").write_text("later\n", encoding="utf-8")
    _git(proot, "add", "later.txt")
    status, body = srv.get("/api/project-files/list?project=proj-a")
    assert status == 200
    assert "later.txt" in [e["name"] for e in body["entries"]]
