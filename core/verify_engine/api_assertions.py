"""
api_assertions.py — API 结构化断言库（spec multi-kind-scenario-model「API 词表与响应捕获」）

分层语义跨 kind 统一：
  第1层 存在性/状态（确定性，0误判）：status_code / sse_event_count
  第3层 内容正确性（确定性，0误判）：json_path / response_header /
        body_contains / json_schema / sse_event_matches
  第4层 启发式阈值（失败=warning，需上下文判定）：latency_under

第1-3层断言失败 = 一定是Bug。CLI/API 无第 2 层（交互可用性是 DOM 概念）。

断言引用响应 MUST 通过 ``response`` 字段指向命名捕获（缺省=最近一次响应）。
每个 ``http_request`` 响应捕获 ``{status, headers, body, json, latency_ms}``；
``sse_connect`` 捕获 ``{type: "sse", events: [...], duration}``。

jsonschema 依赖：json_schema 断言在验收期检查依赖（缺失=验收报错打回），
不在执行期静默跳过（spec verify-runner-engine：httpx 为 ApiRunner 硬依赖；
jsonschema 缺失时 json_schema 断言在验收期报错打回）。
"""

import json
import re
from typing import Any

ASSERTION_LAYERS = {
    "status_code": 1,
    "sse_event_count": 1,
    "json_path": 3,
    "response_header": 3,
    "body_contains": 3,
    "json_schema": 3,
    "sse_event_matches": 3,
    "latency_under": 4,
}

# jsonschema 缺省缺失不算词表错误——直到 json_schema 断言被使用才报错
_JSONSCHEMA_OK = None


def json_schema_available() -> bool:
    """jsonschema 库是否可用（验收期依赖检查用）。"""
    global _JSONSCHEMA_OK
    if _JSONSCHEMA_OK is None:
        try:
            import jsonschema  # noqa: F401

            _JSONSCHEMA_OK = True
        except ImportError:
            _JSONSCHEMA_OK = False
    return _JSONSCHEMA_OK


# ── JSONPath 求值（点路径子集）──────────────────────────────────

# 求值失败哨兵：区分「路径不存在」与「求值结果为 null」。
# 缺省求值仍返回 None（旧签名行为，供 cli_assertions 等调用方保持兼容）。
_MISSING = object()


def _split_path_tokens(path: str) -> list[str]:
    """按点切分路径，引号段（``'...'`` / ``"..."``）内的点不切分。

    分词正则支持引号键形态（``data['a.b']``），若直接 ``re.split(r"\\.", path)``
    会把含点的引号键撕裂成两段静默求值失败，故逐字符感知引号后再切分。
    """
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in path:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ".":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def evaluate_json_path(data: Any, path: str, missing: Any = None) -> Any:
    """按点路径求值 JSON 子树。

    支持的路径形态：
      - ``data.id``（对象键）
      - ``items[0].name``（数组下标）
      - 混合：``a.b[1].c``
      - 引号键（含点的键名）：``data['a.b']``
    求值失败（键缺失/越界）返回 ``missing``（缺省 None——与「值相等或不等」
    语义无关，断言结果通过 actual=None 与 expected 对比即可区分；
    传入哨兵可区分「路径不存在」与「显式 null」）。
    """
    if not path:
        return data
    cur = data
    for token in _split_path_tokens(path):
        if cur is None:
            return missing
        while token:
            m = re.match(r"([^\[]+)|\[(\d+|'[^']*'|\"[^\"]*\")\]", token)
            if not m:
                return missing
            if m.group(1) is not None:
                key = m.group(1)
                if isinstance(cur, dict) and key in cur:
                    cur = cur[key]
                else:
                    return missing
                token = token[len(key) :]
            else:
                idx_s = m.group(2)
                if idx_s.startswith(("'", '"')):
                    key = idx_s[1:-1]
                    if isinstance(cur, dict) and key in cur:
                        cur = cur[key]
                    else:
                        return missing
                    token = token[len(m.group(0)) :]
                else:
                    try:
                        idx = int(idx_s)
                    except ValueError:
                        return missing
                    if isinstance(cur, list) and 0 <= idx < len(cur):
                        cur = cur[idx]
                    else:
                        return missing
                    token = token[len(m.group(0)) :]
    return cur


class ApiAssertionRunner:
    """执行结构化 API 断言。

    每个断言方法签名为: async def _assert_<type>(self, resp, assertion) -> dict
    返回统一格式 dict: {type, layer, pass, ...}。

    ``resp`` 为响应捕获（status/headers/body/json/latency_ms 或 events）。
    """

    # ── 断言执行入口 ──────────────────────────────────────────

    async def run(self, captures: dict, assertions: list[dict]) -> list[dict]:
        """执行断言列表，返回每个断言的结果。

        Args:
            captures: 命名响应捕获表（含 ``_latest`` 最近一次响应；
                ``{"create": {...}, "_latest": {...}}``）。
            assertions: 断言定义列表。
        """
        results: list[dict] = []
        for assertion in assertions:
            a_type = assertion.get("type", "")
            handler = getattr(self, f"_assert_{a_type}", None)
            if handler is None:
                results.append(
                    {
                        "type": a_type,
                        "layer": ASSERTION_LAYERS.get(a_type, 0),
                        "pass": False,
                        "error": f"未知断言类型: {a_type}",
                    }
                )
                continue
            resp = self._resolve_response(captures, assertion)
            if resp is None:
                ref = assertion.get("response") or "_latest"
                results.append(
                    {
                        "type": a_type,
                        "layer": ASSERTION_LAYERS.get(a_type, 0),
                        "pass": False,
                        "error": f"断言引用的响应 '{ref}' 不存在"
                        f"（response 字段指向命名捕获，缺省=最近一次）",
                    }
                )
                continue
            try:
                result = await handler(resp, assertion)
                result.setdefault("type", a_type)
                result.setdefault("layer", ASSERTION_LAYERS.get(a_type, 0))
                results.append(result)
            except Exception as e:
                results.append(
                    {
                        "type": a_type,
                        "layer": ASSERTION_LAYERS.get(a_type, 0),
                        "pass": False,
                        "error": f"断言执行异常: {e}",
                    }
                )
        return results

    def _resolve_response(self, captures: dict, assertion: dict) -> Any:
        """断言引用的响应：response 字段指定命名捕获，缺省=最近一次。"""
        ref = assertion.get("response") or "_latest"
        return captures.get(ref)

    # ═══════════════════════════════════════════════════════════════
    # 第1层：存在性/状态（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_status_code(self, resp, a: dict) -> dict:
        """断言 HTTP 状态码等于期望值（expected 允许 str/int 表示等价，如 "200"）。"""

        def _numeric(value: Any) -> Any:
            # 仅做 str/int 表示归一：可解析为整型则按数值比较，否则保持原值严格相等
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                return value

        expected = a.get("expected")
        actual = resp.get("status")
        # fail-closed：expected 缺失时不得借 None==None 蒙混判 pass（验收期
        # 必填表 ASSERTION_REQUIRED_FIELDS 是前置防线，此处兜住运行期自愈/
        # 绕过验收的调用路径），口径对齐 json_path 断言的 fail-closed
        passed = expected is not None and _numeric(actual) == _numeric(expected)
        result = {
            "type": "status_code",
            "layer": 1,
            "expected": expected,
            "actual": actual,
            "pass": passed,
        }
        if expected is None:
            result["error"] = "断言缺 expected，无法与实际状态码对比（fail-closed）"
        return result

    async def _assert_sse_event_count(self, resp, a: dict) -> dict:
        """断言 SSE 窗口内事件数不少于下限（第1层存在性）。"""
        events = resp.get("events") or []
        minimum = int(a.get("min", 1))
        return {
            "type": "sse_event_count",
            "layer": 1,
            "min": minimum,
            "actual": len(events),
            "pass": len(events) >= minimum,
        }

    # ═══════════════════════════════════════════════════════════════
    # 第3层：内容正确性（确定性，0误判）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_json_path(self, resp, a: dict) -> dict:
        """断言 JSON 子树与期望值相等（path 点路径求值）。"""
        path = a.get("path")
        expected = a.get("expected")
        payload = resp.get("json")
        if payload is None:
            if resp.get("type") == "sse":
                # 定向提示：SSE 捕获（{type: sse, events, duration}）无 JSON
                # 载荷属捕获类型不匹配，非「响应体非合法 JSON」，防 judge 误
                # 归因；SSE 事件内容断言应走 sse_event_matches
                return {
                    "type": "json_path",
                    "layer": 3,
                    "path": path,
                    "expected": expected,
                    "actual": None,
                    "pass": False,
                    "error": (
                        "json_path 断言不支持 SSE 捕获（无 JSON 载荷）；"
                        "事件内容断言请改用 sse_event_matches"
                    ),
                }
            # fail-closed：无 JSON 载荷时不得以 actual=None 与 expected=None 蒙混判 pass
            return {
                "type": "json_path",
                "layer": 3,
                "path": path,
                "expected": expected,
                "actual": None,
                "pass": False,
                "error": "响应体非合法 JSON（或 JSON 根为 null），无 JSON 载荷可求值",
            }
        actual = evaluate_json_path(payload, path, missing=_MISSING)
        mode = a.get("mode", "exact")
        path_missing = actual is _MISSING
        if path_missing:
            # 哨兵仅用于内部判定，不外泄到结果（actual 归一为 None）
            actual = None
        passed = False
        error = None
        if mode not in ("exact", "contains", "regex"):
            # 配置错误可见化：与 run() 入口「未知断言类型」口径对齐，
            # 避免拼写错的 mode 静默按失败处理、被误归因为产品缺陷
            error = f"未知 mode: {mode}"
        elif path_missing:
            # 0 误判：expected=null 时「路径不存在」≠「显式 null」，fail-closed。
            # 路径缺失对任何内容比对 mode 都显式报错（与 exact 分支口径统一，
            # 供 judge 区分「路径缺失——多为产品/场景缺陷」与「内容不符」）；
            # 否则 contains/regex 会把缺失归一为空串静默失败，expected 可
            # 匹配空串时甚至假阳性通过
            passed = False
            error = (
                f"路径 {path!r} 在 JSON 载荷中不存在（区别于显式 null），"
                f"无法与 expected 对比"
            )
        elif mode == "exact":
            passed = actual == expected
        elif mode == "contains":
            # 以 is not None 判空：or 会把 0/False 等 falsy 合法值折叠为 ""；
            # 左侧 expected 一并 str 归一（数值/布尔形态不抛 TypeError，
            # 与 sse_event_matches 口径对齐）
            passed = str(expected) in str(actual if actual is not None else "")
        else:  # regex
            try:
                passed = bool(
                    re.search(str(expected), str(actual if actual is not None else ""))
                )
            except re.error:
                passed = False
        result = {
            "type": "json_path",
            "layer": 3,
            "path": path,
            "expected": expected,
            "actual": actual,
            "pass": passed,
        }
        if error is not None:
            result["error"] = error
        return result

    async def _assert_response_header(self, resp, a: dict) -> dict:
        """断言响应头存在且匹配（header 名大小写不敏感）。"""
        header = a.get("header", "")
        expected = a.get("expected", "")
        mode = a.get("mode", "exact")
        actual = None
        for k, v in (resp.get("headers") or {}).items():
            if k.lower() == str(header).lower():
                actual = v
                break
        passed = False
        error = None
        if mode not in ("exact", "contains", "regex"):
            # 配置错误可见化：与 run() 入口「未知断言类型」口径对齐
            error = f"未知 mode: {mode}"
        elif actual is not None:
            if mode == "exact":
                passed = str(actual).strip() == str(expected).strip()
            elif mode == "contains":
                # expected 一并 str 归一（数值/布尔形态不抛 TypeError）
                passed = str(expected) in str(actual)
            elif mode == "regex":
                try:
                    passed = bool(re.search(str(expected), str(actual)))
                except re.error:
                    passed = False
        else:
            # 头不存在与值不匹配区分归因（与 json_path 缺失分支口径对齐），
            # judge 无须从 actual=None 自行推断
            error = f"响应头 '{header}' 不存在"
        result = {
            "type": "response_header",
            "layer": 3,
            "header": header,
            "expected": expected,
            "actual": actual,
            "pass": passed,
        }
        if error is not None:
            result["error"] = error
        return result

    async def _assert_body_contains(self, resp, a: dict) -> dict:
        """断言响应体包含期望文本。"""
        expected = a.get("expected", "")
        mode = a.get("mode", "contains")
        body = resp.get("body") or ""
        passed = False
        error = None
        if mode not in ("exact", "contains", "regex"):
            # 配置错误可见化：与 run() 入口「未知断言类型」口径对齐
            error = f"未知 mode: {mode}"
        elif mode == "exact":
            passed = str(body).strip() == str(expected).strip()
        elif mode == "contains":
            # expected 一并 str 归一（数值/布尔形态不抛 TypeError，与
            # sse_event_matches 口径对齐）
            passed = str(expected) in str(body)
        elif mode == "regex":
            try:
                passed = bool(re.search(str(expected), str(body)))
            except re.error:
                passed = False
        result = {
            "type": "body_contains",
            "layer": 3,
            "expected": expected,
            "mode": mode,
            "pass": passed,
            "actual_snippet": str(body)[:200] if not passed and body else "",
        }
        if error is not None:
            result["error"] = error
        return result

    async def _assert_json_schema(self, resp, a: dict) -> dict:
        """断言响应体 JSON 符合 schema（jsonschema 库；验收期已查依赖）。"""
        if not json_schema_available():
            return {
                "type": "json_schema",
                "layer": 3,
                "pass": False,
                "error": "json_schema 断言需要 jsonschema 库（验收期已打回，此处不应到达）",
            }
        import jsonschema

        schema = a.get("schema")
        if not isinstance(schema, dict):
            # schema 缺失/非 dict 预检：jsonschema.validate 对非 dict schema
            # 抛 SchemaError 而非 ValidationError，不预检会被 run() 包成笼统
            # 「断言执行异常」，judge 无法区分「响应不合 schema」与「场景
            # schema 本身写错」
            return {
                "type": "json_schema",
                "layer": 3,
                "pass": False,
                "error": (
                    f"schema 非法: 须为 JSON Schema 对象（dict），"
                    f"实际 {type(schema).__name__}"
                ),
            }
        payload = resp.get("json")
        if payload is None:
            return {
                "type": "json_schema",
                "layer": 3,
                "pass": False,
                "error": "响应体非合法 JSON，无法做 schema 校验",
            }
        try:
            jsonschema.validate(payload, schema)
            return {"type": "json_schema", "layer": 3, "pass": True}
        except jsonschema.ValidationError as e:
            return {
                "type": "json_schema",
                "layer": 3,
                "pass": False,
                "error": f"schema 校验失败: {e.message}（{e.json_path}）",
            }
        except jsonschema.SchemaError as e:
            # 运行期兜底（自愈/绕过验收的调用路径）补全：schema 本身写错
            # 属场景缺陷，与「响应不合 schema」须可区分
            return {
                "type": "json_schema",
                "layer": 3,
                "pass": False,
                "error": f"schema 非法: {e.message}",
            }

    async def _assert_sse_event_matches(self, resp, a: dict) -> dict:
        """断言 SSE 窗口内存在与期望匹配的事件（data 字段）。"""
        events = [dict(e) for e in (resp.get("events") or [])]
        expected = a.get("expected", "")
        mode = a.get("mode", "contains")
        # fail-closed：缺 expected 时 contains 空串恒真、regex 空串恒匹配，
        # 窗口内有任一事件即假通过；与 web 侧 text_match 缺参显式失败口径
        # 一致（exact 空串是合法期望，不在拦截之列）
        if expected is None or (expected == "" and mode in ("contains", "regex")):
            return {
                "type": "sse_event_matches",
                "layer": 3,
                "expected": expected,
                "mode": mode,
                "actual_hits": [],
                "hit_count": 0,
                "pass": False,
                "error": "缺少 expected 字段",
            }
        # 配置错误可见化：与 run() 入口「未知断言类型」口径对齐（未知 mode 不再静默）
        error = None if mode in ("exact", "contains", "regex") else f"未知 mode: {mode}"
        hits = []
        for ev in events:
            data = str(ev.get("data") or "")
            if mode == "exact":
                matched = data.strip() == str(expected).strip()
            elif mode == "contains":
                matched = str(expected) in data
            elif mode == "regex":
                try:
                    matched = bool(re.search(str(expected), data))
                except re.error:
                    matched = False
            else:
                matched = False
            if matched:
                hits.append(data)
        result = {
            "type": "sse_event_matches",
            "layer": 3,
            "expected": expected,
            "mode": mode,
            "actual_hits": hits[:5],
            "hit_count": len(hits),
            "pass": len(hits) > 0,
        }
        if error is not None:
            result["error"] = error
        return result

    # ═══════════════════════════════════════════════════════════════
    # 第4层：启发式阈值（失败=warning，需上下文判定）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_latency_under(self, resp, a: dict) -> dict:
        """断言响应延迟低于毫秒上限（启发式，慢环境不判产品缺陷）。"""
        expected = a.get("expected")
        actual = resp.get("latency_ms")
        return {
            "type": "latency_under",
            "layer": 4,
            "expected": expected,
            "actual": actual,
            "pass": actual is not None and actual < int(expected),
        }
