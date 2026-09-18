"""fix-fasttrack-recovery-resume — fast-track 车道恢复续做消费 单测。

覆盖 spec（fix-fasttrack-recovery-resume）核心 requirement：

1. fast-track 派发入口消费恢复续做标记（Requirement 1）：
   - 续做命中不抹锚点（branch 仍为保留分支）
   - 载体贯通到 runner（run_fast_track 收到 pre_wt_path）
   - 标记一次性消费（_recovery_resume 写 None）
   - 载体不可用降级并留痕（WARNING 含 spec 名与分支名）
   - 无恢复标记的全新派发行为不变（清旧锚点，且不打 Resume site WARNING）
   - 规模预检 full 档降级不碰锚点（branch/_recovery_resume 原样保留）
2. 恢复来源判据（Requirement 3 附属）：mark_reused 带 recovery=True 登记
3. 可观测性（Requirement 5）：续做命中/降级/清锚点日志可直接判读

基于 mock/stub 构造 dispatch 环境（真实 StateMachine 文件 + MagicMock
worktree_manager + 记录型 FakeLogger），MUST NOT 依赖真实 daemon。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.state_machine import StateMachine


class RecordingLogger:
    """记录型 logger：断言日志文本（Resume dispatch / Resume site / 清锚点）。"""

    def __init__(self):
        self.records = []  # (level, text)

    def _rec(self, level, *a, **k):
        text = a[1] if len(a) > 1 and isinstance(a[1], str) else str(a)
        self.records.append((level, text))

    def debug(self, *a, **k):
        self._rec("debug", *a, **k)

    def info(self, *a, **k):
        self._rec("info", *a, **k)

    def warning(self, *a, **k):
        self._rec("warning", *a, **k)

    def error(self, *a, **k):
        self._rec("error", *a, **k)

    def texts(self, level=None):
        return [
            t for lv, t in self.records
            if level is None or lv == level
        ]


def _mk_spec_dir(proot: Path, name: str, n_tasks: int = 1) -> None:
    """写 spec 目录（.spec.yaml + tasks.md），scale 落在 normal 档。"""
    d = proot / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / ".spec.yaml").write_text(
        "schema: spec-driven\ncreated: 2026-09-18\nmode: fast-track\n",
        encoding="utf-8",
    )
    lines = ["## 1. x"]
    for i in range(1, n_tasks + 1):
        lines.append(f"- [ ] {i}.x do it")
    (d / "tasks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_engine(proot: Path, config=None):
    """构造最小 PMEngine：真实 StateMachine（文件态）+ MagicMock agent_runner。

    Returns: (engine, sm, logger, dispatcher, wm)
    """
    logger = RecordingLogger()
    sm = StateMachine(proot / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, proot, logger)
    engine.handle_event = MagicMock()
    engine._on_spec_verified = MagicMock()
    engine._enqueue = MagicMock()
    engine._enqueue_front = MagicMock()
    engine._increment_impl_run_budget_used = MagicMock()
    # worktree_manager mock：resolve_resume_site / mark_reused / get_reuse_record 可配
    wm = MagicMock()
    wm.ensure_spec_committed.return_value = True
    engine.agent_runner.worktree_manager = wm
    # dispatcher 实例注入（engine.__getattr__ 委托 _dispatcher_instance）
    from core.pm_engine.dispatch import Dispatcher

    dispatcher = Dispatcher(engine)
    dispatcher._enqueue = MagicMock()
    dispatcher._enqueue_front = MagicMock()
    engine.__dict__["_dispatcher_instance"] = dispatcher
    return engine, sm, logger, dispatcher, wm


class TestFastTrackRecoveryResume:
    """fast-track 车道恢复续做消费（Requirement 1 / 5）。"""

    def _dispatch(self, tmp_path, spec, state_updates=None, resolve_ret=None):
        """统一派发入口：写 spec 目录 + STATE 初始条目 + 派发 fast-track。"""
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, spec)
        engine, sm, logger, dispatcher, wm = _make_engine(proot)
        sm.add_spec(spec, {"priority": 5})
        sm.transition(spec, "ready")
        if state_updates:
            sm.update_spec(spec, state_updates)
        if resolve_ret is not None:
            wm.resolve_resume_site.return_value = resolve_ret
        dispatcher._run_fast_track_worker = MagicMock()
        engine._run_agent_worker(spec, "fast-track", 5)
        return engine, sm, logger, dispatcher, wm

    def test_resume_hit_keeps_anchor(self, tmp_path):
        """续做命中不抹锚点：branch 仍为保留分支，未写入 {branch: None}。"""
        spec = "resume-keep"
        branch = f"fenix/{spec}-1789750000"
        carrier = tmp_path / "proj" / ".claude" / "worktrees" / f"impl-{spec}-1789750000"
        engine, sm, logger, dispatcher, wm = self._dispatch(
            tmp_path, spec,
            state_updates={"branch": branch, "_recovery_resume": True},
            resolve_ret=(carrier, branch),
        )
        entry = sm.read_one(spec)
        assert entry.get("branch") == branch, "续做命中时 branch 不得被清空"
        # 清锚点日志 MUST NOT 出现
        for _, t in logger.records:
            assert "新轮次派发清除旧锚点" not in t, "续做命中不得打清锚点日志"
        # 续做命中日志出现（可观测性）
        resume_logs = [t for _, t in logger.records if "Resume dispatch" in t]
        assert resume_logs, "续做命中必须打 Resume dispatch INFO 日志"
        assert branch in resume_logs[0]

    def test_carrier_passed_to_worker(self, tmp_path):
        """载体贯通：_run_fast_track_worker 收到 pre_wt_path=<载体>。"""
        spec = "resume-carry"
        branch = f"fenix/{spec}-1789750001"
        carrier = tmp_path / "proj" / ".claude" / "worktrees" / f"impl-{spec}-1789750001"
        engine, sm, logger, dispatcher, wm = self._dispatch(
            tmp_path, spec,
            state_updates={"branch": branch, "_recovery_resume": True},
            resolve_ret=(carrier, branch),
        )
        dispatcher._run_fast_track_worker.assert_called_once_with(
            spec, pre_wt_path=carrier
        )
        # mark_reused 带 recovery=True（恢复来源判据，design D6）
        wm.mark_reused.assert_called_once_with(spec, carrier, branch, recovery=True)

    def test_marker_consumed_once(self, tmp_path):
        """标记一次性消费：派发后 _recovery_resume 不再为真（falsy）。

        注：STATE.md 布尔字段往返——写入 None 序列化为 null、解析回退 False，
        二者对 ``entry.get("_recovery_resume")`` 判据均为 falsy，即「不再续做」。
        """
        spec = "resume-consume"
        branch = f"fenix/{spec}-1789750002"
        carrier = tmp_path / "proj" / ".claude" / "worktrees" / f"impl-{spec}-1789750002"
        engine, sm, logger, dispatcher, wm = self._dispatch(
            tmp_path, spec,
            state_updates={"branch": branch, "_recovery_resume": True},
            resolve_ret=(carrier, branch),
        )
        assert not sm.read_one(spec).get("_recovery_resume"), "标记须一次性消费（不再为真）"

    def test_carrier_unavailable_degrade_with_warning(self, tmp_path):
        """载体不可用降级留痕：WARNING 含分支名；此时允许清锚点。"""
        spec = "resume-degrade"
        branch = f"fenix/{spec}-1789750003"
        engine, sm, logger, dispatcher, wm = self._dispatch(
            tmp_path, spec,
            state_updates={"branch": branch, "_recovery_resume": True},
            resolve_ret=(None, None),
        )
        warns = logger.texts("warning")
        assert any("Resume site unavailable" in t and branch in t for t in warns), (
            "载体降级必须打 WARNING 含 spec 名与分支名"
        )
        # 降级 = 未命中续做：清锚点（branch 被清空）
        entry = sm.read_one(spec)
        assert entry.get("branch") is None, "载体不可用时允许清空旧锚点"
        assert not entry.get("_recovery_resume"), "标记仍须一次性消费（不再为真）"
        assert any("新轮次派发清除旧锚点" in t for _, t in logger.records)

    def test_no_marker_behavior_unchanged(self, tmp_path):
        """无恢复标记的全新派发：清旧锚点；MUST NOT 打 Resume site WARNING。"""
        spec = "resume-fresh"
        old_branch = f"fenix/{spec}-1789750004"
        old_impl_run = "impl-old-1"
        engine, sm, logger, dispatcher, wm = self._dispatch(
            tmp_path, spec,
            state_updates={
                "branch": old_branch,
                "implementer_run": old_impl_run,
                "_repair_awaiting_remerge": True,
            },
            # 无 _recovery_resume → resume_branch=None → resolve_resume_site 不被调用
        )
        entry = sm.read_one(spec)
        assert entry.get("branch") is None, "无标记时旧锚点被清空（与 implementer 非续做路径一致）"
        assert entry.get("implementer_run") is None
        assert entry.get("_repair_awaiting_remerge") is False
        # MUST NOT 打 Resume site unavailable（无标记不是降级）
        warns = logger.texts("warning")
        assert not any("Resume site unavailable" in t for t in warns)
        # MUST NOT 打 Resume dispatch（非续做）
        infos = logger.texts("info")
        assert not any("Resume dispatch" in t for t in infos)
        # 清锚点 INFO 日志含被清空的旧锚点值（可观测性）
        clear_logs = [t for _, t in logger.records if "新轮次派发清除旧锚点" in t]
        assert clear_logs and old_branch in clear_logs[0] and old_impl_run in clear_logs[0]
        # 载体实参为 None（1.5 断言口径）
        dispatcher._run_fast_track_worker.assert_called_once_with(spec, pre_wt_path=None)
        # resolve_resume_site 不得被调用（无标记时无载体可解析）
        wm.resolve_resume_site.assert_not_called()

    def test_full_tier_downgrade_touches_no_anchor(self, tmp_path):
        """规模预检 full 档降级：branch/_recovery_resume 均未被改动。"""
        spec = "resume-big"
        branch = f"fenix/{spec}-1789750005"
        proot = tmp_path / "proj"
        # 30 任务 + 8 交付物 = 46 > 45 → full
        d = proot / "spec" / "changes" / spec
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text(
            "schema: spec-driven\ncreated: 2026-09-18\nmode: fast-track\n",
            encoding="utf-8",
        )
        lines = ["## 1. x"]
        for i in range(1, 31):
            lines.append(f"- [ ] {i}.x do it")
        lines += ["", "## Deliverables", "", "```yaml"]
        for i in range(8):
            lines += [f"- path: core/f{i}.py", "  kind: modify"]
        lines.append("```")
        (d / "tasks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        engine, sm, logger, dispatcher, wm = _make_engine(proot)
        sm.add_spec(spec, {"priority": 5})
        sm.transition(spec, "ready")
        sm.update_spec(
            spec, {"branch": branch, "implementer_run": "impl-big-1", "_recovery_resume": True}
        )
        # 观察降级出口真实实现（不清锚点/不消费标记）
        dispatcher._downgrade_fast_track_scale = MagicMock(
            wraps=dispatcher._downgrade_fast_track_scale
        )
        dispatcher._run_fast_track_worker = MagicMock()
        engine._run_agent_worker(spec, "fast-track", 5)
        dispatcher._downgrade_fast_track_scale.assert_called_once()
        dispatcher._run_fast_track_worker.assert_not_called()
        entry = sm.read_one(spec)
        assert entry.get("branch") == branch, "full 档降级 MUST NOT 清空 branch"
        assert entry.get("implementer_run") == "impl-big-1"
        assert entry.get("_recovery_resume") is True, "降级路径 MUST NOT 消费标记"
        assert "降级完整模式" in (entry.get("error") or "")
        dispatcher._enqueue.assert_called_with(spec, "implementer")
        # 降级路径不得打 Resume 相关日志（未到续做判定）
        assert not any("Resume" in t for _, t in logger.records)
