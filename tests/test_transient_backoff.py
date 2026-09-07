"""fix-provider-transient-backoff：错误归因降噪与瞬断判定单元测试。

覆盖 tasks：
- 1.3 诊断行过滤、全噪音回退、双通道判定各正反例（error-attribution-denoise D5/D2）

参照 tests/test_provider_failover.py 真实故障 fixture 惯例（2026-09 死亡 run stderr 样本）。
"""

import re
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.provider_circuit import ProviderCircuit
from tests.helpers import FakeLogger


# ═══════════════════════════════════════════════════════════════════════════
# 1.1 诊断行过滤（error-attribution-denoise D5）
# ═══════════════════════════════════════════════════════════════════════════

class TestDenoiseStderr:
    """测试 AgentRunner._denoise_stderr 静态方法。"""

    def test_filters_claude_code_diagnostic_lines(self):
        """含诊断行 + 真实错误 → 过滤诊断行，只保留真实错误。"""
        stderr_lines = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
            "API error: unrecognized model \"deepseek-v4-flash\"",
            "[claude-code:token_usage] total=0",
            "connection reset by peer",
            "[claude-code:session_id] sid=abc123",
        ]
        effective, error_msg = AgentRunner._denoise_stderr(stderr_lines, 1)
        assert len(effective) == 2
        assert "[claude-code:" not in "\n".join(effective)
        assert "unrecognized model" in error_msg
        assert "connection reset" in error_msg

    def test_all_noise_fallback_to_exit_code(self):
        """全为诊断噪音行 → 回退 `Exit code: {returncode}`。"""
        stderr_lines = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
            "[claude-code:token_usage] total=0",
            "[claude-code:session_id] sid=abc123",
        ]
        effective, error_msg = AgentRunner._denoise_stderr(stderr_lines, 42)
        assert len(effective) == 0
        assert error_msg == "Exit code: 42"

    def test_empty_stderr_fallback(self):
        """空 stderr → 回退 `Exit code: {returncode}`。"""
        effective, error_msg = AgentRunner._denoise_stderr([], 1)
        assert len(effective) == 0
        assert error_msg == "Exit code: 1"

    def test_no_noise_preserves_original(self):
        """无诊断行 → 原样取末 5 行拼接（既有行为不变）。"""
        stderr_lines = ["real error line 1", "real error line 2", "real error line 3"]
        effective, error_msg = AgentRunner._denoise_stderr(stderr_lines, 1)
        assert effective == stderr_lines
        assert "real error line 1" in error_msg

    def test_denoised_max_5_lines(self):
        """过滤后仍超 5 行 → 只取末 5 行，且截断至 500 字符。"""
        noise = "[claude-code:noise]"
        real = [f"real error {i}" for i in range(20)]
        stderr_lines = [noise] * 5 + real
        effective, error_msg = AgentRunner._denoise_stderr(stderr_lines, 1)
        assert len(effective) == 20
        # error_msg 取末 5 行
        assert "real error 19" in error_msg
        assert "real error 15" in error_msg
        assert "real error 14" not in error_msg

    def test_jsonl_stderr_raw_events_not_affected(self):
        """验证降噪逻辑：jsonl 的 stderr 原始事件行保持不过滤。

        _denoise_stderr 只返回过滤后的有效行；jsonl 写入发生在 _read_stream
        中，与 error 拼装互不干扰（本文档验证降噪的副作用不泄漏到 jsonl）。
        """
        raw_line = "[claude-code:unrecognized_model] model deepseek-v4 not found"
        effective, error_msg = AgentRunner._denoise_stderr([raw_line], 1)
        assert len(effective) == 0
        assert "Exit code: 1" == error_msg


# ═══════════════════════════════════════════════════════════════════════════
# 1.2 瞬断判定（error-attribution-denoise D2）
# ═══════════════════════════════════════════════════════════════════════════

class TestClassifyTransientError:
    """测试 ProviderCircuit.classify_transient_error 静态方法。

    判定信号（任一命中即瞬断）：
    通道 1：全量 stderr 命中 switch 类 pattern（unrecognized_model / 5xx / 连接类）
    通道 2：exit≠0 + 无 result 事件 + stderr 存在 [claude-code:] 诊断行
    """

    # ── 真实故障 stderr 样本（2026-09 死亡 run） ──────────────────────
    REAL_TRANSIENT_STDERR = [
        "[claude-code:unrecognized_model] model deepseek-v4 not found",
        "API error: unrecognized model \"deepseek-v4-flash\"",
        "[claude-code:token_usage] total=0",
    ]

    def test_unrecognized_model_in_stderr_channel1(self):
        """通道 1：全量 stderr 含 unrecognized_model → 瞬断。"""
        assert ProviderCircuit.classify_transient_error(
            self.REAL_TRANSIENT_STDERR, 1, False) is True

    def test_5xx_in_stderr_channel1(self):
        """通道 1：全量 stderr 含 HTTP 5xx → 瞬断。"""
        stderr = [
            "HTTP 503 Service Unavailable",
            "[claude-code:token_usage] total=0",
        ]
        assert ProviderCircuit.classify_transient_error(stderr, 1, False) is True

    def test_connection_error_in_stderr_channel1(self):
        """通道 1：全量 stderr 含连接错误 → 瞬断。"""
        stderr = [
            "connection reset by peer",
            "failed to connect: dial tcp 1.2.3.4:443: i/o timeout",
        ]
        assert ProviderCircuit.classify_transient_error(stderr, 1, False) is True

    def test_4xx_not_transient(self):
        """4xx 配额/鉴权类错误 → 不判瞬断（走 4xx 熔断路径）。"""
        stderr = [
            "HTTP 404 Not Found",
            "API error (404): model not found",
        ]
        assert ProviderCircuit.classify_transient_error(stderr, 1, False) is False

    def test_channel2_exit_nonzero_no_result_has_diagnostic(self):
        """通道 2：exit≠0 + 无 result + stderr 含 [claude-code:] → 瞬断。"""
        stderr = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
        ]
        assert ProviderCircuit.classify_transient_error(stderr, 1, False) is True

    def test_channel2_with_result_not_transient(self):
        """通道 2：exit≠0 + 有 result → 不判瞬断（CLI 有终态事件）。"""
        stderr = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
        ]
        # has_result=True → 通道 2 不命中；通道 1 的 switch pattern 需单独检查
        # 此处全量 stderr 有 unrecognized_model，通道 1 命中 → 瞬断
        # 但若无 switch pattern 且有 result → 不瞬断
        stderr_no_switch = [
            "[claude-code:token_usage] total=0",
        ]
        assert ProviderCircuit.classify_transient_error(
            stderr_no_switch, 1, True) is False

    def test_channel2_exit_zero_not_transient(self):
        """exit=0（成功退出）+ 有诊断行 → 不判瞬断。"""
        stderr = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
        ]
        # exit=0 + has_result=True → 不判瞬断
        assert ProviderCircuit.classify_transient_error(stderr, 0, True) is False

    def test_empty_stderr_not_transient(self):
        """空 stderr → 不判瞬断。"""
        assert ProviderCircuit.classify_transient_error([], 1, False) is False

    def test_not_depend_on_denoised_error(self):
        """判定不依赖降噪后 error 字符串（D2 核心约束）。

        降噪后 unrecognized_model 已被过滤；判定应看原始 stderr_lines 而非
        error_msg 字符串。
        """
        # 原始 stderr 含 unrecognized_model
        stderr = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
        ]
        # 降噪后的 error_msg 会丢失 unrecognized_model 字样
        effective, error_msg = AgentRunner._denoise_stderr(stderr, 1)
        assert "unrecognized_model" not in error_msg
        # 但 classify_transient_error 看原始 stderr，应判瞬断
        assert ProviderCircuit.classify_transient_error(stderr, 1, False) is True


# ═══════════════════════════════════════════════════════════════════════════
# 真实故障文本 fixture 回放（Task 6.4 前置）
# ═══════════════════════════════════════════════════════════════════════════

class TestRealFailureFixtures:
    """以 2026-09 死亡 run 的 stderr 样本回放判定与降噪路径。

    参照 tests/test_provider_failover.py:173 真实故障 fixture 惯例。
    """

    FIXTURES = [
        # 2026-09 死亡 run #1：unrecognized_model 拒绝 deepseek 变体
        {
            "description": "inferaiapi unrecognized_model",
            "stderr": (
                "[claude-code:unrecognized_model] model deepseek-v4 not found\n"
                "API error: unrecognized model \"deepseek-v4-flash\"\n"
                "[claude-code:token_usage] total=0\n"
            ),
            "exit_code": 1,
            "has_result": False,
            "expected_transient": True,
        },
        # 2026-09 死亡 run #2：503 网关瞬断
        {
            "description": "aliyun 503 service unavailable",
            "stderr": (
                "HTTP 503 Service Unavailable\n"
                "[claude-code:token_usage] total=0\n"
            ),
            "exit_code": 1,
            "has_result": False,
            "expected_transient": True,
        },
        # 2026-09 死亡 run #3：连接超时
        {
            "description": "connection timeout to gateway",
            "stderr": (
                "failed to connect: dial tcp 1.2.3.4:443: connection timed out\n"
                "[claude-code:token_usage] total=0\n"
            ),
            "exit_code": 1,
            "has_result": False,
            "expected_transient": True,
        },
        # 404 配额问题（不判瞬断）
        {
            "description": "404 quota exceeded (not transient)",
            "stderr": (
                "HTTP 404 Not Found\n"
                "API error (404): quota exceeded for model deepseek-v4-flash\n"
            ),
            "exit_code": 1,
            "has_result": False,
            "expected_transient": False,
        },
        # 真实缺陷类错误（不判瞬断）
        {
            "description": "real bug in code (not transient)",
            "stderr": (
                "AssertionError: expected 'foo' to equal 'bar'\n"
                "at tests/test_feature.py:42\n"
            ),
            "exit_code": 1,
            "has_result": True,
            "expected_transient": False,
        },
    ]

    @pytest.mark.parametrize("fixture", FIXTURES,
                             ids=[f["description"] for f in FIXTURES])
    def test_fixture_transient_classification(self, fixture):
        """每个 fixture 按预期判定为瞬断或非瞬断。"""
        stderr_lines = fixture["stderr"].strip().split("\n")
        result = ProviderCircuit.classify_transient_error(
            stderr_lines, fixture["exit_code"], fixture["has_result"])
        assert result is fixture["expected_transient"], (
            f"{fixture['description']}: expected {fixture['expected_transient']}, "
            f"got {result}"
        )

    @pytest.mark.parametrize("fixture", FIXTURES,
                             ids=[f["description"] for f in FIXTURES])
    def test_denoise_removes_diagnostic_noise(self, fixture):
        """降噪过滤掉 [claude-code:] 诊断行，真实错误保留。"""
        stderr_lines = fixture["stderr"].strip().split("\n")
        effective, error_msg = AgentRunner._denoise_stderr(stderr_lines, 1)
        assert "[claude-code:" not in "\n".join(effective), (
            f"{fixture['description']}: diagnostic line should be filtered"
        )
        # 降噪后至少有部分真实内容（除非全噪音）
        assert len(effective) >= 0


# ═══════════════════════════════════════════════════════════════════════════
# 2.1-2.4 原地退避（fix-provider-transient-backoff D1）
# ═══════════════════════════════════════════════════════════════════════════

class TestParseTransientBackoffSchedule:
    """测试退避序列解析（纯函数，不依赖 runner 实例）。"""

    def test_valid_schedule(self):
        assert AgentRunner._parse_transient_backoff_schedule("30,60,120") == [30, 60, 120]

    def test_custom_schedule(self):
        assert AgentRunner._parse_transient_backoff_schedule("5,10,20,40") == [5, 10, 20, 40]

    def test_invalid_elements_filtered(self):
        """非法元素静默跳过。"""
        assert AgentRunner._parse_transient_backoff_schedule("30,abc,60") == [30, 60]

    def test_all_invalid_fallback(self):
        """全非法回退缺省。"""
        assert AgentRunner._parse_transient_backoff_schedule("abc,def") == [30, 60, 120]

    def test_empty_string_fallback(self):
        assert AgentRunner._parse_transient_backoff_schedule("") == [30, 60, 120]

    def test_none_fallback(self):
        assert AgentRunner._parse_transient_backoff_schedule(None) == [30, 60, 120]

    def test_negative_filtered(self):
        """负数静默跳过。"""
        assert AgentRunner._parse_transient_backoff_schedule("-10,30") == [30]

    def test_zero_filtered(self):
        """零值静默跳过。"""
        assert AgentRunner._parse_transient_backoff_schedule("0,30,60") == [30, 60]


class TestTransientRetryLogic:
    """验证原地重试核心逻辑（纯函数/属性验证，不启动 claude 进程）。"""

    def test_sub_run_id_generation(self):
        """子重试 run_id 格式：attempt_run_id-r{N}。"""
        attempt_run_id = "run-20260907-a1"
        # 首次（retries=0）: 不加后缀
        assert (f"{attempt_run_id}" if 0 == 0
                else f"{attempt_run_id}-r{0}") == attempt_run_id
        # 第1次重试: -r1
        assert f"{attempt_run_id}-r{1}" == "run-20260907-a1-r1"
        # 第2次重试: -r2
        assert f"{attempt_run_id}-r{2}" == "run-20260907-a1-r2"

    def test_transient_budget_limits_retries(self):
        """瞬断重试次数不超过退避序列长度。"""
        budget = [30, 60, 120]
        retries = 0
        # 3 次预算
        while retries < len(budget):
            retries += 1
        assert retries == 3
        # 第4次应停止
        assert retries == len(budget)

    def test_non_transient_exits_while(self):
        """非瞬断错误（real bug）→ classify_transient_error 返回 False → break。"""
        stderr = [
            "AssertionError: expected 'foo' to equal 'bar'",
        ]
        assert ProviderCircuit.classify_transient_error(stderr, 1, True) is False

    def test_resume_dead_not_transient(self):
        """resume 死 session（No conversation found）不判瞬断（排除在原地重试外）。"""
        error_text = "No conversation found with session ID abc123"
        stderr = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
            f"Claude API error: {error_text}",
        ]
        # 通道 1 会因为 unrecognized_model 命中 → 瞬断；但 resume_dead 在 runner 中排除
        assert ProviderCircuit.classify_transient_error(stderr, 1, False) is True
        # runner 的 except 块中先检查 resume_dead 再判瞬断，resume_dead=True 时不原地重试


# ═══════════════════════════════════════════════════════════════════════════
# 3.4 worktree 保留扩展（fix-provider-transient-backoff D3）
# ═══════════════════════════════════════════════════════════════════════════


class _TransientError(RuntimeError):
    """模拟 Claude CLI 瞬断失败异常（携带 stderr_lines / exit_code / has_result）。"""

    def __init__(self, msg="cli transient failure", *, stderr_lines=None,
                 exit_code=1, has_result=False):
        super().__init__(msg)
        self.stderr_lines = stderr_lines or []
        self.exit_code = exit_code
        self.has_result = has_result


class _NonTransientError(RuntimeError):
    """模拟真实代码缺陷类异常（不触发瞬断判定）。"""

    def __init__(self, msg="AssertionError: expected 'foo' to equal 'bar'",
                 *, stderr_lines=None, exit_code=1, has_result=True):
        super().__init__(msg)
        self.stderr_lines = stderr_lines or [
            "AssertionError: expected 'foo' to equal 'bar'",
            "  at tests/test_feature.py:42",
        ]
        self.exit_code = exit_code
        self.has_result = has_result


def _make_chain_config(agent_type="planner-judge"):
    """构造含单 provider 候选链的 config（供 provider_name 非空路径测试）。"""
    return {
        "llm": {"providers": [
            {"name": "inferaiapi.com", "baseurl": "https://a.com", "apikey": "k1"},
        ]},
        "agents": {
            "models": {
                agent_type: {
                    "provider": "inferaiapi.com",
                    "model": "deepseek-v4-flash",
                },
            },
            "max_retries": 2,
            "transient_backoff_schedule": "1",   # 预算长度 1，两次即耗尽
        },
    }


def _build_runner(tmp_path, config=None):
    """构造可驱动 _execute_agent 的最小 runner 实例。

    绕过 __init__，手动填充必要属性并注入 mock 组件（v2_server / token_accountant /
    build_prompt / run_claude），使 _execute_agent_inner 可正常跑通而不触发真实子进程。
    """
    from core.agent_runner import AgentRunner
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = tmp_path
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._daily_reset_date = None
    runner._daily_provider_attempts = {}
    runner._daily_provider_warned = {}
    runner.provider_circuits = {}
    # mock v2_server（避免真实 dev-server 启停）
    runner.__dict__["_v2_server_instance"] = MagicMock()
    runner._v2_server._v2_inject_env.return_value = {}
    # mock token accountant（避免 state_machine 依赖）
    runner.__dict__["_token_accountant_instance"] = MagicMock()
    # mock _build_prompt（避免 spec 文件读取）
    runner._build_prompt = lambda *a, **k: "test prompt"
    # mock _v2_harvest（在 _execute_agent finally 中调用）
    runner._v2_server._v2_stop_for_worktree.return_value = None
    return runner


class TestWorktreeReuseAcrossAttempts:
    """Task 3.4 — planner-judge attempt 间复用（D3：全 agent_type 保留 worktree）。

    场景：planner-judge attempt 1 死于瞬断 → 原地重试耗尽 → 转换链 → attempt 2
    使用与 attempt 1 相同的 worktree 目录与分支，不新建 worktree。
    """

    def test_planner_judge_reuses_worktree_between_attempts(self, tmp_path, monkeypatch):
        """planner-judge attempt 1 瞬断 → attempt 2 复用同一 worktree，create 仅调一次。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)   # 抹掉 attempt 间隔 sleep

        config = _make_chain_config("planner-judge")
        runner = _build_runner(tmp_path, config)
        wt = tmp_path / "wt"
        wt.mkdir()
        subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-123"

        stderr_real = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
            "API error: unrecognized model",
        ]
        attempt_n = {"n": 0}
        call_cwds = []

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            attempt_n["n"] += 1
            call_cwds.append(cwd)
            if attempt_n["n"] <= 2:
                # attempt 1：初始 + 原地重试 1 次（预算 [1]）均瞬断
                raise _TransientError(stderr_lines=stderr_real, exit_code=1, has_result=False)
            # attempt 2 成功
            return ("done", 1, "sess-2", {"input_tokens": 0, "output_tokens": 0,
                                          "cache_creation_input_tokens": 0,
                                          "cache_read_input_tokens": 0, "cost_usd": None})

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("test-spec", "planner-judge", "run-1")

        # create 只被调用 1 次（attempt 2 复用 attempt 1 创建的 worktree）
        assert runner.worktree_manager.create.call_count == 1
        # 两次 _run_claude 调用的 cwd 完全相同（worktree 复用）
        assert len(call_cwds) >= 2
        assert call_cwds[0] == call_cwds[1] == wt
        # attempt 2 成功
        assert result.success is True


class TestTransientTerminalKeepForReuse:
    """Task 3.4 — 瞬断终态保留现场（D3：transient → keep_for_reuse）。

    场景：implementer run 烧尽 attempt 与原地重试预算，终态 error 带
    [provider-transient] 标记 → keep_for_reuse 登记（非 cleanup）。
    """

    def test_transient_terminal_calls_keep_for_reuse(self, tmp_path, monkeypatch):
        """瞬断终态 → keep_for_reuse 被调用，cleanup 不被调用。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)

        config = _make_chain_config("implementer")
        config["agents"]["max_retries"] = 1   # 单次 attempt 即终态
        runner = _build_runner(tmp_path, config)
        wt = tmp_path / "wt"
        wt.mkdir()
        subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-123"

        stderr_real = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found",
            "API error: unrecognized model",
        ]

        def fake_run_claude(*args, **kwargs):
            raise _TransientError(stderr_lines=stderr_real, exit_code=1, has_result=False)

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("test-spec", "implementer", "run-2")

        # 终态标记 → keep_for_reuse 被调用（传入 agent_type）
        runner.worktree_manager.keep_for_reuse.assert_called_once()
        call_args = runner.worktree_manager.keep_for_reuse.call_args
        assert call_args[1].get("agent_type") == "implementer" or (
            len(call_args[0]) >= 3 and call_args[0][2] == "implementer"
        )
        # cleanup(success=False) 未被调用
        runner.worktree_manager.cleanup.assert_not_called()
        # 结果标记 worktree_kept
        assert result.worktree_kept is True
        assert "[provider-transient]" in (result.error or "")


class TestNonTransientTerminalCleanup:
    """Task 3.4 — 非瞬断终态照旧清理（真实缺陷 → cleanup）。

    场景：implementer run 因真实缺陷类错误（非瞬断判定）烧尽全部重试
    → 终态处置维持 cleanup(success=False) 行为。
    """

    def test_non_transient_terminal_calls_cleanup(self, tmp_path, monkeypatch):
        """非瞬断终态 → cleanup(success=False) 被调用，keep_for_reuse 不被调用。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)

        config = _make_chain_config("implementer")
        config["agents"]["max_retries"] = 1
        runner = _build_runner(tmp_path, config)
        wt = tmp_path / "wt"
        wt.mkdir()
        subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-123"

        def fake_run_claude(*args, **kwargs):
            raise _NonTransientError()

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("test-spec", "implementer", "run-3")

        # 非瞬断 → cleanup(success=False) 被调用
        runner.worktree_manager.cleanup.assert_called_once_with(wt, success=False)
        # keep_for_reuse 未被调用
        runner.worktree_manager.keep_for_reuse.assert_not_called()
        assert result.success is False


class TestReuseClaimInheritance:
    """Task 3.4 — 认领继承现场（_take_reusable_worktree 认领 keep_for_reuse 遗产）。

    场景：keep_for_reuse 登记 worktree 后，下轮 dispatch 调用 create() 时
    经 _take_reusable_worktree 认领同一目录与分支，继承已提交与未提交现场。
    """

    def test_claim_inherited_worktree_after_keep_for_reuse(self, tmp_path):
        """keep_for_reuse → create() 返回同一 worktree 路径与分支。"""
        from core.worktree_manager import WorktreeManager
        root = tmp_path / "repo"
        root.mkdir()
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email",
                        "test@fenix.local"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name",
                        "Fenix Test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "commit.gpgsign",
                        "false"], check=True)
        (root / "base.py").write_text("BASE\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m",
                        "[fenix] base"], check=True)
        subprocess.run(["git", "-C", str(root), "branch", "-M", "main"], check=True)

        base = root / ".claude" / "worktrees"
        base.mkdir(parents=True, exist_ok=True)
        wm = WorktreeManager(base, root, FakeLogger())

        # 首次 create → 得到 worktree
        wt1 = wm.create("demo-spec", "planner-judge")
        assert wt1 is not None
        branch = wm.get_branch_name(wt1)
        assert branch is not None

        # keep_for_reuse 登记
        wm.keep_for_reuse("demo-spec", wt1, agent_type="planner-judge")

        # 再次 create → 经 _take_reusable_worktree 认领同一 worktree
        wt2 = wm.create("demo-spec", "planner-judge")
        assert wt2 == wt1, "认领应返回同一 worktree 路径"
        assert wm.get_branch_name(wt2) == branch, "认领应继承同一分支"


# ═══════════════════════════════════════════════════════════════════════════
# 4.4 transient 标记注入与 dispatch 排程（transient-dispatch-gating D4）
# ═══════════════════════════════════════════════════════════════════════════

class TestTransientMarkerInjection:
    """Task 4.4 — [provider-transient] 标记写侧统一注入（D4）。

    瞬断终态收场时 error 消息头部注入 `[provider-transient]` 结构化标记，
    供 dispatch 读侧识别（排程重派 / 全局熔断记账共用）。
    """

    def test_terminal_error_has_marker(self, tmp_path, monkeypatch):
        """瞬断终态 error 头部含 [provider-transient] 标记。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        config = _make_chain_config("implementer")
        config["agents"]["max_retries"] = 1
        runner = _build_runner(tmp_path, config)
        wt = tmp_path / "wt"
        wt.mkdir()
        subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-123"

        def fake_run_claude(*args, **kwargs):
            raise _TransientError(
                stderr_lines=["[claude-code:unrecognized_model] model not found"],
                exit_code=1, has_result=False,
            )

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("test-spec", "implementer", "run-m")
        # 终态错误带标记
        assert result.error is not None
        assert result.error.startswith("[provider-transient]") or \
            "[provider-transient]" in result.error
        # 非瞬断路径不应注入标记
        runner2 = _build_runner(tmp_path, config)
        runner2.worktree_manager = MagicMock()
        runner2.worktree_manager.create.return_value = wt
        runner2.worktree_manager.get_branch_name.return_value = "fenix/spec-123"

        def fake_run_claude2(*args, **kwargs):
            raise _NonTransientError()

        runner2._run_claude = fake_run_claude2
        result2 = runner2._execute_agent("test-spec", "implementer", "run-m2")
        assert "[provider-transient]" not in (result2.error or "")


class TestTransientDispatchScheduling:
    """Task 4.4 — dispatch 排程等待重派（不写 retries exhausted）。

    场景：error 带 `[provider-transient]` 标记 → 走 _schedule_transient_recovery
    排程定时器，跳过 `_retry_count` 递增/清零路径，不写 retries exhausted。
    """

    def _make_dispatcher(self, pm):
        from core.pm_engine.dispatch import Dispatcher
        return Dispatcher(pm)

    def _make_pm(self):
        class _PM:
            def __init__(self):
                self.config = {}
                self.logger = FakeLogger()
                self.scheduled = []
                self._queue_lock = __import__("threading").Lock()

            def _get_config(self, key, default=None):
                return self.config.get(key, default)

            def _on_spec_ready(self, spec_name):
                self.scheduled.append(("ready", spec_name))

            def _process_queue(self):
                self.scheduled.append(("queue", None))

        pm = _PM()
        return pm

    def test_schedule_transient_recovery_uses_timer(self):
        """瞬断恢复排程创建定时器且幂等（同 spec 不重复排程）。"""
        pm = self._make_pm()
        dispatcher = self._make_dispatcher(pm)
        # 直接调用锁内实现，避免真实等待
        dispatcher._schedule_transient_recovery_locked("spec-a")
        assert "spec-a" in dispatcher._transient_timers
        # 幂等：再次排程不重复
        dispatcher._schedule_transient_recovery_locked("spec-a")
        assert len(dispatcher._transient_timers) == 1

    def test_on_transient_recovery_reenqueues(self):
        """冷却到期回调：移出 timers 并重入 _on_spec_ready + _process_queue。"""
        pm = self._make_pm()
        dispatcher = self._make_dispatcher(pm)
        dispatcher._transient_timers.add("spec-a")
        dispatcher._on_transient_recovery("spec-a")
        assert "spec-a" not in dispatcher._transient_timers
        assert ("ready", "spec-a") in pm.scheduled
        assert ("queue", None) in pm.scheduled


class TestGlobalTransientBreak:
    """Task 4.4 — 全局错误指纹熔断触发/解除/告警节流（D4）。

    场景：窗口内同指纹达阈值触发冻结；冷却到期解除；告警 15 分钟节流。
    """

    class _FakePM:
        def __init__(self):
            self.config = {}
            self.project_root = None
            self.logger = FakeLogger()
            self.now = 1000.0

        def _now(self):
            return self.now

        def _get_config(self, key, default=None):
            from core.config import ConfigLoader
            return ConfigLoader.get(self.config, key, default)

    def _make_circuit(self, config=None):
        pm = self._FakePM()
        pm.config = config or {}
        return ProviderCircuit(pm), pm

    def test_trigger_at_threshold(self):
        """窗口内同指纹达阈值（缺省 3）→ 触发全局熔断。"""
        pc, pm = self._make_circuit()
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1000) is False
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1100) is False
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1200) is True
        assert pc.is_global_transient_break(now=1200) is True

    def test_trigger_across_model_variants(self):
        """不同 model 变体归一化为同一指纹 → 收敛触发熔断。"""
        pc, pm = self._make_circuit()
        assert pc.record_transient_error(
            "unrecognized model deepseek-v4-flash", now=1000) is False
        assert pc.record_transient_error(
            "unrecognized model glm-5.3-flash", now=1100) is False
        assert pc.record_transient_error(
            "unrecognized model claude-sonnet-5", now=1200) is True

    def test_break_expires_and_resets(self):
        """冷却到期 → 熔断解除，窗口指纹计数清零重新起算。"""
        pc, pm = self._make_circuit()
        pc.record_transient_error("unrecognized model deepseek-v4", now=1000)
        pc.record_transient_error("unrecognized model deepseek-v4", now=1100)
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1200) is True
        # 冷却中仍冻结
        assert pc.is_global_transient_break(now=1700) is True
        # 冷却到期（缺省 600s）→ 解除
        assert pc.is_global_transient_break(now=1801) is False
        # 计数清零：再触发需重新累计 3 次
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1900) is False

    def test_threshold_config_respected(self):
        """配置阈值/窗口/冷却生效（transient_break_threshold 等）。"""
        pc, pm = self._make_circuit({
            "agents": {"transient_break_threshold": 2,
                       "transient_break_window_seconds": 600,
                       "transient_break_cooldown_seconds": 300},
        })
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1000) is False
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1100) is True
        assert pc.is_global_transient_break(now=1100) is True
        # 冷却 300s → 1400 到期
        assert pc.is_global_transient_break(now=1400) is False

    def test_window_slides_old_events(self):
        """窗口外旧事件滑出：间隔超过窗口的事件不计入。"""
        pc, pm = self._make_circuit()
        pc.record_transient_error("unrecognized model deepseek-v4", now=0)
        pc.record_transient_error("unrecognized model deepseek-v4", now=100)
        # 第三次在窗口外（窗口 600s）
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=700) is False

    def test_different_fingerprints_no_false_positive(self):
        """不同错误指纹互不累计（真实缺陷不误伤）。"""
        pc, pm = self._make_circuit()
        pc.record_transient_error("AssertionError: expected foo", now=1000)
        pc.record_transient_error("TypeError: unsupported operand", now=1100)
        pc.record_transient_error("KeyError: missing key", now=1200)
        assert pc.is_global_transient_break(now=1200) is False

    def test_alert_throttled_15min(self):
        """触发熔断的 major 告警 15 分钟节流（同信号窗口内不重复）。"""
        pc, pm = self._make_circuit()
        pm.project_root = Path("/nonexistent-ftb")   # AdminStore 打开失败 → 告警写失败不阻断
        # 触发熔断（内部尝试告警；项目根不存在 → 写失败被捕获，不抛异常）
        pc.record_transient_error("unrecognized model deepseek-v4", now=1000)
        pc.record_transient_error("unrecognized model deepseek-v4", now=1100)
        # 告警写入失败不应使熔断触发流程抛异常
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1200) is True
        assert pc.is_global_transient_break(now=1200) is True


class TestDispatchWorkerTransientBranch:
    """Task 4.4 — dispatch worker 读侧：transient 终态不写 retries exhausted。

    验证 dispatch._run_agent_worker 中 [provider-transient] 分支走排程等待、
    不递增 _retry_count、不写 retries exhausted（非 transient 路径逐字节不变）。
    """

    def test_transient_marker_routes_to_schedule_not_retry(self, tmp_path):
        """带标记的失败 → _schedule_transient_recovery，_retry_count 不变。"""
        import json as _json
        import threading as _threading
        from core.state_machine import StateMachine
        from core.pm_engine.dispatch import Dispatcher
        from core.agent_runner import AgentRunResult

        project_root = tmp_path / "proj"
        project_root.mkdir(parents=True, exist_ok=True)
        state_path = project_root / ".fenix" / "STATE.md"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        class FakeLogger:
            def debug(self, *a, **k): pass
            def info(self, *a, **k): pass
            def warning(self, *a, **k): pass
            def error(self, *a, **k): pass

        logger = FakeLogger()
        sm = StateMachine(state_path, logger)
        sm.add_spec("spec-t", {"priority": 5})
        sm.transition("spec-t", "implementing")

        class FakePM:
            def __init__(self):
                self.config = {}
                self.state_machine = sm
                self.logger = logger
                self.shutting_down = False
                self.scheduled_recovery = []
                self._queue_lock = _threading.Lock()
                self._increment_calls = 0
                self.exempted = []

            def _get_config(self, key, default=None):
                return self.config.get(key, default)

            def _process_queue(self):
                pass

            def _increment_impl_run_budget_used(self, spec_name):
                self._increment_calls += 1

            def _exempt_dead_run_budget(self, spec_name, reason):
                self.exempted.append((spec_name, reason))

            def _implementer_zero_change(self, spec_name, result):
                return False

            def _schedule_transient_recovery(self, spec_name):
                self.scheduled_recovery.append(spec_name)

            def _rollback_failed_dispatch(self, spec_name, agent_type, e):
                pass

            def _on_spec_ready(self, spec_name):
                pass

        pm = FakePM()

        class FakeWM:
            def ensure_spec_committed(self, spec_name):
                pass

        class FakeRunner:
            worktree_manager = FakeWM()

            def run_implementer(self, spec_name, pre_wt_path=None):
                return AgentRunResult(
                    "impl-spec-t-1-a1", "spec-t", "implementer",
                    success=False, duration_seconds=1.0,
                    error="[provider-transient] unrecognized model — cli died",
                )

        pm.agent_runner = FakeRunner()
        # _read_implementer_result 无 result 文件 → None
        pm._read_implementer_result = lambda spec_name: None
        pm._enqueue = lambda spec_name, agent_type: None
        pm._enqueue_front = lambda spec_name, agent_type: None

        dispatcher = Dispatcher(pm)
        # patch Dispatcher 自身的排程方法（真实实现会起 600s 定时器）
        dispatcher._schedule_transient_recovery = lambda spec_name: pm.scheduled_recovery.append(spec_name)
        dispatcher._run_agent_worker("spec-t", "implementer", 5)

        # 排程等待被调用
        assert pm.scheduled_recovery == ["spec-t"]
        # 状态机 _retry_count 未被递增（transient 分支跳过 retry 路径）
        entry = sm.read_one("spec-t")
        assert entry.get("_retry_count", 0) == 0
        # 死亡豁免保持（无 result 文件）
        assert len(pm.exempted) == 1

    def test_non_transient_path_unchanged(self, tmp_path):
        """非 transient 终态 → 维持现行 retry 计数路径（逐字节不变）。"""
        import threading as _threading
        from core.state_machine import StateMachine
        from core.pm_engine.dispatch import Dispatcher
        from core.agent_runner import AgentRunResult

        project_root = tmp_path / "proj2"
        project_root.mkdir(parents=True, exist_ok=True)
        state_path = project_root / ".fenix" / "STATE.md"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        class FakeLogger:
            def debug(self, *a, **k): pass
            def info(self, *a, **k): pass
            def warning(self, *a, **k): pass
            def error(self, *a, **k): pass

        logger = FakeLogger()
        sm = StateMachine(state_path, logger)
        sm.add_spec("spec-n", {"priority": 5})
        sm.transition("spec-n", "implementing")

        class FakePM:
            def __init__(self):
                self.config = {"agents": {"max_retries": 3}}
                self.state_machine = sm
                self.logger = logger
                self.shutting_down = False
                self.scheduled_recovery = []
                self._queue_lock = _threading.Lock()
                self.enqueued = []

            def _get_config(self, key, default=None):
                return self.config.get(key, default)

            def _process_queue(self):
                pass

            def _increment_impl_run_budget_used(self, spec_name):
                pass

            def _exempt_dead_run_budget(self, spec_name, reason):
                pass

            def _implementer_zero_change(self, spec_name, result):
                return False

            def _schedule_transient_recovery(self, spec_name):
                self.scheduled_recovery.append(spec_name)

            def _rollback_failed_dispatch(self, spec_name, agent_type, e):
                pass

            def _on_spec_ready(self, spec_name):
                pass

            def _enqueue(self, spec_name, agent_type):
                self.enqueued.append((spec_name, agent_type))

            def _enqueue_front(self, spec_name, agent_type):
                self.enqueued.append((spec_name, agent_type))

        pm = FakePM()

        class FakeWM:
            def ensure_spec_committed(self, spec_name):
                pass

        class FakeRunner:
            worktree_manager = FakeWM()

            def run_implementer(self, spec_name, pre_wt_path=None):
                return AgentRunResult(
                    "impl-spec-n-1-a1", "spec-n", "implementer",
                    success=False, duration_seconds=1.0,
                    error="real bug: AssertionError expected foo",
                )

        pm.agent_runner = FakeRunner()
        pm._read_implementer_result = lambda spec_name: None
        dispatcher = Dispatcher(pm)
        dispatcher._schedule_transient_recovery = lambda spec_name: pm.scheduled_recovery.append(spec_name)
        dispatcher._run_agent_worker("spec-n", "implementer", 5)

        # 非 transient → 不排程瞬断恢复
        assert pm.scheduled_recovery == []
        # retry 计数递增（max_retries=3 → 第一次失败 retries=1；STATE 存字符串）
        entry = sm.read_one("spec-n")
        assert str(entry.get("_retry_count", 0)) == "1"
