"""
tests/test_transition_context.py — fix-observability-gaps 2.3

验证 transition / transition_gate 各通道（auto/manual/recovery）产生的日志
均携带结构化 context（trigger_run_id / agent_type / channel），
幂等分支（old==new）显式不产生转换日志（2.1a 排除）。

用真实 Logger 写磁盘后读日志文件断言，不 mock logger。
"""

import json
from pathlib import Path

from core.logger import Logger
from core.state_machine import StateMachine

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_state_machine(tmp_path: Path) -> StateMachine:
    """构造写入 tmp_path 的 StateMachine 实例。"""
    sm = StateMachine(tmp_path / "STATE.md", Logger(tmp_path / ".logs", "DEBUG"))
    return sm


def _read_transition_contexts(tmp_path: Path, pattern: str = "Transition:") -> list[dict]:
    """从 fenixd.log 读取匹配 pattern 的 Transition 行的 context dict 列表。"""
    log_file = tmp_path / ".logs" / "fenixd.log"
    if not log_file.exists():
        return []
    results = []
    for raw in log_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        msg = entry.get("message", "")
        if pattern not in msg:
            continue
        ctx = entry.get("context") or {}
        results.append({"message": msg, "context": ctx})
    return results


def _read_gate_transition_contexts(tmp_path: Path) -> list[dict]:
    """读取 Gate transition 行的 context dict 列表。"""
    return _read_transition_contexts(tmp_path, pattern="Gate transition:")


# ═════════════════════════════════════════════════════════════════════════════
# 自动来源（auto）：PM Engine 派发 / 验证路径
# ═════════════════════════════════════════════════════════════════════════════

class TestTransitionContextAuto:
    def test_transition_with_auto_channel(self, tmp_path):
        """手动调用 transition（auto）→ 日志 context 含 channel=auto。"""
        sm = _make_state_machine(tmp_path)
        sm.add_spec("spec-x", {"status": "drafted"})
        sm.transition(
            "spec-x", "ready",
            trigger_run_id="run-123", agent_type="implementer", channel="auto",
        )
        sm.logger.close()
        ctxs = _read_transition_contexts(tmp_path)
        assert len(ctxs) >= 1
        c = ctxs[-1]["context"]
        assert c.get("channel") == "auto"
        assert c.get("trigger_run_id") == "run-123"
        assert c.get("agent_type") == "implementer"


# ═════════════════════════════════════════════════════════════════════════════
# 人工来源（manual）：Dashboard / CLI 触发
# ═════════════════════════════════════════════════════════════════════════════

class TestTransitionContextManual:
    def test_transition_with_manual_channel(self, tmp_path):
        """transition（manual）→ 日志 context 含 channel=manual。"""
        sm = _make_state_machine(tmp_path)
        sm.add_spec("spec-y", {"status": "drafted"})
        sm.transition(
            "spec-y", "ready",
            trigger_run_id=None, agent_type=None, channel="manual",
        )
        sm.logger.close()
        ctxs = _read_transition_contexts(tmp_path)
        assert len(ctxs) >= 1
        c = ctxs[-1]["context"]
        assert c.get("channel") == "manual"
        assert c.get("trigger_run_id") is None


# ═════════════════════════════════════════════════════════════════════════════
# 恢复来源（recovery）：admin_monitor 恢复路径
# ═════════════════════════════════════════════════════════════════════════════

class TestTransitionContextRecovery:
    def test_transition_gate_with_recovery_channel(self, tmp_path):
        """transition_gate（recovery）→ 日志含 Gate transition + channel=recovery。"""
        sm = _make_state_machine(tmp_path)
        sm.add_spec("spec-z", {"status": "verified"})
        # 触发 GATE_TRANSITIONS 路径（verified → testing，合法门禁转换）
        sm.transition_gate(
            "spec-z", "testing",
            trigger_run_id=None, agent_type=None, channel="recovery",
        )
        sm.logger.close()
        gate_ctxs = _read_gate_transition_contexts(tmp_path)
        assert len(gate_ctxs) >= 1
        c = gate_ctxs[-1]["context"]
        assert c.get("channel") == "recovery"
        assert c.get("trigger_run_id") is None


# ═════════════════════════════════════════════════════════════════════════════
# 2.1a：幂等短路（old==new）不产生 transition 日志行
# ═════════════════════════════════════════════════════════════════════════════

class TestIdempotentExclusion:
    def test_idempotent_transition_no_log_line(self, tmp_path):
        """幂等 transition（old==new）返回 True 但不产生 Transition 日志行（2.1a）。"""
        sm = _make_state_machine(tmp_path)
        sm.add_spec("spec-w", {"status": "ready"})
        # 幂等：已经是 ready，再转 ready
        result = sm.transition(
            "spec-w", "ready",
            trigger_run_id=None, agent_type="implementer", channel="auto",
        )
        sm.logger.close()
        assert result is True
        # 日志里不应有真实 Transition 行（只有 Idempotent transition INFO）
        real_ctxs = _read_transition_contexts(tmp_path)
        assert len(real_ctxs) == 0, "幂等转换不应产生带 context 的 Transition 日志"
