"""core.pm_engine.verification.judge_gate — judge 派发门/重跑上限/降级上下文（refactor-verification-module D2）。

从 VerificationPipeline 摘出的 judge 派发门禁（_judge_dispatch_gate）、judge
重跑硬上限冻结（_judge_hard_cap_freeze / _judge_rerun_count）、全绿快速路径
（_all_green_fast_path）、planner 成本读取（_last_planner_cost_usd /
_last_planner_run_cost）、降级上下文读写（_write_degrade_context /
_clear_degrade_context）。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.agent_runner.run_files import run_spec_part

# judge-rerun-stability R1：单 spec judge 重跑硬上限（judge run 总数）。
_MAX_JUDGE_RERUNS = 5


def _judge_dispatch_gate(pipeline, spec_name: str):
    """judge 派发前置守卫（judge-rerun-stability R1）。

    调用点在阶段3 judge 派发处（三阶段主路径 + 全绿快道回退）：
      - judge_rerun_count +1（含被稳定性复用跳过但未实际派发的判定次数）；
      - 总数超上限（_MAX_JUDGE_RERUNS=5）→ blocked + 人工升级告警，hard cap
        触发时 judge_rerun_count 与 _verify_fail_rounds 一并冻结
        （_judge_cap_frozen 标记，两者的自动递增全部失效）；
      - verdict 稳定（spec 戳未变 && report.json mtime 未变 && 连续两轮
        一致）→ 返回合成复用结果（不新起 judge run，叫停连发重派）。

    Returns:
      - None：正常派发 judge；
      - AgentRunResult：verdict 稳定复用的合成结果（调用方直接采纳）；
      - False：硬上限已 blocked，调用方应 return。
    """
    from core.verify_report import is_verdict_stable, read_verdict_stability

    count = pipeline._judge_rerun_count(spec_name, delta=1)
    if count > _MAX_JUDGE_RERUNS:
        pipeline._judge_hard_cap_freeze(spec_name, count)
        return False
    if not is_verdict_stable(pipeline._context.project_root, spec_name):
        return None
    # 稳定性复用：返回合成结果，下游采纳尾段继续（_read_planner_result
    # 读到上次 judge 落盘的 .fenix-run-result.json，verdict 一致即等价）。
    data = read_verdict_stability(pipeline._context.project_root, spec_name) or {}
    rounds = data.get("rounds") or []
    latest = rounds[-1] if rounds else {}
    status = latest.get("status") if isinstance(latest, dict) else "unknown"
    text = (
        f"verdict 稳定复用（连续两轮一致，status={status}，spec 戳与"
        f"report.json 未变）— 跳过 judge 派发"
    )
    pipeline._context.logger.info("pm_engine", f"[阶段3] verdict 稳定复用 '{spec_name}' — {text}")
    from core.agent_runner.runner import AgentRunResult

    return AgentRunResult(
        run_id="verdict-stable-reuse",
        spec_name=spec_name,
        agent_type="planner-judge",
        success=True,
        duration_seconds=0.0,
        output=text,
    )


def _judge_hard_cap_freeze(pipeline, spec_name: str, count: int) -> None:
    """judge 重跑硬上限处置：blocked + 人工升级告警，计数器一并冻结（R1）。

    judge_rerun_count 与 _verify_fail_rounds 正交；hard cap 触发时两者一并
    冻结（_judge_cap_frozen 标记使两侧自动递增全部失效），与 fail-closed
    同语义需人工裁决放行。
    """
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "status": "blocked",
            "error": (
                f"judge 重跑超上限（{count}/{_MAX_JUDGE_RERUNS} 轮）— 已冻结"
                f"等待人工裁决。详见 `spec/changes/{spec_name}/verification-report.md`"
            ),
            "_judge_cap_frozen": True,
        },
    )
    pipeline._context.logger.error(
        "pm_engine",
        f"judge 重跑硬上限 '{spec_name}'（{count} 轮）— " f"冻结为 blocked，等待人工裁决",
    )
    pipeline._context.escalation_notifier(
        spec_name=spec_name,
        signal_type="judge_rerun_cap",
        severity="major",
        description=(
            f"'{spec_name}' judge 重跑超上限"
            f"（{count}/{_MAX_JUDGE_RERUNS} 轮），已冻结等待人工裁决"
        ),
        evidence=f"spec={spec_name}; judge_rerun_count={count}",
        recommended_action=(
            "检查验证为何反复重跑 judge（场景集冻结是否生效/失败是否复现一致）；"
            "人工裁决后重置验证，计数器随 verified 落定清零点恢复"
        ),
    )


def _judge_rerun_count(pipeline, spec_name: str, delta: int = 0) -> int:
    """STATE.md 读取/增量 ``_judge_rerun_count``（判据与 _verify_fail_rounds 正交）。

    judge 派发决策（含被稳定性复用跳过但未实际派发的判定次数）在派发处
    delta=+1 递增；读到 ``_judge_cap_frozen`` 冻结标记时强制不再递增
    （hard cap 触发后 judge 侧计数器冻结，与 _verify_fail_rounds 一并冻结）。
    """
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    if delta and entry.get("_judge_cap_frozen"):
        return int(entry.get("_judge_rerun_count", 0) or 0)
    count = 0
    try:
        count = int(entry.get("_judge_rerun_count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    if delta:
        count = max(0, count + delta)
        pipeline._context.state_machine.update_spec(spec_name, {"_judge_rerun_count": count})
    return count


def _all_green_fast_path(pipeline, spec_name: str, report: dict, fail_count: int):
    """全绿快道（judge 效率治理 A，2026-09-06）：0 失败 0 警告 → 机械 verified。

    返回合成 ``AgentRunResult``（run_id=mechanical-all-green）供既有采纳
    尾段原样消费；返回 None = 存在失败/警告，走常规 judge。结果文件写
    primary 路径并**覆盖上一轮 judge 残留**（防 ``_read_planner_result``
    读到旧裁决）。

    fix-verdict-read-failclosed D6（fail-closed 语义反转）：写回失败**不得**
    静默 verified——快道产物是机械合成，写回失败极罕见，此时按「本轮无裁决
    产物」退化为常规 judge（返回 None），由 judge 补一轮真实裁决；绝无
    「按 verified 兜底」的旧语义（读侧缺失文件按通过放行即历史事故根因）。
    """
    summary = report.get("summary") or {}
    if fail_count != 0 or (summary.get("warnings") or 0) != 0 or (summary.get("passed") or 0) <= 0:
        return None
    result_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / ".fenix-run-result.json"
    )
    text = (
        f"全绿快道: {summary.get('passed')}/{summary.get('total')} 场景通过、"
        "0 失败 0 警告——无分类对象，跳过 judge 机械 verified"
    )
    payload = {
        "spec": spec_name,
        "status": "verified",
        "bugs": [],
        "summary": text,
        "mechanical": True,
    }
    try:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        # fix-verdict-read-failclosed D6：机械写回失败 → 退化常规 judge（返回
        # None），不得按 verified 兜底放行（历史 fail-open 语义已清除）。
        pipeline._context.logger.error(
            "pm_engine",
            f"全绿快道结果文件写回失败 '{spec_name}' — 退化为常规 judge: {e}",
        )
        return None
    pipeline._context.logger.info("pm_engine", f"[阶段3] 全绿快道 '{spec_name}' — {text}")
    from core.agent_runner.runner import AgentRunResult

    return AgentRunResult(
        run_id="mechanical-all-green",
        spec_name=spec_name,
        agent_type="planner-judge",
        success=True,
        duration_seconds=0.0,
        output=text,
    )


# ── judge-rerun-stability：计数/稳定性复用/verified 放行门 ────────────


def _last_planner_cost_usd(pipeline, spec_name: str) -> float | None:
    """最近一次 planner-plan run 的网关回传成本（degrade 上下文用，D3）。

    从验证链侧车 ``.fenix/verify-progress/<spec>/tokens.json`` 取最后一个
    agent_type=planner-plan 条目的 cost_usd。网关不回传时为 None（不伪造）。

    Returns:
        cost_usd 或 None（侧车缺失/无 planner 条目/回传为 None）。
    """
    tokens_json = (
        pipeline._context.project_root / ".fenix" / "verify-progress" / spec_name / "tokens.json"
    )
    if not tokens_json.is_file():
        return None
    try:
        data = json.loads(tokens_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    runs = data.get("runs")
    if not isinstance(runs, list):
        return None
    for r in reversed(runs):
        if not isinstance(r, dict):
            continue
        if r.get("agent_type") != "planner-plan":
            continue
        cost = r.get("cost_usd")
        if cost is None:
            return None
        try:
            return float(cost)
        except (TypeError, ValueError):
            return None
    return None


def _last_planner_run_cost(pipeline, spec_name: str) -> str:
    """最近一次 planner run 的实际成本摘要（冻结转人工告警的裁决参考，D5）。

    从 STATE 累计 ``_cost_usd``/``_tokens_in`` 与 ``.fenix/runs/`` 中该 spec
    最近一次 planner-plan 产物（``planner-plan-<spec>-*.jsonl``）取时长。
    任一来源缺失 → 返回空串（告警附注段 fail-open，不因取数失败阻断升级）。

    Returns:
        人类可读成本摘要（如 ``累计 $176.65 / 2.61亿 tokens；最近 planner
        run 5.3 小时``）；无数据返回空串。
    """
    spec = pipeline._context.state_machine.read_one(spec_name) or {}
    parts: list[str] = []
    try:
        cost = float(spec.get("_cost_usd") or 0)
        tokens_in = int(spec.get("_tokens_in") or 0)
        if cost > 0 or tokens_in > 0:
            cost_txt = f"${cost:.2f}" if cost > 0 else "费用未回传"
            tokens_txt = f"{tokens_in/1e6:.1f}M tokens" if tokens_in else "tokens 未记录"
            parts.append(f"累计 {cost_txt} / {tokens_txt}")
    except (TypeError, ValueError):
        pass
    try:
        runs_dir = pipeline._context.project_root / ".fenix" / "runs"
        if runs_dir.is_dir():
            candidates = sorted(
                p for p in runs_dir.glob(f"planner-plan-{spec_name}-*.jsonl")
                # 精确归属守卫（范式见 recovery.py）：spec 名互为前缀时
                # glob 命中不得直接认定——planner-plan-fix-x 不得取 fix-x-y 的耗时
                if run_spec_part(p.stem) == spec_name
            )
            if candidates:
                last = candidates[-1]
                duration_s = None
                for line in last.read_text(encoding="utf-8", errors="ignore").splitlines():
                    try:
                        d = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if isinstance(d, dict) and d.get("type") == "result":
                        dur = d.get("duration_ms")
                        if dur:
                            duration_s = float(dur) / 1000.0
                if duration_s:
                    hours = duration_s / 3600.0
                    parts.append(f"最近 planner run {hours:.1f} 小时")
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return "；".join(parts)


def _write_degrade_context(
    pipeline, spec_name: str, reason: str, run_id: str, duration_seconds: float
) -> None:
    """降级前落盘 degrade 上下文（add-planready-artifact-gate D3）。

    新验证流程降级 legacy verifier 的判定点调用：把降级原因与被降级轮次
    代价（时长/成本）持久化到 ``.fenix/verify-progress/<spec>/degrade_context.json``，
    供 verify_report 合成路径注入降级标注（G3）。写失败不阻断降级主流程
    （WARNING 留痕，观测增强）。

    Args:
        spec_name: spec 名。
        reason: 降级原因归因文案（planner 阶段失败归因，如
            「Planner 未生成有效场景，status=不可读(missing: ...)」）。
        run_id: 被降级的 planner run id。
        duration_seconds: 被降级轮次的时长（秒）。
    """
    ctx_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "degrade_context.json"
    )
    cost_usd = pipeline._last_planner_cost_usd(spec_name)
    payload = {
        "reason": str(reason or ""),
        "run_id": str(run_id or ""),
        "duration_seconds": (float(duration_seconds or 0) if duration_seconds else 0.0),
        "cost_usd": (float(cost_usd) if cost_usd is not None else None),
        "degraded_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        ctx_path.parent.mkdir(parents=True, exist_ok=True)
        ctx_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as e:
        # 观测量写入绝不分叉降级主流程：MagicMock 泄漏/路径不可写/类型
        # 非法统一 WARNING 留痕（design D3「写失败不阻断」）。
        pipeline._context.logger.warning(
            "pm_engine",
            f"degrade_context 落盘失败（不阻断降级）'{spec_name}': {e}",
        )


def _clear_degrade_context(pipeline, spec_name: str) -> None:
    """新验证流程成功路径删除陈旧 degrade 上下文（add-planready-artifact-gate D3）。

    plan-ready 校验通过后调用——覆盖旧降级事实，防陈旧标注污染后续正常报告
    （D3：成功时删除；失败/重验路径之外不清，历史留痕）。删除失败仅 WARNING
    （陈旧标注风险窗口极小，不阻断验证主流程）。
    """
    ctx_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "degrade_context.json"
    )
    try:
        if ctx_path.exists():
            ctx_path.unlink()
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"陈旧 degrade_context 清理失败 '{spec_name}': {e}",
        )
