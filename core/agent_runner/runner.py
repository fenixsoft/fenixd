"""
runner.py — AgentRunner 门面（Agent execution engine for fenixd）.

Spawns claude CLI subprocesses to run implementer and verifier Agents.
Handles result parsing, retry logic, and token/turn budget control.
"""

import json
import os
import functools
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from core.agent_runner.prompt_builder import (
    PromptBuilder,
    spec_review_result_path,
    spec_review_result_status_whitelist,
)

# fix-verdict-read-failclosed D2（新鲜度宽限）与 add-planready-artifact-gate D2
# （planner-plan status 白名单）的常量定义随消费者迁 core/agent_runner/result_gate.py
# （D2b 规则 3），此处 re-export 保持既有导入路径与补丁缝隙（D6）。
from core.agent_runner.result_gate import (  # noqa: F401
    AgentArtifactGateError,
    AdminDisposition,
    AgentRunResult,
    EvolutionResult,
    RunCancelledError,
    SelfReviewResult,
    _ARTIFACT_FRESHNESS_GRACE_SECONDS,
    _PLANREADY_STATUSES,
    _append_crosscheck_skipped,
    _check_agent_result_artifact,
    _check_artifact_json_file,
    _check_impl_result_artifact,
    _check_partial_consistency,
    _check_success_completion,
    _check_taskupdate_crosscheck,
    _format_gap_list,
    _invalid_completed_ids,
    _read_init_tools,
    classify_and_enrich_artifact_error,
    salvage_result_from_transcript,
)
# run 级 API 延迟统计纯函数与常量迁 core/agent_runner/latency.py（D4），
# re-export 维持 bin/analyze_run_latency.py / tests/test_run_latency_stats.py 的
# 既有导入路径（D6）；`_default_ts_parser` 在 runner.py 保留一行委托（见下）。
from core.agent_runner.latency import (  # noqa: F401
    LATENCY_STALL_SECONDS,
    _default_ts_parser as _latency_default_ts_parser,
    _entry_is_tool_result,
    _percentile,
    format_latency_summary,
    iter_events,
    latency_samples_from_events,
    latency_stats,
)
from core.agent_runner.liveness import (
    AGENT_TERMINATE_GRACE_SECONDS,
    LIVE_ATTEMPT_STREAM_WINDOW_SECONDS,
    LivenessSupervisor,
)
from core.agent_runner.session import SessionTracker
from core.agent_runner.provider_circuit import (
    PROVIDER_CIRCUIT_4XX,
    PROVIDER_CIRCUIT_COOLDOWN_SECONDS,
    PROVIDER_CIRCUIT_THRESHOLD,
    PROVIDER_CIRCUIT_WINDOW_SECONDS,
    PROVIDER_DAILY_ATTEMPTS_WARN,
    PROVIDER_SWITCH_COOLDOWN_SECONDS,
    ProviderCircuit,
)
from core.agent_runner.run_files import (
    archive_spec_runs,
    append_run_error,
    append_run_line,
    run_spec_part,
)
from core.agent_runner.token_budget import TokenAccountant
from core.agent_runner.v2_server import V2ServerManager
from core.wip_checkpoint import (
    ANCHOR_EXTENSION_TAIL,
    ANCHOR_TRANSIENT_BACKOFF,
    ANCHOR_TURN_LIMIT,
    commit_wip_checkpoint,
)


# DEFAULT_GATEWAY_MODEL 随 _get_admin_model 迁 maintenance_runs.py（D2b 规则 3），
# re-export 保持内部使用点与既有导入路径；维护型 run 实现同迁，此处一行委托。
from core.agent_runner.maintenance_runs import (
    ADMIN_DISPOSITION_GLOB,
    ADMIN_DISPOSITION_PREFIX,
    DEFAULT_GATEWAY_MODEL,
    _accumulate_evolution_tokens,
    _accumulate_self_review_tokens,
    _clear_admin_disposition,
    _clear_self_review_out,
    _delete_admin_disposition,
    _delete_evolution_out,
    _delete_self_review_out,
    _get_admin_model,
    _read_admin_disposition,
    _read_self_review_out,
    admin_disposition_path,
    run_administrator,
    run_evolution,
    run_self_review,
)

# ── 路由地图生成（add-planner-efficiency：planner-route-map）─────────────
# 项目声明生成器协议（design D1）：
# - 生成器位于项目根 `bin/gen-route-map.py`（worktree 内，随 impl 分支入库）；
# - 框架以 worktree 为 cwd、单参（worktree 根）调用，stdout 为人类可读
#   Markdown（条目含 `文件:行号` 出处），超时默认 60s；
# - 非零退出/超时/缺生成器 = 失败 fail-open：不阻塞验证管线，记 warning
#   （planner 回退逐轮 grep 现状）。
# - 产物 `<worktree>/.fenix/route-map.md` 以 worktree HEAD 为复用键：
#   HEAD 未变（replan 循环/重验）跳过生成器；HEAD 变更重新生成。
ROUTE_MAP_TIMEOUT_SECONDS = 60
ROUTE_MAP_REL = ".fenix/route-map.md"
ROUTE_MAP_HEAD_MARKER_REL = ".fenix/.route-map-head"
ROUTE_MAP_GENERATOR_REL = "bin/gen-route-map.py"

# ── 派发拦截 error 文案常量（fix-verdict-retry-misattribution D3）────────
# frozen 门 error 文案与 verification.py 的 frozen 判定共用此导出常量（防文案
# 改动使匹配失效）；取消旗标路径沿用 AgentRunResult.cancelled 结构化字段（非
# 字符串匹配），其 error 前缀同样抽为常量以便统改。对外文案与常量抽取前逐字一致。
FROZEN_TERMINATED_ERROR_PREFIX = "spec frozen"
CANCELLED_BY_ADMIN_ERROR_PREFIX = "cancelled by admin"

# 原地重试让位失败的前缀标记（fix-verdict-dedup-resynthesis D4）：重派前状态
# 复查命中（status 迁出本 agent 预期态 / frozen / _cancelled_hold）时返回的
# 语义化失败 error 以此标记开头，消费侧（verification.py 重试派发三分支外的
# 其它失败分支）按温和处置识别为「人工接管让位」而非网关故障。
RETRY_YIELDED_ERROR_PREFIX = "[retry-yielded]"

# agent_type → spec 预期态（fix-verdict-dedup-resynthesis D4）：该 agent 正在
# 跑时 spec 应处于此态；被人工接管（status 迁移/blocked/frozen 等）后，退避
# 结束的原地重派必须让位（19:48 事故 $4.77 白烧的直接原因）。未列出的
# agent_type 不做 status 判定（保持现状重试语义，fail-open）。
EXPECTED_SPEC_STATUS_BY_AGENT = {
    "implementer": "implementing",
    "fast-track": "implementing",
    "repair": "implementing",
    "planner-judge": "testing",
    "verifier": "testing",
}

# evo-verifier-result-single-source：agent_type → 主树共享文件 role 戳映射。
# _execute_agent 拷回 worktree 根 .fenix-run-result.json 到主树共享
# .fenix/.fenix-run-result.json 时按此注入 role 与 spec 戳，供裁决读侧
# （pm_engine._read_verdict）隔离 implementer 残留（role≠verifier 一律不
# 采信）；未列出的 agent_type（无结果文件契约，如 dispute-judge）不注入
# role 兜底。role 取值 = 实际写者全集：implementer | verifier | planner |
# judge | repair（fast-track 属 implementer 变体，语义同 implementer）。
AGENT_TYPE_TO_ROLE = {
    "implementer": "implementer",
    "fast-track": "implementer",
    "verifier": "verifier",
    "planner-plan": "planner",
    "planner-judge": "judge",
    "repair": "repair",
}

# ── planner 生成节流（add-planner-efficiency：planner-generation-throttle）──
# 配置键 `verify.planner_max_concurrent`：0/缺省=不节流（现状）；正整数=跨
# verify 管线的 planner 阶段级并发上限。信号量在 `run_planner` 入口（design
# D2：全部 planner 路径——完整管线+fast-track+重排——的单一咽喉），一处包裹
# 全覆盖；取消/异常经 try/finally 释放不泄漏。按配置惰性重建（热更新生效）。
#
# 模块级状态（进程内全局）：
# - 多 run 并发（worker 池）共享同一信号量，节流语义是「全框架同时在出题的
#   planner 数」，与派发层 agents.max_concurrent 语义正交（本限制是管线内
#   新增的第二道门，不动 parallelism-config/priority-parallel-scheduler）。
# - 配置读取走 AgentRunner._get_config（每次现读），重建只在上限值变化时发生；
#   值为 0/缺省时信号量为 None（不节流路径零开销）。
_PLANNER_SEMAPHORE: threading.BoundedSemaphore | None = None
_PLANNER_SEMAPHORE_LIMIT: int = 0
_PLANNER_SEMAPHORE_LOCK = threading.Lock()
# 排队等待保活事件节流：每秒至多写一次 throttled-wait（run 流保持新鲜，
# 防 recovery watch 把「已派发、在持槽等待」误判为 stuck/dispatch_stalled）。
THROTTLED_WAIT_HEARTBEAT_SECONDS = 60.0


def _route_map_head(wt_path: Path, logger) -> str:
    """读取 worktree 当前 HEAD（git rev-parse），失败返回空串（不阻断生成）。"""
    try:
        res = subprocess.run(
            ["git", "-C", str(wt_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except subprocess.SubprocessError:
        pass
    return ""


def ensure_route_map(wt_path: Path, project_root: Path, logger,
                     timeout: float | None = None) -> Path | None:
    """生成/复用 `<wt_path>/.fenix/route-map.md`（HEAD 键控、fail-open）。

    add-planner-efficiency（planner-route-map D1）。以 impl worktree（非主树）
    为源执行项目声明生成器 `bin/gen-route-map.py`（worktree 为 cwd、单参
    worktree 根），产物供 planner prompt 注入（已知入口索引、非穷尽清单）。

    - 无生成器 → None（fail-open，planner 逐轮 grep 现状）；
    - worktree HEAD 未变且地图已在（.route-map-head 标记一致）→ 复用，
      不重复执行生成器；
    - 生成器非零退出/超时/异常 → warning + None（不阻塞验证管线）。

    Args:
        wt_path: impl worktree 根（生成器发现与执行上下文）。
        project_root: 主项目根（预留；可被生成器用于感知主树）。
        logger: 日志器（component=agent_runner）。
        timeout: 生成器单次执行超时（缺省 ROUTE_MAP_TIMEOUT_SECONDS=60s）。

    Returns:
        地图文件路径（存在/生成成功）或 None（fail-open 无地图）。
    """
    timeout = timeout or ROUTE_MAP_TIMEOUT_SECONDS
    generator = Path(wt_path) / ROUTE_MAP_GENERATOR_REL
    if not generator.is_file():
        logger.debug(
            "agent_runner",
            f"route-map: 项目未声明生成器 {ROUTE_MAP_GENERATOR_REL} — fail-open",
        )
        return None
    out = Path(wt_path) / ROUTE_MAP_REL
    marker = Path(wt_path) / ROUTE_MAP_HEAD_MARKER_REL
    head = _route_map_head(wt_path, logger)
    # HEAD 键控复用：地图与 HEAD 标记同时存在且标记 == 当前 HEAD → 跳过生成器
    if head and out.is_file() and marker.is_file():
        try:
            if marker.read_text(encoding="utf-8").strip() == head:
                logger.debug("agent_runner", f"route-map: HEAD 未变复用 {out}")
                return out
        except OSError:
            pass
    try:
        result = subprocess.run(
            [sys.executable, str(generator), str(wt_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(wt_path),
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "agent_runner",
            f"route-map 生成器超时（>{int(timeout)}s）— fail-open: {generator}",
        )
        return None
    if result.returncode != 0:
        logger.warning(
            "agent_runner",
            f"route-map 生成器失败（exit={result.returncode}）— fail-open: "
            f"{generator}\n{(result.stderr or '').strip()[:300]}",
        )
        return None
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.stdout, encoding="utf-8")
        if head:
            marker.write_text(head, encoding="utf-8")
    except OSError as e:
        logger.warning("agent_runner", f"route-map 写入失败（fail-open）: {e}")
        return None
    logger.info(
        "agent_runner",
        f"route-map 生成完成: {out}（{len(result.stdout)} 字节, "
        f"HEAD={head[:12] or 'unknown'}）",
    )
    return out

# ── V2 测试服务器（add-worktree-test-server）────────────────────────────
# per-run 隔离测试服务的端口分配基数，范围 [V2_TEST_PORT_BASE, V2_TEST_PORT_BASE+19]
# 主服务 8787 排除在外，并发运行（并行度 2，预留余量取 20 个高位端口段）不冲突。
V2_TEST_PORT_BASE = 19000
V2_TEST_PORT_RANGE = 20
V2_DEV_SERVER_MARKER = "fenix-v2-dev-server"

# ── 轮次上限活性感知续期（add-turn-limit-anchor-c design D2）────────────────
# 轮询环判定 run 触达 max_turns 上限时，按封闭决策矩阵（分支提交活性 / 尾部
# 窗口 tool_result 流量活性）判定续期或终止——有活性且续期未达封顶 → extend
# 上限量；无活性或封顶 → kill + 锚点 C 收口。机制与超时路径
# _supervision_deadline_action（improve-run-lifecycle-governance D3）同构。
# 参数依据（design D2）：每次续期步长 = max_turns 的 25%（400 → +100 轮），
# 封顶 2 次（理论最大 600 轮）——保守取值：无活性 run 一次都续不到，最坏墙钟
# 增幅 = 200 轮 ≈ +26-42min，仅对真活性 run 发生。配置常量落模块级（不进
# config.yaml，参照 AGENT_TERMINATE_GRACE_SECONDS 先例——框架生命周期内部
# 治理参数，后续有需求再暴露配置）。活性判定窗口复用延迟采样口径（60s）。
TURN_EXTENSION_STEP_FRACTION = 0.25
TURN_EXTENSION_MAX = 2
TURN_EXTENSION_WINDOW_SECONDS = 60.0

# ── extension 末位自动保全（add-fast-track-scale-precheck D3）────────────────
# fast-track 超时预算用尽前（extension #2 收尾前）自动触发一次 WIP checkpoint
# 保全：已完成轮次的工作不随超时无保全作废。触发条件为『extension 末位窗口』
# ——run 剩余时间进入该提前量（supervision deadline - now < 该值）判定进入末位，
# 先调 commit_wip_checkpoint（消息契约 fenix(wip): checkpoint extension-tail <spec>）
# 再走既有超时收口。提前量取值 30min：与 SUPERVISION_DEFAULTS 的单次续期
# extension_seconds=1800 对齐（proposal「如剩余时间窗口 <30min」），末位窗口恰好
# 覆盖最后一个 extension 的收尾段。配置常量落模块级（不进 config.yaml，参照
# TURN_EXTENSION_WINDOW_SECONDS 先例——框架生命周期内部治理参数）。
EXTENSION_TAIL_WINDOW_SECONDS = 1800.0

def _default_ts_parser(entry: dict):
    """默认 timestamp 解析器：委托 core.agent_runner.latency 实现（D4）。"""
    return _latency_default_ts_parser(entry)


@dataclass
class _AttemptState:
    """attempt 周期共享状态对象（design D3）。

    承载 `_execute_agent_inner` 内跨块共享的局部标量，替代「十几个标量的
    隐式元组」直接传参。逐字段映射原局部变量读写点，MUST NOT 改变读写
    顺序或作用域（等价搬移）；状态对象生命周期限于本函数（attempt 循环
    期间），MUST NOT 提升为实例属性（避免跨 run 泄漏）。
    """

    # 当前 attempt 使用的 worktree 路径（读 53 次，最高频共享标量）
    wt_path: Optional[Path] = None
    # 本轮候选 provider 名（链选择前 None，供 frozen 提前返回使用）
    provider_name: Optional[str] = None
    # 当前模型名
    model: Optional[str] = None
    # 实例级链指针（design D1：cursor 按 agent_type 记忆）。-1 表示尚未选定
    chain_cursor: int = -1
    # session_id 所属 provider（None=默认网关）
    session_id: Optional[str] = None
    session_provider: Optional[str] = None
    # 本 attempt 已原地重试次数（预算 = 退避序列长度）
    transient_retries: int = 0
    # 连续 resume 失败次数（≥2 后本次 attempt 改全新会话）
    resume_failures: int = 0
    # worktree-reuse：fast-track 终态失败保留的复用遗产路径
    kept_wt_path: Optional[Path] = None
    # add-run-cancel D3/D5：本轮 run 是否被人工取消
    cancelled_flag: bool = False
    cancel_reason: str = ""
    # shutdown-interrupted 守卫（2026-09-09 事故）
    shutdown_interrupted: bool = False
    # run 终态指标落盘需 usage_info（早夭分支引用前初始化，unobserved 语义）
    usage_info: dict = field(default_factory=dict)
    # 同上：预检早夭分支无 turns 值，统一顶部初始化
    turns: int = 0
    # 用于 "provider switched" 跨 attempt 打点
    last_provider_used: Optional[str] = None


class AgentRunner:
    """
    Execute Agents via claude CLI subprocess.

    Manages retry logic, run limits, and result tracking.
    """

    # shutdown 守卫信号（shutdown-interrupted guard）：daemon 关停入口置位
    # （fenixd.shutdown），时序上早于一切子进程 SIGTERM——attempt 循环失败分支
    # 据此把「框架主动终止」与「网关瞬断」区分开。类属性缺省 False：绕过
    # __init__ 的测试构造（__new__）无需逐处补默认。
    shutting_down = False

    # ── 门面转发注册表（refactor-facade-delegation D2 / facade-inventory.md）──
    # 实例式转发（52 个）：{门面方法名: (子对象属性名, 目标方法名)} 或
    # {门面方法名: self 首参模块函数}。子对象属性为惰性 property（`_liveness`
    # 等，正常查找命中不触发 `__getattr__`），经 `getattr(self, 子对象属性名)`
    # 触发惰性构造；`__getattr__` 返回 `getattr(子对象, 目标方法名)`/partial。
    # 注册表以源码内联 dict 声明（静态可读）；未知名 MUST `raise AttributeError`
    # （hasattr/getattr(..., default) 语义正确）；dunder 名 MUST NOT 转发。
    _FORWARDER_REGISTRY: dict[str, object] = {
        "_build_prompt": ("_prompt_builder", "_build_prompt"),
        "_build_legacy_section": ("_prompt_builder", "_build_legacy_section"),
        "_legacy_dirty_snapshot": ("_prompt_builder", "_legacy_dirty_snapshot"),
        "_scenario_freeze_section": ("_prompt_builder", "_scenario_freeze_section"),
        "_interaction_contract_section": ("_prompt_builder", "_interaction_contract_section"),
        "_triage_recheck_section": ("_prompt_builder", "_triage_recheck_section"),
        "_verdict_rejection_section": ("_prompt_builder", "_verdict_rejection_section"),
        "_circuit_state": ("_provider_circuit", "_circuit_state"),
        "is_circuit_open": ("_provider_circuit", "is_circuit_open"),
        "is_switch_cooldown": ("_provider_circuit", "is_switch_cooldown"),
        "_record_switch_cooldown": ("_provider_circuit", "_record_switch_cooldown"),
        "_write_provider_marker": ("_provider_circuit", "_write_provider_marker"),
        "_record_daily_provider_attempt": ("_provider_circuit", "_record_daily_provider_attempt"),
        "_circuit_open_error": ("_provider_circuit", "_circuit_open_error"),
        "_record_provider_4xx": ("_provider_circuit", "_record_provider_4xx"),
        "_record_provider_probe": ("_provider_circuit", "_record_provider_probe"),
        "record_transient_break": ("_provider_circuit", "record_transient_error"),
        "is_global_transient_break_active": ("_provider_circuit", "is_global_transient_break"),
        "is_signal_kill_cooldown": ("_provider_circuit", "is_signal_kill_cooldown"),
        "signal_kill_cooldown_until": ("_provider_circuit", "signal_kill_cooldown_until"),
        "_signal_kill_counts": ("_provider_circuit", "signal_kill_counts"),
        "_record_signal_kill": ("_provider_circuit", "record_signal_kill"),
        "_accumulate_token_usage": ("_token_accountant", "_accumulate_token_usage"),
        "_check_token_budget": ("_token_accountant", "_check_token_budget"),
        "_send_token_alert": ("_token_accountant", "_send_token_alert"),
        "_record_verify_progress_tokens": ("_token_accountant", "_record_verify_progress_tokens"),
        "_v2_ensure_state": ("_v2_server", "_v2_ensure_state"),
        "_v2_launch_for_worktree": ("_v2_server", "_v2_launch_for_worktree"),
        "_v2_inject_env": ("_v2_server", "_v2_inject_env"),
        "_v2_stop_for_worktree": ("_v2_server", "_v2_stop_for_worktree"),
        "_v2_stop_all": ("_v2_server", "_v2_stop_all"),
        "has_live_attempt": ("_liveness", "has_live_attempt"),
        "sweep_dangling_runs": ("_liveness", "sweep_dangling_runs"),
        "_pgrep_live_attempt": ("_liveness", "_pgrep_live_attempt"),
        "_stream_recent": ("_liveness", "_stream_recent"),
        "note_run_extension": ("_liveness", "note_run_extension"),
        "get_extension_baseline": ("_liveness", "get_extension_baseline"),
        "_liveness_snapshot": ("_liveness", "_liveness_snapshot"),
        "_judge_liveness": ("_liveness", "_judge_liveness"),
        "_supervision_settings": ("_liveness", "_supervision_settings"),
        "_supervision_judge_timeout": ("_liveness", "_supervision_judge_timeout"),
        "_supervision_deadline_action": ("_liveness", "_supervision_deadline_action"),
        "wait_for_running_agents": ("_liveness", "wait_for_running_agents"),
        "run_administrator": run_administrator,
        "run_self_review": run_self_review,
        "run_evolution": run_evolution,
        "_get_admin_model": _get_admin_model,
        "_check_agent_result_artifact": _check_agent_result_artifact,
        "_check_impl_result_artifact": _check_impl_result_artifact,
        "_check_success_completion": _check_success_completion,
        "_check_partial_consistency": _check_partial_consistency,
        "_check_taskupdate_crosscheck": _check_taskupdate_crosscheck,    }

    def __getattr__(self, name: str):
        """门面转发统一委托（refactor-facade-delegation D1/D2）。

        注册表内实例式转发经此解析；未知名 / dunder 名 `raise AttributeError`。
        惰性 property（`_liveness` 等）是类属性，正常查找命中，不会走到这里。"""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}")
        target = type(self)._FORWARDER_REGISTRY.get(name)
        if target is None:
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}")
        if isinstance(target, tuple):
            sub_attr, meth = target
            return getattr(getattr(self, sub_attr), meth)
        return functools.partial(target, self)

    def __dir__(self):
        """IDE 补全增强（refactor-facade-delegation Open Question / tasks 5.1）：
        返回既有属性 + 注册表键，缓解 `__getattr__` 委托下 dir() 不显示转发名。"""
        return sorted(set(super().__dir__()) | set(type(self)._FORWARDER_REGISTRY))


    # ── 静态式转发类级别名（refactor-facade-delegation D7 / tasks 3.3）──
    # 首参非 self 的 @staticmethod 式转发（12 个）与目标不以 self 为首参的
    # 模块函数转发（3 个：_read_admin_disposition / _read_self_review_out /
    # _check_artifact_json_file）MUST NOT 走实例 __getattr__ 的 partial 路径
    # （partial 会多注一个 self → TypeError）；以类级别名保留 `Cls.<名>` 与
    # `self.<名>` 两条解析路径（staticmethod 描述符经类/实例访问返回原函数，
    # 不重复签名、无 docstring，spec「双份签名不再存在」）。
    _entry_is_tool_result = staticmethod(_entry_is_tool_result)
    _format_gap_list = staticmethod(_format_gap_list)
    _invalid_completed_ids = staticmethod(_invalid_completed_ids)
    _read_init_tools = staticmethod(_read_init_tools)
    parse_api_error_status = staticmethod(ProviderCircuit.parse_api_error_status)
    classify_switch_error = staticmethod(ProviderCircuit.classify_switch_error)
    classify_transient_error = staticmethod(ProviderCircuit.classify_transient_error)
    _summarize_snapshot = staticmethod(LivenessSupervisor._summarize_snapshot)
    _parse_verdict_json = staticmethod(LivenessSupervisor._parse_verdict_json)
    _resumable_session_id = staticmethod(SessionTracker._resumable_session_id)
    _extract_session_id = staticmethod(SessionTracker._extract_session_id)
    _extract_usage_info = staticmethod(SessionTracker._extract_usage_info)
    # 目标不以 self 为首参（模块函数转发，非注入）
    _read_admin_disposition = staticmethod(_read_admin_disposition)
    _read_self_review_out = staticmethod(_read_self_review_out)
    _check_artifact_json_file = staticmethod(_check_artifact_json_file)

    def __init__(self, config: dict, worktree_manager, state_machine,
                 project_root: Path, logger):
        self.config = config
        self.worktree_manager = worktree_manager
        self.state_machine = state_machine
        self.project_root = project_root
        self.logger = logger

        # 在跑 agent 登记表（run_id → Popen）。跨线程共享（fix-admin-run-blocks-
        # mainloop tasks 4.4）：admin run 在 worker 池线程登记/摘除，主循环派发的
        # implementer/verifier 在主线程登记；liveness 监督与 shutdown 关停均以
        # list(...) 快照迭代、pop 带 default——全部单键原子操作，无读改写竞态，
        # 不加锁（持锁跨 grace 等待窗口反而引入死锁面）。
        # _daily_run_count 仅在 _execute_agent（implementer/verifier/planner）路径
        # 自增，admin run 不经过该路径，无跨线程写。
        self._running_agents: Dict[str, subprocess.Popen] = {}
        self._daily_run_count = 0
        # 人工取消旗标集合（add-run-cancel D1）：键为基础 run_id（已剥 -a<n>
        # attempt 后缀）。由 cancel_run 登记、_run_claude 轮询环/attempt 循环
        # 顶部消费、run 收尾清理。跨线程共享（dashboard/daemon 线程写、worker
        # 线程读），以独立锁保护。惰性 property（测试 __new__ 绕过 __init__）。
        self._cancel_requested = set()
        self._cancel_meta = {}
        self._cancel_requested_lock = threading.Lock()

    # ── 取消旗标惰性 property（add-run-cancel）────────────────────
    # 测试普遍以 ``AgentRunner.__new__`` 绕过 ``__init__`` 构造，沿用
    # _instant_fail 的惰性初始化模式：首次访问即时建态。

    @property
    def _cancel_requested(self) -> set:
        inst = self.__dict__.get("_cancel_requested_state")
        if inst is None:
            inst = set()
            self.__dict__["_cancel_requested_state"] = inst
        return inst

    @_cancel_requested.setter
    def _cancel_requested(self, value):
        self.__dict__["_cancel_requested_state"] = value

    @property
    def _cancel_meta(self) -> dict:
        inst = self.__dict__.get("_cancel_meta_state")
        if inst is None:
            inst = {}
            self.__dict__["_cancel_meta_state"] = inst
        return inst

    @_cancel_meta.setter
    def _cancel_meta(self, value):
        self.__dict__["_cancel_meta_state"] = value

    @property
    def _cancel_requested_lock(self) -> threading.Lock:
        inst = self.__dict__.get("_cancel_requested_lock_state")
        if inst is None:
            inst = threading.Lock()
            self.__dict__["_cancel_requested_lock_state"] = inst
        return inst

    @_cancel_requested_lock.setter
    def _cancel_requested_lock(self, value):
        self.__dict__["_cancel_requested_lock_state"] = value

    # ── run_id 归一化助手（add-run-cancel D1/D3）──────────────────

    @staticmethod
    def _normalize_run_id(run_id: str) -> str:
        """剥掉尾部连续多组 -a<n>（attempt）/ -r<n>（瞬态重试）后缀，返回基础 run_id。

        ``cancel_run`` 按基础 run_id 登记旗标，轮询环/attempt 循环按基础 run_id
        检查——两者使用同一归一化函数，保证匹配一致。瞬态重试子循环产生形如
        ``<base>-a1-r1`` 的在飞 run_id（fix-provider-transient-backoff），故归一化
        需连续剥离 ``-a<n>`` / ``-r<n>`` 任意组合（``(?:-a\\d+|-r\\d+)+$``），使
        登记键与两类消费点收敛到同一 base 键。无后缀时原样返回（幂等）。

        风险注释：spec 名若以 ``-a<n>``/``-r<n>`` 字面形态结尾会被多剥——与既有
        ``-a\\d+$`` 剥离同级风险，本项目 kebab-case spec 名无此形态（设计已登记）。
        """
        return re.sub(r"(?:-a\d+|-r\d+)+$", "", run_id)

    def _cancel_is_requested(self, base_run_id: str) -> bool:
        """base_run_id 是否命中取消旗标（锁内判定，幂等读）。

        入参先做同一归一化再精确匹配：消费点传入的键形态不一（attempt 循环顶
        传 run 级 id、轮询环传 attempt/子 run id，后者可能带 ``-r<n>`` 瞬态重试
        后缀），归一化后与 ``cancel_run`` 登记键收敛到同一 base 键。
        """
        base_run_id = self._normalize_run_id(base_run_id)
        with self._cancel_requested_lock:
            return base_run_id in self._cancel_requested

    def _cancel_clear(self, base_run_id: str) -> None:
        """run 收尾清理取消旗标（幂等，防泄漏）。"""
        with self._cancel_requested_lock:
            self._cancel_requested.discard(base_run_id)
            self._cancel_meta.pop(base_run_id, None)

    # ── 人工取消原语（add-run-cancel D1）─────────────────────────

    def cancel_run(self, run_id: str, reason: str = "", by: str = "admin") -> dict:
        """外部专用 run 粒度终止原语——登记取消旗标，由属主线程执行终止。

        **仅供外部管理动作调用**（dashboard API / 文件信号消费方）；状态机及
        一切自动链路（transition、recovery、stuck auto-recovery、gate、freeze）
        MUST NOT 调用本方法。

        本方法自身 MUST NOT 执行任何状态转换、MUST NOT 写任何 spec 的 status
        字段；终止动作由持有该 run 的 worker 线程在 _run_claude 轮询环内完成
        （调用线程不做跨线程 kill）。

        Returns:
            {"status": "cancel_requested", "attempts": [...], "base_run_id": str}
            — 命中活跃 attempt；
            {"status": "not_running", "base_run_id": str}
            — 未命中。
        """
        base_id = self._normalize_run_id(run_id)

        # 按基础 run_id 前缀匹配所有活跃 attempt
        matched_attempts = [
            aid for aid in list(self._running_agents.keys())
            if aid.startswith(base_id)
        ]

        if not matched_attempts:
            self.logger.info(
                "agent_runner",
                f"cancel_run: run '{base_id}' 无活跃 attempt，返回 not_running",
            )
            return {"status": "not_running", "base_run_id": base_id}

        # 登记旗标（幂等——同一 base_id 多次调用不重复计数）
        with self._cancel_requested_lock:
            self._cancel_requested.add(base_id)
            self._cancel_meta[base_id] = {"reason": reason, "by": by}

        self.logger.info(
            "agent_runner",
            f"cancel_run: 已登记取消旗标 '{base_id}'，命中活跃 attempt "
            f"{matched_attempts}（reason={reason!r}, by={by}）",
        )

        # minor 级审计（add-run-cancel D1 / spec「取消动作审计留痕」）
        try:
            from core.admin_store import AdminStore, SIGNAL
            store = AdminStore(self.project_root, self.logger)
            # 从 run_id 推断 spec（与 run_spec_part 同逻辑）；解析失败留空不强解
            from core.agent_runner.run_files import run_spec_part
            spec_name = run_spec_part(base_id)
            store.append({
                "kind": SIGNAL,
                "signal_type": "run_cancelled",
                "spec": spec_name if spec_name != base_id else None,
                "severity": "minor",
                "description": (
                    f"人工取消 run '{base_id}'（活跃 attempt: {matched_attempts}）"
                    f"—— reason={reason!r}, by={by}"
                ),
                "evidence": (
                    f"base_run_id={base_id}; attempts={len(matched_attempts)}; "
                    f"reason={reason}; by={by}"
                ),
                "recommended_action": (
                    "run 已登记取消旗标，由持有线程完成 terminate/kill 与 cancelled "
                    "终态落盘；spec 保持原状态，由 stuck 检测/恢复扫描按既有节奏接管"
                ),
            })
        except Exception as e:
            self.logger.debug(
                "agent_runner",
                f"cancel_run 审计记录写入失败（非阻塞）: {e}",
            )

        return {
            "status": "cancel_requested",
            "attempts": matched_attempts,
            "base_run_id": base_id,
        }

        # 秒挂退避熔断（cli-retry-backoff）：spec 维度连续秒挂计数与冷却态。
        # 进程内存、不落盘：{spec_name: {"count": int, "cooldown_until": float}}
        # count = 连续秒挂次数（未重置），cooldown_until = 冷却到期单调秒。
        # daemon 重启重建即清零（冷却不跨重启，重启即视为恢复）。惰性清理：
        # 冷却到期由 is_instant_fail_cooldown 恢复并清除；无条目即无冷却。
        self._instant_fail: Dict[str, dict] = {}


    # ── V2 per-run 隔离测试服务（add-worktree-test-server）─────────────────────


    # ── provider 熔断（fix-stashpop-deadlock：provider-fault-fuse） ──────────────


    def _now(self) -> float:
        """单调时间戳（测试可覆写）。用 time.monotonic 避免时钟回拨影响窗口。"""
        return time.monotonic()

    # ── 秒挂退避熔断状态表（cli-retry-backoff）───────────────────────
    # 惰性 property：测试普遍以 ``AgentRunner.__new__`` 绕过 ``__init__`` 构造，
    # 直接访问 self._instant_fail 会 AttributeError。沿用组合组件惰性初始化模式，
    # 首次访问即时建表（__init__ 内的赋值经 setter 落地同一 backstore）。

    @property
    def _instant_fail(self) -> Dict[str, dict]:
        inst = self.__dict__.get("_instant_fail_state")
        if inst is None:
            inst = {}
            self.__dict__["_instant_fail_state"] = inst
        return inst

    @_instant_fail.setter
    def _instant_fail(self, value):
        self.__dict__["_instant_fail_state"] = value

    @_instant_fail.deleter
    def _instant_fail(self):
        self.__dict__.pop("_instant_fail_state", None)


    # ── provider 切换冷却（add-provider-failover：failover-dispatch） ──────────


    def run_implementer(self, spec_name: str,
                        pre_wt_path: Path | None = None) -> AgentRunResult:
        """
        Run the implementer Agent for a SPEC.

        Steps:
        1. Create worktree
        2. Build claude prompt
        3. Execute via subprocess
        4. Parse result
        5. Clean up worktree
        6. Return result

        interrupt-recovery-preserve（D4）：``pre_wt_path`` 非 None 时**不创建新
        worktree**，直接在指定 worktree 内续做（恢复保留分支的 resume 续做）。
        worktree 生命周期由调用层（dispatch）解析与登记，成功/失败清理语义与
        既有 repair 路径一致。
        """
        run_id = f"impl-{spec_name}-{int(time.time())}"
        return self._execute_agent(spec_name, "implementer", run_id,
                                   pre_wt_path=pre_wt_path)

    def run_verifier(self, spec_name: str) -> AgentRunResult:
        """Run the verifier Agent for a SPEC."""
        run_id = f"verify-{spec_name}-{int(time.time())}"
        return self._execute_agent(spec_name, "verifier", run_id)

    def run_planner(self, spec_name: str, mode: str) -> AgentRunResult:
        """Run the Planner Agent for a SPEC.

        Args:
            spec_name: SPEC名称
            mode: "plan"（生成测试场景）或 "judge"（判定验证结果）
        """
        if mode not in ("plan", "judge"):
            raise ValueError(f"mode 必须是 'plan' 或 'judge'，实际: {mode}")
        run_id = f"planner-{mode}-{spec_name}-{int(time.time())}"
        sem = self._planner_throttle_semaphore()
        if sem is None:
            # 未开启节流：直接派发（现状行为）
            return self._execute_agent(spec_name, f"planner-{mode}", run_id)
        # ── 节流持槽等待（add-planner-efficiency：planner-generation-throttle）──
        # 持槽等待期间不派发 attempt——run 尚未创建，先写保活事件到预生成
        # run 文件（防 recovery watch 在长等待中把「已派发但未启动」误判为
        # 无进度/stuck；design D2 备选方案，见 _planner_throttle_acquire）。
        acquired = self._planner_throttle_acquire(spec_name, run_id)
        if not acquired:
            return AgentRunResult(
                run_id, spec_name, f"planner-{mode}",
                success=False, duration_seconds=0,
                error="planner throttle 获取信号量失败",
            )
        try:
            return self._execute_agent(spec_name, f"planner-{mode}", run_id)
        finally:
            # 取消/异常均释放信号量（不泄漏占位导致后续 spec 永久排队）
            sem.release()

    def run_dispute_judge(self, spec_name: str, judge_input: dict,
                          run_id: str | None = None) -> AgentRunResult:
        """Run the Dispute Judge Agent for a SPEC (deliverable-declaration-triage D3).

        收工守卫判缺件后、打回/重派前由 dispatch 调用：轻量**单轮只读**裁决者。
        与 planner-judge 同属 judge 范式，但**不创建 worktree**（design D3：
        主树只读上下文，--add-dir 主树、无 worktree、无写权限任务书）：

        - run_id 前缀 ``dispute-judge-<spec>-<ts>``（_RUN_PREFIXES 同步扩展，
          见 run_files.py 前缀元组与 admin_monitor._RUN_PREFIXES，两处同源）；
          调用方（dispatch）可注入预生成 run_id——终审期间 spec 的 error 字段须
          先行携带该 id（D5：blocked + 「LLM 终审进行中」阻断重派竞态）；
        - 输入（缺件清单 + spec 语境摘录 + 实现 run findings + basename 候选）
          由调用方组装为 ``judge_input`` dict，本方法落盘
          ``.fenix/verify-progress/<spec>/dispute_judge_input.json`` 并经 prompt
          指示 judge 读取；
        - 输出契约：``.fenix/verify-progress/<spec>/dispute_judge_result.json``
          顶层 ``status: "success"`` + ``verdicts: [{element, verdict,
          actual_path, reasoning, confidence}]``（verdict 四取一
          typo|reference|missing|unclear）；
        - 裁决的机械执行（D4）由调用方（dispatch）完成——本方法只派发与收工。

        Args:
            spec_name: SPEC 名。
            judge_input: 裁决输入 dict（missing/spec_context/findings 等）。
            run_id: 预生成 run id（派发前已写入 spec error 的场景）；省略则
                本方法生成 ``dispute-judge-<spec>-<ts>``。

        Returns:
            AgentRunResult（success 仅表示 run 正常收工；裁决语义合法性由调用方
            读取结果文件校验——run 失败/超时/输出不合法等价 unclear）。
        """
        run_id = run_id or f"dispute-judge-{spec_name}-{int(time.time())}"
        vp_dir = self.project_root / ".fenix" / "verify-progress" / spec_name
        input_path = vp_dir / "dispute_judge_input.json"
        try:
            vp_dir.mkdir(parents=True, exist_ok=True)
            input_path.write_text(
                json.dumps(judge_input or {}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            return AgentRunResult(
                run_id, spec_name, "dispute-judge",
                success=False, duration_seconds=0.0,
                error=f"dispute judge 输入落盘失败: {e}",
            )

        try:
            prompt = self._build_prompt(
                spec_name, "dispute-judge",
                detail={"dispute_input_path": str(input_path)},
            )
        except Exception as e:
            return AgentRunResult(
                run_id, spec_name, "dispute-judge",
                success=False, duration_seconds=0.0,
                error=f"dispute judge prompt 构建失败: {e}",
            )

        # 模型路由（design Non-Goal：不新增配置键）：已分配 provider 用分配模型
        # 直连（与 administrator 同通道）；未分配走默认网关（cc-switch），
        # --model 用官方模型名常量，由网关映射到可用模型。
        assignment = self._get_agent_model_assignment("dispute-judge")
        env_overrides: Dict[str, str] = {}
        provider_name = None
        if assignment:
            provider, model_override = assignment[0]
            provider_name = provider["name"]
            env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
            env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
            env_overrides["ANTHROPIC_MODEL"] = model_override
            env_overrides["CLAUDE_CONFIG_DIR"] = str(
                self._ensure_agent_config_dir(provider["name"])
            )
            for k, v in (provider.get("env") or {}).items():
                env_overrides[k] = v
            # 观测：run jsonl 写 provider_marker（与 dispatch attempt 路径同口径）
            self._write_provider_marker(
                run_id, spec_name, "dispute-judge",
                provider["name"], model_override, 0, 1,
            )
        else:
            model_override = DEFAULT_GATEWAY_MODEL

        start_time = time.time()
        try:
            output, turns, _session_id, _usage = self._run_claude(
                prompt, self.project_root, run_id, model_override, env_overrides,
                max_turns=self._get_config("agents.max_turns", 300),
                spec_name=spec_name,
                agent_type="dispute-judge",
            )
            return AgentRunResult(
                run_id, spec_name, "dispute-judge",
                success=True, duration_seconds=time.time() - start_time,
                turns_used=turns, output=output or "",
                provider_used=provider_name, model_used=model_override,
            )
        except Exception as e:
            self.logger.warning(
                "agent_runner",
                f"dispute judge run 失败 '{spec_name}'（等价 unclear）: {e}",
            )
            return AgentRunResult(
                run_id, spec_name, "dispute-judge",
                success=False, duration_seconds=time.time() - start_time,
                error=str(e),
                provider_used=provider_name, model_used=model_override,
            )

    def run_spec_review(self, spec_name: str, run_id: str | None = None) -> AgentRunResult:
        """Run the Spec Review Agent for a SPEC (add-spec-review-gate).

        方案评审门禁：drafted → reviewing 晋升后由 PM Engine 派发。
        与 run_dispute_judge 同属判官范式：不创建 worktree，cwd=主树，--add-dir 主树。

        - run_id 前缀 ``spec-review-<spec>-<ts>``（_RUN_PREFIXES 同步扩展）；
        - 评审者直接读取 SPEC 目录下的文档，无需额外输入 JSON；
        - 输出契约：``.fenix/spec-review/<spec>/.fenix-run-result.json``
          顶层 ``status`` 三取一（approved/repaired/rejected）+ findings/repairs 等；
        - 结果硬门复用 _check_agent_result_artifact。

        Args:
            spec_name: SPEC 名。
            run_id: 预生成 run id；省略则生成 ``spec-review-<spec>-<ts>``。

        Returns:
            AgentRunResult（success 仅表示 run 正常收工；评审语义合法性由调用方
            读取结果文件校验）。
        """
        run_id = run_id or f"spec-review-{spec_name}-{int(time.time())}"
        result_path = spec_review_result_path(self.project_root, spec_name)
        # 确保结果目录存在
        result_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            prompt = self._build_prompt(
                spec_name, "spec-review",
                detail={"result_path": str(result_path)},
            )
        except Exception as e:
            return AgentRunResult(
                run_id, spec_name, "spec-review",
                success=False, duration_seconds=0.0,
                error=f"spec review prompt 构建失败: {e}",
            )

        # 模型路由：复用 agents.models.spec-review（未分配走默认网关）
        assignment = self._get_agent_model_assignment("spec-review")
        env_overrides: Dict[str, str] = {}
        provider_name = None
        if assignment:
            provider, model_override = assignment[0]
            provider_name = provider["name"]
            env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
            env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
            env_overrides["ANTHROPIC_MODEL"] = model_override
            env_overrides["CLAUDE_CONFIG_DIR"] = str(
                self._ensure_agent_config_dir(provider["name"])
            )
            for k, v in (provider.get("env") or {}).items():
                env_overrides[k] = v
            self._write_provider_marker(
                run_id, spec_name, "spec-review",
                provider["name"], model_override, 0, 1,
            )
        else:
            model_override = DEFAULT_GATEWAY_MODEL

        start_time = time.time()
        try:
            output, turns, _session_id, _usage = self._run_claude(
                prompt, self.project_root, run_id, model_override, env_overrides,
                max_turns=self._get_config("agents.max_turns", 300),
                spec_name=spec_name,
                agent_type="spec-review",
            )
            return AgentRunResult(
                run_id, spec_name, "spec-review",
                success=True, duration_seconds=time.time() - start_time,
                turns_used=turns, output=output or "",
                provider_used=provider_name, model_used=model_override,
            )
        except Exception as e:
            self.logger.warning(
                "agent_runner",
                f"spec review run 失败 '{spec_name}': {e}",
            )
            return AgentRunResult(
                run_id, spec_name, "spec-review",
                success=False, duration_seconds=time.time() - start_time,
                error=str(e),
                provider_used=provider_name, model_used=model_override,
            )

    def _planner_throttle_semaphore(self) -> Optional[threading.BoundedSemaphore]:
        """按配置惰性重建 planner 节流信号量（0/缺省=不节流）。

        add-planner-efficiency（planner-generation-throttle 2.1）：配置键
        ``verify.planner_max_concurrent``。热更新生效——每次 run_planner
        重新读配置，上限变化即重建 BoundedSemaphore（既有占位按新上限重计）。
        返回 None 表示未开启节流（调用方不获取、直接派发）。
        """
        global _PLANNER_SEMAPHORE, _PLANNER_SEMAPHORE_LIMIT
        limit = self._get_config("verify.planner_max_concurrent", 0) or 0
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 0
        if limit <= 0:
            return None
        with _PLANNER_SEMAPHORE_LOCK:
            if _PLANNER_SEMAPHORE is None or _PLANNER_SEMAPHORE_LIMIT != limit:
                _PLANNER_SEMAPHORE = threading.BoundedSemaphore(limit)
                _PLANNER_SEMAPHORE_LIMIT = limit
                self.logger.info(
                    "agent_runner",
                    f"planner 生成节流启用：跨管线并发上限 {limit} "
                    f"（verify.planner_max_concurrent）",
                )
            return _PLANNER_SEMAPHORE

    def _planner_throttle_acquire(self, spec_name: str, run_id: str) -> bool:
        """持槽等待信号量（可观测 + 等待期保活，design D2 备选方案）。

        - 排队可观测：等待开始时打 INFO 日志（spec 名 + 当前占用者数量），
          时间轴可审计；
        - 等待期保活：run 尚未启动（_execute_agent 内才创建 attempt run），
          以带超时的 acquire 轮询获取，等待期间按心跳周期向预生成 run 文件
          追加 ``throttled-wait`` 事件行——保持 run 流新鲜，避免等待超过
          stuck 阈值（160min）且无写入时被 recovery watch 误判为
          stuck/dispatch_stalled（spec「排队不被误判」Scenario）。
        - 取消（RunCancelledError）在等待期不可达（无子进程可终止），因此
          仅释放义务由调用方 finally 承担。
        """
        sem = _PLANNER_SEMAPHORE
        if sem is None:
            return True
        self.logger.info(
            "agent_runner",
            f"planner 节流排队中: spec={spec_name} run={run_id} "
            f"当前占用 {sem._value}/{_PLANNER_SEMAPHORE_LIMIT}（持槽等待）",
        )
        # 预生成 run 文件：等待期保活事件写入目标（避免无文件可写）
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{run_id}.jsonl"
        try:
            run_file.touch(exist_ok=True)
        except OSError:
            pass
        deadline = time.monotonic() + THROTTLED_WAIT_HEARTBEAT_SECONDS
        while True:
            if sem.acquire(timeout=THROTTLED_WAIT_HEARTBEAT_SECONDS):
                # 获取成功，补一次保活事件标记正式开始
                try:
                    append_run_line(run_file, {
                        "type": "throttled-wait",
                        "event": "acquired",
                        "spec": spec_name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except OSError:
                    pass
                return True
            # 等待仍在继续：保活心跳（约每 60s 一次），run 流保持新鲜
            if time.monotonic() >= deadline:
                deadline = time.monotonic() + THROTTLED_WAIT_HEARTBEAT_SECONDS
                try:
                    append_run_line(run_file, {
                        "type": "throttled-wait",
                        "event": "heartbeat",
                        "spec": spec_name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except OSError:
                    pass

    def ensure_planner_route_map(self, spec_name: str) -> Path | None:
        """阶段1 前置接入：对 spec 当前使用的 impl worktree 生成/复用路由地图。

        add-planner-efficiency（planner-route-map 1.1）。verification.py 阶段1
        进入处调用；复用键=worktree HEAD（未变跳过）。worktree 尚未创建
        （首轮 planner 派发前没有 planner worktree）时无操作返回 None——
        真正的生成兜底在 ``_execute_agent_inner`` planner 分支（worktree 创建
        后、prompt 组装前，HEAD 键控）。两者共用 ``ensure_route_map``，幂等。

        Returns: 地图文件路径或 None（fail-open / 无可用 worktree）。
        """
        if not spec_name:
            return None
        try:
            wt = self.worktree_manager.find_implementer_worktree(spec_name)
        except Exception:
            return None
        if wt is None:
            return None
        try:
            return ensure_route_map(Path(wt), self.project_root, self.logger)
        except Exception as e:
            self.logger.warning(
                "agent_runner",
                f"route-map 生成异常（fail-open）'{spec_name}': {e}",
            )
            return None

    def run_fast_track(self, spec_name: str) -> AgentRunResult:
        """Run the Fast-Track Agent for a SPEC (single run: implement + verify).

        Fast-track run 同时完成实现与验证（实现+场景设计+验证+判定）。
        生成的分支与成功路径 merge 语义与 implementer 一致；budget 沿用
        impl_run_budget（走 impl- 前缀 run_id，复用既有计数/对账路径）。
        """
        run_id = f"impl-{spec_name}-{int(time.time())}"
        return self._execute_agent(spec_name, "fast-track", run_id)

    def run_repair(self, spec_name: str, wt_path: Path,
                   conflict_summary: dict | None = None) -> AgentRunResult:
        """Run the Repair Agent for a SPEC in an existing worktree.

        add-merge-back-repair-lane D5：merge-back 语义冲突失败后，在实现分支
        一侧原地修复（把 main 合进分支、解决冲突、跑测试、commit）。与普通
        implementer 的差异：
        - run_id 前缀 ``repair-<spec>-<ts>``（Dashboard/runs 可辨识，不计入
          fix 族谱；repair<->fix 异名不触发同根互斥）；
        - **不创建新 worktree**：使用调度层解析好的 repair 载体（原地或换壳）；
        - token 记所属 spec 名下（走既有 ``_accumulate_token_usage`` ——
          repair agent 的消耗计入实现预算，design「repair 轮计入该 spec 的
          实现预算」）；
        - worktree 生命周期交由调用层（dispatch）管理：成功与失败都不清理
          worktree（worktree_kept=True），保证多轮 repair 可原地复用或终态回收。

        Args:
            spec_name: SPEC 名称。
            wt_path: repair 载体 worktree 路径（调度层经三态解析）。
            conflict_summary: 冲突分类摘要 dict（prompt 注入，缺省 {}）。
        """
        run_id = f"repair-{spec_name}-{int(time.time())}"
        return self._execute_agent(
            spec_name, "repair", run_id,
            pre_wt_path=wt_path,
            conflict_summary=conflict_summary or {},
        )

    def _clear_admin_disposition(self, disp_path: Path):
        _clear_admin_disposition(disp_path)

    def _delete_admin_disposition(self, disp_path: Path):
        _delete_admin_disposition(disp_path)

    def _clear_self_review_out(self, out_path: Path):
        _clear_self_review_out(out_path)

    def _delete_self_review_out(self, out_path: Path):
        _delete_self_review_out(out_path)

    def _accumulate_self_review_tokens(self, date_str: str, usage_info: dict) -> None:
        _accumulate_self_review_tokens(self, date_str, usage_info)

    def _delete_evolution_out(self, out_path: Path):
        _delete_evolution_out(out_path)

    def _accumulate_evolution_tokens(self, run_id: str, usage_info: dict) -> None:
        _accumulate_evolution_tokens(self, run_id, usage_info)

    def _build_isolated_settings(self) -> dict:
        """构造隔离 settings.json：enabledPlugins / hooks（spec D2/D3）。

        从 ~/.claude/settings.json 复制 enabledPlugins（缺省 superpowers）。hooks 从
        .fenix/agent-settings.json 复制（PreToolUse block-image-read）。不复制任何 env
        模型名映射——那属于 cc-switch 网关、对直连 Provider 无用且有毒化子代理解析的
        风险（如陈旧 hy3）。Provider 的 ANTHROPIC_MODEL/BASE_URL/API_KEY 经进程 env 注入。
        """
        settings: Dict[str, Any] = {}
        source: Dict[str, Any] = {}
        home_settings = Path.home() / ".claude" / "settings.json"
        try:
            if home_settings.is_file():
                loaded = json.loads(home_settings.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    source = loaded
        except (OSError, json.JSONDecodeError):
            source = {}

        plugins = source.get("enabledPlugins")
        if isinstance(plugins, dict) and plugins:
            settings["enabledPlugins"] = plugins
        else:
            settings["enabledPlugins"] = {"superpowers@claude-plugins-official": True}

        agent_settings = self.project_root / ".fenix" / "agent-settings.json"
        if agent_settings.is_file():
            try:
                loaded = json.loads(agent_settings.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("hooks"), dict):
                    settings["hooks"] = loaded["hooks"]
            except (OSError, json.JSONDecodeError):
                pass

        # 不复制 ~/.claude/settings.json 的 env（ANTHROPIC_DEFAULT_* / CLAUDE_CODE_SUBAGENT_MODEL
        # 等 cc-switch 网关映射）——直连 Provider 不需要，且会毒化子代理模型解析（陈旧 hy3）。
        return settings

    def _ensure_agent_config_dir(self, provider_name: str) -> Path:
        """按需生成并返回 Provider 的隔离配置目录（spec D1/D2/D5）。

        目录：.fenix/agent-config/<provider_name>/，含 settings.json 与指向
        ~/.claude 的 skills/plugins symlink（源目录不存在则跳过，优雅降级）。
        幂等：settings.json 已存在则跳过重建；并发首次创建由原子 mkdir +
        temp+rename 写文件兜底，内容确定无副作用。
        """
        cfg_dir = self.project_root / ".fenix" / "agent-config" / provider_name
        marker = cfg_dir / "settings.json"
        if marker.is_file():
            return cfg_dir
        try:
            cfg_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return cfg_dir

        settings = self._build_isolated_settings()
        try:
            tmp = cfg_dir / ".settings.tmp"
            tmp.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, marker)
        except OSError:
            pass

        for name in ("skills", "plugins"):
            src = Path.home() / ".claude" / name
            dst = cfg_dir / name
            try:
                if src.is_dir() and not dst.exists():
                    dst.symlink_to(src, target_is_directory=True)
            except OSError:
                pass
        return cfg_dir

    def _select_chain_candidate(self, chain, spec_name: str, agent_type: str,
                                 now: float | None = None) -> int:
        """在候选链上选择首个「未熔断且未处于 switch 冷却」的候选下标（add-provider-failover）。

        design D3：链选择跳过 switch-cooldown 中或 4xx 熔断中的候选；返回值用于落点。
        全部候选都冷却 → 返回 -1（调用方据 chain_exhausted 失败语义处理，不启动进程、
        不计入 spec 重试消耗）。

        Args:
            chain: ConfigLoader.get_agent_model_assignment 返回的候选链
                （list[(provider_dict, model)]），可为空。
        """
        now = self._now() if now is None else now
        for idx, (provider, _model) in enumerate(chain):
            name = provider["name"]
            if self.is_circuit_open(name, now=now):
                continue
            if self.is_switch_cooldown(name, now=now):
                continue
            return idx
        return -1

    def _worktree_path_valid(self, wt_path: Path) -> bool:
        """worktree 路径存在性快检（fix-resume-stale-worktree 3a）。

        目录存在且仍是可解析的 git 工作树；任何异常（权限/超时）按失效处置，
        由调用方走各自回退路径（新建/显式失败）。
        """
        try:
            if not wt_path.is_dir():
                return False
            proc = subprocess.run(
                ["git", "-C", str(wt_path), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=10,
            )
            return proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _check_terminal_no_commit_gate(self, spec_name: str, agent_type: str,
                                       wt_path, branch, wt_dirty: list,
                                       sub_run_id: str) -> None:
        """终态零提交门判定（add-impl-terminal-nocommit-gate D2）。

        仅 implementer 车道生效：分支相对 main 零新提交（`git rev-list --count
        main..branch` == 0）且 worktree dirty 取证非空时，抛携带
        `[terminal-no-commit]` 前缀与机械归因文案的 `AgentArtifactGateError`，
        进入既有原地退避重试通道（锚点 B WIP 提交 + 退避 + resume 续做）。

        放行（不拦）情形：分支有新提交、零提交且 worktree 干净（真空转归既有
        零变更哨管辖）、fast-track/repair/verifier 车道、rev-list 失败
        （fail-open——门自身故障绝不打断正常收口）。
        """
        if agent_type != "implementer" or not wt_dirty:
            return
        if not branch:
            return
        try:
            rc = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-list",
                 "--count", f"main..{branch}"],
                capture_output=True, text=True, timeout=15,
            )
            zero_commit = (
                rc.returncode == 0 and int(rc.stdout.strip() or "0") == 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            zero_commit = False  # fail-open：不因门故障误拦
        if not zero_commit:
            return
        attribution = self._classify_terminal_no_commit(sub_run_id)
        raise AgentArtifactGateError(
            f"[terminal-no-commit] 归因:{attribution} — "
            f"implementer 正常终态但分支零提交且 worktree 有 "
            f"{len(wt_dirty)} 个未提交产物；进入退避通道：WIP "
            f"提交保全 + 原地退避 + 同 worktree resume 续做"
        )

    # ── 终态零提交门机械归因（add-impl-terminal-nocommit-gate D3）──────────
    # 归因为纯文本机械匹配、零 LLM：读 run 转录最后一条含 text 块的 assistant
    # 消息，看其是否含「假工具调用」特征——模型把工具调用写成了正文（XML
    # `<function_calls>` 形态或 markdown fenced code 形态），SDK 不从 text 解析
    # 工具 → `end_turn`「自然完成」→ 成功判定但零提交（2026-09-10 双事故根因）。
    # 归因仅用于 audit 与日志语义区分，不改变处置路径（resume 对两种原因均正确）。
    _TERMINAL_NO_COMMIT_TOOL_PATTERN = (
        r"(?:<function_calls>"
        r"|```\s*(?:(?:Edit|Write|Bash|NotebookEdit)\b|<invoke))"
    )

    def _classify_terminal_no_commit(self, sub_run_id: str) -> str:
        """机械归因：run 转录末轮 assistant text 的假工具调用特征判定。

        - text 含 ``<function_calls>``（XML 内嵌工具调用）→ 「格式回退截断」
        - text 含 markdown fenced code 紧随工具名（Edit/Write/Bash/NotebookEdit）
          或 ``<invoke`` → 「格式回退截断」
        - 无上述特征 → 「未提交即收工」
        - 转录缺失/损坏 → 降级「未提交即收工」（fail-open）

        基准为逐行扫描整个转录并**持续更新**最后一条 assistant text 块（stream-json
        逐行追加，末轮即最后读到的一个 text 块）；找不到任何 assistant text 时同样
        降级为「未提交即收工」。
        """
        last_text: str = ""
        run_file = self.project_root / ".fenix" / "runs" / f"{sub_run_id}.jsonl"
        try:
            with run_file.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("type") != "assistant":
                        continue
                    for c in (d.get("message") or {}).get("content") or []:
                        if isinstance(c, dict) and c.get("type") == "text":
                            last_text = c.get("text") or ""
        except OSError:
            return "未提交即收工"
        if re.search(
                self._TERMINAL_NO_COMMIT_TOOL_PATTERN,
                last_text, re.IGNORECASE):
            return "格式回退截断"
        return "未提交即收工"

    # ── spec-review 结果捞回（2026-09-15 事故修复）──────────────────────
    # 评审 run 正常收工但从未调用 Write，把结果 JSON 当正文 fenced 代码块吐出
    # （与 _classify_terminal_no_commit 同族的「假工具调用」死法）。框架代写：
    # 从转录末轮 assistant text 抽最后一个 fenced JSON，status 在白名单内即落盘
    # ——把「整轮白烧重试」降为「零成本回收」。抽不出/status 非法/文件已存在
    # 一律不动，交由硬门与读侧按既有语义处理。
    #
    # fix-impl-resultfile-contract-gap D4：实现泛化为车道无关
    # （salvage_result_from_transcript，落 result_gate.py），本方法保留为薄
    # 包装——spec-review 路径与白名单行为逐字不变（core/pm_engine/spec_review.py
    # :191/220 反射调用点与 tests/test_review_circuit_breaker.py 打桩对象继续
    # 可用）。成功日志由泛化实现内部写出（含 spec/run_id/status，不静默）。

    def _salvage_spec_review_result(self, spec_name: str,
                                    run_id: str | None) -> bool:
        """尝试从评审 run 转录捞回结果并落盘（薄包装，委派泛化实现）。

        Returns: True 表示已代写落盘；False 表示无可用 JSON / status 非法 /
            文件已存在（不覆盖既有产物）。
        """
        return salvage_result_from_transcript(
            self.project_root, spec_name, run_id, "spec-review",
            statuses=spec_review_result_status_whitelist)

    def _salvage_impl_result(self, spec_name: str, run_id: str | None,
                             wt_path: Path | None, agent_type: str) -> bool:
        """实现者车道（implementer / fast-track）结果文件捞回薄包装。

        fix-impl-resultfile-contract-gap 3.4：run 自然收工但从未写结果文件时，
        从转录末轮 fenced JSON 代写落盘到 ``<wt_path>/.fenix-run-result.json``
        （`_IMPL_RESULT_STATUSES` 是类属性，白名单经 ``statuses`` 参数传入，
        不得导出为模块常量）。``wt_path`` 为 None（测试/异常场景）MUST no-op
        返回 False，MUST NOT 抛错。
        """
        if wt_path is None:
            return False
        return salvage_result_from_transcript(
            self.project_root, spec_name, run_id, agent_type,
            wt_path=wt_path, statuses=self._IMPL_RESULT_STATUSES)

    def _wip_checkpoint_before_backoff(self, spec_name: str, wt_path) -> None:
        """锚点 B（add-impl-wip-checkpoint D3）：transient 原地退避前的 WIP 提交。

        attempt 循环判定瞬断、写入 ``transient_retry`` 记录后、进入
        ``time.sleep(backoff)`` 前调用——此刻子进程已退出、worktree 静默可
        证明。对当前 attempt 使用的 worktree 执行 ``fenix(wip): checkpoint
        transient-backoff <spec>`` 提交：即便 daemon 在退避窗口内死亡重启，
        该分支上已有可恢复提交，recovery 走保留续做而非降级重建。

        无 worktree 载体（pre_wt_path 为 None 且本 attempt 未建且不等于复用
        路径）或路径已失效时跳过——现行行为逐字节不变。失败由 helper 内部
        WARNING 降级，不阻断退避循环。
        """
        if wt_path is None:
            return
        if not self._worktree_path_valid(wt_path):
            self.logger.debug(
                "agent_runner",
                f"WIP checkpoint (transient-backoff) skip: worktree "
                f"{wt_path} not a valid git worktree for '{spec_name}'",
            )
            return
        try:
            commit_wip_checkpoint(
                wt_path, spec_name, ANCHOR_TRANSIENT_BACKOFF, self.logger)
        except Exception as e:
            # 兜底：helper 理论上不抛，防御性捕获保证退避循环不被打断
            self.logger.warning(
                "agent_runner",
                f"WIP checkpoint (transient-backoff) failed for '{spec_name}': "
                f"{e} — non-blocking",
            )

    def _wip_checkpoint_on_forced_kill(self, spec_name: str, wt_path,
                                       anchor: str = ANCHOR_TURN_LIMIT) -> None:
        """锚点 C（add-turn-limit-anchor-c D1）：强杀收口前的 WIP 提交。

        turn-limit / timeout 两强杀路径共用：轮询环已 kill 子进程、读线程
        已 join（finally 语义保证 worktree 静默）后、``append_run_error``
        之前调用——此刻 agent 已可证明不再写盘（事故取证：第 12 提交与
        SIGKILL 同秒落盘，kill 前提交可能纳入半写文件）。对当前 attempt
        使用的 worktree 执行 ``fenix(wip): checkpoint <anchor> <spec>``
        提交，零提交型 run 的现场（builtin a1 84min 未提交产物）得以保全，
        后续 attempt resume 或降级重建均可从该提交恢复。

        无 worktree 载体或路径失效时跳过（与锚点 A/B 同语义，幂等）。
        失败由 helper 内部 WARNING 降级（git 超时/失败不阻断收口流程）。
        """
        if wt_path is None:
            return
        if not self._worktree_path_valid(wt_path):
            self.logger.debug(
                "agent_runner",
                f"WIP checkpoint ({anchor}) skip: worktree "
                f"{wt_path} not a valid git worktree for '{spec_name}'",
            )
            return
        try:
            commit_wip_checkpoint(
                wt_path, spec_name, anchor, self.logger)
        except Exception as e:
            # 兜底：helper 理论上不抛，防御性捕获保证强杀收口不被阻断
            self.logger.warning(
                "agent_runner",
                f"WIP checkpoint ({anchor}) failed for '{spec_name}': "
                f"{e} — non-blocking",
            )

    def _wip_checkpoint_on_extension_tail(self, spec_name: str, wt_path) -> None:
        """extension 末位窗口保全（add-fast-track-scale-precheck D3）。

        fast-track run 剩余时间进入末位窗口（remaining <
        ``EXTENSION_TAIL_WINDOW_SECONDS``）时调用：先 commit_wip_checkpoint
        （消息契约 ``fenix(wip): checkpoint extension-tail <spec>``）保全已
        完成轮次工作，run 继续轮询；超时到点后走既有收口，已完成工作不随
        超时无保全作废。

        无 worktree 载体或路径失效时跳过（与锚点 A/B/C 同语义，幂等）。
        失败由 helper 内部 WARNING 降级（git 超时/失败不阻断轮询与收口，
        任务 3.2：保全失败仅 WARNING，既有超时收口照常执行）。
        """
        if wt_path is None:
            return
        if not self._worktree_path_valid(wt_path):
            self.logger.debug(
                "agent_runner",
                f"WIP checkpoint (extension-tail) skip: worktree "
                f"{wt_path} not a valid git worktree for '{spec_name}'",
            )
            return
        try:
            commit_wip_checkpoint(
                wt_path, spec_name, ANCHOR_EXTENSION_TAIL, self.logger)
        except Exception as e:
            # 兜底：helper 理论上不抛，防御性捕获保证轮询/收口不被阻断
            self.logger.warning(
                "agent_runner",
                f"WIP checkpoint (extension-tail) failed for '{spec_name}': "
                f"{e} — non-blocking",
            )

    def _turn_limit_action(self, run_file: Path, spec_name: str | None,
                           run_id: str, turn_extensions_used: int,
                           wt_path, agent_type: str | None = None,
                           *, max_turns: int | None = None) -> dict:
        """轮次上限到期后的监督决策（add-turn-limit-anchor-c design D2）：续期 or 终止。

        封闭矩阵（先封顶后活性，与超时路径 ``_supervision_deadline_action``
        （improve-run-lifecycle-governance D3）同构但计数独立）：
          1. 已用满 ``TURN_EXTENSION_MAX`` → 无条件 kill（封顶语义）；
          2. 分支活性：工作树分支相对 run 起点（主树 HEAD）有提交，且较上次
             判定有增量 → extend；
          3. 流量活性：run 文件尾部 ``TURN_EXTENSION_WINDOW_SECONDS`` 窗口内
             有新 ``tool_result`` 事件（按 ``_entry_is_tool_result`` 统一识别——
             真实转录 ``user`` 包裹 ``tool_result`` block，兼容顶层
             ``tool_result`` 事件，复用 ``_parse_event_timestamp`` 口径）
             → extend；
          4. 双无活性 → kill。

        任一活性证据命中即续期（design D2「任一命中即 extend」）；rev-list
        失败 fail-open（分支状态不可知不判死，视为有活性——封顶次数兜住最坏
        情况）。判定只在命中轮次上限的轮询轮执行（rev-list 不在常规 1s 轮询
        路径上，无周期拖慢）。

        Returns: {"action": "extend"|"kill", "extension_index",
                  "turn_step", "evidence", "new_turn_cap"}
        """
        if not hasattr(self, "_turn_branch_state"):
            self._turn_branch_state = {}
        turn_step = int((max_turns or 0) * TURN_EXTENSION_STEP_FRACTION)
        base = {
            "extension_index": turn_extensions_used,
            "turn_step": turn_step,
        }
        if turn_extensions_used >= TURN_EXTENSION_MAX:
            return {
                **base,
                "action": "kill",
                "evidence": (
                    f"turn extension budget exhausted "
                    f"({turn_extensions_used}/{TURN_EXTENSION_MAX})"),
                "new_turn_cap": (max_turns or 0)
                + turn_extensions_used * turn_step,
            }

        # ── 活性证据 a：分支提交增量（首次以主树 HEAD 为 run 起点基线）──
        branch_alive = False
        branch_evidence = ""
        if wt_path is not None and self._worktree_path_valid(wt_path):
            try:
                base_head = subprocess.run(
                    ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
                    capture_output=True, text=True, timeout=15,
                )
                branch_tip = subprocess.run(
                    ["git", "-C", str(wt_path), "rev-parse", "HEAD"],
                    capture_output=True, text=True, timeout=15,
                )
                if (base_head.returncode != 0 or branch_tip.returncode != 0
                        or not base_head.stdout.strip()
                        or not branch_tip.stdout.strip()):
                    raise subprocess.SubprocessError(
                        "rev-parse failed: "
                        f"base={base_head.returncode} tip={branch_tip.returncode}")
                rc = subprocess.run(
                    ["git", "-C", str(wt_path), "rev-list", "--count",
                     f"{base_head.stdout.strip()}..{branch_tip.stdout.strip()}"],
                    capture_output=True, text=True, timeout=15,
                )
                if rc.returncode != 0 or not rc.stdout.strip():
                    raise subprocess.SubprocessError(
                        f"rev-list failed: {rc.stderr.strip() or rc.stdout.strip()}")
                count = int(rc.stdout.strip())
            except (subprocess.SubprocessError, OSError,
                    subprocess.TimeoutExpired, ValueError) as e:
                # fail-open：git 不可用/慢/版本异常时不得判死（封顶次数兜底）
                branch_alive = True
                self.logger.debug(
                    "agent_runner",
                    f"turn-limit branch liveness check unavailable for "
                    f"'{spec_name}' ({run_id}): {e} — fail-open as alive",
                )
            else:
                state = self._turn_branch_state.setdefault(run_id, {})
                prev = state.get("commit_count")
                if prev is None:
                    # 首次判定：以 run 起点（主树 HEAD 基线）计分支新提交
                    branch_alive = count > 0
                else:
                    branch_alive = count > prev  # 较上次判定有增量
                state["commit_count"] = count
                if branch_alive:
                    branch_evidence = f"branch commits {prev or 0}→{count}"

        # ── 活性证据 b：尾部窗口 tool_result 流量 ──
        traffic_alive = self._turn_traffic_active(run_file)
        evidence_parts = []
        if branch_alive:
            evidence_parts.append(branch_evidence or "branch commits present")
        if traffic_alive:
            evidence_parts.append(
                f"tool_result traffic in last {int(TURN_EXTENSION_WINDOW_SECONDS)}s")

        if branch_alive or traffic_alive:
            new_index = turn_extensions_used + 1
            return {
                **base,
                "action": "extend",
                "extension_index": new_index,
                "evidence": " or ".join(evidence_parts) or "liveness evidence",
                "new_turn_cap": (max_turns or 0) + new_index * turn_step,
            }
        return {
            **base,
            "action": "kill",
            "evidence": (
                "no liveness: no branch commits and no tool_result traffic "
                f"within {int(TURN_EXTENSION_WINDOW_SECONDS)}s"),
            "new_turn_cap": (max_turns or 0) + turn_extensions_used * turn_step,
        }

    def _turn_traffic_active(self, run_file: Path,
                             window_seconds: float = TURN_EXTENSION_WINDOW_SECONDS
                             ) -> bool:
        """尾部窗口内 run 文件是否有新 tool_result 流量（design D2 活性证据 b）。

        读文件尾部 64KiB（与 SessionTracker._extract_session_id 同窗口径），
        逐行解析：``_entry_is_tool_result``（统一识别——真实转录以 ``user``
        事件包裹 ``tool_result`` content block 承载，兼容顶层 ``tool_result``
        事件）且 timestamp 落在 ``now - window_seconds`` 内 → 有流量活性。
        事件无时间戳时回退文件 mtime 判定（与 liveness._liveness_snapshot
        同口径，纯 stderr 流不失真）。文件缺失/不可读 → False（无流量活性）。
        """
        cutoff = time.time() - max(0.0, window_seconds)
        try:
            size = run_file.stat().st_size
            if size == 0:
                return False
            with run_file.open("rb") as f:
                if size > 65536:
                    f.seek(size - 65536)
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return False
        mtime_ok = False
        try:
            mtime_ok = run_file.stat().st_mtime >= cutoff
        except OSError:
            pass
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if not _entry_is_tool_result(entry):
                continue
            ts = self._parse_event_timestamp(entry)
            if ts is None:
                if mtime_ok:
                    return True  # 无时间戳：文件在窗口内已写入即算流量
                continue
            if ts >= cutoff:
                return True
        return False

    def _execute_agent(self, spec_name: str, agent_type: str, run_id: str,
                       pre_wt_path: Path | None = None,
                       conflict_summary: dict | None = None) -> AgentRunResult:
        """Core agent execution logic with retry support.

        fix-fenix-token-waste：
        - 每次 attempt 使用独立 run_id（-a<attempt>），产物文件与尝试一一对应
        - implementer 失败重试复用同一 worktree + `claude --resume` 续跑，不从零
          全量重跑；其余 agent_type 维持每次全新 worktree
        - max_turns 在 _run_claude 内强制

        add-provider-failover（design D1/D2/D3/D4/D5）：
        - 该 agent_type 的 provider 分配为**按序候选链**；每次 attempt 启动前用
          _select_chain_candidate 选首个未冷却候选（链指针按 agent_type 记忆于本实例）。
        - 切换类错误（classify_switch_error）失败 → 该 provider 进入 switch 短冷却，同 run
          后续 attempt 自动前进到下一候选；仅当 provider 未变时才 --resume 原会话
          （fix 跨 provider resume：session 在旧 CLAUDE_CONFIG_DIR，切换后续跑必然
          'No conversation found' 秒挂）；4xx 配额类维持既有熔断不前进。
        - 全链冷却 → 直接失败返回（chain_exhausted，不启动进程、不消耗 spec 重试）。
        - 切换后 CLAUDE_CONFIG_DIR 隔离目录随候选同步切换；run jsonl 写 provider_marker；
          AgentRunResult 带 provider_used/model_used；每 provider 当日计数超阈值告警。

        add-merge-back-repair-lane（D5）：repair run 传入 ``pre_wt_path``
        （调度层解析好的实现分支载体 worktree）与 ``conflict_summary``
        （prompt 注入）。pre_wt_path 非 None 时**不创建新 worktree**，
        直接在该 worktree 内工作——repair 原地修复语义。

        verify-process-lifecycle（D1/D2 终态收割）：运行作用域维护 used_wts
        （本 run 创建/复用的 wt_path）与 handed_off（deliberate keep 集合——
        fast-track/repair 延迟分支、keep_for_reuse、取消 keep）。任意终态
        （成功/失败/取消/frozen 早退/chain_exhausted/熔断拦截/日限 raise/未预期
        异常）由本方法 finally 对 ``used_wts - handed_off`` 且仍在注册表的条目
        执行收割（_v2_stop_for_worktree + _kill_worktree_strays，幂等，双调无害）。
        """
        used_wts: set = set()
        handed_off: set = set()
        try:
            return self._execute_agent_inner(
                spec_name, agent_type, run_id,
                pre_wt_path=pre_wt_path, conflict_summary=conflict_summary,
                used_wts=used_wts, handed_off=handed_off,
            )
        finally:
            try:
                self._v2_harvest_used_worktrees(used_wts, handed_off)
            except Exception as e:
                self.logger.warning(
                    "agent_runner", f"终态收割异常（不阻断结果返回）: {e}")

    def _execute_agent_inner(self, spec_name: str, agent_type: str, run_id: str,
                             pre_wt_path: Path | None = None,
                             conflict_summary: dict | None = None,
                             used_wts: set = None,
                             handed_off: set = None) -> AgentRunResult:
        """派发循环主体（verify-process-lifecycle）：维护收割集合并返回结果。

        收割义务由外层 _execute_agent 的 try/finally 承担；本层仅登记
        used_wts（本 run 创建/复用的 wt_path）与 handed_off（有意交接集合），
        不自行清理——任意终态漏网（异常/早退）都回到外层 finally 收口。
        """
        if used_wts is None:
            used_wts = set()
        if handed_off is None:
            handed_off = set()
        max_retries = self._get_config("agents.max_retries", 3)
        start_time = time.time()

        # ── R0: 跨 attempt 共享状态对象（design D3 _AttemptState）─────────
        # 逐字段映射原 14 个局部标量，为后续方法提取提供显式传参载体。
        # 当前阶段（Task 4.1）：创建实例并映射初始值，保留原同名局部变量
        # 作为 st 字段的别名——函数体读写点暂不改为 st.xxx（等价搬移），
        # 后续提取方法时（4.2-4.6）逐块替换读写点为 st.xxx。
        st = _AttemptState(
            wt_path=pre_wt_path,
            provider_name=None,
            model=None,
            chain_cursor=-1,
            last_provider_used=None,
            kept_wt_path=None,
            usage_info=self._extract_usage_info(None),
            turns=0,
            cancelled_flag=False,
            cancel_reason="",
            shutdown_interrupted=False,
        )
        # 别名：原变量名 → st 字段（保留，函数体暂不改为 st.xxx）
        wt_path = st.wt_path
        session_id = st.session_id
        session_provider = st.session_provider
        chain_cursor = st.chain_cursor
        last_provider_used = st.last_provider_used
        kept_wt_path = st.kept_wt_path
        provider_name = st.provider_name
        model = st.model
        usage_info = st.usage_info
        turns = st.turns
        self._last_model_used = None  # 用于 model_changed 日志留痕（design D3）
        cancelled_flag = st.cancelled_flag
        cancel_reason = st.cancel_reason
        shutdown_interrupted = st.shutdown_interrupted

        for attempt in range(1, max_retries + 1):
            attempt_run_id = f"{run_id}-a{attempt}"
            # ── attempt 顶守卫（frozen / 取消旗标，见 _attempt_top_guards）──
            _early = self._attempt_top_guards(
                spec_name=spec_name, agent_type=agent_type,
                run_id=run_id, attempt=attempt, max_retries=max_retries,
                start_time=start_time, turns=turns, usage_info=usage_info,
                st=st, handed_off=handed_off,
            )
            if _early is not None:
                return _early
            cancel_reason = st.cancel_reason
            kept_wt_path = st.kept_wt_path
            wt_path = st.wt_path
            provider_name = st.provider_name
            model = st.model
            usage_info = st.usage_info
            turns = st.turns
            # cli-retry-backoff：秒挂按 attempt 实际存活时长判定（进程时长近似，
            # 包含 worktree 创建到失败，60s 级判定不敏感于准备开销）。
            attempt_started_at = time.time()
            self.logger.info(
                "agent_runner",
                f"Running {agent_type} for '{spec_name}' (attempt {attempt}/{max_retries})",
                {"run_id": attempt_run_id},
            )

            # Check daily run limit
            self._check_daily_limit()

            # ── 候选链解析与选择（add-provider-failover，见 _resolve_provider_candidate）──
            provider, model, chain, _early = self._resolve_provider_candidate(
                spec_name, agent_type, run_id, attempt_run_id, start_time,
                turns, usage_info, st,
            )
            if _early is not None:
                return _early
            provider_name = st.provider_name

            # ── R3: worktree 复用/新建（等价搬移，D1 R3 表，部分可提取）────────
            # 路径校验 / create 失败重试让位 / used_wts 登记 / dev-server /
            # provider_marker / 路由地图。跨边界 continue（create 失败重试）
            # 与 return（让位/失败）经返回值回传，调用者据以决策。
            wt_path, reuse_worktree, _early, _do_continue = self._prepare_worktree(
                spec_name=spec_name, agent_type=agent_type,
                attempt=attempt, attempt_run_id=attempt_run_id,
                max_retries=max_retries, start_time=start_time,
                turns=turns, usage_info=usage_info,
                provider_name=provider_name, model=model,
                wt_path=wt_path, run_id=run_id,
                st=st, used_wts=used_wts,
            )
            if _do_continue:
                continue
            if _early is not None:
                return _early
            last_provider_used = st.last_provider_used

            # ── 观测：run jsonl 写 provider_marker（design D5 / spec failover-dispatch） ──
            # attempt 启动时写入，指明所用 provider/model 与链内下标，事后可追溯实际网关。
            if provider_name is not None:
                self._write_provider_marker(
                    attempt_run_id, spec_name, agent_type,
                    provider_name, model, st.chain_cursor, len(chain),
                )

            # ── 路由地图生成（add-planner-efficiency：planner-route-map 1.1） ──
            # planner 阶段以 impl worktree 为源执行项目声明生成器（HEAD 键控复用、
            # fail-open）。在 prompt 组装前调用——地图是 planner 出题时的入口索引，
            # 必须在提示词注入前就绪（design D1 生成点=阶段1 进入处）。生成器缺失/
            # 失败/超时不阻塞派发（planner 回退逐轮 grep 现状）。judge 不生成地图
            # （判定不出题，无需入口索引）。
            if agent_type == "planner-plan" and wt_path is not None:
                try:
                    ensure_route_map(wt_path, self.project_root, self.logger)
                except Exception as e:
                    self.logger.warning(
                        "agent_runner",
                        f"route-map 生成异常（fail-open，不阻断 planner 派发）: {e}",
                    )


            # ── 原地重试子循环（fix-provider-transient-backoff D1） ──
            # 瞬断类失败时同一 attempt 内指数退避重试：provider 不变、不触发 switch
            # 冷却、不推进 chain_cursor、不递增 attempt 计数。run_id 加 r{n} 后缀
            # 产生独立产物文件；session 从上一子产物提取续 --resume。
            transient_retries = 0  # 本 attempt 已原地重试次数（预算 = 退避序列长度）
            transient_budget = self._parse_transient_backoff_schedule(
                self._get_config("agents.transient_backoff_schedule", "30,60,120"))
            resume_failures = 0  # 连续 resume 失败次数（≥2 后本次 attempt 改全新会话）
            sub_run_id = (attempt_run_id if transient_retries == 0
                          else f"{attempt_run_id}-r{transient_retries}")

            while True:
                if transient_retries > 0:
                    # 换新 sub_run_id = 弃置旧产物文件（fix-retry-orphan-active-runs
                    # 交叉引用）：两处原地重试通道（provider 瞬断 / artifact-gate）
                    # 在 transient_retry 落盘后均已向旧文件补写 superseded 终态，
                    # 故此处换新不留下无终态尸体；daemon 退避窗口内死亡由
                    # interrupted 补写接续（末行仍终态）。
                    sub_run_id = f"{attempt_run_id}-r{transient_retries}"
                try:
                    if agent_type == "repair":
                        # repair prompt 注入冲突摘要（add-merge-back-repair-lane D5）
                        prompt = self._build_prompt(
                            spec_name, agent_type, detail=conflict_summary or {},
                            wt_path=wt_path,
                        )
                    else:
                        prompt = self._build_prompt(
                            spec_name, agent_type, wt_path=wt_path)
                    env_overrides: Dict[str, str] = {}
                    # add-worktree-test-server（D1 注入）：把该 worktree 专属 dev-server 地址
                    # 注入 agent 运行环境，使 Playwright baseURL 指向 worktree 副本而非主 8787。
                    # 未启动 dev-server（端口冲突/启动失败）时不注入，测试回退缺省 8787。
                    env_overrides.update(self._v2_inject_env(wt_path))
                    if provider is not None:
                        env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
                        env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
                        env_overrides["ANTHROPIC_MODEL"] = model
                        # add-agent-llm-isolation：Provider 生效时完全隔离——CLAUDE_CONFIG_DIR
                        # 指向独立配置目录，彻底绕过 ~/.claude/settings.json 的 env 覆盖，
                        # 使 Provider 的 baseurl/apikey/model 绝对生效（spec D1）。
                        # add-provider-failover：隔离目录随候选同步切换（design D4 / task 3.2）。
                        env_overrides["CLAUDE_CONFIG_DIR"] = str(
                            self._ensure_agent_config_dir(provider["name"])
                        )
                        # 注入 provider 自定义环境变量（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）
                        for k, v in (provider.get("env") or {}).items():
                            env_overrides[k] = v
                        model_override = model
                    else:
                        # 未分配 agent（含 Administrator）走默认网关（cc-switch），--model 用
                        # 官方模型名常量，由 cc-switch 网关自行映射到可用模型。
                        model_override = DEFAULT_GATEWAY_MODEL
                    output, turns, run_session_id, usage_info = self._run_claude(
                        prompt, wt_path, sub_run_id, model_override, env_overrides,
                        resume_session_id=self._resumable_session_id(
                            session_id, session_provider, provider_name, reuse_worktree,
                        ),
                        max_turns=self._get_config("agents.max_turns", 300),
                        spec_name=spec_name,
                        agent_type=agent_type,
                    )
                    if run_session_id:
                        session_id = run_session_id
                        session_provider = provider_name
                    # fix-impl-resultfile-contract-gap D4：实现者车道 fenced-JSON
                    # 结果捞回——run 自然收工（_run_claude 正常返回）但结果文件
                    # 未落盘时，从转录末轮 fenced JSON 代写落盘。插入点 MUST 在
                    # 拷回块之前：既有拷回块按 agent_type 注入 role/spec 戳并写
                    # 主树副本，捞回若在其后执行，代写文件将不带 role 且主树无
                    # 副本（与「落盘视图同构」要求相悖）。wt_path 不可得时 no-op。
                    if agent_type in ("implementer", "fast-track") and wt_path is not None:
                        self._salvage_impl_result(
                            spec_name, sub_run_id, wt_path, agent_type)
                    # fix-verdict-read-failclosed D1（拷回前置）：_run_claude 返回后、
                    # 产物硬门**之前**立即拷回 worktree 验证产物——门检对象必须是本轮
                    # run 真实写出的结果文件。历史事故（add-verify-contract-autodraft）：
                    # 拷回晚于门检，门验到主树上一轮残留旧合法文件而放行，随后拷回把
                    # 非法 JSON（裸换行）落到主树 → 读侧 fail-open 放行 → auto-push。
                    # 语义：主树缺失或 worktree 版本 mtime 较新才拷贝（mtime 守卫与
                    # 原「成功时拷回」块相同，防止 worktree 复用继承的陈旧产物回灌覆盖
                    # 主树较新的冻结场景集）；目录不存在零动作。拷回幂等、前置无副作用。
                    # evo-verifier-result-single-source R2（写入隔离）：主树共享文件是
                    # 跨 agent 共享单例，拷回时按 agent_type 注入 role 与 spec 戳——
                    # 裁决读侧只认 role=verifier 的共享文件，implementer/planner/judge/
                    # repair 的残留（含旧格式无 role）一律不采信为验证裁决。JSON 无法
                    # 解析时维持原始字节拷回（不注入，避免破坏字节；下游产物硬门会
                    # 拦截非法 JSON，读侧按 parse 归因）。
                    self._copyback_run_result(spec_name, agent_type, wt_path)
                    self._copyback_verify_progress(wt_path, spec_name)
                    # add-judge-artifact-gate D1：planner 产物存在性硬门——成功判定
                    # 从「进程 exit 0」升级为「exit 0 且结果文件落盘且可解析」；
                    # 不满足抛 AgentArtifactGateError，落入下方瞬态退避重试通道
                    # （复用 fix-provider-transient-backoff，不消耗 validate_report
                    # 的「裁决重试一次」预算）。
                    gate_err = self._check_agent_result_artifact(
                        spec_name, agent_type, run_started_at=attempt_started_at,
                        wt_path=wt_path, is_resumed_worktree=reuse_worktree)
                    if gate_err:
                        raise AgentArtifactGateError(gate_err)
                    success = True
                    error = None
                    break  # 原地重试子循环：成功退出 while
                except RunCancelledError as e:
                    # add-run-cancel D5：RunCancelledError 专用捕获——不重试、不计秒挂、
                    # 不触发 provider 链切换，直接返回 cancelled=True 失败结果。
                    # 取消旗标已在 _run_claude 轮询环内确认并清理 _running_agents，
                    # 此处只负责结果收口。
                    output = ""
                    turns = 0
                    success = False
                    cancelled_flag = True
                    cancel_reason = e.reason
                    error = CANCELLED_BY_ADMIN_ERROR_PREFIX + (f": {e.reason}" if e.reason else "")
                    self.logger.info(
                        "agent_runner",
                        f"{agent_type} for '{spec_name}' run 被人工取消"
                        f"（attempt {attempt}）：{error}",
                    )
                    usage_info = self._extract_usage_info(None)
                    break  # 原地重试子循环：取消退出 while
                except AgentArtifactGateError as e:
                    # add-judge-artifact-gate D1：exit 0 但产物缺失/为空/非法 JSON
                    # → 按瞬态失败走既有原地退避重试（见 _handle_artifact_gate_retry）。
                    # 跨边界 return（让位）/ continue（原地重试）/ break（预算耗尽）
                    # 经返回值驱动，调用者据此决策（D2）。
                    output = ""
                    turns = 0
                    success = False
                    (error, transient_retries, _gate_yielded,
                     _gate_retry, _gate_break) = self._handle_artifact_gate_retry(
                        e, spec_name=spec_name, agent_type=agent_type,
                        run_id=run_id, attempt=attempt,
                        attempt_run_id=attempt_run_id, sub_run_id=sub_run_id,
                        provider_name=provider_name, model=model, wt_path=wt_path,
                        transient_retries=transient_retries,
                        transient_budget=transient_budget,
                        start_time=start_time, turns=turns,
                        usage_info=usage_info,
                    )
                    if _gate_yielded is not None:
                        return _gate_yielded
                    if _gate_retry:
                        continue
                    if _gate_break:
                        break  # 原地预算耗尽 → 退出 while，attempt 层继续重试
                except Exception as e:
                    output = ""
                    turns = 0
                    success = False
                    error = str(e)
                    # ── shutdown-interrupted 守卫（2026-09-09 事故）──
                    # 框架主动终止/daemon 濒死期间的失败不是网关的错：不做瞬断
                    # 判定、不排原地重试、不记瞬断熔断。SIGTERM 死法（exit≠0 +
                    # 无 result + stderr 仅 [claude-code: 诊断行）会被通道2 误判
                    # provider-transient——排僵尸原地重试与下一 daemon recovery
                    # 重派赛跑、污染全局瞬断指纹计数。shutting_down 置位早于一切
                    # SIGTERM（无竞态主信号）；产物 interrupted 标记为辅（覆盖
                    # 外部终止已带标记的形态）。先于 _record_instant_fail：濒死
                    # 期间的快速死亡不计 spec 秒挂计数。
                    if self.shutting_down or self._run_was_interrupted(
                            self.project_root / ".fenix" / "runs"
                            / f"{sub_run_id}.jsonl"):
                        error = f"[shutdown-interrupted] {error}"
                        shutdown_interrupted = True
                        usage_info = self._extract_usage_info(None)
                        self.logger.warning(
                            "agent_runner",
                            f"{agent_type} for '{spec_name}' terminated by daemon "
                            f"shutdown (attempt {attempt}) — skip transient "
                            f"classify/retry (shutdown-interrupted guard)",
                        )
                        break  # 原地重试子循环：退出 while，attempt 层收口
                    # evo-sigterm-source-tracking-cooldown：信号死法来源判定
                    #（闭集）。已在 shutdown 守卫之后——shutting_down/产物
                    # interrupted 先行短路；框架自身终止（supervision 超时/
                    # 轮次上限强杀）与 cancel 路径各自排除；其余 143/负信号 →
                    # 注入 [signal-kill: …] 标签并计入该 spec 信号冷却计数。
                    # 先于 _record_instant_fail：信号死法若同时是秒挂，两条
                    # 通道对同一事件各自计数（双记仅累加，冷却截止互不覆盖）。
                    error = self._record_signal_kill_or_label(
                        spec_name, error, getattr(e, "exit_code", None))
                    # cli-retry-backoff（2.1）：attempt 失败按存活时长判定秒挂并累计。
                    # 仅「进程确实启动过」的失败才判定（worktree 创建失败等进程未起的
                    # 分支走上方 return/continue，不进入本法）；框架主动 SIGTERM 由
                    # _run_was_interrupted 识别不计入。
                    self._record_instant_fail(
                        spec_name,
                        time.time() - attempt_started_at,
                        self.project_root / ".fenix" / "runs" / f"{attempt_run_id}.jsonl",
                    )
                    # add-cost-observability（D1）+ add-turn-limit-anchor-c（D4）：
                    # _run_claude 抛错（超时/kill/非 0 退出/rc==0 但 result 标记
                    # error），stream-json 终态已被丢弃，usage 不可观测（unobserved
                    # 语义，非确认为零——对照 a2 实测成本证明真实消耗大概率非零），
                    # 仅 DEBUG 留痕。文案不得再写「tokens counted as 0」防审计误导。
                    usage_info = self._extract_usage_info(None)
                    self.logger.debug(
                        "agent_runner",
                        f"{agent_type} for '{spec_name}' ended in error — usage "
                        f"unobserved (no result terminal event; real consumption "
                        f"likely non-zero, add-cost-observability): {error}",
                    )
                    # 4xx 熔断计数 + 瞬断判定（见 _record_4xx_or_transient）
                    error, is_transient, _may_switch = self._record_4xx_or_transient(
                        error, provider_name, agent_type,
                        getattr(e, "stderr_lines", None),
                        getattr(e, "exit_code", None),
                        getattr(e, "has_result", None),
                    )
                    # 瞬断原地退避重试（见 _maybe_in_place_retry；跨边界
                    # continue 回到 while 顶部 / return 让位经返回值驱动，D2）。
                    transient_retries, _yielded, _do_retry = self._maybe_in_place_retry(
                        spec_name=spec_name, agent_type=agent_type,
                        run_id=run_id, attempt=attempt,
                        attempt_run_id=attempt_run_id, sub_run_id=sub_run_id,
                        provider_name=provider_name, model=model, wt_path=wt_path,
                        is_transient=is_transient,
                        transient_retries=transient_retries,
                        transient_budget=transient_budget,
                        start_time=start_time, turns=turns,
                        usage_info=usage_info,
                    )
                    if _yielded is not None:
                        return _yielded
                    if _do_retry:
                        continue  # 回到 while 顶部重跑同一 attempt（新 sub_run_id）
                    # 非瞬断或原地预算耗尽 → 现行切换逻辑
                    # add-provider-failover（design D2/D3）：切换类错误 → 该 provider
                    # 进入 switch 短冷却，同 run 后续 attempt 前进到下一候选（跨
                    # provider 不 resume，见 _resumable_session_id）。
                    # 4xx 配额/鉴权类不触发（维持既有熔断语义、链指针不动）。
                    if _may_switch and self.classify_switch_error(error):
                        self._record_switch_cooldown(provider_name)
                        # 仅当链上还有后续候选才前进指针；否则保持当前（全链耗尽将
                        # 在下一 attempt 的 _select_chain_candidate 中判定为 chain_exhausted）。
                        if st.chain_cursor + 1 < len(chain):
                            st.chain_cursor += 1
                    # fix-provider-transient-backoff（D2）：implementer 失败后从产物尾部
                    # 提取 session_id 供续跑——全 agent_type 均提取（attempt 间 worktree
                    # 保留扩展到全部 agent_type，session 随同现场保留）。
                    if error and agent_type != "repair":
                        run_file = self.project_root / ".fenix" / "runs" / f"{sub_run_id}.jsonl"
                        sid = self._extract_session_id(run_file)
                        if sid:
                            session_id = sid
                            session_provider = provider_name
                    # fix 跨 provider resume：resume 报「会话不存在」说明该 session_id 已失效
                    # （典型：上一次 attempt 切换了 provider，session 在旧 CLAUDE_CONFIG_DIR 里），
                    # 若不清除，后续 attempt 会带着死 id 反复秒挂、烧尽全部重试。
                    if error and "No conversation found with session ID" in error:
                        resume_failures += 1
                        session_id = None
                        session_provider = None
                        # 连续 2 次 resume 失败后本次 attempt 剩余重试改全新会话
                        if resume_failures >= 2:
                            self.logger.warning(
                                "agent_runner",
                                f"Resume dead session x{resume_failures} for '{spec_name}' — "
                                f"switching to fresh session for remaining in-place retries",
                            )
                    break  # 非瞬断（或预算耗尽）退出 while 循环

            # 记录分支名（在 cleanup 之前，cleanup 会从 _wt_branches 中移除）
            branch = self.worktree_manager.get_branch_name(wt_path) if success else None

            if success:
                return self._finalize_success(
                    spec_name=spec_name, agent_type=agent_type,
                    run_id=run_id, attempt_run_id=attempt_run_id,
                    attempt=attempt, start_time=start_time,
                    turns=turns, usage_info=usage_info,
                    provider_name=provider_name, model=model,
                    wt_path=wt_path, output=output,
                    sub_run_id=sub_run_id, branch=branch,
                    handed_off=handed_off,
                )
            else:
                # ── 失败终态分型（见 _finalize_failure_keep，D1 R8）──
                # 重试等待（attempt 内剩余预算）vs 终态 keep 分型。跨边界
                # break 决策经返回值回传；kept_wt_path / wt_path 经状态对象回写。
                st.wt_path = wt_path
                st.kept_wt_path = kept_wt_path
                should_break = self._finalize_failure_keep(
                    spec_name=spec_name, agent_type=agent_type,
                    attempt=attempt, attempt_run_id=attempt_run_id,
                    max_retries=max_retries, start_time=start_time,
                    turns=turns, usage_info=usage_info,
                    provider_name=provider_name, model=model,
                    error=error, cancelled_flag=cancelled_flag,
                    shutdown_interrupted=shutdown_interrupted,
                    st=st, handed_off=handed_off,
                )
                wt_path = st.wt_path
                kept_wt_path = st.kept_wt_path
                if should_break:
                    break

        return self._exhausted_result(
            spec_name, agent_type, run_id, max_retries, start_time,
            error=error, turns=turns, usage_info=usage_info,
            provider_name=provider_name, model=model,
            cancelled_flag=cancelled_flag, shutdown_interrupted=shutdown_interrupted,
            kept_wt_path=kept_wt_path,
        )

    # ── R3: worktree 复用/新建（等价搬移，D1 R3 表，部分可提取）──────
    # 路径校验 / create 失败重试让位 / used_wts 登记 / dev-server / provider_marker
    # / 路由地图。跨边界 continue（create 失败重试）与 return（让位/失败）
    # 经返回值 (do_continue, early_result) 回传，调用者据以决策。
    def _prepare_worktree(self, spec_name: str, agent_type: str, attempt: int,
                          attempt_run_id: str, max_retries: int, start_time: float,
                          turns: int, usage_info: dict, provider_name, model,
                          wt_path, run_id: str,
                          st: _AttemptState, used_wts: set) -> tuple:
        """worktree 复用/新建准备（等价搬移自 R3）。

        返回四元组 (wt_path, reuse_worktree, early_result, do_continue)：
        - do_continue=True → 调用者 MUST continue（create 失败重试等待后回到 attempt
          循环顶部，跳过本次剩余 attempt 内步骤）
        - early_result 非 None → 调用者 MUST return early_result
        - 否则 wt_path 已就绪，reuse_worktree 指示是否复用模式，调用者继续执行
        """
        # fast-track 与 implementer 同语义：跨 attempt 复用同一 worktree（失败续跑）。
        # repair 沿用同一语义：repair run 的 attempt 复用同一个 repair worktree
        #（add-merge-back-repair-lane——worktree 由调度层解析，内部 attempt 不重造）。
        # fix-resume-stale-worktree（todo 09-04 失误#3 处方 3a）：复用前校验路径
        # 真实存在——恢复清理/孤儿回收可能在 attempt 间隙删除目录，盲复用以
        # [Errno 2] 秒挂白烧一次重试额度。失效处置：implementer/fast-track 丢弃
        # 引用改走新建分支路径；repair 载体失效显式失败交还调度层重新解析
        # （repair 语义要求在实现分支内修复，换新分支即失去载体意义）。
        reuse_worktree = False
        if (agent_type in ("implementer", "fast-track", "repair")
                and wt_path is not None):
            if self._worktree_path_valid(wt_path):
                reuse_worktree = True
            elif agent_type == "repair":
                error_msg = (f"repair worktree {wt_path} lost between attempts "
                             f"— need fresh carrier resolution")
                self.logger.error("agent_runner", error_msg)
                self._log_run_metrics(
                    run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                    duration_seconds=time.time() - start_time, turns=turns,
                    usage_info=usage_info, terminal="failure",
                    provider=provider_name, model=model,
                )
                return wt_path, reuse_worktree, AgentRunResult(
                    attempt_run_id, spec_name, agent_type,
                    success=False, duration_seconds=time.time() - start_time,
                    error=error_msg, provider_used=provider_name, model_used=model,
                ), False
            else:
                self.logger.warning(
                    "agent_runner",
                    f"Worktree {wt_path} for '{spec_name}' no longer exists "
                    f"(deleted between attempts) — fresh create instead of resume",
                )
                wt_path = None

        # 跨 attempt 切换打点（design D5 / spec failover-dispatch「切换留痕」）：
        # 本次实际使用的 provider 与上一次不同 → 输出 "provider switched" 日志；
        # 当 model 也发生变更时附带 `model_changed: <old>→<new>`（design D3）。
        # 放在 reuse_worktree 判断之后、运行之前，确保本次 dispatch 的 provider 已确定。
        if st.last_provider_used is not None and provider_name is not None \
                and provider_name != st.last_provider_used:
            switch_msg = (
                f"provider switched {st.last_provider_used} → {provider_name} "
                f"for '{spec_name}'"
            )
            last_model = getattr(self, "_last_model_used", None)
            if model and last_model and model != last_model:
                switch_msg += f" — model_changed: {last_model}→{model}"
            self.logger.info("agent_runner", switch_msg)
        # 记忆本次使用的模型名（供下次 attempt 切换时判定 model_changed，design D3）
        if model:
            self._last_model_used = model
        # 更新记忆：下次 attempt 据以判断切换并打点（design D5）。
        st.last_provider_used = provider_name

        # Create or reuse worktree
        if wt_path is None:
            wt_path = self.worktree_manager.create(spec_name, agent_type)
            if wt_path is None:
                error_msg = "Failed to create worktree"
                self.logger.error("agent_runner", error_msg)
                if attempt < max_retries:
                    time.sleep(5)
                    # fix-restart-dual-dispatch S3/S4：重试前判定——锁活跃
                    #（另一 run 在跑）或人工冻结时放弃，不再换名再造并行 run
                    if self._should_give_up_before_retry(
                                    spec_name, agent_type):
                        self._log_run_metrics(
                            run_id=run_id, spec_name=spec_name,
                            agent_type=agent_type,
                            duration_seconds=time.time() - start_time,
                            turns=turns, usage_info=usage_info,
                            terminal="failure", provider=provider_name,
                            model=model,
                        )
                        return wt_path, False, AgentRunResult(
                            attempt_run_id, spec_name, agent_type,
                            success=False,
                            duration_seconds=time.time() - start_time,
                            error=f"{error_msg} (gave up: parallel run or manual freeze)",
                            provider_used=provider_name, model_used=model,
                        ), False
                    return wt_path, False, None, True  # do_continue
                self._log_run_metrics(
                    run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                    duration_seconds=time.time() - start_time, turns=turns,
                    usage_info=usage_info, terminal="failure",
                    provider=provider_name, model=model,
                )
                return wt_path, False, AgentRunResult(
                    attempt_run_id, spec_name, agent_type,
                    success=False, duration_seconds=time.time() - start_time,
                    error=error_msg, provider_used=provider_name, model_used=model,
                ), False
            # verify-process-lifecycle（D1）：登记本 run 使用的 worktree，
            # 供外层 finally 对未交接集合执行终态收割。
            used_wts.add(wt_path)
            # add-worktree-test-server（D2 派发前启动）：worktree 创建成功后立即
            # 为其启动专属 dev-server，供本次 attempt 的测试请求命中 worktree 副本。
            self._v2_launch_for_worktree(wt_path)
        else:
            self.logger.info(
                "agent_runner",
                f"Reusing worktree {wt_path} for '{spec_name}' (attempt {attempt}, resume)",
            )
            used_wts.add(wt_path)
            if agent_type == "fast-track":
                # 跨 attempt 复用同一 worktree：补记继承痕迹（prompt 注入用）
                self.worktree_manager.mark_reused(
                    spec_name, wt_path,
                    self.worktree_manager.get_branch_name(wt_path) or "",
                )
        return wt_path, reuse_worktree, None, False

    # ── R6 子步 1: 4xx 熔断计数 + 瞬断判定（等价搬移，D1 R6 表）──────
    # 纯副作用：4xx 计数 / 半开探针闭合失败记账 / 瞬断判定 / 全局瞬断指纹记账。
    # 无跨边界 continue/break/return（D2 边界），可安全提取。
    # 模块级名 PROVIDER_CIRCUIT_4XX / PROVIDER_CIRCUIT_THRESHOLD / 实例方法
    # 均保持从 runner.py 模块全局访问（D7 patch 缝隙）。
    def _record_4xx_or_transient(self, error, provider_name, agent_type,
                                 exc_stderr, exc_exit, exc_has_result) -> tuple:
        """4xx 熔断计数 + 瞬断判定（等价搬移自 R6 的 `if provider_name:` 段）。

        返回 (error, is_transient, may_switch)：error 可能被注入
        `[provider-transient]` 前缀（瞬断终态/重试共用标记，
        transient-dispatch-gating D4）；is_transient 供调用者决定是否走原地
        退避重试；may_switch 指示调用者是否可尝试 switch 冷却——原 `else:`
        分支（provider 在位且 code 非 4xx）语义，4xx/无 provider 均不得触发
        switch（维持既有熔断语义、链指针不动）。无跨边界控制流。
        """
        if not provider_name:
            return error, False, False
        # evo-sigterm-source-tracking-cooldown：信号死法（[signal-kill: …] 前缀）
        # 不入瞬断通道——不归 [provider-transient]、不排原地重试、不记全局瞬断
        # 指纹（信号死法的重试与冷却由信号冷却通道（spec 维度）管辖，反复撞
        # 运气至预算耗尽的形态即由该通道熔断）。
        if error and error.startswith("[signal-kill:"):
            return error, False, False
        code = self.parse_api_error_status(error)
        if code is not None and code in PROVIDER_CIRCUIT_4XX:
            # 4xx 熔断计数（fix-stashpop-deadlock：provider-fault-fuse）。
            # 仅对「已分配 provider」且错误文本能解析出 HTTP 4xx 的情况计数（design D4）；
            # 5xx/网络错误不计数（瞬态，走既有 retry）。解析不到 code 视为失败、不计数。
            was_half_open = False
            _circ_st = self.provider_circuits.get(provider_name)
            if _circ_st and _circ_st.get("count", 0) >= PROVIDER_CIRCUIT_THRESHOLD \
                    and _circ_st.get("cooldown_until", 0) > 0 \
                    and _circ_st["cooldown_until"] <= self._now():
                # 半开探针仍 4xx → 重新冷却（design D4），不重复计数。
                was_half_open = True
            self._record_provider_4xx(provider_name, code)
            if was_half_open:
                self._record_provider_probe(provider_name, success=False)
            return error, False, False
        # fix-provider-transient-backoff（D1）：瞬断判定独立于
        # classify_switch_error——降噪后 error 文本可能不含
        # unrecognized_model 字样（D5 已过滤），判定必须依赖原始
        # stderr 信号（异常携带的 stderr_lines / has_result）。
        # resume 死 session（No conversation found）不属网关瞬断，
        # 排除在瞬断判定之外（其处置走下方 session 清理兜底）。
        exc_stderr = exc_stderr or []
        resume_dead = (
            error and "No conversation found with session ID" in error)
        is_transient = (
            not resume_dead and self.classify_transient_error(
                exc_stderr,
                exc_exit if exc_exit is not None else 1,
                bool(exc_has_result)))
        if is_transient:
            # 瞬断终态/重试共用标记（transient-dispatch-gating D4）：写侧统一
            # 在 error 头部注入 `[provider-transient]`，供 dispatch 读侧识别
            # 与终态 keep_for_reuse 判定（task 3.2 / 4.1）。
            if "[provider-transient]" not in error:
                error = f"[provider-transient] {error}"
            # 全局瞬断错误指纹计数（fix-provider-transient-backoff D4）：
            # 每次瞬断失败记账到全局熔断；达阈值触发全局派发冻结。
            # 指纹源用原始 stderr（降噪后 error 可能丢 unrecognized_model
            # 字样），与 D2 判定同源。
            try:
                self.record_transient_break(
                    "\n".join(str(l) for l in exc_stderr) or error)
            except Exception as _break_err:
                self.logger.debug(
                    "agent_runner",
                    f"global transient break 记账失败（不阻断）: {_break_err}",
                )
        return error, is_transient, True  # may_switch：else 分支（provider 在位且 code 非 4xx）

    # ── R6 子步 2: 瞬断原地退避重试（等价搬移，D1 R6 表，Task 5.1）──────
    # 仅处理「is_transient 且原地预算未耗尽」时的瞬断重试段：写 transient_retry
    # / superseded 事件留痕、锚点 B WIP 提交、按退避序列 sleep、退避后让位复查。
    # 跨边界控制流（continue 回 while 顶部 / return 让位）经返回值驱动，调用者
    # MUST 据此决策（D2）：
    #   - yielded 非 None → 调用者 MUST return yielded（让位语义化失败）
    #   - do_retry=True   → 调用者 MUST continue（回到 while 顶部重跑同一 attempt）
    #   - 否则（非瞬断或预算耗尽）→ 调用者继续走现行 switch 冷却逻辑
    # 模块级名（append_run_line / datetime / timezone / time / RETRY_YIELDED_...
    # AgentRunResult）均保持从 runner.py 模块全局访问（D7 patch 缝隙）。
    def _maybe_in_place_retry(self, spec_name: str, agent_type: str, run_id: str,
                              attempt: int, attempt_run_id: str, sub_run_id: str,
                              provider_name, model, wt_path, is_transient: bool,
                              transient_retries: int, transient_budget: list,
                              start_time: float, turns: int, usage_info: dict) -> tuple:
        """瞬断原地退避重试决策（等价搬移自 R6 的 `if (is_transient ...)` 段）。

        返回三元组 (transient_retries, yielded, do_retry)：
        - yielded 非 None → 调用者 MUST return yielded（重派前复查命中让位）
        - do_retry=True → 调用者 MUST continue（原地重试，新 sub_run_id）
        - 否则 → 非瞬断或预算耗尽，调用者走现行 switch 冷却逻辑。
        """
        if not (is_transient and transient_retries < len(transient_budget)):
            return transient_retries, None, False
        # 原地退避重试：写 transient_retry 事件留痕，按退避序列
        # 下一档 sleep，然后 while 循环顶部以同 provider 重跑该
        # attempt（不递增 attempt、不触发 switch 冷却、不改 chain_cursor）。
        backoff = transient_budget[transient_retries]
        transient_retries += 1
        append_run_line(
            self.project_root / ".fenix" / "runs"
            / f"{sub_run_id}.jsonl", {
                "type": "transient_retry",
                "spec": spec_name,
                "provider": provider_name,
                "backoff_seconds": backoff,
                "retry_number": transient_retries,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        # fix-retry-orphan-active-runs D1：superseded
        # 终态补写——本文件末行恒为终态，恢复「终态后置」
        # 不变量。写侧紧跟 transient_retry = 本文件终态，
        # 重试在新 sub_run_id 文件继续（runner.py:1922
        # 换新注释处交叉引用）；daemon 退避窗口内死亡
        # 由 interrupted 补写接续（末行仍终态）。
        append_run_line(
            self.project_root / ".fenix" / "runs"
            / f"{sub_run_id}.jsonl", {
                "type": "superseded",
                "spec": spec_name,
                "provider": provider_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        self.logger.warning(
            "agent_runner",
            f"Transient error for '{spec_name}' (attempt {attempt}, "
            f"provider {provider_name}) — in-place retry "
            f"{transient_retries}/{len(transient_budget)} "
            f"after {backoff}s backoff (fix-provider-transient-backoff)",
        )
        # 锚点 B（add-impl-wip-checkpoint D3）：transient_retry
        # 记录写后、sleep 前的静默窗口 WIP 提交——即便 daemon 在
        # 退避窗口内死亡，分支上已有可恢复提交（无载体则跳过）。
        self._wip_checkpoint_before_backoff(spec_name, wt_path)
        time.sleep(backoff)
        # fix-verdict-dedup-resynthesis D4：退避期间 spec
        # 可能被人工/其它链路接管（admin SIGKILL 后 30s 内
        # 置 blocked 即 19:48 事故形态）——重派前复查，
        # 命中即让位（返回语义化失败，不再产生新的
        # transient_retry 重派，token 消耗不再发生）。
        if self._should_give_up_before_retry(
                spec_name, agent_type, check_lock=False):
            self.logger.warning(
                "agent_runner",
                f"Provider-transient retry for '{spec_name}' "
                f"({agent_type}) yields: spec 已被接管，"
                f"放弃重派（fix-verdict-dedup-resynthesis D4）",
            )
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name,
                agent_type=agent_type,
                duration_seconds=time.time() - start_time,
                turns=turns, usage_info=usage_info,
                terminal="failure", provider=provider_name,
                model=model,
            )
            return transient_retries, AgentRunResult(
                attempt_run_id, spec_name, agent_type,
                success=False,
                duration_seconds=time.time() - start_time,
                error=(
                    f"{RETRY_YIELDED_ERROR_PREFIX} spec 已被接管"
                    f"（status 迁出预期态或 frozen/hold），"
                    f"重试让位（fix-verdict-dedup-resynthesis D4）"),
                provider_used=provider_name, model_used=model,
            ), False
        return transient_retries, None, True

    # ── R5: except 产物门（等价搬移，D1 R5 表，Task 5.3）────────────
    # add-judge-artifact-gate D1：exit 0 但产物缺失/为空/非法 JSON → 按瞬态
    # 失败走既有原地退避重试（fix-provider-transient-backoff 通道原样复用，
    # 不新增重试机制；不消耗 validate_report 的「裁决重试一次」预算）。
    # run 已完整执行（exit 0），不计数秒挂；usage 保留 _run_claude 实测值
    # （区别于早期抛错按 0 计）。跨边界控制流（return 让位 / continue 重试 /
    # break 预算耗尽）经返回值驱动，调用者 MUST 据此决策（D2）。
    # 模块级名（classify_and_enrich_artifact_error / append_run_line /
    # datetime / timezone / time / RETRY_YIELDED_ERROR_PREFIX /
    # AgentRunResult）均保持从 runner.py 模块全局访问（D7 patch 缝隙）。
    def _handle_artifact_gate_retry(self, e, spec_name: str, agent_type: str,
                                    run_id: str, attempt: int,
                                    attempt_run_id: str, sub_run_id: str,
                                    provider_name, model, wt_path,
                                    transient_retries: int,
                                    transient_budget: list,
                                    start_time: float, turns: int,
                                    usage_info: dict) -> tuple:
        """except AgentArtifactGateError 处置（等价搬移自 R5 段）。

        返回五元组 (error, transient_retries, yielded_result, do_continue,
        do_break)：
        - yielded_result 非 None → 调用者 MUST return yielded_result（让位）
        - do_continue=True → 调用者 MUST continue（原地重试）
        - do_break=True → 调用者 MUST break（原地预算耗尽，attempt 层继续重试）
        """
        error = str(e)
        self.logger.warning(
            "agent_runner",
            f"Artifact gate failed for '{spec_name}' ({agent_type}): {error}",
        )
        # evo-sigterm-source-tracking-cooldown：产物硬门失败停止全局瞬断**指纹**
        # 记账（对齐 runner.py [terminal-no-commit] carve-out 先例——产物硬门失败
        # 是「格式回退/忘提交/未收工」类而非网关瞬断，不入瞬断指纹通道）。两类
        # 按各自既有契约隔离，MUST NOT 混为一谈：
        # - 任务完成度类（[task-gate] 前缀，result_gate.py:559-716）：MUST NOT
        #   注入 [provider-transient] 标签、MUST NOT 记全局瞬断指纹、MUST NOT
        #   消耗原地瞬态退避预算——重试由既有 gate 降级语义
        #   （TASK_GATE_DEGRADE_THRESHOLD=2）与 attempt 层重试承担；
        # - 结构类（文件缺失/为空/非法 JSON/顶层非对象/status 白名单外，无前缀）：
        #   保留既有原地退避重试与 [provider-transient] 标签（test_agent_runner_
        #   gate.py 契约），仅新增结构类机械归因标签 + 停止全局瞬断指纹记账。
        is_task_gate = error.startswith("[task-gate]")
        is_terminal_nocommit = error.startswith("[terminal-no-commit]")
        if not is_task_gate:
            if "[provider-transient]" not in error:
                error = f"[provider-transient] {error}"
        if not is_task_gate and not is_terminal_nocommit:
            # 结构类机械归因标签（供读侧与任务完成度类区分）
            error = f"[artifact-structural] {error}"
        # fix-impl-resultfile-contract-gap 4.2：结果文件缺失归因——
        # 复用终态机械特征区分「格式回退截断」/「未收工即停」（只改
        # 局部变量 error，MUST NOT 改动传入 record_transient_break
        # 的 str(e)——全局瞬断指纹记账读 str(e)，归因文案不可污染）。
        if agent_type in ("implementer", "fast-track"):
            error = classify_and_enrich_artifact_error(
                self, error, agent_type, sub_run_id)
        # 任务完成度类：不进原地瞬态退避预算 → 退出 while，attempt 层继续重试
        #（不消耗 transient_budget；重试由 gate 降级与 attempt 层承担）。
        if is_task_gate:
            return error, transient_retries, None, False, True
        if transient_retries >= len(transient_budget):
            # 原地预算耗尽 → 退出 while，attempt 层继续重试
            return error, transient_retries, None, False, True
        backoff = transient_budget[transient_retries]
        transient_retries += 1
        append_run_line(
            self.project_root / ".fenix" / "runs"
            / f"{sub_run_id}.jsonl", {
                "type": "transient_retry",
                "spec": spec_name,
                "provider": provider_name,
                "backoff_seconds": backoff,
                "retry_number": transient_retries,
                "reason": "artifact_gate",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        # fix-retry-orphan-active-runs D1：superseded 终态补写
        # ——与 provider 瞬断通道同语义：superseded 紧跟
        # transient_retry = 本文件终态，重试在新 sub_run_id 文件
        # 继续（runner.py:1922 换新注释处交叉引用）。
        append_run_line(
            self.project_root / ".fenix" / "runs"
            / f"{sub_run_id}.jsonl", {
                "type": "superseded",
                "spec": spec_name,
                "provider": provider_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        self.logger.warning(
            "agent_runner",
            f"Artifact gate for '{spec_name}' (attempt {attempt}, "
            f"{agent_type}) — in-place retry "
            f"{transient_retries}/{len(transient_budget)} "
            f"after {backoff}s backoff (add-judge-artifact-gate)",
        )
        # 锚点 B（add-impl-wip-checkpoint D3）：transient_retry
        # 记录写后、sleep 前的静默窗口 WIP 提交——即便 daemon 在
        # 退避窗口内死亡，分支上已有可恢复提交（无载体则跳过）。
        self._wip_checkpoint_before_backoff(spec_name, wt_path)
        time.sleep(backoff)
        # fix-verdict-dedup-resynthesis D4：退避期间 spec 可能被
        # 人工/其它链路接管（status 迁出预期态/frozen/hold）——
        # 重派前复查，命中即让位（返回语义化失败，不再产生新的
        # transient_retry 重派，19:48 事故 $4.77 白烧根因）。
        if self._should_give_up_before_retry(
                spec_name, agent_type, check_lock=False):
            self.logger.warning(
                "agent_runner",
                f"Artifact-gate retry for '{spec_name}' "
                f"({agent_type}) yields: spec 已被接管，"
                f"放弃重派（fix-verdict-dedup-resynthesis D4）",
            )
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name,
                agent_type=agent_type,
                duration_seconds=time.time() - start_time,
                turns=turns, usage_info=usage_info,
                terminal="failure", provider=provider_name,
                model=model,
            )
            return error, transient_retries, AgentRunResult(
                attempt_run_id, spec_name, agent_type,
                success=False,
                duration_seconds=time.time() - start_time,
                error=(
                    f"{RETRY_YIELDED_ERROR_PREFIX} spec 已被接管"
                    f"（status 迁出预期态或 frozen/hold），"
                    f"重试让位（fix-verdict-dedup-resynthesis D4）"),
                provider_used=provider_name, model_used=model,
            ), False, False
        return error, transient_retries, None, True, False

    # ── R1: attempt 顶守卫（等价搬移，D1 R1 表，部分可提取）──────────
    # frozen 终止 / 取消旗标（worktree 三型处置）。写回变量（cancel_reason /
    # kept_wt_path / wt_path）经 _AttemptState 回写，调用者 MUST 在返回后
    # 同步局部变量。返回 AgentRunResult（早退终态）或 None（继续执行）。
    def _attempt_top_guards(self, spec_name: str, agent_type: str, run_id: str,
                            attempt: int, max_retries: int, start_time: float,
                            turns: int, usage_info: dict,
                            st: _AttemptState, handed_off: set):
        """attempt 顶部守卫（等价搬移自 _execute_agent_inner R1）。

        frozen 命中 → 终止重试链返回 frozen 失败结果；取消旗标命中 → worktree
        三型处置（fast-track keep / repair keep / 其余 cleanup）后返回 cancelled
        失败结果。均不进入下一 attempt。写回变量经 st：调用者 MUST 在返回后
        同步局部变量 cancel_reason / kept_wt_path / wt_path。
        """
        # lifecycle-hygiene 4.1：每轮 attempt 启动前统一检查 spec 结构化 frozen
        # 字段——frozen 为真立即终止重试链（不派发 attempt、不创建 worktree），
        # run 以失败收场保留错误记录。覆盖 judge failover 换网关重试等全部重试
        # 路径，不止 worktree 失败路径；未冻结行为零变化。
        if self._spec_is_frozen(spec_name):
            self.logger.warning(
                "agent_runner",
                f"spec '{spec_name}' frozen — 终止 {agent_type} 自动重试链"
                f"（attempt {attempt}/{max_retries}），不派发 attempt",
            )
            # fix-observability-gaps 1.1：frozen 早夭也是终态，写指标（unobserved）
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                duration_seconds=time.time() - start_time, turns=turns,
                usage_info=usage_info, terminal="frozen",
                provider=st.provider_name, model=st.model,
            )
            return AgentRunResult(
                run_id, spec_name, agent_type,
                success=False, duration_seconds=time.time() - start_time,
                error=(f"{FROZEN_TERMINATED_ERROR_PREFIX} — auto-retry terminated "
                       f"(attempt {attempt}/{max_retries})"),
                provider_used=st.provider_name, model_used=st.model,
            )
        # add-run-cancel D3：attempt 循环顶部检查取消旗标（与 frozen 检查同
        # 位置，覆盖 attempt 间隙/准备阶段）——命中立即返回，不派发后续
        # attempt、不创建本 attempt 的 worktree；残留 worktree 按终态失败
        # 同语义清理。
        if self._cancel_is_requested(run_id):
            meta = self._cancel_meta.get(run_id, {})
            st.cancel_reason = meta.get("reason", "")
            self.logger.warning(
                "agent_runner",
                f"run '{run_id}' 取消旗标命中，终止 {agent_type} 重试链"
                f"（attempt {attempt}/{max_retries}），不派发 attempt",
            )
            if st.wt_path is not None:
                self._v2_stop_for_worktree(st.wt_path)
                if agent_type == "fast-track":
                    self.worktree_manager.keep_for_reuse(spec_name, st.wt_path)
                    st.kept_wt_path = st.wt_path
                    # 取消 keep：目录+分支有意保留供下轮复用，不参与终态收割
                    handed_off.add(st.wt_path)
                elif agent_type == "repair":
                    # 终态失败保留现场：dispatch 层负责回收（fallback 清理）
                    st.kept_wt_path = st.wt_path
                    handed_off.add(st.wt_path)
                else:
                    self.worktree_manager.cleanup(st.wt_path, success=False)
            self._cancel_clear(run_id)
            # fix-observability-gaps 1.1：attempt 顶部取消也是终态，写指标
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                duration_seconds=time.time() - start_time, turns=turns,
                usage_info=usage_info, terminal="cancelled",
                provider=st.provider_name, model=st.model,
            )
            return AgentRunResult(
                run_id, spec_name, agent_type,
                success=False, duration_seconds=time.time() - start_time,
                error=(CANCELLED_BY_ADMIN_ERROR_PREFIX
                       + (f": {st.cancel_reason}" if st.cancel_reason else "")),
                cancelled=True,
                provider_used=st.provider_name, model_used=st.model,
                worktree_path=st.kept_wt_path,
                worktree_kept=st.kept_wt_path is not None,
            )
        return None

    # ── R7: 成功终态（等价搬移，D1 R7 表）─────────────────────────────
    # 半开探针闭合 / wt_dirty 取证 / 终态零提交门 / worktree 分型 / token 入账。
    # 纯终态收割：无跨边界 continue/break（attempt 循环直接 return），可提取。
    def _finalize_success(self, spec_name: str, agent_type: str, run_id: str,
                          attempt_run_id: str, attempt: int, start_time: float,
                          turns: int, usage_info: dict, provider_name, model,
                          wt_path: Path, output: str, sub_run_id: str,
                          branch, handed_off: set) -> AgentRunResult:
        """成功终态收割（等价搬移，D1 R7）。

        半开探针闭合 → wt_dirty 取证 → 终态零提交门 → worktree 分型清理 →
        token 入账 → 结构化指标 → 返回 success 结果。
        """
        # 半开探针闭合（fix-stashpop-deadlock）：若该 provider 此前已进入熔断但
        # 冷却已到期（半开），此派发成功即视为网关恢复，闭合熔断（design D4）。
        if provider_name:
            _circ = self.provider_circuits.get(provider_name)
            if _circ and _circ.get("cooldown_until", 0) > 0 and _circ["cooldown_until"] <= self._now():
                self._record_provider_probe(provider_name, success=True)
        # add-worktree-test-server（D2 终态回收）：worktree 清理前先回收其 dev-server。
        # fast-track 例外：成功不清理——硬校验/守卫在 dispatch 层判定，失败时
        # 保留 worktree 供重派继承（worktree-reuse）；通过则由 dispatch 在
        # merge 后统一清理。dev-server 随 dispatch 层处置一并回收。
        wt_dirty: list = []
        if agent_type in ("implementer", "fast-track"):
            # fix-zero-change-blindspot：cleanup 前取证 worktree dirty 状态
            #（仅 implementer / fast-track——零变更哨对两者都生效）。
            _st = subprocess.run(
                ["git", "-C", str(wt_path), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
            if _st.returncode == 0:
                wt_dirty = [l for l in _st.stdout.splitlines() if l.strip()]
        elif agent_type == "repair":
            # repair 现场取证：冲突解决是否已 commit（dispatch 层据此
            # 判断 re-merge-back 前的现场状态，add-merge-back-repair-lane）。
            _st = subprocess.run(
                ["git", "-C", str(wt_path), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
            if _st.returncode == 0:
                wt_dirty = [l for l in _st.stdout.splitlines() if l.strip()]
        # add-impl-terminal-nocommit-gate（D2）：终态零提交门——wt_dirty
        # 取证之后、fast-track/repair 分流之前判定。implementer 正常终态
        # （exit 0 + 合法结果文件）但分支相对 main 零新提交且 worktree 有
        # 未提交产物时，拦截为可恢复错误（复用 AgentArtifactGateError 既有
        # 通道：锚点 B WIP 提交 + 原地退避 + 同 worktree --resume 续做），
        # 替代「成功判定 → cleanup 硬删 → 交付物守卫打回整轮重做」的零提交
        # 死法（2026-09-10 双 SPEC 首轮全丢事故根因补位）。rev-list 失败
        # fail-open 不拦——门自身故障绝不打断正常收口。
        if agent_type == "implementer":
            self._check_terminal_no_commit_gate(
                spec_name=spec_name, agent_type=agent_type,
                wt_path=wt_path,
                branch=self.worktree_manager.get_branch_name(wt_path),
                wt_dirty=wt_dirty, sub_run_id=sub_run_id)
        # add-merge-back-repair-lane：repair 与 fast-track 同语义，
        # 成功不清理 worktree——冲突解决成果仍在分支上，交给 dispatch
        # 层的 re-merge-back 决定终态；多轮 repair 需原地复用现场。
        if agent_type in ("fast-track", "repair"):
            # 延迟清理：worktree 与 dev-server 均由 dispatch 层处置；
            # 有意交接 → 不参与本 run 终态收割
            handed_off.add(wt_path)
        else:
            self._v2_stop_for_worktree(wt_path)
            # 成果继承（fix-redispatch-loop-governance D4）：implementer 成功
            # 路径先 cleanup 再返回（dispatch 层拿到结果时现场已被删除），故 keep
            # 判定必须落在此处、cleanup(success=True) 之前。partial 且诚实退出
            # 收敛**不成立**的 run（确有未申报缺口）将被 spec 层判失败重派——
            # 保留 worktree 现场与分支成果供下轮经 _take_reusable_worktree 认领
            #（同一目录同一分支，不再从零重建）。判据单点复用
            # core.run_task_track.honest_exit_convergence_gap（与 dispatch.
            # _honest_exit_gap 同一实现点，MUST NOT 重写第二套收敛推导）；判定/
            # 保留抛异常 fail-open 走既有 cleanup（保留失败绝不阻断 run 收工）。
            # MUST NOT 影响正常成功推进路径的 cleanup(success=True) 语义。
            if self._should_keep_worktree_for_partial(spec_name, wt_path):
                try:
                    self.worktree_manager.keep_for_reuse(spec_name, wt_path)
                    handed_off.add(wt_path)
                    self.logger.info(
                        "agent_runner",
                        f"partial 非收敛 '{spec_name}'：保留 worktree 供下轮"
                        f"重派继承 {wt_path}",
                    )
                except Exception as e:  # noqa: BLE001 — 保留失败 fail-open
                    self.logger.warning(
                        "agent_runner",
                        f"partial keep 保留失败 '{spec_name}'（fail-open 走既有"
                        f"cleanup）: {e}",
                    )
                    self.worktree_manager.cleanup(wt_path, success=True)
            else:
                # 成功：清理 worktree（保留分支供 merge-back），返回结果
                self.worktree_manager.cleanup(wt_path, success=True)
        duration = time.time() - start_time
        self._daily_run_count += 1
        # cli-retry-backoff（2.1/2.2）：成功收工重置秒挂连续计数（非连续不累积）
        self._reset_instant_fail(spec_name)
        # evo-sigterm-source-tracking-cooldown：成功收工重置信号死法连续计数
        #（连续信号死法链被打断；若该 spec 曾因信号死法进入冷却，冷却到期由
        # dispatch 闸门侧自动恢复，此处只清计数状态）。
        self._reset_signal_kill(spec_name)
        self.logger.info(
            "agent_runner",
            f"{agent_type} succeeded for '{spec_name}'",
            {"run_id": attempt_run_id, "attempt": attempt, "turns": turns,
             "provider": provider_name, "model": model},
        )
        # add-cost-observability（D1）：收工成功 → 累加 usage 到 STATE 内部字段
        self._accumulate_token_usage(spec_name, usage_info)
        # 验证链侧车：planner/judge run 的 usage 逐轮追加（D3）
        self._record_verify_progress_tokens(spec_name, agent_type, usage_info)
        # fix-observability-gaps 1.1：成功收尾写结构化指标（duration/usage/cost）。
        # run_id 记基础 run_id（run 级指标，含全部 attempt 的整条 run 耗时；
        # 读侧按剥 attempt 后缀后的 base 匹配 run 文件）。
        self._log_run_metrics(
            run_id=run_id, spec_name=spec_name, agent_type=agent_type,
            duration_seconds=duration, turns=turns, usage_info=usage_info,
            terminal="success", provider=provider_name, model=model,
        )
        # run 收尾清理取消旗标（add-run-cancel D5：正常完成也清，防泄漏）
        self._cancel_clear(run_id)
        return AgentRunResult(
            attempt_run_id, spec_name, agent_type,
            success=True, duration_seconds=duration,
            turns_used=turns, output=output,
            branch=branch, provider_used=provider_name, model_used=model,
            worktree_dirty=wt_dirty,
            worktree_path=(wt_path if agent_type in ("fast-track", "repair") else None),
        )

    def _should_keep_worktree_for_partial(self, spec_name: str, wt_path) -> bool:
        """「partial 且诚实退出收敛不成立」→ 保留 worktree 供下轮重派继承（D4 判据单点）。

        读 worktree 内结果文件（缺失 → 主树共享文件回退，与 engine._read_implementer_result
        同语义）；``status == "partial"`` 且 ``honest_exit_convergence_gap`` 判
        **不**收敛（缺口有未申报项 / 申报含非法项 / 无申报）→ True。

        判据 MUST 复用 ``core.run_task_track.honest_exit_convergence_gap``（与
        dispatch._honest_exit_gap 同一个实现点），MUST NOT 重写第二套收敛推导
        （否则违反 honest-exit-convergence 的「缺口口径单点」要求，并把读源回退的
        洞重新开在 runner 侧）。任何异常 fail-open 返回 False（走既有 cleanup），
        保留失败不阻断 run 收工（liveness 兜底）。
        """
        try:
            result_path = wt_path / ".fenix-run-result.json"
            if not result_path.exists():
                result_path = self.project_root / ".fenix" / ".fenix-run-result.json"
                if not result_path.exists():
                    return False
            data = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False
            # stamp 严格校验（fail-closed，与 engine._read_implementer_result 同口径）：
            # 共享 .fenix/.fenix-run-result.json 是跨 spec 单例，无 stamp 残留
            # 不得被误采信为当前 spec 的结果（worktree 文件同规则收紧）。
            if data.get("spec") != spec_name:
                return False
            if data.get("status") != "partial":
                # 仅 partial 形态纳入 keep；success/error 走既有 cleanup 语义
                #（正常成功推进路径 cleanup(success=True) 不变）。
                return False
            from core.run_task_track import honest_exit_convergence_gap

            converged = bool(honest_exit_convergence_gap(data, self.project_root, spec_name))
            return not converged
        except Exception as e:  # noqa: BLE001 — 判定异常 fail-open
            self.logger.debug(
                "agent_runner",
                f"partial keep 判定异常（fail-open 走既有 cleanup）'{spec_name}': {e}",
            )
            return False

    # ── R8: 失败终态分型（等价搬移，D1 R8 表）────────────────────────
    # 重试等待 vs 终态 keep 分型。跨边界 break 决策经返回值回传；
    # kept_wt_path / wt_path 经 _AttemptState 回写（调用者 MUST 同步局部变量）。
    def _finalize_failure_keep(self, spec_name: str, agent_type: str,
                               attempt: int, attempt_run_id: str,
                               max_retries: int, start_time: float,
                               turns: int, usage_info: dict,
                               provider_name, model,
                               error, cancelled_flag: bool,
                               shutdown_interrupted: bool,
                               st: _AttemptState, handed_off: set) -> bool:
        """失败终态分型（等价搬移，D1 R8）：重试等待 or 终态 keep。

        返回 True 表示 should_break（cancelled_flag or shutdown_interrupted 触发的
        终态——attempt 循环 MUST break）；返回 False 表示已 sleep(10) 等待重试，
        调用者继续下一轮 attempt。
        方法内通过 st 回写 st.kept_wt_path / st.wt_path，调用者 MUST 同步
        局部变量 kept_wt_path / wt_path。
        """
        self.logger.warning(
            "agent_runner",
            f"{agent_type} failed for '{spec_name}' (attempt {attempt})",
            {"run_id": attempt_run_id, "error": error, "provider": provider_name},
        )
        # 失败后的 worktree 处理（worktree-reuse：fast-track 与 implementer
        # 同语义，跨 attempt 复用同一 worktree 续跑）：
        # - implementer / fast-track / repair 且还有重试：保留 worktree（连同其
        #   dev-server），下次 attempt 续跑；dev-server 随之复用，不重复启停。
        # - fast-track 终态失败：保留目录与分支登记为复用遗产，下轮重派在同一
        #   worktree 继承上一轮成果（不再从零重做）。
        # - repair 终态失败：保留 worktree（add-merge-back-repair-lane：
        #   worktree 生命周期交由 dispatch 层——fallback 或下一轮复用）。
        # - 其他 / 终态失败：清理 worktree 并回收其 dev-server，下次 attempt 全新创建。
        # add-run-cancel D5：取消（cancelled_flag）时不再进入下一 attempt——
        # 走终态清理路径后 break，由循环后的 cancelled 收口返回 cancelled=True。
        if attempt < max_retries and not cancelled_flag \
                and not shutdown_interrupted:
            time.sleep(10)  # Wait before retry
            # fix-provider-transient-backoff（D3）：attempt 间 worktree
            # 保留扩展到全部 agent_type——非 implementer 族复用前仍过
            # frozen/取消检查（见上方 reuse_worktree 判定），不再清工作树。
            # dev-server 随之复用，不重复启停。
            return False
        self._v2_stop_for_worktree(st.wt_path)
        if shutdown_interrupted:
            # daemon 濒死：保留现场交 recovery/排水保全处置——
            # cleanup 会销毁待保全的未提交工作（checkpoint 锚点 A
            # 的保护对象）；keep_for_reuse 的复用认领语义也不适用
            # （续做与否由下一 daemon recovery 单源决定）。
            st.kept_wt_path = st.wt_path
            handed_off.add(st.wt_path)
        elif agent_type == "fast-track":
            self.worktree_manager.keep_for_reuse(spec_name, st.wt_path)
            st.kept_wt_path = st.wt_path
            # 终态失败保留复用遗产：下轮在同一 worktree 继承成果，
            # 目录+分支有意保留 → 不参与终态收割（dev-server 已停）
            handed_off.add(st.wt_path)
        elif agent_type == "repair":
            # 终态失败保留现场：dispatch 层负责回收（fallback 清理）
            st.kept_wt_path = st.wt_path
            handed_off.add(st.wt_path)
        elif error and "[provider-transient]" in error:
            # fix-provider-transient-backoff（D3）：transient 终态失败保留现场
            # 供下轮认领（替代 cleanup(success=False)）——复用遗产机制，
            # 下轮经 _take_reusable_worktree 认领同一目录与分支继承现场。
            # 非 transient 终态失败维持现行清理，避免真实缺陷现场被误续用。
            self.worktree_manager.keep_for_reuse(
                spec_name, st.wt_path, agent_type=agent_type)
            st.kept_wt_path = st.wt_path
            handed_off.add(st.wt_path)
            self.logger.warning(
                "agent_runner",
                f"Transient terminal failure for '{spec_name}' — worktree "
                f"{st.wt_path} kept for reuse (fix-provider-transient-backoff)",
            )
        else:
            self.worktree_manager.cleanup(st.wt_path, success=False)
        st.wt_path = None
        return cancelled_flag or shutdown_interrupted

    # ── R2: 候选链解析与选择（等价搬移，D1 R2 表）─────────────────────
    # 模型分配 → 指针推进 → 全链耗尽/4xx 熔断拦截 → 记当日 attempt。
    # chain_cursor 经状态对象（_AttemptState.chain_cursor）读写（D1 粘合表：
    # R2 写 R2/R4/R7 读）；早退分支（circuit/chain_exhausted）返回 early_result，
    # 调用者 MUST return。返回 (provider, model, chain, early_result)。
    def _resolve_provider_candidate(self, spec_name: str, agent_type: str,
                                    run_id: str, attempt_run_id: str,
                                    start_time: float, turns: int,
                                    usage_info: dict, st: _AttemptState) -> tuple:
        """候选链解析与选择（等价搬移，D1 R2）。

        无 provider 分配（chain 空）→ (None, None, [], None)（默认网关路径）；
        选中未熔断 → (provider, model, chain, None) 并回写 st.provider_name /
        st.model / st.chain_cursor；早退（circuit / chain_exhausted）→
        (None, None, chain, AgentRunResult)，调用者 MUST return early_result。
        """
        chain = self._get_agent_model_assignment(agent_type) or []
        if not chain:
            # 无 provider 分配：走默认网关（cc-switch），无链可选。provider_name=None。
            st.provider_name = None
            st.model = None
            return None, None, chain, None
        # 链指针推进：上次因切换类失败已前移的，保持前移（design D1/D3）；
        # 否则从头选首个未冷却候选。4xx 熔断拦截态也算"不可用"跳过。
        if st.chain_cursor < 0:
            st.chain_cursor = self._select_chain_candidate(chain, spec_name, agent_type)
        if st.chain_cursor < 0:
            # 无可用候选。区分两类根因（design D3 / spec failover-dispatch）：
            # - 全部候选仅因 4xx 熔断（is_circuit_open）被跳过 → 维持既有
            #   "provider circuit open" 错误语义（不污染 error 文本、便于 admin/dashboard
            #   区分 provider 故障），报告首个 4xx 熔断候选。
            # - 否则（含 switch 冷却 / 全链冷却）→ chain_exhausted 失败语义，
            #   不启动进程、不计入 spec 重试消耗。
            first_4xx_open = None
            for (provider, _m) in chain:
                if self.is_circuit_open(provider["name"]):
                    first_4xx_open = provider["name"]
                    break
            if first_4xx_open is not None:
                circuit_err = self._circuit_open_error(first_4xx_open)
                self.logger.warning(
                    "agent_runner",
                    f"Suppressed {agent_type} dispatch for '{spec_name}': {circuit_err}",
                )
                self._log_run_metrics(
                    run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                    duration_seconds=time.time() - start_time, turns=turns,
                    usage_info=usage_info, terminal="circuit",
                    provider=first_4xx_open, model=None,
                )
                return None, None, chain, AgentRunResult(
                    attempt_run_id, spec_name, agent_type,
                    success=False, duration_seconds=time.time() - start_time,
                    error=circuit_err, provider_used=first_4xx_open,
                )
            exhausted_err = (
                f"provider chain exhausted for {agent_type} '{spec_name}': "
                f"all {len(chain)} candidates in switch/4xx cooldown"
            )
            self.logger.error("agent_runner", exhausted_err)
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                duration_seconds=time.time() - start_time, turns=turns,
                usage_info=usage_info, terminal="chain_exhausted",
                provider=None, model=None,
            )
            return None, None, chain, AgentRunResult(
                attempt_run_id, spec_name, agent_type,
                success=False, duration_seconds=time.time() - start_time,
                error=exhausted_err, chain_exhausted=True,
            )
        provider, model = chain[st.chain_cursor]
        st.provider_name = provider["name"]
        st.model = model

        # ── 4xx 熔断拦截（fix-stashpop-deadlock：provider-fault-fuse） ──
        # 仅对当前选中候选生效；若已熔断（冷却未到期），直接失败返回、不启动 claude、
        # 不创建 worktree/autostash、不计入 spec 连续失败重试（design D5）。冷却到期后
        # 首个真实派发作为半开探针（design D4）。
        if self.is_circuit_open(st.provider_name):
            circuit_err = self._circuit_open_error(st.provider_name)
            self.logger.warning(
                "agent_runner",
                f"Suppressed {agent_type} dispatch for '{spec_name}': {circuit_err}",
            )
            # 不创建 worktree、不进入重试计数。直接以熔断错误返回。
            # fix-observability-gaps 1.1：circuit 拦截终态写指标
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                duration_seconds=time.time() - start_time, turns=turns,
                usage_info=usage_info, terminal="circuit",
                provider=st.provider_name, model=st.model,
            )
            return None, None, chain, AgentRunResult(
                attempt_run_id, spec_name, agent_type,
                success=False, duration_seconds=time.time() - start_time,
                error=circuit_err, provider_used=st.provider_name, model_used=st.model,
            )

        # 选中且未熔断 → 计一次当日 attempt（design D5 / spec 4.2），后续跨 attempt
        # 切换打点依赖 last_provider_used。
        self._record_daily_provider_attempt(st.provider_name)
        return provider, model, chain, None

    # ── R9: 循环后收口（D1 R9 表，可无副作用提取）────────────────────
    # 全重试耗尽三型返回 + token 入账。等价搬移自 _execute_agent_inner
    # 的 for 循环后段；参数显式传递 attempt 循环后的最终局部变量值。
    def _exhausted_result(self, spec_name: str, agent_type: str, run_id: str,
                          max_retries: int, start_time: float,
                          error=None, turns: int = 0, usage_info=None,
                          provider_name=None, model=None,
                          cancelled_flag: bool = False,
                          shutdown_interrupted: bool = False,
                          kept_wt_path=None) -> AgentRunResult:
        """全重试耗尽三型返回（等价搬移，D1 R9）：cancelled / shutdown / 全失败。"""
        # All retries exhausted
        duration = time.time() - start_time
        # run 收尾（add-run-cancel D5）：清理取消旗标，防泄漏。
        # cancelled_flag 为 True 时（RunCancelledError 已 break 到此处）
        # 返回 cancelled=True 结果；否则走既有终态失败返回。
        self._cancel_clear(run_id)
        if cancelled_flag:
            # fix-observability-gaps 1.1：取消收尾写结构化指标
            # （run_id 记基础 run_id，读侧按 base 匹配）
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                duration_seconds=duration, turns=turns, usage_info=usage_info,
                terminal="cancelled", provider=provider_name, model=model,
            )
            return AgentRunResult(
                run_id, spec_name, agent_type,
                success=False, duration_seconds=duration,
                error=error,
                cancelled=True,
                provider_used=provider_name, model_used=model,
                worktree_path=kept_wt_path,
                worktree_kept=kept_wt_path is not None,
            )
        if shutdown_interrupted:
            # shutdown-interrupted 终态：error 已带 [shutdown-interrupted] 前缀；
            # usage 按 0（异常早夭同源）且不入账（对齐取消路径，避免濒死写 STATE）。
            # fix-observability-gaps 1.1：中断收尾写结构化指标（含真实 duration）
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                duration_seconds=duration, turns=turns, usage_info=usage_info,
                terminal="shutdown", provider=provider_name, model=model,
            )
            return AgentRunResult(
                run_id, spec_name, agent_type,
                success=False, duration_seconds=duration,
                error=error,
                provider_used=provider_name, model_used=model,
                worktree_path=kept_wt_path,
                worktree_kept=kept_wt_path is not None,
            )
        # add-cost-observability（D1）：终态失败也累加（末次 attempt 的 usage，
        # 异常早夭时为 0），保证预算告警在失败轮同样累计、不漏计。
        self._accumulate_token_usage(spec_name, usage_info)
        # 验证链侧车（D3）：终态失败的 planner run 同样逐轮追加
        self._record_verify_progress_tokens(spec_name, agent_type, usage_info)
        # fix-observability-gaps 1.1：全失败终态写结构化指标
        self._log_run_metrics(
            run_id=run_id, spec_name=spec_name, agent_type=agent_type,
            duration_seconds=duration, turns=turns, usage_info=usage_info,
            terminal="failure", provider=provider_name, model=model,
        )
        return AgentRunResult(
            run_id, spec_name, agent_type,
            success=False, duration_seconds=duration,
            error=f"All {max_retries} attempts failed. Last error: {error}",
            provider_used=provider_name, model_used=model,
            worktree_path=kept_wt_path,
            worktree_kept=kept_wt_path is not None,
        )

    # ── token 累计与预算告警（add-cost-observability D1 / D4）──────────────────

    def _copyback_verify_progress(self, wt_path: Path, spec_name: str) -> None:
        """成功收尾：把 worktree 的 per-spec 验证产物目录逐文件拷回主树同路径。

        add-worktree-verify-progress-copyback（D2 mtime 守卫 / D3 fail-open /
        D4 零动作）：worktree `.fenix/verify-progress/<spec>/` 不存在时直接返回
        （不创建主树目录、不打日志）；存在时逐文件 copy2——主树同路径缺失或
        worktree 版本 mtime 较新才拷贝，主树较新则跳过（防止 worktree 复用继承的
        陈旧产物回灌覆盖主树较新的冻结场景集）。单文件 OSError 仅记 WARNING 后
        继续，不抛出、不阻塞 run 收尾。
        """
        wt_vp = wt_path / ".fenix" / "verify-progress" / spec_name
        if not wt_vp.is_dir():
            return
        root_vp = self.project_root / ".fenix" / "verify-progress" / spec_name
        for src in wt_vp.rglob("*"):
            if not src.is_file():
                continue
            dst = root_vp / src.relative_to(wt_vp)
            try:
                if not dst.exists() or src.stat().st_mtime_ns > dst.stat().st_mtime_ns:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            except OSError:
                self.logger.warning(
                    "agent_runner",
                    f"verify-progress copyback failed for '{spec_name}' "
                    f"(add-worktree-verify-progress-copyback): "
                    f"{src} -> {dst}",
                )

    # ── R4 子段: 结果文件 role/spec 戳拷回（D1 R4 表，零粘合可提取）──────
    # 仅覆盖「worktree .fenix-run-result.json → 主树共享文件」的戳注入 + 拷回
    # 子段（design D2：无写点、无跨边界控制流、无 return——可无副作用提取）。
    # try 体其余部分与末句 break 留循环体内（D2）。模块级名 json / 常量
    # AGENT_TYPE_TO_ROLE 保持从 runner.py 模块全局访问（D7 patch 缝隙）。
    def _copyback_run_result(self, spec_name: str, agent_type: str, wt_path: Path) -> None:
        """把 worktree 的结果文件按 agent_type 注入 role/spec 戳后拷回主树共享文件。

        等价搬移自 _execute_agent_inner 内层 try 体的戳拷回子段（D1 R4）：
        - 主树共享文件是跨 agent 共享单例，拷回时按 agent_type 注入 role 与
          spec 戳（evo-verifier-result-single-source R2 写入隔离）——裁决读侧
          只认 role=verifier 的共享文件。
        - JSON 无法解析时维持原始字节拷回（不注入，避免破坏字节）。
        - OSError 静默（与既有行为一致）；目录不存在零动作。
        """
        wt_result = wt_path / ".fenix-run-result.json"
        root_result = self.project_root / ".fenix" / ".fenix-run-result.json"
        if wt_result.exists():
            try:
                raw = wt_result.read_text(encoding="utf-8")
                role = AGENT_TYPE_TO_ROLE.get(agent_type)
                if role is not None:
                    try:
                        payload = json.loads(raw)
                        if isinstance(payload, dict):
                            payload["role"] = role
                            payload["spec"] = spec_name
                            root_result.write_text(
                                json.dumps(
                                    payload, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            raw = None  # 已注入写盘，跳过原始拷回
                    except (json.JSONDecodeError, ValueError):
                        pass  # 非法 JSON：fall through 原始字节拷回
                if raw is not None:
                    root_result.write_text(raw, encoding="utf-8")
            except OSError:
                pass

    def _run_claude(self, prompt: str, cwd: Path, run_id: str,
                    model_override: str | None = None,
                    env_overrides: Dict[str, str] | None = None,
                    resume_session_id: str | None = None,
                    max_turns: int | None = None,
                    spec_name: str | None = None,
                    agent_type: str | None = None) -> tuple:
        """
        Execute claude CLI with the given prompt, streaming events to disk.

        与旧版 `--output-format json` + subprocess.run 的差异（见 D1 / agent-run-artifacts）：
        - 改用 `subprocess.Popen` + `--output-format stream-json`，将运行期间逐行
          JSON 事件（system/assistant/user/tool_use/tool_result/result）原样追加写入
          `.fenix/runs/<run_id>.jsonl`，供 Web Dashboard 实时轮询。
        - stdout/stderr 各由一条守护线程逐行读取；非 JSON 行（stderr 噪声）以
          `{"type":"stderr","line":...}` 兜底写入，保证产物文件始终可逐行解析。
        - 结束时从流中最后一个 `result` 事件还原 `output`（result 文本）与 `turns`
          （num_turns），与旧版解析结果等价。
        - 超时/kill/非零退出时向产物文件追加 `{"type":"error",...}` 终态行，并仍按
          现状语义抛出 RuntimeError。

        fix-fenix-token-waste：
        - `thinking_tokens` 遥测事件不再落盘（占旧转录 ~75% 的纯噪音）
        - `max_turns` 由本方法强制：统计流中 assistant 事件数，达到上限即 kill，
          按失败路径触发重试（claude CLI 无 --max-turns flag，故在 daemon 侧强制）
        - `resume_session_id` 传入时追加 `--resume`，从失败处续跑而非全量重跑

        Args:
            prompt: The instruction prompt for the agent.
            cwd: Worktree directory the agent operates in.
            run_id: 本次运行唯一 id（如 `impl-<spec>-<ts>-a<attempt>`），决定产物文件名。
            model_override: Pass `--model <value>` explicitly. 这是**实际发给网关的模型名**
                （claude CLI 的 --model 覆盖 ANTHROPIC_MODEL，见 fenixd-sdk-model-routing）。
                已分配 provider 的 agent 传该 agent 的 `model`（网关模型名，如
                deepseek-v4-flash）；未分配（含 Administrator）传 DEFAULT_GATEWAY_MODEL
                （默认网关 cc-switch 的官方模型名）。
            env_overrides: 额外注入到子进程的环境变量（每线程独立 env 副本，不串扰）。
                用于按 agent_type 注入不同 Provider 的 baseurl/apikey/model。
            resume_session_id: 非 None 时以 `--resume <id>` 续跑该 session。
            max_turns: 单次运行轮次上限；达到即 kill（None 表示不限制）。

        Returns: (output, turns_used, session_id)
        """
        # per-agent-timeout-override 3.2：run 生效超时按 agent_type 覆盖值查询
        #（override → 全局 run_timeout_seconds → 3600 回退）。
        timeout = self._effective_run_timeout(agent_type)
        from core.config import ConfigLoader
        # fix-stuck-threshold-unify D5：supervision 激活路径读取 absolute_max 兜底值，
        # 不直接读原始配置（防止与 run 超时脱钩）。返回 None 表示未启用 supervision。
        sup_abs_max = ConfigLoader.effective_supervision_absolute_max_seconds(self.config)
        if sup_abs_max is not None and sup_abs_max < timeout:
            # 护栏兜底已保证 sup_abs_max ≥ run_timeout + 7200，正常不应进此分支；
            # 极端情况下仍以兜底值覆盖，确保 supervision 不早于 run 超时终止运行。
            self.logger.debug(
                "agent_runner",
                f"supervision absolute_max({int(sup_abs_max)}s) 低于 run_timeout({timeout}s)，"
                "以兜底值优先",
            )

        # 每线程独立 env 副本，多 agent_type 并发时环境覆盖互不串扰
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
            # Provider 覆盖生效时清除继承的 ANTHROPIC_AUTH_TOKEN（如 supervisor/tmux 环境
            # 里残留的火山 ark token）。claude-code 认证时 AUTH_TOKEN 优先于 API_KEY，
            # 残留 token 会让请求以错误的 Bearer 认证打到 Provider → 401。
            if "ANTHROPIC_API_KEY" in env_overrides:
                env.pop("ANTHROPIC_AUTH_TOKEN", None)

        # worktree 隔离纵深（2026-09-08 skill 基路径锚定事故）：把项目根与本次
        # worktree 交给 PreToolUse 守卫 hook（block-main-tree-write.py），拦截
        # 「skill 注入的主树绝对路径被模型锚定为项目根」导致的写主树。无 worktree
        # 的 run（cwd == 项目根）置空，hook 全放行、行为不变。
        env["FENIX_RUN_PROJECT_ROOT"] = str(self.project_root)
        env["FENIX_RUN_WORKTREE"] = (
            str(cwd) if str(cwd) != str(self.project_root) else ""
        )

        # 任务清单工具显式启用（2026-09-15 原地修复）。claude CLI 2.1.272 起把
        # TaskCreate/TaskUpdate/TaskGet/TaskList 收窄为「仅第一方模型默认提供」，
        # 网关模型（deepseek-v4-flash / claude-sonnet-5 等）不再默认注入——需
        # CLAUDE_CODE_ENABLE_TODO_TOOLS=1 显式 opt-in（CLI changelog 原文 + 本地
        # 实测：默认 22 工具无 TaskCreate；置 1 后 26 工具有）。整套 run-progress
        # 链路（parse_run_task_done / run_task_progress / dashboard 叠加 /
        # _sync_task_progress 回写 / prompt_builder 条件契约段）全部依赖该工具族，
        # 默认关闭会让实现期间任务进度恒 0/N（无法分辨卡死与正常推进）。此处统一
        # 注入对该族工具「不适用」的第一方模型无副作用（本就默认提供）。
        env["CLAUDE_CODE_ENABLE_TODO_TOOLS"] = "1"

        # Progress dir for verifier to write incremental progress
        progress_dir = self.project_root / ".fenix" / "verify-progress"
        progress_dir.mkdir(parents=True, exist_ok=True)

        # 运行产物目录（.fenix/runs/），加入模板 gitignore，不入版本控制
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{run_id}.jsonl"

        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",  # claude CLI 要求: --print + --output-format=stream-json 必须带 --verbose
            "--add-dir", str(cwd),
            "--add-dir", str(progress_dir),
            "--permission-mode", "bypassPermissions",
        ]
        # 注入 agent 专用 settings（PreToolUse hook：阻止 Read 图片文件）。
        # 模型（deepseek-v4-flash 经本地代理）不支持图像输入，verifier/planner
        # 读截图会把图片送进对话导致 400 整轮失败。
        agent_settings = self.project_root / ".fenix" / "agent-settings.json"
        if agent_settings.exists():
            cmd += ["--settings", str(agent_settings)]
        if model_override:
            cmd += ["--model", model_override]
        if resume_session_id:
            cmd += ["--resume", resume_session_id]

        self.logger.debug(
            "agent_runner",
            f"Running: claude -p '...' --output-format stream-json --add-dir {cwd}"
            + (" (resume)" if resume_session_id else ""),
            {"run_id": run_id, "run_file": str(run_file)},
        )

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # 行缓冲，保证实时可读
            env=env,
            cwd=str(cwd),
        )
        self._running_agents[run_id] = proc

        # 两条守护线程分别读 stdout / stderr，避免单线程 readline 卡死。
        # 共享状态由主线程在 join 之后读取，天然构成 happens-before。
        last_result: Dict[str, Any] = {}
        turn_count = [0]  # 被读线程递增；主线程轮询读取（GIL 保证可见性）
        stdout_lines: list = []
        stderr_lines: list = []

        # ── run 级 API 延迟统计（add-planner-efficiency：run-latency-observability）──
        # 纯读侧采集：`tool_result → 下一个 assistant` 间隔样本（API 往返等待）。
        # sample_state 被 _read_stream 子线程 append，主线程在 join 后读取，
        # 同线程追加+join 后读取无竞态（类 turn_count 同模式）。
        latency_state: dict = {"last_tool_result_ts": None, "samples": []}

        def _read_stream(stream, is_stderr: bool) -> None:
            try:
                for line in iter(stream.readline, ""):
                    line = line.rstrip("\n")
                    if not line.strip():
                        continue
                    if is_stderr:
                        # stderr 噪声：不保证是 JSON，一律按 stderr 兜底写入
                        stderr_lines.append(line)
                        append_run_line(run_file, {"type": "stderr", "line": line})
                        continue
                    stdout_lines.append(line)
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        entry = {"type": "stderr", "line": line}
                    if isinstance(entry, dict):
                        # fix-fenix-token-waste：thinking_tokens 遥测噪音不落盘
                        if (entry.get("type") == "system"
                                and entry.get("subtype") == "thinking_tokens"):
                            continue
                        if entry.get("type") == "assistant":
                            turn_count[0] += 1
                        if entry.get("type") == "result":
                            # 记录最后一个 result 事件（含 num_turns / result 文本 / session_id）；
                            # 落盘推迟到读线程 join 后，保证 result 终态是文件最后一行
                            # （并发 stderr 噪声不会落在其后，Dashboard 状态分类不受干扰）
                            last_result.clear()
                            last_result.update(entry)
                            continue
                        # 延迟样本采集：tool_result → assistant = 一次 API 往返
                        # （tool_result 按 _entry_is_tool_result 统一识别：真实
                        # stream-json 转录以 user 事件包裹 tool_result block
                        # 承载，兼容顶层 tool_result 事件）
                        e_ts = AgentRunner._parse_event_timestamp(entry)
                        if AgentRunner._entry_is_tool_result(entry):
                            if e_ts is not None:
                                latency_state["last_tool_result_ts"] = e_ts
                        elif entry.get("type") == "assistant":
                            if (e_ts is not None
                                    and latency_state["last_tool_result_ts"] is not None):
                                latency_state["samples"].append(
                                    e_ts - latency_state["last_tool_result_ts"])
                                latency_state["last_tool_result_ts"] = None
                    append_run_line(run_file, entry)
            except Exception:
                # 读取线程异常不应导致主流程崩溃；半成品产物仍可被 Dashboard 读取
                pass

        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, False), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, True), daemon=True)
        t_out.start()
        t_err.start()

        # 轮询等待：同时支持超时与 max_turns 强制（claude CLI 无 --max-turns flag）
        returncode = None
        timeout_error = None
        turn_limit_error = None
        started_at = time.time()
        deadline = started_at + timeout
        extensions_used = 0  # 本 run 已续期次数（D3 封闭矩阵）
        # add-turn-limit-anchor-c（design D2/D3）：轮次续期独立计数与当前上限。
        # current_turn_cap 初始 = max_turns，extend 后累加步长；两套续期计数
        # （extensions_used / turn_extensions_used）各自封顶、互不读写。
        turn_extensions_used = 0
        current_turn_cap = max_turns
        # add-run-cancel D1/D3：轮询环每轮检查取消旗标，命中则
        # terminate→grace→kill→写 cancelled 终态行→抛 RunCancelledError
        base_run_id = self._normalize_run_id(run_id)
        cancel_error: RunCancelledError | None = None
        # add-planner-efficiency（run-latency-observability）：run 末延迟摘要文本。
        # 在 finally（读线程 join 后）计算并打日志；失败/取消路径把摘要拼入
        # error 上下文（卡死 vs 慢可判）。
        latency_summary_text = ""
        # add-fast-track-scale-precheck D3：extension 末位自动保全幂等标记。
        # 每个 run 至多触发一次（耗尽预算的最后一个 extension 内），防止
        # remaining < 窗口的每轮轮询重复触发。
        extension_tail_triggered = False
        try:
            while True:
                # ── 取消旗标检查（add-run-cancel D1/D3）──
                # 放在超时检查之前：人工取消优先级高于自动超时，管理员
                # 想终止就不必等超时到点。
                if self._cancel_is_requested(base_run_id):
                    meta = self._cancel_meta.get(base_run_id, {})
                    reason = meta.get("reason", "")
                    by = meta.get("by", "admin")
                    self.logger.info(
                        "agent_runner",
                        f"run '{base_run_id}' 取消旗标命中，"
                        f"terminate 子进程（attempt {run_id}）",
                    )
                    proc.terminate()
                    try:
                        proc.wait(timeout=AGENT_TERMINATE_GRACE_SECONDS)
                    except subprocess.TimeoutExpired:
                        self.logger.warning(
                            "agent_runner",
                            f"run '{base_run_id}' grace 窗口内未退出，SIGKILL",
                        )
                        proc.kill()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                    returncode = -15  # SIGTERM 对应语义
                    cancel_error = RunCancelledError(reason=reason, by=by)
                    break

                remaining = deadline - time.time()
                # ── extension 末位窗口自动保全（add-fast-track-scale-precheck D3）──
                # 剩余时间进入末位窗口（< EXTENSION_TAIL_WINDOW_SECONDS 且 >0）
                # 且该 run 尚未触发过保全时，先执行一次 WIP checkpoint
                #（fenix(wip): checkpoint extension-tail <spec>），保全已完成
                # 轮次工作；随后继续轮询——超时到点仍走既有 _supervision
                # deadline_action 收口。幂等：extension_tail_triggered 标记保证
                # 每 run 至多一次。fast-track 专有行为（非 fast-track 零影响）。
                if (not extension_tail_triggered
                        and agent_type == "fast-track"
                        and 0 < remaining < EXTENSION_TAIL_WINDOW_SECONDS):
                    extension_tail_triggered = True
                    self._wip_checkpoint_on_extension_tail(spec_name, cwd)
                if remaining <= 0:
                    # 超时活性监督（improve-run-lifecycle-governance D3）：到点不
                    # 立即杀——按封闭决策矩阵判定（硬上限 → 次数上限 → 活性）。
                    action = self._supervision_deadline_action(
                        run_file, spec_name, run_id, started_at, extensions_used,
                        agent_type=agent_type)
                    if action["action"] == "extend":
                        extensions_used = int(action["extension_index"])
                        deadline += float(action["extension_seconds"])
                        append_run_line(run_file, {
                            "type": "timeout_extension",
                            "extension": extensions_used,
                            "extension_seconds": action["extension_seconds"],
                            "evidence": str(action.get("evidence") or "")[:400],
                            "new_deadline": deadline,
                        })
                        if spec_name:
                            self.note_run_extension(
                                spec_name, run_id, extensions_used, deadline)
                        continue
                    timeout_error = (
                        f"Timeout after {int(time.time() - started_at)}s — "
                        f"{action['reason']}"
                    )
                    if action.get("evidence"):
                        timeout_error += f" | evidence: {action['evidence']}"
                    proc.kill()
                    break
                if max_turns and turn_count[0] >= current_turn_cap:
                    # 轮次上限活性监督（add-turn-limit-anchor-c D2/D3）：触达当前
                    # 上限不立即杀——按封闭决策矩阵（封顶 → 分支提交活性 →
                    # tool_result 流量活性）判定续期或终止，与超时路径同构。
                    action = self._turn_limit_action(
                        run_file, spec_name, run_id, turn_extensions_used,
                        cwd, agent_type=agent_type, max_turns=max_turns)
                    if action["action"] == "extend":
                        turn_extensions_used = int(action["extension_index"])
                        current_turn_cap = int(action["new_turn_cap"])
                        append_run_line(run_file, {
                            "type": "turn_extension",
                            "extension": turn_extensions_used,
                            "turn_step": int(action.get("turn_step") or 0),
                            "evidence": str(action.get("evidence") or "")[:400],
                            "new_turn_cap": current_turn_cap,
                        })
                        self.logger.info(
                            "agent_runner",
                            f"Turn limit extended for '{spec_name}' "
                            f"({turn_extensions_used}/{TURN_EXTENSION_MAX}): "
                            f"step={int(action.get('turn_step') or 0)}, "
                            f"new_cap={current_turn_cap}, "
                            f"evidence={action.get('evidence')}",
                            {"run_id": run_id},
                        )
                        continue
                    turn_limit_error = (
                        f"Max turns ({current_turn_cap}) reached — "
                        f"{action['evidence']}"
                    )
                    proc.kill()
                    break
                rc = proc.poll()
                if rc is not None:
                    returncode = rc
                    break
                time.sleep(1)
            if timeout_error or turn_limit_error:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                returncode = -9
        except Exception as e:
            # add-runtime-run-sweeper D4（源头修复）：轮询环未预期异常即刻落显式
            # error 终态（含 repr 归因），不再依赖运行期清扫器 30 分钟后兜底——
            # 线程级死亡与进程级死亡（清扫器负责）分层收口。except 先于 finally
            # 执行，崩溃场景 last_result/cancel_error 均为空，error 行即文件末行
            # （finally 内无 result/cancelled 可写）。原样 re-raise 保持 attempt
            # 循环既有失败处理（预算计数/STATE 转换/异常通道）语义不变。
            append_run_error(run_file, f"run thread crashed: {e!r}", returncode)
            raise
        finally:
            # 等待读线程把残留行刷完，再决定终态，保证 error 终态行是文件最后一行
            t_out.join(timeout=5)
            t_err.join(timeout=5)
            self._running_agents.pop(run_id, None)
            # add-planner-efficiency（run-latency-observability）：run 末延迟摘要
            # 日志——统一覆盖成功/失败/取消全部退出路径（component=agent_runner，
            # 含 run_id）。纯读侧统计，不改变事件处理时序。
            try:
                stats = latency_stats(latency_state["samples"])
                latency_summary_text = format_latency_summary(run_id, stats)
                self.logger.info(
                    "agent_runner",
                    latency_summary_text,
                    {"run_id": run_id, "latency_rounds": stats["rounds"],
                     "latency_stalls": stats["stalls"],
                     "latency_p90": stats.get("p90"),
                     "latency_max": stats.get("max")},
                )
                # 延迟观测自检（fix-run-latency-toolresult-parser design D4）：
                # latency_rounds==0 但 turn_count>0 = 解析器失明的确定信号
                # （有 assistant 轮次却配对不出任何样本），显式 WARNING 使盲区
                # 不再静默。仅日志，不写 admin_alerts（延迟数据不触发独立人工
                # 告警铁律）；rounds==0 且 turn_count==0（真空跑）不告警。
                if stats["rounds"] == 0 and turn_count[0] > 0:
                    self.logger.warning(
                        "agent_runner",
                        f"run {run_id}: 延迟观测疑似失明（latency_rounds=0 但 "
                        f"assistant 轮次={turn_count[0]}）——有模型轮次却配对不出 "
                        f"任何 API 往返样本，请检查 tool_result 事件识别",
                        {"run_id": run_id, "latency_rounds": 0,
                         "turn_count": turn_count[0]},
                    )
            except Exception as e:
                self.logger.debug(
                    "agent_runner",
                    f"延迟摘要计算失败（不阻断 run 终态）: {e}",
                )
            # result 终态事件最后落盘（读线程里跳过内联写），保证是文件最后一行
            if last_result:
                append_run_line(run_file, dict(last_result))
            # add-run-cancel D2：cancelled 终态行在 join 之后落盘（result 行后），
            # 保证 cancelled 行是文件最后一行（终态后置既有次序）。
            if cancel_error is not None:
                append_run_line(run_file, {
                    "type": "cancelled",
                    "reason": cancel_error.reason,
                    "by": cancel_error.by,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                # 取消已在轮询环内消费：run 收尾清理旗标防泄漏（幂等；
                # _execute_agent 层的 _cancel_clear 亦会兜底）。
                self._cancel_clear(base_run_id)
            # 产物文件可能因崩溃等遗留为"活动但不再增长"，清理时按时间淘汰即可

        if cancel_error is not None:
            raise cancel_error

        if timeout_error is not None:
            # 锚点 C（add-turn-limit-anchor-c D1）：超时强杀收口前的 WIP 保全。
            # 此刻子进程已 kill、读线程已 join（finally 语义保证 worktree 静默可
            # 证明），先保全未提交现场再 append_run_error——失败降级不阻断收口。
            self._wip_checkpoint_on_forced_kill(spec_name, cwd)
            append_run_error(run_file, timeout_error, returncode)
            raise RuntimeError(
                f"claude CLI {timeout_error}"
                + (f" | latency: {latency_summary_text}" if latency_summary_text else ""))

        if turn_limit_error is not None:
            # 锚点 C（add-turn-limit-anchor-c D1）：turn-limit 强杀收口前的 WIP
            # 保全——零提交型 run（builtin a1 84min 未提交工作滞留 worktree）的
            # 现场保全点，后续 attempt resume 或降级重建从该提交恢复。
            self._wip_checkpoint_on_forced_kill(spec_name, cwd)
            append_run_error(run_file, turn_limit_error, returncode)
            raise RuntimeError(
                f"claude CLI {turn_limit_error}"
                + (f" | latency: {latency_summary_text}" if latency_summary_text else ""))

        output = last_result.get("result", "") if last_result else ""
        turns = last_result.get("num_turns", 0)
        session_id = last_result.get("session_id") if last_result else None

        if returncode != 0:
            # error-attribution-denoise（D5）：拼装 error 前过滤 CLI stderr 诊断
            # 噪音行（v2.1.233+ 每请求写入 `[claude-code:...]`、与死因无关），避免
            # 死因被系统性误标。过滤后无剩余内容 → 回退 `Exit code: {returncode}`。
            # run 产物 jsonl 的 stderr 原始事件保持不过滤（取证现场完整）。
            effective_lines, error_msg = self._denoise_stderr(stderr_lines, returncode)
            append_run_error(run_file, error_msg, returncode)
            exc = RuntimeError(
                f"claude CLI failed: {error_msg}"
                + (f" | latency: {latency_summary_text}" if latency_summary_text else ""))
            # fix-provider-transient-backoff（D2）：异常携带**原始** stderr 信号与
            # result 事件存在性，供 attempt 循环瞬断判定——判定不得读降噪后的
            # error 文本反推（unrecognized_model 已被过滤），必须用原始信号。
            # 超时/强杀路径（timeout_error/turn_limit_error）不携带（空列表），
            # 保证超时卡死不被误判为瞬断。
            exc.stderr_lines = list(stderr_lines)
            exc.has_result = bool(last_result)
            exc.exit_code = returncode
            raise exc

        # D5: 终态语义校验前置 —— rc==0 但 last_result 标记为 error 时仍判失败
        # （Claude CLI 可能把 API 错误包装成 result/success 终止事件且 exit 0）
        if last_result:
            result_is_error = last_result.get("is_error", False)
            result_subtype = last_result.get("subtype", "success")
            if result_is_error or result_subtype in ("error", "error_during_execution"):
                err_text = last_result.get("result", "") or f"is_error={result_is_error}, subtype={result_subtype}"
                append_run_error(run_file, f"API error disguised as success: {err_text}", returncode)
                raise RuntimeError(
                    f"claude CLI rc==0 but result indicates error: {err_text}"
                    + (f" | latency: {latency_summary_text}" if latency_summary_text else ""))

        # add-cost-observability（D1）：从 stream-json 终态 result 事件提取 usage 与
        # 成本字段；失败/异常路径上 _run_claude 已抛错，此处仅成功终态能拿到 usage。
        return output, turns, session_id, self._extract_usage_info(last_result)


    @staticmethod
    def _denoise_stderr(stderr_lines: list, returncode: int) -> tuple:
        """error 拼装前过滤 CLI stderr 诊断噪音行（error-attribution-denoise D5）。

        v2.1.233+ 每请求向 stderr 写入 `[claude-code:...]` 诊断行，与死因无关；
        按 `^[claude-code:` 前缀过滤后再取末 5 行拼接。过滤后无剩余内容 →
        回退 `Exit code: {returncode}` 形态。jsonl 中 stderr 原始事件行保持
        不过滤（取证现场完整，降噪只影响 error 文本）。

        Returns: (effective_lines, error_msg)——effective_lines 为过滤后的有效行，
        供需要原始信号的调用方复用（避免重复过滤）。
        """
        effective_lines = [
            l for l in stderr_lines if not re.match(r"^\[claude-code:", l)
        ]
        error_msg = ("\n".join(effective_lines[-5:])[:500] if effective_lines
                     else f"Exit code: {returncode}")
        return effective_lines, error_msg

    @staticmethod
    def _parse_transient_backoff_schedule(raw: str) -> list:
        """解析原地退避序列为正整数列表（fix-provider-transient-backoff D1）。

        配置键 `agents.transient_backoff_schedule`，逗号分隔的秒序列，
        如 "30,60,120" → [30, 60, 120]。非法元素静默跳过，全非法回退
        缺省 [30,60,120]。序列长度即原地重试预算上限。
        """
        DEFAULT_SCHEDULE = [30, 60, 120]
        if not raw or not isinstance(raw, str):
            return DEFAULT_SCHEDULE
        result = []
        for part in raw.split(","):
            part = part.strip()
            try:
                val = int(part)
                if val > 0:
                    result.append(val)
            except (ValueError, TypeError):
                continue
        return result if result else DEFAULT_SCHEDULE


    # ── attempt 存活探测（improve-run-lifecycle-governance D4）────────────────


    # ── 超时续期基准（improve-run-lifecycle-governance 3.2 / D3）──────────────


    # ── 超时活性监督（improve-run-lifecycle-governance 4.1–4.3 / D1–D3）────────


    @staticmethod
    def _parse_event_timestamp(entry: dict) -> float | None:
        """解析 run 事件的 timestamp（ISO 字符串或 epoch 数值）；缺失返回 None。"""
        raw = entry.get("timestamp")
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return None


    def _check_daily_limit(self):
        """Check and reset daily run counter."""
        today = datetime.now(timezone.utc).date()
        if today != self._daily_reset_date:
            self._daily_run_count = 0
            # D5：直接写组合对象（转发 setter 已删；AgentRunner 不另行持有第二份）。
            self._provider_circuit._daily_reset_date = today

        limit = self._get_config("agents.daily_run_limit", 50)
        if limit > 0 and self._daily_run_count >= limit:
            raise RuntimeError(f"Daily agent run limit ({limit}) reached")

    def _get_agent_model_assignment(self, agent_type: str):
        """Return (provider_dict, model_name) for agent_type, or None if unassigned.

        Wraps ConfigLoader.get_agent_model_assignment. 每次调用都从 config 重新解析，
        避免缓存状态不一致；同时保证每线程拿到独立的 env 覆盖字典。
        """
        from core.config import ConfigLoader
        return ConfigLoader.get_agent_model_assignment(self.config, agent_type)

    def _get_config(self, key: str, default=None):
        """Get a nested config value."""
        from core.config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)

    def _effective_run_timeout(self, agent_type: str | None = None) -> float:
        """agent run 生效超时（per-agent-timeout-override 3.2）。

        ``agents.timeout_overrides.<agent_type>`` 存在且合法时取覆盖值，否则回退
        ``agents.run_timeout_seconds`` 全局默认；全局缺失回退 3600。
        """
        from core.config import ConfigLoader
        return ConfigLoader.effective_run_timeout_seconds(self.config, agent_type)

    def _spec_is_frozen(self, spec_name: str) -> bool:
        """spec 是否处于人工冻结态（结构化 frozen 字段，lifecycle-hygiene 4.1）。

        state_machine 缺失/读取异常时 fail-open（返回 False）——判定故障不放大为
        run 故障，未冻结行为零变化。
        """
        try:
            if self.state_machine is None:
                return False
            entry = self.state_machine.read_one(spec_name) or {}
            return bool(entry.get("frozen"))
        except Exception:
            return False

    def _should_give_up_before_retry(self, spec_name: str, agent_type: str,
                                     check_lock: bool = True) -> bool:
        """attempt 重试前的放弃判定（fix-restart-dual-dispatch S3/S4）。

        2026-09-03 事故：双派发场景下 create 撞同名分支 fatal，attempt 循环
        sleep(5) 后换新时间戳重试成功 → 与第一梯队形成并行 run。重试前检查：
        - 锁活跃：另一个 run 已持 spec 锁，继续重试只会造出第二个并行 run
          （仅 attempt 层 create 前的既有调用点启用；check_lock=False 时跳过）；
        - 人工冻结：spec 被人为冻结（结构化 frozen 字段），自动重试必须让位；
        - **重派前状态复查（fix-verdict-dedup-resynthesis D4）**：spec 当前
          status 已迁出该 agent 的预期态（judge=testing、implementer=
          implementing，见 EXPECTED_SPEC_STATUS_BY_AGENT），或 _cancelled_hold
          取消保持态 → 人工已接管，放弃重试让位（退避结束后重派前的复查）。

        check_lock=False 供原地重试子循环的退避后复查使用——锁语义专属于
        attempt 层 create 前的双派发守卫，退避重派只判「人工接管」态。

        检查自身异常时 fail-open（返回 False）——判定故障不放大为 run 故障，
        既有重试语义保持可用。
        """
        try:
            if check_lock and self.worktree_manager is not None \
                    and self.worktree_manager.has_active_lock(spec_name, agent_type):
                self.logger.warning(
                    "agent_runner",
                    f"Giving up retry for '{spec_name}' ({agent_type}): "
                    f"spec lock held by another live run — retrying would "
                    f"create a parallel run (dual-dispatch guard)",
                )
                return True
            entry = self.state_machine.read_one(spec_name) or {}
            if entry.get("frozen"):
                self.logger.warning(
                    "agent_runner",
                    f"Giving up retry for '{spec_name}': manually frozen "
                    f"(frozen field set) — auto-retry yields to human decision",
                )
                return True
            # 取消保持态（fix-cancel-holdstate-recovery）：run 被人工取消后的
            # 有意等待态，自动重派不得复活它。
            if entry.get("_cancelled_hold"):
                self.logger.warning(
                    "agent_runner",
                    f"Giving up retry for '{spec_name}' ({agent_type}): "
                    f"spec in cancelled-hold state — auto-retry must not "
                    f"resurrect a deliberately held spec",
                )
                return True
            # 预期态判定（fix-verdict-dedup-resynthesis D4）：status 迁出预期态
            # = 人工/其它链路已接管，重派会与接管竞跑（admin SIGKILL 后 30s 内
            # 改 blocked → 退避结束照派一轮白烧 token）。
            expected = EXPECTED_SPEC_STATUS_BY_AGENT.get(agent_type)
            if expected:
                status = entry.get("status") or ""
                if status and status != expected:
                    self.logger.warning(
                        "agent_runner",
                        f"Giving up retry for '{spec_name}' ({agent_type}): "
                        f"spec status '{status}' no longer expected "
                        f"'{expected}' — retry would race human takeover "
                        f"(retry-yields guard)",
                    )
                    return True
        except Exception:
            return False
        return False

    # ── 秒挂退避熔断（cli-retry-backoff）─────────────────────────────
    # 同一 spec 的连接 CLI run 在「进程存活时长」低于阈值即死亡（如 Exit 143 秒挂）
    # 连续达阈值 → 该 spec 进入冷却，期间 implementer/fast-track/repair 派发被
    # 跳过（不耗预算、不起进程）；冷却到期自动恢复且计数清零。

    def _instant_fail_threshold(self) -> int:
        """秒挂判定阈值（agents.instant_fail_threshold_seconds，缺省 60）。"""
        try:
            v = int(self._get_config("agents.instant_fail_threshold_seconds", 60) or 60)
        except (TypeError, ValueError):
            v = 60
        return max(1, v)

    def _instant_fail_cooldown_after(self) -> int:
        """连续秒挂触发冷却的次数（agents.instant_fail_cooldown_after，缺省 3）。"""
        try:
            v = int(self._get_config("agents.instant_fail_cooldown_after", 3) or 3)
        except (TypeError, ValueError):
            v = 3
        return max(1, v)

    def _instant_fail_cooldown_seconds(self) -> int:
        """冷却时长（agents.instant_fail_cooldown_seconds，缺省 300）。"""
        try:
            v = int(self._get_config("agents.instant_fail_cooldown_seconds", 300) or 300)
        except (TypeError, ValueError):
            v = 300
        return max(1, v)

    @staticmethod
    def _run_was_interrupted(run_file) -> bool:
        """run 产物是否含 interrupted 标记（框架主动 SIGTERM，liveness/shutdown
        路径写入）。秒挂退避不计入被框架主动终止的 run（design D2）。"""
        if run_file is None:
            return False
        try:
            with Path(run_file).open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("type") == "interrupted":
                        return True
        except OSError:
            return False
        return False

    # ── 信号死法来源判定（evo-sigterm-source-tracking-cooldown）──────────
    # 闭集按序短路（先排除框架自身终止，否则框架自己强杀的 run 会被误标外部
    # 信号）：cancel 旗标（RunCancelledError 独立异常通道）→ supervision 超时/
    # 轮次上限强杀（returncode=-9 且错误文本 Timeout after/Max turns）→ daemon
    # 关停（shutting_down/产物 interrupted，既有 [shutdown-interrupted] 守卫先行
    # 短路）→ 其余 143/负信号 → [signal-kill: …] 标签 + 信号冷却计数。
    # 来源归属 MUST 只由可实测的三源闭集推导；无判别力时标 unknown 并如实带
    # returncode，MUST NOT 以猜测声称 external-kill。

    @staticmethod
    def _signal_kill_label(exit_code) -> Optional[str]:
        """returncode → 信号死法标签；非信号死法返回 None。

        143 = 128 + SIGTERM（CLI 自身把 SIGTERM 转写为退出码 143，见既有
        Exit 143 秒挂实测注释）；负信号为 -<信号号>（-9=SIGKILL / -15=SIGTERM）。
        无法映射的信号号标 unknown 并如实带 returncode（不得猜测信号发出者）。
        """
        if exit_code == 143:
            return "[signal-kill: SIGTERM/143]"
        if exit_code == 130:
            return "[signal-kill: SIGINT/130]"
        if isinstance(exit_code, int) and exit_code < 0:
            name = {1: "SIGHUP", 2: "SIGINT", 9: "SIGKILL",
                    15: "SIGTERM"}.get(-exit_code)
            if name:
                return f"[signal-kill: {name}/{exit_code}]"
            return f"[signal-kill: unknown/{exit_code}]"
        return None

    def _record_signal_kill_or_label(self, spec_name: str, error: str,
                                     exit_code) -> str:
        """信号死法来源判定（闭集）+ spec 维度信号冷却计数。

        调用点 MUST 在 shutdown-interrupted 守卫之后（shutting_down/产物
        interrupted 已先行短路为 [shutdown-interrupted]）；cancel 旗标走
        RunCancelledError 独立异常通道，不达本方法。框架自身终止（supervision
        超时/轮次上限强杀：错误文本 Timeout after/Max turns）MUST NOT 打信号
        标签、MUST NOT 计信号计数——框架自己强杀不得冷却链路。

        Returns: 可能被注入 ``[signal-kill: …]`` 前缀的 error。
        """
        if not spec_name or not error:
            return error
        # 框架自身终止排除（supervision 超时/轮次上限强杀，错误文本为
        # `Timeout after …` / `Max turns …`，runner.py:2833/2874 收口）。
        # 真实超时/强杀路径异常不带 exit_code（timeout/turn_limit raise 无属性），
        # 错误文本排除对有无 exit_code 一视同仁——统一先行短路。
        if "Timeout after" in error or "Max turns" in error:
            return error
        if exit_code is None:
            # 无 exit_code 且非框架自身终止文本 → 判别力不足，不归类不计数。
            return error
        label = self._signal_kill_label(exit_code)
        if label is None:
            # 非信号死法（普通非零退出）：连续信号死法链被打断，重置计数。
            self._provider_circuit.reset_signal_kill(spec_name)
            return error
        if "[signal-kill:" not in error:
            error = f"{label} {error}"
        # 计入信号冷却通道（spec 维度；与秒挂冷却并存，同事件双记仅累加）。
        try:
            self._provider_circuit.record_signal_kill(spec_name)
        except Exception as _sig_err:
            self.logger.debug(
                "agent_runner",
                f"signal-kill 计数记账失败（不阻断）: {_sig_err}",
            )
        self.logger.warning(
            "agent_runner",
            f"'{spec_name}' 子进程信号死法 exit_code={exit_code} — {label} "
            f"（source=unknown：非框架终止/非 daemon 关停，信号发出者不可考）",
        )
        return error

    def _record_instant_fail(self, spec_name: str, duration_seconds: float,
                             run_file=None) -> None:
        """attempt 失败时按进程存活时长判定秒挂并累计 spec 维度连续计数。

        - 框架主动 SIGTERM 的 run（产物含 interrupted 标记）不计入；
        - 存活 ≥ 阈值（或无法判定时长异常）的失败视为非秒挂 → 重置计数；
        - 秒挂连续达 cooldown_after → 进入冷却并触发首次 major 告警
          （同 spec 同信号 15 分钟内 throttle 去重）。
        """
        if not spec_name:
            return
        if self._run_was_interrupted(run_file):
            self.logger.debug(
                "agent_runner",
                f"'{spec_name}' run 被框架终止，不计入秒挂退避计数",
            )
            return
        threshold = self._instant_fail_threshold()
        if duration_seconds >= threshold:
            # 存活超阈值失败 = 正常失败，不是秒挂：重置连续计数（design D2）
            self._reset_instant_fail(spec_name)
            return

        st = self._instant_fail.setdefault(
            spec_name, {"count": 0, "cooldown_until": 0.0})
        st["count"] = st.get("count", 0) + 1
        cooldown_after = self._instant_fail_cooldown_after()
        if st["count"] < cooldown_after:
            self.logger.warning(
                "agent_runner",
                f"'{spec_name}' 秒挂 {st['count']}/{cooldown_after} "
                f"（存活 {duration_seconds:.0f}s < {threshold}s 阈值）",
            )
            return

        # 达阈值：进入冷却
        cooldown_seconds = self._instant_fail_cooldown_seconds()
        now = self._now() if hasattr(self, "_now") else time.monotonic()
        st["cooldown_until"] = now + cooldown_seconds
        self.logger.error(
            "agent_runner",
            f"'{spec_name}' 连续 {st['count']} 次秒挂（阈值 {cooldown_after}）— "
            f"进入 {cooldown_seconds}s 冷却，期间 implementer/fast-track/repair "
            f"派发被跳过；到期自动恢复",
        )
        self._alert_instant_fail_storm(spec_name, st["count"], cooldown_seconds)

    def _alert_instant_fail_storm(self, spec_name: str, count: int,
                                  cooldown_seconds: int) -> None:
        """首次冷却触发发 major 告警（signal_type=instant_fail_storm）。

        重复冷却由既有 15 分钟 throttle 抑制：AdminStore.latest_signal 按
        (spec, signal_type) 在窗口内查重，窗口内已有同信号则不发第二条。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION
            store = AdminStore(self.project_root, self.logger)
            if store.latest_signal(spec_name, "instant_fail_storm", 15) is not None:
                self.logger.debug(
                    "agent_runner",
                    f"instant_fail_storm 告警已 throttle（15 分钟内已有）: '{spec_name}'",
                )
                return
            store.append({
                "kind": ESCALATION,
                "signal_type": "instant_fail_storm",
                "spec": spec_name,
                "severity": "major",
                "description": (
                    f"spec '{spec_name}' 连续 {count} 次秒挂（进程存活低于阈值即死亡）"
                    f"— 已进入 {cooldown_seconds}s 冷却，期间 implementer/fast-track/"
                    f"repair 派发被跳过；冷却到期自动恢复"
                ),
                "evidence": (
                    f"spec={spec_name}; instant_fail_count={count}; "
                    f"cooldown_seconds={cooldown_seconds}"
                ),
                "recommended_action": (
                    "检查 CLI/网关瞬时死亡根因（模型不兼容、token/额度不足、会话丢失等）；"
                    "冷却自动到期后恢复，无需人工干预"
                ),
            })
        except Exception as e:
            self.logger.error(
                "agent_runner",
                f"instant_fail_storm 告警写入失败 '{spec_name}': {e}",
            )

    def _reset_instant_fail(self, spec_name: str) -> None:
        """成功 / 存活超阈值失败：清除该 spec 的秒挂连续计数与冷却态。"""
        self._instant_fail.pop(spec_name, None)

    def _instant_fail_counts(self, spec_name: str) -> int:
        """当前连续秒挂次数（测试/观测辅助）。"""
        st = self._instant_fail.get(spec_name)
        return int(st.get("count", 0)) if st else 0

    def is_instant_fail_cooldown(self, spec_name: str, now: float | None = None) -> bool:
        """判断 spec 是否处于秒挂冷却期（dispatch 派发前闸门调用）。

        冷却到期自动恢复并清零计数（design D2：到期后从 0 重新累计）；
        无条目 / 未进入冷却返回 False（行为与现状一致）。
        """
        if not spec_name:
            return False
        st = self._instant_fail.get(spec_name)
        if not st:
            return False
        until = st.get("cooldown_until") or 0.0
        if until <= 0:
            return False
        now = self._now() if now is None else now
        if now >= until:
            self._reset_instant_fail(spec_name)
            return False
        return True

    def _read_verify_progress(self, spec_name: str) -> dict | None:
        """读取 verifier 断点进度文件（verifier-checkpoint-resume spec）。

        返回解析后的 dict（含 total/done/current），用于构造续跑提示词；以下情况
        返回 None（视作无断点、全新开始）：
        - 文件不存在
        - 内容不是合法 JSON
        - 缺少 done / total 字段，或 done 非整数
        文件损坏时移除该文件，避免污染后续 attempt（设计 D1 / 安全降级）。
        """
        progress_path = self.project_root / ".fenix" / "verify-progress" / f"{spec_name}.json"
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 损坏文件：移除以免后续 attempt 读到半截内容
            try:
                if progress_path.exists():
                    progress_path.unlink()
            except OSError:
                pass
            return None
        if not isinstance(data, dict):
            try:
                if progress_path.exists():
                    progress_path.unlink()
            except OSError:
                pass
            return None
        done = data.get("done")
        total = data.get("total")
        if not isinstance(total, int) or not isinstance(done, int):
            return None
        return data
    @property
    def _prompt_builder(self) -> PromptBuilder:
        """组合组件（refactor-core-packages 阶段 1）：提示词构建器。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_prompt_builder_instance")
        if inst is None:
            inst = PromptBuilder(self)
            self.__dict__["_prompt_builder_instance"] = inst
        return inst


    # ── 组合组件委托（refactor-core-packages 阶段 1：PromptBuilder）──────
    # 测试引用方法（runner._build_prompt 等）保持调用路径可用（design D3 规则 4）。

    # 结果文件顶层 status 白名单（P0 / spec「结果产物硬门」）：success=全部任务完成；
    # partial=诚实申报未完成；error=失败不施加完成度判据。白名单外取值判失败（防
    # fail-open 事故形态）；判据实现在 result_gate.py（D2b 规则 1 经 runner 注入）。
    _IMPL_RESULT_STATUSES = ("success", "error", "partial")

    def _append_crosscheck_skipped(self, spec_name: str, run_file,
                                   reason: str) -> None:
        _append_crosscheck_skipped(self, spec_name, run_file, reason)

    # ── 组合组件（refactor-core-packages 阶段 2）────────────────────────

    @property
    def _provider_circuit(self) -> ProviderCircuit:
        """组合组件（refactor-core-packages 阶段 2）：ProviderCircuit。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_provider_circuit_instance")
        if inst is None:
            inst = ProviderCircuit(self)
            self.__dict__["_provider_circuit_instance"] = inst
        return inst

    @property
    def _token_accountant(self) -> TokenAccountant:
        """组合组件（refactor-core-packages 阶段 2）：TokenAccountant。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_token_accountant_instance")
        if inst is None:
            inst = TokenAccountant(self)
            self.__dict__["_token_accountant_instance"] = inst
        return inst

    @property
    def _v2_server(self) -> V2ServerManager:
        """组合组件（refactor-core-packages 阶段 2）：V2ServerManager。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_v2_server_instance")
        if inst is None:
            inst = V2ServerManager(self)
            self.__dict__["_v2_server_instance"] = inst
        return inst


    # ── 组合组件委托（阶段 2：状态/方法已迁组件，门面保持调用路径）──────

    # ── 全局瞬断熔断转导（fix-provider-transient-backoff D4）──────────────────

    # ── 信号死法冷却转导（evo-sigterm-source-tracking-cooldown）────────────

    def _reset_signal_kill(self, spec_name: str) -> None:
        """成功：清除该 spec 的信号死法连续计数与冷却态（连续链被打断）。"""
        self._provider_circuit.reset_signal_kill(spec_name)

    def _v2_harvest_used_worktrees(self, used_wts: set, handed_off: set) -> None:
        """终态收割（verify-process-lifecycle D1/D2）：对未交接 worktree 回收。

        对 ``used_wts - handed_off`` 的每个 worktree：停止其 dev-server 注册
        条目（幂等——条目已不存在/进程已死时安全空转）并扫杀 worktree 游离
        进程（claude 豁免，不误伤在跑 attempt）。一处 closing 覆盖 frozen 早退、
        chain_exhausted、熔断拦截、日限 raise、取消、任意异常的漏网终态；
        与 dispatch 层 worker 兜底双调无害。
        """
        targets = sorted(set(used_wts) - set(handed_off))
        for wt in targets:
            if not wt:
                continue
            try:
                self._v2_stop_for_worktree(Path(wt))
            except Exception as e:
                self.logger.warning(
                    "agent_runner", f"终态收割 V2 stop 失败 {wt}: {e}")
            try:
                self.worktree_manager._kill_worktree_strays(Path(wt).name)
            except Exception as e:
                self.logger.warning(
                    "agent_runner", f"终态收割 strays 清扫失败 {wt}: {e}")

    @property
    def provider_circuits(self):
        return self._provider_circuit.provider_circuits

    @property
    def _daily_provider_attempts(self):
        return self._provider_circuit._daily_provider_attempts

    @property
    def _daily_provider_warned(self):
        return self._provider_circuit._daily_provider_warned

    @property
    def _daily_reset_date(self):
        return self._provider_circuit._daily_reset_date

    @property
    def _v2_servers(self):
        return self._v2_server._v2_servers

    @property
    def _v2_used_ports(self):
        return self._v2_server._v2_used_ports

    @property
    def _v2_run_seq(self):
        return self._v2_server._v2_run_seq

    # ── 组合组件（refactor-core-packages 阶段 3）────────────────────────

    @property
    def _liveness(self) -> LivenessSupervisor:
        """组合组件（refactor-core-packages 阶段 3）：LivenessSupervisor。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_liveness_instance")
        if inst is None:
            inst = LivenessSupervisor(self)
            self.__dict__["_liveness_instance"] = inst
        return inst

    @property
    def _session(self) -> SessionTracker:
        """组合组件（refactor-core-packages 阶段 3）：SessionTracker。

        惰性构造：测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例也安全。
        """
        inst = self.__dict__.get("_session_instance")
        if inst is None:
            inst = SessionTracker(self)
            self.__dict__["_session_instance"] = inst
        return inst


    # ── 组合组件委托（阶段 3：存活/监督/session 已迁组件）────────────────

    def running_run_ids(self) -> list:
        """当前在册在跑 run 的 run_id 列表（存活判定：进程仍在或快照内未收割）。

        供 shutdown 排水模式枚举等待对象；以进程表为真相（poll() 为 None = 存活），
        完成终态后自然移出。
        """
        return [
            rid for rid, proc in list(self._running_agents.items())
            if proc.poll() is None
        ]

    def drain_wait(self, timeout: float) -> list:
        """规划性重启排水：等在跑 run 自然终态，不再对其发 terminate。

        interrupt-recovery-preserve D1/D4：daemon 收到 SIGTERM 且 restart_request
        在册时进入排水模式——禁新派发已由 shutting_down 保证，此处只等在册 run
        收工（run 自身 timeout 兜底），到期仍残留的 run_id 列表原样返回，由
        shutdown 流程据侧车保全后走现行 terminate 收口。

        Args:
            timeout: 排水窗口秒数（admin.shutdown_drain_seconds，缺省 1800）。

        Returns: 窗口到期仍未终态的在跑 run_id 列表（空 = 全部自然收工）。
        """
        waited = 0.0
        deadline = time.time() + max(0.0, timeout)
        remaining = self.running_run_ids()
        if not remaining:
            return []
        while time.time() < deadline:
            remaining = self.running_run_ids()
            if not remaining:
                return []
            time.sleep(0.5)
        return self.running_run_ids()

    # ── run 终止指标落盘（fix-observability-gaps 1.x） ─────────────────────────
    # 每次 run 进入终态时写一条结构化指标（复用既有日志设施，不新建 metrics
    # 目录/消费者；design D1）。字段与 spec「run 终止指标结构化落盘」对齐：
    # run_id / spec / agent_type / duration_seconds / turns / usage 四分项 /
    # cost_usd / terminal / provider。usage/cost 直接取自 _extract_usage_info
    # 的既有产出（add-cost-observability D1），不重复计算（任务 1.2）；
    # cost_usd 只做事件留痕，页面成本口径维持 dashboard 既有计价表
    # （任务 1.6，不叠加、不双源）。

    def _log_run_metrics(
        self,
        *,
        run_id: str,
        spec_name: str,
        agent_type: str,
        duration_seconds: float,
        turns: int,
        usage_info: dict,
        terminal: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """写一条 run 收尾结构化指标（成功/失败/取消/中断等终态各一条）。

        复用 ``self.logger.info(component, message, context)`` 落盘（JSON 行，
        context 为结构化字段）；落盘失败仅记 warning，绝不阻断 run 收尾。
        """
        usage = usage_info or {}
        try:
            self.logger.info(
                "agent_runner",
                f"run metrics: {agent_type} {terminal} '{spec_name}'",
                {
                    "metric_type": "run_metrics",
                    "run_id": run_id,
                    "spec": spec_name,
                    "agent_type": agent_type,
                    "duration_seconds": round(float(duration_seconds or 0), 3),
                    "turns": int(turns or 0),
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                    "cache_creation_input_tokens": int(
                        usage.get("cache_creation_input_tokens") or 0),
                    "cache_read_input_tokens": int(
                        usage.get("cache_read_input_tokens") or 0),
                    "cost_usd": usage.get("cost_usd"),
                    "terminal": terminal,
                    "provider": provider,
                },
            )
        except Exception as e:  # 指标落盘失败不得阻断 run 收尾
            self.logger.warning(
                "agent_runner",
                f"run metrics 落盘失败 '{spec_name}' ({run_id}): {e}",
            )

    @property
    def _extension_baselines(self):
        return self._liveness._extension_baselines

