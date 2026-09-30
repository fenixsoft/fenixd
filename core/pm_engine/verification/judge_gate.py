"""core.pm_engine.verification.judge_gate — judge 派发门/重跑上限/降级上下文（refactor-verification-module D2）。

从 VerificationPipeline 摘出的 judge 派发门禁（_judge_dispatch_gate）、judge
重跑硬上限冻结（_judge_hard_cap_freeze / _judge_rerun_count）、全绿快速路径
（_all_green_fast_path）、planner 成本读取（_last_planner_cost_usd /
_last_planner_run_cost）、降级上下文读写（_write_degrade_context /
_clear_degrade_context）。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.agent_runner.run_files import run_spec_part
from core.pm_engine.verification.scenario_gate import atomic_write_text

# judge-rerun-stability R1：单 spec judge 重跑硬上限（judge run 总数）。
_MAX_JUDGE_RERUNS = 5

# ── judge 轮内重裁决治理（add-verify-lane-throughput 3.1/3.2）─────────────
# 轮内真实派发阈值：同一 (spec, 验证轮) 内真实派发（非 fast-track 复用命中）
# 达 2 次仍需再派 → 停止第 3 次派发，人工升级告警 + spec 保持可重试状态。
# 与既有 spec 级硬上限（_MAX_JUDGE_RERUNS=5）并存，轮内阈值先触发。
_JUDGE_ROUND_MAX_REAL_DISPATCHES = 2
# 证据扩充每轮上限（3.2）：低置信可补类型（缺 evidence/截断）优先补证重判，
# 扩充不计入重派计数，每轮至多 1 次。
_JUDGE_ROUND_MAX_EXPANSIONS = 1

# 轮级计数器的 STATE 字段（随验证轮重置）与生命周期统计字段（跨轮累计，
# 读侧 summary 消费，见 dashboard/data/summary.py judge_fasttrack_hits /
# judge_real_dispatches）。
_JUDGE_ROUND_ID_FIELD = "_judge_round_id"
_JUDGE_ROUND_REAL_FIELD = "_judge_round_real"
_JUDGE_ROUND_EXPANDED_FIELD = "_judge_round_expanded"
_JUDGE_ROUND_ESCALATED_FIELD = "_judge_round_escalated"
_JUDGE_ROUND_REPORT_MTIME_FIELD = "_judge_round_report_mtime"
_JUDGE_FASTTRACK_HITS_FIELD = "_judge_fasttrack_hits"
_JUDGE_REAL_DISPATCHES_FIELD = "_judge_real_dispatches"


def _judge_verify_round(pipeline, spec_name: str) -> int:
    """当前验证轮次（= ``_verify_fail_rounds``，首轮 0；读取异常按 0）。"""
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    try:
        return int(entry.get("_verify_fail_rounds", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _judge_report_mtime_ns(pipeline, spec_name: str):
    """当前 report.json mtime_ns（判定上下文指纹）；缺失返回 None。"""
    p = (
        Path(pipeline._context.project_root)
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "report.json"
    )
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return None


def _judge_round_state(pipeline, spec_name: str) -> dict:
    """读 (spec, 验证轮, 判定上下文) 维度计数器；上下文变化即重置（3.1）。

    轮次键 = ``_verify_fail_rounds``（bug-found 修复递增）；同轮判定上下文
    键 = report.json mtime——**场景修复重入（scenario-repaired）每轮合法
    重执行并重派 judge**，report 已重写即视为新判定上下文，计数从零计
    （治理目标只是「同一份报告反复重裁决」，不拦合法的新执行轮）。
    """
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    current_round = _judge_verify_round(pipeline, spec_name)
    current_mtime = _judge_report_mtime_ns(pipeline, spec_name)

    def _int_or(v, d=0):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return d

    try:
        stored_round = entry.get(_JUDGE_ROUND_ID_FIELD)
        same_round = stored_round is not None and int(stored_round) == current_round
    except (TypeError, ValueError):
        same_round = False
    if same_round:
        stored_mtime = entry.get(_JUDGE_ROUND_REPORT_MTIME_FIELD)
        try:
            stored_mtime = int(stored_mtime) if stored_mtime is not None else None
        except (TypeError, ValueError):
            stored_mtime = None
        if (
            stored_mtime is not None
            and current_mtime is not None
            and stored_mtime != current_mtime
        ):
            same_round = False  # report 重执行 → 新判定上下文
    if not same_round:
        reset = {
            _JUDGE_ROUND_ID_FIELD: current_round,
            _JUDGE_ROUND_REAL_FIELD: 0,
            _JUDGE_ROUND_EXPANDED_FIELD: 0,
            _JUDGE_ROUND_ESCALATED_FIELD: False,
        }
        if current_mtime is not None:
            reset[_JUDGE_ROUND_REPORT_MTIME_FIELD] = current_mtime
        # [fenix-ignore:77163ea07645] update_spec 与 bump_counters 同锁域（各自都在 .STATE.md.lock 的 flock(LOCK_EX) 内读改写），且本重置写的是常量 0 而非锁外快照计算值，无丢增量窗口。
        pipeline._context.state_machine.update_spec(spec_name, reset)
        return {"round": current_round, "real": 0, "expanded": 0, "escalated": False}
    return {
        "round": current_round,
        "real": _int_or(entry.get(_JUDGE_ROUND_REAL_FIELD)),
        "expanded": _int_or(entry.get(_JUDGE_ROUND_EXPANDED_FIELD)),
        # STATE 属性以字符串持久化（布尔落盘为 'False'/'True'）——不能用
        # bool() 直接包（bool('False') 为真会误判「本轮已升级」而吞掉告警）。
        "escalated": str(entry.get(_JUDGE_ROUND_ESCALATED_FIELD, False)).strip().lower()
        in ("true", "1"),
    }


def _judge_round_bump(pipeline, spec_name: str, field: str) -> int:
    """轮内/生命周期计数字段 +1（返回新值；写失败不影响主流程）。

    锁内原子递增（``state_machine.bump_counters``，与
    ``fastlane._bump_fail_streak`` 同款）：锁外快照读改写会与其它对同字段
    的写者（验证失败记账、admin infra 回拨）互相覆盖丢增量，使轮内/生命周期
    阈值失真。
    """
    final = pipeline._context.state_machine.bump_counters(spec_name, {field: 1})
    return final.get(field, 0)


def _judge_charge_real_dispatch(pipeline, spec_name: str) -> int:
    """记一次真实派发：轮内计数 +1、生命周期 ``_judge_real_dispatches`` +1。

    同时刷新判定上下文键（当前 report.json mtime）——后续 gate 以此识别
    「同轮 report 重执行」并重置轮内计数（合法新执行轮不受阈值约束）。
    """
    _judge_round_bump(pipeline, spec_name, _JUDGE_ROUND_REAL_FIELD)
    mtime = _judge_report_mtime_ns(pipeline, spec_name)
    if mtime is not None:
        pipeline._context.state_machine.update_spec(
            spec_name, {_JUDGE_ROUND_REPORT_MTIME_FIELD: mtime}
        )
    return _judge_round_bump(pipeline, spec_name, _JUDGE_REAL_DISPATCHES_FIELD)


def _judge_charge_fasttrack_hit(pipeline, spec_name: str) -> int:
    """记一次 fast-track 复用命中（``_judge_fasttrack_hits``，不计真实派发）。"""
    return _judge_round_bump(pipeline, spec_name, _JUDGE_FASTTRACK_HITS_FIELD)


def _judge_charge_verdict_retry(pipeline, spec_name: str, violations: list) -> str:
    """对一次 judge 重裁决派发分类记账（add-verify-lane-throughput 3.2）。

    记账前先做轮次键校验（``_judge_round_state``：验证轮变化即重置）。分类：
      - violations 全为可补类型（evidence 缺失/截断，``is_expandable_evidence_violation``）
        且轮内扩充名额未用尽 → 占用扩充名额，本次重判 **不计入** 重派计数，
        返回 "expansion"；
      - 否则（含不可补类型、名额耗尽、violations 为空）→ 记一次真实派发
        （轮内 +1、生命周期 ``_judge_real_dispatches`` +1），返回 "real"。

    调用点：``_verify_verdict_evidence`` 违规重派处（该路径直接 run_planner
    不经 gate，轮内计数必须在此同步记账）。
    """
    from core.verdict_check import is_expandable_evidence_violation

    state = _judge_round_state(pipeline, spec_name)
    expandable = bool(violations) and all(
        is_expandable_evidence_violation(v.get("reason") if isinstance(v, dict) else "")
        for v in violations
    )
    if expandable and state["expanded"] < _JUDGE_ROUND_MAX_EXPANSIONS:
        _judge_round_bump(pipeline, spec_name, _JUDGE_ROUND_EXPANDED_FIELD)
        pipeline._context.logger.info(
            "pm_engine",
            f"judge 重裁决定性为证据扩充 '{spec_name}'（违规均属可补类型，"
            f"本轮扩充 {state['expanded'] + 1}/{_JUDGE_ROUND_MAX_EXPANSIONS}）"
            "— 不计入重派计数",
        )
        return "expansion"
    _judge_charge_real_dispatch(pipeline, spec_name)
    return "real"


def _judge_round_verdict_history(pipeline, spec_name: str, limit: int = 5) -> str:
    """历次 judge 结论摘要（升级告警 evidence 用，fail-open 空串）。"""
    try:
        from core.verify_report import read_verdict_stability

        data = read_verdict_stability(pipeline._context.project_root, spec_name) or {}
        rounds = data.get("rounds") or []
        parts = []
        for r in rounds[-limit:]:
            if isinstance(r, dict):
                parts.append(
                    f"{r.get('at') or r.get('timestamp') or '?'}: {r.get('status', '?')}"
                )
        return "；".join(parts)
    except Exception:
        return ""


def _judge_round_escalate(pipeline, spec_name: str, state: dict) -> None:
    """轮内停派的人工升级（只发一次/轮，复用 human-escalation-alert 通道）。

    spec 保持 testing 可重试状态（MUST NOT 冻结、MUST NOT 销毁产物）：人工
    处置后重入 testing 按正常路径执行；重复命中（stuck 兜底重入验证轮）仅
    INFO 留痕，不重复告警。
    """
    fresh = _judge_round_state(pipeline, spec_name)
    if fresh["escalated"]:
        pipeline._context.logger.info(
            "pm_engine",
            f"judge 轮内重裁决已达阈值（本轮已升级）'{spec_name}' — 保持 testing "
            f"等待人工处置，不重复告警",
        )
        return
    pipeline._context.state_machine.update_spec(
        spec_name, {_JUDGE_ROUND_ESCALATED_FIELD: True}
    )
    history = _judge_round_verdict_history(pipeline, spec_name)
    pipeline._context.logger.error(
        "pm_engine",
        f"judge 轮内重裁决达阈值 '{spec_name}'（本轮真实派发 "
        f"{fresh['real']} 次，仍需第 {fresh['real'] + 1} 次）— 停止派发，人工升级；"
        f"spec 保持 testing 可重试",
    )
    # 升级通道自身失败不得抛穿裁决流程（与 escalation.py 升级路径对齐，
    # code-review item 7e0509f14fdd）：轮内停派升级告警失败仅 WARNING
    # 留痕，spec 保持 testing 可重试的停派结论不受影响。
    try:
        pipeline._context.escalation_notifier(
            spec_name=spec_name,
            signal_type="judge_round_rerun_cap",
            severity="major",
            description=(
                f"'{spec_name}' 第 {state['round']} 轮验证内 judge 重裁决达阈值"
                f"（真实派发 {fresh['real']} 次，第 {fresh['real'] + 1} 次派发被阻止）—"
                "已停止派发等待人工处置，spec 保持可重试状态"
            ),
            evidence=(
                f"spec={spec_name}; verify_round={state['round']}; "
                f"round_real_dispatches={fresh['real']}; 历次结论: {history or '无记录'}"
            ),
            recommended_action=(
                "检查本轮 judge 反复重裁决根因（场景集是否冻结生效/失败是否复现一致/"
                "产物是否被并发改写）；人工处置后重入 testing 即按正常路径执行"
            ),
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"judge 轮内停派升级告警失败 '{spec_name}'（非阻塞）: "
            f"{type(e).__name__}: {e}",
        )


def _judge_dispatch_gate(pipeline, spec_name: str):
    """judge 派发前置守卫（judge-rerun-stability R1 + add-verify-lane-throughput 3.1）。

    调用点在阶段3 judge 派发处（三阶段主路径 + 全绿快道回退）：
      - judge_rerun_count +1（含被稳定性复用跳过但未实际派发的判定次数）；
      - 总数超上限（_MAX_JUDGE_RERUNS=5）→ blocked + 人工升级告警，hard cap
        触发时 judge_rerun_count 与 _verify_fail_rounds 一并冻结
        （_judge_cap_frozen 标记，两者的自动递增全部失效）；
      - verdict 稳定（spec 戳未变 && report.json mtime 未变 && 连续两轮
        一致）→ 返回合成复用结果（不新起 judge run，叫停连发重派），并记
        fast-track 命中（``_judge_fasttrack_hits``，不计真实派发）；
      - 轮内重裁决阈值（3.1，先于全局硬上限触发的语义位在稳定性复用之后）：
        本轮真实派发已达 2 次仍需再派 → 停止派发 + 人工升级告警（含历次结论
        摘要），spec 保持 testing 可重试，返回 False 供调用方让位退出。

    Returns:
      - None：正常派发 judge（已记一次真实派发）；
      - AgentRunResult：verdict 稳定复用的合成结果（调用方直接采纳）；
      - False：硬上限已 blocked，或轮内重裁决停派（人工升级已发），调用方应
        return 让位。
    """
    from core.verify_report import is_verdict_stable, read_verdict_stability

    # 轮内停派已生效的判定不再计入全局重跑数（code-review item 5cb6790efc98）：
    # _judge_round_escalated 置位后，每次 stuck 兜底/重试重入本 gate 都不会再
    # 实际派发；若仍无条件 delta=1，judge_rerun_count 很快越过 _MAX_JUDGE_RERUNS
    # 触发 _judge_hard_cap_freeze——与轮内停派「spec 保持 testing 可重试、
    # MUST NOT 冻结」的承诺直接冲突（人工面对的是需 unfreeze 的冻结态而非
    # 可重试 testing）。经 _judge_round_state 读旗标：轮次/判定上下文变化时
    # 它自动重置 escalated=False，合法新执行轮照常恢复计数与派发；已停派则
    # 直接让位返回，计数停增（首次升级告警已由置位时的 _judge_round_escalate
    # 发出，此处不复读避免逐次重复告警）。
    if _judge_round_state(pipeline, spec_name)["escalated"]:
        return False
    count = pipeline._judge_rerun_count(spec_name, delta=1)
    if count > _MAX_JUDGE_RERUNS:
        pipeline._judge_hard_cap_freeze(spec_name, count)
        return False
    if not is_verdict_stable(pipeline._context.project_root, spec_name):
        # ── 轮内重裁决阈值门（add-verify-lane-throughput 3.1）──
        # 治理对象是「同一份已落盘报告的反复重裁决」：report.json 缺失
        # （内存/合成执行环境、judge 前置产物未落盘）即无可治理的判定
        # 上下文，放行且不计数（spec 级硬上限仍然兜底）。
        if _judge_report_mtime_ns(pipeline, spec_name) is None:
            return None
        state = _judge_round_state(pipeline, spec_name)
        if state["real"] >= _JUDGE_ROUND_MAX_REAL_DISPATCHES:
            _judge_round_escalate(pipeline, spec_name, state)
            return False
        _judge_charge_real_dispatch(pipeline, spec_name)
        return None
    # 稳定性复用命中 = fast-track 命中（design 决策 5：gate 返回合成结果即
    # 命中，不计入真实派发）。
    _judge_charge_fasttrack_hit(pipeline, spec_name)
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
    # code-fix 0eda9bae5886：改走 freeze_for_human 单一入口——原先裸
    # update_spec 置 blocked 无 frozen 结构化标记、error 亦无 FREEZE_ERROR_
    # PREFIX，blocked_stuck 看门狗的三选一豁免（frozen 字段 / 'frozen:'
    # 前缀 / '用户指令' 子串）全不命中，声称「等待人工裁决」却会被自动派
    # admin run。frozen 与人工升级告警经该入口成对落盘；升级通道自身失败
    # 不得抛穿裁决流程（code-review item 7e0509f14fdd 语义）由
    # freeze_for_human 内部容错承接（告警失败记 WARNING、不回滚冻结）。
    pipeline._context.state_machine.freeze_for_human(
        spec_name,
        error=(
            f"judge 重跑超上限（{count}/{_MAX_JUDGE_RERUNS} 轮）— 已冻结"
            f"等待人工裁决。详见 `spec/changes/{spec_name}/verification-report.md`"
        ),
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
        alert_callback=pipeline._context.escalation_notifier,
        extra_updates={"_judge_cap_frozen": True},
    )
    pipeline._context.logger.error(
        "pm_engine",
        f"judge 重跑硬上限 '{spec_name}'（{count} 轮）— " f"冻结为 blocked，等待人工裁决",
    )


def _judge_rerun_count(pipeline, spec_name: str, delta: int = 0) -> int:
    """STATE.md 读取/增量 ``_judge_rerun_count``（判据与 _verify_fail_rounds 正交）。

    judge 派发决策（含被稳定性复用跳过但未实际派发的判定次数）在派发处
    delta=+1 递增；读到 ``_judge_cap_frozen`` 冻结标记时强制不再递增
    （hard cap 触发后 judge 侧计数器冻结，与 _verify_fail_rounds 一并冻结）。
    """
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    frozen = delta and entry.get("_judge_cap_frozen")
    count = 0
    try:
        count = int(entry.get("_judge_rerun_count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    if frozen:
        # 冻结早退：复用上方受保护转换（脏值按 0 兜底），不再递增
        return count
    if delta:
        # 锁内原子递增（与 _judge_round_bump 同款）：锁外快照读改写会与
        # 其它对同字段的写者（verified 归零、admin 重置清零）互相覆盖丢
        # 增量，使 hard cap 阈值失真。
        return pipeline._context.state_machine.bump_counters(
            spec_name, {"_judge_rerun_count": delta}
        ).get("_judge_rerun_count", 0)
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
        # fix-verify-late-result-terminal-clobber D3：补来源戳——读侧
        # _verifier_result_is_stale/_read_verdict 对 role 缺失一律判不采信，
        # 快道产物缺 role 戳会使同 SPEC 在飞 LLM verifier 完成时必然被拒
        # （2026-09-24 事故误判土壤）。mechanical: true 保留机械来源可辨识。
        "role": "verifier",
        "bugs": [],
        "summary": text,
        "mechanical": True,
    }
    try:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写（对齐 _copyback_run_result 的 _write_atomic 手法）：同目录
        # 临时文件 + os.replace，写盘瞬间读侧（Dashboard 轮询）不会读到半截 JSON。
        fd, tmp_name = tempfile.mkstemp(
            prefix=".fenix-run-result.", suffix=".tmp", dir=str(result_path.parent)
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, indent=1))
            os.replace(tmp_path, result_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
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
                # 逐行流式读（jsonl 转录可达数十 MB）：只取最后一条
                # type=result 的 duration，整文件 read_text+splitlines 会在
                # 告警旁路上造成不必要的全量内存峰值（code-review
                # cd65b5bb8a0c）。
                with open(last, encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
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
    try:
        payload = {
            "reason": str(reason or ""),
            "run_id": str(run_id or ""),
            "duration_seconds": (float(duration_seconds or 0) if duration_seconds else 0.0),
            "cost_usd": (float(cost_usd) if cost_usd is not None else None),
            "degraded_at": datetime.now(timezone.utc).isoformat(),
        }
        ctx_path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写（mkstemp + os.replace，复用 scenario_gate.atomic_write_text）：
        # daemon 中途被杀不留半截 JSON——该文件会被 verify_report 合成路径
        # （G3 降级标注）回读（code-review 2bb2844a51f2，对齐 _all_green_fast_path）。
        atomic_write_text(
            ctx_path,
            json.dumps(payload, ensure_ascii=False, indent=2),
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
