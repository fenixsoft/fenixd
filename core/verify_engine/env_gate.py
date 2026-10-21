"""
env_gate.py — 验证环境健全性门（verify-environment-sanity-gate）。

问题：mock_api 步骤在验证环境中斩断真实推送（SSE）时，页面 DOM 永不更新，
后续断言（Locator.wait_for / 引擎 wait 步骤）全部进入纯等待超时 → 整批场景
被误判为产品缺陷 → 每个假阴性都派生 fix 子 SPEC 空转完整实现+验证周期。

本模块实现「场景结算后的统一后置分类」（design D1，纯函数，可单测）：
  候选 degrade = 步骤序列含 mock_api 且失败项属于纯等待超时（无业务信息）
  降级 blocked-env = 候选 且 环境探针确认实例失联/推流中断
  探针健康 = 维持 fail（此时确属真缺陷或慢场景）

三条件同时成立才降级（design Risks 防误伤），任一不满足保持原判定。
例外（B1 白屏候选）：step_results 含显式 ``first_frame_ok is False`` 时，
白屏属客户端渲染维度证据，finalize 不依赖探针直接降级 blocked-env
（见 is_blank_render_candidate）。
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

_logger = logging.getLogger("fenixd.verify.env_gate")

# 直连 opener（code-review item 58da54c017a9，对齐 api_runner 的 trust_env=False
# 铁律）：urlopen 缺省按 HTTP(S)_PROXY/ALL_PROXY 环境变量构建代理路由，daemon
# 进程携带代理变量时探针请求会被路由进代理——代理不可达或拒绝回源本机实例即抛
# URLError 判失联，finalize_scenario_status 随即把真实产品缺陷洗白为
# blocked-env。显式空 ProxyHandler 强制直连被测实例；构建零 I/O，模块级一次。
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 纯等待超时特征指纹（Playwright / 引擎 wait 步骤）。裸「超时」「exceeded」
# 已收窄（code-review 2084e503bd60）：业务型超时文案（「请求后端接口超时」
# 「deadline exceeded」）不得混入候选。引擎 wait 步骤封装统一带「wait 超时」
# 前缀；Playwright 超时文案为「Timeout ...ms exceeded.」形态，由 "timeout "
# 前缀覆盖。
# [fenix-ignore:71beefa96751] 文案指纹耦合已在上文显式注明：Playwright 超时
# 文案为库内固定英文不随 locale 本地化，browser.py 分类以类型化异常优先、
# 文案仅兜底，引擎「wait 超时」中文前缀本身已在指纹表内。
# 裸 "wait_for" 已收窄为 "wait_for_selector"（code-review 821c2b29bb5b）：
# 业务型错误文案（步骤名 wait_for_xxx、「wait_for_response 返回业务错误」类）
# 不再凭 wait_for 子串混入纯等待超时候选。真实 Playwright 超时文案均带
# 「Timeout ...ms exceeded」稳定特征（由 "timeout " 覆盖），引擎 wait 步骤由
# "wait 超时" 覆盖，裸 wait_for 的唯一独立覆盖面仅剩 API 前缀形态
# "wait_for_selector: ..."——收窄零漏判真实 env 阻塞。
_WAIT_TIMEOUT_MARKERS = (
    "timeout ",
    "timed out",
    "wait_for_selector",
    "waiting for locator",
    "wait 超时",
    "locator does not exist",
    "did not appear",
)


def is_wait_timeout_error(error: str) -> bool:
    """判断断言/步骤失败是否属于纯等待超时（无业务信息）。

    特征包括:
    - Playwright 统一超时文案: "Timeout 3000ms exceeded."
    - 等待过程描述: "waiting for locator" / "wait_for_selector"
    - 元素缺席描述: "did not appear" / "locator does not exist"
    - 引擎 wait 步骤封装: "wait 超时: ..."（裸「超时」/「exceeded」已收窄，
      业务型超时文案不判纯等待超时——code-review 2084e503bd60）
    """
    if not error:
        return False
    lowered = error.lower()
    return any(marker in lowered for marker in _WAIT_TIMEOUT_MARKERS)


def has_mock_api_step(scenario_result: dict) -> bool:
    """报告场景的 step_results 中是否含 mock_api 操作步骤。

    仅信任 step_results 中显式的 action 字段；缺失即视为无 mock
    （不可测即不降级，保守方向）。
    """
    step_results = scenario_result.get("step_results")
    if not isinstance(step_results, list):
        return False
    for step in step_results:
        if isinstance(step, dict) and step.get("action") == "mock_api":
            return True
    return False


def _failed_wait_errors(scenario_result: dict, field: str) -> list[str]:
    """提取指定字段（steps/assertions）中失败且为等待超时类的错误文本。"""
    items = scenario_result.get(field)
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        passed = item.get("pass")
        success = item.get("success")
        # assertions 用 pass、steps 用 success；两键缺失（None）自然落入
        # 判定之外视为未失败（保守），无需显式分支
        if (passed is False or success is False) and is_wait_timeout_error(
            str(item.get("error") or "")
        ):
            out.append(str(item.get("error") or ""))
    return out


def is_env_candidate(scenario_result: dict) -> bool:
    """判定某失败场景是否可降级为 blocked-env 的候选。

    候选 = 步骤序列含 mock_api 且（失败断言或失败步骤）属于纯等待超时。
    调用方须确保场景 status == "fail"（本函数不做状态判断，保持单一职责）。
    """
    if not has_mock_api_step(scenario_result):
        return False
    wait_errors = _failed_wait_errors(scenario_result, "assertion_results")
    wait_errors += _failed_wait_errors(scenario_result, "step_results")
    return bool(wait_errors)


def is_connection_error_candidate(scenario_result: dict) -> bool:
    """API 场景连接失败类候选（verify-runner-engine：连接失败类=环境候选）。

    候选 = step_results 含 http_request/sse_connect 步骤且 error_type 为
    connection_failed（实例失联/不可达）。探针确认失联 → 降级 blocked-env；
    连接失败不代表产品逻辑缺陷，不得进入 product-bug 管道。
    """
    step_results = scenario_result.get("step_results")
    if not isinstance(step_results, list):
        return False
    return any(
        isinstance(s, dict)
        and s.get("action") in ("http_request", "sse_connect")
        and s.get("error_type") == "connection_failed"
        for s in step_results
    )


def is_blank_render_candidate(scenario_result: dict) -> bool:
    """web 场景白屏候选（B1，fenixd-registry-ignored-false-attribution-loop）。

    候选 = step_results 存在显式 ``first_frame_ok is False`` 的步骤
    （browser._wait_stable 首帧等待 8s 超时后由 navigate 步骤落盘）。
    CSR SPA 冷启动白屏时后续断言全为「元素不存在」类无业务信息失败，
    曾被误归因为 registry/数据问题打回 implementer 空转。

    白屏是**客户端渲染维度**证据：即便服务探针健康（实例在线、API 正常），
    「该场景本轮未完成渲染」的事实不变——finalize 对本候选**不依赖**
    probe_healthy 一律降级 blocked-env。真前端崩溃（JS 异常白屏）由
    pm_engine 的 blocked-env 升级通道（_escalate_env_blocked）送人工复核，
    不静默丢失。

    保守性：仅信任显式 ``is False``（缺失/True 均不算）；调用方须确保
    场景 status == "fail"（与 is_env_candidate 同一单一职责约定）。
    """
    step_results = scenario_result.get("step_results")
    if not isinstance(step_results, list):
        return False
    return any(isinstance(s, dict) and s.get("first_frame_ok") is False for s in step_results)


def finalize_scenario_status(scenario_result: dict, probe_healthy: bool) -> str:
    """场景状态最终结算：对 fail 候选做 blocked-env 后置分类。

    Args:
        scenario_result: report 中的场景结果 dict（含 status/step_results/
            assertion_results）。
        probe_healthy: 该轮验证的环境探针结果（True=实例在线推流正常）。

    Returns:
        有效状态: pass / warning / fail / blocked-env。
    """
    status = scenario_result.get("status", "pass")
    if status != "fail":
        return status
    # 白屏候选直接降级：客户端渲染失败证据不因服务探针健康而被推翻（B1），
    # 真前端崩溃走 pm_engine blocked-env 升级通道送人工，不进产品归因
    if is_blank_render_candidate(scenario_result):
        return "blocked-env"
    # 探针健康 → 维持真失败（design D1：此时确属真缺陷或慢场景）
    if probe_healthy:
        return "fail"
    # 探针失联 + 候选（web mock 断流 / api 连接失败）→ blocked-env
    if is_env_candidate(scenario_result) or is_connection_error_candidate(scenario_result):
        return "blocked-env"
    return "fail"


def probe_http_health(base_url: str, timeout: float = 2.0) -> bool:
    """对被测实例发起连通性探测（含等价数据端点检查）。

    顺序探测: 根路径 → /api/state（dashboard 实时数据源）→ /api/overview
    （dashboard 等价端点）。收到任意 HTTP 状态码（2xx/3xx 经响应对象、
    4xx/5xx 以 HTTPError 形态抛出）即视为连通——TCP+HTTP 可达证明实例在线，
    受限（401/403）/路径迁移（404）形态不误判失联；仅连接类异常（拒绝/
    超时/DNS）判失联。争议端点不可探测时仅凭根路径结果判定（非 dashboard
    应用不误降级）。

    Args:
        base_url: 实例入口 URL（应含 scheme://host[:port]）。
        timeout: 单次探测超时（秒）。

    Returns:
        True 表示任一探测端点连通即成立（根路径返回任意 HTTP 状态码即满足，
        不强制数据端点可达）；False 表示全部探测端点均失联。
    """
    candidates: list[str] = []
    base = (base_url or "").rstrip("/")
    if base.startswith("chrome-extension://"):
        # 扩展内页无法在验证上下文直接 HTTP 探测：视为无法完成探测（保守健康）
        return True
    if not base:
        return True
    if not base.startswith(("http://", "https://")):
        # scheme 缺失（如 "127.0.0.1:8787"，配置写法漂移即可出现）时无法完成
        # 探测：urllib 对裸串抛 unknown url type 全候选 continue，最终误判
        # 失联并批量降级 blocked-env——与空值/chrome-extension 分支同款保守
        # 健康口径（code-review 769ac7589733）。
        _logger.warning("env_probe base_url 缺 scheme，跳过探测（保守健康）: %s", base)
        return True
    # 执行到这里 base 必然带 http(s):// 前缀（缺失/空/扩展内页均已提前返回）。
    candidates.append(base + "/")
    for ep in ("/api/state", "/api/overview"):
        candidates.append(base + ep)
    for url in candidates:
        try:
            req = urllib.request.Request(
                url, method="GET", headers={"User-Agent": "fenix-env-probe"}
            )
            # [fenix-ignore:1d928f301673] 同步阻塞为设计契约：全部调用点
            # （engine/web_runner/api_runner）均已 asyncio.to_thread 放线程池，
            # 事件循环内不存在直调。
            with _DIRECT_OPENER.open(req, timeout=timeout) as resp:
                if resp.status < 400:
                    return True
        except urllib.error.HTTPError:
            # 收到任意 HTTP 状态码（含 401/403/404/5xx，urllib 以 HTTPError
            # 形态抛出）即 TCP+HTTP 可达：实例在线，受限/路径迁移形态的真失败
            # 不再被误降级 blocked-env（code-review 42a28727427f）；
            # 仅连接类异常（拒绝/超时/DNS）判失联。
            return True
        except Exception:
            continue
    _logger.debug("env_probe 失联: %s", base)
    return False

