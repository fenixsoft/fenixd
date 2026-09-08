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
