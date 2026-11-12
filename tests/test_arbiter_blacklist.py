"""arbiter_blacklist 单元测试（add-arbiter-blacklist-disposition 1.2）。

覆盖 spec 需求 arbiter-blacklist-disposition：
  - 五禁项谓词正反例（consolidate-alerts 事故形态样本：位置点击 +
    ``POST /api/alerts/clear`` 批量清空守卫 = B1、裁决包 id 消费 = B2、
    删 ``_scenarios_full.json`` 无门 = B3、经证明器门场景成对写 = 放行、
    直写 STATE.md = B5）
  - B4 消费证明器判定的正反例
  - 叙述性字段不在扫描面（报告里提到事故 ≠ 执行动作）
  - ``enabled=false``（D9 降级态）谓词直通放行锚点 + prompt 回滚态文案
  - prompt 文案导出与谓词同源一致性（文案点名的端点/产物在谓词词表内、
    禁项段逐条同源渲染）
"""

import tempfile
from pathlib import Path

import pytest

from core.pm_engine import arbiter_blacklist as bl
from core.pm_engine.arbiter_blacklist import (
    BAN_ITEMS,
    b4_hit_from_prover,
    blacklist_enabled,
    render_ban_section,
    render_mode_sections,
    scan_report,
)


def _tmp_project() -> Path:
    return Path(tempfile.mkdtemp())


def _ban_ids(hits):
    return {h["ban_id"] for h in hits}


# ── 1. B1 生产账本副作用（事故形态：位置点击 + 批量清空端点）───────────

class TestB1LedgerSideEffects:
    def test_consolidate_alerts_accident_form_detected(self):
        # 事故实锤形态：机器人对生产账本执行批量清空端点
        rep = {"actions_taken": [
            "点击告警列表首行触发 POST /api/alerts/clear 清空全部告警",
        ]}
        hits = scan_report(rep)
        assert _ban_ids(hits) == {"B1"}
        assert hits[0]["surface"] == "actions_taken[0]"
        assert "alerts/clear" in hits[0]["detail"]

    def test_mark_all_handled_detected(self):
        rep = {"actions_taken": [
            "调用 mark_all_handled 端点把生产告警全部标记已处理",
        ]}
        assert _ban_ids(scan_report(rep)) == {"B1"}

    def test_seed_alert_state_write_endpoint_detected(self):
        # 记录级告警状态写端点（alerts/<id>/handled）同属生产账本副作用
        rep = {"actions_taken": [
            "请求 /api/alerts/provfix-77/handled 标记种子告警已处置",
        ]}
        assert _ban_ids(scan_report(rep)) == {"B1"}

    def test_ledger_file_status_write_detected(self):
        rep = {"actions_taken": [
            "覆写 admin_alerts.json 把 12 条生产告警置为 handled",
        ]}
        assert _ban_ids(scan_report(rep)) == {"B1"}

    def test_adjudication_choice_execute_detected(self):
        rep = {"actions_taken": [
            "POST /api/alerts/a-1/choices/c-2/execute 落实推荐项",
        ]}
        assert _ban_ids(scan_report(rep)) == {"B1"}

    def test_readonly_ledger_forensics_not_flagged(self):
        # 只读取证合法：账本文件名出现但无写动词
        rep = {"actions_taken": [
            "只读取证：解析 admin_alerts.json 统计未处理告警数",
        ]}
        assert scan_report(rep) == []

    def test_readonly_dashboard_query_not_flagged(self):
        rep = {"actions_taken": [
            "运行 dashboard 只读查询子命令核对告警生命周期状态",
        ]}
        assert scan_report(rep) == []


# ── 2. B2 人工裁决通道代行（事故形态：裁决包 id 消费）─────────────────

class TestB2HumanAdjudicationProxy:
    def test_choice_package_consumption_detected(self):
        rep = {"actions_taken": [
            "消费 choice-id=c-88 的裁决包并执行终审",
        ]}
        hits = scan_report(rep)
        assert _ban_ids(hits) == {"B2"}
        assert hits[0]["surface"] == "actions_taken[0]"

    def test_judge_rerun_cap_close_detected(self):
        rep = {"actions_taken": [
            "关闭 judge_rerun_cap 裁决包视同人工已确认",
        ]}
        assert _ban_ids(scan_report(rep)) == {"B2"}

    def test_impl_unattainable_confirm_detected(self):
        rep = {"actions_taken": [
            "对 impl_unattainable 申报执行确认代行拍板",
        ]}
        assert _ban_ids(scan_report(rep)) == {"B2"}

    def test_producing_package_only_not_flagged(self):
        # 只产裁决包交人工 = 正道，不命中
        rep = {"actions_taken": [
            "产出裁决包 recommendations 与候选方案交人工处置",
        ]}
        assert scan_report(rep) == []


# ── 3. B3 破坏性动作直执（经门成对写 = 唯一白名单例外）────────────────

class TestB3DestructiveDirectExecution:
    def test_ungated_scenario_file_delete_detected(self):
        rep = {"actions_taken": [
            "删除 _scenarios_full.json 中 3 条失败场景（无证明器门）",
        ]}
        hits = scan_report(rep)
        assert _ban_ids(hits) == {"B3"}
        assert hits[0]["surface"] == "actions_taken[0]"

    def test_run_transcript_overwrite_detected(self):
        rep = {"actions_taken": ["覆写 run 归档 .jsonl 抹掉失败轮次"]}
        assert _ban_ids(scan_report(rep)) == {"B3"}

    def test_verdict_file_delete_detected(self):
        rep = {"actions_taken": ["删除被拒 verdict 文件重跑验证"]}
        assert _ban_ids(scan_report(rep)) == {"B3"}

    def test_prover_gated_pair_write_passes(self):
        # 经证明器门获准（prover_verdict=pass）的场景成对写申报 = 放行
        rep = {
            "spec": "add-robu-fix",
            "actions_taken": [],
            "scenario_fixes": [{
                "file": "_scenarios_full.json + test_scenarios.json",
                "fix_class": "scenario-repaired",
                "summary": "经证明器门获准后成对覆盖写两份场景文件（同契约版本戳）",
                "justification": "选择器作用域化收紧，断言只紧不松",
                "prover_verdict": "pass",
            }],
        }
        assert scan_report(rep) == []

    def test_ungated_pair_write_declaration_still_scanned(self):
        # 同形态申报缺 prover_verdict（无门）→ 照常命中 B3
        rep = {
            "spec": "add-robu-fix",
            "scenario_fixes": [{
                "file": "_scenarios_full.json + test_scenarios.json",
                "fix_class": "scenario-repaired",
                "summary": "成对覆盖写两份场景文件",
            }],
        }
        assert _ban_ids(scan_report(rep)) == {"B3"}

    def test_gating_is_per_declaration(self):
        # 门按申报条目生效：门内申报放行、同报告其他无门破坏动作仍命中
        rep = {
            "spec": "add-robu-fix",
            "scenario_fixes": [{
                "file": "_scenarios_full.json",
                "summary": "成对覆盖写收紧断言",
                "prover_verdict": "pass",
            }],
            "actions_taken": ["顺带删除旧 run 归档 .jsonl"],
        }
        hits = scan_report(rep)
        assert _ban_ids(hits) == {"B3"}
        assert hits[0]["surface"].startswith("actions_taken")

    def test_cleanup_via_whitelist_channel_not_flagged(self):
        # 无主坏产物走 cleanup_paths 由框架白名单校验删除 = 申报面，不命中
        rep = {"actions_taken": [], "cleanup_paths": [
            ".fenix/tmp/orphan-artifact.bin",
        ]}
        assert scan_report(rep) == []


# ── 4. B4 验证契约放宽（消费证明器判定）───────────────────────────────

class TestB4ProverConsumption:
    def test_rejected_verdict_is_hit(self):
        hit = b4_hit_from_prover("净放宽判定：断言 exact→contains 期望弱化且无获准正当性码")
        assert hit is not None
        assert hit["ban_id"] == "B4"
        assert hit["surface"] == "scenario_fixes"

    def test_empty_verdict_is_none(self):
        assert b4_hit_from_prover("") is None
        assert b4_hit_from_prover(None) is None


# ── 5. B5 越界写（STATE.md / 主树源码 / 他 spec worktree）─────────────

class TestB5OutOfBoundsWrite:
    def test_state_md_direct_write_detected(self):
        rep = {"spec": "add-robu-fix", "actions_taken": [
            "直接覆写 .fenix/STATE.md 将 spec 置为 done",
        ]}
        hits = scan_report(rep)
        assert _ban_ids(hits) == {"B5"}
        assert "STATE.md 本体直写" in hits[0]["detail"]

    def test_main_source_tree_write_detected(self):
        rep = {"spec": "add-robu-fix", "actions_taken": [
            "顺手修改 core/pm_engine/arbiter.py 的判定阈值",
        ]}
        hits = scan_report(rep)
        assert _ban_ids(hits) == {"B5"}
        assert "主树源码树写面" in hits[0]["detail"]

    def test_other_spec_worktree_write_detected(self):
        rep = {"spec": "add-arbiter-blacklist-disposition", "actions_taken": [
            "进入 .claude/worktrees/impl-add-dashboard-tile 修改其进度文件",
        ]}
        hits = scan_report(rep)
        assert _ban_ids(hits) == {"B5"}
        assert "他 spec worktree 写面" in hits[0]["detail"]

    def test_own_spec_worktree_write_not_flagged(self):
        # 本 spec worktree 内写进度 = 合法作业面
        rep = {"spec": "add-robu-fix", "actions_taken": [
            "在 .claude/worktrees/impl-add-robu-fix-179 更新验证进度文件",
        ]}
        assert scan_report(rep) == []

    def test_readonly_state_md_not_flagged(self):
        rep = {"spec": "add-robu-fix", "actions_taken": [
            "只读读取 STATE.md 条目核对当前状态",
        ]}
        assert scan_report(rep) == []

    def test_source_tree_readonly_reference_not_flagged(self):
        rep = {"spec": "add-robu-fix", "actions_taken": [
            "只读取证 core/pm_engine 现状并在报告 gaps 上报修复方向",
        ]}
        assert scan_report(rep) == []


# ── 6. 叙述性字段不在扫描面 + fail-open 边界 ─────────────────────────

class TestSurfaceAndFailOpen:
    def test_narrative_fields_not_scanned(self):
        # summary / forensic_timeline 引用事故端点 ≠ 执行动作，不命中
        rep = {
            "outcome": "escalate",
            "summary": "复盘 consolidate-alerts 事故：机器人曾执行 POST /api/alerts/clear",
            "forensic_timeline": [
                {"at": "T+1", "event": "发现生产告警遭 mark_all_handled 清剿"},
            ],
            "root_cause": "场景守卫缺失导致位置点击误伤生产账本",
            "actions_taken": ["只读取证完成"],
        }
        assert scan_report(rep) == []

    def test_non_dict_report_returns_empty(self):
        assert scan_report(None) == []
        assert scan_report("not-a-dict") == []

    def test_malformed_surfaces_not_crash(self):
        rep = {"actions_taken": [123, None, {"step": "x"}],
               "scenario_fixes": "bad", "cleanup_paths": 42}
        assert isinstance(scan_report(rep), list)

    def test_empty_report_passes(self):
        assert scan_report({}) == []


# ── 7. enabled=false（D9 降级态）直通放行锚点 ─────────────────────────

class TestDisabledBypass:
    def _disable_via_monkeypatch(self, monkeypatch, root):
        from core.config import ConfigLoader

        monkeypatch.setattr(
            ConfigLoader, "resolve_config",
            classmethod(lambda cls, proot: {"arbiter_blacklist": {"enabled": False}}),
        )
        return root

    def test_blacklist_enabled_reads_config_false(self, monkeypatch):
        root = self._disable_via_monkeypatch(monkeypatch, _tmp_project())
        assert blacklist_enabled(root) is False

    def test_disabled_scan_passes_accident_forms(self, monkeypatch):
        # 降级态：全部禁项谓词直通放行（回滚路径行为与合入前一致）
        root = self._disable_via_monkeypatch(monkeypatch, _tmp_project())
        accident = {"actions_taken": [
            "POST /api/alerts/clear 清空告警",
            "删除 _scenarios_full.json",
            "覆写 .fenix/STATE.md",
        ]}
        assert scan_report(accident, project_root=root) == []

    def test_disabled_render_returns_legacy_sections(self, monkeypatch):
        root = self._disable_via_monkeypatch(monkeypatch, _tmp_project())
        sections = render_mode_sections(root)
        assert "升级偏向" in sections["mode_section"]
        assert "判定反例" in sections["mode_section"]
        assert "禁项判定" not in sections["mode_section"]
        assert sections["writable_surface_note"] == ""

    def test_project_config_yaml_integration(self, tmp_path):
        # 真实配置链：项目级 .fenix/config.yaml 覆盖默认值
        (tmp_path / ".fenix").mkdir()
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "arbiter_blacklist:\n  enabled: false\n", encoding="utf-8",
        )
        assert blacklist_enabled(tmp_path) is False
        accident = {"actions_taken": ["POST /api/alerts/clear 清空告警"]}
        assert scan_report(accident, project_root=tmp_path) == []

    def test_default_enabled_without_config(self, tmp_path):
        # 缺省开启：无配置的项目默认启用黑名单
        assert blacklist_enabled(tmp_path / "nonexistent-proj") is True

    def test_enabled_render_contains_blacklist_sections(self, tmp_path):
        sections = render_mode_sections(tmp_path / "nonexistent-proj")
        assert "处置哲学（黑名单制：默认可救）" in sections["mode_section"]
        assert "禁项判定" in sections["mode_section"]
        assert "救回工具箱" in sections["mode_section"]
        assert "证明器门" in sections["writable_surface_note"]


# ── 8. prompt 文案导出与谓词同源一致性 ────────────────────────────────

class TestPromptPredicateSameSource:
    def test_ban_items_enumerate_five(self):
        assert [b.ban_id for b in BAN_ITEMS] == ["B1", "B2", "B3", "B4", "B5"]

    def test_ban_section_renders_each_item(self):
        section = render_ban_section()
        for item in BAN_ITEMS:
            assert f"- **{item.ban_id} {item.title}**：" in section
            assert item.prompt_text in section

    def test_b1_prompt_endpoints_in_predicate_vocabulary(self):
        # 文案点名的端点形态必须在 B1 谓词词表内（同源，防双源漂移）
        b1 = bl.BAN_BY_ID["B1"].prompt_text
        assert "POST /api/alerts/clear" in b1
        assert "mark_all_handled" in b1
        assert bl._B1_ENDPOINT_RE.search(b1)
        assert bl._B1_ENDPOINT_RE.search("调用 mark_all_handled 接口")
        assert bl._B1_ENDPOINT_RE.search("POST /api/alerts/a-1/choices/c-2/execute")

    def test_b1_prompt_ledger_file_in_predicate_vocabulary(self):
        b1 = bl.BAN_BY_ID["B1"].prompt_text
        assert "admin_alerts.json" in b1
        assert bl._B1_LEDGER_FILE_RE.search(b1)

    def test_b2_prompt_adjudication_objects_in_predicate_vocabulary(self):
        b2 = bl.BAN_BY_ID["B2"].prompt_text
        assert "judge_rerun_cap" in b2
        assert "impl_unattainable" in b2
        assert bl._B2_ADJUDICATION_RE.search(b2)
        assert bl._B2_ADJUDICATION_RE.search("choice-id=c-9 的裁决包")

    def test_b3_prompt_artifacts_in_predicate_vocabulary(self):
        b3 = bl.BAN_BY_ID["B3"].prompt_text
        assert "_scenarios_full.json" in b3
        assert "test_scenarios.json" in b3
        assert bl._B3_ARTIFACT_RE.search(b3)

    def test_b5_prompt_state_file_in_predicate_vocabulary(self):
        b5 = bl.BAN_BY_ID["B5"].prompt_text
        assert "STATE.md" in b5
        assert bl._B5_STATE_RE.search(b5)

    def test_b3_prompt_names_gated_pair_write_exception(self):
        # 唯一例外与机械门口径一致：经证明器门的成对写 + 同契约版本戳
        b3 = bl.BAN_BY_ID["B3"].prompt_text
        assert "证明器门" in b3
        assert "cleanup_paths" in b3

    def test_mode_section_embeds_ban_section_verbatim(self, tmp_path):
        sections = render_mode_sections(tmp_path / "nonexistent-proj")
        assert render_ban_section() in sections["mode_section"]

    def test_mode_section_toolbox_declares_report_fields(self, tmp_path):
        # T1/T2 救回产出挂靠报告字段（scenario_fixes / rescue_evidence）
        sections = render_mode_sections(tmp_path / "nonexistent-proj")
        assert "T1" in sections["mode_section"]
        assert "T2" in sections["mode_section"]
        assert "scenario_fixes" in sections["mode_section"]
        assert "rescue_evidence" in sections["mode_section"]

    def test_b4_b5_have_no_text_predicate_false_asymmetry(self):
        # B4 由证明器判定承载（无文本谓词）；B5 文本谓词独立成套
        assert hasattr(bl, "_B5_STATE_RE") and hasattr(bl, "_B5_WORKTREE_RE")
        assert b4_hit_from_prover("拒绝")["surface"] == "scenario_fixes"


# ── 8. resolved 三级硬门与自动降级（5.1）────────────────────────────

class TestResolvedHardGate:
    """resolved 硬门三级判定 + 拒绝自动降级 escalate（全链经
    process_chain_handoff 驱动；密闭性：报告/台账/配置全落 tmp_path）。"""

    def _lane(self, tmp_path, report):
        from tests.test_arbiter_lane import FakeRunner, make_lane

        return make_lane(
            tmp_path, runner=FakeRunner(tmp_path, script={"run": report}))

    def _resolved_report(self, **kw):
        rep = {
            "outcome": "resolved",
            "spec": "spec-a",
            "signal_type": "verify_env_blocked",
            "summary": "## 发生了什么\n冻结误报，显式 status 解冻复位。",
            "actions_taken": ["显式 status 解冻 spec-a（经框架 unfreeze_spec 通道）"],
            "status_before": "frozen",
            "status_after": "ready",
        }
        rep.update(kw)
        return rep

    def _trigger(self):
        return {"signature": "sig-a", "spec": "spec-a",
                "signal_type": "verify_env_blocked"}

    def _ledger_kinds(self, tmp_path):
        from core.pm_engine.arbiter import load_arbiter_ledger

        return [str(r.get("kind") or "") for r in load_arbiter_ledger(tmp_path)]

    @pytest.fixture(autouse=True)
    def _lane_cleanup(self):
        yield
        from core.pm_engine.arbiter import reset_lane

        reset_lane()

    def test_clean_report_passes_gate(self, tmp_path):
        # 干净 resolved 报告：硬门三级全过 → disposition 台账（不降级）
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        lane = self._lane(tmp_path, self._resolved_report())
        assert lane.process_chain_handoff(self._trigger()) == "resolved"
        assert self._ledger_kinds(tmp_path) == ["disposition"]
        assert "sig-a" in lane._dispositioned

    def test_b1_hit_degrades_to_escalate(self, tmp_path):
        # ①禁项谓词命中（生产账本批量清空）→ 自动降级 escalate：裁决包
        # 原位挂靠方向（_chain_endpoint_*）+ escalation 台账留痕 + run 记
        # 合法终态不折算失败（failure_counts 不被触碰、不计处置账）。
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        lane = self._lane(tmp_path, self._resolved_report(actions_taken=[
            "POST /api/alerts/clear 清空生产告警账本",
        ]))
        trigger = self._trigger()
        assert lane.process_chain_handoff(trigger) == "escalated"
        assert self._ledger_kinds(tmp_path) == ["escalation"]
        reason = str(trigger.get("_chain_endpoint_reason") or "")
        assert "resolved 硬门拒绝自动降级" in reason
        assert "原 outcome=resolved" in reason
        assert "B1" in reason
        assert trigger.get("_chain_endpoint_kind") == "arbiter-escalated"
        assert "sig-a" not in lane._dispositioned
        assert lane._failure_counts == {}

    def test_b3_ungated_declaration_degrades(self, tmp_path):
        # ①B3 无门破坏动作申报（产物名+破坏动词跨字段联结）→ 拒绝
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        lane = self._lane(tmp_path, self._resolved_report(scenario_fixes=[{
            "file": "_scenarios_full.json 与 test_scenarios.json",
            "fix_class": "robustness-repair",
            "summary": "删除失败场景文件",
        }]))
        trigger = self._trigger()
        assert lane.process_chain_handoff(trigger) == "escalated"
        assert "B3" in str(trigger.get("_chain_endpoint_reason") or "")

    def test_prover_missing_verdict_degrades(self, tmp_path):
        # ②证明器复核：申报缺 prover_verdict → B4 拒绝（无门申报不摘除）
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        lane = self._lane(tmp_path, self._resolved_report(scenario_fixes=[{
            "file": "test_scenarios.json",
            "fix_class": "robustness-repair",
            "summary": "放宽断言等待窗口",
        }]))
        trigger = self._trigger()
        assert lane.process_chain_handoff(trigger) == "escalated"
        reason = str(trigger.get("_chain_endpoint_reason") or "")
        assert "证明器判定未获准" in reason and "B4" in reason

    def test_prover_pass_summary_allowed_and_b3_gate_same_source(self, tmp_path):
        # ②放行形态 + B3 门摘除同源锚点：to_summary 全文形态（非裸
        # "pass"）也判放行，且同一申报的破坏动词被 B3 门摘除（不误拒）
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        lane = self._lane(tmp_path, self._resolved_report(scenario_fixes=[{
            "file": "_scenarios_full.json 与 test_scenarios.json 成对写",
            "fix_class": "compliance-fix",
            "summary": "移除位置锚定点击步骤，改 testid 定位安全变体",
            "justification": "收紧：作用域从首行缩到 testid 命名空间",
            "prover_verdict": "证明器净判定：pass（3 条 diff，未获准放宽 0 条）",
        }]))
        assert lane.process_chain_handoff(self._trigger()) == "resolved"
        assert self._ledger_kinds(tmp_path) == ["disposition"]

    def test_no_evidence_degrades(self, tmp_path):
        # ③证据类校验：无申报/无探针/无 cleanup/无显式 status_after → 拒
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        lane = self._lane(tmp_path, self._resolved_report(status_after=""))
        trigger = self._trigger()
        assert lane.process_chain_handoff(trigger) == "escalated"
        assert "证据类校验失败" in str(trigger.get("_chain_endpoint_reason") or "")

    def test_probe_evidence_passes_gate(self, tmp_path):
        # ③稳态复跑探针证据在场 → 放行（T2 救回证据落 rescue_evidence）
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        lane = self._lane(tmp_path, self._resolved_report(rescue_evidence={
            "probe_transient": "稳态 checkout 只读复跑 3 次未复现（探针留痕）",
        }))
        assert lane.process_chain_handoff(self._trigger()) == "resolved"

    def test_disabled_direct_pass(self, tmp_path):
        # D9 降级态（enabled=false）硬门直通：B1 形态 resolved 也放行
        (tmp_path / ".fenix").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".fenix" / "config.yaml").write_text(
            "arbiter_blacklist:\n  enabled: false\n", encoding="utf-8")
        lane = self._lane(tmp_path, self._resolved_report(actions_taken=[
            "POST /api/alerts/clear 清空生产告警账本",
        ]))
        assert lane.process_chain_handoff(self._trigger()) == "resolved"
        assert self._ledger_kinds(tmp_path) == ["disposition"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
