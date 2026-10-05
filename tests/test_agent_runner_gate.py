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
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner import runner as runner_module
from core.agent_runner.prompt_builder import (
    PromptBuilder,
    planner_result_path,
)
from core.agent_runner.result_gate import (
    AgentArtifactGateError,
    TASK_GATE_ERROR_PREFIX,
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
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
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
        """非 planner/implementer/fast-track 类型无产物契约 → 零拦截。

        fix-impl-tasks-completion-gate P0：implementer/fast-track 已纳入产物硬门
        （见 tests/test_impl_tasks_completion_gate.py），此处改以 verifier 等
        无契约类型断言「零拦截」；implementer 无 worktree 时返回失败归因（fail-closed）。
        """
        runner = _make_runner(tmp_path)
        assert runner._check_agent_result_artifact("spec-x", "verifier") is None
        assert runner._check_agent_result_artifact("spec-x", "self-review") is None
        # implementer 分支已有产物契约：wt_path 缺位 → 拦截（fail-closed）
        err = runner._check_agent_result_artifact("spec-x", "implementer")
        assert err is not None
        assert "worktree 路径不可得" in err
        assert "产物硬门" in err

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
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
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

        # 无效文件须在 fake_run_claude 内写入，确保 mtime ≥ attempt_started_at
        # （fix-verdict-read-failclosed D2 新鲜度约束：预写文件可能因
        # mtime < run_started_at 被拦截为陈旧残留而非非法 JSON）。
        result_path = planner_result_path(tmp_path, "spec-x", "planner-judge")

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text("{{not-json", encoding="utf-8")
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

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            # 产物须在 run 启动后写入（D2 新鲜度：mtime ≥ attempt_started_at）
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps({"status": "verified", "summary": "ok"}),
                encoding="utf-8",
            )
            return ("done", 1, "sess-ok", _usage_ok())

        runner._run_claude = fake_run_claude
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
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            return ("plan-ready", 1, "sess-plan", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-plan", "run-p1")
        assert result.success is False
        # 非 PASS 即失败——错误归因到 test_scenarios.json 缺失
        assert "test_scenarios.json" in (result.error or "")
        assert "结果文件缺失" in (result.error or "")

    def test_plan_with_scenarios_artifact_passes(self, tmp_path):
        """planner-plan 落盘双产物（test_scenarios.json + status=plan-ready 结果文件）→ run 成功。"""
        runner = _make_runner(tmp_path, _standard_chain_config("planner-plan"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        scenarios_path = planner_result_path(tmp_path, "spec-x", "planner-plan")
        result_path = planner_result_path(tmp_path, "spec-x", "planner-judge")

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            # 双产物须在 run 启动后写入（D2 新鲜度：mtime ≥ attempt_started_at）；
            # add-planready-artifact-gate：planner-plan 结果文件契约与 judge 同源路径
            scenarios_path.parent.mkdir(parents=True, exist_ok=True)
            scenarios_path.write_text(json.dumps([{"id": "s1", "description": "d"}]),
                                      encoding="utf-8")
            result_path.write_text(
                json.dumps({"status": "plan-ready", "spec": "spec-x"}),
                encoding="utf-8",
            )
            return ("plan-ready", 1, "sess-plan", _usage_ok())

        runner._run_claude = fake_run_claude
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
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
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
# fix-verdict-read-failclosed：拷回时序 / 新鲜度 / status 白名单（Task 1.4）
# ═══════════════════════════════════════════════════════════════════════════

class TestVerdictReadFailClosedGate:
    """产物硬门三增补：拷回前置门检、mtime 新鲜度、顶层 status 白名单。"""

    def _gate_path(self, proot: Path, spec: str) -> Path:
        return planner_result_path(proot, spec, "planner-judge")

    # ── ① worktree 侧非法 JSON（裸换行复刻事故）→ 拷回后门检拦截 ────────

    def test_worktree_invalid_json_caught_after_copyback(self, tmp_path,
                                                         monkeypatch):
        """worktree 侧写裸换行非法 JSON → 拷回后门检拦截（瞬态重试）。

        复刻 add-verify-contract-autodraft 事故签名：judge 以相对路径写产物
        落在 worktree 真实 .fenix/ 下；拷回先于门检（D1），门验到主树同路径
        本轮真实产物（非法 JSON）→ 拦截走瞬态退避重试。
        """
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"

        # worktree 真实 .fenix/ 下的产物：summary 字符串含未转义裸换行
        wt_vp = wt / ".fenix" / "verify-progress" / "spec-x"
        wt_vp.mkdir(parents=True, exist_ok=True)

        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            # 每轮重写 worktree 侧非法产物（本轮真实产出 = 非法 JSON）
            (wt_vp / ".fenix-run-result.json").write_text(
                '{"status": "bug-found", "summary": "line1\nline2"}',
                encoding="utf-8")
            return ("done", 1, "sess-gate", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-v1")
        assert result.success is False
        assert "非法 JSON" in (result.error or "")
        assert calls["n"] >= 2  # 瞬态退避重试发生
        # 拷回先行证据：主树同路径已被本轮 worktree 产物覆盖（非法 JSON）
        assert self._gate_path(tmp_path, "spec-x").is_file()

    def test_worktree_valid_bugfound_passes_after_copyback(self, tmp_path):
        """worktree 侧写合法 bug-found → 拷回后门检通过 → run success。"""
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        wt_vp = wt / ".fenix" / "verify-progress" / "spec-x"
        wt_vp.mkdir(parents=True, exist_ok=True)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            (wt_vp / ".fenix-run-result.json").write_text(
                json.dumps({"status": "bug-found", "summary": "found"}),
                encoding="utf-8")
            return ("done", 1, "sess-gate", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-v2")
        assert result.success is True
        # 拷回生效：主树同路径已有本轮产物（而非依赖残留）
        assert self._gate_path(tmp_path, "spec-x").is_file()

    # ── ② 主树残留上一轮合法文件 + 本轮零产出 → 新鲜度拦截 ─────────────

    def test_stale_main_tree_artifact_freshness_rejected(self, tmp_path,
                                                         monkeypatch):
        """主树残留上一轮合法文件 + 本轮零产出 → mtime 新鲜度拦截。

        evo-add-judge-result-predispatch-rename 1.2 起拦截后处置升级：原地
        重试前陈旧文件被改名留档 prev-judge-result.json，终态归因退化为
        「结果文件缺失」（首次门禁失败仍归因「早于本轮启动」，见重试事件）。
        """
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"

        # 主树残留上一轮合法产物（mtime 远早于本轮 attempt 启动）
        stale_path = self._gate_path(tmp_path, "spec-x")
        stale_path.parent.mkdir(parents=True, exist_ok=True)
        stale_path.write_text(json.dumps({"status": "verified", "summary": "old"}),
                              encoding="utf-8")
        old = time.time() - 3600
        os.utime(stale_path, (old, old))

        runner._run_claude = MagicMock(
            return_value=("done", 1, "sess-gate", _usage_ok()))
        result = runner._execute_agent("spec-x", "planner-judge", "run-v3")
        assert result.success is False
        # 首次门禁失败仍归因陈旧残留（重试事件留痕）
        events = _run_file_events(tmp_path, "run-v3", "-a1")
        stale_retries = [e for e in events
                         if e.get("type") == "transient_retry"
                         and "早于本轮启动" in (e.get("error") or "")]
        assert stale_retries
        # 清理生效：陈旧文件已改名留档，终态归因退化为「结果文件缺失」
        archive_path = stale_path.parent / "prev-judge-result.json"
        assert json.loads(
            archive_path.read_text(encoding="utf-8")) == {
            "status": "verified", "summary": "old"}
        assert not stale_path.exists()
        assert "结果文件缺失" in (result.error or "")
        assert "早于本轮启动" not in (result.error or "")

    # ── ③ 顶层 status="success" → 白名单拦截 ─────────────────────────────

    def test_gate_rejects_non_whitelist_status(self, tmp_path):
        """顶层 status='success'（verdict 语义错位）→ 白名单拦截，附实际值。"""
        runner = _make_runner(tmp_path)
        p = self._gate_path(tmp_path, "spec-x")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "success", "summary": "impl ok"}),
                     encoding="utf-8")
        err = runner._check_agent_result_artifact("spec-x", "planner-judge")
        assert err is not None
        assert "'success'" in err
        assert "白名单" in err

    # ── ④ 合法 verified / bug-found → 通过 ───────────────────────────────

    @pytest.mark.parametrize("status", ["verified", "bug-found",
                                        "scenario-repaired"])
    def test_gate_pass_on_whitelist_status(self, tmp_path, status):
        """白名单内合法 status → 门检放行（None）。"""
        runner = _make_runner(tmp_path)
        p = self._gate_path(tmp_path, "spec-x")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": status, "summary": "ok"}),
                     encoding="utf-8")
        assert runner._check_agent_result_artifact("spec-x", "planner-judge") is None


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

# ═══════════════════════════════════════════════════════════════════════════
# add-timeline-gate-failure-display：门禁归因落盘 + gate-blocked 终态（Task 4.1/4.3）
# ═══════════════════════════════════════════════════════════════════════════


def _gate_events(proot: Path, sub_run_id: str) -> list:
    """读单个 sub_run 产物文件的全部事件（按行序）。"""
    f = proot / ".fenix" / "runs" / f"{sub_run_id}.jsonl"
    if not f.is_file():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestGateBlockedTerminal:
    """门禁失败在 run jsonl 留痕：error 文案 + gate-blocked 终态事件。

    事故形态（2026-09-21 add-freeze-stop-inflight-agents 收尾）：门禁连续 7 次
    拒绝，run jsonl 里零归因（transient_retry/superseded 都不含 error），预算
    耗尽后末行仍是 CLI 的 result（is_error:false）→ 读侧判 done → 时间轴一串
    绿点，用户以为 Agent 反复顺利收工。写侧 MUST 把归因与终态落到产物里。
    """

    def _call_gate(self, runner, tmp_path, error_msg, *,
                   transient_retries: int = 0, transient_budget=None,
                   provider=None, agent_type: str = "planner-judge",
                   sub_run_id: str = "run-x-a1"):
        """直接驱动门禁处置（只覆盖分支派发，不跑 attempt 循环）。"""
        return runner._handle_artifact_gate_retry(
            AgentArtifactGateError(error_msg),
            spec_name="spec-x", agent_type=agent_type,
            run_id="run-x", attempt=1,
            attempt_run_id="run-x-a1", sub_run_id=sub_run_id,
            provider_name=provider, model="m1",
            wt_path=tmp_path / "wt",
            transient_retries=transient_retries,
            transient_budget=list(transient_budget or []),
            start_time=time.time(), turns=1, usage_info=_usage_ok(),
        )

    # ── ① ② 原地重试两条事件都带 error（集成路径）────────────────────

    def test_gate_failure_records_error_on_retry_and_superseded(
            self, tmp_path, monkeypatch):
        """门禁失败 → transient_retry / superseded 均含非空 error 且含门禁名。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            # 复刻真实 _run_claude 的 CLI 收尾行：门禁是在 exit 0「之后」判的，
            # 故 result 行必然先落盘——gate-blocked MUST 成为其后的末行
            p = tmp_path / ".fenix" / "runs" / f"{run_id}.jsonl"
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "result", "result": "done"}) + "\n")
            return ("done", 1, "sess-gate", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-gb1")
        assert result.success is False

        events = _run_file_events(tmp_path, "run-gb1", "-a1")
        retries = [e for e in events if e.get("type") == "transient_retry"]
        superseded = [e for e in events if e.get("type") == "superseded"]
        assert retries, "应含 artifact_gate 原地重试事件"
        assert superseded, "应含弃置事件"
        for e in retries:
            assert e.get("error"), f"transient_retry 缺 error 归因: {e}"
            assert "结果文件缺失" in e["error"] or "产物硬门" in e["error"]
        for e in superseded:
            assert e.get("error"), f"superseded 缺 error 归因: {e}"

        # ③④ 末次 attempt 文件末行为 gate-blocked（结构类 → artifact_gate），
        # 且不得以 CLI 的 result 收尾（否则读侧判 done）
        last_file = _gate_events(tmp_path, "run-gb1-a2-r1")
        assert last_file, "末次原地重试产物缺失"
        assert last_file[-1]["type"] == "gate-blocked", last_file[-1]
        assert last_file[-1]["reason"] == "artifact_gate"
        assert last_file[-1]["error"], "gate-blocked 缺 error"
        for stem in ("run-gb1-a1", "run-gb1-a1-r1", "run-gb1-a2",
                     "run-gb1-a2-r1"):
            evs = _gate_events(tmp_path, stem)
            assert evs, f"{stem} 产物缺失"
            assert evs[-1]["type"] != "result", (
                f"{stem} 以 result 收尾 → 读侧会判成功: {evs[-1]}")

    # ── ③ 任务完成度类分支 reason 必须是 task_gate ────────────────────

    def test_task_gate_branch_reason_is_task_gate(self, tmp_path):
        """`[task-gate]` 类终止 → 末行 gate-blocked 且 reason == "task_gate"。

        归因 MUST NOT 写成 artifact_gate——那是产物结构门的归因，混用会让读侧/前端
        把「任务完成度门」误标为「产物结构门」。
        """
        runner = _make_runner(tmp_path)
        assert TASK_GATE_ERROR_PREFIX == "[task-gate]"  # 与真实产出门前缀对齐
        error, _retries, _yielded, do_continue, do_break = self._call_gate(
            runner, tmp_path,
            f"{TASK_GATE_ERROR_PREFIX} 未勾选任务：1.2（impl-tasks-completion-gate）",
        )
        assert do_break is True and do_continue is False
        assert "[task-gate]" in error
        events = _gate_events(tmp_path, "run-x-a1")
        assert events[-1]["type"] == "gate-blocked"
        assert events[-1]["reason"] == "task_gate"
        assert events[-1]["error"]

    # ── ③ provider 为 None 仍可序列化 ────────────────────────────────

    def test_gate_blocked_serializes_none_provider(self, tmp_path):
        """provider 缺位（None）→ gate-blocked 写 "" 而非 null，JSON 可解析。"""
        runner = _make_runner(tmp_path)
        self._call_gate(runner, tmp_path, "结果文件缺失（impl-code-review-gate）",
                        transient_budget=[], provider=None)
        events = _gate_events(tmp_path, "run-x-a1")
        assert events[-1]["type"] == "gate-blocked"
        assert events[-1]["provider"] == ""
        assert events[-1]["reason"] == "artifact_gate"

    # ── ⑤ 截断口径：字符（code point），非字节 ────────────────────────

    def test_error_truncated_to_1024_chars_not_bytes(self, tmp_path):
        """超长归因截断至 ≤1024 字符（UTF-8 ≤4096 字节），口径为字符切片。"""
        assert runner_module._GATE_ERROR_TRUNCATE == 1024
        runner = _make_runner(tmp_path)
        # 2000 个 CJK 字符 = 2000 字符 / UTF-8 6000 字节：字节口径只会剩 ~341
        # 字符，字符口径应恰好切到 1024
        self._call_gate(runner, tmp_path, "门" * 2000, transient_budget=[])
        events = _gate_events(tmp_path, "run-x-a1")
        err = events[-1]["error"]
        assert len(err) <= 1024, f"字符数超上限: {len(err)}"
        assert len(err.encode("utf-8")) <= 4096, "UTF-8 编码后超 4096 字节"
        assert len(err) == 1024, "应恰好截到 1024 字符（字符口径，非字节）"
        assert len(err.encode("utf-8")) > 1024, "字符口径下 CJK 字节数必然 > 字符数"

    def test_transient_retry_error_truncated(self, tmp_path, monkeypatch):
        """原地重试事件的 error 同样受 1024 字符上限约束。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path)
        # 让退避后的让位复查直接通过（不依赖 state_machine）
        runner._should_give_up_before_retry = lambda *a, **k: False
        runner._wip_checkpoint_before_backoff = lambda *a, **k: None
        self._call_gate(runner, tmp_path, "工" * 3000, transient_budget=[0])
        events = _gate_events(tmp_path, "run-x-a1")
        retry = [e for e in events if e.get("type") == "transient_retry"]
        assert retry, events
        assert len(retry[0]["error"]) == 1024


class TestGateBlockedBudgetAccounting:
    """4.3：门禁终态不被计作「死亡 run」（预算不外溢豁免）。"""

    def test_gate_blocked_run_not_counted_dead(self, tmp_path):
        """末行 gate-blocked → _run_file_died 返回 False（仍计入已耗预算）。

        门禁失败已经烧掉一轮实现预算，MUST NOT 因「不是 error 终态」被当成
        死亡 run 而豁免（那会让门禁连环拒绝对预算对账失去意义）。
        """
        from core.pm_engine.budget import ImplBudget
        p = tmp_path / "impl-spec-x-1700000000-a2-r1.jsonl"
        p.write_text(
            json.dumps({"type": "result", "result": "done"}) + "\n"
            + json.dumps({"type": "gate-blocked", "reason": "artifact_gate",
                          "error": "x"}) + "\n",
            encoding="utf-8")
        assert ImplBudget._run_file_died(p) is False
        # 对照：末行确为 error 时才算死亡
        p2 = tmp_path / "impl-spec-x-1700000001-a1.jsonl"
        p2.write_text(json.dumps({"type": "error", "error": "boom"}) + "\n",
                      encoding="utf-8")
        assert ImplBudget._run_file_died(p2) is True

    def test_empty_run_file_not_counted_dead(self, tmp_path):
        """空产物文件（零字节）→ _run_file_died 返回 False（按收工计入）。

        空文件/进程中断流无 error 末行，对账侧
        （_count_normal_completed_impl_runs）按正常收工计入——固化该边界。
        """
        from core.pm_engine.budget import ImplBudget
        p = tmp_path / "impl-spec-x-1700000002-a1.jsonl"
        p.write_text("", encoding="utf-8")
        assert ImplBudget._run_file_died(p) is False


# ═══════════════════════════════════════════════════════════════════════════
# evo-add-judge-result-predispatch-rename（Task 2.1）
# 裁决结果文件派发前留档 + 陈旧残留重试前清理。
# 背景：2026-10-05 potplayer-base 事故——上轮 .fenix-run-result.json 残留触发
# 新鲜度硬门，把 exit 0 的正常裁决轮整轮作废；且重跑路径不清理陈旧文件，
# 最坏烧光原地重试预算。
# ═══════════════════════════════════════════════════════════════════════════

def _plant_judge_result(proot: Path, spec: str, payload: dict,
                        age_seconds: float = 0.0) -> Path:
    """预置 per-spec judge 结果文件（可选陈旧 mtime）。"""
    p = planner_result_path(proot, spec, "planner-judge")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    if age_seconds:
        past = time.time() - age_seconds
        os.utime(p, (past, past))
    return p


def _flaky_replace_broken_for(dst_name: str):
    """构造仅对目标文件名失败的 os.replace（其余委托真实现）。"""
    real_replace = os.replace

    def _replace(src, dst, *a, **k):
        if Path(dst).name == dst_name:
            raise OSError(f"rename blocked for {dst_name}")
        return real_replace(src, dst, *a, **k)

    return _replace


class TestJudgeResultPredispatchRename:
    """judge 派发前留档 + 陈旧残留重试前清理（evo-add-judge-result-predispatch-rename）。"""

    def _mock_worktree(self, runner, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir(parents=True, exist_ok=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

    def test_predispatch_stale_result_archived_and_gate_passes(self, tmp_path):
        """预置上轮遗留文件 → run_planner("judge") 派发前已改名、本轮硬门放行、留档可回溯。"""
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        self._mock_worktree(runner, tmp_path)
        prev_payload = {"status": "bug-found", "summary": "上一轮裁决结论"}
        result_path = _plant_judge_result(tmp_path, "spec-x", prev_payload,
                                          age_seconds=3600)
        archive_path = result_path.parent / "prev-judge-result.json"

        seen_at_dispatch = {}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            # agent 首次被调用时刻 = 派发后：原路径已腾空、留档内容可回溯
            seen_at_dispatch["result_gone"] = not result_path.exists()
            seen_at_dispatch["archive"] = (
                json.loads(archive_path.read_text(encoding="utf-8"))
                if archive_path.is_file() else None)
            result_path.write_text(
                json.dumps({"status": "verified", "summary": "本轮裁决"}),
                encoding="utf-8")
            return ("done", 1, "sess-ok", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner.run_planner("spec-x", "judge")

        assert result.success is True  # 本轮硬门放行（不再命中陈旧残留）
        assert seen_at_dispatch["result_gone"] is True
        assert seen_at_dispatch["archive"] == prev_payload
        assert json.loads(
            archive_path.read_text(encoding="utf-8")) == prev_payload

    def test_predispatch_no_leftover_zero_impact(self, tmp_path):
        """无遗留文件 → 派发行为零变化（不产生 prev-judge-result.json，run 成功）。"""
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        self._mock_worktree(runner, tmp_path)
        result_path = planner_result_path(tmp_path, "spec-x", "planner-judge")
        archive_path = result_path.parent / "prev-judge-result.json"

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
        result = runner.run_planner("spec-x", "judge")

        assert result.success is True
        assert not archive_path.exists()

    def test_predispatch_rename_failure_does_not_block(self, tmp_path,
                                                       monkeypatch):
        """改名失败（OSError）→ 仅 WARNING 留痕，派发照常、run 成功。"""
        monkeypatch.setattr(runner_module.os, "replace",
                            _flaky_replace_broken_for("prev-judge-result.json"))
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        self._mock_worktree(runner, tmp_path)
        result_path = _plant_judge_result(
            tmp_path, "spec-x", {"status": "bug-found", "summary": "prev"})
        archive_path = result_path.parent / "prev-judge-result.json"
        calls = {"n": 0}

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            result_path.write_text(
                json.dumps({"status": "verified", "summary": "本轮"}),
                encoding="utf-8")
            return ("done", 1, "sess-ok", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner.run_planner("spec-x", "judge")

        assert calls["n"] == 1  # 派发未被阻断
        assert result.success is True
        assert not archive_path.exists()  # 改名失败：无留档产物，agent 覆写原路径

    def test_plan_mode_dispatch_does_not_archive(self, tmp_path, monkeypatch):
        """mode="plan" 派发不触发留档（改名仅挂在 judge 分支）。"""
        runner = _make_runner(tmp_path)
        archived = []
        monkeypatch.setattr(
            runner, "_archive_prev_judge_result",
            lambda spec, fallback_unlink=False: archived.append(spec))
        monkeypatch.setattr(
            runner, "_execute_agent",
            lambda spec, atype, rid: "sentinel")

        assert runner.run_planner("spec-x", "plan") == "sentinel"
        assert archived == []
        assert runner.run_planner("spec-x", "judge") == "sentinel"
        assert archived == ["spec-x"]

    def test_archive_helper_fallback_unlink_on_rename_failure(self, tmp_path,
                                                              monkeypatch):
        """重试前清理路径：改名失败退化为删除（再败归因退化为结果文件缺失）。"""
        runner = _make_runner(tmp_path)
        p = _plant_judge_result(tmp_path, "spec-x", {"status": "verified"})
        monkeypatch.setattr(runner_module.os, "replace",
                            _flaky_replace_broken_for("prev-judge-result.json"))

        assert runner._archive_prev_judge_result(
            "spec-x", fallback_unlink=True) is True
        assert not p.exists()  # 原文件已删除（清理达成）
        assert not (p.parent / "prev-judge-result.json").exists()

        # 派发前留档路径（fallback_unlink=False）：改名失败不删原文件
        p2 = _plant_judge_result(tmp_path, "spec-y", {"status": "verified"})
        assert runner._archive_prev_judge_result("spec-y") is False
        assert p2.exists()

    def test_stale_artifact_retry_no_repeat_hit(self, tmp_path, monkeypatch):
        """硬门命中陈旧残留 → 原地重试前已清理，再败归因不再是「陈旧残留」。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _standard_chain_config("planner-judge"))
        self._mock_worktree(runner, tmp_path)
        prev_payload = {"status": "bug-found", "summary": "上一轮裁决"}
        result_path = _plant_judge_result(tmp_path, "spec-x", prev_payload,
                                          age_seconds=3600)
        archive_path = result_path.parent / "prev-judge-result.json"
        # 跨 spec 共享根文件（实现收尾契约唯一落点）MUST NOT 被改名/删除
        root_result = tmp_path / ".fenix" / ".fenix-run-result.json"
        root_result.parent.mkdir(parents=True, exist_ok=True)
        root_result.write_text(json.dumps({"status": "success"}),
                               encoding="utf-8")

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            # 始终不写产物：第一次门禁命中预置陈旧文件，此后命中「结果文件缺失」
            return ("done", 1, "sess-stale", _usage_ok())

        runner._run_claude = fake_run_claude
        result = runner._execute_agent("spec-x", "planner-judge", "run-stale")

        assert result.success is False
        # 陈旧文件已被改名留档且内容可回溯（重试前清理生效）
        assert json.loads(
            archive_path.read_text(encoding="utf-8")) == prev_payload
        assert not result_path.exists()
        # 跨 spec 共享根文件未被触碰
        assert json.loads(root_result.read_text(encoding="utf-8")) == {
            "status": "success"}

        # attempt-1 链路的重试事件：恰好一次「陈旧」归因，其余为「结果文件缺失」
        events = _run_file_events(tmp_path, "run-stale", "-a1")
        retries = [e for e in events
                   if e.get("type") == "transient_retry"
                   and e.get("reason") == "artifact_gate"]
        assert [e for e in retries if "陈旧" in (e.get("error") or "")], \
            "首次门禁失败应归因陈旧残留"
        # 清理后重试不再重复命中同一陈旧文件
        assert all("陈旧" not in (e.get("error") or "") for e in retries[1:]), \
            "清理后的重试不得再命中陈旧残留"
        assert all("结果文件缺失" in (e.get("error") or "") for e in retries[1:])
        # 终态归因不再是陈旧残留
        assert "陈旧" not in (result.error or "")
        assert "结果文件缺失" in (result.error or "")
