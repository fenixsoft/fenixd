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
    _is_tmux_hosted,
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
    # 显式隔离新判据：tmux 直接承载 pytest（tmux new-session "pytest …"）时
    # 真实父进程即 tmux server，不隔离会被判为常驻而假失败
    monkeypatch.setattr("core.dashboard.server._is_tmux_hosted", lambda ppid=None: False)
    assert _start_claude_watchdog() is True
    t = _wait_thread("claude-watchdog")
    assert t is not None, "应出现名为 claude-watchdog 的线程"
    assert t.daemon is True


def test_bind_parent_lifecycle_detaches_with_watchdog(monkeypatch):
    """集成：DETACH=1 + CLAUDE_PID 下 _bind_parent_lifecycle 装配 watchdog（本次缺口的行为修复点）。"""
    monkeypatch.setenv("FENIX_DASHBOARD_DETACH", "1")
    monkeypatch.setenv("CLAUDE_PID", str(os.getpid()))
    # 同上：隔离真实父进程身份（tmux 承载 pytest 时判据会命中常驻）
    monkeypatch.setattr("core.dashboard.server._is_tmux_hosted", lambda ppid=None: False)
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


# ── 显式长驻判据：_is_tmux_hosted（2026-09-22 8787 误杀事故）──────────


def _patch_proc_files(monkeypatch, mapping):
    """把模块内 Path 对 /proc/<pid>/… 的读取重定向到临时文件。

    mapping 形如 {"/proc/4242/comm": tmp_path/"comm"}；未映射的路径原样透传。
    """
    import core.dashboard.server as server_mod

    real_path = Path

    def fake_path(p, *a, **k):
        p = str(p)
        if p in mapping:
            return real_path(mapping[p])
        return real_path(p)

    monkeypatch.setattr(server_mod, "Path", fake_path)


def test_is_tmux_hosted_detects_tmux_parent(monkeypatch, tmp_path):
    """comm 恰为 'tmux: server' → True；非 tmux comm → False；/proc 读取失败 → False。"""
    comm = tmp_path / "comm"
    comm.write_text("tmux: server\n")
    _patch_proc_files(monkeypatch, {"/proc/4242/comm": comm})
    assert _is_tmux_hosted(4242) is True

    comm.write_text("bash\n")
    assert _is_tmux_hosted(4242) is False

    # comm 不匹配 → 回退 cmdline：argv[0] basename 恰为 tmux → True；
    # 仅含 tmux 子串（agent 自测包装脚本形态）→ False
    cmdline = tmp_path / "cmdline"
    _patch_proc_files(
        monkeypatch, {"/proc/4242/comm": comm, "/proc/4242/cmdline": cmdline}
    )
    comm.write_text("sleep\n")
    cmdline.write_bytes(b"tmux\x00attach\x00\x00")
    assert _is_tmux_hosted(4242) is True
    cmdline.write_bytes(b"/tmp/tmux_selftest.sh\x00\x00")
    assert _is_tmux_hosted(4242) is False

    # /proc 读取失败（进程不存在等）：按非长驻处理 → False
    _patch_proc_files(monkeypatch, {"/proc/4242/comm": tmp_path / "gone" / "comm"})
    assert _is_tmux_hosted(4242) is False


def test_is_tmux_hosted_tolerates_undecodable_comm(monkeypatch, tmp_path):
    """comm 含非法 UTF-8 字节（PR_SET_NAME 可写任意字节）→ replace 解码按非匹配处理。

    UnicodeDecodeError 是 ValueError 不是 OSError，若判据用严格 read_text 解码会
    逃逸处理器、违反「读取失败 → False」契约（code-review 发现的回归锚）。
    """
    comm = tmp_path / "comm"
    comm.write_bytes(b"tmux: \xff\xfe server\n")
    _patch_proc_files(monkeypatch, {"/proc/4242/comm": comm})
    assert _is_tmux_hosted(4242) is False


def test_watchdog_skipped_when_tmux_hosted(monkeypatch):
    """tmux 承载（显式长驻）：即使 CLAUDE_PID 指向存活进程也不装配 watchdog。"""
    monkeypatch.setenv("FENIX_DASHBOARD_DETACH", "1")
    monkeypatch.setenv("CLAUDE_PID", str(os.getpid()))
    monkeypatch.setattr("core.dashboard.server._is_tmux_hosted", lambda ppid=None: True)
    before = {t.name for t in threading.enumerate()}
    assert _start_claude_watchdog() is False
    assert {t.name for t in threading.enumerate()} == before, "不应新装配任何线程"


def test_watchdog_still_assembled_when_not_tmux_hosted(monkeypatch):
    """非 tmux 承载（agent nohup 自测形态）：既有防泄漏不变，仍装配 watchdog。"""
    monkeypatch.setenv("FENIX_DASHBOARD_DETACH", "1")
    monkeypatch.setenv("CLAUDE_PID", str(os.getpid()))
    monkeypatch.setattr("core.dashboard.server._is_tmux_hosted", lambda ppid=None: False)
    before = sum(1 for t in threading.enumerate() if t.name == "claude-watchdog")
    assert _start_claude_watchdog() is True
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        now = sum(1 for t in threading.enumerate() if t.name == "claude-watchdog")
        if now > before:
            break
        time.sleep(0.02)
    else:
        pytest.fail("应新装配一个 claude-watchdog 线程")


def test_is_tmux_hosted_ignores_tmux_env(monkeypatch):
    """自身环境含 TMUX（agent_runner 透传形态）不改变判据：真实 sleep 进程 → False。

    MUST 调用未经 stub 的真实 _is_tmux_hosted：stub 后断言与装配用例同义反复，
    证明不了判据未读 TMUX。
    """
    monkeypatch.setenv("TMUX", "/tmp/tmux-0/default,631314,0")
    victim = subprocess.Popen(["sleep", "30"])
    try:
        assert _is_tmux_hosted(victim.pid) is False
    finally:
        if victim.poll() is None:
            victim.kill()
            victim.wait()


def _wait_proc_state(pid: int, expected_comm: str, timeout: float = 5.0) -> bool:
    """等待 /proc/<pid>/comm 变为期望值（夹具 exec/prctl 完成的就绪信号）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if Path(f"/proc/{pid}/comm").read_text().strip() == expected_comm:
                return True
        except OSError:
            pass
        time.sleep(0.05)
    return False


def test_is_tmux_hosted_with_real_fixture():
    """真实 /proc 路径覆盖（非纯 monkeypatch）：comm 主判据 + argv 回退 + 负例。"""
    # comm 主判据：prctl(PR_SET_NAME) 把 comm 改为 "tmux: server"（exec -a 只改
    # argv[0] 不改 comm，覆盖不到主判据，故必须用 prctl 夹具）
    renamed = subprocess.Popen(
        [
            "python3",
            "-c",
            "import ctypes,time; "
            "ctypes.CDLL('libc.so.6').prctl(15, b'tmux: server', 0, 0, 0);"
            " time.sleep(30)",
        ]
    )
    try:
        assert _wait_proc_state(renamed.pid, "tmux: server"), "夹具未就绪"
        assert _is_tmux_hosted(renamed.pid) is True
    finally:
        if renamed.poll() is None:
            renamed.kill()
            renamed.wait()

    # argv 回退：exec -a 后 comm 仍为 sleep、argv[0] basename 恰为 tmux → True
    argv_tmux = subprocess.Popen(["bash", "-c", "exec -a tmux sleep 30"])
    try:
        assert _wait_proc_state(argv_tmux.pid, "sleep"), "夹具未就绪"
        assert _is_tmux_hosted(argv_tmux.pid) is True
    finally:
        if argv_tmux.poll() is None:
            argv_tmux.kill()
            argv_tmux.wait()

    # 负例：argv[0] basename 含 tmux 子串但非 tmux/tmux: 前缀（自测包装脚本）→ False
    argv_sub = subprocess.Popen(["bash", "-c", "exec -a /tmp/tmux_selftest.sh sleep 30"])
    try:
        assert _wait_proc_state(argv_sub.pid, "sleep"), "夹具未就绪"
        assert _is_tmux_hosted(argv_sub.pid) is False
    finally:
        if argv_sub.poll() is None:
            argv_sub.kill()
            argv_sub.wait()

    # 负例：普通 sleep 进程 → False
    plain = subprocess.Popen(["sleep", "30"])
    try:
        assert _is_tmux_hosted(plain.pid) is False
    finally:
        if plain.poll() is None:
            plain.kill()
            plain.wait()
