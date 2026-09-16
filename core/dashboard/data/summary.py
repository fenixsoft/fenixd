"""core.dashboard.data.summary — 聚合视图/摘要（summary 组）。

refactor-dashboard-data-module D3 分组：本模块承载聚合视图职责域。
daemon/托管态检测、项目与 SPEC 摘要、摘要索引、概览。
"""

import copy
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# infra 轮次/失败计数常量子段（spec_summary/spec_detail 补推断口）
from core.state_machine import (
    INFRA_FAILURE_COUNT_FIELD,
    VERIFY_INFRA_ROUNDS_FIELD,
)

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


def project_summary(project_root, name: str, path: str) -> dict:
    """单个项目的聚合摘要（/api/projects、/api/overview 共用）。"""
    proot = Path(path)
    # D8：parse_state 经门面解析（tests patch 门面同名，与 overview 内 parse_state 一致）
    import core.dashboard.data as _facade

    specs = _facade.parse_state(proot)
    status_counts = {}
    for e in specs.values():
        st = e.get("status", "?") or "?"
        status_counts[st] = status_counts.get(st, 0) + 1

    grand_done = grand_total = 0
    problems = 0
    for sname in specs:
        entry = specs[sname]
        d, t = _facade.task_progress(proot, sname, entry.get("status", ""))
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

    # D8：daemon_health/hosting_state 经门面解析（tests patch 门面同名）
    import core.dashboard.data as _facade

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
        "updated": (
            (Path(path) / ".fenix" / "STATE.md").stat().st_mtime
            if (Path(path) / ".fenix" / "STATE.md").exists()
            else 0
        ),
        "description": description,
    }


def _spec_total_duration(project_root, spec_name: str, entry: dict, runs: list) -> int:
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


def _resolve_global_impl_run_budget(project_root) -> int:
    """读取全局 agents.impl_run_budget 有效值，fallback DEFAULT_IMPL_RUN_BUDGET。

    结果按项目级 config.yaml 签名键缓存（config 变化自动失效），与闸门口径一致：
    ConfigLoader.get 读合并配置 → 按有效上限夹紧 → fallback DEFAULT。
    """
    from core.pm_engine.budget import (
        clamp_impl_run_budget,
        DEFAULT_IMPL_RUN_BUDGET,
        resolve_impl_run_budget_max,
        IMPL_RUN_BUDGET_MAX_KEY,
        IMPL_RUN_BUDGET_MAX_DEFAULT,
    )
    from core.config import ConfigLoader
    import core.dashboard.data as _facade

    proot = Path(project_root)
    cfg_path = proot / ".fenix" / "config.yaml"
    sig = _facade._config_file_sig(cfg_path)
    cache_key = (str(proot.resolve()), sig)
    cached = _GLOBAL_BUDGET_CACHE.get(cache_key)
    if cached is not None:
        return cached
    cfg = ConfigLoader.resolve_config(proot)
    max_value = resolve_impl_run_budget_max(
        ConfigLoader.get(cfg, IMPL_RUN_BUDGET_MAX_KEY, IMPL_RUN_BUDGET_MAX_DEFAULT)
    )
    raw = ConfigLoader.get(cfg, "agents.impl_run_budget")
    budget = clamp_impl_run_budget(raw, max_value) or DEFAULT_IMPL_RUN_BUDGET
    if len(_GLOBAL_BUDGET_CACHE) > _GLOBAL_BUDGET_CACHE_MAX:
        _GLOBAL_BUDGET_CACHE.clear()
    _GLOBAL_BUDGET_CACHE[cache_key] = budget
    return budget


def _impl_budget_max(project_root) -> int:
    """读取有效预算上限 ``agents.impl_run_budget_max``（缺省 100）。

    供 spec_summary 夹紧 override 与 API 校验共用（与闸门 ImplBudget._impl_budget_max
    同源：同一 resolve_impl_run_budget_max 纯函数 + 同一配置键）。
    """
    from core.pm_engine.budget import (
        resolve_impl_run_budget_max,
        IMPL_RUN_BUDGET_MAX_KEY,
        IMPL_RUN_BUDGET_MAX_DEFAULT,
    )
    from core.config import ConfigLoader

    cfg = ConfigLoader.resolve_config(Path(project_root))
    raw = ConfigLoader.get(cfg, IMPL_RUN_BUDGET_MAX_KEY, IMPL_RUN_BUDGET_MAX_DEFAULT)
    return resolve_impl_run_budget_max(raw)


def spec_summary(project_root, spec_name: str, entry: dict) -> dict:
    """单个 SPEC 的摘要（/api/specs 列表项）。"""
    import core.dashboard.data as _facade

    done, total = _facade.task_progress(project_root, spec_name, entry.get("status", ""))
    vp = _facade.parse_verify_progress(project_root, spec_name)
    # 含归档：run 产物被清理后列表页耗时统计不缩水
    runs = _facade.get_runs(project_root, spec_name, include_archive=True)
    total_duration = _spec_total_duration(project_root, spec_name, entry, runs)
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
    budget_override_raw = entry.get(IMPL_RUN_BUDGET_OVERRIDE_FIELD) if entry else None
    budget_override = clamp_impl_run_budget(budget_override_raw, budget_max)
    try:
        budget_used = int(entry.get("_impl_run_budget_used", 0) or 0) if entry else 0
    except (TypeError, ValueError):
        budget_used = 0
    if budget_override is not None:
        budget_effective = budget_override
    else:
        budget_effective = _resolve_global_impl_run_budget(project_root)
    return {
        "name": spec_name,
        "status": entry.get("status"),
        "archived": _facade.is_spec_archived(project_root, spec_name),
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
        # 冻结态（结构化字段优先，回退文本前缀）：前端据此渲染解冻入口。
        # 自动冻结（内容完整性闸门 / 预算闸门 / env 阻塞）只认文本会漏判。
        "frozen": _facade.is_spec_frozen(entry),
        # add-task-progress-verify-phase：阶段判定单点在后端——仅 testing 切
        # verify（验证引擎运行中），其余一切状态按 impl；fast-track 经
        # _fast_track_advance_to_verified 瞬时连转 testing→verified 不停留，
        # 天然恒 impl，无需 mode 特判。前端只消费该字段，不重复判定。
        "progress_phase": "verify" if entry.get("status") == "testing" else "impl",
        "verify_current": vp.get("current", ""),
        "task_done": done,
        "task_total": total,
        # run 层实时进度（fix-implementer-task-progress D3）：tasks.md 快照失效
        # （subject 无编号 / agent 不勾 tasks.md）时仍能看到 run 推进。
        "run_progress": _facade.run_task_progress(project_root, spec_name),
        # 存活心跳（2026-09-15 原地补充）：run_progress 依赖 TaskCreate/TaskUpdate，
        # 而派发路由实测不含该工具族 → 实现期间恒 0/N。run_activity 以「产物是否
        # 仍在写」提供不依赖任务工具的存活线索，前端据此在进度单元显示「进行中」。
        "run_activity": _facade.run_activity(project_root, spec_name),
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
        "verify_infra_rounds": int(entry.get("_verify_infra_rounds", 0) or 0) if entry else 0,
        "infra_failure_count": int(entry.get("_infra_failure_count", 0) or 0) if entry else 0,
    }


# ── spec 摘要索引（dashboard-spec-summary-index D1） ─────────────


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


def _spec_dep_sigs(proot: Path, spec_name: str, entry: dict, runs_sigs: dict) -> dict:
    """单个 spec 摘要的依赖文件签名集合（对齐 spec_summary 实际读路径）。

    覆盖 tasks.md（implementing 时含实现 worktree 副本）/ specs/ 目录整体 /
    .spec.yaml / verification-report.md / verify-progress 相关文件 /
    该 spec 的 run 产物（由调用方预扫描 runs_sigs 传入）。宁多勿漏：把
    specs/ 目录整体入签名，依赖文件集合单向全覆盖。
    """
    sigs: dict = {}
    changes = proot / "spec" / "changes" / spec_name

    import core.dashboard.data as _facade

    def add(p: Path):
        sig = _stat_sig(p)
        if sig is not None:
            sigs[str(p)] = sig

    add(changes / "tasks.md")
    if entry and entry.get("status") == "implementing":
        wt = _facade.find_implementer_worktree(proot, spec_name)
        if wt is not None:
            add(wt / "spec" / "changes" / spec_name / "tasks.md")
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
    # add-spec-status-modal-budget D3：budget_effective 依赖全局 config
    # （agents.impl_run_budget 覆盖优先解析的兜底来源），项目级与用户级
    # config.yaml 变化须触发摘要失效（宁多勿漏原则）。
    add(proot / ".fenix" / "config.yaml")
    for p, sig in (runs_sigs.get(spec_name) or {}).items():
        sigs[p] = sig
    return sigs


class SummaryIndex:
    """每项目 spec 摘要内存索引（dashboard-spec-summary-index D1）。

    结构：{proot_key: {spec_name: {"summary": dict, "sigs": {path: (mtime_ns, size)}}}}

    - 惰性构建：首次 get() 触发；watcher 与 server 共享同一实例（单写者 watcher
      线程，读者 HTTP 线程，经 RLock 保护——读多写少场景足够）。
    - 失效策略：每 spec 先比对依赖文件签名，未变直返缓存；变化只重算该 spec。
    - STATE.md 签名变化 → 该项目全量重建（新增/删除 spec 只有 parse_state 全量
      才能发现，触发频率低）。
    - 有界性：摘要 dict 常驻内存（10000 spec ≈ 数十 MB，可接受）；签名只对存在
      路径记录，删除的 spec 目录从索引剔除。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._idx: dict = {}
        self._state_sigs: dict = {}
        self._state_snapshot: dict = {}

    def get(self, proot, specs: dict | None = None, state_sig=None) -> list:
        """返回该项目的全部 spec_summary 列表（顺序与 specs dict 一致）。

        Args:
            proot: 项目根路径
            specs: parse_state 快照 {spec_name: entry}；省略时复用索引内缓存快照
                （STATE.md 签名未变则直接复用，避免每请求全量解析 STATE.md）。
            state_sig: STATE.md 的 (mtime_ns, size) 签名；变化时触发全量重建
                并重新解析 STATE.md 快照。
        """
        key = str(Path(proot).resolve())
        # 跨组引用经门面延迟解析（D4/D8）
        import core.dashboard.data as _facade

        with self._lock:
            if state_sig is None:
                state_sig = _stat_sig(proot / ".fenix" / "STATE.md")

            # STATE.md 签名变化 → 全量重建索引 + 重新解析快照（新增/删除 spec
            # 只有 parse_state 全量才能发现；触发频率低，仅 STATE.md 变更时）。
            state_changed = state_sig is not None and self._state_sigs.get(key) != state_sig
            if specs is None:
                if not state_changed:
                    specs = self._state_snapshot.get(key)
                if specs is None:
                    specs = _facade.parse_state(proot)
                    self._state_snapshot[key] = specs

            idx = self._idx.get(key)
            if idx is None or state_changed:
                idx = {}

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
                import core.dashboard.data as _facade

                summary = _facade.spec_summary(proot, spec_name, entry)
                idx[spec_name] = {"summary": summary, "sigs": sigs}
                out.append(summary)

            # 清理已删除 spec 的签名条目
            for stale in [s for s in idx if s not in specs]:
                del idx[stale]

            self._idx[key] = idx
            if state_sig is not None:
                self._state_sigs[key] = state_sig
                if specs is not None:
                    self._state_snapshot[key] = specs
            return out


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
    # 跨组引用（timeline 组的 get_spec_timeline/_timeline_with_retry）经门面延迟解析（D4）
    import core.dashboard.data as _facade

    timeline = _facade._timeline_with_retry(
        _facade.get_spec_timeline(project_root, spec_name, entry.get("created") or ""),
        project_root,
        entry,
    )
    # improve-provider-billing-config（D2）：SPEC 级成本合计——计价表非空
    # （有任一声明 billing 的卡片）时进入计价分支；单 run 计价由匹配函数自行
    # 判定未开启卡片 → None（未开启卡片 run 不计入 priced_runs）。
    cost_summary = None
    billing_table = _facade._load_billing_config(project_root)
    if billing_table:
        cost_summary = _facade._cost_summary_from_timeline(timeline)
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
        "depends_on": entry.get("depends_on"),
        "tasks": _facade.parse_tasks(project_root, spec_name, spec_status),
        "tasks_note": _facade.tasks_note(project_root, spec_name, spec_status),
        "run_progress": _facade.run_task_progress(project_root, spec_name),
        "run_activity": _facade.run_activity(project_root, spec_name),
        "verify_progress": _facade.parse_verify_progress(project_root, spec_name),
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
        "total_duration": _spec_total_duration(project_root, spec_name, entry, runs),
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
            "verify_infra_rounds": int(entry.get(VERIFY_INFRA_ROUNDS_FIELD, 0) or 0),
            "infra_failure_count": int(entry.get(INFRA_FAILURE_COUNT_FIELD, 0) or 0),
            "verify_fail_rounds": int(entry.get("_verify_fail_rounds", 0) or 0),
        },
    }


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
    分项数据（历史条目），前端不显示缓存括号。
    """
    if not isinstance(entry, dict):
        entry = {}
    tokens_in = int(entry.get("_tokens_in", 0) or 0)
    tokens_out = int(entry.get("_tokens_out", 0) or 0)
    # 分项字段：缺失（历史 spec）保持 None，存在则规整为 int（STATE 读出为字符串）
    cache_read = entry.get("_cache_read_tokens")
    cache_creation = entry.get("_cache_creation_tokens")
    cache_read_val = int(cache_read) if cache_read is not None else None
    cache_creation_val = int(cache_creation) if cache_creation is not None else None
    cost = entry.get("_cost_usd")
    if cost is None:
        cost_val = None
        cost_available = False
    else:
        try:
            cost_val = float(cost)
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
    try:
        ts = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    return ts.astimezone() if ts.tzinfo is None else ts


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
        tokens = int(entry.get("_tokens_in", 0) or 0) + int(entry.get("_tokens_out", 0) or 0)
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
    now = datetime.now().astimezone()
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
            # D8：project_summary 经门面解析（tests monkeypatch 门面同名）
            import core.dashboard.data as _facade

            s = _facade.project_summary(p["path"], p["name"], p["path"])
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
            # D8：parse_state 经门面解析（tests patch 门面同名）
            import core.dashboard.data as _facade

            entries = _facade.parse_state(p["path"])
            t_today, t_week = _updated_spec_counts(entries, today_start, week_start)
            totals["spec_updated_today"] += t_today
            totals["spec_updated_week"] += t_week
            token_entries.extend(_token_recent_entries(entries, p["name"]))
            for st, n in s["status_counts"].items():
                status_counts[st] = status_counts.get(st, 0) + n
        except Exception as exc:  # noqa: BLE001 —— 单项目失败降级，不得使整页失败
            projects.append(_degraded_project(p, f"摘要计算失败: {exc}"))
    totals["status_counts"] = status_counts
    token_entries.sort(key=lambda e: (e["_ts"].timestamp() if e["_ts"] else 0.0), reverse=True)
    for e in token_entries:
        e.pop("_ts", None)
    return {"projects": projects, "totals": totals, "token_usage": {"recent": token_entries[:20]}}
