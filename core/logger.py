"""
logger.py — Structured logging for fenixd.

Provides JSON-format structured logging with rotation support.
Writes to .fenix/logs/fenixd.log.
"""

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

        # File handler with rotation
        log_file = self.log_dir / "fenixd.log"
        self._handler = RotatingFileHandler(
            str(log_file),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        self._handler.setFormatter(JsonFormatter())
        self._python_logger.addHandler(self._handler)

    def _log(self, level: int, component: str, message: str, context: dict = None):
        """Thread-safe log entry."""
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
