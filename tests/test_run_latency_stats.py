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
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.runner import (
    LATENCY_STALL_SECONDS,
    STALL_ROUND_WARN_SECONDS,
    _entry_is_tool_result,
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


def _user_tool_result_evt(ts: float, n_blocks: int = 1) -> dict:
    """真实 stream-json 形态的 tool_result 承载事件：``user`` 事件包裹
    ``message.content[]`` 里的 ``tool_result`` content block（顶层无
    ``tool_result`` 事件——实测转录 100% 走该形态）。"""
    return {
        "type": "user",
        "timestamp": _iso(ts),
        "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"tu_{i}",
             "content": f"result-{i}"} for i in range(n_blocks)
        ]},
    }


def _user_text_evt(ts: float) -> dict:
    """skill 加载消息形态：``user`` 事件仅含 ``text`` block（非 tool_result）。"""
    return {
        "type": "user",
        "timestamp": _iso(ts),
        "message": {"content": [
            {"type": "text", "text": "Base directory for this skill: ..."},
        ]},
    }


class _RecordingLogger:
    """记录型 logger：捕获 info/warning 调用（FakeLogger 静默，无法断言分级落点）。"""

    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.records.append(("info", a, k))

    def error(self, *a, **k):
        pass

    def warning(self, *a, **k):
        self.records.append(("warning", a, k))


# ── 统一 tool_result 识别（tool-result-stream-detection）──────────────


class TestToolResultDetection:
    """Scenario: 流转录 tool_result 事件统一识别（单一真源判定）。"""

    def test_user_wrapped_tool_result_block_true(self):
        assert _entry_is_tool_result(_user_tool_result_evt(100.0))

    def test_plain_text_user_event_false(self):
        assert not _entry_is_tool_result(_user_text_evt(100.0))

    def test_top_level_tool_result_compat_true(self):
        assert _entry_is_tool_result(_evt("tool_result", 100.0))

    def test_multi_block_user_event_true(self):
        assert _entry_is_tool_result(_user_tool_result_evt(100.0, n_blocks=3))

    def test_other_event_types_false(self):
        for etype in ("assistant", "system", "result", "tool_progress",
                      "stderr", "provider_marker"):
            assert not _entry_is_tool_result(_evt(etype, 100.0))

    def test_string_content_user_event_false(self):
        # message.content 为字符串（非 block 列表）不得误判
        entry = {"type": "user", "timestamp": 100.0,
                 "message": {"content": "plain string"}}
        assert not _entry_is_tool_result(entry)


# ── 真实 stream-json 形态样本提取（fix-run-latency-toolresult-parser）──


class TestRealShapeExtraction:
    """Scenario: 真实 stream-json 转录产出非空样本（根治合成自我证明盲区）。"""

    def test_user_wrapped_tool_result_produces_sample(self):
        events = [
            _user_tool_result_evt(100.0),
            _evt("assistant", 104.5),
        ]
        samples = latency_samples_from_events(events)
        assert len(samples) == 1
        assert samples[0] == pytest.approx(4.5)

    def test_user_wrapped_tool_result_multi_round_trips(self):
        events = [
            _user_tool_result_evt(10.0),
            _evt("assistant", 12.0),
            _user_tool_result_evt(20.0),
            _evt("assistant", 80.0),
        ]
        assert latency_samples_from_events(events) == [2.0, 60.0]

    def test_plain_text_user_event_not_sampled(self):
        # 纯 text user 事件（skill 加载消息）不得作为待配对 tool_result
        events = [
            _user_text_evt(0.0),
            _evt("assistant", 5.0),
        ]
        assert latency_samples_from_events(events) == []

    def test_multi_block_user_event_counts_single_roundtrip(self):
        # 一个 user 事件承载 N 个 tool_result block（并行回喂）= 一次 API 往返
        events = [
            _user_tool_result_evt(10.0, n_blocks=2),
            _evt("assistant", 12.0),
        ]
        assert latency_samples_from_events(events) == [2.0]

    def test_no_top_level_tool_result_still_samples(self):
        # 真实转录全程无顶层 tool_result 事件（全部 user 包裹）也能配对出样本
        events = [
            _evt("system", 0.0),
            _user_tool_result_evt(1.0),
            _evt("assistant", 2.5),
        ]
        samples = latency_samples_from_events(events)
        assert len(samples) == 1
        assert samples[0] == pytest.approx(1.5)


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


# ── _run_agent 旁路摘要日志与失败证据 ─────────────────────────────


class TestRunClaudeIntegration:
    """Scenario: 摘要日志 / 统计不改变行为 / 失败附证据。"""

    def _make_runner(self, proot):
        import threading

        from test_agent_runner import make_runner
        runner = make_runner(proot)
        runner.config = {"agents": {"run_timeout_seconds": 3600}}
        # 轮询环取消旗标所需最小实例状态（make_runner 跳过 __init__ 未初始化）
        runner._cancel_requested = set()
        runner._cancel_requested_lock = threading.Lock()
        runner._cancel_meta = {}
        return runner

    @staticmethod
    def _fake_subprocess(events, returncode=3):
        """Popen 替身：stdout 产出 stream-json 事件行，进程随即以 rc 退出。"""
        import io
        from types import SimpleNamespace

        class _FakeProc:
            def __init__(self):
                self.stdout = io.StringIO(
                    "".join(json.dumps(e) + "\n" for e in events))
                self.stderr = io.StringIO("")
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

    def test_latency_functions_pure(self):
        """统计为纯旁路：同一事件序列重复计算结果一致、不修改输入。"""
        events = [_evt("tool_result", 1.0), _evt("assistant", 3.0)]
        before = [dict(e) for e in events]
        latency_samples_from_events(events)
        assert events == before

    def test_failure_error_appends_latency_summary(self, tmp_path):
        """失败 run（rc!=0）的 RuntimeError 真实拼入「| latency:」摘要。

        驱动真实 _run_agent：fake Popen 产出一轮 tool_result→assistant
        事件（间隔 4.5s）后以 rc=3 退出，断言异常文本含延迟摘要、
        error 终态行落盘为最后一行（原用例自拼字符串自证，未触达
        runner.py 的拼接路径）。
        """
        proot = tmp_path / "proj"
        runner = self._make_runner(proot)
        events = [
            {"type": "tool_result", "timestamp": 100.0},
            {"type": "assistant", "timestamp": 104.5},
        ]
        fake_ns, _proc = self._fake_subprocess(events)
        import core.agent_runner.runner as rmod
        with mock.patch.object(rmod, "subprocess", fake_ns):
            with pytest.raises(RuntimeError) as cm:
                runner._run_agent("prompt", proot, "impl-x-1")
        err = str(cm.value)
        assert "claude CLI failed" in err
        assert "Exit code: 3" in err
        # 失败上下文附延迟证据：摘要含 run_id 与口径字段（卡死 vs 慢可判）
        assert " | latency: " in err
        assert "run impl-x-1" in err
        assert "rounds" in err and "median" in err and "stalls>60s=" in err
        # 真实路径副作用：error 终态行落盘为文件最后一行
        run_file = proot / ".fenix" / "runs" / "impl-x-1.jsonl"
        lines = [l for l in run_file.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        assert json.loads(lines[-1])["type"] == "error"

    def test_latency_self_check_warns_on_blind_run(self, tmp_path):
        """有 assistant 轮次却配不出样本 → WARNING 含「失明」/latency_rounds=0。

        驱动真实 _run_agent：fake Popen 产出仅 assistant 事件、无任何
        tool_result 形态，rc=3 退出 → finally 延迟自检命中（rounds=0
        且 turn_count>0），发出 WARNING 日志。
        """
        proot = tmp_path / "proj"
        runner = self._make_runner(proot)
        rec_logger = _RecordingLogger()
        runner.logger = rec_logger
        events = [
            {"type": "assistant", "timestamp": 100.0},
            {"type": "assistant", "timestamp": 200.0},
        ]
        fake_ns, _proc = self._fake_subprocess(events)
        import core.agent_runner.runner as rmod
        with mock.patch.object(rmod, "subprocess", fake_ns):
            with pytest.raises(RuntimeError):
                runner._run_agent("prompt", proot, "impl-blind-1")
        # WARNING 中含「失明」/「latency_rounds=0」且 turn_count=2
        # logger.warning("component", msg, {extra_dict}) → a = (component, msg, extra)
        blind_warns = [
            a[2] for (kind, a, _) in rec_logger.records
            if kind == "warning"
            and "失明" in str(a)
            and (a[2] if len(a) >= 3 else {}).get("latency_rounds") == 0
        ]
        assert len(blind_warns) >= 1, f"未检测到失明自检 WARNING；records={rec_logger.records}"
        extra = blind_warns[0]
        assert extra.get("turn_count") == 2
        assert extra.get("run_id") == "impl-blind-1"

    def test_latency_self_check_no_warn_when_vacuum_run(self, tmp_path):
        """真空跑（rounds=0 且 turn_count=0）→ 不触发失明告警。"""
        proot = tmp_path / "proj"
        runner = self._make_runner(proot)
        rec_logger = _RecordingLogger()
        runner.logger = rec_logger
        # 无 assistant 事件（真空跑）→ turn_count 始终为 0
        fake_ns, _proc = self._fake_subprocess([])
        import core.agent_runner.runner as rmod
        with mock.patch.object(rmod, "subprocess", fake_ns):
            with pytest.raises(RuntimeError):
                runner._run_agent("prompt", proot, "impl-vacuum-1")
        blind_warns = [
            a[2] for (kind, a, _) in rec_logger.records
            if kind == "warning"
            and "失明" in str(a)
            and (a[2] if len(a) >= 3 else {}).get("latency_rounds") == 0
        ]
        assert len(blind_warns) == 0, f"真空跑不应触发失明告警；records={rec_logger.records}"


# ── 期内停滞 WARNING（evo-add-api-stall-observability 1.1/1.2）──────


class TestStallRoundWarn:
    """Scenario: 超阈值样本期内 WARNING / 阈值内静默 / 无效测量双静默 /
    纯读侧（stats 不因告警改变）。"""

    def _make_runner(self, proot):
        import threading

        from test_agent_runner import make_runner
        runner = make_runner(proot)
        runner.config = {"agents": {"run_timeout_seconds": 3600}}
        runner._cancel_requested = set()
        runner._cancel_requested_lock = threading.Lock()
        runner._cancel_meta = {}
        return runner

    _fake_subprocess = staticmethod(TestRunClaudeIntegration._fake_subprocess)

    @staticmethod
    def _stall_warns(logger):
        """提取停滞 WARNING 记录（event=api_round_stall）。"""
        return [
            (a, k) for (kind, a, k) in logger.records
            if kind == "warning" and len(a) >= 3
            and isinstance(a[2], dict)
            and a[2].get("event") == "api_round_stall"
        ]

    @staticmethod
    def _stall_infos(logger):
        """提取 info 级停滞日志记录（event=api_round_stall，分级降级）。"""
        return [
            (a, k) for (kind, a, k) in logger.records
            if kind == "info" and len(a) >= 3
            and isinstance(a[2], dict)
            and a[2].get("event") == "api_round_stall"
        ]

    def test_stall_round_warn_constant_value(self):
        """常量值 120.0；与既有常量各自独立、既有常量未被改动。"""
        from core.agent_runner import latency as latency_mod
        from core.agent_runner.runner import RUN_STALL_ROUND_SECONDS
        assert STALL_ROUND_WARN_SECONDS == 120.0
        # 单源：runner re-export 与 latency.py 模块属性同值（不另立常量）
        assert latency_mod.STALL_ROUND_WARN_SECONDS == 120.0
        # 统计口径（60.0）与判停计入线（120.0）未被本能力改动
        assert LATENCY_STALL_SECONDS == 60.0
        assert RUN_STALL_ROUND_SECONDS == 120.0

    def test_isolated_single_stall_info_graded(self, tmp_path):
        """251.1s 孤立单轮（120-300s、连续第 1 轮）：分级降级 INFO 只计数。

        evo-api-stall-signal-grading 1.2 分级语义（原「单轮 >120s 必打
        WARNING」断言随新语义更新）：不打 WARNING；事件名仍 api_round_stall、
        context 增 grade="info"；样本照常进入既有样本序列。"""
        proot = tmp_path / "proj"
        runner = self._make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 100.0},
            {"type": "assistant", "timestamp": 351.1},  # 251.1s：孤立单轮
        ]
        fake_ns, _proc = self._fake_subprocess(events)
        import core.agent_runner.runner as rmod
        with mock.patch.object(rmod, "subprocess", fake_ns):
            with pytest.raises(RuntimeError):
                runner._run_agent("prompt", proot, "impl-stall-info-1")
        # 新语义：无任何停滞 WARNING（120-300s 孤立单轮降级 INFO）
        assert self._stall_warns(rec) == []
        # INFO 级落日志：事件仍 api_round_stall，context 增 grade="info"
        infos = self._stall_infos(rec)
        assert len(infos) == 1, f"应恰一条 info 级停滞日志；records={rec.records}"
        a, _k = infos[0]
        assert a[0] == "agent_runner"
        assert "run impl-stall-info-1" in a[1]
        assert "251.1" in a[1]  # 样本秒数（:.1f 格式）
        extra = a[2]
        assert extra["run_id"] == "impl-stall-info-1"
        assert extra["grade"] == "info"
        assert extra["latency_round"] == 1  # 有效样本序列中的序数（1 基）
        assert extra["latency_max"] == pytest.approx(251.1)

    def test_boundary_and_below_threshold_silent(self, tmp_path):
        """119.9s 边界内与恰 120.0s（严格 > 比较）样本全 run 静默，
        且样本照常入序列（静默不等于丢样本）。"""
        proot = tmp_path / "proj"
        runner = self._make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 0.0},
            {"type": "assistant", "timestamp": 119.9},   # 边界内
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1120.0},  # 恰等于阈值
        ]
        fake_ns, _proc = self._fake_subprocess(events)
        import core.agent_runner.runner as rmod
        with mock.patch.object(rmod, "subprocess", fake_ns):
            with pytest.raises(RuntimeError) as cm:
                runner._run_agent("prompt", proot, "impl-stall-quiet-1")
        assert self._stall_warns(rec) == []
        # 两个样本照常进 stats（error 摘要 2 rounds）
        assert "run impl-stall-quiet-1: 2 rounds" in str(cm.value)

    def test_invalid_measurement_no_sample_no_warn(self, tmp_path):
        """timestamp 缺失/负差值无效测量：既不产样本也不触发 WARNING。"""
        proot = tmp_path / "proj"
        runner = self._make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result"},                    # 缺 timestamp：不记录待配对
            {"type": "assistant", "timestamp": 300.0},  # 无待配对 → 无样本
            {"type": "tool_result", "timestamp": 400.0},
            {"type": "assistant", "timestamp": 350.0},  # 负差值 → 无效测量
        ]
        fake_ns, _proc = self._fake_subprocess(events)
        import core.agent_runner.runner as rmod
        with mock.patch.object(rmod, "subprocess", fake_ns):
            with pytest.raises(RuntimeError) as cm:
                runner._run_agent("prompt", proot, "impl-stall-invalid-1")
        assert self._stall_warns(rec) == []
        # 无有效样本（error 摘要 0 rounds）
        assert "0 rounds" in str(cm.value)

    def test_stats_unchanged_by_grading(self, tmp_path):
        """纯读侧：分级落日志不改变 stats——与纯函数对同一事件序列的计算
        逐字段一致（样本序列未被告警/分级改变）；汇总行附分级计数
        warning=0 info=1（孤立 251.1s 单轮降级 info）。"""
        proot = tmp_path / "proj"
        runner = self._make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 0.0},
            {"type": "assistant", "timestamp": 119.9},   # ≤120s：静默
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1251.1},  # 251.1s：孤立单轮 → info
        ]
        expected = latency_stats(latency_samples_from_events(events))
        fake_ns, _proc = self._fake_subprocess(events)
        import core.agent_runner.runner as rmod
        with mock.patch.object(rmod, "subprocess", fake_ns):
            with pytest.raises(RuntimeError) as cm:
                runner._run_agent("prompt", proot, "impl-stall-pure-1")
        # 无 WARNING；恰一条 info 级分级日志，序数为第 2 个有效样本
        assert self._stall_warns(rec) == []
        infos = self._stall_infos(rec)
        assert len(infos) == 1
        assert infos[0][0][2]["latency_round"] == 2
        assert infos[0][0][2]["grade"] == "info"
        # run 末摘要与纯函数结果逐字段一致（拼入 error 上下文的同一文本，
        # 行尾附分级计数 warning=0 info=1）
        expected_text = format_latency_summary(
            "impl-stall-pure-1", expected, {"warning": 0, "info": 1})
        assert f" | latency: {expected_text}" in str(cm.value)


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