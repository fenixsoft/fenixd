"""
test_review_circuit_breaker.py — evo-run-failure-classification-circuitbreaker 单元测试。

验收标准（tasks.md 4.1-4.3）：
  4.1 连续 3 次 infra → 熔断（不再派发、恰好 1 条 critical）；冷却后自动恢复重试
  4.2 内容失败维持重试语义；artifact 失败不重试
  4.3 熔断状态 daemon 重启后恢复（持久化读回）
"""

import json
import os
import time
from typing import Dict, Optional
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 避免真实依赖：构造最小 PMEngine mock
from core.pm_engine.infra_breaker import InfraCircuitBreaker


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_project(tmp_path):
    """最小 project root，含 .fenix/ 目录。"""
    (tmp_path / ".fenix").mkdir(exist_ok=True)
    return tmp_path


@pytest.fixture
def breaker(tmp_project):
    """默认配置（threshold=3, cooldown=30min）的 InfraCircuitBreaker。"""
    return InfraCircuitBreaker(
        tmp_project,
        {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}},
    )


class FakeStateMachine:
    """最小 state_machine mock，支持 read_one / update_spec / bump_counters。

    freeze_for_human 签名与 production（core/state_machine.py:624）逐参对齐
    （测试替身保真守卫：宽容 **kwargs 替身违规）。
    """
    def __init__(self):
        self._specs = {}

    def read_one(self, spec_name):
        return self._specs.get(spec_name)

    def update_spec(self, spec_name, updates):
        if spec_name not in self._specs:
            self._specs[spec_name] = {}
        self._specs[spec_name].update(updates)

    def bump_counters(self, spec_name: str, deltas: Dict[str, int]) -> Dict[str, int]:
        """计数器原地递增，契约与 production（core/state_machine.py:1034）对齐：
        各字段按 delta 累加（负 delta 下限 0），返回 ``{field: 最终生效值}``；
        SPEC 不存在时返回全 0（production 另记 warning，替身省略日志）。
        """
        if spec_name not in self._specs:
            return {field: 0 for field in deltas}
        entry = self._specs[spec_name]
        result = {}
        for field, delta in deltas.items():
            try:
                current = int(entry.get(field, 0) or 0)
            except (TypeError, ValueError):
                current = 0
            result[field] = max(0, current + delta)
            entry[field] = result[field]
        return result

    def freeze_for_human(
        self,
        spec_name: str,
        *,
        error: str,
        signal_type: str,
        severity: str,
        description: str,
        evidence: str,
        recommended_action: str,
        alert_callback=None,
        extra_updates: Optional[dict] = None,
    ) -> bool:
        self.update_spec(spec_name, {"frozen": True})
        return True


# ── infra_breaker 测试 ─────────────────────────────────────────────

class TestInfraCircuitBreaker:
    """InfraCircuitBreaker 核心行为（链路无关，可独立测试）。"""

    def test_no_trigger_below_threshold(self, breaker):
        """前两次 infra 失败不触发熔断。"""
        assert breaker.record_failure("spec-review") is False
        assert breaker.record_failure("spec-review") is False
        assert not breaker.is_open("spec-review")

    def test_trigger_at_threshold(self, breaker):
        """第三次连续 infra 失败触发熔断（恰好 1 次）。"""
        assert breaker.record_failure("spec-review") is False
        assert breaker.record_failure("spec-review") is False
        assert breaker.record_failure("spec-review") is True  # 触发
        assert breaker.is_open("spec-review")
        assert breaker.cooldown_remaining("spec-review") > 0

    def test_cooldown_auto_recovery(self, breaker):
        """冷却到期自动恢复（窗口滑动，惰性判定）。"""
        breaker.record_failure("spec-review")  # 1
        breaker.record_failure("spec-review")  # 2
        breaker.record_failure("spec-review")  # 3 → 触发熔断
        assert breaker.is_open("spec-review")

        # 模拟冷却到期：直接修改 until 为过去时间
        st = breaker.get_state("spec-review")
        breaker._cache["spec-review"]["until"] = time.time() - 1  # 刚刚到期
        # condition() 应返回 "recovered" 并翻转
        assert breaker.condition("spec-review") == "recovered"
        assert not breaker.is_open("spec-review")  # 已恢复

    def test_success_clears_count(self, breaker):
        """成功 run 清零计数（"连续 ≥3 次"语义）。"""
        breaker.record_failure("spec-review")  # count=1
        breaker.record_failure("spec-review")  # count=2
        breaker.record_success("spec-review")   # 清零
        assert breaker.get_state("spec-review")["count"] == 0
        assert not breaker.is_open("spec-review")
        # 再两次失败仍不触发（需 3 次连续）
        assert breaker.record_failure("spec-review") is False
        assert breaker.record_failure("spec-review") is False
        assert not breaker.is_open("spec-review")

    def test_persistence_survives_reload(self, tmp_project):
        """熔断状态持久化，daemon 重启后恢复（4.3）。"""
        path = tmp_project / ".fenix" / "admin_infra_breaker.json"
        # 第一个实例触发熔断
        b1 = InfraCircuitBreaker(
            tmp_project,
            {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}})
        b1.record_failure("spec-review")
        b1.record_failure("spec-review")
        b1.record_failure("spec-review")  # 触发
        assert b1.is_open("spec-review")
        # 状态已写盘
        assert path.exists()

        # 第二个实例（模拟 daemon 重启）从文件恢复
        b2 = InfraCircuitBreaker(
            tmp_project,
            {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}})
        assert b2.is_open("spec-review")
        assert b2.get_state("spec-review")["count"] == 3

    def test_corrupted_state_fail_open(self, tmp_project):
        """损坏状态文件 fail-open（不阻塞派发）。"""
        path = tmp_project / ".fenix" / "admin_infra_breaker.json"
        path.write_text("NOT JSON", encoding="utf-8")
        b = InfraCircuitBreaker(tmp_project, {})
        assert not b.is_open("spec-review")  # fail-open：不熔断

    def test_half_open_failure_re_triggers(self, breaker):
        """半开探测失败 → 立即重新熔断（count 达标触发）。"""
        # 三次失败触发熔断
        for _ in range(3):
            breaker.record_failure("spec-review")
        assert breaker.is_open("spec-review")
        # 模拟冷却到期 → 恢复
        breaker._cache["spec-review"]["until"] = time.time() - 1
        assert breaker.condition("spec-review") == "recovered"
        assert not breaker.is_open("spec-review")
        # 此时 count=3，再次失败 → count=4 >= threshold → 立即重新熔断
        assert breaker.record_failure("spec-review") is True
        assert breaker.is_open("spec-review")


# ── _classify_run_failure 测试 ─────────────────────────────────────

class TestClassifyRunFailure:
    """三类失败分类（1.1）。"""

    def _make_manager(self, tmp_project, artifact_valid=False):
        """构造 SpecReviewManager（最小 mock）。"""
        from core.pm_engine.spec_review import SpecReviewManager
        manager = SpecReviewManager(
            tmp_project,
            FakeStateMachine(),
            MagicMock(),
            MagicMock(config={"admin": {}}),
            {"admin": {}},
            logger=MagicMock(),
        )
        manager.pm_engine.infra_breaker = InfraCircuitBreaker(
            tmp_project,
            {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}})
        # 可控的 _artifact_landed_valid mock
        manager._artifact_landed_valid = lambda s: artifact_valid
        return manager

    def test_infra_403(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("403 Forbidden", "test") == "infra"

    def test_infra_402(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("402 Payment Required", "test") == "infra"

    def test_infra_429(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("429 Too Many Requests", "test") == "infra"

    def test_infra_quota(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("quota exceeded", "test") == "infra"

    def test_infra_budget(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("评审 budget exhausted", "test") == "infra"

    def test_infra_balance(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("Insufficient balance", "test") == "infra"

    def test_infra_rate_limit(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("Rate limit exceeded", "test") == "infra"

    def test_infra_provider_circuit_open(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure(
            "provider circuit open: openai (HTTP 403 x 3) — cooldown 1800s remaining",
            "test") == "infra"

    def test_infra_provider_chain_exhausted(self, tmp_project):
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure(
            "provider chain exhausted for spec-review 'test': all 3 candidates in switch/4xx cooldown",
            "test") == "infra"

    def test_infra_exit_code_non_content(self, tmp_project):
        """Exit code 非 0/1 → infra（CLI 进程级崩溃）。"""
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("Exit code: 127", "test") == "infra"
        assert m._classify_run_failure("Exit code: -9", "test") == "infra"
        assert m._classify_run_failure("Exit code: 2", "test") == "infra"

    def test_content_exit_code_1(self, tmp_project):
        """Exit code: 1 → content（评审器内容失败，不得一律判 infra）。"""
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure("Exit code: 1", "test") == "content"

    def test_content_normal(self, tmp_project):
        """普通失败文本 → content。"""
        m = self._make_manager(tmp_project)
        assert m._classify_run_failure(
            "unknown status: rejected", "test") == "content"
        assert m._classify_run_failure(
            "结果文件读取失败: No such file", "test") == "content"

    def test_artifact_overrides_infra(self, tmp_project):
        """artifact 优先级最高（即使 reason 含 infra 指纹，产物已合法落盘 → artifact）。"""
        m = self._make_manager(tmp_project, artifact_valid=True)
        assert m._classify_run_failure("403 Forbidden", "test") == "artifact"


# ── _handle_review_failure 测试 ───────────────────────────────────

class TestHandleReviewFailure:
    """_handle_review_failure 按分类落点（1.2）。"""

    def _setup(self, tmp_project, artifact_valid=False):
        from core.pm_engine.spec_review import SpecReviewManager
        sm = FakeStateMachine()
        sm.update_spec("test-spec", {
            "_review_attempts": 0,
            "reviewer_run": None,
        })
        pm = MagicMock()
        pm.is_review_in_flight = MagicMock(return_value=False)
        pm.infra_breaker = InfraCircuitBreaker(
            tmp_project,
            {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}})
        manager = SpecReviewManager(tmp_project, sm, MagicMock(), pm, {"admin": {}},
                                      logger=MagicMock())
        manager._artifact_landed_valid = lambda s: artifact_valid
        manager.consume_review_result = MagicMock(return_value=True)
        return manager, sm, pm

    def test_infra_failure_does_not_increment_attempts(self, tmp_project):
        """infra 失败：清 reviewer_run、不递增 _review_attempts。"""
        m, sm, pm = self._setup(tmp_project)
        breaker = pm.infra_breaker
        assert breaker.get_state("spec-review")["count"] == 0
        m._handle_review_failure("test-spec", "403 Forbidden")
        entry = sm.read_one("test-spec")
        assert entry["reviewer_run"] is None
        assert entry["_review_attempts"] == 0  # 未递增
        assert "infra failure" in entry["error"]
        assert breaker.get_state("spec-review")["count"] == 1

    def test_infra_failure_triggers_alert_on_third(self, tmp_project):
        """连续第 3 次 infra 失败触发熔断告警（恰好 1 条）。"""
        m, sm, pm = self._setup(tmp_project)
        pm._emit_infra_breaker_event = MagicMock()
        # 两次不触发
        m._handle_review_failure("test-spec", "403 Forbidden")
        m._handle_review_failure("test-spec", "403 Forbidden")
        pm._emit_infra_breaker_event.assert_not_called()
        # 第三次触发
        m._handle_review_failure("test-spec", "403 Forbidden")
        pm._emit_infra_breaker_event.assert_called_once()
        args = pm._emit_infra_breaker_event.call_args
        assert args[0][0] == "triggered"

    def test_content_failure_increments_attempts(self, tmp_project):
        """content 失败：递增 _review_attempts（既有重试语义）。"""
        m, sm, pm = self._setup(tmp_project)
        m._handle_review_failure("test-spec", "unknown status: rejected")
        entry = sm.read_one("test-spec")
        assert entry["_review_attempts"] == 1  # 递增

    def test_artifact_failure_consumes_directly(self, tmp_project):
        """artifact 失败：直接消费（不重试）。"""
        m, sm, pm = self._setup(tmp_project, artifact_valid=True)
        m._handle_review_failure("test-spec", "some error")
        m.consume_review_result.assert_called_once_with("test-spec")


# ── dispatch_review 短路测试 ───────────────────────────────────────

class TestDispatchReviewShortCircuit:
    """熔断窗口内 dispatch_review 短路（2.1）。"""

    def test_dispatch_short_circuits_when_broken(self, tmp_project):
        """熔断窗口内 dispatch_review 返回 False（不派发）。"""
        from core.pm_engine.spec_review import SpecReviewManager
        sm = FakeStateMachine()
        sm.update_spec("test-spec", {"reviewer_run": None})
        pm = MagicMock()
        pm.is_review_in_flight = MagicMock(return_value=False)
        breaker = InfraCircuitBreaker(
            tmp_project,
            {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}})
        pm.infra_breaker = breaker
        pm._emit_infra_breaker_event = MagicMock()
        manager = SpecReviewManager(tmp_project, sm, MagicMock(), pm, {"admin": {}},
                                      logger=MagicMock())
        # 手动触发熔断
        for _ in range(3):
            breaker.record_failure("spec-review")
        assert breaker.is_open("spec-review")
        # dispatch_review 应被短路
        result = manager.dispatch_review("test-spec")
        assert result is False

    def test_dispatch_recovers_after_cooldown(self, tmp_project):
        """冷却到期后 dispatch_review 恢复（不短路）+ 落恢复 SIGNAL 记录。"""
        from core.pm_engine.spec_review import SpecReviewManager
        sm = FakeStateMachine()
        sm.update_spec("test-spec", {"reviewer_run": None, "_review_attempts": 0})
        pm = MagicMock()
        pm.is_review_in_flight = MagicMock(return_value=False)
        pm._emit_infra_breaker_event = MagicMock()
        breaker = InfraCircuitBreaker(
            tmp_project,
            {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}})
        pm.infra_breaker = breaker
        # 触发熔断
        for _ in range(3):
            breaker.record_failure("spec-review")
        # 模拟冷却到期
        breaker._cache["spec-review"]["until"] = time.time() - 1
        manager = SpecReviewManager(tmp_project, sm, MagicMock(), pm, {"admin": {}},
                                    logger=MagicMock())
        manager._take_snapshot = MagicMock(return_value={})
        manager.agent_runner._check_agent_result_artifact = MagicMock(return_value=None)
        manager.agent_runner._salvage_spec_review_result = MagicMock()
        # 模拟 run_spec_review 成功（返回 ok=True）——但 dispatcher 会同步阻塞。
        # 我们需要 mock 掉 run 调用；dispatch_review 内部第一步是读 entry、检查 attempts，
        # 然后更新 reviewer_run、快照、运行 run。这里 mock 掉 run 返回成功。
        from unittest.mock import patch as _patch
        # 显式构造 AgentRunResult-like mock
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.error = None
        with _patch.object(manager.agent_runner, 'run_spec_review', return_value=mock_result):
            # 同时 mock consume_review_result 使其不真实执行（会读不存在的文件）
            manager.consume_review_result = MagicMock(return_value=True)
            result = manager.dispatch_review("test-spec")
        # dispatch_review 应该成功（不短路），并且因为冷却已恢复，落恢复记录
        assert result is True
        pm._emit_infra_breaker_event.assert_called_once()
        args = pm._emit_infra_breaker_event.call_args
        assert args[0][0] == "recovered"
        assert breaker.get_state("spec-review")["count"] == 3


# ── PMEngine 级集成测试 ─────────────────────────────────────────────

def _make_engine(tmp_path):
    """构造真实 PMEngine（agent_runner/state_machine 用 mock）。"""
    from core.pm_engine import PMEngine
    sm = FakeStateMachine()
    sm.update_spec("test-spec", {
        "status": "reviewing",
        "reviewer_run": None,
        "_review_attempts": 0,
    })
    engine = PMEngine(sm, MagicMock(), {}, tmp_path, MagicMock())
    return engine, sm


class TestEngineIntegration:
    """PMEngine 级集成：熔断短路 / 告警落盘 / 恢复。"""

    def test_on_spec_reviewing_short_circuits_when_broken(self, tmp_path):
        """熔断窗口内 _on_spec_reviewing 不派发。"""
        engine, sm = _make_engine(tmp_path)
        # 触发熔断
        for _ in range(3):
            engine.infra_breaker.record_failure("spec-review")
        assert engine.infra_breaker.is_open("spec-review")
        engine._on_spec_reviewing("test-spec")
        # 不派发：reviewer_run 保持空
        entry = sm.read_one("test-spec")
        assert entry["reviewer_run"] is None

    def test_emit_triggered_writes_one_critical(self, tmp_path):
        """熔断触发：恰好 1 条 critical ESCALATION（4.1 验收）。"""
        from core.admin_store import AdminStore
        engine, sm = _make_engine(tmp_path)
        breaker = engine.infra_breaker
        breaker.record_failure("spec-review")  # count=1
        breaker.record_failure("spec-review")  # count=2
        # 第三次触发熔断并落告警
        triggered = breaker.record_failure("spec-review")
        assert triggered is True
        engine._emit_infra_breaker_event(
            "triggered", "test-spec", "403 Forbidden",
            breaker.get_state("spec-review"))
        store = AdminStore(tmp_path)
        recs = store.read_all()
        infra_recs = [r for r in recs if r.get("signal_type") == "run_infra_failure"]
        # 恰好 1 条 critical ESCALATION
        assert len(infra_recs) == 1
        assert infra_recs[0]["kind"] == "escalation"
        assert infra_recs[0]["severity"] == "critical"
        assert infra_recs[0]["spec"] == "test-spec"
        assert "count=3" in infra_recs[0]["evidence"]

    def test_emit_recovered_writes_signal(self, tmp_path):
        """熔断恢复：落 SIGNAL 记录（不绑定 spec）。"""
        from core.admin_store import AdminStore
        engine, sm = _make_engine(tmp_path)
        breaker = engine.infra_breaker
        for _ in range(3):
            breaker.record_failure("spec-review")
        engine._emit_infra_breaker_event(
            "recovered", "test-spec", "", breaker.get_state("spec-review"))
        store = AdminStore(tmp_path)
        recs = store.read_all()
        infra_recs = [r for r in recs if r.get("signal_type") == "run_infra_failure"]
        assert len(infra_recs) == 1
        assert infra_recs[0]["kind"] == "signal"
        assert infra_recs[0]["spec"] is None  # 链路级恢复

    def test_full_cycle_triple_failure_then_recovery(self, tmp_path):
        """完整链路（4.1 验收）：连续 3 次 infra → 熔断 → 冷却恢复。

        通过 _on_spec_reviewing 走真实派发短路；用 _emit_infra_breaker_event
        验证告警恰好 1 条 critical；冷却到期后短路解除。
        """
        from core.admin_store import AdminStore
        engine, sm = _make_engine(tmp_path)
        # 三次 infra 失败，每次走 _handle_review_failure（通过 SpecReviewManager）
        from core.pm_engine.spec_review import SpecReviewManager
        manager = SpecReviewManager(
            tmp_path, sm, MagicMock(), engine, {}, logger=MagicMock())
        manager._artifact_landed_valid = lambda s: False
        manager._handle_review_failure("test-spec", "403 Forbidden")
        manager._handle_review_failure("test-spec", "402 Payment Required")
        manager._handle_review_failure("test-spec", "429 Too Many Requests")
        # 熔断触发
        assert engine.infra_breaker.is_open("spec-review")
        # 冷却窗口内 _on_spec_reviewing 不派发
        engine._on_spec_reviewing("test-spec")
        entry = sm.read_one("test-spec")
        assert entry["reviewer_run"] is None
        # 恰好 1 条 critical（熔断触发时落，后两次失败不重复落）
        store = AdminStore(tmp_path)
        infra_escalations = [
            r for r in store.read_all()
            if r.get("signal_type") == "run_infra_failure"
            and r.get("kind") == "escalation"
        ]
        assert len(infra_escalations) == 1
        assert infra_escalations[0]["severity"] == "critical"
        # 冷却到期 → 自动恢复
        engine.infra_breaker._cache["spec-review"]["until"] = time.time() - 1
        assert engine.infra_breaker.condition("spec-review") == "recovered"
        assert not engine.infra_breaker.is_open("spec-review")
        # 恢复后 _on_spec_reviewing 派发（不短路）：但 agent_runner 是 mock，
        # run_spec_review 返回 MagicMock（success truthy）→ dispatch_review
        # 会继续走 consume_review_result → _check_agent_result_artifact 也是 mock。
        # 直接断言短路已解除（不再因熔断返回）即可。
        engine.infra_breaker.record_success("spec-review")
        assert engine.infra_breaker.get_state("spec-review")["count"] == 0
