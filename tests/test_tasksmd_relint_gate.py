"""tasks.md 收口复检门禁测试（add-tasksmd-relint-gate）。

Task 2.1 full 车道：implementer 成功后 merge 前的 relint 门禁。
Task 2.2 fast-track 车道：交付物守卫后、硬校验前的 relint 门禁。
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunResult
from core.state_machine import StateMachine


def _mk_spec_dir(root, name, mode="full"):
    d = root / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / ".spec.yaml").write_text(
        f"schema: spec-driven\ncreated: 2026-09-11\nmode: {mode}\n",
        encoding="utf-8",
    )
    return d


def _mk_fast_spec_dir(root, name):
    d = root / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / ".spec.yaml").write_text(
        "schema: spec-driven\ncreated: 2026-09-11\nmode: fast-track\n",
        encoding="utf-8",
    )
    (d / "tasks.md").write_text(
        "# Tasks\n\n## 1. x\n\n- [ ] 1.1 do it\n", encoding="utf-8",
    )
    return d


def _fast_result(verdict="verified"):
    return {
        "status": "success", "spec": "demo", "mode": "fast-track", "summary": "ok",
        "verification": {
            "scenarios": [{
                "scenario_id": "s1", "description": "d", "status": "pass",
                "assertion_results": [{"type": "step", "pass": True, "message": ""}],
                "screenshots": ["/tmp/s1.png"],
            }],
            "verdict": verdict,
            "bugs": [],
        },
    }


DAMAGED_TASKS = (
    "# Tasks\n\n## 1. Setup\n\n^- [x] 1.1 a\n^- [x] 1.2 b\n\n"
    "## 2. Core\n\n^- [x] 2.1 c\n"
)

NORMAL_TASKS = (
    "# Tasks\n\n## 1. Setup\n\n- [x] 1.1 a\n- [x] 1.2 b\n\n"
    "## 2. Core\n\n- [x] 2.1 c\n"
)


class _FullBase(unittest.TestCase):
    """full 车道 relint 门禁测试夹具。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from core.pm_engine import PMEngine
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.pr, self.logger)
        # mock worktree manager
        wm = MagicMock()
        wm.ensure_spec_committed.return_value = True
        wm.merge_back_from_branch.return_value = (True, "")
        wm.consume_legacy = MagicMock()
        wm.has_active_worktree.return_value = False
        wm.last_stash_pop_conflicts = []
        wm.find_implementer_worktree.return_value = None
        self.engine.agent_runner.worktree_manager = wm
        # mock required methods
        self.engine._verification._implementer_zero_change = MagicMock(return_value=False)
        self.engine._verification._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._write_impl_result_snapshot = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine.handle_event = MagicMock()
        # prevent _process_queue from re-dispatching in the finally block
        self.engine._process_queue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mk(self, name="demo"):
        _mk_spec_dir(self.pr, name, mode="full")
        vp = self.pr / ".fenix" / "verify-progress" / name
        vp.mkdir(parents=True, exist_ok=True)
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")


class TestFullLaneRelintGate(_FullBase):
    """Task 2.1: full 车道 implementer 成功后 merge 前 relint 门禁。"""

    def _run_implementer_success(self, spec_name="demo", branch="fenix/demo-1"):
        """simulate a successful implementer run going through _run_agent_worker."""
        result = SimpleNamespace(
            success=True, error=None, run_id="impl-demo-1", branch=branch,
            worktree_dirty=[], cancelled=False, worktree_path=None,
        )
        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        # _read_implementer_result must return success
        self.engine._read_implementer_result = MagicMock(return_value={
            "status": "success", "spec": spec_name,
        })
        # drive the agent worker
        self.engine._run_agent_worker(spec_name, "implementer", 5)

    def test_damaged_tasks_md_blocks_merge(self):
        """分支 tasks.md 带损伤前缀 → 不 merge、状态回 ready、error 含违规明细。"""
        self._mk()
        # patch _tasks_md_relint_from_branch to return violations
        self.engine._verification._tasks_md_relint_from_branch = MagicMock(return_value=[
            "tasks.md 存在任务分组（2 个），但未解析出任何任务行——任务行必须为 "
            "`- [ ] <编号>. <任务>` / `- [x] <编号>. <任务>` 行首形态"
        ])
        self._run_implementer_success()
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("tasks.md 收口复检违规", entry["error"])
        self.assertIn("任务分组", entry["error"])
        # branch must NOT be merged
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.assert_not_called()

    def test_damaged_tasks_md_error_has_prescription(self):
        """违规 error 须含 `- [ ]`/`- [x]` 修正处方和 `^-` 损伤特征。"""
        self._mk()
        self.engine._verification._tasks_md_relint_from_branch = MagicMock(return_value=[
            "tasks.md 存在任务分组（2 个），但未解析出任何任务行"
        ])
        self._run_implementer_success()
        entry = self.sm.read_one("demo")
        self.assertIn("- [ ]", entry["error"])
        self.assertIn("- [x]", entry["error"])
        self.assertIn("^-", entry["error"])

    def test_normal_tasks_md_proceeds_to_merge(self):
        """分支 tasks.md 正常 → 复检放行，正常 merge 执行。"""
        self._mk()
        self.engine._verification._tasks_md_relint_from_branch = MagicMock(return_value=[])
        self._run_implementer_success()
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.assert_called_once_with("fenix/demo-1")
        entry = self.sm.read_one("demo")
        self.assertNotIn("relint", (entry.get("error") or "").lower())

    def test_no_tasks_md_fail_open(self):
        """分支无 tasks.md → fail-open 放行。"""
        self._mk()
        self.engine._verification._tasks_md_relint_from_branch = MagicMock(return_value=[])
        self._run_implementer_success()
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.assert_called_once()

    def test_git_show_failure_fail_open(self):
        """git show 失败 → fail-open 放行 + WARNING。"""
        self._mk()
        # simulate git show failure returning empty list
        self.engine._verification._tasks_md_relint_from_branch = MagicMock(return_value=[])
        self._run_implementer_success()
        # verify merge proceeds (fail-open)
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.assert_called_once()
        self.assertTrue(self.engine._verification._tasks_md_relint_from_branch.called)


class TestFullLaneRelintGitShow(unittest.TestCase):
    """full 车道 git show 读取行为（真实 subprocess mock）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from core.pm_engine import PMEngine
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.pr, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("subprocess.run")
    def test_git_show_returns_violations(self, mock_run):
        """git show 返回损伤 tasks.md → lint_tasks_text 判违规。"""
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout=DAMAGED_TASKS, stderr="",
        )
        violations = self.engine._tasks_md_relint_from_branch("demo", "fenix/demo-1")
        self.assertEqual(len(violations), 1)
        self.assertIn("任务分组", violations[0])
        self.assertIn("tasks.md", violations[0])

    @patch("subprocess.run")
    def test_git_show_normal_returns_empty(self, mock_run):
        """git show 返回正常 tasks.md → 空违规列表。"""
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout=NORMAL_TASKS, stderr="",
        )
        violations = self.engine._tasks_md_relint_from_branch("demo", "fenix/demo-1")
        self.assertEqual(violations, [])

    @patch("subprocess.run")
    def test_git_show_nonzero_returns_empty(self, mock_run):
        """git show 返回非零退出码（路径不存在）→ fail-open（不记 WARNING）。"""
        mock_run.return_value = SimpleNamespace(
            returncode=1, stdout="", stderr="fatal: path not found",
        )
        violations = self.engine._tasks_md_relint_from_branch("demo", "fenix/demo-1")
        self.assertEqual(violations, [])
        # 路径不存在属合法形态，不记 WARNING（与 lint「文件不存在不拦」同语义）
        self.assertFalse(self.logger.warning.called)

    @patch("subprocess.run")
    def test_git_show_timeout_returns_empty(self, mock_run):
        """git show 超时 → fail-open + WARNING。"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=15)
        violations = self.engine._tasks_md_relint_from_branch("demo", "fenix/demo-1")
        self.assertEqual(violations, [])
        self.assertTrue(self.logger.warning.called)

    def test_no_branch_returns_empty(self):
        """branch 为空 → fail-open。"""
        violations = self.engine._tasks_md_relint_from_branch("demo", None)
        self.assertEqual(violations, [])

    def test_no_branch_empty_string_returns_empty(self):
        """branch 为空字符串 → fail-open。"""
        violations = self.engine._tasks_md_relint_from_branch("demo", "")
        self.assertEqual(violations, [])


class TestFullLaneRelintRedispatchCounting(unittest.TestCase):
    """full 车道 relint 违规重派计数：连续 3 次 → blocked。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from core.pm_engine import PMEngine
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.pr, self.logger)
        # _redispatch_tasks_relint is on Dispatcher; access via _dispatcher property
        self.dispatcher = self.engine._dispatcher
        # 观察点：dispatcher 直接 self._enqueue_front（refactor-giant-classes 3.8
        # 消解回引后不再经 engine 门面委托转发）
        self.dispatcher._enqueue_front = MagicMock()
        self.sm.add_spec("demo", {"priority": 5})
        self.sm.transition("demo", "implementing")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_first_relint_sets_retry_count_1(self):
        self.dispatcher._redispatch_tasks_relint("demo", ["violation"],
                                                 run_id="run-1")
        entry = self.sm.read_one("demo")
        self.assertEqual(int(entry["_retry_count"]), 1)
        self.assertEqual(entry["status"], "ready")
        self.dispatcher._enqueue_front.assert_called_once_with("demo", "implementer")

    def test_third_relint_blocks(self):
        """连续 3 次 relint → blocked。"""
        for i in range(1, 4):
            self.dispatcher._redispatch_tasks_relint("demo", [f"violation-{i}"],
                                                     run_id=f"run-{i}")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("连续 3 次", entry["error"])
        self.assertIn("blocked", entry["error"])
        self.assertEqual(int(entry["_retry_count"]), 3)

    def test_relint_error_includes_prescription(self):
        self.dispatcher._redispatch_tasks_relint("demo", ["任务行全灭"],
                                                 run_id="run-1")
        entry = self.sm.read_one("demo")
        self.assertIn("修正处方", entry["error"])
        self.assertIn("- [ ]", entry["error"])
        self.assertIn("^-", entry["error"])


class _Base(unittest.TestCase):
    """fast-track 车道共用夹具（与 test_fast_track_dispatch.py 同构）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.pr / ".fenix" / "verify-progress").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from core.pm_engine import PMEngine
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.pr, self.logger)
        self.engine.handle_event = MagicMock()
        # mock worktree manager
        wm = MagicMock()
        wm.ensure_spec_committed.return_value = True
        wm.merge_back_from_branch.return_value = (True, "")
        wm.consume_legacy = MagicMock()
        wm.has_active_worktree.return_value = False
        wm.last_stash_pop_conflicts = []
        self.engine.agent_runner.worktree_manager = wm
        # mock _on_spec_verified and _enqueue
        self.engine._on_spec_verified = MagicMock()
        self._enqueued = []

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mk(self, name="demo"):
        _mk_fast_spec_dir(self.pr, name)
        vp = self.pr / ".fenix" / "verify-progress" / name
        vp.mkdir(parents=True, exist_ok=True)
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")


class TestFastTrackLaneRelintGate(_Base):
    """Task 2.2: fast-track 车道交付物守卫后、硬校验前 relint 门禁。"""

    def _prepare(self, worktree_path=None, worktree_kept=False):
        self._mk()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0,
            branch="fenix/demo-1",
            worktree_path=worktree_path, worktree_kept=worktree_kept,
        )
        self.engine._verification._implementer_zero_change = MagicMock(return_value=False)
        self.engine._verification._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()

    def _write_designed(self, ids):
        sp = self.pr / ".fenix" / "verify-progress" / "demo" / "test_scenarios.json"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(
            json.dumps([{"id": i, "description": "d", "steps": [], "assertions": []}
                        for i in ids]),
            encoding="utf-8",
        )

    def test_damaged_tasks_md_keeps_worktree_and_redispatches(self):
        """worktree 内 tasks.md 损伤 → keep worktree + 失败重派 + error 有明细处方。"""
        wt = self.pr / "wt-demo"
        wt.mkdir(parents=True, exist_ok=True)
        self._prepare(worktree_path=wt)
        self._write_designed(["s1"])
        self.engine._read_implementer_result = MagicMock(
            return_value=_fast_result("verified"))
        self.engine._verification._tasks_md_relint_from_worktree = MagicMock(return_value=[
            "tasks.md 存在任务分组（2 个），但未解析出任何任务行"
        ])

        self.engine._run_fast_track_worker("demo")

        wm = self.engine.agent_runner.worktree_manager
        wm.keep_for_reuse.assert_called_once()
        self.assertEqual(wm.keep_for_reuse.call_args[0][0], "demo")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("tasks.md 收口复检违规", entry["error"])
        self.assertIn("- [ ]", entry["error"])
        self.assertIn("^-", entry["error"])

    def test_normal_tasks_md_proceeds_to_hard_check(self):
        """worktree 内 tasks.md 正常 → 流程继续硬校验与 merge。"""
        wt = self.pr / "wt-demo"
        wt.mkdir(parents=True, exist_ok=True)
        self._prepare(worktree_path=wt)
        self._write_designed(["s1"])
        self.engine._read_implementer_result = MagicMock(
            return_value=_fast_result("verified"))
        self.engine._verification._tasks_md_relint_from_worktree = MagicMock(return_value=[])
        self.engine._on_spec_verified = MagicMock()

        self.engine._run_fast_track_worker("demo")

        wm = self.engine.agent_runner.worktree_manager
        wm.cleanup.assert_called_once_with(wt, success=True)
        wm.keep_for_reuse.assert_not_called()
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "verified")

    def test_missing_tasks_md_fail_open(self):
        """worktree 内无 tasks.md → fail-open 放行、继续硬校验。"""
        wt = self.pr / "wt-demo"
        wt.mkdir(parents=True, exist_ok=True)
        self._prepare(worktree_path=wt)
        self._write_designed(["s1"])
        self.engine._read_implementer_result = MagicMock(
            return_value=_fast_result("verified"))
        self.engine._verification._tasks_md_relint_from_worktree = MagicMock(return_value=[])
        self.engine._on_spec_verified = MagicMock()

        self.engine._run_fast_track_worker("demo")

        wm = self.engine.agent_runner.worktree_manager
        wm.cleanup.assert_called_once_with(wt, success=True)
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "verified")

    def test_lint_exception_fail_open(self):
        """lint 异常 → fail-open 放行 + WARNING（不阻塞 merge）。"""
        wt = self.pr / "wt-demo"
        wt.mkdir(parents=True, exist_ok=True)
        self._prepare(worktree_path=wt)
        self._write_designed(["s1"])
        self.engine._read_implementer_result = MagicMock(
            return_value=_fast_result("verified"))
        self.engine._verification._tasks_md_relint_from_worktree = MagicMock(
            side_effect=OSError("disk gone"))
        self.engine._on_spec_verified = MagicMock()

        self.engine._run_fast_track_worker("demo")

        wm = self.engine.agent_runner.worktree_manager
        wm.cleanup.assert_called_once_with(wt, success=True)
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "verified")
        self.assertTrue(self.engine.logger.warning.called)


class TestFastTrackRelintWorktreeReading(unittest.TestCase):
    """fast-track worktree 读取行为：真实文件系统。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from core.pm_engine import PMEngine
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.pr, self.logger)
        # build a worktree-like dir with damaged tasks.md
        self.wt = self.pr / "wt"
        (self.wt / "spec" / "changes" / "demo").mkdir(parents=True, exist_ok=True)
        (self.wt / "spec" / "changes" / "demo" / "tasks.md").write_text(
            DAMAGED_TASKS, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_worktree_damaged_returns_violation(self):
        violations = self.engine._tasks_md_relint_from_worktree("demo", self.wt)
        self.assertEqual(len(violations), 1)
        self.assertIn("任务分组", violations[0])

    def test_worktree_normal_returns_empty(self):
        wt = self.pr / "wt"
        (wt / "spec" / "changes" / "demo" / "tasks.md").write_text(
            NORMAL_TASKS, encoding="utf-8")
        violations = self.engine._tasks_md_relint_from_worktree("demo", self.wt)
        self.assertEqual(violations, [])

    def test_worktree_missing_tasks_md_returns_empty(self):
        (self.wt / "spec" / "changes" / "demo" / "tasks.md").unlink()
        violations = self.engine._tasks_md_relint_from_worktree("demo", self.wt)
        self.assertEqual(violations, [])

    def test_worktree_none_returns_empty(self):
        violations = self.engine._tasks_md_relint_from_worktree("demo", None)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
