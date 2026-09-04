"""
孤儿实例防护单测（_bind_parent_lifecycle）——2026-09-03 runs 删空事故 V1 防线。

调试脚本直接 import serve() 起实例后孤儿化（PPID→1），以旧码长期服务端口。
防护：FENIX_DASHBOARD_DETACH=1 豁免；先设 PR_SET_PDEATHSIG 再查 PPID==1 拒启。

2026-09-04 第二防线（claude-watchdog）：CLI 豁免被 agent 的 nohup 自测利用
（add-run-cancel 8790 泄漏），豁免通道检测到 agent 环境（CLAUDE_PID）时绑定
claude 进程生命周期——claude 死则实例自杀；纯人 CLI（无 CLAUDE_PID）豁免不变。
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard.server import (
    _bind_parent_lifecycle,
    _claude_watchdog_loop,
    _proc_starttime,
    _start_claude_watchdog,
)


class _FakeLibc:
    def __init__(self, ret=0):
        self.ret = ret
        self.calls = []

    def prctl(self, *args):
        self.calls.append(args)
        return self.ret


def test_detach_env_skips_binding(monkeypatch):
    """显式豁免（CLI 长驻入口）：不设 PDEATHSIG、不做孤儿检查、不退出。"""
    monkeypatch.setenv("FENIX_DASHBOARD_DETACH", "1")
    calls = []

    def _no_cdll(*a, **k):
        calls.append(a)
        return _FakeLibc(0)

    monkeypatch.setattr(ctypes, "CDLL", _no_cdll)
    _bind_parent_lifecycle()
    assert calls == []


def test_orphan_start_rejected(monkeypatch):
    """启动时已是孤儿（PPID=1）→ SystemExit(1)。"""
    monkeypatch.delenv("FENIX_DASHBOARD_DETACH", raising=False)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: _FakeLibc(0))
    monkeypatch.setattr(os, "getppid", lambda: 1)
    with pytest.raises(SystemExit) as ei:
        _bind_parent_lifecycle()
    assert ei.value.code == 1


def test_live_parent_binds_pdeathsig(monkeypatch):
    """正常父进程：PR_SET_PDEATHSIG(1) + SIGTERM 被设置，随后正常返回。"""
    monkeypatch.delenv("FENIX_DASHBOARD_DETACH", raising=False)
    fake = _FakeLibc(0)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: fake)
    monkeypatch.setattr(os, "getppid", lambda: 10086)
    _bind_parent_lifecycle()
    assert fake.calls, "prctl 应被调用"
    assert fake.calls[0][0] == 1  # PR_SET_PDEATHSIG
    assert fake.calls[0][1] == 15  # SIGTERM


def test_prctl_failure_warns_but_continues(monkeypatch):
    """prctl 失败（非 Linux 等）：仅告警不阻断；PPID 非 1 时不退出。"""
    monkeypatch.delenv("FENIX_DASHBOARD_DETACH", raising=False)
    fake = _FakeLibc(-1)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: fake)
    monkeypatch.setattr(os, "getppid", lambda: 10086)
    _bind_parent_lifecycle()
    assert fake.calls


def test_cdll_unavailable_warns_but_continues(monkeypatch):
    """libc 加载失败：仅告警不阻断（PPID 非 1 时不退出）。"""
    monkeypatch.delenv("FENIX_DASHBOARD_DETACH", raising=False)

    def _boom(*a, **k):
        raise OSError("no libc")

    monkeypatch.setattr(ctypes, "CDLL", _boom)
    monkeypatch.setattr(os, "getppid", lambda: 10086)
    _bind_parent_lifecycle()


# ── 第二防线：claude-watchdog（agent 豁免通道的生命周期绑定）──────────


def _wait_thread(name: str, timeout: float = 2.0) -> threading.Thread | None:
    """等待名为 name 的线程出现（装配在后台线程中完成时存在竞态）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for t in threading.enumerate():
            if t.name == name:
                return t
        time.sleep(0.02)
    return None


def test_proc_starttime_of_live_and_dead_process():
    """活进程返回与 /proc 一致的 starttime；死进程返回 None。"""
    st = _proc_starttime(os.getpid())
    assert st is not None and st > 0
    # 与 /proc 原文独立核对一次
    raw = Path(f"/proc/{os.getpid()}/stat").read_text()
    fields = raw[raw.rindex(")") + 2:].split()
    assert st == int(fields[19])
    assert _proc_starttime(10 ** 9) is None


def test_watchdog_skipped_without_claude_pid(monkeypatch):
    """纯人 CLI（无 CLAUDE_PID）：不装配 watchdog，豁免行为不变。"""
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    before = {t.name for t in threading.enumerate()}
    assert _start_claude_watchdog() is False
    assert {t.name for t in threading.enumerate()} == before


def test_watchdog_skipped_for_dead_or_garbage_pid(monkeypatch):
    """CLAUDE_PID 指向已死进程/非数字：无法绑定，按纯豁免处理（False）。"""
    for raw in (str(10 ** 9), "not-a-number"):
        monkeypatch.setenv("CLAUDE_PID", raw)
        assert _start_claude_watchdog() is False


def test_watchdog_assembled_for_agent_env(monkeypatch):
    """agent 环境（CLAUDE_PID=存活 claude 进程）：装配名为 claude-watchdog 的 daemon 线程。

    目标用测试进程自身（永不退出），线程随 pytest 进程结束回收，无自杀副作用。
    """
    monkeypatch.setenv("FENIX_DASHBOARD_DETACH", "1")
    monkeypatch.setenv("CLAUDE_PID", str(os.getpid()))
    assert _start_claude_watchdog() is True
    t = _wait_thread("claude-watchdog")
    assert t is not None, "应出现名为 claude-watchdog 的线程"
    assert t.daemon is True


def test_bind_parent_lifecycle_detaches_with_watchdog(monkeypatch):
    """集成：DETACH=1 + CLAUDE_PID 下 _bind_parent_lifecycle 装配 watchdog（本次缺口的行为修复点）。"""
    monkeypatch.setenv("FENIX_DASHBOARD_DETACH", "1")
    monkeypatch.setenv("CLAUDE_PID", str(os.getpid()))
    calls = []
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: calls.append(a) or _FakeLibc(0))
    _bind_parent_lifecycle()
    assert calls == [], "豁免通道不应设 PDEATHSIG"
    assert _wait_thread("claude-watchdog") is not None


def test_watchdog_loop_fires_when_target_dies():
    """目标进程死亡 → on_death 被触发（轮询回路，不真自杀）。"""
    victim = subprocess.Popen(["sleep", "30"])
    st = _proc_starttime(victim.pid)
    fired = threading.Event()
    t = threading.Thread(
        target=_claude_watchdog_loop,
        args=(victim.pid, st),
        kwargs={"interval": 0.05, "on_death": fired.set},
        daemon=True,
    )
    t.start()
    try:
        assert not fired.wait(timeout=0.2), "目标存活期间不应触发"
        victim.kill()
        victim.wait()
        assert fired.wait(timeout=2.0), "目标死亡后应触发 on_death"
    finally:
        if victim.poll() is None:
            victim.kill()
            victim.wait()


def test_watchdog_loop_fires_on_pid_reuse_starttime_mismatch():
    """PID 复用防护：/proc starttime 与登记值不匹配 → 触发 on_death。

    用活进程 + 篡改的登记 starttime 模拟复用（复用后 starttime 必然不同）。
    """
    stranger = subprocess.Popen(["sleep", "30"])
    try:
        real = _proc_starttime(stranger.pid)
        fired = threading.Event()
        t = threading.Thread(
            target=_claude_watchdog_loop,
            args=(stranger.pid, real + 12345),
            kwargs={"interval": 0.05, "on_death": fired.set},
            daemon=True,
        )
        t.start()
        assert fired.wait(timeout=2.0), "starttime 不匹配应立即触发"
    finally:
        if stranger.poll() is None:
            stranger.kill()
            stranger.wait()
