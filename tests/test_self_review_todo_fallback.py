"""自省「近 3 日既有条目」段状态可分辨（evo-add-self-review-todo-fallback-honesty）。

「未收集」（read_todo 关闭）与「真收集为空」（read_todo=true 且窗口内无条目）
是两种状态，MUST 输出可分辨的陈述——2026-10-05 potplayer-base 轮次实证：
read_todo=false 下「（近3日窗口内无既有条目）」让回顾 agent 声称窗口无条目，
而 .fenix/todo.md 实存 21 条窗口内条目。
"""

from datetime import datetime
from pathlib import Path

import pytest

from core.self_review import TODO_ENTRIES_NOT_COLLECTED, render_todo_entries
from tests.test_daily_self_review import (
    FakeReviewRunner,
    TODO_MULTI_DAY,
    _freeze_time,
    _ts,
    make_run,
    make_scheduler,
    write_todo,
)

NOT_COLLECTED = TODO_ENTRIES_NOT_COLLECTED
EMPTY_WINDOW = "（近3日窗口内无既有条目）"


@pytest.fixture()
def proot(tmp_path):
    root = tmp_path / "proj"
    (root / ".fenix").mkdir(parents=True)
    (root / "spec" / "changes").mkdir(parents=True)
    (root / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
    return root


class TestTodoEntriesStates:
    """调度器组装侧：三种状态注入的 {todo_entries} 值可分辨。"""

    def test_read_todo_off_injects_not_collected(self, proot, monkeypatch):
        """read_todo=false：注入显式未收集陈述，不含空窗口文案（场景 1）。"""
        write_todo(proot, TODO_MULTI_DAY)  # todo.md 实存窗口内条目
        _freeze_time(monkeypatch, datetime(2026, 9, 7, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 7, 10))}", "done")
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, run_at="22:00", read_todo=False, runner=runner)
        res = sched.check_and_run()
        assert res["triggered"] is True and res["ok"] is True
        entries_seg = runner.calls[0][3]
        assert entries_seg == NOT_COLLECTED
        assert "read_todo 关闭" in entries_seg
        assert EMPTY_WINDOW not in entries_seg
        # 窗口内实存条目未被收集（未收集 ≠ 收集为空的结论）
        assert "[2026-09-04#浪费#1]" not in entries_seg

    def test_read_todo_on_empty_window(self, proot, monkeypatch):
        """read_todo=true 且窗口内确无条目：保持「（近3日窗口内无既有条目）」（场景 2）。"""
        _freeze_time(monkeypatch, datetime(2026, 9, 7, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 7, 10))}", "done")
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, run_at="22:00", read_todo=True, runner=runner)
        res = sched.check_and_run()
        assert res["triggered"] is True and res["ok"] is True
        assert runner.calls[0][3] == EMPTY_WINDOW

    def test_read_todo_on_with_entries(self, proot, monkeypatch):
        """read_todo=true 且窗口内有条目：注入带 ID 标注清单（行为与现状一致，场景 3）。"""
        write_todo(proot, TODO_MULTI_DAY)
        _freeze_time(monkeypatch, datetime(2026, 9, 7, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 7, 10))}", "done")
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, run_at="22:00", read_todo=True, runner=runner)
        res = sched.check_and_run()
        assert res["triggered"] is True and res["ok"] is True
        entries_seg = runner.calls[0][3]
        assert "[2026-09-04#浪费#1]" in entries_seg
        assert "## 2026-09-04" in entries_seg
        assert NOT_COLLECTED not in entries_seg

    def test_states_distinguishable(self):
        """前两态文案可分辨：未收集陈述不含空窗口字样，反之亦然。"""
        assert NOT_COLLECTED != EMPTY_WINDOW
        assert "近3日窗口内无既有条目" not in NOT_COLLECTED
        assert "read_todo" not in EMPTY_WINDOW

    def test_render_empty_window_unchanged(self):
        """空清单渲染文案不变（真收集后的可核实结论）。"""
        assert render_todo_entries([]) == EMPTY_WINDOW


class TestSelfReviewPromptStates:
    """prompt 组装侧：注入值直达 {todo_entries} 段，不互相污染。"""

    def _builder(self, proot):
        from types import SimpleNamespace

        from core.agent_runner.prompt_builder import PromptBuilder
        return PromptBuilder(SimpleNamespace(project_root=proot))

    def test_prompt_not_collected_state(self, proot):
        prompt = self._builder(proot)._build_self_review_prompt(
            "2026-09-04", {"daily_summary": "s", "out_path": "/tmp/o.json",
                           "todo_entries": NOT_COLLECTED})
        assert NOT_COLLECTED in prompt
        assert EMPTY_WINDOW not in prompt
        assert "{todo_entries}" not in prompt

    def test_prompt_empty_window_state(self, proot):
        prompt = self._builder(proot)._build_self_review_prompt(
            "2026-09-04", {"daily_summary": "s", "out_path": "/tmp/o.json",
                           "todo_entries": EMPTY_WINDOW})
        assert EMPTY_WINDOW in prompt
        assert NOT_COLLECTED not in prompt
