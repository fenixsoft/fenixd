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

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from core.agent_runner.result_gate import (
    AdminDisposition,
    CodeReviewResult,
    EvolutionResult,
    RegressionResult,
    SelfReviewResult,
)
from core.code_review import (
    resolve_snapshot,
    upsert_findings,
)
from core.agent_runner.result_gate import _check_repo_code_review_artifact
from core.agent_runner.run_files import append_run_line

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
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"], model_override))
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
    except Exception as e:
        # fix-admin-self-heal 守卫降级不可静默：若 AdminStore import/append
        # 持续失败（权限/schema/磁盘），pending 记录从不写入但 run 照常——
        # 整个 self-heal 告警路径静默失效（被 kill 的 admin 不留任何可升级
        # 的痕迹）。至少 WARNING 留痕（code-review item 8353a3138b0f）；
        # logger 判空与本文件其它调用点统一走 getattr。
        _log = getattr(runner, "logger", None)
        if _log is not None:
            _log.warning(
                "agent_runner",
                f"Administrator pending disposition write failed (run {run_id}): "
                f"{type(e).__name__}: {e}",
                {"run_id": run_id, "spec": spec, "error": str(e)},
            )

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
        # logger 判空（code-review item b1d40b9afa56）：本处位于 except 中，
        # logger 缺失/为 None 会抛 AttributeError 把真正失败归因整体吞掉；
        # 与本文件其它调用点（run_code_review/run_evolution）统一用 getattr 判空。
        _log = getattr(runner, "logger", None)
        if _log is not None:
            _log.warning(
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
        # add-human-adjudication-choices 4.2：处置记录结构化裁决字段透传
        # （缺省空串兼容无键的存量处置记录）
        choice_id=str(disp.get("choice_id") or ""),
        suggested_choice=str(disp.get("suggested_choice") or ""),
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
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"], model_override))
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


def _append_token_run(tokens_json: Path, entry: dict) -> None:
    """向 token 归账文件的 ``runs`` 数组追加一条记录（flock + 原子替换）。

    三个归账函数（self-review / evolution / code-review）共用同一段读-改-写
    逻辑，且各自无锁重写——两个运维 run 并发收尾（daemon 检查点在 worker 线程
    投递）时后写者会覆盖前者的 ``runs`` 追加，token 记录静默丢失
    （code-review item d1836827425e）。此处提取为公共助手：以
    ``.<name>.lock`` 做 fcntl.flock 互斥、以 tempfile + fsync + os.replace
    原子落盘（同 core/code_review._with_lock/_atomic_write 手法），彻底消除
    并发覆盖与半写。写失败静默降级（观测增强，不阻断主流程）。
    """
    try:
        tokens_json.parent.mkdir(parents=True, exist_ok=True)
        lock_path = tokens_json.parent / f".{tokens_json.name}.lock"
        with open(lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
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
                runs.append(entry)
                data["runs"] = runs
                content = json.dumps(data, ensure_ascii=False, indent=2)
                # 原子替换：进程唯一临时名 + fsync + os.replace
                fd, tmp_str = tempfile.mkstemp(
                    prefix=f".{tokens_json.name}.", suffix=".tmp",
                    dir=str(tokens_json.parent),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_str, str(tokens_json))
                finally:
                    tmp_path = Path(tmp_str)
                    if tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except OSError:
                            pass
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
    except (OSError, json.JSONDecodeError):
        pass


def _safe_int(value) -> int:
    """防御性整数转换（code-review item dc8f109b8b60）：非法值回落 0。

    token 记账是观测增强，写失败须静默降级、不阻断维护 run 主流程；agent/网关
    JSON 里解析出的非数值（带引号的 ``"12.5"``、``true``、嵌套结构等）此前让
    裸 ``int()`` 抛 ValueError/TypeError 穿透三个归账调用点——agent 工作已完成
    之后在收尾记账处崩溃，与「静默降级」契约相悖。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _token_usage_fields(usage_info: dict) -> dict:
    """把 usage_info 归整为归账记录的 token 字段（input 含三类 cache）。

    字段值经 ``_safe_int`` 防御转换（code-review item dc8f109b8b60）：非数值
    回落 0，不让畸形 usage 打挂维护 run 收尾。
    """
    if not isinstance(usage_info, dict):
        usage_info = {}
    return {
        "input_tokens": _safe_int(usage_info.get("input_tokens", 0) or 0)
        + _safe_int(usage_info.get("cache_creation_input_tokens", 0) or 0)
        + _safe_int(usage_info.get("cache_read_input_tokens", 0) or 0),
        "output_tokens": _safe_int(usage_info.get("output_tokens", 0) or 0),
        "cost_usd": usage_info.get("cost_usd"),
    }


def _accumulate_self_review_tokens(runner, date_str: str, usage_info: dict) -> None:
    """add-daily-self-review：自省 token 归账到 cost-observability 独立类目。

    design D2 二选一（独立 self-review 类目）：追加到
    ``.fenix/cost/self_review_tokens.json`` 的 runs 数组（与
    verify-progress tokens.json 同结构），供成本对账口径一致；不写
    STATE（禁止注册 STATE 条目硬约束）。写失败静默降级（观测增强，
    不阻断自省主流程）。写路径走 _append_token_run（flock + 原子替换）。
    """
    tokens_json = runner.project_root / ".fenix" / "cost" / "self_review_tokens.json"
    entry = {
        "agent_type": "self-review",
        "date": date_str,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **_token_usage_fields(usage_info),
    }
    _append_token_run(tokens_json, entry)


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
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"], model_override))
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
            except ContractError as e:
                run_ok = False
                error = str(e)
                contract = None
        except Exception as e:
            # 落地异常不应穿透（检查点统一捕获）；整轮视为失败带原因
            run_ok = False
            error = f"分析落地异常: {e}"
            contract = None
        finally:
            # 清理放外层 finally（code-review item f1ef92e5ca50）：``from
            # core.evolution import`` 在外层 try 内执行，其失败被外层 except
            # 捕获、从未进入内层 try/finally——旧清理位置盖不到 import 路径，
            # out-<run_id>.json 残留 .fenix/evolution/ 累积垃圾（与 docstring
            # 「run 结束读取并清理」不符）。finally 上移保证无论 import/
            # 读写成败都清理本 run 的产物文件。
            runner._delete_evolution_out(out_path)
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
    ``evolution`` 以便成本对账区分。写路径走 _append_token_run（flock +
    原子替换），与 self-review/code-review 共用，消除并发覆盖。
    """
    tokens_json = runner.project_root / ".fenix" / "cost" / "self_review_tokens.json"
    entry = {
        "agent_type": "evolution",
        "date": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **_token_usage_fields(usage_info),
    }
    _append_token_run(tokens_json, entry)


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
    run_id = runner._unique_code_review_run_id()
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
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"], model_override))
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

    # token 归账到独立类目（不写 STATE，与自省同一约束）。经门面调用
    # （对齐 run_administrator/run_self_review 的 runner.<method> 形态）：
    # 直接调模块函数会绕过 __getattr__，实例属性打桩被静默忽略。
    runner._accumulate_code_review_tokens(run_id, usage_info)

    # ── 产物硬门（2026-09-19 原地修复：此前该车道**全链无任何产物门**）────
    # 事故取证：run exit 0（subtype=success）但 agent 从未写过 out-<run_id>.jsonl
    # （只写了自己切批的 batch_N.json），_read_code_review_out 对缺失文件 return []，
    # 落账走完 inserted=0/updated=0 后仍返回 success=True——空跑被当成功，
    # 用户看到的进度条闪一下就消失。对照同族的 spec-review 车道：
    # SpecReviewManager.dispatch_review 有 _check_agent_result_artifact 硬门。
    # 判据与归因文案见 core/agent_runner/result_gate.py 的同名门函数。
    if run_ok:
        gate_err = _check_repo_code_review_artifact(manifest, opath)
        if gate_err is not None:
            run_ok = False
            error = gate_err
            _log = getattr(runner, "logger", None)
            if _log is not None:
                _log.error(
                    "code-review",
                    f"产物硬门拦截: run={run_id} manifest={len(manifest)} — {gate_err}",
                )

    # 读取增量产物并落账（产物缺失/解析失败 → success=False 带原因）
    inserted = updated = resolved = 0
    if run_ok:
        try:
            findings = runner._read_code_review_out(opath)
        except OSError as e:
            run_ok = False
            error = f"读取审查产物失败: {e}"
            findings = []
        # `_read_code_review_out` 所有返回路径都是 list（缺失文件返回 []），
        # 旧写法 `findings is not None` 是恒真判断（code-review item d315670fb35f），
        # 会误导读者以为存在 None 返回路径。直接判 run_ok。
        if run_ok:
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
                # 全仓快照核销：本轮未再观测到的 open 项置 resolved（D5）。
                # 空集保护（code-review item 69166b2235fd）：旧实现以 `if findings:`
                # 为门，但 `observed` 取的 `fingerprint` 字段 agent 从不产出（指纹由
                # upsert_findings 内部按 sha1(file|category|normalize_title) 现算），
                # 故常态是 findings 非空而 observed 为空集 → resolve_snapshot(root, set())
                # 会把台账**全部 open 置 resolved**（正是注释声明 MUST 避免的空集核销
                # 白洗）。改为在框架侧按**同一指纹口径**补算 observed，并以「observed
                # 非空」为最终门：既修复常态白洗，也保住「一条条目都没审出」时跳过核销。
                if findings:
                    try:
                        from core.code_review import fingerprint as _cr_fingerprint

                        observed = set()
                        for _f in findings:
                            if not isinstance(_f, dict):
                                continue
                            _fp = _f.get("fingerprint")
                            if not _fp:
                                _file = str(_f.get("file") or "")
                                _cat = str(_f.get("category") or "")
                                _title = str(_f.get("title") or "")
                                if _file and _title:
                                    _fp = _cr_fingerprint(_file, _cat, _title)
                            if _fp:
                                observed.add(_fp)
                        if observed:
                            resolved = resolve_snapshot(runner.project_root, observed)
                        else:
                            _log = getattr(runner, "logger", None)
                            if _log is not None:
                                _log.warning(
                                    "code-review",
                                    f"全仓快照核销跳过（run {run_id}）：本轮无可归一的"
                                    f"指纹（{len(findings)} 条 finding 缺 file/title），"
                                    f"拒绝空集核销以免误置全部 open 为 resolved",
                                )
                    except Exception:  # noqa: BLE001 — 核销失败记 WARNING 不使整轮失败
                        _log = getattr(runner, "logger", None)
                        if _log is not None:
                            _log.warning("code-review", f"全仓快照核销失败（run {run_id}）")

    # ── 自动修复激活（task 7.1 / design D4 路径一）────────────────────────
    # 成功落账且本轮 inserted > 0（产生了新 open 条目）→ 触发一次编排检查点。
    # 经可选的 runner._code_fix_orchestrator（未装配时静默跳过）；异常记
    # WARNING 不使审查 run 失败（评审车道异常不得影响审查既有判定）。
    if run_ok and inserted > 0:
        _orch = getattr(runner, "_code_fix_orchestrator", None)
        if _orch is not None:
            try:
                _orch.checkpoint()
            except Exception as e:  # noqa: BLE001 — 激活失败不影响审查 run
                _log = getattr(runner, "logger", None)
                if _log is not None:
                    _log.warning(
                        "code-review", f"code-fix 检查点触发失败（已忽略）: {e}"
                    )

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
    """生成并**原子申领**不冲突的 ``code-review-<epoch>`` run_id（task 3.7）。

    秒级时间戳在「手动触发 + 同秒周期触发」下可能撞名（manifest/out 文件
    会被互相覆盖）。目标文件已存在时追加 ``-<n>`` 退避（n 从 1 起递增）。

    申领即创建（code-review item e61828a54fda）：旧实现只探测 manifest/out
    是否存在后返回候选，探测-然后-行动窗口内两个同秒触发会同时通过探测、
    随后各自 write_text manifest 并驱动 agent 写同一 out 文件——恰好是该辅助
    声称要防的碰撞。现以 ``O_CREAT|O_EXCL`` 抢占 ``manifest-<candidate>.json``
    本身（原子），输者退避下一候选；占位内容为合法空 JSON ``{}``（
    read_progress 等读者对未完成 manifest 按 ``{}`` 兜底，不会解析失败），
    随后 run_code_review 的 write_text 以完整 manifest 原地覆盖。
    """
    base = f"code-review-{int(time.time())}"
    candidate = base
    n = 1
    cr_dir = runner.project_root / ".fenix" / "code-review"
    while True:
        if (cr_dir / f"out-{candidate}.jsonl").exists():
            n += 1
            candidate = f"{base}-{n}"
            continue
        try:
            cr_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 目录建不出（权限等）：退回既有语义——返回候选，落盘失败由
            # run_code_review 的 manifest 落盘路径统一报错
            return candidate
        try:
            fd = os.open(
                cr_dir / f"manifest-{candidate}.json",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
        except FileExistsError:
            # 已被并发触发申领 → 退避下一候选（申领即裁决，无再撞窗口）
            n += 1
            candidate = f"{base}-{n}"
            continue
        except OSError:
            return candidate
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("{}\n")
        return candidate


def _read_code_review_out(runner, opath: Path) -> list:
    """读取审查增量产物 ``out-<run_id>.jsonl``。

    每行为一个文件的审查结果 JSON（file/findings[]）。非 dict 行忽略；
    损坏行跳过；文件缺失返回空列表（run 失败路径已由 success=False 兜底）。

    ``runner`` 首参为门面注册表契约（self 首参模块函数）预留：本函数体
    不读 runner 状态，但经 ``runner._read_code_review_out(...)`` 转发时
    partial 会注入 runner 首参（code-review item 0c9577c146d9）。
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
    （审查 run 无 spec 维度）。写路径走 _append_token_run（flock + 原子替换）。
    """
    tokens_json = runner.project_root / ".fenix" / "cost" / "code_review_tokens.json"
    entry = {
        "agent_type": "code-review",
        "date": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **_token_usage_fields(usage_info),
    }
    _append_token_run(tokens_json, entry)


# ── 全量回归执行（add-test-regression-tab，task 3.1）────────────────────


def _unique_regression_run_id(runner) -> str:
    """生成不冲突的 ``regression-<epoch>`` run_id（task 3.1）。

    秒级时间戳在「手动触发 + 同秒周期触发」下可能撞名（对齐
    _unique_code_review_run_id 的退避形态）。信号文件/日志按 run 实例留痕。
    """
    base = f"regression-{int(time.time())}"
    candidate = base
    n = 1
    while True:
        if not (runner.project_root / ".fenix" / "regression" / f"run-{candidate}.json").exists():
            return candidate
        n += 1
        candidate = f"{base}-{n}"


def run_regression(runner, spec, reason: str = "manual", project_root=None, lock_root=None) -> RegressionResult:
    """执行一次全量回归（task 3.1，对齐 run_code_review 形态）。

    与 run_code_review 不同：**不经 LLM**——直接按 verify.yaml regression.cmd
    在项目根执行、解析 JUnit XML 并写 `.fenix/regression/last-run.json` 快照
    （core/regression.run_and_write_regression 封装）。本函数是 runner 门面
    转发表中的执行函数：run_id 前缀 ``regression-<epoch>``、结果写完后返回
    RegressionResult 信封。

    参数:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1；仅用
            project_root/logger）。
        spec: 已解析的 RegressionSpec（verify.yaml regression 段）。
        reason: manual / scheduled（写进结果快照供审计，缺省 manual）。
        project_root: 执行根（add-code-review-auto-fix D10）。缺省 None
            回落 ``runner.project_root``（既有调用点零迁移）。code-fix 批
            worker 传 worktree 根——回归命令 cwd 与快照均落 worktree
            （快照不指望出现在主树「测试回归」分面）。
        lock_root: 主机级锁锚定根（D10）。缺省 None。code-fix 批 worker
            传主树根，使 worktree 内回归与主树/其它 worktree 共用同一把
            ``.fenix/full-suite.lock``。

    返回:
        RegressionResult(status=快照状态, snapshot=完整快照)。
    """
    from core.regression import run_and_write_regression

    run_id = _unique_regression_run_id(runner)
    log = getattr(runner, "logger", None)
    exec_root = project_root if project_root is not None else runner.project_root

    try:
        snapshot = run_and_write_regression(
            exec_root,
            spec,
            logger=log,
            lock_root=lock_root,
        )
    except Exception as e:  # noqa: BLE001 — 执行异常兜底为失败快照
        snapshot = {
            "status": "parse_error",
            "cmd": str(getattr(spec, "cmd", "")),
            "output": str(getattr(spec, "output", "")),
            "reason": f"回归执行异常: {e}",
        }
        if log is not None:
            log.error("regression", f"回归执行异常（run {run_id}）: {e}")

    ok = snapshot.get("status") in ("passed", "failed", "timeout")
    status = snapshot.get("status", "parse_error")
    if status == "skipped":
        # 主机级锁未获取等：非成功也非失败（本次未执行）
        return RegressionResult(
            run_id=run_id,
            success=False,
            status=status,
            error=snapshot.get("reason", "skipped"),
            snapshot=snapshot,
        )
    return RegressionResult(
        run_id=run_id,
        success=ok,
        status=status,
        error=snapshot.get("reason", "") if not ok else "",
        snapshot=snapshot,
    )


# ── 自动修复执行（add-code-review-auto-fix，task 6.1-6.3）────────────────


class CodeFixResult:
    """code-fix run 的结果信封（run_code_fix 返回，add-code-review-auto-fix）。

    与 CodeReviewResult / RegressionResult 同形态的维护型 run 结果：
    - ``fixed`` / ``skipped``: out 产物行中 status=fixed / skipped 的计数
      （skipped 条目 MUST 保持 open——由编排器在合回成功后只核销 fixed）；
    - ``error``: success=False 时的失败原因（含产物硬门拦截文案）。
    """

    def __init__(
        self,
        run_id: str = "",
        success: bool = True,
        fixed: int = 0,
        skipped: int = 0,
        error: str = "",
        output: str = "",
    ):
        self.run_id = run_id
        self.success = success
        self.fixed = fixed
        self.skipped = skipped
        self.error = error
        self.output = output


def _unique_code_fix_run_id(runner, exclude=()) -> str:
    """生成不冲突的 ``code-fix-<epoch>`` run_id（task 6.2）。

    撞名判据（对齐 _unique_code_review_run_id 的退避形态）：runner 侧在飞
    run_id + 主树 ``.fenix/code-review/fix-out-<candidate>.jsonl`` 残留
    （run 的产物文件落在 worktree，此处以主树残留近似兜底并发窗口）+
    ``exclude`` 额外禁用集（编排器预生成重试轮 run_id 时传入本批已 issued
    的 run_id——重试产物落**同一 worktree**，主树残留判据覆盖不到，同秒
    撞名会让重试轮复用首轮 out 文件、破坏「重试独立文件并集」口径，
    add-code-fix-item-level-progress 2.2）。
    目标已占时追加 ``-<n>`` 退避（n 从 1 起递增）。
    """
    base = f"code-fix-{int(time.time())}"
    candidate = base
    n = 0
    cr_dir = runner.project_root / ".fenix" / "code-review"
    running = getattr(runner, "_running_agents", None) or {}
    while True:
        if (
            candidate in running
            or candidate in exclude
            or (cr_dir / f"fix-out-{candidate}.jsonl").exists()
        ):
            n += 1
            candidate = f"{base}-{n}"
            continue
        return candidate


def _check_code_fix_artifact(items, out_path: Path) -> str | None:
    """code-fix run 的产物硬门（task 6.2，对齐 _check_repo_code_review_artifact）。

    判据（fail-closed）：
    - ``items`` 为空 → None（调用方前置跳过场景，不重复判定）；
    - ``out_path`` 不存在，或存在但**零有效行** → 返回失败原因。

    「有效行」与编排侧 ``read_fix_out`` 同口径：非空、可解析为 dict、含
    非空 ``item_id`` 且 ``status ∈ {fixed, skipped}``——「该条处置完了」的
    登记形态。run exit 0 但无产物即判失败，空跑不得当成功。
    """
    if not items:
        return None
    if not out_path.is_file():
        return (
            f"code-fix 产物缺失: 注入清单 {len(items)} 条但 out 文件不存在"
            f"（{out_path}）——run 正常退出但零产物，判失败（fail-closed）"
        )
    valid = 0
    for line in out_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(rec, dict)
            and rec.get("item_id")
            and rec.get("status") in ("fixed", "skipped")
        ):
            valid += 1
    if valid == 0:
        return (
            f"code-fix 产物零有效行: 注入清单 {len(items)} 条但 {out_path} "
            "无一条可解析的 {item_id, status} 行，判失败（fail-closed）"
        )
    return None


def run_code_fix(
    runner,
    worktree_root,
    items: list,
    run_id: str | None = None,
    failure_summary: str = "",
) -> CodeFixResult:
    """执行一次 code-fix（自动修复）run（task 6.1，对齐 run_code_review 形态）。

    与 run_code_review 的差异：**在 worktree 内执行**（cwd=worktree_root，
    agent 可改码）；产物为逐条处置结果 ``fix-out-<run_id>.jsonl``（每行
    ``{item_id, status: fixed|skipped, file}``）；不经台账（核销由编排器在
    合回成功后经 ``core.code_review.mark_resolved`` 驱动）。

    - run_id 前缀 ``code-fix-<epoch>``：运维车道，不占 spec 维度预算、
      不计入每日 agent run 计数（不走 _execute_agent）；
    - 模型解析链（design D1）：agents.models.code-fix 分配优先 → 回退
      agents.models.code-review → 回退 self-review → 回退 administrator →
      再回退 _get_admin_model → 默认网关（缺省即与 code-review 同源）；
    - 产物硬门：注入清单非空而 out 缺失/零有效行 → success=False；
    - ``failure_summary`` 非空时注入 prompt（回归失败重试轮，task 5.6）。

    Args:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1）。
        worktree_root: 本批 worktree 根（agent 工作目录）。
        items: 本批台账条目 record 列表（select_batch 产物）。
        run_id: 缺省自动生成（code-fix-<epoch>）。
        failure_summary: 重试轮注入的失败用例摘要（首轮为空）。
    """
    run_id = run_id or _unique_code_fix_run_id(runner)
    wt = Path(worktree_root)
    out_path = wt / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return CodeFixResult(
            run_id=run_id, success=False, error=f"out 目录创建失败: {e}"
        )

    prompt = runner._build_prompt(
        run_id,
        "code-fix",
        detail={
            "items": items,
            "out_path": str(out_path),
            "worktree": str(wt),
            "failure_summary": failure_summary,
        },
    )

    # 模型解析链（D1）：code-fix > code-review > self-review > administrator
    # > _get_admin_model → 默认网关（缺省与 code-review 同源）
    env_overrides: Dict[str, str] = {}
    assignment = (
        runner._get_agent_model_assignment("code-fix")
        or runner._get_agent_model_assignment("code-review")
        or runner._get_agent_model_assignment("self-review")
        or runner._get_agent_model_assignment("administrator")
    )
    if assignment:
        provider, model_override = assignment[0]
        env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
        env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
        env_overrides["ANTHROPIC_MODEL"] = model_override
        env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"], model_override))
        for k, v in (provider.get("env") or {}).items():
            env_overrides[k] = v
    else:
        model_override = runner._get_admin_model()

    try:
        output, _turns, _session_id, _usage_info = runner._run_claude(
            prompt,
            wt,
            run_id,
            model_override,
            env_overrides,
            max_turns=runner._get_config("agents.max_turns", 300),
            spec_name="code-review-fix",
            agent_type="code-fix",
        )
        run_ok = True
        error = ""
    except Exception as e:  # noqa: BLE001 — run 异常兜底为失败信封
        output = ""
        run_ok = False
        error = str(e)

    # ── 产物硬门（task 6.2）：run exit 0 但 out 缺失/零有效行 → 判失败 ──
    if run_ok:
        gate_err = _check_code_fix_artifact(items, out_path)
        if gate_err is not None:
            run_ok = False
            error = gate_err
            _log = getattr(runner, "logger", None)
            if _log is not None:
                _log.error(
                    "code-fix",
                    f"产物硬门拦截: run={run_id} items={len(items)} — {gate_err}",
                )

    # out 解析（fixed/skipped 计数；skipped 条目由编排器保持 open）
    fixed = skipped = 0
    if run_ok:
        for rec in _read_fix_out_rows(out_path):
            if rec.get("status") == "fixed":
                fixed += 1
            elif rec.get("status") == "skipped":
                skipped += 1

    return CodeFixResult(
        run_id=run_id,
        success=run_ok,
        fixed=fixed,
        skipped=skipped,
        error=error,
        output=output,
    )


def _read_fix_out_rows(out_path: Path) -> list:
    """读取 out 产物行（dict 列表；损坏行跳过、缺文件返回空）。"""
    rows: list = []
    if not out_path.is_file():
        return rows
    for line in out_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("item_id"):
            rows.append(rec)
    return rows


# ── impl ocr 异步审查车道（add-impl-ocr-parallel-lane，任务 3.1-3.4）──────
#
# 车道 = 维护型 run（对齐 run_code_review/run_regression 形态）：不经
# _execute_agent、不占 spec 预算、不创建 worktree 语义由「自建 detached
# 检出」替代——审的是已 merge-back 的实现分支 head（merge-back 不改分支
# ref，head_commit 即分支最新形态）。与 tester 验证并行启动，join 于
# testing 出口（裁决在 core/pm_engine/dispatch/queue.py 的 join 评估）。

# ocr 可执行文件的默认裸名（包装器 bin/ocr_review.py 以 os.execvp 解析 PATH，
# 裸名可用；随车道消费点迁入本模块，runner.py re-export——D2b 规则 3 先例
# 同 DEFAULT_GATEWAY_MODEL）。
DEFAULT_OCR_BIN = "ocr"


def _impl_ocr_paths(project_root: Path, spec_name: str) -> tuple:
    """车道产物的主树路径三元组 ``(artifact, raw, cursor)``。"""
    vp = Path(project_root) / ".fenix" / "verify-progress" / spec_name
    return (
        vp / "code-review.json",
        vp / "code-review-raw.json",
        vp / "ocr-cursor.json",
    )


def _unique_impl_ocr_run_id(spec_name: str) -> str:
    """车道 run_id：``impl-ocr-<spec>-<epoch>``（前缀登记见 run_files 3.5）。

    同 spec 车道单飞（join 侧在飞登记去重）+ 秒级时间戳，撞名窗口可忽略；
    即便同秒双实例，产物写侧为原子替换，后写者覆盖亦无害。
    """
    return f"impl-ocr-{spec_name}-{int(time.time())}"


def _ocr_finding_fingerprint(finding: dict) -> str:
    """finding 指纹：``sha1(path|category|content[:200])``（车道写侧与 join
    读侧共用同一口径，杜绝双实现漂移；对齐 code-review 台账指纹思想）。"""
    path = str(finding.get("path") or finding.get("file") or "")
    category = str(finding.get("category") or "")
    content = str(finding.get("content") or finding.get("description") or "")[:200]
    return hashlib.sha1(f"{path}|{category}|{content}".encode("utf-8")).hexdigest()


def _read_ocr_exclude_patterns(project_root) -> list:
    """读项目级 ocr 审查排除域 ``<project_root>/.fenix/ocr-exclude.txt``。

    逐行一条 gitignore 风格 pattern；空行与 `#` 注释行跳过。文件缺失/读失败
    → 空列表（调用方零注入，ocr 命令与无此文件时逐字节一致）。
    """
    try:
        text = (Path(project_root) / ".fenix" / "ocr-exclude.txt").read_text(
            encoding="utf-8"
        )
    except OSError:
        return []
    return [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _normalize_impl_ocr_findings(comments) -> list:
    """ocr 原始报告 comments → 车道产物 findings（宽松解析，design D7）。

    「具体键名以现场跑出的原始报告为准」教训延续：path/file、
    start_line/line、content/description/message 逐级回退；缺 path 的行
    丢弃（无锚点的 finding 对修复轮不可定位）。MUST NOT 抛异常。
    """
    out: list = []
    if not isinstance(comments, list):
        return out
    for c in comments:
        if not isinstance(c, dict):
            continue
        path = str(c.get("path") or c.get("file") or "").strip()
        if not path:
            continue
        try:
            start_line = int(c.get("start_line", c.get("line", 0)) or 0)
        except (TypeError, ValueError):
            start_line = 0
        out.append(
            {
                "path": path,
                "start_line": start_line,
                "category": str(c.get("category") or "general"),
                "severity": str(c.get("severity") or "info"),
                "content": str(
                    c.get("content") or c.get("description") or c.get("message") or ""
                ).strip(),
            }
        )
    return out


def _carry_forward_ocr_findings(prev_findings, new_findings: list) -> list:
    """上一产物中未裁决 findings 携带进新产物（增量审查防丢失）。

    增量审查只覆盖 cursor 以来的提交，上一轮报告的 findings 不会重现；
    实现者已在 worktree 处置文件上标注 disposition 并经拷回通道覆盖主树
    产物时，disposition ∈ {fixed, rejected} 的视为已裁决不携带；其余
    （未处置/deferred/处置文件缺失）按指纹去重后并入新 findings。已在本轮
    重现的 finding 以新版本为准（不叠加旧注释字段）。
    """
    new_fps = {_ocr_finding_fingerprint(f) for f in new_findings}
    out: list = []
    if not isinstance(prev_findings, list):
        return out
    for f in prev_findings:
        if not isinstance(f, dict):
            continue
        if f.get("disposition") in ("fixed", "rejected"):
            continue
        if _ocr_finding_fingerprint(f) in new_fps:
            continue
        out.append(dict(f))
    return out


def _read_ocr_cursor(cursor_path: Path) -> str | None:
    """读增量游标 ``last_reviewed_commit``；缺失/损坏/非字符串 → None。"""
    try:
        data = json.loads(cursor_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    commit = data.get("last_reviewed_commit")
    return commit if isinstance(commit, str) and commit else None


def _write_ocr_cursor(cursor_path: Path, commit: str) -> None:
    """审查成功后推进游标（原子替换；失败静默——下次回退全量，不影响正确性）。"""
    try:
        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cursor_path.with_name(".ocr-cursor.json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "last_reviewed_commit": commit,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, cursor_path)
    except OSError:
        pass


def _git_is_ancestor(project_root: Path, ancestor: str, descendant: str) -> bool:
    """``git merge-base --is-ancestor`` 包装（超时/异常一律按非祖先处理）。"""
    try:
        r = subprocess.run(
            ["git", "-C", str(project_root), "merge-base", "--is-ancestor",
             ancestor, descendant],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001 — 游标可用性判定，失败回退全量
        return False


def _remove_impl_ocr_worktree(project_root: Path, wt) -> None:
    """车道 detached 检出清理（remove --force + prune，对齐 serving 手法）。"""
    if wt is None:
        return
    try:
        subprocess.run(
            ["git", "-C", str(project_root), "worktree", "remove", "--force", str(wt)],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        subprocess.run(
            ["git", "-C", str(project_root), "worktree", "prune"],
            capture_output=True, timeout=15,
        )
    except Exception:  # noqa: BLE001
        pass


def _accumulate_impl_ocr_tokens(runner, run_id: str, summary) -> None:
    """车道 token 记账（对齐 _accumulate_code_review_tokens 形态，任务 3.1）。

    追加到 ``.fenix/cost/code_review_tokens.json``，agent_type 标注
    ``impl-ocr``。ocr 原始 summary 的 input_tokens **已含** cache_read
    （实测 total_tokens = input + output 闭合），MUST NOT 再叠加
    cache_read_tokens 重复计费。写失败静默降级（观测增强，不阻断车道）。
    """
    try:
        if not isinstance(summary, dict):
            summary = {}
        tokens_json = runner.project_root / ".fenix" / "cost" / "code_review_tokens.json"
        entry = {
            "agent_type": "impl-ocr",
            "date": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input_tokens": int(summary.get("input_tokens", 0) or 0),
            "output_tokens": int(summary.get("output_tokens", 0) or 0),
            "cost_usd": summary.get("cost_usd"),
        }
        _append_token_run(tokens_json, entry)
    except Exception:  # noqa: BLE001 — 记账失败不影响车道结论
        pass


def _write_impl_ocr_run_events(project_root: Path, run_id: str, spec_name: str,
                               events: list) -> None:
    """车道 run jsonl 最小生命周期（时间线可见，不经 _run_claude）。

    events 为 (type, extra_dict) 序列；末行为终态语义由调用方保证
    （result/error 二选一）。写失败静默（观测通道，不阻断车道）。
    """
    try:
        run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        for ev_type, extra in events:
            append_run_line(
                run_file,
                {
                    "type": ev_type,
                    "spec": spec_name,
                    "agent_type": "impl-ocr",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **(extra or {}),
                },
            )
    except Exception:  # noqa: BLE001
        pass


# ── ocr 车道运行中心跳（fix-ocr-lane-orphaned-state-misfire D1/D2）──────────
# 间隔 MUST 小于 ORPHANED_RUN_GRACE_SECONDS=120s（core/admin_monitor.py，无驱动
# 探针条件①的 run mtime 宽限窗）：45s 留出线程调度与写盘抖动余量——心跳持续
# 刷新 run 转录 mtime → 条件①持续为假 → 车道在跑不再被误判「无驱动」。模块级
# 常量（读在 _start_impl_ocr_heartbeat 调用时而非缺省参数绑定）：测试经
# monkeypatch 缩至亚秒级，套件时长不被真实间隔放大。不引入配置键（D4）。
IMPL_OCR_HEARTBEAT_INTERVAL_SECONDS = 45.0

# 停跳 join 上限（秒）：Event 置位后循环至多再写一条 progress 即退出，正常
# 亚秒返回；上限仅防极端写阻塞拖住车道收尾（观测通道不值得久等）。
IMPL_OCR_HEARTBEAT_JOIN_TIMEOUT_SECONDS = 5.0


def _start_impl_ocr_heartbeat(project_root: Path, run_id: str, spec_name: str,
                              from_commit: str, head_commit: str) -> tuple:
    """启动车道运行中心跳线程，返回 ``(stop_event, thread)``。

    审查子进程运行期间按 ``IMPL_OCR_HEARTBEAT_INTERVAL_SECONDS`` 间隔经既有
    ``_write_impl_ocr_run_events`` 向车道 run 转录追加 ``progress`` 事件
    （review 区间 from/to + 自启动起 ``time.monotonic`` 已用时秒数）。消费
    orphaned_state 无驱动探针条件①（run mtime 宽限窗）：``_has_recent_spec_run``
    因心跳持续为真 → ``spec_is_undriven`` 为假，大 diff 长审查不再误报孤儿；
    探针判定函数本体零改动。daemon 重启心跳自然停止 → 宽限+阈值过后真孤儿
    仍被正常上报（不加任何 ``_ocr_join_wait`` 有意等待豁免，不遮蔽自愈链）。

    调用方收尾 MUST 先 ``stop_event.set()`` + ``thread.join(有上限)`` 停跳、
    再写终态事件（``result``/``error`` 末行后置不变量，D2 顺序）。心跳写失败
    静默（``_write_impl_ocr_run_events`` 既有语义，观测通道不阻断车道）。
    daemon=True + try/finally 全覆盖兜底：任何路径漏 set 停跳位也不阻塞进程
    退出（线程泄漏风险的最后防线，见 SPEC Risks）。
    """
    interval = IMPL_OCR_HEARTBEAT_INTERVAL_SECONDS
    started = time.monotonic()
    stop_event = threading.Event()

    def _loop() -> None:
        # Event.wait(interval) 可中断等待：置位即退出（含正在等待的余程），
        # 超时返回 False 才发一条心跳——停跳延迟至多一个间隔。
        while not stop_event.wait(interval):
            _write_impl_ocr_run_events(
                project_root,
                run_id,
                spec_name,
                [(
                    "progress",
                    {
                        "message": "ocr 审查进行中（运行中心跳）",
                        "review_range": {"from": from_commit, "to": head_commit},
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    },
                )],
            )

    thread = threading.Thread(
        target=_loop, name=f"impl-ocr-heartbeat-{run_id}", daemon=True
    )
    thread.start()
    return stop_event, thread


def _stop_impl_ocr_heartbeat(stop_event, thread) -> None:
    """停跳（D2 顺序约束）：置位 + 有上限 join，先于终态事件写入。

    幂等（Event.set 可重入、join 已死线程立即返回），供子进程收尾 finally
    与车道整体 finally 双重调用（意外异常路径同样停跳）。返回后心跳线程
    不再追加任何 ``progress`` 行，主线程独占写——终态事件得以保持文件末行，
    归档/worktree 清理也不会被迟到的心跳复活旧文件。
    """
    if stop_event is not None:
        stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=IMPL_OCR_HEARTBEAT_JOIN_TIMEOUT_SECONDS)


def run_impl_ocr(
    runner,
    spec_name: str,
    branch: str,
    base_commit: str,
    head_commit: str,
) -> dict:
    """实现分支收尾 ocr 审查车道（add-impl-ocr-parallel-lane，任务 3.1-3.4）。

    在 ``head_commit`` 的 detached 检出内跑
    ``bin/ocr_review.py review --from <base> --to <head>``（--concurrency/
    --effort 取配置注入；provider 注入复用 implementer 分配 +
    ``_write_run_ocr_config`` 同源机制，任务 3.2）。产物由框架直写主树
    ``.fenix/verify-progress/<spec>/code-review.json``：

    - ``status`` 白名单 ``completed | unavailable``；unavailable MUST 附
      非空 ``reason``（超时/非零退出/provider 不可达/非 git 仓库/解析失败）；
    - ``fingerprint`` = ``(branch, merge_base, head_commit)``——join 读侧
      fail-closed 的比对键（4.3），MUST 为触发时捕获的指纹而非增量游标；
    - 原始报告副本落同目录 ``code-review-raw.json``（供审计/重解析）。

    增量游标（任务 3.4）：``ocr-cursor.json`` 记 ``last_reviewed_commit``；
    重跑优先 ``--from <cursor>``，cursor 缺失/非 head 祖先回退全量；成功后
    推进游标。fingerprint 不随游标走（join 比对的仍是触发指纹）。

    本函数 **MUST NOT 抛未捕获异常**（任务 3.3）：任何意外异常都折算为
    ``unavailable`` 产物收尾；detached 检出在 finally 中清理。

    运行中心跳（fix-ocr-lane-orphaned-state-misfire 1.1）：审查子进程运行
    期间由后台定时线程（daemon=True + ``threading.Event`` 停跳位，循环
    ``Event.wait`` 可中断）按 ``IMPL_OCR_HEARTBEAT_INTERVAL_SECONDS``（45s，
    小于 orphaned_state 探针条件①的 ``ORPHANED_RUN_GRACE_SECONDS``=120s 宽限，
    留调度抖动余量）经 ``_write_impl_ocr_run_events`` 向车道 run 转录追加
    ``progress`` 事件（review 区间 + 已用时），持续刷新 run 文件 mtime——
    消费 ``spec_is_undriven`` 条件①，车道在跑（无论审查多久）不再被判
    「无驱动」，探针判定函数本体零改动。子进程返回（完成/非零退出/车道
    硬超时）先 ``stop_event.set()`` + ``join(有上限)`` 停跳、再写终态事件
    （``result``/``error`` 末行后置不变量）；try/finally 覆盖一切退出路径，
    停跳后不再有任何 ``progress`` 追加；心跳写失败静默不影响收尾。daemon
    重启心跳自然停止 → 宽限+阈值过后真孤儿仍被正常上报（不加任何
    ``_ocr_join_wait`` 有意等待豁免——该字段无 boot 恢复，重启场景恰恰依赖
    orphaned_state 兜底）。
    """
    from core.config import ConfigLoader

    run_id = _unique_impl_ocr_run_id(spec_name)
    log = getattr(runner, "logger", None)
    artifact_path, raw_path, cursor_path = _impl_ocr_paths(
        runner.project_root, spec_name
    )
    artifact: dict = {
        "status": "unavailable",  # 缺省失败态，成功路径显式改写
        "spec": spec_name,
        "run_id": run_id,
        "kind": "impl-ocr-lane",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": {
            "branch": branch,
            "merge_base": base_commit,
            "head_commit": head_commit,
        },
        "review_range": {},
        "llm": {},
        "findings": [],
        "reason": "",
    }

    _write_impl_ocr_run_events(
        runner.project_root,
        run_id,
        spec_name,
        [("start", {"message": f"ocr 车道启动: {branch} {base_commit[:8]}..{head_commit[:8]}"})],
    )

    wt = None
    heartbeat = None  # (stop_event, thread)；审查子进程运行期非 None
    try:
        # ── provider 注入（任务 3.2）：复用 implementer 分配 + 同源 _write_run_ocr_config ──
        env_overrides: Dict[str, str] = {"FENIX_OCR_BIN": DEFAULT_OCR_BIN}
        assignment = runner._get_agent_model_assignment("implementer")
        if assignment:
            provider, model_override = assignment[0]
            ocr_home = runner._write_run_ocr_config(provider, model_override)
            if ocr_home is not None:
                env_overrides["FENIX_OCR_HOME"] = str(ocr_home)
            artifact["llm"] = {
                "provider": provider.get("name"),
                "model": model_override,
            }

        # ── detached 检出（审的是分支 head；非 git 仓库在此折算 unavailable）──
        serving_root = runner.project_root / ".fenix" / "verify-serving"
        serving_root.mkdir(parents=True, exist_ok=True)
        wt = serving_root / f"ocr-{run_id}"
        r = subprocess.run(
            ["git", "-C", str(runner.project_root), "worktree", "add", "--detach",
             str(wt), head_commit],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            artifact["reason"] = (
                f"车道 detached 检出失败（head={head_commit[:8]}）: "
                f"{(r.stderr or r.stdout).strip()[-300:]}"
            )
        else:
            # ── 增量游标（任务 3.4）：cursor 缺失/非祖先回退全量 ──
            from_commit = base_commit
            incremental = False
            cursor = _read_ocr_cursor(cursor_path)
            if (
                cursor
                and cursor != head_commit
                and _git_is_ancestor(runner.project_root, cursor, head_commit)
            ):
                from_commit = cursor
                incremental = True
            artifact["review_range"] = {
                "from": from_commit,
                "to": head_commit,
                "incremental": incremental,
            }

            # ── 上一产物 findings 预读（carry-forward 供成功路径合并）──
            prev_findings: list = []
            try:
                prev = json.loads(artifact_path.read_text(encoding="utf-8"))
                if isinstance(prev, dict) and isinstance(prev.get("findings"), list):
                    prev_findings = prev["findings"]
            except (OSError, ValueError):
                prev_findings = []

            # ── 跑 ocr（硬超时 = 车道级 impl_code_review_lane_timeout_sec，任务 3.3）──
            # GIT_DIR/GIT_WORK_TREE 钉住 detached worktree：ocr 的仓库发现在
            # linked worktree（.git 为文件）里会漂移到主检出（实测：实现者
            # 收尾审查在 worktree 直跑时 --from 被归一成与主树 HEAD 的
            # merge-base，审查区间整体漂到 main 侧），显式 env 钉住后 git
            # 子命令一律解析回本 wt。
            env_overrides["GIT_DIR"] = str(wt / ".git")
            env_overrides["GIT_WORK_TREE"] = str(wt)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                sys.executable, "bin/ocr_review.py", "review",
                "--from", from_commit,
                "--to", head_commit,
                "--concurrency",
                str(ConfigLoader.get_impl_code_review_concurrency(runner.config)),
                "--effort", ConfigLoader.get_impl_code_review_effort(runner.config),
                "--format", "json",
                "--output", str(raw_path),
            ]
            # 项目级排除域（09-23 误报治理）：`.fenix/ocr-exclude.txt` 存在且
            # 含有效行（非空、非 `#` 注释）时逐行拼成逗号分隔串，经 ocr
            # `--exclude`（gitignore 风格，与 rule.json excludes 合并）下发；
            # 文件缺失/空 → 零注入（命令与现状逐字节一致）。
            exclude_patterns = _read_ocr_exclude_patterns(runner.project_root)
            if exclude_patterns:
                cmd += ["--exclude", ",".join(exclude_patterns)]
            # ── 运行中心跳（fix-ocr-lane-orphaned-state-misfire 1.1）：子进程
            # 运行期唯一启跳（elapsed 自子进程启动起计）；返回/超时先停跳再
            # 走分类收尾，终态事件保持末行后置（1.2 顺序约束）。──
            heartbeat = _start_impl_ocr_heartbeat(
                runner.project_root, run_id, spec_name, from_commit, head_commit
            )
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(wt),
                    env={**os.environ, **env_overrides},
                    capture_output=True,
                    text=True,
                    timeout=ConfigLoader.get_impl_code_review_lane_timeout_sec(
                        runner.config
                    ),
                )
                timed_out = False
            except subprocess.TimeoutExpired:
                proc = None
                timed_out = True
            finally:
                # 完成/非零退出/硬超时/意外异常四路同收口：停跳后本线程独占
                # 写（幂等，车道整体 finally 二次调用无害）。
                _stop_impl_ocr_heartbeat(*heartbeat)

            if timed_out:
                lane_timeout = ConfigLoader.get_impl_code_review_lane_timeout_sec(
                    runner.config
                )
                artifact["reason"] = (
                    f"车道硬超时（>{lane_timeout}s，verify."
                    f"impl_code_review_lane_timeout_sec）"
                )
            elif proc.returncode != 0:
                artifact["reason"] = (
                    f"ocr 非零退出（rc={proc.returncode}）: "
                    f"{(proc.stderr or proc.stdout or '').strip()[-400:]}"
                )
            else:
                raw = None
                try:
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raw = None
                if not isinstance(raw, dict):
                    artifact["reason"] = (
                        "ocr 原始报告缺失或不可解析（exit 0 但无有效 JSON）"
                    )
                else:
                    # ── 成功路径：规范化 findings + carry-forward + 记账 + 推进游标 ──
                    findings = _normalize_impl_ocr_findings(raw.get("comments"))
                    findings.extend(_carry_forward_ocr_findings(prev_findings, findings))
                    artifact["status"] = "completed"
                    artifact["findings"] = findings
                    artifact["reason"] = ""
                    _accumulate_impl_ocr_tokens(runner, run_id, raw.get("summary"))
                    _write_ocr_cursor(cursor_path, head_commit)
    except Exception as e:  # noqa: BLE001 — 车道内部异常折算 unavailable（任务 3.3）
        artifact["status"] = "unavailable"
        artifact["reason"] = f"车道内部异常: {type(e).__name__}: {e}"
        if log is not None:
            log.warning(
                "agent_runner",
                f"impl-ocr 车道内部异常（run {run_id}）: {type(e).__name__}: {e}",
            )
    finally:
        # 停跳兜底（1.2 全路径覆盖）：心跳启动后任何未预期异常路径（含降级
        # unavailable 各分支）都先停跳，再清理 worktree——归档/清理不会被
        # 迟到的 progress 复活旧文件。心跳未启动（前置分支失败）时为 no-op。
        if heartbeat is not None:
            _stop_impl_ocr_heartbeat(*heartbeat)
        _remove_impl_ocr_worktree(runner.project_root, wt)

    # ── 产物原子落盘（unavailable/completed 两条路径都写，join 读侧以文件为准）──
    try:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = artifact_path.with_name(".code-review.json.tmp")
        tmp.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, artifact_path)
    except OSError as e:
        if log is not None:
            log.warning("agent_runner", f"impl-ocr 产物落盘失败（run {run_id}）: {e}")

    _write_impl_ocr_run_events(
        runner.project_root,
        run_id,
        spec_name,
        [
            (
                "result",
                {
                    "status": artifact["status"],
                    "findings": len(artifact["findings"]),
                    "reason": artifact["reason"],
                },
            )
        ],
    )
    if log is not None:
        log.info(
            "agent_runner",
            f"impl-ocr 车道完成（run {run_id}）: status={artifact['status']} "
            f"findings={len(artifact['findings'])}",
        )
    return artifact
