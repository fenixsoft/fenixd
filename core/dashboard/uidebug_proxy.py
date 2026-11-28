"""uidebug_proxy.py — fenix-ui-debug 反向代理的同源改写与上游取数单源。

任意 URL 的页面要接入批注框架，必须先搬到 dashboard 同源下（iframe 跨源
不可注入，SOP 硬约束）。本模块承载代理路由的全部纯逻辑：

- :func:`rebase_html` / :func:`rebase_css` —— 根相对 URL（``/x``）改写到
  代理前缀 ``/uidebug/<project>/<session>/~`` 下；跨源绝对 URL 不动；
  既有 ``<base>`` 标签剥离（改写后的根相对引用天然落在代理前缀内，
  保留 base 反而把文档相对引用指去 dashboard 根）；
- :data:`RUNTIME_PATCH_JS` —— 注入页的运行时补丁：patch
  fetch/XHR/EventSource/history.pushState|replaceState/window.open 与动态
  元素 src/href/action 属性 setter，MutationObserver 兜 innerHTML 插入；
  豁免前缀 ``/api/uidebug/``、``/uidebug*`` 与代理前缀自身（fenix 批注
  回流端点不得被再包一层代理）；
- :func:`fetch_upstream` —— 上游取数（重定向不跟随，Location 由路由层
  改写后交浏览器自行跟随；Accept-Encoding: identity 请求未压缩体便于
  HTML/CSS 改写）；:class:`UpstreamUnreachable` 结构化上游不可达。

已知边界（刻意不做，SKILL.md 同步披露）：代理只透传 GET/HEAD（批注流
程是只读浏览+点选反馈）；WebSocket 不改写；不转发浏览器 Cookie——
dashboard 与其他面板（如 dsh web）可能同源部署，浏览器在 dashboard
origin 下的会话 cookie 会随 /uidebug 请求进入本代理，原样转发即把
第三方凭证隧道给被调试页面（上游自身鉴权态经入口 query token 承载）。
"""

from __future__ import annotations

import codecs
import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

# 上游响应体上限：批注对象是页面与资产，不是下载通道；超限拒绝防无界内存
MAX_UPSTREAM_BODY = 64 << 20

# 上游响应体读取总时限（秒）：无界流（SSE 心跳保活）的兜底防线
_UPSTREAM_BODY_DEADLINE_S = 60.0

_UPSTREAM_TIMEOUT_S = 15.0


class UpstreamUnreachable(Exception):
    """上游目标不可达（DNS/连接/超时）；路由层转 502 错误页。"""


class UpstreamBodyTooLarge(Exception):
    """上游响应体超 :data:`MAX_UPSTREAM_BODY`；路由层转 502 错误页。"""


def session_base(project: str, session: str) -> str:
    """会话根前缀（不带 ``~``）：``/uidebug/<project>/<session>``。

    cookie Path 作用域统一收到这里：浏览器只会对本会话前缀内的请求
    回传代理改写过的 cookie，跨会话/跨应用不串线。"""
    return ("/uidebug/" + urllib.parse.quote(project, safe="")
            + "/" + urllib.parse.quote(session, safe=""))


def proxy_prefix(project: str, session: str) -> str:
    """代理前缀（以 ``~`` 结尾）：``/uidebug/<project>/<session>/~``。

    project/session 为 unquote 后的原始值，重新逐段 quote（safe=""）保证
    嵌回 HTML/Location 的形态与网络上收到的一致（同 proto_serve.build_url）。
    """
    return session_base(project, session) + "/~"


def cookie_header_from(headers) -> str | None:
    """取浏览器请求的 Cookie 头；默认不转发（恒返回 None）。

    安全决策：dashboard 与其他面板（如 dsh web）可能同源部署（面板桥
    前缀反代/嵌入），浏览器在 dashboard origin 下的会话 cookie 会随
    /uidebug 请求进入本代理；原样转发给注册 target 即构成凭证外泄。
    会话结构（session.json）未记录 target 自身 Set-Cookie 的 cookie 名
    名单，无法安全区分「目标应用自己的 cookie」与「同源部署面板的
    cookie」，因此默认一律不转发；上游自身鉴权态经入口 query token
    （entry_query）承载。TODO: 如需恢复转发，按会话记录的 target
    Set-Cookie 名单做白名单显式 opt-in，不得整体透传 Cookie 头。
    """
    return None


def rewrite_set_cookies(headers, base: str) -> list[str]:
    """上游 Set-Cookie 逐条改写为会话作用域，返回改写后的列表。

    - Path 属性统一重写为会话根前缀 base：cookie 只随本会话前缀内的
      请求回流（浏览器按 Path 作用域发送）；回流 cookie 代理默认不再
      转发上游（见 :func:`cookie_header_from`），此处收口 Path 仅为防
      跨会话/跨应用串线存储；
    - 无 Path 属性时补写会话根（RFC 6265 默认 Path=上游目录，须显式收口）；
    - Secure 剥除：交付通道是纯 HTTP（frp 隧道无 TLS），带 Secure 的
      cookie 浏览器不回传。
    其余属性（HttpOnly/SameSite/Max-Age/Expires）原样保留；上游 30x 与
    正常响应同样处理（303 登录跳转常携带鉴权 Set-Cookie）。
    """
    out: list[str] = []
    for raw in (headers.get_all("Set-Cookie") or [] if headers else []):
        parts = raw.split(";")
        kept = []
        for attr in parts[1:]:
            a = attr.strip()
            if not a:
                continue
            low = a.lower()
            if low == "secure" or low.startswith("path="):
                continue        # Path 统一重写，Secure 剥除
            kept.append(a)
        kept.append("Path=" + base)
        out.append("; ".join([parts[0].strip()] + kept))
    return out


def is_reserved_path(path: str, prefix: str) -> bool:
    """rebase 豁免前缀：fenix 自有通道不得被包进代理。

    - 代理前缀自身（已改写过的值二次进入不改写，MutationObserver 收敛前提）；
    - ``/uidebug/``（wrapper 页）、``/uidebug-assets/``（批注器资产）；
    - ``/api/uidebug/``（批注回流端点——目标应用自身调用 /api/x 仍会被
      改写进代理，只有 fenix 回流端点豁免）。
    """
    return (path == prefix
            or path.startswith(prefix + "/")
            or path.startswith("/uidebug/")
            or path.startswith("/uidebug-assets/")
            or path.startswith("/api/uidebug/"))


def rebase_url_path(path: str, prefix: str) -> str:
    """单个根相对路径改写；非根相对/豁免前缀原样返回。"""
    if not path.startswith("/"):
        return path          # 文档相对、协议相对不含 /、锚点、query 不动
    if path.startswith("//"):
        return path          # 协议相对 = 跨源引用，保持原样
    if is_reserved_path(path, prefix):
        return path
    return prefix + path


# ── HTML 改写 ──────────────────────────────────────────────────────────

# URL 值属性（引号包裹）：限定空白引导避免误吞 JS 里的 location.href= 形态
_ATTR_URL_RE = re.compile(
    r"(\s(?:src|href|action|poster|formaction)\s*=\s*)"
    r"(\"([^\"]*)\"|'([^']*)')",
    re.IGNORECASE,
)
_SRCSET_RE = re.compile(
    r"(\ssrcset\s*=\s*)(\"([^\"]*)\"|'([^']*)')",
    re.IGNORECASE,
)
_STYLE_ATTR_RE = re.compile(
    r"(\sstyle\s*=\s*)(\"[^\"]*\"|'[^']*')",
    re.IGNORECASE,
)
_STYLE_BLOCK_RE = re.compile(
    r"(<style\b[^>]*>)(.*?)(</style\s*>)",
    re.IGNORECASE | re.DOTALL,
)
_BASE_TAG_RE = re.compile(r"<base\b[^>]*>", re.IGNORECASE)
_HEAD_CLOSE_RE = re.compile(r"</head\s*>", re.IGNORECASE)
_BODY_OPEN_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE)


def _attr_value(match: "re.Match[str]") -> str:
    # ("..."|'...') 二选一：group(3)=双引号内值，group(4)=单引号内值
    return match.group(3) if match.group(3) is not None else match.group(4)


def rebase_html(html: str, prefix: str) -> str:
    """把 HTML 里根相对的引用改写到代理前缀下（纯函数，不注入脚本）。"""
    html = _BASE_TAG_RE.sub("<!-- fenix-ui-debug: base stripped -->", html)
    html = _ATTR_URL_RE.sub(
        lambda m: m.group(1) + m.group(2)[0]
        + rebase_url_path(_attr_value(m), prefix) + m.group(2)[-1],
        html,
    )
    html = _SRCSET_RE.sub(
        lambda m: m.group(1) + m.group(2)[0]
        + _rebase_srcset(_attr_value(m), prefix) + m.group(2)[-1],
        html,
    )
    html = _STYLE_BLOCK_RE.sub(
        lambda m: m.group(1) + rebase_css(m.group(2), prefix) + m.group(3),
        html,
    )
    html = _STYLE_ATTR_RE.sub(
        lambda m: m.group(1) + m.group(2)[0]
        + rebase_css(_attr_value(m), prefix) + m.group(2)[-1],
        html,
    )
    return html


def _rebase_srcset(value: str, prefix: str) -> str:
    # srcset 值形如 "url 1x, url 2x"：逗号分候选，候选首 token 为 URL
    out = []
    for cand in value.split(","):
        cand = cand.strip()
        if not cand:
            continue
        pieces = cand.split()
        if pieces and pieces[0].startswith("/") and not pieces[0].startswith("//"):
            pieces[0] = rebase_url_path(pieces[0], prefix)
        out.append(" ".join(pieces))
    return ", ".join(out)


# ── CSS 改写（.css 响应 + <style> 块 + style 属性共用） ────────────────

_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(/[^'\")]+)\1\s*\)", re.IGNORECASE)
_CSS_IMPORT_RE = re.compile(r"(@import\s+)(['\"])(/[^'\"]+)\2", re.IGNORECASE)


def rebase_css(css: str, prefix: str) -> str:
    """CSS 内根相对 url()/@import 改写到代理前缀下。"""
    css = _CSS_URL_RE.sub(
        lambda m: "url(" + (m.group(1) or "") + rebase_url_path(m.group(2), prefix)
        + (m.group(1) or "") + ")", css)
    css = _CSS_IMPORT_RE.sub(
        lambda m: m.group(1) + m.group(2) + rebase_url_path(m.group(3), prefix)
        + m.group(2), css)
    return css


# ── 注入（运行时补丁 + 批注器） ────────────────────────────────────────

# 运行时同源补丁。三层防线（HTML 静态改写由 rebase_html 承担，这里补运行时）：
# 1. 网络 API patch：fetch/XHR/EventSource/window.open/history.pushState|
#    replaceState —— SPA 的 /api/x 相对请求搬进代理前缀；
# 2. 属性 setter patch：动态 createElement 后赋 src/href/action 的形态
#    （webpack/vite chunk 加载、图片预加载、表单提交）；
# 3. MutationObserver：innerHTML/insertAdjacentHTML 插入不走属性 setter，
#    观察器兜底改写（rebase 幂等：已在前缀内的值原样返回，观察收敛）。
# 原生引用备份到 window.__fenixUidDebugNative：fenix 批注器与目标页脚本
# 先行替换 fetch 时都有兜底通道。
RUNTIME_PATCH_JS = r'''
(function () {
  "use strict";
  var CFG = window.__FENIX_UIDEBUG__;
  if (!CFG || window.__fenixUidDebugPatched) return;
  window.__fenixUidDebugPatched = true;
  var ORIGIN = window.location.origin;
  var PREFIX = CFG.prefix;
  function reserved(p) {
    return p === PREFIX || p.indexOf(PREFIX + "/") === 0 ||
      p.indexOf("/uidebug/") === 0 || p.indexOf("/uidebug-assets/") === 0 ||
      p.indexOf("/api/uidebug/") === 0;
  }
  function rebase(raw) {
    if (typeof raw !== "string" || !raw) return raw;
    var u;
    try { u = new URL(raw, window.location.href); } catch (e) { return raw; }
    if (u.origin !== ORIGIN) return raw;
    if (reserved(u.pathname)) return raw;
    return ORIGIN + PREFIX + u.pathname + u.search + u.hash;
  }
  var nf = window.fetch ? window.fetch.bind(window) : null;
  var xo = XMLHttpRequest.prototype.open;
  window.__fenixUidDebugNative = { fetch: nf, xhrOpen: xo };
  if (nf) {
    window.fetch = function (input, init) {
      try {
        if (typeof input === "string") input = rebase(input);
        else if (input && typeof input.url === "string")
          input = new Request(rebase(input.url), input);
      } catch (e) {}
      return nf(input, init);
    };
  }
  XMLHttpRequest.prototype.open = function (method, url) {
    var args = Array.prototype.slice.call(arguments);
    args[1] = rebase(url);
    return xo.apply(this, args);
  };
  if (window.EventSource) {
    var ES = window.EventSource;
    var PES = function (url, cfg2) { return new ES(rebase(url), cfg2); };
    PES.prototype = ES.prototype;
    window.EventSource = PES;
  }
  ["pushState", "replaceState"].forEach(function (name) {
    var orig = window.history[name];
    window.history[name] = function (state, title, url) {
      try { if (typeof url === "string") url = rebase(url); } catch (e) {}
      return orig.call(window.history, state, title, url);
    };
  });
  if (window.open) {
    var origOpen = window.open.bind(window);
    window.open = function (url, n, f) { return origOpen(rebase(url), n, f); };
  }
  [["HTMLScriptElement", "src"], ["HTMLImageElement", "src"],
   ["HTMLSourceElement", "src"], ["HTMLMediaElement", "src"],
   ["HTMLTrackElement", "src"], ["HTMLIFrameElement", "src"],
   ["HTMLLinkElement", "href"], ["HTMLAnchorElement", "href"],
   ["HTMLFormElement", "action"]
  ].forEach(function (pair) {
    var ctor = window[pair[0]];
    if (!ctor || !ctor.prototype) return;
    var desc = Object.getOwnPropertyDescriptor(ctor.prototype, pair[1]);
    if (!desc || !desc.set) return;
    try {
      Object.defineProperty(ctor.prototype, pair[1], {
        get: desc.get,
        set: function (v) {
          try { v = rebase(String(v)); } catch (e) {}
          desc.set.call(this, v);
        },
        configurable: true,
        enumerable: desc.enumerable,
      });
    } catch (e) {}
  });
  function fixAttrs(node) {
    if (!node || !node.hasAttribute) return;
    var attrs = ["src", "href", "action", "poster"];
    for (var i = 0; i < attrs.length; i++) {
      var a = attrs[i];
      if (!node.hasAttribute(a)) continue;
      var v = node.getAttribute(a);
      var r = rebase(v);
      if (r !== v) node.setAttribute(a, r);
    }
  }
  function fixTree(root) {
    if (!root || root.nodeType !== 1) return;
    fixAttrs(root);
    var list;
    try { list = root.querySelectorAll("[src],[href],[action],[poster]"); }
    catch (e) { return; }
    for (var i = 0; i < list.length; i++) fixAttrs(list[i]);
  }
  function startObserver() {
    if (!document.body) { window.setTimeout(startObserver, 50); return; }
    try {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var m = muts[i];
          if (m.type === "childList") {
            for (var j = 0; j < m.addedNodes.length; j++) fixTree(m.addedNodes[j]);
          } else if (m.type === "attributes") {
            fixAttrs(m.target);
          }
        }
      }).observe(document.body, {
        childList: true, subtree: true,
        attributes: true, attributeFilter: ["src", "href", "action", "poster"],
      });
    } catch (e) {}
  }
  startObserver();
})();
'''.strip()


def inject_into_html(html: str, prefix: str, round_no: int | None = None) -> str:
    """剥离既有 <base> 并注入运行时补丁 + uidebug 模式批注器引用。

    注入点：</head> 前优先；缺失则 <body> 开标签后；都没有（非法/超简
    HTML）整体前置——批注器自带 defer + body 缺失降级（annotator.js mount），
    前置也可存活。
    """
    stripped = _BASE_TAG_RE.sub("<!-- fenix-ui-debug: base stripped -->", html)
    cfg = "window.__FENIX_UIDEBUG__=" + json.dumps({"prefix": prefix}) + ";"
    if round_no:
        # 轮次走全局量（annotator 优先级：URL 参数 > 全局量 > 1）；代理把
        # proto_round 从上游 query 里剥掉（fenix 迭代参数不属于目标应用）
        cfg += "window.__PROTO_FEEDBACK_ROUND__=" + str(int(round_no)) + ";"
    cfg += 'window.__FENIX_ANNOTATOR_MODE__="uidebug";'
    block = ('<script data-fenix-uidebug="patch">' + cfg + RUNTIME_PATCH_JS
             + "</script>"
             + '<script src="/uidebug-assets/annotator.js" defer></script>')
    m = _HEAD_CLOSE_RE.search(stripped)
    if m:
        return stripped[:m.start()] + block + stripped[m.start():]
    m = _BODY_OPEN_RE.search(stripped)
    if m:
        return stripped[:m.end()] + block + stripped[m.end():]
    return block + stripped


# ── 上游取数 ───────────────────────────────────────────────────────────

def build_upstream_url(target: str, sub_path: str, query: str) -> str:
    """注册 target（无尾斜杠规范化）+ 代理子路径 → 上游 URL。

    sub_path 为网络上收到的原始形态（保持 percent-encoding 原样透传，
    不做 unquote/re-quote 往返）；query 为剥掉 proto_round 后的原始串。
    空 sub_path 落到目录形态（target base 非空时补尾斜杠，文档相对引用
    以文档 URL 为基解析，缺尾斜杠会落到上级目录——同原型 301 补斜杠语义）。
    """
    parts = urllib.parse.urlsplit(target)
    if sub_path:
        path = parts.path + "/" + sub_path.lstrip("/")
    else:
        path = (parts.path + "/") if parts.path else "/"
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, path, query, ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁用 urllib 自动跟随：30x 交路由层改写 Location 后由浏览器跟随。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)

# 浏览器 UA（部分开发服务器/网关对默认 Python-UA 拒绝服务）；追加
# fenix-uidebug 标记便于目标侧日志识别代理流量
_UPSTREAM_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 fenix-uidebug")


def _read_capped(fp, headers) -> bytes:
    try:
        cl = int(headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        cl = 0
    if cl > MAX_UPSTREAM_BODY:
        raise UpstreamBodyTooLarge(
            f"upstream body exceeds {MAX_UPSTREAM_BODY} bytes")
    # 分块读 + 总时限：event-stream 等无界流靠心跳保活，单次 recv 的
    # socket timeout 永不触发（urllib timeout 只约束单次操作）——总时限
    # 是防钉死 dashboard 工作线程的最后防线（正常响应体远小于该时限）
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + _UPSTREAM_BODY_DEADLINE_S
    while True:
        if time.monotonic() > deadline:
            raise UpstreamBodyTooLarge(
                f"upstream body read exceeded {_UPSTREAM_BODY_DEADLINE_S}s")
        chunk = fp.read(65536)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_UPSTREAM_BODY:
            raise UpstreamBodyTooLarge(
                f"upstream body exceeds {MAX_UPSTREAM_BODY} bytes")
    return b"".join(chunks)


def _is_event_stream(headers) -> bool:
    """上游响应是否 SSE 流：代理不读其正文（永不 EOF，读即钉死工作线程），
    交路由层 204 快速失败。"""
    return ((headers.get("Content-Type") or "").strip().lower()
            .startswith("text/event-stream"))


def fetch_upstream(url: str, timeout: float = _UPSTREAM_TIMEOUT_S,
                   cookie_header: str | None = None):
    """GET 上游，返回 (status, headers, body)；30x 不跟随原样返回。

    headers 为 email.message.Message（.get 大小写不敏感）。重定向返回空体，
    Location 由路由层经 :func:`rebase_redirect` 改写。不可达抛
    :class:`UpstreamUnreachable`，超体抛 :class:`UpstreamBodyTooLarge`。
    cookie_header 默认 None——不转发浏览器 Cookie（安全决策见
    :func:`cookie_header_from`）；仅未来显式 opt-in 时才原样转发给
    注册 target。
    """
    req_headers = {
        "User-Agent": _UPSTREAM_UA,
        "Accept-Encoding": "identity",   # 要改写的 HTML/CSS 必须拿未压缩体
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "*/*;q=0.8"),
    }
    if cookie_header:
        req_headers["Cookie"] = cookie_header
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            status = resp.status
            headers = resp.headers
            if _is_event_stream(headers):
                # SSE：响应头即知形态，正文永不 EOF——空体返回交路由层 204
                return status, headers, b""
            return status, headers, _read_capped(resp, resp.headers)
    except urllib.error.HTTPError as exc:
        try:
            body = b"" if _is_event_stream(exc.headers) \
                else _read_capped(exc, exc.headers)
        except (OSError, UpstreamBodyTooLarge):
            body = b""
        return exc.code, exc.headers, body
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # URLError（DNS/拒绝连接）、socket.timeout（OSError 子类）等全部
        # 收敛为结构化不可达；ValueError 兜非法 Location 等罕见解析异常
        raise UpstreamUnreachable(str(exc) or exc.__class__.__name__) from exc


def rebase_redirect(location: str, upstream_url: str,
                    target: str, prefix: str) -> str:
    """上游 30x 的 Location 改写：同源落代理前缀内，跨源原样透传。

    同源（= 注册 target 源）重定向若原样透传，浏览器会导航到 dashboard
    根下的同路径（绕过代理）——必须改写进前缀让浏览器继续经代理跟随；
    跨源重定向（SSO 跳外部等）代理不越权，透传后页面离开批注范围。
    """
    resolved = urllib.parse.urljoin(upstream_url, location or "")
    r = urllib.parse.urlsplit(resolved)
    t = urllib.parse.urlsplit(target)
    if (r.scheme, r.netloc) == (t.scheme, t.netloc):
        return prefix + r.path + (("?" + r.query) if r.query else "")
    return location or resolved


# ── 响应改写 ───────────────────────────────────────────────────────────

def response_charset(headers) -> str:
    """从 Content-Type 解析 charset；缺失/未知回落 utf-8。"""
    ctype = headers.get("Content-Type") or ""
    m = re.search(r"charset\s*=\s*([^\s;]+)", ctype, re.IGNORECASE)
    if m:
        try:
            return codecs.lookup(m.group(1).strip("\"' ")).name
        except (LookupError, ValueError):
            pass
    return "utf-8"


def maybe_gunzip(body: bytes, headers) -> bytes:
    """防御性解压：个别服务器无视 Accept-Encoding: identity 强推 gzip。

    解压失败一律回落原 body 不打断代理：BadGzipFile（OSError 子类）=
    头部损坏，EOFError = gzip 流被截断，zlib.error = 数据损坏——三者
    都不是可上抛的致命错误，外抛会把「解压失败降级」变成路由层 500。
    """
    if (headers.get("Content-Encoding") or "").strip().lower() == "gzip":
        try:
            return gzip.decompress(body)
        except (OSError, EOFError, zlib.error):
            return body
    return body


def rewrite_response(content_type: str, body: bytes, headers,
                     prefix: str, round_no: int | None):
    """HTML/CSS 响应改写（charset 保真往返）；不属改写类型返回 None。

    返回 (body, content_type)；改写响应的 Content-Encoding 由调用方剥除
    （maybe_gunzip 已解压或原文未压缩）。解码/回编码均 errors="replace"：
    声明与实际 charset 不符时不让代理 500，降级为个别字符替换。
    """
    low = (content_type or "").strip().lower()
    if low.startswith("text/html") or low.startswith("application/xhtml"):
        enc = response_charset(headers)
        text = maybe_gunzip(body, headers).decode(enc, errors="replace")
        text = rebase_html(text, prefix)
        text = inject_into_html(text, prefix, round_no)
        return text.encode(enc, errors="replace"), (content_type or "text/html")
    if low.startswith("text/css"):
        enc = response_charset(headers)
        text = rebase_css(
            maybe_gunzip(body, headers).decode(enc, errors="replace"), prefix)
        return text.encode(enc, errors="replace"), (content_type or "text/css")
    return None


# ── wrapper 页 ─────────────────────────────────────────────────────────

def build_wrapper_html(project: str, session: str, target: str,
                       sub_path: str, round_no: int | None,
                       entry_query: str = "") -> str:
    """顶层 wrapper 页：顶栏（目标/轮次/重载）+ iframe 嵌代理页。

    批注器活在 iframe 内（页面同源注入的前提）；wrapper 只承载稳定入口：
    轮次参数挂在 iframe src 上（annotator 从 iframe URL 读），应用内部
    跳转丢参数时轮次退回默认——与原型流程的迭代语义一致。entry_query
    是会话入口 query（token URL 等鉴权参数），随 iframe src 透传给上游。
    """
    prefix = proxy_prefix(project, session)
    frame_src = prefix + "/" + sub_path.lstrip("/")
    if entry_query:
        frame_src += "?" + entry_query
    if round_no and int(round_no) > 0:
        frame_src += ("&" if entry_query else "?") + "proto_round=" \
            + str(int(round_no))
    display_target = target + ("/" + sub_path.lstrip("/") if sub_path else "/")
    title = "fenix-ui-debug · " + session
    round_txt = str(int(round_no)) if round_no and int(round_no) > 0 else "1"
    import html as _html

    return (
        '<!doctype html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>" + _html.escape(title) + "</title>\n"
        "<style>\n"
        "html,body{margin:0;height:100%;}\n"
        "body{display:flex;flex-direction:column;"
        'font:13px/1.6 -apple-system,"Segoe UI",sans-serif;background:#1f1f1f;}\n'
        "#fdb-bar{display:flex;align-items:center;gap:10px;padding:6px 12px;"
        "background:#1f1f1f;color:#ddd;flex:none;}\n"
        "#fdb-bar strong{color:#fa8c16;white-space:nowrap;}\n"
        "#fdb-target{font-family:monospace;font-size:12px;color:#9dd3ff;"
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;}\n"
        "#fdb-round{color:#999;white-space:nowrap;font-size:12px;}\n"
        "#fdb-reload{border:1px solid #555;background:#2f2f2f;color:#eee;"
        "border-radius:4px;padding:2px 10px;cursor:pointer;white-space:nowrap;}\n"
        "#fdb-frame{flex:1;border:0;width:100%;background:#fff;}\n"
        "</style>\n</head>\n<body>\n"
        '<div id="fdb-bar"><strong>fenix-ui-debug</strong>'
        '<span id="fdb-target">' + _html.escape(display_target) + "</span>"
        '<span id="fdb-round">轮次 ' + _html.escape(round_txt) + "</span>"
        '<button id="fdb-reload" type="button">重载</button></div>\n'
        '<iframe id="fdb-frame" src="' + _html.escape(frame_src, quote=True)
        + '"></iframe>\n'
        "<script>\n"
        'document.getElementById("fdb-reload")\n'
        '  .addEventListener("click", function () {\n'
        '    var f = document.getElementById("fdb-frame");\n'
        "    f.src = f.src;\n"
        "  });\n"
        "</script>\n</body>\n</html>\n"
    )
