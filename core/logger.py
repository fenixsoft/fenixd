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

        self._python_logger = logging.getLogger("fenixd")
        self._python_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
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
        # 级别判定（fix-robustness-edge-cases 3.3）：此前直接
        # ``self._python_logger.handle(record)`` 绕开 ``isEnabledFor``，使
        # ``logging.level``（缺省 INFO）失效、DEBUG 恒落盘；先判级再构造
        # record——level=DEBUG 且日志器级别高于 DEBUG 时直接跳过。
        if not self._python_logger.isEnabledFor(level):
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
            self._python_logger.handle(record)
            # Flush to disk for testability and crash safety
            if self._handler:
                self._handler.flush()

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

    def tail(self, lines: int = 20, level: str = None) -> list:
        """Return the last N log lines, optionally filtered by level."""
        log_file = self.log_dir / "fenixd.log"
        if not log_file.exists():
            return []

        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()

        # Read extra lines to account for level filtering
        result = []
        for line in all_lines[-(lines * 3) :]:
            try:
                entry = json.loads(line.strip())
                if level and entry.get("level") != level.upper():
                    continue
                result.append(entry)
            except json.JSONDecodeError:
                continue

        return result[-lines:]
