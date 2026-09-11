"""add-spec-content-integrity-gate 能力测试。

覆盖 spec 全部 Scenario（spec.md 三 Requirement）：
- 判定函数各形态：不存在/空目录/只有无关文件/有 tasks/有 proposal/只有 specs
  子目录/读目录 IO 异常保守放行
- 闸门命中冻结：blocked + spec_content_missing 告警 + 不启动 run + 回滚队列
- 含实质内容正常派发：校验通过进入 implementing
- 已冻结幂等：已是 blocked 不重复告警但仍拒绝重派
- 告警生命周期闭环：spec_content_missing 已注册到 _SIGNAL_CONDITIONS
  （spec 补内容解冻后自动 resolve）
"""

import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, ESCALATION
from core.alert_lifecycle import _SIGNAL_CONDITIONS, CONDITION_SPEC_TERMINAL_OR_UNBLOCKED
from core.state_machine import StateMachine
from core.pm_engine.spec_integrity import spec_has_content, SpecIntegrityGate


def _mk_engine(project_root, logger, config=None):
    from core.pm_engine import PMEngine
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, project_root, logger)
    engine.handle_event = MagicMock()
    return engine, sm


def _mk_spec_dir(project_root: Path, name: str, files: list) -> Path:
    """构造 spec/changes/<name>/ 目录并按 files 清单创建内容文件。"""
    d = project_root / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        p = d / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")
    return d


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _alerts(self, signal_type: str, spec: str) -> list:
        return [a for a in AdminStore(self.project_root, self.logger).read_all()
                if a.get("signal_type") == signal_type and a.get("spec") == spec]


class TestSpecHasContent(unittest.TestCase):
    """1.1：spec_has_content 各形态"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dir_not_exist_returns_false(self):
        self.assertFalse(spec_has_content(self.project_root, "no-such-spec"))

    def test_empty_dir_returns_false(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.assertFalse(spec_has_content(self.project_root, "empty-spec"))

    def test_unrelated_files_only_returns_false(self):
        _mk_spec_dir(self.project_root, "noise-spec", [".DS_Store", "run.log"])
        self.assertFalse(spec_has_content(self.project_root, "noise-spec"))

    def test_has_tasks_md_returns_true(self):
        _mk_spec_dir(self.project_root, "ok-spec", ["tasks.md"])
        self.assertTrue(spec_has_content(self.project_root, "ok-spec"))

    def test_has_proposal_md_returns_true(self):
        _mk_spec_dir(self.project_root, "draft-spec", ["proposal.md"])
        self.assertTrue(spec_has_content(self.project_root, "draft-spec"))

    def test_has_design_md_returns_true(self):
        _mk_spec_dir(self.project_root, "design-only-spec", ["design.md"])
        self.assertTrue(spec_has_content(self.project_root, "design-only-spec"))

    def test_only_specs_subdir_md_returns_true(self):
        _mk_spec_dir(self.project_root, "specs-only-spec",
                     ["specs/some-cap/spec.md"])
        self.assertTrue(spec_has_content(self.project_root, "specs-only-spec"))

    def test_specs_subdir_no_md_returns_false(self):
        # specs/ 存在但无 *.md（只有无关文件）→ 空判定
        _mk_spec_dir(self.project_root, "specs-noise-spec", ["specs/note.txt"])
        self.assertFalse(spec_has_content(self.project_root, "specs-noise-spec"))

    def test_specs_nested_md_returns_true(self):
        # specs/ 多级嵌套 *.md（rglob **）兜底
        _mk_spec_dir(self.project_root, "nested-spec",
                     ["specs/a/b/c/spec.md"])
        self.assertTrue(spec_has_content(self.project_root, "nested-spec"))

    def test_io_error_conservative_pass(self):
        _mk_spec_dir(self.project_root, "perm-spec", ["tasks.md"])
        with patch("core.pm_engine.spec_integrity.Path.is_dir",
                   side_effect=PermissionError("denied")):
            # IO 异常保守放行（True），不误伤
            self.assertTrue(spec_has_content(self.project_root, "perm-spec"))


class TestGateFreeze(_Base):
    """2.1：闸门命中冻结处置"""

    def test_gate_hit_blocks_and_alerts_not_start_run(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")

        self.assertTrue(self.engine._check_spec_content_missing("empty-spec"))

        entry = self.sm.read_one("empty-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("SPEC 内容缺失", entry["error"])
        self.assertIn("empty-spec", entry["error"])
        alerts = self._alerts("spec_content_missing", "empty-spec")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], ESCALATION)
        self.assertEqual(alerts[0]["severity"], "major")
        self.assertIn("empty-spec", alerts[0]["description"])

    def test_gate_pass_does_not_block(self):
        _mk_spec_dir(self.project_root, "ok-spec", ["tasks.md"])
        self.sm.add_spec("ok-spec", {"priority": 5})
        self.sm.transition("ok-spec", "ready")

        self.assertFalse(self.engine._check_spec_content_missing("ok-spec"))
        self.assertEqual(self.sm.read_one("ok-spec")["status"], "ready")
        self.assertEqual(len(self._alerts("spec_content_missing", "ok-spec")), 0)

    def test_already_blocked_idempotent_no_duplicate_alert(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")
        self.engine._check_spec_content_missing("empty-spec")
        self.assertEqual(len(self._alerts("spec_content_missing", "empty-spec")), 1)

        # 再次评估（已是 blocked）：幂等 True，不重复告警
        self.assertTrue(self.engine._check_spec_content_missing("empty-spec"))
        self.assertEqual(
            len(self._alerts("spec_content_missing", "empty-spec")), 1)

    def test_gate_hit_then_content_added_passes(self):
        # 补内容后闸门放行（spec 解冻由恢复巡检处理，此处只验判定）
        d = _mk_spec_dir(self.project_root, "empty-spec", [])
        self.assertTrue(self.engine._spec_integrity.check_spec_content_missing("empty-spec"))
        (d / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
        self.assertFalse(self.engine._spec_integrity.check_spec_content_missing("empty-spec"))


class TestDispatchGate(unittest.TestCase):
    """2.3/2.4：派发前闸门接入（implementer / fast-track 双分支）"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        # 注意：不用 mock _enqueue，使用真实入队以触发 _process_queue

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _enqueue_and_process(self, spec_name: str, agent_type: str):
        self.engine._enqueue(spec_name, agent_type)
        self.engine._process_queue()

    def _alerts(self, signal_type: str, spec: str) -> list:
        return [a for a in AdminStore(self.project_root, self.logger).read_all()
                if a.get("signal_type") == signal_type and a.get("spec") == spec]

    def test_implementer_empty_spec_not_dispatched(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")
        # 打桩：断言 run 绝不启动
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("empty-spec", "implementer")

        self.engine._run_agent_worker.assert_not_called()
        entry = self.sm.read_one("empty-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertEqual(len(self._alerts("spec_content_missing", "empty-spec")), 1)

    def test_implementer_content_spec_dispatched(self):
        _mk_spec_dir(self.project_root, "ok-spec", ["tasks.md"])
        self.sm.add_spec("ok-spec", {"priority": 5})
        self.sm.transition("ok-spec", "ready")
        # 后续 worker 内部会启动线程调用真实逻辑；打桩以同步断言
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("ok-spec", "implementer")

        self.engine._run_agent_worker.assert_called_once()
        self.assertEqual(self.sm.read_one("ok-spec")["status"], "implementing")

    def test_fast_track_empty_spec_not_dispatched(self):
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("empty-spec", "fast-track")

        self.engine._run_agent_worker.assert_not_called()
        self.assertEqual(self.sm.read_one("empty-spec")["status"], "blocked")
        self.assertEqual(len(self._alerts("spec_content_missing", "empty-spec")), 1)

    def test_fast_track_content_spec_dispatched(self):
        _mk_spec_dir(self.project_root, "ok-spec", ["proposal.md"])
        self.sm.add_spec("ok-spec", {"priority": 5})
        self.sm.transition("ok-spec", "ready")
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("ok-spec", "fast-track")

        self.engine._run_agent_worker.assert_called_once()
        self.assertEqual(self.sm.read_one("ok-spec")["status"], "implementing")

    def test_missing_spec_never_touches_budget(self):
        # 空 spec 被内容闸门拦截，预算计数不被消耗（零 run 启动）
        _mk_spec_dir(self.project_root, "empty-spec", [])
        self.sm.add_spec("empty-spec", {"priority": 5})
        self.sm.transition("empty-spec", "ready")
        self.engine._run_agent_worker = MagicMock()

        self._enqueue_and_process("empty-spec", "implementer")

        used = self.engine._impl_run_budget_used("empty-spec")
        self.assertEqual(used, 0)


class TestAlertLifecycleClosedLoop(unittest.TestCase):
    """3.1：spec_content_missing 接入告警生命周期闭环"""

    def test_signal_condition_registered(self):
        self.assertEqual(
            _SIGNAL_CONDITIONS.get("spec_content_missing"),
            CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
        )

    def test_trigger_attached_on_alert(self):
        import tempfile
        import shutil
        tmpdir = tempfile.mkdtemp()
        try:
            project_root = Path(tmpdir)
            (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
            logger = MagicMock()
            engine, sm = _mk_engine(project_root, logger)
            _mk_spec_dir(project_root, "empty-spec", [])
            sm.add_spec("empty-spec", {"priority": 5})
            sm.transition("empty-spec", "ready")
            engine._check_spec_content_missing("empty-spec")

            alerts = [a for a in AdminStore(project_root, logger).read_all()
                      if a.get("signal_type") == "spec_content_missing"]
            self.assertEqual(len(alerts), 1)
            trigger = alerts[0].get("trigger")
            self.assertIsNotNone(trigger)
            self.assertEqual(trigger["condition"], CONDITION_SPEC_TERMINAL_OR_UNBLOCKED)
            self.assertEqual(trigger["spec"], "empty-spec")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()