"""
断言求值时机分层回归测试（spec web-runner-assertion-eval-timing，tasks 2.1）。

机制（当前源码形态）：
- web_runner._execute_scenario 按断言类型分桶构建求值计划：交互桶
  （WEB_ASSERTION_LAYERS 第 2 层：no_click_interception / no_overlap /
  in_viewport / z_index_order）走视图切换感知求值窗口——逐步骤完成点探测
  目标元素可见性，于目标元素仍可见的最后一个步骤完成点即时求值（含
  trial click）；全程不可见回退既有后置时机。流程桶（no_console_error 等）
  保持既有后置统一求值。
- assertions.py 第 2 层断言的 trial click 与 not visible 等失败分支附求值
  时刻视图状态快照（current_view / element_view / basis）入失败载荷。

spec 两个 Requirement 的 Scenario 全覆盖：
- 导航切视图不再误报 / 流程级断言语义不变 / 全程不可见回退后置 /
  早期失败不中断步骤（不启动真实浏览器，mock page 锁定求值时机）
- 失败载荷视图快照字段（真实 AssertionRunner + 假 page 锁定载荷形状）
"""
import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from core.verify_engine.assertions import AssertionRunner
from core.verify_engine.web_runner import WebRunner
from core.verify_engine.scenarios import TestScenario

# 假快照（asseter 级测试的 evaluate 路由产物）：形态对齐 _VIEW_SNAPSHOT_JS
# 的返回结构（current_view / element_view / basis）
_SNAPSHOT_SWITCHED_AWAY = {
    "current_view": {"id": "view-session", "class": "view"},
    "element_view": {"id": "view-connect", "class": "view"},
    "basis": {
        "attached": True,
        "display": "",
        "element_self_visible": False,
        "element_view_visible": False,
        "verdict": "目标元素所在视图非当前可见视图",
    },
}
_SNAPSHOT_SAME_VIEW = {
    "current_view": {"id": "view-connect", "class": "view"},
    "element_view": {"id": "view-connect", "class": "view"},
    "basis": {
        "attached": True,
        "display": "block",
        "element_self_visible": True,
        "element_view_visible": True,
        "verdict": "目标元素所在视图当前可见",
    },
}
_SNAPSHOT_MISSING = {
    "current_view": None,
    "element_view": None,
    "basis": {
        "attached": False,
        "verdict": "目标元素不存在于 DOM（未渲染或已卸载）",
    },
}


def _scenario(sid, steps=None, assertions=None):
    """构造合法 web 场景（navigate 绝对 URL 通过验收）。"""
    return TestScenario.from_dict({
        "id": sid,
        "description": f"场景 {sid}",
        "kind": "web",
        "steps": steps or [
            {"action": "navigate", "value": "http://127.0.0.1:8787/dashboard"},
        ],
        "assertions": assertions or [
            {"type": "element_visible", "selector": ".x", "label": "元素可见"},
        ],
    })


def _mk_web_runner(tmpdir):
    """WebRunner 最小实例（mock 浏览器/断言器，绝不启动真实浏览器）。"""
    runner = WebRunner(
        "demo-spec", project_root=Path(tmpdir), logger=MagicMock(),
        config={"verify_engine": {"headless": True}},
    )
    runner._setup_health_ok = True
    runner.browser = MagicMock()
    runner.asserter = MagicMock()
    runner.differ = MagicMock()
    return runner


def _mk_runner_page(vis_seq=None, default_visible=False):
    """page mock：locator(sel).first.is_visible() 按声明序出队，耗尽后保持末值。

    模拟导航切视图的可见性演化：步骤完成点逐次探测，元素随视图切换由
    True→False 的序列表达。未登记的选择器按 default_visible 返回。
    """
    page = MagicMock()
    counters: dict = {}

    def _locator(sel):
        loc = MagicMock()
        loc.first = loc

        async def _is_visible():
            seq = (vis_seq or {}).get(sel)
            if not seq:
                return default_visible
            k = counters.get(sel, 0)
            counters[sel] = min(k + 1, len(seq) - 1)
            return seq[k]

        loc.is_visible = AsyncMock(side_effect=_is_visible)
        return loc

    page.locator = MagicMock(side_effect=_locator)
    return page


class _FakePage:
    """AssertionRunner 假 page：按选择器表驱动 count/click/evaluate。

    evaluate 按 JS 特征路由：含 current_view 的为视图快照 JS（返回 snapshot），
    含 elementFromPoint 的为拦截详情 JS（返回 intercept_detail），其余按
    eval_results[selector] 返回（缺省 None = 元素求值不可用）。
    """

    def __init__(self, counts=None, click_errors=None, eval_results=None,
                 snapshot=None, intercept_detail=None, eval_raises=False):
        self.counts = counts or {}
        self.click_errors = click_errors or {}
        self.eval_results = eval_results or {}
        self.snapshot = snapshot
        self.intercept_detail = intercept_detail
        self.eval_raises = eval_raises

    def locator(self, selector):
        return _FakeLocator(self, selector)


class _FakeLocator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    @property
    def first(self):
        return self

    async def count(self):
        return self._page.counts.get(self._selector, 0)

    async def click(self, trial=False, timeout=None):
        err = self._page.click_errors.get(self._selector)
        if err:
            raise Exception(err)

    async def evaluate(self, js, *args, timeout=None):
        if self._page.eval_raises:
            raise RuntimeError("evaluate context destroyed")
        if "current_view" in js:
            return self._page.snapshot
        if "elementFromPoint" in js:
            return self._page.intercept_detail
        return self._page.eval_results.get(self._selector)

    async def wait_for(self, state=None, timeout=None):
        if self._page.counts.get(self._selector, 0) == 0:
            raise Exception("element not found")


class TestViewSwitchAwareEvalWindow(unittest.TestCase):
    """Requirement: 断言求值时机按类型分层（web_runner 侧时机关系）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = _mk_web_runner(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_view_switch_interactive_assertion_not_misreported(self):
        """Scenario: 导航切视图不再误报。

        步骤 1 后 #connect-btn 可见、步骤 2（点击进会话视图）后随视图隐藏：
        交互断言须在步骤 1 完成点（元素仍可见的最后一个步骤完成点）求值
        并通过，而非延到断言批时刻在错误视图下误报 not visible。
        """
        page = _mk_runner_page(vis_seq={"#connect-btn": [True, False]})
        context = MagicMock()
        events: list = []

        async def _execute_action(p, step):
            events.append(f"step:{step['action']}")
            return {"action": step["action"], "success": True, "detail": "ok"}

        async def _run(p, defs):
            events.append("assert:" + ",".join(d["type"] for d in defs))
            out = []
            for d in defs:
                if d["type"] == "no_click_interception":
                    out.append({"type": d["type"], "pass": True, "selector": d["selector"]})
                else:
                    out.append({"type": d["type"], "pass": True})
            return out

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.asserter.run = AsyncMock(side_effect=_run)
        self.runner.browser.screenshot = AsyncMock(return_value="/tmp/x.png")

        scenario = _scenario(
            "scn-view-switch",
            steps=[
                {"action": "navigate", "value": "http://127.0.0.1:8787/dashboard"},
                {"action": "click", "target": "#enter-session", "description": "进会话视图"},
            ],
            assertions=[
                {"type": "no_click_interception", "selector": "#connect-btn",
                 "label": "连接按钮不被遮挡"},
                {"type": "no_console_error"},
            ],
        )
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        results = result["assertion_results"]
        self.assertEqual(len(results), 2)
        # 交互断言：窗口内求值且通过（不再误报 not visible）
        self.assertTrue(results[0]["pass"])
        self.assertTrue(results[0]["eval_timing"].startswith("in-window"))
        # 求值点在切视图步骤之前（元素仍可见的完成点）
        self.assertEqual(events, [
            "step:navigate", "assert:no_click_interception",
            "step:click", "assert:no_console_error",
        ])
        # 两次 asserter.run：窗口内 [NCI]、后置 [no_console_error]
        self.assertEqual(self.runner.asserter.run.call_count, 2)
        post_defs = self.runner.asserter.run.call_args_list[1].args[1]
        self.assertEqual([d["type"] for d in post_defs], ["no_console_error"])
        # 全部通过 → 不触发断言失败截图（取证触发条件不变）
        self.assertEqual(result["screenshots"], [])
        self.assertEqual(result["status"], "pass")

    def test_flow_level_assertion_post_batch_unchanged(self):
        """Scenario: 流程级断言语义不变。

        纯流程桶场景（no_console_error / element_visible）只在全部步骤后
        统一求值一次，且运行时数据注入（_console_errors）保持既有行为。
        """
        page = _mk_runner_page()
        context = MagicMock()
        events: list = []

        async def _execute_action(p, step):
            events.append(f"step:{step['action']}")
            return {"action": step["action"], "success": True, "detail": "ok"}

        async def _run(p, defs):
            events.append("assert:" + ",".join(d["type"] for d in defs))
            return [{"type": d["type"], "pass": True} for d in defs]

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.asserter.run = AsyncMock(side_effect=_run)

        scenario = _scenario(
            "scn-flow-only",
            steps=[
                {"action": "navigate", "value": "http://127.0.0.1:8787/a"},
                {"action": "click", "target": "#btn", "description": "操作"},
            ],
            assertions=[
                {"type": "no_console_error"},
                {"type": "element_visible", "selector": ".x"},
            ],
        )
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        # 只后置求值一次（全部步骤完成后），两断言同批
        self.assertEqual(events, ["step:navigate", "step:click",
                                  "assert:no_console_error,element_visible"])
        self.assertEqual(self.runner.asserter.run.call_count, 1)
        post_defs = self.runner.asserter.run.call_args.args[1]
        # 运行时数据注入保持现状
        self.assertIn("_console_errors", post_defs[0])
        self.assertIn("_external_net_errors_ok", post_defs[0])
        # 结果保持声明序
        self.assertEqual([r["type"] for r in result["assertion_results"]],
                         ["no_console_error", "element_visible"])
        self.assertEqual(result["status"], "pass")

    def test_never_visible_falls_back_to_post_eval(self):
        """Scenario: 全程不可见回退后置。

        交互断言目标元素自始至终不可见（元素缺失/真实缺陷）：保持未决、
        回退既有后置时机求值判失败，真实缺陷不被提前求值掩盖。
        """
        page = _mk_runner_page(default_visible=False)
        context = MagicMock()
        events: list = []

        async def _execute_action(p, step):
            events.append(f"step:{step['action']}")
            return {"action": step["action"], "success": True, "detail": "ok"}

        async def _run(p, defs):
            events.append("assert:" + ",".join(d["type"] for d in defs))
            return [{"type": d["type"], "pass": False, "error": "元素不存在"}]

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.asserter.run = AsyncMock(side_effect=_run)
        self.runner.browser.screenshot = AsyncMock(return_value="/tmp/x.png")

        scenario = _scenario(
            "scn-never-visible",
            steps=[
                {"action": "navigate", "value": "http://127.0.0.1:8787/a"},
                {"action": "click", "target": "#btn", "description": "操作"},
            ],
            assertions=[
                {"type": "no_click_interception", "selector": "#missing-btn"},
            ],
        )
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        # 全部步骤完成后才求值（后置时机）
        self.assertEqual(events, ["step:navigate", "step:click",
                                  "assert:no_click_interception"])
        self.assertEqual(self.runner.asserter.run.call_count, 1)
        results = result["assertion_results"]
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["pass"])
        self.assertNotIn("eval_timing", results[0])
        # 失败取证截图触发条件不变
        self.assertEqual(len(result["screenshots"]), 1)
        self.assertEqual(result["status"], "fail")

    def test_early_failure_does_not_interrupt_steps_declaration_order(self):
        """Scenario: 早期失败不中断步骤。

        交互断言在求值窗口内失败：后续步骤继续执行，assertion_results
        保持断言声明序，失败取证截图照常触发。
        """
        page = _mk_runner_page(vis_seq={"#connect-btn": [True, False]})
        context = MagicMock()
        events: list = []

        async def _execute_action(p, step):
            events.append(f"step:{step['action']}")
            return {"action": step["action"], "success": True, "detail": "ok"}

        async def _run(p, defs):
            events.append("assert:" + ",".join(d["type"] for d in defs))
            out = []
            for d in defs:
                if d["type"] == "no_click_interception":
                    out.append({"type": d["type"], "pass": False,
                                "error": "element is not visible"})
                else:
                    out.append({"type": d["type"], "pass": True})
            return out

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.asserter.run = AsyncMock(side_effect=_run)
        self.runner.browser.screenshot = AsyncMock(return_value="/tmp/x.png")

        scenario = _scenario(
            "scn-early-fail",
            steps=[
                {"action": "navigate", "value": "http://127.0.0.1:8787/a"},
                {"action": "click", "target": "#enter-session", "description": "切换"},
            ],
            assertions=[
                {"type": "no_click_interception", "selector": "#connect-btn"},
                {"type": "element_visible", "selector": ".session-hud"},
            ],
        )
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        # 交互断言早期失败不中断后续步骤（两次操作都执行了）
        self.assertEqual([e for e in events if e.startswith("step")],
                         ["step:navigate", "step:click"])
        results = result["assertion_results"]
        # 结果保持断言声明序
        self.assertEqual([r["type"] for r in results],
                         ["no_click_interception", "element_visible"])
        self.assertFalse(results[0]["pass"])
        self.assertTrue(results[0]["eval_timing"].startswith("in-window"))
        self.assertTrue(results[1]["pass"])
        # 失败取证截图照常触发
        self.assertEqual(len(result["screenshots"]), 1)
        self.assertEqual(result["status"], "fail")

    def test_anchor_visible_throughout_result_unchanged(self):
        """Scenario: #connect-btn 锚类场景在新时机下求值结果不变。

        目标元素全程可见：每个步骤完成点都即时求值、取最后一个完成点的
        结果，最终求值语义与既有后置（元素到末尾仍可见）一致且通过。
        """
        page = _mk_runner_page(default_visible=True)
        context = MagicMock()

        async def _execute_action(p, step):
            return {"action": step["action"], "success": True, "detail": "ok"}

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.asserter.run = AsyncMock(return_value=[
            {"type": "no_click_interception", "pass": True}])

        scenario = _scenario(
            "scn-anchor",
            steps=[
                {"action": "navigate", "value": "http://127.0.0.1:8787/a"},
                {"action": "click", "target": "#b1", "description": "一"},
                {"action": "click", "target": "#b2", "description": "二"},
            ],
            assertions=[
                {"type": "no_click_interception", "selector": "#connect-btn"},
            ],
        )
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        results = result["assertion_results"]
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["pass"])
        # 取最后一个可见完成点（步骤 3/3）的求值结果
        self.assertEqual(results[0]["eval_timing"], "in-window(step 3/3)")
        # 每个步骤完成点各求值一次、无后置重复求值
        self.assertEqual(self.runner.asserter.run.call_count, 3)
        for call in self.runner.asserter.run.call_args_list:
            self.assertEqual([d["type"] for d in call.args[1]],
                             ["no_click_interception"])
        self.assertEqual(result["status"], "pass")

    def test_window_eval_exception_falls_back_post_batch(self):
        """窗口内求值异常不中断步骤：该断言回退既有后置时机求值。"""
        page = _mk_runner_page(default_visible=True)
        context = MagicMock()
        calls: list = []

        async def _execute_action(p, step):
            return {"action": step["action"], "success": True, "detail": "ok"}

        async def _run(p, defs):
            calls.append([d["type"] for d in defs])
            if len(calls) <= 2:
                raise RuntimeError("window eval boom")
            return [{"type": d["type"], "pass": True} for d in defs]

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.asserter.run = AsyncMock(side_effect=_run)

        scenario = _scenario(
            "scn-window-exc",
            steps=[
                {"action": "navigate", "value": "http://127.0.0.1:8787/a"},
                {"action": "click", "target": "#btn", "description": "操作"},
            ],
            assertions=[
                {"type": "no_click_interception", "selector": "#connect-btn"},
            ],
        )
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        # 两个步骤完成点各尝试一次（均异常），后置兜底求值成功
        self.assertEqual(calls,
                         [["no_click_interception"],
                          ["no_click_interception"],
                          ["no_click_interception"]])
        results = result["assertion_results"]
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["pass"])
        self.assertNotIn("eval_timing", results[0])
        self.assertEqual(result["status"], "pass")

    def test_steps_failed_discards_window_results(self):
        """步骤失败 → 断言「根本没进行」契约不变：窗口内已求值结果一并丢弃。"""
        page = _mk_runner_page(default_visible=True)
        context = MagicMock()
        calls: list = []

        async def _execute_action(p, step):
            if step["action"] == "click":
                return {"action": "click", "success": False, "error": "timeout"}
            return {"action": step["action"], "success": True, "detail": "ok"}

        async def _run(p, defs):
            calls.append([d["type"] for d in defs])
            return [{"type": d["type"], "pass": True}]

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.asserter.run = AsyncMock(side_effect=_run)
        self.runner.browser.screenshot = AsyncMock(return_value="/tmp/x.png")

        scenario = _scenario(
            "scn-step-fail",
            steps=[
                {"action": "navigate", "value": "http://127.0.0.1:8787/a"},
                {"action": "click", "target": "#btn", "description": "失败步骤"},
            ],
            assertions=[
                {"type": "no_click_interception", "selector": "#connect-btn"},
            ],
        )
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        # 窗口求值发生过（步骤 1 完成点），但报告口径与现状一致：断言未进行
        self.assertEqual(calls, [["no_click_interception"]])
        self.assertEqual(result["assertion_results"], [])
        self.assertEqual(result["screenshots"], [])
        self.runner.browser.screenshot.assert_not_called()
        self.assertEqual(result["status"], "fail")


class TestViewSnapshotPayload(unittest.TestCase):
    """Requirement: 交互断言失败附视图快照（assertions 侧失败载荷形状）。"""

    def setUp(self):
        self.asserter = AssertionRunner()

    def test_nci_not_visible_payload_has_view_snapshot(self):
        """Scenario: 元素随视图切走——not visible 失败载荷明示视图归因。"""
        page = _FakePage(
            counts={"#connect-btn": 1},
            click_errors={"#connect-btn": "TimeoutError: element is not visible"},
            snapshot=_SNAPSHOT_SWITCHED_AWAY,
        )
        result = asyncio.run(self.asserter.run(page, [
            {"type": "no_click_interception", "selector": "#connect-btn",
             "label": "连接按钮不被遮挡"},
        ]))
        self.assertEqual(len(result), 1)
        r = result[0]
        self.assertFalse(r["pass"])
        self.assertIn("not visible", r["error"])
        snap = r["view_snapshot"]
        # 快照三字段键齐备：当前可见视图 / 目标元素所在视图 / 判定依据
        self.assertEqual(snap["current_view"], {"id": "view-session", "class": "view"})
        self.assertEqual(snap["element_view"], {"id": "view-connect", "class": "view"})
        self.assertEqual(snap["basis"]["verdict"], "目标元素所在视图非当前可见视图")
        self.assertFalse(snap["basis"]["element_view_visible"])

    def test_nci_intercepted_payload_has_detail_and_snapshot(self):
        """Scenario: 元素确被遮挡——intercept_detail 与视图快照（同视图依据）并存。"""
        page = _FakePage(
            counts={"#connect-btn": 1},
            click_errors={
                "#connect-btn":
                    "TimeoutError: element click: <div class=modal> intercepts "
                    "pointer events",
            },
            intercept_detail={
                "intercepting_tag": "DIV",
                "intercepting_class": "modal",
                "intercepting_z_index": "999",
                "target_z_index": "10",
            },
            snapshot=_SNAPSHOT_SAME_VIEW,
        )
        result = asyncio.run(self.asserter.run(page, [
            {"type": "no_click_interception", "selector": "#connect-btn"},
        ]))
        r = result[0]
        self.assertFalse(r["pass"])
        self.assertIn("intercepts pointer events", r["error"])
        self.assertEqual(r["intercept_detail"]["intercepting_class"], "modal")
        # 同视图判定依据：视图可见、元素可见 → 归因遮挡而非视图切换
        self.assertEqual(r["view_snapshot"]["basis"]["verdict"],
                         "目标元素所在视图当前可见")

    def test_missing_element_branches_attach_snapshot(self):
        """元素不存在类失败分支（in_viewport / no_overlap / z_index_order）
        均附降级视图快照（attached=False），真实缺陷不被静默放行。"""
        page = _FakePage(snapshot=_SNAPSHOT_MISSING)
        for a_type, extra in [
            ("in_viewport", {}),
            ("no_overlap", {}),
            ("z_index_order", {"compare_selector": "#other"}),
        ]:
            result = asyncio.run(self.asserter.run(page, [
                {"type": a_type, "selector": "#missing-btn", **extra},
            ]))
            r = result[0]
            self.assertFalse(r["pass"], a_type)
            snap = r.get("view_snapshot")
            self.assertIsInstance(snap, dict, a_type)
            self.assertFalse(snap["basis"]["attached"], a_type)
            self.assertIn("不存在", snap["basis"]["verdict"], a_type)

    def test_zero_size_branches_attach_snapshot(self):
        """零尺寸/隐藏类失败分支（in_viewport / no_overlap）附视图快照，
        判定依据携带元素所在视图可见性。"""
        page = _FakePage(
            counts={"#hidden-btn": 1},
            eval_results={"#hidden-btn": {"zero_size": True}},
            snapshot=_SNAPSHOT_SWITCHED_AWAY,
        )
        for a_type in ("in_viewport", "no_overlap"):
            result = asyncio.run(self.asserter.run(page, [
                {"type": a_type, "selector": "#hidden-btn"},
            ]))
            r = result[0]
            self.assertFalse(r["pass"], a_type)
            self.assertIn("零尺寸", r["error"], a_type)
            snap = r["view_snapshot"]
            self.assertEqual(snap["element_view"]["id"], "view-connect", a_type)
            self.assertEqual(snap["basis"]["verdict"],
                             "目标元素所在视图非当前可见视图", a_type)

    def test_snapshot_collection_failure_does_not_break_failure_payload(self):
        """快照采集异常降级为带 verdict 的占位快照，不破坏断言失败结果本身。"""
        page = _FakePage(
            counts={"#connect-btn": 1},
            click_errors={"#connect-btn": "element is not visible"},
            eval_raises=True,
        )
        result = asyncio.run(self.asserter.run(page, [
            {"type": "no_click_interception", "selector": "#connect-btn"},
        ]))
        r = result[0]
        self.assertFalse(r["pass"])
        snap = r["view_snapshot"]
        self.assertIsNone(snap["current_view"])
        self.assertIsNone(snap["element_view"])
        self.assertTrue(snap["basis"]["verdict"].startswith("视图快照采集失败"))

    def test_pass_result_has_no_snapshot(self):
        """trial click 通过的断言不附快照（快照只随失败载荷，控制体积）。"""
        page = _FakePage(counts={"#connect-btn": 1})
        result = asyncio.run(self.asserter.run(page, [
            {"type": "no_click_interception", "selector": "#connect-btn"},
        ]))
        r = result[0]
        self.assertTrue(r["pass"])
        self.assertNotIn("view_snapshot", r)


if __name__ == "__main__":
    unittest.main()
