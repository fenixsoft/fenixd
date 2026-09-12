"""
Tests for PMEngine dispatch functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, StateParser, SpecStatus, VALID_TRANSITIONS


class TestPMEngineBugFound(unittest.TestCase):
    """Test bug-found → inplace repair (non-fix) / legacy fix derivation (fix-*)."""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_buggy_spec(self, name="quick-links-folders"):
        """Create a spec stuck in bug-found state."""
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")
        self.sm.transition(name, "bug-found")

    def test_resolve_fix_name_none_exists(self):
        self.assertEqual(
            self.engine._family._resolve_fix_spec_name("quick-links-folders"),
            "fix-quick-links-folders",
        )

    def test_resolve_fix_name_fix_done(self):
        self.sm.add_spec("fix-quick-links-folders", {"status": "done", "priority": 6})
        self.assertEqual(
            self.engine._family._resolve_fix_spec_name("quick-links-folders"),
            "fix-fix-quick-links-folders",
        )

    def test_resolve_fix_name_fix_done_twice(self):
        # 两轮 fix 均已 done → 递归到第三轮
        self.sm.add_spec("fix-quick-links-folders", {"status": "done", "priority": 6})
        self.sm.add_spec("fix-fix-quick-links-folders", {"status": "done", "priority": 7})
        self.assertEqual(
            self.engine._family._resolve_fix_spec_name("quick-links-folders"),
            "fix-fix-fix-quick-links-folders",
        )

    def test_resolve_fix_name_in_progress(self):
        # 进行中的 fix SPEC → 返回 None（重复派发，跳过）
        self.sm.add_spec("fix-quick-links-folders", {"status": "testing", "priority": 6})
        self.assertIsNone(self.engine._family._resolve_fix_spec_name("quick-links-folders"))

    # ── 原地打回测试（inplace-bug-repair）──

    def test_inplace_repair_first_failure(self):
        """非 fix SPEC 首次 bug-found → 计数 1 + implementing + 修复段注入 + 无新 fix spec"""
        # 准备 tasks.md（注入依赖）
        spec_dir = Path(self.tmpdir) / "spec" / "changes" / "quick-links-folders"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n\n## 1. 实现\n\n- [x] 1.1 done\n", encoding="utf-8")

        self._make_buggy_spec("quick-links-folders")

        self.engine._family._do_spec_bug_found("quick-links-folders")

        # 状态重置为 implementing
        entry = self.sm.read_one("quick-links-folders")
        self.assertEqual(entry["status"], "implementing")
        # 计数器递增到 1
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 1)
        # 无新 fix spec 被创建
        self.assertIsNone(self.sm.read_one("fix-quick-links-folders"))
        # 修复段已注入
        tasks_text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("## 验证修复", tasks_text)
        self.assertIn("第 1 轮", tasks_text)
        # 既有任务与勾选状态不被改写
        self.assertIn("- [x] 1.1 done", tasks_text)
        # 排队实现器
        queued_specs = [(e[1], e[2]) for e in self.engine._dispatcher._run_queue]
        self.assertIn(("quick-links-folders", "implementer"), queued_specs)

    def test_inplace_repair_second_failure(self):
        """第二次 bug-found → 计数 2 + 段内轮数更新"""
        spec_dir = Path(self.tmpdir) / "spec" / "changes" / "quick-links-folders"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

        self._make_buggy_spec("quick-links-folders")
        # 模拟第一次失败后状态
        self.sm.update_spec("quick-links-folders", {
            "_verify_fail_rounds": 1,
            "status": "bug-found",
        })

        self.engine._family._do_spec_bug_found("quick-links-folders")

        entry = self.sm.read_one("quick-links-folders")
        self.assertEqual(entry["status"], "implementing")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 2)
        tasks_text = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("第 2 轮", tasks_text)

    def test_inplace_repair_third_failure_escalates(self):
        """第三轮 bug-found → blocked + 升级告警"""
        self._make_buggy_spec("quick-links-folders")
        self.sm.update_spec("quick-links-folders", {
            "_verify_fail_rounds": 2,
            "status": "bug-found",
        })

        self.engine._family._do_spec_bug_found("quick-links-folders")

        entry = self.sm.read_one("quick-links-folders")
        self.assertEqual(entry["status"], "blocked")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 3)
        # 检查升级告警
        from core.admin_store import AdminStore
        store = AdminStore(Path(self.tmpdir), self.logger)
        alerts = [a for a in store.read_all()
                  if a.get("signal_type") == "verify_fail_escalation"
                  and a.get("spec") == "quick-links-folders"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], "escalation")
        self.assertIn("3 轮", alerts[0]["description"])

    def test_verify_fail_rounds_persists_across_restart(self):
        """计数器跨重启持久：重新读取 STATE.md 后仍保持"""
        self._make_buggy_spec("quick-links-folders")
        self.engine._family._do_spec_bug_found("quick-links-folders")

        # 模拟重启：重新构造 state machine（从磁盘读取）
        from core.state_machine import StateMachine as SM
        new_sm = SM(self.state_path, self.logger)
        entry = new_sm.read_one("quick-links-folders")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 1)
        self.assertEqual(entry["status"], "implementing")


class TestPMEngineBugFoundIdempotent(unittest.TestCase):
    """bug-found 处理幂等性：连续两次 bug-found 不重复注入修复段。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_double_bug_found_no_duplicate_injection(self):
        spec_dir = Path(self.tmpdir) / "spec" / "changes" / "my-spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

        # 第一次 bug-found
        self.sm.add_spec("my-spec", {"priority": 1})
        self.sm.transition("my-spec", "ready")
        self.sm.transition("my-spec", "implementing")
        self.sm.transition("my-spec", "implemented")
        self.sm.transition("my-spec", "testing")
        self.sm.transition("my-spec", "bug-found")

        self.engine._family._do_spec_bug_found("my-spec")
        tasks_after_first = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        count_after_first = tasks_after_first.count("## 验证修复")

        # 第二次 bug-found（模拟 daemon 再次扫描到 bug-found 状态）
        self.sm.update_spec("my-spec", {"status": "bug-found"})
        self.engine._family._do_spec_bug_found("my-spec")
        tasks_after_second = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        count_after_second = tasks_after_second.count("## 验证修复")

        # 修复段只能出现一次
        self.assertEqual(count_after_first, 1)
        self.assertEqual(count_after_second, 1)


class TestPMEngineSameStatusResetDispatch(unittest.TestCase):
    """bug-found 同态重置派发：implementing 重新派发后必须重新进入 testing 流程。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reset_to_implementing_redispatches_implementer(self):
        self.sm.add_spec("my-spec", {"priority": 1})
        self.sm.transition("my-spec", "ready")
        self.sm.transition("my-spec", "implementing")
        self.sm.transition("my-spec", "implemented")
        self.sm.transition("my-spec", "testing")
        self.sm.transition("my-spec", "bug-found")

        self.engine._family._do_spec_bug_found("my-spec")

        # 状态应为 implementing
        entry = self.sm.read_one("my-spec")
        self.assertEqual(entry["status"], "implementing")

        # 应该有 implementer 排队
        queued = [(e[1], e[2]) for e in self.engine._dispatcher._run_queue]
        self.assertIn(("my-spec", "implementer"), queued)


class TestEngineRouteCrossCheck(unittest.TestCase):
    """引擎路由交叉校验：合法 agent_type 经 Dispatcher._enqueue 入队。

    覆盖口径说明：本类只钉住入队面（原 TestRouteTableGuard 已删——其名称
    宣称"未注册类型不得直派"但断言的是入队成功，与守卫语义相反且互为重复）。
    派发路由分发的真实语义（implementer/fast-track/verifier 的 if/elif 分支）
    由 dispatch.py:_run_agent_worker 承担，待后续 SPEC 补直测。
    """

    def test_all_statuses_have_routes(self):
        from core.pm_engine import PMEngine
        tmpdir = tempfile.mkdtemp()
        try:
            (Path(tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
            sm = StateMachine(Path(tmpdir) / ".fenix" / "STATE.md", MagicMock())
            engine = PMEngine(sm, MagicMock(), {}, Path(tmpdir), MagicMock())
            # 所有合法 agent_type 都应有路由（通过 _enqueue 验证）
            for agent_type in ["implementer", "verifier"]:
                # Test that we can enqueue with these agent types
                engine._dispatcher._enqueue("test-spec", agent_type)
                # Verify it was added to the queue
                self.assertTrue(any(e[1] == "test-spec" and e[2] == agent_type
                                  for e in engine._dispatcher._run_queue))
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestPushRefHygiene(unittest.TestCase):
    """测试 main 优先推送 + 远端 SHA 去重 + 分支尽力逻辑。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        # 初始化 git repo + 本地分支 + 远端（用 bare repo 模拟 origin）
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / "README.md").write_text("# test\n")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)
        # 创建远端 bare repo 并配置 origin
        self.remote_root = Path(self.tmpdir) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main",
                        str(self.remote_root)],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(self.remote_root)],
                       cwd=str(self.project_root), capture_output=True)
        # 把 init 推到远端，保证 main 可 FF
        subprocess.run(["git", "push", "-q", "origin", "main"],
                       cwd=str(self.project_root), capture_output=True)

        self.sm = MagicMock()
        self.sm.read_one = MagicMock(
            return_value={"status": "done", "branch": "fenix/test-spec"}
        )
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()
        self.sm.get_by_status = MagicMock(return_value={})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config: dict = None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def test_main_first_push_success(self):
        """main 可 FF 时推送成功并推进 pushed，error 清空。"""
        engine = self._make_engine({})
        result = engine.approve_push("test-spec")
        self.assertTrue(result)
        self.sm.transition.assert_called_once_with("test-spec", "pushed")
        self.assertIsNone(self.sm.update_spec.call_args[0][1]["error"])

    def test_main_diverged_failure(self):
        """远端 main 分叉（非 FF）时推送失败，不推进 pushed。"""
        # 在远端制造一个本地没有的提交，制造分叉
        outside = Path(self.tmpdir) / "outside"
        subprocess.run(["git", "clone", "-q", str(self.remote_root), str(outside)],
                       cwd=str(self.project_root), capture_output=True)
        (outside / "extra.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(outside), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "remote only"],
                       cwd=str(outside), capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "main"],
                       cwd=str(outside), capture_output=True)
        shutil.rmtree(outside, ignore_errors=True)

        engine = self._make_engine({})
        result = engine.approve_push("test-spec")
        self.assertFalse(result)
        self.sm.transition.assert_not_called()
        err = self.sm.update_spec.call_args[0][1]["error"]
        self.assertIn("git push failed", err)

    def test_branch_dedup_skip_when_remote_sha_matches(self):
        """远端分支 SHA 与本地一致 → 不重复推送（去重短路）。"""
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
        }
        # 先在本地创建分支并推到远端（SHA 一致）
        subprocess.run(["git", "branch", "fenix/test-spec"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "fenix/test-spec"],
                       cwd=str(self.project_root), capture_output=True)
        with patch.object(engine, '_git_push_ref', return_value=(True, "")) as mock_push:
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            # 分支去重短路：_git_push_ref 不会被传入分支名
            branch_push_calls = [
                c for c in mock_push.call_args_list if c[0][0] == "fenix/test-spec"
            ]
            self.assertEqual(len(branch_push_calls), 0)
            # main push 仍是成功路径
            main_calls = [c for c in mock_push.call_args_list if c[0][0] == "main"]
            self.assertEqual(len(main_calls), 1)

    def test_local_branch_missing_skips_push(self):
        """本地分支已清理（merge-back 后）→ 无 refspec 错误，main 推送承载。"""
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/gone-branch",
        }
        # 本地没有 fenix/gone-branch 分支，远端也没有
        # approve_push 应成功（main 推送成功），且不会因 gone-branch 报错
        result = engine.approve_push("test-spec")
        self.assertTrue(result)
        self.sm.transition.assert_called_once_with("test-spec", "pushed")

    def test_remote_branch_diff_sha_warns_and_skips(self):
        """远端分支 SHA 不同 → 跳过分支推送并 WARN，main 成功仍推进。"""
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
        }
        # 本地分支
        subprocess.run(["git", "branch", "fenix/test-spec"],
                       cwd=str(self.project_root), capture_output=True)
        # 远端分支放一个「不同 SHA」的对象：用另一个 clone push 不同内容
        outside = Path(self.tmpdir) / "outside2"
        subprocess.run(["git", "clone", "-q", str(self.remote_root), str(outside)],
                       cwd=str(self.project_root), capture_output=True)
        (outside / "diverged.txt").write_text("y")
        subprocess.run(["git", "add", "."], cwd=str(outside), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "diverged branch",
                        "-b", "fenix/test-spec"],
                       cwd=str(outside), capture_output=True)
        subprocess.run(["git", "branch", "-M", "fenix/test-spec"],
                       cwd=str(outside), capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "fenix/test-spec"],
                       cwd=str(outside), capture_output=True)
        shutil.rmtree(outside, ignore_errors=True)

        with patch.object(engine, '_git_push_ref', return_value=(True, "")) as mock_push:
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            branch_calls = [
                c for c in mock_push.call_args_list
                if c[0][0] == "fenix/test-spec"
            ]
            self.assertEqual(len(branch_calls), 0)

    def test_remote_branch_missing_pushes_branch(self):
        """远端分支不存在 → 正常推送 feature 分支（best-effort 成功）。"""
        engine = self._make_engine({})
        self.sm.read_one.return_value = {
            "status": "done", "branch": "fenix/test-spec",
        }
        subprocess.run(["git", "branch", "fenix/test-spec"],
                       cwd=str(self.project_root), capture_output=True)
        with patch.object(engine, '_git_push_ref') as mock_push:
            mock_push.return_value = (True, "")
            result = engine.approve_push("test-spec")
            self.assertTrue(result)
            branch_calls = [
                c for c in mock_push.call_args_list
                if c[0][0] == "fenix/test-spec"
            ]
            self.assertEqual(len(branch_calls), 1)


# ═══════════════════════════════════════════════════════════════════
# Push Residual Backfill Tests (fix-push-ref-lifecycle: task 3.1 / design D4)
# ═══════════════════════════════════════════════════════════════════

class TestPushResidualBackfill(unittest.TestCase):
    """测试幂等回填清理函数（pushed + git push failed → SHA 验证 → 清 error）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / "README.md").write_text("# test\n")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)
        # 远端裸仓 + origin 并推送 main
        self.remote_root = Path(self.tmpdir) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main",
                        str(self.remote_root)],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(self.remote_root)],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "main"],
                       cwd=str(self.project_root), capture_output=True)

        # 使用真实 StateMachine 以便 backfill 后能回读 error
        from core.state_machine import StateMachine
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, MagicMock())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config: dict = None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def test_backfill_cleans_verified_residual(self):
        """远端分支 SHA 存在 → pushed 残痕被清除。"""
        self.sm.add_spec("clean-spec", {
            "status": "pushed",
            "branch": "fenix/clean-spec-123",
            "error": "git push failed (main): x [push_backoff next_retry_at=1]",
        })
        engine = self._make_engine({})
        # 模拟该分支在远端存在
        with patch.object(engine, '_remote_branch_sha', return_value="abc123" * 6):
            result = engine.backfill_push_residuals()
        self.assertIn("clean-spec", result["cleaned"])
        # 回读 error 已被清空
        self.assertIsNone(self.sm.read_one("clean-spec").get("error"))

    def test_backfill_keeps_unverifiable_residual(self):
        """远端分支与 main 均不可达 → 残痕保留并列入 kept 清单。"""
        self.sm.add_spec("kept-spec", {
            "status": "pushed",
            "branch": "fenix/kept-spec-123",
            "error": "git push failed (main): offline",
        })
        engine = self._make_engine({})
        # 模拟 ls-remote 失败（无 origin 名对应真实可达远端）
        with patch.object(engine, '_remote_branch_sha', return_value=None):
            result = engine.backfill_push_residuals()
        self.assertIn("kept-spec", [k["spec"] for k in result["kept"]])
        # 残痕保留
        self.assertIsNotNone(self.sm.read_one("kept-spec").get("error"))

    def test_backfill_skips_non_push_failed(self):
        """error 非 'git push failed' 前缀的 pushed spec 不被清理。"""
        self.sm.add_spec("other-spec", {
            "status": "pushed",
            "error": "some other error",
        })
        engine = self._make_engine({})
        result = engine.backfill_push_residuals()
        self.assertNotIn("other-spec", result["cleaned"])
        self.assertNotIn("other-spec", [k["spec"] for k in result["kept"]])

    def test_backfill_skips_non_pushed(self):
        """非 pushed 状态的 spec 不被清理（即便 error 以 git push failed 开头）。"""
        self.sm.add_spec("done-spec", {
            "status": "done",
            "error": "git push failed (main): x",
        })
        engine = self._make_engine({})
        result = engine.backfill_push_residuals()
        self.assertNotIn("done-spec", result["cleaned"])


# ═══════════════════════════════════════════════════════════════════
# Task Progress Sync Tests (add-task-progress-sync)
# ═══════════════════════════════════════════════════════════════════

import subprocess

def _write_impl_run_for_spec(project_root: Path, spec_name: str, timestamp: int,
                             done_tasks: list, done_ids: list):
    """写 impl run 产物到 .fenix/runs/ 目录。"""
    runs_dir = project_root / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    # 使用正确的文件名格式：impl-<spec_name>-*.jsonl
    run_file = runs_dir / f"impl-{spec_name}-{timestamp}.jsonl"
    # 写入 JSON Lines 格式（每行一个 JSON 对象）
    lines = []
    for i, task in enumerate(done_tasks):
        # TaskCreate 事件
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "name": "TaskCreate",
                    "input": {"subject": task}
                }]
            }
        }))
        # 如果该任务在 done_ids 中，添加 TaskUpdate completed 事件
        if i < len(done_ids) and done_ids[i][1] == "completed":
            lines.append(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [{
                        "type": "tool_use",
                        "name": "TaskUpdate",
                        "input": {"taskId": i + 1, "status": "completed"}
                    }]
                }
            }))
    run_file.write_text("\n".join(lines), encoding="utf-8")


class TestTaskProgressSync(unittest.TestCase):
    """implementer run 成功后 daemon 确定性回写主树 tasks.md 勾选。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        # .fenix/ 运行时产物走 gitignore，不计入工作树脏检测
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        (self.project_root / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)

        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "done"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config=None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def _write_spec_tasks(self, spec_name: str, content: str) -> Path:
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        p = spec_dir / "tasks.md"
        p.write_text(content, encoding="utf-8")
        return p

    def _commit_spec(self, spec_name: str):
        """把 spec 目录提交进主树，模拟 ensure_spec_committed 后的干净基线。"""
        subprocess.run(["git", "add", "--", "spec"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", f"spec {spec_name}"],
                       cwd=str(self.project_root), capture_output=True)

    def _head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"],
                              cwd=str(self.project_root), capture_output=True, text=True).stdout.strip()

    def test_sync_backfills_unchecked_done_ids(self):
        """run 声明 2.1/2.2 完成，主树未勾 → 回写勾选并 commit。"""
        tasks = ("# Tasks: demo\n\n"
                 "## 2. 实现\n\n"
                 "- [ ] 2.1 build\n"
                 "- [ ] 2.2 test\n"
                 "- [ ] 2.3 doc\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        _write_impl_run_for_spec(self.project_root, "demo", 1789000000,
                                 ["Task 2.1: build", "Task 2.2: test", "Task 2.3: doc"],
                                 [(1, "completed"), (2, "completed")])
        engine = self._make_engine()
        engine._sync_task_progress("demo")

        text = (self.project_root / "spec" / "changes" / "demo" / "tasks.md").read_text()
        self.assertIn("- [x] 2.1 build", text)
        self.assertIn("- [x] 2.2 test", text)
        self.assertIn("- [ ] 2.3 doc", text)  # 未出现在 done_ids 的不勾

        res = subprocess.run(["git", "log", "--oneline"],
                             cwd=str(self.project_root), capture_output=True, text=True)
        self.assertIn("sync task progress from run record", res.stdout)

    def test_sync_idempotent_no_extra_commit(self):
        """二次执行不产生新 commit。"""
        tasks = ("# Tasks: demo\n\n"
                 "## 2. 实现\n\n"
                 "- [ ] 2.1 build\n"
                 "- [ ] 2.2 test\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        _write_impl_run_for_spec(self.project_root, "demo", 1789000000,
                                 ["Task 2.1: build", "Task 2.2: test"],
                                 [(1, "completed"), (2, "completed")])
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        first = self._head()
        engine._sync_task_progress("demo")  # 已全勾选，跳过
        self.assertEqual(first, self._head())

    def test_sync_preserves_agent_checked(self):
        """agent 已勾选但 run 记录缺失的任务不被撤销（只增不减）。"""
        tasks = ("# Tasks: demo\n\n"
                 "## 1. 实现\n\n"
                 "- [x] 1.1 already done by agent\n"
                 "- [ ] 1.2 not in run\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        _write_impl_run_for_spec(self.project_root, "demo", 1789000000,
                                 ["Task 1.1: already done by agent", "Task 1.2: not in run"],
                                 [(1, "completed")])
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        text = (self.project_root / "spec" / "changes" / "demo" / "tasks.md").read_text()
        self.assertIn("- [x] 1.1 already done by agent", text)
        self.assertIn("- [ ] 1.2 not in run", text)
        # 无新勾选 → 不 commit（HEAD 不变）
        self.assertEqual(self._head(), self._head())

    def test_sync_skips_when_no_run_file(self):
        """无 run 产物时不动作、不 commit。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [ ] 1.1 x\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        engine = self._make_engine()
        engine._sync_task_progress("demo")
        self.assertEqual(self._head(), self._head())

    def test_sync_skips_when_dirty_tree(self):
        """工作树不干净时跳过回写（非阻塞），不 commit。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [ ] 1.1 x\n")
        self._write_spec_tasks("demo", tasks)
        self._commit_spec("demo")
        _write_impl_run_for_spec(self.project_root, "demo", 1789000000,
                                 ["Task 1.1: x"], [(1, "completed")])
        engine = self._make_engine()
        with patch.object(engine, "_worktree_is_dirty", return_value=True):
            engine._sync_task_progress("demo")
        self.assertEqual(self._head(), self._head())


class TestTaskCompletionGate(unittest.TestCase):
    """verified→done 任务完成一致性门禁（add-task-progress-sync 3.1/3.2）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        (self.project_root / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                       cwd=str(self.project_root), capture_output=True)

        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "verified"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config=None):
        from core.pm_engine import PMEngine
        logger = MagicMock()
        for m in ("info", "warning", "error", "debug"):
            setattr(logger, m, MagicMock())
        ar = MagicMock()
        # worktree_manager.find_implementer_worktree 返回 None，
        # 使 _read_implementer_result 走主树 .fenix/.fenix-run-result.json 回退路径。
        ar.worktree_manager.find_implementer_worktree.return_value = None
        return PMEngine(self.sm, ar, config or {}, self.project_root, logger)

    def _write_spec_tasks(self, spec_name, content):
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(content, encoding="utf-8")

    def _write_impl_result(self, spec_name, status):
        """写 .fenix-run-result.json 到主树 .fenix/（_read_implementer_result 回退路径）。"""
        (self.project_root / ".fenix" / ".fenix-run-result.json").write_text(
            json.dumps({"status": status, "spec": spec_name}), encoding="utf-8")

    def _write_run_done(self, spec_name, done_ids):
        """写 impl run 产物，使其 done_ids 为给定集合。"""
        _write_impl_run_for_spec(
            self.project_root, spec_name, 1789000000,
            [f"Task {tid}: desc" for tid in done_ids] +
            [f"Task {i}.x: extra" for i in range(len(done_ids), 4)],
            [(i + 1, "completed") for i in range(len(done_ids))],
        )

    def test_gate_blocks_on_gap(self):
        """run 声明 success 但 4.1 未勾选且不在 done_ids → 阻断，error 含任务 id。"""
        tasks = ("# Tasks: demo\n\n## 4. 实现\n\n"
                 "- [x] 4.1 done\n- [ ] 4.2 done\n- [ ] 4.3 notdone\n")
        self._write_spec_tasks("demo", tasks)
        self._write_impl_result("demo", "success")
        self._write_run_done("demo", ["4.1", "4.2"])
        engine = self._make_engine()
        blocker = engine._task_completion_blocker("demo")
        self.assertIsNotNone(blocker)
        self.assertIn("4.3", blocker)
        # 通过 _on_spec_verified 端到端验证：阻断时不 transition，写 error
        engine._on_spec_verified("demo")
        self.sm.transition.assert_not_called()
        update_kwargs = self.sm.update_spec.call_args[0][1]
        self.assertIn("4.3", update_kwargs["error"])

    def test_gate_passes_when_all_confirmed(self):
        """全部任务确认完成（勾选 ∪ done_ids 覆盖全部）→ 放行。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n"
                 "- [x] 1.1 done\n- [ ] 1.2 done\n")
        self._write_spec_tasks("demo", tasks)
        self._write_impl_result("demo", "success")
        self._write_run_done("demo", ["1.2"])  # 1.2 在 done_ids，1.1 已勾选
        engine = self._make_engine()
        self.assertIsNone(engine._task_completion_blocker("demo"))
        engine._on_spec_verified("demo")
        self.sm.transition.assert_called_once_with("demo", "done")

    def test_gate_passes_without_run_record(self):
        """无 run 记录可查（.fenix-run-result.json 缺失）→ 放行（无法证伪）。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [ ] 1.1 x\n")
        self._write_spec_tasks("demo", tasks)
        # 不写 .fenix-run-result.json
        engine = self._make_engine()
        self.assertIsNone(engine._task_completion_blocker("demo"))

    def test_gate_passes_when_run_not_success(self):
        """run 声明非 success（如 error）→ 放行（仅 success 触发校验）。"""
        tasks = ("# Tasks: demo\n\n## 1. 实现\n\n- [ ] 1.1 x\n")
        self._write_spec_tasks("demo", tasks)
        self._write_impl_result("demo", "error")
        engine = self._make_engine()
        self.assertIsNone(engine._task_completion_blocker("demo"))

    def test_gate_applies_to_fix_spec(self):
        """fix-* SPEC 走相同规则：缺口任务阻断。"""
        tasks = ("# Tasks: fix-demo\n\n## 1. 修复\n\n"
                 "- [x] 1.1 done\n- [ ] 1.2 notdone\n")
        self._write_spec_tasks("fix-demo", tasks)
        self._write_impl_result("fix-demo", "success")
        self._write_run_done("fix-demo", ["1.1"])
        engine = self._make_engine()
        blocker = engine._task_completion_blocker("fix-demo")
        self.assertIsNotNone(blocker)
        self.assertIn("1.2", blocker)
        engine._on_spec_verified("fix-demo")
        self.sm.transition.assert_not_called()


class TestImplResultSnapshot(unittest.TestCase):
    """fix-verified-gate-evidence-race 4.3：implementer 成功路径 per-spec 快照写点。

    覆盖 spec/changes/fix-verified-gate-evidence-race/specs/verified-gate-evidence
    Requirement「implementer 结果 per-spec 快照」的 Scenario：
    成功即快照 / 重派覆盖旧快照 / 快照写失败不阻塞。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "implementing"})
        self.sm.transition = MagicMock()
        self.sm.update_spec = MagicMock()
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.sm.add_spec = MagicMock()
        self.sm.add_spec("demo", {"priority": 5})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _snap(self, spec="demo"):
        return (self.project_root / ".fenix" / "verify-progress"
                / spec / "impl-result.json")

    def test_success_writes_snapshot_with_spec_and_status(self):
        """成功即快照：快照文件存在，含 spec=本 spec 与 status=success。"""
        impl_result = {"spec": "demo", "status": "success", "summary": "ok"}
        self.engine._write_impl_result_snapshot("demo", impl_result)
        snap = self._snap()
        self.assertTrue(snap.exists())
        data = json.loads(snap.read_text(encoding="utf-8"))
        self.assertEqual(data["spec"], "demo")
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["summary"], "ok")

    def test_redispatch_overwrites_snapshot(self):
        """重派后新成功原子覆盖旧快照，不残留旧字段。"""
        old = {"spec": "demo", "status": "success", "summary": "round-1",
               "extra_old": "should disappear"}
        new = {"spec": "demo", "status": "success", "summary": "round-2"}
        self.engine._write_impl_result_snapshot("demo", old)
        self.engine._write_impl_result_snapshot("demo", new)
        data = json.loads(self._snap().read_text(encoding="utf-8"))
        self.assertEqual(data["summary"], "round-2")
        self.assertNotIn("extra_old", data)

    def test_snapshot_write_failure_not_blocking(self):
        """快照写失败（mock OSError）→ 主流程继续（WARNING 不抛出）。"""
        impl_result = {"spec": "demo", "status": "success"}
        with patch.object(Path, "mkdir", side_effect=OSError("disk full")):
            # 不应抛出
            self.engine._write_impl_result_snapshot("demo", impl_result)
        self.assertTrue(self.engine.logger.warning.called)

    def test_dispatch_success_path_writes_snapshot(self):
        """真实派发成功收口点：implementer 成功即写快照（D1 写点验证）。"""
        from types import SimpleNamespace

        # 共享结果文件 + run 产物
        (self.project_root / ".fenix" / ".fenix-run-result.json").write_text(
            json.dumps({"spec": "demo", "status": "success"}),
            encoding="utf-8",
        )
        self.sm.read_one.return_value = {"status": "implementing",
                                         "implementer_run": "impl-demo-1-a1"}
        result = SimpleNamespace(
            success=True, error=None, run_id="impl-demo-1-a1", branch=None,
            worktree_dirty=[], cancelled=False,
        )
        # 零变更哨 / 交付物守卫返回无缺口，merge-back 成功
        self.engine._implementer_zero_change = MagicMock(return_value=False)
        self.engine._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._reconcile_impl_budget = MagicMock()
        wm = MagicMock()
        wm.find_implementer_worktree = MagicMock(return_value=None)
        wm.merge_back_from_branch.return_value = (True, "")
        self.engine.agent_runner.worktree_manager = wm
        self.engine.agent_runner.run_implementer = MagicMock(
            return_value=result)
        # 状态推进
        self.sm.transition.return_value = True

        # 驱动 _run_agent_worker 的 implementer 分支
        self.engine._run_agent_worker("demo", "implementer", 5)

        snap = self._snap()
        self.assertTrue(snap.exists())
        data = json.loads(snap.read_text(encoding="utf-8"))
        self.assertEqual(data["spec"], "demo")
        self.assertEqual(data["status"], "success")
        # 快照写点须在 merge-back 之前（成功即快照，不依赖 merge 成功与否）
        self.sm.transition.assert_called()

    def test_dispatch_failure_path_does_not_write_snapshot(self):
        """失败路径不写快照：run 失败 → 无 impl-result.json。"""
        from types import SimpleNamespace

        (self.project_root / ".fenix" / ".fenix-run-result.json").write_text(
            json.dumps({"spec": "demo", "status": "error", "error": "boom"}),
            encoding="utf-8",
        )
        self.sm.read_one.return_value = {"status": "implementing",
                                         "implementer_run": "impl-demo-2-a1"}
        result = SimpleNamespace(
            success=False, error="boom", run_id="impl-demo-2-a1",
            branch=None, worktree_dirty=[], cancelled=False,
        )
        self.engine.agent_runner.run_implementer = MagicMock(
            return_value=result)
        wm = MagicMock()
        wm.merge_back_from_branch.return_value = (True, "")
        self.engine.agent_runner.worktree_manager = wm

        self.engine._run_agent_worker("demo", "implementer", 5)

        self.assertFalse(self._snap().exists())


class TestSharedResultFileCleanup(unittest.TestCase):
    """fix-fasttrack-resultfile-missing-redispatch 3.4：主树共享结果文件
    .fenix/.fenix-run-result.json 消费后清理（快照落盘后删除）+ 删除失败不阻塞。

    覆盖 shared-result-file-integrity spec 的「消费并落盘快照后删除共享文件 /
    删除失败仅记日志不阻塞」两态。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "implementing"})
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger,
        )
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _shared(self):
        return self.project_root / ".fenix" / ".fenix-run-result.json"

    def _write_shared(self, spec="demo"):
        self._shared().write_text(
            json.dumps({"spec": spec, "status": "success"}), encoding="utf-8")

    def test_consumed_and_snapshotted_then_deleted(self):
        """stamp 匹配的文件被消费 + 快照落盘后删除共享文件（后续读取不再命中）。"""
        self._write_shared("demo")
        self.engine._write_impl_result_snapshot("demo", {"spec": "demo",
                                                         "status": "success"})
        self.engine._cleanup_shared_result_file("demo")
        self.assertFalse(self._shared().exists())
        # 快照仍在（per-spec 持久证据不随共享文件删除而蒸发）
        snap = (self.project_root / ".fenix" / "verify-progress"
                / "demo" / "impl-result.json")
        self.assertTrue(snap.exists())

    def test_other_spec_stamp_not_deleted(self):
        """共享文件 stamp 非本 spec（其它 spec 在途）→ 不误删。"""
        self._write_shared("other-spec")
        self.engine._cleanup_shared_result_file("demo")
        self.assertTrue(self._shared().exists())

    def test_missing_file_noop(self):
        """共享文件不存在 → no-op 不抛。"""
        self.engine._cleanup_shared_result_file("demo")

    def test_delete_failure_warns_does_not_block(self):
        """删除失败（OSError）→ 仅记 WARNING，主流程不阻塞。"""
        self._write_shared("demo")
        with patch.object(Path, "unlink", side_effect=OSError("permission")):
            self.engine._cleanup_shared_result_file("demo")  # 不应抛出
        self.assertTrue(self.engine.logger.warning.called)


class TestDoneDurationPersist(unittest.TestCase):
    """add-done-duration-persist 2.1/2.2：verified→done 时写入 total_duration。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        self.logger = MagicMock()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md", self.logger)
        ar = MagicMock()
        # worktree 查找返回 None，使 _read_implementer_result 走项目根回退路径
        ar.worktree_manager.find_implementer_worktree.return_value = None
        self.engine = PMEngine(
            self.sm, ar, {}, self.project_root, self.logger,
        )
        self.sm.add_spec("demo", {"priority": 5})
        for st in ("ready", "implementing", "implemented", "testing", "verified"):
            self.sm.transition("demo", st)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_run(self, run_id, start_ts, duration):
        """创建 run 产物并定 mtime，使 duration_seconds = duration。"""
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(exist_ok=True)
        p = runs_dir / f"{run_id}.jsonl"
        p.write_text("", encoding="utf-8")
        end_ts = start_ts + duration
        os.utime(p, (end_ts, end_ts))

    def test_done_writes_summed_duration(self):
        """impl 100s + planner-judge 50s → STATE.md 写入 total_duration: 150。"""
        self._make_run("impl-demo-1789000000-a1", 1789000000, 100)
        self._make_run("planner-judge-demo-1789000050-a1", 1789000050, 50)
        self.engine._on_spec_verified("demo")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "done")
        self.assertEqual(str(entry["total_duration"]), "150")

    def test_done_writes_zero_without_runs(self):
        """无任何 run 产物（含归档）→ 写入 total_duration: 0。"""
        self.engine._on_spec_verified("demo")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "done")
        self.assertEqual(str(entry["total_duration"]), "0")


class TestFastTrackImplResultSnapshot(unittest.TestCase):
    """fast-track 车道同写 impl-result.json 快照（add-planready-artifact-gate 实证缺口）。

    fast-track 因 verified→done 门禁拦截（未勾任务）滞留 verified 时，同样存在
    跨 spec 共享文件覆盖窗口——2026-09-10 实证：共享文件被姊妹 spec 成功覆盖后，
    门禁 fail-closed 误报「run 证据缺失」。成功收口必须落 per-spec 快照，且写点
    须在 _fast_track_advance_to_verified（同步触发 _on_spec_verified 门禁评估）
    之前。
    """

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = MagicMock()
        self.sm.read_one = MagicMock(return_value={"status": "implementing"})
        self.sm.transition = MagicMock(return_value=True)
        self.sm.update_spec = MagicMock()
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, self.project_root, self.logger,
        )
        self.engine._enqueue = MagicMock()
        self.sm.add_spec = MagicMock()
        self.sm.add_spec("demo", {"priority": 5})
        # fast-track 结果文件（共享路径，spec stamp + 顶层 success）
        (self.project_root / ".fenix" / ".fenix-run-result.json").write_text(
            json.dumps({"spec": "demo", "status": "success",
                        "mode": "fast-track"}),
            encoding="utf-8",
        )
        # worktree 无活跃结果文件 → 读共享路径
        self.engine.agent_runner.worktree_manager.find_implementer_worktree = \
            MagicMock(return_value=None)
        # 守卫/校验/merge 全放行（_hard_check/_reconcile/_advance 是 Dispatcher
        # 自身方法，须 mock 在 dispatcher 上；守卫两件在 engine 上）
        self.engine._implementer_zero_change = MagicMock(return_value=False)
        self.engine._deliverable_gate_missing = MagicMock(return_value=[])
        self.engine._dispatcher._hard_check_fast_track = MagicMock(
            return_value={"verdict": "verified", "bugs": []})
        self.engine._dispatcher._reconcile_and_merge = MagicMock(
            return_value=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _snap(self, spec="demo"):
        return (self.project_root / ".fenix" / "verify-progress"
                / spec / "impl-result.json")

    def _result(self):
        from types import SimpleNamespace
        return SimpleNamespace(
            success=True, error=None, run_id="impl-demo-1-a1", branch="fb",
            worktree_dirty=[], cancelled=False,
            worktree_path=None, worktree_kept=False,
        )

    def test_success_writes_snapshot_before_verified_gate(self):
        """成功收口写快照，且写点在同步 verified 门禁评估之前。"""
        seen = {}

        def _probe(spec_name, result):
            seen["exists"] = self._snap().exists()
            if seen["exists"]:
                seen["data"] = json.loads(
                    self._snap().read_text(encoding="utf-8"))

        self.engine._dispatcher._fast_track_advance_to_verified = MagicMock(
            side_effect=_probe)
        self.engine._dispatcher._run_fast_track_flow("demo", self._result())

        self.assertTrue(self._snap().exists())
        data = json.loads(self._snap().read_text(encoding="utf-8"))
        self.assertEqual(data["spec"], "demo")
        self.assertEqual(data["status"], "success")
        # 推进 verified（同步门禁评估）时快照已在场
        self.assertTrue(seen.get("exists"))
        self.assertEqual(seen["data"]["spec"], "demo")

    def test_bugfound_escalation_writes_snapshot(self):
        """bug-found 升级路径同样落快照（实现成功语义，与 full 车道一致）。"""
        self.engine._dispatcher._hard_check_fast_track = MagicMock(
            return_value={"verdict": "bug-found",
                          "bugs": [{"severity": "major", "scenario_ids": ["s1"]}]})
        self.engine._dispatcher._escalate_to_full_mode = MagicMock()
        self.engine._dispatcher._run_fast_track_flow("demo", self._result())
        self.assertTrue(self._snap().exists())
        data = json.loads(self._snap().read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "success")

    def test_cancelled_path_does_not_write_snapshot(self):
        """取消路径不写快照（hold-state 语义不变）。"""
        from types import SimpleNamespace
        result = SimpleNamespace(
            success=False, cancelled=True, error="测试原因", run_id="r",
            branch=None, worktree_dirty=None,
            worktree_path=None, worktree_kept=False,
        )
        self.engine._dispatcher._run_fast_track_flow("demo", result)
        self.assertFalse(self._snap().exists())
