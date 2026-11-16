"""evo-env-fix-reverify-linkage：环境修复处置闭环接续复位 + 回执落地校验。

tasks 3.1（四场景正向）+ 3.2（回归锚）：
- 链上闭环→testing 迁移并入队 verifier（1.1）
- 互斥跳过登记待重评标记后下一巡检消费（1.2）
- blocked_stuck 桶内 manual_fixed_reverify 解析放行（1.3/1.4）
- 判定窗内无落地发告警并标记处置无效（2.1）
- 回归锚：frozen spec 既有解冻不变 / 非 blocked 或非已修复不迁移 /
  判定窗内落地成功零告警
"""

import shutil
import tempfile
import time
from pathlib import Path
from unittest import mock

from core.admin_store import DISPOSITION, ESCALATION, AdminStore
from core.state_machine import StateMachine

from core.admin_monitor import (
    ENV_FIX_RECEIPTS_REL,
    ENV_FIX_REVERIFY_RECHECK_REL,
    _load_env_fix_state,
    _save_env_fix_state,
    load_env_fix_receipts,
    load_env_fix_reverify_rechecks,
    record_env_fix_receipt,
    register_env_fix_reverify_recheck,
)


# ── 替身与夹具 ────────────────────────────────────────────────────────

class _FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _FakePmEngine:
    """pm_engine 替身：记录 handle_event 调用。"""

    def __init__(self):
        self.handle_event_calls = []

    def handle_event(self, event_kind, spec_name, spec_entry):
        self.handle_event_calls.append((event_kind, spec_name, spec_entry))


class _FakeSm:
    """轻量状态机替身：记录迁移/写入调用（read_one 返回内层 dict 引用）。"""

    def __init__(self, specs: dict):
        self._specs = dict(specs)
        self.transition_gate_calls = []
        self.transition_calls = []
        self.update_calls = []
        self.unfreeze_calls = []

    def read_one(self, spec_name):
        return self._specs.get(spec_name)

    def read_all(self):
        return dict(self._specs)

    def transition_gate(self, spec_name, new_status, *, trigger_run_id=None,
                        agent_type=None, channel="auto"):
        self.transition_gate_calls.append((spec_name, new_status))
        entry = self._specs.get(spec_name)
        if entry:
            entry["status"] = new_status
        return True

    def transition(self, spec_name, new_status, *, trigger_run_id=None,
                   agent_type=None, channel="auto"):
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

    def unfreeze_spec(self, spec_name, status=None):
        self.unfreeze_calls.append((spec_name, status))
        entry = self._specs.get(spec_name)
        if not entry:
            return False
        entry["frozen"] = False
        if status:
            entry["status"] = status
        return True


def _fake_subprocess_run_mergereturncode(returncode=0):
    """构造 subprocess.run 替身（合并判定 returncode 口径，同
    test_blocked_reverify_gate 既有夹具）。"""

    class Result:
        def __init__(self, rc):
            self.returncode = rc
            self.stdout = b""
            self.stderr = b""

    return lambda *a, **k: Result(returncode)


def _merge_mock(returncode=0):
    """branch 已合并/未合并判定 mock（_branch_merged_into_tree 走
    core.pm_engine.verification 的 subprocess）。"""
    return mock.patch(
        "core.pm_engine.verification.subprocess.run",
        side_effect=_fake_subprocess_run_mergereturncode(returncode),
    )


def _make_disposition(**kwargs):
    """AdminDisposition 形状替身（dataclass，字段同 admin_monitor 消费面）。"""
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
        status_after: str = ""

    return Disp(**kwargs)


def _blocked_entry(**extra):
    entry = {"status": "blocked", "branch": "fenix/x", "error": "env 阻塞",
             "frozen": False}
    entry.update(extra)
    return entry


def _make_monitor(tmp_path, sm, pm_engine=None):
    """最小 AdminMonitor（绕过真实 __init__ 依赖，同既有测试夹具形态）。"""
    from core.admin_monitor import AdminMonitor

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


def _make_chain(tmp_path, sm, pm_engine=None):
    """最小 EscalationChain（注入 sm/pm，不启动 worker）。"""
    from core.pm_engine.escalation_chain import EscalationChain

    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    chain = EscalationChain(proot, _FakeLogger())
    chain.set_state_machine(sm)
    if pm_engine is not None:
        chain.set_pm(pm_engine)
    return chain, proot


def _advance_receipt_window(proot, spec, minutes=11):
    """把回执 created_at 拨早到窗外（不 patch 全局时钟）。"""
    path = Path(proot) / ENV_FIX_RECEIPTS_REL
    data = _load_env_fix_state(path)
    data[spec]["created_at"] = time.time() - minutes * 60
    assert _save_env_fix_state(path, data)


# ═════════════════════════════════════════════════════════════════════
# 3.1 四场景正向
# ═════════════════════════════════════════════════════════════════════

class TestChainCloseEnvReverify:
    """3.1-1：链上闭环→testing 迁移并入队 verifier（task 1.1）。"""

    def test_chain_close_migrates_to_testing_and_enqueues_verifier(self):
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": _blocked_entry()})
            pm = _FakePmEngine()
            chain, proot = _make_chain(Path(tmp), sm, pm)
            item = {"signal_type": "verify_env_blocked", "spec": "demo",
                    "signature": "sig-1"}
            disp = _make_disposition(run_id="admin-t1", result="resolved",
                                     spec="demo")
            with _merge_mock(0):  # branch 已合并
                side = chain._close_chain_success(item, disp)

            entry = sm.read_one("demo")
            assert entry["status"] == "testing"
            assert entry.get("error") is None
            assert pm.handle_event_calls, "verifier 未入队"
            assert pm.handle_event_calls[0][0] == "spec_implemented"
            assert pm.handle_event_calls[0][1] == "demo"
            assert side["env_reverify"]["migrated"] == "testing"
            assert side["unfrozen"] is False  # 非 frozen 不走解冻路径
            # 回执句柄（2.1 chain-closed 写点）
            receipts = load_env_fix_receipts(proot)
            assert receipts["demo"]["expected_status"] == "testing"
            assert receipts["demo"]["expected_run_type"] == "verify"
            assert receipts["demo"]["run_id"] == "admin-t1"
            assert receipts["demo"]["source"] == "chain-closed"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_chain_close_unmerged_branch_goes_ready(self):
        """branch 未合并 → ready 重实现通道（直通道同判，不误入 testing）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": _blocked_entry()})
            pm = _FakePmEngine()
            chain, proot = _make_chain(Path(tmp), sm, pm)
            item = {"signal_type": "blocked_stuck", "spec": "demo"}
            disp = _make_disposition(run_id="admin-t2", result="resolved",
                                     spec="demo")
            with _merge_mock(1):  # branch 未合并
                side = chain._close_chain_success(item, disp)

            assert sm.read_one("demo")["status"] == "ready"
            assert sm.transition_gate_calls == []
            assert pm.handle_event_calls == []
            assert side["env_reverify"]["migrated"] == "ready"
            receipts = load_env_fix_receipts(proot)
            assert receipts["demo"]["expected_status"] == "ready"
            assert receipts["demo"]["expected_run_type"] == "impl"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestMutexSkipRecheck:
    """3.1-2：互斥跳过登记待重评标记后下一巡检消费（task 1.2）。"""

    def test_mutex_skip_registers_then_next_scan_consumes(self):
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": _blocked_entry()})
            pm = _FakePmEngine()
            monitor, proot = _make_monitor(Path(tmp), sm, pm)
            # 在飞 admin run（pending DISPOSITION 记录）
            monitor.store.append({
                "kind": DISPOSITION, "admin_run_id": "admin-inflight-1",
                "spec": "demo", "signal_type": "stuck", "status": "pending",
            })
            signal = {"signal_type": "verify_env_blocked", "spec": "demo"}
            disp = _make_disposition(run_id="admin-t3", result="resolved",
                                     spec="demo")
            with _merge_mock(0):
                monitor._reset_env_blocked_after_disposition(signal, disp)

            # 互斥命中：不迁移，登记待重评标记
            assert sm.read_one("demo")["status"] == "blocked"
            assert pm.handle_event_calls == []
            markers = load_env_fix_reverify_rechecks(proot)
            assert "demo" in markers
            assert markers["demo"]["source"] == "disposition-auto-reset"

            # 互斥解除（在飞 run final 化）→ 下一巡检周期消费完成迁移
            def _finalize(records):
                changed = False
                for r in records:
                    if (r.get("admin_run_id") == "admin-inflight-1"
                            and r.get("status") == "pending"):
                        r["status"] = "resolved"
                        changed = True
                return changed

            monitor.store.update_records(_finalize)
            with _merge_mock(0):
                consumed = monitor._consume_env_fix_reverify_rechecks()
            assert consumed == 1
            assert sm.read_one("demo")["status"] == "testing"
            assert sm.read_one("demo").get("error") is None
            assert pm.handle_event_calls, "消费迁移未入队 verifier"
            assert load_env_fix_reverify_rechecks(proot) == {}, "标记消费后未清除"
            # 消费迁移同样写回执句柄（2.1）
            receipts = load_env_fix_receipts(proot)
            assert receipts["demo"]["expected_status"] == "testing"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_run_once_hooks_recheck_and_receipt_checkpoints(self):
        """巡检挂载契约：run_once 含两个新检查点（不新增线程/定时器）。"""
        import inspect

        from core.admin_monitor import AdminMonitor

        src = inspect.getsource(AdminMonitor.run_once)
        assert "_consume_env_fix_reverify_rechecks" in src
        assert "_check_env_fix_receipts" in src

    def test_recheck_consumed_without_migration_when_not_blocked(self):
        """迁移前提不再成立（已非 blocked）→ 消费清除但不迁移。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": {"status": "ready", "branch": "fenix/x",
                                   "frozen": False}})
            pm = _FakePmEngine()
            monitor, proot = _make_monitor(Path(tmp), sm, pm)
            register_env_fix_reverify_recheck(proot, "demo",
                                              signal_type="verify_env_blocked",
                                              source="chain-closed")
            consumed = monitor._consume_env_fix_reverify_rechecks()
            assert consumed == 1
            assert sm.read_one("demo")["status"] == "ready"
            assert sm.transition_gate_calls == []
            assert pm.handle_event_calls == []
            assert load_env_fix_reverify_rechecks(proot) == {}
            assert load_env_fix_receipts(proot) == {}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestBlockedStuckChoiceBucket:
    """3.1-3：blocked_stuck 桶内 manual_fixed_reverify 解析放行（1.3/1.4）。"""

    def test_resolve_choice_bucket_exact_match(self):
        from core.dashboard.data.adjudication_choices import (
            choices_for_admin_chain,
            resolve_choice,
        )

        choice, reason = resolve_choice("manual_fixed_reverify", "blocked_stuck")
        assert choice is not None and reason == ""
        assert choice["action"] == "reset_verification"
        assert choice.get("spec_scoped") is True
        # 桶内精确匹配：同桶其他 id 仍拒（不跨选项放行）
        c2, r2 = resolve_choice("revise_scenario_reverify", "blocked_stuck")
        assert c2 is None and r2 == "not-in-bucket"
        # 链上词表按注册桶生成（1.4 提示词面）
        assert [c["id"] for c in choices_for_admin_chain("blocked_stuck")] == [
            "manual_fixed_reverify"
        ]
        # 未注册信号不下发 spec 作用域词表
        assert choices_for_admin_chain("totally_unregistered") == ()

    def test_manual_fixed_reverify_executes_end_to_end(self):
        """端到端：桶内放行 + VERIFY_CHAIN_SIGNAL_TYPES 放行 + 复位落地。"""
        from core.dashboard.data.admin_actions import execute_adjudication_choice

        tmp = tempfile.mkdtemp()
        try:
            proot = Path(tmp) / "proj"
            sm = StateMachine(proot / ".fenix" / "STATE.md", _FakeLogger())
            sm.add_spec("demo", {"status": "blocked", "branch": "fenix/x",
                                 "error": "env 阻塞", "frozen": False})
            with _merge_mock(1):  # 未合并 → ready 通道
                r = execute_adjudication_choice(
                    proot, "demo", "manual_fixed_reverify",
                    signal_type="blocked_stuck",
                )
            assert r.get("ok") is True, r
            assert sm.read_one("demo")["status"] == "ready"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unregistered_signal_scoped_choice_still_rejected(self):
        """回归锚（前置防越界）：未注册信号 × spec_scoped 动作仍被拒。"""
        from core.dashboard.data.admin_actions import execute_adjudication_choice

        tmp = tempfile.mkdtemp()
        try:
            proot = Path(tmp) / "proj"
            sm = StateMachine(proot / ".fenix" / "STATE.md", _FakeLogger())
            sm.add_spec("demo", {"status": "blocked", "branch": "fenix/x",
                                 "error": "env 阻塞", "frozen": False})
            r = execute_adjudication_choice(
                proot, "demo", "manual_fixed_reverify",
                signal_type="totally_unregistered",
            )
            assert r.get("ok") is False
            assert "未注册裁决选项集" in str(r.get("error") or "")
            assert sm.read_one("demo")["status"] == "blocked"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestReceiptLandingCheck:
    """3.1-4：判定窗内无落地发告警并标记处置无效（task 2.1）。"""

    def _seed(self, tmp_path, status="blocked", run_id="admin-r4"):
        sm = _FakeSm({"demo": {"status": status, "branch": "fenix/x",
                               "error": "env 阻塞", "frozen": False}})
        monitor, proot = _make_monitor(Path(tmp_path), sm)
        monitor.store.append({
            "kind": DISPOSITION, "admin_run_id": run_id, "spec": "demo",
            "signal_type": "verify_env_blocked", "status": "resolved",
        })
        record_env_fix_receipt(
            proot, "demo", expected_status="testing",
            expected_run_type="verify", run_id=run_id,
            signal_type="verify_env_blocked", source="chain-closed",
        )
        return monitor, proot, sm

    def test_window_expiry_without_landing_alerts_and_invalidates(self):
        tmp = tempfile.mkdtemp()
        try:
            monitor, proot, sm = self._seed(Path(tmp), status="blocked")
            _advance_receipt_window(proot, "demo")

            alerted = monitor._check_env_fix_receipts()

            assert alerted == 1
            # 处置记录标记无效
            final = [r for r in monitor.store.read_all()
                     if r.get("admin_run_id") == "admin-r4"]
            assert final and final[-1].get("receipt_landing") == "invalid"
            # 升级告警在场且未闭环（人工裁决是唯一出路）
            esc = [r for r in monitor.store.read_all()
                   if r.get("kind") == ESCALATION
                   and r.get("signal_type") == "env_fix_receipt_unverified"]
            assert len(esc) == 1
            assert not esc[0].get("handled")
            assert esc[0].get("spec") == "demo"
            # 回执一次性消费（不逐轮重复烧告警）
            assert load_env_fix_receipts(proot) == {}
            assert monitor._check_env_fix_receipts() == 0
            assert len([r for r in monitor.store.read_all()
                        if r.get("signal_type") == "env_fix_receipt_unverified"]
                       ) == 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_window_expiry_with_run_dispatch_lands_verified(self):
        """STATE 未迁移但预期类型 run 已派发 → 落地（run 证据通道）零告警。"""
        tmp = tempfile.mkdtemp()
        try:
            monitor, proot, sm = self._seed(Path(tmp), status="blocked")
            runs_dir = Path(proot) / ".fenix" / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            run_file = runs_dir / "verify-demo-1799000000.jsonl"
            run_file.write_text('{"type":"init"}\n', encoding="utf-8")
            st = run_file.stat()
            import os

            os.utime(run_file, (time.time(), time.time()))
            _advance_receipt_window(proot, "demo")

            alerted = monitor._check_env_fix_receipts()

            assert alerted == 0
            assert load_env_fix_receipts(proot) == {}
            final = [r for r in monitor.store.read_all()
                     if r.get("admin_run_id") == "admin-r4"]
            assert final[-1].get("receipt_landing") == "verified"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════
# 3.2 回归锚
# ═════════════════════════════════════════════════════════════════════

class TestRegressionAnchors:
    """3.2：frozen 解冻不变 / 非 blocked 非已修复不迁移 / 窗内落地零告警。"""

    def test_frozen_spec_unfreeze_semantics_unchanged(self):
        """frozen spec：显式 status_after 解冻既有行为不变，不叠加复位迁移。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": _blocked_entry(frozen=True)})
            pm = _FakePmEngine()
            chain, proot = _make_chain(Path(tmp), sm, pm)
            item = {"signal_type": "verify_env_blocked", "spec": "demo"}
            disp = _make_disposition(run_id="admin-f1", result="resolved",
                                     status_after="testing", spec="demo")
            with _merge_mock(0):
                side = chain._close_chain_success(item, disp)

            assert side["unfrozen"] is True
            assert side.get("unfreeze_status") == "testing"
            assert sm.read_one("demo")["frozen"] is False
            # 解冻已到目标态：不叠加 env 复位（无 migrated / 无入队）
            env_side = side.get("env_reverify") or {}
            assert "migrated" not in env_side
            assert pm.handle_event_calls == []
            assert sm.transition_gate_calls == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_frozen_missing_status_after_stays_frozen(self):
        """frozen + 缺显式 status_after：拒绝 parse 兜底留冻结（既有行为），
        接续复位亦被 frozen 守卫拦下（skipped，不迁移）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": _blocked_entry(frozen=True)})
            pm = _FakePmEngine()
            chain, proot = _make_chain(Path(tmp), sm, pm)
            item = {"signal_type": "verify_env_blocked", "spec": "demo"}
            disp = _make_disposition(run_id="admin-f2", result="resolved",
                                     spec="demo")  # 无 status_after
            with _merge_mock(0):
                side = chain._close_chain_success(item, disp)

            assert side["unfrozen"] is False
            assert "unfreeze_error" in side
            assert sm.read_one("demo")["frozen"] is True
            assert sm.read_one("demo")["status"] == "blocked"
            env_side = side.get("env_reverify") or {}
            assert env_side.get("skipped"), env_side
            assert pm.handle_event_calls == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_non_blocked_spec_not_migrated(self):
        """spec 不处于 blocked → 链上不迁移（既有行为不变）。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": {"status": "testing", "branch": "fenix/x",
                                   "frozen": False}})
            pm = _FakePmEngine()
            chain, proot = _make_chain(Path(tmp), sm, pm)
            item = {"signal_type": "verify_env_blocked", "spec": "demo"}
            disp = _make_disposition(run_id="admin-f3", result="resolved",
                                     spec="demo")
            side = chain._close_chain_success(item, disp)
            env_side = side.get("env_reverify") or {}
            assert "spec 不处于 blocked" in str(env_side.get("skipped"))
            assert sm.transition_gate_calls == []
            assert pm.handle_event_calls == []
            assert load_env_fix_receipts(proot) == {}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_non_env_family_signal_not_migrated(self):
        """信号不属环境阻塞自动复位集合 → 链上不迁移。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": _blocked_entry()})
            pm = _FakePmEngine()
            chain, proot = _make_chain(Path(tmp), sm, pm)
            item = {"signal_type": "stuck", "spec": "demo"}
            disp = _make_disposition(run_id="admin-f4", result="resolved",
                                     spec="demo")
            with _merge_mock(0):
                side = chain._close_chain_success(item, disp)
            env_side = side.get("env_reverify") or {}
            assert "环境阻塞自动复位集合" in str(env_side.get("skipped"))
            assert sm.read_one("demo")["status"] == "blocked"
            assert sm.transition_gate_calls == []
            assert load_env_fix_receipts(proot) == {}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_non_fixed_disposition_direct_path_noop(self):
        """直接路径：处置非已修复语义（escalated）→ 零迁移零登记零回执。"""
        tmp = tempfile.mkdtemp()
        try:
            sm = _FakeSm({"demo": _blocked_entry()})
            pm = _FakePmEngine()
            monitor, proot = _make_monitor(Path(tmp), sm, pm)
            signal = {"signal_type": "verify_env_blocked", "spec": "demo"}
            disp = _make_disposition(run_id="admin-f5", result="escalated",
                                     spec="demo")
            with _merge_mock(0):
                monitor._reset_env_blocked_after_disposition(signal, disp)
            assert sm.read_one("demo")["status"] == "blocked"
            assert sm.transition_gate_calls == []
            assert pm.handle_event_calls == []
            assert load_env_fix_reverify_rechecks(proot) == {}
            assert load_env_fix_receipts(proot) == {}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_receipt_landed_within_window_zero_alert(self):
        """窗内静默；窗满时 STATE 已迁移 → verified 零告警（记成功语义）。"""
        tmp = tempfile.mkdtemp()
        try:
            monitor, proot, sm = (
                TestReceiptLandingCheck()._seed(Path(tmp), status="testing",
                                                run_id="admin-r7")
            )
            # 窗内：静默等待
            assert monitor._check_env_fix_receipts() == 0
            assert "demo" in load_env_fix_receipts(proot)
            assert monitor.store.read_all()[-1].get("receipt_landing") is None
            # 窗满：STATE 已在 testing（迁移先行落地）→ 成功语义
            _advance_receipt_window(proot, "demo")
            assert monitor._check_env_fix_receipts() == 0
            assert load_env_fix_receipts(proot) == {}
            final = [r for r in monitor.store.read_all()
                     if r.get("admin_run_id") == "admin-r7"]
            assert final[-1].get("receipt_landing") == "verified"
            assert not [r for r in monitor.store.read_all()
                        if r.get("signal_type") == "env_fix_receipt_unverified"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
