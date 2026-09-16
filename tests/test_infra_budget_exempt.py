"""
Tests for evo-infra-failure-budget-exempt — 基础设施故障不消耗实现预算与升级闸门轮次。

覆盖 spec/design 五场景（验收标准）：
1. **infra 不耗预算 / 闸门不累加**：infra 类失败（provider 熔断 / worktree / 陈旧
   结果文件）→ `_impl_run_budget_used` 回退、`_infra_failure_count` +1、
   `_verify_fail_rounds` 不变、spec 不冻结、可自动重排验证。
2. **对账不冲掉退款**：`_infra_failure_count > 0` 且 `_budget_exempt_runs == 0` 时
   跑 `_reconcile_impl_budget`，used 不被回写。
3. **闸门不累加**：连续 infra 轮次不使 `_verify_fail_rounds` 达到
   MAX_VERIFY_FAIL_ROUNDS（3）。
4. **回拨**：历史 `_verify_fail_rounds=3` + 台账含 2 条 infra 轮，admin 回拨后
   fail_rounds=1（低于阈值）且解冻；幂等（重复回拨不二次扣减）。
5. **D5 不回归**：结果文件缺失 / 非法 JSON 仍 blocked + critical，不自动重排。

另覆盖统一归因接口 `enrich_failure_class` 三态（infra|product|unknown）与
`_record_infra_failure` 退款幂等（同一 run 只退款一次）。
"""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import (
    StateMachine,
    INFRA_FAILURE_COUNT_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
    INFRA_REFUNDED_RUN_IDS_FIELD,
)
from core.pm_engine.verification import VerdictReadResult


def _make_circuit_open_error(provider_name="volc"):
    """构造 ProviderCircuit open 时返回的基础设施错误文本（与既有测试同源）。"""
    return (
        f"provider circuit open: {provider_name} "
        f"(HTTP 429 x 5) — cooldown 300s remaining"
    )


class TestInfraBudgetExempt(unittest.TestCase):
    """evo-infra-failure-budget-exempt 回归测试（5 场景验收）。"""

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
        self.engine._enqueue = MagicMock()
        self.engine._on_spec_bug_found = MagicMock()
        self.engine._on_spec_verified = MagicMock()
        self.engine._task_completion_blocker = MagicMock(return_value=None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_testing_spec(self, name="demo-spec", used=0):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")
        if used:
            self.sm.update_spec(name, {"_impl_run_budget_used": used})

    def _run_legacy_circuit_open(self, run_epoch, spec="demo-spec"):
        """legacy 验证路径：run_verifier 返回 circuit open（provider infra）。"""
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=False, error=_make_circuit_open_error(),
                run_id=f"verify-{spec}-{run_epoch}-a1", cancelled=False,
            ))
        self.engine._run_legacy_verification(spec)

    # ── 场景 1：infra 不消耗实现预算 / 可自动重排 ───────────────

    def test_infra_does_not_consume_budget(self):
        """provider 熔断（infra）→ used 回退、_infra_failure_count+1、
        _verify_fail_rounds 不变、spec 不冻结（保持 testing 可重排）。"""
        self._make_testing_spec(used=3)
        self.sm.update_spec("demo-spec", {"_verify_fail_rounds": 2})
        self._run_legacy_circuit_open(1)

        entry = self.sm.read_one("demo-spec")
        # infra 失败不流转 bug-found：保持 testing（full_scan recovery 兜底重排）
        self.assertEqual(entry["status"], "testing")
        self.assertNotEqual(entry["status"], "blocked")
        self.assertNotEqual(entry.get("frozen"), True)  # 不冻结
        self.assertNotEqual(entry["status"], "bug-found")
        # 预算回退（事后补偿）+ 独立计数
        self.assertEqual(int(entry.get("_impl_run_budget_used")), 2)
        self.assertEqual(int(entry.get(INFRA_FAILURE_COUNT_FIELD, 0)), 1)
        # 闸门不累加
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 2)
        # infra 轮次独立记账（观测）
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0)), 1)

    def test_new_path_circuit_open_refunds_budget(self):
        """new 验证路径：planner circuit-open hold → 同挂预算退款与 infra 记账。"""
        self._make_testing_spec(used=3)
        circuit_err = _make_circuit_open_error()
        self.engine.agent_runner.run_planner = MagicMock(
            return_value=SimpleNamespace(
                success=False, error=circuit_err,
                run_id="planner-plan-demo-spec-1-a1", cancelled=False,
            ))
        self.engine._verification._read_planner_result = MagicMock(
            return_value=VerdictReadResult.success("plan-ready"))
        self.engine._verification._apply_scenario_freeze = MagicMock(return_value={})
        self.engine._verification._apply_interaction_contract = MagicMock(return_value=None)

        with patch("importlib.reload", lambda m: m):
            self.engine._run_three_stage_verification("demo-spec")

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(int(entry.get("_impl_run_budget_used")), 2)
        self.assertEqual(int(entry.get(INFRA_FAILURE_COUNT_FIELD, 0)), 1)

    def test_env_blocked_accounts_infra_keeps_blocked_semantics(self):
        """prepare/serve env 阻塞（端口不可达）→ infra 记账，但 MUST 保持 env
        通道 blocked 语义（「env 失败绝不放行」刻意设计，不改为自动重排）。"""
        self._make_testing_spec(used=3)
        self.sm.update_spec(
            "demo-spec", {"implementer_run": "impl-demo-spec-1750000000-a1"})
        # 注入 admin_invoke 消费点可用（写失败静默降级，不阻断升级通道）
        self.engine._escalate_env_blocked(
            "demo-spec", ["port 8000 connection refused"], title="验证环境阻塞")

        entry = self.sm.read_one("demo-spec")
        # blocked + admin 升级语义保持
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("验证环境阻塞", str(entry.get("error") or ""))
        # infra 记账：预算退款 + 独立计数 + 轮次
        self.assertEqual(int(entry.get("_impl_run_budget_used")), 2)
        self.assertEqual(int(entry.get(INFRA_FAILURE_COUNT_FIELD, 0)), 1)
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0)), 1)
        # 闸门不累加
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0) or 0), 0)

    # ── 场景 2：对账不冲掉退款 ──────────────────────────────────

    def test_reconcile_does_not_overwrite_used_with_infra_exemption(self):
        """_infra_failure_count>0 且 _budget_exempt_runs==0（无归档）时跑
        _reconcile_impl_budget，used 不被 runs 计数回写（豁免生效）。"""
        self._make_testing_spec(used=2)
        self.sm.update_spec("demo-spec", {INFRA_FAILURE_COUNT_FIELD: 1})
        # 对账前：used=2 ≠ runs 正常收工数=0（无 run 产物）→ 若无豁免会改写
        self.engine._reconcile_impl_budget("demo-spec")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_impl_run_budget_used")), 2)

    # ── 场景 3：闸门不累加 ─────────────────────────────────────

    def test_consecutive_infra_rounds_do_not_accumulate_fail_rounds(self):
        """连续 4 轮 infra（provider 熔断）→ _verify_fail_rounds 保持 0，
        不触发 MAX_VERIFY_FAIL_ROUNDS 冻结；_verify_infra_rounds 独立累计。"""
        self._make_testing_spec(used=4)
        for i in range(1, 5):
            self._run_legacy_circuit_open(i)
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertNotEqual(entry["status"], "blocked")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0) or 0), 0)
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0) or 0), 4)

    # ── 场景 4：回拨（R3）──────────────────────────────────────

    def test_admin_reclassify_rolls_back_and_unfreezes(self):
        """历史 _verify_fail_rounds=3（闸门冻结）+ 台账 2 条 infra 轮 →
        admin 回拨 2 轮后 fail_rounds=1（低于阈值）且解冻。"""
        spec = "demo-spec"
        self._make_testing_spec()
        # 直接构造历史状态：升级闸门第 3 轮冻结（blocked，结构化非人工冻结）
        self.sm.update_spec(spec, {
            "_verify_fail_rounds": 3,
            "status": "blocked",
            "error": "升级闸门连续失败第 3 轮，已冻结等待人工裁决",
        })
        # 台账含 2 条 infra 轮（回拨参考；冻结清空台账的容错见 design R3——
        # 台账缺失不阻断回拨，此处构造台账以验证参考依据）
        self.engine._append_fail_history(
            spec, "infra", [], failure_class="infra", run_id="v-1")
        self.engine._append_fail_history(
            spec, "infra", [], failure_class="infra", run_id="v-2")

        result = self.engine.reclassify_infra_rounds(
            spec, 2, "audit: 2 infra rounds misclassified pre-policy", actor="test")
        self.assertTrue(result.get("ok"))

        entry = self.sm.read_one(spec)
        # fail_rounds 3→1（低于 MAX_VERIFY_FAIL_ROUNDS）
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0) or 0), 1)
        # 解冻：blocked → ready（无 branch 的实现阶段熔断复位路径）
        self.assertNotEqual(entry["status"], "blocked")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(entry.get("frozen"), False)
        self.assertIsNone(entry.get("error"))

        # 幂等：同一 audit_reason 重复回拨不二次扣减
        result2 = self.engine.reclassify_infra_rounds(
            spec, 2, "audit: 2 infra rounds misclassified pre-policy", actor="test")
        self.assertTrue(result2.get("ok"))
        self.assertEqual(result2.get("applied"), 0)
        entry2 = self.sm.read_one(spec)
        self.assertEqual(int(entry2.get("_verify_fail_rounds", 0) or 0), 1)

    def test_reclassify_below_threshold_no_unfreeze_needed(self):
        """fail_rounds=2（未达冻结阈值）回拨 1 → fail_rounds=1，状态不变。"""
        spec = "demo-spec"
        self._make_testing_spec()
        self.sm.update_spec(spec, {"_verify_fail_rounds": 2})
        result = self.engine.reclassify_infra_rounds(
            spec, 1, "audit: 1 infra round misclassified", actor="test")
        self.assertTrue(result.get("ok"))
        entry = self.sm.read_one(spec)
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0) or 0), 1)
        self.assertEqual(entry["status"], "testing")

    # ── 场景 5：D5 不回归 ──────────────────────────────────────

    def test_d5_unreadable_result_still_blocked_not_redispatch(self):
        """结果文件缺失（unreadable）→ 维持 fix-verdict-read-failclosed D5
        fail-closed（blocked + critical），**不**改为自动重排（不在 infra 域）。"""
        self._make_testing_spec()
        self.engine.agent_runner.run_verifier = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None,
                run_id="verify-demo-spec-1-a1",
            ))
        self.engine._run_legacy_verification("demo-spec")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("不可读", str(entry.get("error")))
        # 不自动重排：不回到 implemented/testing 自动重验
        self.assertNotEqual(entry["status"], "implemented")
        # unreadable 不在 infra 问题域：不计 infra（不豁免、不独立记账）
        self.assertEqual(int(entry.get(INFRA_FAILURE_COUNT_FIELD, 0) or 0), 0)
        self.assertEqual(int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0) or 0), 0)

    # ── 统一失败归因接口 enrich_failure_class（R1）──────────────

    def test_enrich_failure_class_triage(self):
        """三态归因：provider 熔断→infra；worktree 冲突→infra；普通失败→unknown
        （按 product 保守处置，不豁免）。"""
        v = self.engine._verification
        self.assertEqual(
            v.enrich_failure_class("demo-spec", _make_circuit_open_error()),
            "infra")
        self.assertEqual(
            v.enrich_failure_class(
                "demo-spec", "git worktree add failed: already exists"),
            "infra")
        self.assertEqual(
            v.enrich_failure_class(
                "demo-spec", "scenario s3 failed: button not rendered"),
            "unknown")
        # 空判据 → unknown（不误豁免）
        self.assertEqual(v.enrich_failure_class("demo-spec", ""), "unknown")

    def test_enrich_failure_class_stale_result_infra(self):
        """陈旧/异 spec 归属结果文件（复用 _verifier_result_is_stale）→ infra。"""
        spec = "demo-spec"
        now = int(time.time())
        result = SimpleNamespace(run_id=f"verify-{spec}-{now}-a1")
        result_path = (
            Path(self.tmpdir) / ".fenix" / "verify-progress" / spec
            / ".fenix-run-result.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        # 异 spec 戳：文件属其它 spec → foreign → infra
        result_path.write_text(json.dumps(
            {"spec": "other-spec", "status": "bug-found"}), encoding="utf-8")
        v = self.engine._verification
        self.assertEqual(
            v.enrich_failure_class(spec, "", result, result_path), "infra")

    def test_infra_refund_idempotent_same_run(self):
        """预算退款幂等：同一 run 两次 infra 判定只退款一次（避免重复扣减）。
        _infra_failure_count 按「去重后的 infra 失败轮」累计（同一轮重判不再 +1）。"""
        self._make_testing_spec(used=5)
        self.engine._record_infra_failure(
            "demo-spec", "infra", run_id="verify-demo-spec-9-a1")
        self.engine._record_infra_failure(
            "demo-spec", "infra", run_id="verify-demo-spec-9-a1")
        entry = self.sm.read_one("demo-spec")
        # 只退款一次：5→4
        self.assertEqual(int(entry.get("_impl_run_budget_used")), 4)
        # 同一实现 run 去重：infra 计数只 +1（第二次判定幂等跳过）
        self.assertEqual(int(entry.get(INFRA_FAILURE_COUNT_FIELD, 0) or 0), 1)
        # 退款 run 已入侧车（幂等锚点）
        refunded = json.loads(
            entry.get(INFRA_REFUNDED_RUN_IDS_FIELD) or "[]")
        self.assertIn("verify-demo-spec-9-a1", refunded)

    def test_admin_monitor_disposition_text_triggers_reclassify(self):
        """Administrator 处置文本声明「回拨 N 轮」→ _apply_infra_reclassification
        从 _verify_fail_rounds 减回并解冻（对齐 _apply_family_waiver 文本范式）。"""
        from core.admin_monitor import AdminMonitor
        from core.agent_runner import AdminDisposition
        spec = "demo-spec"
        self._make_testing_spec()
        self.sm.update_spec(spec, {
            "_verify_fail_rounds": 3,
            "status": "blocked",
            "error": "升级闸门连续失败第 3 轮，已冻结等待人工裁决",
        })
        mon = AdminMonitor(
            {"admin": {"enabled": True}},
            self.sm, self.tmpdir, self.logger,
            store=None, agent_runner=None, pm_engine=self.engine,
        )
        disp = AdminDisposition(
            run_id="admin-test-1", spec=spec, success=True,
            problem="验证失败根因：基础设施（tsc not found）",
            actions_taken="回拨 2 轮（infra 误计入 fail_rounds）",
            result="resolved",
            summary="诊断结论：基础设施失败；处置时间线：infra 回拨 2 轮；结果：已解决。",
        )
        mon._apply_infra_reclassification(
            {"signal_type": "verify_fail_escalation", "spec": spec}, disp)
        entry = self.sm.read_one(spec)
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0) or 0), 1)
        self.assertNotEqual(entry["status"], "blocked")
        # 审计留痕（admin_store DISPOSITION，reclassify 幂等锚点）
        from core.admin_store import AdminStore
        recs = AdminStore(self.tmpdir, self.logger).read_all()
        recl = [r for r in recs if r.get("signal_type") == "infra_reclassify"]
        self.assertEqual(len(recl), 1)

    def test_dashboard_reclassify_manual_entry(self):
        """dashboard/CLI 手动回拨入口（单测与人工触发共用）。"""
        from core.dashboard.data import reclassify_infra_rounds as dashboard_reclassify
        spec = "demo-spec"
        self._make_testing_spec()
        self.sm.update_spec(spec, {
            "_verify_fail_rounds": 3,
            "status": "blocked",
            "error": "升级闸门连续失败第 3 轮，已冻结等待人工裁决",
        })
        result = dashboard_reclassify(
            self.tmpdir, spec, 2, "manual audit: infra misclassified", actor="cli")
        self.assertTrue(result.get("ok"))
        entry = self.sm.read_one(spec)
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0) or 0), 1)
        self.assertNotEqual(entry["status"], "blocked")
        # spec 不存在 / 缺 audit_reason 拒绝
        self.assertFalse(dashboard_reclassify(self.tmpdir, "nope", 1, "x")["ok"])
        self.assertFalse(dashboard_reclassify(
            self.tmpdir, spec, 1, "")["ok"])

    def test_reclassify_only_subtracts(self):
        """回拨只做减法（product→infra 方向）：当前 fail_rounds=0 时回拨 2 → 0（不补计）。"""
        spec = "demo-spec"
        self._make_testing_spec()
        result = self.engine.reclassify_infra_rounds(
            spec, 2, "audit: over-subtract attempt", actor="test")
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("applied"), 0)
        entry = self.sm.read_one(spec)
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0) or 0), 0)


if __name__ == "__main__":
    unittest.main()