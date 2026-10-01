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

import dataclasses
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import signal
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


def _apply_provider_env(
    env_overrides: Dict[str, str], provider: dict, model_override: str, runner
) -> None:
    """取链首选 provider 的 env_overrides 注入口径（五个维护型 run 共用）。

    code-review item 8303928771e4 去重：run_administrator / run_self_review /
    run_evolution / run_code_review / run_code_fix 此前各自复制同一段组装
    （ANTHROPIC_BASE_URL/API_KEY/ANTHROPIC_MODEL/CLAUDE_CONFIG_DIR +
    provider.env 合并），注入口径任何变化（新增默认 env 键、CLAUDE_CONFIG_DIR
    生成规则调整等）都须同步改五处，漏一处即车道间行为漂移（同
    _write_signal_exclusive 去重先例 422ae03395de 的动机）。各车道的
    assignment 回退链顺序不同属设计差异，留在调用侧。
    """
    env_overrides["ANTHROPIC_BASE_URL"] = provider["baseurl"]
    env_overrides["ANTHROPIC_API_KEY"] = provider["apikey"]
    env_overrides["ANTHROPIC_MODEL"] = model_override
    env_overrides["CLAUDE_CONFIG_DIR"] = str(runner._ensure_agent_config_dir(provider["name"], model_override))
    for k, v in (provider.get("env") or {}).items():
        env_overrides[k] = v


def _write_lane_provider_marker(
    runner, run_id: str, spec_name: str, agent_type: str, assignment
) -> None:
    """维护型车道 assignment 命中时写 provider_marker（code-review item
    faea95e2d494）。

    五条维护车道（administrator/self-review/evolution/code-review/code-fix）
    都不经 _execute_agent_inner 的 attempt 环（runner.py 的自动写点），此前
    除 run_administrator 手动写点外，其余四条车道的 run jsonl 无任何
    provider/model 痕迹；而 _admin_failure_evidence 定位「模型不被网关接受」
    类失败正依赖 provider_marker。本助手在各车道 assignment 命中分支统一
    接入，观测口径一致：车道不接 failover、只用链首选直连，链内下标恒 0/1
    （与 run_administrator 既有写点同口径）。未命中（回退 _get_admin_model
    的默认网关形态）不写。写点是观测增强：替身 runner 缺写点或写入失败
    均不阻断维护 run 主流程。
    """
    if not assignment:
        return
    provider, model_override = assignment[0]
    marker_fn = getattr(runner, "_write_provider_marker", None)
    if not callable(marker_fn):
        # 替身/精简 runner 未提供写点（观测通道缺失）→ 跳过，不阻断车道
        return
    try:
        marker_fn(
            run_id,
            spec_name,
            agent_type,
            provider.get("name"),
            model_override,
            0,
            1,
        )
    except Exception as e:  # noqa: BLE001 — 观测增强，写失败不阻断维护 run
        _log = getattr(runner, "logger", None)
        if _log is not None:
            _log.warning(
                "agent_runner",
                f"provider_marker 写入失败 {run_id}（不阻断维护 run）: {e}",
            )


def _unique_admin_run_id(runner, spec: str) -> str:
    """生成不冲突的 ``admin-<spec>-<epoch>`` run_id（code-review item d543e3aaf129）。

    秒级时间戳在「同 spec 并行多实例」（如 manual-intervention 与 blocked_stuck
    各一）下可能撞名：admin_disposition-<run_id>.json 实例文件与
    runs/admin-<run_id>.jsonl 会互相覆盖，与 fix-admin-run-blocks-mainloop D3
    声称的「并行实例互不覆盖」相悖。对齐 _unique_code_review_run_id 的退避
    形态：候选的处置实例文件或在飞 run 日志任一已存在，即追加 ``-<n>`` 退避
    （n 从 1 起递增）。探测退避而非 O_CREAT|O_EXCL 申领：处置实例文件由
    管理员按 prompt 注入的路径写入、读取即清理，抢先落申领占位文件会改变
    该文件的写入时序与生命周期，故不做原子抢占。
    """
    base = f"admin-{spec}-{int(time.time())}"
    candidate = base
    n = 0
    runs_dir = runner.project_root / ".fenix" / "runs"
    while True:
        if (
            admin_disposition_path(runner.project_root, candidate).exists()
            or (runs_dir / f"{candidate}.jsonl").exists()
        ):
            n += 1
            candidate = f"{base}-{n}"
            continue
        return candidate


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
    run_id = _unique_admin_run_id(runner, spec)
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
        _apply_provider_env(env_overrides, provider, model_override, runner)
        # 观测：run jsonl 写 provider_marker，与 dispatch attempt 路径同口径，
        # 时间轴才能展示 Administrator 实际驱动的 model@provider；写点已提取
        # 为 _write_lane_provider_marker 与其余四条维护车道共用（item
        # faea95e2d494），Administrator 不接 failover，链内下标恒 0/1
        _write_lane_provider_marker(runner, run_id, spec, "administrator", assignment)
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
    # ── 产物硬门（对齐 code-review/code-fix 车道的 fail-closed 先例：
    # _check_repo_code_review_artifact / _check_code_fix_artifact）──────────
    # _run_claude 正常退出（success=True）但管理员从未按 prompt 写入处置文件
    # （文件缺失/不可解析 → _read_admin_disposition 返回空 dict）时，下方
    # result 兜底会把空跑折算成 "resolved"——消费侧 admin_monitor 对非 pending
    # 且非 escalate 的 result 直接 mark_signal_handled，resolved 还会触发自动
    # 复位，困境信号被零动作误闭环。按 fail-closed 折算为失败，错误信息点名
    # 「admin 未写处置文件」。
    if success and not disp:
        success = False
        error = (
            f"admin 未写处置文件: run 正常退出但 {disp_path.name} 缺失或不可解析，"
            "Administrator 零产物，判失败（fail-closed）"
        )
        _log = getattr(runner, "logger", None)
        if _log is not None:
            _log.warning(
                "agent_runner",
                f"Administrator run {run_id} 产物硬门拦截: {error}",
                {"run_id": run_id, "spec": spec},
            )
    # code-review item 4da16a7b2928：残缺产物同门——文件可解析但缺 result 字段
    # （如只写 summary/actions_taken）时，下方 result 兜底同样会把残缺产物折算
    # 成 "resolved"，与上一道门要消灭的「空跑被零动作误闭环」同方向。合法取值
    # 以消费侧实际认可为准，不发明词表：agents/administrator.md 指令枚举
    # resolved | partially-resolved | escalated，admin_monitor 终态消费另认
    # failed（处置未成功的保守保留值）；pending 是框架唤起前自身的占位值、
    # interrupted 是 monitor 孤儿接管自写值，均非管理员终态取值。一并按
    # fail-closed 折算为失败（escalate 位不受影响，升级通道照常）。
    if success and disp.get("result") not in (
        "resolved", "partially-resolved", "escalated", "failed",
    ):
        _raw_result = disp.get("result")
        success = False
        # code-review item 14ce3542d2b9：硬门折算必须同时落到 result 通道——
        # 仅折算 success 位时，下方返回值 result=disp.get("result") or ...
        # 会把非空非法值（如管理员误写 "done"/"resolve"）原样透传。消费侧
        # admin_monitor 已按同 item 给终态回写门补上 success 前置条件
        # （success=False 不再 mark_signal_handled），此处折算 result 通道
        # 属双保险：兼容替身/旧消费方，以及 latest_resolved_disposition 等
        # 只看 result 的查询路径。此处置合法保留值 "failed" 折算返回值，
        # 原始非法值保留在下方 error 文案中取证。
        disp["result"] = "failed"
        error = (
            f"admin 处置记录 result 非法: {disp_path.name} 可解析但 result "
            "缺失或不在合法枚举（resolved/partially-resolved/escalated/failed，"
            f"实际值 {_raw_result!r}），残缺产物判失败（fail-closed）"
        )
        _log = getattr(runner, "logger", None)
        if _log is not None:
            _log.warning(
                "agent_runner",
                f"Administrator run {run_id} 产物硬门拦截: {error}",
                {"run_id": run_id, "spec": spec},
            )
    # 读取即清理自身实例文件：内容已捕获进 AdminDisposition 返回给调用方落
    # final 记录，文件不再有读者；不清理会随并行实例累积成垃圾。
    runner._delete_admin_disposition(disp_path)
    return AdminDisposition(
        run_id=run_id,
        spec=disp.get("spec") or spec,
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
    except (OSError, ValueError):
        # ValueError 口径（code-review item b1501667b176）：UnicodeDecodeError
        # 属 ValueError 系——产物在多字节字符中间被截断时 read_text 直接抛出，
        # 本函数位于 run_administrator 收尾（任何 try 保护之外），不吞会让已
        # 完成的处置 run 在读取时崩溃、被消费侧折算成 dispatch-failure 升级。
        # 对齐 _salvage_evolution_out/_read_ocr_cursor 的既有防御口径。
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


def _unique_self_review_run_id(runner, date_str: str) -> str:
    """生成不冲突的 ``review-<date>`` run_id（code-review item 61ab4fea1b86）。

    固定 ``review-<date>`` 在同日重跑（手动补跑 + 周期触发）下撞名：新旧
    两轮共用 runs/review-<date>.jsonl 事件流与台账归属。对齐
    _unique_admin_run_id 的探测退避形态：候选的 run 事件流或在飞 out 文件
    任一已存在，即追加 ``-<n>`` 退避（n 从 1 起递增）。探测退避而非
    O_CREAT|O_EXCL 申领：out 文件由 agent 按 prompt 注入的路径写入且 run
    结束即清理（_delete_self_review_out），事件流由 _run_claude 追加落盘，
    抢先落申领占位文件会污染 jsonl 事件流并改变 out 文件生命周期。
    """
    base = f"review-{date_str}"
    candidate = base
    n = 0
    runs_dir = runner.project_root / ".fenix" / "runs"
    while True:
        if (
            (runs_dir / f"{candidate}.jsonl").exists()
            or (runner.project_root / ".fenix" / f"self_review_out-{candidate}.json").exists()
        ):
            n += 1
            candidate = f"{base}-{n}"
            continue
        return candidate


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
    - run_id 前缀 ``review-<date>``（同日重跑追加 ``-<n>`` 退避防撞名，
      见 _unique_self_review_run_id）：独立前缀，不占 spec 维度预算、
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
    并清理。失败（异常/超时/rc!=0，或产物硬门判定零产物——out 缺失/
    不可解析/summary 与四类清单全空，fail-closed）返回 success=False
    （调度器记告警、24h 内不重试）。

    Args:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1）。
        date_str: 自省归属执行日 YYYY-MM-DD（即 run_id 内嵌日期）。
        daily_summary: 框架聚合的近 24 小时数据摘要（五源），注入 prompt。
        todo_md: read_todo=true 时的既有 todo.md 全文；None 不注入。
        todo_entries: read_todo=true 时 ID 标注的近 3 日条目清单
            （闭环判定对象）；None 注入占位提示。
    """
    run_id = _unique_self_review_run_id(runner, date_str)
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
        _apply_provider_env(env_overrides, provider, model_override, runner)
        # 观测：run jsonl 补写 provider_marker（item faea95e2d494，五条维护
        # 车道观测口径一致；写失败不阻断，见助手 docstring）
        _write_lane_provider_marker(
            runner, run_id, "self-review", "self-review", assignment
        )
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
    # ── 产物硬门（code-review item 791f1caf55b2，对齐同族 fail-closed 先例）──
    # 同族车道均已补产物门（run_administrator 处置硬门 / _check_repo_code_
    # review_artifact / _check_code_fix_artifact），唯独本车道没有：_run_claude
    # 正常退出但 agent 从未写 out 文件时，_read_self_review_out 返回空 dict、
    # success 仍为 True，调度器（core/self_review.py）记「每日自省完成」并把
    # 空回顾追加进 todo.md，无任何失败告警与重试信号——与本文件多处记载的
    # 「run exit 0 但零产物空跑被当成功」事故同类。判据：产物缺失/不可解析
    # 或无任何有效内容（summary 与 waste/mistakes/improvements/resolved 全空）
    # → 折算失败，error 点名零产物（fail-closed）。
    if success and not (
        (data.get("summary") or "").strip()
        or data.get("waste")
        or data.get("mistakes")
        or data.get("improvements")
        or resolved
    ):
        success = False
        error = (
            f"自省零产物（fail-closed）: run 正常退出但 {out_path.name} 缺失、"
            "不可解析或无任何有效内容（summary/waste/mistakes/improvements/"
            "resolved 全空），判失败"
        )
        _log = getattr(runner, "logger", None)
        if _log is not None:
            _log.warning(
                "self-review",
                f"每日自省 {run_id} 产物硬门拦截: {error}",
                {"run_id": run_id, "date": date_str},
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
    except (OSError, ValueError):
        # ValueError 口径（code-review item b1501667b176）：UnicodeDecodeError
        # 属 ValueError 系，半写/截断的产物文件会让整轮自省在收尾读取时崩溃；
        # 对齐 _salvage_evolution_out/_read_ocr_cursor 的既有防御口径。
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


def _write_claim_placeholder(fd: int, content: str = "{}\n") -> None:
    """fdopen 写申领占位内容并接管 fdopen 自身的失败路径（item cbb57806fbfd）。

    ``os.fdopen`` 自身抛错（fd 非法/MemoryError 等）时裸 fd 未被包装也无人
    关闭（with 的 close 只在 fdopen 成功后才生效）——daemon 长生命周期内的
    描述符泄漏。对齐 routes 侧 _write_signal_exclusive 的显式接管形态
    （item 71d502440d3b，先例 regression_routes item 655c860e2e6e）：f 为
    None（fdopen 未成功）时兜底 os.close；成功后统一经 finally close
    （等价 with 语义）。三个 _unique_*_run_id 申领点共用。
    """
    f = None
    try:
        f = os.fdopen(fd, "w", encoding="utf-8")
        f.write(content)
    finally:
        if f is not None:
            f.close()
        else:
            try:
                os.close(fd)
            except OSError:
                pass


# token 归账 runs 数组的条数上限（code-review item f597c1e03461）：归账文件
# 每次追加都全量读-改-写，runs 无界增长使单次写放大随历史线性增长（累计
# O(n²) I/O），成本对账读取方也随之变慢。上限取 4000 条（保守值）：归账写方
# 合计约百条/日量级（code-review 周期审查 + 每 spec 收尾一条的 impl-ocr +
# self-review/evolution），4000 条 ≈ 月级滚动窗口，覆盖成本对账的常用口径，
# 同时把单文件体积控制在 MB 量级。超出丢最旧（append 序即时间序，各调用方
# entry 均带 timestamp/date），并在文件内留痕最近一次裁剪。
_TOKEN_RUNS_MAX_ENTRIES = 4000


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
                if len(runs) > _TOKEN_RUNS_MAX_ENTRIES:
                    # 条数上限熔断（item f597c1e03461）：丢最旧记录并在文件内
                    # 留痕最近一次裁剪（读取方可感知历史被截断，非静默丢弃）。
                    dropped = len(runs) - _TOKEN_RUNS_MAX_ENTRIES
                    runs = runs[-_TOKEN_RUNS_MAX_ENTRIES:]
                    data["runs_trimmed"] = {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "dropped": dropped,
                    }
                data["runs"] = runs
                content = json.dumps(data, ensure_ascii=False, indent=2)
                # 原子替换：进程唯一临时名 + fsync + os.replace
                fd, tmp_str = tempfile.mkstemp(
                    prefix=f".{tokens_json.name}.", suffix=".tmp",
                    dir=str(tokens_json.parent),
                )
                try:
                    # fdopen 失败路径显式接管（item cbb57806fbfd，形态对齐
                    # _write_claim_placeholder / routes 先例 71d502440d3b）：
                    # with 的 close 只在 fdopen 成功后才生效，fdopen 自身抛错
                    # 时裸 fd 无人关闭——f 为 None 时兜底 os.close。
                    f = None
                    try:
                        f = os.fdopen(fd, "w", encoding="utf-8")
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        if f is not None:
                            f.close()
                        else:
                            try:
                                os.close(fd)
                            except OSError:
                                pass
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
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
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


def _unique_evolution_run_id(runner) -> str:
    """生成不冲突的 ``evo-<epoch>`` run_id（code-review item c52b09b4d42d）。

    秒级时间戳在「手动触发 + 定时触发同秒到达（或快速连续两次调用）」下
    撞名：runs/evo-<run_id>.jsonl 事件流与 out-<run_id>.json 契约产物会互相
    覆盖。对齐 _unique_self_review_run_id 的探测退避形态：候选的 run 事件流
    或在飞 out 文件任一已存在，即追加 ``-<n>`` 退避（n 从 1 起递增）。探测
    退避而非 O_CREAT|O_EXCL 申领：out 文件由 agent 按 prompt 注入的路径写入
    且 run 结束即清理（_delete_evolution_out），抢先落申领占位文件会改变该
    文件生命周期并可能被 read_contract 误读为合法契约。
    """
    base = f"evo-{int(time.time())}"
    candidate = base
    n = 0
    runs_dir = runner.project_root / ".fenix" / "runs"
    while True:
        if (
            (runs_dir / f"{candidate}.jsonl").exists()
            or (
                runner.project_root / ".fenix" / "evolution" / f"out-{candidate}.json"
            ).exists()
        ):
            n += 1
            candidate = f"{base}-{n}"
            continue
        return candidate


def run_evolution(
    runner, ready_projects: list, pending_entries: list | None = None
) -> EvolutionResult:
    """唤起框架自进化分析 run（Administrator 通道语义，design D2 复用）。

    与 implementer/verifier 不同：自进化是运维角色，直接在 main 树
    （project_root）操作，**不创建 worktree**（与 run_self_review 同形态）。
    特性：
    - run_id 前缀 ``evo-<epoch>``（同秒重入追加 ``-<n>`` 退避防撞名，见
      _unique_evolution_run_id）：独立前缀，不占 spec 维度预算、
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
    items[] 含 verdict/analysis_md/spec），run 结束**先抢救再清理**
    （evo-add-evolution-product-salvage：run_ok=False 也先读产物，产物
    缺失或不可解析且 ``<out>.parts`` 有分片时按合并配方恢复；完整契约
    按成功落地并落 INFO，部分恢复按失败落地且不推进水位——水位由
    调用方按 success 决定）。
    产物缺失或解析失败返回 success=False 并带原因，MUST NOT 抛异常
    穿透到调用方。落地（ingest_item）由本方法执行，自动接受是
    5.3 检查点的职责（本方法不触碰配置开关）。

    Args:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1）。
        ready_projects: 就绪项目 [{name, path, todo_md}]（scan_ready_projects
            的返回，同一 run 拿到多份 todo.md）。
        pending_entries: 待分析条目（含 id），None 由调用方传入。
    """
    run_id = _unique_evolution_run_id(runner)
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
        _apply_provider_env(env_overrides, provider, model_override, runner)
        # 观测：run jsonl 补写 provider_marker（item faea95e2d494，五条维护
        # 车道观测口径一致；写失败不阻断，见助手 docstring）
        _write_lane_provider_marker(
            runner, run_id, "evolution", "evolution", assignment
        )
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
    # 收尾段重排为「先抢救再清理」（evo-add-evolution-product-salvage）：
    # 无论 run_ok 先做抢救（产物缺失或 JSON 不可解析且 .parts 有分片 →
    # 合并恢复）再 read_contract；恢复出完整契约（条目数与待分析条目一致
    # 或未知）而 CLI 非零退出时按成功落地并落 INFO；部分恢复（条目不足）
    # 按失败落地——success=False、缺失数入 error，MUST NOT 触发水位推进
    # （fenixd worker 仅在 success 时对全部 ready_projects
    # advance_watermark(snapshot_at)，部分成功推进会永久跳过未分析条目；
    # 已落地条目由 ingest_item 幂等去重由下轮检查点补齐）。确无产物可救
    # 才在 finally 清理，范围含 .parts 残片目录。
    degraded = None
    items_ingested = 0
    drafts = 0
    try:
        try:
            from core.evolution import ContractError, read_contract, ingest_item

            # 先抢救：_run_claude 非零退出/产物半写时按分片合并配方恢复
            salvaged = _salvage_evolution_out(out_path)

            contract = None
            try:
                contract = read_contract(out_path)
            except ContractError as e:
                # 失败归因分级（任务 1.2）：「产物文件未写出」与「产物
                # JSON 不可解析」可判别；CLI 自身异常原因附注保留归因。
                prev_error = error
                run_ok = False
                error = str(e)
                if prev_error and prev_error != str(e):
                    error = f"{error}（CLI 退出异常: {prev_error}）"
                contract = None

            if contract is not None:
                items = contract.get("items") or []
                expected = len(pending_entries) if pending_entries else None
                partial = expected is not None and len(items) < expected
                degraded = contract.get("degraded")
                for item in items:
                    try:
                        status = ingest_item(item, runner.project_root)
                    except Exception as e:
                        # 单条落地失败不使整轮失败（幂等去重保证下轮重试）
                        _log = getattr(runner, "logger", None)
                        if _log is not None:
                            _log.warning(
                                "self-evolution",
                                f"条目落地异常（跳过）: " f"{item.get('title')}: {e}",
                            )
                        continue
                    items_ingested += 1
                    if status == "pending":
                        drafts += 1
                if partial:
                    # 部分恢复按失败落地：缺失数入 error、不触发水位推进
                    # （见上方收尾段说明；已落地条目由下轮幂等去重补齐）。
                    run_ok = False
                    error = (
                        f"产物部分恢复: 仅 {len(items)}/{expected} 条，"
                        f"缺失 {expected - len(items)} 条"
                        f"（水位不推进，已落地条目由下轮幂等去重补齐）"
                    )
                elif not run_ok:
                    # CLI 非零退出但契约产物完整（直读或抢救合并恢复）。
                    # 空条目不翻转：无从证明恢复出完整契约，按失败落地。
                    if items:
                        run_ok = True
                        error = ""
                        _log = getattr(runner, "logger", None)
                        if _log is not None:
                            how = (
                                f"抢救合并恢复 {salvaged} 条分片"
                                if salvaged is not None
                                else "产物直读"
                            )
                            _log.info(
                                "self-evolution",
                                f"CLI 退出异常但契约产物完整（{how}），"
                                f"按成功落地",
                            )
                    else:
                        run_ok = False
                        error = "CLI 退出异常且契约产物无条目"
        except Exception as e:
            # 落地异常不应穿透（检查点统一捕获）；整轮视为失败带原因
            run_ok = False
            error = f"分析落地异常: {e}"
            contract = None
    finally:
        # 清理放外层 finally 且后移到「先抢救」之后（code-review item
        # b77dad6f5ea5；早前 f1ef92e5ca50 把 finally 从内层读写 try 上移，
        # 本轮 evo-add-evolution-product-salvage 再把删除动作从「无条件
        # 先删」改为「先抢救再清理」）：无论 run/import/读写成败都清理
        # 本 run 的产物文件，范围扩到 .parts 残片目录（止住已观测的残片
        # 目录垃圾）。_delete_evolution_out / _delete_evolution_parts_dir
        # 缺失即跳过，run 失败且从未写出时幂等安全。
        runner._delete_evolution_out(out_path)
        _delete_evolution_parts_dir(out_path)

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


def _delete_evolution_parts_dir(out_path: Path):
    """删除本 run 的 ``<out>.parts`` 分片残片目录（幂等安全）。

    分片目录是 agents/evolution.md 纯提示词契约的中间产物，正常收尾由
    agent 自行 rm -rf；抢救路径兜底清理（确无产物可救 / 已合并完成后）
    ，止住已观测的残片目录垃圾。
    """
    try:
        shutil.rmtree(Path(f"{out_path}.parts"), ignore_errors=True)
    except OSError:
        pass


def _salvage_evolution_out(out_path: Path) -> int | None:
    """产物缺失或 JSON 不可解析且 ``<out>.parts`` 分片非空时合并恢复。

    agents/evolution.md 的分片写入契约是纯提示词约定，框架零参与：CLI
    非零退出 / 覆盖写瞬间的截断半写窗口（增量合并按分片反复重写 out，
    恰在 out 已存在时）都可能留下「已写分片未合并」或「产物半写」现场
    （evo-1790079811 实证留有 3 个可解析分片）。分片为每文件单条目自
    包含 JSON，按 sorted(glob) 拼接 items 即既有合并配方，框架侧复刻
    无障碍（产物仅保留 items，run_id 从文件名复算，degraded 置 None
    ——read_contract 对三者均不做存在性强制）。

    Returns:
        恢复写回的分片条目数；无需/无法抢救（产物完整可解析、无分片、
        写回失败）时返回 None——调用方据 None 与数值区分「直读」与「抢救」。
    """
    try:
        part_files = sorted(Path(f"{out_path}.parts").glob("*.json"))
    except OSError:
        return None
    if not part_files:
        return None
    # 产物已存在且 JSON 完整可解析时不覆盖：契约字段级问题（缺字段/
    # 枚举非法）不属抢救范畴，交给 read_contract 的分级报错。
    try:
        json.loads(out_path.read_text(encoding="utf-8"))
        return None
    except (OSError, ValueError):
        pass
    items = []
    for p in part_files:
        try:
            item = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # 单片损坏跳过，不阻塞其余分片
        if isinstance(item, dict):
            items.append(item)
    # 与 agents/evolution.md 合并配方同形：out-<run_id>.json → run_id
    run_id = out_path.stem[len("out-"):] if out_path.stem.startswith("out-") else None
    payload = {"run_id": run_id, "degraded": None, "items": items}
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        return None
    return len(items)


def _accumulate_evolution_tokens(runner, run_id: str, usage_info: dict) -> None:
    """自进化 token 归账（沿用 self_review 的独立类目文件与结构）。

    design D2 二选一：追加到 ``.fenix/cost/self_review_tokens.json`` 的
    runs 数组（与 verify-progress tokens.json 同结构），agent_type 标注
    ``evolution`` 以便成本对账区分。写路径走 _append_token_run（flock +
    原子替换），与 self-review/code-review 共用，消除并发覆盖。
    """
    tokens_json = runner.project_root / ".fenix" / "cost" / "self_review_tokens.json"
    now = datetime.now(timezone.utc)
    # date 统一为日期语义（item f6ba9c4dccef）：此前写 run_id（evo-<epoch>），
    # 与 self-review 的 YYYY-MM-DD 同键不同义，按日聚合的成本视图会把本类目
    # 整体错组；run_id 另立字段承载。
    entry = {
        "agent_type": "evolution",
        "date": now.date().isoformat(),
        "run_id": run_id,
        "timestamp": now.isoformat(),
        **_token_usage_fields(usage_info),
    }
    _append_token_run(tokens_json, entry)


def _get_admin_model(runner) -> str:
    """Administrator 模型名：admin.agent_model > 默认网关 fallback 常量。"""
    admin_model = runner._get_config("admin.agent_model", None)
    if admin_model:
        return admin_model
    return DEFAULT_GATEWAY_MODEL


def _writeoff_coverage_guard(
    origin_files: set,
    covered_files: set,
    logger,
    run_id: str,
    *,
    empty_detail: str,
    locked_detail_tmpl: str,
    unlock_detail_tmpl: str,
) -> tuple[bool, str]:
    """全仓快照核销覆盖完整性守卫的公共判定（item a5262dd130c0）。

    重派 run 与普通 manual_full run 两分支除 origin_files/covered 的数据
    来源外判定结构逐行同构（空集锁死、issubset 解锁、解锁 info 日志），
    收敛于此防两分支单边演进造成核销行为分裂；来源组装与分支差异文案由
    调用方负责（try/except 宁锁勿白洗也留在调用侧，因其须覆盖来源组装
    本身）。返回 (locked, locked_detail)，解锁时 detail 为空串；锁定/
    解锁文案由调用方以 {cov}/{total} 占位模板提供，保证日志逐字不变。
    """
    if not origin_files:
        return True, empty_detail
    if not origin_files.issubset(covered_files):
        return True, locked_detail_tmpl.format(
            cov=len(origin_files & covered_files),
            total=len(origin_files),
        )
    if logger is not None:
        logger.info(
            "code-review",
            f"全仓快照核销解锁（run {run_id}）："
            + unlock_detail_tmpl.format(total=len(origin_files)),
        )
    return False, ""


# ── 周期性代码审查 run（add-code-review-agent-and-quality-tab）──────


def run_code_review(
    runner,
    manifest: list,
    review_kind: str,
    window_start: datetime | None = None,
    scope: str = "window",
    redispatch_of: str | None = None,
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
    - 超时走 agents.run_timeout_seconds 全局默认（_run_claude 内生效）；
    - 429 打死 run 的自动重派（add-code-review-concurrency-and-429-resilience
      D4）：终态归因为 429 限流时经 ``_ratelimit_redispatch_on_terminal``
      登记 ``ratelimit_redispatch`` 意图（provider 限流冷却 + run jsonl 标注），
      意图随结果信封上交消费侧（admin_monitor._worker）延迟重投递；重派时
      消费侧以原 manifest 复调本函数（``redispatch_of`` 标注原 run），
      幂等保障既有：聚合读侧按 file 去重 + 提示词「不重审」纪律。

    Args:
        runner: AgentRunner 实例（门面依赖注入，D2b 规则 1）。
        manifest: 待审文件清单（相对路径列表，框架侧先行算出）。
        review_kind: scheduled / manual_full / manual_window。
        window_start: 审查窗口起点（scheduled/manual_window 注入；
            manual_full 为 None=全仓）。
        scope: full / window（写进 manifest 供审计）。
        redispatch_of: 非 None 表示本 run 是 429 限流重派（值为原 run_id），
            manifest JSON 与 run jsonl 均标注重派缘由（取证可见）。
    """
    run_id = runner._unique_code_review_run_id()
    mpath = runner.project_root / ".fenix" / "code-review" / f"manifest-{run_id}.json"
    opath = runner.project_root / ".fenix" / "code-review" / f"out-{run_id}.jsonl"
    # 申领占位收尾清理（对齐 run_regression item e6a103d93b91 的 finally 形态）：
    # _unique_code_review_run_id 以 O_CREAT|O_EXCL 先落 ``{}`` 空占位，本 run
    # 真正进入执行链（_run_claude）前的任何早退/异常路径（manifest 落盘失败、
    # _build_prompt 失败、模型链 provider 配置缺键 KeyError 等原不在任何 try
    # 保护内）都必须清掉占位后再上抛/折算失败信封，否则空占位永久残留
    # .fenix/code-review/ 累积垃圾。组装完成置位后 finally 不再触碰（占位已被
    # 完整 manifest 覆盖，成为本 run 的合法审计载体）；missing_ok 容忍本就未
    # 落盘的失败路径。
    _manifest_settled = False
    try:
        try:
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "scope": scope,
                        "review_kind": review_kind,
                        "window_start": window_start.isoformat() if window_start else None,
                        # 429 限流重派标注（add-code-review-concurrency-and-429-
                        # resilience D4）：非 None 时本 run 是原 run 的重派，取证可见
                        "redispatch_of": redispatch_of,
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

        # 重派缘由运行留痕（task 5.2「运行记录可见重派缘由字段」）：重派 run 启动
        # 即向自身 jsonl 标注 redispatch_of（写失败仅丢留痕不阻断）。
        if redispatch_of:
            try:
                from core.agent_runner.run_files import append_run_line as _arl

                _arl(
                    runner.project_root / ".fenix" / "runs" / f"{run_id}.jsonl",
                    {
                        "type": "ratelimit_redispatch",
                        "run_id": run_id,
                        "spec": "code-review",
                        "redispatch_of": redispatch_of,
                        "reason": "429 ratelimit",
                    },
                )
            except OSError:
                pass

        review_window = (
            f"[{window_start.isoformat()}, now]" if window_start else "（全仓，manual_full）"
        )
        # 全仓审查并发（add-code-review-concurrency-and-429-resilience）：双通道
        # 注入①提示词侧子代理扇出上限（{repo_concurrency}），②scan 命令
        # --concurrency 由提示词模板同键承载。
        from core.config import ConfigLoader as _CLRepoConc

        prompt = runner._build_prompt(
            run_id,
            "code-review",
            detail={
                "manifest": [str(f) for f in manifest],
                "review_window": review_window,
                "out_path": str(opath),
                "repo_concurrency": _CLRepoConc.get_repo_code_review_concurrency(
                    getattr(runner, "config", {}) or {}
                ),
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
        provider_name = None
        if assignment:
            provider, model_override = assignment[0]
            provider_name = provider.get("name")
            _apply_provider_env(env_overrides, provider, model_override, runner)
            # 观测：run jsonl 补写 provider_marker（item faea95e2d494，五条
            # 维护车道观测口径一致；写失败不阻断，见助手 docstring）
            _write_lane_provider_marker(
                runner, run_id, "code-review", "code-review", assignment
            )
        else:
            model_override = runner._get_admin_model()
        _manifest_settled = True
    finally:
        if not _manifest_settled:
            try:
                mpath.unlink(missing_ok=True)
            except OSError:
                pass  # 清理失败不吞组装期原始异常（对齐 run_regression/run_code_fix 降级语义）

    claude_error = ""  # CLI 原始错误文本（429 终态归因以它为准，见 catch 处）
    # evo-add-code-review-ratelimit-resume 1.2：result 事件富归因（api_error_status
    # /result 文本，runner 非零退出分支挂异常）随原始错误留存——except 块结束
    # 异常绑定即删，后续意图登记只能读这里存的值。
    claude_api_error_status = None
    claude_result_text = ""
    try:
        output, turns, _session_id, usage_info = runner._run_claude(
            prompt,
            runner.project_root,
            run_id,
            model_override,
            env_overrides,
            # 轮次不设限（用户 2026-09-23）：全库审查 manifest 大（240 文件级）、
            # 子代理编排轮次消耗快，800+扩展(2×25%)=1200 实测不够用且死前
            # inserted=0（09-23 manual_full 事故）。_run_claude 对 None 跳过
            # 强制块（`if max_turns and ...`），失控兜底由超时+liveness 承担。
            max_turns=None,
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
        # 429 终态归因原文本单独留存（后续产物硬门/抢救可能改写 error 文案，
        # 限流分类 MUST 以 CLI 原始错误为准，add-code-review-concurrency-and-
        # 429-resilience D4）
        claude_error = str(e)
        # evo-add-code-review-ratelimit-resume 1.2：result 事件富归因一并留存
        # （文本分类未命中时意图登记以此回退判 429，对齐 exc.api_timeout 先例）。
        claude_api_error_status = getattr(e, "api_error_status", None)
        claude_result_text = getattr(e, "result_text", "")

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
        gate_err = _check_repo_code_review_artifact(manifest, runner.project_root, run_id)
        if gate_err is not None:
            run_ok = False
            error = gate_err
            _log = getattr(runner, "logger", None)
            if _log is not None:
                _log.error(
                    "code-review",
                    f"产物硬门拦截: run={run_id} manifest={len(manifest)} — {gate_err}",
                )

    # 读取增量产物并落账（聚合口径：分片 + 主产物，add-code-review-sharded-out
    # 2.1；产物全缺失/解析失败 → success=False 带原因）
    inserted = updated = resolved = 0
    shards = 0
    if run_ok:
        try:
            from core.code_review import shard_paths as _cr_shard_paths

            shards = len(_cr_shard_paths(runner.project_root, run_id))
            findings = runner._read_code_review_out(runner.project_root, run_id)
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
                #
                # ── 覆盖完整性守卫（evo-add-code-review-ratelimit-resume 3.3）──
                # 剃余重派 run（redispatch_of 非空）以**剩余** manifest 跑，若
                # 原样按 manual_full 收尾且 findings 非空，未覆盖文件的存量条目
                # 会被误置 resolved（部分覆盖白洗——与下方 :1288 抢救红线同族
                # 事故）；普通 manual_full run 同理——存在性产物门只查「任一
                # 来源有一行有效行」，agent 静默只审 manifest 子集（自行切批
                # 少审漏审）时同样部分覆盖白洗。解锁门：「本轮累计覆盖（原 run
                # 及其重派链产物 file 字段并集）⊇ 完整原 manifest」才核销，
                # 否则维持抢救红线。守卫唯一实现点在本收尾段（重派/普通两
                # 分支同语义；design 核销门挂点二选一：此处按覆盖判定，消费
                # 侧 admin_monitor 不重复核销解锁）。原 manifest 缺失/损坏或
                # 守卫异常一律按未覆盖处理（宁锁勿白洗）。
                writeoff_locked = False
                locked_detail = ""
                if redispatch_of:
                    try:
                        from core.code_review import (
                            cumulative_covered_files as _cr_cum_covered,
                            read_manifest_files as _cr_manifest_files,
                        )

                        origin_files = set(
                            _cr_manifest_files(runner.project_root, redispatch_of))
                        covered = _cr_cum_covered(runner.project_root, redispatch_of)
                        writeoff_locked, locked_detail = _writeoff_coverage_guard(
                            origin_files, covered,
                            getattr(runner, "logger", None), run_id,
                            empty_detail="原 manifest 缺失/损坏，完整性不可判",
                            locked_detail_tmpl=(
                                f"累计覆盖 {{cov}}/{{total}} 文件"
                                f"（redispatch_of={redispatch_of}），"
                                f"本轮 manifest {len(manifest)} 文件"),
                            unlock_detail_tmpl=(
                                f"累计覆盖完整（{{total}}/{{total}} 文件，"
                                f"redispatch_of={redispatch_of}）"),
                        )
                    except Exception as e:  # noqa: BLE001 — 判定失败按未覆盖处理
                        writeoff_locked = True
                        locked_detail = f"覆盖完整性判定异常（宁锁勿白洗）: {e}"
                else:
                    # 普通 manual_full run（非重派）同语义守卫（item 0372755b5bb3）：
                    # 存在性产物门只查「任一来源有一行有效行」，agent 静默只审
                    # manifest 子集（自行切批少审漏审，09-19 事故的 agent 不听话
                    # 形态）时 run_ok=True 且 observed 非空，未审文件的存量条目
                    # 同样会被白洗。解锁门同口径：本轮累计覆盖（本 run 产物 file
                    # 字段并集，链长 1 时即 cumulative_covered_files 同口径）
                    # ⊇ 本轮 manifest 才核销；manifest 以派发参数为准（同内容
                    # 已落盘 manifest-<run_id>.json）。宁锁勿白洗。
                    try:
                        from core.code_review import (
                            cumulative_covered_files as _cr_cum_covered,
                        )

                        origin_files = {str(f) for f in manifest if str(f)}
                        covered = _cr_cum_covered(runner.project_root, run_id)
                        writeoff_locked, locked_detail = _writeoff_coverage_guard(
                            origin_files, covered,
                            getattr(runner, "logger", None), run_id,
                            empty_detail="manifest 清单为空，完整性不可判",
                            locked_detail_tmpl=(
                                f"本轮覆盖 {{cov}}/{{total}} 文件，manifest "
                                f"{len(manifest)} 文件"),
                            unlock_detail_tmpl="覆盖完整（{total}/{total} 文件）",
                        )
                    except Exception as e:  # noqa: BLE001 — 判定失败按未覆盖处理
                        writeoff_locked = True
                        locked_detail = f"覆盖完整性判定异常（宁锁勿白洗）: {e}"
                if writeoff_locked:
                    _log = getattr(runner, "logger", None)
                    if _log is not None:
                        _log.warning(
                            "code-review",
                            f"全仓快照核销锁定（run {run_id}）：{locked_detail}"
                            "——维持抢救红线，不核销（等剩余文件重派补齐后解锁）",
                        )
                elif findings:
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
    else:
        # ── error 收场抢救（2026-09-24 429 事故）────────────────────────────
        # run 中途死亡（网关 429 / 超时 / 强杀）≠ 零产出：分片直写模式下死前
        # 已落盘的分片与主产物行是真实审查结论，run_ok 门曾把整条消费链跳过
        # （173 条发现滞留分片零落账）。此处仅抢救数据：聚合读 → upsert。
        # 两条红线：MUST NOT 触发 manual_full 全仓快照核销（部分覆盖下会把
        # 未审文件的存量条目误置 resolved，与空集核销白洗同族）；MUST NOT
        # 触发 code-fix 检查点（残跑产物不激活修复链，与下方 run_ok 门一致）。
        try:
            from core.code_review import shard_paths as _cr_shard_paths

            shards = len(_cr_shard_paths(runner.project_root, run_id))
            findings = runner._read_code_review_out(runner.project_root, run_id)
            if findings:
                stats = upsert_findings(
                    runner.project_root,
                    findings,
                    review_id=run_id,
                    review_kind=review_kind,
                )
                inserted = stats.get("inserted", 0)
                updated = stats.get("updated", 0)
                if inserted or updated:
                    error = (
                        f"{error}；error 收场抢救落账 inserted={inserted} "
                        f"updated={updated}（部分覆盖，未做全仓快照核销）"
                    )
                    _log = getattr(runner, "logger", None)
                    if _log is not None:
                        _log.warning(
                            "code-review",
                            f"error 收场抢救落账: run={run_id} shards={shards} "
                            f"inserted={inserted} updated={updated}",
                        )
        except Exception as e:  # noqa: BLE001 — 抢救失败不改变 run 原失败判定
            _log = getattr(runner, "logger", None)
            if _log is not None:
                _log.warning("code-review", f"error 收场抢救失败（run {run_id}）: {e}")

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

    # ── 429 打死 run 的自动重派：runner 侧终态归因与意图登记（D4，task 5.1）──
    # 仅以 CLI 原始错误分类（产物硬门/抢救文案不参与）；意图经结果信封上交
    # 消费侧（admin_monitor._worker），冷却到期后延迟重投递。
    ratelimit_intent = None
    if not run_ok and claude_error:
        _ratelimit = getattr(runner, "_ratelimit_redispatch_on_terminal", None)
        if _ratelimit is not None:
            try:
                ratelimit_intent = _ratelimit(
                    run_id=run_id,
                    error=claude_error,
                    provider_name=provider_name,
                    spec_name="code-review",
                    # evo-add-code-review-ratelimit-resume 1.2：富归因透传——
                    # 文本分类恒 False（stderr 降噪后只剩 Exit code: 1）时，
                    # 登记侧以 result 事件回退判 429，意图照常登记并标注 run。
                    api_error_status=claude_api_error_status,
                    result_text=claude_result_text,
                )
            except Exception as e:  # noqa: BLE001 — 意图登记失败不改变失败终态
                _log = getattr(runner, "logger", None)
                if _log is not None:
                    _log.warning(
                        "code-review",
                        f"ratelimit_redispatch 意图登记失败（run {run_id}）: {e}",
                    )

    result = CodeReviewResult(
        run_id=run_id,
        success=run_ok,
        inserted=inserted,
        updated=updated,
        resolved=resolved,
        error=error,
        output=output,
        shards=shards,
    )
    # 意图随结果信封上交（result_gate.CodeReviewResult.ratelimit_redispatch，
    # 缺省 None——非 429 失败路径恒为 None，消费侧零感知）
    result.ratelimit_redispatch = ratelimit_intent
    return result


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
    # n=0 起始、冲突分支先自增再拼候选 → 首个退避候选为 base-1（与
    # docstring「n 从 1 起递增」及 _unique_code_fix_run_id 同口径对齐）
    n = 0
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
        _write_claim_placeholder(fd)
        return candidate


def _read_code_review_out(runner, project_root, run_id: str) -> list:
    """读取审查增量产物（聚合口径：分片 + 主产物，add-code-review-sharded-out 2.1）。

    迭代顺序与去重统一经 ``code_review.read_review_out_rows``：分片
    （``shard_paths`` N 升序）→ 主产物 ``out-<run_id>.jsonl``，按 ``file``
    去重保留先见行；空行/不可解析行/非 dict 行过滤。单分片读取失败跳过
    该分片（经 logger WARNING 注明，不中断整轮——收尾 ingest 不得因单个
    分片损坏丢掉其余分片数据）；文件缺失返回空列表（run 失败路径已由
    success=False 兜底）。

    每行为一个文件的审查结果 JSON（file/findings[]），展开为逐 finding 的
    归一 dict（file 取文件行 + finding 层可覆盖）。

    ``runner`` 首参为门面注册表契约（self 首参模块函数）预留：本函数体
    只读 project_root/run_id，但经 ``runner._read_code_review_out(...)`` 转发时
    partial 会注入 runner 首参（code-review item 0c9577c146d9）。
    """
    from core.code_review import read_review_out_rows

    _log = getattr(runner, "logger", None)

    def _on_error(src: Path, exc: Exception) -> None:
        if _log is not None:
            _log.warning(
                "code-review",
                f"审查产物来源读取失败跳过（run {run_id}）: {src.name} ({exc})",
            )

    out: list = []
    for rec in read_review_out_rows(project_root, run_id, on_error=_on_error):
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


def agent_process_cpu_seconds(proc) -> float | None:
    """run 子进程进程树的累计 CPU 时间（秒），不可解析返回 None。

    decouple-codefix-review-lanes 看门狗判据 2（design D2）：网络僵死的 run
    表现为「进程活着但 CPU 停止增长」（09-24 事故：2h20m 仅 49s CPU），单
    mtime 判据会被这种形态欺骗，故看门狗以 mtime + CPU 双判据同时无进展
    才判定停滞。读 /proc/<pid>/stat 的 utime+stime（含其后代进程树——审查
    run 的 scan 子进程经 execvp 后以 node/ocr 形态挂在 CLI 子进程下，只看
    顶层 pid 会漏掉真实负载）；任一环节不可解析（进程已退出 / 非 Linux /
    权限不足）返回 None，调用方按 fail-open 不触发（看门狗宁可漏杀不可误杀，
    且无进程句柄时 cancel_run 也无从终止）。

    ``proc`` 为 subprocess.Popen 或等价句柄（只需 .pid 属性）；子进程遍历用
    内核提供的 /proc/<pid>/task/<tid>/children（比全表扫 /proc 匹配 ppid 便宜
    且无「孙进程在遍历间隙被收养」的误判面）。
    """
    pid = getattr(proc, "pid", None)
    if not pid or pid <= 0:
        return None
    ticks = 0.0
    read_any = False
    seen: set[int] = set()
    queue = [int(pid)]
    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):
        clk_tck = 100.0
    if not clk_tck:
        clk_tck = 100.0
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen.add(cur)
        try:
            with open(f"/proc/{cur}/stat", "rb") as f:
                stat = f.read()
        except OSError:
            continue
        # stat 的 comm 字段可含空格/括号，以最后一个 ')' 切开取其后字段
        rparen = stat.rfind(b")")
        if rparen < 0:
            continue
        fields = stat[rparen + 2 :].split()
        # fields[11]=utime fields[12]=stime（14th/15th 列，state 从 fields[0] 起）
        if len(fields) < 13:
            continue
        try:
            ticks += int(fields[11]) + int(fields[12])
        except ValueError:
            continue
        read_any = True
        # 逐线程 children 汇总（同 pid 多线程时 children 记录在各 task 下）
        try:
            for tid_dir in os.scandir(f"/proc/{cur}/task"):
                try:
                    with open(f"/proc/{cur}/task/{tid_dir.name}/children", "rb") as f:
                        queue.extend(int(x) for x in f.read().split())
                except (OSError, ValueError):
                    continue
        except OSError:
            continue
    if not read_any:
        # 顶层 pid 就读不到（已退出/权限）→ 判据不可用，调用方 fail-open
        return None
    return ticks / clk_tck


def _accumulate_code_review_tokens(runner, run_id: str, usage_info: dict) -> None:
    """code-review token 归账到 cost-observability 独立类目（task 3.6）。

    追加到 ``.fenix/cost/code_review_tokens.json`` 的 runs 数组（与
    self_review_tokens.json 同结构），供成本对账口径一致；不写 STATE
    （审查 run 无 spec 维度）。写路径走 _append_token_run（flock + 原子替换）。
    """
    tokens_json = runner.project_root / ".fenix" / "cost" / "code_review_tokens.json"
    now = datetime.now(timezone.utc)
    # date 统一为日期语义（item f6ba9c4dccef）：此前写 run_id
    # （code-review-<epoch>），run_id 另立字段承载（对齐 self-review 的
    # YYYY-MM-DD 口径，按日聚合不再错组）。
    entry = {
        "agent_type": "code-review",
        "date": now.date().isoformat(),
        "run_id": run_id,
        "timestamp": now.isoformat(),
        **_token_usage_fields(usage_info),
    }
    _append_token_run(tokens_json, entry)


# ── 全量回归执行（add-test-regression-tab，task 3.1）────────────────────


def _unique_regression_run_id(runner) -> str:
    """生成并**原子申领**不冲突的 ``regression-<epoch>`` run_id（task 3.1）。

    秒级时间戳在「手动触发 + 同秒周期触发」下可能撞名（对齐
    _unique_code_review_run_id 的退避形态）。信号文件/日志按 run 实例留痕。

    申领即创建（对齐 _unique_code_review_run_id / item e61828a54fda）：
    以 ``O_CREAT|O_EXCL`` 抢占 ``run-<candidate>.json``（原子），输者退避
    下一候选；占位内容为合法空 JSON ``{}``（无读者按 run 文件聚合，占位
    不破坏任何消费方）。占位仅作申领凭据，不回填真实 run 记录——由
    run_regression 收尾 finally 清理（item e6a103d93b91），不留空占位。
    """
    base = f"regression-{int(time.time())}"
    candidate = base
    # n=0 起始、冲突分支先自增再拼候选 → 首个退避候选为 base-1
    # （对齐 _unique_code_review_run_id / _unique_code_fix_run_id 同族口径）
    n = 0
    reg_dir = runner.project_root / ".fenix" / "regression"
    while True:
        if (reg_dir / f"run-{candidate}.json").exists():
            n += 1
            candidate = f"{base}-{n}"
            continue
        try:
            reg_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 目录建不出（权限等）：退回探测语义，落盘失败由回归执行路径统一报错
            return candidate
        try:
            fd = os.open(
                reg_dir / f"run-{candidate}.json",
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
        _write_claim_placeholder(fd)
        return candidate


# pytest 中需要独立参数值（空格分隔形态）的选项（add-codefix-targeted-retry 2.1）：
# 收集目标判定时这些选项的**值**不是收集目标。``--opt=value`` 等号形态天然是
# 单 token 且以 ``-`` 开头，不进此判定。覆盖常见声明形态；未收录选项的空格
# 形态值可能被误判为收集目标——项目契约（verify.yaml regression.cmd）形态
# 稳定（``python3 -m pytest tests/ -q --junit-xml=...``），超出清单时映射侧
# 以 fail-closed 兜底（宁回全量不错替换）。
_PYTEST_VALUE_OPTIONS = frozenset({
    "-c", "--config", "-o", "--override-ini", "-k", "-m", "-p", "-r", "-W",
    "--junit-xml", "--junit-prefix", "--result-log", "--basetemp",
    "--rootdir", "--durations", "--maxfail", "--html", "--css", "--tb",
})

# shell 控制操作符：命令 token 化后含任一即视为复杂 shell 形态，
# fail-closed 不做子集替换（token 级替换在含管道/重定向/命令串的命令上
# 语义不可靠）。
_SHELL_OPERATORS = frozenset({"|", "||", "&&", ";", ">", "<", ">>", "&", "$(", "`"})


def _is_pytest_invocation(token: str) -> bool:
    """token 是否为 pytest 可执行名（含绝对/相对路径形态）。"""
    base = token.rsplit("/", 1)[-1]
    return base in ("pytest", "py.test")


def _apply_pytest_subset(cmd, subset_nodeids):
    """把 pytest 命令的既有收集位置参数替换为失败用例 nodeids（2.1，D2）。

    两态命令均支持（str=shell 经 shlex token 化、list=argv 原样）。替换规则：

    - 命令 MUST 为 pytest 形态（token 序列含 pytest/py.test 可执行名，
      ``python -m pytest`` 形态天然命中）——否则返回 None（回退全量）。
    - 收集目标 = pytest 之后、非旗标、且不紧跟在带值选项后的 token；
      含 shell 控制操作符、或不存在任何收集目标 → 返回 None（fail-closed）。
    - 替换：首个收集目标位置放全部 nodeids，其余收集目标删除（保持
      「收集目标并集」语义下的精确子集）；旗标（``-q``/``--junit-xml`` 等）
      逐字保留。
    - 重组形态与输入一致：shell 命令经 shlex.quote 重组，argv 原样列表。

    返回新命令（同形态）；不可替换时返回 None（调用方回退全量）。
    """
    if not subset_nodeids:
        return None
    is_shell = isinstance(cmd, str)
    try:
        tokens = shlex.split(cmd) if is_shell else [str(t) for t in cmd]
    except ValueError:  # noqa: PERF203 — shell 引号非法：不可安全 token 化
        return None

    pytest_idx = None
    for i, t in enumerate(tokens):
        if _is_pytest_invocation(t):
            pytest_idx = i
            break
    if pytest_idx is None:
        return None
    if any(t in _SHELL_OPERATORS for t in tokens):
        return None
    # 命令替换形态（item cccf30d0fcbb）：shlex 不解析命令替换，'$('/反引号
    # 会附着进相邻 token（``pytest $(ls tests/)`` → ['pytest', '$(ls',
    # 'tests/)']，反引号形态同理），上面的 token 精确匹配拦不住；任一 token
    # 含替换记号即按复杂 shell 形态 fail-closed（回退全量）。
    if any("$(" in t or "`" in t for t in tokens):
        return None

    target_indexes = []
    pending_value_opt = None
    for i in range(pytest_idx + 1, len(tokens)):
        t = tokens[i]
        if t.startswith("-") and len(t) > 1:
            pending_value_opt = t if t in _PYTEST_VALUE_OPTIONS else None
            continue
        if pending_value_opt is not None:
            # 带值选项的值（如 ``--junit-xml path`` 的 path）不是收集目标
            pending_value_opt = None
            continue
        target_indexes.append(i)

    if not target_indexes:
        # 无既有收集位置参数可「取代」——无法以取代语义精确注入
        #（MUST NOT 尾部追加：并集语义会退化全量），回退全量。
        return None

    first = target_indexes[0]
    shift = len(subset_nodeids) - 1
    out = tokens[:first] + [str(n) for n in subset_nodeids] + tokens[first + 1:]
    for i in reversed(target_indexes[1:]):
        # 插入 nodeids 后，原索引 i 的元素右移 shift 位
        del out[i + shift]
    if is_shell:
        return " ".join(shlex.quote(t) for t in out)
    return out


def run_regression(
    runner, spec, reason: str = "manual", project_root=None, lock_root=None,
    subset_nodeids=None,
) -> RegressionResult:
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
        subset_nodeids: 失败用例子集（add-codefix-targeted-retry 2.1，可选
            nodeid 序列）。仅当项目命令为 pytest 形态且子集非空时生效——以
            失败 nodeids **取代**命令中的既有收集位置参数（如 ``tests/``
            目录），保留 ``-q``/``--junit-xml`` 等非收集旗标；MUST NOT 尾部
            追加（pytest 多位置参数为收集目标并集，追加会静默退化全量）。
            子集为空或命令非 pytest 形态（或无法安全改写）时忽略子集跑
            全量（fail-closed 到现状语义）。锁根/执行根透传语义逐字不变；
            子集替换只发生在门面层（D2：不扩散到 core.regression 原语）。

    返回:
        RegressionResult(status=快照状态, snapshot=完整快照)。
    """
    from core.regression import run_and_write_regression

    run_id = _unique_regression_run_id(runner)
    log = getattr(runner, "logger", None)
    exec_root = project_root if project_root is not None else runner.project_root

    # 申领占位收尾清理（item e6a103d93b91）：_unique_regression_run_id 以
    # O_CREAT|O_EXCL 抢占 run-<run_id>.json 仅作原子申领，`{}` 占位此后
    # 无人回填也无人读（执行链 run_and_write_regression 只写 last-run.json
    # /state.json/.running）——不清理则每次执行永久泄漏一个空占位。此处按
    # 申领处同构拼路径（reg_dir 取 runner.project_root，与 project_root
    # 参数无关），成功/失败/skipped/异常各路径 finally 统一清理；missing_ok
    # 容忍 OSError 回退路径本就未落盘的情况。
    claim_placeholder = (
        runner.project_root / ".fenix" / "regression" / f"run-{run_id}.json"
    )
    try:
        subset = list(subset_nodeids) if subset_nodeids else []
        if subset:
            subset_cmd = _apply_pytest_subset(spec.cmd, subset)
            if subset_cmd is not None:
                spec = dataclasses.replace(spec, cmd=subset_cmd)
                if log is not None:
                    log.info(
                        "regression",
                        f"code-fix 定向子集回归（{len(subset)} 例，取代既有收集目标）",
                    )
            else:
                # 非 pytest 形态 / 无法安全改写 → 忽略子集跑全量（fail-closed）
                if log is not None:
                    log.warning(
                        "regression",
                        "定向子集不可用（非 pytest 形态或无法安全改写收集目标），回退全量回归",
                    )

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

        # 语义收窄（code-review b955b21cf40e）：success 仅当回归通过
        # （status == "passed"）为真——failed/timeout 是执行有结果而非回归
        # 通过，旧实现把二者计入 ok 使信封 success=True 与字段字面义相反，
        # 新消费方按 success 判「回归通过」会把失败回归当成功。计数/终态取
        # snapshot 与 status，不依赖 success。
        ok = snapshot.get("status") == "passed"
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
    finally:
        try:
            claim_placeholder.unlink(missing_ok=True)
        except OSError:
            pass  # 清理失败不吞回归结果（对齐 _delete_admin_disposition 等降级语义）


# ── 自动修复执行（add-code-review-auto-fix，task 6.1-6.3）────────────────


class CodeFixResult:
    """code-fix run 的结果信封（run_code_fix 返回，add-code-review-auto-fix）。

    与 CodeReviewResult / RegressionResult 同形态的维护型 run 结果：
    - ``fixed`` / ``skipped``: out 产物行中 status=fixed / skipped 的计数
      （skipped 条目 MUST 保持 open——由编排器在合回成功后只核销 fixed）；
    - ``error``: success=False 时的失败原因（含产物硬门拦截文案）；
    - 结构化失败签名（evo-code-fix-api-timeout-salvage 1.2）：``api_timeout``
      （单轮 API 请求超时终局，判别单源在 runner 层挂异常标记）、
      ``exit_code`` / ``stderr_summary``（原始退出码与 stderr 尾行摘要）——
      失败现场可判别、可追溯，不再把签名压扁为异常字符串。
    """

    def __init__(
        self,
        run_id: str = "",
        success: bool = True,
        fixed: int = 0,
        skipped: int = 0,
        error: str = "",
        output: str = "",
        api_timeout: bool = False,
        exit_code=None,
        stderr_summary: str = "",
    ):
        self.run_id = run_id
        self.success = success
        self.fixed = fixed
        self.skipped = skipped
        self.error = error
        self.output = output
        self.api_timeout = api_timeout
        self.exit_code = exit_code
        self.stderr_summary = stderr_summary


def _stderr_tail_summary(stderr_lines, max_lines: int = 3, max_chars: int = 200) -> str:
    """stderr 尾行摘要（evo-code-fix-api-timeout-salvage 1.2，追溯用非判别用）。

    取末尾至多 ``max_lines`` 条非空行、总长截断 ``max_chars``——判别一律读
    ``api_timeout`` 布尔标记（runner 层单源），摘要只进日志/失败记录。
    """
    lines = [str(ln).strip() for ln in (stderr_lines or []) if str(ln).strip()]
    if not lines:
        return ""
    return " | ".join(lines[-max_lines:])[:max_chars]


def _unique_code_fix_run_id(runner, exclude=()) -> str:
    """生成并**原子申领**不冲突的 ``code-fix-<epoch>`` run_id（task 6.2）。

    撞名判据（对齐 _unique_code_review_run_id 的退避形态）：runner 侧在飞
    run_id + 主树 ``.fenix/code-review/fix-out-<candidate>.jsonl`` 残留
    （run 的产物文件落在 worktree，此处以主树残留近似兜底并发窗口）+
    ``exclude`` 额外禁用集（编排器预生成重试轮 run_id 时传入本批已 issued
    的 run_id——重试产物落**同一 worktree**，主树残留判据覆盖不到，同秒
    撞名会让重试轮复用首轮 out 文件、破坏「重试独立文件并集」口径，
    add-code-fix-item-level-progress 2.2）。
    目标已占时追加 ``-<n>`` 退避（n 从 1 起递增）。

    申领即创建（对齐 _unique_code_review_run_id / item e61828a54fda）：
    旧实现只对在飞快照、exclude 集与主树残留做「检查-然后-返回」探测，
    check-then-act 窗口内两个同秒触发的独立入口会同时通过探测、拿到同一
    candidate。现在飞集/exclude 预检通过后，以 ``O_CREAT|O_EXCL`` 抢占主树
    ``fix-out-<candidate>.jsonl``（原子），输者退避下一候选；占位内容为
    合法空 JSON ``{}``（主树 fix-out 无读者按文件聚合，占位不破坏任何消费
    方；真实产物落 worktree 同名路径，不会与占位同文件）。占位仅作申领
    凭据，不回填真实产物——由 run_code_fix 收尾 finally 清理（对齐
    run_regression / item e6a103d93b91），不留空占位。
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
        try:
            cr_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 目录建不出（权限等）：退回既有探测语义，落盘失败由
            # run_code_fix 的 out 目录创建路径统一报错
            return candidate
        try:
            fd = os.open(
                cr_dir / f"fix-out-{candidate}.jsonl",
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
        _write_claim_placeholder(fd)
        return candidate


def _check_code_fix_artifact(items, out_path: Path) -> str | None:
    """code-fix run 的产物硬门（task 6.2，对齐 _check_repo_code_review_artifact）。

    判据（fail-closed）：
    - ``items`` 为空 → None（调用方前置跳过场景，不重复判定）；
    - ``out_path`` 不存在，或读取抛 OSError，或存在但**零有效行** → 返回失败原因。

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
    try:
        text = out_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        # 判存与读取之间权限收紧等读取异常不得穿透 run_code_fix 的
        # 「异常折算为失败信封」收尾，按硬门失败语义折算为失败原因（fail-closed）。
        return (
            f"code-fix 产物读取失败: 注入清单 {len(items)} 条但 {out_path} "
            f"读取异常（{e}），判失败（fail-closed）"
        )
    for line in text.splitlines():
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

    # 申领占位收尾清理（item e6a103d93b91，对齐 run_regression 同构形态）：
    # _unique_code_fix_run_id 以 O_CREAT|O_EXCL 抢占主树 fix-out-<run_id>.jsonl
    # 仅作原子申领，`{}` 占位此后无人回填也无人读（真实产物落 worktree 同名
    # 路径，主树占位无消费方）——不清理则每次执行永久泄漏一个空占位。此处按
    # 申领处同构拼路径（cr_dir 取 runner.project_root，与 worktree_root 无关），
    # 成功/失败/异常各路径 finally 统一清理；missing_ok 容忍 OSError 回退路径
    # 本就未落盘的情况。
    claim_placeholder = (
        runner.project_root / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
    )
    try:
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
            _apply_provider_env(env_overrides, provider, model_override, runner)
            # 观测：run jsonl 补写 provider_marker（item faea95e2d494，五条
            # 维护车道观测口径一致；写失败不阻断，见助手 docstring）
            _write_lane_provider_marker(
                runner, run_id, "code-review-fix", "code-fix", assignment
            )
        else:
            model_override = runner._get_admin_model()

        # add-agent-env-overrides（2026-09-24 MAX_THINKING_TOKENS 实验）：配置键
        # ``agents.agent_env.code-fix`` 的 per-agent 环境变量注入——本函数只 spawn
        # code-fix run（env 随进程继承给其 Task 子代理），天然不波及其他车道。
        # 背景：glm-5.3-flash thinking 生成是回合耗时大头（09-24 批实测 117/357
        # 消息带 thinking、均 1614 字符、工具执行≈0）。实验定案后若保留须补
        # Dashboard 设置项（fenix-new-config-needs-dashboard-ui）。
        agent_env = (((getattr(runner, "config", {}) or {}).get("agents") or {}).get("agent_env") or {}).get("code-fix") or {}
        if not isinstance(agent_env, dict):
            # code-review item 21e3783270a2：``or {}`` 只兜住键缺失/None，yaml 误写为
            # 字符串/数字/列表时裸调 .items() 抛 AttributeError，且本处位于任何 try
            # 保护之外（:1995 的 try 只包 _run_claude），整批 code-fix 启动即崩。
            # 对齐 _safe_int（item dc8f109b8b60）的防御降级口径：记 WARNING 按空
            # 映射继续（零注入），不阻断维护 run 主流程。
            _log = getattr(runner, "logger", None)
            if _log is not None:
                _log.warning(
                    "code-fix",
                    f"agents.agent_env.code-fix 配置类型错误（期望 dict，实际 "
                    f"{type(agent_env).__name__}），忽略 agent_env 注入",
                )
            agent_env = {}
        for _k, _v in agent_env.items():
            # code-review item a7505e92d33e：yaml 解析值裸 str() 直转会把布尔
            # 落成 "True"/"False"、浮点落成 "1.0"，与 shell 环境变量惯用形态
            # （小写 true / 整数）不一致——下游工具按字面匹配（期望 "true"/"1"）
            # 会静默不生效。归一口径：bool → "1"/"0"（环境变量最通用真值
            # 形态）；float 可无损整归一时转 int（1.0 → "1"）；int 与字符串
            # 原样透传。
            if isinstance(_v, bool):
                _sv = "1" if _v else "0"
            elif isinstance(_v, float) and _v.is_integer():
                _sv = str(int(_v))
            else:
                _sv = str(_v)
            env_overrides[str(_k)] = _sv
        if agent_env:
            _log = getattr(runner, "logger", None)
            if _log is not None:
                _log.info("code-fix", f"agent_env 注入: {sorted(agent_env)}")

        # 结构化失败签名（evo-code-fix-api-timeout-salvage 1.2）：先于 try 初始化——
        # run_ok 也可能被产物硬门/计数读取置 False（此时 except 未执行），三值须有定义。
        api_timeout = False
        exit_code = None
        stderr_summary = ""
        try:
            output, _turns, _session_id, _usage_info = runner._run_claude(
                prompt,
                wt,
                run_id,
                model_override,
                env_overrides,
                # 轮次不设限（用户 2026-09-23）：批内条目数大时 800+扩展不够用，
                # 撞上限=整批作废。_run_claude 对 None 跳过强制块；失控兜底由
                # 超时覆盖（timeout_overrides）+ liveness 承担。
                max_turns=None,
                spec_name="code-review-fix",
                agent_type="code-fix",
            )
            run_ok = True
            error = ""
        except Exception as e:  # noqa: BLE001 — run 异常兜底为失败信封
            output = ""
            run_ok = False
            error = str(e)
            # evo-code-fix-api-timeout-salvage 1.2：结构化签名透出——失败记录与
            # 日志携带 api_timeout / exit_code / stderr 摘要，替代仅 str(e) 压扁。
            # api_timeout 判别在 runner 层完成（design D1），此处只读异常布尔标记；
            # 三元全空（非 _run_claude 失败异常）时 error 保持原文不添噪。
            api_timeout = bool(getattr(e, "api_timeout", False))
            exit_code = getattr(e, "exit_code", None)
            stderr_summary = _stderr_tail_summary(getattr(e, "stderr_lines", None))
            if api_timeout or exit_code is not None or stderr_summary:
                error = (
                    f"{error} [api_timeout={api_timeout} exit_code={exit_code}"
                    + (f" stderr_tail: {stderr_summary}" if stderr_summary else "")
                    + "]"
                )

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
            try:
                rows = _read_fix_out_rows(out_path)
            except OSError as e:
                # 硬门判存/读取成功后、计数读取前产物被删/权限收紧等读取异常
                # 不得穿透本函数收尾。此处成功但零计数会与硬门「至少一条有效
                # 行」的保证矛盾（掩盖读取故障），故对齐硬门 fail-closed 语义
                # 折算为失败信封。
                run_ok = False
                error = f"code-fix 产物计数读取失败: {out_path} 读取异常（{e}）"
                rows = []
            for rec in rows:
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
            api_timeout=api_timeout if not run_ok else False,
            exit_code=exit_code if not run_ok else None,
            stderr_summary=stderr_summary if not run_ok else "",
        )
    finally:
        try:
            claim_placeholder.unlink(missing_ok=True)
        except OSError:
            pass  # 清理失败不吞 code-fix 结果（对齐 run_regression 降级语义）


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


def _read_ocr_exclude_patterns(project_root, logger=None) -> list:
    """读项目级 ocr 审查排除域 ``<project_root>/.fenix/ocr-exclude.txt``。

    逐行一条 gitignore 风格 pattern；空行与 `#` 注释行跳过。文件缺失/读失败
    → 空列表（调用方零注入，ocr 命令与无此文件时逐字节一致）。

    含逗号的行拒绝注入（code-review item d28a00f2dac3）：patterns 经
    ",".join 拼成单值下发给 ocr ``--exclude``，ocr 侧按逗号再切分——本身含
    逗号的 gitignore 风格 pattern（如字符类 ``[a,b]``）会被拆成多条错误
    pattern，排除域静默失真且无告警。该文件由部署方编辑、无法约束其不含
    逗号，故读取侧拒绝此类行并 WARNING 留痕（logger 缺省时仅拒绝不告警）。
    """
    try:
        text = (Path(project_root) / ".fenix" / "ocr-exclude.txt").read_text(
            encoding="utf-8"
        )
    except OSError:
        return []
    patterns: list = []
    for ln in text.splitlines():
        pat = ln.strip()
        if not pat or pat.startswith("#"):
            continue
        if "," in pat:
            if logger is not None:
                logger.warning(
                    "impl-ocr",
                    "ocr-exclude.txt 含逗号的 pattern 拒绝注入"
                    f"（--exclude 逗号拼接会被 ocr 二次切分）: {pat}",
                )
            continue
        patterns.append(pat)
    return patterns


# ocr 审查背景注入（09-23 忽略标记方案）：代码中 `[fenix-ignore:<item_id>]`
# 注释 = 先前审查已裁决「误报/不值得修」的位置。经 ocr --background 通道告知
# 审查 LLM 该约定（ocr 提示词属外部工具不可改）；无标记时本段对审查无作用。
# 写侧（code-fix agent 打标记）见 agents/code-fix.md「忽略标记」节。
OCR_IGNORE_MARKER_BACKGROUND = (
    "忽略标记约定：代码中形如 `[fenix-ignore:<item_id>] <理由>` 的注释表示该"
    "问题已被先前审查裁决为「误报/不值得修」并说明了理由。你复核某处代码时，"
    "若拟上报的问题与就近标记注释的理由一致，MUST NOT 再上报该问题；仅当代码"
    "演进已使标记理由失效（前提不再成立）时才正常上报。"
)


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
        now = datetime.now(timezone.utc)
        # date 统一为日期语义（item f6ba9c4dccef）：此前写 run_id
        # （impl-ocr-<spec>-<epoch>），run_id 另立字段承载（对齐其余归账
        # 函数的 YYYY-MM-DD 口径，按日聚合不再错组）。
        entry = {
            "agent_type": "impl-ocr",
            "date": now.date().isoformat(),
            "run_id": run_id,
            "timestamp": now.isoformat(),
            # 经 _safe_int 防御转换（对齐 _token_usage_fields / item
            # dc8f109b8b60）：ocr summary 畸形值回落 0，保住整条记账记录
            "input_tokens": _safe_int(summary.get("input_tokens", 0) or 0),
            "output_tokens": _safe_int(summary.get("output_tokens", 0) or 0),
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
                              from_commit: str, head_commit: str
                              ) -> tuple[threading.Event, threading.Thread]:
    """启动车道运行中心跳线程，返回 ``(stop_event, thread)``。

    审查子进程运行期间按 ``IMPL_OCR_HEARTBEAT_INTERVAL_SECONDS`` 间隔经既有
    ``_write_impl_ocr_run_events`` 向车道 run 转录追加 ``progress`` 事件
    （review 区间 from/to + 自启动起 ``time.monotonic`` 已用时秒数）。消费
    orphaned_state 无驱动探针条件①（run mtime 宽限窗）：``_has_recent_spec_run``
    因心跳持续为真 → ``spec_is_undriven`` 为假，大 diff 长审查不再误报孤儿；
    探针判定函数本体零改动。daemon 重启心跳自然停止 → 宽限+阈值过后真孤儿
    仍被正常上报（不加任何 ``_ocr_join_wait`` 有意等待豁免，不遮蔽自愈链）。

    调用方收尾 MUST 先 ``stop_event.set()`` + ``thread.join(有上限)`` 停跳、
    再写终态事件（``result``/``error`` 末行后置不变量，D2 顺序；该不变量是
    尽力而为语义——join 超时后仍可能落下迟到的 progress 行，见
    ``_stop_impl_ocr_heartbeat``）。心跳写失败静默
    （``_write_impl_ocr_run_events`` 既有语义，观测通道不阻断车道）。
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


def _stop_impl_ocr_heartbeat(stop_event: threading.Event | None,
                             thread: threading.Thread | None) -> None:
    """停跳（D2 顺序约束）：置位 + 有上限 join，先于终态事件写入。

    幂等（Event.set 可重入、join 已死线程立即返回），供子进程收尾 finally
    与车道整体 finally 双重调用（意外异常路径同样停跳）。正常路径返回后
    心跳线程不再追加任何 ``progress`` 行，主线程独占写——终态事件保持文件
    末行，归档/worktree 清理也不会被迟到的心跳复活旧文件。

    残余竞窗（尽力而为语义，code-review item 60aa2441f347）：若心跳线程恰
    阻塞在 ``_write_impl_ocr_run_events`` 内超过 join 上限，join 超时返回后
    仍可能落下一条迟到的 progress 行。影响有界：``append_run_line`` 的
    O_APPEND 原子追加保证短行不交错，终态行仍是完整行（只是其后多一行
    progress）；终态末行不变量在该路径下按尽力而为理解。
    """
    if stop_event is not None:
        stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=IMPL_OCR_HEARTBEAT_JOIN_TIMEOUT_SECONDS)


def _kill_ocr_process_group(proc: subprocess.Popen) -> None:
    """ocr 审查子进程清场：对独立进程组 SIGTERM→宽限→SIGKILL 杀整棵树。

    code-review item 12df9da4bb5a：spawn 侧 start_new_session=True 独立成组
    （pgid==pid）——bin/ocr_review.py 经 execvp 改名（同 PID）后自身还会并发
    拉起 scan 孙进程（--concurrency），只对组长 kill/SIGTERM 会留下被收养继续
    运行的孙进程孤儿（可能占住 detached worktree 的 git 状态，削弱
    _remove_impl_ocr_worktree 的 --force 清理语义）。对齐仓库既有惯例
    （core/knowledge_backfill.py _kill_process_group、core/regression.py D8、
    core/v2_dev_server.py design D2、core/adjudication_narrative.py，均注明
    「只杀直接子进程会让孙进程存活」）。killpg 失败（进程组已退出）按现状
    静默降级；组长收尸与管道排空仍由调用方的 communicate 负责。

    组长先行退出而孙进程仍持组籍/管道写端时补一刀 SIGKILL：进程组仍有成员
    则 killpg 命中残余孙进程，组已空则 ESRCH 静默——否则调用方 communicate
    会因孙进程未关尽的管道写端读不到 EOF。
    """
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        return  # 进程组已不存在（组长已自行退出），交还调用方 communicate 收尸
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass  # 进程组已不存在
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass  # 组已空/已不存在（ESRCH），静默


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
    lane_done = None  # threading.Event；登记进排水集合后由本线程收尾时 set
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
            exclude_patterns = _read_ocr_exclude_patterns(
                runner.project_root, getattr(runner, "logger", None)
            )
            if exclude_patterns:
                cmd += ["--exclude", ",".join(exclude_patterns)]
            # 忽略标记约定（09-23）：常驻注入，告知审查 LLM [fenix-ignore:*]
            # 注释的语义——先前裁决过的位置不再重报。
            cmd += ["--background", OCR_IGNORE_MARKER_BACKGROUND]
            # ── 运行中心跳（fix-ocr-lane-orphaned-state-misfire 1.1）：子进程
            # 运行期唯一启跳（elapsed 自子进程启动起计）；返回/超时先停跳再
            # 走分类收尾，终态事件保持末行后置（1.2 顺序约束）。──
            heartbeat = _start_impl_ocr_heartbeat(
                runner.project_root, run_id, spec_name, from_commit, head_commit
            )
            # planned-restart-drain B：审查子进程 Popen 化 + 在飞登记进排水
            # 集合——按 Popen 句柄跟踪（wrapper execvp 改名不受影响，同 PID），
            # 规划性重启排水等待本车道完成或超窗有序终止，不再被当无主回收。
            # lane_done 由本线程在全函数收尾（产物+终态事件落盘）后 set，供
            # shutdown 收口 bounded 等待车道落终态，daemon 不至先于终态退出；
            # 排水登记随 set 一同在函数尾段 finally 注销（终态落盘前车道保持
            # 对 running_lane_ids/排水收口可见）。
            # 登记 API 为 planned-restart-drain 2.1 新增：旧测试替身/第三方
            # runner 缺该方法时按未登记处理（行为同现状）。
            lane_done = threading.Event()
            proc = subprocess.Popen(
                cmd,
                cwd=str(wt),
                env={**os.environ, **env_overrides},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # code-review item 12df9da4bb5a：独立进程组（pgid==pid）——
                # bin/ocr_review.py 自身会并发拉起 scan 孙进程（--concurrency），
                # 硬超时/异常/排水清场用 _kill_ocr_process_group 杀整棵树，杜绝
                # 「只杀直接子进程会让孙进程存活」（仓库惯例：regression D8、
                # v2_dev_server design D2、knowledge_backfill 等）。
                start_new_session=True,
            )
            _register_lane = getattr(runner, "register_lane_process", None)
            if callable(_register_lane):
                try:
                    _register_lane(run_id, proc, lane_done)
                except BaseException:
                    # 注册失败同理收尸：进程已启动，不 kill 会以孤儿形态继续
                    # 运行占用资源——进程组清场+reap 后上抛（外层折算
                    # unavailable）。
                    _kill_ocr_process_group(proc)
                    try:
                        proc.communicate(timeout=10)
                    except Exception:
                        pass
                    raise
            try:
                try:
                    _proc_out, _proc_err = proc.communicate(
                        timeout=ConfigLoader.get_impl_code_review_lane_timeout_sec(
                            runner.config
                        )
                    )
                    timed_out = False
                except subprocess.TimeoutExpired:
                    # 车道硬超时：对齐 subprocess.run 语义（进程组清场+reap 后
                    # 不再使用 stdout/stderr，reason 走硬超时文案）
                    _kill_ocr_process_group(proc)
                    try:
                        proc.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    proc = None
                    timed_out = True
                except BaseException:
                    # 意外异常（如 MemoryError）中断 communicate：进程仍存活，
                    # 先进程组清场+reap 收尸再上抛（外层折算 unavailable）——
                    # 否则审查子进程以孤儿形态继续运行占用资源。
                    _kill_ocr_process_group(proc)
                    try:
                        proc.communicate(timeout=10)
                    except Exception:
                        pass
                    raise
            finally:
                # 完成/非零退出/硬超时/意外异常四路同收口：停跳后本线程独占
                # 写（幂等，车道整体 finally 二次调用无害）。排水登记不在此
                # 注销——此刻终态（产物+事件）尚未落盘，提前注销会让 shutdown
                # 落在持久化窗口内时不再等待车道收尾；注销随 lane_done.set()
                # 一同延迟到函数尾段 finally。
                _stop_impl_ocr_heartbeat(*heartbeat)

            if timed_out:
                lane_timeout = ConfigLoader.get_impl_code_review_lane_timeout_sec(
                    runner.config
                )
                artifact["reason"] = (
                    f"车道硬超时（>{lane_timeout}s，verify."
                    f"impl_code_review_lane_timeout_sec）"
                )
            elif proc.returncode < 0:
                # planned-restart-drain D3：负返回码 = 被信号终止（重启排水超窗
                # SIGTERM / SIGKILL 收口）——落 unavailable 终态并写明信号语义，
                # 重启后归档与无主回收逻辑不再误判。
                artifact["reason"] = (
                    f"车道进程被信号终止（signal={-proc.returncode}，"
                    f"重启排水超窗/关停收口）"
                )
            elif proc.returncode != 0:
                artifact["reason"] = (
                    f"ocr 非零退出（rc={proc.returncode}）: "
                    f"{(_proc_err or _proc_out or '').strip()[-400:]}"
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
    # planned-restart-drain B：落盘→终态事件→收尾日志整段包 try/finally——
    # 尾段任何退出路径（含收尾日志等调用抛错）都保证 set lane_done 并注销
    # 排水登记：set 使 terminate_lane_processes 的 bounded 等待不盲等，注销
    # 放在同一 finally 让登记与「终态已 durable」同生命周期（此前在
    # communicate 返回即注销，持久化窗口内车道对排水收口不可见）。finally
    # 只做收尾不吞异常，既有错误传播行为不变。
    try:
        try:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = artifact_path.with_name(".code-review.json.tmp")
            tmp.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, artifact_path)
        except OSError as e:
            if log is not None:
                log.warning(
                    "agent_runner", f"impl-ocr 产物落盘失败（run {run_id}）: {e}"
                )

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
    finally:
        # 产物+终态事件均已落盘（或尾段异常退出），通知 shutdown 收口本车道
        # 终态就绪并注销登记（terminate_lane_processes 据此 bounded 等待，
        # 不再盲等；注销幂等）。
        if lane_done is not None:
            lane_done.set()
        _unregister_lane = getattr(runner, "unregister_lane_process", None)
        if callable(_unregister_lane):
            _unregister_lane(run_id)
    return artifact
