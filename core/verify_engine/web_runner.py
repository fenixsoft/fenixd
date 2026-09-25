"""
web_runner.py — WebRunner：浏览器驱动场景执行

对应 verify-runner-engine PR1「等价重构」：把原 engine.py 的浏览器相关逻辑
整体归位到独立 Runner（BrowserManager 生命周期、extension 健康检查、
per-scenario context、console/network 错误注入、截图取证、视觉对比、推流
探针），**行为不变**——web 场景改造前后的场景结果
（status/step_results/assertion_results/screenshots）语义一致。

navigate 绝对 URL 硬要求随迁至 WebRunner.validate（经 scenarios.validate_scenario
公共入口，词表权威源唯一）。

调度器不得含 per-kind 执行分支：本 Runner 只经 VerifyRunner 接口被引擎调用，
引擎不感知本模块内部细节。
"""

import re
from urllib.parse import urlsplit

from .runner import VerifyRunner, register_runner, determine_scenario_status
from .browser import BrowserManager
from .assertions import AssertionRunner
from .visual_diff import VisualDiffer
from .env_gate import probe_http_health
from .scenarios import validate_scenario


def locate_app_base_url(candidates: list) -> str:
    """从候选场景的 navigate 步骤定位被测应用入口（契约 base_url 缺省回退）。

    navigate 失败（如 ERR_CONNECTION_REFUSED）时 URL 在 error 而非 detail——
    只扫 detail 会漏掉失联场景，探针保守判健康，整轮伪失败无法降级 blocked-env
    （add-v3-spec-detail-page 教训）。
    """
    for r in candidates:
        for step in r.get("step_results") or []:
            if not isinstance(step, dict) or step.get("action") != "navigate":
                continue
            detail = f"{step.get('detail') or ''} {step.get('error') or ''}"
            # 排除集含全角标点：中文文案 URL 直接衔接全角标点时不得并入 netloc，
            # 否则 urlsplit 后 base_url 带尾巴、探针误判环境失联。
            m = re.search(r"(https?://[^\s'\");，。、；：？！）】》」』]+)", detail)
            if m:
                url = m.group(1).rstrip("/")
                parts = urlsplit(url)
                if parts.scheme and parts.netloc:
                    return f"{parts.scheme}://{parts.netloc}"
    return ""


@register_runner
class WebRunner(VerifyRunner):
    """浏览器驱动 Runner（playwright 异步 API，单浏览器多 context）。"""

    kind = "web"

    def __init__(self, spec_name, project_root=None, logger=None, config: dict = None, **kwargs):
        super().__init__(spec_name, project_root, logger, config, **kwargs)
        self.browser = BrowserManager(project_root=project_root, logger=self.logger)
        self.asserter = AssertionRunner()
        # 视觉对比器持有配置（settle 上限 / 重拍次数，verify_engine 段，
        # 缺省回退），见 visual_diff.py D6 配置读取。
        self.differ = VisualDiffer(spec_name, project_root, config=config, logger=self.logger)
        # 契约统一供给的 base_url（引擎注入；优先级高于 navigate 文本考古）。
        # 无实例形态（纯 CLI 轮次）下为空字符串，改写/探针为无害空操作。
        self.base_url = ""
        verify_cfg = (config or {}).get("verify_engine", {})
        self.headless = verify_cfg.get("headless", True)
        self._setup_health_ok = True

    @staticmethod
    def _extract_screenshot_result(ss) -> tuple:
        """兼容 browser.screenshot() 新旧两种返回形态。

        新形态（screenshot-evidence-labeling，design D1）：dict
        {"path": str, "labels": dict}；旧形态 / 测试 mock：纯字符串路径。
        统一返回 (path, labels)，labels 为空 dict 表示无标签（正常截图）。
        """
        if isinstance(ss, dict):
            path = ss.get("path") or ""
            labels = ss.get("labels") if isinstance(ss.get("labels"), dict) else {}
            return path, labels
        return ss or "", {}

    # ── 场景验收 ───────────────────────────────────────────────

    def validate(self, scenario) -> list[str]:
        """web 词表校验（含 navigate 绝对 URL 硬要求，随迁自 engine 验收门）。"""
        return validate_scenario(scenario)

    # ── 生命周期 ───────────────────────────────────────────────

    async def setup(self):
        """启动浏览器（单例）。扩展项目自动起本地 HTTP 服务器并做健康检查。"""
        await self.browser.start(headless=self.headless)
        self._setup_health_ok = True
        self._setup_health_reason = ""
        if self.browser.is_extension_project:
            health_ok, health_reason = await self._perform_health_check()
            self._setup_health_ok = health_ok
            self._setup_health_reason = health_reason
            if not health_ok:
                self.logger.error(
                    "verify_engine",
                    "扩展应用页面加载失败，无法执行场景验证",
                )

    async def teardown(self):
        await self.browser.stop()

    # ── 场景执行 ───────────────────────────────────────────────

    async def execute(self, scenario) -> dict:
        """执行单个 web 场景：context/page 隔离 + 步骤 + 断言 + 截图 + 视觉。"""
        # 扩展项目健康检查失败 → 全部场景 error（不逐个白跑），
        # error 携带健康检查的真实失败原因（区分成因），reason 缺失时
        # 回落到原通用文案，避免文案缺失
        if not getattr(self, "_setup_health_ok", True):
            reason = getattr(self, "_setup_health_reason", "") or ""
            return {
                "scenario_id": scenario.id,
                "kind": scenario.kind,
                "description": scenario.description,
                "status": "error",
                "error": reason
                or "应用页面加载失败：.fenix-dashboard 元素不存在，"
                "请确认 dist/ 构建产物完整",
                "step_results": [],
                "assertion_results": [],
                "visual_results": [],
                "screenshots": [],
                "screenshot_labels": {},
            }
        context = await self.browser.new_context(viewport=getattr(scenario, "viewport", None))
        try:
            page = await context.new_page()
            # 扩展项目：确保页面已加载应用内容（不依赖场景的 navigate 步骤）
            # 非扩展项目由场景自身的 navigate 步骤负责
            if self.browser.is_extension_project:
                nav_ok = await self.browser.navigate_to_app(page)
                if not nav_ok:
                    self.logger.warning(
                        "verify_engine",
                        f"场景'{scenario.id}': navigate_to_app 失败，页面可能为空白",
                    )
            return await self._execute_scenario(scenario, page, context)
        finally:
            await context.close()

    async def _perform_health_check(self) -> tuple:
        """场景执行前健康检查：验证应用页面是否能成功加载。

        创建独立的 context/page，导航到应用并等待 .fenix-dashboard 出现。
        若预检失败，所有场景都会因同一原因失败，无需逐个执行。

        Returns:
            (ok, reason) 二元组：ok 为 True 表示应用页面加载成功
            （.fenix-dashboard 在 DOM 中可见，reason 为空串）；失败时
            reason 携带区分成因的失败原因文案（导航失败/元素未出现/
            检查异常），供场景 error 直接引用，避免一律归因 dist/。
        """
        try:
            context = await self.browser.new_context()
            page = await context.new_page()
            try:
                nav_ok = await self.browser.navigate_to_app(page)
                if not nav_ok:
                    try:
                        current_url = page.url
                        html_len = await page.evaluate(
                            "() => document.documentElement.outerHTML.length"
                        )
                    except Exception:
                        current_url = "unknown"
                        html_len = "unknown"
                    self.logger.warning(
                        "verify_engine",
                        f"健康检查失败: navigate_to_app 返回 False "
                        f"(当前URL={current_url}, HTML长度={html_len})",
                    )
                    return False, (
                        f"应用页面加载失败：无法导航到应用页面 "
                        f"(当前URL={current_url}, HTML长度={html_len})，"
                        f"请确认本地 HTTP 服务已启动且可达"
                    )

                try:
                    await page.wait_for_selector(
                        ".fenix-dashboard",
                        state="visible",
                        timeout=10000,
                    )
                    self.logger.info("verify_engine", "健康检查通过: .fenix-dashboard 已出现")
                    return True, ""
                except Exception:
                    try:
                        current_url = page.url
                        root_html = await page.evaluate(
                            "() => document.getElementById('root')?.innerHTML?.substring(0, 200) || '(empty)'"
                        )
                    except Exception:
                        current_url = "unknown"
                        root_html = "unknown"
                    self.logger.warning(
                        "verify_engine",
                        f"健康检查失败: .fenix-dashboard 在 10 秒内未出现 "
                        f"(当前URL={current_url}, #root内容={root_html})",
                    )
                    return False, (
                        "应用页面加载失败：.fenix-dashboard 元素不存在，"
                        "请确认 dist/ 构建产物完整"
                    )
            finally:
                await context.close()
        except Exception as e:
            self.logger.warning(
                "verify_engine",
                f"健康检查异常: {type(e).__name__}: {e}",
            )
            return False, f"健康检查异常: {type(e).__name__}: {e}"

    async def _execute_scenario(self, scenario, page, context) -> dict:
        """执行单个测试场景的所有步骤和断言（搬运自 engine._execute_scenario）。"""
        self.logger.debug("verify_engine", f"  执行场景: {scenario.id}")

        step_results: list[dict] = []
        screenshots: list[str] = []
        screenshot_labels: dict[str, dict] = {}
        screenshot_dir = (
            self.project_root / ".fenix" / "verify-progress" / self.spec_name / "screenshots"
        )

        # ── 执行操作步骤 ──
        steps_failed = False
        for i, step in enumerate(scenario.steps):
            step_dict = step.to_dict()

            result = await self.browser.execute_action(page, step_dict)
            step_results.append(result)

            # 操作失败即停止后续步骤，且跳过断言执行（断言「根本没进行」）。
            # 此时不截图：截图只在断言真正执行且失败时发生（见下方），
            # 避免环境未正确加载时对同一错误页面产生重复取证。
            if not result.get("success"):
                steps_failed = True
                break

            # 标记为关键步骤的成功操作：按场景声明截图
            if step_dict.get("screenshot", False):
                try:
                    ss = await self.browser.screenshot(
                        page, f"{scenario.id}_step{i}", screenshot_dir
                    )
                    path, labels = self._extract_screenshot_result(ss)
                    screenshots.append(path)
                    if labels:
                        screenshot_labels.setdefault(path, {}).update(labels)
                except Exception as exc:
                    self.logger.warning(
                        "verify_engine",
                        f"场景'{scenario.id}': 关键步骤截图取证失败: {repr(exc)[:200]}",
                    )

        # ── 运行断言（步骤失败 → 断言未进行，跳过）──
        assertion_defs = [a.to_dict() for a in scenario.assertions]

        # 注入运行时数据（console/network错误 + 场景级外部 API 网络豁免标记）
        for a_def in assertion_defs:
            if a_def.get("type") == "no_console_error":
                a_def["_console_errors"] = self.browser.get_console_errors(context)
                a_def["_external_net_errors_ok"] = scenario.external_net_errors_ok
            if a_def.get("type") == "no_network_error":
                a_def["_network_errors"] = self.browser.get_network_errors(context)

        assertion_results: list[dict] = []
        if not steps_failed:
            assertion_results = await self.asserter.run(page, assertion_defs)

            # 断言真正执行且至少一个失败 → 截图取证（真实产品缺陷）。
            # 断言全部通过则不截图。步骤失败已在上方 break，不进入此分支。
            if any(not a.get("pass", True) for a in assertion_results):
                try:
                    ss = await self.browser.screenshot(
                        page, f"{scenario.id}_assert_fail", screenshot_dir
                    )
                    path, labels = self._extract_screenshot_result(ss)
                    screenshots.append(path)
                    if labels:
                        screenshot_labels.setdefault(path, {}).update(labels)
                except Exception as exc:
                    self.logger.warning(
                        "verify_engine",
                        f"场景'{scenario.id}': 断言失败取证截图失败: {repr(exc)[:200]}",
                    )

        # ── 视觉对比 ──
        visual_results: list[dict] = []
        if scenario.visual_baseline:
            try:
                # 传场景通过性上下文（steps_failed + 断言结果）：基线固化门
                # 仅在该场景步骤/断言全过时固化，否则 baseline_deferred 顺延
                # （fix-visual-baseline-settle D3）；污染基线侦测据此判定
                # 「diff_detected 是否伴随 DOM 全过」。
                visual_results = await self.differ.compare(
                    page,
                    scenario.visual_baseline,
                    scenario.id,
                    scenario_context={
                        "steps_failed": steps_failed,
                        "step_results": step_results,
                        "assertion_results": assertion_results,
                    },
                )
            except Exception as e:
                visual_results = [
                    {
                        "baseline": scenario.visual_baseline,
                        "status": "error",
                        "ssim": None,
                        "pass": False,
                        "error": str(e),
                    }
                ]

        # ── 判定场景状态 ──
        status = determine_scenario_status(step_results, assertion_results, visual_results)

        return {
            "scenario_id": scenario.id,
            "description": scenario.description,
            "kind": scenario.kind,
            "status": status,
            "step_results": step_results,
            "assertion_results": assertion_results,
            "visual_results": visual_results,
            "screenshots": screenshots,
            # screenshot-evidence-labeling（design D1）：截图健全性算法标签，
            # 引擎侧随场景结果持久化进 report.json 供 judge/校验器读取。
            # 向后兼容：旧 browser.screenshot 返回纯字符串路径时为空 dict。
            "screenshot_labels": screenshot_labels,
        }

    # ── 环境探针 ───────────────────────────────────────────────

    async def probe_env(self, candidates: list[dict]) -> dict:
        """环境健全性探针：连通 + 推流检查（web 语义，委托模块探针函数）。"""
        return await probe_web_environment(
            self.browser,
            candidates,
            project_root=self.project_root,
            logger=self.logger,
            base_url=self.base_url,
        )


async def _probe_web_push(browser) -> bool:
    """在真实浏览器中验证数据推流：加载应用并等待数据域渲染。

    mock 斩断 SSE 时数据节点永不渲染 → 等待超时 → 判定推流中断。
    复用 browser.navigate_to_app + wait_selector，与场景执行同一浏览器实例。
    """
    context = await browser.new_context()
    page = await context.new_page()
    try:
        nav_ok = await browser.navigate_to_app(page)
        if not nav_ok:
            return False
        try:
            await page.wait_for_selector(
                ".fenix-dashboard [data-live], .fenix-dashboard [data-state], " "#root [data-live]",
                timeout=3000,
            )
            return True
        except Exception:
            return False
    finally:
        await context.close()


async def probe_web_environment(
    browser, candidates, project_root=None, logger=None, base_url: str = ""
) -> dict:
    """环境健全性探针：连通 + 推流检查（与旧 engine._run_environment_probe
    同行为）。WebRunner.probe_env 与引擎回退路径共用。

    1) HTTP 连通性 + 数据端点（dashboard /api/state 等价端点）探测；
    2) 扩展项目额外做真实页面推流检查（DOM 数据域是否渲染）。
    探针本身无法完成（无入口/异常）时保守判健康，避免误降级真缺陷。
    优先使用契约统一供给的 base_url；无实例形态下为空，落回 navigate
    文本考古（locate_app_base_url）。
    """
    base = base_url or browser.base_url
    detail = ""
    healthy = True
    if not base and project_root:
        base = locate_app_base_url(candidates)
    if base:
        healthy = probe_http_health(base, timeout=2.0)
        detail = f"HTTP 探测 {base}: {'连通' if healthy else '失联'}"
    # 推流检查（扩展项目 / 浏览器可用时）
    if healthy and browser.is_extension_project:
        try:
            push_ok = await _probe_web_push(browser)
            healthy = healthy and push_ok
            detail += f"；推流{'正常' if push_ok else '中断'}"
        except Exception as e:
            if logger:
                logger.debug("verify_engine", f"推流检查不可用，跳过: {e}")
    return {"healthy": healthy, "detail": detail.strip("；")}
