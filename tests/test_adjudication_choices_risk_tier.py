"""add-adjudication-auto-exec 1.3：裁决选项风险档位（risk_tier）测试。

覆盖（specs/adjudication-choices-registry/spec.md）：
- 每条选项携带合法档位（三档枚举之一；judge_rerun_cap 桶三选项档位为
  SPEC 钦定映射）；
- 缺档/脏档按最保守 terminal 兜底（choice_risk_tier 单点）；
- 档位声明不改变既有 resolve_choice 解析行为（桶内精确/not-in-bucket/
  scoped-no-reverse/unknown-choice/逐项拷贝）。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dashboard.data.adjudication_choices import (  # noqa: E402
    ADJUDICATION_CHOICES,
    RISK_TIERS,
    RISK_TIER_REVERSIBLE,
    RISK_TIER_STATE_ADVANCE,
    RISK_TIER_TERMINAL,
    choice_risk_tier,
    choices_for,
    resolve_choice,
)


class TestRiskTierDeclarations(unittest.TestCase):
    """每条选项携带合法档位（registry spec.md Scenario 1）。"""

    def test_every_choice_has_valid_tier(self):
        """注册表任意桶任一选项：risk_tier 字段存在且取值三档之一。"""
        seen = []
        for sig, choices in ADJUDICATION_CHOICES.items():
            for choice in choices:
                tier = choice.get("risk_tier")
                self.assertIn(
                    tier, RISK_TIERS,
                    f"桶 {sig} 选项 {choice.get('id')} 档位非法: {tier!r}",
                )
                seen.append((sig, choice["id"], tier))
        # 非空注册表（结构卫队，防上游重构清空后测试空转自证）
        self.assertTrue(seen)

    def test_judge_rerun_cap_bucket_specced_mapping(self):
        """judge_rerun_cap 桶档位为 SPEC 钦定映射（reversible/advance/terminal）。"""
        tiers = {
            c["id"]: choice_risk_tier(c) for c in choices_for("judge_rerun_cap")
        }
        self.assertEqual(
            tiers,
            {
                "manual_fixed_reverify": RISK_TIER_REVERSIBLE,
                "force_advance": RISK_TIER_STATE_ADVANCE,
                "abandon": RISK_TIER_TERMINAL,
            },
        )

    def test_shared_id_tier_consistent_across_buckets(self):
        """同一 id 跨桶档位一致（import 期 _assert_registry_consistency 已
        fail-fast 钉死；此处显式断言双保险）。"""
        by_id: dict = {}
        for sig, choices in ADJUDICATION_CHOICES.items():
            for choice in choices:
                tier = choice_risk_tier(choice)
                prev = by_id.setdefault(choice["id"], tier)
                self.assertEqual(
                    prev, tier,
                    f"choice {choice['id']} 跨桶档位漂移: {prev} vs {tier}",
                )

    def test_reset_family_is_reversible_advance_family_is_not(self):
        """分档语义抽查：reset 族可自动执行，豁免/闸门/冻结类不自动执行。"""
        for cid in ("continue_auto_fix", "manual_fixed_reverify",
                    "retry_review", "revise_reproposal"):
            found = [
                choice_risk_tier(c)
                for choices in ADJUDICATION_CHOICES.values()
                for c in choices if c["id"] == cid
            ]
            self.assertTrue(found, f"{cid} 应注册于至少一个桶")
            for tier in found:
                self.assertEqual(tier, RISK_TIER_REVERSIBLE, cid)
        for cid in ("grant_env_exemption", "skip_review_gate",
                    "freeze_stop_loss", "open_config",
                    "declare_no_artifacts", "commit_stray_wip"):
            found = [
                choice_risk_tier(c)
                for choices in ADJUDICATION_CHOICES.values()
                for c in choices if c["id"] == cid
            ]
            self.assertTrue(found, f"{cid} 应注册于至少一个桶")
            for tier in found:
                self.assertNotEqual(tier, RISK_TIER_REVERSIBLE, cid)


class TestRiskTierFallback(unittest.TestCase):
    """缺档保守兜底（registry spec.md Scenario 2）：terminal 兜底单点。"""

    def test_missing_tier_falls_back_terminal(self):
        """未声明 risk_tier 的条目（历史/笔误）按 terminal 兜底。"""
        self.assertEqual(choice_risk_tier({"id": "legacy"}), RISK_TIER_TERMINAL)
        self.assertEqual(choice_risk_tier({}), RISK_TIER_TERMINAL)
        self.assertEqual(choice_risk_tier(None), RISK_TIER_TERMINAL)

    def test_dirty_tier_falls_back_terminal(self):
        """枚举外脏值（拼写错/大小写变体）同样 terminal 兜底，不臆造档位。"""
        self.assertEqual(choice_risk_tier({"risk_tier": "reversible"}), RISK_TIER_TERMINAL)
        self.assertEqual(choice_risk_tier({"risk_tier": "Reversible-Experiment"}), RISK_TIER_TERMINAL)
        self.assertEqual(choice_risk_tier({"risk_tier": 123}), RISK_TIER_TERMINAL)

    def test_resolve_choice_carries_declared_tier(self):
        """解析结果逐项拷贝携带档位字段（策略引擎经 resolve_choice 单源取档）。"""
        choice, reason = resolve_choice("manual_fixed_reverify", "judge_rerun_cap")
        self.assertEqual(reason, "")
        self.assertEqual(choice_risk_tier(choice), RISK_TIER_REVERSIBLE)


class TestResolveBehaviorUnchanged(unittest.TestCase):
    """档位声明不改变既有解析行为（registry spec.md Scenario 3）。"""

    def test_bucket_exact_match_and_copy_semantics(self):
        """桶内精确命中返回逐项拷贝（就地改写不污染注册表）。"""
        choice, reason = resolve_choice("force_advance", "judge_rerun_cap")
        self.assertEqual(reason, "")
        self.assertEqual(choice["action"], "force_advance")
        choice["risk_tier"] = "tampered"
        original = next(
            c for c in ADJUDICATION_CHOICES["judge_rerun_cap"]
            if c["id"] == "force_advance"
        )
        self.assertEqual(original["risk_tier"], RISK_TIER_STATE_ADVANCE)

    def test_not_in_bucket_no_cross_signal(self):
        """注册桶内未命中 → not-in-bucket（不跨信号放行）。"""
        choice, reason = resolve_choice("retry_review", "judge_rerun_cap")
        self.assertIsNone(choice)
        self.assertEqual(reason, "not-in-bucket")

    def test_scoped_no_reverse_on_unregistered(self):
        """未注册 signal_type 的 spec_scoped 动作反查收紧拒绝。"""
        choice, reason = resolve_choice("manual_fixed_reverify", "unregistered_sig")
        self.assertIsNone(choice)
        self.assertEqual(reason, "scoped-no-reverse")

    def test_unknown_choice(self):
        """全表无此 id → unknown-choice（须搭配未注册 signal_type）。"""
        choice, reason = resolve_choice("no_such_choice", "no_such_bucket")
        self.assertIsNone(choice)
        self.assertEqual(reason, "unknown-choice")

    def test_unregistered_signal_empty_choices(self):
        """未注册 signal_type 查询返回空选项集，不抛异常。"""
        self.assertEqual(choices_for("no_such_bucket"), ())
        self.assertEqual(choices_for(None), ())


if __name__ == "__main__":
    unittest.main()
