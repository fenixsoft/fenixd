"""evo-sigterm-source-tracking-cooldown：CLI 子进程信号死法来源跟踪与冷却测试。

覆盖 tasks 2.1-2.6：
- 2.1 外部信号致死（143/-9，无 shutdown 标记）→ 错误含 [signal-kill: …] 标签、
      不归 [provider-transient]、不记全局瞬断指纹（2026-09-16 两个 admin run
      形态回放；信号发出者不可考 → unknown 形态亦合规）；
- 2.2 shutting_down / 产物 interrupted → 维持 [shutdown-interrupted]（不回归既有守卫）；
- 2.3 143/-9 连续达阈值 → 该 spec 冷却启动、冷却期不重试、到期自动恢复，
      且全局瞬断熔断未被触发（is_global_transient_break 为假）；
- 2.4 provider 网络抖动瞬态 → 既有退避不变；
- 2.5 产物硬门失败 → 不记全局瞬断指纹；结构类仍走原地退避重试
      （transient_retry 事件保留），任务完成度类不带 [provider-transient] 标签；
- 2.6 框架自身强杀（supervision 超时/轮次上限，returncode=-9 且错误文本
      Timeout/Max turns）→ 不打信号标签、不计信号冷却。
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from tests.helpers import FakeLogger


def _make_runner(tmp_path: Path, config: dict | None = None) -> AgentRunner:
    """构造可驱动 _execute_agent 的最小 runner（test_agent_runner_gate 同款）。"""
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
    runner.__dict__["_v2_server_instance"] = MagicMock()
    runner._v2_server._v2_inject_env.return_value = {}
    runner.__dict__["_token_accountant_instance"] = MagicMock()
    runner._build_prompt = lambda *a, **k: "test prompt"
    (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return runner


def _standard_chain_config(agent_type: str = "implementer",
                           max_retries: int = 2) -> dict:
    """含单 provider 候选链的 config（transient 预算长度 1）。"""
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
            "max_retries": max_retries,
            "transient_backoff_schedule": "1",
        },
    }


def _usage_ok() -> dict:
    return {"input_tokens": 1, "output_tokens": 2,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "cost_usd": None}


def _sig_exc(rc: int, text: str | None = None) -> RuntimeError:
    """构造带 exit_code 属性的 RuntimeError（模拟 _run_claude 信号死法路径）。"""
    exc = RuntimeError(text or f"claude CLI failed: Exit code: {rc}")
    exc.exit_code = rc
    exc.stderr_lines = []
    exc.has_result = False
    return exc


def _wire_worktree(runner: AgentRunner, tmp_path: Path) -> Path:
    """装上可跑 _execute_agent 的 worktree mock，返回 worktree 路径。"""
    wt = tmp_path / "wt"
    wt.mkdir(parents=True)
    runner.worktree_manager = MagicMock()
    runner.worktree_manager.create.return_value = wt
    runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
    return wt


# ═══════════════════════════════════════════════════════════════════════════
# 2.1 外部信号致死 → 标签 / 不归瞬断 / 不记指纹
# ═══════════════════════════════════════════════════════════════════════════

class TestExternalSignalKillLabel:

    @pytest.mark.parametrize("rc,label", [
        (143, "[signal-kill: SIGTERM/143]"),
        (-9, "[signal-kill: SIGKILL/-9]"),
        (-15, "[signal-kill: SIGTERM/-15]"),
        (-7, "[signal-kill: unknown/-7]"),
    ], ids=["143-SIGTERM", "-9-SIGKILL", "-15-SIGTERM", "-7-unknown"])
    def test_signal_death_labeled_not_transient_no_fingerprint(
            self, tmp_path, monkeypatch, rc, label):
        """外部信号致死（143/-9/负信号，无 shutdown 标记）→ 错误含信号来源标签、
        不归 [provider-transient]、不记全局瞬断指纹（信号发出者不可考 → 标签
        如实带 returncode，unknown 形态亦合规）。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("implementer"))
        _wire_worktree(runner, tmp_path)
        runner._run_claude = lambda *a, **k: (_ for _ in ()).throw(
            _sig_exc(rc))

        result = runner._execute_agent("spec-x", "implementer", "run-sig-1")

        assert result.success is False
        assert label in (result.error or "")
        assert "[provider-transient]" not in (result.error or "")
        assert "[shutdown-interrupted]" not in (result.error or "")
        # 不记全局瞬断指纹 / 不触发全局瞬断熔断
        assert runner.is_global_transient_break_active() is False
        # 但计入 spec 维度信号冷却计数（外部信号致死进信号通道）
        assert runner._signal_kill_counts("spec-x") == 2  # max_retries=2 → 2 次


# ═══════════════════════════════════════════════════════════════════════════
# 2.2 shutting_down / 产物 interrupted → 维持 [shutdown-interrupted]
# ═══════════════════════════════════════════════════════════════════════════

class TestShutdownGuardUnchanged:

    def test_shutting_down_flag_keeps_guard(self, tmp_path, monkeypatch):
        """shutting_down 置位 → 维持 [shutdown-interrupted]（不回归既有守卫），
        且信号计数不计入（闭集先排除 daemon 关停）。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("implementer"))
        _wire_worktree(runner, tmp_path)
        runner.shutting_down = True
        runner._run_claude = lambda *a, **k: (_ for _ in ()).throw(
            _sig_exc(143))

        result = runner._execute_agent("spec-x", "implementer", "run-sig-2")

        assert result.success is False
        assert "[shutdown-interrupted]" in (result.error or "")
        assert "[signal-kill:" not in (result.error or "")
        assert runner._signal_kill_counts("spec-x") == 0

    def test_interrupted_marker_keeps_guard(self, tmp_path, monkeypatch):
        """产物 interrupted 标记存在 → 维持 [shutdown-interrupted] 守卫。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("implementer"))
        _wire_worktree(runner, tmp_path)
        # 预写 attempt run 产物含 interrupted 标记（liveness/shutdown 路径写入形态）
        attempt_file = tmp_path / ".fenix" / "runs" / "run-sig-3-a1.jsonl"
        attempt_file.write_text(
            json.dumps({"type": "interrupted", "reason": "daemon drain"}) + "\n",
            encoding="utf-8")
        runner._run_claude = lambda *a, **k: (_ for _ in ()).throw(
            _sig_exc(143))

        result = runner._execute_agent("spec-x", "implementer", "run-sig-3")

        assert result.success is False
        assert "[shutdown-interrupted]" in (result.error or "")
        assert "[signal-kill:" not in (result.error or "")
        assert runner._signal_kill_counts("spec-x") == 0


# ═══════════════════════════════════════════════════════════════════════════
# 2.3 信号死法连续达阈值 → spec 冷却启动 / 冷却期不重试 / 到期自动恢复
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalKillCooldown:

    def test_circuit_level_threshold_and_recovery(self, tmp_path, monkeypatch):
        """电路级：143/-9 连续达阈值 → 该 spec 冷却启动；到期自动恢复；
        全局瞬断熔断从未被触发（is_global_transient_break 为假）。"""
        runner = _make_runner(tmp_path)
        now = 1000.0
        monkeypatch.setattr(runner, "_now", lambda: now)

        assert runner.is_signal_kill_cooldown("spec-x", now=now) is False
        runner._record_signal_kill("spec-x", now=now)
        runner._record_signal_kill("spec-x", now=now)
        assert runner.is_signal_kill_cooldown("spec-x", now=now) is False
        assert runner._signal_kill_counts("spec-x") == 2
        # 第三次达阈值 → 冷却启动
        runner._record_signal_kill("spec-x", now=now)
        assert runner.is_signal_kill_cooldown("spec-x", now=now) is True
        assert runner._signal_kill_counts("spec-x") == 3
        # 全局瞬断熔断未被触发（信号冷却通道不得冻结全项目派发）
        assert runner.is_global_transient_break_active(now=now) is False
        assert runner.is_global_transient_break_active() is False
        # 冷却期内继续信号死法 → 仍处于冷却（不重置）
        runner._record_signal_kill("spec-x", now=now)
        assert runner.is_signal_kill_cooldown("spec-x", now=now) is True
        # 到期自动恢复：计数清零
        until = runner.signal_kill_cooldown_until("spec-x")
        assert until > now
        monkeypatch.setattr(runner, "_now", lambda: until + 1)
        assert runner.is_signal_kill_cooldown("spec-x", now=until + 1) is False
        assert runner._signal_kill_counts("spec-x") == 0

    def test_integration_threshold_reaches_cooldown(self, tmp_path, monkeypatch):
        """集成：_execute_agent 连续 3 次 143 → 计数 3 → 该 spec 冷却启动、
        冷却期不重试（闸门 is_signal_kill_cooldown 为真）、全局瞬断熔断未触发。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(
            tmp_path, _standard_chain_config("implementer", max_retries=3))
        _wire_worktree(runner, tmp_path)
        runner._run_claude = lambda *a, **k: (_ for _ in ()).throw(
            _sig_exc(143))

        result = runner._execute_agent("spec-x", "implementer", "run-sig-4")

        assert result.success is False
        assert "[signal-kill: SIGTERM/143]" in (result.error or "")
        assert runner._signal_kill_counts("spec-x") == 3
        # 该 spec 冷却启动（dispatch 闸门据此跳过重派，不耗预算不起进程）
        assert runner.is_signal_kill_cooldown("spec-x") is True
        # 全局瞬断熔断未被触发
        assert runner.is_global_transient_break_active() is False
        # 到期自动恢复
        until = runner.signal_kill_cooldown_until("spec-x")
        monkeypatch.setattr(runner, "_now", lambda: until + 1)
        assert runner.is_signal_kill_cooldown("spec-x") is False
        assert runner._signal_kill_counts("spec-x") == 0

    def test_success_resets_signal_count(self, tmp_path, monkeypatch):
        """成功收工重置信号死法连续计数（连续链被打断）。"""
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = _wire_worktree(runner, tmp_path)
        runner.worktree_manager.cleanup.return_value = None
        # 先制造一次信号死法计数
        runner._record_signal_kill("spec-x")
        assert runner._signal_kill_counts("spec-x") == 1

        from core.agent_runner.prompt_builder import planner_result_path
        result_path = planner_result_path(tmp_path, "spec-x", "planner-judge")

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps({"status": "verified", "summary": "ok"}),
                encoding="utf-8")
            return ("done", 1, "sess-ok", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-sig-5")
        assert result.success is True
        assert runner._signal_kill_counts("spec-x") == 0


# ═══════════════════════════════════════════════════════════════════════════
# 2.4 provider 网络抖动瞬态 → 既有退避不变
# ═══════════════════════════════════════════════════════════════════════════

class TestNetworkTransientUnchanged:

    def test_network_transient_backoff_unchanged(self, tmp_path, monkeypatch):
        """provider 网络抖动瞬态（连接类，非信号死法）→ 既有退避不变：
        [provider-transient] 标签与原地退避重试照旧，信号通道不计数。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("implementer"))
        _wire_worktree(runner, tmp_path)

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            exc = RuntimeError("claude CLI failed: failed to connect: "
                               "connection refused")
            exc.exit_code = 1
            exc.stderr_lines = ["[claude-code:trace] x",
                                "failed to connect: connection refused"]
            exc.has_result = False
            raise exc

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "implementer", "run-sig-6")

        assert result.success is False
        # 瞬态照旧：错误带 [provider-transient] 前缀（原地退避通道标签）
        assert "[provider-transient]" in (result.error or "")
        # 非信号死法：信号通道零计数、零标签
        assert "[signal-kill:" not in (result.error or "")
        assert runner._signal_kill_counts("spec-x") == 0
        # 既有退避照旧：原地重试发生（预算 1 × 2 attempt = 4 次调用）
        assert calls["n"] == 4


# ═══════════════════════════════════════════════════════════════════════════
# 2.5 产物硬门失败 → 不记全局瞬断指纹；结构类保留退避；任务类不带标签
# ═══════════════════════════════════════════════════════════════════════════

class TestArtifactGateChannelIsolation:

    def test_structural_gate_keeps_retry_no_fingerprint(self, tmp_path,
                                                        monkeypatch):
        """结构类产物硬门失败（结果文件缺失，无前缀）→ 保留既有原地退避重试
        （transient_retry 事件保留、[provider-transient] 标签在），但不记全局
        瞬断指纹。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(
            tmp_path, _standard_chain_config("planner-judge"))
        _wire_worktree(runner, tmp_path)

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            return ("done", 1, "sess-gate", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-sig-7")

        assert result.success is False
        assert "结果文件缺失" in (result.error or "")
        # 结构类保留 [provider-transient] 标签与原地退避重试
        assert "[provider-transient]" in (result.error or "")
        assert calls["n"] == 4  # a1 + r1 + a2 + r1'（预算长度 1 × 2 attempt）
        # transient_retry 事件保留（reason=artifact_gate）
        events = []
        for suffix in ("-a1", "-a1-r1", "-a2", "-a2-r1"):
            f = tmp_path / ".fenix" / "runs" / f"run-sig-7{suffix}.jsonl"
            if f.is_file():
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        retries = [e for e in events if e.get("type") == "transient_retry"]
        assert retries, "结构类产物硬门失败应保留原地退避重试事件"
        assert all(e.get("reason") == "artifact_gate" for e in retries)
        # 不记全局瞬断指纹 / 不触发全局瞬断熔断
        assert runner.is_global_transient_break_active() is False

    def test_task_gate_failure_no_transient_label(self, tmp_path, monkeypatch):
        """任务完成度类（[task-gate]）失败 → 不带 [provider-transient] 标签、
        不进原地瞬态退避预算（无 transient_retry 事件）、不记全局瞬断指纹；
        重试由 attempt 层承担。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("implementer"))
        wt = tmp_path / "wt"
        (wt / "spec" / "changes" / "spec-x").mkdir(parents=True, exist_ok=True)
        (wt / "spec" / "changes" / "spec-x" / "tasks.md").write_text(
            "## 1. 阶段一\n\n- [ ] 1.1 任务一\n", encoding="utf-8")
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        result_path = wt / ".fenix-run-result.json"

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps({"status": "success", "completed_tasks": []}),
                encoding="utf-8")
            return ("done", 1, "sess-tg", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "implementer", "run-sig-8")

        assert result.success is False
        assert "[task-gate]" in (result.error or "")
        assert "[provider-transient]" not in (result.error or "")
        assert "[artifact-structural]" not in (result.error or "")
        # 不记全局瞬断指纹
        assert runner.is_global_transient_break_active() is False
        # 不进原地瞬态退避预算：无 transient_retry 事件；调用数 = attempt 数
        assert calls["n"] == 2  # max_retries=2 → 仅 attempt 层重试
        events = []
        for suffix in ("-a1", "-a2"):
            f = tmp_path / ".fenix" / "runs" / f"run-sig-8{suffix}.jsonl"
            if f.is_file():
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        assert not [e for e in events if e.get("type") == "transient_retry"]


# ═══════════════════════════════════════════════════════════════════════════
# 2.6 框架自身强杀（supervision 超时/轮次上限）→ 不打标签、不计冷却
# ═══════════════════════════════════════════════════════════════════════════

class TestFrameworkSelfKillExcluded:

    @pytest.mark.parametrize("text", [
        "claude CLI Timeout after 3600s — 硬上限 reached",
        "claude CLI Max turns (300) reached — evidence",
    ], ids=["timeout", "max-turns"])
    def test_framework_self_kill_no_label_no_count(self, tmp_path, monkeypatch,
                                                   text):
        """框架自身强杀（supervision 超时/轮次上限：returncode=-9 且错误文本
        Timeout/Max turns）→ 不打信号标签、不计信号冷却（框架自己强杀不得
        冷却链路）。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("implementer"))
        _wire_worktree(runner, tmp_path)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            exc = RuntimeError(text)
            # 真实路径异常不带 exit_code（timeout/turn_limit raise 无属性），
            # 此处显式带 -9 模拟 returncode 语义——错误文本排除仍须生效
            exc.exit_code = -9
            exc.stderr_lines = []
            exc.has_result = False
            raise exc

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "implementer", "run-sig-9")

        assert result.success is False
        assert "[signal-kill:" not in (result.error or "")
        assert runner._signal_kill_counts("spec-x") == 0
        # 亦不归 [provider-transient]（框架自身终止既不属于瞬断）
        assert "[provider-transient]" not in (result.error or "")


# ═══════════════════════════════════════════════════════════════════════════
# 标签纯函数单测
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalKillLabelFunction:

    def test_label_mapping(self):
        assert AgentRunner._signal_kill_label(143) == "[signal-kill: SIGTERM/143]"
        assert AgentRunner._signal_kill_label(130) == "[signal-kill: SIGINT/130]"
        assert AgentRunner._signal_kill_label(-9) == "[signal-kill: SIGKILL/-9]"
        assert AgentRunner._signal_kill_label(-15) == "[signal-kill: SIGTERM/-15]"
        assert AgentRunner._signal_kill_label(-7) == "[signal-kill: unknown/-7]"

    def test_non_signal_codes_return_none(self):
        assert AgentRunner._signal_kill_label(1) is None
        assert AgentRunner._signal_kill_label(0) is None
        assert AgentRunner._signal_kill_label(-1) == "[signal-kill: SIGHUP/-1]"
        assert AgentRunner._signal_kill_label(None) is None
