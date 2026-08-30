"""告警生命周期闭环（add-alert-auto-resolve）测试。

覆盖 tasks 3.1 / 3.2：
- 条件解除（pushed / done / 离开 blocked）→ 自动闭环且字段正确
- handled=True（人工）不被覆盖；未识别 condition 与无 spec 字段不闭环
- 全闭环时零写回（admin_alerts.json mtime 不变）
- 存量回填：6 条 2026-08-29 真实告警形态夹具（verify_fail_escalation +
  blocked_stuck、spec 已 pushed）→ 全部自动闭环（注明「存量回填」）；
  无 spec 字段 / 未知 signal_type 的夹具保持原状
- 写入埋点：pm_engine._send_human_escalation_alert 落 trigger 结构化字段
- 扫描接入：AdminMonitor.run_once 内联闭环 + 启动首轮回填仅一次
"""

import time
from pathlib import Path

from core.admin_store import AdminStore, ESCALATION
from core.admin_monitor import AdminMonitor
from core.alert_lifecycle import (
    AUTO_RESOLVE_BY,
    CONDITION_SPEC_TERMINAL_OR_UNBLOCKED,
    build_trigger,
    find_resolvable,
)
from core.pm_engine import PMEngine

from test_admin import FakeLogger, FakeSM, make_monitor


# ── 夹具助手 ────────────────────────────────────────────

def make_escalation(store: AdminStore, spec=None, signal_type="verify_fail_escalation",
                    trigger=None, handled=False, **extra) -> dict:
    entry = {
        "kind": ESCALATION,
        "signal_type": signal_type,
        "spec": spec,
        "description": "验证连续失败 3 轮，已冻结等待人工裁决",
    }
    if trigger is not None:
        entry["trigger"] = trigger
    if handled:
        entry.update({"handled": True, "handled_at": "2026-08-29T00:00:00+00:00",
                      "handled_by": "human"})
    entry.update(extra)
    return store.append(entry)


def triggered(spec, signal_type="verify_fail_escalation") -> dict:
    return build_trigger(signal_type, spec)


# ── 1.1/3.1 条件解除判定 ────────────────────────────────

class TestEvaluateAlert:
    def test_terminal_pushed_resolves(self):
        alert = {"id": "a", "kind": ESCALATION, "spec": "v2-x",
                 "signal_type": "verify_fail_escalation", "handled": False,
                 "trigger": triggered("v2-x")}
        note = find_resolvable([alert], {"v2-x": {"status": "pushed"}})
        assert len(note) == 1
        assert note[0]["id"] == "a"
        assert "v2-x" in note[0]["resolve_note"]
        assert "pushed" in note[0]["resolve_note"]

    def test_terminal_done_resolves(self):
        alert = {"id": "a", "kind": ESCALATION, "spec": "v2-x",
                 "signal_type": "blocked_stuck", "handled": False,
                 "trigger": triggered("v2-x", "blocked_stuck")}
        assert find_resolvable([alert], {"v2-x": {"status": "done"}})

    def test_left_blocked_resolves(self):
        alert = {"id": "a", "kind": ESCALATION, "spec": "v2-x", "handled": False,
                 "trigger": triggered("v2-x")}
        assert find_resolvable([alert], {"v2-x": {"status": "implementing"}})

    def test_still_blocked_not_resolved(self):
        alert = {"id": "a", "kind": ESCALATION, "spec": "v2-x", "handled": False,
                 "trigger": triggered("v2-x")}
        assert find_resolvable([alert], {"v2-x": {"status": "blocked"}}) == []

    def test_handled_human_never_overwritten(self):
        alert = {"id": "a", "kind": ESCALATION, "spec": "v2-x", "handled": True,
                 "handled_by": "human", "trigger": triggered("v2-x")}
        assert find_resolvable([alert], {"v2-x": {"status": "pushed"}}) == []

    def test_unrecognized_condition_skipped(self):
        alert = {"id": "a", "kind": ESCALATION, "spec": "v2-x", "handled": False,
                 "trigger": {"type": "verify_fail_escalation", "spec": "v2-x",
                             "condition": "some_future_condition"}}
        assert find_resolvable([alert], {"v2-x": {"status": "pushed"}}) == []

    def test_missing_spec_field_skipped(self):
        alert = {"id": "a", "kind": ESCALATION, "spec": None, "handled": False,
                 "signal_type": "verify_fail_escalation",
                 "trigger": triggered(None)}
        assert find_resolvable([alert], {"v2-x": {"status": "pushed"}}) == []

    def test_spec_not_in_state_skipped(self):
        """spec 在状态表中不存在（如已清理的假 spec）：无法判定，保持原状。"""
        alert = {"id": "a", "kind": ESCALATION, "spec": "fake-spec",
                 "handled": False, "trigger": triggered("fake-spec")}
        assert find_resolvable([alert], {"other": {"status": "pushed"}}) == []

    def test_non_escalation_skipped(self):
        alert = {"id": "a", "kind": "signal", "spec": "v2-x", "handled": False,
                 "signal_type": "blocked_stuck",
                 "trigger": triggered("v2-x", "blocked_stuck")}
        assert find_resolvable([alert], {"v2-x": {"status": "pushed"}}) == []

    def test_build_trigger_shape(self):
        t = build_trigger("verify_fail_escalation", "v2-x")
        assert t == {"type": "verify_fail_escalation", "spec": "v2-x",
                     "condition": CONDITION_SPEC_TERMINAL_OR_UNBLOCKED}
        # 未接入枚举的 signal_type 不写 trigger
        assert build_trigger("token_budget", "v2-x") is None


# ── 1.3/3.1 auto_resolve 写回 ───────────────────────────

class TestAutoResolve:
    def test_resolves_with_fields(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        alert = make_escalation(store, spec="v2-x", trigger=triggered("v2-x"))
        specs = {"v2-x": {"status": "pushed"}}
        resolvable = find_resolvable(store.read_all(), specs)
        assert store.auto_resolve(resolvable) == 1
        rec = next(r for r in store.read_all() if r["id"] == alert["id"])
        assert rec["handled"] is True
        assert rec["handled_by"] == AUTO_RESOLVE_BY
        assert rec["handled_at"]
        assert "v2-x" in rec["resolve_note"]
        # 人工记录语义不被伪造（description / created 原样保留）
        assert rec["description"] == "验证连续失败 3 轮，已冻结等待人工裁决"

    def test_zero_write_when_all_handled(self, tmp_path):
        """全闭环时零写回：mtime 不变。"""
        store = AdminStore(tmp_path, FakeLogger())
        make_escalation(store, spec="v2-x", trigger=triggered("v2-x"))
        specs = {"v2-x": {"status": "pushed"}}
        assert store.auto_resolve(find_resolvable(store.read_all(), specs)) == 1
        path = tmp_path / ".fenix" / "admin_alerts.json"
        mtime1 = path.stat().st_mtime_ns
        # 全部已闭环：再扫描无可闭环条目 → 零写回
        assert store.auto_resolve(find_resolvable(store.read_all(), specs)) == 0
        assert path.stat().st_mtime_ns == mtime1

    def test_human_record_not_overwritten_on_write(self, tmp_path):
        """ resolutions 命中已人工处理条目 → 跳过不覆盖。"""
        store = AdminStore(tmp_path, FakeLogger())
        human = make_escalation(store, spec="v2-x", trigger=triggered("v2-x"),
                                handled=True)
        before = next(r for r in store.read_all() if r["id"] == human["id"])
        resolved = store.auto_resolve([
            {"id": human["id"], "spec": "v2-x", "resolve_note": "spec v2-x 已到达终态 pushed"}])
        assert resolved == 0
        after = next(r for r in store.read_all() if r["id"] == human["id"])
        assert after["handled_by"] == "human"
        assert after["handled_at"] == before["handled_at"]
        assert "resolve_note" not in after

    def test_no_resolutions_is_noop(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        assert store.auto_resolve([]) == 0
        assert store.auto_resolve(None) == 0
        assert not (tmp_path / ".fenix" / "admin_alerts.json").exists()


# ── 2.1/3.2 存量回填 ────────────────────────────────────

def seed_legacy_alerts(store: AdminStore) -> list:
    """2026-08-29 真实告警形态：无 trigger 字段的 6 条 handled=False 升级告警。"""
    ids = []
    for st, sig in (("v2-config-page", "verify_fail_escalation"),
                    ("v2-project-list-page", "verify_fail_escalation"),
                    ("v2-project-list-page", "verify_fail_escalation"),
                    ("v2-config-page", "verify_fail_escalation"),
                    ("v2-project-list-page", "blocked_stuck"),
                    ("v2-config-page", "blocked_stuck")):
        rec = make_escalation(store, spec=st, signal_type=sig)
        ids.append(rec["id"])
    return ids


class TestBackfill:
    def test_legacy_alerts_resolved_with_backfill_note(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        seed_legacy_alerts(store)
        specs = {"v2-config-page": {"status": "pushed"},
                 "v2-project-list-page": {"status": "pushed"}}
        resolvable = find_resolvable(store.read_all(), specs, backfill=True)
        assert len(resolvable) == 6
        assert store.auto_resolve(resolvable) == 6
        for rec in store.read_all():
            assert rec["handled"] is True
            assert rec["handled_by"] == AUTO_RESOLVE_BY
            assert rec["resolve_note"].startswith("存量回填")
            assert "pushed" in rec["resolve_note"]

    def test_no_spec_field_stays(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        make_escalation(store, spec=None, signal_type="verify_fail_escalation")
        resolvable = find_resolvable(store.read_all(), {}, backfill=True)
        assert resolvable == []
        assert all(not r["handled"] for r in store.read_all())

    def test_unknown_signal_type_stays(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        make_escalation(store, spec="v2-x", signal_type="manual-intervention")
        make_escalation(store, spec="v2-x", signal_type="stuck")
        resolvable = find_resolvable(
            store.read_all(), {"v2-x": {"status": "pushed"}}, backfill=True)
        assert resolvable == []
        assert all(not r["handled"] for r in store.read_all())

    def test_no_backfill_without_flag(self, tmp_path):
        """常态扫描（backfill=False）不推断无 trigger 的存量告警。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_legacy_alerts(store)
        specs = {"v2-config-page": {"status": "pushed"},
                 "v2-project-list-page": {"status": "pushed"}}
        assert find_resolvable(store.read_all(), specs, backfill=False) == []


# ── 1.2 写入埋点 ────────────────────────────────────────

class TestTriggerTagging:
    def _engine(self, tmp_path) -> PMEngine:
        engine = PMEngine.__new__(PMEngine)
        engine.project_root = tmp_path
        engine.logger = FakeLogger()
        return engine

    def test_verify_fail_escalation_carries_trigger(self, tmp_path):
        engine = self._engine(tmp_path)
        engine._send_human_escalation_alert(
            spec_name="v2-x", signal_type="verify_fail_escalation",
            severity="major", description="d", evidence="e", recommended_action="r")
        rec = AdminStore(tmp_path, FakeLogger()).read_all()[0]
        assert rec["trigger"] == {"type": "verify_fail_escalation", "spec": "v2-x",
                                  "condition": CONDITION_SPEC_TERMINAL_OR_UNBLOCKED}

    def test_unmapped_signal_type_has_no_trigger(self, tmp_path):
        engine = self._engine(tmp_path)
        engine._send_human_escalation_alert(
            spec_name="v2-x", signal_type="warning_stale_triage",
            severity="major", description="d", evidence="e", recommended_action="r")
        rec = AdminStore(tmp_path, FakeLogger()).read_all()[0]
        assert "trigger" not in rec

    def test_explicit_trigger_wins(self, tmp_path):
        engine = self._engine(tmp_path)
        engine._send_human_escalation_alert(
            spec_name="v2-x", signal_type="verify_fail_escalation",
            severity="major", description="d", evidence="e", recommended_action="r",
            trigger={"type": "verify_fail_escalation", "spec": "v2-x",
                     "condition": "spec_reach_terminal_or_unblocked"})
        rec = AdminStore(tmp_path, FakeLogger()).read_all()[0]
        assert rec["trigger"]["condition"] == "spec_reach_terminal_or_unblocked"


# ── 1.3/2.1 扫描接入 ────────────────────────────────────

class TestMonitorScanIntegration:
    def test_run_once_resolves_triggered_alert(self):
        specs = {"v2-x": {"status": "pushed"}}
        proot, mon = make_monitor(Path("/tmp"), specs)
        alert = make_escalation(mon.store, spec="v2-x", trigger=triggered("v2-x"))
        mon.run_once()
        rec = next(r for r in mon.store.read_all() if r["id"] == alert["id"])
        assert rec["handled"] is True
        assert rec["handled_by"] == AUTO_RESOLVE_BY

    def test_first_scan_backfills_once(self, tmp_path):
        specs = {"v2-config-page": {"status": "pushed"},
                 "v2-project-list-page": {"status": "pushed"}}
        proot, mon = make_monitor(tmp_path, specs)
        ids = seed_legacy_alerts(mon.store)
        # 启动首轮扫描：存量回填闭环全部 6 条
        mon.run_once()
        recs = {r["id"]: r for r in mon.store.read_all()}
        assert all(recs[i]["handled"] for i in ids)
        assert all(recs[i]["resolve_note"].startswith("存量回填") for i in ids)
        # 首轮之后：新写入的无 trigger 存量形态告警不再被推断闭环
        late = make_escalation(mon.store, spec="v2-config-page",
                               signal_type="verify_fail_escalation")
        mon.run_once()
        rec = next(r for r in mon.store.read_all() if r["id"] == late["id"])
        assert rec["handled"] is False

    def test_no_pending_alerts_zero_write(self, tmp_path):
        """无待闭环告警时零写回：mtime 不变。"""
        specs = {"v2-x": {"status": "blocked"}}
        proot, mon = make_monitor(tmp_path, specs)
        mon.run_once()  # 首轮回填（无告警，零写回）
        assert not (proot / ".fenix" / "admin_alerts.json").exists()

        # 有告警但 spec 仍 blocked → 判定无可闭环条目 → 文件 mtime 不变
        make_escalation(mon.store, spec="v2-x", trigger=triggered("v2-x"))
        path = proot / ".fenix" / "admin_alerts.json"
        mtime = path.stat().st_mtime_ns
        time.sleep(0.01)
        mon.run_once()
        assert path.stat().st_mtime_ns == mtime
        assert all(not r["handled"] for r in mon.store.read_all())

        # spec 到达终态后的下一轮扫描 → 闭环写回
        mon.state_machine._specs = {"v2-x": {"status": "pushed"}}
        mon.run_once()
        assert all(r["handled"] for r in mon.store.read_all())

    def test_monitor_writes_trigger_for_blocked_stuck_escalation(self, tmp_path):
        """admin_monitor 升级人工路径（agent_runner 缺失）对 blocked_stuck 埋点。"""
        specs = {"v2-x": {"status": "blocked"}}
        proot, mon = make_monitor(tmp_path, specs, runner=None)
        mon._invoke_administrator(
            {"signal_type": "blocked_stuck", "spec": "v2-x", "severity": "critical",
             "description": "d", "evidence": "e", "recommended_action": "r"},
            None)
        recs = [r for r in mon.store.read_all()
                if r.get("kind") == ESCALATION]
        assert len(recs) == 1
        assert recs[0]["trigger"]["condition"] == CONDITION_SPEC_TERMINAL_OR_UNBLOCKED


# ── 4.1 视图分组数据管道 ────────────────────────────────

class TestResolvedPayload:
    def test_resolved_alerts_in_payload(self, tmp_path):
        """/api/alerts 聚合 payload 携带已解决告警（含 handled_by/resolve_note）。"""
        from core.dashboard.data import get_resolved_alerts
        store = AdminStore(tmp_path, FakeLogger())
        pending = make_escalation(store, spec="v2-x", trigger=triggered("v2-x"))
        auto = make_escalation(store, spec="v2-y", trigger=triggered("v2-y"))
        store.auto_resolve([{"id": auto["id"], "resolve_note": "spec v2-y 已到达终态 pushed"}])
        manual = make_escalation(store, spec="v2-z", handled=True)

        resolved = get_resolved_alerts(tmp_path)
        ids = {r["id"] for r in resolved}
        assert auto["id"] in ids and manual["id"] in ids
        assert pending["id"] not in ids
        rec = next(r for r in resolved if r["id"] == auto["id"])
        assert rec["handled_by"] == AUTO_RESOLVE_BY
        assert rec["resolve_note"] == "spec v2-y 已到达终态 pushed"
        assert rec["handled_at"]
