"""API 停滞请求明细观测测试（evo-add-api-stall-request-detail）。

对应 spec 全部 Scenario（首采集验收——仅「字段在场」不构成通过）：
- token 语义修正：usage 可得 run 的事件与明细 token 非空 + usage_source=
  "assistant_usage"；usage 全零/缺失 run 的 token=null + "unavailable"
  而 request_bytes 仍非空（「无数据」与「真实值为 0」可区分，不写 0 冒充）；
- request_bytes：转录行字节累计的 prompt 体积代理（截至该轮请求发出前的
  已落盘字节）与 null 回退（累计器不可用时事件/明细不丢弃）；
- stall_details：覆盖全部 >60s 停滞轮（含 (60,120] 不产 api_round_stall
  事件的区间），offset_s = ts - started_at 口径；
- run_metrics 两落点（转录行 + 日志侧）新键与汇总行新段渲染；
- 回归：latency_stats 既有键值不变、self_review 消费面行为不变、
  stall_details 为可选增键（缺键读侧不报错）。
"""

import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.agent_runner.runner as runner_mod
from core.agent_runner.latency import (
    LATENCY_STALL_SECONDS,
    format_latency_summary,
    latency_stats,
)
from core.self_review import _scan_run_stall_totals
from tests.helpers import make_runner


# ── 夹具工具（同 test_api_stall_signal_grading 口径）────────────────────


class _RecordingLogger:
    """记录型 logger：捕获全部级别调用。"""

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
    runner = make_runner(proot)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}
    runner._cancel_requested = set()
    runner._cancel_requested_lock = threading.Lock()
    runner._cancel_meta = {}
    return runner


class _FakeProc:
    def __init__(self, events, returncode=3):
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


def _drive_run(runner, proot, run_id, events, returncode=3):
    """驱动真实 _run_agent（fake Popen），失败路径捕获 RuntimeError。"""
    proc = _FakeProc(events, returncode=returncode)
    fake_ns = SimpleNamespace(
        Popen=lambda *a, **k: proc,
        PIPE=subprocess.PIPE,
        TimeoutExpired=subprocess.TimeoutExpired,
    )
    with mock.patch.object(runner_mod, "subprocess", fake_ns):
        if returncode == 0:
            return None, runner._run_agent(
                "prompt", proot, run_id, spec_name="demo",
                agent_type="implementer")
        with pytest.raises(RuntimeError) as cm:
            runner._run_agent("prompt", proot, run_id, spec_name="demo",
                              agent_type="implementer")
        return cm.value, None


def _read_run_metrics(runner, proot, run_id):
    """读转录 run_metrics 行（末条）与全部事件行。"""
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    lines = [json.loads(l) for l in
             run_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    metrics = [l for l in lines if l.get("type") == "run_metrics"]
    assert metrics, "应落 run_metrics 转录行"
    return metrics[-1], lines


def _log_metrics_rows(rec):
    return [
        a[2] for (kind, a, _k) in rec.records
        if kind == "info" and len(a) >= 3 and isinstance(a[2], dict)
        and a[2].get("metric_type") == "run_metrics"
    ]


def _stall_records(rec, kind):
    return [
        (a, k) for (k2, a, k) in rec.records
        if k2 == kind and len(a) >= 3 and isinstance(a[2], dict)
        and a[2].get("event") == "api_round_stall"
    ]


def _line_len(entry) -> int:
    """读线程转录行字节口径（json.dumps(..., ensure_ascii=False)+"\n"）。"""
    return len((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))


# ── 1.1: token 语义修正 ────────────────────────────────────────────────


class TestTokenSemanticsUsageAvailable:
    """Scenario: usage 可得 run——事件与明细 token 非空 + assistant_usage。"""

    def test_event_and_details_carry_real_tokens(self, tmp_path):
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1130.0,  # 130s → info 事件
             "message": {"usage": {"input_tokens": 1234,
                                   "cache_read_input_tokens": 5678}}},
        ]
        err, _ret = _drive_run(runner, proot, "impl-detail-tok-1", events)
        # 事件侧：token 为真实值（非 0 非 null）且来源标注 assistant_usage
        infos = _stall_records(rec, "info")
        assert len(infos) == 1, f"应恰一条停滞事件；records={rec.records}"
        extra = infos[0][0][2]
        assert extra["input_tokens"] == 1234
        assert extra["cache_read_input_tokens"] == 5678
        assert extra["usage_source"] == "assistant_usage"
        # 明细侧：同一语义
        metrics, _lines = _read_run_metrics(runner, proot, "impl-detail-tok-1")
        details = metrics["stall_details"]
        assert len(details) == 1
        assert details[0]["input_tokens"] == 1234
        assert details[0]["cache_read_input_tokens"] == 5678
        assert details[0]["usage_source"] == "assistant_usage"
        assert err is not None


class TestTokenSemanticsUsageUnavailable:
    """Scenario: usage 全零/缺失 run——token=null + unavailable，
    而 request_bytes 仍非空（字节证据不依赖 usage）。"""

    def test_zero_usage_event_null_tokens(self, tmp_path):
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        # 逐消息 usage 全零 + result 终态带真实 usage（网关形态：真实用量
        # 仅在 result——逐轮仍不可得，事件 MUST NOT 用 result 回填冒充）
        events = [
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1130.0,
             "message": {"usage": {"input_tokens": 0,
                                   "cache_read_input_tokens": 0}}},
            {"type": "result", "subtype": "success", "is_error": False,
             "num_turns": 2, "session_id": "s-1", "result": "done",
             "usage": {"input_tokens": 9999,
                       "cache_read_input_tokens": 8888},
             "timestamp": 1131.0},
        ]
        err, _ret = _drive_run(runner, proot, "impl-detail-tok-2", events)
        warns = _stall_records(rec, "warning") + _stall_records(rec, "info")
        assert len(warns) == 1
        extra = warns[0][0][2]
        assert extra["input_tokens"] is None, "usage 全零时事件 token 必须为 null"
        assert extra["cache_read_input_tokens"] is None
        assert extra["usage_source"] == "unavailable"
        assert extra["request_bytes"] is not None, (
            "usage 不可得的 run request_bytes 仍应非空（不依赖 usage）")
        metrics, _lines = _read_run_metrics(runner, proot, "impl-detail-tok-2")
        details = metrics["stall_details"]
        assert len(details) == 1
        assert details[0]["input_tokens"] is None
        assert details[0]["cache_read_input_tokens"] is None
        assert details[0]["usage_source"] == "unavailable"
        assert details[0]["request_bytes"] == extra["request_bytes"]

    def test_missing_usage_key_null_tokens(self, tmp_path):
        """message.usage 键整体缺失：同 unavailable 语义（非 0 冒充）。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1140.0},  # 140s，无 usage 键
        ]
        _drive_run(runner, proot, "impl-detail-tok-3", events)
        infos = _stall_records(rec, "info")
        assert len(infos) == 1
        extra = infos[0][0][2]
        assert extra["input_tokens"] is None
        assert extra["cache_read_input_tokens"] is None
        assert extra["usage_source"] == "unavailable"


# ── 1.2: request_bytes 采集 ────────────────────────────────────────────


class TestRequestBytes:
    """Scenario: request_bytes = 截至该轮请求发出前已写入转录的累计行字节。"""

    def test_snapshot_counts_only_lines_before_request(self, tmp_path):
        """第 2 轮停滞样本完成于第 4 行写盘前——request_bytes 恰为前 3 行
        字节和（不含本轮响应行，响应体积不能代表请求体积）。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        e1 = {"type": "tool_result", "timestamp": 1000.0}
        e2 = {"type": "assistant", "timestamp": 1130.0,
              "message": {"usage": {"input_tokens": 10,
                                    "cache_read_input_tokens": 20}}}
        e3 = {"type": "tool_result", "timestamp": 2000.0}
        e4 = {"type": "assistant", "timestamp": 2160.0,  # 160s 停滞
              "message": {"usage": {"input_tokens": 11,
                                    "cache_read_input_tokens": 21}}}
        _drive_run(runner, proot, "impl-detail-req-1", [e1, e2, e3, e4])
        metrics, _lines = _read_run_metrics(runner, proot, "impl-detail-req-1")
        details = metrics["stall_details"]
        assert len(details) == 2
        # 第 1 轮快照 = 第 1 行已落盘字节；第 2 轮快照 = 前 3 行字节和
        # （第 2/3 行在本轮请求发出前均已写盘；第 4 行响应行不计入）
        assert details[0]["request_bytes"] == _line_len(e1)
        assert details[1]["request_bytes"] == (
            _line_len(e1) + _line_len(e2) + _line_len(e3))
        assert metrics["latency_stall_bytes_total"] == pytest.approx(
            details[0]["request_bytes"] + details[1]["request_bytes"])

    def test_accumulator_failure_falls_back_to_null(self, tmp_path):
        """累计器不可用（len 探针异常）→ request_bytes 全线 null、字节合计
        0.0，事件与明细不因体积缺失丢弃，转录行完整。"""

        class _LenOnceBytes(bytes):
            """首个 len() 调用抛错（模拟累计异常），后续正常（写盘不受扰）。"""

            def __new__(cls, data):
                obj = super().__new__(cls, data)
                obj._first = True
                return obj

            def __len__(self):
                if self._first:
                    self._first = False
                    raise RuntimeError("len probe failure")
                return bytes.__len__(self)

        class _LenProbeStr(str):
            """str 子类：encode 返回 len 探针字节（拦在累计处而非写盘处）。"""

            def __add__(self, other):
                return _LenProbeStr(str.__add__(self, other))

            def encode(self, *a, **k):
                return _LenOnceBytes(str.encode(self, *a, **k))

        class _LenProbeJson:
            """仅替换 runner 模块可见的 json 面：dumps 返回 len 探针串
            （runner 落盘形如 ``json.dumps(...) + "\\n"`` 再 encode，
            探针须在 str 域保持子类穿透 +）。"""

            JSONDecodeError = json.JSONDecodeError
            loads = staticmethod(json.loads)

            @staticmethod
            def dumps(obj, **kw):
                return _LenProbeStr(json.dumps(obj, **kw))

        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1140.0},
        ]
        with mock.patch.object(runner_mod, "json", _LenProbeJson):
            err, _ret = _drive_run(runner, proot, "impl-detail-req-2", events)
        infos = _stall_records(rec, "info")
        assert len(infos) == 1, "事件不因体积缺失丢弃"
        assert infos[0][0][2]["request_bytes"] is None
        metrics, lines = _read_run_metrics(runner, proot, "impl-detail-req-2")
        details = metrics["stall_details"]
        assert len(details) == 1, "明细不因体积缺失丢弃"
        assert details[0]["request_bytes"] is None
        assert metrics["latency_stall_bytes_total"] == 0.0
        # 转录完整：2 条事件行均落盘（写盘路径不受累计异常扰动）
        assert sum(1 for l in lines if l.get("type") in
                   ("tool_result", "assistant")) == 2


# ── 1.3: stall_details 结构与 (60,120] 区间覆盖 ────────────────────────


class TestStallDetailsStructure:
    """Scenario: 明细覆盖全部 >60s 轮（含 (60,120] 不产事件区间），
    offset_s = ts - started_at 口径。"""

    def test_60_120_band_collected_without_event(self, tmp_path):
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        t0 = time.time()
        events = [
            {"type": "tool_result", "timestamp": t0},
            {"type": "assistant", "timestamp": t0 + 90.0},  # (60,120] 区间
            {"type": "tool_result", "timestamp": t0 + 91.0},
            {"type": "assistant", "timestamp": t0 + 241.0},  # 150s → 事件
        ]
        err, _ret = _drive_run(runner, proot, "impl-detail-band-1", events)
        # (60,120] 轮不产 api_round_stall 事件
        assert _stall_records(rec, "warning") == []
        assert len(_stall_records(rec, "info")) == 1
        metrics, _lines = _read_run_metrics(runner, proot, "impl-detail-band-1")
        details = metrics["stall_details"]
        assert len(details) == 2, "(60,120] 轮必须进明细（独立于 120s 分支）"
        assert metrics["latency_stalls"] == 2, "与 latency_stalls 计数同口径"
        # 结构与口径：round 取样本序数、duration_s 为往返时长、offset_s =
        # ts - started_at（started_at ≈ t0 + 亚秒装配差，±5s 容差）
        assert details[0]["round"] == 1
        assert details[1]["round"] == 2
        assert details[0]["duration_s"] == pytest.approx(90.0)
        assert details[1]["duration_s"] == pytest.approx(150.0)
        assert details[0]["offset_s"] == pytest.approx(90.0, abs=5.0)
        assert details[1]["offset_s"] == pytest.approx(241.0, abs=5.0)
        assert details[0]["ts"] == pytest.approx(t0 + 90.0, abs=5.0)
        # 汇总行含合计秒段（err 内嵌 | latency: 文本）
        assert "stall_total=" in str(err)

    def test_no_stall_run_lands_empty_details(self, tmp_path):
        """零停滞 run：stall_details=[]、bytes_total=0.0（无明细形态）。"""
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        runner.logger = _RecordingLogger()
        events = [
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1002.0},  # 2s 快轮
        ]
        _drive_run(runner, proot, "impl-detail-band-2", events)
        metrics, _lines = _read_run_metrics(runner, proot, "impl-detail-band-2")
        assert metrics["stall_details"] == []
        assert metrics["latency_stall_bytes_total"] == 0.0
        assert metrics["latency_stalls"] == 0


# ── 1.4: run_metrics 两落点与汇总行 ────────────────────────────────────


class TestRunMetricsLanding:
    """Scenario: 转录行与日志侧均落 stall_details/latency_stall_bytes_total，
    既有聚合键名与语义不变。"""

    def test_both_landings_carry_new_keys(self, tmp_path):
        proot = tmp_path / "proj"
        runner = _make_runner(proot)
        rec = _RecordingLogger()
        runner.logger = rec
        events = [
            {"type": "tool_result", "timestamp": 1000.0},
            {"type": "assistant", "timestamp": 1160.0,
             "message": {"usage": {"input_tokens": 7,
                                   "cache_read_input_tokens": 9}}},
        ]
        _drive_run(runner, proot, "impl-detail-met-1", events)
        metrics, _lines = _read_run_metrics(runner, proot, "impl-detail-met-1")
        # 既有聚合键在场且语义不变
        assert metrics["latency_rounds"] == 1
        assert metrics["latency_stalls"] == 1
        assert metrics["latency_max"] == pytest.approx(160.0)
        assert metrics["latency_stall_total_seconds"] == pytest.approx(160.0)
        # 新键：明细数组与字节合计
        details = metrics["stall_details"]
        assert len(details) == 1
        row = details[0]
        assert set(row) == {
            "round", "ts", "offset_s", "duration_s", "request_bytes",
            "input_tokens", "cache_read_input_tokens", "usage_source"}
        assert row["request_bytes"] > 0
        assert metrics["latency_stall_bytes_total"] == pytest.approx(
            row["request_bytes"])
        # 日志侧落点
        log_rows = _log_metrics_rows(rec)
        assert log_rows, "run_metrics 日志侧行应存在"
        lrow = log_rows[-1]
        assert len(lrow["stall_details"]) == 1
        assert lrow["stall_details"][0]["input_tokens"] == 7
        assert lrow["latency_stall_bytes_total"] == pytest.approx(
            metrics["latency_stall_bytes_total"])
        # 汇总行新段（既有段形态不变）
        summary_lines = [
            a[1] for (kind, a, _k) in rec.records
            if kind == "info" and len(a) >= 2
            and isinstance(a[1], str) and "rounds" in a[1] and "stalls>" in a[1]
        ]
        assert summary_lines, "应落延迟汇总行"
        assert "stalls>60s=1 (100%)" in summary_lines[-1]
        assert "stall_total=160.0s" in summary_lines[-1]
        assert f"stall_bytes={int(metrics['latency_stall_bytes_total'])}" \
            in summary_lines[-1]


# ── 2.2: 回归契约（既有消费面行为不变）────────────────────────────────


class TestRegressionContract:
    """Scenario: latency_stats 既有键值不变；self_review 消费面行为不变；
    stall_details 为可选增键（缺键读侧不报错）。"""

    def test_latency_stats_key_set_unchanged(self):
        """既有键集合与取值逐字段不变（新键只由 runner 侧附着，不入纯函数）。"""
        stats = latency_stats([2.0, 60.0, 100.0])
        assert set(stats) == {
            "rounds", "median", "p90", "max", "stalls", "stall_ratio",
            "latency_stall_total_seconds"}
        assert stats["rounds"] == 3
        assert stats["stalls"] == 1
        assert stats["max"] == 100.0
        assert stats["latency_stall_total_seconds"] == pytest.approx(100.0)
        empty = latency_stats([])
        assert set(empty) == set(stats)
        assert empty["stalls"] == 0
        assert empty["latency_stall_total_seconds"] == 0.0
        assert empty["max"] is None

    def test_self_review_scan_unchanged(self, tmp_path):
        """_scan_run_stall_totals（latency_stats 消费面）键集合与取值不变。"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir(parents=True)
        p = runs_dir / "r1.jsonl"
        p.write_text(
            "\n".join(json.dumps(e) for e in [
                {"type": "user",
                 "message": {"content": [{"type": "tool_result"}]},
                 "timestamp": "2026-11-27T00:00:00Z"},
                {"type": "assistant", "timestamp": "2026-11-27T00:01:40Z"},
            ]) + "\n", encoding="utf-8")
        scan = _scan_run_stall_totals(p)
        # 三统计键在场且取值不变（scan 另带 agent_type/truncated 既有旁键，
        # 本 SPEC 不触及）
        assert {"stalls", "total_stall_seconds", "max_stall_seconds"} <= set(scan)
        assert scan["stalls"] == 1
        assert scan["total_stall_seconds"] == pytest.approx(100.0)
        assert scan["max_stall_seconds"] == pytest.approx(100.0)

    def test_summary_line_without_new_keys_byte_identical(self):
        """stats 缺新键（历史调用方手工构造形态）→ 行形态与历史逐字节一致。"""
        legacy = {"rounds": 3, "median": 60.0, "p90": 92.0, "max": 100.0,
                  "stalls": 1, "stall_ratio": 1 / 3}
        line = format_latency_summary("run-x", legacy)
        assert line == (
            "run run-x: 3 rounds, median 60.0s, p90 92.0s, max 100.0s, "
            "stalls>60s=1 (33%)")
        # 仅带既有合计键（latency_stats 直出、无 runner 附着）：只追加
        # stall_total 段，不产 stall_bytes 段
        legacy["latency_stall_total_seconds"] = 100.0
        line2 = format_latency_summary("run-x", legacy)
        assert line2 == line + ", stall_total=100.0s"
        assert "stall_bytes" not in line2

    def test_metrics_row_missing_new_keys_tolerated(self):
        """存量 run_metrics 行（无新键）读侧 .get 口径不报错、按无明细/0 处理。"""
        legacy_row = {"type": "run_metrics", "latency_rounds": 2,
                      "latency_stalls": 1, "latency_max": 150.0,
                      "latency_stall_total_seconds": 150.0}
        details = legacy_row.get("stall_details") or []
        total = float(legacy_row.get("latency_stall_bytes_total") or 0.0)
        assert details == []
        assert total == 0.0
        # 新行缺 stall_details（理论防御：异常回退路径之外的形态）同样容忍
        partial = {"latency_stall_bytes_total": 1.0}
        assert partial.get("stall_details") or [] == []
