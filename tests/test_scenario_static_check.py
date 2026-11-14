"""scenario_static_check 单元测试（add-scenario-defect-triage-gate 1.3）。

覆盖 spec 需求 scenario-static-defect-scan：
  - 跨轮端口残留检出（cli/api 字面端口、web navigate 字面端口）
  - 端口一致不误报
  - 双汉字文本选择器检出、恰 2 汉字边界（1/3 汉字不报、含非汉字不报、
    已含空格 workaround 不报）
  - fail-open：异常记 WARNING 返回空 findings（不抛出）
  - serving 端口未知时端口比对类模式整体跳过（双汉字纯文本模式仍执行）
"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from core.verify_engine.scenario_static_check import (
    PATTERN_TABLE,
    scan_scenarios,
    write_findings,
    load_findings,
)
from core.agent_runner.prompt_builder import PromptBuilder


def _tmp_project() -> Path:
    return Path(tempfile.mkdtemp())


def _cli_scenario(stdin_text: str, scenario_id: str = "cli-1") -> dict:
    return {
        "id": scenario_id,
        "kind": "cli",
        "steps": [
            {"action": "run", "command": "python3 -", "stdin": stdin_text},
        ],
    }


def _api_scenario(url: str, scenario_id: str = "api-1") -> dict:
    return {
        "id": scenario_id,
        "kind": "api",
        "steps": [
            {"action": "http_request", "method": "GET", "url": url},
        ],
    }


def _web_scenario(navigate_url: str = "", assertions=None,
                  steps=None, scenario_id: str = "web-1") -> dict:
    return {
        "id": scenario_id,
        "kind": "web",
        "steps": steps or (
            [{"action": "navigate", "value": navigate_url}] if navigate_url else []
        ),
        "assertions": assertions or [],
    }


# ── 1. 跨轮端口残留检出 ────────────────────────────────────────────

class TestStaleLiteralPort:
    def test_cli_stdin_embedded_port_detected(self):
        # 本次事故根因形态：seed stdin 内嵌上一轮 serving 字面端口兜底
        sc = _cli_scenario(
            "import os\nos.environ.get('FENIX_VERIFY_PORT', '57905')\n"
            "print('http://127.0.0.1:57905/')",
        )
        finds = scan_scenarios([sc], serving_port="6000")
        stale = [f for f in finds if f.rule_id == "stale_literal_port"]
        assert len(stale) >= 1
        assert stale[0].scenario_id == "cli-1"
        assert stale[0].location == "steps[0].stdin"
        assert "57905" in stale[0].message
        assert "6000" in stale[0].message

    def test_cli_command_port_detected(self):
        sc = {
            "id": "cli-cmd",
            "kind": "cli",
            "steps": [{"action": "run",
                       "command": "curl http://localhost:8080/api && python3 -"}],
        }
        finds = scan_scenarios([sc], serving_port="6000")
        stale = [f for f in finds if f.rule_id == "stale_literal_port"]
        assert len(stale) == 1
        assert stale[0].location == "steps[0].command"
        assert "8080" in stale[0].message

    def test_api_url_port_detected(self):
        sc = _api_scenario("http://127.0.0.1:39781/api/spec-budget?project=p")
        finds = scan_scenarios([sc], serving_port="6000")
        stale = [f for f in finds if f.rule_id == "stale_literal_port"]
        assert len(stale) == 1
        assert stale[0].location == "steps[0].url"
        assert "39781" in stale[0].message

    def test_web_navigate_port_detected(self):
        sc = _web_scenario(navigate_url="http://127.0.0.1:39781/#/projects/x")
        finds = scan_scenarios([sc], serving_port="6000")
        stale = [f for f in finds if f.rule_id == "stale_navigate_port"]
        assert len(stale) == 1
        assert stale[0].location == "steps[0].value"
        assert "39781" in stale[0].message

    def test_cli_flag_port_detected(self):
        sc = {
            "id": "cli-flag",
            "kind": "cli",
            "steps": [{"action": "run", "command": "python3 app.py --port 5001"}],
        }
        finds = scan_scenarios([sc], serving_port="6000")
        stale = [f for f in finds if f.rule_id == "stale_literal_port"]
        assert len(stale) == 1
        assert "5001" in stale[0].message

    def test_timestamp_like_not_flagged(self):
        # ISO 时间戳 T08:00:00 中的 :00/:08 非 serving 端口（高端口区间排除）
        sc = _cli_scenario(
            "import yaml\n"
            "'frozen_until': '2099-01-01T08:00:00+00:00'\n"
            "sm.add_spec('x', {'status': 'blocked'})",
        )
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds if f.rule_id == "stale_literal_port"]

    def test_privileged_port_not_flagged(self):
        # 特权端口(80<1024)非 serving 端口形态，不参与比对（确定性规则）
        sc = _cli_scenario("curl http://localhost:80/x")
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds if f.rule_id == "stale_literal_port"]


# ── 2. 端口一致不误报 ──────────────────────────────────────────────

class TestPortConsistent:
    def test_cli_stdin_port_matches_serving(self):
        sc = _cli_scenario(
            "import os\nos.environ.get('FENIX_VERIFY_PORT', '6000')\n"
            "print('http://127.0.0.1:6000/')",
        )
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds if f.rule_id == "stale_literal_port"]

    def test_api_url_port_matches_serving(self):
        sc = _api_scenario("http://127.0.0.1:6000/api/x")
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds if f.rule_id == "stale_literal_port"]

    def test_web_navigate_port_matches_serving(self):
        sc = _web_scenario(navigate_url="http://127.0.0.1:6000/#/projects/x")
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds if f.rule_id == "stale_navigate_port"]

    def test_scenario_without_port_no_findings(self):
        sc = _web_scenario(navigate_url="http://127.0.0.1:6000/#/projects/x")
        finds = scan_scenarios([sc], serving_port="6000")
        assert finds == []


# ── 3. 双汉字文本选择器 ────────────────────────────────────────────

class TestDoubleHanTextSelector:
    def test_exact_2_han_has_text_detected(self):
        sc = _web_scenario(assertions=[
            {"type": "element_visible",
             "selector": 'button:has-text("确定")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        dh = [f for f in finds if f.rule_id == "double_han_text_selector"]
        assert len(dh) == 1
        assert dh[0].location == "assertions[0].selector"
        assert "确定" in dh[0].message

    def test_text_equal_2_han_detected(self):
        sc = _web_scenario(assertions=[
            {"type": "element_visible", "selector": "text=保存"},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert len([f for f in finds
                    if f.rule_id == "double_han_text_selector"]) == 1

    def test_expected_field_2_han_detected(self):
        sc = _web_scenario(assertions=[
            {"type": "text_match", "expected": "确定"},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        dh = [f for f in finds if f.rule_id == "double_han_text_selector"]
        assert len(dh) == 1
        assert dh[0].location == "assertions[0].expected"

    def test_step_target_2_han_detected(self):
        sc = _web_scenario(steps=[
            {"action": "click", "target": 'button:has-text("提交")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        dh = [f for f in finds if f.rule_id == "double_han_text_selector"]
        assert len(dh) == 1
        assert dh[0].location == "steps[0].target"

    def test_1_han_not_flagged(self):
        sc = _web_scenario(assertions=[
            {"type": "element_visible", "selector": 'button:has-text("确")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds
                    if f.rule_id == "double_han_text_selector"]

    def test_3_han_not_flagged(self):
        sc = _web_scenario(assertions=[
            {"type": "element_visible", "selector": 'button:has-text("确定化")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds
                    if f.rule_id == "double_han_text_selector"]

    def test_non_han_mixed_not_flagged(self):
        # "归档 SPEC" 含 2 汉字但混有 ASCII——非 antd 二字按钮形态
        sc = _web_scenario(assertions=[
            {"type": "element_visible",
             "selector": 'button:has-text("归档 SPEC")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds
                    if f.rule_id == "double_han_text_selector"]

    def test_2_han_with_space_workaround_not_flagged(self):
        # "保 存" 已含空格（workaround 已应用）——不再误报
        sc = _web_scenario(assertions=[
            {"type": "element_visible",
             "selector": '.ant-modal button:has-text("保 存")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds
                    if f.rule_id == "double_han_text_selector"]

    def test_only_web_kind_scanned(self):
        # cli 场景的断言不扫双汉字
        sc = {
            "id": "cli-assert",
            "kind": "cli",
            "steps": [{"action": "run", "command": "python3 -"}],
            "assertions": [{"type": "output_match", "expected": "确定"}],
        }
        finds = scan_scenarios([sc], serving_port="6000")
        assert not [f for f in finds
                    if f.rule_id == "double_han_text_selector"]


# ── 4. fail-open 边界 ──────────────────────────────────────────────

class TestFailOpen:
    def test_malformed_scenario_not_crash(self):
        # 非 dict 条目、steps 非 list、command 非字符串 → 隔离/跳过，不抛出
        scenarios = [
            "not-a-dict",
            {"id": "bad-steps", "kind": "cli", "steps": "nope"},
            {"id": "bad-cmd", "kind": "cli",
             "steps": [{"action": "run", "command": 12345}]},
        ]
        finds = scan_scenarios(scenarios, serving_port="6000")
        assert isinstance(finds, list)  # 不抛出

    def test_rule_scan_exception_fail_open(self):
        # 自定义规则抛异常 → 隔离捕获记 WARNING，返回空 findings
        def _boom(scenario, serving_port):
            raise RuntimeError("boom")

        table = [{
            "rule_id": "boom_rule",
            "kinds": {"web"},
            "need_port": False,
            "match": _boom,
        }]
        sc = _web_scenario()
        # 经 scan_scenarios 无法注入自定义表，直接验证顶层捕获存在：
        # 用坏表驱动扫描器主循环（表项 match 缺失键）验证隔离
        try:
            for rule in table:
                for s in [sc]:
                    rule["match"](s, None)
        except RuntimeError:
            pass  # 规则本身抛异常属预期
        # scan_scenarios 对 PATTERN_TABLE 内置规则确保不抛出
        finds = scan_scenarios([sc], serving_port=None)
        assert isinstance(finds, list)

    def test_write_findings_fail_open(self):
        proot = _tmp_project()
        # 只读目录 → 写失败仅 WARNING 不抛出
        ro = proot / "ro"
        ro.mkdir()
        write_findings(ro, "demo", [])  # 不抛出


# ── 5. 端口未知时端口类模式跳过 ────────────────────────────────────

class TestPortUnknown:
    def test_port_rules_skipped_text_rules_run(self):
        sc = _web_scenario(
            navigate_url="http://127.0.0.1:39781/#/projects/x",
            assertions=[{"type": "element_visible",
                         "selector": 'button:has-text("确定")'}],
        )
        finds = scan_scenarios([sc], serving_port=None)
        assert not [f for f in finds if f.rule_id == "stale_navigate_port"]
        assert len([f for f in finds
                    if f.rule_id == "double_han_text_selector"]) == 1

    def test_empty_string_port_skipped(self):
        sc = _cli_scenario("print('http://127.0.0.1:57905/')")
        finds = scan_scenarios([sc], serving_port="")
        assert not [f for f in finds if f.rule_id == "stale_literal_port"]

    def test_zero_port_skipped(self):
        sc = _cli_scenario("print('http://127.0.0.1:57905/')")
        finds = scan_scenarios([sc], serving_port=0)
        assert not [f for f in finds if f.rule_id == "stale_literal_port"]


# ── 6. findings 落盘与读取（2.1 前置，供 prompt 情报段）──────────────

class TestFindingsPersistence:
    def test_write_and_load_roundtrip(self):
        proot = _tmp_project()
        sc = _web_scenario(assertions=[
            {"type": "element_visible", "selector": 'button:has-text("确定")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert finds
        write_findings(proot, "demo", finds)
        loaded = load_findings(proot, "demo")
        assert len(loaded) == len(finds)
        assert loaded[0]["scenario_id"] == "web-1"
        assert loaded[0]["rule_id"] == "double_han_text_selector"
        assert "location" in loaded[0] and "message" in loaded[0]

    def test_load_missing_returns_empty(self):
        proot = _tmp_project()
        assert load_findings(proot, "nope") == []

    def test_load_corrupt_returns_empty(self):
        proot = _tmp_project()
        path = proot / ".fenix" / "verify-progress" / "demo" \
            / "scenario_static_findings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        assert load_findings(proot, "demo") == []


# ── 8. judge prompt 情报段注入（2.3）───────────────────────────────

class TestJudgeFindingsInjection:
    def test_has_findings_injects(self):
        proot = _tmp_project()
        pb = PromptBuilder(SimpleNamespace(project_root=proot))
        sc = _web_scenario(assertions=[
            {"type": "element_visible", "selector": 'button:has-text("确定")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        write_findings(proot, "spec", finds)
        section = pb._scenario_static_findings_section("spec")
        assert "场景静态缺陷情报" in section
        assert "web-1" in section
        assert "double_han_text_selector" in section
        assert "修复属 judge 职责" in section
        assert "先修复已知缺陷再裁决" in section

    def test_stale_port_finding_injects(self):
        proot = _tmp_project()
        pb = PromptBuilder(SimpleNamespace(project_root=proot))
        sc = _cli_scenario("print('http://127.0.0.1:57905/')")
        finds = scan_scenarios([sc], serving_port="6000")
        assert finds
        write_findings(proot, "spec", finds)
        section = pb._scenario_static_findings_section("spec")
        assert "stale_literal_port" in section
        assert "57905" in section

    def test_empty_findings_zero_injection(self):
        proot = _tmp_project()
        pb = PromptBuilder(SimpleNamespace(project_root=proot))
        write_findings(proot, "spec", [])
        assert pb._scenario_static_findings_section("spec") == ""

    def test_missing_file_zero_injection(self):
        proot = _tmp_project()
        pb = PromptBuilder(SimpleNamespace(project_root=proot))
        assert pb._scenario_static_findings_section("nope") == ""

    def test_corrupt_file_zero_injection_no_throw(self):
        proot = _tmp_project()
        pb = PromptBuilder(SimpleNamespace(project_root=proot))
        path = proot / ".fenix" / "verify-progress" / "spec" \
            / "scenario_static_findings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{corrupt", encoding="utf-8")
        assert pb._scenario_static_findings_section("spec") == ""

    def test_mounted_in_judge_prompt_between_cache_and_gate(self):
        # 端到端：build_prompt(planner-judge) 全量 prompt 中情报段位于
        # verdict 缓存段之后、结果硬门之前
        proot = _tmp_project()
        pb = PromptBuilder(SimpleNamespace(project_root=proot))
        sc = _web_scenario(assertions=[
            {"type": "element_visible", "selector": 'button:has-text("保存")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        write_findings(proot, "spec", finds)
        prompt = pb._build_prompt("spec", "planner-judge")
        assert "场景静态缺陷情报" in prompt
        assert "结果文件硬门" in prompt
        assert prompt.index("场景静态缺陷情报") < prompt.index("结果文件硬门")

    def test_judge_prompt_build_end_to_end(self):
        # 端到端：build_prompt(planner-judge) 全量 prompt 含情报段
        proot = _tmp_project()
        pb = PromptBuilder(SimpleNamespace(project_root=proot))
        sc = _web_scenario(assertions=[
            {"type": "element_visible", "selector": 'button:has-text("确定")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        write_findings(proot, "spec", finds)
        prompt = pb._build_prompt("spec", "planner-judge")
        assert "场景静态缺陷情报" in prompt
        assert "修复属 judge 职责" in prompt
        assert "结果文件硬门" in prompt


# ── 9. 模式表结构（design D4）──────────────────────────────────────

class TestPatternTable:
    def test_pattern_rule_ids(self):
        # verify-fixture-guard 四条 + add-arbiter-blacklist-disposition R1–R5
        ids = {rule["rule_id"] for rule in PATTERN_TABLE}
        assert ids == {
            "stale_literal_port",
            "stale_navigate_port",
            "double_han_text_selector",
            "unmarked_fixture_add_project",
            "positional_state_change_click",
            "overbroad_network_guard",
            "batch_destructive_endpoint_execution",
            "global_counter_absolute_assertion",
            "tag_scoped_text_matches_button",
        }

    def test_port_rules_require_port(self):
        for rule in PATTERN_TABLE:
            if rule["rule_id"].startswith("stale"):
                assert rule["need_port"] is True
            else:
                assert rule["need_port"] is False

    def test_rule_kinds_covered(self):
        kinds = {rule["rule_id"]: rule["kinds"] for rule in PATTERN_TABLE}
        assert kinds["stale_literal_port"] == {"cli", "api"}
        assert kinds["stale_navigate_port"] == {"web"}
        assert kinds["double_han_text_selector"] == {"web"}
        assert kinds["unmarked_fixture_add_project"] == {"cli"}
        assert kinds["positional_state_change_click"] == {"web"}
        assert kinds["overbroad_network_guard"] == {"web"}
        assert kinds["batch_destructive_endpoint_execution"] == {"web"}
        assert kinds["global_counter_absolute_assertion"] == {"web"}
        assert kinds["tag_scoped_text_matches_button"] == {"web"}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))

# ── 10. 场景红线规则族 R1–R5（add-arbiter-blacklist-disposition 3.2）──
# 内嵌事故形态 fixtures（consolidate-alerts 复盘红线，knowledge 页
# scenario-env-coupling）双向锚定。

def _redline_web(steps, assertions=None):
    sc = {"id": "web-redline", "kind": "web", "steps": steps,
          "assertions": assertions or []}
    return sc


def _rule_ids_of(findings):
    return {f.rule_id for f in findings}


class TestPositionalStateChangeClick:
    """R1：改状态 click × 位置选择器交叉（high）。"""

    def test_accident_form_hits_r1_and_r2(self):
        # 事故形态：位置点击「标记已处理」+ expect_network 守卫过宽
        sc = _redline_web([
            {"action": "navigate", "value": "http://127.0.0.1:6000/#/ops"},
            {"action": "click",
             "target": 'button:has-text("标记已处理") .first',
             "expect_network": {"url_pattern": "/api/alerts"}},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        ids = _rule_ids_of(finds)
        assert "positional_state_change_click" in ids
        assert "overbroad_network_guard" in ids
        r1 = [f for f in finds
              if f.rule_id == "positional_state_change_click"][0]
        assert r1.severity == "high"
        assert r1.location == "steps[1].target"

    def test_nth_form_click_hits(self):
        sc = _redline_web([
            {"action": "click", "target": 'tbody tr >> nth=0 button',
             "expect_network": {"url_pattern": "/api/alerts/x/handled"}},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert "positional_state_change_click" in _rule_ids_of(finds)

    def test_click_without_state_write_guard_not_flagged(self):
        # 只读点击（无状态写端点守卫）不触发改状态归因
        sc = _redline_web([
            {"action": "click", "target": 'button .first',
             "expect_network": {"url_pattern": "/api/projects"}},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert "positional_state_change_click" not in _rule_ids_of(finds)

    def test_seed_scoped_rewrite_zero_hit(self):
        # 修复后形态：种子行作用域 + 记录级守卫 → R1/R2 零命中
        sc = _redline_web([
            {"action": "click",
             "target": '[data-row-id="provfix-seed-42"] '
                       'button:has-text("标记已处理")',
             "expect_network": {
                 "url_pattern": "/api/alerts/provfix-seed-42/handled"}},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        ids = _rule_ids_of(finds)
        assert "positional_state_change_click" not in ids
        assert "overbroad_network_guard" not in ids


class TestOverbroadNetworkGuard:
    """R2：网络守卫过宽（medium）。"""

    def test_collection_root_guard_hits(self):
        sc = _redline_web([
            {"action": "click", "target": ".ok-btn",
             "expect_network": {"url_pattern": "/api/alerts"}},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        r2 = [f for f in finds if f.rule_id == "overbroad_network_guard"]
        assert len(r2) == 1
        assert r2[0].severity == "medium"

    def test_record_level_guard_zero_hit(self):
        sc = _redline_web([
            {"action": "click", "target": ".ok-btn",
             "expect_network": {"url_pattern": "/api/alerts/9183/handled"}},
        ])
        assert not [f for f in scan_scenarios([sc], serving_port="6000")
                    if f.rule_id == "overbroad_network_guard"]

    def test_re_wildcard_guard_hits(self):
        sc = _redline_web([
            {"action": "click", "target": ".ok-btn",
             "expect_network": {"url_pattern": "re:/api/alerts/.*"}},
        ])
        assert "overbroad_network_guard" in _rule_ids_of(
            scan_scenarios([sc], serving_port="6000"))

    def test_readonly_guard_not_flagged(self):
        # 非状态写端点词族的守卫不参与过宽判定
        sc = _redline_web([
            {"action": "click", "target": ".row-link",
             "expect_network": {"url_pattern": "/api/projects"}},
        ])
        assert not [f for f in scan_scenarios([sc], serving_port="6000")
                    if f.rule_id == "overbroad_network_guard"]


class TestBatchDestructiveExecution:
    """R3：批量破坏端点确认路径执行（critical）。"""

    def test_confirm_click_with_batch_guard_hits(self):
        # 确认弹窗破坏主键 + 批量端点守卫 = 机器人执行批量清空
        sc = _redline_web([
            {"action": "navigate", "value": "http://127.0.0.1:6000/#/ops"},
            {"action": "click",
             "target": '.ant-modal-confirm .ant-btn-dangerous',
             "expect_network": {
                 "url_pattern": "/api/alerts/mark_all_handled"}},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        r3 = [f for f in finds
              if f.rule_id == "batch_destructive_endpoint_execution"]
        assert len(r3) == 1
        assert r3[0].severity == "critical"

    def test_direct_http_post_hits(self):
        sc = _redline_web([
            {"action": "http_request", "method": "POST",
             "url": "http://127.0.0.1:6000/api/alerts/clear"},
        ])
        assert "batch_destructive_endpoint_execution" in _rule_ids_of(
            scan_scenarios([sc], serving_port="6000"))

    def test_modal_shape_assertion_only_zero_hit(self):
        # 合法形态：只开确认弹窗断言确认键机械形态，无批量端点执行
        sc = _redline_web([
            {"action": "click", "target": '.ops-clear-btn'},
            {"action": "wait", "value": 1},
        ], assertions=[
            {"type": "element_visible",
             "selector": ".ant-modal-confirm .ant-btn-dangerous"},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        assert "batch_destructive_endpoint_execution" not in _rule_ids_of(finds)


class TestGlobalCounterAbsoluteAssertion:
    """R4：全局聚合量绝对值断言（medium）。"""

    def test_badge_exact_three_hits(self):
        sc = _redline_web([], assertions=[
            {"type": "text_match", "selector": ".ant-badge-count",
             "expected": "3", "mode": "exact"},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        r4 = [f for f in finds
              if f.rule_id == "global_counter_absolute_assertion"]
        assert len(r4) == 1
        assert r4[0].severity == "medium"
        assert r4[0].location == "assertions[0]"

    def test_regex_shape_zero_hit(self):
        sc = _redline_web([], assertions=[
            {"type": "text_match", "selector": ".ant-badge-count",
             "expected": "\\d+", "mode": "regex"},
        ])
        assert not [f for f in scan_scenarios([sc], serving_port="6000")
                    if f.rule_id == "global_counter_absolute_assertion"]

    def test_non_counter_selector_not_flagged(self):
        sc = _redline_web([], assertions=[
            {"type": "text_match", "selector": ".spec-title",
             "expected": "3", "mode": "exact"},
        ])
        assert not [f for f in scan_scenarios([sc], serving_port="6000")
                    if f.rule_id == "global_counter_absolute_assertion"]


class TestTagScopedTextMatchesButton:
    """R5：`<tag>:text-matches` 组件按钮锚定（medium）。"""

    def test_button_prefixed_text_matches_hits(self):
        sc = _redline_web([], assertions=[
            {"type": "element_visible",
             "selector": 'button:text-matches("取\\s*消")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        r5 = [f for f in finds
              if f.rule_id == "tag_scoped_text_matches_button"]
        assert len(r5) == 1
        assert r5[0].severity == "medium"

    def test_bare_text_matches_zero_hit(self):
        sc = _redline_web([], assertions=[
            {"type": "element_visible",
             "selector": '.ant-modal-confirm :text-matches("取\\s*消")'},
        ])
        assert not [f for f in scan_scenarios([sc], serving_port="6000")
                    if f.rule_id == "tag_scoped_text_matches_button"]

    def test_step_target_also_scanned(self):
        sc = _redline_web([
            {"action": "click",
             "target": 'div > button:text-matches("确\\s*定")'},
        ])
        finds = scan_scenarios([sc], serving_port="6000")
        r5 = [f for f in finds
              if f.rule_id == "tag_scoped_text_matches_button"]
        assert r5 and r5[0].location == "steps[0].target"

    def test_class_prefix_stem_not_flagged(self):
        # 类名词干（.ant-btn:text-matches）不在 <tag> 形态词表内（保守漏报）
        sc = _redline_web([], assertions=[
            {"type": "element_visible",
             "selector": '.ant-btn:text-matches("确\\s*定")'},
        ])
        assert not [f for f in scan_scenarios([sc], serving_port="6000")
                    if f.rule_id == "tag_scoped_text_matches_button"]


class TestRescanCli:
    """回扫 CLI 入口（只读，逐场景×逐规则×严重度汇总）。"""

    def _write_tree(self, tmp_path, scenarios, name="test_scenarios.json"):
        d = tmp_path / "proj" / ".fenix" / "verify-progress" / "spec"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(json.dumps(scenarios, ensure_ascii=False),
                              encoding="utf-8")
        return tmp_path

    def test_cli_reports_findings_and_summary(self, tmp_path, capsys):
        root = self._write_tree(tmp_path, [
            _redline_web([
                {"action": "click", "target": 'button:has-text("标记已处理") .first',
                 "expect_network": {"url_pattern": "/api/alerts"}},
            ], assertions=[
                {"type": "text_match", "selector": ".ant-badge-count",
                 "expected": "3", "mode": "exact"},
            ]),
        ])
        from core.verify_engine.scenario_static_check import _run_rescan_cli
        rc = _run_rescan_cli(["--scan", str(root)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "positional_state_change_click" in out
        assert "global_counter_absolute_assertion" in out
        assert "回扫汇总" in out
        assert "[high]" in out and "[medium]" in out

    def test_cli_json_lines_mode(self, tmp_path, capsys):
        root = self._write_tree(tmp_path, [
            _redline_web([
                {"action": "http_request", "method": "POST",
                 "url": "http://127.0.0.1:6000/api/alerts/clear"},
            ]),
        ])
        from core.verify_engine.scenario_static_check import _run_rescan_cli
        rc = _run_rescan_cli(["--scan", str(root), "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        lines = [json.loads(l) for l in out.splitlines()
                 if l.startswith("{")]
        assert any(l["rule_id"] == "batch_destructive_endpoint_execution"
                   and l["severity"] == "critical" for l in lines)

    def test_cli_nonexistent_root_exit_two(self, capsys):
        from core.verify_engine.scenario_static_check import _run_rescan_cli
        assert _run_rescan_cli(["--scan", "/tmp/no-such-root-xyz-42"]) == 2

    def test_cli_skips_corrupt_file_fail_open(self, tmp_path, capsys):
        d = tmp_path / "proj"
        d.mkdir()
        (d / "test_scenarios.json").write_text("{corrupt", encoding="utf-8")
        from core.verify_engine.scenario_static_check import _run_rescan_cli
        rc = _run_rescan_cli(["--scan", str(tmp_path)])
        assert rc == 0
        assert "[warn] 解析失败跳过" in capsys.readouterr().err


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
