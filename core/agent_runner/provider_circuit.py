"""provider_circuit.py — ProviderCircuit：provider 熔断/切换冷却/探针/4xx 与当日 attempt 计数（refactor-core-packages 阶段 2）。

状态同迁（design D3 规则 1）：provider_circuits 与 per-provider 当日 attempt
计数随组件迁移；门面经 property 委托保持 `runner.provider_circuits` 等路径可用。
时间源 `self._pm._now()`、配置 `self._pm._get_config()` 经门面回引（规则 3）——
测试对 `runner._now` 的 monkeypatch 补丁缝保持有效。
"""

import json
import re
import time
from core.agent_runner.run_files import append_run_line
from datetime import datetime, timezone
from typing import Optional, Dict

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
# （code-review item 8f7f04802d6b）原 PROVIDER_CIRCUIT_PROBE_SUCCESS_CODE 常量
# 全仓零引用——探针成败实际以 `_record_provider_probe(success=bool)` 的实参为准，
# 该常量是与真实逻辑脱节的死配置（可能静默漂移），已移除。

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
# ── 拒模型快速 failover（add-impl-selfcheck-model-probe 2.1）───────────────
# unrecognized_model 是 provider **明确返回**的确定性模型失败（非瞬态网关故障）：
# 同一 (provider, model) 再试必然再拒。既有 add-provider-failover 已把它纳入
# SWITCH_ERROR_TEXT_PATTERNS 驱动链前进，但既有 transient 判定（通道 1 全量
# stderr 匹配 switch patterns）同时让它落入瞬断通道——原地退避重试同一拒模型 +
# 记全局瞬断指纹，均为纯浪费（2026-09 实测 22 个 impl run 秒死、同因重派每
# 2-5 分钟一个）。本组常量把 unrecognized_model 从瞬态中**收窄**出来：识别命中
# 即记 WARNING 并沿链原地切换下一可用模型，不进原地重试、不递增 transient
# 熔断/同因重派计数。
UNRECOGNIZED_MODEL_TEXT_PATTERNS = (
    r"unrecognized_model",
    r"unrecognized model",
)
# 全链模型不可用语义标记（add-impl-selfcheck-model-probe 2.2）：链尾模型仍被拒
# 时注入失败归因，派发器读侧据此**跳过同因重派**（阻断「switch 冷却到期复位 →
# 重派再撞同一拒模型链」的 2-5 分钟循环）。摘除拒模型条目为人工运维步骤
# （docs/help/13-model-chain-ops.md）。
MODEL_CHAIN_UNAVAILABLE_MARKER = "[model-chain-unavailable]"
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
# evo-transient-storm-alert-context（design D2）：触发全局熔断时注入告警上下文
# 的 attempt 聚合清单有界上限——冻结期内事件持续累积，清单 MUST 有界，避免
# description/evidence 与 admin_alerts.json 无界增长；截断时追加 truncated=<被略去条数>。
TRANSIENT_BREAK_ATTEMPT_LIST_LIMIT = 20

# ── 信号死法冷却（evo-sigterm-source-tracking-cooldown）────────────────
# CLI 子进程以信号死法结束（Exit 143 / 负信号 -9/-15 等）且非 daemon 关停、
# 非框架自身终止（cancel/supervision 超时/轮次上限强杀）时的 spec 维度冷却：
# 同 spec 连续信号死法达阈值 → 该 spec 冷却，期间其重派被跳过（不耗预算、
# 不起进程），冷却到期自动恢复。计数键 = spec 维度（爆炸半径限于该 spec，
# MUST NOT 写 record_transient_error / _transient_break_until 全局瞬断熔断）。
# 与既有秒挂冷却（runner._record_instant_fail）并存：同一事件双记仅允许累加，
# 冷却截止各自独立（dispatch 侧 OR 判定天然取更晚者生效），互不覆盖。
# 阈值/冷却量级沿用瞬断通道同量级常量；可配键沿用 agents.* 命名。
SIGNAL_KILL_COOLDOWN_AFTER = 3  # 同 spec 信号死法连续达此数 → 冷却
SIGNAL_KILL_COOLDOWN_SECONDS = 600  # 冷却时长（秒，与瞬断冷却同量级）
SIGNAL_KILL_ALERT_THROTTLE_MINUTES = 15  # major 告警节流（分钟）


def annotate_model_chain_unavailable(error_text: str, provider_name, model,
                                     rejected_count: int) -> str:
    """链尾模型仍被拒时给失败归因注入「全链模型不可用」语义（2.2）。

    幂等：归因已含 ``MODEL_CHAIN_UNAVAILABLE_MARKER`` 时原样返回（同一链尾
    反复撞拒不叠加标注）。派发器读侧（queue / fast_track）以标记子串识别该
    归因并跳过同因重派——这是阻断「冷却复位 → 再撞」循环的关键；标记后的
    归因仍走既有失败路径收场（终态记录/告警/keep-for-reuse 不变）。
    """
    if error_text and MODEL_CHAIN_UNAVAILABLE_MARKER in error_text:
        return error_text
    detail = (
        f"全链模型不可用：provider {provider_name!r} 拒绝模型 {model!r}"
        f"（unrecognized_model，链尾无更多候选；本 run 已有 {rejected_count} 个"
        f"链上候选被拒）——同因重派必然再撞同一拒模型链，摘除拒模型条目为"
        f"人工运维步骤（docs/help/13-model-chain-ops.md）"
    )
    if error_text:
        return f"{MODEL_CHAIN_UNAVAILABLE_MARKER} {detail} ｜ {error_text}"
    return f"{MODEL_CHAIN_UNAVAILABLE_MARKER} {detail}"


class TransientAttempt:
    """一次瞬断失败 attempt 的元信息记账（evo-transient-storm-alert-context D1）。

    与既有时间戳列表同构：``at``（单调秒）用于滑窗剔除（行为不变）；spec/run_id/
    provider 供触发全局熔断时聚合注入告警上下文——对 fingerprint 归一化免疫（即使
    指纹只剩 ``<model>`` 占位，清单仍列出真实 provider/run_id）。元信息缺省为
    空串占位并正常记账，MUST NOT 阻断熔断记账。
    """

    __slots__ = ("spec", "run_id", "provider", "at", "at_wall")

    def __init__(self, spec: str = "", run_id: str = "", provider: str = "",
                 at: float = 0.0, at_wall: float | None = None):
        self.spec = spec or ""
        self.run_id = run_id or ""
        self.provider = provider or ""
        # at：单调秒，仅供滑窗剔除（now - t <= window）。
        # at_wall：墙钟秒，仅供告警上下文展示（code-review item cbaa42ed2281）——
        # 旧实现把单调时间戳直接 fromtimestamp 成「时钟时间」，得到 1970 年附近
        # 的无意义时刻，污染 escalation description/evidence 与 resolve_note。
        # 缺省回退 at（旧调用点未传墙钟时行为与既有测试一致）。
        self.at = at
        self.at_wall = at if at_wall is None else at_wall


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
        #   "switch_cooldown_until": float,  # add-provider-failover 切换类错误冷却到期
        # }}
        # （half_open 字段已删除，code-review item dff73c446d83：只写不读的死
        # 状态——探针结果实际由 runner 半开判据驱动 _record_provider_probe 承载）
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
        #   _transient_break_events: {指纹: [window 内失败 TransientAttempt, ...]}
        #     （at 单调秒供滑窗剔除；spec/run_id/provider 供触发时聚合注入
        #     告警上下文，design D1——两处记账点 MUST 同构经统一助手写入）
        #   _transient_break_until: 全局冻结到期单调秒（0 = 未冻结）
        self._transient_break_events: Dict[str, list] = {}
        self._transient_break_until: float = 0.0

        # evo-sigterm-source-tracking-cooldown：信号死法（143/-9）冷却态（spec 维度）。
        # 进程内存、不落盘（daemon 重启清零，重启即视为恢复）：
        #   {spec_name: {"count": int, "cooldown_until": float}}
        # count = 连续信号死法次数，cooldown_until = 冷却到期单调秒。
        # 冷却只作用于该 spec 的重派（跳过派发、不耗预算、不起进程），MUST NOT
        # 写 record_transient_error / _transient_break_until 全局瞬断熔断。
        self._signal_kill: Dict[str, dict] = {}

    @staticmethod
    def parse_api_error_status(error_text: str) -> Optional[int]:
        """从 claude CLI 错误输出解析网关返回的 HTTP 状态码（fix-stashpop-deadlock）。

        claude CLI 在 provider 网关 4xx 时把错误打到 stderr，典型形如
        ``HTTP 404`` / ``API error (404)`` / ``status code 401``；网关经 SDK 包装时
        也可能出现 ``unrecognized_model``（对应 404）等字样。这里只认明确解析出的数字
        状态码（design D4）；解析不到返回 None（视为非 4xx、不计数、探针失败也不计数——
        R2 防护：避免把偶发解析不出 code 的响应误判闭合）。

        返回解析出的 int 状态码（所有已识别的 3 位码，含 5xx——code-review
        item 6f50f872a842：旧 docstring 声称「非 4xx 返回 None」与实现不符，
        classify_switch_error 恰依赖 5xx 的返回值驱动链前进）；调用方 MUST 自行
        按 ``PROVIDER_CIRCUIT_4XX`` 成员检查区分 4xx 与其它码。
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
        # 1) unrecognized_model 文本（add-impl-selfcheck-model-probe 2.1：判定
        #    MUST 先于 4xx code 解析——拒模型几乎总伴随 404 形态，先走 code
        #    解析会命中「4xx 不切换」提前返回，链永远不前进，正是设计要修的
        #    「误入熔断计数且不切链」盲区。拒模型是确定性失败：唯一正确处置
        #    就是切下一链候选；今日真实故障：inferaiapi/aliyun 各自拒绝
        #    deepseek 变体）。命中即与 classify_unrecognized_model_error 同判
        #    （后者是本判定的真子集）。
        for pat in SWITCH_ERROR_TEXT_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True
        # 2) HTTP 5xx（5xx 属瞬态网关故障，驱动切换；5xx 的 code 解析不出也算失败但会被
        #    下方连接/文本兜底覆盖）。先排除明确 4xx（解析出的 4xx 不触发切换）。
        code = ProviderCircuit.parse_api_error_status(text)
        if code is not None:
            if code in PROVIDER_CIRCUIT_4XX:
                return False  # 4xx 配额/鉴权：交既有熔断，不切换
            if 500 <= code <= 599:
                return True  # 5xx：切换
        # 3) 连接类异常（网络错误 / DNS / 超时 / 连接拒绝）——瞬态，切换
        for pat in SWITCH_ERROR_CONN_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def classify_unrecognized_model_error(error_text: str) -> bool:
        """判断错误文本是否属于「拒模型」确定性失败（add-impl-selfcheck-model-probe 2.1）。

        仅严格匹配 unrecognized_model 结构化类别（stderr
        ``[claude-code:unrecognized_model]`` 或等价文本形态）。5xx / 超时 /
        连接类 / 4xx 配额鉴权等其余错误 MUST NOT 命中（处理路径行为不变，
        回归断言固化）——本判定是 ``classify_switch_error`` 的**真子集**，
        独立存在的原因是拒模型要按确定性失败收窄处理（不进瞬断通道，
        见 UNRECOGNIZED_MODEL_TEXT_PATTERNS 注释）。

        Args:
            error_text: claude CLI 打到 stderr / 被 runner 转成 str 的错误文本。
        """
        if not error_text:
            return False
        for pat in UNRECOGNIZED_MODEL_TEXT_PATTERNS:
            if re.search(pat, error_text, re.IGNORECASE):
                return True
        return False

    def record_unrecognized_model(self, provider_name, model, run_id,
                                  spec_name: str = "") -> None:
        """拒模型识别命中即记 WARNING（add-impl-selfcheck-model-probe 2.1 ①）。

        含 provider / model / run_id（设计 D3 ①），供链摘除决策：同一
        (provider, model) 反复出现本告警即应人工摘除该链条目
        （docs/help/13-model-chain-ops.md）。仅告警留痕，不改变任何计数。
        """
        self._pm.logger.warning(
            "agent_runner",
            f"Unrecognized model rejected by provider "
            f"(add-impl-selfcheck-model-probe) — provider={provider_name!r} "
            f"model={model!r} run_id={run_id!r} spec={spec_name!r}: "
            f"deterministic model failure, advancing chain without "
            f"transient/same-cause counting; consider removing this chain entry "
            f"(see docs/help/13-model-chain-ops.md)",
        )

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
                "switch_cooldown_until": 0.0,  # 切换类错误冷却到期时间戳（add-provider-failover）
            }
            self.provider_circuits[provider_name] = st
        return st

    def is_circuit_open(self, provider_name: str, now: float | None = None) -> bool:
        """判断某 provider 当前是否处于熔断拦截态（open 且冷却未到期）。

        冷却到期即放行（无单探针门控）：冷却到期后的每次派发都等价于探针——
        成功收工时 ``_record_provider_probe(success=True)`` 闭合（runner 收尾）、
        仍 4xx 时由 runner 的半开判据调 ``_record_provider_probe(success=False)``
        重新冷却（不计入窗口计数）。与本文件其余熔断字段的实现一致
        （code-review item dff73c446d83：旧 docstring 声称的「半开门控」并不存在）。
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
        # 数值钳制（code-review item 7729e93d1efe，与 _record_provider_4xx 同口径）：
        # 非数值配置会让 now + cooldown 抛 TypeError，0/负数静默禁用冷却。
        cooldown = self._positive_number(
            self._pm._get_config(
                "pm.failover.switch_cooldown_seconds", PROVIDER_SWITCH_COOLDOWN_SECONDS
            ),
            PROVIDER_SWITCH_COOLDOWN_SECONDS,
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
        run_file = runs_dir / f"{run_id}.jsonl"
        try:
            # mkdir 移入 try（code-review item b42d9b865018）：旧实现 mkdir 在
            # try 外，权限/只读盘下的 OSError 会从标记写入中途逃逸，打断 attempt
            # 启动；且写失败被 `except OSError: pass` 静默吞掉，丢失 provider
            # 可追溯性而无任何痕迹。现 mkdir 一并守卫，失败记 WARNING。
            runs_dir.mkdir(parents=True, exist_ok=True)
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
        except OSError as e:
            self._pm.logger.warning(
                "agent_runner",
                f"provider_marker 写入失败 {run_file}（不阻断 attempt）: {e}",
            )

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
        raw_warn = self._pm._get_config(
            "pm.failover.daily_attempts_warn", PROVIDER_DAILY_ATTEMPTS_WARN
        )
        # 防御转换（code-review item c945454d3b4d）：非数字配置（如 "50"）原样
        # 参与 count > warn 比较会在 attempt 记账时抛 TypeError 打断记账。数字
        # 字符串/浮点转 int；bool（int 子类）按畸形回默认；0/None 保留「禁用
        # 告警」语义，负值无意义同禁用——不走 _positive_number（其把 0 归一
        # 为默认值，会复活显式关闭的告警）。
        warn: int | None = None
        if raw_warn is not None and type(raw_warn) is not bool:
            try:
                warn = int(raw_warn)
            except (TypeError, ValueError):
                warn = PROVIDER_DAILY_ATTEMPTS_WARN
        if (
            warn is not None
            and warn > 0
            and count > warn
            and not self._daily_provider_warned.get(provider_name, False)
        ):
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

    def record_transient_error(
        self,
        error_text: str,
        now: float | None = None,
        *,
        spec: str | None = None,
        run_id: str | None = None,
        provider: str | None = None,
    ) -> bool:
        """记录一次瞬断错误，窗口内同指纹累计 → 达阈值触发全局熔断。

        每次 attempt 除指纹时间戳外同时记账元信息（spec/run_id/provider/at，
        design D1）——触发熔断时聚合注入告警上下文，对指纹归一化免疫。
        spec/run_id/provider 为**可选关键字**参数（缺省 None → 空串占位并正常
        记账，MUST NOT 阻断熔断记账）；``now`` 保持第二位置参数（既有调用点以
        ``("…", now=…)`` 与 ``("x", 1)`` 两种形态调用，缺省 None → 既有调用点
        与既有测试零改动）。两处记账点（正常路径 / 已冻结早退分支）MUST 经
        同一内部助手 ``_append_transient_event`` 写入，保证元素结构一致。

        Returns:
            True 表示本次记录**触发了**全局熔断（首次达阈值）；False 表示未触发
            （未达阈值 / 已在熔断中 / 指纹为空）。
        """
        fingerprint = self.normalize_transient_fingerprint(error_text)
        if not fingerprint:
            return False
        if self.is_global_transient_break(now=now):
            # 已冻结中：只记账不重复触发/告警（冷却到期由查询侧清零重记）。
            # 早退分支 MUST 与正常路径同构经同一助手写入 TransientAttempt
            #（含同一份元信息），否则滑窗剔除对混合元素类型取值失败（design D1）。
            self._append_transient_event(
                fingerprint,
                now if now is not None else self._pm._now(),
                spec=spec,
                run_id=run_id,
                provider=provider,
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
        self._append_transient_event(
            fingerprint, now, spec=spec, run_id=run_id, provider=provider, window=window
        )
        events = self._transient_break_events[fingerprint]
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
            # 触发时构建窗口内 attempt 聚合清单（design D2，对指纹归一化免疫）：
            # ERROR 日志与升级信号上下文并列注入，可定位风暴来源 provider/run。
            attempt_summary, truncated = self._build_attempt_summary(events)
            self._alert_transient_break(
                fingerprint, len(events), window, attempt_summary, truncated
            )
            self._pm.logger.error(
                "agent_runner",
                f"Global transient break TRIGGERED for fingerprint '{fingerprint}' "
                f"({len(events)} failures within {int(window)}s window) — "
                f"freezing all new run dispatch for "
                f"{int(self._transient_break_until - now)}s "
                f"(fix-provider-transient-backoff D4); failed attempts: "
                f"{json.dumps(attempt_summary, ensure_ascii=False)}"
                + (f"; truncated={truncated}" if truncated else ""),
            )
            return True
        return False

    def _append_transient_event(
        self,
        fingerprint: str,
        now: float,
        spec: str | None = None,
        run_id: str | None = None,
        provider: str | None = None,
        window: int | None = None,
    ) -> None:
        """统一经本助手写入一条瞬断事件（design D1：两处记账点 MUST 同构）。

        正常记账路径与已冻结早退路径都经本助手写入 TransientAttempt——任一处
        保留裸时间戳都会让滑窗剔除 ``now - t``（provider_circuit.py:420）与
        D2 聚合对混合元素类型报错/取值失败。window 非 None 时先滑出窗口外旧
        事件（按 ``at`` 时间戳剔除，行为不变；早退分支不剔除——与既有语义
        一致）。元信息缺省 None → 空串占位并正常记账，MUST NOT 阻断熔断记账。
        """
        events = self._transient_break_events.setdefault(fingerprint, [])
        if window is not None and window > 0:
            events = [t for t in events if now - t.at <= window]
        # 墙钟时刻与单调 now 一并固化：告警上下文展示用 at_wall（真实时钟），
        # 滑窗用 at（单调，防时钟回拨）。code-review item cbaa42ed2281。
        events.append(
            TransientAttempt(
                spec=spec or "",
                run_id=run_id or "",
                provider=provider or "",
                at=now,
                at_wall=time.time(),
            )
        )
        self._transient_break_events[fingerprint] = events

    @staticmethod
    def _build_attempt_summary(events: list, limit: int = TRANSIENT_BREAK_ATTEMPT_LIST_LIMIT):
        """把窗口内 TransientAttempt 列表聚合为有界清单（design D2，纯函数）。

        返回 ``(summary, truncated)``：summary 为 ``[{"run_id", "spec",
        "provider", "at": <ISO>}]``（事件按写入序、最新在后，取最近 limit 条）；
        超出 limit 时 truncated = 被略去条数。聚合对指纹归一化免疫——即使指纹
        只剩 ``<model>`` 占位，清单仍列出真实 provider/run_id。
        """
        out = []
        truncated = 0
        if events:
            total = len(events)
            if total > limit:
                truncated = total - limit
            for ev in events[-limit:]:
                out.append(
                    {
                        "run_id": ev.run_id,
                        "spec": ev.spec,
                        "provider": ev.provider,
                        "at": datetime.fromtimestamp(
                            getattr(ev, "at_wall", ev.at), timezone.utc
                        ).isoformat(),
                    }
                )
        return out, truncated

    def is_global_transient_break(self, now: float | None = None) -> bool:
        """全局是否处于瞬断熔断冻结期（派发闸门查询）。

        冷却到期自动解除并清零窗口内指纹计数（重新起算，与 is_instant_fail_cooled
        到期恢复语义一致）；无冻结 / 已到期返回 False（恢复派发）。

        到期分支内联自动核销对应 transient_break_storm 告警（design D3）——
        本代码库无到期事件分发机制，核销 MUST 复用本过期分支（幂等、可测），
        不做轮询/异步扫描。冻结到期后无人查询（如 dispatch 闸门的 shutting_down /
        已抑制条目早退分支先返回、跳过本方法）的路径不产生核销动作，由
        admin_alerts.json 的 MAX_RECORDS=150 环形裁剪（core/admin_store.py:34,
        193-194）与人工/Dashboard 处置承接——本仓库不存在按时间的告警清理机制。
        """
        if self._transient_break_until <= 0:
            return False
        now = self._pm._now() if now is None else now
        if now >= self._transient_break_until:
            # 核销摘要：清零前聚合窗口内全部 attempt（跨指纹扁平化，供
            # resolve_note 的「聚合清单摘要」留审计——design D3 第 2 点）。
            summary, truncated = self._build_attempt_summary(
                [ev for evs in self._transient_break_events.values() for ev in evs]
            )
            self._transient_break_until = 0.0
            self._transient_break_events.clear()
            self._pm.logger.warning(
                "agent_runner",
                "Global transient break expired — dispatch resumed, "
                "fingerprint window reset",
            )
            # 熔断自然过期主动唤醒派发（见 _wake_dispatch_after_break 文档）。
            self._wake_dispatch_after_break()
            # 熔断自然过期自动核销（紧邻 WARNING 之后；异常静默不阻断闸门语义）
            self._auto_resolve_transient_storm(summary, truncated)
            return False
        return True

    def _wake_dispatch_after_break(self) -> None:
        """熔断自然过期后主动唤醒派发队列（最小改动缺口修复）。

        背景（2026-09-22 事故取证）：``_process_queue`` 的首道闸门
        （``core/pm_engine/dispatch/queue.py`` ``_global_transient_break_active``）
        在熔断期直接 return——解冻/恢复产生的 ``spec_ready`` 虽经 ``_on_spec_ready``
        入队成立，队列条目却出不来。而本组件是**惰性自清**的：仅在被查询时才检
        测到期。「熔断到期」与「有人查询队列」两个事件若彼此错开，被挡下的条目
        只能等下一个人为触发点（实测为 60s 一轮的 ``recover_orphan_ready``，最坏
        ~60s 额外延迟；本轮因解冻比到期早约 4 分钟，表现为「解冻后完全没派发」）。

        到期即在此处显式唤醒：经 PMEngine 门面触发一次 ``_process_queue``，把
        熔断期积压的队列条目立即放出。唤醒 MUST NOT 递归——``_process_queue``
        再次查询本方法时熔断已清零（上方赋值先于调用），返回 False 放行。

        fail-open：任何异常静默吞掉，绝不阻断「熔断到期 → 恢复派发」这一闸门
        语义（对齐既有 _auto_resolve 的异常处理取向）。无 PMEngine 回引
        （测试 / CLI 场景，``AgentRunner`` 以 ``__new__`` 构造）时零操作。
        """
        pm_engine = getattr(self._pm, "_pm_engine_ref", None)
        process_queue = getattr(pm_engine, "_process_queue", None)
        if not callable(process_queue):
            return
        try:
            process_queue()
        except Exception as e:
            self._pm.logger.warning(
                "agent_runner",
                f"熔断到期唤醒派发失败（不阻断恢复）: {e}",
            )

    def _alert_transient_break(
        self,
        fingerprint: str,
        count: int,
        window: int,
        attempt_summary: list | None = None,
        truncated: int = 0,
    ) -> None:
        """触发全局瞬断熔断时发 major 告警（15 分钟节流去重）。

        与 _alert_instant_fail_storm 同构：AdminStore.latest_signal 按
        (spec, signal_type) 在窗口内查重，窗口内已有同信号则不发第二条。
        attempt_summary（窗口内失败 attempt 聚合清单，design D2）注入
        description 与 evidence——对指纹归一化免疫（指纹只剩 <model> 时清单
        仍列出真实 provider/run_id）。清单有界（N=20，超出追加 truncated）。
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
            summary_json = json.dumps(attempt_summary or [], ensure_ascii=False)
            truncated_suffix = f"; truncated={truncated}" if truncated else ""
            store.append(
                {
                    "kind": ESCALATION,
                    "signal_type": "transient_break_storm",
                    "spec": "global-transient",
                    "severity": "major",
                    "description": (
                        f"全局瞬断风暴：错误指纹 '{fingerprint}' 在 {int(window)}s 窗口内 "
                        f"出现 {count} 次 — 已冻结全部新 run 派发，冷却期内不再启动新 run"
                        f"；窗口内失败 attempt：{summary_json}"
                        + (f"（截断 {truncated} 条）" if truncated else "")
                    ),
                    "evidence": (
                        f"fingerprint={fingerprint}; count={count}; "
                        f"window_seconds={int(window)}; "
                        f"cooldown_seconds={int(self._transient_break_until - self._pm._now())}; "
                        f"failed_attempts={summary_json}{truncated_suffix}"
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

    def _auto_resolve_transient_storm(
        self, attempt_summary: list | None = None, truncated: int = 0
    ) -> None:
        """熔断自然过期 → 自动核销 transient_break_storm 告警（design D3）。

        定位「窗口内最新**未处理**」告警（Requirement 4）：latest_signal 不做
        handled 过滤（core/admin_store.py:432-436），窗口内更新的已处理条目
        （人工/Dashboard 标记或上一轮熔断已自动核销）会抢先命中——候选已
        handled 时向前继续找窗口内更早的未处理者（spec 场景「最新同类告警已
        处理时核销仍生效」）；无未处理候选（含窗口内全部已处理）→ 零操作、
        零写回。

        核销经既有 AdminStore.auto_resolve 通道（core/admin_store.py:345-378）：
        handled=True + handled_by="auto-resolve" + resolve_note（核销原因=熔断
        自然过期 + 聚合清单摘要）留审计。不引入新告警 kind；MUST NOT 复用
        alert_lifecycle.find_resolvable（其判定输入为 spec 状态表，
        global-transient 不在 STATE.md 状态表中 → 该路径永不命中）。

        锚点口径（design D3）：latest_signal 窗口锚点取 created（escalation
        记录不带 last_seen，core/admin_store.py:443-455）；窗口下限 = 冻结时长
        （agents.transient_break_cooldown_seconds，与 record_transient_error
        记账处同一 ``_get_config`` 取用）换算分钟数 + 时钟域偏差裕量——冻结期
        以 ``time.monotonic`` 计、告警 created 为墙钟 ISO（_utcnow_iso），二者
        非同源，用严格等长窗口会因偏差漏配；MUST NOT 照抄既有 15 分钟节流
        口径（该锚点仅用于「近 15 分钟内是否已发同类告警」的查重，语义不同）。
        缺省不小于 60 分钟。

        异常静默（try/except 沿用告警写入风格）：MUST NOT 阻断
        is_global_transient_break 的闸门/fail-open 语义（该方法被 dispatch
        闸门查询路径调用，core/pm_engine/dispatch/queue.py:172）。
        """
        try:
            from core.admin_store import AdminStore

            store = AdminStore(self._pm.project_root, self._pm.logger)
            cooldown = int(
                self._pm._get_config(
                    "agents.transient_break_cooldown_seconds",
                    TRANSIENT_BREAK_COOLDOWN_SECONDS,
                )
                or 0
            )
            # 冻结时长分钟数 + 偏差裕量（时钟域偏差，见 docstring）；缺省不小于 60 分钟
            anchor_minutes = max(60, cooldown // 60 + 2)
            candidate = store.latest_signal(
                "global-transient", "transient_break_storm", anchor_minutes
            )
            if candidate is None:
                return  # 窗口内无对应告警：零操作、零写回
            if candidate.get("handled") is True:
                # 最新候选已处理——向前找窗口内更早的未处理者（Requirement 4
                # 场景）；找不到（含窗口内全部已处理）→ 零操作、零写回。
                candidate = self._latest_unhandled_storm(store, anchor_minutes)
                if candidate is None:
                    return
            note = (
                "熔断自然过期自动核销（dispatch resumed）："
                f"failed_attempts={json.dumps(attempt_summary or [], ensure_ascii=False)}"
                + (f"; truncated={truncated}" if truncated else "")
            )
            store.auto_resolve(
                [
                    {
                        "id": candidate.get("id"),
                        "spec": "global-transient",
                        "resolve_note": note,
                    }
                ]
            )
            self._pm.logger.info(
                "agent_runner",
                f"transient_break_storm 告警自动核销（熔断自然过期）: "
                f"id={candidate.get('id')}",
            )
        except Exception as e:
            self._pm.logger.error(
                "agent_runner",
                f"transient_break_storm 自动核销失败（不阻断过期解除）: {e}",
            )

    @staticmethod
    def _latest_unhandled_storm(store, anchor_minutes: int) -> Optional[dict]:
        """返回窗口内最新一条**未处理** transient_break_storm 告警（Requirement 4）。

        latest_signal 不做 handled 过滤，窗口内更新的已处理条目会抢先命中；
        本查询跳过已处理候选，直接选「窗口内最新未处理」者。read_all 按
        created 倒序返回，首个命中即最新。窗口边界与 latest_signal 同口径
        （created 锚点 + 分钟窗口）。无命中返回 None（零操作）。MUST NOT
        改写已处理条目。
        """
        if not anchor_minutes or anchor_minutes <= 0:
            return None
        cutoff = time.time() - anchor_minutes * 60
        for rec in store.read_all():
            if rec.get("kind") != "escalation":
                continue
            if rec.get("signal_type") != "transient_break_storm":
                continue
            if rec.get("spec") != "global-transient":
                continue
            if rec.get("handled"):
                continue
            try:
                created = datetime.fromisoformat(
                    (rec.get("created") or "").replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue
            if created.timestamp() < cutoff:
                continue
            return rec
        return None

    # ── 信号死法冷却（evo-sigterm-source-tracking-cooldown）────────────────
    # spec 维度的信号死法（143/-9）连续计数 → 达阈值触发该 spec 冷却。与秒挂
    # 冷却（runner._record_instant_fail）并存：同一事件双记仅累加（信号死法若
    # 同时是秒挂，两条通道各自计数），冷却截止各自独立——dispatch 侧 OR 判定
    # 使两条通道对同一事件互不覆盖冷却截止（取更晚者生效）。

    def record_signal_kill(self, spec_name: str, now: float | None = None) -> bool:
        """记录一次信号死法（143/-9），同 spec 连续计数 → 达阈值触发该 spec 冷却。

        只作用于该 spec 的重派（dispatch 跳过派发、不耗预算、不起进程），
        MUST NOT 写 record_transient_error / _transient_break_until 全局瞬断
        熔断（不得冻结全项目新派发）。触发时写 major 告警（15 分钟节流）。

        Returns:
            True 表示本次记录后该 spec 处于冷却期（本次触发或已在冷却）；
            False 表示未触发（未达阈值）。
        """
        if not spec_name:
            return False
        now = self._pm._now() if now is None else now
        st = self._signal_kill.setdefault(
            spec_name, {"count": 0, "cooldown_until": 0.0})
        st["count"] = int(st.get("count", 0)) + 1
        if st.get("cooldown_until", 0.0) > now:
            # 已在冷却期内：仅累加计数，不重复触发/告警（冷却到期由查询侧恢复）。
            return True
        after = self._signal_kill_cooldown_after()
        if st["count"] < after:
            self._pm.logger.warning(
                "agent_runner",
                f"'{spec_name}' 信号死法 {st['count']}/{after} "
                f"（evo-sigterm-source-tracking-cooldown 计数）",
            )
            return False
        # 达阈值：进入该 spec 冷却
        cooldown_seconds = self._signal_kill_cooldown_seconds()
        st["cooldown_until"] = now + cooldown_seconds
        self._pm.logger.error(
            "agent_runner",
            f"'{spec_name}' 连续 {st['count']} 次信号死法（阈值 {after}）— "
            f"进入 {cooldown_seconds}s 冷却，期间该 spec 重派被跳过；"
            f"冷却到期自动恢复（evo-sigterm-source-tracking-cooldown）",
        )
        self._alert_signal_kill_storm(spec_name, st["count"], cooldown_seconds)
        return True

    def is_signal_kill_cooldown(self, spec_name: str,
                                now: float | None = None) -> bool:
        """该 spec 是否处于信号死法冷却期（dispatch 派发前闸门调用）。

        冷却到期自动恢复并清零计数（与 is_instant_fail_cooldown 同构）；恢复时
        写一条 major 告警（15 分钟节流，signal_type=signal_kill_recovered）。
        无条目 / 未进入冷却返回 False。
        """
        if not spec_name:
            return False
        st = self._signal_kill.get(spec_name)
        if not st:
            return False
        until = st.get("cooldown_until") or 0.0
        if until <= 0:
            return False
        now = self._pm._now() if now is None else now
        if now >= until:
            # 冷却到期自动恢复：清零计数，写恢复告警（节流抑制重复）。
            self._pm.logger.warning(
                "agent_runner",
                f"'{spec_name}' 信号死法冷却到期 — 自动恢复派发，计数清零"
                f"（evo-sigterm-source-tracking-cooldown）",
            )
            self._alert_signal_kill_recovered(spec_name)
            self._signal_kill.pop(spec_name, None)
            return False
        return True

    def signal_kill_cooldown_until(self, spec_name: str) -> float:
        """该 spec 信号死法冷却到期单调秒（未冷却/无条目返回 0；派发恢复排程用）。"""
        st = self._signal_kill.get(spec_name)
        if not st:
            return 0.0
        try:
            return float(st.get("cooldown_until") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def signal_kill_counts(self, spec_name: str) -> int:
        """当前连续信号死法次数（测试/观测辅助）。"""
        st = self._signal_kill.get(spec_name)
        return int(st.get("count", 0)) if st else 0

    def reset_signal_kill(self, spec_name: str) -> None:
        """成功 / 冷却到期：清除该 spec 的信号死法连续计数与冷却态。"""
        self._signal_kill.pop(spec_name, None)

    def _signal_kill_cooldown_after(self) -> int:
        """信号冷却阈值（agents.signal_kill_cooldown_after，缺省 3）。"""
        try:
            v = int(self._pm._get_config(
                "agents.signal_kill_cooldown_after",
                SIGNAL_KILL_COOLDOWN_AFTER) or SIGNAL_KILL_COOLDOWN_AFTER)
        except (TypeError, ValueError):
            v = SIGNAL_KILL_COOLDOWN_AFTER
        return max(1, v)

    def _signal_kill_cooldown_seconds(self) -> int:
        """信号冷却时长（agents.signal_kill_cooldown_seconds，缺省 600）。"""
        try:
            v = int(self._pm._get_config(
                "agents.signal_kill_cooldown_seconds",
                SIGNAL_KILL_COOLDOWN_SECONDS) or SIGNAL_KILL_COOLDOWN_SECONDS)
        except (TypeError, ValueError):
            v = SIGNAL_KILL_COOLDOWN_SECONDS
        return max(1, v)

    def _alert_signal_kill_storm(self, spec_name: str, count: int,
                                 cooldown_seconds: int) -> None:
        """信号死法冷却触发时发 major 告警（signal_type=signal_kill_storm）。

        重复冷却由既有 15 分钟 throttle 抑制：AdminStore.latest_signal 按
        (spec, signal_type) 在窗口内查重，窗口内已有同信号则不发第二条。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION
            store = AdminStore(self._pm.project_root, self._pm.logger)
            if store.latest_signal(spec_name, "signal_kill_storm",
                                   SIGNAL_KILL_ALERT_THROTTLE_MINUTES) is not None:
                self._pm.logger.debug(
                    "agent_runner",
                    f"signal_kill_storm 告警已 throttle（15 分钟内已有）: '{spec_name}'",
                )
                return
            store.append({
                "kind": ESCALATION,
                "signal_type": "signal_kill_storm",
                "spec": spec_name,
                "severity": "major",
                "description": (
                    f"spec '{spec_name}' 连续 {count} 次信号死法（Exit 143/-9，"
                    f"来源待考）— 已进入 {cooldown_seconds}s 冷却，期间该 spec "
                    f"重派被跳过；冷却到期自动恢复"
                ),
                "evidence": (
                    f"spec={spec_name}; signal_kill_count={count}; "
                    f"cooldown_seconds={cooldown_seconds}"
                ),
                "recommended_action": (
                    "检查子进程被信号杀死的外部原因（资源回收/外部 kill/CLI 自身）；"
                    "冷却自动到期后恢复，无需人工干预；若反复触发请核对 daemon 关停"
                    "时序与 supervision 强杀路径是否被误归为外部信号"
                ),
            })
        except Exception as e:
            self._pm.logger.error(
                "agent_runner",
                f"signal_kill_storm 告警写入失败 '{spec_name}': {e}",
            )

    def _alert_signal_kill_recovered(self, spec_name: str) -> None:
        """信号死法冷却到期恢复时发 major 告警（signal_type=signal_kill_recovered）。

        与 _alert_signal_kill_storm 同构：15 分钟节流去重。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION
            store = AdminStore(self._pm.project_root, self._pm.logger)
            if store.latest_signal(spec_name, "signal_kill_recovered",
                                   SIGNAL_KILL_ALERT_THROTTLE_MINUTES) is not None:
                self._pm.logger.debug(
                    "agent_runner",
                    f"signal_kill_recovered 告警已 throttle（15 分钟内已有）: '{spec_name}'",
                )
                return
            store.append({
                "kind": ESCALATION,
                "signal_type": "signal_kill_recovered",
                "spec": spec_name,
                "severity": "major",
                "description": (
                    f"spec '{spec_name}' 信号死法冷却到期，重派已恢复"
                ),
                "evidence": f"spec={spec_name}",
                "recommended_action": (
                    "无需人工干预；若信号死法再次连发将重新冷却"
                ),
            })
        except Exception as e:
            self._pm.logger.error(
                "agent_runner",
                f"signal_kill_recovered 告警写入失败 '{spec_name}': {e}",
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

    @staticmethod
    def _positive_number(value, default) -> float:
        """把配置值容错归一为正数（失败/非正 → default）。

        与 _signal_kill_cooldown_seconds 同口径（code-review item 12595e41e08f）：
        provider_circuit 的 window/threshold/cooldown 此前直接消费原始配置值，
        非数值（字符串）会让滑窗过滤在失败路径抛 TypeError，0/负数则让熔断瞬间
        失效。此处统一钳制——不可解析或 <= 0 时回落常量缺省，保证熔断语义始终成立。
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return float(default)
        if v != v or v in (float("inf"), float("-inf")):  # NaN / inf 兜底
            return float(default)
        if v <= 0:
            return float(default)
        return v

    def _record_provider_4xx(self, provider_name: str, code: int, now: float | None = None) -> None:
        """记录一次 provider 网关 4xx，按滚动窗口计数，达阈值置 open。

        5xx / 网络错误不调用本方法（design D4）。窗口外的旧事件先滑出。
        """
        if not provider_name:
            return
        now = self._pm._now() if now is None else now
        st = self._circuit_state(provider_name)
        # 数值容错（code-review item 12595e41e08f）：window/threshold/cooldown 直接
        # 取配置并参与 `now - t <= window` / `>= threshold` / `now + cooldown`——若
        # 用户写入非数值（字符串）会在此抛 TypeError 打挂 provider 失败路径；0/负数
        # 冷却则让熔断瞬间失效。与本文件 signal-kill 助手同口径：
        # try/except (TypeError, ValueError) + 下限钳制。
        window = self._positive_number(
            self._pm._get_config(
                "agents.provider_circuit_window_seconds", PROVIDER_CIRCUIT_WINDOW_SECONDS
            ),
            PROVIDER_CIRCUIT_WINDOW_SECONDS,
        )
        threshold = self._positive_number(
            self._pm._get_config(
                "agents.provider_circuit_threshold", PROVIDER_CIRCUIT_THRESHOLD
            ),
            PROVIDER_CIRCUIT_THRESHOLD,
        )
        cooldown = self._positive_number(
            self._pm._get_config(
                "agents.provider_circuit_cooldown_seconds", PROVIDER_CIRCUIT_COOLDOWN_SECONDS
            ),
            PROVIDER_CIRCUIT_COOLDOWN_SECONDS,
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
        # 数值钳制（code-review item 7729e93d1efe，与 _record_provider_4xx 同口径）：
        # 非数值配置会让 now + cooldown 抛 TypeError，0/负数静默禁用重冷却。
        cooldown = self._positive_number(
            self._pm._get_config(
                "agents.provider_circuit_cooldown_seconds", PROVIDER_CIRCUIT_COOLDOWN_SECONDS
            ),
            PROVIDER_CIRCUIT_COOLDOWN_SECONDS,
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
        else:
            st["cooldown_until"] = now + cooldown
            self._pm.logger.warning(
                "agent_runner",
                f"Provider circuit re-cooled for '{provider_name}' — probe still failing, "
                f"cooldown {int(cooldown)}s",
            )
