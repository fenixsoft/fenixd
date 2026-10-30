"""session_manager.py — 项目级自由会话进程管理器（dashboard-live-session D1/D2/D5）。

管理每项目至多一个 claude 子进程，stdin 写入、stdout/stderr 读线程、
事件缓冲与空闲回收。纯标准库，与 dashboard 进程同生命周期。
"""

from __future__ import annotations

import codecs
import json
import logging
import os
import select
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from core.agent_env_keys import AGENT_RUN_BANNED_ENV_KEYS
from core.proc_utils import guard_killpg

logger = logging.getLogger("fenixd.dashboard.session_manager")

# ── 模块常量 ────────────────────────────────────────────────────────────────
# D5 / design：不新增受管配置键，与 fix-verify-serving-disk-reclaim
# 的 RECLAIM_GRACE_SECONDS = 600 同款处置。

SESSION_EVENT_BUFFER = 4000          # 事件环形缓冲上限
SESSION_IDLE_TIMEOUT_SECONDS = 1800  # 空闲回收阈值（30 分钟）
SESSION_TERMINATE_GRACE_SECONDS = 5  # 终止宽限：关 stdin 后等该秒数再 kill
# 读线程放弃判定的轮询周期（秒）：select 超时粒度。会话被收割并移出映射后，
# 管道写端若仍被逃逸进程组的孙进程持有（setsid/nohup 逃出进程组继承写端，
# 该形态的现实性见 regression_routes._AUTODRAFT_REAP_TIMEOUT_SECONDS 注释），
# 读端 EOF 永不到来——读线程至多再等该时长即主动退出，Session 对象随之可
# 回收（code-review item 5e822919a5ae）。
SESSION_READER_POLL_SECONDS = 0.5


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
    # code-review item 2e9b99afdf93：会话创建时刻，仅 start 重建时随新实例生成，
    # 活动/复用不刷新——routes 的 started_at 响应键语义为真（last_activity 随
    # send/读线程事件不断前移，不能当起始时刻用）。
    started_at: float = field(default_factory=time.time)
    # code-review item 15da2be46889：本字段无单一保护锁，纪律如下——写侧
    # _stdout_reader / send 持 session.lock，start 复用分支持 manager._lock
    # （该分支在 manager._lock 内，不得再取 session.lock）；读侧 idle 回收
    # （_scan_idle 快照 + _terminate 认领前复核）持 manager._lock。idle 复核
    # 读与 send 的刷新刻意不做互斥：全文件维持 session.lock 与 manager._lock
    # 从不嵌套持有（send 的 stdin.write 可在持 session.lock 期间无限阻塞，
    # 若 idle 认领持 manager._lock 再等 session.lock，单个僵死会话会冻住
    # 整个 manager），故 idle 复核对 in-flight send 仅为尽力收窄——残余窗口
    # 微秒级，最坏把刚完成 send 的会话回收，后果限于一次竞态消息或一次
    # SessionNotRunningError，不为闭合它引入锁序反转。
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
        # code-review item ba9e09f14e6d：关闭闸门——shutdown 置位后 start 拒绝
        # 新会话，堵住「快照之后、进程退出之前」窗口内 spawn 的孤儿子进程；
        # send 亦受同一闸门拒绝（item ce79496a981d），覆盖 start/send 全部入口。
        self._closed = False
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
            # code-review item ba9e09f14e6d：已关闭则拒绝新会话（含复用分支）。
            # 调用方 _api_session_start 以 except Exception 兜底 500，无穿透。
            if self._closed:
                raise SessionError("session manager is shut down")
            existing = self._sessions.get(project_name)
            if existing is not None:
                # code-review item 6f1f51a385a0：_terminate 认领后（关 stdin →
                # 等宽限窗 → kill）进程在窗内仍存活，仅凭 poll() 判活会把即将
                # 被 kill 的会话当可用会话复用，调用方随后的 send 大概率
                # SessionNotRunningError——与 send/stop 的幂等语义对齐，已认领
                # 终止的会话按已退出处理，走下方清理重建路径。
                # 判定收拢进 _is_alive（code-review item c67a62ff28c4）。
                if self._is_alive(existing):
                    # 进程存活，复用
                    existing.last_activity = time.time()
                    return existing
                # 进程已退出，清理后重建
                self._remove_session_nolock(project_name)

            cmd = self._build_cmd()
            env = self._build_env()
            session_id = uuid.uuid4().hex

            # code-review item 46ca71736389：独立进程组（setsid），_terminate 宽限
            # 超时改 killpg 整组收割——claude 以 bypassPermissions 运行可再派生
            # 工具子进程，仅 kill 直接子进程会留孤儿孙进程（与 core.knowledge
            # ._default_spawn / core.v2_dev_server 的清场范式对齐）。会话管道
            # 全为 PIPE 由读线程消费，独立进程组不影响 IO。
            # [fenix-ignore:8cf2f2bfce9a] spawn 在 manager 全局锁内系当前规模下的有意取舍（每项目至多一会话、正常几十毫秒），per-project 锁细化收益不抵复杂度，维持现状
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # 显式 UTF-8 + replace（code-review item 9b6d72e47c71）：
                # text=True 缺省按 locale 编码且 strict 解码，坏字节会在
                # 读线程逐行迭代时抛 UnicodeDecodeError 终止读循环，进程
                # 仍存活但 stdout 不再被消费、写满管道后挂死；与仓库
                # subprocess 编码惯例对齐（session_routes / hook_engine）。
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(project_path),
                env=env,
                start_new_session=True,
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
        """获取存活会话（进程已退出或已认领终止则清理并返回 None）。"""
        with self._lock:
            session = self._sessions.get(project_name)
            # code-review item c67a62ff28c4：存活判定收拢进 _is_alive——仅凭
            # poll() 会把 _terminate 认领后宽限窗内仍存活的会话当存活返回，
            # 调用方随后 send 大概率 SessionNotRunningError；与 start 复用
            # 分支口径对齐，terminating 会话按已退出处理。
            if session is not None and not self._is_alive(session):
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
            # code-review item ce79496a981d：关闭闸门覆盖 send——shutdown 置位
            # 后、_terminate 逐个收尾前，不得再向存活会话 stdin 写入竞态消息；
            # 与 start 闸门（ba9e09f14e6d）口径一致。关闭链路（_terminate/
            # _reap_claimed_session）直接操作 stdin，不经 send，无放行需求。
            # 调用方 _api_session_send 以 except SessionError 兜 400，无穿透。
            if self._closed:
                raise SessionError("session manager is shut down")
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
            # [fenix-ignore:eea05edeb272] 有界写（非阻塞/select+分片重试）须重构写循环，且引入部分写致流协议错乱、慢读但存活的会话被误折算为已退出等新失效模式；阻塞前提是子进程停读且管道写满，维持现状风险更低
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
            # code-review item ba9e09f14e6d：持锁先置位关闭标记再快照——start 与
            # shutdown 在同一把锁上串行：置位前完成的 start 必已把会话登记进
            # 映射、必入快照被终止；置位后到达的 start 必被拒绝。消除「快照后
            # spawn、退出链不知晓」的孤儿窗口。
            self._closed = True
            sessions = list(self._sessions.values())
        # code-review item da1eacbbbe78：串行终止为有意选择——会话数少（每项目
        # 至多一个），正常会话关 stdin 即退，仅僵死会话各拖约宽限 5s+kill 后 2s；
        # 并行 _terminate 的收益小于额外线程与竞态复杂度（认领/映射顶替守卫已
        # 在 _terminate 内串行成立），维持串行。
        for s in sessions:
            self._terminate(s, "shutdown")
            # code-review item 8d55257a7686：_terminate 幂等守卫对已被 idle 扫描
            # 线程认领（terminating=True）的会话直接 return，收割留在 daemon
            # idle 线程手里——进程退出不会等待它，恰在宽限窗内被硬杀时其 killpg
            # 永不执行，独立进程组（start_new_session=True）的 claude 及其工具
            # 子进程孤儿化。退出链上补一次有界等待 + killpg 兜底（进程已退出时
            # 立即返回，零额外开销）。
            self._reap_claimed_session(s)

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
        # 同 shutdown：串行为有意选择（item da1eacbbbe78）——本循环在后台
        # daemon 线程内，不在关闭链上，僵死会话至多拖慢下一轮扫描，无需并行。
        for s in candidates:
            self._terminate(s, "idle", idle_only=True)

    # ── 内部：进程终止 ─────────────────────────────────────────────────────

    def _terminate(
        self, session: Session, reason: str, idle_only: bool = False
    ) -> None:
        """关 stdin → 等宽限 → kill → 广播 session_ended → 移除。

        idle_only：空闲回收专用——认领与活跃复核合并进同一临界区，复核不过
        直接放弃本次回收（仅 _scan_idle 传 True）。
        """
        # 幂等守卫（与 _stdout_reader 的 still_registered 同式）：并发 stop/idle/
        # shutdown 或会话已被替换/移除时，只允许一个线程走完整终止流程，
        # 避免同会话广播两条 session_ended 终态事件。短临界区，锁内不做等待/广播。
        with self._lock:
            if session.terminating or self._sessions.get(session.project) is not session:
                return  # 已被其他路径认领或移除
            # code-review item db06105b6496：_scan_idle 快照候选后已释放锁，与
            # _terminate 之间 send/start 可能已刷新 last_activity——idle 回收在
            # 认领前锁内重查空闲阈值，刚恢复活跃的会话放弃回收，防进行中的
            # send 以 SessionNotRunningError 失败（TOCTOU 尽力收窄：本读持
            # manager._lock，与 send 的 session.lock 刷新无互斥，取舍见
            # Session.last_activity 注）。
            if idle_only and (
                time.time() - session.last_activity
            ) <= SESSION_IDLE_TIMEOUT_SECONDS:
                return
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
            # code-review item 46ca71736389：killpg 收割整个进程组，与
            # core.knowledge._kill_process_group 同式。击杀经自保护守卫
            # （add-killpg-self-guard，resolve 型）：守卫拒绝（自身组/非正
            # pgid）与组已不存在同样静默，不降级单进程 kill（pid=0 经 os.kill
            # 折算同为调用者自身组广播）。
            guard_killpg(
                pid, signal.SIGKILL, caller="session_manager._terminate", resolve=True
            )
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
        # code-review item 79d40459a39e：append 与消费端锁内快照构成互斥，
        # 防 HTTP 线程迭代 deque 期间被并发修改抛 RuntimeError。广播不进锁。
        with session.lock:
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

    def _reap_claimed_session(self, session: Session) -> None:
        """有界等待已被其他路径认领的会话退出，超时对进程组 killpg 兜底。

        shutdown 专用：认领方（idle 扫描线程）是 daemon 线程，dashboard 进程
        退出不会等待它，宽限窗内被硬杀则其 killpg 永不执行。等待上限取认领方
        _terminate 的最长收割时长（宽限 + kill 后 wait）；超时按 _terminate
        同式再 killpg 一次（守卫契约：解析失败/组已不存在即静默返回，不回退
        单进程 kill）。SIGKILL 幂等，与认领方重复 kill 无害；终态广播与
        映射摘除仍归认领方，
        此处不碰（避免同会话两条终态事件）。不持锁等待：认领方收尾需取
        self._lock 与 session.lock。
        """
        try:
            session.proc.wait(timeout=SESSION_TERMINATE_GRACE_SECONDS + 2)
            return
        except subprocess.TimeoutExpired:
            pass
        # 击杀经自保护守卫（add-killpg-self-guard，resolve 型）：守卫拒绝
        # （自身组/非正 pgid）与组已不存在同样静默，不降级单进程 kill。
        guard_killpg(
            session.proc.pid,
            signal.SIGKILL,
            caller="session_manager._reap_claimed_session",
            resolve=True,
        )
        try:
            session.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    def _is_alive(self, session: Session) -> bool:
        """会话存活判定（caller 已持有 self._lock，terminating 亦在该锁内读写）。

        code-review item c67a62ff28c4：单一谓词供 start 复用分支与 get 共用，
        消灭口径分叉——仅凭 poll() 会把 _terminate 认领后（关 stdin → 等宽限
        → kill）宽限窗内仍存活的会话当可用（item 6f1f51a385a0 同源问题）。
        """
        return session.proc.poll() is None and not session.terminating

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

    def _pump_stream_lines(self, session: Session, stream_name: str, handle_line) -> None:
        """逐行泵取子进程输出并回调（stdout/stderr 共用，按 \n 拼行）。

        真实 OS 管道（生产 Popen.PIPE 恒为真实管道）走 select 超时 + os.read
        分段读取、自行拼行：单轮至多阻塞 SESSION_READER_POLL_SECONDS，超时
        回圈复查 _reader_abandoned。会话被收割并移出映射后，管道写端可能仍被
        逃逸进程组的孙进程持有，读端 EOF 永不到来——原 `for line in
        proc.stdout` 的无超时阻塞读会让读线程连同 Session 对象（事件缓冲与
        锁）滞留至进程退出，start/stop 反复命中即逐次累积（item 5e822919a5ae，
        滞留形态佐证见 _reader_abandoned 注）；带超时分段读 + 主动放弃堵死
        该滞留，映射摘除与两读线程退出后 Session 即可被回收。
        UTF-8 增量解码（errors="replace"，与 Popen 的 encoding/errors 口径
        一致）防多字节字符被分段读错切；按 \n 拼行并剥行尾 \r，与文本模式
        universal newlines 的逐行语义对齐（行内 \r 不受影响；EOF 残余半行
        照发）。测试替身流无 OS fd，回退原逐行迭代语义（替身经 close()/EOF
        事件唤醒模拟 EOF，见 tests/test_dashboard_session.py FakePipe）。
        os.read 的 OSError（读端并发关闭等）原样上抛，由调用方 except 留痕，
        与原逐行迭代异常面一致。
        """
        stream = getattr(session.proc, stream_name)
        try:
            fd = stream.fileno()
        except (AttributeError, OSError, ValueError):
            fd = None
        if fd is None:
            for line in stream:
                handle_line(line.rstrip("\n"))
            return
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        pending = ""
        while True:
            if self._reader_abandoned(session):
                return
            # 单轮有界等待：超时无数据回圈复查放弃条件；真 EOF 会即刻就绪，
            # 下方 os.read 立即返回 b""，正常路径无额外延迟。
            if not select.select([fd], [], [], SESSION_READER_POLL_SECONDS)[0]:
                continue
            chunk = os.read(fd, 65536)  # 已就绪读不阻塞
            if not chunk:
                if pending:  # EOF 残余半行（无换行结尾）按文本迭代语义补发
                    handle_line(pending.rstrip("\r"))
                return
            pending += decoder.decode(chunk)
            while True:
                nl = pending.find("\n")
                if nl < 0:
                    break
                line, pending = pending[:nl], pending[nl + 1:]
                handle_line(line.rstrip("\r"))

    def _reader_abandoned(self, session: Session) -> bool:
        """读线程是否应主动放弃：会话已移出映射且其输出不再有消费方。

        映射仍指向本会话（_terminate 宽限窗内、或正常消费中）→ 继续读，不丢
        任何输出。移出映射（被 _terminate 收割移除，或 get/start/send 按「已
        退出/已认领」清退或顶替）后，若已认领终止或进程已退出，读端能否 EOF
        只取决于逃逸孙进程何时关闭继承的写端（不可期）→ 放弃，残余未读输出
        随会话终止一并丢弃。终态广播约定不受影响：认领态（terminating）由
        _terminate 落 session_ended、读线程 finally 去重不重发；非认领态
        （进程自行退出后被清退）读线程 finally 照常补发 process_exit。
        调用方不持任何锁；此处取 manager._lock 短临界区（与全文件
        session.lock / manager._lock 不嵌套持有纪律一致）。
        """
        with self._lock:
            if self._sessions.get(session.project) is session:
                return False
            return session.terminating or session.proc.poll() is not None

    def _stdout_reader(self, session: Session) -> None:
        """逐行读 stdout：JSON 行解析为事件并广播；脏行进 stderr 兜底。"""
        sid = session.session_id
        try:
            self._pump_stream_lines(
                session,
                "stdout",
                lambda line: self._handle_stdout_line(session, sid, line),
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
                # code-review item 79d40459a39e：append 持锁（见 _terminate 同注）
                with session.lock:
                    session.events.append(end_event)
                self._hub.broadcast(
                    {"type": "session_events", "session_id": sid, "events": [end_event]},
                    run_id=sid,
                )
                logger.info("stdout EOF: session=%s reason=process_exit", sid)

    def _handle_stdout_line(self, session: Session, sid: str, line: str) -> None:
        """单行 stdout 处理：JSON 行转事件广播，脏行转 stderr 兜底事件。"""
        if not line:
            return
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
            # code-review item 79d40459a39e：append 持锁（见 _terminate 同注）
            with session.lock:
                session.events.append(ev)
            self._hub.broadcast(
                {"type": "session_events", "session_id": sid, "events": [ev]},
                run_id=sid,
            )
            return

        # D1.1 hook 噪音过滤：丢弃 system/hook_* 事件
        ev_type = ev.get("type", "")
        ev_subtype = ev.get("subtype", "")
        if ev_type == "system" and isinstance(ev_subtype, str) and ev_subtype.startswith("hook_"):
            return

        # add-session-composer 1.1：捕获 init 事件的 slash_commands/skills
        # 覆盖写入 Session 缓存（commands 端点数据源），init 本身不进缓冲
        # 不广播——有意行为变化：前端 claude-msg/runEvents.ts 的
        # SILENT_KINDS 已含 init（零渲染依赖），SSE 消费端无可见回归。
        if ev_type == "system" and ev_subtype == "init":
            session.slash_commands = [
                str(c) for c in (ev.get("slash_commands") or [])
            ]
            session.skills = [str(c) for c in (ev.get("skills") or [])]
            return

        # 补 ts 字段
        if "ts" not in ev:
            ev["ts"] = time.time()

        # [fenix-ignore:232cecb1ea26] 四处 events.append 均已持 session.lock（item 79d40459a39e 既有修复覆盖），本条所述未持锁状态不成立
        # code-review item 79d40459a39e：append 持锁（见 _terminate 同注）
        # code-review item 15da2be46889：last_activity 刷新同锁收编，
        # 写侧不再有裸写（锁纪律总述见 Session.last_activity 注）。
        with session.lock:
            session.events.append(ev)
            session.last_activity = time.time()

        # 广播
        self._hub.broadcast(
            {"type": "session_events", "session_id": sid, "events": [ev]},
            run_id=sid,
        )

    def _stderr_reader(self, session: Session) -> None:
        """逐行读 stderr 进 stderr_tail 环形缓冲，不广播。"""
        try:
            self._pump_stream_lines(
                session, "stderr", lambda line: self._handle_stderr_line(session, line)
            )
        except Exception:
            # code-review item bbb0cd968a89：与 _stdout_reader 的留痕纪律对齐
            logger.exception("stderr reader error: session=%s", session.session_id)

    @staticmethod
    def _handle_stderr_line(session: Session, line: str) -> None:
        """单行 stderr 处理：进尾部环形缓冲（不广播）。"""
        if not line:
            return
        # f6396e93c224：读端 session_routes 锁内快照 stderr_tail，
        # 写端 append 须同锁互斥（否则并发 append 下迭代抛
        # RuntimeError(deque mutated during iteration)）。
        with session.lock:
            session.stderr_tail.append(line)
