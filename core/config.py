"""
config.py — Configuration loader for fenixd.

Reads and validates config.yaml, providing typed access to all settings.
"""

import copy
import logging
import yaml
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 用户级配置目录：与项目级同名 `.fenix/config.yaml`，作用域由所在目录决定
USER_CONFIG_DIR = Path.home() / ".fenix"

_logger = logging.getLogger("fenixd.config")

# ── fix-stuck-threshold-unify：stuck 阈值单源派生 ──────────────────
# D1：派生宽限常量（秒），非配置项。阈值 = run_timeout_seconds + 该宽限，
# 保证 runner 自身超时终止与 auto-recovery 恢复判定之间留确定性时序余量。
STUCK_GRACE_SECONDS = 600
# D4：run_timeout_seconds 缺失或 ≤0 时的派生回退基准（3600+600=4200）。
RUN_TIMEOUT_FALLBACK_SECONDS = 3600
STUCK_FALLBACK_SECONDS = RUN_TIMEOUT_FALLBACK_SECONDS + STUCK_GRACE_SECONDS
# D5：absolute_max 联动兜底续期上限（秒）。absolute_max 低于
# run_timeout_seconds + 该值时按 run_timeout_seconds + 该值兜底生效。
SUPERVISION_EXTENSION_SECONDS = 7200

# D3：旧键弃用告警 / D5：absolute_max 兜底 ERROR 的生命周期去重标记，
# 避免 30 分钟扫描热更新时反复刷屏。
_DEPRECATED_STUCK_WARNED = False
_SUPERVISION_BOUNDS_WARNED = False


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

    # Known agent types for model assignment
    KNOWN_AGENT_TYPES = ["implementer", "planner-plan", "planner-judge", "verifier", "administrator"]

    # Valid approve modes
    VALID_APPROVE_MODES = ["manual", "auto"]

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
        cls._validate(fresh, require_project=False)
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

        # Validate project type — 仅当 project 存在且（严格路径 或 显式提供 type）时校验
        project = config.get("project")
        if isinstance(project, dict) and (require_project or "type" in project):
            ptype = project.get("type", "")
            if ptype not in cls.VALID_PROJECT_TYPES:
                raise ValueError(
                    f"project.type must be one of {cls.VALID_PROJECT_TYPES}: {ptype}"
                )

        # Validate llm.providers (optional — absence means empty registry)
        llm = config.get("llm") or {}
        if llm:
            cls._validate_llm(llm)

        # Validate agents.models (optional — absence means no assignments)
        agents = config.get("agents") or {}
        if "models" in agents and agents["models"]:
            cls._validate_agent_models(agents["models"], llm)

        # Validate gates.approve_mode (optional — defaults to manual)
        gates = config.get("gates") or {}
        if "approve_mode" in gates and gates["approve_mode"] is not None:
            mode = gates["approve_mode"]
            if mode not in cls.VALID_APPROVE_MODES:
                raise ValueError(
                    f"gates.approve_mode must be one of {cls.VALID_APPROVE_MODES}: {mode}"
                )

        # D5：timeout_supervision.absolute_max_seconds 联动护栏，启动/热更新时校验；
        # enabled=true 且配置值低于 run_timeout + 续期上限时打 ERROR 并按兜底值生效。
        cls.effective_supervision_absolute_max_seconds(config)

        # Validate admin.* (optional — 缺省使用默认值，见 get_admin_config)
        admin = config.get("admin") or {}
        if "enabled" in admin and not isinstance(admin["enabled"], bool):
            raise ValueError(f"admin.enabled must be a boolean: {admin['enabled']}")
        for field in ("interval_minutes", "escalation_cooldown_minutes"):
            if field in admin and admin[field] is not None:
                val = admin[field]
                if not isinstance(val, (int, float)) or val <= 0:
                    raise ValueError(f"admin.{field} must be positive: {val}")

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
                    raise ValueError(
                        f"chain element [{idx}] missing non-empty 'provider' name"
                    )
                m = el.get("model")
                if m is not None and not isinstance(m, str):
                    raise ValueError(f"chain element [{idx}].model must be a string")
                elements.append((name, m if (isinstance(m, str) and m) else None))
            else:
                raise ValueError(
                    f"chain element [{idx}] must be a string or object"
                )
        return elements

    @classmethod
    def _resolve_element_model(cls, element_model: Optional[str],
                               role_model: Optional[str],
                               provider_entry: Optional[Dict[str, Any]]) -> Optional[str]:
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
    def _validate_agent_models(cls, models: Dict[str, Any], llm: Dict[str, Any]):
        if not isinstance(models, dict):
            raise ValueError(f"agents.models must be a dict, got: {type(models).__name__}")

        provider_names = set()
        providers = (llm or {}).get("providers") or []
        by_name: Dict[str, Any] = {}
        for p in providers:
            if isinstance(p, dict) and p.get("name"):
                provider_names.add(p["name"])
                by_name[p["name"]] = p

        for agent_type, assignment in models.items():
            if agent_type not in cls.KNOWN_AGENT_TYPES:
                raise ValueError(
                    f"agents.models key '{agent_type}' is not a known agent type. "
                    f"Known types: {cls.KNOWN_AGENT_TYPES}"
                )
            if not isinstance(assignment, dict):
                raise ValueError(f"agents.models.{agent_type} must be a dict")
            raw_provider = assignment.get("provider")
            role_model = assignment.get("model")
            # design D2：角色级 model 不再要求非空，语义降为「全链缺省」；
            # 仅当显式提供且非字符串时报错（bool/数字等非法类型）。
            if role_model is not None and not isinstance(role_model, str):
                raise ValueError(
                    f"agents.models.{agent_type}.model must be a string if provided"
                )
            # design D1：provider 支持 str | list[str|{{provider,model?}}]，规范化为
            # (provider_name, element_model) 二元组列表；形态非法直接拒绝。
            try:
                chain = cls._normalize_provider_chain(raw_provider)
            except ValueError as e:
                raise ValueError(
                    f"agents.models.{agent_type}.provider {e}"
                )
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
                    agent_type, ", ".join(unknown),
                )
            # design D1/D2：逐元素可解析性检查（替换原"角色级 model 必须非空"）。
            # 元素自带 / 角色级 / provider 条目 model 三者皆空 → ERROR 指明元素下标（不阻塞）。
            for idx, (name, element_model) in enumerate(chain):
                if name not in by_name:
                    continue  # 未知 provider 已打过 ERROR，跳过其模型解析
                resolved = cls._resolve_element_model(
                    element_model, role_model, by_name[name]
                )
                if not resolved:
                    _logger.error(
                        "agents.models.%s.provider[%d] 无法解析出模型名（元素/model、角色级 "
                        "model、provider 条目 model 均为空），运行期将跳过该元素",
                        agent_type, idx,
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
    def get_approve_mode(cls, config: Dict[str, Any]) -> str:
        """Return the approve_mode, defaulting to 'manual'."""
        gates = config.get("gates") or {}
        mode = gates.get("approve_mode")
        if mode not in cls.VALID_APPROVE_MODES:
            return "manual"
        return mode

    @classmethod
    def get_admin_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return the admin.* configuration段，缺失项填默认值。

        默认值（见 design D1/D2 与 Migration Plan）：
        - enabled: True
        - interval_minutes: 5
        - agent_model: None（未配置时复用 agents.subagent_model 默认）
        - escalation_cooldown_minutes: 15
        - stuck_threshold_minutes: 由 agents.run_timeout_seconds 单源派生（见
          effective_stuck_threshold_seconds，旧 schedule/admin.stuck_threshold_minutes
          键已弃用、不再生效）
        - merge_breaker_threshold: 复用 agents.merge_breaker_threshold（默认 2）
        """
        admin = config.get("admin") or {}
        # D2：stuck 阈值单源派生，旧键不再作为生效输入（告警在助手内节流）。
        stuck_seconds = cls.effective_stuck_threshold_seconds(config)
        breaker = cls.get(config, "admin.merge_breaker_threshold", None)
        if breaker is None:
            breaker = cls.get(config, "agents.merge_breaker_threshold", 2)
        return {
            "enabled": bool(admin.get("enabled", True)),
            "interval_minutes": float(admin.get("interval_minutes", 5)),
            "agent_model": admin.get("agent_model") or None,
            "escalation_cooldown_minutes": float(
                admin.get("escalation_cooldown_minutes", 15)
            ),
            "stuck_threshold_minutes": stuck_seconds / 60.0,
            "merge_breaker_threshold": int(breaker),
        }

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
                "（=3600 默认超时 + %ss 宽限）；建议显式配置 run_timeout_seconds",
                STUCK_FALLBACK_SECONDS, STUCK_GRACE_SECONDS,
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
                    configured, rt, SUPERVISION_EXTENSION_SECONDS, required, required,
                )
                _SUPERVISION_BOUNDS_WARNED = True
            return required
        return float(configured)

    @classmethod
    def reset_stuck_threshold_state(cls) -> None:
        """重置弃用/兜底告警的生命周期去重标记（供测试与 daemon 重启隔离）。

        正常 daemon 生命周期内只打一次；单测需多次验证「首次告警 / 二次静默」时显式重置。
        """
        global _DEPRECATED_STUCK_WARNED, _SUPERVISION_BOUNDS_WARNED
        _DEPRECATED_STUCK_WARNED = False
        _SUPERVISION_BOUNDS_WARNED = False

    @classmethod
    def get(cls, config: Dict[str, Any], dotted_key: str, default=None):
        """
        Get a nested config value by dotted key.
        E.g., config_get(config, "agents.max_turns", 50)
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
