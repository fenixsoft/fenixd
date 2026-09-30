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

# SSE 心跳周期（秒）。心跳在统一节拍点（_sse_tick）触发：queue 超时分支
# 每轮检查、正常事件分支到点补发，实际节奏粒度由 poll_interval 决定，因此
# poll_interval 必须 ≤ SSE_HEARTBEAT_SECONDS，否则心跳会迟到。
SSE_HEARTBEAT_SECONDS = 25
# poll_interval 缺省值（秒）。生产者真值在 core.dashboard.server 命名空间
# （D3 缝隙，测试 monkeypatch 该属性），此处仅作 getattr 兜底，须与真值一致。
SSE_POLL_INTERVAL_DEFAULT = 1.0
# SSE 连接 socket 写超时（秒）。停滞客户端（连接在但停止读）会把 TCP 发送缓冲
# 写满，使 _sse_send 的 write/flush 无限期阻塞，占死一个连接槽位与一个处理线程；
# 对 connection 设超时后写停滞以 socket.timeout（OSError 子类）浮出，由
# _handle_sse 既有 except 捕获、finally unregister 释放槽位。取值须明显大于
# 心跳节拍（SSE_HEARTBEAT_SECONDS），健康但缓慢的客户端不致被误断。
# [fenix-ignore:d2618f82c7d9] 当前单帧极小（心跳注释帧约 9 字节），30s 写超时相对 25s 心跳的 5s 裕度经核实成立，属前瞻性建议不值得现在改；约束：后续帧负载增大（心跳携带负载或批量事件单帧变大）时须将写超时放大到心跳 3 倍以上，或改按剩余缓冲量动态超时。
SSE_WRITE_TIMEOUT_SECONDS = 30.0


class H9SseRoutesMixin:
    """H9 SSE（design D1 表 C H9）。"""

    def _handle_sse(self):
        """GET /api/stream —— 常驻 SSE 长连接，收到 watcher 广播即推送。

        首次事件为 hello（携带 cid，供前端注册 run 增量订阅）；此后持续阻塞
        读取连接事件队列，距上次心跳超 25s 发心跳注释帧保活。客户端断开即清理。
        活跃连接数 ≥ MAX_SSE_CONNECTIONS 时拒绝（503 + JSON 错误体），
        客户端收到后应退化为轮询（dashboard-connection-limit D6）。
        为及时释放连接槽位（释放后恢复可测），节拍点（_sse_tick：每个队列
        超时 ≤1s 一查，及正常事件分支心跳到点时）做一次客户端 socket 可读
        探测：客户端 FIN → 立即 unregister。事件高频到达期循环走不到队列
        超时分支，靠正常事件分支的时间驱动节拍保证探测与心跳不被饿死。
        连接建立前对 socket 设写超时（SSE_WRITE_TIMEOUT_SECONDS）：连接仍在但
        停止读的客户端不受 FIN 探测影响，须靠写超时突破 write 阻塞后退出释放。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙

        conn = self.server.sse_hub.register()
        if conn is None:
            self._error(503, "too many SSE connections")
            return
        # 停滞客户端防占位：无超时则发送缓冲写满后 _sse_send 永久阻塞，
        # 占死连接槽位与处理线程；写超时经 socket.timeout（OSError 子类）
        # 由下方 except 捕获，finally unregister 释放槽位。
        try:
            # 注册已占槽位，故 settimeout 与写响应头各步须纳入 try/finally 覆盖：
            # 若留在 try 外，响应首字节刷出前客户端 RST 会让写失败穿出本方法、
            # finally 未建立，该槽位永久泄漏（仅进程重启可回收）。
            self.connection.settimeout(SSE_WRITE_TIMEOUT_SECONDS)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self._sse_send({"type": "hello", "cid": conn.id})
            last_heartbeat = time.monotonic()
            poll_interval = getattr(
                _server_mod, "SSE_CLIENT_POLL_INTERVAL", SSE_POLL_INTERVAL_DEFAULT
            )
            while True:
                try:
                    event = conn.queue.get(timeout=poll_interval)
                except queue.Empty:
                    gone, last_heartbeat = self._sse_tick(last_heartbeat)
                    if gone:
                        break
                    continue
                if event is None:  # 关闭信号
                    # 流正常结束：补写 chunked 终止块，使响应符合 RFC 7230
                    # chunked 语义（避免严格代理/客户端把无终止块的响应记为
                    # 协议错误，如 ERR_INCOMPLETE_CHUNKED_ENCODING）。此时连接
                    # 可能已被对端关闭，写失败容忍忽略；客户端断开（FIN 探测）
                    # 与写异常路径不写，直接关闭连接终结流。
                    # 此处刻意不置 close_connection，连接复用策略在 base 层：
                    # 上方显式 Connection: keep-alive 响应头使
                    # BaseHTTPRequestHandler.send_header 置 close_connection=False
                    # （protocol_version="HTTP/1.1"，见 server.py），流终结后
                    # base 层 handle 循环会在同一连接继续读下一请求（EventSource
                    # 重连可复用）；该连接仍挂 SSE_WRITE_TIMEOUT_SECONDS 读超时，
                    # 空闲超时由 base 层读超时关闭。若改显式 close_connection=True，
                    # 须先确认前端重连与既有测试对连接复用的依赖
                    # （code-review item 06b2943f7fd7）。
                    try:
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                    except OSError:
                        pass
                    break
                self._sse_send(event)
                # 时间驱动节拍（code-review item a2734b88dc1f）：事件高频到达
                # 期循环长期走不到 queue.Empty 分支，节拍检查不能依赖其偶然
                # 调度——否则心跳停发（代理按空闲超时误切存活连接），停滞
                # 客户端也只能等写超时兜底。心跳到点即经 _sse_tick 补发心跳
                # 帧并顺带做一次 FIN 探测，探测到断开按既有路径收尾。
                if time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                    gone, last_heartbeat = self._sse_tick(last_heartbeat)
                    if gone:
                        break
        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
            socket.timeout,  # 写超时（OSError 子类，显式列出以文档化停滞退出路径）
            OSError,
        ):
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
        except (BlockingIOError, socket.timeout):
            # 暂无数据可读 ≠ EOF。connection 已设写超时（超时模式），select 就绪
            # 与数据到达间的竞态下 recv 抛 socket.timeout 而非 BlockingIOError
            # （后者仅在纯非阻塞模式出现，保留以免误落下方 OSError 分支被误判断开）
            return False
        except (OSError, ValueError):
            return True
        return data == b""

    def _sse_tick(self, last_heartbeat: float) -> tuple[bool, float]:
        """统一节拍点：FIN 探测 + 到点补发心跳（queue 超时/正常事件两分支共用）。

        返回 (client_gone, new_last_heartbeat)。探测到客户端断开立即返回
        True，由调用方按既有路径 break 收尾（code-review item a2734b88dc1f）。
        """
        # 客户端断开探测：可读且 recv 返回 b""（EOF/FIN）即已断开
        if self._sse_client_gone():
            return True, last_heartbeat
        # 心跳保活（粒度受 poll_interval 约束，见模块头注释）
        if time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
            self._sse_send(None)
            last_heartbeat = time.monotonic()
        return False, last_heartbeat

    def _sse_send(self, event: dict | None):
        """以 HTTP/1.1 chunked 帧写入一条 SSE 消息；event=None 写心跳注释。

        不带 event: 命名行——命名事件不触发前端 onmessage，只有默认事件才触发；
        事件类型已由 data 中的 type 字段区分。
        """
        if event is None:
            frame = b": ping\n\n"
        else:
            # default=str：事件含不可序列化对象（如 datetime）时降级为字符串，
            # 避免 TypeError 穿出外层仅捕获连接类异常的 try 导致异常外泄
            data = json.dumps(event, ensure_ascii=False, default=str)
            frame = ("data: %s\n\n" % data).encode("utf-8")
        chunk = b"%X\r\n" % len(frame) + frame + b"\r\n"
        self.wfile.write(chunk)
        self.wfile.flush()