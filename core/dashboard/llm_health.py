"""llm_health.py — LLM Provider 健康检测（add-provider-health-check，纯探测无副作用）。

对 ``{baseurl}/v1/messages`` 发一条最小消息请求（role=user / content="hello" /
max_tokens=256），回答「这个 Provider+模型组合当前能不能回复 + 多快」。

请求构造照抄 ``bin/probe_prompt_cache.py`` 先例：stdlib urllib（不引入 requests
依赖）、``x-api-key`` + ``anthropic-version: 2023-06-01``、apikey 非空时附加
``Authorization: Bearer``——同时覆盖两种传输口径，与 claude CLI 运行期
（ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY 走 Anthropic 兼容协议）同路径同协议，
检测结论对运行期可用性有效。

设计约束（design D2/D4）：
- 纯函数式探测，handler 只做参数校验与响应编排；HTTP 探测独立成函数便于单测
  （monkeypatch 替换 urlopen）。
- 探测为只读，MUST NOT 写入 provider_circuit 的熔断计数 / 切换冷却 / 半开探针
  状态——手动健康检测与运行期熔断彼此独立。
- 函数内不落盘 apikey 与完整响应内容（错误只回传截断后的响应片段）。
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request

# 超时单源常量（design D4）：同步 urlopen(timeout=) 直传；检测是用户点击后的
# 显式等待，15s 足够覆盖慢网关又不至于让页面干等过久。
HEALTH_CHECK_TIMEOUT_SECONDS = 15

# 非成功响应体回传片段的截断上限（spec「上游返回 HTTP 错误」：≤200 字符）
_ERROR_SNIPPET_MAX_CHARS = 200

# 最小探测请求的 max_tokens。曾为 64：思考型模型（GLM/DeepSeek 系）网关侧默认
# 开思考，64 全花在 thinking 块上没有正文，被误报 empty_reply（09-29 实测
# bigmodel.cn / maomaoai 双双误报，max_tokens=256 实测均 end_turn 正常回文）。
# 探测消息固定 "hello"，思考长度可预期很短，256 已留足正文余量且成本可忽略。
_PROBE_MAX_TOKENS = 256

# 探测 UA 与运行期 claude CLI 同签名。urllib 默认 UA（Python-urllib/3.x）会被
# Cloudflare 等反爬规则按签名拦截（error code: 1010，09-29 实测 corealgos.com
# 403 误拦，掩盖真实业务错误）——同机 CLI 能过的签名探测也应当能过。
_PROBE_USER_AGENT = "claude-cli/2.1.277 (external, cli)"


class _NoCrossHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """拒绝跟随跨主机重定向（redirect_request 返回 None → urllib 抛 HTTPError，
    由 run_llm_health_check 的既有 http_error 分类接住）。

    urllib 默认跟随 301/302 且除 content-length/content-type 外原样转发请求头，
    x-api-key / Authorization: Bearer 会发往 Location 指向的新主机——baseurl/apikey
    由表单直传，跨主机重定向（误配 http→https、开放重定向等）会把探测密钥泄漏
    给第三方。同主机重定向照常放行。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        origin = urllib.parse.urlsplit(req.full_url).netloc.lower()
        target = urllib.parse.urlsplit(newurl).netloc.lower()
        if origin != target:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_probe_request(baseurl: str, apikey: str, model: str) -> urllib.request.Request:
    """构造 urllib Request——与 bin/probe_prompt_cache.py::_post_once 同构。"""
    # 归一尾部 /v1（含 /v1/）：整段「https://host/v1」粘进表单时不剥离会拼出 /v1/v1/messages 的误导性 404
    root = baseurl.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    url = root + "/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": apikey or "",
        "anthropic-version": "2023-06-01",
        "User-Agent": _PROBE_USER_AGENT,
    }
    if apikey:
        headers["Authorization"] = f"Bearer {apikey}"
    body = {
        "model": model,
        "max_tokens": _PROBE_MAX_TOKENS,
        "messages": [{"role": "user", "content": "hello"}],
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    return req


def _truncate(text: str) -> str:
    """响应片段截断 ≤200 字符（先去首尾空白，避免片段以换行开头）。"""
    snippet = (text or "").strip()
    if len(snippet) > _ERROR_SNIPPET_MAX_CHARS:
        return snippet[:_ERROR_SNIPPET_MAX_CHARS]
    return snippet


def _reply_text(data: object) -> str:
    """从 200 响应体解析非空文本 content（找不到返回空串）。

    标准 Anthropic messages 响应 content 为块数组（type=text 块取 text 拼接）；
    部分网关退化为纯字符串 content——同样视为文本回复。
    """
    if not isinstance(data, dict):
        return ""
    content = data.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _thinking_text(data: object) -> str:
    """从 200 响应体解析非空 thinking 块拼接（找不到返回空串）。

    兜底判据：即使正文被 max_tokens 截断，模型能产出思考内容也证明该
    Provider+模型组合存活可用——据此免疫思考型模型的 empty_reply 误报。
    """
    if not isinstance(data, dict):
        return ""
    content = data.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            text = block.get("thinking")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def run_llm_health_check(baseurl: str, apikey: str, model: str) -> dict:
    """对 {baseurl}/v1/messages 发最小消息请求，返回检测结果 dict。

    返回形态（task 1.1）::

        {"ok", "latency_ms", "error_kind", "status", "error", "model"}

    - 成功：ok=True、latency_ms 为实测正整数（毫秒）、model 回显请求的模型名
      （spec「模型正常回复」）；error_kind / status / error 为 None。
    - http_error：非 200，status 透传、error 为截断 ≤200 字符的响应片段。
    - connection_error / timeout：error 为简要原因，latency_ms 为实测耗时。
    - empty_reply：200 但解析不到非空文本 content（含响应非合法 JSON）。
      例外：正文缺失但 thinking 块非空（思考型模型预算被思考吃尽）按成功处理。

    失败四分类中 latency_ms 恒为实测耗时（毫秒，下限钳到 1，见 _latency_ms）。
    不落盘 apikey 与完整响应。
    """
    started = time.monotonic()
    try:
        # 构造也在守卫内：baseurl 非法（unknown url type）在 Request 构造期
        # 即抛 ValueError，须与 urlopen 阶段的同类失败同口径归类
        req = _build_probe_request(baseurl, apikey, model)
        # 挂跨主机重定向拦截 handler 的局部 opener（勿 install_opener，避免改全局状态）
        opener = urllib.request.build_opener(_NoCrossHostRedirectHandler)
        with opener.open(req, timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # 非 200：读错误体片段供排障（401 密钥无效 / 404 路径不对 / 429 限流等）
        try:
            snippet = _truncate(e.read().decode("utf-8", errors="replace"))
        except (OSError, http.client.HTTPException):
            # 错误体读取中断（如 IncompleteRead）同样只是拿不到片段，兜底空串
            snippet = ""
        return _fail(started, "http_error", error=snippet or f"HTTP {e.code}", status=e.code)
    except urllib.error.URLError as e:
        # urlopen 阶段的超时会包成 URLError(reason=TimeoutError)，须与连接类
        # 失败区分（DNS 解析失败 / 拒绝连接 → connection_error）
        reason = getattr(e, "reason", None)
        if isinstance(reason, TimeoutError):
            return _fail(started, "timeout", error=f"上游 {HEALTH_CHECK_TIMEOUT_SECONDS}s 内未返回: {reason}")
        return _fail(started, "connection_error", error=f"{reason or e}")
    except TimeoutError as e:
        # 读响应阶段的裸 socket 超时（响应头已到但体挂起）
        return _fail(started, "timeout", error=f"上游 {HEALTH_CHECK_TIMEOUT_SECONDS}s 内未返回: {e}")
    except http.client.IncompleteRead as e:
        # 响应头已到但体未收齐（上游网关提前断流）——同属连接类失败，
        # 维持「探测失败也是业务数据（恒 200 自含返回）」契约
        return _fail(started, "connection_error", error=f"上游连接提前关闭: {e}")
    except http.client.HTTPException as e:
        # 其余 HTTP 协议层异常（垃圾状态行 BadStatusLine / LineTooLong 等）既非
        # URLError 也非 OSError，不接住会以 500 穿透路由层——归连接类失败
        return _fail(started, "connection_error", error=f"上游 HTTP 协议异常: {e}")
    except (OSError, ValueError) as e:
        # OSError：连接被拒 / DNS 失败 / 远端断开；ValueError：baseurl 非法
        # （urllib 对 unknown url type 抛 ValueError，spec 归 connection_error）
        return _fail(started, "connection_error", error=str(e))

    latency_ms = _latency_ms(started)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return _fail(started, "empty_reply", error=f"响应非合法 JSON: {e}")
    text = _reply_text(data)
    if not text and _thinking_text(data):
        # 正文缺失但思考内容非空（思考型模型预算被 thinking 吃尽的兜底）：
        # 模型确实在产出，provider 存活——按成功处理
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "error_kind": None,
            "status": None,
            "error": None,
            "model": model,
        }
    if not text:
        # 200 但空 content / 非 text 块 / 上游错误体——按「无文本回复」归类
        return _fail(started, "empty_reply", error="响应解析不到非空文本 content")
    return {
        "ok": True,
        "latency_ms": latency_ms,
        "error_kind": None,
        "status": None,
        "error": None,
        "model": model,
    }


def _latency_ms(started: float) -> int:
    """发请求到收齐响应的实测毫秒数；成功回复至少收到过 1 字节，取整为 0
    时下限钳到 1（spec「latency_ms 为正整数」）。"""
    return max(1, int((time.monotonic() - started) * 1000))


def _fail(started: float, error_kind: str, *, error: str, status: int | None = None) -> dict:
    """统一失败响应体构造（ok=False；model 不回显——失败场景无「正常回复的模型」）。"""
    return {
        "ok": False,
        "latency_ms": _latency_ms(started),
        "error_kind": error_kind,
        "status": status,
        "error": error,
        "model": None,
    }
