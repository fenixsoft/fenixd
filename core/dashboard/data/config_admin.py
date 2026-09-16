"""core.dashboard.data.config_admin — 配置读写引擎（config_admin 组）。

refactor-dashboard-data-module D3 分组：本模块承载配置读写职责域。
受管键白名单、read_config/read_effective_config/write_config/sync_config_from_user。
USER_CONFIG_PATH 按 D8 留在门面绑定，本模块内经门面解析。
"""

import copy
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

# ── 配置读写（受管键：llm / agents.* / gates.approve_mode / runs / verify.*） ──

# Dashboard 管理的配置键子集：写回时只更新这些键，其它键原样保留
_MANAGED_KEYS = ["llm", "agents", "gates", "runs", "verify", "hooks"]
# 在 agents 下管理的子键白名单
_AGENTS_MANAGED_SUBKEYS = [
    "models",
    "max_concurrent",
    "run_timeout_seconds",
    "max_turns",
    "daily_run_limit",
    "token_budget_millions",
    "impl_run_budget",
    "impl_run_budget_max",
    "verify_redo_budget",
]

# 用户级配置文件路径（与项目级同名 `.fenix/config.yaml`，作用域由所在目录决定）

# 受管键的来源标注键（前端用于「继承自用户级」badge）
_SOURCE_KEYS = [
    "llm",
    "agents.models",
    "agents.max_concurrent",
    "agents.run_timeout_seconds",
    "agents.max_turns",
    "agents.daily_run_limit",
    "agents.token_budget_millions",
    "agents.impl_run_budget",
    "agents.verify_redo_budget",
    "gates.approve_mode",
    # add-draft-promotion-gate：草稿晋升模式
    "gates.promote_mode",
    # add-spec-review-gate：方案评审模式
    "gates.spec_review_mode",
    # add-daily-self-review：admin.self_review 三键
    "admin.self_review",
    # add-settings-system-tab：admin.* 受管键（5 键）
    "admin.enabled",
    "admin.interval_minutes",
    "admin.escalation_cooldown_minutes",
    "admin.merge_breaker_threshold",
    "admin.shutdown_drain_seconds",
    # add-bug-repair-mode-config：bug-found 修复方式（inplace/derive）
    "admin.bug_repair_mode",
    # stuck-signal-hygiene D4：stuck 处置后静默期（分钟）
    "admin.stuck_silence_minutes",
    # 验证契约键（verify.*：静态服务范围 / worktree 依赖供给模式）
    "verify.static_scope",
    "verify.deps_mode",
    # add-planner-efficiency：planner 生成节流上限
    "verify.planner_max_concurrent",
    # add-spec-hooks：两级 hook 订阅配置（global + specs）
    "hooks",
    # fix-provider-transient-backoff（D6）：瞬断治理五键
    "agents.transient_backoff_schedule",
    "agents.transient_redispatch_delay_seconds",
    "agents.transient_break_threshold",
    "agents.transient_break_window_seconds",
    "agents.transient_break_cooldown_seconds",
    # add-stale-code-selfheal：陈旧自愈配置节两键
    "stale_code_selfheal.enabled",
    "stale_code_selfheal.idle_confirm_seconds",
    # add-framework-self-evolution：self_evolution 全局（用户级）三键
    "self_evolution.auto_accept",
    "self_evolution.max_items_per_run",
    "self_evolution.spec_run_at",
]

# 受管键的默认回显值（add-daily-self-review；与 ConfigLoader.get_self_review_config
# 保持一致：enabled/read_todo 缺省 false，run_at 缺省 02:00）
_DEFAULT_SELF_REVIEW = {"enabled": False, "run_at": "02:00", "read_todo": False}

_CONFIG_HEADER_COMMENT = (
    "# Fenix 配置文件\n"
    "# 本文件可通过 Dashboard 或手工编辑修改；修改后需重启 daemon 生效。\n"
    "# 敏感字段（如 apikey）请妥善保管，.fenix/ 目录已 gitignore。\n"
    "\n"
)


def _managed_key_sources(raw: dict) -> dict:
    """计算每个受管键的来源层级：在该文件中显式定义 → "project"，否则 "user"。

    "user" 表示该键未在此文件定义，由用户级配置或内置默认值兜底。
    """
    sources = {k: "user" for k in _SOURCE_KEYS}
    if isinstance(raw.get("llm"), dict):
        sources["llm"] = "project"
    agents_raw = raw.get("agents")
    if isinstance(agents_raw, dict):
        if isinstance(agents_raw.get("models"), dict):
            sources["agents.models"] = "project"
        if "max_concurrent" in agents_raw:
            sources["agents.max_concurrent"] = "project"
        if "run_timeout_seconds" in agents_raw:
            sources["agents.run_timeout_seconds"] = "project"
        if "max_turns" in agents_raw:
            sources["agents.max_turns"] = "project"
        if "daily_run_limit" in agents_raw:
            sources["agents.daily_run_limit"] = "project"
        if "token_budget_millions" in agents_raw:
            sources["agents.token_budget_millions"] = "project"
        if "impl_run_budget" in agents_raw:
            sources["agents.impl_run_budget"] = "project"
        if "verify_redo_budget" in agents_raw:
            sources["agents.verify_redo_budget"] = "project"
        # fix-provider-transient-backoff（D6）：瞬断治理五键显式定义 → project
        for _tk in (
            "transient_backoff_schedule",
            "transient_redispatch_delay_seconds",
            "transient_break_threshold",
            "transient_break_window_seconds",
            "transient_break_cooldown_seconds",
        ):
            if _tk in agents_raw:
                sources[f"agents.{_tk}"] = "project"
    gates_raw = raw.get("gates")
    if isinstance(gates_raw, dict) and "approve_mode" in gates_raw:
        sources["gates.approve_mode"] = "project"
    # add-draft-promotion-gate：草稿晋升模式显式定义 → project
    if isinstance(gates_raw, dict) and "promote_mode" in gates_raw:
        sources["gates.promote_mode"] = "project"
    # add-spec-review-gate：方案评审模式显式定义 → project
    if isinstance(gates_raw, dict) and "spec_review_mode" in gates_raw:
        sources["gates.spec_review_mode"] = "project"
    verify_src = raw.get("verify")
    if isinstance(verify_src, dict):
        if "static_scope" in verify_src:
            sources["verify.static_scope"] = "project"
        if "deps_mode" in verify_src:
            sources["verify.deps_mode"] = "project"
        if "planner_max_concurrent" in verify_src:
            sources["verify.planner_max_concurrent"] = "project"
    # add-daily-self-review：admin.self_review 段显式定义 → project
    admin_raw = raw.get("admin")
    if isinstance(admin_raw, dict) and isinstance(admin_raw.get("self_review"), dict):
        sources["admin.self_review"] = "project"
    # add-settings-system-tab：admin.* 受管键（5 键）显式定义 → project
    if isinstance(admin_raw, dict):
        for _k in (
            "enabled",
            "interval_minutes",
            "escalation_cooldown_minutes",
            "merge_breaker_threshold",
            "shutdown_drain_seconds",
            "bug_repair_mode",
            "stuck_silence_minutes",
        ):
            if _k in admin_raw:
                sources[f"admin.{_k}"] = "project"
    # add-spec-hooks：hooks 段显式定义 → project
    if isinstance(raw.get("hooks"), dict):
        sources["hooks"] = "project"
    # add-stale-code-selfheal：stale_code_selfheal 节显式定义 → project
    scs_raw = raw.get("stale_code_selfheal")
    if isinstance(scs_raw, dict):
        if "enabled" in scs_raw:
            sources["stale_code_selfheal.enabled"] = "project"
        if "idle_confirm_seconds" in scs_raw:
            sources["stale_code_selfheal.idle_confirm_seconds"] = "project"
    # add-framework-self-evolution：self_evolution 节（全局用户级键）——项目级
    # 写入被 write_config 前置校验拒绝；此处仅当手工残留/历史遗留时标注来源。
    se_raw = raw.get("self_evolution")
    if isinstance(se_raw, dict):
        if "auto_accept" in se_raw:
            sources["self_evolution.auto_accept"] = "project"
        if "max_items_per_run" in se_raw:
            sources["self_evolution.max_items_per_run"] = "project"
        if "spec_run_at" in se_raw:
            sources["self_evolution.spec_run_at"] = "project"
    return sources


# add-settings-system-tab：受管 admin.* 键缺省（与 ConfigLoader.get_admin_config
# 缺省一致：enabled=True / interval_minutes=5 / escalation_cooldown_minutes=60 /
# merge_breaker_threshold 复用 agents.merge_breaker_threshold（缺省 2）/
# shutdown_drain_seconds=1800 / bug_repair_mode=inplace）
_ADMIN_DEFAULTS = {
    "enabled": True,
    "interval_minutes": 5,
    "escalation_cooldown_minutes": 60,
    "shutdown_drain_seconds": 1800,
    "bug_repair_mode": "inplace",
    # stuck-signal-hygiene D4：stuck 处置后静默期（分钟，缺省 120，
    # 与 ConfigLoader.get_admin_config 缺省一致）
    "stuck_silence_minutes": 120,
}


def _managed_admin_keys(config: dict) -> dict:
    """受管 admin.* 键提取：6 键 + 缺省填充，不透传未知 admin 键/self_review 子段。

    与 llm/agents 段「缺省填充」形态一致：文件里为合法类型的值才回显，否则用缺省。
    merge_breaker_threshold 缺省沿用 agents.merge_breaker_threshold（未配置则为 2）；
    bug_repair_mode 仅 inplace/derive 回显，非法值回退缺省 inplace（写路径校验
    保证合法值才能落盘）。
    """
    admin = config.get("admin") if isinstance(config, dict) else None
    admin = admin if isinstance(admin, dict) else {}
    breaker = admin.get("merge_breaker_threshold")
    if not isinstance(breaker, int) or isinstance(breaker, bool) or breaker < 1:
        agents = config.get("agents") if isinstance(config, dict) else None
        breaker = agents.get("merge_breaker_threshold") if isinstance(agents, dict) else None
        if not isinstance(breaker, int) or isinstance(breaker, bool) or breaker < 1:
            breaker = 2
    out = {"merge_breaker_threshold": breaker}
    for key, default in _ADMIN_DEFAULTS.items():
        val = admin.get(key, default)
        if key == "enabled":
            out[key] = val if isinstance(val, bool) else default
        elif key == "bug_repair_mode":
            # 字符串枚举：仅 inplace/derive 回显，非法/非字符串回退缺省
            out[key] = val if val in ("inplace", "derive") else default
        else:
            # 数值键：非数值/布尔一律回退缺省（写路径校验保证合法值才能落盘）
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                val = default
            out[key] = val
    return out


def read_config(scope_root, scope: str = "project") -> dict:
    """读取指定作用域文件的受管配置段。

    scope="project"：读 <scope_root>/.fenix/config.yaml（现状）；
    scope="user"：读 ~/.fenix/config.yaml（scope_root 忽略）。

    返回: {"llm": {...}, "agents": {"models": {...}, "max_concurrent": int},
            "gates": {"approve_mode": ...}, "scope": "user"|"project",
            "raw_exists": bool, "sources": {...}, "error": str|null}
    容错：文件不存在返回空结构 + raw_exists=False；解析失败返回 error。
    """
    import core.dashboard.data as _facade

    config_path = (
        _facade.USER_CONFIG_PATH if scope == "user" else Path(scope_root) / ".fenix" / "config.yaml"
    )
    result = {
        "llm": {},
        "agents": {
            "models": {},
            "max_concurrent": 2,
            "run_timeout_seconds": 9000,
            "max_turns": 400,
            "daily_run_limit": 50,
            "token_budget_millions": 50,
            "impl_run_budget": 4,
            "verify_redo_budget": 3,
        },
        "gates": {"approve_mode": "manual", "promote_mode": "auto"},
        "runs": {"keep": 50},
        # 验证契约键（static_scope 服务范围 / deps_mode worktree 依赖供给模式）
        "verify": {"static_scope": "main", "deps_mode": "prefer-offline"},
        # add-spec-archive D5：自动归档阈值（0 = 禁用，默认 50）
        "archive": {"auto_threshold": 50},
        # add-daily-self-review：admin.self_review 三键（缺省 false/false/02:00）
        "self_review": dict(_DEFAULT_SELF_REVIEW),
        # add-settings-system-tab：admin.* 受管键（5 键 + 缺省填充）
        "admin": dict(_ADMIN_DEFAULTS, merge_breaker_threshold=2),
        # add-spec-hooks：两级 hook 订阅配置（缺省空订阅，零行为）
        "hooks": {"global": [], "specs": {}},
        # add-stale-code-selfheal：陈旧自愈配置节（enabled 缺省 true / idle_confirm_seconds 缺省 120）
        "stale_code_selfheal": {"enabled": True, "idle_confirm_seconds": 120},
        # add-framework-self-evolution：self_evolution 三键（缺省 auto_accept=false /
        # max_items_per_run=20 / spec_run_at=null 立即执行）
        "self_evolution": {"auto_accept": False, "max_items_per_run": 20, "spec_run_at": None},
        "scope": scope,
        "raw_exists": False,
        "sources": _managed_key_sources({}),
        "error": None,
    }
    if scope == "user":
        result["sources"] = {k: "user" for k in _SOURCE_KEYS}
    if not config_path.exists():
        return result
    result["raw_exists"] = True
    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        result["error"] = f"配置文件解析失败: {e}"
        return result
    if not isinstance(raw, dict):
        result["error"] = "配置文件顶层不是对象"
        return result

    if scope == "project":
        result["sources"] = _managed_key_sources(raw)

    # 提取受管键（白名单：llm / agents.models / agents.max_concurrent / gates.approve_mode）
    if isinstance(raw.get("llm"), dict):
        result["llm"] = raw["llm"]
    agents_raw = raw.get("agents")
    if isinstance(agents_raw, dict):
        agents_result = {}
        if isinstance(agents_raw.get("models"), dict):
            # improve-failover-model-mapping-ui（D4）：规范化 models 为 Dashboard
            # 回显视图（str/list/对象统一为对象数组 + resolved model）
            from core.config import ConfigLoader as _CL

            llm_providers = raw.get("llm", {}).get("providers") or []
            agents_result["models"] = _CL.normalize_agent_models(
                agents_raw["models"], llm_providers
            )
        if isinstance(agents_raw.get("max_concurrent"), int):
            agents_result["max_concurrent"] = agents_raw["max_concurrent"]
        if isinstance(agents_raw.get("run_timeout_seconds"), int):
            agents_result["run_timeout_seconds"] = agents_raw["run_timeout_seconds"]
        if isinstance(agents_raw.get("max_turns"), int):
            agents_result["max_turns"] = agents_raw["max_turns"]
        if isinstance(agents_raw.get("daily_run_limit"), int):
            agents_result["daily_run_limit"] = agents_raw["daily_run_limit"]
        if isinstance(agents_raw.get("token_budget_millions"), int):
            # add-cost-observability（D5）：预算键回显（此前缺提取，配置值读不回来）
            agents_result["token_budget_millions"] = agents_raw["token_budget_millions"]
        if isinstance(agents_raw.get("impl_run_budget"), int):
            agents_result["impl_run_budget"] = agents_raw["impl_run_budget"]
        if isinstance(agents_raw.get("verify_redo_budget"), int):
            agents_result["verify_redo_budget"] = agents_raw["verify_redo_budget"]
        # fix-provider-transient-backoff（D6）：瞬断治理五键回显到 agents 段
        # （缺省填充，语义与 read_effective_config 的 get_transient_config 一致）
        from core.config import ConfigLoader as _CLT

        _transient = _CLT.get_transient_config(raw)
        for _tk in (
            "transient_backoff_schedule",
            "transient_redispatch_delay_seconds",
            "transient_break_threshold",
            "transient_break_window_seconds",
            "transient_break_cooldown_seconds",
        ):
            agents_result[_tk] = _transient[_tk]
        if agents_result:
            # 只在结果中有受管键时覆盖默认，避免清空默认值
            for k, v in agents_result.items():
                result["agents"][k] = v
    gates_raw = raw.get("gates")
    if isinstance(gates_raw, dict) and "approve_mode" in gates_raw:
        result["gates"] = {"approve_mode": gates_raw["approve_mode"]}
    # add-draft-promotion-gate：promote_mode 提取（合法枚举才回显，非法留空由读侧缺省兜底）
    if isinstance(gates_raw, dict) and gates_raw.get("promote_mode") in ("auto", "manual"):
        if "gates" not in result:
            result["gates"] = {}
        result["gates"]["promote_mode"] = gates_raw["promote_mode"]
    # add-spec-review-gate：spec_review_mode 提取（合法枚举才回显，非法留空由读侧缺省兜底）
    if isinstance(gates_raw, dict) and gates_raw.get("spec_review_mode") in ("auto", "never"):
        if "gates" not in result:
            result["gates"] = {}
        result["gates"]["spec_review_mode"] = gates_raw["spec_review_mode"]
    verify_raw = raw.get("verify")
    if isinstance(verify_raw, dict):
        if verify_raw.get("static_scope") in ("main", "worktree"):
            result["verify"]["static_scope"] = verify_raw["static_scope"]
        if verify_raw.get("deps_mode") in ("prefer-offline", "hardlink"):
            result["verify"]["deps_mode"] = verify_raw["deps_mode"]
        # add-planner-efficiency（planner-generation-throttle 2.3）：节流上限读回。
        # 与写路径（write_config merge_verify）白名单对称——写了能读回来（BUG-01 修复）。
        pmc = verify_raw.get("planner_max_concurrent")
        if isinstance(pmc, int) and not isinstance(pmc, bool) and pmc >= 0:
            result["verify"]["planner_max_concurrent"] = pmc
    runs_raw = raw.get("runs")
    if (
        isinstance(runs_raw, dict)
        and isinstance(runs_raw.get("keep"), int)
        and runs_raw["keep"] >= 1
    ):
        result["runs"] = {"keep": runs_raw["keep"]}
    archive_raw = raw.get("archive")
    if isinstance(archive_raw, dict):
        from core.config import ConfigLoader as _CL

        result["archive"] = {"auto_threshold": _CL.effective_auto_archive_threshold(raw)}
    # add-daily-self-review：admin.self_review 三键（经 ConfigLoader 生效值回显）
    admin_raw = raw.get("admin")
    if isinstance(admin_raw, dict):
        from core.config import ConfigLoader as _CL

        result["self_review"] = _CL.get_self_review_config(raw)
        # add-settings-system-tab：受管 admin 键提取（5 键 + 缺省填充，不透传未知键）
        result["admin"] = _managed_admin_keys(raw)
    # add-spec-hooks：hooks 段原样透传（读回 UI 编辑视图）
    hooks_raw = raw.get("hooks")
    if isinstance(hooks_raw, dict):
        result["hooks"] = hooks_raw
    # add-stale-code-selfheal：陈旧自愈节回显（经 ConfigLoader 生效值——非法值
    # 回退缺省，回显与生效值一致）
    from core.config import ConfigLoader as _CLSC

    result["stale_code_selfheal"] = _CLSC.get_stale_code_selfheal_config(raw)
    # add-framework-self-evolution：self_evolution 节回显（经 get_self_evolution_config
    # 生效值——非法值回退缺省，回显与生效值一致；用户级全局键）
    from core.config import ConfigLoader as _CLSE

    result["self_evolution"] = _CLSE.get_self_evolution_config(raw)
    return result


# 配置解析签名缓存（dashboard-spec-summary-index D4）：
# read_effective_config 按 (用户级 config.yaml 签名, 项目级 config.yaml 签名) 缓存，
# mtime/size 未变不重读文件与 YAML 解析；写路径不维护显式失效（写后 mtime 已变，
# 签名键自然失效，与 _RUN_TASK_CACHE 同模式）。
# 缓存有界：键 ∈ {用户级 config.yaml，项目 config.yaml} × mtime 版本，超出整体清空
# （防配置频繁写入时旧键残留无界增长）。
_EFFECTIVE_CONFIG_CACHE: dict = {}
_EFFECTIVE_CONFIG_CACHE_MAX = 512


def _config_file_sig(path: Path):
    """配置文件签名 (mtime_ns, size)；缺失返回 None。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def read_effective_config(project_root) -> dict:
    """项目模式有效配置视图：受管键取 resolve_config 有效合并值 + sources 标注。

    返回: {"llm": {...}, "agents": {"models": {...}, "max_concurrent": int},
            "gates": {"approve_mode": ...}, "scope": "project", "raw_exists": bool,
            "sources": {...}, "error": str|null, "description": str}
    sources[key] = "project" 当该键在项目级文件显式定义，否则 "user"（继承用户级或默认）。

    配置解析缓存（D4）：以 (用户级 config.yaml, 项目级 config.yaml) 的
    (mtime_ns, size) 为键缓存解析结果；命中直接返回深拷贝，不重读文件。
    """
    from core.config import ConfigLoader

    proot = Path(project_root)
    proj_path = proot / ".fenix" / "config.yaml"

    import core.dashboard.data as _facade

    cache_key = (_config_file_sig(_facade.USER_CONFIG_PATH), _config_file_sig(proj_path))
    cached = _EFFECTIVE_CONFIG_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    result = {
        "llm": {},
        "agents": {
            "models": {},
            "max_concurrent": 2,
            "run_timeout_seconds": 9000,
            "max_turns": 400,
            "daily_run_limit": 50,
            "token_budget_millions": 50,
            "impl_run_budget": 4,
            "verify_redo_budget": 3,
        },
        "gates": {"approve_mode": "manual", "promote_mode": "auto"},
        "runs": {"keep": 50},
        # 验证契约键（static_scope 服务范围 / deps_mode worktree 依赖供给模式）
        "verify": {"static_scope": "main", "deps_mode": "prefer-offline"},
        # add-spec-archive D5：自动归档阈值（0 = 禁用，默认 50）
        "archive": {"auto_threshold": 50},
        # add-daily-self-review：admin.self_review 三键（缺省 false/false/02:00）
        "self_review": dict(_DEFAULT_SELF_REVIEW),
        # add-settings-system-tab：admin.* 受管键（5 键 + 缺省填充）
        "admin": dict(_ADMIN_DEFAULTS, merge_breaker_threshold=2),
        # add-spec-hooks：两级 hook 订阅配置（缺省空订阅，零行为）
        "hooks": {"global": [], "specs": {}},
        # add-stale-code-selfheal：陈旧自愈配置节（enabled 缺省 true / idle_confirm_seconds 缺省 120）
        "stale_code_selfheal": {"enabled": True, "idle_confirm_seconds": 120},
        # add-framework-self-evolution：self_evolution 用户级生效值（项目级只读透出）
        "self_evolution": {"auto_accept": False, "max_items_per_run": 20},
        "scope": "project",
        "raw_exists": proj_path.exists(),
        "sources": _managed_key_sources({}),
        "error": None,
    }

    # 项目级文件显式定义 → sources 标注；解析失败记录 error 不阻断合并视图
    if proj_path.exists():
        try:
            with proj_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                result["sources"] = _managed_key_sources(loaded)
            else:
                result["error"] = "配置文件顶层不是对象"
        except (yaml.YAMLError, OSError) as e:
            result["error"] = f"配置文件解析失败: {e}"

    try:
        effective = ConfigLoader.resolve_config(proot)
    except Exception as e:
        result["error"] = f"有效配置解析失败: {e}"
        if len(_EFFECTIVE_CONFIG_CACHE) > _EFFECTIVE_CONFIG_CACHE_MAX:
            _EFFECTIVE_CONFIG_CACHE.clear()
        _EFFECTIVE_CONFIG_CACHE[cache_key] = copy.deepcopy(result)
        return result

    # 提取受管键（有效合并值）
    if isinstance(effective.get("llm"), dict):
        result["llm"] = effective["llm"]
    agents_eff = effective.get("agents")
    if isinstance(agents_eff, dict):
        if isinstance(agents_eff.get("models"), dict):
            # improve-failover-model-mapping-ui（D4）：规范化 models 为 Dashboard
            # 回显视图（str/list/对象统一为对象数组 + resolved model）
            from core.config import ConfigLoader as _CL

            llm_eff = effective.get("llm") or {}
            result["agents"]["models"] = _CL.normalize_agent_models(
                agents_eff["models"], (llm_eff.get("providers") or [])
            )
        if isinstance(agents_eff.get("max_concurrent"), int):
            result["agents"]["max_concurrent"] = agents_eff["max_concurrent"]
        if isinstance(agents_eff.get("run_timeout_seconds"), int):
            result["agents"]["run_timeout_seconds"] = agents_eff["run_timeout_seconds"]
        if isinstance(agents_eff.get("max_turns"), int):
            result["agents"]["max_turns"] = agents_eff["max_turns"]
        if isinstance(agents_eff.get("daily_run_limit"), int):
            result["agents"]["daily_run_limit"] = agents_eff["daily_run_limit"]
        if isinstance(agents_eff.get("token_budget_millions"), int):
            # add-cost-observability（D5）：有效合并视图回显预算键（此前缺提取）
            result["agents"]["token_budget_millions"] = agents_eff["token_budget_millions"]
        if isinstance(agents_eff.get("impl_run_budget"), int):
            result["agents"]["impl_run_budget"] = agents_eff["impl_run_budget"]
        if isinstance(agents_eff.get("verify_redo_budget"), int):
            result["agents"]["verify_redo_budget"] = agents_eff["verify_redo_budget"]
        # fix-provider-transient-backoff（D6）：瞬断治理五键回显到 agents 段
        # （缺省填充，语义与 ConfigLoader.get_transient_config 一致——非法值回退缺省）。
        _transient = ConfigLoader.get_transient_config(effective)
        for _tk in (
            "transient_backoff_schedule",
            "transient_redispatch_delay_seconds",
            "transient_break_threshold",
            "transient_break_window_seconds",
            "transient_break_cooldown_seconds",
        ):
            result["agents"][_tk] = _transient[_tk]
    gates_eff = effective.get("gates")
    if isinstance(gates_eff, dict) and "approve_mode" in gates_eff:
        result["gates"] = {"approve_mode": gates_eff["approve_mode"]}
    # add-draft-promotion-gate：草稿晋升模式回显（缺省 auto）
    if isinstance(gates_eff, dict) and "promote_mode" in gates_eff:
        val = gates_eff["promote_mode"]
        if val in ("auto", "manual"):
            if "gates" not in result:
                result["gates"] = {}
            result["gates"]["promote_mode"] = val
    elif "gates" not in result:
        # 缺失时填默认值 auto（对齐 ConfigLoader.get_promote_mode）
        result["gates"] = {"promote_mode": "auto"}
    elif "promote_mode" not in result.get("gates", {}):
        result["gates"]["promote_mode"] = "auto"
    # add-spec-review-gate：方案评审模式回显（经 get_spec_review_mode 生效值，
    # 非法值/缺失回退缺省 auto——与 ConfigLoader 单点同源，回显与生效值一致）
    if "gates" not in result:
        result["gates"] = {}
    result["gates"]["spec_review_mode"] = ConfigLoader.get_spec_review_mode(effective)
    verify_eff = effective.get("verify")
    if isinstance(verify_eff, dict):
        if verify_eff.get("static_scope") in ("main", "worktree"):
            result["verify"]["static_scope"] = verify_eff["static_scope"]
        if verify_eff.get("deps_mode") in ("prefer-offline", "hardlink"):
            result["verify"]["deps_mode"] = verify_eff["deps_mode"]
        # add-planner-efficiency：节流上限有效值回显（与 write_config 白名单对称）
        pmc = verify_eff.get("planner_max_concurrent")
        if isinstance(pmc, int) and not isinstance(pmc, bool) and pmc >= 0:
            result["verify"]["planner_max_concurrent"] = pmc
    runs_eff = effective.get("runs")
    if (
        isinstance(runs_eff, dict)
        and isinstance(runs_eff.get("keep"), int)
        and runs_eff["keep"] >= 1
    ):
        result["runs"] = {"keep": runs_eff["keep"]}
    # add-spec-archive D5：经生效助手取值（非法配置回落默认 50，设置页回显一致）
    result["archive"] = {"auto_threshold": ConfigLoader.effective_auto_archive_threshold(effective)}
    # add-daily-self-review：经生效助手取值（run_at 非法值回退 02:00，回显一致）
    result["self_review"] = ConfigLoader.get_self_review_config(effective)
    # add-settings-system-tab：受管 admin 键提取（5 键 + 缺省填充，不透传未知键）
    result["admin"] = _managed_admin_keys(effective)
    # add-spec-hooks：hooks 段有效值透传（读回 UI 编辑视图）
    hooks_eff = effective.get("hooks")
    if isinstance(hooks_eff, dict):
        result["hooks"] = hooks_eff
    # add-stale-code-selfheal：陈旧自愈节有效值回显（经生效助手取值——非法值
    # 回退缺省，设置页回显与生效值一致）
    result["stale_code_selfheal"] = ConfigLoader.get_stale_code_selfheal_config(effective)
    # add-framework-self-evolution：self_evolution 用户级生效值透出（项目级视图
    # 只读展示全局键，面板在项目级作用域下据此置只读）
    result["self_evolution"] = ConfigLoader.get_self_evolution_config(effective)

    # 提取 project.description → 顶层 description（非 str 或缺失 → ""）
    project_eff = effective.get("project")
    if isinstance(project_eff, dict) and isinstance(project_eff.get("description"), str):
        result["description"] = project_eff["description"]
    else:
        result["description"] = ""

    if len(_EFFECTIVE_CONFIG_CACHE) > _EFFECTIVE_CONFIG_CACHE_MAX:
        _EFFECTIVE_CONFIG_CACHE.clear()
    _EFFECTIVE_CONFIG_CACHE[cache_key] = copy.deepcopy(result)
    return result


def _deep_merge_managed(raw_config: dict, patch: dict) -> dict:
    """把 patch 中的受管键合并到 raw_config，返回新 dict（不修改原对象）。

    合并规则（白名单化）：
    - llm: 整体替换（patch 中存在即替换，不存在则保留原 llm）
    - agents.models: 整体替换（只动 models，其它 agents 子键保留）
    - agents.max_concurrent: 替换（仅 patch 中提供且为正整数时）
    - gates.approve_mode: 只替换 approve_mode 子键
    - gates.promote_mode: 只替换 promote_mode 子键
    """
    import copy

    merged = copy.deepcopy(raw_config)

    if "llm" in patch:
        merged["llm"] = copy.deepcopy(patch["llm"])

    if "agents" in patch and isinstance(patch["agents"], dict):
        if not isinstance(merged.get("agents"), dict):
            merged["agents"] = {}
        if "models" in patch["agents"]:
            merged["agents"]["models"] = copy.deepcopy(patch["agents"]["models"])
        if "max_concurrent" in patch["agents"]:
            merged["agents"]["max_concurrent"] = patch["agents"]["max_concurrent"]
        if "run_timeout_seconds" in patch["agents"]:
            merged["agents"]["run_timeout_seconds"] = patch["agents"]["run_timeout_seconds"]
        if "max_turns" in patch["agents"]:
            merged["agents"]["max_turns"] = patch["agents"]["max_turns"]
        if "daily_run_limit" in patch["agents"]:
            merged["agents"]["daily_run_limit"] = patch["agents"]["daily_run_limit"]
        if "token_budget_millions" in patch["agents"]:
            # add-cost-observability（D5）：此前缺合并分支，保存后预算键被静默丢弃
            merged["agents"]["token_budget_millions"] = patch["agents"]["token_budget_millions"]
        if "impl_run_budget" in patch["agents"]:
            merged["agents"]["impl_run_budget"] = patch["agents"]["impl_run_budget"]
        if "verify_redo_budget" in patch["agents"]:
            # fix-daemon-lifecycle-races 验证发现：缺合并分支导致保存被静默丢弃
            merged["agents"]["verify_redo_budget"] = patch["agents"]["verify_redo_budget"]
        # fix-provider-transient-backoff（D6）：瞬断治理五键合并分支（前置校验
        # 已拒绝非法值，此处只应用合法值；缺省透传由 get_transient_config 兜底）。
        for _tk in (
            "transient_backoff_schedule",
            "transient_redispatch_delay_seconds",
            "transient_break_threshold",
            "transient_break_window_seconds",
            "transient_break_cooldown_seconds",
        ):
            if _tk in patch["agents"]:
                merged["agents"][_tk] = patch["agents"][_tk]

    if "gates" in patch and isinstance(patch["gates"], dict):
        if (
            "approve_mode" in patch["gates"]
            or "promote_mode" in patch["gates"]
            or "spec_review_mode" in patch["gates"]
        ):
            if not isinstance(merged.get("gates"), dict):
                merged["gates"] = {}
        if "approve_mode" in patch["gates"]:
            merged["gates"]["approve_mode"] = patch["gates"]["approve_mode"]
        # add-draft-promotion-gate 验证修复：缺合并分支导致设置页保存的
        # promote_mode 在 merge 阶段被静默丢弃（枚举合法性已由 write_config 前置校验把关）
        if "promote_mode" in patch["gates"]:
            merged["gates"]["promote_mode"] = patch["gates"]["promote_mode"]
        # add-spec-review-gate：spec_review_mode 合并分支（缺合并分支会导致设置页
        # 保存的 spec_review_mode 在 merge 阶段被静默丢弃；枚举合法性已由
        # write_config 前置校验把关）
        if "spec_review_mode" in patch["gates"]:
            merged["gates"]["spec_review_mode"] = patch["gates"]["spec_review_mode"]

    if "runs" in patch and isinstance(patch["runs"], dict):
        keep = patch["runs"].get("keep")
        # 仅接受正整数，非法值静默忽略（保留原配置）
        if isinstance(keep, int) and keep >= 1:
            if not isinstance(merged.get("runs"), dict):
                merged["runs"] = {}
            merged["runs"]["keep"] = keep
    # verify.*：static_scope 服务范围 / deps_mode 依赖供给模式
    # （非法值由 write_config 前置校验拒绝，此处只应用合法值）
    if "verify" in patch and isinstance(patch["verify"], dict):
        if not isinstance(merged.get("verify"), dict):
            merged["verify"] = {}
        for vk in ("static_scope", "deps_mode"):
            if (
                patch["verify"].get(vk) in ("main", "worktree")
                if vk == "static_scope"
                else patch["verify"].get(vk) in ("prefer-offline", "hardlink")
            ):
                merged["verify"][vk] = patch["verify"][vk]
        # add-planner-efficiency（planner-generation-throttle 2.3）：
        # planner 生成节流上限——非负整数（0=不节流），非法值静默忽略。
        pmc = patch["verify"].get("planner_max_concurrent")
        if isinstance(pmc, int) and not isinstance(pmc, bool) and pmc >= 0:
            merged["verify"]["planner_max_concurrent"] = pmc
    # add-spec-archive D5：archive.auto_threshold（非负整数，0=禁用，非法值静默忽略）
    if "archive" in patch and isinstance(patch["archive"], dict):
        at = patch["archive"].get("auto_threshold")
        if isinstance(at, int) and at >= 0:
            if not isinstance(merged.get("archive"), dict):
                merged["archive"] = {}
            merged["archive"]["auto_threshold"] = at
    # add-daily-self-review：admin.self_review 三键（enabled/read_todo 布尔、
    # run_at 合法 HH:MM；非法 run_at 由 write_config 前置校验拒绝，此处只应用合法值）
    if "self_review" in patch and isinstance(patch["self_review"], dict):
        if not isinstance(merged.get("admin"), dict):
            merged["admin"] = {}
        existing_sr = merged["admin"].get("self_review")
        if not isinstance(existing_sr, dict):
            existing_sr = {}
        sr = dict(existing_sr)
        for field in ("enabled", "read_todo"):
            if field in patch["self_review"] and isinstance(patch["self_review"][field], bool):
                sr[field] = patch["self_review"][field]
        run_at = patch["self_review"].get("run_at")
        from core.config import ConfigLoader as _CL

        if _CL.is_valid_hhmm(run_at):
            sr["run_at"] = run_at
        merged["admin"]["self_review"] = sr
    # add-settings-system-tab：admin.* 六键合并。只动 6 个受管键——保留 admin 段内
    # 的 self_review / agent_model / workers 等未知或非受管键（写路径校验保证
    # 进入此处的值合法，self_review 由顶层 patch 分支单独合并）。
    if "admin" in patch and isinstance(patch["admin"], dict):
        if not isinstance(merged.get("admin"), dict):
            merged["admin"] = {}
        for ak in (
            "enabled",
            "interval_minutes",
            "escalation_cooldown_minutes",
            "merge_breaker_threshold",
            "shutdown_drain_seconds",
            "bug_repair_mode",
            "stuck_silence_minutes",
        ):
            if ak in patch["admin"] and patch["admin"][ak] is not None:
                merged["admin"][ak] = patch["admin"][ak]
    # description 分支：patch 顶层 description（str）写入 merged["project"]["description"]
    if "description" in patch and isinstance(patch["description"], str):
        if not isinstance(merged.get("project"), dict):
            merged["project"] = {}
        merged["project"]["description"] = patch["description"]
    # add-spec-hooks：hooks 段整体替换（patch 中存在即替换，不存在则保留原段）
    if "hooks" in patch:
        merged["hooks"] = copy.deepcopy(patch["hooks"])
    # add-stale-code-selfheal：stale_code_selfheal 节两键合并（前置校验已拒绝
    # 非法值，此处只应用合法值；缺省透传由 get_stale_code_selfheal_config 兜底）
    if "stale_code_selfheal" in patch and isinstance(patch["stale_code_selfheal"], dict):
        if not isinstance(merged.get("stale_code_selfheal"), dict):
            merged["stale_code_selfheal"] = {}
        scs = patch["stale_code_selfheal"]
        if "enabled" in scs:
            merged["stale_code_selfheal"]["enabled"] = scs["enabled"]
        if "idle_confirm_seconds" in scs:
            merged["stale_code_selfheal"]["idle_confirm_seconds"] = scs["idle_confirm_seconds"]
    # add-framework-self-evolution：self_evolution 三键合并（项目级作用域写入已
    # 被 write_config 前置校验拒绝，此处仅处理用户级合法值；缺省透传由
    # get_self_evolution_config 兜底）
    if "self_evolution" in patch and isinstance(patch["self_evolution"], dict):
        if not isinstance(merged.get("self_evolution"), dict):
            merged["self_evolution"] = {}
        se_p = patch["self_evolution"]
        if "auto_accept" in se_p:
            merged["self_evolution"]["auto_accept"] = se_p["auto_accept"]
        if "max_items_per_run" in se_p:
            merged["self_evolution"]["max_items_per_run"] = se_p["max_items_per_run"]
        if "spec_run_at" in se_p:
            # null 显式写回 null（= 取消定时，回到立即执行）：不能因「假值不可写」
            # 而保留旧时刻，否则 UI 上关不掉定时
            merged["self_evolution"]["spec_run_at"] = se_p["spec_run_at"]

    return merged


def write_config(scope_root, config_patch: dict, scope: str = "project") -> dict:
    """把受管配置段写回作用域文件（原子写、保留非受管键）。

    写入前使用 ConfigLoader 做受管字段局部校验，校验失败返回错误且不写盘。

    Args:
        scope_root: 项目根路径（scope="project" 时使用；scope="user" 忽略）
        config_patch: 含 llm / agents.models / gates.approve_mode 的 patch dict
        scope: "user" 写 ~/.fenix/config.yaml（自动建目录）；"project" 写项目文件

    Returns: {"ok": bool, "error": str|null, "scope": "user"|"project", "path": str}
    """
    from core.config import ConfigLoader

    import core.dashboard.data as _facade

    if scope == "user":
        config_path = _facade.USER_CONFIG_PATH
    else:
        config_path = Path(scope_root) / ".fenix" / "config.yaml"
    config_dir = config_path.parent
    fail = lambda err: {"ok": False, "error": err, "scope": scope, "path": str(config_path)}

    # 1. 读取现有配置（若不存在则为空 dict，写入时创建）
    raw = {}
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw = loaded
        except (yaml.YAMLError, OSError) as e:
            return fail(f"读取现有配置失败: {e}")

    # improve-failover-model-mapping-ui（D4/D5）：前端编辑器状态（规范化的行列表）
    # 序列化为 _validate_agent_models 能消费的 canonical 形态（str / list[str|对象]）。
    # 在合并前序列化，保证校验与写入都使用 canonical 形态；role-level model 空值
    # 不写入，避免空串覆盖配置文件中已有的模型缺省。
    if isinstance(config_patch.get("agents"), dict) and isinstance(
        config_patch["agents"].get("models"), dict
    ):
        config_patch = dict(config_patch)  # shallow copy, 不改入参
        config_patch["agents"] = dict(config_patch["agents"])
        config_patch["agents"]["models"] = ConfigLoader.serialize_models_patch(
            config_patch["agents"]["models"]
        )

    # add-daily-self-review：前端提交的 self_review patch 后端校验（非法直接拒绝，
    # 不静默忽略——spec「非法输入（如 25:00）被前端与后端双重校验拒绝」）。
    if isinstance(config_patch.get("self_review"), dict):
        sr_patch = config_patch["self_review"]
        for field in ("enabled", "read_todo"):
            if (
                field in sr_patch
                and sr_patch[field] is not None
                and not isinstance(sr_patch[field], bool)
            ):
                return fail(f"admin.self_review.{field} must be a boolean: {sr_patch[field]}")
        if "run_at" in sr_patch and sr_patch["run_at"] is not None:
            if not ConfigLoader.is_valid_hhmm(sr_patch["run_at"]):
                return fail(
                    f"admin.self_review.run_at must be HH:MM (00:00-23:59): {sr_patch['run_at']}"
                )

    # verify.* patch 前置校验：非法值直接拒绝，不静默忽略（同 self_review 模式；
    # 只在 merge 层过滤会让 write "成功" 但用户输入被吞）
    if isinstance(config_patch.get("verify"), dict):
        v_patch = config_patch["verify"]
        if (
            "static_scope" in v_patch
            and v_patch["static_scope"] is not None
            and v_patch["static_scope"] not in ("main", "worktree")
        ):
            return fail(
                f"verify.static_scope must be one of ['main', 'worktree']: "
                f"{v_patch['static_scope']}"
            )
        if (
            "deps_mode" in v_patch
            and v_patch["deps_mode"] is not None
            and v_patch["deps_mode"] not in ("prefer-offline", "hardlink")
        ):
            return fail(
                f"verify.deps_mode must be one of ['prefer-offline', 'hardlink']: "
                f"{v_patch['deps_mode']}"
            )
        # add-planner-efficiency：planner 生成节流上限——非负整数（0=不节流）。
        if "planner_max_concurrent" in v_patch and v_patch["planner_max_concurrent"] is not None:
            pmc = v_patch["planner_max_concurrent"]
            if not isinstance(pmc, int) or isinstance(pmc, bool) or pmc < 0:
                return fail(
                    f"verify.planner_max_concurrent must be a non-negative integer "
                    f"(0=不节流): {pmc!r}"
                )

    # add-settings-system-tab：admin.* 五键前置校验（非法值直接拒绝，不静默忽略——
    # 与 verify/self_review 同模式，前端输入类型错误在后端权威兜底）。
    if isinstance(config_patch.get("admin"), dict):
        adm = config_patch["admin"]
        if "enabled" in adm and adm["enabled"] is not None and not isinstance(adm["enabled"], bool):
            return fail(f"admin.enabled must be a boolean: {adm['enabled']!r}")
        if "interval_minutes" in adm and adm["interval_minutes"] is not None:
            im = adm["interval_minutes"]
            if not isinstance(im, (int, float)) or isinstance(im, bool) or im <= 0:
                return fail(f"admin.interval_minutes must be a positive number: {im!r}")
        if "escalation_cooldown_minutes" in adm and adm["escalation_cooldown_minutes"] is not None:
            ec = adm["escalation_cooldown_minutes"]
            if not isinstance(ec, (int, float)) or isinstance(ec, bool) or ec < 0:
                return fail(
                    f"admin.escalation_cooldown_minutes must be a non-negative number: {ec!r}"
                )
        # stuck-signal-hygiene D4：stuck 处置后静默期——非负数值（同
        # escalation_cooldown_minutes；0 = 不静默），非法值直接拒绝。
        if "stuck_silence_minutes" in adm and adm["stuck_silence_minutes"] is not None:
            ssm = adm["stuck_silence_minutes"]
            if not isinstance(ssm, (int, float)) or isinstance(ssm, bool) or ssm < 0:
                return fail(f"admin.stuck_silence_minutes must be a non-negative number: {ssm!r}")
        if "merge_breaker_threshold" in adm and adm["merge_breaker_threshold"] is not None:
            mb = adm["merge_breaker_threshold"]
            if not isinstance(mb, int) or isinstance(mb, bool) or mb < 1:
                return fail(f"admin.merge_breaker_threshold must be a positive integer: {mb!r}")
        if "shutdown_drain_seconds" in adm and adm["shutdown_drain_seconds"] is not None:
            sd = adm["shutdown_drain_seconds"]
            if not isinstance(sd, int) or isinstance(sd, bool) or sd < 0:
                return fail(f"admin.shutdown_drain_seconds must be a non-negative integer: {sd!r}")
        # add-bug-repair-mode-config：bug_repair_mode 枚举校验（inplace/derive，
        # 非法值直接拒绝——前端类型错误在后端权威兜底，与其它 admin 键同模式）。
        if "bug_repair_mode" in adm and adm["bug_repair_mode"] is not None:
            brm = adm["bug_repair_mode"]
            if brm not in ("inplace", "derive"):
                return fail(f"admin.bug_repair_mode must be one of ['inplace', 'derive']: {brm!r}")

    # add-draft-promotion-gate：gates.promote_mode 前置校验（枚举拒绝，对齐 approve_mode）
    if isinstance(config_patch.get("gates"), dict):
        g_patch = config_patch["gates"]
        if (
            "promote_mode" in g_patch
            and g_patch["promote_mode"] is not None
            and g_patch["promote_mode"] not in ("auto", "manual")
        ):
            return fail(
                f"gates.promote_mode must be one of ['auto', 'manual']: {g_patch['promote_mode']!r}"
            )
        # add-spec-review-gate：gates.spec_review_mode 前置校验（枚举拒绝，
        # 与 promote_mode 同模式；None 视为「未提交」，不校验）
        if (
            "spec_review_mode" in g_patch
            and g_patch["spec_review_mode"] is not None
            and g_patch["spec_review_mode"] not in ("auto", "never")
        ):
            return fail(
                f"gates.spec_review_mode must be one of ['auto', 'never']: {g_patch['spec_review_mode']!r}"
            )

    # add-spec-hooks D7：hooks 段前置校验（非法值直接拒绝 400 且不写入——规则：
    # events 非空且合法、action 合法、webhook 必填 url、shell 必填 command）。
    if isinstance(config_patch.get("hooks"), dict):
        from core.hook_engine import validate_hooks_config

        hooks_err = validate_hooks_config(config_patch)
        if hooks_err:
            return fail(f"hooks 配置非法：{hooks_err}")

    # add-stale-code-selfheal：stale_code_selfheal 两键前置校验（非法值直接拒绝
    # 400，不静默忽略——与 verify/self_review/admin 同模式，前端类型错误在后端
    # 权威兜底）。
    if isinstance(config_patch.get("stale_code_selfheal"), dict):
        scs = config_patch["stale_code_selfheal"]
        if "enabled" in scs and scs["enabled"] is not None and not isinstance(scs["enabled"], bool):
            return fail(f"stale_code_selfheal.enabled must be a boolean: {scs['enabled']!r}")
        if "idle_confirm_seconds" in scs and scs["idle_confirm_seconds"] is not None:
            _scs_v = scs["idle_confirm_seconds"]
            if isinstance(_scs_v, bool) or not isinstance(_scs_v, (int, float)) or _scs_v <= 0:
                return fail(
                    f"stale_code_selfheal.idle_confirm_seconds must be a positive "
                    f"integer: {_scs_v!r}"
                )

    # add-framework-self-evolution：self_evolution 三键前置校验 + 项目级作用域拒绝。
    # 三键为全局（用户级）键：项目级作用域提交含 self_evolution → 400 且不写盘
    # （spec「项目级写入被拒」）；用户级提交的非法值直接拒绝 400，不静默忽略。
    if "self_evolution" in config_patch:
        if scope != "user":
            return fail(
                "self_evolution 为全局用户级键（auto_accept / max_items_per_run / "
                "spec_run_at），请在用户级作用域修改"
            )
        se_patch = config_patch["self_evolution"]
        if not isinstance(se_patch, dict):
            return fail(f"self_evolution must be an object: {se_patch!r}")
        if (
            "auto_accept" in se_patch
            and se_patch["auto_accept"] is not None
            and not isinstance(se_patch["auto_accept"], bool)
        ):
            return fail(
                f"self_evolution.auto_accept must be a boolean: " f"{se_patch['auto_accept']!r}"
            )
        if "max_items_per_run" in se_patch and se_patch["max_items_per_run"] is not None:
            _se_v = se_patch["max_items_per_run"]
            if isinstance(_se_v, bool) or not isinstance(_se_v, int) or _se_v < 1 or _se_v > 200:
                return fail(
                    f"self_evolution.max_items_per_run must be an integer in "
                    f"[1, 200]: {_se_v!r}"
                )
        # spec_run_at：null（立即执行）或合法 HH:MM；25:00 之类直接拒绝 400
        if "spec_run_at" in se_patch and se_patch["spec_run_at"] is not None:
            if not ConfigLoader.is_valid_hhmm(se_patch["spec_run_at"]):
                return fail(
                    f"self_evolution.spec_run_at must be null or HH:MM "
                    f"(00:00-23:59): {se_patch['spec_run_at']!r}"
                )

    # 2. 合并受管键
    merged = _deep_merge_managed(raw, config_patch)

    # improve-provider-billing-config（D1）：顶层 llm.billing 段移除——即使旧客户端
    # 仍提交旧形态也剥离，保证落盘文件永不含顶层 llm.billing（下次保存自然清除
    # 手工残留的旧键）。
    if isinstance(merged.get("llm"), dict) and "billing" in merged["llm"]:
        merged["llm"].pop("billing", None)

    # 3. 校验受管字段（llm / agents.models / agents.max_concurrent / gates.approve_mode）
    #    不做完整 ConfigLoader 校验，避免缺少 project/schedule 等必填键时无法写入。
    try:
        llm = merged.get("llm") or {}
        if llm:
            ConfigLoader._validate_llm(llm)
        # improve-provider-billing-config（task 2.1）：per-provider billing 校验——
        # 遍历 llm.providers[i].billing（enabled 布尔、prices 行 model 非空、4 项
        # 单价非负数值排除 bool、同一卡片内行 model 不重复）；任一非法拒绝写入并
        # 列出违规项。与 _validate_llm 内 load-time 校验共用 _validate_provider_billing。
        if isinstance(llm, dict):
            _providers = llm.get("providers")
            if _providers is not None:
                if not isinstance(_providers, list):
                    raise ValueError("llm.providers must be a list")
                ConfigLoader._validate_provider_billing(_providers)
        agents = merged.get("agents") or {}
        if "models" in agents and agents["models"]:
            ConfigLoader._validate_agent_models(agents["models"], llm)
            # improve-failover-model-mapping-ui D5：Dashboard 保存时额外要求每行引用的
            # provider 名必须存在于 llm.providers（load-time 校验只打 ERROR 不阻塞，但
            # UI 保存不允许"脏配置"落盘）。
            model_patch = (
                config_patch.get("agents", {}).get("models", {})
                if config_patch.get("agents")
                else {}
            )
            if model_patch:
                provider_names = set()
                provs = (llm or {}).get("providers") or []
                for p in provs:
                    if isinstance(p, dict) and p.get("name"):
                        provider_names.add(p["name"])
                for role, entry in model_patch.items():
                    if not isinstance(entry, dict):
                        continue
                    provider_val = entry.get("provider")
                    bad = []
                    if isinstance(provider_val, str):
                        if provider_val and provider_val not in provider_names:
                            bad.append(provider_val)
                    elif isinstance(provider_val, list):
                        for el in provider_val:
                            n = el.get("provider") if isinstance(el, dict) else el
                            if isinstance(n, str) and n and n not in provider_names:
                                bad.append(n)
                    if bad:
                        raise ValueError(
                            f"agents.models.{role}.provider 引用了不存在的 provider: "
                            + ", ".join(sorted(set(bad)))
                        )
        if "max_concurrent" in agents:
            mc = agents["max_concurrent"]
            if not isinstance(mc, int) or mc <= 0:
                raise ValueError(f"agents.max_concurrent must be a positive integer: {mc}")
        if "run_timeout_seconds" in agents:
            rt = agents["run_timeout_seconds"]
            if not isinstance(rt, int) or rt <= 0:
                raise ValueError(f"agents.run_timeout_seconds must be a positive integer: {rt}")
        if "max_turns" in agents:
            mt = agents["max_turns"]
            if not isinstance(mt, int) or mt <= 0:
                raise ValueError(f"agents.max_turns must be a positive integer: {mt}")
        if "daily_run_limit" in agents:
            drl = agents["daily_run_limit"]
            if not isinstance(drl, int) or drl < 0:
                raise ValueError(f"agents.daily_run_limit must be a non-negative integer: {drl}")
        if "impl_run_budget" in agents:
            irb = agents["impl_run_budget"]
            # open-impl-budget-ceiling：上限由 agents.impl_run_budget_max 决定
            # （缺省 100，硬天花板 1000），不再硬编码 10。
            from core.pm_engine.budget import resolve_impl_run_budget_max

            budget_max = resolve_impl_run_budget_max(agents.get("impl_run_budget_max"))
            if not isinstance(irb, int) or irb < 1 or irb > budget_max:
                raise ValueError(
                    f"agents.impl_run_budget must be an integer in [1, {budget_max}]: {irb}"
                )
        if "impl_run_budget_max" in agents:
            ibm = agents["impl_run_budget_max"]
            from core.pm_engine.budget import (
                resolve_impl_run_budget_max,
                IMPL_RUN_BUDGET_MAX_CEILING,
            )

            if (
                not isinstance(ibm, int)
                or isinstance(ibm, bool)
                or ibm < 1
                or ibm > IMPL_RUN_BUDGET_MAX_CEILING
            ):
                raise ValueError(
                    f"agents.impl_run_budget_max must be an integer in "
                    f"[1, {IMPL_RUN_BUDGET_MAX_CEILING}]: {ibm}"
                )
        if "verify_redo_budget" in agents:
            vrb = agents["verify_redo_budget"]
            if not isinstance(vrb, int) or vrb < 1 or vrb > 10:
                raise ValueError(f"agents.verify_redo_budget must be an integer in [1, 10]: {vrb}")
        # fix-provider-transient-backoff（D6）：瞬断治理四数值键——非负整数校验
        # （非法值直接拒绝 400，与 verify/self_review/admin 同模式，前端类型错误
        # 由后端权威兜底；缺省回显与回退仍走 get_transient_config）。
        for _tk in (
            "transient_redispatch_delay_seconds",
            "transient_break_threshold",
            "transient_break_window_seconds",
            "transient_break_cooldown_seconds",
        ):
            if _tk in agents and agents[_tk] is not None:
                _tv = agents[_tk]
                if isinstance(_tv, bool) or not isinstance(_tv, (int, float)) or _tv < 0:
                    raise ValueError(f"agents.{_tk} must be a non-negative integer: {_tv!r}")
        if (
            "transient_backoff_schedule" in agents
            and agents["transient_backoff_schedule"] is not None
        ):
            _ts = agents["transient_backoff_schedule"]
            if not isinstance(_ts, str):
                raise ValueError(
                    "agents.transient_backoff_schedule must be a comma-separated "
                    f"seconds string: {_ts!r}"
                )
            # 逗号秒序列校验：任一元素非正整数即拒绝（空串=关闭原地退避，允许）
            if _ts.strip():
                for _part in _ts.split(","):
                    _p = _part.strip()
                    if not _p:
                        continue
                    try:
                        _iv = int(_p)
                    except (TypeError, ValueError):
                        raise ValueError(
                            f"agents.transient_backoff_schedule 元素非正整数: {_part!r}"
                        )
                    if _iv <= 0:
                        raise ValueError(
                            f"agents.transient_backoff_schedule 元素非正整数: {_part!r}"
                        )
        gates = merged.get("gates") or {}
        if "approve_mode" in gates and gates["approve_mode"] is not None:
            mode = gates["approve_mode"]
            if mode not in ConfigLoader.VALID_APPROVE_MODES:
                raise ValueError(
                    f"gates.approve_mode must be one of {ConfigLoader.VALID_APPROVE_MODES}: {mode}"
                )
        verify_m = merged.get("verify") or {}
        if "static_scope" in verify_m and verify_m["static_scope"] is not None:
            if verify_m["static_scope"] not in ("main", "worktree"):
                raise ValueError(
                    f"verify.static_scope must be one of ['main', 'worktree']: "
                    f"{verify_m['static_scope']}"
                )
        if "deps_mode" in verify_m and verify_m["deps_mode"] is not None:
            if verify_m["deps_mode"] not in ("prefer-offline", "hardlink"):
                raise ValueError(
                    f"verify.deps_mode must be one of ['prefer-offline', 'hardlink']: "
                    f"{verify_m['deps_mode']}"
                )
        # add-spec-archive D5：archive.auto_threshold 必须为非负整数（0=禁用）
        archive_m = merged.get("archive") or {}
        if "auto_threshold" in archive_m and archive_m["auto_threshold"] is not None:
            at = archive_m["auto_threshold"]
            if not isinstance(at, int) or isinstance(at, bool) or at < 0:
                raise ValueError(
                    f"archive.auto_threshold must be a non-negative integer (0=disabled): {at}"
                )
        # add-daily-self-review：admin.self_review 三键（后端校验，非法输入拒绝 400）
        admin_m = merged.get("admin") or {}
        if isinstance(admin_m, dict) and isinstance(admin_m.get("self_review"), dict):
            sr = admin_m["self_review"]
            for field in ("enabled", "read_todo"):
                if field in sr and sr[field] is not None and not isinstance(sr[field], bool):
                    raise ValueError(f"admin.self_review.{field} must be a boolean: {sr[field]}")
            if "run_at" in sr and sr["run_at"] is not None:
                from core.config import ConfigLoader as _CL

                if not _CL.is_valid_hhmm(sr["run_at"]):
                    raise ValueError(
                        f"admin.self_review.run_at must be HH:MM (00:00-23:59): {sr['run_at']}"
                    )
        # add-settings-system-tab：admin.* 六键（merged 视图校验；写路径前置校验
        # 已拒绝非法 patch，此处兜底防绕过前置校验的直连调用）
        if (
            "enabled" in admin_m
            and admin_m["enabled"] is not None
            and not isinstance(admin_m["enabled"], bool)
        ):
            raise ValueError(f"admin.enabled must be a boolean: {admin_m['enabled']!r}")
        if (
            "bug_repair_mode" in admin_m
            and admin_m["bug_repair_mode"] is not None
            and admin_m["bug_repair_mode"] not in ("inplace", "derive")
        ):
            raise ValueError(
                f"admin.bug_repair_mode 非法：{admin_m['bug_repair_mode']!r}"
                f"（保存被拒绝，请修正后重试）"
            )
        for _k, _rule in (
            (
                "interval_minutes",
                lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0,
            ),
            (
                "escalation_cooldown_minutes",
                lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0,
            ),
            (
                "merge_breaker_threshold",
                lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 1,
            ),
            (
                "shutdown_drain_seconds",
                lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
            ),
            (
                "stuck_silence_minutes",
                lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0,
            ),
        ):
            if _k in admin_m and admin_m[_k] is not None and not _rule(admin_m[_k]):
                raise ValueError(f"admin.{_k} 非法：{admin_m[_k]!r}（保存被拒绝，请修正后重试）")
        # add-spec-hooks D7：merged 视图 hooks 校验（兜底防绕过前置校验的直连调用；
        # 校验规则同前置，但作用于合并后视图，含项目级手工写入的非受管 hooks 段）
        from core.hook_engine import validate_hooks_config as _validate_hooks

        if isinstance(merged.get("hooks"), dict):
            _err = _validate_hooks(merged)
            if _err:
                raise ValueError(f"hooks 配置非法：{_err}")
        # add-stale-code-selfheal：merged 视图校验（兜底防绕过前置校验的直连调用，
        # 与 hooks 同模式）
        scs_m = merged.get("stale_code_selfheal")
        if isinstance(scs_m, dict):
            if (
                "enabled" in scs_m
                and scs_m["enabled"] is not None
                and not isinstance(scs_m["enabled"], bool)
            ):
                raise ValueError(
                    f"stale_code_selfheal.enabled must be a boolean: {scs_m['enabled']!r}"
                )
            if "idle_confirm_seconds" in scs_m and scs_m["idle_confirm_seconds"] is not None:
                _sv = scs_m["idle_confirm_seconds"]
                if isinstance(_sv, bool) or not isinstance(_sv, (int, float)) or _sv <= 0:
                    raise ValueError(
                        f"stale_code_selfheal.idle_confirm_seconds must be a positive "
                        f"integer: {_sv!r}"
                    )
    except ValueError as e:
        return fail(str(e))

    # 4. 原子写回（临时文件 + rename）
    config_dir.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(config_dir), prefix=".config-", suffix=".yaml.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_CONFIG_HEADER_COMMENT)
                yaml.safe_dump(
                    merged, f, allow_unicode=True, default_flow_style=False, sort_keys=False
                )
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        return fail(f"写入配置文件失败: {e}")

    return {"ok": True, "error": None, "scope": scope, "path": str(config_path)}


# ── 同步用户级设置到项目级（设置页项目级作用域「同步用户级设置」按钮） ──

# 页面标识 → 用户级 config.yaml 中被同步的受管键白名单。
# 键集与各设置页签 onSave 提交的 patch 键一一对应（「只覆盖当前页面的设置值」）：
# llm 页取 providers 整段；agents 页只取 models；parallel 页取并发三键 +
# verify.planner_max_concurrent；token 页取预算四键；verify 页取 static_scope/
# deps_mode；approval 页取 gates 两键；misc 页取 archive.auto_threshold；
# system 页取 admin.* 六键 + agents.transient_* 五键。
_SYNC_PAGE_KEYS = {
    "llm": {"llm": ["providers"]},
    "agents": {"agents": ["models"]},
    "parallel": {
        "agents": ["max_concurrent", "max_turns", "run_timeout_seconds"],
        "verify": ["planner_max_concurrent"],
    },
    "token": {
        "agents": [
            "token_budget_millions",
            "daily_run_limit",
            "impl_run_budget",
            "verify_redo_budget",
        ],
    },
    "verify": {"verify": ["static_scope", "deps_mode"]},
    "approval": {"gates": ["promote_mode", "approve_mode"]},
    "misc": {"archive": ["auto_threshold"]},
    "system": {
        "admin": [
            "enabled",
            "interval_minutes",
            "escalation_cooldown_minutes",
            "merge_breaker_threshold",
            "shutdown_drain_seconds",
            "bug_repair_mode",
            "stuck_silence_minutes",
        ],
        "agents": [
            "transient_backoff_schedule",
            "transient_redispatch_delay_seconds",
            "transient_break_threshold",
            "transient_break_window_seconds",
            "transient_break_cooldown_seconds",
        ],
    },
}


def sync_config_from_user(project_root, page: str) -> dict:
    """把用户级 config.yaml 中 page 页签对应的受管键覆盖写入项目级配置。

    以用户级文件原始值为 patch 源（read_config 的回显含缺省填充，会把用户级
    未显式配置的键也一并覆盖成缺省值），经 write_config 走完整的前置校验 +
    受管键合并 + 原子写盘——非受管键与其它页签的设置值不受影响。

    Args:
        project_root: 项目根路径
        page: 页面标识（_SYNC_PAGE_KEYS 键）

    Returns: {"ok": bool, "error": str|null, "synced": {...}|None, "path": str}
    """
    if page not in _SYNC_PAGE_KEYS:
        return {"ok": False, "error": f"未知页面标识: {page}", "synced": None, "path": None}

    # 读用户级原始文件（raw dict，不做缺省填充）：用户级未显式配置的键不覆盖
    import core.dashboard.data as _facade

    user_raw = {}
    if _facade.USER_CONFIG_PATH.exists():
        try:
            with _facade.USER_CONFIG_PATH.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                user_raw = loaded
        except (yaml.YAMLError, OSError) as e:
            return {
                "ok": False,
                "error": f"读取用户级配置失败: {e}",
                "synced": None,
                "path": str(_facade.USER_CONFIG_PATH),
            }

    section_map = _SYNC_PAGE_KEYS[page]
    patch = {}
    for section, keys in section_map.items():
        sec_raw = user_raw.get(section)
        if not isinstance(sec_raw, dict):
            continue  # 用户级未配置该段：本页无可同步值，跳过（不写空覆盖）
        picked = {k: sec_raw[k] for k in keys if k in sec_raw}
        if picked:
            patch[section] = picked

    if not patch:
        return {
            "ok": False,
            "error": "用户级配置中该页面没有已设置的值，无可同步内容",
            "synced": None,
            "path": str(_facade.USER_CONFIG_PATH),
        }

    result = write_config(project_root, patch, scope="project")
    return {
        "ok": result["ok"],
        "error": result.get("error"),
        "synced": patch if result["ok"] else None,
        "path": result.get("path"),
    }
