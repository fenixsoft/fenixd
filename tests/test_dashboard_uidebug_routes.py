# -*- coding: utf-8 -*-
"""test_dashboard_uidebug_routes.py — /uidebug/ 界面调试批注路由测试。

fenix-ui-debug（add-fenix-ui-debug）把任意 http(s) URL 经 dashboard 内反向
代理接入批注框架。本文件用 conftest._TestServer 直起 dashboard 实例 + 进程
内 mini upstream 起目标站，覆盖：

- uidebug_io 纯函数（normalize_target / normalize_entry / split_target_url /
  write_session / load_session / session 段校验）
- uidebug_proxy 纯函数（rebase 三层改写 / 豁免前缀 / 重定向改写 /
  build_upstream_url 编码保真）
- 路由守卫（未注册项目 404、缺失会话 404、非法 session 段 403、非 /api/
  POST 405 不变量）
- 代理端到端（HTML/CSS 同源改写、<base> 剥除、运行时补丁与批注器注入、
  proto_round 剥离与轮次传递、同源/跨源重定向、上游不可达 502、
  非 200 原样透传、HEAD 无体）
- 批注落盘（POST /api/uidebug/.../feedback 复用 append_feedback，落点
  <project>/.fenix/ui-debug/<session>/feedback.json）
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

import core.dashboard.uidebug_io as uidebug_io
import core.dashboard.uidebug_proxy as uidebug_proxy
from core.dashboard.server import find_free_port

from conftest import Registry, _TestServer, make_project

# ── mini upstream：进程内目标站 ─────────────────────────────────────────

UPSTREAM_HTML = """<!doctype html><html><head>
<base href="/">
<title>up</title>
<link rel="stylesheet" href="/style.css">
</head><body>
<img src="/x.png" srcset="/x2.png 2x">
<a href="/next">next</a>
<a href="https://elsewhere.example/out">out</a>
<img src="/api/uidebug/proj-a/s1/feedback">
<script src="/uidebug-assets/annotator.js"></script>
</body></html>"""

UPSTREAM_CSS = "body{background:url(/bg.png)}\n@import url(/lib.css);\n"


class _UpstreamHandler(BaseHTTPRequestHandler):
    """固定路由表的目标站：GET 分发，其余 405；记录最近请求供断言。"""

    server_version = "MiniUpstream/1"

    def do_GET(self):  # noqa: N802（http.server 命名约定）
        parts = urlsplit(self.path)
        self.server.last_request_path = self.path  # 原始形态（含 query）
        self.server.last_request_cookie = (
            self.headers.get("Cookie") or "").strip()
        p = parts.path
        if p == "/" or p == "/deep" or p == "/deep/page2":
            body = UPSTREAM_HTML.encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif p == "/style.css":
            self._send(200, "text/css; charset=utf-8",
                       UPSTREAM_CSS.encode("utf-8"))
        elif p == "/x.png":
            self._send(200, "image/png", b"\x89PNG\r\n\x1a\nfake")
        elif p == "/next":
            self._send(200, "text/html; charset=utf-8",
                       b"<html><body>next</body></html>")
        elif p == "/echo-query":
            self._send(200, "text/html; charset=utf-8",
                       ("q=" + parts.query).encode("utf-8"))
        elif p == "/echo-cookie":
            self._send(200, "text/html; charset=utf-8",
                       ("c=" + (self.headers.get("Cookie") or "")
                        ).encode("utf-8"))
        elif p == "/set-cookie":
            body = b"<html><body>cookie set</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie",
                             "sess=abc; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/login":  # token URL 流程：303 + 鉴权 Set-Cookie
            self.send_response(303)
            self.send_header("Location", "/next")
            self.send_header("Set-Cookie",
                             "auth=tok123; Path=/; HttpOnly; SameSite=Strict;"
                             " Max-Age=2592000")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif p == "/redir-local":
            self._redirect("/next")
        elif p == "/redir-remote":
            self._redirect("https://elsewhere.example/remote")
        elif p == "/missing":
            self._send(404, "text/plain", b"nope")
        else:
            self._send(404, "text/plain", b"not found")

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默
        pass


@pytest.fixture()
def upstream():
    srv = ThreadingHTTPServer(("127.0.0.1", find_free_port(25000)),
                              _UpstreamHandler)
    srv.last_request_path = None
    srv.last_request_cookie = None
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", srv
    srv.shutdown()
    srv.server_close()


def _make_uidebug_project(tmp_path: Path, target: str, session: str = "s1",
                          entry: str = "") -> tuple[Path, _TestServer]:
    """注册 proj-a 并写入指向 target 的调试会话。"""
    proot = make_project(tmp_path)
    uidebug_io.write_session(proot, session, target, entry)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": []})
    return proot, _TestServer(reg, tmp_path)


@pytest.fixture()
def uidebug_srv(tmp_path, upstream):
    target, _ = upstream
    proot, srv = _make_uidebug_project(tmp_path, target)
    yield proot, srv, target
    srv.stop()


PREFIX = "/uidebug/proj-a/s1/~"

# ── uidebug_io 纯函数 ──────────────────────────────────────────────────


class TestNormalizeTarget:
    def test_accepts_http_https_strips_fragment_and_trailing_slash(self):
        assert uidebug_io.normalize_target(
            "http://h:3000/app/#frag") == "http://h:3000/app"
        assert uidebug_io.normalize_target("https://h/") == "https://h"

    def test_rejects_non_http_and_hostless(self):
        assert uidebug_io.normalize_target("ftp://h/p") is None
        assert uidebug_io.normalize_target("file:///etc/passwd") is None
        assert uidebug_io.normalize_target("http:///nohost") is None
        assert uidebug_io.normalize_target("") is None
        assert uidebug_io.normalize_target(None) is None

    def test_rejects_dot_segments(self):
        assert uidebug_io.normalize_target("http://h/../evil") is None
        assert uidebug_io.normalize_target("http://h/a/../../b") is None
        assert uidebug_io.normalize_target("http://h/a\\..\\x") is None


class TestNormalizeEntry:
    def test_empty_and_relative_ok(self):
        assert uidebug_io.normalize_entry("") == ""
        assert uidebug_io.normalize_entry(None) == ""
        assert uidebug_io.normalize_entry("page2") == "page2"
        assert uidebug_io.normalize_entry("/a/b/") == "a/b"
        assert uidebug_io.normalize_entry("a\\b") == "a/b"

    def test_rejects_traversal_and_nul(self):
        assert uidebug_io.normalize_entry("..") is None
        assert uidebug_io.normalize_entry("a/../b") is None
        assert uidebug_io.normalize_entry("a\x00b") is None


class TestSplitTargetUrl:
    def test_last_segment_is_entry(self):
        assert uidebug_io.split_target_url(
            "http://h:3000/app/page2") == ("http://h:3000/app", "page2", "")
        assert uidebug_io.split_target_url(
            "http://h:3000/a/b/c.html?x=1") == \
            ("http://h:3000/a/b", "c.html", "x=1")

    def test_origin_and_single_segment(self):
        assert uidebug_io.split_target_url("http://h:3000") == \
            ("http://h:3000", "", "")
        assert uidebug_io.split_target_url("http://h:3000/") == \
            ("http://h:3000", "", "")
        assert uidebug_io.split_target_url("http://h:3000/app") == \
            ("http://h:3000", "app", "")
        assert uidebug_io.split_target_url("http://h:3000/app/") == \
            ("http://h:3000", "app", "")

    def test_entry_query_preserved(self):
        # token URL 登录场景：query 是鉴权入口的一部分，须固化进会话
        assert uidebug_io.split_target_url(
            "http://h:3000/?token=abc&keep=1") == \
            ("http://h:3000", "", "token=abc&keep=1")
        # proto_round 是 fenix 迭代参数，从入口 query 剥离
        assert uidebug_io.split_target_url(
            "http://h:3000/?proto_round=2&token=t") == \
            ("http://h:3000", "", "token=t")

    def test_invalid(self):
        assert uidebug_io.split_target_url("ftp://h/p") is None
        assert uidebug_io.split_target_url("http://h/../evil") is None
        assert uidebug_io.split_target_url("http://h/?\x00") is None


class TestNormalizeEntryQuery:
    def test_strips_proto_round_and_reencodes(self):
        assert uidebug_io.normalize_entry_query("") == ""
        assert uidebug_io.normalize_entry_query(None) == ""
        assert uidebug_io.normalize_entry_query(
            "?token=a b&proto_round=3") == "token=a+b"
        assert uidebug_io.normalize_entry_query("a=1&a=2") == "a=1&a=2"

    def test_rejects_garbage(self):
        assert uidebug_io.normalize_entry_query("x" * 3000) is None
        assert uidebug_io.normalize_entry_query("a\x00b") is None


class TestSessionFile:
    def test_round_trip(self, tmp_path):
        uidebug_io.write_session(tmp_path, "s1", "http://h:3000/app", "page2")
        cfg = uidebug_io.load_session(tmp_path, "s1")
        assert cfg == {"target": "http://h:3000/app", "entry": "page2",
                       "entry_query": ""}

    def test_round_trip_with_entry_query(self, tmp_path):
        uidebug_io.write_session(tmp_path, "s1", "http://h:3000", "",
                                 "token=abc")
        cfg = uidebug_io.load_session(tmp_path, "s1")
        assert cfg == {"target": "http://h:3000", "entry": "",
                       "entry_query": "token=abc"}

    def test_legacy_file_without_entry(self, tmp_path):
        d = tmp_path / ".fenix" / "ui-debug" / "s1"
        d.mkdir(parents=True)
        (d / "session.json").write_text(
            json.dumps({"target": "http://h:3000", "session": "s1"}),
            encoding="utf-8")
        assert uidebug_io.load_session(tmp_path, "s1") == \
            {"target": "http://h:3000", "entry": "", "entry_query": ""}

    def test_missing_or_corrupt_is_none(self, tmp_path):
        assert uidebug_io.load_session(tmp_path, "ghost") is None
        uidebug_io.write_session(tmp_path, "s1", "http://h:3000")
        (tmp_path / ".fenix" / "ui-debug" / "s1" / "session.json").write_text(
            "{broken", encoding="utf-8")
        assert uidebug_io.load_session(tmp_path, "s1") is None

    def test_write_rejects_bad_target(self, tmp_path):
        with pytest.raises(ValueError):
            uidebug_io.write_session(tmp_path, "s1", "ftp://h")


# ── uidebug_proxy 纯函数 ───────────────────────────────────────────────


class TestRebase:
    P = uidebug_proxy.proxy_prefix("proj-a", "s1")

    def test_proxy_prefix_encoding(self):
        assert self.P == "/uidebug/proj-a/s1/~"

    def test_root_relative_rewritten_and_idempotent(self):
        assert uidebug_proxy.rebase_url_path("/x.png", self.P) == \
            self.P + "/x.png"
        # 幂等：代理前缀自身不再改写（运行时补丁重复触发安全）
        assert uidebug_proxy.rebase_url_path(self.P + "/x.png", self.P) == \
            self.P + "/x.png"

    def test_reserved_and_foreign_untouched(self):
        assert uidebug_proxy.rebase_url_path(
            "/api/uidebug/proj-a/s1/feedback", self.P) == \
            "/api/uidebug/proj-a/s1/feedback"
        assert uidebug_proxy.rebase_url_path(
            "/uidebug-assets/annotator.js", self.P) == \
            "/uidebug-assets/annotator.js"
        assert uidebug_proxy.rebase_url_path("rel.png", self.P) == "rel.png"
        assert uidebug_proxy.rebase_url_path("//cdn.example/x.js", self.P) == \
            "//cdn.example/x.js"
        assert uidebug_proxy.rebase_url_path(
            "https://elsewhere.example/a", self.P) == \
            "https://elsewhere.example/a"

    def test_rebase_html_rewrite_and_base_strip(self):
        out = uidebug_proxy.rebase_html(UPSTREAM_HTML, self.P)
        assert 'src="/uidebug/proj-a/s1/~/x.png"' in out
        assert 'href="/uidebug/proj-a/s1/~/style.css"' in out
        assert 'srcset="/uidebug/proj-a/s1/~/x2.png 2x"' in out
        assert "fenix-ui-debug: base stripped" in out
        assert "<base" not in out
        # 豁免与跨源原样
        assert 'src="/api/uidebug/proj-a/s1/feedback"' in out
        assert 'href="https://elsewhere.example/out"' in out

    def test_rebase_css(self):
        out = uidebug_proxy.rebase_css(UPSTREAM_CSS, self.P)
        assert "url(/uidebug/proj-a/s1/~/bg.png)" in out
        assert "url(/uidebug/proj-a/s1/~/lib.css)" in out

    def test_redirect_rebase(self):
        target = "http://127.0.0.1:9"
        same = uidebug_proxy.rebase_redirect(
            "/next", target + "/redir", target, self.P)
        assert same == self.P + "/next"
        cross = uidebug_proxy.rebase_redirect(
            "https://elsewhere.example/remote", target + "/redir", target,
            self.P)
        assert cross == "https://elsewhere.example/remote"

    def test_build_upstream_url_encoding_preserved(self):
        url = uidebug_proxy.build_upstream_url(
            "http://h:3000/app", "a%20b/c", "x=1&y=%E4%B8%AD")
        assert url == "http://h:3000/app/a%20b/c?x=1&y=%E4%B8%AD"
        # 空 sub → 目录尾斜杠形态
        assert uidebug_proxy.build_upstream_url("http://h:3000/app", "",
                                                "") == "http://h:3000/app/"

    def test_inject_sets_mode_and_round(self):
        out = uidebug_proxy.inject_into_html("<html><head></head></html>",
                                             self.P, 3)
        assert "window.__FENIX_UIDEBUG__" in out
        assert "window.__PROTO_FEEDBACK_ROUND__=3" in out
        assert 'window.__FENIX_ANNOTATOR_MODE__="uidebug"' in out
        assert 'src="/uidebug-assets/annotator.js"' in out
        assert out.index("window.__FENIX_UIDEBUG__") < out.index("</head>")


# ── 路由守卫 ───────────────────────────────────────────────────────────


class TestRouteGuards:
    def test_unknown_session_404(self, tmp_path, upstream):
        target, _ = upstream
        proot, srv = _make_uidebug_project(tmp_path, target)
        try:
            # s9 从未写过 session.json → 会话不存在 404
            status, _ct, _body = srv.get("/uidebug/proj-a/s9/~/", raw=True)
            assert status == 404
        finally:
            srv.stop()

    def test_unsafe_session_403(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        for bad in ("/uidebug/proj-a/%2E%2E/~/", "/uidebug/proj-a/s1%00/~/"):
            status, _ct, _body = srv.get(bad, raw=True)
            assert status in (403, 404), bad

    def test_unregistered_project_404(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _ct, _body = srv.get("/uidebug/ghost/s1/~/", raw=True)
        assert status == 404

    def test_wrapper_without_tilde_serves_wrapper(self, uidebug_srv):
        _proot, srv, target = uidebug_srv
        status, ct, body = srv.get("/uidebug/proj-a/s1", raw=True)
        assert status == 200
        assert "text/html" in ct
        assert target.encode() in body

    def test_non_api_post_405(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        # 非 /api/ 前缀 POST 在分派层 405（/uidebug/ 前缀不豁免）
        status, data = srv.post_json("/uidebug/proj-a/s1/feedback", {})
        assert status == 405

    def test_unknown_asset_404(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _ct, _body = srv.get("/uidebug-assets/other.js", raw=True)
        assert status == 404


# ── 代理端到端 ─────────────────────────────────────────────────────────


class TestProxyServing:
    def test_asset_served_single_source(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, ct, body = srv.get("/uidebug-assets/annotator.js", raw=True)
        assert status == 200
        assert "javascript" in ct
        assert b"fenixPrototypeAnnotator" in body

    def test_proxy_rewrites_html_and_injects(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, ct, body = srv.get(f"{PREFIX}/", raw=True)
        assert status == 200
        assert "text/html" in ct
        html = body.decode("utf-8")
        assert 'src="/uidebug/proj-a/s1/~/x.png"' in html
        assert 'href="/uidebug/proj-a/s1/~/style.css"' in html
        assert "<base" not in html
        assert "window.__FENIX_UIDEBUG__" in html
        assert 'window.__FENIX_ANNOTATOR_MODE__="uidebug"' in html
        # 豁免通道原样
        assert 'src="/api/uidebug/proj-a/s1/feedback"' in html
        assert 'src="/uidebug-assets/annotator.js"' in html
        # 恒 no-store
        status2, headers, _body = srv.get_ex(f"{PREFIX}/")
        assert headers.get("Cache-Control") == "no-store, max-age=0"

    def test_proxy_round_passed_via_injected_global(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _ct, body = srv.get(f"{PREFIX}/?proto_round=7&keep=1",
                                    raw=True)
        assert status == 200
        assert b"window.__PROTO_FEEDBACK_ROUND__=7" in body

    def test_proto_round_stripped_from_upstream_query(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _ct, body = srv.get(f"{PREFIX}/echo-query?proto_round=2&foo=bar",
                                    raw=True)
        assert status == 200
        assert b"foo=bar" in body
        assert b"proto_round" not in body

    def test_browser_cookie_not_forwarded_to_upstream(self, uidebug_srv, upstream):
        # 浏览器 Cookie 头一律不透传上游（a0f228890ba7：默认不转发，
        # 防同源部署下面板/宿主会话 cookie 随调试请求外泄给第三方页面）
        _proot, srv, _target = uidebug_srv
        _url, usrv = upstream
        status, _h, body = srv.get_ex(
            f"{PREFIX}/echo-cookie", headers={"Cookie": "auth=tok123"})
        assert status == 200
        assert b"c=" in body and b"c=auth=tok123" not in body
        assert usrv.last_request_cookie == ""

    def test_set_cookie_rescoped_to_session(self, uidebug_srv):
        # 上游 Set-Cookie 的 Path 统一改写为会话根前缀，Secure 剥除
        _proot, srv, _target = uidebug_srv
        status, headers, _body = srv.get_ex(f"{PREFIX}/set-cookie")
        assert status == 200
        sc = headers.get("Set-Cookie")
        assert sc is not None and "sess=abc" in sc
        assert "Path=/uidebug/proj-a/s1" in sc
        assert "HttpOnly" in sc and "SameSite=Strict" in sc
        assert "Secure" not in sc

    def test_redirect_forwards_rescoped_set_cookie(self, uidebug_srv):
        # token URL 流程：303 Location 改写进代理前缀 + 鉴权 Set-Cookie 同步改写
        _proot, srv, _target = uidebug_srv
        status, headers, body = srv.get_ex(f"{PREFIX}/login")
        assert status == 303
        assert body == b""
        assert headers.get("Location") == "/uidebug/proj-a/s1/~/next"
        sc = headers.get("Set-Cookie")
        assert sc is not None and "auth=tok123" in sc
        assert "Path=/uidebug/proj-a/s1" in sc
        assert "Max-Age=2592000" in sc

    def test_proxy_rewrites_css_and_passthrough_binary(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, ct, body = srv.get(f"{PREFIX}/style.css", raw=True)
        assert status == 200 and "text/css" in ct
        assert b"url(/uidebug/proj-a/s1/~/bg.png)" in body
        status, ct, body = srv.get(f"{PREFIX}/x.png", raw=True)
        assert status == 200 and "image/png" in ct
        assert body.startswith(b"\x89PNG")

    def test_upstream_404_passthrough(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _ct, body = srv.get(f"{PREFIX}/missing", raw=True)
        assert status == 404
        assert b"nope" in body

    def test_local_redirect_rebased(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, headers, body = srv.get_ex(f"{PREFIX}/redir-local")
        assert status == 302
        assert headers.get("Location") == "/uidebug/proj-a/s1/~/next"
        assert body == b""

    def test_remote_redirect_passthrough(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, headers, _body = srv.get_ex(f"{PREFIX}/redir-remote")
        assert status == 302
        assert headers.get("Location") == "https://elsewhere.example/remote"

    def test_head_no_body(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        # HEAD 须带 Content-Length 但无响应体（代理与 wrapper 同规则）
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            conn.request("HEAD", f"{PREFIX}/")
            resp = conn.getresponse()
            resp.read()
            assert resp.status == 200
            assert int(resp.getheader("Content-Length")) > 0
            assert resp.read() == b""
            conn2 = http.client.HTTPConnection("127.0.0.1", srv.port,
                                               timeout=10)
            try:
                conn2.request("HEAD", "/uidebug/proj-a/s1")
                resp2 = conn2.getresponse()
                resp2.read()
                assert resp2.status == 200
                assert int(resp2.getheader("Content-Length")) > 0
                assert resp2.read() == b""
            finally:
                conn2.close()
        finally:
            conn.close()

    def test_upstream_down_502(self, tmp_path):
        dead = f"http://127.0.0.1:{find_free_port(26000)}"  # 无人监听
        proot, srv = _make_uidebug_project(tmp_path, dead)
        try:
            status, _ct, _body = srv.get(f"{PREFIX}/", raw=True)
            assert status == 502
        finally:
            srv.stop()

    def test_entry_path_proxied(self, tmp_path, upstream):
        target, _ = upstream
        proot, srv = _make_uidebug_project(tmp_path, target, entry="deep/page2")
        try:
            status, _ct, body = srv.get("/uidebug/proj-a/s1", raw=True)
            assert status == 200
            assert b"/uidebug/proj-a/s1/~/deep/page2" in body  # iframe src
            status, _ct, body = srv.get(f"{PREFIX}/deep/page2", raw=True)
            assert status == 200
            assert b"up" in body
        finally:
            srv.stop()

    def test_entry_query_on_wrapper_and_proxy(self, tmp_path, upstream):
        # token URL 场景：入口 query 固化进会话，wrapper iframe src 与代理
        # 入口都带上；proto_round 与 query 用 & 连接
        target, _ = upstream
        proot = make_project(tmp_path)
        uidebug_io.write_session(proot, "s1", target, "", "token=abc&keep=1")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a",
                                              "path": str(proot)}],
                  "scan_dirs": []})
        srv = _TestServer(reg, tmp_path)
        try:
            status, _ct, body = srv.get("/uidebug/proj-a/s1?proto_round=2",
                                        raw=True)
            assert status == 200
            html = body.decode("utf-8")
            assert "/uidebug/proj-a/s1/~/?token=abc&amp;keep=1&amp;" \
                   "proto_round=2" in html
            status, _ct, body = srv.get(
                f"{PREFIX}/?proto_round=2&token=abc&keep=1", raw=True)
            assert status == 200  # 代理剥 proto_round，其余 query 到上游
        finally:
            srv.stop()

    def test_encoded_sub_path_preserved(self, uidebug_srv, upstream):
        _proot, srv, _target = uidebug_srv
        _base, usrv = upstream
        status, _ct, _body = srv.get(f"{PREFIX}/echo%20path?a=b%20c",
                                     raw=True)
        # 子路径编码原样透传（不发生 unquote/re-quote 往返——上游收到
        # 的是原始请求行形态）；query 经语义化往返（%20↔+）等价即可
        assert usrv.last_request_path.startswith("/echo%20path?")


# ── 批注落盘 ───────────────────────────────────────────────────────────


class TestFeedbackApi:
    def test_post_feedback_writes_session_dir(self, uidebug_srv):
        proot, srv, _target = uidebug_srv
        status, data = srv.post_json(
            "/api/uidebug/proj-a/s1/feedback",
            {"anchor": "body>div:nth-of-type(1)", "text": "标题字号偏小",
             "round": 1, "page": "/uidebug/proj-a/s1/~/deep/page2",
             "element": {"tag": "div", "text": "卡片"}})
        assert status == 200
        assert data["ok"] is True
        assert data["stored"].startswith(".fenix")
        fb = json.loads(
            (proot / ".fenix" / "ui-debug" / "s1" / "feedback.json")
            .read_text(encoding="utf-8"))
        # append_feedback 新建文件为列表形态
        assert fb[0]["text"] == "标题字号偏小"
        assert fb[0]["page"].endswith("/deep/page2")

    def test_post_feedback_invalid_body_400(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _data = srv.post_json(
            "/api/uidebug/proj-a/s1/feedback", {"anchor": "x"})  # 缺 text
        assert status == 400

    def test_post_feedback_unknown_session_404(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _data = srv.post_json(
            "/api/uidebug/proj-a/ghost/feedback",
            {"anchor": "x", "text": "y"})
        assert status == 404

    def test_post_feedback_unsafe_session_403(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _data = srv.post_json(
            "/api/uidebug/proj-a/%2E%2E/feedback", {"anchor": "x", "text": "y"})
        assert status == 403


class TestSseGuard:
    """SSE 流不进代理：204 快速失败，不钉死 dashboard 工作线程。"""

    def test_event_stream_returns_204(self, tmp_path, upstream):
        target, usrv = upstream

        # 给 mini upstream 临时加一个 /stream 端点（SSE 形态）
        orig_do_GET = _UpstreamHandler.do_GET

        def patched(self):
            if urlsplit(self.path).path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            orig_do_GET(self)

        _UpstreamHandler.do_GET = patched
        try:
            proot, srv = _make_uidebug_project(tmp_path, target)
            try:
                status, _ct, body = srv.get(f"{PREFIX}/stream", raw=True)
                assert status == 204
                assert body == b""
            finally:
                srv.stop()
        finally:
            _UpstreamHandler.do_GET = orig_do_GET

    def test_fetch_upstream_skips_endless_event_stream(self, tmp_path):
        """真 SSE 形态（无 Content-Length、心跳保活、永不 EOF）：
        fetch_upstream 必须按响应头短路返回空体，不得读正文钉死。"""
        import time as _time
        from core.dashboard.uidebug_proxy import fetch_upstream

        srv = ThreadingHTTPServer(("127.0.0.1", find_free_port(27000)),
                                  _UpstreamHandler)
        srv.stream_open = True
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()

        orig_do_GET = _UpstreamHandler.do_GET

        def endless_sse(self):
            if urlsplit(self.path).path == "/endless-sse":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()  # 无 Content-Length：chunked/连读形态
                while self.server.stream_open:
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except OSError:
                        return
                    _time.sleep(0.2)
                return
            orig_do_GET(self)

        _UpstreamHandler.do_GET = endless_sse
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/endless-sse"
            started = _time.monotonic()
            status, headers, body = fetch_upstream(url, timeout=5.0)
            elapsed = _time.monotonic() - started
            assert status == 200
            assert body == b""
            assert elapsed < 3.0, f"event-stream 读取未短路（{elapsed:.1f}s）"
        finally:
            srv.stream_open = False  # 放开上游 handler 线程再关服
            srv.shutdown()
            srv.server_close()


class TestFeedbackManageApi:
    """批注管理端点（2026-11-28 批注功能自身优化 1）：GET 列表 / POST 带 id
    重编辑 / DELETE ?id= 删单条；历史无 id 条目 GET 时惰性迁移。"""

    FB = "/api/uidebug/proj-a/s1/feedback"

    def _get_json(self, srv, path):
        status, _headers, body = srv.get_ex(path)
        return status, json.loads(body)

    def _post(self, srv, text="甲意见", anchor="body>div:nth-of-type(1)"):
        return srv.post_json(self.FB, {"anchor": anchor, "text": text,
                                       "round": 1,
                                       "page": "/uidebug/proj-a/s1/~/"})

    def _fb_file(self, proot):
        return proot / ".fenix" / "ui-debug" / "s1" / "feedback.json"

    def test_get_empty_list_ok(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, data = self._get_json(srv, self.FB)
        assert status == 200
        assert data["ok"] is True
        assert data["count"] == 0
        assert data["feedback"] == []

    def test_post_returns_id_and_get_lists_it(self, uidebug_srv):
        proot, srv, _target = uidebug_srv
        status, data = self._post(srv)
        assert status == 200
        fb_id = data.get("id")
        assert isinstance(fb_id, str) and fb_id
        status, data = self._get_json(srv, self.FB)
        assert status == 200 and data["count"] == 1
        assert data["feedback"][0]["id"] == fb_id
        # 落盘文件已带 id：后续删除/重编辑可按它寻址
        on_disk = json.loads(self._fb_file(proot).read_text(encoding="utf-8"))
        assert on_disk[0]["id"] == fb_id

    def test_get_assigns_ids_to_legacy_entries(self, uidebug_srv):
        """历史 feedback.json（无 id）：GET 即惰性迁移补 id 并落盘。"""
        proot, srv, _target = uidebug_srv
        f = self._fb_file(proot)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(
            [{"anchor": "h1", "text": "旧批注", "timestamp": "t", "round": 1}],
            ensure_ascii=False), encoding="utf-8")
        status, data = self._get_json(srv, self.FB)
        assert status == 200 and data["count"] == 1
        migrated = json.loads(f.read_text(encoding="utf-8"))
        assert migrated[0]["id"] == data["feedback"][0]["id"]
        assert migrated[0]["text"] == "旧批注"  # 迁移只补 id，其余字段不动

    def test_post_update_changes_text_only(self, uidebug_srv):
        proot, srv, _target = uidebug_srv
        _s, data = self._post(srv, text="原意见")
        fb_id = data["id"]
        status, upd = srv.post_json(self.FB, {"id": fb_id, "text": "改后的意见"})
        assert status == 200
        assert upd["ok"] is True and upd["updated"] == fb_id  # 回带被改条目 id
        on_disk = json.loads(self._fb_file(proot).read_text(encoding="utf-8"))
        assert on_disk[0]["text"] == "改后的意见"
        assert on_disk[0]["anchor"] == "body>div:nth-of-type(1)"  # 锚/轮次不动
        assert on_disk[0]["round"] == 1
        assert "edited" in on_disk[0]  # 重编辑时间戳

    def test_post_update_unknown_id_404(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        status, _d = srv.post_json(self.FB, {"id": "fb-none", "text": "y"})
        assert status == 404

    def test_post_update_invalid_400(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        assert srv.post_json(self.FB, {"id": 7, "text": "y"})[0] == 400
        assert srv.post_json(self.FB, {"id": "fb-none", "text": "   "})[0] == 400

    def test_delete_removes_entry(self, uidebug_srv):
        proot, srv, _target = uidebug_srv
        _s, d1 = self._post(srv, text="甲")
        _s, d2 = self._post(srv, text="乙")
        status, data = srv.delete(self.FB + "?id=" + d2["id"])
        assert status == 200
        assert data["ok"] is True and data["deleted"] == d2["id"]  # 回带被删 id
        status, data = self._get_json(srv, self.FB)
        assert data["count"] == 1
        assert data["feedback"][0]["id"] == d1["id"]

    def test_delete_requires_and_validates_id(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        assert srv.delete(self.FB)[0] == 400                    # 缺 id
        assert srv.delete(self.FB + "?id=fb-none")[0] == 404    # 未命中

    def test_delete_keeps_dict_form(self, uidebug_srv):
        """dict 形态文件（含 round 等自定义键）删单条后形态保留。"""
        proot, srv, _target = uidebug_srv
        f = self._fb_file(proot)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"round": 2, "feedback": [
            {"anchor": "h1", "text": "旧", "id": "fb-legacy-1"},
        ]}, ensure_ascii=False), encoding="utf-8")
        status, _d = srv.delete(self.FB + "?id=fb-legacy-1")
        assert status == 200
        on_disk = json.loads(f.read_text(encoding="utf-8"))
        assert on_disk["round"] == 2
        assert on_disk["feedback"] == []

    def test_manage_guards_403_404(self, uidebug_srv):
        _proot, srv, _target = uidebug_srv
        assert self._get_json(srv, "/api/uidebug/proj-a/%2E%2E/feedback")[0] == 403
        assert self._get_json(srv, "/api/uidebug/proj-a/ghost/feedback")[0] == 404
        assert srv.delete("/api/uidebug/proj-a/%2E%2E/feedback?id=fb-x")[0] == 403
        assert srv.delete("/api/uidebug/proj-a/ghost/feedback?id=fb-x")[0] == 404
