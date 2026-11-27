"""core/agent_runner/lane_preflight.py — 裁决车道前置自检（agent-lane-preflight）。

arbiter/repair 裁决车道的前置健康探针：CLI 可达 + 凭据路由本地解析两级
检查（对应 2026-11-09 四签名秒挂 8h 事故的两种真实根因——dsh bundle 不
兼容被跳过 / MISSING_CREDENTIAL 凭据路由不可解析）。故障只能靠阻塞堆积
后倒查的前科收口为：启动/周期/派发前三面探针，unhealthy 时显式拦截并
告警（单发），不健康状态不进车道计数（不烧 dead-man/infra 配额）。

fail-open 纪律：探针自身任何异常按 unhealthy 处置并 WARNING，MUST NOT
抛出、MUST NOT 阻塞 daemon 主流程（与推送凭证自检同范式）。禁内存定时
器——周期重探由调用方挂靠既有周期节拍（scheduled-reverify-restart-
durability 纪律），本模块只提供 :class:`LanePreflightCache` TTL 缓存
（派发前置在 TTL 内复用探针结论，超时重探）。

失败分级共用口径：:func:`classify_lane_failure` 与本模块同居一文件——
infra 环境指纹集是「探针能探什么」与「run 失败算不算环境问题」的同一
事实两面，单一来源防漂移（harden-arbiter-lane-resilience design §能力一）。
"""

from __future__ import annotations

import inspect
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# AdminStore escalation kind 字面量（懒 import AdminStore 本体——模块级只
# 定常量，import 留在函数内防装配环；字面量与 core.admin_store.ESCALATION
# 同值，admin_store 侧改动时测试守卫钉死）。
ESCALATION_KIND = "escalation"

# ── 环境指纹集（单一来源，classify_lane_failure 与探针共用）────────────
# 逐条对应实证根因（2026-11-09 事故 + 前日首败）：
# - MISSING_CREDENTIAL：dsh 运行期凭据缺失错误码（provider route 无 API key，
#   dsh_adapter 凭据桥接缺失即秒挂）；
# - No such file or directory：CLI 二进制缺失（Errno 2 形态，含
#   [Errno 2] No such file or directory: 'claude'）；
# - skipping profile bundle：dsh bundle 不兼容被跳过（插件版本不匹配）。
LANE_INFRA_FINGERPRINTS = (
    "MISSING_CREDENTIAL",
    "No such file or directory",
    "skipping profile bundle",
)

#: 派发前置探测的 adapter 健康检查子进程超时（秒）——「短平快」口径：
#: 探针只判可达性，MUST NOT 用 dispatch 同款 20s 缺省拖慢拦截判定路径。
PROBE_HEALTH_TIMEOUT_S = 5.0

#: 凭据路由探针覆盖的裁决车道角色集（config 显式链按角色检查；未分配
#: 角色按 harness 默认链做可判定性检查——provider-fallback-dispatch-gate
#: 1.1 修订前「跳过不报」的静默面，回落形态不再静默）。
PROBE_LANE_ROLES = ("arbiter", "repair")

# ── 回落角色默认链凭据判定（provider-fallback-dispatch-gate 1.1）────────
# 三值判定词表（verdict，供派发冻结闸消费）：
# - FALLBACK_VERDICT_OK：默认链凭据可判定且可用——回落到可用链仍合法
#   （add-harness-default-key-fallback D3 合法回落语义保留，仅拦「注定
#   死亡的回落」）；
# - FALLBACK_VERDICT_MISSING：默认链路由可判定但凭据缺失——11-09 事故
#   形态（「无 key 的默认路由」，spawn 必死于 MISSING_CREDENTIAL）；
# - FALLBACK_VERDICT_INDETERMINABLE：本地无解析面（dsh profile 默认档/
#   无路由痕迹的环境继承），无法判定——按 design Risks 取舍同样冻结
#   （误判后果是拦截+告警+放行键兜底，优于静默秒挂）。
FALLBACK_VERDICT_OK = "ok"
FALLBACK_VERDICT_MISSING = "missing"
FALLBACK_VERDICT_INDETERMINABLE = "indeterminable"

# ── 默认链凭据降级试呼（evo-repair-lane-credential-probe-fix 1.2）────────
# env 三键嗅探不可判定（OAuth/CLI 默认档形态）时，探针默认纯本地、不烧钱
# 不触限流的设计意图由「按 TTL 降级试呼」补齐取证路径：30 分钟 TTL 内至多
# 一次 CLI 短请求（复用 PROBE_HEALTH_TIMEOUT_S 短超时口径）。
# MUST 为**进程级共享单例**（模块级）：消费方有三处且各持独立
# LanePreflightCache 实例——回落冻结闸 TTL 过期同步重探（300s 节拍）、
# daemon 60s 周期 tick、启动自检；缓存若随实例走，闸节拍会让试呼频率放大
# 到设计意图的 6 倍。
DEFAULT_CHAIN_TRIAL_TTL_S = 1800.0
#: 试呼提示词：最小成本单轮请求（只判默认档能否完成一次 API 往返）。
DEFAULT_CHAIN_TRIAL_PROMPT = "回复 ok（车道凭据探针短请求）"

_credential_trial_lock = threading.Lock()
#: (probed_at: time.monotonic, verdict, detail)——模块级试呼缓存单例。
_credential_trial_cache: Optional[Tuple[float, str, str]] = None


def reset_default_chain_trial_cache() -> None:
    """清空进程级试呼缓存（测试密闭 / 热更新场景；生产无调用方）。"""
    global _credential_trial_cache
    with _credential_trial_lock:
        _credential_trial_cache = None


def _trial_default_chain_credentials(
    config, timeout: float = PROBE_HEALTH_TIMEOUT_S
) -> Tuple[str, str]:
    """执行一次 CLI 短请求试呼（默认档可用性取证；异常/超时按不可用）。

    调用方 MUST 持有 :data:`_credential_trial_lock`（除非测试直调）。
    成功（CLI 退出码 0）→ ``(ok, 成功 detail)``；超时/异常/非零退出 →
    ``(indeterminable, detail 含错误尾部)``——探针按 unhealthy 消费，MUST
    NOT 抛出、MUST NOT 无界阻塞（``subprocess.run`` 带 ``timeout``）。
    「纯本地默认链」语义在此处唯一例外：仅 env 嗅探不可判定时调用。
    """
    try:
        from core.agent_runner.harness import HARNESS_EXECUTABLE_NAMES
        from core.config import ConfigLoader

        harness = ConfigLoader.get_harness(config or {})
        executable = HARNESS_EXECUTABLE_NAMES.get(harness) or harness
        env = os.environ.copy()
        # root 部署下 CLI 的 IS_SANDBOX 兜底与 adapter 层同口径（试呼不注入
        # 任何 ANTHROPIC_* 覆写——探的就是现状默认档）
        if getattr(os, "geteuid", None) is not None and os.geteuid() == 0:
            env.setdefault("IS_SANDBOX", "1")
        proc = subprocess.run(
            [executable, "-p", DEFAULT_CHAIN_TRIAL_PROMPT],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return FALLBACK_VERDICT_INDETERMINABLE, (
            f"降级试呼超时（>{timeout:g}s，默认档不可用）")
    except Exception as e:
        return FALLBACK_VERDICT_INDETERMINABLE, (
            f"降级试呼异常（默认档不可用）: {type(e).__name__}: "
            f"{(str(e).strip() or '无错误输出')[-300:]}")
    if proc.returncode == 0:
        return FALLBACK_VERDICT_OK, (
            "降级试呼成功（CLI 单轮短请求往返，默认档可用）")
    tail = (
        (proc.stderr or "").strip()
        or (proc.stdout or "").strip()
        or "无错误输出"
    )[-300:]
    return FALLBACK_VERDICT_INDETERMINABLE, (
        f"降级试呼失败（exit={proc.returncode}，默认档不可用）: {tail}")


def _probe_default_chain_via_trial(config) -> Tuple[str, str]:
    """TTL 缓存包裹的试呼（命中缓存不重复试呼；持锁串行化并发首试）。"""
    global _credential_trial_cache
    with _credential_trial_lock:
        now = time.monotonic()
        if _credential_trial_cache is not None:
            probed_at, verdict, detail = _credential_trial_cache
            if (now - probed_at) < DEFAULT_CHAIN_TRIAL_TTL_S:
                return verdict, detail
        verdict, detail = _trial_default_chain_credentials(config)
        _credential_trial_cache = (now, verdict, detail)
        return verdict, detail


@dataclass(frozen=True)
class LaneHealth:
    """探针结论：``ok``=两级检查全过；``reasons``=失败原因清单（可诊断文案）。

    ``fallback_verdicts``（provider-fallback-dispatch-gate 1.1）：回落角色
    （未分配显式链）的默认链凭据三值判定，键 ∈ :data:`PROBE_LANE_ROLES`
    且仅含回落形态角色，值 ∈ FALLBACK_VERDICT_* 词表——派发冻结闸
    （runner._provider_fallback_dispatch_gate）按角色消费本字段；显式链
    角色不进本表（行为不变）。``ok=True`` 时本表也可能非空（全部回落
    角色判定 ok = 合法回落放行，无 reason）。
    """

    ok: bool
    reasons: List[str] = field(default_factory=list)
    fallback_verdicts: Dict[str, str] = field(default_factory=dict)
    # 稳态边沿标记（evo-lane-probe-steady-noise-governance 1.1，D2）：探针体
    # 经 :func:`observe_lane_conclusion` 观测后回填——``edge``=结论变化拍
    # （含首判）、``heartbeat``=同判稳态心跳拍、``""``=同判稳态静默拍。带
    # 缺省字段，既有构造方（测试手搓 LaneHealth）零改动兼容。
    steady_event: str = ""
    #: 同判稳态已持续时长（秒，monotonic 口径；仅 heartbeat 拍非零）
    steady_duration_s: float = 0.0


def _callable_accepts_timeout_kwarg(func) -> bool:
    """预判 callable 是否接受 ``timeout`` 关键字实参（**kwargs 视为接受）。

    签名不可内省（builtin/C 扩展等罕见形态）按接受处理——探针体内的
    TypeError 由外层 unhealthy 兜底如实归因，不做「TypeError 试探回退」
    （那会把体内 TypeError 误判为签名不符并二次执行探针）。
    """
    try:
        params = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        p.kind
        in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and p.name == "timeout"
        or p.kind == inspect.Parameter.VAR_KEYWORD
        for p in params
    )


def probe_default_chain_credentials(config) -> Tuple[str, str]:
    """回落角色 harness 默认链凭据可判定性（provider-fallback-dispatch-gate 1.1）。

    角色未分配显式链时 spawn 回落 harness 默认配置——按默认链的本地解析
    面做与显式链同构的凭据可判定检查（baseurl/apikey 两键非空判定），返回
    ``(verdict, detail)``。**默认纯本地检查、不发 API 请求**；仅当 env 三键
    嗅探结果为不可判定时，按 :data:`DEFAULT_CHAIN_TRIAL_TTL_S`（30 分钟，
    进程级共享单例）降级执行一次 CLI 短请求试呼取证（evo-repair-lane-
    credential-probe-fix 1.2）——试呼成功判 ok、失败/超时判不可判定且
    detail 附错误尾部（探针据此 unhealthy，MUST NOT 无界阻塞派发入口）：

    - dsh 选型：回落 spawn 不携带 ``--patch``，模型路由由 dsh 侧 profile
      自身配置承载（dsh_adapter 回落形态注释同源），本地无解析面 →
      ``indeterminable``；
    - claude 选型（含未知选型兜底同判）：默认路由 = daemon 进程环境继承
      （adapter 环境继承形态同源），``os.environ`` 的 ANTHROPIC_BASE_URL
      与 AUTH_TOKEN/API_KEY 按四形态判定——路由与凭据齐（baseurl 与
      token/key 均非空）→ ``ok``；有路由无凭据（baseurl 非空、token/key
      均空）→ ``missing``（11-09「无 key 的默认路由」事故形态）；仅凭据
      在场（token/key 非空、baseurl 空）→ 同 ``ok`` 放行：凭据可判定即
      无 MISSING_CREDENTIAL 秒挂面（spawn 以 key 直连官方缺省端点，缺省
      端点与 key 不匹配时仍有 API 往返、不秒挂，故不冻结回落）；路由与
      凭据均无痕迹 → 本地不可判定（OAuth/CLI 默认档形态），按 TTL 降级
      试呼取证：试呼成功 → ``ok``，失败/超时/异常 → ``indeterminable``
      且 detail 附错误尾部（见 :func:`_trial_default_chain_credentials`）。

    解析自身任何异常 → ``("indeterminable", 异常摘要)``——MUST NOT 抛出、
    MUST NOT 静默跳过（spec：无法判定时输出明确探针结果）。
    """
    try:
        from core.config import ConfigLoader

        harness = ConfigLoader.get_harness(config or {})
    except Exception as e:
        return FALLBACK_VERDICT_INDETERMINABLE, (
            f"harness 选型解析异常（按不可判定处置）: {type(e).__name__}: {e}")
    if harness == "dsh":
        return FALLBACK_VERDICT_INDETERMINABLE, (
            "dsh 回落 spawn 不携带 --patch，凭据由 dsh 侧 profile 默认档承载，"
            "本地无解析面（不可判定）")
    baseurl = (os.environ.get("ANTHROPIC_BASE_URL") or "").strip()
    auth = (os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not baseurl and not (auth or key):
        # 本地无路由痕迹（OAuth/CLI 默认档形态）：默认纯本地的检查到此
        # 不可判定，按 TTL 降级试呼一次 CLI 短请求取证（进程级共享缓存，
        # 缓存命中期内不重复试呼）
        verdict, detail = _probe_default_chain_via_trial(config)
        if verdict == FALLBACK_VERDICT_OK:
            return verdict, detail
        return verdict, (
            "daemon 进程环境无 ANTHROPIC_BASE_URL/AUTH_TOKEN/API_KEY 路由痕迹"
            f"（OAuth/CLI 默认档形态本地不可判定）；{detail}")
    if baseurl and not (auth or key):
        return FALLBACK_VERDICT_MISSING, (
            f"daemon 进程环境路由 ANTHROPIC_BASE_URL={baseurl} 无 AUTH_TOKEN/"
            "API_KEY（无 key 的默认路由——MISSING_CREDENTIAL 秒挂同因）")
    # 「仅凭据在场」形态（baseurl 空而 token/key 非空）与「路由凭据齐」
    # 同落此分支按 ok 放行：凭据可判定即无 MISSING_CREDENTIAL 秒挂面，
    # 不冻结回落（docstring 四形态判定口径同源）
    return FALLBACK_VERDICT_OK, (
        f"daemon 进程环境默认路由凭据可判定且齐备（baseurl={baseurl}）")


def probe_lane_health(config, logger=None, health_timeout: float = PROBE_HEALTH_TIMEOUT_S) -> LaneHealth:
    """裁决车道健康探针（两级检查，fail-open 不抛出）。

    ①CLI 可达：按 ``agent.harness`` 选型解析可执行名（单源
    ``HARNESS_EXECUTABLE_NAMES``），``shutil.which`` 探测（探测单源
    ``precheck_harness_executable``，与 dispatch 派发前置共用）；可达再
    执行 adapter 声明的 ``check_health``（duck-typing，dsh 通道=版本白
    名单 + Bundle 挂载探测——bundle 不兼容在派发前即被命中），短超时。
    ②凭据路由可解析：config 显式模型链（``agents.models.<role>``，role ∈
    :data:`PROBE_LANE_ROLES`）的链首选 provider 本地解析出非空 baseurl 与
    apikey（``_apply_provider_env`` 注入口所需的两键，维护车道不接
    failover 只用链首选直连）；显式链角色本地解析，MUST NOT 真发 API
    请求（本约束不变；仅未分配显式链的回落默认链在嗅探不可判定时按
    TTL 降级试呼，见 :func:`probe_default_chain_credentials`）。未分
    配显式链的角色（回落 harness 默认形态，provider-fallback-dispatch-
    gate 1.1 修订前跳过不报）按默认链做可判定性检查
    （:func:`probe_default_chain_credentials`）：verdict 非 ok 即追加
    reason（带 fallback 标记），verdict 记入结果的 ``fallback_verdicts``
    供派发冻结闸按角色消费；verdict ok 的合法回落不报。

    任一级失败 → ``ok=False`` + reasons。探针自身异常按 unhealthy 处置
    并 WARNING（logger 在场时），不抛出、不阻塞调用方。
    """
    reasons: List[str] = []
    fallback_verdicts: Dict[str, str] = {}
    # ── ① CLI 可达 ────────────────────────────────────────────────
    try:
        from core.config import ConfigLoader
        from core.agent_runner.harness import (
            HARNESS_EXECUTABLE_NAMES,
            precheck_harness_executable,
            resolve_adapter_from_config,
        )

        harness = ConfigLoader.get_harness(config or {})
        executable = HARNESS_EXECUTABLE_NAMES.get(harness)
        if executable is None:
            reasons.append(
                f"agent.harness 选型 {harness!r} 无对应可执行名（合法选型外）"
            )
        else:
            precheck_error = precheck_harness_executable(executable)
            if precheck_error:
                reasons.append(precheck_error)
            else:
                # adapter 子进程级健康检查（duck-typing，claude 通道无此成员
                # 零动作放行——与 runner._execute_agent dispatch 前置同口径）
                adapter = resolve_adapter_from_config(config or {})
                health_check = getattr(adapter, "check_health", None)
                if health_check is not None:
                    # 签名预判调用形态（不走 except TypeError 试探回退——
                    # 探针体内 TypeError 会被误判为「无 timeout 形参」并
                    # 二次执行探针）；体内异常由外层 unhealthy 兜底如实归因
                    if _callable_accepts_timeout_kwarg(health_check):
                        health_check(timeout=health_timeout)
                    else:
                        # 兼容无 timeout 形参的 adapter 声明（零参直调）
                        health_check()
    except Exception as e:
        # 探针自身故障按 unhealthy 处置（含 HarnessHealthError 的兜外形态）
        reasons.append(f"车道 CLI 可达探测异常: {type(e).__name__}: {e}")
    # ── ② 凭据路由可解析（本地，不发 API 请求）──────────────────────
    try:
        from core.config import ConfigLoader

        for role in PROBE_LANE_ROLES:
            # 逐角色 try/except：单个角色的脏配置（如链首元素非成对
            # 序列形态）只记该角色的归因 reason，不中断循环、不吞掉
            # 其余角色的检查结果。
            try:
                chain = ConfigLoader.get_agent_model_assignment(
                    config or {}, role)
                if not chain:
                    # 未分配显式链：回落 harness 默认形态——按默认链做凭据
                    # 可判定检查（不再静默跳过；provider-fallback-dispatch-
                    # gate 1.1）。verdict ok 的合法回落（D3 保留语义）不报。
                    verdict, detail = probe_default_chain_credentials(
                        config or {})
                    fallback_verdicts[role] = verdict
                    if verdict == FALLBACK_VERDICT_MISSING:
                        reasons.append(
                            f"{role} 回落 harness 默认链凭据缺失（fallback=true）:"
                            f"{detail}——首派发将被回落冻结闸拦截")
                    elif verdict == FALLBACK_VERDICT_INDETERMINABLE:
                        reasons.append(
                            f"{role} 回落 harness 默认链凭据不可判定（fallback=true）:"
                            f"{detail}——首派发将被回落冻结闸拦截")
                    continue
                provider = chain[0][0] or {}
                baseurl = str(provider.get("baseurl") or "").strip()
                apikey = str(provider.get("apikey") or "").strip()
                if not baseurl or not apikey:
                    reasons.append(
                        f"{role} 车道凭据路由不可解析：链首选 provider "
                        f"{str(provider.get('name') or '?')!r} baseurl/"
                        f"apikey{'均缺' if not baseurl and not apikey else ('baseurl 缺' if not baseurl else 'apikey 缺')}"
                        "（显式链配了一半或凭据未配置——MISSING_CREDENTIAL 秒挂同因）"
                    )
            except Exception as e:
                reasons.append(
                    f"{role} 凭据路由解析异常: {type(e).__name__}: {e}")
    except Exception as e:
        # 循环外兜底（ConfigLoader 导入等）：探针自身异常按 unhealthy
        # 处置的 fail-open 语义保持不变
        reasons.append(f"凭据路由解析异常: {type(e).__name__}: {e}")
    health = LaneHealth(ok=not reasons, reasons=reasons,
                        fallback_verdicts=fallback_verdicts)
    # 稳态边沿观测（evo-lane-probe-steady-noise-governance 1.1）：每拍判定
    # 经进程级单例对账；观测口自身故障 fail-open 按边沿处置（回到逐拍发射
    # 的既有行为——降噪机制失灵宁可多报，不可静默吞掉边沿）。
    try:
        steady_event, steady_duration_s = observe_lane_conclusion(health)
    except Exception:
        steady_event, steady_duration_s = LANE_STEADY_EVENT_EDGE, 0.0
    health = replace(health, steady_event=steady_event,
                     steady_duration_s=steady_duration_s)
    if not health.ok and logger is not None and health.steady_event:
        # 仅边沿（结论变化含首判）与每小时心跳拍发射（R1 稳态降噪）；
        # 心跳携带稳态持续时长。恢复（healthy 边沿）不在探针体打 WARNING
        # ——播报语义由自检消费点的既有 INFO 恢复留痕承担（design Risks）。
        steady_note = ""
        if health.steady_event == LANE_STEADY_EVENT_HEARTBEAT:
            minutes = max(1, int((health.steady_duration_s or 0.0) // 60.0))
            steady_note = f"（同判稳态心跳：已持续约 {minutes} 分钟）"
        try:
            logger.warning(
                "agent_runner",
                "车道前置探针 unhealthy" + steady_note + ": "
                + "；".join(reasons)[:600],
            )
        except Exception:
            pass  # 告警日志失败不改变探针结论
    return health


def classify_lane_failure(result: dict) -> str:
    """裁决车道 run 失败分级：``"infra"``（环境不可用）| ``"judgment"``。

    判据（满足任一即为 infra）：
    - **0 rounds**：信封显式携带 ``rounds`` 键且 <= 0——run 无任何 API
      往返样本（latency 统计「无样本」判定同口径，信封透传真值，不从
      文案反解）；``rounds`` 键缺席时不可判定（既有测试替身/旧信封形态），
      本判据不命中、保守判 judgment；
    - **环境指纹**：error（或 stderr，若信封携带）命中
      :data:`LANE_INFRA_FINGERPRINTS` 固定指纹集。

    其余（含 exit=1 且有 API 往返、产物硬门拦截、outcome 非法）判
    judgment——真实车道真实失败，保持现行连败→dead-man 语义。预算耗尽
    不在本函数判定（信封无预算位），调用方（arbiter._on_run_failed）
    MUST 在调用本函数前先判预算耗尽并恒判 judgment（harden-arbiter-
    lane-resilience design：预算耗尽是真实车道真实消耗，不判 infra）。

    冗余判据「exit_code=1 且 rounds==0」为 0 rounds 判据子集，行为已由
    第一判据覆盖，指纹不单列（design 评审注：冗余保留仅作归因可读性——
    归因文案由 0 rounds 判据的 reason 携带）。
    """
    result = result or {}
    rounds = result.get("rounds")
    if rounds is not None:
        try:
            if int(rounds) <= 0:
                return "infra"
        except (TypeError, ValueError):
            pass  # 脏 rounds 值按缺席处理
    haystack = " ".join(
        str(result.get(key) or "") for key in ("error", "stderr")
    )
    if haystack:
        # [fenix-ignore:7b17929c79e5] 生产信封（run_arbiter）无 stderr 键、error 仅由框架受控模板与 CLI 进程自身 stderr 尾行拼装，运行期工具输出走 stream-json stdout 不进判据，过宽匹配面不成立
        for fingerprint in LANE_INFRA_FINGERPRINTS:
            if fingerprint in haystack:
                return "infra"
    return "judgment"


class LanePreflightCache:
    """探针结论 TTL 缓存（派发前置复用，超时重探）。

    TTL 内多次派发只探一次（S4）；TTL 过期首查重探。``invalidate`` 供
    外部强制失效（测试/热更新场景）。线程安全（arbiter 单飞 worker 与
    主循环周期探针可能并发取用）：``get_or_probe``/``invalidate`` 经
    实例 ``_lock`` 串行化，并发首查合并为单次探测（后到者等持锁方回写
    后复用结论，不各自起探针子进程）。
    """

    def __init__(self, ttl_s: float = 300.0):
        self._ttl_s = max(0.0, float(ttl_s))
        self._health: Optional[LaneHealth] = None
        self._probed_at: float = 0.0
        self._lock = threading.Lock()

    def get_or_probe(self, config, logger=None) -> LaneHealth:
        """TTL 内返回缓存结论；过期/无缓存时探一次并缓存。"""
        # 整段（TTL 检查 + 探测 + 回写）收进临界区：持锁串行化使并发
        # 首查只探一次（探测最长 PROBE_HEALTH_TIMEOUT_S，调用方均为低频
        # 探针，串行等待可接受）；probe_lane_health 不重入本方法，无自锁。
        with self._lock:
            now = time.monotonic()
            if (
                self._health is not None
                and (now - self._probed_at) < self._ttl_s
            ):
                return self._health
            health = probe_lane_health(config, logger)
            self._health = health
            self._probed_at = now
            return health

    def invalidate(self) -> None:
        with self._lock:
            self._health = None
            self._probed_at = 0.0

    @property
    def ttl_s(self) -> float:
        return self._ttl_s


# ── 稳态边沿发射记忆（evo-lane-probe-steady-noise-governance 1.1/R1）────
# 探针多消费方（fenixd 启动/周期 tick 直调 + 回落冻结闸经 LanePreflightCache
# + 自检消费点复查），稳态记忆 MUST 进程级单例并锁保护（防并发拍读写撕裂
# 与心跳重复计时），持续时长以 time.monotonic 计（与 LanePreflightCache 同
# 款，防墙钟跳变）。「结论」可比域（D1）：(ok, fallback_verdicts 归一,
# reasons 归一集) 三元全同才算同判稳态；任一位漂移（unhealthy 同判但失败
# 形态变化）即按新边沿发射，防止形态漂移被同判静默吞掉。

#: 稳态心跳节流间隔（秒）——稳态期间每小时至多 1 条可观测性心跳。
LANE_STEADY_HEARTBEAT_INTERVAL_S = 3600.0
#: 结论变化拍（含进程首判）——即时发射标记。
LANE_STEADY_EVENT_EDGE = "edge"
#: 同判稳态心跳拍标记（携带 :data:`LaneHealth.steady_duration_s`）。
LANE_STEADY_EVENT_HEARTBEAT = "heartbeat"

_lane_steady_lock = threading.Lock()
#: {key, episode, entered_at, next_heartbeat_at, alert_episode}——进程级单例。
_lane_steady_state: Optional[dict] = None
_lane_steady_episode_seq = 0


def reset_lane_steady_state() -> None:
    """清空进程级稳态记忆（测试密闭 / 热更新场景；生产无调用方）。"""
    global _lane_steady_state, _lane_steady_episode_seq
    with _lane_steady_lock:
        _lane_steady_state = None
        _lane_steady_episode_seq = 0


def _lane_conclusion_key(
    ok: bool, reasons, fallback_verdicts
) -> Tuple[bool, Tuple[Tuple[str, str], ...], Tuple[str, ...]]:
    """结论可比域（D1）：三元全同=同判稳态，任一位漂移=新边沿。"""
    return (
        bool(ok),
        tuple(sorted((fallback_verdicts or {}).items())),
        tuple(sorted(str(r) for r in (reasons or ()))),
    )


def observe_lane_conclusion(
    health: "LaneHealth", now: Optional[float] = None
) -> Tuple[str, float]:
    """稳态边沿观测口（锁保护；返回 ``(event, steady_duration_s)``）。

    每拍判定结论对账进程级稳态记忆：

    - 首判 / 结论变化（三元可比域任一位漂移）→ ``(edge, 0.0)``——重置
      稳态进入时刻并推进 episode（episode 是告警重武装闸 2.1 的「同一
      稳态持续期间」判据：恢复/形态漂移/试呼裁决翻转都会推进它）；
    - 同判稳态且心跳窗口到期 → ``(heartbeat, 持续秒数)``——下一心跳窗口
      顺延；
    - 其余同判稳态拍 → ``("", 0.0)``——静默（R1：不再逐拍重打）。

    **双发射点对齐（R3）关键语义**：本口是**领取制**——同一拍先到方（探
    针体）领取边沿/心跳事件，后到方（fenixd 自检消费点复查）对账同判
    稳态得 ``""``，同拍双组件双行被天然消除；``now`` 缺省取 monotonic
    （测试可注入合成时基）。
    """
    global _lane_steady_state, _lane_steady_episode_seq
    key = _lane_conclusion_key(
        health.ok, health.reasons, health.fallback_verdicts)
    if now is None:
        now = time.monotonic()
    with _lane_steady_lock:
        state = _lane_steady_state
        if state is None or state["key"] != key:
            _lane_steady_episode_seq += 1
            _lane_steady_state = {
                "key": key,
                "episode": _lane_steady_episode_seq,
                "entered_at": now,
                "next_heartbeat_at": now + LANE_STEADY_HEARTBEAT_INTERVAL_S,
                "alert_episode": None,
            }
            return LANE_STEADY_EVENT_EDGE, 0.0
        if now >= state["next_heartbeat_at"]:
            state["next_heartbeat_at"] = (
                now + LANE_STEADY_HEARTBEAT_INTERVAL_S)
            return (
                LANE_STEADY_EVENT_HEARTBEAT,
                max(0.0, now - state["entered_at"]),
            )
        return "", 0.0


def mark_lane_env_alert_registered() -> None:
    """告警登记入账（2.1 闸判据）：记「当前 episode 已落地登记」。

    :func:`ensure_lane_env_alert` 在 append 实际落地后调用；稳态记忆缺席
    （进程未探针过）时零动作。
    """
    with _lane_steady_lock:
        state = _lane_steady_state
        if state is not None:
            state["alert_episode"] = state["episode"]


def lane_env_alert_suppressed_by_steady() -> bool:
    """同判稳态一次性终态登记闸（R4/D3，2.1）——是否应抑制本次登记。

    判据：当前稳态 unhealthy 且「登记入账 episode == 当前 episode」（即
    本次连续稳态期间已落地过告警）。人工 handled 后同判稳态持续期间，
    任一登记调用方（fenixd 自检消费点 startup/periodic 与 arbiter run
    infra 失败路径）经 :func:`ensure_lane_env_alert` 入口统一命中本闸不
    重开；判定改变（episode 推进：环境形态漂移 / 试呼裁决翻转 / 恢复后
    再劣化）即新边沿，闸放行按新边沿重新登记。进程重启后稳态记忆单例
    清零——首判即新边沿，允许重新登记（稳态记忆按本 SPEC 1.1 约定是
    进程级生命周期）。
    """
    with _lane_steady_lock:
        state = _lane_steady_state
        return bool(
            state is not None
            and not state["key"][0]
            and state["alert_episode"] == state["episode"]
        )


# ── 「车道环境不可用」告警生命周期（agent-lane-preflight R2）────────────
# 单发（同一 unhealthy 周期只发一次，dedup_key 判据）+ 恢复自动关闭（探针
# healthy 时 auto_resolve）。arbiter run infra 失败路径与 daemon 启动/周期
# 探针共用同一对助手（同 dedup_key 同 signal_type——任一路径开的告警任一
# 路径都能关，双写防漂移）。直写 AdminStore 不入处置链（防自环：链无法
# 处置自己车道的死讯；harness_cli_unavailable 启动自检告警同先例）。

LANE_ENV_ALERT_SIGNAL = "lane_env_unavailable"
LANE_ENV_DEDUP_KEY = "lane-env-unavailable-arbiter-repair"


def _lane_env_alert_inflight(rec: dict) -> bool:
    # 人工已处理（handled=True）条目不属「在案未处理」：不再抑制新的
    # unhealthy 告警落地（否则环境持续不可用期间人工可见面失明，只能等
    # 150 条窗口裁剪后才重新武装）；同型口径见 admin_store
    # dispatch_host_change_rollback_alert 的 is_inflight（not handled 判据）
    return (
        rec.get("kind") == ESCALATION_KIND
        and rec.get("signal_type") == LANE_ENV_ALERT_SIGNAL
        and rec.get("dedup_key") == LANE_ENV_DEDUP_KEY
        and not rec.get("handled")
    )


#: 车道环境不可用告警「超龄未恢复」升级话术（evo-repair-lane-credential-
#: probe-fix 1.3）：原话术「随恢复自动关闭、无需人工处置」在探针长期
#: unhealthy（默认档凭据不可判定且无取证路径）时形成挂账死锁——同
#: dedup_key 未处理告警创建超 UNHANDLED_ESCALATION_AGING_HOURS 后切换。
LANE_ENV_AGED_HANDLING_NOTE = (
    "需人工升级：repair 回落链凭据不可判定已超 {hours} 小时——探针长期 "
    "unhealthy 且未随恢复自动关闭，请人工核查默认链凭据/CLI 环境后处置"
)


def _lane_env_alert_aged_action(hours: int) -> str:
    return LANE_ENV_AGED_HANDLING_NOTE.format(hours=hours)


def _upgrade_lane_env_alert_aging(store) -> int:
    """超龄未恢复告警就地改写升级话术（幂等；返回改写条数）。

    判定口径复用 ``core.self_review.UNHANDLED_ESCALATION_AGING_HOURS``
    （单源，避免与每日自省龄期盘点漂移）；``created`` 缺失/不可解析按
    龄期不可判跳过（不虚报）。``append_if_absent`` 命中在案条目即零写
    跳过（单发语义），故话术切换 MUST 走 :meth:`AdminStore.update_records`
    就地改写；已是升级话术的条目跳过（重复 tick 不重复改写、不动
    hit_count）。fail-open：本助手异常不外抛（外由 ensure_lane_env_alert
    的统一兜底收口）。
    """
    from datetime import datetime, timezone

    from core.self_review import UNHANDLED_ESCALATION_AGING_HOURS
    from core.timelib import parse_ts

    hours = int(UNHANDLED_ESCALATION_AGING_HOURS)
    target_text = _lane_env_alert_aged_action(hours)
    now = datetime.now(timezone.utc)
    aged_ids = []
    for rec in store.read_all():
        if not _lane_env_alert_inflight(rec) or not rec.get("id"):
            continue
        created = parse_ts(rec.get("created") or "")
        if created is None:
            continue  # 龄期不可判 → 跳过（不虚报）
        if created.tzinfo is None:
            created = created.astimezone()  # parse_ts naive 按本地时区解读
        age_hours = (now - created).total_seconds() / 3600.0
        if age_hours < hours:
            continue  # 未超龄：保持原文
        if rec.get("recommended_action") == target_text:
            continue  # 已升级：幂等零写（不重复改写/计数）
        aged_ids.append(str(rec.get("id")))
    if not aged_ids:
        return 0

    def _upgrade(records: list) -> bool:
        changed = False
        for rec in records:
            if str(rec.get("id")) not in aged_ids:
                continue
            if rec.get("recommended_action") != target_text:
                rec["recommended_action"] = target_text
                changed = True
        return changed

    store.update_records(_upgrade)
    return len(aged_ids)


def ensure_lane_env_alert(
    project_root, logger=None, reasons=None, origin: str = "preflight"
) -> None:
    """unhealthy 时发「车道环境不可用」告警（同一 unhealthy 周期单发）。

    dedup_key 命中在案未处理条目即零写跳过（单发语义）；告警 fail-open
    ——AdminStore 故障只 WARNING，不阻断调用方（车道拦截/台账主流程
    不受影响）。

    evo-repair-lane-credential-probe-fix 1.3：写入后在案未处理告警若创建
    超 :data:`core.self_review.UNHANDLED_ESCALATION_AGING_HOURS`，经
    :meth:`AdminStore.update_records` 就地改写 ``recommended_action`` 为
    「需人工升级」话术（幂等；未超时保持原文；不新增告警类型/通道）。
    """
    try:
        from core.admin_store import AdminStore

        store = AdminStore(Path(project_root), logger)
        reason_text = "；".join(str(r) for r in (reasons or ()))[:800] or (
            "探针结论 unhealthy（原因明细见车道日志）"
        )
        store.append_if_absent(
            {
                "kind": ESCALATION_KIND,
                "signal_type": LANE_ENV_ALERT_SIGNAL,
                "dedup_key": LANE_ENV_DEDUP_KEY,
                "spec": None,
                "severity": "major",
                "description": (
                    "arbiter/repair 车道环境不可用——裁决派发将以前置自检"
                    "拦截（零状态变更跳过）或 infra 通道分级（不烧死人开关"
                    "资格），直至环境修复探针转 healthy（本告警自动关闭）"
                ),
                "evidence": f"origin={origin}; reasons={reason_text}",
                "action_taken": (
                    "车道前置自检拦截/infra 分级已生效，未升级人工（资格保留）"
                ),
                "recommended_action": (
                    "修复车道环境（CLI 安装/PATH、provider 凭据路由/模型链"
                    "配置）后探针转 healthy 即自动恢复自主处置；本告警随"
                    "恢复自动关闭，无需人工处置"
                ),
            },
            _lane_env_alert_inflight,
        )
        # 单发命中不更新既有条目：超龄话术切换走就地改写（幂等）
        _upgrade_lane_env_alert_aging(store)
    except Exception as e:
        if logger is not None:
            try:
                logger.warning(
                    "agent_runner",
                    f"车道环境告警写入失败（fail-open）: {e}",
                )
            except Exception:
                pass


def resolve_lane_env_alert(project_root, logger=None, note: str = "") -> int:
    """探针转 healthy 时自动关闭在案未处理的「车道环境不可用」告警。

    按 signal_type+dedup_key 匹配未处理 escalation 条目（不含人工已处理
    ——auto_resolve 自带 handled 跳过），经 AdminStore.auto_resolve 收口
    （handled_by=auto-resolve，条件族自动闭环口径）。无匹配零写回（mtime
    不变）。fail-open：返回 0。
    """
    try:
        from core.admin_store import AdminStore

        store = AdminStore(Path(project_root), logger)
        ids = [
            str(rec.get("id"))
            for rec in store.read_all()
            if _lane_env_alert_inflight(rec) and not rec.get("handled")
            and rec.get("id")
        ]
        if not ids:
            return 0
        return store.auto_resolve(
            [
                {
                    "id": alert_id,
                    "resolve_note": note
                    or "车道前置探针转 healthy（CLI 可达 + 凭据路由可解析），"
                    "环境恢复，告警自动关闭",
                }
                for alert_id in ids
            ]
        )
    except Exception as e:
        if logger is not None:
            try:
                logger.warning(
                    "agent_runner",
                    f"车道环境告警自动关闭失败（fail-open）: {e}",
                )
            except Exception:
                pass
        return 0


# ── 「回落角色冻结」告警生命周期（provider-fallback-dispatch-gate 1.2）──
# 单发（同一角色的冻结周期只发一条，dedup_key 按角色判据）+ 后续命中
# bump 既有条目 hit_count（spec：更新该告警计数而非新建）+ 解冻自动关闭
# （verdict ok / 显式链分配 / 放行键打开时 resolve）。直写 AdminStore 不
# 入处置链（同 ensure_lane_env_alert 先例：链无法处置自己车道的死讯）。

PROVIDER_FALLBACK_ALERT_SIGNAL = "provider_fallback_frozen"


def provider_fallback_dedup_key(role: str) -> str:
    """回落冻结告警 dedup_key（按角色去重的单发判据）。"""
    return f"provider-fallback-frozen-{role}"


def _provider_fallback_alert_inflight(rec: dict, role: str) -> bool:
    # 同型口径见 _lane_env_alert_inflight（not handled 判据）
    return (
        rec.get("kind") == ESCALATION_KIND
        and rec.get("signal_type") == PROVIDER_FALLBACK_ALERT_SIGNAL
        and rec.get("dedup_key") == provider_fallback_dedup_key(role)
        and not rec.get("handled")
    )


def ensure_provider_fallback_alert(
    project_root,
    logger=None,
    role: str = "",
    chain_desc: str = "",
    verdict: str = "",
) -> None:
    """回落冻结拦截时维护「角色回落冻结」告警（单发 + 命中计数）。

    在案未处理条目存在 → ``update_records`` bump ``hit_count`` 并刷新
    evidence 尾部 last_hit（不新建——spec：后续命中更新该告警计数而非
    新建）；不存在 → ``append_if_absent`` 新建（hit_count=1）。告警文案
    含角色名与回落链描述。fail-open：AdminStore 故障只 WARNING，不阻断
    冻结拦截主流程。
    """
    try:
        from core.admin_store import AdminStore

        store = AdminStore(Path(project_root), logger)
        inflight = [
            rec for rec in store.read_all()
            if _provider_fallback_alert_inflight(rec, role) and rec.get("id")
        ]
        if inflight:
            alert_id = str(inflight[0].get("id"))

            def bump(records: list) -> bool:
                for rec in records:
                    if str(rec.get("id")) != alert_id:
                        continue
                    try:
                        cur = int(rec.get("hit_count") or 0)
                    except (TypeError, ValueError):
                        cur = 0
                    rec["hit_count"] = cur + 1
                    # bump 只替换末段 last_hit：按首个 '; last_hit=' 切段
                    # 取首段（历史多段形态幂等），保留原始现场；对 base
                    # 先截到 900 - len(last_hit) 再拼接（保尾不保头），
                    # 最新 last_hit 恒完整，总长不超 900 上限。
                    last_hit = (
                        f"; last_hit={role} verdict={verdict} {chain_desc}"
                    )
                    base = str(rec.get("evidence") or "").partition(
                        "; last_hit="
                    )[0][: max(0, 900 - len(last_hit))]
                    rec["evidence"] = base + last_hit
                    return True
                return False

            store.update_records(bump)
            return
        store.append_if_absent(
            {
                "kind": ESCALATION_KIND,
                "signal_type": PROVIDER_FALLBACK_ALERT_SIGNAL,
                "dedup_key": provider_fallback_dedup_key(role),
                "spec": None,
                "severity": "major",
                "description": (
                    f"{role} 角色回落 harness 默认链且凭据不可用/不可判定"
                    "——首派发已被回落冻结闸拦截（不产生秒挂 run），直至"
                    "默认链凭据可判定可用/该角色分配显式链/显式放行键打开"
                    "（本告警随解冻自动关闭）"
                ),
                "evidence": (
                    f"role={role}; verdict={verdict}; fallback_chain={chain_desc}"
                )[:900],
                "hit_count": 1,
                "action_taken": "回落冻结闸已拦截首派发并维护本单条告警",
                "recommended_action": (
                    "修复 harness 默认链凭据（或为该角色分配显式 provider 链）"
                    "即自动解冻；确认回落形态合法可配置 "
                    "agents.allow_harness_default_fallback=true 显式放行"
                ),
            },
            lambda rec: _provider_fallback_alert_inflight(rec, role),
        )
    except Exception as e:
        if logger is not None:
            try:
                logger.warning(
                    "agent_runner",
                    f"回落冻结告警写入失败（fail-open）: {e}",
                )
            except Exception:
                pass


def resolve_provider_fallback_alert(
    project_root, logger=None, role: str = "", note: str = ""
) -> int:
    """解冻时自动关闭该角色在案未处理的「回落冻结」告警。

    按 signal_type+dedup_key(role) 匹配未处理条目经 AdminStore.auto_resolve
    收口（handled_by=auto-resolve）。无匹配零写回（mtime 不变）。fail-open
    ：返回 0。
    """
    try:
        from core.admin_store import AdminStore

        store = AdminStore(Path(project_root), logger)
        ids = [
            str(rec.get("id"))
            for rec in store.read_all()
            if _provider_fallback_alert_inflight(rec, role) and rec.get("id")
        ]
        if not ids:
            return 0
        return store.auto_resolve(
            [
                {
                    "id": alert_id,
                    "resolve_note": note
                    or f"{role} 回落冻结解除（默认链凭据可判定可用/显式链"
                    "已分配/放行键打开），闸放行，告警自动关闭",
                }
                for alert_id in ids
            ]
        )
    except Exception as e:
        if logger is not None:
            try:
                logger.warning(
                    "agent_runner",
                    f"回落冻结告警自动关闭失败（fail-open）: {e}",
                )
            except Exception:
                pass
        return 0


__all__ = [
    "DEFAULT_CHAIN_TRIAL_PROMPT",
    "DEFAULT_CHAIN_TRIAL_TTL_S",
    "FALLBACK_VERDICT_INDETERMINABLE",
    "FALLBACK_VERDICT_MISSING",
    "FALLBACK_VERDICT_OK",
    "LANE_ENV_ALERT_SIGNAL",
    "LANE_INFRA_FINGERPRINTS",
    "LANE_STEADY_EVENT_EDGE",
    "LANE_STEADY_EVENT_HEARTBEAT",
    "LANE_STEADY_HEARTBEAT_INTERVAL_S",
    "PROBE_HEALTH_TIMEOUT_S",
    "PROBE_LANE_ROLES",
    "PROVIDER_FALLBACK_ALERT_SIGNAL",
    "LaneHealth",
    "LanePreflightCache",
    "classify_lane_failure",
    "ensure_lane_env_alert",
    "ensure_provider_fallback_alert",
    "lane_env_alert_suppressed_by_steady",
    "mark_lane_env_alert_registered",
    "observe_lane_conclusion",
    "probe_default_chain_credentials",
    "probe_lane_health",
    "provider_fallback_dedup_key",
    "reset_default_chain_trial_cache",
    "reset_lane_steady_state",
    "resolve_lane_env_alert",
    "resolve_provider_fallback_alert",
]
