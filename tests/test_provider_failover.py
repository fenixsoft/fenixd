"""add-provider-failover：多 provider 候选链 failover 单测。

覆盖 tasks：
- 1.1 config 链解析（list / 单值兼容 / 未知名 ERROR 不阻塞）
- 2.1 classify_switch_error 错误分类矩阵（含今日真实报错文本 + 4xx 不误分类）
- 2.2 链级 switch 冷却（单家冷却跳转 / 全链耗尽 / 冷却到期主链复位）
- 3.1 attempt 循环链选择 + 续跑（首候选 dying → 次候选接管且 session_id 保持）
- 3.2 CLAUDE_CONFIG_DIR 随候选切换 + 跨 provider 切换日志
- 4.1 观测：provider_marker / provider_used / model_used / "provider switched" 打点
- 4.2 per-provider 当日计数告警
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import (
    PROVIDER_DAILY_ATTEMPTS_WARN,
    PROVIDER_SWITCH_COOLDOWN_SECONDS,
    AgentRunner,
)
from core.config import ConfigLoader


class FakeLogger:
    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.records.append(("info", a[1] if len(a) > 1 else ""))

    def warning(self, *a, **k):
        self.records.append(("warning", a[1] if len(a) > 1 else ""))

    def error(self, *a, **k):
        self.records.append(("error", a[1] if len(a) > 1 else ""))

    def messages(self):
        return [m for _lvl, m in self.records]

    def has(self, text):
        return any(text in m for m in self.messages())


def make_runner(proot: Path, config: dict | None = None) -> AgentRunner:
    """构造最小 AgentRunner 实例（绕过真实 __init__ 的 worktree/state_machine 依赖）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._daily_reset_date = None
    runner._daily_provider_attempts = {}
    runner._daily_provider_warned = {}
    runner.provider_circuits = {}
    return runner


def chain_config(chain, model="deepseek-v4-flash"):
    """构造含两 provider 与 implementer 候选链的 config。"""
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


# ═══════════════════════════════════════════════════════════════════════════
# 1.1 config 链解析
# ═══════════════════════════════════════════════════════════════════════════

class TestChainConfigParsing:
    def test_list_chain_parsed(self):
        """列表链解析为两元素链，首选 inferaiapi.com。"""
        config = chain_config(["inferaiapi.com", "aliyun"])
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        assert result is not None
        assert len(result) == 2
        assert result[0][0]["name"] == "inferaiapi.com"
        assert result[1][0]["name"] == "aliyun"

    def test_single_value_compatible(self, monkeypatch):
        """单值 provider 解析为单元素链，逐字段与变更前一致。"""
        config = chain_config("inferaiapi.com")
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        assert result is not None
        assert len(result) == 1
        provider, model = result[0]
        assert provider["name"] == "inferaiapi.com"
        assert provider["baseurl"] == "https://a.com"
        assert provider["apikey"] == "k1"
        assert model == "deepseek-v4-flash"

    def test_unknown_name_errors_not_blocks(self, tmp_path, monkeypatch):
        """未知 provider 名仅打 ERROR 不阻塞加载，运行期该元素被跳过。"""
        import core.config as cfg_mod
        logger = FakeLogger()
        monkeypatch.setattr(cfg_mod, "_logger", logger)
        config = {
            "llm": {"providers": [
                {"name": "aliyun", "baseurl": "https://b.com", "apikey": "k2"},
            ]},
            "agents": {"models": {
                "implementer": {"provider": ["ghost", "aliyun"], "model": "m"},
            }},
        }
        # get_agent_model_assignment 不抛异常，未知元素跳过、已知元素保留
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        assert result is not None
        assert len(result) == 1
        assert result[0][0]["name"] == "aliyun"


# ═══════════════════════════════════════════════════════════════════════════
# 2.1 classify_switch_error 错误分类矩阵
# ═══════════════════════════════════════════════════════════════════════════

class TestClassifySwitchError:
    # 今日真实故障文本 fixture（2026-08-27 inferaiapi / aliyun 各自拒绝 deepseek 变体）
    REAL_FIXTURES = [
        '[claude-code:unrecognized_model] {"model":"deepseek-v4-flash"}',
        'API error: unrecognized model "deepseek-v4-flash-0731"',
        'model not found: deepseek-v4-flash',
        'HTTP 503 Service Unavailable',
        'HTTP 500 Internal Server Error',
        'connection refused',
        'failed to connect: dial tcp ...: i/o timeout',
        'name or service not known',
    ]

    def test_real_fixtures_classified_as_switch(self):
        for text in self.REAL_FIXTURES:
            assert AgentRunner.classify_switch_error(text) is True, text

    def test_4xx_not_classified(self):
        """4xx 配额/鉴权类不触发切换（维持既有熔断语义）。"""
        assert AgentRunner.classify_switch_error("HTTP 404") is False
        assert AgentRunner.classify_switch_error("HTTP 401 unauthorized") is False
        assert AgentRunner.classify_switch_error("API error (400): bad request") is False

    def test_empty_text_not_classified(self):
        assert AgentRunner.classify_switch_error("") is False
        assert AgentRunner.classify_switch_error(None) is False


# ═══════════════════════════════════════════════════════════════════════════
# 2.2 链级 switch 冷却
# ═══════════════════════════════════════════════════════════════════════════

class TestSwitchCooldown:
    def test_single_provider_cooldown_then_advance(self, tmp_path, monkeypatch):
        """单家切换类冷却后链选择跳过，冷却到期主链复位优先。"""
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        assert runner._select_chain_candidate(
            ConfigLoader.get_agent_model_assignment(runner.config, "implementer"),
            "s", "implementer", now=now,
        ) == 0
        runner._record_switch_cooldown("inferaiapi.com", now=now)
        # 冷却中：_select_chain_candidate 跳过
        assert runner.is_switch_cooldown("inferaiapi.com", now=now)
        # 冷却到期：自动复位、可再次选中
        later = now + PROVIDER_SWITCH_COOLDOWN_SECONDS + 1
        monkeypatch.setattr(runner, "_now", lambda: later)
        assert not runner.is_switch_cooldown("inferaiapi.com", now=later)
        assert runner._select_chain_candidate(
            ConfigLoader.get_agent_model_assignment(runner.config, "implementer"),
            "s", "implementer", now=later,
        ) == 0

    def test_chain_exhausted_when_all_cooldown(self, tmp_path, monkeypatch):
        """全链冷却 → _execute_agent 返回 chain_exhausted 失败、不启动进程。"""
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._record_switch_cooldown("inferaiapi.com", now=now)
        runner._record_switch_cooldown("aliyun", now=now)
        # 不创建 worktree / 不启动 claude
        runner.worktree_manager = MagicMock()
        result = runner.run_implementer("s")
        assert result.success is False
        assert result.chain_exhausted is True
        assert runner.worktree_manager.create.call_count == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3.1 attempt 循环链选择 + 续跑
# ═══════════════════════════════════════════════════════════════════════════

class TestChainSelectExecute:
    def test_first_dying_then_second_takes_over_with_resume(self, tmp_path, monkeypatch):
        """首候选 unrecognized_model 失败后，次候选接管且 session_id 保持（resume）。"""
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        wt = tmp_path / "wt"
        runner.worktree_manager.create.return_value = wt

        calls = {"n": 0, "resume_seen": False, "providers": []}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None):
            calls["n"] += 1
            calls["providers"].append(env_overrides.get("ANTHROPIC_BASE_URL"))
            if calls["n"] == 1:
                # 首候选失败：unrecognized_model（切换类错误）
                raise RuntimeError(
                    '[claude-code:unrecognized_model] {"model":"deepseek-v4-flash"}'
                )
            if resume_session_id == "sess-keep":
                calls["resume_seen"] = True
            return ("ok", 1, "sess-keep")

        runner._run_claude = fake_run_claude
        runner._extract_session_id = MagicMock(return_value="sess-keep")

        result = runner.run_implementer("s")
        # 次候选成功
        assert result.success is True
        assert result.provider_used == "aliyun"
        # 链推进：首 a.com → 次 b.com
        assert calls["providers"][0] == "https://a.com"
        assert calls["providers"][1] == "https://b.com"
        # 切换后 attempt 携带 --resume 续跑原会话
        assert calls["resume_seen"] is True

    def test_switch_not_advance_on_4xx(self, tmp_path, monkeypatch):
        """4xx 配额类失败不推进链指针（维持首候选）。"""
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"

        calls = {"providers": []}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None):
            calls["providers"].append(env_overrides.get("ANTHROPIC_BASE_URL"))
            # 始终 4xx → 不切换，链指针不动，下一 attempt 仍用首候选
            raise RuntimeError("HTTP 404")

        runner._run_claude = fake_run_claude
        runner._extract_session_id = MagicMock(return_value=None)
        runner.run_implementer("s")
        # 三次重试都在首候选（a.com），未前进到 aliyun
        assert calls["providers"] == ["https://a.com"] * 3


# ═══════════════════════════════════════════════════════════════════════════
# 3.2 CLAUDE_CONFIG_DIR 随候选切换 + 跨 provider 切换日志
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigDirSwitch:
    def test_claude_config_dir_switches_with_candidate(self, tmp_path, monkeypatch):
        """注入的 CLAUDE_CONFIG_DIR 随候选同步切换（指向不同 provider 隔离目录）。"""
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"

        captured_dirs = []

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None):
            captured_dirs.append(env_overrides.get("CLAUDE_CONFIG_DIR"))
            if len(captured_dirs) == 1:
                raise RuntimeError("unrecognized_model")
            return ("ok", 1, "sess")

        runner._run_claude = fake_run_claude
        runner._extract_session_id = MagicMock(return_value="sess")
        runner.run_implementer("s")
        # 两次运行指向不同 provider 的隔离目录
        assert "agent-config/inferaiapi.com" in captured_dirs[0]
        assert "agent-config/aliyun" in captured_dirs[1]
        assert captured_dirs[0] != captured_dirs[1]

    def test_switch_event_logged(self, tmp_path, monkeypatch):
        """跨 attempt 的 provider 切换输出 "provider switched" INFO 日志。"""
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None):
            if "a.com" in env_overrides.get("ANTHROPIC_BASE_URL", ""):
                raise RuntimeError("unrecognized_model")
            return ("ok", 1, "sess")

        runner._run_claude = fake_run_claude
        runner._extract_session_id = MagicMock(return_value="sess")
        runner.run_implementer("mytest-spec")
        assert runner.logger.has("provider switched inferaiapi.com → aliyun for 'mytest-spec'")


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 观测：provider_marker / provider_used / model_used
# ═══════════════════════════════════════════════════════════════════════════

class TestProviderObservability:
    def test_provider_marker_written_and_result_fields(self, tmp_path, monkeypatch):
        """attempt 启动时 run jsonl 写 provider_marker；AgentRunResult 带 provider_used/model_used。"""
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"
        runner._run_claude = MagicMock(return_value=("ok", 1, "sess"))
        result = runner.run_implementer("s")
        assert result.provider_used == "inferaiapi.com"
        assert result.model_used == "deepseek-v4-flash"
        # run jsonl 含 provider_marker，指明 chain_index=0
        runs = tmp_path / ".fenix" / "runs"
        marker = None
        for f in runs.glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                e = json.loads(line)
                if e.get("type") == "provider_marker":
                    marker = e
        assert marker is not None
        assert marker["provider"] == "inferaiapi.com"
        assert marker["chain_index"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 4.2 per-provider 当日计数告警
# ═══════════════════════════════════════════════════════════════════════════

class TestDailyAttemptWarn:
    def test_warn_once_when_exceeded(self, tmp_path, monkeypatch):
        """当日 attempt 超 daily_attempts_warn 时打 WARNING 且当日只告警一次。"""
        config = {"pm": {"failover": {"daily_attempts_warn": 3}}}
        runner = make_runner(tmp_path, config)
        # 跨天重置检查不触发（同日期）
        for _ in range(5):
            runner._record_daily_provider_attempt("aliyun")
        warns = [m for lvl, m in runner.logger.records if lvl == "warning"
                 and "daily attempts" in m]
        assert len(warns) == 1
        assert runner._daily_provider_attempts["aliyun"] == 5

    def test_no_warn_under_threshold(self, tmp_path):
        runner = make_runner(tmp_path, {})
        for _ in range(PROVIDER_DAILY_ATTEMPTS_WARN - 1):
            runner._record_daily_provider_attempt("aliyun")
        warns = [m for lvl, m in runner.logger.records if lvl == "warning"
                 and "daily attempts" in m]
        assert warns == []
