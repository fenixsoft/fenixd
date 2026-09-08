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
    """给 runner 装上可跑 _execute_agent 的 worktree_manager / _run_claude mock。"""
    wm = MagicMock()
    wm.create.return_value = proot / "wt"
    runner.worktree_manager = wm
    if claude_side_effect is not None:
        runner._run_claude = MagicMock(side_effect=claude_side_effect)
    else:
        runner._run_claude = MagicMock(return_value=("ok", 1, "sess-1", {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "cost_usd": None}))


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
        """熔断期派发不得启动 claude 进程（_run_claude 不被调用）。"""
        runner = make_runner(tmp_path, provider_config())
        p = "volc"
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)
        runner._provider_circuit._record_provider_4xx(p, 404, now=now)

        called = {"claude": False}

        def fake_run_claude(*a, **k):
            called["claude"] = True
            raise RuntimeError("should not be called")

        monkeypatch.setattr(runner, "_run_claude", fake_run_claude)
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

        def fake_run_claude(*a, **k):
            raise RuntimeError("claude CLI failed: HTTP 404 unrecognized_model")

        patch_runner_for_exec(runner, tmp_path, claude_side_effect=fake_run_claude)
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
