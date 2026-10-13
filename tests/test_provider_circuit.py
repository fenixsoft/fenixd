"""provider-fault-fuse 熔断单测（对应 spec provider-fault-fuse）。

覆盖 tasks 2.1-2.6：
- 滚动窗口内 4xx 达阈值触发熔断
- 熔断期派发拦截（不启动 claude、不增 retry、不 flips 状态机）
- 5xx / 网络错误不计数
- 冷却后半开探针：200 闭合、仍 4xx 重新冷却
- 熔断错误文本含 provider 名 / HTTP code / 次数 / 冷却信息
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import (
    PROVIDER_CIRCUIT_4XX,
    PROVIDER_CIRCUIT_COOLDOWN_SECONDS,
    PROVIDER_CIRCUIT_WINDOW_SECONDS,
    AgentRunner,
)
from tests.helpers import FakeLogger, make_runner


def provider_config(provider_name: str = "volc") -> dict:
    """含已分配 provider 的 config（implementer → provider volc）。"""
    return {
        "llm": {
            "providers": [
                {"name": provider_name, "baseurl": "https://api.test",
                 "apikey": "sk", "model": "deepseek-v4-flash"},
            ]
        },
        "agents": {
            "models": {"implementer": {"provider": provider_name, "model": "deepseek-v4-flash"}}
        },
    }


def patch_runner_for_exec(runner: AgentRunner, proot: Path, claude_side_effect=None):
    """给 runner 装上可跑 _execute_agent 的 worktree_manager / _run_agent mock。"""
    wm = MagicMock()
    wm.create.return_value = proot / "wt"
    runner.worktree_manager = wm
    # implementer 产物硬门 stub：本文件关注熔断/半开探针状态机，与实现产物
    # 完成度正交。fix-impl-tasks-completion-gate（2026-09-14）给 implementer 加了
    # worktree 内 .fenix-run-result.json 硬门，而这里的 _run_agent mock 只返回
    # 成功元组、不落结果文件 → 硬门判失败 → 落入 attempt 退避 time.sleep(10)，
    # 单测试实测挂起 15s（test_probe_success_closes_circuit）。
    runner._check_agent_result_artifact = MagicMock(return_value=None)
    if claude_side_effect is not None:
        runner._run_agent = MagicMock(side_effect=claude_side_effect)
    else:
        runner._run_agent = MagicMock(return_value=("ok", 1, "sess-1", {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "cost_usd": None}))


class TestParseApiErrorStatus:
    """parse_api_error_status：从 claude 错误文本解析网关 HTTP 状态码。"""

    def test_parses_http_404(self):
        assert AgentRunner.parse_api_error_status("HTTP 404") == 404

    def test_parses_paren_code(self):
        assert AgentRunner.parse_api_error_status("API error (401): unauthorized") == 401

    def test_parses_status_code_form(self):
        assert AgentRunner.parse_api_error_status("request failed with status code 400") == 400

    def test_parses_api_error_colon_form(self):
        """claude CLI 实际形态「API Error: 403 ...」：冒号后裸数字（fix-403-auth-failover-blindspot）。"""
        err = "Failed to authenticate. API Error: 403 No active subscription found for this group"
        assert AgentRunner.parse_api_error_status(err) == 403

    def test_returns_none_when_no_code(self):
        assert AgentRunner.parse_api_error_status("network timeout") is None
        assert AgentRunner.parse_api_error_status("") is None

    def test_403_in_4xx_set(self):
        """403 鉴权/订阅类与 401 同语义，应计入熔断面（fix-403-auth-failover-blindspot）。"""
        assert 403 in PROVIDER_CIRCUIT_4XX

    def test_403_does_not_trigger_switch(self):
        """403 属鉴权类不触发链前进，走既有熔断路径（fix-403-auth-failover-blindspot）。"""
        err = "Failed to authenticate. API Error: 403 No active subscription found for this group"
        assert not AgentRunner.classify_switch_error(err)

    def test_5xx_not_in_4xx_set(self):
        code = AgentRunner.parse_api_error_status("HTTP 500")
        assert code == 500
        assert code not in PROVIDER_CIRCUIT_4XX


class TestCircuitThresholdAndOpen:
    """2.1 / 2.2：滚动窗口内 4xx 达阈值触发熔断；5xx/网络不计数。

    （审查删除说明：原 test_5xx_not_counted_by_caller 仅循环
    `if code in PROVIDER_CIRCUIT_4XX` 后断言未熔断——等价于集合成员断言，
    已由 TestParseApiErrorStatus.test_5xx_not_in_4xx_set 覆盖，无新增语义。）
    """

    def test_threshold_triggers_open(self, tmp_path, monkeypatch):
        runner = make_runner(tmp_path)
        p = "volc"
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        assert not runner._provider_circuit.is_circuit_open(p, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        assert runner._provider_circuit.is_circuit_open(p, now=now)
        st = runner._provider_circuit.provider_circuits[p]
        assert st["code"] == 404
        assert st["count"] == 3
        assert st["cooldown_until"] > now

    def test_window_slides_old_events_out(self, tmp_path, monkeypatch):
        runner = make_runner(tmp_path)
        p = "volc"
        window = PROVIDER_CIRCUIT_WINDOW_SECONDS
        cooldown = PROVIDER_CIRCUIT_COOLDOWN_SECONDS
        monkeypatch.setattr(runner, "_now", lambda: 1000.0 + 3)
        runner._record_provider_4xx(p, 404, now=1000.0)
        runner._record_provider_4xx(p, 404, now=1000.0 + 1)
        runner._record_provider_4xx(p, 404, now=1000.0 + 2)
        assert runner.is_circuit_open(p, now=1000.0 + 3)
        new_now = 1000.0 + 3 + cooldown + 10
        monkeypatch.setattr(runner, "_now", lambda: new_now)
        runner._record_provider_4xx(p, 404, now=new_now)
        runner._record_provider_4xx(p, 404, now=new_now + 1)
        assert not runner.is_circuit_open(p, now=new_now + 2)
        runner._record_provider_4xx(p, 404, now=new_now + 2)
        assert runner.is_circuit_open(p, now=new_now + 2)

    def test_configurable_window_threshold_cooldown(self, tmp_path, monkeypatch):
        config = {
            "agents": {
                "provider_circuit_window_seconds": 60,
                "provider_circuit_threshold": 2,
                "provider_circuit_cooldown_seconds": 120,
            }
        }
        runner = make_runner(tmp_path, config)
        p = "volc"
        now = 2000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_provider_4xx(p, 401, now=now)
        runner._provider_circuit._record_provider_4xx(p, 401, now=now)
        assert runner._provider_circuit.is_circuit_open(p, now=now)
        st = runner._provider_circuit.provider_circuits[p]
        assert st["cooldown_until"] == now + 120


class TestCircuitOpenSuppressesDispatch:
    """2.3 / 2.5：熔断期派发拦截——不启动 claude、不增 retry、不 flips 状态机。

    （原 TestCircuitDoesNotFlipStateMachine.test_open_circuit_no_state_machine_touch
    与 test_open_circuit_suppresses_dispatch 同一 setup 同一调用路径、仅多一条
    `_running_agents == {}` 断言——审查后并入本测试，断言全保留。）

    state_machine 构造时为 None，若 _execute_agent 误触会抛 AttributeError，故「未调用」
    被本测试天然保证；且返回结果不携带「应重试」语义（error 明确为 circuit open）。
    """

    def test_open_circuit_suppresses_dispatch(self, tmp_path, monkeypatch):
        runner = make_runner(tmp_path, provider_config())
        p = "volc"
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        assert runner._provider_circuit.is_circuit_open(p, now=now)

        result = runner.run_implementer("test-spec")
        assert result.success is False
        assert "provider circuit open" in result.error
        assert p in result.error
        assert "HTTP 404" in result.error
        # 熔断拦截不计入 spec retry / 不触状态机（原 no_state_machine_touch 断言）
        assert runner._running_agents == {}

    def test_no_spawn_when_open(self, tmp_path, monkeypatch):
        """熔断期派发不得启动 claude 进程（_run_agent 不被调用）。"""
        runner = make_runner(tmp_path, provider_config())
        p = "volc"
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)

        called = {"claude": False}

        def fake_run_agent(*a, **k):
            called["claude"] = True
            raise RuntimeError("should not be called")

        monkeypatch.setattr(runner, "_run_agent", fake_run_agent)
        runner.run_implementer("test-spec")
        assert called["claude"] is False


class TestCircuitHalfOpenRecovery:
    """2.4：冷却后半开探针——200 闭合、仍 4xx 重新冷却。"""

    def test_probe_success_closes_circuit(self, tmp_path, monkeypatch):
        runner = make_runner(tmp_path, provider_config())
        p = "volc"
        cooldown = PROVIDER_CIRCUIT_COOLDOWN_SECONDS
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        assert runner._provider_circuit.is_circuit_open(p, now=now)
        # 冷却到期 → 半开；首个派发作为探针，claude 成功（200）
        probe_time = now + cooldown + 5
        monkeypatch.setattr(runner, "_now", lambda: probe_time)
        patch_runner_for_exec(runner, tmp_path, claude_side_effect=None)
        runner.run_implementer("test-spec")
        st = runner._provider_circuit.provider_circuits.get(p, {})
        assert st.get("cooldown_until", 0) == 0, st
        assert st.get("count", 0) == 0

    def test_probe_failure_recools(self, tmp_path, monkeypatch):
        runner = make_runner(tmp_path, provider_config())
        p = "volc"
        cooldown = PROVIDER_CIRCUIT_COOLDOWN_SECONDS
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        assert runner._provider_circuit.is_circuit_open(p, now=now)
        probe_time = now + cooldown + 5
        monkeypatch.setattr(runner, "_now", lambda: probe_time)

        def fake_run_agent(*a, **k):
            # add-impl-selfcheck-model-probe（2.1）：unrecognized_model 现为独立
            # 判定类（确定性拒模型 → 切链，不入 4xx 熔断计数），本测试验证的是
            # 半开探针仍 4xx → 重新冷却，夹具须用纯 404（不含 unrecognized_model）。
            raise RuntimeError("claude CLI failed: HTTP 404 model_not_found")

        patch_runner_for_exec(runner, tmp_path, claude_side_effect=fake_run_agent)
        monkeypatch.setattr("time.sleep", lambda _s: None)  # 吞掉 attempt 间退避
        runner.run_implementer("test-spec")
        st = runner._provider_circuit.provider_circuits[p]
        assert st["cooldown_until"] >= probe_time
        assert runner.is_circuit_open(p, now=probe_time)


class TestCircuitVisibility:
    """2.6：错误透出含 provider 名 / HTTP code / 次数 / 冷却信息（design D5）。

    （原 test_error_text_format 与 test_circuit_error_text_has_count_and_cooldown
    同一 _circuit_open_error 断言骨架（provider 前缀 + HTTP code x N），后者多断言
    cooldown/remaining——审查后合并，startswith 前缀断言并入保留。）
    """

    def test_circuit_error_text_has_count_and_cooldown(self, tmp_path, monkeypatch):
        runner = make_runner(tmp_path)
        p = "volc"
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        err = runner._provider_circuit._circuit_open_error(p, now=now)
        # 前缀断言（原 test_error_text_format 的 startswith 语义保留）
        assert err.startswith(f"provider circuit open: {p}")
        assert "HTTP 404 x 3" in err
        assert "cooldown" in err
        assert "remaining" in err

    def test_unassigned_provider_never_circuits(self, tmp_path):
        runner = make_runner(tmp_path)  # 无 config → 无 assignment
        assert runner.is_circuit_open(None) is False


# ═══════════════════════════════════════════════════════════════════════════
# 429 限流分类与冷却（add-code-review-concurrency-and-429-resilience D3）
# ═══════════════════════════════════════════════════════════════════════════

class TestRatelimitClassification:
    """429 限流签名分类 / 不计 4xx / 限流冷却通道。"""

    # 2026-09-24 真实错误文本 fixture（bigmodel 网关 429，spec delta Scenario）
    REAL_429_FIXTURE = (
        "API Error: Request rejected (429) · [1302]"
        "[您的账户已达到速率限制，请您控制请求频率]"
    )

    def test_real_fixture_hits_classification(self):
        """真实 429 文本命中限流分类，且纳入切换类（驱动链前进）。"""
        assert AgentRunner.classify_ratelimit_error(self.REAL_429_FIXTURE) is True
        assert AgentRunner.classify_switch_error(self.REAL_429_FIXTURE) is True

    def test_signature_forms(self):
        """三签名任一命中即分类（HTTP 429 / [1302] / rate_limit）+ 兜底 (429)。"""
        assert AgentRunner.classify_ratelimit_error("HTTP 429 Too Many Requests") is True
        assert AgentRunner.classify_ratelimit_error("gateway [1302] throttled") is True
        assert AgentRunner.classify_ratelimit_error("rate_limit_error: quota exceeded") is True
        assert AgentRunner.classify_ratelimit_error("Request rejected (429)") is True  # code 兜底
        # 非限流文本不误判
        assert AgentRunner.classify_ratelimit_error("HTTP 500 Internal Server Error") is False
        assert AgentRunner.classify_ratelimit_error("HTTP 404 not found") is False
        assert AgentRunner.classify_ratelimit_error("connection refused") is False
        assert AgentRunner.classify_ratelimit_error("") is False

    def test_429_not_counted_as_4xx(self, tmp_path, monkeypatch):
        """429 不计入 PROVIDER_CIRCUIT_4XX 熔断计数（限流走冷却通道，非熔断面）。"""
        runner = make_runner(tmp_path)
        p = "volc"
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        error, is_transient, may_switch = runner._record_4xx_or_transient(
            self.REAL_429_FIXTURE, p, "implementer", [], 1, False,
        )
        # 非瞬态（不进原地退避重试——冷却期内原地重试只会继续撞 429）、可切链
        assert is_transient is False
        assert may_switch is True
        # 零 4xx 计数（provider_circuits 无计数条目或 count 恒 0）
        st = runner._provider_circuit.provider_circuits.get(p)
        assert st is None or (st["count"] == 0 and not st["events"])
        assert not runner.is_circuit_open(p, now=now)

    def test_switch_error_includes_429_in_infra_attribution(self):
        """429 进入切换类后，verifier 失败的 infra 归因随之覆盖（task 4.3 固化）。

        「验证没能发生」语义：429 打死的 verifier 失败不得流转 bug-found。
        """
        from core.pm_engine.verification.infra_classify import _verifier_error_is_infra

        pipeline = type("P", (), {})()
        pipeline._pm = type("PM", (), {})()
        pipeline._pm.agent_runner = AgentRunner
        assert (
            _verifier_error_is_infra(pipeline, self.REAL_429_FIXTURE) is True
        )

    def test_switch_cooldown_from_attempt_uses_ratelimit_duration(self, tmp_path, monkeypatch):
        """attempt 循环 429 失败：链前进 + 冷却时长用限流常量（非 switch 配置）。"""
        from core.agent_runner import PROVIDER_RATELIMIT_COOLDOWN_SECONDS

        runner = make_runner(tmp_path, provider_config())
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_switch_cooldown(
            "volc", now=now, cooldown_seconds=PROVIDER_RATELIMIT_COOLDOWN_SECONDS,
        )
        st = runner._provider_circuit.provider_circuits["volc"]
        assert st["switch_cooldown_until"] == pytest.approx(
            now + PROVIDER_RATELIMIT_COOLDOWN_SECONDS)
        # 冷却期内链选择跳过该候选
        assert runner._provider_circuit.is_switch_cooldown("volc", now=now + 1)
        # 冷却到期探针复位：自动复位、可再次选中
        later = now + PROVIDER_RATELIMIT_COOLDOWN_SECONDS + 1
        monkeypatch.setattr(runner, "_now", lambda: later)
        assert not runner._provider_circuit.is_switch_cooldown("volc", now=later)
        assert runner.switch_cooldown_until("volc") == 0.0
