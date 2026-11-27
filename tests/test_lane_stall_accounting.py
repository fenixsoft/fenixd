"""tests/test_lane_stall_accounting.py — evo-add-lane-stall-daily-budget-accounting 4.x

覆盖：
- 4.1 停滞总秒供数：latency_stats 新键求和正确（超统计线样本求和、恰在线上
  不计、0 样本与无停滞 run 为 0）；run_metrics 行（_log_run_metrics metric_ctx
  组装）含新键；_metrics_latency 与成功路径两条透传链同覆盖、None 走零样本
  回退。
- 4.2 车道级日汇总与告警面：同遍捕获 agent_type（零额外 IO）；车道级日汇总
  分组（总秒/run 数/最大单次 + 阈值标注，0=关闭标注）；admin_monitor 车道×日
  累计入账与超阈 info 信号（severity=info、_fp=lane+date 持久指纹）、同日两次
  巡检仍单条、阈值缺省 30 / 0=关闭 / 非法回退 30。
- 4.3 重启重建与兼容：daemon 重启（新 AdminMonitor 实例）后当日计数从已落账
  run_metrics 行重建；重启后同日重复超阈不新增第二条 lane+date 记录（持久键
  去重）；存量行缺新键按 0 计（不发信号）；单 run 粒度 api_round_stall_
  escalated 升级信号行为不回归（error 收场照发 + 同 run 去重 + success 豁免
  保留），车道计数与升级面旁路独立。
"""

import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunner
from core.agent_runner.latency import (
    LATENCY_STALL_SECONDS,
    latency_stats,
)
from core.admin_monitor import (
    SIGNAL,
    AdminMonitor,
    _read_terminal_run_metrics,
)
from core.admin_store import AdminStore
from core.logger import Logger
from core.self_review import (
    SelfReviewScheduler,
    _collect_api_stall_aggregates,
    _lane_stall_daily_rows,
    _scan_run_stall_totals,
)
from core.timelib import from_epoch


# ── 夹具工具 ────────────────────────────────────────────────────────────


def _mk_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="lane-stall-acct-"))
    (root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return root


def _read_metric_rows(root: Path) -> list[dict]:
    """从 fenixd.log 读取 metric_type=run_metrics 结构化行（context）。"""
    log_file = root / ".fenix" / "logs" / "fenixd.log"
    if not log_file.exists():
        return []
    results = []
    for raw in log_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        ctx = entry.get("context") or {}
        if ctx.get("metric_type") != "run_metrics":
            continue
        results.append(ctx)
    return results


def _mk_metrics_runner(root: Path):
    """最小 AgentRunner 替身（驱动 _log_run_metrics 真实落盘）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.project_root = root
    runner.logger = Logger(root / ".fenix" / "logs", "DEBUG")
    return runner


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _stall_events(base_ts: float, gaps, agent_type: str | None = None) -> list:
    """按给定往返间隔构造 stream-json 事件（真实 user 包裹形态）。

    ``agent_type`` 非空时追加终态 run_metrics 行（同遍捕获车道归属的数据源）。
    """
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
    if agent_type is not None:
        events.append({
            "type": "run_metrics",
            "run_id": "any",
            "agent_type": agent_type,
            "latency_rounds": len(gaps),
            "latency_stalls": sum(1 for g in gaps if g > LATENCY_STALL_SECONDS),
            "latency_max": max(gaps) if gaps else None,
        })
    return events


def _write_run(runs_dir: Path, run_id: str, events) -> Path:
    p = runs_dir / f"{run_id}.jsonl"
    p.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8")
    return p


class _FakeSM:
    def read_all(self):
        return {}

    def read_one(self, name):
        return None


class _FakeLogger:
    def __init__(self):
        self.warnings = []
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.infos.append(a)

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        pass


def _make_scheduler(proot, logger=None, config=None):
    return SelfReviewScheduler(
        config or {"admin": {"enabled": True, "self_review": {
            "enabled": True, "run_at": "22:00"}}},
        proot, logger or _FakeLogger(), _FakeSM(),
        agent_runner=None, store=None,
    )


def _write_metrics_run(runs_dir: Path, run_id: str, agent_type: str,
                       total: float, latency_max: float = 100.0,
                       with_total_key: bool = True,
                       terminal_result: dict | None = None) -> Path:
    """写含终态 run_metrics 行的 run jsonl（admin_monitor 检测数据源形态）。

    ``with_total_key=False`` 构造缺新键的存量行（4.3 兼容负控）；
    ``terminal_result`` 非空时在行尾追加 result 终态事件（success 豁免负控）。
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "type": "run_metrics",
        "run_id": run_id,
        "agent_type": agent_type,
        "turns": 40,
        "latency_rounds": 5,
        "latency_stalls": 2,
        "latency_max": latency_max,
    }
    if with_total_key:
        row["latency_stall_total_seconds"] = total
    rows = [
        {"type": "run_start", "run_id": run_id},
        row,
        {"type": "error", "error": "gateway timeout"},
    ]
    if terminal_result is not None:
        rows.append(terminal_result)
    p = runs_dir / f"{run_id}.jsonl"
    p.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    return p


def _mk_monitor(root: Path, config: dict | None = None, logger=None) -> AdminMonitor:
    """真实 AdminMonitor（store 落 tmp 项目）。"""
    return AdminMonitor(
        config or {},
        _FakeSM(),
        root,
        logger or _FakeLogger(),
        store=AdminStore(root, _FakeLogger()),
        agent_runner=None,
    )


def _lane_signals(store: AdminStore) -> list[dict]:
    return [r for r in store.read_records()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "lane_stall_daily_budget"]


def _escalation_signals(store: AdminStore) -> list[dict]:
    return [r for r in store.read_records()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "api_round_stall_escalated"]


# ── 4.1 停滞总秒供数 ───────────────────────────────────────────────────


class TestStallTotalSecondsKey:
    """Scenario: latency_stats 总秒键求和正确；run_metrics 行含新键且两条
    透传链不漏。"""

    def test_sum_over_stall_line(self):
        """>60s 样本求和；恰在线上（60.0）严格比较不计。"""
        stats = latency_stats([100.0, 70.0, 5.0])
        assert stats["stalls"] == 2
        assert stats["latency_stall_total_seconds"] == pytest.approx(170.0)
        # 与统计线同口径：60.0 不超线（> LATENCY_STALL_SECONDS）
        assert latency_stats([60.0])["latency_stall_total_seconds"] == 0.0
        assert latency_stats([60.1])["latency_stall_total_seconds"] == (
            pytest.approx(60.1))

    def test_zero_samples_and_no_stall_run(self):
        """0 样本与全无停滞 run 均为 0.0（键恒落、不缺省）。"""
        assert latency_stats([])["latency_stall_total_seconds"] == 0.0
        assert latency_stats([5.0, 30.0, 60.0])[
            "latency_stall_total_seconds"] == 0.0

    def test_negative_samples_excluded(self):
        """负样本（无效测量）先剔除再统计，不污染总秒键。"""
        stats = latency_stats([-5.0, 100.0, 70.0])
        assert stats["latency_stall_total_seconds"] == pytest.approx(170.0)

    def test_run_metrics_row_carries_key(self, tmp_path):
        """_log_run_metrics 落盘的 run_metrics 行含 latency_stall_total_seconds。"""
        runner = _mk_metrics_runner(tmp_path)
        stats = latency_stats([100.0, 70.0, 5.0])
        runner._log_run_metrics(
            run_id="r1", spec_name="demo", agent_type="planner-judge",
            duration_seconds=12.0, turns=6, usage_info={}, terminal="success",
            latency=stats)
        rows = _read_metric_rows(tmp_path)
        assert len(rows) == 1
        assert rows[0]["latency_stall_total_seconds"] == pytest.approx(170.0)
        assert rows[0]["latency_rounds"] == 3

    def test_both_passthrough_chains_covered(self, tmp_path):
        """_metrics_latency 链（非成功终态）与成功路径直传链同落新键；
        None（_run_agent 抛出路径）走零样本回退 0.0。"""
        runner = _mk_metrics_runner(tmp_path)
        from core.agent_runner.runner import _metrics_latency
        stats = latency_stats([200.0, 10.0])
        # 链 1：非成功终态经 _metrics_latency 归一透传
        runner._log_run_metrics(
            run_id="r2", spec_name="demo", agent_type="impl",
            duration_seconds=1.0, turns=2, usage_info={}, terminal="error",
            latency=_metrics_latency(dict(stats)))
        # 链 2：成功路径 stats 直传（不经过 helper）
        runner._log_run_metrics(
            run_id="r3", spec_name="demo", agent_type="impl",
            duration_seconds=1.0, turns=2, usage_info={}, terminal="success",
            latency=stats)
        # 兜底：None → 零样本回退
        runner._log_run_metrics(
            run_id="r4", spec_name="demo", agent_type="impl",
            duration_seconds=1.0, turns=2, usage_info={}, terminal="error",
            latency=None)
        rows = {r["run_id"]: r for r in _read_metric_rows(tmp_path)}
        assert rows["r2"]["latency_stall_total_seconds"] == pytest.approx(200.0)
        assert rows["r3"]["latency_stall_total_seconds"] == pytest.approx(200.0)
        assert rows["r4"]["latency_stall_total_seconds"] == 0.0


# ── 4.2 车道级日汇总（self_review 侧） ─────────────────────────────────


class TestLaneDailySummary:
    """Scenario: 同遍捕获 agent_type；车道级日汇总分组与阈值标注；
    摘要渲染含车道汇总段。"""

    def test_scan_captures_agent_type_same_pass(self, tmp_path):
        """同一遍流式迭代顺带捕获 run_metrics 行的车道归属（零额外 IO）。"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir(parents=True)
        p = _write_run(runs_dir, "r1", _stall_events(
            1000.0, [100.0, 70.0, 5.0], agent_type="planner-judge"))
        scan = _scan_run_stall_totals(p)
        assert scan["stalls"] == 2
        assert scan["agent_type"] == "planner-judge"
        # 无 run_metrics 行：None（调用方按 run_id 前缀推断兜底）
        p2 = _write_run(runs_dir, "r2", _stall_events(2000.0, [80.0]))
        assert _scan_run_stall_totals(p2)["agent_type"] is None

    def test_aggregate_row_carries_lane(self, tmp_path):
        """聚合行带 agent_type；行缺车道时按 run_id 前缀推断兜底。"""
        now = datetime.now().astimezone()
        root = tmp_path / "proj"
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        rid = f"impl-lane-{int(now.timestamp()) - 60}"
        _write_run(runs_dir, rid, _stall_events(
            now.timestamp(), [70.0, 100.0], agent_type="implementer"))
        bare = f"code-review-bare-{int(now.timestamp()) - 30}"
        _write_run(runs_dir, bare, _stall_events(now.timestamp(), [80.0]))
        results = _collect_api_stall_aggregates(
            root, now - timedelta(hours=1), now + timedelta(minutes=5))
        by_id = {r["run_id"]: r for r in results}
        assert by_id[rid]["agent_type"] == "implementer"
        assert by_id[bare]["agent_type"] == "code-review"  # 前缀推断兜底

    def test_lane_rows_grouping_and_threshold_note(self):
        """纯函数分组：总秒/run 数/最大单次逐组正确，超/未超标注、unknown 归组。"""
        rows = _lane_stall_daily_rows([
            {"run_id": "a", "agent_type": "planner-judge",
             "total_stall_seconds": 100.0, "max_stall_seconds": 60.0},
            {"run_id": "b", "agent_type": "planner-judge",
             "total_stall_seconds": 1900.0, "max_stall_seconds": 500.0},
            {"run_id": "c", "agent_type": "implementer",
             "total_stall_seconds": 50.0, "max_stall_seconds": None},
            {"run_id": "d", "agent_type": None,
             "total_stall_seconds": 70.0, "max_stall_seconds": 70.0},
        ], warn_minutes=30)
        assert len(rows) == 3
        assert rows[0] == (
            "- implementer: total=50.0s runs=1 max=-（未超 30 分钟阈值）")
        assert "planner-judge: total=2000.0s runs=2 max=500.0s" in rows[1]
        assert "已超 30 分钟阈值（provider 拥塞候选）" in rows[1]
        assert rows[2].startswith("- unknown: total=70.0s runs=1")

    def test_lane_rows_threshold_off_note(self):
        """warn_minutes=0（关闭）：汇总行照出、标注为阈值关闭。"""
        rows = _lane_stall_daily_rows([
            {"run_id": "a", "agent_type": "impl",
             "total_stall_seconds": 99999.0, "max_stall_seconds": 500.0},
        ], warn_minutes=0)
        assert rows == [
            "- impl: total=99999.0s runs=1 max=500.0s"
            "（阈值关闭（admin.lane_stall_warn_minutes=0））"
        ]

    def test_section_renders_lane_summary(self, tmp_path):
        """摘要渲染：逐 run 小节之后追加车道级日汇总段（同数据源、零额外 IO）。"""
        now = datetime.now().astimezone()
        root = tmp_path / "proj"
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        rid = f"impl-sum-{int(now.timestamp()) - 60}"
        _write_run(runs_dir, rid, _stall_events(
            now.timestamp(), [70.0, 100.0], agent_type="implementer"))
        # 阈值 1 分钟：170s 超阈 → 已超标注
        sched = _make_scheduler(root, config={
            "admin": {"enabled": True, "lane_stall_warn_minutes": 1,
                      "self_review": {"enabled": True, "run_at": "22:00"}}})
        lines = sched._collect_midflight_section(
            now - timedelta(hours=1), now + timedelta(minutes=5))
        assert "### API 停滞聚合（stall 计数>0 的 run）" in lines
        assert "### 车道级日汇总（按 agent_type 分组）" in lines
        assert (
            f"- implementer: total=170.0s runs=1 max=100.0s"
            f"（已超 1 分钟阈值（provider 拥塞候选））") in lines

    def test_lane_stall_warn_minutes_config_semantics(self, tmp_path):
        """阈值读取：缺省 30、0=关闭、非法/负值/bool 回退 30。"""
        sched = _make_scheduler(tmp_path)
        assert sched._lane_stall_warn_minutes() == 30  # 缺省
        for raw, want in [
            (0, 0), (5, 5), ("abc", 30), (-1, 30), (True, 30), (12.0, 12),
        ]:
            sched2 = _make_scheduler(tmp_path, config={
                "admin": {"lane_stall_warn_minutes": raw}})
            assert sched2._lane_stall_warn_minutes() == want, raw


# ── 4.2/4.3 车道×日累计告警（admin_monitor 侧） ────────────────────────


class TestLaneDailyBudgetSignal:
    """Scenario: 车道×日累计入账、超阈 info 信号、lane+date 持久去重、
    阈值语义、重启重建、存量行兼容、单 run 升级面不回归。"""

    def test_accrual_and_signal_emitted(self, tmp_path):
        """同车道两个超阈 run：入账求和正确，巡检发 1 条 info 信号。"""
        root = _mk_repo()
        runs_dir = root / ".fenix" / "runs"
        _write_metrics_run(runs_dir, "r-a1", "planner-judge", 1000.0)
        _write_metrics_run(runs_dir, "r-a2", "planner-judge", 900.0,
                           latency_max=250.0)
        mon = _mk_monitor(root)
        mon._check_api_round_stall_escalated()
        # 日桶为 UTC（core.timelib.from_epoch 单源派生），断言同源取数——
        # 本地时区非 UTC 时本地日期与 UTC 日桶错位（如 UTC+8 的 0-8 点窗
        # 口用本地日期查询恒落空）。
        today = from_epoch(time.time()).date()
        g = mon._lane_stall_daily.get(("planner-judge", today))
        assert g is not None
        assert g["total_seconds"] == pytest.approx(1900.0)
        assert g["runs"] == 2  # 两个 run 均停滞>0 计数
        assert g["max_seconds"] == pytest.approx(250.0)
        sigs = _lane_signals(mon.store)
        assert len(sigs) == 1
        sig = sigs[0]
        assert sig["severity"] == "info"
        assert "项目名=" in sig["evidence"]
        assert "lane=planner-judge" in sig["evidence"]
        # _fp 稳定指纹（lane+date，不含秒数）随记录留痕
        assert sig["_fp"] == (
            f"lane-stall-daily:planner-judge:{today.isoformat()}")

    def test_same_day_two_sweeps_one_record(self, tmp_path):
        """同日二次巡检（重复超阈）：merge 持久键命中，不新增第二条记录。"""
        root = _mk_repo()
        _write_metrics_run(root / ".fenix" / "runs", "r-b1", "impl", 2000.0)
        mon = _mk_monitor(root)
        mon._check_api_round_stall_escalated()
        mon._check_api_round_stall_escalated()
        assert len(_lane_signals(mon.store)) == 1

    def test_threshold_zero_off(self, tmp_path):
        """阈值 0 = 关闭：计数照常入账，不发信号。"""
        root = _mk_repo()
        _write_metrics_run(root / ".fenix" / "runs", "r-c1", "impl", 99999.0)
        mon = _mk_monitor(root, config={"admin": {"lane_stall_warn_minutes": 0}})
        mon._check_api_round_stall_escalated()
        assert mon._lane_stall_daily  # 计数已入账
        assert _lane_signals(mon.store) == []

    def test_lane_stall_warn_minutes_semantics(self, tmp_path):
        """admin_monitor 侧阈值读取：缺省 30、0=关闭、非法回退 30（与
        self_review 同源同缺省）。"""
        mon = _mk_monitor(tmp_path)
        assert mon._lane_stall_warn_minutes() == 30
        for raw, want in [(0, 0), (5, 5), ("abc", 30), (-3, 30), (False, 30)]:
            m2 = _mk_monitor(tmp_path, config={"admin": {
                "lane_stall_warn_minutes": raw}})
            assert m2._lane_stall_warn_minutes() == want, raw

    def test_restart_rebuilds_counts(self, tmp_path):
        """重启重建：新 AdminMonitor 实例（内存计数器空）首轮巡检从已落账
        终态行重建当日计数；缺新键的存量行按 0 计。"""
        root = _mk_repo()
        runs_dir = root / ".fenix" / "runs"
        _write_metrics_run(runs_dir, "r-d1", "impl", 800.0)
        _write_metrics_run(runs_dir, "r-d2", "impl", 700.0)
        _write_metrics_run(runs_dir, "r-d3", "code-review", 300.0,
                           with_total_key=False)  # 存量行缺新键 → 按 0 计
        first = _mk_monitor(root)
        first._check_api_round_stall_escalated()
        # 模拟 daemon 重启：全新实例（计数器/seen 均空）
        reborn = _mk_monitor(root)
        assert reborn._lane_stall_daily == {}
        reborn._check_api_round_stall_escalated()
        today = from_epoch(time.time()).date()  # UTC 日桶（与产品单源）
        g = reborn._lane_stall_daily.get(("impl", today))
        assert g["total_seconds"] == pytest.approx(1500.0)
        assert g["runs"] == 2
        gc = reborn._lane_stall_daily.get(("code-review", today))
        assert gc["total_seconds"] == 0.0
        assert gc["runs"] == 0  # 停滞 0 的 run 不计停滞 run 数

    def test_restart_no_second_record(self, tmp_path):
        """重启后同日重复超阈：持久键（_fp=lane+date）命中 merge，不新增
        第二条 lane+date 记录。"""
        root = _mk_repo()
        _write_metrics_run(root / ".fenix" / "runs", "r-e1", "impl", 5000.0)
        first = _mk_monitor(root)
        first._check_api_round_stall_escalated()
        assert len(_lane_signals(first.store)) == 1
        reborn = _mk_monitor(root)  # 重启模拟：内存去重记忆全失
        reborn._check_api_round_stall_escalated()
        assert len(_lane_signals(first.store)) == 1  # 仅刷 last_seen 不新增

    def test_single_run_escalation_unregressed(self, tmp_path):
        """3.3 单 run 升级面不回归：error 收场超升级线照发
        api_round_stall_escalated（同 run 去重）；success 终态豁免保留；
        车道计数旁路独立照常入账。"""
        root = _mk_repo()
        runs_dir = root / ".fenix" / "runs"
        _write_metrics_run(runs_dir, "r-f1", "code-review", 100.0,
                           latency_max=420.0)  # >300 升级线
        _write_metrics_run(runs_dir, "r-f2", "code-review", 50.0,
                           latency_max=420.0,
                           terminal_result={"type": "result",
                                            "subtype": "success"})
        mon = _mk_monitor(root)
        mon._check_api_round_stall_escalated()
        esc = _escalation_signals(mon.store)
        assert len(esc) == 1  # 仅 r-f1（r-f2 success 豁免）
        assert "r-f1" in esc[0]["description"]
        # 同 run 二次巡检去重（升级面既有语义）
        mon2 = _mk_monitor(root)
        mon2._check_api_round_stall_escalated()
        assert len(_escalation_signals(mon2.store)) == 1
        # 车道计数旁路独立：两个 run 均入账（success 豁免不影响计数）
        g = mon._lane_stall_daily.get(
            ("code-review", from_epoch(time.time()).date()))  # UTC 日桶
        assert g["total_seconds"] == pytest.approx(150.0)
        assert g["runs"] == 2

    def test_read_terminal_row_has_total_key(self, tmp_path):
        """检测面读到的终态行透传新键（1.2 → 3.1 数据链闭合）。"""
        root = _mk_repo()
        p = _write_metrics_run(root / ".fenix" / "runs", "r-g1", "impl", 123.5)
        row = _read_terminal_run_metrics(p)
        assert row["latency_stall_total_seconds"] == pytest.approx(123.5)
        assert row["agent_type"] == "impl"


# ── evo-stall-signal-archive-scan-reconciliation：扫描面含归档与对账自证 ──


class TestArchiveScanCoverage:
    """Scenario（R1）：归档件入账并触发预算信号 / 落盘即归档下一轮仍入账 /
    跨午夜归档不漏报（归档源与顶层同窗 48h 新鲜度界，不按 UTC 日桶收窄）。"""

    def _archive(self, root: Path) -> Path:
        d = root / ".fenix" / "runs" / "archive"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_archive_run_accrues_and_signals(self):
        """停滞 run 档案直接落入 archive/（顶层无文件）并触发巡检轮：车道
        日累计入账，越过预算线时 lane_stall_daily_budget 信号落账。"""
        root = _mk_repo()
        _write_metrics_run(self._archive(root), "r-arc1", "planner-judge",
                           1000.0)
        mon = _mk_monitor(root, config={
            "admin": {"lane_stall_warn_minutes": 1}})  # 阈值 60s
        mon._check_api_round_stall_escalated()
        today = from_epoch(time.time()).date()  # UTC 日桶（与产品单源）
        g = mon._lane_stall_daily.get(("planner-judge", today))
        assert g is not None
        assert g["total_seconds"] == pytest.approx(1000.0)
        assert g["runs"] == 1
        sigs = _lane_signals(mon.store)
        assert len(sigs) == 1  # 越线落信号（常规面，非对账补发）
        assert "对账补发" not in sigs[0]["evidence"]

    def test_archived_before_any_scan_next_round_accrues(self):
        """落盘后被保留清理立即移入 archive/、「终态→归档」窗口内无巡检轮
        （等价重启后首轮）：下一巡检轮仍能从归档源入账并完成信号判定。"""
        root = _mk_repo()
        runs_dir = root / ".fenix" / "runs"
        p = _write_metrics_run(runs_dir, "r-arc2", "impl", 2000.0)
        self._archive(root)
        p.rename(self._archive(root) / "r-arc2.jsonl")  # 无任何巡检轮看过顶层
        mon = _mk_monitor(root, config={
            "admin": {"lane_stall_warn_minutes": 1}})
        mon._check_api_round_stall_escalated()
        today = from_epoch(time.time()).date()
        assert mon._lane_stall_daily[("impl", today)]["total_seconds"] == (
            pytest.approx(2000.0))
        assert len(_lane_signals(mon.store)) == 1

    def test_cross_midnight_archive_escalation_still_evaluated(self):
        """日末终态 run 的归档跨零点、其后巡检轮属次日：归档源仍按与顶层
        同款 48h 新鲜度界评估该档案（不因 UTC 日桶过滤被排除），单轮升级
        面可补报；日累计侧当日过滤同口径排除非今日行（对账不造假差额）。"""
        root = _mk_repo()
        p = _write_metrics_run(self._archive(root), "r-arc3",
                               "code-review", 100.0, latency_max=420.0)
        old = time.time() - 25 * 3600  # 昨日、48h 新鲜度窗内
        os.utime(p, (old, old))
        mon = _mk_monitor(root)
        mon._check_api_round_stall_escalated()
        esc = _escalation_signals(mon.store)
        assert len(esc) == 1  # 升级面 48h 窗补报，不因日桶收窄漏报
        assert "r-arc3" in esc[0]["description"]
        today = from_epoch(time.time()).date()
        assert ("code-review", today) not in mon._lane_stall_daily  # 非今日不入今日桶


class TestReconciliationSelfCheck:
    """Scenario（R2/R3）：差额超阈值补发且 evidence 含对账来源 / 基准同口径
    不制造假差额 / 三来源只入账一次 / 阈值关闭对账同关 / 豁免与阈值无回归。"""

    def test_diff_over_line_reemits_with_recon_evidence(self):
        """累计器与档案合计差额超 60s（seen 已标而入账漏计的残留形态）：
        补发 lane_stall_daily_budget 且 evidence/description 注明对账来源；
        同差额持续轮 merge 持久键命中不新增第二条记录。"""
        root = _mk_repo()
        _write_metrics_run(root / ".fenix" / "runs", "r-rec1", "impl", 1000.0)
        mon = _mk_monitor(root, config={
            "admin": {"lane_stall_warn_minutes": 1}})
        # 模拟残留漏报形态：run 已被 seen 标记但入账漏计（seen 集只挡信号
        # 重评与重复入账，不挡对账基准复读——基准侧照折算该行）
        mon._api_stall_metrics_seen.add("r-rec1")
        mon._check_api_round_stall_escalated()
        sigs = _lane_signals(mon.store)
        assert len(sigs) == 1
        assert "对账补发" in sigs[0]["evidence"]
        assert "对账补发" in sigs[0]["description"]
        assert sigs[0]["severity"] == "info"  # kind/severity 既有语义不变
        mon._check_api_round_stall_escalated()  # 差额持续轮
        assert len(_lane_signals(mon.store)) == 1  # merge 去重不新增

    def test_recon_basis_includes_success_no_false_diff(self):
        """基准同口径：success 收场的停滞 run 入账面计入、对账基准同样计入
        ——差额为零，不因基准侧口径不齐补发信号；success 终态豁免与常规
        信号落账无回归。"""
        root = _mk_repo()
        _write_metrics_run(root / ".fenix" / "runs", "r-rec2", "impl", 500.0,
                           terminal_result={"type": "result",
                                            "subtype": "success"})
        mon = _mk_monitor(root, config={
            "admin": {"lane_stall_warn_minutes": 1}})
        mon._check_api_round_stall_escalated()
        today = from_epoch(time.time()).date()
        # 入账面：success 豁免不影响日累计计数（既有约定）
        assert mon._lane_stall_daily[("impl", today)]["total_seconds"] == (
            pytest.approx(500.0))
        sigs = _lane_signals(mon.store)
        assert len(sigs) == 1  # 常规面 1 条（500 > 60s 阈值）
        assert "对账补发" not in sigs[0]["evidence"]  # 差额为零无补发
        assert len(_escalation_signals(mon.store)) == 0  # success 豁免保留

    def test_three_sources_single_accrual(self):
        """同一 run 档案先后经顶层扫描、归档扫描、对账补发三种来源触及：
        停滞行只入账一次，日累计不虚高，信号面单条。"""
        root = _mk_repo()
        runs_dir = root / ".fenix" / "runs"
        p = _write_metrics_run(runs_dir, "r-rec3", "impl", 900.0)
        mon = _mk_monitor(root, config={
            "admin": {"lane_stall_warn_minutes": 1}})
        today = from_epoch(time.time()).date()
        mon._check_api_round_stall_escalated()  # 来源①顶层扫描入账
        assert mon._lane_stall_daily[("impl", today)]["total_seconds"] == (
            pytest.approx(900.0))
        (runs_dir / "archive").mkdir(parents=True, exist_ok=True)
        p.rename(runs_dir / "archive" / "r-rec3.jsonl")
        mon._check_api_round_stall_escalated()  # 来源②归档扫描（收敛基含归档候选）
        mon._check_api_round_stall_escalated()  # 来源③对账面触及（差额 0 不补发）
        assert mon._lane_stall_daily[("impl", today)]["total_seconds"] == (
            pytest.approx(900.0))  # 不双计、不虚高
        assert "r-rec3" in mon._lane_stall_accrued  # 已入账条目未被裁掉重扫
        assert len(_lane_signals(mon.store)) == 1

    def test_recon_off_when_threshold_zero(self):
        """warn_minutes=0（信号面关闭）：对账自证同关——差额场景不补发。"""
        root = _mk_repo()
        _write_metrics_run(root / ".fenix" / "runs", "r-rec4", "impl", 5000.0)
        mon = _mk_monitor(root, config={
            "admin": {"lane_stall_warn_minutes": 0}})
        mon._api_stall_metrics_seen.add("r-rec4")  # 差额场景（同残留漏报形态）
        mon._check_api_round_stall_escalated()
        assert _lane_signals(mon.store) == []  # 0=关闭：对账补发同关不产任何记录
