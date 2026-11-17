"""evo-quota-reset-dispatch-freeze：provider 配额重置时刻解析与冻结期派发消费。

覆盖 tasks（spec/changes/evo-quota-reset-dispatch-freeze/tasks.md 3.1 四场景）：
- S1 重置时刻冻结生效且期内零真实派发（1.1 解析 + 冻结记账 + 链选择跳过）
- S2 冻结期派发廉价失败且汇总告警单条（2.1 queue 闸门判定 / 告警 upsert /
  到期翻转收口 / breaker link 记账与复位）
- S3 重置早于固定冷却时按固定时长（1.1 max 语义边界）
- S4 解析失败回退现状（1.1 四类解析失败输入 + 记账回退 + origin 清零）
- 归因注记（2.1 chain_exhausted 分支 [provider-quota-frozen] 标记与 fail-open）
"""

import inspect
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.admin_store import AdminStore
from core.agent_runner import (
    PROVIDER_SWITCH_COOLDOWN_SECONDS,
    PROVIDER_QUOTA_FROZEN_MARKER,
    AgentRunner,
)
from core.agent_runner.runner import _AttemptState
from core.pm_engine.dispatch.queue import (
    QUOTA_FREEZE_ALERT_SIGNAL_TYPE,
    QQQueueMixin,
)
from core.pm_engine.infra_breaker import InfraCircuitBreaker


class FakeLogger:
    """兼容 fenixd Logger 双参（component, message）与单参两种调用形态。"""

    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.records.append(("info", str(a[-1])))

    def warning(self, *a, **k):
        self.records.append(("warning", str(a[-1])))

    def error(self, *a, **k):
        self.records.append(("error", str(a[-1])))

    def messages(self):
        return [m for _lvl, m in self.records]

    def has(self, text):
        return any(text in m for m in self.messages())


def make_runner(proot: Path, config: dict | None = None) -> AgentRunner:
    """构造最小 AgentRunner 实例（绕过真实 __init__，同 test_provider_failover 处方）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    pc = runner._provider_circuit
    pc._daily_reset_date = None
    pc._daily_provider_attempts = {}
    pc._daily_provider_warned = {}
    pc.provider_circuits = {}
    return runner


def chain_config(chain, model="deepseek-v4-flash"):
    """构造 implementer 候选链 config（同 test_provider_failover.chain_config）。"""
    providers = [
        {"name": "inferaiapi.com", "baseurl": "https://a.com", "apikey": "k1"},
        {"name": "aliyun", "baseurl": "https://b.com", "apikey": "k2"},
    ]
    return {
        "llm": {"providers": providers},
        "agents": {
            "models": {"implementer": {"provider": chain, "model": model}},
        },
    }


def _wall_iso(offset_seconds: float) -> str:
    """未来/过去墙钟时刻的 naive 文本形态（报文原文形状：本地时区无时区尾缀）。"""
    lt = time.localtime(time.time() + offset_seconds)
    return (
        f"{lt.tm_year:04d}-{lt.tm_mon:02d}-{lt.tm_mday:02d}"
        f" {lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}"
    )


class _FakePM:
    """queue 层闸门单测的最小 _pm 门面（只暴露闸门各方法触达的成员）。"""

    def __init__(self, runner, breaker, logger, root):
        self.agent_runner = runner
        self.infra_breaker = breaker
        self.logger = logger
        self.project_root = root

    def _transient_unseal_recredit(self):
        pass

    def _rollback_dispatch_slot(self, *a, **k):
        pass


def make_queue(runner, breaker, logger, root) -> QQQueueMixin:
    """构造最小 QQQueueMixin（闸门状态字段手工置位，同绕 __init__ 处方）。"""
    q = QQQueueMixin.__new__(QQQueueMixin)
    q._pm = _FakePM(runner, breaker, logger, root)
    q._quota_freeze_watch = {}
    q._quota_freeze_hit_counts = {}
    q._quota_freeze_lock = threading.Lock()
    return q


# ── S1 重置时刻冻结生效且期内零真实派发 ────────────────────────────────


def test_s1_quota_reset_freeze_blocks_real_dispatch(tmp_path):
    """重置时刻解析成功 → 冻结至重置时刻（超固定冷却），期内链选择零候选。"""
    runner = make_runner(tmp_path, chain_config(["inferaiapi.com"]))
    future_iso = _wall_iso(7200)
    epoch = AgentRunner.parse_quota_reset_epoch(f"限额将在 {future_iso} 重置")
    # 解析成功且落在未来（墙钟差值 ≈ 7200s）
    assert epoch is not None
    assert time.time() + 7195 < epoch < time.time() + 7265

    runner._provider_circuit._record_switch_cooldown(
        "inferaiapi.com", reset_epoch=epoch
    )
    st = runner._provider_circuit.provider_circuits["inferaiapi.com"]
    now_mono = runner._now()
    # 冻结到期取 max(固定冷却, 重置时刻) —— 7200s 冻结压过 300s 固定冷却
    assert st["switch_cooldown_until"] > now_mono + PROVIDER_SWITCH_COOLDOWN_SECONDS
    assert st["switch_cooldown_until"] == pytest.approx(now_mono + 7200, abs=10.0)
    # origin 附记：重置时刻随记账走
    assert st["switch_cooldown_reset_wall"] == pytest.approx(epoch)
    assert runner.is_switch_cooldown("inferaiapi.com")
    assert runner.logger.has("Provider quota freeze")

    # 期内零真实派发：链选择跳过冻结候选（全链单候选 → 无可用候选）
    chain = runner._get_agent_model_assignment("implementer")
    assert runner._select_chain_candidate(chain, "demo", "implementer") == -1
    # 共享判据画像（queue 闸门与 chain_exhausted 归因的单源）
    report = runner.provider_chain_freeze_report(chain)
    assert report["available"] == 0
    assert len(report["switch_frozen"]) == 1
    assert report["switch_frozen"][0]["name"] == "inferaiapi.com"
    assert report["switch_frozen"][0]["reset_wall"] == pytest.approx(epoch)
    assert report["circuit_open"] == []


# ── S2 冻结期派发廉价失败且汇总告警单条 ────────────────────────────────


def test_s2_gate_judgment_boundaries(tmp_path):
    """闸门判定三分界：链上有可用候选放行 / 全链配额冻结拦截 /
    全链普通冷却（无重置时刻）放行既有 chain_exhausted 承载。"""
    runner = make_runner(
        tmp_path, chain_config(["inferaiapi.com", "aliyun"])
    )
    logger = FakeLogger()
    breaker = InfraCircuitBreaker(tmp_path, {}, logger=logger)
    q = make_queue(runner, breaker, logger, tmp_path)

    # ① 链上仍有可用候选（仅首候选配额冻结）→ None 放行（不打破既有链前进）
    runner._provider_circuit._record_switch_cooldown(
        "inferaiapi.com", reset_epoch=time.time() + 7200
    )
    assert q._quota_frozen_candidates("demo", "implementer") is None

    # ② 全链配额冻结 → 返回冻结候选画像清单（廉价失败依据）
    runner._provider_circuit._record_switch_cooldown(
        "aliyun", reset_epoch=time.time() + 3600
    )
    frozen = q._quota_frozen_candidates("demo", "implementer")
    assert frozen is not None and len(frozen) == 2
    assert {f["name"] for f in frozen} == {"inferaiapi.com", "aliyun"}
    assert all(f["reset_wall"] > 0 for f in frozen)

    # ③ 全链普通冷却（无重置时刻，reset_wall=0）→ None 放行既有语义
    for name in ("inferaiapi.com", "aliyun"):
        runner._provider_circuit._record_switch_cooldown(name)
    assert q._quota_frozen_candidates("demo", "implementer") is None


def test_s2_single_aggregated_alert_upsert_and_sweep_close(tmp_path):
    """重复命中只更新计数不新建（恰一条汇总告警）；到期翻转自动收口并复位。"""
    runner = make_runner(tmp_path, chain_config(["inferaiapi.com"]))
    epoch = time.time() + 7200
    runner._provider_circuit._record_switch_cooldown(
        "inferaiapi.com", reset_epoch=epoch
    )
    logger = FakeLogger()
    breaker = InfraCircuitBreaker(tmp_path, {}, logger=logger)
    q = make_queue(runner, breaker, logger, tmp_path)

    frozen = q._quota_frozen_candidates("demo", "implementer")
    assert frozen is not None

    # 冻结期两次派发命中 → 汇总告警恰一条、count=2、breaker link 计数=2
    q._record_quota_freeze_hits(frozen, "spec-a")
    q._record_quota_freeze_hits(frozen, "spec-b")
    store = AdminStore(tmp_path, logger)
    alerts = [
        r for r in store.read_records()
        if r.get("signal_type") == QUOTA_FREEZE_ALERT_SIGNAL_TYPE
    ]
    assert len(alerts) == 1
    rec = alerts[0]
    assert rec["count"] == 2
    assert rec["severity"] == "critical"
    assert rec.get("spec") in (None, "")
    assert "link=quota-freeze:inferaiapi.com;" in rec["evidence"]
    assert "latest_spec=spec-b" in rec["evidence"]  # 证据随最近一次命中走
    assert "冻结至" in rec["description"]
    assert not rec.get("handled")
    link = "quota-freeze:inferaiapi.com"
    assert breaker.get_state(link)["count"] == 2
    # watch/计数内存态与冻结真源对齐
    assert q._quota_freeze_watch == {"inferaiapi.com": pytest.approx(epoch)}
    assert q._quota_freeze_hit_counts == {"inferaiapi.com": 2}

    # 重置时刻未到：扫描不收口（仍冻结，告警保持未 handled）
    assert q._sweep_expired_quota_freeze_alerts() == 0
    before = [
        r for r in AdminStore(tmp_path, logger).read_records()
        if r.get("signal_type") == QUOTA_FREEZE_ALERT_SIGNAL_TYPE
    ]
    assert len(before) == 1 and not before[0].get("handled")

    # 冻结到期翻转（provider_circuit 内存态解除）→ 扫描收口
    runner._provider_circuit.provider_circuits["inferaiapi.com"][
        "switch_cooldown_until"
    ] = 0.0
    assert q._sweep_expired_quota_freeze_alerts() == 1
    rec_after = [
        r for r in AdminStore(tmp_path, logger).read_records()
        if r.get("signal_type") == QUOTA_FREEZE_ALERT_SIGNAL_TYPE
    ]
    assert len(rec_after) == 1  # 仍是同一条（收口≠新建）
    closed = rec_after[0]
    assert closed["handled"] is True
    assert closed["handled_by"] == "auto-resolve"
    assert "冻结已解除" in closed["resolve_note"]
    assert closed["handled_at"]
    # 内存态清空 + breaker link 复位（未来再冻结重新起算）
    assert q._quota_freeze_watch == {}
    assert q._quota_freeze_hit_counts == {}
    assert breaker.get_state(link)["count"] == 0
    assert logger.has("恢复派发")


def test_s2_sweep_noop_on_empty_watch_and_gate_fail_open(tmp_path):
    """watch 空表零开销；判定链异常 fail-open 放行（闸门不阻塞派发主链）。"""
    runner = make_runner(tmp_path, chain_config(["inferaiapi.com"]))
    logger = FakeLogger()
    breaker = InfraCircuitBreaker(tmp_path, {}, logger=logger)
    q = make_queue(runner, breaker, logger, tmp_path)
    # watch 空表 → 零开销短路（不触达 agent_runner）
    assert q._sweep_expired_quota_freeze_alerts() == 0
    # agent_runner 缺失（装配不全的历史路径）→ 放行
    q._pm.agent_runner = None
    assert q._quota_frozen_candidates("demo", "implementer") is None
    # 判定链异常 → fail-open 放行 + WARNING 留痕
    runner2 = make_runner(tmp_path, chain_config(["inferaiapi.com"]))
    q2 = make_queue(runner2, breaker, logger, tmp_path)
    runner2._get_agent_model_assignment = MagicMock(
        side_effect=RuntimeError("boom")
    )
    assert q2._quota_frozen_candidates("demo", "implementer") is None
    assert logger.has("fail-open 放行")


def test_s2_gate_wired_into_process_queue():
    """闸门接线守卫：_process_queue 在出锁段闸门位调用扫描与判定（防静默脱线）。"""
    src = inspect.getsource(QQQueueMixin._process_queue)
    assert "_sweep_expired_quota_freeze_alerts()" in src
    assert "_quota_frozen_candidates(" in src
    assert "_record_quota_freeze_hits(" in src


# ── S3 重置早于固定冷却时按固定时长 ────────────────────────────────────


def test_s3_reset_before_fixed_cooldown_wins(tmp_path):
    """重置时刻早于固定冷却到期 → 按固定 300s（max 语义边界），origin 仍附记。"""
    runner = make_runner(tmp_path, chain_config(["inferaiapi.com"]))
    epoch = time.time() + 60  # 重置 60s 后 < 固定冷却 300s
    runner._provider_circuit._record_switch_cooldown(
        "inferaiapi.com", reset_epoch=epoch
    )
    st = runner._provider_circuit.provider_circuits["inferaiapi.com"]
    now_mono = runner._now()
    assert st["switch_cooldown_until"] == pytest.approx(
        now_mono + PROVIDER_SWITCH_COOLDOWN_SECONDS, abs=2.0
    )
    # 重置时刻合法（未来）→ origin 附记照走（画像/告警展示消费）
    assert st["switch_cooldown_reset_wall"] == pytest.approx(epoch)
    assert runner.is_switch_cooldown("inferaiapi.com")


# ── S4 解析失败回退现状 ────────────────────────────────────────────────


def test_s4_parse_failure_falls_back_to_fixed_cooldown(tmp_path):
    """四类解析失败输入全返回 None；记账回退固定冷却且 origin 清零。"""
    # 空 / 无时间戳 / 过去时刻 / 签名命中但日期非法
    assert AgentRunner.parse_quota_reset_epoch("") is None
    assert AgentRunner.parse_quota_reset_epoch(
        "rate limit exceeded (429), please retry later"
    ) is None
    assert AgentRunner.parse_quota_reset_epoch(
        f"限额将在 {_wall_iso(-3600)} 重置"
    ) is None  # 已过期按解析失败同判
    assert AgentRunner.parse_quota_reset_epoch(
        "限额将在 2026-13-45 99:99:99 重置"
    ) is None

    runner = make_runner(tmp_path, chain_config(["inferaiapi.com"]))
    runner._provider_circuit._record_switch_cooldown(
        "inferaiapi.com", reset_epoch=None
    )
    st = runner._provider_circuit.provider_circuits["inferaiapi.com"]
    now_mono = runner._now()
    assert st["switch_cooldown_until"] == pytest.approx(
        now_mono + PROVIDER_SWITCH_COOLDOWN_SECONDS, abs=2.0
    )
    assert st["switch_cooldown_reset_wall"] == 0.0
    assert runner.logger.has("Provider switch-cooldown")

    # origin 随最近一次记账走：配额冻结后接普通冷却 → 陈旧配额标签显式清零
    runner._provider_circuit._record_switch_cooldown(
        "inferaiapi.com", reset_epoch=time.time() + 7200
    )
    assert runner._provider_circuit.provider_circuits["inferaiapi.com"][
        "switch_cooldown_reset_wall"
    ] > 0
    runner._provider_circuit._record_switch_cooldown("inferaiapi.com")
    assert runner._provider_circuit.provider_circuits["inferaiapi.com"][
        "switch_cooldown_reset_wall"
    ] == 0.0


# ── 2.1 chain_exhausted 归因注记 ───────────────────────────────────────


def _exhaust_via_candidate_resolution(runner, spec="demo"):
    """驱动 _resolve_provider_candidate 走 chain_exhausted 分支（全链冷却）。"""
    runner._log_run_metrics = MagicMock()
    st = _AttemptState()
    provider, model, chain, result = runner._resolve_provider_candidate(
        spec_name=spec, agent_type="implementer", run_id="r1",
        attempt_run_id="ar1", start_time=time.time(), turns=0,
        usage_info={}, st=st,
    )
    return provider, chain, result


def test_quota_frozen_chain_exhausted_annotation(tmp_path):
    """全链配额冻结廉价失败：error 前置 [provider-quota-frozen] 归因注记，
    既有 chain_exhausted 原文保留（substring 兼容）。"""
    runner = make_runner(tmp_path, chain_config(["inferaiapi.com"]))
    runner._provider_circuit._record_switch_cooldown(
        "inferaiapi.com", reset_epoch=time.time() + 7200
    )
    provider, chain, result = _exhaust_via_candidate_resolution(runner)
    assert provider is None
    assert result is not None and result.chain_exhausted is True
    assert PROVIDER_QUOTA_FROZEN_MARKER in result.error
    assert "inferaiapi.com 冻结至" in result.error
    assert "provider chain exhausted" in result.error  # 原文保留


def test_quota_annotation_fail_open_keeps_legacy_semantics(tmp_path):
    """freeze report 异常 fail-open：归因注记丢失不改变既有失败语义。"""
    runner = make_runner(tmp_path, chain_config(["inferaiapi.com"]))
    runner._provider_circuit._record_switch_cooldown("inferaiapi.com")
    runner.provider_chain_freeze_report = MagicMock(
        side_effect=RuntimeError("boom")
    )
    provider, chain, result = _exhaust_via_candidate_resolution(runner)
    assert provider is None
    assert result.chain_exhausted is True
    assert PROVIDER_QUOTA_FROZEN_MARKER not in result.error
    assert "provider chain exhausted" in result.error
