"""session_manager.py — 项目级自由会话进程管理器（dashboard-live-session D1/D2/D5）。

管理每项目至多一个 claude 子进程，stdin 写入、stdout/stderr 读线程、
事件缓冲与空闲回收。纯标准库，与 dashboard 进程同生命周期。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("fenixd.dashboard.session_manager")

# ── 模块常量 ────────────────────────────────────────────────────────────────
# D5 / design：不新增受管配置键，与 fix-verify-serving-disk-reclaim
# 的 RECLAIM_GRACE_SECONDS = 600 同款处置。

SESSION_EVENT_BUFFER = 4000          # 事件环形缓冲上限
SESSION_IDLE_TIMEOUT_SECONDS = 1800  # 空闲回收阈值（30 分钟）
SESSION_TERMINATE_GRACE_SECONDS = 5  # 终止宽限：关 stdin 后等该秒数再 kill


class SessionError(Exception):
    """会话操作错误基类。"""


class SessionNotFoundError(SessionError):
    """会话不存在。"""


class SessionNotRunningError(SessionError):
    """会话进程已退出。"""


@dataclass
class Session:
    """单个会话实例状态。"""

    project: str          # 项目别名（registry 的 name）
    project_path: Path
    proc: subprocess.Popen
    session_id: str       # 本地生成，仅作 SSE 订阅键与前端句柄
    events: deque = field(default_factory=lambda: deque(maxlen=SESSION_EVENT_BUFFER))
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_activity: float = field(default_factory=time.time)
    stderr_tail: deque = field(default_factory=lambda: deque(maxlen=200))
    terminating: bool = False  # _terminate 已认领，防并发双终态


class SessionManager:
    """会话管理器：维护项目→会话映射，提供 start/send/stop/shutdown。

    绑定 SSEHub 用于增量广播。
    """

    def __init__(self, hub):
        from .sse import SSEHub
        self._hub: SSEHub = hub
        self._sessions: dict[str, Session] = {}  # project_name → Session
        self._lock = threading.Lock()
        self._idle_thread: threading.Thread | None = None
        self._idle_stop = threading.Event()
        self._start_idle_thread()

    # ── D1.11：必须不出现的 env 键 ────────────────────────────────────────
    # 自由会话 MUST NOT 注入 agent-run 专用上下文，防回归。
    _BANNED_ENV_KEYS = frozenset({
        "FENIX_RUN_PROJECT_ROOT",
        "FENIX_RUN_WORKTREE",
        "CLAUDE_CODE_ENABLE_TODO_TOOLS",
    })

    def _build_cmd(self) -> list[str]:
        """构建 claude 子进程命令行。

        D1 / D1.10：必须含 --replay-user-messages（回显用户输入）。
        D1.11：MUST NOT 含 --settings / --add-dir（agent-run 专用上下文）。
        """
        return [
            "claude",
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", "bypassPermissions",
            "--replay-user-messages",
        ]

    def _build_env(self) -> dict[str, str]:
        """构建子进程环境：os.environ.copy() 减 agent-run 专用键（D1.11）。"""
        env = os.environ.copy()
        for key in self._BANNED_ENV_KEYS:
            env.pop(key, None)
        return env

    def start(self, project_name: str, project_path: str | Path) -> Session:
        """创建（或复用存活）会话并返回 Session。

        这是唯一允许启动会话进程的入口（2.1 约定）。
        """
        project_path = Path(project_path)
        with self._lock:
            existing = self._sessions.get(project_name)
            if existing is not None:
                if existing.proc.poll() is None:
                    # 进程存活，复用
                    existing.last_activity = time.time()
                    return existing
                # 进程已退出，清理后重建
                self._remove_session_nolock(project_name)

            cmd = self._build_cmd()
            env = self._build_env()
            session_id = uuid.uuid4().hex

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(project_path),
                env=env,
            )

            session = Session(
                project=project_name,
                project_path=project_path,
                proc=proc,
                session_id=session_id,
            )
            self._sessions[project_name] = session

        # 启动读线程（session._lock 保护 stdin/events，manager._lock 不持有）
        self._start_reader_threads(session)
        logger.info(
            "session started: project=%s session_id=%s pid=%d",
            project_name,
            session_id,
            proc.pid,
        )
        return session

    def get(self, project_name: str) -> Session | None:
        """获取存活会话（进程已退出则清理并返回 None）。"""
        with self._lock:
            session = self._sessions.get(project_name)
            if session is not None and session.proc.poll() is not None:
                self._remove_session_nolock(project_name)
                return None
            return session

    def send(self, session_id: str, text: str) -> None:
        """向会话发送用户文本（一轮）。

        session_id 作为不透明句柄；内部按 session_id 反查。
        """
        if not text or not text.strip():
            raise SessionError("text is empty")
        with self._lock:
            session = self._find_by_id(session_id)
            if session is None:
                raise SessionNotFoundError(f"session not found: {session_id}")
            if session.proc.poll() is not None:
                self._remove_session_nolock(session.project)
                raise SessionNotRunningError("session process has exited")

        payload = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        }
        with session.lock:
            if session.proc.poll() is not None:
                raise SessionNotRunningError("session process has exited")
            try:
                session.proc.stdin.write(
                    json.dumps(payload, ensure_ascii=False) + "\n"
                )
                session.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise SessionNotRunningError(f"stdin write failed: {exc}") from exc
            session.last_activity = time.time()

    def stop(self, session_id: str, reason: str = "user") -> None:
        """终止指定会话（幂等）。

        reason：user / idle / shutdown / process_exit
        """
        with self._lock:
            session = self._find_by_id(session_id)
            if session is None:
                return  # 幂等
        self._terminate(session, reason)

    def shutdown(self) -> None:
        """终止全部会话并停空闲回收线程。幂等。"""
        self._idle_stop.set()
        with self._lock:
            sessions = list(self._sessions.values())
        for s in sessions:
            self._terminate(s, "shutdown")

    # ── 内部：空闲回收 ─────────────────────────────────────────────────────

    def _start_idle_thread(self) -> None:
        def _loop():
            while not self._idle_stop.is_set():
                self._idle_stop.wait(timeout=min(60, SESSION_IDLE_TIMEOUT_SECONDS // 6))
                if self._idle_stop.is_set():
                    break
                try:
                    self._scan_idle()
                except Exception:
                    logger.exception("idle scan error")

        self._idle_thread = threading.Thread(
            target=_loop, daemon=True, name="session-idle-scan"
        )
        self._idle_thread.start()

    def _scan_idle(self) -> None:
        now = time.time()
        with self._lock:
            candidates = [
                s for s in self._sessions.values()
                if s.proc.poll() is None
                and (now - s.last_activity) > SESSION_IDLE_TIMEOUT_SECONDS
            ]
        for s in candidates:
            self._terminate(s, "idle")

    # ── 内部：进程终止 ─────────────────────────────────────────────────────

    def _terminate(self, session: Session, reason: str) -> None:
        """关 stdin → 等宽限 → kill → 广播 session_ended → 移除。"""
        # 幂等守卫（与 _stdout_reader 的 still_registered 同式）：并发 stop/idle/
        # shutdown 或会话已被替换/移除时，只允许一个线程走完整终止流程，
        # 避免同会话广播两条 session_ended 终态事件。短临界区，锁内不做等待/广播。
        with self._lock:
            if session.terminating or self._sessions.get(session.project) is not session:
                return  # 已被其他路径认领或移除
            session.terminating = True

        sid = session.session_id
        pid = session.proc.pid

        # 关 stdin（触发 claude 退出）
        try:
            with session.lock:
                if session.proc.stdin and not session.proc.stdin.closed:
                    session.proc.stdin.close()
        except Exception:
            pass

        # 等待宽限
        try:
            session.proc.wait(timeout=SESSION_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                session.proc.kill()
            except Exception:
                pass
            try:
                session.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

        # 追加并广播 session_ended
        event = {
            "type": "session_ended",
            "session_id": sid,
            "reason": reason,
            "ts": time.time(),
        }
        session.events.append(event)
        self._hub.broadcast(
            {"type": "session_events", "session_id": sid, "events": [event]},
            run_id=sid,
        )

        with self._lock:
            self._remove_session_nolock(session.project)

        logger.info(
            "session terminated: project=%s session_id=%s pid=%d reason=%s",
            session.project,
            sid,
            pid,
            reason,
        )

    def _remove_session_nolock(self, project_name: str) -> None:
        """从映射移除会话（caller 已持有 self._lock）。"""
        self._sessions.pop(project_name, None)

    def _find_by_id(self, session_id: str) -> Session | None:
        """按 session_id 查找（caller 已持有 self._lock）。"""
        for s in self._sessions.values():
            if s.session_id == session_id:
                return s
        return None

    # ── 内部：读线程 ───────────────────────────────────────────────────────

    def _start_reader_threads(self, session: Session) -> None:
        """启动 stdout/stderr 读线程。"""
        threading.Thread(
            target=self._stdout_reader,
            args=(session,),
            daemon=True,
            name=f"session-stdout-{session.session_id[:8]}",
        ).start()
        threading.Thread(
            target=self._stderr_reader,
            args=(session,),
            daemon=True,
            name=f"session-stderr-{session.session_id[:8]}",
        ).start()

    def _stdout_reader(self, session: Session) -> None:
        """逐行读 stdout：JSON 行解析为事件并广播；脏行进 stderr 兜底。"""
        sid = session.session_id
        try:
            for line in session.proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                # 尝试 JSON 解析
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    # 非 JSON 行 → stderr 兜底事件（进缓冲 + 广播，前端实时可见）
                    ev = {"type": "stderr", "line": line, "ts": time.time()}
                    session.events.append(ev)
                    self._hub.broadcast(
                        {"type": "session_events", "session_id": sid, "events": [ev]},
                        run_id=sid,
                    )
                    continue

                # D1.1 hook 噪音过滤：丢弃 system/hook_* 事件
                ev_type = ev.get("type", "")
                ev_subtype = ev.get("subtype", "")
                if ev_type == "system" and isinstance(ev_subtype, str) and ev_subtype.startswith("hook_"):
                    continue

                # 补 ts 字段
                if "ts" not in ev:
                    ev["ts"] = time.time()

                session.events.append(ev)
                session.last_activity = time.time()

                # 广播
                self._hub.broadcast(
                    {"type": "session_events", "session_id": sid, "events": [ev]},
                    run_id=sid,
                )
        except Exception:
            logger.exception("stdout reader error: session=%s", sid)
        finally:
            # EOF → 进程退出，追加 session_ended 并移除。
            # 若已被 _terminate（user/idle/shutdown）先行移除则不再重复广播
            # （避免同会话出现两条终态事件）。
            with self._lock:
                still_registered = self._sessions.get(session.project) is session
                if still_registered:
                    self._remove_session_nolock(session.project)
            if still_registered:
                end_event = {
                    "type": "session_ended",
                    "session_id": sid,
                    "reason": "process_exit",
                    "ts": time.time(),
                }
                session.events.append(end_event)
                self._hub.broadcast(
                    {"type": "session_events", "session_id": sid, "events": [end_event]},
                    run_id=sid,
                )
                logger.info("stdout EOF: session=%s reason=process_exit", sid)

    def _stderr_reader(self, session: Session) -> None:
        """逐行读 stderr 进 stderr_tail 环形缓冲，不广播。"""
        try:
            for line in session.proc.stderr:
                line = line.rstrip("\n")
                if line:
                    session.stderr_tail.append(line)
        except Exception:
            pass
