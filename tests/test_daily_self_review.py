"""每日自省（add-daily-self-review）测试：调度 / 产物 / 失败处理 / 数据摘要。

对应 tasks：
- 1.4 单测：定时触发 / 24h 内防重复 / 23:30 启动补跑 / enabled=false 全链路零动作
- 2.4 失败处理：run 失败记 warning 告警、24h 内不重试、满 24h 自然重试
- 2.5 单测：首次创建 / 追加不覆盖 / read_todo 开关注入与不注入 / 自省后
  spec 目录与 STATE 零新增 / commit 仅含 .fenix/todo.md
- 3.4 端点读写（见 test_dashboard_data.py 或本文件后段）

24h 滚动窗口改造（2026-09-07 用户决策，原地修改未立项）：
- 调度判定「last_run_date == 今天」→「距上次执行 ≥24h」（状态文件
  last_run_at ISO 时间戳；旧格式仅 last_run_date 视为从未执行）；
- 数据聚合窗口「自然日」→「执行前 24 小时」（runs/日志 ERROR/admin 记录）；
- 零活动防护按 24h 窗口判定，占位文案改为「近24小时无 SPEC 活动」。
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from core.admin_store import AdminStore, ESCALATION
from core.self_review import (
    SelfReviewScheduler,
    collect_log_errors,
    collect_runs_stats,
)


class FakeSM:
    def __init__(self, specs=None):
        self._specs = specs or {}

    def read_all(self):
        return self._specs


class FakeReviewResult:
    def __init__(self, success=True, waste=(), mistakes=(), improvements=(),
                 summary="s", error="", run_id="review-test-1", resolved=None):
        self.success = success
        self.waste = list(waste)
        self.mistakes = list(mistakes)
        self.improvements = list(improvements)
        self.summary = summary
        self.error = error
        self.run_id = run_id
        self.resolved = list(resolved or [])


class FakeReviewRunner:
    def __init__(self, result=None, fail=False):
        self.calls = []
        self._result = result or FakeReviewResult()
        self._fail = fail

    def run_self_review(self, date_str, daily_summary, todo_md, todo_entries=None):
        self.calls.append((date_str, daily_summary, todo_md, todo_entries))
        if self._fail:
            raise RuntimeError("claude 崩溃")
        return self._result


class FakeLogger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


@pytest.fixture()
def proot(tmp_path):
    root = tmp_path / "proj"
    (root / ".fenix").mkdir(parents=True)
    (root / "spec" / "changes").mkdir(parents=True)
    (root / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
    return root


def make_scheduler(proot, enabled=True, run_at="22:00", read_todo=False,
                   runner=None, specs=None, store=None):
    config = {"admin": {
        "enabled": True,
        "self_review": {
            "enabled": enabled,
            "run_at": run_at,
            "read_todo": read_todo,
        },
    }}
    return SelfReviewScheduler(
        config, proot, FakeLogger(), FakeSM(specs),
        agent_runner=runner,
        store=store or AdminStore(proot, FakeLogger()),
    )


def _freeze_time(monkeypatch, fixed: datetime):
    """Patch self_review module's datetime so `.now()` returns a fixed time.

    The subclass approach avoids Python's TypeError when patching the builtin
    datetime class directly (immutable C type).
    """
    from datetime import datetime as _real_datetime

    class _FakeDatetime(_real_datetime):
        @staticmethod
        def now(tz=None):
            return fixed

    import core.self_review as sr_mod
    monkeypatch.setattr(sr_mod, "datetime", _FakeDatetime)


def make_run(proot, run_id, terminal, ts=None):
    """写入 run 产物文件；terminal in (done/error/running/empty/timeout/instant)。"""
    lines = []
    if terminal == "done":
        lines = [{"type": "result", "result": "ok", "num_turns": 2}]
    elif terminal == "error":
        lines = [{"type": "error", "error": "boom", "exit_code": 1}]
    elif terminal == "timeout":
        lines = [{"type": "error", "error": "Timeout after 120s — x", "exit_code": -9}]
    elif terminal == "instant":
        lines = [{"type": "error", "error": "No conversation found with session ID x", "exit_code": 1}]
    elif terminal == "running":
        lines = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}]
    elif terminal == "empty":
        lines = []
    p = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
    if ts is not None:
        os.utime(p, (ts, ts))
    return p


# ── 1.4 调度判定 ───────────────────────────────────────────

class TestSelfReviewScheduling:
    def test_trigger_after_run_at(self, proot, monkeypatch):
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 4, 10))}", "done")
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, run_at="22:00", runner=runner)
        res = sched.check_and_run()
        assert res["triggered"] is True and res["ok"] is True
        assert res["date"] == "2026-09-04"
        # 状态文件记录执行时刻（24h 判定基准）+ 执行日
        state = json.loads((proot / ".fenix" / "self_review_state.json").read_text())
        assert state["last_run_date"] == "2026-09-04"
        assert datetime.fromisoformat(state["last_run_at"]) \
            == datetime(2026, 9, 4, 22, 30)
        assert len(runner.calls) == 1
        # todo.md 已创建
        todo = proot / ".fenix" / "todo.md"
        assert todo.exists()
        content = todo.read_text(encoding="utf-8")
        assert "## 2026-09-04" in content
        assert "### 浪费" in content and "### 失误" in content and "### 可改进" in content

    def test_before_run_at_no_trigger(self, proot, monkeypatch):
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 21, 0))
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, run_at="22:00", runner=runner)
        res = sched.check_and_run()
        assert res == {"triggered": False, "reason": "before_run_at"}
        assert runner.calls == []
        assert not (proot / ".fenix" / "self_review_state.json").exists()
        assert not (proot / ".fenix" / "todo.md").exists()

    def test_within_24h_no_duplicate(self, proot, monkeypatch):
        """距上次执行不足 24h → 不触发（原「同日防重复」的 24h 版）。"""
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, run_at="22:00", runner=runner)
        sched._save_state("2026-09-04")  # 刚执行过（last_run_at=now）
        res = sched.check_and_run()
        assert res == {"triggered": False, "reason": "within_24h"}
        assert runner.calls == []

    @pytest.mark.parametrize(
        "prior_day", ["success", "failure", "zero_activity_skip"])
    def test_next_day_retriggers_after_prior_cycle(
            self, proot, monkeypatch, prior_day):
        """满 24h 且次日到 run_at、窗口有活动 → 再次触发（每日节奏）。

        三种首日形态（成功 / 失败 / 零活动跳过）都不阻断次日调度。原
        test_after_24h_retriggers / test_next_day_natural_retry /
        test_next_day_with_activity_reviews_normally 三条同核用例合并，
        各自的独有断言按分支逐条保留。
        """
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        if prior_day == "zero_activity_skip":
            make_scheduler(proot, run_at="22:00",
                           runner=FakeReviewRunner()).check_and_run()
        else:
            make_run(proot, f"impl-a-{_ts(datetime(2026, 9, 4, 10))}", "done")
            make_scheduler(proot, run_at="22:00",
                           runner=FakeReviewRunner(
                               fail=(prior_day == "failure")),
                           ).check_and_run()

        # 次日到点（≥24h）→ 新窗口有活动 → 再次触发
        if prior_day == "success":
            # 22:31 严格大于 24h，避开与 22:30 的边界（与原用例一致）
            _freeze_time(monkeypatch, datetime(2026, 9, 5, 22, 31))
        else:
            _freeze_time(monkeypatch, datetime(2026, 9, 5, 22, 30))
        make_run(proot, f"impl-b-{_ts(datetime(2026, 9, 5, 10))}", "done")
        runner2 = FakeReviewRunner()
        res = make_scheduler(
            proot, run_at="22:00", runner=runner2).check_and_run()
        assert res["triggered"] is True and res["ok"] is True
        assert "skipped" not in res
        assert len(runner2.calls) == 1
        if prior_day == "failure":
            # 首日失败不阻断次日重试：重试正常落当日节
            assert res["date"] == "2026-09-05"
            assert "## 2026-09-05" in (proot / ".fenix" / "todo.md").read_text(
                encoding="utf-8")
        elif prior_day == "zero_activity_skip":
            # 首日占位保留 + 次日完整分节追加，日期节按序
            content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
            assert "近24小时无 SPEC 活动，跳过自省。" in content
            assert "### 浪费" in content
            assert content.index("## 2026-09-04") < content.index("## 2026-09-05")

    def test_legacy_state_without_last_run_at_triggers(self, proot, monkeypatch):
        """旧格式状态文件（仅 last_run_date，无 last_run_at）→ 视为从未执行，
        新标准下立即触发（兼作 24h 判定上线后的手动触发通道）。"""
        (proot / ".fenix" / "self_review_state.json").write_text(json.dumps({
            "last_run_date": "2026-09-04",
            "updated_at": "2026-09-04T02:00:27+08:00",
        }), encoding="utf-8")
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 4, 10))}", "done")
        runner = FakeReviewRunner()
        res = make_scheduler(proot, run_at="22:00", runner=runner).check_and_run()
        assert res["triggered"] is True and res["ok"] is True

    def test_catch_up_on_late_start(self, proot, monkeypatch):
        """23:30 启动且距上次执行 ≥24h → 启动后首轮巡检补跑（spec 错过后补跑场景）。"""
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 23, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 4, 10))}", "done")
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, run_at="22:00", runner=runner)
        res = sched.check_and_run()
        assert res["triggered"] is True and res["ok"] is True
        assert res["date"] == "2026-09-04"
        state = json.loads((proot / ".fenix" / "self_review_state.json").read_text())
        assert state["last_run_date"] == "2026-09-04"

    def test_disabled_zero_action(self, proot, monkeypatch):
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 23, 30))
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, enabled=False, runner=runner)
        res = sched.check_and_run()
        assert res == {"triggered": False, "reason": "disabled"}
        assert runner.calls == []
        assert not (proot / ".fenix" / "self_review_state.json").exists()
        assert not (proot / ".fenix" / "todo.md").exists()
        # admin store 也无告警
        assert AdminStore(proot, FakeLogger()).read_all() == []

    def test_hot_reload_config_change_takes_effect(self, proot, monkeypatch):
        """设置页三键修改热更新生效：巡检每轮重读配置，无需重启 daemon。

        模拟 daemon 热更新路径：原地 mutate 共享 config dict（fenixd
        _maybe_reload_config 的 resolve_config_into 语义），下一轮巡检立即
        读到新 run_at。
        """
        from core.config import ConfigLoader
        from core.dashboard.data import write_config
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 23, 0))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 4, 10))}", "done")
        runner = FakeReviewRunner()
        # 设置页先保存一次完整三键（写盘）→ 热更新原地替换共享 config
        res = write_config(proot, {"self_review": {
            "enabled": True, "run_at": "22:00", "read_todo": False,
        }}, scope="project")
        assert res["ok"] is True
        config: dict = {}
        ConfigLoader.resolve_config_into(config, proot)
        sched = SelfReviewScheduler(config, proot, FakeLogger(), FakeSM(),
                                    agent_runner=runner,
                                    store=AdminStore(proot, FakeLogger()))
        assert sched.check_and_run()["triggered"] is True

        # 设置页把 run_at 改为 23:59（含三键整体保存）→ 热更新
        res = write_config(proot, {"self_review": {
            "enabled": True, "run_at": "23:59", "read_todo": False,
        }}, scope="project")
        assert res["ok"] is True
        ConfigLoader.resolve_config_into(config, proot)

        # 次日 23:00（< 23:59）→ 不触发（新 run_at 立即生效）
        _freeze_time(monkeypatch, datetime(2026, 9, 5, 23, 0))
        sched2 = SelfReviewScheduler(config, proot, FakeLogger(), FakeSM(),
                                     agent_runner=runner,
                                     store=AdminStore(proot, FakeLogger()))
        assert sched2.check_and_run() == {"triggered": False, "reason": "before_run_at"}
        # 再热更新：run_at 改回 22:00 → 23:00 又满足（无需重启 daemon）
        write_config(proot, {"self_review": {
            "enabled": True, "run_at": "22:00", "read_todo": False,
        }}, scope="project")
        ConfigLoader.resolve_config_into(config, proot)
        _freeze_time(monkeypatch, datetime(2026, 9, 6, 23, 0))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 6, 10))}", "done")
        sched3 = SelfReviewScheduler(config, proot, FakeLogger(), FakeSM(),
                                     agent_runner=runner,
                                     store=AdminStore(proot, FakeLogger()))
        assert sched3.check_and_run()["triggered"] is True


# ── 零活动防护（2026-09-05 用户决策：窗口内无 SPEC 不唤醒 admin；窗口=24h） ──

class TestZeroActivitySkip:
    def test_zero_runs_skips_admin_and_notes_todo(self, proot, monkeypatch):
        """24h 窗口 0 run → 不发起自省 run，仅在 todo.md 记一句占位并照常落状态。"""
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, run_at="22:00", runner=runner)
        res = sched.check_and_run()
        assert res == {"triggered": True, "ok": True, "date": "2026-09-04",
                       "skipped": True, "reason": "no_spec_activity"}
        assert runner.calls == []  # admin 未被唤醒
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "## 2026-09-04" in content
        assert "近24小时无 SPEC 活动，跳过自省。" in content
        # 占位为日期节下裸 bullet（无小节），不进闭环判定条目收集
        assert "###" not in content
        state = json.loads((proot / ".fenix" / "self_review_state.json").read_text())
        assert state["last_run_date"] == "2026-09-04"
        assert "last_run_at" in state
        # 零活动是正常路径：不产生失败告警
        assert AdminStore(proot, FakeLogger()).read_all() == []

    def test_stale_run_outside_24h_window_skips(self, proot, monkeypatch):
        """活动在 24h 窗口之外（>24h 前的 run）→ 仍视为零活动跳过。

        这正是本次改造的核心负例：凌晨执行时自然日几乎无数据，但 24h 窗口
        覆盖昨日 → 有活动必触发；反之窗口外陈旧 run 不计入。
        """
        make_run(proot, f"impl-old-{_ts(datetime(2026, 9, 3, 8))}", "done")
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))  # 窗口 09-03 22:30 起
        runner = FakeReviewRunner()
        res = make_scheduler(proot, run_at="22:00", runner=runner).check_and_run()
        assert res.get("skipped") is True
        assert runner.calls == []

    def test_review_prefix_run_not_counted_as_activity(self, proot, monkeypatch):
        """窗口内仅剩 review- 自省 run 残留 → 仍视为零 SPEC 活动。"""
        make_run(proot, "review-2026-09-04", "done",
                 ts=datetime(2026, 9, 4, 2, 0).timestamp())
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        runner = FakeReviewRunner()
        res = make_scheduler(proot, run_at="22:00", runner=runner).check_and_run()
        assert res.get("skipped") is True
        assert runner.calls == []

    def test_existing_today_section_not_duplicated(self, proot, monkeypatch):
        """状态文件丢失重跑且 todo 已有当日节 → 不重复追加占位。"""
        (proot / ".fenix" / "todo.md").write_text(
            "## 2026-09-04\n\n### 浪费\n- 旧条目\n", encoding="utf-8")
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        runner = FakeReviewRunner()
        res = make_scheduler(proot, run_at="22:00", runner=runner).check_and_run()
        assert res.get("skipped") is True
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert content.count("## 2026-09-04") == 1
        assert "当日无 SPEC" not in content


# ── 2.4 失败处理 ───────────────────────────────────────────

class TestSelfReviewFailure:
    def test_failure_records_warning_and_marks_now(self, proot, monkeypatch):
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 4, 10))}", "done")
        runner = FakeReviewRunner(fail=True)
        sched = make_scheduler(proot, run_at="22:00", runner=runner)
        res = sched.check_and_run()
        assert res["triggered"] is True and res["ok"] is False
        # 状态文件已记录执行时刻 → 24h 内不重试
        state = json.loads((proot / ".fenix" / "self_review_state.json").read_text())
        assert state["last_run_date"] == "2026-09-04"
        assert sched.check_and_run()["reason"] == "within_24h"
        # warning 告警（已标记 handled，不进人工队列）
        recs = AdminStore(proot, FakeLogger()).read_all()
        assert any(r.get("signal_type") == "self_review_failed"
                   and r.get("severity") == "warning" and r.get("handled")
                   for r in recs)
        # 未写 todo.md
        assert not (proot / ".fenix" / "todo.md").exists()


# ── 2.5 产物写入 ───────────────────────────────────────────

class TestTodoAppend:
    def test_first_create(self, proot):
        sched = make_scheduler(proot)
        result = FakeReviewResult(
            waste=["证据：3 次秒挂；建议：冷却"],
            mistakes=["证据：merge 遗漏；建议：双检"],
            improvements=["证据：planner 丢弃；建议：改进调度"],
        )
        sched._append_todo("2026-09-04", result)
        todo = proot / ".fenix" / "todo.md"
        assert todo.exists()
        content = todo.read_text(encoding="utf-8")
        assert content.startswith("## 2026-09-04\n")
        assert "### 浪费\n- 证据：3 次秒挂" in content
        assert "### 失误\n- 证据：merge 遗漏" in content
        assert "### 可改进\n- 证据：planner 丢弃" in content

    def test_append_not_overwrite(self, proot):
        sched = make_scheduler(proot)
        (proot / ".fenix" / "todo.md").write_text(
            "## 2026-09-03\n\n### 浪费\n- 旧条目\n", encoding="utf-8")
        result = FakeReviewResult(waste=["新浪费"], mistakes=["新失误"], improvements=["新改进"])
        sched._append_todo("2026-09-04", result)
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "## 2026-09-03" in content and "- 旧条目" in content  # 历史保留
        assert "## 2026-09-04" in content and "- 新浪费" in content   # 追加在尾部
        # 新分节在文件尾部（历史之后）
        assert content.index("## 2026-09-03") < content.index("## 2026-09-04")

    def test_empty_sections_keep_structure(self, proot):
        sched = make_scheduler(proot)
        result = FakeReviewResult(waste=[], mistakes=[], improvements=[])
        sched._append_todo("2026-09-04", result)
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "### 浪费" in content and "### 失误" in content and "### 可改进" in content
        assert content.count("（当日无）") == 3

    def test_run_summary_injects_daily_summary(self, proot, monkeypatch):
        """数据摘要四源注入：STATE 终态 / runs / admin / ERROR（24h 窗口）。"""
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        specs = {"spec-a": {"status": "done"}, "spec-b": {"status": "implementing"}}
        make_run(proot, f"impl-spec-a-{_ts(datetime(2026, 9, 4, 10))}", "done")
        make_run(proot, f"impl-spec-b-{_ts(datetime(2026, 9, 4, 11))}", "timeout")
        # 日志 ERROR
        (proot / ".fenix" / "logs").mkdir(parents=True)
        (proot / ".fenix" / "logs" / "fenixd.log").write_text(
            json.dumps({"level": "ERROR", "component": "x", "message": "e1",
                        "timestamp": "2026-09-04T02:00:00Z"}) + "\n",
            encoding="utf-8",
        )
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, runner=runner, specs=specs)
        sched.check_and_run()
        summary = runner.calls[0][1]
        assert "近24小时数据摘要" in summary
        assert "窗口:" in summary
        assert "STATE 终态分布" in summary
        assert "done: 1" in summary and "implementing: 1" in summary
        assert "超时: 1" in summary
        assert "admin 告警与处置" in summary
        assert "日志 ERROR" in summary and "ERROR 总数: 1" in summary


# ── 2.5 禁止自动创建 SPEC / STATE 零新增 / commit 仅含 .fenix/todo.md ──

class TestNoAutoCreation:
    def test_no_state_or_spec_new_entries(self, proot, monkeypatch):
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 4, 10))}", "done")
        state_before = (proot / ".fenix" / "STATE.md").read_text(encoding="utf-8")
        changes_before = sorted(
            p.name for p in (proot / "spec" / "changes").iterdir() if p.is_dir()
        )
        runner = FakeReviewRunner()
        sched = make_scheduler(proot, runner=runner, specs={"spec-a": {"status": "done"}})
        sched.check_and_run()
        # STATE.md 内容逐字节不变；spec/changes 无新增目录；无 agent 派发诉求
        assert (proot / ".fenix" / "STATE.md").read_text(encoding="utf-8") == state_before
        changes_after = sorted(
            p.name for p in (proot / "spec" / "changes").iterdir() if p.is_dir()
        )
        assert changes_after == changes_before
        # 只产生 .fenix/todo.md 与状态文件
        assert (proot / ".fenix" / "todo.md").exists()
        assert (proot / ".fenix" / "self_review_state.json").exists()

    def test_commit_contains_only_todo(self, tmp_path, monkeypatch):
        """写入后 git commit 仅含 .fenix/todo.md（D4 单文件提交语义）。"""
        proot = tmp_path / "repo"
        proot.mkdir(parents=True)
        (proot / ".fenix").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(proot)], check=True)
        subprocess.run(["git", "-C", str(proot), "config", "user.email", "t@t.co"], check=True)
        subprocess.run(["git", "-C", str(proot), "config", "user.name", "test"], check=True)
        (proot / "README.md").write_text("# r", encoding="utf-8")
        subprocess.run(["git", "-C", str(proot), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(proot), "commit", "-qm", "init"], check=True)
        # 已有的未跟踪无关文件：不应被带入 commit
        (proot / "untracked.txt").write_text("x", encoding="utf-8")

        sched = make_scheduler(proot)
        result = FakeReviewResult(waste=["W"], mistakes=["M"], improvements=["I"])
        sched._append_todo("2026-09-04", result)
        assert sched._commit_todo("2026-09-04") is True
        # last commit 仅含 .fenix/todo.md
        shown = subprocess.run(
            ["git", "-C", str(proot), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True, text=True, check=True).stdout.split()
        assert [p for p in shown if p.strip()] == [".fenix/todo.md"]
        # untracked.txt 未被提交
        assert "untracked.txt" not in shown


# ── 3.1/3.4 Dashboard 设置页读写 ─────────────────────────

@pytest.fixture()
def isolated_user_config(tmp_path, monkeypatch):
    """把用户级配置隔离到 tmp，使用例不依赖宿主机 ~/.fenix/config.yaml 的内容。

    read_effective_config / write_config 按设计会合并用户级配置；本机该文件
    可能含真实 self_review 等非缺省键（2026-09-04 起本机自省已启用），断言
    「缺省值」的用例不隔离就会环境敏感假失败。两处常量分属两个模块，须同时
    patch：
    - core.config.USER_CONFIG_DIR：resolve_config 实际读取的用户级目录
    - core.dashboard.data.USER_CONFIG_PATH：read_effective_config 缓存键 /
      write_config(scope="user") 落点（缓存键须与实际读取路径一致）
    patch 后用户级文件不存在 → 用户层按空 dict 兜底 → 仅缺省值参与合并。
    """
    user_dir = tmp_path / "user-fenix"
    monkeypatch.setattr("core.config.USER_CONFIG_DIR", user_dir)
    monkeypatch.setattr("core.dashboard.data.USER_CONFIG_PATH",
                        user_dir / "config.yaml")
    return user_dir


class TestDashboardSelfReview:
    def test_read_write_roundtrip(self, tmp_path, isolated_user_config):
        """Data 层：write_config 写入 self_review → read_effective_config 读回。"""
        from core.dashboard.data import read_effective_config, write_config
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        # 缺省（run_at 缺省 02:00）
        assert read_effective_config(proot)["self_review"] == {
            "enabled": False, "run_at": "02:00", "read_todo": False,
        }
        res = write_config(proot, {"self_review": {
            "enabled": True, "run_at": "23:30", "read_todo": True,
        }}, scope="project")
        assert res["ok"] is True
        cfg = read_effective_config(proot)
        assert cfg["self_review"] == {
            "enabled": True, "run_at": "23:30", "read_todo": True,
        }
        # sources 标注（项目级显式定义）
        assert cfg["sources"].get("admin.self_review") == "project"

    def test_invalid_run_at_rejected(self, tmp_path):
        from core.dashboard.data import read_effective_config, write_config
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        write_config(proot, {"self_review": {"enabled": True, "run_at": "23:30"}},
                     scope="project")
        for bad in ("25:00", "abc", "9:0", "22:60"):
            res = write_config(proot, {"self_review": {"run_at": bad}}, scope="project")
            assert res["ok"] is False, f"{bad} 应被拒绝"
            assert "HH:MM" in res["error"]
        # 原值未被坏提交污染
        assert read_effective_config(proot)["self_review"]["run_at"] == "23:30"

    def test_invalid_types_rejected(self, tmp_path):
        from core.dashboard.data import write_config
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        assert write_config(proot, {"self_review": {"enabled": "yes"}},
                            scope="project")["ok"] is False
        assert write_config(proot, {"self_review": {"read_todo": 1}},
                            scope="project")["ok"] is False

    def test_http_api_endpoint_roundtrip(self, tmp_path, isolated_user_config):
        """HTTP 端点：GET 读回缺省 → POST 写入 → GET 确认 → POST 非法 400。"""
        import http.client
        import threading
        from core.dashboard.registry import Registry
        from core.dashboard.server import DashboardHTTPServer, find_free_port

        proot = tmp_path / "proj-api"
        (proot / ".fenix").mkdir(parents=True)
        (proot / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-api", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        static_dir = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
        port = find_free_port(30000)
        srv = DashboardHTTPServer(("127.0.0.1", port), reg, static_dir)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            def request(method, path, body=None):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                try:
                    headers = {"Content-Type": "application/json"} if body else {}
                    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                                 headers=headers)
                    resp = conn.getresponse()
                    return resp.status, json.loads(resp.read() or b"{}")
                finally:
                    conn.close()

            # 缺省回显（run_at 缺省 02:00）
            status, data = request("GET", "/api/config?project=proj-api")
            assert status == 200
            assert data["self_review"]["run_at"] == "02:00"
            assert data["self_review"]["enabled"] is False
            # 写入
            status, data = request("POST", "/api/config?project=proj-api",
                                   {"self_review": {"enabled": True, "run_at": "23:30",
                                                    "read_todo": True}})
            assert status == 200
            assert data["self_review"]["enabled"] is True
            # 读回确认
            status, data = request("GET", "/api/config?project=proj-api")
            assert status == 200
            assert data["self_review"] == {"enabled": True, "run_at": "23:30",
                                           "read_todo": True}
            # 非法 run_at → 400（后端双重校验）
            status, data = request("POST", "/api/config?project=proj-api",
                                   {"self_review": {"run_at": "25:00"}})
            assert status == 400
            assert "HH:MM" in (data.get("error") or "")
        finally:
            srv.shutdown()
            srv.server_close()


# ── admin_monitor 巡检挂接（1.3） ─────────────────────────

class TestAdminMonitorHook:
    def test_run_once_triggers_self_review(self, tmp_path, monkeypatch):
        """巡检 run_once 内触发自省（挂在既有循环，无新线程）。"""
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        from core.admin_monitor import AdminMonitor
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        (proot / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 4, 10))}", "done")
        runner = FakeReviewRunner()
        mon = AdminMonitor(
            {"admin": {"enabled": True,
                       "self_review": {"enabled": True, "run_at": "22:00"}}},
            FakeSM({}), proot, FakeLogger(),
            store=AdminStore(proot, FakeLogger()),
            agent_runner=runner,
        )
        mon.run_once()
        assert len(runner.calls) == 1
        assert (proot / ".fenix" / "todo.md").exists()

    def test_run_once_with_admin_disabled_no_trigger(self, tmp_path, monkeypatch):
        """admin.enabled=false → 巡检不执行自省（依赖既有 monitor enabled 门控）。"""
        _freeze_time(monkeypatch, datetime(2026, 9, 4, 22, 30))
        from core.admin_monitor import AdminMonitor
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        (proot / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        runner = FakeReviewRunner()
        mon = AdminMonitor(
            {"admin": {"enabled": False,
                       "self_review": {"enabled": True, "run_at": "22:00"}}},
            FakeSM({}), proot, FakeLogger(),
            store=AdminStore(proot, FakeLogger()),
            agent_runner=runner,
        )
        mon.run_once()
        assert runner.calls == []
        assert not (proot / ".fenix" / "todo.md").exists()
        assert not (proot / ".fenix" / "self_review_state.json").exists()


# ── runner.run_self_review 单元（2.1）──────────────────────

class TestRunSelfReviewRunner:
    def _runner(self, proot):
        from core.agent_runner import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner.config = {}
        runner._get_config = lambda key, default=None: default
        runner._get_admin_model = lambda: "claude-sonnet-5"
        runner._get_agent_model_assignment = lambda agent_type: None
        from core.agent_runner.prompt_builder import PromptBuilder
        from types import SimpleNamespace
        runner._prompt_builder_instance = PromptBuilder(SimpleNamespace(project_root=proot))
        return runner

    def test_run_self_review_reads_out_and_accounts_tokens(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        runner = self._runner(proot)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            max_turns, spec_name=None):
            (proot / ".fenix" / f"self_review_out-{run_id}.json").write_text(
                json.dumps({"date": run_id.split("-")[1],
                            "waste": ["W"], "mistakes": ["M"], "improvements": ["I"]}),
                encoding="utf-8")
            return "out", 5, "sess", {"input_tokens": 100, "output_tokens": 20,
                                      "cost_usd": 0.02}

        runner._run_claude = fake_run_claude
        result = runner.run_self_review("2026-09-04", "摘要", None)
        assert result.success is True
        assert result.waste == ["W"] and result.mistakes == ["M"]
        assert result.improvements == ["I"]
        assert result.run_id == "review-2026-09-04"
        # 实例文件清理
        assert not (proot / ".fenix" / "self_review_out-review-2026-09-04.json").exists()
        # token 归账独立类目（不写 STATE）
        ledger = json.loads(
            (proot / ".fenix" / "cost" / "self_review_tokens.json").read_text())
        assert ledger["runs"][0]["input_tokens"] == 100
        assert ledger["runs"][0]["date"] == "2026-09-04"

    def test_run_self_review_failure_returns_success_false(self, tmp_path):
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True)
        runner = self._runner(proot)

        def failing(prompt, cwd, run_id, model_override, env_overrides,
                    max_turns, spec_name=None):
            raise RuntimeError("Timeout after 120s")

        runner._run_claude = failing
        result = runner.run_self_review("2026-09-04", "摘要", None)
        assert result.success is False
        assert "Timeout" in result.error
        # 失败也记账（input=0），实例文件不残留
        assert json.loads(
            (proot / ".fenix" / "cost" / "self_review_tokens.json").read_text()
        )["runs"][0]["input_tokens"] == 0

    def test_run_self_review_parses_resolved(self, tmp_path):
        """out JSON 的 resolved 归一化：畸形条目（非 dict/缺 id/空 id）过滤。"""
        proot = tmp_path / "proj-r"
        (proot / ".fenix").mkdir(parents=True)
        runner = self._runner(proot)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            max_turns, spec_name=None):
            (proot / ".fenix" / f"self_review_out-{run_id}.json").write_text(
                json.dumps({
                    "date": "2026-09-04", "waste": [], "mistakes": [],
                    "improvements": [],
                    "resolved": [
                        {"id": "2026-09-04#浪费#1", "reason": "fix commit abc"},
                        "not-a-dict",
                        {"reason": "缺 id"},
                        {"id": "", "reason": "空 id"},
                        {"id": 42, "reason": "非字符串 id"},
                    ],
                }),
                encoding="utf-8")
            return "out", 5, "sess", {"input_tokens": 10, "output_tokens": 5,
                                      "cost_usd": 0.01}

        runner._run_claude = fake_run_claude
        result = runner.run_self_review("2026-09-04", "摘要", None)
        assert result.resolved == [{"id": "2026-09-04#浪费#1", "reason": "fix commit abc"}]

    def test_run_self_review_resolved_missing_defaults_empty(self, tmp_path):
        proot = tmp_path / "proj-r2"
        (proot / ".fenix").mkdir(parents=True)
        runner = self._runner(proot)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                            max_turns, spec_name=None):
            (proot / ".fenix" / f"self_review_out-{run_id}.json").write_text(
                json.dumps({"date": "2026-09-04", "waste": ["W"],
                            "mistakes": [], "improvements": []}),
                encoding="utf-8")
            return "out", 5, "sess", {"input_tokens": 10, "output_tokens": 5,
                                      "cost_usd": 0.01}

        runner._run_claude = fake_run_claude
        result = runner.run_self_review("2026-09-04", "摘要", None)
        assert result.resolved == []


# ── 数据摘要辅助 ───────────────────────────────────────────

def _ts(dt: datetime) -> int:
    """run_id 内嵌时间戳：与 collect_runs_stats 的 fromtimestamp 本地时区往返一致。"""
    return int(dt.timestamp())


class TestSummaryHelpers:
    def test_runs_stats_classify(self, proot):
        base = datetime(2026, 9, 4, 10)
        make_run(proot, f"impl-a-{_ts(base)}", "done", ts=base.timestamp())
        make_run(proot, f"impl-b-{_ts(base)}", "timeout", ts=base.timestamp())
        make_run(proot, f"impl-c-{_ts(base)}", "instant", ts=base.timestamp())
        make_run(proot, f"impl-d-{_ts(base)}", "error", ts=base.timestamp())
        make_run(proot, f"impl-e-{_ts(base)}", "empty", ts=base.timestamp())
        make_run(proot, "review-2026-09-04", "done", ts=base.timestamp())  # 自省 run 排除
        stats = collect_runs_stats(proot, datetime(2026, 9, 4, 0, 0))
        assert stats["succeeded"] == 1
        assert stats["timeout"] == 1
        assert stats["instant_hang"] == 1
        assert stats["failed"] == 1
        assert stats["dropped"] == 1
        assert stats["total"] == 5  # review- 不计入

    def test_runs_stats_outside_window_excluded(self, proot):
        """窗口开始时刻之前的 run 不计入（24h 滚动窗口语义）。"""
        make_run(proot, f"impl-a-{_ts(datetime(2026, 9, 4, 10))}", "done")
        make_run(proot, f"impl-b-{_ts(datetime(2026, 9, 3, 10))}", "done")
        stats = collect_runs_stats(proot, datetime(2026, 9, 4, 0, 0))
        assert stats["total"] == 1

    def test_log_errors_aggregate(self, proot):
        log = proot / ".fenix" / "logs" / "fenixd.log"
        log.parent.mkdir(parents=True)
        lines = []
        for i in range(3):
            lines.append(json.dumps({"level": "ERROR", "component": "c",
                                     "message": f"err{i}",
                                     "timestamp": "2026-09-04T0%s:00:00Z" % (2 + i)}))
        lines.append(json.dumps({"level": "INFO", "message": "ok",
                                 "timestamp": "2026-09-04T05:00:00Z"}))
        # 窗口开始前 ERROR 不计入
        lines.append(json.dumps({"level": "ERROR", "message": "before-window",
                                 "timestamp": "2026-09-03T05:00:00Z"}))
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        agg = collect_log_errors(proot, datetime(2026, 9, 4, 0, 0))
        assert agg["error_count"] == 3
        assert len(agg["samples"]) == 3
        assert all("err" in s for s in agg["samples"])


# ── todo.md 闭环移除（自省启动时处理前 3 天记录） ─────────────

# 多日 todo.md：09-03 在窗口外（today=2026-09-07 → 窗口 09-04..09-06）
TODO_MULTI_DAY = """## 2026-09-03

### 浪费
- 证据：窗外条目；建议：x

## 2026-09-04

### 浪费
- 证据：A1；建议：r1
- 证据：A2；建议：r2

### 失误
- （当日无）

### 可改进
- 证据：A3；建议：r3

## 2026-09-05

### 浪费
- 证据：B1；建议：r4
"""


def write_todo(proot, text: str) -> Path:
    todo = proot / ".fenix" / "todo.md"
    todo.write_text(text, encoding="utf-8")
    return todo


class TestTodoEntriesCollect:
    """近 3 日条目收集与 ID 标注渲染。"""

    def test_collect_recent_entries_window_and_ids(self, proot):
        write_todo(proot, TODO_MULTI_DAY)
        sched = make_scheduler(proot)
        entries = sched._collect_recent_entries("2026-09-07")
        by_id = {e["id"]: e for e in entries}
        # 窗口外（09-03）排除；（当日无）排除
        assert len(entries) == 4
        assert by_id["2026-09-04#浪费#1"]["text"] == "证据：A1；建议：r1"
        assert by_id["2026-09-04#浪费#2"]["text"] == "证据：A2；建议：r2"
        assert by_id["2026-09-04#可改进#1"]["text"] == "证据：A3；建议：r3"
        assert by_id["2026-09-05#浪费#1"]["text"] == "证据：B1；建议：r4"
        assert all(e["date"] in {"2026-09-04", "2026-09-05", "2026-09-06"}
                   for e in entries)

    def test_collect_recent_entries_missing_file(self, proot):
        assert make_scheduler(proot)._collect_recent_entries("2026-09-07") == []

    def test_render_todo_entries(self, proot):
        from core.self_review import render_todo_entries
        entries = [
            {"id": "2026-09-04#浪费#1", "date": "2026-09-04", "section": "浪费",
             "text": "证据：A1"},
            {"id": "2026-09-04#失误#1", "date": "2026-09-04", "section": "失误",
             "text": "证据：A2"},
            {"id": "2026-09-05#浪费#1", "date": "2026-09-05", "section": "浪费",
             "text": "证据：B1"},
        ]
        rendered = render_todo_entries(entries)
        assert "## 2026-09-04" in rendered and "### 浪费" in rendered
        assert "- [2026-09-04#浪费#1] 证据：A1" in rendered
        assert rendered.index("## 2026-09-05") > rendered.index("### 失误")

    def test_render_todo_entries_empty(self, proot):
        from core.self_review import render_todo_entries
        assert render_todo_entries([]) == "（近3日窗口内无既有条目）"


class TestTodoCleanup:
    """按 resolved 清单从 todo.md 移除已闭环条目。"""

    def test_remove_resolved_and_cleanup_empty_blocks(self, proot):
        write_todo(proot, TODO_MULTI_DAY)
        sched = make_scheduler(proot)
        entries = sched._collect_recent_entries("2026-09-07")
        removed = sched._remove_resolved(entries, [
            {"id": "2026-09-04#浪费#2", "reason": "fix commit abc1234"},
            {"id": "2026-09-05#浪费#1", "reason": "SPEC 已落地"},
        ])
        assert [r["id"] for r in removed] == [
            "2026-09-04#浪费#2", "2026-09-05#浪费#1"]
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        # A2/B1 已移除
        assert "证据：A2" not in content and "证据：B1" not in content
        # 09-05 小节全空 → 日期节整体清理
        assert "## 2026-09-05" not in content
        # 其余内容保留
        assert "证据：A1" in content and "证据：A3" in content
        assert "### 失误" in content and "（当日无）" in content
        # 窗口外日期节逐字保留
        assert "## 2026-09-03" in content and "证据：窗外条目" in content

    def test_remove_resolved_snapshot_mismatch_skips(self, proot):
        write_todo(proot, TODO_MULTI_DAY)
        sched = make_scheduler(proot)
        entries = sched._collect_recent_entries("2026-09-07")
        # 注入后用户经 dashboard 编辑器改写了 A1 原文 → 快照不匹配须跳过
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        content = content.replace("证据：A1；建议：r1", "证据：A1被人改过；建议：r1")
        write_todo(proot, content)
        removed = sched._remove_resolved(entries, [
            {"id": "2026-09-04#浪费#1", "reason": "误判也会被快照拦下"},
            {"id": "2026-09-04#浪费#99", "reason": "窗口内不存在的 id"},
            {"id": "2026-09-01#浪费#1", "reason": "窗口外 id 不在注入清单"},
            "not-a-dict",
            {"reason": "缺 id"},
            42,
        ])
        assert removed == []
        after = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "证据：A1被人改过" in after  # 未被误删

    def test_remove_resolved_preserves_preamble_notes(self, proot):
        """日期节标题下、首个小节前的游离内容（如人工备注）不得因移除丢失。"""
        write_todo(proot, """## 2026-09-04

（人工备注：本日条目较少，仅一条）

### 浪费
- 证据：A1；建议：r1
""")
        sched = make_scheduler(proot)
        entries = sched._collect_recent_entries("2026-09-05")
        removed = sched._remove_resolved(entries, [
            {"id": "2026-09-04#浪费#1", "reason": "fix commit abc"}])
        assert [r["id"] for r in removed] == ["2026-09-04#浪费#1"]
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "### 浪费" not in content  # 小节清空被剔除
        assert "## 2026-09-04" in content  # 日期节因游离内容保留
        assert "（人工备注：本日条目较少，仅一条）" in content  # 备注逐字保留

    def test_apply_todo_update_remove_then_append(self, proot):
        write_todo(proot, TODO_MULTI_DAY)
        sched = make_scheduler(proot)
        entries = sched._collect_recent_entries("2026-09-07")
        result = FakeReviewResult(
            waste=["新W"], mistakes=["新M"], improvements=["新I"],
            resolved=[{"id": "2026-09-04#浪费#1", "reason": "fix commit abc"}],
        )
        sched._apply_todo_update("2026-09-07", result, entries)
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "证据：A1" not in content  # 先移除
        assert "## 2026-09-07" in content and "- 新W" in content  # 后追加
        assert content.index("## 2026-09-05") < content.index("## 2026-09-07")

    def test_apply_todo_update_no_resolved_keeps_history(self, proot):
        """resolved 为空（含旧式 result 无 resolved 属性）→ 只追加不改动。"""
        write_todo(proot, TODO_MULTI_DAY)
        sched = make_scheduler(proot)
        entries = sched._collect_recent_entries("2026-09-07")

        class LegacyResult:  # 模拟无 resolved 属性的旧结果
            waste, mistakes, improvements, summary = ["W"], ["M"], ["I"], "s"
            success, error, run_id = True, "", "review-x"

        sched._apply_todo_update("2026-09-07", LegacyResult(), entries)
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "证据：A1" in content and "证据：B1" in content
        assert "## 2026-09-07" in content

    def test_check_and_run_end_to_end(self, proot, monkeypatch):
        """read_todo=true 全链路：注入 ID 条目 → resolved 生效移除 → 追加当日节。"""
        write_todo(proot, TODO_MULTI_DAY)
        _freeze_time(monkeypatch, datetime(2026, 9, 7, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 7, 10))}", "done")
        result = FakeReviewResult(
            waste=["新W"], mistakes=["新M"], improvements=["新I"],
            resolved=[{"id": "2026-09-05#浪费#1", "reason": "SPEC 已落地"}],
        )
        runner = FakeReviewRunner(result=result)
        sched = make_scheduler(proot, run_at="22:00", read_todo=True, runner=runner)
        res = sched.check_and_run()
        assert res["triggered"] is True and res["ok"] is True
        # 注入的 ID 标注条目（第 4 参）
        assert "[2026-09-04#浪费#1]" in runner.calls[0][3]
        # read_todo=true 注入 todo.md 全文（第 3 参；原 test_read_todo_switches 断言收编）
        assert runner.calls[0][2] is not None
        assert "## 2026-09-03" in runner.calls[0][2]
        # resolved 移除生效 + 当日节追加
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "证据：B1" not in content
        assert "## 2026-09-07" in content

    def test_read_todo_off_no_removal(self, proot, monkeypatch):
        """read_todo=false：不注入条目、resolved 不生效（行为与既往一致）。"""
        write_todo(proot, TODO_MULTI_DAY)
        _freeze_time(monkeypatch, datetime(2026, 9, 7, 22, 30))
        make_run(proot, f"impl-seed-{_ts(datetime(2026, 9, 7, 10))}", "done")
        result = FakeReviewResult(
            waste=["W"], mistakes=["M"], improvements=["I"],
            resolved=[{"id": "2026-09-04#浪费#1", "reason": "不应生效"}],
        )
        runner = FakeReviewRunner(result=result)
        sched = make_scheduler(proot, run_at="22:00", read_todo=False, runner=runner)
        sched.check_and_run()
        # read_todo=false：todo.md 全文（第 3 参）与条目清单（第 4 参）均不注入
        assert runner.calls[0][3] is None
        assert runner.calls[0][2] is None
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "证据：A1" in content  # 未被移除


class TestTodoMultilineFormat:
    """条目「影响/证据/建议」三行渲染（用户确认格式，2026-09-05）。

    agent JSON 契约升级为结构化对象 {impact, evidence, suggestion}，
    _append_todo 渲染为多行 bullet 块；旧字符串条目按旧行内格式透传。
    """

    def test_append_todo_structured_entry_renders_three_lines(self, proot):
        sched = make_scheduler(proot)
        result = FakeReviewResult(waste=[{
            "impact": "1 轮 impl run 约 19 分钟整轮作废",
            "evidence": "run impl-x 在 03:01Z 被 SIGTERM",
            "suggestion": "重启前先排水",
        }], mistakes=[], improvements=[])
        sched._append_todo("2026-09-07", result)
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "- 影响：1 轮 impl run 约 19 分钟整轮作废\n" \
               "  证据：run impl-x 在 03:01Z 被 SIGTERM\n" \
               "  建议：重启前先排水" in content

    def test_append_todo_partial_and_empty_structured_entries(self, proot):
        sched = make_scheduler(proot)
        result = FakeReviewResult(
            waste=[{"impact": "仅有影响", "evidence": "", "suggestion": None},
                   {}],
            mistakes=[], improvements=[])
        sched._append_todo("2026-09-07", result)
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "- 影响：仅有影响" in content
        assert "证据：" not in content and "建议：" not in content
        # 全部字段为空的条目被跳过，无有效条目的小节回落（当日无）
        assert "（当日无）" in content

    def test_append_todo_string_entry_legacy_single_line(self, proot):
        """旧字符串条目（历史 agent 输出）保持行内格式。"""
        sched = make_scheduler(proot)
        result = FakeReviewResult(waste=["证据：3 次秒挂；建议：冷却"],
                                  mistakes=[], improvements=[])
        sched._append_todo("2026-09-07", result)
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "### 浪费\n- 证据：3 次秒挂；建议：冷却" in content

    def test_cleanup_collect_multiline_blocks(self, proot):
        """多行条目按块收集：id/序号按块计，text 取影响行。"""
        write_todo(proot, """## 2026-09-06

### 浪费
- 影响：X1
  证据：E1
  建议：S1
- 影响：X2
  证据：E2
  建议：S2

### 失误
- （当日无）
""")
        sched = make_scheduler(proot)
        entries = sched._collect_recent_entries("2026-09-07")
        by_id = {e["id"]: e for e in entries}
        assert by_id["2026-09-06#浪费#1"]["text"] == "影响：X1"
        assert by_id["2026-09-06#浪费#2"]["text"] == "影响：X2"
        assert len(entries) == 2  # （当日无）不成条

    def test_cleanup_remove_multiline_block_whole(self, proot):
        """移除命中条目时整块删除（含证据/建议续行），其余块逐字保留。"""
        todo_text = """## 2026-09-06

### 浪费
- 影响：X1
  证据：E1
  建议：S1
- 影响：X2
  证据：E2
  建议：S2
"""
        write_todo(proot, todo_text)
        sched = make_scheduler(proot)
        entries = sched._collect_recent_entries("2026-09-07")
        removed = sched._remove_resolved(entries, [
            {"id": "2026-09-06#浪费#1", "reason": "已修复"}])
        assert [r["id"] for r in removed] == ["2026-09-06#浪费#1"]
        content = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert "影响：X1" not in content and "证据：E1" not in content \
            and "建议：S1" not in content  # 整块删除
        assert "- 影响：X2\n  证据：E2\n  建议：S2" in content  # 其余块逐字保留


class TestSelfReviewPromptEntries:
    def _builder(self, proot):
        from types import SimpleNamespace
        from core.agent_runner.prompt_builder import PromptBuilder
        return PromptBuilder(SimpleNamespace(project_root=proot))

    def test_todo_entries_placeholder_rendered(self, proot):
        prompt = self._builder(proot)._build_self_review_prompt(
            "2026-09-04", {"daily_summary": "s", "out_path": "/tmp/o.json",
                           "todo_entries": "MARKER-ENTRIES-XYZ"})
        assert "MARKER-ENTRIES-XYZ" in prompt
        assert "{todo_entries}" not in prompt
        # 模板已宣告 resolved 输出契约（闭环判定任务）
        assert "resolved" in prompt

    def test_todo_entries_default_when_absent(self, proot):
        prompt = self._builder(proot)._build_self_review_prompt(
            "2026-09-04", {"daily_summary": "s", "out_path": "/tmp/o.json"})
        assert "（近3日窗口内无既有条目）" in prompt


class TestSummaryGitCommits:
    """数据摘要第 5 源：近 3 日 git 提交（闭环判定证据）。"""

    def test_daily_summary_includes_recent_commits(self, tmp_path):
        proot = tmp_path / "repo"
        (proot / ".fenix").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(proot)], check=True)
        subprocess.run(["git", "-C", str(proot), "config", "user.email", "t@t.co"],
                       check=True)
        subprocess.run(["git", "-C", str(proot), "config", "user.name", "test"],
                       check=True)
        (proot / "f.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(proot), "add", "f.txt"], check=True)
        subprocess.run(["git", "-C", str(proot), "commit", "-qm", "fix: 闭环修复提交"],
                       check=True)
        summary = make_scheduler(proot).collect_daily_summary(datetime(2026, 9, 4))
        assert "## 5. 近 3 日 git 提交" in summary
        assert "fix: 闭环修复提交" in summary

    def test_daily_summary_git_unavailable_degrades(self, proot):
        # 非 git 目录 → 降级提示，不阻断摘要
        summary = make_scheduler(proot).collect_daily_summary(datetime(2026, 9, 4))
        assert "## 5. 近 3 日 git 提交" in summary
        assert "（git log 读取失败）" in summary