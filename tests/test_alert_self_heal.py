"""基础设施瞬态告警自愈闭环（add-alert-self-heal-marking）测试。

覆盖 tasks 1.4 / 2.2 / 3.2 / 4.2 / 5.3：
- 评估器：安静超窗闭环 / 窗口内复现保持 / env 握手族排除 / spec 附着族
  不双重判定 / handled 不覆盖 / 存量回填推断 / evo 裸升级 / 收敛升级双源锚点
- 写回：auto_self_heal 对 signal 与 escalation 双 kind / handled 跳过 /
  disposition 记录本体逐位不变 / 空解析零写回（mtime 不变）
- 配置：admin.self_heal_quiet_minutes 缺省与脏值回退
- 埋点：注册表登记 → build_trigger/attach_trigger 覆盖三类型；
  _signal_record / _evolution_warn 写入点埋点；merge_signal last_seen 刷新不受影响
- 巡检：run_once 双通道（既有通道不变 + 自愈通道写回）
- 数据层：get_resolved_alerts 收纳自愈 signal 条目、待处理视图不再出现
"""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from core.admin_store import AdminStore, DISPOSITION, ESCALATION, SIGNAL
from core.admin_monitor import AdminMonitor
from core.alert_lifecycle import (
    AUTO_RESOLVE_BY,
    AUTO_SELF_HEAL_BY,
    CONDITION_INFRA_TRANSIENT_SELF_HEALED,
    DEFAULT_SELF_HEAL_QUIET_MINUTES,
    SELF_HEAL_SIGNAL_TYPES,
    attach_trigger,
    build_trigger,
    evaluate_alert,
    find_resolvable,
    find_self_healable,
)
from core.config import ConfigLoader

from test_admin import FakeLogger, FakeSM, make_monitor

WINDOW = DEFAULT_SELF_HEAL_QUIET_MINUTES  # 1440 分钟


# ── 夹具助手 ────────────────────────────────────────────

def iso_minus(minutes: float) -> str:
    """当前时刻往前推 minutes 分钟的 ISO 串（与 AdminStore._utcnow_iso 同形态）。"""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def seed_signal(
    store: AdminStore,
    signal_type="daemon_errors",
    last_seen_minutes_ago=None,
    created_minutes_ago=None,
    **extra,
) -> dict:
    """spec-less signal 条目（daemon 级，携带显式 created/last_seen——
    _normalize_entry 对已带字段 setdefault 不覆写）。"""
    entry = {
        "kind": SIGNAL,
        "signal_type": signal_type,
        "spec": None,
        "severity": "critical",
        "description": "fenixd 日志同错误（指纹 abcd1234）复现 2 次",
    }
    if created_minutes_ago is not None:
        entry["created"] = iso_minus(created_minutes_ago)
    if last_seen_minutes_ago is not None:
        entry["last_seen"] = iso_minus(last_seen_minutes_ago)
    entry.update(extra)
    return store.append(attach_trigger(entry))


def seed_escalation(store: AdminStore, signal_type="daemon_errors", spec=None,
                    admin_run_id=None, created_minutes_ago=None, handled=False,
                    with_trigger=True, **extra) -> dict:
    entry = {
        "kind": ESCALATION,
        "signal_type": signal_type,
        "spec": spec,
        "severity": "critical",
        "description": "Administrator 处置终态未收口（run admin-x-1）",
    }
    if with_trigger:
        attach_trigger(entry)
    if admin_run_id:
        entry["admin_run_id"] = admin_run_id
    if created_minutes_ago is not None:
        entry["created"] = iso_minus(created_minutes_ago)
    if handled:
        entry.update({"handled": True, "handled_at": iso_minus(1), "handled_by": "human"})
    entry.update(extra)
    return store.append(entry)


def seed_disposition(store: AdminStore, admin_run_id, created_minutes_ago=None) -> dict:
    entry = {
        "kind": DISPOSITION,
        "status": "resolved",
        "result": "resolved",
        "signal_type": "daemon_errors",
        "spec": None,
        "admin_run_id": admin_run_id,
        "actions_taken": "重启 daemon",
    }
    if created_minutes_ago is not None:
        entry["created"] = iso_minus(created_minutes_ago)
    return store.append(entry)


# ── 1.4 评估器八组用例 ──────────────────────────────────

class TestSelfHealEvaluation:
    def test_quiet_beyond_window_closes(self, tmp_path):
        """安静超窗的 daemon_errors 信号自动自愈（note 前缀与安静证据）。"""
        store = AdminStore(tmp_path, FakeLogger())
        sig = seed_signal(store, last_seen_minutes_ago=WINDOW + 60,
                          created_minutes_ago=WINDOW + 120)
        now = time.time()
        results = find_self_healable(store.read_all(), now)
        assert len(results) == 1
        assert results[0]["id"] == sig["id"]
        note = results[0]["resolve_note"]
        assert note.startswith("已自愈：")
        assert "daemon_errors" in note
        assert "最近复现" in note and "安静" in note
        # 窗口字面与分钟数入 note（安静时长证据）
        assert str(WINDOW) in note

    def test_recent_last_seen_stays(self, tmp_path):
        """窗口内仍复现（last_seen 距今 < 窗口）：判定返回不可闭环。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_signal(store, last_seen_minutes_ago=30, created_minutes_ago=WINDOW + 120)
        assert find_self_healable(store.read_all(), time.time()) == []

    def test_recent_created_falls_back(self, tmp_path):
        """无 last_seen 回落 created；created 在窗口内同样保持。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_signal(store, created_minutes_ago=10)
        assert find_self_healable(store.read_all(), time.time()) == []

    def test_env_handshake_family_never_closes(self, tmp_path):
        """inconclusive_loop（env 豁免握手族）无论安静多久永不自愈闭环。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_signal(store, signal_type="inconclusive_loop",
                    last_seen_minutes_ago=WINDOW * 10, created_minutes_ago=WINDOW * 10)
        assert find_self_healable(store.read_all(), time.time()) == []
        # evaluate_alert 直判同样保持（注册表外类型不走自愈分支）
        rec = store.read_all()[0]
        assert evaluate_alert(rec, {}, now=time.time(), records=store.read_all()) is None

    def test_unregistered_type_never_closes(self, tmp_path):
        """注册表外 signal_type（如 blocked_stuck 归既有通道）不自愈。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_signal(store, signal_type="blocked_stuck",
                    last_seen_minutes_ago=WINDOW * 5)
        assert find_self_healable(store.read_all(), time.time()) == []

    def test_handled_never_overwritten(self, tmp_path):
        """handled=True（人工记录）自愈判定跳过。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_signal(store, last_seen_minutes_ago=WINDOW * 2, handled=True)
        seed_escalation(store, created_minutes_ago=WINDOW * 2, handled=True)
        assert find_self_healable(store.read_all(), time.time()) == []

    def test_spec_attached_existing_condition_not_double_judged(self):
        """spec 附着族命中既有条件枚举 → 归既有通道，自愈通道不触碰。"""
        alert = {"id": "a", "kind": ESCALATION, "spec": "v2-x",
                 "signal_type": "verify_fail_escalation", "handled": False,
                 "created": iso_minus(WINDOW * 3),
                 "trigger": build_trigger("verify_fail_escalation", "v2-x")}
        # 自愈通道零命中（即便 spec 已终态——那是既有通道的判定对象）
        assert find_self_healable([alert], time.time()) == []
        # 既有通道照常判定
        assert find_resolvable([alert], {"v2-x": {"status": "pushed"}})

    def test_spec_attached_self_heal_type_judged_by_quiet(self, tmp_path):
        """spec 附着的自愈族条目（run_infra_failure 熔断升级）按安静判定，
        不走既有 spec 状态判定（trigger condition 不被既有 _recognized 消费）。"""
        store = AdminStore(tmp_path, FakeLogger())
        esc = seed_escalation(store, signal_type="run_infra_failure", spec="v2-x",
                              created_minutes_ago=WINDOW + 30)
        rec = next(r for r in store.read_all() if r["id"] == esc["id"])
        assert rec["trigger"]["condition"] == CONDITION_INFRA_TRANSIENT_SELF_HEALED
        now = time.time()
        assert len(find_self_healable(store.read_all(), now)) == 1
        # 既有通道不消费该 condition（避免 spec 非 blocked 即「已解除」的误判）
        assert find_resolvable(store.read_all(), {"v2-x": {"status": "implementing"}}) == []

    def test_backfill_inference_note(self, tmp_path):
        """存量回填：无 trigger 的 spec-less 条目按 signal_type 推断参与判定，
        note 注明存量回填且保持「已自愈：」前缀。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_escalation(store, created_minutes_ago=WINDOW + 30, with_trigger=False)
        results = find_self_healable(store.read_all(), time.time())
        assert len(results) == 1
        assert results[0]["resolve_note"].startswith("已自愈：")
        assert results[0]["resolve_note"].endswith("（存量回填）")

    def test_bare_escalation_self_evolution_closes(self, tmp_path):
        """evo 裸升级（self-evolution、无 admin_run_id）按条目自身时间戳超窗闭环。"""
        store = AdminStore(tmp_path, FakeLogger())
        esc = seed_escalation(store, signal_type="self-evolution",
                              created_minutes_ago=WINDOW + 30)
        results = find_self_healable(store.read_all(), time.time())
        assert [r["id"] for r in results] == [esc["id"]]
        assert results[0]["resolve_note"].startswith("已自愈：")
        # 裸升级在窗口内保持
        fresh = seed_escalation(store, signal_type="self-evolution",
                                created_minutes_ago=30)
        assert fresh["id"] not in {r["id"] for r in find_self_healable(store.read_all(), time.time())}

    def test_convergence_escalation_dual_anchor_keeps_on_fresh_signal(self, tmp_path):
        """收敛升级双源锚点：底层 signal 仍在复现（last_seen 新鲜）→ escalation 保持。"""
        store = AdminStore(tmp_path, FakeLogger())
        rid = "admin-v2-x-123"
        seed_disposition(store, rid, created_minutes_ago=WINDOW * 3)
        seed_signal(store, last_seen_minutes_ago=20, created_minutes_ago=WINDOW * 3)
        seed_escalation(store, admin_run_id=rid, created_minutes_ago=WINDOW * 2)
        assert find_self_healable(store.read_all(), time.time()) == []

    def test_convergence_escalation_closes_when_all_quiet(self, tmp_path):
        """收敛升级双源锚点：disposition 与未收口 signal 均安静超窗 → escalation 闭环。"""
        store = AdminStore(tmp_path, FakeLogger())
        rid = "admin-v2-x-456"
        seed_disposition(store, rid, created_minutes_ago=WINDOW * 3)
        seed_signal(store, last_seen_minutes_ago=WINDOW + 90,
                    created_minutes_ago=WINDOW * 3)
        esc = seed_escalation(store, admin_run_id=rid, created_minutes_ago=WINDOW + 200)
        results = find_self_healable(store.read_all(), time.time())
        ids = {r["id"] for r in results}
        assert esc["id"] in ids  # escalation 与底层 signal 同批可自愈
        # note 附底层安静证据
        note = next(r["resolve_note"] for r in results if r["id"] == esc["id"])
        assert note.startswith("已自愈：")

    def test_handled_signal_excluded_from_anchor(self, tmp_path):
        """已收口 signal 不构成复现证据：只剩安静 disposition 与自身时间戳 → 可闭环。"""
        store = AdminStore(tmp_path, FakeLogger())
        rid = "admin-v2-x-789"
        seed_disposition(store, rid, created_minutes_ago=WINDOW * 3)
        seed_signal(store, last_seen_minutes_ago=10, handled=True)
        esc = seed_escalation(store, admin_run_id=rid, created_minutes_ago=WINDOW + 100)
        results = find_self_healable(store.read_all(), time.time())
        assert [r["id"] for r in results] == [esc["id"]]

    def test_quiet_minutes_configurable(self, tmp_path):
        """安静窗口可配（720 分钟生效）。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_signal(store, last_seen_minutes_ago=800, created_minutes_ago=900)
        now = time.time()
        assert find_self_healable(store.read_all(), now, quiet_minutes=720)
        assert find_self_healable(store.read_all(), now, quiet_minutes=1440) == []

    def test_no_now_injected_legacy_path_unchanged(self, tmp_path):
        """未注入 now（既有调用方）自愈分支不启用：spec-less 条目保持 None。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_signal(store, last_seen_minutes_ago=WINDOW * 5)
        seed_escalation(store, created_minutes_ago=WINDOW * 5)
        assert find_resolvable(store.read_all(), {}) == []


# ── 2.2 auto_self_heal 写回 ─────────────────────────────

class TestAutoSelfHeal:
    def test_signal_kind_write_back(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        sig = seed_signal(store, last_seen_minutes_ago=WINDOW * 2)
        results = find_self_healable(store.read_all(), time.time())
        assert store.auto_self_heal(results) == 1
        rec = next(r for r in store.read_all() if r["id"] == sig["id"])
        assert rec["handled"] is True
        assert rec["handled_by"] == AUTO_SELF_HEAL_BY
        assert rec["handled_at"]
        assert rec["resolve_note"].startswith("已自愈：")

    def test_escalation_kind_write_back(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        esc = seed_escalation(store, created_minutes_ago=WINDOW * 2)
        results = find_self_healable(store.read_all(), time.time())
        assert store.auto_self_heal(results) == 1
        rec = next(r for r in store.read_all() if r["id"] == esc["id"])
        assert rec["handled"] is True
        assert rec["handled_by"] == AUTO_SELF_HEAL_BY

    def test_handled_skipped(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        human = seed_escalation(store, created_minutes_ago=WINDOW * 2, handled=True)
        before = next(r for r in store.read_all() if r["id"] == human["id"])
        assert store.auto_self_heal(
            [{"id": human["id"], "resolve_note": "已自愈：x"}]) == 0
        after = next(r for r in store.read_all() if r["id"] == human["id"])
        assert after["handled_by"] == "human"
        assert after["handled_at"] == before["handled_at"]
        assert "resolve_note" not in after

    def test_disposition_record_untouched_bitwise(self, tmp_path):
        """disposition 记录本体逐位不变（result/status 不被改写）。"""
        store = AdminStore(tmp_path, FakeLogger())
        disp = seed_disposition(store, "admin-v2-x-1", created_minutes_ago=WINDOW * 3)
        before = next(r for r in store.read_records() if r["id"] == disp["id"])
        assert before["result"] == "resolved" and before["status"] == "resolved"
        # 即便 resolutions 恶意携带 disposition id 也被拒
        assert store.auto_self_heal(
            [{"id": disp["id"], "resolve_note": "已自愈：x"}]) == 0
        after = next(r for r in store.read_records() if r["id"] == disp["id"])
        assert after == before

    def test_empty_resolutions_zero_write(self, tmp_path):
        """空解析零写回：mtime 不变（含 None / 全 handled 命中）。"""
        store = AdminStore(tmp_path, FakeLogger())
        seed_signal(store, last_seen_minutes_ago=WINDOW * 2, handled=True)
        store.auto_self_heal([])  # 首写建立文件基线
        results = find_self_healable(store.read_all(), time.time())
        assert results == []
        path = tmp_path / ".fenix" / "admin_alerts.json"
        mtime = path.stat().st_mtime_ns
        assert store.auto_self_heal(results) == 0
        assert store.auto_self_heal(None) == 0
        assert path.stat().st_mtime_ns == mtime


# ── 3.2 配置兜底 ────────────────────────────────────────

class TestQuietMinutesConfig:
    def test_default_when_missing(self):
        assert ConfigLoader.get_admin_config({})["self_heal_quiet_minutes"] == 1440

    def test_valid_value_wins(self):
        cfg = ConfigLoader.get_admin_config({"admin": {"self_heal_quiet_minutes": 720}})
        assert cfg["self_heal_quiet_minutes"] == 720

    def test_integer_float_accepted(self):
        cfg = ConfigLoader.get_admin_config({"admin": {"self_heal_quiet_minutes": 180.0}})
        assert cfg["self_heal_quiet_minutes"] == 180

    def test_dirty_values_fall_back(self):
        for dirty in (-1, 0, "abc", True, False, 2.5, None, [90], {"m": 1}):
            cfg = ConfigLoader.get_admin_config(
                {"admin": {"self_heal_quiet_minutes": dirty}})
            assert cfg["self_heal_quiet_minutes"] == 1440, f"dirty={dirty!r}"


# ── 4.1/4.2 写侧埋点 ────────────────────────────────────

class TestRegistryAndTriggerTagging:
    def test_registry_members_map_to_self_heal_condition(self):
        assert set(SELF_HEAL_SIGNAL_TYPES) == {
            "daemon_errors", "run_infra_failure", "self-evolution"}
        for st in SELF_HEAL_SIGNAL_TYPES:
            t = build_trigger(st, None)
            assert t == {"type": st, "spec": None,
                         "condition": CONDITION_INFRA_TRANSIENT_SELF_HEALED}

    def test_inconclusive_loop_not_registered(self):
        assert build_trigger("inconclusive_loop", None) is None

    def test_signal_record_carries_trigger(self):
        """_signal_record 统一埋点：daemon_errors 信号记录落 trigger。"""
        rec = AdminMonitor._signal_record(
            {"signal_type": "daemon_errors", "spec": None, "severity": "critical",
             "description": "d", "evidence": "e", "recommended_action": "r"},
            escalated=False)
        assert rec["trigger"]["condition"] == CONDITION_INFRA_TRANSIENT_SELF_HEALED
        # 未注册类型原样返回（无 trigger）
        rec2 = AdminMonitor._signal_record(
            {"signal_type": "restart_failed", "spec": None, "severity": "critical",
             "description": "d", "evidence": "e", "recommended_action": "r"},
            escalated=False)
        assert "trigger" not in rec2

    def test_merge_signal_last_seen_refresh_preserved(self, tmp_path):
        """last_seen 复现刷新逻辑不被埋点变更破坏：同 hash 沉淀刷 last_seen、
        trigger 保留。"""
        store = AdminStore(tmp_path, FakeLogger())
        sig_rec = AdminMonitor._signal_record(
            {"signal_type": "daemon_errors", "spec": None, "severity": "critical",
             "description": "d", "evidence": "e", "recommended_action": "r"},
            escalated=False)
        first, _ = store.merge_signal(dict(sig_rec), "hash-1")
        rec1 = next(r for r in store.read_records() if r["id"] == first["id"])
        merged, is_new = store.merge_signal(dict(sig_rec), "hash-1")
        assert is_new is False
        assert merged["id"] == first["id"]
        assert merged["trigger"] == rec1["trigger"]
        # 复现刷新：last_seen 前移到刚刚（≥ rec1 的旧值）
        fresh = iso_minus(0)
        assert merged["last_seen"] > rec1["last_seen"] or merged["last_seen"] >= fresh

    def test_evolution_warn_carries_trigger(self):
        """fenixd._evolution_warn 写入点经 attach_trigger 埋点（self-evolution）。"""
        import fenixd

        written = []

        class _Store:
            def append(self, entry):
                written.append(entry)
                return entry

        stub = SimpleNamespace(
            admin_store=_Store(),
            logger=SimpleNamespace(warning=lambda *a, **k: None),
        )
        fenixd.FenixDaemon._evolution_warn(stub, "自进化分析 run evo-1 失败: x")
        assert len(written) == 1
        assert written[0]["signal_type"] == "self-evolution"
        assert written[0]["kind"] == ESCALATION
        assert written[0]["trigger"]["condition"] == CONDITION_INFRA_TRANSIENT_SELF_HEALED


# ── 3.1 巡检双通道接线 ──────────────────────────────────

class TestMonitorDualChannel:
    def test_run_once_self_heals_quiet_transient_alerts(self, tmp_path):
        """run_once：安静超窗的 signal + 收敛升级同批写回 auto-self-heal。"""
        proot, mon = make_monitor(tmp_path, {})
        rid = "admin-v2-x-run1"
        sig = seed_signal(mon.store, last_seen_minutes_ago=WINDOW * 2,
                          created_minutes_ago=WINDOW * 3)
        seed_disposition(mon.store, rid, created_minutes_ago=WINDOW * 3)
        esc = seed_escalation(mon.store, admin_run_id=rid,
                              created_minutes_ago=WINDOW + 100)
        mon.run_once()
        recs = {r["id"]: r for r in mon.store.read_all()}
        assert recs[sig["id"]]["handled"] is True
        assert recs[sig["id"]]["handled_by"] == AUTO_SELF_HEAL_BY
        assert recs[esc["id"]]["handled"] is True
        assert recs[esc["id"]]["handled_by"] == AUTO_SELF_HEAL_BY
        assert recs[sig["id"]]["resolve_note"].startswith("已自愈：")

    def test_run_once_keeps_fresh_alerts_and_zero_write(self, tmp_path):
        """窗口内复现的条目保持待处理；无可自愈条目时零写回。"""
        proot, mon = make_monitor(tmp_path, {})
        seed_signal(mon.store, last_seen_minutes_ago=5, created_minutes_ago=5)
        mon.run_once()
        path = proot / ".fenix" / "admin_alerts.json"
        assert all(not r["handled"] for r in mon.store.read_all())
        mtime = path.stat().st_mtime_ns
        mon.run_once()
        assert path.stat().st_mtime_ns == mtime

    def test_existing_channel_unaffected(self, tmp_path):
        """既有 spec 附着通道不变：verify_fail_escalation 终态照常 auto-resolve。"""
        specs = {"v2-x": {"status": "pushed"}}
        proot, mon = make_monitor(tmp_path, specs)
        entry = {"kind": ESCALATION, "signal_type": "verify_fail_escalation",
                 "spec": "v2-x", "description": "d",
                 "trigger": build_trigger("verify_fail_escalation", "v2-x")}
        alert = mon.store.append(entry)
        mon.run_once()
        rec = next(r for r in mon.store.read_all() if r["id"] == alert["id"])
        assert rec["handled"] is True
        assert rec["handled_by"] == AUTO_RESOLVE_BY


# ── 5.3 数据层映射 ──────────────────────────────────────

class TestDashboardDataMapping:
    def test_resolved_view_includes_self_healed_signal(self, tmp_path):
        from core.dashboard.data import get_resolved_alerts, get_unhandled_alerts

        store = AdminStore(tmp_path, FakeLogger())
        sig = seed_signal(store, last_seen_minutes_ago=WINDOW * 2)
        store.auto_self_heal(find_self_healable(store.read_all(), time.time()))
        # 人工 mark_signal_handled 的信号不进已处理视图（handled_by 缺省）
        manual_sig = seed_signal(store, last_seen_minutes_ago=WINDOW * 2)
        store.mark_signal_handled(manual_sig["id"])
        # 未处理 signal 不出现
        pending_sig = seed_signal(store, last_seen_minutes_ago=5)

        resolved = get_resolved_alerts(tmp_path)
        ids = {r["id"] for r in resolved}
        assert sig["id"] in ids
        assert manual_sig["id"] not in ids
        assert pending_sig["id"] not in ids
        rec = next(r for r in resolved if r["id"] == sig["id"])
        assert rec["handled_by"] == AUTO_SELF_HEAL_BY

        # 待处理视图（escalation 口径）不再出现已自愈条目
        esc = seed_escalation(store, created_minutes_ago=WINDOW * 2)
        store.auto_self_heal(find_self_healable(store.read_all(), time.time()))
        unhandled_ids = {r["id"] for r in get_unhandled_alerts(tmp_path)}
        assert esc["id"] not in unhandled_ids
        assert sig["id"] not in unhandled_ids
