"""诚实退出（unattainable）在 partial 收敛路径的贯通测试（2026-09-17 admin 处置）。

背景（fix-dashboard-read-path-performance 实测事故，2026-09-16）：
实现者把「需用户确认时机后重启 daemon」这类人工运维门控任务用 unattainable
如实申报并以 partial 收工（禁止先勾后做），但两处契约缺口使其无法收敛：

1. 产物硬门 `_check_partial_consistency` 的「并集 == 全部数字任务 id」判据把
   unattainable 任务逼成「必须出现在 unfinished」——而那等于谎报「agent 未完成
   一个它客观上做不了的任务」；且该失败未带 `[task-gate]` 前缀，不参与
   「只卡第一次」降级，实现者被同一门无限拒回。
2. `[task-gate]` 文案不指引 unattainable 出路，实现者三轮原地重试后仍不知该申报。

本文件覆盖修复后的判据与收敛：任一项回归，spec 会重新落入 implementing
悬置（admin orphaned_state 唤起）→ 重复烧预算。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_impl_tasks_completion_gate import _mk_worktree, _write_result  # noqa: E402
from test_agent_runner import make_runner  # noqa: E402

# tasks.md：1.1/1.2 完成，7.3 为人工运维门控（未勾）
HUMAN_GATE_TASKS = (
    "# Tasks\n\n## 1. 实现\n\n- [x] 1.1 任务一\n- [x] 1.2 任务二\n"
    "## 7. 收尾\n\n- [ ] 7.3 经用户确认时机后重启 daemon\n"
)
UNATTAINABLE_73 = [
    {"task": "7.3", "reason": "人工运维门控：需用户确认时机后重启 daemon",
     "evidence": "重启会打断在飞 run，须由用户掌控时机"}
]


class TestPartialUnattainableGate(unittest.TestCase):
    """产物硬门：partial + unattainable 申报的判据（改进②补齐 partial 路径）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        self.runner = make_runner(self.proot)
        self.spec = "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _gate(self, tasks_text, payload):
        wt = _mk_worktree(self.proot, self.spec, tasks_text=tasks_text)
        _write_result(wt, payload)
        return self.runner._check_impl_result_artifact(self.spec, None, wt)

    def test_partial_with_unattainable_passes(self):
        """缺口全部 ⊆ unattainable（且未列入 unfinished）→ 放行（本 SPEC 修复点）。"""
        err = self._gate(
            HUMAN_GATE_TASKS,
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73},
        )
        assert err is None, err

    def test_partial_unattainable_also_listed_in_unfinished_passes(self):
        """unattainable 同时列入 unfinished（形式差异）→ 同样放行。"""
        err = self._gate(
            HUMAN_GATE_TASKS,
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"], "unfinished": ["7.3"],
             "unattainable": UNATTAINABLE_73},
        )
        assert err is None, err

    def test_partial_undeclared_gap_still_blocked(self):
        """未申报的缺口（既不在 unfinished 也不在 unattainable）→ 仍拦（防洗白）。"""
        err = self._gate(
            HUMAN_GATE_TASKS,
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"], "unfinished": []},
        )
        assert err is not None
        assert "未申报缺口" in err
        assert "7.3" in err

    def test_partial_message_points_to_unattainable(self):
        """拒绝文案 MUST 指引 unattainable 申报语法（防实现者不知出路）。"""
        err = self._gate(
            HUMAN_GATE_TASKS,
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"], "unfinished": []},
        )
        assert "unattainable" in err
        assert '"task": "7.3"' in err

    def test_partial_unattainable_for_checked_task_blocked(self):
        """unattainable 申报已勾选任务 → 判失败（不能拿它洗白已完成项）。"""
        err = self._gate(
            HUMAN_GATE_TASKS,
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": [{"task": "1.1", "reason": "假申报"}]},
        )
        assert err is not None
        assert "非未完成任务" in err

    def test_partial_pure_unfinished_unchanged(self):
        """纯 unfinished 申报（非 unattainable 任务）语义不变 → 放行。"""
        err = self._gate(
            "## 1. 实现\n\n- [x] 1.1 任务一\n- [ ] 1.2 任务二\n",
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1"], "unfinished": ["1.2"]},
        )
        assert err is None, err


class TestHonestExitConvergence(unittest.TestCase):
    """收敛路径：partial + 全量 unattainable 申报 → 不重派，按成功收口转验证。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine

        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.root, self.logger)
        self.spec = "demo"
        self.spec_dir = self.root / "spec" / "changes" / self.spec
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        (self.spec_dir / "tasks.md").write_text(HUMAN_GATE_TASKS, encoding="utf-8")
        self.engine._enqueue = MagicMock()
        # 观察点：dispatcher 直接 self._enqueue_front（refactor-giant-classes 3.8
        # 消解回引后不再经 engine 门面委托转发）
        self.engine._dispatcher._enqueue_front = MagicMock()
        self.engine._process_queue = MagicMock()
        self.engine._reconcile_impl_budget = MagicMock()
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.transition(self.spec, "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _partial_result(self, payload):
        self.sm.transition(self.spec, "implementing")
        from types import SimpleNamespace

        def _fake_impl(spec_name, pre_wt_path=None):
            (self.root / ".fenix" / ".fenix-run-result.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return SimpleNamespace(
                success=True, error=None, run_id=f"impl-{self.spec}-1-a1",
                branch=None, duration_seconds=1.0,
            )

        self.engine.agent_runner.run_implementer = MagicMock(side_effect=_fake_impl)
        # 结果文件从主树共享路径读取（无活跃 worktree → 回退主树，与真实
        # 「run 已收工、worktree 已清理」形态一致）
        self.engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        return self.sm.read_one(self.spec)

    def test_all_unattainable_converges_to_implemented(self):
        """partial + 缺口全申报 → implemented（转验证），不进重试。"""
        entry = self._partial_result(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73}
        )
        assert entry["status"] == "implemented", entry
        assert int(entry.get("_retry_count", 0) or 0) == 0
        assert self.engine._dispatcher._enqueue_front.call_args[0][1] == "verifier"

    def test_undeclared_gap_still_retries(self):
        """partial 但存在未申报缺口 → 仍按失败重派（不洗白）。"""
        entry = self._partial_result(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"], "unfinished": []}
        )
        assert entry["status"] == "ready", entry
        assert int(entry.get("_retry_count", 0) or 0) == 1
        assert entry.get("error")

    def test_honest_exit_writes_human_todo_alert(self):
        """诚实退出放行 MUST 写人工待办告警（approve 环节可见）。"""
        from core.admin_store import AdminStore

        self._partial_result(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73}
        )
        alerts = [
            a for a in AdminStore(self.root, self.logger).read_all()
            if a.get("signal_type") == "impl_unattainable_tasks"
        ]
        assert alerts, "诚实退出未写 impl_unattainable_tasks 告警"
        assert "7.3" in (alerts[0].get("evidence") or "")

    def test_honest_exit_snapshots_impl_result(self):
        """诚实退出收敛写 per-spec 快照（verified→done 门禁的证据源）。"""
        self._partial_result(
            {"status": "partial", "spec": self.spec,
             "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73}
        )
        snap = (self.root / ".fenix" / "verify-progress" / self.spec
                / "impl-result.json")
        assert snap.is_file(), "诚实退出未写 impl-result 快照"
        assert json.loads(snap.read_text(encoding="utf-8"))["status"] == "partial"


# tasks.md：主树侧全部未勾（partial 收敛走不到 _sync_task_progress 回写路径，
# 收敛判据 MUST NOT 读它）。1.1/1.2 已在 worktree 完成并登记进 completed_tasks。
ALL_UNCHECKED_TASKS = (
    "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 任务一\n- [ ] 1.2 任务二\n"
    "## 7. 收尾\n\n- [ ] 7.3 经用户确认时机后重启 daemon\n"
)


class TestHonestExitGapReadSource(unittest.TestCase):
    """缺口口径回归：MUST 取结果文件，MUST NOT 读主树 tasks.md 勾选。

    复现 fix-robustness-edge-cases 读侧自锁（2026-09-17）：主树 tasks.md 因
    partial 收敛走不到回写路径而全未勾选；旧实现回退读主树 → 把已在
    completed_tasks 里的 1.1/1.2 也算成缺口 → 缺口 ⊄ unattainable → 判失败
    → 重派 → 主树仍全未勾 → 永久循环（实测 3 轮、每轮 ~$18、首轮整支丢弃）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.spec = "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_main_tasks(self, text):
        d = self.root / "spec" / "changes" / self.spec
        d.mkdir(parents=True, exist_ok=True)
        (d / "tasks.md").write_text(text, encoding="utf-8")

    def test_gap_from_result_ignores_main_tree_checked_state(self):
        """主树全未勾 + completed_tasks 齐全 → 缺口仅剩真正未完成者。"""
        from core.run_task_track import gap_from_result

        self._write_main_tasks(ALL_UNCHECKED_TASKS)
        gap = gap_from_result(
            {"status": "partial", "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73},
            self.root, self.spec,
        )
        assert gap == ["7.3"], gap

    def test_gap_from_result_prefers_unfinished(self):
        """unfinished 非空 → 直接采信（不反推）。"""
        from core.run_task_track import gap_from_result

        self._write_main_tasks(ALL_UNCHECKED_TASKS)
        gap = gap_from_result(
            {"status": "partial", "completed_tasks": ["1.1"],
             "unfinished": ["1.2", "7.3"]},
            self.root, self.spec,
        )
        assert gap == ["1.2", "7.3"], gap

    def test_honest_exit_gap_converges_with_unchecked_main_tree(self):
        """主树全未勾（自锁场景）下，缺口 ⊆ unattainable → 收敛成立。"""
        from core.pm_engine.dispatch import Dispatcher

        self._write_main_tasks(ALL_UNCHECKED_TASKS)
        pm = MagicMock()
        pm.project_root = self.root
        gap = Dispatcher._honest_exit_gap(
            pm, self.spec,
            {"status": "partial", "completed_tasks": ["1.1", "1.2"],
             "unattainable": UNATTAINABLE_73},
        )
        assert gap == ["7.3"], gap

    def test_honest_exit_gap_still_blocks_undeclared(self):
        """主树全未勾且存在未申报缺口（1.2 未完成也未申报）→ 仍拦（防洗白）。"""
        from core.pm_engine.dispatch import Dispatcher

        self._write_main_tasks(ALL_UNCHECKED_TASKS)
        pm = MagicMock()
        pm.project_root = self.root
        gap = Dispatcher._honest_exit_gap(
            pm, self.spec,
            {"status": "partial", "completed_tasks": ["1.1"],
             "unattainable": UNATTAINABLE_73},
        )
        assert gap == [], gap
