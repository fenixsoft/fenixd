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
        self.state_path = self.project_root / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        config = {"schedule": {"stuck_threshold_minutes": 60}}
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
        self.state_path = self.repo / "STATE.md"
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
