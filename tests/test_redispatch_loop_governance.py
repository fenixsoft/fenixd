"""fix-redispatch-loop-governance 契约测试（2026-09-18）。

背景（fix-robustness-edge-cases 事故，2026-09-17）：实现 Agent 每一轮都真实干完
14/15 任务、写出正确的 `status: "partial"` 结果文件、如实把最后一条任务申报为
`unattainable`——然后被 spec 层收口判定判为失败重派。连烧 3 轮、每轮约 $18，
且每轮的 5 个提交整支丢弃。三层根因：

1. 读源自锁（读侧回退主树 tasks.md 勾选，partial 收敛走不到回写路径）；
2. 重派熔断是空转（retries >= max_r 时清零 + 照样重派）；
3. 成果不继承（run 层成功时 cleanup(success=True) 清理 worktree）。

本文件覆盖本 SPEC 的契约：

- `TestConvergenceContract`（tasks 1.3/2.2）：收敛成立 → is_success=True /
  final_error=None / implemented + verifier 入队；缺口 ⊆ unattainable 不重派；
  交付物缺件不因收敛放行。
- `TestAntiReadSourceFallback`（tasks 1.4）：主树 tasks.md 全未勾选时收敛仍成立。
- `TestInvalidUnattainableFailClosed`（tasks 2.5）：收敛点对非法 unattainable fail-closed。
- `TestFastTrackConvergence`（tasks 2.6）：fast-track 车道收敛不再被打回，
  降级完整模式补独立验证。
- `TestSameCauseCircuitBreaker`（tasks 3.8/3.3b/3.5）：同因重派熔断 / 作用域边界 /
  解冻清零。
- `TestWorktreeInheritance`（tasks 4.3/4.4）：成果继承 + 预算正交。
- `TestRedispatchStatePersistence`（tasks 3.2）：STATE 字段重启保持。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.run_task_track import (  # noqa: E402
    gap_from_result,
    parse_unattainable,
)

# tasks.md：1.1/1.2 完成，7.3 为人工运维门控（未勾）
HUMAN_GATE_TASKS = (
    "# Tasks\n\n## 1. 实现\n\n- [x] 1.1 任务一\n- [x] 1.2 任务二\n"
    "## 7. 收尾\n\n- [ ] 7.3 经用户确认时机后重启 daemon\n"
)
# 主树侧全部未勾（partial 收敛走不到 _sync_task_progress 回写路径）
ALL_UNCHECKED_TASKS = (
    "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 任务一\n- [ ] 1.2 任务二\n"
    "## 7. 收尾\n\n- [ ] 7.3 经用户确认时机后重启 daemon\n"
)
UNATTAINABLE_73 = [
    {"task": "7.3", "reason": "人工运维门控：需用户确认时机后重启 daemon",
     "evidence": "重启会打断在飞 run，须由用户掌控时机"}
]


def _make_engine(root, logger=None):
    """构造隔离的 PMEngine（与 test_honest_exit_convergence 同范式）。"""
    from core.pm_engine import PMEngine
    from core.state_machine import StateMachine

    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = logger or MagicMock()
    sm = StateMachine(root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), {}, root, logger)
    engine._enqueue = MagicMock()
    engine._dispatcher._enqueue = MagicMock()
    engine._dispatcher._enqueue_front = MagicMock()
    engine._process_queue = MagicMock()
    engine._reconcile_impl_budget = MagicMock()
    return sm, engine, logger


def _write_main_tasks(root, spec_name, text):
    d = root / "spec" / "changes" / spec_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text(text, encoding="utf-8")
    return d


def _mk_result_file(root, spec_name, payload):
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    (root / ".fenix" / ".fenix-run-result.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class _RunAgentBase(unittest.TestCase):
    """run_implementer 结果驱动的 _run_agent_worker 观察夹具（full 车道）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.spec = "demo"
        _write_main_tasks(self.root, self.spec, HUMAN_GATE_TASKS)
        self.sm, self.engine, self.logger = _make_engine(self.root)
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.transition(self.spec, "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_impl(self, payload, *, success=True, error=None, branch=None,
                  worktree_dirty=None):
        self.sm.transition(self.spec, "implementing")
        _mk_result_file(self.root, self.spec, payload)

        def _fake_impl(spec_name, pre_wt_path=None):
            return SimpleNamespace(
                success=success, error=error,
                run_id=f"impl-{self.spec}-1-a1",
                branch=branch, duration_seconds=1.0,
                worktree_dirty=worktree_dirty or [],
            )

        self.engine.agent_runner.run_implementer = MagicMock(side_effect=_fake_impl)
        self.engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )
        self.engine.agent_runner.worktree_manager.merge_back_from_branch = (
            MagicMock(return_value=(True, ""))
        )
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        return self.sm.read_one(self.spec)


class TestConvergenceContract(_RunAgentBase):
    """tasks 1.3/2.2：收敛成立时的收口序列契约。"""

    def test_convergence_sets_implemented_and_queues_verifier(self):
        """partial + 缺口全申报 → implemented + verifier 入队（MUST NOT 重派）。"""
        entry = self._run_impl(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73},
            # branch 非空（真实 success 路径的分支名由 runner 从 worktree 取得，
            # 本例走真实 merge-back 收口）。partial 诚实退出收敛允许 branch 缺失
            # （守卫豁免 impl_status == "partial"，见 queue.py item e45c71cbcd2c
            # 注释）；守卫只拦伪 success（自报 success/无结果文件）的缺支。
            branch="fenix/demo-1",
        )
        assert entry["status"] == "implemented", entry
        assert entry.get("error") is None, entry
        assert int(entry.get("_retry_count", 0) or 0) == 0
        # verifier 入队而非 implementer 重派
        self.engine._dispatcher._enqueue_front.assert_called()
        assert self.engine._dispatcher._enqueue_front.call_args[0][1] == "verifier"
        self.engine._dispatcher._enqueue.assert_not_called()

    def test_convergence_not_redispatched_when_gap_subset_unattainable(self):
        """缺口非空但 ⊆ unattainable → MUST NOT 进入重派通道。"""
        self._run_impl(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73},
            branch="fenix/demo-1",
        )
        # 任何形式的 implementer 重派（_enqueue / _enqueue_front）均不得发生
        for call in self.engine._dispatcher._enqueue.call_args_list:
            assert call[0][1] != "implementer", call
        for call in self.engine._dispatcher._enqueue_front.call_args_list:
            assert call[0][1] != "implementer", call

    def test_convergence_passes_zero_change_sentinel_with_real_commits(self):
        """收敛后零变更哨 MUST NOT 把有真实提交的 run 误判为空转。"""
        # branch 非空（有提交）→ 哨兵误判的确认型 no-op 分支不会触发
        entry = self._run_impl(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73},
            branch="fenix/demo-1",
        )
        assert entry["status"] == "implemented", entry

    def test_convergence_keeps_deliverable_gate_closure(self):
        """收敛后交付物守卫仍按声明段机械对账——缺件不因收敛放行。"""
        # 收敛成立 + run 声称 success=True → 若交付物守卫报缺件，MUST NOT 因
        # 已收敛而放行；仍走守卫缺件处置（重派补齐 / dispute 裁决）。
        self.engine._deliverable_gate_missing = MagicMock(
            return_value=[{"path": "core/foo.py", "violation": "missing"}]
        )
        entry = self._run_impl(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73}
        )
        # 缺件：不得 merge/implemented，走守卫缺件处置路径
        assert entry["status"] != "implemented", entry
        assert entry.get("error"), "缺件应有 error"


class TestAntiReadSourceFallback(_RunAgentBase):
    """tasks 1.4：主树 tasks.md 全未勾选时收敛仍成立（防读源回退回归）。"""

    def test_convergence_holds_with_all_unchecked_main_tree(self):
        """复现读侧自锁：主树全未勾 + completed_tasks 齐全 → 收敛成立。"""
        _write_main_tasks(self.root, self.spec, ALL_UNCHECKED_TASKS)
        entry = self._run_impl(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73},
            branch="fenix/demo-1",
        )
        assert entry["status"] == "implemented", entry
        assert int(entry.get("_retry_count", 0) or 0) == 0

    def test_undeclared_gap_still_fails_with_all_unchecked_main_tree(self):
        """主树全未勾 + 存在未申报缺口 → 仍按失败重派（防洗白）。"""
        _write_main_tasks(self.root, self.spec, ALL_UNCHECKED_TASKS)
        entry = self._run_impl(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1"], "unfinished": []}
        )
        assert entry["status"] == "ready", entry
        assert int(entry.get("_retry_count", 0) or 0) == 1


class TestInvalidUnattainableFailClosed(unittest.TestCase):
    """tasks 2.5：收敛点对非法 unattainable 项 fail-closed（D2b）。

    产物硬门正常时非法申报已被拦，但「只卡第一次」降级放行后非法条目可抵达
    收敛点；部分采信（合法项生效、非法项静默忽略）等于开了洗白窗口。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.spec = "demo"
        _write_main_tasks(self.root, self.spec, HUMAN_GATE_TASKS)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_honest_exit_gap_fail_closed_on_invalid(self):
        """_honest_exit_gap：含非法条目（task 非合法 id）→ 判不收敛。"""
        from core.pm_engine.dispatch import Dispatcher

        pm = MagicMock()
        pm.project_root = self.root
        gap = Dispatcher._honest_exit_gap(
            pm, self.spec,
            {"status": "partial", "completed_tasks": ["1.1", "1.2"],
             "unattainable": [
                 {"task": "7.3", "reason": "门控"},
                 {"task": "NOT-A-TASK", "reason": "非法 id"},
             ]},
        )
        assert gap == [], gap

    def test_honest_exit_gap_valid_entries_only_converges(self):
        """全部条目合法且覆盖全部缺口 → 收敛成立。"""
        from core.pm_engine.dispatch import Dispatcher

        pm = MagicMock()
        pm.project_root = self.root
        gap = Dispatcher._honest_exit_gap(
            pm, self.spec,
            {"status": "partial", "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73},
        )
        assert gap == ["7.3"], gap

    def test_task_completion_blocker_fail_closed_on_invalid(self):
        """_task_completion_blocker：非法 unattainable → 不放行（fail-closed）。"""
        from core.pm_engine import PMEngine
        from core.pm_engine import TASK_GAP_ERROR_PREFIX
        from core.state_machine import StateMachine

        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(self.root / ".fenix" / "STATE.md", MagicMock())
        engine = PMEngine(sm, MagicMock(), {}, self.root, MagicMock())
        sm.add_spec(self.spec, {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing", "verified"):
            sm.transition(self.spec, st)
        sm.update_spec(self.spec, {"implementer_run": f"impl-{self.spec}-1-a1"})
        # 写快照（partial + 非法 unattainable）
        vp = self.root / ".fenix" / "verify-progress" / self.spec
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "impl-result.json").write_text(
            json.dumps({"spec": self.spec, "status": "partial",
                        "completed_tasks": ["1.1", "1.2"],
                        "unattainable": [
                            {"task": "7.3", "reason": "门控"},
                            {"task": 123, "reason": "非法"},
                        ]}),
            encoding="utf-8",
        )
        engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )
        blocker = engine._task_completion_blocker(self.spec)
        assert blocker is not None, "非法 unattainable 必须拦截"
        assert blocker.startswith(TASK_GAP_ERROR_PREFIX), blocker
        assert "非法 unattainable" in blocker, blocker


class TestFastTrackConvergence(unittest.TestCase):
    """tasks 2.6：fast-track 车道收敛链（D2a 修复后不再被打回）。

    partial + 全申报的结果文件必然不含合法 verification 段；修复前
    _hard_check_fast_track fail-closed 打回重派（fast-track 收敛死路）。
    修复后：跳过硬校验 → merge → .spec.yaml mode→full → 入队完整模式 verifier。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.spec = "demo"
        _write_main_tasks(self.root, self.spec, HUMAN_GATE_TASKS)
        # .spec.yaml mode=fast-track
        spec_dir = self.root / "spec" / "changes" / self.spec
        (spec_dir / ".spec.yaml").write_text(
            "schema: spec-driven\ncreated: 2026-09-17\nmode: fast-track\n",
            encoding="utf-8",
        )
        self.sm, self.engine, self.logger = _make_engine(self.root)
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.transition(self.spec, "ready")
        self.sm.transition(self.spec, "implementing")
        # 门控与 merge 依赖打桩
        self.engine._implementer_zero_change = MagicMock(return_value=False)
        self.engine._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._tasks_md_relint_from_worktree = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch = MagicMock(return_value=(True, ""))
        wm.find_implementer_worktree = MagicMock(return_value=None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _result(self, branch="fenix/demo-1"):
        return SimpleNamespace(
            success=True, error=None, run_id=f"impl-{self.spec}-1-a1",
            branch=branch, duration_seconds=1.0,
            worktree_path=None, worktree_kept=False, cancelled=False,
            worktree_dirty=[],
        )

    def _run_flow(self, payload, result=None):
        _mk_result_file(self.root, self.spec, payload)
        self.engine._dispatcher._run_fast_track_flow(self.spec, result or self._result())
        return self.sm.read_one(self.spec)

    def test_fast_track_convergence_not_redispatched(self):
        """fast-track partial + 全申报 → 不重派、mode→full、入队 verifier。"""
        entry = self._run_flow(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73}
        )
        assert entry["status"] == "implemented", entry
        # .spec.yaml mode 改写为 full
        spec_yaml = (self.root / "spec" / "changes" / self.spec
                     / ".spec.yaml").read_text(encoding="utf-8")
        assert "mode: full" in spec_yaml, spec_yaml
        # verifier 入队（完整模式）
        self.engine._dispatcher._enqueue.assert_called()
        assert self.engine._dispatcher._enqueue.call_args[0][1] == "verifier"
        for call in self.engine._dispatcher._enqueue_front.call_args_list:
            assert call[0][1] != "fast-track", call

    def test_fast_track_undeclared_gap_still_redispatched(self):
        """fast-track partial 但存在未申报缺口 → 仍打回重派（防洗白）。

        失败通道走 _handle_fast_track_failure（ready + _retry_count 递增 +
        error 含归因）；重派由队列重处理触发（_enqueue 在 max_r 封顶分支），
        此处以状态与计数断言「未按成功收口推进」。
        """
        entry = self._run_flow(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"], "unfinished": []}
        )
        assert entry["status"] == "ready", entry
        assert int(entry.get("_retry_count", 0) or 0) == 1, entry
        assert entry.get("error"), entry


class TestTraceSymmetry(unittest.TestCase):
    """tasks 2.3：两条车道发生收敛时均写人工待办告警 + 日志含缺口清单。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.spec = "demo"
        _write_main_tasks(self.root, self.spec, HUMAN_GATE_TASKS)
        self.sm, self.engine, self.logger = _make_engine(self.root)
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.transition(self.spec, "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _alerts(self):
        from core.admin_store import AdminStore

        return [
            a for a in AdminStore(self.root, self.logger).read_all()
            if a.get("signal_type") == "impl_unattainable_tasks"
        ]

    def _full_lane_converge(self):
        self.sm.transition(self.spec, "implementing")
        _mk_result_file(self.root, self.spec,
                        {"status": "partial", "spec": self.spec,
                         "completed_tasks": ["1.1", "1.2"],
                         "unattainable": UNATTAINABLE_73})

        def _fake_impl(spec_name, pre_wt_path=None):
            return SimpleNamespace(
                success=True, error=None, run_id=f"impl-{self.spec}-1-a1",
                branch=None, duration_seconds=1.0, worktree_dirty=[],
            )

        self.engine.agent_runner.run_implementer = MagicMock(side_effect=_fake_impl)
        self.engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )
        self.engine.agent_runner.worktree_manager.merge_back_from_branch = (
            MagicMock(return_value=(True, ""))
        )
        self.engine._run_agent_worker(self.spec, "implementer", 5)

    def _fast_track_lane_converge(self):
        self.sm.transition(self.spec, "implementing")
        _mk_result_file(self.root, self.spec,
                        {"status": "partial", "spec": self.spec,
                         "completed_tasks": ["1.1", "1.2"],
                         "unattainable": UNATTAINABLE_73})
        self.engine._implementer_zero_change = MagicMock(return_value=False)
        self.engine._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._tasks_md_relint_from_worktree = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch = MagicMock(return_value=(True, ""))
        wm.find_implementer_worktree = MagicMock(return_value=None)
        result = SimpleNamespace(
            success=True, error=None, run_id=f"impl-{self.spec}-1-a1",
            branch="fenix/demo-1", duration_seconds=1.0,
            worktree_path=None, worktree_kept=False, cancelled=False,
            worktree_dirty=[],
        )
        self.engine._dispatcher._run_fast_track_flow(self.spec, result)

    def test_both_lanes_write_human_todo_alert(self):
        """full 与 fast-track 车道收敛后均写 impl_unattainable_tasks 告警。"""
        self._full_lane_converge()
        assert self._alerts(), "full 车道未写 impl_unattainable_tasks 告警"
        assert "7.3" in (self._alerts()[0].get("evidence") or "")

        # 重置 admin store 后走 fast-track 车道
        self.sm.transition(self.spec, "implementing")
        self._fast_track_lane_converge()
        alerts = self._alerts()
        assert alerts, "fast-track 车道未写 impl_unattainable_tasks 告警"
        assert "7.3" in (alerts[-1].get("evidence") or "")

    def test_both_lanes_log_contains_gap_list(self):
        """两条车道收敛日志均含缺口清单（可观测留痕）。"""
        self._full_lane_converge()
        full_logs = " ".join(str(c) for c in self.logger.warning.call_args_list)
        assert "7.3" in full_logs

        self.logger.reset_mock()
        self.sm.transition(self.spec, "implementing")
        self._fast_track_lane_converge()
        ft_logs = " ".join(str(c) for c in self.logger.warning.call_args_list)
        assert "7.3" in ft_logs


class TestRedispatchStatePersistence(unittest.TestCase):
    """tasks 3.2/3.5：STATE 字段持久化（_ 前缀全量透传）与解冻清零。"""

    def setUp(self):
        from core.state_machine import StateMachine

        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", MagicMock())
        self.sm.add_spec("demo", {"priority": 5})
        self.sm.transition("demo", "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_breaker_fields_survive_serialize_roundtrip(self):
        """序列化→反序列化后两字段不丢（daemon 重启保持性）。"""
        from core.state_machine import StateMachine

        self.sm.update_spec(
            "demo",
            {"_redispatch_same_cause_streak": 3, "_redispatch_cause_fp": "abc123def456"},
        )
        sm2 = StateMachine(self.root / ".fenix" / "STATE.md", MagicMock())
        entry = sm2.read_one("demo")
        assert int(entry.get("_redispatch_same_cause_streak", 0) or 0) == 3
        assert entry.get("_redispatch_cause_fp") == "abc123def456"

    def test_unfreeze_clears_breaker_fields(self):
        """解冻清零：人工处置后同因计数从零起算（同一原子写）。"""
        from core.state_machine import FROZEN_FIELD

        self.sm.update_spec(
            "demo",
            {"status": "blocked", FROZEN_FIELD: True,
             "_redispatch_same_cause_streak": 4, "_redispatch_cause_fp": "fp-xyz",
             "error": "原状态 implementing · 同因重派循环（fp=fp-xyz，连续同因 4 轮）"},
        )
        assert bool(self.sm.read_one("demo").get(FROZEN_FIELD))
        self.sm.unfreeze_spec("demo")
        entry = self.sm.read_one("demo")
        assert int(entry.get("_redispatch_same_cause_streak", -1) or 0) == 0
        assert entry.get("_redispatch_cause_fp") is None
        assert not entry.get(FROZEN_FIELD)


class TestSameCauseCircuitBreaker(_RunAgentBase):
    """tasks 3.8/3.3b/3.5：同因重派熔断 + 作用域边界 + 解冻后不立即熔断。"""

    # 同缺口的 partial 归因文案稳定（指纹同源）；跨轮 epoch 变化的 run 引用
    # 不应改变指纹 → 连续 3 轮同因 → 冻结。
    ROUND_ERROR = (
        "实现者申报未完成（status=partial）：7.3 "
        "run=impl-demo-{epoch}-a1"
    )
    ROUND_PARTIAL = {
        "status": "partial", "spec": "demo",
        "completed_tasks": ["1.1", "1.2"], "unfinished": [],
    }

    def _run_failure_round(self, error_text=None, payload=None, epoch=1,
                           merge_ok=True, merge_error="", success=True):
        """跑一轮失败重派（结果文件驱动），返回 spec entry。"""
        self.sm.transition(self.spec, "implementing")
        if payload is None:
            payload = dict(self.ROUND_PARTIAL)
            payload["unfinished"] = [str(i) for i in payload.get("unfinished", [])]
        _mk_result_file(self.root, self.spec, payload)

        def _fake_impl(spec_name, pre_wt_path=None):
            return SimpleNamespace(
                success=success, error=None,
                run_id=f"impl-{self.spec}-{epoch}-a1",
                branch="fenix/demo-2", duration_seconds=1.0,
                worktree_dirty=[],
            )

        self.engine.agent_runner.run_implementer = MagicMock(side_effect=_fake_impl)
        self.engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )
        self.engine.agent_runner.worktree_manager.merge_back_from_branch = (
            MagicMock(return_value=(merge_ok, merge_error))
        )
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        return self.sm.read_one(self.spec)

    def test_same_cause_reaches_threshold_freezes(self):
        """同因连续达阈值（缺省 3）→ 冻结 + 告警信号 + 不再派发。"""
        from core.state_machine import FROZEN_FIELD
        from core.admin_store import AdminStore

        entry = None
        for r in (1, 2, 3):
            entry = self._run_failure_round(epoch=r)
        assert entry["status"] == "blocked", entry
        assert bool(entry.get(FROZEN_FIELD)), entry
        assert int(entry.get("_redispatch_same_cause_streak", 0) or 0) == 3
        # error 内嵌「原状态 X」+ 指纹 + 轮数
        assert "原状态 implementing" in entry.get("error", ""), entry
        assert "同因重派循环" in entry.get("error", ""), entry
        assert "指纹" in entry.get("error", ""), entry
        # 冻结后 MUST NOT 再 _enqueue（第 3 轮冻结分支不派发）
        assert self.engine._dispatcher._enqueue.call_count == 0
        # 人工升级告警信号
        alerts = [
            a for a in AdminStore(self.root, self.logger).read_all()
            if a.get("signal_type") == "redispatch_loop_detected"
        ]
        assert alerts, "熔断未写 redispatch_loop_detected 告警"

    def test_streak_resets_on_fingerprint_change(self):
        """不同因不误熔断：指纹变化即重置 streak，连续多轮不冻结。"""
        # 抬升 max_retries：本测试验证的是同因 streak 维度（每轮原因不同 → 不
        # 熔断），须避免 3.4 的 max_r 封顶冻结（retries>=3）遮蔽观察点。
        self.engine.config.setdefault("agents", {})["max_retries"] = 20

        entry = None
        for r in (1, 2, 3, 4):
            # 每轮失败归因不同（缺口集合不同 → 归因文案不同 → 指纹不同）
            gap_task = f"1.{r}"
            payload = {
                "status": "partial", "spec": self.spec,
                "completed_tasks": ["1.1", "1.2"], "unfinished": [gap_task],
            }
            entry = self._run_failure_round(epoch=r, payload=payload)
        assert entry["status"] == "ready", entry
        assert "blocked" != entry["status"]
        assert int(entry.get("_redispatch_same_cause_streak", 0) or 0) == 1, entry
        assert int(entry.get("_retry_count", 0) or 0) == 4, entry

    def test_freeze_error_parseable_for_unfreeze_channel(self):
        """冻结 error 经 parse_orig_status → unfreeze_spec(status=orig) 可还原。"""
        from core.state_machine import FROZEN_FIELD, parse_orig_status

        for r in (1, 2, 3):
            entry = self._run_failure_round(epoch=r)
        assert entry["status"] == "blocked"
        orig = parse_orig_status(entry.get("error"))
        assert orig == "implementing", (orig, entry.get("error"))
        # 官方解冻通道：unfreeze_spec(status=orig) 还原为可调度状态
        self.sm.unfreeze_spec(self.spec, status=orig)
        revived = self.sm.read_one(self.spec)
        assert not revived.get(FROZEN_FIELD)
        assert revived["status"] == "implementing"
        # 解冻后计数清零 → 重新派发不立即熔断
        assert int(revived.get("_redispatch_same_cause_streak", 0) or 0) == 0

    def test_merge_breaker_channel_does_not_feed_streak(self):
        """3.3b：merge 指纹熔断通道 MUST NOT 增减 _redispatch_same_cause_streak。"""
        # 预置 streak=2（来自另一渠道），驱动 merge 失败整轮
        self.sm.update_spec(self.spec, {"_redispatch_same_cause_streak": 2,
                                        "_redispatch_cause_fp": "fp-old"})
        # 成功实现 + merge 失败（同一错误指纹连续 < 熔断阈值 → 普通重试分支）
        entry = self._run_failure_round(
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
            merge_ok=False, merge_error="Merge-back failed: conflict in foo",
            success=True,
        )
        # merge 通道只写 _merge_fp/_merge_streak/_retry_count，不碰同因 streak
        assert int(entry.get("_merge_streak", 0) or 0) == 1
        assert int(entry.get("_redispatch_same_cause_streak", 0) or 0) == 2

    def test_provider_transient_channel_does_not_feed_streak(self):
        """3.3b：provider transient 排程 MUST NOT 增减 _redispatch_same_cause_streak。"""
        self.sm.update_spec(self.spec, {"_redispatch_same_cause_streak": 2})
        entry = self._run_failure_round(
            payload={"status": "error", "spec": self.spec,
                     "error": "[provider-transient] gateway timeout"},
            epoch=7, success=False,
        )
        assert int(entry.get("_redispatch_same_cause_streak", 0) or 0) == 2
        assert int(entry.get("_retry_count", 0) or 0) == 0  # transient 不递增 retry

    def test_deliverable_gate_channel_does_not_feed_streak(self):
        """3.3b：交付物守卫 _retry_count 封顶通道 MUST NOT 增减 streak。"""
        self.sm.update_spec(self.spec, {"_redispatch_same_cause_streak": 2})
        self.engine._deliverable_gate_missing = MagicMock(
            return_value=[{"path": "core/foo.py", "violation": "missing"}]
        )
        entry = self._run_failure_round(
            payload={"status": "success", "spec": self.spec,
                     "completed_tasks": ["1.1", "1.2"]},
        )
        # 守卫缺件处置（_retry_count 封顶路径），不碰同因 streak
        assert int(entry.get("_redispatch_same_cause_streak", 0) or 0) == 2

    def test_lock_conflict_backoff_does_not_feed_streak(self):
        """3.3b：锁冲突退避（_dispatch_backoff_until）MUST NOT 增减 streak。"""
        self.sm.update_spec(self.spec, {"_redispatch_same_cause_streak": 2})
        # 退避定时器桩掉（避免真实定时器在测试后触发 _on_spec_ready 再派发）
        self.engine._dispatcher._schedule_backoff_retry = MagicMock()
        self.engine._dispatcher._handle_dispatch_lock_conflict(self.spec)
        entry = self.sm.read_one(self.spec)
        assert int(entry.get("_dispatch_backoff_until") or 0) > 0
        assert int(entry.get("_redispatch_same_cause_streak", 0) or 0) == 2


class TestWorktreeInheritance(unittest.TestCase):
    """tasks 4.2/4.4：成果继承判据 + 预算/豁免正交。"""

    def setUp(self):
        from test_agent_runner import make_runner

        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.spec = "demo"
        _write_main_tasks(self.root, self.spec, HUMAN_GATE_TASKS)
        self.runner = make_runner(self.root)
        self.wt = self.root / ".claude" / "worktrees" / f"impl-{self.spec}-1"
        self.wt.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_wt_result(self, payload):
        (self.wt / ".fenix-run-result.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_keep_for_partial_non_convergent(self):
        """partial 且存在未申报缺口 → keep（供下轮继承）。"""
        self._write_wt_result(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"], "unfinished": []}
        )
        assert self.runner._should_keep_worktree_for_partial(self.spec, self.wt) is True

    def test_no_keep_for_partial_convergent(self):
        """partial 且缺口全申报（收敛）→ 不 keep（正常成功路径 cleanup 不变）。"""
        self._write_wt_result(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73}
        )
        assert self.runner._should_keep_worktree_for_partial(self.spec, self.wt) is False

    def test_no_keep_for_success_or_error(self):
        """success / error 形态 → 不 keep（既有 cleanup 语义不变）。"""
        self._write_wt_result({"status": "success", "spec": self.spec,
                               "completed_tasks": ["1.1", "1.2"]})
        assert self.runner._should_keep_worktree_for_partial(self.spec, self.wt) is False
        self._write_wt_result({"status": "error", "spec": self.spec, "error": "x"})
        assert self.runner._should_keep_worktree_for_partial(self.spec, self.wt) is False

    def test_keep_fail_open_on_exception(self):
        """判定/读取异常 → fail-open 返回 False（走既有 cleanup，不阻断收工）。"""
        (self.wt / ".fenix-run-result.json").write_text("{not-json", encoding="utf-8")
        assert self.runner._should_keep_worktree_for_partial(self.spec, self.wt) is False
        (self.wt / ".fenix-run-result.json").unlink()
        assert self.runner._should_keep_worktree_for_partial(self.spec, self.wt) is False

    def test_cross_assert_runner_judgement_matches_dispatch(self):
        """runner 侧 keep 判据与 dispatch._honest_exit_gap 对同一结果文件同结论。"""
        from core.pm_engine.dispatch import Dispatcher

        cases = [
            # (payload, 期望 keep, 期望收敛)
            ({"status": "partial", "spec": self.spec,
              "completed_tasks": ["1.1", "1.2"], "unfinished": []}, True, False),
            ({"status": "partial", "spec": self.spec,
              "completed_tasks": ["1.1", "1.2"],
              "unattainable": UNATTAINABLE_73}, False, True),
            ({"status": "success", "spec": self.spec,
              "completed_tasks": ["1.1", "1.2"]}, False, False),
        ]
        pm = MagicMock()
        pm.project_root = self.root
        for payload, expect_keep, expect_converged in cases:
            self._write_wt_result(payload)
            keep = self.runner._should_keep_worktree_for_partial(self.spec, self.wt)
            converged = bool(Dispatcher._honest_exit_gap(pm, self.spec, payload))
            assert keep == expect_keep, (payload, keep)
            assert converged == expect_converged, (payload, converged)
            # 逐字等价：runner keep ⟺ (partial ∧ ¬收敛)；_honest_exit_gap 只在
            # partial 域返回非空（= 收敛成立），success/error 域返回 [] 与收敛
            # 无关——等价域以 partial 形态界定。
            is_partial = payload.get("status") == "partial"
            assert keep == (is_partial and not converged), (
                "runner keep 判据 MUST 与 dispatch._honest_exit_gap 逐字等价",
                payload)

    def test_breaker_freeze_keeps_budget_and_skips_death_exempt(self):
        """4.4：熔断时 _impl_run_budget_used 保持真实值、MUST NOT 走死亡 run 豁免。"""
        sm, engine, logger = _make_engine(self.root)
        engine.config.setdefault("agents", {})["max_same_cause_redispatches"] = 2
        sm.add_spec(self.spec, {"priority": 5})
        sm.transition(self.spec, "ready")
        engine._exempt_dead_run_budget = MagicMock()
        engine._increment_impl_run_budget_used = MagicMock(
            wraps=lambda s: sm.update_spec(
                s, {"_impl_run_budget_used": int(
                    (sm.read_one(s) or {}).get("_impl_run_budget_used", 0) or 0) + 1}
            ) or 0
        )

        def _fake_impl(spec_name, pre_wt_path=None):
            return SimpleNamespace(
                success=True, error=None,
                run_id=f"impl-{self.spec}-1-a1", branch=None,
                duration_seconds=1.0, worktree_dirty=[],
            )

        engine.agent_runner.run_implementer = MagicMock(side_effect=_fake_impl)
        engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )
        for r in (1, 2):
            sm.transition(self.spec, "implementing")
            _mk_result_file(self.root, self.spec,
                            {"status": "partial", "spec": self.spec,
                             "completed_tasks": ["1.1", "1.2"], "unfinished": []})
            engine._run_agent_worker(self.spec, "implementer", 5)
        entry = sm.read_one(self.spec)
        assert entry["status"] == "blocked"
        # 预算计数保持真实值（每轮启动递增一次），MUST NOT 被熔断重置
        assert int(entry.get("_impl_run_budget_used", 0) or 0) == 2, entry
        # 死亡 run 豁免（无收工结果形态）MUST NOT 被触发
        engine._exempt_dead_run_budget.assert_not_called()


if __name__ == "__main__":
    unittest.main()
