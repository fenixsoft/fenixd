"""add-judge-artifact-gate：planner 产物硬门 + judge 逐场景 checkpoint 测试。

覆盖 tasks：
- 1.3 exit 0 无产物 → success=False + 瞬态重试判定（不进裁决重试预算）；
     结果文件空/非法 JSON 同判；产物合规放行；planner-plan 无 test_scenarios.json 同判。
- 2.3 模拟部分增强的 report.json → 重试 prompt 含「沿用已归因场景」注入段；
     已归因场景不被二次改写（读侧校验）。

硬门判据（design D1）：planner-judge 成功 = exit 0 且结果文件
（.fenix/verify-progress/<spec>/.fenix-run-result.json）存在且可解析；
planner-plan = test_scenarios.json。产物缺失/空/非法 JSON → AgentArtifactGateError
→ 既有瞬态原地退避重试（fix-provider-transient-backoff 通道原样复用）。
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.prompt_builder import (
    PromptBuilder,
    planner_result_path,
)
from tests.helpers import FakeLogger


def _make_runner(tmp_path: Path, config: dict | None = None) -> AgentRunner:
    """构造可驱动 _execute_agent 的最小 runner（test_transient_backoff 同款）。

    绕过 __init__，注入 mock 组件（v2_server / token_accountant / build_prompt /
    run_claude），使 _execute_agent_inner 可完整跑通而不触发真实子进程。
    """
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
    # runs 产物目录：真实 _run_claude 在流写盘前创建；测试 fake 不建，此处补齐
    (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return runner


def _standard_chain_config(agent_type: str = "planner-judge") -> dict:
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


def _run_file_events(proot: Path, run_id: str, base: str) -> list:
    """读取某 attempt 的 run jsonl（含原地重试子产物 r1..rn）。"""
    events = []
    p = proot / ".fenix" / "runs"
    for suffix in (base, f"{base}-r1", f"{base}-r2"):
        f = p / f"{run_id}{suffix}.jsonl"
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


# ═══════════════════════════════════════════════════════════════════════════
# 1.3 产物硬门（Task 1.3）
# ═══════════════════════════════════════════════════════════════════════════

class TestArtifactGate:
    """planner 产物存在性硬门（add-judge-artifact-gate D1）。"""

    def _gate_path(self, proot: Path, spec: str, agent_type: str) -> Path:
        return planner_result_path(proot, spec, agent_type)

    # ── _check_agent_result_artifact 单测 ──────────────────────────────

    def test_gate_check_pass_on_valid_artifact(self, tmp_path):
        """合法 JSON 产物 → 校验通过（返回 None）。"""
        runner = _make_runner(tmp_path)
        spec = "spec-x"
        p = self._gate_path(tmp_path, spec, "planner-judge")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "verified", "summary": "ok"}),
                     encoding="utf-8")
        assert runner._check_agent_result_artifact(spec, "planner-judge") is None

    def test_gate_check_missing_artifact(self, tmp_path):
        """产物缺失 → 归因错误包含「结果文件缺失」硬门语义。"""
        runner = _make_runner(tmp_path)
        err = runner._check_agent_result_artifact("spec-x", "planner-judge")
        assert err is not None
        assert "结果文件缺失" in err
        assert "产物硬门" in err

    @pytest.mark.parametrize("content", ["", "not-json{{{"])
    def test_gate_check_empty_and_invalid_json(self, tmp_path, content):
        """产物为空 / 非法 JSON → 与缺失同判（fail-closed）。"""
        runner = _make_runner(tmp_path)
        spec = "spec-x"
        p = self._gate_path(tmp_path, spec, "planner-plan")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        err = runner._check_agent_result_artifact(spec, "planner-plan")
        assert err is not None
        assert "产物硬门" in err

    def test_gate_check_ignores_other_agent_types(self, tmp_path):
        """非 planner 类型无产物契约 → 零拦截。"""
        runner = _make_runner(tmp_path)
        assert runner._check_agent_result_artifact("spec-x", "implementer") is None
        assert runner._check_agent_result_artifact("spec-x", "fast-track") is None

    # ── _execute_agent 集成：exit 0 无产物 → 瞬态重试 ──────────────────

    def test_judge_exit0_no_artifact_transient_retry(self, tmp_path, monkeypatch):
        """judge exit 0 但结果文件缺失 → success=False + 原地瞬态退避重试。

        不消耗裁决重试预算的 runner 侧证据：错误经 [provider-transient] 通道
        归因（dispatch 层据此走瞬态复用/重派，而非 validate_report 的重试一次）；
        run jsonl 含 reason=artifact_gate 的 transient_retry 事件。
        """
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            calls["n"] += 1
            return ("done", 1, "sess-gate", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-g1")

        # 进程均 exit 0（每次 _run_claude 均返回成功）——失败只能来自产物硬门
        assert calls["n"] == 4  # a1 + r1 + a2 + r1'（预算长度 1 × 2 attempt）
        assert result.success is False
        assert "结果文件缺失" in (result.error or "")
        assert "[provider-transient]" in (result.error or "")
        # 瞬态重试事件留痕（reason=artifact_gate）
        events = _run_file_events(tmp_path, "run-g1", "-a1")
        retries = [e for e in events if e.get("type") == "transient_retry"]
        assert retries, "run jsonl 应含 artifact_gate 瞬态重试事件"
        assert all(e.get("reason") == "artifact_gate" for e in retries)

    def test_judge_exit0_invalid_json_artifact_transient(self, tmp_path,
                                                        monkeypatch):
        """结果文件为空 / 非法 JSON → 与缺失同判（fail-closed 集成）。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"

        invalid = {"written": False}
        result_path = planner_result_path(tmp_path, "spec-x", "planner-judge")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text("{{not-json", encoding="utf-8")
        assert invalid == {"written": False}  # 仅占位：产物已预写为非法 JSON

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            calls["n"] += 1
            return ("done", 1, "sess-gate", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-g2")
        assert result.success is False
        assert "非法 JSON" in (result.error or "")

    def test_judge_exit0_valid_artifact_passes(self, tmp_path):
        """exit 0 且结果文件为合法 JSON → run 成功（无 gate 触发）。"""
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        result_path = planner_result_path(tmp_path, "spec-x", "planner-judge")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps({"status": "verified", "summary": "ok"}),
            encoding="utf-8",
        )

        runner._run_claude = MagicMock(
            return_value=("done", 1, "sess-ok", _usage_ok()))
        result = runner._execute_agent("spec-x", "planner-judge", "run-g3")
        assert result.success is True
        # 成功后 worktree 被清理（非 fast-track/repair 类型）
        runner.worktree_manager.cleanup.assert_called_once()

    def test_plan_no_scenarios_artifact_transient(self, tmp_path, monkeypatch):
        """planner-plan exit 0 但 test_scenarios.json 未生成 → 同判失败。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("planner-plan"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            calls["n"] += 1
            return ("plan-ready", 1, "sess-plan", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-plan", "run-p1")
        assert result.success is False
        # 非 PASS 即失败——错误归因到 test_scenarios.json 缺失
        assert "test_scenarios.json" in (result.error or "")
        assert "结果文件缺失" in (result.error or "")

    def test_plan_with_scenarios_artifact_passes(self, tmp_path):
        """planner-plan 落盘 test_scenarios.json → run 成功。"""
        runner = _make_runner(tmp_path, _standard_chain_config("planner-plan"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        scenarios_path = planner_result_path(tmp_path, "spec-x", "planner-plan")
        scenarios_path.parent.mkdir(parents=True, exist_ok=True)
        scenarios_path.write_text(json.dumps([{"id": "s1", "description": "d"}]),
                                  encoding="utf-8")

        runner._run_claude = MagicMock(
            return_value=("plan-ready", 1, "sess-plan", _usage_ok()))
        result = runner._execute_agent("spec-x", "planner-plan", "run-p2")
        assert result.success is True

    def test_success_after_gate_transient_with_artifact(self, tmp_path,
                                                        monkeypatch):
        """硬门瞬态重试后产物落盘 → run 成功（重试通道正常收敛）。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        calls = {"n": 0}
        config = _standard_chain_config("planner-judge")
        # 提高重试预算，留足第二次 attempt 的原地重试空间
        config["agents"]["transient_backoff_schedule"] = "1,1"
        runner.config = config

        result_path = planner_result_path(tmp_path, "spec-x", "planner-judge")

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return ("done", 1, "sess-gate", _usage_ok())  # 无产物 → gate 失败
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps({"status": "bug-found", "summary": "ok"}),
                encoding="utf-8",
            )
            return ("done", 1, "sess-gate", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-g4")
        assert result.success is True
        assert calls["n"] == 2  # 首次 gate 失败 → 原地重试（r1）即成功


# ═══════════════════════════════════════════════════════════════════════════
# 2.3 截断恢复注入段（Task 2.3）
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckpointRecoverySection:
    """judge 逐场景 checkpoint 的截断恢复注入（add-judge-artifact-gate D3）。"""

    def _make_prompt_builder(self, tmp_path: Path) -> PromptBuilder:
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = tmp_path
        return PromptBuilder(runner)

    def _write_report(self, tmp_path: Path, spec: str, scenarios: list) -> Path:
        p = tmp_path / ".fenix" / "verify-progress" / spec / "report.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"scenarios": scenarios}, ensure_ascii=False),
                     encoding="utf-8")
        return p

    def test_section_lists_only_classified_scenarios(self, tmp_path):
        """部分增强的 report.json → 注入段只列出「已归因」场景，跳过缺失/非法。"""
        spec = "spec-x"
        self._write_report(tmp_path, spec, [
            {"scenario_id": "ok-1", "status": "fail",
             "classification": "product-bug",
             "evidence": {"failed_assertions": [], "first_failed_step": "步骤1"}},
            {"scenario_id": "ok-2", "status": "error",
             "classification": "env",
             "evidence": {"screenshots": []}},
            {"scenario_id": "missing-1", "status": "fail"},          # 缺归因
            {"scenario_id": "invalid-1", "status": "warning",
             "classification": "bogus-label", "evidence": {}},       # 非法分类
            {"scenario_id": "pass-1", "status": "pass"},             # PASS 跳过
        ])
        pb = self._make_prompt_builder(tmp_path)
        section = pb._checkpoint_recovery_section(spec)
        assert "ok-1" in section
        assert "ok-2" in section
        assert "missing-1" not in section
        assert "invalid-1" not in section
        assert "pass-1" not in section

    def test_section_requires_legal_classification_and_nonempty_evidence(self,
                                                                         tmp_path):
        """只有 classification 合法且 evidence 非空的场景才算「已归因」。"""
        spec = "spec-x"
        self._write_report(tmp_path, spec, [
            {"scenario_id": "scn-empty-evidence", "status": "fail",
             "classification": "test-defect", "evidence": {}},       # 空 evidence
            {"scenario_id": "scn-missing-evidence", "status": "fail",
             "classification": "flaky"},                             # 缺 evidence
            {"scenario_id": "scn-valid", "status": "fail",
             "classification": "env",
             "evidence": {"failed_assertions": []}},                 # 合法
        ])
        pb = self._make_prompt_builder(tmp_path)
        section = pb._checkpoint_recovery_section(spec)
        assert "scn-valid" in section
        assert "scn-empty-evidence" not in section
        assert "scn-missing-evidence" not in section

    def test_section_zero_injection_no_report(self, tmp_path):
        """report.json 缺失 / 无已归档场景 → 零注入（空串）。"""
        pb = self._make_prompt_builder(tmp_path)
        assert pb._checkpoint_recovery_section("spec-x") == ""
        # 有 report 但全是 pass → 零注入
        self._write_report(tmp_path, "spec-x", [
            {"scenario_id": "p1", "status": "pass"},
            {"scenario_id": "p2", "status": "passed"},
        ])
        assert pb._checkpoint_recovery_section("spec-x") == ""

    def test_retry_prompt_contains_reuse_directive(self, tmp_path):
        """重试 judge 的完整 prompt 注入「重用」指令——已归因场景不被二次改写。

        读侧校验：构建 planner-judge 全文 prompt，断言含截断恢复注入段，且指令
        明确「直接沿用 / MUST NOT 二次裁决/复现/改写」，场景 id 原样列出。
        """
        spec = "spec-x"
        self._write_report(tmp_path, spec, [
            {"scenario_id": "early-1", "status": "fail",
             "classification": "product-bug",
             "evidence": {"first_failed_step": "步骤1"}},
            {"scenario_id": "later-1", "status": "fail"},  # 待补齐场景
        ])
        pb = self._make_prompt_builder(tmp_path)
        prompt = pb._build_prompt(spec, "planner-judge")
        assert "截断恢复" in prompt
        assert "early-1" in prompt
        assert "直接沿用" in prompt
        assert "MUST NOT 二次裁决/复现/改写" in prompt
        assert "later-1" not in prompt  # 缺失场景须完整裁决，不在沿用清单

        # 已归因场景不被二次改写：沿用指令内容 = 字段在位性判据下的保留语义
        reuse_lines = [l for l in prompt.splitlines() if "early-1" in l]
        assert reuse_lines, "沿用清单必须逐 id 列出"
        assert "仅对" in prompt and "缺失或非法" in prompt