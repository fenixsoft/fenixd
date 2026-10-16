"""
api_runner.py — ApiRunner：httpx 驱动的 API 场景执行（spec verify-runner-engine PR2）

步骤（限 api 词表）：
  - ``http_request``：method/url/headers/body+body_type/timeout/as。仅 headers
    值支持 {env:VAR} 插值（url 不插值，原样发送）；URL origin 由框架统一
    改写（BASE_URL 注入铁律扩展，路径保留）。
  - ``sse_connect``：url/duration（收集窗口秒数）/as。流式收集窗口内事件列表。

响应捕获：步骤 ``as`` 命名、断言 ``response`` 字段引用（缺省=最近一次），
支撑多请求流（create→get→delete）。每个 http_request 捕获
``{status, headers, body, json, latency_ms}``；sse_connect 捕获
``{type: "sse", events, duration}``。证据 64KB 截断纪律与 CLI 同源。

连接失败类（httpx.ConnectError 等）＝环境候选：不判产品缺陷，交由引擎
环境门对契约 base_url 执行就绪探针、探针确认失联后降级 blocked-env。

httpx 依赖：setup 时检查（缺失=验证环境错误，引擎不判 bug-found）。
"""

import asyncio
import json
import time
from urllib.parse import urlparse

from ._evidence import _EVIDENCE_LIMIT, _truncate, _interpolate_env  # 共享证据工具（符号出口保持）
from .runner import VerifyRunner, register_runner, determine_scenario_status
from .api_assertions import ApiAssertionRunner, json_schema_available
from .env_gate import probe_http_health
from .scenarios import validate_scenario

_SSE_MAX_EVENTS = 100  # sse_connect 单窗口事件收集上限（触顶截断并在 detail 标注）
# 响应体 JSON 解析体积上限（与 evidence 侧 64KB 截断纪律同旨）：异常端点返回
# 超大响应时 resp.text 与解析对象树会同时驻留内存，超限跳过解析置 resp_json=None
_JSON_PARSE_LIMIT = 1024 * 1024
# 响应体读入硬上限（读入侧，独立于解析侧 _JSON_PARSE_LIMIT 与证据侧 64KB 截断）：
# http_request 按块累积、触顶即停，防异常端点数百 MB 级响应整体驻留内存放大 OOM 风险
_RESPONSE_READ_LIMIT = 8 * 1024 * 1024
# 响应头值脱敏名单（键保留，存在性判断不受影响）：Set-Cookie 等携带会话
# 令牌的头原样入证据会随证据长期留存（judge 上下文与落盘），值遮蔽即可
_EVIDENCE_REDACT_HEADERS = frozenset({"set-cookie", "set-cookie2"})


def rewrite_origin(url: str, base_url: str) -> str:
    """URL origin 全量改写（路径保留）——与 navigate 同规则。

    无实例形态（base_url 空）为无害空操作，返回原 URL。
    """
    if not base_url or not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return url
    suffix = parsed.path
    if parsed.query:
        suffix += "?" + parsed.query
    if parsed.fragment:
        suffix += "#" + parsed.fragment
    return base_url.rstrip("/") + suffix


@register_runner
class ApiRunner(VerifyRunner):
    """httpx 驱动的 API Runner（每场景独立 client 隔离 cookie）。"""

    kind = "api"

    def __init__(self, spec_name, project_root=None, logger=None, config: dict = None, **kwargs):
        super().__init__(spec_name, project_root, logger, config, **kwargs)
        # 契约统一供给的实例 base_url（引擎注入；http_request/sse_connect
        # URL origin 全量改写依据）。无实例形态为空字符串（无害空操作）。
        self.base_url = ""
        self.asserter = ApiAssertionRunner()

    # ── 场景验收 ───────────────────────────────────────────────

    def validate(self, scenario) -> list[str]:
        """api 词表校验 + jsonschema 依赖验收（缺失=报错打回，不静默跳过）。"""
        errors = validate_scenario(scenario)
        if errors:
            return errors
        # as 命名保留键验收（code-review item 063aa5e8ad24）：'_latest' 是
        # 框架保留键（断言缺省引用最近一次捕获）。步骤内检查在请求已完整
        # 执行后才触发（http_request 在响应读取完毕后、sse_connect 在收集
        # 窗口结束后），POST/DELETE 等副作用请求已真实打到实例而捕获被整体
        # 丢弃，可能污染同一实例上后续场景的执行前提——前移到验收期在发送
        # 前拒绝，步骤内两处检查保留为兜底。
        for i, step in enumerate(scenario.steps):
            if step.action in ("http_request", "sse_connect") and step.as_ == "_latest":
                errors.append(
                    f"场景'{scenario.id}'步骤{i}: "
                    f"as 命名 '_latest' 是框架保留键，请改用其他名称"
                )
        if (
            any(a.type == "json_schema" for a in scenario.assertions)
            and not json_schema_available()
        ):
            errors.append(
                f"场景'{scenario.id}'包含 json_schema 断言但 jsonschema 库不可用"
                f"——请安装（pip3 install jsonschema）后重试，不静默跳过"
            )
        return errors

    # ── 生命周期 ───────────────────────────────────────────────

    async def setup(self):
        """httpx 依赖检查（缺失=验证环境错误，引擎不判 bug-found）。"""
        try:
            import httpx  # noqa: F401
        except ImportError as e:
            raise RuntimeError(f"ApiRunner 需要 httpx 库（pip3 install httpx）: {e}") from e

    async def teardown(self):
        # client 按场景独立创建/关闭（execute 内 async with），无共享连接池
        pass

    # ── 场景执行 ───────────────────────────────────────────────

    async def execute(self, scenario) -> dict:
        """执行单个 api 场景：http_request/sse_connect 步骤 + API 断言。

        每场景独立 httpx.AsyncClient（隔离 cookie）；步骤 as 命名响应捕获；
        断言经 response 字段引用命名捕获（缺省最近一次）。
        """
        import httpx

        captures: dict = {}
        step_results: list[dict] = []
        steps_failed = False

        # trust_env=False：实例流量直连，防止进程携带的 HTTP(S)_PROXY 等代理
        # 环境变量把打向本机实例的请求路由进代理（BASE_URL 注入铁律：
        # 打新鲜实例）——httpx 缺省 trust_env=True 会读取这些变量。
        async with httpx.AsyncClient(trust_env=False) as client:
            for i, step in enumerate(scenario.steps):
                step_dict = step.to_dict()
                result = await self._execute_step(client, step_dict, captures)
                step_results.append(result)
                if not result.get("success"):
                    # 步骤失败即停止后续步骤，且跳过断言执行（同 web 语义：
                    # 断言「根本没进行」，避免对残余状态产生噪声归因）。
                    steps_failed = True
                    break

        assertion_results: list[dict] = []
        if not steps_failed:
            assertion_defs = [a.to_dict() for a in scenario.assertions]
            assertion_results = await self.asserter.run(captures, assertion_defs)

        status = determine_scenario_status(step_results, assertion_results, [])

        return {
            "scenario_id": scenario.id,
            "description": scenario.description,
            "kind": scenario.kind,
            "status": status,
            "step_results": step_results,
            "assertion_results": assertion_results,
            "visual_results": [],
            "screenshots": [],
        }

    async def _execute_step(self, client, step: dict, captures: dict) -> dict:
        """执行单个 api 步骤（http_request/sse_connect）。"""
        action = step.get("action")
        if action == "http_request":
            return await self._execute_http_request(client, step, captures)
        if action == "sse_connect":
            return await self._execute_sse_connect(client, step, captures)
        return {
            "success": False,
            "action": action,
            "error": f"api 词表不支持的操作: {action}",
        }

    async def _execute_http_request(self, client, step: dict, captures: dict) -> dict:
        """http_request：构建 httpx 请求并捕获命名响应。"""
        import httpx

        method = str(step.get("method") or "GET").upper()
        url = rewrite_origin(str(step.get("url") or ""), self.base_url)
        raw_headers = step.get("headers")
        if raw_headers is not None and not isinstance(raw_headers, dict):
            # 非法 headers（列表/字符串等非对象形态）调 .items() 会抛
            # AttributeError 穿出令整个场景 run 异常收场——入口归一为本步骤
            # 结构化失败，与 timeout/body 分支同款防御口径。
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error": f"headers 须为对象（键值映射）: {type(raw_headers).__name__}",
            }
        for k, v in (raw_headers or {}).items():
            if isinstance(v, (dict, list)):
                # 容器形态头值（YAML/JSON 均可自然写出）经下方 str() 归一会
                # 以 Python repr 形态（如 "['a', 'b']"）静默作为头值发送，
                # 作者意图与实际请求悄然背离，失败被误归因为产品行为——与
                # 非 dict headers/body 分支同款，归一为本步骤结构化失败
                # （数字/布尔标量的 str() 归一保留）。
                return {
                    "success": False,
                    "action": "http_request",
                    "method": method,
                    "url": url,
                    "error": f"头值须为标量（容器形态请写成字符串）: headers[{k!r}] 为 {type(v).__name__}",
                }
        headers = {
            # 键同值侧 str() 归一（YAML/JSON 场景可写出数字键）：后续
            # body_type=json 且 body 为 null 的分支会对键调 .lower()，非字
            # 符串键即 AttributeError 穿出步骤级结构化失败。
            str(k): _interpolate_env(str(v), self.config_env())
            for k, v in (raw_headers or {}).items()
        }
        body = step.get("body", "")
        body_type = str(step.get("body_type") or "").lower()
        if body_type and body_type not in ("json", "text"):
            # 未知 body_type（词表仅 json/text）可见化为本步骤结构化失败：
            # 静默按原文发送会让作者意图（如按 JSON 发送）与实际行为悄然
            # 背离，失败时被误归因为产品行为不符——与未知 action、未知
            # 断言 mode 的 fail-closed 口径对齐（值已在上方归一小写）。
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error": f"未知 body_type: {step.get('body_type')!r}（词表仅支持 json/text）",
            }
        try:
            # 区分「键缺失」与「显式 0」：or 兜底会把显式 0（立即超时）静默
            # 改写成缺省 30s；缺省仅在键缺失时生效
            _raw_timeout = step.get("timeout")
            timeout = float(30.0 if _raw_timeout is None else _raw_timeout)
        except (TypeError, ValueError) as e:
            # 非法 timeout（非数字字符串/结构化值）归一为本步骤结构化失败，
            # 而非 ValueError 穿出令整个场景 run 异常中断。
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error": f"timeout 须为数字（秒）: {step.get('timeout')!r} ({e})",
            }
        if body and not isinstance(body, str):
            # 结构化 body（dict/list）进 json.loads 会抛 TypeError（仅捕获
            # JSONDecodeError），未捕获即整个场景 run 异常收场——入口归一为
            # 本步骤结构化失败。
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error": f"body 须为字符串（结构化对象请写成 JSON 文本）: {type(body).__name__}",
            }

        content = None
        json_body = None
        sniff_fallback_text = False
        if body:
            if body_type == "json":
                try:
                    json_body = json.loads(body)
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "action": "http_request",
                        "method": method,
                        "url": url,
                        "error": f"body 非合法 JSON: {body[:100]}",
                    }
                if json_body is None:
                    # JSON 字面量 null（code-review item 4825b023e7ac）：解析结果
                    # None 与「未提供 json 参数」在 httpx（json 参数按 is not None
                    # 判定）下不可区分，直接走 json= 会把请求体静默丢成空 body——
                    # 作者意图（发字面量 null）与实际行为悄然背离，失败被误归因
                    # 为产品行为不符。降级按 content 原文发送（json.dumps(None)
                    # 同为 "null"，请求体字节等价），并补 application/json 头，
                    # 与其余 JSON 值走 json= 路径的请求头口径保持一致。
                    content = body
                    if not any(k.lower() == "content-type" for k in headers):
                        headers["Content-Type"] = "application/json"
            elif not body_type and str(body).lstrip().startswith(("{", "[")):
                # 未声明 body_type 时的首字符嗅探：解析失败不再判整步失败，
                # 降级按 content 原文发送——body 以 {/[ 开头不代表一定是 JSON
                # （如文本型载荷 `{a: 1}`、日志样张），作者本意可能就是发原文；
                # 如需强制 JSON 语义应显式声明 body_type: json。嗅探成功与
                # 显式声明的路径行为均不变。
                try:
                    json_body = json.loads(body)
                except json.JSONDecodeError:
                    content = body
                    sniff_fallback_text = True
            else:
                content = body

        try:
            t0 = time.monotonic()
            async with client.stream(
                method,
                url,
                headers=headers,
                content=content,
                json=json_body,
                timeout=timeout,
                follow_redirects=True,
            ) as resp:
                # 读入侧硬上限：按块累积、触顶即停（提前退出由上下文关闭连接），
                # 防超大响应整体驻留内存——解析/证据侧上限只约束后续消费，不约束
                # 读入本身。触顶置 read_truncated 标注供 judge 归因。
                chunks = []
                read_bytes = 0
                read_truncated = False
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    read_bytes += len(chunk)
                    if read_bytes >= _RESPONSE_READ_LIMIT:
                        read_truncated = True
                        break
                # charset_encoding 为 httpx 0.28 引入（旧版属性名为 encoding），
                # setup 只校验可导入不校验版本，兼容两代属性名取值，旧版环境
                # 不再 AttributeError 致全量 http_request 步骤失败且归因失真
                resp_encoding = (
                    getattr(resp, "charset_encoding", None)
                    or getattr(resp, "encoding", None)
                    or "utf-8"
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
        except httpx.ConnectError as e:
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error_type": "connection_failed",
                "error": f"连接失败（实例失联或不可达，环境候选）: {e}",
            }
        except httpx.ConnectTimeout as e:
            # 连接阶段超时继承自 TimeoutException 而非 ConnectError（典型：
            # 主机宕机但防火墙丢包而非立即拒绝），须在通用超时分支之前细分，
            # 否则实例失联场景漏标环境候选。
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error_type": "connection_failed",
                "error": f"连接超时（连接阶段，实例失联或不可达，环境候选）: {e}",
            }
        except (httpx.ReadError, httpx.RemoteProtocolError) as e:
            # 响应中途断连（aiter_bytes 读流阶段服务端断开、响应不完整）：
            # 与建连类失败同属实例失联形态（典型：实例进程在响应中途崩溃/
            # 重启），复用 error_type=connection_failed 进入环境候选分流
            # （env_gate 只认该既有值，新增独立值无消费方），交由环境门
            # 就绪探针与 judge 复核归因——mid-response 断连语义两可，此处
            # 只补机械分流标记，不下产品/环境分类结论。
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error_type": "connection_failed",
                "error": f"响应中途断连（连接失败类，环境候选，待环境探针复核）: {e}",
            }
        except httpx.TimeoutException as e:
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                # 读超时按场景失败处理（与连接类失败的环境候选分流不同），
                # 但补 error_type 使下游机械分流无须匹配中文文案
                "error_type": "request_timeout",
                "error": f"请求超时（{timeout}s）: {e}",
            }
        except Exception as e:
            # 请求头值经 {env:VAR} 插值后可能携带敏感令牌，非法头值触发的
            # h11 LocalProtocolError 等异常文案会携带头值原文（如 Illegal
            # header value b'...'），原样入证据即穿透请求侧脱敏纪律（响应
            # Set-Cookie 已按 _EVIDENCE_REDACT_HEADERS 遮蔽）——落证据前先
            # 把本步骤出现过的请求头值替换为占位符。
            error_text = f"请求异常: {type(e).__name__}: {e}"
            # [fenix-ignore:7069dc3f5433] 全量 replace 是防令牌穿透证据的安全优先取舍：阈值收窄修不了清单自举示例（application/json/keep-alive 均达长度阈值），只会引入短令牌漏遮蔽的安全回归
            for header_value in headers.values():
                if header_value:
                    error_text = error_text.replace(header_value, "<已脱敏>")
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error": error_text,
            }

        # 证据截断只作用于证据字段（body/truncated）：JSON 解析必须用完整
        # 响应体，先解析后截断。若先截断再 json.loads，>64KB 的合法 JSON 会
        # 被截成非法文本 → resp_json=None → json_schema/json_path 断言必然
        # 假失败（harness 缺陷，非产品缺陷、非场景缺陷）。
        raw_body = b"".join(chunks)
        try:
            resp_text = raw_body.decode(resp_encoding, errors="replace")
        except LookupError:
            # 响应头声明了未知字符集时按 UTF-8 宽松解码兜底
            resp_text = raw_body.decode("utf-8", errors="replace")
        # JSON 解析必须用完整响应体（防截断破坏合法 JSON），但解析侧设体积
        # 上限：超限响应跳过解析置 resp_json=None（json_path/json_schema 断言
        # 按「路径不存在/非 JSON」口径失败），capture 标注便于 judge 归因。
        # 体积按 UTF-8 字节口径计量（与 _truncate 同口径）：len(str) 是字符数，
        # 中文等多字节响应的实际字节数可达字符数倍数，按字符比较会低估内存
        # 占用，且未解析标注里的数字与真实体积不符。
        resp_text_bytes = len(resp_text.encode("utf-8", errors="replace"))
        json_parse_skipped = resp_text_bytes > _JSON_PARSE_LIMIT
        if json_parse_skipped:
            resp_json = None
        else:
            try:
                resp_json = json.loads(resp_text) if resp_text.strip() else None
            except json.JSONDecodeError:
                resp_json = None
        resp_body, truncated = _truncate(resp_text)

        capture = {
            "status": resp.status_code,
            # 脱敏名单内的头只留键名、值遮蔽（长度保留供归因），其余头原样入证据
            "headers": {
                k: (
                    f"<已脱敏:{len(v)} 字符>" if k.lower() in _EVIDENCE_REDACT_HEADERS else v
                )
                for k, v in resp.headers.items()
            },
            "body": resp_body,
            "json": resp_json,
            "latency_ms": latency_ms,
            "truncated": truncated,
        }
        if json_parse_skipped:
            capture["json_parse_skipped"] = (
                f"响应体超大未解析（{resp_text_bytes} 字节 > 上限 {_JSON_PARSE_LIMIT}）"
            )
        if read_truncated:
            capture["read_truncated"] = (
                f"响应体超过读入上限（{_RESPONSE_READ_LIMIT} 字节），仅保留前缀参与解析与证据"
            )
        name = step.get("as") or ""
        if name == "_latest":
            # `_latest` 是框架保留键（断言缺省引用最近一次捕获）：场景 as 命名
            # 撞上会与后续未命名步骤的 captures["_latest"] 同槽互相覆盖，断言
            # 缺省引用读到非预期响应且无提示——与 cli_runner 同款结构化失败
            # （code-review item f247bc4a9f97）
            return {
                "success": False,
                "action": "http_request",
                "url": url,
                "error": "as 命名 '_latest' 是框架保留键，请改用其他名称",
            }
        if name:
            captures[name] = capture
        captures["_latest"] = capture

        return {
            "success": True,
            "action": "http_request",
            "method": method,
            "url": url,
            "status": resp.status_code,
            "latency_ms": latency_ms,
            "detail": f"{method} {url} → {resp.status_code}"
            + ("（JSON 嗅探失败已按原文发送）" if sniff_fallback_text else "")
            + ("（响应体已截断 64KB）" if truncated else "")
            + ("（响应体超大未解析）" if json_parse_skipped else "")
            + ("（响应体超读入上限已截断）" if read_truncated else ""),
        }

    async def _execute_sse_connect(self, client, step: dict, captures: dict) -> dict:
        """sse_connect：流式收集窗口内事件列表（SSE 步骤，fast-follow 可降级）。"""
        import httpx

        url = rewrite_origin(str(step.get("url") or ""), self.base_url)
        try:
            # 区分「键缺失」与「显式 0」：or 兜底会把显式 0（零窗口）静默
            # 改写成缺省 5s；缺省仅在键缺失时生效
            _raw_duration = step.get("duration")
            duration = float(5.0 if _raw_duration is None else _raw_duration)
        except (TypeError, ValueError) as e:
            # 非法 duration（非数字字符串/结构化值）归一为本步骤结构化失败，
            # 与 http_request 的 timeout 防御口径对齐，而非 ValueError 穿出
            # 令整个场景 run 异常中断。
            return {
                "success": False,
                "action": "sse_connect",
                "url": url,
                "error": f"duration 须为数字（秒）: {step.get('duration')!r} ({e})",
            }
        events: list[dict] = []
        truncated = False
        data_truncated = False
        # 缓冲初始化置于 try 外：ReadTimeout 可能在 stream 建连读响应头阶段
        # 抛出并按「窗口正常结束」返回，收尾 flush 仍需访问缓冲。
        event: dict = {"data": "", "event": ""}
        data_bytes = 0  # 当前事件 data 累计 UTF-8 字节（与 _truncate 同口径）

        try:
            async with client.stream(
                "GET",
                url,
                timeout=httpx.Timeout(
                    connect=5.0, read=max(10.0, duration + 10.0), write=5.0, pool=5.0
                ),
                follow_redirects=True,
            ) as resp:
                if resp.status_code >= 400:
                    return {
                        "success": False,
                        "action": "sse_connect",
                        "url": url,
                        "error": f"SSE 连接失败: HTTP {resp.status_code}",
                    }
                deadline = time.monotonic() + duration
                async for line in resp.aiter_lines():
                    if time.monotonic() > deadline:
                        break
                    line = (line or "").rstrip("\r")
                    if line.startswith("data:"):
                        # SSE 规范：只剥除冒号后的单个前导空格，保留载荷
                        # 内部与尾部空白，避免多行 data 保真度受损。
                        v = line[5:]
                        if v.startswith(" "):
                            v = v[1:]
                        # 单事件 data 64KB 截断纪律（与 http_request body 同源
                        # _truncate）：拼接前按「已累计 + 本行字节数」预判，超限
                        # 只取停在边界内的行前缀，防高速流式端点把单条事件推到
                        # 任意大、在本步骤内存里全量驻留到分帧/收尾才被裁剪
                        # （读入侧触顶即停，对齐 http_request 的
                        # _RESPONSE_READ_LIMIT 读入硬上限纪律）。
                        line_bytes = len((v + "\n").encode("utf-8", errors="replace"))
                        if data_bytes + line_bytes <= _EVIDENCE_LIMIT:
                            data_bytes += line_bytes
                            event["data"] += v + "\n"
                        elif data_bytes >= _EVIDENCE_LIMIT:
                            # 触顶后同一事件的后续 data 行被丢弃：此处显式置标。
                            # 收尾 _truncate 复判的是去掉尾部换行后的保留前缀，
                            # 恰停在边界内（如一行 65536 字节后接续行）会判不超
                            # 限而漏标，judge 拿到外观完整的截断事件做归因。
                            data_truncated = True
                        else:
                            # 首次触顶：截取本行 UTF-8 前缀使累计恰停在边界内
                            # （errors="ignore" 丢弃被切半的多字节尾部，不产生
                            # 替换字符挤占预算），本行剩余部分连同后续 data 行
                            # 一并丢弃并置标。
                            data_truncated = True
                            allowed = _EVIDENCE_LIMIT - data_bytes - 1  # 留尾部换行
                            if allowed > 0:
                                prefix = v.encode("utf-8", errors="replace")[
                                    :allowed
                                ].decode("utf-8", errors="ignore")
                                data_bytes += len(
                                    (prefix + "\n").encode("utf-8", errors="replace")
                                )
                                event["data"] += prefix + "\n"
                    elif line.startswith("event:"):
                        event["event"] = line[6:].strip()
                    elif line == "":
                        # 仅携带 event 名而无 data 的事件（如纯心跳 event 行）
                        # 也是合法 SSE 事件：按空 data 入列，否则 sse_event_count/
                        # sse_event_matches 会少计而假失败；data 与 event 名皆空
                        # 的空行/连续空行不产生幻影事件。
                        if event["data"].strip() or event["event"]:
                            data, over = _truncate(event["data"].rstrip("\n"))
                            if over:
                                data_truncated = True
                            events.append(
                                {
                                    "data": data,
                                    "event": event["event"],
                                }
                            )
                        event = {"data": "", "event": ""}
                        data_bytes = 0
                        # [fenix-ignore:02355951014f] 触顶 break 前缓冲已在上方重置为空，收尾 flush 条件不成立不会二次入列，events 恒 ≤ _SSE_MAX_EVENTS，不存在 101 个事件的路径
                        if len(events) >= _SSE_MAX_EVENTS:
                            truncated = True
                            break
        except httpx.ConnectError as e:
            return {
                "success": False,
                "action": "sse_connect",
                "url": url,
                "error_type": "connection_failed",
                "error": f"连接失败（实例失联或不可达，环境候选）: {e}",
            }
        except httpx.ConnectTimeout as e:
            # 连接阶段超时继承自 TimeoutException 而非 ConnectError：与
            # ConnectError 同为实例失联环境候选，勿落入通用异常分支。
            return {
                "success": False,
                "action": "sse_connect",
                "url": url,
                "error_type": "connection_failed",
                "error": f"连接超时（连接阶段，实例失联或不可达，环境候选）: {e}",
            }
        except httpx.ReadTimeout:
            # 窗口内服务端完全不发数据（无心跳/注释行）时，aiter_lines 阻塞至
            # read 超时；read = max(10, duration+10) 恒大于窗口 duration，超时
            # 触发时截止时刻必然已过：按窗口正常结束处理，保留已收集事件返回
            # 成功（0 事件交由断言判定），不误判「SSE 收集异常」。
            pass
        except (httpx.ReadError, httpx.RemoteProtocolError) as e:
            # 响应中途断连（aiter_lines 读流阶段服务端断开、流不完整）：与
            # http_request 同形态口径（code-review item e5dbbae31e02）——
            # 典型为实例进程响应途中崩溃/重启，属实例失联形态，补
            # error_type=connection_failed 进入环境候选分流（env_gate 只认
            # 该既有值），不落入通用异常分支被误归因为产品/场景失败；
            # 已收集事件随失败结果保留供归因。
            return {
                "success": False,
                "action": "sse_connect",
                "url": url,
                "error_type": "connection_failed",
                "events": events,
                "error": f"响应中途断连（连接失败类，环境候选，待环境探针复核）: {e}",
            }
        except Exception as e:
            # 已收集事件随失败结果保留供归因（与 ReadError/RemoteProtocolError
            # 分支同口径）：窗口中途非连接类异常同样已有局部事件证据。
            return {
                "success": False,
                "action": "sse_connect",
                "url": url,
                "events": events,
                "error": f"SSE 收集异常: {type(e).__name__}: {e}",
            }

        # 收尾 flush：deadline 截止 break 与流 EOF 都不会走到空行分帧分支，
        # 缓冲中未以空行终结的最后一个事件若不在此落 events 会被静默丢弃，
        # sse_event_count/sse_event_matches 等事件类断言据此假失败。窗口
        # 截止/EOF 后仍有 data 或仅有 event 名的缓冲按空行分帧同口径入列。
        if event["data"].strip() or event["event"]:
            data, over = _truncate(event["data"].rstrip("\n"))
            if over:
                data_truncated = True
            events.append({"data": data, "event": event["event"]})

        # 截断标注透出（口径对齐 http_request capture 的 truncated）：单事件
        # data 超 64KB 或事件数触顶后，被截断的事件证据外观完整，若只拼进步
        # 骤 detail 文案，sse_event_matches 等内容断言失败时 judge 无法区分
        # 「事件内容不匹配」与「证据不完整」。
        capture = {
            "type": "sse",
            "events": events,
            "duration": duration,
            "truncated": truncated,
            "data_truncated": data_truncated,
        }
        name = step.get("as") or ""
        if name == "_latest":
            # `_latest` 是框架保留键：场景 as 命名撞上会与未命名步骤的
            # captures["_latest"] 同槽互相覆盖——与 cli_runner 同款结构化失败
            # （code-review item f247bc4a9f97）
            return {
                "success": False,
                "action": "sse_connect",
                "url": url,
                "error": "as 命名 '_latest' 是框架保留键，请改用其他名称",
            }
        if name:
            captures[name] = capture
        captures["_latest"] = capture

        return {
            "success": True,
            "action": "sse_connect",
            "url": url,
            "events": len(events),
            "detail": f"SSE 收集 {len(events)} 个事件（{duration}s 窗口）"
            + (f"（达到收集上限 {_SSE_MAX_EVENTS}，后续事件已截断）" if truncated else "")
            + ("（单事件 data 超 64KB 已截断）" if data_truncated else ""),
        }

    def config_env(self) -> dict:
        """{env:VAR} 插值的取值环境：本进程环境（框架注入变量经 os.environ）。"""
        import os

        return dict(os.environ)

    # ── 环境探针（环境门委托）─────────────────────────────────

    async def probe_env(self, candidates: list[dict]) -> dict:
        """契约就绪探针：对 base_url 做 HTTP 连通探测。

        连接失败类候选降级 blocked-env 的依据。无实例形态（base_url 空）
        无法探测，保守判健康（避免误降级真缺陷）。
        """
        if not self.base_url:
            return {"healthy": True, "detail": "api 无实例形态，跳过探针"}
        # 线程池执行：probe_http_health 为同步阻塞探测（最坏 3×2s），避免卡死事件循环
        healthy = await asyncio.to_thread(probe_http_health, self.base_url, timeout=2.0)
        return {
            "healthy": healthy,
            "detail": f"契约就绪探针 {self.base_url}: " f"{'连通' if healthy else '失联'}",
        }
