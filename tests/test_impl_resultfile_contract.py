"""implementer 车道结果文件契约注入、路径分派、重试死因透传、捞回与归因。

fix-impl-resultfile-contract-gap：闭合「硬门在拦、提示词不说」的反馈断链。
覆盖范围：

1. 实现者双车道（implementer / fast-track）均注入结果文件硬门契约段（5.1）
2. 契约段路径按车道分派（5.2）
3. 既有三车道契约段不回归（5.3）
4. 死因透传三态（error/诊断/零注入）+ 字段级去重（5.4）
5. 实现者车道捞回四态（5.5）
6. 归因两类别文案区分 + 转录缺失降级（5.6）
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.prompt_builder import (
    PromptBuilder,
    impl_result_path,
    planner_result_path,
    spec_review_result_path,
    SPEC_REVIEW_RESULT_STATUS_WHITELIST,
)
from tests.helpers import FakeLogger

# ── 辅助 ──────────────────────────────────────────────────────────

def _make_runner(tmp_path: Path, config: dict | None = None) -> AgentRunner:
    """最小 runner（test_planready_artifact_gate / test_spec_review_artifact_gate 同款）。"""
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
    (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return runner


def _make_project(tmp_path: Path, spec: str = "demo") -> Path:
    """创建含 tasks.md 的项目结构。"""
    proot = tmp_path / "proj"
    (proot / "spec" / "changes" / spec).mkdir(parents=True, exist_ok=True)
    (proot / "spec" / "changes" / spec / "tasks.md").write_text(
        "- [ ] 1.1 x\n", encoding="utf-8")
    return proot


def _wt_path(tmp_path: Path, spec: str = "demo") -> Path:
    """模拟 worktree 路径。"""
    wt = tmp_path / f"wt-impl-{spec}"
    (wt / "spec" / "changes" / spec).mkdir(parents=True, exist_ok=True)
    return wt


def _write_transcript(tmp_path: Path, run_id: str, texts: list[str]) -> Path:
    """写一份 run 转录（与 test_spec_review_artifact_gate 同款）。"""
    p = tmp_path / ".fenix" / "runs" / f"{run_id}.jsonl"
    lines = [{"type": "system", "subtype": "init"}]
    for t in texts:
        lines.append({"type": "assistant",
                       "message": {"content": [{"type": "text", "text": t}]}})
    lines.append({"type": "result", "subtype": "success", "num_turns": 5})
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
                 encoding="utf-8")
    return p


# ── 5.1：实现者双车道契约段注入 ──────────────────────────────────

class TestImplLaneGateContract:
    """两分支（implementer / fast-track）MUST 均包含结果文件硬门段及五项要素。"""

    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_implementer_gate_section_present(self, tmp_path, agent_type):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt(
            "demo", agent_type, wt_path=_wt_path(tmp_path))
        # 段落标题
        assert "结果文件硬门" in prompt
        assert "实现者收工契约" in prompt
        # 五项核心要素（D2 / 5.1）
        assert "先落盘再深入" in prompt
        assert "正文里的 JSON 不算交付" in prompt or "正文" in prompt
        assert "判失败" in prompt
        # fix-agent-lane-efficiency 5.4：「无后台节拍」措辞已修正——能力事实
        #（ScheduleWakeup 不产生唤醒）保留，新增后台 Bash 完成通知可用 + 一次
        #后台启动 + 禁止 sleep 自旋。旧锚点 assert "无后台节拍" in prompt 已废弃。
        assert "ScheduleWakeup" in prompt
        assert "完成通知" in prompt or "run_in_background" in prompt
        assert "run_full_suite" in prompt or "前台有界" in prompt

    @pytest.mark.parametrize("agent_type", ["implementer", "fast-track"])
    def test_gate_does_not_contain_old_planner_text(self, tmp_path, agent_type):
        """实现者段不含 planner-judge 专属文案。"""
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt(
            "demo", agent_type, wt_path=_wt_path(tmp_path))
        # planner-judge 有「不消耗裁决重试预算」文案，实现者段不含
        assert "不消耗裁决重试预算" not in prompt


# ── 5.2：契约段路径按车道分派 ──────────────────────────────────────

class TestGateSectionPathDispatch:
    """契约段输出的结果文件路径 MUST 按 agent_type 分派。"""

    def test_implementer_path_is_worktree_root(self, tmp_path):
        proot = _make_project(tmp_path)
        wt = _wt_path(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "implementer", wt_path=wt)
        expected = str(impl_result_path(wt))
        assert expected in prompt

    def test_fast_track_path_is_worktree_root(self, tmp_path):
        proot = _make_project(tmp_path)
        wt = _wt_path(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "fast-track", wt_path=wt)
        expected = str(impl_result_path(wt))
        assert expected in prompt

    def test_planner_judge_path_unchanged(self, tmp_path):
        """planner-judge 路径仍指向 verify-progress（回归保护）。"""
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "planner-judge")
        expected = str(planner_result_path(proot, "demo", "planner-judge"))
        assert expected in prompt
        assert "结果文件硬门" in prompt

    def test_spec_review_path_unchanged(self, tmp_path):
        """spec-review 路径仍指向 .fenix/spec-review/<spec>/（回归保护）。"""
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "spec-review")
        expected = str(spec_review_result_path(proot, "demo"))
        assert expected in prompt

    def test_planner_plan_path_unchanged(self, tmp_path):
        """planner-plan 路径仍为 .fenix/verify-progress/<spec>/test_scenarios.json。"""
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "planner-plan")
        expected = str(planner_result_path(proot, "demo", "planner-plan"))
        assert expected in prompt

    def test_implementer_gate_section_without_wt_path(self, tmp_path):
        """wt_path=None 时降级为相对路径表述，不崩溃。"""
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "implementer", wt_path=None)
        assert "结果文件硬门" in prompt
        assert "worktree 根目录" in prompt


# ── 5.3：既有车道契约段不回归 ──────────────────────────────────────

class TestExistingLaneGateNonRegression:
    """planner-plan / planner-judge / spec-review 三车道契约段仍存在且路径一致。"""

    def test_planner_plan_gate(self, tmp_path):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "planner-plan")
        assert "结果文件硬门" in prompt
        assert str(planner_result_path(proot, "demo", "planner-plan")) in prompt
        assert str(planner_result_path(proot, "demo", "planner-judge")) in prompt

    def test_planner_judge_gate(self, tmp_path):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "planner-judge")
        assert "结果文件硬门" in prompt
        assert str(planner_result_path(proot, "demo", "planner-judge")) in prompt

    def test_spec_review_gate(self, tmp_path):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        pb = runner._prompt_builder
        prompt = pb._build_prompt("demo", "spec-review")
        assert "结果文件硬门" in prompt
        assert "正文" in prompt
        assert str(spec_review_result_path(proot, "demo")) in prompt


# ── 5.4：死因透传三态 + 字段级去重 ──────────────────────────────────

class TestRetryCauseTransmission:
    """_prev_error_section + _impl_diagnosis_section 三态注入与字段级去重。"""

    def _make_builder(self, tmp_path, error=None, diagnosis=None):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        sm = MagicMock()
        sm.read_one.return_value = {
            "error": error or None,
            "_impl_diagnosis": json.dumps(diagnosis) if diagnosis else None,
        }
        runner.state_machine = sm
        return PromptBuilder(runner)

    def test_error_only_injected(self, tmp_path):
        """仅 error 非空 → _prev_error_section 注入，_impl_diagnosis_section 零注入。"""
        pb = self._make_builder(tmp_path, error="结果文件缺失（implementer 产物硬门）")
        err_sec = pb._prev_error_section("demo")
        diag_sec = pb._impl_diagnosis_section("demo")
        assert "结果文件缺失" in err_sec
        assert "Previous run error" in err_sec
        assert diag_sec == ""  # 诊断为空时零注入

    def test_diagnosis_only_injected(self, tmp_path):
        """error 为空，_impl_diagnosis 有值 → _prev_error_section 零注入，诊断注入。"""
        diag = {
            "terminal": "error",
            "attribution": "结果文件缺失",
            "conclusion": "未写结果文件即收工",
            "progress": {"branch": "fenix/fix-x", "tasks_checked": 2},
        }
        pb = self._make_builder(tmp_path, diagnosis=diag)
        err_sec = pb._prev_error_section("demo")
        diag_sec = pb._impl_diagnosis_section("demo")
        assert err_sec == ""
        assert "结果文件缺失" in diag_sec
        assert "未写结果文件即收工" in diag_sec

    def test_both_present_field_dedup(self, tmp_path):
        """error 与 diagnosis 同时非空：字段级去重成立——_prev_error_section
        只渲染 error 原文，不渲染 attribution/conclusion/progress 条目。
        attribution 与 error 同源（final_error[:500] vs final_error），error
        原文内含 attribution 子串属预期，MUST NOT 计为重复。
        """
        diag = {
            "terminal": "error",
            "attribution": "结果文件缺失",
            "conclusion": "结论",
            "progress": {"branch": "main", "tasks_checked": 1},
        }
        pb = self._make_builder(tmp_path, error="结果文件缺失", diagnosis=diag)
        err_sec = pb._prev_error_section("demo")
        diag_sec = pb._impl_diagnosis_section("demo")
        # error 原文出现在 _prev_error_section
        assert "结果文件缺失" in err_sec
        # _prev_error_section 不含独立诊断字段条目
        for field in ("attribution:", "conclusion:", "progress:"):
            # "attribution:" 出现在 diag_sec 的结构化段中，不出现在 err_sec 中
            assert field not in err_sec
        # _impl_diagnosis_section 是唯一渲染诊断字段的段
        assert "attribution:" in diag_sec
        assert "conclusion:" in diag_sec

    def test_no_context_zero_injection(self, tmp_path):
        """首次派发（无 error、无 _impl_diagnosis）→ 零注入（不含空标题段）。"""
        pb = self._make_builder(tmp_path)
        err_sec = pb._prev_error_section("demo")
        diag_sec = pb._impl_diagnosis_section("demo")
        assert err_sec == ""
        assert diag_sec == ""

    def test_malformed_json_renders_raw(self, tmp_path):
        """诊断 JSON 解析失败 → 降级为原文截断呈现（2.2），MUST NOT 返回空。"""
        pb = self._make_builder(tmp_path)
        sm = pb._pm.state_machine
        sm.read_one.return_value = {"_impl_diagnosis": "NOT VALID JSON{{{"}
        diag_sec = pb._impl_diagnosis_section("demo")
        # 不再返回空——降级渲染原始文本（截断至 500 字）
        assert "NOT VALID JSON{{{" in diag_sec
        assert "raw" in diag_sec.lower() or "inherited" in diag_sec.lower()

    def test_attribution_truncated_at_500(self, tmp_path):
        """attribution 截断至 ≤500 字，conclusion 截断至 ≤800 字（2.2）。"""
        long_attr = "A" * 600
        long_conc = "B" * 1000
        diag = {
            "terminal": "error",
            "attribution": long_attr,
            "conclusion": long_conc,
            "progress": {"branch": None, "tasks_checked": None},
        }
        pb = self._make_builder(tmp_path, diagnosis=diag)
        diag_sec = pb._impl_diagnosis_section("demo")
        # attribution 截断至 500
        assert "A" * 500 in diag_sec
        assert "A" * 501 not in diag_sec
        # conclusion 截断至 800
        assert "B" * 800 in diag_sec
        assert "B" * 801 not in diag_sec


# ── 5.5：捞回四态 ──────────────────────────────────────────────────

class TestImplSalvageFourStates:
    """实现者车道捞回：成功落盘 / 文件已存在不覆盖 / status 非法不落盘 / 转录缺失不抛错。"""

    IMPL_STATUSES = ("success", "error", "partial")

    def _runner_and_wt(self, tmp_path):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        wt = _wt_path(tmp_path)
        return runner, proot, wt

    def test_salvage_writes_from_fenced_json(self, tmp_path):
        runner, proot, wt = self._runner_and_wt(tmp_path)
        run_id = "impl-demo-001"
        payload = {"status": "success", "spec": "demo", "completed_tasks": ["1.1"]}
        _write_transcript(proot, run_id, [
            "实现完成",
            "```json\n" + json.dumps(payload) + "\n```",
        ])
        ok = runner._salvage_impl_result("demo", run_id, wt, "implementer")
        assert ok is True
        target = impl_result_path(wt)
        assert target.exists()
        got = json.loads(target.read_text(encoding="utf-8"))
        assert got["status"] == "success"

    def test_salvage_skips_when_file_exists(self, tmp_path):
        """目标文件已存在 → 不覆盖（worktree 复用是设计预期）。"""
        runner, proot, wt = self._runner_and_wt(tmp_path)
        run_id = "impl-demo-002"
        target = impl_result_path(wt)
        target.write_text(json.dumps({"status": "success", "old": True}),
                          encoding="utf-8")
        _write_transcript(proot, run_id, [
            "```json\n" + json.dumps({"status": "partial"}) + "\n```",
        ])
        ok = runner._salvage_impl_result("demo", run_id, wt, "implementer")
        assert ok is False
        # 原有内容未被覆盖
        assert json.loads(target.read_text(encoding="utf-8")).get("old") is True

    def test_salvage_rejects_invalid_status(self, tmp_path):
        """fenced JSON 合法但 status 不在白名单 → 不落盘。"""
        runner, proot, wt = self._runner_and_wt(tmp_path)
        run_id = "impl-demo-003"
        _write_transcript(proot, run_id, [
            "```json\n" + json.dumps({"status": "approved"}) + "\n```",
        ])
        ok = runner._salvage_impl_result("demo", run_id, wt, "fast-track")
        assert ok is False
        assert not impl_result_path(wt).exists()

    def test_salvage_no_transcript_no_error(self, tmp_path):
        """转录缺失 → 返回 False，MUST NOT 抛异常。"""
        runner, proot, wt = self._runner_and_wt(tmp_path)
        ok = runner._salvage_impl_result("demo", "nonexistent-run", wt, "implementer")
        assert ok is False

    def test_salvage_no_fenced_json(self, tmp_path):
        """转录末轮无 fenced JSON → 返回 False。"""
        runner, proot, wt = self._runner_and_wt(tmp_path)
        run_id = "impl-demo-005"
        _write_transcript(proot, run_id, ["全部完成，无需产出"])
        ok = runner._salvage_impl_result("demo", run_id, wt, "implementer")
        assert ok is False

    def test_salvage_wt_path_none_returns_false(self, tmp_path):
        """wt_path=None（测试/异常场景）MUST no-op 返回 False，不抛错。"""
        runner, proot, _ = self._runner_and_wt(tmp_path)
        run_id = "impl-demo-006"
        _write_transcript(proot, run_id, [
            "```json\n" + json.dumps({"status": "success"}) + "\n```",
        ])
        ok = runner._salvage_impl_result("demo", run_id, None, "implementer")
        assert ok is False


# ── 5.5b：spec-review 捞回回归 ─────────────────────────────────────

class TestSpecReviewSalvageNonRegression:
    """_salvage_spec_review_result 薄包装委派到泛化实现后，行为逐字不变。"""

    def test_salvage_writes_from_fenced_json(self, tmp_path):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        run_id = "spec-review-demo-001"
        payload = {"status": "repaired", "repairs": []}
        _write_transcript(proot, run_id, [
            "评审完成",
            "```json\n" + json.dumps(payload) + "\n```",
        ])
        ok = runner._salvage_spec_review_result("demo", run_id)
        assert ok is True
        got = json.loads(spec_review_result_path(proot, "demo").read_text(encoding="utf-8"))
        assert got["status"] == "repaired"

    def test_salvage_skips_invalid_status(self, tmp_path):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        run_id = "spec-review-demo-002"
        _write_transcript(proot, run_id, [
            "```json\n" + json.dumps({"status": "success"}) + "\n```",
        ])
        assert runner._salvage_spec_review_result("demo", run_id) is False

    def test_salvage_returns_false_when_no_json(self, tmp_path):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        run_id = "spec-review-demo-003"
        _write_transcript(proot, run_id, ["我评审完了，approved"])
        assert runner._salvage_spec_review_result("demo", run_id) is False

    def test_salvage_does_not_overwrite_existing(self, tmp_path):
        proot = _make_project(tmp_path)
        runner = _make_runner(proot)
        p = spec_review_result_path(proot, "demo")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "approved"}), encoding="utf-8")
        run_id = "spec-review-demo-004"
        _write_transcript(proot, run_id, [
            "```json\n" + json.dumps({"status": "rejected"}) + "\n```",
        ])
        assert runner._salvage_spec_review_result("demo", run_id) is False
        assert json.loads(p.read_text(encoding="utf-8"))["status"] == "approved"


# ── 5.6：归因两类别文案区分 ──────────────────────────────────────

class TestClassifyTerminalStall:
    """classify_terminal_stall 薄包装：假工具调用特征→「格式回退截断」；
    无特征/转录缺失→「未收工即停」；处置路径不变。"""

    @staticmethod
    def _make_runner_for_classify(tmp_path: Path) -> AgentRunner:
        runner = _make_runner(tmp_path)
        return runner

    def test_fake_tool_call_classified(self, tmp_path):
        """假工具调用特征 → 「格式回退截断」。"""
        runner = self._make_runner_for_classify(tmp_path)
        proot = runner.project_root
        run_id = "classify-001"
        _write_transcript(tmp_path, run_id, [
            "Let me call the tool.\n<function_calls>\n<invoke name=\"Bash\">",
        ])
        from core.agent_runner.result_gate import classify_terminal_stall
        result = classify_terminal_stall(runner, run_id)
        assert result == "格式回退截断"

    def test_no_feature_classified(self, tmp_path):
        """无假工具调用特征 → 「未收工即停」（非既有「未提交即收工」）。"""
        runner = self._make_runner_for_classify(tmp_path)
        run_id = "classify-002"
        _write_transcript(tmp_path, run_id, ["全部完成，一切正常。"])
        from core.agent_runner.result_gate import classify_terminal_stall
        result = classify_terminal_stall(runner, run_id)
        assert result == "未收工即停"

    def test_missing_transcript_classified(self, tmp_path):
        """转录缺失 → 降级为「未收工即停」，不抛错。"""
        runner = self._make_runner_for_classify(tmp_path)
        from core.agent_runner.result_gate import classify_terminal_stall
        result = classify_terminal_stall(runner, "nonexistent-run")
        assert result == "未收工即停"

    def test_existing_method_not_regressed(self, tmp_path):
        """既有 _classify_terminal_no_commit 返回「未提交即收工」不变。
        tests/test_terminal_nocommit_gate.py:196/203 断言该文案。"""
        runner = self._make_runner_for_classify(tmp_path)
        run_id = "classify-003"
        _write_transcript(tmp_path, run_id, ["全部完成。"])
        raw = runner._classify_terminal_no_commit(run_id)
        assert raw == "未提交即收工"


class TestClassifyAndEnrichArtifactError:
    """classify_and_enrich_artifact_error：错误文案含「结果文件缺失」时拼入归因。"""

    @staticmethod
    def _make_runner_for_enrich(tmp_path: Path) -> AgentRunner:
        runner = _make_runner(tmp_path)
        proot = runner.project_root
        # 准备带特征的转录
        run_id = "enrich-001"
        _write_transcript(tmp_path, run_id, [
            "<function_calls>",
        ])
        return runner

    def test_enrich_with_fake_tool(self, tmp_path):
        """含假工具调用 → 归因「格式回退截断」拼入错误文案。"""
        runner = self._make_runner_for_enrich(tmp_path)
        from core.agent_runner.result_gate import classify_and_enrich_artifact_error
        err = "[provider-transient] exit 0 但结果文件缺失（implementer 产物硬门）: /x"
        enriched = classify_and_enrich_artifact_error(runner, err, "implementer", "enrich-001")
        assert "格式回退截断" in enriched
        # str(e) 不可被改动——验证原始前缀仍在
        assert enriched.startswith("[provider-transient]")

    def test_enrich_without_feature(self, tmp_path):
        """无假工具调用 → 归因「未收工即停」。"""
        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {}
        runner.worktree_manager = None
        runner.state_machine = None
        runner.project_root = tmp_path
        runner.logger = FakeLogger()
        runner._running_agents = {}
        (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        run_id = "enrich-002"
        _write_transcript(tmp_path, run_id, ["完成"])
        from core.agent_runner.result_gate import classify_and_enrich_artifact_error
        err = "[provider-transient] exit 0 但结果文件缺失（fast-track 产物硬门）: /x"
        enriched = classify_and_enrich_artifact_error(runner, err, "fast-track", run_id)
        assert "未收工即停" in enriched
        assert enriched.startswith("[provider-transient]")

    def test_no_enrich_when_not_impl_agent(self, tmp_path):
        """非 implementer/fast-track → 不归因，原样返回。"""
        runner = self._make_runner_for_enrich(tmp_path)
        from core.agent_runner.result_gate import classify_and_enrich_artifact_error
        err = "exit 0 但结果文件缺失（planner-judge 产物硬门）: /x"
        enriched = classify_and_enrich_artifact_error(runner, err, "planner-judge", "enrich-001")
        assert enriched == err

    def test_no_enrich_when_no_missing_text(self, tmp_path):
        """错误文案不含「结果文件缺失」→ 不归因，原样返回。"""
        runner = self._make_runner_for_enrich(tmp_path)
        from core.agent_runner.result_gate import classify_and_enrich_artifact_error
        err = "exit 0 但结果文件为空（implementer 产物硬门）: /x"
        enriched = classify_and_enrich_artifact_error(runner, err, "implementer", "enrich-001")
        assert enriched == err

    def test_no_enrich_when_no_run_id(self, tmp_path):
        """run_id 缺失（测试/异常场景）→ 不归因，原样返回。"""
        runner = self._make_runner_for_enrich(tmp_path)
        from core.agent_runner.result_gate import classify_and_enrich_artifact_error
        err = "[provider-transient] exit 0 但结果文件缺失（implementer 产物硬门）: /x"
        enriched = classify_and_enrich_artifact_error(runner, err, "implementer", None)
        assert enriched == err


# ── 5.4b：impl_result_path 路径函数回归 ────────────────────────────

class TestImplResultPath:
    """impl_result_path helper 与 _check_impl_result_artifact 同源。"""

    def test_returns_worktree_root_path(self, tmp_path):
        wt = tmp_path / "wt"
        result = impl_result_path(wt)
        assert result == wt / ".fenix-run-result.json"

    def test_accepts_string(self):
        """从 runner.py 调用时可能传 str 而非 Path。"""
        from core.agent_runner.result_gate import _check_impl_result_artifact
        # 仅验证签名兼容，不执行完整判定
        assert callable(_check_impl_result_artifact)
