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

# 词表 layer 表单一权威源在 scenarios.py（KIND_ASSERTION_LAYERS 的 api 侧），
# 此处别名导入不再维护副本，避免新增 api 断言类型时两表漂移、layer 静默落 0
from .scenarios import API_ASSERTION_LAYERS as ASSERTION_LAYERS

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


# ── regex 预检（API 侧四处内容断言共用）────────────────────────

# regex 第三方库可选增强：其引擎对嵌套量词等灾难回溯形态自带线性化保护，
# 且支持 timeout（超时抛 TimeoutError）。场景正则由 planner 生成（有幻觉
# 正则原语前科），嵌套量词类病态模式对 64KB 级 body/事件文本 search 可指数
# 回溯长时间阻塞验证事件循环；库缺失时回退 stdlib re（行为同无防护版）。
try:
    import regex as _regex_lib
except ImportError:  # pragma: no cover - 环境相关分支
    _regex_lib = None

# 单次正则匹配的墙上时钟上限（秒）：合法断言正则对 64KB 文本远低于此值
_REGEX_MATCH_TIMEOUT_SECONDS = 1.0


class TimeoutRegexError(re.error):
    """regex 库匹配超时（疑似灾难性回溯）的定向异常。

    继承 re.error 以保住调用方既有 ``except re.error`` 捕获面（超时沿
    原异常面传播、run() 归一为带定向归因的断言失败），同时让「匹配
    超时」在类型层可判别——调用点无须再依赖文案区分超时与真正的
    非法正则（非法正则在 _compile_regex 预检期返回、不以此类型抛出）。
    """


class _TimeoutRegex:
    """re.Pattern 的回溯安全包装：search 走 regex 库（带 timeout）防阻塞。

    对外只暴露与 re.Pattern 同形的 ``search(text) -> bool``，四处内容断言
    调用点无须感知背后是 regex 库还是 stdlib 回退。
    """

    def __init__(self, source: str, compiled: re.Pattern):
        self._source = source
        self._compiled = compiled

    def search(self, text: str) -> bool:
        if _regex_lib is not None:
            try:
                return (
                    _regex_lib.search(
                        self._source, text, timeout=_REGEX_MATCH_TIMEOUT_SECONDS
                    )
                    is not None
                )
            except TimeoutError:
                # 超时按确定性配置失败 fail-closed：沿 TimeoutRegexError（
                # re.error 子类）传播，调用点既有 except re.error 捕获面不变
                # （run() 归一为带定向归因的断言失败），防 judge 把场景正则
                # 缺陷误归因为产品缺陷
                raise TimeoutRegexError(
                    f"正则匹配超时（>{_REGEX_MATCH_TIMEOUT_SECONDS}s，"
                    f"疑似灾难性回溯）: {self._source!r}"
                ) from None
        return self._compiled.search(text) is not None


def _compile_regex(pattern: str) -> tuple[_TimeoutRegex | None, str | None]:
    """进匹配前编译预检：非法正则是确定性配置错误。

    此前各 regex 分支 ``except re.error: passed = False`` 静默吞错，结果与
    「内容确实不匹配」无法区分，judge 会把 planner 写错的正则误归因为产品
    缺陷；统一预检后非法时返回带「非法正则」error 的确定性失败（口径对齐
    web 侧 _assert_text_match）。返回 (compiled, None)；非法时 (None, 文案)。
    预检仍用 stdlib re.compile（保持非法判定口径），编译产物包一层
    _TimeoutRegex：regex 库可用时匹配带 timeout，防病态正则长时间阻塞
    （见 _TimeoutRegex）。
    """
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return None, f"非法正则: {e}"
    return _TimeoutRegex(pattern, compiled), None


# ── JSONPath 求值（点路径子集）──────────────────────────────────

# 求值失败哨兵：区分「路径不存在」与「求值结果为 null」。
# 缺省求值仍返回 None（旧签名行为，供 cli_assertions 等调用方保持兼容）。
_MISSING = object()


def _split_path_tokens(path: str) -> list[str]:
    """按点切分路径，引号段（``'...'`` / ``"..."``）内的点不切分。

    分词正则支持引号键形态（``data['a.b']``），若直接 ``re.split(r"\\.", path)``
    会把含点的引号键撕裂成两段静默求值失败，故逐字符感知引号后再切分。
    产出空段（连续点/首尾点，如 ``a..b`` / ``.name``）、裸引号段（如
    ``data.'a.b'`` 的 ``'a.b'``——引号键仅 ``data['a.b']`` 括号形态在契约
    内）或引号未闭合（如 ``data['a.b``）时抛 ValueError：空段若被静默跳过、
    裸引号段/未闭合引号若被当普通字符求值，拼错的 path 会等价于另一条路径
    在错误节点上求值、判 pass/fail，与「未知 mode」的配置错误可见化口径
    相悖（fail-closed）。
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
    if any(not part for part in parts):
        raise ValueError(f"路径非法（含连续点或首尾点空段）: {path!r}")
    if quote is not None:
        # 未闭合引号若静默流入求值，引号字符被当普通键名、按「路径不存在」
        # 失败，场景路径笔误会被误归因为产品缺陷——与空段同口径 fail-closed
        raise ValueError(f"路径非法（引号未闭合）: {path!r}")
    if any(part[0] in ("'", '"') for part in parts):
        # 裸引号段（如 data.'a.b'）流入求值同样带引号字符整段查键、必然
        # miss 并按「路径不存在」失败，judge 会把「路径形态不支持」误归因
        # 为产品/场景路径缺失——与未闭合引号同口径显式 fail-closed
        raise ValueError(
            f"路径非法（裸引号段，引号键须用括号形态 data['a.b']）: {path!r}"
        )
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
    路径非法（含空段、裸引号段、引号未闭合或畸形括号段）抛 ValueError，
    由调用方归一为显式 error。
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
                # 首分支 [^\[]+ 对任何非 [ 起始的 token 恒可匹配，失配必为
                # [ 起始的畸形括号段（未闭合下标 data[0、裸标识符 data[abc]、
                # 数字后缀 data[0x] 等）。若静默按「路径不存在」失败，judge
                # 会把路径语法笔误误归因为产品/场景缺陷——与 _split_path_tokens
                # 对空段/裸引号段/未闭合引号的口径一致，显式 fail-closed
                raise ValueError(
                    f"路径非法（括号段须为数字下标或引号键）: {path!r}"
                )
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


def _missing_expected(expected: Any, mode: Any) -> bool:
    """expected 缺失/空串的 fail-closed 拦截判定（本模块四处内容断言共用）。

    语义口径（固化于此，调用点勿各自解读）：
    - None 是 Assertion 的「未设置」哨兵（非显式 null），任何 mode 都拦截
      ——否则 exact 与 None 判等、contains 以 "None" 子串、regex 以字面
      None 为模式参与匹配，配置缺失被静默当作合法期望；
    - 空串仅在 contains/regex 下拦截（空串 contains 恒真、regex 恒匹配，
      假绿）；exact 空串是合法期望（断言值为空），放行。

    调用点：json_path / response_header / body_contains / sse_event_matches；
    语义若要调整只改此处，防四处拦截口径漂移分叉。
    """
    return expected is None or (expected == "" and mode in ("contains", "regex"))


class ApiAssertionRunner:
    """执行结构化 API 断言。

    每个断言方法签名为: async def _assert_<type>(self, resp, assertion) -> dict
    返回统一格式 dict: {type, pass, ...}；layer 不由 handler 携带，统一由
    run() 从 ASSERTION_LAYERS（scenarios.py 权威词表）注入。

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
            if not isinstance(assertion, dict):
                # fail-closed：非 dict 断言条目（planner/自愈链路产出的畸形
                # 条目，如字符串或 None）会让下方 assertion.get 抛
                # AttributeError，且在 run() 的 try 之外直接穿透（try 只包
                # handler 调用）；本文件对 capture 形状（events 非 dict、
                # schema 非 dict）都有显式防御，断言条目是同级别的不可信
                # 输入。按「未知断言类型」同款结构返回确定性失败
                results.append(
                    {
                        "type": None,
                        "layer": 0,
                        "pass": False,
                        "error": (
                            f"断言条目非法: 须为 dict，"
                            f"实际 {type(assertion).__name__}"
                        ),
                    }
                )
                continue
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
            "expected": expected,
            "actual": actual,
            "pass": passed,
        }
        if expected is None:
            result["error"] = "断言缺 expected，无法与实际状态码对比（fail-closed）"
        return result

    async def _assert_sse_event_count(self, resp, a: dict) -> dict:
        """断言 SSE 窗口内事件数不少于下限（第1层存在性）。"""
        # 定向提示：http_request 捕获（{status, headers, body, json, latency_ms}）
        # 无 events，事件计数挂在普通捕获上会恒按 0 事件失败且无 error，judge
        # 须能区分「场景把断言挂错捕获类型」与真实「事件数不足」（反向形态，
        # 口径对齐 json_path / latency_under 的 SSE 定向归因）
        if resp.get("type") != "sse":
            return {
                "type": "sse_event_count",
                "min": a.get("min", 1),
                "actual": None,
                "pass": False,
                "error": (
                    "sse_event_count 断言不支持 http_request 捕获（无 events）；"
                    "事件计数请引用 sse_connect 捕获"
                ),
            }
        events = resp.get("events") or []
        raw_min = a.get("min", 1)
        # fail-closed：min 非数字时不得让 int() 抛 ValueError 被 run() 包成
        # 笼统「断言执行异常」，judge 须能区分场景配置错误与产品缺陷
        # （口径对齐 _assert_latency_under 的 expected 预检）
        try:
            minimum = int(raw_min)
        except (TypeError, ValueError):
            minimum = None
        # fail-closed：负数下限对任意事件数（含 0）恒真且不附 error，无意义
        # 配置被静默放行为假绿，与本文件对 expected 缺失/未知 mode 的
        # fail-closed 拦截纪律同口径；0 是合法期望（断言零事件），不在拦截之列
        negative_min = minimum is not None and minimum < 0
        if negative_min:
            minimum = None
        actual = len(events)
        result = {
            "type": "sse_event_count",
            "min": minimum,
            "actual": actual,
            "pass": minimum is not None and actual >= minimum,
        }
        if minimum is None:
            if negative_min:
                result["error"] = (
                    f"sse_event_count 的 min 须为非负整数（事件数下限）: {raw_min!r}"
                )
            else:
                result["error"] = (
                    f"sse_event_count 的 min 非数字（事件数下限）: {raw_min!r}"
                )
        return result

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
            if resp.get("json_parse_skipped"):
                # capture 标注透出：响应体超解析上限被跳过解析置 json=None，
                # 「非合法 JSON」文案会把体积问题误归因为响应格式缺陷
                return {
                    "type": "json_path",
                    "path": path,
                    "expected": expected,
                    "actual": None,
                    "pass": False,
                    "error": f"{resp['json_parse_skipped']}，无 JSON 载荷可求值",
                }
            return {
                "type": "json_path",
                "path": path,
                "expected": expected,
                "actual": None,
                "pass": False,
                "error": "响应体非合法 JSON（或 JSON 根为 null），无 JSON 载荷可求值",
            }
        # fail-closed：path 缺失/空串时 evaluate_json_path 按缺省语义返回整棵
        # 文档，exact 拿整文档对比且无定向 error（与「未知 mode」「缺少
        # expected」口径不一致，judge 难归因）；非字符串 path 同样不静默
        # str() 归一求值。口径对齐 cli 侧 file_exists 的「缺少 path 字段」
        # （验收期必填表 ASSERTION_REQUIRED_FIELDS 是前置防线，此处兜住
        # 运行期自愈/绕过验收的调用路径）
        if not isinstance(path, str) or not path:
            return {
                "type": "json_path",
                "path": path,
                "expected": expected,
                "actual": None,
                "pass": False,
                "error": "缺少 path 字段",
            }
        try:
            actual = evaluate_json_path(payload, path, missing=_MISSING)
        except ValueError as e:
            # 路径非法可见化：与「未知 mode」口径对齐，避免拼错的 path 沿
            # 另一条路径静默求值、被判为产品缺陷
            return {
                "type": "json_path",
                "path": path,
                "expected": expected,
                "actual": None,
                "pass": False,
                "error": str(e),
            }
        mode = a.get("mode", "exact")
        # fail-closed：expected 缺失（None 是 Assertion 的「未设置」哨兵，
        # 非显式 null）时 exact 与 None 判等、contains 以 "None" 子串、
        # regex 以字面 None 为模式参与匹配，配置缺失被静默当作合法期望；
        # 空串 expected 加 contains/regex 同样假绿（空串 contains 恒真、
        # regex 恒匹配），与 body_contains / sse_event_matches 同口径拦截
        # （exact 空串是合法期望，不在拦截之列；拦截谓词统一走
        # _missing_expected，四处调用点口径单一来源）
        if _missing_expected(expected, mode):
            return {
                "type": "json_path",
                "path": path,
                "expected": expected,
                "actual": None,
                "pass": False,
                "error": "缺少 expected 字段",
            }
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
            pattern, regex_error = _compile_regex(str(expected))
            if pattern is not None:
                passed = bool(
                    pattern.search(str(actual if actual is not None else ""))
                )
            else:
                # 非法正则显式报错：与「内容确实不匹配」可区分，judge
                # 不把场景配置错误误归因为产品缺陷
                error = regex_error
        # 结果体积界：actual 指向大 JSON 子树（path 命中容器节点）时原样
        # 塞进结果 dict 会让报告体积失控，超长截断为 200 字符 snippet（口径
        # 对齐 body_contains 的 actual_snippet 上限；dashboard/judge 侧仅作
        # 证据展示，渲染本就走 JSON.stringify）；pass 判定已在上方完成，
        # 截断不影响结论
        shown_actual = actual
        if isinstance(shown_actual, str):
            shown_actual = shown_actual[:200]
        elif isinstance(shown_actual, (dict, list)):
            shown_actual = json.dumps(shown_actual, ensure_ascii=False)[:200]
        result = {
            "type": "json_path",
            "path": path,
            "expected": expected,
            "actual": shown_actual,
            "pass": passed,
        }
        if error is not None:
            result["error"] = error
        return result

    async def _assert_response_header(self, resp, a: dict) -> dict:
        """断言响应头存在且匹配（header 名大小写不敏感）。"""
        header = a.get("header", "")
        expected = a.get("expected")
        mode = a.get("mode", "exact")
        # fail-closed：header 缺失/空串（非字符串同样不静默 str() 归一）时
        # 下方大小写不敏感匹配必然 miss，最终落到「响应头 '' 不存在」——
        # 场景配置缺字段被误导为「产品没返回该头」，judge 会误归因为产品
        # 缺陷。口径对齐 json_path 的 path 预检（验收期必填表
        # ASSERTION_REQUIRED_FIELDS 是前置防线，此处兜住运行期自愈/绕过
        # 验收的调用路径）
        if not isinstance(header, str) or not header:
            return {
                "type": "response_header",
                "header": header,
                "expected": expected,
                "actual": None,
                "pass": False,
                "error": "缺少 header 字段",
            }
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
        elif _missing_expected(expected, mode):
            # fail-closed：缺 expected 时 contains 空串恒真、regex 空串恒匹配，
            # 只要头存在即假通过（exact 与空串比较则是确定性伪失败且不附
            # error，judge 会把配置缺失误归因为产品缺陷）；口径对齐
            # body_contains / sse_event_matches（exact 空串是合法期望——
            # 断言头为空值，不在拦截之列）
            error = "缺少 expected 字段"
        elif actual is not None:
            if mode == "exact":
                passed = str(actual).strip() == str(expected).strip()
            elif mode == "contains":
                # expected 一并 str 归一（数值/布尔形态不抛 TypeError）
                passed = str(expected) in str(actual)
            elif mode == "regex":
                pattern, regex_error = _compile_regex(str(expected))
                if pattern is not None:
                    passed = bool(pattern.search(str(actual)))
                else:
                    error = regex_error
        else:
            # 头不存在与值不匹配区分归因（与 json_path 缺失分支口径对齐），
            # judge 无须从 actual=None 自行推断
            error = f"响应头 '{header}' 不存在"
        result = {
            "type": "response_header",
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
        # fail-closed：缺 expected 时 contains 空串恒真、regex 空串恒匹配，
        # mode 缺省 contains 下会假绿；口径对齐 _assert_sse_event_matches
        # （exact 空串是合法期望——断言响应体为空，不在拦截之列）
        expected = a.get("expected")
        mode = a.get("mode", "contains")
        if _missing_expected(expected, mode):
            return {
                "type": "body_contains",
                "expected": expected,
                "mode": mode,
                "pass": False,
                "actual_snippet": "",
                "error": "缺少 expected 字段",
            }
        # 定向归因：SSE 捕获（{type: sse, events, duration}）无 body，经下方
        # `resp.get("body") or ""` 得空串后会按「响应体不包含期望文本」失败
        # （actual_snippet 为空），judge 无法看出是捕获类型不匹配；口径对齐
        # json_path / json_schema 的 SSE 分流，防误归因为产品缺陷
        if resp.get("type") == "sse":
            return {
                "type": "body_contains",
                "expected": expected,
                "mode": mode,
                "pass": False,
                "actual_snippet": "",
                "error": (
                    "body_contains 断言不支持 SSE 捕获（无响应体）；"
                    "事件内容断言请改用 sse_event_matches"
                ),
            }
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
            pattern, regex_error = _compile_regex(str(expected))
            if pattern is not None:
                passed = bool(pattern.search(str(body)))
            else:
                error = regex_error
        result = {
            "type": "body_contains",
            "expected": expected,
            "mode": mode,
            "pass": passed,
            "actual_snippet": str(body)[:200] if not passed and body else "",
            # 透出截断标记：body 证据在 capture 侧已按 64KB 截断（_truncate），
            # 截断点之后的期望文本匹配不到会产生假失败（json 侧已以「先解析
            # 后截断」修复同类问题，body 断言只能以标记提示兜底），judge 须
            # 能区分「内容不匹配」与「证据不完整」
            "body_truncated": bool(resp.get("truncated")),
        }
        if error is not None:
            result["error"] = error
        elif not passed and result["body_truncated"]:
            result["error"] = (
                "响应体超过 64KB 已截断，仅前 64KB 参与匹配，"
                "期望文本可能位于截断点之后；本失败不能单独作为产品缺陷证据"
            )
        return result

    async def _assert_json_schema(self, resp, a: dict) -> dict:
        """断言响应体 JSON 符合 schema（jsonschema 库；验收期已查依赖）。"""
        if not json_schema_available():
            return {
                "type": "json_schema",
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
                "pass": False,
                "error": (
                    f"schema 非法: 须为 JSON Schema 对象（dict），"
                    f"实际 {type(schema).__name__}"
                ),
            }
        payload = resp.get("json")
        if payload is None:
            if resp.get("type") == "sse":
                # 定向提示：SSE 捕获（{type: sse, events, duration}）无 JSON
                # 载荷属捕获类型不匹配，非「响应体非合法 JSON」（口径对齐
                # json_path 的 SSE 分流），防 judge 误归因
                error = (
                    "json_schema 断言不支持 SSE 捕获（无 JSON 载荷）；"
                    "事件内容断言请改用 sse_event_matches"
                )
            elif resp.get("json_parse_skipped"):
                # capture 标注透出：响应体超解析上限被跳过解析置 json=None，
                # 非「响应体非合法 JSON」
                error = f"{resp['json_parse_skipped']}，无法做 schema 校验"
            else:
                error = "响应体非合法 JSON，无法做 schema 校验"
            return {
                "type": "json_schema",
                "pass": False,
                "error": error,
            }
        try:
            jsonschema.validate(payload, schema)
            return {"type": "json_schema", "pass": True}
        except jsonschema.ValidationError as e:
            return {
                "type": "json_schema",
                "pass": False,
                "error": f"schema 校验失败: {e.message}（{e.json_path}）",
            }
        except jsonschema.SchemaError as e:
            # 运行期兜底（自愈/绕过验收的调用路径）补全：schema 本身写错
            # 属场景缺陷，与「响应不合 schema」须可区分
            return {
                "type": "json_schema",
                "pass": False,
                "error": f"schema 非法: {e.message}",
            }
        except Exception as e:
            # 终极兜底：schema 含不可解析 $ref 等校验器异常（具体类型随
            # jsonschema 版本而异，如 RefResolutionError）也不得漏成笼统
            # 「断言执行异常」，与上方 SchemaError 分支同口径归一
            return {
                "type": "json_schema",
                "pass": False,
                "error": f"schema 非法或校验器异常: {e}",
            }

    async def _assert_sse_event_matches(self, resp, a: dict) -> dict:
        """断言 SSE 窗口内存在与期望匹配的事件（data 字段）。"""
        raw_events = resp.get("events") or []
        # 配置错误可见化：events 含非 dict 元素时不再让 dict() 抛 TypeError
        # 被包成笼统「断言执行异常」（capture 由 mock/手写来源构造时可能出
        # 现），与本文件其余断言的定向归因口径对齐
        non_dict = [i for i, e in enumerate(raw_events) if not isinstance(e, dict)]
        if non_dict:
            return {
                "type": "sse_event_matches",
                "expected": a.get("expected", ""),
                "mode": a.get("mode", "contains"),
                "actual_hits": [],
                "hit_count": 0,
                "pass": False,
                "error": (
                    f"events 含非 dict 元素（第 {non_dict[0]} 个为 "
                    f"{type(raw_events[non_dict[0]]).__name__}，"
                    f"共 {len(non_dict)} 个），capture 结构非法"
                ),
            }
        events = [dict(e) for e in raw_events]
        expected = a.get("expected")
        mode = a.get("mode", "contains")
        # fail-closed：缺 expected（None 哨兵，与本文件 _assert_json_path 口径
        # 一致）时一律显式失败——contains 空串恒真、regex 空串恒匹配、exact
        # 空串会误命中窗口内的空/纯空白 data 事件（keep-alive 常见形态）；与
        # web 侧 text_match 缺参显式失败口径一致（显式设置的空串 exact 期望
        # 仍照常放行）（code-review item d6f5b0adcfc6）
        if _missing_expected(expected, mode):
            return {
                "type": "sse_event_matches",
                "expected": expected,
                "mode": mode,
                "actual_hits": [],
                "hit_count": 0,
                "pass": False,
                "error": "缺少 expected 字段",
            }
        # 配置错误可见化：与 run() 入口「未知断言类型」口径对齐（未知 mode 不再静默）
        error = None if mode in ("exact", "contains", "regex") else f"未知 mode: {mode}"
        # 非法正则进匹配前预检（口径对齐 web 侧 _assert_text_match）：逐事件
        # 静默吞 re.error 会与「无事件匹配」混淆、误归因为产品缺陷
        pattern = None
        if mode == "regex" and error is None:
            pattern, regex_error = _compile_regex(str(expected))
            if pattern is None:
                error = regex_error
        hits = []
        for ev in events:
            # 以 is not None 判空：or 会把 0/False 等 falsy 合法值折叠为 ""，
            # 导致 contains "0" 对 data=0 的事件漏匹配（口径对齐 _assert_json_path
            # contains 分支）
            data = str(v) if (v := ev.get("data")) is not None else ""
            if mode == "exact":
                matched = data.strip() == str(expected).strip()
            elif mode == "contains":
                matched = str(expected) in data
            elif mode == "regex":
                matched = pattern is not None and bool(pattern.search(data))
            else:
                matched = False
            if matched:
                hits.append(data)
        result = {
            "type": "sse_event_matches",
            "expected": expected,
            "mode": mode,
            "actual_hits": hits[:5],
            "hit_count": len(hits),
            "pass": len(hits) > 0,
        }
        # capture 截断标注透出（口径对齐 body_contains 的 body_truncated 专项
        # error）：事件数触顶/单事件 data 超 64KB 后证据不完整，期望内容可能
        # 位于截断点之后，judge 须能区分「事件内容不匹配」与「证据不完整」
        evidence_truncated = bool(resp.get("truncated") or resp.get("data_truncated"))
        if error is not None:
            result["error"] = error
        elif not result["pass"] and evidence_truncated:
            result["error"] = (
                "SSE 事件证据不完整（事件数触顶或单事件 data 超 64KB 已截断），"
                "期望内容可能位于截断点之后；本失败不能单独作为产品缺陷证据"
            )
        return result

    # ═══════════════════════════════════════════════════════════════
    # 第4层：启发式阈值（失败=warning，需上下文判定）
    # ═══════════════════════════════════════════════════════════════

    async def _assert_latency_under(self, resp, a: dict) -> dict:
        """断言响应延迟低于毫秒上限（启发式，慢环境不判产品缺陷）。"""
        expected = a.get("expected")
        actual = resp.get("latency_ms")
        # fail-closed：expected 缺失或非数字时不得让 int() 抛 TypeError 被
        # run() 包成笼统「断言执行异常」，judge 须能区分场景配置错误与产品
        # 缺陷（口径对齐 status_code 的 expected 校验）
        try:
            limit = int(expected)
        except (TypeError, ValueError):
            limit = None
        # fail-closed：actual（resp.get("latency_ms")）为字符串等非数字时
        # actual < limit 抛 TypeError 被 run() 包成笼统「断言执行异常」，
        # 恰好是本文件处处避免的误归因形态（mock/手写 capture 可能出现，
        # 防御假设同 sse_event_matches 对 events 非 dict 的预检）；bool 是
        # int 子类须一并排除
        actual_numeric = isinstance(actual, (int, float)) and not isinstance(
            actual, bool
        )
        passed = limit is not None and actual_numeric and actual < limit
        result = {
            "type": "latency_under",
            "expected": expected,
            "actual": actual,
            "pass": passed,
        }
        if expected is None:
            result["error"] = (
                "latency_under 缺少数字型 expected，无法与延迟上限对比（fail-closed）"
            )
        elif limit is None:
            result["error"] = (
                f"latency_under 的 expected 非数字（毫秒），无法与延迟上限对比: {expected!r}"
            )
        elif actual is None:
            # 无载荷定向归因：SSE 捕获（{type: sse, events, duration}）无
            # latency_ms 采样，静默 pass=False 会逼 judge 自行推断捕获类型
            # 不匹配（口径对齐 json_path 的 SSE 定向提示）
            if resp.get("type") == "sse":
                result["error"] = "latency_under 断言不支持 SSE 捕获（无 latency_ms 延迟采样）"
            else:
                result["error"] = "响应捕获无 latency_ms 延迟采样，无法与延迟上限对比"
        elif not actual_numeric:
            # 定向归因：捕获到的 latency_ms 非数字（与 expected 非数字分支
            # 同结构），judge 须能区分「响应捕获字段畸形」与真实延迟表现
            result["error"] = (
                f"响应捕获 latency_ms 非数字（毫秒），无法与延迟上限对比: {actual!r}"
            )
        return result
