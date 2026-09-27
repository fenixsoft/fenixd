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

from core.agent_env_keys import AGENT_RUN_BANNED_ENV_KEYS

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
    # add-session-composer 1.1：stdout init 事件缓存的补全数据源（commands 端点
    # 读取）。随 Session 生命周期存亡：进程退出会话被移除即缓存消亡；会话重建
    # 后由新 init 事件覆盖。读线程写、HTTP 线程读，单次赋值原子。
    slash_commands: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


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
    # 自由会话 MUST NOT 注入 agent-run 专用上下文，防回归。键集单一来源见
    # core/agent_env_keys.py（与 core.knowledge、architecture_routes 共用）。
    _BANNED_ENV_KEYS = AGENT_RUN_BANNED_ENV_KEYS

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
                # code-review item 6f1f51a385a0：_terminate 认领后（关 stdin →
                # 等宽限窗 → kill）进程在窗内仍存活，仅凭 poll() 判活会把即将
                # 被 kill 的会话当可用会话复用，调用方随后的 send 大概率
                # SessionNotRunningError——与 send/stop 的幂等语义对齐，已认领
                # 终止的会话按已退出处理，走下方清理重建路径。
                if existing.proc.poll() is None and not existing.terminating:
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
            # ValueError 归入同一语义（code-review item e3ad6cee4723）：
            # _terminate 关 stdin 后的宽限窗内进程仍存活，两道 poll 检查均可
            # 通过，写已关闭文件抛 ValueError 而非 BrokenPipeError/OSError。
            except (BrokenPipeError, OSError, ValueError) as exc:
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
            # code-review item 6f1f51a385a0：start 复用分支把 terminating 会话
            # 按已退出清理重建后，宽限窗内映射可能已被新会话顶替——按 project
            # 名盲 pop 会摘掉新会话制造孤儿进程，仅当仍是本会话时才移除。
            if self._sessions.get(session.project) is session:
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
                    ev = None
                # code-review item a1ad7f4c983b：合法 JSON 但非 object（null/数组/
                # 字符串等）的行若放行到下方 ev.get 会抛 AttributeError，被外层
                # except 捕获后整条读循环终止、存活会话被误按 process_exit 移除，
                # 故与 JSONDecodeError 同走 stderr 兜底分支。
                # 非 JSON / 非 object 行 → stderr 兜底事件（进缓冲 + 广播，前端实时可见）
                if not isinstance(ev, dict):
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

                # add-session-composer 1.1：捕获 init 事件的 slash_commands/skills
                # 覆盖写入 Session 缓存（commands 端点数据源），init 本身不进缓冲
                # 不广播——有意行为变化：前端 claude-msg/runEvents.ts 的
                # SILENT_KINDS 已含 init（零渲染依赖），SSE 消费端无可见回归。
                if ev_type == "system" and ev_subtype == "init":
                    session.slash_commands = [
                        str(c) for c in (ev.get("slash_commands") or [])
                    ]
                    session.skills = [str(c) for c in (ev.get("skills") or [])]
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
            # 若已被 _terminate（user/idle/shutdown）认领或先行移除则不再重复
            # 广播（避免同会话出现两条终态事件）。code-review item 84c6823a177e：
            # _terminate 认领（terminating=True）到移除之间隔着关 stdin 与宽限
            # 等待，进程恰在此窗内退出时本 finally 会触发且会话仍在映射中——
            # 只查注册表会把真实停止理由抢先成 process_exit 并产生两条终态
            # 事件，故补查 terminating，交由 _terminate 落终态。
            # code-review item a1ad7f4c983b：循环因异常退出（如 broadcast 抛错）
            # 时进程可能仍在运行——补查 poll()，进程仍存活则不删会话、不广播
            # process_exit 终态（记 WARNING 留痕），交由 _terminate/idle 扫描
            # 正常回收，防存活会话被误删、子进程成孤儿。
            # code-review item 67cd36c22c79：终态广播与映射摘除解耦——get()/
            # start()/send() 的清理分支会在进程退出后抢先摘除映射但不广播，
            # 若仍以「映射仍指向本会话」作为广播前置，抢先摘除后本 finally 判
            # still_registered 为假即静默返回，该会话的 SSE 订阅端收不到任何
            # 终态事件。故广播条件改为「进程已退出且未被 _terminate 认领」，
            # 仅靠 terminating 标记去重——认领方 _terminate 与本 finally 二者
            # 恰其一广播，恰一方广播约定不变；映射摘除仍仅在映射仍指向本会话
            # 时执行，避免误摘他人。存活会话不可能被未认领路径摘除（get/
            # start/send 均只摘已退出进程），故 proc_still_alive 判定无需再查
            # 映射归属。
            with self._lock:
                claimed = session.terminating
                proc_exited = session.proc.poll() is not None
                still_registered = (
                    not claimed
                    and proc_exited
                    and self._sessions.get(session.project) is session
                )
                if still_registered:
                    self._remove_session_nolock(session.project)
                proc_still_alive = not claimed and not proc_exited
            if proc_still_alive:
                logger.warning(
                    "stdout reader exited but process alive: session=%s pid=%d, "
                    "kept for _terminate/idle reclaim",
                    sid,
                    session.proc.pid,
                )
            if not claimed and proc_exited:
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
