"""expect_network 交互步骤网络请求断言单测（add-mechanical-scenario-refetch-assertion）。

覆盖：
- 引擎执行（browser.execute_action 包装窗口）：request 事件收集、URL 子串/``re:``
  前缀正则匹配、min_count 断言、窗口收尾固定短静默等待（延迟请求不漏计）、
  失败明细（期望/实际计数 + 至多 3 条样例 URL）、步骤失败计入场景 fail。
- 契约校验（scenarios._validate_web 白名单段）：交互/非交互显式集、形态逐条
  报错、min_count > 3 WARNING 不拒绝。
- TestStep expect_network 规范字段 from_dict/to_dict 回环；planner 契约示例
  过引擎验收（防契约与实现漂移）。

引擎行为测试用 FakePage 替身（request 事件注册/摘除 + wait_for_timeout 真实
让出事件循环），不启 playwright；静默窗常量经 mock.patch 缩短保证测试速度，
默认值（design 钉死约 300ms）由专项 pin 测试锁定。
"""

import asyncio
import logging
import unittest
from unittest import mock

from core.verify_engine import browser as browser_mod
from core.verify_engine.browser import BrowserManager
from core.verify_engine.scenarios import (
    EXPECT_NETWORK_RE_PREFIX,
    INTERACTIVE_WEB_ACTIONS,
    TestScenario,
    TestStep,
    url_matches_network_pattern,
    validate_expect_network_form,
    validate_scenario_dicts,
)

# 单测缩窗后的静默窗/封顶（毫秒）：行为测试跑得快，默认值由 pin 测试锁定
_QUIET_MS = 50
_QUIET_MAX_MS = 500

MATCH_PATTERN = "/api/command-center/pipeline"
MATCH_URL = "https://app.example.com:8000/api/command-center/pipeline?window=1"


class _FakeRequest:
    def __init__(self, url: str):
        self.url = url


class FakePage:
    """最小 page 替身：request 事件注册/摘除 + wait_for_timeout 真实让出。

    emit_request 同步派发给已注册监听器（与 playwright 事件回调同形：
    handler(request)）；schedule_request 延迟后派发，用于驱动「尾部延迟
    请求」时序。
    """

    def __init__(self):
        self._listeners = {}

    def on(self, event, handler):
        self._listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        handlers = self._listeners.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    async def wait_for_timeout(self, timeout_ms):
        await asyncio.sleep(timeout_ms / 1000.0)

    def emit_request(self, url):
        for handler in list(self._listeners.get("request", [])):
            handler(_FakeRequest(url))

    def schedule_request(self, url, delay_s):
        async def _fire():
            await asyncio.sleep(delay_s)
            self.emit_request(url)

        return asyncio.ensure_future(_fire())


def _net_step(**overrides):
    """带 expect_network 的 wait 步骤（wait 无需 target，执行即 5ms 暂停）。"""
    step = {
        "action": "wait",
        "value": "5",
        "expect_network": [{"url_pattern": MATCH_PATTERN, "min_count": 1}],
    }
    step.update(overrides)
    return step


class ExpectNetworkEngineTest(unittest.TestCase):
    """引擎执行窗口行为（task 1.2 ①②③④）。"""

    def setUp(self):
        self.browser = BrowserManager()
        self.page = FakePage()
        patchers = [
            mock.patch.object(browser_mod, "_EXPECT_NETWORK_QUIET_MS", _QUIET_MS),
            mock.patch.object(
                browser_mod, "_EXPECT_NETWORK_QUIET_MAX_MS", _QUIET_MAX_MS
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _run(self, coro):
        return asyncio.run(coro)

    # ① 窗口内 1 个匹配请求 → 通过，且报告该步骤含网络断言通过记录
    def test_single_matching_request_passes(self):
        step = _net_step()

        async def main():
            self.page.schedule_request(MATCH_URL, 0.01)
            return await self.browser.execute_action(self.page, step)

        result = self._run(main())
        self.assertTrue(result["success"], result.get("error"))
        records = result["network_assertions"]
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["pass"])
        self.assertEqual(records[0]["actual_count"], 1)
        self.assertEqual(records[0]["min_count"], 1)
        self.assertEqual(records[0]["url_pattern"], MATCH_PATTERN)

    # ② 零匹配 → fail，明细含「期望 ≥1 实际 0」，场景计入 fail
    # （web_runner 对 success=False 的步骤 steps_failed → determine_scenario_status
    # 判 fail，该链路单测见 test_verify_screenshot_timing 既有口径，此处断言
    # 步骤置败 + 明细内容）
    def test_zero_match_fails_with_counts(self):
        result = self._run(self.browser.execute_action(self.page, _net_step()))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "expect_network_failed")
        record = result["network_assertions"][0]
        self.assertFalse(record["pass"])
        self.assertEqual(record["actual_count"], 0)
        # spec 明细措辞：「期望 ≥1 实际 0」
        self.assertIn("期望 ≥1 实际 0", record["message"])
        self.assertIn("期望 ≥1 实际 0", result["error"])
        # 零捕获 → 样例为空提示（不携带 samples 键 + message 内空样例提示）
        self.assertEqual(record.get("samples", []), [])
        self.assertIn("（无）", record["message"])

    # ③ 窗口尾部静默等待生效：交互标记完成后才入栈的延迟请求不漏计
    def test_delayed_tail_request_is_counted(self):
        # 动作本身 5ms 完成；请求在动作完成后 ~25ms（第一静默窗内）入栈——
        # 无收尾静默等待的实现会在动作结束即断言，actual=0 误判失败
        step = _net_step()

        async def main():
            self.page.schedule_request(MATCH_URL, 0.03)
            return await self.browser.execute_action(self.page, step)

        result = self._run(main())
        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["network_assertions"][0]["actual_count"], 1)

    # ④ 非匹配 URL 不计入：噪声请求不影响计数，匹配按模式单点判定
    def test_non_matching_urls_not_counted(self):
        noise = [
            "https://cdn.example.com/static/app.js",
            "https://app.example.com:8000/api/stream",
        ]
        # 4a：只有噪声 → 匹配计数 0 → 步骤失败，样例展示窗口内实际请求
        async def only_noise():
            for i, url in enumerate(noise):
                self.page.schedule_request(url, 0.005 * (i + 1))
            return await self.browser.execute_action(self.page, _net_step())
        result = self._run(only_noise())
        self.assertFalse(result["success"])
        record = result["network_assertions"][0]
        self.assertEqual(record["actual_count"], 0)
        self.assertEqual(record.get("samples", []), noise)

        # 4b：噪声 + 1 个匹配 → 匹配计数 1（噪声不计入）→ 通过
        async def noise_plus_match():
            for i, url in enumerate(noise):
                self.page.schedule_request(url, 0.005 * (i + 1))
            self.page.schedule_request(MATCH_URL, 0.02)
            return await self.browser.execute_action(self.page, _net_step())

        result = self._run(noise_plus_match())
        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["network_assertions"][0]["actual_count"], 1)

    # re: 前缀正则模式（design D2：与既有断言器风格对齐）
    def test_regex_prefix_pattern(self):
        step = _net_step(
            expect_network=[{"url_pattern": f"{EXPECT_NETWORK_RE_PREFIX}/api/command-ce.ter/.*pipeline", "min_count": 1}]
        )

        async def main():
            self.page.schedule_request(MATCH_URL, 0.01)
            return await self.browser.execute_action(self.page, step)

        result = self._run(main())
        self.assertTrue(result["success"], result.get("error"))

    # 交互本身失败 → 按步骤原失败返回，不叠加网络断言明细（归因不混淆）
    def test_action_failure_skips_network_assertion(self):
        step = _net_step(action="click", target="")  # click 缺 target → 结构化失败

        async def main():
            self.page.schedule_request(MATCH_URL, 0.01)
            return await self.browser.execute_action(self.page, step)

        result = self._run(main())
        self.assertFalse(result["success"])
        self.assertNotIn("network_assertions", result)
        self.assertNotEqual(result.get("error_type"), "expect_network_failed")

    # 监听器收窗即摘：同 page 跨步骤复用不泄漏（后续步骤请求不再入旧窗口）
    def test_listener_detached_after_window(self):
        self._run(self.browser.execute_action(self.page, _net_step()))
        self.assertEqual(self.page._listeners.get("request", []), [])
        self.page.emit_request(MATCH_URL)  # 摘除后派发不进任何捕获、不抛

    # 条目形态非法（直构 TestStep 绕过验收的残档）→ 该项失败，不假通过
    def test_malformed_entry_fails_conservatively(self):
        result = self._run(
            self.browser.execute_action(self.page, _net_step(expect_network="click"))
        )
        self.assertFalse(result["success"])
        self.assertIn("必须为列表", result["network_assertions"][0]["message"])


class ExpectNetworkQuietWindowPinTest(unittest.TestCase):
    """静默窗默认值 pin（design Risks：固定短静默窗约 300ms，单测钉死）。"""

    def test_default_quiet_window_is_300ms(self):
        self.assertEqual(browser_mod._EXPECT_NETWORK_QUIET_MS, 300)
        # 封顶必须大于单轮静默窗（否则静默收敛判定永远走不到）
        self.assertGreater(browser_mod._EXPECT_NETWORK_QUIET_MAX_MS, 300)
        self.assertEqual(browser_mod._EXPECT_NETWORK_SAMPLE_LIMIT, 3)


# ── 契约校验（task 2.2）───────────────────────────────────────────

_NAV = {"action": "navigate", "value": "https://app.example.com:8000/"}


def _scenario(steps, sid="net-assert"):
    return {"id": sid, "description": "网络断言验收", "steps": steps, "assertions": []}


def _valid_click(**overrides):
    step = {
        "action": "click",
        "target": "[data-testid='project-filter']",
        "expect_network": [{"url_pattern": MATCH_PATTERN, "min_count": 1}],
    }
    step.update(overrides)
    return step


class ExpectNetworkValidationTest(unittest.TestCase):
    def _validate(self, steps, sid="net-assert"):
        return TestScenario.from_dict(_scenario(steps, sid)).validate()

    # ① 合法形态过验收
    def test_valid_form_passes(self):
        self.assertEqual(self._validate([dict(_NAV), _valid_click()]), [])

    # ② 非交互步骤携带被拒（验收错误，非运行时失败），错误指向该步骤
    def test_non_interactive_step_rejected(self):
        for action_step in (
            dict(_NAV, expect_network=[{"url_pattern": MATCH_PATTERN, "min_count": 1}]),
            {"action": "wait", "value": "100", "expect_network": [{"url_pattern": MATCH_PATTERN, "min_count": 1}]},
            {"action": "mock_api", "target": "**/api/x", "value": "{}", "expect_network": [{"url_pattern": MATCH_PATTERN, "min_count": 1}]},
        ):
            errors = self._validate([dict(_NAV), action_step])
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("非交互操作", errors[0])
            self.assertIn("expect_network", errors[0])
            self.assertIn("场景'net-assert'步骤1", errors[0])

    # ③ 非法形态逐条报错（url_pattern 非空 + min_count 正整数，同条目双错齐报）
    def test_illegal_form_reports_per_entry(self):
        errors = self._validate(
            [dict(_NAV), _valid_click(expect_network=[{"url_pattern": "", "min_count": 0}])]
        )
        joined = "\n".join(errors)
        self.assertIn("url_pattern 须为非空字符串", joined)
        self.assertIn("min_count 须为正整数", joined)
        self.assertIn("场景'net-assert'步骤1expect_network", joined)

        # 非 dict 条目 / 非列表字段 / 坏正则逐条定位
        errors = self._validate(
            [dict(_NAV), _valid_click(expect_network=["/api/command-center/pipeline"])]
        )
        self.assertTrue(any("条目0: 须为对象" in e for e in errors), errors)

        errors = self._validate(
            [dict(_NAV), _valid_click(expect_network={"url_pattern": MATCH_PATTERN})]
        )
        self.assertTrue(any("必须为列表" in e for e in errors), errors)

        errors = self._validate(
            [dict(_NAV), _valid_click(expect_network=[{"url_pattern": "re:([", "min_count": 1}])]
        )
        self.assertTrue(any("正则编译失败" in e for e in errors), errors)

        # bool 是 int 子类，显式拒绝（口径同 _parse_viewport）
        errors = self._validate(
            [dict(_NAV), _valid_click(expect_network=[{"url_pattern": MATCH_PATTERN, "min_count": True}])]
        )
        self.assertTrue(any("min_count 须为正整数" in e for e in errors), errors)

    # ④ min_count > 3 落 WARNING 不拒绝（经 scenarios 模块 logger 落验证日志）
    def test_min_count_above_three_warns_without_reject(self):
        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        cap_logger = logging.getLogger("core.verify_engine.scenarios")
        cap_logger.addHandler(handler)
        try:
            errors = self._validate(
                [dict(_NAV), _valid_click(expect_network=[{"url_pattern": MATCH_PATTERN, "min_count": 5}])]
            )
        finally:
            cap_logger.removeHandler(handler)
        self.assertEqual(errors, [])
        self.assertTrue(
            any(r.levelno == logging.WARNING and "min_count=5" in r.getMessage() for r in records),
            records,
        )


# ── 形态定义单点与回环（task 1.1 配套 + design D3 单点）─────────────


class ExpectNetworkFormUnitTest(unittest.TestCase):
    def test_url_matches_network_pattern(self):
        self.assertTrue(url_matches_network_pattern(MATCH_URL, MATCH_PATTERN))
        self.assertFalse(url_matches_network_pattern("https://x/api/other", MATCH_PATTERN))
        self.assertTrue(url_matches_network_pattern(MATCH_URL, "re:/api/command-ce.ter/"))
        self.assertFalse(url_matches_network_pattern("https://x/api/other", "re:/api/command-ce.ter/"))
        # 防御：非法 pattern 按不匹配收场，引擎侧永不抛
        self.assertFalse(url_matches_network_pattern(MATCH_URL, ""))
        self.assertFalse(url_matches_network_pattern(MATCH_URL, "re:(["))
        self.assertFalse(url_matches_network_pattern(None, MATCH_PATTERN))

    def test_validate_expect_network_form_shape(self):
        errs, warns = validate_expect_network_form(
            [{"url_pattern": MATCH_PATTERN, "min_count": 1}]
        )
        self.assertEqual((errs, warns), ([], []))
        errs, warns = validate_expect_network_form(
            [{"url_pattern": MATCH_PATTERN, "min_count": 4}]
        )
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 1)
        self.assertIn("min_count=4", warns[0])

    def test_teststep_expect_network_roundtrip(self):
        step = TestStep.from_dict(_valid_click())
        self.assertEqual(
            step.expect_network, [{"url_pattern": MATCH_PATTERN, "min_count": 1}]
        )
        d = step.to_dict()
        self.assertIn("expect_network", d)
        again = TestStep.from_dict(d)
        self.assertEqual(again.expect_network, step.expect_network)

    def test_teststep_without_field_stays_clean(self):
        # 无该字段的步骤（存量场景）from_dict/to_dict 行为逐位不变
        step = TestStep.from_dict({"action": "click", "target": "#a"})
        self.assertEqual(step.expect_network, [])
        self.assertNotIn("expect_network", step.to_dict())

    def test_scenario_roundtrip_keeps_expect_network(self):
        scenario = TestScenario.from_dict(_scenario([dict(_NAV), _valid_click()]))
        d = scenario.to_dict()
        self.assertIn("expect_network", d["steps"][1])
        again = TestScenario.from_dict(d)
        self.assertEqual(again.steps[1].expect_network, scenario.steps[1].expect_network)

    def test_interactive_action_set_matches_design(self):
        # design D3 显式集：交互 = WEB_ACTIONS - {navigate, wait, seed, mock_api}
        from core.verify_engine.scenarios import WEB_ACTIONS

        self.assertEqual(
            INTERACTIVE_WEB_ACTIONS, frozenset(WEB_ACTIONS - {"navigate", "wait", "seed", "mock_api"})
        )


# ── planner 契约示例过引擎验收（task 3.2）─────────────────────────


class PlannerContractExampleGateTest(unittest.TestCase):
    """契约示例作为验收用例跑通：防契约段示例与实现漂移。

    示例逐字取自 agents/planner-plan.md「交互后网络请求断言」节——
    契约段变更须同步更新此处（或反向）。
    """

    CONTRACT_EXAMPLE = {
        "id": "contract-example-pipeline-filter-refetch",
        "description": "点击项目筛选后应重拉 pipeline 数据（契约示例）",
        "steps": [
            {"action": "navigate", "value": "https://app.example.com:8000/"},
            {
                "action": "click",
                "target": "[data-testid='project-filter']",
                "expect_network": [
                    {"url_pattern": "/api/command-center/pipeline", "min_count": 1}
                ],
            },
        ],
        "assertions": [],
    }

    def test_contract_example_passes_acceptance(self):
        # 场景写端 schema 门单源（planner 产物收编同一校验链）
        self.assertEqual(validate_scenario_dicts([self.CONTRACT_EXAMPLE]), [])

    def test_contract_example_step_roundtrips(self):
        scenario = TestScenario.from_dict(self.CONTRACT_EXAMPLE)
        d = scenario.to_dict()
        self.assertEqual(
            d["steps"][1]["expect_network"],
            [{"url_pattern": "/api/command-center/pipeline", "min_count": 1}],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
