"""core.dashboard.data.summary — 聚合视图/摘要（summary 组）。

refactor-dashboard-data-module D3 分组：本模块承载聚合视图职责域。
daemon/托管态检测、项目与 SPEC 摘要、摘要索引、概览。
"""

import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# infra 轮次/失败计数常量子段（spec_summary/spec_detail 补推断口）
from core.state_machine import (
    INFRA_FAILURE_COUNT_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
    # 2.1a 条目指纹的预算覆盖字段（budget.py 同源常量，经 state_machine 顶层
    # 导入可避开 pm_engine 包循环：pm_engine/__init__ → engine → dashboard.data）
    IMPL_RUN_BUDGET_OVERRIDE_FIELD,
)
# 取消保持标记归一读值单点（add-cancelled-spec-resume-action D1；叶子模块，无环）
from core.timelib import now_local, parse_ts
from .state import normalize_bool_flag

# 服务端日志留痕出口（overview 降级摘要等；客户端只收固定文案，不外泄裸异常）
logger = logging.getLogger("fenixd.dashboard.summary")

# ── daemon 健康检测（D4：TTL memo 避免高频轮询重复 spawn tmux） ──────

_DAEMON_HEALTH_TTL = 5.0  # 秒；结果在 TTL 内复用
_DAEMON_HEALTH_CACHE: dict = {}  # key=规范化项目根, value=(状态, 时间戳)


def daemon_health(project_root) -> str:
    """项目 fenixd daemon 是否在运行，返回 "running"/"stopped"。

    判定复用 core.fenix_session.is_running（进程检测为主：项目根下的
    fenixd.py / fenixd_supervisor.py 进程；/proc 不可用时回退 tmux session）。
    tmux 不可用、subprocess 异常或均未命中一律 "stopped"，
    不抛异常。带短 TTL memo，避免 overview 每 2s 轮询重复 spawn 子进程。
    """
    key = str(Path(project_root).expanduser().resolve())
    now = time.monotonic()
    cached = _DAEMON_HEALTH_CACHE.get(key)
    if cached is not None and now - cached[1] < _DAEMON_HEALTH_TTL:
        return cached[0]
    try:
        # D8：经门面延迟解析（_facade 替换时 patch("core.dashboard.data._is_running") 生效）
        import core.dashboard.data as _facade

        status = "running" if _facade._is_running(key) else "stopped"
    except Exception:
        status = "stopped"
    if len(_DAEMON_HEALTH_CACHE) > 256:
        _DAEMON_HEALTH_CACHE.clear()
    _DAEMON_HEALTH_CACHE[key] = (status, now)
    return status


# ── 托管态检测（fix-supervisor-hosting-chain D3：managed/unmanaged/stopped）──

_HOSTING_STATE_TTL = 5.0  # 秒；结果在 TTL 内复用（与 daemon_health 同窗口）
_HOSTING_STATE_CACHE: dict = {}  # key=规范化项目根, value=(状态, 时间戳)


def hosting_state(project_root) -> str:
    """项目 daemon 托管态：managed / unmanaged / stopped。

    fix-supervisor-hosting-chain D3/D5：复用 core.fenix_session.hosting_state
    （supervisor 在跑 = managed；有 daemon 进程但无 supervisor = unmanaged；
    两者皆无 = stopped）。检测异常时以 "stopped" 兜底，不使请求 500。
    带短 TTL memo，避免 overview 高频轮询重复扫描 /proc。
    """
    key = str(Path(project_root).expanduser().resolve())
    now = time.monotonic()
    cached = _HOSTING_STATE_CACHE.get(key)
    if cached is not None and now - cached[1] < _HOSTING_STATE_TTL:
        return cached[0]
    try:
        from core.fenix_session import hosting_state as _fs_hosting_state

        state = _fs_hosting_state(key)
    except Exception:
        state = "stopped"
    if len(_HOSTING_STATE_CACHE) > 256:
        _HOSTING_STATE_CACHE.clear()
    _HOSTING_STATE_CACHE[key] = (state, now)
    return state


def project_summary(name: str, path: str, specs=None) -> dict:
    """单个项目的聚合摘要（/api/projects、/api/overview 共用）。

    specs：可选的 parse_state 快照（{spec_name: entry}）。调用方已持有同
    一项目的解析结果时透传，避免 STATE.md 在同一次请求内被重复解析
    （overview 单次解析供摘要与统计两处消费）；省略时内部自行解析，
    行为与原先一致。
    """
    proot = Path(path)
    # D8：parse_state 经门面解析（tests patch 门面同名，与 overview 内 parse_state 一致）
    import core.dashboard.data as _facade

    if specs is None:
        specs = _facade.parse_state(proot)
    status_counts = {}
    for e in specs.values():
        st = e.get("status", "?") or "?"
        status_counts[st] = status_counts.get(st, 0) + 1

    grand_done = grand_total = 0
    problems = 0
    # D2：runs 目录（含 archive）预扫一次按 spec 分组，task_progress 复用该
    # 文件集，不再每 spec 各自 glob（目录 glob 次数为常数；overview 每 2s
    # 轮询、/api/projects 共用本聚合，spec 数大时放大最明显）。
    runs_sigs = _runs_by_spec_sigs(proot)
    for sname in specs:
        entry = specs[sname]
        d, t = _facade.task_progress(
            proot, sname, entry.get("status", ""), files=[Path(p) for p in (runs_sigs.get(sname) or {})]
        )
        grand_done += d
        grand_total += t
        if entry.get("error") and entry.get("status") not in ("done", "pushed"):
            problems += 1

    runs = _facade.get_runs(proot)
    active = sum(1 for r in runs if r["status"] in ("running", "empty"))
    active_by_type = {}
    for r in runs:
        if r["status"] in ("running", "empty"):
            active_by_type[r["agent_type"]] = active_by_type.get(r["agent_type"], 0) + 1

    # 获取项目描述
    effective_config = _facade.read_effective_config(proot)
    description = effective_config.get("description", "")

    # STATE.md mtime 单次容错读：先 exists 再 stat 的两次系统调用之间存在
    # TOCTOU 竞态（文件在间隙被删除——项目被移除/STATE.md 被迁移——则 stat
    # 抛 FileNotFoundError 使整个摘要失败），且同路径 exists+stat 属重复 IO。
    # 改为一次 stat + OSError 兜底；缺失时保持既有取值 0。
    try:
        state_st = (Path(path) / ".fenix" / "STATE.md").stat()
    except OSError:
        state_st = None

    # D8：daemon_health/hosting_state 经门面解析（tests patch 门面同名）
    return {
        "name": name,
        "path": str(path),
        "daemon": _facade.daemon_health(proot),
        "hosting": _facade.hosting_state(proot),
        "spec_count": len(specs),
        "status_counts": status_counts,
        "task_done": grand_done,
        "task_total": grand_total,
        "problems": problems,
        "active_runs": active,
        "active_runs_by_type": active_by_type,
        "scenario_count": sum(_facade.count_scenarios(proot, s) for s in specs),
        "updated": state_st.st_mtime if state_st else 0,
        "description": description,
    }


def _spec_total_duration(entry: dict, runs: list) -> int:
    """SPEC 累计耗时（add-spec-detail-duration：列表 spec_summary / 详情 spec_detail
    共用同一口径，保证两页数值严格一致）。done/pushed 优先读 STATE.md 固化的
    total_duration（done 时刻快照，不随 run 产物清理归零）；其余状态或脏值回退
    实时求和（运行中的 SPEC 耗时应持续增长，固化值仅对终态有意义）。"""
    persisted = None
    if entry.get("status") in ("done", "pushed"):
        raw = entry.get("total_duration")
        if raw is not None:
            try:
                persisted = int(raw)
            except (TypeError, ValueError):
                persisted = None
    if persisted is None:
        # 耗时 = 该 spec 全部运行记录（implementer/verifier/planner/tester 等）的
        # duration_seconds 求和；无任何运行记录时为 0。
        return sum(int(r.get("duration_seconds") or 0) for r in runs)
    return persisted


# ── 全局 impl_run_budget 缓存（add-spec-status-modal-budget D3）──────────────
# budget_effective 需读全局 config agents.impl_run_budget 做 fallback，每次
# spec_summary 调用都 resolve_config 是浪费（O(N) YAML 解析）；以 config 文件
# 签名键缓存一次解析结果，签名不变直返缓存。与 _EFFECTIVE_CONFIG_CACHE 同模式。
_GLOBAL_BUDGET_CACHE: dict = {}
_GLOBAL_BUDGET_CACHE_MAX = 64


def _cached_config_value(project_root, cache: dict, cache_max: int, parse):
    """config 读侧签名缓存公共流程单点（config 读侧各入口共用）。

    统一「（用户级 + 项目级）config.yaml 签名键 → 命中直返 → resolve_config
    → parse(cfg) → 写缓存 → 超 cache_max 清空」样板，各入口只保留自己的
    解析语义（parse 闭包）与缓存表，避免再增配置读侧时复制一半流程、漏掉
    双签名修正。parse 在 cache miss 时才调用（其内部导入不落在命中热路径）。
    """
    import core.dashboard.data as _facade
    from core.config import ConfigLoader

    proot = Path(project_root)
    # fcdd13be884c：resolve_config 是用户级 + 项目级深合并，cache_key 须并入
    # 用户级 config.yaml 签名，否则用户只改用户级 agents.impl_run_budget(_max)
    # 时缓存不失效、持续吐旧值。文件缺失时 _config_file_sig 恒返回 None，稳定。
    cache_key = (
        str(proot.resolve()),
        _facade._config_file_sig(_facade.USER_CONFIG_PATH),
        _facade._config_file_sig(proot / ".fenix" / "config.yaml"),
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    cfg = ConfigLoader.resolve_config(proot)
    value = parse(cfg)
    if len(cache) > cache_max:
        cache.clear()
    cache[cache_key] = value
    return value


# 公开访问面（code-review item 20ad589a3bc4）：quality_gates.py 跨组引用改用
# 公开名（不跨组消费下划线私有名），与 _cached_config_value 同一函数对象单源绑定。
cached_config_value = _cached_config_value


def _resolve_global_impl_run_budget(project_root) -> int:
    """读取全局 agents.impl_run_budget 有效值，fallback DEFAULT_IMPL_RUN_BUDGET。

    结果按（用户级 + 项目级）config.yaml 签名键缓存（config 变化自动失效，
    公共流程见 _cached_config_value），与闸门口径一致：ConfigLoader.get 读
    合并配置 → 按有效上限夹紧 → fallback DEFAULT。
    """

    def _parse(cfg):
        # budget 为 pm_engine 叶子模块：函数内导入避开 pm_engine 包循环
        from core.pm_engine.budget import (
            clamp_impl_run_budget,
            DEFAULT_IMPL_RUN_BUDGET,
            resolve_impl_run_budget_max,
            IMPL_RUN_BUDGET_MAX_KEY,
            IMPL_RUN_BUDGET_MAX_DEFAULT,
        )
        from core.config import ConfigLoader

        max_value = resolve_impl_run_budget_max(
            ConfigLoader.get(cfg, IMPL_RUN_BUDGET_MAX_KEY, IMPL_RUN_BUDGET_MAX_DEFAULT)
        )
        raw = ConfigLoader.get(cfg, "agents.impl_run_budget")
        return clamp_impl_run_budget(raw, max_value) or DEFAULT_IMPL_RUN_BUDGET

    return _cached_config_value(
        project_root, _GLOBAL_BUDGET_CACHE, _GLOBAL_BUDGET_CACHE_MAX, _parse
    )


# ── per-spec 预算上限缓存（fix-dashboard-read-path-performance D1）───────────
# _impl_budget_max 每 spec_summary 调用都 resolve_config（O(YAML) × N spec，
# 实测冷重建 5.6s/220 spec），以（用户级 + 项目级）config.yaml 签名键缓存一次
# 解析结果。
# 与 _GLOBAL_BUDGET_CACHE/_EFFECTIVE_CONFIG_CACHE 同模式；.fenix/config.yaml
# 已入 _spec_dep_sigs，config 变化会触发摘要重算并自然刷新本缓存。
_IMPL_BUDGET_MAX_CACHE: dict = {}
_IMPL_BUDGET_MAX_CACHE_MAX = 64


def _impl_budget_max(project_root) -> int:
    """读取有效预算上限 ``agents.impl_run_budget_max``（缺省 100）。

    供 spec_summary 夹紧 override 与 API 校验共用（与闸门 ImplBudget._impl_budget_max
    同源：同一 resolve_impl_run_budget_max 纯函数 + 同一配置键）。
    结果按（用户级 + 项目级）config.yaml 签名缓存（配置变化自动失效，公共流程
    见 _cached_config_value），避免每 spec 重复 resolve_config
    （fix-dashboard-read-path-performance：读路径冷重建最大单项成本）。
    """

    def _parse(cfg):
        # budget 为 pm_engine 叶子模块：函数内导入避开 pm_engine 包循环
        from core.pm_engine.budget import (
            resolve_impl_run_budget_max,
            IMPL_RUN_BUDGET_MAX_KEY,
            IMPL_RUN_BUDGET_MAX_DEFAULT,
        )
        from core.config import ConfigLoader

        raw = ConfigLoader.get(cfg, IMPL_RUN_BUDGET_MAX_KEY, IMPL_RUN_BUDGET_MAX_DEFAULT)
        return resolve_impl_run_budget_max(raw)

    return _cached_config_value(
        project_root, _IMPL_BUDGET_MAX_CACHE, _IMPL_BUDGET_MAX_CACHE_MAX, _parse
    )


def normalize_depends_on(raw) -> str | None:
    """规范化 depends_on 取值（add-spec-manual-activation D12）。

    公开接口（code-review item b4b0573cd357）：bin/fenix_process.py 等 TUI
    脚本只依赖本公开名；旧私有名经函数体后的别名保持兼容。

    depends_on **未**登记在 `StateParser._parse_content` 的 null→None 归一化
    键表里，而 serialize 对空值恒写 ``- depends_on: null``——STATE.md 里
    无依赖 SPEC 的该字段解析回来后是**字面量字符串 "null"**（本仓库实测
    227/244 条）而非 None。若原样透出，前端裸真值判定会让所有无依赖 SPEC
    被误标「前置依赖」。取值口径与调度器 `_dependencies_satisfied` 的
    ``deps == "null"`` 守卫对齐：
    - 缺失 / None / 空串 / 全空白 / 字面量 "null"（大小写不敏感）→ None
    - 其余 → ``str(raw).strip()`` 原样返回（逗号分隔直接透传）
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() == "null":
        return None
    return text


# 兼容别名：旧私有名继续可用（tests/test_dashboard_data.py 等既有调用方零改动）
_normalize_depends_on = normalize_depends_on


def spec_summary(
    project_root, spec_name: str, entry: dict, runs_files: list | None = None,
    state_entries: dict | None = None, archived_entries: dict | None = None,
) -> dict:
    """单个 SPEC 的摘要（/api/specs 列表项）。

    runs_files: 调用方预扫描的本 spec run 产物路径集（SummaryIndex 每轮经
        _runs_by_spec_sigs 预扫一次后传入）；提供时 get_runs/任务进度/存活
        心跳全部复用该文件集，不再各自 glob 整个 runs 目录（D2：目录 glob
        次数为常数）。缺省 None 时内部自行 glob（详情页等非索引路径）。
    state_entries / archived_entries: 调用方已解析的活跃 STATE.md / 归档清单
        快照（与 project_summary(specs=...) 同模式），仅供 is_spec_archived
        判定复用——SummaryIndex 重建链逐 spec 透传，避免对每个已归档 spec
        全量重解析双 STATE 文件（code-review item c5e751f5a595）。缺省 None
        时 is_spec_archived 内部自行解析，行为与原先一致。
    """
    # 入口单点归一（code-review item c028b72cc8ef）：SummaryIndex 调用链本就
    # 保证 entry 非 None（entry = entry or {}），此处兜底同款归一，函数内
    # 裸取与散落的 `if entry else` 守卫口径统一（守卫已按恒取前支化简，
    # None entry 不再有 AttributeError 分叉）。
    entry = entry or {}
    import core.dashboard.data as _facade

    done, total = _facade.task_progress(
        project_root, spec_name, entry.get("status", ""), files=runs_files
    )
    vp = _facade.parse_verify_progress(project_root, spec_name)
    # 含归档：run 产物被清理后列表页耗时统计不缩水
    runs = _facade.get_runs(project_root, spec_name, include_archive=True, files=runs_files)
    # add-quality-gates-visibility：质量门禁读侧合成（fail-open，详情页同源；
    # D8：经门面解析供测试打桩）
    gates = _facade.parse_quality_gates(project_root, spec_name, entry=entry, runs=runs)
    # ocr 车道在飞（gates 阶段第二支判据）
    lane_running = any(
        isinstance(it, dict) and it.get("id") == "code-review" and it.get("status") == "running"
        for it in gates.get("items", [])
    )
    # add-task-progress-verify-phase + add-quality-gates-visibility 修订：阶段
    # 判定单点在后端（前端只消费不重复判定）。窗口两支——
    #   ① implementing ∧ 任务全勾 ∧ 门禁可见 ∧ 未全了结 → gates（收尾门禁进行中）
    #   ② testing ∧ ocr 车道 running → gates（并行审查进行中，优先于 verify）
    # 其余一切状态按 impl；fast-track 瞬时连转不停留 testing，天然恒 impl。
    if entry.get("status") == "testing":
        phase = "gates" if lane_running else "verify"
    elif (
        entry.get("status") == "implementing"
        and total > 0
        and done == total
        and gates.get("exists")
        and gates.get("done", 0) < gates.get("total", 6)
    ):
        phase = "gates"
    else:
        phase = "impl"
    total_duration = _spec_total_duration(entry, runs)
    # add-fast-track-mode（task 7.1）：执行模式（读 .spec.yaml，缺省 full）
    from core.spec_mode import read_spec_mode

    mode = read_spec_mode(project_root, spec_name)
    # add-spec-status-modal-budget D3：per-spec 预算字段
    # 三字段读取与预算闸门同源（clamp_impl_run_budget 单点），前端不重复实现解析。
    # open-impl-budget-ceiling：夹紧上限改由可配置键解析，前端界面范围与此同源。
    from core.pm_engine.budget import (
        clamp_impl_run_budget,
        IMPL_RUN_BUDGET_OVERRIDE_FIELD,
        DEFAULT_IMPL_RUN_BUDGET,
    )

    budget_max = _impl_budget_max(project_root)
    budget_override_raw = entry.get(IMPL_RUN_BUDGET_OVERRIDE_FIELD)
    budget_override = clamp_impl_run_budget(budget_override_raw, budget_max)
    try:
        budget_used = int(entry.get("_impl_run_budget_used", 0) or 0)
    except (TypeError, ValueError):
        budget_used = 0
    if budget_override is not None:
        budget_effective = budget_override
    else:
        budget_effective = _resolve_global_impl_run_budget(project_root)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        # 快照透传（c5e751f5a595）：SummaryIndex 调用链复用本轮已解析的活跃/
        # 清单快照，非索引路径（缺省 None）内部自解析，行为不变。
        "archived": _facade.is_spec_archived(
            project_root, spec_name,
            state_entries=state_entries, archived_entries=archived_entries,
        ),
        # add-archive-state-migration D4：迁出溯源字段透传（清单条目自带，
        # 活跃条目无该键 → None）。条目来自合并快照（SummaryIndex 活跃 ∪ 清单），
        # 迁出条目的字段即清单小节原值。
        "archived_at": entry.get("archived_at"),
        "archived_by": entry.get("archived_by"),
        "mode": mode,
        "priority": entry.get("priority"),
        "created": entry.get("created"),
        "updated": entry.get("updated"),
        "error": entry.get("error"),
        # add-spec-review-gate D10：评审 run 引用（reviewing 态必有值，
        # 前端据此展示在飞评审 run_id）
        "reviewer_run": entry.get("reviewer_run"),
        # add-spec-scheduling-controls D6：定时拾取（start_after）与定时解冻
        # （frozen_until）规范值（ISO8601 UTC 或 null），前端列表据此渲染
        # 定时 Tag/倒计时与冻结模式。
        "start_after": _facade.get_spec_start_after(entry),
        "frozen_until": _facade.get_frozen_until(entry),
        # add-spec-manual-activation D12：depends_on 规范化值（列表页「前置依赖」
        # tag 的数据源）。MUST NOT 直接透传 entry.get("depends_on")——该字段未
        # 登记在 StateParser._parse_content 的 null→None 归一化键表，serialize 对
        # 空值恒写 `depends_on: null`，透传会让 227/244 条无依赖 SPEC 拿到字面量
        # "null" 而被误标（见 normalize_depends_on docstring）。
        "depends_on": normalize_depends_on(entry.get("depends_on")),
        # 冻结态（结构化字段优先，回退文本前缀）：前端据此渲染解冻入口。
        # 自动冻结（内容完整性闸门 / 预算闸门 / env 阻塞）只认文本会漏判。
        "frozen": _facade.is_spec_frozen(entry),
        # 取消保持态（add-cancelled-spec-resume-action D4）：前端「恢复运行」
        # 区块渲染判据。取值为归一化布尔——_cancelled_hold 已登记进
        # state.py parse_state 归一化表（与 frozen 同口径），文本 False 不再
        # 以真值字符串漏出；此处不写 bool(entry.get(...))，保持防回归口径。
        "cancelled_hold": normalize_bool_flag(entry.get("_cancelled_hold")),
        # add-task-progress-verify-phase + add-quality-gates-visibility：阶段
        # 判定单点在后端（见上方窗口两支注释），前端只消费该字段不重复判定。
        "progress_phase": phase,
        "verify_current": vp.get("current", ""),
        # add-quality-gates-visibility：门禁完成度与当前进展文案（列表 gates
        # 阶段渲染数据源；门禁不可见时 done=0/total=6/current 空串）
        "gates_done": gates.get("done", 0),
        "gates_total": gates.get("total", 6),
        "gates_current": gates.get("current", ""),
        "task_done": done,
        "task_total": total,
        # run 层实时进度（fix-implementer-task-progress D3）：tasks.md 快照失效
        # （subject 无编号 / agent 不勾 tasks.md）时仍能看到 run 推进。
        "run_progress": _facade.run_task_progress(project_root, spec_name, files=runs_files),
        # 存活心跳（2026-09-15 原地补充）：run_progress 依赖 TaskCreate/TaskUpdate，
        # 该工具族虽经 CLAUDE_CODE_ENABLE_TODO_TOOLS=1 恢复，实现期间 agent 未必
        # 立刻建 Task、历史 run 也可能无事件。run_activity 以「产物是否
        # 仍在写」提供不依赖任务工具的存活线索，前端据此在进度单元显示「进行中」。
        "run_activity": _facade.run_activity(project_root, spec_name, files=runs_files),
        "verify_done": vp.get("done", 0),
        "verify_total": vp.get("total", 0),
        "verify_error": vp.get("error"),
        # verification-phase-progress：出题进度（生成阶段 verify_total=0 时有值）
        "generation": _facade.spec_generation_progress(project_root, spec_name, entry, vp=vp),
        "scenario_count": _facade.count_scenarios(project_root, spec_name),
        "total_duration": total_duration,
        "latest_run": runs[0]["run_id"] if runs else None,
        "latest_run_status": runs[0]["status"] if runs else None,
        # add-spec-status-modal-budget D3：per-spec 预算覆盖三字段
        # （used 容错读；override 非法视为 null；effective 与闸门同源解析）
        "budget_used": budget_used,
        "budget_override": budget_override,
        "budget_effective": budget_effective,
        # open-impl-budget-ceiling：有效上限（前端覆盖输入框 max 与此同源）
        "budget_max": budget_max,
        # evo-infra-failure-budget-exempt R3：infra 与 product 失败构成分离——
        # _verify_infra_rounds 为本轮验证周期 infra 轮次（纯观测，不参与
        # MAX_VERIFY_FAIL_ROUNDS 冻结；验证 PASS 归零）；_infra_failure_count
        # 为生命周期累计观测值（不归零，同 _budget_exempt_runs 范式）。
        "verify_infra_rounds": _int_or_zero(entry.get("_verify_infra_rounds")),
        "infra_failure_count": _int_or_zero(entry.get("_infra_failure_count")),
        # add-verify-lane-throughput 3.3：judge 治理读侧观测（design 决策 5）——
        # fast-track 复用命中与真实派发的生命周期累计，fast-track 命中率 =
        # hits / (hits + dispatches) 由消费方计算；历史 spec 无记录 → None
        # （缺失容错，与 0 区分「未启用期」）。
        "judge_fasttrack_hits": _judge_stat_or_none(entry.get("_judge_fasttrack_hits")),
        "judge_real_dispatches": _judge_stat_or_none(entry.get("_judge_real_dispatches")),
    }


# ── spec 摘要索引（dashboard-spec-summary-index D1） ─────────────


def _judge_stat_or_none(value):
    """judge 治理统计字段容错读（add-verify-lane-throughput 3.3）。

    合法整数（含数字串）→ int；缺失/None/非法 → None（fail-open，历史
    spec 无该字段时读侧不炸、不为 0）。
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError：非有限浮点（int(float('inf'))）。STATE.md 为 YAML 方言，
        # 字段被写成 .inf 时解析为 float inf，与 code_review._line_key 同口径。
        return None


def _stat_sig(path: Path):
    """文件签名 (mtime_ns, size)；缺失/不可 stat 返回 None。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _runs_by_spec_sigs(proot: Path) -> dict:
    """扫描 .fenix/runs（含 archive）一次，按 spec 分组各 run 文件签名。

    返回 {spec_name: {run_path_str: (mtime_ns, size)}}。全目录只 glob 一次，
    避免每 spec 各自 glob 的 O(N²) 放大（add-dashboard-incremental-data D1）。
    """
    from core.agent_runner.run_files import run_spec_part

    runs_dir = proot / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return {}
    out: dict = {}
    try:
        paths = list(runs_dir.glob("*.jsonl"))
        arc = runs_dir / "archive"
        if arc.is_dir():
            paths.extend(arc.glob("*.jsonl"))
    except OSError:
        return out
    for p in paths:
        sig = _stat_sig(p)
        if sig is None:
            continue
        spec_part = run_spec_part(p.stem)
        if not spec_part:
            continue
        out.setdefault(spec_part, {})[str(p)] = sig
    return out


# 公开访问面（code-review item c0c4df6ac475）：project_routes.py 跨组引用改用
# 公开名（不跨组消费下划线私有名），与 _runs_by_spec_sigs 同一函数对象单源绑定。
runs_by_spec_sigs = _runs_by_spec_sigs


# ── 2.1a：STATE 条目指纹（fix-dashboard-read-path-performance D1） ──────────
# spec_summary 输出大量直接由 STATE 条目字段决定（status/priority/created/
# updated/error/reviewer_run/start_after/frozen_until/frozen/预算覆盖/_ 前缀
# 计数，以及经 status 派生的 progress_phase/出题进度/任务进度）。只比依赖文件
# 签名会让「条目字段变化但依赖文件未变」的 spec 永远返回陈旧摘要（spec 被预算/
# env 闸门置 blocked、或自动冻结时，tasks.md/.spec.yaml/specs/run 产物均未变；
# 现状由 state_changed → idx={} 全量重建掩盖）。宁多勿漏：与 spec_summary
# 实际读 entry 的字段一一对应。
_ENTRY_SIG_KEYS = (
    "status",
    "priority",
    "created",
    "updated",
    "error",
    "reviewer_run",
    "start_after",
    "frozen_until",
    "frozen",
    # add-cancelled-spec-resume-action 2.4：摘要新增读取取消保持字段，
    # 缓存指纹白名单同步登记（宁多勿漏契约：仅保持标记变化时也要失效缓存）
    "_cancelled_hold",
    "depends_on",
    IMPL_RUN_BUDGET_OVERRIDE_FIELD,
    "_impl_run_budget_used",
    "_verify_infra_rounds",
    "_infra_failure_count",
    # add-verify-lane-throughput 3.3：judge 治理观测字段（spec_summary 读侧），
    # fast-track 命中不产生签名集内任何文件变化，须靠字段指纹失效缓存
    "_judge_fasttrack_hits",
    "_judge_real_dispatches",
    # done/pushed 态经 _spec_total_duration 读取的固化耗时（state_machine
    # done→done 幂等覆盖时会重算），与迁出溯源透传字段 archived_at/archived_by
    # （evict_spec 写入清单条目）：仅这些字段变化时也须失效缓存
    "total_duration",
    "archived_at",
    "archived_by",
)


def _entry_fingerprint(entry: dict) -> str:
    """把 spec 的 STATE 条目关键字段序列化为稳定指纹（并入 _spec_dep_sigs）。

    仅收集 _ENTRY_SIG_KEYS 白名单字段（非整个 entry：_tokens_in 等高频变化但
    不影响 spec_summary 输出的字段不参与，避免无谓重算）。None 与缺失同义；
    值统一经 json.dumps(default=str) 归一，保证跨类型稳定比较。
    """
    if not entry:
        return ""
    return json.dumps(
        {k: entry.get(k) for k in _ENTRY_SIG_KEYS},
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )


def _spec_dep_sigs(proot: Path, spec_name: str, entry: dict, runs_sigs: dict) -> dict:
    """单个 spec 摘要的依赖签名集合（对齐 spec_summary 实际读路径）。

    覆盖 tasks.md（implementing 时含实现 worktree 副本）/ specs/ 目录整体 /
    .spec.yaml / verification-report.md / verify-progress 相关文件 /
    该 spec 的 run 产物（由调用方预扫描 runs_sigs 传入）以及 STATE 条目指纹
    （2.1a：条目字段变化但依赖文件未变时也必须失效）。宁多勿漏：把 specs/
    目录整体入签名，依赖文件集合单向全覆盖。
    """
    sigs: dict = {}
    changes = proot / "spec" / "changes" / spec_name

    import core.dashboard.data as _facade

    def add(p: Path):
        sig = _stat_sig(p)
        if sig is not None:
            sigs[str(p)] = sig

    # add-archive-state-migration BUG-01：活跃目录存在性本身入签名。archived
    # 标记以活跃目录存在性为可见性单源之一（is_spec_archived），而目录可能仅含
    # 不入签名的文件（如 proposal.md）——目录在首建索引后重建/删除时其余签名
    # 零变化，陈旧 archived 标记永不重算。目录 sig（mtime_ns, size）同时覆盖
    # 直接子项增删，宁多勿漏。
    add(changes)
    add(changes / "tasks.md")
    add(changes / ".spec.yaml")
    add(changes / "verification-report.md")
    specs_dir = changes / "specs"
    if specs_dir.is_dir():
        try:
            for sf in specs_dir.rglob("*.md"):
                add(sf)
        except OSError:
            pass
    add(proot / ".fenix" / "verify-progress" / f"{spec_name}.json")
    vp_dir = proot / ".fenix" / "verify-progress" / spec_name
    add(vp_dir / "report.json")
    add(vp_dir / "test_scenarios.json")
    # add-quality-gates-visibility：门禁落盘与 ocr 车道产物入摘要失效签名
    # （渐进落盘期间列表 gates 阶段须实时刷新）
    add(vp_dir / "quality-gates.json")
    add(vp_dir / "code-review.json")
    # full-suite 门的框架侧产物源（parse_quality_gates _full_suite_product_status
    # 经 read_result 消费，按分支指纹匹配可见）：回归快照单独落盘而本 spec
    # 其余依赖未变时也须失效摘要（宁多勿漏，与 spec_detail_signature 同源对齐）
    add(proot / ".fenix" / "regression" / "last-run.json")
    # run-result 两路候选（parse_verify_progress 缺失时回退链
    # parse_run_result_scenarios 消费的专属副本与共享根文件）同入签名
    # （宁多勿漏）：与 spec_detail_signature 的源集对齐，否则 run-result
    # 重写后签名比对判未变，回退链上的 verify_done/total/current 持续陈旧。
    add(vp_dir / ".fenix-run-result.json")
    add(proot / ".fenix" / ".fenix-run-result.json")
    # implementing 态 worktree 产物统一在此登记（含 worktree tasks.md，
    # 对应上方项目级 tasks.md；勿再另起重复 implementing 分支）
    # [fenix-ignore:72c95cb763b2] 现行代码已是单个 implementing 分支（一次 find_implementer_worktree 后统一 add tasks.md 与 quality-gates.json/code-review.json），无重复解析与重复 add
    if entry and entry.get("status") == "implementing":
        wt = _facade.find_implementer_worktree(proot, spec_name)
        if wt is not None:
            add(wt / "spec" / "changes" / spec_name / "tasks.md")
            add(wt / ".fenix" / "verify-progress" / spec_name / "quality-gates.json")
            add(wt / ".fenix" / "verify-progress" / spec_name / "code-review.json")
    # [fenix-ignore:01fa63282f46] 与 fcdd13be884c 重复：缓存键与 _spec_dep_sigs 均已并入用户级 config.yaml 签名，问题已修不成立
    # add-spec-status-modal-budget D3：budget_effective 依赖全局 config
    # （agents.impl_run_budget 覆盖优先解析的兜底来源），项目级与用户级
    # config.yaml 变化须触发摘要失效（宁多勿漏原则）。
    add(_facade.USER_CONFIG_PATH)
    add(proot / ".fenix" / "config.yaml")
    for p, sig in (runs_sigs.get(spec_name) or {}).items():
        sigs[p] = sig
    # 2.1a：STATE 条目字段并入失效签名（键带哨兵前缀避免与路径键冲突）
    sigs["__entry__"] = _entry_fingerprint(entry)
    return sigs


class SummaryIndex:
    """每项目 spec 摘要内存索引（dashboard-spec-summary-index D1）。

    结构：{proot_key: {spec_name: {"summary": dict, "sigs": {path: (mtime_ns, size)}}}}

    - 惰性构建：首次 get() 触发；watcher 与 server 共享同一实例（单写者 watcher
      线程，读者 HTTP 线程，经 RLock 保护——读多写少场景足够）。
    - 失效策略：每 spec 先比对依赖签名（文件签名 + STATE 条目指纹），未变直返
      缓存；变化只重算该 spec。
    - STATE.md 签名变化 → 重新解析 STATE.md 快照，但保留既有 idx：新增 spec
      自然不在 idx 中（重算）、删除 spec 由清理步骤剔除、其余 spec 逐条比对
      签名（fix-dashboard-read-path-performance D1：增量失效，不再全量重建）。
    - 有界性：摘要 dict 常驻内存（10000 spec ≈ 数十 MB，可接受）；签名只对存在
      路径记录，删除的 spec 目录从索引剔除。
    - 锁粒度取舍（code-review item 8b43aa321467）：get()/invalidation_signature()
      共用同一把实例级 RLock 且覆盖全部项目——任一项目的冷/增量重建（全项目
      runs 签名扫描 + 逐 spec 签名比对 + 未命中 spec 的完整摘要重算，含
      parse_quality_gates/count_scenarios/runs 读取等 IO）期间，其余项目的读请求
      会被串行化阻塞。属已知取舍：写侧仅 watcher 单写者，HTTP 并发轮询规模
      有限，按项目分槽锁（或重 IO 移出锁外）的收益不抵复杂度，暂不引入。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._idx: dict = {}
        self._state_sigs: dict = {}
        self._state_snapshot: dict = {}
        # 归档清单快照（add-archive-state-migration D4）：签名变化才重新解析
        self._arch_sigs: dict = {}
        self._arch_snapshot: dict = {}

    def get(self, proot, specs: dict | None = None, state_sig=None) -> list:
        """返回该项目的全部 spec_summary 列表（顺序与 specs dict 一致）。

        Args:
            proot: 项目根路径
            specs: parse_state 快照 {spec_name: entry}；省略时复用索引内缓存快照
                （STATE.md 签名未变则直接复用，避免每请求全量解析 STATE.md）。
            state_sig: STATE.md 的 (mtime_ns, size) 签名；变化时重新解析
                STATE.md 快照并按 spec 增量失效（保留未变 spec 的缓存摘要）。
        """
        key = str(Path(proot).resolve())
        # 跨组引用经门面延迟解析（D4/D8）
        import core.dashboard.data as _facade

        with self._lock:
            if state_sig is None:
                state_sig = _stat_sig(proot / ".fenix" / "STATE.md")

            # STATE.md 签名变化 → 重新解析快照（新增/删除 spec 只有 parse_state
            # 才能发现；idx 保留，仅增量重算签名变化的 spec——见下方循环）。
            # STATE.md 整体消失（sig None）但索引曾记录过该 key 签名 → 同样视为
            # 变化：parse_state 的空结果刷新快照、已删 spec 经下方清理剔除，否则
            # 陈旧摘要持续吐出直至重启；初始化窗口（key 从未入 _state_sigs，该表
            # 仅在 sig 非 None 时记录）sig 为 None 不算变更，维持既有行为。
            state_changed = (
                state_sig is not None and self._state_sigs.get(key) != state_sig
            ) or (state_sig is None and key in self._state_sigs)
            if specs is None:
                if not state_changed:
                    specs = self._state_snapshot.get(key)
                if specs is None:
                    specs = _facade.parse_state(proot)
                    self._state_snapshot[key] = specs

            idx = self._idx.get(key)
            # state_changed 时保留既有 idx（增量失效：只对新增/删除/签名
            # 变化的 spec 重算）；全量重建仅用于首次构建（idx is None）或
            # 索引损坏（entry cache 中 summary/sigs 缺失，由 per-spec sig
            # 比对自然触发重建）。
            if idx is None:
                idx = {}

            # 合并归档清单条目（add-archive-state-migration D4）：活跃 ∪ 清单，
            # 同名单活跃侧优先。合并单点在本索引——/api/specs 与 watcher SSE
            # 推送同源消费，迁出条目在两侧都保持可见（watcher 的 diff 基线
            # 不再把迁出误判为删除行）。快照仅存活跃侧（下方回写
            # active_specs），清单文件删除/清空时不会经快照泄漏幽灵条目。
            active_specs = specs
            arch_sig = _stat_sig(proot / ".fenix" / "STATE.archive.md")
            if arch_sig != self._arch_sigs.get(key) or key not in self._arch_snapshot:
                self._arch_snapshot[key] = _facade.parse_archived_state(proot)
                self._arch_sigs[key] = arch_sig
            archived_entries = self._arch_snapshot.get(key) or {}
            if archived_entries:
                merged = dict(archived_entries)
                merged.update(specs or {})
                specs = merged

            runs_sigs = _runs_by_spec_sigs(proot)
            out = []
            for spec_name, entry in specs.items():
                entry = entry or {}
                cached = idx.get(spec_name)
                sigs = _spec_dep_sigs(proot, spec_name, entry, runs_sigs)
                if cached is not None and cached.get("sigs") == sigs:
                    out.append(cached["summary"])
                    continue
                # D8：经门面延迟解析（tests 以 dash_data.spec_summary=... 替换）
                # D2：复用本轮预扫描的 runs_sigs 分组结果，spec_summary 不再
                # 自行 glob runs/archive 目录（目录 glob 次数为常数）。
                spec_files = [Path(p) for p in (runs_sigs.get(spec_name) or {})]
                # c5e751f5a595：透传本轮已解析的活跃（active_specs）与归档清单
                # （archived_entries）快照，is_spec_archived 不再对每个已归档
                # spec 全量重解析双 STATE 文件（重建期 O(N) 放大）。
                summary = _facade.spec_summary(
                    proot, spec_name, entry, runs_files=spec_files,
                    state_entries=active_specs, archived_entries=archived_entries,
                )
                idx[spec_name] = {"summary": summary, "sigs": sigs}
                out.append(summary)

            # 清理已删除 spec 的签名条目
            for stale in [s for s in idx if s not in specs]:
                del idx[stale]

            self._idx[key] = idx
            if state_sig is not None:
                self._state_sigs[key] = state_sig
                # 快照只回写活跃侧（合并前的 specs）：清单快照独立维护（见上
                # _arch_sigs/_arch_snapshot），两侧失效互不牵连
                if active_specs is not None:
                    self._state_snapshot[key] = active_specs
            return out

    def state_snapshot(self, proot) -> dict:
        """复用索引的 STATE.md 解析快照（签名未变免重解析，变化即刷新）。

        ETag 签名函数（如 /api/specs/<spec> 的条目存在性判定）廉价消费：
        与 get() 同一失效键（STATE.md 签名）与同一快照缓存，不引入第二套
        解析。返回活跃侧 {spec_name: entry}（与 _state_snapshot 同源）。
        """
        import core.dashboard.data as _facade

        key = str(Path(proot).resolve())
        with self._lock:
            state_sig = _stat_sig(proot / ".fenix" / "STATE.md")
            state_changed = (
                state_sig is not None and self._state_sigs.get(key) != state_sig
            ) or (state_sig is None and key in self._state_sigs)
            specs = self._state_snapshot.get(key)
            if state_changed or specs is None:
                specs = _facade.parse_state(proot)
                self._state_snapshot[key] = specs
                if state_sig is not None:
                    self._state_sigs[key] = state_sig
            return specs

    def invalidation_signature(self, proot) -> str:
        """摘要失效键组合哈希（/api/specs ETag 单源，add-dashboard-paging-and-etag 1.3）。

        与 get() 逐 spec 失效键**完全同源**（_spec_dep_sigs + STATE/归档/runs
        签名）：响应中任一摘要将被重算 ⇔ 此哈希翻转——签名完整性由复用同一
        失效键集保证，不另建第二套扫描。复用 state/arch 解析快照（签名未变
        不重解析），只 stat 不读内容；成本 ≈ get() 每请求本就支付的失效键
        计算（per-spec sig 本就每次现算比对）。
        """
        from . import signature as _sigmod

        # 经门面延迟解析（D8：tests 以 dash_data.parse_archived_state=… 替换生效）
        import core.dashboard.data as _facade

        proot = Path(proot)
        key = str(proot.resolve())
        with self._lock:
            state_sig = _stat_sig(proot / ".fenix" / "STATE.md")
            # RLock 可重入：state_snapshot 复用同一把锁与同一失效键
            specs = self.state_snapshot(proot)
            arch_sig = _stat_sig(proot / ".fenix" / "STATE.archive.md")
            if arch_sig != self._arch_sigs.get(key) or key not in self._arch_snapshot:
                self._arch_snapshot[key] = _facade.parse_archived_state(proot)
                self._arch_sigs[key] = arch_sig
            runs_sigs = _runs_by_spec_sigs(proot)
            per_spec = []
            for spec_name, entry in specs.items():
                sigs = _spec_dep_sigs(proot, spec_name, entry or {}, runs_sigs)
                # 值含 (mtime_ns, size) 元组与 __entry__ 指纹串；键唯一，
                # 排序只比键不比值（跨类型值不参与比较）
                per_spec.append((spec_name, sorted((k, v) for k, v in sigs.items())))
            per_spec.sort()
            all_runs = sorted(
                (str(p), s[0], s[1])
                for d in runs_sigs.values()
                for p, s in d.items()
            )
            return _sigmod.combine(
                [("state", state_sig), ("arch", arch_sig), ("runs", all_runs), ("specs", per_spec)]
            )


# ── SPEC 生命周期时间轴 ──────────────────────────────────────────

# 生命周期线性序（状态机文档 drafted → [reviewing →] ready → … 一致）。
# 未登记的键走 .get(s, 9) 哨兵 9（高于 pushed=7）——add-spec-review-gate 新增
# reviewing 态时漏登记，reviewing→ready 被算成 1<9 的假回退并落「状态回退」
# 兜底文案（2026-09-15 evo-admin-dispatch-failure-escalation 实测：草稿→评审中
# →就绪的正常推进被挂回退徽标）。reviewing 为评审门，位于 drafted 与 ready 之间。
# blocked 有意不登记（哨兵）：进入 blocked 为前向（如 implementing→blocked），
# 离开 blocked（blocked→ready / blocked→testing / blocked→reviewing）判回退。


def spec_detail(project_root, spec_name: str, entry: dict) -> dict:
    """单个 SPEC 的完整详情（/api/specs/<spec>）。"""
    import core.dashboard.data as _facade

    report = _facade.parse_report(project_root, spec_name)
    bugs = _facade.parse_bugs(project_root, spec_name)
    scenarios = (
        report.get("scenarios", []) if report.get("exists") and not report.get("error") else []
    )
    # scenarios 为非列表标量（report.json 被手改/部分写入）时按空处理，
    # 对齐 artifacts.parse_bugs 防护口径：否则迭代得到字符/键名，垃圾条目
    # 原样进入响应；置空后由下方 run-result 兜底接管（fail-closed 同语义）。
    if not isinstance(scenarios, list):
        scenarios = []
    # 场景内截图同样归一化为文件名（report.json 存的是服务器本地绝对路径）
    scenarios = [
        (
            {
                **sc,
                "screenshots": [
                    os.path.basename(s)
                    for s in sc.get("screenshots", [])
                    if isinstance(s, str) and s.strip()
                ],
            }
            if isinstance(sc, dict)
            else sc
        )
        for sc in scenarios
    ]
    # 合成报告（report.json 缺失/无 scenarios）时，从 .fenix-run-result.json 兜底取
    # 逐场景明细，使 Dashboard「场景结果」页签即便在无 report.json 的合成产物下也能
    # 渲染逐场景节点（fix-add-verify-report-gate Bug 2 根因）。
    if not scenarios:
        scenarios = _facade.parse_run_result_scenarios(project_root, spec_name)
    screenshots = _facade.list_screenshots(project_root, spec_name)
    # 含归档：spec 详情「运行历史」可回看已归档的旧 run
    runs = _facade.get_runs(project_root, spec_name, include_archive=True)
    verdict = _facade.parse_verdict(project_root, spec_name)
    spec_status = entry.get("status", "")
    # add-fast-track-mode（task 7.1）：执行模式（读 .spec.yaml，缺省 full）
    from core.spec_mode import read_spec_mode

    mode = read_spec_mode(project_root, spec_name)
    # 时间轴（含运行节点 cost_usd；计费开关关闭时 get_spec_timeline 不下发）；
    # created 锚定读取窗口：STATE 条目的 created 使早期事件不被日志尾窗截断
    # 跨组引用（timeline 组的 get_spec_timeline/timeline_with_retry）经门面延迟解析（D4）
    timeline = _facade.timeline_with_retry(
        # entry 透传（add-timeline-ocr-lane-visibility 任务 1.2）：最新「→ testing」
        # 节点附 ocr 门状态，与下方 quality_gates Card 同参同源合成
        _facade.get_spec_timeline(project_root, spec_name, entry.get("created") or "", entry=entry),
        project_root,
        entry,
    )
    # improve-provider-billing-config（D2）：SPEC 级成本合计——计价表非空
    # （有任一声明 billing 的卡片）时进入计价分支；单 run 计价由匹配函数自行
    # 判定未开启卡片 → None（未开启卡片 run 不计入 priced_runs）。
    cost_summary = None
    billing_table = _facade.load_billing_config(project_root)
    if billing_table:
        cost_summary = _facade.cost_summary_from_timeline(timeline)
    # tasks 与 tasks_note 共享一次解析（code-review item 6d2eca146f3c）：
    # tasks_note 传 groups 免去对 tasks.md 的第二次完整 parse_tasks
    tasks = _facade.parse_tasks(project_root, spec_name, spec_status)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        "mode": mode,
        "priority": entry.get("priority"),
        "created": entry.get("created"),
        "updated": entry.get("updated"),
        "error": entry.get("error"),
        "branch": entry.get("branch"),
        "implementer_run": entry.get("implementer_run"),
        "tester_run": entry.get("tester_run"),
        # add-cancelled-spec-resume-action 2.2：取消保持标记透传（与列表摘要
        # 同口径单点归一，零漂移；弹窗详情态渲染判据）
        "cancelled_hold": normalize_bool_flag(entry.get("_cancelled_hold")) if entry else False,
        # add-spec-manual-activation D12：与列表摘要 spec_summary 同口径单点归一——
        # STATE.md 对空依赖恒写 `depends_on: null`，透传会让详情态复现列表页
        # 已修掉的「前置依赖」误标（见 normalize_depends_on docstring）
        "depends_on": normalize_depends_on(entry.get("depends_on")),
        "tasks": tasks,
        "tasks_note": _facade.tasks_note(project_root, spec_name, spec_status, groups=tasks),
        "run_progress": _facade.run_task_progress(project_root, spec_name),
        "run_activity": _facade.run_activity(project_root, spec_name),
        "verify_progress": _facade.parse_verify_progress(project_root, spec_name),
        # add-quality-gates-visibility：详情页「质量门禁」Card 数据源
        # （{exists, done, total, current, items}；SSE 全量 detail 推送自动携带）
        "quality_gates": _facade.parse_quality_gates(
            project_root, spec_name, entry=entry, runs=runs
        ),
        # verification-phase-progress：出题进度（生成阶段 verify_progress 为空态，
        # 详情页验证进度卡片据此展示「出题 N/M」而非「暂无验证进度」）
        "generation": _facade.spec_generation_progress(project_root, spec_name, entry),
        "report": {
            "exists": report.get("exists", False),
            "error": report.get("error"),
            "timestamp": report.get("timestamp"),
            "summary": report.get("summary"),
            # add-planready-artifact-gate D4：降级标注（框架合成报告时从
            # degrade_context.json 注入 report.json 顶层 degrade_annotation），
            # 前端报告区据此条件渲染「⚠️ 降级说明」一行提示；无降级时缺省。
            "degrade_annotation": report.get("degrade_annotation"),
        },
        "scenarios": scenarios,
        "bugs": bugs,
        # fix-verify-verdict-visibility：被分类过滤（非 product-bug）的失败/错误场景摘要，
        # 与 bugs 互补互斥；旧格式 report.json（无 classification）不产生条目
        "filtered_failures": _facade.parse_filtered_failures(project_root, spec_name),
        "screenshots": screenshots,
        "runs": runs,
        "verdict": verdict,
        "timeline": timeline,
        # add-spec-detail-duration：详情页「耗时」与列表页「耗时」列同源同口径
        # （runs 已含归档，见 _spec_total_duration）
        "total_duration": _spec_total_duration(entry, runs),
        # add-model-billing-cost-display：SPEC 级成本合计（计费关闭时缺省 None）
        "cost_summary": cost_summary,
        # add-cost-observability（D2）：治理区展示的累计 token 与成本可用性标记。
        # _cost_usd 仅在网关真实回传时存在（不伪造金额，spec「金额展示不伪造」）。
        "token_usage": _token_usage_view(entry),
        # evo-infra-failure-budget-exempt R3：infra 与 product 失败构成分离——
        # verify_infra_rounds 本轮验证周期 infra 轮次（观测，不参与冻结）；
        # infra_failure_count 生命周期累计（不归零）；fail_rounds product 轮次。
        # dashboard 据此渲染「infra vs product」失败构成。
        "failure_composition": {
            "verify_infra_rounds": _int_or_zero(entry.get(VERIFY_INFRA_ROUNDS_FIELD)),
            "infra_failure_count": _int_or_zero(entry.get(INFRA_FAILURE_COUNT_FIELD)),
            "verify_fail_rounds": _int_or_zero(entry.get("_verify_fail_rounds")),
        },
    }


def _int_or_zero(value):
    """STATE 数值字段容错读（与 _judge_stat_or_none 同风格，补齐同文件防护）。

    合法整数（含数字串）→ int；缺失/None/非法文本 → 0。STATE.md 持久字段
    为字符串，被手工改坏为非数值文本时直转抛 ValueError 会沿摘要接口穿透 500。
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError：非有限浮点（int(float('inf'))），同 _judge_stat_or_none 口径。
        return 0


def _token_usage_view(entry: dict) -> dict:
    """把 STATE 内部 token 字段规整为治理区展示结构（add-cost-observability D2）。

    返回固定结构：
        {
          "tokens_in": int, "tokens_out": int,
          "cache_creation_input_tokens": int | None,  # 分项自 add-cache-hit-display 起累计；历史 spec 无字段→None
          "cache_read_input_tokens": int | None,
          "cost_usd": float | None,    # None = 网关未回传，界面展示「成本不可用」
          "cost_available": bool,       # 成本字段是否可展示
        }
    STATE 持久累计 _tokens_in/_tokens_out/_cost_usd 及缓存分项 _cache_read_tokens/
    _cache_creation_tokens（分项 cache 入 input）；分项为 None 表示该 spec 未记录过
    分项数据（历史条目或字段非法），前端不显示缓存括号。
    """
    if not isinstance(entry, dict):
        entry = {}
    tokens_in = _int_or_zero(entry.get("_tokens_in"))
    tokens_out = _int_or_zero(entry.get("_tokens_out"))
    # 分项字段：缺失（历史 spec）或非法文本均按 None（未记录）处理（STATE 读出为
    # 字符串），复用 _judge_stat_or_none 的 fail-open 口径——前端不显示缓存括号
    cache_read_val = _judge_stat_or_none(entry.get("_cache_read_tokens"))
    cache_creation_val = _judge_stat_or_none(entry.get("_cache_creation_tokens"))
    cost = entry.get("_cost_usd")
    if cost is None:
        cost_val = None
        cost_available = False
    else:
        try:
            cost_val = float(cost)
            # code-review item 9b4dfa399776：STATE.md 为 YAML 方言，字段被手改为
            # .inf/.nan 时解析为非有限 float，float() 会成功放行——api 层
            # json.dumps 默认 allow_nan 输出 Infinity/NaN 字面量，浏览器
            # JSON.parse 整份响应失败，详情/列表接口不可用。非有限值按
            # None/cost_available=False 处理，与 _judge_stat_or_none 的
            # fail-open 口径对齐。
            if not math.isfinite(cost_val):
                raise ValueError("non-finite cost")
            cost_available = True
        except (TypeError, ValueError):
            cost_val = None
            cost_available = False
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_creation_input_tokens": cache_creation_val,
        "cache_read_input_tokens": cache_read_val,
        "cost_usd": cost_val,
        "cost_available": cost_available,
    }


def _parse_spec_ts(raw) -> "datetime | None":
    """解析 STATE 条目的 updated 时间戳；缺失/非法返回 None。naive 视为本地时间。"""
    if not raw:
        return None
    # SPEC-B 批④：解析收拢 parse_ts（唯一入口；naive 视作本地——与原
    # astimezone() 收尾同语义，失败返回 None 同路）。
    return parse_ts(str(raw))


def _updated_spec_counts(entries: dict, today_start: datetime, week_start: datetime) -> tuple:
    """统计 updated 落在今日（本地自然日）/ 近7天（滚动窗口）的 spec 数。"""
    today = week = 0
    for entry in entries.values():
        ts = _parse_spec_ts(entry.get("updated"))
        if ts is None:
            continue
        if ts >= week_start:
            week += 1
        if ts >= today_start:
            today += 1
    return today, week


def _token_recent_entries(entries: dict, project_name: str) -> list:
    """收集各 spec 的累计 token 消耗（_tokens_in/_tokens_out 为 STATE 持久累计值）。

    跳过无消耗数值（tokens==0）的 spec——消费方展示「最近 20 个有数值的 spec」。
    """
    out = []
    for name, entry in entries.items():
        tokens = _int_or_zero(entry.get("_tokens_in")) + _int_or_zero(entry.get("_tokens_out"))
        if tokens <= 0:
            continue
        out.append(
            {
                "project": project_name,
                "spec": name,
                "tokens": tokens,
                "updated": entry.get("updated") or "",
                "_ts": _parse_spec_ts(entry.get("updated")),
            }
        )
    return out


def _degraded_project(p: dict, error: str) -> dict:
    """聚合阶段失败项目的降级摘要（复用既有 error 键 schema）。

    `exists` 语义保持为 True：路径本身可解析（发现层 is_dir 已通过）即
    exists=True，失败原因只体现在 `error` 字段——避免 UI 把「不可读」误
    渲染成「项目不存在」（设计 D4）。
    """
    return {
        "name": p.get("name") or (Path(p["path"]).name or p["path"]),
        "path": p["path"],
        "discovered": p.get("discovered", False),
        "exists": True,
        "daemon": "stopped",
        "hosting": "stopped",
        "error": error,
    }


def overview(registry_projects: list) -> dict:
    """跨项目概览（/api/overview）。registry_projects 为 registry.discover() 结果。

    逐项目异常隔离：单个项目的摘要计算或状态解析抛出任何异常时，只影响该
    项目——该项目摘要携带 `error` 字段、不向 `totals` 累加任何计数，其余
    项目摘要与 `totals` 照常返回，函数不得抛出（dashboard-server 容错契约）。
    """
    now = now_local()  # SPEC-B 批④收拢（与原 now().astimezone() 等价）
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    projects = []
    totals = {
        "spec_count": 0,
        "task_done": 0,
        "task_total": 0,
        "problems": 0,
        "active_runs": 0,
        "spec_updated_today": 0,
        "spec_updated_week": 0,
        "active_runs_by_type": {},
    }
    status_counts = {}
    token_entries = []
    for p in registry_projects:
        if not p.get("exists"):
            projects.append(
                {
                    "name": p["name"],
                    "path": p["path"],
                    "discovered": p.get("discovered", False),
                    "exists": False,
                    "daemon": "stopped",
                    "hosting": "stopped",
                    "error": "项目路径不存在",
                }
            )
            continue
        try:
            # D8：parse_state / project_summary 经门面解析（tests monkeypatch 门面同名）
            import core.dashboard.data as _facade

            # 单次解析 STATE.md：同份快照供 project_summary（免其内部重复 IO）
            # 与下方 spec_updated/token 统计消费
            entries = _facade.parse_state(p["path"])
            s = _facade.project_summary(p["name"], p["path"], entries)
            s["discovered"] = p.get("discovered", False)
            s["exists"] = True
            projects.append(s)
            totals["spec_count"] += s["spec_count"]
            totals["task_done"] += s["task_done"]
            totals["task_total"] += s["task_total"]
            totals["problems"] += s["problems"]
            totals["active_runs"] += s["active_runs"]
            for at, n in (s.get("active_runs_by_type") or {}).items():
                totals["active_runs_by_type"][at] = totals["active_runs_by_type"].get(at, 0) + n
            t_today, t_week = _updated_spec_counts(entries, today_start, week_start)
            totals["spec_updated_today"] += t_today
            totals["spec_updated_week"] += t_week
            token_entries.extend(_token_recent_entries(entries, p["name"]))
            for st, n in s["status_counts"].items():
                status_counts[st] = status_counts.get(st, 0) + n
        except Exception as exc:  # noqa: BLE001 —— 单项目失败降级，不得使整页失败
            # 不外泄裸异常文本（与 run_routes 取消端点异常脱敏口径一致）：str(exc)
            # 可能携带服务器内部路径/errno 细节，随 /api/overview 下发浏览器；
            # 细节经服务端日志留痕，客户端收固定文案。
            logger.warning(
                "项目摘要计算失败（project=%s path=%s）: %s: %s",
                p.get("name"),
                p["path"],
                type(exc).__name__,
                exc,
            )
            projects.append(_degraded_project(p, "摘要计算失败，详见服务端日志"))
    totals["status_counts"] = status_counts
    token_entries.sort(key=lambda e: (e["_ts"].timestamp() if e["_ts"] else 0.0), reverse=True)
    for e in token_entries:
        e.pop("_ts", None)
    return {"projects": projects, "totals": totals, "token_usage": {"recent": token_entries[:20]}}
