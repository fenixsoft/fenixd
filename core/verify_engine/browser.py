"""
browser.py — Playwright 浏览器管理器

职责：
  - 浏览器生命周期管理（启动/复用/关闭）
  - 用户操作执行（click/type/scroll/select/wait/navigate）
  - 数据采集（截图、console日志、网络错误）
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
import inspect
import json
import math
import os
import re
import socketserver
import tempfile
import threading
from pathlib import Path
from typing import Optional

from .path_safety import safe_component

# playwright 类型化异常（code-review item ea1ef016ced3）：顶层 error_type
# 分类优先按异常类型分流，不依赖随版本漂移的错误文案；playwright 未安装的
# 环境（本模块由 web_runner 间接导入，启动路径才真正触达 playwright）回退
# 空元组——isinstance(x, ()) 恒 False，分类退回纯文案兜底，行为不劣化。
try:
    from playwright.async_api import TimeoutError as _PlaywrightTimeoutError
except ImportError:  # pragma: no cover - 无 playwright 环境仅走文案兜底
    _PlaywrightTimeoutError = ()

# 顶层异常分类的文案子串兜底表（code-review item ea1ef016ced3）：从
# execute_action 内联字面量收敛为模块级常量，便于随 playwright 版本维护。
# 注意命中顺序敏感：click_intercepted 必须最先判（点击超时的错误日志体常含
# 「intercepts pointer events」重试原因，既有口径归为 click_intercepted）。
_CLICK_INTERCEPTED_MARKER = "intercepts pointer events"
_TIMEOUT_MARKER = "timeout"
_NOT_VISIBLE_MARKER = "not visible"

# 页面内 Promise 型 evaluate 的外层超时秒数（code-review item c8c04ed298b8）：
# page.evaluate 无超时语义，页面主线程挂起/死循环时页内 setTimeout/
# requestAnimationFrame 兜底定时器永不触发、await 永久挂起。对依赖页内定时
# 器 resolve 的两处 evaluate 显式包 asyncio.wait_for，超时按「注入失败」
# 既有容错路径处理。
_IN_PAGE_EVALUATE_TIMEOUT_S = 10


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """多线程 HTTP 服务器（ThreadingMixIn，每个请求在独立线程中处理），用于提供静态文件服务。"""

    daemon_threads = True
    allow_reuse_address = True


def _make_handler(directory: str):
    """创建绑定到指定目录的处理器类。"""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, format, *args):
            pass  # 抑制日志

        def end_headers(self):
            # 不附加 CORS 头（code-review item 5a964f04fa22）：被测页面与本
            # 静态服务同源加载自身资源，本不需要跨域授权；通配 CORS 反而
            # 允许验证浏览器中任意页面跨源读取 dist 下的文件与目录列表
            self.send_header("Cache-Control", "no-store, must-revalidate")
            super().end_headers()

    return Handler


# console/network 错误收集条数上限（code-review item eba5cdf51753）：
# 错误循环型页面（SSE 重连风暴、轮询接口持续 4xx/5xx）在单场景窗口内
# 可累计成百上千条，无界收集会经 no_console_error / no_network_error
# 断言结果的 errors 字段整表进入 report.json 与 judge 归因上下文
_MAX_COLLECTED_ERRORS = 200

# 无 target wait 步骤的暂停毫秒数上限（code-review item 03121e3f15f4）：
# planner 误写（毫秒/秒混用、或 "1e9" 这类超大有限值）会被 float() 正常
# 解析并传给 wait_for_timeout 如实等待，而引擎对单场景没有超时包裹，该
# 场景会持续占用并行信号量槽与浏览器 context 直至外部监督超时介入，整轮
# 验证窗口被单条场景声明占满。10 分钟覆盖合法长等待，超过按配置错误拦截
_MAX_WAIT_MS = 600_000


def _capped_append(bucket: list[str], entry: str) -> None:
    """向错误收集列表追加一条，达到 _MAX_COLLECTED_ERRORS 后截断。

    触顶时仅追加一次 [truncated] 标记保留「后续还有错误」信号；断言侧
    （_assert_no_console_error / _assert_no_network_error）会把该标记从
    errors/pass 计算中剔除并以 truncated 标志透出，避免在
    external_net_errors_ok 豁免路径上把标记本身误计为控制台错误，或 judge
    读网络错误清单时混入非错误记录。
    """
    if len(bucket) < _MAX_COLLECTED_ERRORS:
        bucket.append(entry)
    elif len(bucket) == _MAX_COLLECTED_ERRORS:
        bucket.append(f"[truncated] 错误条数达到上限 {_MAX_COLLECTED_ERRORS}，后续已截断")


# window/body type 步骤键盘按键的命名键词表（code-review item 9d40ace9827c）：
# 启发式（仅排除引号/#/./[/空格）会放行普通文本（如 "hello"），press 抛错
# 被顶层 except 归为 unknown——多字符 value 须命中本表（单字符按键如
# "a"/"1" 直接放行），否则走 invalid_type_target 结构化失败
_KEYBOARD_NAMED_KEYS = frozenset(
    {
        "Enter", "Tab", "Backspace", "Delete", "Insert", "Escape",
        "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
        "Home", "End", "PageUp", "PageDown",
        "Space", "Control", "Alt", "Shift", "Meta", "ControlOrMeta",
        "CapsLock", "NumLock", "ScrollLock", "Pause", "PrintScreen",
        "ContextMenu", "Clear", "Select",
    }
    | {f"F{n}" for n in range(1, 13)}
)
# 组合键修饰键（Control+a、Shift+Tab 等 press 合法形态）
_KEYBOARD_MODIFIER_KEYS = frozenset({"Control", "Alt", "Shift", "Meta", "ControlOrMeta"})


def _is_valid_press_key(value: str) -> bool:
    """判断 window/body type 步骤的 value 是否为合法键盘按键名。

    允许：单字符按键（"a"/"1"）、命名键（Escape/ArrowDown/...）、
    「修饰键+键」组合（Control+a / Shift+Tab）。其余（普通文本如
    "hello"）返回 False——避免 press 抛错被顶层 except 归为 unknown
    （code-review item 9d40ace9827c）。
    """
    if not value:
        return False
    if len(value) == 1:
        return True
    parts = value.split("+")
    if len(parts) > 1:
        if not all(m in _KEYBOARD_MODIFIER_KEYS for m in parts[:-1]):
            return False
        parts = parts[-1:]
    # 末段：单字符按键或命名键
    return len(parts[0]) == 1 or parts[0] in _KEYBOARD_NAMED_KEYS


# mock 路由 glob → 正则编译缓存（code-review item 9af293ddcb49）：response
# 监听对每条 4xx/5xx 都要查 mock 命中，避免逐条重复编译。
_GLOB_RE_CACHE: dict = {}
# 缓存条目上限（code-review item ab5534d7b2aa）：daemon 常驻进程跨多轮
# spec/场景集运行时 pattern 只增不减，超阈值整表清空（正则重编译成本可忽略）
_GLOB_RE_CACHE_MAX = 512


def _mock_url_hit(url: str, patterns) -> bool:
    """判断 URL 是否命中已注册 mock 路由的 glob pattern。

    与 Playwright route 匹配同口径：``**`` 匹配任意字符、``*`` 匹配除
    ``/`` 外任意字符、``?`` 匹配单个非 ``/`` 字符。
    """
    for pat in patterns:
        regex = _GLOB_RE_CACHE.get(pat)
        if regex is None:
            regex = re.compile(
                "".join(
                    ".*" if t == "**"
                    else "[^/]*" if t == "*"
                    else "[^/]" if t == "?"
                    else re.escape(t)
                    for t in re.split(r"(\*\*|\*|\?)", pat)
                )
            )
            _GLOB_RE_CACHE[pat] = regex
            if len(_GLOB_RE_CACHE) > _GLOB_RE_CACHE_MAX:
                _GLOB_RE_CACHE.clear()
        if regex.fullmatch(url):
            return True
    return False


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

    页内 Promise 靠 requestAnimationFrame 兜底 resolve，而 page.evaluate 无
    超时语义：页面主线程挂起/死循环时兜底定时器永不触发、await 永久挂起，
    故外层再包 asyncio.wait_for（下限 _IN_PAGE_EVALUATE_TIMEOUT_S，并随
    timeout_ms 抬升以免截短配置的长等待，code-review item c8c04ed298b8 /
    89577553b196），超时同按注入失败路径返回 False。

    Args:
        page: Playwright Page 对象。
        timeout_ms: 等待上限（毫秒）；0/负值跳过等待；非有限/超 _MAX_WAIT_MS
            收敛为 _MAX_WAIT_MS。

    Returns:
        True=动画全部静置（或跳过等待）；False=达上限仍有未完成动画（或注入失败）。
    """
    if not timeout_ms or timeout_ms <= 0:
        return True
    # 非有限/超上限收敛（code-review item c728b2991374）：与任何数比较恒为
    # False 的脏值（inf/nan）绕过上方入口守卫，timeout_ms=+inf 会同时抬升
    # 页内 deadline 与外层 wait_for 上限，页面主线程挂起时「下限 10s 逃逸
    # 通道」彻底失效、永久挂起。回落到 _MAX_WAIT_MS（与 execute_action 的
    # wait/drag 分支对毫秒数的上限同口径）而非按注入失败返回 False，helper
    # 自身满足「任何输入都有界等待」，不依赖调用方自律
    if not math.isfinite(timeout_ms) or timeout_ms > _MAX_WAIT_MS:
        timeout_ms = _MAX_WAIT_MS
    try:
        settled = await asyncio.wait_for(
            page.evaluate(
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
            ),
            # 外层兜底取 max(固定下限, 页内 deadline + 余量)（code-review item
            # 89577553b196）：固定 _IN_PAGE_EVALUATE_TIMEOUT_S 会把 >10s 的
            # timeout_ms 在页内 deadline 未到时静默截短、走 except 按注入失败
            # 返回 False；下限仍保留页面主线程挂起时的逃逸通道
            timeout=max(_IN_PAGE_EVALUATE_TIMEOUT_S, timeout_ms / 1000 + 1),
        )
        return bool(settled)
    except Exception:
        # 注入失败（老内核/异常页面）按超时退化处理，不放大失败
        # （含上方 wait_for 超时：页面主线程挂起时页内 rAF 兜底不触发）
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
        # 日志接口形态（code-review item 132b2d2776ab）：构造期探测一次
        # fenixd Logger 的 (component, message) 双参 / 标准 logging 单参接口
        # 并缓存，运行期直接按形态调用——不再每条日志先吃一次 TypeError 再
        # 回退（异常控制流有开销，且会把 log_fn 实现内部的真实 TypeError 误
        # 吞改走回退分支）。None=签名不可内省（Mock/异构 callable），_log
        # 运行期保留旧的逐次探测兜底。
        self._log_two_arg = self._detect_two_arg_logger()

        # 扩展项目 HTTP 服务器
        self._dev_server: Optional[http.server.HTTPServer] = None
        self._dev_server_port: int = 0
        self._base_url: str = ""
        self._is_extension_project: bool = False

        # 独立 HTML 入口点支持
        self._use_verify_html: bool = False

        # 截图文件名唯一后缀序号（code-review item c593862ba608）：
        # 见 screenshot()——不同原始名经 safe_component 折叠为同一文件名时防
        # 互相覆盖。
        self._screenshot_seq = 0

        # （dialog 待摘一次性处理器亦记录在 page 对象属性
        # _fenix_pending_dialog_handler 上——并发场景共享本管理器，实例级
        # 单槽会摘错别的场景页面的处理器并让本页旧 mode 残留与新处理器同响
        # 一次对话框，见 _register_dialog_handler（code-review item
        # 557b3726aad6）。）

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

        # poll_interval 调小（code-review item 359d056ab56f）：_stop_dev_server
        # 在 async stop()/start() 失败路径内同步调用 shutdown()，后者会等
        # serve_forever 线程走到下一个轮询点才返回，缺省 0.5s 间隔使事件循环
        # 最坏被阻塞约 0.5s（并行场景的事件回调随之延迟）——缩到 50ms 量级，
        # 轮询开销可忽略
        thread = threading.Thread(
            target=self._dev_server.serve_forever, args=(0.05,), daemon=True
        )
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
        # 避免 dist 残留多份历史 bundle 时字典序选中旧版本。
        # glob 枚举与 stat 之间存在文件系统竞态（并发构建清理/替换、
        # 临时文件消失）：单文件 stat 失败跳过该候选，不因个别文件消失
        # 整体降级回退 index.html——候选全部不可 stat（列表为空）才走
        # 回退分支，与 serving._probe_dist_freshness 的容错口径对齐
        # （code-review item c2ca81061541）。
        def _mtime_desc(candidates):
            """预 stat 每个候选（失败跳过），按 (mtime, name) 降序返回。"""
            stats = []
            for p in candidates:
                try:
                    stats.append((p.stat().st_mtime, p.name, p))
                except OSError:
                    continue
            stats.sort(key=lambda t: (t[0], t[1]), reverse=True)
            return [t[2] for t in stats]

        js_files = _mtime_desc(assets_dir.glob("index.html-*.js"))
        css_files = _mtime_desc(assets_dir.glob("index-*.css"))

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
        # 原子写（对齐 save_scenarios / settings_routes._atomic_write_text
        # 惯例，code-review item 8eea9dd16d3a）：同目录临时文件 + os.replace，
        # 写盘中途被杀不会在 dev server 正在服务的路径上留下截断的 HTML。
        fd, tmp_path = tempfile.mkstemp(
            dir=str(verify_path.parent), prefix=f".{verify_path.name}-", suffix=".tmp"
        )
        try:
            # fdopen 失败路径显式接管（fs_ops.atomic_write_json /
            # cbb57806fbfd 统一口径）：with 的 close 只在 fdopen 成功后才
            # 生效，fdopen 自身抛错时裸 fd 无人关闭——f 为 None 时兜底
            # os.close。
            f = None
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
                f.write(html)
                f.flush()
                os.fsync(f.fileno())
            finally:
                if f is not None:
                    f.close()
                else:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            os.replace(tmp_path, str(verify_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        self._use_verify_html = True
        self._log("info", f"已生成独立 HTML 入口: verify.html (JS={js_path}, CSS={css_path})")

    def _detect_two_arg_logger(self) -> Optional[bool]:
        """探测 logger 是否为 fenixd 双参 (component, message) 日志接口。

        fenixd Logger.info(component, message, context=None) 有 >=2 个位置
        形参 → 双参；标准 logging.Logger.info(msg, *args, **kwargs) 与
        _NullLogger.info(*_args) 位置形参 <2 → 单参。签名不可内省（Mock/
        异构 callable）返回 None，由 _log 运行期按旧探测兜底。
        """
        log_fn = getattr(self._logger, "info", None)
        if log_fn is None:
            return False
        try:
            parameters = list(inspect.signature(log_fn).parameters.values())
        except (TypeError, ValueError):
            return None
        return (
            sum(
                1
                for p in parameters
                if p.kind
                in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            )
            >= 2
        )

    def _log(self, level: str, message: str):
        """内部日志辅助方法。

        兼容两种 logger 接口（形态在构造期探测并缓存，
        code-review item 132b2d2776ab——不再每条日志靠 TypeError 回退）：
        - 标准 logging.Logger / _NullLogger: info(msg) → 单参数消息
        - fenixd Logger: info(component, message) → 双参数（component 作为第一参数）
        """
        if self._logger:
            log_fn = getattr(self._logger, level, None)
            if log_fn:
                if self._log_two_arg is None:
                    # 构造期内省失败的异构 logger：保留旧的逐次探测兜底
                    try:
                        log_fn(f"[browser] {message}")
                    except TypeError:
                        # 回退到 fenixd Logger 的 (component, message) 调用
                        log_fn("browser", message)
                elif self._log_two_arg:
                    log_fn("browser", message)
                else:
                    log_fn(f"[browser] {message}")

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

        # 半初始化残留释放（code-review item 00cdf0b6ee65）：上次 start() 在
        # async_playwright().start() 成功后 chromium.launch 抛错时，_playwright
        # 已驻留而 _started 仍为 False；不经 stop() 重入 start() 会直接覆盖
        # self._playwright 引用，前一个 playwright driver 进程无人释放直至
        # 宿主进程退出。此处 best-effort 释放旧实例后再继续。
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as e:
                self._log(
                    "warning", f"释放残留 playwright 实例失败: {type(e).__name__}: {e}"
                )
            self._playwright = None

        try:
            self._playwright = await async_playwright().start()
            launch_args = [
                "--disable-animations",
                "--disable-gpu",
                "--font-render-hinting=none",
            ]
            # 沙箱按运行环境注入（code-review item 03879984b764）：仅 root
            # （euid==0，Chromium 渲染进程沙箱在此环境无法启用）才回退
            # --no-sandbox；其余环境保留默认沙箱隔离，避免被测页面侧漏洞
            # 直达宿主。geteuid 在非 Unix 平台不存在，按非 root 处理。
            if getattr(os, "geteuid", None) is not None and os.geteuid() == 0:
                launch_args.append("--no-sandbox")
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=launch_args,
            )
        except Exception:
            # launch 失败路径回收本地 HTTP 服务器（code-review item bf93a61f4d20）：
            # _start_dev_server 已在上面先行启动，此处抛错若不回收，_started 仍为
            # False 而监听 socket 与服务器线程驻留至进程退出；调用方在 start()
            # 失败后通常不会（也无法配对地）调用 stop()，无人值守 daemon 跨轮
            # 重试每次失败泄漏一个。best-effort：与残留 playwright 释放同款容错。
            try:
                self._stop_dev_server()
            except Exception as e:
                self._log(
                    "warning", f"回收本地 HTTP 服务器失败: {type(e).__name__}: {e}"
                )
            # launch 失败路径同步回收本轮 playwright driver（code-review item
            # 57687aa447db）：async_playwright().start() 成功后 chromium.launch
            # 抛错时 _playwright 已驻留，与上方服务器同理不依赖下轮 start() 重入
            # 才释放，把回收时机提前到失败当场。容错与 stop() 的 playwright.stop
            # 同款；_playwright 仅 start/stop 两条路径引用，置 None 无共享影响
            # （若异常发生在 start() 本身则此处为 None，无操作）。
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    self._log(
                        "warning", f"释放 playwright 实例失败: {type(e).__name__}: {e}"
                    )
                self._playwright = None
            raise
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

        # 收集控制台错误和网络错误（条数上限见 _MAX_COLLECTED_ERRORS：
        # 错误循环型页面单场景窗口可累计成百上千条，无界收集撑大报告）
        console_errors: list[str] = []
        network_errors: list[str] = []

        context.on(
            "page",
            lambda p: p.on(
                "console",
                lambda msg: (
                    _capped_append(console_errors, f"[{msg.type}] {msg.text}")
                    if msg.type == "error"
                    else None
                ),
            ),
        )
        # 未捕获 JS 异常走 pageerror 事件、不产生 console error 消息
        # （code-review item 6e48bf397533）：缺此监听时页面运行时抛错
        # （如点击处理器 TypeError）不会进入收集，no_console_error 断言
        # 与 judge 归因均不可见。并入同一桶按 _capped_append 口径截断；
        # 断言侧网络层豁免按 net::ERR_ 等标记过滤，pageerror 条目不受
        # 豁免影响（运行时异常属产品缺陷信号，应严格失败）
        context.on(
            "page",
            lambda p: p.on(
                "pageerror",
                lambda err: _capped_append(console_errors, f"[pageerror] {err}"),
            ),
        )
        context.on(
            "page",
            lambda p: p.on(
                "response",
                lambda resp: (
                    _capped_append(network_errors, f"{resp.status} {resp.url}")
                    if resp.status >= 400
                    # mock_api 刻意 fulfill 的 4xx/5xx（409/500 分支场景必需，
                    # 见 execute_action）是场景语义内的合法响应，不计入
                    # network_errors：否则「mock 错误码验证错误提示 +
                    # no_network_error 断言」组合会系统性伪失败
                    # （code-review item 9af293ddcb49）
                    and not _mock_url_hit(resp.url, getattr(p, "_fenix_mock_patterns", ()))
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
            # 首帧等待结果落页面对象属性（code-review item c109de7ea35b）：
            # 本方法返回值只表达导航成败，_wait_stable 的首帧 8s 超时此前被
            # 丢弃，扩展项目场景入口（web_runner.execute）的瞬态白屏无法进
            # env_gate 白屏降级。调用侧读取 _fenix_nav_first_frame_ok 写入与
            # execute_action navigate 分支同款的结构化标记；每场景独立
            # context/page（execute 内 new_page），无跨场景残留。
            first_frame_ok = await self._wait_stable(page)
            page._fenix_nav_first_frame_ok = first_frame_ok
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
        # prompt_text 同款 str 归一（code-review item b44580320e5d）：target/
        # value/dialog 已在运行层入口做 str 归一（08ef327b2c7e /
        # 394576642420 / 5f5d31a35c76），prompt_text 此前原样透传——步骤里
        # 数值/布尔形态的 prompt_text 会让 dialog.accept(prompt_text=<数值>)
        # 在 playwright 协议层抛类型错误，异常只经 _reap_dialog_task 落一条
        # warning，声明的 prompt 意图静默丢失、对话框回落 Playwright 默认
        # dismiss，后续步骤失败被归因到时序/元素。None 保持 None（缺省语义
        # =accept 不带文本），其余 str() 归一
        if prompt_text is not None and not isinstance(prompt_text, str):
            prompt_text = str(prompt_text)

        def _reap_dialog_task(task, _mode=mode):
            # 收割 accept/dismiss 任务的异常（code-review item 5804ee753ce8）：
            # fire-and-forget 任务此前无人 await，accept 竞态失败（对话框已被
            # Playwright 侧处理、页面已关闭等）只在 GC 时产生「Task exception
            # was never retrieved」噪声，场景声明的 accept 意图静默丢失、对话
            # 框悬挂回落 Playwright 默认 dismiss，后续步骤超时被误归因为时序/
            # 元素问题——落 warning 日志使失败可观测、可与后续失败正确归因
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                self._log(
                    "warning",
                    f"对话框 {_mode} 处理任务失败（声明的对话框意图可能未生效）: "
                    f"{type(exc).__name__}: {exc}",
                )

        def _handle(dialog, _mode=mode, _text=prompt_text):
            try:
                if _mode == "accept":
                    task = (
                        dialog.accept(prompt_text=_text) if _text is not None else dialog.accept()
                    )
                else:
                    task = dialog.dismiss()
                asyncio.ensure_future(task).add_done_callback(_reap_dialog_task)
            except Exception:
                pass

        # 注册前先摘除上一轮残留的未消费 once 处理器（code-review item
        # 4c32769cc34e）：声明的 dialog 步骤之后 click 实际未弹框时，once
        # 处理器不会自动移除，会按旧 mode 吞掉后续步骤触发的对话框；摘除后
        # 同页至多挂一个处理器，也消除一次对话框同时唤醒多个 once 回调的问题。
        # 待摘引用挂在 page 对象上（与 _fenix_sse_blocked 同款页面对象属性
        # 惯例，code-review item 557b3726aad6）：并发场景共享同一
        # BrowserManager（每场景独立 context/page），实例级单槽会摘到别的
        # 场景页面上的处理器、放走本页旧 mode 残留
        stale = getattr(page, "_fenix_pending_dialog_handler", None)
        if stale is not None:
            try:
                page.remove_listener("dialog", stale)
            except Exception:
                pass
        page.once("dialog", _handle)
        page._fenix_pending_dialog_handler = _handle

    # [fenix-ignore:031f326ccf92] 结构性拆分超出 code-fix 最小改动边界：十余动作分支共享同一顶层 try/except 错误分类与 target/value 归一口径，抽 handler 需穿参并保 raise 穿透语义、回归风险大于收益
    async def execute_action(self, page, step: dict) -> dict:
        """执行单个用户操作。

        支持的操作类型（词表权威源：scenarios.py 的 WEB_ACTIONS，以该处为准）：
        - navigate: 页面导航
        - click: 点击元素（自动检测click interception，可携带 dialog/prompt_text）
        - type: 输入文本（先清空再填充）；target=window/body 时 value 为键盘按键名
        - clear: 清空输入框
        - select: 下拉选择
        - scroll: 滚动到元素；target=window/body 时 value 为 "dx,dy" 像素位移
        - wait: 等待指定选择器可见；无 target 时 value 为暂停毫秒数
        - hover: 悬停元素
        - contextmenu: 右键点击（触发 onContextMenu）
        - drag: 长按拖拽（target=源元素，value=目标选择器或 JSON 配置）
        - seed: 写 localStorage（target=键，value=JSON 字符串）后重载页面
        - dialog: 注册一次性对话框处理器（value=accept/dismiss）
        - mock_api: 拦截 URL 模式返回固定 JSON（target=glob，value=响应体，
          status=HTTP 状态码）

        对扩展项目：
        - navigate to about:blank 自动重定向到本地 HTTP 服务器的应用页面

        Returns:
            {"success": bool, "action": str, "target"?: str, "error"?: str,
             "error_type"?: str, ...}
        """
        action = step.get("action", "")
        # target 与 value 同款 str 归一（code-review item 394576642420）：
        # 数值/布尔形态的 target 此前原样透传，page.locator(target) 抛
        # TypeError 落顶层 except 归为 unknown，报错不可定位——复用 value
        # 的归一口径（08ef327b2c7e，仅以 is None 判缺失）
        _raw_target = step.get("target")
        target = "" if _raw_target is None else str(_raw_target)
        # value 归一为字符串（code-review item 08ef327b2c7e）：场景 JSON 中
        # 数值/布尔形态的 value（planner 产物并非不可能）此前会在
        # startswith/fill/select_option/json.loads 等分支抛
        # AttributeError/TypeError 并被顶层 except 归为 unknown，报错不可定位。
        # 仅以 is None 判缺失（code-review item 205fe924442d）：or "" 会把
        # 显式 0/False 当成「未提供」清空掉，type/select 步骤静默偏离场景意图
        _raw_value = step.get("value")
        value = "" if _raw_value is None else str(_raw_value)

        try:
            if action == "navigate":
                # 扩展项目：将 about:blank 重定向到验证 HTML
                # 统一去首尾空白（code-review item 5a0c89e01388）：下方
                # ^https?:// 校验对 strip 后的值判定（带空白的合法地址会
                # 通过），而 goto 用原始值会被 Playwright 以 invalid URL
                # 拒绝并归为 unknown——与 _find_step_url_candidate 的
                # 去空白口径对齐（code-review item 48320e6f6abb）
                actual_url = value.strip()
                # 相对/非法 navigate URL 直接显式失败（2026-08-28：相对路径
                # 导致 about:blank 白屏、整轮断言全灭的假失败）。不注入任何
                # 默认 base/端口——被测实例地址只有运行环境自己知道，此类
                # 失败应退回 plan 阶段重新生成绝对 URL 场景。
                # 校验先于项目类型分支生效（code-review item 3e0e5251e751）：
                # extension 项目对 ftp:// 等非 http(s) 目标此前直达 page.goto
                # 抛 Playwright 异常被顶层 except 归为 unknown，与 web 项目
                # 同类输入的归因口径不对称。extension 的合法例外：空/about:*
                # （下方重定向到本地 HTTP 服务）与 chrome-extension://（同款
                # 回退），不视为非法 URL。
                # scheme 大小写不敏感匹配（code-review item bbca5c47bea6）：
                # RFC 3986 中 scheme 大小写等价，HTTPS://EXAMPLE.com/x 为合法
                # 绝对地址且 goto 实际可达，此前大小写敏感匹配会把它误判成
                # invalid_navigate_url，与上方「只拦 100% 是错误形态」的
                # 零误杀取向不符
                if not re.match(r"^https?://", str(value).strip(), re.IGNORECASE) and not (
                    self._is_extension_project
                    and (
                        actual_url == ""
                        or actual_url.startswith("about:")
                        or actual_url.startswith("chrome-extension://")
                    )
                ):
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_navigate_url",
                        "error": (
                            f"navigate URL 必须为绝对地址（http/https），"
                            f"不注入默认 base/端口: {value!r}"
                        ),
                        "detail": f"非法 navigate 目标 {value!r}",
                    }
                # chrome-extension:// URL 在当前验证浏览器（未加载扩展）中不可达
                # （Planner 可能生成 chrome-extension://__MSG_@@extension_id__/ 之类目标），
                # 统一回退到本地 HTTP 服务器（navigate_to_app 同款入口），避免场景判 fail。
                # 重定向判定统一用 strip 后的 actual_url（code-review item
                # 4ce84c27a018）：与上方归一及 ^https?:// 校验同口径——带首尾
                # 空白的目标（如 " about:blank "）此前三个重定向分支全不命中，
                # goto 落在字面空白页，后续步骤连锁失败
                if self._is_extension_project and actual_url.startswith("chrome-extension://"):
                    self._log(
                        "warning",
                        f"navigate 目标 {value} 为 chrome-extension:// URL"
                        "（验证浏览器未加载扩展），已回退到本地 HTTP 服务器",
                    )
                    entry_html = "verify.html" if self._use_verify_html else "index.html"
                    actual_url = f"{self._base_url}/{entry_html}"
                elif self._is_extension_project and (
                    actual_url == "about:blank"
                    or actual_url == ""
                    or actual_url.startswith("about:")
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
                # 值解析与实际等待分开捕获（code-review 修）：float("abc")
                # 抛 ValueError 若混入同一 except 会被误标成「wait 超时」，
                # 把场景配置类错误伪装成时序类问题，干扰失败归因
                try:
                    timeout_ms = float(value) if value else 1000
                except (TypeError, ValueError):
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_wait_value",
                        "error": f"wait 值非法（应为毫秒数）: {value!r}",
                    }
                # 负值/inf/nan 毫秒数显式失败（code-review item 6057e90f3fa3；
                # inf/nan 补拦 09fcf01028c6）：wait_for_timeout 对负值立即返回，
                # 场景声明的等待被静默丢弃，断言时点比场景意图提前、失败归因
                # 偏向时序而非配置错误——与 mock_status/drag 配置脏值的结构化
                # 失败同口径。inf/nan（float("inf")/"nan"/"1e999" 的解析产物）
                # 与任何数比较恒为 False，只拦负值拦不住，脏值流入 Playwright
                # 协议层后落顶层 except 归因退化为 unknown，同样按配置错误拦截
                if timeout_ms < 0 or not math.isfinite(timeout_ms):
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_wait_value",
                        "error": f"wait 值非法（毫秒数不能为负且必须有限）: {value!r}",
                    }
                # 超大有限值同款拦截（code-review item 03121e3f15f4）：
                # planner 误写（毫秒/秒混用写成 "6000000"，或 "1e9"）会被
                # float() 正常解析并如实等待；引擎 _execute_parallel 对单场景
                # 没有超时包裹，该场景持续占用并行信号量槽与浏览器 context，
                # 直至外部监督超时介入，整轮验证窗口被单条场景声明占满。
                # 上限 _MAX_WAIT_MS（10 分钟），超过按配置错误结构化失败并
                # 附原始值，与上方负值/非有限值拦截同口径
                elif timeout_ms > _MAX_WAIT_MS:
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_wait_value",
                        "error": f"wait 值非法（毫秒数不能超过 {_MAX_WAIT_MS}）: {value!r}",
                    }
                # 纯计时器不抛 timeout 类异常（code-review item 2d93bf93df4e）：
                # 此前的 try/except 实际不可达，且真触发时（页面/浏览器关闭等
                # 环境级故障）会被误标成「wait 超时」，把环境故障伪装成场景
                # 时序问题——异常统一交给下方顶层 except 按实际错误分类
                await page.wait_for_timeout(timeout_ms)
                return {
                    "success": True,
                    "action": action,
                    "detail": f"等待 {timeout_ms}ms",
                }

            # dialog 操作无需 CSS target：注册一次性对话框处理器，
            # 供后续 click 触发的 window.confirm 使用
            if action == "dialog":
                mode = (value or "accept").lower()
                if mode not in ("accept", "dismiss"):
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
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
                return {
                    "success": False,
                    "action": action,
                    "target": target,
                    "error": "缺少 target 选择器",
                }

            # seed 的 target 是 localStorage 键（非 CSS 选择器），需在通用选择器等待前处理
            if action == "seed":
                # origin 预检（code-review item fb21b35af4a7）：seed 先于 navigate
                # 执行时页面停留在 about:blank 不透明 origin，localStorage 访问
                # 抛 SecurityError 后被顶层 except 归为 unknown；即便写入成功也
                # 不属于应用 origin，随后的 navigate 会使其静默丢失——两类失败
                # 都无法归因到「seed 需在 navigate 之后」这一配置错误。与
                # invalid_wait_value / invalid_mock_status 同口径，结构化失败
                # 返回并附当前页面地址
                current_url = page.url or ""
                if not current_url.startswith(("http://", "https://")):
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_seed_origin",
                        "error": (
                            f"seed 需在 navigate 之后执行（当前页面非 http(s) origin）: "
                            f"{current_url!r}"
                        ),
                    }
                # 写入 localStorage 后重载页面，使应用按新数据重新渲染：
                # target = 存储键，value = 原始 JSON 字符串（直接写入，不解析）
                await page.evaluate(
                    "(kv) => localStorage.setItem(kv[0], kv[1])",
                    [target, value],
                )
                await page.reload(wait_until="domcontentloaded", timeout=15000)
                first_frame_ok = await self._wait_stable(page)
                result = {"success": True, "action": action, "target": target}
                # 与 navigate 分支（B1）对齐：seed 后整页重载同样可能首帧渲染
                # 失败，仅首帧超时时显式落 False（True 不写键，旧报告/测试兼容）；
                # env_gate.is_blank_render_candidate 依赖此键把白屏场景降级
                # blocked-env，不再伪装成「元素不存在」类产品/场景失败
                if first_frame_ok is False:
                    result["first_frame_ok"] = False
                return result

            # mock_api：拦截 URL 模式并返回固定 JSON，用于离线验证依赖外部 API
            # 的场景（如 Open-Meteo / 时间服务器）。target = URL 模式（Playwright
            # glob，如 https://api.open-meteo.com/*），value = JSON 响应体。
            # route 注册在 page 上，reload/导航后仍保留（同一 page 对象）。
            if action == "mock_api":
                try:
                    # 响应体 JSON 合法性预检（code-review item 2039c7773f8a）：
                    # 场景解析层 _str_field 把对象形态的 value 归一为 str(dict)
                    # （Python repr 单引号），直接 fulfill 后前端 JSON.parse 必
                    # 失败，错误提示类断言失败会被归因为产品缺陷——与 api_runner
                    # body_type=json 的 json.loads 预检同口径，route 注册前按
                    # 结构化失败拦截并附原始值
                    try:
                        json.loads(value)
                    except json.JSONDecodeError:
                        return {
                            "success": False,
                            "action": action,
                            "target": target,
                            "error_type": "invalid_mock_body",
                            "error": f"mock_api 响应体非合法 JSON: {value!r}",
                        }
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
                        # 标记在 route 注册成功后才落（code-review item
                        # 222eba9212b5）：注册抛异常时若标记已为 True，同页
                        # 后续 mock_api 步骤会误判「已拦截」而跳过 SSE 隔离，
                        # 活体 /api/stream 推流将重新污染 mock 数据
                        page._fenix_sse_blocked = True
                    # mock 状态码（admin 修 2026-08-29：族谱爆炸根因之一）：
                    # 场景可携带 "status"（如 409/500）模拟后端拒绝/异常分支。
                    # 此前硬编码 200，导致 4xx/5xx 场景的 mock 全部按成功返回，
                    # 错误 toast 断言必然失败 → 伪失败被记为产品 bug。
                    # 仅 status 缺省（None）回退 200（code-review item
                    # e0a4971e5701）：or 200 会把 falsy 的 0/"" 静默改写成
                    # 200，显式脏值应走 invalid_mock_status 结构化失败（与
                    # wait 的 invalid_wait_value 同口径）
                    raw_status = step.get("status")
                    try:
                        # bool 是 int 子类，须在 int() 前显式排除（与
                        # cli_assertions._assert_exit_code / cli_runner
                        # timeout / engine max_parallel 同纪律），否则
                        # status: true 被静默折算成 HTTP 状态码 1
                        if isinstance(raw_status, bool):
                            raise ValueError(raw_status)
                        mock_status = 200 if raw_status is None else int(raw_status)
                    except (TypeError, ValueError):
                        # 不静默回退 200（code-review 修）：场景意图的 4xx/5xx
                        # 分支若因 status 脏值被当成成功响应，错误提示类断言会
                        # 系统性伪失败并被归因为产品缺陷。与 wait 的
                        # invalid_wait_value 同口径，本步骤结构化失败返回。
                        return {
                            "success": False,
                            "action": action,
                            "target": target,
                            "error_type": "invalid_mock_status",
                            "error": (
                                f"mock_api status 非法（应为 HTTP 状态码整数）: "
                                f"{step.get('status')!r}"
                            ),
                        }
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
                    # 登记 mock pattern（code-review item 9af293ddcb49）：
                    # new_context 的 response 监听据此跳过本路由 fulfill 的
                    # 4xx/5xx，不再计入 network_errors；登记放在注册成功
                    # 之后，route 注册失败时不会误标记
                    mock_patterns = getattr(page, "_fenix_mock_patterns", None)
                    if mock_patterns is None:
                        mock_patterns = set()
                        page._fenix_mock_patterns = mock_patterns
                    mock_patterns.add(route_pattern)
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
                        "error_type": "mock_api_failed",
                        "error": f"mock_api 失败: {e}",
                    }

            # 窗口级操作（admin 修 2026-08-29：族谱爆炸根因之一）：
            # target=window 不是 DOM 元素，通用 locator.wait_for 必然超时；
            # target=body 可定位但非表单元素，fill 同样必然报错——键盘按键类
            # 步骤必须在任何 DOM 定位/填充之前分流处理。（空 target 已被
            # 上方「缺少 target 选择器」分支提前返回，不再列入条件——
            # code-review item 6a5e642fd04d）
            if target in ("window", "body") and action in ("scroll", "type"):
                if action == "scroll":
                    # value 为 "dx,dy" 像素位移（默认 0,300），经鼠标滚轮触发真实 scroll 事件
                    try:
                        dx, dy = (float(x) for x in (value or "0,300").split(","))
                        # inf/nan 脏值同款拦截（code-review item 09fcf01028c6）：
                        # 比较恒为 False 绕过数值校验直达 mouse.wheel，失败落
                        # 顶层 except 归因退化为 unknown——并入下方既有
                        # invalid_scroll_value 结构化失败口径
                        if not (math.isfinite(dx) and math.isfinite(dy)):
                            raise ValueError
                    except ValueError:
                        # 不静默回退默认位移（code-review item 34ae9c4badaa）：
                        # 与 wait 的 invalid_wait_value / mock_api 的
                        # invalid_mock_status 同口径，结构化失败返回并附原始
                        # value——场景显式声明的位移被无提示改写，滚动类断言
                        # 失败时会难以归因到步骤配置错误
                        return {
                            "success": False,
                            "action": action,
                            "target": target,
                            "error_type": "invalid_scroll_value",
                            "error": (
                                f"scroll 值非法（应为 \"dx,dy\" 像素位移）: {value!r}"
                            ),
                        }
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
                    # 按键名合法性预判（code-review item 9d40ace9827c）：启发式
                    # 会放行普通文本（如 "hello"），press 抛错被顶层 except 归为
                    # unknown——此处先校验，未命中走下方 invalid_type_target
                    # 同款结构化失败
                    if not _is_valid_press_key(value):
                        return {
                            "success": False,
                            "action": action,
                            "target": target,
                            "error_type": "invalid_type_target",
                            "error": (
                                f"window/body 目标的键盘按键名非法: {value!r}"
                                f"（仅支持单字符按键、命名键（如 Escape/Enter/"
                                f"Tab/ArrowDown）或修饰键组合（如 Control+a））"
                            ),
                        }
                    await page.keyboard.press(value)
                    return {
                        "success": True,
                        "action": action,
                        "target": target,
                        "value": value,
                        "detail": f"键盘按键: {value}",
                    }
                # 键盘按键启发式未命中：window/body 不是可填充 DOM 元素，若穿透
                # 到下方通用 fill 路径，Playwright 报「Element is not an <input>」
                # 类错误并被外层 except 归为 unknown error_type，场景作者难以
                # 定位是 target 用错了窗口级语义（code-review 修）。
                if action == "type":
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_type_target",
                        "error": (
                            f"window/body 目标不支持文本输入；键盘按键仅支持"
                            f"无特殊字符的按键名（如 Escape/Enter）: {value!r}"
                        ),
                    }

            # 等待目标元素可交互（.first 避免 strict mode violation）
            locator = page.locator(target).first
            # wait 动作跳过此前置等待（code-review item a7938c87ef82）：
            # wait 分支用 wait_for_selector(state="visible", 10s) 自带同一
            # 可见性等待，先做 5s locator.wait_for 会对同一条件双重等待，
            # 元素不存在时最坏 15s 才报错；仅交互类动作需要此前置等待
            if action != "wait":
                await locator.wait_for(state="visible", timeout=5000)
                await self._wait_stable(page)

            if action == "click":
                # 支持 click 步骤携带 dialog 处理（accept/dismiss），
                # 处理点击后同步弹出的 window.confirm 对话框
                # dialog 归一为字符串（code-review item 5f5d31a35c76）：planner
                # 产物并非不可能为布尔/数值——此前 (dialog or "").lower() 抛
                # AttributeError 被顶层 except 归为 unknown，与上方 value 的
                # str() 归一（08ef327b2c7e）同款防御
                dialog_mode = str(step.get("dialog") or "").lower()
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
                await locator.fill(value, timeout=5000)
                return {
                    "success": True,
                    "action": action,
                    "target": target,
                    "value": value,
                }

            elif action == "clear":
                await locator.fill("", timeout=5000)
                return {"success": True, "action": action, "target": target}

            elif action == "select":
                await locator.select_option(value, timeout=5000)
                return {
                    "success": True,
                    "action": action,
                    "target": target,
                    "value": value,
                }

            elif action == "scroll":
                await locator.scroll_into_view_if_needed(timeout=5000)
                return {"success": True, "action": action, "target": target}

            elif action == "hover":
                await locator.hover(timeout=5000)
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
                # 残缺 JSON 拦截（code-review item d1980b980f9c）：value 以 {
                # 开头但 json.loads 失败（planner 写出截断 JSON，如 {"to": "x"
                # 缺右括号）时，整段残缺 JSON 若落入 {"to": value} 回退会成为
                # to_sel，后续 locator/wait_for 抛错被顶层 except 归为
                # unknown——与 hold/dwell/via_wait 脏值（44b3d43812ab）同口径，
                # 复用既有 invalid_drag_config 结构化失败并附原始 value；
                # 纯选择器形态保持现回退
                if value.strip().startswith("{"):
                    try:
                        cfg = json.loads(value)
                    except Exception:
                        return {
                            "success": False,
                            "action": action,
                            "target": target,
                            "error_type": "invalid_drag_config",
                            "error": (
                                f"drag 配置 JSON 解析失败（应为选择器或完整 JSON 配置）: "
                                f"value={value!r}"
                            ),
                        }
                else:
                    cfg = {"to": value}
                to_sel = cfg.get("to", "")
                if not to_sel:
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error": "drag 缺少目标选择器（value 或 value.to）",
                    }
                via_sel = cfg.get("via", "")
                # to/via 选择器 str 归一（code-review item d31c43f215ee）：
                # 步骤级 value 已 str 归一（08ef327b2c7e），非字符串脏值只会
                # 出现在 JSON 配置内（{"to": 123}、{"via": ["x"]}），此前原样
                # 传入 page.locator()，抛 TypeError/PlaywrightError 后被顶层
                # except 归为 error_type=unknown——与 hold/dwell/via_wait 的
                # int 归一（44b3d43812ab）同口径，结构化失败并附原始值
                if not isinstance(to_sel, str) or not isinstance(via_sel, str):
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_drag_config",
                        "error": (
                            f"drag 配置 to/via 必须为字符串（选择器）: "
                            f"to={cfg.get('to')!r} via={cfg.get('via')!r}"
                        ),
                    }
                # hold/dwell/via_wait 的 int 转换单独捕获（code-review item
                # 44b3d43812ab）：脏值（如 "450ms"、null）此前落入顶层 except
                # 归为 unknown——与 invalid_wait_value / invalid_scroll_value /
                # invalid_mock_status 同口径，结构化失败并附原始值。
                # 转换点位于 mouse.down 之前，提前 return 无按压状态泄漏
                try:
                    hold = int(cfg.get("hold", 450))
                    dwell = int(cfg.get("dwell", 600))
                    via_wait = int(cfg.get("via_wait", 300))
                # OverflowError 并入同款拦截（code-review item e3f70f16ae5c）：
                # json 的 1e999 解析为 inf，int(inf) 抛 OverflowError 不在原
                # 元组内，会穿到顶层 except 归因退化为 unknown——与 wait 的
                # 非有限值拦截同口径
                except (TypeError, ValueError, OverflowError):
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_drag_config",
                        "error": (
                            f"drag 配置 hold/dwell/via_wait 必须为数值（毫秒）: "
                            f"hold={cfg.get('hold')!r} dwell={cfg.get('dwell')!r} "
                            f"via_wait={cfg.get('via_wait')!r}"
                        ),
                    }
                # 负值/超大值同款钳制（code-review item e3f70f16ae5c）：wait
                # 分支对毫秒数设 _MAX_WAIT_MS（10 分钟）上限（引擎对单场景无
                # 超时包裹，超大值长期占住并行信号量槽与浏览器 context），
                # drag 三时长此前 int() 后直接进 wait_for_timeout，planner
                # 毫秒/秒混写（如 450000）会让单条 drag 步骤挂起分钟级；负值
                # 则令 wait_for_timeout 立即返回、长按/驻留被静默丢弃——均
                # 复用既有 invalid_drag_config 结构化失败并附原始值
                if not all(0 <= d <= _MAX_WAIT_MS for d in (hold, dwell, via_wait)):
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error_type": "invalid_drag_config",
                        "error": (
                            f"drag 配置 hold/dwell/via_wait 须为 0~{_MAX_WAIT_MS}"
                            f"（毫秒）: hold={cfg.get('hold')!r} "
                            f"dwell={cfg.get('dwell')!r} "
                            f"via_wait={cfg.get('via_wait')!r}"
                        ),
                    }

                src_box = await locator.bounding_box()
                if not src_box:
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error": f"源元素不可见: {target}",
                    }
                to_locator = page.locator(to_sel).first
                await to_locator.wait_for(state="visible", timeout=5000)
                to_box = await to_locator.bounding_box()
                if not to_box:
                    return {
                        "success": False,
                        "action": action,
                        "target": target,
                        "error": f"目标元素不可见: {to_sel}",
                    }

                sx = src_box["x"] + src_box["width"] / 2
                sy = src_box["y"] + src_box["height"] / 2
                await page.mouse.move(sx, sy)
                await page.mouse.down()
                try:
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
                except Exception:
                    # 失败路径先释放左键再抛：按压状态泄漏会被同 context 内
                    # 后续步骤（click/scroll/drag）继承，产生与场景意图无关
                    # 的连锁失败、归因困难（code-review 4c9e4cd003c2）
                    # 释放动作自身抛错不得顶替原始异常（code-review item
                    # 3daf57f3dcff）：浏览器/页面已崩溃时 mouse.up 的新异常
                    # 会直接向外传播、bare raise 不再执行，顶层错误分类按
                    # 释放动作的错误信息走（多为 unknown），拖拽失败的真实
                    # 原因不可见——释放失败仅记日志，保留原始异常继续抛出
                    try:
                        await page.mouse.up()
                    except Exception as up_exc:
                        self._log(
                            "warning",
                            f"drag 失败路径释放左键自身失败（原始异常继续抛出）: "
                            f"{type(up_exc).__name__}: {up_exc}",
                        )
                    raise
                await page.mouse.up()
                await page.wait_for_timeout(400)  # 等待 React 重渲染与持久化
                await self._wait_stable(page)
                return {"success": True, "action": action, "target": target}

            else:
                return {
                    "success": False,
                    "action": action,
                    "target": target,
                    "error": f"不支持的操作: {action}",
                }

        except Exception as e:
            error_msg = str(e)
            # 错误分类：类型化异常优先（code-review item ea1ef016ced3）——
            # playwright TimeoutError 不依赖错误文案（playwright 版本升级
            # 文案漂移会致 error_type 误判），文案子串仅作兜底（子串表见
            # 模块级常量）。click_intercepted 判定保持在最前：点击超时的
            # 错误日志体常含「intercepts pointer events」重试原因，既有
            # 口径归为 click_intercepted，error_type 取值保持不变。
            if _CLICK_INTERCEPTED_MARKER in error_msg:
                error_type = "click_intercepted"
            elif isinstance(e, _PlaywrightTimeoutError) or _TIMEOUT_MARKER in error_msg.lower():
                error_type = "element_not_found_or_not_actionable"
            elif _NOT_VISIBLE_MARKER in error_msg.lower():
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
            handle = await page.wait_for_function(
                "() => (document.body && document.body.innerText || '').trim().length > 0",
                timeout=8000,
            )
        # [fenix-ignore:088471e0a93e] 崩溃类异常与白屏同落 blocked-env 正是 env_gate 设计归因（真崩溃经 _escalate_env_blocked 升级送人工、不进产品归因），无精度弱化
        except Exception:
            # B1（fenixd-registry-ignored-false-attribution-loop）：首帧 8s 超时
            # 不再完全无声——返回 False，navigate 步骤据此落 first_frame_ok=False，
            # env_gate.is_blank_render_candidate 据此把白屏场景降级 blocked-env
            # （客户端渲染失败不进产品/场景归因）。「不在此处判失败」的原语义
            # 保留：极端形态（纯画布等）仍走 CLS 退化，不放大为步骤失败。
            return False

        # 句柄释放（code-review item f1f6353374a1）：wait_for_function 返回包裹
        # 返回值的 JSHandle，此处仅用于等待真值、返回值被丢弃，句柄若不显式
        # dispose 会在单场景内按步骤累积，直到场景 context 关闭才统一回收。
        # 释放放在等待成功路径之后并单独吞掉二次异常：页面已关闭等场景下
        # dispose 自身抛错不得顶替等待结果、不得改变既有等待语义（首帧超时
        # → False，成功 → 继续 CLS 判定）
        try:
            await handle.dispose()
        except Exception:
            pass

        # CLS 稳定
        try:
            # 页内 Promise 靠 setTimeout 兜底 resolve，page.evaluate 无超时
            # 语义：页面主线程挂起时兜底定时器永不触发、await 永久挂起，
            # 外层包 asyncio.wait_for 显式兜底（code-review item
            # c8c04ed298b8），超时与下方异常同路——跳过 CLS 段不放大失败
            await asyncio.wait_for(
                page.evaluate("""() => {
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
                }"""),
                timeout=_IN_PAGE_EVALUATE_TIMEOUT_S,
            )
        except Exception:
            pass  # 浏览器不支持 CLS API 时跳过（含上方 wait_for 超时）

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
        # 路径成分净化（code-review item 8c2bad0d3932）：name 拼自 scenario.id
        # （validate_scenario 只查非空、不查字符集），含 ../ 或分隔符的 id 经
        # f-string 拼接可把截图写出 screenshots 目录——复用共用的
        # path_safety.safe_component（含纯点 . / .. 归一，code-review item
        # 80d8ee05f07a），正常 kebab-case 命名不受影响
        safe_name = safe_component(str(name))
        # 唯一后缀（code-review item c593862ba608）：safe_component 把分隔符
        # 与纯点成分统一折叠为下划线，不同原始名可净化出同一文件名（如
        # 「x/../y」与「x_.._y」同为 x_.._y）→ 同目录后写截图覆盖先写截图、
        # 报告证据丢失。附加实例内单调序号保证同一次运行内不重名（asyncio
        # 单线程事件循环，取号两行间无 await，天然原子）；实例随 run 重建、
        # 序号复位，保留「同槽位重跑覆盖旧证据」的既有语义。消费方（报告
        # screenshots 列表等）一律使用本方法返回的 path，不按名字重建路径，
        # 后缀对消费方透明；序号为纯数字，文件名字符集安全。
        seq = self._screenshot_seq
        self._screenshot_seq += 1
        path = output_dir / f"{safe_name}_{seq}.png"
        await page.screenshot(path=str(path), full_page=False)
        from .screenshot_lab import classify_screenshot

        labels = classify_screenshot(str(path))
        return {"path": str(path), "labels": labels}

    def get_console_errors(self, context) -> list[str]:
        """获取在 context 生命周期中收集的控制台错误。"""
        return getattr(context, "_console_errors", [])

    def get_network_errors(self, context) -> list[str]:
        """获取在 context 生命周期中收集的网络错误。"""
        return getattr(context, "_network_errors", [])
