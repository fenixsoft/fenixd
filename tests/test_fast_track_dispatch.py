"""add-fast-track-mode task 3/8.1：fast-track 派发全链路测试（mock runner）。"""
import json, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunResult
from core.state_machine import StateMachine
from core.spec_mode import read_spec_mode


def _mk_spec_dir(root, name, mode="fast-track"):
    d = root / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / ".spec.yaml").write_text(
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
        _mk_spec_dir(self.pr, name)
        vp = self.pr / ".fenix" / "verify-progress" / name
        vp.mkdir(parents=True, exist_ok=True)
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")


class TestModeAwareDispatch(_Base):
    def test_fast_track_mode_enqueues_fast_track(self):
        self._mk()
        self.engine._dispatcher._enqueue = MagicMock()
        self.engine._on_spec_ready("demo")
        calls = [c[0] for c in self.engine._dispatcher._enqueue.call_args_list]
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
        result_path = self.pr / ".fenix" / ".fenix-run-result.json"
        result_path.write_text(json.dumps(_fast_result("verified")), encoding="utf-8")
        # write designed scenarios
        sp = self.pr / ".fenix" / "verify-progress" / "demo" / "test_scenarios.json"
        sp.write_text(
            json.dumps([{"id": "s1", "description": "d", "steps": [], "assertions": []}]),
            encoding="utf-8",
        )
        self.engine._read_implementer_result = MagicMock(return_value=_fast_result("verified"))
        self.engine._verification._implementer_zero_change = MagicMock(return_value=False)
        self.engine._verification._deliverable_gate_missing = MagicMock(return_value=[])
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
        self.engine._verification._implementer_zero_change = MagicMock(return_value=True)
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
        self.engine._verification._implementer_zero_change = MagicMock(return_value=False)
        self.engine._verification._deliverable_gate_missing = MagicMock(return_value=[])
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
        self.engine._verification._implementer_zero_change = MagicMock(return_value=False)
        self.engine._verification._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._dispatcher._enqueue = MagicMock()
        self.sm.transition("demo", "implementing")

        self.engine._run_fast_track_worker("demo")

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "implemented")
        # mode should be full
        self.assertEqual(read_spec_mode(self.pr, "demo"), "full")
        # verifier should be enqueued
        self.engine._dispatcher._enqueue.assert_called_with("demo", "verifier")


class TestFastTrackWorktreeReuse(_Base):
    """worktree 继承：打回保留、成功回收（runner 成功路径延迟清理由 dispatch 处置）。"""

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


class TestResultStatusNormalization(_Base):
    """status/verdict 混淆归一化 + 非法 status 处方（add-agent-prompt-files 事故）。

    agent 曾把 verification.verdict 的值写到顶层 status（status='verified' 且
    6 场景全 pass），语义成功的 run 被判失败整轮作废重派。
    """

    def _write_wt_result(self, status):
        wt = self.pr / "wt"
        wt.mkdir(parents=True, exist_ok=True)
        (wt / ".fenix-run-result.json").write_text(json.dumps(
            {"status": status, "spec": "demo", "mode": "fast-track",
             "verification": {"verdict": "verified", "scenarios": [], "bugs": []}}),
            encoding="utf-8")
        return wt

    def test_verified_status_normalized_to_success(self):
        self._mk()
        wt = self._write_wt_result("verified")
        self.engine._find_implementer_worktree = MagicMock(return_value=wt)
        ft = self.engine._read_implementer_result("demo")
        self.assertIsNotNone(ft)
        self.assertEqual(ft["status"], "success")

    def test_bug_found_status_normalized_to_success(self):
        self._mk()
        wt = self._write_wt_result("bug-found")
        self.engine._find_implementer_worktree = MagicMock(return_value=wt)
        ft = self.engine._read_implementer_result("demo")
        self.assertEqual(ft["status"], "success")

    def test_other_invalid_status_not_normalized(self):
        # 非 verdict 值域的非法 status 不归一化（仍走失败分支 + 处方）
        self._mk()
        wt = self._write_wt_result("completed")
        self.engine._find_implementer_worktree = MagicMock(return_value=wt)
        ft = self.engine._read_implementer_result("demo")
        self.assertEqual(ft["status"], "completed")

    def test_invalid_status_error_carries_prescription(self):
        self._mk()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0, branch="fenix/demo-1",
        )
        self.engine._read_implementer_result = MagicMock(return_value={
            "status": "completed", "spec": "demo"})
        self.sm.transition("demo", "implementing")

        self.engine._run_fast_track_worker("demo")

        entry = self.sm.read_one("demo")
        self.assertIn("status='completed'", entry["error"])
        self.assertIn("'success'", entry["error"])
        self.assertIn("重写", entry["error"])


class TestFastTrackMissingResultMerge(_Base):
    """fix-fasttrack-resultfile-missing-redispatch D2：结果文件缺失但分支
    已有提交 → merge + 升级补验证（不豁免预算、不 reset ready）。

    覆盖 proposal 两起事故签名：add-turn-limit-anchor-c run1 /
    add-main-tree-deps-provision run1，均已全量提交仍判死亡重派。
    """

    def _mk_in_implementing(self):
        self._mk()
        self.sm.transition("demo", "implementing")

    def test_missing_result_branch_has_commits_merges_and_escalates(self):
        """D2 分流：分支有提交 + 结果文件缺失 → merge 完成、mode→full、
        enqueue verifier（不豁免预算、不 reset ready、error 记原因）。"""
        self._mk_in_implementing()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0,
            branch="fenix/demo-1",
        )
        # 结果文件缺失
        self.engine._read_implementer_result = MagicMock(return_value=None)
        # 分支有提交（helper）
        self.engine._verification._implementation_branch_has_commits = MagicMock(return_value=True)
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()
        self.engine._dispatcher._enqueue = MagicMock()

        self.engine._run_fast_track_worker("demo")

        # merge 被调用（通过 merge_back_from_branch）
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.assert_called_once_with("fenix/demo-1")
        # spec 转 implemented（merge 成功）
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "implemented")
        # mode 改写为 full
        self.assertEqual(read_spec_mode(self.pr, "demo"), "full")
        # verifier 被 enqueue（补验证）
        self.engine._dispatcher._enqueue.assert_called_once_with("demo", "verifier")
        # error 记原因
        self.assertIn("结果文件缺失", entry.get("error", ""))
        self.assertIn("分支已提交", entry.get("error", ""))
        self.assertIn("升级补验证", entry.get("error", ""))
        # 不豁免预算、不 reset ready（._exempt_dead_run_budget 不被调用）
        self.assertFalse(hasattr(self.engine, "_exempt_mock_called"))
        # （_handle_fast_track_failure 不被调用 → 不会调 _exempt_dead_run_budget）

    def test_missing_result_zero_commits_keeps_death_path(self):
        """D2 零提交分支/无 branch：走既有死亡豁免 + reset ready + 重派（不变）。"""
        self._mk_in_implementing()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0,
            branch="fenix/demo-1",
        )
        self.engine._read_implementer_result = MagicMock(return_value=None)
        # 分支零提交
        self.engine._verification._implementation_branch_has_commits = MagicMock(return_value=False)
        # mock budget exemption 用于断言死亡豁免
        self.engine._exempt_dead_run_budget = MagicMock()
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._dispatcher._enqueue = MagicMock()

        self.engine._run_fast_track_worker("demo")

        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        # 死亡豁免预算被调用
        self.engine._exempt_dead_run_budget.assert_called_once()
        self.assertIn("fast-track no run-result", self.engine._exempt_dead_run_budget.call_args[0][1])
        # retry 1 < max(3)：不直接 enqueue，spec 回 ready 由 ready 派发器重派
        self.engine._dispatcher._enqueue.assert_not_called()

    def test_missing_result_merge_failure_preserves_worktree(self):
        """merge 失败 → _reconcile_and_merge 内部处置（保留 worktree + 重派），
        不走升级。"""
        self._mk_in_implementing()
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0,
            worktree_path=Path("/tmp/wt-demo"),
            branch="fenix/demo-1",
        )
        self.engine._read_implementer_result = MagicMock(return_value=None)
        self.engine._verification._implementation_branch_has_commits = MagicMock(return_value=True)
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._dispatcher._enqueue = MagicMock()
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = (False, "conflict")
        wm.last_stash_pop_conflicts = []

        self.engine._run_fast_track_worker("demo")

        wm.keep_for_reuse.assert_called_once()
        entry = self.sm.read_one("demo")
        self.assertIn("Merge-back failed", entry["error"])
        # 不走升级（mode 仍为 fast-track）
        self.assertEqual(read_spec_mode(self.pr, "demo"), "fast-track")
        self.engine._dispatcher._enqueue.assert_not_called()


class TestAccidentSignatureReplay(_Base):
    """fix-fasttrack-resultfile-missing-redispatch 4.2：日志夹具回放。

    对齐 proposal 两起事故签名（真实 git 仓库 + 真实 rev-list 判定，不 mock
    helper）：实现分支已有提交但结果文件缺失 → 走 merge + 升级补验证而非
    death 豁免（add-turn-limit-anchor-c run1 / add-main-tree-deps-provision
    run1：均已全量提交仍被当「run 死亡」discard 后从零重派）。
    """

    def setUp(self):
        import subprocess as _sp
        self._sp = _sp
        super().setUp()

        def git(*a):
            r = _sp.run(["git", "-C", str(self.pr), *a],
                        capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            return r.stdout
        self.git = git
        git("init", "-q", "-b", "main")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (self.pr / "f.txt").write_text("x", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "init")
        git("branch", "fenix/demo")

    def _commit_like_accident(self, n=5):
        """模拟 add-main-tree-deps-provision run1：分支全量提交 5 个 commit。"""
        git = self.git
        git("checkout", "-q", "fenix/demo")
        for i in range(n):
            (self.pr / "work.txt").write_text(f"impl {i}", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", f"[fenix] impl {i}")
        git("checkout", "-q", "main")

    def test_committed_branch_missing_result_merges_and_escalates(self):
        """夹具回放：分支 5 提交 + 结果文件缺失 → 真实 rev-list 判 True →
        走 merge + mode→full + enqueue verifier，不豁免预算、不 reset ready。"""
        # 先落分支提交再建 spec/STATE（git checkout 会清掉未跟踪的 spec 文件与
        # .fenix/STATE.md，必须先 commit 分支再建状态文件）
        self._commit_like_accident(5)
        self._mk()
        self.sm.transition("demo", "implementing")

        # 真实 rev-list 判定（不 mock helper）
        self.assertTrue(self.engine._implementation_branch_has_commits(
            AgentRunResult("r", "demo", "fast-track", True, 0.0,
                           branch="fenix/demo")))
        self.engine.agent_runner.run_fast_track.return_value = AgentRunResult(
            "impl-demo-1", "demo", "fast-track", True, 10.0,
            branch="fenix/demo",
        )
        # 结果文件缺失（事故签名）
        self.engine._read_implementer_result = MagicMock(return_value=None)
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()
        self.engine._dispatcher._enqueue = MagicMock()
        self.engine._exempt_dead_run_budget = MagicMock()

        self.engine._run_fast_track_worker("demo")

        entry = self.sm.read_one("demo")
        # 不是 death 豁免：预算不豁免、spec 不 reset ready
        self.engine._exempt_dead_run_budget.assert_not_called()
        self.assertEqual(entry["status"], "implemented")
        # 分支被 merge（merge_back_from_branch 被调用）
        self.engine.agent_runner.worktree_manager.merge_back_from_branch \
            .assert_called_once_with("fenix/demo")
        # 升级补验证：mode→full + verifier enqueue
        self.assertEqual(read_spec_mode(self.pr, "demo"), "full")
        self.engine._dispatcher._enqueue.assert_called_once_with("demo", "verifier")
        self.assertIn("结果文件缺失", entry.get("error", ""))


if __name__ == "__main__":
    unittest.main()
