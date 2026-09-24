"""proc_utils.py — 进程/端口判定的公共助手（verify-process-lifecycle D4/D5）。

从 worktree_manager（_is_claude_process）与 verify_contract（_find_free_port）
上移共用的无状态判定函数，避免模块间循环依赖：

- ``is_claude_process``：进程 argv[0] 是否为 claude agent（存活判定与清扫豁免锚点）；
- ``find_free_port``：向系统申请一个临时空闲端口（bind 0 + getsockname）；
- ``find_bound_socket``：保留已绑定 socket 的 contextmanager（消除 TOCTOU 竞态窗口，
  concurrent-suite-isolation 4.1），绑定失败时按可重试策略重取。

两函数均只依赖 stdlib，任何 core 模块均可安全导入。
"""

import os
import socket
import time
from contextlib import contextmanager


def is_claude_process(pid_str: str) -> bool:
    """进程 argv[0] 是否为 claude agent 可执行文件（basename claude / claude.exe）。

    存活判定与残留清扫都以「agent 进程」为锚：implementer 起的测试子进程
    （v2 dev-server 等）cmdline 同样携带 worktree 路径，若按路径匹配会把
    agent 退出后的永生孤儿误判为持锁者（add-fast-track-mode 派发死锁，
    2026-09-02）。清扫豁免（worktree_manager._kill_worktree_strays 与
    v2_dev_server._worktree_has_live_referencing_process）共用此判定。
    """
    try:
        with open(f"/proc/{pid_str}/cmdline", "rb") as f:
            argv0 = f.read().split(b"\0", 1)[0]
        return os.path.basename(argv0.decode("utf-8", "replace")) in ("claude", "claude.exe")
    except (OSError, IndexError):
        return False


def find_free_port() -> int:
    """向系统申请一个临时空闲端口（探测即释放，向后兼容现有调用方）。"""
    from socket import socket as _socket

    with _socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bind_retry(host: str = "127.0.0.1", retries: int = 3) -> socket.socket:
    """尝试 bind 0 端口（OS 分配），绑定失败时重试（消除 TOCTOU）。"""
    from socket import socket as _socket

    last_err = None
    for _ in range(max(1, retries)):
        try:
            s = _socket()
            s.bind((host, 0))
            return s
        except OSError as e:
            last_err = e
            time.sleep(0.05)
    raise last_err  # type: ignore[misc]


@contextmanager
def find_bound_socket(host: str = "127.0.0.1", retries: int = 3):
    """保留已绑定 socket 的 contextmanager（concurrent-suite-isolation 4.1）。

    退出时释放 socket（无条件关闭）。绑定失败时按可重试策略重取（最多 retries
    次，间隔 50ms），彻底消除「探测到的端口被他人抢占」的 TOCTOU 窗口。

    Usage::

        with find_bound_socket() as s:
            port = s.getsockname()[1]
            # port 在 contextmanager 存活期间被持有
            run_server(port)
        # 退出时 socket 被释放

    既有的 ``find_free_port()`` API 不变（返回 int，立即释放）；新调用方
    （run_full_suite.py / 测试入口）改用本函数获取已绑定端口并传递给子进程。
    """
    s = _bind_retry(host, retries)
    try:
        yield s
    finally:
        try:
            s.close()
        except OSError:
            pass
