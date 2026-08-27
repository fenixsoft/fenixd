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
    def _validate_agent_models(cls, models: Dict[str, Any], llm: Dict[str, Any]):
        if not isinstance(models, dict):
            raise ValueError(f"agents.models must be a dict, got: {type(models).__name__}")

        provider_names = set()
        providers = (llm or {}).get("providers") or []
        for p in providers:
            if isinstance(p, dict) and p.get("name"):
                provider_names.add(p["name"])

        for agent_type, assignment in models.items():
            if agent_type not in cls.KNOWN_AGENT_TYPES:
                raise ValueError(
                    f"agents.models key '{agent_type}' is not a known agent type. "
                    f"Known types: {cls.KNOWN_AGENT_TYPES}"
                )
            if not isinstance(assignment, dict):
                raise ValueError(f"agents.models.{agent_type} must be a dict")
            provider = assignment.get("provider")
            model = assignment.get("model")
            # add-provider-failover：provider 支持 str（单值链）或 list[str]（按序候选链）。
            # 非 str/list 形态视为配置错误直接拒绝；list 内每个元素也必须是非空字符串。
            if isinstance(provider, str):
                provider_chain = [provider] if provider else []
            elif isinstance(provider, list):
                provider_chain = [p for p in provider if isinstance(p, str) and p]
                if any(not isinstance(p, str) for p in provider):
                    raise ValueError(
                        f"agents.models.{agent_type}.provider list must contain only strings"
                    )
            else:
                raise ValueError(
                    f"agents.models.{agent_type}.provider must be a string or list of strings"
                )
            if not provider_chain:
                raise ValueError(f"agents.models.{agent_type}.provider must be a non-empty string or list")
            # add-provider-failover：未知 provider 名只打 ERROR 不阻塞加载（design D3：
            # 沿用热更新哲学，运行期该链元素被跳过）。不再抛 ValueError，否则坏一个名字
            # 就整 daemon 起不来。
            unknown = [n for n in provider_chain if n not in provider_names]
            if unknown:
                _logger.error(
                    "agents.models.%s.provider 引用了不存在的 provider（已跳过，不阻塞加载）: %s",
                    agent_type, ", ".join(unknown),
                )
            if not model or not isinstance(model, str):
                raise ValueError(f"agents.models.{agent_type}.model must be a non-empty string")

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

        model 解析（design D1 / spec provider-chain-config「模型名按 provider 独立解析」）：
        优先用角色级 `model` 字段（与变更前一致，保证 resume 续跑时跨 provider 用同一逻辑
        模型名不丢上下文）；角色级 `model` 缺失时回退到该 provider 项自身的 `model` 字段。
        """
        agents = config.get("agents") or {}
        models = agents.get("models") or {}
        assignment = models.get(agent_type)
        if not isinstance(assignment, dict):
            return None

        raw_provider = assignment.get("provider")
        role_model = assignment.get("model")
        # 解析 provider 为链：str → 单元素；list → 顺序候选；其余 → 空链
        if isinstance(raw_provider, str):
            chain_names = [raw_provider] if raw_provider else []
        elif isinstance(raw_provider, list):
            chain_names = [n for n in raw_provider if isinstance(n, str) and n]
        else:
            chain_names = []
        if not chain_names:
            return None

        llm = config.get("llm") or {}
        providers = llm.get("providers") or []
        by_name = {p.get("name"): p for p in providers if isinstance(p, dict)}

        result: List[Tuple[Dict[str, Any], str]] = []
        for name in chain_names:
            provider = by_name.get(name)
            if provider is None:
                # 未知名字已在校验阶段打 ERROR，运行期跳过该元素
                continue
            # model：角色级优先，回退 provider 自带 model
            model = role_model if (role_model and isinstance(role_model, str)) else provider.get("model")
            if not model:
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
        - stuck_threshold_minutes: 复用 schedule.stuck_threshold_minutes（默认 60）
        - merge_breaker_threshold: 复用 agents.merge_breaker_threshold（默认 2）
        """
        admin = config.get("admin") or {}
        stuck = cls.get(config, "admin.stuck_threshold_minutes", None)
        if stuck is None:
            stuck = cls.get(config, "schedule.stuck_threshold_minutes", 60)
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
            "stuck_threshold_minutes": float(stuck),
            "merge_breaker_threshold": int(breaker),
        }

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
