"""
logger.py — Structured logging for fenixd.

Provides JSON-format structured logging with rotation support.
Writes to .fenix/logs/fenixd.log.
"""

import fcntl
import json
import logging
import os
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


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
        return json.dumps(entry, ensure_ascii=False)


class FlockRotatingFileHandler(RotatingFileHandler):
    """
    跨进程安全的 RotatingFileHandler。

    daemon、dashboard、CLI 等多个进程各自构造 Logger 并共写同一
    `.fenix/logs/fenixd.log`，而标准 RotatingFileHandler 只保证单进程安全：
    一进程轮转改名后，另一进程仍持旧 fd 把日志写进已改名的备份文件，且并发
    rollover 会互相覆盖备份。本子类用伴随锁文件 `<日志>.lock` 的 flock
    串行化各进程的轮转窗口，并在持锁后做 (st_dev, st_ino) 陈旧检测，
    发现基底文件已被其他进程轮转时仅重新打开新基底文件，不再重复 rename。
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
        return self._path_is_stale()

    def doRollover(self):
        # 取跨进程排他锁，串行化轮转窗口；进程退出后 flock 随 fd 自动释放
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
        self._level = getattr(logging, level.upper(), logging.INFO)

        # 全局 "fenixd" 根日志器仅承载 fenixd.* 裸 getLogger 的传播记录；
        # 本实例的结构化写入不经它分发（见 _log）。
        self._python_logger = logging.getLogger("fenixd")
        self._python_logger.setLevel(self._level)
        # Close previous handlers before clearing
        for h in list(self._python_logger.handlers):
            h.close()
            self._python_logger.removeHandler(h)

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

    def _log(self, level: int, component: str, message: str, context: dict = None):
        """Thread-safe log entry."""
        # 级别判定（fix-robustness-edge-cases 3.3）：先判级再构造 record，
        # level 低于日志器级别时直接跳过。判本实例的 self._level 而非全局
        # logger 的 isEnabledFor——多项目同进程下各 Logger 依次构造并重绑
        # 全局 "fenixd" 日志器，其级别是 last-wins 的，读它会串级别。
        if level < self._level:
            return
        # close() 后 _handler 被置 None：daemon 关停序列里（atexit 钩子、异常
        # 兜底、后台线程收尾）close 之后仍可能有日志调用，这里降级为无害
        # no-op，避免 AttributeError 掩盖原始错误甚至打断关停路径。先取局部
        # 变量再判空，容忍判空与使用之间被 close() 并发置 None。
        handler = self._handler
        if handler is None:
            return
        with self._lock:
            record = logging.LogRecord(
                name="fenixd",
                level=level,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None,
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

    # 尾部窗口单次读取字节数：JSON 行通常远小于此，无级别过滤时一轮即可
    # 凑够 lines 条；带过滤时按窗口向前扩直至文件头，峰值内存为单窗而非全文件
    TAIL_WINDOW_BYTES = 64 * 1024

    def tail(self, lines: int = 20, level: str = None) -> list:
        """Return the last N log lines, optionally filtered by level."""
        log_file = self.log_dir / "fenixd.log"
        if not log_file.exists():
            return []

        # 基于 seek 的尾部窗口读取（code-review ec3bd4861a4b）：原实现
        # f.readlines() 把整个文件读进内存（handler maxBytes=10MB），且级别
        # 过滤只在末尾 3N 行窗口内进行、会漏掉更早的匹配行。现从文件尾按
        # 窗口向前扩展，直到凑够 lines 条匹配或到文件头；窗口两端对齐换行
        # 边界并丢弃残行，避免把跨窗口截断的行当完整行解析。
        wanted_level = level.upper() if level else None
        result = []
        # exists() 与 open() 之间存在竞态窗口：FlockRotatingFileHandler 恰好
        # 完成轮转（fenixd.log 被 rename 成 .1、新文件尚未重建）或多进程窗口
        # 内文件被外部删除，open 抛 FileNotFoundError/OSError 直接冒泡会让
        # dashboard 尾部日志 API 500。tail 是只读观测接口，与同文件其余路径
        # 的 OSError 容错口径一致，失败降级为空集。
        try:
            with open(log_file, "rb") as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                window_end = file_size
                while True:
                    window_start = max(0, window_end - self.TAIL_WINDOW_BYTES)
                    f.seek(window_start)
                    text = f.read(window_end - window_start).decode(
                        "utf-8", errors="replace"
                    )
                    if window_start > 0:
                        # 首段可能是上一窗口截断的残行，对齐到下一个换行
                        newline = text.find("\n")
                        text = text[newline + 1 :] if newline != -1 else ""
                    if window_end < file_size:
                        # 末段残行属于下一轮窗口，这里丢弃
                        newline = text.rfind("\n")
                        text = text[: newline + 1] if newline != -1 else ""
                    window_entries = []
                    for line in text.splitlines():
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if wanted_level and entry.get("level") != wanted_level:
                            continue
                        window_entries.append(entry)
                    # 各窗口从尾向头扫描，前插以保持与日志时间顺序一致
                    result = window_entries + result
                    if len(result) >= lines or window_start == 0:
                        break
                    window_end = window_start

            return result[-lines:]
        except OSError:
            return []
