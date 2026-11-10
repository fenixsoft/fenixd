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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

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
#: 角色走默认网关/通道自身配置，本地无可判凭据，跳过不报）。
PROBE_LANE_ROLES = ("arbiter", "repair")


@dataclass(frozen=True)
class LaneHealth:
    """探针结论：``ok``=两级检查全过；``reasons``=失败原因清单（可诊断文案）。"""

    ok: bool
    reasons: List[str] = field(default_factory=list)


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
    failover 只用链首选直连）；纯本地检查，MUST NOT 真发 API 请求。无显
    式链（默认网关/通道自身配置形态）本地无可判对象，跳过不报。

    任一级失败 → ``ok=False`` + reasons。探针自身异常按 unhealthy 处置
    并 WARNING（logger 在场时），不抛出、不阻塞调用方。
    """
    reasons: List[str] = []
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
            chain = ConfigLoader.get_agent_model_assignment(config or {}, role)
            if not chain:
                continue  # 未分配显式链：默认网关/通道自身配置，无可判对象
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
        reasons.append(f"凭据路由解析异常: {type(e).__name__}: {e}")
    health = LaneHealth(ok=not reasons, reasons=reasons)
    if not health.ok and logger is not None:
        try:
            logger.warning(
                "agent_runner",
                "车道前置探针 unhealthy: " + "；".join(reasons)[:600],
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
        for fingerprint in LANE_INFRA_FINGERPRINTS:
            if fingerprint in haystack:
                return "infra"
    return "judgment"


class LanePreflightCache:
    """探针结论 TTL 缓存（派发前置复用，超时重探）。

    TTL 内多次派发只探一次（S4）；TTL 过期首查重探。``invalidate`` 供
    外部强制失效（测试/热更新场景）。线程安全（arbiter 单飞 worker 与
    主循环周期探针可能并发取用）。
    """

    def __init__(self, ttl_s: float = 300.0):
        self._ttl_s = max(0.0, float(ttl_s))
        self._health: Optional[LaneHealth] = None
        self._probed_at: float = 0.0

    def get_or_probe(self, config, logger=None) -> LaneHealth:
        """TTL 内返回缓存结论；过期/无缓存时探一次并缓存。"""
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
        self._health = None
        self._probed_at = 0.0

    @property
    def ttl_s(self) -> float:
        return self._ttl_s


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


def ensure_lane_env_alert(
    project_root, logger=None, reasons=None, origin: str = "preflight"
) -> None:
    """unhealthy 时发「车道环境不可用」告警（同一 unhealthy 周期单发）。

    dedup_key 命中在案未处理条目即零写跳过（单发语义）；告警 fail-open
    ——AdminStore 故障只 WARNING，不阻断调用方（车道拦截/台账主流程
    不受影响）。
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


__all__ = [
    "LANE_ENV_ALERT_SIGNAL",
    "LANE_INFRA_FINGERPRINTS",
    "PROBE_HEALTH_TIMEOUT_S",
    "PROBE_LANE_ROLES",
    "LaneHealth",
    "LanePreflightCache",
    "classify_lane_failure",
    "ensure_lane_env_alert",
    "probe_lane_health",
    "resolve_lane_env_alert",
]
