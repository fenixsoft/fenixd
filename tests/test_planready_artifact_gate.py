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


# ═══════════════════════════════════════════════════════════════════════════
# 2.4 降级合成报告标注（degrade-annotation spec）
# ═══════════════════════════════════════════════════════════════════════════

class TestDegradeAnnotationReport:
    """合成报告携带降级标注三 Scenario（degrade-annotation spec）。"""

    def _deg_ctx(self, **overrides):
        ctx = {
            "reason": "Planner 未生成有效场景，status=不可读(missing: x)",
            "run_id": "planner-plan-demo-1-a1",
            "duration_seconds": 429.0,
            "cost_usd": 2.28,
            "degraded_at": "2026-09-09T15:39:18+00:00",
        }
        ctx.update(overrides)
        return ctx

    def _setup_legacy_result(self, root: Path, spec: str) -> Path:
        """legacy 合成场景：.fenix-run-result.json 存在、report.json 缺失。"""
        vp = root / ".fenix" / "verify-progress" / spec
        vp.mkdir(parents=True, exist_ok=True)
        (root / "spec" / "changes" / spec).mkdir(parents=True, exist_ok=True)
        (vp / ".fenix-run-result.json").write_text(json.dumps({
            "status": "bug-found", "spec": spec, "bugs": [],
            "summary": "legacy 降级后的裁决结果",
        }), encoding="utf-8")
        return vp

    def test_scenario_degraded_report_carries_annotation(self, tmp_path):
        """Scenario 1：降级上下文存在 → report.json 持久化标注 + markdown 渲染。"""
        root = tmp_path
        spec = "demo-spec"
        vp = self._setup_legacy_result(root, spec)
        (vp / "degrade_context.json").write_text(
            json.dumps(self._deg_ctx()), encoding="utf-8")

        from core.verify_report import synthesize_verification_report
        result = synthesize_verification_report(root, spec)
        assert result.get("ok"), result

        # 标注随 report.json 顶层持久化（非仅日志）
        persisted = json.loads((vp / "report.json").read_text(encoding="utf-8"))
        ann = persisted.get("degrade_annotation")
        assert ann is not None
        assert ann["run_id"] == "planner-plan-demo-1-a1"
        assert ann["duration_seconds"] == 429.0
        assert ann["cost_usd"] == 2.28
        assert "degraded_at" in ann

        # markdown 头部渲染「⚠️ 降级说明」引用块（原因+run_id+分钟+美元）
        md = (root / "spec" / "changes" / spec / "verification-report.md").read_text(
            encoding="utf-8")
        assert "⚠️ 降级说明" in md
        assert "Planner 未生成有效场景" in md
        assert "planner-plan-demo-1-a1" in md
        assert "7.2min" in md  # 429/60
        assert "$2.28" in md

    def test_scenario_normal_report_no_annotation(self, tmp_path):
        """Scenario 2：无降级 → 报告不携带标注（字段缺省），markdown 无降级块。"""
        root = tmp_path
        spec = "demo-spec"
        vp = self._setup_legacy_result(root, spec)

        from core.verify_report import synthesize_verification_report
        result = synthesize_verification_report(root, spec)
        assert result.get("ok"), result

        md = (root / "spec" / "changes" / spec / "verification-report.md").read_text(
            encoding="utf-8")
        assert "降级说明" not in md
        if (vp / "report.json").exists():
            data = json.loads((vp / "report.json").read_text(encoding="utf-8"))
            assert "degrade_annotation" not in data

    def test_scenario_annotation_persisted_in_report_json(self, tmp_path):
        """Scenario 3：标注随 report.json 数据结构持久化（还原降级事实与代价）。"""
        root = tmp_path
        spec = "demo-spec"
        vp = self._setup_legacy_result(root, spec)
        # 已有 report.json（引擎写入的正常产物）时标注注入顶层而非覆盖其余字段
        (vp / "report.json").write_text(json.dumps({
            "summary": {"passed": 0, "failed": 1, "total": 1},
            "scenarios": [{"scenario_id": "s1", "status": "fail"}],
        }), encoding="utf-8")
        (vp / "degrade_context.json").write_text(
            json.dumps(self._deg_ctx()), encoding="utf-8")

        from core.verify_report import synthesize_verification_report
        result = synthesize_verification_report(root, spec)
        assert result.get("ok"), result

        persisted = json.loads((vp / "report.json").read_text(encoding="utf-8"))
        assert persisted["degrade_annotation"]["run_id"] == "planner-plan-demo-1-a1"
        # 原字段不被覆盖（标注注入而非重建）
        assert persisted["summary"]["passed"] == 0
        assert persisted["scenarios"][0]["scenario_id"] == "s1"

    def test_degrade_context_missing_synthesis_unchanged(self, tmp_path):
        """degrade_context.json 缺失 → 合成行为与现状一致（无标注、正常产物）。"""
        root = tmp_path
        spec = "demo-spec"
        vp = self._setup_legacy_result(root, spec)
        assert not (vp / "degrade_context.json").exists()

        from core.verify_report import render_verification_report
        from core.verify_report import synthesize_verification_report
        result = synthesize_verification_report(root, spec)
        assert result.get("ok"), result
        # 渲染函数缺省不渲染（显式缺省参数零渲染）
        content = render_verification_report(
            spec, {"status": "verified"}, {"summary": {"passed": 1}})
        assert "降级说明" not in content

    def test_render_default_no_annotation(self):
        """render_verification_report 缺省 degrade_annotation → 报告与现状逐字节一致。"""
        from core.verify_report import render_verification_report
        content = render_verification_report(
            "demo-spec", {"status": "verified"},
            {"summary": {"passed": 1, "total": 1}})
        assert "降级说明" not in content
        assert "本报告由框架" in content


# ═══════════════════════════════════════════════════════════════════════════
# 2.4 pm_engine 侧降级判定点写文件 / 成功路径删文件分支覆盖
# ═══════════════════════════════════════════════════════════════════════════

class TestPmEngineDegradeContext:
    """阶段1 降级判定点写 degrade_context.json；plan-ready 成功路径删除。"""

    def _mk_pm(self, tmp_path, spec="demo-spec"):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        from unittest.mock import MagicMock as MM
        state_path = tmp_path / ".fenix" / "STATE.md"
        logger = MM()
        sm = StateMachine(state_path, logger)
        engine = PMEngine(sm, MM(), {}, tmp_path, logger)
        sm.add_spec(spec, {"priority": 5})
        for s in ("ready", "implementing", "implemented", "testing"):
            sm.transition(spec, s)
        # 阶段1 之后路径的组件 mock（聚焦降级判定点）
        engine._enqueue = MM()
        engine._apply_scenario_freeze = MM(return_value={})
        engine._apply_interaction_contract = MM(return_value=None)
        engine._on_spec_verified = MM()
        engine._on_spec_bug_found = MM()
        engine._ensure_app_reachable = MM(return_value=(True, False, ""))
        engine._ensure_verification_report = MM(return_value=None)
        engine._check_verification_gate = MM(return_value=None)
        engine._env_whitewash_gate = MM(return_value=True)
        engine._task_completion_blocker = MM(return_value=None)
        engine._verify_verdict_evidence = MM(return_value={
            "ok": True, "cause": "pass", "violations": [], "dispatch_error": "",
        })
        engine._update_warning_streaks = MM(return_value=[])
        engine._send_human_escalation_alert = MM()
        return engine, sm

    def _vp_dir(self, root, spec):
        return Path(root) / ".fenix" / "verify-progress" / spec

    def test_degrade_point_writes_context(self, tmp_path):
        """降级判定点：plan 结果不可读 → 写 degrade_context.json 后 raise。"""
        from types import SimpleNamespace
        from core.pm_engine.verification import VerdictReadResult
        engine, sm = self._mk_pm(tmp_path, "spec-a")
        engine.agent_runner = MagicMock()
        engine.agent_runner.run_planner = MagicMock(return_value=SimpleNamespace(
            success=True, error=None,
            run_id="planner-plan-spec-a-1-a1",
            duration_seconds=429.0,
        ))
        engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.failure("missing", "file-not-found"))

        import pytest
        with pytest.raises(RuntimeError):
            engine._run_three_stage_verification("spec-a")

        ctx_path = self._vp_dir(tmp_path, "spec-a") / "degrade_context.json"
        assert ctx_path.is_file()
        data = json.loads(ctx_path.read_text(encoding="utf-8"))
        assert data["run_id"] == "planner-plan-spec-a-1-a1"
        assert data["duration_seconds"] == 429.0
        assert "Planner 未生成有效场景" in data["reason"]
        assert "degraded_at" in data

    def test_planready_success_clears_stale_context(self, tmp_path):
        """plan-ready 校验通过 → 删除陈旧 degrade_context.json（防污染正常报告）。"""
        from types import SimpleNamespace
        from core.pm_engine.verification import VerdictReadResult
        from core.verify_engine import VerifyEngine
        engine, sm = self._mk_pm(tmp_path, "spec-b")
        engine.agent_runner = MagicMock()
        engine.agent_runner.run_planner = MagicMock(return_value=SimpleNamespace(
            success=True, error=None,
            run_id="planner-plan-spec-b-1-a1",
            duration_seconds=120.0,
        ))
        engine._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("plan-ready"))

        # 陈旧 degrade_context.json 预置（上一轮降级残留）
        vp = self._vp_dir(tmp_path, "spec-b")
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "degrade_context.json").write_text(
            json.dumps({"reason": "旧降级", "run_id": "old-run"}),
            encoding="utf-8")
        # 不写 test_scenarios.json：_load_frozen_scenarios 返回 None → 进入
        # planner 设计闭环 → run_planner 成功 + plan-ready → 成功路径调
        # _clear_degrade_context（本测试焦点）→ 随后阶段2 因场景文件缺失走
        # env_error 路径返回（不抛出）；断言在流程后仍成立。

        from unittest.mock import patch
        class FakeEngine:
            def __init__(self, *a, **k):
                pass
            async def run(self, scenarios):
                return {"spec": "spec-b",
                        "summary": {"total": 1, "passed": 1, "failed": 0,
                                    "warnings": 0, "errors": 0},
                        "scenarios": []}
        try:
            with patch("importlib.reload", lambda m: m), \
                    patch("core.verify_engine.VerifyEngine", FakeEngine):
                engine._run_three_stage_verification("spec-b")
        except Exception:
            # 阶段2 因无场景文件走异常路径属预期——_clear_degrade_context 已在
            # plan-ready 校验通过后、阶段2 之前执行完毕（本测试焦点）
            pass

        assert not (vp / "degrade_context.json").exists()
