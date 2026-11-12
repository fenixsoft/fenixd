"""add-escalation-chain-admin-arbiter：处置链核心测试。

1.1 防自环清单：_send_human_escalation_alert 与 freeze_for_human 全调用点
机械枚举并标注来源（框架信号 / 链成员产出）——框架信号经 family 咽喉入链
头，链成员产出走链终点直写（chain_context 携带，跳过链头重入）。新增调用
点绕过咽喉或链终点缺 chain_context 时本类红。

6.1 全 Scenario 覆盖见后续类（escalation-chain 与 chain-observability）。
"""

import glob
import json
import re
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.admin_store import load_narrative_sidecars
from core.pm_engine.escalation_chain import (
    ChainQuotaStore,
    EscalationChain,
    entry_phase,
    load_chain_state,
    reset_chain,
    save_chain_state,
    set_chain,
)
from tests.helpers import utcnow_iso as _utcnow_iso


def _scan_call_sites(pattern: str, directory: str = "core") -> list:
    """机械枚举 core/ 内 ``pattern`` 的属性调用点（跳过 def 定义行）。

    ``directory`` 可为目录（递归 glob）或单文件路径。返回
    ``[(file, 调用段文本)]``；调用段取调用点后 500 字符供子断言。
    """
    targets = (
        [directory] if directory.endswith(".py")
        else sorted(glob.glob(f"{directory}/**/*.py", recursive=True))
    )
    hits = []
    for fp in targets:
        src = open(fp, encoding="utf-8").read()
        for m in re.finditer(re.escape(pattern) + r"\(", src):
            if src[max(0, m.start() - 4):m.start()].rstrip().endswith("def"):
                continue  # 定义行
            hits.append((fp.replace("\\", "/"), src[m.end():m.end() + 500]))
    return hits


# 咽喉与链终点之外的真实调用点白名单（全部为框架信号——经 PMEngine 委托
# `_family` 咽喉进链头；新框架调用点出现于此清单外时本测试红，须人工确认
# 来源标注后收录）。
FRAMEWORK_ALERT_CALLERS = {
    "core/pm_engine/budget.py",             # impl_budget_exhausted 族
    "core/pm_engine/engine.py",             # legacy 降级熔断 verify_env_blocked
    "core/pm_engine/spec_integrity.py",     # spec_content_missing 族
    "core/pm_engine/verification/context.py",  # escalation_notifier 委托
}


class TestAntiSelfLoopInventory(unittest.TestCase):
    """1.1 升级咽喉调用点清单与防自环判定。"""

    def test_throat_is_single_entry(self):
        """告警咽喉单入口：除 family 本体与链终点外，无旁路落人工调用点。"""
        callers = {fp for fp, _seg in _scan_call_sites("_send_human_escalation_alert")}
        callers.discard("core/pm_engine/family.py")            # 咽喉本体
        callers.discard("core/pm_engine/escalation_chain.py")  # 链终点直写
        stray = callers - FRAMEWORK_ALERT_CALLERS
        assert not stray, (
            f"发现未收录的落人工告警调用点 {sorted(stray)}——"
            f"框架信号必须经 family 咽喉（链优先派发），"
            f"链成员产出必须走链终点（chain_context 直写）"
        )

    def test_chain_endpoint_alerts_carry_chain_context(self):
        """链成员产出的上升件 MUST 携带 chain_context（链终点直写不重入链头）。"""
        hits = _scan_call_sites("_send_human_escalation_alert",
                                "core/pm_engine/escalation_chain.py")
        assert hits, "链终点上升调用点零命中——扫描器坏了或链终点路径被移除"
        for fp, seg in hits:
            assert re.search(r"chain_context\s*=", seg), (
                f"{fp}: 链成员上升件缺 chain_context——咽喉会把它当框架信号"
                f"重新入链（同签名 dedup 兜底不死循环，但链痕迹丢失）"
            )

    def test_family_throat_chain_first(self):
        """family 咽喉链优先：chain_context 为空时 MUST 先调链派发再落盘。"""
        src = open("core/pm_engine/family.py", encoding="utf-8").read()
        m = re.search(r"def _send_human_escalation_alert", src)
        assert m, "family 咽喉定义缺失"
        body = src[m.end():m.end() + 4000]
        assert "chain_context is None" in body, "咽喉缺链头判定分叉"
        assert "submit_entry" in body, "咽喉缺链优先派发（框架信号绕链直落人工）"

    def test_freeze_hook_chain_first_with_fallback(self):
        """freeze 咽喉链优先 + 降级回落：先试链，链缺席回落 lane.submit_trigger。"""
        src = open("core/pm_engine/arbiter.py", encoding="utf-8").read()
        m = re.search(r"def install_freeze_hook", src)
        assert m, "install_freeze_hook 定义缺失"
        body = src[m.end():src.find("\ndef ", m.end())]
        assert "submit_entry" in body, "freeze 咽喉缺链优先派发"
        assert "submit_trigger" in body, (
            "freeze 咽喉缺降级回落——链缺席时冻结信号必须仍可进 Arbiter 既有路径"
        )

    def test_freeze_throat_signals_outside_default_blacklist(self):
        """freeze_for_human 全调用点 signal_type 不落在缺省黑名单内。"""
        found = set()
        for fp, seg in _scan_call_sites("freeze_for_human"):
            sm = re.search(r"signal_type\s*=\s*['\"]?([A-Za-z][\w-]*)", seg)
            if sm:
                found.add(sm.group(1))
        assert found, "freeze_for_human 机械枚举零命中——扫描器本身坏了"
        tmp = Path(tempfile.mkdtemp())
        try:
            chain = EscalationChain(tmp, MagicMock())  # 缺省配置（黑名单空）
            for sig in sorted(found):
                assert not chain.blacklisted(sig), (
                    f"冻结族 '{sig}' 落在缺省黑名单内——链头会拒收生产冻结信号"
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            reset_chain()


class TestChainQuotaStoreBasics(unittest.TestCase):
    """配额状态层基本读写（6.1 场景的底层前置）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    def test_empty_state_shape(self):
        state = load_chain_state(self.tmp)
        assert state["version"] == 1
        assert state["signatures"] == {}
        assert state["in_flight"] == []
        assert "meta" in state

    def test_admin_attempt_counting(self):
        sig = "spec-a::verify_env_blocked"
        store = ChainQuotaStore(self.tmp)
        store.count_admin_attempt(sig)
        store.count_admin_attempt(sig)
        state = load_chain_state(self.tmp)
        assert state["signatures"][sig]["admin_attempts"] == 2


class TestChainClosureAndMigration(unittest.TestCase):
    """4.1/4.2：链上收口 API 与存量迁移（版本哨兵防重跑）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    def _write_escalation(self, spec, chain_sig=None, handled=False) -> str:
        from core.admin_store import ESCALATION, AdminStore

        store = AdminStore(self.tmp)
        entry = {
            "kind": ESCALATION,
            "signal_type": "verify_env_blocked",
            "spec": spec,
            "severity": "major",
            "description": "d",
            "evidence": "e",
            "recommended_action": "r",
        }
        if chain_sig:
            entry["chain"] = {"signature": chain_sig}
        rec = store.append(entry)
        if handled:
            store.mark_handled(rec["id"])
        return rec["id"]

    def _read_rec(self, rec_id: str) -> dict:
        from core.admin_store import AdminStore

        for rec in AdminStore(self.tmp).read_all():
            if rec.get("id") == rec_id:
                return rec
        raise AssertionError(f"record {rec_id} 不存在")

    def test_close_escalations_by_chain_closes_matching_only(self):
        from core.admin_store import AUTO_RESOLVE_BY, CLOSED_BY_CHAIN, AdminStore

        hit = self._write_escalation("spec-a", chain_sig="spec-a::verify_env_blocked")
        other = self._write_escalation("spec-b", chain_sig="spec-b::verify_env_blocked")
        legacy = self._write_escalation("spec-a")  # 无链关联键（存量件）
        store = AdminStore(self.tmp)
        closed = store.close_escalations_by_chain(
            "spec-a::verify_env_blocked", resolve_note="链闭环自动收口"
        )
        assert closed == 1
        rec = self._read_rec(hit)
        assert rec["handled"] is True
        assert rec["close_cause"] == CLOSED_BY_CHAIN
        assert rec["handled_by"] == AUTO_RESOLVE_BY
        # 非本签名/无链关联键的件不受扰
        assert not self._read_rec(other).get("handled")
        assert not self._read_rec(legacy).get("handled")

    def test_close_escalations_by_chain_skips_handled_and_empty_sig(self):
        from core.admin_store import AdminStore

        done = self._write_escalation(
            "spec-a", chain_sig="spec-a::verify_env_blocked", handled=True
        )
        store = AdminStore(self.tmp)
        assert store.close_escalations_by_chain(
            "spec-a::verify_env_blocked", resolve_note="n"
        ) == 0
        assert self._read_rec(done).get("close_cause") is None
        # 空签名直拒（防宽匹配误收口）
        assert store.close_escalations_by_chain("", resolve_note="n") == 0

    def _mk_sm(self):
        from core.state_machine import StateMachine
        from unittest.mock import MagicMock

        state = self.tmp / ".fenix" / "STATE.md"
        sm = StateMachine(state, MagicMock())
        sm.add_spec("spec-done", {"status": "done"})
        sm.add_spec("spec-live", {"status": "blocked", "frozen": True})
        return sm

    def test_migration_closes_terminal_spec_pending_only(self):
        from core.pm_engine.escalation_chain import EscalationChain

        terminal = self._write_escalation("spec-done")     # 底层已终态 → 收口
        live = self._write_escalation("spec-live")         # 冻结在办 → 保留
        chain = EscalationChain(self.tmp, None)
        chain.set_state_machine(self._mk_sm())
        out = chain.migrate_legacy_pending()
        assert out["status"] == "ok" and out["closed"] == 1 and out["kept"] == 1
        closed = self._read_rec(terminal)
        assert closed["handled"] is True
        assert closed["close_cause"] == "migrated"
        assert closed["handled_by"] == "chain-migration"
        assert not self._read_rec(live).get("handled")

    def test_migration_sentinel_prevents_rerun(self):
        from core.pm_engine.escalation_chain import EscalationChain

        chain = EscalationChain(self.tmp, None)
        chain.set_state_machine(self._mk_sm())
        assert chain.migrate_legacy_pending()["status"] == "ok"
        # 哨兵已落后新出现的存量 pending 不再被二次迁移（一次性语义）
        late = self._write_escalation("spec-done")
        out = chain.migrate_legacy_pending()
        assert out == {"status": "already-migrated"}
        assert not self._read_rec(late).get("handled")


# ── 6.1 验收场景覆盖（装置 + 场景类）─────────────────────────────────

_SIG = "spec-a::verify_env_blocked"


def _disp(**kw):
    """Admin 派发终态替身（AdminDisposition 形态子集；缺省=失败终态）。"""
    from types import SimpleNamespace

    base = dict(
        run_id="",
        result="failed",
        success=False,
        error="admin run 崩溃",
        escalate=False,
        handoff="",
        handoff_reason="",
        status_after="",
        choice_id="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _FakePm:
    """pm 门面替身：链终点上升件按 family 咽喉同款契约落盘（entry.chain =
    chain_context 关联键并入）。链内成功零人工落盘 = 本替身其余路径零副作用，
    落盘记录出现即链终点真实触达。"""

    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.alerts = []

    def _send_human_escalation_alert(
        self, spec, signal_type, severity, description, evidence,
        recommended_action, trigger=None, chain_context=None,
    ):
        from core.admin_store import ESCALATION, AdminStore

        self.alerts.append({
            "spec": spec,
            "signal_type": signal_type,
            "severity": severity,
            "chain_context": dict(chain_context or {}),
        })
        entry = {
            "kind": ESCALATION,
            "signal_type": signal_type,
            "spec": spec,
            "severity": severity,
            "description": description,
            "evidence": evidence,
            "recommended_action": recommended_action,
        }
        if chain_context:
            entry["chain"] = dict(chain_context)
        AdminStore(self.project_root).append(entry)


class _FakeArbiterLane:
    """Arbiter 车道替身（链同步驱动缝 core.pm_engine.arbiter.get_lane）：

    - 脚本化拍板终态（resolved/escalated/dead-man/failed）；
    - 与真车道同口径的拍板配额计数（resolved/escalated 各计一次，经磁盘
      ChainQuotaStore——真车道在 _on_disposition_success/_on_escalate 计）；
    - trigger 收集器键回填（_chain_run_id/_chain_unfrozen/_chain_endpoint_*
      /_chain_ledger_ids，与 arbiter.process_chain_handoff 契约同形）。
    """

    def __init__(self, project_root, outcomes=()):
        self.project_root = Path(project_root)
        self.outcomes = list(outcomes)
        self.calls = []

    @property
    def enabled(self):
        return True

    def config(self):
        return {"enabled": True, "max_consecutive_failures": 2}

    def process_chain_handoff(self, trigger):
        self.calls.append(dict(trigger))
        outcome = self.outcomes.pop(0) if self.outcomes else "escalated"
        trigger["_chain_run_id"] = f"arbiter-run-{len(self.calls)}"
        if outcome in ("resolved", "escalated"):
            ChainQuotaStore(self.project_root).count_arbiter_ruling(
                str(trigger.get("signature") or "")
            )
        if outcome == "resolved":
            trigger["_chain_unfrozen"] = True
        elif outcome == "escalated":
            trigger["_chain_endpoint_kind"] = "arbiter-escalated"
            trigger["_chain_endpoint_reason"] = "须人类拍板（预算豁免类越权）"
            trigger["_chain_ledger_ids"] = ["arb-ledger-1"]
        return outcome


def _drain_chain(chain, timeout_s=15.0):
    """等链单飞队列排空（worker 消费完且无在飞签名）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if chain._queue.unfinished_tasks == 0 and not chain._active:
            return True
        time.sleep(0.01)
    return False


class TestAcceptanceScenarios(unittest.TestCase):
    """设计真相源 9 验收场景链级对应用例（docs/superpowers/specs/
    2026-11-03-escalation-chain-admin-arbiter-design.md「验收场景（最小集）」）。

    seam 策略：Admin 派发缝（``chain._dispatch_admin`` 实例替换）与 Arbiter
    车道缝（``core.pm_engine.arbiter.get_lane`` patch）注入脚本化终态——
    链序/配额/终点语义由真链机器（_process/_run_admin_phase/
    _run_arbiter_phase/_endpoint_escalate）承载，替身只提供 run 终态脚本。
    验收 5/9（harness 无分配对称回落）属 harness SPEC 场景面：此处仅断言
    无 agents.models 分配的 runner 下链装配可用、派发照常发生。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        # 项目级配置显式钉死 cap（屏蔽宿主用户级配置漂移；亦为 s11 热更新基线）
        (self.tmp / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )
        reset_chain()
        self.chain = EscalationChain(self.tmp, MagicMock())
        self.chain.set_runner(MagicMock())  # 无 agents.models 分配（验收 5/9）
        self.chain.set_state_machine(self._mk_sm())
        self.pm = _FakePm(self.tmp)
        self.chain.set_pm(self.pm)
        self.lane = _FakeArbiterLane(self.tmp)
        self._lane_patcher = patch(
            "core.pm_engine.arbiter.get_lane", lambda *a, **k: self.lane
        )
        self._lane_patcher.start()
        self.dispatch_calls = []
        self._dispatch_script = []
        self.chain._dispatch_admin = self._fake_dispatch

    def tearDown(self):
        self._lane_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    def _mk_sm(self):
        from core.state_machine import StateMachine

        # fix-escalation-chain-watchdog-yield-gaps 1.3：链头派发前 frozen 预检
        # 生效——夹具默认非冻结（frozen 形态由预检/deferred 专测按需
        # freeze_spec 构造），保证既有派发处置场景语义不变。
        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": False})
        return sm

    def _fake_dispatch(self, item):
        # 在飞快照随派发记录留证（在办可见性断言用）
        state = load_chain_state(self.tmp)
        self.dispatch_calls.append({
            "item": dict(item),
            "in_flight": [dict(x) for x in state["in_flight"]],
        })
        return self._dispatch_script.pop(0) if self._dispatch_script else _disp()

    def _submit(self, **kw):
        params = dict(
            spec="spec-a",
            signal_type="verify_env_blocked",
            severity="major",
            description="验证环境阻塞",
            evidence="env log",
            recommended_action="修复环境",
            source="unit-test",
        )
        params.update(kw)
        return self.chain.submit_entry(**params)

    def _quota(self):
        return ChainQuotaStore(self.tmp)

    def _ledger_kinds(self):
        from core.pm_engine.arbiter import load_arbiter_ledger

        try:
            return [str(rec.get("kind") or "") for rec in load_arbiter_ledger(self.tmp)]
        except Exception:
            return []

    def _admin_escalations(self):
        from core.admin_store import ESCALATION, AdminStore

        return [
            rec for rec in AdminStore(self.tmp).read_all()
            if rec.get("kind") == ESCALATION
        ]

    # ── 验收 1：信号入链 → Admin 修复 → 闭环，人工队列零痕迹 ────────

    def test_s1_admin_resolves_zero_human_trace(self):
        self._dispatch_script = [
            _disp(run_id="adm-1", result="resolved", success=True, status_after="ready")
        ]
        # 此前已升级到人工队列的同签名在队件——链闭环自动收口（task 4.1）
        from core.admin_store import AUTO_RESOLVE_BY, CLOSED_BY_CHAIN, AdminStore

        store = AdminStore(self.tmp)
        prior = store.append({
            "kind": "escalation", "signal_type": "verify_env_blocked",
            "spec": "spec-a", "severity": "major", "description": "旧件",
            "evidence": "e", "recommended_action": "r",
            "chain": {"signature": _SIG, "chain_id": "chain-old"},
        })

        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        # 人工队列零痕迹：本链零新增上升件，旧件被链成功自动收口
        assert self.pm.alerts == []
        recs = {r["id"]: r for r in self._admin_escalations()}
        assert recs[prior["id"]]["handled"] is True
        assert recs[prior["id"]]["close_cause"] == CLOSED_BY_CHAIN
        assert recs[prior["id"]]["handled_by"] == AUTO_RESOLVE_BY
        # 非冻结件闭环：spec 保持可运行态（frozen=False 件处置成功不解冻——
        # 显式 status 解冻 side-effects 由冻结件分支承载，专测见
        # TestDeferredYieldAndFrozenPrecheck.test_close_chain_success_unfreezes）
        entry = self.chain._resolve_state_machine().read_one("spec-a")
        assert entry["frozen"] is False
        # 成功处置不计失败配额
        assert self._quota().admin_attempts(_SIG) == 0
        assert "chain-closed" in self._ledger_kinds()

    # ── 验收 2：Admin 2 败 → Arbiter 拍板成功（预算豁免语义在车道侧）──

    def test_s2_admin_exhausted_then_arbiter_resolves(self):
        self._dispatch_script = [_disp(run_id="adm-1"), _disp(run_id="adm-2")]
        self.lane.outcomes = ["resolved"]

        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        # Admin 尝试恰烧满配额即转单，不重复同一拍板面
        assert len(self.dispatch_calls) == 2
        assert len(self.lane.calls) == 1
        trig = self.lane.calls[0]
        assert len(trig["admin_trail"]) == 2
        assert all(rec["run_id"] in ("adm-1", "adm-2") for rec in trig["admin_trail"])
        assert trig["admin_handoff_reason"] == ""
        assert trig["source"].startswith("chain-handoff:")
        assert self._quota().admin_attempts(_SIG) == 2
        assert self._quota().arbiter_rulings(_SIG) == 1
        # 链闭环：零人工痕迹 + 台账 handoff→closed 两事件
        assert self.pm.alerts == []
        assert self._ledger_kinds() == ["chain-handoff", "chain-closed"]

    # ── 验收 3：拍板 2 次，第 3 次复现 → 强制上升人工附全链痕 ────────

    def test_s3_third_recurrence_forces_human_with_full_trail(self):
        q = self._quota()
        for _ in range(2):
            q.count_admin_attempt(_SIG)
            q.count_arbiter_ruling(_SIG)

        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        # 双重配额短路：Admin 不再派发（拍板面预算已烧尽）、车道不再重派
        assert self.dispatch_calls == []
        assert self.lane.calls == []
        assert len(self.pm.alerts) == 1
        ctx = self.pm.alerts[0]["chain_context"]
        assert ctx["endpoint_kind"] == "quota-exhausted"
        assert ctx["arbiter_rulings"] == 2 and ctx["admin_attempts_used"] == 2
        assert "第 3 次" in ctx["endpoint_reason"]
        assert ctx["signature"] == _SIG
        # 复现登记可见（chain-recurrence）+ 上升件携全链关联键落人工队列
        assert "chain-recurrence" in self._ledger_kinds()
        assert "chain-escalated" in self._ledger_kinds()
        recs = self._admin_escalations()
        assert len(recs) == 1
        assert recs[0]["chain"]["endpoint_kind"] == "quota-exhausted"
        assert recs[0]["handled"] is False  # 在人工队列待处置

    # ── 验收 4：Arbiter run 崩溃重试 1/2 仍败 → 上升附半成品调查包 ──

    def test_s4_arbiter_run_crash_retries_then_escalates(self):
        self._dispatch_script = [_disp(run_id="adm-1"), _disp(run_id="adm-2")]
        self.lane.outcomes = ["failed", "failed"]

        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        # 车道重派恰 bounded by 连败上限（重试 1/2 后链终点接管）
        assert len(self.lane.calls) == 2
        assert len(self.pm.alerts) == 1
        ctx = self.pm.alerts[0]["chain_context"]
        assert ctx["endpoint_kind"] == "arbiter-escalated"
        assert ctx["arbiter_run_id"].startswith("arbiter-run-")
        # 全链痕附 Admin 尝试（半成品调查包随链终点一并上升）
        assert len(ctx["admin_trail"]) == 2
        assert "chain-escalated" in self._ledger_kinds()

    def test_s4b_deadman_signature_permanent_single_shot(self):
        """死人开关永久例外：既往同签名已停机 → 不再入链直接上升（单次豁免）。"""
        from core.agent_runner.run_files import append_run_line
        from core.pm_engine.arbiter import arbiter_ledger_path

        append_run_line(arbiter_ledger_path(self.tmp), {
            "id": "arb-ledger-dead", "created": "2026-01-01T00:00:00+00:00",
            "kind": "dead-man", "signature": _SIG, "spec": "spec-a",
        })

        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        assert self.dispatch_calls == [] and self.lane.calls == []
        assert len(self.pm.alerts) == 1
        assert self.pm.alerts[0]["chain_context"]["endpoint_kind"] == "dead-man-permanent"

    # ── 验收 8a：链成员不自环——转单直达 Arbiter 不重入不计失败 ────

    def test_s5_handoff_direct_to_arbiter_no_failure_count(self):
        self._dispatch_script = [
            _disp(run_id="adm-1", result="handoff", success=False,
                  handoff="arbiter", handoff_reason="预算类超出环境运维拍板面")
        ]
        self.lane.outcomes = ["resolved"]

        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        assert len(self.dispatch_calls) == 1
        # 转单不计失败（配额水位零烧）
        assert self._quota().admin_attempts(_SIG) == 0
        trig = self.lane.calls[0]
        assert trig["admin_handoff_reason"] == "预算类超出环境运维拍板面"
        assert trig["admin_trail"][0]["handoff"] == "arbiter"
        assert self.pm.alerts == []
        assert self._ledger_kinds() == ["chain-handoff", "chain-closed"]

    # ── 验收 8b：框架自指信号照常入链头 ─────────────────────────────

    def test_s6_framework_signal_enters_chain_head(self):
        assert not self.chain.blacklisted("admin_dispatch_programming_error")
        self._dispatch_script = [
            _disp(run_id="adm-1", result="resolved", success=True, status_after="ready")
        ]

        assert self._submit(
            signal_type="admin_dispatch_programming_error",
            description="Admin run 编程错误",
        ) == "queued"
        assert _drain_chain(self.chain)

        assert len(self.dispatch_calls) == 1
        assert self.dispatch_calls[0]["item"]["signal_type"] == (
            "admin_dispatch_programming_error"
        )
        assert self.pm.alerts == []

    # ── 观测面：在办可见（处置进行中即有在办登记，收口即清）─────────

    def test_s7_inflight_visible_midflight(self):
        self._dispatch_script = [
            _disp(run_id="adm-1", result="resolved", success=True, status_after="ready")
        ]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        snap = self.dispatch_calls[0]["in_flight"]
        assert len(snap) == 1
        assert snap[0]["phase"] == "admin"
        assert snap[0]["chain_id"].startswith("chain-")
        assert snap[0]["signature"] == _SIG
        # 收口后在办登记清零
        assert load_chain_state(self.tmp)["in_flight"] == []

    # ── 配额复位：SPEC 状态翻转即时清零 / 静默满窗清零 ───────────────

    def test_s8_spec_status_transition_resets_quota(self):
        q = self._quota()
        for _ in range(2):
            q.count_admin_attempt(_SIG)
            q.count_arbiter_ruling(_SIG)
        # 预置配额基线（首见不复位语义须有上次观测值）
        from core.pm_engine.escalation_chain import save_chain_state

        state = load_chain_state(self.tmp)
        state["signatures"][_SIG]["last_spec_status"] = "blocked"
        save_chain_state(self.tmp, state)
        # SPEC 状态翻转（链成功解冻即真实迁移形态）
        self.chain._resolve_state_machine().unfreeze_spec("spec-a", status="ready")

        self._dispatch_script = [
            _disp(run_id="adm-2", result="resolved", success=True)
        ]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        # 配额被状态迁移清零 → Admin 重新获得拍板预算（不再配额短路）
        assert len(self.dispatch_calls) == 1
        assert self._quota().admin_attempts(_SIG) == 0  # 成功处置不计数

    def test_s9_window_reset_reopens_quota(self):
        q = self._quota()
        for _ in range(2):
            q.count_admin_attempt(_SIG)
            q.count_arbiter_ruling(_SIG)
        from core.pm_engine.escalation_chain import save_chain_state

        stale = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        state = load_chain_state(self.tmp)
        state["signatures"][_SIG]["last_seen"] = stale
        save_chain_state(self.tmp, state)

        self._dispatch_script = [
            _disp(run_id="adm-3", result="resolved", success=True)
        ]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        assert len(self.dispatch_calls) == 1  # 满窗清零后链头重获预算
        assert self._quota().admin_attempts(_SIG) == 0

    # ── kill switch：黑名单信号绕过链直达人工（6.2 逐字节一致的前置）──

    def test_s10_blacklisted_signal_bypasses_chain(self):
        cfg = self.tmp / ".fenix" / "config.yaml"
        cfg.write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n  blacklist:\n    - verify_env_blocked\n",
            encoding="utf-8",
        )
        assert self.chain.blacklisted("verify_env_blocked")

        assert self._submit() == "blacklisted"
        assert self.dispatch_calls == [] and self.lane.calls == []
        assert self.pm.alerts == []  # 调用方走既有落盘路径，链侧零副作用
        assert load_chain_state(self.tmp)["in_flight"] == []
        assert load_chain_state(self.tmp)["signatures"] == {}  # 不入配额水位

    # ── 配额配置热更新：保存即生效（链每次判定即时解析）─────────────

    def test_s11_quota_config_hot_update(self):
        self._dispatch_script = [_disp(run_id="adm-1"), _disp(run_id="adm-2")]
        self.lane.outcomes = ["resolved"]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        assert self._quota().arbiter_rulings(_SIG) == 1  # cap 2 下拍板 1 次
        lane_calls_after_cycle1 = len(self.lane.calls)  # 跨轮累积，只比增量

        # 「设置页保存」热更新：写项目配置 arbiter_rulings 2→1，无需重启
        cfg = self.tmp / ".fenix" / "config.yaml"
        cfg.write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 1\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )

        # 复现：新 cap 下闸门即时判定耗尽（车道不再重派）
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        assert len(self.lane.calls) == lane_calls_after_cycle1
        assert len(self.pm.alerts) == 1
        assert self.pm.alerts[0]["chain_context"]["endpoint_kind"] == "quota-exhausted"

    # ── 链头单飞：同签名在飞重复触发 dedup（不落人工不双派）─────────

    def test_s12_dedup_same_signature_inflight(self):
        self.chain._active.add(_SIG)
        assert self._submit() == "deduped"
        assert self.dispatch_calls == [] and self.pm.alerts == []

    # ── 在飞互斥：同 spec 已有 admin run 在飞 → 本件让行不双派 ──────

    def test_s13_deferred_when_admin_run_in_flight(self):
        # fix-escalation-chain-watchdog-yield-gaps 1.2：互斥守卫命中从「整条
        # 清除」改为「deferred 留痕」（yield_to=被让行 run_id + 信号快照），
        # 看护扫描在被让行 run 终态后回喂重派（不再静默丢弃等复发）。
        # 守卫单源已收拢 _merge_admin_runs（_active_admin_run_id 消费）。
        with patch(
            "core.admin_monitor._merge_admin_runs",
            lambda *a, **k: {"admin-spec-a-live": {
                "final": False, "has_pending": True, "rec": {}}},
        ):
            assert self._submit() == "queued"
            assert _drain_chain(self.chain)
        assert self.dispatch_calls == []      # 互斥守卫命中不双派
        assert self.pm.alerts == []           # 让行不上升（等看护扫描回喂）
        inflight = load_chain_state(self.tmp)["in_flight"]
        assert len(inflight) == 1             # 让行后整条清除改为 deferred 留痕
        entry = inflight[0]
        assert entry["phase"] == "deferred"
        assert entry["yield_to"] == "admin-spec-a-live"   # 被让行对象标识
        assert entry["deferred_at"]                       # 让行时间戳
        assert entry["started_at"]                        # 既有字段保留（reap 口径）
        assert entry["signature"] == _SIG
        assert entry["item_signal"]["signal_type"] == "verify_env_blocked"  # 重派快照

    # ── 车道缺席终点：Arbiter 车道不可用 → 上升 arbiter-unavailable ─

    def test_s14_arbiter_lane_unavailable_endpoint(self):
        self._dispatch_script = [_disp(run_id="adm-1"), _disp(run_id="adm-2")]
        item = {
            "spec": "spec-a", "signal_type": "verify_env_blocked",
            "severity": "major", "description": "验证环境阻塞",
            "evidence": "env log", "recommended_action": "修复环境",
            "source": "unit-test", "signature": _SIG, "granularity": "spec",
            "enqueued_at": "2026-01-01T00:00:00+00:00",
            "trigger": {}, "payload": {},
        }
        with patch("core.pm_engine.arbiter.get_lane", lambda *a, **k: None):
            self.chain._process(item)  # 直驱（submit 的 chain_active 会先拒缺席车道）
        assert len(self.dispatch_calls) == 2    # Admin 照常烧配额
        assert self._quota().admin_attempts(_SIG) == 2
        assert len(self.pm.alerts) == 1
        assert self.pm.alerts[0]["chain_context"]["endpoint_kind"] == (
            "arbiter-unavailable"
        )

    # ── Arbiter 自判失败上升：run 正常终态但结论须人工（无重派）─────

    def test_s15_arbiter_escalated_single_call_no_retry(self):
        self._dispatch_script = [_disp(run_id="adm-1"), _disp(run_id="adm-2")]
        self.lane.outcomes = ["escalated"]  # 自判失败 ≠ failed（不触发链内重派）
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        assert len(self.lane.calls) == 1
        assert len(self.pm.alerts) == 1
        ctx = self.pm.alerts[0]["chain_context"]
        assert ctx["endpoint_kind"] == "arbiter-escalated"
        assert ctx["arbiter_ledger_ids"] == ["arb-ledger-1"]  # 调查台账随件附上
        assert ctx["arbiter_run_id"] == "arbiter-run-1"


class TestChainObservabilityScenarios(unittest.TestCase):
    """chain-observability 场景面（5.1/5.2 消费端 + spec=null 归组）。

    场景语义：链事件（转单/复现/闭环/上升）须在 SPEC 时间轴可见；
    spec=null 信号按主体键归组进处置链视图而不落任何 SPEC 时间轴；
    处置链视图四视图（在办/水位/上升件/队列）端到端贯通。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )
        reset_chain()
        self.chain = EscalationChain(self.tmp, MagicMock())
        self.chain.set_runner(MagicMock())
        self.chain.set_state_machine(self._mk_sm())
        self.pm = _FakePm(self.tmp)
        self.chain.set_pm(self.pm)
        self.lane = _FakeArbiterLane(self.tmp)
        self._lane_patcher = patch(
            "core.pm_engine.arbiter.get_lane", lambda *a, **k: self.lane
        )
        self._lane_patcher.start()
        self.dispatch_calls = []
        self._dispatch_script = []
        self.chain._dispatch_admin = self._fake_dispatch

    def tearDown(self):
        self._lane_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    def _mk_sm(self):
        from core.state_machine import StateMachine

        # fix-escalation-chain-watchdog-yield-gaps 1.3：预检生效后夹具默认
        # 非冻结（同 TestAcceptanceScenarios 口径）
        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": False})
        return sm

    def _fake_dispatch(self, item):
        self.dispatch_calls.append(dict(item))
        return self._dispatch_script.pop(0) if self._dispatch_script else _disp()

    def _submit(self, **kw):
        params = dict(
            spec="spec-a", signal_type="verify_env_blocked", severity="major",
            description="验证环境阻塞", evidence="env log",
            recommended_action="修复环境", source="unit-test",
        )
        params.update(kw)
        return self.chain.submit_entry(**params)

    def _chain_nodes(self):
        from core.dashboard.data.timeline import get_spec_timeline

        return [n for n in get_spec_timeline(self.tmp, "spec-a") if n.get("kind") == "chain"]

    # ── 转单事件可见（验收 7 + chain-observability 转单场景）────────

    def test_chain_events_visible_on_spec_timeline(self):
        self._dispatch_script = [_disp(run_id="adm-1"), _disp(run_id="adm-2")]
        self.lane.outcomes = ["resolved"]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        nodes = self._chain_nodes()
        kinds = [n["chain_kind"] for n in nodes]
        assert kinds == ["chain-handoff", "chain-closed"]
        assert all(n["signature"] == _SIG for n in nodes)
        assert all(n["chain_id"].startswith("chain-") for n in nodes)
        # 转单摘要携原因（handoff_reason 随 action_or_upgrade 下发）
        assert "配额耗尽" in nodes[0]["summary"]
        # 时间升序（链叙事顺序）
        times = [n["time"] for n in nodes]
        assert times == sorted(times)

    def test_handoff_reason_summary_on_timeline(self):
        self._dispatch_script = [
            _disp(run_id="adm-1", result="handoff", success=False,
                  handoff="arbiter", handoff_reason="预算类超出环境运维拍板面")
        ]
        self.lane.outcomes = ["resolved"]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        nodes = self._chain_nodes()
        handoff = [n for n in nodes if n["chain_kind"] == "chain-handoff"]
        assert len(handoff) == 1
        assert "预算类超出环境运维拍板面" in handoff[0]["summary"]

    # ── 复现计数可见 + 上升件/队列视图端到端 ─────────────────────────

    def test_recurrence_and_queue_view_end_to_end(self):
        # 第一轮：Admin 2 败 → Arbiter 拍板 1 次（cap 2 内）闭环
        self._dispatch_script = [_disp(run_id="adm-1"), _disp(run_id="adm-2")]
        self.lane.outcomes = ["resolved"]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        # 第二轮：复现 → Admin 配额短路 → 车道拍板第 2 次（cap 内）→ 复现计数 2
        self.lane.outcomes = ["resolved"]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        # 第三轮：第 3 次复现 → 强制上升（验收 3 的观测面消费）
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)

        # 复现事件与上升事件均落时间轴
        kinds = [n["chain_kind"] for n in self._chain_nodes()]
        assert "chain-recurrence" in kinds and "chain-escalated" in kinds
        # 处置链视图四视图端到端（真消费链_overview 聚合）
        from core.dashboard.data import chain_overview

        view = chain_overview(self.tmp)
        assert view["summary"]["in_flight"] == 0  # 已收口清零
        assert view["summary"]["signatures"] == 1
        sig_row = view["signatures"][0]
        assert sig_row["arbiter_rulings"] == 2 and sig_row["arbiter_cap"] == 2
        assert sig_row["exhausted"] is True
        assert view["summary"]["escalations"] == 1
        assert view["queue"] == view["escalations"]  # 全部未收口在人工队列
        assert view["queue"][0]["chain"]["endpoint_kind"] == "quota-exhausted"

    # ── spec=null 归组：主体键签名入视图、不落 SPEC 时间轴 ───────────

    def test_subject_grouping_view_not_on_spec_timeline(self):
        assert self._submit(spec="", payload={"subject": "检测器-1"}) == "queued"
        self._dispatch_script = [_disp(run_id="adm-1", result="resolved", success=True)]
        assert _drain_chain(self.chain)

        sig = "null:检测器-1::verify_env_blocked"
        state = load_chain_state(self.tmp)
        assert sig in state["signatures"]  # 主体键归组配额水位
        assert self._chain_nodes() == []   # 不落任何 SPEC 时间轴

    # ── 验收 5/9：无 agents.models 分配 runner 下链装配可用 ─────────

    def test_no_model_assignment_chain_active(self):
        runner = MagicMock()
        runner._get_agent_model_assignment.return_value = None
        assert self.chain.chain_active() is True  # spawn 可用判定不受分配缺席影响
        self._dispatch_script = [
            _disp(run_id="adm-1", result="resolved", success=True, status_after="ready")
        ]
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        assert len(self.dispatch_calls) == 1  # 派发照常发生（harness 回落属 harness SPEC 面）


class _RecordingLogger:
    """记录型 logger（6.2 一次性 WARN 断言用）。"""

    def __init__(self):
        self.warnings = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        pass


class TestDegradedAlertPathParity(unittest.TestCase):
    """6.2 降级态逐字节一致（设计验收 6）。

    kill switch 命中 / ``arbiter.enabled=false`` / 链级失能（装配缺席）三形态
    下，咽喉回落既有落盘路径——告警条目与合入前基线（无链直落）逐字段一致：
    无 ``chain`` 关联键、降噪分级照旧（warning 写入即 handled）、零后台派发
    （consolidate-alerts-to-ops-page 1.2 调查叙事生成链退役，不再有补叙
    调度）、配额水位零扰动；配置修复后自动恢复入链。
    """

    # 条目级易变字段（id/时间戳）不参与逐字节比对
    VOLATILE_FIELDS = {"id", "created", "updated", "handled_at"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        reset_chain()
        from core.pm_engine.arbiter import set_lane

        set_lane(None)

    def tearDown(self):
        from core.pm_engine.arbiter import set_lane

        set_lane(None)
        set_chain(None)
        reset_chain()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── 装置 ────────────────────────────────────────────────────────

    def _mk_sm(self):
        from core.state_machine import StateMachine

        # fix-escalation-chain-watchdog-yield-gaps 1.3：预检生效后夹具默认
        # 非冻结（同 TestAcceptanceScenarios 口径）
        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": False})
        return sm

    def _write_project_config(self, arbiter_enabled=True, blacklist=False):
        lines = [f"arbiter:\n  enabled: {'true' if arbiter_enabled else 'false'}\n"]
        lines.append(
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n"
        )
        if blacklist:
            lines.append("  blacklist:\n    - verify_env_blocked\n")
        (self.tmp / ".fenix" / "config.yaml").write_text(
            "".join(lines), encoding="utf-8"
        )

    def _install_chain(self, *, wired):
        chain = EscalationChain(self.tmp, MagicMock())
        if wired:
            chain.set_runner(MagicMock())
            chain.set_state_machine(self._mk_sm())
        set_chain(chain)
        return chain

    def _fire(self, severity="major"):
        """经真咽喉（FamilyGovernor 回落路径）发射一次升级信号，返回**本次新增**落盘件。"""
        from core.admin_store import ESCALATION, AdminStore
        from core.pm_engine.family import FamilyGovernor

        class FakePM:
            project_root = self.tmp
            logger = MagicMock()

        before = {
            r.get("id") for r in AdminStore(self.tmp).read_all()
        }
        gov = FamilyGovernor.__new__(FamilyGovernor)
        gov._pm = FakePM()
        gov._send_human_escalation_alert(
            "spec-a", "verify_env_blocked", severity, "验证环境阻塞",
            "env log", "修复环境",
        )
        return [
            r for r in AdminStore(self.tmp).read_all()
            if r.get("kind") == ESCALATION and r.get("id") not in before
        ]

    def _drain_singleton(self):
        """链单例排水（链接单后 worker 异步消费，断言前须排空）。"""
        from core.pm_engine.escalation_chain import get_chain

        chain = get_chain(self.tmp)
        assert chain is not None
        assert _drain_chain(chain)

    def _stub_admin_resolved(self, chain):
        """链头 Admin 派发缝替身（恢复入链排水期的确定性闭环）。"""
        chain._dispatch_admin = lambda item: _disp(
            run_id="adm-r", result="resolved", success=True, status_after="ready"
        )

    @staticmethod
    def _stable(rec):
        return {k: v for k, v in rec.items() if k not in TestDegradedAlertPathParity.VOLATILE_FIELDS}

    # ── 基线：合入前形态（无链直落）────────────────────────────────

    def test_baseline_no_chain_writes_pre_chain_shape(self):
        set_chain(None)  # get_chain → None：纯合入前路径
        recs = self._fire()
        assert len(recs) == 1
        rec = recs[0]
        assert "chain" not in rec
        assert rec["signal_type"] == "verify_env_blocked"
        assert rec["handled"] is False  # major 进人工待处理队列
        # 机械文案形态（trigger/choices 按 signal_type 枚举推导，缺席即缺席
        # ——三形态逐字段比对以本基线为准，不在此钉死具体键集）

    # ── 三形态逐字段一致 ────────────────────────────────────────────

    def test_kill_switch_bytes_identical_to_baseline(self):
        set_chain(None)
        baseline = self._stable(self._fire()[0])
        baseline_warn = self._stable(self._fire(severity="warning")[0])

        # 重建干净库重放 kill switch 形态
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        self._write_project_config(blacklist=True)
        self._install_chain(wired=True)
        recs = self._fire()
        assert len(recs) == 1
        assert "chain" not in recs[0]
        assert self._stable(recs[0]) == baseline
        # 降噪分级照旧：warning 写入即 handled（与基线 warning 件一致）
        recs_w = self._fire(severity="warning")
        assert len(recs_w) == 1
        assert recs_w[0]["handled"] is True
        assert self._stable(recs_w[0]) == baseline_warn
        # 零后台派发（叙事生成链退役，基线与降级件均零侧车）；
        # 链侧零扰动（配额水位零写入）
        assert load_narrative_sidecars(self.tmp) == {}
        assert load_chain_state(self.tmp)["signatures"] == {}

    def test_arbiter_disabled_bytes_identical_to_baseline(self):
        set_chain(None)
        baseline = self._stable(self._fire()[0])

        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        self._write_project_config(arbiter_enabled=False)
        self._install_chain(wired=True)  # 装配完备、纯配置关闭
        recs = self._fire()
        assert len(recs) == 1
        assert "chain" not in recs[0]
        assert self._stable(recs[0]) == baseline
        # 零后台派发（叙事生成链退役：基线与降级件均零侧车零补叙）
        assert load_narrative_sidecars(self.tmp) == {}
        assert load_chain_state(self.tmp)["signatures"] == {}

        # 配置修复后自动恢复入链（零重启）：链接单零人工落盘
        self._write_project_config(arbiter_enabled=True)
        chain = self._install_chain(wired=True)
        self._stub_admin_resolved(chain)
        assert self._fire() == []
        self._drain_singleton()
        assert self._fire() == []  # 排水后复核：链闭环过程零人工痕迹

    def test_chain_unwired_bytes_identical_to_baseline(self):
        set_chain(None)
        baseline = self._stable(self._fire()[0])

        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        self._write_project_config(arbiter_enabled=True)
        chain = self._install_chain(wired=False)  # runner/sm 缺席
        logger = _RecordingLogger()
        chain.logger = logger
        recs = self._fire()
        assert len(recs) == 1
        assert "chain" not in recs[0]
        assert self._stable(recs[0]) == baseline
        assert load_chain_state(self.tmp)["signatures"] == {}
        # 一次性 WARN 留痕：重复触发不再叠加
        self._fire()
        disabled_warns = [
            w for w in logger.warnings
            if any("处置链级失能" in str(seg) for seg in w)
        ]
        assert len(disabled_warns) == 1

    # ── 车道单例隔离：链失能判定不受他测残留车道影响 ────────────────

    def test_lane_singleton_reset_between_forms(self):
        from core.pm_engine.arbiter import set_lane

        set_chain(None)
        self._write_project_config(arbiter_enabled=False)
        self._install_chain(wired=True)
        assert self._fire() != []  # 关闭态回落落盘
        set_lane(None)
        self._write_project_config(arbiter_enabled=True)
        chain = self._install_chain(wired=True)
        self._stub_admin_resolved(chain)
        assert self._fire() == []  # 复开 + 车道重建 → 恢复入链零落盘
        self._drain_singleton()
        assert self._fire() == []


class TestDeferredYieldAndFrozenPrecheck(unittest.TestCase):
    """fix-escalation-chain-watchdog-yield-gaps 3.1：链侧五组新行为用例。

    覆盖 tasks 3.1 字面清单：frozen 预检不烧配额 / 冻结击杀空壳不计尝试 /
    让行留痕形态（phase/yield_to/deferred_at）/ deferred 超时 reap /
    新旧条目形态混合兼容。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )
        reset_chain()
        from core.state_machine import StateMachine

        self.chain = EscalationChain(self.tmp, MagicMock())
        self.chain.set_runner(MagicMock())
        self.sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        self.sm.add_spec("spec-a", {"status": "blocked", "frozen": False})
        self.chain.set_state_machine(self.sm)
        self.pm = _FakePm(self.tmp)
        self.chain.set_pm(self.pm)
        self.lane = _FakeArbiterLane(self.tmp)
        self._lane_patcher = patch(
            "core.pm_engine.arbiter.get_lane", lambda *a, **k: self.lane
        )
        self._lane_patcher.start()
        self.dispatch_calls = []
        self._dispatch_script = []
        self.chain._dispatch_admin = self._fake_dispatch

    def tearDown(self):
        self._lane_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    def _fake_dispatch(self, item):
        self.dispatch_calls.append(dict(item))
        return self._dispatch_script.pop(0) if self._dispatch_script else _disp()

    def _freeze(self, frozen=True):
        self.sm.update_spec("spec-a", {"frozen": frozen})

    def _submit(self, **kw):
        params = dict(
            spec="spec-a",
            signal_type="verify_env_blocked",
            severity="major",
            description="验证环境阻塞",
            evidence="env log",
            recommended_action="修复环境",
            source="unit-test",
        )
        params.update(kw)
        return self.chain.submit_entry(**params)

    def _in_flight(self):
        return load_chain_state(self.tmp)["in_flight"]

    def _deferred_entries(self):
        return [x for x in self._in_flight() if entry_phase(x) == "deferred"]

    def _write_run(self, run_id, events):
        runs = self.tmp / ".fenix" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{run_id}.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
        )

    def _age_started_at(self, hours):
        state = load_chain_state(self.tmp)
        old = datetime.now(timezone.utc) - timedelta(hours=hours)
        for x in state["in_flight"]:
            x["started_at"] = old.isoformat()
        save_chain_state(self.tmp, state)

    # ── frozen 预检：不派发、不烧配额、直达 Arbiter 冻结鉴定 ─────────
    # （用户定调 2026-11-05「告警、阻塞到人类之前一定要先经过 arbiter」：
    # 冻结件不再 deferred 等人工解冻——admin 不介入 arbiter 必须接手；
    # deferred 收窄为互斥让行专用形态）

    def test_frozen_precheck_routes_to_arbiter(self):
        self.sm.update_spec("spec-a", {"frozen": True})
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        assert self.dispatch_calls == []  # 预检拦截：零派发
        sig = self.chain._quota.snapshot().get(_SIG) or {}
        assert not sig.get("admin_attempts")  # 零 Admin 配额消耗
        # Arbiter 冻结鉴定接单（默认替身 escalated → 链终点上升）
        assert len(self.lane.calls) == 1
        trig = self.lane.calls[0]
        assert trig["admin_trail"] == []  # Admin 未尝试（附空尝试痕）
        assert "frozen" in str(trig.get("admin_handoff_reason") or "")
        assert sig.get("arbiter_rulings") == 1  # Arbiter 参与被记账
        assert len(self.pm.alerts) == 1  # Arbiter 处理后仍失败 → 才上升人工
        ctx = self.pm.alerts[0]["chain_context"]
        assert ctx["endpoint_kind"] == "arbiter-escalated"
        assert ctx["admin_attempts_used"] == 0
        assert self._deferred_entries() == []  # 不再 deferred 等人工
        assert self._in_flight() == []

    def test_frozen_precheck_arbiter_resolved_closes_chain(self):
        # 冻结鉴定成功（machine 冻结自愈解冻形态）→ 链闭环零人工痕迹
        self.lane.outcomes = ["resolved"]
        self.sm.update_spec("spec-a", {"frozen": True})
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        assert self.dispatch_calls == []
        assert self.pm.alerts == []  # 拍板成功 → 人工队列零痕迹
        assert self._in_flight() == []
        assert self._deferred_entries() == []
        sig = self.chain._quota.snapshot().get(_SIG) or {}
        assert sig.get("arbiter_rulings") == 1

    def test_legacy_empty_yield_deferred_still_resubmits(self):
        # 向后兼容：存量 yield_to="" deferred 条目（旧冻结预检形态）解冻后
        # 仍可被看护重派消费——重派走新链头全流程（冻结预检改道后新条目
        # 不再产出空 yield_to 形态，存量条目按原语义自然消化）
        state = load_chain_state(self.tmp)
        state["in_flight"].append({
            "chain_id": "chain-legacy-frozen", "signature": _SIG,
            "spec": "spec-a", "phase": "deferred", "yield_to": "",
            "deferred_at": _utcnow_iso(), "started_at": _utcnow_iso(),
            "item_signal": {
                "spec": "spec-a", "signal_type": "verify_env_blocked",
                "severity": "major", "description": "验证环境阻塞",
                "evidence": "env log", "recommended_action": "修复环境",
                "trigger": {}, "payload": {},
                "source": "escalation-alert", "signature": _SIG,
                "granularity": "spec",
            },
        })
        save_chain_state(self.tmp, state)
        self._dispatch_script = [
            _disp(run_id="adm-legacy", result="resolved", success=True,
                  status_after="ready")
        ]
        entry = self._deferred_entries()[0]
        assert self.chain.resubmit_deferred(entry) == "queued"
        assert _drain_chain(self.chain)
        assert len(self.dispatch_calls) == 1  # 解冻态下照常派发
        assert self._in_flight() == []

    # ── 冻结击杀空壳：0 assistant 轮次 + frozen-terminated 终态不计尝试 ──

    def test_frozen_killed_empty_shell_routes_to_arbiter(self):
        self._dispatch_script = [_disp(run_id="adm-shell")]
        self._write_run(
            "adm-shell",
            [{"type": "system"},
             {"type": "frozen-terminated", "reason": "spec frozen"}],
        )
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        sig = self.chain._quota.snapshot().get(_SIG) or {}
        assert not sig.get("admin_attempts")  # 空壳不计尝试
        assert len(self.lane.calls) == 1  # 冻结竞态件同口径改道 Arbiter
        assert self._deferred_entries() == []  # 不再 deferred 等人工

    def test_shell_exemption_requires_zero_api_rounds(self):
        # 跑过轮次（有 assistant 事件）后遭 frozen-terminated：正常计尝试
        self._dispatch_script = [_disp(run_id="adm-ran")]
        self._write_run(
            "adm-ran",
            [{"type": "assistant", "message": {"content": [{"type": "text"}]}},
             {"type": "frozen-terminated", "reason": "spec frozen"}],
        )
        assert self._submit() == "queued"
        assert _drain_chain(self.chain)
        # 非空壳：照常计配额（首次失败计 1；cap=2 下链自动第二次尝试耗默认
        # 失败替身计 2 → exhausted 转 Arbiter——失败计点路径与空壳豁免互斥）
        sig = self.chain._quota.snapshot().get(_SIG) or {}
        assert sig.get("admin_attempts") == 2
        assert sig.get("arbiter_rulings") == 1  # 链终点已走 Arbiter 拍板
        assert self._deferred_entries() == []

    # ── 让行留痕形态：phase/yield_to/deferred_at/item_signal ─────────

    def test_yield_deferred_trace_form(self):
        # 同 spec 活 admin run 在飞（manual-intervention 等非链成员通道）
        with patch(
            "core.admin_monitor._merge_admin_runs",
            return_value={"admin-manual-live": {
                "final": False, "has_pending": True, "rec": {}}},
        ):
            assert self._submit() == "queued"
            assert _drain_chain(self.chain)
        assert self.dispatch_calls == []  # 让行：不派发
        deferred = self._deferred_entries()
        assert len(deferred) == 1
        entry = deferred[0]
        assert entry["phase"] == "deferred"
        assert entry["yield_to"] == "admin-manual-live"  # 被让行 run_id 留痕
        assert entry["deferred_at"]
        assert entry["started_at"]  # 既有字段保留（reap 口径）
        snap = entry["item_signal"]
        assert snap["signature"] == _SIG
        assert snap["severity"] == "major"
        assert snap["description"] == "验证环境阻塞"

    def test_yielded_run_death_enables_resubmit(self):
        # 让行留痕 → 被让行 run 死（文件终态）→ resubmit 回喂照常派发
        with patch(
            "core.admin_monitor._merge_admin_runs",
            return_value={"admin-manual-dead": {
                "final": False, "has_pending": True, "rec": {}}},
        ):
            assert self._submit() == "queued"
            assert _drain_chain(self.chain)
        assert len(self._deferred_entries()) == 1
        self._write_run(
            "admin-manual-dead",
            [{"type": "assistant", "message": {"content": []}},
             {"type": "error", "error": "boom"}],  # 末行终态 = 死亡证据
        )
        self._dispatch_script = [
            _disp(run_id="adm-2", result="resolved", success=True,
                  status_after="ready")
        ]
        entry = self._deferred_entries()[0]
        assert self.chain.resubmit_deferred(entry) == "queued"
        assert _drain_chain(self.chain)
        assert len(self.dispatch_calls) == 1

    # ── deferred 超时 reap：与 admin 相条目同拍按 started_at 回收 ─────

    def test_deferred_stale_reaped_with_admin_entries(self):
        with patch(
            "core.admin_monitor._merge_admin_runs",
            return_value={"admin-manual-reap": {
                "final": False, "has_pending": True, "rec": {}}},
        ):
            assert self._submit() == "queued"
            assert _drain_chain(self.chain)  # 产生 deferred 让行条目
        # 再手工放一条旧形态 admin 相条目（无 phase 键——存量形态）
        state = load_chain_state(self.tmp)
        state["in_flight"].append({
            "chain_id": "chain-legacy", "signature": "spec-x::stuck",
            "spec": "spec-x", "started_at": _utcnow_iso(),
        })
        save_chain_state(self.tmp, state)
        self._age_started_at(hours=7)  # 超过 CHAIN_INFLIGHT_STALE_S=6h
        stale = self.chain._quota.stale_in_flight()
        assert {x["chain_id"] for x in stale} >= {
            x["chain_id"] for x in self._in_flight()
        }  # deferred 与 admin 相一视同仁
        assert self.chain.reap_stale_inflight() >= 2
        assert self._in_flight() == []

    # ── 新旧条目形态混合兼容 ────────────────────────────────────────

    def test_mixed_legacy_entry_compat(self):
        state = load_chain_state(self.tmp)
        # 旧形态：无 phase 键（存量 in_flight）+ phase="admin"（显式旧值）
        state["in_flight"] = [
            {"chain_id": "chain-old-1", "signature": _SIG, "spec": "spec-a",
             "started_at": _utcnow_iso()},
            {"chain_id": "chain-old-2", "signature": "spec-x::stuck",
             "spec": "spec-x", "phase": "admin",
             "started_at": _utcnow_iso()},
        ]
        save_chain_state(self.tmp, state)
        assert entry_phase(state["in_flight"][0]) == "admin"  # 缺 phase 归一
        assert entry_phase(state["in_flight"][1]) == "admin"
        assert entry_phase({"phase": "nonsense"}) == "admin"  # 非法值归一
        assert self.chain._quota.deferred_in_flight() == []  # 不误判为 deferred
        # 新形态 deferred 与旧形态并存：读侧各归各位（deferred 直注——
        # 冻结预检已改道 Arbiter，不再产出空 yield_to 条目）
        state = load_chain_state(self.tmp)
        state["in_flight"].append({
            "chain_id": "chain-legacy-def", "signature": "spec-y::stuck",
            "spec": "spec-y", "phase": "deferred", "yield_to": "",
            "deferred_at": _utcnow_iso(), "started_at": _utcnow_iso(),
        })
        save_chain_state(self.tmp, state)
        phases = sorted(entry_phase(x) for x in self._in_flight())
        assert phases == ["admin", "admin", "deferred"]
        assert len(self.chain._quota.deferred_in_flight()) == 1


class TestFirstIncidentTimeline(unittest.TestCase):
    """fix-escalation-chain-watchdog-yield-gaps 3.3：端到端时序用例。

    复刻首例事件时间轴（design 提案的取证蓝本）：

      T0 冻结竞态：验证冻结瞬间链件照常派发 → frozen-terminated 空壳烧配额
      T1 让行留痕：解冻后重派 → 同 spec 活 admin run（manual-intervention
         等非链成员通道）在飞 → 链头让行、deferred 留痕
      T2 被让行 run 死：manual run 落终态 → 看护扫描回喂重派（旧实现此处置
         留痕被整条清除 → 静默挂起，信号永不收口）
      T3 链终点：互斥放行 → Admin 烧满配额 → Arbiter escalated → 链终点
         人工上升件落盘
      T4 抑制窗口：链在办期间孤儿看护巡检对链头死 run 的 pending 不告警
         不终结（首例 19:28 看护 critical 早于链终点裁决包 3 分钟的重复
         出件被消除）

    终态断言：链终点上升件是该事件的唯一人工作品，全程人工队列零重复条目。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )
        reset_chain()
        from core.state_machine import StateMachine

        self.sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        self.sm.add_spec("spec-a", {"status": "blocked", "frozen": True})
        self.chain = EscalationChain(self.tmp, MagicMock())
        self.chain.set_runner(MagicMock())
        self.chain.set_state_machine(self.sm)
        self.pm = _FakePm(self.tmp)
        self.chain.set_pm(self.pm)
        self.lane = _FakeArbiterLane(self.tmp)
        self._lane_patcher = patch(
            "core.pm_engine.arbiter.get_lane", lambda *a, **k: self.lane
        )
        self._lane_patcher.start()
        # monitor 与链共享 store / state machine / project_root（端到端同源）
        from core.admin_monitor import AdminMonitor
        from core.admin_store import AdminStore
        from tests.helpers import FakeLogger

        self.store = AdminStore(self.tmp, FakeLogger())
        self.mon = AdminMonitor(
            {"admin": {"escalation_cooldown_minutes": 15}},
            self.sm, self.tmp, FakeLogger(), store=self.store,
        )
        set_chain(self.chain)  # 看护抑制/重派经链单例消费

    def tearDown(self):
        self._lane_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    # ── 时序装置 ────────────────────────────────────────────────────

    def _write_run(self, run_id, events):
        runs = self.tmp / ".fenix" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{run_id}.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
        )

    def _append_run_line(self, run_id, event):
        runs = self.tmp / ".fenix" / "runs"
        with (runs / f"{run_id}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def _append_pending_aged(self, run_id, signal_type, minutes):
        """落 pending disposition 并拨回 minutes 前（超看护 grace）。"""
        from core.admin_store import DISPOSITION
        from tests.helpers import iso_ago

        rec = self.store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": signal_type, "spec": "spec-a",
            "admin_run_id": run_id,
        })
        alerts_path = self.store.alerts_path
        alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
        for r in alerts:
            if r.get("id") == rec["id"]:
                r["created"] = iso_ago(minutes)
        alerts_path.write_text(json.dumps(alerts), encoding="utf-8")

    def _escalations(self):
        from core.admin_store import ESCALATION

        return [r for r in self.store.read_all()
                if r.get("kind") == ESCALATION]

    def _deferred_entries(self):
        return self.chain._quota.deferred_in_flight()

    def _wait_until(self, pred, timeout_s=10.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if pred():
                return True
            time.sleep(0.01)
        return False

    def _drain(self, timeout_s=15.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.chain._queue.unfinished_tasks == 0 and not self.chain._active:
                return True
            time.sleep(0.01)
        return False

    # ── 首例时间轴全程 ──────────────────────────────────────────────

    def test_first_incident_full_timeline(self):
        """冻结竞态 → 让行留痕 → 被让行 run 死 → 看护重派 → 链终点唯一
        人工作品，全程人工队列零重复条目。"""
        import threading

        from core.agent_runner import AdminDisposition

        gate = threading.Event()
        dispatch_calls = []

        def fake_dispatch(item):
            """链头 Admin 派发替身：真落 pending + 死亡形态 run 文件
            （链路径 run_administrator 唤起前落 pending、链头不落 final
            ——孤儿形态由它承载），二次调用阻塞构造「链在办」窗口。"""
            n = len(dispatch_calls) + 1
            dispatch_calls.append(dict(item))
            run_id = f"adm-{n}"
            self._append_pending_aged(run_id, "verify_env_blocked", 20)
            self._write_run(run_id, [
                {"type": "assistant", "message": {"content": []}},
                {"type": "error", "error": "boom"},
            ])
            if n == 2:
                assert gate.wait(timeout=30), "dispatch gate 超时"
            return AdminDisposition(
                run_id=run_id, spec="spec-a", success=False,
                problem="环境阻塞", actions_taken="尝试修复失败",
                result="failed",
                summary="诊断结论：环境阻塞；处置时间线：尝试修复失败；结果：失败。",
            )

        self.chain._dispatch_admin = fake_dispatch

        # ── T0 冻结竞态：冻结态下信号入链 → 预检拦（零派发零配额）────
        # （用户定调 2026-11-05 改道：冻结件直达 Arbiter 冻结鉴定——
        # Arbiter 先处理后仍失败才落人工，不再 deferred 等人工解冻）
        assert self.chain.submit_entry(
            spec="spec-a", signal_type="verify_env_blocked", severity="major",
            description="验证环境阻塞", evidence="env log",
            recommended_action="修复环境", source="incident-e2e",
        ) == "queued"
        assert self._drain()
        assert dispatch_calls == []  # T0 零派发
        assert not (self.chain._quota.snapshot().get(_SIG) or {}).get("admin_attempts")
        assert len(self.lane.calls) == 1  # Arbiter 冻结鉴定接单（默认 escalated）
        assert len(self.pm.alerts) == 1  # Arbiter 处理后上升（链终点件 #1）
        assert self._deferred_entries() == []

        # ── T1 解冻 + 复发入链：互斥命中活 manual run → 让行 ──────────
        self.sm.update_spec("spec-a", {"frozen": False})
        self._append_pending_aged("admin-manual-1", "manual-intervention", 0)
        self._write_run("admin-manual-1", [
            {"type": "assistant", "message": {"content": [{"type": "text"}]}},
        ])  # 非终态 = manual run 在飞
        assert self.chain.submit_entry(
            spec="spec-a", signal_type="verify_env_blocked", severity="major",
            description="验证环境阻塞", evidence="env log",
            recommended_action="修复环境", source="incident-e2e",
        ) == "queued"
        assert self._wait_until(lambda: (
            len(self._deferred_entries()) == 1
            and self._deferred_entries()[0]["yield_to"] == "admin-manual-1"
        ))  # 让行留痕（互斥让行为 deferred 唯一来源）
        assert len(dispatch_calls) == 0  # 让行不派发

        # ── T2 被让行 run 死：manual run 落终态 → 看护再扫 → 互斥放行 ──
        self._append_run_line("admin-manual-1", {
            "type": "error", "error": "manual run crashed"})
        assert self.mon._scan_deferred_chain_items() == 1
        assert self._wait_until(lambda: len(dispatch_calls) == 1)
        # adm-1 的 pending 残留（run 已死）不占互斥面（自证在飞死锁豁免）
        # → 链头第二次尝试放行、烧满配额 → Arbiter
        assert self._wait_until(lambda: len(dispatch_calls) == 2)
        gate.set()  # 放行第二次派发（T4 窗口构造点）
        assert self._drain()

        # ── T3 链终点：Admin 烧满 2 次 → Arbiter escalated → 人工上升件 ──
        quota = self.chain._quota.snapshot().get(_SIG) or {}
        assert quota.get("admin_attempts") == 2
        assert len(self.lane.calls) == 2  # Arbiter 接手两次（T0 冻结鉴定 + T3 终点）
        assert len(self.pm.alerts) == 2  # 链终点人工上升件（T0 + T3 各一）
        assert self.pm.alerts[0]["chain_context"]["chain_id"]
        assert self._in_flight_all_cleared()
        assert self._deferred_entries() == []

        # ── T4 终局对账：人工队列只含两次链终点件（T0 冻结鉴定 + T3）───
        esc = self._escalations()
        assert len(esc) == 2
        for e in esc:
            assert e.get("chain")  # 链关联键在场（与看护出件形态区分）
        # 看护复扫（链痕已全消）：adm-N pending 已由链终点收口语义覆盖，
        # 孤儿兜底升级不得再产出同签名第二件——T4 窗口已验证抑制，此处
        # 断言全链路终态人工面收敛
        assert self.mon._scan_deferred_chain_items() == 0  # 无残留可重派

    def test_suppression_window_during_chain_inflight(self):
        """T4 独立验证：链在办窗口内孤儿看护对链头死 run 的 pending
        不告警不终结（首例「看护 critical 早于链终点裁决包 3 分钟」的
        重复出件被消除）。"""
        import threading

        from core.agent_runner import AdminDisposition

        gate = threading.Event()
        dispatch_calls = []

        def fake_dispatch(item):
            n = len(dispatch_calls) + 1
            dispatch_calls.append(dict(item))
            run_id = f"adm-{n}"
            self._append_pending_aged(run_id, "verify_env_blocked", 20)
            self._write_run(run_id, [
                {"type": "assistant", "message": {"content": []}},
                {"type": "error", "error": "boom"},
            ])
            if n == 2:
                assert gate.wait(timeout=30)
            return AdminDisposition(
                run_id=run_id, spec="spec-a", success=False,
                problem="p", actions_taken="a", result="failed",
                summary="诊断结论：x；处置时间线：y；结果：失败。",
            )

        self.chain._dispatch_admin = fake_dispatch
        # T0 冻结 → 解冻直派（无 manual 竞争）→ Admin 第一败
        self.sm.update_spec("spec-a", {"frozen": False})
        assert self.chain.submit_entry(
            spec="spec-a", signal_type="verify_env_blocked", severity="major",
            description="验证环境阻塞", evidence="env log",
            recommended_action="修复环境", source="incident-e2e",
        ) == "queued"
        assert self._wait_until(lambda: len(dispatch_calls) == 2)
        # 此时链 worker 阻塞在第二次派发内：adm-1 pending 超时 + run 死 +
        # 链 in_flight 在办 → 看护巡检必须抑制
        assert self._wait_until(lambda: len(self._deferred_entries()) == 0)
        in_flight_admin = self._wait_until(lambda: any(
            entry_phase(x) == "admin"
            for x in load_chain_state(self.tmp)["in_flight"]
        ))
        assert in_flight_admin  # 链在办痕迹在场（抑制依据）
        self.mon._recover_orphaned_dispositions()
        assert self._escalations() == []  # 链在办：零看护告警
        # 零看护终结（pending 原状保留）——非 pending 处置记录仅链侧 final
        # 落账单点自带（fix-escalation-chain-ledger-closure 1.3：adm-1 派发
        # 返回即落 final），看护自身不得终结在飞窗口内的 adm-2 pending
        disps = [r for r in self.store.read_all()
                 if r.get("kind") == "disposition" and r.get("status") != "pending"]
        assert {str(r.get("admin_run_id") or "") for r in disps} == {"adm-1"}
        gate.set()
        assert self._drain()
        assert len(self.pm.alerts) == 1  # 链终点唯一人工作品

    def _in_flight_all_cleared(self):
        from core.pm_engine.escalation_chain import load_chain_state

        return load_chain_state(self.tmp)["in_flight"] == []


# ══ fix-escalation-chain-ledger-closure：链侧终态落账 / choice 执行 / 事件 run_id ══


class TestLedgerClosure(unittest.TestCase):
    """tasks 1.3/1.4/3.2：链上 admin run 终态即时落账守卫 + 双路径字段契约。

    复刻首例事件 …6474 时间轴形态作回归锚：``run_administrator`` 唤起前落
    pending（替身内复刻，对齐 maintenance_runs 既有行为）、链头三分支任一
    出口完成后 MUST 存在带该 run_id 的非 pending 处置记录——否则 pending
    永久孤儿 → 15 分钟 grace 后孤儿看护假「处置中断」升级（一天 4 例实证
    的结构性根因）。seam 策略同 TestAcceptanceScenarios：Admin 派发缝替身
    内先落 pending 再返回脚本化终态，链序/落账/闭环语义由真链机器承载。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )
        reset_chain()
        from core.state_machine import StateMachine

        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": False})
        self.chain = EscalationChain(self.tmp, MagicMock())
        self.chain.set_runner(MagicMock())
        self.chain.set_state_machine(sm)
        self.pm = _FakePm(self.tmp)
        self.chain.set_pm(self.pm)
        self.lane = _FakeArbiterLane(self.tmp)
        self._lane_patcher = patch(
            "core.pm_engine.arbiter.get_lane", lambda *a, **k: self.lane
        )
        self._lane_patcher.start()

    def tearDown(self):
        self._lane_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    # ── 装置 ────────────────────────────────────────────────────────

    def _install_dispatch_with_pending(self, script):
        """链头派发缝替身：先落 pending（复刻 run_administrator 唤起序），
        再返回脚本化终态。返回替身输出收集器。"""
        from core.admin_store import DISPOSITION, AdminStore

        store = AdminStore(self.tmp)
        out = []

        def fake_dispatch(item):
            d = script.pop(0) if script else _disp()
            out.append(d)
            try:
                store.append({
                    "kind": DISPOSITION, "status": "pending", "result": "pending",
                    "signal_type": item.get("signal_type"),
                    "spec": item.get("spec") or "global",
                    "admin_run_id": d.run_id,
                })
            except Exception:
                pass  # run_administrator 对 pending 落盘失败内部降级继续（同款保真）
            return d

        self.chain._dispatch_admin = fake_dispatch
        return out

    def _submit_and_drain(self):
        assert self.chain.submit_entry(
            spec="spec-a", signal_type="verify_env_blocked", severity="major",
            description="验证环境阻塞", evidence="env log",
            recommended_action="修复环境", source="ledger-closure-test",
        ) == "queued"
        assert _drain_chain(self.chain)

    def _dispositions(self):
        from core.admin_store import DISPOSITION, AdminStore

        return [r for r in AdminStore(self.tmp).read_all()
                if r.get("kind") == DISPOSITION]

    def _finals_for(self, run_id):
        return [r for r in self._dispositions()
                if str(r.get("admin_run_id") or "") == run_id
                and (r.get("status") or r.get("result")) != "pending"]

    def _ledger_events(self):
        from core.pm_engine.arbiter import load_arbiter_ledger

        return load_arbiter_ledger(self.tmp)

    # ── 首例时间轴三形态守卫（…6474 形态 MUST NOT 再产无 final 孤儿）──

    def test_success_outlet_final_record_closes_pending(self):
        script = [_disp(run_id="adm-6474", result="resolved", success=True,
                        status_after="ready")]
        self._install_dispatch_with_pending(script)
        self._submit_and_drain()

        finals = self._finals_for("adm-6474")
        assert len(finals) == 1
        assert finals[0]["result"] == "resolved"
        # 不变式（守卫本体）：by_run 归并判该 run 已终结——pending 不再被
        # 孤儿看护判为超时孤儿
        from core.admin_monitor import _merge_admin_runs
        from core.admin_store import AdminStore

        by_run = _merge_admin_runs(AdminStore(self.tmp).read_all())
        assert by_run["adm-6474"]["final"] is True
        # 链 closed 事件在场且 run_id 落实际 admin run id（3.2）
        closed = [e for e in self._ledger_events() if e.get("kind") == "chain-closed"]
        assert len(closed) == 1 and closed[0]["run_id"] == "adm-6474"
        # 时序不变式：final 落账先于链 closed 事件（D2）
        assert str(finals[0]["created"]) <= str(closed[0]["created"])
        # 链闭环：人工队列零痕迹
        assert self.pm.alerts == []

    def test_handoff_outlet_final_record_present(self):
        script = [_disp(run_id="adm-h", result="resolved", success=True,
                        handoff="arbiter", handoff_reason="超范围")]
        self._install_dispatch_with_pending(script)
        self.lane.outcomes = ["resolved"]
        self._submit_and_drain()

        finals = self._finals_for("adm-h")
        assert len(finals) == 1
        # result 保持管理员终态原值、escalate 位保持 disp 原值
        assert finals[0]["result"] == "resolved"
        assert finals[0]["escalate"] is False
        # 链继续 Arbiter 相（转单已达车道）
        assert len(self.lane.calls) == 1
        # chain-handoff 事件 run_id 落实际 admin run id（3.2）
        handoffs = [e for e in self._ledger_events()
                    if e.get("kind") == "chain-handoff"]
        assert handoffs and handoffs[0]["run_id"] == "adm-h"
        # Arbiter 相 chain-closed 事件 run_id 语义不变（既有行为：不落
        # admin run id，arbiter run id 只在文案里）
        closed = [e for e in self._ledger_events() if e.get("kind") == "chain-closed"]
        assert closed and closed[0]["run_id"] != "adm-h"

    def test_exhausted_outlet_finals_for_every_attempt(self):
        script = [
            _disp(run_id="adm-e1", result="failed", success=False, error="boom1"),
            _disp(run_id="adm-e2", result="failed", success=False, error="boom2"),
        ]
        self._install_dispatch_with_pending(script)
        self._submit_and_drain()

        for rid in ("adm-e1", "adm-e2"):
            assert len(self._finals_for(rid)) == 1, rid
        # 耗尽转单事件 run_id 落末次尝试 run id（3.2）
        handoffs = [e for e in self._ledger_events()
                    if e.get("kind") == "chain-handoff"]
        assert handoffs and handoffs[-1]["run_id"] == "adm-e2"

    def test_ledger_append_failure_degrades_not_blocks(self):
        script = [_disp(run_id="adm-d", result="resolved", success=True,
                        handoff="arbiter", handoff_reason="超范围")]
        self._install_dispatch_with_pending(script)
        self.lane.outcomes = ["escalated"]
        with patch.object(
            __import__("core.admin_store", fromlist=["AdminStore"]).AdminStore,
            "append", side_effect=OSError("disk full"),
        ):
            self._submit_and_drain()

        # 落账失败不阻断分支判定：handoff 判定照常触达 Arbiter 车道
        assert len(self.lane.calls) == 1

    # ── 双路径字段形状契约（D1 单源防族孪漂移）──────────────────────

    def test_contract_direct_and_chain_record_shape_identical(self):
        from core.agent_runner import AdminDisposition
        from core.admin_store import AdminStore

        # 直接路径形态参照：真 AdminDisposition 经同一落账助手产出（1.2 起
        # _worker 亦走此单点）
        store = AdminStore(self.tmp)
        direct_disp = AdminDisposition(
            run_id="adm-direct", spec="spec-a", success=True,
            problem="环境阻塞", actions_taken="修复动作", result="resolved",
            recommended_action="建议", summary="诊断结论：x；结果：已解决。",
            error="", choice_id="", suggested_choice="", choice_payload="",
        )
        assert store.append_admin_final(
            {"signal_type": "verify_env_blocked", "spec": "spec-a",
             "severity": "major", "description": "验证环境阻塞",
             "recommended_action": "修复环境"},
            direct_disp,
        ) is True
        direct_rec = self._finals_for("adm-direct")[0]

        # 链路径产出：成功闭环出口
        script = [_disp(run_id="adm-chain", result="resolved", success=True,
                        status_after="ready", problem="环境阻塞",
                        actions_taken="修复动作", recommended_action="建议",
                        summary="诊断结论：x；结果：已解决。")]
        self._install_dispatch_with_pending(script)
        self._submit_and_drain()
        chain_rec = self._finals_for("adm-chain")[0]

        # 字段形状一致（键集合同一；值随 run 不同属正常）
        assert set(direct_rec.keys()) == set(chain_rec.keys())
        # 关键形状断言：结构化裁决字段与载荷恒在（空值 None 形态稳定口径）
        for k in ("choice_id", "suggested_choice", "choice_payload",
                  "failure_evidence", "admin_run_id", "escalate", "error"):
            assert k in chain_rec, k

    def test_worker_final_append_delegates_to_shared_helper(self):
        # 源级守卫（对齐本文件 TestAntiSelfLoopInventory 扫描风格）：
        # 直接路径 _worker 的 final 落账已收敛到共享助手，内联字段拼装
        # 不复存在（防两路径再漂移）
        src = Path("core/admin_monitor.py").read_text(encoding="utf-8")
        assert "self.store.append_admin_final(signal, disp" in src
        assert "Failed to persist administrator disposition" not in src

    # ── chain_events_for_run 查询口（3.3 单测面）────────────────────

    def test_chain_events_for_run_filters_and_fail_open(self):
        script = [_disp(run_id="adm-q", result="resolved", success=True,
                        status_after="ready")]
        self._install_dispatch_with_pending(script)
        self._submit_and_drain()

        hits = self.chain.chain_events_for_run("adm-q")
        assert hits and all(e["run_id"] == "adm-q" for e in hits)
        assert self.chain.chain_events_for_run("adm-no-such") == []
        # 台账损坏 fail-open（零命中）
        ledger = self.tmp / ".fenix" / "arbiter_ledger.jsonl"
        ledger.write_text("{broken json", encoding="utf-8")
        assert self.chain.chain_events_for_run("adm-q") == []


class TestChainChoiceExecution(unittest.TestCase):
    """tasks 2.2/2.3：链 closed 出口执行注册表 choice（payload 型生效 /
    执行失败不伪造闭环 / 白名单外保持转单）。

    执行器缝 patch ``core.dashboard.data.admin_actions.
    execute_adjudication_choice``（模块级单源执行机器的底层执行器）——
    链侧调用链（_execute_chain_choice → admin_choice_exec → 执行器）真实
    执行，只脚本化最底层动作面。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".fenix" / "config.yaml").write_text(
            "arbiter:\n  enabled: true\n"
            "chain:\n  admin_attempts: 2\n  arbiter_rulings: 2\n"
            "  reset_window_days: 7\n",
            encoding="utf-8",
        )
        reset_chain()
        from core.state_machine import StateMachine

        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": False})
        self.chain = EscalationChain(self.tmp, MagicMock())
        self.chain.set_runner(MagicMock())
        self.chain.set_state_machine(sm)
        self.pm = _FakePm(self.tmp)
        self.chain.set_pm(self.pm)
        self.lane = _FakeArbiterLane(self.tmp)
        self._lane_patcher = patch(
            "core.pm_engine.arbiter.get_lane", lambda *a, **k: self.lane
        )
        self._lane_patcher.start()
        from core.admin_store import DISPOSITION, AdminStore

        self.store = AdminStore(self.tmp)
        self._DISPOSITION = DISPOSITION
        self.exec_calls = []

    def tearDown(self):
        self._lane_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_chain()

    def _install_dispatch(self, script):
        def fake_dispatch(item):
            d = script.pop(0) if script else _disp()
            self.store.append({
                "kind": self._DISPOSITION, "status": "pending",
                "result": "pending",
                "signal_type": item.get("signal_type"),
                "spec": item.get("spec") or "global",
                "admin_run_id": d.run_id,
            })
            return d

        self.chain._dispatch_admin = fake_dispatch

    def _submit_and_drain(self):
        assert self.chain.submit_entry(
            spec="spec-a", signal_type="verify_env_blocked", severity="major",
            description="验证环境阻塞", evidence="env log",
            recommended_action="修复环境", source="chain-choice-test",
        ) == "queued"
        assert _drain_chain(self.chain)

    def _patch_executor(self, result=None, exc=None):
        recorded = self.exec_calls

        def fake_executor(project_root, spec, choice_id, note="",
                          signal_type=""):
            recorded.append({
                "project_root": project_root, "spec": spec,
                "choice_id": choice_id, "note": note,
                "signal_type": signal_type,
            })
            if exc is not None:
                raise exc
            return dict(result or {})

        return patch(
            "core.dashboard.data.admin_actions.execute_adjudication_choice",
            fake_executor,
        )

    def _dispositions(self):
        return [r for r in self.store.read_all()
                if r.get("kind") == self._DISPOSITION]

    def _ledger_kinds(self):
        from core.pm_engine.arbiter import load_arbiter_ledger

        return [str(r.get("kind") or "") for r in load_arbiter_ledger(self.tmp)]

    def test_payload_choice_executes_on_chain(self):
        payload = json.dumps(
            {"scenarios": ["scenario-a"], "reason": "场景定义不可行"},
            ensure_ascii=False,
        )
        script = [_disp(run_id="adm-c", result="resolved", success=True,
                        status_after="ready",
                        choice_id="revise_scenario_reverify",
                        choice_payload=payload)]
        self._install_dispatch(script)
        with self._patch_executor(
            result={"ok": True, "action": "revise_scenario_reverify",
                    "steps": ["wrote scenario pair"]},
        ):
            self._submit_and_drain()

        # 执行器被调用：载荷原文整体直传（不经截断）
        assert len(self.exec_calls) == 1
        call = self.exec_calls[0]
        assert call["spec"] == "spec-a"
        assert call["choice_id"] == "revise_scenario_reverify"
        assert call["note"] == payload
        assert call["signal_type"] == "verify_env_blocked"
        # 逐动作 DISPOSITION 审计记录落账（result=resolved、无 admin_run_id）
        audits = [r for r in self._dispositions()
                  if r.get("action_taken") == "revise_scenario_reverify"
                  and not r.get("admin_run_id")]
        assert len(audits) == 1 and audits[0]["result"] == "resolved"
        # 闭环事件在执行成功后写（chain-closed 在场 + final 落账在前）
        assert "chain-closed" in self._ledger_kinds()
        finals = [r for r in self._dispositions()
                  if str(r.get("admin_run_id") or "") == "adm-c"
                  and (r.get("status") or r.get("result")) != "pending"]
        assert len(finals) == 1
        # 成功闭环不计失败
        assert ChainQuotaStore(self.tmp).admin_attempts(_SIG) == 0
        assert self.pm.alerts == []

    def test_choice_execution_failure_no_false_closure(self):
        script = [
            _disp(run_id="adm-f1", result="resolved", success=True,
                  status_after="ready", choice_id="revise_scenario_reverify",
                  choice_payload=json.dumps({"scenarios": ["s"]})),
            _disp(run_id="adm-f2", result="resolved", success=True,
                  status_after="ready"),  # 重试后无 choice → 正常闭环
        ]
        self._install_dispatch(script)
        with self._patch_executor(exc=RuntimeError("载荷非法：scenarios 缺失")):
            self._submit_and_drain()

        # fail-closed：不伪造闭环——执行失败事件在场 + 计一次失败
        assert "chain-choice-failed" in self._ledger_kinds()
        assert ChainQuotaStore(self.tmp).admin_attempts(_SIG) == 1
        failed_ev = [e for e in self._ledger_all()
                     if e.get("kind") == "chain-choice-failed"]
        assert failed_ev[0]["run_id"] == "adm-f1"
        assert "载荷非法" in failed_ev[0]["action_or_upgrade"]
        # 该件按链既有失败语义处理：配额未尽回环重派 → 第二次成功闭环
        assert "chain-closed" in self._ledger_kinds()
        assert self.pm.alerts == []

    def test_choice_skipped_payload_missing_fails_closed(self):
        # requires_payload 选项而处置记录未携带载荷 → 执行器主动跳过
        # （ok=False skipped，执行器不被触达）→ 链侧同款 fail-closed
        script = [_disp(run_id="adm-s1", result="resolved", success=True,
                        status_after="ready",
                        choice_id="revise_scenario_reverify")]
        self._install_dispatch(script)
        with self._patch_executor(
            result={"ok": True, "action": "revise_scenario_reverify"},
        ):
            self._submit_and_drain()

        assert self.exec_calls == []  # 载荷缺失在执行机器内被跳过，执行器不触达
        assert "chain-choice-failed" in self._ledger_kinds()
        assert ChainQuotaStore(self.tmp).admin_attempts(_SIG) >= 1
        assert "chain-closed" not in self._ledger_kinds()  # 首件未伪造闭环

    def test_out_of_allowlist_choice_still_hands_off(self):
        # 白名单外（人类拍板面 raise_budget）→ 不执行、转单 Arbiter 不计失败
        script = [_disp(run_id="adm-o", result="resolved", success=True,
                        status_after="ready", choice_id="raise_budget")]
        self._install_dispatch(script)
        self.lane.outcomes = ["escalated"]
        with self._patch_executor(
            result={"ok": True, "action": "raise_budget"},
        ):
            self._submit_and_drain()

        assert self.exec_calls == []  # 白名单外不执行
        assert len(self.lane.calls) == 1  # 越界复核转单照常
        assert ChainQuotaStore(self.tmp).admin_attempts(_SIG) == 0  # 不计失败
        handoffs = [e for e in self._ledger_all()
                    if e.get("kind") == "chain-handoff"]
        assert handoffs and handoffs[0]["run_id"] == "adm-o"
        # final 记录照常落账（越界件同样不产孤儿 pending）
        finals = [r for r in self._dispositions()
                  if str(r.get("admin_run_id") or "") == "adm-o"
                  and (r.get("status") or r.get("result")) != "pending"]
        assert len(finals) == 1

    # ── 台账读取小工具 ──────────────────────────────────────────────

    def _ledger_all(self):
        from core.pm_engine.arbiter import load_arbiter_ledger

        return load_arbiter_ledger(self.tmp)
