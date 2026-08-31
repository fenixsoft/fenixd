"""provider_circuit.py — ProviderCircuit：provider 熔断/切换冷却/探针/4xx 与当日 attempt 计数（refactor-core-packages 阶段 2）。

状态同迁（design D3 规则 1）：provider_circuits 与 per-provider 当日 attempt
计数随组件迁移；门面经 property 委托保持 `runner.provider_circuits` 等路径可用。
时间源 `self._pm._now()`、配置 `self._pm._get_config()` 经门面回引（规则 3）——
测试对 `runner._now` 的 monkeypatch 补丁缝保持有效。
"""

from core.agent_runner.run_files import append_run_line
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import re


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


class ProviderCircuit:
    """provider 熔断与切换冷却组件（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

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

        # add-provider-failover（design D5 / spec failover-dispatch 4.2）：per-provider
        # 当日 attempt 计数与单次告警标记。进程内存、按 UTC 日期滚动重置；超过
        # pm.failover.daily_attempts_warn（默认 50）时打 WARNING 且当日只告警一次。
        self._daily_provider_attempts: Dict[str, int] = {}
        self._daily_provider_warned: Dict[str, bool] = {}
        self._daily_reset_date = datetime.now(timezone.utc).date()

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
        code = ProviderCircuit.parse_api_error_status(text)
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
        now = self._pm._now() if now is None else now
        return st["cooldown_until"] > now


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
        now = self._pm._now() if now is None else now
        return st.get("switch_cooldown_until", 0.0) > now


    def _record_switch_cooldown(self, provider_name: str, now: float | None = None) -> None:
        """记录一次切换类错误：把该 provider 推进到 switch 短冷却（design D2/D3）。

        默认 300s（PROVIDER_SWITCH_COOLDOWN_SECONDS），可配 pm.failover.switch_cooldown_seconds。
        与 4xx 熔断计数完全独立：仅设置 switch_cooldown_until，不动 4xx 的 events/count/
        cooldown_until。冷却到期后链选择自动复位优先。
        """
        if not provider_name:
            return
        now = self._pm._now() if now is None else now
        st = self._circuit_state(provider_name)
        cooldown = self._pm._get_config("pm.failover.switch_cooldown_seconds",
                                    PROVIDER_SWITCH_COOLDOWN_SECONDS)
        st["switch_cooldown_until"] = now + cooldown
        self._pm.logger.info(
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
        runs_dir = self._pm.project_root / ".fenix" / "runs"
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
        warn = self._pm._get_config("pm.failover.daily_attempts_warn",
                                PROVIDER_DAILY_ATTEMPTS_WARN)
        if warn and count > warn and not self._daily_provider_warned.get(provider_name, False):
            self._daily_provider_warned[provider_name] = True
            self._pm.logger.warning(
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
        now = self._pm._now() if now is None else now
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
        now = self._pm._now() if now is None else now
        st = self._circuit_state(provider_name)
        window = self._pm._get_config("agents.provider_circuit_window_seconds",
                                  PROVIDER_CIRCUIT_WINDOW_SECONDS)
        threshold = self._pm._get_config("agents.provider_circuit_threshold",
                                     PROVIDER_CIRCUIT_THRESHOLD)
        cooldown = self._pm._get_config("agents.provider_circuit_cooldown_seconds",
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
            self._pm.logger.error(
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
        now = self._pm._now() if now is None else now
        cooldown = self._pm._get_config("agents.provider_circuit_cooldown_seconds",
                                    PROVIDER_CIRCUIT_COOLDOWN_SECONDS)
        if success:
            self._pm.logger.info(
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
            self._pm.logger.warning(
                "agent_runner",
                f"Provider circuit re-cooled for '{provider_name}' — probe still failing, "
                f"cooldown {int(cooldown)}s",
            )
