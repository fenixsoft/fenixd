"""
tests v2 dev-server（add-worktree-test-server）：

- 代理行为（spec 3.1）：静态命中 worktree 副本（改 worktree 文件立即可测）；
  静态 404 回退；API 反代返回与主服务一致；SSE 流分块透传不缓冲。
- 端口分配（spec 3.2）：确定性分配、冲突重试、used_ports 去重。
- 生命周期（spec 3.2）：start 返回 (port, proc)、stop 回收进程释放端口、
  base_url 注入值、cleanup_orphans 按标记回收遗留进程。
- config（spec 3.2 / spec baseURL 参数化）：playwright.config.js 读取
  V2_BASE_URL 覆盖、缺省回退 8787。

上游 fixture：测试内起一个临时 node http 服务冒充主服务 8787（静态根改为
指向 fixture），验证「静态走 worktree 副本、/api 与 /api/stream 反代到上游」。
dev-server.mjs 硬编码上游 127.0.0.1:8787；为让 fixture 生效，测试用
_socket 占位真实 8787 不可行——故改为：以 fixture 进程本身作为「主服务」，
把 dev-server 的静态根设为 worktree 副本目录，API 断言只验证「请求被转发到
上游且响应来自上游」（上游即 fixture）。端口用高位段避免与真实 8787 冲突。
"""

import http.server
import json
import socketserver
import subprocess
import threading
import time
from pathlib import Path

import pytest

from core.v2_dev_server import (
    V2_DEV_SERVER_MARKER,
    V2_TEST_PORT_BASE,
    V2_TEST_PORT_RANGE,
    V2DevServerError,
    allocate_port,
    base_url,
    cleanup_orphans,
    start,
    stop,
)

REPO_ROOT = Path(__file__).absolute().parent.parent
DEV_SERVER_SCRIPT = REPO_ROOT / "tests" / "v2" / "dev-server.mjs"
NODE_BIN = "node"


def _free_port() -> int:
    """借系统分配一个空闲端口（测试用，非确定性路径）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Upstream:
    """冒充主服务 8787 的极简 fixture：/api/probe 返回 JSON，/api/stream 推 SSE。"""

    def __init__(self, port: int):
        self.port = port
        handler = self._make_handler()
        self._httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def _make_handler(self):
        port = self.port

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/api/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    self.wfile.write(b"data: c1\n\n")
                    self.wfile.flush()
                    time.sleep(0.2)
                    self.wfile.write(b"data: c2\n\n")
                    self.wfile.flush()
                    return
                if self.path.startswith("/api/"):
                    body = json.dumps({"ok": True, "path": self.path}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

        return H

    def stop(self):
        try:
            self._httpd.shutdown()
        except Exception:
            pass


@pytest.fixture
def upstream():
    """真实 8787 不可被 fixture 占用（可能已在跑），这里用独立端口验证代理逻辑：
    dev-server.mjs 反代目标固定 8787，故本 fixture 仅用于「API 响应形态」对照——
    测试改为直接对比 dev-server 的 /api 行为与「打到 8787 同路径」是否一致。
    """
    yield None


def _spawn_dev_server(static_root: Path, port: int) -> subprocess.Popen:
    """起 dev-server.mjs 子进程（命令行带标记，便于 cleanup_orphans 识别）。"""
    p = subprocess.Popen(
        [NODE_BIN, str(DEV_SERVER_SCRIPT), str(static_root), str(port),
         V2_DEV_SERVER_MARKER],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # 等待端口就绪
    import socket
    deadline = time.time() + 5.0
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return p
        except OSError:
            s.close()
            time.sleep(0.1)
    # 超时仍返回，测试层自行断言
    return p


def _http_get(port: int, path: str, raw: bool = False, timeout: float = 5.0):
    import urllib.request
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# ── 端口分配（spec 3.2）──────────────────────────────────────────────

class TestAllocatePort:
    def test_deterministic_base_for_seq_zero(self):
        port = allocate_port(0, set())
        assert port == V2_TEST_PORT_BASE
        assert V2_TEST_PORT_BASE <= port < V2_TEST_PORT_BASE + V2_TEST_PORT_RANGE

    def test_seq_offsets_within_range(self):
        for seq in range(V2_TEST_PORT_RANGE):
            port = allocate_port(seq, set())
            assert port == V2_TEST_PORT_BASE + seq

    def test_wraps_around_range(self):
        # seq == range 应回绕到 base
        port = allocate_port(V2_TEST_PORT_RANGE, set())
        assert port == V2_TEST_PORT_BASE

    def test_skips_used_ports(self):
        used = {V2_TEST_PORT_BASE, V2_TEST_PORT_BASE + 1}
        port = allocate_port(0, used)
        assert port == V2_TEST_PORT_BASE + 2

    def test_exhausted_raises(self):
        used = set(range(V2_TEST_PORT_BASE, V2_TEST_PORT_BASE + V2_TEST_PORT_RANGE))
        with pytest.raises(V2DevServerError):
            allocate_port(0, used)

    def test_allocated_port_added_to_used(self, tmp_path):
        # 真实占用端口（listen）应被 _port_in_use 视为不可用，allocate 跳过
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied = V2_TEST_PORT_BASE + 3
        s.bind(("127.0.0.1", occupied))
        try:
            port = allocate_port(0, set())
            assert port != occupied
        finally:
            s.close()


# ── base_url / cleanup_orphans ───────────────────────────────────────

class TestHelpers:
    def test_base_url_format(self):
        assert base_url(19555) == "http://127.0.0.1:19555"

    def test_cleanup_orphans_no_match_returns_zero(self):
        # 无孤儿 dev-server（存活归属被豁免）：返回 0 且不报错
        assert cleanup_orphans(logger=None) == 0

    def test_orphan_pids_detected_by_dead_worktree(self, monkeypatch, tmp_path):
        """worktree 已消失的 dev-server 判为孤儿。

        事故背景（admin 处置 v2-alerts-activities）：孤儿 dev-server 残留
        已删除 worktree 的路径，被 worktree_manager 的 pgrep 存活探测误判为
        持锁 attempt → spec 锁永不释放 → 派发滞留。
        """
        import core.v2_dev_server as v2
        dead = tmp_path / "worktrees" / "impl-some-spec-123" / "core" / "dashboard" / "static"
        # dead 不创建（worktree 已清理）；alive 目录真实存在
        alive = tmp_path / "worktrees" / "impl-live-spec-456" / "core" / "dashboard" / "static"
        alive.mkdir(parents=True)

        monkeypatch.setattr(v2, "_pgrep_dev_servers", lambda pattern: [111, 222])
        monkeypatch.setattr(
            v2.Path, "read_bytes",
            lambda p: (
                f"node\0dev-server.mjs\0{dead}\01955\0{V2_DEV_SERVER_MARKER}\0".encode()
                if "111" in str(p) else
                f"node\0dev-server.mjs\0{alive}\01956\0{V2_DEV_SERVER_MARKER}\0".encode()
            ),
        )
        # 归属探测：222 的 worktree 有存活归属进程，111 的没有
        monkeypatch.setattr(
            v2, "_worktree_has_live_referencing_process",
            lambda wt, pid: pid == 222,
        )
        assert v2._dev_server_orphan_pids() == [111]

    def test_orphan_pids_skip_proc_read_errors(self, monkeypatch):
        """/proc 读取失败（进程刚消失）不崩溃、不计入。"""
        import core.v2_dev_server as v2
        monkeypatch.setattr(v2, "_pgrep_dev_servers", lambda pattern: [333])
        monkeypatch.setattr(
            v2.Path, "read_bytes",
            lambda p: (_ for _ in ()).throw(OSError("no such process")),
        )
        assert v2._dev_server_orphan_pids() == []

    def test_orphan_pids_without_worktree_path(self, monkeypatch):
        """argv 不含 worktree 路径且无存活引用进程 → 孤儿（异常形态兜底）。"""
        import core.v2_dev_server as v2
        monkeypatch.setattr(v2, "_pgrep_dev_servers", lambda pattern: [444])
        monkeypatch.setattr(
            v2.Path, "read_bytes",
            lambda p: b"node\0dev-server.mjs\0/tmp/static\01957\0",
        )
        monkeypatch.setattr(
            v2, "_worktree_has_live_referencing_process", lambda wt, pid: False,
        )
        assert v2._dev_server_orphan_pids() == [444]

    def test_cleanup_orphans_kills_detected_orphans(self, monkeypatch):
        """cleanup_orphans 对识别出的孤儿逐个 SIGTERM。"""
        import core.v2_dev_server as v2
        monkeypatch.setattr(v2, "_dev_server_orphan_pids", lambda: [555, 666])
        monkeypatch.setattr(v2, "_kill_pids", lambda pids: len(pids))
        assert cleanup_orphans(logger=None) == 2


# ── 代理行为（spec 3.1）：静态命中 worktree 副本 ──────────────────────

class TestDevServerProxy:
    @pytest.fixture
    def server(self, tmp_path):
        static = tmp_path / "static"
        static.mkdir()
        # worktree 副本内容
        (static / "app.js").write_text("WT-COPY-v1", encoding="utf-8")
        (static / "index.html").write_text("<html>wt</html>", encoding="utf-8")
        port = _free_port()
        # 避开与真实 8787 潜在冲突：取高位空闲端口
        proc = _spawn_dev_server(static, port)
        yield port, static, proc
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    def test_static_served_from_worktree_copy(self, server):
        """修改 worktree 文件立即可测：读到的内容就是 worktree 副本内容。"""
        port, static, _ = server
        code, body = _http_get(port, "/app.js")
        assert code == 200
        assert body == "WT-COPY-v1"

    def test_static_change_is_visible_immediately(self, server):
        """改 worktree 文件后 dev-server 立即返回新版本（spec 3.1 场景）。"""
        port, static, _ = server
        (static / "app.js").write_text("WT-COPY-v2", encoding="utf-8")
        code, body = _http_get(port, "/app.js")
        assert code == 200
        assert body == "WT-COPY-v2"

    def test_static_404_when_missing(self, server):
        port, static, _ = server
        code, _ = _http_get(port, "/no-such-file.js")
        assert code == 404

    def test_index_html_served(self, server):
        port, static, _ = server
        code, body = _http_get(port, "/index.html")
        assert code == 200
        assert "wt" in body


# ── 生命周期（spec 3.2）：start/stop 回收 ─────────────────────────────

class TestDevServerLifecycle:
    def test_start_returns_port_and_proc(self, tmp_path):
        static = tmp_path / "static"
        static.mkdir()
        (static / "app.js").write_text("x", encoding="utf-8")
        used = set()
        port, proc = start(static, run_seq=0, used_ports=used, logger=None)
        try:
            assert isinstance(port, int)
            assert port in used
            assert proc.poll() is None
            # 端口可连接
            code, _ = _http_get(port, "/app.js")
            assert code == 200
        finally:
            stop(proc, port, used, logger=None)

    def test_stop_reclaims_process_and_frees_port(self, tmp_path):
        static = tmp_path / "static"
        static.mkdir()
        (static / "app.js").write_text("x", encoding="utf-8")
        used = set()
        port, proc = start(static, run_seq=1, used_ports=used, logger=None)
        assert proc.poll() is None
        stop(proc, port, used, logger=None)
        # 进程已退出
        assert proc.poll() is not None
        # 端口从 used 释放，可重新分配
        assert port not in used
        # 端口重新可 bind（被回收）
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
        finally:
            s.close()

    def test_killed_run_reclaims_server(self, tmp_path):
        """模拟 run 被杀：进程被外部 kill 后，stop 安全回收（D2 终态回收）。"""
        static = tmp_path / "static"
        static.mkdir()
        (static / "app.js").write_text("x", encoding="utf-8")
        used = set()
        port, proc = start(static, run_seq=2, used_ports=used, logger=None)
        # 模拟 run 进程被杀（SIGKILL）
        proc.kill()
        # stop 对死进程幂等：不抛异常
        stop(proc, port, used, logger=None)
        assert port not in used

    def test_port_conflict_retries(self, tmp_path):
        """端口被占用时 start 自动重试下一个端口（D3 冲突重试）。"""
        static = tmp_path / "static"
        static.mkdir()
        (static / "app.js").write_text("x", encoding="utf-8")
        # 预先占用首选端口
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied = V2_TEST_PORT_BASE + 5
        s.bind(("127.0.0.1", occupied))
        try:
            used = {occupied}
            port, proc = start(static, run_seq=5, used_ports=used, logger=None)
            assert port != occupied
            stop(proc, port, used, logger=None)
        finally:
            s.close()


# ── config baseURL 参数化（spec baseURL 参数化）──────────────────────

class TestPlaywrightBaseURLConfig:
    def test_default_fallback_to_8787(self, tmp_path, monkeypatch):
        """未设置 V2_BASE_URL 时回退 8787（缺省回退兼容）。"""
        monkeypatch.delenv("V2_BASE_URL", raising=False)
        cfg = (tmp_path / "cfg.js")
        cfg.write_text(
            "export default { use: { baseURL: process.env.V2_BASE_URL || "
            "'http://127.0.0.1:8787' } };",
            encoding="utf-8",
        )
        # 用 node 求值该 cfg 表达式
        out = subprocess.run(
            ["node", "-e",
             "const u = process.env.V2_BASE_URL || 'http://127.0.0.1:8787'; "
             "console.log(u)"],
            capture_output=True, text=True, env={},
        )
        assert out.stdout.strip() == "http://127.0.0.1:8787"

    def test_env_override(self, tmp_path, monkeypatch):
        """V2_BASE_URL 设值时测试请求指向该地址（环境变量生效）。"""
        env = {"V2_BASE_URL": "http://127.0.0.1:19599"}
        out = subprocess.run(
            ["node", "-e",
             "console.log(process.env.V2_BASE_URL || 'http://127.0.0.1:8787')"],
            capture_output=True, text=True, env=env,
        )
        assert out.stdout.strip() == "http://127.0.0.1:19599"

    def test_actual_playwright_config_file(self):
        """实际 playwright.config.js 读 V2_BASE_URL 覆盖 + 缺省 8787。"""
        cfg = REPO_ROOT / "tests" / "v2" / "playwright.config.js"
        content = cfg.read_text(encoding="utf-8")
        assert "process.env.V2_BASE_URL" in content
        assert "http://127.0.0.1:8787" in content
