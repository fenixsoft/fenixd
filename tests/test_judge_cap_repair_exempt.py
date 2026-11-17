"""evo-judge-rerun-cap-repair-exempt：judge 重跑硬上限的修复推进豁免。

覆盖三组行为：

1. 豁免放行与封顶（1.2/1.3）：修复申报受理置一次性豁免旗标（未达封顶、
   受理非拒收）；派发门超上限消费豁免放行（常规分支 + 预算近满压缩分支
   各一例——旗标消费、主计数照常累计、不写 judge_rerun_cap 冻结）；封顶
   （生命周期消费计数达 JUDGE_CAP_EXEMPT_MAX）后受理不再置旗标、超上限
   即走既有 hard cap 冻结。
2. 清零链回归（1.1/1.4/1.5）：verified 落定 / 人工 unfreeze_spec / admin
   手动清零三处终态清零点成对清零两新字段。
3. 冻结 evidence 失败集轨迹（2.1）：verdict_stability 侧车在位 → evidence
   含轮内 failed_ids 序列（侧车至多两轮）；侧车缺失 → 降级省略、冻结不受阻。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine.verification.judge_gate import (
    _JUDGE_CONSERVE_REMAINING,
    _MAX_JUDGE_RERUNS,
    _consume_judge_cap_repair_exempt,
    _judge_dispatch_gate,
    _judge_hard_cap_freeze,
)
from core.pm_engine.verification.pipeline import _record_repair_claim
from core.state_machine import (
    JUDGE_CAP_EXEMPT_MAX,
    JUDGE_CAP_EXEMPT_USED_FIELD,
    JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD,
    StateMachine,
)
from core.verify_report import write_verdict_stability


def make_state(proot: Path, spec: str) -> StateMachine:
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
    sm.add_spec(spec, {"priority": 5, "status": "implementing"})
    return sm


def make_pipeline(proot: Path, sm: StateMachine, config_map=None):
    """VerificationPipeline 最小装配（test_token_budget_escalation 同款范式）。"""
    from core.pm_engine.verification import VerificationPipeline

    pipeline = VerificationPipeline.__new__(VerificationPipeline)
    cfg = dict(config_map or {})
    ctx = SimpleNamespace(
        project_root=proot,
        logger=MagicMock(),
        state_machine=sm,
        config_reader=lambda key, default=None: cfg.get(key, default),
        escalation_notifier=MagicMock(),
    )
    pipeline._pm = ctx
    pipeline._context = ctx
    return pipeline


def _flag_true(sm: StateMachine, spec: str) -> bool:
    entry = sm.read_one(spec) or {}
    return str(entry.get(JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD) or "").strip().lower() in (
        "true",
        "1",
    )


def _used_count(sm: StateMachine, spec: str) -> int:
    entry = sm.read_one(spec) or {}
    try:
        return int(entry.get(JUDGE_CAP_EXEMPT_USED_FIELD, 0) or 0)
    except (TypeError, ValueError):
        return 0


# ════════════════ 1.2：受理置旗标（未达封顶 / 拒收不置） ════════════════

class TestRepairClaimSetsExemptFlag:
    """受理写点：rejected=False 且消费计数未达封顶 → 同一受理原子写置旗标。"""

    def test_acceptance_sets_flag_when_under_cap(self, tmp_path):
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-claim")
        pipeline = make_pipeline(proot, sm)

        _record_repair_claim(pipeline, "spec-claim", rejected=False)

        assert _flag_true(sm, "spec-claim") is True
        entry = sm.read_one("spec-claim")
        assert int(entry.get("_judge_repair_claim_rounds") or 0) == 1
        assert _used_count(sm, "spec-claim") == 0  # 置位不消费

    def test_rejection_does_not_set_flag(self, tmp_path):
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-rej")
        pipeline = make_pipeline(proot, sm)

        _record_repair_claim(pipeline, "spec-rej", rejected=True)

        assert _flag_true(sm, "spec-rej") is False
        entry = sm.read_one("spec-rej")
        # 拒收轮照常计申报轮数（既有语义），仅旗标不置
        assert int(entry.get("_judge_repair_claim_rounds") or 0) == 1
        assert int(entry.get("_judge_repair_rejected_rounds") or 0) == 1

    def test_cap_reached_no_flag_but_claims_still_counted(self, tmp_path):
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-cap")
        sm.update_spec("spec-cap", {JUDGE_CAP_EXEMPT_USED_FIELD: JUDGE_CAP_EXEMPT_MAX})
        pipeline = make_pipeline(proot, sm)

        _record_repair_claim(pipeline, "spec-cap", rejected=False)

        assert _flag_true(sm, "spec-cap") is False
        entry = sm.read_one("spec-cap")
        # 申报记账照常（受理事实不受封顶影响），仅豁免额度不再发放
        assert int(entry.get("_judge_repair_claim_rounds") or 0) == 1
        assert _used_count(sm, "spec-cap") == JUDGE_CAP_EXEMPT_MAX

    def test_dirty_used_value_falls_back_to_zero_and_sets(self, tmp_path):
        """脏值消费计数按 0 兜底 → 置旗标（与 judge_gate 取数同防御口径）。"""
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-dirty")
        sm.update_spec("spec-dirty", {JUDGE_CAP_EXEMPT_USED_FIELD: "garbage"})
        pipeline = make_pipeline(proot, sm)

        _record_repair_claim(pipeline, "spec-dirty", rejected=False)

        assert _flag_true(sm, "spec-dirty") is True


# ════════════════ 1.3：派发门豁免消费（常规 / 预算近满压缩） ════════════════

class TestDispatchGateExemptRelease:
    """超上限判定为真且旗标在位 → 消费豁免放行；主计数照常累计、不冻结。"""

    def test_normal_branch_release_at_cap_plus_one(self, tmp_path):
        """count 达 5 + 受理置旗标 → 下一轮派发放行、旗标消费、计数累计 6。"""
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-rel")
        sm.update_spec("spec-rel", {
            "_judge_rerun_count": _MAX_JUDGE_RERUNS,
            JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD: True,
        })
        pipeline = make_pipeline(proot, sm)

        r = _judge_dispatch_gate(pipeline, "spec-rel")

        assert r is None  # 放行（report.json 未落盘 → 无可治理判定上下文放行）
        entry = sm.read_one("spec-rel")
        # 主计数照常累计（豁免轮预算照烧，不回退）
        assert int(entry.get("_judge_rerun_count") or 0) == _MAX_JUDGE_RERUNS + 1
        # 旗标消费即清、消费计数 +1
        assert _flag_true(sm, "spec-rel") is False
        assert _used_count(sm, "spec-rel") == 1
        # 不写 judge_rerun_cap 冻结
        assert not entry.get("_judge_cap_frozen")
        assert not (entry.get("error") or "")
        pipeline._context.escalation_notifier.assert_not_called()

    def test_normal_branch_freezes_when_flag_absent(self, tmp_path):
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-frz")
        sm.update_spec("spec-frz", {"_judge_rerun_count": _MAX_JUDGE_RERUNS})
        pipeline = make_pipeline(proot, sm)

        r = _judge_dispatch_gate(pipeline, "spec-frz")

        assert r is False
        entry = sm.read_one("spec-frz")
        assert entry["_judge_cap_frozen"] is True
        assert "judge 重跑超上限" in str(entry.get("error") or "")

    def test_flag_not_consumed_when_count_under_cap(self, tmp_path):
        """判定短路：count ≤ 上限时旗标保留（不提前消费）。"""
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-under")
        sm.update_spec("spec-under", {
            "_judge_rerun_count": _MAX_JUDGE_RERUNS - 1,
            JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD: True,
        })
        pipeline = make_pipeline(proot, sm)

        r = _judge_dispatch_gate(pipeline, "spec-under")

        assert r is None
        assert _flag_true(sm, "spec-under") is True
        assert _used_count(sm, "spec-under") == 0
        assert int(sm.read_one("spec-under").get("_judge_rerun_count") or 0) == _MAX_JUDGE_RERUNS

    def test_conserve_branch_release_and_next_freeze(self, tmp_path):
        """预算近满压缩分支：越限首轮消费豁免放行（文案不触发），下一轮冻结。"""
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-cs", )
        sm.update_spec("spec-cs", {
            "_tokens_in": 49_000_000,
            "_tokens_out": 0,
            "_judge_rerun_count": 1,
            JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD: True,
        })
        cfg = {
            "agents.token_budget_millions": 50,
            "agents.token_conserve_ratio": 0.95,
        }
        pipeline = make_pipeline(proot, sm, cfg)

        # 第 1 次：count=2 ≤ 基线(1)+1 → 常规放行，旗标保留
        r1 = _judge_dispatch_gate(pipeline, "spec-cs")
        assert r1 is None
        assert _flag_true(sm, "spec-cs") is True

        # 第 2 次：count=3 > 基线+1 → 消费豁免放行（不冻结）
        r2 = _judge_dispatch_gate(pipeline, "spec-cs")
        assert r2 is None
        entry = sm.read_one("spec-cs")
        assert _flag_true(sm, "spec-cs") is False
        assert _used_count(sm, "spec-cs") == 1
        assert not entry.get("_judge_cap_frozen")
        assert int(entry.get("_judge_rerun_count") or 0) == 3  # 主计数不回退

        # 第 3 次：count=4 > 基线+1、旗标已消费 → 既有预算近满冻结
        r3 = _judge_dispatch_gate(pipeline, "spec-cs")
        assert r3 is False
        entry = sm.read_one("spec-cs")
        assert entry["_judge_cap_frozen"] is True
        assert "预算近满" in str(entry.get("error") or "")

    def test_consume_helper_returns_false_without_flag(self, tmp_path):
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-noflag")
        pipeline = make_pipeline(proot, sm)

        assert _consume_judge_cap_repair_exempt(pipeline, "spec-noflag") is False
        assert _used_count(sm, "spec-noflag") == 0

    def test_consume_helper_persists_across_reparse(self, tmp_path):
        """消费记账经 STATE.md 往返可读（旗标 False 不串行化成 truthy）。"""
        proot = tmp_path / "proj"
        sm = make_state(proot, "spec-persist")
        sm.update_spec("spec-persist", {JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD: True})
        pipeline = make_pipeline(proot, sm)

        assert _consume_judge_cap_repair_exempt(pipeline, "spec-persist") is True

        # 重建 StateMachine（模拟进程重启后的磁盘重读）
        sm2 = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        entry = sm2.read_one("spec-persist")
        assert entry.get(JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD) is False
        assert int(entry.get(JUDGE_CAP_EXEMPT_USED_FIELD) or 0) == 1


# ════════════════ 1.1/1.4/1.5：三处终态清零点成对清除 ════════════════

class TestExemptClearPoints:
    """verified 落定 / unfreeze_spec / admin 手动清零三处成对清零两新字段。"""

    SEED = {
        JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD: True,
        JUDGE_CAP_EXEMPT_USED_FIELD: 2,
    }

    def _setup(self, tmp_path, spec):
        proot = tmp_path / "proj"
        sm = make_state(proot, spec)
        sm.update_spec(spec, dict(self.SEED))
        return proot, sm

    def test_verified_clears_both_fields(self, tmp_path):
        from core.pm_engine.verification.verdict_evidence import _record_verdict_adoption

        proot, sm = self._setup(tmp_path, "spec-verified")
        pipeline = make_pipeline(proot, sm)
        with patch("core.verify_report.record_verdict_round"), \
                patch("core.verify_report.verdict_failed_ids", return_value=[]), \
                patch("core.verify_report._sum_verify_chain_tokens", return_value=None):
            _record_verdict_adoption(pipeline, "spec-verified", "verified", report={})

        entry = sm.read_one("spec-verified")
        assert entry.get(JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD) is False
        assert int(entry.get(JUDGE_CAP_EXEMPT_USED_FIELD) or 0) == 0

    def test_unfreeze_clears_both_fields(self, tmp_path):
        proot, sm = self._setup(tmp_path, "spec-unfz")

        sm.unfreeze_spec("spec-unfz")

        entry = sm.read_one("spec-unfz")
        assert entry.get(JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD) is False
        assert int(entry.get(JUDGE_CAP_EXEMPT_USED_FIELD) or 0) == 0

    def test_admin_reset_clears_both_fields(self, tmp_path):
        from core.dashboard.data.admin_actions import reset_verification

        proot, sm = self._setup(tmp_path, "spec-admin")
        # 冻结为 judge_rerun_cap 验证链信号（reset_verification 仅对
        # 验证链冻结/blocked 开放）
        sm.freeze_for_human(
            "spec-admin",
            error="judge 重跑超上限（6/5 轮）— 已冻结",
            signal_type="judge_rerun_cap",
            severity="major",
            description="'spec-admin' judge 重跑超上限，已冻结等待人工裁决",
            evidence="spec=spec-admin; judge_rerun_count=6",
            recommended_action="检查验证为何反复重跑 judge",
            alert_callback=MagicMock(),
            extra_updates={"_judge_cap_frozen": True},
        )

        result = reset_verification(proot, "spec-admin", signal_type="judge_rerun_cap")

        assert result.get("ok") is True, result
        entry = sm.read_one("spec-admin")
        assert entry.get(JUDGE_CAP_REPAIR_EXEMPT_AVAIL_FIELD) is False
        assert int(entry.get(JUDGE_CAP_EXEMPT_USED_FIELD) or 0) == 0


# ════════════════ 2.1：冻结 evidence 附失败集轨迹 ════════════════

class TestFreezeEvidenceFailTrajectory:
    """_judge_hard_cap_freeze evidence 追加 verdict_stability 轮内 failed_ids
    序列；侧车缺失降级省略、不阻塞冻结主路径。"""

    def _setup(self, tmp_path, spec):
        proot = tmp_path / "proj"
        sm = make_state(proot, spec)
        pipeline = make_pipeline(proot, sm)
        freeze = MagicMock()
        sm.freeze_for_human = freeze
        return proot, sm, pipeline, freeze

    def test_evidence_contains_failed_ids_trajectory(self, tmp_path):
        proot, sm, pipeline, freeze = self._setup(tmp_path, "spec-traj")
        # 侧车两轮（侧车保留最近两轮的上限形态）：失败集从 3 收缩到 1
        write_verdict_stability(proot, "spec-traj", {
            "rounds": [
                {"status": "bug-found", "failed_ids": ["s1", "s2", "s3"],
                 "at": "2026-11-17T10:00:00+00:00"},
                {"status": "bug-found", "failed_ids": ["s3"],
                 "at": "2026-11-17T11:00:00+00:00"},
            ],
        })

        _judge_hard_cap_freeze(pipeline, "spec-traj", 6)

        assert freeze.called
        evidence = str(freeze.call_args.kwargs.get("evidence"))
        assert "失败集轨迹" in evidence
        assert "s1,s2,s3" in evidence
        assert "failed=3" in evidence
        assert "failed=1" in evidence
        assert "[s3]" in evidence
        # 冻结语义不变：blocked + 冻结旗标 + judge_rerun_cap 信号
        kwargs = freeze.call_args.kwargs
        assert kwargs.get("signal_type") == "judge_rerun_cap"
        assert kwargs.get("extra_updates") == {"_judge_cap_frozen": True}

    def test_evidence_omits_trajectory_without_sidecar(self, tmp_path):
        """侧车缺失：该段降级省略，冻结照常落盘（不报错、不阻塞）。"""
        proot, sm, pipeline, freeze = self._setup(tmp_path, "spec-noside")

        _judge_hard_cap_freeze(pipeline, "spec-noside", 6)

        assert freeze.called
        evidence = str(freeze.call_args.kwargs.get("evidence"))
        assert "失败集轨迹" not in evidence
        assert "judge_rerun_count=6" in evidence

    def test_corrupt_sidecar_degrades_gracefully(self, tmp_path):
        """侧车损坏：fail-open 省略轨迹段，冻结不受阻。"""
        proot, sm, pipeline, freeze = self._setup(tmp_path, "spec-corrupt")
        sidecar = proot / ".fenix" / "verify-progress" / "spec-corrupt"
        sidecar.mkdir(parents=True, exist_ok=True)
        (sidecar / "verdict_stability.json").write_text("{not-json", encoding="utf-8")

        _judge_hard_cap_freeze(pipeline, "spec-corrupt", 6)

        assert freeze.called
        assert "失败集轨迹" not in str(freeze.call_args.kwargs.get("evidence"))
