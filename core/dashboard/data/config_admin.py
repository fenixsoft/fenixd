"""core.dashboard.data.config_admin — 配置读写引擎（config_admin 组）。

refactor-dashboard-data-module D3 分组：本模块承载配置读写职责域。
受管键白名单、read_config/read_effective_config/write_config/sync_config_from_user。
USER_CONFIG_PATH 按 D8 留在门面绑定，本模块内经门面解析。
"""

import copy
import os
import tempfile
import threading
from pathlib import Path

import yaml

from core.pm_engine.budget import DEFAULT_IMPL_RUN_BUDGET

# ── 配置读写（受管键：llm / agents.* / gates.approve_mode / verify.*） ──

# Dashboard 受管键的历史门面常量（code-review item f37ddee25a11 更正注释）：
# 下行「写回时只更新这些键」描述的是旧写回机制；现行 write_config 经
# _deep_merge_managed 的显式合并分支白名单写回，受管键集的权威来源是
# _SOURCE_KEYS 与 _SYNC_PAGE_KEYS——knowledge / worktree / admin /
# stale_code_selfheal / self_evolution 等后增受管段均不在本列表内。
# 本常量如今仅作 data/__init__ 再导出与契约测试锚点保留，改此列表
# 并不会放开写回（勿据其判断写回范围）。
_MANAGED_KEYS = ["llm", "agents", "gates", "verify", "hooks"]

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
    # open-impl-budget-ceiling：实现尝试预算上限（与 _AGENTS_SOURCE_KEYS 同键
    # 双登记——后者只管回显与 project 标注，缺此处的 user 缺省登记则未配置时
    # sources 缺键，来源徽标拿到 undefined）
    "agents.impl_run_budget_max",
    "agents.verify_redo_budget",
    # 同因重派熔断阈值（agents.max_same_cause_redispatches）
    "agents.max_same_cause_redispatches",
    # 规模预检三键（agents.scale_precheck.*）
    "agents.scale_precheck",
    # supervision-timeout-config-consistency：超时监督段（agents.timeout_supervision）
    "agents.timeout_supervision",
    "gates.approve_mode",
    # add-draft-promotion-gate：草稿晋升模式
    "gates.promote_mode",
    # add-spec-review-gate：方案评审模式
    "gates.spec_review_mode",
    # add-start-after-scope-config：start_after 门控覆盖范围
    "gates.start_after_scope",
    # add-daily-self-review：admin.self_review 三键
    "admin.self_review",
    # add-code-review-agent-and-quality-tab：admin.code_review 两键（周期代码审查）
    "admin.code_review",
    # add-code-review-auto-fix：admin.code_review_fix 两键（自动修复车道）
    "admin.code_review_fix",
    # add-test-regression-tab：admin.regression 键（周期全量回归开关）
    "admin.regression",
    # add-settings-system-tab：admin.* 受管键全部
    "admin.enabled",
    "admin.interval_minutes",
    "admin.escalation_cooldown_minutes",
    "admin.merge_breaker_threshold",
    "admin.shutdown_drain_seconds",
    # add-bug-repair-mode-config：bug-found 修复方式（inplace/derive）
    "admin.bug_repair_mode",
    # stuck-signal-hygiene D4：stuck 处置后静默期（分钟）
    "admin.stuck_silence_minutes",
    # add-adjudication-alert-narrative：转人工裁决告警三段式叙事三键
    "admin.narrative_enabled",
    "admin.narrative_timeout_seconds",
    "admin.narrative_model",
    # add-alert-self-heal-marking 5.2：告警自愈安静窗口（分钟）
    "admin.self_heal_quiet_minutes",
    "verify.static_scope",
    "verify.deps_mode",
    # add-impl-code-review-gate：实现阶段末尾代码质量审查开关
    "verify.impl_code_review",
    # add-impl-code-review-tuning：收尾审查三运行参数（超时秒/并发/力度，
    # 缺省 600/2/low，与 ConfigLoader 三读取器缺省同源）
    "verify.impl_code_review_timeout_sec",
    "verify.impl_code_review_concurrency",
    # add-code-review-concurrency-and-429-resilience：全仓审查并发
    # （manual_full/manual_window/scheduled 的子代理扇出 + ocr scan --concurrency）
    "verify.repo_code_review_concurrency",
    "verify.impl_code_review_effort",
    # add-impl-ocr-parallel-lane：join 裁决双档模式（gate/advisory）
    "verify.impl_code_review_mode",
    # add-impl-ocr-parallel-lane（ocr 审查 finding#1 补纳管）：ocr 车道级硬超时
    # （秒，缺省 2400，消费方 run_impl_ocr；与单请求超时 timeout_sec 按键分离）
    "verify.impl_code_review_lane_timeout_sec",
    # fix-agent-lane-efficiency D3：上下文经济性诊断告警阈值
    "verify.context_cost_per_turn_threshold",
    "verify.serving_reclaim.enabled",
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
    # fix-agent-lane-efficiency D1：子代理模型覆盖键（设置页「模型」面板可编辑）
    "agents.subagent_model_override",
    # add-stale-code-selfheal：陈旧自愈配置节两键
    "stale_code_selfheal.enabled",
    "stale_code_selfheal.idle_confirm_seconds",
    # add-framework-self-evolution：self_evolution 全局（用户级）三键
    "self_evolution.auto_accept",
    "self_evolution.max_items_per_run",
    "self_evolution.spec_run_at",
    # evo-merge-back-wip-artifact-scope：构建产物路径键（项目级可编辑；
    # 不含 _SYNC_PAGE_KEYS——不参与用户级同步写入）
    "worktree.build_artifact_paths",
    # fix-artifact-paths-hardcoded-default D4：项目是否存在构建产物（三态，
    # 缺省 None=未裁决 / false=已声明无产物 / true=按路径判定）
    "worktree.has_build_artifacts",
    # add-knowledge-atlas：知识真相源总开关（设置页「杂项」页签可编辑）
    "knowledge.enabled",
    # add-knowledge-atlas-maintenance：知识真相源维护车道键（设置页「杂项」页签可编辑；
    # graph_enabled 已随 graphify 功能取消下线，不再受管——存量键被静默忽略）
    "knowledge.audit_enabled",
]

# 受管 agents 标量键（来源标注 + 回显共用；配置键新条目在此登记一次即可
# 同时获得来源标注与数值回显，压缩 read_config/read_effective_config 的逐键块）。
_AGENTS_SOURCE_KEYS = (
    "max_concurrent",
    "run_timeout_seconds",
    "max_turns",
    "daily_run_limit",
    "token_budget_millions",
    "impl_run_budget",
    # open-impl-budget-ceiling：实现尝试预算上限（1-1000；设置页 TokenBudgetPanel
    # 提交该键，缺此分支会被 _deep_merge_managed 静默丢弃且回显缺失弹回缺省 100）
    "impl_run_budget_max",
    "verify_redo_budget",
    # 同因重派熔断阈值（回显经归一化覆盖，非法回退缺省 3）
    "max_same_cause_redispatches",
)
# 合并写回键（数值标量透传；与来源键同集合）
_AGENTS_MERGE_KEYS = _AGENTS_SOURCE_KEYS

def _is_int_not_bool(v) -> bool:
    """数值标量校验助手：仅接受真 int。

    Python 中 bool 是 int 子类，isinstance(True, int) 为 True——不排除的话
    PATCH {"agents": {"max_concurrent": true}} 之类布尔值会通过校验落盘、
    回显时也被当 int 显示。与 impl_run_budget_max / merge_breaker_threshold
    等键的 isinstance(x, bool) 显式排除同款防护。
    """
    return isinstance(v, int) and not isinstance(v, bool)

def _echo_agents_int_keys(agents_src) -> dict:
    """回显 agents 数值标量键（仅真 int 值回显，缺省/非法由缺省 dict 兜底）。"""
    out = {}
    if isinstance(agents_src, dict):
        for k in _AGENTS_SOURCE_KEYS:
            if _is_int_not_bool(agents_src.get(k)):
                out[k] = agents_src[k]
    return out


def _echo_agents_str_key(agents_src, key: str) -> str:
    """回显 agents 字符串标量键（subagent_model_override：仅 str 值回显，缺省空串）。

    fix-agent-lane-efficiency D1：子代理模型覆盖键为字符串（模型名），
    非法类型（非 str）视为未配置 → 回显空串（语义 = 使用 provider model）。
    """
    if isinstance(agents_src, dict):
        val = agents_src.get(key)
        if isinstance(val, str):
            return val.strip()
    return ""

# 受管键的默认回显值（add-daily-self-review；与 ConfigLoader.get_self_review_config
# 保持一致：enabled/read_todo 缺省 false，run_at 缺省 02:00）
_DEFAULT_SELF_REVIEW = {"enabled": False, "run_at": "02:00", "read_todo": False}
# add-code-review-agent-and-quality-tab：admin.code_review 缺省（与
# ConfigLoader.get_code_review_config 一致：enabled 缺省 false，max_files 缺省 500，
# scope 缺省 window——add-code-review-scope-config；stall_alert_minutes 缺省 15
# ——add-code-review-sharded-out 停滞告警阈值）
_DEFAULT_CODE_REVIEW = {
    "enabled": False,
    "max_files": 500,
    "scope": "window",
    "stall_alert_minutes": 15,
    # add-code-review-run-at 4.1：触发时点缺省回显生效值——缺省回退自省
    # run_at（单源 _DEFAULT_SELF_REVIEW，与 ConfigLoader.get_code_review_config
    # 回退口径一致，read 路径经该助手归一化同值）
    "run_at": _DEFAULT_SELF_REVIEW["run_at"],
}
# add-code-review-auto-fix：admin.code_review_fix 缺省（与
# ConfigLoader.get_code_review_fix_config 一致：enabled 缺省 false，
# batch_size 缺省 20；targeted_retry_max 缺省 3，add-codefix-targeted-retry；
# targeted_regression 缺省 True，add-codefix-affinity-batching）
_DEFAULT_CODE_REVIEW_FIX = {
    "enabled": False,
    "batch_size": 20,
    "targeted_retry_max": 3,
    "targeted_regression": True,
}
# add-test-regression-tab：admin.regression 缺省（与 ConfigLoader.get_regression_config
# 一致：enabled 缺省 false——周期全量回归开关缺省关闭零动作）
_DEFAULT_REGRESSION = {"enabled": False}

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
        for _ak in _AGENTS_SOURCE_KEYS:
            if _ak in agents_raw:
                sources[f"agents.{_ak}"] = "project"
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
        # supervision-timeout-config-consistency：超时监督段显式定义 → project
        # （映射段，isinstance 判定对齐 agents.models 同款）
        if isinstance(agents_raw.get("timeout_supervision"), dict):
            sources["agents.timeout_supervision"] = "project"
        # code-review item 96df8344d8ff：scale_precheck（映射段，isinstance 判定
        # 对齐 timeout_supervision 同款）与 subagent_model_override（str 存在性
        # 判定，None=未配置不标；空串是合法显式值=回落 provider model）缺标注
        # 分支——项目级显式配置后 sources 仍回 "user"，徽标恒错
        if isinstance(agents_raw.get("scale_precheck"), dict):
            sources["agents.scale_precheck"] = "project"
        if isinstance(agents_raw.get("subagent_model_override"), str):
            sources["agents.subagent_model_override"] = "project"
    gates_raw = raw.get("gates")
    if isinstance(gates_raw, dict) and "approve_mode" in gates_raw:
        sources["gates.approve_mode"] = "project"
    # add-draft-promotion-gate：草稿晋升模式显式定义 → project
    if isinstance(gates_raw, dict) and "promote_mode" in gates_raw:
        sources["gates.promote_mode"] = "project"
    # add-spec-review-gate：方案评审模式显式定义 → project
    if isinstance(gates_raw, dict) and "spec_review_mode" in gates_raw:
        sources["gates.spec_review_mode"] = "project"
    # add-start-after-scope-config：start_after 门控覆盖范围（full/dispatch）
    if isinstance(gates_raw, dict) and gates_raw.get("start_after_scope") in ("full", "dispatch"):
        sources["gates.start_after_scope"] = "project"
    verify_src = raw.get("verify")
    if isinstance(verify_src, dict):
        if "static_scope" in verify_src:
            sources["verify.static_scope"] = "project"
        if "deps_mode" in verify_src:
            sources["verify.deps_mode"] = "project"
        if "planner_max_concurrent" in verify_src:
            sources["verify.planner_max_concurrent"] = "project"
        # add-impl-code-review-gate：严格 bool 才标注 project（缺省/非法不标）
        if isinstance(verify_src.get("impl_code_review"), bool):
            sources["verify.impl_code_review"] = "project"
        # add-impl-code-review-tuning：三运行参数严格类型判定才标注 project
        # （正整数/枚举，缺省/非法不标——与 impl_code_review bool 同款）
        if isinstance(verify_src.get("impl_code_review_timeout_sec"), int) and \
                not isinstance(verify_src.get("impl_code_review_timeout_sec"), bool):
            if verify_src["impl_code_review_timeout_sec"] > 0:
                sources["verify.impl_code_review_timeout_sec"] = "project"
        if isinstance(verify_src.get("impl_code_review_concurrency"), int) and \
                not isinstance(verify_src.get("impl_code_review_concurrency"), bool):
            if verify_src["impl_code_review_concurrency"] > 0:
                sources["verify.impl_code_review_concurrency"] = "project"
        # add-code-review-concurrency-and-429-resilience：全仓审查并发同款
        # 来源标注（正整数才标注 project，缺省/非法不标）
        if isinstance(verify_src.get("repo_code_review_concurrency"), int) and \
                not isinstance(verify_src.get("repo_code_review_concurrency"), bool):
            if verify_src["repo_code_review_concurrency"] > 0:
                sources["verify.repo_code_review_concurrency"] = "project"
        if verify_src.get("impl_code_review_effort") in ("low", "medium", "high"):
            sources["verify.impl_code_review_effort"] = "project"
        # add-impl-ocr-parallel-lane：mode 枚举合法值才标注 project（缺省/非法不标）
        if verify_src.get("impl_code_review_mode") in ("gate", "advisory"):
            sources["verify.impl_code_review_mode"] = "project"
        # ocr 审查 finding#1：lane_timeout 正整数才标注 project（与 timeout_sec 同款）
        if isinstance(verify_src.get("impl_code_review_lane_timeout_sec"), int) and \
                not isinstance(verify_src.get("impl_code_review_lane_timeout_sec"), bool):
            if verify_src["impl_code_review_lane_timeout_sec"] > 0:
                sources["verify.impl_code_review_lane_timeout_sec"] = "project"
        sr_raw = verify_src.get("serving_reclaim")
        if isinstance(sr_raw, dict) and "enabled" in sr_raw:
            sources["verify.serving_reclaim.enabled"] = "project"
        # code-review item 96df8344d8ff：上下文经济性告警阈值显式定义 → project
        # （非负整数才标注，0=关闭告警是合法显式值——与读回显/合并分支/写校验
        # 同域；按正整数判定会把显式 0 误标回 "user"）
        _cct_src = verify_src.get("context_cost_per_turn_threshold")
        if isinstance(_cct_src, int) and not isinstance(_cct_src, bool) and _cct_src >= 0:
            sources["verify.context_cost_per_turn_threshold"] = "project"
    # add-daily-self-review：admin.self_review 段显式定义 → project
    admin_raw = raw.get("admin")
    if isinstance(admin_raw, dict) and isinstance(admin_raw.get("self_review"), dict):
        sources["admin.self_review"] = "project"
    # add-code-review-agent-and-quality-tab：admin.code_review 段显式定义 → project
    if isinstance(admin_raw, dict) and isinstance(admin_raw.get("code_review"), dict):
        sources["admin.code_review"] = "project"
    # add-code-review-auto-fix：admin.code_review_fix 段显式定义 → project
    if isinstance(admin_raw, dict) and isinstance(admin_raw.get("code_review_fix"), dict):
        sources["admin.code_review_fix"] = "project"
    # add-test-regression-tab：admin.regression 段显式定义 → project
    if isinstance(admin_raw, dict) and isinstance(admin_raw.get("regression"), dict):
        sources["admin.regression"] = "project"
    # add-settings-system-tab：admin.* 受管键显式定义 → project
    if isinstance(admin_raw, dict):
        for _k in (
            "enabled",
            "interval_minutes",
            "escalation_cooldown_minutes",
            "merge_breaker_threshold",
            "shutdown_drain_seconds",
            "bug_repair_mode",
            "stuck_silence_minutes",
            # code-review item 7d53f7fb5c7a：叙事三键与 _SOURCE_KEYS /
            # _SYNC_PAGE_KEYS（system 页）登记对齐——缺此三键时项目级显式配置后
            # sources 仍回 "user"，设置页「继承自用户级」徽标恒错
            "narrative_enabled",
            "narrative_timeout_seconds",
            "narrative_model",
            # add-alert-self-heal-marking 5.2：来源标注三键对齐（缺此键时项目级
            # 显式配置后 sources 仍回 "user"，设置页徽标恒错）
            "self_heal_quiet_minutes",
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
    # evo-merge-back-wip-artifact-scope / fix-artifact-paths-hardcoded-default：
    # worktree 段显式定义 → project（两键各判一次，存在性判定不可用 or/in 合并）
    wm_raw = raw.get("worktree")
    if isinstance(wm_raw, dict) and "build_artifact_paths" in wm_raw:
        sources["worktree.build_artifact_paths"] = "project"
    if isinstance(wm_raw, dict) and "has_build_artifacts" in wm_raw:
        sources["worktree.has_build_artifacts"] = "project"
    # add-knowledge-atlas(-maintenance)：knowledge 两键存在性判定 → project
    # （code-review item 84c86642e5c9：缺标注分支——项目级显式配置后 sources
    # 仍回 "user"，设置页「杂项」页签徽标恒错；对齐 worktree 两键同款写法）
    kn_raw = raw.get("knowledge")
    if isinstance(kn_raw, dict):
        if "enabled" in kn_raw:
            sources["knowledge.enabled"] = "project"
        if "audit_enabled" in kn_raw:
            sources["knowledge.audit_enabled"] = "project"
    return sources


# add-settings-system-tab：受管 admin.* 键缺省（与 ConfigLoader.get_admin_config
# 一致：enabled/interval/escalation/merge_breaker/shutdown/bug_repair_mode）
_ADMIN_DEFAULTS = {
    "enabled": True,
    "interval_minutes": 5,
    "escalation_cooldown_minutes": 60,
    "shutdown_drain_seconds": 1800,
    "bug_repair_mode": "inplace",
    # stuck-signal-hygiene D4：stuck 处置后静默期（分钟，缺省 120，
    # 与 ConfigLoader.get_admin_config 缺省一致）
    "stuck_silence_minutes": 120,
    # add-adjudication-alert-narrative：叙事三键缺省（与
    # ConfigLoader.get_admin_config / config.template.yaml 同源）
    "narrative_enabled": True,
    "narrative_timeout_seconds": 60,
    "narrative_model": "",
    # add-alert-self-heal-marking 5.2：自愈安静窗口缺省（与
    # ConfigLoader.get_admin_config / config.template.yaml 同源 1440）
    "self_heal_quiet_minutes": 1440,
}

def _managed_admin_keys(config: dict) -> dict:
    """受管 admin.* 键提取：全部受管键 + 缺省填充，不透传未知 admin 键/self_review 子段。

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
        if key in ("enabled", "narrative_enabled"):
            # 严格 bool 回显：非 bool 回退缺省（narrative_enabled 缺省 True）
            out[key] = val if isinstance(val, bool) else default
        elif key == "bug_repair_mode":
            # 字符串枚举：仅 inplace/derive 回显，非法/非字符串回退缺省
            out[key] = val if val in ("inplace", "derive") else default
        elif key == "narrative_model":
            # add-adjudication-alert-narrative：字符串键回显（空串=回退链，
            # 合法值照原样回显），非字符串回退缺省 ""
            out[key] = val if isinstance(val, str) else default
        else:
            # 数值键：非数值/布尔一律回退缺省（写路径校验保证合法值才能落盘）
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                val = default
            out[key] = val
    return out

def _default_echo_view(scope: str) -> dict:
    """read_config / read_effective_config 共用的缺省回显视图（单源）。

    两函数的缺省 result 块曾整块手工镜像，已两次实际漂移（impl_run_budget
    手写字面量 2→4；self_evolution.spec_run_at 单侧缺失，导致
    read_effective_config 的 resolve_config 异常早退路径返回形状少键）。
    抽此单源杜绝再漂移：以含 spec_run_at 的超集为基准；scope 原样落
    result["scope"]，raw_exists 恒缺省 False（read_effective_config 按项目
    文件存在性自行覆写）。
    """
    # 缺省回显块经读取器取缺省（单一天然来源，见 verify 块注释）
    from core.config import ConfigLoader as _CLICRT

    return {
        "llm": {},
        "agents": {
            "models": {},
            "max_concurrent": 2,
            "run_timeout_seconds": 9000,
            "max_turns": 400,
            "daily_run_limit": 50,
            "token_budget_millions": 50,
            # 回显缺省与运行时单源（code-review item 3ee9a4e0d218）：取
            # DEFAULT_IMPL_RUN_BUDGET，勿再手写字面量（曾与运行时 6 漂移为 4）
            "impl_run_budget": DEFAULT_IMPL_RUN_BUDGET,
            "verify_redo_budget": 3,
            "max_same_cause_redispatches": 3,
            # fix-agent-lane-efficiency D1：子代理模型覆盖（缺省空串 = 用 provider model）
            "subagent_model_override": "",
        },
        "gates": {"approve_mode": "manual", "promote_mode": "auto", "spec_review_mode": "auto", "start_after_scope": "dispatch"},
        "verify": {"static_scope": "main", "deps_mode": "hardlink", "serving_reclaim": {"enabled": True},
                   # add-impl-code-review-tuning：三运行参数恒回显缺省（与
                   # impl_code_review「缺省不回显」语义相反，spec「缺省回显」
                   # Scenario）。缺省值经 ConfigLoader 读取器取（传空配置即回
                   # 缺省）——单一来源，杜绝手工字面量镜像漂移（ocr 审查
                   # finding#2；保存时会把回显值显式落盘，镜像停在旧值会压过
                   # 新缺省，本次 2→4 已实际踩中）
                   "impl_code_review_timeout_sec": _CLICRT.get_impl_code_review_timeout_sec({}),
                   "impl_code_review_concurrency": _CLICRT.get_impl_code_review_concurrency({}),
                   # add-code-review-concurrency-and-429-resilience：全仓审查并发
                   # 缺省恒回显（与三运行参数「缺省回显」同款语义）
                   "repo_code_review_concurrency": _CLICRT.get_repo_code_review_concurrency({}),
                   "impl_code_review_effort": _CLICRT.get_impl_code_review_effort({}),
                   # add-impl-ocr-parallel-lane：join 双档模式恒回显缺省（gate——
                   # 与上方三运行参数「缺省回显」同款语义）
                   "impl_code_review_mode": _CLICRT.get_impl_code_review_mode({}),
                   # ocr 审查 finding#1：车道级硬超时同样纳入缺省回显（2400）
                   "impl_code_review_lane_timeout_sec": _CLICRT.get_impl_code_review_lane_timeout_sec({}),
                   # fix-agent-lane-efficiency D3：上下文经济性告警阈值（0=关闭）
                   "context_cost_per_turn_threshold": 200000},
        # add-spec-archive D5：自动归档阈值（0 = 禁用，默认 50）
        "archive": {"auto_threshold": 50},
        # add-knowledge-atlas：知识真相源总开关（缺省 true，与 ConfigLoader 缺省
        # 同步）；add-knowledge-atlas-maintenance：维护车道键同节缺省
        "knowledge": {"enabled": True, "audit_enabled": True},
        # add-daily-self-review：admin.self_review 三键（缺省 false/false/02:00）
        "self_review": dict(_DEFAULT_SELF_REVIEW),
        # add-code-review-agent-and-quality-tab：admin.code_review 两键（缺省 false/500）
        "code_review": dict(_DEFAULT_CODE_REVIEW),
        # add-code-review-auto-fix：admin.code_review_fix 两键（缺省 false/20）
        "code_review_fix": dict(_DEFAULT_CODE_REVIEW_FIX),
        # add-test-regression-tab：admin.regression 键（缺省 false，周期全量回归开关）
        "regression": dict(_DEFAULT_REGRESSION),
        # add-settings-system-tab：admin.* 受管键全部（含缺省填充）
        "admin": dict(_ADMIN_DEFAULTS, merge_breaker_threshold=2),
        # add-spec-hooks：两级 hook 订阅配置（缺省空订阅，零行为）
        "hooks": {"global": [], "specs": {}},
        # add-stale-code-selfheal：陈旧自愈配置节（enabled 缺省 true /
        # idle_confirm_seconds 缺省 600，evo-reduce-stale-code-selfheal-noise
        # 2.4——与 ConfigLoader 缺省同步，避免设置页以旧值回填表单、用户保存即
        # 把旧缺省显式写入项目配置、静默覆盖新缺省）
        "stale_code_selfheal": {"enabled": True, "idle_confirm_seconds": 600},
        # add-framework-self-evolution：self_evolution 三键（缺省 auto_accept=false /
        # max_items_per_run=20 / spec_run_at=null 立即执行；code-review item
        # 42b017717b1e：两读路径统一含 spec_run_at，早退路径形状不缺键）
        "self_evolution": {"auto_accept": False, "max_items_per_run": 20, "spec_run_at": None},
        # evo-merge-back-wip-artifact-scope / fix-artifact-paths-hardcoded-default：
        # worktree 产物键缺省（空列表=未配置；has_build_artifacts 缺省 None=未裁决）
        "worktree": {"build_artifact_paths": [], "has_build_artifacts": None},
        "scope": scope,
        "raw_exists": False,
        # code-review item 7e414f8f4485：description 顶层缺省键——正常路径由
        # project.description 提取填充（非 str/缺失 → ""），缺省置空串保证
        # resolve_config 异常早退路径返回形状与正常路径一致
        "description": "",
        "sources": _managed_key_sources({}),
        "error": None,
    }

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
    # 缺省回显块单源（code-review item 42b017717b1e）：与 read_effective_config
    # 共用 _default_echo_view，杜绝手工镜像漂移（self_evolution.spec_run_at
    # 曾单侧漂移）
    result = _default_echo_view(scope)
    if scope == "user":
        result["sources"] = {k: "user" for k in _SOURCE_KEYS}
    if not config_path.exists():
        return result
    result["raw_exists"] = True
    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        # UnicodeDecodeError：PyYAML 对已解码 str 流不包装异常，文件为非 UTF8
        # 编码（如 GBK）时 stream.read() 抛出——既非 YAMLError 也非 OSError，
        # 缺则逃出 except 直达 HTTP 层成 500（code-review item eeec7a6f3ff5）
        result["error"] = f"配置文件解析失败: {e}"
        return result
    if not isinstance(raw, dict):
        result["error"] = "配置文件顶层不是对象"
        return result

    if scope == "project":
        result["sources"] = _managed_key_sources(raw)

    # 提取受管键（白名单：llm / agents.models / agents.max_concurrent / gates.approve_mode）
    # [fenix-ignore:6032b09cf68a] apikey 掩码需配对写侧 mask-keep，而 llm 为整段替换写入且生效视图跨 user/project 作用域（哨兵落盘毁配置或跨作用域复制密钥），属成面改动不实施
    if isinstance(raw.get("llm"), dict):
        result["llm"] = raw["llm"]
    agents_raw = raw.get("agents")
    if isinstance(agents_raw, dict):
        agents_result = {}
        if isinstance(agents_raw.get("models"), dict):
            # improve-failover-model-mapping-ui（D4）：规范化 models 为 Dashboard
            # 回显视图（str/list/对象统一为对象数组 + resolved model）
            from core.config import ConfigLoader as _CL

            llm_raw = raw.get("llm")
            llm_providers = (
                (llm_raw.get("providers") or []) if isinstance(llm_raw, dict) else []
            )
            agents_result["models"] = _CL.normalize_agent_models(
                agents_raw["models"], llm_providers
            )
        agents_result.update(_echo_agents_int_keys(agents_raw))
        # fix-agent-lane-efficiency D1：子代理模型覆盖键回显（str 才回显，缺省空串）
        agents_result["subagent_model_override"] = _echo_agents_str_key(
            agents_raw, "subagent_model_override"
        )
        # 同因重派熔断阈值回显（agents.max_same_cause_redispatches）——经
        # ConfigLoader 单点归一化（正整数 1–100，非法回退缺省 3）
        from core.config import ConfigLoader as _CLMSC

        agents_result["max_same_cause_redispatches"] = _CLMSC.get_max_same_cause_redispatches(raw)
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
        # 规模预检三键回显（agents.scale_precheck，缺省填充 + 非法值回退同读侧归一化）
        from core.fast_track_result import get_scale_precheck_config as _get_sp

        agents_result["scale_precheck"] = _get_sp(raw)
        # code-review item d73ee0a33fbe：本分支内 subagent_model_override 等键
        # 无条件写入，agents_result 必非空（原恒真守卫已删）；逐键覆盖默认，
        # 避免整段替换清空默认值
        for k, v in agents_result.items():
            result["agents"][k] = v
    gates_raw = raw.get("gates")
    # code-review item 775c04d26905：合法枚举才回显（非法值留空由缺省段 manual
    # 兜底，与运行时 get_approve_mode 回退 manual 口径一致；对齐同段 promote_mode
    # / spec_review_mode / start_after_scope 的过滤写法），杜绝手工脏值直显。
    # 枚举集与 write_config 校验同源（ConfigLoader.VALID_APPROVE_MODES）。
    from core.config import ConfigLoader as _CLAM

    if isinstance(gates_raw, dict) and gates_raw.get("approve_mode") in _CLAM.VALID_APPROVE_MODES:
        # add-start-after-scope-config 3.2：MUST NOT 整段替换 result["gates"]
        # ——项目级显式配置 approve_mode 时其余 gates 键（promote_mode /
        # spec_review_mode / start_after_scope）会在此分支后被丢弃（实测复现）。
        # 改为单键赋值，保留其余键（对齐其余分支写法）。
        result.setdefault("gates", {})["approve_mode"] = gates_raw["approve_mode"]
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
    # add-start-after-scope-config：start_after_scope 提取（合法枚举才回显，
    # 非法留空由读侧缺省兜底，对齐 spec_review_mode 写法）
    if isinstance(gates_raw, dict) and gates_raw.get("start_after_scope") in ("full", "dispatch"):
        if "gates" not in result:
            result["gates"] = {}
        result["gates"]["start_after_scope"] = gates_raw["start_after_scope"]
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
        # add-impl-code-review-gate：严格 bool 才回显，缺省不填充（与
        # planner_max_concurrent「缺省不回显」同款，不破坏既有严格相等断言）
        if isinstance(verify_raw.get("impl_code_review"), bool):
            result["verify"]["impl_code_review"] = verify_raw["impl_code_review"]
        # add-impl-code-review-tuning：三运行参数恒回显——缺省段已含 600/2/low，
        # 此处读回显式定义值覆盖（读取器对非法值回退缺省，回显与生效值一致；
        # 与 impl_code_review「缺省不回显」语义相反，spec「缺省回显」Scenario）
        from core.config import ConfigLoader as _CLICRT

        result["verify"]["impl_code_review_timeout_sec"] = (
            _CLICRT.get_impl_code_review_timeout_sec(raw)
        )
        result["verify"]["impl_code_review_concurrency"] = (
            _CLICRT.get_impl_code_review_concurrency(raw)
        )
        # add-code-review-concurrency-and-429-resilience：全仓审查并发生效值回显
        result["verify"]["repo_code_review_concurrency"] = (
            _CLICRT.get_repo_code_review_concurrency(raw)
        )
        result["verify"]["impl_code_review_effort"] = (
            _CLICRT.get_impl_code_review_effort(raw)
        )
        # add-impl-ocr-parallel-lane：join 双档模式生效值回显（读取器对非法值
        # 回退缺省 gate，回显与生效值一致；与三运行参数「缺省回显」同款）
        result["verify"]["impl_code_review_mode"] = (
            _CLICRT.get_impl_code_review_mode(raw)
        )
        # ocr 审查 finding#1：车道级硬超时生效值回显（读取器对非法值回退
        # 缺省 2400，与 timeout_sec 同款正整数语义）
        result["verify"]["impl_code_review_lane_timeout_sec"] = (
            _CLICRT.get_impl_code_review_lane_timeout_sec(raw)
        )
        # fix-agent-lane-efficiency D3：上下文经济性告警阈值回显（正整数才回显，
        # 缺省 200000 由缺省段兜底；0 = 关闭告警）
        _cct = verify_raw.get("context_cost_per_turn_threshold")
        if isinstance(_cct, int) and not isinstance(_cct, bool) and _cct >= 0:
            result["verify"]["context_cost_per_turn_threshold"] = _cct
        sr_raw = verify_raw.get("serving_reclaim")
        if isinstance(sr_raw, dict) and isinstance(sr_raw.get("enabled"), bool):
            result["verify"]["serving_reclaim"]["enabled"] = sr_raw["enabled"]
    archive_raw = raw.get("archive")
    if isinstance(archive_raw, dict):
        from core.config import ConfigLoader as _CL

        result["archive"] = {"auto_threshold": _CL.effective_auto_archive_threshold(raw)}
    # add-knowledge-atlas：knowledge 段回显（段在文件中显式出现才覆盖缺省，
    # 与 archive 同型——避免未配置段以回显形态伪装成已配置）；合并后段内键
    # 共存（enabled 蒸馏总开关 + audit_enabled 维护车道），
    # 各经生效助手归一（非法值回落缺省）
    if isinstance(raw.get("knowledge"), dict):
        from core.config import ConfigLoader as _CLK

        result["knowledge"] = {
            **_CLK.get_knowledge_lane_config(raw),
            **_CLK.get_knowledge_config(raw),
        }
    # add-daily-self-review：admin.self_review 三键（经 ConfigLoader 生效值回显）
    admin_raw = raw.get("admin")
    if isinstance(admin_raw, dict):
        from core.config import ConfigLoader as _CL

        result["self_review"] = _CL.get_self_review_config(raw)
        # add-code-review-agent-and-quality-tab：admin.code_review 两键
        # （经 ConfigLoader 生效值回显，与 self_review 同形态：顶层独立子键、
        # 不进 _managed_admin_keys 键集）
        result["code_review"] = _CL.get_code_review_config(raw)
        # add-code-review-auto-fix：admin.code_review_fix 两键（经 ConfigLoader
        # 生效值回显，与 code_review 同形态：顶层独立子键）
        result["code_review_fix"] = _CL.get_code_review_fix_config(raw)
        # add-test-regression-tab：admin.regression 键（经 ConfigLoader 生效值
        # 回显，与 code_review 同形态：顶层独立子键、不进 _managed_admin_keys
        # 键集——未知 admin 键由白名单狭窄回显，读不懂写入值）
        result["regression"] = _CL.get_regression_config(raw)
        # add-settings-system-tab：受管 admin 键提取（含缺省填充，不透传未知键）
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
    # evo-merge-back-wip-artifact-scope：产物路径回显（worktree_config_view，
    # 非法形态回显空列表 = 未配置，与解析侧 fail-safe 一致）
    from core.worktree_manager.artifact_paths import worktree_config_view as _wtcv

    result["worktree"] = _wtcv(raw)
    return result


# 配置解析签名缓存（dashboard-spec-summary-index D4）：read_effective_config
# 按 (项目根路径, 用户级签名, 项目级签名) 缓存，签名为 (mtime_ns, size)；
# 写后自然失效。
_EFFECTIVE_CONFIG_CACHE: dict = {}
_EFFECTIVE_CONFIG_CACHE_MAX = 512

def _config_file_sig(path: Path):
    """配置文件签名 (mtime_ns, size)；缺失返回 None。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


# 公开访问面（code-review item 5d821006cf18）：summary.py 跨组引用改用公开名，
# 与 _config_file_sig 同一函数对象单源绑定。
config_file_sig = _config_file_sig

def read_effective_config(project_root) -> dict:
    """项目模式有效配置视图：受管键取 resolve_config 有效合并值 + sources 标注。

    返回: {"llm": {...}, "agents": {"models": {...}, "max_concurrent": int},
            "gates": {"approve_mode": ...}, "scope": "project", "raw_exists": bool,
            "sources": {...}, "error": str|null, "description": str}
    sources[key] = "project" 当该键在项目级文件显式定义，否则 "user"（继承用户级或默认）。

    配置解析缓存（D4）：以 (项目根路径, 用户级 config.yaml 签名, 项目级
    config.yaml 签名) 为键缓存解析结果（签名为 (mtime_ns, size)，路径维度
    防不同项目同签名撞键）；命中直接返回深拷贝，不重读文件。
    """
    from core.config import ConfigLoader

    proot = Path(project_root)
    proj_path = proot / ".fenix" / "config.yaml"

    import core.dashboard.data as _facade

    # 键含项目根路径（code-review item 8f604abe8377）：仅签名会撞键——不同项目
    # config.yaml 保留 mtime 复制后签名相同即互相串用缓存视图。
    cache_key = (str(proot), _config_file_sig(_facade.USER_CONFIG_PATH), _config_file_sig(proj_path))
    cached = _EFFECTIVE_CONFIG_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    # 缺省回显块单源（code-review item 42b017717b1e）：与 read_config 共用
    # _default_echo_view——含 self_evolution.spec_run_at 超集，resolve_config
    # 异常早退路径的返回形状与正常路径/项目级读路径一致；raw_exists 按项目
    # 文件存在性覆写（本函数语义）。
    result = _default_echo_view("project")
    result["raw_exists"] = proj_path.exists()

    # 项目级文件显式定义 → sources 标注；解析失败记录 error 不阻断合并视图
    if proj_path.exists():
        try:
            with proj_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                result["sources"] = _managed_key_sources(loaded)
            else:
                result["error"] = "配置文件顶层不是对象"
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            # UnicodeDecodeError：非 UTF8 编码文件 read() 即抛（code-review
            # item eeec7a6f3ff5，与五处 yaml 读取点同款口径）
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
    # [fenix-ignore:6032b09cf68a] apikey 掩码需配对写侧 mask-keep，而 llm 为整段替换写入且生效视图跨 user/project 作用域（哨兵落盘毁配置或跨作用域复制密钥），属成面改动不实施
    if isinstance(effective.get("llm"), dict):
        result["llm"] = effective["llm"]
    agents_eff = effective.get("agents")
    if isinstance(agents_eff, dict):
        if isinstance(agents_eff.get("models"), dict):
            # improve-failover-model-mapping-ui（D4）：规范化 models 为 Dashboard
            # 回显视图（str/list/对象统一为对象数组 + resolved model）
            from core.config import ConfigLoader as _CL

            llm_eff = effective.get("llm")
            result["agents"]["models"] = _CL.normalize_agent_models(
                agents_eff["models"],
                (llm_eff.get("providers") or []) if isinstance(llm_eff, dict) else [],
            )
        result["agents"].update(_echo_agents_int_keys(agents_eff))
        # fix-agent-lane-efficiency D1：子代理模型覆盖生效值回显（code-review
        # item d1b9c5631669）——缺省视图恒空串，不回填则项目作用域覆盖值在
        # 有效配置视图恒显示空串，且 merge 分支把空串定义为「显式清除覆盖」，
        # 前端基于有效视图构造 agents patch 保存会静默清掉磁盘配置值。经
        # get_subagent_model_override 单点归一化（str 剥空白，非法类型回空串），
        # 与 read_config 回显口径一致。
        result["agents"]["subagent_model_override"] = ConfigLoader.get_subagent_model_override(effective)
        # 同因重派熔断阈值有效值回显（经 ConfigLoader 单点归一化，非法回退缺省 3）
        result["agents"]["max_same_cause_redispatches"] = (
            ConfigLoader.get_max_same_cause_redispatches(effective)
        )
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
        # 规模预检三键回显（缺省填充 + 非法值回退，与读侧同源归一化）
        from core.fast_track_result import get_scale_precheck_config as _get_sp_eff

        result["agents"]["scale_precheck"] = _get_sp_eff(effective)
    gates_eff = effective.get("gates")
    # add-start-after-scope-config 3.2：MUST NOT 整段替换 result["gates"]
    # （同 read_config 既有缺陷——其余 gates 键在分支后丢失），单键赋值。
    # code-review item 775c04d26905：经 get_approve_mode 生效值归一（缺失/非法
    # 值回退 manual，回显与运行时生效值一致——对齐同段 spec_review_mode /
    # start_after_scope 的 getter 单点写法），杜绝手工脏值直显。
    result.setdefault("gates", {})["approve_mode"] = ConfigLoader.get_approve_mode(effective)
    # add-draft-promotion-gate：草稿晋升模式回显（缺省 auto）
    if isinstance(gates_eff, dict) and "promote_mode" in gates_eff:
        val = gates_eff["promote_mode"]
        if val in ("auto", "manual"):
            if "gates" not in result:
                result["gates"] = {}
            result["gates"]["promote_mode"] = val
    elif "promote_mode" not in result.get("gates", {}):
        result["gates"]["promote_mode"] = "auto"
    # add-spec-review-gate：方案评审模式回显（经 get_spec_review_mode 生效值，
    # 非法值/缺失回退缺省 auto——与 ConfigLoader 单点同源，回显与生效值一致）
    if "gates" not in result:
        result["gates"] = {}
    result["gates"]["spec_review_mode"] = ConfigLoader.get_spec_review_mode(effective)
    # add-start-after-scope-config：start_after 门控覆盖范围回显（经
    # get_start_after_scope 生效值，缺失/非法回退 dispatch——与 getter 单点同源）
    result["gates"]["start_after_scope"] = ConfigLoader.get_start_after_scope(effective)
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
        # add-impl-code-review-gate：严格 bool 才回显，缺省不填充
        if isinstance(verify_eff.get("impl_code_review"), bool):
            result["verify"]["impl_code_review"] = verify_eff["impl_code_review"]
        # add-impl-code-review-tuning：三运行参数恒回显——缺省段已含 600/2/low，
        # 此处读有效合并值覆盖（读取器对非法值回退缺省，回显与生效值一致）
        result["verify"]["impl_code_review_timeout_sec"] = (
            ConfigLoader.get_impl_code_review_timeout_sec(effective)
        )
        result["verify"]["impl_code_review_concurrency"] = (
            ConfigLoader.get_impl_code_review_concurrency(effective)
        )
        # add-code-review-concurrency-and-429-resilience：全仓审查并发生效值回显
        result["verify"]["repo_code_review_concurrency"] = (
            ConfigLoader.get_repo_code_review_concurrency(effective)
        )
        result["verify"]["impl_code_review_effort"] = (
            ConfigLoader.get_impl_code_review_effort(effective)
        )
        # add-impl-ocr-parallel-lane：join 双档模式生效值回显（非法值回退缺省
        # gate，回显与生效值一致）
        result["verify"]["impl_code_review_mode"] = (
            ConfigLoader.get_impl_code_review_mode(effective)
        )
        # ocr 审查 finding#1：车道级硬超时生效值回显（非法值回退缺省 2400）
        result["verify"]["impl_code_review_lane_timeout_sec"] = (
            ConfigLoader.get_impl_code_review_lane_timeout_sec(effective)
        )
        sr_eff = verify_eff.get("serving_reclaim")
        if isinstance(sr_eff, dict) and isinstance(sr_eff.get("enabled"), bool):
            result["verify"]["serving_reclaim"]["enabled"] = sr_eff["enabled"]
    # add-spec-archive D5：经生效助手取值（非法配置回落默认 50，设置页回显一致）
    result["archive"] = {"auto_threshold": ConfigLoader.effective_auto_archive_threshold(effective)}
    # add-knowledge-atlas：经生效助手取值（非法值回退 true，设置页回显一致）；
    # 合并后段内键共存（enabled 总开关 + 维护车道键）
    result["knowledge"] = {
        **ConfigLoader.get_knowledge_lane_config(effective),
        **ConfigLoader.get_knowledge_config(effective),
    }
    # add-daily-self-review：经生效助手取值（run_at 非法值回退 02:00，回显一致）
    result["self_review"] = ConfigLoader.get_self_review_config(effective)
    # add-code-review-agent-and-quality-tab：code_review 生效值回显（与
    # self_review 同形态：顶层独立子键、经 get_code_review_config 归一化缺省）
    result["code_review"] = ConfigLoader.get_code_review_config(effective)
    # add-code-review-auto-fix：code_review_fix 生效值回显（同形态）
    result["code_review_fix"] = ConfigLoader.get_code_review_fix_config(effective)
    # add-test-regression-tab：regression 生效值回显（与 code_review 同形态：
    # 顶层独立子键、经 get_regression_config 归一化缺省）
    result["regression"] = ConfigLoader.get_regression_config(effective)
    # add-settings-system-tab：受管 admin 键提取（含缺省填充，不透传未知键）
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
    # evo-merge-back-wip-artifact-scope：产物路径回显（有效合并视图，非法形态回显空列表）
    from core.worktree_manager.artifact_paths import worktree_config_view as _wtcv

    result["worktree"] = _wtcv(effective)

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

    合并总则（白名单制）：只有函数体内显式写出合并分支的键才会被应用，
    未列出合并分支的键一律静默丢弃（不透传、不报错）。受管键集的权威
    来源是 _SOURCE_KEYS（受管键总清单，来源标注 + read 回显共用；agents
    数值标量键经 _AGENTS_MERGE_KEYS 与本函数共享同一名单）与
    _SYNC_PAGE_KEYS（「同步用户级设置」的页签级白名单），本 docstring
    不逐键罗列以免再次滞后于函数体。

    新增受管键必须同步三处，缺一即「界面可填、保存被静默吞掉」：
    1. read 回显（read_config / read_effective_config 白名单提取）
    2. merge 分支（在本函数内补显式分支）
    3. write 校验（write_config 前置合法性校验）
    函数体内多处「缺合并分支会被静默丢弃」的事故注释均源于漏掉第 2 处。

    分支形态举例（完整分支以函数体为准）：
    - hooks: 整体替换（patch 中存在即替换，不存在则保留原段）
    - llm: providers 整体替换、段内其余键逐键替换（patch 只带 providers 时
      llm 段其余键保留——item 9a727bd02545）
    - agents.models: 整体替换（只动 models，其它 agents 子键走各自分支）
    - agents.max_concurrent 等数值标量键: patch 提供即透传（合法性由
      write_config 前置校验把关）
    - gates.approve_mode / gates.promote_mode: 只替换对应子键
    """
    merged = copy.deepcopy(raw_config)

    # code-review item 9a727bd02545：providers 子键级合并（原整体替换会把项目级
    # llm 段内 providers 之外的键静默抹掉——「同步用户级设置」llm 页白名单只挑
    # providers 构造 patch，与 agents.models 同款只动本键、保留段内其余键）。
    # 段内其余键仍须逐键替换（回归修复：只合并 providers 会让 patch 段内
    # providers 之外的键被静默丢弃、write_config 仍返回 ok——与 promote_mode
    # 等历史「缺合并分支被静默丢弃」同坑）
    if "llm" in patch and isinstance(patch["llm"], dict):
        if not isinstance(merged.get("llm"), dict):
            merged["llm"] = {}
        for _llk, _llv in patch["llm"].items():
            # providers 列表整体替换（不逐项合并）；其余键逐键替换
            merged["llm"][_llk] = copy.deepcopy(_llv)

    if "agents" in patch and isinstance(patch["agents"], dict):
        if not isinstance(merged.get("agents"), dict):
            merged["agents"] = {}
        if "models" in patch["agents"]:
            merged["agents"]["models"] = copy.deepcopy(patch["agents"]["models"])
        # 数值标量键统一合并分支（历史 token_budget/verify_redo/scale_precheck 缺分支被静默丢弃）
        for _mk in _AGENTS_MERGE_KEYS:
            if _mk in patch["agents"]:
                merged["agents"][_mk] = patch["agents"][_mk]
        if "scale_precheck" in patch["agents"]:
            # 规模预检/超时监督段整体替换（缺分支会静默丢弃保存，历史同坑）
            merged["agents"]["scale_precheck"] = copy.deepcopy(patch["agents"]["scale_precheck"])
        if "timeout_supervision" in patch["agents"]:
            merged["agents"]["timeout_supervision"] = copy.deepcopy(
                patch["agents"]["timeout_supervision"]
            )
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
        # fix-agent-lane-efficiency D1：子代理模型覆盖合并分支。
        # 非空字符串覆盖、空串显式写回空值（语义 = 清除覆盖、回落 provider
        # model，磁盘原值会被覆盖）——与 read_config 回显语义（空串 = 使用
        # provider model）一致：用户在 UI 保存空串意为"用 provider 默认值"，
        # 清空此前的覆盖。
        _sro = patch["agents"].get("subagent_model_override")
        if isinstance(_sro, str):
            merged["agents"]["subagent_model_override"] = _sro.strip()

    if "gates" in patch and isinstance(patch["gates"], dict):
        if (
            "approve_mode" in patch["gates"]
            or "promote_mode" in patch["gates"]
            or "spec_review_mode" in patch["gates"]
            or "start_after_scope" in patch["gates"]
        ):
            if not isinstance(merged.get("gates"), dict):
                merged["gates"] = {}
        if "approve_mode" in patch["gates"]:
            merged["gates"]["approve_mode"] = patch["gates"]["approve_mode"]
        # add-draft-promotion-gate 验证修复：缺合并分支导致设置页保存的
        # promote_mode 在 merge 阶段被静默丢弃（枚举合法性已由 write_config 前置校验把关）
        if "promote_mode" in patch["gates"]:
            merged["gates"]["promote_mode"] = patch["gates"]["promote_mode"]
        # add-spec-review-gate：spec_review_mode 缺合并分支会被静默丢弃（同 promote_mode）
        if "spec_review_mode" in patch["gates"]:
            merged["gates"]["spec_review_mode"] = patch["gates"]["spec_review_mode"]
        # add-start-after-scope-config：start_after_scope 缺合并分支会被静默丢弃
        # （同 promote_mode / spec_review_mode 历史同坑）
        if "start_after_scope" in patch["gates"]:
            merged["gates"]["start_after_scope"] = patch["gates"]["start_after_scope"]

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
        sr_patch = patch["verify"].get("serving_reclaim")
        if isinstance(sr_patch, dict) and isinstance(sr_patch.get("enabled"), bool):
            merged.setdefault("verify", {}).setdefault("serving_reclaim", {})["enabled"] = sr_patch["enabled"]
        # add-planner-efficiency（planner-generation-throttle 2.3）：
        # planner 生成节流上限——非负整数（0=不节流），非法值静默忽略。
        pmc = patch["verify"].get("planner_max_concurrent")
        if isinstance(pmc, int) and not isinstance(pmc, bool) and pmc >= 0:
            merged["verify"]["planner_max_concurrent"] = pmc
        # add-impl-code-review-gate：严格 bool 才合并（前置校验已拒绝非法值，
        # 此处只应用合法值；缺省不写入——与 planner_max_concurrent 同款）
        if isinstance(patch["verify"].get("impl_code_review"), bool):
            merged["verify"]["impl_code_review"] = patch["verify"]["impl_code_review"]
        # add-impl-code-review-tuning：三运行参数合并（正整数/枚举才合并，
        # 缺失不填充、非法值由前置校验拒绝；与 impl_code_review 同款
        # 「界面可填、保存不静默丢弃」对称——漏 merge 分支即保存被吞）
        _ict = patch["verify"].get("impl_code_review_timeout_sec")
        if isinstance(_ict, int) and not isinstance(_ict, bool) and _ict > 0:
            merged["verify"]["impl_code_review_timeout_sec"] = _ict
        _icc = patch["verify"].get("impl_code_review_concurrency")
        if isinstance(_icc, int) and not isinstance(_icc, bool) and _icc > 0:
            merged["verify"]["impl_code_review_concurrency"] = _icc
        # add-code-review-concurrency-and-429-resilience：全仓审查并发合并
        # （正整数才合并，缺失不填充、非法值由前置校验拒绝；同款「界面可填、
        # 保存不静默丢弃」对称——漏 merge 分支即保存被吞）
        _rcc = patch["verify"].get("repo_code_review_concurrency")
        if isinstance(_rcc, int) and not isinstance(_rcc, bool) and _rcc > 0:
            merged["verify"]["repo_code_review_concurrency"] = _rcc
        _ice = patch["verify"].get("impl_code_review_effort")
        if _ice in ("low", "medium", "high"):
            merged["verify"]["impl_code_review_effort"] = _ice
        # add-impl-ocr-parallel-lane：join 双档模式合并（白名单枚举才合并，
        # 缺失不填充、非法值由前置校验拒绝；与 effort 同款「界面可填、保存
        # 不静默丢弃」对称）
        _icm = patch["verify"].get("impl_code_review_mode")
        if _icm in ("gate", "advisory"):
            merged["verify"]["impl_code_review_mode"] = _icm
        # ocr 审查 finding#1：车道级硬超时合并（正整数才合并，同款对称）
        _icl = patch["verify"].get("impl_code_review_lane_timeout_sec")
        if isinstance(_icl, int) and not isinstance(_icl, bool) and _icl > 0:
            merged["verify"]["impl_code_review_lane_timeout_sec"] = _icl
        # fix-agent-lane-efficiency D3：上下文经济性告警阈值合并（非负整数才合并，
        # 缺省 200000 由缺省段兜底；0 = 关闭告警）
        _cct = patch["verify"].get("context_cost_per_turn_threshold")
        if isinstance(_cct, int) and not isinstance(_cct, bool) and _cct >= 0:
            merged["verify"]["context_cost_per_turn_threshold"] = _cct
    # add-spec-archive D5：archive.auto_threshold（非负整数，0=禁用，非法值静默忽略）
    if "archive" in patch and isinstance(patch["archive"], dict):
        at = patch["archive"].get("auto_threshold")
        # code-review item 57914bc4b28c：排除 bool（True 是 int 子类且 True >= 0
        # 成立），与 verify 数值键合并分支防御口径对齐
        if isinstance(at, int) and not isinstance(at, bool) and at >= 0:
            if not isinstance(merged.get("archive"), dict):
                merged["archive"] = {}
            merged["archive"]["auto_threshold"] = at
    # add-knowledge-atlas：knowledge.enabled（bool 总开关；非 bool 由 write_config
    # 前置校验拒绝，合并分支只应用合法形态——缺分支会被静默丢弃，历史同坑）；
    # add-knowledge-atlas-maintenance：维护车道键（audit_enabled）同型合并——
    # 设置页「杂项」页签提交它，缺分支同样静默丢弃（历史同坑）
    if "knowledge" in patch and isinstance(patch["knowledge"], dict):
        _km = patch["knowledge"]
        for _kkey in ("enabled", "audit_enabled"):
            _kv = _km.get(_kkey)
            if isinstance(_kv, bool):
                if not isinstance(merged.get("knowledge"), dict):
                    merged["knowledge"] = {}
                merged["knowledge"][_kkey] = _kv
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
    # add-code-review-agent-and-quality-tab：admin.code_review 两键（enabled
    # 严格 bool、max_files 正整数；非法值由 write_config 前置校验拒绝，此处只
    # 应用合法值——对齐 self_review 合并语义）
    if "code_review" in patch and isinstance(patch["code_review"], dict):
        if not isinstance(merged.get("admin"), dict):
            merged["admin"] = {}
        existing_cr = merged["admin"].get("code_review")
        if not isinstance(existing_cr, dict):
            existing_cr = {}
        cr = dict(existing_cr)
        if isinstance(patch["code_review"].get("enabled"), bool):
            cr["enabled"] = patch["code_review"]["enabled"]
        max_files = patch["code_review"].get("max_files")
        if (
            isinstance(max_files, int)
            and not isinstance(max_files, bool)
            and max_files > 0
        ):
            cr["max_files"] = max_files
        # add-code-review-scope-config：scope 白名单应用（非法值由前置校验拒绝，
        # 此处只应用合法值——对齐 max_files 同款合并语义）
        if patch["code_review"].get("scope") in ("window", "full"):
            cr["scope"] = patch["code_review"]["scope"]
        # add-code-review-sharded-out 3.2：停滞告警阈值随受管段放行（正整数才
        # 合并，bool 是 int 子类显式排除——对齐 max_files 同款合并语义）
        sam = patch["code_review"].get("stall_alert_minutes")
        if isinstance(sam, int) and not isinstance(sam, bool) and sam > 0:
            cr["stall_alert_minutes"] = sam
        # add-code-review-run-at 4.1：触发时点随受管段放行（合法 HH:MM 才合并，
        # 脏值由 write_config 前置校验拒绝——对齐 self_review.run_at 同款合并
        # 语义；is_valid_hhmm 对 None/非串均 False）
        from core.config import ConfigLoader as _CL

        if _CL.is_valid_hhmm(patch["code_review"].get("run_at")):
            cr["run_at"] = patch["code_review"]["run_at"]
        merged["admin"]["code_review"] = cr
    # add-code-review-auto-fix：admin.code_review_fix 两键（enabled 严格 bool、
    # batch_size 正整数；非法值由 write_config 前置校验拒绝，此处只应用合法值
    # ——对齐 code_review 合并语义）
    if "code_review_fix" in patch and isinstance(patch["code_review_fix"], dict):
        if not isinstance(merged.get("admin"), dict):
            merged["admin"] = {}
        existing_crf = merged["admin"].get("code_review_fix")
        if not isinstance(existing_crf, dict):
            existing_crf = {}
        crf = dict(existing_crf)
        if isinstance(patch["code_review_fix"].get("enabled"), bool):
            crf["enabled"] = patch["code_review_fix"]["enabled"]
        bs = patch["code_review_fix"].get("batch_size")
        if isinstance(bs, int) and not isinstance(bs, bool) and bs > 0:
            crf["batch_size"] = bs
        trm = patch["code_review_fix"].get("targeted_retry_max")
        if isinstance(trm, int) and not isinstance(trm, bool) and 1 <= trm <= 5:
            crf["targeted_retry_max"] = trm
        # add-codefix-affinity-batching 4.3：定向回归开关随受管段放行
        #（严格 bool 才合并——非法值由 write_config 前置校验拒绝）
        if isinstance(patch["code_review_fix"].get("targeted_regression"), bool):
            crf["targeted_regression"] = patch["code_review_fix"]["targeted_regression"]
        merged["admin"]["code_review_fix"] = crf
    # add-test-regression-tab：admin.regression 键（enabled 严格 bool；非法值
    # 由 write_config 前置校验拒绝，此处只应用合法值——对齐 code_review 合并
    # 语义；未知 admin 键由 _managed_admin_keys 白名单狭窄回显，读不懂写入值，
    # 故本键 MUST 走本合并路径而非依赖 admin 段透传）
    if "regression" in patch and isinstance(patch["regression"], dict):
        if not isinstance(merged.get("admin"), dict):
            merged["admin"] = {}
        existing_reg = merged["admin"].get("regression")
        if not isinstance(existing_reg, dict):
            existing_reg = {}
        reg = dict(existing_reg)
        if isinstance(patch["regression"].get("enabled"), bool):
            reg["enabled"] = patch["regression"]["enabled"]
        merged["admin"]["regression"] = reg
    # add-settings-system-tab：admin.* 受管键合并（只动受管键，保留未知键）
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
            # add-adjudication-alert-narrative：叙事三键合并分支（缺此步「界面
            # 可填、保存被静默吞掉」——本函数 docstring 的同款事故）
            "narrative_enabled",
            "narrative_timeout_seconds",
            "narrative_model",
            # add-alert-self-heal-marking 5.2：自愈安静窗口合并分支（缺此步
            # 「界面可填、保存被静默吞掉」——本函数 docstring 的同款事故）
            "self_heal_quiet_minutes",
        ):
            if ak in patch["admin"] and patch["admin"][ak] is not None:
                merged["admin"][ak] = patch["admin"][ak]
        # code-review item 46a887dedf6a：「同步用户级设置」把 quality 页白名单里
        # 的 admin.code_review 段以 {"admin": {"code_review": {...}}} 形态的 patch
        # 送入本分支——不在此显式合并子段，该值会被上面的标量白名单静默丢弃
        # （与下方 code_review_fix 同款坑）。逐键守卫与顶层 code_review 分支一致。
        cr_sync = patch["admin"].get("code_review")
        if isinstance(cr_sync, dict):
            existing_cr = merged["admin"].get("code_review")
            if not isinstance(existing_cr, dict):
                existing_cr = {}
            merged_cr = dict(existing_cr)
            if isinstance(cr_sync.get("enabled"), bool):
                merged_cr["enabled"] = cr_sync["enabled"]
            _mf = cr_sync.get("max_files")
            if isinstance(_mf, int) and not isinstance(_mf, bool) and _mf > 0:
                merged_cr["max_files"] = _mf
            if cr_sync.get("scope") in ("window", "full"):
                merged_cr["scope"] = cr_sync["scope"]
            _sam = cr_sync.get("stall_alert_minutes")
            if isinstance(_sam, int) and not isinstance(_sam, bool) and _sam > 0:
                merged_cr["stall_alert_minutes"] = _sam
            # add-code-review-run-at 4.1：触发时点同口径合并（「同步用户级设置」
            # 按用户级回显原样携带 run_at 键，非法值由 write_config 前置校验拒绝
            # ——缺此步该键在合并阶段被静默丢弃，synced 与实际落盘不一致）
            from core.config import ConfigLoader as _CL

            if _CL.is_valid_hhmm(cr_sync.get("run_at")):
                merged_cr["run_at"] = cr_sync["run_at"]
            merged["admin"]["code_review"] = merged_cr
        # add-code-review-auto-fix：「同步用户级设置」按 _SYNC_PAGE_KEYS 构造
        # {"admin": {"code_review_fix": {...}}} 形态的 patch 进入本分支（顶层
        # code_review_fix 键只有设置页保存路径走）——不在此显式合并子段，该值
        # 会被上面的标量白名单静默丢弃，sync 返回 ok 但项目配置未落盘（ocr
        # 审查实证，正是上方 regression 注释点名的「缺分支静默丢弃保存」坑）。
        crf_sync = patch["admin"].get("code_review_fix")
        if isinstance(crf_sync, dict):
            existing_crf = merged["admin"].get("code_review_fix")
            if not isinstance(existing_crf, dict):
                existing_crf = {}
            merged_crf = dict(existing_crf)
            if isinstance(crf_sync.get("enabled"), bool):
                merged_crf["enabled"] = crf_sync["enabled"]
            _bs = crf_sync.get("batch_size")
            if isinstance(_bs, int) and not isinstance(_bs, bool) and _bs > 0:
                merged_crf["batch_size"] = _bs
            # code-review item 5607e1eab677：定向重试上限补合并分支（与顶层
            # code_review_fix 分支同口径：int 非 bool 且 1..5）——_SYNC_PAGE_KEYS
            # 把用户级 code_review_fix 段原样构进 patch（含 targeted_retry_max），
            # 缺此步该键在合并阶段被静默丢弃，sync 返回 ok 且 synced 回执原样
            # 包含该键（synced 与实际落盘不一致，复制粘贴漂移同款坑）
            _trm = crf_sync.get("targeted_retry_max")
            if isinstance(_trm, int) and not isinstance(_trm, bool) and 1 <= _trm <= 5:
                merged_crf["targeted_retry_max"] = _trm
            # add-codefix-affinity-batching 4.3：定向回归开关同口径合并
            if isinstance(crf_sync.get("targeted_regression"), bool):
                merged_crf["targeted_regression"] = crf_sync["targeted_regression"]
            merged["admin"]["code_review_fix"] = merged_crf
    # description 分支：patch 顶层 description（str）写入 merged["project"]["description"]
    # （非 str 非 None 由 write_config 前置校验拒绝，此处只应用合法值）
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
    # add-framework-self-evolution：self_evolution 三键合并（项目级被拒，此处仅用户级）
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
    # evo-merge-back-wip-artifact-scope / fix-artifact-paths-hardcoded-default：
    # worktree 段列表形态原样透传（非法值 write_config 拒绝）；has_build_artifacts
    # 布尔形态合并（False/True 显式写回，缺省 None 不覆盖旧值）。
    if "worktree" in patch and isinstance(patch["worktree"], dict):
        if not isinstance(merged.get("worktree"), dict):
            merged["worktree"] = {}
        _bap = patch["worktree"].get("build_artifact_paths")
        if isinstance(_bap, list):
            merged["worktree"]["build_artifact_paths"] = list(_bap)
        _hba = patch["worktree"].get("has_build_artifacts")
        if isinstance(_hba, bool):
            merged["worktree"]["has_build_artifacts"] = _hba
        elif "has_build_artifacts" in patch["worktree"] and _hba is None:
            # 显式 null = 撤销裁决（code-review item 22ec00069cd7）：写入 None 使
            # 「未配置」态真正生效，而非保留旧布尔让单选框弹回。写路径的
            # has_build_artifacts 缺省本就是 None（见 _defaults），语义自洽。
            merged["worktree"]["has_build_artifacts"] = None
    return merged

# config 写路径进程内串行锁（code-review item 39d2fda48088）：write_config 的
# 「读 raw → 合并受管键 → 原子替换」是读-改-写序列，os.replace 只保证单次写
# 不损坏、不保证序列原子性——ThreadingHTTPServer 并发线程各自基于旧 raw 合并
# 时，后落盘者会用不含对方改动的 merged 整体覆盖文件，先写方的受管键被静默
# 回滚。user/project 两作用域共用一把锁（写路径低频，无需按路径分锁）；
# 跨进程并发不在本锁覆盖范围（如需可叠加 flock），当前 dashboard HTTP 线程与
# daemon 裁决回写（admin_actions）同进程。
_CONFIG_WRITE_LOCK = threading.Lock()


def write_config(scope_root, config_patch: dict, scope: str = "project") -> dict:
    """把受管配置段写回作用域文件（原子写、保留非受管键）。

    写入前使用 ConfigLoader 做受管字段局部校验，校验失败返回错误且不写盘。

    Args:
        scope_root: 项目根路径（scope="project" 时使用；scope="user" 忽略）
        config_patch: 含 llm / agents.models / gates.approve_mode /
            gates.start_after_scope 的 patch dict
        scope: "user" 写 ~/.fenix/config.yaml（自动建目录）；"project" 写项目文件

    Returns: {"ok": bool, "error": str|null, "scope": "user"|"project", "path": str}
    """
    # 读-改-写全程持锁（code-review item 39d2fda48088）：临界区含前置校验
    # （校验只依赖 patch 不依赖 raw，在锁内仅略微拉长持锁时间，写路径低频
    # 可接受），保证并发保存不互覆盖。
    with _CONFIG_WRITE_LOCK:
        return _write_config_locked(scope_root, config_patch, scope)


def _write_config_locked(scope_root, config_patch: dict, scope: str = "project") -> dict:
    """write_config 实现（MUST NOT 直接调用：调用方须已持 _CONFIG_WRITE_LOCK）。"""
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
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            # UnicodeDecodeError：非 UTF8 编码文件 read() 即抛，缺则成 500
            # （code-review item eeec7a6f3ff5）
            return fail(f"读取现有配置失败: {e}")

    # 非 dict 的 agents patch 直接拒绝（对齐 self_evolution 同款「must be an
    # object」；非 dict 在下方守卫与 _deep_merge_managed 中均被跳过，若放行到
    # 末尾 _model_patch 提取会对 str/list 调 .get 抛 AttributeError 成 500）
    if "agents" in config_patch and not isinstance(config_patch["agents"], dict):
        return fail(f"agents must be an object: {config_patch['agents']!r}")

    # 非 dict 的 agents.models patch 直接拒绝（同上款「must be an object」口径：
    # 非 dict models 会被 _deep_merge_managed 原样拷入 merged——truthy 非 dict
    # 在末尾 _model_patch.items() 抛 AttributeError 成 500，falsy 非 dict 则
    # 绕过全部校验被静默落盘，违反 D7「非法值直接拒绝」契约）
    if (
        isinstance(config_patch.get("agents"), dict)
        and "models" in config_patch["agents"]
        and not isinstance(config_patch["agents"]["models"], dict)
    ):
        return fail(f"agents.models must be an object: {config_patch['agents']['models']!r}")

    # improve-failover-model-mapping-ui D4/D5：编辑器行列表序列化为 canonical 形态
    # （str/list|对象）供校验；role-level model 空值不写入（避免空串覆盖已有缺省）
    if isinstance(config_patch.get("agents"), dict) and isinstance(
        config_patch["agents"].get("models"), dict
    ):
        config_patch = dict(config_patch)  # shallow copy, 不改入参
        config_patch["agents"] = dict(config_patch["agents"])
        config_patch["agents"]["models"] = ConfigLoader.serialize_models_patch(
            config_patch["agents"]["models"]
        )

    # D5：agents.max_same_cause_redispatches 前置校验（正整数 1-100，非法拒绝 400）
    if isinstance(config_patch.get("agents"), dict):
        _msc = config_patch["agents"].get("max_same_cause_redispatches")
        if _msc is not None and (
            isinstance(_msc, bool) or not isinstance(_msc, int) or _msc < 1 or _msc > 100
        ):
            return fail(
                f"agents.max_same_cause_redispatches must be a positive integer "
                f"in [1, 100]: {_msc!r}"
            )

    # code-review item 1b1ed55c771c：agents.token_budget_millions 前置校验
    # （非负数 int/float，排除 bool——bool 是 int 子类；0=关闭是合法语义，
    # 其余任意类型一律拒绝不落盘，同 D7「非法值直接拒绝」契约）
    if isinstance(config_patch.get("agents"), dict):
        _tbm = config_patch["agents"].get("token_budget_millions")
        if _tbm is not None and (
            isinstance(_tbm, bool) or not isinstance(_tbm, (int, float)) or _tbm < 0
        ):
            return fail(
                f"agents.token_budget_millions must be a non-negative number "
                f"(0=关闭): {_tbm!r}"
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

    # add-code-review-agent-and-quality-tab：前端提交的 code_review patch 后端
    # 校验（非法直接拒绝，不静默忽略——同 self_review 模式）。
    # code-review item e717a52cd82e：嵌套 admin.code_review（「同步用户级设置」
    # 经 _SYNC_PAGE_KEYS 构造）与下方 code_review_fix 同款两路同口径——合并分支
    # 对内层脏值是静默跳过语义，缺此校验时 write_config 返回 ok、键照常计入
    # synced 回执（synced 与实际落盘不一致的假成功，且项目级被写入空段）。
    _cr_patches = []
    if isinstance(config_patch.get("code_review"), dict):
        _cr_patches.append(config_patch["code_review"])
    if isinstance(config_patch.get("admin"), dict) and isinstance(
        config_patch["admin"].get("code_review"), dict
    ):
        _cr_patches.append(config_patch["admin"]["code_review"])
    for cr_patch in _cr_patches:
        if (
            "enabled" in cr_patch
            and cr_patch["enabled"] is not None
            and not isinstance(cr_patch["enabled"], bool)
        ):
            return fail(f"admin.code_review.enabled must be a boolean: {cr_patch['enabled']}")
        if "max_files" in cr_patch and cr_patch["max_files"] is not None:
            mf = cr_patch["max_files"]
            if isinstance(mf, bool) or not isinstance(mf, int) or mf <= 0:
                return fail(
                    f"admin.code_review.max_files must be a positive integer: {mf!r}"
                )
        # add-code-review-scope-config：scope 枚举校验（非法直接拒绝不落盘，
        # 对齐 max_files 同款「非 None 且非法 → fail」；合法值 window | full）
        if "scope" in cr_patch and cr_patch["scope"] is not None:
            if cr_patch["scope"] not in ("window", "full"):
                return fail(
                    f"admin.code_review.scope must be 'window' or 'full': "
                    f"{cr_patch['scope']!r}"
                )
        # add-code-review-sharded-out 3.2：停滞告警阈值前置校验（正整数，非法
        # 直接拒绝不落盘——对齐 max_files 同款；bool 是 int 子类显式排除）
        if "stall_alert_minutes" in cr_patch and cr_patch["stall_alert_minutes"] is not None:
            sam = cr_patch["stall_alert_minutes"]
            if not isinstance(sam, int) or isinstance(sam, bool) or sam <= 0:
                return fail(
                    f"admin.code_review.stall_alert_minutes must be a positive "
                    f"integer: {sam!r}"
                )
        # add-code-review-run-at 4.1：触发时点前置校验（合法 HH:MM，非法直接
        # 拒绝不落盘——对齐 self_review.run_at 同款「非 None 且非法 → fail」）
        if "run_at" in cr_patch and cr_patch["run_at"] is not None:
            if not ConfigLoader.is_valid_hhmm(cr_patch["run_at"]):
                return fail(
                    f"admin.code_review.run_at must be HH:MM (00:00-23:59): "
                    f"{cr_patch['run_at']!r}"
                )

    # add-code-review-auto-fix：前端提交的 code_review_fix patch 后端校验
    # （enabled 严格 bool、batch_size 正整数；非法直接拒绝不落盘、不半写）。
    # 顶层 code_review_fix（设置页保存）与嵌套 admin.code_review_fix
    # （「同步用户级设置」经 _SYNC_PAGE_KEYS 构造）两条路径同口径校验。
    _crf_patches = []
    if isinstance(config_patch.get("code_review_fix"), dict):
        _crf_patches.append(config_patch["code_review_fix"])
    if isinstance(config_patch.get("admin"), dict) and isinstance(
        config_patch["admin"].get("code_review_fix"), dict
    ):
        _crf_patches.append(config_patch["admin"]["code_review_fix"])
    for crf_patch in _crf_patches:
        if (
            "enabled" in crf_patch
            and crf_patch["enabled"] is not None
            and not isinstance(crf_patch["enabled"], bool)
        ):
            return fail(
                f"admin.code_review_fix.enabled must be a boolean: {crf_patch['enabled']}"
            )
        if "batch_size" in crf_patch and crf_patch["batch_size"] is not None:
            bs = crf_patch["batch_size"]
            if isinstance(bs, bool) or not isinstance(bs, int) or bs <= 0:
                return fail(
                    f"admin.code_review_fix.batch_size must be a positive integer: {bs!r}"
                )
        if (
            "targeted_retry_max" in crf_patch
            and crf_patch["targeted_retry_max"] is not None
        ):
            trm = crf_patch["targeted_retry_max"]
            if isinstance(trm, bool) or not isinstance(trm, int) or not 1 <= trm <= 5:
                return fail(
                    "admin.code_review_fix.targeted_retry_max must be an integer "
                    f"in [1, 5]: {trm!r}"
                )
        # add-codefix-affinity-batching 4.3：定向回归开关严格 bool（非法直接
        # 拒绝不落盘——同 enabled 同款契约）
        if (
            "targeted_regression" in crf_patch
            and crf_patch["targeted_regression"] is not None
            and not isinstance(crf_patch["targeted_regression"], bool)
        ):
            return fail(
                "admin.code_review_fix.targeted_regression must be a boolean: "
                f"{crf_patch['targeted_regression']!r}"
            )

    # add-test-regression-tab：前端提交的 regression patch 后端校验（enabled
    # 严格 bool，非法直接拒绝、不静默忽略——同 code_review 模式）
    if isinstance(config_patch.get("regression"), dict):
        reg_patch = config_patch["regression"]
        if (
            "enabled" in reg_patch
            and reg_patch["enabled"] is not None
            and not isinstance(reg_patch["enabled"], bool)
        ):
            return fail(f"admin.regression.enabled must be a boolean: {reg_patch['enabled']}")

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
        # add-impl-code-review-gate：严格 bool 前置校验（非 bool 直接拒绝，
        # 与同段 deps_mode 枚举校验的「非法值直接拒绝」语义一致，不落盘）
        if "impl_code_review" in v_patch and v_patch["impl_code_review"] is not None:
            if not isinstance(v_patch["impl_code_review"], bool):
                return fail(
                    f"verify.impl_code_review must be a boolean: "
                    f"{v_patch['impl_code_review']!r}"
                )
        # add-impl-code-review-tuning：三运行参数前置校验（正整数 / 枚举拒绝，
        # 非法值直接 fail 不落盘，与 impl_code_review bool 同款「非 None 且非法 → fail」；
        # None 视为「未提交」，不校验）
        if (
            "impl_code_review_timeout_sec" in v_patch
            and v_patch["impl_code_review_timeout_sec"] is not None
        ):
            _ict = v_patch["impl_code_review_timeout_sec"]
            if isinstance(_ict, bool) or not isinstance(_ict, int) or _ict <= 0:
                return fail(
                    f"verify.impl_code_review_timeout_sec must be a positive integer: {_ict!r}"
                )
        if (
            "impl_code_review_concurrency" in v_patch
            and v_patch["impl_code_review_concurrency"] is not None
        ):
            _icc = v_patch["impl_code_review_concurrency"]
            if isinstance(_icc, bool) or not isinstance(_icc, int) or _icc <= 0:
                return fail(
                    f"verify.impl_code_review_concurrency must be a positive integer: {_icc!r}"
                )
        # add-code-review-concurrency-and-429-resilience：全仓审查并发前置校验
        # （正整数，bool 不算——与 impl 键同款）
        if (
            "repo_code_review_concurrency" in v_patch
            and v_patch["repo_code_review_concurrency"] is not None
        ):
            _rcc = v_patch["repo_code_review_concurrency"]
            if isinstance(_rcc, bool) or not isinstance(_rcc, int) or _rcc <= 0:
                return fail(
                    f"verify.repo_code_review_concurrency must be a positive integer: {_rcc!r}"
                )
        if (
            "impl_code_review_effort" in v_patch
            and v_patch["impl_code_review_effort"] is not None
            and v_patch["impl_code_review_effort"] not in ("low", "medium", "high")
        ):
            return fail(
                f"verify.impl_code_review_effort must be one of ['low', 'medium', 'high']: "
                f"{v_patch['impl_code_review_effort']!r}"
            )
        # add-impl-ocr-parallel-lane：join 双档模式前置校验（白名单枚举拒绝，
        # 「非 None 且非法 → fail」与 effort 同款；None 视为「未提交」不校验）
        if (
            "impl_code_review_mode" in v_patch
            and v_patch["impl_code_review_mode"] is not None
            and v_patch["impl_code_review_mode"] not in ("gate", "advisory")
        ):
            return fail(
                f"verify.impl_code_review_mode must be one of ['gate', 'advisory']: "
                f"{v_patch['impl_code_review_mode']!r}"
            )
        # ocr 审查 finding#1：车道级硬超时前置校验（非正整数拒绝，同 timeout_sec）
        if (
            "impl_code_review_lane_timeout_sec" in v_patch
            and v_patch["impl_code_review_lane_timeout_sec"] is not None
        ):
            _icl = v_patch["impl_code_review_lane_timeout_sec"]
            if isinstance(_icl, bool) or not isinstance(_icl, int) or _icl <= 0:
                return fail(
                    f"verify.impl_code_review_lane_timeout_sec must be a positive integer: {_icl!r}"
                )
        # fix-agent-lane-efficiency D3：上下文经济性告警阈值校验（非负整数，0=关闭告警）
        if "context_cost_per_turn_threshold" in v_patch and v_patch["context_cost_per_turn_threshold"] is not None:
            _cct = v_patch["context_cost_per_turn_threshold"]
            if isinstance(_cct, bool) or not isinstance(_cct, int) or _cct < 0:
                return fail(f"verify.context_cost_per_turn_threshold must be a non-negative integer: {_cct!r}")
        # code-review item cbbece865318：serving_reclaim 非 dict patch 直接拒绝
        # （合并分支以 isinstance dict 为前置，非 dict 真值走静默跳过、write_config
        # 仍返回 ok，提交被无声丢弃——对齐下方容器键「must be an object」同款
        # D7 拒绝契约；None 视为「未提交」放行）
        sr_patch = v_patch.get("serving_reclaim")
        if sr_patch is not None and not isinstance(sr_patch, dict):
            return fail(f"verify.serving_reclaim must be an object: {sr_patch!r}")
        if isinstance(sr_patch, dict) and sr_patch.get("enabled") is not None and not isinstance(sr_patch["enabled"], bool):
            return fail(f"verify.serving_reclaim.enabled must be a boolean: {sr_patch['enabled']!r}")

    # add-settings-system-tab：admin.* 受管键前置校验（非法值直接拒绝，不静默忽略——
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
        # add-adjudication-alert-narrative：叙事三键前置校验（enabled 严格 bool、
        # timeout 正整数、model 字符串；非法值直接拒绝不落盘，同其它 admin 键）。
        if (
            "narrative_enabled" in adm
            and adm["narrative_enabled"] is not None
            and not isinstance(adm["narrative_enabled"], bool)
        ):
            return fail(
                f"admin.narrative_enabled must be a boolean: {adm['narrative_enabled']!r}"
            )
        if (
            "narrative_timeout_seconds" in adm
            and adm["narrative_timeout_seconds"] is not None
        ):
            nt = adm["narrative_timeout_seconds"]
            if not isinstance(nt, int) or isinstance(nt, bool) or nt <= 0:
                return fail(
                    f"admin.narrative_timeout_seconds must be a positive integer: {nt!r}"
                )
        if (
            "narrative_model" in adm
            and adm["narrative_model"] is not None
            and not isinstance(adm["narrative_model"], str)
        ):
            return fail(
                f"admin.narrative_model must be a string: {adm['narrative_model']!r}"
            )
        # add-alert-self-heal-marking 5.2：自愈安静窗口正整数校验（非法值直接
        # 拒绝不落盘，同其它 admin 数值键）
        if (
            "self_heal_quiet_minutes" in adm
            and adm["self_heal_quiet_minutes"] is not None
        ):
            sq = adm["self_heal_quiet_minutes"]
            if not isinstance(sq, int) or isinstance(sq, bool) or sq <= 0:
                return fail(
                    f"admin.self_heal_quiet_minutes must be a positive integer: {sq!r}"
                )

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
        # add-start-after-scope-config：gates.start_after_scope 前置校验（枚举拒绝
        # full/dispatch，与 promote_mode 同模式；None 视为「未提交」，不校验）
        if (
            "start_after_scope" in g_patch
            and g_patch["start_after_scope"] is not None
            and g_patch["start_after_scope"] not in ("full", "dispatch")
        ):
            return fail(
                f"gates.start_after_scope must be one of ['full', 'dispatch']: {g_patch['start_after_scope']!r}"
            )

    # 非 dict 的 hooks patch 直接拒绝（对齐 agents 同款「must be an object」守卫：
    # 非 dict 跳过下方 validate_hooks_config，且会被 _deep_merge_managed 原样整体
    # 落盘，违反 D7「非法值直接拒绝 400 且不写入」契约）
    if "hooks" in config_patch and not isinstance(config_patch["hooks"], dict):
        return fail(f"hooks must be an object: {config_patch['hooks']!r}")

    # add-spec-hooks D7：hooks 段前置校验（非法值直接拒绝 400 且不写入——规则：
    # events 非空且合法、action 合法、webhook 必填 url、shell 必填 command）。
    if isinstance(config_patch.get("hooks"), dict):
        from core.hook_engine import validate_hooks_config

        hooks_err = validate_hooks_config(config_patch)
        if hooks_err:
            return fail(f"hooks 配置非法：{hooks_err}")

    # evo-merge-back-wip-artifact-scope：build_artifact_paths 前置校验（误配会静默
    # 丢弃语义改动，故拒绝而非静默忽略；判定权威 = validate_build_artifact_paths）
    if isinstance(config_patch.get("worktree"), dict):
        bap_patch = config_patch["worktree"].get("build_artifact_paths")
        if bap_patch is not None:
            from core.worktree_manager.artifact_paths import (
                validate_build_artifact_paths,
            )

            bap_err = validate_build_artifact_paths(bap_patch)
            if bap_err:
                return fail(bap_err)
        # fix-artifact-paths-hardcoded-default D4：has_build_artifacts 必须为布尔
        # （三态语义依赖「缺省=None / false / true」可区分，非法值 400 拒绝）
        hba_patch = config_patch["worktree"].get("has_build_artifacts")
        if hba_patch is not None and not isinstance(hba_patch, bool):
            return fail(
                f"worktree.has_build_artifacts must be a boolean (true/false): "
                f"{hba_patch!r}"
            )

    # add-stale-code-selfheal：两键前置校验（非法值直接拒绝 400，同 verify/self_review 模式）
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

    # add-framework-self-evolution：self_evolution 三键校验 + 项目级作用域拒绝
    # （全局用户级键，项目级提交 400 不写盘，用户级非法值直接拒绝 400）
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

    # code-review item 30ffc3a445d4：容器键非 dict patch 直接拒绝（对齐上方
    # agents / hooks / self_evolution 同款「must be an object」守卫：这批键在
    # _deep_merge_managed 中均带 isinstance(..., dict) 前置条件，非 dict 值走
    # 静默跳过路径，write_config 仍返回 ok:true，提交被丢弃而调用方无感知；
    # 各键的非法「值」校验段同样以 isinstance(..., dict) 为前提，非 dict 一律绕过）
    # code-review item bfcfdb155695：llm 同款纳入前置守卫——其合并分支无
    # isinstance dict 前置条件（整体替换），非 dict patch 原样置入 merged，最终
    # 由 merged-view 容器守卫以「存量非法段」文案拒绝：结果 400 正确，但文案把
    # 本次提交的问题误归因为存量 config.yaml（基线归因对不上时仍返回带误导括注
    # 的原文案），故前移至此以同款「must be an object」口径拒绝
    for _ck in (
        "llm",
        "gates",
        "verify",
        "archive",
        "admin",
        "self_review",
        "code_review",
        "code_review_fix",
        "regression",
        "stale_code_selfheal",
        "worktree",
        "knowledge",
    ):
        if _ck in config_patch and not isinstance(config_patch[_ck], dict):
            return fail(f"{_ck} must be an object: {config_patch[_ck]!r}")

    # description 前置校验（受管回显键：read_effective_config 提取顶层
    # project.description 回显）：merge 分支只应用 str，非 str 非 None 值走静默
    # 跳过路径、write_config 仍返回 ok:true——UI 填写的描述被无声吞掉且回显退回
    # 空串，违反 D7「非法值直接拒绝」契约（None 沿用本文件「视为未提交」口径）
    if (
        "description" in config_patch
        and config_patch["description"] is not None
        and not isinstance(config_patch["description"], str)
    ):
        return fail(f"description must be a string: {config_patch['description']!r}")

    # add-knowledge-atlas：knowledge.enabled 前置校验（布尔；非法直接拒绝 400，
    # 不静默落盘——合并分支对非 bool 是「跳过」语义，缺此校验会退回 ok:true
    # 静默丢弃，违反 D7「非法值直接拒绝」契约）
    if isinstance(config_patch.get("knowledge"), dict):
        for _kkey in ("enabled", "audit_enabled"):
            _ke = config_patch["knowledge"].get(_kkey)
            if _ke is not None and not isinstance(_ke, bool):
                return fail(f"knowledge.{_kkey} must be a boolean: {_ke!r}")

    # 嵌套形态同口径：「同步用户级设置」经 _SYNC_PAGE_KEYS 把用户级 admin 段以
    # {"admin": {"code_review": ...}} 形态送入（值取自用户级文件原文，手工脏数据
    # 会原样透传），非 dict 子段在合并分支（isinstance dict 前置）被静默跳过致
    # sync 返回 ok 却未落盘——与顶层同款拒绝
    if isinstance(config_patch.get("admin"), dict):
        for _nk in ("code_review", "code_review_fix"):
            if _nk in config_patch["admin"] and not isinstance(config_patch["admin"][_nk], dict):
                return fail(f"admin.{_nk} must be an object: {config_patch['admin'][_nk]!r}")

    # 2. 合并受管键
    merged = _deep_merge_managed(raw, config_patch)

    # improve-provider-billing-config D1：顶层 llm.billing 段移除（旧客户端残留清零）
    if isinstance(merged.get("llm"), dict) and "billing" in merged["llm"]:
        merged["llm"].pop("billing", None)

    # 24cea7818140：存量视图基线（不含本次 patch 的 raw），供校验失败归因用
    _baseline_view = copy.deepcopy(raw)
    if isinstance(_baseline_view.get("llm"), dict) and "billing" in _baseline_view["llm"]:
        _baseline_view["llm"].pop("billing", None)

    def _validate_merged_view(merged, model_patch):
        # 折叠原内联校验段（入参名 merged 遮蔽外层同名变量，校验逻辑零改动）
        # 3. 校验受管字段（llm / agents.models / agents.max_concurrent / gates.approve_mode）
        #    不做完整 ConfigLoader 校验，避免缺少 project/schedule 等必填键时无法写入。
        try:
            # code-review item bfbc50a5c577：存量 config.yaml 中容器段被手工编辑为
            # 非 dict 真值标量（如 gates: 5、llm: "x"）时，_deep_merge_managed 原样
            # 保留该非法段，下方 _validate_llm 对 str 抛 AttributeError、gates /
            # verify / archive / admin 经 `or {}` 后 `键 in xxx` 成员测试对 int 抛
            # TypeError——均非 ValueError，逃出本函数 except 致保存 500（agents 段
            # 同款问题已由 item 9e99a31f08fd 守卫转 400，此处对齐其余五个容器段；
            # 读侧 resolve_config 对非 dict 段按空段降级，写路径须显式拒绝）
            # code-review item 0afae666dbbc：knowledge 为后增受管段，同款存量
            # 非 dict 真值（如误当标量开关写的 knowledge: true）在下方
            # `键 in knowledge_m` 成员测试对 bool/int 抛 TypeError 致 500——
            # 纳入同款容器段守卫转 400
            for _seg in ("llm", "gates", "verify", "archive", "admin", "knowledge"):
                _seg_v = merged.get(_seg)
                if _seg_v is not None and not isinstance(_seg_v, dict):
                    raise ValueError(
                        f"{_seg} must be a mapping (存量非法段请先修正 config.yaml): {_seg_v!r}"
                    )
            llm = merged.get("llm") or {}
            if llm:
                ConfigLoader._validate_llm(llm)
            # improve-provider-billing-config task 2.1：per-provider billing 校验
            # （enabled 布尔、prices model 非空、单价非负、行 model 不重复，非法拒绝并列出）
            if isinstance(llm, dict):
                _providers = llm.get("providers")
                if _providers is not None:
                    if not isinstance(_providers, list):
                        raise ValueError("llm.providers must be a list")
                    ConfigLoader._validate_provider_billing(_providers)
            agents = merged.get("agents") or {}
            # code-review item 9e99a31f08fd：存量 agents 段为非 dict 真值（手工
            # 编辑 config.yaml 所致）且本次 patch 不含 agents 键时，
            # _deep_merge_managed 原样保留该非法段，下方 agents.get(...) 对
            # list/str 抛 AttributeError、truthy 标量在 `in` 成员测试抛 TypeError，
            # 均逃出 except ValueError 致保存 500——此处守卫转 400 校验错误
            # （patch 含 agents dict 时 _deep_merge_managed 已重置为 {}，本守卫
            # 仅拦存量非法）
            if not isinstance(agents, dict):
                raise ValueError(
                    f"agents must be a mapping (存量非法段请先修正 config.yaml): {agents!r}"
                )
            if "models" in agents and agents["models"]:
                ConfigLoader._validate_agent_models(agents["models"], llm)
                # improve-failover-model-mapping-ui D5：UI 保存要求 provider 名存在于 llm.providers
                # （model_patch 为入参：merged 校验传本次 patch 提取值；存量基线
                # 复跑传 {}，跳过仅由本次提交引发的检查，避免误归因为存量）
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
                if not _is_int_not_bool(mc) or mc <= 0:
                    raise ValueError(f"agents.max_concurrent must be a positive integer: {mc}")
            if "run_timeout_seconds" in agents:
                rt = agents["run_timeout_seconds"]
                if not _is_int_not_bool(rt) or rt <= 0:
                    raise ValueError(f"agents.run_timeout_seconds must be a positive integer: {rt}")
            if "max_turns" in agents:
                mt = agents["max_turns"]
                if not _is_int_not_bool(mt) or mt <= 0:
                    raise ValueError(f"agents.max_turns must be a positive integer: {mt}")
            if "daily_run_limit" in agents:
                drl = agents["daily_run_limit"]
                if not _is_int_not_bool(drl) or drl < 0:
                    raise ValueError(f"agents.daily_run_limit must be a non-negative integer: {drl}")
            if "token_budget_millions" in agents:
                tbm = agents["token_budget_millions"]
                # code-review item 1b1ed55c771c：非负数（int/float，排除 bool），
                # 0=关闭合法；与前置校验同规则，兜底防绕过前置直连写盘
                if isinstance(tbm, bool) or not isinstance(tbm, (int, float)) or tbm < 0:
                    raise ValueError(
                        f"agents.token_budget_millions must be a non-negative number "
                        f"(0=关闭): {tbm!r}"
                    )
            if "impl_run_budget" in agents:
                irb = agents["impl_run_budget"]
                # open-impl-budget-ceiling：上限由 agents.impl_run_budget_max 决定
                # （缺省 100，硬天花板 1000），不再硬编码 10。
                from core.pm_engine.budget import resolve_impl_run_budget_max

                budget_max = resolve_impl_run_budget_max(agents.get("impl_run_budget_max"))
                if not _is_int_not_bool(irb) or irb < 1 or irb > budget_max:
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
                if not _is_int_not_bool(vrb) or vrb < 1 or vrb > 10:
                    raise ValueError(f"agents.verify_redo_budget must be an integer in [1, 10]: {vrb}")
            # fix-agent-lane-efficiency D1：子代理模型覆盖键校验。
            # 类型：仅接受 str 或 None（None 视为未配置）；空串合法（= 使用 provider
            # model）。非 str 类型（int/bool/list）拒绝，防止用户误填导致类型混淆。
            _sro = agents.get("subagent_model_override")
            if _sro is not None and not isinstance(_sro, str):
                raise ValueError(
                    f"agents.subagent_model_override must be a string "
                    f"(model name or empty): {_sro!r}"
                )
            if "scale_precheck" in agents and agents["scale_precheck"] is not None:
                # 规模预检（agents.scale_precheck）：enabled 必须布尔；两阈值正整数
                # 且 higher < full（倒挂或相等即拒绝——否则档位语义不自洽）。
                from core.fast_track_result import (
                    SCALE_PRECHECK_ENABLED_KEY,
                    SCALE_PRECHECK_FULL_KEY,
                    SCALE_PRECHECK_HIGHER_KEY,
                    SCALE_PRECHECK_THRESHOLD_MAX,
                    SCALE_PRECHECK_THRESHOLD_MIN,
                )

                _sp = agents["scale_precheck"]
                if not isinstance(_sp, dict):
                    raise ValueError(f"agents.scale_precheck must be a mapping: {_sp!r}")
                if SCALE_PRECHECK_ENABLED_KEY in _sp and not isinstance(
                    _sp[SCALE_PRECHECK_ENABLED_KEY], bool
                ):
                    raise ValueError(
                        "agents.scale_precheck.enabled must be a boolean: "
                        f"{_sp[SCALE_PRECHECK_ENABLED_KEY]!r}"
                    )

                def _sp_threshold(key: str):
                    if key not in _sp or _sp[key] is None:
                        return None
                    _v = _sp[key]
                    if (
                        isinstance(_v, bool)
                        or not isinstance(_v, int)
                        or _v < SCALE_PRECHECK_THRESHOLD_MIN
                        or _v > SCALE_PRECHECK_THRESHOLD_MAX
                    ):
                        raise ValueError(
                            f"agents.scale_precheck.{key} must be an integer in "
                            f"[{SCALE_PRECHECK_THRESHOLD_MIN}, {SCALE_PRECHECK_THRESHOLD_MAX}]: {_v!r}"
                        )
                    return _v

                _sp_higher = _sp_threshold(SCALE_PRECHECK_HIGHER_KEY)
                _sp_full = _sp_threshold(SCALE_PRECHECK_FULL_KEY)
                if _sp_higher is not None and _sp_full is not None and _sp_higher >= _sp_full:
                    raise ValueError(
                        "agents.scale_precheck requires higher_threshold < full_threshold: "
                        f"{_sp_higher} >= {_sp_full}"
                    )
            # fix-provider-transient-backoff D6：瞬断治理四数值键非负数值校验（非法拒绝 400）
            for _tk in (
                "transient_redispatch_delay_seconds",
                "transient_break_threshold",
                "transient_break_window_seconds",
                "transient_break_cooldown_seconds",
            ):
                if _tk in agents and agents[_tk] is not None:
                    _tv = agents[_tk]
                    if isinstance(_tv, bool) or not isinstance(_tv, (int, float)) or _tv < 0:
                        raise ValueError(f"agents.{_tk} must be a non-negative number: {_tv!r}")
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
            # supervision-timeout-config-consistency：timeout_supervision 段校验
            # （自动对齐 + 直连写回共用；数值键非负，enabled 布尔，非法拒绝 400）
            if "timeout_supervision" in agents and agents["timeout_supervision"] is not None:
                _ts_sup = agents["timeout_supervision"]
                if not isinstance(_ts_sup, dict):
                    raise ValueError(f"agents.timeout_supervision must be a mapping: {_ts_sup!r}")
                for _tsk in ("extension_seconds", "max_extensions", "absolute_max_seconds", "judge_window"):
                    _tsv = _ts_sup.get(_tsk)
                    if _tsv is not None and (
                        isinstance(_tsv, bool) or not isinstance(_tsv, (int, float)) or _tsv < 0
                    ):
                        raise ValueError(
                            f"agents.timeout_supervision.{_tsk} must be a non-negative "
                            f"number: {_tsv!r}"
                        )
                if (
                    "enabled" in _ts_sup
                    and _ts_sup["enabled"] is not None
                    and not isinstance(_ts_sup["enabled"], bool)
                ):
                    raise ValueError(
                        f"agents.timeout_supervision.enabled must be a boolean: "
                        f"{_ts_sup['enabled']!r}"
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
            # add-knowledge-atlas + add-knowledge-atlas-maintenance：knowledge 段
            # 受管键必须为布尔（非法值拒绝 400，对齐 D7「非法值直接拒绝」契约）
            knowledge_m = merged.get("knowledge") or {}
            for _kkey in ("enabled", "audit_enabled"):
                if _kkey in knowledge_m and knowledge_m[_kkey] is not None:
                    if not isinstance(knowledge_m[_kkey], bool):
                        raise ValueError(
                            f"knowledge.{_kkey} must be a boolean: {knowledge_m[_kkey]!r}"
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
            # add-settings-system-tab：admin.* 受管键（merged 视图校验；写路径前置校验
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
                # add-adjudication-alert-narrative：叙事三键合并视图校验
                # （兜底防绕过前置校验的直连调用，规则同前置）
                (
                    "narrative_enabled",
                    lambda v: isinstance(v, bool),
                ),
                (
                    "narrative_timeout_seconds",
                    lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
                ),
                (
                    "narrative_model",
                    lambda v: isinstance(v, str),
                ),
                # add-alert-self-heal-marking 5.2：自愈安静窗口合并视图校验
                # （兜底防绕过前置校验的直连调用，规则同前置）
                (
                    "self_heal_quiet_minutes",
                    lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
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

    _model_patch = (
        config_patch.get("agents", {}).get("models", {})
        if config_patch.get("agents")
        else {}
    )
    _err = _validate_merged_view(merged, _model_patch)
    if _err is not None:
        # 24cea7818140：失败归因——同一校验在存量视图（不含本次 patch）上复跑，
        # 报错一致 ⇒ 失败由 config.yaml 存量非法值引发（与本次提交无关），文案
        # 标注定位指引；保存仍被拒绝（判定结果不变），仅错误文案可定位。
        try:
            _err_base = _validate_merged_view(_baseline_view, {})
        except Exception:
            _err_base = None
        if _err_base is not None and _err_base["error"] == _err["error"]:
            return fail(
                "存量配置值非法（与本次提交无关），请先修正 config.yaml 中对应键后重试："
                + _err["error"]
            )
        return _err

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
                # code-review item f264136fda60：replace 前 flush+fsync（仓库原子
                # 写惯例，与 _atomic_write_text / _atomic_write_request 同口径），
                # 防掉电后 rename 落盘空/半截 yaml 成正式配置
                f.flush()
                os.fsync(f.fileno())
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

# 页面标识 → 用户级 config.yaml 中被同步的受管键白名单（键集与各页签 onSave
# patch 一一对应）。worktree.build_artifact_paths / worktree.has_build_artifacts
# 不含——项目级键 + 误配会静默丢弃语义改动（产物判定必须由项目声明），
# 「同步用户级设置」不得覆盖进项目级（须在验证页项目作用域显式编辑）。
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
            # open-impl-budget-ceiling（code-review item 9996d46ad1a9）：实现尝试
            # 预算上限随 token 页签同步——项目级 impl_run_budget 的校验上限按项目级
            # impl_run_budget_max 取值，缺此键时「同步用户级设置」会静默漏同步，
            # 项目级校验仍走旧上限
            "impl_run_budget_max",
            "verify_redo_budget",
        ],
    },
    "verify": {"verify": ["static_scope", "deps_mode", "serving_reclaim"]},
    # 收尾代码质量审查自「验证」页迁出至独立「质量」页签（键路径 verify.impl_code_review
    # 保持不变，仅换呈现位置；见 settings 页 quality 页签）。
    # add-impl-code-review-tuning：同步白名单同步扩三运行参数键（缺此步时「同步
    # 用户级设置」按钮会静默漏同步三键——功能对用户不可见）。
    "quality": {
        "verify": [
            "impl_code_review",
            "impl_code_review_timeout_sec",
            "impl_code_review_concurrency",
            # add-code-review-concurrency-and-429-resilience：全仓审查并发随
            # 质量页签同步（缺此步时「同步用户级设置」按钮会静默漏同步该键）
            "repo_code_review_concurrency",
            "impl_code_review_effort",
            # add-impl-ocr-parallel-lane：join 双档模式随质量页签同步（缺此步时
            # 「同步用户级设置」按钮会静默漏同步该键——功能对用户不可见）
            "impl_code_review_mode",
            # ocr 审查 finding#1：车道级硬超时随质量页签同步（同款理由）
            "impl_code_review_lane_timeout_sec",
        ],
        # add-code-review-auto-fix：admin.code_review_fix 段随质量页签同步
        # code-review item 46a887dedf6a：admin.code_review 段（QualityPanel onSave
        # 顶层提交的 code_review）同样随质量页签同步——缺此键时「同步用户级设置」
        # 不落 admin.code_review、「清空」也删不掉，与 code_review_fix 不对称。
        "admin": ["code_review", "code_review_fix"],
    },
    "approval": {
        "gates": ["promote_mode", "approve_mode", "spec_review_mode", "start_after_scope"]
    },
    "misc": {
        "archive": ["auto_threshold"],
        # add-knowledge-atlas-maintenance（code-review item b0f9ef662810）：知识
        # 真相源维护车道键随杂项页签同步——缺此步时「同步用户级设置」按钮会
        # 静默漏同步 audit_enabled、「清空」也删不掉项目级覆盖
        # （与 quality 页三运行参数 / join 模式的同型事故同款）
        "knowledge": ["enabled", "audit_enabled"],
    },
    "system": {
        "admin": [
            "enabled",
            "interval_minutes",
            "escalation_cooldown_minutes",
            "merge_breaker_threshold",
            "shutdown_drain_seconds",
            "bug_repair_mode",
            "stuck_silence_minutes",
            # add-adjudication-alert-narrative：叙事三键随系统页签同步（缺此步
            # 「同步用户级设置」按钮会静默漏同步三键——功能对用户不可见）
            "narrative_enabled",
            "narrative_timeout_seconds",
            "narrative_model",
            # add-alert-self-heal-marking 5.2：自愈安静窗口随系统页签同步
            "self_heal_quiet_minutes",
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

# 「同步用户级设置」逐键形态谓词（code-review item b4686d41625c，前身是
# fd7178c8666c 的段内复合值键白名单）：sync 以用户级文件原值构造 patch，部分
# 形态（枚举/布尔键显式 null、serving_reclaim 为 dict 但缺 enabled 布尔）能通过
# write_config 前置校验（None 视为「未提交」放行），却在 _deep_merge_managed
# 对应合并分支的形态条件处被静默跳过不落盘，键仍照常计入 synced 回执——
# fd7178c8666c / 46a887dedf6a 同款「synced 与实际落盘不一致」假成功的残余面
# （触发条件为手工编辑的用户级配置）。本表列出合并分支带形态条件的键，谓词与
# 对应 _deep_merge_managed 分支同口径（逐键核对），拾取后预检不命中直接报错
# 拒绝（不剔除、不假成功）。agents.models 与 admin.code_review /
# admin.code_review_fix 不在表内：非 dict 已由 write_config 的「must be an
# object」前置守卫直接拒绝，无需本函数重复预检。
_SYNC_PAGE_APPLY_PREDICATES = {
    "verify": {
        "static_scope": (
            lambda v: v in ("main", "worktree"),
            "must be one of ['main', 'worktree']",
        ),
        "deps_mode": (
            lambda v: v in ("prefer-offline", "hardlink"),
            "must be one of ['prefer-offline', 'hardlink']",
        ),
        "serving_reclaim": (
            lambda v: isinstance(v, dict) and isinstance(v.get("enabled"), bool),
            "must be an object with boolean enabled",
        ),
        "planner_max_concurrent": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
            "must be a non-negative integer",
        ),
        "impl_code_review": (
            lambda v: isinstance(v, bool),
            "must be a boolean",
        ),
        "impl_code_review_timeout_sec": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
            "must be a positive integer",
        ),
        "impl_code_review_concurrency": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
            "must be a positive integer",
        ),
        "repo_code_review_concurrency": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
            "must be a positive integer",
        ),
        "impl_code_review_effort": (
            lambda v: v in ("low", "medium", "high"),
            "must be one of ['low', 'medium', 'high']",
        ),
        "impl_code_review_mode": (
            lambda v: v in ("gate", "advisory"),
            "must be one of ['gate', 'advisory']",
        ),
        "impl_code_review_lane_timeout_sec": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
            "must be a positive integer",
        ),
    },
    "archive": {
        "auto_threshold": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
            "must be a non-negative integer",
        ),
    },
    "knowledge": {
        "enabled": (
            lambda v: isinstance(v, bool),
            "must be a boolean",
        ),
        "audit_enabled": (
            lambda v: isinstance(v, bool),
            "must be a boolean",
        ),
    },
    # code-review item b331b2c9ae73：system 页 admin 标量键补登记——合并分支
    # 带「is not None」形态条件（None = 未提交，静默跳过），用户级手工写成
    # null 的键原样构进 patch 后在此被拾取，缺登记则预检放行、合并跳过、
    # synced 回执照含该键（同款「synced 与实际落盘不一致」假成功）。谓词与
    # write_config 前置校验同口径（非 None 且类型合法）。
    "admin": {
        "enabled": (
            lambda v: isinstance(v, bool),
            "must be a boolean",
        ),
        "interval_minutes": (
            lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0,
            "must be a positive number",
        ),
        "escalation_cooldown_minutes": (
            lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0,
            "must be a non-negative number",
        ),
        "merge_breaker_threshold": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 1,
            "must be a positive integer",
        ),
        "shutdown_drain_seconds": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
            "must be a non-negative integer",
        ),
        "bug_repair_mode": (
            lambda v: v in ("inplace", "derive"),
            "must be one of ['inplace', 'derive']",
        ),
        "stuck_silence_minutes": (
            lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0,
            "must be a non-negative number",
        ),
        "narrative_enabled": (
            lambda v: isinstance(v, bool),
            "must be a boolean",
        ),
        "narrative_timeout_seconds": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
            "must be a positive integer",
        ),
        "narrative_model": (
            lambda v: isinstance(v, str),
            "must be a string",
        ),
        "self_heal_quiet_minutes": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
            "must be a positive integer",
        ),
    },
}

def _pred_hhmm(v) -> bool:
    """run_at 谓词（延迟 import，与合并分支内局部 import 同款）。"""
    from core.config import ConfigLoader

    return ConfigLoader.is_valid_hhmm(v)


# code-review item 002d3c8a7fb0：sync 以整段子 dict 构 patch 的键
# （verify.serving_reclaim / admin.code_review / admin.code_review_fix），
# _deep_merge_managed 对应合并分支只应用表内白名单子键——段内未知键、
# 显式 null 不落盘，synced 回执若原样返回构造 patch 即虚报已同步
# （fd7178c8666c / 46a887dedf6a / b331b2c9ae73 同款「synced 与实际落盘
# 不一致」假成功的残余面）。谓词与对应合并分支逐键同口径，synced 回执
# 按本表裁剪（在 write_config 之后裁：已知子键非法值仍由其前置校验
# 直接拒绝，不改变「不剔除、不假成功」语义）。其余受管键均为标量键或
# 整体替换（llm.providers / agents.models），回执天然与落盘一致，不入表。
_SYNC_DICT_SUBKEY_APPLY = {
    ("verify", "serving_reclaim"): {
        "enabled": lambda v: isinstance(v, bool),
    },
    ("admin", "code_review"): {
        "enabled": lambda v: isinstance(v, bool),
        "max_files": lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
        "scope": lambda v: v in ("window", "full"),
        "stall_alert_minutes": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0
        ),
        "run_at": _pred_hhmm,
    },
    ("admin", "code_review_fix"): {
        "enabled": lambda v: isinstance(v, bool),
        "batch_size": lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
        "targeted_retry_max": (
            lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5
        ),
        "targeted_regression": lambda v: isinstance(v, bool),
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
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            # UnicodeDecodeError：非 UTF8 编码文件 read() 即抛（code-review
            # item eeec7a6f3ff5，与五处 yaml 读取点同款口径）
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
        if sec_raw is None:
            continue  # 用户级未配置该段：本页无可同步值，跳过（不写空覆盖）
        if not isinstance(sec_raw, dict):
            # code-review item fd7178c8666c：段存在但形态脏（如 verify: true）
            # 不能静默跳过——该段会被无声略去而其余段照常 sync 返回 ok，同款
            # 「synced 与实际落盘不一致」假成功，直接报错拒绝。
            return {
                "ok": False,
                "error": f"{section} must be an object: {sec_raw!r}",
                "synced": None,
                "path": str(_facade.USER_CONFIG_PATH),
            }
        picked = {k: sec_raw[k] for k in keys if k in sec_raw}
        # 逐键可应用性预检（口径见 _SYNC_PAGE_APPLY_PREDICATES 表注释）：形态
        # 不符直接报错拒绝，而非照常计入 synced 回执虚报已同步
        for _pk, _pv in picked.items():
            _pred = _SYNC_PAGE_APPLY_PREDICATES.get(section, {}).get(_pk)
            if _pred is not None and not _pred[0](_pv):
                return {
                    "ok": False,
                    "error": f"{section}.{_pk} {_pred[1]}: {_pv!r}",
                    "synced": None,
                    "path": str(_facade.USER_CONFIG_PATH),
                }
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
    if result["ok"]:
        # code-review item 002d3c8a7fb0：synced 回执按 _deep_merge_managed 实际
        # 应用口径逐键裁剪整段子对象（段内未知键、显式 null 不落盘，原样回执
        # 即虚报已同步）。裁剪在 write_config 成功后进行，不影响其前置校验
        # （已知子键非法值仍被直接拒绝，不剔除、不假成功）。
        for _sec, _keys_patch in patch.items():
            for _pk in _keys_patch:
                _sub_apply = _SYNC_DICT_SUBKEY_APPLY.get((_sec, _pk))
                if _sub_apply is not None and isinstance(_keys_patch[_pk], dict):
                    _keys_patch[_pk] = {
                        _sk: _sv
                        for _sk, _sv in _keys_patch[_pk].items()
                        if _sk in _sub_apply and _sub_apply[_sk](_sv)
                    }
    return {
        "ok": result["ok"],
        "error": result.get("error"),
        "synced": patch if result["ok"] else None,
        "path": result.get("path"),
    }


def clear_project_page_keys(project_root, page: str) -> dict:
    """从项目级 config.yaml 删除 page 页签对应的受管键（「清空」按钮）。

    项目级不再显式覆盖这些键后，用户级配置/内置默认值自然生效（sources 回
    "user"）——与「同步用户级设置」互补：同步=显式对齐，清空=取消项目级覆盖。
    删空的 section 整段移除；非受管键与其它 section 原样保留；原子写盘。

    Args:
        project_root: 项目根路径
        page: 页面标识（_SYNC_PAGE_KEYS 键）

    Returns: {"ok": bool, "error": str|null, "cleared": dict|None, "path": str}
        cleared = 实际删除的键（{section: {key: 原值}}），None = 项目级文件不存在
        （本来就没有覆盖，幂等 no-op）。
    """
    if page not in _SYNC_PAGE_KEYS:
        return {"ok": False, "error": f"未知页面标识: {page}", "cleared": None, "path": None}

    import core.dashboard.data as _facade

    config_path = Path(project_root) / ".fenix" / "config.yaml"
    fail = lambda err: {"ok": False, "error": err, "cleared": None, "path": str(config_path)}

    if not config_path.exists():
        return {"ok": True, "error": None, "cleared": None, "path": str(config_path)}

    # 读-改-写全程持锁（code-review item 7d24ff72b5ca）：与 write_config 共用
    # _CONFIG_WRITE_LOCK——用户在设置页同时点「清空」与另一页签「保存」时，两侧
    # 各自基于 raw 快照整文件写回，后落盘者会覆盖先落盘者（save 的键被 clear 的
    # 旧快照抹掉，或 clear 的删除被 save 的旧快照写回）。写路径低频，锁内仅多出
    # yaml 读写，无重入风险（调用方为 HTTP 路由，不持本锁）。
    with _CONFIG_WRITE_LOCK:
        raw = {}
        try:
            with config_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw = loaded
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            # UnicodeDecodeError：非 UTF8 编码文件 read() 即抛，缺则成 500
            # （code-review item eeec7a6f3ff5）
            return fail(f"读取现有配置失败: {e}")

        cleared = {}
        for section, keys in _SYNC_PAGE_KEYS[page].items():
            sec_raw = raw.get(section)
            if not isinstance(sec_raw, dict):
                continue
            removed = {k: sec_raw.pop(k) for k in keys if k in sec_raw}
            if removed:
                cleared[section] = removed
                if not sec_raw:
                    raw.pop(section)  # section 删空整段移除，不留空 mapping

        if not cleared:
            # 没有可删的键：不重写文件（保留原文件 mtime，避免无意义触碰配置热更新）
            return {"ok": True, "error": None, "cleared": {}, "path": str(config_path)}

        config_dir = config_path.parent
        try:
            fd, tmp_path = tempfile.mkstemp(dir=str(config_dir), prefix=".config-", suffix=".yaml.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(_CONFIG_HEADER_COMMENT)
                    yaml.safe_dump(
                        raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False
                    )
                    # code-review item f264136fda60：replace 前 flush+fsync（仓库
                    # 原子写惯例，与 write_config 同口径），防掉电后半截 yaml 换入
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, config_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            return fail(f"写入配置文件失败: {e}")

    return {"ok": True, "error": None, "cleared": cleared, "path": str(config_path)}
