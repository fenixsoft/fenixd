"""characterization tests for refactor-core-packages（阶段 0，任务 1.2）。

锁定将被搬移且当前无测试覆盖的方法在拆分前的行为，搬移后必须逐条保持一致：
- PMEngine._same_root / _sibling_has_live_agent（→ core/pm_engine/family.py）
- PMEngine._rewrite_scenario_port（→ core/pm_engine/verification.py）
- PMEngine.generate_report / generate_daily_report / get_pushable_specs
  （→ core/pm_engine/reporting.py，engine.py 保留门面）
- PMEngine._signal_push_failed / get_health_summary / _dependencies_satisfied
  （留在 core/pm_engine/engine.py，未迁入 reporting.py）

覆盖口径：core/ 双巨文件 per-method 行覆盖分析（2026-08-31 基线，见
spec/changes/refactor-core-packages/findings.md）。本文件只新增，
不修改任何现有测试文件。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine


def make_engine(tmpdir, state_machine=None, agent_runner=None, config=None):
    return PMEngine(
        state_machine if state_machine is not None else MagicMock(),
        agent_runner if agent_runner is not None else MagicMock(),
        config or {},
        Path(tmpdir),
        MagicMock(),
    )


class TestSameRootCharacterization(unittest.TestCase):
    """_same_root：同根判定（剥除全部 fix- 前缀后同名）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = make_engine(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_same_root_pairs(self):
        self.assertTrue(self.engine._family._same_root("fix-x", "fix-fix-x"))
        self.assertTrue(self.engine._family._same_root("fix-fix-x", "fix-x"))
        self.assertTrue(self.engine._family._same_root("fix-x", "fix-x"))

    def test_different_roots(self):
        self.assertFalse(self.engine._family._same_root("fix-x", "fix-y"))
        self.assertFalse(self.engine._family._same_root("fix-x", "y"))

    def test_non_fix_names_are_never_same_root(self):
        self.assertFalse(self.engine._family._same_root("x", "x"))
        self.assertFalse(self.engine._family._same_root("x", "fix-x"))


class TestSiblingHasLiveAgentCharacterization(unittest.TestCase):
    """_sibling_has_live_agent：worktree_manager → has_live_attempt → pgrep 兜底。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ar = MagicMock()
        self.engine = make_engine(self.tmpdir, agent_runner=self.ar)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_worktree_manager_active_wins(self):
        wm = self.ar.worktree_manager
        wm.has_active_worktree = MagicMock(return_value=True)
        self.assertTrue(self.engine._family._sibling_has_live_agent("s1"))
        wm.has_active_worktree.assert_called_once_with("s1")

    def test_has_live_attempt_fallback(self):
        self.ar.worktree_manager.has_active_worktree = MagicMock(return_value=False)
        self.ar.has_live_attempt = MagicMock(return_value=True)
        self.assertTrue(self.engine._family._sibling_has_live_agent("s1"))
        self.ar.has_live_attempt.assert_called_once_with("s1")

    def test_no_live_agent_without_worktrees_dir(self):
        self.ar.worktree_manager.has_active_worktree = MagicMock(return_value=False)
        self.ar.has_live_attempt = MagicMock(return_value=False)
        # tmpdir 下无 .claude/worktrees → pgrep 回退直接 False
        self.assertFalse(self.engine._family._sibling_has_live_agent("s1"))

    def test_worktree_manager_missing_attribute_is_tolerated(self):
        # agent_runner 无 worktree_manager 属性 / 无 has_live_attempt 属性时不炸
        del self.ar.worktree_manager
        del self.ar.has_live_attempt
        self.assertFalse(self.engine._family._sibling_has_live_agent("s1"))


class TestRewriteScenarioPortCharacterization(unittest.TestCase):
    """_rewrite_scenario_port：URL 端口改写与异常吞并（→ verification.py）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.logger = MagicMock()
        self.engine = make_engine(self.tmpdir, config={})
        self.engine.logger = self.logger

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rewrites_url_port_only(self):
        p = self.tmpdir / "test_scenarios.json"
        p.write_text(
            json.dumps([
                {"steps": [
                    {"action": "navigate", "value": "http://127.0.0.1:8765/"},
                ]},
            ]),
            encoding="utf-8",
        )
        self.engine._verification._rewrite_scenario_port(p, 8765, 9999)
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["steps"][0]["value"], "http://127.0.0.1:9999/")
        self.logger.info.assert_called_once()

    def test_non_target_fields_preserved(self):
        """2026-09-17 同类缺口回归：选择器/注入数据/断言内的端口 MUST NOT 被改写。

        旧实现与 rewrite_scenarios_origin 同型——对 test_scenarios.json 整份
        文本跑端口正则，落进 ``input[placeholder='http://127.0.0.1:8765']``、
        ``seed.value``、断言 ``expected`` 等字段即把「选择器字面量/测试数据」
        当「导航目标」改写（快速链接事故的同型通道）。
        """
        p = self.tmpdir / "test_scenarios.json"
        p.write_text(
            json.dumps([
                {
                    "steps": [
                        {"action": "navigate", "value": "http://127.0.0.1:8765/"},
                        {"action": "type",
                         "target": "input[placeholder='http://127.0.0.1:8765']",
                         "value": "http://127.0.0.1:8765"},
                        {"action": "seed", "target": "k",
                         "value": '[{"url": "http://127.0.0.1:8765/x"}]'},
                        {"action": "mock_api", "target": "**/127.0.0.1:8765/**",
                         "value": "{}"},
                    ],
                    "assertions": [
                        {"type": "attribute_match", "selector": "a",
                         "expected": "http://127.0.0.1:8765/"},
                    ],
                },
            ]),
            encoding="utf-8",
        )
        self.engine._verification._rewrite_scenario_port(p, 8765, 9999)
        data = json.loads(p.read_text(encoding="utf-8"))
        steps = data[0]["steps"]
        self.assertEqual(steps[0]["value"], "http://127.0.0.1:9999/")
        self.assertEqual(steps[1]["target"],
                         "input[placeholder='http://127.0.0.1:8765']")
        self.assertEqual(steps[2]["value"], '[{"url": "http://127.0.0.1:8765/x"}]')
        self.assertEqual(steps[3]["target"], "**/127.0.0.1:8765/**")
        self.assertEqual(data[0]["assertions"][0]["expected"],
                         "http://127.0.0.1:8765/")

    def test_missing_file_is_swallowed_with_warning(self):
        p = self.tmpdir / "missing.json"
        self.engine._verification._rewrite_scenario_port(p, 8765, 9999)
        self.logger.warning.assert_called_once()
        self.assertFalse(p.exists())


class TestReportingCharacterization(unittest.TestCase):
    """generate_report / generate_daily_report / get_pushable_specs /
    _signal_push_failed / get_health_summary（→ reporting.py）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.sm = MagicMock()
        self.engine = make_engine(self.tmpdir, state_machine=self.sm)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generate_report_empty(self):
        self.sm.read_all.return_value = {}
        self.assertEqual(
            self.engine.generate_report(),
            "📋 No SPECs yet. Create one with /fenix:new",
        )

    def test_generate_report_counts_and_orders(self):
        self.sm.read_all.return_value = {
            "b-spec": {"status": "ready", "priority": 4},
            "a-spec": {"status": "done", "priority": 2},
            "c-spec": {"status": "weird-status", "priority": 3},
        }
        report = self.engine.generate_report()
        self.assertIn("### Summary", report)
        self.assertIn("- 🎯 **a-spec** (P2): done", report)
        self.assertIn("- ❓ **c-spec** (P3): weird-status", report)
        self.assertIn("- Total: 3", report)
        self.assertIn("- 🎯 done: 1", report)
        self.assertIn("- ❓ weird-status: 1", report)

    def test_generate_daily_report_appends_project_log(self):
        self.sm.read_all.return_value = {}
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
        self.engine.generate_daily_report()
        log = (self.tmpdir / ".fenix" / "PROJECT_LOG.md").read_text(encoding="utf-8")
        self.assertIn("📋 No SPECs yet", log)
        self.assertIn("---", log)

    def test_get_pushable_specs_passthrough(self):
        self.sm.get_by_status.return_value = [{"name": "a"}]
        self.assertEqual(self.engine.get_pushable_specs(), [{"name": "a"}])
        self.sm.get_by_status.assert_called_once_with("done")

    def test_signal_push_failed_writes_admin_store(self):
        self.engine._signal_push_failed("spec-a", "boom detail")
        from core.admin_store import AdminStore
        records = AdminStore(self.tmpdir, self.engine.logger).read_all()
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["signal_type"], "push_failed")
        self.assertEqual(rec["spec"], "spec-a")
        self.assertEqual(rec["severity"], "major")
        self.assertEqual(rec["evidence"], "boom detail")
        self.assertFalse(rec["handled"])

    def test_get_health_summary_empty(self):
        self.sm.read_all.return_value = {}
        self.assertEqual(self.engine.get_health_summary(), "📋 尚无 SPEC")

    def test_get_health_summary_counts(self):
        self.sm.read_all.return_value = {
            "a": {"status": "done"},
            "b": {"status": "pushed"},
            "c": {"status": "implementing"},
            "d": {"status": "testing"},
            "e": {"status": "ready", "error": "boom"},
            "f": {"status": "ready"},
        }
        summary = self.engine.get_health_summary()
        self.assertIn("📦 6 个 SPEC", summary)
        self.assertIn("✅ 2 完成", summary)
        self.assertIn("🔨 2 进行中", summary)
        self.assertIn("⚠️ 1 阻塞", summary)


class TestDependenciesSatisfiedCharacterization(unittest.TestCase):
    """_dependencies_satisfied（→ reporting.py 收尾诊断域）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = MagicMock()
        self.engine = make_engine(self.tmpdir, state_machine=self.sm)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_spec_is_satisfied(self):
        self.sm.read_one.return_value = None
        self.assertTrue(self.engine._dependencies_satisfied("ghost"))

    def test_no_deps_is_satisfied(self):
        self.sm.read_one.return_value = {"name": "a"}
        self.assertTrue(self.engine._dependencies_satisfied("a"))

    def test_null_string_deps_is_satisfied(self):
        self.sm.read_one.return_value = {"name": "a", "depends_on": "null"}
        self.assertTrue(self.engine._dependencies_satisfied("a"))

    def test_missing_dependency_blocks(self):
        def read_one(name):
            return {"name": "a", "depends_on": "dep-x"} if name == "a" else None
        self.sm.read_one.side_effect = read_one
        self.assertFalse(self.engine._dependencies_satisfied("a"))

    def test_terminal_dependency_satisfies(self):
        def read_one(name):
            return ({"name": "a", "depends_on": "dep-x"} if name == "a"
                    else {"name": "dep-x", "status": "implemented"})
        self.sm.read_one.side_effect = read_one
        self.assertTrue(self.engine._dependencies_satisfied("a"))

    def test_active_dependency_blocks(self):
        def read_one(name):
            return ({"name": "a", "depends_on": "dep-x, dep-y"} if name == "a"
                    else {"name": name, "status": "ready"})
        self.sm.read_one.side_effect = read_one
        self.assertFalse(self.engine._dependencies_satisfied("a"))


if __name__ == "__main__":
    unittest.main()
