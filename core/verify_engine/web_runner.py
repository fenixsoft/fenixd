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

import asyncio
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .runner import VerifyRunner, register_runner, determine_scenario_status
from .browser import BrowserManager
from .assertions import AssertionRunner
from .visual_diff import VisualDiffer
from .env_gate import probe_http_health
from .scenarios import validate_scenario, WEB_ASSERTION_LAYERS
from .path_safety import safe_component

# 交互桶层归属（web-runner-assertion-eval-timing 1.1）：WEB_ASSERTION_LAYERS
# 第 2 层封闭枚举（no_click_interception / no_overlap / in_viewport /
# z_index_order）。分桶类型判定读断言声明的 layer 词表单源，不新增断言
# schema 字段、不要求场景文件逐场景改动。
_INTERACTIVE_ASSERTION_LAYER = 2


def locate_app_base_url(candidates: list, logger=None) -> str:
    """从候选场景的 navigate 步骤定位被测应用入口（契约 base_url 缺省回退）。

    navigate 失败（如 ERR_CONNECTION_REFUSED）时 URL 在 error 而非 detail——
    只扫 detail 会漏掉失联场景，探针保守判健康，整轮伪失败无法降级 blocked-env
    （add-v3-spec-detail-page 教训）。
    """
    for r in candidates:
        # code-review item 93baf5aa6007：外层候选与内层 step 同款类型防护，
        # 非 dict 候选直接跳过，避免 AttributeError 穿出探针链路（探针
        # 无法完成时设计口径为保守判健康，而非抛异常）。
        if not isinstance(r, dict):
            continue
        # code-review item 7d1fef294e67：step_results 类型前置收敛——`or []`
        # 只兜 None/空值，report 损坏把 step_results 写成数字/布尔等非空标量
        # 时 for 直接 TypeError 穿出（探针口径为保守判健康而非抛异常）。
        steps = r.get("step_results")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict) or step.get("action") != "navigate":
                continue
            detail = f"{step.get('detail') or ''} {step.get('error') or ''}"
            # 排除集含全角标点：中文文案 URL 直接衔接全角标点时不得并入 netloc，
            # 否则 urlsplit 后 base_url 带尾巴、探针误判环境失联。
            # code-review item eef126ad7232：排除集补半角「,;>」——URL 后无
            # 空白粘连续文（如 "http://127.0.0.1:8787,please retry"、
            # "http://a->http://b" 箭头粘连）此前被整条并入候选，rstrip 只能
            # 剥纯标点尾巴、port 校验 ValueError 后整条报废且无留痕，考古
            # 能力静默退化。三字符在 netloc 及「只取 scheme://netloc」的返回
            # 语境下均非法，截断不破坏任何合法形态；半角「.」故意不收——
            # 「127.0.0.1」等点分 host 属合法成分，收进排除集会把捕获截断成
            # "http://127"，点粘连形态仍走 port 校验 ValueError（下方 debug
            # 留痕）兜底。
            # code-review item 7e83a470e55c：re.search 只取首个命中，箭头粘
            # 连形态（"http://a->http://b"）首个候选经剥尾成无端口残址后，
            # 同串真实的第二 URL 无从入选，探针打向半截地址伪判失联。改
            # finditer 依序出候选：剥尾且无显式端口的残址暂缓采纳，优先返
            # 回更完整候选（未剥尾、或含显式端口）；全串无更完整候选时保
            # 留残址兜底（debug 留痕，与下方 ValueError 分支口径一致）。
            deferred_candidate = None
            for m in re.finditer(r"(https?://[^\s'\");,;>，。、；：？！）】》」』]+)", detail):
                url = m.group(1).rstrip("/")
                # 排除集缺半角「.,;:]>」等闭合标点：错误文案 URL 后紧跟句点/
                # 逗号（如 "... at http://127.0.0.1:8787."）会把尾巴并入
                # netloc，探针三端点因非法端口全部 ValueError 落 except
                # continue → 伪判环境失联。只剥尾部、不动中间——本函数只回
                # scheme://netloc，路径尾句点即使被剥也不改变返回值；含「[」
                # 的 IPv6 字面量其收尾「]」属合法成分，不可剥。尾「-」随
                # 「>」箭头粘连（"http://a->http://b" 捕获成 "http://a-"）
                # 一并剥除：host 段按 DNS 词法不得以「-」收尾，剥尾无损
                # 合法形态。
                url = url.rstrip(".,;:->" if "[" in url else ".,;:]->")
                try:
                    parts = urlsplit(url)
                    parts.port  # netloc 端口段仍不合法（非纯数字）时抛 ValueError
                except ValueError as e:
                    # code-review item eef126ad7232：弃用候选补 debug 留痕——
                    # 此前 continue 无任何日志，粘连/非法端口形态整条报废
                    # 无从定位；探针口径不变（保守判健康，不抛出）。
                    if logger:
                        logger.debug(
                            "verify_engine",
                            f"base_url 考古：候选 URL 因粘连/非法端口弃用（{e}）: {url!r}",
                        )
                    continue  # 该候选损坏：不原样返回带尾巴的 URL，继续扫下一候选
                if not (parts.scheme and parts.netloc):
                    continue
                if parts.port is None and url != m.group(1).rstrip("/"):
                    # 剥尾发生过且 netloc 无显式端口 → 高概率为截断残址
                    # （如箭头粘连的半截地址），暂缓采纳并续扫；其余候选
                    # 维持「首个有效即返回」。
                    if deferred_candidate is None:
                        deferred_candidate = f"{parts.scheme}://{parts.netloc}"
                        if logger:
                            logger.debug(
                                "verify_engine",
                                f"base_url 考古：剥尾无端口残址暂缓采纳，续扫更完整候选: {deferred_candidate!r}",
                            )
                    continue
                return f"{parts.scheme}://{parts.netloc}"
            if deferred_candidate is not None:
                if logger:
                    logger.debug(
                        "verify_engine",
                        f"base_url 考古：无更完整候选，采纳剥尾残址兜底: {deferred_candidate!r}",
                    )
                return deferred_candidate
    return ""


def _normalize_bool_config(value, key, default, logger=None) -> bool:
    """verify_engine 布尔型配置键归一读值（code-review item 278aa4c0a8e5）。

    JSON 合法写入 "headless": "false" 时裸真值判定得 True——非空字符串
    恒为真，期望的有头调试形态静默失效。口径：bool 直通；整数按 0→
    False、非零→True 归一（code-review item 382ff842892a：与字符串
    "0"/"1" 同语义，用户手写 JSON 的数字 0/1 笔误形态不再与字符串形态
    行为相反）；字符串按小写白名单（true/1/yes、false/0/no，与
    dashboard normalize_bool_flag 同款白名单思路）；其余未识别形态
    WARNING 留痕后回退缺省。本模块为叶子，不反向依赖 dashboard 包，
    就地实现同口径。
    """
    if isinstance(value, bool):
        return value
    # bool 是 int 子类，上方 bool 分支已先行直通；此处显式排除 bool，
    # 防止 True/False 被 int 分支二次归一（行为等价但取向含糊）。
    if isinstance(value, int) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    if logger:
        logger.warning(
            "verify_engine",
            f"配置 verify_engine.{key}={value!r} 非布尔形态，回退缺省 {default}",
        )
    return default


async def _safe_close_context(context, label: str, logger=None) -> None:
    """容错关闭 BrowserContext，三处 finally 统一口径（item abaa010f774c）。

    close 在浏览器进程已崩溃/连接已断时抛 TargetClosedError——execute
    （item 9d9cfb64c2e3）与 _perform_health_check / _probe_web_push
    （item 6fec72673aa8）的 finally 原各自手写同构 try/except 包裹，现
    收敛为本 helper 单一出处：warning 留痕后吞掉 close 的次生异常，调用
    方 try 体已算好的结论（场景结果/健康检查二元组/推流布尔）正常返回；
    try 体本身已抛异常时原异常照常穿出，此处仅吞 close 的次生异常。
    无 logger 形态（engine.py 直调 _probe_web_push 未传）静默吞。
    label 为日志前缀（含标点，与收敛前三处文案逐字一致）。
    """
    try:
        await context.close()
    except Exception as e:
        if logger:
            logger.warning(
                "verify_engine",
                f"{label} context.close 失败: {type(e).__name__}: {e}",
            )


@register_runner
class WebRunner(VerifyRunner):
    """浏览器驱动 Runner（playwright 异步 API，单浏览器多 context）。"""

    kind = "web"

    def __init__(self, spec_name, project_root=None, logger=None, config: Optional[dict] = None, **kwargs):
        # code-review item 2b8a2997cc9f：project_root 归一为 Path（str/PathLike
        # → Path，falsy 保持 None）。基类 __init__ 原样存储、缺省 None，不归一
        # 时 _execute_scenario 截图目录拼接 ``self.project_root / ".fenix"``
        # 对 str/None 形态抛 TypeError 穿出场景执行，被引擎 return_exceptions
        # 兜底替换为空 error 条目、已采集证据全失。None 保持 None 不改探测
        # （无 root 时 base_url 考古/CLI 回退链的 falsy 判定）与 fail-fast
        # 语义（VisualDiffer 构造契约本要求 Path）。
        # [fenix-ignore:7d85a0f2316a] 已核实 None 崩溃不可达：下方 VisualDiffer 构造（visual_diff.py Path(project_root)）对 None 在 __init__ 构造期即抛 TypeError fail-fast，实例到不了 _execute_scenario 的截图目录拼接。
        project_root = Path(project_root) if project_root else None
        super().__init__(spec_name, project_root, logger, config, **kwargs)
        self.browser = BrowserManager(project_root=project_root, logger=self.logger)
        self.asserter = AssertionRunner()
        # 视觉对比器持有配置（settle 上限 / 重拍次数，verify_engine 段，
        # 缺省回退），见 visual_diff.py D6 配置读取。
        self.differ = VisualDiffer(spec_name, project_root, config=config, logger=self.logger)
        # 契约统一供给的 base_url（引擎注入；优先级高于 navigate 文本考古）。
        # 无实例形态（纯 CLI 轮次）下为空字符串，改写/探针为无害空操作。
        self.base_url = ""
        # 容错口径对齐 engine.__init__：段非 dict（str/list 等）时回退空段，
        # 避免 AttributeError 在验收门 _runner_for 构造点穿出整轮 run()。
        verify_cfg = (config or {}).get("verify_engine") or {}
        if not isinstance(verify_cfg, dict):
            verify_cfg = {}
        # code-review item 278aa4c0a8e5：headless 字符串形态布尔值归一，
        # 避免 "false" 非空字符串真值导致无头模式静默失效。
        self.headless = _normalize_bool_config(
            verify_cfg.get("headless", True),
            "headless",
            default=True,
            logger=self.logger,
        )
        self._setup_health_ok = True

    @staticmethod
    def _extract_screenshot_result(ss) -> tuple:
        """兼容 browser.screenshot() 新旧两种返回形态。

        新形态（screenshot-evidence-labeling，design D1）：dict
        {"path": str, "labels": dict}；旧形态 / 测试 mock：纯字符串路径。
        统一返回 (path, labels)，labels 为空 dict 表示无标签（正常截图）。
        其余真值形态（bytes/数字等）归一为空串，兼容面只承诺字符串。
        """
        if isinstance(ss, dict):
            path = ss.get("path") or ""
            labels = ss.get("labels") if isinstance(ss.get("labels"), dict) else {}
            return path, labels
        # code-review item 353c8d931dfb：非 dict 分支收窄为纯字符串——
        # bytes/数字等真值标量不再原样充当截图路径穿出入账（此前
        # _record_screenshot 只判 falsy，真值标量会混进 screenshots 列表、
        # screenshot_labels 以该对象为键，报错定位在下游读证文件端而非
        # 采集端）；归一为空串后与空路径同走 _record_screenshot 的
        # WARNING 留痕跳过，「screenshots 列表只含有效路径」口径闭合。
        return (ss if isinstance(ss, str) else ""), {}

    def _record_screenshot(self, path, labels, screenshots, screenshot_labels, warn_msg) -> None:
        """取证截图入账（code-review item 56a797a882e0）。

        _extract_screenshot_result 对 dict 形态缺/空 path 键容忍为空串、
        旧形态 None 与非字符串标量（item 353c8d931dfb）亦归一为空串；
        入账时空 path WARNING 留痕后跳过，
        screenshots 列表只含有效路径、screenshot_labels 不出现空串键，
        下游 judge/校验器按路径读取证文件不会拿到无效条目。两处入账点
        （关键步骤截图 / 断言失败取证）统一走本 helper 单一出处。
        """
        if not path:
            self.logger.warning("verify_engine", warn_msg)
            return
        screenshots.append(path)
        if labels:
            screenshot_labels.setdefault(path, {}).update(labels)

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
            nav_first_frame_ok = None
            if self.browser.is_extension_project:
                nav_ok = await self.browser.navigate_to_app(page)
                # 首帧等待结果（code-review item c109de7ea35b）：navigate_to_app
                # 内 _wait_stable 的首帧 8s 超时此前被丢弃，健康检查通过后的
                # 瞬态白屏在该入口被归因为「元素不存在」类产品/场景失败
                nav_first_frame_ok = getattr(page, "_fenix_nav_first_frame_ok", None)
                if not nav_ok:
                    self.logger.warning(
                        "verify_engine",
                        f"场景'{scenario.id}': navigate_to_app 失败，页面可能为空白",
                    )
            result = await self._execute_scenario(scenario, page, context)
            # 与 execute_action navigate 分支（B1）同款结构化标记：env_gate
            # 只信任 step_results 里显式 first_frame_ok is False，白屏场景
            # 据此降级 blocked-env；success=True 不影响 determine_scenario_
            # status 的步骤成败判定，插在队首对齐预导航的时序位置
            if nav_first_frame_ok is False:
                result["step_results"].insert(
                    0,
                    {
                        "action": "navigate",
                        "success": True,
                        "detail": (
                            "扩展项目场景入口预导航（navigate_to_app）完成，"
                            "首帧渲染等待超时"
                        ),
                        "first_frame_ok": False,
                    },
                )
            return result
        finally:
            # code-review item 9d9cfb64c2e3：close 在浏览器进程已崩溃/连接
            # 已断时抛 TargetClosedError，裸奔会在 return result 前把已算好
            # 的场景结果（step_results/assertion_results 等全部证据）顶掉，
            # 穿到引擎 run_one 的 return_exceptions 兜底被替换成空 error 条
            # 目。与 BrowserManager.stop 的逐步容错口径对齐：warning 留痕
            # 后吞掉，try 体的 result 正常返回；try 体本身已抛异常时原异常
            # 照常穿出（此处仅吞 close 的次生异常）。
            # item abaa010f774c：容错包裹收敛到 _safe_close_context 单一出处。
            await _safe_close_context(
                context, f"场景'{scenario.id}':", self.logger
            )

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
            try:
                page = await context.new_page()
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
                # code-review item 6fec72673aa8：close 在浏览器进程已崩溃/
                # 连接已断时抛 TargetClosedError，finally 裸奔会顶掉 try 体
                # 已算好的健康检查结论（True 或 False+成因文案）。与 execute
                # 的 finally（item 9d9cfb64c2e3）同款口径：warning 留痕后吞掉。
                # item abaa010f774c：容错包裹收敛到 _safe_close_context 单一出处。
                await _safe_close_context(context, "健康检查", self.logger)
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
            self.project_root
            / ".fenix"
            / "verify-progress"
            / safe_component(self.spec_name)
            / "screenshots"
        )

        # ── 断言求值计划分层（web-runner-assertion-eval-timing 1.1）──
        # 交互桶（WEB_ASSERTION_LAYERS 第 2 层四类）走视图切换感知求值窗口：
        # 导航类场景中途 show('session') 切视图后，交互断言若统一延到断言批
        # 时刻求值，目标元素已随视图隐藏，not visible 走非遮挡分支且无视图
        # 证据（judge_attribution.json 三案例互证的误报根因）。流程桶保持
        # 既有后置统一求值语义不变。
        assertion_defs = [a.to_dict() for a in scenario.assertions]
        pending_interactive: set[int] = {
            i
            for i, a in enumerate(assertion_defs)
            if WEB_ASSERTION_LAYERS.get(a.get("type", ""), 0)
            == _INTERACTIVE_ASSERTION_LAYER
        }
        seen_visible: set[int] = set()
        early_results: dict[int, dict] = {}

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
                    self._record_screenshot(
                        path, labels, screenshots, screenshot_labels,
                        f"场景'{scenario.id}': 关键步骤截图取证返回空路径，跳过该条目",
                    )
                except Exception as exc:
                    self.logger.warning(
                        "verify_engine",
                        f"场景'{scenario.id}': 关键步骤截图取证失败: {repr(exc)[:200]}",
                    )

            # 交互桶求值窗口：步骤完成点探测 + 即时求值（含 trial click）。
            # 窗口内失败/异常均不中断后续步骤（与「断言失败不停步骤」现状
            # 一致），结果按声明序回填。
            if pending_interactive:
                early_results.update(
                    await self._eval_interactive_window(
                        page, assertion_defs, pending_interactive,
                        seen_visible, i, len(scenario.steps),
                    )
                )

        # ── 运行断言（步骤失败 → 断言未进行，跳过）──

        # 注入运行时数据（console/network错误 + 场景级外部 API 网络豁免标记）
        for a_def in assertion_defs:
            if a_def.get("type") == "no_console_error":
                a_def["_console_errors"] = self.browser.get_console_errors(context)
                a_def["_external_net_errors_ok"] = scenario.external_net_errors_ok
            if a_def.get("type") == "no_network_error":
                a_def["_network_errors"] = self.browser.get_network_errors(context)

        assertion_results: list[dict] = []
        if not steps_failed:
            # 求值计划合并：交互桶已收口条目（窗口内最后可见完成点的求值
            # 结果）按声明序回填；其余条目（流程桶 + 全程不可见回退的交互
            # 断言）保持既有后置统一求值。回退条目与流程条目合并为一次
            # asserter.run 调用，后置求值时机与现状一致。
            fallback_defs = [
                a for i, a in enumerate(assertion_defs) if i not in early_results
            ]
            try:
                post_results = (
                    await self.asserter.run(page, fallback_defs)
                    if fallback_defs
                    else []
                )
                post_iter = iter(post_results)
                # 哨兵消费（code-review item 512d04645f39）：裸 next 在
                # asserter.run 返回条数少于 fallback_defs 时抛 StopIteration，
                # 被下方 except 接住后整批重建为一条笼统错误项——后置桶已
                # 求出的部分结果与对应断言定位全部丢失。耗尽时为该断言生成
                # 带 type/selector 定位的逐条失败项（layer=0 保守判 fail，
                # 与既有兜底项形状同款），已得结果按声明序保留。
                _exhausted = object()
                assertion_results = []
                for i in range(len(assertion_defs)):
                    if i in early_results:
                        assertion_results.append(early_results[i])
                        continue
                    a_def = assertion_defs[i]
                    result = next(post_iter, _exhausted)
                    if result is _exhausted:
                        result = {
                            "type": a_def.get("type", "assert_run"),
                            "layer": 0,
                            "pass": False,
                            "error": (
                                f"断言结果缺失（asserter.run 返回 {len(post_results)} 条，"
                                f"少于后置声明 {len(fallback_defs)} 条，"
                                f"总声明 {len(assertion_defs)} 条），按失败兜底"
                            ),
                        }
                        if a_def.get("selector"):
                            result["selector"] = a_def["selector"]
                    assertion_results.append(result)
            except Exception as exc:
                # 兜底断言入口异常（code-review item 7467793325b4，与下方视觉
                # 对比兜底同模式）：异常若穿透 _execute_scenario，会落到引擎
                # run_one 的 return_exceptions 兜底——该路径 step_results/
                # assertion_results 全为空列表，已采集的步骤证据被整体抹掉。
                # 错误项形状对齐 assertions.run 的兜底（layer=0 → 保守判 fail）；
                # 窗口内已收口的交互断言结果按声明序保留，不被入口异常抹掉。
                assertion_results = [
                    *(early_results[i] for i in sorted(early_results)),
                    {
                        "type": "assert_run",
                        "layer": 0,
                        "pass": False,
                        "error": f"断言执行入口异常: {type(exc).__name__}: {exc}",
                    },
                ]

            # 断言真正执行且至少一个失败 → 截图取证（真实产品缺陷）。
            # 断言全部通过则不截图。步骤失败已在上方 break，不进入此分支。
            # 取证触发缺省与 determine_scenario_status 完全同款（code-review
            # item 48c972a8e287）：dict 条目缺 pass 键按 fail 兜底（缺省
            # False）、非 dict 条目（上游畸形）亦按 fail 兜底——状态被判
            # fail 的场景必有断言失败取证截图，judge/复核链不缺证据。
            if any(not (isinstance(a, dict) and a.get("pass", False)) for a in assertion_results):
                try:
                    ss = await self.browser.screenshot(
                        page, f"{scenario.id}_assert_fail", screenshot_dir
                    )
                    path, labels = self._extract_screenshot_result(ss)
                    self._record_screenshot(
                        path, labels, screenshots, screenshot_labels,
                        f"场景'{scenario.id}': 断言失败取证截图返回空路径，跳过该条目",
                    )
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
                # 兜底形状对齐 visual_diff._compare_once 的结构化 error 结果：
                # 携带 scenario_id、错误文案用 detail 键
                # （code-review item b9b9185b012e）。
                visual_results = [
                    {
                        "baseline": scenario.visual_baseline,
                        "status": "error",
                        "ssim": None,
                        "pass": False,
                        "detail": str(e),
                        "scenario_id": scenario.id,
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

    async def _eval_interactive_window(
        self,
        page,
        assertion_defs: list[dict],
        pending: set,
        seen_visible: set,
        step_index: int,
        total_steps: int,
    ) -> dict:
        """交互桶求值窗口：步骤完成点探测未决交互断言的目标元素可见性。

        求值窗口语义（视图切换感知，web-runner-assertion-eval-timing 1.1）：
        - 目标元素在本步骤完成点仍可见 → 即时求值（含 trial click），本次
          结果覆盖先前窗口结果——调用方最终取「目标元素仍可见的最后一个
          步骤完成点」的求值结果，绑定步骤完成点而非步骤中间态；
        - 目标元素曾可见、本步骤完成点转不可见 → 从未决集收口：最后可见
          完成点的结果即最终结果，不再随视图切走被后置求值误判；
        - 目标元素全程不可见 → 保持未决，由调用方回退既有后置时机求值
          （真实缺陷不被提前求值掩盖）。

        窗口内探测/求值异常吞掉留痕、不中断后续步骤（与「断言失败不停
        步骤」现状一致），对应断言回退既有后置时机。返回本次窗口新求值
        的 {断言声明序 index: 结果}；pending/seen_visible 就地维护。
        """
        fresh: dict = {}
        for idx in sorted(pending):
            selector = assertion_defs[idx].get("selector", "")
            if not selector:
                # 无锚点探测不了窗口：保持未决走后置（selector 缺参由
                # asserter.run 分派前兜底定向失败，与现状口径一致）
                continue
            try:
                visible = await page.locator(selector).first.is_visible()
            except Exception as exc:
                # 探测异常（选择器语法非法/上下文关闭等）：保持未决回退
                # 后置，由 asserter.run 的既有异常兜底定向归因
                self.logger.debug(
                    "verify_engine",
                    f"交互断言窗口探测异常（回退后置求值）: selector={selector!r}, "
                    f"{type(exc).__name__}: {exc}",
                )
                continue
            if not visible:
                if idx in seen_visible:
                    # 曾可见 → 已错过最后可见完成点，以最近一次窗口结果收口
                    pending.discard(idx)
                continue
            seen_visible.add(idx)
            try:
                results = await self.asserter.run(page, [assertion_defs[idx]])
                if results and isinstance(results[0], dict):
                    fresh[idx] = results[0]
                    # 求值窗口留痕：judge/报告可区分窗口内求值与后置求值
                    fresh[idx]["eval_timing"] = (
                        f"in-window(step {step_index + 1}/{total_steps})"
                    )
            except Exception as exc:
                self.logger.warning(
                    "verify_engine",
                    f"交互断言窗口内求值异常（不中断步骤，回退后置求值）: "
                    f"selector={selector!r}, {type(exc).__name__}: {exc}",
                )
        return fresh

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


async def _probe_web_push(browser, logger=None) -> bool:
    """在真实浏览器中验证数据推流：加载应用并等待数据域渲染。

    mock 斩断 SSE 时数据节点永不渲染 → 等待超时 → 判定推流中断。
    复用 browser.navigate_to_app + wait_selector，与场景执行同一浏览器实例。
    """
    context = await browser.new_context()
    try:
        page = await context.new_page()
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
        # code-review item 6fec72673aa8：同款口径包裹 close 次生异常，
        # 避免顶掉 try 体的推流检查结论（True/False）。无 logger 形态
        # （engine.py 直调点未传）静默吞，结论保住为先。
        # item abaa010f774c：容错包裹收敛到 _safe_close_context 单一出处。
        await _safe_close_context(context, "推流探针", logger)


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
    # code-review item 538544bbd784：getattr 防御——browser 为无 base_url
    # 属性的形态（测试替身/无实例直调）时 AttributeError 会穿出探针链路，
    # 违背「探针无法完成时保守判健康」契约；与 execute 里
    # getattr(self, "_setup_health_ok", True) 同款防御口径。
    base = base_url or getattr(browser, "base_url", "")
    detail = ""
    healthy = True
    if not base and project_root:
        base = locate_app_base_url(candidates, logger=logger)
    if base:
        # 线程池执行：probe_http_health 为同步阻塞探测（最坏 3×2s），避免卡死事件循环
        healthy = await asyncio.to_thread(probe_http_health, base, timeout=2.0)
        detail = f"HTTP 探测 {base}: {'连通' if healthy else '失联'}"
    # 推流检查（扩展项目 / 浏览器可用时）
    # code-review item af9a13d07f10：同款 getattr 防御，替身缺
    # is_extension_project 时 AttributeError 会穿出探针链路，违背
    # 「探针无法完成时保守判健康」契约；与 engine._fallback_environment_probe
    # 的 getattr(self.browser, "is_extension_project", False) 同口径。
    if healthy and getattr(browser, "is_extension_project", False):
        try:
            push_ok = await _probe_web_push(browser, logger=logger)
            healthy = healthy and push_ok
            detail += f"；推流{'正常' if push_ok else '中断'}"
        except Exception as e:
            if logger:
                logger.debug("verify_engine", f"推流检查不可用，跳过: {e}")
    return {"healthy": healthy, "detail": detail.strip("；")}
