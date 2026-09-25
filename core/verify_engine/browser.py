"""
browser.py — Playwright 浏览器管理器

职责：
  - 浏览器生命周期管理（启动/复用/关闭）
  - 用户操作执行（click/type/scroll/select/wait/navigate）
  - 数据采集（DOM快照、截图、console日志、网络错误）
  - 布局稳定性等待（CLS 稳定；networkidle 因页面常驻 SSE 永不满足，已移除）
  - 扩展项目支持：自动启动本地 HTTP 服务器提供 dist/ 目录

设计决策：
  - 单浏览器实例 + 每场景独立 context（隔离 + 复用）
  - 使用 Playwright 异步 API
  - 操作前自动等待元素可交互（Playwright 内置 auto-wait）
  - 点击时自动检测 interception（Playwright 原生错误）
  - 对 Chrome 扩展项目，自动启动 HTTP 服务器并将 about:blank 重定向到应用
"""

import asyncio
import http.server
import json
import re
import socket
import socketserver
import threading
from pathlib import Path
from typing import Optional


def _find_free_port() -> int:
    """查找一个可用的端口号。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """多线程 HTTP 服务器（ThreadingMixIn，每个请求在独立线程中处理），用于提供静态文件服务。"""

    daemon_threads = True
    allow_reuse_address = True


class _StaticFileHandler(http.server.SimpleHTTPRequestHandler):
    """静态文件处理器，从指定目录提供服务。"""

    def __init__(self, *args, directory: str, **kwargs):
        self.directory = directory
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format, *args):
        """抑制 HTTP 日志输出。"""
        pass


def _make_handler(directory: str):
    """创建绑定到指定目录的处理器类。"""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, format, *args):
            pass  # 抑制日志

        def end_headers(self):
            # 添加 CORS 头以支持跨域请求
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Cache-Control", "no-store, must-revalidate")
            super().end_headers()

    return Handler


async def wait_animations_settled(page, timeout_ms: int) -> bool:
    """等待页面动画静置（settle，fix-visual-baseline-settle D1）。

    注入 JS 轮询 ``document.getAnimations()``，等待全部进行中动画（playState
    为 running）到达 finished；全部静置返回 True，达 ``timeout_ms`` 上限仍有
    未完成动画返回 False。``timeout_ms <= 0`` 直接返回 True（不等待，行为与
    现状一致，逃生门）。

    覆盖 ``_wait_stable`` 的 CLS 判定检测不到的 opacity/transform 渐变动画
    （antd Modal ~300ms fade：Playwright 的 visible 判定不看 opacity，DOM
    断言通过而截图拍到动画早段画面）。注入失败（老内核/异常页面）按超时
    退化返回 False，不抛出——与 CLS 检测同容错模式，不放大失败。

    Args:
        page: Playwright Page 对象。
        timeout_ms: 等待上限（毫秒）；0/负值跳过等待。

    Returns:
        True=动画全部静置（或跳过等待）；False=达上限仍有未完成动画（或注入失败）。
    """
    if not timeout_ms or timeout_ms <= 0:
        return True
    try:
        settled = await page.evaluate(
            """(timeoutMs) => {
            if (!timeoutMs || timeoutMs <= 0) return true;
            const deadline = performance.now() + timeoutMs;
            return new Promise((resolve) => {
                const tick = () => {
                    let running = 0;
                    try {
                        if (document.getAnimations) {
                            running = document.getAnimations().filter(
                                (a) => a && a.playState === 'running'
                            ).length;
                        }
                    } catch (e) {
                        running = 0;  // getAnimations 异常按无动画处理
                    }
                    if (running === 0) {
                        resolve(true);
                    } else if (performance.now() >= deadline) {
                        resolve(false);
                    } else {
                        requestAnimationFrame(tick);
                    }
                };
                tick();
            });
        }""",
            timeout_ms,
        )
        return bool(settled)
    except Exception:
        # 注入失败（老内核/异常页面）按超时退化处理，不放大失败
        return False


class BrowserManager:
    """Playwright 浏览器管理器。

    使用 Playwright 异步 API。
    支持 Chrome 扩展项目的本地 HTTP 服务器自动启动。
    """

    def __init__(self, project_root: Optional[Path] = None, logger=None):
        self._playwright = None
        self._browser = None
        self._started = False
        self._project_root = project_root
        self._logger = logger

        # 扩展项目 HTTP 服务器
        self._dev_server: Optional[http.server.HTTPServer] = None
        self._dev_server_port: int = 0
        self._base_url: str = ""
        self._is_extension_project: bool = False

        # 独立 HTML 入口点支持
        self._use_verify_html: bool = False

        # （SSE 拦截标记现记录在 page 对象属性 _fenix_sse_blocked 上——
        # mock 场景必须隔离活体推流，见 mock_api 分支；勿用 id(page) 集合，
        # 页面对象 GC 后 id 复用会造成标记误命中。）

    # ── 扩展项目检测 ───────────────────────────────────────────

    def _detect_extension_project(self) -> bool:
        """检测项目是否为 Chrome 扩展（存在 dist/manifest.json）。"""
        if not self._project_root:
            return False
        manifest = self._project_root / "dist" / "manifest.json"
        return manifest.exists()

    # ── 本地 HTTP 服务器 ───────────────────────────────────────

    def _start_dev_server(self):
        """启动本地 HTTP 服务器提供 dist/ 目录的静态文件。"""
        if self._dev_server is not None:
            return  # 已启动

        dist_dir = self._project_root / "dist"
        handler = _make_handler(str(dist_dir))
        # 直接 bind 0 端口，由内核在同一次绑定中分配并占住空闲端口，
        # 消除「先 _find_free_port() 探测、后真正绑定」两步之间端口被
        # 其他进程抢占的 TOCTOU 窗口（此前 EADDRINUSE 会以未捕获
        # OSError 打断 start()，无日志也无降级）。实际端口在绑定成功后
        # 从 server 取回，_dev_server_port/_base_url 与监听 socket 恒一致。
        try:
            self._dev_server = _ThreadedHTTPServer(("127.0.0.1", 0), handler)
        except OSError as e:
            self._log("error", f"启动本地 HTTP 服务器失败: {type(e).__name__}: {e}")
            raise
        self._dev_server_port = self._dev_server.server_address[1]
        self._base_url = f"http://127.0.0.1:{self._dev_server_port}"

        thread = threading.Thread(target=self._dev_server.serve_forever, daemon=True)
        thread.start()

        # 生成独立可运行的 HTML 入口点（绕过 CRXJS 扩展外壳）
        self._generate_standalone_html()

    def _stop_dev_server(self):
        """停止本地 HTTP 服务器。"""
        if self._dev_server:
            self._dev_server.shutdown()
            self._dev_server.server_close()
            self._dev_server = None
            self._dev_server_port = 0
            self._base_url = ""

    def _generate_standalone_html(self):
        """扫描 dist/assets 找到编译后的主应用资源，生成可独立运行的 verify.html。

        CRXJS 构建产出的 dist/index.html 是扩展开发外壳，会尝试连接
        Vite 开发服务器（localhost:5199），在独立 HTTP 服务器上下文中无法工作。
        此方法扫描 dist/assets/ 中的实际应用 bundle 文件并生成可独立加载的 HTML。

        该方法被 try/except 完整包裹，确保任何 I/O 错误都不会导致
        _use_verify_html 处于不确定状态。
        """
        try:
            self._generate_standalone_html_impl()
        except Exception as e:
            self._use_verify_html = False
            self._log("error", f"生成 verify.html 失败: {type(e).__name__}: {e}")

    def _generate_standalone_html_impl(self):
        """_generate_standalone_html 的实现逻辑。"""
        if not self._project_root:
            self._use_verify_html = False
            return

        assets_dir = self._project_root / "dist" / "assets"
        if not assets_dir.exists():
            self._log("warning", f"dist/assets/ 目录不存在，回退到 index.html")
            self._use_verify_html = False
            return

        # 扫描主 JS 文件: index.html-{hash}.js
        # 文件名 hash 与构建时间无关，按 mtime 降序取最新，
        # 避免 dist 残留多份历史 bundle 时字典序选中旧版本
        js_files = sorted(
            assets_dir.glob("index.html-*.js"),
            key=lambda p: (p.stat().st_mtime, p.name),
            reverse=True,
        )
        # 扫描主 CSS 文件: index-{hash}.css
        css_files = sorted(
            assets_dir.glob("index-*.css"),
            key=lambda p: (p.stat().st_mtime, p.name),
            reverse=True,
        )

        if not js_files:
            self._log("warning", "未找到 index.html-*.js 文件，回退到 index.html")
            self._use_verify_html = False
            return
        if not css_files:
            self._log("warning", "未找到 index-*.css 文件，回退到 index.html")
            self._use_verify_html = False
            return

        js_path = js_files[0].name
        css_path = css_files[0].name
        if len(js_files) > 1 or len(css_files) > 1:
            self._log(
                "warning",
                f"dist/assets 存在多份候选 bundle（JS×{len(js_files)}, CSS×{len(css_files)}），"
                f"已按修改时间取最新: JS={js_path}, CSS={css_path}，疑似历史构建残留",
            )

        # 生成独立 HTML，参考根 index.html 结构
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Fenix New Tab - Verify</title>
    <link rel="stylesheet" href="/assets/{css_path}" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/assets/{js_path}"></script>
  </body>
</html>"""

        verify_path = self._project_root / "dist" / "verify.html"
        # 自动清理旧文件，确保每次生成都是最新内容
        verify_path.unlink(missing_ok=True)
        verify_path.write_text(html, encoding="utf-8")
        self._use_verify_html = True
        self._log("info", f"已生成独立 HTML 入口: verify.html (JS={js_path}, CSS={css_path})")

    def _log(self, level: str, message: str):
        """内部日志辅助方法。

        兼容两种 logger 接口：
        - 标准 logging.Logger / _NullLogger: info(msg) → 单参数消息
        - fenixd Logger: info(component, message) → 双参数（component 作为第一参数）

        先尝试标准单参数调用，失败再回退到 fenixd 双参数调用，
        避免标准 logging 的 %-格式化 TypeError 噪音。
        """
        if self._logger:
            log_fn = getattr(self._logger, level, None)
            if log_fn:
                try:
                    # 先尝试标准单参数调用（兼容 logging.Logger / _NullLogger）
                    log_fn(f"[browser] {message}")
                except TypeError:
                    # 回退到 fenixd Logger 的 (component, message) 调用
                    log_fn("browser", message)

    # ── 生命周期 ───────────────────────────────────────────────

    async def start(self, headless: bool = True):
        """启动浏览器实例（单例）。

        对扩展项目自动启动本地 HTTP 服务器。
        """
        if self._started:
            return

        self._is_extension_project = self._detect_extension_project()

        if self._is_extension_project:
            self._start_dev_server()

        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-animations",
                "--disable-gpu",
                "--no-sandbox",
                "--font-render-hinting=none",
            ],
        )
        self._started = True

    async def stop(self):
        """停止浏览器并释放资源。

        三步释放（browser.close / playwright.stop / 停本地 HTTP 服务器）
        用 try/finally 串联且各步独立容错：任一步失败（如浏览器进程已
        崩溃导致 close 抛 PlaywrightError）不阻断后续释放，避免残留
        playwright driver 进程与本地 HTTP 服务器线程直到进程退出。
        """
        try:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception as e:
                    self._log("warning", f"browser.close 失败: {type(e).__name__}: {e}")
                finally:
                    self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    self._log("warning", f"playwright.stop 失败: {type(e).__name__}: {e}")
                finally:
                    self._playwright = None
        finally:
            self._started = False
            try:
                self._stop_dev_server()
            except Exception as e:
                self._log("warning", f"停止本地 HTTP 服务器失败: {type(e).__name__}: {e}")

    async def new_context(self, viewport: Optional[dict] = None) -> "BrowserContext":
        """创建隔离的浏览器上下文。

        每个场景一个独立的 context，实现状态隔离。
        viewport：场景级视口覆盖（TestScenario.viewport，移动端/响应式场景）；
        None 沿用桌面缺省 1280×800（admin 修 2026-09-07：此前场景声明的
        移动端视口被静默丢弃，useIsMobile 门控的 UI 在验证中永不渲染）。
        """
        if not self._started:
            raise RuntimeError("浏览器未启动，请先调用 start()")

        context = await self._browser.new_context(
            viewport=viewport or {"width": 1280, "height": 800},
            reduced_motion="reduce",
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        # 收集控制台错误和网络错误
        console_errors: list[str] = []
        network_errors: list[str] = []

        context.on(
            "page",
            lambda p: p.on(
                "console",
                lambda msg: (
                    console_errors.append(f"[{msg.type}] {msg.text}")
                    if msg.type == "error"
                    else None
                ),
            ),
        )
        context.on(
            "page",
            lambda p: p.on(
                "response",
                lambda resp: (
                    network_errors.append(f"{resp.status} {resp.url}")
                    if resp.status >= 400
                    else None
                ),
            ),
        )

        # 将错误收集器挂到 context 上供断言使用
        context._console_errors = console_errors
        context._network_errors = network_errors

        return context

    # ── 属性 ───────────────────────────────────────────────────

    @property
    def is_extension_project(self) -> bool:
        """是否为 Chrome 扩展项目。"""
        return self._is_extension_project

    @property
    def base_url(self) -> str:
        """本地 HTTP 服务器的基础 URL（扩展项目有效）。"""
        return self._base_url

    # ── 页面导航辅助 ─────────────────────────────────────────

    async def navigate_to_app(self, page) -> bool:
        """将页面导航到应用首页（扩展项目专用）。

        仅在 is_extension_project 为 True 且 base_url 非空时执行。
        优先使用自动生成的 verify.html（独立可运行），回退到 index.html。

        Returns:
            True 表示导航成功，False 表示跳过或失败
        """
        if not self._is_extension_project or not self._base_url:
            return False
        target = "verify.html" if self._use_verify_html else "index.html"
        url = f"{self._base_url}/{target}"
        try:
            await page.goto(
                url,
                # domcontentloaded 与 execute_action navigate 分支一致；networkidle
                # 因页面常驻连接（SSE 长连）永不满足（见模块 docstring），加载
                # 稳定性由紧随其后的 _wait_stable（首帧非空文本 + CLS）承担
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await self._wait_stable(page)
            return True
        except Exception as e:
            self._log("warning", f"navigate_to_app 失败 ({target}): {type(e).__name__}: {e}")
            return False

    # ── 操作执行 ───────────────────────────────────────────────

    def _register_dialog_handler(self, page, mode: str, prompt_text: str = None) -> None:
        """注册一次性对话框处理器，处理下一个 window.confirm/alert/prompt。

        Playwright 对未处理的 dialog 默认自动 dismiss（相当于点击「取消」），
        导致切换/删除用户等正向场景被误判失败。此方法让场景显式声明
        accept（确认）或 dismiss（取消）行为。

        prompt_text：prompt 对话框 accept 时提交的文本。Playwright 的
        dialog.accept() 不带文本时返回空串而非页面预填默认值——依赖预填值
        的正向场景（如「调整优先级」直接确认预填 P5）会走取消/校验失败分支，
        场景必须显式携带 prompt_text（admin 修 2026-08-29：族谱爆炸根因之一）。
        """

        def _handle(dialog, _mode=mode, _text=prompt_text):
            try:
                if _mode == "accept":
                    task = (
                        dialog.accept(prompt_text=_text) if _text is not None else dialog.accept()
                    )
                else:
                    task = dialog.dismiss()
                asyncio.ensure_future(task)
            except Exception:
                pass

        page.once("dialog", _handle)

    async def execute_action(self, page, step: dict) -> dict:
        """执行单个用户操作。

        支持的操作类型：
        - navigate: 页面导航
        - click: 点击元素（自动检测click interception）
        - type: 输入文本（先清空再填充）
        - clear: 清空输入框
        - select: 下拉选择
        - scroll: 滚动到元素
        - wait: 等待指定选择器可见

        对扩展项目：
        - navigate to about:blank 自动重定向到本地 HTTP 服务器的应用页面

        Returns:
            {"success": bool, "action": str, "target"?: str, "error"?: str,
             "error_type"?: str, ...}
        """
        action = step.get("action", "")
        target = step.get("target", "")
        value = step.get("value", "")

        try:
            if action == "navigate":
                # 扩展项目：将 about:blank 重定向到验证 HTML
                actual_url = value
                # web 项目：相对/非法 navigate URL 直接显式失败（2026-08-28：
                # 相对路径导致 about:blank 白屏、整轮断言全灭的假失败）。
                # 不注入任何默认 base/端口——被测实例地址只有运行环境自己知道，
                # 此类失败应退回 plan 阶段重新生成绝对 URL 场景。
                if not self._is_extension_project and not re.match(
                    r"^https?://", str(value).strip()
                ):
                    return {
                        "success": False,
                        "action": action,
                        "error_type": "invalid_navigate_url",
                        "error": (
                            f"navigate URL 必须为绝对地址（http/https），"
                            f"环境未提供 base_url 且禁止猜测默认端口: {value!r}"
                        ),
                        "detail": f"非法 navigate 目标 {value!r}",
                    }
                # chrome-extension:// URL 在当前验证浏览器（未加载扩展）中不可达
                # （Planner 可能生成 chrome-extension://__MSG_@@extension_id__/ 之类目标），
                # 统一回退到本地 HTTP 服务器（navigate_to_app 同款入口），避免场景判 fail。
                if self._is_extension_project and value.startswith("chrome-extension://"):
                    self._log(
                        "warning",
                        f"navigate 目标 {value} 为 chrome-extension:// URL"
                        "（验证浏览器未加载扩展），已回退到本地 HTTP 服务器",
                    )
                    entry_html = "verify.html" if self._use_verify_html else "index.html"
                    actual_url = f"{self._base_url}/{entry_html}"
                elif self._is_extension_project and (
                    value == "about:blank" or value == "" or value.startswith("about:")
                ):
                    entry_html = "verify.html" if self._use_verify_html else "index.html"
                    actual_url = f"{self._base_url}/{entry_html}"

                await page.goto(actual_url, wait_until="domcontentloaded", timeout=15000)
                first_frame_ok = await self._wait_stable(page)
                result = {"success": True, "action": action, "detail": f"已导航到 {actual_url}"}
                # B1：仅首帧超时时显式落 False（True 不写键，旧报告/测试兼容）；
                # env_gate.is_blank_render_candidate 依赖此键把白屏场景降级
                # blocked-env，不再伪装成「元素不存在」类产品/场景失败
                if first_frame_ok is False:
                    result["first_frame_ok"] = False
                return result

            # wait 操作可以没有 target（此时使用 value 作为暂停毫秒数）
            if action == "wait" and not target:
                try:
                    timeout_ms = float(value) if value else 1000
                    await page.wait_for_timeout(timeout_ms)
                    return {
                        "success": True,
                        "action": action,
                        "detail": f"等待 {timeout_ms}ms",
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "action": action,
                        "error": f"wait 超时: {e}",
                    }

            # dialog 操作无需 CSS target：注册一次性对话框处理器，
            # 供后续 click 触发的 window.confirm 使用
            if action == "dialog":
                mode = (value or "accept").lower()
                if mode not in ("accept", "dismiss"):
                    return {
                        "success": False,
                        "action": action,
                        "error": f"dialog 模式无效: {value}（应为 accept/dismiss）",
                    }
                self._register_dialog_handler(page, mode, prompt_text=step.get("prompt_text"))
                return {
                    "success": True,
                    "action": action,
                    "detail": f"注册对话框处理器: {mode}",
                }

            # 所有其他操作都需要 target
            if not target:
                return {"success": False, "action": action, "error": "缺少 target 选择器"}

            # seed 的 target 是 localStorage 键（非 CSS 选择器），需在通用选择器等待前处理
            if action == "seed":
                # 写入 localStorage 后重载页面，使应用按新数据重新渲染：
                # target = 存储键，value = 原始 JSON 字符串（直接写入，不解析）
                await page.evaluate(
                    "(kv) => localStorage.setItem(kv[0], kv[1])",
                    [target, value],
                )
                await page.reload(wait_until="domcontentloaded", timeout=15000)
                await self._wait_stable(page)
                return {"success": True, "action": action, "target": target}

            # mock_api：拦截 URL 模式并返回固定 JSON，用于离线验证依赖外部 API
            # 的场景（如 Open-Meteo / 时间服务器）。target = URL 模式（Playwright
            # glob，如 https://api.open-meteo.com/*），value = JSON 响应体。
            # route 注册在 page 上，reload/导航后仍保留（同一 page 对象）。
            if action == "mock_api":
                try:
                    # mock 隔离（fix-fix-stashpop 族谱爆炸根因修正）：拦截同页 SSE
                    # 推流。活体 dashboard 的 watcher 经 /api/stream 推送 'state'
                    # 消息，前端 handleSSEEvent 直接用真实 specs 调 renderView，
                    # 绕过已 mock 的 REST 路由，把 mock 场景的 DOM 污染成真实
                    # STATE.md 内容（如 clean-path 场景 mock 1 条无 error 的 spec
                    # 却渲染出 6 个真实信息子行）→ 断言必然失败 → 伪失败被记为
                    # 产品 bug → bug-found → 派生 fix 子 SPEC 空转完整周期。
                    # 在首个 mock_api 注册时一并拦截 SSE（route 持久于 page，
                    # 导航后仍生效；空 body 使 EventSource 无数据可收）。
                    if getattr(page, "_fenix_sse_blocked", False) is not True:
                        # 以页面对象自身属性标记（admin 修 2026-08-29）：此前用
                        # id(page) 去重，页面对象被 GC 后 id 复用会导致后续场景
                        # 误判「已拦截」而跳过 SSE 隔离。
                        page._fenix_sse_blocked = True

                        async def _hold_sse(route):
                            # 故意不 fulfill：让 /api/stream 请求永久挂起，
                            # EventSource 停在 CONNECTING。此前的「空 body 200」
                            # 方案会被浏览器立刻关闭流 → EventSource 原生自动
                            # 重连 → app.js sse.onopen 在重连（非首次）时调用
                            # load() 整页重拉 → 冻结 mock 数据把已删除/已变更的
                            # 行重新加回 DOM（如删除场景「行仍在」的非确定性伪
                            # 失败，正是重连重拉与断言时序竞争的结果）。
                            return

                        await page.route("**/api/stream*", _hold_sse)
                    # mock 状态码（admin 修 2026-08-29：族谱爆炸根因之一）：
                    # 场景可携带 "status"（如 409/500）模拟后端拒绝/异常分支。
                    # 此前硬编码 200，导致 4xx/5xx 场景的 mock 全部按成功返回，
                    # 错误 toast 断言必然失败 → 伪失败被记为产品 bug。
                    try:
                        mock_status = int(step.get("status") or 200)
                    except (TypeError, ValueError):
                        mock_status = 200
                    # Playwright URL glob：`*` 不匹配 `/`，结尾 `/*` 补成 `/**`
                    # （否则 https://host/* 无法匹配多段路径 /v1/forecast）
                    route_pattern = target[:-1] + "**" if target.endswith("/*") else target
                    await page.route(
                        route_pattern,
                        lambda route: route.fulfill(
                            status=mock_status,
                            content_type="application/json",
                            body=value,
                        ),
                    )
                    return {
                        "success": True,
                        "action": action,
                        "target": target,
                        "detail": f"已 mock API: {target}",
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error": f"mock_api 失败: {e}",
                    }

            # 窗口级操作（admin 修 2026-08-29：族谱爆炸根因之一）：
            # target=window/空 不是 DOM 元素，通用 locator.wait_for 必然超时；
            # target=body 可定位但非表单元素，fill 同样必然报错——键盘按键类
            # 步骤必须在任何 DOM 定位/填充之前分流处理。
            if target in ("window", "", "body") and action in ("scroll", "type"):
                if action == "scroll":
                    # value 为 "dx,dy" 像素位移（默认 0,300），经鼠标滚轮触发真实 scroll 事件
                    try:
                        dx, dy = (float(x) for x in (value or "0,300").split(","))
                    except ValueError:
                        dx, dy = 0.0, 300.0
                    await page.mouse.wheel(dx, dy)
                    await self._wait_stable(page)
                    return {
                        "success": True,
                        "action": action,
                        "target": target,
                        "detail": f"窗口滚动 ({dx},{dy})",
                    }
                # type：值为按键名（如 Escape/Enter）而非文本输入 → 键盘按键
                if value and not any(ch in value for ch in ("'", '"', "#", ".", "[", " ")):
                    await page.keyboard.press(value)
                    return {
                        "success": True,
                        "action": action,
                        "target": target,
                        "value": value,
                        "detail": f"键盘按键: {value}",
                    }

            # 等待目标元素可交互（.first 避免 strict mode violation）
            locator = page.locator(target).first
            await locator.wait_for(state="visible", timeout=5000)
            await self._wait_stable(page)

            if action == "click":
                # 支持 click 步骤携带 dialog 处理（accept/dismiss），
                # 处理点击后同步弹出的 window.confirm 对话框
                dialog_mode = (step.get("dialog") or "").lower()
                if dialog_mode:
                    if dialog_mode not in ("accept", "dismiss"):
                        return {
                            "success": False,
                            "action": action,
                            "target": target,
                            "error": f"dialog 模式无效: {dialog_mode}（应为 accept/dismiss）",
                        }
                    self._register_dialog_handler(
                        page, dialog_mode, prompt_text=step.get("prompt_text")
                    )
                await locator.click(timeout=5000)
                await self._wait_stable(page)
                return {"success": True, "action": action, "target": target}

            elif action == "type":
                await locator.fill(value)
                return {
                    "success": True,
                    "action": action,
                    "target": target,
                    "value": value,
                }

            elif action == "clear":
                await locator.fill("")
                return {"success": True, "action": action, "target": target}

            elif action == "select":
                await locator.select_option(value)
                return {
                    "success": True,
                    "action": action,
                    "target": target,
                    "value": value,
                }

            elif action == "scroll":
                await locator.scroll_into_view_if_needed()
                return {"success": True, "action": action, "target": target}

            elif action == "hover":
                await locator.hover()
                await self._wait_stable(page)
                return {"success": True, "action": action, "target": target}

            elif action == "wait":
                await page.wait_for_selector(target, state="visible", timeout=10000)
                return {"success": True, "action": action, "target": target}

            elif action == "contextmenu":
                # 右键点击，触发 React onContextMenu（自定义右键菜单/原生菜单阻止）
                await locator.click(button="right", timeout=5000)
                await self._wait_stable(page)
                return {"success": True, "action": action, "target": target}

            elif action == "drag":
                # 长按拖拽（模拟 pointer 手势）：target = 源卡片选择器，
                # value = 目标选择器（普通字符串）或 JSON 配置：
                #   {"to": 目标选择器, "hold": 长按ms(默认450),
                #    "dwell": 驻留ms(默认600), "via": 中间悬停选择器,
                #    "via_wait": 中间悬停ms(默认300)}
                try:
                    cfg = json.loads(value) if value.strip().startswith("{") else {"to": value}
                except Exception:
                    cfg = {"to": value}
                to_sel = cfg.get("to", "")
                if not to_sel:
                    return {
                        "success": False,
                        "action": action,
                        "error": "drag 缺少目标选择器（value 或 value.to）",
                    }
                hold = int(cfg.get("hold", 450))
                dwell = int(cfg.get("dwell", 600))
                via_sel = cfg.get("via", "")
                via_wait = int(cfg.get("via_wait", 300))

                src_box = await locator.bounding_box()
                if not src_box:
                    return {"success": False, "action": action, "error": f"源元素不可见: {target}"}
                to_locator = page.locator(to_sel).first
                await to_locator.wait_for(state="visible", timeout=5000)
                to_box = await to_locator.bounding_box()
                if not to_box:
                    return {
                        "success": False,
                        "action": action,
                        "error": f"目标元素不可见: {to_sel}",
                    }

                sx = src_box["x"] + src_box["width"] / 2
                sy = src_box["y"] + src_box["height"] / 2
                await page.mouse.move(sx, sy)
                await page.mouse.down()
                await page.wait_for_timeout(hold)  # 长按进入拖拽

                if via_sel:
                    via_locator = page.locator(via_sel).first
                    await via_locator.wait_for(state="visible", timeout=5000)
                    via_box = await via_locator.bounding_box()
                    if via_box:
                        vx = via_box["x"] + via_box["width"] / 2
                        vy = via_box["y"] + via_box["height"] / 2
                        await page.mouse.move(vx, vy, steps=8)
                        await page.wait_for_timeout(via_wait)

                tx = to_box["x"] + to_box["width"] / 2
                ty = to_box["y"] + to_box["height"] / 2
                await page.mouse.move(tx, ty, steps=8)
                await page.wait_for_timeout(dwell)
                await page.mouse.up()
                await page.wait_for_timeout(400)  # 等待 React 重渲染与持久化
                await self._wait_stable(page)
                return {"success": True, "action": action, "target": target}

            else:
                return {
                    "success": False,
                    "action": action,
                    "error": f"不支持的操作: {action}",
                }

        except Exception as e:
            error_msg = str(e)
            # 错误分类
            if "intercepts pointer events" in error_msg:
                error_type = "click_intercepted"
            elif "timeout" in error_msg.lower():
                error_type = "element_not_found_or_not_actionable"
            elif "not visible" in error_msg.lower():
                error_type = "element_not_visible"
            else:
                error_type = "unknown"

            return {
                "success": False,
                "action": action,
                "target": target,
                "error_type": error_type,
                "error": error_msg,
            }

    # ── 稳定等待 ───────────────────────────────────────────────

    async def _wait_stable(self, page):
        """等待页面布局稳定。

        0. 等待首帧真实渲染（body 出现非空文本）
        1. 等待布局偏移分数（CLS）稳定
        （networkidle 等待已移除，见下）

        admin 修 2026-09-06（add-spec-hooks 第 1 轮 4 个 web 场景白屏 env
        阻塞）：CSR SPA 冷启动时 domcontentloaded 后 body 仍空白（JS 包
        尚未执行完），而空白页没有任何布局偏移 → CLS 恒「稳定」，本方法
        立即返回，白屏原样穿透到断言窗口（元素不存在＝伪失败；重载机器
        上冷浏览器首帧渲染实测超出 500ms+5s 断言窗口，judge 复现实证）。
        先等 body 出现非空文本再进入 CLS 判定：已渲染页面立即通过（零
        附加延迟，不影响既有场景断言时点），空白页最多等 8s（渲染失败/
        纯画布等极端形态退化为原行为，不放大失败）。

        admin 修 2026-08-29（fix-fix-stashpop 族谱爆炸根因之一）：dashboard
        页面常驻 SSE 连接（/api/stream；mock 场景中被 _hold_sse 永久挂起，
        真实场景中由 EventSource 保持长连），networkidle 在两种形态下都
        永不满足 → 此前每次 _wait_stable 必然吃满 3s 超时。后果：
        1) 全部场景每次稳定等待白耗 3s；
        2) 点击类步骤后断言时点被拖后 3s+，越过 UI 瞬时反馈窗口
           （如 clearSpecError 失败态 2s 自动复位）→ text_contains 伪失败
           → bug-found → 派生 fix 子 SPEC 空转完整周期（族谱爆炸推手）。
        稳定性判定改为完全依赖 CLS 稳定 + 场景显式 wait 步骤。
        """
        # 首帧真实渲染：等待 body 出现非空文本（空白页 CLS 恒稳定，见 docstring）
        try:
            await page.wait_for_function(
                "() => (document.body && document.body.innerText || '').trim().length > 0",
                timeout=8000,
            )
        except Exception:
            # B1（fenixd-registry-ignored-false-attribution-loop）：首帧 8s 超时
            # 不再完全无声——返回 False，navigate 步骤据此落 first_frame_ok=False，
            # env_gate.is_blank_render_candidate 据此把白屏场景降级 blocked-env
            # （客户端渲染失败不进产品/场景归因）。「不在此处判失败」的原语义
            # 保留：极端形态（纯画布等）仍走 CLS 退化，不放大为步骤失败。
            return False

        # CLS 稳定
        try:
            await page.evaluate("""() => {
                return new Promise((resolve) => {
                    let lastScore = 0;
                    let stableCount = 0;
                    const observer = new PerformanceObserver((list) => {
                        for (const entry of list.getEntries()) {
                            if (entry.hadRecentInput) continue;
                            const currentScore = entry.value;
                            if (Math.abs(currentScore - lastScore) < 0.001) {
                                stableCount++;
                                if (stableCount >= 3) {
                                    observer.disconnect();
                                    resolve(true);
                                }
                            } else {
                                stableCount = 0;
                                lastScore = currentScore;
                            }
                        }
                    });
                    observer.observe({type: 'layout-shift', buffered: true});
                    // 最多等 500ms 即视为稳定（不要求零偏移）
                    setTimeout(() => {
                        observer.disconnect();
                        resolve(true);
                    }, 500);
                });
            }""")
        except Exception:
            pass  # 浏览器不支持 CLS API 时跳过

        return True

    # ── 数据采集 ───────────────────────────────────────────────

    async def screenshot(self, page, name: str, output_dir: Path) -> dict:
        """截图并保存到磁盘。

        落盘后调用 screenshot_lab.classify_screenshot 做健全性判定（纯算法，
        spec screenshot-evidence-labeling），标签（blank_screenshot /
        low_contrast + 量化指标）并入返回值。判定自身异常时返回空标签且
        不抛出——截图主流程不受健全性判定影响。

        Returns:
            {
                "path": 截图文件的绝对路径,
                "labels": 健全性标签 dict（无标签=正常，兼容旧消费方）,
            }
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{name}.png"
        await page.screenshot(path=str(path), full_page=False)
        from .screenshot_lab import classify_screenshot

        labels = classify_screenshot(str(path))
        return {"path": str(path), "labels": labels}

    async def capture_dom_snapshot(self, page) -> dict:
        """捕获结构化DOM快照（用于断言和调试）。

        递归采集可见元素的 tag/id/classes/text/rect/attributes。
        最大深度 10 层，防止无限递归。
        """
        return await page.evaluate("""() => {
            function snapshot(el, depth) {
                if (!el || depth > 10) return null;
                const info = {
                    tag: el.tagName ? el.tagName.toLowerCase() : null,
                    id: el.id || null,
                    classes: el.className
                        ? (typeof el.className === 'string'
                            ? el.className.split(' ').filter(c => c)
                            : [])
                        : [],
                    text: (el.textContent || '').trim().substring(0, 200),
                    visible: el.offsetParent !== null,
                    rect: el.getBoundingClientRect(),
                    attributes: {},
                    children: []
                };
                // 关键属性
                for (const attr of ['data-testid', 'href', 'type', 'placeholder',
                                     'value', 'aria-label', 'role']) {
                    const val = el.getAttribute(attr);
                    if (val) info.attributes[attr] = val;
                }
                // 递归子元素
                for (const child of el.children) {
                    const s = snapshot(child, depth + 1);
                    if (s) info.children.push(s);
                }
                return info;
            }
            return snapshot(document.body, 0);
        }""")

    def get_console_errors(self, context) -> list[str]:
        """获取在 context 生命周期中收集的控制台错误。"""
        return getattr(context, "_console_errors", [])

    def get_network_errors(self, context) -> list[str]:
        """获取在 context 生命周期中收集的网络错误。"""
        return getattr(context, "_network_errors", [])
