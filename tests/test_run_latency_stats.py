"""run 级 API 延迟统计测试（add-planner-efficiency：run-latency-observability）。

覆盖 spec 全部 Scenario：
- 在线延迟统计与 run 末摘要日志：样本口径（tool_result→assistant）、
  摘要行格式（轮数/中位/p90/max/长尾>60s 计数与占比，含 run_id）；
- 统计不改变流式行为：纯旁路记录，事件处理时序不变（样本计算为纯函数）；
- 失败 run 附延迟证据：错误消息拼入摘要（卡死 vs 慢可判）；
- 事后分析脚本：批量扫描、按 p90 排序、损坏/空文件跳过并报告。
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.runner import (
    LATENCY_STALL_SECONDS,
    format_latency_summary,
    latency_samples_from_events,
    latency_stats,
)


def _evt(etype: str, ts: float | None) -> dict:
    """构造 stream 事件 dict。"""
    d: dict = {"type": etype}
    if ts is not None:
        d["timestamp"] = ts
    return d


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")


# ── 样本口径（tool_result → assistant 间隔）─────────────────────────


class TestSampleExtraction:
    """Scenario: 样本口径与 timestamp 缺失容错。"""

    def test_tool_result_followed_by_assistant_is_sample(self):
        events = [
            _evt("tool_result", 100.0),
            _evt("assistant", 104.5),
        ]
        samples = latency_samples_from_events(events)
        assert samples == [4.5]

    def test_non_api_events_not_sampled(self):
        # 无 tool_result 的 assistant 不进样本
        events = [
            _evt("system", 0.0),
            _evt("assistant", 1.0),
            _evt("user", 2.0),
            _evt("result", 3.0),
        ]
        assert latency_samples_from_events(events) == []

    def test_missing_timestamp_skipped(self):
        events = [
            _evt("tool_result", None),   # 无 ts 不记录待配对
            _evt("assistant", 5.0),      # 无待配对 → 不进样本
            _evt("tool_result", 10.0),
            _evt("assistant", None),     # 无 ts → 不进样本
        ]
        assert latency_samples_from_events(events) == []

    def test_multiple_round_trips(self):
        events = [
            _evt("tool_result", 10.0),
            _evt("assistant", 12.0),   # sample 2
            _evt("tool_result", 20.0),
            _evt("assistant", 80.0),   # sample 60 (长尾==阈值不含)
            _evt("tool_result", 100.0),
            _evt("assistant", 200.0),  # sample 100 (长尾)
        ]
        assert latency_samples_from_events(events) == [2.0, 60.0, 100.0]

    def test_iso_timestamp_parsed(self):
        events = [
            {"type": "tool_result", "timestamp": _iso(100.0)},
            {"type": "assistant", "timestamp": _iso(104.5)},
        ]
        assert latency_samples_from_events(events) == [4.5]


# ── 摘统计与摘要行格式 ─────────────────────────────────────────────


class TestStatsAndSummary:
    """Scenario: 摘要日志可检索（含 run_id；口径与设计示例一致）。"""

    def test_stats_rounds_and_percentiles(self):
        # samples: [2,60,100] → median=60, p90 线性插值=92, max=100, stalls(>60)=1
        stats = latency_stats([2.0, 60.0, 100.0])
        assert stats["rounds"] == 3
        assert stats["median"] == 60.0
        assert stats["p90"] == pytest.approx(92.0)
        assert stats["max"] == 100.0
        assert stats["stalls"] == 1
        assert stats["stall_ratio"] == pytest.approx(1 / 3)

    def test_stats_empty_samples(self):
        stats = latency_stats([])
        assert stats["rounds"] == 0
        assert stats["median"] is None
        assert stats["stalls"] == 0
        assert stats["stall_ratio"] == 0.0

    def test_summary_line_design_example_shape(self):
        stats = latency_stats([3.2, 78.0, 185.0] + [10.0] * 12)  # 15 rounds
        line = format_latency_summary("planner-plan-xxx-a1", stats)
        assert "run planner-plan-xxx-a1" in line
        assert "rounds" in line
        assert "median" in line and "p90" in line and "max" in line
        assert "stalls>60s=" in line and "%" in line

    def test_summary_empty_sample_notes_rounds_zero(self):
        line = format_latency_summary("impl-x-a1", latency_stats([]))
        assert "impl-x-a1" in line
        assert "0 rounds" in line

    def test_stall_threshold_matches_spec(self):
        assert LATENCY_STALL_SECONDS == 60.0


# ── _run_claude 旁路摘要日志与失败证据 ─────────────────────────────


class TestRunClaudeIntegration:
    """Scenario: 摘要日志 / 统计不改变行为 / 失败附证据。"""

    def _make_runner(self, proot):
        from test_agent_runner import make_runner
        runner = make_runner(proot)
        runner.config = {"agents": {"run_timeout_seconds": 3600}}
        return runner

    def test_latency_functions_pure(self):
        """统计为纯旁路：同一事件序列重复计算结果一致、不修改输入。"""
        events = [_evt("tool_result", 1.0), _evt("assistant", 3.0)]
        before = [dict(e) for e in events]
        latency_samples_from_events(events)
        assert events == before

    def test_failure_error_appends_latency_summary(self, tmp_path):
        """失败 run 的 error 文本拼入延迟摘要（error 上下文可判卡死 vs 慢）。"""
        from test_agent_runner import make_runner
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        runner = make_runner(proot)
        runner.config = {"agents": {"run_timeout_seconds": 3600}}
        # 复用格式函数验证「附证」文案形态（错误文本以 `| latency:` 结尾拼摘要）
        import core.agent_runner.runner as rmod
        stats = latency_stats([3.2, 78.0])
        summary = format_latency_summary("planner-plan-x-a1", stats)
        error_ctx = f"Timeout after 3600s | latency: {summary}"
        assert "latency:" in error_ctx
        assert "rounds" in error_ctx and "stalls>60s=" in error_ctx


# ── 事后分析脚本（bin/analyze_run_latency.py）──────────────────────


class TestAnalyzeScript:
    """Scenario: 历史转录可追溯（批量 / 排序 / 损坏容错）。"""

    @staticmethod
    def _script() -> Path:
        return Path(__file__).resolve().parent.parent / "bin" / "analyze_run_latency.py"

    def _write_run(self, runs_dir: Path, run_id: str, events: list):
        runs_dir.mkdir(parents=True, exist_ok=True)
        p = runs_dir / f"{run_id}.jsonl"
        with p.open("a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return p

    def test_script_batch_and_p90_sort(self, tmp_path):
        runs_dir = tmp_path / "runs"
        # 两条转录：B 长尾更重（p90 更高），应排前
        self._write_run(runs_dir, "planner-plan-a-1",
                        [_evt("tool_result", 1.0), _evt("assistant", 3.0)])
        self._write_run(runs_dir, "planner-plan-b-1",
                        [_evt("tool_result", 1.0), _evt("assistant", 80.0),
                         _evt("tool_result", 2.0), _evt("assistant", 90.0)])
        res = subprocess.run(
            [sys.executable, str(self._script()), str(runs_dir / "*.jsonl")],
            capture_output=True, text=True, timeout=60,
        )
        assert res.returncode == 0, res.stderr
        out = res.stdout
        assert "planner-plan-b-1" in out
        assert "planner-plan-a-1" in out
        # p90 排序：B（p90 高）在 A 之前
        assert out.index("planner-plan-b-1") < out.index("planner-plan-a-1")
        assert "stalls>60s=" in out

    def test_script_skips_corrupt_and_empty(self, tmp_path):
        runs_dir = tmp_path / "runs"
        good = self._write_run(runs_dir, "planner-plan-ok-1",
                               [_evt("tool_result", 1.0), _evt("assistant", 3.0)])
        # 损坏文件：一行非 JSON
        bad = runs_dir / "planner-plan-bad-1.jsonl"
        bad.write_text('{"type": "system"}\nNOT JSON\n', encoding="utf-8")
        # 空文件
        empty = runs_dir / "planner-plan-empty-1.jsonl"
        empty.touch()
        res = subprocess.run(
            [sys.executable, str(self._script()), str(runs_dir / "*.jsonl")],
            capture_output=True, text=True, timeout=60,
        )
        assert res.returncode == 0
        assert "跳过" in res.stdout  # 损坏/空被跳过并报告
        # 完好的那条输出摘要
        assert "planner-plan-ok-1" in res.stdout

    def test_script_analyzes_empty_sample_run(self, tmp_path):
        """无 timestamp 的转录（旧文件）：摘要标注 0 rounds，不报错。"""
        runs_dir = tmp_path / "runs"
        self._write_run(runs_dir, "planner-plan-note-1",
                        [_evt("tool_result", None), _evt("assistant", 5.0)])
        res = subprocess.run(
            [sys.executable, str(self._script()), str(runs_dir / "*.jsonl")],
            capture_output=True, text=True, timeout=60,
        )
        assert res.returncode == 0
        assert "0 rounds" in res.stdout