"""add-spec-status-modal-budget 能力测试（per-spec 实现尝试预算覆盖）。

覆盖 per-spec-impl-budget 全部 Scenario：
- 夹紧纯函数边界（0/11/非整数/bool）
- 覆盖优先解析（覆盖生效/缺失回退全局/全局缺失回退缺省/覆盖非法回退）
- 三调用点日志与耗尽判定按有效预算（告警 evidence budget=有效值）
- 覆盖只影响目标 spec

夹具复用 test_fail_counter_budget 的 _mk_engine 风格。
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, ESCALATION
from core.pm_engine.budget import (
    DEFAULT_IMPL_RUN_BUDGET,
    clamp_impl_run_budget,
    IMPL_RUN_BUDGET_OVERRIDE_FIELD,
)
from core.state_machine import StateMachine


def _mk_engine(project_root, logger, config=None):
    from core.pm_engine import PMEngine
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, project_root, logger)
    engine.handle_event = MagicMock()
    return engine, sm


class TestClampImplRunBudget(unittest.TestCase):
    """clamp_impl_run_budget 纯函数边界（模块级可导出）。"""

    def test_valid_int_clamped(self):
        self.assertEqual(clamp_impl_run_budget(5), 5)
        self.assertEqual(clamp_impl_run_budget(1), 1)
        self.assertEqual(clamp_impl_run_budget(10), 10)

    def test_out_of_range_clamped(self):
        self.assertEqual(clamp_impl_run_budget(0), 1)
        self.assertEqual(clamp_impl_run_budget(11), 10)
        self.assertEqual(clamp_impl_run_budget(100), 10)
        self.assertEqual(clamp_impl_run_budget(-5), 1)

    def test_string_int_is_non_integer(self):
        """字符串数字属于非整数类型 → None（回退下一优先级），与 API 400 口径一致。"""
        self.assertIsNone(clamp_impl_run_budget("7"))
        self.assertIsNone(clamp_impl_run_budget("0"))
        self.assertIsNone(clamp_impl_run_budget(5.5))
        self.assertIsNone(clamp_impl_run_budget("5.5"))
        self.assertIsNone(clamp_impl_run_budget([1, 2]))

    def test_non_int_returns_none(self):
        self.assertIsNone(clamp_impl_run_budget(None))
        self.assertIsNone(clamp_impl_run_budget("abc"))
        self.assertIsNone(clamp_impl_run_budget("5.5"))
        self.assertIsNone(clamp_impl_run_budget([1, 2]))

    def test_bool_returns_none(self):
        """bool 是 int 子类但语义非法 → None（回退下一优先级）。"""
        self.assertIsNone(clamp_impl_run_budget(True))
        self.assertIsNone(clamp_impl_run_budget(False))


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

    def _make_spec(self, name="demo-spec", status="bug-found"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")
        self.sm.transition(name, status)


class TestOverridePriority(_Base):
    """覆盖优先解析：per-spec override > 全局 config > DEFAULT。"""

    def test_override_active(self):
        """STATE 有 override=8 → 使用 8（全局 config 为 6）。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: 8})
        engine, _ = _mk_engine(self.project_root, self.logger,
                               {"agents": {"impl_run_budget": 6}})
        self.assertEqual(engine._budget._impl_run_budget("spec-a"), 8)

    def test_override_missing_fallback_global(self):
        """无 override → 回退全局 config（6）。"""
        self._make_spec("spec-a")
        engine, _ = _mk_engine(self.project_root, self.logger,
                               {"agents": {"impl_run_budget": 6}})
        self.assertEqual(engine._budget._impl_run_budget("spec-a"), 6)

    def test_global_missing_fallback_default(self):
        """无 override 且全局 config 无此键 → 回退 DEFAULT（6）。"""
        self._make_spec("spec-a")
        self.assertEqual(self.engine._budget._impl_run_budget("spec-a"),
                         DEFAULT_IMPL_RUN_BUDGET)

    def test_override_invalid_fallback_global(self):
        """override=abc（非整数）→ 忽略，回退全局 config（6）。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: "abc"})
        engine, _ = _mk_engine(self.project_root, self.logger,
                               {"agents": {"impl_run_budget": 6}})
        self.assertEqual(engine._budget._impl_run_budget("spec-a"), 6)

    def test_override_bool_fallback_global(self):
        """override=true（bool）→ 忽略，回退全局 config。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: True})
        engine, _ = _mk_engine(self.project_root, self.logger,
                               {"agents": {"impl_run_budget": 5}})
        self.assertEqual(engine._budget._impl_run_budget("spec-a"), 5)

    def test_override_zero_clamped_to_one(self):
        """override=0 → 夹紧为 1（与全局同口径）。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: 0})
        self.assertEqual(self.engine._budget._impl_run_budget("spec-a"), 1)

    def test_override_11_clamped_to_10(self):
        """override=11 → 夹紧为 10。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: 11})
        self.assertEqual(self.engine._budget._impl_run_budget("spec-a"), 10)

    def test_spec_name_none_uses_global(self):
        """spec_name=None → 直接用全局 config（无 override 查询）。"""
        engine, _ = _mk_engine(self.project_root, self.logger,
                               {"agents": {"impl_run_budget": 7}})
        self.assertEqual(engine._budget._impl_run_budget(None), 7)


class TestCallSitesUseEffectiveBudget(_Base):
    """三调用点日志与耗尽判定按有效预算（告警 evidence budget=有效值）。"""

    def test_increment_log_uses_effective_budget(self):
        """计数 +1 日志中 budget 字段为 per-spec 有效预算。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: 8})
        engine, _ = _mk_engine(self.project_root, self.logger)
        engine._budget._increment_impl_run_budget_used("spec-a")
        info_msgs = [c.args[1] for c in engine.logger.info.call_args_list]
        assert any("used=1/8" in m for m in info_msgs), (
            f"期望日志含 used=1/8，实际: {info_msgs}"
        )

    def test_exempt_log_uses_effective_budget(self):
        """死亡 run 豁免日志中 budget 字段为 per-spec 有效预算。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: 4})
        engine, _ = _mk_engine(self.project_root, self.logger)
        engine._budget._exempt_dead_run_budget("spec-a", "test death")
        warn_msgs = [c.args[1] for c in engine.logger.warning.call_args_list]
        assert any("回退至 0/4" in m for m in warn_msgs), (
            f"期望日志含 used=0/4，实际: {warn_msgs}"
        )

    def test_exhaustion_triggers_at_override_value(self):
        """预算耗尽判定按有效预算触发（override=3 → used=3 冻结）。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: 3})
        engine, _ = _mk_engine(self.project_root, self.logger)
        for _ in range(3):
            engine._budget._increment_impl_run_budget_used("spec-a")
        # 第 3 次后应冻结（used=3 >= budget=3）
        self.assertTrue(engine._budget._check_impl_budget_exhausted("spec-a"))
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("3/3", entry["error"])

    def test_exhaustion_evidence_contains_override_budget(self):
        """耗尽告警 evidence 中 budget 为 per-spec 有效预算。"""
        self._make_spec("spec-a")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: 3})
        engine, _ = _mk_engine(self.project_root, self.logger)
        for _ in range(3):
            engine._budget._increment_impl_run_budget_used("spec-a")
        engine._budget._check_impl_budget_exhausted("spec-a")
        alerts = [a for a in AdminStore(self.project_root, self.logger).read_all()
                  if a.get("signal_type") == "impl_budget_exhausted"
                  and a.get("spec") == "spec-a"]
        self.assertEqual(len(alerts), 1)
        self.assertIn("budget=3", alerts[0]["evidence"])


class TestOverrideAffectsOnlyTarget(_Base):
    """覆盖只影响目标 spec：其他 spec 仍用全局预算。"""

    def test_different_specs_use_different_budgets(self):
        self._make_spec("spec-a")
        self._make_spec("spec-b")
        self.sm.update_spec("spec-a", {IMPL_RUN_BUDGET_OVERRIDE_FIELD: 2})
        # spec-b 无 override → 全局（默认 6）
        engine, _ = _mk_engine(self.project_root, self.logger)
        self.assertEqual(engine._budget._impl_run_budget("spec-a"), 2)
        self.assertEqual(engine._budget._impl_run_budget("spec-b"),
                         DEFAULT_IMPL_RUN_BUDGET)
        # spec-a used=2 时冻结
        for _ in range(2):
            engine._budget._increment_impl_run_budget_used("spec-a")
        self.assertTrue(engine._budget._check_impl_budget_exhausted("spec-a"))
        # spec-b used=2 时未冻结
        for _ in range(2):
            engine._budget._increment_impl_run_budget_used("spec-b")
        self.assertFalse(engine._budget._check_impl_budget_exhausted("spec-b"))


if __name__ == "__main__":
    unittest.main()
