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


# ── 2.2 边界用例 ────────────────────────────────────────────────────────


class TestFallbackBoundaries:
    """在飞回退 / 降级留痕 / 跨窗单次入账 / attempt 后缀四个边界。"""

    def test_inflight_run_falls_back_to_start_and_running_bucket(self, tmp_path):
        """在飞 run（无 run_metrics 行）回退起点判据，仍入 running 桶（语义不变）。"""
        now = datetime.now().astimezone()
        root = tmp_path / "proj"
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        window_start = now - timedelta(hours=1)
        window_end = now + timedelta(minutes=5)
        start_ts = int(now.timestamp())
        rid = f"impl-inflight-{start_ts}"
        # 在飞形态：仅事件流前段，无 run_metrics/result 终态行
        _write_run(runs_dir, rid, [
            {"type": "system", "subtype": "init", "timestamp": _iso_utc(start_ts)},
            {"type": "user",
             "message": {"content": [{"type": "tool_result", "content": "r"}]},
             "timestamp": _iso_utc(start_ts)},
        ])
        assert _run_window_attr_ts(rid, runs_dir / f"{rid}.jsonl") == float(start_ts)
        stats = collect_runs_stats(root, window_start, window_end=window_end)
        assert stats["total"] == 1
        assert stats["running"] == 1

    def test_missing_duration_s_falls_back_with_debug_trace(self, tmp_path, caplog):
        """缺 duration_s / 占位 0 / 非数值 → 回退起点，留 debug 级降级痕迹。"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir(parents=True)
        start_ts = 1794000000
        p = _write_run(runs_dir, f"impl-nodur-{start_ts}",
                       _terminalize([], duration_s=None))
        with caplog.at_level(logging.DEBUG, logger="fenixd.self_review"):
            assert _run_window_attr_ts(p.stem, p) == float(start_ts)
        assert any(
            rec.levelno == logging.DEBUG and p.stem in rec.getMessage()
            for rec in caplog.records
        ), "缺 duration_s 应回退起点并留 debug 降级痕迹"
        # duration_s=0 是未收尾兜底行占位值，不构成终态证据，同样回退
        p0 = _write_run(runs_dir, f"impl-zdur-{start_ts}",
                        _terminalize([], duration_s=0))
        assert _run_metrics_duration_s(p0) is None
        assert _run_window_attr_ts(p0.stem, p0) == float(start_ts)
        # 非数值形态解析失败同样回退（不抛）
        pb = _write_run(runs_dir, f"impl-bdur-{start_ts}",
                        _terminalize([], duration_s="600"))
        assert _run_metrics_duration_s(pb) is None
        assert _run_window_attr_ts(pb.stem, pb) == float(start_ts)

    def test_cross_window_terminal_single_accounting(self, tmp_path):
        """跨窗终态单次入账：上窗不再按起点记在跑，本窗按终态入账一次。"""
        now = datetime.now().astimezone()
        root = tmp_path / "proj"
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        win_a = (now - timedelta(hours=2), now - timedelta(hours=1))
        win_b = (now - timedelta(hours=1), now + timedelta(minutes=5))
        start_ts = int(win_a[0].timestamp()) + 60  # 起点在上窗 A
        rid = f"impl-crosswin-{start_ts}"
        _write_run(runs_dir, rid,
                   _terminalize([{"type": "system", "subtype": "init",
                                  "timestamp": _iso_utc(start_ts)}],
                                duration_s=7200.0))  # 终态 = 起点 + 2h，落本窗 B
        stats_a = collect_runs_stats(root, win_a[0], window_end=win_a[1])
        stats_b = collect_runs_stats(root, win_b[0], window_end=win_b[1])
        assert stats_a["total"] == 0  # 终态键整 run 归本窗（上窗已按在跑可见的快照语义）
        assert stats_b["total"] == 1  # 终态入账恰一次，无双计
        assert stats_b["succeeded"] == 1

    def test_attempt_suffix_and_mtime_fallback_compat(self, tmp_path):
        """attempt 后缀（-a1/-r1 可叠加）剥离取内嵌起点；起点不可辨维持 mtime 回退。"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir(parents=True)
        start_ts = 1794000000
        p = _write_run(runs_dir, f"impl-att-{start_ts}-a1-r1",
                       _terminalize([], duration_s=120.5))
        assert _run_window_attr_ts(p.stem, p) == start_ts + 120.5
        # attempt 多段档案：末段最后一条 run_metrics 行胜出
        pm = _write_run(runs_dir, f"impl-multi-{start_ts}", [
            {"type": "run_metrics", "duration_s": 10.0},
            {"type": "run_metrics", "duration_s": 600.0},
            {"type": "result", "subtype": "success", "result": "done"},
        ])
        assert _run_metrics_duration_s(pm) == 600.0
        # 起点不可辨 → 既有 mtime 回退维持（透传免二次 stat）
        plegacy = _write_run(runs_dir, "legacy-run", _terminalize([], duration_s=30.0))
        assert _run_window_attr_ts("legacy-run", plegacy,
                                   mtime_s=1700000000) == 1700000000.0
        # 透传缺省（直调兼容）：自取产物 mtime
        assert _run_window_attr_ts("legacy-run", plegacy) == float(
            int(plegacy.stat().st_mtime))

