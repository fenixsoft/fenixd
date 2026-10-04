"""admin-orphan-disposition-effect-check：孤儿处置收敛的生效核查补记 + 小步落账测试。

对应 spec/changes/evo-add-admin-orphan-disposition-effect-check 的 tasks 3.1 / 3.2：
  - 3.1  final 组（partially-resolved 终态 + pending 占位）+ 关联 SIGNAL
        （spec=null、escalated=true、handled=false）+ 真实状态证据（STATE
        解冻推进 / 日志 Transition 留痕）→ 补记 resolved（注明补记）并收口
        关联信号；spec 仍 frozen / 日志无留痕 → 不补记、维持滞留升级；
        健康组（信号已 handled）、组内 escalate=true 终结、同 spec 在飞
        run → 跳过
  - 3.2  同一组补记一次后幂等跳过；choice 动作成功后逐动作事件即已落账
        （模拟 run 在 final 落账前死亡）、逐动作事件不含 admin_run_id
        （归并后组不提前 final）、多步 choice 部分失败不出现提前收口与
        resolved 预写
"""

import json

from core.admin_store import AdminStore, SIGNAL, ESCALATION, DISPOSITION
from core.admin_monitor import AdminMonitor, _merge_admin_runs, _spec_has_active_admin_run
from core.agent_runner import AdminDisposition
from tests.helpers import FakeLogger, iso_ago, utcnow_iso


# ── 辅助 ────────────────────────────────────────────────


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return list(self._specs.values())

    def read_one(self, name):
        return self._specs.get(name)


def make_monitor(tmp_path, specs: dict, runner=None):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    store = AdminStore(proot, FakeLogger())
    mon = AdminMonitor(
        {},
        FakeSM(specs),
        proot,
        FakeLogger(),
        store=store,
        agent_runner=runner,
    )
    return proot, mon, store


def _append_signal(store, *, signal_type="daemon_errors", spec=None,
                   escalated=True, handled=False):
    return store.append(
        {
            "kind": SIGNAL,
            "signal_type": signal_type,
            "spec": spec,
            "severity": "critical",
            "description": f"信号 {signal_type}",
            "escalated": escalated,
            "handled": handled,
        }
    )


def _append_disposition(store, *, run_id, status, result, signal_type,
                        spec, escalate=None, created_ago_minutes=None):
    rec = store.append(
        {
            "kind": DISPOSITION,
            "status": status,
            "result": result,
            "signal_type": signal_type,
            "spec": spec,
            "admin_run_id": run_id,
            **({"escalate": escalate} if escalate is not None else {}),
        }
    )
    if created_ago_minutes is not None:
        _backdate(store, rec["id"], created_ago_minutes)
    return rec


def _backdate(store, rec_id, minutes):
    """把某条记录 created 拨回 minutes 分钟前（穿透 grace 门用）。"""
    alerts_path = store.alerts_path
    alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
    for r in alerts:
        if r.get("id") == rec_id:
            r["created"] = iso_ago(minutes)
    alerts_path.write_text(json.dumps(alerts), encoding="utf-8")


def _backdate_group(store, run_id, minutes=130):
    """整组记录（pending 占位 + 终态）统一拨旧——grace 门取组内最新时刻。"""
    for r in store.read_records():
        if r.get("kind") == DISPOSITION and r.get("admin_run_id") == run_id:
            _backdate(store, r["id"], minutes)


def _write_log_transition(proot, spec, ts_iso, channel="manual",
                          note="重派评审（人工裁决）"):
    """写入一条 state_machine 解冻族 Transition 留痕（fenixd.log JSON 行）。"""
    log_dir = proot / ".fenix" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": ts_iso,
        "level": "INFO",
        "component": "state_machine",
        "message": f"Transition: {spec} blocked → reviewing",
        "context": {"channel": channel, "note": note},
    }
    with (log_dir / "fenixd.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _make_final_group(store, *, run_id, spec, signal_type, final_result="partially-resolved",
                      final_escalate=None):
    """构造 429 现场镜像：pending 占位 + 终态记录（同 admin_run_id）。"""
    _append_disposition(store, run_id=run_id, status="pending", result="pending",
                        signal_type=signal_type, spec=spec)
    _append_disposition(store, run_id=run_id, status=final_result,
                        result=final_result, signal_type=signal_type, spec=spec,
                        escalate=final_escalate)
    _backdate_group(store, run_id)


def _backfills(store):
    return [r for r in store.read_records()
            if r.get("kind") == DISPOSITION and r.get("source") == "orphan-backfill"]


def _escalations(store):
    return [r for r in store.read_records() if r.get("kind") == ESCALATION]


def _signal_by_id(store, sig_id):
    return [r for r in store.read_records()
            if r.get("kind") == SIGNAL and r.get("id") == sig_id][0]


# ── 3.1 生效核查收敛路径 ────────────────────────────────


class TestOrphanGroupConvergence:
    def test_global_group_effective_backfills_and_closes_signal(self, tmp_path):
        """429 现场镜像：final 组 + 关联 SIGNAL（spec=null）+ 日志留痕在窗
        → 补记 resolved（注明补记）并收口关联信号。"""
        proot, mon, store = make_monitor(tmp_path, {})
        sig = _append_signal(store, signal_type="daemon_errors", spec=None)
        _make_final_group(store, run_id="admin-global-1", spec="global",
                          signal_type="daemon_errors")
        _write_log_transition(proot, "evo-some-spec", iso_ago(1))
        mon._recover_orphaned_dispositions()
        bfs = _backfills(store)
        assert len(bfs) == 1
        bf = bfs[0]
        assert bf["result"] == "resolved"
        assert bf["admin_run_id"] == "admin-global-1"
        assert bf["signal_type"] == "daemon_errors"
        assert bf["spec"] == "global"
        # 补记留痕：actions_taken/description 注明补记，evidence 引真实状态依据
        assert "补记" in (bf.get("actions_taken") or "") + (bf.get("description") or "")
        assert "Transition" in (bf.get("evidence") or "")
        # 关联信号收口（SIGNAL spec=null 经 None↔"global" 归一化命中）
        assert _signal_by_id(store, sig["id"])["handled"] is True

    def test_spec_group_effective_via_state_backfills(self, tmp_path):
        """spec 组：目标 spec 在 STATE 已解冻推进（frozen=False 且离开
        blocked）→ 补记 resolved 并收口关联信号。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": False, "status": "reviewing"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-spec-a-1", spec="spec-a",
                          signal_type="stuck")
        mon._recover_orphaned_dispositions()
        bfs = _backfills(store)
        assert len(bfs) == 1
        assert bfs[0]["result"] == "resolved"
        assert "frozen=False" in (bfs[0].get("evidence") or "")
        assert _signal_by_id(store, sig["id"])["handled"] is True

    def test_frozen_spec_not_effective_escalates(self, tmp_path):
        """未生效现场（spec 仍 frozen）：不补记、维持滞留并走既有孤儿升级
        （fail-closed），且升级后带 escalate=true 终结记录防重复升级。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": True, "status": "blocked"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-spec-a-2", spec="spec-a",
                          signal_type="stuck")
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        escs = _escalations(store)
        assert len(escs) == 1
        assert escs[0]["admin_run_id"] == "admin-spec-a-2"
        assert escs[0]["severity"] == "critical"
        # escalate=true 终结记录在场（本组后续轮次整体豁免）
        group = [r for r in store.read_records()
                 if r.get("kind") == DISPOSITION
                 and r.get("admin_run_id") == "admin-spec-a-2"]
        assert any((r.get("status") or r.get("result")) == "escalated"
                   and r.get("escalate") is True for r in group)
        # 信号不被误收口
        assert _signal_by_id(store, sig["id"])["handled"] is False

    def test_global_group_without_log_evidence_escalates(self, tmp_path):
        """global 组且对账窗口内无解冻族 Transition 留痕 → 不补记、升级。"""
        proot, mon, store = make_monitor(tmp_path, {})
        _append_signal(store, signal_type="daemon_errors", spec=None)
        _make_final_group(store, run_id="admin-global-2", spec="global",
                          signal_type="daemon_errors")
        # 窗口外的陈旧留痕（早于对账窗口下界：组 created 130 分钟前 − 5 分钟
        # 松弛 → 窗口下界 135 分钟前，180 分钟前的留痕不算证据）
        _write_log_transition(proot, "evo-old-spec", iso_ago(180))
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert len(_escalations(store)) == 1

    def test_healthy_group_never_enters_branch(self, tmp_path):
        """健康组（关联信号已 handled）反例：不进入收敛分支，零新增记录。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": False, "status": "reviewing"}}
        )
        _append_signal(store, signal_type="stuck", spec="spec-a", handled=True)
        _make_final_group(store, run_id="admin-spec-a-3", spec="spec-a",
                          signal_type="stuck")
        before = len(store.read_records())
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert _escalations(store) == []
        assert len(store.read_records()) == before

    def test_escalate_true_terminal_group_skipped(self, tmp_path):
        """组内已有 escalate=true 终结记录 → 跳过（升级人工是唯一出路）。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": False, "status": "reviewing"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-spec-a-4", spec="spec-a",
                          signal_type="stuck", final_result="resolved",
                          final_escalate=True)
        before = len(store.read_records())
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert _escalations(store) == []
        assert len(store.read_records()) == before
        assert _signal_by_id(store, sig["id"])["handled"] is False

    def test_inflight_run_for_same_spec_skips(self, tmp_path):
        """同 spec 存在在飞 run（pending 组）→ 本组不抢先补记/收口。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": False, "status": "reviewing"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        # 旧组已 final（孤儿形态）
        _make_final_group(store, run_id="admin-spec-a-5", spec="spec-a",
                          signal_type="stuck")
        # 新 run 在飞：pending 组（终态未落账），不拨旧（年轻组 pending 路径
        # 亦不处理，且 run 文件缺失时死亡证据门跳过）
        _append_disposition(store, run_id="admin-spec-a-6", status="pending",
                            result="pending", signal_type="stuck", spec="spec-a")
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert _escalations(store) == []
        assert _signal_by_id(store, sig["id"])["handled"] is False

    def test_young_final_group_within_grace_untouched(self, tmp_path):
        """终态刚落账（grace 窗内）→ 不核查不收敛（给 _worker 回写窗口）。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": False, "status": "reviewing"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-spec-a-7", spec="spec-a",
                          signal_type="stuck")
        _backdate_group(store, "admin-spec-a-7", minutes=1)
        before = len(store.read_records())
        mon._recover_orphaned_dispositions()
        assert _backfills(store) == []
        assert _escalations(store) == []
        assert len(store.read_records()) == before
        assert _signal_by_id(store, sig["id"])["handled"] is False


# ── 3.2 幂等 + 小步落账 ────────────────────────────────


class TestBackfillIdempotence:
    def test_second_scan_skips_after_backfill_even_if_signal_reopened(self, tmp_path):
        """补记一次后，即使信号被重新置为未收口，后续扫描轮次幂等跳过
        （不重复补记、不重复收口）。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": False, "status": "reviewing"}}
        )
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-spec-a-8", spec="spec-a",
                          signal_type="stuck")
        mon._recover_orphaned_dispositions()
        assert len(_backfills(store)) == 1
        # 模拟信号被外部重新打开（handled 还原 false）
        alerts_path = store.alerts_path
        alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
        for r in alerts:
            if r.get("kind") == SIGNAL and r.get("id") == sig["id"]:
                r["handled"] = False
                r["handled_at"] = None
        alerts_path.write_text(json.dumps(alerts), encoding="utf-8")
        mon._recover_orphaned_dispositions()
        mon._recover_orphaned_dispositions()
        assert len(_backfills(store)) == 1  # 不重复补记
        assert _escalations(store) == []  # 不误升级

    def test_backfill_record_does_not_break_merge_semantics(self, tmp_path):
        """补记记录（非 pending、携带同组 admin_run_id）不改变组的 final
        归并结果——已 final 组仍 final，_merge_admin_runs 语义兼容。"""
        proot, mon, store = make_monitor(
            tmp_path, {"spec-a": {"frozen": False, "status": "reviewing"}}
        )
        _append_signal(store, signal_type="stuck", spec="spec-a")
        _make_final_group(store, run_id="admin-spec-a-9", spec="spec-a",
                          signal_type="stuck")
        mon._recover_orphaned_dispositions()
        by_run = _merge_admin_runs(store.read_records())
        assert by_run["admin-spec-a-9"]["final"] is True
        assert store.has_disposition_backfill("admin-spec-a-9") is True
        # 未补记的组探测为 False（幂等判据不误报）
        assert store.has_disposition_backfill("admin-other") is False


class _PendingThenDispRunner:
    """run_administrator 替身：先落 pending（唤起锚点），返回带 choice_id 的处置。"""

    def __init__(self, store, *, run_id, result="resolved", choice_id="retry_review"):
        self.store = store
        self.run_id = run_id
        self.result = result
        self.choice_id = choice_id
        self._raw_append = store.append  # 逃逸实例级补丁（死亡模拟用）

    def run_administrator(self, signal):
        self._raw_append(
            {
                "kind": DISPOSITION,
                "status": "pending",
                "result": "pending",
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "admin_run_id": self.run_id,
                "description": f"Administrator 处置中（run {self.run_id}）",
            }
        )
        return AdminDisposition(
            run_id=self.run_id,
            spec=signal.get("spec"),
            success=True,
            problem="评审中断需重派",
            actions_taken="执行 retry_review",
            result=self.result,
            summary="诊断结论：评审中断；处置时间线：重派评审；结果：已解决。",
            choice_id=self.choice_id,
        )


def _choice_signal(store, spec="spec-a", signal_type="stuck"):
    sig = _append_signal(store, signal_type=signal_type, spec=spec)
    signal = {
        "signal_type": signal_type,
        "spec": spec,
        "severity": "critical",
        "description": "评审中断",
    }
    return sig, signal


class TestChoiceStepAccounting:
    def test_step_record_persisted_and_signal_closed_on_ok(self, tmp_path):
        """choice 整体 ok：逐动作事件落账（result=resolved、不含
        admin_run_id）+ 信号提前收口；final 落账后组 final 照旧。"""
        proot, mon, store = make_monitor(tmp_path, {})
        runner = _PendingThenDispRunner(store, run_id="admin-choice-1")
        mon.agent_runner = runner
        sig, signal = _choice_signal(store)
        mon._apply_choice_execution = lambda s, d: {
            "ok": True, "action": "retry_review", "error": None,
            "steps": ["冻结解除", "回 reviewing"],
        }
        mon._invoke_administrator(signal, sig)
        recs = store.read_records()
        steps = [r for r in recs
                 if r.get("kind") == DISPOSITION and r.get("result") == "resolved"
                 and r.get("action_taken") == "retry_review"
                 and not r.get("admin_run_id")]
        assert len(steps) == 1
        # 信号提前收口（choice 整体 ok）
        assert _signal_by_id(store, sig["id"])["handled"] is True
        # 逐动作事件不携带 admin_run_id → 不参与归并，组 final 仅由真实
        # final 记录承载
        by_run = _merge_admin_runs(recs)
        assert by_run["admin-choice-1"]["final"] is True

    def test_step_record_survives_death_before_final(self, tmp_path):
        """模拟 run 在 final 落账前死亡：逐动作事件即已落账、信号已提前
        收口，且归并后组仍判在飞（在飞护栏不因逐动作事件失守）。"""
        proot, mon, store = make_monitor(tmp_path, {})
        runner = _PendingThenDispRunner(store, run_id="admin-choice-2")
        mon.agent_runner = runner
        sig, signal = _choice_signal(store)
        mon._apply_choice_execution = lambda s, d: {
            "ok": True, "action": "retry_review", "error": None, "steps": [],
        }
        real_append = store.append

        def dying_append(entry):
            # 终态记录（携带 admin_run_id）落盘瞬间模拟进程死亡
            if entry.get("kind") == DISPOSITION and entry.get("admin_run_id"):
                raise RuntimeError("simulated crash before final append")
            return real_append(entry)

        store.append = dying_append
        mon._invoke_administrator(signal, sig)
        recs = store.read_records()
        steps = [r for r in recs
                 if r.get("kind") == DISPOSITION and r.get("result") == "resolved"
                 and r.get("action_taken") == "retry_review"]
        assert len(steps) == 1
        assert not steps[0].get("admin_run_id")  # 事件不含 admin_run_id
        # final 记录确未落账（死亡生效），已执行事实由逐动作事件承载
        finals = [r for r in recs
                  if r.get("admin_run_id") == "admin-choice-2"
                  and (r.get("status") or r.get("result")) != "pending"]
        assert finals == []
        # 组仍判在飞（pending 在场且非 final）——在飞护栏不破坏
        assert _spec_has_active_admin_run(store, "spec-a") is True
        # 信号已提前收口
        assert _signal_by_id(store, sig["id"])["handled"] is True

    def test_partial_failure_no_early_close_no_resolved(self, tmp_path):
        """多步 choice 部分失败（整体非 ok）：不提前收口、不预写 resolved；
        失败落 result=failed 审计事件（fail-closed）。"""
        proot, mon, store = make_monitor(tmp_path, {})
        runner = _PendingThenDispRunner(store, run_id="admin-choice-3",
                                        result="failed")
        mon.agent_runner = runner
        sig, signal = _choice_signal(store)
        mon._apply_choice_execution = lambda s, d: {
            "ok": False, "action": "retry_review",
            "error": "第 2 步失败：spec not found",
            "steps": ["冻结解除", "回 reviewing 失败"],
        }
        mon._invoke_administrator(signal, sig)
        recs = store.read_records()
        # 无任何 result=resolved 预写（逐动作事件与终态都不得写 resolved）
        assert not [r for r in recs if r.get("result") == "resolved"]
        # 失败审计事件在场（result=failed、含 action_taken）
        failed_steps = [r for r in recs
                        if r.get("kind") == DISPOSITION
                        and r.get("result") == "failed"
                        and r.get("action_taken") == "retry_review"
                        and not r.get("admin_run_id")]
        assert len(failed_steps) == 1
        # 信号保留待重审（不提前收口；choice 失败留痕分支亦不置 handled）
        assert _signal_by_id(store, sig["id"])["handled"] is False

    def test_skipped_outcome_persists_nothing(self, tmp_path):
        """全局信号 × spec 作用域动作的跳过形态（skipped=True）：未执行任何
        动作，不落逐动作事件、不收口。"""
        proot, mon, store = make_monitor(tmp_path, {})
        runner = _PendingThenDispRunner(store, run_id="admin-choice-4")
        mon.agent_runner = runner
        sig, signal = _choice_signal(store)
        mon._apply_choice_execution = lambda s, d: {
            "ok": False, "skipped": True, "action": "retry_review",
            "error": "全局信号不可执行 spec 作用域动作",
        }
        before = len(store.read_records())
        mon._invoke_administrator(signal, sig)
        recs = store.read_records()
        # 跳过形态不落逐动作事件：除信号记录外，新增仅 pending + final
        # （均携带 admin_run_id），无 admin_run_id 的逐动作事件为零
        assert len(recs) - before == 2
        assert not [r for r in recs
                    if r.get("kind") == DISPOSITION and not r.get("admin_run_id")]
        assert _signal_by_id(store, sig["id"])["handled"] is False
