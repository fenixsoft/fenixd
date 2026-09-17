"""sse_routes.py — H9 SSE（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的 SSE 方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D3 patch 缝隙：`SSE_CLIENT_POLL_INTERVAL` 常量仍定义在
`core.dashboard.server` 命名空间（测试 monkeypatch 该命名空间属性）——
本模块调用点 MUST 经 `core.dashboard.server` 命名空间**延迟解析**。
"""

from __future__ import annotations

import json
import queue
import socket
import time


class H9SseRoutesMixin:
    """H9 SSE（design D1 表 C H9）。"""

    def _handle_sse(self):
        """GET /api/stream —— 常驻 SSE 长连接，收到 watcher 广播即推送。

        首次事件为 hello（携带 cid，供前端注册 run 增量订阅）；此后持续阻塞
        读取连接事件队列，25s 无事件发心跳注释帧保活。客户端断开即清理。
        活跃连接数 ≥ MAX_SSE_CONNECTIONS 时拒绝（503 + JSON 错误体），
        客户端收到后应退化为轮询（dashboard-connection-limit D6）。
        为及时释放连接槽位（释放后恢复可测），除写心跳外每个队列超时
        （≤1s）做一次客户端 socket 可读探测：客户端 FIN → 立即 unregister。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙

        conn = self.server.sse_hub.register()
        if conn is None:
            self._error(503, "too many SSE connections")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            self._sse_send({"type": "hello", "cid": conn.id})
            last_heartbeat = time.monotonic()
            poll_interval = getattr(_server_mod, "SSE_CLIENT_POLL_INTERVAL", 1.0)
            while True:
                try:
                    event = conn.queue.get(timeout=poll_interval)
                except queue.Empty:
                    # 客户端断开探测：可读且 recv 返回 b""（EOF/FIN）即已断开
                    if self._sse_client_gone():
                        break
                    # 25s 心跳保活
                    if time.monotonic() - last_heartbeat >= 25:
                        self._sse_send(None)
                        last_heartbeat = time.monotonic()
                    continue
                if event is None:  # 关闭信号
                    break
                self._sse_send(event)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.server.sse_hub.unregister(conn)

    def _sse_client_gone(self) -> bool:
        """探测 SSE 客户端 socket 是否已关闭（FIN）。

        用 select 探测可读性 + recv(MSG_PEEK) 判 EOF，不消费任何真实数据，
        避免误读浏览器可能发送的其它字节。
        """
        import select

        try:
            r, _, _ = select.select([self.connection], [], [], 0)
        except (OSError, ValueError):
            return True
        if not r:
            return False
        try:
            data = self.connection.recv(1, socket.MSG_PEEK)
        except (BlockingIOError, OSError, ValueError):
            return True
        return data == b""

    def _sse_send(self, event: dict | None):
        """以 HTTP/1.1 chunked 帧写入一条 SSE 消息；event=None 写心跳注释。

        不带 event: 命名行——命名事件不触发前端 onmessage，只有默认事件才触发；
        事件类型已由 data 中的 type 字段区分。
        """
        if event is None:
            frame = b": ping\n\n"
        else:
            data = json.dumps(event, ensure_ascii=False)
            frame = ("data: %s\n\n" % data).encode("utf-8")
        chunk = b"%X\r\n" % len(frame) + frame + b"\r\n"
        self.wfile.write(chunk)
        self.wfile.flush()