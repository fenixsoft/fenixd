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

import io
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
    # aware 本地当前时刻（批①：窗口气泡迁 aware，替身边界与生产同批迁移）
    now = datetime.now().astimezone()
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
                   cost=None, duration=100.0, terminal="success", spec=None,
                   model=None) -> None:
    """向 fenixd.log 追加一条 run_metrics 指标行（runner._log_run_metrics 同形态）。

    agent_type=None 时省略该字段——evo-add-run-metrics-lane-baseline 1.3 之前
    maintenance 三车道与 context metrics 兜底行的历史形态，供 run_id 前缀推断
    分组用例使用。spec=None 时落 f"spec-{run_id}"（既有形态）；显式传 None 之外
    的值供摊薄口径用例指向真实 tasks.md。model 供 2.1/2.2 落行与渲染用例。
    """
    context = {
        "metric_type": "run_metrics",
        "run_id": run_id,
        "spec": spec or f"spec-{run_id}",
        "duration_seconds": duration,
        "turns": turns,
        "input_tokens": 1000,
        "output_tokens": 2000,
        "cost_usd": cost,
        "terminal": terminal,
        "provider": "test-provider",
    }
    if model is not None:
        context["model"] = model
    if agent_type is not None:
        context["agent_type"] = agent_type
    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": "INFO",
        "component": "agent_runner",
        "message": f"run metrics: {agent_type} {terminal} '{context['spec']}'",
        "context": context,
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
        assert r["stderr_noise_count"] == 0  # 夹具两条 stderr 均为真实行
        assert r["first_stderr"] == "warn one"
        assert r["error_count"] == 0
        assert r["truncated"] is False

    def test_first_stderr_skips_cli_noise_line(self, env):
        """first_stderr 跳过 CLI 启动期诊断噪声行，取首条非噪声行（D2）。

        [claude-code:unrecognized_model] 每 run 恒 1 条、与死因零相关；
        计数按噪声分离：stderr_count 只计非噪声行，噪声行走
        stderr_noise_count 单独累计。
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
        assert r["stderr_count"] == 1  # 只计真实行（噪声行已剥离）
        assert r["stderr_noise_count"] == 1
        assert r["first_stderr"] == "real diagnostic: ECONNRESET"

    def test_all_noise_stderr_left_blank(self, env):
        """stderr 全为噪声行时 first_stderr 置空，stderr_count 归零、
        stderr_noise_count 计满（D2 + 计数分离）。"""
        rid = _run_id("allnoise", datetime.now().timestamp() - 120)
        lines = [
            {"type": "stderr",
             "line": "[claude-code:unrecognized_model] Model 'deepseek-v4-flash' is not a valid model name"},
            {"type": "stderr",
             "line": "[claude-code:unrecognized_model] Model 'glm-5.3-flash' is not a valid model name"},
        ]
        p = _write_run_file(env["runs_dir"], rid, lines)
        r = _scan_run_midflight(p)
        assert r["stderr_count"] == 0
        assert r["stderr_noise_count"] == 2  # 噪声行数单独计满
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


# ── 4.4 深扫行噪声注记（split-self-review-stderr-noise-count）─────────


class TestMidflightScanRowNoiseAnnotation:
    """深扫行「中途stderr=」非噪声口径 + 噪声同行注记（渲染层）。"""

    @staticmethod
    def _outlier_summary(env, transcript):
        """构造 turns 离群 run（90 vs 组 10/12）并返回每日摘要与离群 run_id。"""
        now_ts = datetime.now().timestamp()
        rid = _run_id("nz", now_ts - 120)
        _write_run_file(env["runs_dir"], rid, transcript)
        for i, t in enumerate((10, 12, 90)):
            pad = _run_id(f"p{i}", now_ts - 130 - i)
            _write_run_file(env["runs_dir"], pad, [{"type": "result", "subtype": "success"}])
            _append_metric(env["log_path"], pad if t != 90 else rid,
                           turns=t, duration=100.0 + i * 10, terminal="success")
        summary = _make_scheduler(env["root"]).collect_daily_summary(env["window_start"])
        return rid, summary

    def test_noise_only_run_renders_annotation(self, env):
        """离群 run stderr 仅为 1 条已知启动噪声：呈现
        「中途stderr=0（另 1 条已知 CLI 启动噪声）」，定噪不再冒充信号。"""
        rid, summary = self._outlier_summary(env, [
            {"type": "system", "subtype": "init"},
            {"type": "stderr",
             "line": "[claude-code:unrecognized_model] Model 'glm-5.3-flash' is not a valid model name"},
            {"type": "result", "subtype": "success"},
        ])
        assert "### 离群 run 事件流深扫（API 停滞与中途 error）" in summary
        assert f"- {rid}: stall=0 中途stderr=0（另 1 条已知 CLI 启动噪声）" in summary
        assert "中途stderr=1" not in summary  # 噪声行不计入主计数

    def test_real_only_run_keeps_plain_shape(self, env):
        """对照档案无噪声行（真实诊断行 1 条）：行形如「中途stderr=1」
        且不含噪声注记。"""
        rid, summary = self._outlier_summary(env, [
            {"type": "system", "subtype": "init"},
            {"type": "stderr", "line": "real diagnostic: ECONNRESET"},
            {"type": "result", "subtype": "success"},
        ])
        assert f"- {rid}: stall=0 中途stderr=1" in summary
        assert "已知 CLI 启动噪声" not in summary


# ── evo-add-run-metrics-lane-baseline：分组兜底与车道基线 ──────────────


class TestLaneGroupingBaseline:
    """1.1/2.1：缺 agent_type 行按 run_id 前缀归组 + 批量车道 P90 基线。"""

    def test_mixed_window_grouped_by_run_id_prefix(self, env):
        """无 agent_type 指标行 + code-fix/evo/spec-review 混合窗口：各组按
        前缀推断/显式字段归组判定，不再落 unknown 混合组。"""
        now_ts = datetime.now().timestamp()
        # code-fix 组（无 agent_type 字段，前缀推断）：3 样本有效批，其中
        # 400 的近批 peers 仅 2 个 < 3 → 回退窗口中位 50 → 400 > 150 旗标
        for i, t in enumerate([48, 50, 400]):
            rid = f"code-fix-m{i}-{int(now_ts) - 60 * (i + 1)}"
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, agent_type=None, turns=t)
        # evolution 组（evo- 前缀推断，非批量车道 → 窗口中位）：中位 12×3=36
        for i, t in enumerate([10, 12, 200]):
            rid = f"evo-{int(now_ts) - 60 * (10 + i)}"
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, agent_type=None, turns=t)
        # spec-review 组（显式 agent_type，既有行为不回退）：中位 9×3=27
        for i, t in enumerate([8, 9, 100]):
            rid = f"spec-review-s{i}-{int(now_ts) - 60 * (20 + i)}"
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, agent_type="spec-review", turns=t)

        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        by_type = {o["agent_type"] for o in outliers}
        assert by_type == {"code-fix", "evolution", "spec-review"}
        # evo- 前缀推断断言：evolution 组旗标 run 确为 evo- 前缀产物
        evo = next(o for o in outliers if o["agent_type"] == "evolution")
        assert evo["run_id"].startswith("evo-")
        # 非批量车道基线仍为窗口中位（无 baseline_kind 注记），形态不回退
        assert evo["outliers"]["turns"] == {"value": 200, "median": 12}
        # spec-review 显式 agent_type 行为不变
        sr = next(o for o in outliers if o["agent_type"] == "spec-review")
        assert sr["run_id"].startswith("spec-review-")
        assert sr["outliers"]["turns"] == {"value": 100, "median": 9}
        # code-fix 组：peers < 3 回退窗口中位（基线 50，无 baseline_kind）
        cf = next(o for o in outliers if o["agent_type"] == "code-fix")
        assert cf["run_id"].startswith("code-fix-")
        assert cf["outliers"]["turns"] == {"value": 400, "median": 50}

    def test_small_group_skip_after_prefix_inference(self, env):
        """前缀推断后组内样本 < 3 仍跳过（跳过语义不回退）。"""
        now_ts = datetime.now().timestamp()
        for i in range(2):
            rid = f"code-fix-s{i}-{int(now_ts) - 60 * (i + 1)}"
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, agent_type=None,
                           turns=1000 if i else 3)
        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert outliers == []

    def test_p90_baseline_normal_long_batch_not_flagged(self, env):
        """code-fix 正常长批不再越线（近 10 批 P90 基线），超分布异常批仍被
        标出且附 baseline_kind 注记。

        实景对应 proposal 基线：组内中位 49×3=147 < 正常批 158 全员误报；
        P90 基线下 158 落分布内、3000 仍超 P90×3。"""
        now_ts = datetime.now().timestamp()
        turns = [45, 48, 49, 50, 50, 52, 55, 58, 60]
        ids = {}
        for i, t in enumerate(turns):
            rid = f"code-fix-b{i}-{int(now_ts) - 60 * (i + 2)}"
            ids[rid] = t
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, agent_type=None, turns=t)
        long_id = f"code-fix-long-{int(now_ts) - 120}"
        _write_run_file(env["runs_dir"], long_id, [])
        _append_metric(env["log_path"], long_id, agent_type=None, turns=158)
        bad_id = f"code-fix-bad-{int(now_ts) - 60}"
        _write_run_file(env["runs_dir"], bad_id, [])
        _append_metric(env["log_path"], bad_id, agent_type=None, turns=3000)

        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        flagged = {o["run_id"]: o for o in outliers}
        # 正常长批 158 不再越线（中位 49×3=147 的旧误报消除）
        assert long_id not in flagged
        # 异常批仍被标出：基线 = 近 10 批 P90（排除自身后的近批样本）
        assert set(flagged) == {bad_id}
        entry = flagged[bad_id]["outliers"]["turns"]
        assert entry["value"] == 3000
        assert entry["baseline_kind"] == "p90_recent_batches"
        # bad 的 peers = 全部非自身有效批按时间倒序取 10 = [158,60,58,55,52,
        # 50,50,49,48,45] → 最近秩 P90 = 升序第 9 个 = 60
        assert entry["median"] == 60

    def test_retry_run_excluded_from_baseline_sample(self, env):
        """重试轮（-r/-a 后缀，与 runs.py 剥后缀同口径）不入基线样本：
        排除后 P90 取正常批分布，重试轮自身仍按同基线参与判定。"""
        now_ts = int(datetime.now().timestamp())
        # 9 个正常批（turns 40）+ 1 个大批（base stem + -r2 重试 stem 共享
        # 基础 id 指标，形态对齐生产：指标日志记基础 run_id、产物按 attempt
        # 分文件）+ 候选批 200。
        # 若重试 stem 不排除：peers 含两个 500 → P90=500 → 200 不旗标；
        # 排除后 peers=10 → P90=40 → 200 > 120 旗标（断言翻转靠排除成立）。
        for i in range(9):
            rid = f"code-fix-n{i}-{now_ts - 60 * (i + 3)}"
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, agent_type=None, turns=40)
        big = f"code-fix-big-{now_ts - 120}"
        big_retry = f"{big}-r2"
        for stem in (big, big_retry):
            _write_run_file(env["runs_dir"], stem, [])
        _append_metric(env["log_path"], big, agent_type=None, turns=500)
        cand = f"code-fix-cand-{now_ts - 60}"
        _write_run_file(env["runs_dir"], cand, [])
        _append_metric(env["log_path"], cand, agent_type=None, turns=200)

        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        flagged = {o["run_id"]: o for o in outliers}
        assert cand in flagged
        assert flagged[cand]["outliers"]["turns"]["median"] == 40

    def test_cost_dim_visible_for_lane_via_rich_row(self, env):
        """maintenance 车道成本维度可观测（spec「未分组车道的成本维度可观测」）：
        design 二选一取写侧——三车道收尾补 _log_run_metrics 富指标行（含
        cost_usd）后，无 agent_type 行的成本样本参与组基线判定（85.68 美元型
        全仓扫描不再失明）。"""
        now_ts = datetime.now().timestamp()
        costs = [1.0, 1.2, 30.0]
        for i, c in enumerate(costs):
            rid = f"code-fix-c{i}-{int(now_ts) - 60 * (i + 1)}"
            _write_run_file(env["runs_dir"], rid, [])
            _append_metric(env["log_path"], rid, agent_type=None, turns=50, cost=c)
        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert len(outliers) == 1
        assert outliers[0]["outliers"]["cost_usd"] == {"value": 30.0, "median": 1.2}


# ── evo-add-run-metrics-lane-baseline 3.2：前缀表同源行为回归 ──────────


class TestRunFilesPrefixTableSameSource:
    """RUN_ID_AGENT_PREFIXES 补 evo- 后，dashboard/get_runs 时间线归属与
    run_spec_part 语义不回退（同一前缀表唯一真源的同源消费方）。"""

    def test_get_runs_attributes_evo_run_to_evolution(self, tmp_path):
        """时间线归属 agent→evolution（预期修复，此前退化为泛型 "agent"）。"""
        from core.dashboard.data.runs import get_runs

        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "evo-1791395158.jsonl").write_text(
            '{"type": "result"}\n', encoding="utf-8"
        )
        rows = get_runs(str(tmp_path))
        assert len(rows) == 1
        assert rows[0]["run_id"] == "evo-1791395158"
        assert rows[0]["agent_type"] == "evolution"

    def test_run_spec_part_evo_epoch_yields_bare_epoch_segment(self):
        """evo-<epoch> 的 run_spec_part = 裸 epoch 段（此前为伪 spec「evo」）：
        两侧均不等于真实 spec 名，全等守卫不回退。"""
        from core.agent_runner.run_files import infer_run_agent_type, run_spec_part

        assert infer_run_agent_type("evo-1791395158") == ("evolution", "1791395158")
        spec_part = run_spec_part("evo-1791395158")
        assert spec_part == "1791395158"
        # 不得解析出真实 spec 名（新旧行为均非真实 spec 名，守卫语义不变）
        assert spec_part != "evo"


# ── evo-refine-midflight-outlier-dims：摊薄口径 / 纯文本轮占比 / model ──


def _write_spec_tasks(root: Path, spec_name: str, n: int) -> None:
    """夹具项目写 spec 的 tasks.md（n 条数字任务），供 parse_tasks_md 取台账
    条目数（len(all)）。"""
    tasks_dir = root / "spec" / "changes" / spec_name
    tasks_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- [ ] {i + 1}.1 任务 {i + 1}" for i in range(n))
    (tasks_dir / "tasks.md").write_text(
        f"# Tasks\n\n## 1. 分组\n\n{body}\n", encoding="utf-8"
    )


class TestBatchLaneDilution:
    """1.1：批量车道 cost_usd/duration_seconds 维按台账条目数摊薄对比。"""

    def test_batch_run_not_flagged_after_dilution(self, env):
        """复刻 2026-10-17 窗形态：修 9 条、cost 3.401011、521.22 秒对单条目
        小 run 组（绝对口径 7.05×/3.55× 误标），摊薄后不标离群。"""
        now_ts = int(datetime.now().timestamp())
        # 组内 3 个单条目小 run：cost 中位 0.483、duration 中位 146.85
        smalls = [(0.48, 140.0), (0.483, 146.85), (0.49, 150.0)]
        for i, (c, d) in enumerate(smalls):
            rid = f"code-fix-small{i}-{now_ts - 60 * (i + 3)}"
            _write_spec_tasks(env["root"], f"spec-{rid}", 1)
            _write_run_file(env["runs_dir"], rid, [
                {"type": "result", "subtype": "success"},
            ])
            _append_metric(env["log_path"], rid, agent_type=None, turns=30,
                           cost=c, duration=d, spec=f"spec-{rid}")
        # 大批 run：修 9 条（turns=45 落近批 P90 分布内，隔离 cost/duration 维）
        big = f"code-fix-big-{now_ts - 120}"
        _write_spec_tasks(env["root"], f"spec-{big}", 9)
        _write_run_file(env["runs_dir"], big, [
            {"type": "result", "subtype": "success"},
        ])
        _append_metric(env["log_path"], big, agent_type=None, turns=45,
                       cost=3.401011, duration=521.22, spec=f"spec-{big}")

        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        flagged = {o["run_id"] for o in outliers}
        # 绝对口径下 3.401 > 0.483×3、521.22 > 146.85×3 必标；摊薄后
        # 0.3779/条 vs 0.483/条、57.91s/条 vs 146.85s/条 均 < 3× → 不标
        assert big not in flagged
        assert not flagged

    def test_diluted_outlier_still_flagged_with_per_task_entry(self, env):
        """摊薄显著超基线的 run 仍标离群，entry 携带摊薄前后两对数字与分母。"""
        now_ts = int(datetime.now().timestamp())
        for i, c in enumerate([0.9, 1.0, 1.1]):
            rid = f"code-fix-s{i}-{now_ts - 60 * (i + 3)}"
            _write_spec_tasks(env["root"], f"spec-{rid}", 1)
            _write_run_file(env["runs_dir"], rid, [
                {"type": "result", "subtype": "success"},
            ])
            _append_metric(env["log_path"], rid, agent_type=None, turns=30,
                           cost=c, duration=100.0, spec=f"spec-{rid}")
        # 大 run：2 条目、cost 30（摊薄 15/条 > 组摊薄中位 1.05×3）；duration
        # 240（120/条 < 100×3 不标）；turns 30（P90 基线 30 不标）
        big = f"code-fix-big-{now_ts - 120}"
        _write_spec_tasks(env["root"], f"spec-{big}", 2)
        _write_run_file(env["runs_dir"], big, [
            {"type": "result", "subtype": "success"},
        ])
        _append_metric(env["log_path"], big, agent_type=None, turns=30,
                       cost=30.0, duration=240.0, spec=f"spec-{big}")

        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert [o["run_id"] for o in outliers] == [big]
        entry = outliers[0]["outliers"]["cost_usd"]
        assert entry["baseline_kind"] == "per_task_median"
        assert entry["value"] == pytest.approx(15.0)
        # 组基线=摊薄中位（含自身，窗口中位语义同现状）：median([0.9,1.0,1.1,15])
        assert entry["median"] == pytest.approx(1.05)
        # 摊薄前后两对数字 + 分母（摘要行人工对账用）
        assert entry["raw_value"] == 30.0
        assert entry["raw_median"] == pytest.approx(1.05)
        assert entry["task_count"] == 2
        # duration 维摊薄后不标
        assert "duration_seconds" not in outliers[0]["outliers"]

    def test_missing_entry_count_whole_dim_falls_back_absolute(self, env):
        """组内任一 run 条目数不可得（spec 无 tasks.md）→ 该维整组回退绝对
        口径：大批 run 按 7.05× 绝对倍数标出（单一基线不混口径）。"""
        now_ts = int(datetime.now().timestamp())
        for i, c in enumerate([0.48, 0.483, 0.49]):
            rid = f"code-fix-small{i}-{now_ts - 60 * (i + 3)}"
            if i != 1:
                # small-1 的 spec 无 tasks.md → 条目数不可得
                _write_spec_tasks(env["root"], f"spec-{rid}", 1)
            _write_run_file(env["runs_dir"], rid, [
                {"type": "result", "subtype": "success"},
            ])
            _append_metric(env["log_path"], rid, agent_type=None, turns=30,
                           cost=c, duration=146.85, spec=f"spec-{rid}")
        big = f"code-fix-big-{now_ts - 120}"
        _write_spec_tasks(env["root"], f"spec-{big}", 9)
        _write_run_file(env["runs_dir"], big, [
            {"type": "result", "subtype": "success"},
        ])
        _append_metric(env["log_path"], big, agent_type=None, turns=45,
                       cost=3.401011, duration=521.22, spec=f"spec-{big}")

        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        by_id = {o["run_id"]: o for o in outliers}
        entry = by_id[big]["outliers"]["cost_usd"]
        # 绝对口径：无 baseline_kind 注记，value/median 均为原始值（组中位含
        # 自身：median([0.48, 0.483, 0.49, 3.401011])=0.4865）
        assert "baseline_kind" not in entry
        assert entry["value"] == 3.401011
        assert entry["median"] == pytest.approx(0.4865)

    def test_single_entry_run_behaves_as_absolute(self, env):
        """单条目 run 行为与现状一致（摊薄后等于原值）：摊薄口径下仍按绝对
        数值判定与呈现，仅基线标签注记为摊薄组中位。"""
        now_ts = int(datetime.now().timestamp())
        for i, c in enumerate([0.9, 1.0, 1.1]):
            rid = f"code-fix-s{i}-{now_ts - 60 * (i + 3)}"
            _write_spec_tasks(env["root"], f"spec-{rid}", 1)
            _write_run_file(env["runs_dir"], rid, [
                {"type": "result", "subtype": "success"},
            ])
            _append_metric(env["log_path"], rid, agent_type=None, turns=30,
                           cost=c, duration=100.0, spec=f"spec-{rid}")
        # 单条目大 cost run：摊薄不改变数值
        big = f"code-fix-big-{now_ts - 120}"
        _write_spec_tasks(env["root"], f"spec-{big}", 1)
        _write_run_file(env["runs_dir"], big, [
            {"type": "result", "subtype": "success"},
        ])
        _append_metric(env["log_path"], big, agent_type=None, turns=30,
                       cost=30.0, duration=100.0, spec=f"spec-{big}")

        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        by_id = {o["run_id"]: o for o in outliers}
        entry = by_id[big]["outliers"]["cost_usd"]
        assert entry["value"] == 30.0
        assert entry["raw_value"] == 30.0
        assert entry["median"] == pytest.approx(1.05)
        assert entry["task_count"] == 1

    def test_diluted_and_model_rendered_in_summary(self, env):
        """摘要行摊薄前后数值与 model 附带渲染（1.1 摘要 + 2.2）。"""
        now_ts = int(datetime.now().timestamp())
        for i, c in enumerate([0.9, 1.0, 1.1]):
            rid = f"code-fix-s{i}-{now_ts - 60 * (i + 3)}"
            _write_spec_tasks(env["root"], f"spec-{rid}", 1)
            _write_run_file(env["runs_dir"], rid, [
                {"type": "result", "subtype": "success"},
            ])
            _append_metric(env["log_path"], rid, agent_type=None, turns=30,
                           cost=c, duration=100.0, spec=f"spec-{rid}")
        big = f"code-fix-big-{now_ts - 120}"
        _write_spec_tasks(env["root"], f"spec-{big}", 2)
        _write_run_file(env["runs_dir"], big, [
            {"type": "result", "subtype": "success"},
        ])
        _append_metric(env["log_path"], big, agent_type=None, turns=30,
                       cost=30.0, duration=100.0, spec=f"spec-{big}",
                       model="deepseek-v4-flash", terminal="success")

        section = _make_scheduler(env["root"])._collect_midflight_section(
            env["window_start"], env["window_end"]
        )
        text = "\n".join(section)
        # 行头附 model
        assert f"- {big}（code-fix，model=deepseek-v4-flash）：" in text
        # 摊薄行同时给摊薄前后数值：value=15/条、基线 1.05/条、分母 2、
        # 原值 30.0 对 组中位 1.05、成功收尾
        assert (
            f"cost_usd=15/条（摊薄组中位 1.05/条，分母 2；原值 30.0 对 "
            f"组中位 1.05，成功收尾）" in text
        )


class TestTextTurnRatioDim:
    """1.2：纯文本轮占比维度（双条件阈值判定，context 行原始取数）。"""

    @staticmethod
    def _ctx_metrics_row(turns, text_turns=None):
        """context metrics 转录行形态（runner._run_agent 收尾 finally 落盘）。"""
        row = {
            "type": "run_metrics",
            "run_id": "rid",
            "duration_s": 100.0,
            "turns": turns,
            "text_turns": text_turns,
            "tool_uses_total": 3,
        }
        if text_turns is None:
            row.pop("text_turns")  # dsh 通道/历史行形态：整字段缺席
        return row

    def _seed(self, env, rid, turns, text_turns=None, model=None):
        _write_run_file(env["runs_dir"], rid, [
            self._ctx_metrics_row(turns, text_turns),
            {"type": "result", "subtype": "success"},
        ])
        _append_metric(env["log_path"], rid, agent_type=None, turns=turns,
                       model=model)

    def test_high_turns_high_ratio_flags(self, env):
        """turns=204、text_turns=125（2026-10-17 窗形态）→ 标纯文本轮占比。"""
        now_ts = int(datetime.now().timestamp())
        rid = f"code-fix-text-{now_ts - 60}"
        self._seed(env, rid, turns=204, text_turns=125)
        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert [o["run_id"] for o in outliers] == [rid]
        entry = outliers[0]["outliers"]["text_turns"]
        assert entry["baseline_kind"] == "text_turn_ratio"
        assert entry["value"] == pytest.approx(125 / 204)
        assert entry["median"] == 0.5
        assert entry["text_turn_count"] == 125
        assert entry["turns_count"] == 204

    def test_baseline_batch_shape_not_flagged(self, env):
        """基线批形态（turns=104、text_turns=22，占比 21%）→ 不标。"""
        now_ts = int(datetime.now().timestamp())
        rid = f"code-fix-base-{now_ts - 60}"
        self._seed(env, rid, turns=104, text_turns=22)
        assert _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        ) == []

    def test_low_turns_high_ratio_not_flagged(self, env):
        """低轮数高占比（4 轮中 3 轮纯文本）→ 不标（绝对轮数条件挡噪音）。"""
        now_ts = int(datetime.now().timestamp())
        rid = f"code-fix-low-{now_ts - 60}"
        self._seed(env, rid, turns=4, text_turns=3)
        assert _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        ) == []

    def test_ratio_boundary_strictly_above(self, env):
        """占比恰等于阈值（100/200=50%）不标；严格超阈值（101/200）标。"""
        now_ts = int(datetime.now().timestamp())
        at = f"code-fix-at-{now_ts - 120}"
        self._seed(env, at, turns=200, text_turns=100)
        assert _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        ) == []
        above = f"code-fix-above-{now_ts - 60}"
        self._seed(env, above, turns=200, text_turns=101)
        outliers = _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        )
        assert [o["run_id"] for o in outliers] == [above]

    def test_missing_text_turns_field_skipped(self, env):
        """context 行缺 text_turns 字段（dsh 通道/历史行）→ 该 run 该维跳过。"""
        now_ts = int(datetime.now().timestamp())
        rid = f"code-fix-dsh-{now_ts - 60}"
        self._seed(env, rid, turns=204, text_turns=None)
        assert _collect_metrics_outliers(
            env["root"], env["window_start"], env["window_end"]
        ) == []

    def test_text_ratio_and_model_rendered_in_summary(self, env):
        """摘要行纯文本轮占比形态渲染：计数/占比/双条件阈值 + model 附带。"""
        now_ts = int(datetime.now().timestamp())
        rid = f"code-fix-text-{now_ts - 60}"
        self._seed(env, rid, turns=204, text_turns=125, model="glm-5.3-flash")
        section = _make_scheduler(env["root"])._collect_midflight_section(
            env["window_start"], env["window_end"]
        )
        text = "\n".join(section)
        assert f"- {rid}（code-fix，model=glm-5.3-flash）：" in text
        assert (
            "text_turns=125/204（占比 61.3%，阈值 turns>100 且占比>50%，"
            "成功收尾）" in text
        )


# ── 2.1 run_metrics 补 model 字段（runner 侧三行落盘断言） ─────────────


class _MetricsCaptureLogger:
    """捕获 info 调用的假 logger（日志侧 context metrics 行断言用）。"""

    def __init__(self):
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.infos.append((a, k))

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeSpawnProc:
    """假 Popen：stdout 预载脚本化转录（StringIO 逐行 readline），秒退。

    pid 取正但不可能存在（2**22 > Linux 默认 pid_max），对齐
    add-killpg-self-guard 对替身进程组的口径（killpg 不可误伤本进程）。
    """

    UNREACHABLE_PID = 2**22

    def __init__(self, out_lines):
        self.stdout = io.StringIO("".join(line + "\n" for line in out_lines))
        self.stderr = io.StringIO("")
        self.stdin = io.StringIO("")  # _feed_stdin 线程写入目标，避免线程异常告警
        self.pid = _FakeSpawnProc.UNREACHABLE_PID

    def poll(self):
        return 0

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def _make_metrics_runner(proot: Path, logger) -> "AgentRunner":
    """最小 AgentRunner（__new__ 绕过 __init__），缝对齐
    test_codefix_digest_metrics._make_runner（真实 _run_agent 可驱动）。"""
    from core.agent_runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = logger
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    runner._worktree_path_valid = lambda p: False
    return runner


class TestRunMetricsModelField:
    """2.1/3.2：run_metrics 三行（转录行/日志侧 context 行/终态行）model 落行。"""

    RESULT_LINE = json.dumps({
        "type": "result", "subtype": "success", "result": "ok",
        "num_turns": 3, "session_id": "s",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }, ensure_ascii=False)

    def _drive(self, proot, run_id, model):
        from core.agent_runner import runner as runner_module

        logger = _MetricsCaptureLogger()
        runner = _make_metrics_runner(proot, logger)
        orig_popen = runner_module.subprocess.Popen
        runner_module.subprocess.Popen = (
            lambda cmd, **kw: _FakeSpawnProc([self.RESULT_LINE])
        )
        try:
            runner._run_agent(
                "prompt", proot, run_id,
                model_override=model, max_turns=50,
                spec_name="spec-x", agent_type="implementer",
            )
        finally:
            runner_module.subprocess.Popen = orig_popen
        return logger

    def test_context_metrics_rows_carry_model(self, tmp_path):
        """转录行（type=run_metrics）与日志侧行（metric_type=run_metrics）
        均落实际 --model 值（原样记录不归一）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        rid = "code-fix-model-x1"
        logger = self._drive(proot, rid, "deepseek-v4-flash")

        run_file = proot / ".fenix" / "runs" / f"{rid}.jsonl"
        rows = [
            json.loads(line)
            for line in run_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        metrics_rows = [r for r in rows if r.get("type") == "run_metrics"]
        assert len(metrics_rows) == 1, "run 收尾恰落一条转录 run_metrics 行"
        assert metrics_rows[0]["model"] == "deepseek-v4-flash"

        ctx_rows = [
            a[2]
            for a, _k in logger.infos
            if len(a) >= 3 and isinstance(a[2], dict)
            and a[2].get("metric_type") == "run_metrics"
        ]
        assert len(ctx_rows) == 1, "日志侧恰一条 context metrics 行"
        assert ctx_rows[0]["model"] == "deepseek-v4-flash"

    def test_terminal_log_run_metrics_writes_model(self, tmp_path):
        """终态 _log_run_metrics 接通休眠形参：context.model 落行；model=None
        原样落 null（未观测语义）。"""
        from core.logger import Logger

        log_dir = tmp_path / ".fenix" / "logs"
        log_dir.mkdir(parents=True)
        runner = _make_metrics_runner(tmp_path, Logger(log_dir, "DEBUG"))
        runner._log_run_metrics(
            run_id="run-model-1", spec_name="spec-x", agent_type="verifier",
            duration_seconds=1.2, turns=4, usage_info={"cost_usd": 0.01},
            terminal="success", provider="p1", model="deepseek-v4-flash",
        )
        runner._log_run_metrics(
            run_id="run-model-2", spec_name="spec-x", agent_type="verifier",
            duration_seconds=0.8, turns=2, usage_info={},
            terminal="failure", provider=None, model=None,
        )
        runner.logger.close()

        log_file = log_dir / "fenixd.log"
        ctx_rows = []
        for raw in log_file.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            ctx = entry.get("context") or {}
            if ctx.get("metric_type") == "run_metrics":
                ctx_rows.append(ctx)
        by_run = {c["run_id"]: c for c in ctx_rows}
        assert by_run["run-model-1"]["model"] == "deepseek-v4-flash"
        assert "model" in by_run["run-model-2"]
        assert by_run["run-model-2"]["model"] is None
