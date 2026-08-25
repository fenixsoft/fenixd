"""
engine.py — 验证引擎主控

职责：
  - 接收测试场景列表，驱动浏览器并行执行
  - 对所有场景运行DOM断言和视觉对比
  - 汇总生成结构化验证报告

并行策略（默认）：
  - 拓扑排序：按 depends_on 声明分层层级
  - 同层并行：依赖已满足的场景通过 asyncio.gather + Semaphore 并发
  - 信号量控制：max_parallel 限制同时运行的场景数（默认5）
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .browser import BrowserManager
from .assertions import AssertionRunner
from .visual_diff import VisualDiffer
from .scenarios import TestScenario


class VerifyEngine:
    """验证引擎主控。

    流程：
    1. 加载测试场景（从JSON或直接传入）
    2. 启动浏览器（单例）
    3. 拓扑排序 → 并行执行场景
    4. 每个场景：执行步骤 → DOM断言 → 视觉对比
    5. 汇总报告
    6. 停止浏览器
    """

    def __init__(
        self,
        spec_name: str,
        project_root: Path,
        logger=None,
        config: Optional[dict] = None,
    ):
        self.spec_name = spec_name
        self.project_root = project_root
        self.logger = logger or _NullLogger()
        self.browser = BrowserManager(project_root=project_root, logger=self.logger)
        self.asserter = AssertionRunner()
        self.differ = VisualDiffer(spec_name, project_root)

        # 并行度配置
        verify_cfg = (config or {}).get("verify_engine", {})
        self.max_parallel = verify_cfg.get("max_parallel", 5)
        self.headless = verify_cfg.get("headless", True)

    async def run(self, scenarios: list) -> dict:
        """主入口。

        Args:
            scenarios: TestScenario 对象列表 或 dict 列表
                       如果传入dict，会自动做 from_dict 转换

        Returns:
            report dict，结构:
            {
                "spec": str,
                "timestamp": iso8601,
                "summary": {total, passed, warnings, failed},
                "scenarios": [{...}, ...],
            }
        """
        # 规范化场景
        normalized = []
        for s in scenarios:
            if isinstance(s, TestScenario):
                normalized.append(s)
            elif isinstance(s, dict):
                normalized.append(TestScenario.from_dict(s))
            else:
                self.logger.warning(
                    "verify_engine",
                    f"跳过非场景对象: {type(s).__name__}",
                )

        self.logger.info(
            "verify_engine",
            f"🚀 开始验证 '{self.spec_name}': "
            f"{len(normalized)} 个场景, 并行度={self.max_parallel}",
        )

        await self.browser.start(headless=self.headless)

        try:
            results = await self._execute_parallel(normalized)
        finally:
            await self.browser.stop()

        report = self._build_report(results)
        self._save_report(report)

        # 验证完成，进度更新到 100%
        total = report["summary"]["total"]
        self._write_progress(total, total,
                             f"验证完成: {report['summary']['passed']}通过, "
                             f"{report['summary']['failed']}失败, "
                             f"{report['summary']['errors']}错误")

        return report

    # ── 并行执行引擎 ───────────────────────────────────────────

    async def _execute_parallel(self, scenarios: list[TestScenario]) -> list[dict]:
        """按依赖关系分层，同层场景通过信号量控制的并发池并行执行。"""
        # ── 场景执行前健康检查 ──
        # 健康检查仅对扩展项目做硬阻断：扩展项目的场景依赖 navigate_to_app
        # 自动注入应用页面，若加载失败则所有场景必然失败。
        # 非扩展项目（如自带 HTTP 服务的 Web 应用）由场景自身的 navigate
        # 步骤负责加载页面，健康检查不做前置阻断。
        if self.browser.is_extension_project:
            health_ok = await self._perform_health_check()
            if not health_ok:
                self.logger.error(
                    "verify_engine",
                    "扩展应用页面加载失败，无法执行场景验证",
                )
                return [
                    {
                        "scenario_id": s.id,
                        "description": s.description,
                        "status": "error",
                        "error": "应用页面加载失败：.fenix-dashboard 元素不存在，"
                                 "请确认 dist/ 构建产物完整",
                        "step_results": [],
                        "assertion_results": [],
                        "visual_results": [],
                        "screenshots": [],
                    }
                    for s in scenarios
                ]
        else:
            self.logger.info(
                "verify_engine",
                "非扩展项目，跳过前置健康检查（场景自行导航）",
            )

        semaphore = asyncio.Semaphore(self.max_parallel)
        results: list[dict] = []
        completed_ids: set[str] = set()
        remaining = list(scenarios)
        batch_num = 0

        while remaining:
            # 找出所有依赖已满足的场景
            ready = [
                s for s in remaining
                if all(dep in completed_ids for dep in s.depends_on)
            ]

            if not ready:
                # 可能循环依赖或所有场景无依赖，直接全部执行
                ready = remaining

            batch_num += 1
            self.logger.info(
                "verify_engine",
                f"📦 批次{batch_num}: 并行执行 {len(ready)} 个场景",
            )

            async def run_one(scenario: TestScenario) -> dict:
                async with semaphore:
                    context = await self.browser.new_context()
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
                    try:
                        return await self._execute_scenario(scenario, page, context)
                    finally:
                        await context.close()

            batch_results = await asyncio.gather(
                *[run_one(s) for s in ready],
                return_exceptions=True,
            )

            for i, r in enumerate(batch_results):
                sid = ready[i].id
                completed_ids.add(sid)
                if isinstance(r, Exception):
                    self.logger.error("verify_engine", f"场景'{sid}'异常: {r}")
                    results.append({
                        "scenario_id": sid,
                        "status": "error",
                        "error": str(r),
                    })
                else:
                    results.append(r)

            # 每批次完成后更新进度文件，供仪表盘实时展示
            self._write_progress(len(completed_ids), len(scenarios),
                                 f"批次{batch_num}完成: {ready[-1].id if ready else '?'}")

            remaining = [s for s in remaining if s.id not in completed_ids]

        return results

    async def _perform_health_check(self) -> bool:
        """场景执行前健康检查：验证应用页面是否能成功加载。

        创建独立的 context/page，导航到应用并等待 .fenix-dashboard 出现。
        若预检失败，所有场景都会因同一原因失败，无需逐个执行。

        Returns:
            True 表示应用页面加载成功（.fenix-dashboard 在 DOM 中可见）
        """
        try:
            context = await self.browser.new_context()
            page = await context.new_page()
            try:
                nav_ok = await self.browser.navigate_to_app(page)
                if not nav_ok:
                    # 增强诊断：记录页面 URL 和 HTML 长度
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
                    return False

                # 等待应用根容器出现（Playwright auto-wait，最多 10 秒）
                try:
                    await page.wait_for_selector(
                        ".fenix-dashboard",
                        state="visible",
                        timeout=10000,
                    )
                    self.logger.info("verify_engine", "健康检查通过: .fenix-dashboard 已出现")
                    return True
                except Exception:
                    # 增强诊断：记录页面 URL 和 #root 内容
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
                    return False
            finally:
                await context.close()
        except Exception as e:
            self.logger.warning(
                "verify_engine",
                f"健康检查异常: {type(e).__name__}: {e}",
            )
            return False

    async def _execute_scenario(
        self, scenario: TestScenario, page, context
    ) -> dict:
        """执行单个测试场景的所有步骤和断言。"""
        self.logger.debug("verify_engine", f"  执行场景: {scenario.id}")

        step_results: list[dict] = []
        screenshots: list[str] = []
        screenshot_dir = (
            self.project_root / ".fenix" / "verify-progress"
            / self.spec_name / "screenshots"
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
                    screenshots.append(ss)
                except Exception:
                    pass

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
                    screenshots.append(ss)
                except Exception:
                    pass

        # ── 视觉对比 ──
        visual_results: list[dict] = []
        if scenario.visual_baseline:
            try:
                visual_results = await self.differ.compare(
                    page, scenario.visual_baseline, scenario.id
                )
            except Exception as e:
                visual_results = [{
                    "baseline": scenario.visual_baseline,
                    "status": "error",
                    "ssim": None,
                    "pass": False,
                    "error": str(e),
                }]

        # ── 判定场景状态 ──
        status = self._determine_scenario_status(
            step_results, assertion_results, visual_results
        )

        return {
            "scenario_id": scenario.id,
            "description": scenario.description,
            "status": status,
            "step_results": step_results,
            "assertion_results": assertion_results,
            "visual_results": visual_results,
            "screenshots": screenshots,
        }

    # ── 状态判定 ───────────────────────────────────────────────

    def _determine_scenario_status(
        self,
        step_results: list[dict],
        assertion_results: list[dict],
        visual_results: list[dict],
    ) -> str:
        """判定场景整体状态。

        - 任何步骤失败 → "fail"
        - 任何第1-3层断言失败 → "fail"
        - 仅第4层断言失败 → "warning"
        - 视觉差异超阈值 → "warning"
        - 全部通过 → "pass"
        """
        # 步骤失败
        if any(not s.get("success", True) for s in step_results):
            return "fail"

        # 断言判定
        has_layer_1_3_fail = False
        has_layer_4_fail = False
        for a in assertion_results:
            if a.get("pass", True):
                continue
            layer = a.get("layer", 0)
            if 1 <= layer <= 3:
                has_layer_1_3_fail = True
            elif layer == 4:
                has_layer_4_fail = True

        if has_layer_1_3_fail:
            return "fail"

        # 视觉差异
        if any(v.get("status") == "diff_detected" for v in visual_results):
            return "warning"
        if any(v.get("status") == "warning" for v in visual_results):
            return "warning"

        if has_layer_4_fail:
            return "warning"

        return "pass"

    # ── 报告生成 ───────────────────────────────────────────────

    def _build_report(self, scenario_results: list[dict]) -> dict:
        """构建最终验证报告。"""
        total = len(scenario_results)
        passed = sum(1 for r in scenario_results if r["status"] == "pass")
        warnings = sum(1 for r in scenario_results if r["status"] == "warning")
        failed = sum(1 for r in scenario_results if r["status"] == "fail")
        errors = sum(1 for r in scenario_results if r["status"] == "error")

        return {
            "spec": self.spec_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total": total,
                "passed": passed,
                "warnings": warnings,
                "failed": failed,
                "errors": errors,
            },
            "scenarios": scenario_results,
        }

    def _write_progress(self, done: int, total: int, current: str):
        """写入实时进度文件，供仪表盘读取。

        与旧版 verifier agent 写入的格式兼容：
        {"total": N, "done": D, "current": "描述"}
        """
        progress_path = (
            self.project_root / ".fenix" / "verify-progress"
            / f"{self.spec_name}.json"
        )
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress = {
            "total": total,
            "done": done,
            "current": current,
        }
        try:
            with open(progress_path, "w", encoding="utf-8") as f:
                json.dump(progress, f, ensure_ascii=False)
        except Exception as e:
            self.logger.debug("verify_engine",
                              f"进度文件写入失败（非致命）: {e}")

    def _save_report(self, report: dict):
        """将报告写入磁盘。"""
        report_dir = (
            self.project_root / ".fenix" / "verify-progress" / self.spec_name
        )
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        self.logger.info(
            "verify_engine",
            f"📊 报告已保存: {report_path}",
        )


class _NullLogger:
    """空日志器，当未提供logger时的默认实现。"""

    def info(self, *args, **kwargs): pass
    def debug(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
