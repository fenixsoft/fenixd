"""tests/test_run_budget_continuity.py — fix-run-hang-amplification 2.x

覆盖：
  5.4 监督超时杀死 run → 断言预算计数**不**回退；`interrupted` 终态 → 断言回退（既有语义保留）。
  5.5 断言重派 attempt 的 prompt 含结构化诊断段；无诊断时 prompt 与现状逐字节一致；
      `_rollback_failed_dispatch` 后诊断字段仍在。
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pm_engine.budget import ImplBudget
from core.state_machine import IMPL_DIAGNOSIS_FIELD

# 模块级快捷引用，方便测试调用
_is_exemptable_reason = ImplBudget._is_exemptable_reason


# ── Helpers ───────────────────────────────────────────────────────────

class FakePM:
    def __init__(self, project_root=None):
        self.project_root = project_root or Path(tempfile.mkdtemp())
        self.logger = MagicMock()
        self.state_machine = MagicMock()
        self.state_machine.read_one.return_value = {}
        self.state_machine.bump_impl_budget.return_value = 5
        self.state_machine.bump_budget_exempt_runs.return_value = 1

    def _get_config(self, key, default=None):
        return default

    def _send_human_escalation_alert(self, spec_name, signal_type, severity,
                                     description, evidence, recommended_action,
                                     trigger=None):
        pass

    def _exempt_dead_run_budget(self, spec_name, reason, run_reason=None):
        pass

    def _enqueue(self, spec_name, agent_type):
        pass

    def _enqueue_front(self, spec_name, agent_type):
        pass


# ── 5.4 预算豁免判定 ──────────────────────────────────────────────────

class TestBudgetExemption:
    """5.4 监督超时/停滞杀不豁免；基础设施性死亡豁免保留。"""

    def test_timeout_budget_exhausted_not_exempt(self):
        """'Timeout after ... extension budget exhausted' → 不可豁免。"""
        reasons = [
            "Timeout after 12600s — extension budget exhausted (2/2)",
            "stagnant: heuristic zero-output ...",
            "judged stagnant",
            "stagnant: zero substantive run events within judge window",
        ]
        for r in reasons:
            assert not _is_exemptable_reason(r), f"reason={r!r} must NOT be exemptable"

    def test_infra_death_exempt(self):
        """基础设施性死亡原因 → 可豁免。"""
        reasons = [
            "no run-result file (error=None)",
            "dispatch exception: provider circuit open",
            "auto-recovery: stuck implementing 30m, no live child (no run-result)",
            "provider chain exhausted",
            "no run-result file (error=)",
        ]
        for r in reasons:
            assert _is_exemptable_reason(r), f"reason={r!r} must be exemptable"

    def test_exempt_dead_run_budget_respects_reason(self, tmp_path):
        """_exempt_dead_run_budget 按 run_reason 判定是否回退计数。"""
        pm = FakePM(tmp_path)
        budget = ImplBudget(pm)

        # 超时/停滞原因：不豁免（不触发幂等退款，也不直接回退计数）
        budget._exempt_dead_run_budget(
            "spec-a", "test reason",
            run_reason="Timeout after 100s — extension budget exhausted (2/2)")
        pm.state_machine.refund_dead_run_once.assert_not_called()
        pm.state_machine.bump_impl_budget.assert_not_called()

        # 重置 mock
        pm.state_machine.refund_dead_run_once.reset_mock()
        pm.state_machine.bump_impl_budget.reset_mock()
        pm.state_machine.bump_budget_exempt_runs.reset_mock()

        # 基础设施性死亡：豁免（item cd696b7c0de9：退款动作收敛为
        # state_machine.refund_dead_run_once 幂等锚点，锚点缺省回退
        # STATE implementer_run；不再直接调 bump_impl_budget）
        pm.state_machine.read_one.return_value = {"implementer_run": "run-b"}
        pm.state_machine.refund_dead_run_once.return_value = (True, 4)
        budget._exempt_dead_run_budget(
            "spec-b", "no run-result",
            run_reason=None)  # None → 旧语义豁免
        pm.state_machine.refund_dead_run_once.assert_called_once_with("spec-b", "run-b")
        pm.state_machine.bump_budget_exempt_runs.assert_called_once_with("spec-b")


# ── 5.5 结构化诊断继承 ────────────────────────────────────────────────

class TestDiagnosisInheritance:
    """5.5 诊断段注入与 rollback 不清除。"""

    def test_prompt_includes_diagnosis_when_present(self, tmp_path):
        """有 _impl_diagnosis 时 prompt 包含结构化诊断段。"""
        from core.agent_runner.prompt_builder import PromptBuilder
        diag = {
            "terminal": "timeout_budget_exhausted",
            "attribution": "Timeout after 12600s — extension budget exhausted",
            "conclusion": "全量套件在 32% 处挂起（pytest 死循环）",
            "progress": {"branch": "fenix/fix-x", "tasks_checked": 3},
        }
        entry = {
            "status": "implementing",
            IMPL_DIAGNOSIS_FIELD: json.dumps(diag, ensure_ascii=False),
        }
        pm = MagicMock()
        pm.project_root = tmp_path
        pm.state_machine.read_one.return_value = entry
        pb = PromptBuilder(pm)
        section = pb._impl_diagnosis_section("test-spec")
        assert "timeout_budget_exhausted" in section
        assert "全量套件在 32% 处挂起" in section
        assert "fenix/fix-x" in section
        assert "tasks_checked=3" in section

    def test_prompt_no_diagnosis_when_absent(self, tmp_path):
        """无 _impl_diagnosis 时 prompt 不含诊断段（逐字节不变）。"""
        from core.agent_runner.prompt_builder import PromptBuilder
        entry = {"status": "implementing"}
        pm = MagicMock()
        pm.project_root = tmp_path
        pm.state_machine.read_one.return_value = entry
        pb = PromptBuilder(pm)
        section = pb._impl_diagnosis_section("test-spec")
        assert section == ""

    def test_rollback_does_not_clear_diagnosis(self, tmp_path):
        """_rollback_failed_dispatch 清 error 时不清除 _impl_diagnosis。"""
        from core.pm_engine.dispatch import Dispatcher
        pm = FakePM(tmp_path)
        updates_log = []
        def fake_update(name, updates):
            updates_log.append(updates)
            return True
        pm.state_machine.update_spec.side_effect = fake_update

        spec_entry = {
            "status": "implementing",
            "implementer_run": "run-001",
            "error": None,
            IMPL_DIAGNOSIS_FIELD: json.dumps({
                "terminal": "stagnant",
                "attribution": "judged stagnant",
                "conclusion": "",
                "progress": {"branch": "fenix/y", "tasks_checked": 5},
            }),
        }
        pm.state_machine.read_one.return_value = spec_entry

        dispatcher = Dispatcher(pm)
        dispatcher._rollback_failed_dispatch(
            "test-spec", "implementer",
            Exception("dispatch failed"))

        assert len(updates_log) == 1
        called_updates = updates_log[0]
        assert called_updates.get("error") is None
        assert IMPL_DIAGNOSIS_FIELD not in called_updates
        assert IMPL_DIAGNOSIS_FIELD in spec_entry
        assert json.loads(spec_entry[IMPL_DIAGNOSIS_FIELD])["terminal"] == "stagnant"
        pm = FakePM(tmp_path)
        # 模拟 state_machine.update_spec 增量更新（只更新传入字段）
        updates_log = []
        def fake_update(name, updates):
            updates_log.append(updates)
            return True
        pm.state_machine.update_spec.side_effect = fake_update

        spec_entry = {
            "status": "implementing",
            "implementer_run": "run-001",
            "error": None,
            IMPL_DIAGNOSIS_FIELD: json.dumps({
                "terminal": "stagnant",
                "attribution": "judged stagnant",
                "conclusion": "",
                "progress": {"branch": "fenix/y", "tasks_checked": 5},
            }),
        }
        pm.state_machine.read_one.return_value = spec_entry

        dispatcher = Dispatcher(pm)
        dispatcher._rollback_failed_dispatch(
            "test-spec", "implementer",
            Exception("dispatch failed"))

        # update_spec 应被调用一次（implementer 分支）
        assert len(updates_log) == 1
        called_updates = updates_log[0]
        # error 被清为 None
        assert called_updates.get("error") is None
        # _impl_diagnosis 不在 updates 中（增量更新不会清除它）
        assert IMPL_DIAGNOSIS_FIELD not in called_updates
        # 验证 _impl_diagnosis 保留在原 spec_entry（模拟行为）
        assert IMPL_DIAGNOSIS_FIELD in spec_entry
        assert json.loads(spec_entry[IMPL_DIAGNOSIS_FIELD])["terminal"] == "stagnant"
