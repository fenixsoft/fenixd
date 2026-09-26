"""
api_runner.py — ApiRunner：httpx 驱动的 API 场景执行（spec verify-runner-engine PR2）

步骤（限 api 词表）：
  - ``http_request``：method/url/headers（值支持 {env:VAR} 插值）/body+body_type/
    timeout/as。URL origin 由框架统一改写（BASE_URL 注入铁律扩展，路径保留）。
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

        async with httpx.AsyncClient() as client:
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
        headers = {
            k: _interpolate_env(str(v), self.config_env())
            for k, v in (step.get("headers") or {}).items()
        }
        body = step.get("body", "")
        body_type = str(step.get("body_type") or "").lower()
        try:
            timeout = float(step.get("timeout") or 30.0)
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
            resp = await client.request(
                method,
                url,
                headers=headers,
                content=content,
                json=json_body,
                timeout=timeout,
                follow_redirects=True,
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
        except httpx.TimeoutException as e:
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error": f"请求超时（{timeout}s）: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "action": "http_request",
                "method": method,
                "url": url,
                "error": f"请求异常: {type(e).__name__}: {e}",
            }

        # 证据截断只作用于证据字段（body/truncated）：JSON 解析必须用完整
        # 响应体，先解析后截断。若先截断再 json.loads，>64KB 的合法 JSON 会
        # 被截成非法文本 → resp_json=None → json_schema/json_path 断言必然
        # 假失败（harness 缺陷，非产品缺陷、非场景缺陷）。
        resp_text = resp.text or ""
        try:
            resp_json = json.loads(resp_text) if resp_text.strip() else None
        except json.JSONDecodeError:
            resp_json = None
        resp_body, truncated = _truncate(resp_text)

        capture = {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp_body,
            "json": resp_json,
            "latency_ms": latency_ms,
            "truncated": truncated,
        }
        name = step.get("as") or ""
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
            + ("（响应体已截断 64KB）" if truncated else ""),
        }

    async def _execute_sse_connect(self, client, step: dict, captures: dict) -> dict:
        """sse_connect：流式收集窗口内事件列表（SSE 步骤，fast-follow 可降级）。"""
        import httpx

        url = rewrite_origin(str(step.get("url") or ""), self.base_url)
        try:
            duration = float(step.get("duration") or 5.0)
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
                event: dict = {"data": "", "event": ""}
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
                        event["data"] += v + "\n"
                    elif line.startswith("event:"):
                        event["event"] = line[6:].strip()
                    elif line == "":
                        if event["data"].strip():
                            events.append(
                                {
                                    "data": event["data"].rstrip("\n"),
                                    "event": event["event"],
                                }
                            )
                        event = {"data": "", "event": ""}
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
        except Exception as e:
            return {
                "success": False,
                "action": "sse_connect",
                "url": url,
                "error": f"SSE 收集异常: {type(e).__name__}: {e}",
            }

        capture = {"type": "sse", "events": events, "duration": duration}
        name = step.get("as") or ""
        if name:
            captures[name] = capture
        captures["_latest"] = capture

        return {
            "success": True,
            "action": "sse_connect",
            "url": url,
            "events": len(events),
            "detail": f"SSE 收集 {len(events)} 个事件（{duration}s 窗口）"
            + (f"（达到收集上限 {_SSE_MAX_EVENTS}，后续事件已截断）" if truncated else ""),
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
