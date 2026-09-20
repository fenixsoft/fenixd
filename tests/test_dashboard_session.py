"""
Tests for dashboard live session (add-dashboard-live-session).

覆盖：
- SessionManager 单元测试：复用语义、空文本拒绝、不存在会话 send 抛错、
  stop 幂等、shutdown 终止全部
- 假进程注入：stdout 读线程 JSON 行转事件、脏行转 stderr、EOF 转
  session_ended(process_exit)、hook 噪音过滤、hub.broadcast 收到消息
- 路由层：GET /api/session 无会话/有会话、POST /api/session/send 400/404/200、
  POST/DELETE /api/session/watch 调 hub.watch/unwatch
- 真实进程集成测试（无 claude CLI 时 skip）：两轮输入均产生 assistant 事件
"""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer
from core.dashboard.registry import Registry
from core.dashboard.session_manager import (
    SESSION_EVENT_BUFFER,
    SESSION_TERMINATE_GRACE_SECONDS,
    SessionManager,
    SessionNotFoundError,
    SessionNotRunningError,
)
from core.dashboard import server as server_mod


# ── 假进程：可注入的 Popen 替身 ──────────────────────────────────────────

class FakePipe:
    """可写的假 stdin / 可迭代的假 stdout/stderr。

    eof=False（默认）：迭代产出 lines 后阻塞等待，模拟存活进程未 EOF；
    eof=True：产出 lines 后正常结束（进程退出语义）。
    """

    def __init__(self, name, lines=None, eof=False):
        self.name = name
        self.lines = lines or []  # 假 stdout/stderr 逐行内容
        self.written = []         # 假 stdin 收到的行
        self.closed = False
        self.eof = eof
        # eof=False 时迭代需「阻塞等待」模拟存活进程未 EOF。**必须用 Event 阻塞，
        # 不可 busy-wait**：reader 线程（session_manager._start_reader_threads，
        # daemon=True）会一直迭代本 pipe；旧实现 ``while not eof: time.sleep(0.05)``
        # 令线程存活期内每 0.05s 醒一次抢 GIL，且 kill() 不置 eof → 线程永不退出、
        # 跨测试累积，持续拖慢其后所有用例（实测 test_dashboard_session 之后的
        # test_dispatch_aging 0.05s→11.2s，×200）。Event.wait() 阻塞不占 GIL，
        # 与真实管道 read() 的阻塞语义一致。
        self._eof_event = threading.Event()
        if eof:
            self._eof_event.set()

    # stdout/stderr 迭代器语义：逐行产出后按 eof 决定是否阻塞
    def __iter__(self):
        for line in self.lines:
            yield line
        self._eof_event.wait()

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True
        self.eof = True
        self._eof_event.set()


class FakeProc:
    """FakeProc：模拟 subprocess.Popen 的最小对象。"""

    def __init__(
        self,
        stdout_lines=None,
        stderr_lines=None,
        exit_code=None,
        stdout_eof=False,
        stderr_eof=False,
    ):
        self.stdin = FakePipe("stdin")
        self.stdout = FakePipe("stdout", stdout_lines or [], eof=stdout_eof)
        self.stderr = FakePipe("stderr", stderr_lines or [], eof=stderr_eof)
        self._exit_code = exit_code
        self.pid = 4242
        self.killed = False

    def poll(self):
        if self._exit_code is not None:
            return self._exit_code
        return None

    def wait(self, timeout=None):
        if self._exit_code is None:
            self._exit_code = 0
        return self._exit_code

    def kill(self):
        self.killed = True
        if self._exit_code is None:
            self._exit_code = 9
        # 真实 Popen.kill() 关闭管道 → reader 迭代结束。置 read pipe 为 EOF
        # 才能让读线程退出（否则 Event.wait() 永久阻塞、线程跨测试泄漏——
        # 旧实现 busy-wait 同因 kill 不置 eof 而泄漏，本处一并堵死）。
        self.stdout.close()
        self.stderr.close()


class FakeHub:
    """SSEHub 替身：记录 broadcast / watch / unwatch 调用。"""

    def __init__(self):
        self.broadcasts = []      # (event, run_id)
        self.watch_calls = []     # (cid, run_id)
        self.unwatch_calls = []   # (cid, run_id)

    def broadcast(self, event, run_id=None):
        self.broadcasts.append((event, run_id))

    def watch(self, cid, run_id):
        self.watch_calls.append((cid, run_id))

    def unwatch(self, cid, run_id):
        self.unwatch_calls.append((cid, run_id))


@pytest.fixture()
def manager_fx(monkeypatch):
    """SessionManager + 默认假进程工厂。"""
    hub = FakeHub()
    mgr = SessionManager(hub)
    mgr._idle_stop.set()  # 停空闲扫描线程，避免测试干扰
    yield mgr, hub
    mgr.shutdown()


# ── 1.1 单元测试：SessionManager ─────────────────────────────────────────

class TestSessionManagerUnit:
    def test_reuse_same_handle(self, manager_fx, monkeypatch):
        """复用语义：同项目二次 start 返回同一句柄。"""
        mgr, hub = manager_fx
        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen",
            lambda *a, **kw: FakeProc(),
        )
        s1 = mgr.start("proj-a", "/tmp/proj-a")
        s2 = mgr.start("proj-a", "/tmp/proj-a")
        assert s1 is s2
        assert s1.session_id == s2.session_id

    def test_start_spawns_with_replay_and_no_agent_env(self, manager_fx, monkeypatch):
        """1.10/1.11：命令行含 --replay-user-messages，env 无 agent-run 键。"""
        mgr, hub = manager_fx
        captured = {}

        def fake_popen(cmd, **kw):
            captured["cmd"] = cmd
            captured["env"] = kw.get("env")
            captured["cwd"] = kw.get("cwd")
            return FakeProc()

        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen", fake_popen
        )
        # 预置 agent-run 专用 env 键，确认会被清除
        monkeypatch.setenv("FENIX_RUN_WORKTREE", "/tmp/wt")
        monkeypatch.setenv("FENIX_RUN_PROJECT_ROOT", "/tmp/proot")
        monkeypatch.setenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", "1")

        mgr.start("proj-a", "/tmp/proj-a")

        assert "--replay-user-messages" in captured["cmd"]
        assert "--settings" not in captured["cmd"]
        assert "--add-dir" not in captured["cmd"]
        assert "FENIX_RUN_WORKTREE" not in captured["env"]
        assert "FENIX_RUN_PROJECT_ROOT" not in captured["env"]
        assert "CLAUDE_CODE_ENABLE_TODO_TOOLS" not in captured["env"]
        # cwd 是项目路径
        assert captured["cwd"] == "/tmp/proj-a"

    def test_send_blank_rejected(self, manager_fx, monkeypatch):
        """空文本 send 抛错。"""
        mgr, hub = manager_fx
        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen",
            lambda *a, **kw: FakeProc(),
        )
        s = mgr.start("proj-a", "/tmp/proj-a")
        with pytest.raises(Exception):
            mgr.send(s.session_id, "   ")

    def test_send_unknown_session_raises(self, manager_fx, monkeypatch):
        """不存在会话 send 抛 SessionNotFoundError。"""
        mgr, hub = manager_fx
        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen",
            lambda *a, **kw: FakeProc(),
        )
        with pytest.raises(SessionNotFoundError):
            mgr.send("nope", "hello")

    def test_send_writes_json_line_to_stdin(self, manager_fx, monkeypatch):
        """send 写入单行 JSON（ensure_ascii=False 保留中文）。"""
        mgr, hub = manager_fx
        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen",
            lambda *a, **kw: FakeProc(),
        )
        s = mgr.start("proj-a", "/tmp/proj-a")
        mgr.send(s.session_id, "你好，世界")
        assert s.proc.stdin.written, "stdin 应有写入"
        payload = json.loads(s.proc.stdin.written[0])
        assert payload["type"] == "user"
        assert payload["message"]["content"][0]["text"] == "你好，世界"

    def test_stop_idempotent(self, manager_fx, monkeypatch):
        """stop 幂等：重复调用 no-op。"""
        mgr, hub = manager_fx
        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen",
            lambda *a, **kw: FakeProc(),
        )
        s = mgr.start("proj-a", "/tmp/proj-a")
        mgr.stop(s.session_id, "user")
        mgr.stop(s.session_id, "user")  # 第二次应为 no-op
        # 终止后会话已移除
        assert mgr.get("proj-a") is None

    def test_shutdown_terminates_all(self, manager_fx, monkeypatch):
        """shutdown 终止全部会话且幂等。"""
        mgr, hub = manager_fx
        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen",
            lambda *a, **kw: FakeProc(),
        )
        mgr.start("proj-a", "/tmp/proj-a")
        mgr.start("proj-b", "/tmp/proj-b")
        mgr.shutdown()
        assert mgr.get("proj-a") is None
        assert mgr.get("proj-b") is None
        # 幂等
        mgr.shutdown()

    def test_start_after_process_exit_creates_new(self, manager_fx, monkeypatch):
        """进程已退出后再次 start 应创建新会话（不复用僵尸）。"""
        mgr, hub = manager_fx
        proc = FakeProc(exit_code=1)
        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen",
            lambda *a, **kw: proc,
        )
        s1 = mgr.start("proj-a", "/tmp/proj-a")
        s2 = mgr.start("proj-a", "/tmp/proj-a")
        assert s1 is not s2  # 旧进程已退出 → 新会话


# ── 1.2 假进程读线程测试 ────────────────────────────────────────────────

class TestReaderThreads:
    def _mk(self, manager_fx, monkeypatch, stdout_lines, stderr_lines=None, stdout_eof=True):
        mgr, hub = manager_fx
        proc = FakeProc(
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines or [],
            stdout_eof=stdout_eof,
        )
        monkeypatch.setattr(
            "core.dashboard.session_manager.subprocess.Popen",
            lambda *a, **kw: proc,
        )
        s = mgr.start("proj-a", "/tmp/proj-a")
        return mgr, hub, s, proc

    def _wait_reader(self, mgr, s, timeout=5.0):
        """等待 stdout 读线程把事件消化完（轮询 hub 广播中的 session_ended）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for event, _run_id in mgr._hub.broadcasts:
                if event.get("type") == "session_events":
                    for ev in event.get("events", []):
                        if ev.get("type") == "session_ended":
                            return True
            time.sleep(0.02)
        return False

    def _events_from_broadcasts(self, hub):
        """收集所有 session_events 广播中的事件列表。"""
        out = []
        for event, _run_id in hub.broadcasts:
            if event.get("type") == "session_events":
                out.extend(event.get("events", []))
        return out

    def test_json_line_to_event_and_broadcast(self, manager_fx, monkeypatch):
        """JSON 行转事件并广播 session_events。"""
        mgr, hub, s, proc = self._mk(
            manager_fx,
            monkeypatch,
            stdout_lines=['{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}'],
            stdout_eof=True,
        )
        # 等 stdout 线程跑完
        self._wait_reader(mgr, s)
        # hub 应收到事件广播
        events = self._events_from_broadcasts(hub)
        assert events, "应有 session_events 广播"
        assert any(ev["type"] == "assistant" for ev in events)
        # 事件带 ts
        ev = events[0]
        assert "ts" in ev

    def test_hook_noise_filtered(self, manager_fx, monkeypatch):
        """hook_ 前缀的 system 事件被丢弃（1.9），system/init 保留。"""
        mgr, hub, s, proc = self._mk(
            manager_fx,
            monkeypatch,
            stdout_lines=[
                '{"type":"system","subtype":"hook_started","uuid":"h1"}',
                '{"type":"system","subtype":"hook_response","uuid":"h2"}',
                '{"type":"system","subtype":"init","uuid":"h3"}',
                '{"type":"assistant","message":{"content":[{"type":"text","text":"ok"}]}}',
            ],
            stdout_eof=True,
        )
        self._wait_reader(mgr, s)
        events = self._events_from_broadcasts(hub)
        # hook_* 噪音被过滤，system/init 保留，assistant 保留
        subtypes = [ev.get("subtype", "") for ev in events if ev["type"] == "system"]
        assert "init" in subtypes
        assert not any(
            sub.startswith("hook_") for sub in subtypes
        ), f"hook 噪音应被过滤: {subtypes}"
        assert any(ev["type"] == "assistant" for ev in events)

    def test_dirty_line_to_stderr_event(self, manager_fx, monkeypatch):
        """非 JSON 脏行转 stderr 兜底事件。"""
        mgr, hub, s, proc = self._mk(
            manager_fx,
            monkeypatch,
            stdout_lines=["NOT A JSON LINE"],
            stdout_eof=True,
        )
        self._wait_reader(mgr, s)
        events = self._events_from_broadcasts(hub)
        assert any(ev["type"] == "stderr" and ev.get("line") == "NOT A JSON LINE" for ev in events)

    def test_eof_to_session_ended(self, manager_fx, monkeypatch):
        """EOF 追加 session_ended(process_exit) 并从登记移除。"""
        mgr, hub, s, proc = self._mk(
            manager_fx,
            monkeypatch,
            stdout_lines=['{"type":"assistant","message":{"content":[{"type":"text","text":"x"}]}}'],
            stdout_eof=True,
        )
        assert self._wait_reader(mgr, s)
        events = self._events_from_broadcasts(hub)
        reasons = [
            ev["reason"]
            for ev in events
            if ev.get("type") == "session_ended"
        ]
        assert "process_exit" in reasons
        # 登记移除
        assert mgr.get("proj-a") is None

    def test_stderr_tail_bounded(self, manager_fx, monkeypatch):
        """stderr 进 stderr_tail 环形缓冲（上限 200 行）。"""
        mgr, hub, s, proc = self._mk(
            manager_fx,
            monkeypatch,
            stdout_lines=[],
            stderr_lines=[f"err-{i}" for i in range(210)],
        )
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if len(s.stderr_tail) >= 200:
                break
            time.sleep(0.02)
        assert len(s.stderr_tail) == 200
        assert s.stderr_tail[0] == "err-10"  # 最旧 10 行被丢弃
        assert s.stderr_tail[-1] == "err-209"


# ── 1.3 路由层测试 ──────────────────────────────────────────────────────

@pytest.fixture()
def session_server_fx(tmp_path, monkeypatch):
    """启动真实 _TestServer，挂上 SessionManager（假进程驱动）。"""
    proot = tmp_path / "proj-a"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    reg = Registry(config_path=tmp_path / "dashboard.yaml")
    reg.save(
        {
            "port": 8787,
            "projects": [{"name": "proj-a", "path": str(proot)}],
            "scan_dirs": [str(tmp_path / "scan-empty")],
        }
    )
    from core.dashboard.http_server import DashboardHTTPServer
    from core.dashboard import server as server_mod

    srv = _TestServer(reg, server_mod.STATIC_DIR)
    from core.dashboard.session_manager import SessionManager

    # 用假进程替换真实 Popen
    monkeypatch.setattr(
        "core.dashboard.session_manager.subprocess.Popen",
        lambda *a, **kw: FakeProc(stdout_lines=[]),
    )
    mgr = SessionManager(srv.httpd.sse_hub)
    srv.httpd.session_manager = mgr
    yield proot, srv, mgr
    mgr.shutdown()
    srv.stop()


class TestSessionRoutes:
    def test_get_session_no_session(self, session_server_fx):
        """GET /api/session 无会话 → session: null + events: []（只读）。"""
        proot, srv, mgr = session_server_fx
        status, data = srv.get("/api/session?project=proj-a")
        assert status == 200
        assert data["session"] is None
        assert data["events"] == []
        assert data["truncated"] is False
        # MUST NOT 触发创建
        assert mgr.get("proj-a") is None

    def test_get_session_after_start(self, session_server_fx):
        """有会话时回读缓冲 + truncated 标记。"""
        proot, srv, mgr = session_server_fx
        s = mgr.start("proj-a", str(proot))
        s.events.append({"type": "assistant", "content": "hi", "ts": time.time()})
        status, data = srv.get("/api/session?project=proj-a")
        assert status == 200
        assert data["session"]["id"] == s.session_id
        assert len(data["events"]) == 1
        assert data["events"][0]["type"] == "assistant"
        assert data["truncated"] is False

    def test_get_session_unknown_project(self, session_server_fx):
        """项目不存在 → 4xx。"""
        proot, srv, mgr = session_server_fx
        status, _ = srv.get("/api/session?project=no-such")
        assert status == 404

    def test_send_blank_400(self, session_server_fx):
        """send 空白 → 400。"""
        proot, srv, mgr = session_server_fx
        mgr.start("proj-a", str(proot))
        status, data = srv.post_json("/api/session/send?project=proj-a", {"text": "  "})
        assert status == 400

    def test_send_no_session_404(self, session_server_fx):
        """send 无会话 → 404。"""
        proot, srv, mgr = session_server_fx
        status, data = srv.post_json("/api/session/send?project=proj-a", {"text": "hi"})
        assert status == 404

    def test_send_ok(self, session_server_fx):
        """send 成功 → 200 ok:true，且写入 stdin。"""
        proot, srv, mgr = session_server_fx
        s = mgr.start("proj-a", str(proot))
        status, data = srv.post_json("/api/session/send?project=proj-a", {"text": "hello"})
        assert status == 200
        assert data["ok"] is True
        assert s.proc.stdin.written, "stdin 应有写入"

    def test_stop_idempotent_200(self, session_server_fx):
        """stop 无会话也 200。"""
        proot, srv, mgr = session_server_fx
        status, data = srv.post("/api/session/stop?project=proj-a")
        assert status == 200
        assert data["ok"] is True

    def test_stop_after_start(self, session_server_fx):
        """stop 终止会话。"""
        proot, srv, mgr = session_server_fx
        s = mgr.start("proj-a", str(proot))
        status, data = srv.post("/api/session/stop?project=proj-a")
        assert status == 200
        assert mgr.get("proj-a") is None

    def test_watch_post_delete(self, session_server_fx):
        """POST/DELETE /api/session/watch 调 hub.watch/unwatch。"""
        proot, srv, mgr = session_server_fx
        s = mgr.start("proj-a", str(proot))
        hub = srv.httpd.sse_hub
        # 注册一个 SSE 连接（cid 须存在于 hub._conns，否则 watch 静默失效）
        conn = hub.register()
        assert conn is not None
        status, data = srv.post(f"/api/session/watch?project=proj-a&cid={conn.id}")
        assert status == 200
        assert s.session_id in hub._conns[conn.id].watched_runs

        status, data = srv.delete(f"/api/session/watch?project=proj-a&cid={conn.id}")
        assert status == 200
        assert s.session_id not in hub._conns[conn.id].watched_runs


# ── 1.4 真实进程集成测试（无 claude CLI 时 skip） ───────────────────────

CLAUDE_BIN = "claude"


def _claude_available() -> bool:
    import shutil

    return shutil.which(CLAUDE_BIN) is not None


@pytest.mark.skipif(not _claude_available(), reason="环境无 claude CLI")
class TestRealProcessIntegration:
    def test_two_rounds_assistant_events(self, tmp_path):
        """真实进程：连发两轮，两轮均产生 assistant 事件（含 isReplay user 回显）。"""
        from core.dashboard.session_manager import SessionManager
        from core.dashboard.sse import SSEHub

        hub = SSEHub()
        mgr = SessionManager(hub)
        try:
            s = mgr.start("proj-a", str(tmp_path))
            # 分开发送并间隔：让 CLI 有时间启动并处理第一轮，
            # 避免并发环境（全量套件）下资源竞争导致第二轮回显超时。
            mgr.send(s.session_id, "回复：一")
            time.sleep(1.0)
            mgr.send(s.session_id, "回复：二")

            # 轮询等待：两轮 assistant + 两条 isReplay user 回显（最长 180s）
            deadline = time.time() + 180
            assistant_seen = 0
            replay_seen = 0
            while time.time() < deadline:
                assistant_seen = sum(
                    1 for ev in s.events if ev.get("type") == "assistant"
                )
                replay_seen = sum(
                    1 for ev in s.events
                    if ev.get("type") == "user" and ev.get("isReplay")
                )
                if assistant_seen >= 2 and replay_seen >= 2:
                    break
                time.sleep(1.0)

            assert assistant_seen >= 2, f"两轮均须有 assistant 事件（当前 {assistant_seen}）"

            # 1.10：回显 user 事件（isReplay）应出现在缓冲
            assert replay_seen >= 2, (
                f"--replay-user-messages 应回显两轮用户输入（当前 {replay_seen}）"
            )
        finally:
            mgr.shutdown()
