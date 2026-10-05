"""proc_utils.py — 进程/端口判定的公共助手（verify-process-lifecycle D4/D5）。

从 worktree_manager（_is_claude_process）与 verify_contract（_find_free_port）
上移共用的无状态判定函数，避免模块间循环依赖：

- ``is_claude_process``：进程 argv[0] 是否为 claude agent（存活判定与清扫豁免锚点）；
- ``proc_stat_fields``：/proc/<pid>/stat 尾段单点解析（comm 可含括号与空格的陷阱在此收口）；
- ``pid_alive_stat``：/proc stat 口径存活判定，僵尸态语义由 zombie_is_dead 显式选择；
- ``proc_start_ticks``：starttime 身份快照（pid 复用防护锚点）；
- ``pid_alive_signal``：kill(pid, 0) 存在性判定（不区分僵尸态）；
- ``find_free_port``：向系统申请一个临时空闲端口（bind 0 + getsockname）；
- ``find_bound_socket``：保留已绑定 socket 的 contextmanager（消除 TOCTOU 竞态窗口，
  concurrent-suite-isolation 4.1），绑定失败时按可重试策略重取。

以下助手均只依赖 stdlib，任何 core 模块均可安全导入。
"""

import os
import socket
import time
from contextlib import contextmanager
from typing import List, Optional


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


def proc_stat_fields(pid: int) -> Optional[List[str]]:
    """读取 /proc/<pid>/stat，返回最后一个 ')' 之后的字段列表（首项即字段 3 state）。

    comm 字段（第 2 项）可含空格与括号，须从**最后一个** ')' 之后切分才是
    真正的状态字段区——这是 stat 解析的经典陷阱，此处单点收口，供存活判定
    （pid_alive_stat）与身份快照（proc_start_ticks）共用，避免同款解析在
    各模块漂移。

    读取失败（/proc 缺失、权限不足、非 Linux 等 OSError）或内容无右括号
    （畸形）返回 None。
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    _, sep, tail = data.rpartition(")")
    if not sep:
        return None
    return tail.split()


def pid_alive_stat(pid: int, zombie_is_dead: bool = False) -> bool:
    """/proc stat 口径的存活判定；僵尸态语义由 zombie_is_dead 显式选择。

    两种口径各有场景理由，由调用点显式参数选择而非隐式共享：

    - zombie_is_dead=True（v2_dev_server 孤儿清扫）：孤儿 dev-server 的父
      进程（已死 daemon 的 shell 链）可能不收尸，/proc 条目以 Z 态残留，
      须按已终止计，否则误补 SIGKILL 且漏计清理数；
    - zombie_is_dead=False：/proc 条目可读即存活（含 Z 态），与 kill(pid, 0)
      口径（pid_alive_signal）的「有主即活」保守方向一致。

    stat 不可读（/proc 缺失、权限、畸形）按已终止计（宁可少杀）。
    """
    fields = proc_stat_fields(pid)
    if fields is None:
        return False
    if zombie_is_dead and fields[:1] == ["Z"]:
        return False
    return True


def proc_start_ticks(pid: int) -> Optional[int]:
    """/proc/<pid>/stat 的 starttime 字段（字段 22，系统启动后的 tick 数），读不到返回 None。

    pid + starttime 唯一确定一个进程实例：原进程退出后 pid 被系统复用时，
    新进程的 starttime 必然不同——以此锚定登记项的收割目标（对 exec/argv
    变化免疫，starttime 在 fork 时即固定），serving_registry 登记制据此
    做 pid 复用防误杀。
    """
    fields = proc_stat_fields(pid)
    if fields is None or len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def pid_alive_signal(pid: int) -> bool:
    """kill(pid, 0) 存在性判定：命中即存活（不区分僵尸态，够用）。

    EPERM 恰恰证明目标进程存在、仅属其他用户（无权发信号）——按存活，
    与 kill_process_group 对 getpgid EPERM 的显式处理同口径。
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def find_free_port() -> int:
    """向系统申请一个临时空闲端口（探测即释放，向后兼容现有调用方）。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _bind_retry(host: str = "127.0.0.1", retries: int = 3) -> socket.socket:
    """尝试 bind 0 端口（OS 分配），绑定失败时重试（消除 TOCTOU）。"""
    last_err = None
    s = None
    for _ in range(max(1, retries)):
        try:
            s = socket.socket()
            s.bind((host, 0))
            return s
        except OSError as e:
            # bind 失败时显式释放已创建的 socket（与 find_bound_socket 的
            # 释放纪律对齐；非引用计数实现下避免 fd 积累）
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
                s = None
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

    既有的 ``find_free_port()`` API 不变（返回 int，立即释放）；当前仓库内
    消费方为测试入口（tests/test_port_allocation.py），套件入口
    （bin/run_full_suite.py）暂经 FENIX_SUITE_PORT_BASE 端口段约定分配，
    尚未接入本函数。
    """
    s = _bind_retry(host, retries)
    try:
        yield s
    finally:
        try:
            s.close()
        except OSError:
            pass


def hold_free_port(host: str = "127.0.0.1", retries: int = 3) -> socket.socket:
    """返回一个已绑定匿名端口的占位 socket（调用方持有至 spawn 前再关闭）。

    ``find_free_port`` 探测即释放，「探测 → 实际使用」之间存在 TOCTOU 窗口，
    端口可被并发进程抢占；本助手返回的 socket 在被关闭前一直占住该端口，
    把「分配端口 → 子进程绑定」之间的空窗压缩到 close→spawn 一瞬
    （code-review item eb7fb0c8d239）。适用于进程为任意命令、无法经 fd
    移交继承绑定的场景；可直接移交 socket 的场景用 ``find_bound_socket``。

    Usage::

        holder = hold_free_port()
        port = holder.getsockname()[1]
        ...  # 准备命令行/预检等耗时步骤，端口始终被占住
        holder.close()
        spawn(cmd_with_port)
    """
    return _bind_retry(host, retries)
