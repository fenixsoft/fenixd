"""test-dashboard-project-files-api — 项目文件浏览四通道后端测试
（add-project-home-tab 5.1 + 2026-11-10 五点增强 raw 内联通道）。

覆盖（specs/project-home-tab/spec.md「路径越界防护与项目校验」/「git 属性
展示」/「文件内容查看与下载」/「README 渲染」/「非 git 项目空态」）：

- list 根目录形态：目录先行 + 名称不分大小写升序、latest/branch/readme 附带、
  条目级 last_commit（含无历史条目 null）、gitignored 项以 hidden 条目入列
  （--directory 折叠，2026-11-11 隐藏文件通道；磁盘存在的忽略目录可导航、
  .git 永不出现、同名可见优先）、未跟踪文件（--others）入列表、条目 bytes
  （文件 stat 实值 / 目录 null——大小列数据源，2026-11-10 第二批增强）
- list 子目录导航：多级 path、目录内条目、文件路径请求 list → 404（非目录
  不经列表通道）、不存在路径 → 404
- 截断：221 条目目录 → 200 + truncated_count
- 路径防护：``..`` 越界 / 绝对路径 / ``.git`` 内路径一律 400（泛化文案
  Invalid path，响应体不回显路径细节）
- content：文本内容与 lines/bytes、256 KiB 截断（bytes 恒 stat 实值）、
  二进制（NUL 判定）binary=true 无 content、目录 400、缺失 404
- download：attachment 头 + RFC 5987 filename*（含中文名百分号编码）+
  nosniff + Content-Length 实值 + 字节回读一致
- raw：图片扩展白名单按扩展名精确下发 Content-Type（<img> 直显通道）+
  nosniff + Content-Length 实值 + 字节回读一致；svg 附 Content-Security-Policy
  sandbox（防 SVG 脚本）；非图片扩展 400、目录 400、缺失 404、越界 400
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
        ".fenix/\nnode_modules/\nignored/\ndist/\n*.log\n", encoding="utf-8"
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
    # gitignored 目录内容 → 永不入可见列表；2026-11-11 起作为 hidden 条目
    # 呈现（--directory 折叠：全忽略目录单条、忽略文件逐条）
    ig = proot / "node_modules" / "pkg"
    ig.mkdir(parents=True, exist_ok=True)
    (ig / "x.js").write_text("// js\n", encoding="utf-8")
    igdir = proot / "ignored" / "sub"
    igdir.mkdir(parents=True, exist_ok=True)
    (igdir / "deep.txt").write_text("ignored\n", encoding="utf-8")
    (proot / "stray.log").write_text("ignored log\n", encoding="utf-8")


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
    # .git 永不入列表（磁盘存在也不进 hidden 通道）；.gitignore 本身是已
    # 提交可见文件。make_project 自带的 .fenix/ 全目录被忽略 → 折叠 hidden
    for banned in (".git",):
        assert banned not in names
    assert ".gitignore" in names
    # 2026-11-11：gitignored 条目以 hidden 形态入列（--directory 折叠）
    by_name = {e["name"]: e for e in body["entries"]}
    for hidden_name in (".fenix", "node_modules", "ignored", "stray.log"):
        assert hidden_name in names, f"gitignored {hidden_name} 应以 hidden 入列"
        assert by_name[hidden_name]["hidden"] is True
    assert by_name["node_modules"]["dir"] is True
    assert by_name["node_modules"]["bytes"] is None
    assert by_name["stray.log"]["dir"] is False
    assert by_name["stray.log"]["bytes"] == (proot / "stray.log").stat().st_size
    assert by_name["stray.log"]["last_commit"] is None
    # 目录先行 + 各组名称升序在 hidden 归并后仍保持
    assert names == dirs + files
    # gitignored 内容永不作为子路径出现（只出现折叠后的直接子项）
    assert all("/" not in n for n in names)

    # 已提交条目带最近提交属性；未跟踪条目无历史 → null
    assert by_name["notes.txt"]["last_commit"]["message"] == "init"
    assert by_name["notes.txt"]["last_commit"]["hash"]
    assert by_name["untracked.txt"]["last_commit"] is None
    # 目录条目取该目录下最近提交
    assert by_name["core"]["dir"] is True
    assert by_name["core"]["last_commit"]["message"] == "init"
    # 混合目录：同名既有可见又有忽略 → 可见优先，hidden 不标灰
    assert by_name["core"]["hidden"] is not True


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
    # 2026-11-11：gitignored 目录磁盘存在即可导航（hidden 条目可进）
    status, body = srv.get("/api/project-files/list?project=proj-a&path=node_modules")
    assert status == 200
    assert [e["name"] for e in body["entries"]] == ["pkg"]
    assert body["entries"][0]["hidden"] is True
    # 磁盘不存在的 ignore 规则目录仍 404
    status, _ = srv.get("/api/project-files/list?project=proj-a&path=dist")
    assert status == 404


def test_list_entry_bytes_files_only(tmp_path):
    """大小列数据源（2026-11-10 第二批增强）：文件条目附 bytes 实际大小，
    目录条目 bytes 为 null（不做递归汇总，前端显示「目录」）。"""
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/list?project=proj-a")
    assert status == 200
    by_name = {e["name"]: e for e in body["entries"]}
    # 文件：bytes 与磁盘字节数一致
    expected = (proot / "notes.txt").stat().st_size
    assert by_name["notes.txt"]["bytes"] == expected
    # 目录：null
    assert by_name["core"]["bytes"] is None
    assert by_name["bin"]["bytes"] is None


def test_list_hidden_entries_ignored_channel(tmp_path):
    """隐藏文件通道（2026-11-11）：git 忽略项以 hidden 条目并入列表，
    --directory 折叠（全忽略目录单条）、子目录取直接子项、同名可见优先。"""
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    status, body = srv.get("/api/project-files/list?project=proj-a")
    assert status == 200
    hidden = [e for e in body["entries"] if e.get("hidden")]
    hidden_names = {e["name"] for e in hidden}
    # 折叠形态：目录单条（不带尾斜杠）、忽略文件逐条；深子路径不出现
    assert hidden_names == {".fenix", "node_modules", "ignored", "stray.log"}
    assert all("/" not in e["name"] for e in hidden)
    # 可见条目不带 hidden（或为 False）
    visible = [e for e in body["entries"] if not e.get("hidden")]
    assert all(not e["hidden"] for e in visible)
    assert "core" in {e["name"] for e in visible}

    # 子目录忽略项：仅直接子项
    status, body = srv.get("/api/project-files/list?project=proj-a&path=ignored")
    assert status == 200
    assert [e["name"] for e in body["entries"]] == ["sub"]
    assert body["entries"][0]["hidden"] is True
    status, body = srv.get("/api/project-files/list?project=proj-a&path=ignored/sub")
    assert status == 200
    assert [e["name"] for e in body["entries"]] == ["deep.txt"]
    assert body["entries"][0]["hidden"] is True


def test_build_entries_hidden_dedup(tmp_path):
    """build_entries 纯函数：同名可见条目优先，hidden 不标灰；纯忽略项
    按尾斜杠形态归入 dir/file。"""
    from core.dashboard.data.project_files import build_entries

    files = ["core/readme.md", "notes.txt", "README.md"]
    entries, _trunc = build_entries(
        files, "",
        hidden_names=["core/", "notes.txt", "beta.log", "node_modules/"],
    )
    by_name = {e["name"]: e for e in entries}
    # 同名既有可见又有忽略 → 可见优先不标灰（部分忽略的混合目录 core /
    # 可见文件 notes.txt）
    assert by_name["core"]["hidden"] is False
    assert by_name["core"]["dir"] is True
    assert by_name["notes.txt"]["hidden"] is False
    assert by_name["notes.txt"]["dir"] is False
    # 纯忽略项：尾斜杠 → 目录，否则文件
    assert by_name["beta.log"]["hidden"] is True
    assert by_name["beta.log"]["dir"] is False
    assert by_name["node_modules"]["hidden"] is True
    assert by_name["node_modules"]["dir"] is True
    # 无 hidden 通道时条目 hidden 恒 False
    plain_entries, _t = build_entries(files, "")
    for e in plain_entries:
        assert e["hidden"] is False


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


def test_raw_png_inline_headers_and_roundtrip(tmp_path):
    """raw 通道：图片扩展精确 Content-Type + nosniff + 实值长度 + 字节一致。"""
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    path = urllib.parse.quote("bin/logo.png", safe="")
    status, headers, body = srv.get_ex(
        f"/api/project-files/raw?project=proj-a&path={path}"
    )
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert headers["X-Content-Type-Options"] == "nosniff"
    expect = (proot / "bin" / "logo.png").read_bytes()
    assert headers["Content-Length"] == str(len(expect))
    assert body == expect
    # 内联通道语义：不是 attachment（浏览器 <img> 直显，不触发下载）
    assert "Content-Disposition" not in headers


def test_raw_rejects_non_image_and_error_shapes(tmp_path):
    """raw 通道仅服务图片扩展白名单；错误形态与 download 同款。"""
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    srv = _server(tmp_path, proot)

    # 非图片扩展（文本/markdown）→ 400（下载走 download 通道）
    status, body = srv.get("/api/project-files/raw?project=proj-a&path=notes.txt")
    assert status == 400 and "not an inline image" in body["error"]
    status, body = srv.get(
        "/api/project-files/raw?project=proj-a&path="
        + urllib.parse.quote("说明.md", safe="")
    )
    assert status == 400 and "not an inline image" in body["error"]
    # 目录 400
    status, body = srv.get("/api/project-files/raw?project=proj-a&path=bin")
    assert status == 400 and body["error"] == "path is a directory"
    # 缺失 404
    status, body = srv.get("/api/project-files/raw?project=proj-a&path=bin/nope.png")
    assert status == 404 and body["error"] == "file not found"
    # 越界 400（containment 单点，泛化文案）
    status, body = srv.get(
        "/api/project-files/raw?project=proj-a&path="
        + urllib.parse.quote("../../etc/passwd", safe="")
    )
    assert status == 400 and body["error"] == "Invalid path"


def test_raw_svg_carries_csp_sandbox(tmp_path):
    """svg 直显附 Content-Security-Policy: sandbox（防 SVG 内嵌脚本执行）。"""
    proot = make_project(tmp_path)
    _repo_with_fixture_tree(proot)
    # 未跟踪 svg（--others 可见性同下载通道的未跟踪 notes.txt）
    assets = proot / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "icon.svg").write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>'
    )
    srv = _server(tmp_path, proot)

    path = urllib.parse.quote("assets/icon.svg", safe="")
    status, headers, body = srv.get_ex(
        f"/api/project-files/raw?project=proj-a&path={path}"
    )
    assert status == 200
    assert headers["Content-Type"] == "image/svg+xml"
    assert headers["Content-Security-Policy"] == "sandbox"
    assert body == (proot / "assets" / "icon.svg").read_bytes()


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
