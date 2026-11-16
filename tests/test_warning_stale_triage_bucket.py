"""evo-register-warning-stale-triage-bucket：warning_stale_triage 裁决桶测试。

tasks 2.1-2.3 覆盖面：
- 2.1 桶内选项集（choices_for 含 ack_triage / revise_scenario_reverify，
  后者 requires_payload=true）与链上白名单（choices_for_admin_chain 两项
  均在，不被人类拍板面专属排除集过滤）；
- 2.2 发射点告警携带 choices（经 FamilyGovernor._send_human_escalation_alert
  中心接线落盘）与 resolve_choice 桶内精确命中 / 未注册信号 scoped-no-reverse
  回退守卫不回退；
- 2.3 链上越界归因两形态：未注册信号（空集=注册缺口）写「信号未注册裁决
  桶」，已注册信号（空集=权限边界）仍写「人类拍板面专属」；拒绝语义不变
  （不执行、转单 Arbiter、不计失败）。
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.dashboard.data.adjudication_choices import (
    choices_for,
    choices_for_admin_chain,
    resolve_choice,
)
from core.pm_engine.escalation_chain import ChainQuotaStore, reset_chain
from tests.helpers import FakeLogger
from tests.test_escalation_chain import (
    _disp,
    _drain_chain,
    _FakeArbiterLane,
    _FakePm,
)


# ── 2.1 桶内选项集与链上白名单 ──────────────────────────────────────────


class TestBucketChoices:
    def test_bucket_contains_both_choices(self):
        cs = {c["id"]: c for c in choices_for("warning_stale_triage")}
        assert set(cs) == {"ack_triage", "revise_scenario_reverify"}, (
            f"warning_stale_triage 桶选项集漂移: {set(cs)}"
        )

    def test_ack_triage_shape(self):
        c = next(c for c in choices_for("warning_stale_triage")
                 if c["id"] == "ack_triage")
        # 留痕收口语义：复用 ack_self_heal 执行分支（执行器零改动）、不触
        # 状态机（spec_scoped=true 锚定具体 spec）、可逆自限档
        assert c["action"] == "ack_self_heal"
        assert c["spec_scoped"] is True
        assert c["risk_tier"] == "reversible-experiment"

    def test_revise_scenario_reverify_reference_with_payload_gate(self):
        c = next(c for c in choices_for("warning_stale_triage")
                 if c["id"] == "revise_scenario_reverify")
        assert c["requires_payload"] is True
        # 按引用复用单源常量：与 inconclusive_loop 桶逐项相等
        base = next(c for c in choices_for("inconclusive_loop")
                    if c["id"] == "revise_scenario_reverify")
        assert c == base

    def test_admin_chain_whitelist_contains_both(self):
        # 两项均不被 ADMIN_CHAIN_EXCLUDED_CHOICE_IDS 过滤——链上 Admin 对该
        # 信号有非空拍板面（缺桶时代的空白名单即本案结构性缺口）
        ids = {c["id"] for c in choices_for_admin_chain("warning_stale_triage")}
        assert {"ack_triage", "revise_scenario_reverify"} <= ids


# ── 2.2 发射点告警携带 choices 与 resolve_choice 解析 ────────────────────


class TestEmissionAndResolve:
    def test_alert_carries_choices(self, tmp_path):
        """经 family 咽喉发出该信号：落盘告警含 choices 注册表快照。"""
        from core.admin_store import ESCALATION, AdminStore
        from core.pm_engine.family import FamilyGovernor

        proot = tmp_path / "proj-triage"
        (proot / ".fenix").mkdir(parents=True)
        gov = FamilyGovernor.__new__(FamilyGovernor)
        gov._pm = SimpleNamespace(project_root=proot, logger=FakeLogger())
        gov._send_human_escalation_alert(
            "spec-a", "warning_stale_triage", "critical",
            "场景连续 2 轮 warning 需 triage", "evidence", "人工复核",
        )

        recs = [r for r in AdminStore(proot, FakeLogger()).read_all()
                if r.get("signal_type") == "warning_stale_triage"]
        assert recs, "告警未落盘"
        rec = recs[0]
        assert rec["kind"] == ESCALATION
        assert rec.get("choices") == list(choices_for("warning_stale_triage"))
        assert {c["id"] for c in rec["choices"]} == {
            "ack_triage", "revise_scenario_reverify",
        }

    def test_resolve_choice_bucket_hit(self):
        choice, reason = resolve_choice(
            "revise_scenario_reverify", "warning_stale_triage")
        assert reason == ""
        assert choice is not None and choice["requires_payload"] is True

    def test_unregistered_signal_scoped_no_reverse_unchanged(self):
        # 同一 choice 对未注册信号仍 scoped-no-reverse（守卫不回退）
        assert resolve_choice(
            "revise_scenario_reverify", "daemon_errors"
        ) == (None, "scoped-no-reverse")


# ── 2.3 链上越界归因两形态 ──────────────────────────────────────────────


class TestChainOutOfBucketAttribution(unittest.TestCase):
    """链越界复核归因文案：复用 test_escalation_chain 链级 harness（Admin
    派发缝脚本化终态、Arbiter 车道缝咽件），断言收敛在 chain-handoff 的
    handoff_reason 文案与拒绝语义（不执行 / 不计失败）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )
        reset_chain()
        from core.state_machine import StateMachine
        from core.pm_engine.escalation_chain import EscalationChain

        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": False})
        self.chain = EscalationChain(self.tmp, MagicMock())
        self.chain.set_runner(MagicMock())
        self.chain.set_state_machine(sm)
        self.pm = _FakePm(self.tmp)
        self.chain.set_pm(self.pm)
        self.lane = _FakeArbiterLane(self.tmp)
        self._lane_patcher = patch(
            "core.pm_engine.arbiter.get_lane", lambda *a, **k: self.lane
        )
        self._lane_patcher.start()

    def tearDown(self):
        self._lane_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    def _submit_and_drain(self, signal_type, script):
        self.chain._dispatch_admin = lambda item: (
            script.pop(0) if script else _disp()
        )
        self.lane.outcomes = ["escalated"]
        assert self.chain.submit_entry(
            spec="spec-a", signal_type=signal_type, severity="major",
            description="d", evidence="e", recommended_action="r",
            source="triage-bucket-test",
        ) == "queued"
        assert _drain_chain(self.chain)

    def _handoff_reasons(self):
        from core.pm_engine.arbiter import load_arbiter_ledger

        return [
            str(r.get("handoff_reason") or "")
            for r in load_arbiter_ledger(self.tmp)
            if r.get("kind") == "chain-handoff"
        ]

    def test_unregistered_signal_attribution_registry_gap(self):
        # 未注册信号（daemon_errors 不在注册表）：越界归因写注册缺口形态
        script = [_disp(
            run_id="adm-u", result="resolved", success=True,
            status_after="ready", choice_id="ack_triage",
        )]
        self._submit_and_drain("daemon_errors", script)

        reasons = self._handoff_reasons()
        assert reasons and "信号未注册裁决桶: ack_triage" in reasons[0], (
            f"未注册信号越界归因漂移: {reasons}"
        )
        assert "人类拍板面专属" not in reasons[0]
        # 拒绝语义不变：不执行、转单 Arbiter、不计失败
        assert len(self.lane.calls) == 1
        assert ChainQuotaStore(self.tmp).admin_attempts(
            "spec-a::daemon_errors") == 0

    def test_registered_signal_attribution_human_exclusive(self):
        # 已注册信号（warning_stale_triage）× 人类专属 choice（abandon）：
        # 越界归因保持权限边界形态
        script = [_disp(
            run_id="adm-r", result="resolved", success=True,
            status_after="ready", choice_id="abandon",
        )]
        self._submit_and_drain("warning_stale_triage", script)

        reasons = self._handoff_reasons()
        assert reasons and (
            "人类拍板面专属" in reasons[0] and "abandon" in reasons[0]
        ), f"已注册信号越界归因漂移: {reasons}"
        assert "信号未注册裁决桶" not in reasons[0]
        assert len(self.lane.calls) == 1
        assert ChainQuotaStore(self.tmp).admin_attempts(
            "spec-a::warning_stale_triage") == 0
