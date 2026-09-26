"""
runner.py — AgentRunner 门面（Agent execution engine for fenixd）.

Spawns claude CLI subprocesses to run implementer and verifier Agents.
Handles result parsing, retry logic, and token/turn budget control.
"""

import json
import logging
import os
import functools
import re
import shutil
import subprocess
import tempfile
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
    FrozenTerminatedError,
    RunCancelledError,
    SelfReviewResult,
    _ARTIFACT_FRESHNESS_GRACE_SECONDS,
    _PLANREADY_STATUSES,
    _append_crosscheck_skipped,
    _check_agent_result_artifact,
    _check_artifact_json_file,
    _check_impl_code_review_artifact,
    _check_impl_result_artifact,
    _check_quality_gates_soft,
    _check_repo_code_review_artifact,
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
    _file_has_terminal_event,
)
from core.agent_runner.session import SessionTracker
from core.agent_runner.provider_circuit import (
    MODEL_CHAIN_UNAVAILABLE_MARKER,
    PROVIDER_CIRCUIT_4XX,
    PROVIDER_CIRCUIT_COOLDOWN_SECONDS,
    PROVIDER_CIRCUIT_THRESHOLD,
    PROVIDER_CIRCUIT_WINDOW_SECONDS,
    PROVIDER_DAILY_ATTEMPTS_WARN,
    PROVIDER_RATELIMIT_COOLDOWN_SECONDS,
    PROVIDER_SWITCH_COOLDOWN_SECONDS,
    RATELIMIT_REDISPATCH_MAX,
    ProviderCircuit,
    annotate_model_chain_unavailable,
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
    ANCHOR_FREEZE_HOLD,
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
    DEFAULT_OCR_BIN,
    _accumulate_code_review_tokens,
    _accumulate_evolution_tokens,
    _accumulate_self_review_tokens,
    _clear_admin_disposition,
    _clear_self_review_out,
    _delete_admin_disposition,
    _delete_evolution_out,
    _delete_self_review_out,
    _get_admin_model,
    _read_admin_disposition,
    _read_code_review_out,
    _read_self_review_out,
    _unique_code_review_run_id,
    admin_disposition_path,
    run_administrator,
    run_code_review,
    run_code_fix,
    run_evolution,
    run_impl_ocr,
    run_regression,
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

# ── run 停滞预算复合判停（evo-add-run-stop-loss 2.1，缺省关闭）────────
# 判停阈值常量（120s 级单次往返为 stall 样本；占比与无进展窗经
# agents.run_stall_budget_* 配置，见 core/config.py 单点归一化）。
RUN_STALL_ROUND_SECONDS = 120.0        # 单次往返 ≥120s 计入 stall 样本
RUN_STALL_RATIO_MIN_SAMPLES = 2        # 占比判据最小完成样本数（防单样本退化）
RUN_STALL_RATIO_TRIGGER = 0.5          # stall 占比门槛（达到一半）
# 判停终态 error 前缀（对齐 [retry-yielded] 的「前缀即语义标签」约定）；
# 终态日志与 run jsonl 据此机械识别「判停止损」而非网关故障。
RUN_STALL_BUDGET_ERROR_PREFIX = "[run-stall-budget]"


class RunStallBudgetExceededError(Exception):
    """run 触发停滞预算复合判停时抛出（evo-add-run-stop-loss 2.1）。

    与 RunCancelledError / FrozenTerminatedError 并列的独立终止通道：
    不重试、不计秒挂、不触发 provider 切换、不触发 in-place retry 重派——
    命中即终止整个重试链（否则止损被自动重派放大）。携带 criterion
    （命中判据名：consecutive_slow_rounds / stall_ratio_no_progress）。
    """

    def __init__(self, criterion: str = "", detail: str = ""):
        self.criterion = criterion
        self.detail = detail
        super().__init__(f"run stall budget exceeded ({criterion}): {detail}")

# ── add-timeline-gate-failure-display：门禁归因落 run jsonl 的截断上限 ────
# 门禁归因文案（含 [artifact-structural]/[task-gate] 标签、gate 名与目标路径）
# 落进 run jsonl 前必须先截断：append_run_line 的单行原子性只在行数据不超过
# TextIOWrapper 内部缓冲（默认约 8 KiB）时才成立，超缓冲大行会绕过缓冲分发为
# 多次 raw write，与并发 writer 交错产生半行 JSON（run_files.py:56-71 注释）。
#
# 单位 = **字符（code point）**，MUST NOT 当字节读并按字节截断：实现用字符切片
# ``error[:_GATE_ERROR_TRUNCATE]``，UTF-8 下 1024 字符最坏 ≤4 KiB，仍低于 8 KiB
# 单行缓冲阈值，字符口径即已满足「不外溢」。用例断言口径与之统一为「字符数
# ≤1024 且 UTF-8 编码后 ≤4096 字节」。
_GATE_ERROR_TRUNCATE = 1024

# ── add-impl-code-review-gate：ocr 包装器默认可执行名 ──────────────────
# add-impl-ocr-parallel-lane：消费点随 run_impl_ocr 迁 maintenance_runs.py
# （D2b 规则 3，同 DEFAULT_GATEWAY_MODEL），DEFAULT_OCR_BIN 改由上方导入块
# re-export，保持既有导入路径可用（ocr 可执行文件的默认裸名，包装器
# bin/ocr_review.py 以 os.execvp 解析 PATH）。

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

# 主树 verify-progress 目录非其工作区的车道（fix-impl-code-review-writepath D2）：
# 这三条车道的 verify-progress 产物全在 worktree 内或别处——implementer 的
# code-review.json 在 worktree（门读 wt_path、_copyback 单向 worktree→主树）、
# repair 与 implementer 同工作区、spec-review 写 .fenix/spec-review/。主树
# `<project_root>/.fenix/verify-progress` 不是它们的工作区，_run_claude 不再为
# 它们注入 `--add-dir`，只给 verifier/planner/fast-track/dispute-judge/administrator
# 等确有主树 verify-progress 落点的车道保留。
_NO_MAIN_TREE_VERIFY_PROGRESS_LANES = ("implementer", "repair", "spec-review")


def _route_map_head(wt_path: Path, logger) -> str:
    """读取 worktree 当前 HEAD（git rev-parse），失败返回空串（不阻断生成）。"""
    try:
        res = subprocess.run(
            ["git", "-C", str(wt_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
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
    # text=True 下 result.stdout 是 str，len() 为字符数；按 utf-8 编码统计
    # 真实字节数（与 write_text 落盘体积同口径），避免排障估算产物体积被误导。
    logger.info(
        "agent_runner",
        f"route-map 生成完成: {out}（{len(result.stdout.encode('utf-8'))} 字节, "
        f"HEAD={head[:12] or 'unknown'}）",
    )
    return out

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
    # run 级链指针（design D1）：仅本次 run 的 attempt 间记忆切换进度，跨 run
    # 由 _select_chain_candidate 重新选点。-1 表示尚未选定
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
    # add-freeze-stop-inflight-agents D1：本轮 run 是否因 spec 冻结被终止
    # （与 cancelled_flag 并列、互不读写——dispatch 据此写 _frozen_hold
    # 而非 _cancelled_hold）。
    frozen_terminated_flag: bool = False
    # evo-add-run-stop-loss 2.1：本轮 run 是否因停滞预算判停被终止
    # （与 frozen_terminated_flag 并列：不重试、终止整个重试链）
    stall_budget_flag: bool = False
    # shutdown-interrupted 守卫（2026-09-09 事故）
    shutdown_interrupted: bool = False
    # run 终态指标落盘需 usage_info（早夭分支引用前初始化，unobserved 语义）
    usage_info: dict = field(default_factory=dict)
    # 同上：预检早夭分支无 turns 值，统一顶部初始化
    turns: int = 0
    # 用于 "provider switched" 跨 attempt 打点
    last_provider_used: Optional[str] = None
    # add-impl-selfcheck-model-probe（2.1/2.2）：本 run 内 unrecognized_model
    # 拒模型命中计数（全链不可用归因里报告规模用）与「链尾仍被拒」旗标
    # （置位后 attempt 预算立即收场——对同一拒模型再起必败进程是纯浪费）。
    chain_reject_hits: int = 0
    chain_rejected_exhausted: bool = False


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
        # add-code-review-concurrency-and-429-resilience：限流冷却到期时刻查询
        # （ratelimit_redispatch 意图登记消费）
        "switch_cooldown_until": ("_provider_circuit", "switch_cooldown_until"),
        "_record_switch_cooldown": ("_provider_circuit", "_record_switch_cooldown"),
        # add-impl-selfcheck-model-probe（2.1）：拒模型识别告警经组件单点，
        # 门面转发保持与其它 provider 记账原语同机制。
        "_record_unrecognized_model": ("_provider_circuit", "record_unrecognized_model"),
        "_write_provider_marker": ("_provider_circuit", "_write_provider_marker"),
        "_record_daily_provider_attempt": ("_provider_circuit", "_record_daily_provider_attempt"),
        "_circuit_open_error": ("_provider_circuit", "_circuit_open_error"),
        "_record_provider_4xx": ("_provider_circuit", "_record_provider_4xx"),
        "_record_provider_probe": ("_provider_circuit", "_record_provider_probe"),
        "record_transient_break": ("_provider_circuit", "record_transient_error"),
        "is_global_transient_break_active": ("_provider_circuit", "is_global_transient_break"),
        # evo-fix-transient-break-unseal-backoff 1.2：解封节奏闸态/单条准入/
        # 错峰积压放完回调（engine 门面经同名方法消费，fail-open 口径见彼处）。
        "transient_unseal_gate": ("_provider_circuit", "transient_unseal_gate"),
        "admit_unseal_dispatch": ("_provider_circuit", "admit_unseal_dispatch"),
        "note_unseal_release_drained": ("_provider_circuit", "note_release_drained"),
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
        # evo-spec-concurrency-flight-guard D0：共享「在飞评审 run」判定
        # （引擎/队列两处派发落点经门面访问，避免第二套漂移实现）
        "reviewer_in_flight": ("_liveness", "reviewer_in_flight"),
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
        "run_code_review": run_code_review,
        # code-review 车道三 helper 同走门面（code-review item 0c9577c146d9）：
        # run_code_review 内部经 runner.<helper> 调用（实例属性打桩有效）——
        # 直接调模块函数会绕过 __getattr__，打桩被静默忽略。
        "_unique_code_review_run_id": _unique_code_review_run_id,
        "_read_code_review_out": _read_code_review_out,
        "_accumulate_code_review_tokens": _accumulate_code_review_tokens,
        # add-code-review-auto-fix（task 6.4）：code-fix 运维车道同处注册。
        # code-fix 不在 _execute_agent 路径（不占 spec 维度预算、不计入每日
        # agent run 计数），仅经本转发表被编排器调用。
        "run_code_fix": run_code_fix,
        "run_regression": run_regression,
        # add-impl-ocr-parallel-lane（任务 3.1/3.2）：ocr 审查车道同处注册——
        # 不走 _execute_agent（不占 spec 预算、不计每日 run 计数），仅经本
        # 转发表被派发接线（queue join 评估）调用。
        "run_impl_ocr": run_impl_ocr,
        "_get_admin_model": _get_admin_model,
        "_check_agent_result_artifact": _check_agent_result_artifact,
        "_check_impl_code_review_artifact": _check_impl_code_review_artifact,
        "_check_impl_result_artifact": _check_impl_result_artifact,
        # add-quality-gates-visibility：quality-gates.json 宽松对账（仅 WARNING，
        # 零拦截——登记供门面转发，与其它 _check_* 同机制）
        "_check_quality_gates_soft": _check_quality_gates_soft,
        "_check_repo_code_review_artifact": _check_repo_code_review_artifact,
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
    # add-code-review-concurrency-and-429-resilience：429 限流分类与切换类同源转发
    classify_ratelimit_error = staticmethod(ProviderCircuit.classify_ratelimit_error)
    classify_unrecognized_model_error = staticmethod(
        ProviderCircuit.classify_unrecognized_model_error)
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
        # run 收尾互斥锁（code-review item 183ded7b526a）：注册表 pop 与停机
        # interrupted 标记写入互斥（协议详见 _run_finalize_lock property 注释）。
        self._run_finalize_lock = threading.Lock()
        # 车道登记表（design D2）：__init__ 即建态——车道线程（queue
        # _start_impl_ocr_lane 每 spec 一线程）并发首次 register 时不得走
        # _lane_registry 的建态分支（两线程同见 None 会各建一个 dict、后一次
        # __dict__ 赋值静默顶掉前者 → 先登记的车道从排水集合消失，重启即被
        # 当无主回收）。单键 set/pop 原子，对齐 _running_agents 不加锁。
        self._lane_processes: Dict[str, tuple] = {}
        # per-run 终态回调表（add-mergeback-wip-active-coordination D2）：
        # base_run_id → {subscriber → callback}。挂在 _execute_agent 终态收口
        # 处触发；defer 批合回消费者据此注册持有者 run 监听实现事件驱动重试。
        # 二级 dict 按 subscriber 键覆盖（同订阅方重复注册不累积）；fire 时
        # 整键 pop 消费（单键原子，对齐 _running_agents 不加锁）。
        self._run_terminal_callbacks: Dict[str, Dict[str, object]] = {}

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

    @property
    def _stall_budget_states(self) -> dict:
        """run 停滞预算判停状态表（evo-add-run-stop-loss 2.1）。

        惰性 property（测试 ``__new__`` 绕过 ``__init__``，对齐
        _cancel_requested 模式）：键为归一化 base_run_id（含 epoch），值结构见
        _stall_budget_state_for。统计随 run 生命周期累积、不随 attempt 重置；
        终态外口经 _stall_budget_forget 摘除。
        """
        inst = self.__dict__.get("_stall_budget_states_state")
        if inst is None:
            inst = {}
            self.__dict__["_stall_budget_states_state"] = inst
        return inst

    @_stall_budget_states.setter
    def _stall_budget_states(self, value):
        self.__dict__["_stall_budget_states_state"] = value

    @property
    def _run_finalize_lock(self) -> threading.Lock:
        """run 收尾互斥锁（code-review item 183ded7b526a）：注册表 pop 与停机
        interrupted 标记写入的互斥点。liveness.wait_for_running_agents 停机写
        标记持本锁完成「注册表成员复核 + 末行终态复核 + 追加」临界区，本类
        _run_claude finally 段的注册表 pop 持本锁执行——run 线程的 result 等
        终态落盘严格后于该 pop（同线程顺序），锁排他即保证 daemon 的复核-追加
        临界区与「pop → 终态落盘」序列不交错：pop 先于临界区则复核必不通过
        （跳过标记），后于临界区则 result 落在标记之后（末行仍是 result）。
        堵住原先「两重复核通过后、追加前 run 线程完成 pop+落盘，interrupted
        成为文件末行、成功 run 被下游末行口径判成 interrupted」的第三类窗口。
        惰性 property（测试 __new__ 绕过 __init__，对齐 _cancel_requested_lock
        模式）。
        """
        inst = self.__dict__.get("_run_finalize_lock_state")
        if inst is None:
            inst = threading.Lock()
            self.__dict__["_run_finalize_lock_state"] = inst
        return inst

    @_run_finalize_lock.setter
    def _run_finalize_lock(self, value):
        self.__dict__["_run_finalize_lock_state"] = value

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
            {"status": "not_running", "base_run_id": str, "flag_registered": bool}
            — 未命中（evo-add-run-stop-loss 1.1 起仍按 base_id 登记取消旗标，
            flag_registered=True；旗标键含 epoch，仅本 run 的复活/重派 attempt
            会被启动守卫拦截，无跨 run 泄漏）。
        """
        base_id = self._normalize_run_id(run_id)

        # 按基础 run_id 匹配所有活跃 attempt；带 ``-`` 边界（同 _run_id_in_flight
        # 口径）防 base id 前缀撞上其他更长 run_id 的 attempt（如 impl-x-100
        # 不得命中 impl-x-1000-a1）而误报 cancel_requested。
        matched_attempts = [
            aid for aid in list(self._running_agents.keys())
            if aid == base_id or aid.startswith(base_id + "-")
        ]

        if not matched_attempts:
            # evo-add-run-stop-loss 1.1（A）：attempt 间隙取消。2026-09-25
            # planner-plan 事故：取消恰好落在 attempt 退出与下一 attempt（或
            # in-place retry -r<n>）重派之间的间隙，原 not_running 分支不登记
            # 旗标直接返回，重派的 attempt 复活再跑 36 分钟（run 级成本全部
            # 沉没）。现按 base_id 登记旗标（复用 add-run-cancel 的归一化、
            # 幂等集合与 reason/by 元数据），随后复活/重派的 attempt 在启动
            # 守卫（_attempt_top_guards）与 in-place retry 让位复查处命中即
            # 有序终止；在飞 attempt（若有）照常走轮询环取消，行为不变。
            with self._cancel_requested_lock:
                self._cancel_requested.add(base_id)
                self._cancel_meta[base_id] = {"reason": reason, "by": by}
            self.logger.warning(
                "agent_runner",
                f"cancel_run: run '{base_id}' 无活跃 attempt，已登记取消旗标"
                f"（attempt 间隙取消，复活/重派 attempt 将被启动守卫拦截；"
                f"reason={reason!r}, by={by}）",
            )
            return {
                "status": "not_running",
                "base_run_id": base_id,
                "flag_registered": True,
            }

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
        # 恒成功：无限等待直至获取信号量（无排队超时/失败返回路径，
        # 见 _planner_throttle_acquire 契约），无需检查返回值
        self._planner_throttle_acquire(spec_name, run_id, sem)
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
          typo|reference|missing|unclear）；派发前会 unlink 上一轮结果文件
          （陈旧裁决防护：本轮未落新文件时读取侧按等价 unclear 兜底，不消费
          上一轮裁决）；
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

        # 派发前清除上一轮结果文件（陈旧裁决防护，与 engine
        # 「Ignoring stale result file」同取向）：结果文件按 spec 固定路径跨轮
        # 复用且内容不带 run id，若本轮 judge 收工但未落新文件（未按输出契约
        # 写盘/写盘中断），读取侧会把上一轮裁决误当作本轮结论消费。派发前
        # unlink 使「本轮未写 = 文件不存在」，读取侧（_read_dispute_verdicts）
        # 自然按等价 unclear 兜底。删除失败不阻断派发（文件不存在属常态；
        # 其他异常 debug 级留痕）。
        result_path = vp_dir / "dispute_judge_result.json"
        try:
            result_path.unlink()
            self.logger.debug(
                "agent_runner",
                f"已清除上一轮 dispute judge 结果文件 '{spec_name}': {result_path}",
            )
        except FileNotFoundError:
            pass
        except OSError as e:
            self.logger.debug(
                "agent_runner",
                f"清除上一轮 dispute judge 结果文件失败 '{spec_name}'"
                f"（不阻断派发）: {e}",
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
                self._ensure_agent_config_dir(provider["name"], model_override)
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
            # 收工后补写 run stamp（code-review item 01d1335a9902）：结果文件按
            # spec 固定路径跨轮复用且内容不带 run id——派发前 unlink 失败 +
            # 本轮 judge 未写盘时，读取侧会误消费上一轮裁决。此处确定性补写
            # run_id，读取侧（_read_dispute_verdicts）据此做 stamp 严格匹配
            # （对齐 engine._cleanup_shared_result_file 范式）。补写失败仅留痕：
            # 读取侧 run stamp 校验不过 → 等价 unclear 兜底（fail-closed）。
            try:
                _rp = vp_dir / "dispute_judge_result.json"
                if _rp.exists():
                    _rd = json.loads(_rp.read_text(encoding="utf-8"))
                    if isinstance(_rd, dict):
                        _rd["run_id"] = run_id
                        _rp.write_text(
                            json.dumps(_rd, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
            except Exception as _e:
                self.logger.warning(
                    "agent_runner",
                    f"dispute judge 结果补写 run stamp 失败 '{spec_name}'"
                    f"（读取侧按等价 unclear 兜底）: {_e}",
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
        # 确保结果目录存在（与 run_dispute_judge 同口径：目录创建失败收口为
        # 结构化失败结果，OSError 不裸冒泡给调用方）
        try:
            result_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return AgentRunResult(
                run_id, spec_name, "spec-review",
                success=False, duration_seconds=0.0,
                error=f"spec review 结果目录创建失败: {e}",
            )

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
                self._ensure_agent_config_dir(provider["name"], model_override)
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

    def _planner_throttle_acquire(self, spec_name: str, run_id: str,
                                  sem: threading.BoundedSemaphore) -> None:
        """持槽等待信号量直至获取（恒成功，无失败返回路径；可观测 + 等待期
        保活，design D2 备选方案）。

        - 排队无时长上限：本方法无限等待直至 acquire 成功才返回（恒成功，
          调用方无需检查返回值），等待期靠保活心跳维持 run 流新鲜；
        - ``sem`` 必须传入调用方经 _planner_throttle_semaphore() 取得的同一
          实例——acquire 与调用方 finally 的 release 须落在同一对象。若在此
          处无锁重读模块全局，热更新重建信号量的窗口内会 acquire 到新对象、
          release 落到旧对象（旧对象无对应 acquire 时抛 ValueError 且新对象
          槽位泄漏）；
        - 排队可观测：等待开始时打 INFO 日志（spec 名 + 并发上限），
          时间轴可审计；
        - 等待期保活：run 尚未启动（_execute_agent 内才创建 attempt run），
          以带超时的 acquire 轮询获取，等待期间按心跳周期向预生成 run 文件
          追加 ``throttled-wait`` 事件行——保持 run 流新鲜，避免等待超过
          stuck 阈值（160min）且无写入时被 recovery watch 误判为
          stuck/dispatch_stalled（spec「排队不被误判」Scenario）。
        - 取消（RunCancelledError）在等待期不可达（无子进程可终止），因此
          仅释放义务由调用方 finally 承担。
        """
        self.logger.info(
            "agent_runner",
            f"planner 节流排队中: spec={spec_name} run={run_id} "
            f"并发上限 {_PLANNER_SEMAPHORE_LIMIT}（持槽等待）",
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
                return
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

    def run_fast_track(self, spec_name: str, pre_wt_path: Path | None = None) -> AgentRunResult:
        """Run the Fast-Track Agent for a SPEC (single run: implement + verify).

        Fast-track run 同时完成实现与验证（实现+场景设计+验证+判定）。
        生成的分支与成功路径 merge 语义与 implementer 一致；budget 沿用
        impl_run_budget（走 impl- 前缀 run_id，复用既有计数/对账路径）。

        Args:
            spec_name: SPEC 名称。
            pre_wt_path: 可选。非 None 时在既有 worktree 内续做
                （interrupt-recovery-preserve 恢复续做），不创建新 worktree；
                语义与 ``run_implementer`` 的 pre_wt_path 相同。
        """
        run_id = f"impl-{spec_name}-{int(time.time())}"
        return self._execute_agent(
            spec_name, "fast-track", run_id, pre_wt_path=pre_wt_path
        )

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

    def _build_isolated_settings(self, provider_model: str = "") -> dict:
        """构造隔离 settings.json：enabledPlugins / hooks / env 子代理模型映射（spec D2/D3）。

        从 ~/.claude/settings.json 复制 enabledPlugins（缺省 superpowers）。hooks 从
        .fenix/agent-settings.json 复制（PreToolUse block-image-read）。不复制宿主
        ~/.claude/settings.json 的 env 模型名映射——那属于 cc-switch 网关、对直连
        Provider 无用且有毒化子代理解析的风险（如陈旧 hy3）。Provider 的
        ANTHROPIC_MODEL/BASE_URL/API_KEY 经进程 env 注入。

        fix-agent-lane-efficiency D1：当传入 provider_model（直连 Provider 车道）时，
        额外注入一段**按该 provider 重算**的 env 模型映射——CLAUDE_CODE_SUBAGENT_MODEL
        与 ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL 均映射到 provider 自身模型，
        取值优先级为 agents.subagent_model_override（非空）→ provider_model。这使
        子代理 tier 解析永不回落到宿主 cc-switch 的官方模型名（直连 Provider 无此
        模型 → model_not_found 404）。provider_model 为空（未分配 provider，走默认
        网关）时不写任何 env——该路径行为与变更前逐字节一致。
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

        if provider_model:
            # D1：provider 作用域内重建的子代理模型映射（非复制宿主 cc-switch 映射）。
            # 取值优先级：agents.subagent_model_override（非空）→ provider 自身 model。
            from core.config import ConfigLoader as _CLSubagentModel

            config = getattr(self, "config", None) or {}
            subagent_model = (
                _CLSubagentModel.get_subagent_model_override(config)
                or provider_model
            )
            settings["env"] = {
                "CLAUDE_CODE_SUBAGENT_MODEL": subagent_model,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": subagent_model,
                "ANTHROPIC_DEFAULT_SONNET_MODEL": subagent_model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": subagent_model,
            }
        return settings

    # fix-agent-lane-efficiency D1：隔离 settings.json 内容版本标记。旧版本（无 env
    # 子代理模型映射）settings.json 在已部署机器上已存在（_ensure_agent_config_dir 现行
    # 「marker 已存在即 return」会永不重建）——实现版本标记 + 内容不匹配时原子重写，
    # 使新映射在存量隔离目录上也生效。
    ISOLATED_SETTINGS_SCHEMA_VERSION = 2

    def _ensure_agent_config_dir(self, provider_name: str, provider_model: str = "") -> Path:
        """按需生成并返回 Provider 的隔离配置目录（spec D1/D2/D5）。

        目录：.fenix/agent-config/<provider_name>/，含 settings.json 与指向
        ~/.claude 的 skills/plugins symlink（源目录不存在则跳过，优雅降级）。
        幂等：settings.json 已存在且内容与将写入内容一致（含 schema 版本标记）则
        跳过重建；存在旧版/内容不匹配时原子重写（tempfile + os.replace，保留既有
        symlink）。并发首次创建由原子 mkdir + temp+rename 写文件兜底。

        fix-agent-lane-efficiency D1：传入 provider_model（直连 Provider 车道）时
        settings.json 含按 provider 重算的 env 子代理模型映射；存量旧 settings.json
        （无 env 段）会被内容比对识别并原子重写为最新映射。
        """
        cfg_dir = self.project_root / ".fenix" / "agent-config" / provider_name
        marker = cfg_dir / "settings.json"
        settings = self._build_isolated_settings(provider_model)
        settings["_schema_version"] = self.ISOLATED_SETTINGS_SCHEMA_VERSION
        try:
            cfg_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return cfg_dir

        def _write_atomic() -> None:
            # code-review item a340597064c9：mkstemp 生成唯一临时文件（固定
            # .settings.tmp 在并发首建/重写时交错截断写坏 settings.json），
            # 与 _copyback_run_result 的 _write_atomic 同款手法。
            fd, tmp_name = tempfile.mkstemp(
                prefix=".settings.", suffix=".tmp", dir=str(cfg_dir))
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(settings, ensure_ascii=False, indent=2))
                os.replace(tmp_path, marker)
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

        if marker.is_file():
            try:
                existing = json.loads(marker.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and existing == settings:
                    return cfg_dir
            except (OSError, json.JSONDecodeError):
                pass
            # 内容不匹配（旧版无 env / 用户改过 / 损坏）→ 原子重写（幂等陷阱处置）
            try:
                _write_atomic()
            except OSError:
                pass
            return cfg_dir

        try:
            _write_atomic()
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

    # ── add-impl-code-review-gate：run 级 ocr 配置写入 ─────────────────────
    # 写一份 run 级 .opencodereview/config.json 到 provider 隔离目录的
    # ocrcfg/ 子目录，使 ocr 复用分配给本次 implementer run 的那个 provider
    #（baseurl/apikey/model 与 fenix 记账同源）。包装器 bin/ocr_review.py 把
    # HOME 指向该子目录后 exec ocr，ocr 读 $HOME/.opencodereview/config.json。

    def _ocr_home_for_provider(self, provider_name: str) -> Path:
        """返回包含 .opencodereview/config.json 的 HOME 目录（即 ocrcfg/ 本身）。

        不变量：返回值 P 满足 (P / ".opencodereview" / "config.json").is_file()
        当写入成功；ocr 只认 $HOME/.opencodereview/config.json，HOME 指到父
        目录则配置文件永远读不到（design D2）。
        """
        return self.project_root / ".fenix" / "agent-config" / provider_name / "ocrcfg"

    def _write_run_ocr_config(self, provider: dict, model: str) -> Optional[Path]:
        """写 run 级 ocr 配置，返回 HOME 目录路径（失败返回 None）。

        在 _ensure_agent_config_dir 建立的 provider 隔离目录下建 ocrcfg/
        子目录，写 .opencodereview/config.json（原子替换，同款 _ensure_agent_config_dir
        手法）。provider 名固定为 "fenix-impl"（避免与 ocr 内置预设名撞名）；
        url 原样透传 provider["baseurl"]（不追加版本后缀，实测 ocr 自行拼
        /v1/messages）。

        ``timeout_sec`` 来源：``ConfigLoader.get_impl_code_review_timeout_sec``
        解析 ``verify.impl_code_review_timeout_sec`` 的结果（缺省 600，秒）。
        语义：ocr LLM 单请求超时（连响应头都算在内）——不配置时 ocr 走其内置
        300s 默认，实测 8 路并发 + 300s 单请求超时会撞穿首字节等待导致大面积
        文件级 timeout（duration_to_headers_ms 恰 300000）；注入后确定性生效
        （探针实验：timeout_sec=20 时 duration_to_headers_ms≈20000）。

        Args:
            provider: 已选定的 provider dict（含 name/baseurl/apikey）
            model: 本轮实际生效的模型名（与 fenix 记账同源）
        Returns:
            HOME 目录路径（ocrcfg/ 本身），或写入失败时 None
        """
        try:
            from core.config import ConfigLoader as _CLOCR

            provider_name = provider.get("name", "unknown")
            home_dir = self._ocr_home_for_provider(provider_name)
            ocr_cfg_dir = home_dir / ".opencodereview"
            ocr_cfg_dir.mkdir(parents=True, exist_ok=True)
            config_path = ocr_cfg_dir / "config.json"
            config_data = {
                "provider": "fenix-impl",
                "custom_providers": {
                    "fenix-impl": {
                        "api_key": provider.get("apikey", ""),
                        "url": provider.get("baseurl", ""),
                        "protocol": "anthropic",
                        "model": model,
                        # add-impl-code-review-tuning：ocr LLM 单请求超时（秒），
                        # 与 api_key/url/protocol/model 同批原子写入。
                        "timeout_sec": _CLOCR.get_impl_code_review_timeout_sec(
                            self.config
                        ),
                    }
                },
            }
            # 原子替换（code-review item a340597064c9：mkstemp 唯一临时名——
            # 固定 .config.json.tmp 并发写同一路径时交错截断写坏 config.json，
            # 与 _copyback_run_result 的 _write_atomic 同款手法）
            fd, tmp_name = tempfile.mkstemp(
                prefix=".config.json.", suffix=".tmp", dir=str(ocr_cfg_dir))
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(config_data, ensure_ascii=False, indent=2))
                os.replace(tmp_path, config_path)
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
            return home_dir
        except (OSError, json.JSONDecodeError) as e:
            self.logger.warning(
                "agent_runner",
                f"[impl-code-review-gate] _write_run_ocr_config 失败，跳过 ocr 注入: {e}",
                {"provider": provider.get("name", "unknown"), "model": model},
            )
            return None

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

    def _is_main_worktree(self, wt_path: Path) -> bool:
        """判断 wt_path 是否为主工作树（而非 git 链接 worktree）。

        两重判据，任一命中即主树：
        - 解析后等于 project_root（dispute-judge / spec-review / 维护型等
          无 worktree 车道直接以主树为 cwd）；
        - ``git rev-parse --git-common-dir`` 与 ``--git-dir`` 指向同一路径
          （链接 worktree 的 git-dir 是 ``<common>/worktrees/<name>`` 子目录，
          仅主工作树二者同源）。
        任何异常（权限/超时）按"非主树"处置——返回 False 交由既有失效/
        降级路径兜底，不改变调用方行为。
        """
        try:
            if wt_path.resolve() == self.project_root.resolve():
                return True
            proc = subprocess.run(
                ["git", "-C", str(wt_path),
                 "rev-parse", "--git-common-dir", "--git-dir"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode != 0:
                return False
            lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
            return len(lines) == 2 and lines[0] == lines[1]
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

        第三种调用形态（add-freeze-stop-inflight-agents D1，锚点
        freeze-hold）：frozen 预终止——``proc.terminate()`` 之前调用，此刻
        子进程仍存活、无法证明不再写盘。冻结即停、不再有下一 attempt 的
        退避窗口保全机会，故有意接受竞态代价：git add/commit 可能纳入半写
        文件、也可能撞 index.lock 使保全失败（仅 WARNING，不阻断冻结终止）。

        无 worktree 载体或路径失效时跳过（与锚点 A/B 同语义，幂等）。
        主工作树同样跳过（fix-main-tree-wip-checkpoint）：dispute-judge /
        spec-review / 维护型等无 worktree 车道的 cwd 就是 project_root，
        而 _worktree_path_valid 对主树恒 True——对主树 WIP 提交会把无关
        脏状态卷进主分支历史，故 WIP 保全只对拥有专属 worktree 的车道执行。
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
        if self._is_main_worktree(wt_path):
            self.logger.debug(
                "agent_runner",
                f"WIP checkpoint ({anchor}) skip: {wt_path} is the main "
                f"worktree (no dedicated worktree lane) for '{spec_name}'",
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

    def _turn_branch_state_forget(self, run_id: str) -> None:
        """run 收尾摘除该 run 的轮次分支基线（code-review item b9f426346304）。

        ``_turn_branch_state`` 按 run_id（每次 run 唯一）记忆分支提交基线，
        仅 ``_turn_limit_action`` 在 run 存续期消费；run 终态后不摘除会在
        长跑 daemon 内随 run 数无界累积（实例级泄漏）。

        code-review item 9dc9195cbd73：摘除由 ``_execute_agent`` 的终态
        finally 统一调用（任意终态路径都经此外口，替代原先仅 success /
        exhausted 两收口的遗漏）；且 ``_turn_limit_action`` 经 ``_run_claude``
        以 attempt/sub-run 派生 id（``<run_id>-a<n>[-r<m>]``）记键，摘除须
        连带本 run 派生的全部子键。摘除失败不阻断收口。
        """
        state = getattr(self, "_turn_branch_state", None)
        if state:
            try:
                prefix = f"{run_id}-"
                for key in [k for k in state
                            if k == run_id or k.startswith(prefix)]:
                    state.pop(key, None)
            except Exception:  # noqa: BLE001 — 清理失败绝不影响 run 收尾
                pass

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
          _select_chain_candidate 选首个未冷却候选（链指针为 run 级：仅本次 run
          的 attempt 间记忆切换进度，跨 run 由 _select_chain_candidate 重新选点）。
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
            # 轮次分支基线按 run 摘除（code-review item b9f426346304 /
            # 9dc9195cbd73）：统一在 run 终态外口摘除，覆盖 success/exhausted
            # 两收口之外的全部早退终态 return（frozen/取消/熔断/链耗尽/让位）。
            self._turn_branch_state_forget(run_id)
            # evo-add-run-stop-loss 1.1：取消旗标随 run 终态外口幂等清理——
            # 覆盖「not_running 间隙登记后 run 未再复活即自然收尾」的路径
            # （旗标键含 epoch，不清理也不跨 run 误伤，摘除仅为生命周期
            # 卫生）；与 success/exhausted/守卫/轮询环四处既有清理互为幂等。
            self._cancel_clear(run_id)
            # evo-add-run-stop-loss 2.1：判停统计随 run 终态外口摘除（键含
            # epoch 不清理也不跨 run 误伤，摘除仅为生命周期卫生；建态时另有
            # 24h 过期淘汰兜底非派发链路的直调泄漏）。
            self._stall_budget_forget(run_id)
            # per-run 终态回调触发（add-mergeback-wip-active-coordination D2）：
            # 终态收口处（成功/失败/取消/冻结/熔断等任意终态都经本 finally）
            # 消费回调表——持有者 run 收尾即唤醒 defer 批合回事件驱动重试。
            try:
                self._fire_run_terminal_callbacks(run_id)
            except Exception as e:
                self.logger.warning(
                    "agent_runner", f"run 终态回调触发异常（不阻断结果返回）: {e}")
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
        # 误配置下限钳制：0/负数/None/非整数值会使 attempt 循环体不执行，
        # 收口处 _exhausted_result 引用未绑定的 error 抛 UnboundLocalError，
        # 失败形态与真实死因（配置非法）无关。非法值统一回落缺省 3。
        try:
            max_retries = max(1, int(max_retries))
        except (TypeError, ValueError):
            max_retries = 3
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
            frozen_terminated_flag=False,
            stall_budget_flag=False,
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
        frozen_terminated_flag = st.frozen_terminated_flag
        stall_budget_flag = st.stall_budget_flag

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
            sub_run_id = attempt_run_id

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
                            self._ensure_agent_config_dir(provider["name"], model)
                        )
                        # 注入 provider 自定义环境变量（如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）
                        for k, v in (provider.get("env") or {}).items():
                            env_overrides[k] = v
                        model_override = model
                        # add-impl-code-review-gate：run 级 ocr provider 注入——
                        # 复用分配给本 run 的 provider（baseurl/apikey/model 与
                        # fenix 记账同源，model 取 model_override 即本分支生效值）；
                        # 开关关闭 / 写入失败时跳过（审查环境缺失不影响实现 run 主体）。
                        from core.config import ConfigLoader as _CLOCR

                        try:
                            if _CLOCR.get_impl_code_review_enabled(self.config):
                                ocr_home = self._write_run_ocr_config(provider, model_override)
                                if ocr_home is not None:
                                    env_overrides["FENIX_OCR_HOME"] = str(ocr_home)
                                env_overrides["FENIX_OCR_BIN"] = DEFAULT_OCR_BIN
                                # ocr node 启动器的版本检查开关——HOME 重定向到 run 级
                                # 目录后避免 detached 拉起联网 update.js 的游离请求
                                env_overrides["OCR_NO_UPDATE"] = "1"
                        except Exception as e:
                            self.logger.warning(
                                "agent_runner",
                                f"[impl-code-review-gate] ocr 配置注入异常，跳过: {e}",
                                {"run_id": attempt_run_id},
                            )
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
                    # add-impl-terminal-nocommit-gate（D2）：终态零提交门——
                    # 判定 MUST 落在 while 循环 try 体内（成功 break 之前、
                    # 拷回与产物硬门之后），抛出的 AgentArtifactGateError 才能
                    # 被本层 except AgentArtifactGateError 接住，经
                    # _handle_artifact_gate_retry 的 [terminal-no-commit] 分支
                    # 走锚点 B WIP 提交 + 原地退避 + 同 worktree resume 续做。
                    # 此前判定误置于 _finalize_success（break 之后的 return
                    # 调用、except 作用域之外），异常会裸抛穿调度层、重试通道
                    # 不可达。wt_dirty 取证口径与 _finalize_success 相同
                    # （git status --porcelain，失败按空列表 fail-open）。
                    if agent_type == "implementer":
                        # fix-nocommit-gate-git-forensics-failopen：复用
                        # _git_status_porcelain 取证（OSError/SubprocessError
                        # 按空列表 fail-open），git 超时/缺失不吞已到手的
                        # 成功终态——与本注释上方声明的口径一致。
                        _nc_dirty = self._git_status_porcelain(wt_path)
                        self._check_terminal_no_commit_gate(
                            spec_name=spec_name, agent_type=agent_type,
                            wt_path=wt_path,
                            branch=self.worktree_manager.get_branch_name(wt_path),
                            wt_dirty=_nc_dirty, sub_run_id=sub_run_id)
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
                except FrozenTerminatedError as e:
                    # add-freeze-stop-inflight-agents D1/D3：冻结终止专用捕获
                    # ——不重试、不计秒挂、不触发 provider 链切换，与取消同列但
                    # 走独立 frozen_terminated 结果通道（dispatch 写 _frozen_hold）。
                    output = ""
                    turns = 0
                    success = False
                    frozen_terminated_flag = True
                    error = (FROZEN_TERMINATED_ERROR_PREFIX
                             + (f": {e.reason}" if e.reason else ""))
                    self.logger.info(
                        "agent_runner",
                        f"{agent_type} for '{spec_name}' run 因 spec 冻结被终止"
                        f"（attempt {attempt}）：{error}",
                    )
                    usage_info = self._extract_usage_info(None)
                    break  # 原地重试子循环：冻结退出 while
                except RunStallBudgetExceededError as e:
                    # evo-add-run-stop-loss 2.1：停滞判停专用捕获——不重试、
                    # 不计秒挂、不触发 provider 链切换，与取消/冻结并列的独立
                    # 终止通道。stall_budget_flag 使 no-retry 条件立即收场
                    #（终止整个重试链：止损被瞬态重试/in-place retry 重派
                    # 放大即失去意义），run 以 [run-stall-budget] 前缀失败终态。
                    output = ""
                    turns = 0
                    success = False
                    stall_budget_flag = True
                    error = (RUN_STALL_BUDGET_ERROR_PREFIX
                             + f" 命中判据 {e.criterion}: {e.detail}")
                    self.logger.info(
                        "agent_runner",
                        f"{agent_type} for '{spec_name}' run 停滞判停止损"
                        f"（attempt {attempt}）：{error}",
                    )
                    usage_info = self._extract_usage_info(None)
                    break  # 原地重试子循环：判停止损退出 while
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
                        # 与上方 shutdown 守卫同源取在飞产物文件：interrupted
                        # 终态补写在 sub_run_id（原地重试后 ≠ attempt_run_id）
                        self.project_root / ".fenix" / "runs" / f"{sub_run_id}.jsonl",
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
                    # 4xx 熔断计数 + 瞬断判定（见 _record_4xx_or_transient）；
                    # 透传 attempt 元信息（spec_name / attempt_run_id，均在该
                    # 作用域内）供瞬断记账聚合注入（evo-transient-storm-alert-context D1）
                    error, is_transient, _may_switch = self._record_4xx_or_transient(
                        error, provider_name, agent_type,
                        getattr(e, "stderr_lines", None),
                        getattr(e, "exit_code", None),
                        getattr(e, "has_result", None),
                        spec_name=spec_name,
                        run_id=attempt_run_id,
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
                        # add-impl-selfcheck-model-probe（2.1）：unrecognized_model
                        # 命中即记 WARNING（provider/model/run_id，供链摘除决策）。
                        # 链尾模型仍被拒 → 归因注入「全链模型不可用」语义（2.2，
                        # 派发器据此跳过同因重派）并置旗标：attempt 预算立即收场，
                        # 对同一拒模型再起必败进程是纯浪费。
                        if self.classify_unrecognized_model_error(error):
                            self._record_unrecognized_model(
                                provider_name, model, attempt_run_id, spec_name)
                            st.chain_reject_hits += 1
                            if st.chain_cursor + 1 >= len(chain):
                                error = annotate_model_chain_unavailable(
                                    error, provider_name, model, st.chain_reject_hits)
                                st.chain_rejected_exhausted = True
                        # add-code-review-concurrency-and-429-resilience（D3）：
                        # 429 限流冷却走同一通道但用独立常量时长（非
                        # switch_cooldown_seconds 配置），便于限流调参。
                        if self.classify_ratelimit_error(error):
                            self._record_switch_cooldown(
                                provider_name,
                                cooldown_seconds=PROVIDER_RATELIMIT_COOLDOWN_SECONDS,
                            )
                        else:
                            self._record_switch_cooldown(provider_name)
                        # 仅当链上还有后续候选才前进指针；否则保持当前（全链耗尽将
                        # 在下一 attempt 的 _select_chain_candidate 中判定为 chain_exhausted）。
                        if st.chain_cursor + 1 < len(chain):
                            st.chain_cursor += 1
                    # fix-provider-transient-backoff（D2）：implementer 失败后从产物尾部
                    # 提取 session_id 供续跑（attempt 间 worktree 保留扩展到全部
                    # agent_type，session 随同现场保留）。repair 有意排除：载体由调度层
                    # 三态解析（原地或换壳）、失败交还调度层重新解析，worktree 生命周期
                    # 与续跑决策均在调度层——旧 session 绑定旧载体的会话现场，对换壳
                    # 后的新载体不可复用。
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
                    frozen_terminated_flag=frozen_terminated_flag,
                    stall_budget_flag=stall_budget_flag,
                    st=st, handed_off=handed_off,
                )
                wt_path = st.wt_path
                kept_wt_path = st.kept_wt_path
                # add-impl-selfcheck-model-probe（2.2）：链尾拒模型已注入
                # [model-chain-unavailable] 归因 → 同因重派必然撞同一拒模型链，
                # 剩余 attempt 预算立即放弃（error 已带归因，走 _exhausted_result
                # 既有失败终态路径）。
                if should_break or st.chain_rejected_exhausted:
                    break

        return self._exhausted_result(
            spec_name, agent_type, run_id, max_retries, start_time,
            error=error, turns=turns, usage_info=usage_info,
            provider_name=provider_name, model=model,
            cancelled_flag=cancelled_flag, shutdown_interrupted=shutdown_interrupted,
            frozen_terminated_flag=frozen_terminated_flag,
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
            # evo-add-worktree-acquire-backoff（design 1/2）：create 失败不再
            # 「sleep(5) 一次 + 单一判定」，改由 _prepare_worktree 内分探针
            # 处置——锁活跃（并行 run 持同 spec:agent_type 锁）走短退避等待
            # 重试（不消耗 attempt 重试额度，等持锁方排空）；frozen/
            # _cancelled_hold/status 迁出预期态三种人工接管态立即让位不进
            # 退避；其余失败保持既有 attempt 层重试语义。
            wt_path, acquire_yield = self._create_worktree_with_backoff(
                spec_name, agent_type)
            if wt_path is None:
                error_msg = "Failed to create worktree"
                self.logger.error("agent_runner", error_msg)
                if acquire_yield in ("human-takeover",
                                     "lock-backoff-exhausted"):
                    # 退避耗尽仍锁活跃 / 人工接管让位 → 既有 gave up 终态
                    #（错误文案保持 fix-restart-dual-dispatch 既有签名）
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
                if attempt < max_retries:
                    time.sleep(5)
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

    # ── evo-add-worktree-acquire-backoff：锁让路退避取得 worktree ──────
    # 退避序列（design 1）：锁活跃导致的 create 失败按该序列等待重试，
    # 在 _prepare_worktree 内完成、不消耗 attempt 重试额度；耗尽才交还
    # 调用方走既有 gave up 终态。
    WORKTREE_ACQUIRE_BACKOFF_SEQUENCE = (30, 60, 120)

    def _create_worktree_with_backoff(self, spec_name: str,
                                      agent_type: str) -> tuple:
        """create worktree，锁活跃时按短退避序列等待重试
        （evo-add-worktree-acquire-backoff design 1/2）。

        create 返回 None 后按原因分探针分流（不改
        _should_give_up_before_retry 既有签名与语义）：
        - 人工接管态（frozen / _cancelled_hold / status 迁出预期态，经
          check_lock=False 探针）：立即让位，不进退避——人工接管语义
          不可自动穿越；
        - 锁活跃（has_active_lock 探针，并行 run 持同 spec:agent_type
          锁）：按 WORKTREE_ACQUIRE_BACKOFF_SEQUENCE 退避等待重试，
          每轮重探前复查人工接管态（等待期间被冻结/取消保持/status
          迁出，含并行 run 完成后的状态迁移，即立即让位，不得在锁
          释放后照常取得 worktree——先例：provider-transient 退避的
          重派前复查）；锁释放后下一轮 create 即取得。
        - 其余失败原因（非锁、非人工接管）：不等待，交还调用方按
          既有 attempt 层语义处理。

        返回 (wt_path, acquire_yield)：
        - wt_path 非 None → 取得成功，acquire_yield 为 None；
        - wt_path 为 None → acquire_yield 为让位/失败原因：
          "human-takeover"（人工接管让位）/
          "lock-backoff-exhausted"（退避耗尽仍锁活跃）/
          "create-failed"（其它失败原因）
        """
        wt_path = self.worktree_manager.create(spec_name, agent_type)
        if wt_path is not None:
            return wt_path, None
        # 分探针 1：人工接管态立即让位（check_lock=False——锁由下方独立分流）
        if self._should_give_up_before_retry(spec_name, agent_type,
                                             check_lock=False):
            return None, "human-takeover"
        # 分探针 2：非锁活跃（git 失败等其它原因）不进退避
        wm = self.worktree_manager
        if wm is None or not wm.has_active_lock(spec_name, agent_type):
            return None, "create-failed"
        seq = self.WORKTREE_ACQUIRE_BACKOFF_SEQUENCE
        for round_no, backoff in enumerate(seq, start=1):
            self.logger.warning(
                "agent_runner",
                f"Worktree create for '{spec_name}' ({agent_type}) blocked "
                f"by active spec lock — waiting {backoff}s before re-probe "
                f"({round_no}/{len(seq)}) "
                f"(evo-add-worktree-acquire-backoff)",
            )
            time.sleep(backoff)
            # 每轮重探前复查人工接管态：等待期间 spec 被冻结/取消保持/
            # status 迁出预期态 → 立即让位，不得照常取得 worktree。
            if self._should_give_up_before_retry(spec_name, agent_type,
                                                 check_lock=False):
                self.logger.warning(
                    "agent_runner",
                    f"Worktree acquire for '{spec_name}' ({agent_type}) "
                    f"yields during lock backoff: spec 已被人工/其它链路"
                    f"接管",
                )
                return None, "human-takeover"
            wt_path = self.worktree_manager.create(spec_name, agent_type)
            if wt_path is not None:
                self.logger.info(
                    "agent_runner",
                    f"Worktree for '{spec_name}' ({agent_type}) acquired "
                    f"after lock wait ({round_no}/{len(seq)}) — peer run "
                    f"released spec lock",
                )
                return wt_path, None
            # 锁已释放但 create 仍失败（命名重试撞满、git 错误等）→
            # 交还调用方按既有 attempt 层语义处理，不再空转退避。
            if not wm.has_active_lock(spec_name, agent_type):
                return None, "create-failed"
        return None, "lock-backoff-exhausted"

    # ── R6 子步 1: 4xx 熔断计数 + 瞬断判定（等价搬移，D1 R6 表）──────
    # 纯副作用：4xx 计数 / 半开探针闭合失败记账 / 瞬断判定 / 全局瞬断指纹记账。
    # 无跨边界 continue/break/return（D2 边界），可安全提取。
    # 模块级名 PROVIDER_CIRCUIT_4XX / PROVIDER_CIRCUIT_THRESHOLD / 实例方法
    # 均保持从 runner.py 模块全局访问（D7 patch 缝隙）。
    def _record_4xx_or_transient(self, error, provider_name, agent_type,
                                 exc_stderr, exc_exit, exc_has_result,
                                 spec_name=None, run_id=None) -> tuple:
        """4xx 熔断计数 + 瞬断判定（等价搬移自 R6 的 `if provider_name:` 段）。

        返回 (error, is_transient, may_switch)：error 可能被注入
        `[provider-transient]` 前缀（瞬断终态/重试共用标记，
        transient-dispatch-gating D4）；is_transient 供调用者决定是否走原地
        退避重试；may_switch 指示调用者是否可尝试 switch 冷却——原 `else:`
        分支（provider 在位且 code 非 4xx）语义，4xx/无 provider 均不得触发
        switch（维持既有熔断语义、链指针不动）。无跨边界控制流。

        spec_name/run_id 为瞬断记账的 attempt 元信息（evo-transient-storm-alert-
        context D1）：缺省 None → 空串占位正常记账，既有调用零改动。
        """
        if not provider_name:
            return error, False, False
        # evo-sigterm-source-tracking-cooldown：信号死法（[signal-kill: …] 前缀）
        # 不入瞬断通道——不归 [provider-transient]、不排原地重试、不记全局瞬断
        # 指纹（信号死法的重试与冷却由信号冷却通道（spec 维度）管辖，反复撞
        # 运气至预算耗尽的形态即由该通道熔断）。
        if error and error.startswith("[signal-kill:"):
            return error, False, False
        # add-impl-selfcheck-model-probe（2.1）：unrecognized_model 是 provider
        # 明确返回的**确定性拒模型**，判定须先于 4xx 解析——拒模型常伴随 404
        # 形态（unrecognized_model 对应 404），先走 4xx 分支会误入熔断计数且
        # 不切链。命中：非瞬态（不进原地退避重试、不记全局瞬断指纹、不递增
        # 同因重派计数）、may_switch=True（调用方沿链前进 + switch 短冷却，
        # 复用 add-provider-failover 既有机制，无平行切换路径）。WARNING 告警
        # 与链尾归因标注在调用方 attempt 循环（该作用域有 model / run_id）。
        if error and self.classify_unrecognized_model_error(error):
            return error, False, True
        # add-code-review-concurrency-and-429-resilience（D3）：429 限流是暂时性
        # 配额压力——非瞬态（不进原地退避重试：冷却期内原地重试同一账号只会
        # 继续撞 429，纯烧预算）、may_switch=True（调用方沿链前进 + 限流冷却，
        # 复用 switch 冷却通道）。判定 MUST 先于 4xx 解析与瞬断通道——429 形态
        # 常伴随「exit 1 + 无 result + 诊断行」（瞬断通道 2 会把它误判瞬断进
        # 原地重试）；且 429 不在 PROVIDER_CIRCUIT_4XX 内，天然不进熔断计数。
        if error and self.classify_ratelimit_error(error):
            return error, False, True
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
            # 字样），与 D2 判定同源。attempt 元信息（spec/run_id/provider）
            # 透传记账（evo-transient-storm-alert-context D1，供触发时聚合
            # 注入告警上下文——对指纹归一化免疫）。
            try:
                self.record_transient_break(
                    "\n".join(str(l) for l in exc_stderr) or error,
                    spec=spec_name,
                    run_id=run_id,
                    provider=provider_name,
                )
            except Exception as _break_err:
                self.logger.debug(
                    "agent_runner",
                    f"global transient break 记账失败（不阻断）: {_break_err}",
                )
        return error, is_transient, True  # may_switch：else 分支（provider 在位且 code 非 4xx）

    # ── 429 限流终态归因与重派意图登记（add-code-review-concurrency-and-429-resilience D4）──
    def _ratelimit_redispatch_on_terminal(self, run_id: str, error: str,
                                          provider_name: str | None = None,
                                          spec_name: str = "") -> dict | None:
        """run 终态归因为 429 限流时登记 ``ratelimit_redispatch`` 意图（design D4）。

        分工（design D4）：runner 只负责终态归因与意图登记——
        ① provider 进限流冷却（复用 switch 冷却通道与候选跳过语义，独立常量
        PROVIDER_RATELIMIT_COOLDOWN_SECONDS）：同 run/其它派发的链选择在冷却期
        跳过该候选（不启动 claude、不烧 429）；
        ② run jsonl 标注重派缘由（type=ratelimit_redispatch，含最早冷却到期
        时刻，spec failover-dispatch delta「运行记录 SHALL 标注重派缘由」）。

        意图 dict 经结果信封（CodeReviewResult.ratelimit_redispatch）上交消费
        侧（run_code_review 唯一生产调用方 admin_monitor._worker），由其在冷却
        到期后延迟重投递；重派上限（RATELIMIT_REDISPATCH_MAX=1）与单飞守卫由
        消费侧执行（run 已终态死亡，进程内无人续跑）。本函数对同一 run_id 只
        登记一次（jsonl 幂等：已有标注即不再登记；重派后的 run 是新 run_id，
        由消费侧上限守卫兜底，不会无限重派）。

        返回意图 dict（reason/provider/cooldown_until/cooldown_until_epoch）；
        非 429 / 空错误 / 已登记 → None。

        Args:
            run_id: 终态失败的 run 标识（jsonl 标注落点）。
            error: 终态错误文本（降噪后；分类判定同源 classify_ratelimit_error）。
            provider_name: 本次 run 实际使用的 provider（限流冷却落点；未知时
                跳过冷却记账、意图冷却到期时刻回退常量时长推算）。
            spec_name: 归属 spec（code-review 车道传 "code-review"）。
        """
        if not error or not self.classify_ratelimit_error(error):
            return None
        from core.agent_runner.provider_circuit import PROVIDER_RATELIMIT_COOLDOWN_SECONDS as _RL_CD

        run_file = self.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"
        # 幂等：同 run 已登记过即不再登记（重派后的 run 是新 run_id，消费侧
        # 上限守卫兜底——这里防的是同 run 重复登记刷屏）。
        try:
            if run_file.exists():
                for line in run_file.read_text(encoding="utf-8").splitlines():
                    if '"type": "ratelimit_redispatch"' in line:
                        return None
        except OSError:
            pass
        now = time.time()
        cooldown_until = 0.0
        if provider_name:
            try:
                cooldown_until = self.switch_cooldown_until(provider_name)
            except Exception:  # noqa: BLE001 — 冷却查询失败回退常量推算
                cooldown_until = 0.0
        # 时钟口径统一：switch_cooldown_until 返回的是 monotonic 时刻而非
        # epoch 秒，不得与 epoch now 直接比较/格式化。在效冷却按剩余单调差值
        # 换算成 epoch 截止；无冷却/已到期/查询失败（返回 0）回退常量时长
        # 推算——与原回退值同口径，延迟语义不变。
        _mono_now = self._now()
        if cooldown_until > _mono_now:
            cooldown_until = now + (cooldown_until - _mono_now)
        else:
            cooldown_until = now + _RL_CD
        # ① provider 进限流冷却（复用 switch 冷却通道与候选跳过语义；时长用
        # 独立常量——spec 限流冷却通道，design D3）。
        if provider_name:
            try:
                self._record_switch_cooldown(
                    provider_name, cooldown_seconds=_RL_CD)
            except Exception:  # noqa: BLE001 — 冷却记账失败不阻断意图登记
                pass
        # ② run jsonl 标注重派缘由（冷却到期时刻双格式：iso 供人读、epoch 供
        # 消费侧算延迟；写失败仅丢留痕，不阻断意图上交）。
        try:
            append_run_line(
                run_file,
                {
                    "type": "ratelimit_redispatch",
                    "run_id": run_id,
                    "spec": spec_name,
                    "provider": provider_name,
                    "reason": "429 ratelimit",
                    "cooldown_until": datetime.fromtimestamp(
                        cooldown_until, tz=timezone.utc).isoformat(),
                    "cooldown_until_epoch": cooldown_until,
                    "max_redispatches": RATELIMIT_REDISPATCH_MAX,
                },
            )
        except OSError:
            pass
        self.logger.info(
            "agent_runner",
            f"Ratelimit redispatch intent registered (add-code-review-"
            f"concurrency-and-429-resilience) — run={run_id} spec={spec_name!r} "
            f"provider={provider_name!r} cooldown_until="
            f"{datetime.fromtimestamp(cooldown_until, tz=timezone.utc).isoformat()}",
        )
        return {
            "reason": "429 ratelimit",
            "provider": provider_name,
            "run_id": run_id,
            "cooldown_until": datetime.fromtimestamp(
                cooldown_until, tz=timezone.utc).isoformat(),
            "cooldown_until_epoch": cooldown_until,
            "max_redispatches": RATELIMIT_REDISPATCH_MAX,
        }

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
        # 留痕写失败不改变重试决策（code-review item 449ab5cb953f：对齐
        # _planner_throttle_acquire/_ratelimit_redispatch_on_terminal 口径）
        try:
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
        except OSError as e:
            self.logger.warning(
                "agent_runner",
                f"transient_retry 留痕写入失败（不阻断退避重试）: {e}",
            )
        # fix-retry-orphan-active-runs D1：superseded
        # 终态补写——本文件末行恒为终态，恢复「终态后置」
        # 不变量。写侧紧跟 transient_retry = 本文件终态，
        # 重试在新 sub_run_id 文件继续（runner.py:1922
        # 换新注释处交叉引用）；daemon 退避窗口内死亡
        # 由 interrupted 补写接续（末行仍终态）。
        try:
            append_run_line(
                self.project_root / ".fenix" / "runs"
                / f"{sub_run_id}.jsonl", {
                    "type": "superseded",
                    "spec": spec_name,
                    "provider": provider_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except OSError as e:
            self.logger.warning(
                "agent_runner",
                f"superseded 留痕写入失败（不阻断退避重试）: {e}",
            )
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
        # evo-add-run-stop-loss 1.2（B）：planner-plan 增查并行出题标记——
        # 消费侧已把标记翻成 discarded（产物隔离/转串行收尾伴生写入）时，
        # 重派只会与已转道的串行出题竞跑；在途（dispatched）或无标记
        # （未注入/读取失败）不命中，重试照常。
        if self._parallel_plan_marker_discarded(spec_name, agent_type):
            self.logger.warning(
                "agent_runner",
                f"Provider-transient retry for '{spec_name}' "
                f"({agent_type}) yields: 并行出题标记已 discarded"
                f"（产物已隔离/转串行），放弃重派"
                f"（evo-add-run-stop-loss 1.2）",
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
                    f"{RETRY_YIELDED_ERROR_PREFIX} 并行出题标记已 discarded"
                    f"（产物已隔离/转串行出题），"
                    f"重试让位（evo-add-run-stop-loss 1.2）"),
                provider_used=provider_name, model_used=model,
            ), False
        return transient_retries, None, True

    def _append_gate_blocked(self, *, sub_run_id: str, spec_name: str,
                             provider_name, error: str, reason: str,
                             agent_type: str) -> None:
        """追加门禁终态事件 ``gate-blocked``（add-timeline-gate-failure-display D2）。

        调用时机 = 门禁失败**终止当前 attempt 产物文件**的两条分支（结构类原地
        预算耗尽 / 任务完成度类 `[task-gate]`）。写入即追加，故为文件末行——维持
        框架「终态后置」不变量（该文件此后无任何写入者：attempt 终止，重试在新
        sub_run_id 文件继续）。

        ``reason`` 按分支取值（`artifact_gate` / `task_gate`），MUST NOT 一律填
        同一个值——读侧/时间轴据它区分门类。**退避后让位分支 MUST NOT 调用本
        方法**：该分支弃置原因是「spec 已被接管」而非门禁判定，其终态已由
        ``superseded``（带 error）承担；再追加会把「被接管」误标成「门禁拒绝」，
        且同一次失败在时间轴上出现两个失败节点。

        ``provider`` 写 ``provider_name or ""``：provider 为 None（配置缺失/
        链耗尽）时仍可序列化，下游解析不因 null 异常。
        """
        # 留痕写失败不改变门禁终态处置（code-review item 449ab5cb953f：
        # 对齐 _planner_throttle_acquire/_ratelimit_redispatch_on_terminal 口径）
        try:
            append_run_line(
                self.project_root / ".fenix" / "runs" / f"{sub_run_id}.jsonl", {
                    "type": "gate-blocked",
                    "spec": spec_name,
                    "provider": provider_name or "",
                    "reason": reason,
                    "error": error[:_GATE_ERROR_TRUNCATE],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except OSError as e:
            self.logger.warning(
                "agent_runner",
                f"gate-blocked 留痕写入失败（不阻断门禁终态处置）: {e}",
            )
        self.logger.warning(
            "agent_runner",
            f"Artifact gate for '{spec_name}' ({agent_type}) terminal: "
            f"gate-blocked (reason={reason}) for {sub_run_id}",
        )

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

        add-timeline-gate-failure-display D1/D2：本方法在终止当前 attempt 文件的
        两条 do_break 分支（结构类原地预算耗尽 / 任务完成度类）写入 ``gate-blocked``
        终态事件（末行，带截断后的 error 与分支归因 reason），并在原地重试分支的
        ``transient_retry`` / ``superseded`` payload 里带上同一 error 文案；让位
        分支不写 ``gate-blocked``（详见 ``_append_gate_blocked``）。
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
        # add-timeline-gate-failure-display D2：终止本 attempt 文件前追加门禁
        # 终态——reason 按分支取 task_gate（任务完成度门），MUST NOT 写
        # artifact_gate（那是产物结构门的归因，混用会让读侧无法区分门类）。
        if is_task_gate:
            self._append_gate_blocked(
                sub_run_id=sub_run_id, spec_name=spec_name,
                provider_name=provider_name, error=error,
                reason="task_gate", agent_type=agent_type,
            )
            return error, transient_retries, None, False, True
        if transient_retries >= len(transient_budget):
            # 原地预算耗尽 → 退出 while，attempt 层继续重试。
            # add-timeline-gate-failure-display D2：同理追加门禁终态（结构类 →
            # reason=artifact_gate）。缺此步该文件末行仍是 CLI 的 result
            # （is_error:false），classify_run 会把门禁拒绝判成 done（绿点误导）。
            self._append_gate_blocked(
                sub_run_id=sub_run_id, spec_name=spec_name,
                provider_name=provider_name, error=error,
                reason="artifact_gate", agent_type=agent_type,
            )
            return error, transient_retries, None, False, True
        backoff = transient_budget[transient_retries]
        transient_retries += 1
        # add-timeline-gate-failure-display D1：门禁归因随事件落盘
        #（原先只进 daemon log），截断口径见 _GATE_ERROR_TRUNCATE。
        # 留痕写失败不改变重试决策（code-review item 449ab5cb953f：对齐
        # _planner_throttle_acquire/_ratelimit_redispatch_on_terminal 口径）
        try:
            append_run_line(
                self.project_root / ".fenix" / "runs"
                / f"{sub_run_id}.jsonl", {
                    "type": "transient_retry",
                    "spec": spec_name,
                    "provider": provider_name,
                    "backoff_seconds": backoff,
                    "retry_number": transient_retries,
                    "reason": "artifact_gate",
                    "error": error[:_GATE_ERROR_TRUNCATE],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except OSError as e:
            self.logger.warning(
                "agent_runner",
                f"transient_retry 留痕写入失败（不阻断退避重试）: {e}",
            )
        # fix-retry-orphan-active-runs D1：superseded 终态补写
        # ——与 provider 瞬断通道同语义：superseded 紧跟
        # transient_retry = 本文件终态，重试在新 sub_run_id 文件
        # 继续（runner.py:1922 换新注释处交叉引用）。
        # add-timeline-gate-failure-display D1：本文件被弃置后读侧只能从事件取
        # 原因，门禁归因 MUST 一并带上（否则时间轴该节点 reason 为空 =
        # 「无原因绿点」误导）。
        try:
            append_run_line(
                self.project_root / ".fenix" / "runs"
                / f"{sub_run_id}.jsonl", {
                    "type": "superseded",
                    "spec": spec_name,
                    "provider": provider_name,
                    "error": error[:_GATE_ERROR_TRUNCATE],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except OSError as e:
            self.logger.warning(
                "agent_runner",
                f"superseded 留痕写入失败（不阻断退避重试）: {e}",
            )
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
        # add-timeline-gate-failure-display D2：让位分支 MUST NOT 追加
        # gate-blocked —— 弃置原因是「spec 已被接管」而非门禁判定，本文件
        # 终态已由上方 superseded（带 error）承担；再写会把「被接管」误标成
        # 「门禁拒绝」，且同一次失败在时间轴出现两个失败节点。
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
        # evo-add-run-stop-loss 1.2（B）：planner-plan 增查并行出题标记——
        # discarded（产物隔离/转串行收尾伴生写入）即放弃重派：本次事故的
        # 复活正是产物硬门通道（exit 0 但 test_scenarios.json 缺失被拦）。
        # 在途（dispatched）或无标记（未注入/读取失败）不命中，重试照常。
        if self._parallel_plan_marker_discarded(spec_name, agent_type):
            self.logger.warning(
                "agent_runner",
                f"Artifact-gate retry for '{spec_name}' "
                f"({agent_type}) yields: 并行出题标记已 discarded"
                f"（产物已隔离/转串行），放弃重派"
                f"（evo-add-run-stop-loss 1.2）",
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
                    f"{RETRY_YIELDED_ERROR_PREFIX} 并行出题标记已 discarded"
                    f"（产物已隔离/转串行出题），"
                    f"重试让位（evo-add-run-stop-loss 1.2）"),
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
                frozen_terminated=True,
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

    def _git_status_porcelain(self, wt_path: Path) -> list:
        """worktree dirty 取证（git status --porcelain，成功终态收割用）。

        取证失败（git 超时/缺失等 OSError/SubprocessError）fail-open 返回空
        列表：取证环节绝不吞掉已到手的成功终态（与 _worktree_path_valid /
        _check_terminal_no_commit_gate 对同类 git 调用的 fail-open 口径一致）。
        """
        try:
            _st = subprocess.run(
                ["git", "-C", str(wt_path), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if _st.returncode != 0:
            return []
        return [l for l in _st.stdout.splitlines() if l.strip()]

    # ── R7: 成功终态（等价搬移，D1 R7 表）─────────────────────────────
    # 半开探针闭合 / wt_dirty 取证 / worktree 分型 / token 入账。
    # 终态零提交门不在此处（except 作用域之外不可达重试通道），已上移至
    # _execute_agent_inner 的 while 循环 try 体内。
    # 纯终态收割：无跨边界 continue/break（attempt 循环直接 return），可提取。
    def _finalize_success(self, spec_name: str, agent_type: str, run_id: str,
                          attempt_run_id: str, attempt: int, start_time: float,
                          turns: int, usage_info: dict, provider_name, model,
                          wt_path: Path, output: str, sub_run_id: str,
                          branch, handed_off: set) -> AgentRunResult:
        """成功终态收割（等价搬移，D1 R7）。

        半开探针闭合 → wt_dirty 取证 → worktree 分型清理 → token 入账 →
        结构化指标 → 返回 success 结果。
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
            wt_dirty = self._git_status_porcelain(wt_path)
        elif agent_type == "repair":
            # repair 现场取证：冲突解决是否已 commit（dispatch 层据此
            # 判断 re-merge-back 前的现场状态，add-merge-back-repair-lane）。
            wt_dirty = self._git_status_porcelain(wt_path)
        # add-impl-terminal-nocommit-gate（D2）：终态零提交门已上移至
        # _execute_agent_inner 的 while 循环 try 体内（成功 break 之前、拷回
        # 与产物硬门之后）——本方法由 break 之后的 return 调用，位于
        # except AgentArtifactGateError 作用域之外，在此抛错会裸抛穿调度层、
        # [terminal-no-commit] 重试通道不可达。此处 wt_dirty 取证保留，供
        # worktree 分型处置与 worktree_dirty 结果上报。
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
                               frozen_terminated_flag: bool = False,
                               stall_budget_flag: bool = False,
                               st: _AttemptState = None, handed_off: set = None) -> bool:
        """失败终态分型（等价搬移，D1 R8）：重试等待 or 终态 keep。

        返回 True 表示 should_break（cancelled_flag or shutdown_interrupted or
        stall_budget_flag 触发的终态——attempt 循环 MUST break）；返回 False
        表示已 sleep(10) 等待重试，调用者继续下一轮 attempt。
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
        # add-freeze-stop-inflight-agents（D2/task 1.6）：冻结终止
        # （frozen_terminated_flag）MUST 同样 break——不进入下一 attempt、不
        # sleep(10) 重试；worktree 按 shutdown_interrupted 同款「保留现场」处理
        #（implementer 亦保留：既有 else 分支的 cleanup(success=False) 会删除
        # implementer 的 worktree 目录，使 WIP 保全与解冻后续做双双落空）。
        if attempt < max_retries and not cancelled_flag \
                and not shutdown_interrupted and not frozen_terminated_flag \
                and not stall_budget_flag:
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
        elif frozen_terminated_flag:
            # add-freeze-stop-inflight-agents task 1.6：冻结终止「保留现场」——
            # WIP 保全（锚点 freeze-hold）已在轮询环内完成，worktree 目录与
            # 分支必须原样保留供解冻后续做（_frozen_hold + _recovery_resume
            # 依据 branch/implementer_run 锚点）。含 implementer 在内的全部
            # agent_type 均走此分支，MUST NOT 落入 cleanup(success=False)。
            # 登记为在册 worktree（keep_for_reuse 路径形态即目录保留），使
            # stale_sweep 的 _branch_protected_by_state 扩展判据（frozen +
            # _frozen_hold → branch 受保护）能够兜底跨 daemon 重启。
            st.kept_wt_path = st.wt_path
            handed_off.add(st.wt_path)
            try:
                if st.wt_path is not None:
                    self.worktree_manager.keep_for_reuse(
                        spec_name, st.wt_path, agent_type=agent_type)
            except Exception as e:
                # keep_for_reuse 失败不阻断冻结终止收口（目录已保留，
                # 登记仅影响跨 daemon 重启的回收保护）
                self.logger.debug(
                    "agent_runner",
                    f"freeze-terminated keep_for_reuse failed for "
                    f"'{spec_name}': {e}",
                )
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
        # evo-add-run-stop-loss 2.1：停滞判停与取消/停机/冻结同列 should_break
        #（终止整个重试链）；worktree 走下方默认 else cleanup 分支——非冻结的
        # 保留现场语义不适用（判停 run 的现场由 WIP 保全锚点在强杀前收走）。
        return (cancelled_flag or shutdown_interrupted
                or frozen_terminated_flag or stall_budget_flag)

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
        # 上界守卫：chain 每 attempt 现读配置重建，运行中配置热更新缩短候选链时，
        # 遗留 cursor 可能 >= len(chain)，此时重选落点而非以未捕获 IndexError 崩溃；
        # 重选仍为 -1 则落入下方 chain_exhausted/circuit 分支。
        if st.chain_cursor < 0 or st.chain_cursor >= len(chain):
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
                          frozen_terminated_flag: bool = False,
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
        if frozen_terminated_flag:
            # add-freeze-stop-inflight-agents D1/D3：冻结终止独立收口——与取消
            # 同列（不重试、不重派由 dispatch 侧保证）但走独立 frozen_terminated
            # 结果字段（dispatch 写 _frozen_hold 而非 _cancelled_hold）。
            self._log_run_metrics(
                run_id=run_id, spec_name=spec_name, agent_type=agent_type,
                duration_seconds=duration, turns=turns, usage_info=usage_info,
                terminal="frozen", provider=provider_name, model=model,
            )
            return AgentRunResult(
                run_id, spec_name, agent_type,
                success=False, duration_seconds=duration,
                error=error,
                frozen_terminated=True,
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
        - JSON 无法解析或非 UTF-8 字节时维持原始字节拷回（不注入，避免破坏
          字节；非 UTF-8 读取降级不外抛，拷回环节绝不改变 run 终态）。
        - OSError 静默（与既有行为一致）；目录不存在零动作。
        - 主树共享文件是跨 agent 共享单例，多 run 并发收工时拷回交错会写坏
          JSON，故写盘走 temp 文件 + os.replace 原子替换（同
          _ensure_agent_config_dir 的 _write_atomic 手法）。
        """
        wt_result = wt_path / ".fenix-run-result.json"
        root_result = self.project_root / ".fenix" / ".fenix-run-result.json"

        def _write_atomic(dest: Path, data: str | bytes) -> None:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".fenix-run-result.", suffix=".tmp",
                dir=str(dest.parent),
            )
            tmp_path = Path(tmp_name)
            try:
                # 二进制落盘（str 先按 utf-8 编码）：原始字节拷回路径不因文本
                # 模式编解码抛 UnicodeEncodeError、不改变字节。
                if isinstance(data, str):
                    data = data.encode("utf-8")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(tmp_path, dest)
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

        if wt_result.exists():
            try:
                raw_bytes = wt_result.read_bytes()
                try:
                    raw: str | None = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    raw = None  # 非 UTF-8 字节：跳过注入，降级原始字节拷回
                role = AGENT_TYPE_TO_ROLE.get(agent_type)
                if role is not None and raw is not None:
                    try:
                        payload = json.loads(raw)
                        if isinstance(payload, dict):
                            payload["role"] = role
                            payload["spec"] = spec_name
                            _write_atomic(
                                root_result,
                                json.dumps(
                                    payload, ensure_ascii=False, indent=2),
                            )
                            raw_bytes = None  # 已注入写盘，跳过原始拷回
                    except (json.JSONDecodeError, ValueError):
                        pass  # 非法 JSON：fall through 原始字节拷回
                if raw_bytes is not None:
                    _write_atomic(root_result, raw_bytes)
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

        Returns: (output, turns_used, session_id, usage_info)。usage_info 为终态
            result 事件提取的 usage/成本（add-cost-observability D1，经
            _extract_usage_info）；强杀等无 result 终态事件的路径四数值键全 0 且置
            unobserved=True（观测兜底而非确认为零，语义见 _extract_usage_info）。
            失败/异常路径直接抛 RuntimeError，不返回。
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
            "--permission-mode", "bypassPermissions",
        ]
        # --add-dir 车道化注入（fix-impl-code-review-writepath D2）：主树
        # verify-progress 只授给确有该落点的车道（verifier/planner/fast-track/
        # dispute-judge/administrator，见 _NO_MAIN_TREE_VERIFY_PROGRESS_LANES 注释）。
        # implementer/repair/spec-review 的该产物在 worktree 内，主树该目录不是其
        # 工作区——保留注入会把「verify-progress 是主树共享目录」的语义错误外溢到
        # 这些车道（后果：实现者据"授权"写主树，门读 worktree 恒判缺失）。缺省
        # （agent_type is None 或表外值）保持注入——maintenance/admin/dashboard
        # 会话等既有调用点零行为变化。
        if agent_type not in _NO_MAIN_TREE_VERIFY_PROGRESS_LANES:
            cmd += ["--add-dir", str(progress_dir)]
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

        # ── evo-add-run-stop-loss 2.1：base_run_id 前移 ─────────────────
        # 归一化键（含 epoch）在子线程启动前就绪：读线程的停滞预算采样旁挂
        # 与轮询环判停共用（原赋值点在 t_out.start() 之后，读线程先启动即
        # 存在 UnboundLocalError 竞态，故整体前移到线程定义之前）。
        base_run_id = self._normalize_run_id(run_id)
        # 停滞预算配置一次读取（run 内静态；缺省关闭 → None，轮询环零开销
        # 短路）。关闭态同样不建态、不采样（record_sample 首次调用才建）。
        stall_cfg = self._stall_budget_config()

        # ── run 级 API 延迟统计（add-planner-efficiency：run-latency-observability）──
        # 纯读侧采集：`tool_result → 下一个 assistant` 间隔样本（API 往返等待）。
        # sample_state 被 _read_stream 子线程 append，主线程在 join 后读取，
        # 同线程追加+join 后读取无竞态（类 turn_count 同模式）。
        latency_state: dict = {"last_tool_result_ts": None, "samples": []}

        # ── fix-agent-lane-efficiency D3：run 级上下文经济性指标（纯读侧旁路）──
        # 累计 input_tokens / cache_read_input_tokens / context_peak_estimate，
        # run 终结时落盘到 transcript + 日志（_log_run_metrics），超阈值打 WARNING。
        # 转录事件来源：assistant 事件的 message.usage；不用 CLI result.modelUsage（D3
        # 记账段已证实 modelUsage 与 result.usage 矛盾）。指标来源以本 run 转录事件
        # 为准，MUST NOT 取 CLI result.modelUsage。
        context_metrics: dict = {
            "total_input_tokens": 0,
            "total_cache_read_tokens": 0,
            "context_peak_tokens": 0,
            "peak_input_so_far": 0,
        }

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
                            # fix-agent-lane-efficiency D3：逐轮累计 usage
                            # 指标（纯读侧旁路）。来源：assistant 事件的
                            # message.usage（与转录同源），不用 CLI
                            # result.modelUsage（D3 记账段证实矛盾）。
                            _msg = entry.get("message") or {}
                            _usage = _msg.get("usage") or {}
                            # usage 字段级防御（code-review item 3a3c7edfa67b）：
                            # 畸形值（非数值字符串/嵌套 dict）令 int() 抛
                            # ValueError/TypeError 会命中外层 except 终止整个读
                            # 线程——此后该 run 全部 stdout 事件（含 result 终态）
                            # 不再落盘，且 stdout 管道无人排水。单事件按 0 计 +
                            # DEBUG 留痕，与逐行 JSONDecodeError 防护同粒度。
                            try:
                                _inp = int(_usage.get("input_tokens") or 0)
                                _cr = int(
                                    _usage.get("cache_read_input_tokens") or 0
                                )
                            except (TypeError, ValueError):
                                _inp = _cr = 0
                                self.logger.debug(
                                    "agent_runner",
                                    f"malformed usage fields, metrics"
                                    f" skipped: {_usage!r}",
                                    {
                                        "run_id": run_id,
                                        "event": "usage_field_malformed",
                                    },
                                )
                            context_metrics["total_input_tokens"] += _inp
                            context_metrics["total_cache_read_tokens"] += _cr
                            if _inp > context_metrics["peak_input_so_far"]:
                                context_metrics["peak_input_so_far"] = _inp
                            context_metrics["context_peak_tokens"] = (
                                context_metrics["peak_input_so_far"]
                            )
                        if entry.get("type") == "result":
                            # 记录最后一个 result 事件（含 num_turns / result 文本 / session_id）；
                            # 落盘推迟到读线程 join 后，保证 result 终态是文件最后一行
                            # （并发 stderr 噪声不会落在其后，Dashboard 状态分类不受干扰）
                            last_result.clear()
                            last_result.update(entry)
                            continue
                        # fix-agent-lane-efficiency D1：子代理启动失败可见化。
                        # 子代理（Explore/general-purpose/Plan）以 model_not_found /
                        # 认证失败 / 启动期错误终止时，claude CLI 在流中落
                        # task_notification 事件（summary 含子代理类型与错误类别）。
                        # 纯读侧捕获：落显式 WARNING（含 run_id、子代理类型、错误
                        # 原文摘要），MUST NOT 改变本 run 终态判定、MUST NOT 改变
                        # 事件处理时序（与 D3 指标同模式——只读日志旁路）。
                        if entry.get("type") == "task_notification":
                            _tsum = str(entry.get("summary") or "")
                            if _tsum and any(
                                _sig in _tsum
                                for _sig in (
                                    "model_not_found",
                                    "HTTP 404",
                                    "authentication",
                                    "auth_error",
                                    "startup",
                                    "启动",
                                    "not exist",
                                    "may not have access",
                                )
                            ):
                                self.logger.warning(
                                    "agent_runner",
                                    f"subagent startup failure detected: {_tsum[:400]}",
                                    {
                                        "run_id": run_id,
                                        "event": "subagent_startup_failure",
                                        "summary": _tsum[:400],
                                    },
                                )
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
                                _sb_sample = (
                                    e_ts - latency_state["last_tool_result_ts"])
                                latency_state["samples"].append(_sb_sample)
                                latency_state["last_tool_result_ts"] = None
                                # evo-add-run-stop-loss 2.1：停滞预算样本旁挂
                                # 采集（run 级累积、不随 attempt 重置；reader
                                # 单写者，内部异常仅 WARNING 不阻断读流）。
                                self._stall_budget_record_sample(
                                    base_run_id, _sb_sample)
                    append_run_line(run_file, entry)
            except Exception as e:
                # 读取线程异常不应导致主流程崩溃；半成品产物仍可被 Dashboard 读取。
                # 但不零痕迹（code-review item 2fffcc8e3be1）：与模块内「失败记
                # warning 不阻断」惯例一致，留一条含 run_id 的可审计日志，避免
                # 排查时只能靠 run 文件提前停止增长反推夭折原因。
                self.logger.warning(
                    "agent_runner",
                    f"read stream thread aborted: {e!r}",
                    {
                        "run_id": run_id,
                        "is_stderr": is_stderr,
                        "event": "read_stream_thread_error",
                    },
                )

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
        #（base_run_id 已前移到读线程启动前，见上）
        cancel_error: RunCancelledError | None = None
        # add-freeze-stop-inflight-agents D1：冻结终止独立异常（与取消并列、
        # 不复用取消语义）。轮询环命中 spec frozen 时置位，finally 段并列
        # cancel_error 落 frozen-terminated 终态行后抛出。
        frozen_error: FrozenTerminatedError | None = None
        # evo-add-run-stop-loss 2.1：停滞判停独立异常（与取消/冻结并列）。
        # 轮询环复合判据命中时置位，finally 段并列落 stall-budget-terminated
        # 终态行后抛出；attempt 循环侧据此置 stall_budget_flag 终止整个重试链。
        stall_error: RunStallBudgetExceededError | None = None
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
                # ── 冻结检查（add-freeze-stop-inflight-agents D1）──
                # 放在取消旗标检查之前：冻结是 spec 级、取消是 run 级，
                # spec 级优先级更高。轮询环每 1 秒直接读 STATE 结构化 frozen
                # 字段（_spec_is_frozen fail-open：读取异常不终止）。
                # 顺序上先于 poll()：run 恰在冻结瞬间完成时，poll() 已观察到
                # rc 非 None 走自然收工（上一轮），不误判为冻结终止。
                if self._spec_is_frozen(spec_name):
                    self.logger.info(
                        "agent_runner",
                        f"spec '{spec_name}' frozen — 终止在飞 agent 子进程"
                        f"（attempt {run_id}，base {base_run_id}）",
                    )
                    # 终止前 WIP 保全（锚点 freeze-hold）：子进程仍活着时提交
                    # 未落盘现场——冻结终止即停，不再有下一 attempt 的退避窗口
                    # 保全机会；无 worktree 载体/失败仅 WARNING 不阻断。
                    self._wip_checkpoint_on_forced_kill(
                        spec_name, cwd, anchor=ANCHOR_FREEZE_HOLD)
                    proc.terminate()
                    try:
                        proc.wait(timeout=AGENT_TERMINATE_GRACE_SECONDS)
                    except subprocess.TimeoutExpired:
                        self.logger.warning(
                            "agent_runner",
                            f"run '{base_run_id}' frozen grace 窗口内未退出，SIGKILL",
                        )
                        proc.kill()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                    returncode = -15  # SIGTERM 对应语义
                    frozen_error = FrozenTerminatedError(
                        reason=f"spec '{spec_name}' frozen", by="admin")
                    # 冻结命中清理残留 cancel 旗标（spec 级 > run 级）：防止
                    # 解冻后续做时被残留旗标立即再终止。
                    self._cancel_clear(base_run_id)
                    break

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

                # ── run 停滞预算复合判停（evo-add-run-stop-loss 2.1）─────
                # 缺省关闭（stall_cfg=None 零开销短路）。启用后每轮评估：
                # 判据一连续 N 次 ≥120s 往返（reader 旁挂采样累积）/ 判据二
                # stall 占比 ≥1/2 且超过 M 分钟无产物（run 转录）mtime 进展。
                # 统计 run 级累积（键=base_run_id，不随 attempt 重置）；命中
                # 强杀在飞 attempt 并置独立异常——终止整个重试链（不再触发
                # 瞬态重试或 in-place retry 重派），不新增 admin 告警。
                if stall_cfg is not None:
                    _sb = self._stall_budget_state_for(base_run_id)
                    try:
                        _sb_mtime = os.path.getmtime(run_file)
                    except OSError:
                        _sb_mtime = None
                    if _sb_mtime is not None and _sb_mtime > _sb["last_mtime"]:
                        # 产物进展（转录文件增长）：推进无进展窗锚点
                        _sb["last_mtime"] = _sb_mtime
                        _sb["last_progress_ts"] = time.time()
                    _sb_criterion = self._stall_budget_hit_criterion(
                        _sb, stall_cfg, now=time.time())
                    if _sb_criterion:
                        _sb_stats = (
                            f"samples_total={_sb['samples_total']}, "
                            f"stalls_total={_sb['stalls_total']}, "
                            f"consecutive_stalls={_sb['consecutive_stalls']}, "
                            f"no_progress_seconds="
                            f"{int(time.time() - _sb['last_progress_ts'])}")
                        self.logger.warning(
                            "agent_runner",
                            f"run '{base_run_id}' 命中停滞预算判据 "
                            f"{_sb_criterion}，强杀在飞 attempt {run_id}"
                            f"并终止重试链（{_sb_stats}）",
                            {
                                "run_id": run_id,
                                "event": "run_stall_budget_hit",
                                "criterion": _sb_criterion,
                            },
                        )
                        # 强杀收口前的 WIP 保全（对齐超时/turn-limit 锚点）：
                        # 失败降级不阻断判停收口。
                        self._wip_checkpoint_on_forced_kill(spec_name, cwd)
                        proc.kill()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                        returncode = -9  # SIGKILL 对应语义
                        stall_error = RunStallBudgetExceededError(
                            criterion=_sb_criterion, detail=_sb_stats)
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
            # code-review item 183ded7b526a：pop 持 _run_finalize_lock，与
            # wait_for_running_agents 停机写 interrupted 标记的「成员复核 +
            # 末行复核 + 追加」临界区互斥（其后同线程的 result 等终态落盘
            # 严格后序于本 pop，锁排他即保证标记不会插到 result 之后成为
            # 文件末行、把成功 run 判成 interrupted）。
            with self._run_finalize_lock:
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
            # ── fix-agent-lane-efficiency D3：上下文经济性指标落盘 ──
            # 纯读侧统计（assistant 事件的 message.usage 累计），写入 transcript
            # 的 run_metrics 行（终态行之前追加：result/cancelled/frozen-terminated
            # 终态行在本块之后才落盘，保证文件末行恒为终态——classify_run 读末行
            # 判状态；MUST NOT 把本块调到终态行之后）+ 日志；超阈值
            # 打 WARNING（不阻断 run、不触发独立人工告警）。最小样本门槛：turns
            # < 5 或 usage 缺失/零轮空跑只落指标不打告警（零轮空跑噪声抑制）。
            try:
                _turns = turn_count[0]
                _inp = context_metrics["total_input_tokens"]
                _cr = context_metrics["total_cache_read_tokens"]
                _peak = context_metrics["context_peak_tokens"]
                _per_turn = (_inp // _turns) if _turns > 0 else 0
                # 指标行落盘（先于终态行，type 为 run_metrics）
                append_run_line(run_file, {
                    "type": "run_metrics",
                    "run_id": run_id,
                    "turns": _turns,
                    "input_tokens": _inp,
                    "cache_read_input_tokens": _cr,
                    "context_peak_tokens": _peak,
                    "per_turn_input_tokens": _per_turn,
                })
                # 日志侧也落一份（与既有的 _log_run_metrics 同源，
                # dashboard 读侧按 metric_type==run_metrics 增量索引）
                self.logger.info(
                    "agent_runner",
                    f"context metrics: turns={_turns} inp={_inp} "
                    f"peak={_peak} per_turn={_per_turn} cr={_cr}",
                    {
                        "metric_type": "run_metrics",
                        "run_id": run_id,
                        "turns": _turns,
                        "input_tokens": _inp,
                        "cache_read_input_tokens": _cr,
                        "context_peak_tokens": _peak,
                        "per_turn_input_tokens": _per_turn,
                    },
                )
                # 超阈值诊断 WARNING（告警降噪：turns < 5 空跑跳过）
                if _turns >= 5 and _per_turn > 0:
                    from core.config import ConfigLoader as _CLT
                    _threshold = _CLT.get(
                        self.config, "verify.context_cost_per_turn_threshold",
                        200000,
                    )
                    if isinstance(_threshold, (int, float)) and _per_turn > _threshold:
                        self.logger.warning(
                            "agent_runner",
                            f"context cost per turn={_per_turn} exceeds "
                            f"threshold={_threshold} for run '{run_id}' "
                            f"—— O(N²) context structure detected",
                            {
                                "run_id": run_id,
                                "per_turn_input_tokens": _per_turn,
                                "threshold": _threshold,
                                "turns": _turns,
                            },
                        )
            except Exception as e:
                self.logger.debug(
                    "agent_runner",
                    f"context metrics落盘失败（不阻断 run 终态）: {e}",
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
            # add-freeze-stop-inflight-agents D1：frozen-terminated 终态行与
            # cancelled 行同位置（finally 内、join 之后、result 行后）——保证
            # 为文件末行级终态（run_metrics 行在终态行之前追加是既有常态、
            # 不属于终态事件，不影响 classify_run 的末行判定；MUST NOT 把
            # run_metrics 调到终态行之后，否则文件末行不再是终态）。
            if frozen_error is not None:
                append_run_line(run_file, {
                    "type": "frozen-terminated",
                    "reason": frozen_error.reason,
                    "by": frozen_error.by,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            # evo-add-run-stop-loss 2.1：stall-budget-terminated 终态行与
            # cancelled / frozen-terminated 同位置（join 后、result 行后），
            # 保证为文件末行级终态；命中判据与统计快照入行可审计（判停
            # 不新增 admin 告警，run 转录即唯一落点）。
            if stall_error is not None:
                append_run_line(run_file, {
                    "type": "stall-budget-terminated",
                    "criterion": stall_error.criterion,
                    "detail": stall_error.detail,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            # 产物文件可能因崩溃等遗留为"活动但不再增长"，清理时按时间淘汰即可

        if cancel_error is not None:
            raise cancel_error

        if frozen_error is not None:
            # add-freeze-stop-inflight-agents D1：冻结终止独立异常通道——
            # 不重试、不计秒挂、不触发 provider 切换（与 RunCancelledError
            # 并列的收口语义），dispatch 侧据此写 _frozen_hold 而非
            # _cancelled_hold。
            raise frozen_error

        if stall_error is not None:
            # evo-add-run-stop-loss 2.1：停滞判停独立异常通道——不重试、不计
            # 秒挂、不触发 provider 切换、不触发 in-place retry 重派（与
            # RunCancelledError / FrozenTerminatedError 并列的收口语义），
            # attempt 循环侧据此置 stall_budget_flag 终止整个重试链。
            raise stall_error

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
        # bool 是 int 子类，显式排除以免 True/False 直通成 epoch 1.0/0.0 秒
        # 假样本（与 latency._default_ts_parser 逐字段一致，契约测试样本
        # 已含 bool 用例锁定该等价性）。
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw)
        try:
            text = str(raw)
            # 仅剥离结尾一个 "Z"（ISO 8601 UTC 标记；replace 全量替换会误伤
            # 串中其他 "Z" 字符）；naive（无时区）值显式按 UTC 取 epoch，
            # 避免 .timestamp() 按进程本地时区解释、TZ 环境不同算出整体偏移。
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
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

    # ── 并行出题标记让位判据（evo-add-run-stop-loss 1.2）──────────────────

    def _parallel_plan_marker_discarded(self, spec_name: str,
                                        agent_type: str) -> bool:
        """in-place retry 重派前的让位判据（B）：planner-plan 增查并行出题标记。

        标记由 pm_engine 并行出题车道全程落盘（.fenix/verify-progress/<spec>/
        parallel_plan.json，实际枚举 dispatched/failed/discarded/completed）；
        消费侧的产物隔离（_quarantine_parallel_product → .parallel-discarded）
        与转串行收尾伴生写入 discarded——单值即覆盖「已隔离」与「已转串行」
        两类终态。命中即放弃重派：重派只会与已转道的串行出题竞跑（2026-09-25
        planner-plan 事故 -r1 复活 36 分钟形态）。

        仅 planner-plan 参与；读取回调由装配侧注入（_parallel_plan_marker_reader，
        PMEngine.__init__ 沿 result_gate 注入约定回引字段先例），本类 MUST NOT
        依赖 pm_engine 模块。未注入（缺省 None）/ 读取异常 / 标记缺失一律按
        无标记处理（fail-open，不阻断正常重试）。
        """
        if agent_type != "planner-plan":
            return False
        reader = getattr(self, "_parallel_plan_marker_reader", None)
        if reader is None:
            return False
        try:
            marker = reader(spec_name) or {}
        except Exception as e:  # noqa: BLE001 — 读取失败按无标记处理
            self.logger.warning(
                "agent_runner",
                f"并行出题标记读取失败（按无标记处理，不阻断重试）"
                f"'{spec_name}': {e}",
            )
            return False
        return (marker if isinstance(marker, dict) else {}).get("status") \
            == "discarded"

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

    # ── run 停滞预算复合判停（evo-add-run-stop-loss 2.1，缺省关闭）──────
    # 判停统计与评估：reader 线程旁挂采样（单写者）+ 轮询环 mtime 进展
    # 跟踪（单写者）+ 纯函数判据评估。状态键为归一化 base_run_id（含
    # epoch），随 run 生命周期累积、不随 attempt 重置；终态外口幂等摘除。

    def _stall_budget_config(self):
        """读取停滞预算配置；缺省关闭（或读取失败）返回 None。

        单点经 ConfigLoader.get_run_stall_budget_config（2.2 归一化，消费与
        展示同源）；读取异常 fail-open 为关闭——配置读失败不构成杀 run 的
        理由（与 _spec_is_frozen fail-open 同惯例）。
        """
        try:
            from core.config import ConfigLoader as _CLSbCfg
            cfg = _CLSbCfg.get_run_stall_budget_config(self.config)
        except Exception:
            return None
        if not cfg or not cfg.get("enabled"):
            return None
        return cfg

    def _stall_budget_state_for(self, base_run_id: str) -> dict:
        """取/建 run 级判停状态（键=归一化 base_run_id，含 epoch）。

        建态时顺带淘汰 created_ts 超 24h 的陈旧条目：兜底非派发链路
        （_run_claude 被直调、不经 _execute_agent 终态外口 forget）的状态
        泄漏（对齐 _cancel_requested 无需清理的键含 epoch 语义 + 卫生性
        淘汰）。
        """
        states = self._stall_budget_states
        key = self._normalize_run_id(base_run_id)
        st = states.get(key)
        if st is None:
            now = time.time()
            for k in [k for k, v in states.items()
                      if now - float(v.get("created_ts") or now) > 86400.0]:
                states.pop(k, None)
            st = {
                "created_ts": now,
                # reader 线程单写者维护的往返样本计数
                "samples_total": 0,
                "stalls_total": 0,
                "consecutive_stalls": 0,
                # 轮询环单写者维护的产物（run 转录）mtime 进展锚点
                "last_mtime": 0.0,
                "last_progress_ts": now,
            }
            states[key] = st
        return st

    def _stall_budget_forget(self, run_id: str) -> None:
        """run 终态外口摘除判停状态（_execute_agent finally 幂等清理）。"""
        try:
            self._stall_budget_states.pop(self._normalize_run_id(run_id), None)
        except Exception:
            pass

    def _stall_budget_record_sample(self, base_run_id: str,
                                    sample_seconds) -> None:
        """reader 线程单写者：累积 run 级 stall 样本计数（纯读侧旁路）。

        ≥RUN_STALL_ROUND_SECONDS 的往返计入 stalls_total 并推进连续计数；
        健康往返清零连续计数（判据一的「连续」语义）。MUST NOT 影响读线程
        事件处理时序——内部异常仅 WARNING 不上抛。
        """
        try:
            st = self._stall_budget_state_for(base_run_id)
            st["samples_total"] += 1
            if (sample_seconds is not None
                    and float(sample_seconds) >= RUN_STALL_ROUND_SECONDS):
                st["stalls_total"] += 1
                st["consecutive_stalls"] += 1
            else:
                st["consecutive_stalls"] = 0
        except Exception as e:
            self.logger.warning(
                "agent_runner",
                f"stall budget sample record failed（不阻断）: {e}",
                {"run_id": base_run_id, "event": "run_stall_budget_sample_error"},
            )

    @staticmethod
    def _stall_budget_hit_criterion(st: dict, cfg: dict,
                                    now: float = None) -> str:
        """纯函数评估复合判停判据（evo-add-run-stop-loss 2.1）。

        - 判据一 consecutive_slow_rounds：run 内连续 ≥stalls 次达到
          RUN_STALL_ROUND_SECONDS 的 API 往返；
        - 判据二 stall_ratio_no_progress：完成样本 ≥RUN_STALL_RATIO_MIN_SAMPLES
          且 stall 占比 ≥RUN_STALL_RATIO_TRIGGER，且超过 window_seconds 无产物
          mtime 进展（mtime 锚点由轮询环调用侧更新，本函数只读）。

        命中返回判据名，未命中返回空串。now 参数供测试注入时钟。
        """
        if now is None:
            now = time.time()
        stalls = max(1, int(cfg.get("stalls") or 1))
        window_seconds = float(cfg.get("window_seconds") or 600.0)
        if int(st.get("consecutive_stalls") or 0) >= stalls:
            return "consecutive_slow_rounds"
        total = int(st.get("samples_total") or 0)
        if (total >= RUN_STALL_RATIO_MIN_SAMPLES
                and total > 0
                and (int(st.get("stalls_total") or 0) / total)
                >= RUN_STALL_RATIO_TRIGGER
                and now - float(st.get("last_progress_ts") or now) > window_seconds):
            return "stall_ratio_no_progress"
        return ""

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
        # `Timeout after …` / `Max turns …`，见 _run_claude 内
        # timeout_error / turn_limit_error 赋值处收口）。
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

    # ── per-run 终态回调表（add-mergeback-wip-active-coordination D2）──────
    # 现状无通用 per-run 订阅 API（core/event_bus.py 是 STATE.md 文件监视器，
    # 非 pub-sub；_lane_registry 的 done_event 明示车道键非 run_id、不含实现
    # 车道）——本表为新增：挂在 _execute_agent 终态收口处（实现/code-fix run
    # 落终态都经此），做 base_run_id → {subscriber → callback}。defer 批合回
    # 消费者据此注册持有者 run 监听，终态到达即触发事件驱动重试（替代固定
    # 长间隔轮询作为主要唤醒手段；轮询降级为兜底）。

    def _run_terminal_callback_table(self) -> dict:
        """终态回调表（base_run_id → {subscriber → callback}）。

        生产路径 ``__init__`` 已建态；惰性回退仅对齐 _lane_registry 先例，让
        测试以 ``AgentRunner.__new__`` 绕过 ``__init__`` 的实例同样安全。
        """
        tbl = self.__dict__.get("_run_terminal_callbacks")
        if tbl is None:
            tbl = {}
            self.__dict__["_run_terminal_callbacks"] = tbl
        return tbl

    def register_run_terminal_callback(self, run_id: str, callback,
                                       subscriber: str = "default") -> None:
        """注册 per-run 终态回调（D2）：该 run 落终态即触发 callback。

        注册时先查该 run 是否已终态（run 文件终态行，复用
        ``liveness._file_has_terminal_event`` 同口径；且不在在飞进程表），
        是则立即触发——不依赖后续事件，防「终态后才注册」的监听泄漏（设计
        Risks 第 3 条）。注册与立即触发双轨：即便「已终态」判定漏判（旧
        attempt 文件残留终态行等），真正的终态收口仍会触发本回调——回调
        消费方幂等（重复触发 = 一次空转重试），漏触发才不可接受。

        Args:
            run_id: run id（任意 attempt 形态，内部按 base_run_id 归一化）。
            callback: 无参可调用对象；在终态收口线程/注册线程**同步执行**，
                消费方 MUST 自兜异常且快速返回（fire 侧有 try/except 兜底，
                单回调异常不阻断其余回调与 run 收尾）。
            subscriber: 订阅方键（同 run 同订阅方重复注册覆盖，不累积）。
        """
        base = self._normalize_run_id(str(run_id or ""))
        if not base:
            return
        subs = self._run_terminal_callback_table().setdefault(base, {})
        subs[str(subscriber or "default")] = callback
        if not self._run_id_in_flight(base) and self._run_files_terminal(base):
            self._fire_run_terminal_callbacks(base)

    def _run_id_in_flight(self, base_run_id: str) -> bool:
        """base_run_id 的任一 attempt 是否仍在在飞进程表（注册表键为 attempt id）。"""
        running = getattr(self, "_running_agents", None) or {}
        return any(
            rid == base_run_id or str(rid).startswith(base_run_id + "-")
            for rid in list(running.keys())
        )

    def _run_files_terminal(self, base_run_id: str) -> bool:
        """该 base run 的任一 run 文件已出现终态事件（_file_has_terminal_event 同口径）。

        匹配 ``<base>.jsonl`` 与 ``<base>-*.jsonl``（attempt/瞬态重试文件）；
        带 ``-`` 边界防止 base id 前缀撞上其他 run（``impl-x-123`` 不得命中
        ``impl-x-1234-a1.jsonl``）。
        """
        runs_dir = self.project_root / ".fenix" / "runs"
        try:
            files: list = []
            for pat in (f"{base_run_id}.jsonl", f"{base_run_id}-*.jsonl"):
                files.extend(runs_dir.glob(pat))
        except OSError:
            return False
        return any(_file_has_terminal_event(f) for f in files)

    def _fire_run_terminal_callbacks(self, run_id: str) -> None:
        """触发并消费该 run 的全部终态回调（整键 pop，单键原子）。

        供 ``_execute_agent`` 终态收口调用；单回调异常 warning 兜底，不阻断
        其余回调与 run 收尾。
        """
        base = self._normalize_run_id(str(run_id or ""))
        if not base:
            return
        subs = self._run_terminal_callback_table().pop(base, None)
        if not subs:
            return
        for name, cb in list(subs.items()):
            try:
                cb()
            except Exception as e:  # noqa: BLE001 — 单回调异常不阻断收尾
                self.logger.warning(
                    "agent_runner",
                    f"run 终态回调执行异常（run={base}, subscriber={name}）: {e}",
                )

    # ── 车道级在飞登记（planned-restart-drain B/D2）───────────────────────
    # 非 agent_runner 派生的车道进程（run_impl_ocr 的 ocr 子进程等）不在
    # _running_agents 注册表——排水集合对其是盲区，重启即丢工作且载体被当
    # 无主回收。登记制（design D2）：车道以 Popen 句柄自觉注册，execvp 改名
    # 天然覆盖（同 PID）；刻意独立于 _running_agents——车道键不是 run_id，
    # 混入会令 checkpoint 广播 / interrupted 标记 / run 保全误作用在车道上。

    def _lane_registry(self) -> dict:
        """车道登记表（key → (Popen, done_event|None)）。

        生产路径 ``__init__`` 已建态，不会触达下方建态分支；惰性回退仅对齐
        _cancel_requested 先例，让测试以 ``AgentRunner.__new__`` 绕过
        ``__init__`` 的实例同样安全（该场景单线程，无并发建态竞态）。
        """
        reg = self.__dict__.get("_lane_processes")
        if reg is None:
            reg = {}
            self.__dict__["_lane_processes"] = reg
        return reg

    def register_lane_process(self, key: str, proc, done_event=None) -> None:
        """车道进程在飞登记：进入排水集合，规划性重启排水等待其收尾。

        Args:
            key: 车道实例键（如 ocr 车道 run_id）；同键重复登记以后者覆盖。
            proc: ``subprocess.Popen`` 句柄（存活判定 poll() is None）。
            done_event: 可选 ``threading.Event``，车道线程落终态后 set——
                shutdown 收口据此 bounded 等待车道收尾，避免进程先于终态退出。
        """
        self._lane_registry()[key] = (proc, done_event)
        self.logger.info(
            "agent_runner",
            f"lane process registered: {key} (pid={getattr(proc, 'pid', '?')})",
        )

    def unregister_lane_process(self, key: str) -> None:
        """车道进程注销（收尾/异常路径均须调用；幂等）。"""
        self._lane_registry().pop(key, None)

    def running_lane_ids(self) -> list:
        """当前在飞车道键列表（poll() 为 None = 存活）——排水集合车道段。"""
        return [
            key for key, (proc, _ev) in list(self._lane_registry().items())
            if proc.poll() is None
        ]

    def terminate_lane_processes(
        self, grace: float = AGENT_TERMINATE_GRACE_SECONDS
    ) -> list:
        """登记车道进程的有序终止收口：SIGTERM → grace 宽限 → SIGKILL。

        planned-restart-drain D3：对齐 liveness.wait_for_running_agents 语义——
        先 SIGTERM 让车道子进程收尾，grace 秒内未退出者 SIGKILL 兜底；随后对
        提供 done_event 的车道 bounded 等待其线程落终态（产物/终态事件/worktree
        清理），避免 daemon 进程先于车道终态退出。返回被终止的车道键列表；
        登记表为空时零开销返回空。
        """
        # 方法入口一次快照、下方两循环共用同一份：车道线程在 communicate()
        # 返回后即自行注销（常早于 SIGTERM 循环的 wait(grace) 返回），若
        # done-event 循环重读活登记表，条目多已被弹出、ev.wait() 被静默跳过
        # ——bounded 终态等待保证落空（planned-restart-drain D3）。
        reg_items = list(self._lane_registry().items())
        terminated: list = []
        for key, (proc, _ev) in reg_items:
            try:
                if proc.poll() is not None:
                    continue
                proc.terminate()  # SIGTERM
                try:
                    proc.wait(timeout=max(grace, 0.0))
                except subprocess.TimeoutExpired:
                    self.logger.warning(
                        "agent_runner",
                        f"lane process did not exit within {grace}s, SIGKILL: {key}",
                    )
                    try:
                        proc.kill()
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    except ProcessLookupError:
                        pass
                terminated.append(key)
            except ProcessLookupError:
                pass  # 已退出（竞态）
            except Exception as e:  # noqa: BLE001 — 单车道失败不阻塞其余收口
                self.logger.warning(
                    "agent_runner", f"lane process terminate failed: {key}: {e}"
                )
        # 车道线程落终态 bounded 等待（SIGTERM 后 communicate 返回 → 车道线程
        # finally 写产物/终态事件并 set done_event）
        for key, (_proc, ev) in reg_items:
            if ev is not None:
                try:
                    ev.wait(timeout=max(grace, 0.0))
                except Exception:  # noqa: BLE001
                    pass
        return terminated

    def broadcast_restart_checkpoint(self, reason: str = "planned restart") -> list:
        """restart 排水前向每个在飞 run 广播一次 checkpoint 信号（写即返回）。

        add-pipeline-throughput-governance D3 / graceful-restart-drain：daemon 收到
        restart_request、停止新派发后调用。对每个在飞 run 原子写 run 控制旗标
        ``.fenix/runs/<run_id>.checkpoint.json``（含 created/reason），促使实现侧
        有响应语义的 run 尽快落盘进度声明收尾；无响应语义的 run 不读该文件、
        best-effort 忽略——处理路径与未广播时完全一致（无新增失败终态、无打回，
        超窗强杀与恢复续做行为不变）。

        写后即返回，MUST NOT 阻塞排水等待；单 run 写入失败只记 warning
        （逐 run best-effort，不影响其余 run 与排水流程）。

        Returns: 成功写入旗标的 run_id 列表（供调用方留痕于排水日志）。
        """
        dispatched: list = []
        for rid in self.running_run_ids():
            try:
                runs_dir = self.project_root / ".fenix" / "runs"
                runs_dir.mkdir(parents=True, exist_ok=True)
                flag = runs_dir / f"{rid}.checkpoint.json"
                payload = {
                    "run_id": rid,
                    "action": "checkpoint",
                    "reason": reason,
                    "created": datetime.now(timezone.utc).isoformat(),
                }
                fd, tmp_name = tempfile.mkstemp(
                    dir=str(runs_dir), prefix=f".{rid}.checkpoint.", suffix=".tmp"
                )
                # code-review item 3db27e866e4d：对齐 _write_atomic 手法——
                # json.dump / os.replace 抛错时 finally 兜底 unlink 临时文件，
                # 避免 .fenix/runs 留 .tmp 尸体随逐 run best-effort 重试持续累积。
                tmp_path = Path(tmp_name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False, indent=2)
                    os.replace(tmp_path, flag)
                finally:
                    if tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except OSError:
                            pass
                dispatched.append(rid)
                self.logger.info(
                    "agent_runner",
                    f"restart checkpoint broadcast: '{rid}' 旗标已写"
                    f"（reason={reason}；无响应语义的 run best-effort 忽略）",
                )
            except Exception as e:
                self.logger.warning(
                    "agent_runner",
                    f"restart checkpoint broadcast: '{rid}' 写旗标失败"
                    f"（best-effort 忽略，不影响排水）: {e}",
                )
        return dispatched

    def drain_wait(self, timeout: float) -> list:
        """规划性重启排水：等在跑 run 自然终态，不再对其发 terminate。

        interrupt-recovery-preserve D1/D4：daemon 收到 SIGTERM 且 restart_request
        在册时进入排水模式——禁新派发已由 shutting_down 保证，此处只等在册 run
        收工（run 自身 timeout 兜底），到期仍残留的 run_id 列表原样返回，由
        shutdown 流程据侧车保全后走现行 terminate 收口。

        planned-restart-drain B：排水集合扩展覆盖登记车道进程
        （running_lane_ids）——run 与车道全部安静才提前返回；返回值契约不变
        （仅 run_id，车道不进 run 保全/terminate 链），车道超窗残留由
        ``terminate_lane_processes`` 在 shutdown 收口有序终止。

        Args:
            timeout: 排水窗口秒数（agents.run_drain_max_seconds 生效值）。

        Returns: 窗口到期仍未终态的在跑 run_id 列表（空 = 全部自然收工）。
        """
        deadline = time.time() + max(0.0, timeout)
        remaining = self.running_run_ids()
        if not remaining and not self.running_lane_ids():
            return []
        while time.time() < deadline:
            remaining = self.running_run_ids()
            if not remaining and not self.running_lane_ids():
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

