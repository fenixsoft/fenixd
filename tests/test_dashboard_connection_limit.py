"""
Tests for dashboard-connection-limit: SSE 连接上限与 HTTP 线程上限。
"""
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import server as server_mod
from core.dashboard.registry import Registry
from core.dashboard.server import (
    DashboardHTTPServer,
    MAX_SSE_CONNECTIONS,
    MAX_SERVER_THREADS,
    find_free_port,
)


# ── 辅助：在临时目录启动一个最小 dashboard server ─────────────────────────

class _TestServer:
    def __init__(self, registry: Registry, static_dir: Path):
        self.port = find_free_port(21000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), registry, static_dir)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _open_sse(port: int, timeout: float = 5.0):
    """打开一条 SSE 长连接，读到 hello 帧后返回 (sock, hello_dict)。

    若服务端 503 拒绝，则返回 (None, None) 并关闭 socket。
    """
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall(b"GET /api/stream HTTP/1.1\r\nHost: localhost\r\n\r\n")
    buf = b""
    # 读到 HTTP 响应头结束
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    if buf.startswith(b"HTTP/1.1 503"):
        s.close()
        return None, None
    # 继续读 hello 数据帧（首个 data: 块）
    while b"data: " not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    # 解析 hello JSON
    try:
        data_part = buf.split(b"data: ", 1)[1].split(b"\n\n", 1)[0]
        hello = json.loads(data_part.decode("utf-8"))
    except Exception:
        hello = None
    return s, hello


def _http_get(port: int, path: str = "/api/projects"):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        try:
            payload = json.loads(body)
        except Exception:
            payload = None
        return resp.status, payload
    finally:
        conn.close()


@pytest.fixture()
def srv_fx(tmp_path, monkeypatch):
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [], "scan_dirs": []})
    static_dir = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
    # 缩短 SSE 断开探测轮询间隔，让「释放后恢复」测试可快速通过
    monkeypatch.setattr(server_mod, "SSE_CLIENT_POLL_INTERVAL", 0.05)
    srv = _TestServer(reg, static_dir)
    yield srv
    srv.stop()


class TestSSEConnectionLimit:
    def test_exceed_limit_rejected_with_503(self, srv_fx, monkeypatch):
        monkeypatch.setattr(server_mod, "MAX_SSE_CONNECTIONS", 2)
        socks = []
        try:
            s1, hello1 = _open_sse(srv_fx.port)
            assert s1 is not None and hello1 is not None
            socks.append(s1)
            s2, hello2 = _open_sse(srv_fx.port)
            assert s2 is not None and hello2 is not None
            socks.append(s2)
            # 第 3 条 → 拒绝 503（JSON 错误体）
            s3, hello3 = _open_sse(srv_fx.port)
            assert s3 is None, "超限时应拒绝新连接"
            # 已建立连接仍可用：再发一条广播，2 条连接都应收到
            srv_fx.httpd.sse_hub.broadcast({"type": "refresh"})
            got = []
            for s in socks:
                s.settimeout(3)
                chunk = s.recv(4096)
                got.append(chunk)
            assert any(b"refresh" in c for c in got)
        finally:
            for s in socks:
                try:
                    s.close()
                except OSError:
                    pass

    def test_release_after_disconnect(self, srv_fx, monkeypatch):
        monkeypatch.setattr(server_mod, "MAX_SSE_CONNECTIONS", 2)
        s1, _ = _open_sse(srv_fx.port)
        s2, _ = _open_sse(srv_fx.port)
        assert s1 is not None and s2 is not None
        # 断开 1 条 → 计数回落 → 新连接可建立
        s1.close()
        import time
        time.sleep(0.1)
        s3, hello3 = _open_sse(srv_fx.port)
        try:
            assert s3 is not None and hello3 is not None, "释放后应恢复接受新连接"
        finally:
            if s3:
                s3.close()
            s2.close()


class TestHTTPThreadLimit:
    def test_thread_exhausted_returns_503(self, srv_fx, monkeypatch):
        # 降到 2：2 条 SSE 长连接占满并发槽位 → 第 3 个请求 503 server busy
        monkeypatch.setattr(server_mod, "MAX_SERVER_THREADS", 2)
        s1, _ = _open_sse(srv_fx.port)
        s2, _ = _open_sse(srv_fx.port)
        assert s1 is not None and s2 is not None
        try:
            status, payload = _http_get(srv_fx.port)
            assert status == 503
            assert payload and payload.get("error") == "server busy"
        finally:
            s1.close()
            s2.close()

    def test_thread_release_after_disconnect(self, srv_fx, monkeypatch):
        monkeypatch.setattr(server_mod, "MAX_SERVER_THREADS", 2)
        s1, _ = _open_sse(srv_fx.port)
        assert s1 is not None
        s1.close()
        import time
        time.sleep(0.1)
        status, payload = _http_get(srv_fx.port, "/api/projects")
        assert status == 200
        assert "projects" in payload

    def test_constants_exposed(self):
        assert isinstance(MAX_SSE_CONNECTIONS, int) and MAX_SSE_CONNECTIONS >= 1
        assert isinstance(MAX_SERVER_THREADS, int) and MAX_SERVER_THREADS >= 1
        assert MAX_SSE_CONNECTIONS <= 32
        assert MAX_SERVER_THREADS <= 64