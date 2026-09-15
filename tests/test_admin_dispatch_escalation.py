"""
tests/test_admin_dispatch_escalation.py — admin-dispatch-failure-escalation SPEC 测试。

覆盖 tasks.md 3.1/3.2/3.3：
  3.1 TypeError 注入 → admin_dispatch_programming_error critical（含异常类型/调用点）；
      OSError 注入 → 不归类编程错误。
  3.2 冷却后重试一次（节流不吞、frozen 跳过）；仍失败 retry_count=1 保持升级；
      恢复后重试/后续派发成功 → 升级记录闭环（handled，resolve_note）。
  3.3 回放 stash_pop_conflict dict evidence → 专用升级记录（admin_dispatch_programming_error
      critical，含异常类型/调用点）；admin 活动视图 signal_type 标签归类。
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

from core.admin_store import AdminStore, ESCALATION, SIGNAL, DISPOSITION
from core.admin_monitor import (
    AdminMonitor,
    DISPATCH_RETRY_MAX,
    _PROGRAMMING_ERROR_TYPES,
)
from core.agent_runner.runner import AdminDisposition
from tests.helpers import FakeLogger, utcnow_iso, iso_ago


# ── 轻量替身 ───────────────────────────────────────────────

class FakeSM:
    """极简状态机：仅 read_one / read_all（硬编码 spec 表）。"""

    def __init__(self, specs: dict):
        self._specs = dict(specs)

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)


class RecordingFakeRunner:
    """可编程 AgentRunner 替身：按调用序弹出异常或返回 AdminDisposition。

    exc_queue 为 (Exception|None, …) 列表——第 N 次调用弹 exc_queue[N-1]
    （None 表示正常返回）；队列耗尽后按 fallback_exc 返回（None 即正常
    返回）。调用计数与 calls 列表解耦（calls.clear() 不影响行为）。
    """

    def __init__(self, exc_queue=None, fallback_exc=None):
        self.calls: list = []
        self._exc_queue = list(exc_queue or [])
        self._fallback_exc = fallback_exc
        self._call_idx = 0

    def run_administrator(self, signal):
        self.calls.append(signal)
        idx = self._call_idx
        self._call_idx += 1
        if idx < len(self._exc_queue):
            exc = self._exc_queue[idx]
            if exc is not None:
                raise exc
        elif self._fallback_exc is not None:
            raise self._fallback_exc
        return AdminDisposition(
            run_id=f"admin-test-{idx + 1}",
            spec=signal.get("spec"),
            success=True,
            problem=signal.get("description", ""),
            actions_taken="测试处置",
            result="resolved",
            summary="诊断结论：测试困境；处置时间线：测试处置；结果：已解决。",
        )


def _make_signal(spec="spec-a", signal_type="stuck",
                 evidence="原信号 evidence 文本"):
    return {
        "signal_type": signal_type,
        "spec": spec,
        "severity": "major",
        "description": f"困境 {signal_type}",
        "evidence": evidence,
        "recommended_action": "检查根因",
    }


def _make_monitor(tmp_path, specs, runner, config=None):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    mon = AdminMonitor(
        config or {},
        FakeSM(specs),
        proot,
        FakeLogger(),
        store=AdminStore(proot, FakeLogger()),
        agent_runner=runner,
    )
    return proot, mon


def _rec_id(store, idx=0):
    """返回 store 读取记录中第 idx 条的 id。"""
    recs = store.read_all()
    return recs[idx]["id"] if recs < len(recs) else None


def _escalations(store):
    """返回 kind=escalation 的记录列表（最新在前）。"""
    return [r for r in store.read_all() if r.get("kind") == ESCALATION]


def _has_unhandled(store, spec, signal_type):
    return store.unhandled_for(spec, signal_type) is not None


# ── 3.1 ─────────────────────────────────────────────────────

class TestDispatchProgrammingErrorEscalation:
    """tasks.md 3.1：TypeError 注入 → admin_dispatch_programming_error critical。"""

    def test_typeerror_escalates_programming_error(self, tmp_path):
        runner = RecordingFakeRunner(exc_queue=[TypeError("replace() argument 2 must be str, not dict")])
        spec_name = "evo-test-typeerror"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        signal = _make_signal(spec=spec_name, signal_type="stash_pop_conflict")
        signal_rec = {"id": "sig-test-1"}  # 模拟自动巡检来源

        mon._invoke_administrator(signal, signal_rec)

        escls = _escalations(mon.store)
        prog_errs = [e for e in escls if e.get("signal_type") == "admin_dispatch_programming_error"]

        # 恰好 1 条 admin_dispatch_programming_error
        assert len(prog_errs) == 1, (
            f"预期 1 条 programming_error 升级，实际 {len(prog_errs)} 条；"
            f"全记录={[e.get('signal_type') for e in escls]}"
        )
        rec = prog_errs[0]
        assert rec["spec"] == spec_name
        assert rec["severity"] == "critical"
        # evidence 序列化为 JSON 串（store 归一）
        ev = rec.get("evidence") or ""
        assert isinstance(ev, str)
        ev_parsed = json.loads(ev)
        assert ev_parsed["exception_type"] == "TypeError"
        assert "replace()" in ev_parsed.get("message", "")
        # original_signal 完整
        orig = ev_parsed.get("original_signal", {})
        assert orig.get("signal_type") == "stash_pop_conflict"
        assert orig.get("spec") == spec_name
        # callsite 提取（core/ 内最深帧或提示词占位符处）——至少含行号和函数名
        callsite = ev_parsed.get("callsite") or rec.get("description") or ""
        assert ev_parsed.get("callsite") is not None, "callsite 不应为空"
        assert "(" in ev_parsed["callsite"], f"callsite 格式异常：{ev_parsed['callsite']}"
        # 顶层 original_signal 字段存在（供重试重建）
        assert rec.get("original_signal", {}).get("signal_type") == "stash_pop_conflict"

    def test_unhandled_dedup_same_error_not_double(self, tmp_path):
        """同 spec 已有未处理 programming_error 时不重复落盘（去重）。"""
        runner = RecordingFakeRunner(exc_queue=[TypeError("bug1"), TypeError("bug2")])
        spec_name = "evo-dedup"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        signal = _make_signal(spec=spec_name, signal_type="stuck")

        mon._invoke_administrator(signal, {"id": "s1"})
        mon._invoke_administrator(signal, {"id": "s2"})

        prog_errs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"
                     and not e.get("handled")]
        assert len(prog_errs) == 1, "去重：只应有 1 条未处理 programming_error"

    def test_oserror_not_classified_as_programming_error(self, tmp_path):
        """OSError（运维失败）→ 不归类编程错误，维持原 signal_type 升级。"""
        runner = RecordingFakeRunner(exc_queue=[OSError("Connection refused")])
        spec_name = "evo-oserror"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        signal = _make_signal(spec=spec_name, signal_type="stuck")
        signal_rec = {"id": "sig-os-1"}

        mon._invoke_administrator(signal, signal_rec)

        escls = _escalations(mon.store)
        # 不应有 programming_error
        prog_errs = [e for e in escls if e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(prog_errs) == 0, f"OSError 不应产生 programming_error，实际有 {len(prog_errs)} 条"
        # 原类型升级记录存在，带 next_retry_at（可重试）
        stuck_errs = [e for e in escls
                      if e.get("signal_type") == "stuck"
                      and "Administrator 唤起失败" in (e.get("action_taken") or "")]
        assert len(stuck_errs) == 1
        rec = stuck_errs[0]
        assert rec["severity"] == "major"
        assert rec.get("next_retry_at") is not None, "运维异常升级应带 next_retry_at"
        assert rec.get("retry_count", 0) == 0

    def test_valueerror_also_classified_as_programming_error(self, tmp_path):
        """ValueError（含 JSONDecodeError 子类）→ 归类编程错误。"""
        runner = RecordingFakeRunner(exc_queue=[ValueError("No JSON object could be decoded")])
        _, mon = _make_monitor(tmp_path, {
            "s": {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        mon._invoke_administrator(_make_signal(spec="s"), {"id": "sve"})
        prog_errs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(prog_errs) == 1


# ── 3.2 ─────────────────────────────────────────────────────

class TestDispatchFailureRetry:
    """tasks.md 3.2：冷却后重试一次；仍失败 bump；恢复后闭环。"""

    def test_retry_fires_after_cooldown(self, tmp_path):
        """next_retry_at 过期 → _retry_due_dispatch_failures 触发重试（节流不吞）。"""
        # 第一次派发失败（TypeError），第二次（冷却后重试）成功
        runner = RecordingFakeRunner(exc_queue=[TypeError("boom"), None])
        spec_name = "evo-retry"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s1"})

        # 首次失败落了升级记录且带 next_retry_at
        prog_errs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"
                     and not e.get("handled")]
        assert len(prog_errs) == 1
        fail_rec = prog_errs[0]
        assert fail_rec.get("next_retry_at") is not None

        # 把 next_retry_at 改为过去时间（模拟冷却到期）
        _force_past_retry_due(mon.store, fail_rec["id"])

        calls_before = len(runner.calls)
        retried = mon._retry_due_dispatch_failures(time.time())
        assert retried == 1, f"预期重试 1 条，实际 {retried}"
        # 重试触发了一次 run_administrator（直接调 _invoke_administrator，
        # 未再经 _handle_signal 节流吞掉）
        assert len(runner.calls) == calls_before + 1
        # 重试不新增记录：仍只有 1 条 programming_error escalation
        prog_errs2 = [e for e in _escalations(mon.store)
                      if e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(prog_errs2) == 1, "重试不追加新记录"
        # 重试成功 → 既有记录被闭环
        assert prog_errs2[0]["handled"] is True
        assert prog_errs2[0].get("resolve_note") == "后续派发成功"

    def test_retry_frozen_spec_skipped(self, tmp_path):
        """frozen spec → 跳过重试。"""
        runner = RecordingFakeRunner(exc_queue=[TypeError("freeze-me")])
        spec_name = "evo-frozen"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso(),
                        "frozen": True},
        }, runner)
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s1"})
        _force_past_retry_due(mon.store,
                              [e for e in _escalations(mon.store)
                               if e.get("signal_type") == "admin_dispatch_programming_error"
                               and not e.get("handled")][0]["id"])
        runner.calls.clear()
        retried = mon._retry_due_dispatch_failures(time.time())
        assert retried == 0, "frozen spec 不应触发重试"
        assert len(runner.calls) == 0

    def test_retry_failure_bumps_count_no_new_record(self, tmp_path):
        """重试仍失败 → retry_count bump，不新增记录（上限 1）。"""
        runner = RecordingFakeRunner(exc_queue=[TypeError("a"), TypeError("b")])
        spec_name = "evo-bump"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s1"})
        fail_recs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"
                     and not e.get("handled")]
        assert len(fail_recs) == 1
        _force_past_retry_due(mon.store, fail_recs[0]["id"])
        runner.calls.clear()
        mon._retry_due_dispatch_failures(time.time())
        assert len(runner.calls) == 1
        # retry_count=1
        fail_recs2 = [e for e in _escalations(mon.store)
                      if e.get("signal_type") == "admin_dispatch_programming_error"
                      and not e.get("handled")]
        assert len(fail_recs2) == 1
        assert int(fail_recs2[0].get("retry_count") or 0) == DISPATCH_RETRY_MAX
        # 再扫一次 → retry_count 已达上限，不再重试
        runner.calls.clear()
        mon._retry_due_dispatch_failures(time.time())
        assert len(runner.calls) == 0, "retry_count=1 达上限不应再重试"

    def test_retry_success_closes_failure_alerts(self, tmp_path):
        """重试成功（run_administrator 正常返回）→ 既有升级记录被闭环。"""
        runner = RecordingFakeRunner(exc_queue=[TypeError("fail"), None])
        spec_name = "evo-retry-ok"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s1"})
        fail_recs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"
                     and not e.get("handled")]
        assert len(fail_recs) == 1
        _force_past_retry_due(mon.store, fail_recs[0]["id"])
        mon._retry_due_dispatch_failures(time.time())
        # 重试成功 → 该记录被 handled
        fail_recs_after = [e for e in _escalations(mon.store)
                           if e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(fail_recs_after) == 1
        assert fail_recs_after[0]["handled"] is True
        assert fail_recs_after[0].get("resolve_note") == "后续派发成功"

    def test_subsequent_dispatch_closes_existing_alerts(self, tmp_path):
        """后续正常派发成功（非重试路径）→ 既有派发失败升级记录也被闭环。"""
        runner = RecordingFakeRunner(exc_queue=[TypeError("first-fail")])
        spec_name = "evo-subseq-ok"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s1"})
        fail_recs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"
                     and not e.get("handled")]
        assert len(fail_recs) == 1

        # 第二次正常派发（runner 无异常）
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s2"})
        fail_recs2 = [e for e in _escalations(mon.store)
                      if e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(fail_recs2) == 1
        assert fail_recs2[0]["handled"] is True
        assert fail_recs2[0].get("resolve_note") == "后续派发成功"

    def test_no_residual_critical_after_success(self, tmp_path):
        """恢复后派发成功 → 无残留 critical 升级。"""
        runner = RecordingFakeRunner(exc_queue=[TypeError("fail")])
        spec_name = "evo-no-residue"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s1"})
        # 成功派发闭环
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s2"})
        unhandled = [e for e in _escalations(mon.store) if not e.get("handled")]
        # 无残留未处理 critical 升级（所有派发失败记录已闭环）
        critical_unhandled = [e for e in unhandled
                              if e.get("severity") == "critical"
                              and e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(critical_unhandled) == 0, "不应有残留 critical 派发失败升级"

    def test_manual_dispatch_no_retry_flag(self, tmp_path):
        """manual 派发（signal_rec=None）失败 → 不带 next_retry_at，不参与重试。"""
        runner = RecordingFakeRunner(exc_queue=[TypeError("manual-fail")])
        spec_name = "evo-manual"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        # signal_rec=None 模拟 manual
        mon._invoke_administrator(_make_signal(spec=spec_name), None)
        prog_errs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(prog_errs) == 1
        assert prog_errs[0].get("next_retry_at") is None, "manual 派发不应带 next_retry_at"
        # scan 不会选中（next_retry_at 为 None）
        runner.calls.clear()
        retried = mon._retry_due_dispatch_failures(time.time())
        assert retried == 0
        assert len(runner.calls) == 0

    def test_agent_runner_none_retry_bumps_not_new_record(self, tmp_path):
        """重试时 agent_runner 不可用 → bump 后结束，不落新记录。"""
        runner1 = RecordingFakeRunner(exc_queue=[TypeError("first")])
        spec_name = "evo-runner-none"
        proot, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner1)
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s1"})
        fail_recs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"
                     and not e.get("handled")]
        assert len(fail_recs) == 1
        _force_past_retry_due(mon.store, fail_recs[0]["id"])

        # 模拟 agent_runner 被移除（如 daemon 重启后未恢复）
        mon.agent_runner = None
        retried = mon._retry_due_dispatch_failures(time.time())
        # agent_runner is None → bump 后返回，不落新记录
        # 但 retried 计数仍计入（_invoke_administrator 正常返回了——只是 bump）
        fail_recs2 = [e for e in _escalations(mon.store)
                      if e.get("signal_type") == "admin_dispatch_programming_error"
                      and not e.get("handled")]
        assert len(fail_recs2) == 1, "agent_runner 不可用不新增记录"
        # retry_count 被 bump
        assert int(fail_recs2[0].get("retry_count") or 0) == DISPATCH_RETRY_MAX


# ── 3.3 ─────────────────────────────────────────────────────

class TestReplayStashPopConflictDictEvidence:
    """tasks.md 3.3：回放 stash_pop_conflict dict evidence → 专用升级记录。"""

    def test_dict_evidence_stash_pop_conflict_escalates(self, tmp_path):
        """stash_pop_conflict dict evidence 穿透 str.replace → admin_dispatch_programming_error。"""
        runner = RecordingFakeRunner(exc_queue=[
            TypeError("replace() argument 2 must be str, not dict")
        ])
        spec_name = "evo-stash-replay"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        # 模拟 2026-09-14 实际信号（dict evidence）
        signal = {
            "signal_type": "stash_pop_conflict",
            "spec": spec_name,
            "severity": "major",
            "description": "merge-back stash pop 冲突已自愈",
            "evidence": {
                "conflict_files": ["core/a.py"],
                "stash_kept": True,
            },
            "recommended_action": "核对 stash",
        }
        mon._invoke_administrator(signal, {"id": "sig-stash-1"})

        prog_errs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(prog_errs) == 1, (
            f"stash_pop_conflict dict evidence 应产生 1 条 programming_error，"
            f"实际 {[e.get('signal_type') for e in _escalations(mon.store)]}"
        )
        rec = prog_errs[0]
        assert rec["severity"] == "critical"
        ev_str = rec.get("evidence") or ""
        assert isinstance(ev_str, str)
        ev = json.loads(ev_str)
        assert ev["exception_type"] == "TypeError"
        assert ev["original_signal"]["signal_type"] == "stash_pop_conflict"
        # callsite 非空（指示 prompt_builder 调用点）
        assert ev.get("callsite") is not None
        # 顶层 original_signal 完整
        assert rec["original_signal"]["signal_type"] == "stash_pop_conflict"

    def test_signal_type_label_for_dashboard(self, tmp_path):
        """admin_dispatch_programming_error signal_type 在活动视图可归类查看。

        core/dashboard/data.py:3256 已导出 signal_type，前端 activities/
        index.tsx:148 signalTag 渲染——确保 signal_type 字段准确。
        """
        runner = RecordingFakeRunner(exc_queue=[TypeError("mock")])
        spec_name = "evo-label"
        _, mon = _make_monitor(tmp_path, {
            spec_name: {"status": "implementing", "updated": utcnow_iso()},
        }, runner)
        mon._invoke_administrator(_make_signal(spec=spec_name), {"id": "s1"})
        prog_errs = [e for e in _escalations(mon.store)
                     if e.get("signal_type") == "admin_dispatch_programming_error"]
        assert len(prog_errs) == 1
        rec = prog_errs[0]
        # signal_type 精确匹配，前端按此渲染标签
        assert rec["signal_type"] == "admin_dispatch_programming_error"
        assert rec["spec"] == spec_name


# ── 辅助 ─────────────────────────────────────────────────────

def _force_past_retry_due(store: AdminStore, alert_id: str):
    """把指定升级记录的 next_retry_at 强制改写为过去时间（供测试冷却到期）。"""
    def mutate(records):
        for rec in records:
            if rec.get("id") == alert_id and rec.get("kind") == ESCALATION:
                # 写入 ISO 格式的过去时间（30 分钟前）
                past = datetime.fromtimestamp(
                    time.time() - 30 * 60, tz=timezone.utc
                ).isoformat()
                rec["next_retry_at"] = past
                return True
        return False
    store._mutate(mutate)
