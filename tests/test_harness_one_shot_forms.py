"""add-harness-adapter-layer 4.3：一次性 spawn 收编后「同参数」替身验证。

收编后各点经 run_one_shot/claude_adapter spawn，替身捕获 argv 与收编前形态
逐元素相等断言（形态史实，git 主干平移基线）：

- 监督 judge（liveness._judge_liveness_once）：``claude -p --output-format
  json --model <admin 模型>``，stdin 传 prompt，env 不传（inherit）；
- 知识蒸馏（knowledge._spawn_and_wait）：``claude -p --permission-mode
  bypassPermissions``（无 --output-format），stdin 传 prompt；
- 知识回填（knowledge_backfill.default_spawn）：同蒸馏形态；
- 告警叙事（adjudication_narrative.default_channel）：``claude -p --model m``
  （4.2 起模型恒显式传递），stdin 传 prompt，超时/非零/空输出 fail-open
  返回 None 的触发行为一致；
- 项目简介（project_routes describe，argv 传输 ``claude -p <prompt>``）的
  prompt 恒等与 lane 形态由 tests/test_dashboard_api.py prompt 恒等断言覆盖
  （prompt_transport == "argv"），此处不重复。

替身打桩点：全局 ``subprocess.Popen``——run_one_shot 在 one_shot 模块内调用
时解析 subprocess.Popen（同一模块对象），与收编前 liveness/narrative 测试
同一打桩面；蒸馏经 DistillManager(spawn=...) 既有 Popen 级注入缝。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.adjudication_narrative as adj
from core.adjudication_narrative import default_channel
from core.agent_runner.maintenance_runs import DEFAULT_GATEWAY_MODEL
from core.knowledge import DistillManager
from core.knowledge_backfill import default_spawn


# ── 替身 ────────────────────────────────────────────────

class _OutProc:
    """成功路径 fake：returncode 可配，stdout/stderr 固定。"""

    pid = 2**24  # 假 pid：清场路径 getpgid 落 ProcessLookupError 静默

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout_txt = stdout
        self.stderr_txt = stderr
        self.returncode = returncode
        self.stdin = self.stdout = self.stderr = None

    def communicate(self, payload=None, timeout=None):
        return self.stdout_txt, self.stderr_txt


class _TimeoutProc:
    """超时路径 fake：communicate/wait 恒超时（清场两段式全走一遍）。"""

    pid = 2**24
    returncode = None
    stdin = stdout = stderr = None

    def communicate(self, payload=None, timeout=None):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)


class _QuietLogger:
    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


def _bare_runner(tmp_path):
    """最小 AgentRunner（同 tests/test_run_lifecycle_governance.bare_runner）。"""
    from core.agent_runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = tmp_path
    runner.logger = _QuietLogger()
    runner._running_agents = {}
    return runner


# ── 监督 judge 形态 ─────────────────────────────────────

class TestJudgeForm:
    def test_argv_matches_pre_migration(self, tmp_path, monkeypatch):
        seen = {}

        def fake_popen(cmd, **kwargs):
            seen["argv"] = cmd
            seen["kwargs"] = kwargs
            return _OutProc(
                stdout=json.dumps(
                    {"result": json.dumps({"verdict": "advancing", "evidence": "ok"})}
                )
            )

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        runner = _bare_runner(tmp_path)
        verdict = runner._liveness._judge_liveness_once({}, "s1", "r1", 120)
        assert verdict["verdict"] == "advancing"
        # admin.agent_model 未配置 → _get_admin_model 兜底框架默认（与收编前
        # 同源），--model 恒在
        assert seen["argv"] == [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--model",
            DEFAULT_GATEWAY_MODEL,
        ]
        # inherit env 口径（现状 Popen 不传 env）
        assert "env" not in seen["kwargs"]

    def test_configured_admin_model_lands_in_argv(self, tmp_path, monkeypatch):
        seen = {}

        def fake_popen(cmd, **kwargs):
            seen["argv"] = cmd
            return _OutProc(stdout="没有 JSON 的输出")

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        runner = _bare_runner(tmp_path)
        runner.config = {"admin": {"agent_model": "glm-9"}}
        verdict = runner._liveness._judge_liveness_once({}, "s1", "r1", 120)
        assert verdict["verdict"] == "stagnant"  # unparseable → stagnant
        assert "liveness judge unavailable" in verdict["evidence"]
        assert seen["argv"] == [
            "claude", "-p", "--output-format", "json", "--model", "glm-9",
        ]

    def test_timeout_returns_stagnant_with_terminated_marker(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: _TimeoutProc())
        runner = _bare_runner(tmp_path)
        verdict = runner._liveness._judge_liveness_once({}, "s1", "r1", 3)
        assert verdict["verdict"] == "stagnant"
        assert "judge timed out after 3s" in verdict["evidence"]
        assert "claude process group terminated" in verdict["evidence"]


# ── 知识蒸馏形态（DistillManager spawn 注入缝）──────────

class TestDistillForm:
    def test_argv_matches_pre_migration(self, tmp_path):
        seen = {}

        def spawn(cmd, cwd):
            seen["argv"] = cmd
            seen["cwd"] = cwd
            return _OutProc()

        ok, err = DistillManager(spawn=spawn)._spawn_and_wait(tmp_path, "提示词")
        assert (ok, err) == (True, None)
        assert seen["argv"] == [
            "claude", "-p", "--permission-mode", "bypassPermissions",
        ]
        assert seen["cwd"] == str(tmp_path)

    def test_nonzero_exit_maps_to_error_with_stderr_tail(self, tmp_path):
        def spawn(cmd, cwd):
            return _OutProc(stderr="boom-tail", returncode=2)

        ok, err = DistillManager(spawn=spawn)._spawn_and_wait(tmp_path, "提示词")
        assert ok is False
        assert "exit=2" in err and "boom-tail" in err


# ── 知识回填形态 ────────────────────────────────────────

class TestBackfillForm:
    def test_argv_matches_pre_migration(self, tmp_path, monkeypatch):
        seen = {}

        def fake_popen(cmd, **kwargs):
            seen["argv"] = cmd
            seen["kwargs"] = kwargs
            return _OutProc(stdout="回填完成")

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        out = default_spawn(tmp_path)("回填提示词", "run-1")
        assert out == "回填完成"
        assert seen["argv"] == [
            "claude", "-p", "--permission-mode", "bypassPermissions",
        ]
        # clean env 口径经 SpawnSpec.env 显式传入（现状 _build_spawn_env 同形）
        assert "env" in seen["kwargs"]

    def test_timeout_raises_bounded_runtime_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: _TimeoutProc())
        with pytest.raises(RuntimeError, match="回填 run run-t.*超时"):
            default_spawn(tmp_path)("p", "run-t")


# ── 告警叙事通道：argv 形态 + fail-open 触发行为 ────────

class TestNarrativeChannelForm:
    def test_argv_carries_explicit_model(self, tmp_path, monkeypatch):
        seen = {}

        def fake_popen(cmd, **kwargs):
            seen["argv"] = cmd
            seen["kwargs"] = kwargs
            return _OutProc(stdout="  正文输出\n")

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        out = default_channel("你好", "glm-9", 30)
        assert out == "正文输出"
        assert seen["argv"] == ["claude", "-p", "--model", "glm-9"]
        assert "env" not in seen["kwargs"]  # inherit 口径

    def test_spawn_missing_cli_fails_open(self, monkeypatch):
        def fake_popen(cmd, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "claude")

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        assert default_channel("p", None, 5) is None

    def test_timeout_fails_open_without_orphan(self, monkeypatch):
        monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: _TimeoutProc())
        assert default_channel("p", None, 5) is None

    def test_nonzero_exit_fails_open(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "Popen",
            lambda cmd, **kw: _OutProc(stderr="boom", returncode=1),
        )
        assert default_channel("p", None, 5) is None

    def test_blank_output_fails_open(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "Popen", lambda cmd, **kw: _OutProc(stdout="   ")
        )
        assert default_channel("p", None, 5) is None
