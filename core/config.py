"""
config.py — Configuration loader for fenixd.

Reads and validates config.yaml, providing typed access to all settings.
"""

import copy
import logging
import math
import os
import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .alert_lifecycle import DEFAULT_SELF_HEAL_QUIET_MINUTES

# 用户级配置目录：与项目级同名 `.fenix/config.yaml`，作用域由所在目录决定
USER_CONFIG_DIR = Path.home() / ".fenix"

_logger = logging.getLogger("fenixd.config")

# ── fix-stuck-threshold-unify：stuck 阈值单源派生 ──────────────────
# D1：派生宽限常量（秒），非配置项。阈值 = run_timeout_seconds + 该宽限，
# 保证 runner 自身超时终止与 auto-recovery 恢复判定之间留确定性时序余量。
STUCK_GRACE_SECONDS = 600
# D4：run_timeout_seconds 缺失或 ≤0 时的派生回退基准（9000+600=9600）。
RUN_TIMEOUT_FALLBACK_SECONDS = 9000
STUCK_FALLBACK_SECONDS = RUN_TIMEOUT_FALLBACK_SECONDS + STUCK_GRACE_SECONDS
# planned-restart-drain D1：规划性重启排水窗口相对 supervisor SIGKILL 等待的
# 终止收口安全余量（秒）——保证超窗有序终止（SIGTERM+宽限+SIGKILL）与 sidecar
# 保全收口不被 supervisor 截断。取值 ≥10s 且不小于单 run terminate 宽限
# （core/agent_runner/liveness.py AGENT_TERMINATE_GRACE_SECONDS）。
PLANNED_DRAIN_TERMINATE_MARGIN_SECONDS = 10
# D5：supervision 超时监督默认值（单源派生，supervision-timeout-config-consistency）。
# 单次续期 extension_seconds、次数上限 max_extensions、总墙钟上限 absolute_max_seconds
# （命中即无条件终止，封闭续期的成本风险）、活性判定窗口 judge_window（秒）。
# 本表由 liveness 运行时（_supervision_settings）与 supervision 下限派生共用，
# 禁止两处各自手写常数（消除 22200/18600 双份表述）。
SUPERVISION_DEFAULTS = {
    "enabled": True,
    "extension_seconds": 1800,
    "max_extensions": 2,
    "absolute_max_seconds": 7200,
    "judge_window": 600,
}
# fast-track higher 档（_fast_track_scale_tier == "higher"）的续期预算加成：
# 默认 max_extensions 2 → 4，使大任务面 spec 获得更充足超时预算。配置校验层
# 下限按「最大可达续期预算」取 max_extensions + 该加成（保守口径，与 liveness
# 运行时 fast-track 加成语义一致；仅在基础预算 2×1800 时，higher 档运行时仍
# 命中同文案 ERROR，「消除 ERROR 复发」目标落空——实测依据见 proposal）。
SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS = 2

# ── evo-add-impl-wallclock-budget-sizing 1.3：impl 车道墙钟 sizing 缺省 ────
# 档位函数（core/fast_track_result.get_impl_wallclock_sizing_config）与设置
# 读侧共用的单点缺省（禁两处手写，沿 SUPERVISION_DEFAULTS 单源纪律）：
# - enabled：sizing 总开关，缺省开（大 spec 抬续期预算，消除 potplayer 形
#   「轮数 sizing 已生效但墙钟仍烧满硬上限被 SIGKILL」主浪费段）；
# - full_scale_threshold：规模阈值，**严格大于**才抬（与 budget_tier_for_scale /
#   轮数 sizing 判定形态同源），缺省与轮数 sizing 同值 45（语义独立不共用常量，
#   两处阈值后续可独立收敛）；
# - extra_extensions：抬升幅度（max_extensions += extra），泛化 fast-track
#   higher 档 +2 先例（SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS）。
# absolute_max_seconds 封顶语义不变：sizing 只扩「续期预算」，不触碰绝对上限
# （防失控 run 无限独占车道）。supervision_floor 协同复核结论（design 决策 5）：
# 运行时下限由 liveness 以抬升后的实际续期预算作 extension_budget 入参派生
# （liveness 先抬 max_extensions、后调 supervision_floor，与 fast-track higher
# 档同机制），configured_abs_max < floor 时既有 ERROR 守护与抬升兜底照常生效，
# 本表新增键不触碰 supervision_floor / supervision_config_floor 派生公式；
# 配置校验层最大下限（supervision_config_floor）仍按 fast-track 最大部署口径，
# impl sizing 抬得更高时走运行时 ERROR + 抬升兜底路径（有界：续期轮次有限）。
IMPL_WALLCLOCK_SIZING_DEFAULTS = {
    "enabled": True,
    "full_scale_threshold": 45,
    "extra_extensions": 2,
}

# ── add-bug-repair-mode-config：admin.bug_repair_mode 取值枚举 ────────
# bug-found 处置的修复方式：inplace（原地打回，缺省）/ derive（派生 fix-* 子
# SPEC）。枚举而非布尔，为未来第三种修复策略留扩展位（design D1）。
VALID_BUG_REPAIR_MODES = ("inplace", "derive")

# ── add-daily-self-review：admin.self_review 段 ──────────────────────
# run_at 缺省 02:00（每晚时间点），enabled/read_todo 缺省 false（纯增量，
# 零行为变化）。run_at 非法值打 ERROR 并回退本缺省（design「Migration
# Plan」：enabled 缺省 false，开启后次日生效）。
SELF_REVIEW_DEFAULT_RUN_AT = "02:00"
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# ── add-framework-self-evolution：self_evolution 段 ──────────────────
# auto_accept 缺省 false（纯增量，用户显式开启后才自动接受）。
# max_items_per_run 缺省 20，上界 200（非法回退缺省，不阻塞 daemon 启动）。
# spec_run_at 缺省 None = 立项后立即执行（存量配置无此键即保持现状）；值为
# "HH:mm" 时表示「每日该时刻执行」——立项时把新 SPEC 的 start_after 排到下一个
# 该时刻，到点前 dispatch 静默跳过。时区口径与 admin.self_review.run_at 一致
# （本地时区；落盘 start_after 仍为 UTC ISO）。
SELF_EVOLUTION_AUTO_ACCEPT_DEFAULT = False
SELF_EVOLUTION_MAX_ITEMS_DEFAULT = 20
SELF_EVOLUTION_MAX_ITEMS_UPPER = 200
SELF_EVOLUTION_SPEC_RUN_AT_DEFAULT = None

# D3：旧键弃用告警 / D5：absolute_max 兜底 ERROR 的生命周期去重标记，
# 避免 30 分钟扫描热更新时反复刷屏。
_DEPRECATED_STUCK_WARNED = False
_SUPERVISION_BOUNDS_WARNED = False
# 运行期下限兜底 ERROR 的独立去重标记（code-review item bbfc01b9388a）：
# 与 _SUPERVISION_BOUNDS_WARNED（_check_supervision_consistency 的对齐诊断）
# 分开——共用一个标记会让先触发者压制另一条诊断整个进程生命周期。
_SUPERVISION_RUNTIME_FLOOR_WARNED = False
# supervision-timeout-config-consistency：最近一次「自动对齐」抬升到的配置层
# 下限（进程级记录，供 daemon 在 resolve_config 后经既有写路径持久化）。
# _validate 对齐时写入、daemon 消费即复位（take_supervision_alignment）；
# 未消费的残留记录会被下一次 _validate 覆盖，恒反映最新校验的配置。
_SUPERVISION_LAST_ALIGNED = None

# run 超时回退 WARNING 的进程级一次性去重标记：agents.run_timeout_seconds 缺失/
# ≤0/非有限时 effective_run_timeout_seconds 按 RUN_TIMEOUT_FALLBACK_SECONDS 回退，
# 派发路径高频读取，仿 _DEPRECATED_STUCK_WARNED「首次告警、后续静默」（原为
# stuck 阈值回退所设、与后者共用；code-review item c623952c5cef 仿
# bbfc01b9388a 拆分范式改为本读取器专属）。
_RUN_TIMEOUT_FALLBACK_WARNED = False

# stuck 阈值回退 WARNING 的独立去重标记（code-review item c623952c5cef，仿
# bbfc01b9388a 拆分范式）：effective_stuck_threshold_seconds 与
# effective_run_timeout_seconds 对同一坏键各打不同文案、不同回退值（9600s 派生
# vs 9000s）的 WARNING，共用一个标记会让先触发者压制另一条诊断整个进程生命周期。
_STUCK_FALLBACK_WARNED = False

# ── improve-hot-reload-robustness D3：未知 agent 类型键降级告警去重 ──
# 同一未知键每进程生命周期只报一次（30s 热重载重试风暴下，不去重则告警与
# ERROR 同步刷屏）。keys 以键名字符串为准，不随进程内白名单变化失效。
_UNKNOWN_AGENT_MODEL_KEYS_WARNED = set()

# 整段非 dict 降级 ERROR 的进程级一次性去重（code-review item bb5366851f4a，
# 同 _UNKNOWN_AGENT_MODEL_KEYS_WARNED 范式）：同一 (段键, 脏值类型) 只在首次
# 告警。一条读取链会反复取同一脏段（get_admin_config → get_self_review_config
# / get_run_infra_breaker_config；agents 脏段经 _validate →
# _check_supervision_consistency → normalize_timeout_overrides /
# effective_run_timeout_seconds 按 agent 类型循环取段），30s 热更新下单轮可
# 产生十余条逐字相同的 ERROR。去重只作用于告警分支，归一返回值（空段降级）
# 行为不变。
_SEGMENT_DIRTY_WARNED = set()

# 校验期 ERROR 的进程级一次性去重（code-review item eec7502eb329，同
# _SEGMENT_DIRTY_WARNED 范式）：resolve_config 每 30s 热更新全量重跑
# _validate → _validate_agent_models，「provider 引用不存在的名字」与「链元素
# 无法解析出模型名」两处 ERROR 在坏配置在场时逐周期重复打印。键取
# (agent_type, provider 名) / (agent_type, provider 名, 链元素下标)，同一坏点
# 只在首次告警；去重只作用于告警分支，校验/跳过行为不变。
_UNKNOWN_PROVIDER_REF_WARNED = set()
_UNRESOLVED_CHAIN_MODEL_WARNED = set()

# _validate 软校验 ERROR 的进程级一次性去重（code-review item a84b10635fb2，
# 同 _SEGMENT_DIRTY_WARNED / _UNKNOWN_PROVIDER_REF_WARNED 范式）：resolve_config
# 每 30s 热更新全量重跑 _validate，四处软校验（admin.self_review 整段非 dict、
# archive.auto_threshold 非法、knowledge.enabled 非法、self_evolution 段及其
# 子键 auto_accept / max_items_per_run / spec_run_at 非法）只记 ERROR 不抛错，
# 坏配置在场时逐周期重复打印同一告警。键取 (段键/键路径, 脏值类型)，同一坏点
# 只在首次告警；去重只作用于告警分支，校验/降级行为不变。
_VALIDATE_SOFT_WARNED = set()

# agents.transient_backoff_schedule 回退 WARNING 的进程级一次性去重（code-review
# item 0bae22a66073，同 _SEGMENT_DIRTY_WARNED / _RUN_TIMEOUT_FALLBACK_WARNED 范式）：
# normalize_transient_backoff_schedule 经 get_transient_config 被消费方与 30s 热更新
# 反复调用，同一坏值只在首次告警；键取 repr(raw)，去重只作用于日志、回退行为不变。
_TRANSIENT_BACKOFF_FALLBACK_WARNED = set()

# agents.timeout_overrides 非法键值 ERROR 的进程级一次性去重（code-review item
# 343d2ec54938，同 _SEGMENT_DIRTY_WARNED / _VALIDATE_SOFT_WARNED 范式）：
# normalize_timeout_overrides 经 supervision_config_floor（resolve_config 每 30s
# 热更新全量重跑）与 effective_run_timeout_seconds / judge_timeout_seconds（每 run
# 派发读取）被反复调用，agents.timeout_overrides 含坏键时同一 ERROR 逐周期、逐 run
# 重复打印。键取 (键名, repr(值))（未知键分支值记 None），同一坏键重复出现被去重、
# 不同坏键互不压制；去重只作用于日志、忽略/回退行为不变。
_TIMEOUT_OVERRIDE_INVALID_WARNED = set()

# verify 段正整数键非法值 WARNING 的进程级一次性去重（code-review item
# 4a67fbffa917，同 _SEGMENT_DIRTY_WARNED / _TRANSIENT_BACKOFF_FALLBACK_WARNED
# 范式）：_positive_int_reader 经 get_impl_code_review_* 被派发链与 30s 热更新
# 反复调用，键取 (键名, repr(值))，同一坏值只在首次告警；去重只作用于日志、
# 回退缺省行为不变。
_VERIFY_POSITIVE_INT_WARNED = set()

# 配置读取器非法值告警的进程级一次性去重（code-review item 50dac34fe569，同
# _SEGMENT_DIRTY_WARNED / _VERIFY_POSITIVE_INT_WARNED 范式）：同族读取器
# （effective_auto_archive_threshold / get_knowledge_config /
# get_knowledge_lane_config / get_code_review_fix_config）被 30s 热更新与周期
# 消费路径（spec_archive 定时扫描、knowledge_audit 维护车道、Dashboard 设置页
# 回显）反复调用，坏值未修复期间同一告警逐次重复打印。键取 (键路径, repr(值))，
# 同一坏点只在首次告警；去重只作用于日志、回退缺省行为不变。
_CONFIG_READER_WARNED = set()


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个配置 dict，返回新 dict（不修改入参）。

    规则：两值均为 dict → 递归合并（override 优先）；否则（标量 / list / None）
    → override 整体替换 base。用户级配置为基础、项目级配置为覆盖。
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigLoader:
    """Load and validate fenixd configuration from YAML."""

    # Required top-level keys
    REQUIRED_KEYS = ["project", "schedule", "agents", "worktree", "gates", "commands", "logging"]

    # Valid project types
    VALID_PROJECT_TYPES = ["web", "cli", "library", "api"]

    # Known agent types for model assignment（fast-track 与 implementer 同为派发角色，
    # 未纳入时 agents.models 配置它会被 _validate_agent_models 拒绝，fast-track 派发
    # 恒走默认网关——任务进度契约在其会话中成为死信的根因之一。dispute-judge 同样：
    # 未纳入时无法分配专属模型，只能随网关当前 provider 漂移，且网关欠费时秒挂。
    # 注意：向本列表新增角色会同步放开 agents.timeout_overrides 同名键
    # （TIMEOUT_OVERRIDE_AGENT_TYPES 由本列表派生，见下方白名单注释）
    KNOWN_AGENT_TYPES = [
        "implementer",
        "fast-track",
        "planner-plan",
        "planner-judge",
        "verifier",
        "administrator",
        "self-review",
        "spec-review",
        "dispute-judge",
        # add-code-review-agent-and-quality-tab: code-review（周期性仓库级
        # 代码审查）。不登记会被 _hash_gate 静默跳过 agents.models.code-review
        # 并回退默认网关（dispute-judge 前科）。
        "code-review",
        # add-code-review-auto-fix: code-fix（自动修复车道 agent）。不登记会被
        # _hash_gate 静默跳过 agents.models.code-fix 并回退默认网关——模型链
        # （code-fix → code-review → self-review → administrator → 默认网关）中
        # code-review 级回退将失效，恒走默认网关。
        "code-fix",
        # add-knowledge-atlas（design Open Question 立项裁定）：knowledge-distiller
        # （归档蒸馏车道 agent，commit_archive_move 单点派发）。不登记会被
        # _hash_gate 静默跳过 agents.models.knowledge-distiller 并回退默认网关
        # ——复用「未登记 agent 无回退链」的教训，立项即登记（零成本）。
        "knowledge-distiller",
    ]

    # ── run_timeout 按 agent_type 覆盖（per-agent-timeout-override）──────
    # agents.timeout_overrides.<agent_type> 覆盖全局 run_timeout_seconds。
    # 白名单键 = KNOWN_AGENT_TYPES 全集 + repair + supervision-judge，随
    # agents.models 角色集动态扩大（向 KNOWN_AGENT_TYPES 新增角色即同步放开
    # 同名 timeout_overrides 键）；design D3 初版的「七类」表述已过时。
    TIMEOUT_OVERRIDE_AGENT_TYPES = frozenset(KNOWN_AGENT_TYPES) | {"repair"}
    # supervision-judge 是内部轻量判定子进程（非长 run），不参与 absolute_max 派生，
    # 允许低于 agent run 的 300s 下限（spec per-agent-timeout-override 3.3 场景 240s 生效）。
    TIMEOUT_OVERRIDE_KEYS = TIMEOUT_OVERRIDE_AGENT_TYPES | {"supervision-judge"}
    # agent run 覆盖值下限（秒）：低于此值会截断正常长 run，整条忽略 + ERROR。
    TIMEOUT_OVERRIDE_MIN_SECONDS = 300

    # Valid approve modes
    VALID_APPROVE_MODES = ["manual", "auto"]

    # Valid draft promote modes（add-draft-promotion-gate：值语义与 approve_mode 对齐）
    VALID_PROMOTE_MODES = ["auto", "manual"]

    # Valid spec review modes（add-spec-review-gate：auto=默认全量评审，never=完全关闭）
    VALID_SPEC_REVIEW_MODES = ["auto", "never"]

    # Valid start_after scopes（add-start-after-scope-config：两档覆盖范围）
    # dispatch（缺省）= start_after 只约束实现派发链（定时/待激活 SPEC 立即晋升并跑
    # 方案评审，实现等到点）即 fix-start-after-premature-pickup 之前的旧行为；
    # full = 同时约束晋升/评审入口（SPEC 停在 drafted，到期/激活才晋升并评审）。
    VALID_START_AFTER_SCOPES = ["full", "dispatch"]

    # ── 瞬断治理配置（fix-provider-transient-backoff D6 / transient-controls-ui）──
    # 五键缺省值（design D6 表）。消费方（runner/provider_circuit/dispatch）经
    # _get_config 读取，非法值由本类防御式规范化回退缺省。
    TRANSIENT_BACKOFF_SCHEDULE_DEFAULT = "30,60,120"  # 原地退避秒序列（长度=原地重试上限）
    TRANSIENT_REDISPATCH_DELAY_DEFAULT = 600  # dispatch 排程等待秒
    TRANSIENT_BREAK_THRESHOLD_DEFAULT = 3  # 熔断窗口内同指纹次数
    TRANSIENT_BREAK_WINDOW_DEFAULT = 600  # 熔断窗口秒
    TRANSIENT_BREAK_COOLDOWN_DEFAULT = 600  # 熔断冷却秒

    # ── 解封渐进恢复（evo-fix-transient-break-unseal-backoff 1.4 / design D5）──
    # agents.transient_unseal_* 五键缺省值：缺省启用、数值保守（design D5）。
    # backoff_base=0 语义为「解封节奏禁用」（回到既有到期即全量放行行为），
    # 规范化显式保留 0（_normalize_transient_seconds 接受整值 0）。
    TRANSIENT_UNSEAL_BACKOFF_BASE_DEFAULT = 60  # post-unseal hold 基数秒
    TRANSIENT_UNSEAL_BACKOFF_MAX_DEFAULT = 600  # hold 封顶秒
    TRANSIENT_UNSEAL_PROBE_WINDOW_DEFAULT = 120  # 探针观察窗秒
    TRANSIENT_UNSEAL_STABLE_WINDOW_DEFAULT = 1800  # 解封次数稳定衰减窗秒（30 分钟）
    TRANSIENT_UNSEAL_RELEASE_STAGGER_DEFAULT = 30  # 错峰放行节拍秒

    # ── 同因重派熔断（fix-redispatch-loop-governance D3/D5）──
    # agents.max_same_cause_redispatches：同一 spec 连续同因重派计数阈值，
    # 达阈值冻结转人工（替代既有「清零 _retry_count 后照样重派」的空转）。
    # 正整数，合法范围 1–100；非法/缺失回退缺省 3。
    MAX_SAME_CAUSE_REDISPATCHES_DEFAULT = 3
    MAX_SAME_CAUSE_REDISPATCHES_MIN = 1
    MAX_SAME_CAUSE_REDISPATCHES_MAX = 100

    @classmethod
    def get_max_same_cause_redispatches(cls, config: Dict[str, Any]) -> int:
        """读取并规范化 ``agents.max_same_cause_redispatches``（正整数 1–100）。

        非法（缺失 / 非整数 / 布尔 / 越界 1–100）回退缺省 3——单点归一化，
        设置界面回显与 dispatch 熔断消费同一函数，展示与生效值不脱节
        （与 get_transient_config 同模式）。
        """
        try:
            val = cls.get(config, "agents.max_same_cause_redispatches", None)
        except Exception:
            return cls.MAX_SAME_CAUSE_REDISPATCHES_DEFAULT
        if val is None or isinstance(val, bool) or not isinstance(val, int):
            return cls.MAX_SAME_CAUSE_REDISPATCHES_DEFAULT
        if val < cls.MAX_SAME_CAUSE_REDISPATCHES_MIN or val > cls.MAX_SAME_CAUSE_REDISPATCHES_MAX:
            return cls.MAX_SAME_CAUSE_REDISPATCHES_DEFAULT
        return val

    # ── harness 进程边界选择（add-harness-adapter-layer 6.1）──────────
    # 新顶层段 agent（单数，区别于既有 agents 段——见 config.template.yaml
    # 两段注释）：agent.harness 选 spawn 的 agent 进程边界实现。
    HARNESS_DEFAULT = "claude"

    @classmethod
    def get_harness(cls, config: Dict[str, Any]) -> str:
        """读取并规范化 ``agent.harness``（合法值 claude|dsh，缺省 claude）。

        非法值（含非字符串/空白）回退缺省并 WARNING 告警（文案含「不支持」
        与合法值词表）。单点归一化：dispatch 前置健康检查、设置页回显与
        one_shot/叙事 spawn 的 adapter 解析消费同一函数，展示与生效值不脱节
        （与 get_max_same_cause_redispatches 同模式）。

        词表经 harness 包单源（VALID_HARNESS_VALUES）；函数内延迟解析——
        core.agent_runner 包初始化即拉入 runner 重链，而 runner 反向依赖本
        模块（SUPERVISION_DEFAULTS 等），模块级 import 会成环。
        """
        raw = cls.get(config, "agent.harness", None)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return cls.HARNESS_DEFAULT
        value = str(raw).strip().lower()
        from core.agent_runner.harness import VALID_HARNESS_VALUES

        if value in VALID_HARNESS_VALUES:
            if value == "dsh":
                cls._warn_dsh_protocol_mismatch(config)
            return value
        _logger.warning(
            "agent.harness 配置值不支持：%r（合法值：%s）；回退缺省 %s",
            raw,
            "/".join(VALID_HARNESS_VALUES),
            cls.HARNESS_DEFAULT,
        )
        return cls.HARNESS_DEFAULT

    #: dsh 协议守卫告警的进程级去重（热重载每 30s 重解析，不重复刷屏）。
    _DSH_PROTOCOL_WARNED = False

    @classmethod
    def _warn_dsh_protocol_mismatch(cls, config: Dict[str, Any]) -> None:
        """dsh 通道线协议守卫：agent.harness=dsh 且 provider baseurl 为
        Anthropic 兼容形态（路径含 /anthropic）而 agent.dsh_api 未配置时
        WARNING 一次——该组合会以 OpenAI 形状请求打 Anthropic 端点，dsh
        侧 TRANSPORT 断流 0 轮（2026-10-14 真实验收 run2 实证）。告警不
        阻断：OpenAI 形态端点不受影响，agent.dsh_api 可后配热生效。"""
        if cls._DSH_PROTOCOL_WARNED:
            return
        dsh_api = str(cls.get(config, "agent.dsh_api", "") or "").strip()
        if dsh_api:
            return
        # 段入口经 _segment_or_empty 归一（code-review item 7be994ab259e）：
        # `or {}` 对真值非 dict（如 llm: [1]）不回落，紧随的 .get("providers")
        # 抛 AttributeError 击穿 get_harness「非法值回退缺省并 WARNING」的
        # fail-open 契约，与本文件段读取纪律（_segment_or_empty）对齐。
        providers = cls._segment_or_empty(config, "llm").get("providers") or []
        if any(isinstance(p, dict) and "/anthropic" in str(p.get("baseurl", ""))
               for p in providers):
            cls._DSH_PROTOCOL_WARNED = True
            _logger.warning(
                "agent.harness=dsh 但未配置 agent.dsh_api，而 provider 链含 "
                "Anthropic 兼容形态 baseurl（*/anthropic）——dsh 将以 OpenAI "
                "形状请求打 Anthropic 端点，表现为 TRANSPORT 断流（0 轮即死）。"
                "修复：config 增配 agent.dsh_api: anthropic-messages"
            )

    # ── run 停滞预算（evo-add-run-stop-loss 2.2，缺省关闭）────────────
    # agents.run_stall_budget_* 三键：复合判停（连续 N 次达到 120s 的往返，
    # 或 stall 占比达到一半且超过 M 分钟无产物 mtime 进展）的开关与阈值。
    # 整个预算缺省关闭（design D3：绝对次数单一阈值会把慢 provider 下正常
    # run 杀掉重跑，必须复合判据 + 灰度开启）；非法值回退缺省。
    RUN_STALL_BUDGET_ENABLED_DEFAULT = False
    RUN_STALL_BUDGET_STALLS_DEFAULT = 5        # 连续慢往返次数门槛 N（≥1）
    RUN_STALL_BUDGET_WINDOW_MINUTES_DEFAULT = 10.0  # 无产物进展窗 M（分钟，>0）

    @classmethod
    def get_run_stall_budget_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """读取并规范化 run 停滞预算三键（缺省关闭，非法值回退缺省）。

        返回 ``{"enabled": bool, "stalls": int, "window_seconds": float}``：
        - enabled：仅接受布尔；缺失/None/非法一律 False（缺省关闭）；
        - stalls：正整数（bool 排除、整值浮点接受），非法回退缺省 N=5；
        - window_minutes：正数（bool 排除），换算为 window_seconds 返回，
          非法回退缺省 M=10 分钟。

        单点归一化：runner 判停消费与设置展示同一函数，展示与生效不脱节
        （与 get_max_same_cause_redispatches 同模式）。
        """
        try:
            raw_enabled = cls.get(config, "agents.run_stall_budget_enabled", None)
        except Exception:
            raw_enabled = None
        enabled = raw_enabled if isinstance(raw_enabled, bool) \
            else cls.RUN_STALL_BUDGET_ENABLED_DEFAULT
        # 开关两态行为一致：关闭态同样返回归一化阈值（读侧可展示生效形态；
        # 判停消费方以 enabled=False 短路，不进判停），故归一化只写一遍。
        stalls = cls._normalize_stall_budget_positive(
            config, "agents.run_stall_budget_stalls",
            cls.RUN_STALL_BUDGET_STALLS_DEFAULT, integer=True)
        window_seconds = cls._normalize_stall_budget_positive(
            config, "agents.run_stall_budget_window_minutes",
            cls.RUN_STALL_BUDGET_WINDOW_MINUTES_DEFAULT, integer=False) * 60.0
        return {"enabled": enabled, "stalls": stalls,
                "window_seconds": window_seconds}

    # ── impl 任务进度停滞预警（evo-add-impl-env-blocker-stop-loss 2.2，
    # 缺省开启）────────────────────────────────────────────────────────
    # agents.task_stall_warn_* 两键：impl run「自最近 run 内任务完成起的
    # 轮数」观测面的开关与预警阈值（数据源为 run 流内 TaskUpdate 观测）。
    # 纯观测面（超阈 WARNING + run_metrics 注记），不参与续期/击杀判定；
    # 缺省开启（proposal 实证：600 轮上限击杀前 275 轮零任务完成，观测
    # 预警是唯一在途信号），可显式关闭。键风格沿 run_stall_budget_* 先例
    # 归一化（_normalize_stall_budget_positive 单点）。
    TASK_STALL_WARN_ENABLED_DEFAULT = True
    TASK_STALL_WARN_TURNS_DEFAULT = 200  # 阈值 N 轮（design 标定值，按观测调参）

    @classmethod
    def get_task_stall_warn_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """读取并规范化任务进度停滞预警两键（缺省开启，非法值回退缺省）。

        返回 ``{"enabled": bool, "turns": int}``：
        - enabled：仅接受布尔；缺失/None/非法一律回退缺省 True（与
          run_stall_budget 缺省关闭的灰度语义相反——本键只观测不判定，
          开启无副作用，无需灰度）；
        - turns：正整数（bool 排除、整值浮点接受），非法回退缺省 200
          （design Open Question 标定值，实现后按观测调参）。

        单点归一化：runner 轮询环消费与设置展示同一函数，展示与生效不脱节
        （与 get_run_stall_budget_config 同模式）。
        """
        try:
            raw_enabled = cls.get(config, "agents.task_stall_warn_enabled", None)
        except Exception:
            raw_enabled = None
        enabled = raw_enabled if isinstance(raw_enabled, bool) \
            else cls.TASK_STALL_WARN_ENABLED_DEFAULT
        turns = cls._normalize_stall_budget_positive(
            config, "agents.task_stall_warn_turns",
            cls.TASK_STALL_WARN_TURNS_DEFAULT, integer=True)
        return {"enabled": enabled, "turns": turns}

    @classmethod
    def _normalize_int_value(cls, value: Any, default: int, *, positive: bool) -> int:
        """参数化整数归一单点（code-review item 05cdb9c48227 守卫收敛）。

        收敛本文件多份形态相近的「读键 → 排 bool → 排非有限浮点 → 整值浮点
        与否 → 回退缺省」守卫：``value`` 为 int 或整值浮点（``300.0`` 按整数
        接受，与 _normalize_transient_seconds 既有口径一致）时返回
        ``int(value)``；bool（int 子类显式排除）、非数值（含 None）、非有限
        浮点（YAML ``.nan``/``.inf`` 能穿透比较且 int() 抛异常）、非整值浮点
        （``0.5``，旧 ``int()`` 截断族缺陷）一律回退 ``default``。下界域由
        ``positive`` 参数化：True 时 ``<=0`` 回退缺省（0 不等效关闭的键），
        否则仅 ``<0`` 回退缺省（0 合法，含 0=禁用/关闭语义的键）。

        覆盖范围：仅「整值浮点按整数接受」口径的键。严格 int 键（整值浮点
        拒绝，如 knowledge.escalate_after_rounds / archive.auto_threshold）、
        数值字符串转换族（_num）与失败路径带告警留痕的读取器接受集/行为不同，
        MUST NOT 迁移至本助手（行为变更单列评审）。
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        if isinstance(value, float) and (
            not math.isfinite(value) or not value.is_integer()
        ):
            return default
        if positive:
            if value <= 0:
                return default
        elif value < 0:
            return default
        return int(value)

    @classmethod
    def _normalize_stall_budget_positive(cls, config: Dict[str, Any], key: str,
                                         default, integer: bool):
        """停滞预算数值键归一：正数（integer=True 时须整值），非法回退缺省。

        bool 排除与 _normalize_transient_seconds 同口径（bool 是 int 子类，
        ``true`` 会被 int() 截成 1 静默生效）。非有限浮点（.nan/.inf）同回退
        缺省（code-review item a61ee2b2031e）：nan 使下方 <=0 比较恒 False。
        """
        try:
            val = cls.get(config, key, None)
        except Exception:
            return default
        if integer:
            # 整数档判定核心单点收敛 _normalize_int_value（code-review item
            # 05cdb9c48227）：接受集与原内联守卫逐值一致（正整数、整值浮点
            # 按整数接受；bool/非数值/非有限浮点/非整值浮点/≤0 回缺省）。
            return cls._normalize_int_value(val, default, positive=True)
        if (
            val is None
            or isinstance(val, bool)
            or not isinstance(val, (int, float))
            or (isinstance(val, float) and not math.isfinite(val))
        ):
            return default
        if val <= 0:
            return default
        return float(val)

    @classmethod
    def _warn_backoff_schedule_fallback(cls, raw) -> str:
        """schedule 非法回退缺省前留痕（code-review item 0bae22a66073）。

        回退发生时配置已合法通过加载、生效值却被整条替换为缺省，静默无痕违背
        本文件「回退必告警」哲学（对照 _validated_run_at / get_knowledge_config）。
        本助手经 get_transient_config 被消费方与 30s 热更新反复调用，同一坏值
        进程级只告警一次（同 _SEGMENT_DIRTY_WARNED 范式，去重只作用于日志、
        回退行为不变）。
        """
        dedup_key = repr(raw)
        if dedup_key not in _TRANSIENT_BACKOFF_FALLBACK_WARNED:
            _TRANSIENT_BACKOFF_FALLBACK_WARNED.add(dedup_key)
            _logger.warning(
                "agents.transient_backoff_schedule 非法（应为逗号分隔正整数"
                "序列字符串或其列表）：%r，回退缺省 %s",
                raw,
                cls.TRANSIENT_BACKOFF_SCHEDULE_DEFAULT,
            )
        return cls.TRANSIENT_BACKOFF_SCHEDULE_DEFAULT

    @classmethod
    def normalize_transient_backoff_schedule(cls, raw) -> str:
        """规范 `agents.transient_backoff_schedule` 为合法逗号秒序列字符串。

        非法（非字符串 / 非逗号分隔正整数序列）回退缺省 ``"30,60,120"``（防御式
        先例同 ``_shutdown_drain_seconds``）并打 WARNING 留痕（code-review item
        0bae22a66073；``raw is None`` 属缺省语义，不算非法、不告警）。空串视为
        关闭原地退避（设计 Migration Plan：`transient_backoff_schedule: ""` 关闭
        原地退避），保持原样返回。
        """
        raw_orig = raw
        if raw is None:
            return cls.TRANSIENT_BACKOFF_SCHEDULE_DEFAULT
        if isinstance(raw, (list, tuple)):
            # 列表形态与 _validate 的接受集对齐（code-review item da6a06e5b48d）：
            # 校验显式接受 list，而旧规范化对非 str 一律回落缺省——合法通过的
            # 列表配置在运行时被静默替换为缺省，校验与消费口径不一致。此处把
            # 列表按逗号序列同口径规范化（元素须为正整数）。整值浮点先按 int
            # 归一（code-review item c50c760f64e3，对应 _validate 护栏的放行集）：
            # str(30.0)="30.0" 无法被下方 int() 解析，会让通过加载校验的列表
            # 整条回退缺省。
            raw = ",".join(
                str(int(x)) if isinstance(x, float) and x.is_integer() else str(x)
                for x in raw
            )
        if not isinstance(raw, str):
            return cls._warn_backoff_schedule_fallback(raw_orig)
        if not raw.strip():
            return ""  # 显式空串 = 关闭原地退避（Migration Plan）
        parts = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                val = int(part)
            except (TypeError, ValueError):
                return cls._warn_backoff_schedule_fallback(raw_orig)
            if val <= 0:
                return cls._warn_backoff_schedule_fallback(raw_orig)
            parts.append(str(val))
        if not parts:
            return cls._warn_backoff_schedule_fallback(raw_orig)
        return ",".join(parts)

    @classmethod
    def _normalize_transient_seconds(cls, config, key: str, default: int) -> int:
        """读取并规范化某瞬断治理秒/次数字段（非负整数，非法回退缺省）。

        非整数拒绝（code-review item 5bfa7e1a80ca）：旧实现放行任意非负数后
        ``int(val)`` 截断——``transient_break_threshold: 0.5`` 截成 0，按文档
        0 = 「熔断器禁用」，分数阈值反而把保护静默关掉（或在计数阈值读法下
        首次失败即触发）。与 admin.run_infra_breaker.threshold 已修复的同类
        缺陷（item 46b77a7d7e83）对齐：小数值一律回退文档默认值；整值浮点
        （如 ``30.0``）按整数接受，显式 ``0``（禁用）保持合法。
        """
        try:
            val = cls.get(config, key, None)
        except Exception:
            return default
        # 判定核心单点收敛 _normalize_int_value（code-review item 05cdb9c48227）：
        # 非负整数（显式 0 合法）、整值浮点按整数接受；bool/非数值/非有限浮点/
        # 非整值浮点/负数回缺省——接受集与原内联守卫逐值一致。
        return cls._normalize_int_value(val, default, positive=False)

    @classmethod
    def _normalize_transient_positive_seconds(cls, config, key: str, default: int) -> int:
        """正数版瞬断秒/次数字段归一（code-review item d4a017ecdaf1）。

        与 ``_normalize_transient_seconds`` 同口径，差异仅在 0 的去向：运行时
        消费侧（``provider_circuit._unseal_cfg`` 的 ``_positive_number``）把
        显式 0 归一回缺省——0 对 cap/stable 无意义（hold 无上限 / 衰减窗永不
        衰减），非合法配置。本快照必须同样钳制，否则设置页展示 0、运行时却按
        缺省生效（展示与生效脱节，事故调参误导）。仅 base/stagger/probe_window
        三个键保留 0 = 禁用语义（走既有非负归一）。
        """
        val = cls._normalize_transient_seconds(config, key, default)
        return default if val <= 0 else val

    @classmethod
    def get_transient_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """返回规范化后的瞬断治理配置（五键 + 缺省填充，供 Settings UI / 消费方）。

        语义与 design D6 表一致；非法值（负数/非数字/坏序列）回退缺省，保证
        展示与生效值不脱节。``transient_backoff_schedule`` 保留字符串形态
        （逗号秒序列），其余四键为 int。
        """
        # 段入口经 _segment_or_empty 归一（code-review item a4d95c2e3419）：
        # agents 整段非 dict（如 agents: [1]）时 ERROR 告警并按空段降级，与
        # 同族段级读取器（get_admin_config 等）统一降级与告警口径，不再静默
        # 吞掉脏段按全缺省返回。
        agents = cls._segment_or_empty(config, "agents")
        return {
            "transient_backoff_schedule": cls.normalize_transient_backoff_schedule(
                agents.get("transient_backoff_schedule")
            ),
            "transient_redispatch_delay_seconds": cls._normalize_transient_seconds(
                config,
                "agents.transient_redispatch_delay_seconds",
                cls.TRANSIENT_REDISPATCH_DELAY_DEFAULT,
            ),
            "transient_break_threshold": cls._normalize_transient_seconds(
                config,
                "agents.transient_break_threshold",
                cls.TRANSIENT_BREAK_THRESHOLD_DEFAULT,
            ),
            "transient_break_window_seconds": cls._normalize_transient_seconds(
                config,
                "agents.transient_break_window_seconds",
                cls.TRANSIENT_BREAK_WINDOW_DEFAULT,
            ),
            "transient_break_cooldown_seconds": cls._normalize_transient_seconds(
                config,
                "agents.transient_break_cooldown_seconds",
                cls.TRANSIENT_BREAK_COOLDOWN_DEFAULT,
            ),
            # 解封渐进恢复五键（evo-fix-transient-break-unseal-backoff 1.4）：
            # 展示与生效同源单点归一（与既有五键同模式）。cap/stable 两键运行时
            # 按正数钳制（0 → 缺省，_unseal_cfg._positive_number），快照同口径
            # （code-review item d4a017ecdaf1：0 非合法值，仅 base/stagger/
            # probe_window 保留 0 = 禁用语义）。
            "transient_unseal_backoff_base_seconds": cls._normalize_transient_seconds(
                config,
                "agents.transient_unseal_backoff_base_seconds",
                cls.TRANSIENT_UNSEAL_BACKOFF_BASE_DEFAULT,
            ),
            "transient_unseal_backoff_max_seconds": cls._normalize_transient_positive_seconds(
                config,
                "agents.transient_unseal_backoff_max_seconds",
                cls.TRANSIENT_UNSEAL_BACKOFF_MAX_DEFAULT,
            ),
            "transient_unseal_probe_window_seconds": cls._normalize_transient_seconds(
                config,
                "agents.transient_unseal_probe_window_seconds",
                cls.TRANSIENT_UNSEAL_PROBE_WINDOW_DEFAULT,
            ),
            "transient_unseal_stable_window_seconds": cls._normalize_transient_positive_seconds(
                config,
                "agents.transient_unseal_stable_window_seconds",
                cls.TRANSIENT_UNSEAL_STABLE_WINDOW_DEFAULT,
            ),
            "transient_unseal_release_stagger_seconds": cls._normalize_transient_seconds(
                config,
                "agents.transient_unseal_release_stagger_seconds",
                cls.TRANSIENT_UNSEAL_RELEASE_STAGGER_DEFAULT,
            ),
        }

    @classmethod
    def resolve_config(cls, project_root) -> Dict[str, Any]:
        """解析某项目的有效配置：用户级 + 项目级深合并（项目级优先）。

        读取用户级 `~/.fenix/config.yaml` 与项目级 `<project_root>/.fenix/config.yaml`，
        任一或全部缺失按空 dict 兜底；解析失败记录错误日志但不阻断。
        有效配置缺失 `project.name` 时以项目根目录名补齐（用户级 project 键不参与身份）。
        校验采用宽松模式（require_project=False）：不强制顶层必填键，已存在键做值级校验。

        Returns: 有效配置 dict，始终含 `project.name`。
        """
        proot = Path(project_root)

        user = {}
        user_path = USER_CONFIG_DIR / "config.yaml"
        if user_path.exists():
            user = cls._load_optional_yaml(user_path, "用户级")

        proj = {}
        proj_path = proot / ".fenix" / "config.yaml"
        if proj_path.exists():
            proj = cls._load_optional_yaml(proj_path, "项目级")

        effective = deep_merge(user, proj)

        # 补全项目身份：仅项目级显式定义的 project.name 生效；否则用项目根目录名
        project = effective.get("project")
        if not isinstance(project, dict):
            project = {}
            effective["project"] = project
        proj_name = None
        proj_project = proj.get("project")
        if isinstance(proj_project, dict):
            proj_name = proj_project.get("name")
        project["name"] = proj_name or proot.name

        cls._validate(effective, require_project=False)
        return effective

    @classmethod
    def resolve_config_into(cls, config: Dict[str, Any], project_root) -> None:
        """把最新有效配置原地写入 config（热更新），保持 dict 对象身份不变。

        所有组件持有同一 config 引用，原地 clear+update 后自动看到新值。
        解析或校验失败时抛异常且不触碰 config（保留旧值，运行中配置不被坏文件清空）。
        """
        fresh = cls.resolve_config(project_root)
        # 注意：resolve_config 内部已对 fresh 完成同一份 _validate（方法名引用，
        # 避免行号漂移），此处不重复校验（improve-hot-reload-robustness D9 死代码清理）。
        #
        # 原地更新顺序（code-review item 0c1e1d2b4341）：旧实现 `clear()` → `update()`
        # 存在一个「dict 为空」的窗口，而后台读线程（admin worker / 自进化 worker /
        # HookEngine / EventBus / code-review worker）正并发经 ConfigLoader.get
        # 遍历同一 dict——落在窗口内的读取会观测到空树并静默回落到内建缺省。
        # 改为「先 update 新值，再删除 fresh 中已不存在的键」：任一时刻 dict 都
        # 非空，键集合为旧∪新（读到的是旧值/新值的混合，但不会出现「整树消失」）。
        # 对象身份不变（组件持有的同一引用仍生效），语义等价。
        # [fenix-ignore:248c6e2d24fb] 全仓排查确无对共享顶层 config 的整树迭代读者（各组件均经 ConfigLoader.get 逐键导航、_validate 为 O(1) 成员判断、deep_merge 只作用于 resolve 期新造 dict），update+逐键 pop 的尺寸变化无可被打断的迭代者，引用换层/加锁加固不值得引入。
        config.update(fresh)
        for stale_key in [k for k in config if k not in fresh]:
            config.pop(stale_key, None)

    @classmethod
    def _load_optional_yaml(cls, path: Path, label: str) -> Dict[str, Any]:
        """读取单个配置文件，失败/非 dict 时记录日志并按空 dict 兜底。"""
        try:
            with path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if not isinstance(loaded, dict):
                _logger.error("%s配置顶层不是对象，按空配置处理: %s", label, path)
                return {}
            return loaded
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            # UnicodeDecodeError 是 ValueError 子类（非 OSError）：非 UTF-8 配置
            # 文件旧实现会逃出本兜底，中止 daemon 启动或 30s 热重载
            # （code-review item 40b623c7090b）。并入捕获集，兑现 docstring
            # 「任何读取/解析失败降级空 dict」。
            _logger.error("%s配置解析失败，按空配置处理: %s (%s)", label, path, e)
            return {}

    @classmethod
    def load(cls, config_path: Path) -> Dict[str, Any]:
        """Load config from path, validate, and return as dict."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if config is None:
            raise ValueError(f"Config file is empty: {config_path}")

        # 顶层类型检查（code-review item 9d47730f6504）：标量/列表顶层落到
        # _validate 会以 TypeError（`key not in <int>`）或误导性的
        # 「Missing required config key」报错。与 _load_optional_yaml 的
        # 「顶层不是对象」检查对称，此处提前给出清晰报错。
        if not isinstance(config, dict):
            raise ValueError(f"配置顶层必须是对象: {config_path}")

        cls._validate(config)
        return config

    @classmethod
    def _segment_or_empty(cls, config: Dict[str, Any], key: str) -> Dict[str, Any]:
        """段归一助手：读 ``config[key]`` 段，真值非 dict 时 ERROR 告警并按空段降级
        （code-review item 06352a414cf4）。

        手改 YAML 可使整段为列表/标量（``agents: [1]`` / ``admin: 3``）：宽松
        校验路径此前对其全数放行，运行期读者对列表/标量调 .get 抛 AttributeError，
        使 admin_monitor stuck 巡检 / pm_engine.check_blockers / 模型链解析逐周期
        崩溃。_validate 段入口与热路径读者统一经本助手取段：非 dict 记 ERROR 并
        按空段降级，对齐 _validate_agent_models（improve-hot-reload-robustness D2）
        与 self_evolution / _supervision_segment 的既有哲学——段级类型损坏按段
        跳过，其余配置照常校验/生效，不中断加载与热更新。
        """
        seg = config.get(key) if isinstance(config, dict) else None
        if isinstance(seg, dict):
            return seg
        if seg is not None:
            # 进程级 (key, 脏值类型) 一次性去重（code-review item bb5366851f4a，
            # 同 _UNKNOWN_AGENT_MODEL_KEYS_WARNED 范式）：只在告警分支去重，
            # 合法段与缺段路径不经过此处；降级返回 {} 的行为不变。
            dedup_key = (key, type(seg).__name__)
            if dedup_key in _SEGMENT_DIRTY_WARNED:
                return {}
            _SEGMENT_DIRTY_WARNED.add(dedup_key)
            _logger.error(
                "config.%s 整段非 dict（%s），该段已忽略、按空段降级；其余配置照常生效",
                key,
                type(seg).__name__,
            )
        return {}

    @classmethod
    def _warn_reader_once(cls, key: str, value, log, msg: str, *args) -> None:
        """配置读取器非法值告警的进程级一次性去重（code-review item 50dac34fe569）。

        同族读取器（effective_auto_archive_threshold / get_knowledge_config /
        get_knowledge_lane_config / get_code_review_fix_config）被 30s 热更新与
        周期消费路径（spec_archive 定时扫描、knowledge_audit 维护车道、
        Dashboard 设置页回显）反复调用，坏值未修复期间同一告警逐次重复打印，
        与本文件既有去重纪律（_SEGMENT_DIRTY_WARNED 范式）不一致。键取
        (键路径, repr(值))，同一坏点只在首次告警；去重只作用于日志，回退缺省
        行为不变。``log`` 传各调用点原有的 ``_logger.error`` / ``_logger.warning``，
        保留原级别与文案。
        """
        dedup_key = (key, repr(value))
        if dedup_key in _CONFIG_READER_WARNED:
            return
        _CONFIG_READER_WARNED.add(dedup_key)
        log(msg, *args)

    @classmethod
    def _validate(cls, config: Dict[str, Any], require_project: bool = True):
        """Validate configuration structure and values.

        require_project=True（load 严格路径）：顶层 REQUIRED_KEYS 必须全部存在，
        且 project.type 必须有效。
        require_project=False（resolve_config 宽松路径）：不强制顶层键存在（缺省
        交由消费方默认值兜底），仅校验已存在的键；project.type 缺失时不参与校验。
        """
        # 顶层必填键检查（仅严格路径）
        if require_project:
            for key in cls.REQUIRED_KEYS:
                if key not in config:
                    raise ValueError(f"Missing required config key: '{key}'")

        # Validate schedule
        # 段入口经 _segment_or_empty 归一（code-review item c382e6a9ea84）：
        # 真值非 dict 段（如 schedule: [1]）不再以 AttributeError 崩溃，而是
        # ERROR 告警 + 按空段降级，对齐下方 agents/admin 段口径。
        schedule = cls._segment_or_empty(config, "schedule")
        poll = schedule.get("poll_interval_minutes", 30)
        # 排除 bool（code-review item e9c679fb1bb3）：bool 是 int 子类，
        # YAML `poll_interval_minutes: true` 会通过 isinstance 校验并以 True 参与
        # 运算（True*60）。显式拒绝 bool。
        # 非有限浮点同拒（code-review item a61ee2b2031e，范式先例 d9e9a238696f）：
        # nan 使 <=0 比较恒 False 可穿透校验，event_bus 周期扫描读到 nan 后
        # time.sleep(nan) 抛 ValueError 冲出扫描线程循环。
        # 显式 null 语义（code-review item 23468c4eba86）：本键与下方 agents
        # 三键对「键存在但值为 null」（YAML 冒号留空）硬拒绝，而 admin/gates/
        # transient 族 `is not None` 短路按缺省跳过——同一写法两类行为，且
        # 「must be positive: None」文案指向取值而非真实问题（写法）。不统一为
        # 「null=缺省跳过」：读取端对 None 不兜底（event_bus 对 schedule 直读
        # dict.get，缺省只在键缺失时生效），放行会把加载期报错变成运行期
        # TypeError。故对 None 单独报错指明写法问题，与「值非法」文案区分。
        if poll is None:
            raise ValueError(
                "schedule.poll_interval_minutes is explicitly null (key present "
                "with empty value): remove the line to use the default 30, or "
                "set a positive number of minutes"
            )
        if (
            isinstance(poll, bool)
            or not isinstance(poll, (int, float))
            or (isinstance(poll, float) and not math.isfinite(poll))
            or poll <= 0
        ):
            raise ValueError(f"schedule.poll_interval_minutes must be positive: {poll}")

        # Validate agents — max_concurrent / max_retries / max_turns 均为可选，
        # 缺失时由各消费方使用默认值；仅当显式提供时才校验必须为正整数。
        # 段入口经 _segment_or_empty 归一（code-review item 06352a414cf4）：
        # 真值非 dict 段不再全数放行（列表对 in 是恒 False 的成员测试、标量
        # 直接 TypeError），而是 ERROR 告警 + 按空段降级。
        agents = cls._segment_or_empty(config, "agents")
        for field in ["max_concurrent", "max_retries", "max_turns"]:
            if field in agents:
                val = agents[field]
                # 显式 null 单独报错（code-review item 23468c4eba86，同上方
                # schedule.poll_interval_minutes 口径）：文案指明「键显式留空」
                # 的写法问题，而非误导向取值非法。
                if val is None:
                    raise ValueError(
                        f"agents.{field} is explicitly null (key present with "
                        "empty value): remove the line to use the consumer "
                        "default, or set a positive integer"
                    )
                # 整值浮点按整数接受（code-review item 2f24ce55d6f6，同
                # _normalize_transient_seconds / _positive_int_reader 口径，
                # 判别式同款 ``is_integer() and > 0``）：YAML ``max_turns: 400.0``
                # 此前被 ``not isinstance(val, int)`` 硬拒，整份配置加载/热更新
                # 失败、旧值锁死；而同函数 schedule.poll_interval_minutes 接受
                # 30.0，且三键各读取端（queue int() / repair_lane is_integer 分支
                # / adjudication / runner int() 钳制）均已按整值浮点归一——同类值
                # 在同文件两种命运。就地 int() 归一（同 _check_supervision_
                # consistency 校验层自动对齐的原地写范式）：三键无本模块归一层，
                # maintenance_runs 直传 _run_agent 的读取点不钳型，放行不归一会
                # 让浮点漏进轮询环。is_integer() 对 .nan/.inf 恒 False，非有限
                # 浮点与正负零判别同落入下方硬拒分支。
                if isinstance(val, float) and val.is_integer() and val > 0:
                    val = int(val)
                    agents[field] = val
                # 排除 bool（bool 是 int 子类，code-review item e9c679fb1bb3）
                if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                    raise ValueError(f"agents.{field} must be a positive integer: {val}")

        # admin 段入口在此统一取段一次并复用（code-review item ea7c504c6ed9）：
        # 脏段 ERROR 告警只记一条，供下方 run_drain 一致性校验与末尾 admin.*
        # 字段校验共用，避免同一轮校验对同一脏段重复输出 ERROR。
        admin = cls._segment_or_empty(config, "admin")

        # add-pipeline-throughput-governance D3：restart 排水窗口上限
        # agents.run_drain_max_seconds（缺省 60，专管 restart 场景；常规停机仍走
        # admin.shutdown_drain_seconds 不变）。显式提供时校验非负数值；与
        # admin.shutdown_drain_seconds 均显式且后者 > 0 时 MUST 满足
        # run_drain ≤ shutdown——supervisor 的 SIGKILL 等待 = shutdown + 120s
        # 余量（bin/fenixd_supervisor.py），违反即排水窗口可能被强杀截断。
        # 仅两者均显式时拒绝（缺省 60 与较小显式 shutdown 的组合由读取门面
        # get_run_drain_max_seconds 的 min 夹紧兜底，不把缺省值变成地雷）。
        if "run_drain_max_seconds" in agents and agents["run_drain_max_seconds"] is not None:
            rdm = agents["run_drain_max_seconds"]
            if (
                isinstance(rdm, bool)
                or not isinstance(rdm, (int, float))
                or (isinstance(rdm, float) and not math.isfinite(rdm))
                or rdm < 0
            ):
                raise ValueError(
                    f"agents.run_drain_max_seconds must be a non-negative number: {rdm!r}"
                )
            _sd = admin.get("shutdown_drain_seconds")
            if (
                isinstance(_sd, (int, float))
                and not isinstance(_sd, bool)
                and _sd > 0
                and rdm > _sd
            ):
                raise ValueError(
                    f"agents.run_drain_max_seconds ({rdm}) must be <= "
                    f"admin.shutdown_drain_seconds ({_sd}) — supervisor SIGKILL "
                    f"wait = shutdown_drain_seconds + 120s, a larger run-drain "
                    f"window risks being killed mid-drain"
                )

        # fix-provider-transient-backoff（D6）：瞬断治理五键防御式校验。极端非法
        # 值在 loads 阶段硬拒绝（raise ValueError；热更新校验失败即保留旧值）：
        # 数值键为 bool / 非数值 / 负数，schedule 为非 str 非 list——并非「仅打
        # ERROR 不拒绝加载」。数值合法域的宽松形态（整值浮点 30.0）与绕过本段
        # 校验的运行时直读，才由 get_transient_config / _normalize_transient_seconds
        # 归一或回退缺省（Migration Plan 回滚语义 = 配置键置空）作第二道防线。
        for field in (
            "transient_redispatch_delay_seconds",
            "transient_break_threshold",
            "transient_break_window_seconds",
            "transient_break_cooldown_seconds",
        ):
            if field in agents and agents[field] is not None:
                val = agents[field]
                if (
                    isinstance(val, bool)
                    or not isinstance(val, (int, float))
                    or (isinstance(val, float) and not math.isfinite(val))
                    or val < 0
                ):
                    raise ValueError(f"agents.{field} must be a non-negative number: {val!r}")
        if (
            "transient_backoff_schedule" in agents
            and agents["transient_backoff_schedule"] is not None
        ):
            schedule_val = agents["transient_backoff_schedule"]
            if not isinstance(schedule_val, str) and not isinstance(schedule_val, list):
                raise ValueError(
                    "agents.transient_backoff_schedule must be a comma-separated "
                    f"seconds string or list: {schedule_val!r}"
                )
            if isinstance(schedule_val, list):
                # 列表元素须为非空标量（code-review item 0bae22a66073）：旧版
                # 对 list 只查容器类型，[30, null] / [{}] / 嵌套 list 均放行，
                # 运行期 join 后逐元素 int() 解析必然整体回退缺省——配置看似
                # 合法加载、生效值被整条替换，加载阶段硬拒绝更早暴露。bool
                # （int 子类，str(True)="True" 解析必败）与非整值浮点（str
                # (30.5)="30.5" 解析必败；.nan/.inf 的 is_integer() 恒 False，
                # 一并拒绝）同本文件既有护栏排除；整值浮点（30.0）放行，由
                # normalize_transient_backoff_schedule 按 int 归一（code-review
                # item c50c760f64e3，与 _normalize_transient_seconds「整值浮点
                # 按整数接受」同口径），使加载期接受集与运行期解析集一致。
                for _idx, _el in enumerate(schedule_val):
                    if (
                        _el is None
                        or isinstance(_el, bool)
                        or not isinstance(_el, (str, int, float))
                        or (isinstance(_el, float) and not _el.is_integer())
                        or (isinstance(_el, str) and not _el.strip())
                    ):
                        raise ValueError(
                            "agents.transient_backoff_schedule list elements must "
                            f"be non-empty scalars (str/int/integer-valued float): "
                            f"{schedule_val!r}"
                        )
                    # str 元素补一道与运行期同口径的预检（code-review item
                    # 5f872daea086）：上方只要求非空，"abc"/"30.0" 等不可被
                    # int() 解析的串会合法通过加载，运行期
                    # normalize_transient_backoff_schedule 解析失败才把整条
                    # schedule 回退缺省——正是本段注释要靠加载期硬拒绝消除的
                    # 「看似合法加载、生效值被整条替换」形态。与 normalize 的
                    # 逐元素 int() 解析同口径：strip 后须解析为正整数，非法串
                    # 在加载/保存阶段即报错并指明下标。
                    if isinstance(_el, str):
                        try:
                            _seconds = int(_el.strip())
                        except ValueError:
                            _seconds = 0
                        if _seconds <= 0:
                            raise ValueError(
                                "agents.transient_backoff_schedule list elements "
                                "must be positive integers (str elements parsed "
                                f"like the runtime normalizer): element #{_idx} "
                                f"{_el!r} in {schedule_val!r}"
                            )

        # Validate project type — 仅当（严格路径 或 显式提供 type）时校验。
        # 段入口经 _segment_or_empty 归一（code-review item b72e37e34e3b）：
        # project 段与其他段不同——缺失（None/{}）是合法态（宽松路径由
        # resolve_config 以 {} 重建身份），缺失不告警；仅真值非 dict 的脏段
        # （如 project: [1]）ERROR 告警 + 按空段降级，与 schedule/agents/llm/
        # gates/admin 段口径一致。降级后的空段在严格路径必然缺 type → 照常
        # raise，docstring「require_project=True 时 project.type 必须有效」
        # 不再被脏段静默绕过。
        project = cls._segment_or_empty(config, "project")
        if require_project or "type" in project:
            ptype = project.get("type", "")
            if ptype not in cls.VALID_PROJECT_TYPES:
                raise ValueError(f"project.type must be one of {cls.VALID_PROJECT_TYPES}: {ptype}")

        # Validate llm.providers (optional — absence means empty registry)；
        # 段入口经 _segment_or_empty 归一（code-review item c382e6a9ea84），
        # 真值非 dict 段（如 llm: 3）按空段降级，不进 _validate_llm 崩溃。
        llm = cls._segment_or_empty(config, "llm")
        if llm:
            cls._validate_llm(llm)

        # Validate agents.models (optional — absence means no assignments)。
        # models 显式提供（非 None）即进校验：非 dict 段由 _validate_agent_models
        # 内部按"忽略该段 + 告警"降级（improve-hot-reload-robustness D2）。
        # agents 段复用上方已取局部变量，不重复取段（code-review item
        # ea7c504c6ed9）：脏段同一轮校验只告警一次。
        if "models" in agents and agents["models"] is not None:
            cls._validate_agent_models(agents["models"], llm)

        # Validate gates.approve_mode (optional — defaults to manual)；
        # 段入口经 _segment_or_empty 归一（code-review item c382e6a9ea84），
        # 真值非 dict 段按空段降级，避免脏段以 AttributeError 崩溃校验路径。
        gates = cls._segment_or_empty(config, "gates")
        if "approve_mode" in gates and gates["approve_mode"] is not None:
            mode = gates["approve_mode"]
            if mode not in cls.VALID_APPROVE_MODES:
                raise ValueError(
                    f"gates.approve_mode must be one of {cls.VALID_APPROVE_MODES}: {mode}"
                )

        # Validate gates.promote_mode (optional — defaults to auto)
        if "promote_mode" in gates and gates["promote_mode"] is not None:
            mode = gates["promote_mode"]
            if mode not in cls.VALID_PROMOTE_MODES:
                raise ValueError(
                    f"gates.promote_mode must be one of {cls.VALID_PROMOTE_MODES}: {mode}"
                )

        # Validate gates.spec_review_mode (optional — defaults to auto)
        if "spec_review_mode" in gates and gates["spec_review_mode"] is not None:
            mode = gates["spec_review_mode"]
            if mode not in cls.VALID_SPEC_REVIEW_MODES:
                raise ValueError(
                    f"gates.spec_review_mode must be one of {cls.VALID_SPEC_REVIEW_MODES}: {mode}"
                )

        # Validate gates.start_after_scope (optional — defaults to dispatch)
        if "start_after_scope" in gates and gates["start_after_scope"] is not None:
            scope = gates["start_after_scope"]
            if scope not in cls.VALID_START_AFTER_SCOPES:
                raise ValueError(
                    f"gates.start_after_scope must be one of {cls.VALID_START_AFTER_SCOPES}: {scope}"
                )

        # D5：timeout_supervision.absolute_max_seconds 一致性校验，启动/热更新时
        # 执行：默认自动对齐（内存抬升 + daemon 持久化），显式关闭 auto_align 时
        # fail-fast（启动/加载失败；热更新拒绝新配置保留旧值）。口径取全部署最大
        # 可达下限（supervision_config_floor），详见 _check_supervision_consistency。
        cls._check_supervision_consistency(config)

        # Validate admin.* (optional — 缺省使用默认值，见 get_admin_config)；
        # 段入口同样经 _segment_or_empty 归一（code-review item 06352a414cf4），
        # 此处复用上方已取的 admin 局部变量（code-review item ea7c504c6ed9）。
        if "enabled" in admin and not isinstance(admin["enabled"], bool):
            raise ValueError(f"admin.enabled must be a boolean: {admin['enabled']}")
        for field in (
            "interval_minutes",
            "escalation_cooldown_minutes",
            "orphaned_state_threshold_minutes",
        ):
            if field in admin and admin[field] is not None:
                val = admin[field]
                # bool 须排除（code-review item b8822ad7bae7）：Python 里
                # bool 是 int 子类，不排除时 admin.interval_minutes: true 通过
                # 校验并被 get_admin_config 转成 float(True)=1.0——巡检间隔
                # 静默缩到 1 分钟。与下方 stuck_silence_minutes/workers/
                # shutdown_drain_seconds 护栏同型。
                if (
                    not isinstance(val, (int, float))
                    or isinstance(val, bool)
                    or (isinstance(val, float) and not math.isfinite(val))
                    or val <= 0
                ):
                    raise ValueError(f"admin.{field} must be positive: {val}")
        # stuck-signal-hygiene D4：stuck 处置后静默期——非负护栏（0 = 不静默），
        # 与 escalation_cooldown_minutes 同型（负数/非法类型拒绝）。
        if "stuck_silence_minutes" in admin and admin["stuck_silence_minutes"] is not None:
            _ssm = admin["stuck_silence_minutes"]
            if (
                not isinstance(_ssm, (int, float))
                or isinstance(_ssm, bool)
                or (isinstance(_ssm, float) and not math.isfinite(_ssm))
                or _ssm < 0
            ):
                raise ValueError(
                    f"admin.stuck_silence_minutes must be a non-negative number: {_ssm}"
                )
        # fix-admin-run-blocks-mainloop D6：后台 worker 池大小；0 表示不启用后台池
        # （回退主循环内同步执行）。负数与非法类型拒绝。
        if "workers" in admin and admin["workers"] is not None:
            workers = admin["workers"]
            if not isinstance(workers, int) or isinstance(workers, bool) or workers < 0:
                raise ValueError(f"admin.workers must be a non-negative integer: {workers}")
        # interrupt-recovery-preserve D1：规划性重启排水窗口；0 = 不排水、保持现行
        # 快速停机。负数/非法类型拒绝（读取方 _validated_drain 另有回退兜底）。
        if "shutdown_drain_seconds" in admin and admin["shutdown_drain_seconds"] is not None:
            drain = admin["shutdown_drain_seconds"]
            if (
                not isinstance(drain, (int, float))
                or isinstance(drain, bool)
                or (isinstance(drain, float) and not math.isfinite(drain))
                or drain < 0
            ):
                raise ValueError(
                    f"admin.shutdown_drain_seconds must be a non-negative number: {drain}"
                )
        # add-bug-repair-mode-config：admin.bug_repair_mode 护栏。允许缺省
        # （None/未配置 → 消费方缺省 inplace）或字符串枚举 inplace/derive；
        # 非法取值（非字符串或非枚举值）直接拒绝，报错风格与既有 admin 护栏一致。
        if "bug_repair_mode" in admin and admin["bug_repair_mode"] is not None:
            brm = admin["bug_repair_mode"]
            if brm not in VALID_BUG_REPAIR_MODES:
                raise ValueError(
                    f"admin.bug_repair_mode must be one of "
                    f"{list(VALID_BUG_REPAIR_MODES)}: {brm!r}"
                )

        # add-daily-self-review：admin.self_review 段护栏。
        # enabled/read_todo 须为布尔（非布尔直接拒绝）；run_at 须合法 HH:MM、
        # 非法值打 ERROR 并回退缺省（不阻塞加载，硬语义由 get_self_review_config
        # 的生效值兜底）。enabled 缺省 false（纯增量零行为变化）。
        # 整段非 dict（列表/标量）与 self_evolution / stale_code_selfheal 同口径
        # （code-review item 48753a3159b2）：只记 ERROR 按空段降级，不中断加载与
        # 热更新——读取器 get_self_review_config 对非 dict 段本就按空段兜底。
        sr = admin.get("self_review") if isinstance(admin, dict) else None
        if sr is not None and not isinstance(sr, dict):
            # 进程级一次性去重（code-review item a84b10635fb2，同
            # _SEGMENT_DIRTY_WARNED 范式，见 _VALIDATE_SOFT_WARNED 定义处）。
            dedup_key = ("admin.self_review", type(sr).__name__)
            if dedup_key not in _VALIDATE_SOFT_WARNED:
                _VALIDATE_SOFT_WARNED.add(dedup_key)
                _logger.error(
                    "admin.self_review 段非法（应为对象）：%r，按空段降级"
                    "（enabled 缺省 false）；其余配置照常生效",
                    type(sr).__name__,
                )
        elif isinstance(sr, dict):
            for field in ("enabled", "read_todo"):
                if field in sr and sr[field] is not None and not isinstance(sr[field], bool):
                    raise ValueError(f"admin.self_review.{field} must be a boolean: {sr[field]}")
            if "run_at" in sr and sr["run_at"] is not None:
                cls._validated_run_at(sr["run_at"])  # 非法值仅 ERROR+回退，不抛错

        # add-spec-archive D5：archive.auto_threshold —— 自动归档阈值。
        # 非负整数（0 = 禁用）；非法值记日志并按默认 50 兜底（宽松校验，
        # 不因坏一个值阻断整个配置热更新/加载）。用户级与项目级均可设置，
        # 项目级经深合并优先。
        # 段入口经 _segment_or_empty 归一（code-review item c382e6a9ea84）：
        # 真值非 dict 段按空段降级，不中断加载与热更新。
        archive = cls._segment_or_empty(config, "archive")
        if "auto_threshold" in archive and archive["auto_threshold"] is not None:
            at = archive["auto_threshold"]
            if not isinstance(at, int) or isinstance(at, bool) or at < 0:
                # 进程级一次性去重（code-review item a84b10635fb2）。
                dedup_key = ("archive.auto_threshold", type(at).__name__)
                if dedup_key not in _VALIDATE_SOFT_WARNED:
                    _VALIDATE_SOFT_WARNED.add(dedup_key)
                    _logger.error(
                        "archive.auto_threshold 非法（应为非负整数，0=禁用）：%r，" "回落默认 50",
                        at,
                    )

        # add-knowledge-atlas（task 1.1）：knowledge 段护栏（软校验）。与
        # archive.auto_threshold 同型：键存在但类型非法时不进硬失败路径——只记
        # ERROR，生效值由 get_knowledge_config 按回退规则兜底（回退 true）。
        # 保证 30s 热更新路径不会因该节被中断。
        knowledge = cls._segment_or_empty(config, "knowledge")
        if (
            "enabled" in knowledge
            and knowledge["enabled"] is not None
            and not isinstance(knowledge["enabled"], bool)
        ):
            # 进程级一次性去重（code-review item a84b10635fb2）。
            dedup_key = ("knowledge.enabled", type(knowledge["enabled"]).__name__)
            if dedup_key not in _VALIDATE_SOFT_WARNED:
                _VALIDATE_SOFT_WARNED.add(dedup_key)
                _logger.error(
                    "knowledge.enabled 非法（应为布尔）：%r，回退缺省 true",
                    knowledge["enabled"],
                )

        # add-framework-self-evolution：self_evolution 段护栏（软校验）。
        # 与 stale_code_selfheal 的处理方式一致：节/键存在但类型非法时不进入硬
        # 失败路径——只记 ERROR，生效值由 get_self_evolution_config 按 1.1 的
        # 回退规则兜底。保证 30s 热更新路径（resolve_config_into）不会因该节
        # 被中断（用户级全局键，项目级写入由 dashboard 前置校验拒绝）。
        se = config.get("self_evolution")
        if se is not None and not isinstance(se, dict):
            # 进程级一次性去重（code-review item a84b10635fb2）。
            dedup_key = ("self_evolution", type(se).__name__)
            if dedup_key not in _VALIDATE_SOFT_WARNED:
                _VALIDATE_SOFT_WARNED.add(dedup_key)
                _logger.error(
                    "self_evolution 段非法（应为对象）：%r，按缺省值生效",
                    type(se).__name__,
                )
        elif isinstance(se, dict):
            if (
                "auto_accept" in se
                and se["auto_accept"] is not None
                and not isinstance(se["auto_accept"], bool)
            ):
                # 进程级一次性去重（code-review item a84b10635fb2）。
                dedup_key = ("self_evolution.auto_accept", type(se["auto_accept"]).__name__)
                if dedup_key not in _VALIDATE_SOFT_WARNED:
                    _VALIDATE_SOFT_WARNED.add(dedup_key)
                    _logger.error(
                        "self_evolution.auto_accept 非法（应为布尔）：%r，" "回退缺省 %s",
                        se["auto_accept"],
                        SELF_EVOLUTION_AUTO_ACCEPT_DEFAULT,
                    )
            if "max_items_per_run" in se and se["max_items_per_run"] is not None:
                mip = se["max_items_per_run"]
                if (
                    isinstance(mip, bool)
                    or not isinstance(mip, int)
                    or mip < 1
                    or mip > SELF_EVOLUTION_MAX_ITEMS_UPPER
                ):
                    # 进程级一次性去重（code-review item a84b10635fb2）。
                    dedup_key = ("self_evolution.max_items_per_run", type(mip).__name__)
                    if dedup_key not in _VALIDATE_SOFT_WARNED:
                        _VALIDATE_SOFT_WARNED.add(dedup_key)
                        _logger.error(
                            "self_evolution.max_items_per_run 非法（应为 1..%s 整数）："
                            "%r，回退缺省 %s",
                            SELF_EVOLUTION_MAX_ITEMS_UPPER,
                            mip,
                            SELF_EVOLUTION_MAX_ITEMS_DEFAULT,
                        )
            # spec_run_at 合法域 = None（立即执行）或 "HH:mm"；其余回退 None
            if "spec_run_at" in se and se["spec_run_at"] is not None:
                sra = se["spec_run_at"]
                if not (isinstance(sra, str) and _HHMM_RE.match(sra)):
                    # 进程级一次性去重（code-review item a84b10635fb2）。
                    dedup_key = ("self_evolution.spec_run_at", type(sra).__name__)
                    if dedup_key not in _VALIDATE_SOFT_WARNED:
                        _VALIDATE_SOFT_WARNED.add(dedup_key)
                        _logger.error(
                            "self_evolution.spec_run_at 非法（应为 null 或 HH:mm，"
                            "如 02:00）：%r，回退缺省（立项后立即执行）",
                            sra,
                        )

    @classmethod
    def _validate_provider_billing(cls, providers) -> None:
        """校验 llm.providers[i].billing 子对象（improve-provider-billing-config）。

        Dashboard 保存校验与 load-time 防呆共用同一实现（规则一致，风格与既有
        env 校验并列——非法直接 raise ValueError，不静默忽略）。规则：
        - billing 提供时必须为对象；
        - enabled 提供时为布尔（None 缺省视为关闭，不报错）；
        - prices 提供时必须为列表；每行 model 非空字符串、4 项单价为非负有限数值
          （bool 除外，NaN/inf 拒绝）、行 model 在同一卡片内不重复；
        错误信息含违规行路径（providers[i].billing.prices[j].字段）。
        """
        _price_fields = (
            "input_per_million",
            "output_per_million",
            "cache_read_per_million",
            "cache_creation_per_million",
        )
        for p_idx, provider in enumerate(providers):
            if not isinstance(provider, dict):
                continue
            billing = provider.get("billing")
            if billing is None:
                continue
            if not isinstance(billing, dict):
                raise ValueError(
                    f"llm.providers[{p_idx}].billing must be an object, "
                    f"got: {type(billing).__name__}"
                )
            if (
                "enabled" in billing
                and billing["enabled"] is not None
                and not isinstance(billing["enabled"], bool)
            ):
                raise ValueError(
                    f"llm.providers[{p_idx}].billing.enabled must be a boolean: "
                    f"{billing['enabled']!r}"
                )
            prices = billing.get("prices")
            if prices is not None and not isinstance(prices, list):
                raise ValueError(f"llm.providers[{p_idx}].billing.prices must be a list")
            seen: set = set()
            for r_idx, row in enumerate(prices or []):
                if not isinstance(row, dict):
                    raise ValueError(
                        f"llm.providers[{p_idx}].billing.prices[{r_idx}] must be an object"
                    )
                _prefix = f"llm.providers[{p_idx}].billing.prices[{r_idx}]"
                errs = []
                model = row.get("model")
                if not isinstance(model, str) or not model.strip():
                    errs.append(f"{_prefix}.model 必须为非空字符串")
                if model is not None and isinstance(model, str) and model.strip():
                    _key = model.strip()
                    if _key in seen:
                        errs.append(f"{_prefix} 卡片内 model 重复: {model}")
                    seen.add(_key)
                for _f in _price_fields:
                    v = row.get(_f)
                    if (
                        isinstance(v, bool)
                        or not isinstance(v, (int, float))
                        or (isinstance(v, float) and not math.isfinite(v))
                        or v < 0
                    ):
                        errs.append(f"{_prefix}.{_f} 必须为非负有限数值: {v!r}")
                if errs:
                    raise ValueError("billing 校验失败: " + "; ".join(errs))

    @classmethod
    def _validate_llm(cls, llm: Dict[str, Any]):
        providers = llm.get("providers")
        if providers is None:
            return
        if not isinstance(providers, list):
            raise ValueError(f"llm.providers must be a list, got: {type(providers).__name__}")

        seen_names = set()
        for idx, provider in enumerate(providers):
            if not isinstance(provider, dict):
                raise ValueError(f"llm.providers[{idx}] must be a dict")
            name = provider.get("name")
            baseurl = provider.get("baseurl")
            apikey = provider.get("apikey")
            if not name or not isinstance(name, str):
                raise ValueError(f"llm.providers[{idx}].name must be a non-empty string")
            if not baseurl or not isinstance(baseurl, str):
                raise ValueError(f"llm.providers[{idx}].baseurl must be a non-empty string")
            if not apikey or not isinstance(apikey, str):
                raise ValueError(f"llm.providers[{idx}].apikey must be a non-empty string")
            # 可选的自定义环境变量字典（运行时注入子进程，如 CLAUDE_CODE_MAX_CONTEXT_TOKENS）
            env = provider.get("env")
            if env is not None:
                if not isinstance(env, dict):
                    raise ValueError(
                        f"llm.providers[{idx}].env must be a dict, got: {type(env).__name__}"
                    )
                for k, v in env.items():
                    if not isinstance(k, str) or not isinstance(v, str):
                        # 只回显键名与值类型，不回显值本身（env 常承载 token/密钥，
                        # 对齐上方 apikey 校验的脱敏口径）
                        raise ValueError(
                            f"llm.providers[{idx}].env keys/values must be strings: "
                            f"key {k!r} (value type: {type(v).__name__})"
                        )
            if name in seen_names:
                raise ValueError(f"llm.providers[{idx}].name must be unique: duplicate '{name}'")
            seen_names.add(name)

        # improve-provider-billing-config（task 2.2）：billing 子对象校验（手工编辑
        # config.yaml 防呆，与 env 校验并列——非法直接拒绝加载，不回退老配置）。
        cls._validate_provider_billing(providers)

    @classmethod
    def _normalize_provider_chain(cls, raw_provider: Any) -> List[Tuple[str, Optional[str]]]:
        """把 `agents.models.<role>.provider` 统一规范化为 `(provider_name, element_model|None)` 列表。

        design D1：链元素支持 `str | {provider: str, model?: str}` 对象两种形态，
        也允许 str / 对象在 list 中混合（如 `[{provider: a, model: m1}, b]`）。
        解析矩阵：
        - str：单元素链，element_model=None（回退角色级 / provider 条目 model）
        - list[str]：按序候选链，每元素 element_model=None
        - list[{provider, model?}]：对象元素，element_model=该对象 model（缺省 None）
        - 混合：上述任意组合
        非法形态（元素非 str 且非 dict、对象缺 provider 键、model 非字符串）抛 ValueError，
        由 _validate_agent_models / get_agent_model_assignment 决定阻塞与否。
        空串元素与空 list 被过滤（返回空链），调用方据"空链"语义处理。
        """
        if isinstance(raw_provider, str):
            chain_raw = [raw_provider] if raw_provider else []
        elif isinstance(raw_provider, list):
            chain_raw = raw_provider
        else:
            raise ValueError("must be a string or list of strings/objects")

        elements: List[Tuple[str, Optional[str]]] = []
        for idx, el in enumerate(chain_raw):
            if isinstance(el, str):
                if el:
                    elements.append((el, None))
            elif isinstance(el, dict):
                name = el.get("provider")
                if not isinstance(name, str) or not name:
                    raise ValueError(f"chain element [{idx}] missing non-empty 'provider' name")
                m = el.get("model")
                if m is not None and not isinstance(m, str):
                    raise ValueError(f"chain element [{idx}].model must be a string")
                elements.append((name, m if (isinstance(m, str) and m) else None))
            else:
                raise ValueError(f"chain element [{idx}] must be a string or object")
        return elements

    @classmethod
    def _resolve_element_model(
        cls,
        element_model: Optional[str],
        role_model: Optional[str],
        provider_entry: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """按 design D1 解析顺序确定元素最终使用的模型名：元素自带 > 角色级 > provider 条目。

        三者皆空返回 None（该元素运行期被跳过并打 ERROR）。
        """
        if element_model and isinstance(element_model, str):
            return element_model
        if role_model and isinstance(role_model, str):
            return role_model
        if isinstance(provider_entry, dict):
            pe = provider_entry.get("model")
            if pe and isinstance(pe, str):
                return pe
        return None

    @classmethod
    def _warn_unknown_agent_model_key(cls, agent_type: str) -> bool:
        """未知 agent 类型键逐键降级告警（每进程生命周期对同一键只报一次）。

        improve-hot-reload-robustness D1/D3：未知键不整段拒绝——跳过该校键校验、
        键保留在有效配置中（跳过校验 ≠ 剔除数据）。告警文案内嵌重启处方
        （touch .fenix/restart_request）。热重载失败快照不更新的 30s 重试风暴下，
        同一键只报一次，后续轮次静默跳过。

        Returns: True 表示本次为首次告警；False 表示此前已告警过、本轮静默。
        """
        if agent_type in _UNKNOWN_AGENT_MODEL_KEYS_WARNED:
            return False
        _UNKNOWN_AGENT_MODEL_KEYS_WARNED.add(agent_type)
        _logger.error(
            "agents.models 含未知 agent 类型键 %r（本进程已知类型: %s）——已跳过"
            "该键校验、键保留在有效配置中。若该角色是新增派发角色，请重启 daemon "
            "使新白名单生效（touch .fenix/restart_request）",
            agent_type,
            sorted(cls.KNOWN_AGENT_TYPES),
        )
        return True

    @classmethod
    def _validate_agent_models(cls, models: Dict[str, Any], llm: Dict[str, Any]):
        """校验 agents.models 段。分类线（improve-hot-reload-robustness D2）：

        - 键集不匹配（代码演进产物，如新角色未被本进程白名单收录）→ 逐键降级：
          跳过该校键校验 + ERROR 告警（含重启处方），键保留在有效配置中；
        - 值/类型非法（配置真坏，如已知键的 provider 链形态错误）→ 维持 raise
          整段拒绝，旧配置原子保留；
        - 本段整段非 dict → 忽略该段 + ERROR 告警（无法逐键时按段跳，对齐
          _load_optional_yaml 哲学），其余段照常校验应用。
        """
        if not isinstance(models, dict):
            _logger.error(
                "agents.models 整段非 dict（%s），该段已忽略、不参与校验；其余配置"
                "照常应用（如需生效请修正后重启：touch .fenix/restart_request）",
                type(models).__name__,
            )
            return

        provider_names = set()
        providers = (llm or {}).get("providers") or []
        by_name: Dict[str, Any] = {}
        for p in providers:
            if isinstance(p, dict) and p.get("name"):
                provider_names.add(p["name"])
                by_name[p["name"]] = p

        for agent_type, assignment in models.items():
            if agent_type not in cls.KNOWN_AGENT_TYPES:
                cls._warn_unknown_agent_model_key(agent_type)
                continue
            if not isinstance(assignment, dict):
                raise ValueError(f"agents.models.{agent_type} must be a dict")
            raw_provider = assignment.get("provider")
            role_model = assignment.get("model")
            # design D2：角色级 model 不再要求非空，语义降为「全链缺省」；
            # 仅当显式提供且非字符串时报错（bool/数字等非法类型）。
            if role_model is not None and not isinstance(role_model, str):
                raise ValueError(f"agents.models.{agent_type}.model must be a string if provided")
            # design D1：provider 支持 str | list[str|{{provider,model?}}]，规范化为
            # (provider_name, element_model) 二元组列表；形态非法直接拒绝。
            try:
                chain = cls._normalize_provider_chain(raw_provider)
            except ValueError as e:
                raise ValueError(f"agents.models.{agent_type}.provider {e}")
            if not chain:
                raise ValueError(
                    f"agents.models.{agent_type}.provider must be a non-empty string or list"
                )
            # add-provider-failover：未知 provider 名只打 ERROR 不阻塞加载（design D3：
            # 沿用热更新哲学，运行期该链元素被跳过）。不再抛 ValueError，否则坏一个名字
            # 就整 daemon 起不来。
            unknown = [n for (n, _m) in chain if n not in provider_names]
            for unknown_name in unknown:
                # 进程级一次性去重（code-review item eec7502eb329）：热更新逐周期
                # 重跑本校验，同一 (agent_type, provider) 坏点只在首次告警。
                if (agent_type, unknown_name) in _UNKNOWN_PROVIDER_REF_WARNED:
                    continue
                _UNKNOWN_PROVIDER_REF_WARNED.add((agent_type, unknown_name))
                _logger.error(
                    "agents.models.%s.provider 引用了不存在的 provider（已跳过，不阻塞加载）: %s",
                    agent_type,
                    unknown_name,
                )
            # design D1/D2：逐元素可解析性检查（替换原"角色级 model 必须非空"）。
            # 元素自带 / 角色级 / provider 条目 model 三者皆空 → ERROR 指明元素下标（不阻塞）。
            for idx, (name, element_model) in enumerate(chain):
                if name not in by_name:
                    continue  # 未知 provider 已打过 ERROR，跳过其模型解析
                resolved = cls._resolve_element_model(element_model, role_model, by_name[name])
                if not resolved:
                    # 进程级一次性去重（code-review item eec7502eb329）：同上，
                    # 同一 (agent_type, provider, 元素下标) 坏点只在首次告警。
                    dedup_key = (agent_type, name, idx)
                    if dedup_key in _UNRESOLVED_CHAIN_MODEL_WARNED:
                        continue
                    _UNRESOLVED_CHAIN_MODEL_WARNED.add(dedup_key)
                    _logger.error(
                        "agents.models.%s.provider[%d] 无法解析出模型名（元素/model、角色级 "
                        "model、provider 条目 model 均为空），运行期将跳过该元素",
                        agent_type,
                        idx,
                    )

    @classmethod
    def get_agent_model_assignment(
        cls, config: Dict[str, Any], agent_type: str
    ) -> Optional[List[Tuple[Dict[str, Any], str]]]:
        """Return the candidate provider chain for the given agent_type.

        add-provider-failover：返回**按序候选链**——`list[(provider_dict, model)]`，
        链首项为首选；`agents.models.<role>.provider` 为 `str` 时解析为单元素链，与变更前
        逐字段一致。返回 `None` 表示该角色未分配 provider（走默认网关）。

        链条目仅引用 provider 名；未知名字在 `_validate_agent_models` 已打 ERROR，此处
        直接跳过（运行期安全降级）。整条链都被跳过/不存在时返回 `None`。

        模型 解析（design D1 / spec chain-model-mapping「元素级模型」）：
        每个元素独立解析模型名，解析顺序 元素自带 model > 角色级 model > 该 provider 项
        自身的 model 字段（三者皆空则该元素被跳过）。角色级 `model` 不再强制非空，语义
        为全链缺省。
        """
        agents = cls._segment_or_empty(config, "agents")
        models = agents.get("models") or {}
        if not isinstance(models, dict):
            return None
        assignment = models.get(agent_type)
        if not isinstance(assignment, dict):
            return None

        raw_provider = assignment.get("provider")
        role_model = assignment.get("model")
        # design D1：规范化为 (provider_name, element_model) 二元组链。
        # 形态非法（校验阶段已拦截，运行期兜底）返回 None 走默认网关。
        try:
            chain = cls._normalize_provider_chain(raw_provider)
        except ValueError:
            return None
        if not chain:
            return None

        # 段入口经 _segment_or_empty 归一（code-review item f3a0f8e121c8）：
        # llm 段真值非 dict 时不再 AttributeError，按空段降级、链解析返回 None 走默认网关。
        llm = cls._segment_or_empty(config, "llm")
        providers = llm.get("providers") or []
        by_name = {p.get("name"): p for p in providers if isinstance(p, dict)}

        result: List[Tuple[Dict[str, Any], str]] = []
        for name, element_model in chain:
            provider = by_name.get(name)
            if provider is None:
                # 未知名字已在校验阶段打 ERROR，运行期跳过该元素
                continue
            # 元素级模型解析：元素自带 > 角色级 > provider 条目 model（design D1）
            model = cls._resolve_element_model(element_model, role_model, provider)
            if not model:
                # 三者皆空：校验阶段已打 ERROR 指明下标，运行期跳过该元素
                continue
            result.append((provider, model))
        return result if result else None

    @classmethod
    def normalize_agent_models(
        cls, models: Dict[str, Any], llm_providers: Any = None
    ) -> Dict[str, Any]:
        """把 raw `agents.models` 转换为 Dashboard 回显用的规范化视图（design D4）。

        每个角色输出：
        - `model`: 角色级 model（缺省为 None）
        - `provider`: 规范化链数组，每个元素 `{provider, model}`，其中 `model` 为
          该元素**解析后**的模型名（元素自带 > 角色级 > provider 条目），供前端回显。
          无法解析模型的元素 `model` 置 None（前端占位显示角色级缺省）。

        三种既有形态（str / str 列表 / 对象列表）统一规范化为对象数组，保证前端
        只读一种结构即可渲染可排序行编辑器。
        """
        if not isinstance(models, dict):
            return {}
        out: Dict[str, Any] = {}
        providers = llm_providers or []
        by_name = {p.get("name"): p for p in providers if isinstance(p, dict)}

        for agent_type, assignment in models.items():
            if not isinstance(assignment, dict):
                continue
            raw_provider = assignment.get("provider")
            role_model = assignment.get("model")
            try:
                chain = cls._normalize_provider_chain(raw_provider)
            except ValueError:
                chain = []
            rows = []
            for name, element_model in chain:
                resolved = cls._resolve_element_model(element_model, role_model, by_name.get(name))
                rows.append({"provider": name, "model": resolved})
            out[agent_type] = {
                "model": role_model if (isinstance(role_model, str) and role_model) else None,
                "provider": rows,
            }
        return out

    @classmethod
    def serialize_models_patch(cls, models: Dict[str, Any]) -> Dict[str, Any]:
        """把 Dashboard 编辑器状态（design D4/D5）序列化回写 config.yaml 的规范形态。

        输入 `models[role]` 约定为编辑器状态：`model`（角色级缺省，可选） +
        `provider`（行列表，每行 `{provider, model}`；`model` 为元素级模型，可空）。

        序列化规则（design D4）：
        - 单行（仅一行）且该行无元素级 model → 退化为字符串 `"providername"`（向后兼容）
        - 否则 → 数组：每行按有无元素级 model 序列化为 `"providername"` 或
          `{"provider": name, "model": model}`

        角色级 `model` 仅当非空字符串时保留；空/None/缺省不写（避免脏缺省覆盖）。

        返回规范化的 `agents.models` dict，可直接进入 _validate_agent_models 校验
        与 _deep_merge_managed 应用。
        """
        if not isinstance(models, dict):
            return models
        out: Dict[str, Any] = {}
        for agent_type, assignment in models.items():
            if not isinstance(assignment, dict):
                # 容错：非编辑器形态（如已规范化的遗留结构）原样保留
                out[agent_type] = assignment
                continue
            role_model = assignment.get("model")
            role_model = role_model if (isinstance(role_model, str) and role_model) else None
            rows = assignment.get("provider")
            # 兼容：provider 已是 str / list[str|对象]（旧形态或前端直传）时原样使用
            if isinstance(rows, str):
                provider_out = rows if rows else None
            elif isinstance(rows, list):
                norm_rows = []
                for r in rows:
                    if isinstance(r, str):
                        norm_rows.append((r, None))
                    elif isinstance(r, dict):
                        n = r.get("provider")
                        if not isinstance(n, str) or not n:
                            continue
                        m = r.get("model")
                        norm_rows.append((n, m if (isinstance(m, str) and m) else None))
                    else:
                        continue
                if len(norm_rows) == 1 and norm_rows[0][1] is None:
                    # 单行且无元素级 model → 退化为字符串（design D4）
                    provider_out = norm_rows[0][0]
                else:
                    provider_out = [
                        (n if m is None else {"provider": n, "model": m}) for (n, m) in norm_rows
                    ] or None
            else:
                # code-review item fa355f2a1afd：str/list 之外的形态（如 tuple）
                # 此前静默丢弃且不留日志，配置丢失无从排查——落 WARNING 使降级
                # 可观测（对齐 _segment_or_empty 的脏值告警口径），行为不变。
                _logger.warning(
                    "agents.models[%s].provider 形态未知（%s），该角色 provider 配置已丢弃",
                    agent_type,
                    type(rows).__name__,
                )
                provider_out = None

            entry: Dict[str, Any] = {}
            if provider_out is not None:
                entry["provider"] = provider_out
            if role_model is not None:
                entry["model"] = role_model
            if entry:
                out[agent_type] = entry
        return out

    @classmethod
    def get_approve_mode(cls, config: Dict[str, Any]) -> str:
        """Return the approve_mode, defaulting to 'manual'."""
        # 段入口经 _segment_or_empty 归一（code-review item f8501642fde7）：
        # gates 真值非 dict 时 ERROR 告警并按空段降级，派发热路径不再 AttributeError 崩溃。
        gates = cls._segment_or_empty(config, "gates")
        mode = gates.get("approve_mode")
        if mode not in cls.VALID_APPROVE_MODES:
            return "manual"
        return mode

    @classmethod
    def get_promote_mode(cls, config: Dict[str, Any]) -> str:
        """Return the draft promote mode, defaulting to 'auto'.

        'auto' (default): drafted SPECs are automatically promoted to ready by
        PM Engine. 'manual': drafted SPECs stay in draft state awaiting manual
        promotion via Dashboard, CLI promote, or /fenix-ready.
        """
        # 段入口经 _segment_or_empty 归一（code-review item f8501642fde7）。
        gates = cls._segment_or_empty(config, "gates")
        mode = gates.get("promote_mode")
        if mode not in cls.VALID_PROMOTE_MODES:
            return "auto"
        return mode

    @classmethod
    def get_spec_review_mode(cls, config: Dict[str, Any]) -> str:
        """Return the spec review mode, defaulting to 'auto'.

        'auto' (default): all SPECs go through review unless they meet skip criteria.
        'never': skip review entirely, behave as before add-spec-review-gate.
        """
        # 段入口经 _segment_or_empty 归一（code-review item f8501642fde7）。
        gates = cls._segment_or_empty(config, "gates")
        mode = gates.get("spec_review_mode")
        if mode not in cls.VALID_SPEC_REVIEW_MODES:
            return "auto"
        return mode

    @classmethod
    def get_start_after_scope(cls, config: Dict[str, Any]) -> str:
        """Return the start_after scope, defaulting to 'dispatch'.

        'dispatch' (default): start_after only gates the implementation dispatch chain
        — scheduled/manual SPECs are immediately promoted and go through review; implementation
        dispatch waits until due (behavior before fix-start-after-premature-pickup).

        'full': start_after also gates the promotion and review entry points — SPECs stay
        in drafted until due/activated before promotion and review (behavior after
        fix-start-after-premature-pickup).
        """
        config = config or {}
        # 段入口经 _segment_or_empty 归一（code-review item f8501642fde7）。
        gates = cls._segment_or_empty(config, "gates")
        scope = gates.get("start_after_scope")
        if scope not in cls.VALID_START_AFTER_SCOPES:
            return "dispatch"
        return scope

    @classmethod
    def get_run_drain_max_seconds(cls, config: Dict[str, Any], planned: bool = False) -> float:
        """restart 排水窗口生效值（秒）：agents.run_drain_max_seconds，缺省 60。

        add-pipeline-throughput-governance D3：专管 daemon restart 流程等待在飞
        run 排水的时长上限；常规停机仍走 admin.shutdown_drain_seconds 语义不变。
        协调规则（graceful-restart-drain）：该值 MUST ≤ admin.shutdown_drain_seconds
        ——supervisor 的 SIGKILL 等待 = shutdown + 120s 余量，满足不等式即保证
        supervisor 不会先于 daemon 排水窗口动作。校验层已拒绝「两者均显式且违反」
        的组合；本门面对旁路脏配置与「缺省 60 遇较小显式 shutdown」的组合按
        min(raw, shutdown 生效值) 兜底夹紧（shutdown=0 快速停机时联动为 0，
        restart 不排水，与既有 drain=0 语义一致）。非法值一律回退缺省 60。

        planned-restart-drain D1：``planned=True``（restart_request 在场，规划性
        重启）时豁免 shutdown_drain_seconds 的快速停机联动夹紧——shutdown=0 的
        部署不再把窗口清零，改受 supervisor 协调上界约束：
        ``min(原值, supervisor SIGKILL 等待 − 终止收口安全余量)``。SIGKILL 等待
        按 bin/fenixd_supervisor.py ``_sigkill_wait_seconds`` 同源建模：shutdown>0
        时 = shutdown + 120s（DRAIN_MARGIN_SECONDS）；shutdown≤0 时回退缺省 60s
        （DEFAULT_SIGKILL_WAIT_SECONDS）。余量取 10s（≥ 建议下限且 = 单 run
        terminate 宽限 AGENT_TERMINATE_GRACE_SECONDS），保证超窗有序终止
        （SIGTERM+宽限+SIGKILL）与 sidecar 收口不被 supervisor SIGKILL 截断。
        shutdown>0 且 run_drain ≤ shutdown 的可加载配置下该上界不束紧、行为不变。
        """
        raw = cls.get(config, "agents.run_drain_max_seconds", None)
        # bool 排除（code-review item 611268328575）：float(True)=1.0 不抛异常，
        # 会把 restart 排水窗静默缩到 1 秒——与 _num 及 _validate 的既有 bool
        # 护栏同口径回退缺省 60。
        if raw is None or isinstance(raw, bool):
            value = 60.0
        else:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = 60.0
            # `not (value >= 0)` 同时捕获负数与 NaN（NaN 参与比较恒 False）
            if not (value >= 0):
                value = 60.0
        # 段入口经 _segment_or_empty 归一（code-review item 7035b5e127eb）：
        # 整段非 dict（如 admin: 3）记 ERROR 并按空段降级，而非静默回退缺省。
        admin = cls._segment_or_empty(config, "admin")
        sd_raw = admin.get("shutdown_drain_seconds")
        # bool 排除（code-review item 1b768109fdc2）：float(True)=1.0 不抛异常，
        # planned=False 路径会经下方 min 夹紧把 restart 排水窗静默压到 1 秒——
        # 与上方 raw 分支及 _num 的既有 bool 护栏同口径回退缺省 1800。
        if sd_raw is None or isinstance(sd_raw, bool):
            shutdown = 1800.0
        else:
            try:
                shutdown = float(sd_raw)
            except (TypeError, ValueError):
                shutdown = 1800.0
            if not (shutdown >= 0):
                shutdown = 1800.0
        if planned:
            # supervisor SIGKILL 等待（_sigkill_wait_seconds 同源建模）
            if shutdown > 0:
                sigkill_wait = shutdown + 120.0  # DRAIN_MARGIN_SECONDS
            else:
                sigkill_wait = 60.0  # DEFAULT_SIGKILL_WAIT_SECONDS 回退
            cap = max(sigkill_wait - PLANNED_DRAIN_TERMINATE_MARGIN_SECONDS, 0.0)
            return min(value, cap)
        return min(value, max(shutdown, 0.0))

    @classmethod
    def get_admin_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the admin.* configuration段，缺失项填默认值。

        默认值（见 design D1/D2 与 Migration Plan）：
        - enabled: True
        - interval_minutes: 5
        - agent_model: None（未配置时复用 agents.subagent_model 默认）
        - escalation_cooldown_minutes: 60
        - stuck_threshold_minutes: 由 agents.run_timeout_seconds 单源派生（见
          effective_stuck_threshold_seconds，旧 schedule/admin.stuck_threshold_minutes
          键已弃用、不再生效）
        - merge_breaker_threshold: 复用 agents.merge_breaker_threshold（默认 2）
        - shutdown_drain_seconds: 1800（0 = 快速停机）
        - bug_repair_mode: "inplace"（原地打回；derive = 派生 fix-* 子 SPEC）
        - stuck_silence_minutes: 120（stuck 处置后静默期：result=resolved/
          partially-resolved 处置后同 (spec, signal_type) 在窗口内不产信号）
        - narrative_enabled: True（转人工裁决告警四段式调查叙事开关）
        - narrative_timeout_seconds: 180（叙事单次调用硬超时，秒；
          upgrade-narrative-to-investigation 3.2 缺省 60→180，与
          core.adjudication_narrative.DEFAULT_TIMEOUT_SECONDS 单源对齐——
          网关 stall 实测 p90≈55s、max≈188s，60s 把长尾全判死）
        - narrative_model: None（叙事模型，None=回退链 admin.agent_model →
          框架默认）
        - self_heal_quiet_minutes: 1440（瞬态告警签名安静多久后标「已自愈」，
          add-alert-self-heal-marking；bool/非 int/≤0 回缺省）
        """
        admin = cls._segment_or_empty(config, "admin")
        # D2：stuck 阈值单源派生，旧键不再作为生效输入（告警在助手内节流）。
        stuck_seconds = cls.effective_stuck_threshold_seconds(config)
        breaker = cls.get(config, "admin.merge_breaker_threshold", None)
        if breaker is None:
            breaker = cls.get(config, "agents.merge_breaker_threshold", 2)
        # 类型校验 fail-open（code-review item d2344d1546c2）：_validate 只在
        # dashboard 写路径把关（须正整数 ≥1），手改 config.yaml 的非数字值
        # （"two"/list/dict）此前让下方 int(breaker) 抛 ValueError/TypeError
        # 而非回退默认，打破本类其余读取助手的 fail-open 归一哲学。bool
        # （int 子类，恒通过 isinstance int 检查）与 ≤0（熔断阈值无意义：
        # 0/负值使 _merge_streak 恒触发）同按非法回文档默认 2。
        if isinstance(breaker, bool):
            breaker = 2
        else:
            try:
                breaker = int(breaker)
            except (TypeError, ValueError):
                breaker = 2
            if breaker <= 0:
                breaker = 2
        brm = admin.get("bug_repair_mode", "inplace")
        if brm not in VALID_BUG_REPAIR_MODES:
            # 校验层已拦截非法值；运行期兜底（直读脏配置的旁路调用）回退缺省
            brm = "inplace"

        # 类型校验 fail-open（code-review item 632b4bb62eb3）：与上方 breaker
        # 同型，手改 config.yaml 的非数字值（"abc"/嵌套结构/显式 null）此前
        # 让下方 float()/int() 抛 ValueError/TypeError 而非回退默认。仅兜转换
        # 失败，各字段既有取值语义不变（stuck_silence/shutdown_drain 的显式 0
        # 合法、drain 负数仍由 max(0, …) 夹 0），回退值与原缺省逐字一致。
        def _num(value, default, conv):
            # bool 排除（code-review item 611268328575）：bool 是 int 子类，
            # conv(True)=1.0 / conv(False)=0.0 不抛异常——interval_minutes: true
            # 把巡检间隔静默缩到 1 分钟、shutdown_drain_seconds: true 变 1 秒
            # 快速停机、stuck_silence_minutes: false 把静默期归 0（语义是
            # 「不静默」而非缺省 120）。与上方 breaker 及 _validate 硬校验层的
            # 既有 bool 护栏同口径：非 bool 值才参与转换，否则回缺省。
            if isinstance(value, bool):
                return default
            try:
                result = conv(value)
            except (TypeError, ValueError):
                return default
            # 非有限浮点回退缺省（code-review item a61ee2b2031e）：float(nan)
            # 不抛异常，nan 直接入返回值使静默窗/巡检间隔比较恒 False。
            if isinstance(result, float) and not math.isfinite(result):
                return default
            return result

        # 严格 bool（code-review item 556de743c9af）：bool(...) 会把任何 truthy
        # 非 bool 值（如 YAML 引号串 enabled: "false"）静默转 True、意外启用
        # admin 子系统；非 bool 回退文档缺省 True（与 get_code_review_config
        # 同范式）。
        enabled = admin.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = True

        # 单源对齐落地（code-review item 390de4b1b6df）：下方 narrative_timeout
        # 三处回退值复用 core.adjudication_narrative.DEFAULT_TIMEOUT_SECONDS
        # 常量而非 180 字面量双写；函数体内延迟 import（get_harness 同款先例），
        # 规避模块级 import 环（adjudication_narrative 经 agent_runner 链回指
        # 本模块）。
        from .adjudication_narrative import DEFAULT_TIMEOUT_SECONDS

        # add-adjudication-alert-narrative：告警叙事三键（enabled 严格 bool
        # 缺省 True；timeout 正整数缺省 180——upgrade-narrative-to-
        # investigation 3.2 由 60 上调以覆盖网关 stall 长尾，异步补叙后超时
        # 成本不落告警路径，与 core.adjudication_narrative.DEFAULT_TIMEOUT_
        # SECONDS 单源对齐；bool/非数值/≤0 回缺省；model 空值归一 None=回退
        # 链 admin.agent_model → 框架默认）。类型非法 fail-open 回缺省，与
        # 上方 breaker/_num 同哲学。
        narrative_enabled = admin.get("narrative_enabled", True)
        if not isinstance(narrative_enabled, bool):
            narrative_enabled = True
        narrative_timeout_raw = admin.get("narrative_timeout_seconds")
        if isinstance(narrative_timeout_raw, bool) or (
            isinstance(narrative_timeout_raw, float)
            and not narrative_timeout_raw.is_integer()
        ):
            # bool 与非整值浮点回缺省（code-review item ed7dedfe5a87）：2.5
            # 旧实现经 _num 的 int() 截成 2 直接生效，与 run_infra_breaker.
            # threshold（item f03d70778889）/ _normalize_transient_seconds 的
            # 「非整值浮点回退缺省」口径对齐（.nan/.inf 的 is_integer() 为
            # False，同在此回缺省）。整值浮点（如 180.0）仍按整数接受。
            narrative_timeout = DEFAULT_TIMEOUT_SECONDS
        else:
            narrative_timeout = _num(
                narrative_timeout_raw, DEFAULT_TIMEOUT_SECONDS, int
            )
            if narrative_timeout is None or narrative_timeout <= 0:
                narrative_timeout = DEFAULT_TIMEOUT_SECONDS

        # add-alert-self-heal-marking 3.2：告警自愈安静窗口（分钟）——瞬态
        # 告警签名安静多久后标「已自愈」。缺省 1440（design D4：盖过跨日
        # 同刻复发节律）；bool / 负数 / 零 / 非 int / 非整值浮点回缺省，与
        # 上方 narrative_timeout 同口径（整值浮点仍按整数接受）。
        self_heal_quiet_raw = admin.get("self_heal_quiet_minutes")
        if isinstance(self_heal_quiet_raw, bool) or (
            isinstance(self_heal_quiet_raw, float)
            and not self_heal_quiet_raw.is_integer()
        ):
            self_heal_quiet_minutes = DEFAULT_SELF_HEAL_QUIET_MINUTES
        else:
            self_heal_quiet_minutes = _num(
                self_heal_quiet_raw, DEFAULT_SELF_HEAL_QUIET_MINUTES, int
            )
            if (
                self_heal_quiet_minutes is None
                or self_heal_quiet_minutes <= 0
            ):
                self_heal_quiet_minutes = DEFAULT_SELF_HEAL_QUIET_MINUTES

        # interrupt-recovery-preserve D1：显式提供的 shutdown_drain_seconds
        # 非整值浮点回缺省（code-review item e3dbb81371ea）——旧实现经 _num 的
        # int() 静默截断（1799.9 → 1799；更糟的是 0.5 → 0，语义从「排水 0.5 秒」
        # 翻转成 0 =「快速停机不排水」），与 narrative_timeout_seconds（item
        # ed7dedfe5a87）/ run_infra_breaker.threshold（item f03d70778889）/
        # _normalize_transient_seconds 的「非整值浮点回退缺省」口径对齐。
        # .nan/.inf 的 is_integer() 恒 False，同在此回缺省（_validate 只拒非
        # 有限浮点，非整值浮点合法通过加载，本门面是唯一守卫点）。显式 0 仍
        # 合法（快速停机）、负数仍由下方 max(0, …) 夹 0，既有取值语义不变；
        # bool 已由 _num 既有护栏回缺省，此处不重复判定。
        shutdown_drain_raw = admin.get("shutdown_drain_seconds")
        if isinstance(shutdown_drain_raw, float) and not shutdown_drain_raw.is_integer():
            shutdown_drain_raw = 1800

        return {
            "enabled": enabled,
            "interval_minutes": _num(admin.get("interval_minutes"), 5.0, float),
            "agent_model": admin.get("agent_model") or None,
            "escalation_cooldown_minutes": _num(
                admin.get("escalation_cooldown_minutes"), 60.0, float
            ),
            "stuck_threshold_minutes": stuck_seconds / 60.0,
            # add-control-plane-silent-failure-guards D5：孤儿状态（状态无驱动）
            # 探测阈值——缺省 15 分钟（= 3 个 interval_minutes(5) 巡检周期，
            # 与巡检周期整数倍对齐避免漏检），远短于 stuck（run_timeout+600s，
            # 当前约 160 分钟），使「状态无驱动」分钟级可发现。与 stuck 阈值
            # 互不影响（独立键，stuck 仍由 run_timeout 单源派生）。
            "orphaned_state_threshold_minutes": _num(
                admin.get("orphaned_state_threshold_minutes"), 15.0, float
            ),
            "merge_breaker_threshold": int(breaker),
            # interrupt-recovery-preserve D1：规划性重启排水窗口（秒）；0 = 现行
            # 快速停机。缺省 1800（半小时量级，用户已确认方向）。
            # 显式 is None 判缺省（code-review item 8d6d85bb339f）：旧实现用
            # `or 1800` 真值回退，把**显式配置的 0** 当假值又还原成 1800——而
            # `_validate` 明确允许 0（只拒负数）且 docstring 声明「0 = 快速停机」，
            # 使这条快速停机路径经本门面永远请求不到（daemon/supervisor 的读取方
            # 是尊重 0 的，口径不一致）。
            "shutdown_drain_seconds": max(
                0,
                _num(
                    1800 if shutdown_drain_raw is None else shutdown_drain_raw,
                    1800,
                    int,
                ),
            ),
            # add-bug-repair-mode-config：bug-found 修复方式（未配置缺省 inplace）
            "bug_repair_mode": brm,
            # stuck-signal-hygiene D3/D4：stuck 处置后静默期（分钟）——
            # (spec, signal_type) 最近一次 result∈{resolved, partially-resolved}
            # 处置后，窗口内不产生 stuck 信号（非负护栏，0=不静默）。
            "stuck_silence_minutes": _num(
                admin.get("stuck_silence_minutes"), 120.0, float
            ),
            # add-daily-self-review：自省配置段（enabled 缺省 false）
            "self_review": cls.get_self_review_config(config),
            # evo-run-failure-classification-circuitbreaker D5：infra 熔断配置
            # 段（阈值/冷却分钟，缺省 3/30）
            "run_infra_breaker": cls.get_run_infra_breaker_config(config),
            # add-adjudication-alert-narrative：转人工裁决告警三段式叙事三键
            # （叙事开关缺省 true；同步调用硬超时缺省 180s；模型缺省 None=
            # 回退链 admin.agent_model → 框架默认）
            "narrative_enabled": narrative_enabled,
            "narrative_timeout_seconds": narrative_timeout,
            "narrative_model": admin.get("narrative_model") or None,
            # add-alert-self-heal-marking 3.2：瞬态告警自愈安静窗口（分钟，
            # 缺省 1440，脏值回退——见上方取值段）
            "self_heal_quiet_minutes": self_heal_quiet_minutes,
        }

    # ── 陈旧自愈配置（add-stale-code-selfheal D5）──────────────────────
    # stale_code_selfheal 节两键缺省：enabled 默认开启（本项目陈旧是常态，默认
    # 关闭等于把问题留给用户发现；风险由 supervisor 熔断兜底、由开关提供退出
    # 通道）；idle_confirm_seconds 取 600s 作为连续空闲确认窗（触发实现在
    # fenixd.py 主循环 _maybe_stale_selfheal_tick）。evo-reduce-stale-code-
    # selfheal-noise：120s（沿自 daemon 内建化之前的实践）会把开发日密集落地
    # 的代码批次逐个放大成多轮重启（2026-09-26 实测单日 16 次重启 + drain
    # 约 20 分钟不可用）；600s 窗让短间隙批次由同一轮重启一次收编（重启加载
    # 的是触盘时点的全部代码），小时间隔的独立批次仍各得一轮重启。项目级
    # stale_code_selfheal.idle_confirm_seconds 覆盖语义不变。
    STALE_CODE_SELFHEAL_ENABLED_DEFAULT = True
    STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT = 600
    STALE_CODE_SELFHEAL_MAX_SECONDS = 86400  # 仅建议上界（警告不拒绝），保持读取宽容语义
    # evo-stale-selfheal-restart-cooldown：重启冷却与自触发识别缺省
    # （窗口 / 阈值 / 锁存时长 / 自触发窗口 / 自触发升级阈值）
    STALE_CODE_SELFHEAL_COOLDOWN_WINDOW_SECONDS_DEFAULT = 1800
    STALE_CODE_SELFHEAL_COOLDOWN_THRESHOLD_DEFAULT = 3
    STALE_CODE_SELFHEAL_COOLDOWN_DURATION_SECONDS_DEFAULT = 600
    STALE_CODE_SELFHEAL_SELF_TRIGGERED_WINDOW_SECONDS_DEFAULT = 300
    STALE_CODE_SELFHEAL_SELF_TRIGGERED_THRESHOLD_DEFAULT = 3
    # evo-add-stale-code-dangling-deadline 1.1：陈旧悬空超时升级时限缺省
    # （4 小时——白天 code-fix 高频节律下最多损失一个批次的排水重跑）。
    # 0 = 关闭升级（只保留空闲自愈路径）；负值/非整数/bool 回退缺省。
    STALE_CODE_SELFHEAL_MAX_DANGLING_SECONDS_DEFAULT = 14400

    @classmethod
    def _stale_selfheal_positive_int(cls, section: Dict[str, Any], key: str, default: int) -> int:
        """取 ``section[key]`` 的正整数，非法/缺失回退 ``default``（不抛异常）。

        bool 是 int 子类须显式排除（``True``/``False`` 不是合法的秒数/次数）；
        ``0`` / 负数 / 字符串 / None / 非整值浮点一律回退缺省——与
        ``idle_confirm_seconds`` 同款校验范式（``0`` 不等效关闭）。非有限
        浮点（YAML ``.nan``/``.inf`` 字面量）同样回退缺省；非整值浮点（如
        ``0.5``）旧实现 ``int()`` 截断成 0 返回，恰落进「0 一律回退缺省」的
        非法域（code-review item 2460e8a27c5d），现与
        ``_normalize_transient_seconds`` 同口径回退缺省，整值浮点（``30.0``）
        仍按整数接受。
        """
        value = section.get(key, default)
        # 判定核心单点收敛 _normalize_int_value（code-review item 05cdb9c48227）：
        # bool/非数值/非有限浮点（.nan/.inf 能穿透 isinstance 与 <=0 比较、
        # int() 抛异常，code-review d9e9a238696f）/非整值浮点（旧 int() 截断
        # 成 0，code-review item 2460e8a27c5d）/0/负数一律回退缺省，整值浮点
        # 按整数接受——接受集与原实现逐值一致。
        return cls._normalize_int_value(value, default, positive=True)

    @classmethod
    def _stale_selfheal_dangling_seconds(
        cls, section: Dict[str, Any], key: str, default: int
    ) -> int:
        """取 ``section[key]`` 的非负秒数，非法/缺失回退 ``default``（不抛异常）。

        evo-add-stale-code-dangling-deadline 1.1：MUST NOT 复用
        ``_stale_selfheal_positive_int``——后者「0/负数一律回退缺省（0 不等效
        关闭）」，与本键「0 = 关闭升级」语义冲突。本校验：``0``（含 0.0 整值
        浮点）合法并原样返回 0（关闭升级）；负值 / 字符串 / None / bool（int
        子类须显式排除）回退缺省；非整值浮点同样回退缺省（code-review item
        6a69eac80f8a，与 _normalize_transient_seconds 同口径——旧 ``int()``
        截断把 ``0.5`` 变成 0，语义翻转成「关闭升级」而非回退缺省 14400）。
        """
        value = section.get(key, default)
        # 判定核心单点收敛 _normalize_int_value（code-review item 05cdb9c48227）：
        # 0（含 0.0 整值浮点）合法返回 0（关闭升级）；负值/字符串/None/bool/
        # 非整值浮点（旧 int() 截断把 0.5 翻转成关闭语义而非回退缺省，code-
        # review item 6a69eac80f8a）/非有限浮点（穿透 ==0 与 <0 比较，code-
        # review d9e9a238696f）回退缺省——接受集与原实现逐值一致。
        return cls._normalize_int_value(value, default, positive=False)

    @classmethod
    def get_stale_code_selfheal_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``stale_code_selfheal`` 段，缺失/非法值回退缺省。

        - enabled: 布尔，缺省 True（非布尔回退缺省——布尔缺省语义下非法即用缺省）
        - idle_confirm_seconds: 正整数秒，缺省 600（evo-reduce-stale-code-
          selfheal-noise，原 120；非整数/负数/0 回退缺省；bool 是 int 子类
          须显式排除）
        - cooldown_window_seconds / cooldown_threshold / cooldown_duration_seconds /
          self_triggered_window_seconds / self_triggered_threshold: 正整数，缺省
          1800 / 3 / 600 / 300 / 3（evo-stale-selfheal-restart-cooldown）。冷却
          无独立开关，整体关闭走 enabled: false；五键经 .fenix/config.yaml 配置
          + 30s 热更新生效，本 SPEC 不扩展 Dashboard 面板/写白名单
        - max_dangling_seconds: 非负整数秒，缺省 14400（4 小时），0 = 关闭
          升级；负值/非整数/bool 回退缺省（evo-add-stale-code-dangling-deadline
          1.1，校验语义与正整数键不同，见 _stale_selfheal_dangling_seconds）

        节缺失、键缺失或值非法时不抛异常、不使 daemon 启动失败；读取走既有
        config 对象，30s 配置热更新自然生效（下一检测周期起采用新值）。
        """
        # 段入口经 _segment_or_empty 归一（code-review item 112323a798bf）：
        # 整段非 dict（如 stale_code_selfheal: [1]）ERROR 告警并按空段降级，
        # 对齐同族读取器——配置没生效时日志留痕，不再静默。
        section = cls._segment_or_empty(config, "stale_code_selfheal")
        enabled = section.get("enabled", cls.STALE_CODE_SELFHEAL_ENABLED_DEFAULT)
        if not isinstance(enabled, bool):
            enabled = cls.STALE_CODE_SELFHEAL_ENABLED_DEFAULT
        # 与同段五个正整数键（cooldown_threshold 等）共用 _stale_selfheal_
        # positive_int 归一口径（code-review item 44ca4611627e）：旧内联分支缺
        # 「非整值浮点回退缺省」，0.5 经 int() 截断成 0 秒确认窗、陈旧自愈在
        # 首个空闲 tick 立即触发。非有限浮点（.nan/.inf）同由 helper 排除，
        # d9e9a238696f 的「不抛异常」契约保持不变。
        seconds = cls._stale_selfheal_positive_int(
            section,
            "idle_confirm_seconds",
            cls.STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT,
        )
        if seconds > cls.STALE_CODE_SELFHEAL_MAX_SECONDS:
            _logger.warning(
                "stale_code_selfheal.idle_confirm_seconds 过大 (%ss，建议 ≤ %s)："
                "自愈将在长时间空闲后才触发（不拒绝，按配置生效）",
                seconds,
                cls.STALE_CODE_SELFHEAL_MAX_SECONDS,
            )
        pos = cls._stale_selfheal_positive_int
        return {
            "enabled": enabled,
            "idle_confirm_seconds": seconds,
            "cooldown_window_seconds": pos(
                section,
                "cooldown_window_seconds",
                cls.STALE_CODE_SELFHEAL_COOLDOWN_WINDOW_SECONDS_DEFAULT,
            ),
            "cooldown_threshold": pos(
                section,
                "cooldown_threshold",
                cls.STALE_CODE_SELFHEAL_COOLDOWN_THRESHOLD_DEFAULT,
            ),
            "cooldown_duration_seconds": pos(
                section,
                "cooldown_duration_seconds",
                cls.STALE_CODE_SELFHEAL_COOLDOWN_DURATION_SECONDS_DEFAULT,
            ),
            "self_triggered_window_seconds": pos(
                section,
                "self_triggered_window_seconds",
                cls.STALE_CODE_SELFHEAL_SELF_TRIGGERED_WINDOW_SECONDS_DEFAULT,
            ),
            "self_triggered_threshold": pos(
                section,
                "self_triggered_threshold",
                cls.STALE_CODE_SELFHEAL_SELF_TRIGGERED_THRESHOLD_DEFAULT,
            ),
            # evo-add-stale-code-dangling-deadline 1.1：悬空超时升级时限
            # （0 = 关闭升级，只保留既有空闲自愈路径）
            "max_dangling_seconds": cls._stale_selfheal_dangling_seconds(
                section,
                "max_dangling_seconds",
                cls.STALE_CODE_SELFHEAL_MAX_DANGLING_SECONDS_DEFAULT,
            ),
        }

    @classmethod
    def get_self_evolution_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``self_evolution`` 段，缺失/非法值回退缺省。

        - auto_accept: 布尔，缺省 False（非布尔回退缺省，与 stale_code_selfheal
          的 bool 处理方式一致；`1`/`"yes"` 等 truthy 非布尔值同样回退缺省）
        - max_items_per_run: 正整数，缺省 20，上界 200（非整数 / bool / < 1 /
          > 200 → 回退缺省 20）
        - spec_run_at: 缺省 None（立项后立即执行）；合法值域为 None 或 "HH:mm"
          （每日该时刻执行）。非 None 且非合法 HH:mm 字符串 → ERROR 后回退
          None（与 max_items_per_run 同款软回退，不让脏值卡住立项）

        节缺失、键缺失或值非法时不抛异常、不使 daemon 启动失败；读取走既有
        config 对象，30s 配置热更新自然生效。
        """
        # 段入口经 _segment_or_empty 归一（code-review item 112323a798bf）：
        # 与 _validate 的 self_evolution 段 ERROR 护栏同口径，整段非 dict 时
        # ERROR 告警并按空段降级，对齐同族读取器（get_self_review_config 等）。
        section = cls._segment_or_empty(config, "self_evolution")
        # auto_accept：必须为布尔，显式 True 才生效
        auto_accept = section.get("auto_accept", SELF_EVOLUTION_AUTO_ACCEPT_DEFAULT)
        if not isinstance(auto_accept, bool):
            auto_accept = SELF_EVOLUTION_AUTO_ACCEPT_DEFAULT
        # max_items_per_run：正整数（严格 int，bool/float/字符串均非法），上界 200
        max_items = section.get("max_items_per_run", SELF_EVOLUTION_MAX_ITEMS_DEFAULT)
        if (
            isinstance(max_items, bool)
            or not isinstance(max_items, int)
            or max_items < 1
            or max_items > SELF_EVOLUTION_MAX_ITEMS_UPPER
        ):
            max_items = SELF_EVOLUTION_MAX_ITEMS_DEFAULT
        # spec_run_at：None 或 HH:mm
        spec_run_at = section.get("spec_run_at")
        if spec_run_at is not None and not (
            isinstance(spec_run_at, str) and _HHMM_RE.match(spec_run_at)
        ):
            spec_run_at = SELF_EVOLUTION_SPEC_RUN_AT_DEFAULT
        return {
            "auto_accept": auto_accept,
            "max_items_per_run": int(max_items),
            "spec_run_at": spec_run_at,
        }

    @classmethod
    def get_self_review_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``admin.self_review.*`` 段，缺失项填默认值。

        默认值（add-daily-self-review design D1 / Migration Plan）：
        - enabled: False（纯增量，用户显式开启后才调度）
        - run_at: "02:00"（每晚时间点，HH:MM）
        - read_todo: False（不注入既有 todo.md 上下文）
        - todo_head_restore: True（回写前 HEAD 自愈，evo-self-review-todo-head-restore）

        run_at 经 ``_validated_run_at`` 兜底：非法值（类型错误/格式错误/越界
        时分）打 ERROR 并按 "02:00" 回退生效，保证调度判定永远拿到合法 HH:MM。
        """
        # 段入口经 _segment_or_empty 归一（code-review item 997a8452a39f）：
        # 与 get_admin_config 及同族 admin.* 读取器对齐——真值非 dict 段 ERROR
        # 降级，非 dict config 本身也不再抛 AttributeError。
        admin = cls._segment_or_empty(config, "admin")
        # admin 已由助手归一、契约恒返回 dict（code-review item 8dd876b76689），
        # 不再重复 isinstance 防御
        sr = admin.get("self_review")
        if not isinstance(sr, dict):
            sr = {}
        # 严格 bool：bool(...) 会把任何 truthy 非 bool 值（如 YAML 引号串
        # enabled: "false"）静默转 True、意外开启自省周期调度；非 bool 回退
        # 文档缺省 False（与 get_regression_config 同范式，code-review
        # item 1050310f1b6e）。
        enabled = sr.get("enabled", False)
        if not isinstance(enabled, bool):
            enabled = False
        read_todo = sr.get("read_todo", False)
        if not isinstance(read_todo, bool):
            read_todo = False
        # todo_head_restore：回写前 HEAD 自愈开关（evo-self-review-todo-head-
        # restore R2），缺省 true（清空丢历史是已兑现事故形态，防护默认在）；
        # 非 bool 回退缺省，同 read_todo 既有严格 bool 范式。false 供有意清空
        # 台账时豁免——跳过恢复且不落恢复 WARNING。
        todo_head_restore = sr.get("todo_head_restore", True)
        if not isinstance(todo_head_restore, bool):
            todo_head_restore = True
        return {
            "enabled": enabled,
            "run_at": cls._validated_run_at(sr.get("run_at")),
            "read_todo": read_todo,
            "todo_head_restore": todo_head_restore,
        }

    @classmethod
    def get_code_review_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``admin.code_review.*`` 段，缺失项填默认值。

        默认值（add-code-review-agent-and-quality-tab D7）：
        - enabled: False（纯增量，用户显式开启后才进入周期调度；手动触发
          不受该开关约束——用户显式点击即执行，与 admin.self_review 的
          「开关只管周期调度」语义一致）
        - max_files: 500（全仓审查 manifest 上限；窗口审查按窗口收集。
          非法值（非正整数/类型错误）回退缺省）
        - scope: "window"（add-code-review-scope-config：周期审查范围两档）
          - "window"（缺省）：窗口审查——只审 window_start（自省同源）之后
            变更文件；
          - "full"：全库审查——collect_manifest 全仓受控源码文件，与项目页
            「全库审查」手动按钮同语义；max_files 上限两档同样生效。
          回退规则：值恰为字符串 "full" 才生效为 full；其余一切（键缺失、
          "window"、非法字面量、非字符串类型）一律回退 "window"——周期
          巡检路径 MUST NOT 因配置脏值中断，且缺省即历史行为（向后兼容）。
        - stall_alert_minutes: 15（add-code-review-sharded-out：事中零进度
          停滞告警阈值，分钟；消费方 core.code_review.check_progress_stall。
          非法值（非正整数/类型错误/bool）回退缺省）
        - run_at: 回退 admin.self_review.run_at（add-code-review-run-at D1：
          周期审查触发时点独立键，本地时间 HH:MM）。cr 段存在且恰能被
          _HHMM_RE（与 _validated_run_at / _parse_run_at 同一格式口径）解析
          为合法 HH:MM 才生效；其余一切（键缺失/非法字面量/非字符串类型）
          回退 get_self_review_config(config)["run_at"]——缺省路径零行为
          变化（用户定调「暂不挪时点，仅解耦配置能力」，与自省同刻的现状
          保持，时点后续可在 Dashboard 设置页自行调整错峰）。巡检路径
          MUST NOT 因配置脏值中断（对齐 scope 白名单回退口径）。
        """
        # 段入口经 _segment_or_empty 归一（code-review item 4d46314da624）：
        # 与 get_admin_config/get_self_review_config 对齐——admin 整段为列表/
        # 标量时 ERROR 告警并按空段降级，不再静默吞掉故障配置。
        admin = cls._segment_or_empty(config, "admin")
        cr = admin.get("code_review")
        if not isinstance(cr, dict):
            cr = {}
        max_files = cr.get("max_files", 500)
        if (
            not isinstance(max_files, int)
            or isinstance(max_files, bool)
            or max_files <= 0
        ):
            max_files = 500
        # scope 白名单：恰为 "full" 才取 full，其余（缺失/window/非法字面量/
        # 非字符串类型）一律回退 "window"（add-code-review-scope-config D1）
        scope = cr.get("scope", "window")
        if scope != "full":
            scope = "window"
        # 严格 bool：bool(...) 会把任何 truthy 非 bool 值（如 YAML 引号串
        # enabled: "false"）静默转 True、意外开启周期审查；非 bool 回退文档
        # 缺省 False（与 get_code_review_fix_config 同范式）。
        enabled = cr.get("enabled", False)
        if not isinstance(enabled, bool):
            enabled = False
        # 停滞告警阈值（分钟，正整数，缺省 15）：bool 是 int 子类显式排除
        #（与 max_files 同款守卫）；非法回退缺省。
        stall_alert_minutes = cr.get("stall_alert_minutes", 15)
        if (
            not isinstance(stall_alert_minutes, int)
            or isinstance(stall_alert_minutes, bool)
            or stall_alert_minutes <= 0
        ):
            stall_alert_minutes = 15
        # 手动全仓审查叠加防护阈值（evo-add-code-review-ratelimit-resume 4.1）：
        # 台账 open 条数超过该阈值时手动 full 触发回 409 确认态（对齐
        # trigger-ack 409 守卫先例），body 携带 confirm=true 二次确认后才派发。
        # 缺省 30；显式 0 = 关闭守卫（直接派发，回退历史行为）；负数/bool/
        # 非整数回退缺省。
        manual_full_open_warn = cr.get("manual_full_open_warn", 30)
        if (
            not isinstance(manual_full_open_warn, int)
            or isinstance(manual_full_open_warn, bool)
            or manual_full_open_warn < 0
        ):
            manual_full_open_warn = 30
        # 触发时点（add-code-review-run-at D1）：合法 HH:MM 才生效，其余一切
        # （键缺失/非法字面量/非字符串类型）回退自省 run_at——缺省＝历史行为
        # 逐位一致；_HHMM_RE 与 self_review._parse_run_at 的格式口径同源。
        cr_run_at = cr.get("run_at")
        if not (isinstance(cr_run_at, str) and _HHMM_RE.match(cr_run_at)):
            cr_run_at = cls.get_self_review_config(config)["run_at"]
        return {
            "enabled": enabled,
            "max_files": int(max_files),
            "scope": scope,
            "stall_alert_minutes": int(stall_alert_minutes),
            "manual_full_open_warn": int(manual_full_open_warn),
            "run_at": cr_run_at,
        }

    @classmethod
    def get_code_review_fix_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``admin.code_review_fix.*`` 段，缺失项填默认值。

        默认值（add-code-review-auto-fix D9）：
        - enabled: False（总开关；关闭 = 全链路零动作——不选批、不派 run、
          不写进度。严格 bool：非 bool 值（如字符串/数字）回退 False）
        - batch_size: 20（每批条目数；必须为正整数，bool / ≤0 / 非整数
          回退 20）
        - targeted_retry_max: 3（add-codefix-targeted-retry 2.4；回归失败
          后定向重试轮上限，注释约束合理区间 1-5，bool / 非整数 / 越界
          回退 3——过大烧钱、0 会让「重试一次」的现状语义都保不住）
        - targeted_regression: True（add-codefix-affinity-batching 4.1；
          批收尾回归两段式：true=链内非末批按触碰面定向回归 + 链末批恒
          全量兜底，false=全批全量。严格 bool，非法值回退缺省 True 并记
          warning——不抛异常中断批链）
        - min_immediate_severity: "major"（evo-add-codefix-severity-batch-gate
          1.1；发现分级处置门限：severity 达门限的条目保持当日批序，低于
          门限的延后累积至周批。severity 契约词表四档 critical|major|minor|
          info，词表外取值（含历史漂移值域 high/medium/low——配置侧不做
          归一，避免误把写侧漂移当合法门限）回退缺省并记 warning）
        - minor_batch_cadence: 7（evo-add-codefix-severity-batch-gate 1.1；
          周批节奏天数：低于门限条目挂起距首挂起锚达该天数后整组放行。
          正整数；bool/非整数/非正值回退缺省并记 warning）
        - severity_batch_gate_enabled: False（2026-10-11；severity 分级门限
          总开关。缺省关闭＝当天发现的所有内容当天处理（不挂起、不积累
          周批），关闭语义在 gate 解析层（severity_gate_from_config_segment
          返回 None）整体旁路。严格 bool：非 bool 值回退 False 并记
          warning）
        段缺失或非 dict 时整体视为缺省，不抛异常。
        """
        # 段入口经 _segment_or_empty 归一（code-review item 4d46314da624）：
        # 与 get_admin_config/get_self_review_config 对齐——admin 整段为列表/
        # 标量时 ERROR 告警并按空段降级，不再静默吞掉故障配置。
        admin = cls._segment_or_empty(config, "admin")
        crf = admin.get("code_review_fix")
        if not isinstance(crf, dict):
            crf = {}
        enabled = crf.get("enabled", False)
        if not isinstance(enabled, bool):
            enabled = False
        batch_size = crf.get("batch_size", 20)
        if (
            not isinstance(batch_size, int)
            or isinstance(batch_size, bool)
            or batch_size <= 0
        ):
            batch_size = 20
        targeted_retry_max = crf.get("targeted_retry_max", 3)
        if (
            not isinstance(targeted_retry_max, int)
            or isinstance(targeted_retry_max, bool)
            or not 1 <= targeted_retry_max <= 5
        ):
            targeted_retry_max = 3
        targeted_regression = crf.get("targeted_regression", True)
        if not isinstance(targeted_regression, bool):
            cls._warn_reader_once(
                "admin.code_review_fix.targeted_regression",
                targeted_regression,
                _logger.warning,
                "admin.code_review_fix.targeted_regression 非法值 %r（非 bool），"
                "回退缺省 True",
                targeted_regression,
            )
            targeted_regression = True
        # severity 分级门限（evo-add-codefix-severity-batch-gate 1.1）：词表
        # 白名单回退（对齐 scope 的白名单口径）；非法值不阻断评审与修复主链。
        min_immediate_severity = crf.get("min_immediate_severity", "major")
        if min_immediate_severity not in ("critical", "major", "minor", "info"):
            cls._warn_reader_once(
                "admin.code_review_fix.min_immediate_severity",
                min_immediate_severity,
                _logger.warning,
                "admin.code_review_fix.min_immediate_severity 非法值 %r"
                "（severity 词表外），回退缺省 major",
                min_immediate_severity,
            )
            min_immediate_severity = "major"
        # 周批节奏天数：严格正整数（bool 是 int 子类显式排除，与 batch_size
        # 同款守卫）；非法回退缺省不抛异常。
        minor_batch_cadence = crf.get("minor_batch_cadence", 7)
        if (
            not isinstance(minor_batch_cadence, int)
            or isinstance(minor_batch_cadence, bool)
            or minor_batch_cadence <= 0
        ):
            cls._warn_reader_once(
                "admin.code_review_fix.minor_batch_cadence",
                minor_batch_cadence,
                _logger.warning,
                "admin.code_review_fix.minor_batch_cadence 非法值 %r"
                "（非正整数），回退缺省 7",
                minor_batch_cadence,
            )
            minor_batch_cadence = 7
        # severity 分级门限总开关（2026-10-11）：缺省关闭（当天内容当天
        # 处理）；严格 bool，非法回退 False（视同关闭）。
        severity_batch_gate_enabled = crf.get(
            "severity_batch_gate_enabled", False)
        if not isinstance(severity_batch_gate_enabled, bool):
            cls._warn_reader_once(
                "admin.code_review_fix.severity_batch_gate_enabled",
                severity_batch_gate_enabled,
                _logger.warning,
                "admin.code_review_fix.severity_batch_gate_enabled 非法值 %r"
                "（非 bool），回退 False（视同关闭）",
                severity_batch_gate_enabled,
            )
            severity_batch_gate_enabled = False
        return {
            "enabled": enabled,
            "batch_size": int(batch_size),
            "targeted_retry_max": int(targeted_retry_max),
            "targeted_regression": targeted_regression,
            "min_immediate_severity": min_immediate_severity,
            "minor_batch_cadence": int(minor_batch_cadence),
            "severity_batch_gate_enabled": severity_batch_gate_enabled,
        }

    @classmethod
    def get_knowledge_lane_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``knowledge.*`` 维护车道生效值（add-knowledge-atlas-maintenance D4）。

        - audit_enabled / no_conflict_exempt：bool，缺省 True
          （纯增量：audit 车道默认随每日检查点开启；
          no_conflict_exempt 为疑点台账的内容豁免开关，
          add-knowledge-audit-finding-ledger 4.1）。
        - escalate_after_rounds：正整数，缺省 2（同一疑点连续 N 轮复核均无
          确定性判定即升级待人工；豁免解冻重派不计入升级轮次）。
        - escalated_stale_days：正整数，缺省 7（escalated 挂起超过该天数即对
          涉事知识页写 disputed 超龄注记，add-knowledge-audit-escalation-
          consumption 2.1）。
        - 非法值不阻塞加载/热更新：WARNING 告警并回退缺省（bool 键同
          get_code_review_fix_config 的 targeted_regression 口径——解析级
          容错，语义破坏由消费方门控兜底）。
        - 段入口经 _segment_or_empty 归一：整段非 dict 时该段按空段降级（ERROR
          已由助手记录），各键取缺省值。
        - ``enabled``（蒸馏总开关）归前置 SPEC add-knowledge-atlas 的解析器所有，
          本方法不触碰，合并后各键同段共存。
        - graph_enabled 已随 graphify 关系图生成功能取消下线（2026-09-29），
          不再解析；存量配置文件中的该键被静默忽略（未知键不告警）。
        """
        knowledge = cls._segment_or_empty(config, "knowledge")
        result = {}
        for key, default in (
            ("audit_enabled", True),
            ("no_conflict_exempt", True),
        ):
            val = knowledge.get(key, default)
            if not isinstance(val, bool):
                cls._warn_reader_once(
                    f"knowledge.{key}",
                    val,
                    _logger.warning,
                    "knowledge.%s 非法值 %r（非 bool），回退缺省 %s",
                    key,
                    val,
                    default,
                )
                val = default
            result[key] = val
        rounds = knowledge.get("escalate_after_rounds", 2)
        # bool 是 int 子类：True/False 不当轮次数（与 regression.enabled 的严格
        # bool 同理，防 YAML 引号串/布尔值被静默当 1/0）
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
            cls._warn_reader_once(
                "knowledge.escalate_after_rounds",
                rounds,
                _logger.warning,
                "knowledge.escalate_after_rounds 非法值 %r（非正整数），回退缺省 2",
                rounds,
            )
            rounds = 2
        result["escalate_after_rounds"] = rounds
        stale = knowledge.get("escalated_stale_days", 7)
        # 同 escalate_after_rounds 口径：bool 是 int 子类不当天数
        if not isinstance(stale, int) or isinstance(stale, bool) or stale < 1:
            cls._warn_reader_once(
                "knowledge.escalated_stale_days",
                stale,
                _logger.warning,
                "knowledge.escalated_stale_days 非法值 %r（非正整数），回退缺省 7",
                stale,
            )
            stale = 7
        result["escalated_stale_days"] = stale
        return result

    @classmethod
    def get_regression_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``admin.regression.*`` 段，缺失项填默认值。

        默认值（add-test-regression-tab）：
        - enabled: False（周期全量回归开关，缺省关闭零动作；与
          admin.code_review.enabled 同形制——开关只管周期调度，手动
          触发不受约束）
        """
        # 段入口经 _segment_or_empty 归一（code-review item 4d46314da624）：
        # 与 get_admin_config/get_self_review_config 对齐——admin 整段为列表/
        # 标量时 ERROR 告警并按空段降级，不再静默吞掉故障配置。
        admin = cls._segment_or_empty(config, "admin")
        reg = admin.get("regression")
        if not isinstance(reg, dict):
            reg = {}
        # 严格 bool：bool(...) 会把任何 truthy 非 bool 值（如 YAML 引号串
        # enabled: "false"）静默转 True、意外开启周期回归；非 bool 回退文档
        # 缺省 False（与 get_code_review_fix_config 同范式）。
        enabled = reg.get("enabled", False)
        if not isinstance(enabled, bool):
            enabled = False
        return {
            "enabled": enabled,
        }

    @classmethod
    def get_run_infra_breaker_config(cls, config: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Return the ``admin.run_infra_breaker.*`` 段，缺失项填默认值（D5）。

        默认值：
        - threshold: 3（连续 infra 失败触发熔断）
        - cooldown_minutes: 30（熔断冷却时长，分钟）

        非法值（非正数/类型错误）回退缺省（config D5 读取宽容语义）。
        """
        # 段入口经 _segment_or_empty 归一（code-review item 4d46314da624）：
        # 非 dict admin 段 ERROR 告警并按空段降级，对齐同族 admin.* 读取器
        # （config=None 缺省参时助手按空段处理，全缺省语义不变）。
        admin = cls._segment_or_empty(config, "admin")
        ib = admin.get("run_infra_breaker")
        if not isinstance(ib, dict):
            ib = {}
        threshold = ib.get("threshold", 3)
        cooldown = ib.get("cooldown_minutes", 30)
        # 校验：必须为整值 ≥ 1（排除 bool，code-review item 46b77a7d7e83）；
        # 小数非整值回退缺省（code-review item f03d70778889）——旧实现 int()
        # 静默截断（2.5→2 阈值偏移，0.5→0 首次即判失败）。判定核心已单点
        # 收敛 _normalize_int_value（code-review item 05cdb9c48227）：接受集
        # 与原内联守卫逐值一致（正整数、整值浮点按整数接受、.nan/.inf 同拒）。
        threshold = cls._normalize_int_value(threshold, 3, positive=True)
        # 非有限浮点同拒（code-review item 25f2aed84a49，范式先例 a61ee2b2031e /
        # d9e9a238696f）：nan 使 <=0 比较恒 False 可穿透校验，冷却比较恒 False
        # （熔断即建即恢复或永不恢复），且经 get_admin_config 嵌套输出时以 NaN
        # 字面量进入 JSON 序列化（非法 JSON）。
        if (
            not isinstance(cooldown, (int, float))
            or isinstance(cooldown, bool)
            or (isinstance(cooldown, float) and not math.isfinite(cooldown))
            or cooldown <= 0
        ):
            cooldown = 30
        return {
            "threshold": int(threshold),
            "cooldown_minutes": float(cooldown),
        }

    @staticmethod
    def is_valid_hhmm(value) -> bool:
        """静态校验 HH:MM 字符串（00:00–23:59），不含回退逻辑。

        供后端设置写入校验与前端校验共用同一格式语义（add-daily-self-review
        「前端与后端双重校验拒绝非法输入」）。
        """
        return isinstance(value, str) and bool(_HHMM_RE.match(value))

    @classmethod
    def _validated_run_at(cls, raw) -> str:
        """校验 ``run_at`` 的 HH:MM 合法性；非法值打 ERROR 并回退缺省 02:00。

        合法格式：``^([01]\\d|2[0-3]):[0-5]\\d$``（00:00–23:59）。None/缺省
        直接回退缺省（不视为错误，读取方默认值语义）；显式提供的非法值记
        ERROR 后回退。所有消费方（self_review 调度、Dashboard 回显）MUST
        经本助手读取生效值，非法配置不会流入调度判定。
        """
        if raw is None:
            return SELF_REVIEW_DEFAULT_RUN_AT
        if isinstance(raw, str) and _HHMM_RE.match(raw):
            return raw
        # 进程级 (键路径, repr(raw)) 一次性去重（code-review item 18f2c8a3f86c，
        # 同 _warn_reader_once 范式）：本助手被 _validate 每 30s 热更新与
        # get_self_review_config（get_admin_config / get_code_review_config 嵌套、
        # code_review 停滞检测等周期路径）反复调用，坏 run_at 在场时同一 ERROR
        # 逐周期重复打印。去重只作用于日志，回退缺省行为不变。
        cls._warn_reader_once(
            "admin.self_review.run_at",
            raw,
            _logger.error,
            "admin.self_review.run_at 非法（应为 HH:MM，如 22:00）：%r，"
            "回退缺省 %s",
            raw,
            SELF_REVIEW_DEFAULT_RUN_AT,
        )
        return SELF_REVIEW_DEFAULT_RUN_AT

    @classmethod
    def effective_stuck_threshold_seconds(cls, config: Dict[str, Any]) -> float:
        """stuck 判定阈值单源派生自 run 超时（design D1/D2/D4）。

        effective_threshold = run_timeout_seconds + STUCK_GRACE_SECONDS（600s）。
        run_timeout_seconds 缺失、非正数或非有限浮点（.nan）时回退
        STUCK_FALLBACK_SECONDS（9600s）并打
        WARNING（D4：
        防有人把超时关掉导致恢复永不触发）。旧键
        schedule/admin.stuck_threshold_minutes 不论是否配置都不影响结果（D3 告警）。

        pm_engine.check_blockers 与 admin_monitor 的 stuck 检测 MUST 调用本助手，
        不再各自读取旧键。
        """
        global _STUCK_FALLBACK_WARNED
        cls._maybe_warn_deprecated_stuck_keys(config)
        agents = cls._segment_or_empty(config, "agents")
        rt = agents.get("run_timeout_seconds")
        # bool 排除与 effective_run_timeout_seconds 同口径（code-review item
        # d5c6b590a12b）：bool 是 int 子类，agents.run_timeout_seconds: true
        # 此前通过检查得 float(True)+600=601s 而非文档 9600s 回退，使 stuck/
        # auto-recovery 阈值比其派生源 run 超时（9000s 回退）早约 15 倍触发，
        # 打破单源派生保证。
        # code-review d9e9a238696f：YAML .nan 字面量穿透 isinstance 与 <=0 检查，
        # 阈值得 nan+600，后续超时比较恒 False，stuck/恢复判定永不触发——
        # 非有限浮点与缺失/非正数同口径回退
        if (
            not isinstance(rt, (int, float))
            or isinstance(rt, bool)
            or (isinstance(rt, float) and not math.isfinite(rt))
            or rt <= 0
        ):
            if not _STUCK_FALLBACK_WARNED:
                _logger.warning(
                    "agents.run_timeout_seconds 缺失或 ≤0，stuck 阈值按 %ss 回退生效"
                    "（=9000 默认超时 + %ss 宽限）；建议显式配置 run_timeout_seconds",
                    STUCK_FALLBACK_SECONDS,
                    STUCK_GRACE_SECONDS,
                )
                _STUCK_FALLBACK_WARNED = True
            return float(STUCK_FALLBACK_SECONDS)
        return float(rt) + STUCK_GRACE_SECONDS

    @classmethod
    def _maybe_warn_deprecated_stuck_keys(cls, config: Dict[str, Any]) -> None:
        """旧键弃用告警，生命周期内只打一次（design D3）。

        schedule.stuck_threshold_minutes / admin.stuck_threshold_minutes 仍可能残留在
        配置中（向后兼容读取不报错），但其值已不再作为 stuck 阈值输入——阈值改为由
        run 超时派生。存在任一旧键时打一次 WARNING 指明新语义。
        """
        global _DEPRECATED_STUCK_WARNED
        if _DEPRECATED_STUCK_WARNED:
            return
        # config 本体同款守卫（code-review item da95c072831b）：非 dict config
        # 按空配置降级，与 _segment_or_empty / _supervision_segment 的既有容错
        # 口径一致——本助手是 effective_stuck_threshold_seconds 的第一站（早于
        # 其 _segment_or_empty 读取），config=None 时此处 config.get 先抛
        # AttributeError，击穿同族「非 dict config 也不再抛 AttributeError」降级。
        config = config if isinstance(config, dict) else {}
        schedule = config.get("schedule")
        # schedule 段与 admin 同款守卫：真值非 dict（如手改 YAML schedule: 3）
        # 按空段降级，否则下方 in 成员测试对标量会 TypeError。
        schedule = schedule if isinstance(schedule, dict) else {}
        # admin 段真值非 dict 时按空段降级（code-review item 06352a414cf4）：
        # 下方 in 成员测试对标量会 TypeError，使 effective_stuck_threshold_seconds
        # 在其自身的 agents 段读取之前就崩溃。
        admin = config.get("admin")
        admin = admin if isinstance(admin, dict) else {}
        if "stuck_threshold_minutes" in schedule or "stuck_threshold_minutes" in admin:
            _logger.warning(
                "检测到已弃用的 stuck_threshold_minutes 配置键（schedule/admin）：stuck 阈值"
                "已改为由 agents.run_timeout_seconds 单源派生（run_timeout + %ss 宽限），"
                "旧键值不再生效",
                STUCK_GRACE_SECONDS,
            )
            _DEPRECATED_STUCK_WARNED = True

    @classmethod
    def _supervision_segment(cls, config: Dict[str, Any]) -> Optional[dict]:
        """解析 ``timeout_supervision`` 配置段（supervision-timeout-config-consistency）。

        canonical 位置 ``agents.timeout_supervision``；缺省回退旧版顶层
        ``timeout_supervision``（fix-stuck-threshold-unify 遗留，enabled=false 作
        回退开关，与 liveness ``_supervision_settings`` 读取顺序一致）；两处均非
        dict → 返回 None（supervision 未配置）。

        返回的 dict 是 config 内对象：自动对齐分支靠原地改写 absolute_max_seconds
        使内存生效（持久化由 daemon 经既有写路径完成，本模块不直写配置文件）。
        """
        if not isinstance(config, dict):
            return None
        agents = config.get("agents")
        if isinstance(agents, dict):
            sup = agents.get("timeout_supervision")
            if isinstance(sup, dict):
                return sup
        sup = config.get("timeout_supervision")
        if isinstance(sup, dict):
            return sup
        return None

    @classmethod
    def _supervision_settings(cls, config: Dict[str, Any]) -> dict:
        """规范化后的 supervision 段（缺省填充 ``SUPERVISION_DEFAULTS``）。

        段缺失时按缺省（enabled=true + 默认参数）返回——liveness 运行时缺段时
        仍按缺省激活监督（既有语义）。调用方读 ``enabled`` 判定是否启用。
        """
        cfg = dict(SUPERVISION_DEFAULTS)
        sup = cls._supervision_segment(config)
        if sup is not None:
            # 拷全部 SUPERVISION_DEFAULTS 键（code-review item b724b5ae63a4）：
            # 旧实现只拷 enabled/extension_seconds/max_extensions，用户配置的
            # absolute_max_seconds / judge_window 被静默忽略（调用方读到的恒为
            # 硬编码缺省 7200 / 600）——静默覆盖用户配置。改为按键表全量拷贝。
            for key in SUPERVISION_DEFAULTS:
                if key in sup and sup[key] is not None:
                    cfg[key] = sup[key]
            # 数字键类型归一（code-review item a167cbc7bfe9）：手改配置的脏值
            # （如 max_extensions: "two"）原样拷出后，supervision_floor /
            # supervision_config_floor 的 int()/float() 转换会抛 ValueError，
            # 经 _check_supervision_consistency → _validate 使 load()/热更新
            # 直接失败（报错为 int 解析错误，难以定位）——与本文件「脏值回退
            # 缺省、不中断加载」的 fail-open 哲学相悖。与 _normalize_transient_
            # seconds 同款归一：bool 排除（bool 是 int 子类）、非法回退缺省。
            for key in ("extension_seconds", "max_extensions", "judge_window", "absolute_max_seconds"):
                cfg[key] = cls._normalize_transient_seconds(sup, key, SUPERVISION_DEFAULTS[key])
            # enabled 严格 bool 归一（code-review item 6b032f4596e5）：YAML 引号串
            # enabled: "false" 经真值判定恒按启用生效（bool("false") 亦为 True），
            # 监督被意外开启且无日志线索——与同文件 get_admin_config /
            # get_self_review_config 等既有严格 bool 口径一致：非 bool 打 WARNING
            # 并回退 SUPERVISION_DEFAULTS["enabled"]（True）。
            if not isinstance(cfg["enabled"], bool):
                _logger.warning(
                    "timeout_supervision.enabled 非布尔（%r），回退缺省 %s",
                    cfg["enabled"],
                    SUPERVISION_DEFAULTS["enabled"],
                )
                cfg["enabled"] = SUPERVISION_DEFAULTS["enabled"]
        return cfg

    @classmethod
    def supervision_floor(
        cls,
        config: Dict[str, Any],
        agent_type: str | None = None,
        extension_budget: int | None = None,
    ) -> Optional[float]:
        """supervision absolute_max 下限的单一派生来源（design supervision-timeout-config-consistency）。

        下限 = 生效 run_timeout_seconds（含 per-agent 覆盖）+ 续期预算 × extension_seconds。
        - 生效超时：``effective_run_timeout_seconds``（``agents.timeout_overrides.<agent_type>``
          覆盖，缺省回退全局 / RUN_TIMEOUT_FALLBACK_SECONDS 兜底）；
        - 续期预算：显式传入的 ``extension_budget``，缺省 ``max(0, max_extensions)``；
          fast-track higher 档由调用方传 ``max_extensions + SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS``
          （liveness 运行时按 spec 档位加成，保持既有加成语义）；
        - extension_seconds / max_extensions / enabled 取 ``agents.timeout_supervision``
          （缺省回退旧顶层 ``timeout_supervision``，再回退 SUPERVISION_DEFAULTS）。

        Returns: 下限秒数（float）；supervision 显式 disabled（enabled=false）时
                 返回 None。段缺失按缺省语义派生（liveness 运行时缺段仍按缺省
                 激活监督）；配置校验层在「缺段 / 未配置 absolute_max_seconds」时
                 由调用方跳过校验。
        """
        settings = cls._supervision_settings(config)
        if not settings["enabled"]:
            return None
        if extension_budget is None:
            extension_budget = max(0, int(settings["max_extensions"]))
        extension_seconds = max(1.0, float(settings["extension_seconds"]))
        effective_rt = cls.effective_run_timeout_seconds(config, agent_type)
        return float(effective_rt) + float(extension_budget) * extension_seconds

    @classmethod
    def supervision_config_floor(cls, config: Dict[str, Any]) -> Optional[float]:
        """配置校验层全部署最大可达下限（supervision-timeout-config-consistency）。

        下限 = max(全局 run_timeout_seconds, agents.timeout_overrides 全部值)
              + (max_extensions + SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS) × extension_seconds
        - ``+2`` 覆盖 fast-track higher 档运行时加成：仅按基础预算（如 18600s）
          时，该档运行时仍需 22200s（liveness 按档位加 2 次续期），会再次命中
          同文案 ERROR，「消除 ERROR 复发」目标落空（实测依据见 proposal）；
        - 与既有保守口径同源：SUPERVISION_DEFAULTS 7200（= 4×1800）与模板 16200
          （= 9000 + 4×1800）均按「最大可达续期预算」取值，本函数把手写常数改
          为派生，MUST NOT 下调保守性；
        - ``supervision-judge`` 覆盖不参与（内部轻量判定子进程，非长 run，不参与
          absolute_max 派生，见 TIMEOUT_OVERRIDE_KEYS 注释）。

        Returns: 下限秒数；supervision 未启用（enabled=false）或缺段时返回 None（不校验）。
        """
        sup = cls._supervision_segment(config)
        if sup is None:
            return None
        # enabled 经 _supervision_settings 严格 bool 归一后判定（code-review
        # item 6b032f4596e5）：不再直读原始段真值——引号串 "false" 等非 bool
        # 脏值在此处同样回退缺省，不会按启用路径误入下限校验甚至 fail-fast。
        settings = cls._supervision_settings(config)
        if not settings["enabled"]:
            return None
        budget = max(0, int(settings["max_extensions"])) + SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS
        max_effective = cls.effective_run_timeout_seconds(config, None)
        max_agent = None
        for at in cls.normalize_timeout_overrides(config):
            if at == "supervision-judge":
                continue
            rt = cls.effective_run_timeout_seconds(config, at)
            if rt > max_effective:
                max_effective, max_agent = rt, at
        return cls.supervision_floor(config, agent_type=max_agent, extension_budget=budget)

    @classmethod
    def effective_supervision_absolute_max_seconds(cls, config: Dict[str, Any]) -> Optional[float]:
        """timeout_supervision.absolute_max_seconds 的生效值（含联动兜底，design D5）。

        enabled=true 时：配置值 MUST ≥ 配置校验层下限（supervision_config_floor），
        否则打 ERROR 并按该下限兜底返回。enabled=false 或段缺失：返回 None（不启用
        supervision，不校验）。absolute_max 未配置：返回 None（由消费方按各自默认
        处理，本护栏只约束显式值）。

        agent_runner 的 supervision 激活路径 MUST 调本助手读取兜底值，而非直读原始配置。
        一致性校验（自动对齐 / fail-fast）见 ``_check_supervision_consistency``，本助手
        只读不写，供运行期（runner.py）查询生效值。
        """
        floor = cls.supervision_config_floor(config)
        if floor is None:
            return None
        sup = cls._supervision_segment(config) or {}
        configured = sup.get("absolute_max_seconds")
        # code-review 56eecd2ea903：YAML .nan/.inf 字面量穿透 isinstance 校验，
        # NaN 与 floor 的 < 比较恒 False，NaN 会被当生效值返回，下游 absolute_max
        # 超时比较恒 False，supervision 的无条件终止兜底失效——非有限浮点与
        # 未配置同口径返回 None（消费方按各自默认），与 effective_stuck_threshold_seconds
        # 的 .nan 防御（code-review d9e9a238696f）同款范式。
        if not isinstance(configured, (int, float)) or (
            isinstance(configured, float) and not math.isfinite(configured)
        ):
            return None
        if float(configured) < float(floor):
            # 独立去重标记（code-review item bbfc01b9388a）：运行时下限兜底 ERROR
            # 与 _check_supervision_consistency 的对齐 ERROR 此前共用同一个全局
            # 标记，先触发者会让另一个在整个进程生命周期内静默——真实运行时兜底
            # 可能因早前一次加载已对齐而不留任何痕迹。改用各自的标记。
            global _SUPERVISION_RUNTIME_FLOOR_WARNED
            floor_int = int(floor) if float(floor).is_integer() else float(floor)
            if not _SUPERVISION_RUNTIME_FLOOR_WARNED:
                _logger.error(
                    "timeout_supervision.absolute_max_seconds=%s 低于配置校验层下限 %s"
                    "（max(生效超时) + (max_extensions + %s)×extension_seconds），按 %s 兜底"
                    "生效（supervision 不会先于墙钟终止运行）",
                    configured,
                    floor_int,
                    SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS,
                    floor_int,
                )
                _SUPERVISION_RUNTIME_FLOOR_WARNED = True
            return float(floor)
        return float(configured)

    @classmethod
    def _check_supervision_consistency(cls, config: Dict[str, Any]) -> None:
        """supervision absolute_max 与配置校验层下限的一致性校验（design D5 升级）。

        absolute_max_seconds < 配置校验层下限（supervision_config_floor）时：
        - 默认（``agents.timeout_supervision.auto_align`` 缺省 true）：ERROR 留痕
          （含两侧值、配置层下限、两条修正建议）→ 把 absolute_max 抬升至下限
          （内存生效，供 daemon 经写路径持久化）；MUST NOT 抛异常，保证启动与
          热更新均可继续；
        - auto_align 显式关闭：fail-fast 抛 ValueError——启动/加载失败；热更新沿
          既有 try/except + resolve_config_into「失败不触碰旧 dict」语义拒绝新
          配置、保留旧值，daemon 不退出。

        顺序约定：自动对齐分支先执行，仅当其被显式关闭时才进入阻断分支——两者
        不同时生效。持久化 MUST 复用 core.dashboard.data.write_config（受管键
        白名单 + 原子写 + 配置头注释），由 daemon（fenixd.py）在 resolve_config
        后调用；本模块 MUST NOT 直接写配置文件。
        """
        # 对齐记录按次清零（code-review item c0436bc5e566）：_SUPERVISION_LAST_ALIGNED
        # 若只在对齐分支赋值，不需要对齐的验证 pass 会保留上次记录——不消费该
        # 记录的读方可把过时值带给 daemon 热重载，覆盖用户显式配置的更高
        # absolute_max_seconds。入口先复位：本 pass 未走对齐分支即恒为 None，
        # take_supervision_alignment() 不会读到陈旧值。
        global _SUPERVISION_LAST_ALIGNED
        _SUPERVISION_LAST_ALIGNED = None
        floor = cls.supervision_config_floor(config)
        if floor is None:
            return  # supervision 未启用（enabled=false / 段缺失）：不校验
        sup = cls._supervision_segment(config)
        if sup is None:
            return
        configured = sup.get("absolute_max_seconds")
        # code-review 56eecd2ea903：非有限浮点（.nan/.inf）与未配置同口径不校验，
        # 防 NaN 穿透 >= 比较误入对齐/fail-fast 分支产生「低于下限」的误导性诊断
        if not isinstance(configured, (int, float)) or (
            isinstance(configured, float) and not math.isfinite(configured)
        ):
            return  # 未配置显式 absolute_max（含 .nan/.inf）：由消费方按各自默认处理，不校验
        if float(configured) >= float(floor):
            return  # 一致（含自动对齐后再次校验）
        # 严格 bool 归一（code-review item 6fad622be56a）：引号串
        # auto_align: "false" 真值恒为 True，not 判定不成立会让用户显式要求的
        # fail-fast（拒绝加载、保留旧值）被静默跳过、落入自动对齐分支且无告警
        # 留痕——与 _supervision_settings 的 enabled 同款归一（code-review item
        # 6b032f4596e5）：非 bool 打 WARNING 并按缺省 True（自动对齐）处理。
        auto_align = sup.get("auto_align", True)
        if not isinstance(auto_align, bool):
            _logger.warning(
                "agents.timeout_supervision.auto_align 非布尔（%r），"
                "按缺省 True（自动对齐）处理",
                auto_align,
            )
            auto_align = True
        if not auto_align:
            raise ValueError(
                "timeout_supervision.absolute_max_seconds=%s 低于配置校验层下限 %s"
                "（= max(生效超时) + (max_extensions + %s)×extension_seconds），且 auto_align "
                "已显式关闭：拒绝加载。修正建议：① 抬升 absolute_max_seconds 至 %s 以上；"
                "或 ② 下调 agents.run_timeout_seconds / agents.timeout_overrides 以保住显式硬上限"
                % (
                    configured,
                    floor,
                    SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS,
                    floor,
                )
            )
        # 默认自动对齐：ERROR 留痕 + 内存抬升（持久化由 daemon 经写路径完成）
        # （_SUPERVISION_LAST_ALIGNED 已在函数入口声明 global 并复位）
        global _SUPERVISION_BOUNDS_WARNED
        aligned_value = int(floor) if float(floor).is_integer() else float(floor)
        if not _SUPERVISION_BOUNDS_WARNED:
            _logger.error(
                "timeout_supervision.absolute_max_seconds=%s 低于配置校验层下限 %ss"
                "（= max(生效超时) + (max_extensions + %s)×extension_seconds）：默认自动对齐，"
                "absolute_max 抬升至 %ss 并持久化。修正建议：① 抬升 absolute_max_seconds（保"
                "显式硬上限）；或 ② 下调 agents.run_timeout_seconds / agents.timeout_overrides"
                "（保住 %ss 级硬上限）",
                configured,
                aligned_value,
                SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS,
                aligned_value,
                configured,
            )
            _SUPERVISION_BOUNDS_WARNED = True
        sup["absolute_max_seconds"] = aligned_value  # 内存生效
        _SUPERVISION_LAST_ALIGNED = float(floor)

    @classmethod
    def take_supervision_alignment(cls) -> Optional[float]:
        """读取并复位最近一次「自动对齐」抬升到的下限（消费即复位，供 daemon 持久化）。

        校验层自动对齐时写入、daemon 在 resolve_config / resolve_config_into 后
        消费：返回该下限则调用方应经既有写路径把 absolute_max 落盘；返回 None
        表示本次加载未发生对齐（无持久化必要）。进程级记录，恒反映最新校验的
        配置；未消费的残留会被下一次 _validate 对齐覆盖。
        """
        global _SUPERVISION_LAST_ALIGNED
        value = _SUPERVISION_LAST_ALIGNED
        _SUPERVISION_LAST_ALIGNED = None
        return value

    @classmethod
    def normalize_timeout_overrides(cls, config: Dict[str, Any]) -> Dict[str, int]:
        """校验并规范化 ``agents.timeout_overrides``（逐键：非法键值忽略 + ERROR）。

        per-agent-timeout-override（design D3 / spec 3.1）：
        - 键 ∈ TIMEOUT_OVERRIDE_KEYS（KNOWN_AGENT_TYPES 全集 + repair +
          supervision-judge，随 agents.models 角色集动态扩大）；
        - agent run 键值须为 ≥300 整数（低于下限会截断正常长 run）；
          supervision-judge 键值须为 ≥1 整数（内部轻量判定，不受 300 下限约束）；
          整值浮点（如 ``900.0``）按整数接受（code-review item 01ae33baf2e6，
          与 _normalize_transient_seconds 同口径；is_integer() 对 .nan/.inf 恒
          False，非有限浮点同被拒）；
        - 非法键值**整条忽略**（该键回退全局默认）并打 ERROR，其余合法键正常生效；
          进程不得崩溃（调用方容错）。ERROR 经进程级 (键名, repr(值)) 一次性去重
          （见 _TIMEOUT_OVERRIDE_INVALID_WARNED），坏键在场时只在首次告警。

        Returns: 规范化后的覆盖表 {agent_type: seconds}。缺省/非 dict/空 → {}。
        """
        agents = cls._segment_or_empty(config, "agents")
        raw = agents.get("timeout_overrides")
        if not isinstance(raw, dict) or not raw:
            return {}
        out: Dict[str, int] = {}
        for key, val in raw.items():
            # 三处 ERROR 均只在告警分支去重（code-review item 343d2ec54938）：
            # 忽略/回退行为不变，同一 (键名, 值) 重复出现不再逐周期刷屏。
            if key not in cls.TIMEOUT_OVERRIDE_KEYS:
                dedup_key = (key, None)
                if dedup_key not in _TIMEOUT_OVERRIDE_INVALID_WARNED:
                    _TIMEOUT_OVERRIDE_INVALID_WARNED.add(dedup_key)
                    _logger.error(
                        "agents.timeout_overrides 键 %r 非法（应为 %s 之一），"
                        "该键被忽略并回退全局默认",
                        key,
                        sorted(cls.TIMEOUT_OVERRIDE_KEYS),
                    )
                continue
            # 整值浮点按整数接受（code-review item 01ae33baf2e6）：与
            # _normalize_transient_seconds / get_run_infra_breaker_config 同口径，
            # YAML `900.0`（整值浮点）不再被判非法整条忽略并静默回退全局超时。
            # is_integer() 对 .nan/.inf 恒 False，非有限浮点同被拒。
            if (
                isinstance(val, bool)
                or not isinstance(val, (int, float))
                or (isinstance(val, float) and not val.is_integer())
            ):
                dedup_key = (key, repr(val))
                if dedup_key not in _TIMEOUT_OVERRIDE_INVALID_WARNED:
                    _TIMEOUT_OVERRIDE_INVALID_WARNED.add(dedup_key)
                    _logger.error(
                        "agents.timeout_overrides.%s=%r 非法（应为整数秒），"
                        "该键被忽略并回退全局默认",
                        key,
                        val,
                    )
                continue
            min_allowed = 1 if key == "supervision-judge" else cls.TIMEOUT_OVERRIDE_MIN_SECONDS
            if val < min_allowed:
                dedup_key = (key, repr(val))
                if dedup_key not in _TIMEOUT_OVERRIDE_INVALID_WARNED:
                    _TIMEOUT_OVERRIDE_INVALID_WARNED.add(dedup_key)
                    _logger.error(
                        "agents.timeout_overrides.%s=%s 低于下限 %ss，" "该键被忽略并回退全局默认",
                        key,
                        val,
                        min_allowed,
                    )
                continue
            out[key] = int(val)
        return out

    @classmethod
    def effective_run_timeout_seconds(
        cls, config: Dict[str, Any], agent_type: str | None = None
    ) -> float:
        """agent run 的生效超时（per-agent-timeout-override spec 3.1/3.2）。

        解析顺序 MUST：``agents.timeout_overrides.<agent_type>`` 存在且合法时取覆盖值，
        否则回退 ``agents.run_timeout_seconds`` 全局默认；全局缺失/非正数/非有限浮点
        （.inf/.nan）回退 RUN_TIMEOUT_FALLBACK_SECONDS（9000）。

        覆盖 MUST 适用于 TIMEOUT_OVERRIDE_AGENT_TYPES 全部键（KNOWN_AGENT_TYPES
        全集 + repair，含 implementer、verifier、planner-plan、planner-judge、
        fast-track、repair、administrator、self-review、spec-review、dispute-judge、
        code-review、code-fix；经 _execute_agent 与 _run_agent 统一路径生效）。

        注意：supervision-judge 键不在此处生效（那是 liveness judge 子进程超时，
        经 ``judge_timeout_seconds`` 读取，不参与 absolute_max 派生）。
        """
        global _RUN_TIMEOUT_FALLBACK_WARNED
        overrides = cls.normalize_timeout_overrides(config)
        if agent_type and agent_type in overrides:
            return float(overrides[agent_type])
        # 段入口经 _segment_or_empty 归一（code-review item 3a51f7bf0267）：
        # `or {}` 对真值非 dict（如 agents: [1]）不回落，下方 .get 抛
        # AttributeError，与 effective_stuck_threshold_seconds 同口径降级。
        agents = cls._segment_or_empty(config, "agents")
        rt = agents.get("run_timeout_seconds")
        # bool 排除（d5c6b590a12b）与非有限浮点回退（5b7fe2708100：YAML .inf
        # 字面量穿透 rt > 0 检查直通生效，墙钟永不触发，且经
        # supervision_config_floor 把 absolute_max 对齐成 inf 请求持久化自传播）
        # 均与 effective_stuck_threshold_seconds（d9e9a238696f）同键同口径。
        if (
            not isinstance(rt, (int, float))
            or isinstance(rt, bool)
            or (isinstance(rt, float) and not math.isfinite(rt))
            or rt <= 0
        ):
            if not _RUN_TIMEOUT_FALLBACK_WARNED:
                _logger.warning(
                    "agents.run_timeout_seconds 缺失、≤0 或非有限（.inf/.nan），"
                    "run 超时按 %ss 回退生效；建议显式配置合法的 run_timeout_seconds",
                    RUN_TIMEOUT_FALLBACK_SECONDS,
                )
                _RUN_TIMEOUT_FALLBACK_WARNED = True
            return float(RUN_TIMEOUT_FALLBACK_SECONDS)
        return float(rt)

    @classmethod
    def judge_timeout_seconds(cls, config: Dict[str, Any], default: float = 120) -> float:
        """liveness 活性判定 judge 子进程超时（spec per-agent-timeout-override 3.3）。

        读取 ``agents.timeout_overrides.supervision-judge``（缺省回退 120 秒常量）。
        该值不参与 absolute_max 派生。非法/缺失时回退 default。
        """
        overrides = cls.normalize_timeout_overrides(config)
        val = overrides.get("supervision-judge")
        if val is not None:
            return float(val)
        try:
            return float(default)
        except (TypeError, ValueError):
            return 120.0

    @classmethod
    def reset_stuck_threshold_state(cls) -> None:
        """重置弃用/兜底/回退/未知键告警的生命周期去重标记（供测试与 daemon 重启隔离）。

        正常 daemon 生命周期内只打一次；单测需多次验证「首次告警 / 二次静默」时显式重置。
        """
        global _DEPRECATED_STUCK_WARNED, _SUPERVISION_BOUNDS_WARNED, _SUPERVISION_LAST_ALIGNED
        global _SUPERVISION_RUNTIME_FLOOR_WARNED
        global _RUN_TIMEOUT_FALLBACK_WARNED, _STUCK_FALLBACK_WARNED
        _DEPRECATED_STUCK_WARNED = False
        _SUPERVISION_BOUNDS_WARNED = False
        _SUPERVISION_RUNTIME_FLOOR_WARNED = False
        _RUN_TIMEOUT_FALLBACK_WARNED = False
        _STUCK_FALLBACK_WARNED = False
        _SUPERVISION_LAST_ALIGNED = None
        _UNKNOWN_AGENT_MODEL_KEYS_WARNED.clear()
        _SEGMENT_DIRTY_WARNED.clear()
        _UNKNOWN_PROVIDER_REF_WARNED.clear()
        _UNRESOLVED_CHAIN_MODEL_WARNED.clear()
        _VALIDATE_SOFT_WARNED.clear()
        _TRANSIENT_BACKOFF_FALLBACK_WARNED.clear()
        _TIMEOUT_OVERRIDE_INVALID_WARNED.clear()
        _CONFIG_READER_WARNED.clear()
        # dsh 协议守卫告警标记（code-review item 1ff17e93f028）：同为「进程级
        # 去重、不重复刷屏」语义的类属性，纳入本助手隔离清单，使测试可重复
        # 验证「首次告警 / 二次静默」，与其他标记口径一致。
        cls._DSH_PROTOCOL_WARNED = False

    @classmethod
    def effective_auto_archive_threshold(cls, config: Dict[str, Any], default: int = 50) -> int:
        """archive.auto_threshold 的生效值（非负整数；0 = 禁用）。

        D5：非法值（非整数 / 负数 / bool）记日志并回落默认 50，且不阻塞加载。
        所有消费方（daemon 自动归档检查、dashboard 设置回显）MUST 调本助手读取
        生效值，而非直读原始配置——保证非法值不会流入归档判定。
        """
        archive = cls._segment_or_empty(config, "archive")
        at = archive.get("auto_threshold")
        if at is None:
            return default
        if isinstance(at, bool) or not isinstance(at, int) or at < 0:
            cls._warn_reader_once(
                "archive.auto_threshold",
                at,
                _logger.error,
                "archive.auto_threshold 非法（应为非负整数，0=禁用）：%r，回落默认 %s",
                at,
                default,
            )
            return default
        return at

    @classmethod
    def get_knowledge_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """读取 ``knowledge`` 段生效值（add-knowledge-atlas task 1.1）。

        返回 ``{"enabled": bool}``：
        - enabled 缺省 True（真相源默认开启）；
        - 显式 bool 原样生效；
        - 非法值（非 bool）记 ERROR 告警并回退 True（spec「非法值回退 true 并
          告警」，宽松校验不阻塞加载与热更新，对齐 archive.auto_threshold 哲学）。

        所有消费方（归档蒸馏派发、dashboard 页签禁用态回显）MUST 调本助手读取
        生效值，而非直读原始配置——保证非法值不会流入派发判定。
        """
        knowledge = cls._segment_or_empty(config, "knowledge")
        enabled = knowledge.get("enabled")
        if enabled is None:
            return {"enabled": True}
        if not isinstance(enabled, bool):
            cls._warn_reader_once(
                "knowledge.enabled",
                enabled,
                _logger.error,
                "knowledge.enabled 非法（应为布尔）：%r，回退缺省 true；"
                "其余配置照常生效",
                enabled,
            )
            return {"enabled": True}
        return {"enabled": enabled}

    @classmethod
    def get_impl_code_review_enabled(cls, config: Dict[str, Any]) -> bool:
        """读取 ``verify.impl_code_review`` 开关（impl-code-review-gate）。

        严格 bool 语义：仅当值为 Python ``True`` 时返回 True；值为 ``False``、
        缺失、类型非法（int/str/None 等）、或 ``verify`` 节缺失/非 dict 时一律
        返回 False（fail-open，脏值不中断派发）。

        该键支持用户级默认 + 项目级覆盖（合并由既有 ``resolve_config`` 深合并
        完成），本读取器只看合并后的结果。
        """
        # verify 段归一统一走 _segment_or_empty（code-review item fa432f912635）：
        # 段缺失静默、真值非 dict 记 ERROR（进程级一次性去重）并按空段降级，
        # 与本文件其他段读取器同口径；空段下键读取回退缺省，返回语义不变。
        verify = cls._segment_or_empty(config, "verify")
        val = verify.get("impl_code_review")
        return val is True  # 严格 bool：1/"yes" 等非 bool 一律不算

    @classmethod
    def _positive_int_reader(cls, config: Dict[str, Any], key: str, default: int) -> int:
        """verify 段正整数键读取助手（get_impl_code_review_* 正整数同族共用）。

        接受**正整数 int** 及整值浮点（``300.0`` 按整数接受，code-review item
        4a67fbffa917，与 _normalize_transient_seconds / _stale_selfheal_positive_int
        同口径）（``bool`` 是 int 子类，显式排除）；其余（键缺失 / verify 节缺失
        或非 dict / str / 非整值浮点 / ``<= 0``）一律回退缺省（fail-open，脏值
        不中断派发）。「配置了但非法」的值回退前打 WARNING 留痕（进程级一次性
        去重，同 _TRANSIENT_BACKOFF_FALLBACK_WARNED 范式；键缺失/None 静默回退，
        不打日志噪声），不再静默替换。

        注意：经本助手读取的键 MUST NOT 进入 ``resolve_config`` 的缺省填充列表
        ——缺省只由各读取器单点提供（与 ``get_impl_code_review_enabled`` 同款，
        避免 defaults 与读取器缺省双源漂移）。
        """
        # verify 段归一统一走 _segment_or_empty（code-review item fa432f912635，
        # 与 get_impl_code_review_enabled 同口径）；空段下键读取回退缺省。
        verify = cls._segment_or_empty(config, "verify")
        val = verify.get(key)
        if isinstance(val, bool):
            return default
        if isinstance(val, int) and val > 0:
            return val
        # 整值浮点按整数接受（code-review item 4a67fbffa917）：YAML ``300.0``
        # 解析为 float，旧实现判非法静默回缺省；.nan/.inf 的 is_integer() 恒
        # False，自然落入下方非法分支。
        if isinstance(val, float) and val.is_integer() and val > 0:
            return int(val)
        # 「配置了但非法」回退缺省前 WARNING 留痕（违背「回退必告警」哲学的
        # 旧静默路径，对照 _warn_backoff_schedule_fallback）；进程级去重防 30s
        # 热更新刷屏。
        if val is not None:
            dedup_key = ("verify." + key, repr(val))
            if dedup_key not in _VERIFY_POSITIVE_INT_WARNED:
                _VERIFY_POSITIVE_INT_WARNED.add(dedup_key)
                _logger.warning(
                    "verify.%s 非法值 %r（应为正整数），回退缺省 %s",
                    key,
                    val,
                    default,
                )
        return default

    @classmethod
    def _whitelist_str_reader(
        cls,
        config: Dict[str, Any],
        key: str,
        choices: tuple,
        default: str,
        log_invalid: bool = False,
    ) -> str:
        """verify 段白名单字符串键读取助手（get_impl_code_review_* 枚举同族共用）。

        键值恰为 ``choices`` 之一才生效；其余取值（缺失 / verify 节缺失或非
        dict / 大小写不匹配 / 非 str / 空串）一律回退缺省（fail-open，脏值不
        中断派发）。``log_invalid=True`` 时仅对「配置了但非法」的值记 DEBUG
        留痕（缺失/None 静默回退，不打日志噪声）。

        注意：经本助手读取的键 MUST NOT 进入 ``resolve_config`` 的缺省填充列表
        ——缺省只由各读取器单点提供（与 ``get_impl_code_review_enabled`` 同款）。
        """
        # verify 段归一统一走 _segment_or_empty（code-review item fa432f912635，
        # 与 get_impl_code_review_enabled 同口径）；空段下键读取回退缺省。
        verify = cls._segment_or_empty(config, "verify")
        val = verify.get(key)
        if val in choices:
            return val
        if log_invalid and val is not None:
            _logger.debug(
                "verify.%s 非法值 %r（合法：%s），回退缺省 %s",
                key,
                val,
                "/".join(choices),
                default,
            )
        return default

    @classmethod
    def get_impl_code_review_timeout_sec(cls, config: Dict[str, Any]) -> int:
        """读取 ``verify.impl_code_review_timeout_sec``：ocr LLM 单请求超时秒（写入 run 级 ocr provider 配置），缺省 600，仅正整数 int（add-impl-code-review-tuning）。"""
        return cls._positive_int_reader(config, "impl_code_review_timeout_sec", 600)

    @classmethod
    def get_impl_code_review_concurrency(cls, config: Dict[str, Any]) -> int:
        """读取 ``verify.impl_code_review_concurrency``：ocr 并发子任务上限（车道命令 ``--concurrency <n>``），缺省 4（add-impl-ocr-parallel-lane D7 由 2 上调），仅正整数 int（add-impl-code-review-tuning）。"""
        return cls._positive_int_reader(config, "impl_code_review_concurrency", 4)

    @classmethod
    def get_repo_code_review_concurrency(cls, config: Dict[str, Any]) -> int:
        """读取 ``verify.repo_code_review_concurrency``：全仓审查并行审查度（提示词侧并行扇出上限与 ``ocr scan --concurrency <n>`` 一键两用），缺省 4，仅正整数 int（add-code-review-concurrency-and-429-resilience）。"""
        return cls._positive_int_reader(config, "repo_code_review_concurrency", 4)

    @classmethod
    def get_impl_code_review_effort(cls, config: Dict[str, Any]) -> str:
        """读取 ``verify.impl_code_review_effort``：ocr 审查力度预设（low/medium/high，提示词命令示例 ``--effort <v>``），缺省 "low"，仅白名单三值（add-impl-code-review-tuning）。"""
        return cls._whitelist_str_reader(
            config, "impl_code_review_effort", ("low", "medium", "high"), "low"
        )

    @classmethod
    def get_impl_code_review_mode(cls, config: Dict[str, Any]) -> str:
        """读取 ``verify.impl_code_review_mode``：join 裁决双档模式（gate/advisory），缺省 "gate"，仅白名单两值、非法值记 DEBUG（add-impl-ocr-parallel-lane）。"""
        return cls._whitelist_str_reader(
            config, "impl_code_review_mode", ("gate", "advisory"), "gate", log_invalid=True
        )

    @classmethod
    def get_impl_code_review_lane_timeout_sec(cls, config: Dict[str, Any]) -> int:
        """读取 ``verify.impl_code_review_lane_timeout_sec``：ocr 车道级硬超时秒（run 级整体墙钟上限；与单请求 ``impl_code_review_timeout_sec`` 按键分离 MUST NOT 共用，design D2），缺省 2400，仅正整数 int（add-impl-ocr-parallel-lane）。"""
        return cls._positive_int_reader(config, "impl_code_review_lane_timeout_sec", 2400)

    @classmethod
    def get_context_cost_per_turn_threshold(
        cls, config: Dict[str, Any], default: int = 200000
    ) -> int:
        """读取 ``verify.context_cost_per_turn_threshold``：上下文经济性告警阈值（0=关闭），缺省 200000，仅非负整数 int（fix-agent-lane-efficiency D3）。

        单点读取器（code-review item 431081458861）：dashboard 缺省回显视图与
        agent_runner 运行时告警双侧均经本读取器取值——该键缺省曾以手写字面量
        双处镜像（config_admin._default_echo_view 与 runner 内联 `get(..., 200000)`），
        构成会实际漂移的双源。非法值回落缺省（bool 是 int 子类显式排除），与
        effective_auto_archive_threshold 同口径；WARNING 经 _VERIFY_POSITIVE_INT_WARNED
        同款进程级去重（运行时逐 run 调用，防同一坏值刷屏）。
        """
        verify = cls._segment_or_empty(config, "verify")
        val = verify.get("context_cost_per_turn_threshold")
        if val is None:
            return default
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            dedup_key = ("verify.context_cost_per_turn_threshold", repr(val))
            if dedup_key not in _VERIFY_POSITIVE_INT_WARNED:
                _VERIFY_POSITIVE_INT_WARNED.add(dedup_key)
                _logger.warning(
                    "verify.context_cost_per_turn_threshold 非法值 %r（应为非负整数，"
                    "0=关闭），回退缺省 %s",
                    val,
                    default,
                )
            return default
        return val

    @classmethod
    def get_subagent_model_override(cls, config: Dict[str, Any]) -> str:
        """读取 ``agents.subagent_model_override``（fix-agent-lane-efficiency D1）。

        子代理模型覆盖键：非空时，隔离 settings.json 的 env 子代理 tier 映射（
        ``CLAUDE_CODE_SUBAGENT_MODEL`` / ``ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL``）
        使用该值而非 provider 自身 model。空串（缺省）= 使用 provider model。

        命名冲突处置记录（2026-09-20，tasks 1.6 决策登记）：``agents.subagent_model``
        （2026-09-02-add-agent-llm-isolation 遗留）为无读点的死键——本实现选择
        **保留新键 ``agents.subagent_model_override``** 为唯一活键；``agents.subagent_model``
        保持死键（不读、不写），语义边界写入实现记录与 docs/help/09-config.md。
        MUST NOT 从本读取器回退读取死键——否则两个键同时可被用户读作「子代理模型」
        即违反 D1「不留下两个活配置键」约束。
        """
        # 段入口经 _segment_or_empty 归一（code-review item 7035b5e127eb）：
        # 整段非 dict（如 agents: [1]）记 ERROR 并按空段降级，而非静默返回空串。
        agents = cls._segment_or_empty(config, "agents")
        val = agents.get("subagent_model_override")
        if isinstance(val, str):
            return val.strip()
        return ""

    @classmethod
    def get(cls, config: Dict[str, Any], dotted_key: str, default=None):
        """
        Get a nested config value by dotted key.
        E.g., config_get(config, "agents.max_turns", 400)
        """
        keys = dotted_key.split(".")
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    # ── 数值型配置统一读取守卫（code-review item 2513848b87c2）──────────
    # fenixd.py 曾四处复制「读原始值 → or 缺省 → 非有限浮点预检 → int/float()
    # → except (TypeError, ValueError, OverflowError) 回退缺省并 ERROR 留痕」
    # 守卫（admin.workers 启动读取、agents.verify_redo_budget、admin.
    # interval_minutes 主循环读取、_maybe_reload_config 的 workers 比对），
    # 同一模式先后修了五轮评审缺陷（8f6bf8446388/625a1341f928/b80e1bf206f9/
    # fc1f18a4eb95/0c251f8d00a5），复制式守卫再遇新非法值形态时漏改一处即
    # 复发。收口为本助手：内部完成 or 缺省、非有限浮点预检（转换前后各一道，
    # int/float 两种 conv 都覆盖）、转换与统一捕获集回退；各处回退动作差异
    # （回缺省 / 返回哨兵跳过比对）由 fallback 表达，留痕文案与去重策略由
    # on_invalid 回调承接（本助手自身不告警、不去重，保持各处既有行为）。
    @classmethod
    def get_finite_number(
        cls,
        config: Dict[str, Any],
        dotted_key: str,
        *,
        conv,
        get_default=None,
        or_default=None,
        fallback=None,
        on_invalid=None,
    ):
        """按点分键读取数值型配置并归一，非法回退 ``fallback``。

        语义（与被收口的四处守卫逐格等价）：
        - ``cls.get(config, dotted_key, get_default)`` 取原始值（缺键 / 中途
          None → ``get_default``）；
        - ``or_default`` 非 None 时做既有「``raw or X``」假值映射（0/""/False
          等 → X，如 admin.workers 的空值映射 0 = 关闭后台池）；None 表示不
          做 or 映射、原样转换；
        - 非有限浮点（.inf/.nan，YAML 合法标量）按非法值处理：int(.inf) 抛
          OverflowError、int(.nan) 抛 ValueError、float() 不抛但令比较恒
          False——故转换前后各一道 isfinite 预检；
        - ``conv`` 转换，``except (TypeError, ValueError, OverflowError)`` 时
          调 ``on_invalid(raw, reason)`` 留痕（reason："convert" 转换失败 /
          "non-finite" 非有限值）并返回 ``fallback``；``on_invalid`` 为 None
          时静默回退。

        与 get_admin_config._num 的口径差异（有意保留，勿「统一」）：本助手
        **不排除 bool**——bool 是 int 子类，四处被收口守卫的既有行为矩阵中
        ``int(True)=1`` / ``float(True)=1.0`` 直接生效；收口以行为逐格等价为
        先决条件，改 bool 去向属语义变更，须独立评审项决策。
        """
        raw = cls.get(config, dotted_key, get_default)

        def _fallback(reason: str):
            if on_invalid is not None:
                on_invalid(raw, reason)
            return fallback

        try:
            value = (raw or or_default) if or_default is not None else raw
            if isinstance(value, float) and not math.isfinite(value):
                return _fallback("non-finite")
            result = conv(value)
            if isinstance(result, float) and not math.isfinite(result):
                return _fallback("non-finite")
            return result
        except (TypeError, ValueError, OverflowError):
            return _fallback("convert")
