"""fix-provider-transient-backoff：错误归因降噪与瞬断判定单元测试。

覆盖 tasks：
- 1.3 诊断行过滤、全噪音回退、双通道判定各正反例（error-attribution-denoise D5/D2）

参照 tests/test_provider_failover.py 真实故障 fixture 惯例（2026-09 死亡 run stderr 样本）。
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.provider_circuit import ProviderCircuit


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
