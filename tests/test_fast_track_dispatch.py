"""add-fast-track-mode task 3/8.1：fast-track 派发全链路测试（mock runner）。"""
import json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunResult
from core.state_machine import StateMachine
from core.openspec_mode import read_spec_mode


def _mk_spec_dir(root, name, mode="fast-track"):
    d = root / "openspec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / ".openspec.yaml").write_text(
        f"schema: spec-driven\ncreated: 2026-09-02\nmode: {mode}\n",
        encoding="utf-8",
    )
    (d / "tasks.md").write_text("# Tasks\n\n## 1. x\n\n- [ ] 1.1 do it\n", encoding="utf-8")
    return d


def _fast_result(verdict="verified"):
    scenarios = [
        {
            "scenario_id": "s1",
            "description": "场景一",
            "status": "pass" if verdict == "verified" else "fail",
            "assertion_results": [{"type": "step", "pass": verdict == "verified", "message": ""}],
            "screenshots": ["/tmp/s1.png"],
        }
    ]
    if verdict != "verified":
        scenarios[0].update({
            "classification": "product-bug",
            "evidence": {"failed_assertions": [{"type": "x"}], "first_failed_step": "s1"},
        })
    return {
        "status": "success", "spec": "demo", "mode": "fast-track", "summary": "ok",
        "verification": {
            "scenarios": scenarios,
            "verdict": verdict,
            "bugs": [] if verdict == "verified" else [
                {"severity": "major", "scenario_ids": ["s1"], "description": "bug"}
            ],
        },
    }


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.pr / ".fenix" / "verify-progress").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from core.pm_engine import PMEngine
        self.sm = StateMachine(self.pr / "STATE.md", self.logger)
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
        _mk_spec_dir(self.pr, name)
        vp = self.pr / ".fenix" / "verify-progress" / name
        vp.mkdir(parents=True, exist_ok=True)
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")


class TestModeAwareDispatch(_Base):
    def test_fast_track_mode_enqueues_fast_track(self):
        self._mk()
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_ready("demo")
        calls = [c[0] for c in self.engine._enqueue.call_args_list]
        self.assertIn(("demo", "fast-track"), calls)


class TestFastTrackVerified(_Base):
    def test_success_advances_to_verified(self):
        self._mk()
        # stub runner.run_fast_track
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0,
            branch="fenix/demo-1",
        )
        # stub result file
        result_path = self.pr / ".fenix-run-result.json"
        result_path.write_text(json.dumps(_fast_result("verified")), encoding="utf-8")
        # write designed scenarios
        sp = self.pr / ".fenix" / "verify-progress" / "demo" / "test_scenarios.json"
        sp.write_text(
            json.dumps([{"id": "s1", "description": "d", "steps": [], "assertions": []}]),
            encoding="utf-8",
        )
        self.engine._read_implementer_result = MagicMock(return_value=_fast_result("verified"))
        self.engine._implementer_zero_change = MagicMock(return_value=False)
        self.engine._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()
        self.sm.transition("demo", "implementing")

        self.engine._run_fast_track_worker("demo")

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "verified")
        self.engine._on_spec_verified.assert_called_once_with("demo")


class TestFastTrackZeroChange(_Base):
    def test_zero_change_redispatches(self):
        self._mk()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0,
            branch="fenix/demo-1", worktree_dirty=[],
        )
        self.engine._read_implementer_result = MagicMock(return_value=_fast_result("verified"))
        self.engine._implementer_zero_change = MagicMock(return_value=True)
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.sm.transition("demo", "implementing")

        self.engine._run_fast_track_worker("demo")

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")


class TestFastTrackIllegalResult(_Base):
    def test_illegal_result_redispatches(self):
        self._mk()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0, branch="fenix/demo-1",
        )
        self.engine._read_implementer_result = MagicMock(return_value=None)
        self.engine._implementer_zero_change = MagicMock(return_value=False)
        self.engine._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.sm.transition("demo", "implementing")

        self.engine._run_fast_track_worker("demo")

        entry = self.sm.read_one("demo")
        self.assertIn(entry["status"], ("ready", "implementing"))


class TestFastTrackBugFoundEscalates(_Base):
    def test_bug_found_escalates_to_full(self):
        self._mk()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0, branch="fenix/demo-1",
        )
        ft_res = _fast_result("bug-found")
        self.engine._read_implementer_result = MagicMock(return_value=ft_res)
        self.engine._implementer_zero_change = MagicMock(return_value=False)
        self.engine._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._enqueue = MagicMock()
        self.sm.transition("demo", "implementing")

        self.engine._run_fast_track_worker("demo")

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "implemented")
        # mode should be full
        self.assertEqual(read_spec_mode(self.pr, "demo"), "full")
        # verifier should be enqueued
        self.engine._enqueue.assert_called_with("demo", "verifier")


class TestFastTrackWorktreeReuse(_Base):
    """worktree 继承：打回保留、成功回收（runner 成功路径延迟清理由 dispatch 处置）。"""

    def _prepare(self, worktree_path=None, worktree_kept=False):
        self._mk()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0,
            branch="fenix/demo-1",
            worktree_path=worktree_path, worktree_kept=worktree_kept,
        )
        self.engine._implementer_zero_change = MagicMock(return_value=False)
        self.engine._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()
        self.sm.transition("demo", "implementing")

    def _write_designed(self, ids):
        sp = self.pr / ".fenix" / "verify-progress" / "demo" / "test_scenarios.json"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(
            json.dumps([{"id": i, "description": "d", "steps": [], "assertions": []}
                        for i in ids]),
            encoding="utf-8",
        )

    def test_hard_check_fail_keeps_worktree_with_prescription(self):
        self._prepare(worktree_path=Path("/tmp/wt-demo"))
        self._write_designed(["s1"])
        # 执行集缺 s1（scenario_id 改名）→ 场景静默遗漏
        ft = _fast_result("verified")
        ft["verification"]["scenarios"][0]["scenario_id"] = "s2"
        self.engine._read_implementer_result = MagicMock(return_value=ft)

        self.engine._run_fast_track_worker("demo")

        wm = self.engine.agent_runner.worktree_manager
        wm.keep_for_reuse.assert_called_once()
        self.assertEqual(wm.keep_for_reuse.call_args[0][0], "demo")
        entry = self.sm.read_one("demo")
        self.assertIn("场景静默遗漏", entry["error"])
        self.assertIn("修复处方", entry["error"])

    def test_terminal_failure_kept_by_runner_skips_double_keep(self):
        # 终态失败：runner 已保留（worktree_kept=True），dispatch 不重复保留
        self._prepare(worktree_path=Path("/tmp/wt-demo"), worktree_kept=True)
        self.engine._read_implementer_result = MagicMock(return_value=None)

        self.engine._run_fast_track_worker("demo")

        wm = self.engine.agent_runner.worktree_manager
        wm.keep_for_reuse.assert_not_called()

    def test_merge_success_releases_deferred_worktree(self):
        self._prepare(worktree_path=Path("/tmp/wt-demo"))
        self._write_designed(["s1"])
        self.engine._read_implementer_result = MagicMock(
            return_value=_fast_result("verified"))
        self.engine._on_spec_verified = MagicMock()

        self.engine._run_fast_track_worker("demo")

        wm = self.engine.agent_runner.worktree_manager
        wm.cleanup.assert_called_once_with(Path("/tmp/wt-demo"), success=True)
        wm.keep_for_reuse.assert_not_called()
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "verified")

    def test_merge_fail_keeps_worktree_for_retry(self):
        self._prepare(worktree_path=Path("/tmp/wt-demo"))
        self._write_designed(["s1"])
        self.engine._read_implementer_result = MagicMock(
            return_value=_fast_result("verified"))
        self.engine._on_spec_verified = MagicMock()
        self.engine.agent_runner.worktree_manager.merge_back_from_branch \
            .return_value = (False, "conflict")

        self.engine._run_fast_track_worker("demo")

        wm = self.engine.agent_runner.worktree_manager
        wm.keep_for_reuse.assert_called_once()
        entry = self.sm.read_one("demo")
        self.assertIn("Merge-back failed", entry["error"])


if __name__ == "__main__":
    unittest.main()
