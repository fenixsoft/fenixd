"""improve-spec-topology-pipeline-view 1.4：daemon 日志写侧单事件体积上限。

JsonFormatter 序列化出口封顶（specs/daemon-log-event-governance「日志写侧
单事件序列化体积上限」Requirement）：

- 巨型 context（>256KB，实测样本 admin_monitor 嵌 51054 entry 单行 6.6MB）
  截断后落盘单行 ≤ 上限（含开销余量）且为合法 JSONL，含 truncated 留痕，
  message 字段完整保留；
- 正常事件（< 上限）序列化结果与截断逻辑接入前逐字节一致（修复前逻辑的
  逐字副本对账）；
- message/exc_info 单体超限的兜底路径同样 ≤ 上限且附 truncated 留痕。
"""

import json
import logging
import sys
from datetime import timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import LOG_EVENT_MAX_BYTES, JsonFormatter  # noqa: E402


def _record(message: str = "hello", context=None, exc_info=None) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="fenixd",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=exc_info,
    )
    rec.component = "test_comp"
    rec.context = context
    return rec


def _legacy_format(record: logging.LogRecord) -> str:
    """修复前序列化逻辑逐字副本（快照基准：正常事件逐字节一致对账）。

    时间戳取 ``core.logger.datetime``（fixture 冻结后两侧同源）。
    """
    import core.logger as logger_mod

    entry = {
        "timestamp": logger_mod.datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": record.levelname,
        "component": getattr(record, "component", "unknown"),
        "message": record.getMessage(),
    }
    if hasattr(record, "context") and record.context:
        entry["context"] = record.context
    if record.exc_info:
        entry["exc_info"] = logging.Formatter().formatException(record.exc_info)
    return json.dumps(entry, ensure_ascii=False, default=str)


def _json_len(line: str) -> int:
    return len(line.encode("utf-8", "replace"))


@pytest.fixture()
def frozen_clock(monkeypatch):
    """冻结 JsonFormatter 的时间戳源：逐字节对账两侧同一 timestamp。"""
    from datetime import datetime, timezone

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    import core.logger as logger_mod

    monkeypatch.setattr(logger_mod, "datetime", _FrozenDateTime)


# ── Scenario「正常事件原样写入」 ─────────────────────────────────────────────


class TestNormalEventByteCompatible:
    def test_small_context_byte_identical(self, frozen_clock):
        rec = _record(context={"spec": "demo", "n": 3})
        assert JsonFormatter().format(rec) == _legacy_format(rec)

    def test_no_context_byte_identical(self, frozen_clock):
        rec = _record(message="plain message")
        assert JsonFormatter().format(rec) == _legacy_format(rec)

    def test_non_dict_context_byte_identical(self, frozen_clock):
        rec = _record(context=["a", "b"])
        assert JsonFormatter().format(rec) == _legacy_format(rec)

    def test_exc_info_under_limit_byte_identical(self, frozen_clock):
        try:
            raise ValueError("boom")
        except ValueError:
            rec = _record(message="failed", context={"k": "v"}, exc_info=sys.exc_info())
        assert JsonFormatter().format(rec) == _legacy_format(rec)

    def test_limit_boundary_just_under(self, frozen_clock):
        # 恰在上限内的 context 走原样路径（不触碰截断防御）
        pad = "x" * (LOG_EVENT_MAX_BYTES - 400)
        rec = _record(context={"blob": pad})
        assert JsonFormatter().format(rec) == _legacy_format(rec)
        assert _json_len(JsonFormatter().format(rec)) <= LOG_EVENT_MAX_BYTES


# ── Scenario「巨型 context 事件被截断留痕」 ─────────────────────────────────


class TestGiantContextTruncation:
    def test_giant_context_capped_and_valid_jsonl(self):
        # 实测样本形态：51054 个 entry 全文嵌入 context（>256KB）
        entries = [{"path": f"p{i}", "status": "???"} for i in range(51054)]
        rec = _record(message="admin signal", context={"entries": entries})
        line = JsonFormatter().format(rec)
        assert _json_len(line) <= LOG_EVENT_MAX_BYTES
        # 合法 JSONL 单行（无内嵌裸换行）
        parsed = json.loads(line)
        assert "\n" not in line
        # truncated 留痕 + 顶层键名保留 + 原体积记录
        ctx = parsed["context"]
        assert ctx["truncated"] is True
        assert ctx["orig_bytes"] > LOG_EVENT_MAX_BYTES
        assert ctx["context_keys"] == ["entries"]

    def test_message_preserved_despite_context_truncation(self):
        big = "y" * (LOG_EVENT_MAX_BYTES * 2)
        rec = _record(message="Signal admin_monitor received", context={"blob": big})
        parsed = json.loads(JsonFormatter().format(rec))
        # message 本体不因 context 截断而丢失
        assert parsed["message"] == "Signal admin_monitor received"
        assert parsed["level"] == "INFO"
        assert parsed["component"] == "test_comp"
        assert parsed["timestamp"].endswith("Z")

    def test_multiple_context_keys_listed(self):
        rec = _record(
            message="m",
            context={"alpha": "a" * 200000, "beta": "b" * 200000, "small": 1},
        )
        parsed = json.loads(JsonFormatter().format(rec))
        assert set(parsed["context"]["context_keys"]) == {"alpha", "beta", "small"}
        assert parsed["context"]["truncated"] is True


class TestOversizedFieldFallback:
    def test_giant_message_capped_with_truncated_marker(self):
        # 无 context、message 单体超限：尾部截断 + 顶层 truncated 留痕
        rec = _record(message="HEAD-" + "z" * (LOG_EVENT_MAX_BYTES * 3))
        line = JsonFormatter().format(rec)
        assert _json_len(line) <= LOG_EVENT_MAX_BYTES
        parsed = json.loads(line)
        assert parsed["truncated"] is True
        assert parsed["message"].startswith("HEAD-")

    def test_giant_message_with_context_both_capped(self):
        rec = _record(
            message="M" * (LOG_EVENT_MAX_BYTES * 2),
            context={"blob": "c" * (LOG_EVENT_MAX_BYTES * 2)},
        )
        line = JsonFormatter().format(rec)
        assert _json_len(line) <= LOG_EVENT_MAX_BYTES
        parsed = json.loads(line)
        assert parsed["truncated"] is True
        assert parsed["context"]["truncated"] is True
        assert parsed["message"]  # 头部保留

    def test_giant_exc_info_capped(self):
        try:
            raise RuntimeError("x" * (LOG_EVENT_MAX_BYTES * 2))
        except RuntimeError:
            rec = _record(message="failed", context={"k": 1}, exc_info=sys.exc_info())
        line = JsonFormatter().format(rec)
        assert _json_len(line) <= LOG_EVENT_MAX_BYTES
        parsed = json.loads(line)
        # context 占位摘要已足够（≤ 上限）时 message/exc_info 不再截断
        assert parsed["context"]["truncated"] is True


class TestLoggerEndToEnd:
    def test_logger_writes_capped_jsonl(self, tmp_path):
        """端到端：Logger 实例写巨型 context，落盘单行 ≤ 上限且可解析。"""
        from core.logger import Logger

        logger = Logger(tmp_path, "INFO")
        try:
            logger.info("admin_monitor", "signal", {"entries": [{"p": "x" * 40}] * 20000})
        finally:
            logger.close()
        log_file = tmp_path / "fenixd.log"
        lines = log_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert _json_len(lines[0]) <= LOG_EVENT_MAX_BYTES
        entry = json.loads(lines[0])
        assert entry["message"] == "signal"
        assert entry["context"]["truncated"] is True

    def test_logger_normal_event_roundtrip(self, tmp_path):
        from core.logger import Logger

        logger = Logger(tmp_path, "INFO")
        try:
            logger.info("pm_engine", "Transition: demo drafted → reviewing", {"spec": "demo"})
        finally:
            logger.close()
        lines = (tmp_path / "fenixd.log").read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        assert entry["message"] == "Transition: demo drafted → reviewing"
        assert entry["context"] == {"spec": "demo"}
        assert "truncated" not in entry and "truncated" not in entry.get("context", {})
