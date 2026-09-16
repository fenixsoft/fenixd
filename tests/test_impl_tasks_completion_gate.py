"""implementer/fast-track 结果产物硬门测试（fix-impl-tasks-completion-gate）。

覆盖 spec「结果产物硬门」全部 Scenario：
- 结果文件缺失 / 为空 / 非法 JSON / 顶层非对象 / status 白名单外 → 拦截；
- 健康轮次（success + 完成度判据通过）→ 放行；
- success 未勾任务残留（事故回归）→ 拦截且归因含缺口 id；
- completed_tasks 缺项/多项/缺失 → 拦截；
- partial 申报不一致 → 拦截；申报一致 → 放行；
- error 不施加完成度类判据；
- 无数字任务 SPEC → 放行；
- 能力探测：init.tools 含 TaskCreate 且 done_ids 不覆盖 → 拦截；
  init.tools 不含 → 放行且写 impl-task-crosscheck-skipped 审计事件；init 不可得 → 放行。
- 新鲜度（fix-artifact-freshness-resume）：新建 worktree 首轮 mtime 早于本轮 → 拦截；
  复用 worktree（is_resumed_worktree）→ 跳过 mtime 硬拦、交内容判据（2026-09-15/16 修复轮秒退事故回归）。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_agent_runner import make_runner


def _mk_worktree(proot: Path, spec: str, *, tasks_text: str) -> Path:
    """构造实现者 worktree（含 spec/changes/<spec>/tasks.md）。"""
    wt = proot / "wt"
    (wt / "spec" / "changes" / spec).mkdir(parents=True, exist_ok=True)
    (wt / "spec" / "changes" / spec / "tasks.md").write_text(
        tasks_text, encoding="utf-8")
    return wt


def _write_result(wt: Path, payload: dict | str) -> None:
    if isinstance(payload, str):
        (wt / ".fenix-run-result.json").write_text(payload, encoding="utf-8")
    else:
        (wt / ".fenix-run-result.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _mk_run_file(proot: Path, spec: str, *, tools=None) -> None:
    """写 impl run 产物（能力探测的 init.tools 数据源）。"""
    runs = proot / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "system", "subtype": "init", "tools": tools or []}]
    (runs / f"impl-{spec}-1780000000.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
        encoding="utf-8")


def _mk_run(proot: Path, spec: str, *, name: str, tools=None,
            events=None) -> None:
    """写一个具名 impl run 产物（epoch 家族由 name 决定）。

    Args:
        name: run 文件名（如 ``impl-demo-1780000001-a1.jsonl``）。
        tools: init 事件 tools 数组。
        events: assistant 事件的 content block 列表（如 TaskCreate/TaskUpdate）。
    """
    runs = proot / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "system", "subtype": "init", "tools": tools or []}]
    if events:
        lines.append({"type": "assistant", "message": {"content": events}})
    (runs / name).write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
        encoding="utf-8")


ALL_DONE_TASKS = "## 1. 阶段一\n\n- [x] 1.1 任务一\n- [x] 1.2 任务二\n"
PARTIAL_TASKS = "## 1. 阶段一\n\n- [x] 1.1 任务一\n- [ ] 1.2 任务二\n"
NO_NUMERIC_TASKS = "## 1. 阶段一\n\n- [ ] 功能清单完善\n"


class TestImplResultGate(unittest.TestCase):
    """结果产物硬门：基础校验各失败形态与放行。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        self.runner = make_runner(self.proot)
        self.spec = "demo"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _gate(self, tasks_text=ALL_DONE_TASKS, payload=None, spec=None,
              *, run_started_at=None, is_resumed_worktree=False):
        wt = _mk_worktree(self.proot, spec or self.spec, tasks_text=tasks_text)
        if payload is not None:
            _write_result(wt, payload)
        return self.runner._check_impl_result_artifact(
            spec or self.spec, run_started_at, wt,
            is_resumed_worktree=is_resumed_worktree)

    # ── 基础校验 ─────────────────────────────────────────────

    def test_missing_result_file_blocked(self):
        """结果文件缺失 → 拦截（含 worktree 路径）。"""
        err = self._gate(payload=None)
        assert err is not None
        assert "结果文件缺失" in err
        assert ".fenix-run-result.json" in err

    # ── 新鲜度：新建 worktree 首轮硬拦 vs 复用 worktree 放行 ────
    # 2026-09-15/16 事故：已完工 worktree 复用做修复轮，agent 判定「无需动作」
    # 不重写结果文件 → mtime 停在上一轮 → 旧实现对所有轮硬拦 → 秒退死循环。

    def _stale_gate(self, *, is_resumed_worktree):
        import os
        import time as _time
        from test_agent_runner import make_runner  # noqa: F401
        wt = _mk_worktree(self.proot, self.spec, tasks_text=ALL_DONE_TASKS)
        _write_result(wt, {"status": "success", "spec": self.spec,
                           "completed_tasks": ["1.1", "1.2"]})
        old = _time.time() - 3600  # 结果文件 mtime 远早于本轮启动
        os.utime(wt / ".fenix-run-result.json", (old, old))
        return self.runner._check_impl_result_artifact(
            self.spec, _time.time(), wt,
            is_resumed_worktree=is_resumed_worktree)

    def test_fresh_worktree_stale_artifact_blocked(self):
        """新建 worktree 首轮 + 陈旧结果文件 → 仍拦截（防旧文件冒充本轮）。"""
        err = self._stale_gate(is_resumed_worktree=False)
        assert err is not None
        assert "早于本轮启动" in err

    def test_resumed_worktree_stale_artifact_passes(self):
        """复用 worktree（resume/修复轮）+ 陈旧结果文件 → 放行（交内容判据）。

        回归：worktree 复用做修复轮时结果文件本就早于本轮；跳过 mtime 硬拦，
        内容判据（success + completed_tasks 与 tasks.md 全勾一致）自然通过。
        """
        err = self._stale_gate(is_resumed_worktree=True)
        assert err is None

    def test_empty_result_file_blocked(self):
        err = self._gate(payload="")
        assert err is not None
        assert "结果文件为空" in err

    def test_invalid_json_blocked(self):
        err = self._gate(payload="not-json{{{")
        assert err is not None
        assert "非法 JSON" in err

    def test_top_level_array_blocked(self):
        """顶层为数组 → 顶层非对象类别拦截。"""
        err = self._gate(payload='["a", "b"]')
        assert err is not None
        assert "顶层非对象" in err

    def test_status_outside_whitelist_blocked(self):
        """status 白名单外（如 plan-ready/verified）→ 拦截且归因含真实 status。"""
        err = self._gate(payload={"status": "plan-ready", "spec": self.spec})
        assert err is not None
        assert "status='plan-ready'" in err
        assert "不在白名单" in err

    def test_status_present_failure(self):
        """status=error → 不施加任何完成度类判据（带未勾任务也放行）。"""
        err = self._gate(
            tasks_text=PARTIAL_TASKS,
            payload={"status": "error", "spec": self.spec, "error": "bug"},
        )
        assert err is None

    def test_no_numeric_tasks_spec_passes(self):
        """无数字任务的 SPEC：勾选清零通过、completed_tasks 空/缺失均通过。"""
        assert self._gate(
            tasks_text=NO_NUMERIC_TASKS,
            payload={"status": "success", "spec": self.spec},
        ) is None
        assert self._gate(
            tasks_text=NO_NUMERIC_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": []},
        ) is None

    # ── success 完成度判据 ───────────────────────────────────

    def test_success_unchecked_tasks_blocked(self):
        """事故回归：status=success 但 tasks.md 有未勾任务 → 拦截且含缺口 id。"""
        err = self._gate(
            tasks_text=PARTIAL_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1"]},
        )
        assert err is not None
        assert "未勾选数字任务" in err
        assert "1.2" in err

    def test_success_missing_completed_tasks_blocked(self):
        """status=success、tasks.md 全勾但无 completed_tasks 键 → 拦截。"""
        err = self._gate(payload={"status": "success", "spec": self.spec})
        assert err is not None
        assert "completed_tasks" in err

    def test_success_extra_completed_tasks_blocked(self):
        """completed_tasks 含未勾任务（多项）→ 拦截含 id。"""
        err = self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2", "9.9"]},
        )
        assert err is not None
        assert "多项" in err
        assert "9.9" in err

    def test_success_missing_checked_task_blocked(self):
        """completed_tasks 缺列已勾任务（缺项）→ 拦截含缺口 id。"""
        err = self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1"]},
        )
        assert err is not None
        assert "缺项" in err
        assert "1.2" in err

    def test_success_non_numeric_id_blocked(self):
        """completed_tasks 含非法任务 id → 拦截且归因点名该 id。"""
        err = self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2", "abc"]},
        )
        assert err is not None
        assert "非法任务 id" in err
        assert "abc" in err

    def test_success_letter_suffixed_ids_pass(self):
        """字母后缀任务是合法 id（1.2b/4.6b）→ 放行（2026-09-15 事故回归）。

        任务 id 语法为 ``<组号>.<任务号>[可选小写字母后缀]``；硬门只认 ``x.y``
        时会把实现者如实上报的 ``1.2b`` 判为「非数字 id」，使一轮完整成功的
        交付被误拦（并误标 provider-transient 反复原地重试烧穿预算）。
        """
        tasks_text = (
            "## 1. 阶段一\n\n- [x] 1.1 任务一\n- [x] 1.2b 任务一补充\n"
            "## 2. 阶段二\n\n- [x] 2.1 任务二\n- [x] 2.1a 任务二补充\n"
        )
        assert self._gate(
            tasks_text=tasks_text,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2b", "2.1", "2.1a"]},
        ) is None

    def test_partial_letter_suffixed_ids_pass(self):
        """partial 申报含字母后缀 id（已完成与未完成两侧）→ 放行。"""
        tasks_text = (
            "## 1. 阶段一\n\n- [x] 1.1 任务一\n- [ ] 1.2b 任务一补充\n"
        )
        assert self._gate(
            tasks_text=tasks_text,
            payload={"status": "partial", "spec": self.spec,
                     "completed_tasks": ["1.1"], "unfinished": ["1.2b"]},
        ) is None

    def test_healthy_success_passes(self):
        """健康轮次：tasks.md 全勾 + completed_tasks 集合相等 → 放行。"""
        assert self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
        ) is None

    # ── partial 申报一致性判据 ───────────────────────────────

    def test_partial_consistent_passes(self):
        """partial 申报一致（completed/unfinished 与勾选状态严格对应）→ 放行。"""
        assert self._gate(
            tasks_text=PARTIAL_TASKS,
            payload={"status": "partial", "spec": self.spec,
                     "completed_tasks": ["1.1"], "unfinished": ["1.2"]},
        ) is None

    def test_partial_missing_unfinished_blocked(self):
        """partial 缺 unfinished 数组 → 拦截。"""
        err = self._gate(
            tasks_text=PARTIAL_TASKS,
            payload={"status": "partial", "spec": self.spec,
                     "completed_tasks": ["1.1"]},
        )
        assert err is not None
        assert "partial" in err

    def test_partial_gap_underreported_blocked(self):
        """partial：unfinished 漏列未勾任务 → 拦截（缺口 id）。"""
        err = self._gate(
            tasks_text=PARTIAL_TASKS,
            payload={"status": "partial", "spec": self.spec,
                     "completed_tasks": ["1.1"],
                     "unfinished": []},
        )
        assert err is not None
        assert "不一致" in err or "unfinished" in err

    def test_partial_completed_overreported_blocked(self):
        """partial：completed_tasks 含未勾任务 → 拦截。"""
        err = self._gate(
            tasks_text=PARTIAL_TASKS,
            payload={"status": "partial", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"],
                     "unfinished": []},
        )
        assert err is not None

    # ── 能力探测（D4）───────────────────────────────────────

    def test_taskcreate_available_but_no_task_tracked_passes(self):
        """init.tools 含 TaskCreate 但全程未建任何 Task → 放行（无证据可核对）。

        2026-09-15 语义修正：要求集 = checked ∩ tracked。若实现者从未调用
        TaskCreate（tracked 为空），则无从核对——与「工具不可用」同办，
        fail-open。旧行为（要求 checked_ids 全覆盖）会把「未用工具」误判为
        「记录不一致」。
        """
        _mk_run_file(self.proot, self.spec,
                     tools=["Task", "TaskCreate", "TaskUpdate", "Bash"])
        assert self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
        ) is None

    def test_taskcreate_available_done_ids_cover_passes(self):
        """init.tools 含 TaskCreate 且 done_ids 覆盖全部已勾 → 放行。"""
        runs = self.proot / ".fenix" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        run_file = runs / f"impl-{self.spec}-1780000000.jsonl"
        lines = [
            {"type": "system", "subtype": "init",
             "tools": ["Task", "TaskCreate", "TaskUpdate"]},
            {"type": "assistant",
             "message": {"content": [
                 {"type": "tool_use", "name": "TaskCreate",
                  "input": {"subject": "Task 1.1: 任务一"}},
                 {"type": "tool_use", "name": "TaskCreate",
                  "input": {"subject": "Task 1.2: 任务二"}},
                 {"type": "tool_use", "name": "TaskUpdate",
                  "input": {"taskId": 1, "status": "completed"}},
                 {"type": "tool_use", "name": "TaskUpdate",
                  "input": {"taskId": 2, "status": "completed"}},
             ]}},
        ]
        run_file.write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
            encoding="utf-8")
        assert self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
        ) is None

    # ── 跨轮累积与 tracked 判据（2026-09-15 事故修正回归）──────

    def test_cross_round_cumulative_passes(self):
        """首轮建 Task、次轮（修复轮）不建 → 跨轮累积后仍放行。

        事故形态：done_ids 只读 mtime 最新单 run（修复轮为空）→ 误拦。
        这里首轮创建 1.1/1.2 并完成，次轮不动 Task；门须查全部历史 run。
        """
        base = ["Task", "TaskCreate", "TaskUpdate"]
        # 首轮：创建 1.1/1.2 并完成（taskId 1/2）
        _mk_run(self.proot, self.spec, name=f"impl-{self.spec}-1780000001-a1.jsonl",
                tools=base, events=[
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.1: 任务一"}},
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.2: 任务二"}},
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 1, "status": "completed"}},
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 2, "status": "completed"}},
                ])
        # 修复轮（mtime 更新 → 成为 find_impl_run_file 的最新）：不建任何 Task
        _mk_run(self.proot, self.spec, name=f"impl-{self.spec}-1780000002-a1.jsonl",
                tools=base, events=[
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 1, "status": "completed"}},
                ])
        assert self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
        ) is None

    def test_taskid_global_order_across_resume(self):
        """resume 续做轮：taskId 为会话级全局序，跨 a1/a2 映射须正确。

        a1 创建 2 个任务（taskId 1/2）；a2 续建第 3 个（taskId 3）。
        若按单 run 局部序映射，a2 的 taskId=3 会越界丢失 → 误判 1.3 未完成。
        """
        base = ["Task", "TaskCreate", "TaskUpdate"]
        _mk_run(self.proot, self.spec, name=f"impl-{self.spec}-1780000001-a1.jsonl",
                tools=base, events=[
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.1: 任务一"}},
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.2: 任务二"}},
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 1, "status": "completed"}},
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 2, "status": "completed"}},
                ])
        _mk_run(self.proot, self.spec, name=f"impl-{self.spec}-1780000001-a2.jsonl",
                tools=base, events=[
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.3: 任务三"}},
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 3, "status": "completed"}},
                ])
        assert self._gate(
            tasks_text="## 1. 阶段一\n\n- [x] 1.1 任务一\n- [x] 1.2 任务二\n- [x] 1.3 任务三\n",
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2", "1.3"]},
        ) is None

    def test_untracked_checked_id_not_required(self):
        """已勾选但从未建过 Task 的任务（如 1.2b）不要求 done_ids 覆盖。

        事故形态：planner 中途插入 1.2b，实现者未单独建 Task 却勾选；
        门若要求 checked_ids 全覆盖会误拦。要求集须为 checked ∩ tracked。
        """
        _mk_run(self.proot, self.spec, name=f"impl-{self.spec}-1780000001-a1.jsonl",
                tools=["Task", "TaskCreate", "TaskUpdate"], events=[
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.1: 任务一"}},
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.2: 任务二"}},
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 1, "status": "completed"}},
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 2, "status": "completed"}},
                ])
        assert self._gate(
            tasks_text="## 1. 阶段一\n\n- [x] 1.1 任务一\n- [x] 1.2 任务二\n- [x] 1.2b 补充任务\n",
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2", "1.2b"]},
        ) is None

    def test_tracked_checked_id_still_blocked_when_missing(self):
        """tracked 任务（建过 Task）未完成仍拦截——不能因放宽容忍真缺口。"""
        _mk_run(self.proot, self.spec, name=f"impl-{self.spec}-1780000001-a1.jsonl",
                tools=["Task", "TaskCreate", "TaskUpdate"], events=[
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.1: 任务一"}},
                    {"type": "tool_use", "name": "TaskCreate",
                     "input": {"subject": "Task 1.2: 任务二"}},
                    {"type": "tool_use", "name": "TaskUpdate",
                     "input": {"taskId": 1, "status": "completed"}},
                    # 1.2（taskId 2）未 completed
                ])
        err = self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
        )
        assert err is not None
        assert "1.2" in err

    def test_taskcreate_unavailable_skips_and_audits(self):
        """init.tools 不含 TaskCreate → 放行且写 impl-task-crosscheck-skipped 审计。"""
        _mk_run_file(self.proot, self.spec, tools=["Bash", "Read", "Write"])
        assert self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
        ) is None
        run_file = self.proot / ".fenix" / "runs" / f"impl-{self.spec}-1780000000.jsonl"
        audit = [
            json.loads(line) for line in
            run_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("type") == "impl-task-crosscheck-skipped"
        ]
        assert len(audit) == 1
        assert audit[0]["spec"] == self.spec
        assert audit[0]["reason"]
        assert audit[0]["run_id"]

    def test_init_event_unavailable_skips(self):
        """init 事件不可得（run 文件缺失）→ 按工具不可用处理：放行（fail-open）。"""
        # 不写 run 文件 → find_impl_run_file 返回 None → 跳过交叉核对
        assert self._gate(
            tasks_text=ALL_DONE_TASKS,
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
        ) is None


if __name__ == "__main__":
    unittest.main()