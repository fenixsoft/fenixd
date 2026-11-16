"""自省窗口终态归属测试（evo-self-review-window-terminal-attribution）。

对应 spec 全部 Scenario：
- 跨缝 run（起点早于窗口起点、终态深入窗内）：停滞聚合与 runs 统计两节均
  计入本窗（2.1）；
- 在飞 run（无 run_metrics 行）回退起点入 running 桶、缺 duration_s 回退
  起点留 debug 降级痕迹、跨窗终态单次入账、attempt 后缀 run id 兼容（2.2）；
- 存量窗口用例零回归由 tests/test_api_stall_signal_grading.py 与
  tests/test_self_review_window_snapshot.py 承载（2.3 回归入口，本文件不重
  复其断言）。

fixture 形态参照 tests/test_api_stall_signal_grading.py 的 _write_run/
_stall_events（真实 user 包裹、逐事件 timestamp、run_id 内嵌 epoch 控制窗口
归属），终态行按 runner 收尾契约补齐 [assistant, run_metrics, result]（先
指标行后终态行，core/agent_runner/runner.py 落盘序）。
"""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.self_review as sr
from core.self_review import (
    _collect_api_stall_aggregates,
    _run_metrics_duration_s,
    _run_window_attr_ts,
    collect_runs_stats,
)


# ── 夹具工具 ────────────────────────────────────────────────────────────


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _write_run(runs_dir: Path, run_id: str, events) -> Path:
    p = runs_dir / f"{run_id}.jsonl"
    p.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8")
    return p


def _stall_events(base_ts: float, gaps) -> list:
    """按给定往返间隔序列构造 stream-json 事件（真实 user 包裹形态）。"""
    events = [{"type": "system", "subtype": "init", "timestamp": _iso_utc(base_ts)}]
    ts = base_ts
    for gap in gaps:
        events.append({
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "r"}]},
            "timestamp": _iso_utc(ts),
        })
        ts += gap
        events.append({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "a"}]},
            "timestamp": _iso_utc(ts),
        })
        ts += 1
    return events


def _terminalize(events, duration_s, result_text="done"):
    """按 runner 收尾契约追加终态行：run_metrics（先落）+ result（后落）。

    duration_s=None 构造缺字段形态（降级出题）；其余值原样入行。
    """
    metrics = {"type": "run_metrics", "turns": 3}
    if duration_s is not None:
        metrics["duration_s"] = duration_s
    return events + [
        metrics,
        {"type": "result", "subtype": "success", "result": result_text},
    ]


# ── 2.1 跨缝 run 终态归属 ───────────────────────────────────────────────


class TestCrossSeamTerminalAttribution:
    """跨缝 run（起点早于窗口起点、终态深入窗内）归本窗。

    缝隙形态：夜间全仓审查与自省同一巡检固定先审查后自省、两车道 run_at
    同为 00:00，审查 run 起点亚秒级早于窗口锚点——起点键整只漏计（11-14/
    15/16 三晚实测）。run_id 内嵌 epoch 为秒粒度，亚秒缝隙在判据侧同构表现
    为「起点秒早于窗口起点秒」，夹具以 1 秒缝隙出题。
    """

    def test_cross_seam_run_in_stall_aggregation_and_runs_stats(self, tmp_path):
        now = datetime.now().astimezone()
        root = tmp_path / "proj"
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        window_start = now - timedelta(hours=1)
        window_end = now + timedelta(minutes=5)
        start_ts = int(window_start.timestamp()) - 1
        rid = f"impl-seam-{start_ts}"
        _write_run(runs_dir, rid,
                   _terminalize(_stall_events(float(start_ts), [100.0, 70.0]),
                                duration_s=600.0))
        # 前提：起点判据下该 run 不在本窗（改造前整只漏计形态复现）
        assert sr._in_window(sr.from_epoch(start_ts), window_start, window_end) is False
        # 终态时刻 = 内嵌起点 + run_metrics duration_s，深入窗内
        assert _run_window_attr_ts(rid, runs_dir / f"{rid}.jsonl") == start_ts + 600.0
        # 停滞聚合节计入本窗
        agg = _collect_api_stall_aggregates(root, window_start, window_end)
        assert [r["run_id"] for r in agg] == [rid]
        assert agg[0]["stalls"] == 2
        assert agg[0]["total_stall_seconds"] == pytest.approx(170.0)
        assert agg[0]["max_stall_seconds"] == pytest.approx(100.0)
        # runs 统计节计入本窗（同一归属键，口径不分叉）
        stats = collect_runs_stats(root, window_start, window_end=window_end)
        assert stats["total"] == 1
        assert stats["succeeded"] == 1
