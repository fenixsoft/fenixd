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
PROVIDER_CIRCUIT_WINDOW_SECONDS = 300  # 滚动窗口 5 分钟
PROVIDER_CIRCUIT_THRESHOLD = 3  # 窗口内 4xx 达此次数 → 熔断
PROVIDER_CIRCUIT_COOLDOWN_SECONDS = 1800  # 冷却 30 分钟
# 计入熔断的 HTTP 4xx 状态码（401 与 400/404 一并计数：余额不足同样要防烧钱；
# 403 同为鉴权/订阅类——inferaiapi 实测「API Error: 403 No active subscription」
# 反复原地重试烧链预算，fix-403-auth-failover-blindspot 一并纳入）
PROVIDER_CIRCUIT_4XX = (400, 401, 403, 404)
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
    r"name or service not known",  # DNS 解析失败
    r"temporarily unavailable",
    r"network is unreachable",
)
# per-provider 当日 attempt 计数告警上限（design D5：防备备份 provider 悄悄烧贵）；
# 可配 pm.failover.daily_attempts_warn，默认 50。
PROVIDER_DAILY_ATTEMPTS_WARN = 50

# ── 全局瞬断错误指纹熔断（fix-provider-transient-backoff D4 / transient-dispatch-gating） ──
# 与 4xx/switch 冷却同构的进程内存态（重启清零）；同错误指纹在窗口内达阈值
# 触发全局派发冻结。
TRANSIENT_BREAK_WINDOW_SECONDS = 600  # 窗口时长（秒）
TRANSIENT_BREAK_THRESHOLD = 3  # 窗口内同指纹次数达此次数 → 触发熔断
TRANSIENT_BREAK_COOLDOWN_SECONDS = 600  # 触发后全局冻结时长（秒）
TRANSIENT_BREAK_ALERT_THROTTLE_MINUTES = 15  # major 告警节流（分钟）


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

        # fix-provider-transient-backoff（D4 / transient-dispatch-gating）：全局
        # 瞬断错误指纹熔断态。进程内存、不落盘（与 4xx 熔断/switch 冷却同构，
        # daemon 重启清零可接受）。
        #   _transient_break_events: {指纹: [window 内失败时间戳, ...]}
        #   _transient_break_until: 全局冻结到期单调秒（0 = 未冻结）
        self._transient_break_events: Dict[str, list] = {}
        self._transient_break_until: float = 0.0

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
        # 顺序匹配：HTTP <code> / (404) / status code <code> / code <code> /
        # 「API Error: 403」（claude CLI 经 SDK 包装的鉴权错误实际形态，
        # fix-403-auth-failover-blindspot）
        for pat in (
            r"HTTP\s+(\d{3})",
            r"\((\d{3})\)",
            r"status\s*code\s*[:=]?\s*(\d{3})",
            r"\bcode\s*[:=]?\s*(\d{3})",
            r"[Ee]rror:?\s*(\d{3})",
        ):
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

    @staticmethod
    def classify_transient_error(stderr_lines: list, exit_code: int, has_result: bool) -> bool:
        """瞬断判定（fix-provider-transient-backoff D2，与降噪解耦）。

        判定信号（任一命中即瞬断）：
        - 全量 stderr_lines 命中 switch 类 pattern（unrecognized_model / 5xx /
          连接类），从**全量** stderr 匹配而非末 5 行（末 5 行含 `[claude-code:...]`
          诊断噪音行的 run 会漏判）；
        - 或（exit≠0 且本进程无 result 事件且 stderr 存在 `[claude-code:...]`
          诊断行）——CLI 实验实证：400 fatal / 500 耗尽 / 流断耗尽三种形态均为
          exit 1 + 无 result + stderr 仅剩诊断行。

        前置条件：exit=0 且 has_result=True 时直接返回 False（CLI 成功完成，
        不是瞬断——即使 stderr 含 switch pattern 诊断噪音行）。判定依赖**原始**
        stderr 信号与结构化信号（exit_code / has_result），不得读降噪后的 error
        字符串反推（D2：unrecognized_model 可能已被过滤）。

        Args:
            stderr_lines: 本进程 stderr 全量原始行（未降噪，jsonl 事件同源）。
            exit_code: 子进程退出码（≠0 表示非零退出）。
            has_result: 本进程流中是否出现 result 事件（无则说明 CLI 未走到终态）。
        """
        if not stderr_lines:
            return False
        # 前置：CLI 成功完成（exit=0 + 有 result 事件）→ 不是瞬断
        if exit_code == 0 and has_result:
            return False
        full_text = "\n".join(str(l) for l in stderr_lines)
        # 通道 1：全量 stderr 命中 switch 类 pattern（复用 switch 文本匹配语义，
        # 4xx 配额/鉴权类自动排除——那属熔断面，不判瞬断）。
        if full_text and ProviderCircuit.classify_switch_error(full_text):
            return True
        # 通道 2：非零退出 + 无 result 事件 + stderr 含 `[claude-code:` 诊断行。
        if exit_code != 0 and not has_result:
            if any(str(l).startswith("[claude-code:") for l in stderr_lines):
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
        cooldown = self._pm._get_config(
            "pm.failover.switch_cooldown_seconds", PROVIDER_SWITCH_COOLDOWN_SECONDS
        )
        st["switch_cooldown_until"] = now + cooldown
        self._pm.logger.info(
            "agent_runner",
            f"Provider switch-cooldown for '{provider_name}' "
            f"(add-provider-failover) — {int(cooldown)}s, advance chain",
        )

    def _write_provider_marker(
        self,
        run_id: str,
        spec_name: str,
        agent_type: str,
        provider_name: str,
        model: str,
        chain_index: int,
        chain_len: int,
    ) -> None:
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
            append_run_line(
                run_file,
                {
                    "type": "provider_marker",
                    "spec": spec_name,
                    "agent_type": agent_type,
                    "provider": provider_name,
                    "model": model,
                    "chain_index": chain_index,
                    "chain_len": chain_len,
                },
            )
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
        warn = self._pm._get_config("pm.failover.daily_attempts_warn", PROVIDER_DAILY_ATTEMPTS_WARN)
        if warn and count > warn and not self._daily_provider_warned.get(provider_name, False):
            self._daily_provider_warned[provider_name] = True
            self._pm.logger.warning(
                "agent_runner",
                f"Provider '{provider_name}' daily attempts ({count}) exceeded "
                f"pm.failover.daily_attempts_warn ({warn}) — check for silent cost",
            )

    # ── 全局瞬断错误指纹熔断（fix-provider-transient-backoff D4 / transcendent-dispatch-gating）──
    # 全局维度的瞬断错误指纹计数：错误文本归一化（剥离 model 名/时间戳等可变字段）
    # 生成指纹，在窗口内同一指纹出现次数达阈值 → 触发全局派发冻结。计数与熔断
    # 状态保持进程内存（与既有 4xx 熔断同构，daemon 重启清零）。

    @staticmethod
    def normalize_transient_fingerprint(error_text: str) -> str:
        """把瞬断错误文本归一化为指纹（design D4）。

        归一化只剥离「可变字段」：HTTP 状态码之外的具体 model 标识、run 专属
        时间戳、会话 id 等。保留错误类别骨架（如 ``unrecognized_model``、
        ``HTTP 503`` 字样），使不同 spec 的同型瞬断收敛为同一指纹、真实缺陷型
        错误文本各异则指纹不同。

        实现要点：小写化 → 剥离 ``[claude-code:...]`` 诊断前缀 → 剥 model 名
        （``deepseek-v4-flash`` / ``glm-5.3-flash`` / ``claude-*`` 等形态）→
        剥 ISO 时间戳与长数字串 → 压空白。
        """
        if not error_text:
            return ""
        text = error_text.lower()
        # 剥 [claude-code:...] 诊断前缀（v2.1.233+ 每请求写入的噪音）
        text = re.sub(r"\[claude-code:[^\]]*\]", "", text)
        # 剥 model 名：版本化模型名形如 deepseek-v4-flash / glm-5.3-flash /
        # claude-3-5-haiku（含「-<数字>」片段）。统一替换为占位符，使不同
        # 模型变体的同型瞬断收敛为同一指纹。
        text = re.sub(
            r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)*-v?\d+(?:\.\d+)*(?:-[a-z0-9.]+)*\b",
            "<model>",
            text,
        )
        # 剥 iso 时间戳（2026-09-07t10:40:03z 等）
        text = re.sub(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?z?", "", text)
        # 剥长数字串（unix 时间戳 / session id 碎片）
        text = re.sub(r"\d{4,}", "", text)
        # 剥分隔符噪音与空白
        text = re.sub(r"[\s:/.,()\"'-]+", " ", text).strip()
        return text

    def record_transient_error(self, error_text: str, now: float | None = None) -> bool:
        """记录一次瞬断错误，窗口内同指纹累计 → 达阈值触发全局熔断。

        Returns:
            True 表示本次记录**触发了**全局熔断（首次达阈值）；False 表示未触发
            （未达阈值 / 已在熔断中 / 指纹为空）。
        """
        fingerprint = self.normalize_transient_fingerprint(error_text)
        if not fingerprint:
            return False
        if self.is_global_transient_break(now=now):
            # 已冻结中：只记账不重复触发/告警（冷却到期由查询侧清零重记）。
            self._transient_break_events.setdefault(fingerprint, []).append(
                now if now is not None else self._pm._now()
            )
            return False
        now = self._pm._now() if now is None else now
        window = int(
            self._pm._get_config(
                "agents.transient_break_window_seconds", TRANSIENT_BREAK_WINDOW_SECONDS
            )
            or 0
        )
        if window <= 0:
            return False
        events = self._transient_break_events.setdefault(fingerprint, [])
        # 滑出窗口外旧事件
        events = [t for t in events if now - t <= window]
        events.append(now)
        self._transient_break_events[fingerprint] = events
        threshold = int(
            self._pm._get_config("agents.transient_break_threshold", TRANSIENT_BREAK_THRESHOLD) or 0
        )
        if threshold <= 0:
            return False
        if len(events) >= threshold:
            cooldown = int(
                self._pm._get_config(
                    "agents.transient_break_cooldown_seconds", TRANSIENT_BREAK_COOLDOWN_SECONDS
                )
                or 0
            )
            self._transient_break_until = now + (cooldown or TRANSIENT_BREAK_COOLDOWN_SECONDS)
            self._alert_transient_break(fingerprint, len(events), window)
            self._pm.logger.error(
                "agent_runner",
                f"Global transient break TRIGGERED for fingerprint '{fingerprint}' "
                f"({len(events)} failures within {int(window)}s window) — "
                f"freezing all new run dispatch for "
                f"{int(self._transient_break_until - now)}s "
                f"(fix-provider-transient-backoff D4)",
            )
            return True
        return False

    def is_global_transient_break(self, now: float | None = None) -> bool:
        """全局是否处于瞬断熔断冻结期（派发闸门查询）。

        冷却到期自动解除并清零窗口内指纹计数（重新起算，与 is_instant_fail_cooled
        到期恢复语义一致）；无冻结 / 已到期返回 False（恢复派发）。
        """
        if self._transient_break_until <= 0:
            return False
        now = self._pm._now() if now is None else now
        if now >= self._transient_break_until:
            self._transient_break_until = 0.0
            self._transient_break_events.clear()
            self._pm.logger.warning(
                "agent_runner",
                "Global transient break expired — dispatch resumed, " "fingerprint window reset",
            )
            return False
        return True

    def _alert_transient_break(self, fingerprint: str, count: int, window: int) -> None:
        """触发全局瞬断熔断时发 major 告警（15 分钟节流去重）。

        与 _alert_instant_fail_storm 同构：AdminStore.latest_signal 按
        (spec, signal_type) 在窗口内查重，窗口内已有同信号则不发第二条。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION

            store = AdminStore(self._pm.project_root, self._pm.logger)
            if (
                store.latest_signal(
                    "global-transient",
                    "transient_break_storm",
                    TRANSIENT_BREAK_ALERT_THROTTLE_MINUTES,
                )
                is not None
            ):
                self._pm.logger.debug(
                    "agent_runner",
                    f"transient_break_storm 告警已 throttle "
                    f"({TRANSIENT_BREAK_ALERT_THROTTLE_MINUTES} 分钟内已有)",
                )
                return
            store.append(
                {
                    "kind": ESCALATION,
                    "signal_type": "transient_break_storm",
                    "spec": "global-transient",
                    "severity": "major",
                    "description": (
                        f"全局瞬断风暴：错误指纹 '{fingerprint}' 在 {int(window)}s 窗口内 "
                        f"出现 {count} 次 — 已冻结全部新 run 派发，冷却期内不再启动新 run"
                    ),
                    "evidence": (
                        f"fingerprint={fingerprint}; count={count}; "
                        f"window_seconds={int(window)}; "
                        f"cooldown_seconds={int(self._transient_break_until - self._pm._now())}"
                    ),
                    "recommended_action": (
                        "检查网关/默认 provider 瞬时故障（model 拒绝 / 5xx / 断连）；"
                        "熔断自动冷却到期后恢复派发，无需人工干预"
                    ),
                }
            )
        except Exception as e:
            self._pm.logger.error(
                "agent_runner",
                f"transient_break_storm 告警写入失败: {e}",
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
        return (
            f"provider circuit open: {provider_name} " f"(HTTP {code} x {count}) — {cooldown_info}"
        )

    def _record_provider_4xx(self, provider_name: str, code: int, now: float | None = None) -> None:
        """记录一次 provider 网关 4xx，按滚动窗口计数，达阈值置 open。

        5xx / 网络错误不调用本方法（design D4）。窗口外的旧事件先滑出。
        """
        if not provider_name:
            return
        now = self._pm._now() if now is None else now
        st = self._circuit_state(provider_name)
        window = self._pm._get_config(
            "agents.provider_circuit_window_seconds", PROVIDER_CIRCUIT_WINDOW_SECONDS
        )
        threshold = self._pm._get_config(
            "agents.provider_circuit_threshold", PROVIDER_CIRCUIT_THRESHOLD
        )
        cooldown = self._pm._get_config(
            "agents.provider_circuit_cooldown_seconds", PROVIDER_CIRCUIT_COOLDOWN_SECONDS
        )

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

    def _record_provider_probe(
        self, provider_name: str, success: bool, now: float | None = None
    ) -> None:
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
        cooldown = self._pm._get_config(
            "agents.provider_circuit_cooldown_seconds", PROVIDER_CIRCUIT_COOLDOWN_SECONDS
        )
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
