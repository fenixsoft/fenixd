"""add-arbiter-lane 6.2：护栏测试（3.2 红线契约含在本文件）。

覆盖 tasks 3.2 / 4.2 / 4.3 / 4.4 / 5.1：
- 红线契约断言：agents/arbiter.md 关键禁令词目与段落存在性机械断言（漏段
  即测试红），含占位符注入面（构建后无残留占位符）；
- 同签名复发直接升级、白名单外只产裁决包不擅动状态；
- 告警零噪音分层：处置成功原位终态化 resolved_by=arbiter（不新增条目）、
  升级同 alert_id 原位静默更新 + 推 pending + narrative 槽位裁决包；
- 关闭态零侵扰：enabled=false 时 narrative 让位判定 False、freeze 咽喉短路
  零写入；
- 台账五段完整、_log_lane_run_metrics 指标行落盘、立项节流三限、narrative
  让位与非阻塞类不受扰。

复用 tests/test_arbiter_lane.py 的替身组件（FakeRunner/FakeStateMachine），
告警存储用真实 AdminStore（tmp 项目根，不落 HOME）。
"""

import json
import re
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.admin_store import AdminStore, ESCALATION
from core.adjudication_narrative import (
    load_narrative_sidecars,
    narrative_yielded_to_arbiter,
)
from core.agent_runner.maintenance_runs import run_arbiter
from core.pm_engine.arbiter import (
    ARBITER_EXCLUDED_SIGNAL_TYPES,
    ARBITER_PINNED_MODEL,
    PROPOSAL_MAX_PER_RUN,
    PROPOSAL_WEEKLY_QUOTA,
    arbiter_report_path,
    get_lane,
    load_arbiter_ledger,
    reset_lane,
    set_lane,
)
from tests.test_arbiter_lane import (
    FakeLogger,
    FakeRunner,
    FakeStateMachine,
    drain,
    make_lane,
)

from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR, AGENT_PROMPT_FILES

GOOD_REPORT = {
    "outcome": "resolved",
    "summary": "## 发生了什么\nx\n\n## 调查结论\ny\n\n## 为什么需要你决策\nz\n"
               "\n## 处置时间线\n1\n\n## 证据回链\nref",
    "root_cause": "root",
    "scene_snapshot": "snap",
    "forensic_timeline": [{"at": "t0", "event": "trigger"}],
    "actions_taken": ["清理坏产物"],
    "evidence_refs": [".fenix/runs/arbiter-x.jsonl"],
    "status_after": "ready",
}
ESCALATE_REPORT = {
    "outcome": "escalate",
    "summary": GOOD_REPORT["summary"],
    "root_cause": "root",
    "scene_snapshot": "snap",
    "forensic_timeline": [],
    "actions_taken": [],
    "evidence_refs": ["ref"],
    "escalation_reason": "白名单外：产品缺陷终裁",
    "recommended_action": "请人类裁决场景集语义",
}


# ── 3.2 红线契约测试 ────────────────────────────────────

class TestRedLineContract:
    @staticmethod
    def _template() -> str:
        return (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["arbiter"]).read_text(
            encoding="utf-8")

    def test_five_red_lines_present(self):
        """永不可碰 5 类红线段：标题 + 关键禁令词目机械断言。"""
        tpl = self._template()
        assert "永不可碰 5 类" in tpl
        # 5 类红线逐一锚定
        assert "证据源只读" in tpl
        assert "禁伪造 run 产出形态文件" in tpl
        assert "禁 push" in tpl and "禁手工 merge" in tpl
        assert "禁绕过 flock 直写 STATE" in tpl
        assert "禁动进程管理面" in tpl
        # 红线段置顶（必须出现在许可清单之前）
        assert tpl.index("永不可碰 5 类") < tpl.index("许可清单")

    def test_six_permissions_present(self):
        """许可清单 6 类知情违规逐项存在。"""
        tpl = self._template()
        assert "许可清单" in tpl
        for item in (
            "显式 status 解冻",
            "端点四步语义直执行",
            "验证计数清零",
            "删除经鉴定无主坏产物",
            "复位重派",
            "主树 spec 目录在飞改动提交",
        ):
            assert item in tpl, f"许可清单缺项: {item}"

    def test_escalation_bias_section(self):
        """升级偏向段：假阴性无害、假阳性危险 + 白名单外只产裁决包。"""
        tpl = self._template()
        assert "升级偏向" in tpl
        assert "假阴性无害" in tpl and "假阳性危险" in tpl
        assert "MUST 只产裁决包" in tpl

    def test_five_class_whitelist_and_throttle(self):
        """五类白名单鉴定要点 + 立项节流三限段落存在。"""
        tpl = self._template()
        assert "首期自主处置白名单" in tpl
        for item in (
            "冻结场景文件拯救",
            "裁决落位/verdict 缺失考古",
            "验证侧计数冻结复位",
            "worktree 陈锁清扫",
            "WIP 门/在飞闸门分拣提交",
        ):
            assert item in tpl, f"白名单缺类: {item}"
        assert "立项节流三限" in tpl
        assert "同主题 drafted" in tpl
        assert "至多 2 条" in tpl
        assert "周配额" in tpl

    def test_report_contract_section(self):
        """调查报告五段格式与裁决包契约段存在（prompt 文件化纪律）。"""
        tpl = self._template()
        assert "调查报告契约" in tpl
        for key in ("outcome", "scene_snapshot", "forensic_timeline",
                    "root_cause", "cleanup_paths", "evidence_refs",
                    "status_after", "escalation_reason", "recommended_action",
                    "proposals"):
            assert f'"{key}"' in tpl, f"报告契约缺键: {key}"
        for section in ("发生了什么", "调查结论", "为什么需要你决策",
                        "处置时间线", "证据回链"):
            assert f"## {section}" in tpl, f"五段模板缺段: {section}"

    def test_placeholders_injected_no_residue(self, tmp_path):
        """构建 arbiter 提示词：契约段占位符全部注入，无残留。"""
        from core.agent_runner.prompt_builder import PromptBuilder

        pb = PromptBuilder.__new__(PromptBuilder)
        pb._pm = MagicMock()
        pb._pm.project_root = tmp_path
        detail = {
            "signal_type": "verify_env_blocked",
            "spec": "spec-a",
            "severity": "major",
            "description": "d",
            "evidence": "e",
            "recommended_action": "r",
            "run_id": "arbiter-spec-a-123",
        }
        prompt = pb._fill_placeholders(self._template(), "arbiter", "spec-a", detail)
        for token in ("{sig_type}", "{sig_spec}", "{severity}", "{description}",
                      "{evidence}", "{recommendation}", "{dash_script}",
                      "{run_id}", "{report_path}"):
            assert token not in prompt, f"残留占位符 {token}"
        assert "verify_env_blocked" in prompt
        assert str(arbiter_report_path(tmp_path, "arbiter-spec-a-123")) in prompt

    def test_injection_matches_framework_read_side(self, tmp_path):
        """注入 {report_path} 值 = 框架读侧路径（run_arbiter 硬门同源）。"""
        run_id = "arbiter-spec-a-456"
        assert str(arbiter_report_path(tmp_path, run_id)) == str(
            tmp_path / ".fenix" / f"arbiter_report-{run_id}.json")


# ── 6.2 护栏 ────────────────────────────────────────────

class TestRecurrenceEscalation:
    def test_recurrence_goes_straight_to_upgrade(self, tmp_path):
        """同签名处置后复发 → 直接升级，不再自主处置（design D6）。"""
        report = {**GOOD_REPORT}
        runner = FakeRunner(tmp_path, script={"run": report})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        runs_after_first = len(runner.run_agent_calls)
        out = lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert out == "recurrence-escalated"
        assert len(runner.run_agent_calls) == runs_after_first


class TestWhitelistOutNoTouch:
    def test_escalate_does_not_touch_state_or_cleanup(self, tmp_path):
        """白名单外（outcome=escalate）：只产裁决包，不擅动状态、不清理。"""
        runner = FakeRunner(tmp_path, script={"run": {**ESCALATE_REPORT,
                                                      "cleanup_paths": [
                                                          str(tmp_path / ".fenix" / "tmp" / "junk")]}})
        sm = FakeStateMachine({"spec-a": {"status": "blocked", "frozen": True}})
        (tmp_path / ".fenix" / "tmp").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".fenix" / "tmp" / "junk").write_text("x", encoding="utf-8")
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked")
        assert drain(lane)
        assert sm.unfreeze_calls == [], "升级路径 MUST NOT 解冻"
        kinds = [r["kind"] for r in load_arbiter_ledger(tmp_path)]
        assert "escalation" in kinds
        assert (tmp_path / ".fenix" / "tmp" / "junk").exists(), \
            "升级路径 MUST NOT 清理产物"

    def test_cleanup_whitelist_rejects_outside_paths(self, tmp_path):
        """cleanup_paths 白名单：越界/敏感路径一律拒绝删除。"""
        lane = make_lane(tmp_path)
        for evil in (
            str(tmp_path / "spec" / "changes" / "spec-a"),
            str(tmp_path / ".git"),
            str(tmp_path / ".fenix" / "STATE.md"),
            str(tmp_path),
            "/etc/passwd",
            "../outside",
        ):
            assert lane._safe_cleanup_path(evil) is None, f"越界路径被放行: {evil}"
        (tmp_path / ".fenix" / "tmp" / "ok").mkdir(parents=True, exist_ok=True)
        assert lane._safe_cleanup_path(str(tmp_path / ".fenix" / "tmp" / "ok")) \
            is not None


class TestZeroNoiseFinalization:
    def _append_alert(self, tmp_path, alert_id="alert-1", handled=False):
        store = AdminStore(tmp_path, None)
        rec = store.append({
            "kind": ESCALATION,
            "signal_type": "verify_env_blocked",
            "spec": "spec-a",
            "severity": "major",
            "description": "d",
            "handled": handled,
        })
        return rec["id"]

    def test_disposition_resolves_in_place_no_new_entry(self, tmp_path):
        """处置成功：原告警原位终态化 resolved_by=arbiter，不新增条目不进 pending。"""
        before = len(AdminStore(tmp_path, None).read_all())
        alert_id = self._append_alert(tmp_path)
        runner = FakeRunner(tmp_path, script={"run": {**GOOD_REPORT}})
        sm = FakeStateMachine({"spec-a": {"status": "blocked", "frozen": True}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked",
                    alert_id=alert_id)
        assert drain(lane)
        store = AdminStore(tmp_path, None)
        entries = store.read_all()
        assert len(entries) == before + 1, "MUST NOT 新增告警条目"
        rec = [e for e in entries if e["id"] == alert_id][0]
        assert rec["handled"] is True
        assert rec["resolved_by"] == "arbiter"
        assert rec["handled_by"] == "arbiter"
        assert not [e for e in entries
                    if e.get("kind") == ESCALATION and not e.get("handled")], \
            "处置成功 MUST NOT 推 pending"

    def test_escalation_upgrades_in_place_same_alert(self, tmp_path):
        """升级：同 alert_id 原位静默更新 + 推 pending + narrative 槽位裁决包。"""
        before = len(AdminStore(tmp_path, None).read_all())
        alert_id = self._append_alert(tmp_path, handled=True)
        runner = FakeRunner(tmp_path, script={"run": {**ESCALATE_REPORT}})
        lane = make_lane(tmp_path, runner=runner)
        lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked",
                    alert_id=alert_id)
        assert drain(lane)
        store = AdminStore(tmp_path, None)
        entries = store.read_all()
        assert len(entries) == before + 1, "升级 MUST NOT 新增告警条目"
        recs = [e for e in entries if e["id"] == alert_id]
        assert len(recs) == 1
        rec = recs[0]
        assert rec["handled"] is False, "升级 MUST 推回 pending 人工队列"
        assert rec["arbiter_upgrade"]["recommended_action"] == \
            ESCALATE_REPORT["recommended_action"]
        # 报告进 narrative 槽位（sidecar model=arbiter）
        sidecars = load_narrative_sidecars(tmp_path)
        assert alert_id in sidecars
        assert sidecars[alert_id].get("model") == "arbiter"
        assert "裁决包" in (sidecars[alert_id].get("text") or "")


class TestDisabledZeroIntrusion:
    def test_yield_gate_disabled_returns_false(self, tmp_path):
        """enabled=false：narrative 让位判定 False（narrative 行为不变）。"""
        from core.config import ConfigLoader

        set_lane(None)  # 单例未注入配置 → get_arbiter_config 缺省 True？否——
        # 让位判定读 ConfigLoader.resolve_config(project_root)，测试项目根无
        # 配置文件 → 缺省 enabled=True。此处构造真实关闭态：写项目级 config。
        cfg_dir = tmp_path / ".fenix"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.yaml").write_text(
            "arbiter:\n  enabled: false\n", encoding="utf-8")
        # 清掉可能被其它测试污染的单例（project_root 不同会重建）
        set_lane(None)
        assert narrative_yielded_to_arbiter(
            "verify_env_blocked",
            {"project_root": tmp_path, "logger": None},
        ) is False

    def test_yield_gate_enabled_blocked_signal_true(self, tmp_path):
        """enabled=true + 触发面内 signal → 让位 True。"""
        set_lane(None)
        assert narrative_yielded_to_arbiter(
            "verify_env_blocked",
            {"project_root": tmp_path, "logger": None},
        ) is True

    def test_yield_gate_excluded_signal_false(self, tmp_path):
        """enabled=true 但排除表 signal（token 预算/spec_integrity）→ False。"""
        set_lane(None)
        for sig in ("impl_budget_exhausted", "spec_content_missing",
                    "redispatch_loop_detected"):
            assert narrative_yielded_to_arbiter(
                sig, {"project_root": tmp_path, "logger": None}) is False

    def test_disabled_lane_no_writes_on_submit(self, tmp_path):
        """关闭态 submit：零派发、零台账、零侧车（s8 关闭态零侵扰）。"""
        lane = make_lane(tmp_path, config={"enabled": False})
        assert lane.submit_trigger(spec="spec-a", signal_type="verify_env_blocked",
                           alert_id="a-1") == "disabled"
        assert load_arbiter_ledger(tmp_path) == []
        assert load_narrative_sidecars(tmp_path) == {}


class TestLedgerCompleteness:
    def test_all_kinds_carry_five_segments(self, tmp_path):
        """各 kind 台账条目五段结构完整（处置/升级/死人开关）。"""
        for script, signal in (
            ({"run": {**GOOD_REPORT}}, "verify_env_blocked"),
            ({"run": {**ESCALATE_REPORT}}, "verify_env_blocked"),
            ({"run": "raise"}, "verify_env_blocked"),
            ({"run": "raise"}, "verify_env_blocked"),
        ):
            runner = FakeRunner(tmp_path, script=script)
            lane = make_lane(tmp_path, runner=runner)
            lane.submit_trigger(spec=f"s-{int(time.time()*1000)%100000}",
                        signal_type=signal)
            assert drain(lane)
        recs = load_arbiter_ledger(tmp_path)
        assert len(recs) >= 3
        from core.pm_engine.arbiter import ledger_entry_complete
        for rec in recs:
            assert ledger_entry_complete(rec), f"台账缺段 kind={rec.get('kind')}"


class TestLaneMetricsRow:
    def test_run_arbiter_logs_lane_metrics(self, tmp_path):
        """run_arbiter 终态写 _log_lane_run_metrics 富指标行（agent_type=arbiter）。"""
        rows = []

        class MetricsRunner(FakeRunner):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self._run_harness = {}

            def _log_run_metrics(self, *, run_id, spec_name, agent_type,
                                 duration_seconds, turns, usage_info, terminal,
                                 provider=None, model=None, latency=None,
                                 toolface=None):
                rows.append({
                    "run_id": run_id, "spec_name": spec_name,
                    "agent_type": agent_type,
                    "duration_seconds": duration_seconds, "turns": turns,
                    "usage_info": usage_info, "terminal": terminal,
                    "provider": provider, "model": model,
                })

        report = {**GOOD_REPORT, "status_after": "ready"}
        runner = MetricsRunner(tmp_path, script={"run": report})
        result = run_arbiter(runner, {"spec": "spec-a",
                                      "signal_type": "verify_env_blocked"})
        assert result["ok"] is True
        assert result["report"]["outcome"] == "resolved"
        assert len(rows) == 1
        row = rows[0]
        assert row["agent_type"] == "arbiter"
        assert row["terminal"] == "success"
        assert row["run_id"].startswith("arbiter-spec-a-")
        # 报告实例文件读取即清理（不留垃圾）
        assert not arbiter_report_path(
            tmp_path, row["run_id"]).exists()

    def test_run_arbiter_hard_gate_on_missing_report(self, tmp_path):
        """硬门：run 正常退出但未写报告 → fail-closed 判失败。"""
        runner = FakeRunner(tmp_path, script={"run": None})  # 不写文件
        result = run_arbiter(runner, {"spec": "spec-a",
                                      "signal_type": "verify_env_blocked"})
        assert result["ok"] is False
        assert "未写调查报告" in result["error"]

    def test_run_arbiter_hard_gate_on_bad_outcome(self, tmp_path):
        """硬门：outcome 非法 → fail-closed 判失败。"""
        runner = FakeRunner(tmp_path, script={"run": {"outcome": "done"}})
        result = run_arbiter(runner, {"spec": "spec-a",
                                      "signal_type": "verify_env_blocked"})
        assert result["ok"] is False
        assert "outcome 非法" in result["error"]

    def test_pinned_model_no_assignment(self, tmp_path):
        """无 model 分配 → 钉死 glm-5.3-flash。"""
        runner = FakeRunner(tmp_path, script={"run": {**GOOD_REPORT}})
        run_arbiter(runner, {"spec": "spec-a", "signal_type": "verify_env_blocked"})
        assert runner.observed_models == [ARBITER_PINNED_MODEL]


class TestProjectProposalThrottle:
    REPORT_TPL = {
        "summary": "s", "root_cause": "r", "scene_snapshot": "snap",
        "forensic_timeline": [], "actions_taken": ["a"],
        "evidence_refs": ["e"], "status_after": "ready",
    }

    def _resolved(self, proposals):
        return {"run": {**self.REPORT_TPL, "outcome": "resolved",
                        "proposals": proposals}}

    def test_draft_pool_dedup_and_status_drafted(self, tmp_path):
        """同主题 drafted 在池不重复立项；新提案落池 status=drafted。"""
        runner = FakeRunner(tmp_path)
        sm = FakeStateMachine({"existing-auth-retry": {
            "status": "drafted", "priority": 5}})
        lane = make_lane(tmp_path, runner=runner, sm=sm)
        lane._apply_proposals(
            {"spec": "spec-a", "signature": "sig", "run_id": "r1",
             "enqueued_at": "", "source": "t"},
            {"proposals": [
                {"topic": "auth retry 退避", "rationale": "同主题已在池"},
                {"topic": "completely-new-thing", "rationale": "新"},
            ]})
        # 主题 token "auth"/"retry" 命中在池名 existing-auth-retry → dedup
        added = [e for e in sm.entries if e.startswith("arb-")]
        assert added == ["arb-completely-new-thing"]
        assert sm.entries["arb-completely-new-thing"]["status"] == "drafted"
        kinds = [r["kind"] for r in load_arbiter_ledger(tmp_path)]
        assert "proposal-dedup" in kinds
        assert "spec-proposed" in kinds

    def test_max_two_per_run(self, tmp_path):
        """单次调查至多 2 条：第 3 条起只记台账。"""
        runner = FakeRunner(tmp_path)
        lane = make_lane(tmp_path, runner=runner)
        lane._apply_proposals(
            {"spec": "spec-a", "signature": "sig", "run_id": "r1",
             "enqueued_at": "", "source": "t"},
            {"proposals": [
                {"topic": "alpha-one", "rationale": "r"},
                {"topic": "beta-two", "rationale": "r"},
                {"topic": "gamma-three", "rationale": "r"},
                {"topic": "delta-four", "rationale": "r"},
            ]})
        kinds = [r["kind"] for r in load_arbiter_ledger(tmp_path)]
        assert kinds.count("spec-proposed") == PROPOSAL_MAX_PER_RUN
        assert "proposal-throttled" in kinds

    def test_weekly_quota_five(self, tmp_path):
        """周配额 5：超配额提案只记台账不落池。"""
        runner = FakeRunner(tmp_path)
        lane = make_lane(tmp_path, runner=runner)
        trigger = {"spec": "spec-a", "signature": "sig", "run_id": "r1",
                   "enqueued_at": "", "source": "t"}
        # 预置本周已 5 条 spec-proposed 台账（周窗口锚定取本周周一，
        # seed 用当前时间才落在真窗口内）
        from datetime import datetime, timezone

        from core.pm_engine.arbiter import arbiter_ledger_path

        ledger = arbiter_ledger_path(tmp_path)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(timezone.utc).isoformat()
        with ledger.open("a", encoding="utf-8") as f:
            for i in range(PROPOSAL_WEEKLY_QUOTA):
                f.write(json.dumps({
                    "id": f"seed-{i}", "created": now_iso,
                    "kind": "spec-proposed",
                }, ensure_ascii=False) + "\n")
        lane._apply_proposals(trigger, {"proposals": [
            {"topic": "quota-test-topic", "rationale": "r"}]})
        recs = load_arbiter_ledger(tmp_path)
        kinds = [r["kind"] for r in recs]
        assert "proposal-throttled" in kinds
        # 仅有预置的 5 条 spec-proposed（seed），超配额提案不落池
        assert kinds.count("spec-proposed") == PROPOSAL_WEEKLY_QUOTA
        assert not [r for r in recs
                    if r["kind"] == "spec-proposed"
                    and r["id"].startswith("arb-ledger-")], \
            "超配额提案 MUST NOT 落池（不新增 spec-proposed 台账）"


class TestNarrativeYieldIsolation:
    def test_non_blocked_family_signal_unaffected(self, tmp_path):
        """非阻塞类（排除表）信号：narrative 让位判定 False——既有路径不受扰。"""
        set_lane(None)
        for sig in sorted(ARBITER_EXCLUDED_SIGNAL_TYPES):
            assert narrative_yielded_to_arbiter(
                sig, {"project_root": tmp_path, "logger": None}) is False

    def test_yield_decision_is_side_effect_free(self, tmp_path):
        """让位判定零副作用：判定前后台账/侧车零变化。"""
        set_lane(None)
        before_ledger = load_arbiter_ledger(tmp_path)
        narrative_yielded_to_arbiter(
            "verify_env_blocked",
            {"project_root": tmp_path, "logger": None})
        assert load_arbiter_ledger(tmp_path) == before_ledger == []
        assert load_narrative_sidecars(tmp_path) == {}


class TestFrozenAlertPathIntegration:
    def test_family_throat_yields_and_dispatches(self, tmp_path):
        """1.2 集成面：_send_human_escalation_alert 改道经 lane.submit_for_alert
        （让位命中 → dispatched ∈ queued/deduped/recurrence-escalated）。"""
        from core.pm_engine.family import FamilyGovernor

        lane = make_lane(tmp_path)

        class FakePM:
            project_root = tmp_path
            logger = FakeLogger()

        captured = {}

        def fake_submit_for_alert(pm, entry, alert_id):
            captured["entry"] = entry
            captured["alert_id"] = alert_id
            return "queued"

        lane.submit_for_alert = fake_submit_for_alert
        set_lane(lane)
        governor = FamilyGovernor.__new__(FamilyGovernor)
        governor._pm = FakePM()
        import core.adjudication_narrative as adj_mod

        scheduled = []
        orig_sched = adj_mod.schedule_narrative
        adj_mod.schedule_narrative = lambda *a, **k: scheduled.append(a)
        try:
            governor._send_human_escalation_alert(
                "spec-a", "verify_env_blocked", "major", "d", "e", "r",
            )
        finally:
            adj_mod.schedule_narrative = orig_sched
            set_lane(None)
        assert captured.get("alert_id"), "告警咽喉必须携带 alert_id 派发"
        assert captured["entry"]["spec"] == "spec-a"
        assert scheduled == [], "让位命中时 narrative MUST 跳过（不双重补叙）"


class TestConfigRoundTrip:
    def test_config_admin_managed_keys(self):
        """四键入受管键集（config_admin._SOURCE_KEYS）。"""
        from core.dashboard.data.config_admin import _SOURCE_KEYS

        for key in ("arbiter.enabled", "arbiter.budget_wallclock_s",
                    "arbiter.budget_tokens", "arbiter.max_consecutive_failures"):
            assert key in _SOURCE_KEYS, f"缺受管键 {key}"

    def test_write_config_rejects_invalid(self, tmp_path):
        """非法值直接拒绝（D7：不静默落盘）。"""
        from core.dashboard.data.config_admin import write_config

        result = write_config(str(tmp_path), {"arbiter": {"enabled": "yes"}},
                              scope="project")
        assert result.get("ok") is not True

    def test_read_config_echoes_normalized(self, tmp_path):
        """读侧回显经 get_arbiter_config 归一（非法值回退缺省）。"""
        from core.dashboard.data.config_admin import read_config

        cfg_dir = tmp_path / ".fenix"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.yaml").write_text(
            "arbiter:\n  enabled: false\n  budget_wallclock_s: 0\n",
            encoding="utf-8")
        view = read_config(str(tmp_path), scope="project")
        arb = view.get("arbiter") or {}
        assert arb.get("enabled") is False
        assert arb.get("budget_wallclock_s") == 1800  # 0 非法回退缺省


class TestArbiterStatusEndpoint:
    def test_status_endpoint_route_registered(self):
        """路由注册：GET /api/arbiter/status 在派发表。"""
        from core.dashboard.routes import base as routes_base

        paths = [r[1] for r in routes_base._API_GET_ROUTES]
        assert "/api/arbiter/status" in paths

    def test_status_endpoint_handler(self, tmp_path):
        """handler 返回 config/lane/ledger 三段（自含 JSON）。"""
        from core.dashboard.routes.settings_routes import H5SettingsRoutesMixin

        mixin = H5SettingsRoutesMixin.__new__(H5SettingsRoutesMixin)
        sent = {}
        mixin._json = lambda payload: sent.update(payload=payload)
        mixin._project_or_user_scope = lambda query: (None, False)
        mixin._api_arbiter_status_get({})
        payload = sent.get("payload") or {}
        assert "config" in payload and "ledger" in payload
        assert payload["config"].get("enabled") is True  # 缺省开启
