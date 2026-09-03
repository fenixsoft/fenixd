"""
Tests for dashboard-log-offset-index: fenixd 日志块偏移索引，查询只读尾部窗口。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dashboard import data as dash_data


def _now_iso(offset_s: int = 0) -> str:
    """当前 UTC 时间（可偏移秒），ISO 格式。"""
    ts = datetime.now(timezone.utc).timestamp() + offset_s
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _make_project_with_log(tmp_path, size_mb: int = 2) -> Path:
    """构造含 size_mb MB 结构化日志的项目（近期时间戳，每行一条 JSON 事件）。"""
    proot = tmp_path / "proj-a"
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    log = proot / ".fenix" / "logs" / "fenixd.log"
    target = size_mb * 1024 * 1024
    written = 0
    idx = 0
    with log.open("a", encoding="utf-8") as f:
        while written < target or idx == 0:
            entry = json.dumps({
                "timestamp": _now_iso(-idx),
                "level": "INFO",
                "component": "pm_engine",
                "message": f"line-{idx}-" + "x" * 150,
            }, ensure_ascii=False) + "\n"
            f.write(entry)
            written += len(entry.encode("utf-8"))
            idx += 1
    return proot


class _CountingReader:
    """包装底层文件对象，累计 read 字节数。"""

    def __init__(self, underlying, counter):
        self._u = underlying
        self._c = counter

    def read(self, *a, **kw):
        data = self._u.read(*a, **kw)
        self._c[0] += len(data)
        return data

    def seek(self, *a, **kw):
        return self._u.seek(*a, **kw)

    def close(self):
        return self._u.close()

    def __getattr__(self, name):
        return getattr(self._u, name)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._u.__exit__(*a)


def _count_log_reads(proot: Path, fn):
    """运行 fn 期间统计日志文件被 read 的总字节数。"""
    log_path = proot / ".fenix" / "logs" / "fenixd.log"
    counter = [0]
    orig_open = Path.open

    def patched_open(self, *a, **kw):
        f = orig_open(self, *a, **kw)
        if str(self) == str(log_path):
            return _CountingReader(f, counter)
        return f

    import pathlib
    monkey = pytest.MonkeyPatch()
    monkey.setattr(pathlib.Path, "open", patched_open)
    try:
        result = fn()
    finally:
        monkey.undo()
    return result, counter[0]


class TestLogOffsetIndex:
    def test_query_reads_only_tail_window(self, tmp_path):
        """大日志文件（2MB）索引就绪后查询只读尾部 ≤1MB 窗口，不读全量。"""
        proot = _make_project_with_log(tmp_path, size_mb=2)
        # 首次查询包含一次性索引构建（≤1 次全量扫描）；就绪后再统计窗口读取
        dash_data.get_recent_events(proot, minutes=10)
        events, read_bytes = _count_log_reads(
            proot, lambda: dash_data.get_recent_events(proot, minutes=10))
        assert isinstance(events, list)
        assert read_bytes < 2 * 1024 * 1024, f"应只读尾部窗口，实际读 {read_bytes} 字节"
        assert read_bytes <= dash_data.LOG_INDEX_TAIL_WINDOW + dash_data.LOG_INDEX_BLOCK + 4096

    def test_index_hot_update_after_append(self, tmp_path):
        """追加新行后再次查询：索引热更新（重建 0 次），新行可被查到。"""
        proot = _make_project_with_log(tmp_path, size_mb=0)
        log = proot / ".fenix" / "logs" / "fenixd.log"
        dash_data.get_recent_events(proot, minutes=10)  # 建立索引
        dash_data._LOG_INDEX_REBUILDS["count"] = 0

        before = dash_data.get_recent_events(proot, minutes=10)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": _now_iso(0), "message": "NEW-EVENT"}) + "\n")
        after = dash_data.get_recent_events(proot, minutes=10)
        assert any(e.get("message") == "NEW-EVENT" for e in after)
        assert dash_data._LOG_INDEX_REBUILDS["count"] == 0, "追加场景不应重建索引"

    def test_index_corrupt_rebuild_tolerance(self, tmp_path):
        """索引缺失或 size 不匹配 → 重建一次后返回正确结果，后续沿用新索引。"""
        proot = _make_project_with_log(tmp_path, size_mb=0)
        dash_data._LOG_INDEX_REBUILDS["count"] = 0

        ev1 = dash_data.get_recent_events(proot, minutes=10)
        assert dash_data._LOG_INDEX_REBUILDS["count"] == 1

        # 模拟索引损坏（size 不匹配）
        idx_path = dash_data._log_index_path(proot)
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text('{"size": 999, "offsets": [0]}', encoding="utf-8")
        dash_data._LOG_INDEX_REBUILDS["count"] = 0
        ev2 = dash_data.get_recent_events(proot, minutes=10)
        assert dash_data._LOG_INDEX_REBUILDS["count"] == 1, "size 不匹配应重建一次"
        assert ev1 == ev2, "重建后结果应与全量口径一致"

        # 后续沿用新索引：不再重建
        ev3 = dash_data.get_recent_events(proot, minutes=10)
        assert dash_data._LOG_INDEX_REBUILDS["count"] == 1, "后续查询沿用新索引，不重建"
        assert ev3 == ev1

    def test_index_missing_then_cached(self, tmp_path):
        """索引文件缺失：查询正常，索引落盘后第二次查询不再重建。"""
        proot = _make_project_with_log(tmp_path, size_mb=0)
        dash_data._LOG_INDEX_REBUILDS["count"] = 0
        dash_data.get_recent_events(proot, minutes=10)
        idx_path = dash_data._log_index_path(proot)
        assert idx_path.exists(), "索引应落盘"
        assert dash_data._LOG_INDEX_REBUILDS["count"] == 1
        dash_data.get_recent_events(proot, minutes=10)
        assert dash_data._LOG_INDEX_REBUILDS["count"] == 1

    def test_out_of_window_truncation_no_error(self, tmp_path):
        """超窗截断：查询窗口起点早于索引范围 → 返回可得的记录，不抛错。"""
        proot = _make_project_with_log(tmp_path, size_mb=0)
        log = proot / ".fenix" / "logs" / "fenixd.log"
        events = dash_data.get_recent_events(proot, minutes=100000)
        assert isinstance(events, list)
        recent = dash_data.get_recent_events(proot, minutes=10)
        assert isinstance(recent, list)

    def test_spec_timeline_uses_tail_window(self, tmp_path):
        """get_spec_timeline 同样走尾部窗口，Transition 提取逻辑不变。"""
        proot = _make_project_with_log(tmp_path, size_mb=0)
        log = proot / ".fenix" / "logs" / "fenixd.log"
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": _now_iso(0),
                "message": "Transition: myspec ready → implementing",
            }) + "\n")
        timeline = dash_data.get_spec_timeline(proot, "myspec")
        states = [e for e in timeline if e.get("kind") == "state"]
        assert states, "应提取到 Transition 状态节点"
        assert any(e.get("to") == "implementing" for e in states)