"""
agent_runner.py — Agent execution engine for fenixd.

Spawns claude CLI subprocesses to run implementer and verifier Agents.
Handles result parsing, retry logic, and token/turn budget control.
"""

import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

# .fenix/runs/ 保留的最近运行产物数量上限（默认 20，见 D1 / spec agent-run-artifacts）
RUNS_KEEP = 20

# 无 provider 分配的 agent（含 Administrator）走默认网关（cc-switch）时 --model 用的
# 官方模型名。provider 已分配的 agent，其 --model 直接取该 agent 分配的网关模型名
# （model 字段，如 deepseek-v4-flash）——见 fenixd-sdk-model-routing：--model 即实际
# 发给网关的模型名，ANTHROPIC_MODEL 被 --model 覆盖不生效。本常量只作 fallback。
DEFAULT_GATEWAY_MODEL = "claude-sonnet-5"

# 优雅退出时对每个在跑 agent 的 SIGTERM 缓冲窗口（秒）。daemon 收到关闭信号后对所有
# 在跑 agent 发 SIGTERM，等此窗口让其收尾（关会话/flush 输出）；窗口结束仍未退出的
# 用 SIGKILL 兜底。取 claude 收尾所需量级，模块级常量便于测试注入短值。
# 见 spec agent-shutdown-interrupt：总关闭时长需压到 ≪ supervisor 60s SIGKILL 窗口。
AGENT_TERMINATE_GRACE_SECONDS = 10

# ── provider 熔断（fix-stashpop-deadlock：provider-fault-fuse） ──────────────
# 同一 provider 在滚动窗口内累计 HTTP 4xx（400/401/404）达阈值 → circuit_open，
# 冷却期内不再派发该 provider（直接失败、不启动 claude、不计入 spec 连续失败重试、
# 不触发状态机回退）。冷却结束后首个派发作半开探针，200 闭合、仍 4xx 重新冷却。
# 5xx/网络错误不计数（属瞬态，走既有 retry）。常量化便于调参，不落盘（见 design D3）。
PROVIDER_CIRCUIT_WINDOW_SECONDS = 300      # 滚动窗口 5 分钟
PROVIDER_CIRCUIT_THRESHOLD = 3             # 窗口内 4xx 达此次数 → 熔断
PROVIDER_CIRCUIT_COOLDOWN_SECONDS = 1800   # 冷却 30 分钟
# 计入熔断的 HTTP 4xx 状态码（401 与 400/404 一并计数：余额不足同样要防烧钱）
PROVIDER_CIRCUIT_4XX = (400, 401, 404)
# 半开探针成功判据：claude CLI 正常退出（视作网关 200）。解析不到 code 视为失败、不计数。
PROVIDER_CIRCUIT_PROBE_SUCCESS_CODE = 0

# ── provider 切换冷却（add-provider-failover：failover-dispatch） ──────────
# 与 4xx 熔断（provider-fault-fuse）独立的字段：切换类错误（unrecognized_model / 5xx /
# 网络错误）不计入 4xx 计数，而是把该 provider 推进到"switch 冷却"，链选择时跳过冷却中
# 候选；冷却到期主链自动复位优先（design D3：只触发链前进+短冷却，不永久拉黑）。
# 默认 300s，可配 pm.failover.switch_cooldown_seconds。
PROVIDER_SWITCH_COOLDOWN_SECONDS = 300
# 今日（2026-08-27）真实故障文本 fixture（inferaiapi / aliyun 各自拒绝 deepseek 变体）：
# claude CLI 经 SDK 包装时把 unrecognized_model 打到 stderr，形如下列；用于 classify_switch_error
# 文本匹配（design D2）。中央化便于日后新增网关报错形态。
SWITCH_ERROR_TEXT_PATTERNS = (
    r"unrecognized_model",
    r"unrecognized model",
    r"model.*not.*found",
)
# 连接类异常关键字（网络错误 / DNS / 超时 / 连接拒绝）——属瞬态，驱动链前进
SWITCH_ERROR_CONN_PATTERNS = (
    r"connection.*(refused|reset|error|timeout)",
    r"connect.*(refused|reset|error|timeout)",
    r"failed to connect",
    r"name or service not known",   # DNS 解析失败
    r"temporarily unavailable",
    r"network is unreachable",
)
# per-provider 当日 attempt 计数告警上限（design D5：防备备份 provider 悄悄烧贵）；
# 可配 pm.failover.daily_attempts_warn，默认 50。
PROVIDER_DAILY_ATTEMPTS_WARN = 50

# ── attempt 存活探测 / 超时活性监督（improve-run-lifecycle-governance）──────
# 进程扫描不可用时，run 流文件 mtime 在该窗口内视为 attempt 仍在活动（D4 回退判据）。
LIVE_ATTEMPT_STREAM_WINDOW_SECONDS = 120
# 超时监督默认值（D3）。单次续期 extension_seconds、次数上限 max_extensions、
# 总墙钟上限 absolute_max_seconds（命中即无条件终止，封闭续期的成本风险）、
# 活性判定窗口 judge_window（秒）。
SUPERVISION_DEFAULTS = {
    "enabled": True,
    "extension_seconds": 1800,
    "max_extensions": 2,
    "absolute_max_seconds": 7200,
    "judge_window": 600,
}
# 活性判定 LLM 单轮调用的超时秒数（D2）：judge 卡死不能拖住监督循环
JUDGE_TIMEOUT_SECONDS = 120
# 活性快照 last_output 片段截断字符数（D1）
LIVENESS_SNIPPET_CHARS = 400


class AgentRunResult:
    """Result of a single Agent run."""

    def __init__(self, run_id: str, spec_name: str, agent_type: str,
                 success: bool, duration_seconds: float,
                 turns_used: int = 0, error: str = None, output: str = "",
                 branch: str | None = None,
                 provider_used: str | None = None, model_used: str | None = None,
                 chain_exhausted: bool = False):
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


def append_run_line(run_file: Path, entry: dict) -> None:
    """向运行产物文件追加一行 JSON 并立即 flush，保证运行期间 Dashboard 可读。

    每行独立 open("a") + flush，两个读线程并发写入时依赖 O_APPEND 的原子性，
    避免长行被交错切碎。
    """
    with run_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()


def append_run_error(run_file: Path, error: str, exit_code: int) -> None:
    """异常/超时/kill 终止时向产物文件追加 error 终态行。"""
    append_run_line(run_file, {"type": "error", "error": error, "exit_code": exit_code})


def clean_old_runs(runs_dir: Path, keep: int = RUNS_KEEP, active_ids=None) -> int:
    """清理 .fenix/runs/ 中超出保留上限的最旧产物，跳过受保护的产物。

    Args:
        runs_dir: .fenix/runs/ 目录。
        keep: 保留的最近产物数量。
        active_ids: 不删除的 run_id 集合——既含仍在增长的活动产物，也含
            STATE.md 引用的历史产物（implementer_run/tester_run，清理时由
            data.cleanup_runs 传入），被引用的 run 是 spec 时间轴数据源。

    Returns: 删除的文件数。
    """
    if not runs_dir.is_dir():
        return 0
    active_ids = set(active_ids or ())
    try:
        candidates = [
            p for p in runs_dir.glob("*.jsonl")
            if p.stem not in active_ids
        ]
    except OSError:
        return 0
    # 按最近修改时间排序，旧的在前
    candidates.sort(key=lambda p: p.stat().st_mtime)
    removed = 0
    while len(candidates) > keep:
        victim = candidates.pop(0)
        try:
            victim.unlink()
            removed += 1
        except OSError:
            continue
    return removed


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

        self._running_agents: Dict[str, subprocess.Popen] = {}
        self._daily_run_count = 0
        self._daily_reset_date = datetime.now(timezone.utc).date()

        # add-provider-failover（design D5 / spec failover-dispatch 4.2）：per-provider
        # 当日 attempt 计数与单次告警标记。进程内存、按 UTC 日期滚动重置；超过
        # pm.failover.daily_attempts_warn（默认 50）时打 WARNING 且当日只告警一次。
        self._daily_provider_attempts: Dict[str, int] = {}
        self._daily_provider_warned: Dict[str, bool] = {}

        # provider 熔断状态（fix-stashpop-deadlock：provider-fault-fuse）。
        # 进程内存、不落盘（design D3）：{provider_name: {
        #   "code": int,            # 触发熔断的 HTTP 4xx code
        #   "events": [ts, ...],     # 滚动窗口内 4xx 时间戳（单调秒）
        #   "count": int,           # 窗口内 4xx 次数
        #   "open_since": float,     # 进入 open 的时间戳
        #   "cooldown_until": float, # 冷却到期时间戳
        #   "half_open": bool,       # 冷却到期后首个派发作为探针
        #   "switch_cooldown_until": float,  # add-provider-failover 切换类错误冷却到期
        # }}
        self.provider_circuits: Dict[str, dict] = {}

        # 超时监督续期基准注册表（improve-run-lifecycle-governance 3.2 / D3）：
        # {spec_name: {"baseline": epoch, "run_id": str, "extension": int,
        #              "deadline": epoch}}。agent_runner 每次超时续期时把 baseline
        # 顺延到续期时刻，pm_engine 的 stuck 检测读取该基准而非 STATE.md 的固定
        # updated 起点——否则刚被续期的长任务下一轮就被误判 stuck。
        # 无显式回收：get_extension_baseline 按流文件新鲜度自清理（run 结束后
        # 流停止增长即失效）。
        self._extension_baselines: Dict[str, dict] = {}

    # ── provider 熔断（fix-stashpop-deadlock：provider-fault-fuse） ──────────────

    @staticmethod
    def parse_api_error_status(error_text: str) -> Optional[int]:
        """从 claude CLI 错误输出解析网关返回的 HTTP 状态码（fix-stashpop-deadlock）。

        claude CLI 在 provider 网关 4xx 时把错误打到 stderr，典型形如
        ``HTTP 404`` / ``API error (404)`` / ``status code 401``；网关经 SDK 包装时
        也可能出现 ``unrecognized_model``（对应 404）等字样。这里只认明确解析出的数字
        状态码（design D4）；解析不到返回 None（视为非 4xx、不计数、探针失败也不计数——
        R2 防护：避免把偶发解析不出 code 的响应误判闭合）。

        返回 int 状态码；非 4xx（5xx/网络错误）返回 None。
        """
        if not error_text:
            return None
        # 顺序匹配：HTTP <code> / (404) / status code <code> / code <code>
        for pat in (r"HTTP\s+(\d{3})", r"\((\d{3})\)", r"status\s*code\s*[:=]?\s*(\d{3})",
                    r"\bcode\s*[:=]?\s*(\d{3})"):
            m = re.search(pat, error_text, re.IGNORECASE)
            if m:
                try:
                    code = int(m.group(1))
                except (TypeError, ValueError):
                    return None
                return code
        return None

    @staticmethod
    def classify_switch_error(error_text: str) -> bool:
        """判断错误文本是否属于「切换类错误」（add-provider-failover：design D2）。

        切换类错误驱动 failover 链前进：unrecognized_model 文本 / HTTP 5xx / 连接类异常。
        以下情形**不**返回 True（维持既有 4xx 熔断语义、不纳入链前进）：
        - HTTP 4xx（配额/鉴权，parsed code ∈ PROVIDER_CIRCUIT_4XX）——走 provider-fault-fuse
        - 空文本 / 解析不到 code 且不匹配任何切换文本

        返回 True 表示该 attempt 失败应以「链前进 + switch 短冷却」处理。

        Args:
            error_text: claude CLI 打到 stderr / 被 runner 转成 str 的错误文本。
        """
        if not error_text:
            return False
        text = error_text
        # 1) HTTP 5xx（5xx 属瞬态网关故障，驱动切换；5xx 的 code 解析不出也算失败但会被
        #    下方连接/文本兜底覆盖）。先排除明确 4xx（解析出的 4xx 不触发切换）。
        code = AgentRunner.parse_api_error_status(text)
        if code is not None:
            if code in PROVIDER_CIRCUIT_4XX:
                return False  # 4xx 配额/鉴权：交既有熔断，不切换
            if 500 <= code <= 599:
                return True  # 5xx：切换
        # 2) unrecognized_model 文本（今日真实故障：inferaiapi/aliyun 各自拒绝 deepseek 变体）
        for pat in SWITCH_ERROR_TEXT_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True
        # 3) 连接类异常（网络错误 / DNS / 超时 / 连接拒绝）——瞬态，切换
        for pat in SWITCH_ERROR_CONN_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False

    def _now(self) -> float:
        """单调时间戳（测试可覆写）。用 time.monotonic 避免时钟回拨影响窗口。"""
        return time.monotonic()

    def _circuit_state(self, provider_name: str) -> dict:
        """返回（惰性创建）某 provider 的熔断状态 dict。

        add-provider-failover：在既有 provider-fault-fuse 字段外新增 `switch_cooldown_until`
        （切换类错误冷却到期时间戳），与 4xx 熔断 `cooldown_until` 键隔离（design D3），
        避免两类计数互相污染。
        """
        st = self.provider_circuits.get(provider_name)
        if st is None:
            st = {
                "code": None,
                "events": [],
                "count": 0,
                "open_since": 0.0,
                "cooldown_until": 0.0,
                "half_open": False,
                "switch_cooldown_until": 0.0,  # 切换类错误冷却到期时间戳（add-provider-failover）
            }
            self.provider_circuits[provider_name] = st
        return st

    def is_circuit_open(self, provider_name: str, now: float | None = None) -> bool:
        """判断某 provider 当前是否处于熔断拦截态（open 且冷却未到期）。

        半开态（冷却到期、首个探针未发）仍视为 open（拦截并由首个派发当探针）。
        """
        if not provider_name:
            return False
        st = self.provider_circuits.get(provider_name)
        if st is None:
            return False
        now = self._now() if now is None else now
        return st["cooldown_until"] > now

    # ── provider 切换冷却（add-provider-failover：failover-dispatch） ──────────

    def is_switch_cooldown(self, provider_name: str, now: float | None = None) -> bool:
        """判断某 provider 当前是否处于「切换类冷却」态（链路选择跳过）。

        与 is_circuit_open 键隔离：仅由 classify_switch_error 触发的短冷却，不读 4xx 熔断
        的 cooldown_until。冷却到期后该 provider 自动复位、链选择优先复用（design D3）。
        """
        if not provider_name:
            return False
        st = self.provider_circuits.get(provider_name)
        if st is None:
            return False
        now = self._now() if now is None else now
        return st.get("switch_cooldown_until", 0.0) > now

    def _record_switch_cooldown(self, provider_name: str, now: float | None = None) -> None:
        """记录一次切换类错误：把该 provider 推进到 switch 短冷却（design D2/D3）。

        默认 300s（PROVIDER_SWITCH_COOLDOWN_SECONDS），可配 pm.failover.switch_cooldown_seconds。
        与 4xx 熔断计数完全独立：仅设置 switch_cooldown_until，不动 4xx 的 events/count/
        cooldown_until。冷却到期后链选择自动复位优先。
        """
        if not provider_name:
            return
        now = self._now() if now is None else now
        st = self._circuit_state(provider_name)
        cooldown = self._get_config("pm.failover.switch_cooldown_seconds",
                                    PROVIDER_SWITCH_COOLDOWN_SECONDS)
        st["switch_cooldown_until"] = now + cooldown
        self.logger.info(
            "agent_runner",
            f"Provider switch-cooldown for '{provider_name}' "
            f"(add-provider-failover) — {int(cooldown)}s, advance chain",
        )

    def _write_provider_marker(self, run_id: str, spec_name: str, agent_type: str,
                               provider_name: str, model: str, chain_index: int,
                               chain_len: int) -> None:
        """向 run jsonl 写入 provider_marker 行（design D5 / spec failover-dispatch「产物可追溯」）。

        在 attempt 启动、进程派发前写入，供 Dashboard / 事后审计确认本次 run 实际使用的
        provider/model 与链内下标；三件套摘要（baseurl/apikey 不落盘，仅记 provider 名）。
        """
        if not provider_name:
            return
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{run_id}.jsonl"
        try:
            append_run_line(run_file, {
                "type": "provider_marker",
                "spec": spec_name,
                "agent_type": agent_type,
                "provider": provider_name,
                "model": model,
                "chain_index": chain_index,
                "chain_len": chain_len,
            })
        except OSError:
            pass

    def _record_daily_provider_attempt(self, provider_name: str) -> None:
        """per-provider 当日 attempt 计数 + 单次 WARNING 告警（design D5 / spec 4.2）。

        按 UTC 日期滚动：跨天自动重置计数与告警标记。当日计数超
        pm.failover.daily_attempts_warn（默认 50）时打 WARNING，且当日只告警一次（防备
        备份 provider 悄悄烧贵）。进程内存、不落盘。
        """
        if not provider_name:
            return
        today = datetime.now(timezone.utc).date()
        if today != self._daily_reset_date:
            self._daily_provider_attempts = {}
            self._daily_provider_warned = {}
            self._daily_reset_date = today
        count = self._daily_provider_attempts.get(provider_name, 0) + 1
        self._daily_provider_attempts[provider_name] = count
        warn = self._get_config("pm.failover.daily_attempts_warn",
                                PROVIDER_DAILY_ATTEMPTS_WARN)
        if warn and count > warn and not self._daily_provider_warned.get(provider_name, False):
            self._daily_provider_warned[provider_name] = True
            self.logger.warning(
                "agent_runner",
                f"Provider '{provider_name}' daily attempts ({count}) exceeded "
                f"pm.failover.daily_attempts_warn ({warn}) — check for silent cost",
            )

    def _circuit_open_error(self, provider_name: str, now: float | None = None) -> str:
        """构造熔断拦截错误信息（design D5 / spec 故障可见性）。

        含 provider 名、HTTP code、次数与冷却剩余/到期信息，经 error → STATE.md /
        admin_monitor / dashboard 链路可见，便于区分「provider 故障」与「spec 自身问题」。
        """
        st = self.provider_circuits.get(provider_name) or {}
        now = self._now() if now is None else now
        code = st.get("code") or "?"
        count = st.get("count") or 0
        cooldown_until = st.get("cooldown_until") or 0.0
        remaining = max(0, int(cooldown_until - now))
        if remaining > 0:
            cooldown_info = f"cooldown {remaining}s remaining"
        else:
            cooldown_info = "cooldown expired (probing)"
        return (f"provider circuit open: {provider_name} "
                f"(HTTP {code} x {count}) — {cooldown_info}")

    def _record_provider_4xx(self, provider_name: str, code: int,
                             now: float | None = None) -> None:
        """记录一次 provider 网关 4xx，按滚动窗口计数，达阈值置 open。

        5xx / 网络错误不调用本方法（design D4）。窗口外的旧事件先滑出。
        """
        if not provider_name:
            return
        now = self._now() if now is None else now
        st = self._circuit_state(provider_name)
        window = self._get_config("agents.provider_circuit_window_seconds",
                                  PROVIDER_CIRCUIT_WINDOW_SECONDS)
        threshold = self._get_config("agents.provider_circuit_threshold",
                                     PROVIDER_CIRCUIT_THRESHOLD)
        cooldown = self._get_config("agents.provider_circuit_cooldown_seconds",
                                    PROVIDER_CIRCUIT_COOLDOWN_SECONDS)

        # 滑出滚动窗口外的旧事件
        st["events"] = [t for t in st["events"] if now - t <= window]
        st["events"].append(now)
        st["count"] = len(st["events"])
        st["code"] = code

        if st["count"] >= threshold:
            # 进入熔断（或重新进入冷却）。半开探针仍 4xx → 重新冷却，记录 open_since。
            st["open_since"] = now
            st["cooldown_until"] = now + cooldown
            st["half_open"] = False
            self.logger.error(
                "agent_runner",
                f"Provider circuit OPEN for '{provider_name}' "
                f"(HTTP {code} x{st['count']} within {int(window)}s), "
                f"cooldown {int(cooldown)}s — suppress dispatch until probe recovers",
            )

    def _record_provider_probe(self, provider_name: str, success: bool,
                               now: float | None = None) -> None:
        """半开探针结果：成功闭合（closed）、失败重新冷却（design D4/D5）。

        成功：清空计数、回到 closed。失败：重新进入冷却期（沿用上次 code），不进计数
        （避免探针失败被反复计数导致无限冷却；R2 防护：解析不出 code 的失败也不计数）。
        """
        if not provider_name:
            return
        st = self.provider_circuits.get(provider_name)
        if st is None:
            return
        now = self._now() if now is None else now
        cooldown = self._get_config("agents.provider_circuit_cooldown_seconds",
                                    PROVIDER_CIRCUIT_COOLDOWN_SECONDS)
        if success:
            self.logger.info(
                "agent_runner",
                f"Provider circuit CLOSED for '{provider_name}' — probe recovered",
            )
            # 回到 closed：清空窗口计数与冷却，但保留 code 信息供诊断
            st["events"] = []
            st["count"] = 0
            st["cooldown_until"] = 0.0
            st["open_since"] = 0.0
            st["half_open"] = False
        else:
            st["cooldown_until"] = now + cooldown
            st["half_open"] = False
            self.logger.warning(
                "agent_runner",
                f"Provider circuit re-cooled for '{provider_name}' — probe still failing, "
                f"cooldown {int(cooldown)}s",
            )

    def run_implementer(self, spec_name: str) -> AgentRunResult:
        """
        Run the implementer Agent for a SPEC.

        Steps:
        1. Create worktree
        2. Build claude prompt
        3. Execute via subprocess
        4. Parse result
        5. Clean up worktree
        6. Return result
        """
        run_id = f"impl-{spec_name}-{int(time.time())}"
        return self._execute_agent(spec_name, "implementer", run_id)

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
        return self._execute_agent(spec_name, f"planner-{mode}", run_id)

    def run_administrator(self, signal: dict) -> AdminDisposition:
        """唤起 Administrator Agent 处置困境信号（administrator-agent spec）。

        与 implementer/verifier 不同：Administrator 是运维角色，直接在 main 树
        （project_root）操作框架，不创建 worktree（design D4）。产物写入
        .fenix/runs/admin-<spec>-<ts>.jsonl；处置结果从管理员按 prompt 写入的
        .fenix/admin_disposition.json 读取，由 daemon 落盘到 admin_alerts.json。

        Args:
            signal: admin_monitor 检测到的困境信号 dict
                （signal_type/spec/severity/description/evidence/recommended_action）。
        """
        spec = signal.get("spec") or "global"
        run_id = f"admin-{spec}-{int(time.time())}"
        prompt = self._build_prompt(spec, "administrator", detail=signal)

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
        else:
            model_override = self._get_admin_model()

        # fix-admin-self-heal：唤起前先落 pending disposition，保证即使 admin 被
        # kill（如 daemon 重启/崩溃）也有记录可回溯；monitor 会检测无最终结果的
        # pending 并升级人工，避免「admin 死了但没有任何告警」。
        try:
            from .admin_store import AdminStore, DISPOSITION
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

        self._clear_admin_disposition()
        try:
            output, turns, _session_id = self._run_claude(
                prompt, self.project_root, run_id, model_override, env_overrides,
                max_turns=self._get_config("agents.max_turns", 300),
                spec_name=spec,
            )
            success = True
            error = ""
        except Exception as e:
            output = ""
            success = False
            error = str(e)

        disp = self._read_admin_disposition()
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

    def _clear_admin_disposition(self):
        """清空上次的处置记录，避免运行失败时读到陈旧数据。"""
        disp_path = self.project_root / ".fenix" / "admin_disposition.json"
        try:
            if disp_path.exists():
                disp_path.unlink()
        except OSError:
            pass

    def _read_admin_disposition(self) -> dict:
        """读取管理员按 prompt 写入的处置记录 .fenix/admin_disposition.json。

        文件缺失/损坏返回空 dict（调用方用信号详情兜底）。
        """
        disp_path = self.project_root / ".fenix" / "admin_disposition.json"
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

    def _execute_agent(self, spec_name: str, agent_type: str, run_id: str) -> AgentRunResult:
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
          后续 attempt 自动前进到下一候选并 --resume 原会话；4xx 配额类维持既有熔断不前进。
        - 全链冷却 → 直接失败返回（chain_exhausted，不启动进程、不消耗 spec 重试）。
        - 切换后 CLAUDE_CONFIG_DIR 隔离目录随候选同步切换；run jsonl 写 provider_marker；
          AgentRunResult 带 provider_used/model_used；每 provider 当日计数超阈值告警。
        """
        max_retries = self._get_config("agents.max_retries", 3)
        start_time = time.time()
        wt_path = None
        session_id = None
        # 实例级链指针（design D1：cursor 按 agent_type 记忆）。-1 表示尚未选定。
        chain_cursor = -1
        last_provider_used = None  # 用于 "provider switched" 跨 attempt 打点
        self._last_model_used = None  # 用于 model_changed 日志留痕（design D3）

        for attempt in range(1, max_retries + 1):
            attempt_run_id = f"{run_id}-a{attempt}"
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

            reuse_worktree = (agent_type == "implementer" and wt_path is not None)

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
                        continue
                    return AgentRunResult(
                        attempt_run_id, spec_name, agent_type,
                        success=False, duration_seconds=time.time() - start_time,
                        error=error_msg, provider_used=provider_name, model_used=model,
                    )
            else:
                self.logger.info(
                    "agent_runner",
                    f"Reusing worktree {wt_path} for '{spec_name}' (attempt {attempt}, resume)",
                )

            # ── 观测：run jsonl 写 provider_marker（design D5 / spec failover-dispatch） ──
            # attempt 启动时写入，指明所用 provider/model 与链内下标，事后可追溯实际网关。
            if provider_name is not None:
                self._write_provider_marker(
                    attempt_run_id, spec_name, agent_type,
                    provider_name, model, chain_cursor, len(chain),
                )

            # Build and execute the prompt
            try:
                prompt = self._build_prompt(spec_name, agent_type)
                env_overrides: Dict[str, str] = {}
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
                output, turns, run_session_id = self._run_claude(
                    prompt, wt_path, attempt_run_id, model_override, env_overrides,
                    resume_session_id=session_id if reuse_worktree else None,
                    max_turns=self._get_config("agents.max_turns", 300),
                    spec_name=spec_name,
                )
                if run_session_id:
                    session_id = run_session_id
                success = True
                error = None
            except Exception as e:
                output = ""
                turns = 0
                success = False
                error = str(e)
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
                    # add-provider-failover（design D2/D3）：切换类错误 → 该 provider 进入
                    # switch 短冷却，同 run 后续 attempt 前进到下一候选并 resume 原会话。
                    # 4xx 配额/鉴权类不触发（维持既有熔断语义、链指针不动）。
                    elif self.classify_switch_error(error):
                        self._record_switch_cooldown(provider_name)
                        # 仅当链上还有后续候选才前进指针；否则保持当前（全链耗尽将在下一
                        # attempt 的 _select_chain_candidate 中判定为 chain_exhausted）。
                        if chain_cursor + 1 < len(chain):
                            chain_cursor += 1
                # implementer 失败后从产物尾部提取 session_id，供下一次 attempt --resume 续跑
                if agent_type == "implementer":
                    run_file = self.project_root / ".fenix" / "runs" / f"{attempt_run_id}.jsonl"
                    sid = self._extract_session_id(run_file)
                    if sid:
                        session_id = sid

            # 记录分支名（在 cleanup 之前，cleanup 会从 _wt_branches 中移除）
            branch = self.worktree_manager.get_branch_name(wt_path) if success else None

            # 成功时，把 worktree 中的 .fenix-run-result.json 复制到主树。
            if success:
                wt_result = wt_path / ".fenix-run-result.json"
                root_result = self.project_root / ".fenix-run-result.json"
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
                # 成功：清理 worktree（保留分支供 merge-back），返回结果
                self.worktree_manager.cleanup(wt_path, success=True)
                duration = time.time() - start_time
                self._daily_run_count += 1
                self.logger.info(
                    "agent_runner",
                    f"{agent_type} succeeded for '{spec_name}'",
                    {"run_id": attempt_run_id, "attempt": attempt, "turns": turns,
                     "provider": provider_name, "model": model},
                )
                return AgentRunResult(
                    attempt_run_id, spec_name, agent_type,
                    success=True, duration_seconds=duration,
                    turns_used=turns, output=output,
                    branch=branch, provider_used=provider_name, model_used=model,
                )
            else:
                self.logger.warning(
                    "agent_runner",
                    f"{agent_type} failed for '{spec_name}' (attempt {attempt})",
                    {"run_id": attempt_run_id, "error": error, "provider": provider_name},
                )
                # 失败后的 worktree 处理：
                # - implementer 且还有重试：保留 worktree，下次 attempt 用 --resume 续跑
                # - 其他：清理 worktree 并删除分支，下次 attempt 全新创建
                if attempt < max_retries:
                    time.sleep(10)  # Wait before retry
                    if agent_type != "implementer":
                        self.worktree_manager.cleanup(wt_path, success=False)
                        wt_path = None
                else:
                    self.worktree_manager.cleanup(wt_path, success=False)
                    wt_path = None

        # All retries exhausted
        duration = time.time() - start_time
        return AgentRunResult(
            run_id, spec_name, agent_type,
            success=False, duration_seconds=duration,
            error=f"All {max_retries} attempts failed. Last error: {error}",
            provider_used=provider_name, model_used=model,
        )

    def _build_prompt(self, spec_name: str, agent_type: str, detail: dict | None = None) -> str:
        """Build the claude CLI prompt for the Agent.

        detail: 可选。administrator 分支接收困境信号 dict。
        """
        spec_dir = f"openspec/changes/{spec_name}"

        if agent_type == "implementer":
            return (
                f"You are the Fenix Implementer Agent. Your job is to implement the SPEC "
                f"located at {spec_dir}/.\n\n"
                f"1. Read {spec_dir}/proposal.md, {spec_dir}/design.md, and {spec_dir}/specs/\\*.md "
                f"to understand what needs to be built.\n"
                f"2. Read {spec_dir}/tasks.md and identify the next unchecked task.\n"
                f"3. Implement that task. Write actual production code, not stubs.\n"
                f"4. Run the project's tests after implementation. Fix any failures.\n"
                f"5. Commit your changes with message: [fenix] {spec_name}: <task description>\n"
                f"6. Mark the task as complete in tasks.md (- [x])\n"
                f"7. If all tasks are done, write a file .fenix-run-result.json with: "
                f'{{"status": "success", "spec": "{spec_name}", "summary": "<brief summary>"}}\n'
                f"8. If you encounter an error you cannot fix after 3 attempts, write "
                f".fenix-run-result.json with: "
                f'{{"status": "error", "spec": "{spec_name}", "error": "<description>"}}\n\n'
                f"IMPORTANT: Do NOT modify STATE.md directly. The daemon handles that."
            )
        elif agent_type == "verifier":
            progress_path = self.project_root / ".fenix" / "verify-progress" / f"{spec_name}.json"
            # 结构化报告（与 verify_engine 产物同位置，Dashboard 场景/缺陷列表数据源）
            report_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / "report.json"
            )
            # 断点续跑（verifier-checkpoint-resume spec）：读取上次 attempt 的进度文件，
            # 存在且 done>0 时把断点信息注入提示词，让新 agent 从 done+1 场景继续，
            # 不再从头重跑。文件缺失 / done==0 / JSON 损坏 → 不注入、全新开始，损坏文件
            # 移除以免污染后续 attempt。
            breakpoint_section = ""
            progress = self._read_verify_progress(spec_name)
            if progress is not None:
                total = progress.get("total")
                done = progress.get("done") or 0
                current = progress.get("current") or ""
                if isinstance(done, int) and done > 0:
                    initial_done = done
                    start_scenario = done + 1
                    breakpoint_section = (
                        f"\n⚠️ RESUME CHECKPOINT (断点续跑) — 你是从上次中断处续跑的验证 Agent。\n"
                        f"上次验证进度：total={total}, done={done}, 上次进行中的场景: '{current}'\n"
                        f"指令：\n"
                        f"  1. 跳过已完成的 {done} 个场景，从第 {start_scenario} 个场景开始执行\n"
                        f"     （场景总数保持 {total} 不变，不要重新数；已完成的场景视为已通过）。\n"
                        f"  2. 首次写入进度时直接写 done={initial_done}（不要重置为 0），"
                        f"之后每完成一个场景将 done 递增 1 并更新 current。\n"
                        f"  3. 直至 done 达到 {total}，写入 done={total} 与最终结果。\n"
                        f"  4. 不要重复执行已完成场景的截图/报告，但需确保本次从断点起的场景全部真实在\n"
                        f"     浏览器中跑通（DOM snapshot 文本验证）。\n\n"
                    )
            return (
                f"You are the Fenix Verifier Agent. Independently verify the SPEC at {spec_dir}/.\n\n"
                f"CRITICAL: You MUST test in a REAL browser/user environment.\n"
                f"Code analysis alone = INCOMPLETE = FAILURE. Use playwright-cli for web projects.\n\n"
                f"WORKFLOW — write progress to {progress_path} at EVERY step:\n"
                f"  Step 0: Write done=0, current='初始化: 读取SPEC'\n"
                f"  Step 1: Read specs, count scenarios. Write total=N.\n"
                f"  Step 2: Build and START the project in its real runtime.\n"
                f"    Web: npm run dev, open in browser via playwright-cli.\n"
                f"    Extension: npm run build, load in Chrome (if possible) or npm run dev.\n"
                f"  Step 3: MANDATORY click-through UI regression test — test EVERY panel:\n"
                f"    - Quick Links: CLICK '+', fill form, SUBMIT → verify new link appears in grid\n"
                f"    - Notes: CLICK '+', type note, SAVE → verify note appears in list\n"
                f"    - Stock: TYPE 'sh600036', CLICK 'add' → verify stock appears in list\n"
                f"    - Calculator: TYPE '2+3', ENTER → verify '5' result is visible and readable\n"
                f"    - Email: CLICK settings, add account → verify form works\n"
                f"    After EACH interaction, TAKE SCREENSHOT as evidence.\n"
                f"    If any button click produces NO visible result = BLOCKING BUG.\n"
                f"  Step 4: Test scenarios ONE BY ONE as a REAL USER.\n"
                f"    USE PLAYWRIGHT-CLI: navigate, click, type, scroll, take screenshots.\n"
                f"    After EACH scenario, increment done and write progress.\n"
                f"    Format: {{\"total\": N, \"done\": D, \"current\": \"scenario description\"}}\n"
                f"  Step 4: Test edge cases (empty input, long input, resize, rapid clicks).\n"
                f"  Step 5: Write {spec_dir}/verification-report.md with screenshots.\n"
                f"    Also write {report_path} — structured report.json（Dashboard 的\n"
                f"    场景/缺陷列表数据源，全部场景执行完毕后一次写入，MUST exist before\n"
                f"    you finish）:\n"
                f"    {{\n"
                f'      "spec": "{spec_name}",\n'
                f'      "timestamp": "<ISO8601 当前时间>",\n'
                f'      "summary": {{"total": N, "passed": P, "warnings": W, "failed": F, "errors": E}},\n'
                f'      "scenarios": [\n'
                f'        {{"scenario_id": "s1", "description": "场景描述",\n'
                f'          "status": "pass | fail | error | warning",\n'
                f'          "assertion_results": [{{"type": "step", "pass": true, "message": ""}}],\n'
                f'          "screenshots": ["/绝对路径/证据截图.png"]}}\n'
                f"      ]\n"
                f"    }}\n"
                f"    status 判定: pass=全部断言与步骤通过; fail=断言/步骤失败(产品缺陷);\n"
                f"    error=不可测或环境故障(非产品缺陷); warning=仅视觉或第4层断言差异。\n"
                f"    每个真实执行的场景都必须出现在 scenarios；summary 计数与 scenarios 一致；\n"
                f"    fail/error 场景在 assertion_results 中给出未通过断言（含凭证 message）。\n"
                f"  Step 6: All pass → write .fenix-run-result.json: "
                f'{{"status":"verified","spec":"{spec_name}","bugs":[]}}\n'
                f"  Step 7: Bugs found → write .fenix-run-result.json: "
                f'{{"status":"bug-found","spec":"{spec_name}","bugs":[...]}}\n\n'
                f"  Step 8: CLEANUP — 验证结果已写出后，主动清理本次验证创建的临时资源，"
                f"不要留给用户打扫:\n"
                f"    - 删除自己为本次验证复制/创建的 mock、临时或测试项目目录"
                f"（如 /tmp/fenix-verify-*、/tmp/verify-* 等本次新建的目录）\n"
                f"    - 终止自己为本次验证启动的 mock/辅助服务器进程\n"
                f"    - 删除自己创建的临时脚本与临时产物文件\n"
                f"    - 保留：verification-report.md、{report_path}、.fenix-run-result.json、"
                f"{progress_path}，以及 verify worktree 自身\n"
                f"    - 禁止删除被测项目内的任何文件（含 worktree 内的报告与结果文件）\n"
                f"    - 清理失败或文件被占用时跳过即可，不得阻塞结果上报、不得误删项目文件\n\n"
                f"MANDATORY: Write progress after EVERY step and EVERY scenario.\n"
                f"MANDATORY: Use playwright-cli for browser testing. NO shortcuts.\n"
                f"MANDATORY: If you cannot start the REAL project, report it as a failure.\n"
                f"IMPORTANT: Do NOT Read image/screenshot files (.png/.jpg) — 当前模型不支持图像输入，"
                f"读图会被 hook 拦截；截图仅作为证据文件保存到报告，验证用 DOM snapshot 文本。\n"
                f"IMPORTANT: Do NOT modify STATE.md."
                f"{breakpoint_section}"
            )

        elif agent_type == "planner-plan":
            scenarios_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            result_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            return (
                f"你是 Fenix Planner Agent。你的任务是将 SPEC 文档转化为结构化的浏览器测试场景。\n\n"
                f"## 步骤\n"
                f"1. 读取 {spec_dir}/proposal.md, {spec_dir}/design.md, {spec_dir}/specs/*.md\n"
                f"2. 分析所有功能点，为每个功能生成至少一个测试场景\n"
                f"3. 将生成的场景保存到 {scenarios_path}\n"
                f"4. 将运行结果写入 {result_path}（绝对路径，与场景文件同目录，"
                f"不要写别处）："
                f'{{"status":"plan-ready","spec":"{spec_name}"}}\n\n'
                f"## 场景覆盖规则\n"
                f"- 功能正向路径：每个SPEC功能点的完整操作流程\n"
                f"- 异常路径：空输入、超长输入、特殊字符\n"
                f"- 交互流程：多步骤操作序列，验证中间状态\n"
                f"- 回归点：操作后状态与操作前对比\n"
                f"- 空状态：列表/面板在无数据时的显示\n"
                f"- 删除/撤销：删除操作后的状态验证\n\n"
                f"## 真实云端端到端场景（同步/云端/数据隔离相关 SPEC 必须）\n"
                f"- 对「同步 / 云端存储 / 上传下载 / 数据加密 / 数据隔离」相关 SPEC，"
                f"必须生成至少一个「真实创建用户 → 解锁 → 点击下载」的端到端场景，"
                f"触发真实云端请求（腾讯云 COS）。\n"
                f"- 这类场景用 no_auth_error 断言「无签名/认证错误」，用于捕获"
                f"数据加解密/签名正确性 bug（纯 UI 断言无法覆盖）。\n"
                f"- 约束：只做「下载」（读取云端，安全），不做「上传」（避免污染真实云端数据）。\n"
                f"- 示例步骤：seed 清空用户与同步键 → 创建用户（密码 test-password-123）→ "
                f"解锁 → 点击「下载云端数据」→ 断言 no_auth_error。\n\n"
                f"## 选择器规范\n"
                f"- 优先使用 data-testid 属性\n"
                f"- 其次使用语义选择器：button[name=\"提交\"], input[placeholder=\"搜索\"]\n"
                f"- 避免使用：CSS类名、第n个子元素、绝对路径\n\n"
                f"## navigate URL 规范（验收硬约束，违反即退回 plan）\n"
                f"- fenixd 是通用软件开发框架，被测应用可能是任何软件：navigate 路径"
                f"**必须来自被测应用的真实源码**，不得臆测。生成场景前先阅读被测应用的"
                f"路由/入口定义代码（服务端路由表、页面注册、框架路由配置等——不同"
                f"框架形式不同），确认每个目标路径真实存在，并在场景 description 末尾"
                f"标注出处（文件:行号）供审计。\n"
                f"- navigate 步骤的 value 必须是**绝对 URL**：http:// 或 https:// 开头，"
                f"含主机与端口（主机与端口以验证运行实例实际启动的为准，路径来自源码证据）。\n"
                f"- 相对路径（如 \"/dashboard\"）或源码中查无出处的路径会被拒收。\n"
                f"- 若 {scenarios_path} 同目录存在 REPLAN_FEEDBACK.md，必须先读取："
                f"那是上一轮场景未通过验收的反馈，逐条修正后重新输出全部场景。\n\n"
                f"## 断言规范（每个场景至少包含）\n"
                f"- 1个 element_visible（操作结果可见）\n"
                f"- 如涉及点击：1个 no_click_interception（点击不被拦截）\n"
                f"- 如涉及输入：1个 text_match（输入内容正确）\n"
                f"- 如涉及表单：1个 element_enabled（提交按钮状态正确）\n\n"
                f"## 对话框处理（window.confirm/alert/prompt）\n"
                f"- 点击若触发 window.confirm 等浏览器对话框，必须显式处理，否则被默认 dismiss 会误判：\n"
                f"  - 确认场景：在触发对话框的 click 步骤加 \"dialog\": \"accept\"，"
                f"或在 click 前加一步 {{\"action\": \"dialog\", \"value\": \"accept\"}}\n"
                f"  - 取消场景：同理用 \"dismiss\"\n"
                f"- 示例：{{\"action\": \"click\", \"target\": \".user-chip\", "
                f"\"dialog\": \"accept\", \"description\": \"点击切换并确认\"}}\n\n"
                f"## no_click_interception 时机规范\n"
                f"- 只在「即将点击某元素」前断言该元素不被遮挡；一旦打开 modal/overlay，"
                f"其覆盖的底层按钮被遮挡是正常交互，不得再对其断言 no_click_interception。\n\n"
                f"## 弹窗/对话框关闭后的断言规范（时序）\n"
                f"- 若某操作（如点击「保存」「取消」）会关闭弹窗/对话框，则关闭之后"
                f"弹窗内元素已从 DOM 移除，**不得再断言弹窗内元素**（如输入框的值）。\n"
                f"- 应改为断言弹窗外持久 DOM 的交互结果（如面板主体区的文本/元素），"
                f"或在触发关闭的操作**之前**断言弹窗内输入框的值。\n"
                f"- 示例：输入地点 → 点「保存」（弹窗关闭）→ 断言面板天气区文本，"
                f"而非断言弹窗内输入框。\n\n"
                f"## seed 数据规范\n"
                f"- seed 写入的 localStorage 值必须是目标键的合法格式：base64 键"
                f"（如 fenix:sync:persisted-key）必须使用合法 base64，不得使用 "
                f"\"some-base64-key\" 这类占位符。\n\n"
                f"## 输出JSON格式\n"
                f'[\n'
                f'  {{\n'
                f'    "id": "kebab-case-unique-id",\n'
                f'    "description": "中文场景描述",\n'
                f'    "depends_on": ["前置场景ID"],\n'
                f'    "steps": [\n'
                f'      {{"action": "navigate", "value": "https://..."}},\n'
                f'      {{"action": "click", "target": "[data-testid=\'add-btn\']", "description": "点击添加按钮"}},\n'
                f'      {{"action": "type", "target": "[data-testid=\'title-input\']", "value": "测试标题"}},\n'
                f'      {{"action": "click", "target": "[data-testid=\'submit-btn\']", "description": "提交表单"}}\n'
                f'    ],\n'
                f'    "assertions": [\n'
                f'      {{"type": "element_visible", "selector": ".result-item", "label": "新增项可见"}},\n'
                f'      {{"type": "text_match", "selector": ".result-item .title", "expected": "测试标题"}},\n'
                f'      {{"type": "no_click_interception", "selector": "[data-testid=\'add-btn\']"}},\n'
                f'      {{"type": "no_console_error"}}\n'
                f'    ],\n'
                f'    "visual_baseline": "scenario_id_baseline"\n'
                f'  }}\n'
                f']\n\n'
                f"支持的断言类型: element_visible, element_count, element_not_exist, "
                f"element_focused, element_enabled, no_click_interception, no_overlap, "
                f"in_viewport, z_index_order, text_match, text_contains, attribute_match, "
                f"no_console_error, no_network_error, no_auth_error, dom_structure, no_overflow, alignment\n\n"
                f"支持的操作类型: navigate, click, type, clear, select, scroll, wait, dialog, seed, mock_api\n"
                f"（click 步骤可携带 \"dialog\": \"accept\" | \"dismiss\" 处理浏览器对话框）\n"
                f"## 外部 API 场景规范（真实网络请求 / mock）\n"
                f"- 涉及外部 API 真实请求的场景（如 open-meteo 天气、时间服务器），在场景 JSON "
                f"顶层声明 \"external_net_errors_ok\": true，表示允许 no_console_error 过滤 "
                f"net::ERR_ 等网络层错误（测试环境不可达属环境因素，非产品缺陷）；"
                f"签名/认证类错误仍严格失败。\n"
                f"- 若需离线完整验证外部 API 请求→解析→渲染链路，可在场景 steps 中加入 "
                f"mock_api 步骤：{{\"action\": \"mock_api\", \"target\": \"https://api.open-meteo.com/**\", "
                f"\"value\": \"{{\\\"current\\\": ...}}\"}}（target 为 URL 模式，value 为 JSON 响应体；"
                f"注意 Playwright glob 中 `*` 不匹配 `/`，多段路径需用 `**`，引擎会自动把结尾 "
                f"`/*` 补成 `/**`）。mock 注册在 page 上，reload/导航后仍保留；仅作用于当前场景。\n\n"
                f"IMPORTANT: 当前模型不支持图像输入——不要 Read 图片/截图文件（会被 hook 拦截），"
                f"截图仅作为证据文件。\n"
                f"IMPORTANT: Do NOT modify STATE.md."
            )

        elif agent_type == "planner-judge":
            report_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / "report.json"
            )
            result_path = (
                self.project_root / ".fenix" / "verify-progress"
                / spec_name / ".fenix-run-result.json"
            )
            return (
                f"你是 Fenix Planner Agent。你的任务是分析验证引擎的测试报告，判定验证是否通过。\n\n"
                f"## 步骤\n"
                f"1. 读取 {report_path}\n"
                f"2. 按照判定规则分析每个断言结果\n"
                f"3. 聚合同类型失败，避免重复报告\n"
                f"4. 将运行结果写入 {result_path}（绝对路径，与场景/报告文件同目录，"
                f"不要写别处）\n"
                f"5. 写入 {spec_dir}/verification-report.md（人类可读的验证报告）\n\n"
                f"## 判定规则\n\n"
                f"### 第1-2层断言失败 → 一定是Bug\n"
                f"元素不存在、不可见、点击被拦截、重叠等。直接记录，不需要额外判断。\n\n"
                f"### 第3层断言失败 → 大概率是Bug\n"
                f"文字不匹配、属性错误、DOM结构错误。除非有明显理由（如SPEC允许动态内容），否则记为Bug。\n\n"
                f"### no_auth_error 特判（真实云端端到端场景）\n"
                f"- 出现「签名验证失败」「InvalidAccessKeyId」「SignatureDoesNotMatch」等"
                f"密钥/签名错误 → 产品 Bug（密钥派生或加解密正确性问题）。\n"
                f"- 仅网络不可达（超时、连接失败、DNS 错误），且无上述密钥/签名关键词 → "
                f"环境问题，不记为产品 Bug，报告中标注「网络环境不可达，无法验证」。\n\n"
                f"### no_console_error 外部 API 网络错误特判\n"
                f"- 断言结果含 `filtered_network` 字段且 `errors` 为空 → 该断言通过："
                f"涉及外部 API 的场景已声明豁免，net::ERR_ 等网络层错误按环境因素过滤，"
                f"不记为 Bug。\n\n"
                f"### 断言时序特判（弹窗/对话框关闭后查询弹窗内元素）\n"
                f"- 断言失败原因为「元素随弹窗/对话框关闭而从 DOM 移除」（如 Locator 超时、"
                f"evaluate 找不到节点），且同场景其他功能性断言通过 → 判为断言时序问题"
                f"（测试场景设计缺陷），不记为产品 Bug；报告中标注「断言时序问题：应在"
                f"交互前校验或改断言弹窗外持久 DOM」。\n"
                f"- 典型模式：点击「保存」后弹窗立即关闭，后续仍断言弹窗内输入框的值。\n\n"
                f"### 第4层断言失败 → 需结合上下文\n"
                f"- SSIM低于阈值：检查是否为动态内容区域（时间戳/随机推荐）。是→忽略，不是→Bug。\n"
                f"- 元素溢出：检查是否在预期视口尺寸内。是→忽略，不是→Bug。\n\n"
                f"### 聚合规则\n"
                f"- 同一场景同一类型的失败 → 合并为1个Bug\n"
                f"- 同一元素在多个场景中同一类失败 → 标记为\"系统性问题\"\n"
                f"- 3个以上场景出现相同root cause → 只报1个Bug，标注影响范围\n\n"
                f"### .fenix-run-result.json 格式\n"
                f'{{\n'
                f'  "status": "verified" | "bug-found",\n'
                f'  "bugs": [\n'
                f'    {{\n'
                f'      "severity": "critical" | "major" | "minor",\n'
                f'      "scenario_ids": ["场景ID列表"],\n'
                f'      "assertion_type": "断言类型",\n'
                f'      "description": "Bug的清晰中文描述",\n'
                f'      "root_cause": "推断的根因",\n'
                f'      "evidence": {{...}}\n'
                f'    }}\n'
                f'  ],\n'
                f'  "summary": "验证总结"\n'
                f'}}\n\n'
                f"IMPORTANT: Do NOT modify STATE.md."
            )

        elif agent_type == "administrator":
            sig = detail or {}
            sig_spec = sig.get("spec") or spec_name
            sig_type = sig.get("signal_type") or "unknown"
            severity = sig.get("severity") or "major"
            description = sig.get("description") or ""
            evidence = sig.get("evidence") or ""
            recommendation = sig.get("recommended_action") or ""
            dash_script = f"{self.project_root}/.fenix/bin/fenix_dashboard.py"
            return (
                f"You are the Fenix Administrator Agent — 运维角色，"
                f"负责处置 Agent 无法自行脱困的困境。\n\n"
                f"## 困境信号\n"
                f"- 类型: {sig_type}\n"
                f"- spec: {sig_spec}\n"
                f"- 严重度: {severity}\n"
                f"- 描述: {description}\n"
                f"- 证据: {evidence}\n"
                f"- 建议处置: {recommendation}\n\n"
                f"## 你的高级权限（自主处置，无需询问）\n"
                f"- 杀死进行中的 Agent 子进程（先 ps 确认归属再操作）\n"
                f"- 需要重启 fenixd 时：写 .fenix/restart_request 文件（内容随意），"
                f"supervisor 会负责重启；【不要】直接 kill daemon——daemon 是你的宿主进程，"
                f"kill 它会连带杀死你，导致重启和处置记录都丢失\n"
                f"- git 清理：worktree prune / stash / reset / commit / 分支管理\n"
                f"- 直接修改 Fenixd 自身代码（当前已在主树）并提交\n"
                f"- 发起新的 SPEC（创建 openspec/changes/<name>/ 并更新 STATE.md）\n"
                f"- 重置/修复 spec 状态（将卡死 spec 更新为 ready/blocked 并清空陈旧字段）\n"
                f"- 运维跨项目 Dashboard 服务（见下方运维手册）\n"
                f"- 修正错误的验证基础设施文件：检查并修复 "
                f".fenix/verify-progress/<spec>/test_scenarios.json 的协议/URL/断言等"
                f"基础设施性错误（如 https 访问纯 HTTP 服务、端口错误、失效模板）"
                f"— 这属验证基础设施修正而非产品开发\n\n"
                f"## Dashboard 服务运维手册\n"
                f"- 脚本: python3 {dash_script}（bin/fenix_dashboard.py），默认端口 8787\n"
                f"- 【探活】必须双重校验：/api/projects 返回含 \"projects\" 字段的 JSON "
                f"且首页返回 200；仅检查 HTTP 200 会误判（SPA fallback 对任意路径返回 200）\n"
                f"- 【常驻启动】未运行时使用 tmux 常驻："
                f"tmux new-session -d -s fenix-dashboard \"python3 {dash_script} --serve\"，"
                f"随后轮询探活至就绪（约 1 秒）；tmux 常驻不受你的子进程退出影响\n"
                f"- 【注册监控】python3 {dash_script} --add-project <项目根目录>；"
                f"【列表】--list-projects；【停止】tmux kill-session -t fenix-dashboard\n"
                f"- 若你处置期间发现 dashboard 已退出/未监听，恢复常驻是你的职责"
                f"（探测 → 重启 → 注册）\n\n"
                f"## 铁律\n"
                f"1. 只处置困境，不开发功能、不实现 SPEC 需求。\n"
                f"2. 先只读诊断（日志/STATE.md/进程/run 转录），确认根因再动手。\n"
                f"3. 所有处置动作留痕（在处置记录中说明）。\n"
                f"4. 持久化优先：完成诊断后【先】写一次 .fenix/admin_disposition.json"
                f"（含初步结论与计划动作），再执行破坏性动作；任何时刻被杀都不丢处置记录。\n"
                f"5. 若确实无法自主处置（需人类决策、连续失败、不可逆操作），"
                f"将 escalate 置为 true 并给出 recommended_action。\n\n"
                f"## 完成后\n"
                f"把最终处置记录写入 .fenix/admin_disposition.json（当前目录即主树），"
                f"覆盖之前的初步记录。其中 summary 字段为必填：一段人类可读的叙述性总结，"
                f"必须包含诊断结论（问题是什么、根因）、处置时间线（做了什么、顺序）、"
                f"最终结果，以及如需人工介入时的具体建议：\n"
                f'{{\n'
                f'  "spec": "{sig_spec}",\n'
                f'  "problem": "处理的困境问题",\n'
                f'  "actions_taken": ["动作1", "动作2"],\n'
                f'  "result": "resolved | partially-resolved | escalated",\n'
                f'  "summary": "人类可读叙述：诊断结论 + 处置时间线 + 最终结果 + 对人类的建议",\n'
                f'  "escalate": true/false,\n'
                f'  "recommended_action": "若升级，给出人类应做的操作"\n'
                f'}}\n'
                f"然后结束，无需额外输出。不要直接编辑 .fenix/admin_alerts.json——"
                f"daemon 会基于你的处置记录写入。\n"
            )

    def _run_claude(self, prompt: str, cwd: Path, run_id: str,
                    model_override: str | None = None,
                    env_overrides: Dict[str, str] | None = None,
                    resume_session_id: str | None = None,
                    max_turns: int | None = None,
                    spec_name: str | None = None) -> tuple:
        from .config import ConfigLoader
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
        timeout = self._get_config("agents.run_timeout_seconds", 3600)
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
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    # 超时活性监督（improve-run-lifecycle-governance D3）：到点不
                    # 立即杀——按封闭决策矩阵判定（硬上限 → 次数上限 → 活性）。
                    action = self._supervision_deadline_action(
                        run_file, spec_name, run_id, started_at, extensions_used)
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
            # result 终态事件最后落盘（读线程里跳过内联写），保证是文件最后一行
            if last_result:
                append_run_line(run_file, dict(last_result))
            # 产物文件可能因崩溃等遗留为"活动但不再增长"，清理时按时间淘汰即可

        if timeout_error is not None:
            append_run_error(run_file, timeout_error, returncode)
            raise RuntimeError(f"claude CLI {timeout_error}")

        if turn_limit_error is not None:
            append_run_error(run_file, turn_limit_error, returncode)
            raise RuntimeError(f"claude CLI {turn_limit_error}")

        output = last_result.get("result", "") if last_result else ""
        turns = last_result.get("num_turns", 0)
        session_id = last_result.get("session_id") if last_result else None

        if returncode != 0:
            error_msg = "\n".join(stderr_lines[-5:])[:500] if stderr_lines else f"Exit code: {returncode}"
            append_run_error(run_file, error_msg, returncode)
            raise RuntimeError(f"claude CLI failed: {error_msg}")

        # D5: 终态语义校验前置 —— rc==0 但 last_result 标记为 error 时仍判失败
        # （Claude CLI 可能把 API 错误包装成 result/success 终止事件且 exit 0）
        if last_result:
            result_is_error = last_result.get("is_error", False)
            result_subtype = last_result.get("subtype", "success")
            if result_is_error or result_subtype in ("error", "error_during_execution"):
                err_text = last_result.get("result", "") or f"is_error={result_is_error}, subtype={result_subtype}"
                append_run_error(run_file, f"API error disguised as success: {err_text}", returncode)
                raise RuntimeError(f"claude CLI rc==0 but result indicates error: {err_text}")

        return output, turns, session_id

    @staticmethod
    def _extract_session_id(run_file: Path) -> str | None:
        """从 run 产物提取 session_id（供 --resume 续跑）。

        session_id 出现在两类事件：开头的 system/init 事件（会话建立时），以及
        结尾的 result 事件。max_turns/超时强杀时 CLI 不会输出 result 事件，
        必须从 init 事件取，否则 resume 在 Max turns 场景失效（fix）。
        文件不存在/损坏返回 None。
        """
        try:
            size = run_file.stat().st_size
            with run_file.open("rb") as f:
                if size > 65536:
                    f.seek(size - 65536)
                tail = f.read().decode("utf-8", "replace")
                f.seek(0)
                head = f.read(65536).decode("utf-8", "replace")
        except OSError:
            return None
        for chunk in (head, tail):
            for line in chunk.splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict):
                    continue
                if e.get("type") == "result" and e.get("session_id"):
                    return e["session_id"]
                if (e.get("type") == "system" and e.get("subtype") == "init"
                        and e.get("session_id")):
                    return e["session_id"]
        return None

    # ── attempt 存活探测（improve-run-lifecycle-governance D4）────────────────

    def has_live_attempt(self, spec_name: str) -> bool:
        """探测某 SPEC 是否仍有存活的 attempt 子进程（恢复一致性 D4 接口）。

        判定顺序：
          1. pgrep 进程表：cmdline 含该 spec 的 worktree 目录字面量
             （``worktrees/{impl,verify}-<spec>-<ts>``）→ 存活；
          2. 进程扫描不可用/未命中时，回退 run 流文件新鲜度：
             该 spec 任一 run jsonl 的 mtime < LIVE_ATTEMPT_STREAM_WINDOW_SECONDS
             视为仍在活动（resume 孤儿进程通常持续写流）。

        供 pm_engine auto-recovery 与 event_bus 孤儿 ready 白名单调用——
        有存活子进程时 MUST NOT 重置状态/清空跟踪字段。
        """
        try:
            if self._pgrep_live_attempt(spec_name):
                return True
        except Exception as e:  # 扫描器异常一律走流新鲜度回退，不向上抛
            self.logger.debug(
                "agent_runner",
                f"has_live_attempt process scan failed for '{spec_name}': {e}",
            )
        return self._stream_recent(spec_name, LIVE_ATTEMPT_STREAM_WINDOW_SECONDS)

    def _pgrep_live_attempt(self, spec_name: str) -> bool:
        """pgrep 匹配 cmdline 含该 spec worktree 目录字面量的进程。

        pgrep 不可用（缺失/超时/OSError）时返回 False，由流新鲜度回退判定。
        """
        for prefix in ("impl", "verify"):
            pattern = f"worktrees/{prefix}-{spec_name}-"
            try:
                res = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True, text=True, timeout=5,
                )
            except (subprocess.SubprocessError, OSError):
                return False
            if res.returncode == 0 and res.stdout.strip():
                return True
        return False

    def _stream_recent(self, spec_name: str, seconds: int) -> bool:
        """该 spec 最新 run 流文件的 mtime 是否在 seconds 内（不可用 → False）。"""
        runs_dir = self.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return False
        cutoff = time.time() - seconds
        for prefix in ("impl", "verify"):
            try:
                paths = list(runs_dir.glob(f"{prefix}-{spec_name}-*.jsonl"))
            except OSError:
                return False
            for p in paths:
                try:
                    if p.stat().st_mtime >= cutoff:
                        return True
                except OSError:
                    continue
        return False

    # ── 超时续期基准（improve-run-lifecycle-governance 3.2 / D3）──────────────

    def note_run_extension(self, spec_name: str, run_id: str,
                           extension_index: int, new_deadline: float) -> None:
        """超时续期时登记该 spec 的新 stuck 检测基准（续期时刻）。

        pm_engine.check_blockers 的 stuck 计算通过 ``get_extension_baseline``
        读取该基准，使 stuck 起点随续期同步顺延——否则刚续期的长任务立刻被
        误判 stuck 并触发 auto-recovery（等于绕过整个监督机制）。
        """
        self._extension_baselines[spec_name] = {
            "baseline": time.time(),
            "run_id": run_id,
            "extension": int(extension_index),
            "deadline": float(new_deadline),
        }
        self.logger.info(
            "agent_runner",
            f"Extension #{extension_index} noted for '{spec_name}' (run {run_id}) — "
            f"stuck baseline reset, new deadline "
            f"{datetime.fromtimestamp(new_deadline, timezone.utc).isoformat()}",
        )

    def get_extension_baseline(self, spec_name: str) -> float | None:
        """返回该 spec 的续期基准（epoch 秒）；无条目或 run 已结束返回 None。

        新鲜度自清理：关联 run 流文件已停止增长（超过 LIVE_ATTEMPT_STREAM_
        WINDOW_SECONDS）说明 run 已结束——基准随即失效并移除，调用方回退到
        既有 updated 起点（行为与无注册表时一致）。
        """
        entry = self._extension_baselines.get(spec_name)
        if not entry:
            return None
        run_id = entry.get("run_id") or ""
        run_file = self.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"
        try:
            mtime = run_file.stat().st_mtime
        except OSError:
            self._extension_baselines.pop(spec_name, None)
            return None
        if time.time() - mtime > LIVE_ATTEMPT_STREAM_WINDOW_SECONDS:
            self._extension_baselines.pop(spec_name, None)
            return None
        return float(entry.get("baseline") or 0.0)

    # ── 超时活性监督（improve-run-lifecycle-governance 4.1–4.3 / D1–D3）────────

    def _liveness_snapshot(self, run_file: Path, window_seconds: float,
                           now: float | None = None) -> dict:
        """run jsonl 活性快照（D1）：窗口内事件数、tool_use 数、最后事件距今。

        判定要素（tasks 4.1）：
        - ``events_in_window``：带可解析时间戳且落在窗口内的事件数；
        - ``tool_use`` / ``tool_counts``：assistant 消息中的工具调用计数；
        - ``last_event_age``：最后一个事件距今秒数（事件无时间戳时回退文件 mtime）；
        - ``last_output``：最后的 assistant 文本 / result 文本片段（截断）。

        无时间戳的行（stderr 兜底行等）按「文件 mtime 在窗口内即计入」的口径
        处理，保证纯 stderr 流不会被误判为死流。
        """
        now = time.time() if now is None else now
        snapshot = {
            "run_file": str(run_file),
            "window_seconds": float(window_seconds),
            "total_events": 0,
            "events_in_window": 0,
            "tool_use": 0,
            "tool_counts": {},
            "last_event_age": None,
            "last_output": "",
            "stream_available": True,
        }
        cutoff = now - max(0.0, window_seconds)
        try:
            with run_file.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    snapshot["total_events"] += 1
                    ts = self._parse_event_timestamp(entry)
                    if ts is None:
                        # 无时间戳：只有文件本身仍在窗口内才计入
                        try:
                            if run_file.stat().st_mtime >= cutoff:
                                snapshot["events_in_window"] += 1
                        except OSError:
                            pass
                    else:
                        if ts >= cutoff:
                            snapshot["events_in_window"] += 1
                        if (snapshot["last_event_age"] is None
                                or (now - ts) < snapshot["last_event_age"]):
                            snapshot["last_event_age"] = max(0.0, now - ts)
                    if entry.get("type") == "assistant":
                        msg = entry.get("message") or {}
                        for block in (msg.get("content") or []):
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_use":
                                snapshot["tool_use"] += 1
                                name = str(block.get("name") or "unknown")
                                snapshot["tool_counts"][name] = (
                                    snapshot["tool_counts"].get(name, 0) + 1)
                            elif block.get("type") == "text":
                                text = str(block.get("text") or "").strip()
                                if text:
                                    snapshot["last_output"] = text
                    elif entry.get("type") == "result":
                        text = str(entry.get("result") or "").strip()
                        if text:
                            snapshot["last_output"] = text
        except OSError:
            snapshot["stream_available"] = False
            return snapshot

        if snapshot["last_event_age"] is None:
            # 全部事件无时间戳：以文件 mtime 作为最后活动时刻
            try:
                snapshot["last_event_age"] = max(0.0, now - run_file.stat().st_mtime)
            except OSError:
                snapshot["last_event_age"] = None
        snapshot["last_output"] = snapshot["last_output"][:LIVENESS_SNIPPET_CHARS]
        return snapshot

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

    @staticmethod
    def _summarize_snapshot(snapshot: dict) -> str:
        """活性快照的证据摘要（供终止证据与日志，短小可读）。"""
        tools = snapshot.get("tool_counts") or {}
        tool_str = ",".join(f"{k}x{v}" for k, v in sorted(tools.items())) or "none"
        age = snapshot.get("last_event_age")
        return (
            f"events_in_window={snapshot.get('events_in_window')}, "
            f"total_events={snapshot.get('total_events')}, "
            f"tool_use={snapshot.get('tool_use')} ({tool_str}), "
            f"last_event_age={'n/a' if age is None else f'{age:.0f}s'}, "
            f"last_output={(snapshot.get('last_output') or '')[:160]}"
        )

    def _judge_liveness(self, snapshot: dict, spec_name: str | None,
                        run_id: str) -> dict:
        """轻量 LLM 活性判定（D2）：单轮调用，输出 {verdict, evidence}。

        模型路由复用 Administrator 的兜底通道（DEFAULT_GATEWAY_MODEL），不落
        .fenix/runs 正式 run 文件——判定结论写回被监督 run 的 jsonl 与 daemon 日志。
        任何解析失败 / 异常都按 ``stagnant`` 处理，evidence 以
        ``liveness judge unavailable`` 开头（tasks 4.2 要求的可辨识证据）。
        """
        prompt = (
            "你是长时运行 agent 的活性监督判定器。根据以下 run 流统计快照，判断该"
            " agent 是在真实推进任务，还是已陷入停滞（空转、卡死、重复循环、无输出）。\n\n"
            f"SPEC: {spec_name or 'unknown'}\nRUN: {run_id}\n\n快照：\n"
            f"{json.dumps(snapshot, ensure_ascii=False)}\n\n"
            "只输出一个 JSON 对象，不要其它文字：\n"
            '{"verdict": "advancing|stagnant", "evidence": "简短判定依据（<=200字）"}\n'
            "判定口径：窗口内有新事件且工具调用在推进/产出新内容 → advancing；"
            "零事件、同参数工具调用反复失败、长时间无新输出 → stagnant。"
        )
        try:
            cmd = ["claude", "-p", prompt, "--output-format", "json"]
            model = self._get_admin_model()
            if model:
                cmd += ["--model", model]
            res = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=JUDGE_TIMEOUT_SECONDS, cwd=str(self.project_root),
            )
            text = res.stdout or ""
            try:
                payload = json.loads(text)
                if isinstance(payload, dict) and payload.get("result"):
                    text = str(payload["result"])
            except json.JSONDecodeError:
                pass
            verdict = self._parse_verdict_json(text)
            if verdict:
                return {
                    "verdict": verdict["verdict"],
                    "evidence": str(verdict.get("evidence") or "")[:400],
                }
            return {
                "verdict": "stagnant",
                "evidence": (f"liveness judge unavailable: unparseable output "
                             f"(rc={res.returncode}) {(res.stderr or '')[:160]}"),
            }
        except Exception as e:
            return {"verdict": "stagnant", "evidence": f"liveness judge unavailable: {e}"}

    @staticmethod
    def _parse_verdict_json(text: str) -> dict | None:
        """从模型输出中提取 ``{"verdict": ...}`` JSON 对象；找不到返回 None。"""
        if not text:
            return None
        start = text.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
                        if (isinstance(obj, dict)
                                and obj.get("verdict") in ("advancing", "stagnant")):
                            return obj
                        break
            start = text.find("{", start + 1)
        return None

    def _supervision_settings(self) -> dict:
        """超时监督配置（D3）：canonical ``agents.timeout_supervision``，回退旧顶层键。

        缺省取 SUPERVISION_DEFAULTS（enabled=true）；旧版顶层 ``timeout_supervision``
        （fix-stuck-threshold-unify 引入，enabled=false）作为回退开关仍然生效。
        """
        cfg = dict(SUPERVISION_DEFAULTS)
        sup = self._get_config("agents.timeout_supervision", None)
        if not isinstance(sup, dict):
            sup = self._get_config("timeout_supervision", None)
        if not isinstance(sup, dict):
            sup = {}
        for key, default in cfg.items():
            value = sup.get(key)
            if value is None:
                continue
            if isinstance(default, bool):
                cfg[key] = bool(value)
                continue
            try:
                cfg[key] = type(default)(value)
            except (TypeError, ValueError):
                self.logger.warning(
                    "agent_runner",
                    f"Invalid timeout_supervision.{key}={value!r} — keeping default "
                    f"{default}",
                )
        return cfg

    def _supervision_deadline_action(self, run_file: Path, spec_name: str | None,
                                     run_id: str, started_at: float,
                                     extensions_used: int,
                                     judge=None) -> dict:
        """deadline 到点后的监督决策（D3）：续期 or 终止，封闭矩阵。

        判定顺序（先硬上限后活性）：
          1. supervision 未启用 → 纯墙钟终止（现状行为）；
          2. 总墙钟 ≥ absolute_max_seconds（不低于 run_timeout + 续期总额，
             保证续期预算完整可用）→ 无条件终止；
          3. 已用满 max_extensions → 终止；
          4. judge_window 内零事件 → 跳过 LLM、直接判停滞终止；
          5. LLM 判定 advancing → 续期 extension_seconds；
          6. LLM 判定 stagnant（含 judge 不可用）→ 终止并保留证据。

        Returns: {"action": "extend"|"kill", "reason", "extension_seconds"?,
                  "extension_index"?, "evidence", "settings"}
        """
        sup = self._supervision_settings()
        evidence = ""
        if not sup["enabled"]:
            return {
                "action": "kill",
                "reason": "run timeout reached (supervision disabled)",
                "evidence": evidence,
                "settings": sup,
            }
        run_timeout = float(self._get_config("agents.run_timeout_seconds", 3600) or 3600)
        max_extensions = max(0, int(sup["max_extensions"]))
        extension_seconds = max(1.0, float(sup["extension_seconds"]))
        # absolute_max 是总墙钟上限；配置偏小时抬到 run_timeout + 续期总额，
        # 否则续期预算会被总上限截断（语义矛盾）。
        absolute_max = max(
            float(sup["absolute_max_seconds"]),
            run_timeout + max_extensions * extension_seconds,
        )
        now = time.time()
        if now - started_at >= absolute_max:
            return {
                "action": "kill",
                "reason": (f"absolute_max_seconds cap reached ({int(absolute_max)}s, "
                           f"extensions_used={extensions_used})"),
                "evidence": evidence,
                "settings": sup,
            }
        if extensions_used >= max_extensions:
            return {
                "action": "kill",
                "reason": (f"extension budget exhausted "
                           f"({extensions_used}/{max_extensions})"),
                "evidence": evidence,
                "settings": sup,
            }
        window = max(30.0, float(sup["judge_window"]))
        snapshot = self._liveness_snapshot(run_file, window)
        evidence = self._summarize_snapshot(snapshot)
        if (not snapshot.get("stream_available")
                or snapshot.get("last_event_age") is None
                or snapshot["last_event_age"] > window
                or snapshot.get("events_in_window", 0) == 0):
            return {
                "action": "kill",
                "reason": "stagnant: zero run events within judge window",
                "evidence": evidence,
                "settings": sup,
            }
        verdict = (judge or self._judge_liveness)(snapshot, spec_name, run_id)
        if verdict.get("verdict") == "advancing":
            return {
                "action": "extend",
                "extension_seconds": extension_seconds,
                "extension_index": extensions_used + 1,
                "reason": "judged advancing",
                "evidence": str(verdict.get("evidence") or "")[:400],
                "settings": sup,
            }
        return {
            "action": "kill",
            "reason": "judged stagnant",
            "evidence": str(verdict.get("evidence") or "")[:400],
            "settings": sup,
        }

    def wait_for_running_agents(self, timeout: int = AGENT_TERMINATE_GRACE_SECONDS):
        """优雅退出时终止全部在跑 agent（terminate 流程），不再逐 agent 等待完成。

        fix-graceful-shutdown-agents：原实现每 agent 最多等待 timeout（300s）串行叠加，
        叠加 supervisor 固定 60s SIGKILL 窗口必触发 kill -9，丢失在跑 agent 的 run 结果。

        新流程（D5 并行终止）：
          1. 对所有在跑 agent 立即发 SIGTERM（不等待完成）；
          2. 同步向各自 run 文件追加 interrupted 标记（标记 daemon 侧已知中断，
             与"疑似崩溃"区分，且不影响已 finalize 的完成 run）；
          3. 统一等待 ≤ grace 缓冲窗口（默认 10s），让 claude 收尾；
          4. 窗口结束仍未退出的 agent 用 SIGKILL 兜底。

        总终止时长恒 ≲ grace，不随 agent 数量线性增长，确保 daemon 在 supervisor 60s
        窗口内退出。

        Args:
            timeout: 缓冲窗口秒数（子类/测试可覆写短值避免真实等待）。
        """
        grace = max(0, timeout)
        running = list(self._running_agents.items())
        if not running:
            return

        # 第一步：统一 SIGTERM，并行通知所有在跑 agent 收尾
        for name, proc in running:
            try:
                proc.terminate()  # SIGTERM：让 claude 关会话/flush 输出
                self.logger.info("agent_runner", f"Sent SIGTERM to running agent: {name}")
            except ProcessLookupError:
                # 进程已退出（竞态），标记清理后跳过
                self._running_agents.pop(name, None)
            except Exception as e:  # pragma: no cover - 防御性
                self.logger.warning("agent_runner", f"SIGTERM failed for agent {name}: {e}")

        # 第二步：同步写入 interrupted 标记。running 快照只含未完成 agent（完成的已
        # finalize 并移除），不会误标已完成 run。对每个被终止 agent 都写标记——无论其
        # 是否已在 SIGTERM 后快速退出（design D2：标记由 daemon 侧同步写入，不依赖
        # agent 优雅退出，保证"已知中断"证据完整）。读线程以 append 模式单行写入，
        # O_APPEND 原子追加不破坏 JSONL 结构。
        runs_dir = self.project_root / ".fenix" / "runs"
        for name, proc in running:
            run_file = runs_dir / f"{name}.jsonl"
            try:
                append_run_line(run_file, {
                    "type": "interrupted",
                    "reason": "daemon shutdown",
                    "by": "agent_runner",
                })
            except Exception as e:  # pragma: no cover - run 文件写入失败不影响退出
                self.logger.warning(
                    "agent_runner", f"Failed to write interrupted marker for {name}: {e}"
                )

        # 第三步 + 第四步：统一缓冲窗口，窗口内未退出者 SIGKILL 兜底
        if grace > 0:
            deadline = time.time() + grace
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                alive = [n for n, p in self._running_agents.items() if p.poll() is None]
                if not alive:
                    break
                time.sleep(min(0.2, remaining))
            # 缓冲窗口结束仍未退出的，强制 SIGKILL（标记已写入，不依赖优雅退出）
            for name, proc in list(self._running_agents.items()):
                if proc.poll() is None:
                    self.logger.warning(
                        "agent_runner", f"Agent did not exit within {grace}s, SIGKILL: {name}"
                    )
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    except Exception as e:  # pragma: no cover - 防御性
                        self.logger.warning("agent_runner", f"SIGKILL failed for {name}: {e}")
        else:
            # grace=0：直接 SIGKILL 兜底
            for name, proc in list(self._running_agents.items()):
                if proc.poll() is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass

        # 收割所有子进程，避免僵尸进程
        for name, proc in list(self._running_agents.items()):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            except Exception:  # pragma: no cover - 防御性
                pass
            self._running_agents.pop(name, None)

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
        from .config import ConfigLoader
        return ConfigLoader.get_agent_model_assignment(self.config, agent_type)

    def _get_config(self, key: str, default=None):
        """Get a nested config value."""
        from .config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)

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
