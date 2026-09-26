"""admin-disposition-reschedule：孤儿处置自动重派测试。

对应 spec/changes/evo-admin-disposition-reschedule 的 tasks 1.3 / 3.1-3.6：
  - 1.3  unhandled_signal_for：未处理且 escalated 的信号返回记录、
        escalated=False 的节流沉淀记录不返回、spec 不等不返回、
        handled=true 返回 None、多 signal_type 互不影响
  - 3.1  信号未处理 + 中断 run 超时 → 重派（新 run 的 pending disposition
        生成，admin_run_id 变更）且原 disposition 追加 status=superseded
        记录（非 interrupted）
  - 3.2  无未处理信号记录 → 仍终结 interrupted 不重派
  - 3.3  连续重派超限（3 次中断，reschedule_count 依次 0→1→2）→ 第 3 次
        产生 escalation（kind=escalation，severity=critical）且不再重派，
        同时该 run 获非 pending 终结记录
  - 3.4  已有在飞 admin run（同 (spec, signal_type) 的 pending disposition）
        → 去重跳过，不产生新 run
  - 3.5  重派后的新 run 再次中断 → 再次进入重派判定（计数递增而非被跳过）
"""

import json

from core.admin_store import AdminStore, SIGNAL, ESCALATION, DISPOSITION
from core.admin_monitor import AdminMonitor
from core.agent_runner import AdminDisposition
from tests.helpers import FakeLogger, utcnow_iso, iso_ago


# ── 辅助 ────────────────────────────────────────────────


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)


class RescheduleRunner:
    """run_administrator 替身：先落 pending disposition，再返回最终处置。

    对齐真实 maintenance_runs.py:182 行为——唤起前先落 pending 记录（新 run
    的孤儿可检测性由它承载），返回后由 _invoke_administrator 落最终记录。
    run_id 按调用序号生成（每次不同，供断言「admin_run_id 变更」）。
    """

    def __init__(self, store: AdminStore, result: str = "resolved"):
        self.store = store
        self.result = result
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        # run_id 与手工构造的原 run（admin-spec-a-N）明确区分，供断言
        # 「admin_run_id 变更」；每次调用序号递增
        run_id = f"admin-{signal.get('spec')}-resched-{len(self.calls)}"
        self.store.append(
            {
                "kind": DISPOSITION,
                "status": "pending",
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "admin_run_id": run_id,
                "description": f"Administrator 处置中（run {run_id}）",
                "result": "pending",
            }
        )
        return AdminDisposition(
            run_id=run_id,
            spec=signal.get("spec"),
            success=True,
            problem=signal.get("description", ""),
            actions_taken="测试处置",
            result=self.result,
            summary="诊断结论：测试困境；处置时间线：测试处置；结果：已解决。",
        )


def make_monitor(tmp_path, specs: dict, runner=None, config=None):
    """构造 AdminMonitor 夹具。

    runner 传 RescheduleRunner 类（或 None）——runner 需要与 monitor 共享
    store（run_administrator 落盘的 pending 记录须与断言读的同一文件）。
    """
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    store = AdminStore(proot, FakeLogger())
    runner_inst = runner(store) if runner is not None else None
    mon = AdminMonitor(
        config or {},
        FakeSM(specs),
        proot,
        FakeLogger(),
        store=store,
        agent_runner=runner_inst,
    )
    return proot, mon, store


def _append_signal(store, *, signal_type="stuck", spec="spec-a", escalated=True,
                   handled=False, sig_id=None):
    """落一条 kind=signal 记录（escalated 默认 True——唤起锚点）。"""
    return store.append(
        {
            "kind": SIGNAL,
            "signal_type": signal_type,
            "spec": spec,
            "severity": "critical",
            "description": f"信号 {signal_type}",
            "escalated": escalated,
            "handled": handled,
            **({"id": sig_id} if sig_id else {}),
        }
    )


def _append_pending(store, *, run_id="admin-spec-a-1", signal_type="stuck",
                    spec="spec-a", created_ago_minutes=20):
    """落一条 pending disposition，并把 created 拨回 created_ago_minutes 分钟前。"""
    rec = store.append(
        {
            "kind": DISPOSITION,
            "status": "pending",
            "result": "pending",
            "signal_type": signal_type,
            "spec": spec,
            "admin_run_id": run_id,
        }
    )
    alerts_path = store.alerts_path
    alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
    for r in alerts:
        if r.get("id") == rec["id"]:
            r["created"] = iso_ago(created_ago_minutes)
    alerts_path.write_text(json.dumps(alerts), encoding="utf-8")
    return rec


def _write_interrupted_run(proot, run_id):
    """写入含 interrupted 标记的 run 产物文件（agent_runner 关闭时写入）。"""
    runs = proot / ".fenix" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": []}}) + "\n"
        + json.dumps({"type": "interrupted", "reason": "daemon shutdown",
                      "by": "agent_runner"}) + "\n",
        encoding="utf-8",
    )


def _escalations(store):
    return [r for r in store.read_all() if r.get("kind") == ESCALATION]


def _revert_signal_handled(store, sig_id):
    """还原信号的 handled 回写（替身保真，配合多轮重派模拟）。

    真实链路中「重派后的 run 于落最终记录前被杀」时，处置终态回写
    （_invoke_administrator 末尾的 mark_signal_handled）位于最终记录落盘
    之后、同样不会发生。RescheduleRunner 替身同步返回 resolved 会触发该
    回写，使下一轮巡检因信号已 handled 而无法再进入重派判定，与「再次
    中断 → 再次重派」的模拟前提相悖；此处还原 handled 族字段，保持替身
    与真实中断场景一致。
    """
    alerts_path = store.alerts_path
    alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
    for r in alerts:
        if r.get("kind") == SIGNAL and r.get("id") == sig_id:
            r["handled"] = False
            r["handled_at"] = None
    alerts_path.write_text(json.dumps(alerts), encoding="utf-8")


# ── 1.3 unhandled_signal_for ────────────────────────────


class TestUnhandledSignalFor:
    def test_returns_unhandled_escalated_signal(self, tmp_path):
        """未处理且 escalated 的信号记录 → 返回该记录。"""
        store = AdminStore(tmp_path / "proj", FakeLogger())
        rec = _append_signal(store, signal_type="stuck", spec="spec-a")
        out = store.unhandled_signal_for("spec-a", "stuck")
        assert out is not None
        assert out["id"] == rec["id"]
        assert out["kind"] == SIGNAL

    def test_returns_latest_match(self, tmp_path):
        """多条命中时返回最新一条（created 倒序）。"""
        store = AdminStore(tmp_path / "proj", FakeLogger())
        r1 = _append_signal(store, signal_type="stuck", spec="spec-a")
        r2 = _append_signal(store, signal_type="stuck", spec="spec-a")
        out = store.unhandled_signal_for("spec-a", "stuck")
        assert out["id"] == r2["id"]  # 最新一条

    def test_throttled_sediment_not_returned(self, tmp_path):
        """escalated=False 的节流沉淀记录 → 不返回（从未实际唤起过）。"""
        store = AdminStore(tmp_path / "proj", FakeLogger())
        _append_signal(store, signal_type="stuck", spec="spec-a", escalated=False)
        assert store.unhandled_signal_for("spec-a", "stuck") is None

    def test_spec_mismatch_not_returned(self, tmp_path):
        """spec 不严格相等 → 不返回（不做宽松匹配）。"""
        store = AdminStore(tmp_path / "proj", FakeLogger())
        _append_signal(store, signal_type="stuck", spec="spec-a")
        assert store.unhandled_signal_for("spec-b", "stuck") is None
        # spec=None 请求不匹配有 spec 的记录
        assert store.unhandled_signal_for(None, "stuck") is None

    def test_handled_signal_not_returned(self, tmp_path):
        """handled=true 的信号记录 → 返回 None。"""
        store = AdminStore(tmp_path / "proj", FakeLogger())
        _append_signal(store, signal_type="stuck", spec="spec-a", handled=True)
        assert store.unhandled_signal_for("spec-a", "stuck") is None

    def test_signal_type_isolated(self, tmp_path):
        """多 signal_type 互不影响。"""
        store = AdminStore(tmp_path / "proj", FakeLogger())
        _append_signal(store, signal_type="stuck", spec="spec-a")
        _append_signal(store, signal_type="flapping", spec="spec-a")
        assert store.unhandled_signal_for("spec-a", "stuck") is not None
        assert store.unhandled_signal_for("spec-a", "flapping") is not None
        assert store.unhandled_signal_for("spec-a", "repeated_failures") is None

    def test_escalation_records_not_matched(self, tmp_path):
        """kind=escalation 记录不参与本查询（与 unhandled_for 分工）。"""
        store = AdminStore(tmp_path / "proj", FakeLogger())
        store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "spec-a",
                      "escalated": True})
        assert store.unhandled_signal_for("spec-a", "stuck") is None


# ── 3.x 重派闭环集成测试 ────────────────────────────────


class TestRescheduleIntegration:
    def test_signal_unhandled_interrupted_run_reschedules(self, tmp_path):
        """3.1 信号未处理 + 中断 run 超时 → 重派（新 run pending 生成，
        admin_run_id 变更）且原 disposition 追加 superseded（非 interrupted）。"""
        proot, mon, store = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}},
            runner=RescheduleRunner)
        # 底层信号：escalated ∧ 未 handled
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")
        pending = _append_pending(store, run_id="admin-spec-a-1")
        _write_interrupted_run(proot, "admin-spec-a-1")

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        # 原 run 追加 superseded 记录（同 admin_run_id），非 interrupted
        superseded = [r for r in recs
                      if (r.get("status") or r.get("result")) == "superseded"]
        assert len(superseded) == 1
        assert superseded[0]["admin_run_id"] == pending["admin_run_id"]
        assert superseded[0]["reschedule_count"] == 1
        assert f"signal {sig['id']} still unhandled" in superseded[0]["actions_taken"]
        # 不产生 interrupted 终结
        assert not any((r.get("status") or r.get("result")) == "interrupted"
                       for r in recs)
        # 不产生人工升级
        assert _escalations(store) == []
        # 重派产生新 run 的 pending 记录（admin_run_id 变更），由 runner 落盘
        new_pendings = [r for r in recs
                        if (r.get("status") or r.get("result")) == "pending"
                        and r["admin_run_id"] != pending["admin_run_id"]]
        assert len(new_pendings) == 1
        assert new_pendings[0]["signal_type"] == "stuck"
        assert new_pendings[0]["spec"] == "spec-a"

    def test_no_signal_keeps_interrupted_termination(self, tmp_path):
        """3.2 无未处理信号记录 → 仍终结 interrupted 不重派（回归兼容）。"""
        proot, mon, store = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        # 无任何信号记录
        _append_pending(store, run_id="admin-spec-a-1")
        _write_interrupted_run(proot, "admin-spec-a-1")

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        interrupted = [r for r in recs
                       if (r.get("status") or r.get("result")) == "interrupted"]
        assert len(interrupted) == 1
        assert not any((r.get("status") or r.get("result")) == "superseded"
                       for r in recs)
        assert _escalations(store) == []
        # runner 未被唤起（无新 run）
        assert len([r for r in recs if (r.get("status") or r.get("result")) == "pending"]) == 1

    def test_signal_not_escalated_keeps_interrupted_termination(self, tmp_path):
        """仅节流沉淀（escalated=False）的信号 → 不重派，终结 interrupted。"""
        proot, mon, store = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        _append_signal(store, signal_type="stuck", spec="spec-a", escalated=False)
        _append_pending(store, run_id="admin-spec-a-1")
        _write_interrupted_run(proot, "admin-spec-a-1")

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        assert any((r.get("status") or r.get("result")) == "interrupted"
                   for r in recs)
        assert not any((r.get("status") or r.get("result")) == "superseded"
                       for r in recs)

    def test_reschedule_limit_escalates(self, tmp_path):
        """3.3 连续重派超限（3 次中断）→ 第 3 次产生 escalation critical 且
        不再重派，同时该 run 获非 pending 终结记录。"""
        proot, mon, store = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}},
            runner=RescheduleRunner)
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")

        # 第 1 次中断 → 重派（reschedule_count 0→1）
        _append_pending(store, run_id="admin-spec-a-1")
        _write_interrupted_run(proot, "admin-spec-a-1")
        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        assert any((r.get("status") or r.get("result")) == "superseded"
                   and r.get("reschedule_count") == 1 for r in recs)
        assert _escalations(store) == []
        # 真实场景：被重派的 run 未落最终记录即被杀 → handled 回写不会发生，
        # 信号仍可被下轮巡检回溯（替身同步 resolved 触发了回写，须还原）
        _revert_signal_handled(store, sig["id"])

        # 第 2 次中断（新 run）→ 再重派（1→2）
        _append_pending(store, run_id="admin-spec-a-2")
        _write_interrupted_run(proot, "admin-spec-a-2")
        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        assert any((r.get("status") or r.get("result")) == "superseded"
                   and r.get("reschedule_count") == 2 for r in recs)
        assert _escalations(store) == []
        _revert_signal_handled(store, sig["id"])

        # 第 3 次中断 → 超限：不再重派，升级人工 + escalated 终结记录
        _append_pending(store, run_id="admin-spec-a-3")
        _write_interrupted_run(proot, "admin-spec-a-3")
        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        esc = _escalations(store)
        assert len(esc) == 1
        assert esc[0]["kind"] == ESCALATION
        assert esc[0]["severity"] == "critical"
        assert "重派" in esc[0]["description"] or "中断" in esc[0]["description"]
        assert any(r.get("admin_run_id") == "admin-spec-a-3"
                   and (r.get("status") or r.get("result")) == "escalated"
                   for r in recs)
        # 不再产生 superseded（第 3 次未重派）
        superseded = [r for r in recs
                      if (r.get("status") or r.get("result")) == "superseded"]
        assert len(superseded) == 2

        # 再次巡检：不得重复升级（终结记录已判 final）
        mon._recover_orphaned_dispositions()
        assert len(_escalations(store)) == 1

    def test_inflight_run_dedup_skips_reschedule(self, tmp_path):
        """3.4 已有在飞 admin run（同 (spec, signal_type) 的 pending disposition）
        → 去重跳过，不产生新 run。"""
        proot, mon, store = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}},
            runner=RescheduleRunner)
        _append_signal(store, signal_type="stuck", spec="spec-a")
        # 在飞的 run：pending disposition（未超时，created 拨回 20 分钟前但
        # 由另一条 pending 记录承载——直接构造「该 run 有 pending」即可）
        pending = _append_pending(store, run_id="admin-spec-a-1")
        _append_pending(store, run_id="admin-spec-a-active", created_ago_minutes=1)
        _write_interrupted_run(proot, "admin-spec-a-1")

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        # 去重：不产生 superseded，也不唤起新 run
        assert not any((r.get("status") or r.get("result")) == "superseded"
                       for r in recs)
        # 在飞 run 的 pending 仍在
        assert any(r.get("admin_run_id") == "admin-spec-a-active"
                   and (r.get("status") or r.get("result")) == "pending"
                   for r in recs)
        # 原中断 run 被终结为 interrupted（回落原逻辑），不升级
        assert any(r.get("admin_run_id") == pending["admin_run_id"]
                   and (r.get("status") or r.get("result")) == "interrupted"
                   for r in recs)
        assert _escalations(store) == []

    def test_rescheduled_run_reinterrupted_counts_up(self, tmp_path):
        """3.5 重派后的新 run 再次中断 → 再次进入重派判定（计数递增而非被跳过）。
        验证 by_run 归并未把新 run 误判为 final。"""
        proot, mon, store = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}},
            runner=RescheduleRunner)
        sig = _append_signal(store, signal_type="stuck", spec="spec-a")

        # 第一次：中断 run 触发重派 → 新 run 的 pending 记录由 runner 落盘
        _append_pending(store, run_id="admin-spec-a-1")
        _write_interrupted_run(proot, "admin-spec-a-1")
        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        superseded = [r for r in recs
                      if (r.get("status") or r.get("result")) == "superseded"]
        assert len(superseded) == 1
        assert superseded[0]["reschedule_count"] == 1
        # 新 run 的 pending 记录（与原 run 不同 admin_run_id）
        new_run_pending = [r for r in recs
                           if (r.get("status") or r.get("result")) == "pending"
                           and r["admin_run_id"] != "admin-spec-a-1"]
        assert len(new_run_pending) == 1
        new_run_id = new_run_pending[0]["admin_run_id"]

        # 第二次：新 run 再次被中断——模拟 run 跑超 grace 后在落最终记录前被杀：
        # 撤掉 _invoke_administrator 已写的最终记录，仅保留 pending + interrupted
        # 标记，并把该 pending 的 created 拨回超 grace（真实场景 run 已跑超 15 分钟）
        alerts_path = store.alerts_path
        alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
        kept = []
        for r in alerts:
            if r.get("kind") == DISPOSITION and r.get("admin_run_id") == new_run_id \
                    and (r.get("status") or r.get("result")) != "pending":
                continue  # 撤掉新 run 的最终记录（模拟 die 于最终落盘前）
            kept.append(r)
        for r in kept:
            if r.get("kind") == DISPOSITION and r.get("admin_run_id") == new_run_id:
                r["created"] = iso_ago(20)  # 拨回超 grace
        alerts_path.write_text(json.dumps(kept), encoding="utf-8")
        # 同上：真实场景 run 死于最终记录落盘前，handled 回写不会发生，还原之
        _revert_signal_handled(store, sig["id"])
        _write_interrupted_run(proot, new_run_id)

        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        superseded = [r for r in recs
                      if (r.get("status") or r.get("result")) == "superseded"]
        # 第二次重派：reschedule_count 递增为 2（而非被跳过）
        assert len(superseded) == 2
        assert any(r.get("reschedule_count") == 2 for r in superseded)
        assert _escalations(store) == []

    def test_superseded_run_not_reprocessed_next_round(self, tmp_path):
        """重派（superseded）后下轮巡检不再处理原 run（终结即 final，去重）。"""
        proot, mon, store = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}},
            runner=RescheduleRunner)
        _append_signal(store, signal_type="stuck", spec="spec-a")
        _append_pending(store, run_id="admin-spec-a-1")
        _write_interrupted_run(proot, "admin-spec-a-1")

        mon._recover_orphaned_dispositions()
        mon._recover_orphaned_dispositions()  # 再次巡检

        recs = store.read_all()
        superseded = [r for r in recs
                      if (r.get("status") or r.get("result")) == "superseded"]
        assert len(superseded) == 1  # 只重派一次
