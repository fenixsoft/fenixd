"""自省中途信号采集（add-self-review-midflight-signals）测试。

对应 tasks：
- 1.3 初筛用例：成功但 turns 离群入选（附组中位对照）、样本 < 3 组跳过、
  cost 全组缺失跳过、索引异常返回空 list
- 2.3 深扫用例：真实 stream-json 形态夹具（user 包裹 tool_result block）的
  stall=3 与 stderr=2 被采集、超限截断标注 truncated、单行坏 JSON 跳过不抛异常
- 3.2 归集用例：窗口内混合痕迹按组计数正确、样本条数截断至 5、窗口外行不
  计入、日志文件缺失返回空
- 4.3 注入用例：混合信号渲染三小节、全空渲染占位行、某环节抛异常时摘要仍
  完整返回且其余五节不受影响
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from core.self_review import (
    MIDFLIGHT_SCAN_MAX_LINES,
    SelfReviewScheduler,
    _collect_metrics_outliers,
    _collect_midflight_scans,
    _collect_rescue_traces,
    _scan_run_midflight,
)


# ── 夹具工具 ────────────────────────────────────────────────────────────


class FakeSM:
    def __init__(self, specs=None):
        self._specs = specs or {}

    def read_all(self):
        return self._specs


class FakeLogger:
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


def _run_id(tag: str, ts: float) -> str:
    """带内嵌开始时间戳的 run_id（-<10 位 unix 秒>，_RUN_TS_RE 可解析）。"""
    return f"impl-{tag}-{int(ts)}"


def _iso_utc(epoch: float) -> str:
    """epoch 秒 → stream-json 转录常见 ISO UTC 形态（Z 后缀）。"""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def env(tmp_path):
    """夹具项目：.fenix/runs + .fenix/logs 目录与窗口边界。"""
    root = tmp_path / "proj"
    runs_dir = root / ".fenix" / "runs"
    runs_dir.mkdir(parents=True)
    (root / ".fenix" / "logs").mkdir(parents=True)
    now = datetime.now()
    return {
        "root": root,
        "runs_dir": runs_dir,
        "log_path": root / ".fenix" / "logs" / "fenixd.log",
        "window_start": now - timedelta(hours=1),
        "window_end": now + timedelta(minutes=5),
    }


def _write_run_file(runs_dir: Path, run_id: str, lines) -> Path:
    """写 run 事件流产物（dict 逐行 JSON；str 原样写入供坏行用例）。"""
    p = runs_dir / f"{run_id}.jsonl"
    body = "\n".join(
        json.dumps(ln, ensure_ascii=False) if isinstance(ln, dict) else ln for ln in lines
    )
    p.write_text(body + "\n", encoding="utf-8")
    return p


def _append_metric(log_path: Path, run_id: str, agent_type="implementer", turns=10,
                   cost=None, duration=100.0, terminal="success") -> None:
    """向 fenixd.log 追加一条 run_metrics 指标行（runner._log_run_metrics 同形态）。"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": "INFO",
        "component": "agent_runner",
        "message": f"run metrics: {agent_type} {terminal} 'spec-{run_id}'",
        "context": {
            "metric_type": "run_metrics",
            "run_id": run_id,
            "spec": f"spec-{run_id}",
            "agent_type": agent_type,
            "duration_seconds": duration,
            "turns": turns,
            "input_tokens": 1000,
            "output_tokens": 2000,
            "cost_usd": cost,
            "terminal": terminal,
            "provider": "test-provider",
        },
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _stall_transcript(base_ts: float) -> list:
    """真实 stream-json 形态夹具：3 次 tool_result→assistant 间隔 > 60s + 2 条 stderr。

    工具结果以 user 事件包裹 tool_result content block 承载（禁用顶层
    tool_result 合成形态作主用例，_entry_is_tool_result 真实形态分支）。
    """
    t0 = base_ts
    return [
        {"type": "system", "subtype": "init", "timestamp": _iso_utc(t0)},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "go"}]},
         "timestamp": _iso_utc(t0)},
        {"type": "stderr", "line": "warn one"},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r1"}]},
         "timestamp": _iso_utc(t0 + 10)},
        # 停滞 1：tool_result → assistant 间隔 100s
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "a1"}]},
         "timestamp": _iso_utc(t0 + 110)},
        {"type": "stderr", "line": "warn two"},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r2"}]},
         "timestamp": _iso_utc(t0 + 200)},
        # 停滞 2：间隔 90s
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "a2"}]},
         "timestamp": _iso_utc(t0 + 290)},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r3"}]},
         "timestamp": _iso_utc(t0 + 300)},
        # 停滞 3：间隔 70s
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "a3"}]},
         "timestamp": _iso_utc(t0 + 370)},
        {"type": "result", "subtype": "success", "timestamp": _iso_utc(t0 + 375)},
    ]


def _make_scheduler(proot, logger=None):
    return SelfReviewScheduler(
        {"admin": {"enabled": True, "self_review": {"enabled": True, "run_at": "22:00"}}},
        proot,
        logger or FakeLogger(),
        FakeSM(),
        agent_runner=None,
        store=None,
    )


# ── 1.3 量化离群初筛 ───────────────────────────────────────────────────


class TestMetricsOutliers:
    def test_success_run_turns_outlier_selected_with_median(self, env):
        """成功但 turns 离群的 run 入选，附组中位对照；review- 前缀排除。"""
        now_ts = datetime.now().timestamp()
        ids = [_run_id(f"r{i}", now_ts - 60 * (i + 1)) for i in range(4)]
        # turns 8/10/10/45：中位 10，45 > 30 → 离群；终态 success
        turns = [8, 10, 10, 45]
        for i, rid in enumerate(ids):
            _write_run_file(env["runs_dir"], rid, [
                {"type": "result", "subtype": "success"},
            ])
            _append_metric(env["log_path"], rid, turns=turns[i],
                           duration=100.0 + i, terminal="success")
        # review- 前缀自省 run（turns 极大）不审视自身
        review_id = f"review-daily-{int(now_ts - 60)}"
        _write_run_file(env["runs_dir"], review_id, [])
        _append_metric(env["log_path"], review_id, turns=10000)

        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert [o["run_id"] for o in outliers] == [ids[3]]
        o = outliers[0]
        assert o["terminal"] == "success"
        assert o["agent_type"] == "implementer"
        assert o["outliers"]["turns"] == {"value": 45, "median": 10}
        assert o["path"].endswith(f"{ids[3]}.jsonl")
        assert "review-" not in o["run_id"]

    def test_small_group_skipped(self, env):
        """组内样本 < 3 不判离群（2 个 run 互为对照无意义）。"""
        now_ts = datetime.now().timestamp()
        for i in range(2):
            rid = _run_id(f"s{i}", now_ts - 60 * (i + 1))
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, turns=1000 if i else 3)
        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert outliers == []

    def test_cost_dim_all_missing_skipped(self, env):
        """cost_usd 全组缺失（provider 不回传）该维度跳过，不产假离群。"""
        now_ts = datetime.now().timestamp()
        for i in range(3):
            rid = _run_id(f"c{i}", now_ts - 60 * (i + 1))
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, turns=10 + i, cost=None)
        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert outliers == []

    def test_out_of_window_run_not_screened(self, env):
        """窗口外 run（run_id 内嵌时间戳在窗口之前）不入初筛。"""
        old_ts = datetime.now().timestamp() - 3600 * 3  # 3 小时前 < window_start
        rid = _run_id("old", old_ts)
        _write_run_file(env["runs_dir"], rid, [])
        for i in range(3):
            cur = _run_id(f"cur{i}", datetime.now().timestamp() - 60 * (i + 1))
            _write_run_file(env["runs_dir"], cur, [])
            _append_metric(env["log_path"], cur, turns=10 + i)
        _append_metric(env["log_path"], rid, turns=10000)
        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert outliers == []

    def test_index_error_returns_empty_list(self, env):
        """索引访问异常按缺失跳过：返回空 list，不抛错。"""
        now_ts = datetime.now().timestamp()
        rid = _run_id("x", now_ts - 60)
        _write_run_file(env["runs_dir"], rid, [])
        _append_metric(env["log_path"], rid, turns=1000)
        with mock.patch(
            "core.dashboard.data.runs.load_run_metric",
            side_effect=RuntimeError("index boom"),
        ):
            outliers = _collect_metrics_outliers(
                env["root"], env["window_start"], env["window_end"]
            )
        assert outliers == []


# ── 2.3 离群 run 事件流深扫 ───────────────────────────────────────────


class TestScanRunMidflight:
    def test_stall_and_stderr_collected_real_stream_json_shape(self, env):
        """user 包裹 tool_result 形态：stall=3、max_gap=100s、中途stderr=2。"""
        rid = _run_id("stall", datetime.now().timestamp() - 120)
        p = _write_run_file(env["runs_dir"], rid, _stall_transcript(datetime.now().timestamp() - 100))
        r = _scan_run_midflight(p)
        assert r["rounds"] == 3
        assert r["stalls"] == 3
        assert r["max_gap"] == pytest.approx(100.0)
        assert r["stderr_count"] == 2
        assert r["first_stderr"] == "warn one"
        assert r["error_count"] == 0
        assert r["truncated"] is False

    def test_first_stderr_skips_cli_noise_line(self, env):
        """first_stderr 跳过 CLI 启动期诊断噪声行，取首条非噪声行（D2）。

        [claude-code:unrecognized_model] 每 run 恒 1 条、与死因零相关；
        stderr_count 仍保留全量计数（含噪声行）。
        """
        rid = _run_id("noise", datetime.now().timestamp() - 120)
        lines = [
            {"type": "system", "subtype": "init"},
            {"type": "stderr",
             "line": "[claude-code:unrecognized_model] Model 'glm-5.3-flash' is not a valid model name"},
            {"type": "stderr", "line": "real diagnostic: ECONNRESET"},
        ]
        p = _write_run_file(env["runs_dir"], rid, lines)
        r = _scan_run_midflight(p)
        assert r["stderr_count"] == 2  # 计数保留全量（噪声行也计）
        assert r["first_stderr"] == "real diagnostic: ECONNRESET"

    def test_all_noise_stderr_left_blank(self, env):
        """stderr 全为噪声行时 first_stderr 置空，计数仍计（D2）。"""
        rid = _run_id("allnoise", datetime.now().timestamp() - 120)
        lines = [
            {"type": "stderr",
             "line": "[claude-code:unrecognized_model] Model 'deepseek-v4-flash' is not a valid model name"},
            {"type": "stderr",
             "line": "[claude-code:unrecognized_model] Model 'glm-5.3-flash' is not a valid model name"},
        ]
        p = _write_run_file(env["runs_dir"], rid, lines)
        r = _scan_run_midflight(p)
        assert r["stderr_count"] == 2
        assert r["first_stderr"] is None

    def test_error_events_counted_with_summary(self, env):
        """中途 error 终态行计数 + 首条摘要（≤140 字符）。"""
        rid = _run_id("err", datetime.now().timestamp() - 120)
        lines = [
            {"type": "error", "error": "x" * 200, "exit_code": 1},
            {"type": "error", "error": "second", "exit_code": 1},
        ]
        p = _write_run_file(env["runs_dir"], rid, lines)
        r = _scan_run_midflight(p)
        assert r["error_count"] == 2
        assert r["first_error"] == "x" * 140  # 截断至 140 字符
        assert r["stderr_count"] == 0

    def test_over_limit_truncated(self, env):
        """超过行数上限停止扫描并标注 truncated，上限外事件不采集。"""
        rid = _run_id("big", datetime.now().timestamp() - 120)
        lines = [{"type": "system", "subtype": "init"}] * 3
        lines.append({"type": "stderr", "line": "in-window stderr"})
        lines.append({"type": "user", "message": {"content": [{"type": "tool_result"}]}})
        lines.append({"type": "assistant", "timestamp": _iso_utc(datetime.now().timestamp())})
        lines.append({"type": "stderr", "line": "beyond limit"})
        p = _write_run_file(env["runs_dir"], rid, lines)
        r = _scan_run_midflight(p, max_lines=5)
        assert r["truncated"] is True
        assert r["stderr_count"] == 1  # 第 6 行起不再采集
        assert r["first_stderr"] == "in-window stderr"

    def test_default_max_lines_constant(self, env):
        """缺省行数上限 = MIDFLIGHT_SCAN_MAX_LINES（20000）。"""
        rid = _run_id("c", datetime.now().timestamp() - 120)
        p = _write_run_file(env["runs_dir"], rid, [{"type": "result"}])
        r = _scan_run_midflight(p)
        assert r["truncated"] is False  # 1 行 << 20000 不截断
        assert MIDFLIGHT_SCAN_MAX_LINES == 20000

    def test_bad_json_line_skipped(self, env):
        """单行坏 JSON（半行交错等）跳过不抛异常，计数与采样不受影响。"""
        rid = _run_id("bad", datetime.now().timestamp() - 120)
        ts = datetime.now().timestamp() - 100
        lines = _stall_transcript(ts)
        lines.insert(4, '{"type": "stderr", "line": "half-wr')  # 坏行
        lines.insert(5, "not json at all")
        p = _write_run_file(env["runs_dir"], rid, lines)
        r = _scan_run_midflight(p)
        assert r["stalls"] == 3
        # 坏行不计入 stderr 事件计数（解析失败跳过）
        assert r["stderr_count"] == 2

    def test_missing_file_zero_scan(self, env):
        """path 不存在按空产出（零值扫描），不抛异常。"""
        r = _scan_run_midflight(env["runs_dir"] / "nope-123.jsonl")
        assert r["stalls"] == 0
        assert r["max_gap"] is None
        assert r["error_count"] == 0
        assert r["truncated"] is False


class TestCollectMidflightScans:
    def test_no_outliers_returns_empty(self, env):
        assert _collect_midflight_scans(env["root"], [], env["window_start"], env["window_end"]) == []

    def test_scan_per_outlier_and_skip_missing_path(self, env):
        """逐个以 path 深扫；path 不存在的 run 跳过不阻断其余 run。"""
        now_ts = datetime.now().timestamp()
        good = _run_id("good", now_ts - 120)
        p = _write_run_file(env["runs_dir"], good, _stall_transcript(now_ts - 100))
        outliers = [
            {
                "run_id": good,
                "path": str(p),
                "agent_type": "implementer",
                "terminal": "success",
                "outliers": {"turns": {"value": 45, "median": 10}},
            },
            {
                "run_id": "impl-gone-123",
                "path": str(env["runs_dir"] / "impl-gone-123.jsonl"),
                "agent_type": "implementer",
                "terminal": "success",
                "outliers": {},
            },
        ]
        results = _collect_midflight_scans(
            env["root"], outliers, env["window_start"], env["window_end"]
        )
        assert len(results) == 1
        r = results[0]
        assert r["run_id"] == good
        assert r["terminal"] == "success"
        assert r["stalls"] == 3
        assert r["stderr_count"] == 2
        assert r["max_gap"] == pytest.approx(100.0)
        assert r["truncated"] is False


# ── 3.2 编排层救回痕迹归集 ────────────────────────────────────────────


class TestRescueTraces:
    @staticmethod
    def _append_log(log_path: Path, component: str, message: str, ts: datetime,
                    level="WARNING") -> None:
        entry = {
            "timestamp": ts.isoformat(),
            "level": level,
            "component": component,
            "message": message,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def test_mixed_traces_grouped_with_sample_cap(self, env):
        """窗口内混合痕迹按组计数；每组样本截断至 5。"""
        now = datetime.now()
        lp = env["log_path"]
        for i in range(2):
            self._append_log(lp, "agent_runner",
                             f"provider switched a → b for 'spec-{i}'", now)
        for i in range(7):
            self._append_log(lp, "agent_runner",
                             f"Transient error for 'spec-{i}' — in-place retry "
                             f"{i}/3 after 5s backoff", now)
        self._append_log(lp, "pm_engine",
                         "dispatch failed 'spec-x': Failed to create worktree "
                         "(gave up: parallel run or manual freeze)", now, level="ERROR")
        groups = _collect_rescue_traces(env["root"], env["window_start"], env["window_end"])
        assert groups["provider switched"]["count"] == 2
        assert groups["in-place retry"]["count"] == 7
        assert groups["gave up"]["count"] == 1
        assert len(groups["in-place retry"]["samples"]) == 5  # 样本截断至 5
        assert len(groups["provider switched"]["samples"]) == 2
        assert "provider switched" in groups["provider switched"]["samples"][0]
        assert "[agent_runner]" in groups["provider switched"]["samples"][0]

    def test_keyword_component_pairing_and_noise(self, env):
        """关键词与组件成对绑定：泛词 retry/错误组件命中的行不计入。"""
        now = datetime.now()
        lp = env["log_path"]
        # 泛词 retry（event_bus 噪声）不匹配任何「关键词→组件」对
        self._append_log(lp, "event_bus", "retry scheduled for spec-y", now)
        # 关键词命中但组件不配对
        self._append_log(lp, "pm_engine", "provider switched a → b for 'spec-z'", now)
        self._append_log(lp, "agent_runner", "gave up hint in wrong component", now)
        groups = _collect_rescue_traces(env["root"], env["window_start"], env["window_end"])
        assert groups == {}

    def test_out_of_window_lines_not_counted(self, env):
        """窗口外（早于 window_start / 晚于 window_end）行不计入。"""
        now = datetime.now()
        lp = env["log_path"]
        self._append_log(lp, "agent_runner", "provider switched a → b", now)
        self._append_log(lp, "agent_runner", "provider switched a → b",
                         now - timedelta(hours=2))  # 窗口前
        self._append_log(lp, "agent_runner", "provider switched a → b",
                         now + timedelta(hours=2))  # 窗口后
        groups = _collect_rescue_traces(env["root"], env["window_start"], env["window_end"])
        assert groups["provider switched"]["count"] == 1

    def test_missing_log_returns_empty(self, env):
        """日志文件缺失降级空 dict。"""
        assert _collect_rescue_traces(env["root"], env["window_start"], env["window_end"]) == {}

    def test_bad_lines_and_noise_ignored(self, env):
        """坏 JSON 行与非 object 行跳过，不阻断归集。"""
        now = datetime.now()
        with env["log_path"].open("a", encoding="utf-8") as f:
            f.write("not-json\n")
            f.write(json.dumps([1, 2]) + "\n")
            f.write(json.dumps({
                "timestamp": now.isoformat(), "level": "WARNING",
                "component": "agent_runner", "message": "provider switched a → b",
            }) + "\n")
        groups = _collect_rescue_traces(env["root"], env["window_start"], env["window_end"])
        assert groups["provider switched"]["count"] == 1


# ── 4.3 摘要注入 ──────────────────────────────────────────────────────


class TestDailySummarySection6:
    def test_mixed_signals_render_three_subsections(self, env):
        """混合信号：初筛离群、深扫、救回痕迹三小节依次渲染，前五节不受影响。"""
        now_ts = datetime.now().timestamp()
        now = datetime.now()
        turns = [10, 12, 90]
        ids = []
        for i, t in enumerate(turns):
            rid = _run_id(f"m{i}", now_ts - 120 - i)
            ids.append(rid)
            lines = (
                _stall_transcript(now_ts - 100)
                if i == 2
                else [{"type": "result", "subtype": "success"}]
            )
            _write_run_file(env["runs_dir"], rid, lines)
            _append_metric(env["log_path"], rid, turns=t, duration=100.0 + i * 10,
                           terminal="success" if i == 2 else "success")
        with env["log_path"].open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": now.isoformat(), "level": "WARNING",
                "component": "agent_runner",
                "message": "provider switched p1 → p2 for 'spec-m2'",
            }) + "\n")

        summary = _make_scheduler(env["root"]).collect_daily_summary(env["window_start"])
        assert "## 6. 中途信号（含成功 run）" in summary
        assert "### 初筛离群 run（run_metrics 量化，> 组中位 ×3）" in summary
        assert f"{ids[2]}（implementer）：turns=90（组中位 12，成功收尾）" in summary
        assert "### 离群 run 事件流深扫（API 停滞与中途 error）" in summary
        assert f"- {ids[2]}: stall=3 max_gap=100.0s 中途stderr=2" in summary
        assert "### 编排救回痕迹（fenixd.log 关键词归组）" in summary
        assert "provider switched=1" in summary
        # 既有五节保持完整
        for head in ("## 1. STATE 终态分布", "## 2. runs 统计（窗口内）",
                     "## 3. admin 告警与处置记录（窗口内）", "## 4. 日志 ERROR 聚合（窗口内）",
                     "## 5. 近 3 日 git 提交"):
            assert head in summary

    def test_all_empty_renders_placeholder(self, tmp_path):
        """全部信号为空时渲染占位行（形态稳定）。"""
        root = tmp_path / "proj"
        (root / ".fenix" / "runs").mkdir(parents=True)
        (root / ".fenix" / "logs").mkdir(parents=True)
        summary = _make_scheduler(root).collect_daily_summary(
            datetime.now() - timedelta(hours=1)
        )
        assert "## 6. 中途信号（含成功 run）" in summary
        assert "- （窗口内无中途信号）" in summary

    def test_section_exception_degrades_and_keeps_other_sections(self, env):
        """初筛环节抛异常：降级空产出 + warning，摘要完整返回且其余五节不受影响。"""
        now_ts = datetime.now().timestamp()
        rid = _run_id("boom", now_ts - 60)
        _write_run_file(env["runs_dir"], rid, [])
        logger = FakeLogger()
        with mock.patch(
            "core.self_review._collect_metrics_outliers",
            side_effect=RuntimeError("screening boom"),
        ):
            summary = _make_scheduler(env["root"], logger).collect_daily_summary(
                env["window_start"]
            )
        # 摘要完整返回：第六节与其余五节均在
        assert "## 6. 中途信号（含成功 run）" in summary
        assert "- （窗口内无中途信号）" in summary
        for head in ("## 1. STATE 终态分布", "## 2. runs 统计（窗口内）",
                     "## 3. admin 告警与处置记录（窗口内）", "## 4. 日志 ERROR 聚合（窗口内）",
                     "## 5. 近 3 日 git 提交"):
            assert head in summary
        # 降级留痕 warning
        assert any("screening boom" in str(w) for w in logger.warnings)
