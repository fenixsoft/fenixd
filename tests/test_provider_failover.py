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
import subprocess
import time
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


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """吞掉 runner 的重试 sleep（与 test_agent_runner_gate 等同一处方）。

    run_implementer 失败后每 attempt 有 ``time.sleep(10)``（runner.py:3116），
    provider 失败场景常走满 2 次重试 → 每测试 +20s；本文件 8 个测试曾因此
    累计 161s。sleep 不是被测行为（退避时长有独立覆盖），stub 掉即恢复
    测试的原始耗时。
    """
    monkeypatch.setattr(time, "sleep", lambda _s: None)


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
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    # v2 dev-server stub：本文件各测试的 fake _run_agent 让 run_implementer 走
    # 完整成功收口 → _finalize_success 会 _v2_launch_for_worktree / _v2_stop_for_worktree
    # 真实 spawn/回收 node dev-server（每个测试一次），全量套件内累积到 250s+。
    # 本文件测 provider 链切换，与 worktree 测试服务器生命周期正交，stub 掉即恢复
    # 原始语义（与 test_agent_runner_gate / test_planready_artifact_gate 同处方）。
    runner.__dict__["_v2_server_instance"] = MagicMock()
    runner._v2_server._v2_inject_env.return_value = {}
    # 产物硬门 stub（test_provider_failover 关注 provider 切换，与 implementer
    # 产物完成度正交）：fix-impl-tasks-completion-gate（2026-09-14 df8dd94c）
    # 给 implementer/fast-track 加了「worktree 内 .fenix-run-result.json 存在 +
    # status 白名单 + tasks.md 完成度对账」硬门，而本文件各测试的 fake
    # _run_agent 只返回成功元组、从不写结果文件 → 硬门判失败 → 落入瞬态退避
    # 通道 time.sleep(30/60/120)，单测试实测挂起 210s+（全文件 8 failed/161s，
    # 也是 run_full_suite 卡死的根因）。这些测试不关心产物完成度，stub 掉硬门
    # 即恢复其原始语义（09-14 之前该硬门对 implementer 直接 return None）。
    runner._check_agent_result_artifact = MagicMock(return_value=None)
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


def object_chain_config(elements):
    """构造 implementer 对象数组链 config（每个元素 {provider, model?}）。"""
    providers = [
        {"name": "inferaiapi.com", "baseurl": "https://a.com", "apikey": "k1"},
        {"name": "aliyun", "baseurl": "https://b.com", "apikey": "k2"},
        {"name": "bigmodel.cn", "baseurl": "https://c.com", "apikey": "k3"},
    ]
    return {
        "llm": {"providers": providers},
        "agents": {
            "models": {"implementer": {"provider": elements}},
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

    def test_object_elements_resolve_per_element_model(self):
        """对象元素按各自 model 解析，不共享角色级 model（角色级缺省）。"""
        config = object_chain_config([
            {"provider": "inferaiapi.com", "model": "deepseek-v4-flash"},
            {"provider": "bigmodel.cn",    "model": "glm-5.3-flash"},
        ])
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        assert result is not None
        assert len(result) == 2
        assert (result[0][0]["name"], result[0][1]) == ("inferaiapi.com", "deepseek-v4-flash")
        assert (result[1][0]["name"], result[1][1]) == ("bigmodel.cn",    "glm-5.3-flash")

    def test_mixed_str_object_chain(self):
        """混合 [对象, str]：str 元素无角色级 model 时回退 provider 条目 model。"""
        config = object_chain_config([
            {"provider": "inferaiapi.com", "model": "deepseek-v4-flash"},
            "aliyun",  # aliyun 在 providers 条目中无 model → 无可用模型被跳过
        ])
        result = ConfigLoader.get_agent_model_assignment(config, "implementer")
        assert result is not None
        assert len(result) == 1
        assert result[0][0]["name"] == "inferaiapi.com"

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
        runner._provider_circuit._record_switch_cooldown("inferaiapi.com", now=now)
        # 冷却中：_select_chain_candidate 跳过
        assert runner._provider_circuit.is_switch_cooldown("inferaiapi.com", now=now)
        # 冷却到期：自动复位、可再次选中
        later = now + PROVIDER_SWITCH_COOLDOWN_SECONDS + 1
        monkeypatch.setattr(runner, "_now", lambda: later)
        assert not runner._provider_circuit.is_switch_cooldown("inferaiapi.com", now=later)
        assert runner._select_chain_candidate(
            ConfigLoader.get_agent_model_assignment(runner.config, "implementer"),
            "s", "implementer", now=later,
        ) == 0

    def test_chain_exhausted_when_all_cooldown(self, tmp_path, monkeypatch):
        """全链冷却 → _execute_agent 返回 chain_exhausted 失败、不启动进程。"""
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner._provider_circuit._record_switch_cooldown("inferaiapi.com", now=now)
        runner._provider_circuit._record_switch_cooldown("aliyun", now=now)
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
    def test_first_dying_then_second_takes_over_without_cross_provider_resume(
            self, tmp_path, monkeypatch):
        """首候选 unrecognized_model 失败后，次候选接管但跨 provider 不 resume（fix）。

        session 存在于首候选的 CLAUDE_CONFIG_DIR，切换后 --resume 必然
        'No conversation found with session ID' 秒挂（2026-08-28 admin 处置
        fix-fix-fix-add-spec-context-menu 根因），故 provider 变更后续跑必须放弃。
        """
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        wt = tmp_path / "wt"
        wt.mkdir()
        subprocess.run(["git", "init", "-q", str(wt)], check=True)  # 3a：须为可解析 git 工作树
        runner.worktree_manager.create.return_value = wt

        calls = {"n": 0, "resume_seen": False, "providers": [], "fresh_after_switch": False}

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None, spec_name=None,
                            agent_type=None, task_progress_snapshot=None):
            calls["n"] += 1
            calls["providers"].append(env_overrides.get("ANTHROPIC_BASE_URL"))
            if calls["n"] == 1:
                # 首候选失败：unrecognized_model（切换类错误）
                raise RuntimeError(
                    '[claude-code:unrecognized_model] {"model":"deepseek-v4-flash"}'
                )
            if resume_session_id == "sess-keep":
                calls["resume_seen"] = True
            else:
                calls["fresh_after_switch"] = True
            return ("ok", 1, "sess-keep", {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "cost_usd": None})

        runner._run_agent = fake_run_agent
        runner._extract_session_id = MagicMock(return_value="sess-keep")

        result = runner.run_implementer("s")
        # 次候选成功
        assert result.success is True
        assert result.provider_used == "aliyun"
        # 链推进：首 a.com → 次 b.com
        assert calls["providers"][0] == "https://a.com"
        assert calls["providers"][1] == "https://b.com"
        # fix：跨 provider 切换后从头执行，不带死 session_id 去 --resume
        assert calls["resume_seen"] is False
        assert calls["fresh_after_switch"] is True

    def test_dead_session_cleared_on_resume_not_found(self, tmp_path, monkeypatch):
        """resume 报会话不存在时清除 session_id，同 provider 重试从头执行。"""
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        wt = tmp_path / "wt"
        wt.mkdir()
        subprocess.run(["git", "init", "-q", str(wt)], check=True)  # 3a：须为可解析 git 工作树
        runner.worktree_manager.create.return_value = wt

        calls = {"n": 0, "resumes": []}

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None, spec_name=None,
                            agent_type=None, task_progress_snapshot=None):
            calls["n"] += 1
            calls["resumes"].append(resume_session_id)
            if calls["n"] == 1:
                # a1 瞬态失败（非切换类，链指针不动），但已建立 session
                raise RuntimeError("mock transient failure")
            if calls["n"] == 2:
                # a2 resume 死 id → 会话不存在
                raise RuntimeError(
                    "claude CLI failed: No conversation found with session ID: sess-dead"
                )
            return ("ok", 1, "sess-new", {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "cost_usd": None})

        runner._run_agent = fake_run_agent
        runner._extract_session_id = MagicMock(return_value="sess-dead")

        result = runner.run_implementer("s")
        # a2 携带死 id resume 失败 → 清除后 a3 从头执行，链推进后成功（不烧尽重试）
        assert result.success is True
        assert calls["resumes"] == [None, "sess-dead", None]

    def test_switch_not_advance_on_4xx(self, tmp_path, monkeypatch):
        """4xx 配额类失败不推进链指针（维持首候选）。"""
        runner = make_runner(tmp_path, chain_config(["inferaiapi.com", "aliyun"]))
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"

        calls = {"providers": []}

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None, spec_name=None,
                            agent_type=None, task_progress_snapshot=None):
            calls["providers"].append(env_overrides.get("ANTHROPIC_BASE_URL"))
            # 始终 4xx → 不切换，链指针不动，下一 attempt 仍用首候选
            raise RuntimeError("HTTP 404")

        runner._run_agent = fake_run_agent
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

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None, spec_name=None,
                            agent_type=None, task_progress_snapshot=None):
            captured_dirs.append(env_overrides.get("CLAUDE_CONFIG_DIR"))
            if len(captured_dirs) == 1:
                raise RuntimeError("unrecognized_model")
            return ("ok", 1, "sess", {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "cost_usd": None})

        runner._run_agent = fake_run_agent
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

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None, spec_name=None,
                            agent_type=None, task_progress_snapshot=None):
            if "a.com" in env_overrides.get("ANTHROPIC_BASE_URL", ""):
                raise RuntimeError("unrecognized_model")
            return ("ok", 1, "sess", {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "cost_usd": None})

        runner._run_agent = fake_run_agent
        runner._extract_session_id = MagicMock(return_value="sess")
        runner.run_implementer("mytest-spec")
        assert runner.logger.has("provider switched inferaiapi.com → aliyun for 'mytest-spec'")


# ═══════════════════════════════════════════════════════════════════════════
# 4.1 观测：provider_marker / provider_used / model_used
# ═══════════════════════════════════════════════════════════════════════════

class TestProviderObservability:
    def test_provider_marker_written_and_result_fields(self, tmp_path, monkeypatch):
        """attempt 启动时 run jsonl 写 provider_marker（provider/model/chain_index）；
        AgentRunResult 带 provider_used/model_used。

        （原 TestModelChangedLog.test_model_changed_marker_in_provider_marker 与本测试
        同一 marker 扫描逻辑、仅分别断言 model 字段与 provider/chain_index 字段——
        审查后合并为对象链 config 一次扫描全断言。）
        """
        config = object_chain_config([
            {"provider": "inferaiapi.com", "model": "deepseek-v4-flash"},
            {"provider": "bigmodel.cn",    "model": "glm-5.3-flash"},
        ])
        runner = make_runner(tmp_path, config)
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"
        # _run_agent 契约为 5 元组 (output, turns, session_id, usage_info,
        # stall_latency)——旧宽度桩会在解包处 ValueError→被 attempt 循环吞掉
        # 走重试耗尽路径（宽度契约由 tests/test_run_agent_call_site_arity.py 钉死）
        runner._run_agent = MagicMock(return_value=(
            "ok", 1, "sess",
            {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            {"rounds": 1, "stalls": 0, "max": 0.3}))
        result = runner.run_implementer("s")
        assert result.provider_used == "inferaiapi.com"
        assert result.model_used == "deepseek-v4-flash"
        # run jsonl 含 provider_marker，指明元素级 model 与 chain_index=0
        runs = tmp_path / ".fenix" / "runs"
        marker = None
        for f in runs.glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                e = json.loads(line)
                if e.get("type") == "provider_marker":
                    marker = e
        assert marker is not None
        assert marker["provider"] == "inferaiapi.com"
        assert marker["model"] == "deepseek-v4-flash"
        assert marker["chain_index"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# improve-failover-model-mapping-ui：跨模型切换留痕 (design D3)
# ═══════════════════════════════════════════════════════════════════════════

class TestModelChangedLog:
    # 跨模型链 / 同模型链（provider 变 model 不变）两形态共用同一 stub 与断言骨架
    CHAINS = [
        pytest.param(
            [{"provider": "inferaiapi.com", "model": "deepseek-v4-flash"},
             {"provider": "bigmodel.cn",    "model": "glm-5.3-flash"}],
            True, id="cross-model"),
        pytest.param(
            [{"provider": "inferaiapi.com", "model": "same-model"},
             {"provider": "aliyun",         "model": "same-model"}],
            False, id="same-model"),
    ]

    @pytest.mark.parametrize("chain,expect_model_changed", CHAINS)
    def test_model_changed_scoped_to_model_change(self, tmp_path, monkeypatch,
                                                  chain, expect_model_changed):
        """provider 切换日志恒含 provider switched；model_changed 标记仅在跨模型
        切换时出现（improve-failover-model-mapping-ui D3）。

        （原 test_cross_model_switch_appends_model_changed 与
        test_same_model_no_model_changed 同一 stub 骨架、仅链形态与反向断言不同——
        审查后合并为参数化，断言逐条保留。）
        """
        config = object_chain_config(chain)
        runner = make_runner(tmp_path, config)
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = tmp_path / "wt"

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None, spec_name=None,
                            agent_type=None, task_progress_snapshot=None):
            # 首候选失败 → 触发链前进到次候选
            if "a.com" in env_overrides.get("ANTHROPIC_BASE_URL", ""):
                raise RuntimeError("unrecognized_model")
            return ("ok", 1, "sess", {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "cost_usd": None})

        runner._run_agent = fake_run_agent
        runner._extract_session_id = MagicMock(return_value="sess")
        runner.run_implementer("s")
        # 两个场景都包含 provider switched
        assert runner.logger.has("provider switched")
        if expect_model_changed:
            # 跨模型：日志含 model_changed 标记，指明旧→新模型名
            assert runner.logger.has(
                "model_changed: deepseek-v4-flash→glm-5.3-flash")
        else:
            # 同模型：不含 model_changed 标记（模型名未变）。断言用真实日志格式
            # "model_changed: "（runner.py: " — model_changed: {old}→{new}"）而非裸
            # 子串——裸 "model_changed" 会误命中 pytest 按测试名截断生成的
            # tmp_path/worktree 目录名（test_model_changed_scoped_to_m0），假失败。
            assert not runner.logger.has("model_changed: ")


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
            runner._provider_circuit._record_daily_provider_attempt("aliyun")
        warns = [m for lvl, m in runner.logger.records if lvl == "warning"
                 and "daily attempts" in m]
        assert len(warns) == 1
        assert runner._daily_provider_attempts["aliyun"] == 5

    def test_no_warn_under_threshold(self, tmp_path):
        runner = make_runner(tmp_path, {})
        for _ in range(PROVIDER_DAILY_ATTEMPTS_WARN - 1):
            runner._provider_circuit._record_daily_provider_attempt("aliyun")
        warns = [m for lvl, m in runner.logger.records if lvl == "warning"
                 and "daily attempts" in m]
        assert warns == []


class TestRatelimitRedispatch:
    """429 打死 run 的自动重派（add-code-review-concurrency-and-429-resilience，task 5.4）。

    覆盖：429 终态登记重派意图（provider 限流冷却 + run jsonl 标注）/ 同 run
    幂等不重复登记 / 非 429 失败不触发 / 消费侧冷却到期以原 manifest 重调
    run_code_review 一次 / 重派超上限走既有失败收场不再重派 / 重派 run 自身
    manifest 与 jsonl 均标注重派缘由。
    """

    REAL_429 = (
        "API Error: Request rejected (429) · "
        "[1302][您的账户已达到速率限制，请您控制请求频率]"
    )

    # ── 登记侧（runner._ratelimit_redispatch_on_terminal） ──────────────

    @staticmethod
    def _mk_run(tmp_path, run_id="run-a"):
        rdir = tmp_path / ".fenix" / "runs"
        rdir.mkdir(parents=True, exist_ok=True)
        f = rdir / f"{run_id}.jsonl"
        f.write_text(json.dumps({"type": "run_start", "run_id": run_id}) + "\n",
                     encoding="utf-8")
        return f

    def test_terminal_429_registers_intent_with_jsonl_marker(self, tmp_path):
        from core.agent_runner.provider_circuit import (
            PROVIDER_RATELIMIT_COOLDOWN_SECONDS,
            RATELIMIT_REDISPATCH_MAX,
        )

        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        run_file = self._mk_run(tmp_path)
        intent = runner._ratelimit_redispatch_on_terminal(
            run_id="run-a", error=self.REAL_429,
            provider_name="inferaiapi.com", spec_name="code-review")
        assert intent is not None
        assert intent["reason"] == "429 ratelimit"
        assert intent["provider"] == "inferaiapi.com"
        assert intent["run_id"] == "run-a"
        assert RATELIMIT_REDISPATCH_MAX == 1
        assert intent["max_redispatches"] == RATELIMIT_REDISPATCH_MAX
        # 冷却到期时刻须在未来（消费侧据此延迟投递）
        assert intent["cooldown_until_epoch"] > time.time()
        # ① provider 进限流冷却（复用 switch 冷却通道与候选跳过语义）
        assert runner._provider_circuit.is_switch_cooldown("inferaiapi.com")
        st_until = runner._provider_circuit.provider_circuits[
            "inferaiapi.com"]["switch_cooldown_until"]
        assert st_until > 0
        assert (st_until - runner._provider_circuit._pm._now()) == pytest.approx(
            PROVIDER_RATELIMIT_COOLDOWN_SECONDS, abs=5.0)
        # ② run jsonl 标注重派缘由
        rows = [json.loads(l) for l in run_file.read_text(encoding="utf-8").splitlines()]
        markers = [r for r in rows if r.get("type") == "ratelimit_redispatch"]
        assert len(markers) == 1
        assert markers[0]["run_id"] == "run-a"
        assert markers[0]["spec"] == "code-review"
        assert markers[0]["cooldown_until_epoch"] == pytest.approx(
            intent["cooldown_until_epoch"])

    def test_duplicate_intent_same_run_is_idempotent(self, tmp_path):
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        run_file = self._mk_run(tmp_path)
        first = runner._ratelimit_redispatch_on_terminal(
            run_id="run-a", error=self.REAL_429,
            provider_name="inferaiapi.com", spec_name="code-review")
        assert first is not None
        second = runner._ratelimit_redispatch_on_terminal(
            run_id="run-a", error=self.REAL_429,
            provider_name="inferaiapi.com", spec_name="code-review")
        assert second is None  # 已登记 → 不重复登记
        rows = [json.loads(l) for l in run_file.read_text(encoding="utf-8").splitlines()]
        assert sum(1 for r in rows if r.get("type") == "ratelimit_redispatch") == 1

    def test_non_ratelimit_error_returns_none(self, tmp_path):
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        run_file = self._mk_run(tmp_path, "run-c")
        intent = runner._ratelimit_redispatch_on_terminal(
            run_id="run-c", error="API Error: 500 internal server error",
            provider_name="inferaiapi.com", spec_name="code-review")
        assert intent is None
        assert runner._ratelimit_redispatch_on_terminal(
            run_id="run-c", error="", provider_name="inferaiapi.com") is None
        rows = [json.loads(l) for l in run_file.read_text(encoding="utf-8").splitlines()]
        assert not any(r.get("type") == "ratelimit_redispatch" for r in rows)

    # ── 消费侧（admin_monitor._schedule/_consume_ratelimit_redispatch） ──

    @staticmethod
    def _mk_monitor():
        import threading

        from core.admin_monitor import AdminMonitor

        mon = AdminMonitor.__new__(AdminMonitor)
        mon.logger = FakeLogger()
        mon._code_review_lock = threading.Lock()
        mon._code_review_in_flight = False
        mon._code_review_executor = None
        mon._code_review_ratelimit_redispatches = 0
        mon._code_review_redispatch_timer = None
        return mon

    @staticmethod
    def _intent(run_id="run-a", epoch=None):
        return {
            "reason": "429 ratelimit",
            "provider": "inferaiapi.com",
            "run_id": run_id,
            "cooldown_until": "2026-09-24T00:00:00+00:00",
            "cooldown_until_epoch": epoch if epoch is not None else time.time() - 1,
            "max_redispatches": 1,
        }

    def test_consume_redispatches_once_with_original_manifest(self):
        mon = self._mk_monitor()
        calls = []

        def fake_run(manifest, review_kind=None, window_start=None, scope=None,
                     redispatch_of=None):
            calls.append({
                "manifest": list(manifest),
                "review_kind": review_kind,
                "window_start": window_start,
                "scope": scope,
                "redispatch_of": redispatch_of,
            })
            return MagicMock(run_id="run-b", inserted=0, updated=0,
                             resolved=0, shards=1, error="")

        mon.agent_runner = MagicMock()
        mon.agent_runner.run_code_review.side_effect = fake_run
        # 冷却到期时刻在近未来：先证「冷却期内 MUST NOT 重派」，再等 Timer
        # 到期触发（delay=0 会与测试抢跑——消费侧触发即摘句柄）
        mon._schedule_ratelimit_redispatch(
            manifest=["core/a.py", "core/b.py"], review_kind="manual_full",
            window_start=None, scope="full",
            intent=self._intent(epoch=time.time() + 0.3))
        timer = mon._code_review_redispatch_timer
        assert timer is not None
        assert calls == []  # 冷却期内未重派
        timer.join(timeout=5)
        assert not timer.is_alive()
        # 登记即占额 + 消费后单飞复位
        assert mon._code_review_ratelimit_redispatches == 1
        assert mon._code_review_in_flight is False
        # 重调一次、且仅一次：原 manifest / 原 review_kind / 原 scope + redispatch_of
        assert len(calls) == 1
        assert calls[0]["redispatch_of"] == "run-a"
        assert calls[0]["manifest"] == ["core/a.py", "core/b.py"]
        assert calls[0]["review_kind"] == "manual_full"
        assert calls[0]["scope"] == "full"

    def test_redispatch_beyond_max_takes_existing_failure_path(self):
        from core.agent_runner.provider_circuit import RATELIMIT_REDISPATCH_MAX

        mon = self._mk_monitor()
        calls = []
        mon.agent_runner = MagicMock()
        mon.agent_runner.run_code_review.side_effect = \
            lambda *a, **k: calls.append(a)
        # 本 monitor 生命周期内已重派过 → 达上限，按既有失败路径收场
        mon._code_review_ratelimit_redispatches = RATELIMIT_REDISPATCH_MAX
        mon._schedule_ratelimit_redispatch(
            manifest=["core/a.py"], review_kind="manual_full",
            window_start=None, scope="full", intent=self._intent())
        assert mon._code_review_redispatch_timer is None  # 未排程
        assert calls == []  # run_code_review 未被再调
        assert mon.logger.has("已达上限")

    # ── 重派 run 自身的缘由标注（run_code_review(redispatch_of=...)） ────

    def test_redispatch_run_marks_manifest_and_jsonl(self, tmp_path):
        from core.agent_runner import maintenance_runs as mr

        run_id = "code-review-1790217000"
        runner = type("R", (), {})()
        runner.project_root = tmp_path
        runner.config = {}
        runner.logger = None
        runner._unique_code_review_run_id = lambda: run_id
        runner._build_prompt = lambda *a, **k: "PROMPT"
        runner._get_agent_model_assignment = lambda name: None
        runner._get_admin_model = lambda: "test-model"
        runner._extract_usage_info = lambda x: {}
        runner._accumulate_code_review_tokens = lambda rid, usage: None
        runner._read_code_review_out = lambda project_root, rid: mr._read_code_review_out(
            runner, project_root, rid)

        def _boom(*a, **k):
            raise RuntimeError(self.REAL_429)

        runner._run_agent = _boom
        # runs 目录生产恒存在（append_run_line 不建目录），tmp 里自建
        (tmp_path / ".fenix" / "runs").mkdir(parents=True)
        result = mr.run_code_review(
            runner, ["core/a.py"], "manual_full", redispatch_of="run-a")
        assert result.success is False
        assert result.ratelimit_redispatch is None  # 桩 runner 无登记方法 → 意图缺位
        # manifest JSON 标注重派缘由
        manifest = json.loads(
            (tmp_path / ".fenix" / "code-review" / f"manifest-{run_id}.json")
            .read_text(encoding="utf-8"))
        assert manifest["redispatch_of"] == "run-a"
        # run jsonl 启动即标注重派缘由
        rf = tmp_path / ".fenix" / "runs" / f"{run_id}.jsonl"
        rows = [json.loads(l) for l in rf.read_text(encoding="utf-8").splitlines()]
        assert any(
            r.get("type") == "ratelimit_redispatch" and r.get("redispatch_of") == "run-a"
            for r in rows)


class TestRatelimitAttributionDualSource:
    """429 归因双源（evo-add-code-review-ratelimit-resume 1.1，task 5.1）。

    事故基线（code-review-1790574672）：429 文案只在 result 事件，stderr 经
    _denoise_stderr 降噪后只剩 "Exit code: 1"——文本分类恒 False，意图不登记、
    provider 不冷却、run 无标注（归档 jsonl 无 ratelimit_redispatch 行）。
    归因优先级：文本分类 → result 事件（非零退出分支挂异常的富归因 → run
    jsonl result 事件兜底）。
    """

    NOISE_STDERR = "Exit code: 1"
    REAL_429 = TestRatelimitRedispatch.REAL_429

    @staticmethod
    def _mk_run(tmp_path, run_id, extra_events=()):
        rdir = tmp_path / ".fenix" / "runs"
        rdir.mkdir(parents=True, exist_ok=True)
        f = rdir / f"{run_id}.jsonl"
        lines = [json.dumps({"type": "run_start", "run_id": run_id})]
        lines.extend(json.dumps(ev) for ev in extra_events)
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f

    def test_api_error_status_429_registers_intent(self, tmp_path):
        """stderr 全噪音 + result 事件 api_error_status=429 → 意图仍登记且
        provider 进冷却（spec「stderr 全噪音仍归因」）。"""
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        run_file = self._mk_run(tmp_path, "run-d")
        intent = runner._ratelimit_redispatch_on_terminal(
            run_id="run-d", error=self.NOISE_STDERR,
            provider_name="inferaiapi.com", spec_name="code-review",
            api_error_status=429, result_text="")
        assert intent is not None
        assert intent["reason"] == "429 ratelimit"
        assert intent["run_id"] == "run-d"
        # provider 进限流冷却（消费侧 300 秒延迟重投递的依据）
        assert runner._provider_circuit.is_switch_cooldown("inferaiapi.com")
        # run jsonl 标注重派缘由（告警面板取证可见）
        rows = [json.loads(l) for l in run_file.read_text(encoding="utf-8").splitlines()]
        assert any(r.get("type") == "ratelimit_redispatch" for r in rows)

    def test_result_text_signature_registers_intent(self, tmp_path):
        """api_error_status 缺失但 result 文本命中限流签名 → 同样归因。"""
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        self._mk_run(tmp_path, "run-e")
        intent = runner._ratelimit_redispatch_on_terminal(
            run_id="run-e", error=self.NOISE_STDERR,
            provider_name="inferaiapi.com", spec_name="code-review",
            api_error_status=None, result_text=self.REAL_429)
        assert intent is not None

    def test_string_api_error_status_parses_to_429(self, tmp_path):
        """result 事件 api_error_status 以文本形态落盘（"429"）→ 可解析归因。"""
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        self._mk_run(tmp_path, "run-f")
        intent = runner._ratelimit_redispatch_on_terminal(
            run_id="run-f", error=self.NOISE_STDERR,
            provider_name="inferaiapi.com", spec_name="code-review",
            api_error_status="429", result_text="")
        assert intent is not None

    def test_jsonl_result_event_fallback_registers_intent(self, tmp_path):
        """富归因未挂载（历史调用方路径）→ 回退读 run jsonl 末个 result 事件。"""
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        run_file = self._mk_run(tmp_path, "run-g", extra_events=[
            {"type": "assistant", "message": "working"},
            {"type": "result", "api_error_status": 429,
             "result": "API Error: Request rejected (429)"},
        ])
        intent = runner._ratelimit_redispatch_on_terminal(
            run_id="run-g", error=self.NOISE_STDERR,
            provider_name="inferaiapi.com", spec_name="code-review")
        assert intent is not None
        rows = [json.loads(l) for l in run_file.read_text(encoding="utf-8").splitlines()]
        assert any(r.get("type") == "ratelimit_redispatch" for r in rows)

    def test_all_sources_miss_returns_none(self, tmp_path):
        """全源未命中（普通失败）→ 不登记、不冷却、不标注。"""
        runner = make_runner(tmp_path, chain_config("inferaiapi.com"))
        run_file = self._mk_run(tmp_path, "run-h", extra_events=[
            {"type": "result", "api_error_status": 500,
             "result": "API Error: 500 internal server error"},
        ])
        intent = runner._ratelimit_redispatch_on_terminal(
            run_id="run-h", error=self.NOISE_STDERR,
            provider_name="inferaiapi.com", spec_name="code-review")
        assert intent is None
        assert not runner._provider_circuit.is_switch_cooldown("inferaiapi.com")
        rows = [json.loads(l) for l in run_file.read_text(encoding="utf-8").splitlines()]
        assert not any(r.get("type") == "ratelimit_redispatch" for r in rows)


class TestRatelimitShardedResume:
    """分片续跑（evo-add-code-review-ratelimit-resume 3.1/3.2/3.3，task 5.1）。

    事故基线：270 文件级全仓审查死于 429 时原 run 已落 4 片（自述 16 片），
    既有重派消费复用原 manifest 全量重跑（重烧约 14 美元）。重派剃余＝原
    清单 − 已落分片覆盖（本组以 6 文件缩比复刻该形状，剃余只删不改序）；
    全仓快照核销以「本轮累计覆盖 = 完整 manifest」为解锁门，未覆盖完整维持
    抢救红线（宁锁勿白洗）。
    """

    ORIGIN_FILES = [f"core/f{i}.py" for i in range(6)]

    def _mk_origin(self, proot, run_id="run-a", covered=()):
        crdir = proot / ".fenix" / "code-review"
        crdir.mkdir(parents=True, exist_ok=True)
        (crdir / f"manifest-{run_id}.json").write_text(
            json.dumps({"files": list(self.ORIGIN_FILES),
                        "review_kind": "manual_full"}),
            encoding="utf-8")
        (crdir / f"out-{run_id}.jsonl").write_text(
            "".join(json.dumps({"file": f, "findings": []}) + "\n"
                    for f in covered),
            encoding="utf-8")
        # runs 目录生产恒存在（run_start jsonl 落点），tmp 里自建
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _mk_monitor(proot):
        import threading

        from core.admin_monitor import AdminMonitor

        mon = AdminMonitor.__new__(AdminMonitor)
        mon.logger = FakeLogger()
        mon.project_root = proot
        mon._code_review_lock = threading.Lock()
        mon._code_review_in_flight = False
        mon._code_review_executor = None
        mon._code_review_ratelimit_redispatches = 0
        mon._code_review_redispatch_timer = None
        return mon

    def test_consume_shaves_manifest_to_remaining(self, tmp_path):
        """重派剃余：run_code_review 只收剩余文件（原清单 − 已落分片覆盖），
        redispatch_of 链路保留。"""
        mon = self._mk_monitor(tmp_path)
        self._mk_origin(tmp_path, covered=self.ORIGIN_FILES[:2])
        calls = []

        def fake_run(manifest, review_kind=None, window_start=None, scope=None,
                     redispatch_of=None):
            calls.append({"manifest": list(manifest),
                          "redispatch_of": redispatch_of})
            return MagicMock(run_id="run-b", inserted=0, updated=0,
                             resolved=0, shards=1, error="")

        mon.agent_runner = MagicMock()
        mon.agent_runner.run_code_review.side_effect = fake_run
        mon._consume_ratelimit_redispatch(
            list(self.ORIGIN_FILES), "manual_full", None, "full", "run-a")
        assert len(calls) == 1
        assert calls[0]["manifest"] == self.ORIGIN_FILES[2:], "剃掉已落账 f0/f1"
        assert calls[0]["redispatch_of"] == "run-a", "链路保留"

    def test_consume_full_covered_skips_redispatch(self, tmp_path):
        """原 run 已全覆盖（如 429 死于收尾段）→ 无需重派，配额不退（防风暴）。"""
        mon = self._mk_monitor(tmp_path)
        self._mk_origin(tmp_path, covered=self.ORIGIN_FILES)
        calls = []
        mon.agent_runner = MagicMock()
        mon.agent_runner.run_code_review.side_effect = \
            lambda *a, **k: calls.append(a)
        mon._consume_ratelimit_redispatch(
            list(self.ORIGIN_FILES), "manual_full", None, "full", "run-a")
        assert calls == []
        assert mon._code_review_redispatch_timer is None, "未排程重派"
        assert mon.logger.has("累计覆盖已完整")

    # ── 核销门（3.3：累计覆盖完整前 MUST NOT 核销） ─────────────────────

    def _mk_success_runner(self, proot, run_id, artifact_rows):
        from core.agent_runner import maintenance_runs as mr

        runner = type("R", (), {})()
        runner.project_root = proot
        runner.config = {}
        runner.logger = FakeLogger()
        runner._unique_code_review_run_id = lambda: run_id
        runner._build_prompt = lambda *a, **k: "PROMPT"
        runner._get_agent_model_assignment = lambda name: None
        runner._get_admin_model = lambda: "test-model"
        runner._extract_usage_info = lambda x: {}
        runner._accumulate_code_review_tokens = lambda rid, usage: None
        runner._read_code_review_out = lambda project_root, rid: mr._read_code_review_out(
            runner, project_root, rid)

        def _run_agent(*a, **k):
            # agent 行为：本轮产物（逐文件结果行）在 run 途中落盘
            crdir = proot / ".fenix" / "code-review"
            (crdir / f"out-{run_id}.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in artifact_rows),
                encoding="utf-8")
            return "OUT", 1, "sess", {}, {"rounds": 1, "stalls": 0, "max": 0.3}

        runner._run_agent = _run_agent
        return runner

    @staticmethod
    def _seed_open(proot, file_):
        from core.code_review import upsert_findings

        upsert_findings(proot, [{
            "file": file_, "category": "maintainability",
            "title": "存量未被本轮观测。", "severity": "minor",
            "description": "d", "suggestion": "s", "evidence": "e",
        }], review_id="seed", review_kind="manual_full")

    @staticmethod
    def _finding(file_):
        return {"file": file_, "findings": [
            {"line": 1, "severity": "minor", "category": "maintainability",
             "title": f"{file_} 本轮新发现。", "description": "d",
             "suggestion": "s", "evidence": "e"}]}

    def test_writeoff_locked_when_cumulative_coverage_partial(self, tmp_path):
        """剃余重派 run 只覆盖部分 → 累计覆盖 ≠ 完整 manifest → 快照核销锁定
        （存量 open 保持，防部分覆盖白洗——事故红线）。"""
        from core.agent_runner import maintenance_runs as mr
        from core.code_review import read_items

        self._mk_origin(tmp_path, covered=self.ORIGIN_FILES[:2])
        self._seed_open(tmp_path, "core/f5.py")
        runner = self._mk_success_runner(
            tmp_path, "run-b", [self._finding("core/f2.py")])
        result = mr.run_code_review(
            runner, ["core/f2.py"], "manual_full", redispatch_of="run-a")
        assert result.success is True
        assert result.resolved == 0, "未覆盖完整 MUST NOT 核销"
        assert runner.logger.has("核销锁定")
        items = read_items(tmp_path)
        seeded = [r for r in items.values() if r.get("file") == "core/f5.py"]
        assert seeded and seeded[0]["status"] == "open"

    def test_writeoff_unlocked_when_cumulative_coverage_complete(self, tmp_path):
        """本轮补齐全部剩余文件 → 累计覆盖 = 完整 manifest → 核销解锁执行
        （本轮未再观测的存量 open 置 resolved）。"""
        from core.agent_runner import maintenance_runs as mr
        from core.code_review import read_items

        self._mk_origin(tmp_path, covered=self.ORIGIN_FILES[:2])
        self._seed_open(tmp_path, "core/f5.py")
        remaining = self.ORIGIN_FILES[2:]
        runner = self._mk_success_runner(
            tmp_path, "run-b", [self._finding(f) for f in remaining])
        result = mr.run_code_review(
            runner, remaining, "manual_full", redispatch_of="run-a")
        assert result.success is True
        assert result.resolved == 1, "累计覆盖完整 → 核销解锁"
        assert runner.logger.has("核销解锁")
        items = read_items(tmp_path)
        seeded = [r for r in items.values()
                  if r.get("file") == "core/f5.py"
                  and r.get("review_id") == "seed"]
        assert seeded and seeded[0]["status"] == "resolved"
