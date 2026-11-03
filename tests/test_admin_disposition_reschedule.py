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
import time
from unittest.mock import MagicMock, patch

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


class TestChainTraceSuppressionAndAttribution:
    """fix-escalation-chain-watchdog-yield-gaps 3.2：看护侧新行为用例。

    覆盖 tasks 3.2 字面清单：链在飞抑制不告警不终结 / 链痕消失兜底升级 /
    归因按 run 终态实证（frozen-terminated、cancelled 击杀、死因不明；
    interrupted 口径由 TestRescheduleIntegration::test_no_signal 终结既有
    用例覆盖，不重复）/ deferred 重派触发与单飞守卫限流。

    seam 策略：链实例与 monitor 共享 proot（chain_state 文件同源），链痕
    直写状态文件构造（chain_signature 单源构签，与 monitor 查询同口径）；
    链派发缝 _dispatch_admin 替身只记录调用。
    """

    SPECS = {"spec-a": {"status": "blocked", "frozen": False}}

    def _install_chain(self, proot):
        from core.pm_engine.escalation_chain import EscalationChain, set_chain

        chain = EscalationChain(proot, FakeLogger())
        chain.set_state_machine(FakeSM(self.SPECS))
        chain.set_runner(MagicMock())
        chain.set_pm(MagicMock())  # 链闭环收口走 pm 门面：替身零人工落盘
        set_chain(chain)
        return chain

    def _write_chain_state(self, proot, in_flight):
        from core.pm_engine.escalation_chain import save_chain_state

        save_chain_state(proot, {
            "version": 1, "signatures": {}, "meta": {},
            "in_flight": in_flight,
        })

    def _write_run(self, proot, run_id, events):
        runs = proot / ".fenix" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{run_id}.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
        )

    def _orphan_fixture(self, tmp_path, run_id="admin-spec-a-1"):
        """孤儿升级前提装置：超时 pending + run 文件末行 error 终态。"""
        proot, mon, store = make_monitor(tmp_path, self.SPECS, config={
            "admin": {"escalation_cooldown_minutes": 15}})
        _append_pending(store, run_id=run_id, created_ago_minutes=20)
        self._write_run(proot, run_id, [
            {"type": "assistant", "message": {"content": []}},
            {"type": "error", "error": "boom"},
        ])
        return proot, mon, store

    def _chain_state_sig(self, proot):
        from core.pm_engine.escalation_chain import chain_signature

        sig, _gran = chain_signature("spec-a", "stuck")
        return sig

    def _dispositions(self, store):
        from core.admin_store import DISPOSITION

        return [r for r in store.read_all() if r.get("kind") == DISPOSITION]

    # ── 链在飞抑制：不告警不终结 ────────────────────────────────────

    def test_chain_inflight_suppresses_orphan_escalation(self, tmp_path):
        proot, mon, store = self._orphan_fixture(tmp_path)
        chain = self._install_chain(proot)
        self._write_chain_state(proot, [{
            "chain_id": "chain-live", "signature": self._chain_state_sig(proot),
            "spec": "spec-a", "phase": "admin", "started_at": utcnow_iso(),
        }])
        mon._recover_orphaned_dispositions()
        assert _escalations(store) == []  # 零告警
        # pending 未被终结（无新增非 pending 处置记录）
        assert [r for r in self._dispositions(store)
                if r.get("status") != "pending"] == []

    def test_deferred_trace_also_suppresses(self, tmp_path):
        proot, mon, store = self._orphan_fixture(tmp_path)
        self._install_chain(proot)
        self._write_chain_state(proot, [{
            "chain_id": "chain-def", "signature": self._chain_state_sig(proot),
            "spec": "spec-a", "phase": "deferred", "yield_to": "admin-x",
            "started_at": utcnow_iso(), "deferred_at": utcnow_iso(),
            "item_signal": {"spec": "spec-a", "signal_type": "stuck"},
        }])
        mon._recover_orphaned_dispositions()
        assert _escalations(store) == []

    def test_arbiter_active_trace_suppresses(self, tmp_path):
        proot, mon, store = self._orphan_fixture(tmp_path)
        self._install_chain(proot)
        sig = self._chain_state_sig(proot)

        class _Lane:
            def snapshot(self):
                return {"active_signatures": [sig]}

        with patch("core.pm_engine.arbiter.get_lane", lambda *a, **k: _Lane()):
            mon._recover_orphaned_dispositions()
        assert _escalations(store) == []

    def test_trace_gone_proceeds_escalation(self, tmp_path):
        # 兜底语义：链痕全部消失（本用例不写链痕）→ 照常升级 + 终结
        proot, mon, store = self._orphan_fixture(tmp_path)
        self._install_chain(proot)
        mon._recover_orphaned_dispositions()
        esc = _escalations(store)
        assert len(esc) == 1
        finals = [r for r in self._dispositions(store)
                  if r.get("status") == "escalated"]
        assert len(finals) == 1  # 升级即终结

    def test_chain_absent_fail_open(self, tmp_path):
        # 链未装配（不 set_chain）→ fail-open 零命中 → 升级照常
        proot, mon, store = self._orphan_fixture(tmp_path)
        mon._recover_orphaned_dispositions()
        assert len(_escalations(store)) == 1

    # ── 归因按 run 终态实证（三态 + 摘录）─────────────────────────

    def _attribution_case(self, tmp_path, events, expected_word):
        proot, mon, store = make_monitor(tmp_path, self.SPECS, config={
            "admin": {"escalation_cooldown_minutes": 15}})
        _append_pending(store, run_id="admin-spec-a-attr", created_ago_minutes=20)
        self._write_run(proot, "admin-spec-a-attr", events)
        mon._recover_orphaned_dispositions()
        esc = _escalations(store)
        assert len(esc) == 1
        desc = str(esc[0].get("description") or "")
        assert expected_word in desc
        evidence = str(esc[0].get("evidence") or "")
        assert "admin-spec-a-attr" in evidence
        assert "run 终态摘录" in evidence
        return desc

    def test_attribution_frozen_terminated(self, tmp_path):
        self._attribution_case(tmp_path, [
            {"type": "assistant", "message": {"content": []}},
            {"type": "frozen-terminated", "reason": "spec frozen"},
        ], "spec 冻结击杀")

    def test_attribution_cancelled(self, tmp_path):
        self._attribution_case(tmp_path, [
            {"type": "assistant", "message": {"content": []}},
            {"type": "cancelled", "by": "user"},
        ], "被取消/击杀")

    def test_attribution_unknown_death(self, tmp_path):
        # 归因词表保守兜底：末行非映射词表（文件证据异常/解析失败防御面）。
        # 方法级直测——巡检路径上有死亡证据门（末行须终态才到升级），终态
        # 词表全类各有专归因（interrupted 走既有已知中断分支），真实巡检流
        # 无法自然构造「过门但无词」形态，直测归因函数的兜底出口。
        proot, mon, store = self._orphan_fixture(tmp_path)
        # 末行 assistant（非终态事件）：不误归因为任何击杀词表
        self._write_run(proot, "admin-spec-a-plain", [
            {"type": "assistant", "message": {"content": []}},
        ])
        attribution, _ = mon._orphan_run_attribution("admin-spec-a-plain")
        assert attribution == "死因不明（run 证据缺失）"
        # run 文件缺失同兜底
        attribution2, _ = mon._orphan_run_attribution("admin-no-such-run")
        assert attribution2 == "死因不明（run 证据缺失）"

    def test_attribution_error_and_gate_blocked_and_result(self, tmp_path):
        # 归因映射词表其余三态（方法级直测）
        proot, mon, store = self._orphan_fixture(tmp_path)
        self._write_run(proot, "run-err", [
            {"type": "assistant", "message": {"content": []}},
            {"type": "error", "error": "boom"},
        ])
        self._write_run(proot, "run-gate", [
            {"type": "assistant", "message": {"content": []}},
            {"type": "gate-blocked", "gate": "deliverable"},
        ])
        self._write_run(proot, "run-result", [
            {"type": "assistant", "message": {"content": []}},
            {"type": "result", "subtype": "error_max_turns"},
        ])
        assert "error 终态" in mon._orphan_run_attribution("run-err")[0]
        assert "gate-blocked 终态" in mon._orphan_run_attribution("run-gate")[0]
        assert "非成功结论" in mon._orphan_run_attribution("run-result")[0]

    # ── deferred 重派触发与等待条件 ─────────────────────────────────

    def _deferred_fixture(self, tmp_path, *, yield_to, sig_overrides=None):
        """deferred 留痕 + 共享链实例装置；返回 (proot, mon, store, chain, sent)。"""
        proot, mon, store = make_monitor(tmp_path, self.SPECS, config={
            "admin": {"escalation_cooldown_minutes": 15}})
        chain = self._install_chain(proot)
        sent = []
        chain._dispatch_admin = lambda item: sent.append(dict(item)) or AdminDisposition(
            run_id="admin-resumed", spec="spec-a", success=True,
            problem="p", actions_taken="a", result="resolved",
            summary="诊断结论：x；处置时间线：y；结果：已解决。",
        )
        snap = {
            "spec": "spec-a", "signal_type": "stuck", "severity": "critical",
            "description": "信号 stuck", "evidence": "e", "recommended_action": "r",
            "source": "unit-test", "signature": self._chain_state_sig(proot),
        }
        snap.update(sig_overrides or {})
        self._write_chain_state(proot, [{
            "chain_id": "chain-def-1", "signature": self._chain_state_sig(proot),
            "spec": "spec-a", "phase": "deferred", "yield_to": yield_to,
            "started_at": utcnow_iso(), "deferred_at": utcnow_iso(),
            "item_signal": snap,
        }])
        return proot, mon, store, chain, sent

    def _drain(self, chain, timeout_s=10.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if chain._queue.unfinished_tasks == 0 and not chain._active:
                return True
            time.sleep(0.01)
        return False

    def test_deferred_rescan_resumes_after_yielded_run_dies(self, tmp_path):
        proot, mon, store, chain, sent = self._deferred_fixture(
            tmp_path, yield_to="admin-spec-a-dead")
        self._write_run(proot, "admin-spec-a-dead", [
            {"type": "assistant", "message": {"content": []}},
            {"type": "error", "error": "boom"},  # 被让行 run 已死（终态）
        ])
        assert mon._scan_deferred_chain_items() == 1  # 重派触发
        assert self._drain(chain)
        assert len(sent) == 1  # 链头照常派发（互斥无活 run）
        from core.pm_engine.escalation_chain import load_chain_state

        # 留痕条目已被 resubmit 清除（处置成功闭环）
        assert load_chain_state(proot)["in_flight"] == []

    def test_deferred_rescan_waits_while_yielded_run_alive(self, tmp_path):
        proot, mon, store, chain, sent = self._deferred_fixture(
            tmp_path, yield_to="admin-spec-a-live")
        self._write_run(proot, "admin-spec-a-live", [
            {"type": "assistant", "message": {"content": []}},  # 非终态=仍在飞
        ])
        assert mon._scan_deferred_chain_items() == 0  # 让行理由存续，等
        assert len(sent) == 0
        from core.pm_engine.escalation_chain import load_chain_state

        assert len(load_chain_state(proot)["in_flight"]) == 1  # 条目保留

    def test_deferred_rescan_frozen_item_waits_unfreeze(self, tmp_path):
        proot, mon, store, chain, sent = self._deferred_fixture(
            tmp_path, yield_to="")  # frozen 预检件（无被让行对象）
        self.SPECS["spec-a"]["frozen"] = True  # 仍冻结（FakeSM 直改）
        assert mon._scan_deferred_chain_items() == 0  # 等
        assert len(sent) == 0
        self.SPECS["spec-a"]["frozen"] = False  # 解冻 → 重派条件满足
        assert mon._scan_deferred_chain_items() == 1
        assert self._drain(chain)
        assert len(sent) == 1

    def test_deferred_rescan_signal_closed_clears_only(self, tmp_path):
        self.SPECS["spec-a"]["status"] = "pushed"  # 信号收口（spec 终态）
        try:
            proot, mon, store, chain, sent = self._deferred_fixture(
                tmp_path, yield_to="admin-spec-a-dead")
            assert mon._scan_deferred_chain_items() == 0  # 仅清条目不重派
            assert len(sent) == 0
            from core.pm_engine.escalation_chain import load_chain_state

            assert load_chain_state(proot)["in_flight"] == []
        finally:
            self.SPECS["spec-a"]["status"] = "blocked"

    def test_deferred_rescan_queue_full_keeps_entry(self, tmp_path):
        # 单飞守卫限流：链队列满（submit_entry 撞 RuntimeError）→
        # resubmit_deferred 返回 queue-full → 留痕条目保留待下轮。
        # 缝在 submit_entry 抛单飞满载异常（worker 异步消费使真实满载
        # 无法确定性维持），resubmit 的限流分支与 scan 的 queue-full
        # 处理真实执行。
        from core.pm_engine.escalation_chain import load_chain_state

        proot, mon, store, chain, sent = self._deferred_fixture(
            tmp_path, yield_to="admin-spec-a-dead")
        with patch(
            "core.pm_engine.escalation_chain.EscalationChain.submit_entry",
            side_effect=RuntimeError("处置链单飞队列已满（maxsize=8）"),
        ):
            assert mon._scan_deferred_chain_items() == 0  # 限流：零重派
        assert len(sent) == 0
        # deferred 留痕条目保留待下轮
        assert len(load_chain_state(proot)["in_flight"]) == 1
