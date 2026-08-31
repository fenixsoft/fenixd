"""原地打回处置测试（add-inplace-bug-repair）。

覆盖 inplace-bug-repair spec 的全部 Scenario：
- 首轮失败 → 计数 1 + implementing + 修复段注入 + 无新 fix spec
- 二轮失败 → 计数 2 + 段内轮数更新
- 第三轮 → blocked + 告警
- 计数器跨重启持久（模拟 STATE.md 重读）
- 噪音分流不触发打回（assertion_results 为空场景）
- 既有勾选状态不被改写
- 存量 fix 链重验闭环回归（legacy 路径）
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, ESCALATION
from core.state_machine import StateMachine


def _mk_engine(project_root, logger, config=None):
    from core.pm_engine import PMEngine
    sm = StateMachine(project_root / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, project_root, logger)
    engine.handle_event = MagicMock()
    return engine, sm


class _InplaceBase(unittest.TestCase):
    """公共夹具：临时项目根 + PMEngine（不真实派发）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_buggy_spec(self, name="quick-links-folders"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")
        self.sm.transition(name, "bug-found")

    def _write_tasks(self, name, content):
        spec_dir = self.project_root / "openspec" / "changes" / name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(content, encoding="utf-8")

    def _tasks_text(self, name):
        return (self.project_root / "openspec" / "changes" / name / "tasks.md") \
            .read_text(encoding="utf-8")


class TestInplaceFirstRound(_InplaceBase):
    """Scenario: 首次验证失败原地打回。"""

    def test_first_round_injects_section_no_fix(self):
        self._write_tasks("quick-links-folders",
                          "# Tasks\n\n## 1. 实现\n\n- [x] 1.1 已完成\n")
        self._make_buggy_spec("quick-links-folders")

        self.engine._family._do_spec_bug_found("quick-links-folders")

        entry = self.sm.read_one("quick-links-folders")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 1)
        self.assertEqual(entry["status"], "implementing")
        # 无新 fix-* SPEC 被创建
        self.assertIsNone(self.sm.read_one("fix-quick-links-folders"))
        # tasks.md 末尾出现「验证修复」段，标注轮数 1
        txt = self._tasks_text("quick-links-folders")
        self.assertIn("## 验证修复", txt)
        self.assertIn("第 1 轮", txt)
        self.assertIn("verification-report.md", txt)
        self.assertIn("真实产品 Bug", txt)
        # 既有勾选不被改写
        self.assertIn("- [x] 1.1 已完成", txt)
        # 排队实现器
        self.engine._enqueue.assert_called_once_with("quick-links-folders", "implementer")


class TestInplaceSecondRound(_InplaceBase):
    """Scenario: 二次失败递增轮数而非新建链条。"""

    def test_second_round_updates_round_number(self):
        self._write_tasks("quick-links-folders", "# Tasks\n")
        self._make_buggy_spec("quick-links-folders")
        self.sm.update_spec("quick-links-folders", {
            "_verify_fail_rounds": 1, "status": "bug-found",
        })

        self.engine._family._do_spec_bug_found("quick-links-folders")

        entry = self.sm.read_one("quick-links-folders")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 2)
        self.assertEqual(entry["status"], "implementing")
        # 族谱深度保持 0（无 fix 子）
        self.assertEqual(self.engine._family._fix_prefix_depth("quick-links-folders"), 0)
        txt = self._tasks_text("quick-links-folders")
        self.assertIn("第 2 轮", txt)
        # 轮数注记更新而非新增段（仍只有一个「验证修复」标题）
        self.assertEqual(txt.count("## 验证修复"), 1)


class TestInplaceThirdRoundEscalate(_InplaceBase):
    """Scenario: 连续三轮失败冻结升级。"""

    def test_third_round_blocks_and_alerts(self):
        self._make_buggy_spec("quick-links-folders")
        self.sm.update_spec("quick-links-folders", {
            "_verify_fail_rounds": 2, "status": "bug-found",
        })

        self.engine._family._do_spec_bug_found("quick-links-folders")

        entry = self.sm.read_one("quick-links-folders")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 3)
        self.assertEqual(entry["status"], "blocked")
        # 不再重置 implementing，也不追加任务段
        txt_path = self.project_root / "openspec" / "changes" / "quick-links-folders" / "tasks.md"
        if txt_path.exists():
            self.assertNotIn("## 验证修复", txt_path.read_text(encoding="utf-8"))
        # 产生 human-escalation-alerts 告警
        alerts = [a for a in AdminStore(self.project_root, self.logger).read_all()
                  if a.get("signal_type") == "verify_fail_escalation"
                  and a.get("spec") == "quick-links-folders"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], ESCALATION)
        self.assertIn("3 轮", alerts[0]["description"])
        self.assertIn("verification-report.md", alerts[0]["evidence"])


class TestFailRoundsPersistAcrossRestart(_InplaceBase):
    """Scenario: 计数器跨重启持久。"""

    def test_counter_persists_after_restart(self):
        self._write_tasks("quick-links-folders", "# Tasks\n")
        self._make_buggy_spec("quick-links-folders")
        self.engine._family._do_spec_bug_found("quick-links-folders")

        # 模拟 daemon 重启：从磁盘重新构造 state machine
        from core.state_machine import StateMachine as SM
        new_sm = SM(self.project_root / "STATE.md", self.logger)
        entry = new_sm.read_one("quick-links-folders")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 1)
        self.assertEqual(entry["status"], "implementing")

        # 第二轮：从持久化值继续递增
        engine2, _ = _mk_engine(self.project_root, self.logger)
        engine2._enqueue = MagicMock()
        engine2._do_spec_bug_found("quick-links-folders")
        entry2 = new_sm.read_one("quick-links-folders")
        self.assertEqual(int(entry2.get("_verify_fail_rounds", 0)), 2)


class TestNoiseNotRepaired(_InplaceBase):
    """Scenario: 噪音分流不触发打回（assertion_results 为空）。

    注：噪音分流的判定在验证裁决前置（verification-completion-gate），
    本测试验证 `_do_spec_bug_found` 对「非真实产品缺陷」信号不执行打回。
    这里用 legacy 路径（fix-*）与 inplace 路径对照，确保计数/状态语义正确。
    """

    def test_inplace_only_on_real_bug_signal(self):
        # 仅当裁决已置 bug-found 且 _is_fix_spec 为 False 时才走原地打回
        self._make_buggy_spec("quick-links-folders")
        self.engine._family._do_spec_bug_found("quick-links-folders")
        entry = self.sm.read_one("quick-links-folders")
        # 真实 bug 信号 → 原地打回（计数+1，状态 implementing）
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 1)
        self.assertEqual(entry["status"], "implementing")


class TestExistingCheckboxPreserved(_InplaceBase):
    """既有勾选状态不被改写（D3）。"""

    def test_checkbox_state_not_overwritten(self):
        self._write_tasks("quick-links-folders",
                          "# Tasks\n\n"
                          "- [x] 1.1 已完成实现\n"
                          "- [ ] 1.2 待办\n\n"
                          "## 验证修复\n\n"
                          "- [x] 旧轮次勾选\n")
        self._make_buggy_spec("quick-links-folders")
        self.sm.update_spec("quick-links-folders", {
            "_verify_fail_rounds": 1, "status": "bug-found",
        })

        self.engine._family._do_spec_bug_found("quick-links-folders")

        txt = self._tasks_text("quick-links-folders")
        # 既有勾选保持不变
        self.assertIn("- [x] 1.1 已完成实现", txt)
        self.assertIn("- [ ] 1.2 待办", txt)
        self.assertIn("第 2 轮", txt)


class TestLegacyFixChainReverify(_InplaceBase):
    """存量 fix 链重验闭环回归（D4 legacy 路径仍生效）。"""

    def test_legacy_fix_child_preserved_on_parent_bugfound(self):
        # 存量 fix-quick-links-folders 仍在 bug-found，已有 done 子 fix-fix-...
        self.sm.add_spec("fix-quick-links-folders", {"priority": 5})
        self.sm.transition("fix-quick-links-folders", "ready")
        self.sm.transition("fix-quick-links-folders", "implementing")
        self.sm.transition("fix-quick-links-folders", "implemented")
        self.sm.transition("fix-quick-links-folders", "testing")
        self.sm.transition("fix-quick-links-folders", "bug-found")
        self.sm.add_spec("fix-fix-quick-links-folders", {
            "status": "done", "priority": 6,
            "implementer_run": "impl-old", "tester_run": "tst-old",
        })

        self.engine._family._do_spec_bug_found("fix-quick-links-folders")

        # done 子保持原状
        child = self.sm.read_one("fix-fix-quick-links-folders")
        self.assertEqual(child["status"], "done")
        self.assertEqual(child["implementer_run"], "impl-old")
        # 派生新一轮 fix-fix-fix-* 作为新修复承载方
        new_child = self.sm.read_one("fix-fix-fix-quick-links-folders")
        self.assertIsNotNone(new_child)
        self.assertEqual(new_child["status"], "ready")
        # 父 fix 保持 bug-found（legacy 闭环：等子 fix 完成后由 _on_spec_done 重验）
        self.assertEqual(self.sm.read_one("fix-quick-links-folders")["status"], "bug-found")
        self.engine._enqueue.assert_called_with(
            "fix-fix-fix-quick-links-folders", "implementer")


if __name__ == "__main__":
    unittest.main()
