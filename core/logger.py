"""
logger.py — Structured logging for fenixd.

Provides JSON-format structured logging with rotation support.
Writes to .fenix/logs/fenixd.log.
"""

import fcntl
import json
import logging
import os
import sys
import threading
from pathlib import Path
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


# 单事件序列化体积上限（字节；improve-spec-topology-pipeline-view 1.3）：
# daemon 日志首行曾出现 6.6MB 巨型行（admin_monitor 信号把 51054 个 untracked
# entry 全文嵌入 context），读侧锚定窗口被巨型行整体占据、锚点后事件全部丢失。
# 写侧在序列化出口整体封顶：超限事件 context 替换为占位摘要后重新序列化
# （message/level/timestamp/component 原样保留），防止单条 context 再次撑爆
# 日志窗口。常量可调（测试按需放宽/收紧）。
LOG_EVENT_MAX_BYTES = 256 * 1024


def _json_len(line: str) -> int:
    """序列化产物的 UTF-8 字节长（编码防御与 format 出口同口径，replace 不抛）。"""
    return len(line.encode("utf-8", "replace"))


class JsonFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            # 保持 Z 后缀格式不变（utcnow 的非弃用等价写法），展示层与既有 grep 依赖该格式
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "component": getattr(record, "component", "unknown"),
            "message": record.getMessage(),
        }
        # Include extra context if available
        if hasattr(record, "context") and record.context:
            entry["context"] = record.context
        # 500 兜底等调用方以 logger.exception 约定「详情（含堆栈）留服务端日志」，
        # 缺此字段 traceback 会被静默丢弃（code-review item c175ecdbbeed）
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        # default=str 兜底不可序列化的 context 值（datetime/Path 等）：
        # 否则 json.dumps 抛 TypeError，整条记录被 emit→handleError 吞掉只剩
        # stderr 提示，结构化日志静默丢失
        line = json.dumps(entry, ensure_ascii=False, default=str)
        # 单事件体积上限（improve-spec-topology-pipeline-view 1.3）：不超限
        # 路径逐字节不变（快照测试钉死），超限才进入截断防御。
        if _json_len(line) > LOG_EVENT_MAX_BYTES:
            line = self._cap_event(entry)
        # 孤立代理字符清洗（item 98cd82225213）：os.fsdecode 出的非法文件名等
        # 输入混入孤立代理时 json.dumps(ensure_ascii=False) 原样保留，_json_len
        # 以 replace 口径度量通过，但 handler 以 encoding='utf-8' 写盘会抛
        # UnicodeEncodeError，整条记录被 emit→handleError 吞掉、结构化日志静默
        # 丢失。超限兜底路径（_cap_event 尾部硬截）已有同口径解码清洗先例，这里
        # 在 format 唯一出口拉齐口径，保证任意输入可写盘；合法输入经 replace
        # 往返逐字节不变，不触碰快照钉死的不超限路径。
        return line.encode("utf-8", "replace").decode("utf-8")

    @staticmethod
    def _cap_event(entry: dict) -> str:
        """超限事件截断防御：保证落盘单行 ≤ LOG_EVENT_MAX_BYTES（任意输入可达）。

        ① context 替换为占位摘要（truncated/orig_bytes/context_keys）后重新
        序列化——message/level/timestamp/component 原样保留（specs
        daemon-log-event-governance「message 本体不因 context 截断而丢失」）；
        ② 替换后仍超限（message/exc_info 单体超限）：对超限字段尾部截断并
        附带顶层 truncated 留痕，保证「落盘单行 ≤ 上限」在任意输入下可达。
        """
        line = json.dumps(entry, ensure_ascii=False, default=str)
        total = _json_len(line)
        if "context" in entry:
            orig_ctx = entry["context"]
            entry["context"] = {
                "truncated": True,
                "orig_bytes": total,
                "context_keys": list(orig_ctx.keys()) if isinstance(orig_ctx, dict) else [],
            }
            line = json.dumps(entry, ensure_ascii=False, default=str)
            if _json_len(line) <= LOG_EVENT_MAX_BYTES:
                return line
        # 仍超限：message/exc_info 单体超限，尾部截断（保留头部）。逐次折半
        # 保证终止（1 字符残段直接清空）；顶层 truncated 留痕标记截断形态。
        entry["truncated"] = True
        for _ in range(256):
            line = json.dumps(entry, ensure_ascii=False, default=str)
            if _json_len(line) <= LOG_EVENT_MAX_BYTES:
                return line
            for field in ("exc_info", "message"):
                val = entry.get(field)
                if isinstance(val, str) and val:
                    # 先截 exc_info（堆栈可再生）后截 message（本体优先保留头部）
                    entry[field] = val[: len(val) // 2] if len(val) > 1 else ""
                    break
            else:
                break
        # 理论兜底（无字符串字段仍超限，仅 default=str 折叠出超大非字符串
        # 表示时可达）：硬截序列化产物尾部。截断行不再保证合法 JSON——
        # 读侧逐行 json.loads 失败跳过，不令日志读取链路失败。
        return line.encode("utf-8", "replace")[:LOG_EVENT_MAX_BYTES].decode("utf-8", "ignore")


class FlockRotatingFileHandler(RotatingFileHandler):
    """
    跨进程安全的 RotatingFileHandler。

    daemon、dashboard、CLI 等多个进程各自构造 Logger 并共写同一
    `.fenix/logs/fenixd.log`，而标准 RotatingFileHandler 只保证单进程安全：
    一进程轮转改名后，另一进程仍持旧 fd 把日志写进已改名的备份文件，且并发
    rollover 会互相覆盖备份。本子类用伴随锁文件 `<日志>.lock` 的 flock
    串行化各进程的轮转窗口，并在持锁后做 (st_dev, st_ino) 陈旧检测，
    发现基底文件已被其他进程轮转时仅重新打开新基底文件，不再重复 rename。

    已知残留窗口（code-review item 15ae410d5d35）：伴随 flock 只包住
    doRollover，emit 路径（handle 内的 shouldRollover 判定与 stream.write）
    不持锁。本进程在 shouldRollover 判定「未过期」之后、写入之前，若另一
    进程恰好完成一轮轮转改名，本条记录会追加进已被改名的备份文件而非新
    基底；下一条记录的 _path_is_stale 检测会重开新基底，故损失限于每次
    轮转至多一条错位记录（不丢，仅落错文件）。彻底消除需在 emit 前后同样
    持 flock，代价是所有日志写跨进程串行，与该单条错位的收益不成比例，
    故接受现状并在此明示。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 伴随锁文件：与日志同目录，仅用于跨进程互斥，本身无内容
        self._lock_filename = self.baseFilename + ".lock"

    @staticmethod
    def _inode_tuple(st) -> tuple:
        return (st.st_dev, st.st_ino)

    def _path_is_stale(self) -> bool:
        """
        陈旧检测：基底文件路径当前指向的 inode 与本进程持有 fd 的 inode
        不一致，说明其他进程已轮转改名（或文件被外部删除），本进程的流
        已经过期。stream 为 None 时保持既有语义，交由调用方处理。
        """
        if self.stream is None:
            return False
        try:
            path_stat = os.stat(self.baseFilename)
        except FileNotFoundError:
            return True
        try:
            fd_stat = os.fstat(self.stream.fileno())
        except (OSError, ValueError):
            # fd 已失效或流已关闭，同样视为陈旧
            return True
        return self._inode_tuple(path_stat) != self._inode_tuple(fd_stat)

    def shouldRollover(self, record) -> bool:
        if super().shouldRollover(record):
            return True
        # 其他进程轮转后本进程仍持旧 fd 会把日志写进已改名文件，陈旧即视为需轮转
        # [fenix-ignore:6d3b591495d7] 仅放行记录（_log 已先判级）各多两次 stat，节流需引入共享状态、复杂度与收益不成比例，保持现状
        return self._path_is_stale()

    def doRollover(self):
        # 取跨进程排他锁，串行化轮转窗口；进程退出后 flock 随 fd 自动释放
        # [fenix-ignore:68f9518f845d] 锁文件常驻仅是目录卫生问题，close 时清理存在多进程竞态、收益有限，保持现状
        lock_fd = os.open(self._lock_filename, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if self._path_is_stale():
                # 基底文件已被其他进程轮转改名：只关闭旧流并重新打开新基底
                # 文件，不再 rename，避免覆盖他人的备份序列
                if self.stream:
                    self.stream.close()
                    self.stream = None
                self.stream = self._open()
                return
            super().doRollover()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


class Logger:
    """
    Structured logger for fenixd components.

    Usage:
        logger = Logger(Path(".fenix/logs"), "INFO")
        logger.info("agent_runner", "Starting agent", {"spec": "add-login"})
    """

    def __init__(self, log_dir: Path, level: str = "INFO"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._handler = None
        # 实例自身级别：级别判定只读本实例状态。多项目同进程下全局 "fenixd"
        # 日志器被各项目实例先后 setLevel，其级别是 last-wins 的共享状态。
        # getattr 未命中（配置级别拼写错误，如 "INF0"/"verbose"）时本 logger
        # 尚未就绪、不能走日志通道，先向 stderr 打一行警告再按 INFO 宽容回退，
        # 避免配置静默失效（code-review item c0dc5282e062）。构造期一次性
        # 告警，重复构造重复警告可接受，无需去重。
        # 非 str 级别（如沿用 stdlib 数值习惯的 20、布尔）同样走下面的 stderr
        # 告警 + INFO 宽容回退，不在 level.upper() 上 AttributeError 炸掉构造
        # （code-review item b0340a81d79d）；显式 null 经 ConfigLoader.get 已
        # 回缺省 "INFO"，不进本分支。
        _resolved_level = None
        if isinstance(level, str):
            _resolved_level = getattr(logging, level.upper(), None)
        # 级别常量均为 int；getattr 命中 logging 模块的非级别属性（如
        # BASIC_FORMAT 是格式模板字符串）时同样视为解析失败，否则
        # setLevel(该字符串) 会 ValueError 炸掉构造（code-review item
        # 2781d8672820），统一走下面的 stderr 告警 + INFO 回退
        if not isinstance(_resolved_level, int):
            print(
                f"fenixd: unknown logging level {level!r}, falling back to INFO",
                file=sys.stderr,
            )
            _resolved_level = logging.INFO
        self._level = _resolved_level

        # 全局 "fenixd" 根日志器仅承载 fenixd.* 裸 getLogger 的传播记录；
        # 本实例的结构化写入不经它分发（见 _log）。
        self._python_logger = logging.getLogger("fenixd")
        self._python_logger.setLevel(self._level)
        # 仅摘除旧实例挂在全局日志器上的 handler，不 close（code-review item
        # 3617b2ee430b）：多项目同进程下 project_state_logger 按项目根缓存
        # Logger 实例（state_machine.py），N 个实例并存且各自经 _log 直写本
        # 项目的 fenixd.log；在此 close 会关掉前一项目实例仍持有的流，其后续
        # 日志静默丢失。handler 生命周期归各自实例的 close() 管理。
        for h in list(self._python_logger.handlers):
            self._python_logger.removeHandler(h)
        # 已知局限（code-review item 9ed664019b2d）：摘除之后全局日志器只剩
        # 最后构造实例的 handler，裸 logging.getLogger("fenixd.*") 子日志器
        # （core 下 30 余处，如 archive_commit.py）自身无 handler，按传播语义
        # 其记录会上溯串写进最后构造项目的 fenixd.log，生效级别也随最后实例
        # 的 _level 漂移。进程内没有可靠的「当前项目」上下文可供按项目路由，
        # 保留多实例 handler 又会向所有项目扇出串写，故维持 last-wins 并在此
        # 明示：core 代码需要落盘日志时统一走 Logger 实例，勿依赖裸
        # getLogger("fenixd.*") 通道（其输出项目归属不确定）。

        # File handler with rotation（FlockRotatingFileHandler：多进程共写安全的轮转）
        log_file = self.log_dir / "fenixd.log"
        self._handler = FlockRotatingFileHandler(
            str(log_file),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        self._handler.setFormatter(JsonFormatter())
        self._python_logger.addHandler(self._handler)

    def _log(self, level: int, component: str, message: str, context: dict = None,
             exc_info=None):
        """Thread-safe log entry. exc_info 非 None 时经 JsonFormatter 落盘堆栈。"""
        # 级别判定（fix-robustness-edge-cases 3.3）：先判级再构造 record，
        # level 低于日志器级别时直接跳过。判本实例的 self._level 而非全局
        # logger 的 isEnabledFor——多项目同进程下各 Logger 依次构造并重绑
        # 全局 "fenixd" 日志器，其级别是 last-wins 的，读它会串级别。
        if level < self._level:
            return
        # close() 后 _handler 被置 None：daemon 关停序列里（atexit 钩子、异常
        # 兜底、后台线程收尾）close 之后仍可能有日志调用，这里降级为无害
        # no-op，避免 AttributeError 掩盖原始错误甚至打断关停路径。判空放在
        # self._lock 内与 close() 的置 None 互斥（code-review item
        # 87f191448088），锁内所见即所写，不再有判空与使用之间被并发
        # close() 的窗口。
        with self._lock:
            handler = self._handler
            if handler is None:
                return
            record = logging.LogRecord(
                name="fenixd",
                level=level,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=exc_info,
            )
            record.component = component
            record.context = context
            # 直接经本实例 handler 落盘（handler.handle 自带锁与陈旧轮转
            # 处理）：全局 "fenixd" 日志器是单例，多项目同进程下
            # project_state_logger 各建 Logger 后其 handler 是最后构造项目
            # 的，经 self._python_logger.handle(record) 分发会把记录写进
            # 别的项目的 fenixd.log。
            handler.handle(record)
            # Flush to disk for testability and crash safety
            handler.flush()

    def close(self):
        """Close the log handler, flushing any buffered data."""
        # 与 _log 共用 self._lock：flush/close/置 None 与 _log 的锁内判空
        # 互斥，关停窗口内并发日志调用不会写向已 close 的流（code-review
        # item 87f191448088）。
        with self._lock:
            if self._handler:
                self._handler.flush()
                self._handler.close()
                self._python_logger.removeHandler(self._handler)
                self._handler = None

    def debug(self, component: str, message: str, context: dict = None):
        self._log(logging.DEBUG, component, message, context)

    def info(self, component: str, message: str, context: dict = None):
        self._log(logging.INFO, component, message, context)

    def warning(self, component: str, message: str, context: dict = None):
        self._log(logging.WARNING, component, message, context)

    def error(self, component: str, message: str, context: dict = None):
        self._log(logging.ERROR, component, message, context)

    def exception(self, component: str, message: str, context: dict = None):
        # 在 except 块内调用：取当前异常堆栈传入 LogRecord，JsonFormatter 的
        # exc_info 字段经实例通道真正生效（item df6de36313c9——core 代码统一
        # 走 Logger 实例落盘，traceback 不得依赖手工拼进 message）。
        # except 块外 sys.exc_info() 返回 (None, None, None)，三元组为真值会让
        # JsonFormatter 落盘一段「NoneType: None」伪堆栈（item 129ba2b71356），
        # 无异常时归一为 None。
        exc = sys.exc_info()
        self._log(logging.ERROR, component, message, context,
                  exc_info=exc if exc[0] is not None else None)
