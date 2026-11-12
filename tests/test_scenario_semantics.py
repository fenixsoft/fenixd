"""scenario_semantics 单元测试（add-arbiter-blacklist-disposition 2.2）。

双向锚定（tasks.md 2.2 字面清单）：
  - 选择器作用域化收紧放行；双汉字空格字面变体放行；选择器重写无码拒绝
  - 徽标 exact ``3``→regex ``\\d+`` 带正当性码放行；同改写无码拒绝
  - 场景删除拒绝（白名单码可机械豁免；未知码闭合拒绝）
  - 破坏性确认路径改安全变体（移除批量破坏点击+机械形态断言）carve-out
    中性放行；carve-out 前置条件反例（新增生产端点 / 移除非破坏步骤）拒绝
  - 收紧方向放行（contains→exact、regex 收窄）；扩大方向拒绝
  - 成对落盘契约锚点（先 `_scenarios_full.json` 后 `test_scenarios.json`、
    同契约版本戳，与 judge 受理门 judge-repair-scenario-writeback-gate 同构）
"""

import pytest

from core.verify_engine.scenario_semantics import (
    CONTRACT_VERSION_FIELD,
    CURRENT_CONTRACT_VERSION,
    JUSTIFICATION_CODE_ANCHORS,
    PAIR_WRITE_BACKUP_FILE,
    PAIR_WRITE_MAIN_FILE,
    PAIR_WRITE_ORDER,
    SCHEMA_VERSION,
    assert_pair_write_contract,
    prove_scenario_fix,
)
from core.verify_engine.scenarios import prepare_scenarios_for_write

GLOBAL_COUNTER = "global-counter-nondeterministic"


def _nav(url="http://127.0.0.1:6000/#/ops"):
    return {"action": "navigate", "value": url}


def _web(scenario_id, steps, assertions):
    return {"id": scenario_id, "kind": "web", "steps": steps,
            "assertions": assertions}


def _badge_old():
    return _web("web-badge", [_nav()], [
        {"type": "text_match", "expected": "3", "mode": "exact"},
    ])


def _badge_new(mode="regex", expected="\\d+", **extra):
    assertion = {"type": "text_match", "expected": expected, "mode": mode,
                 **extra}
    return _web("web-badge", [_nav()], [assertion])


# ── 1. 放行方向（合法救回修复）───────────────────────────────────────

class TestPassDirection:
    def test_selector_scoping_tighten_passes(self):
        old = _web("web-1", [_nav()], [
            {"type": "element_visible", "selector": 'button:has-text("确定")'},
        ])
        new = _web("web-1", [_nav()], [
            {"type": "element_visible",
             "selector": '.ant-modal button:has-text("确定")'},
        ])
        assert prove_scenario_fix([old], [new]).passed

    def test_double_han_space_variant_passes(self):
        # 骨架等价的引号字面变体 = 文案注记 neutral
        old = _web("web-1", [_nav()], [
            {"type": "element_visible", "selector": 'button:has-text("确定")'},
        ])
        new = _web("web-1", [_nav()], [
            {"type": "element_visible", "selector": 'button:has-text("保 存")'},
        ])
        assert prove_scenario_fix([old], [new]).passed

    def test_badge_exact_to_regex_with_code_passes(self):
        # 全局聚合量只断言形态（知识锚 global-counter-nondeterministic）
        just = [{"scenario_id": "web-badge", "code": GLOBAL_COUNTER}]
        v = prove_scenario_fix([_badge_old()], [_badge_new()], just)
        assert v.passed
        assert [e for e in v.entries
                if e["classification"] == "neutral"
                and "global-counter-nondeterministic" in e["note"]]

    def test_badge_exact_to_regex_inline_code_passes(self):
        # 内联 justification_code 双通道等价
        new = _badge_new(justification_code=GLOBAL_COUNTER)
        assert prove_scenario_fix([_badge_old()], [new]).passed

    def test_contains_to_exact_tighten_passes(self):
        old = _badge_old()
        old["assertions"][0]["mode"] = "contains"
        old["assertions"][0]["expected"] = "处理"
        new = _badge_new(mode="exact", expected="处理 3 条")
        assert prove_scenario_fix([old], [new]).passed

    def test_regex_narrowing_tighten_passes(self):
        old = _badge_new(expected="\\d+")
        new = _badge_new(expected="\\d{4}-\\d{2}")
        assert prove_scenario_fix([old], [new]).passed

    def test_wait_timing_and_port_rebind_neutral(self):
        old = _web("web-1", [_nav("http://127.0.0.1:39781/#/ops"),
                             {"action": "wait", "value": 2}], [])
        new = _web("web-1", [_nav("http://127.0.0.1:6000/#/ops"),
                             {"action": "wait", "value": 5}], [])
        assert prove_scenario_fix([old], [new]).passed

    def test_added_scenario_is_tighten(self):
        v = prove_scenario_fix([_badge_old()],
                               [_badge_old(),
                                _web("web-2", [_nav()], [])])
        assert v.passed
        assert any(e["note"] == "新增场景（覆盖面扩展）" for e in v.entries)


# ── 2. 拒绝方向（放宽未获准）─────────────────────────────────────────

class TestRejectDirection:
    def test_badge_exact_to_regex_without_code_rejects(self):
        v = prove_scenario_fix([_badge_old()], [_badge_new()])
        assert not v.passed
        assert v.reject_summary().startswith("证明器拒绝")
        assert v.to_summary().startswith("证明器净判定：reject")

    def test_pass_verdict_reject_summary_empty(self):
        v = prove_scenario_fix([_badge_old()], [_badge_old()])
        assert v.passed
        assert v.reject_summary() == ""

    def test_exact_to_contains_rejects(self):
        old = _badge_old()
        new = _badge_new(mode="contains", expected="3")
        assert not prove_scenario_fix([old], [new]).passed

    def test_regex_widening_rejects(self):
        old = _badge_new(expected="\\d{4}")
        new = _badge_new(expected="\\d+")
        assert not prove_scenario_fix([old], [new]).passed

    def test_scenario_deletion_rejects(self):
        other = _web("web-other", [_nav()], [])
        v = prove_scenario_fix([_badge_old(), other], [other])
        assert not v.passed
        assert any(e["scenario_id"] == "web-badge"
                   and "场景删除" in e["note"] for e in v.unjustified)

    def test_assertion_deletion_rejects(self):
        old = _badge_old()
        old["assertions"].append(
            {"type": "element_visible", "selector": ".ops-badge"},
        )
        new = _badge_old()
        assert not prove_scenario_fix([old], [new]).passed

    def test_selector_rewrite_without_containment_rejects(self):
        old = _web("web-1", [_nav()], [
            {"type": "element_visible", "selector": 'button:has-text("确定")'},
        ])
        new = _web("web-1", [_nav()], [
            {"type": "element_visible", "selector": '[data-testid="ok-btn"]'},
        ])
        assert not prove_scenario_fix([old], [new]).passed

    def test_unknown_code_closure_rejects(self):
        # 白名单闭合：白名单外码不豁免
        just = [{"scenario_id": "web-badge", "code": "my-invention"}]
        assert not prove_scenario_fix(
            [_badge_old()], [_badge_new()], just).passed

    def test_code_for_other_scenario_not_cover(self):
        just = [{"scenario_id": "web-other", "code": GLOBAL_COUNTER}]
        assert not prove_scenario_fix(
            [_badge_old()], [_badge_new()], just).passed

    def test_kind_redefinition_rejects(self):
        old = _badge_old()
        new = _badge_old()
        new["kind"] = "api"
        assert not prove_scenario_fix([old], [new]).passed

    def test_navigate_path_change_rejects(self):
        old = _web("web-1", [_nav("http://127.0.0.1:6000/#/ops")], [])
        new = _web("web-1", [_nav("http://127.0.0.1:6000/#/projects")], [])
        assert not prove_scenario_fix([old], [new]).passed


# ── 3. B1 合规化 carve-out（事故主形态）──────────────────────────────

def _destructive_old():
    # R3 形态：机器人点击批量清空确认键执行 mark_all_handled
    return _web("web-batch", [_nav("http://127.0.0.1:6000/#/ops")], [
        {"type": "element_visible", "selector": ".ops-badge"},
    ])


def _destructive_old_with_click(target='tbody tr:first-child button'):
    sc = _destructive_old()
    sc["steps"].append({
        "action": "click",
        "target": target,
        "expect_network": {"url_pattern": "/api/alerts/mark_all_handled"},
    })
    return sc


class TestB1ComplianceCarveOut:
    def test_batch_destructive_removal_to_safe_variant_passes(self):
        # 事故主形态：移除批量破坏确认点击 + 机械形态断言（danger 样式）
        new = _destructive_old()
        new["assertions"].append({
            "type": "element_visible",
            "selector": ".ant-modal-confirm .ant-btn-dangerous",
        })
        v = prove_scenario_fix([_destructive_old_with_click()], [new])
        assert v.passed
        assert any("B1 合规化 carve-out" in e["note"] for e in v.entries)

    def test_positional_click_removal_passes(self):
        # R1 形态：位置点击改状态步骤移除（teardown 侧合规化）
        new = _destructive_old()
        v = prove_scenario_fix([_destructive_old_with_click()], [new])
        assert v.passed

    def test_carve_out_blocked_by_new_production_endpoint(self):
        new = _destructive_old()
        new["steps"].append({
            "action": "http_request", "method": "POST",
            "url": "http://127.0.0.1:6000/api/alerts/x/handled",
        })
        v = prove_scenario_fix([_destructive_old_with_click()], [new])
        assert not v.passed

    def test_non_destructive_step_removal_rejects(self):
        # carve-out 只覆盖破坏性形态步骤移除；普通步骤移除照常 relax
        old = _destructive_old()
        old["steps"].append({
            "action": "click",
            "target": '.ant-modal button:has-text("确 定")',
            "expect_network": {"url_pattern": "/api/projects"},
        })
        v = prove_scenario_fix([old], [_destructive_old()])
        assert not v.passed

    def test_carve_out_blocked_by_unjustified_assertion_relax(self):
        new = _destructive_old()
        new["assertions"] = [
            {"type": "text_match", "expected": "\\d+", "mode": "regex"},
        ]
        v = prove_scenario_fix([_destructive_old_with_click()], [new])
        assert not v.passed


# ── 4. 成对落盘契约锚点（与 judge 受理门同构）─────────────────────────

class TestPairWriteContractAnchor:
    def test_pair_write_order_backup_first(self):
        assert PAIR_WRITE_ORDER == ("_scenarios_full.json",
                                    "test_scenarios.json")
        assert PAIR_WRITE_BACKUP_FILE == "_scenarios_full.json"
        assert PAIR_WRITE_MAIN_FILE == "test_scenarios.json"

    def test_prepare_stamps_both_versions(self):
        stamped = prepare_scenarios_for_write([_badge_old()])
        assert stamped[0]["schema_version"] == SCHEMA_VERSION
        assert stamped[0][CONTRACT_VERSION_FIELD] == CURRENT_CONTRACT_VERSION

    def test_consistent_pair_has_no_violations(self):
        stamped = prepare_scenarios_for_write([_badge_old()])
        assert assert_pair_write_contract(stamped, stamped) == []

    def test_torn_pair_detected(self):
        backup = prepare_scenarios_for_write([_badge_old()])
        main = prepare_scenarios_for_write([_badge_old()])
        main[0][CONTRACT_VERSION_FIELD] = CURRENT_CONTRACT_VERSION - 1
        violations = assert_pair_write_contract(backup, main)
        assert any("web-badge" in v and CONTRACT_VERSION_FIELD in v
                   for v in violations)

    def test_single_side_missing_detected(self):
        backup = prepare_scenarios_for_write([_badge_old()])
        violations = assert_pair_write_contract(backup, [])
        assert any("单侧缺失" in v for v in violations)

    def test_whitelist_anchored_to_knowledge_page(self):
        assert JUSTIFICATION_CODE_ANCHORS[GLOBAL_COUNTER] == (
            "spec/knowledge/domains/verify-pipeline/scenario-env-coupling.md"
        )

    def test_wrapper_dict_input_accepted(self):
        just = [{"scenario_id": "web-badge", "code": GLOBAL_COUNTER}]
        v = prove_scenario_fix({"scenarios": [_badge_old()]},
                               {"scenarios": [_badge_new()]}, just)
        assert v.passed


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
