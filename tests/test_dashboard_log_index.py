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

    def test_spec_timeline_reads_log(self, tmp_path):
        """get_spec_timeline 能提取 Transition 状态节点（读取语义不变）。"""
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

    @staticmethod
    def _write_line(f, ts: str, message: str, pad: int = 0):
        f.write(json.dumps({
            "timestamp": ts,
            "level": "INFO",
            "component": "pm_engine",
            "message": message + "y" * pad,
        }, ensure_ascii=False) + "\n")

    def test_spec_timeline_created_anchor_beyond_tail_window(self, tmp_path):
        """created 锚定：>1MB 日志中尾窗外的早期 Transition 仍可提取。

        回归场景：长周期 spec 的早期派发/报错事件落在尾部 1MB 尾窗之外，
        旧实现静默截断（dashboard 时间轴只剩收尾几条）。
        """
        proot = _make_project_with_log(tmp_path, size_mb=0)
        log = proot / ".fenix" / "logs" / "fenixd.log"
        early_ts = "2026-09-07T08:09:28.000000Z"
        with log.open("a", encoding="utf-8") as f:
            # 早期 Transition 在前，随后 >1MB 填充把其推出尾窗
            self._write_line(f, early_ts, "Transition: myspec ready → implementing")
            written = 0
            idx = 0
            while written < 1.2 * 1024 * 1024:
                entry = json.dumps({
                    "timestamp": "2026-09-08T00:00:00.000000Z",
                    "level": "INFO",
                    "component": "pm_engine",
                    "message": f"filler-{idx}-" + "x" * 1024,
                }, ensure_ascii=False) + "\n"
                f.write(entry)
                written += len(entry.encode("utf-8"))
                idx += 1
        timeline = dash_data.get_spec_timeline(
            proot, "myspec", created="2026-09-07T08:08:27.000000+00:00")
        states = [e for e in timeline if e.get("kind") == "state"]
        assert any(
            e.get("from") == "ready" and e.get("to") == "implementing"
            for e in states), "尾窗外的早期 Transition 应经 created 锚定窗口提取到"

    def test_spec_timeline_created_anchor_excludes_early_events(self, tmp_path):
        """created 锚定生效：锚点早于的事件不进入时间轴，锚点后事件保留。"""
        proot = _make_project_with_log(tmp_path, size_mb=0)
        log = proot / ".fenix" / "logs" / "fenixd.log"
        with log.open("a", encoding="utf-8") as f:
            self._write_line(f, "2026-09-07T08:09:28.000000Z",
                             "Transition: myspec ready → implementing")
            self._write_line(f, "2026-09-07T09:00:00.000000Z",
                             "Transition: myspec implementing → implemented")
        # 锚点介于两条之间：首条被排除，第二条保留
        timeline = dash_data.get_spec_timeline(
            proot, "myspec", created="2026-09-07T08:30:00.000000+00:00")
        states = [e for e in timeline if e.get("kind") == "state"]
        assert not any(e.get("to") == "implementing" for e in states)
        assert any(e.get("to") == "implemented" for e in states)


# ── improve-spec-topology-pipeline-view 1.6：首行巨型行日志读侧防御 ──────────

_GIANT_BYTES = 6600 * 1024  # 实测样本：fenixd.log 首行 admin_monitor 巨型行 6.6MB


def _iso(epoch: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _make_giant_first_line_log(tmp_path) -> tuple:
    """首行 6.6MB 巨型行 + 其后 3 条常规事件（含可解析 Transition 行）。"""
    proot = tmp_path / "proj-giant"
    (proot / ".fenix" / "logs").mkdir(parents=True)
    log = proot / ".fenix" / "logs" / "fenixd.log"
    giant_ts = _iso(1792938331)
    with log.open("wb") as f:
        f.write(json.dumps({
            "timestamp": giant_ts,
            "level": "INFO",
            "component": "admin_monitor",
            "message": "signal",
            "context": {"blob": "x" * _GIANT_BYTES},
        }, ensure_ascii=False).encode("utf-8") + b"\n")
        for i in range(1, 4):
            f.write(json.dumps({
                "timestamp": _iso(1792938331 + i),
                "message": f"Transition: demo drafted → reviewing #{i}",
            }, ensure_ascii=False).encode("utf-8") + b"\n")
    return proot, log, giant_ts


class _MaxReadProbe:
    """包装文件对象：累计 read 总字节 + 单次 read 最大字节数。"""

    def __init__(self, underlying, stats):
        self._u = underlying
        self._s = stats

    def read(self, *a, **kw):
        data = self._u.read(*a, **kw)
        self._s["total"] += len(data)
        self._s["max_single"] = max(self._s["max_single"], len(data))
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


def _probe_log_reads(log_path: Path, fn):
    """运行 fn 期间统计日志文件 read 总字节与单次最大 read 字节。"""
    stats = {"total": 0, "max_single": 0}
    orig_open = Path.open

    def patched_open(self, *a, **kw):
        f = orig_open(self, *a, **kw)
        if str(self) == str(log_path):
            return _MaxReadProbe(f, stats)
        return f

    import pathlib
    monkey = pytest.MonkeyPatch()
    monkey.setattr(pathlib.Path, "open", patched_open)
    try:
        result = fn()
    finally:
        monkey.undo()
    return result, stats


class TestGiantFirstLineDefense:
    def test_anchor_after_giant_line_reads_parseable_events(self, tmp_path):
        """created 锚点在巨型行后：窗口含锚点后可解析事件（transitions 可派生）。"""
        proot, log, giant_ts = _make_giant_first_line_log(tmp_path)
        assert log.stat().st_size > _GIANT_BYTES
        # 建索引（一次性全量扫描不计入窗口读取统计）
        dash_data.read_log_window_from(proot, log, "")
        anchor_ts = _iso(1792938331 + 1)
        w = dash_data.read_log_window_from(proot, log, anchor_ts)
        content = w.decode("utf-8", errors="replace")
        events = [json.loads(line) for line in content.split("\n") if line.strip()]
        assert events, "锚点后可解析事件 MUST 不因巨型行丢失"
        assert any(f"#{3}" in e["message"] for e in events)
        # 事件时刻全部 ≥ 锚点（巨型行及其后残余不混入）
        assert all(e["timestamp"] >= anchor_ts for e in events)
        # 拓扑派生链路：_scan_spec_log_events 可派生该 SPEC 的状态转移
        from core.dashboard.data.topology import _scan_spec_log_events

        transitions, _ = _scan_spec_log_events(proot, "demo", giant_ts)
        assert len(transitions) == 3, "transitions MUST NOT 因单个巨型行整体为空"
        assert all(t["to"] == "reviewing" for t in transitions)

    def test_giant_line_content_not_read_wholesale(self, tmp_path):
        """超长行内容不整读入内存：单次 read 字节数有界（不以窗口上限整读）。"""
        proot, log, _ = _make_giant_first_line_log(tmp_path)
        dash_data.read_log_window_from(proot, log, "")  # 建索引
        _, stats = _probe_log_reads(
            log, lambda: dash_data.read_log_window_from(proot, log, _iso(1792938331 + 1))
        )
        # 旧实现单次 read 整窗（1MB）；新实现分块扫描 + 逐行读取，单次 read
        # 字节数 ≤ 阈值常量 + 块扫描窗，绝不出现一次性读入巨型行的单请求
        bound = dash_data.LOG_LINE_SKIP_THRESHOLD + dash_data.LOG_INDEX_BLOCK + 4096
        assert stats["max_single"] <= bound, (
            f"单次 read {stats['max_single']} 字节超界（{bound}）：巨型行被整读"
        )
        # 总字节有界：定位巨型行行界必须以 64KB 探测窗顺序扫描其字节（锚点
        # 探测 + 窗口起点跳过各一遍，最坏 2 遍），内存峰值受单次 read 上限
        # 约束——断言防整读与读放大，不断言零扫描（扫描是定位行界的必要 IO）。
        assert stats["total"] < 3 * _GIANT_BYTES, (
            f"窗口读取总字节 {stats['total']} 超界：读放大超出分块扫描上界"
        )

    def test_regular_log_window_identical_to_raw_read(self, tmp_path):
        """常规日志（无超长行）：窗口起点/终点/截断标记与整读实现一致。"""
        proot = _make_project_with_log(tmp_path, size_mb=0)
        log = proot / ".fenix" / "logs" / "fenixd.log"
        with log.open("a", encoding="utf-8") as f:
            for i in range(1, 8):
                f.write(json.dumps({
                    "timestamp": _iso(1792938330 + i),
                    "message": f"event-{i}",
                }) + "\n")
        size = log.stat().st_size
        dash_data.read_log_window_from(proot, log, "")  # 建索引
        # 锚定窗口（锚点在首事件前 → 从文件头读至窗口上限）
        w = dash_data.read_log_window_from(proot, log, _iso(1792938300))
        raw = log.read_bytes()
        expect_end = min(size, dash_data.LOG_INDEX_ANCHOR_WINDOW)
        assert w == raw[:expect_end], "常规日志窗口内容应与整读逐字节一致"
        assert w.truncated == (expect_end < size)
        # 锚点晚于全部事件 → 二分定位 + 窗口内容仍为行对齐字节区间
        w2 = dash_data.read_log_window_from(proot, log, _iso(1792938400))
        assert w2 == raw, "全事件早于锚点：窗口应覆盖整个小文件"
        assert w2.truncated is False

    def test_giant_line_only_log_degrades_empty_without_error(self, tmp_path):
        """巨型行直达 EOF（无后续行）：窗口退化为空，不抛错不误读行中偏移。"""
        proot = tmp_path / "proj-only-giant"
        (proot / ".fenix" / "logs").mkdir(parents=True)
        log = proot / ".fenix" / "logs" / "fenixd.log"
        with log.open("wb") as f:
            f.write(json.dumps({
                "timestamp": _iso(1792938331),
                "message": "giant to eof",
                "context": {"blob": "x" * (_GIANT_BYTES)},
            }).encode("utf-8"))  # 无行尾 \n
        w = dash_data.read_log_window_from(proot, log, _iso(1792938400))
        assert w == b""
        assert w.truncated is False