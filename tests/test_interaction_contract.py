"""add-interaction-contract-and-per-assert-triage 单元测试（任务 1.x / 2.x / 3.x / 4.x）。

覆盖：
  1. 契约校验器（core/interaction_contract.py）：可交互候选识别（v2-overview-page
     卡片形态）、覆盖缺失被拦、纯展示声明放行（SPEC 标注 + planner declared_display）、
     covers 元数据登记进 scenarios.json。
  2. 裁决逐断言归因（core/verdict_check.py）：failed 场景缺 assertion_triage 不合规、
     单断言 product-bug 阻止场景豁免（强制 failed）、全断言非产品缺陷可豁免。
  3. 报告断言级豁免清单（core/verify_report.py）：逐条渲染、旧报告缺省。
  4. 真实夹具回归（任务 4.2）：v2-overview-page 真实报告（12 场景 6 豁免）作夹具，
     豁免清单应逐条列出被豁免断言。
  5. prompt 契约条款注入（任务 1.2 / 2.1 / 3.1）。
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _write_spec_doc(proot: Path, spec: str, rel: str, text: str) -> Path:
    p = proot / "spec" / "changes" / spec / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ───────────────── 1. 契约校验器：候选识别（任务 4.1） ─────────────────


class TestCandidateExtraction(unittest.TestCase):
    """可交互候选识别：首版声明式模式（design D1）。"""

    def test_v2_overview_card_link_class_form(self):
        """v2-overview-page 卡片形态：链接样式卡片 token 被识别为候选。"""
        from core.interaction_contract import extract_candidates
        text = (
            "## Requirement: 项目卡片\n\n"
            "项目卡片渲染为链接样式（dark-Card--link），点击卡片跳转项目详情页。\n"
        )
        cands = extract_candidates(text, source="spec.md")
        keys = [c.key for c in cands]
        self.assertIn("card-link", keys)
        cand = next(c for c in cands if c.key == "card-link")
        self.assertEqual(cand.raw, "dark-Card--link")
        self.assertEqual(cand.source, "spec.md")
        self.assertEqual(cand.line, 3)

    def test_button_group_and_href_field_patterns(self):
        """首版模式：button-group / button / href 字段。"""
        from core.interaction_contract import extract_candidates
        text = (
            "- 顶部渲染 button-group 操作区\n"
            "- 提交按钮 id=submit-btn\n"
            '- 卡片定义含 "href": "/detail" 字段\n'
        )
        keys = [c.key for c in extract_candidates(text)]
        self.assertIn("button-group", keys)
        self.assertIn("submit-btn", keys)
        self.assertIn("href", keys)

    def test_cards_loop_pattern_and_plural(self):
        """首版模式：cards 渲染循环与复数形式。"""
        from core.interaction_contract import extract_candidates
        text = "页面循环渲染项目 cards（启动/停止/删除按钮）\n"
        keys = [c.key for c in extract_candidates(text)]
        self.assertIn("cards", keys)
        # 复数裸关键词（v2-overview-page proposal 的实际写法）
        keys2 = [c.key for c in extract_candidates("统计卡 grid + 项目 cards\n")]
        self.assertIn("cards", keys2)

    def test_display_declaration_inline_detected(self):
        """元素定义处的「纯展示」声明被登记（declared_display=True）。"""
        from core.interaction_contract import extract_candidates
        text = "- 状态按钮 status-btn（纯展示、不可交互，仅展示状态文本）\n"
        cands = extract_candidates(text)
        hit = [c for c in cands if c.key == "status-btn"]
        self.assertEqual(len(hit), 1)
        self.assertTrue(hit[0].declared_display)

    def test_real_v2_overview_page_spec_yields_candidates(self):
        """真实夹具（任务 4.1）：v2-overview-page SPEC 文档可检出卡片候选。

        原始 spec 已归档（spec/archive/2026-09-05-v2-overview-page）：归档移动
        会令指向 spec/changes 的真实夹具失效（judge 判定噪音源），此处把归档
        副本拷入临时项目结构后按同一路径约定收集。
        """
        from core.interaction_contract import collect_spec_candidates
        with tempfile.TemporaryDirectory() as td:
            spec_copy = Path(td) / "spec" / "changes" / "v2-overview-page"
            spec_copy.parent.mkdir(parents=True)
            shutil.copytree(
                REPO_ROOT / "spec" / "archive" / "2026-09-05-v2-overview-page",
                spec_copy)
            cands = collect_spec_candidates(td, "v2-overview-page")
        keys = [c.key for c in cands]
        # proposal.md「项目 cards(启动/停止/删除按钮…)」是事故复发点
        self.assertTrue(any("card" in k for k in keys), keys)


# ───────────────── 2. 覆盖校验：缺失被拦 / 声明放行 ─────────────────


class TestCoverageValidation(unittest.TestCase):
    """场景覆盖 diff + 纯展示声明放行（spec 需求：可交互元素的行为契约）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        _write_spec_doc(
            self.proot, "demo", "specs/demo/spec.md",
            "项目卡片渲染为链接样式（dark-Card--link），点击卡片跳转项目详情页。\n"
            "顶部渲染 button-group 操作区。\n",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _scenarios(self, *objs):
        return list(objs)

    def test_uncovered_candidates_rejected(self):
        """既无覆盖又无声明 → 校验失败（要求 planner 补齐）。"""
        from core.interaction_contract import validate_interaction_coverage
        scenarios = [{"id": "s1", "description": "统计块渲染真实数值"}]
        res = validate_interaction_coverage(self.proot, "demo", scenarios)
        self.assertFalse(res.ok)
        self.assertEqual(sorted(res.uncovered), ["button-group", "card-link"])
        # 反馈文本内容断言见 test_feedback_text_requests_completion（不重复）

    def test_scenario_coverage_channels_pass(self):
        """两条覆盖通道均放行：description 文本引用 / covers 显式登记。"""
        from core.interaction_contract import validate_interaction_coverage
        channels = {
            "description-text": [
                {"id": "s1", "description": "点击项目卡片（dark-Card--link）后跳转项目详情页"},
                {"id": "s2", "description": "点击 button-group 中的启动按钮，toast 提示"},
            ],
            "covers-metadata": [
                {"id": "s1", "description": "卡片交互流程", "covers": ["dark-Card--link"]},
                {"id": "s2", "description": "操作区交互", "covers": ["button-group"]},
            ],
        }
        for channel, scenarios in channels.items():
            with self.subTest(channel=channel):
                res = validate_interaction_coverage(self.proot, "demo", scenarios)
                self.assertTrue(res.ok, res.uncovered)
        # 文本引用通道覆盖映射（design D1：description 引用即覆盖）
        res = validate_interaction_coverage(self.proot, "demo",
                                            channels["description-text"])
        covered = {k: v for k, v in res.covered}
        self.assertEqual(covered.get("card-link"), ["s1"])
        self.assertEqual(covered.get("button-group"), ["s2"])

    def test_declared_display_channel(self):
        """通道：planner declared_display 纯展示声明放行。"""
        from core.interaction_contract import validate_interaction_coverage
        scenarios = [
            {"id": "s1", "description": "卡片交互流程", "covers": ["dark-Card--link"]},
            {"id": "s2", "description": "统计渲染",
             "declared_display": ["button-group"]},
        ]
        res = validate_interaction_coverage(self.proot, "demo", scenarios)
        self.assertTrue(res.ok, res.uncovered)
        self.assertEqual(res.declared, ["button-group"])

    def test_spec_inline_display_declaration_exempt(self):
        """SPEC 元素定义处的「纯展示」声明豁免交互场景。"""
        from core.interaction_contract import validate_interaction_coverage
        _write_spec_doc(
            self.proot, "demo", "specs/demo/spec.md",
            "项目卡片渲染为链接样式（dark-Card--link），点击卡片跳转项目详情页。\n"
            "顶部渲染 button-group 操作区（纯展示、不可交互）。\n",
        )
        scenarios = [
            {"id": "s1", "description": "点击卡片跳转", "covers": ["card-link"]},
        ]
        res = validate_interaction_coverage(self.proot, "demo", scenarios)
        self.assertTrue(res.ok, res.uncovered)

    def test_legacy_persisted_set_skipped(self):
        """旧场景集（无 covers 元数据）不追溯（design D2）。"""
        from core.interaction_contract import validate_interaction_coverage
        from core.verify_scenarios import ScenarioSet, ScenarioEntry
        persisted = ScenarioSet("demo", 3, [ScenarioEntry("s1", "旧场景", 1)])
        scenarios = [{"id": "s1", "description": "统计块渲染"}]
        res = validate_interaction_coverage(
            self.proot, "demo", scenarios, persisted)
        self.assertTrue(res.skipped)
        self.assertTrue(res.ok)

    def test_feedback_text_requests_completion(self):
        """反馈文本要求补齐：交互场景（covers 登记）或纯展示声明。"""
        from core.interaction_contract import (
            validate_interaction_coverage, build_replan_feedback,
        )
        scenarios = [{"id": "s1", "description": "统计块渲染真实数值"}]
        res = validate_interaction_coverage(self.proot, "demo", scenarios)
        feedback = build_replan_feedback(res)
        self.assertIn("交互契约覆盖不完整", feedback)
        self.assertIn("dark-Card--link", feedback)
        self.assertIn("covers", feedback)
        self.assertIn("declared_display", feedback)


class TestNonWebScenarioNoop(unittest.TestCase):
    """多形态验证（add-verify-multi-kind-runner）：交互契约对非 web 场景空转。

    cli/api 场景没有可交互元素（run/http_request 是执行/请求步骤，不是 UI
    控件）：collect_display_declarations 不得把 run/http_request 步骤误报为
    交互声明；纯 cli/api 场景集无 candidates 时覆盖校验空转放行。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def _write_cli_spec(self):
        # 纯 CLI 交付的 SPEC 文档：无页面/交互元素关键词
        _write_spec_doc(
            self.proot, "cli-demo", "specs/cli-demo/spec.md",
            "新增 cost-stats 命令：输出各模型成本统计并落盘 CSV。\n",
        )

    def test_collect_declarations_not_fooled_by_run_http_steps(self):
        """run/http_request 步骤中的交互形态关键词不产生误报声明。

        collect_display_declarations 只认场景显式 declared_display 数组；
        command/url/headers 字段不进场景文本 blob，不会把命令参数里的
        「button」等词误判为交互元素声明。
        """
        from core.interaction_contract import collect_display_declarations
        scenarios = [
            {"id": "c1", "kind": "cli",
             "description": "运行统计命令",
             "steps": [{"action": "run",
                        "command": "click-button --target .save-btn",
                        "as": "out"}]},
            {"id": "a1", "kind": "api",
             "description": "请求端点",
             "steps": [{"action": "http_request", "method": "GET",
                        "url": "http://stale:1/api/save-button",
                        "headers": {"X": "card-link"}}]},
        ]
        declared = collect_display_declarations(scenarios)
        self.assertEqual(declared, [], "run/http_request 不得产生纯展示声明")
        # 显式 declared_display 仍被正常收集（不是被禁用）
        scenarios[0]["declared_display"] = ["status-tile"]
        declared2 = collect_display_declarations(scenarios)
        self.assertEqual(declared2, ["status-tile"])

    def test_pure_cli_set_no_candidates_noop(self):
        """纯 cli/api 场景集 + 无候选元素：覆盖校验空转放行（covers 空登记合法）。"""
        from core.interaction_contract import (
            validate_interaction_coverage, collect_display_declarations,
        )
        self._write_cli_spec()
        scenarios = [
            {"id": "c1", "kind": "cli",
             "description": "运行统计命令",
             "steps": [{"action": "run", "command": "cost-stats --out cost.csv",
                        "as": "out"}],
             "assertions": [{"type": "exit_code", "expected": 0}]},
            {"id": "a1", "kind": "api", "description": "请求端点",
             "steps": [{"action": "http_request", "method": "GET",
                        "url": "http://stale:1/api/cost"}]},
        ]
        # cli/api 场景无 covers 字段合法（候选来自 SPEC 文档）；声明收集也空
        self.assertEqual(collect_display_declarations(scenarios), [])
        res = validate_interaction_coverage(self.proot, "cli-demo", scenarios)
        self.assertTrue(res.ok, res.uncovered)
        self.assertIn("未检出可交互候选元素", "\n".join(res.change_lines))


# ───────────────── 3. scenarios.json 元数据（任务 1.2） ─────────────────


class TestScenarioMetadata(unittest.TestCase):
    """契约声明进场景集元数据（spec Scenario: 契约声明进场景集元数据）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_covers_and_display_declarations_persisted(self):
        from core.verify_scenarios import (
            diff_planner_output, save_scenario_set, load_scenario_set,
        )
        planner = [
            {"id": "s1", "description": "卡片交互", "covers": ["dark-Card--link"]},
            {"id": "s2", "description": "统计渲染",
             "declared_display": ["button-group"]},
        ]
        diff = diff_planner_output(self.proot, "demo", None, planner, 1)
        save_scenario_set(self.proot, diff.scenario_set)
        got = load_scenario_set(self.proot, "demo")
        covers_map = {e.id: e.covers for e in got.scenarios}
        self.assertEqual(covers_map["s1"], ["dark-Card--link"])
        self.assertEqual(got.display_declarations, ["button-group"])
        # 可审计：落盘 JSON 含元数据字段
        raw = json.loads((self.proot / ".fenix" / "verify-progress" / "demo"
                          / "scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["scenarios"][0]["covers"], ["dark-Card--link"])
        self.assertEqual(raw["display_declarations"], ["button-group"])

    def test_legacy_entries_without_covers_omit_field(self):
        """旧集条目无 covers → 落盘不带该字段（向后兼容）。"""
        from core.verify_scenarios import ScenarioEntry, ScenarioSet
        d = ScenarioEntry("s1").to_dict()
        self.assertNotIn("covers", d)
        d2 = ScenarioSet("demo", 1, [ScenarioEntry("s1")]).to_dict()
        self.assertNotIn("display_declarations", d2)
        # 旧格式读回不崩
        s = ScenarioSet.from_dict({"spec": "demo", "round": 1,
                                   "scenarios": [{"id": "s1"}]})
        self.assertEqual(s.scenarios[0].covers, [])


# ───────────────── 4. 裁决逐断言归因（任务 2.2） ─────────────────


class TestAssertionTriageValidation(unittest.TestCase):
    """verdict_check 扩展：assertion_triage 完整性 + 豁免限制。"""

    def _failed_scenario(self, **kw):
        sc = {
            "scenario_id": "s1", "status": "failed",
            "classification": "test-defect",
            "evidence": {"first_failed_step": "步骤3 失败"},
            "assertion_results": [
                {"type": "no_click_interception", "pass": False,
                 "selector": ".dark-Card button"},
                {"type": "element_visible", "pass": False,
                 "selector": ".toast-success"},
            ],
            "assertion_triage": [
                {"assertion": "no_click_interception .dark-Card button",
                 "classification": "test-defect",
                 "evidence": "选择器含臆测类名"},
                {"assertion": "element_visible .toast-success",
                 "classification": "env",
                 "evidence": "网关抖动导致应用不可达"},
            ],
        }
        sc.update(kw)
        return sc

    def test_failed_without_triage_is_violation(self):
        from core.verdict_check import validate_report
        report = {"scenarios": [{
            "scenario_id": "s1", "status": "failed",
            "classification": "test-defect",
            "evidence": {"first_failed_step": "x"},
        }]}
        res = validate_report(report)
        self.assertFalse(res["ok"])
        self.assertIn("assertion_triage", res["violations"][0]["reason"])

    def test_triage_missing_entry_is_violation(self):
        """归因条目数少于失败断言数（漏条目）→ 违规。"""
        from core.verdict_check import validate_report
        sc = self._failed_scenario()
        sc["assertion_triage"] = sc["assertion_triage"][:1]
        res = validate_report({"scenarios": [sc]})
        self.assertFalse(res["ok"])
        self.assertIn("少于失败断言数", res["violations"][0]["reason"])

    def test_triage_illegal_class_or_empty_evidence_is_violation(self):
        from core.verdict_check import validate_report
        sc = self._failed_scenario(assertion_triage=[
            {"assertion": "a", "classification": "bogus", "evidence": "x"},
            {"assertion": "b", "classification": "env", "evidence": "  "},
        ])
        res = validate_report({"scenarios": [sc]})
        self.assertFalse(res["ok"])
        self.assertIn("classification", res["violations"][0]["reason"])

    def test_complete_triage_passes(self):
        from core.verdict_check import validate_report
        res = validate_report({"scenarios": [self._failed_scenario()]})
        self.assertTrue(res["ok"], res["violations"])

    def test_single_product_bug_assertion_blocks_exemption(self):
        """单断言 product-bug 阻止场景豁免（spec Scenario）。"""
        from core.verdict_check import is_scenario_exemptible, enforce_status_mapping
        sc = self._failed_scenario(
            status="warning", classification="env",
            assertion_triage=[
                {"assertion": "no_click_interception .dark-Card button",
                 "classification": "product-bug", "evidence": "卡片跳转未实现"},
                {"assertion": "element_visible .toast-success",
                 "classification": "env", "evidence": "环境抖动"},
            ])
        self.assertFalse(is_scenario_exemptible(sc))
        mapped = enforce_status_mapping({"scenarios": [sc]})
        self.assertEqual(mapped["corrected"][0]["to_status"], "failed")
        self.assertEqual(sc["status"], "failed")
        self.assertTrue(sc.get("exempt_blocked_by_assertion"))

    def test_all_non_product_bug_assertions_exemptible(self):
        """全断言非产品缺陷（test-defect/flaky/env 且各附证据）→ 可豁免。"""
        from core.verdict_check import is_scenario_exemptible
        sc = self._failed_scenario()
        self.assertTrue(is_scenario_exemptible(sc))
        sc2 = self._failed_scenario(status="warning", classification="env")
        self.assertTrue(is_scenario_exemptible(sc2))


# ───────────────── 5. 报告断言级豁免清单（任务 2.3 / 4.2） ─────────────────


class TestExemptionListSection(unittest.TestCase):
    """verify_report 渲染「断言级豁免清单」。"""

    def test_section_lists_each_exempted_assertion(self):
        from core.verify_report import render_verification_report
        report = {"summary": {"total": 2, "passed": 0, "warnings": 1,
                              "failed": 1, "errors": 0},
                  "scenarios": [
                      {"scenario_id": "s1", "status": "warning",
                       "classification": "env",
                       "assertion_triage": [
                           {"assertion": "no_click_interception .card button",
                            "classification": "test-defect",
                            "evidence": "选择器失效"},
                           {"assertion": "text_match .title",
                            "classification": "env", "evidence": "网络不可达"},
                       ]},
                      {"scenario_id": "s2", "status": "failed",
                       "classification": "product-bug",
                       "assertion_triage": [
                           {"assertion": "element_visible .detail",
                            "classification": "product-bug",
                            "evidence": "跳转未实现"},
                       ]},
                  ]}
        run_result = {"status": "bug-found", "bugs": []}
        content = render_verification_report("demo", run_result, report)
        self.assertIn("## 断言级豁免清单", content)
        # 被豁免断言逐条可见（场景 / 断言 / 归类 / 证据 / 理由）
        self.assertIn("no_click_interception .card button", content)
        self.assertIn("text_match .title", content)
        self.assertIn("test-defect", content)
        self.assertIn("选择器失效", content)
        self.assertIn("测试用例自身缺陷（非产品缺陷）", content)
        # product-bug 断言不被豁免（进「真实产品 Bug」，不进豁免清单）
        self.assertNotIn("element_visible .detail", content)

    def test_old_report_without_triage_omits_section(self):
        """历史报告无 assertion_triage → 小节缺省（design D4 向后兼容）。"""
        from core.verify_report import render_verification_report
        report = {"summary": {"total": 1, "passed": 0, "warnings": 0,
                              "failed": 1, "errors": 0},
                  "scenarios": [
                      {"scenario_id": "s1", "status": "fail",
                       "assertion_results": [
                           {"type": "element_visible", "pass": False}]},
                  ]}
        content = render_verification_report("demo", {"status": "bug-found"}, report)
        self.assertNotIn("断言级豁免清单", content)

    def test_exempted_assertions_helper_skips_product_bug(self):
        from core.verdict_check import exempted_assertions
        report = {"scenarios": [
            {"scenario_id": "s1", "status": "failed",
             "assertion_triage": [
                 {"assertion": "a", "classification": "product-bug",
                  "evidence": "e1"},
                 {"assertion": "b", "classification": "flaky", "evidence": "e2"},
             ]},
        ]}
        rows = exempted_assertions(report)
        self.assertEqual([r["assertion"] for r in rows], ["b"])
        self.assertEqual(rows[0]["classification"], "flaky")


class TestV2OverviewPageFixture(unittest.TestCase):
    """真实夹具回归（任务 4.2）：v2-overview-page 事故报告（12 场景 6 豁免）。

    事故：6 个失败场景被整体豁免为 harness 缺陷而放行，掩盖了卡片跳转缺失。
    逐断言归因后，豁免清单 MUST 逐条列出被豁免断言供人工复核。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        spec = "v2-overview-page"
        vdir = self.proot / ".fenix" / "verify-progress" / spec
        vdir.mkdir(parents=True, exist_ok=True)
        self.raw = _load_fixture("v2-overview-page-report.json")
        (vdir / "report.json").write_text(
            json.dumps(self.raw, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _enriched(self):
        """模拟 judge 逐断言归因：6 个失败场景各断言单独归类（事故当时的
        错误归类——整体豁免为 test-defect/env）。"""
        enriched = json.loads(json.dumps(self.raw))
        triaged = 0
        for sc in enriched["scenarios"]:
            if sc["status"] == "pass":
                continue
            failed = [a for a in sc.get("assertion_results", [])
                      if isinstance(a, dict) and not a.get("pass", True)]
            # step 级失败（无断言结果）也按一条归因补齐
            entries = [
                {"assertion": f"{a.get('type')} {a.get('selector', '')}".strip(),
                 "classification": "test-defect" if a.get("type") == "no_click_interception" else "env",
                 "evidence": "harness 缺陷（事故当时的整体豁免口径）"}
                for a in failed
            ] or [{"assertion": "step_failed", "classification": "env",
                   "evidence": "harness 缺陷"}]
            sc["assertion_triage"] = entries
            sc["classification"] = "test-defect"
            sc["evidence"] = {"failed_assertions": [
                {"type": a.get("type"), "selector": a.get("selector", "")}
                for a in failed] or [{"type": "step"}]}
            triaged += len(entries)
        self.assertEqual(len([s for s in enriched["scenarios"]
                              if s["status"] != "pass"]), 6)
        return enriched, triaged

    def test_old_incident_report_is_now_noncompliant(self):
        """事故报告（无逐断言归因）在现行校验器下不合规——驱动裁决补全。"""
        from core.verdict_check import validate_report
        res = validate_report(self.raw)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["violations"]), 6)  # 6 个失败场景各一条违规

    def test_exempted_assertions_listed_in_report(self):
        from core.verify_report import render_verification_report
        from core.verdict_check import exempted_assertions
        enriched, triaged = self._enriched()
        rows = exempted_assertions(enriched)
        self.assertEqual(len(rows), triaged)
        self.assertGreater(len(rows), 6)  # 每条失败断言各占一行
        (self.proot / ".fenix" / "verify-progress" / "v2-overview-page"
         / "report.json").write_text(
            json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
        content = render_verification_report(
            "v2-overview-page", {"status": "bug-found", "bugs": []}, enriched)
        self.assertIn("## 断言级豁免清单", content)
        # 事故关键证据逐条可见：卡片上的按钮点击拦截断言
        self.assertIn("no_click_interception .dark-Card:has-text('test-run-proj') "
                      "button:has-text('停止')", content)
        # 逐条含归类、豁免理由与证据列
        self.assertIn("| 场景 | 断言 | 归类 | 豁免理由 | 证据 |", content)
        self.assertIn("harness 缺陷", content)


# ───────────────── 6. prompt 契约条款（任务 1.2 / 2.1 / 3.1） ─────────────────


class _AgentRunnerBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        from core.agent_runner import AgentRunner
        wm = MagicMock()
        wm.get_legacy.return_value = None  # 无遗产 → 不注入 legacy 段
        sm = MagicMock()
        sm.read_one.return_value = None
        self.runner = AgentRunner({}, wm, sm, self.proot, MagicMock())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestPromptClauses(_AgentRunnerBase):
    def test_planner_plan_injects_contract_section_when_candidates(self):
        _write_spec_doc(
            self.proot, "demo", "specs/demo/spec.md",
            "项目卡片渲染为链接样式（dark-Card--link）。\n")
        prompt = self.runner._prompt_builder._build_prompt("demo", "planner-plan")
        self.assertIn("交互契约", prompt)
        self.assertIn("dark-Card--link", prompt)
        self.assertIn("covers", prompt)
        self.assertIn("declared_display", prompt)

    def test_planner_plan_prompt_unchanged_without_candidates(self):
        _write_spec_doc(self.proot, "demo", "proposal.md", "纯算法模块，无 UI。\n")
        prompt = self.runner._prompt_builder._build_prompt("demo", "planner-plan")
        # fix-agent-noninteractive-contract 2.x：中央「非交互契约」段标题含子串
        # 「交互契约」，通用子串否定断言已失效——改指交互契约段的独有标记
        # （interaction-contract / add-interaction-contract-and-per-assert-triage）。
        self.assertNotIn("interaction-contract", prompt)

    def test_planner_judge_requires_assertion_triage(self):
        prompt = self.runner._prompt_builder._build_prompt("demo", "planner-judge")
        self.assertIn("assertion_triage", prompt)
        self.assertIn("逐断言归因", prompt)
        self.assertIn("product-bug", prompt)

    def test_implementer_contract_clause(self):
        prompt = self.runner._prompt_builder._build_prompt("demo", "implementer")
        self.assertIn("交互契约", prompt)
        self.assertIn("待裁决交互", prompt)
        self.assertIn("findings", prompt)
        self.assertIn("纯展示", prompt)


if __name__ == "__main__":
    unittest.main()
