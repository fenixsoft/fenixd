"""pm_engine 两处调度故障的回归测试：

1) 卡在 verified 的 blocker 必须是 dict —— 此前 append 字符串，
   _write_blocker_report 取 b['spec'] 抛 TypeError（string indices must be integers），
   全量扫描中断、auto-recovery 永不执行。
2) push 分支解析 —— worktree 实现分支名带时间戳后缀且从未写回 STATE.md，
   回退名 fenix/<spec> 不存在导致 auto-push 全部失败（src refspec does not match any）。
"""

import shutil
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine


class TestVerifiedStuckBlocker(unittest.TestCase):
    """卡 verified 的 blocker 形状与恢复行为。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        # stuck 阈值由 agents.run_timeout_seconds 单源派生（config.py D1/D4，
        # 缺省回退 9600s=160min），旧键 schedule.stuck_threshold_minutes 已弃用
        # 不再生效——不配键即用缺省派生值。
        config = {}
        self.engine = PMEngine(self.sm, MagicMock(), config, self.project_root, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _spec_to_verified(self, name="s1"):
        from unittest.mock import MagicMock as MM
        # add_spec 内部会调 handle_event，避免真实派发逻辑干扰
        real_handle = self.engine.handle_event
        self.engine.handle_event = MM()
        try:
            self.sm.add_spec(name, {"priority": 5})
            self.sm.transition(name, "ready")
            self.sm.transition(name, "implementing")
            self.sm.transition(name, "implemented")
            self.sm.transition(name, "testing")
            self.sm.transition(name, "verified")
        finally:
            self.engine.handle_event = real_handle

    def test_blocker_entry_is_dict_not_string(self):
        self._spec_to_verified()
        result = self.engine.check_blockers()  # 修复前此处抛 TypeError
        b = result["blockers"][0]
        self.assertIsInstance(b, dict)
        self.assertEqual(b["spec"], "s1")
        self.assertEqual(b["status"], "verified")

    def test_verified_stuck_not_rolled_back_to_implemented(self):
        self._spec_to_verified()
        self.sm.update_spec("s1", {
            "error": "验证未完成：5/17",
            "_last_blocker_check_probe": True,
        })
        self.engine.check_blockers()
        entry = self.sm.read_one("s1")
        # 不能回滚到 implemented 触发整轮重跑验证（防 token 烧钱循环）
        self.assertEqual(entry["status"], "verified")
        self.assertEqual(entry["error"], "验证未完成：5/17")


class TestPushBranchResolution(unittest.TestCase):
    """push 分支解析：STATE branch 为空时从本地 refs 找回真实实现分支。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.repo / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        config = {}
        self.engine = PMEngine(self.sm, MagicMock(), config, self.repo, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _init_repo_with_impl_branches(self):
        def git(*args, env=None):
            return subprocess.run(["git", "-C", str(self.repo), *args],
                                  capture_output=True, text=True, check=True,
                                  env={**os.environ, **(env or {})})

        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (self.repo / "f.txt").write_text("a")
        git("add", "f.txt")
        git("commit", "-q", "-m", "base", env={"GIT_COMMITTER_DATE": "2026-08-26T00:00:00 +0000"})
        subprocess.run(["git", "-C", str(self.repo), "branch",
                        "fenix/spec-x-1787700000"], check=True)
        # 在第二个分支上追加一个更晚提交时间的 commit
        git("checkout", "-q", "-b", "fenix/spec-x-1787900000")
        (self.repo / "f.txt").write_text("b")
        git("add", "f.txt")
        git("commit", "-q", "-m", "newer", env={"GIT_COMMITTER_DATE": "2026-08-27T00:00:00 +0000"})

    def test_resolves_newest_timestamped_branch(self):
        self._init_repo_with_impl_branches()
        branch = self.engine._resolve_push_branch("spec-x", {"branch": None})
        self.assertEqual(branch, "fenix/spec-x-1787900000")

    def test_state_branch_takes_precedence(self):
        self._init_repo_with_impl_branches()
        branch = self.engine._resolve_push_branch("spec-x", {"branch": "manual/branch"})
        self.assertEqual(branch, "manual/branch")

    def test_fallback_plain_name_when_no_refs(self):
        branch = self.engine._resolve_push_branch("spec-y", {"branch": None})
        self.assertEqual(branch, "fenix/spec-y")


if __name__ == "__main__":
    unittest.main()


class TestStashPopConflictAlert(unittest.TestCase):
    """fix-mergeback-stashpop-silent-loss D1：pop 冲突自愈后 admin 告警直发。

    两个 spec scenario：
      1. 冲突自愈 → admin_alerts 出现 handled=false 的 stash_pop_conflict 记录
         且 description 含冲突文件清单
      2. pop 成功（无冲突）→ 不产生该记录
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.repo / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        config = {}
        self.engine = PMEngine(self.sm, MagicMock(), config, self.repo, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _alerts_path(self):
        from core.admin_store import AdminStore
        return AdminStore(self.repo, self.logger).alerts_path

    def test_conflict_self_heal_writes_unhandled_alert(self):
        """scenario 1: conflict_files 非空 → handled=false 的告警 + 文件清单。"""
        alerts_path = self._alerts_path()
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        # spec 存在（error 字段写入走真实 state machine）
        real_handle = self.engine.handle_event
        self.engine.handle_event = MagicMock()
        try:
            self.sm.add_spec("spec-x", {"priority": 5})
        finally:
            self.engine.handle_event = real_handle

        # worktree_manager 报告条目被 drop + sha（D2 去向状态）
        wm = MagicMock()
        wm.last_stash_entry_fate = {"kept": False, "sha": "abc123def4567890abcd"}
        self.engine.agent_runner.worktree_manager = wm

        merge_info = MagicMock()
        merge_info.wip_overlap = ["core/a.py"]

        self.engine._report_stash_pop_conflict(
            "spec-x", ["core/a.py", "core/b.py"], merge_info=merge_info)

        import json
        records = json.loads(alerts_path.read_text(encoding="utf-8"))
        hits = [r for r in records if r.get("signal_type") == "stash_pop_conflict"]
        self.assertEqual(len(hits), 1, f"应恰好一条告警: {records}")
        rec = hits[0]
        self.assertFalse(rec.get("handled"), "告警应未处理（handled=false）")
        self.assertEqual(rec.get("spec"), "spec-x")
        self.assertEqual(rec.get("severity"), "major")
        desc = rec.get("description", "")
        for fragment in ("spec-x", "core/a.py", "core/b.py",
                         "git show abc123def4567890abcd:core/a.py"):
            self.assertIn(fragment, desc, f"description 应含 {fragment!r}: {desc}")
        # wip_overlap 并入告警文本
        self.assertIn("core/a.py", desc)
        # spec.error 既有写入保持不变
        entry = self.sm.read_one("spec-x") or {}
        self.assertIn("stash pop conflict", entry.get("error", ""))

    def test_pop_success_produces_no_alert(self):
        """scenario 2: conflict_files 为空 → 不产生告警记录，error 不写。"""
        alerts_path = self._alerts_path()
        alerts_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine._report_stash_pop_conflict("spec-y", [])

        import json
        if alerts_path.exists():
            records = json.loads(alerts_path.read_text(encoding="utf-8"))
            hits = [r for r in records
                    if r.get("signal_type") == "stash_pop_conflict"]
            self.assertEqual(hits, [], "无冲突不应产生告警")
        entry = self.sm.read_one("spec-y") or {}
        self.assertIsNone(entry.get("error"), "conflict_files 为空不应写 error")

    def test_alert_included_in_stored_signal_types(self):
        """新信号类型被 monitor 白名单收录（scenario: 新信号类型被 monitor 收录）。"""
        from core.admin_monitor import SIGNAL_SEVERITY, STORED_SIGNAL_TYPES
        self.assertIn("stash_pop_conflict", STORED_SIGNAL_TYPES)
        self.assertEqual(SIGNAL_SEVERITY.get("stash_pop_conflict"), "major")


class TestMergebackWipOverlapAlert(unittest.TestCase):
    """evo-merge-back-wip-overlap-gate D3：阻塞路径旁路熔断 + 告警直发。

    三个 spec scenario：
      1. wip_gate_blocked=True → admin_alerts 出现 handled=false 的
         mergeback_wip_overlap 记录（description 含重叠清单与找回命令），
         且 _merge_streak 未累计、spec 未被 transition("blocked")
      2. 连续两次阻塞亦然（第二次同样不记账、不冻结）
      3. signal_type 被 admin_monitor 白名单收录 + severity major
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)
        self.logger = MagicMock()
        (self.repo / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = self.repo / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        config = {}
        self.engine = PMEngine(self.sm, MagicMock(), config, self.repo, self.logger)
        # mock worktree manager：merge_back_from_branch 返回 WIP 重叠闸门阻塞
        wm = MagicMock()
        wm.ensure_spec_committed.return_value = True
        wm.last_stash_pop_conflicts = []
        wm.has_active_worktree.return_value = False
        wm.find_implementer_worktree.return_value = None
        wm.consume_legacy = MagicMock()
        self.engine.agent_runner.worktree_manager = wm
        # mock worker 依赖
        self.engine._verification._implementer_zero_change = MagicMock(return_value=False)
        self.engine._verification._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._tasks_md_relint_from_branch = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._write_impl_result_snapshot = MagicMock()
        self.engine._cleanup_shared_result_file = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()
        self.engine._record_impl_diagnosis = MagicMock()
        self.engine._note_unattainable_todos = MagicMock()
        self.engine._process_queue = MagicMock()
        self.engine.handle_event = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _alerts_path(self):
        from core.admin_store import AdminStore
        return AdminStore(self.repo, self.logger).alerts_path

    def _mk(self, name="blocked-spec"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")

    def _stub_blocked_merge(self, overlap=("core/a.py",)):
        from core.worktree_manager.types import MergeConflictInfo
        wm = self.engine.agent_runner.worktree_manager
        wm.merge_back_from_branch.return_value = MergeConflictInfo(
            False,
            "Merge-back blocked by WIP overlap gate (policy=block): 1 main-tree "
            "tracked file(s) with uncommitted changes overlap branch changes: "
            "['core/a.py']",
            wip_overlap=list(overlap),
            wip_gate_blocked=True,
        )

    def _run_implementer_merge_attempt(self, spec_name="blocked-spec",
                                       branch="fenix/blocked-spec-1"):
        """模拟一次 implementer run 走到 merge-back（被闸门阻塞）。"""
        result = SimpleNamespace(
            success=True, error=None, run_id="impl-blocked-1", branch=branch,
            worktree_dirty=[], cancelled=False, worktree_path=None,
        )
        self.engine.agent_runner.run_implementer = MagicMock(return_value=result)
        self.engine._read_implementer_result = MagicMock(return_value={
            "status": "success", "spec": spec_name,
        })
        self.engine._run_agent_worker(spec_name, "implementer", 5)

    def test_blocked_merge_writes_unhandled_alert_and_skips_breaker(self):
        """scenario 1: 阻塞 → handled=false 告警 + _merge_streak 未累计 + 不 blocked。"""
        self._mk()
        self._stub_blocked_merge()

        self._run_implementer_merge_attempt()

        # admin_alerts 出现 handled=false 的 mergeback_wip_overlap 记录
        import json
        records = json.loads(self._alerts_path().read_text(encoding="utf-8"))
        hits = [r for r in records if r.get("signal_type") == "mergeback_wip_overlap"]
        self.assertEqual(len(hits), 1, f"应恰好一条告警: {records}")
        rec = hits[0]
        self.assertFalse(rec.get("handled"), "告警应未处理（handled=false）")
        self.assertEqual(rec.get("spec"), "blocked-spec")
        self.assertEqual(rec.get("severity"), "major")
        desc = rec.get("description", "")
        for fragment in ("blocked-spec", "core/a.py", "git show", "git stash list",
                         "提交（git add/commit）或 stash"):
            self.assertIn(fragment, desc, f"description 应含 {fragment!r}: {desc}")
        # evidence 已序列化为 str（dict 穿透 str.replace 会致 Administrator 唤起失败）
        ev = rec.get("evidence")
        self.assertIsInstance(ev, str, f"evidence 应为 str: {ev!r}")
        self.assertIn("core/a.py", ev)

        # spec 保持 in-flight：未被 transition("blocked")、未降级 ready
        entry = self.sm.read_one("blocked-spec") or {}
        self.assertEqual(entry.get("status"), "implementing",
                         f"阻塞不应翻转状态机: {entry}")
        # _merge_fp/_merge_streak 未累计（旁路熔断记账：键不存在或为 None/0）
        self.assertNotIn("_merge_fp", entry, "旁路不应写入指纹")
        self.assertEqual(int(entry.get("_merge_streak", 0) or 0), 0,
                         "不应累计熔断连击")

    def test_repeated_block_never_counts_or_blocks(self):
        """scenario 2: 连续两次阻塞 → _merge_streak 恒 0、spec 保持 in-flight。"""
        self._mk()
        self._stub_blocked_merge()

        self._run_implementer_merge_attempt()
        # 模拟人工处置后重新放行（ready → implementing 重派）
        self.sm.transition("blocked-spec", "ready")
        self.sm.transition("blocked-spec", "implementing")
        self._run_implementer_merge_attempt()

        entry = self.sm.read_one("blocked-spec") or {}
        self.assertEqual(entry.get("status"), "implementing",
                         f"连续阻塞后 spec 仍应 in-flight: {entry}")
        self.assertEqual(int(entry.get("_merge_streak", 0) or 0), 0,
                         "连续阻塞 MUST NOT 累计 _merge_streak（不入熔断）")
        self.assertIsNone(entry.get("_merge_fp"))

    def test_signal_type_whitelisted(self):
        """scenario 3: signal_type 被 admin_monitor 白名单收录 + severity major。"""
        from core.admin_monitor import SIGNAL_RECOMMENDATION, SIGNAL_SEVERITY, STORED_SIGNAL_TYPES
        self.assertIn("mergeback_wip_overlap", STORED_SIGNAL_TYPES,
                      "未收录则摄取循环跳过、记录石沉大海")
        self.assertEqual(SIGNAL_SEVERITY.get("mergeback_wip_overlap"), "major")
        self.assertTrue(SIGNAL_RECOMMENDATION.get("mergeback_wip_overlap"),
                        "应有核对指引")
