"""http_server.py — DashboardHTTPServer（refactor-giant-classes D1/D3/D6）。

原为 `core/dashboard/server.py` 的伴生类 `DashboardHTTPServer`
（design D1 表 C「伴生类」），原样搬移。

D6 无环约束：本模块 MUST NOT 顶部 import `core.dashboard.server`
（server.py 引用本模块的 DashboardHTTPServer）——
`DashboardHandler`（handler_class）经 `__init__` 参数注入 + 延迟解析。

D3 patch 缝隙：`MAX_SERVER_THREADS` 常量仍定义在 `core.dashboard.server`
命名空间（测试 `monkeypatch.setattr(server_mod, "MAX_SERVER_THREADS", 2)`
patch 该命名空间属性）——本模块调用点 MUST 经 `core.dashboard.server`
命名空间**延迟解析**（不得顶部 import 绑定常量），否则重绑不生效。
"""

from __future__ import annotations

import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from . import data as dashboard_data
from .registry import Registry
from .sse import SSEHub


class DashboardHTTPServer(ThreadingHTTPServer):
    """携带 registry / static_dir / 项目缓存的自定义 HTTP 服务器。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, registry: Registry, static_dir: Path, handler_class=None):
        # D6 无环：handler_class（DashboardHandler）由 server.py 注入；
        # 缺省经延迟解析兜底（http_server 自身不得顶部 import server）。
        if handler_class is None:
            from core.dashboard import server as _server_mod

            handler_class = _server_mod.DashboardHandler
        super().__init__(addr, handler_class)
        self.registry = registry
        self.static_dir = Path(static_dir)
        self.sse_hub = SSEHub()
        self.summary_index = dashboard_data.SummaryIndex()  # 摘要索引（thread-safe）
        self.watcher = None  # serve() 中创建并启动
        self.session_manager = None  # serve() 中创建并启动（dashboard-live-session 3.1）
        self._projects_cache = []
        self._cache_ts = 0.0
        self._cache_ttl = 10.0
        # 并发请求槽位计数（dashboard-connection-limit D6）：entry 获取、finally 释放
        self._request_slots = 0
        self._slots_lock = threading.Lock()

    def _try_acquire_request_slot(self) -> bool:
        """尝试获取一个处理槽位；并发数 ≥ MAX_SERVER_THREADS 时拒绝。

        D3 缝隙：上限常量经 `core.dashboard.server` 命名空间延迟解析。
        """
        from core.dashboard import server as _server_mod

        max_threads = getattr(_server_mod, "MAX_SERVER_THREADS", 64)
        with self._slots_lock:
            if self._request_slots >= max_threads:
                return False
            self._request_slots += 1
            return True

    def _release_request_slot(self):
        with self._slots_lock:
            self._request_slots = max(0, self._request_slots - 1)

    def projects(self) -> list:
        """带 TTL 的发现结果缓存（扫描开销低但避免每次请求都扫盘）。

        发现异常兜底（fix-dashboard-fault-isolation D5）：`discover()` 抛异常时
        保留上次成功结果（从未成功过则为空列表）并记录错误，异常 MUST NOT
        冒泡；`_cache_ts` 无条件推进，使 TTL 内后续请求复用上次结果而非每个
        请求都重试一次注定失败的发现。
        """
        from core.dashboard import server as _server_mod

        logger = _server_mod.logger
        now = time.time()
        if now - self._cache_ts > self._cache_ttl:
            try:
                self._projects_cache = self.registry.discover()
            except Exception as exc:  # noqa: BLE001 —— 发现层兜底，不得使请求失败
                # 保留 _projects_cache 原值；记录错误；不抛出
                logger.error("项目发现失败，复用上次成功结果: %s", exc)
            finally:
                self._cache_ts = now
        return self._projects_cache

    def invalidate_projects_cache(self):
        """使 projects() 的 TTL 缓存立即失效（下一次调用强制重新 discover）。

        改变发现结果的写操作（删除项目等）完成后必须调用：缓存 TTL 内的
        后续读请求否则会拿到变更前的旧项目集——已删项目在概览页
        「消失→马上重现→约 10s（=TTL）后才再消失」。
        """
        self._cache_ts = 0.0

    def project_by_name(self, name: str):
        for p in self.projects():
            if p["name"] == name:
                return p
        return None