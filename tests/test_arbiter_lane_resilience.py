"""harden-arbiter-lane-resilience 回归测试（两能力场景全覆盖）。

能力一 arbiter-infra-failure-reset（场景 S1-S6）＋能力二
agent-lane-preflight（场景 S1-S5）＋台账读侧兼容回归（能力一 S5）。

密闭性纪律：探针结论一律预种/patch，MUST NOT 依赖宿主 CLI/凭据环境
（tests/test_arbiter_lane.make_lane 预种 healthy 同款）；fenixd 接线
用例 patch ``fenixd.PROJECT_ROOT`` 到 tmp，真实 AdminStore 落盘不出 tmp。
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.agent_runner.lane_preflight import (
    LANE_ENV_ALERT_SIGNAL,
    LaneHealth,
    LanePreflightCache,
    classify_lane_failure,
    probe_lane_health,
)
from core.agent_runner.maintenance_runs import run_arbiter
from core.agent_runner.run_files import append_run_line
from core.admin_store import AdminStore, ESCALATION
from core.config import ConfigLoader
from core.pm_engine.arbiter import (
    arbiter_failure_signature,
    arbiter_ledger_path,
    load_arbiter_ledger,
    reset_lane,
)
from core.pm_engine.escalation_chain import (
    ChainQuotaStore,
    EscalationChain,
    reset_chain,
)
from core.state_machine import StateMachine
from tests.test_arbiter_lane import FakeLogger, FakeRunner, drain, make_lane
from tests.test_escalation_chain import (
    _FakeArbiterLane,
    _FakePm,
    _disp,
    _drain_chain,
)

SIG = arbiter_failure_signature("spec-a", "verify_env_blocked")
MISSING_CRED_MSG = (
    "dsh: MISSING_CREDENTIAL for profile bundle（链首选 provider 无 apikey）"
)


class InfraRunner(FakeRunner):
    """infra 秒挂替身：_run_agent 抛带环境指纹异常（异常路径 rounds=0）。"""

    def __init__(self, project_root, message=MISSING_CRED_MSG):
        super().__init__(project_root)
        self.message = message

    def _run_agent(self, prompt, project_root, run_id, model_override,
                   env_overrides, max_turns=300, spec_name=None,
                   agent_type=None):
        self.run_agent_calls.append(run_id)
        raise RuntimeError(self.message)


class ZeroRoundRunner(FakeRunner):
    """0 rounds 秒挂替身（无异常路径——信封 ``rounds`` 透传判定形态）。"""

    def _run_agent(self, prompt, project_root, run_id, model_override,
                   env_overrides, max_turns=300, spec_name=None,
                   agent_type=None):
        self.run_agent_calls.append(run_id)
        usage = {"input_tokens": 0, "output_tokens": 0,
                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        return ("", 0, None, usage, None)


def seed_unhealthy(lane, reasons=("宿主 CLI 不在 PATH",)):
    """预种探针 unhealthy（密闭拦截用例；make_lane 预种 healthy 的反向）。"""
    lane._preflight_cache._health = LaneHealth(ok=False, reasons=list(reasons))
    lane._preflight_cache._probed_at = __import__("time").monotonic()


def ledger_kinds(tmp_path):
    return [str(rec.get("kind") or "") for rec in load_arbiter_ledger(tmp_path)]


def lane_env_alerts(tmp_path):
    return [
        rec for rec in AdminStore(tmp_path).read_all()
        if rec.get("signal_type") == LANE_ENV_ALERT_SIGNAL
    ]


def human_escalations(tmp_path):
    return [
        rec for rec in AdminStore(tmp_path).read_all()
        if rec.get("kind") == ESCALATION
        and rec.get("signal_type") != LANE_ENV_ALERT_SIGNAL
    ]


@pytest.fixture(autouse=True)
def _lane_cleanup():
    yield
    reset_lane()


# ══ 能力一：arbiter-infra-failure-reset ════════════════════════════


class TestClassifyLaneFailure:
    """分级器单元口径（R1：0 rounds 信封透传 + 环境指纹，禁文案反解）。"""

    def test_zero_rounds_is_infra(self):
        assert classify_lane_failure({"rounds": 0}) == "infra"
        assert classify_lane_failure({"rounds": -1}) == "infra"

    def test_rounds_absent_conservative_judgment(self):
        # 旧信封/测试替身无 rounds 键：保守判 judgment（零行为变化）
        assert classify_lane_failure({}) == "judgment"
        assert classify_lane_failure({"summary": "s", "outcome": "bogus"}) == (
            "judgment"
        )

    def test_positive_rounds_judgment(self):
        assert classify_lane_failure({"rounds": 1}) == "judgment"
        assert classify_lane_failure({"rounds": 3, "error": "gateway 5xx"}) == (
            "judgment"
        )

    def test_fingerprint_overrides_rounds(self):
        assert classify_lane_failure(
            {"rounds": 3, "error": f"x {MISSING_CRED_MSG} y"}
        ) == "infra"

    def test_fingerprints_cover_incident_surface(self):
        assert classify_lane_failure(
            {"error": "sh: dsh: No such file or directory"}) == "infra"
        assert classify_lane_failure(
            {"stderr": "skipping profile bundle prof-1"}) == "infra"
        assert classify_lane_failure(
            {"error": "dsh: MISSING_CREDENTIAL"}) == "infra"


class TestRunArbiterRoundsPassthrough:
    """run_arbiter 信封 ``rounds`` 透传（R1：分级按信封真值，禁文案反解）。"""

    def test_normal_path_carries_turns(self, tmp_path):
        runner = FakeRunner(tmp_path)
        envelope = run_arbiter(runner, {"spec": "spec-a"})
        assert envelope["rounds"] == 1  # _run_agent 5 元组第 2 位
        assert envelope["ok"] is False  # 空报告产物硬门（既有语义）

    def test_exception_path_rounds_zero(self, tmp_path):
        runner = InfraRunner(tmp_path)
        envelope = run_arbiter(runner, {"spec": "spec-a"})
        assert envelope["rounds"] == 0
        assert envelope["ok"] is False
        assert "MISSING_CREDENTIAL" in str(envelope.get("error") or "")


class TestInfraChannelS1:
    """S1：0 rounds + 环境指纹连败 ≥ 上限 → 全 infra-failed、零 dead-man、
    零人工升级；同签名资格保留可再试。"""

    def test_consecutive_infra_never_deadman(self, tmp_path):
        lane = make_lane(tmp_path, runner=InfraRunner(tmp_path))
        for _ in range(3):  # 超过缺省上限 2 仍资格保留
            assert lane.submit_trigger(
                spec="spec-a", signal_type="verify_env_blocked") == "queued"
            assert drain(lane)
        assert ledger_kinds(tmp_path) == ["infra-failed"] * 3
        assert not lane._deadmanned, "infra MUST NOT 进死人开关"
        # 告警：车道环境单发（dedup），无人工升级件
        assert len(lane_env_alerts(tmp_path)) == 1
        assert human_escalations(tmp_path) == []
        # 台账 action 注明待复位（不烧资格）
        recs = load_arbiter_ledger(tmp_path)
        assert "待健康探针复位" in str(recs[-1].get("action_or_upgrade") or "")
        # 日志 WARNING 留痕（不升级人工）
        assert any(
            lv == "warning" and "infra-failed" in m
            for lv, _c, m in lane.logger.records
        )

    def test_zero_rounds_without_exception_is_infra(self, tmp_path):
        lane = make_lane(tmp_path, runner=ZeroRoundRunner(tmp_path))
        assert lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked") == "queued"
        assert drain(lane)
        assert ledger_kinds(tmp_path) == ["infra-failed"]
        assert not lane._deadmanned


class TestJudgmentRegressionS2:
    """S2：有 API 往返的失败连败 → 现行 dead-man 永久升级（回归不变）。"""

    def test_roundtrip_failures_still_deadman(self, tmp_path):
        # 缺省 FakeRunner：报告写盘但空 → 产物硬门失败，turns=1（有往返）；
        # 未达上限不内循环（等同签名下次触发），两次触发到 cap
        lane = make_lane(tmp_path)
        for _ in range(2):
            assert lane.submit_trigger(
                spec="spec-a", signal_type="verify_env_blocked") == "queued"
            assert drain(lane)
        kinds = ledger_kinds(tmp_path)
        assert "dead-man" in kinds
        assert "infra-failed" not in kinds, "有往返失败 MUST NOT 误判 infra"
        assert SIG in lane._deadmanned


class TestBudgetExhaustedS3:
    """S3：预算耗尽恒判 judgment 走 dead-man，不误判 infra。"""

    def test_budget_exhausted_goes_deadman(self, tmp_path):
        # usage 150 tokens > budget 100 → tokens_exhausted（单次即 dead-man）
        lane = make_lane(tmp_path, config={"budget_tokens": 100})
        assert lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked") == "queued"
        assert drain(lane)
        kinds = ledger_kinds(tmp_path)
        assert "dead-man" in kinds
        assert "infra-failed" not in kinds, "预算耗尽 MUST NOT 误判 infra"


class TestLaneHealthyResetS4:
    """S4：infra 停机后探针转 healthy → 计数清零 + 留痕，同签名恢复处置；
    judgment 连败与 dead-man 不动。"""

    def test_healthy_resets_infra_counts_only(self, tmp_path):
        lane = make_lane(tmp_path, runner=InfraRunner(tmp_path))
        assert lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked") == "queued"
        assert drain(lane)
        assert lane._infra_failure_counts.get(SIG) == 1
        # 预置 judgment 连败与 dead-man（复位 MUST NOT 触碰）
        lane._failure_counts[SIG] = 1
        other = arbiter_failure_signature("spec-b", "other_signal")
        lane._deadmanned.add(other)

        lane.on_lane_healthy(source="test")

        assert lane._infra_failure_counts == {}, "infra 计数 MUST 清零"
        assert lane._failure_counts.get(SIG) == 1, "judgment 连败 MUST NOT 动"
        assert other in lane._deadmanned, "dead-man 永久语义 MUST NOT 动"
        assert any(
            lv == "info" and "infra 计数复位" in m
            for lv, _c, m in lane.logger.records
        )
        # 同签名恢复自主处置（再触发照常入队并再跑）
        assert lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked") == "queued"
        assert drain(lane)
        assert ledger_kinds(tmp_path) == ["infra-failed", "infra-failed"]

    def test_steady_healthy_zero_noise(self, tmp_path):
        """infra 计数为空时复位静默（周期探针高频复用不刷屏）。"""
        lane = make_lane(tmp_path)
        n = len(lane.logger.records)
        lane.on_lane_healthy(source="test")
        assert len(lane.logger.records) == n


class TestLedgerReadSideCompatS5:
    """S5：历史台账含 infra-failed 行 → dead-man 判定/回扫排除与无该行
    完全一致（读侧只认 kind=dead-man）。"""

    def test_infra_rows_invisible_to_deaddman_readside(self, tmp_path):
        arbiter_ledger_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        append_run_line(arbiter_ledger_path(tmp_path), {
            "id": "row-dead", "created": "2026-01-01T00:00:00+00:00",
            "kind": "dead-man", "signature": SIG, "spec": "spec-a",
        })
        append_run_line(arbiter_ledger_path(tmp_path), {
            "id": "row-infra", "created": "2026-01-01T00:01:00+00:00",
            "kind": "infra-failed", "signature": SIG, "spec": "spec-a",
        })
        # 台账解析：infra-failed 行原样保留（不丢不折）
        kinds = ledger_kinds(tmp_path)
        assert kinds == ["dead-man", "infra-failed"]

        lane = make_lane(tmp_path)
        # 读侧 dead-man 签名集只认 dead-man 行（infra 行不改变判定）
        assert lane._ledger_sigs(kinds={"dead-man"}) == {SIG}

    def test_infra_row_does_not_block_redispatch(self, tmp_path):
        """仅 infra-failed 在案：同签名照常自主处置（无永久例外）。"""
        arbiter_ledger_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        append_run_line(arbiter_ledger_path(tmp_path), {
            "id": "row-infra", "created": "2026-01-01T00:01:00+00:00",
            "kind": "infra-failed", "signature": SIG, "spec": "spec-a",
        })
        lane = make_lane(tmp_path)
        assert lane._ledger_sigs(kinds={"dead-man"}) == set()
        assert lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked") == "queued"

    def test_deaddman_row_still_blocks(self, tmp_path):
        """dead-man 行在场：同签名永久例外照旧（infra 行不在场也不变）。"""
        arbiter_ledger_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        append_run_line(arbiter_ledger_path(tmp_path), {
            "id": "row-dead", "created": "2026-01-01T00:00:00+00:00",
            "kind": "dead-man", "signature": SIG, "spec": "spec-a",
        })
        lane = make_lane(tmp_path)
        outcome = lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked")
        assert outcome == "recurrence-escalated"
        assert ledger_kinds(tmp_path).count("dead-man") == 1  # 未再派发


class TestChainInfraDeferredS6:
    """S6：链交接 run infra 失败 → ``infra-failed`` 终态 + 链件不上升人工、
    不循环重派、deferred 范式留痕、不烧拍板配额。"""

    def test_lane_handoff_returns_infra_failed(self, tmp_path):
        lane = make_lane(tmp_path, runner=InfraRunner(tmp_path))
        trigger = {"signature": SIG, "spec": "spec-a",
                   "signal_type": "verify_env_blocked"}
        outcome = lane.process_chain_handoff(trigger)
        assert outcome == "infra-failed"
        assert trigger.get("_chain_run_id"), "run_id 须回填供链留痕"
        assert ledger_kinds(tmp_path) == ["infra-failed"]
        assert not lane._deadmanned

    def test_lane_handoff_gate_intercept_returns_infra_failed(self, tmp_path):
        """前置探针 unhealthy：链交接同样零状态变更让行（infra-failed）。"""
        lane = make_lane(tmp_path)
        seed_unhealthy(lane)
        trigger = {"signature": SIG, "spec": "spec-a",
                   "signal_type": "verify_env_blocked"}
        outcome = lane.process_chain_handoff(trigger)
        assert outcome == "infra-failed"
        assert "前置自检拦截" in str(trigger.get("_chain_failure_reason") or "")
        assert load_arbiter_ledger(tmp_path) == [], "拦截零台账"
        assert not lane._active and not lane._infra_failure_counts

    def test_chain_consumes_infra_without_escalation(self, tmp_path):
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )
        reset_chain()
        chain = EscalationChain(tmp_path, MagicMock())
        chain.set_runner(MagicMock())  # 无 agents.models 分配
        sm = StateMachine(tmp_path / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": False})
        chain.set_state_machine(sm)
        pm = _FakePm(tmp_path)
        chain.set_pm(pm)
        lane = _FakeArbiterLane(tmp_path, outcomes=["infra-failed"])
        patcher = patch("core.pm_engine.arbiter.get_lane", lambda *a, **k: lane)
        patcher.start()
        try:
            chain._dispatch_admin = lambda item: _disp(run_id="adm-1")
            assert chain.submit_entry(
                spec="spec-a", signal_type="verify_env_blocked",
                severity="major", description="验证环境阻塞",
                evidence="env log", recommended_action="修复环境",
                source="unit-test",
            ) == "queued"
            assert _drain_chain(chain)

            chain_sig = str(lane.calls[0]["signature"])
            assert len(lane.calls) == 1, "infra MUST NOT 循环重派"
            assert pm.alerts == [], "infra MUST NOT 上升人工"
            kinds = ledger_kinds(tmp_path)
            assert "chain-infra-deferred" in kinds, "deferred 范式留痕"
            assert "chain-escalated" not in kinds
            # 不烧拍板配额（count_arbiter_ruling 仅在拍板出口计）
            assert ChainQuotaStore(tmp_path).arbiter_rulings(chain_sig) == 0
            assert chain._active == set() or not chain._active
        finally:
            patcher.stop()
            reset_chain()


# ══ 能力二：agent-lane-preflight ═══════════════════════════════════


class TestProbeLaneHealth:
    """探针两级检查（密闭：precheck/adapter 面 patch，不依赖宿主环境）。"""

    def _patch_precheck(self, monkeypatch, ret=None, exc=None):
        import core.agent_runner.harness as harness_mod

        def _fake(executable):
            if exc is not None:
                raise exc
            return ret

        monkeypatch.setattr(harness_mod, "precheck_harness_executable", _fake)
        # probe 惰性 import 同名符号，patch 源模块即可被取到
        import core.agent_runner.lane_preflight as lp

        monkeypatch.setattr(
            lp, "precheck_harness_executable", _fake, raising=False)

    def test_probe_ok_hermetic(self, monkeypatch):
        self._patch_precheck(monkeypatch, ret=None)
        health = probe_lane_health({})
        assert health.ok, health.reasons  # claude 通道无 check_health 零动作

    def test_probe_cli_missing_unhealthy(self, monkeypatch):
        self._patch_precheck(monkeypatch, ret="claude 未找到于 PATH")
        health = probe_lane_health({})
        assert not health.ok
        assert any("PATH" in r for r in health.reasons)

    def test_probe_credentials_missing_unhealthy(self, monkeypatch):
        self._patch_precheck(monkeypatch, ret=None)
        config = {
            "llm": {"providers": [{"name": "p1", "baseurl": "", "apikey": ""}]},
            "agents": {"models": {
                "arbiter": {"provider": "p1", "model": "m"},
                "repair": {"provider": "p1", "model": "m"},
            }},
        }
        health = probe_lane_health(config)
        assert not health.ok
        joined = "；".join(health.reasons)
        assert "凭据路由不可解析" in joined
        assert "arbiter" in joined and "repair" in joined

    def test_probe_credentials_ok_not_reported(self, monkeypatch):
        self._patch_precheck(monkeypatch, ret=None)
        config = {
            "llm": {"providers": [
                {"name": "p1", "baseurl": "https://gw.example", "apikey": "k"},
            ]},
            "agents": {"models": {"arbiter": {"provider": "p1", "model": "m"}}},
        }
        health = probe_lane_health(config)
        assert health.ok, health.reasons

    def test_probe_internal_exception_unhealthy_no_raise(self, monkeypatch):
        self._patch_precheck(
            monkeypatch, exc=RuntimeError("which 爆炸"))
        health = probe_lane_health({})  # MUST NOT 抛出
        assert not health.ok
        assert any("探测异常" in r for r in health.reasons)

    def test_probe_unassigned_chain_skipped(self, monkeypatch):
        """无显式模型链：本地无可判对象，跳过不报（默认网关形态）。"""
        self._patch_precheck(monkeypatch, ret=None)
        config = {"agents": {"models": {}}}
        assert probe_lane_health(config).ok


class TestPreflightCacheTtlS4:
    """S4：TTL 内多次取用只探一次；过期/失效重探。"""

    def test_cache_reuses_within_ttl(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: (
                calls.append(1) or LaneHealth(ok=True, reasons=[])
            ),
        )
        cache = LanePreflightCache(ttl_s=300)
        assert cache.get_or_probe({}).ok
        assert cache.get_or_probe({}).ok
        assert len(calls) == 1, "TTL 内 MUST 复用缓存结论"

    def test_ttl_zero_reprobes(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: (
                calls.append(1) or LaneHealth(ok=True, reasons=[])
            ),
        )
        cache = LanePreflightCache(ttl_s=0)
        cache.get_or_probe({})
        cache.get_or_probe({})
        assert len(calls) == 2, "TTL=0 每次取用都重探"

    def test_invalidate_forces_reprobe(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: (
                calls.append(1) or LaneHealth(ok=True, reasons=[])
            ),
        )
        cache = LanePreflightCache(ttl_s=300)
        cache.get_or_probe({})
        cache.invalidate()
        cache.get_or_probe({})
        assert len(calls) == 2


class TestPreflightGate:
    """派发前置闸（submit_trigger / process_chain_handoff 拦截点）。"""

    def test_unhealthy_intercept_deduped_zero_state(self, tmp_path):
        """S1/S5：拦截返回既有终态字 deduped，零状态变更零台账。"""
        lane = make_lane(tmp_path)
        seed_unhealthy(lane)
        outcome = lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked")
        assert outcome == "deduped"
        assert not lane._active, "MUST NOT 写 _active"
        assert not lane._infra_failure_counts, "MUST NOT 计 infra 配额"
        assert load_arbiter_ledger(tmp_path) == [], "MUST NOT 落台账"
        assert lane._queue.qsize() == 0, "MUST NOT 入队"
        assert any(
            lv == "warning" and "派发前置自检拦截" in m
            for lv, _c, m in lane.logger.records
        )

    def test_gate_healthy_resets_prior_infra_counts(self, tmp_path):
        """S2：探针 healthy → 派发放行；此前 infra 停机计数复位。"""
        lane = make_lane(tmp_path, runner=InfraRunner(tmp_path))
        trigger = {"signature": SIG, "spec": "spec-a",
                   "signal_type": "verify_env_blocked"}
        lane._on_run_failed(trigger, {
            "ok": False, "rounds": 0, "error": MISSING_CRED_MSG, "report": {},
        }, {})
        assert lane._infra_failure_counts.get(SIG) == 1
        # 下次派发闸 healthy（make_lane 预种）→ 放行且复位
        assert lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked") == "queued"
        assert lane._infra_failure_counts == {}, "闸 healthy MUST 复位计数"

    def test_gate_probes_once_within_ttl(self, tmp_path, monkeypatch):
        """S4（车道侧）：TTL 内多次派发只探一次。"""
        calls = []
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: (
                calls.append(1) or LaneHealth(ok=True, reasons=[])
            ),
        )
        lane = make_lane(tmp_path)
        lane._preflight_cache.invalidate()
        for _ in range(2):
            assert lane.submit_trigger(
                spec="spec-a", signal_type="verify_env_blocked") == "queued"
            assert drain(lane)  # 首触发消费完再提交（否则同签名 dedup）
        assert len(calls) == 1, "TTL 内两次派发只探一次"

    def test_gate_ttl_hot_update_rebuilds_cache(self, tmp_path, monkeypatch):
        """preflight_ttl 热更新：闸按新 TTL 重建缓存（下次取用新节拍）。"""
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: LaneHealth(
                ok=True, reasons=[]),
        )
        lane = make_lane(tmp_path)
        lane.config = lambda: {
            "enabled": True, "budget_wallclock_s": 1800,
            "budget_tokens": 1000000, "max_consecutive_failures": 2,
            "max_consecutive_infra_failures": 2, "preflight_ttl": 600,
        }
        assert lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked") == "queued"
        assert lane._preflight_cache.ttl_s == 600

    def test_gate_disabled_lane_zero_interference(self, tmp_path):
        """关闭态零侵扰：disabled 先行短路，探针不把关不产生副作用。"""
        lane = make_lane(tmp_path, config={"enabled": False})
        seed_unhealthy(lane)
        assert lane.submit_trigger(
            spec="spec-a", signal_type="verify_env_blocked") == "disabled"
        assert lane_env_alerts(tmp_path) == []


# ══ fenixd 接线（能力二 S1 启动面 + 告警生命周期）═══════════════════


class TestFenixdLanePreflightWiring:
    """启动自检 + 周期重探 + 告警单发/恢复自动关闭（fenixd.py 3.2 接线）。

    真实 AdminStore 落 tmp（patch fenixd.PROJECT_ROOT）；探针 patch 到
    LaneHealth 脚本，不依赖宿主环境。
    """

    def _mk_daemon(self):
        import fenixd

        d = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
        d.logger = FakeLogger()
        d.config = {}
        d._lane_preflight_ever_unhealthy = False
        d._lane_preflight_next_ts = 0.0
        return d

    def test_unhealthy_alert_single_shot_then_auto_close(
        self, tmp_path, monkeypatch,
    ):
        import fenixd

        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: LaneHealth(
                ok=False, reasons=["cli 缺失", "凭据缺失"]),
        )
        d = self._mk_daemon()
        d._startup_lane_preflight_check()
        d._startup_lane_preflight_check()  # 同 unhealthy 周期第二次
        alerts = lane_env_alerts(tmp_path)
        assert len(alerts) == 1, "dedup_key 单发"
        assert "cli 缺失" in str(alerts[0].get("evidence") or "")
        assert d._lane_preflight_ever_unhealthy is True
        assert human_escalations(tmp_path) == [], "非人工升级件"

        # 探针转 healthy：自动关闭 + 边沿 INFO + 旗标复位
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: LaneHealth(
                ok=True, reasons=[]),
        )
        d._startup_lane_preflight_check()
        alerts = lane_env_alerts(tmp_path)
        assert len(alerts) == 1
        assert alerts[0].get("handled") is True
        assert alerts[0].get("handled_by") == "auto-resolve"
        assert d._lane_preflight_ever_unhealthy is False
        assert any(
            lv == "info" and "healthy" in m
            for lv, _c, m in d.logger.records
        )

    def test_steady_healthy_zero_alert_noise(self, tmp_path, monkeypatch):
        import fenixd

        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: LaneHealth(
                ok=True, reasons=[]),
        )
        d = self._mk_daemon()
        d._startup_lane_preflight_check()
        n = len(d.logger.records)
        d._startup_lane_preflight_check()  # 常态 healthy：零播报
        assert len(d.logger.records) == n
        assert lane_env_alerts(tmp_path) == []

    def test_periodic_tick_gated_at_60s(self, tmp_path, monkeypatch):
        import time as _time

        import fenixd

        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        calls = []
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: (
                calls.append(1) or LaneHealth(ok=True, reasons=[])
            ),
        )
        d = self._mk_daemon()
        d._lane_preflight_next_ts = _time.time() - 1  # 到期
        d._lane_preflight_periodic_tick()
        assert len(calls) == 1
        assert d._lane_preflight_next_ts > _time.time() + 50
        d._lane_preflight_periodic_tick()  # 门内
        assert len(calls) == 1, "时间门内不得重复探测"

    def test_startup_check_advances_periodic_gate(self, tmp_path, monkeypatch):
        import time as _time

        import fenixd

        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: LaneHealth(
                ok=True, reasons=[]),
        )
        d = self._mk_daemon()
        assert d._lane_preflight_next_ts == 0.0
        d._startup_lane_preflight_check()
        assert d._lane_preflight_next_ts > _time.time() + 50, (
            "启动探测后周期门同步推进（主循环首轮不重复探测）"
        )

    def test_consume_fail_open_on_alert_store_error(
        self, tmp_path, monkeypatch,
    ):
        import fenixd

        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)

        def _boom(*a, **k):
            raise RuntimeError("admin store 爆炸")

        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.ensure_lane_env_alert", _boom)
        d = self._mk_daemon()
        # MUST NOT 抛出（消费链异常降级 WARNING，不击穿启动序列/主循环）
        d._lane_preflight_consume(
            LaneHealth(ok=False, reasons=["r"]), source="t")
        assert any(
            lv == "warning" and "fail-open" in m
            for lv, _c, m in d.logger.records
        )

    def test_periodic_tick_calls_lane_reset_when_healthy(
        self, tmp_path, monkeypatch,
    ):
        """周期探针 healthy → 在场车道单例复位消费（能力一 R3 触发点）。"""
        import fenixd

        monkeypatch.setattr(fenixd, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(
            "core.agent_runner.lane_preflight.probe_lane_health",
            lambda config, logger=None, health_timeout=5.0: LaneHealth(
                ok=True, reasons=[]),
        )
        lane = make_lane(tmp_path)
        lane._infra_failure_counts[SIG] = 1
        import core.pm_engine.arbiter as arb

        monkeypatch.setattr(arb, "get_lane", lambda: lane)
        d = self._mk_daemon()
        d._lane_preflight_next_ts = 0.0
        d._lane_preflight_periodic_tick()
        assert lane._infra_failure_counts == {}, "周期 healthy MUST 复位计数"


# ══ 配置白名单（get_arbiter_config 两新键）══════════════════════════


class TestArbiterConfigNewKeys:
    """get_arbiter_config 白名单扩展（R2：缺省值与正整数归一）。"""

    def test_defaults_present(self):
        cfg = ConfigLoader.get_arbiter_config({})
        assert cfg["max_consecutive_infra_failures"] >= 1
        assert cfg["preflight_ttl"] >= 1

    def test_explicit_values_normalized(self):
        cfg = ConfigLoader.get_arbiter_config({
            "arbiter": {
                "max_consecutive_infra_failures": 5,
                "preflight_ttl": 60,
            },
        })
        assert cfg["max_consecutive_infra_failures"] == 5
        assert cfg["preflight_ttl"] == 60
