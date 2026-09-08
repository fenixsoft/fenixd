"""
runner.py — AgentRunner 门面（Agent execution engine for fenixd）.

Spawns claude CLI subprocesses to run implementer and verifier Agents.
Handles result parsing, retry logic, and token/turn budget control.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from core.agent_runner.prompt_builder import (
    PromptBuilder,
    planner_result_path,
)
from core.agent_runner.liveness import (
    AGENT_TERMINATE_GRACE_SECONDS,
    LIVE_ATTEMPT_STREAM_WINDOW_SECONDS,
    SUPERVISION_DEFAULTS,
    JUDGE_TIMEOUT_SECONDS,
    LIVENESS_SNIPPET_CHARS,
    LivenessSupervisor,
)
from core.agent_runner.liveness import LivenessSupervisor
from core.agent_runner.session import SessionTracker
from core.agent_runner.provider_circuit import (
    PROVIDER_CIRCUIT_4XX,
    PROVIDER_CIRCUIT_COOLDOWN_SECONDS,
    PROVIDER_CIRCUIT_PROBE_SUCCESS_CODE,
    PROVIDER_CIRCUIT_THRESHOLD,
    PROVIDER_CIRCUIT_WINDOW_SECONDS,
    PROVIDER_DAILY_ATTEMPTS_WARN,
    PROVIDER_SWITCH_COOLDOWN_SECONDS,
    SWITCH_ERROR_CONN_PATTERNS,
    SWITCH_ERROR_TEXT_PATTERNS,
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
from core.v2_dev_server import (
    V2DevServerError,
    start as v2_start_dev_server,
    stop as v2_stop_dev_server,
    base_url as v2_base_url,
    cleanup_orphans as v2_cleanup_orphans,
)


# 无 provider 分配的 agent（含 Administrator）走默认网关（cc-switch）时 --model 用的
# 官方模型名。provider 已分配的 agent，其 --model 直接取该 agent 分配的网关模型名
# （model 字段，如 deepseek-v4-flash）——见 fenixd-sdk-model-routing：--model 即实际
# 发给网关的模型名，ANTHROPIC_MODEL 被 --model 覆盖不生效。本常量只作 fallback。
DEFAULT_GATEWAY_MODEL = "claude-sonnet-5"

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

# ── Administrator 处置状态实例文件（fix-admin-run-blocks-mainloop D3）─────
# 处置状态文件按 run 实例分离：每个 admin run 使用独立文件
# .fenix/admin_disposition-<run_id>.json，并行实例互不覆盖。
# 旧全局路径 .fenix/admin_disposition.json 不再读写（残留文件由拾取侧清扫）。
ADMIN_DISPOSITION_PREFIX = "admin_disposition-"
ADMIN_DISPOSITION_GLOB = "admin_disposition-*.json"


def admin_disposition_path(project_root: Path, run_id: str) -> Path:
    """某次 admin run 的处置状态实例文件路径。"""
    return Path(project_root) / ".fenix" / f"{ADMIN_DISPOSITION_PREFIX}{run_id}.json"


# ── V2 测试服务器（add-worktree-test-server）────────────────────────────
# per-run 隔离测试服务的端口分配基数，范围 [V2_TEST_PORT_BASE, V2_TEST_PORT_BASE+19]
# 主服务 8787 排除在外，并发运行（并行度 2，预留余量取 20 个高位端口段）不冲突。
V2_TEST_PORT_BASE = 19000
V2_TEST_PORT_RANGE = 20
V2_DEV_SERVER_MARKER = "fenix-v2-dev-server"

class RunCancelledError(Exception):
    """run 被 cancel_run 原语人工取消时抛出。

    不走通用 Exception 处理路径——不重试、不计秒挂、不触发 provider 切换。
    携带 reason（取消原因）与 by（操作人）。
    """

    def __init__(self, reason: str = "", by: str = "admin"):
        self.reason = reason
        self.by = by
        msg = f"run cancelled by {by}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class AgentArtifactGateError(Exception):
    """planner 产物硬门失败（add-judge-artifact-gate D1）。

    进程 exit 0 但结果文件（judge: .fenix-run-result.json / plan:
    test_scenarios.json）缺失、为空或非法 JSON 时抛出——run 按瞬态失败走
    既有原地退避重试通道，不进入 validate_report 的「裁决重试一次」预算。
    """

    def __init__(self, message: str = ""):
        self.artifact_error = message
        super().__init__(message)


class AgentRunResult:
    """Result of a single Agent run."""

    def __init__(self, run_id: str, spec_name: str, agent_type: str,
                 success: bool, duration_seconds: float,
                 turns_used: int = 0, error: str = None, output: str = "",
                 branch: str | None = None,
                 provider_used: str | None = None, model_used: str | None = None,
                 chain_exhausted: bool = False,
                 worktree_dirty: list | None = None,
                 worktree_path=None, worktree_kept: bool = False,
                 cancelled: bool = False):
        self.run_id = run_id
        self.spec_name = spec_name
        self.agent_type = agent_type
        self.success = success
        self.duration_seconds = duration_seconds
        self.turns_used = turns_used
        self.error = error
        self.output = output
        self.branch = branch  # worktree 分支名（成功时由 _execute_agent 填入）
        # add-provider-failover（design D5 / spec failover-dispatch「切换可观测」）：
        # 本次 run 实际使用的 provider 名与 model 名（链选择/切换后落盘可查）。
        self.provider_used = provider_used
        self.model_used = model_used
        # chain_exhausted：链上全部候选均处于 switch 冷却期，attempt 直接失败返回
        # （不启动进程、不计入 spec 重试消耗；design D3 / spec failover-dispatch）。
        self.chain_exhausted = chain_exhausted
        # fix-zero-change-blindspot：implementer 成功收工时、worktree cleanup **前**
        # 取证的 `git status --porcelain` 非空行清单。零变更哨需要「agent 是否真的
        # 动过文件」的证据；cleanup 后证据即销毁（曾致 Bash 写文件的真实工作被
        # 误判为空转、2.11h/$10 全丢）。None/空 = 无脏文件或非 implementer。
        self.worktree_dirty = worktree_dirty
        # worktree 继承（fast-track 打回重派复用）：worktree_path = 本轮使用的
        # worktree（fast-track 成功路径延迟清理、由 dispatch 层判定后处置）；
        # worktree_kept = runner 终态失败时已保留为复用遗产（dispatch 无需重复保留）。
        self.worktree_path = worktree_path
        self.worktree_kept = worktree_kept
        # run 是否被人工取消（cancel_run 旗标命中导致 RunCancelledError）。
        self.cancelled = cancelled

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "spec_name": self.spec_name,
            "agent_type": self.agent_type,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "turns_used": self.turns_used,
            "error": self.error,
            "branch": self.branch,
            "provider_used": self.provider_used,
            "model_used": self.model_used,
            "chain_exhausted": self.chain_exhausted,
            "cancelled": self.cancelled,
            "output_summary": self.output[-500:] if self.output else "",
        }


class AdminDisposition:
    """Administrator Agent 一次处置的结果（run_administrator 返回）。"""

    def __init__(self, run_id: str, spec: str | None = None, success: bool = True,
                 problem: str = "", actions_taken: str = "", result: str = "",
                 escalate: bool = False, recommended_action: str = "",
                 summary: str = "", error: str = "", output: str = "",
                 family_waiver: bool = False):
        self.run_id = run_id
        self.spec = spec
        self.success = success
        self.problem = problem
        self.actions_taken = actions_taken
        self.result = result
        self.escalate = escalate
        self.recommended_action = recommended_action
        self.summary = summary
        self.error = error
        self.output = output
        # family_explosion 处置：Administrator 对该父 SPEC「放行一次」。
        # 由 admin_monitor 落成 _family_waiver=true（单次豁免，用后复位）。
        self.family_waiver = family_waiver

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "spec": self.spec,
            "success": self.success,
            "problem": self.problem,
            "actions_taken": self.actions_taken,
            "result": self.result,
            "escalate": self.escalate,
            "recommended_action": self.recommended_action,
            "summary": self.summary,
            "error": self.error,
        }


class SelfReviewResult:
    """每日自省 run 的结果（run_self_review 返回，add-daily-self-review）。

    waste/mistakes/improvements 为三个小节条目列表（每条含证据与建议，
    由 Agent 在回顾 JSON 中产出）；resolved 为闭环判定清单（``[{id,
    reason}]``，畸形条目在解析时过滤），调度器据此从 todo.md 移除已闭环
    条目；success=False 时 error 携带失败原因。
    """

    def __init__(self, run_id: str, date: str = "", success: bool = True,
                 waste: list | None = None, mistakes: list | None = None,
                 improvements: list | None = None, summary: str = "",
                 resolved: list | None = None,
                 error: str = "", output: str = ""):
        self.run_id = run_id
        self.date = date
        self.success = success
        self.waste = list(waste or [])
        self.mistakes = list(mistakes or [])
        self.improvements = list(improvements or [])
        self.summary = summary
        self.resolved = list(resolved or [])
        self.error = error
        self.output = output


# ── run 级 API 延迟统计（add-planner-efficiency：run-latency-observability）──
# 在线（_run_claude 流式循环旁路）与事后（bin/analyze_run_latency.py）共用
# 同一套口径函数：对事件序列 `tool_result → 下一个 assistant` 间隔采样为
# API 往返样本，再计算直方图摘要（轮数/中位/p90/max/长尾>60s 计数与占比）。
# 纯读侧，不改变流式事件处理时序。timestamp 解析复用 AgentRunner 的
# _parse_event_timestamp（以惰性解析避免类定义前的默认参数引用）。

LATENCY_STALL_SECONDS = 60.0


def iter_events(entries):
    """逐条 yield（兼容既有调用方传 list 或生成器）。"""
    yield from entries


def _default_ts_parser(entry: dict):
    """默认 timestamp 解析器：委托 AgentRunner._parse_event_timestamp。"""
    return AgentRunner._parse_event_timestamp(entry)


def latency_samples_from_events(entries, parser=None) -> list:
    """从事件序列提取 API 往返样本（tool_result → 下一个 assistant 间隔）。

    口径（design D3，与 2026-09-05 事故分析一致）：记录最近一个
    ``tool_result`` 事件的 timestamp，遇到下一个 ``assistant`` 事件时两者
    之差 = 一次 API 往返样本；随后清空待配对的 tool_result（一个样本只
    配对一次）。timestamp 缺失的事件不参与（跳过），样本列表可空。

    Args:
        entries: 事件 dict 序列（list / 生成器）。
        parser: timestamp 解析函数（缺省 = AgentRunner._parse_event_timestamp）。

    Returns: float 秒样本列表（含 >60s 长尾；顺序为事件到达序）。
    """
    if parser is None:
        parser = _default_ts_parser
    samples: list = []
    last_tool_result_ts: float | None = None
    for e in iter_events(entries):
        if not isinstance(e, dict):
            continue
        etype = e.get("type")
        if etype == "tool_result":
            ts = parser(e)
            if ts is not None:
                last_tool_result_ts = ts
        elif etype == "assistant":
            ts = parser(e)
            if ts is not None and last_tool_result_ts is not None:
                samples.append(ts - last_tool_result_ts)
                last_tool_result_ts = None
    return samples


def latency_stats(samples) -> dict:
    """把 API 往返样本压缩为直方图摘要（空样本安全返回全 0 键）。

    Returns: {"rounds": int, "median": float|None, "p90": float|None,
              "max": float|None, "stalls": int, "stall_ratio": float}
        rounds 为样本数（=有 timestamps 的 API 往返轮数）；stalls 为
        >60s 长尾样本数；stall_ratio = stalls/rounds（0 样本为 0）。
    """
    n = len(samples)
    base = {"rounds": n, "median": None, "p90": None, "max": None,
            "stalls": 0, "stall_ratio": 0.0}
    if n == 0:
        return base
    ordered = sorted(samples)
    base["median"] = _percentile(ordered, 0.5)
    base["p90"] = _percentile(ordered, 0.9)
    base["max"] = ordered[-1]
    base["stalls"] = sum(1 for s in samples if s > LATENCY_STALL_SECONDS)
    base["stall_ratio"] = base["stalls"] / n
    return base


def _percentile(ordered: list, q: float) -> float:
    """已排序列表的线性插值分位数（q∈[0,1]）。"""
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def format_latency_summary(run_id: str, stats: dict) -> str:
    """把摘要渲染为日志行（设计示例同款口径）。

    ``run planner-plan-xxx-a1: 58 rounds, median 3.2s, p90 78s, max 185s,
    stalls>60s=15 (26%)``。无样本时标注样本数（时间戳缺失的旧转录）。
    """
    if stats.get("rounds", 0) <= 0:
        return f"run {run_id}: 0 rounds（无 timestamp 样本，旧转录跳过）"
    med = stats.get("median") or 0
    p90 = stats.get("p90") or 0
    mx = stats.get("max") or 0
    stalls = stats.get("stalls") or 0
    ratio = (stats.get("stall_ratio") or 0) * 100
    return (
        f"run {run_id}: {stats['rounds']} rounds, "
        f"median {med:.1f}s, p90 {p90:.1f}s, max {mx:.1f}s, "
        f"stalls>60s={stalls} ({ratio:.0f}%)"
    )


class AgentRunner:
    """
    Execute Agents via claude CLI subprocess.

    Manages retry logic, run limits, and result tracking.
    """

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

    def run_administrator(self, signal: dict) -> AdminDisposition:
        """唤起 Administrator Agent 处置困境信号（administrator-agent spec）。

        与 implementer/verifier 不同：Administrator 是运维角色，直接在 main 树
        （project_root）操作框架，不创建 worktree（design D4）。产物写入
        .fenix/runs/admin-<spec>-<ts>.jsonl；处置结果从管理员按 prompt 写入的
        实例文件 .fenix/admin_disposition-<run_id>.json 读取，由 daemon 落盘到
        admin_alerts.json。

        fix-admin-run-blocks-mainloop D3：处置状态文件按 run 实例分离——并行
        多实例（worker 池）各自 clear/write/read 自己的文件，互不覆盖。

        Args:
            signal: admin_monitor 检测到的困境信号 dict
                （signal_type/spec/severity/description/evidence/recommended_action）。
        """
        spec = signal.get("spec") or "global"
        run_id = f"admin-{spec}-{int(time.time())}"
        # 实例路径注入提示词（prompt_builder 把写入指令指向该文件）
        disp_path = admin_disposition_path(self.project_root, run_id)
        prompt_detail = dict(signal)
        prompt_detail["disposition_path"] = str(disp_path)
        prompt = self._build_prompt(spec, "administrator", detail=prompt_detail)

        # improve-config-ui-tabs：Administrator 运行时解析链（design D4）
        #   1. agents.models.administrator assignment → 用分配 model 并注入 provider env（直连）
        #   2. 无 assignment → 沿用旧逻辑 _get_admin_model()（admin.agent_model → 默认网关）
        assignment = self._get_agent_model_assignment("administrator")
        env_overrides: Dict[str, str] = {}
        if assignment:
            # 取链首选（Administrator 不接入 attempt 级 failover，仅用首选直连）
            provider, model_override = assignment[0]
            env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
            env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
            env_overrides["ANTHROPIC_MODEL"] = model_override
            env_overrides["CLAUDE_CONFIG_DIR"] = str(
                self._ensure_agent_config_dir(provider["name"])
            )
            for k, v in (provider.get("env") or {}).items():
                env_overrides[k] = v
            # 观测：run jsonl 写 provider_marker，与 dispatch attempt 路径同口径，
            # 时间轴才能展示 Administrator 实际驱动的 model@provider；
            # Administrator 不接 failover，链内下标恒 0/1
            self._write_provider_marker(
                run_id, spec, "administrator",
                provider["name"], model_override, 0, 1,
            )
        else:
            model_override = self._get_admin_model()

        # fix-admin-self-heal：唤起前先落 pending disposition，保证即使 admin 被
        # kill（如 daemon 重启/崩溃）也有记录可回溯；monitor 会检测无最终结果的
        # pending 并升级人工，避免「admin 死了但没有任何告警」。
        try:
            from core.admin_store import AdminStore, DISPOSITION
            AdminStore(self.project_root, getattr(self, "logger", None)).append({
                "kind": DISPOSITION,
                "status": "pending",
                "signal_type": signal.get("signal_type"),
                "spec": spec,
                "admin_run_id": run_id,
                "description": (f"Administrator 处置中（run {run_id}），尚未完成；"
                                f"若长时间无最终结果，AdminMonitor 会自动升级人工"),
                "result": "pending",
                "recommended_action": signal.get("recommended_action"),
            })
        except Exception:
            pass

        self._clear_admin_disposition(disp_path)
        try:
            # _run_claude 返回 4 元组（add-cost-observability D1 加 usage_info）；
            # admin 不消费 usage，此调用点曾漏改按 3 元组解包——admin run 一启动
            # 即崩 too many values to unpack（2026-09-05 回检发现）
            output, turns, _session_id, _usage = self._run_claude(
                prompt, self.project_root, run_id, model_override, env_overrides,
                max_turns=self._get_config("agents.max_turns", 300),
                spec_name=spec,
                agent_type="administrator",
            )
            success = True
            error = ""
        except Exception as e:
            output = ""
            success = False
            error = str(e)
            # fix-admin-disposition-empty-shell：失败不再静默——WARNING 携带 run_id
            # 与异常文本，保证 `grep "Administrator run"` 可一次检索全部失败。
            self.logger.warning(
                "agent_runner",
                f"Administrator run {run_id} failed: {error}",
                {"run_id": run_id, "error": error},
            )

        disp = self._read_admin_disposition(disp_path)
        # 读取即清理自身实例文件：内容已捕获进 AdminDisposition 返回给调用方落
        # final 记录，文件不再有读者；不清理会随并行实例累积成垃圾。
        self._delete_admin_disposition(disp_path)
        return AdminDisposition(
            run_id=run_id,
            spec=disp.get("spec") or signal.get("spec"),
            success=success,
            problem=disp.get("problem") or signal.get("description", ""),
            actions_taken=disp.get("actions_taken") or "",
            result=disp.get("result") or ("resolved" if success else "failed"),
            escalate=bool(disp.get("escalate", False)),
            recommended_action=disp.get("recommended_action") or "",
            summary=disp.get("summary") or "",
            error=error,
            output=output,
            family_waiver=bool(disp.get("family_waiver", False)),
        )

    def _clear_admin_disposition(self, disp_path: Path):
        """清空本次 run 的处置状态文件（若残留），避免读到陈旧数据。

        fix-admin-run-blocks-mainloop D3：路径按 run 实例传入，不再使用全局
        固定文件名——并行实例只清理自己的文件。
        """
        try:
            if disp_path.exists():
                disp_path.unlink()
        except OSError:
            pass

    def _delete_admin_disposition(self, disp_path: Path):
        """run 结束后删除自己的处置状态实例文件（内容已在内存中/已落 final）。"""
        try:
            disp_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _read_admin_disposition(self, disp_path: Path) -> dict:
        """读取管理员按 prompt 写入的处置记录（实例文件，路径按 run 注入）。

        文件缺失/损坏返回空 dict（调用方用信号详情兜底）。
        """
        try:
            data = json.loads(disp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        at = data.get("actions_taken")
        if isinstance(at, list):
            # 列表型动作以换行符连接，每条动作独立一行（design D5）
            data["actions_taken"] = "\n".join(str(x) for x in at if x)
        elif at is None:
            data["actions_taken"] = ""
        elif not isinstance(at, str):
            data["actions_taken"] = str(at)
        sm = data.get("summary")
        if isinstance(sm, list):
            # 列表型叙述以换行符连接，每段独立一行
            data["summary"] = "\n".join(str(x) for x in sm if x)
        elif sm is None:
            data["summary"] = ""
        elif not isinstance(sm, str):
            data["summary"] = str(sm)
        return data

    # ── 每日自省 run（add-daily-self-review spec，design D2） ──────────

    def run_self_review(self, date_str: str, daily_summary: str,
                        todo_md: str | None = None,
                        todo_entries: str | None = None) -> SelfReviewResult:
        """唤起每日自省 run（Administrator 通道，design D2 复用语义）。

        与 implementer/verifier 不同：自省是运维角色，直接在 main 树
        （project_root）操作，不创建 worktree。特性：
        - run_id 前缀 ``review-<date>``：独立前缀，不占 spec 维度预算、
          不计入每日 agent run 计数（不走 _execute_agent）；
        - token 归账到 cost-observability 独立类目
          （.fenix/cost/self_review_tokens.json，design D2 二选一），不写
          STATE（自省链路禁止注册 STATE 条目）；
        - 超时走 agents.run_timeout_seconds 全局默认（_run_claude 内生效，
          不设 override）。
        - 模型解析链：agents.models.self-review 分配优先；未配置回退
          agents.models.administrator（向后兼容，自省源自运维通道）；
          再回退 admin.agent_model → 默认网关。

        Agent 按 prompt 把回顾写入实例文件
        ``.fenix/self_review_out-<run_id>.json``（JSON：
        date/waste/mistakes/improvements/resolved/summary），run 结束读取
        并清理。失败（异常/超时/rc!=0）返回 success=False（调度器记告警、
        24h 内不重试）。

        Args:
            date_str: 自省归属执行日 YYYY-MM-DD（即 run_id 内嵌日期）。
            daily_summary: 框架聚合的近 24 小时数据摘要（五源），注入 prompt。
            todo_md: read_todo=true 时的既有 todo.md 全文；None 不注入。
            todo_entries: read_todo=true 时 ID 标注的近 3 日条目清单
                （闭环判定对象）；None 注入占位提示。
        """
        run_id = f"review-{date_str}"
        out_path = self.project_root / ".fenix" / f"self_review_out-{run_id}.json"
        prompt = self._build_prompt(date_str, "self-review", detail={
            "review_date": date_str,
            "daily_summary": daily_summary or "",
            "todo_md": todo_md or "",
            "todo_entries": todo_entries or "",
            "out_path": str(out_path),
        })

        # 模型解析链：agents.models.self-review > 回退 agents.models.administrator
        # （向后兼容：自省未单独配置时继承运维通道分配）> admin.agent_model → 默认网关
        env_overrides: Dict[str, str] = {}
        assignment = (self._get_agent_model_assignment("self-review")
                      or self._get_agent_model_assignment("administrator"))
        if assignment:
            provider, model_override = assignment[0]
            env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
            env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
            env_overrides["ANTHROPIC_MODEL"] = model_override
            env_overrides["CLAUDE_CONFIG_DIR"] = str(
                self._ensure_agent_config_dir(provider["name"])
            )
            for k, v in (provider.get("env") or {}).items():
                env_overrides[k] = v
        else:
            model_override = self._get_admin_model()

        self._clear_self_review_out(out_path)
        try:
            output, turns, _session_id, usage_info = self._run_claude(
                prompt, self.project_root, run_id, model_override, env_overrides,
                max_turns=self._get_config("agents.max_turns", 300),
                spec_name="self-review",
            )
            success = True
            error = ""
        except Exception as e:
            output = ""
            success = False
            error = str(e)
            usage_info = self._extract_usage_info(None)

        # token 归账到独立类目（不写 STATE，硬约束）
        self._accumulate_self_review_tokens(date_str, usage_info)

        data = self._read_self_review_out(out_path)
        self._delete_self_review_out(out_path)
        # resolved 闭环判定清单归一化：非 dict / 缺 id / 空 id / 非 str id 过滤
        resolved = []
        for item in (data.get("resolved") or []):
            if (isinstance(item, dict) and isinstance(item.get("id"), str)
                    and item["id"]):
                resolved.append({
                    "id": item["id"],
                    "reason": str(item.get("reason") or ""),
                })
        return SelfReviewResult(
            run_id=run_id,
            date=date_str,
            success=success,
            waste=data.get("waste") or [],
            mistakes=data.get("mistakes") or [],
            improvements=data.get("improvements") or [],
            summary=data.get("summary") or "",
            resolved=resolved,
            error=error,
            output=output,
        )

    def _clear_self_review_out(self, out_path: Path):
        """清空本次自省 run 的输出文件（若残留），避免读到陈旧数据。"""
        try:
            if out_path.exists():
                out_path.unlink()
        except OSError:
            pass

    def _delete_self_review_out(self, out_path: Path):
        """run 结束后删除自己的 self_review 输出实例文件。"""
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _read_self_review_out(self, out_path: Path) -> dict:
        """读取自省 run 的回顾 JSON；缺失/损坏返回空 dict（调用方兜底）。"""
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        for field in ("waste", "mistakes", "improvements"):
            val = data.get(field)
            if not isinstance(val, list):
                data[field] = []
            else:
                # 结构化条目（dict，{impact, evidence, analysis?, suggestion}）
                # 保持原形直达渲染层，仅非 dict/str 标量兜底 str——无差别
                # str() 会把合规 dict 打成 dict-repr 字符串，渲染层四行格式
                # 失效退化为机器形态（09-08 事故）。
                data[field] = [x if isinstance(x, (dict, str)) else str(x)
                               for x in val if x]
        sm = data.get("summary")
        if sm is None:
            data["summary"] = ""
        elif not isinstance(sm, str):
            data["summary"] = str(sm)
        return data

    def _accumulate_self_review_tokens(self, date_str: str, usage_info: dict) -> None:
        """add-daily-self-review：自省 token 归账到 cost-observability 独立类目。

        design D2 二选一（独立 self-review 类目）：追加到
        ``.fenix/cost/self_review_tokens.json`` 的 runs 数组（与
        verify-progress tokens.json 同结构），供成本对账口径一致；不写
        STATE（禁止注册 STATE 条目硬约束）。写失败静默降级（观测增强，
        不阻断自省主流程）。
        """
        if not isinstance(usage_info, dict):
            usage_info = {}
        cost_dir = self.project_root / ".fenix" / "cost"
        tokens_json = cost_dir / "self_review_tokens.json"
        try:
            tokens_json.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if tokens_json.is_file():
                try:
                    loaded = json.loads(tokens_json.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    loaded = {}
                if isinstance(loaded, dict):
                    data = loaded
            runs = data.get("runs")
            if not isinstance(runs, list):
                runs = []
            runs.append({
                "agent_type": "self-review",
                "date": date_str,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_tokens": int(usage_info.get("input_tokens", 0) or 0)
                + int(usage_info.get("cache_creation_input_tokens", 0) or 0)
                + int(usage_info.get("cache_read_input_tokens", 0) or 0),
                "output_tokens": int(usage_info.get("output_tokens", 0) or 0),
                "cost_usd": usage_info.get("cost_usd"),
            })
            data["runs"] = runs
            tokens_json.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    def _get_admin_model(self) -> str:
        """Administrator 模型名：admin.agent_model > 默认网关 fallback 常量。"""
        admin_model = self._get_config("admin.agent_model", None)
        if admin_model:
            return admin_model
        return DEFAULT_GATEWAY_MODEL

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
        wt_path = pre_wt_path
        session_id = None
        # session_id 所属 provider（None=默认网关）：session 存在于其创建时的
        # CLAUDE_CONFIG_DIR，跨 provider 续跑必然 'No conversation found'（fix）。
        session_provider = None
        # 实例级链指针（design D1：cursor 按 agent_type 记忆）。-1 表示尚未选定。
        chain_cursor = -1
        last_provider_used = None  # 用于 "provider switched" 跨 attempt 打点
        kept_wt_path = None  # worktree-reuse：fast-track 终态失败保留的复用遗产路径
        provider_name = None  # 本轮候选 provider（链选择前为 None，供 frozen 提前返回使用）
        model = None
        self._last_model_used = None  # 用于 model_changed 日志留痕（design D3）
        # add-run-cancel D3/D5：本轮 run 是否被人工取消（RunCancelledError 捕获
        # 或 attempt 顶部旗标命中）。cancelled_flag 为 True 时不再进入下一 attempt。
        cancelled_flag = False
        cancel_reason = ""

        for attempt in range(1, max_retries + 1):
            attempt_run_id = f"{run_id}-a{attempt}"
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
                return AgentRunResult(
                    run_id, spec_name, agent_type,
                    success=False, duration_seconds=time.time() - start_time,
                    error=(f"spec frozen — auto-retry terminated "
                           f"(attempt {attempt}/{max_retries})"),
                    provider_used=provider_name, model_used=model,
                )
            # add-run-cancel D3：attempt 循环顶部检查取消旗标（与 frozen 检查同
            # 位置，覆盖 attempt 间隙/准备阶段）——命中立即返回，不派发后续
            # attempt、不创建本 attempt 的 worktree；残留 worktree 按终态失败
            # 同语义清理。
            if self._cancel_is_requested(run_id):
                meta = self._cancel_meta.get(run_id, {})
                cancel_reason = meta.get("reason", "")
                self.logger.warning(
                    "agent_runner",
                    f"run '{run_id}' 取消旗标命中，终止 {agent_type} 重试链"
                    f"（attempt {attempt}/{max_retries}），不派发 attempt",
                )
                if wt_path is not None:
                    self._v2_stop_for_worktree(wt_path)
                    if agent_type == "fast-track":
                        self.worktree_manager.keep_for_reuse(spec_name, wt_path)
                        kept_wt_path = wt_path
                        # 取消 keep：目录+分支有意保留供下轮复用，不参与终态收割
                        handed_off.add(wt_path)
                    elif agent_type == "repair":
                        # 终态失败保留现场：dispatch 层负责回收（fallback 清理）
                        kept_wt_path = wt_path
                        handed_off.add(wt_path)
                    else:
                        self.worktree_manager.cleanup(wt_path, success=False)
                self._cancel_clear(run_id)
                return AgentRunResult(
                    run_id, spec_name, agent_type,
                    success=False, duration_seconds=time.time() - start_time,
                    error=("cancelled by admin"
                           + (f": {cancel_reason}" if cancel_reason else "")),
                    cancelled=True,
                    provider_used=provider_name, model_used=model,
                    worktree_path=kept_wt_path,
                    worktree_kept=kept_wt_path is not None,
                )
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

            # ── 候选链解析与选择（add-provider-failover） ──
            chain = self._get_agent_model_assignment(agent_type) or []
            if not chain:
                # 无 provider 分配：走默认网关（cc-switch），无链可选。provider_name=None。
                provider_name = None
                provider = None
                model = None
            else:
                # 链指针推进：上次因切换类失败已前移的，保持前移（design D1/D3）；
                # 否则从头选首个未冷却候选。4xx 熔断拦截态也算"不可用"跳过。
                if chain_cursor < 0:
                    chain_cursor = self._select_chain_candidate(chain, spec_name, agent_type)
                if chain_cursor < 0:
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
                        return AgentRunResult(
                            attempt_run_id, spec_name, agent_type,
                            success=False, duration_seconds=time.time() - start_time,
                            error=circuit_err, provider_used=first_4xx_open,
                        )
                    exhausted_err = (
                        f"provider chain exhausted for {agent_type} '{spec_name}': "
                        f"all {len(chain)} candidates in switch/4xx cooldown"
                    )
                    self.logger.error("agent_runner", exhausted_err)
                    return AgentRunResult(
                        attempt_run_id, spec_name, agent_type,
                        success=False, duration_seconds=time.time() - start_time,
                        error=exhausted_err, chain_exhausted=True,
                    )
                provider, model = chain[chain_cursor]
                provider_name = provider["name"]

                # ── 4xx 熔断拦截（fix-stashpop-deadlock：provider-fault-fuse） ──
                # 仅对当前选中候选生效；若已熔断（冷却未到期），直接失败返回、不启动 claude、
                # 不创建 worktree/autostash、不计入 spec 连续失败重试（design D5）。冷却到期后
                # 首个真实派发作为半开探针（design D4）。
                if self.is_circuit_open(provider_name):
                    circuit_err = self._circuit_open_error(provider_name)
                    self.logger.warning(
                        "agent_runner",
                        f"Suppressed {agent_type} dispatch for '{spec_name}': {circuit_err}",
                    )
                    # 不创建 worktree、不进入重试计数。直接以熔断错误返回。
                    return AgentRunResult(
                        attempt_run_id, spec_name, agent_type,
                        success=False, duration_seconds=time.time() - start_time,
                        error=circuit_err, provider_used=provider_name, model_used=model,
                    )

                # 选中且未熔断 → 计一次当日 attempt（design D5 / spec 4.2），后续跨 attempt
                # 切换打点依赖 last_provider_used。
                self._record_daily_provider_attempt(provider_name)

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
                    return AgentRunResult(
                        attempt_run_id, spec_name, agent_type,
                        success=False, duration_seconds=time.time() - start_time,
                        error=error_msg, provider_used=provider_name, model_used=model,
                    )
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
            if last_provider_used is not None and provider_name is not None \
                    and provider_name != last_provider_used:
                switch_msg = (
                    f"provider switched {last_provider_used} → {provider_name} "
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
            last_provider_used = provider_name

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
                        if self._should_give_up_before_retry(spec_name, agent_type):
                            return AgentRunResult(
                                attempt_run_id, spec_name, agent_type,
                                success=False,
                                duration_seconds=time.time() - start_time,
                                error=f"{error_msg} (gave up: parallel run or manual freeze)",
                                provider_used=provider_name, model_used=model,
                            )
                        continue
                    return AgentRunResult(
                        attempt_run_id, spec_name, agent_type,
                        success=False, duration_seconds=time.time() - start_time,
                        error=error_msg, provider_used=provider_name, model_used=model,
                    )
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

            # ── 观测：run jsonl 写 provider_marker（design D5 / spec failover-dispatch） ──
            # attempt 启动时写入，指明所用 provider/model 与链内下标，事后可追溯实际网关。
            if provider_name is not None:
                self._write_provider_marker(
                    attempt_run_id, spec_name, agent_type,
                    provider_name, model, chain_cursor, len(chain),
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
                    # add-judge-artifact-gate D1：planner 产物存在性硬门——成功判定
                    # 从「进程 exit 0」升级为「exit 0 且结果文件落盘且可解析」；
                    # 不满足抛 AgentArtifactGateError，落入下方瞬态退避重试通道
                    # （复用 fix-provider-transient-backoff，不消耗 validate_report
                    # 的「裁决重试一次」预算）。
                    gate_err = self._check_agent_result_artifact(spec_name, agent_type)
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
                    error = "cancelled by admin" + (f": {e.reason}" if e.reason else "")
                    self.logger.info(
                        "agent_runner",
                        f"{agent_type} for '{spec_name}' run 被人工取消"
                        f"（attempt {attempt}）：{error}",
                    )
                    usage_info = self._extract_usage_info(None)
                    break  # 原地重试子循环：取消退出 while
                except AgentArtifactGateError as e:
                    # add-judge-artifact-gate D1：exit 0 但产物缺失/为空/非法 JSON
                    # → 按瞬态失败走既有原地退避重试（fix-provider-transient-backoff
                    # 通道原样复用，不新增重试机制；不消耗 validate_report 的「裁决
                    # 重试一次」预算）。run 已完整执行（exit 0），不计数秒挂；usage
                    # 保留 _run_claude 实测值（区别于早期抛错按 0 计）。
                    output = ""
                    turns = 0
                    success = False
                    error = str(e)
                    self.logger.warning(
                        "agent_runner",
                        f"Artifact gate failed for '{spec_name}' ({agent_type}): {error}",
                    )
                    if "[provider-transient]" not in error:
                        error = f"[provider-transient] {error}"
                    # 全局瞬断指纹计数（transient-dispatch-gating D4 同语义）：
                    # 产物硬门失败同样记账，保留 dispatch 闸门对瞬断风暴的可见性。
                    try:
                        self.record_transient_break(str(e))
                    except Exception as _break_err:
                        self.logger.debug(
                            "agent_runner",
                            f"global transient break 记账失败（不阻断）: {_break_err}",
                        )
                    if transient_retries < len(transient_budget):
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
                        self.logger.warning(
                            "agent_runner",
                            f"Artifact gate for '{spec_name}' (attempt {attempt}, "
                            f"{agent_type}) — in-place retry "
                            f"{transient_retries}/{len(transient_budget)} "
                            f"after {backoff}s backoff (add-judge-artifact-gate)",
                        )
                        time.sleep(backoff)
                        continue
                    break  # 原地预算耗尽 → 退出 while，attempt 层继续重试
                except Exception as e:
                    output = ""
                    turns = 0
                    success = False
                    error = str(e)
                    # cli-retry-backoff（2.1）：attempt 失败按存活时长判定秒挂并累计。
                    # 仅「进程确实启动过」的失败才判定（worktree 创建失败等进程未起的
                    # 分支走上方 return/continue，不进入本法）；框架主动 SIGTERM 由
                    # _run_was_interrupted 识别不计入。
                    self._record_instant_fail(
                        spec_name,
                        time.time() - attempt_started_at,
                        self.project_root / ".fenix" / "runs" / f"{attempt_run_id}.jsonl",
                    )
                    # add-cost-observability（D1）：_run_claude 抛错（超时/kill/非 0 退出/
                    # rc==0 但 result 标记 error），stream-json 终态已被丢弃，按 0 计 usage，
                    # 仅 DEBUG 留痕（异常早夭的 run 消耗小，与 jsonl 考古一致偏差可接受）。
                    usage_info = self._extract_usage_info(None)
                    self.logger.debug(
                        "agent_runner",
                        f"{agent_type} for '{spec_name}' ended in error — tokens counted "
                        f"as 0 (add-cost-observability): {error}",
                    )
                    # 4xx 熔断计数（fix-stashpop-deadlock：provider-fault-fuse）。
                    # 仅对「已分配 provider」且错误文本能解析出 HTTP 4xx 的情况计数（design D4）；
                    # 5xx/网络错误不计数（瞬态，走既有 retry）。解析不到 code 视为失败、不计数。
                    if provider_name:
                        code = self.parse_api_error_status(error)
                        if code is not None and code in PROVIDER_CIRCUIT_4XX:
                            was_half_open = False
                            st = self.provider_circuits.get(provider_name)
                            if st and st.get("count", 0) >= PROVIDER_CIRCUIT_THRESHOLD \
                                    and st.get("cooldown_until", 0) > 0 \
                                    and st["cooldown_until"] <= self._now():
                                # 半开探针仍 4xx → 重新冷却（design D4），不重复计数。
                                was_half_open = True
                            self._record_provider_4xx(provider_name, code)
                            if was_half_open:
                                self._record_provider_probe(provider_name, success=False)
                        else:
                            # fix-provider-transient-backoff（D1）：瞬断判定独立于
                            # classify_switch_error——降噪后 error 文本可能不含
                            # unrecognized_model 字样（D5 已过滤），判定必须依赖原始
                            # stderr 信号（异常携带的 stderr_lines / has_result）。
                            # resume 死 session（No conversation found）不属网关瞬断，
                            # 排除在瞬断判定之外（其处置走下方 session 清理兜底）。
                            exc_stderr = getattr(e, "stderr_lines", None) or []
                            exc_exit = getattr(e, "exit_code", None)
                            exc_has_result = getattr(e, "has_result", None)
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
                            if (is_transient
                                    and transient_retries < len(transient_budget)):
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
                                self.logger.warning(
                                    "agent_runner",
                                    f"Transient error for '{spec_name}' (attempt {attempt}, "
                                    f"provider {provider_name}) — in-place retry "
                                    f"{transient_retries}/{len(transient_budget)} "
                                    f"after {backoff}s backoff (fix-provider-transient-backoff)",
                                )
                                time.sleep(backoff)
                                continue  # 回到 while 顶部重跑同一 attempt（新 sub_run_id）
                            # 非瞬断或原地预算耗尽 → 现行切换逻辑
                            # add-provider-failover（design D2/D3）：切换类错误 → 该 provider
                            # 进入 switch 短冷却，同 run 后续 attempt 前进到下一候选（跨
                            # provider 不 resume，见 _resumable_session_id）。
                            # 4xx 配额/鉴权类不触发（维持既有熔断语义、链指针不动）。
                            if self.classify_switch_error(error):
                                self._record_switch_cooldown(provider_name)
                                # 仅当链上还有后续候选才前进指针；否则保持当前（全链耗尽将
                                # 在下一 attempt 的 _select_chain_candidate 中判定为 chain_exhausted）。
                                if chain_cursor + 1 < len(chain):
                                    chain_cursor += 1
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

            # 成功时，把 worktree 中的 .fenix-run-result.json 复制到主树。
            if success:
                wt_result = wt_path / ".fenix-run-result.json"
                root_result = self.project_root / ".fenix" / ".fenix-run-result.json"
                if wt_result.exists():
                    try:
                        root_result.write_text(
                            wt_result.read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                    except OSError:
                        pass

            if success:
                # 半开探针闭合（fix-stashpop-deadlock）：若该 provider 此前已进入熔断但
                # 冷却已到期（半开），此派发成功即视为网关恢复，闭合熔断（design D4）。
                if provider_name:
                    st = self.provider_circuits.get(provider_name)
                    if st and st.get("cooldown_until", 0) > 0 and st["cooldown_until"] <= self._now():
                        self._record_provider_probe(provider_name, success=True)
                # add-worktree-test-server（D2 终态回收）：worktree 清理前先回收其 dev-server。
                # fast-track 例外：成功不清理——硬校验/守卫在 dispatch 层判定，失败时
                # 保留 worktree 供重派继承（worktree-reuse）；通过则由 dispatch 在
                # merge 后统一清理。dev-server 随 dispatch 层处置一并回收。
                wt_dirty: list = []
                if agent_type in ("implementer", "fast-track"):
                    # fix-zero-change-blindspot：cleanup 前取证 worktree dirty 状态
                    #（仅 implementer / fast-track——零变更哨对两者都生效）。
                    st = subprocess.run(
                        ["git", "-C", str(wt_path), "status", "--porcelain"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if st.returncode == 0:
                        wt_dirty = [l for l in st.stdout.splitlines() if l.strip()]
                elif agent_type == "repair":
                    # repair 现场取证：冲突解决是否已 commit（dispatch 层据此
                    # 判断 re-merge-back 前的现场状态，add-merge-back-repair-lane）。
                    st = subprocess.run(
                        ["git", "-C", str(wt_path), "status", "--porcelain"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if st.returncode == 0:
                        wt_dirty = [l for l in st.stdout.splitlines() if l.strip()]
                # add-merge-back-repair-lane：repair 与 fast-track 同语义，
                # 成功不清理 worktree——冲突解决成果仍在分支上，交给 dispatch
                # 层的 re-merge-back 决定终态；多轮 repair 需原地复用现场。
                if agent_type in ("fast-track", "repair"):
                    # 延迟清理：worktree 与 dev-server 均由 dispatch 层处置；
                    # 有意交接 → 不参与本 run 终态收割
                    handed_off.add(wt_path)
                else:
                    self._v2_stop_for_worktree(wt_path)
                    # 成功：清理 worktree（保留分支供 merge-back），返回结果
                    self.worktree_manager.cleanup(wt_path, success=True)
                duration = time.time() - start_time
                self._daily_run_count += 1
                # cli-retry-backoff（2.1/2.2）：成功收工重置秒挂连续计数（非连续不累积）
                self._reset_instant_fail(spec_name)
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
            else:
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
                if attempt < max_retries and not cancelled_flag:
                    time.sleep(10)  # Wait before retry
                    # fix-provider-transient-backoff（D3）：attempt 间 worktree
                    # 保留扩展到全部 agent_type——非 implementer 族复用前仍过
                    # frozen/取消检查（见上方 reuse_worktree 判定），不再清工作树。
                    # dev-server 随之复用，不重复启停。
                else:
                    self._v2_stop_for_worktree(wt_path)
                    if agent_type == "fast-track":
                        self.worktree_manager.keep_for_reuse(spec_name, wt_path)
                        kept_wt_path = wt_path
                        # 终态失败保留复用遗产：下轮在同一 worktree 继承成果，
                        # 目录+分支有意保留 → 不参与终态收割（dev-server 已停）
                        handed_off.add(wt_path)
                    elif agent_type == "repair":
                        # 终态失败保留现场：dispatch 层负责回收（fallback 清理）
                        kept_wt_path = wt_path
                        handed_off.add(wt_path)
                    elif error and "[provider-transient]" in error:
                        # fix-provider-transient-backoff（D3）：transient 终态失败保留现场
                        # 供下轮认领（替代 cleanup(success=False)）——复用遗产机制，
                        # 下轮经 _take_reusable_worktree 认领同一目录与分支继承现场。
                        # 非 transient 终态失败维持现行清理，避免真实缺陷现场被误续用。
                        self.worktree_manager.keep_for_reuse(
                            spec_name, wt_path, agent_type=agent_type)
                        kept_wt_path = wt_path
                        handed_off.add(wt_path)
                        self.logger.warning(
                            "agent_runner",
                            f"Transient terminal failure for '{spec_name}' — worktree "
                            f"{wt_path} kept for reuse (fix-provider-transient-backoff)",
                        )
                    else:
                        self.worktree_manager.cleanup(wt_path, success=False)
                    wt_path = None
                    if cancelled_flag:
                        break

        # All retries exhausted
        duration = time.time() - start_time
        # run 收尾（add-run-cancel D5）：清理取消旗标，防泄漏。
        # cancelled_flag 为 True 时（RunCancelledError 已 break 到此处）
        # 返回 cancelled=True 结果；否则走既有终态失败返回。
        self._cancel_clear(run_id)
        if cancelled_flag:
            return AgentRunResult(
                run_id, spec_name, agent_type,
                success=False, duration_seconds=duration,
                error=error,
                cancelled=True,
                provider_used=provider_name, model_used=model,
                worktree_path=kept_wt_path,
                worktree_kept=kept_wt_path is not None,
            )
        # add-cost-observability（D1）：终态失败也累加（末次 attempt 的 usage，
        # 异常早夭时为 0），保证预算告警在失败轮同样累计、不漏计。
        self._accumulate_token_usage(spec_name, usage_info)
        # 验证链侧车（D3）：终态失败的 planner run 同样逐轮追加
        self._record_verify_progress_tokens(spec_name, agent_type, usage_info)
        return AgentRunResult(
            run_id, spec_name, agent_type,
            success=False, duration_seconds=duration,
            error=f"All {max_retries} attempts failed. Last error: {error}",
            provider_used=provider_name, model_used=model,
            worktree_path=kept_wt_path,
            worktree_kept=kept_wt_path is not None,
        )

    # ── token 累计与预算告警（add-cost-observability D1 / D4）──────────────────












    def _run_claude(self, prompt: str, cwd: Path, run_id: str,
                    model_override: str | None = None,
                    env_overrides: Dict[str, str] | None = None,
                    resume_session_id: str | None = None,
                    max_turns: int | None = None,
                    spec_name: str | None = None,
                    agent_type: str | None = None) -> tuple:
        from core.config import ConfigLoader
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
                        etype = entry.get("type")
                        e_ts = AgentRunner._parse_event_timestamp(entry)
                        if etype == "tool_result":
                            if e_ts is not None:
                                latency_state["last_tool_result_ts"] = e_ts
                        elif etype == "assistant":
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
        # add-run-cancel D1/D3：轮询环每轮检查取消旗标，命中则
        # terminate→grace→kill→写 cancelled 终态行→抛 RunCancelledError
        base_run_id = self._normalize_run_id(run_id)
        cancel_error: RunCancelledError | None = None
        # add-planner-efficiency（run-latency-observability）：run 末延迟摘要文本。
        # 在 finally（读线程 join 后）计算并打日志；失败/取消路径把摘要拼入
        # error 上下文（卡死 vs 慢可判）。
        latency_summary_text = ""
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
                if max_turns and turn_count[0] >= max_turns:
                    proc.kill()
                    turn_limit_error = f"Max turns ({max_turns}) reached"
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
            append_run_error(run_file, timeout_error, returncode)
            raise RuntimeError(
                f"claude CLI {timeout_error}"
                + (f" | latency: {latency_summary_text}" if latency_summary_text else ""))

        if turn_limit_error is not None:
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
            self._daily_reset_date = today

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

    def _should_give_up_before_retry(self, spec_name: str, agent_type: str) -> bool:
        """attempt 重试前的放弃判定（fix-restart-dual-dispatch S3/S4）。

        2026-09-03 事故：双派发场景下 create 撞同名分支 fatal，attempt 循环
        sleep(5) 后换新时间戳重试成功 → 与第一梯队形成并行 run。重试前检查：
        - 锁活跃：另一个 run 已持 spec 锁，继续重试只会造出第二个并行 run；
        - 人工冻结：spec 被人为冻结（结构化 frozen 字段），自动重试必须让位。

        检查自身异常时 fail-open（返回 False）——判定故障不放大为 run 故障，
        既有重试语义保持可用。
        """
        try:
            if self.worktree_manager.has_active_lock(spec_name, agent_type):
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

    def _build_prompt(self, spec_name: str, agent_type: str, detail: dict | None = None,
                      wt_path: Path | None = None) -> str:
        return self._prompt_builder._build_prompt(
            spec_name, agent_type, detail, wt_path=wt_path)

    # ── planner 产物硬门（add-judge-artifact-gate D1）────────────────────

    def _check_agent_result_artifact(self, spec_name: str,
                                     agent_type: str) -> str | None:
        """planner 产物存在性硬门校验（fail-closed）。

        成功判定从「进程 exit 0」升级为「exit 0 **且**结果文件落盘且可解析」：
        - planner-judge 结果文件 = planner_result_path(..., "planner-judge")
          （.fenix-run-result.json）
        - planner-plan  结果文件 = planner_result_path(..., "planner-plan")
          （test_scenarios.json）
        路径与 prompt_builder 注入的 {result_path}/{scenarios_path} 同源计算，
        防双实现漂移。文件缺失 / 为空 / 非法 JSON 一律视为缺失（fail-closed）。

        Args:
            spec_name: spec 名（决定 verify-progress 子目录）。
            agent_type: 仅 planner-judge / planner-plan 有产物契约；其余返回 None。

        Returns:
            None = 通过；否则返回失败归因文案（含「结果文件缺失」语义，
            供 error 直用）。
        """
        if agent_type not in ("planner-judge", "planner-plan"):
            return None
        path = planner_result_path(self.project_root, spec_name, agent_type)
        try:
            if not path.is_file():
                return (f"exit 0 但结果文件缺失（{agent_type} 产物硬门）: {path}")
            if path.stat().st_size == 0:
                return (f"exit 0 但结果文件为空（{agent_type} 产物硬门）: {path}")
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            return (f"exit 0 但结果文件不可读（{agent_type} 产物硬门）: {path} ({e})")
        except json.JSONDecodeError as e:
            return (f"exit 0 但结果文件非法 JSON（{agent_type} 产物硬门）: {path} ({e})")
        return None

    def _build_legacy_section(self, spec_name: str) -> str:
        return self._prompt_builder._build_legacy_section(spec_name)

    def _legacy_dirty_snapshot(self, wt_path: str) -> str:
        return self._prompt_builder._legacy_dirty_snapshot(wt_path)

    def _scenario_freeze_section(self, spec_name: str) -> str:
        return self._prompt_builder._scenario_freeze_section(spec_name)

    def _interaction_contract_section(self, spec_name: str) -> str:
        return self._prompt_builder._interaction_contract_section(spec_name)

    def _triage_recheck_section(self, spec_name: str) -> str:
        return self._prompt_builder._triage_recheck_section(spec_name)

    def _verdict_rejection_section(self, spec_name: str) -> str:
        return self._prompt_builder._verdict_rejection_section(spec_name)

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

    @staticmethod
    def parse_api_error_status(error_text: str) -> Optional[int]:
        return ProviderCircuit.parse_api_error_status(error_text)

    @staticmethod
    def classify_switch_error(error_text: str) -> bool:
        return ProviderCircuit.classify_switch_error(error_text)

    @staticmethod
    def classify_transient_error(stderr_lines: list, exit_code: int,
                                 has_result: bool) -> bool:
        """瞬断判定转导（fix-provider-transient-backoff D2）——见
        ProviderCircuit.classify_transient_error（全量 stderr 信号，与降噪解耦）。"""
        return ProviderCircuit.classify_transient_error(stderr_lines, exit_code,
                                                        has_result)

    def _circuit_state(self, provider_name: str) -> dict:
        return self._provider_circuit._circuit_state(provider_name)

    def is_circuit_open(self, provider_name: str, now: float | None = None) -> bool:
        return self._provider_circuit.is_circuit_open(provider_name, now)

    def is_switch_cooldown(self, provider_name: str, now: float | None = None) -> bool:
        return self._provider_circuit.is_switch_cooldown(provider_name, now)

    def _record_switch_cooldown(self, provider_name: str, now: float | None = None) -> None:
        return self._provider_circuit._record_switch_cooldown(provider_name, now)

    def _write_provider_marker(self, run_id: str, spec_name: str, agent_type: str,
                               provider_name: str, model: str, chain_index: int,
                               chain_len: int) -> None:
        return self._provider_circuit._write_provider_marker(run_id, spec_name, agent_type, provider_name, model, chain_index, chain_len)

    def _record_daily_provider_attempt(self, provider_name: str) -> None:
        return self._provider_circuit._record_daily_provider_attempt(provider_name)

    def _circuit_open_error(self, provider_name: str, now: float | None = None) -> str:
        return self._provider_circuit._circuit_open_error(provider_name, now)

    def _record_provider_4xx(self, provider_name: str, code: int,
                             now: float | None = None) -> None:
        return self._provider_circuit._record_provider_4xx(provider_name, code, now)

    def _record_provider_probe(self, provider_name: str, success: bool,
                               now: float | None = None) -> None:
        return self._provider_circuit._record_provider_probe(provider_name, success, now)

    # ── 全局瞬断熔断转导（fix-provider-transient-backoff D4）──────────────────

    def record_transient_break(self, error_text: str) -> bool:
        """记录一次瞬断失败到全局指纹计数（D4）。返回 True = 首次触发熔断。"""
        return self._provider_circuit.record_transient_error(error_text)

    def is_global_transient_break_active(self, now: float | None = None) -> bool:
        """全局瞬断熔断是否生效（dispatch 闸门查询）。"""
        return self._provider_circuit.is_global_transient_break(now=now)

    def _accumulate_token_usage(self, spec_name: str, usage_info: dict) -> None:
        return self._token_accountant._accumulate_token_usage(spec_name, usage_info)

    def _check_token_budget(self, spec_name: str, tokens_in: int) -> None:
        return self._token_accountant._check_token_budget(spec_name, tokens_in)

    def _send_token_alert(self, spec_name: str, tokens_in: int, budget: float,
                          severity: str, title: str) -> None:
        return self._token_accountant._send_token_alert(spec_name, tokens_in, budget, severity, title)

    def _record_verify_progress_tokens(self, spec_name: str, agent_type: str,
                                         usage_info: dict) -> None:
        return self._token_accountant._record_verify_progress_tokens(spec_name, agent_type, usage_info)

    def _v2_ensure_state(self) -> None:
        return self._v2_server._v2_ensure_state()

    def _v2_launch_for_worktree(self, wt_path: Path) -> None:
        return self._v2_server._v2_launch_for_worktree(wt_path)

    def _v2_inject_env(self, wt_path: Path) -> Dict[str, str]:
        return self._v2_server._v2_inject_env(wt_path)

    def _v2_stop_for_worktree(self, wt_path: Path) -> None:
        return self._v2_server._v2_stop_for_worktree(wt_path)

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

    def _v2_stop_all(self) -> None:
        return self._v2_server._v2_stop_all()

    @property
    def provider_circuits(self):
        return self._provider_circuit.provider_circuits

    @provider_circuits.setter
    def provider_circuits(self, value):
        self._provider_circuit.provider_circuits = value

    @provider_circuits.deleter
    def provider_circuits(self):
        del self._provider_circuit.provider_circuits

    @property
    def _daily_provider_attempts(self):
        return self._provider_circuit._daily_provider_attempts

    @_daily_provider_attempts.setter
    def _daily_provider_attempts(self, value):
        self._provider_circuit._daily_provider_attempts = value

    @_daily_provider_attempts.deleter
    def _daily_provider_attempts(self):
        del self._provider_circuit._daily_provider_attempts

    @property
    def _daily_provider_warned(self):
        return self._provider_circuit._daily_provider_warned

    @_daily_provider_warned.setter
    def _daily_provider_warned(self, value):
        self._provider_circuit._daily_provider_warned = value

    @_daily_provider_warned.deleter
    def _daily_provider_warned(self):
        del self._provider_circuit._daily_provider_warned

    @property
    def _daily_reset_date(self):
        return self._provider_circuit._daily_reset_date

    @_daily_reset_date.setter
    def _daily_reset_date(self, value):
        self._provider_circuit._daily_reset_date = value

    @_daily_reset_date.deleter
    def _daily_reset_date(self):
        del self._provider_circuit._daily_reset_date

    @property
    def _v2_servers(self):
        return self._v2_server._v2_servers

    @_v2_servers.setter
    def _v2_servers(self, value):
        self._v2_server._v2_servers = value

    @_v2_servers.deleter
    def _v2_servers(self):
        del self._v2_server._v2_servers

    @property
    def _v2_used_ports(self):
        return self._v2_server._v2_used_ports

    @_v2_used_ports.setter
    def _v2_used_ports(self, value):
        self._v2_server._v2_used_ports = value

    @_v2_used_ports.deleter
    def _v2_used_ports(self):
        del self._v2_server._v2_used_ports

    @property
    def _v2_run_seq(self):
        return self._v2_server._v2_run_seq

    @_v2_run_seq.setter
    def _v2_run_seq(self, value):
        self._v2_server._v2_run_seq = value

    @_v2_run_seq.deleter
    def _v2_run_seq(self):
        del self._v2_server._v2_run_seq

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

    def has_live_attempt(self, spec_name: str) -> bool:
        return self._liveness.has_live_attempt(spec_name)

    def sweep_dangling_runs(self) -> list:
        return self._liveness.sweep_dangling_runs()

    def _pgrep_live_attempt(self, spec_name: str) -> bool:
        return self._liveness._pgrep_live_attempt(spec_name)

    def _stream_recent(self, spec_name: str, seconds: int) -> bool:
        return self._liveness._stream_recent(spec_name, seconds)

    def note_run_extension(self, spec_name: str, run_id: str,
                           extension_index: int, new_deadline: float) -> None:
        return self._liveness.note_run_extension(spec_name, run_id, extension_index, new_deadline)

    def get_extension_baseline(self, spec_name: str) -> float | None:
        return self._liveness.get_extension_baseline(spec_name)

    def _liveness_snapshot(self, run_file: Path, window_seconds: float,
                           now: float | None = None) -> dict:
        return self._liveness._liveness_snapshot(run_file, window_seconds, now)

    @staticmethod
    def _summarize_snapshot(snapshot: dict) -> str:
        return LivenessSupervisor._summarize_snapshot(snapshot)

    def _judge_liveness(self, snapshot: dict, spec_name: str | None,
                        run_id: str) -> dict:
        return self._liveness._judge_liveness(snapshot, spec_name, run_id)

    @staticmethod
    def _parse_verdict_json(text: str) -> dict | None:
        return LivenessSupervisor._parse_verdict_json(text)

    def _supervision_settings(self) -> dict:
        return self._liveness._supervision_settings()

    def _supervision_judge_timeout(self) -> float:
        return self._liveness._supervision_judge_timeout()

    def _supervision_deadline_action(self, run_file: Path, spec_name: str | None,
                                     run_id: str, started_at: float,
                                     extensions_used: int,
                                     judge=None, agent_type: str | None = None) -> dict:
        return self._liveness._supervision_deadline_action(
            run_file, spec_name, run_id, started_at, extensions_used, judge, agent_type)

    def wait_for_running_agents(self, timeout: int = AGENT_TERMINATE_GRACE_SECONDS):
        return self._liveness.wait_for_running_agents(timeout)

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

    @staticmethod
    def _resumable_session_id(
        session_id: str | None,
        session_provider: str | None,
        current_provider: str | None,
        reuse_worktree: bool,
    ) -> str | None:
        return SessionTracker._resumable_session_id(session_id, session_provider, current_provider, reuse_worktree)

    @staticmethod
    def _extract_session_id(run_file: Path) -> str | None:
        return SessionTracker._extract_session_id(run_file)

    @staticmethod
    def _extract_usage_info(result_event: dict | None) -> dict:
        return SessionTracker._extract_usage_info(result_event)

    @property
    def _extension_baselines(self):
        return self._liveness._extension_baselines

    @_extension_baselines.setter
    def _extension_baselines(self, value):
        self._liveness._extension_baselines = value

    @_extension_baselines.deleter
    def _extension_baselines(self):
        del self._liveness._extension_baselines

