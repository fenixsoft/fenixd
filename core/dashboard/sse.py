"""sse.py — SSE 连接 / 订阅集线器（refactor-giant-classes D1/D3）。

原为 `core/dashboard/server.py` 的伴生类 `SSEConnection`/`SSEHub`
（design D1 表 C「伴生类」），原样搬移。

D3 patch 缝隙：`MAX_SSE_CONNECTIONS` 常量仍定义在 `core.dashboard.server`
命名空间（测试 `monkeypatch.setattr(server_mod, "MAX_SSE_CONNECTIONS", 2)`
patch 该命名空间属性）——本模块调用点 MUST 经 `core.dashboard.server`
命名空间**延迟解析**（不得顶部 import 绑定常量），否则重绑不生效。
"""

from __future__ import annotations

import queue
import threading


class SSEConnection:
    """一条浏览器 SSE 长连接：自带事件队列 + 该连接订阅的 run。

    慢客户端不阻塞广播者：队列满则丢弃最旧事件，队列上限防止内存无界增长。
    """

    def __init__(self, cid: str):
        self.id = cid
        self.queue = queue.Queue(maxsize=256)
        self.watched_runs = set()  # 该连接打开的 run 弹窗（增量推送目标）

    def send(self, event: dict):
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            pass


class SSEHub:
    """SSE 连接注册 / 广播 / run 订阅管理（供 watcher 推送 + handler 注册）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._conns = {}  # cid -> SSEConnection
        self._seq = 0

    def register(self) -> SSEConnection | None:
        """注册新 SSE 连接；活跃连接数 ≥ MAX_SSE_CONNECTIONS 时拒绝（返回 None）。

        拒绝语义（dashboard-connection-limit D6）：已建立连接不受影响；被拒客户端
        由前端退化为轮询（心跳兜底）。计数经锁保护，断开时 unregister 回落。

        D3 缝隙：连接上限常量经 `core.dashboard.server` 命名空间延迟解析
        （测试 monkeypatch 该命名空间属性）。
        """
        from core.dashboard import server as _server_mod

        max_conns = getattr(_server_mod, "MAX_SSE_CONNECTIONS", 32)
        with self._lock:
            if len(self._conns) >= max_conns:
                return None
            self._seq += 1
            conn = SSEConnection(f"c{self._seq}")
            self._conns[conn.id] = conn
        return conn

    def unregister(self, conn: SSEConnection):
        with self._lock:
            self._conns.pop(conn.id, None)

    def broadcast(self, event: dict, run_id: str | None = None):
        """广播事件；run_id 非空时只发给订阅了该 run 的连接。

        成员测试与 watch/unwatch 写侧同锁（self._lock），保证 watched_runs
        读写锁纪律对称。conn.send 在锁内调用安全：仅做 queue nowait 操作
        （非阻塞、无网络写），队列内部互斥量是叶子锁（消费侧 get 等待时
        释放，且无任何路径持队列锁反向获取本锁），锁序单向，无死锁或阻塞放大。
        """
        with self._lock:
            for conn in self._conns.values():
                if run_id is None or run_id in conn.watched_runs:
                    conn.send(event)

    def watch(self, cid: str, run_id: str):
        with self._lock:
            conn = self._conns.get(cid)
            if conn:
                conn.watched_runs.add(run_id)

    def unwatch(self, cid: str, run_id: str):
        with self._lock:
            conn = self._conns.get(cid)
            if conn:
                conn.watched_runs.discard(run_id)

    def is_watched(self, run_id: str) -> bool:
        with self._lock:
            return any(run_id in c.watched_runs for c in self._conns.values())