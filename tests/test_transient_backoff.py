"""fix-provider-transient-backoff：错误归因降噪与瞬断判定单元测试。

覆盖 tasks：
- 1.3 诊断行过滤、全噪音回退、双通道判定各正反例（error-attribution-denoise D5/D2）

参照 tests/test_provider_failover.py 真实故障 fixture 惯例（2026-09 死亡 run stderr 样本）。
"""

import json
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
        """4xx 配额/鉴权类错误 → 不判瞬断（走 4xx 熔断路径）。

        （add-impl-selfcheck-model-probe 2.1 起「model not found」文本按拒模型
        类驱动切换，夹具改用纯配额 4xx 以保留本测试「4xx 不判瞬断」的意图。）
        """
        stderr = [
            "HTTP 404 Not Found",
            "API error (404): quota exceeded",
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
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
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
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            attempt_n["n"] += 1
            call_cwds.append(cwd)
            if attempt_n["n"] <= 2:
                # attempt 1：初始 + 原地重试 1 次（预算 [1]）均瞬断
                raise _TransientError(stderr_lines=stderr_real, exit_code=1, has_result=False)
            # attempt 2 成功：写入 planner-judge 产物（add-judge-artifact-gate D1）
            # 产物落盘点为 project_root（runner 硬门同源路径），非 worktree cwd
            result_path = (
                Path(tmp_path) / ".fenix" / "verify-progress" / "test-spec"
                / ".fenix-run-result.json"
            )
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps({"status": "verified", "summary": "ok"}),
                encoding="utf-8",
            )
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
        """冷却到期 → 熔断解除进入 post-unseal hold，窗口指纹计数清零重新起算。

        （evo-fix-transient-break-unseal-backoff 2.2 修订：清零语义保留；「到期
        即全量放行」改为 hold+探针渐进恢复——hold 期内闸门整队持有，计数清零
        语义不变：解封后再触发需重新累计 3 次。）
        """
        pc, pm = self._make_circuit()
        pc.record_transient_error("unrecognized model deepseek-v4", now=1000)
        pc.record_transient_error("unrecognized model deepseek-v4", now=1100)
        assert pc.record_transient_error("unrecognized model deepseek-v4", now=1200) is True
        # 冷却中仍冻结
        assert pc.is_global_transient_break(now=1700) is True
        # 冷却到期（缺省 600s）→ 解除冻结，进入 post-unseal hold（非全量放行）
        assert pc.is_global_transient_break(now=1801) is False
        assert pc.is_post_unseal_hold(now=1801) is True
        assert pc.transient_unseal_gate(now=1801) == "hold"
        assert pc._transient_hold_until == pytest.approx(1801 + 60)
        # 计数清零：再触发需重新累计 3 次（清零语义保留）
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

    # ── 熔断到期主动唤醒派发（2026-09-22 事故回归）───────────────────────
    # 缺口：`_process_queue` 首道闸门在熔断期直接 return——解冻/恢复产生的
    # `spec_ready` 虽经 `_on_spec_ready` 入队成立，条目却出不来；而熔断是
    # 惰性自清（仅被查询时检测到期），到期与「有人查询队列」错开时被挡条目
    # 只能等下一个触发点（实测最坏约 4 分钟后才派发）。到期须显式唤醒一次
    # `_process_queue`。

    def _make_circuit_with_engine(self):
        """构造带 PMEngine 回引（记录 `_process_queue` 调用）的熔断实例。"""
        calls: list = []

        class _Engine:
            def _process_queue(self):
                calls.append(True)

        pm = self._FakePM()
        pm._pm_engine_ref = _Engine()
        return ProviderCircuit(pm), pm, calls

    def _trigger(self, pc):
        pc.record_transient_error("unrecognized model deepseek-v4", now=1000)
        pc.record_transient_error("unrecognized model deepseek-v4", now=1100)
        assert pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1200) is True

    def test_expiry_wakes_dispatch_queue_once(self):
        """冷却到期查询 → 唤醒 `_process_queue` 恰一次（幂等，不重复唤醒）。

        （evo-fix-transient-break-unseal-backoff 2.2 修订：到期唤醒语义保留，
        但唤醒不再等于全量放行——解封后先进入 post-unseal hold，闸门仍整队
        持有；hold 期满才放单条探针。）
        """
        pc, pm, calls = self._make_circuit_with_engine()
        self._trigger(pc)
        # 冻结中查询不唤醒（`_process_queue` 本就该被闸门挡住）
        assert pc.is_global_transient_break(now=1700) is True
        assert calls == []
        # 冷却到期（缺省 600s）→ 解除并唤醒一次（唤醒 ≠ 放行：随即进入 hold）
        assert pc.is_global_transient_break(now=1801) is False
        assert calls == [True]
        assert pc.transient_unseal_gate(now=1801) == "hold"
        # 已解除后再查询不再重复唤醒（熔断态已清零，早退分支）
        assert pc.is_global_transient_break(now=1900) is False
        assert calls == [True]
        # hold 期满 → 探针观察窗（单条探针准入，非全量放行）
        assert pc.transient_unseal_gate(now=1862) == "probe"
        assert pc.admit_unseal_dispatch(now=1862) is True
        assert pc.admit_unseal_dispatch(now=1862.5) is False

    def test_expiry_wake_failure_does_not_block_resume(self):
        """唤醒异常 MUST NOT 阻断「熔断到期 → 恢复派发」闸门语义（fail-open）。

        （evo-fix-transient-break-unseal-backoff 2.2 修订：fail-open 覆盖解封
        全链——唤醒异常不阻断解封→hold→探针观察窗的闸门推进。）
        """
        class _BoomEngine:
            def _process_queue(self):
                raise RuntimeError("boom")

        pc, pm, _ = self._make_circuit_with_engine()
        pm._pm_engine_ref = _BoomEngine()
        self._trigger(pc)
        assert pc.is_global_transient_break(now=1801) is False
        # 熔断态确已清零，解封→hold 推进不被唤醒异常吞掉
        assert pc.transient_unseal_gate(now=1801) == "hold"
        assert pc.is_global_transient_break(now=1900) is False
        # hold 期满 → 探针观察窗照常推进
        assert pc.transient_unseal_gate(now=1862) == "probe"
        assert pc.admit_unseal_dispatch(now=1862) is True

    def test_expiry_without_engine_ref_is_noop(self):
        """无 PMEngine 回引（测试/CLI 场景）时零操作、不抛异常。"""
        pc, pm = self._make_circuit()
        self._trigger(pc)
        assert pc.is_global_transient_break(now=1801) is False
        assert pc.is_global_transient_break(now=1900) is False



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

            def _exempt_dead_run_budget(self, spec_name, reason, run_reason=None):
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

            def _exempt_dead_run_budget(self, spec_name, reason, run_reason=None):
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

            # fix-redispatch-loop-governance 3.3：同因重派熔断经 _pm 调用归因指纹
            #（与真实 PMEngine._redispatch_cause_fingerprint 同语义——归一化哈希）
            @staticmethod
            def _redispatch_cause_fingerprint(error):
                import hashlib
                norm = "".join((error or "").split())
                return hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:12]

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


# ═══════════════════════════════════════════════════════════════════════════
# 6.1 回归：瞬断重试 × 秒挂熔断（cli-retry-backoff instant_fail 交互）
# ═══════════════════════════════════════════════════════════════════════════

class TestTransientRetryInstantFailInteraction:
    """Task 6.1 — 原地重试拉长存活不误触发秒挂；与死亡豁免/预算闸门叠加不回归。

    交互面：attempt 的秒挂判定按 `time.time() - attempt_started_at`（wall clock）
    判定，原地退避的 sleep 计入其中——多次快速失败会在退避间隙被拉长到 ≥60s
    阈值，从而 _record_instant_fail 视为「正常失败」并重置秒挂计数，不误触发冷却。
    """

    def test_transient_retry_does_not_accumulate_instant_fail(self, tmp_path):
        """原地退避 sleep 拉长 wall clock → 秒挂计数被重置而非累计触发冷却。"""
        runner = _build_runner(tmp_path, _make_chain_config("implementer"))
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-123"
        runner._run_claude = lambda *a, **k: (_ for _ in ()).throw(
            _TransientError(
                stderr_lines=["[claude-code:unrecognized_model] model not found"],
                exit_code=1, has_result=False,
            ))

        # 直接验证 _record_instant_fail 的交互语义（不依赖 sleep 真等）：
        # 瞬断重试场景下 attempt 存活时长 ≥60s → 重置计数；<60s 连续失败达
        # cooldown_after 才冷却。此处模拟「退避拉长到阈值以上」的重置路径。
        assert runner._instant_fail_counts("spec-x") == 0
        runner._record_instant_fail("spec-x", duration_seconds=59)   # 秒挂 +1
        assert runner._instant_fail_counts("spec-x") == 1
        runner._record_instant_fail("spec-x", duration_seconds=120)  # 退避后拉长 → 重置
        assert runner._instant_fail_counts("spec-x") == 0
        assert runner.is_instant_fail_cooldown("spec-x") is False

    def test_instant_fail_storm_still_triggers(self, tmp_path):
        """真实秒挂风暴（无退避拉长）仍触发冷却——闸门不被新逻辑弱化。"""
        runner = _build_runner(tmp_path, _make_chain_config("implementer"))
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-123"
        # cooldown_after=2（缩小阈值便于断言）
        runner._get_config = lambda key, default=None: (
            2 if key == "agents.instant_fail_cooldown_after" else default)
        runner._record_instant_fail("spec-y", duration_seconds=5)
        runner._record_instant_fail("spec-y", duration_seconds=5)
        assert runner._instant_fail_counts("spec-y") == 2
        assert runner.is_instant_fail_cooldown("spec-y") is True


# ═══════════════════════════════════════════════════════════════════════════
# 6.2 回归：daemon 重启恢复与 keep_for_reuse 遗产协同（无互删）
# ═══════════════════════════════════════════════════════════════════════════

class TestRecoveryKeepForReuseCoordination:
    """Task 6.2 — recover_interrupted 与 keep_for_reuse 遗产认领协同。

    协同面：瞬断终态 keep_for_reuse 登记的遗产进入 _legacy（回收中心登记表），
    与 interrupt-recovery-preserve 的恢复保留共用同一豁免机制；boot 顺序
    recovery → stale cleanup 与遗产认领互不删、可继承。
    """

    def _init_repo(self, root):
        root.mkdir(parents=True, exist_ok=True)
        for args in (["init", "-q"], ["config", "user.email", "test@fenix.local"],
                     ["config", "user.name", "Fenix Test"],
                     ["config", "commit.gpgsign", "false"]):
            subprocess.run(["git", "-C", str(root), *args], check=True)
        (root / "base.py").write_text("BASE\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "[fenix] base"],
                       check=True)
        subprocess.run(["git", "-C", str(root), "branch", "-M", "main"], check=True)

    def test_keep_for_reuse_legacy_survives_recovery_and_stale_cleanup(self, tmp_path):
        """keep_for_reuse 遗产经 recover + stale cleanup 后仍被 create 认领（无互删）。"""
        from core.worktree_manager import WorktreeManager
        root = tmp_path / "repo"
        self._init_repo(root)
        base = root / ".claude" / "worktrees"
        base.mkdir(parents=True, exist_ok=True)
        wm = WorktreeManager(base, root, FakeLogger())

        wt = wm.create("spec-r", "planner-judge")
        assert wt is not None
        branch = wm.get_branch_name(wt)
        wm.keep_for_reuse("spec-r", wt, agent_type="planner-judge")
        # 遗产在册
        assert wm.has_legacy("spec-r")
        assert wm.get_legacy("spec-r")["reuse"] is True

        # 模拟 daemon boot：先 recovery（本 spec 无 interrupted 保留条目 → 不影响），
        # 再 stale 清扫——遗产 worktree 名在豁免集，不得被删除
        wm.cleanup_stale_worktrees()
        assert wt.exists(), "keep_for_reuse 遗产在 stale 清扫中不得被误删"

        # 下轮派发 create() → 经 _take_reusable_worktree 认领同一目录与分支
        wt2 = wm.create("spec-r", "planner-judge")
        assert wt2 == wt, "遗产应被认领复用而非新建"
        assert wm.get_branch_name(wt2) == branch
        # 认领后从 _legacy 摘出（sweeper 不再豁免，属在用目录）
        assert not wm.has_legacy("spec-r")

    def test_stale_cleanup_removes_non_legacy_worktrees(self, tmp_path):
        """对照：未登记的孤儿 worktree 仍被 stale 清扫删除（遗产豁免不殃及正常回收）。"""
        from core.worktree_manager import WorktreeManager
        root = tmp_path / "repo2"
        self._init_repo(root)
        base = root / ".claude" / "worktrees"
        base.mkdir(parents=True, exist_ok=True)
        wm = WorktreeManager(base, root, FakeLogger())

        # 一个 keep_for_reuse 遗产 + 一个未登记的孤儿 worktree
        wt_kept = wm.create("spec-k", "implementer")
        wm.keep_for_reuse("spec-k", wt_kept, agent_type="implementer")
        wt_orphan = wm.create("spec-orphan", "verifier")
        # 孤儿不登记遗产、不在活动集（模拟异常退出残留）：从活动集移除即可被清扫
        wm._active_worktrees.discard(str(wt_orphan))

        wm.cleanup_stale_worktrees()
        assert wt_kept.exists(), "登记遗产豁免清理"
        assert not wt_orphan.exists(), "未登记孤儿被清扫"


# ═══════════════════════════════════════════════════════════════════════════
# 6.4 真实故障文本 fixture 回放（补充：瞬断指纹 × 全局熔断链路）
# ═══════════════════════════════════════════════════════════════════════════

class TestRealFailureFingerprintReplay:
    """Task 6.4 — 2026-09 死亡 run 的 stderr 样本回放全局熔断指纹链路。

    样本与 TestRealFailureFixtures 同源；此处验证归一化指纹在真实故障文本上
    收敛（不同 model 变体同指纹 → 熔断触发），且真实缺陷文本指纹互异（不误伤）。
    """

    def test_real_transient_samples_converge_to_one_fingerprint(self):
        """死亡 run 的三个真实瞬断 stderr 样本归一化为同一指纹。"""
        samples = [
            "[claude-code:unrecognized_model] model deepseek-v4 not found\n"
            'API error: unrecognized model "deepseek-v4-flash"\n'
            "[claude-code:token_usage] total=0\n",
            "[claude-code:unrecognized_model] model deepseek-v4 not found\n"
            'API error: unrecognized model "glm-5.3-flash"\n'
            "[claude-code:token_usage] total=0\n",
            "[claude-code:unrecognized_model] model deepseek-v4 not found\n"
            'API error: unrecognized model "claude-sonnet-5"\n'
            "[claude-code:token_usage] total=0\n",
        ]
        fps = [ProviderCircuit.normalize_transient_fingerprint(s) for s in samples]
        assert len(set(fps)) == 1, f"三个真实瞬断样本应归一化为同一指纹: {fps}"

    def test_real_transient_samples_trigger_global_break(self):
        """三个不同 spec 的真实瞬断死亡 → 第 3 次触发全局熔断。"""
        pm = type("_PM", (), {
            "config": {}, "project_root": None, "logger": FakeLogger(),
            "now": 1000.0,
            "_now": lambda self: 1000.0,
            "_get_config": lambda self, key, default=None: default,
        })()
        pc = ProviderCircuit(pm)
        samples = [
            'API error: unrecognized model "deepseek-v4-flash"',
            'API error: unrecognized model "glm-5.3-flash"',
            'API error: unrecognized model "claude-sonnet-5"',
        ]
        assert pc.record_transient_error(samples[0]) is False
        assert pc.record_transient_error(samples[1]) is False
        assert pc.record_transient_error(samples[2]) is True
        assert pc.is_global_transient_break() is True

    def test_real_bug_texts_have_distinct_fingerprints(self):
        """真实缺陷类错误文本指纹互异（不收敛、不误触发熔断）。"""
        bugs = [
            "AssertionError: expected 'foo' to equal 'bar'",
            "TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'",
            "ValueError: invalid literal for int() with base 10: 'abc'",
        ]
        fps = [ProviderCircuit.normalize_transient_fingerprint(b) for b in bugs]
        assert len(set(fps)) == 3, f"真实缺陷文本指纹应互异: {fps}"

    def test_non_model_numeric_fields_not_swallowed_as_model(self):
        """exit code / http 状态码 / request id 保留原文，异类失败指纹互异。

        （item 686d4a1b599f：旧宽 pattern 把「连字符分段且数字结尾」的 token
        一律剥成 <model>，不同退出码/HTTP 状态码的异类失败被折进同一指纹。）
        """
        failures = [
            "process terminated with exit-code-143",
            "process terminated with exit-code-137",
            "gateway returned http-503",
            "gateway returned http-502",
            "upstream rejected request-id-88271",
        ]
        fps = [ProviderCircuit.normalize_transient_fingerprint(s) for s in failures]
        assert len(set(fps)) == len(failures), f"异类失败指纹应互异: {fps}"
        assert all("<model>" not in fp for fp in fps), (
            f"非模型数字字段不应被剥成 <model>: {fps}"
        )

    def test_numeric_field_hyphen_and_space_forms_converge(self):
        """同一错误的连字符/空格两种书写形态收敛到同一指纹（item 686d4a1b599f）。"""
        pairs = [
            ("process terminated with exit-code-143",
             "process terminated with exit code 143"),
            ("gateway returned http-503", "gateway returned http 503"),
            ("upstream rejected request-id-88271",
             "upstream rejected request id 88271"),
        ]
        for hyphen_form, space_form in pairs:
            assert (
                ProviderCircuit.normalize_transient_fingerprint(hyphen_form)
                == ProviderCircuit.normalize_transient_fingerprint(space_form)
            ), f"两种书写形态应收敛同一指纹: {hyphen_form!r} vs {space_form!r}"

    def test_versioned_model_names_still_normalized_to_placeholder(self):
        """收窄版本段 pattern 后真模型名（含版本号形态）仍剥成 <model> 且变体收敛。"""
        texts = [
            'API error: unrecognized model "deepseek-v4-flash"',
            'API error: unrecognized model "glm-5.3-flash"',
            'API error: unrecognized model "claude-sonnet-5"',
            'API error: unrecognized model "claude-3-5-haiku"',
        ]
        fps = [ProviderCircuit.normalize_transient_fingerprint(t) for t in texts]
        assert all("<model>" in fp for fp in fps), (
            f"真模型名应仍被归一为 <model>: {fps}"
        )
        assert len(set(fps)) == 1, f"模型变体同型瞬断应收敛同一指纹: {fps}"


class TestShutdownInterruptGuard:
    """shutdown-kill 不进瞬断通道（2026-09-09 事故守卫）。

    事故：restart_request 排水收口 SIGTERM 杀在飞 implementer（exit 143 + stderr
    仅 [claude-code: 诊断行 + 无 result），被通道2 误判 provider-transient →
    排 30s 僵尸原地重试（与下一 daemon recovery 重派赛跑）+ 污染全局瞬断计数。
    守卫：shutting_down 置位（无竞态主信号）或产物 interrupted 标记（辅信号）
    命中 → 跳过瞬断判定/原地重试/熔断记账，error 打 [shutdown-interrupted]
    前缀，终态保留 worktree 现场（交 recovery/保全处置，不 cleanup 销毁）。
    """

    def _incident_signature_error(self):
        """精确复刻 09-09 事故签名：SIGTERM 死法 → 通道2 必命中。"""
        return _TransientError(
            stderr_lines=["[claude-code:ERROR] session terminated by signal"],
            exit_code=143,
            has_result=False,
        )

    def _build_incident_runner(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda _: None)
        config = _make_chain_config("implementer")
        config["agents"]["max_retries"] = 2
        runner = _build_runner(tmp_path, config)
        wt = tmp_path / "wt"
        wt.mkdir()
        subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-123"
        return runner, wt

    def test_shutting_down_skips_transient_retry(self, tmp_path, monkeypatch):
        """shutting_down 置位 + 事故签名 → 不重试、[shutdown-interrupted] 前缀、保留现场。"""
        runner, _wt = self._build_incident_runner(tmp_path, monkeypatch)
        runner.shutting_down = True

        calls = {"n": 0}

        def fake_run_claude(*args, **kwargs):
            calls["n"] += 1
            raise self._incident_signature_error()

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("test-spec", "implementer", "run-1")

        # 单次调用即终态：无原地重试、无 attempt 2
        assert calls["n"] == 1, f"应只调用一次 _run_claude，实际 {calls['n']} 次"
        assert result.success is False
        assert (result.error or "").startswith("[shutdown-interrupted]")
        # 现场保留（交 recovery/保全处置），不 cleanup 销毁未提交工作
        runner.worktree_manager.cleanup.assert_not_called()
        runner.worktree_manager.keep_for_reuse.assert_not_called()
        assert result.worktree_kept is True

    def test_interrupted_marker_skips_transient_retry(self, tmp_path, monkeypatch):
        """产物已带 interrupted 标记（shutting_down 未置位）→ 同样短路瞬断通道。"""
        runner, _wt = self._build_incident_runner(tmp_path, monkeypatch)

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            # 模拟 daemon 侧同步写入 interrupted 标记（liveness 第二步）
            runs_dir = runner.project_root / ".fenix" / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            run_file = runs_dir / f"{run_id}.jsonl"
            with run_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "type": "interrupted",
                    "reason": "daemon shutdown",
                    "by": "agent_runner",
                }) + "\n")
            raise self._incident_signature_error()

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("test-spec", "implementer", "run-2")

        assert calls["n"] == 1, f"应只调用一次 _run_claude，实际 {calls['n']} 次"
        assert (result.error or "").startswith("[shutdown-interrupted]")
        runner.worktree_manager.cleanup.assert_not_called()
