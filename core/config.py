"""
config.py — Configuration loader for fenixd.

Reads and validates config.yaml, providing typed access to all settings.
"""

import copy
import logging
import os
import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
# D5：absolute_max 联动兜底续期上限（秒）。absolute_max 低于
# run_timeout_seconds + 该值时按 run_timeout_seconds + 该值兜底生效。
SUPERVISION_EXTENSION_SECONDS = 7200

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

# ── improve-hot-reload-robustness D3：未知 agent 类型键降级告警去重 ──
# 同一未知键每进程生命周期只报一次（30s 热重载重试风暴下，不去重则告警与
# ERROR 同步刷屏）。keys 以键名字符串为准，不随进程内白名单变化失效。
_UNKNOWN_AGENT_MODEL_KEYS_WARNED = set()


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
    # 未纳入时无法分配专属模型，只能随网关当前 provider 漂移，且网关欠费时秒挂）
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
    ]

    # ── run_timeout 按 agent_type 覆盖（per-agent-timeout-override）──────
    # agents.timeout_overrides.<agent_type> 覆盖全局 run_timeout_seconds。
    # 白名单键 = 全部七类 agent run（含 fast-track/repair，design D3 的
    # KNOWN_AGENT_TYPES 仅指 agents.models 角色集）+ supervision-judge。
    TIMEOUT_OVERRIDE_AGENT_TYPES = frozenset(KNOWN_AGENT_TYPES) | {"fast-track", "repair"}
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

    # ── 瞬断治理配置（fix-provider-transient-backoff D6 / transient-controls-ui）──
    # 五键缺省值（design D6 表）。消费方（runner/provider_circuit/dispatch）经
    # _get_config 读取，非法值由本类防御式规范化回退缺省。
    TRANSIENT_BACKOFF_SCHEDULE_DEFAULT = "30,60,120"  # 原地退避秒序列（长度=原地重试上限）
    TRANSIENT_REDISPATCH_DELAY_DEFAULT = 600  # dispatch 排程等待秒
    TRANSIENT_BREAK_THRESHOLD_DEFAULT = 3  # 熔断窗口内同指纹次数
    TRANSIENT_BREAK_WINDOW_DEFAULT = 600  # 熔断窗口秒
    TRANSIENT_BREAK_COOLDOWN_DEFAULT = 600  # 熔断冷却秒

    @classmethod
    def normalize_transient_backoff_schedule(cls, raw) -> str:
        """规范 `agents.transient_backoff_schedule` 为合法逗号秒序列字符串。

        非法（非字符串 / 非逗号分隔正整数序列）回退缺省 ``"30,60,120"``（防御式
        先例同 ``_shutdown_drain_seconds``）。空串视为关闭原地退避（设计 Migration
        Plan：`transient_backoff_schedule: ""` 关闭原地退避），保持原样返回。
        """
        if raw is None or not isinstance(raw, str):
            return cls.TRANSIENT_BACKOFF_SCHEDULE_DEFAULT
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
                return cls.TRANSIENT_BACKOFF_SCHEDULE_DEFAULT
            if val <= 0:
                return cls.TRANSIENT_BACKOFF_SCHEDULE_DEFAULT
            parts.append(str(val))
        if not parts:
            return cls.TRANSIENT_BACKOFF_SCHEDULE_DEFAULT
        return ",".join(parts)

    @classmethod
    def _normalize_transient_seconds(cls, config, key: str, default: int) -> int:
        """读取并规范化某瞬断治理秒/次数字段（非负整数，非法回退缺省）。"""
        try:
            val = cls.get(config, key, None)
        except Exception:
            return default
        if val is None:
            return default
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return default
        if val < 0:
            return default
        return int(val)

    @classmethod
    def get_transient_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """返回规范化后的瞬断治理配置（五键 + 缺省填充，供 Settings UI / 消费方）。

        语义与 design D6 表一致；非法值（负数/非数字/坏序列）回退缺省，保证
        展示与生效值不脱节。``transient_backoff_schedule`` 保留字符串形态
        （逗号秒序列），其余四键为 int。
        """
        agents = config.get("agents") if isinstance(config, dict) else None
        agents = agents if isinstance(agents, dict) else {}
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
        # 注意：resolve_config 内部（config.py:123）已对 fresh 完成同一份 _validate，
        # 此处不重复校验（improve-hot-reload-robustness D9 死代码清理）。
        config.clear()
        config.update(fresh)

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
        except (yaml.YAMLError, OSError) as e:
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

        cls._validate(config)
        return config

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
        schedule = config.get("schedule") or {}
        poll = schedule.get("poll_interval_minutes", 30)
        if not isinstance(poll, (int, float)) or poll <= 0:
            raise ValueError(f"schedule.poll_interval_minutes must be positive: {poll}")

        # Validate agents — max_concurrent / max_retries / max_turns 均为可选，
        # 缺失时由各消费方使用默认值；仅当显式提供时才校验必须为正整数。
        agents = config.get("agents") or {}
        for field in ["max_concurrent", "max_retries", "max_turns"]:
            if field in agents:
                val = agents[field]
                if not isinstance(val, int) or val <= 0:
                    raise ValueError(f"agents.{field} must be a positive integer: {val}")

        # fix-provider-transient-backoff（D6）：瞬断治理五键防御式校验。非法值不
        # 拒绝加载——由 get_transient_config / 消费方回退缺省（Migration Plan 回滚
        # 语义 = 配置键置空），仅对「值类型极端非法以致无法安全解析」打 ERROR。
        # 写法对齐 loads 阶段只拦截明显损坏的类型（字符串数字歧义由规范化兜底）。
        for field in (
            "transient_redispatch_delay_seconds",
            "transient_break_threshold",
            "transient_break_window_seconds",
            "transient_break_cooldown_seconds",
        ):
            if field in agents and agents[field] is not None:
                val = agents[field]
                if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0:
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

        # Validate project type — 仅当 project 存在且（严格路径 或 显式提供 type）时校验
        project = config.get("project")
        if isinstance(project, dict) and (require_project or "type" in project):
            ptype = project.get("type", "")
            if ptype not in cls.VALID_PROJECT_TYPES:
                raise ValueError(f"project.type must be one of {cls.VALID_PROJECT_TYPES}: {ptype}")

        # Validate llm.providers (optional — absence means empty registry)
        llm = config.get("llm") or {}
        if llm:
            cls._validate_llm(llm)

        # Validate agents.models (optional — absence means no assignments)。
        # models 显式提供（非 None）即进校验：非 dict 段由 _validate_agent_models
        # 内部按"忽略该段 + 告警"降级（improve-hot-reload-robustness D2）。
        agents = config.get("agents") or {}
        if "models" in agents and agents["models"] is not None:
            cls._validate_agent_models(agents["models"], llm)

        # Validate gates.approve_mode (optional — defaults to manual)
        gates = config.get("gates") or {}
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

        # D5：timeout_supervision.absolute_max_seconds 联动护栏，启动/热更新时校验；
        # enabled=true 且配置值低于 run_timeout + 续期上限时打 ERROR 并按兜底值生效。
        cls.effective_supervision_absolute_max_seconds(config)

        # Validate admin.* (optional — 缺省使用默认值，见 get_admin_config)
        admin = config.get("admin") or {}
        if "enabled" in admin and not isinstance(admin["enabled"], bool):
            raise ValueError(f"admin.enabled must be a boolean: {admin['enabled']}")
        for field in (
            "interval_minutes",
            "escalation_cooldown_minutes",
            "orphaned_state_threshold_minutes",
        ):
            if field in admin and admin[field] is not None:
                val = admin[field]
                if not isinstance(val, (int, float)) or val <= 0:
                    raise ValueError(f"admin.{field} must be positive: {val}")
        # stuck-signal-hygiene D4：stuck 处置后静默期——非负护栏（0 = 不静默），
        # 与 escalation_cooldown_minutes 同型（负数/非法类型拒绝）。
        if "stuck_silence_minutes" in admin and admin["stuck_silence_minutes"] is not None:
            _ssm = admin["stuck_silence_minutes"]
            if not isinstance(_ssm, (int, float)) or isinstance(_ssm, bool) or _ssm < 0:
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
            if not isinstance(drain, (int, float)) or isinstance(drain, bool) or drain < 0:
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
        sr = admin.get("self_review") if isinstance(admin, dict) else None
        if sr is not None:
            if not isinstance(sr, dict):
                raise ValueError("admin.self_review must be an object")
            for field in ("enabled", "read_todo"):
                if field in sr and sr[field] is not None and not isinstance(sr[field], bool):
                    raise ValueError(f"admin.self_review.{field} must be a boolean: {sr[field]}")
            if "run_at" in sr and sr["run_at"] is not None:
                cls._validated_run_at(sr["run_at"])  # 非法值仅 ERROR+回退，不抛错

        # add-spec-archive D5：archive.auto_threshold —— 自动归档阈值。
        # 非负整数（0 = 禁用）；非法值记日志并按默认 50 兜底（宽松校验，
        # 不因坏一个值阻断整个配置热更新/加载）。用户级与项目级均可设置，
        # 项目级经深合并优先。
        archive = config.get("archive") or {}
        if "auto_threshold" in archive and archive["auto_threshold"] is not None:
            at = archive["auto_threshold"]
            if not isinstance(at, int) or isinstance(at, bool) or at < 0:
                _logger.error(
                    "archive.auto_threshold 非法（应为非负整数，0=禁用）：%r，" "回落默认 50",
                    at,
                )

        # add-framework-self-evolution：self_evolution 段护栏（软校验）。
        # 与 stale_code_selfheal 的处理方式一致：节/键存在但类型非法时不进入硬
        # 失败路径——只记 ERROR，生效值由 get_self_evolution_config 按 1.1 的
        # 回退规则兜底。保证 30s 热更新路径（resolve_config_into）不会因该节
        # 被中断（用户级全局键，项目级写入由 dashboard 前置校验拒绝）。
        se = config.get("self_evolution")
        if se is not None and not isinstance(se, dict):
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
        - prices 提供时必须为列表；每行 model 非空字符串、4 项单价为非负数值
          （bool 除外）、行 model 在同一卡片内不重复；
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
                    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                        errs.append(f"{_prefix}.{_f} 必须为非负数值: {v!r}")
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
                        raise ValueError(
                            f"llm.providers[{idx}].env keys/values must be strings: {k!r}={v!r}"
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
            if unknown:
                _logger.error(
                    "agents.models.%s.provider 引用了不存在的 provider（已跳过，不阻塞加载）: %s",
                    agent_type,
                    ", ".join(unknown),
                )
            # design D1/D2：逐元素可解析性检查（替换原"角色级 model 必须非空"）。
            # 元素自带 / 角色级 / provider 条目 model 三者皆空 → ERROR 指明元素下标（不阻塞）。
            for idx, (name, element_model) in enumerate(chain):
                if name not in by_name:
                    continue  # 未知 provider 已打过 ERROR，跳过其模型解析
                resolved = cls._resolve_element_model(element_model, role_model, by_name[name])
                if not resolved:
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
        agents = config.get("agents") or {}
        models = agents.get("models") or {}
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

        llm = config.get("llm") or {}
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
        gates = config.get("gates") or {}
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
        gates = config.get("gates") or {}
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
        gates = config.get("gates") or {}
        mode = gates.get("spec_review_mode")
        if mode not in cls.VALID_SPEC_REVIEW_MODES:
            return "auto"
        return mode

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
        """
        admin = config.get("admin") or {}
        # D2：stuck 阈值单源派生，旧键不再作为生效输入（告警在助手内节流）。
        stuck_seconds = cls.effective_stuck_threshold_seconds(config)
        breaker = cls.get(config, "admin.merge_breaker_threshold", None)
        if breaker is None:
            breaker = cls.get(config, "agents.merge_breaker_threshold", 2)
        brm = admin.get("bug_repair_mode", "inplace")
        if brm not in VALID_BUG_REPAIR_MODES:
            # 校验层已拦截非法值；运行期兜底（直读脏配置的旁路调用）回退缺省
            brm = "inplace"
        return {
            "enabled": bool(admin.get("enabled", True)),
            "interval_minutes": float(admin.get("interval_minutes", 5)),
            "agent_model": admin.get("agent_model") or None,
            "escalation_cooldown_minutes": float(admin.get("escalation_cooldown_minutes", 60)),
            "stuck_threshold_minutes": stuck_seconds / 60.0,
            # add-control-plane-silent-failure-guards D5：孤儿状态（状态无驱动）
            # 探测阈值——缺省 15 分钟（= 3 个 interval_minutes(5) 巡检周期，
            # 与巡检周期整数倍对齐避免漏检），远短于 stuck（run_timeout+600s，
            # 当前约 160 分钟），使「状态无驱动」分钟级可发现。与 stuck 阈值
            # 互不影响（独立键，stuck 仍由 run_timeout 单源派生）。
            "orphaned_state_threshold_minutes": float(
                admin.get("orphaned_state_threshold_minutes", 15)
            ),
            "merge_breaker_threshold": int(breaker),
            # interrupt-recovery-preserve D1：规划性重启排水窗口（秒）；0 = 现行
            # 快速停机。缺省 1800（半小时量级，用户已确认方向）。
            "shutdown_drain_seconds": max(
                0, int(admin.get("shutdown_drain_seconds", 1800) or 1800)
            ),
            # add-bug-repair-mode-config：bug-found 修复方式（未配置缺省 inplace）
            "bug_repair_mode": brm,
            # stuck-signal-hygiene D3/D4：stuck 处置后静默期（分钟）——
            # (spec, signal_type) 最近一次 result∈{resolved, partially-resolved}
            # 处置后，窗口内不产生 stuck 信号（非负护栏，0=不静默）。
            "stuck_silence_minutes": float(admin.get("stuck_silence_minutes", 120)),
            # add-daily-self-review：自省配置段（enabled 缺省 false）
            "self_review": cls.get_self_review_config(config),
            # evo-run-failure-classification-circuitbreaker D5：infra 熔断配置
            # 段（阈值/冷却分钟，缺省 3/30）
            "run_infra_breaker": cls.get_run_infra_breaker_config(admin),
        }

    # ── 陈旧自愈配置（add-stale-code-selfheal D5）──────────────────────
    # stale_code_selfheal 节两键缺省：enabled 默认开启（本项目陈旧是常态，默认
    # 关闭等于把问题留给用户发现；风险由 supervisor 熔断兜底、由开关提供退出
    # 通道）；idle_confirm_seconds 取 120s 作为连续空闲确认窗（触发实现在
    # fenixd.py 主循环 _maybe_stale_selfheal_tick），该取值沿自 daemon 内建化
    # 之前的实践，已验证足以防零活跃窗口竞态。
    STALE_CODE_SELFHEAL_ENABLED_DEFAULT = True
    STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT = 120
    STALE_CODE_SELFHEAL_MAX_SECONDS = 86400  # 仅建议上界（警告不拒绝），保持读取宽容语义

    @classmethod
    def get_stale_code_selfheal_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``stale_code_selfheal`` 段，缺失/非法值回退缺省。

        - enabled: 布尔，缺省 True（非布尔回退缺省——布尔缺省语义下非法即用缺省）
        - idle_confirm_seconds: 正整数秒，缺省 120（非整数/负数/0 回退缺省；
          bool 是 int 子类须显式排除）

        节缺失、键缺失或值非法时不抛异常、不使 daemon 启动失败；读取走既有
        config 对象，30s 配置热更新自然生效（下一检测周期起采用新值）。
        """
        section = config.get("stale_code_selfheal")
        if not isinstance(section, dict):
            section = {}
        enabled = section.get("enabled", cls.STALE_CODE_SELFHEAL_ENABLED_DEFAULT)
        if not isinstance(enabled, bool):
            enabled = cls.STALE_CODE_SELFHEAL_ENABLED_DEFAULT
        seconds = section.get("idle_confirm_seconds", cls.STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
            seconds = cls.STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT
        seconds = int(seconds)
        if seconds > cls.STALE_CODE_SELFHEAL_MAX_SECONDS:
            _logger.warning(
                "stale_code_selfheal.idle_confirm_seconds 过大 (%ss，建议 ≤ %s)："
                "自愈将在长时间空闲后才触发（不拒绝，按配置生效）",
                seconds,
                cls.STALE_CODE_SELFHEAL_MAX_SECONDS,
            )
        return {"enabled": enabled, "idle_confirm_seconds": seconds}

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
        section = config.get("self_evolution")
        if not isinstance(section, dict):
            section = {}
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

        run_at 经 ``_validated_run_at`` 兜底：非法值（类型错误/格式错误/越界
        时分）打 ERROR 并按 "02:00" 回退生效，保证调度判定永远拿到合法 HH:MM。
        """
        admin = config.get("admin") or {}
        sr = admin.get("self_review") if isinstance(admin, dict) else None
        if not isinstance(sr, dict):
            sr = {}
        return {
            "enabled": bool(sr.get("enabled", False)),
            "run_at": cls._validated_run_at(sr.get("run_at")),
            "read_todo": bool(sr.get("read_todo", False)),
        }

    @classmethod
    def get_run_infra_breaker_config(cls, admin: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Return the ``admin.run_infra_breaker.*`` 段，缺失项填默认值（D5）。

        默认值：
        - threshold: 3（连续 infra 失败触发熔断）
        - cooldown_minutes: 30（熔断冷却时长，分钟）

        非法值（非正数/类型错误）回退缺省（config D5 读取宽容语义）。
        """
        if not isinstance(admin, dict):
            admin = {}
        ib = admin.get("run_infra_breaker")
        if not isinstance(ib, dict):
            ib = {}
        threshold = ib.get("threshold", 3)
        cooldown = ib.get("cooldown_minutes", 30)
        # 校验：必须为正数
        if not isinstance(threshold, (int, float)) or threshold <= 0:
            threshold = 3
        if not isinstance(cooldown, (int, float)) or cooldown <= 0:
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
        _logger.error(
            "admin.self_review.run_at 非法（应为 HH:MM，如 22:00）：%r，" "回退缺省 %s",
            raw,
            SELF_REVIEW_DEFAULT_RUN_AT,
        )
        return SELF_REVIEW_DEFAULT_RUN_AT

    @classmethod
    def effective_stuck_threshold_seconds(cls, config: Dict[str, Any]) -> float:
        """stuck 判定阈值单源派生自 run 超时（design D1/D2/D4）。

        effective_threshold = run_timeout_seconds + STUCK_GRACE_SECONDS（600s）。
        run_timeout_seconds 缺失或非正数时回退 4200s 并打 WARNING（D4：
        防有人把超时关掉导致恢复永不触发）。旧键
        schedule/admin.stuck_threshold_minutes 不论是否配置都不影响结果（D3 告警）。

        pm_engine.check_blockers 与 admin_monitor 的 stuck 检测 MUST 调用本助手，
        不再各自读取旧键。
        """
        cls._maybe_warn_deprecated_stuck_keys(config)
        agents = config.get("agents") or {}
        rt = agents.get("run_timeout_seconds")
        if not isinstance(rt, (int, float)) or rt <= 0:
            _logger.warning(
                "agents.run_timeout_seconds 缺失或 ≤0，stuck 阈值按 %ss 回退生效"
                "（=9000 默认超时 + %ss 宽限）；建议显式配置 run_timeout_seconds",
                STUCK_FALLBACK_SECONDS,
                STUCK_GRACE_SECONDS,
            )
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
        schedule = config.get("schedule") or {}
        admin = config.get("admin") or {}
        if "stuck_threshold_minutes" in schedule or "stuck_threshold_minutes" in admin:
            _logger.warning(
                "检测到已弃用的 stuck_threshold_minutes 配置键（schedule/admin）：stuck 阈值"
                "已改为由 agents.run_timeout_seconds 单源派生（run_timeout + %ss 宽限），"
                "旧键值不再生效",
                STUCK_GRACE_SECONDS,
            )
            _DEPRECATED_STUCK_WARNED = True

    @classmethod
    def effective_supervision_absolute_max_seconds(cls, config: Dict[str, Any]) -> Optional[float]:
        """timeout_supervision.absolute_max_seconds 的生效值（含联动兜底，design D5）。

        enabled=true 时：配置值 MUST ≥ run_timeout_seconds + SUPERVISION_EXTENSION_SECONDS，
        否则打 ERROR 并按 run_timeout_seconds + 该续期上限兜底返回。
        enabled=false 或段缺失：返回 None（不启用 supervision，不校验）。
        absolute_max 未配置：返回 None（由消费方按各自默认处理，本护栏只约束显式值）。

        agent_runner 的 supervision 激活路径 MUST 调本助手读取兜底值，而非直读原始配置。
        """
        sup = config.get("timeout_supervision") or {}
        if not sup.get("enabled", False):
            return None
        configured = sup.get("absolute_max_seconds")
        if not isinstance(configured, (int, float)):
            return None
        agents = config.get("agents") or {}
        rt = agents.get("run_timeout_seconds")
        if not isinstance(rt, (int, float)) or rt <= 0:
            rt = RUN_TIMEOUT_FALLBACK_SECONDS
        required = float(rt) + SUPERVISION_EXTENSION_SECONDS
        if float(configured) < required:
            global _SUPERVISION_BOUNDS_WARNED
            if not _SUPERVISION_BOUNDS_WARNED:
                _logger.error(
                    "timeout_supervision.absolute_max_seconds=%s 低于 run_timeout_seconds(%s)"
                    "+ 续期上限(%s)=%s，按 %s 兜底生效（supervision 不会先于墙钟终止运行）",
                    configured,
                    rt,
                    SUPERVISION_EXTENSION_SECONDS,
                    required,
                    required,
                )
                _SUPERVISION_BOUNDS_WARNED = True
            return required
        return float(configured)

    @classmethod
    def normalize_timeout_overrides(cls, config: Dict[str, Any]) -> Dict[str, int]:
        """校验并规范化 ``agents.timeout_overrides``（逐键：非法键值忽略 + ERROR）。

        per-agent-timeout-override（design D3 / spec 3.1）：
        - 键 ∈ TIMEOUT_OVERRIDE_KEYS（全部七类 agent run + supervision-judge）；
        - agent run 键值须为 ≥300 整数（低于下限会截断正常长 run）；
          supervision-judge 键值须为 ≥1 整数（内部轻量判定，不受 300 下限约束）；
        - 非法键值**整条忽略**（该键回退全局默认）并打 ERROR，其余合法键正常生效；
          进程不得崩溃（调用方容错）。

        Returns: 规范化后的覆盖表 {agent_type: seconds}。缺省/非 dict/空 → {}。
        """
        agents = config.get("agents") or {}
        raw = agents.get("timeout_overrides")
        if not isinstance(raw, dict) or not raw:
            return {}
        out: Dict[str, int] = {}
        for key, val in raw.items():
            if key not in cls.TIMEOUT_OVERRIDE_KEYS:
                _logger.error(
                    "agents.timeout_overrides 键 %r 非法（应为 %s 之一），"
                    "该键被忽略并回退全局默认",
                    key,
                    sorted(cls.TIMEOUT_OVERRIDE_KEYS),
                )
                continue
            if isinstance(val, bool) or not isinstance(val, int):
                _logger.error(
                    "agents.timeout_overrides.%s=%r 非法（应为整数秒），"
                    "该键被忽略并回退全局默认",
                    key,
                    val,
                )
                continue
            min_allowed = 1 if key == "supervision-judge" else cls.TIMEOUT_OVERRIDE_MIN_SECONDS
            if val < min_allowed:
                _logger.error(
                    "agents.timeout_overrides.%s=%s 低于下限 %ss，" "该键被忽略并回退全局默认",
                    key,
                    val,
                    min_allowed,
                )
                continue
            out[key] = val
        return out

    @classmethod
    def effective_run_timeout_seconds(
        cls, config: Dict[str, Any], agent_type: str | None = None
    ) -> float:
        """agent run 的生效超时（per-agent-timeout-override spec 3.1/3.2）。

        解析顺序 MUST：``agents.timeout_overrides.<agent_type>`` 存在且合法时取覆盖值，
        否则回退 ``agents.run_timeout_seconds`` 全局默认；全局缺失/非正数回退
        RUN_TIMEOUT_FALLBACK_SECONDS（9000）。

        覆盖 MUST 适用于全部七类 agent run：implementer、verifier、planner-plan、
        planner-judge、fast-track、repair、administrator（后两者经 _execute_agent
        与 _run_claude 统一路径生效）。

        注意：supervision-judge 键不在此处生效（那是 liveness judge 子进程超时，
        经 ``judge_timeout_seconds`` 读取，不参与 absolute_max 派生）。
        """
        overrides = cls.normalize_timeout_overrides(config)
        if agent_type and agent_type in overrides:
            return float(overrides[agent_type])
        agents = config.get("agents") or {}
        rt = agents.get("run_timeout_seconds")
        if isinstance(rt, (int, float)) and not isinstance(rt, bool) and rt > 0:
            return float(rt)
        return float(RUN_TIMEOUT_FALLBACK_SECONDS)

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
        """重置弃用/兜底/未知键告警的生命周期去重标记（供测试与 daemon 重启隔离）。

        正常 daemon 生命周期内只打一次；单测需多次验证「首次告警 / 二次静默」时显式重置。
        """
        global _DEPRECATED_STUCK_WARNED, _SUPERVISION_BOUNDS_WARNED
        _DEPRECATED_STUCK_WARNED = False
        _SUPERVISION_BOUNDS_WARNED = False
        _UNKNOWN_AGENT_MODEL_KEYS_WARNED.clear()

    @classmethod
    def effective_auto_archive_threshold(cls, config: Dict[str, Any], default: int = 50) -> int:
        """archive.auto_threshold 的生效值（非负整数；0 = 禁用）。

        D5：非法值（非整数 / 负数 / bool）记日志并回落默认 50，且不阻塞加载。
        所有消费方（daemon 自动归档检查、dashboard 设置回显）MUST 调本助手读取
        生效值，而非直读原始配置——保证非法值不会流入归档判定。
        """
        archive = config.get("archive") or {}
        at = archive.get("auto_threshold")
        if at is None:
            return default
        if isinstance(at, bool) or not isinstance(at, int) or at < 0:
            _logger.error(
                "archive.auto_threshold 非法（应为非负整数，0=禁用）：%r，回落默认 %s",
                at,
                default,
            )
            return default
        return at

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
