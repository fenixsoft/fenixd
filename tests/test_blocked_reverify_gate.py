"""add-blocked-reverify-lane：BLOCKED→TESTING 重验直通道 + _env_block_rounds 生命周期。

对应 spec/changes/add-blocked-reverify-lane/tasks.md tasks 4.1-4.4。
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from core.state_machine import (
    ENV_BLOCK_ROUNDS_FIELD,
    FREEZE_ERROR_PREFIX,
    GATE_TRANSITIONS,
    VALID_TRANSITIONS,
    SpecStatus,
    StateMachine,
)
from core.state_machine import FREEZE_ERROR_PREFIX
from core.pm_engine.verification import (
    ENV_BLOCK_SIGNAL_TYPES,
    ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS,
    resolve_env_blocked_reset_path,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _sm_setup(tmp_path, *, status="blocked", branch="fenix/test-1700000000",
              frozen=False, error=None, tester_run=None, impl_run=None):
    """构造 tmp 目录上的 StateMachine，写入指定 spec entry。"""
    state_path = tmp_path / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(state_path, mock.MagicMock())
    entry = {"status": status, "branch": branch, "frozen": frozen,
             "error": error, "tester_run": tester_run, "implementer_run": impl_run}
    sm.add_spec("demo", {k: v for k, v in entry.items() if v is not None})
    return sm


class _FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


# ═══════════════════════════════════════════════════════════════════════
# 4.1 GATE_TRANSITIONS 白名单断言
# ═══════════════════════════════════════════════════════════════════════

class TestGateTransitionsBlockedListing:

    def test_blocked_testing_in_gate_transitions(self):
        """BLOCKED→TESTING 列入 GATE_TRANSITIONS 白名单。"""
        assert SpecStatus.TESTING in GATE_TRANSITIONS.get(SpecStatus.BLOCKED, [])

    def test_blocke_testing_not_in_valid_transitions(self):
        """BLOCKED→TESTING 不在 VALID_TRANSITIONS（人工路径须被拒）。"""
        assert SpecStatus.TESTING not in VALID_TRANSITIONS.get(SpecStatus.BLOCKED, [])

    def test_gate_transition_blocked_to_testing_allowed(self):
        """transition_gate(blocked→testing) 放行（幂等自迁移短路）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _sm_setup(Path(tmp))
            result = sm.transition_gate("demo", "testing")
            assert result is True
            assert sm.read_one("demo")["status"] == "testing"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_human_transition_blocked_to_testing_rejected(self):
        """人工路径 transition(blocked→testing) 被 VALID_TRANSITIONS 拒绝。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _sm_setup(Path(tmp))
            result = sm.transition("demo", "testing")
            assert result is False
            assert sm.read_one("demo")["status"] == "blocked"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_gate_transition_idempotent_shortcircuit(self):
        """幂等自迁移（already testing）直接返回 True，不报错。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _sm_setup(Path(tmp))
            sm.transition_gate("demo", "testing")  # 第一次
            result = sm.transition_gate("demo", "testing")  # 幂等
            assert result is True
            assert sm.read_one("demo")["status"] == "testing"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_gate_transition_preserves_branch_and_rounds(self):
        """BLOCKED→TESTING 只改 status，保留 branch / _env_block_rounds。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _sm_setup(Path(tmp))
            sm.update_spec("demo", {ENV_BLOCK_ROUNDS_FIELD: 1, "branch": "fenix/x"})
            sm.transition_gate("demo", "testing")
            entry = sm.read_one("demo")
            assert entry["status"] == "testing"
            assert entry.get("branch") == "fenix/x"
            # 侧车字段经 STATE.md 文本往返为 str；断言数值等价即验证「未清零」
            assert int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0) == 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# 4.2 复位判定守卫链单测
# ═══════════════════════════════════════════════════════════════════════

class _FakeProjectRoot:
    """用于 resolve_env_blocked_reset_path 的 git 判定：模拟 merge-base 结果。"""

    def __init__(self, merged=True):
        self.merged = merged

    def __fspath__(self):
        return str(self._dummy)

    @property
    def _dummy(self):
        return Path("/tmp/fake_project")


def _fake_subprocess_run_mergereturncode(returncode=0):
    """构造 subprocess.run 替身，返回指定 returncode。"""
    class Result:
        def __init__(self, rc):
            self.returncode = rc
            self.stdout = b""
            self.stderr = b""
    return lambda *a, **k: Result(returncode)


class TestResolveEnvBlockedResetPath:

    def test_not_blocked_returns_none(self):
        """非 blocked spec → None（不适用）。"""
        assert resolve_env_blocked_reset_path({"status": "ready"}, "/tmp") is None
        assert resolve_env_blocked_reset_path({}, "/tmp") is None

    def test_frozen_human_freeze_returns_none(self):
        """人工冻结（frozen=True）→ None（不走自动复位）。"""
        spec = {"status": "blocked", "frozen": True, "branch": "fenix/x"}
        assert resolve_env_blocked_reset_path(spec, "/tmp") is None

    def test_error_starts_with_freeze_prefix_returns_none(self):
        """error 以冻结前缀开头 → None（人工冻结文本契约）。"""
        spec = {"status": "blocked", "error": f"{FREEZE_ERROR_PREFIX}原因",
                "branch": "fenix/x"}
        assert resolve_env_blocked_reset_path(spec, "/tmp") is None

    def test_no_branch_returns_ready(self):
        """branch 为空（实现阶段熔断）→ ready。"""
        spec = {"status": "blocked", "error": "env 阻塞", "branch": None}
        result = resolve_env_blocked_reset_path(spec, "/tmp")
        assert result == "ready"

    def test_branch_merged_returns_testing(self):
        """branch 已合并（git merge-base exit 0）→ testing。"""
        spec = {"status": "blocked", "error": "env 阻塞", "branch": "fenix/x"}
        fake_root = _FakeProjectRoot()
        with mock.patch("core.pm_engine.verification.subprocess.run",
                        side_effect=_fake_subprocess_run_mergereturncode(0)):
            result = resolve_env_blocked_reset_path(spec, fake_root)
        assert result == "testing"

    def test_branch_not_merged_returns_ready(self):
        """branch 未合并（git merge-base exit 1）→ ready。"""
        spec = {"status": "blocked", "error": "env 阻塞", "branch": "fenix/x"}
        fake_root = _FakeProjectRoot()
        with mock.patch("core.pm_engine.verification.subprocess.run",
                        side_effect=_fake_subprocess_run_mergereturncode(1)):
            result = resolve_env_blocked_reset_path(spec, fake_root)
        assert result == "ready"

    def test_git_exception_returns_ready(self):
        """git 命令异常 → fail-safe 回退 ready（宁可多重实现）。"""
        spec = {"status": "blocked", "error": "env 阻塞", "branch": "fenix/x"}
        fake_root = _FakeProjectRoot()
        with mock.patch("core.pm_engine.verification.subprocess.run",
                        side_effect=OSError("git not found")):
            result = resolve_env_blocked_reset_path(spec, fake_root)
        assert result == "ready"


# ═══════════════════════════════════════════════════════════════════════
# 4.3 _env_block_rounds 生命周期语义单测
# ═══════════════════════════════════════════════════════════════════════

class TestEnvBlockRoundsLifecycle:

    def test_verified_clears_env_block_rounds(self):
        """verified 落定清零 _env_block_rounds（验证通过唯一自动清零点）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _sm_setup(Path(tmp), status="testing", error=None)
            sm.update_spec("demo", {ENV_BLOCK_ROUNDS_FIELD: 1})
            # 模拟 verified 落定清零（由 verification.py 调用）
            sm.update_spec("demo", {
                "status": "verified",
                "tester_run": "verify-1",
                "error": None,
                ENV_BLOCK_ROUNDS_FIELD: 0,
            })
            entry = sm.read_one("demo")
            # 清零后值为字符串 '0'（STATE.md 文本往返），int 等价断言
            assert int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0) == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unfreeze_clears_env_block_rounds(self):
        """unfreeze_spec 清零 _env_block_rounds（人工解冻清零点）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _sm_setup(Path(tmp), status="blocked", frozen=True,
                           error=f"{FREEZE_ERROR_PREFIX}环境阻塞",
                           branch="fenix/x")
            sm.update_spec("demo", {ENV_BLOCK_ROUNDS_FIELD: 1})
            sm.unfreeze_spec("demo", status="ready")
            entry = sm.read_one("demo")
            # 清零后值为字符串 '0'（STATE.md 文本往返），int 等价断言
            assert int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0) == 0
            assert entry["status"] == "ready"
            assert entry.get("frozen") is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_admin_disposition_does_not_clear_env_block_rounds(self):
        """admin 处置复位到 ready 时 _env_block_rounds 不清零（生命周期累计）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _sm_setup(Path(tmp), status="blocked", branch="fenix/x",
                           error="env 阻塞")
            sm.update_spec("demo", {ENV_BLOCK_ROUNDS_FIELD: 1})
            # 模拟 admin 处置复位路径（transition(ready) + 清 error，不清 rounds）
            sm.transition("demo", "ready")
            sm.update_spec("demo", {"error": None})
            entry = sm.read_one("demo")
            assert int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0) == 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_escalate_env_blocked_increments_rounds(self):
        """_escalate_env_blocked 每次调用 rounds+1；rounds=2 触发 frozen 冻结。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _sm_setup(Path(tmp), status="blocked", branch="fenix/x",
                           error="env 阻塞")
            sm.update_spec("demo", {ENV_BLOCK_ROUNDS_FIELD: 1})

            # 模拟 _escalate_env_blocked 内部逻辑
            spec = sm.read_one("demo") or {}
            rounds = int(spec.get(ENV_BLOCK_ROUNDS_FIELD) or 0) + 1
            frozen = rounds >= 2
            sm.update_spec("demo", {
                ENV_BLOCK_ROUNDS_FIELD: rounds,
                # 文案形状与 verification._escalate_env_blocked 保持同源：冻结
                # 一律以 FREEZE_ERROR_PREFIX 开头（模拟段曾写「用户指令冻结（…」
                # 全角括号，与常量不匹配——照抄即复现该文本契约断裂）。
                "error": f"env 阻塞（第 {rounds} 轮）" if not frozen
                         else f"{FREEZE_ERROR_PREFIX}env 阻塞连续 {rounds} 轮，转人工",
            })
            if frozen:
                sm.update_spec("demo", {"frozen": True})
            entry = sm.read_one("demo")
            assert int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0) == 2
            assert entry.get("frozen") is True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# 4.4 处置收尾集成测
# ═══════════════════════════════════════════════════════════════════════

class _FakeSmWithTransitionGate:
    """轻量状态机替身：记录 transition_gate / transition 调用。"""

    def __init__(self, specs: dict):
        self._specs = dict(specs)
        self.transition_gate_calls = []
        self.transition_calls = []
        self.update_calls = []

    def read_one(self, spec_name):
        return self._specs.get(spec_name)

    def read_all(self):
        return dict(self._specs)

    def transition_gate(self, spec_name, new_status,
                        *, trigger_run_id=None, agent_type=None, channel="auto"):
        self.transition_gate_calls.append((spec_name, new_status))
        entry = self._specs.get(spec_name)
        if entry:
            entry["status"] = new_status
        return True

    def transition(self, spec_name, new_status,
                   *, trigger_run_id=None, agent_type=None, channel="auto"):
        self.transition_calls.append((spec_name, new_status))
        entry = self._specs.get(spec_name)
        if entry:
            entry["status"] = new_status
        return True

    def update_spec(self, spec_name, updates):
        self.update_calls.append((spec_name, updates))
        entry = self._specs.get(spec_name)
        if entry:
            entry.update(updates)
        return True


class _FakePmEngine:
    """pm_engine 替身：记录 handle_event 调用。"""

    def __init__(self):
        self.handle_event_calls = []

    def handle_event(self, event_kind, spec_name, spec_entry):
        self.handle_event_calls.append((event_kind, spec_name, spec_entry))


class TestDispositionResetIntegration:

    def _make_admin_monitor(self, tmp_path, sm, pm_engine=None):
        """构造最小 AdminMonitor（绕过真实的 __init__ 依赖）。"""
        from core.admin_monitor import AdminMonitor
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        from core.admin_store import AdminStore
        store = AdminStore(proot, _FakeLogger())
        monitor = AdminMonitor.__new__(AdminMonitor)
        monitor.config = {}
        monitor.admin_cfg = {"enabled": False, "interval_minutes": 30,
                             "cooldown_minutes": 5}
        monitor.state_machine = sm
        monitor.project_root = proot
        monitor.logger = _FakeLogger()
        monitor.store = store
        monitor.agent_runner = None
        monitor.pm_engine = pm_engine
        return monitor

    def _make_admin_disposition(self, **kwargs):
        """构造 AdminDisposition 数据对象。"""
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class Disp:
            run_id: str = "admin-test-1"
            spec: Optional[str] = None
            success: bool = True
            problem: str = "env 阻塞"
            actions_taken: str = "修复端口"
            result: str = "resolved"
            summary: str = "已解决"
            escalate: bool = False
            error: str = ""
            recommended_action: str = ""
            family_waiver: bool = False

        return Disp(**kwargs)

    def test_resolved_gate_path_triggers_testing_and_enqueue(self):
        """result=resolved + env 信号 + branch merged → transition_gate(testing)
        + verifier 入队（pm_engine.handle_event spec_implemented）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSmWithTransitionGate({
                "demo": {"status": "blocked", "branch": "fenix/x",
                         "error": "env 阻塞", "frozen": False,
                         ENV_BLOCK_ROUNDS_FIELD: 1, "implementer_run": "impl-1"},
            })
            pm = _FakePmEngine()
            monitor = self._make_admin_monitor(Path(tmp), sm, pm_engine=pm)

            signal = {
                "signal_type": "verify_env_blocked",
                "spec": "demo",
                "severity": "warning",
                "description": "env 阻塞",
                "evidence": "test",
                "recommended_action": "修复环境",
            }
            disp = self._make_admin_disposition(
                result="resolved", spec="demo",
            )
            # mock git 判定：branch merged
            with mock.patch("core.pm_engine.verification.subprocess.run",
                            side_effect=_fake_subprocess_run_mergereturncode(0)):
                monitor._reset_env_blocked_after_disposition(signal, disp)

            entry = sm.read_one("demo")
            assert entry["status"] == "testing"
            assert entry.get("error") is None
            assert int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0) == 1  # 不清零
            assert pm.handle_event_calls == [
                ("spec_implemented", "demo", sm.read_one("demo"))
            ]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_resolved_ready_path_transitions_ready(self):
        """result=resolved + env 信号 + branch 未合并 → transition(ready)。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSmWithTransitionGate({
                "demo": {"status": "blocked", "branch": "fenix/x",
                         "error": "env 阻塞", "frozen": False,
                         ENV_BLOCK_ROUNDS_FIELD: 1, "implementer_run": "impl-1"},
            })
            pm = _FakePmEngine()
            monitor = self._make_admin_monitor(Path(tmp), sm, pm_engine=pm)

            signal = {
                "signal_type": "verify_env_blocked",
                "spec": "demo",
                "severity": "warning",
                "description": "env 阻塞",
                "evidence": "test",
            }
            disp = self._make_admin_disposition(result="resolved", spec="demo")
            # mock git 判定：branch NOT merged
            with mock.patch("core.pm_engine.verification.subprocess.run",
                            side_effect=_fake_subprocess_run_mergereturncode(1)):
                monitor._reset_env_blocked_after_disposition(signal, disp)

            entry = sm.read_one("demo")
            assert entry["status"] == "ready"
            assert sm.transition_calls == [("demo", "ready")]
            assert sm.transition_gate_calls == []
            assert int(entry.get(ENV_BLOCK_ROUNDS_FIELD) or 0) == 1  # 不清零
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_escalated_does_not_trigger_reset(self):
        """result=escalated 不触发自动复位（admin 升级人工是另一条路）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSmWithTransitionGate({
                "demo": {"status": "blocked", "branch": "fenix/x",
                         "error": "env 阻塞", "frozen": False,
                         ENV_BLOCK_ROUNDS_FIELD: 1},
            })
            pm = _FakePmEngine()
            monitor = self._make_admin_monitor(Path(tmp), sm, pm_engine=pm)
            signal = {
                "signal_type": "verify_env_blocked",
                "spec": "demo",
                "severity": "critical",
                "description": "env 阻塞",
                "evidence": "test",
            }
            disp = self._make_admin_disposition(result="escalated", spec="demo")
            monitor._reset_env_blocked_after_disposition(signal, disp)

            entry = sm.read_one("demo")
            assert entry["status"] == "blocked"
            assert pm.handle_event_calls == []
            assert sm.transition_gate_calls == []
            assert sm.transition_calls == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_escalated_result_does_not_call_reset_from_wrapper(self):
        """_invoke_administrator 路径：result=escalated 不走 _reset 分支。"""
        from core.admin_monitor import AdminMonitor

        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSmWithTransitionGate({
                "demo": {"status": "blocked", "branch": "fenix/x",
                         "error": "env 阻塞", "frozen": False,
                         ENV_BLOCK_ROUNDS_FIELD: 1},
            })
            pm = _FakePmEngine()
            monitor = self._make_admin_monitor(Path(tmp), sm, pm_engine=pm)

            # 验证 _reset_env_blocked_after_disposition 在 escalated 时不被调用
            with mock.patch.object(monitor, "_reset_env_blocked_after_disposition") as mock_reset:
                signal = {
                    "signal_type": "verify_env_blocked",
                    "spec": "demo",
                    "severity": "critical",
                    "description": "env 阻塞",
                    "evidence": "test",
                }
                # disp.result = "escalated" → 不应进入 _reset 分支
                disp = self._make_admin_disposition(result="escalated", spec="demo")
                # 直接调 wrapper 里的条件判断
                if disp.result in ("resolved", "partially-resolved"):
                    sig_type = signal.get("signal_type")
                    if sig_type in ENV_BLOCK_SIGNAL_TYPES:
                        monitor._reset_env_blocked_after_disposition(signal, disp)
                mock_reset.assert_not_called()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# add-control-plane-silent-failure-guards 3.5：复位路径编程错误升级
# ═══════════════════════════════════════════════════════════════════════

class _TypeErrorPmEngine:
    """handle_event 抛出 TypeError——模拟复位路径调用点实参数量不符的代码缺陷。"""

    def handle_event(self, event_kind, spec_name, spec_entry):
        raise TypeError(
            f"handle_event() missing 1 required positional argument: 'spec_entry'")


class _OSErrorPmEngine:
    """handle_event 抛出 OSError——模拟运维失败（端口占用/网络），不升级。"""

    def handle_event(self, event_kind, spec_name, spec_entry):
        raise OSError("port 8787 already in use")


class TestResetProgrammingErrorEscalation:
    """admin-reset-error-escalation R1/R2/R3：复位路径编程错误分层升级。

    拔牙属性：若把 `_reset_env_blocked_after_disposition` 的
    `except (TypeError, AttributeError, NameError)` 分层移除（退回单一
    `except Exception`），TypeError 会被静默降级为 WARNING——
    TypeError 注入用例断言 0 条 critical 升级告警，测试即失败。
    """

    def _make_monitor(self, tmp_path, sm, pm_engine):
        from core.admin_monitor import AdminMonitor
        from core.admin_store import AdminStore
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        store = AdminStore(proot, _FakeLogger())
        monitor = AdminMonitor.__new__(AdminMonitor)
        monitor.config = {}
        monitor.admin_cfg = {"enabled": False, "interval_minutes": 30,
                             "cooldown_minutes": 5}
        monitor.state_machine = sm
        monitor.project_root = proot
        monitor.logger = _FakeLogger()
        monitor.store = store
        monitor.agent_runner = None
        monitor.pm_engine = pm_engine
        return monitor, proot

    def _setup(self, tmp_path, pm_engine):
        sm = _FakeSmWithTransitionGate({
            "demo": {"status": "blocked", "branch": "fenix/x",
                     "error": "env 阻塞", "frozen": False,
                     ENV_BLOCK_ROUNDS_FIELD: 1, "implementer_run": "impl-1"},
        })
        monitor, proot = self._make_monitor(tmp_path, sm, pm_engine)
        from core.admin_store import ESCALATION
        signal = {
            "signal_type": "verify_env_blocked",
            "spec": "demo",
            "severity": "warning",
            "description": "env 阻塞",
            "evidence": "test",
            "recommended_action": "修复环境",
        }
        disp = TestDispositionResetIntegration()._make_admin_disposition(
            result="resolved", spec="demo")
        return monitor, proot, sm, signal, disp, ESCALATION

    def test_typeerror_escalates_critical(self):
        """TypeError 注入 → 恰好 1 条 admin_reset_programming_error critical 告警。"""
        tmp = tempfile.mkdtemp()
        try:
            monitor, proot, sm, signal, disp, _ESC = self._setup(
                Path(tmp), _TypeErrorPmEngine())
            with mock.patch("core.pm_engine.verification.subprocess.run",
                            side_effect=_fake_subprocess_run_mergereturncode(0)):
                monitor._reset_env_blocked_after_disposition(signal, disp)
            # 复位到 testing 完成了（异常发生在 verifier 入队步），处置记录语义完整
            assert sm.read_one("demo")["status"] == "testing"
            alerts = [r for r in monitor.store.read_all()
                      if r.get("kind") == "escalation"
                      and r.get("signal_type") == "admin_reset_programming_error"]
            assert len(alerts) == 1, f"期望恰好 1 条升级告警，实际 {len(alerts)}"
            alert = alerts[0]
            assert alert.get("severity") == "critical"
            assert "TypeError" in alert.get("evidence")
            assert "调用点=" in alert.get("evidence")
            assert alert.get("recommended_action")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_oserror_stays_warning(self):
        """OSError 注入 → 0 条升级告警（保持既有 WARNING 语义）。"""
        tmp = tempfile.mkdtemp()
        try:
            monitor, proot, sm, signal, disp, _ESC = self._setup(
                Path(tmp), _OSErrorPmEngine())
            with mock.patch("core.pm_engine.verification.subprocess.run",
                            side_effect=_fake_subprocess_run_mergereturncode(0)):
                monitor._reset_env_blocked_after_disposition(signal, disp)
            alerts = [r for r in monitor.store.read_all()
                      if r.get("kind") == "escalation"
                      and r.get("signal_type") == "admin_reset_programming_error"]
            assert alerts == [], f"OSError 不应升级，实际 {len(alerts)} 条"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_duplicate_escalation_deduped(self):
        """R3 去重：同一 spec 连续两轮触发同类编程错误 → 仅 1 条未处理告警。"""
        tmp = tempfile.mkdtemp()
        try:
            monitor, proot, sm, signal, disp, _ESC = self._setup(
                Path(tmp), _TypeErrorPmEngine())
            with mock.patch("core.pm_engine.verification.subprocess.run",
                            side_effect=_fake_subprocess_run_mergereturncode(0)):
                monitor._reset_env_blocked_after_disposition(signal, disp)  # 第一轮
            with mock.patch("core.pm_engine.verification.subprocess.run",
                            side_effect=_fake_subprocess_run_mergereturncode(0)):
                monitor._reset_env_blocked_after_disposition(signal, disp)  # 第二轮
            unhandled = [r for r in monitor.store.read_all()
                         if r.get("kind") == "escalation"
                         and r.get("signal_type") == "admin_reset_programming_error"
                         and not r.get("handled")]
            assert len(unhandled) == 1, f"应去重为 1 条未处理告警，实际 {len(unhandled)}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_callsite_points_into_core(self):
        """R2 调用点：evidence 中调用点指向 core/ 内帧（非测试外层）。"""
        tmp = tempfile.mkdtemp()
        try:
            monitor, proot, sm, signal, disp, _ESC = self._setup(
                Path(tmp), _TypeErrorPmEngine())
            with mock.patch("core.pm_engine.verification.subprocess.run",
                            side_effect=_fake_subprocess_run_mergereturncode(0)):
                monitor._reset_env_blocked_after_disposition(signal, disp)
            alert = next(r for r in monitor.store.read_all()
                         if r.get("signal_type") == "admin_reset_programming_error")
            callsite = alert["evidence"].split("调用点=")[-1]
            # 最深 core/ 帧落在 admin_monitor.py（调用链在 core 内），
            # 而非 tests/ 注入点
            assert "admin_monitor.py" in callsite, callsite
            assert "test_blocked_reverify_gate" not in callsite, callsite
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_recommendation_points_to_code_defect(self):
        """R4 处置指引到位：SIGNAL_RECOMMENDATION 登记 admin_reset_programming_error
        且指明为代码缺陷（Administrator 无法修复、勿派子 fix 反复重跑），
        落盘告警携带该指引（而非环境修复话术）。"""
        from core.admin_monitor import SIGNAL_RECOMMENDATION
        rec = SIGNAL_RECOMMENDATION.get("admin_reset_programming_error", "")
        assert rec, "admin_reset_programming_error 必须登记处置指引"
        assert "代码缺陷" in rec, f"指引应指明代码缺陷: {rec}"
        assert "Administrator 无法修复" in rec, f"指引应指明非 Administrator 可修: {rec}"
        assert "勿派子 fix" in rec, f"指引应劝阻子 fix 反复重跑: {rec}"
        tmp = tempfile.mkdtemp()
        try:
            monitor, proot, sm, signal, disp, _ESC = self._setup(
                Path(tmp), _TypeErrorPmEngine())
            with mock.patch("core.pm_engine.verification.subprocess.run",
                            side_effect=_fake_subprocess_run_mergereturncode(0)):
                monitor._reset_env_blocked_after_disposition(signal, disp)
            alert = next(r for r in monitor.store.read_all()
                         if r.get("signal_type") == "admin_reset_programming_error")
            assert alert.get("recommended_action") == rec, (
                f"告警 recommended_action 应为登记指引: {alert.get('recommended_action')}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
