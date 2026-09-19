"""
maintenance_runs.py — 维护型 run（refactor-agent-runner-module D3）。

从 runner.py 拆出的 Administrator / 每日自省 / 框架自进化三类运维 run 及其配套
（_clear/_delete/_read_admin_disposition、_clear/_delete/_read_self_review_out、
_accumulate_self_review_tokens、_delete_evolution_out、_accumulate_evolution_tokens、
_get_admin_model）。纯结构搬移，零行为变化。

本模块 MUST NOT `import runner`（D2b 规则 1）：门面依赖（_build_prompt /
_run_claude / _get_config / _get_agent_model_assignment / _ensure_agent_config_dir /
_write_provider_marker / _extract_usage_info / logger / project_root）一律以显式
`runner`（AgentRunner 实例）参数注入；兄弟函数间调用一律 `runner.<方法名>`
（D2b 规则 2，实例属性打桩不被绕过）。

DEFAULT_GATEWAY_MODEL 随 `_get_admin_model` 同迁本模块（D2b 规则 3），
`admin_disposition_path` / ADMIN_DISPOSITION_* 随 `run_administrator` 同迁；
均由 runner.py re-export（D2b 规则 4）。
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from core.agent_runner.result_gate import (
    AdminDisposition,
    CodeReviewResult,
    EvolutionResult,
    SelfReviewResult,
)
from core.code_review import (
    resolve_snapshot,
    upsert_findings,
)

# 无 provider 分配的 agent（含 Administrator）走默认网关（cc-switch）时 --model 用的
# 官方模型名。provider 已分配的 agent，其 --model 直接取该 agent 分配的网关模型名
# （model 字段，如 deepseek-v4-flash）——见 fenixd-sdk-model-routing：--model 即实际
# 发给网关的模型名，ANTHROPIC_MODEL 被 --model 覆盖不生效。本常量只作 fallback。
# 随消费者（_get_admin_model）同迁本模块，runner.py re-export。
DEFAULT_GATEWAY_MODEL = "claude-sonnet-5"

# ── Administrator 处置状态实例文件（fix-admin-run-blocks-mainloop D3）─────
# 处置状态文件按 run 实例分离：每个 admin run 使用独立文件
# .fenix/admin_disposition-<run_id>.json，并行实例互不覆盖。
# 旧全局路径 .fenix/admin_disposition.json 不再读写（残留文件由拾取侧清扫）。
ADMIN_DISPOSITION_PREFIX = "admin_disposition-"
ADMIN_DISPOSITION_GLOB = "admin_disposition-*.json"

# ── 失败取证参数（orphaned-state-probe-calibration 1.5） ─────────────
# run_administrator 非零退出失败证据的取值上限：原始 stderr 取末 N 行、
# 整体截断 4KB；run 产物取末 3 条带 timestamp 事件。
_ADMIN_FAILURE_STDERR_TAIL_LINES = 10
_ADMIN_FAILURE_STDERR_MAX_CHARS = 4 * 1024
_ADMIN_FAILURE_TS_EVENTS = 3


def _admin_failure_evidence(runner, run_id: str, exc: Exception) -> dict:
    """Administrator 处置 run 非零退出的可定位失败证据（orphaned-state-probe-calibration 1.5）。

    四项，全部来自异常本身（`_run_claude` 抛出的 RuntimeError 携带原始信号，
    runner.py:2983-2985）与 run 产物：
    - ``stderr_tail``：``getattr(exc, "stderr_lines", [])`` 末 N 行原始 stderr，
      拼接后截断 4KB（不止 error-attribution-denoise 过滤后的 5 行——原始
      现场逐条保留，unrecognized_model 类死因在此可定位）；
    - ``exit_code``：``getattr(exc, "exit_code", None)``；
    - ``provider_model``：run 产物内 ``provider_marker`` 事件的
      provider/model（Administrator 实际驱动的模型@网关，定位「模型不被网关
      接受」类失败的关键证据）；
    - ``recent_event_timestamps``：run 产物末 3 条**带 timestamp** 事件的
      时间戳——MUST 跳过无 timestamp 的 error/stderr/result/provider_marker/
      system 事件（这些终态/旁路事件不落时间戳，否则恒为空）。

    原始 stderr 只进独立证据字段（返回 dict），**不得**回填 ``error`` 归因
    文本——error-attribution-denoise D5 的全局降噪语义保持不变。任何读取
    异常降级为空 dict（只影响可定位性，不阻断处置主流程）。
    """
    evidence: dict = {
        "exit_code": getattr(exc, "exit_code", None),
        "stderr_tail": "",
        "provider_model": None,
        "recent_event_timestamps": [],
    }
    stderr_lines = getattr(exc, "stderr_lines", None)
    if isinstance(stderr_lines, list) and stderr_lines:
        tail = "\n".join(str(l) for l in stderr_lines[-_ADMIN_FAILURE_STDERR_TAIL_LINES:])
        evidence["stderr_tail"] = tail[:_ADMIN_FAILURE_STDERR_MAX_CHARS]
    run_file = runner.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"
    if run_file.is_file():
        try:
            rows = run_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            rows = []
        provider_marker = None
        timestamped: list = []
        for line in rows:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "provider_marker":
                provider_marker = entry
            ts = entry.get("timestamp")
            if isinstance(ts, str) and ts:
                timestamped.append(ts)
        if provider_marker is not None:
            evidence["provider_model"] = {
                "provider": provider_marker.get("provider"),
                "model": provider_marker.get("model"),
                "agent_type": provider_marker.get("agent_type"),
            }
        evidence["recent_event_timestamps"] = timestamped[-_ADMIN_FAILURE_TS_EVENTS:]
    return evidence


def admin_disposition_path(project_root: Path, run_id: str) -> Path:
    """某次 admin run 的处置状态实例文件路径。"""
    return Path(project_root) / ".fenix" / f"{ADMIN_DISPOSITION_PREFIX}{run_id}.json"


def run_administrator(runner, signal: dict) -> AdminDisposition:
    """唤起 Administrator Agent 处置困境信号（administrator-agent spec）。

    与 implementer/verifier 不同：Administrator 是运维角色，直接在 main 树
    （project_root）操作框架，不创建 worktree（design D4）。产物写入
    .fenix/runs/admin-<spec>-<ts>.jsonl；处置结果从管理员按 prompt 写入的
    实例文件 .fenix/admin_disposition-<run_id>.json 读取，由 daemon 落盘到
    admin_alerts.json。

    fix-admin-run-blocks-mainloop D3：处置状态文件按 run 实例分离——并行
    多实例（worker 池）各自 clear/write/read 自己的文件，互不覆盖。

    Args:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1）。
        signal: admin_monitor 检测到的困境信号 dict
            （signal_type/spec/severity/description/evidence/recommended_action）。
    """
    spec = signal.get("spec") or "global"
    run_id = f"admin-{spec}-{int(time.time())}"
    # 实例路径注入提示词（prompt_builder 把写入指令指向该文件）
    disp_path = admin_disposition_path(runner.project_root, run_id)
    prompt_detail = dict(signal)
    prompt_detail["disposition_path"] = str(disp_path)
    prompt = runner._build_prompt(spec, "administrator", detail=prompt_detail)

    # improve-config-ui-tabs：Administrator 运行时解析链（design D4）
    #   1. agents.models.administrator assignment → 用分配 model 并注入 provider env（直连）
    #   2. 无 assignment → 沿用旧逻辑 _get_admin_model()（admin.agent_model → 默认网关）
    assignment = runner._get_agent_model_assignment("administrator")
    env_overrides: Dict[str, str] = {}
    if assignment:
        # 取链首选（Administrator 不接入 attempt 级 failover，仅用首选直连）
        provider, model_override = assignment[0]
        env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
        env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
        env_overrides["ANTHROPIC_MODEL"] = model_override
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"]))
        for k, v in (provider.get("env") or {}).items():
            env_overrides[k] = v
        # 观测：run jsonl 写 provider_marker，与 dispatch attempt 路径同口径，
        # 时间轴才能展示 Administrator 实际驱动的 model@provider；
        # Administrator 不接 failover，链内下标恒 0/1
        runner._write_provider_marker(
            run_id,
            spec,
            "administrator",
            provider["name"],
            model_override,
            0,
            1,
        )
    else:
        model_override = runner._get_admin_model()

    # fix-admin-self-heal：唤起前先落 pending disposition，保证即使 admin 被
    # kill（如 daemon 重启/崩溃）也有记录可回溯；monitor 会检测无最终结果的
    # pending 并升级人工，避免「admin 死了但没有任何告警」。
    try:
        from core.admin_store import AdminStore, DISPOSITION

        AdminStore(runner.project_root, getattr(runner, "logger", None)).append(
            {
                "kind": DISPOSITION,
                "status": "pending",
                "signal_type": signal.get("signal_type"),
                "spec": spec,
                "admin_run_id": run_id,
                "description": (
                    f"Administrator 处置中（run {run_id}），尚未完成；"
                    f"若长时间无最终结果，AdminMonitor 会自动升级人工"
                ),
                "result": "pending",
                "recommended_action": signal.get("recommended_action"),
            }
        )
    except Exception:
        pass

    runner._clear_admin_disposition(disp_path)
    failure_evidence: dict = {}
    try:
        # _run_claude 返回 4 元组（add-cost-observability D1 加 usage_info）；
        # admin 不消费 usage，此调用点曾漏改按 3 元组解包——admin run 一启动
        # 即崩 too many values to unpack（2026-09-05 回检发现）
        output, turns, _session_id, _usage = runner._run_claude(
            prompt,
            runner.project_root,
            run_id,
            model_override,
            env_overrides,
            max_turns=runner._get_config("agents.max_turns", 300),
            spec_name=spec,
            agent_type="administrator",
        )
        success = True
        error = ""
    except Exception as e:
        output = ""
        success = False
        error = str(e)
        # evo-sigterm-source-tracking-cooldown：admin 处置 run 同走信号死法来源
        # 判定（闭集）——与 _execute_agent_inner 同款：daemon 关停（shutting_down
        # / 产物 interrupted）→ [shutdown-interrupted]；框架自身终止（supervision
        # 超时/轮次上限强杀）由 _record_signal_kill_or_label 内部排除；其余
        # 143/负信号 → [signal-kill: …] 标签 + spec 维度信号冷却计数（admin 处置
        # run 路由覆盖，不再无限瞬态重试）。
        run_file = runner.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"
        if getattr(runner, "shutting_down", False) or runner._run_was_interrupted(
                run_file):
            error = f"[shutdown-interrupted] {error}"
        else:
            error = runner._record_signal_kill_or_label(
                spec, error, getattr(e, "exit_code", None))
        # orphaned-state-probe-calibration 1.5：失败证据四件套（原始 stderr
        # 摘录 / 退出码 / provider·model / 带时间戳事件时间线）——只进独立
        # 证据字段（AdminDisposition.failure_evidence 与 logger context），
        # 不回填 error 归因文本（error-attribution-denoise D5 语义不变）。
        failure_evidence = _admin_failure_evidence(runner, run_id, e)
        # fix-admin-disposition-empty-shell：失败不再静默——WARNING 携带 run_id
        # 与异常文本，保证 `grep "Administrator run"` 可一次检索全部失败。
        runner.logger.warning(
            "agent_runner",
            f"Administrator run {run_id} failed: {error}",
            {"run_id": run_id, "error": error, "failure_evidence": failure_evidence},
        )

    disp = runner._read_admin_disposition(disp_path)
    # 读取即清理自身实例文件：内容已捕获进 AdminDisposition 返回给调用方落
    # final 记录，文件不再有读者；不清理会随并行实例累积成垃圾。
    runner._delete_admin_disposition(disp_path)
    return AdminDisposition(
        run_id=run_id,
        spec=disp.get("spec") or signal.get("spec"),
        success=success,
        problem=disp.get("problem") or signal.get("description", ""),
        actions_taken=disp.get("actions_taken") or "",
        result=disp.get("result") or ("resolved" if success else "failed"),
        escalate=bool(disp.get("escalate", False)),
        recommended_action=disp.get("recommended_action") or "",
        summary=disp.get("summary") or "",
        error=error,
        output=output,
        family_waiver=bool(disp.get("family_waiver", False)),
        failure_evidence=failure_evidence,
    )


def _clear_admin_disposition(disp_path: Path):
    """清空本次 run 的处置状态文件（若残留），避免读到陈旧数据。

    fix-admin-run-blocks-mainloop D3：路径按 run 实例传入，不再使用全局
    固定文件名——并行实例只清理自己的文件。
    """
    try:
        if disp_path.exists():
            disp_path.unlink()
    except OSError:
        pass


def _delete_admin_disposition(disp_path: Path):
    """run 结束后删除自己的处置状态实例文件（内容已在内存中/已落 final）。"""
    try:
        disp_path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_admin_disposition(disp_path: Path) -> dict:
    """读取管理员按 prompt 写入的处置记录（实例文件，路径按 run 注入）。

    文件缺失/损坏返回空 dict（调用方用信号详情兜底）。
    """
    try:
        data = json.loads(disp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    at = data.get("actions_taken")
    if isinstance(at, list):
        # 列表型动作以换行符连接，每条动作独立一行（design D5）
        data["actions_taken"] = "\n".join(str(x) for x in at if x)
    elif at is None:
        data["actions_taken"] = ""
    elif not isinstance(at, str):
        data["actions_taken"] = str(at)
    sm = data.get("summary")
    if isinstance(sm, list):
        # 列表型叙述以换行符连接，每段独立一行
        data["summary"] = "\n".join(str(x) for x in sm if x)
    elif sm is None:
        data["summary"] = ""
    elif not isinstance(sm, str):
        data["summary"] = str(sm)
    return data


# ── 每日自省 run（add-daily-self-review spec，design D2） ──────────


def run_self_review(
    runner,
    date_str: str,
    daily_summary: str,
    todo_md: str | None = None,
    todo_entries: str | None = None,
) -> SelfReviewResult:
    """唤起每日自省 run（Administrator 通道，design D2 复用语义）。

    与 implementer/verifier 不同：自省是运维角色，直接在 main 树
    （project_root）操作，不创建 worktree。特性：
    - run_id 前缀 ``review-<date>``：独立前缀，不占 spec 维度预算、
      不计入每日 agent run 计数（不走 _execute_agent）；
    - token 归账到 cost-observability 独立类目
      （.fenix/cost/self_review_tokens.json，design D2 二选一），不写
      STATE（自省链路禁止注册 STATE 条目）；
    - 超时走 agents.run_timeout_seconds 全局默认（_run_claude 内生效，
      不设 override）。
    - 模型解析链：agents.models.self-review 分配优先；未配置回退
      agents.models.administrator（向后兼容，自省源自运维通道）；
      再回退 admin.agent_model → 默认网关。

    Agent 按 prompt 把回顾写入实例文件
    ``.fenix/self_review_out-<run_id>.json``（JSON：
    date/waste/mistakes/improvements/resolved/summary），run 结束读取
    并清理。失败（异常/超时/rc!=0）返回 success=False（调度器记告警、
    24h 内不重试）。

    Args:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1）。
        date_str: 自省归属执行日 YYYY-MM-DD（即 run_id 内嵌日期）。
        daily_summary: 框架聚合的近 24 小时数据摘要（五源），注入 prompt。
        todo_md: read_todo=true 时的既有 todo.md 全文；None 不注入。
        todo_entries: read_todo=true 时 ID 标注的近 3 日条目清单
            （闭环判定对象）；None 注入占位提示。
    """
    run_id = f"review-{date_str}"
    out_path = runner.project_root / ".fenix" / f"self_review_out-{run_id}.json"
    prompt = runner._build_prompt(
        date_str,
        "self-review",
        detail={
            "review_date": date_str,
            "daily_summary": daily_summary or "",
            "todo_md": todo_md or "",
            "todo_entries": todo_entries or "",
            "out_path": str(out_path),
        },
    )

    # 模型解析链：agents.models.self-review > 回退 agents.models.administrator
    # （向后兼容：自省未单独配置时继承运维通道分配）> admin.agent_model → 默认网关
    env_overrides: Dict[str, str] = {}
    assignment = runner._get_agent_model_assignment(
        "self-review"
    ) or runner._get_agent_model_assignment("administrator")
    if assignment:
        provider, model_override = assignment[0]
        env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
        env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
        env_overrides["ANTHROPIC_MODEL"] = model_override
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"]))
        for k, v in (provider.get("env") or {}).items():
            env_overrides[k] = v
    else:
        model_override = runner._get_admin_model()

    runner._clear_self_review_out(out_path)
    try:
        output, turns, _session_id, usage_info = runner._run_claude(
            prompt,
            runner.project_root,
            run_id,
            model_override,
            env_overrides,
            max_turns=runner._get_config("agents.max_turns", 300),
            spec_name="self-review",
        )
        success = True
        error = ""
    except Exception as e:
        output = ""
        success = False
        error = str(e)
        usage_info = runner._extract_usage_info(None)

    # token 归账到独立类目（不写 STATE，硬约束）
    runner._accumulate_self_review_tokens(date_str, usage_info)

    data = runner._read_self_review_out(out_path)
    runner._delete_self_review_out(out_path)
    # resolved 闭环判定清单归一化：非 dict / 缺 id / 空 id / 非 str id 过滤
    resolved = []
    for item in data.get("resolved") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            resolved.append(
                {
                    "id": item["id"],
                    "reason": str(item.get("reason") or ""),
                }
            )
    return SelfReviewResult(
        run_id=run_id,
        date=date_str,
        success=success,
        waste=data.get("waste") or [],
        mistakes=data.get("mistakes") or [],
        improvements=data.get("improvements") or [],
        summary=data.get("summary") or "",
        resolved=resolved,
        error=error,
        output=output,
    )


def _clear_self_review_out(out_path: Path):
    """清空本次自省 run 的输出文件（若残留），避免读到陈旧数据。"""
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass


def _delete_self_review_out(out_path: Path):
    """run 结束后删除自己的 self_review 输出实例文件。"""
    try:
        out_path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_self_review_out(out_path: Path) -> dict:
    """读取自省 run 的回顾 JSON；缺失/损坏返回空 dict（调用方兜底）。"""
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    for field in ("waste", "mistakes", "improvements"):
        val = data.get(field)
        if not isinstance(val, list):
            data[field] = []
        else:
            # 结构化条目（dict，{impact, evidence, analysis?, suggestion}）
            # 保持原形直达渲染层，仅非 dict/str 标量兜底 str——无差别
            # str() 会把合规 dict 打成 dict-repr 字符串，渲染层四行格式
            # 失效退化为机器形态（09-08 事故）。
            data[field] = [x if isinstance(x, (dict, str)) else str(x) for x in val if x]
    sm = data.get("summary")
    if sm is None:
        data["summary"] = ""
    elif not isinstance(sm, str):
        data["summary"] = str(sm)
    return data


def _accumulate_self_review_tokens(runner, date_str: str, usage_info: dict) -> None:
    """add-daily-self-review：自省 token 归账到 cost-observability 独立类目。

    design D2 二选一（独立 self-review 类目）：追加到
    ``.fenix/cost/self_review_tokens.json`` 的 runs 数组（与
    verify-progress tokens.json 同结构），供成本对账口径一致；不写
    STATE（禁止注册 STATE 条目硬约束）。写失败静默降级（观测增强，
    不阻断自省主流程）。
    """
    if not isinstance(usage_info, dict):
        usage_info = {}
    cost_dir = runner.project_root / ".fenix" / "cost"
    tokens_json = cost_dir / "self_review_tokens.json"
    try:
        tokens_json.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if tokens_json.is_file():
            try:
                loaded = json.loads(tokens_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                data = loaded
        runs = data.get("runs")
        if not isinstance(runs, list):
            runs = []
        runs.append(
            {
                "agent_type": "self-review",
                "date": date_str,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_tokens": int(usage_info.get("input_tokens", 0) or 0)
                + int(usage_info.get("cache_creation_input_tokens", 0) or 0)
                + int(usage_info.get("cache_read_input_tokens", 0) or 0),
                "output_tokens": int(usage_info.get("output_tokens", 0) or 0),
                "cost_usd": usage_info.get("cost_usd"),
            }
        )
        data["runs"] = runs
        tokens_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass


# ── 框架自进化 run（add-framework-self-evolution spec，design D2） ──


def run_evolution(
    runner, ready_projects: list, pending_entries: list | None = None
) -> EvolutionResult:
    """唤起框架自进化分析 run（Administrator 通道语义，design D2 复用）。

    与 implementer/verifier 不同：自进化是运维角色，直接在 main 树
    （project_root）操作，**不创建 worktree**（与 run_self_review 同形态）。
    特性：
    - run_id 前缀 ``evo-<epoch>``：独立前缀，不占 spec 维度预算、
      不计入每日 agent run 计数（不走 _execute_agent）；
    - token 归账沿用 _accumulate_self_review_tokens 的既有类目（cost
      独立类目，不写 STATE）；
    - 超时走 agents.run_timeout_seconds 全局默认（_run_claude 内生效）；
    - 模型解析链：agents.models.self-review 分配优先；未配置回退
      agents.models.administrator；再回退 _get_admin_model → 默认网关
      （MUST NOT 引入新的 agents.models.* 配置键）。
    - max_turns / 超时 / 预算 / 告警 / provider 熔断全部走既有
      _run_claude（spec「分析 run 的角色、模型链与执行形态」）。

    产物路径 ``.fenix/evolution/out-<run_id>.json``（契约 JSON：
    items[] 含 verdict/analysis_md/spec），run 结束读取并清理（4.4）。
    产物缺失或解析失败返回 success=False 并带原因，MUST NOT 抛异常
    穿透到调用方。落地（ingest_item）由本方法执行，自动接受是
    5.3 检查点的职责（本方法不触碰配置开关）。

    Args:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1）。
        ready_projects: 就绪项目 [{name, path, todo_md}]（scan_ready_projects
            的返回，同一 run 拿到多份 todo.md）。
        pending_entries: 待分析条目（含 id），None 由调用方传入。
    """
    run_id = f"evo-{int(time.time())}"
    out_path = runner.project_root / ".fenix" / "evolution" / f"out-{run_id}.json"
    prompt = runner._build_prompt(
        run_id,
        "evolution",
        detail={
            "ready_projects": ready_projects or [],
            "pending_entries": pending_entries or [],
            "out_path": str(out_path),
        },
    )

    # 模型解析链：agents.models.self-review > 回退 agents.models.administrator
    # > _get_admin_model（与自省 agent 完全同源，spec「模型链与自省同源」）。
    env_overrides: Dict[str, str] = {}
    assignment = runner._get_agent_model_assignment(
        "self-review"
    ) or runner._get_agent_model_assignment("administrator")
    if assignment:
        provider, model_override = assignment[0]
        env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
        env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
        env_overrides["ANTHROPIC_MODEL"] = model_override
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"]))
        for k, v in (provider.get("env") or {}).items():
            env_overrides[k] = v
    else:
        model_override = runner._get_admin_model()

    try:
        output, turns, _session_id, usage_info = runner._run_claude(
            prompt,
            runner.project_root,
            run_id,
            model_override,
            env_overrides,
            max_turns=runner._get_config("agents.max_turns", 300),
            spec_name="evolution",
        )
        run_ok = True
        error = ""
    except Exception as e:
        output = ""
        run_ok = False
        error = str(e)
        usage_info = runner._extract_usage_info(None)

    # token 归账到独立类目（不写 STATE，与自省同一约束）
    runner._accumulate_evolution_tokens(run_id, usage_info)

    # 读取契约产物并落地（4.4：产物缺失/解析失败 → success=False 带原因）
    degraded = None
    items_ingested = 0
    drafts = 0
    if run_ok:
        try:
            from core.evolution import ContractError, read_contract, ingest_item

            try:
                contract = read_contract(out_path)
                runner._delete_evolution_out(out_path)
            except ContractError as e:
                run_ok = False
                error = str(e)
                contract = None
        except Exception as e:
            # 落地异常不应穿透（检查点统一捕获）；整轮视为失败带原因
            run_ok = False
            error = f"分析落地异常: {e}"
            contract = None
        if run_ok and contract:
            degraded = contract.get("degraded")
            for item in contract.get("items") or []:
                try:
                    status = ingest_item(item, runner.project_root)
                except Exception as e:
                    # 单条落地失败不使整轮失败（幂等去重保证下轮重试）
                    _log = getattr(runner, "logger", None)
                    if _log is not None:
                        _log.warning(
                            "self-evolution", f"条目落地异常（跳过）: " f"{item.get('title')}: {e}"
                        )
                    continue
                items_ingested += 1
                if status == "pending":
                    drafts += 1

    return EvolutionResult(
        run_id=run_id,
        success=run_ok,
        items_ingested=items_ingested,
        drafts=drafts,
        degraded=degraded,
        error=error,
        output=output,
    )


def _delete_evolution_out(out_path: Path):
    """run 结束后删除自己的 evolution 输出实例文件（与 self_review 同处理）。"""
    try:
        out_path.unlink(missing_ok=True)
    except OSError:
        pass


def _accumulate_evolution_tokens(runner, run_id: str, usage_info: dict) -> None:
    """自进化 token 归账（沿用 self_review 的独立类目文件与结构）。

    design D2 二选一：追加到 ``.fenix/cost/self_review_tokens.json`` 的
    runs 数组（与 verify-progress tokens.json 同结构），agent_type 标注
    ``evolution`` 以便成本对账区分。写失败静默降级（观测增强，不阻断）。
    """
    if not isinstance(usage_info, dict):
        usage_info = {}
    cost_dir = runner.project_root / ".fenix" / "cost"
    tokens_json = cost_dir / "self_review_tokens.json"
    try:
        tokens_json.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if tokens_json.is_file():
            try:
                loaded = json.loads(tokens_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                data = loaded
        runs = data.get("runs")
        if not isinstance(runs, list):
            runs = []
        runs.append(
            {
                "agent_type": "evolution",
                "date": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_tokens": int(usage_info.get("input_tokens", 0) or 0)
                + int(usage_info.get("cache_creation_input_tokens", 0) or 0)
                + int(usage_info.get("cache_read_input_tokens", 0) or 0),
                "output_tokens": int(usage_info.get("output_tokens", 0) or 0),
                "cost_usd": usage_info.get("cost_usd"),
            }
        )
        data["runs"] = runs
        tokens_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass


def _get_admin_model(runner) -> str:
    """Administrator 模型名：admin.agent_model > 默认网关 fallback 常量。"""
    admin_model = runner._get_config("admin.agent_model", None)
    if admin_model:
        return admin_model
    return DEFAULT_GATEWAY_MODEL


# ── 周期性代码审查 run（add-code-review-agent-and-quality-tab）──────


def run_code_review(
    runner,
    manifest: list,
    review_kind: str,
    window_start: datetime | None = None,
    scope: str = "window",
) -> CodeReviewResult:
    """唤起代码审查 run（code-review agent，design D1/D4）。

    与 self_review/evolution 同形态：运维角色，直接在 main 树（project_root）
    操作，**不创建 worktree**。特性：
    - run_id 前缀 ``code-review-<epoch>``：独立前缀，不占 spec 维度预算、
      不计入每日 agent run 计数（不走 _execute_agent）；
    - 派发前框架侧把 manifest（待审文件清单，进度 total 权威来源）落盘为
      ``.fenix/code-review/manifest-<run_id>.json``，并注入 prompt；
    - agent 逐文件审查、每审完一个文件向 ``.fenix/code-review/out-<run_id>
      .jsonl`` 追加一行（增量落盘，进度 done 来源）；
    - run 结束读增量产物并 ``upsert_findings`` 入台账；``manual_full``
      收尾再 ``resolve_snapshot`` 全仓核销（D5 只增不核销的例外）；
    - token 归账到独立类目 ``.fenix/cost/code_review_tokens.json``
      （MUST NOT 走 _accumulate_token_usage——审查 run 无 spec 维度）；
    - 模型解析链：agents.models.code-review 分配优先 → 回退
      agents.models.self-review → 回退 agents.models.administrator →
      再回退 _get_admin_model → 默认网关。
    - 超时走 agents.run_timeout_seconds 全局默认（_run_claude 内生效）。

    Args:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1）。
        manifest: 待审文件清单（相对路径列表，框架侧先行算出）。
        review_kind: scheduled / manual_full / manual_window。
        window_start: 审查窗口起点（scheduled/manual_window 注入；
            manual_full 为 None=全仓）。
        scope: full / window（写进 manifest 供审计）。
    """
    run_id = _unique_code_review_run_id(runner)
    mpath = runner.project_root / ".fenix" / "code-review" / f"manifest-{run_id}.json"
    opath = runner.project_root / ".fenix" / "code-review" / f"out-{run_id}.jsonl"
    try:
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "scope": scope,
                    "review_kind": review_kind,
                    "window_start": window_start.isoformat() if window_start else None,
                    "files": [str(f) for f in manifest],
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        return CodeReviewResult(run_id=run_id, success=False, error=f"manifest 落盘失败: {e}")

    review_window = (
        f"[{window_start.isoformat()}, now]" if window_start else "（全仓，manual_full）"
    )
    prompt = runner._build_prompt(
        run_id,
        "code-review",
        detail={
            "manifest": [str(f) for f in manifest],
            "review_window": review_window,
            "out_path": str(opath),
        },
    )

    # 模型解析链：agents.models.code-review > self-review > administrator >
    # _get_admin_model → 默认网关（design D1 模型链回退）
    env_overrides: Dict[str, str] = {}
    assignment = (
        runner._get_agent_model_assignment("code-review")
        or runner._get_agent_model_assignment("self-review")
        or runner._get_agent_model_assignment("administrator")
    )
    if assignment:
        provider, model_override = assignment[0]
        env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
        env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
        env_overrides["ANTHROPIC_MODEL"] = model_override
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"]))
        for k, v in (provider.get("env") or {}).items():
            env_overrides[k] = v
    else:
        model_override = runner._get_admin_model()

    try:
        output, turns, _session_id, usage_info = runner._run_claude(
            prompt,
            runner.project_root,
            run_id,
            model_override,
            env_overrides,
            max_turns=runner._get_config("agents.max_turns", 300),
            spec_name="code-review",
            agent_type="code-review",
        )
        run_ok = True
        error = ""
    except Exception as e:
        output = ""
        run_ok = False
        error = str(e)
        usage_info = runner._extract_usage_info(None)

    # token 归账到独立类目（不写 STATE，与自省同一约束）
    _accumulate_code_review_tokens(runner, run_id, usage_info)

    # 读取增量产物并落账（产物缺失/解析失败 → success=False 带原因）
    inserted = updated = resolved = 0
    if run_ok:
        try:
            findings = _read_code_review_out(opath)
        except OSError as e:
            run_ok = False
            error = f"读取审查产物失败: {e}"
            findings = []
        if run_ok and findings is not None:
            try:
                stats = upsert_findings(
                    runner.project_root,
                    findings,
                    review_id=run_id,
                    review_kind=review_kind,
                )
                inserted = stats.get("inserted", 0)
                updated = stats.get("updated", 0)
            except Exception as e:
                # 落账异常不应穿透；整轮视为失败带原因
                run_ok = False
                error = f"审查落账异常: {e}"
            if run_ok and review_kind == "manual_full":
                # 全仓快照核销：本轮未再观测到的 open 项置 resolved（D5）
                try:
                    observed = {f["fingerprint"] for f in findings if isinstance(f, dict) and f.get("fingerprint")}
                    resolved = resolve_snapshot(runner.project_root, observed)
                except Exception:  # noqa: BLE001 — 核销失败记 WARNING 不使整轮失败
                    _log = getattr(runner, "logger", None)
                    if _log is not None:
                        _log.warning("code-review", f"全仓快照核销失败（run {run_id}）")

    return CodeReviewResult(
        run_id=run_id,
        success=run_ok,
        inserted=inserted,
        updated=updated,
        resolved=resolved,
        error=error,
        output=output,
    )


def _unique_code_review_run_id(runner) -> str:
    """生成不冲突的 ``code-review-<epoch>`` run_id（task 3.7）。

    秒级时间戳在「手动触发 + 同秒周期触发」下可能撞名（manifest/out 文件
    会被互相覆盖）。目标文件已存在时追加 ``-<n>`` 退避（n 从 1 起递增）。
    """
    base = f"code-review-{int(time.time())}"
    candidate = base
    n = 1
    cr_dir = runner.project_root / ".fenix" / "code-review"
    while True:
        if not (cr_dir / f"manifest-{candidate}.json").exists() and not (
            cr_dir / f"out-{candidate}.jsonl"
        ).exists():
            return candidate
        n += 1
        candidate = f"{base}-{n}"


def _read_code_review_out(opath: Path) -> list:
    """读取审查增量产物 ``out-<run_id>.jsonl``。

    每行为一个文件的审查结果 JSON（file/findings[]）。非 dict 行忽略；
    损坏行跳过；文件缺失返回空列表（run 失败路径已由 success=False 兜底）。
    """
    out: list = []
    if not opath.is_file():
        return out
    for lineno, line in enumerate(opath.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        file_ = str(rec.get("file") or "")
        findings = rec.get("findings")
        if not isinstance(findings, list):
            # 单文件无结果行：跳过（不计入台账，也不报错）
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            # 审查契约字段归一（file 取文件行 + finding 层可覆盖）
            base = dict(finding)
            base.setdefault("file", file_)
            base.setdefault("spec", "")
            base.setdefault("line", 1)
            if base.get("file"):
                out.append(base)
    return out


def _accumulate_code_review_tokens(runner, run_id: str, usage_info: dict) -> None:
    """code-review token 归账到 cost-observability 独立类目（task 3.6）。

    追加到 ``.fenix/cost/code_review_tokens.json`` 的 runs 数组（与
    self_review_tokens.json 同结构），供成本对账口径一致；不写 STATE
    （审查 run 无 spec 维度）。写失败静默降级（观测增强，不阻断）。
    """
    if not isinstance(usage_info, dict):
        usage_info = {}
    cost_dir = runner.project_root / ".fenix" / "cost"
    tokens_json = cost_dir / "code_review_tokens.json"
    try:
        tokens_json.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if tokens_json.is_file():
            try:
                loaded = json.loads(tokens_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                data = loaded
        runs = data.get("runs")
        if not isinstance(runs, list):
            runs = []
        runs.append(
            {
                "agent_type": "code-review",
                "date": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_tokens": int(usage_info.get("input_tokens", 0) or 0)
                + int(usage_info.get("cache_creation_input_tokens", 0) or 0)
                + int(usage_info.get("cache_read_input_tokens", 0) or 0),
                "output_tokens": int(usage_info.get("output_tokens", 0) or 0),
                "cost_usd": usage_info.get("cost_usd"),
            }
        )
        data["runs"] = runs
        tokens_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass
