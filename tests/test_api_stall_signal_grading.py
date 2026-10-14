"""API stall 信号分级与摘要可见性测试（evo-api-stall-signal-grading）。

对应 spec 全部 Scenario：
- R1 stall 分级：classify_round_stall 纯函数边界（恰 300 秒、恰连续第 2 轮、
  120-300 秒孤立单轮）+ 发射点日志级别断言（info→INFO、escalated→WARNING、
  连续第 2 轮→WARNING、≤120s 快轮重置 streak）；
- R2 run 级停滞统计入账：run 末汇总行附分级计数（warning=N info=M）、
  成功终态 run metrics 日志行带非零 stall 统计（真实 _finalize_success →
  _log_run_metrics 通路；_run_agent 返回 tuple 第 5 元素携带同一 stats）；
- R3 每日自省第 6 节 API 停滞聚合行（stalls>0 的 run 才列、窗口归属、
  有界流式扫描、聚合环节异常降级空产出 + warning）。
"""

import io
import json
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import latency as latency_mod
import core.agent_runner.runner as runner_mod
from core.agent_runner.latency import (
    LATENCY_STALL_SECONDS,
    STALL_ROUND_ESCALATE_SECONDS,
    STALL_ROUND_WARN_SECONDS,
    classify_round_stall,
)
from core.agent_runner.runner import RUN_STALL_ROUND_SECONDS
from core.self_review import (
    MIDFLIGHT_SCAN_MAX_LINES,
    SelfReviewScheduler,
    _collect_api_stall_aggregates,
    _scan_run_stall_totals,
)
from tests.helpers import make_runner


# ── 夹具工具 ────────────────────────────────────────────────────────────


class _RecordingLogger:
    """记录型 logger：捕获全部级别调用（分级断言需区分 INFO/WARNING 落点）。"""

    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        self.records.append(("debug", a, k))

    def info(self, *a, **k):
        self.records.append(("info", a, k))

    def error(self, *a, **k):
        self.records.append(("error", a, k))

    def warning(self, *a, **k):
        self.records.append(("warning", a, k))


def _make_runner(proot):
    """最小 AgentRunner（同 test_run_latency_stats 口径，可驱动真实 _run_agent）。"""
    runner = make_runner(proot)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}
    runner._cancel_requested = set()
    runner._cancel_requested_lock = threading.Lock()
    runner._cancel_meta = {}
    return runner


def _fake_subprocess(events, returncode=3):
    """Popen 替身：stdout 产出 stream-json 事件行，进程随即以 rc 退出。"""
    class _FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(
                "".join(json.dumps(e) + "\n" for e in events))
            self.stderr = io.StringIO("")
            self.stdin = io.StringIO()
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


def _drive_run(runner, proot, run_id, events, returncode=3):
    """驱动真实 _run_agent（fake Popen），失败路径捕获 RuntimeError。"""
    fake_ns, _proc = _fake_subprocess(events, returncode=returncode)
    with mock.patch.object(runner_mod, "subprocess", fake_ns):
        if returncode == 0:
            return None, runner._run_agent(
                "prompt", proot, run_id, spec_name="demo",
                agent_type="implementer")
        with pytest.raises(RuntimeError) as cm:
            runner._run_agent("prompt", proot, run_id, spec_name="demo",
                              agent_type="implementer")
        return cm.value, None


def _stall_records(logger, kind):
    """提取停滞分级日志记录（event=api_round_stall，按级别过滤）。"""
    return [
        (a, k) for (k2, a, k) in logger.records
        if k2 == kind and len(a) >= 3
        and isinstance(a[2], dict)
        and a[2].get("event") == "api_round_stall"
    ]


# ── R1: 分级纯函数与常量 ────────────────────────────────────────────────


class TestClassifyRoundStall:
    """Scenario: 分级阈值以新常量表达；三既有常量取值与语义不动。"""

    def test_new_constant_and_reexport_same_object(self):
        assert STALL_ROUND_ESCALATE_SECONDS == 300.0
        # 单源：runner re-export 与 latency.py 模块属性同源（不另立常量）
        assert runner_mod.STALL_ROUND_ESCALATE_SECONDS is (
            latency_mod.STALL_ROUND_ESCALATE_SECONDS)
        assert runner_mod.classify_round_stall is latency_mod.classify_round_stall
        # 三既有常量取值未被本能力改动（同值不同义，严禁合并复用）
        assert LATENCY_STALL_SECONDS == 60.0
        assert STALL_ROUND_WARN_SECONDS == 120.0
        assert RUN_STALL_ROUND_SECONDS == 120.0

    def test_exactly_300s_single_round_not_escalated(self):
        """恰 300 秒：严格 > 比较，不升级（孤立单轮 → info）。"""
        assert classify_round_stall(1, 300.0) == "info"

    def test_just_over_300s_escalated(self):
        assert classify_round_stall(1, 300.1) == "warning-escalated"
        assert classify_round_stall(1, 1200.0) == "warning-escalated"

    def test_exactly_second_consecutive_round_warns(self):
        """恰连续第 2 轮（各 >120s）→ warning。"""
        assert classify_round_stall(2, 121.0) == "warning"
        assert classify_round_stall(3, 200.0) == "warning"

    def test_single_round_120_to_300s_info(self):
        """120-300 秒孤立单轮 → info（只计数、不打 WARNING）。"""
        assert classify_round_stall(1, 120.1) == "info"
        assert classify_round_stall(1, 299.9) == "info"

    def test_escalation_takes_precedence_over_streak(self):
        """单轮超限优先于连续停滞分级。"""
        assert classify_round_stall(5, 400.0) == "warning-escalated"


# ── R1: 发射点分级落日志 ────────────────────────────────────────────────


class TestEmissionGrading:
    """Scenario: 发射点按分级落 INFO/WARNING；汇总行附分级计数。"""

    def test_isolated_single_round_info_level(self, tmp_path):
        """150s 孤立单轮：INFO 级、grade="info"、零 WARNING、计数 info=1。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 100.0},
            {"type": "assistant", "timestamp": 250.0},  # 150s 孤立单轮
        ]
        err, _ret = _drive_run(runner, proot, "impl-grade-info-1", events)
        assert _stall_records(rec, "warning") == []
        infos = _stall_records(rec, "info")
        assert len(infos) == 1, f"应恰一条 info 级停滞日志；records={rec.records}"
        extra = infos[0][0][2]
        assert extra["run_id"] == "impl-grade-info-1"
        assert extra["grade"] == "info"
        assert extra["latency_round"] == 1
        assert extra["latency_max"] == pytest.approx(150.0)
        # run 末汇总行附分级计数
        assert "warning=0 info=1" in str(err)

    def test_single_round_over_300s_escalated_to_warning(self, tmp_path):
        """320s 单轮：WARNING 级、grade="warning-escalated"、零 INFO。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 100.0},
            {"type": "assistant", "timestamp": 420.0},  # 320s > 300s
        ]
        err, _ret = _drive_run(runner, proot, "impl-grade-esc-1", events)
        assert _stall_records(rec, "info") == []
        warns = _stall_records(rec, "warning")
        assert len(warns) == 1, f"应恰一条 WARNING；records={rec.records}"
        extra = warns[0][0][2]
        assert extra["grade"] == "warning-escalated"
        assert extra["latency_max"] == pytest.approx(320.0)
        assert "warning=1 info=0" in str(err)

    def test_exactly_300s_emission_not_escalated(self, tmp_path):
        """恰 300 秒发射点：INFO（严格 > 比较，升级线不含等于）。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 100.0},
            {"type": "assistant", "timestamp": 400.0},  # 恰 300.0s
        ]
        _err, _ret = _drive_run(runner, proot, "impl-grade-bound-1", events)
        assert _stall_records(rec, "warning") == []
        infos = _stall_records(rec, "info")
        assert len(infos) == 1
        assert infos[0][0][2]["grade"] == "info"

    def test_second_consecutive_round_warns(self, tmp_path):
        """连续两轮 >120s：第 1 轮 info、第 2 轮 WARNING（grade="warning"）。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 0.0},
            {"type": "assistant", "timestamp": 130.0},   # 130s：孤立 → info
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1140.0},  # 140s：连续第 2 轮 → warning
        ]
        err, _ret = _drive_run(runner, proot, "impl-grade-streak-1", events)
        infos = _stall_records(rec, "info")
        warns = _stall_records(rec, "warning")
        assert len(infos) == 1 and infos[0][0][2]["grade"] == "info"
        assert len(warns) == 1
        wextra = warns[0][0][2]
        assert wextra["grade"] == "warning"
        assert wextra["latency_round"] == 2  # 第 2 个有效样本
        assert wextra["latency_max"] == pytest.approx(140.0)
        assert "warning=1 info=1" in str(err)

    def test_streak_resets_after_fast_round(self, tmp_path):
        """≤120s 快轮重置连续计数：其后 140s 仍是孤立单轮 → info。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 0.0},
            {"type": "assistant", "timestamp": 130.0},   # 130s：info
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1005.0},  # 5s：快轮重置
            {"type": "tool_result", "timestamp": 2000.0},
            {"type": "assistant", "timestamp": 2140.0},  # 140s：重置后孤立 → info
        ]
        err, _ret = _drive_run(runner, proot, "impl-grade-reset-1", events)
        assert _stall_records(rec, "warning") == []
        infos = _stall_records(rec, "info")
        assert len(infos) == 2
        assert all(a[2]["grade"] == "info" for a, _k in infos)
        assert "warning=0 info=2" in str(err)


# ── R2: 成功终态 run metrics 带实际 latency 统计 ────────────────────────


class TestSuccessTerminalLatencyStats:
    """Scenario: stats 经 _run_agent 返回 tuple 携带 → _finalize_success →
    _log_run_metrics；成功终态日志行不再 0/0/None 回退。"""

    def test_run_agent_success_returns_stats_in_tuple(self, tmp_path):
        """_run_agent 成功返回 5 元 tuple，末位携带本 run latency 统计；
        转录 run_metrics 行（既有字段不动）入账同一 stats。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 100.0},
            {"type": "assistant", "timestamp": 250.0},  # 150s stall → info
            {"type": "result", "subtype": "success", "is_error": False,
             "num_turns": 2, "session_id": "s-1", "result": "done",
             "timestamp": 260.0},
        ]
        _err, ret = _drive_run(runner, proot, "impl-success-1", events,
                               returncode=0)
        assert isinstance(ret, tuple) and len(ret) == 5
        assert ret[0] == "done"
        stats = ret[4]
        assert stats["rounds"] == 1
        assert stats["stalls"] == 1
        assert stats["max"] == pytest.approx(150.0)
        # 转录 run_metrics 行（构建处既有字段不动）带同一 stats
        run_file = proot / ".fenix" / "runs" / "impl-success-1.jsonl"
        lines = [json.loads(l) for l in
                 run_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        metrics = [l for l in lines if l.get("type") == "run_metrics"]
        assert metrics, "成功路径应落 run_metrics 转录行"
        assert metrics[-1]["latency_rounds"] == 1
        assert metrics[-1]["latency_stalls"] == 1
        assert metrics[-1]["latency_max"] == pytest.approx(150.0)

    def test_finalize_success_logs_real_latency(self, tmp_path):
        """真实 _finalize_success（最小协作替身）→ 真实 _log_run_metrics：
        成功终态 run metrics 日志行带非零 stall 统计。"""
        proot = tmp_path / "proj"
        wt = proot / "wt"
        wt.mkdir(parents=True)
        runner = make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        cleaned = []
        runner.worktree_manager = SimpleNamespace(
            cleanup=lambda p, success: (
                cleaned.append((p, success)),
                shutil.rmtree(p, ignore_errors=True)),
            keep_for_reuse=lambda *a, **k: None,
            get_branch_name=lambda p: "fenix/demo",
        )
        runner.__dict__["_v2_server_instance"] = SimpleNamespace(
            _v2_stop_for_worktree=lambda p: None)
        runner._git_status_porcelain = lambda p: []
        runner._should_keep_worktree_for_partial = lambda s, p: False
        runner._daily_count_lock = threading.Lock()
        runner._daily_run_count = 0
        runner._reset_instant_fail = lambda s: None
        runner._reset_signal_kill = lambda s: None
        runner._accumulate_token_usage = lambda *a, **k: None
        runner._record_verify_progress_tokens = lambda *a, **k: None
        runner._cancel_clear = lambda r: None

        from core.agent_runner.result_gate import AgentRunResult
        result = runner._finalize_success(
            spec_name="demo", agent_type="implementer", run_id="run",
            attempt_run_id="run-a1", attempt=1, start_time=0.0, turns=5,
            usage_info={}, provider_name=None, model=None,
            wt_path=wt, output="ok", sub_run_id="run-a1",
            branch="fenix/demo", handed_off=set(),
            latency={"rounds": 4, "stalls": 2, "max": 151.5},
        )
        assert isinstance(result, AgentRunResult) and result.success
        metrics = [
            a[2] for (kind, a, _k) in rec.records
            if kind == "info" and len(a) >= 3
            and isinstance(a[2], dict)
            and a[2].get("metric_type") == "run_metrics"
            and a[2].get("terminal") == "success"
        ]
        assert len(metrics) == 1, f"应恰一条 success run_metrics；records={rec.records}"
        assert metrics[0]["latency_rounds"] == 4
        assert metrics[0]["latency_stalls"] == 2
        assert metrics[0]["latency_max"] == pytest.approx(151.5)

    def test_log_run_metrics_zero_sample_fallback_preserved(self, tmp_path):
        """提前终态路径（无样本上下文）维持零样本回退：latency 缺省 → 0/0/None。"""
        proot = tmp_path / "proj"
        runner = make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        runner._log_run_metrics(
            run_id="r", spec_name="s", agent_type="implementer",
            duration_seconds=1.0, turns=1, usage_info={}, terminal="error")
        metrics = [
            a[2] for (kind, a, _k) in rec.records
            if kind == "info" and len(a) >= 3
            and isinstance(a[2], dict)
            and a[2].get("metric_type") == "run_metrics"
        ]
        assert len(metrics) == 1
        assert metrics[0]["latency_rounds"] == 0
        assert metrics[0]["latency_stalls"] == 0
        assert metrics[0]["latency_max"] is None


# ── R3: 每日自省第 6 节 API 停滞聚合 ────────────────────────────────────


class _FakeSM:
    def read_all(self):
        return {}


class _FakeLogger:
    def __init__(self):
        self.warnings = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        pass


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


def _make_scheduler(proot, logger=None):
    return SelfReviewScheduler(
        {"admin": {"enabled": True, "self_review": {"enabled": True,
                                                    "run_at": "22:00"}}},
        proot, logger or _FakeLogger(), _FakeSM(),
        agent_runner=None, store=None,
    )


class TestSelfReviewStallAggregation:
    """Scenario: 第 6 节 API 停滞聚合行——stalls>0 才列、窗口归属、有界流式、
    降级契约（异常降级空产出 + warning，不阻断其余小节）。"""

    def test_scan_run_stall_totals_values(self, tmp_path):
        """stalls/max 取 latency_stats（>60s 口径）；累计停滞秒 = >60s 样本和。"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir(parents=True)
        p = _write_run(runs_dir, "r1",
                       _stall_events(1000.0, [100.0, 70.0, 5.0]))
        scan = _scan_run_stall_totals(p)
        assert scan["stalls"] == 2
        assert scan["total_stall_seconds"] == pytest.approx(170.0)
        assert scan["max_stall_seconds"] == pytest.approx(100.0)

    def test_scan_bounded_by_max_lines(self, tmp_path):
        """有界流式：超过 max_lines 行即停（样本不入统计，不整文件读入）。"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir(parents=True)
        events = _stall_events(1000.0, [100.0] + [5.0] * 50)
        p = _write_run(runs_dir, "r2", events)
        scan = _scan_run_stall_totals(p, max_lines=3)
        # 前 3 行（system + user + assistant）恰好配出首个 100s 样本即止
        assert scan["stalls"] == 1
        assert scan["total_stall_seconds"] == pytest.approx(100.0)
        # 缺省上限与深扫同源
        assert MIDFLIGHT_SCAN_MAX_LINES == 20000

    def test_aggregate_lists_only_stalled_runs_in_window(self, tmp_path):
        """当日 stalls>0 的 run 才列；stalls=0 与窗口外 run 不列；按 run_id 排序。"""
        now = datetime.now().astimezone()
        runs_dir = tmp_path / "proj" / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        stalled_a = f"impl-a-{int(now.timestamp()) - 60}"
        stalled_b = f"impl-b-{int(now.timestamp()) - 30}"
        fast = f"impl-fast-{int(now.timestamp()) - 20}"
        stale = f"impl-stale-{int((now - timedelta(days=2)).timestamp())}"
        _write_run(runs_dir, stalled_a, _stall_events(now.timestamp(), [70.0, 100.0]))
        _write_run(runs_dir, stalled_b, _stall_events(now.timestamp(), [61.0]))
        _write_run(runs_dir, fast, _stall_events(now.timestamp(), [5.0, 6.0]))
        _write_run(runs_dir, stale, _stall_events(now.timestamp() - 2 * 86400, [90.0]))
        results = _collect_api_stall_aggregates(
            runs_dir.parent.parent,
            now - timedelta(hours=1), now + timedelta(minutes=5))
        assert [r["run_id"] for r in results] == [stalled_a, stalled_b]
        assert results[0]["stalls"] == 2
        assert results[0]["total_stall_seconds"] == pytest.approx(170.0)
        assert results[0]["max_stall_seconds"] == pytest.approx(100.0)
        assert results[1]["stalls"] == 1

    def test_aggregate_renders_section_line(self, tmp_path):
        """第 6 节渲染「- api-stall: <run_id> stalls=N total=Xs max=Ys」行。"""
        now = datetime.now().astimezone()
        root = tmp_path / "proj"
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        rid = f"impl-render-{int(now.timestamp()) - 60}"
        _write_run(runs_dir, rid, _stall_events(now.timestamp(), [70.0, 100.0]))
        sched = _make_scheduler(root)
        lines = sched._collect_midflight_section(
            now - timedelta(hours=1), now + timedelta(minutes=5))
        assert "### API 停滞聚合（stall 计数>0 的 run）" in lines
        assert (
            f"- api-stall: {rid} stalls=2 total=170.0s max=100.0s" in lines)

    def test_aggregation_absent_keeps_placeholder(self, tmp_path):
        """窗口内无停滞 run：聚合不产段，占位行形态不破。"""
        now = datetime.now().astimezone()
        root = tmp_path / "proj"
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        _write_run(runs_dir, f"impl-fast-{int(now.timestamp())}",
                   _stall_events(now.timestamp(), [5.0]))
        sched = _make_scheduler(root)
        lines = sched._collect_midflight_section(
            now - timedelta(hours=1), now + timedelta(minutes=5))
        assert lines == ["- （窗口内无中途信号）"]

    def test_aggregation_degrades_on_error(self, tmp_path):
        """聚合环节异常：降级空产出 + warning，不阻断占位行与其余小节。"""
        now = datetime.now().astimezone()
        root = tmp_path / "proj"
        (root / ".fenix" / "runs").mkdir(parents=True)
        logger = _FakeLogger()
        sched = _make_scheduler(root, logger)
        with mock.patch("core.self_review._collect_api_stall_aggregates",
                        side_effect=RuntimeError("aggregate boom")):
            lines = sched._collect_midflight_section(
                now - timedelta(hours=1), now + timedelta(minutes=5))
        assert "- （窗口内无中途信号）" in lines
        assert any("API 停滞聚合异常" in str(w) for w in logger.warnings)
