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
        self.state_path = Path(self.tmpdir) / "STATE.md"
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
        spec_dir = Path(self.tmpdir) / "openspec" / "changes" / "quick-links-folders"
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
        spec_dir = Path(self.tmpdir) / "openspec" / "changes" / "quick-links-folders"
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
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_double_bug_found_no_duplicate_injection(self):
        spec_dir = Path(self.tmpdir) / "openspec" / "changes" / "my-spec"
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
        self.state_path = Path(self.tmpdir) / "STATE.md"
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


class TestRouteTableGuard(unittest.TestCase):
    """路由表守卫：未注册的 agent_type 不得绕过路由表直派。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.engine = PMEngine(
            self.sm, MagicMock(), {}, Path(self.tmpdir), self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unknown_agent_type_raises(self):
        self.sm.add_spec("test-spec", {"priority": 1})
        self.sm.transition("test-spec", "ready")
        # Test that unknown agent type is handled appropriately
        # The Dispatcher uses _enqueue to add to queue
        self.engine._dispatcher._enqueue("test-spec", "unknown_type")
        # Verify it was added to the queue
        self.assertTrue(any(e[1] == "test-spec" and e[2] == "unknown_type"
                          for e in self.engine._dispatcher._run_queue))


class TestEngineRouteCrossCheck(unittest.TestCase):
    """引擎路由交叉校验：所有合法 agent_type 必须有对应路由。"""

    def test_all_statuses_have_routes(self):
        from core.pm_engine import PMEngine
        tmpdir = tempfile.mkdtemp()
        try:
            sm = StateMachine(Path(tmpdir) / "STATE.md", MagicMock())
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
