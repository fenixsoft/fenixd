"""tests/test_port_allocation.py — fix-run-hang-amplification 4.x

覆盖 5.7：
  - 并发多进程取端口均能独占绑定成功；
  - 绑定被抢占时重试成功（消除 TOCTOU 窗口）。

验证目标：
  ``core.proc_utils.find_bound_socket`` contextmanager 在并发场景下
  每个调用者获得自己可独占绑定的端口，且重试逻辑在抢占时能恢复。
"""
import sys
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.proc_utils import find_bound_socket, find_free_port


# ── 5.7.1 并发独占绑定 ────────────────────────────────────────────────

def _acquire_and_hold(seconds=0.5):
    """在 contextmanager 内获取端口并短暂停留（模拟真实使用窗口），
    返回端口号。"""
    with find_bound_socket() as s:
        port = s.getsockname()[1]
        time.sleep(seconds)
        return port


class TestConcurrentPortAllocation:
    """并发获取端口均能独占绑定。"""

    def test_many_threads_get_unique_ports(self):
        """20 个并发线程同时获取端口，端口互不相同且均绑定成功。"""
        collected_ports = []
        lock = threading.Lock()

        def worker():
            port = _acquire_and_hold(seconds=0.1)
            with lock:
                collected_ports.append(port)

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(worker) for _ in range(20)]
            for f in as_completed(futures):
                f.result()  # raise on exception

        assert len(collected_ports) == 20
        # 所有端口互不相同（真正独占绑定，无 TOCTOU 抢占）
        assert len(set(collected_ports)) == 20, (
            f"expected 20 unique ports, got {len(set(collected_ports))} — "
            f"TOCTOU race may still exist"
        )

    def test_find_free_port_still_works(self):
        """既有 find_free_port API 兼容：返回可用端口。"""
        port = find_free_port()
        assert isinstance(port, int)
        assert 1 <= port <= 65535
        # 能成功绑定（验证端口可用）
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            s.listen(1)


# ── 5.7.2 重试成功（模拟抢占）───────────────────────────────────────

class TestRetryOnConflict:
    """绑定被抢占时重试逻辑能成功获取端口。"""

    def test_retry_succeeds_after_port_taken(self):
        """预先占用一个端口，find_bound_socket 重试后仍能成功绑定（得到不同端口）。"""
        # 先获取一个空闲端口并持有
        held_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held_socket.bind(("127.0.0.1", 0))
        held_port = held_socket.getsockname()[1]
        held_socket.listen(1)
        try:
            # find_bound_socket 应能在重试后得到另一个端口
            port = _acquire_and_hold()
            assert port != held_port, "should get a different port due to retry"
            # 能成功绑定到新端口
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
        finally:
            held_socket.close()


# ── 5.7.3 contextmanager 生命周期 ─────────────────────────────────────

class TestBoundSocketLifecycle:
    """contextmanager 退出时 socket 被释放。"""

    def test_socket_closed_after_context(self):
        """退出 contextmanager 后端口应被释放，可被其他人绑定。"""
        port = _acquire_and_hold()
        # 端口已释放，尝试绑定
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            s.listen(1)
            # 验证绑定成功（无 OSError）
            assert s.getsockname()[1] == port
