"""
截图时机门禁回归测试（spec add-lost-semantics-regression-tests
Requirement「截图时机门禁」，tasks 4.2）。

背景（c310ee5 refactor-test-structure）：原 TestVerifyEngineScreenshotTiming
（119 行真实浏览器测试）被替换为空壳后随清理删除，断言丢失。

时序机制（web_runner._execute_scenario，当前源码形态）：
- 操作步骤失败 → break → **断言根本不执行** → 不进入断言失败截图分支；
- 断言执行且至少一个失败 → 截图 ``{scenario.id}_assert_fail``（归因场景）；
- 断言全部通过（含未声明关键步骤截图）→ 不截图；
- 步骤声明 ``screenshot: true`` 且成功 → 按步骤截图 ``{scenario.id}_step{i}``。

本组测试按 design D1-4 用 mock 浏览器锁定「断言执行 ⇄ 截图调用」的时机
关系（不启动真实浏览器，验证调用时机而非渲染结果）。

spec 两个 Scenario：
- 断言未执行不出图（页面加载/前置步骤失败 → 无截图文件/截图事件）
- 断言执行后截图可归因（文件名含场景标识）
"""
import asyncio
import json
import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from core.verify_engine.web_runner import WebRunner
from core.verify_engine.scenarios import TestScenario


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


class TestScreenshotNotTakenWhenAssertionsNotExecuted(unittest.TestCase):
    """Scenario: 断言未执行不出图。

    前置步骤失败（页面导航/操作异常）→ 断言跳过 → 截图方法必须零调用、
    场景结果截图清单为空。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = _mk_web_runner(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_step_failure_before_assertions_no_screenshot(self):
        """导航失败（页面加载失败）→ 断言未执行 → 截图从未被调用。"""
        page = MagicMock()
        context = MagicMock()

        async def _execute_action(page, step):
            return {"action": step["action"], "success": False,
                    "error": "Page.goto: net::ERR_CONNECTION_REFUSED"}

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.browser.screenshot = AsyncMock(return_value="/tmp/x.png")

        scenario = _scenario("scn-fail-nav")
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        # 断言未执行（步骤失败短路）：截图时机门禁核心
        self.assertEqual(result["assertion_results"], [])
        self.runner.asserter.run.assert_not_called()
        self.assertEqual(result["screenshots"], [])
        self.runner.browser.screenshot.assert_not_called()

    def test_mid_scenario_step_failure_no_assertion_screenshot(self):
        """导航成功但中间操作失败 → 断言未执行 → 无断言失败截图。"""
        page = MagicMock()
        context = MagicMock()
        calls = {"n": 0}

        async def _execute_action(page, step):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"action": "navigate", "success": True, "detail": "ok"}
            return {"action": "click", "success": False, "error": "timeout"}

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.browser.screenshot = AsyncMock(return_value="/tmp/x.png")

        scenario = _scenario(
            "scn-mid-fail",
            steps=[
                {"action": "navigate", "value": "http://127.0.0.1:8787/a"},
                {"action": "click", "target": "[data-testid='btn']", "description": "点击"},
            ],
        )
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        self.assertEqual(result["assertion_results"], [])
        self.assertEqual(result["screenshots"], [])
        self.runner.browser.screenshot.assert_not_called()
        # 步骤失败错误已归因到 step_results（供裁决，而非截图）
        self.assertEqual(result["step_results"][-1]["success"], False)

    def test_asserter_not_called(self):
        """断言执行器未被触碰（assertion_results 为空但执行器本身也未调用）。"""
        page = MagicMock()
        context = MagicMock()
        self.runner.browser.execute_action = AsyncMock(
            return_value={"action": "navigate", "success": False, "error": "err"})
        self.runner.asserter.run = AsyncMock(return_value=[{"pass": True}])
        scenario = _scenario("scn-no-assert")
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))
        self.assertEqual(result["assertion_results"], [])
        self.runner.asserter.run.assert_not_called()


class TestScreenshotAttributableAfterAssertions(unittest.TestCase):
    """Scenario: 断言执行后截图可归因。

    断言真正执行且失败 → 截图文件名含场景标识（``{scenario.id}_assert_fail``），
    截图清单可作证据链；断言全部通过 → 不截图。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = _mk_web_runner(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_assert_fail_screenshot_contains_scenario_id(self):
        """断言失败 → 截图名含场景 id（可归因）。"""
        page = MagicMock()
        context = MagicMock()

        async def _execute_action(page, step):
            return {"action": "navigate", "success": True, "detail": "ok"}

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.browser.screenshot = AsyncMock(
            return_value="/tmp/scn-bug_assert_fail.png")
        self.runner.asserter.run = AsyncMock(return_value=[{
            "type": "element_visible", "pass": False,
            "error": "未找到元素 .x",
        }])

        scenario = _scenario("scn-bug")
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        self.assertEqual(len(result["assertion_results"]), 1)
        self.assertFalse(result["assertion_results"][0]["pass"])
        # 归因：截图文件名含场景标识
        self.assertEqual(len(result["screenshots"]), 1)
        call_args = self.runner.browser.screenshot.call_args
        self.assertIn("scn-bug", call_args.args[1])
        self.assertEqual(result["screenshots"][0], "/tmp/scn-bug_assert_fail.png")

    def test_assert_all_pass_no_screenshot(self):
        """断言全部通过 → 不产生截图（防截图噪音）。"""
        page = MagicMock()
        context = MagicMock()
        self.runner.browser.execute_action = AsyncMock(
            return_value={"action": "navigate", "success": True, "detail": "ok"})
        self.runner.asserter.run = AsyncMock(return_value=[
            {"type": "element_visible", "pass": True}])

        scenario = _scenario("scn-pass")
        result = asyncio.run(
            self.runner._execute_scenario(scenario, page, context))

        self.assertTrue(result["assertion_results"][0]["pass"])
        self.assertEqual(result["screenshots"], [])
        self.runner.browser.screenshot.assert_not_called()

    def test_steps_failed_flag_guards_assertion_branch(self):
        """steps_failed 标记与截图分支的绑定：断言执行与截图同源。"""
        page = MagicMock()
        context = MagicMock()
        called = {"assert": False, "shot": False}

        async def _execute_action(page, step):
            return {"action": "navigate", "success": True, "detail": "ok"}

        async def _assert_run(page, defs):
            called["assert"] = True
            return [{"type": "element_visible", "pass": False, "error": "boom"}]

        async def _shot(page, name, out):
            called["shot"] = True
            return str(Path(out) / f"{name}.png")

        self.runner.browser.execute_action = AsyncMock(side_effect=_execute_action)
        self.runner.asserter.run = AsyncMock(side_effect=_assert_run)
        self.runner.browser.screenshot = AsyncMock(side_effect=_shot)

        scenario = _scenario("scn-pair")
        asyncio.run(self.runner._execute_scenario(scenario, page, context))
        self.assertTrue(called["assert"], "断言应执行")
        self.assertTrue(called["shot"], "断言失败后应截图")


class TestVisualBaselineScreenshotAttribution(unittest.TestCase):
    """视觉对比基线解析（visual_diff 的截图归因）：baseline 场景截图与场景绑定。

    注：视觉对比属「断言执行后截图」的延伸——当前源码在 scenario.visual_baseline
    声明时由 differ 写 ``{scenario_id}_current.png``，同样按场景可归因。
    """

    def test_visual_diff_screenshot_name_includes_scenario_id(self):
        """视觉对比基线场景：截图文件名含场景 id（可归因）。

        用真实 PNG 生成基线图并建 baseline，使 compare 不触发异常（首次
        运行走 baseline_created 路径，不进入 SSIM 对比）。断言文件名含场景 id。
        """
        tmpdir = tempfile.mkdtemp()
        try:
            screenshots_dir = Path(tmpdir) / ".fenix" / "verify-progress" / \
                "demo-spec" / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            # 预置一张有效 PNG 供 shutil.copy 使用（baseline_created 路径）。
            # 须真实可解码：损坏流的截图自 item 8953abec4c68 起被 classify
            # 判定失败防护按 baseline_deferred 拒绝固化（原硬编码字节即
            # 残缺流，靠旧缺陷「判定失败照常固化」才走到建基线路径）
            buf = BytesIO()
            Image.new("RGB", (2, 2), (255, 255, 255)).save(buf, format="PNG")
            dummy_png = screenshots_dir / "_dummy.png"
            dummy_png.write_bytes(buf.getvalue())

            page = MagicMock()

            async def _shot(path=None, **kw):
                # 复制 dummy PNG 到 current_path（模拟真实截图文件）
                import shutil as _sh
                _sh.copy(str(dummy_png), path)
                return "ok"

            page.screenshot = AsyncMock(side_effect=_shot)
            differ = __import__(
                "core.verify_engine.visual_diff", fromlist=["VisualDiffer"]
            ).VisualDiffer("demo-spec", Path(tmpdir))
            result = asyncio.run(
                differ.compare(page, "baseline-name", "scn-visual"))
            self.assertIsInstance(result, list)
            self.assertEqual(result[0]["status"], "baseline_created")
            # 截图文件名含场景 id：scn-visual_current.png
            self.assertTrue(
                (screenshots_dir / "scn-visual_current.png").exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()