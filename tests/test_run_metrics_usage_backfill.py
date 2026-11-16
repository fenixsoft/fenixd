"""
tests/test_run_metrics_usage_backfill.py — evo-text-turn-inflation-response 3.1

网关逐消息零用量的终局回填（evo-text-turn-inflation-response 1.1）单测：
部分网关逐消息不回传 usage（assistant 事件 message.usage 恒零，逐消息累计
载体 total_input_tokens / total_cache_read_tokens 全零），真实用量仅在
result 终态事件（last_result.usage）。终态 run_metrics 落盘收尾块须从
last_result 回填既有计量键并落 usage_source 来源标注；转录行与同块日志
侧行两 sink 同源同值。

驱动形态对齐 test_run_latency_stats.TestRunClaudeIntegration：fake Popen
产 stream-json 事件行 → 驱动真实 _run_agent（rc!=0 抛 RuntimeError，
run_metrics 收尾块在 finally 照常执行——预期外异常会让 pytest.raises
落空，天然覆盖「不异常」断言）。
"""

import io
import json
import subprocess
import threading
from types import SimpleNamespace
from unittest import mock

import pytest


# ── 替身装置 ──────────────────────────────────────────────────────────────────

class _RecordingLogger:
    """记录 (kind, args, kwargs) 的替身 logger（形态对齐 test_run_latency_stats）。"""

    def __init__(self):
        self.records = []

    def _rec(self, kind, *args, **kwargs):
        self.records.append((kind, args, kwargs))

    def debug(self, *a, **k):
        self._rec("debug", *a, **k)

    def info(self, *a, **k):
        self._rec("info", *a, **k)

    def warning(self, *a, **k):
        self._rec("warning", *a, **k)

    def error(self, *a, **k):
        self._rec("error", *a, **k)


def _make_runner(proot):
    from test_agent_runner import make_runner

    runner = make_runner(proot)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}
    # 轮询环取消旗标所需最小实例状态（make_runner 跳过 __init__ 未初始化）
    runner._cancel_requested = set()
    runner._cancel_requested_lock = threading.Lock()
    runner._cancel_meta = {}
    runner.logger = _RecordingLogger()
    return runner


def _fake_subprocess(events, returncode=3):
    """Popen 替身：stdout 产出 stream-json 事件行，进程随即以 rc 退出。"""

    class _FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(
                "".join(json.dumps(e) + "\n" for e in events))
            self.stderr = io.StringIO("")
            # stdin-feed 线程写入通道（缺省缺失会让喂入线程 AttributeError）
            self.stdin = io.StringIO("")
            self.returncode = returncode
            self.pid = 4242

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            pass

        def kill(self):
            pass

    proc = _FakeProc()
    ns = SimpleNamespace(
        Popen=lambda *a, **k: proc,
        PIPE=subprocess.PIPE,
        TimeoutExpired=subprocess.TimeoutExpired,
    )
    return ns, proc


def _assistant_evt(usage):
    """assistant 事件（usage=None 表示 message 不携带 usage 键）。"""
    msg = {"role": "assistant",
           "content": [{"type": "text", "text": "hi"}]}
    if usage is not None:
        msg["usage"] = usage
    return {"type": "assistant", "message": msg}


def _result_evt(usage):
    """result 终态事件（usage=None 表示不携带 usage 键）。"""
    evt = {"type": "result", "subtype": "success", "result": "done",
           "num_turns": 2, "session_id": "sess-1"}
    if usage is not None:
        evt["usage"] = usage
    return evt


def _drive_run(runner, events, run_id):
    """驱动真实 _run_agent 至 rc=3 收尾；仅预期 CLI 失败的 RuntimeError。"""
    fake_ns, _proc = _fake_subprocess(events)
    import core.agent_runner.runner as rmod
    with mock.patch.object(rmod, "subprocess", fake_ns):
        with pytest.raises(RuntimeError):
            runner._run_agent("prompt", runner.project_root, run_id)


def _transcript_metrics_line(proot, run_id):
    """读 run 产物中恰好一条 run_metrics 转录行。"""
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    lines = [line for line in run_file.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    metrics = [json.loads(line) for line in lines
               if json.loads(line).get("type") == "run_metrics"]
    assert len(metrics) == 1, (
        f"应恰好一条 run_metrics 转录行，实得 {len(metrics)}")
    return metrics[0]


def _log_metrics_extras(runner):
    """摘取日志侧行（metric_type=run_metrics 的 info extra dict）。"""
    out = []
    for kind, args, _kw in runner.logger.records:
        if kind != "info":
            continue
        extra = args[2] if len(args) >= 3 else {}
        if isinstance(extra, dict) and extra.get("metric_type") == "run_metrics":
            out.append(extra)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# evo-text-turn-inflation-response 1.1：终态 run_metrics 用量回填
# ═════════════════════════════════════════════════════════════════════════════

class TestUsageBackfill:

    def test_all_zero_per_message_backfills_from_result(self, tmp_path):
        """① 逐消息全零 + result 有用量 → 回填 + 来源标注 + per_turn 重算。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        events = [
            _assistant_evt({"input_tokens": 0, "cache_read_input_tokens": 0}),
            _assistant_evt({"input_tokens": 0, "cache_read_input_tokens": 0}),
            _result_evt({"input_tokens": 12000, "cache_read_input_tokens": 3400,
                         "output_tokens": 500}),
        ]
        _drive_run(runner, events, "impl-backfill-1")

        line = _transcript_metrics_line(proot, "impl-backfill-1")
        assert line["input_tokens"] == 12000
        assert line["cache_read_input_tokens"] == 3400
        # 派生键由回填后 input 重算（12000 // 2 轮）
        assert line["turns"] == 2
        assert line["per_turn_input_tokens"] == 6000
        # 来源标注（与正常逐消息累计可区分）
        assert line["usage_source"] == "final_result_backfill"
        # context_peak_tokens 为逐轮峰值，run 末聚合不可回填：保持原值不臆造
        assert line["context_peak_tokens"] == 0

    def test_nonzero_per_message_not_overwritten(self, tmp_path):
        """② 逐消息累计非零 → 不覆盖、不落 usage_source（正常路径行为不变）。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        events = [
            _assistant_evt({"input_tokens": 100, "cache_read_input_tokens": 50}),
            _assistant_evt({"input_tokens": 100, "cache_read_input_tokens": 50}),
            _result_evt({"input_tokens": 999999, "cache_read_input_tokens": 888888}),
        ]
        _drive_run(runner, events, "impl-keep-1")

        line = _transcript_metrics_line(proot, "impl-keep-1")
        assert line["input_tokens"] == 200
        assert line["cache_read_input_tokens"] == 100
        assert line["per_turn_input_tokens"] == 100
        assert "usage_source" not in line

    def test_result_without_usage_stays_zero(self, tmp_path):
        """③ last_result 无 usage → 字段保持零、不落标注、收尾不异常。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        events = [
            _assistant_evt(None),
            _result_evt(None),
        ]
        _drive_run(runner, events, "impl-nousage-1")

        line = _transcript_metrics_line(proot, "impl-nousage-1")
        assert line["input_tokens"] == 0
        assert line["cache_read_input_tokens"] == 0
        assert line["per_turn_input_tokens"] == 0
        assert "usage_source" not in line

    def test_malformed_result_usage_stays_zero(self, tmp_path):
        """③b result.usage 畸形（非数值/非 dict）→ 字段级防御、保持零不异常。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        events = [
            _assistant_evt(None),
            _result_evt({"input_tokens": "garbage",
                         "cache_read_input_tokens": {"nested": 1}}),
        ]
        _drive_run(runner, events, "impl-malformed-1")

        line = _transcript_metrics_line(proot, "impl-malformed-1")
        assert line["input_tokens"] == 0
        assert line["cache_read_input_tokens"] == 0
        assert "usage_source" not in line

    def test_transcript_and_log_side_same_values(self, tmp_path):
        """④ 回填值在转录行与同块日志侧行两 sink 同源同值、两行均落标注。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        events = [
            _assistant_evt({"input_tokens": 0, "cache_read_input_tokens": 0}),
            _result_evt({"input_tokens": 9000, "cache_read_input_tokens": 300}),
        ]
        _drive_run(runner, events, "impl-samesink-1")

        line = _transcript_metrics_line(proot, "impl-samesink-1")
        log_lines = _log_metrics_extras(runner)
        assert len(log_lines) == 1, (
            f"应恰好一条日志侧 run_metrics 行，实得 {len(log_lines)}")
        log_extra = log_lines[0]
        for key in ("input_tokens", "cache_read_input_tokens",
                    "per_turn_input_tokens", "turns"):
            assert log_extra[key] == line[key], f"两 sink 的 {key} 应同值"
        # 两行均落 usage_source 来源标注
        assert line["usage_source"] == "final_result_backfill"
        assert log_extra["usage_source"] == "final_result_backfill"
