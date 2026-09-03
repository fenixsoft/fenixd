"""
孤儿实例防护单测（_bind_parent_lifecycle）——2026-09-03 runs 删空事故 V1 防线。

调试脚本直接 import serve() 起实例后孤儿化（PPID→1），以旧码长期服务端口。
防护：FENIX_DASHBOARD_DETACH=1 豁免；先设 PR_SET_PDEATHSIG 再查 PPID==1 拒启。
"""
import ctypes
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard.server import _bind_parent_lifecycle


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
