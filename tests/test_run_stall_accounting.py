"""run 停滞指标随 run_metrics 入账测试（evo-add-api-stall-observability 2.2）。

覆盖 1.3 三处落点：
- 档案 run_metrics 行（``append_run_line`` 的 ``type: run_metrics``）新增
  ``latency_rounds`` / ``latency_stalls`` / ``latency_max``，取值与预期
  stall 统计一致、仍恰一条且位于终态行之后（崩溃口径契约，
  ``tests/test_daemon_lifecycle_races.py::
  test_run_claude_poll_loop_crash_writes_error_terminal`` 同款），既有
  字段不动；
- daemon 侧 run metrics 结构化日志（``_run_claude`` 正常收尾内联形态，
  ``metric_type: run_metrics``，不经过 ``_log_run_metrics``）context 含
  同名字段同值（复用同一 stats 结果）；
- 零样本 run 字段回退 0/None 不抛；
- 轮询环崩溃路径 run_metrics 行照常追加、字段缺省不抛。

装配参照 ``test_daemon_lifecycle_races`` 的 ``_run_claude`` 假 Popen：
带样本用例走真实读线程（StringIO 产 stream-json 事件行），崩溃口径用例
按权威测试同款 patch ``threading.Thread``。
"""

import io
import json
import subprocess
import sys
import threading
import unittest.mock
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.agent_runner.runner as rmod
from core.agent_runner.runner import AgentRunner


class _CaptureLogger:
    """记录型 logger：捕获 info/warning 调用（断言 daemon 侧日志 context）。"""

    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.records.append(("info", a, k))

    def warning(self, *a, **k):
        self.records.append(("warning", a, k))

    def error(self, *a, **k):
        self.records.append(("error", a, k))


def _make_runner(proot: Path, logger: _CaptureLogger) -> AgentRunner:
    """最小 AgentRunner 装配（test_run_latency_stats 同款，换记录型 logger）。"""
    from test_agent_runner import make_runner
    runner = make_runner(proot)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}
    runner._cancel_requested = set()
    runner._cancel_requested_lock = threading.Lock()
    runner._cancel_meta = {}
    runner.logger = logger
    return runner


class _FakeProc:
    """Popen 替身：stdout 产出 stream-json 事件行；poll 行为可注入。"""

    def __init__(self, events, returncode=3, poll_error=None):
        self.stdout = io.StringIO(
            "".join(json.dumps(e) + "\n" for e in events))
        self.stderr = io.StringIO("")
        self.stdin = io.StringIO("")
        self.returncode = returncode
        self.pid = 4242
        self._poll_error = poll_error

    def poll(self):
        if self._poll_error is not None:
            raise self._poll_error
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        pass

    def kill(self):
        pass


def _patched_popen(proc: _FakeProc):
    """把 runner 模块视角的 subprocess.Popen 换成替身。"""
    ns = SimpleNamespace(
        Popen=lambda *a, **k: proc,
        PIPE=subprocess.PIPE,
        TimeoutExpired=subprocess.TimeoutExpired,
    )
    return unittest.mock.patch.object(rmod, "subprocess", ns)


def _read_lines(run_file: Path) -> list:
    return [json.loads(l) for l in
            run_file.read_text(encoding="utf-8").splitlines() if l.strip()]


def _run_metrics_contexts(logger: _CaptureLogger) -> list:
    """提取 daemon 侧 metric_type=run_metrics 结构化日志的 context。"""
    return [
        a[2] for (kind, a, _k) in logger.records
        if kind == "info" and len(a) >= 3 and isinstance(a[2], dict)
        and a[2].get("metric_type") == "run_metrics"
    ]


def _no_thread_factory(*args, **kwargs):
    """读线程替身工厂：不真正起线程（崩溃口径用例，stdout 为 MagicMock）。"""
    return MagicMock()


STALL_EVENTS = [
    {"type": "tool_result", "timestamp": 0.0},
    {"type": "assistant", "timestamp": 3.0},      # 3.0s
    {"type": "tool_result", "timestamp": 10.0},
    {"type": "assistant", "timestamp": 129.9},    # 119.9s（≤告警线，>60s 计 stall）
    {"type": "tool_result", "timestamp": 200.0},
    {"type": "assistant", "timestamp": 451.1},    # 251.1s（最长样本）
]
# 预期 stats：rounds=3, stalls(>60)=2（119.9 与 251.1 均超统计口径 60s，
# 其中仅 251.1 超期内告警线 120s）, max=251.1


class TestStallMetricsAccounting:
    """Scenario: 有停滞样本的 run 两处落点均含字段 / 零样本回退 / 崩溃路径。"""

    def test_stall_run_metrics_line_fields(self, tmp_path):
        """带停滞样本的 run 收尾后档案 run_metrics 行含三字段且与预期
        stall 统计一致、仍恰一条且位于终态行之后；daemon 侧内联日志
        context 同名字段同值。"""
        proot = tmp_path / "proj"
        logger = _CaptureLogger()
        runner = _make_runner(proot, logger)
        run_id = "impl-stall-acc-1"
        # poll 首调即崩（崩溃口径）——finally 仍 join 真实读线程收全样本，
        # run_metrics 行按权威契约落在 error 终态行之后
        proc = _FakeProc(STALL_EVENTS, poll_error=TypeError("boom-poll"))
        with _patched_popen(proc):
            with pytest.raises(TypeError):
                runner._run_claude("prompt", proot, run_id)
        run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
        lines = _read_lines(run_file)
        # 恰一条 error 终态行 + 恰一条 run_metrics 行，且在终态行之后
        terminal = [l for l in lines if l.get("type") == "error"]
        metrics = [l for l in lines if l.get("type") == "run_metrics"]
        assert len(terminal) == 1, f"应恰一条 error 终态行；lines={lines}"
        assert len(metrics) == 1, f"应恰一条 run_metrics 行；lines={lines}"
        assert lines.index(terminal[0]) < lines.index(metrics[0])
        m = metrics[0]
        # 新字段与预期 stall 统计一致（rounds=3 / stalls=2 / max=251.1）
        assert m["latency_rounds"] == 3
        assert m["latency_stalls"] == 2
        assert m["latency_max"] == pytest.approx(251.1)
        # 既有字段不动（加法字段无破坏）
        for key in ("run_id", "turns", "input_tokens",
                    "cache_read_input_tokens", "context_peak_tokens",
                    "per_turn_input_tokens", "text_turns",
                    "tool_uses_total", "tool_uses"):
            assert key in m, f"既有字段 {key} 不得缺失"
        assert m["run_id"] == run_id
        assert m["turns"] == 3
        # daemon 侧 run metrics 日志 context：同名字段同值（同一 stats 单源）
        ctxs = _run_metrics_contexts(logger)
        assert len(ctxs) == 1, f"应恰一条 metric_type=run_metrics 日志；{logger.records}"
        ctx = ctxs[0]
        assert ctx["run_id"] == run_id
        assert ctx["latency_rounds"] == 3
        assert ctx["latency_stalls"] == 2
        assert ctx["latency_max"] == pytest.approx(251.1)

    def test_zero_sample_run_fields_fallback(self, tmp_path):
        """零样本 run（启动即失败）：字段回退 0/0/None 不抛、不阻断收尾。"""
        proot = tmp_path / "proj"
        logger = _CaptureLogger()
        runner = _make_runner(proot, logger)
        run_id = "impl-stall-zero-1"
        proc = _FakeProc([], returncode=3)
        with _patched_popen(proc):
            with pytest.raises(RuntimeError, match="claude CLI failed"):
                runner._run_claude("prompt", proot, run_id)
        run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
        lines = _read_lines(run_file)
        metrics = [l for l in lines if l.get("type") == "run_metrics"]
        assert len(metrics) == 1
        m = metrics[0]
        assert m["latency_rounds"] == 0
        assert m["latency_stalls"] == 0
        assert m["latency_max"] is None
        # 正常失败路径既有行序不变：error 终态行仍为文件末行
        assert lines[-1]["type"] == "error"
        # daemon 侧 context 同步零样本回退
        ctxs = _run_metrics_contexts(logger)
        assert len(ctxs) == 1
        assert ctxs[0]["latency_rounds"] == 0
        assert ctxs[0]["latency_stalls"] == 0
        assert ctxs[0]["latency_max"] is None

    def test_poll_loop_crash_metrics_defaults(self, tmp_path):
        """轮询环崩溃路径：run_metrics 行照常追加于 error 终态行之后，
        字段缺省（零样本回退）不抛（权威测试同款装配 + 新字段断言）。"""
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = Path(tmp_path)
        logger = _CaptureLogger()
        runner.logger = logger
        runner.config = {}
        runner._running_agents = {}
        runner._cancel_meta = {}
        run_id = "impl-stall-crash-1"
        run_file = Path(tmp_path) / ".fenix" / "runs" / f"{run_id}.jsonl"
        fake_proc = MagicMock()
        fake_proc.poll.side_effect = TypeError("boom-inside-poll-loop")
        fake_proc.stdout = MagicMock()
        fake_proc.stderr = MagicMock()
        with unittest.mock.patch.object(
                subprocess, "Popen", return_value=fake_proc), \
             unittest.mock.patch(
                "threading.Thread", side_effect=_no_thread_factory), \
             unittest.mock.patch.object(
                AgentRunner, "_effective_run_timeout", create=True,
                return_value=3600), \
             unittest.mock.patch.object(
                AgentRunner, "_cancel_is_requested",
                create=True, return_value=False), \
             unittest.mock.patch.object(
                AgentRunner, "_normalize_run_id",
                create=True, side_effect=lambda x: x):
            with pytest.raises(TypeError) as ctx_exc:
                runner._run_claude(
                    "prompt", Path(tmp_path), run_id,
                    spec_name="stall-crash", agent_type="impl")
        assert "boom-inside-poll-loop" in str(ctx_exc.value)
        lines = _read_lines(run_file)
        terminal = [l for l in lines if l.get("type") == "error"]
        metrics = [l for l in lines if l.get("type") == "run_metrics"]
        assert len(terminal) == 1, f"应恰一条 error 终态行；lines={lines}"
        assert len(metrics) == 1, f"run_metrics 行照常追加；lines={lines}"
        assert lines.index(terminal[0]) < lines.index(metrics[0])
        m = metrics[0]
        assert m["latency_rounds"] == 0
        assert m["latency_stalls"] == 0
        assert m["latency_max"] is None
        # daemon 侧内联日志同样落盘、字段缺省不抛
        ctxs = _run_metrics_contexts(logger)
        assert len(ctxs) == 1
        assert ctxs[0]["latency_rounds"] == 0
        assert ctxs[0]["latency_stalls"] == 0
        assert ctxs[0]["latency_max"] is None
