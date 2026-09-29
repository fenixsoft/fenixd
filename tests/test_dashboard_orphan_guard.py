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
import signal
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


# ── 端口接管常驻豁免：serve() 接管分支（2026-09-29 事故）────────────────
# 占用者为 tmux 承载的常驻 --serve 实例时不可被接管（杀 pane 进程 → tmux
# 单窗口会话消失、用户可访问实例静默死亡）；非 tmux 旧实例接管语义不变；
# 父进程身份读取失败按非 tmux 承载放行（fail-safe 偏向放行）。

_OCCUPANT_PID = 4242
_OCCUPANT_STARTTIME = 123456


class _FakeHttpd:
    """serve() 成功绑定路径的最小 httpd 替身：serve_forever 立即返回
    （KeyboardInterrupt → except → finally 清理 → serve() 正常返回），
    不落真端口、不起真线程。"""

    def __init__(self, addr, registry, static_dir):
        self.addr = addr
        self.watcher = None
        self.session_manager = None
        self.sse_hub = object()
        self.summary_index = None

    def projects(self):
        return []

    def serve_forever(self):
        raise KeyboardInterrupt()

    def shutdown(self):
        pass

    def server_close(self):
        pass


class _FakeWatcher:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class _FakeSessionManager:
    def __init__(self, hub):
        self.hub = hub

    def shutdown(self):
        pass


def _occupant():
    return {
        "pid": _OCCUPANT_PID,
        "cmdline": "python3 fenix_dashboard.py --serve",
        "starttime": _OCCUPANT_STARTTIME,
    }


def _install_serve_harness(monkeypatch, bind_outcomes, occupant):
    """装配 serve() 接管分支测试夹具，返回 (created_httpd, signals)。

    bind_outcomes 按构造次序消费：OSError 实例 = 该次绑定抛 EADDRINUSE，
    其余为成功返回的 httpd 替身。signals 记录 os.kill 调用 (pid, sig)。
    占用者 starttime 复核恒通过（防 PID 复用分支不在本组用例覆盖面），
    占用者 kill 后视为立即退出（跳过等待轮询）。
    """
    import core.dashboard.server as server_mod

    created = []
    signals = []

    def fake_server_cls(addr, registry, static_dir):
        outcome = bind_outcomes.pop(0)
        if isinstance(outcome, OSError):
            raise outcome
        created.append(outcome)
        return outcome

    monkeypatch.setattr(server_mod, "DashboardHTTPServer", fake_server_cls)
    monkeypatch.setattr(server_mod, "FileWatcher", _FakeWatcher)
    monkeypatch.setattr(
        "core.dashboard.session_manager.SessionManager", _FakeSessionManager
    )
    monkeypatch.setattr(server_mod, "_bind_parent_lifecycle", lambda: None)
    monkeypatch.setattr(server_mod, "_find_dashboard_occupant", lambda port: occupant)
    monkeypatch.setattr(server_mod, "_proc_starttime", lambda pid: _OCCUPANT_STARTTIME)
    monkeypatch.setattr(server_mod, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(server_mod.signal, "signal", lambda *a, **k: None)
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))
    return created, signals


_EADDRINUSE = OSError(98, "Address already in use")


def _write_occupant_stat(tmp_path, ppid):
    """写 fake 占用者 /proc/<pid>/stat：')' 后首字段=state、次字段=ppid。"""
    stat = tmp_path / "stat"
    stat.write_text(f"{_OCCUPANT_PID} (python3) S {ppid} {_OCCUPANT_PID} 1 0\n")
    return stat


def test_takeover_rejected_for_tmux_resident_occupant(monkeypatch, tmp_path, capsys):
    """tmux 常驻占用者：不发任何信号、非 0 退出、错误含 PID 与 --port 指引。"""
    stat = _write_occupant_stat(tmp_path, ppid=777)
    comm = tmp_path / "comm"
    comm.write_text("tmux: server\n")
    _patch_proc_files(
        monkeypatch,
        {f"/proc/{_OCCUPANT_PID}/stat": stat, "/proc/777/comm": comm},
    )
    created, signals = _install_serve_harness(
        monkeypatch, [_EADDRINUSE], _occupant()
    )
    with pytest.raises(SystemExit) as ei:
        import core.dashboard.server as server_mod

        server_mod.serve(None, port=8787)
    assert ei.value.code == 1
    assert signals == []  # 未向占用者发送任何信号（tmux 会话不受影响）
    assert created == []  # 未完成绑定（拒绝启动而非自动换端口）
    err = capsys.readouterr().err
    assert str(_OCCUPANT_PID) in err  # 含占用者 PID
    assert "常驻" in err  # tmux 常驻说明
    assert "--port" in err  # 换端口指引


def test_takeover_proceeds_for_non_tmux_occupant(monkeypatch, tmp_path):
    """非 tmux 旧实例：既有接管语义不变——占用者收 SIGTERM、新实例完成绑定。"""
    stat = _write_occupant_stat(tmp_path, ppid=777)
    comm = tmp_path / "comm"
    comm.write_text("bash\n")  # 父进程非 tmux server
    _patch_proc_files(
        monkeypatch,
        {f"/proc/{_OCCUPANT_PID}/stat": stat, "/proc/777/comm": comm},
    )
    httpd = _FakeHttpd(("127.0.0.1", 8787), None, None)
    created, signals = _install_serve_harness(
        monkeypatch, [_EADDRINUSE, httpd], _occupant()
    )
    import core.dashboard.server as server_mod

    server_mod.serve(None, port=8787)  # 替身 serve_forever 立即返回 → 正常收尾
    assert signals == [(_OCCUPANT_PID, signal.SIGTERM)]
    assert created == [httpd]  # 新实例完成绑定


def test_parent_is_tmux_server_read_failures_return_false(monkeypatch, tmp_path):
    """两层读取失败均 → False：(a) 占用者 stat 不可读；(b) 父进程 comm/cmdline
    均不可读；孤儿化占用者（ppid=1，init 非 tmux）经正常判定亦 False。"""
    import core.dashboard.server as server_mod

    # (a) 占用者 /proc/<pid>/stat 不可读 → ppid 提取失败 → False
    _patch_proc_files(
        monkeypatch, {f"/proc/{_OCCUPANT_PID}/stat": tmp_path / "gone" / "stat"}
    )
    assert server_mod._parent_is_tmux_server(_OCCUPANT_PID) is False

    # (b) stat 可得 ppid=777，但父进程 comm 与 cmdline 均不可读 → False
    stat = _write_occupant_stat(tmp_path, ppid=777)
    _patch_proc_files(
        monkeypatch,
        {
            f"/proc/{_OCCUPANT_PID}/stat": stat,
            "/proc/777/comm": tmp_path / "gone" / "comm",
            "/proc/777/cmdline": tmp_path / "gone" / "cmdline",
        },
    )
    assert server_mod._parent_is_tmux_server(_OCCUPANT_PID) is False

    # 孤儿化占用者：ppid 归 1，init（comm 可读非 tmux、cmdline 回退失败）→ False
    orphan_stat = _write_occupant_stat(tmp_path, ppid=1)
    init_comm = tmp_path / "init_comm"
    init_comm.write_text("init\n")
    _patch_proc_files(
        monkeypatch,
        {
            f"/proc/{_OCCUPANT_PID}/stat": orphan_stat,
            "/proc/1/comm": init_comm,
            "/proc/1/cmdline": tmp_path / "gone" / "cmdline",
        },
    )
    assert server_mod._parent_is_tmux_server(_OCCUPANT_PID) is False


def test_parent_is_tmux_server_walks_ancestor_chain(monkeypatch, tmp_path):
    """真实 tmux pane 交互形态：占用者父是 pane shell（bash/zsh），祖父才是
    tmux server——须沿祖先链上溯判定。只查一层会把 pane shell 的 comm
    （zsh/bash）当判定对象、豁免永不命中、SIGTERM 照发（2026-09-30 真实
    环境场景验证实证）。链上祖先 stat 不可读 → False（放行既有接管）。"""
    import core.dashboard.server as server_mod

    occupant_stat = _write_occupant_stat(tmp_path, ppid=2001)
    shell_stat = tmp_path / "shell_stat"
    # pane shell 2001 → tmux server 7541（pid 字段对解析无影响，只取 ppid）
    shell_stat.write_text("2001 (zsh) S 7541 2001 1 0\n")
    tmux_comm = tmp_path / "tmux_comm"
    tmux_comm.write_text("tmux: server\n")
    _patch_proc_files(
        monkeypatch,
        {
            f"/proc/{_OCCUPANT_PID}/stat": occupant_stat,
            "/proc/2001/stat": shell_stat,
            "/proc/7541/comm": tmux_comm,
        },
    )
    assert server_mod._parent_is_tmux_server(_OCCUPANT_PID) is True

    # 祖先链断裂：pane shell 已退出（stat 不可读）→ False，放行既有接管
    _patch_proc_files(
        monkeypatch, {f"/proc/{_OCCUPANT_PID}/stat": occupant_stat}
    )
    assert server_mod._parent_is_tmux_server(_OCCUPANT_PID) is False


def test_takeover_rejected_for_tmux_pane_shell_occupant(monkeypatch, tmp_path, capsys):
    """pane 交互 shell 形态的 tmux 常驻（父=pane shell、祖父=tmux server）：
    豁免同样命中——不发任何信号、非 0 退出、错误含 PID 与 --port 指引。"""
    occupant_stat = _write_occupant_stat(tmp_path, ppid=2001)
    shell_stat = tmp_path / "shell_stat"
    shell_stat.write_text("2001 (zsh) S 7541 2001 1 0\n")
    tmux_comm = tmp_path / "tmux_comm"
    tmux_comm.write_text("tmux: server\n")
    _patch_proc_files(
        monkeypatch,
        {
            f"/proc/{_OCCUPANT_PID}/stat": occupant_stat,
            "/proc/2001/stat": shell_stat,
            "/proc/7541/comm": tmux_comm,
        },
    )
    created, signals = _install_serve_harness(
        monkeypatch, [_EADDRINUSE], _occupant()
    )
    with pytest.raises(SystemExit) as ei:
        import core.dashboard.server as server_mod

        server_mod.serve(None, port=8787)
    assert ei.value.code == 1
    assert signals == []  # pane 交互形态的常驻实例同样不受信号
    assert created == []
    err = capsys.readouterr().err
    assert str(_OCCUPANT_PID) in err
    assert "常驻" in err
    assert "--port" in err


def test_takeover_proceeds_when_parent_identity_unreadable(monkeypatch, tmp_path):
    """父进程身份读取失败（两层）→ 按非 tmux 承载走既有接管，不产生新报错分支。"""
    import core.dashboard.server as server_mod

    occupant = _occupant()

    # (a) 占用者 stat 不可读（ppid 提取失败）→ 放行接管
    _patch_proc_files(
        monkeypatch, {f"/proc/{_OCCUPANT_PID}/stat": tmp_path / "gone" / "stat"}
    )
    httpd_a = _FakeHttpd(("127.0.0.1", 8787), None, None)
    created_a, signals_a = _install_serve_harness(
        monkeypatch, [_EADDRINUSE, httpd_a], occupant
    )
    server_mod.serve(None, port=8787)
    assert signals_a == [(_OCCUPANT_PID, signal.SIGTERM)]
    assert created_a == [httpd_a]

    # (b) ppid 可得但父进程 comm/cmdline 均不可读 → 亦放行接管
    stat = _write_occupant_stat(tmp_path, ppid=777)
    _patch_proc_files(
        monkeypatch,
        {
            f"/proc/{_OCCUPANT_PID}/stat": stat,
            "/proc/777/comm": tmp_path / "gone" / "comm",
            "/proc/777/cmdline": tmp_path / "gone" / "cmdline",
        },
    )
    httpd_b = _FakeHttpd(("127.0.0.1", 8787), None, None)
    created_b, signals_b = _install_serve_harness(
        monkeypatch, [_EADDRINUSE, httpd_b], occupant
    )
    server_mod.serve(None, port=8787)
    assert signals_b == [(_OCCUPANT_PID, signal.SIGTERM)]
    assert created_b == [httpd_b]
