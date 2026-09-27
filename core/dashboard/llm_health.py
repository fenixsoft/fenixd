"""llm_health.py — LLM Provider 健康检测（add-provider-health-check，纯探测无副作用）。

对 ``{baseurl}/v1/messages`` 发一条最小消息请求（role=user / content="hello" /
max_tokens=64），回答「这个 Provider+模型组合当前能不能回复 + 多快」。

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
import urllib.request

# 超时单源常量（design D4）：同步 urlopen(timeout=) 直传；检测是用户点击后的
# 显式等待，15s 足够覆盖慢网关又不至于让页面干等过久。
HEALTH_CHECK_TIMEOUT_SECONDS = 15

# 非成功响应体回传片段的截断上限（spec「上游返回 HTTP 错误」：≤200 字符）
_ERROR_SNIPPET_MAX_CHARS = 200

# 最小探测请求的 max_tokens（proposal：成本可忽略，不自动重试）
_PROBE_MAX_TOKENS = 64


def _build_probe_request(baseurl: str, apikey: str, model: str) -> urllib.request.Request:
    """构造 urllib Request——与 bin/probe_prompt_cache.py::_post_once 同构。"""
    url = baseurl.rstrip("/") + "/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": apikey or "",
        "anthropic-version": "2023-06-01",
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


def run_llm_health_check(baseurl: str, apikey: str, model: str) -> dict:
    """对 {baseurl}/v1/messages 发最小消息请求，返回检测结果 dict。

    返回形态（task 1.1）::

        {"ok", "latency_ms", "error_kind", "status", "error", "model"}

    - 成功：ok=True、latency_ms 为实测正整数（毫秒）、model 回显请求的模型名
      （spec「模型正常回复」）；error_kind / status / error 为 None。
    - http_error：非 200，status 透传、error 为截断 ≤200 字符的响应片段。
    - connection_error / timeout：error 为简要原因，latency_ms 为实测耗时。
    - empty_reply：200 但解析不到非空文本 content（含响应非合法 JSON）。

    失败四分类中 latency_ms 恒为实测耗时（毫秒，连接类瞬时失败可能小到取整
    为 0，与 spec「实测耗时或 0」口径一致）。不落盘 apikey 与完整响应。
    """
    started = time.monotonic()
    try:
        # 构造也在守卫内：baseurl 非法（unknown url type）在 Request 构造期
        # 即抛 ValueError，须与 urlopen 阶段的同类失败同口径归类
        req = _build_probe_request(baseurl, apikey, model)
        with urllib.request.urlopen(
            req, timeout=HEALTH_CHECK_TIMEOUT_SECONDS
        ) as resp:
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
