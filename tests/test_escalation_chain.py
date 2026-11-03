"""add-escalation-chain-admin-arbiter：处置链核心测试。

1.1 防自环清单：_send_human_escalation_alert 与 freeze_for_human 全调用点
机械枚举并标注来源（框架信号 / 链成员产出）——框架信号经 family 咽喉入链
头，链成员产出走链终点直写（chain_context 携带，跳过链头重入）。新增调用
点绕过咽喉或链终点缺 chain_context 时本类红。

6.1 全 Scenario 覆盖见后续类（escalation-chain 与 chain-observability）。
"""

import glob
import re
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.pm_engine.escalation_chain import (
    ChainQuotaStore,
    EscalationChain,
    load_chain_state,
    reset_chain,
    set_chain,
)


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

        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": True})
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
        # 显式 status 解冻（拒绝 parse 兜底的正面路径）
        entry = self.chain._resolve_state_machine().read_one("spec-a")
        assert entry["frozen"] is False and entry["status"] == "ready"
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
        with patch(
            "core.admin_monitor._spec_has_active_admin_run", lambda *a, **k: True
        ):
            assert self._submit() == "queued"
            assert _drain_chain(self.chain)
        assert self.dispatch_calls == []      # 互斥守卫命中不双派
        assert self.pm.alerts == []           # 让行不上升（复发由下次触发重新入链）
        assert load_chain_state(self.tmp)["in_flight"] == []  # 让行后登记清零

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

        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": True})
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
    无 ``chain`` 关联键、降噪分级照旧（warning 写入即 handled）、narrative
    补叙照旧调度、配额水位零扰动；配置修复后自动恢复入链。
    """

    # 条目级易变字段（id/时间戳）不参与逐字节比对
    VOLATILE_FIELDS = {"id", "created", "updated", "handled_at"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        reset_chain()
        from core.pm_engine.arbiter import set_lane

        set_lane(None)
        import core.adjudication_narrative as adj_mod

        self._adj_mod = adj_mod
        self._orig_sched = adj_mod.schedule_narrative
        self.scheduled = []
        adj_mod.schedule_narrative = lambda *a, **k: self.scheduled.append(a)

    def tearDown(self):
        self._adj_mod.schedule_narrative = self._orig_sched
        from core.pm_engine.arbiter import set_lane

        set_lane(None)
        set_chain(None)
        reset_chain()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── 装置 ────────────────────────────────────────────────────────

    def _mk_sm(self):
        from core.state_machine import StateMachine

        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec("spec-a", {"status": "blocked", "frozen": True})
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
        self.scheduled.clear()
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
        # narrative 照旧调度；链侧零扰动（配额水位零写入）
        assert len(self.scheduled) == 2
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
        assert len(self.scheduled) == 2  # 基线与降级件各补叙一次（narrative 照旧）
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
