"""spec-review 结果产物硬门 + 转录捞回 + 重试上下文回归。

2026-09-15 evo-stuck-signal-hygiene 事故：评审 run 正常收工（exit 0 +
result.success）却**从未调用 Write**——模型把结果 JSON 当正文 fenced 代码块
吐出，end_turn 自然完成。四个缺口：

1. spec-review 从未收到「不写结果文件 = run 失败」的硬门契约段
   （planner 车道有 `_result_gate_section`，spec-review 分支没有）；
2. `_check_agent_result_artifact` 对 `spec-review` 直接 return None（空阀）；
3. 重试派发不注入上轮死因（`_prev_error_section` 只给 implementer/fast-track），
   第二轮盲重试；
4. 正文里那份合法 JSON 无人捞回，白烧一轮 token 重试。

覆盖：
- G1 prompt 硬门契约段（含结果路径与「正文 JSON 不算交付」措辞）
- G2 runner 硬门对 spec-review 真接线（缺失/空/非白名单 status/陈旧 mtime）
- G3 转录末轮 fenced JSON 捞回落盘；无 JSON / 已有文件不覆盖
- G4 重试派发注入上轮 error
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner


def _stub_pm():
    """MagicMock pm_engine + is_review_in_flight stub（fix-spec-review-blocking-dispatch）。

    dispatch_review 入口新增 `pm_engine.is_review_in_flight` 在飞判据；裸 MagicMock
    对其调用返回 MagicMock（真值）会把 dispatch_review 拒派。此处 stub 为 False
    （无在飞评审），使测试聚焦于既有评审语义。
    """
    m = MagicMock()
    m.is_review_in_flight = MagicMock(return_value=False)
    return m


from core.agent_runner.prompt_builder import (
    AGENT_PROMPT_DIR,
    spec_review_result_path,
)
from tests.helpers import FakeLogger


def _make_runner(tmp_path: Path, config: dict | None = None) -> AgentRunner:
    """最小 runner（test_planready_artifact_gate 同款）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = tmp_path
    runner.logger = FakeLogger()
    runner._running_agents = {}
    (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return runner


def _write_transcript(tmp_path: Path, run_id: str, texts: list[str]) -> Path:
    """写一份 run 转录，texts 依次作为 assistant text 块。"""
    p = tmp_path / ".fenix" / "runs" / f"{run_id}.jsonl"
    lines = [{"type": "system", "subtype": "init"}]
    for t in texts:
        lines.append({"type": "assistant",
                      "message": {"content": [{"type": "text", "text": t}]}})
    lines.append({"type": "result", "subtype": "success", "num_turns": 5})
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
                 encoding="utf-8")
    return p


# ── G1：prompt 硬门契约段 ────────────────────────────────────────────


class TestSpecReviewPromptGateContract:
    def test_build_prompt_includes_gate_section(self, tmp_path):
        """spec-review prompt MUST 携带「结果文件落盘=成功判据」硬门段。"""
        proot = tmp_path / "proj"
        (proot / "spec" / "changes" / "demo").mkdir(parents=True)
        (proot / "spec" / "changes" / "demo" / "tasks.md").write_text(
            "- [ ] 1.1 x\n", encoding="utf-8")
        runner = _make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("demo", "spec-review")
        result_path = str(spec_review_result_path(proot, "demo"))
        assert result_path in prompt
        # 硬门语义：不写文件即判失败，且明确「正文里的 JSON 不算交付」
        assert "结果文件硬门" in prompt
        assert "判**失败**" in prompt or "判失败" in prompt
        assert "正文" in prompt

    def test_agent_file_uses_write_tool_wording(self):
        """agents/spec-review.md 输出段 MUST 要求用 Write 工具落盘。"""
        text = (AGENT_PROMPT_DIR / "spec-review.md").read_text(encoding="utf-8")
        assert "Write" in text
        assert "结果文件未落盘" in text


# ── G2：runner 硬门对 spec-review 真接线 ─────────────────────────────


class TestSpecReviewArtifactGate:
    def test_missing_result_file_intercepted(self, tmp_path):
        runner = _make_runner(tmp_path)
        err = runner._check_agent_result_artifact("demo", "spec-review")
        assert err is not None
        assert "结果文件缺失" in err

    def test_empty_result_file_intercepted(self, tmp_path):
        runner = _make_runner(tmp_path)
        p = spec_review_result_path(tmp_path, "demo")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
        err = runner._check_agent_result_artifact("demo", "spec-review")
        assert err is not None
        assert "为空" in err

    def test_status_out_of_whitelist_intercepted(self, tmp_path):
        runner = _make_runner(tmp_path)
        p = spec_review_result_path(tmp_path, "demo")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "success"}), encoding="utf-8")
        err = runner._check_agent_result_artifact("demo", "spec-review")
        assert err is not None
        assert "success" in err and "白名单" in err

    def test_stale_result_file_intercepted(self, tmp_path):
        runner = _make_runner(tmp_path)
        p = spec_review_result_path(tmp_path, "demo")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "approved"}), encoding="utf-8")
        old = time.time() - 3600
        import os
        os.utime(p, (old, old))
        err = runner._check_agent_result_artifact(
            "demo", "spec-review", run_started_at=time.time())
        assert err is not None
        assert "陈旧" in err

    def test_healthy_result_file_passes(self, tmp_path):
        runner = _make_runner(tmp_path)
        p = spec_review_result_path(tmp_path, "demo")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "approved", "repairs": []}),
                     encoding="utf-8")
        assert runner._check_agent_result_artifact("demo", "spec-review") is None


# ── G3：转录末轮 fenced JSON 捞回 ────────────────────────────────────


class TestSalvageFromTranscript:
    def test_salvage_writes_file_from_fenced_json(self, tmp_path):
        runner = _make_runner(tmp_path)
        run_id = "spec-review-demo-123"
        payload = {"status": "repaired",
                   "repairs": [{"path": "spec/changes/demo/tasks.md",
                                "summary": "x"}]}
        _write_transcript(tmp_path, run_id, [
            "分析中……",
            "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```",
        ])
        ok = runner._salvage_spec_review_result("demo", run_id)
        assert ok is True
        got = json.loads(spec_review_result_path(tmp_path, "demo").read_text(
            encoding="utf-8"))
        assert got["status"] == "repaired"

    def test_salvage_returns_false_when_no_json(self, tmp_path):
        runner = _make_runner(tmp_path)
        run_id = "spec-review-demo-124"
        _write_transcript(tmp_path, run_id, ["我评审完了，结论是 approved。"])
        assert runner._salvage_spec_review_result("demo", run_id) is False
        assert not spec_review_result_path(tmp_path, "demo").exists()

    def test_salvage_skips_invalid_status(self, tmp_path):
        """fenced JSON 存在但 status 不在白名单 → 不落盘（避免放行语义错位）。"""
        runner = _make_runner(tmp_path)
        run_id = "spec-review-demo-125"
        _write_transcript(tmp_path, run_id,
                          ["```json\n" + json.dumps({"status": "success"}) + "\n```"])
        assert runner._salvage_spec_review_result("demo", run_id) is False

    def test_salvage_does_not_overwrite_existing(self, tmp_path):
        runner = _make_runner(tmp_path)
        run_id = "spec-review-demo-126"
        p = spec_review_result_path(tmp_path, "demo")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "approved", "repairs": []}),
                     encoding="utf-8")
        _write_transcript(tmp_path, run_id,
                          ["```json\n" + json.dumps({"status": "rejected"}) + "\n```"])
        assert runner._salvage_spec_review_result("demo", run_id) is False
        assert json.loads(p.read_text(encoding="utf-8"))["status"] == "approved"

    def test_salvage_picks_last_json_block(self, tmp_path):
        """多个 JSON 块时取最后一条 assistant text 的那个（末轮即结论）。"""
        runner = _make_runner(tmp_path)
        run_id = "spec-review-demo-127"
        _write_transcript(tmp_path, run_id, [
            "```json\n" + json.dumps({"status": "approved", "repairs": []}) + "\n```",
            "重新考量后：\n```json\n" + json.dumps({"status": "rejected"}) + "\n```",
        ])
        assert runner._salvage_spec_review_result("demo", run_id) is True
        got = json.loads(spec_review_result_path(tmp_path, "demo").read_text(
            encoding="utf-8"))
        assert got["status"] == "rejected"


# ── G4：重试派发注入上轮死因 ─────────────────────────────────────────


class TestSpecReviewRetryContext:
    def test_prev_error_injected_for_spec_review(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / "spec" / "changes" / "demo").mkdir(parents=True)
        (proot / "spec" / "changes" / "demo" / "tasks.md").write_text(
            "- [ ] 1.1 x\n", encoding="utf-8")
        runner = _make_runner(proot)
        sm = MagicMock()
        sm.read_one.return_value = {
            "error": "spec-review-incomplete: 结果文件读取失败: No such file"}
        runner.state_machine = sm
        prompt = runner._prompt_builder._build_prompt("demo", "spec-review")
        assert "结果文件读取失败" in prompt

    def test_no_error_no_injection(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / "spec" / "changes" / "demo").mkdir(parents=True)
        (proot / "spec" / "changes" / "demo" / "tasks.md").write_text(
            "- [ ] 1.1 x\n", encoding="utf-8")
        runner = _make_runner(proot)
        sm = MagicMock()
        sm.read_one.return_value = {"error": None}
        runner.state_machine = sm
        prompt = runner._prompt_builder._build_prompt("demo", "spec-review")
        assert "Previous run error" not in prompt


# ── G5：dispatch_review 接线（捞回 + 新鲜度）─────────────────────────


class TestDispatchSalvageWiring:
    def _mk_spec(self, tmp_path):
        from core.state_machine import StateMachine
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(tmp_path / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("demo", {"status": "reviewing", "reviewer_run": None})
        d = tmp_path / "spec" / "changes" / "demo"
        d.mkdir(parents=True, exist_ok=True)
        (d / "tasks.md").write_text("- [ ] 1.1 x\n", encoding="utf-8")
        return sm

    def test_dispatch_calls_salvage_before_consume(self, tmp_path):
        """run 收工后 MUST 先尝试捞回，再消费结果。"""
        from core.pm_engine.spec_review import SpecReviewManager

        sm = self._mk_spec(tmp_path)
        calls = []

        class _R:
            def _check_agent_result_artifact(self, s, t, run_started_at=None,
                                             wt_path=None):
                return None

            def _salvage_spec_review_result(self, spec_name, run_id):
                calls.append(("salvage", spec_name, run_id))
                p = spec_review_result_path(tmp_path, spec_name)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"status": "approved", "repairs": []}),
                             encoding="utf-8")
                return True

            def run_spec_review(self, spec_name, run_id=None):
                return MagicMock(success=True, run_id=run_id)

            # fix-spec-review-blocking-dispatch：dispatch_review 入口在飞守卫
            # 会在 reviewer_run 非空时调 agent_runner.reviewer_in_flight。
            def reviewer_in_flight(self, spec_name, reviewer_run):
                return (False, None)

        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        mgr = SpecReviewManager(tmp_path, sm, _R(), engine, {}, MagicMock())
        assert mgr.dispatch_review("demo") is True
        assert calls and calls[0][0] == "salvage"
        assert sm.read_one("demo")["status"] == "ready"

    def test_dispatch_passes_run_started_at_to_consume(self, tmp_path):
        """consume 必须收到非 None 的 run_started_at（新鲜度守卫不空转）。"""
        from core.pm_engine.spec_review import SpecReviewManager

        sm = self._mk_spec(tmp_path)
        seen = {}

        class _R:
            def _check_agent_result_artifact(self, s, t, run_started_at=None,
                                             wt_path=None):
                seen["run_started_at"] = run_started_at
                return "stub-fail"

            def run_spec_review(self, spec_name, run_id=None):
                return MagicMock(success=True, run_id=run_id)

            # fix-spec-review-blocking-dispatch：dispatch_review 入口在飞守卫
            # 会在 reviewer_run 非空时调 agent_runner.reviewer_in_flight。
            def reviewer_in_flight(self, spec_name, reviewer_run):
                return (False, None)

        mgr = SpecReviewManager(tmp_path, sm, _R(), _stub_pm(), {}, MagicMock())
        mgr.dispatch_review("demo")
        assert seen.get("run_started_at") is not None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))