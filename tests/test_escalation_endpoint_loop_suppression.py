"""evo-escalation-endpoint-loop-suppression：链终点件自环回派抑制。

覆盖 tasks 1.1 / 2.1 / 3.1 判定面：
- 咽喉守卫（family.py 直派段）：链终点上升件（chain_context 非空）落库后
  零 ``submit_for_alert`` 调用（自环守卫），抑制日志含签名与 alert id；
- 回落兜底件不受影响：链队列满回落（submit_entry RuntimeError →
  chain_context=None 落既有路径）照常直派 Arbiter；
- 入口第二道防线（arbiter.py ``submit_for_alert``）：entry 含 chain 字段即
  短路返回否定哨兵 ``"excluded"``、零 ``submit_trigger`` 调用；无 chain
  字段的既有透传形态不受影响。

测试全程不触网、不真调网关；链头派发缝以 monkeypatch 密闭。
"""

import types
from pathlib import Path

import pytest

from core.admin_store import AdminStore, ESCALATION


# ── 夹具助手 ────────────────────────────────────────────

class FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, component, message, context=None):
        self.records.append(("info", component, message))

    def warning(self, component, message, context=None):
        self.records.append(("warning", component, message))

    def error(self, component, message, context=None):
        self.records.append(("error", component, message))


CHAIN_CONTEXT = {
    "chain_id": "chain-1",
    "signature": "spec-a::verify_env_blocked",
    "granularity": "spec",
    "endpoint_kind": "arbiter-escalated",
    "endpoint_reason": "Arbiter 处置失败",
    "arbiter_rulings": 3,
}


def _make_governor(tmp_path: Path):
    """真咽喉 FamilyGovernor（__new__ 装配，test_arbiter_guardrails 同款）。"""
    from core.pm_engine.family import FamilyGovernor

    logger = FakeLogger()
    gov = FamilyGovernor.__new__(FamilyGovernor)
    gov._pm = types.SimpleNamespace(project_root=tmp_path, logger=logger)
    return gov, logger


def _escalation_entries(tmp_path: Path):
    return [r for r in AdminStore(tmp_path).read_all()
            if r.get("kind") == ESCALATION]


# ── 1.1 咽喉守卫：链终点件零回派 ────────────────────────

class TestThroatGuardEndpointItem:
    def test_endpoint_item_never_resubmits(self, tmp_path, monkeypatch):
        """链终点件走完 _send_human_escalation_alert 全流程：告警落库（含
        全链痕迹）但零 submit_for_alert 调用，抑制日志含签名与 alert id。"""
        from core.pm_engine import family as family_mod

        gov, logger = _make_governor(tmp_path)
        lane_calls = []
        fake_lane = types.SimpleNamespace(
            submit_for_alert=lambda pm, entry, alert_id: (
                lane_calls.append((entry, alert_id)) or "queued"
            )
        )
        # 两个派发缝全开（lane 可用 ∧ 让位判定 True）：守卫前形态下本件
        # 必直派自环，守卫后 MUST 零调用。
        monkeypatch.setattr(family_mod, "yielded_to_arbiter",
                            lambda sig, ctx: True)
        monkeypatch.setattr("core.pm_engine.arbiter.get_lane",
                            lambda root, logger: fake_lane)

        gov._send_human_escalation_alert(
            "spec-a", "verify_env_blocked", "major",
            "验证环境阻塞", "env log", "修复环境",
            chain_context=dict(CHAIN_CONTEXT),
        )

        entries = _escalation_entries(tmp_path)
        assert len(entries) == 1, "链终点件 MUST 落人工裁决面（唯一落盘）"
        assert entries[0]["chain"]["signature"] == \
            CHAIN_CONTEXT["signature"], "全链痕迹随件落盘（人工可还原处置史）"
        assert lane_calls == [], \
            "链终点件 MUST NOT 触发 submit_for_alert（自环守卫）"
        info_msgs = [m for lvl, _, m in logger.records if lvl == "info"]
        assert any(
            "抑制" in m and CHAIN_CONTEXT["signature"] in m
            and entries[0]["id"] in m
            for m in info_msgs
        ), f"抑制日志 MUST 含签名与 alert id: {info_msgs}"

    def test_endpoint_alert_no_arbiter_log_suffix(self, tmp_path, monkeypatch):
        """链终点件的收尾告警日志不渲染 arbiter 回派结果（dispatched 恒
        None → 词表静默，排障面不出现误导性回派痕迹）。"""
        from core.pm_engine import family as family_mod

        gov, logger = _make_governor(tmp_path)
        monkeypatch.setattr(family_mod, "yielded_to_arbiter",
                            lambda sig, ctx: True)
        monkeypatch.setattr(
            "core.pm_engine.arbiter.get_lane",
            lambda root, logger: types.SimpleNamespace(
                submit_for_alert=lambda *a, **k: "queued"),
        )

        gov._send_human_escalation_alert(
            "spec-a", "verify_env_blocked", "major", "d", "e", "r",
            chain_context=dict(CHAIN_CONTEXT),
        )

        warn_msgs = [m for lvl, _, m in logger.records if lvl == "warning"]
        final = [m for m in warn_msgs if m.startswith("human-escalation-alert")]
        assert final and all("arbiter:" not in m for m in final), \
            f"链终点件收尾日志 MUST 零 arbiter 回派后缀: {final}"


# ── 1.1 不误伤：链队列满回落兜底件照常直派 ──────────────

class TestQueueFullFallbackUnaffected:
    def test_queue_full_fallback_still_dispatches(self, tmp_path, monkeypatch):
        """链队列满（submit_entry RuntimeError）回落为兜底直派件
        （chain_context=None、entry 无 chain 字段）：既有直派逻辑照常。"""
        from core.pm_engine import family as family_mod

        gov, _ = _make_governor(tmp_path)

        class _FullChain:
            # 显式 keyword-only 签名对齐生产 EscalationChain.submit_entry
            # （test-double-fidelity 守卫：替身不得以 **kwargs 吸收参数）。
            def submit_entry(
                self, *, spec, signal_type, severity="major",
                description="", evidence="", recommended_action="",
                trigger=None, payload=None, source="",
            ):
                raise RuntimeError("处置链队列已满")

        lane_calls = []
        fake_lane = types.SimpleNamespace(
            submit_for_alert=lambda pm, entry, alert_id: (
                lane_calls.append((entry, alert_id)) or "queued"
            )
        )
        monkeypatch.setattr("core.pm_engine.escalation_chain.get_chain",
                            lambda *a, **k: _FullChain())
        monkeypatch.setattr(family_mod, "yielded_to_arbiter",
                            lambda sig, ctx: True)
        monkeypatch.setattr("core.pm_engine.arbiter.get_lane",
                            lambda root, logger: fake_lane)

        gov._send_human_escalation_alert(
            "spec-a", "verify_env_blocked", "major",
            "验证环境阻塞", "env log", "修复环境",
        )

        entries = _escalation_entries(tmp_path)
        assert len(entries) == 1, "回落件 MUST 落盘（告警本体先行）"
        assert "chain" not in entries[0], "回落件无链上下文字段"
        assert len(lane_calls) == 1, "回落兜底件 MUST 照常直派（守卫不误伤）"
        dispatched_entry, dispatched_alert = lane_calls[0]
        assert "chain" not in dispatched_entry
        assert dispatched_alert == entries[0]["id"], "直派挂靠本次落盘 alert id"


# ── 2.1 入口第二道防线：submit_for_alert 链上下文短路 ────

def _make_lane(tmp_path: Path):
    from core.pm_engine.arbiter import ArbiterLane

    return ArbiterLane(tmp_path, FakeLogger())


class TestLaneEntryGuard:
    def test_chain_entry_short_circuited(self, tmp_path, monkeypatch):
        """绕过咽喉的新调用点直接以含 chain 字段 entry 调 submit_for_alert：
        入口识别链上下文并短路，返回否定哨兵 "excluded"、零 submit_trigger。"""
        lane = _make_lane(tmp_path)
        trigger_calls = []
        monkeypatch.setattr(
            lane, "submit_trigger",
            lambda **kw: trigger_calls.append(kw) or "queued",
        )

        out = lane.submit_for_alert(
            None,
            {"spec": "spec-a", "signal_type": "verify_env_blocked",
             "description": "d",
             "chain": dict(CHAIN_CONTEXT)},
            "alert-1",
        )

        assert out == "excluded", "链上下文 entry MUST 被入口短路"
        assert trigger_calls == [], "短路 MUST 零 submit_trigger（零入队零台账）"
        info_msgs = [m for lvl, _, m in lane.logger.records if lvl == "info"]
        assert any("短路" in m and "alert-1" in m for m in info_msgs), \
            f"入口跳过日志 MUST 记录 alert id: {info_msgs}"

    def test_plain_entry_passthrough_unaffected(self, tmp_path, monkeypatch):
        """无 chain 字段的既有透传形态（回落兜底件）不受入口守卫影响。"""
        lane = _make_lane(tmp_path)
        trigger_calls = []
        monkeypatch.setattr(
            lane, "submit_trigger",
            lambda **kw: trigger_calls.append(kw) or "queued",
        )

        out = lane.submit_for_alert(
            None,
            {"spec": "spec-a", "signal_type": "verify_env_blocked",
             "description": "d"},
            "alert-2",
        )

        assert out == "queued"
        assert len(trigger_calls) == 1
        kw = trigger_calls[0]
        assert kw["spec"] == "spec-a"
        assert kw["signal_type"] == "verify_env_blocked"
        assert kw["alert_id"] == "alert-2"
        assert kw["source"] == "escalation-alert"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
