"""add-planready-artifact-gate：planner-plan 结果文件契约硬门测试。

覆盖 tasks 1.2（planner-plan 产物硬门扩展）：
- spec「planready-artifact-gate」四 Scenario：
  1. planner 未写结果文件（只落 test_scenarios.json）→ 硬门拦截 + 走既有
     瞬态退避重试通道（AgentArtifactGateError 归因，run 不被标记 succeeded）
  2. 结果文件 status 白名单外（如 "success"）→ 拦截且文案含真实取值
  3. 健康轮次双产物齐备（status='plan-ready'）→ 返回 None / run 成功
  4. 结果文件 mtime 陈旧残留 → 按「本轮零产物」拦截
- 组合行为：健康 plan-ready 文件 + 场景文件任一缺失 → 拦截
- 覆盖 `_execute_agent` 集成路径（AgentArtifactGateError 断言）
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.prompt_builder import planner_result_path
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
    runner._daily_reset_date = None
    runner._daily_provider_attempts = {}
    runner._daily_provider_warned = {}
    runner.provider_circuits = {}
    runner.__dict__["_v2_server_instance"] = MagicMock()
    runner._v2_server._v2_inject_env.return_value = {}
    runner.__dict__["_token_accountant_instance"] = MagicMock()
    runner._build_prompt = lambda *a, **k: "test prompt"
    (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return runner


def _standard_chain_config(agent_type: str = "planner-plan") -> dict:
    """含单 provider 候选链的 config（transient 预算长度 1，attempt 上限 2）。"""
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
            "transient_backoff_schedule": "1",
        },
    }


def _usage_ok() -> dict:
    return {"input_tokens": 1, "output_tokens": 2,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "cost_usd": None}


def _plan_paths(proot: Path, spec: str):
    """planner-plan 双产物路径（test_scenarios.json + .fenix-run-result.json）。"""
    vp = proot / ".fenix" / "verify-progress" / spec
    return (
        planner_result_path(proot, spec, "planner-plan"),
        planner_result_path(proot, spec, "planner-judge"),
    )


class TestPlanreadyArtifactGateUnit:
    """_check_agent_result_artifact 单测（spec 四 Scenario 的单元形态）。"""

    def _write(self, path: Path, content: str, fresh: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if fresh:
            now = time.time()
            os.utime(path, (now, now))

    def test_scenario_missing_result_file_intercepted(self, tmp_path):
        """Scenario 1：只落场景文件、未写结果文件 → 归因含「结果文件缺失」+ primary 路径。"""
        runner = _make_runner(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        self._write(sc, json.dumps([{"id": "s1", "description": "d"}]))
        err = runner._check_agent_result_artifact(spec, "planner-plan")
        assert err is not None
        assert "结果文件缺失" in err
        assert "产物硬门" in err
        assert str(res) in err  # 归因含具体 primary 路径

    def test_scenario_status_out_of_whitelist(self, tmp_path):
        """Scenario 2：status='success'（implementer 残留语义错位）→ 拦截且含真实取值。"""
        runner = _make_runner(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        self._write(sc, json.dumps([{"id": "s1", "description": "d"}]))
        self._write(res, json.dumps({"status": "success", "spec": spec}))
        err = runner._check_agent_result_artifact(spec, "planner-plan")
        assert err is not None
        assert "status='success' 不在白名单" in err
        assert "success" in err  # 真实取值不丢弃、不以 None 替代
        assert str(res) in err

    def test_scenario_healthy_dual_artifacts_pass(self, tmp_path):
        """Scenario 3：双产物齐备 + status='plan-ready' → 返回 None（通过）。"""
        runner = _make_runner(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        self._write(sc, json.dumps([{"id": "s1", "description": "d"}]))
        self._write(res, json.dumps({"status": "plan-ready", "spec": spec}))
        assert runner._check_agent_result_artifact(spec, "planner-plan") is None

    def test_scenario_stale_result_file_intercepted(self, tmp_path):
        """Scenario 4：结果文件 mtime 早于本轮启动减宽限 → 陈旧残留拦截。"""
        runner = _make_runner(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        self._write(sc, json.dumps([{"id": "s1", "description": "d"}]))
        self._write(res, json.dumps({"status": "plan-ready", "spec": spec}))
        stale = time.time() - 100.0
        os.utime(res, (stale, stale))
        err = runner._check_agent_result_artifact(
            spec, "planner-plan", run_started_at=time.time())
        assert err is not None
        assert "陈旧残留" in err
        assert str(res) in err

    def test_healthy_result_file_but_scenarios_missing(self, tmp_path):
        """组合：健康 plan-ready 结果文件 + 场景文件缺失 → 拦截（既有校验叠加生效）。"""
        runner = _make_runner(tmp_path)
        spec = "spec-plan"
        _sc, res = _plan_paths(tmp_path, spec)
        self._write(res, json.dumps({"status": "plan-ready", "spec": spec}))
        err = runner._check_agent_result_artifact(spec, "planner-plan")
        assert err is not None
        assert "结果文件缺失" in err
        assert "test_scenarios.json" in err

    def test_healthy_scenarios_but_result_file_empty(self, tmp_path):
        """组合：健康场景文件 + 结果文件为空 → 拦截（fail-closed 同判）。"""
        runner = _make_runner(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        self._write(sc, json.dumps([{"id": "s1", "description": "d"}]))
        self._write(res, "")
        err = runner._check_agent_result_artifact(spec, "planner-plan")
        assert err is not None
        assert "结果文件为空" in err

    def test_result_file_not_top_level_object(self, tmp_path):
        """结果文件为合法 JSON 但顶层非对象（数组）→ 顶层非对象归因。"""
        runner = _make_runner(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        self._write(sc, json.dumps([{"id": "s1", "description": "d"}]))
        self._write(res, json.dumps(["not", "an", "object"]))
        err = runner._check_agent_result_artifact(spec, "planner-plan")
        assert err is not None
        assert "顶层非对象" in err

    def test_result_file_invalid_json(self, tmp_path):
        """结果文件非法 JSON → 非法 JSON 归因（与缺失同判，fail-closed）。"""
        runner = _make_runner(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        self._write(sc, json.dumps([{"id": "s1", "description": "d"}]))
        self._write(res, "{{not-json")
        err = runner._check_agent_result_artifact(spec, "planner-plan")
        assert err is not None
        assert "非法 JSON" in err

    def test_judge_branch_unchanged(self, tmp_path):
        """planner-judge 分支行为不变：status='verified' 放行、四值白名单外拦截。"""
        runner = _make_runner(tmp_path)
        spec = "spec-judge"
        path = planner_result_path(tmp_path, spec, "planner-judge")
        self._write(path, json.dumps({"status": "verified", "summary": "ok"}))
        assert runner._check_agent_result_artifact(spec, "planner-judge") is None
        # 语义错位取值仍拦截（四值白名单，planner-plan 单值白名单独立）
        self._write(path, json.dumps({"status": "success"}))
        err = runner._check_agent_result_artifact(spec, "planner-judge")
        assert err is not None
        assert "status='success' 不在白名单" in err


class TestPlanreadyArtifactGateIntegration:
    """_execute_agent 集成：硬门失败 → AgentArtifactGateError → 瞬态退避重试。"""

    def _runner_with_worktree(self, tmp_path):
        runner = _make_runner(tmp_path, _standard_chain_config("planner-plan"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-plan"
        runner.worktree_manager.cleanup.return_value = None
        return runner, wt

    def test_exit0_no_result_file_gate_error_transient_retry(self, tmp_path,
                                                             monkeypatch):
        """Scenario 1 集成：exit 0 只写场景文件 → AgentArtifactGateError 归因 → 退避重试。

        error 走 [provider-transient] 通道（瞬态退避重试，不消耗裁决重试预算）；
        run 不被标记 succeeded。
        """
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner, wt = self._runner_with_worktree(tmp_path)
        spec = "spec-plan"
        sc, _res = _plan_paths(tmp_path, spec)
        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            calls["n"] += 1
            # 复刻白烧事故：只写场景文件、忘写结果文件
            sc.parent.mkdir(parents=True, exist_ok=True)
            sc.write_text(json.dumps([{"id": "s1", "description": "d"}]),
                          encoding="utf-8")
            return ("plan-ready", 1, "sess-plan", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent(spec, "planner-plan", "run-pgate")
        # 进程均 exit 0——失败只能来自结果文件硬门（attempt 1 + 子重试 + attempt 2）
        assert calls["n"] == 4  # a1 + r1 + a2 + r1'（预算长度 1 × 2 attempt）
        assert result.success is False
        assert "结果文件缺失" in (result.error or "")
        assert "[provider-transient]" in (result.error or "")

    def test_exit0_status_success_intercepted_with_real_value(self, tmp_path,
                                                             monkeypatch):
        """Scenario 2 集成：结果文件 status='success' → 归因含真实取值，run 失败。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner, wt = self._runner_with_worktree(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            sc.parent.mkdir(parents=True, exist_ok=True)
            sc.write_text(json.dumps([{"id": "s1", "description": "d"}]),
                          encoding="utf-8")
            # implementer 共享文件残留语义错位取值
            res.write_text(json.dumps({"status": "success", "spec": spec}),
                           encoding="utf-8")
            return ("plan-ready", 1, "sess-plan", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent(spec, "planner-plan", "run-pgate2")
        assert result.success is False
        assert "status='success' 不在白名单" in (result.error or "")
        assert "[provider-transient]" in (result.error or "")

    def test_exit0_dual_artifacts_passes(self, tmp_path):
        """Scenario 3 集成：双产物齐备（status='plan-ready'）→ run 成功标记 succeeded。"""
        runner, wt = self._runner_with_worktree(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            sc.parent.mkdir(parents=True, exist_ok=True)
            sc.write_text(json.dumps([{"id": "s1", "description": "d"}]),
                          encoding="utf-8")
            res.write_text(json.dumps({"status": "plan-ready", "spec": spec}),
                           encoding="utf-8")
            return ("plan-ready", 1, "sess-plan", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent(spec, "planner-plan", "run-pgate3")
        assert result.success is True
        runner.worktree_manager.cleanup.assert_called_once()

    def test_exit0_stale_result_file_intercepted(self, tmp_path, monkeypatch):
        """Scenario 4 集成：结果文件陈旧残留（上一轮残留）→ 拦截，run 失败。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner, wt = self._runner_with_worktree(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        # 预写陈旧残留（mtime 远早于 run 启动）
        sc.parent.mkdir(parents=True, exist_ok=True)
        sc.write_text(json.dumps([{"id": "s1", "description": "d"}]),
                      encoding="utf-8")
        res.write_text(json.dumps({"status": "plan-ready", "spec": spec}),
                       encoding="utf-8")
        stale = time.time() - 100.0
        os.utime(res, (stale, stale))

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            # 本轮只写场景文件——陈旧结果文件未刷新
            return ("plan-ready", 1, "sess-plan", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent(spec, "planner-plan", "run-pgate4")
        assert result.success is False
        assert "陈旧残留" in (result.error or "")

    def test_success_after_gate_transient_with_dual_artifacts(self, tmp_path,
                                                              monkeypatch):
        """硬门瞬态重试后双产物齐备 → run 成功（重试通道正常收敛）。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner, wt = self._runner_with_worktree(tmp_path)
        spec = "spec-plan"
        sc, res = _plan_paths(tmp_path, spec)
        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            calls["n"] += 1
            sc.parent.mkdir(parents=True, exist_ok=True)
            sc.write_text(json.dumps([{"id": "s1", "description": "d"}]),
                          encoding="utf-8")
            # 第一次子 run 补上结果文件 → 后续 attempt 双产物齐备放行
            res.write_text(json.dumps({"status": "plan-ready", "spec": spec}),
                           encoding="utf-8")
            return ("plan-ready", 1, "sess-plan", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent(spec, "planner-plan", "run-pgate5")
        assert result.success is True
