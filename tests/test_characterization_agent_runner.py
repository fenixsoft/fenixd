"""characterization tests — refactor-agent-runner-module 阶段 0（tasks 1.2）。

锁定拆分重构 MUST NOT 改变的行为契约（spec「拆分零行为变化」Scenario）：
- 四个结果类的构造参数与 `to_dict()` 输出逐字段不变；
- 产物门族的判定行为与失败归因文案不含关键语义漂移（缺失/空/非法 JSON/
  陈旧/白名单外/完成度判据）。

这些断言面向**公共行为**而非内部实现——重构后结果类迁往 result_gate.py、
产物门迁往 result_gate.py 并经 AgentRunner 保留一行委托后，本文件 MUST
仍然全部通过。
"""

import json
import time
from pathlib import Path

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.runner import (
    AdminDisposition,
    AgentRunResult,
    EvolutionResult,
    SelfReviewResult,
)
from tests.helpers import FakeLogger, make_runner


# ── 结果类构造与 to_dict 字段锁定 ─────────────────────────────

class TestResultClassesChar:
    """四个结果类：构造字段 ↔ to_dict 输出逐字段锁定。"""

    def test_agent_run_result_to_dict_fields(self):
        r = AgentRunResult(
            run_id="impl-demo-1780000000-a1",
            spec_name="demo",
            agent_type="implementer",
            success=True,
            duration_seconds=12.5,
            turns_used=3,
            error=None,
            output="done" * 300,  # >500 chars，验证 output_summary 截断
            branch="fenix/demo-123",
            provider_used="inferaiapi.com",
            model_used="deepseek-v4-flash",
            chain_exhausted=False,
            worktree_dirty=["a.py"],
            worktree_path=Path("/wt"),
            worktree_kept=False,
            cancelled=False,
        )
        d = r.to_dict()
        assert d == {
            "run_id": "impl-demo-1780000000-a1",
            "spec_name": "demo",
            "agent_type": "implementer",
            "success": True,
            "duration_seconds": 12.5,
            "turns_used": 3,
            "error": None,
            "branch": "fenix/demo-123",
            "provider_used": "inferaiapi.com",
            "model_used": "deepseek-v4-flash",
            "chain_exhausted": False,
            "cancelled": False,
            "frozen_terminated": False,
            "output_summary": ("done" * 300)[-500:],
        }

    def test_agent_run_result_defaults(self):
        r = AgentRunResult(run_id="x", spec_name="s", agent_type="a",
                           success=True, duration_seconds=1.0)
        d = r.to_dict()
        assert d["turns_used"] == 0
        assert d["error"] is None
        assert d["output_summary"] == ""
        assert d["branch"] is None
        assert d["provider_used"] is None
        assert d["model_used"] is None
        assert d["chain_exhausted"] is False
        assert d["cancelled"] is False
        # 暴露的属性与 to_dict 一致
        assert (r.worktree_dirty, r.worktree_path, r.worktree_kept) == \
            (None, None, False)

    def test_admin_disposition_to_dict_fields(self):
        a = AdminDisposition(
            run_id="admin-demo-1780000000",
            spec="demo",
            success=False,
            problem="p",
            actions_taken="at",
            result="failed",
            escalate=True,
            recommended_action="ra",
            summary="sm",
            error="boom",
            output="out",
            family_waiver=True,
        )
        d = a.to_dict()
        assert d == {
            "run_id": "admin-demo-1780000000",
            "spec": "demo",
            "success": False,
            "problem": "p",
            "actions_taken": "at",
            "result": "failed",
            "escalate": True,
            "recommended_action": "ra",
            "summary": "sm",
            "error": "boom",
        }
        assert a.family_waiver is True  # 内部字段，不进 to_dict

    def test_admin_disposition_defaults(self):
        a = AdminDisposition(run_id="r")
        d = a.to_dict()
        assert d["spec"] is None and d["success"] is True
        assert d["problem"] == "" and d["actions_taken"] == ""
        assert d["result"] == "" and d["escalate"] is False
        assert d["recommended_action"] == "" and d["summary"] == ""
        assert d["error"] == ""

    def test_self_review_result_fields(self):
        s = SelfReviewResult(
            run_id="review-2026-09-16",
            date="2026-09-16",
            success=True,
            waste=[{"impact": "w1"}],
            mistakes=["m1"],
            improvements=None,
            summary="sm",
            resolved=[{"id": "1.1", "reason": "closed"}],
            error="",
            output="o",
        )
        assert s.waste == [{"impact": "w1"}]
        assert s.mistakes == ["m1"]
        assert s.improvements == []  # None → 空列表
        assert s.resolved == [{"id": "1.1", "reason": "closed"}]
        # 列表字段构造时拷贝，不共享引用
        waste = [1]
        s2 = SelfReviewResult(run_id="r2", waste=waste)
        waste.append(2)
        assert s2.waste == [1]

    def test_evolution_result_fields(self):
        e = EvolutionResult(
            run_id="evo-1780000000",
            success=True,
            items_ingested=3,
            drafts=1,
            accepted=2,
            degraded=None,
            error="",
            output="o",
        )
        assert e.items_ingested == 3 and e.drafts == 1
        assert e.accepted == 2 and e.degraded is None
        e2 = EvolutionResult(run_id="")
        assert e2.items_ingested == 0 and e2.success is True


# ── 产物门族判定行为锁定 ─────────────────────────────────────

ALL_BLOCKED_TEXT = ("缺失", "为空", "非法 JSON", "不可读", "顶层非对象",
                    "不在白名单")


def _runner_with_planner(proot: Path) -> AgentRunner:
    """直调产物门需的最小 runner（helpers.make_runner 已含转发属性初始化）。"""
    from core.agent_runner.prompt_builder import planner_result_path
    return make_runner(proot)


class TestArtifactJsonFileChar:
    """_check_artifact_json_file：存在/空/非法/陈旧/合法。"""

    def _gate(self, proot: Path, payload, mtime_fresh=True):
        r = _runner_with_planner(proot)
        p = proot / "artifact.json"
        if payload is not None:
            if isinstance(payload, (dict, list)):
                p.write_text(json.dumps(payload), encoding="utf-8")
            else:
                p.write_text(payload, encoding="utf-8")
            if not mtime_fresh:
                old = time.time() - 120
                os_utime(p, old)
        run_started_at = None if mtime_fresh else time.time()
        return r._check_artifact_json_file(p, "planner-judge", run_started_at)

    def test_missing_file(self, tmp_path):
        r = _runner_with_planner(tmp_path)
        err, data = r._check_artifact_json_file(
            tmp_path / "nope.json", "planner-judge", None)
        assert err is not None and "缺失" in err

    def test_empty_file(self, tmp_path):
        err, _ = self._gate(tmp_path, "")
        assert err is not None and "为空" in err and "产物硬门" in err

    def test_invalid_json(self, tmp_path):
        err, _ = self._gate(tmp_path, "not-json{{{")
        assert err is not None and "非法 JSON" in err

    def test_stale_mtime(self, tmp_path):
        err, _ = self._gate(tmp_path, {"status": "verified"}, mtime_fresh=False)
        assert err is not None and "陈旧残留" in err
        assert err is not None and "grace" in err

    def test_fresh_valid_dict(self, tmp_path):
        err, data = self._gate(tmp_path, {"status": "verified"})
        assert err is None
        assert data == {"status": "verified"}


class TestPlannerArtifactGateChar:
    """_check_agent_result_artifact：planner-judge / planner-plan / spec-review 分支。"""

    def _planner_judge_file(self, proot: Path, spec: str, payload,
                            mtime_fresh=True):
        from core.agent_runner.prompt_builder import planner_result_path
        p = planner_result_path(proot, spec, "planner-judge")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")
        if not mtime_fresh:
            os_utime(p, time.time() - 120)
        return p

    def test_planner_judge_ok(self, tmp_path):
        r = _runner_with_planner(tmp_path)
        self._planner_judge_file(tmp_path, "demo", {"status": "verified"})
        assert r._check_agent_result_artifact("demo", "planner-judge", None) is None

    def test_planner_judge_missing(self, tmp_path):
        r = _runner_with_planner(tmp_path)
        err = r._check_agent_result_artifact("demo", "planner-judge", None)
        assert err is not None and "缺失" in err

    def test_planner_judge_bad_status(self, tmp_path):
        r = _runner_with_planner(tmp_path)
        self._planner_judge_file(tmp_path, "demo", {"status": "success"})
        err = r._check_agent_result_artifact("demo", "planner-judge", None)
        assert err is not None and "status='success'" in err
        assert err is not None and "不在白名单" in err

    def test_planner_judge_stale(self, tmp_path):
        r = _runner_with_planner(tmp_path)
        self._planner_judge_file(tmp_path, "demo", {"status": "verified"},
                                 mtime_fresh=False)
        err = r._check_agent_result_artifact("demo", "planner-judge", time.time())
        assert err is not None and "陈旧残留" in err

    def test_planner_judge_top_level_not_dict(self, tmp_path):
        from core.agent_runner.prompt_builder import planner_result_path
        p = planner_result_path(tmp_path, "demo", "planner-judge")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('["a"]', encoding="utf-8")
        r = _runner_with_planner(tmp_path)
        err = r._check_agent_result_artifact("demo", "planner-judge", None)
        assert err is not None and "顶层非对象" in err

    def test_planner_plan_requires_both(self, tmp_path):
        from core.agent_runner.prompt_builder import planner_result_path
        r = _runner_with_planner(tmp_path)
        # 只有 .fenix-run-result.json（plan-ready）没有 test_scenarios.json → 拦截
        result = planner_result_path(tmp_path, "demo", "planner-judge")
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps({"status": "plan-ready"}), encoding="utf-8")
        err = r._check_agent_result_artifact("demo", "planner-plan", None)
        assert err is not None and "缺失" in err
        # 双产物齐备 plan-ready → 通过
        sc = planner_result_path(tmp_path, "demo", "planner-plan")
        sc.write_text(json.dumps({"scenarios": []}), encoding="utf-8")
        assert r._check_agent_result_artifact("demo", "planner-plan", None) is None
        # 结果文件 status 白名单外（verified）→ 拦截
        result.write_text(json.dumps({"status": "verified"}), encoding="utf-8")
        err = r._check_agent_result_artifact("demo", "planner-plan", None)
        assert err is not None and "status='verified'" in err

    def test_spec_review_gate(self, tmp_path):
        from core.agent_runner.prompt_builder import spec_review_result_path
        r = _runner_with_planner(tmp_path)
        # 结果文件缺失 → 拦截
        err = r._check_agent_result_artifact("demo", "spec-review", None)
        assert err is not None and "缺失" in err
        # 白名单内 status（approved）→ 通过
        p = spec_review_result_path(tmp_path, "demo")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "approved"}), encoding="utf-8")
        assert r._check_agent_result_artifact("demo", "spec-review", None) is None
        # 白名单外（verified）→ 拦截
        p.write_text(json.dumps({"status": "verified"}), encoding="utf-8")
        err = r._check_agent_result_artifact("demo", "spec-review", None)
        assert err is not None and "status='verified'" in err

    def test_unsupported_agent_type(self, tmp_path):
        r = _runner_with_planner(tmp_path)
        # 无产物契约的 agent_type → None（空阀保留）
        assert r._check_agent_result_artifact("demo", "verifier", None) is None


# ── implementer 结果产物硬门（success/partial 完成度判据）────

TASKS_ALL_DONE = "## 1. 阶段\n\n- [x] 1.1 甲\n- [x] 1.2 乙\n"
TASKS_PARTIAL = "## 1. 阶段\n\n- [x] 1.1 甲\n- [ ] 1.2 乙\n"
TASKS_WITH_SUFFIX = "## 1. 阶段\n\n- [x] 1.1 甲\n- [x] 1.2b 乙b\n"


def _wt(proot: Path, tasks_text: str) -> Path:
    wt = proot / "wt"
    (wt / "spec" / "changes" / "demo").mkdir(parents=True, exist_ok=True)
    (wt / "spec" / "changes" / "demo" / "tasks.md").write_text(
        tasks_text, encoding="utf-8")
    return wt


def _set_result(wt: Path, payload) -> None:
    (wt / ".fenix-run-result.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestImplArtifactGateChar:
    """_check_impl_result_artifact + _check_success_completion /
    _check_partial_consistency 判定行为。"""

    def _runner(self, proot: Path) -> AgentRunner:
        return make_runner(proot)

    def test_impl_missing_result(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_ALL_DONE)
        err = r._check_impl_result_artifact("demo", None, wt)
        assert err is not None and "结果文件缺失" in err

    def test_impl_empty_result(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_ALL_DONE)
        (wt / ".fenix-run-result.json").write_text("", encoding="utf-8")
        err = r._check_impl_result_artifact("demo", None, wt)
        assert err is not None and "结果文件为空" in err

    def test_impl_status_error_passes(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_PARTIAL)
        _set_result(wt, {"status": "error", "error": "x"})
        assert r._check_impl_result_artifact("demo", None, wt) is None

    def test_success_full_done(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_ALL_DONE)
        _set_result(wt, {"status": "success", "completed_tasks": ["1.1", "1.2"]})
        assert r._check_impl_result_artifact("demo", None, wt) is None

    def test_success_unchecked_blocked(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_PARTIAL)
        _set_result(wt, {"status": "success", "completed_tasks": ["1.1"]})
        err = r._check_impl_result_artifact("demo", None, wt)
        assert err is not None and "未勾选数字任务" in err
        assert err is not None and "缺口: 1.2" in err

    def test_success_missing_completed_tasks_blocked(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_ALL_DONE)
        _set_result(wt, {"status": "success", "spec": "demo"})
        err = r._check_impl_result_artifact("demo", None, wt)
        assert err is not None and "缺 completed_tasks" in err

    def test_success_mismatch_blocked(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_ALL_DONE)
        _set_result(wt, {"status": "success", "completed_tasks": ["1.1"]})
        err = r._check_impl_result_artifact("demo", None, wt)
        assert err is not None and "缺项: 1.2" in err

    def test_success_invalid_id_blocked(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_ALL_DONE)
        _set_result(wt, {"status": "success",
                         "completed_tasks": ["1.1", "not-an-id"]})
        err = r._check_impl_result_artifact("demo", None, wt)
        assert err is not None and "非法任务 id" in err

    def test_success_letter_suffix_id_ok(self, tmp_path):
        """字母后缀任务 id（1.2b）是合法形态，不判非法。"""
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_WITH_SUFFIX)
        _set_result(wt, {"status": "success",
                         "completed_tasks": ["1.1", "1.2b"]})
        assert r._check_impl_result_artifact("demo", None, wt) is None

    def test_partial_consistent(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_PARTIAL)
        _set_result(wt, {"status": "partial", "completed_tasks": ["1.1"],
                         "unfinished": ["1.2"]})
        assert r._check_impl_result_artifact("demo", None, wt) is None

    def test_partial_inconsistent(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_PARTIAL)
        # unfinished 与实际未勾选（[1.2]）不一致 → 拦截
        _set_result(wt, {"status": "partial", "completed_tasks": ["1.1"],
                         "unfinished": ["1.1"]})
        err = r._check_impl_result_artifact("demo", None, wt)
        assert err is not None and "申报一致性判据" in err

    def test_partial_overlap_blocked(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_PARTIAL)
        _set_result(wt, {"status": "partial", "completed_tasks": ["1.1", "1.2"],
                         "unfinished": ["1.2"]})
        err = r._check_impl_result_artifact("demo", None, wt)
        assert err is not None and "交集非空" in err

    def test_no_numeric_tasks_passes(self, tmp_path):
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, "## 1. 阶段\n\n- [ ] 功能清单完善\n")
        _set_result(wt, {"status": "success", "spec": "demo"})
        assert r._check_impl_result_artifact("demo", None, wt) is None

    def test_taskupdate_crosscheck_skipped_without_run_file(self, tmp_path):
        """无 run 产物（find_impl_run_file → None）→ fail-open 跳过交叉核对。"""
        r = self._runner(tmp_path)
        wt = _wt(tmp_path, TASKS_ALL_DONE)
        _set_result(wt, {"status": "success", "completed_tasks": ["1.1", "1.2"]})
        assert r._check_impl_result_artifact("demo", None, wt) is None


def os_utime(p: Path, ts: float) -> None:
    import os
    os.utime(p, (ts, ts))