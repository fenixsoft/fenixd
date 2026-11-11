"""add-adjudication-auto-exec 2.4：自动执行策略引擎单元测试。

覆盖（specs/adjudication-auto-exec/spec.md + tasks.md 2.4 指定场景）：
- 到点自动执行成功：真实执行链（execute_choice_for_disposition →
  reset_verification）走通，DISPOSITION 留痕 actor=auto-policy，告警
  handled_by=auto-policy 闭环，spec 出 blocked；
- 四判据逐条缺失跳过（①无调查痕/零命中/歧义/纯否定 ②非可逆档
  ③载荷位/全局形态 ④共存更高档 ⑤连续 cap 超限）；
- grace 窗自推荐落账时刻起算（异步升级件 upgraded_at 晚于 created，
  窗口完整，不以 created 锚导致否决窗归零）；
- 人工先到先得不重复执行（执行前瞬时重读让位）；
- 开关停用（enabled=false 零动作）；
- 单条异常隔离（同轮其余告警照常处理）；
- 老化升级（2.3：human-only 档 warning/critical 两档 + 去重 + 可逆档不升）；
- 连续计数派生语义（aging-watch / pending 中性跳过，人工留痕断链）。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_auto_exec import (  # noqa: E402
    AGING_ACTOR,
    AUTO_POLICY_ACTOR,
    AdminAutoExecEngine,
)
from core.admin_store import AdminStore, DISPOSITION, ESCALATION  # noqa: E402
from core.dashboard.data.adjudication_choices import choices_for  # noqa: E402
from tests.helpers import FakeLogger  # noqa: E402

SPEC = "spec-auto"


# ── 夹具 ────────────────────────────────────────────────────────────────


def _write_state(proot: Path, specs: dict) -> None:
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, fields in specs.items():
        lines.append(f"### {name}")
        for k, v in fields.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    (proot / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")


def _make_proot(tmp_path: Path) -> Path:
    """blocked spec 处于 judge_rerun_cap 冻结形态（reset_verification
    成功路径夹具，同 test_adjudication_choices.py 成功用例形态）。"""
    proot = tmp_path / "proj-auto"
    (proot / ".fenix").mkdir(parents=True)
    fields = {
        "status": "blocked",
        "priority": 2,
        "created": "2026-01-01T00:00:00+00:00",
        "updated": "2026-01-02T00:00:00+00:00",
        "error": "judge_rerun_cap: judge 重跑达上限（原状态 testing）",
        "depends_on": "null",
        "frozen": True,
        "_judge_rerun_count": 3,
        "_judge_cap_frozen": True,
        "_verify_fail_rounds": 2,
    }
    _write_state(proot, {SPEC: fields})
    vp = proot / ".fenix" / "verify-progress" / SPEC
    vp.mkdir(parents=True)
    for name in ("test_scenarios.json", "_scenarios_full.json", "tokens.json"):
        (vp / name).write_text("{}", encoding="utf-8")
    return proot


def _iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _make_engine(proot, store, config=None):
    cfg = {"auto_exec": dict(config or {})}
    return AdminAutoExecEngine(cfg, proot, FakeLogger(), store=store)


def _make_alert(store, *, spec=SPEC, signal_type="judge_rerun_cap",
                severity="major", created_minutes_ago=0.0, upgrade=None):
    """pending 升级告警（choices 快照取注册表桶；arbiter_upgrade 直写
    任意 upgraded_at——store.arbiter_upgrade 写点恒 now，测试需历史锚）。"""
    rec = {
        "kind": ESCALATION,
        "signal_type": signal_type,
        "spec": spec,
        "severity": severity,
        "description": "judge 重跑达上限（原状态 testing）",
        "created": _iso(created_minutes_ago),
        "choices": [dict(c) for c in choices_for(signal_type)],
    }
    if upgrade is not None:
        rec["arbiter_upgrade"] = upgrade
    return store.append(rec)["id"]


def _upgrade(recommended, minutes_ago=31.0):
    return {
        "summary": "arbiter 调查完成",
        "recommended_action": recommended,
        "run_id": "run-arb-1",
        "upgraded_at": _iso(minutes_ago),
    }


def _dispositions(store):
    return [r for r in store.read_all() if r.get("kind") == DISPOSITION]


def _auto_dispositions(store):
    return [r for r in _dispositions(store)
            if r.get("actor") == AUTO_POLICY_ACTOR]


def _alert(store, alert_id):
    return next(r for r in store.read_all()
                if r.get("id") == alert_id and r.get("kind") == ESCALATION)


def _mutate_alert(store, alert_id, **fields):
    """原地改写告警字段（update_records(fn) 契约：fn 原地修改，返回值仅为
    写回结果——返回新列表不落盘）。"""
    def fn(rs):
        for r in rs:
            if r.get("id") == alert_id:
                r.update(fields)
        return True
    assert store.update_records(fn)


def _rewrite_recommendation(store, alert_id, text):
    """改写 arbiter_upgrade.recommended_action（保 upgraded_at 其余字段）。"""
    def fn(rs):
        for r in rs:
            if (r.get("id") == alert_id
                    and isinstance(r.get("arbiter_upgrade"), dict)):
                r["arbiter_upgrade"] = dict(
                    r["arbiter_upgrade"], recommended_action=text)
        return True
    assert store.update_records(fn)


# ── 到点自动执行成功 ────────────────────────────────────────────────────


class TestSuccessAutoExec:
    def test_executes_reversible_recommendation_with_trace(self, tmp_path):
        """grace 满四判据全过：真实执行链走通 + 留痕 actor=auto-policy + 闭环。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        # 否定语境跨兄弟列表：「不推荐 force_advance/abandon」不构成正向，
        # 唯一正向命中 manual_fixed_reverify（reversible-experiment）
        alert_id = _make_alert(store, upgrade=_upgrade(
            "调查结论：不推荐 force_advance/abandon，"
            "推荐 manual_fixed_reverify 重跑验证"))
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 1
        rec = _alert(store, alert_id)
        assert rec["handled"] is True
        assert rec["handled_by"] == AUTO_POLICY_ACTOR
        assert rec["action_taken"] == "reset_verification"
        auto = _auto_dispositions(store)
        assert len(auto) == 1
        d = auto[0]
        assert d["choice_id"] == "manual_fixed_reverify"
        assert d["result"] == "resolved"
        assert d["alert_id"] == alert_id
        assert d["auto_exec"] is True
        assert d["spec"] == SPEC
        # 执行真实落效应：spec 出 blocked（BLOCKED→READY 复位通道）
        from core.dashboard.data import parse_state

        assert parse_state(proot)[SPEC]["status"] == "ready"

    def test_execution_failure_keeps_alert_pending(self, tmp_path):
        """执行失败不闭环：告警保持 pending 等人工，留痕 result=failed。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        # spec 无关联 STATE 条目 → reset_verification 报 spec not found
        alert_id = _make_alert(store, spec="spec-ghost",
                               upgrade=_upgrade("推荐 manual_fixed_reverify"))
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        rec = _alert(store, alert_id)
        assert rec["handled"] is False
        auto = _auto_dispositions(store)
        assert len(auto) == 1
        assert auto[0]["result"] == "failed"
        assert "not found" in str(auto[0].get("error") or "")

    def test_requires_payload_choice_skipped(self, tmp_path):
        """可逆档但 requires_payload：自动通道无载荷，前置跳过等人工。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = _make_alert(
            store, signal_type="inconclusive_loop",
            upgrade=_upgrade("推荐 revise_scenario_reverify"),
        )
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False
        assert _auto_dispositions(store) == []


# ── grace 窗锚点与时效 ──────────────────────────────────────────────────


class TestGraceWindow:
    def test_not_due_within_grace(self, tmp_path):
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = _make_alert(store, upgrade=_upgrade(
            "推荐 manual_fixed_reverify", minutes_ago=5.0))
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False
        assert _auto_dispositions(store) == []

    def test_grace_anchored_at_upgraded_at_not_created(self, tmp_path):
        """异步升级件：created 早于 upgraded_at（推荐落账）3 小时——窗口自
        upgraded_at 起算完整；若误锚 created 则此刻已「到期」误执行。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = _make_alert(
            store, created_minutes_ago=180.0,
            upgrade=_upgrade("推荐 manual_fixed_reverify", minutes_ago=10.0),
        )
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False

    def test_grace_anchored_fallback_created_without_upgrade_time(self, tmp_path):
        """upgrade 痕缺 upgraded_at（历史形态）→ 回退 created 锚。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        upg = _upgrade("推荐 manual_fixed_reverify")
        upg.pop("upgraded_at")
        alert_id = _make_alert(store, created_minutes_ago=60.0, upgrade=upg)
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 1
        assert _alert(store, alert_id)["handled_by"] == AUTO_POLICY_ACTOR

    def test_custom_grace_minutes_respected(self, tmp_path):
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = _make_alert(store, upgrade=_upgrade(
            "推荐 manual_fixed_reverify", minutes_ago=10.0))
        engine = _make_engine(proot, store, config={"grace_minutes": 5})
        assert engine.scan_once() == 1
        assert _alert(store, alert_id)["handled"] is True


# ── 四判据逐条缺失跳过 ──────────────────────────────────────────────────


class TestCriteriaSkips:
    def _due_alert(self, store, **kw):
        return _make_alert(store, created_minutes_ago=120.0,
                           upgrade=_upgrade("推荐 manual_fixed_reverify",
                                            minutes_ago=120.0), **kw)

    def test_no_arbiter_upgrade_waits_human(self, tmp_path):
        """判据①前半：无 arbiter 完整调查/推荐痕——静默等人工。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._due_alert(store)
        _mutate_alert(store, alert_id, arbiter_upgrade=None)
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False

    def test_zero_positive_mention_skips(self, tmp_path):
        """判据①后半：推荐文本对全部选项零正向提及。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._due_alert(store)
        _rewrite_recommendation(store, alert_id, "继续观察，无需处置")
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False
        assert _auto_dispositions(store) == []

    def test_negation_only_mention_skips(self, tmp_path):
        """全部提及均处否定语境（跨兄弟列表）→ 零正向命中跳过。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._due_alert(store)
        _rewrite_recommendation(
            store, alert_id,
            "不推荐 manual_fixed_reverify、force_advance、abandon，请人工研判")
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False

    def test_ambiguous_mention_skips(self, tmp_path):
        """判据①后半：多义命中判歧义，宁跳过勿误执行。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._due_alert(store)
        _rewrite_recommendation(
            store, alert_id, "推荐 manual_fixed_reverify 或 force_advance")
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False

    def test_non_reversible_tier_skips(self, tmp_path):
        """判据②：推荐 state-advance 档不自动执行等人工。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._due_alert(store)
        _rewrite_recommendation(store, alert_id, "推荐 force_advance")
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False

    def test_global_spec_form_skips(self, tmp_path):
        """判据②附带作用域守卫：spec_scoped 动作 × 全局形态 spec 跳过。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._due_alert(store, spec="global")
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False

    def test_higher_severity_conflict_skips(self, tmp_path):
        """判据③：同 SPEC 共存更高严重度 pending 告警，让人工一并裁决。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._due_alert(store, severity="major")
        # 共存件：同 SPEC critical、无调查痕（自身不会被处理）
        _make_alert(store, severity="critical", upgrade=None)
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False
        assert _auto_dispositions(store) == []

    def test_consecutive_cap_reached_transfers_to_human(self, tmp_path):
        """判据④：连续自动执行已达 cap 转纯人工等待。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        for _ in range(2):
            store.append({
                "kind": DISPOSITION, "signal_type": "judge_rerun_cap",
                "spec": SPEC, "severity": "major", "description": "prev",
                "action_taken": "reset_verification", "result": "resolved",
                "actor": AUTO_POLICY_ACTOR,
            })
        alert_id = self._due_alert(store)
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False
        # cap 放宽到 3 后同一告警即可自动执行
        engine2 = _make_engine(proot, store, config={"consecutive_max": 3})
        assert engine2.scan_once() == 1
        assert _alert(store, alert_id)["handled_by"] == AUTO_POLICY_ACTOR


# ── 先到先得 / 开关 / 隔离 ──────────────────────────────────────────────


class TestRaceAndGates:
    def test_human_first_to_act_wins(self, tmp_path):
        """grace 窗竞态：引擎持陈旧快照判四判据全过，执行前瞬时重读发现
        人工已处理 → 让位不重复执行（闭环归人工）。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = _make_alert(store, upgrade=_upgrade(
            "推荐 manual_fixed_reverify", minutes_ago=60.0))
        engine = _make_engine(proot, store)
        from core.config import ConfigLoader

        cfg = ConfigLoader.get_auto_exec_config(engine.config)
        # 引擎在窗口内拿到陈旧快照（此刻告警尚未被处理）
        stale = store.read_all()
        rec = next(r for r in stale if r.get("id") == alert_id)
        # 人工抢先处置真实落盘
        _mutate_alert(store, alert_id, handled=True, handled_by="human",
                      action_taken="manual_fixed_reverify")
        # 引擎持陈旧快照走判定：执行前重读让位
        assert engine._maybe_auto_exec(rec, stale, cfg) is False
        assert _auto_dispositions(store) == []
        assert _alert(store, alert_id)["handled_by"] == "human"

    def test_disabled_switch_zero_action(self, tmp_path):
        """enabled=false：整体停用回退纯人工语义（到期也不执行）。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = _make_alert(store, created_minutes_ago=600.0,
                               upgrade=_upgrade("推荐 manual_fixed_reverify",
                                                minutes_ago=600.0))
        engine = _make_engine(proot, store, config={"enabled": False})
        assert engine.scan_once() == 0
        assert _alert(store, alert_id)["handled"] is False
        assert _dispositions(store) == []

    def test_per_alert_exception_isolation(self, tmp_path):
        """单条判定异常被捕获隔离，同轮其余告警照常处理。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        bad_id = _make_alert(store, spec="spec-bad", upgrade=None)
        good_id = _make_alert(store, upgrade=_upgrade(
            "推荐 manual_fixed_reverify", minutes_ago=60.0))
        engine = _make_engine(proot, store)
        orig = engine._maybe_auto_exec

        def flaky(rec, pending, cfg):
            if str(rec.get("id") or "") == bad_id:
                raise RuntimeError("boom")
            return orig(rec, pending, cfg)

        engine._maybe_auto_exec = flaky
        assert engine.scan_once() == 1  # 异常条目跳过，正常条目执行
        assert _alert(store, bad_id)["handled"] is False
        assert _alert(store, good_id)["handled_by"] == AUTO_POLICY_ACTOR


# ── 2.3 老化升级 ────────────────────────────────────────────────────────


class TestAgingEscalation:
    def _human_only_alert(self, store, minutes_ago):
        return _make_alert(
            store, created_minutes_ago=minutes_ago,
            upgrade=_upgrade("推荐 force_advance", minutes_ago=minutes_ago),
        )

    def _aging_records(self, store):
        return [r for r in _dispositions(store) if r.get("actor") == AGING_ACTOR]

    def test_warning_level_at_2h(self, tmp_path):
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._human_only_alert(store, minutes_ago=130)
        engine = _make_engine(proot, store)
        assert engine.scan_once() == 0  # 不执行（human-only 档）
        aging = self._aging_records(store)
        assert len(aging) == 1
        assert aging[0]["alert_id"] == alert_id
        assert aging[0]["action_taken"] == "aging-escalated:warning"
        assert aging[0]["result"] == "aging"
        assert _alert(store, alert_id)["handled"] is False

    def test_critical_level_at_6h(self, tmp_path):
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = self._human_only_alert(store, minutes_ago=370)
        engine = _make_engine(proot, store)
        engine.scan_once()
        aging = self._aging_records(store)
        assert len(aging) == 1
        assert aging[0]["action_taken"] == "aging-escalated:critical"
        assert aging[0]["severity"] == "critical"

    def test_dedup_same_level(self, tmp_path):
        """同告警同档只记一条（引擎 60s 一轮，不去重会每分钟刷屏）。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        self._human_only_alert(store, minutes_ago=130)
        engine = _make_engine(proot, store)
        engine.scan_once()
        engine.scan_once()
        engine.scan_once()
        assert len(self._aging_records(store)) == 1

    def test_reversible_alert_never_ages(self, tmp_path):
        """可逆档走 grace 自动执行语义，不写老化升级（仍在窗内）。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        _make_alert(store, created_minutes_ago=400,
                    upgrade=_upgrade("推荐 manual_fixed_reverify",
                                     minutes_ago=5.0))
        engine = _make_engine(proot, store)
        engine.scan_once()
        assert self._aging_records(store) == []

    def test_no_recommendation_no_aging(self, tmp_path):
        """推荐歧义/无调查痕的告警语义未定档，不写老化（防不可判件刷屏）。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        _make_alert(store, created_minutes_ago=500, upgrade=None)
        engine = _make_engine(proot, store)
        engine.scan_once()
        assert self._aging_records(store) == []


# ── 连续计数派生语义 ────────────────────────────────────────────────────


class TestConsecutiveStreak:
    def _disp(self, store, actor=None, result="resolved", spec=SPEC):
        rec = {
            "kind": DISPOSITION, "signal_type": "judge_rerun_cap",
            "spec": spec, "severity": "major", "description": "d",
            "action_taken": "reset_verification", "result": result,
        }
        if actor is not None:
            rec["actor"] = actor
        store.append(rec)

    def test_counts_auto_policy_trail(self, tmp_path):
        from core.admin_store import AdminStore as S

        proot = _make_proot(tmp_path)
        store = S(proot, FakeLogger())
        self._disp(store, actor=AUTO_POLICY_ACTOR)
        self._disp(store, actor=AUTO_POLICY_ACTOR)
        engine = _make_engine(proot, store)
        assert engine._consecutive_auto_exec(SPEC) == 2

    def test_human_record_breaks_streak(self, tmp_path):
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        self._disp(store, actor=AUTO_POLICY_ACTOR)
        self._disp(store)  # 人工/链出口留痕：无 actor 字段
        engine = _make_engine(proot, store)
        assert engine._consecutive_auto_exec(SPEC) == 0

    def test_aging_and_pending_records_neutral(self, tmp_path):
        """aging-watch 与 pending 在飞标记中性跳过：不误计也不误重置。

        记录序（append 即时间序）：auto → aging → pending（在飞，无 actor）。
        从最新向前走查：pending 跳过、aging 跳过、auto 计 1。"""
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        self._disp(store, actor=AUTO_POLICY_ACTOR)
        self._disp(store, actor=AGING_ACTOR, result="aging")
        self._disp(store, actor=None, result="pending")
        engine = _make_engine(proot, store)
        assert engine._consecutive_auto_exec(SPEC) == 1

    def test_other_spec_isolated(self, tmp_path):
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        self._disp(store, actor=AUTO_POLICY_ACTOR, spec="spec-other")
        engine = _make_engine(proot, store)
        assert engine._consecutive_auto_exec(SPEC) == 0

    def test_global_spec_zero(self, tmp_path):
        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        engine = _make_engine(proot, store)
        assert engine._consecutive_auto_exec("") == 0


# ── 读侧投影（5.1 消费形态预演） ────────────────────────────────────────


class TestProjectionShape:
    def test_executed_flag_and_due(self, tmp_path):
        from core.admin_auto_exec import auto_exec_projection

        proot = _make_proot(tmp_path)
        store = AdminStore(proot, FakeLogger())
        alert_id = _make_alert(store, upgrade=_upgrade(
            "推荐 manual_fixed_reverify", minutes_ago=31.0))
        engine = _make_engine(proot, store)
        engine.scan_once()
        rec = _alert(store, alert_id)
        proj = auto_exec_projection(rec, grace_minutes=30)
        assert proj["executed"] is True
        assert proj["recommended_choice"] == "manual_fixed_reverify"
        assert proj["risk_tier"] == "reversible-experiment"
        assert proj["due_at"] is not None
        assert proj["anchor_at"] is not None

    def test_pending_alert_projects_countdown(self):
        from core.admin_auto_exec import auto_exec_projection

        rec = {
            "kind": ESCALATION, "signal_type": "judge_rerun_cap",
            "spec": SPEC, "severity": "major",
            "created": _iso(60.0),
            "choices": [dict(c) for c in choices_for("judge_rerun_cap")],
            "arbiter_upgrade": _upgrade("推荐 manual_fixed_reverify",
                                        minutes_ago=10.0),
        }
        proj = auto_exec_projection(rec, grace_minutes=30)
        assert proj["executed"] is False
        assert proj["recommended_choice"] == "manual_fixed_reverify"
        assert proj["risk_tier"] == "reversible-experiment"
        assert proj["skip_reason"] is None
        assert proj["due_at"] > rec["arbiter_upgrade"]["upgraded_at"]

    def test_human_closed_not_flagged_executed(self):
        from core.admin_auto_exec import auto_exec_projection

        rec = {
            "kind": ESCALATION, "signal_type": "judge_rerun_cap",
            "spec": SPEC, "severity": "major", "created": _iso(60.0),
            "choices": [dict(c) for c in choices_for("judge_rerun_cap")],
            "arbiter_upgrade": _upgrade("推荐 force_advance"),
            "handled": True, "handled_by": "human",
        }
        proj = auto_exec_projection(rec, grace_minutes=30)
        assert proj["executed"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
