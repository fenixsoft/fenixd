"""self-review-window-snapshot 测试：聚合窗口上界固定快照。

对应 tasks：
- 2.1 tests/test_self_review_window_snapshot.py：构造窗口边界 run（恰在快照前/后创建），断言归属与聚合启动时刻一致
- 2.2 回归：聚合耗时场景下边界不漂移（mock now 两次调用返回不同值断言不受影响）

SPEC-B 批① aware UTC 迁移：时间接缝随迁——冻结点为模块级 ``now_utc``
（原模块级 datetime 类替换退役）；naive 本地替身值以 ``.astimezone()``
折算为同一瞬时的 aware 值，命中集合断言逐字不变。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

import core.self_review as csr
from core.self_review import (
    _in_window,
    collect_runs_stats,
    collect_log_errors,
)

# 固定快照「当下」：naive 本地 12:00 ↔ 同一瞬时 aware UTC 对偶值。
SNAP_NAIVE = datetime(2026, 9, 13, 12, 0, 0)
SNAP_UTC = SNAP_NAIVE.astimezone(timezone.utc)


class TestInWindowSnapshot:
    """测试 _in_window 的窗口快照化行为。"""

    def test_in_window_with_window_end(self):
        """测试 _in_window 使用指定的 window_end 参数。"""
        window_start = datetime(2026, 9, 13, 0, 0, 0).astimezone()
        window_end = datetime(2026, 9, 13, 12, 0, 0).astimezone()

        # 窗口内的点
        dt_in = datetime(2026, 9, 13, 10, 0, 0).astimezone()
        assert _in_window(dt_in, window_start, window_end) is True

        # 窗口外的点（在 window_end 之后）
        dt_out = datetime(2026, 9, 13, 14, 0, 0).astimezone()
        assert _in_window(dt_out, window_start, window_end) is False

        # 恰好在 window_end 上的点（闭区间）
        dt_on_end = window_end
        assert _in_window(dt_on_end, window_start, window_end) is True

    def test_in_window_without_window_end_uses_now(self):
        """测试 _in_window 未指定 window_end 时使用实时 now（now_utc 接缝）。"""
        window_start = datetime(2026, 9, 13, 0, 0, 0).astimezone()

        with mock.patch.object(csr, "now_utc", return_value=SNAP_UTC):
            # 窗口内的点
            dt_in = datetime(2026, 9, 13, 10, 0, 0).astimezone()
            assert _in_window(dt_in, window_start) is True

            # 窗口外的点（在 now 之后）
            dt_out = datetime(2026, 9, 13, 14, 0, 0).astimezone()
            assert _in_window(dt_out, window_start) is False

    def test_in_window_none_dt(self):
        """测试 _in_window 处理 None 输入。"""
        window_start = datetime(2026, 9, 13, 0, 0, 0).astimezone()
        window_end = datetime(2026, 9, 13, 12, 0, 0).astimezone()

        assert _in_window(None, window_start, window_end) is False


def _make_run(runs_dir: Path, local_dt: datetime, tag: str) -> str:
    """run_id 内嵌 epoch 起始时间戳（_run_start_ts 抽取约定）。"""
    rid = f"test-run-{tag}-{int(local_dt.timestamp())}"
    (runs_dir / f"{rid}.jsonl").write_text(
        json.dumps({"type": "result", "data": {}}), encoding="utf-8"
    )
    return rid


class TestCollectRunsStatsSnapshot:
    """测试 collect_runs_stats 的窗口快照化行为。"""

    def test_runs_stats_uses_snapshot_window_end(self, tmp_path):
        """测试 collect_runs_stats 使用快照化的 window_end。"""
        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)

        # run1: 在快照前创建（应该计入）；run2: 快照后（不应该计入）
        _make_run(runs_dir, datetime(2026, 9, 13, 10, 0, 0), "1")
        _make_run(runs_dir, datetime(2026, 9, 13, 14, 0, 0), "2")

        window_start = datetime(2026, 9, 13, 0, 0, 0).astimezone()

        with mock.patch.object(csr, "now_utc", return_value=SNAP_UTC):
            stats = collect_runs_stats(tmp_path, window_start)

        assert stats["total"] == 1
        assert stats["succeeded"] == 1

    def test_runs_stats_during_long_running_aggregation(self, tmp_path):
        """测试长聚合期间窗口边界不漂移。"""
        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)

        _make_run(runs_dir, datetime(2026, 9, 13, 10, 0, 0), "1")

        window_start = datetime(2026, 9, 13, 0, 0, 0).astimezone()

        # 模拟长聚合：多次 now_utc() 调用返回不同值（聚合期间时间流逝）
        first_now = datetime(2026, 9, 13, 12, 0, 0).astimezone(timezone.utc)
        second_now = datetime(2026, 9, 13, 14, 0, 0).astimezone(timezone.utc)

        calls = {"n": 0}

        def _drifting_now():
            calls["n"] += 1
            return first_now if calls["n"] == 1 else second_now

        with mock.patch.object(csr, "now_utc", side_effect=_drifting_now):
            stats = collect_runs_stats(tmp_path, window_start)

        # 应该只计入 run1，尽管聚合期间 now 发生了变化
        assert stats["total"] == 1
        assert stats["succeeded"] == 1


class TestCollectLogErrorsSnapshot:
    """测试 collect_log_errors 的窗口快照化行为。"""

    def _write_log(self, log_file: Path, entries):
        log_file.write_text(
            "\n".join(
                json.dumps(
                    {
                        "timestamp": ts.isoformat(),
                        "level": "ERROR",
                        "component": "test",
                        "message": msg,
                    },
                    ensure_ascii=False,
                )
                for ts, msg in entries
            )
            + "\n",
            encoding="utf-8",
        )

    def test_log_errors_uses_snapshot_window_end(self, tmp_path):
        """测试 collect_log_errors 使用快照化的 window_end。"""
        logs_dir = tmp_path / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "fenixd.log"

        # log1: 快照前（应该计入）；log2: 快照后（不应该计入）
        self._write_log(
            log_file,
            [
                (datetime(2026, 9, 13, 10, 0, 0), "error 1"),
                (datetime(2026, 9, 13, 14, 0, 0), "error 2"),
            ],
        )

        window_start = datetime(2026, 9, 13, 0, 0, 0).astimezone()

        with mock.patch.object(csr, "now_utc", return_value=SNAP_UTC):
            result = collect_log_errors(tmp_path, window_start)

        # 应该只计入 log1（在快照前），不计入 log2（在快照后）
        assert result["error_count"] == 1
        assert len(result["samples"]) == 1
        assert "error 1" in result["samples"][0]

    def test_log_errors_during_long_running_aggregation(self, tmp_path):
        """测试长聚合期间窗口边界不漂移。"""
        logs_dir = tmp_path / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "fenixd.log"

        self._write_log(log_file, [(datetime(2026, 9, 13, 10, 0, 0), "error 1")])

        window_start = datetime(2026, 9, 13, 0, 0, 0).astimezone()

        first_now = datetime(2026, 9, 13, 12, 0, 0).astimezone(timezone.utc)
        second_now = datetime(2026, 9, 13, 14, 0, 0).astimezone(timezone.utc)

        calls = {"n": 0}

        def _drifting_now():
            calls["n"] += 1
            return first_now if calls["n"] == 1 else second_now

        with mock.patch.object(csr, "now_utc", side_effect=_drifting_now):
            result = collect_log_errors(tmp_path, window_start)

        assert result["error_count"] == 1
        assert len(result["samples"]) == 1
        assert "error 1" in result["samples"][0]
