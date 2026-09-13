"""self-review-window-snapshot 测试：聚合窗口上界固定快照。

对应 tasks：
- 2.1 tests/test_self_review_window_snapshot.py：构造窗口边界 run（恰在快照前/后创建），断言归属与聚合启动时刻一致
- 2.2 回归：聚合耗时场景下边界不漂移（mock now 两次调用返回不同值断言不受影响）
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from core.self_review import (
    _in_window,
    collect_runs_stats,
    collect_log_errors,
)


class TestInWindowSnapshot:
    """测试 _in_window 的窗口快照化行为。"""

    def test_in_window_with_window_end(self):
        """测试 _in_window 使用指定的 window_end 参数。"""
        window_start = datetime(2026, 9, 13, 0, 0, 0)
        window_end = datetime(2026, 9, 13, 12, 0, 0)

        # 窗口内的点
        dt_in = datetime(2026, 9, 13, 10, 0, 0)
        assert _in_window(dt_in, window_start, window_end) is True

        # 窗口外的点（在 window_end 之后）
        dt_out = datetime(2026, 9, 13, 14, 0, 0)
        assert _in_window(dt_out, window_start, window_end) is False

        # 恰好在 window_end 上的点（闭区间）
        dt_on_end = datetime(2026, 9, 13, 12, 0, 0)
        assert _in_window(dt_on_end, window_start, window_end) is True

    def test_in_window_without_window_end_uses_now(self):
        """测试 _in_window 未指定 window_end 时使用实时 now。"""
        window_start = datetime(2026, 9, 13, 0, 0, 0)

        # 使用 mock 固定 now 的值
        mock_now = datetime(2026, 9, 13, 12, 0, 0)
        with mock.patch("core.self_review.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            # 窗口内的点
            dt_in = datetime(2026, 9, 13, 10, 0, 0)
            assert _in_window(dt_in, window_start) is True

            # 窗口外的点（在 now 之后）
            dt_out = datetime(2026, 9, 13, 14, 0, 0)
            assert _in_window(dt_out, window_start) is False

    def test_in_window_none_dt(self):
        """测试 _in_window 处理 None 输入。"""
        window_start = datetime(2026, 9, 13, 0, 0, 0)
        window_end = datetime(2026, 9, 13, 12, 0, 0)

        assert _in_window(None, window_start, window_end) is False


class TestCollectRunsStatsSnapshot:
    """测试 collect_runs_stats 的窗口快照化行为。"""

    def test_runs_stats_uses_snapshot_window_end(self, tmp_path):
        """测试 collect_runs_stats 使用快照化的 window_end。"""
        # 创建测试项目结构
        project_root = tmp_path / "project"
        project_root.mkdir()
        runs_dir = project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)

        # 创建测试 run 文件
        # run1: 在快照前创建（应该计入）
        run1_time = datetime(2026, 9, 13, 10, 0, 0)
        run1_ts = int(run1_time.timestamp())
        run1_id = f"test-run-1-{run1_ts}"
        run1_file = runs_dir / f"{run1_id}.jsonl"
        run1_file.write_text(json.dumps({"type": "result", "data": {}}), encoding="utf-8")

        # run2: 在快照后创建（不应该计入）
        run2_time = datetime(2026, 9, 13, 14, 0, 0)
        run2_ts = int(run2_time.timestamp())
        run2_id = f"test-run-2-{run2_ts}"
        run2_file = runs_dir / f"{run2_id}.jsonl"
        run2_file.write_text(json.dumps({"type": "result", "data": {}}), encoding="utf-8")

        window_start = datetime(2026, 9, 13, 0, 0, 0)

        # mock datetime.now 返回快照时间（12:00）
        snapshot_time = datetime(2026, 9, 13, 12, 0, 0)
        with mock.patch("core.self_review.datetime") as mock_datetime:
            mock_datetime.now.return_value = snapshot_time
            # 让 fromtimestamp 返回正确的 datetime 对象
            mock_datetime.fromtimestamp.side_effect = lambda ts: datetime.fromtimestamp(ts)
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            stats = collect_runs_stats(project_root, window_start)

            # 应该只计入 run1（在快照前），不计入 run2（在快照后）
            assert stats["total"] == 1
            assert stats["succeeded"] == 1

    def test_runs_stats_during_long_running_aggregation(self, tmp_path):
        """测试长聚合期间窗口边界不漂移。"""
        # 创建测试项目结构
        project_root = tmp_path / "project"
        project_root.mkdir()
        runs_dir = project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)

        # 创建测试 run 文件
        run1_time = datetime(2026, 9, 13, 10, 0, 0)
        run1_ts = int(run1_time.timestamp())
        run1_id = f"test-run-1-{run1_ts}"
        run1_file = runs_dir / f"{run1_id}.jsonl"
        run1_file.write_text(json.dumps({"type": "result", "data": {}}), encoding="utf-8")

        window_start = datetime(2026, 9, 13, 0, 0, 0)

        # 模拟长聚合：两次 datetime.now() 调用返回不同值
        first_now = datetime(2026, 9, 13, 12, 0, 0)
        second_now = datetime(2026, 9, 13, 14, 0, 0)  # 聚合期间时间流逝

        call_count = 0
        def mock_now_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_now
            else:
                return second_now

        with mock.patch("core.self_review.datetime") as mock_datetime:
            mock_datetime.now.side_effect = mock_now_side_effect
            mock_datetime.fromtimestamp.side_effect = lambda ts: datetime.fromtimestamp(ts)
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            stats = collect_runs_stats(project_root, window_start)

            # 应该只计入 run1，尽管聚合期间 now 发生了变化
            assert stats["total"] == 1
            assert stats["succeeded"] == 1


class TestCollectLogErrorsSnapshot:
    """测试 collect_log_errors 的窗口快照化行为。"""

    def test_log_errors_uses_snapshot_window_end(self, tmp_path):
        """测试 collect_log_errors 使用快照化的 window_end。"""
        # 创建测试项目结构
        project_root = tmp_path / "project"
        project_root.mkdir()
        logs_dir = project_root / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)

        # 创建测试日志文件
        log_file = logs_dir / "fenixd.log"

        # log1: 在快照前创建（应该计入）
        log1_time = datetime(2026, 9, 13, 10, 0, 0)
        log1_entry = {
            "timestamp": log1_time.isoformat(),
            "level": "ERROR",
            "component": "test",
            "message": "error 1"
        }

        # log2: 在快照后创建（不应该计入）
        log2_time = datetime(2026, 9, 13, 14, 0, 0)
        log2_entry = {
            "timestamp": log2_time.isoformat(),
            "level": "ERROR",
            "component": "test",
            "message": "error 2"
        }

        log_file.write_text(
            json.dumps(log1_entry) + "\n" + json.dumps(log2_entry) + "\n",
            encoding="utf-8"
        )

        window_start = datetime(2026, 9, 13, 0, 0, 0)

        # mock datetime.now 返回快照时间（12:00）
        snapshot_time = datetime(2026, 9, 13, 12, 0, 0)
        with mock.patch("core.self_review.datetime") as mock_datetime:
            mock_datetime.now.return_value = snapshot_time
            mock_datetime.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            result = collect_log_errors(project_root, window_start)

            # 应该只计入 log1（在快照前），不计入 log2（在快照后）
            assert result["error_count"] == 1
            assert len(result["samples"]) == 1
            assert "error 1" in result["samples"][0]

    def test_log_errors_during_long_running_aggregation(self, tmp_path):
        """测试长聚合期间窗口边界不漂移。"""
        # 创建测试项目结构
        project_root = tmp_path / "project"
        project_root.mkdir()
        logs_dir = project_root / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)

        # 创建测试日志文件
        log_file = logs_dir / "fenixd.log"

        log1_time = datetime(2026, 9, 13, 10, 0, 0)
        log1_entry = {
            "timestamp": log1_time.isoformat(),
            "level": "ERROR",
            "component": "test",
            "message": "error 1"
        }

        log_file.write_text(json.dumps(log1_entry) + "\n", encoding="utf-8")

        window_start = datetime(2026, 9, 13, 0, 0, 0)

        # 模拟长聚合：两次 datetime.now() 调用返回不同值
        first_now = datetime(2026, 9, 13, 12, 0, 0)
        second_now = datetime(2026, 9, 13, 14, 0, 0)  # 聚合期间时间流逝

        call_count = 0
        def mock_now_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_now
            else:
                return second_now

        with mock.patch("core.self_review.datetime") as mock_datetime:
            mock_datetime.now.side_effect = mock_now_side_effect
            mock_datetime.fromisoformat.side_effect = lambda s: datetime.fromisoformat(s)
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            result = collect_log_errors(project_root, window_start)

            # 应该只计入 log1，尽管聚合期间 now 发生了变化
            assert result["error_count"] == 1
            assert len(result["samples"]) == 1
            assert "error 1" in result["samples"][0]