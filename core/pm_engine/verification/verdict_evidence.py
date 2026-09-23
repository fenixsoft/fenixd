"""core.pm_engine.verification.verdict_evidence — 裁决证据/重合成族（refactor-verification-module D2）。

从 VerificationPipeline 摘出的裁决证据校验（_verify_verdict_evidence / violations）、
重合成指令读写（resynthesis 族 9 项）、裁决采纳记账、verdict 缓存持久化、
verified 结果持久化门禁。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from core.agent_runner.runner import FROZEN_TERMINATED_ERROR_PREFIX
from core.verify_engine.judge_files import ATTRIBUTION_STATUS_ACCEPT, ATTRIBUTION_STATUS_REQUEUE

# resynthesis 指令文件名与重合成预算（随组迁移）
_RESYNTHESIS_DIRECTIVE_FILENAME = "dedup_resynthesis_directive.json"
_RESYNTHESIS_MAX_ATTEMPTS = 2
from typing import Optional


def _verify_verdict_evidence(pipeline, spec_name: str, retry_judge: bool = False) -> dict:
    """确定性校验裁决 report.json 的分类/证据合规，并按映射强制重写 status。

    流程（design D1-D3，fix-verdict-retry-misattribution D1）：
      1. 读 report.json（judge 应在其中增强 classification/evidence）；
      2. validate_report：每个非 PASS 场景 MUST 有合法 classification + 非空 evidence；
      3. 不合规且 ``retry_judge`` 为真 → 走既有 judge 重试一次（同 run_planner 调用），
         重试后再次校验；二次仍不合规 → 返回 ``cause=violations``（调用方
         blocked-env + 告警，与 verify-report-gate 阻断语义一致，宁可不推进也不
         带病采纳）。合规后按分类-状态映射强制重写 status（D3），原子写回
         report.json。
      4. 返回结构化结果 ``{"ok", "cause", "violations", "dispatch_error"}``：
         cause ∈ pass / violations / dispatch_frozen / dispatch_cancelled /
         dispatch_failed / dispatch_exception / report_missing。

    注意：judge 失败（process 级）已由调用方在 ``judge_result.success`` 处拦截，
    本方法只负责「judge 已成功但产物不合规」的确定性校验与重试。

    dispatch_frozen / dispatch_cancelled = 人工已接管（frozen 门/取消旗标拦截
    重试派发）→ 语义化返回供调用方静默让位（零写入零告警）；dispatch_exception
    = ``run_planner`` 抛异常立即早退，**禁止**落至 ``load_report`` 复读第一轮
    违规的旧文件（现路径假 ERROR 根除）。
    """
    from core.verdict_check import (
        validate_report,
        enforce_status_mapping,
        load_report,
        save_report,
    )

    report = load_report(pipeline._context.project_root, spec_name)
    if report is None:
        # 无 report.json：验证产物门禁（verify-report-gate）会兜底，此处不阻断
        # （不制造伪 violation），交由既有流程处理。
        return {"ok": True, "cause": "pass", "violations": [], "dispatch_error": ""}

    result = validate_report(report)
    if result["ok"]:
        # ── 归因分级门（add-verdict-credibility-gate / design D2）──
        # 框架侧机械计算 attribution_level，白屏方向约束强制改写分类；
        # 批量归因查重拒绝硬编码套用；缓存归因打新鲜度标。
        # 全部发生在报告落盘/打回上下文组装前（本方法即统一入口）。
        try:
            from core.verdict_check import (
                validate_attribution_levels,
                enforce_blank_screenshot_direction,
                check_batch_attribution_dedup_scenario,
                load_verdict_cache,
                tag_cached_attributions,
            )

            validate_attribution_levels(report)
            # 白屏方向约束：blank_screenshot 标签强制 env 方向
            for sc in report.get("scenarios") or []:
                if not isinstance(sc, dict):
                    continue
                new_cls = enforce_blank_screenshot_direction(sc)
                if new_cls:
                    old_cls = sc.get("classification")
                    sc["classification"] = new_cls
                    sc["blank_direction_forced"] = True
                    pipeline._context.logger.info(
                        "pm_engine",
                        f"白屏方向约束 '{spec_name}' 场景 "
                        f"{sc.get('scenario_id')}: classification "
                        f"'{old_cls}' → '{new_cls}'（blank_screenshot 标签强制 env 方向）",
                    )
            # 批量归因查重：≥3 场景逐字相同 → 场景级判定（add-judge-
            # incremental-attribution 2.1：命中重复的归因置 requeue 待回炉，
            # 非重复置 accept 保留；MUST NOT 因子集重复废弃整轮归因）。
            dedup = check_batch_attribution_dedup_scenario(report)
            if not dedup["ok"]:
                for v in dedup["violations"]:
                    sids = v.get("scenario_ids") or []
                    pipeline._context.logger.error(
                        "pm_engine",
                        f"批量归因查重拒绝采纳 '{spec_name}': {v.get('reason')}",
                    )
                # 场景级回炉闭环：标记 requeue/accept 状态 + 回炉清单 →
                # 派发重合成（仅重做 requeue 子集）→ 回灌校验（fix-verdict-
                # dedup-resynthesis D1/D2；返回 cause=pass 已闭环采纳）
                return pipeline._handle_scenario_requeue(spec_name, report, dedup)
            # 跨轮缓存归因打标（design D3 / Task 3.1）
            cache = load_verdict_cache(pipeline._context.project_root, spec_name)
            tagged = tag_cached_attributions(report, cache, spec_name)
            if tagged:
                pipeline._context.logger.info(
                    "pm_engine",
                    f"跨轮缓存归因打标 '{spec_name}': "
                    f"{len(tagged)} 个场景带 cached_from_previous_round 标",
                )
        except Exception as e:
            # 归因分级自身异常不阻断既有裁决链（分级是附加治理，宁可缺失
            # 也不让增强流程因治理代码崩溃——judge 正常裁决继续）
            pipeline._context.logger.warning(
                "pm_engine",
                f"归因分级校验异常跳过 '{spec_name}'（不阻断裁决）: " f"{type(e).__name__}: {e}",
            )
        # 合规：清掉历史驳回清单（若有）后强制重写 status 映射（D3）写回
        pipeline._clear_verdict_violations(spec_name)
        pipeline._clear_requeue_manifest(spec_name)
        pipeline._persist_verdict_cache(spec_name, report)
        mapping = enforce_status_mapping(report)
        if mapping["corrected"]:
            try:
                save_report(pipeline._context.project_root, spec_name, report)
            except OSError as e:
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"裁决映射重写写回失败 '{spec_name}': {e}",
                )
            for c in mapping["corrected"]:
                pipeline._context.logger.info(
                    "pm_engine",
                    f"裁决映射强制重写 '{spec_name}' 场景 {c['scenario_id']}: "
                    f"{c['from_status']} → failed ({c['classification']})",
                )
        return {"ok": True, "cause": "pass", "violations": [], "dispatch_error": ""}

    # 一次不合规：judge 重试一次（design D2）；违规明细落盘供重试 prompt 注入
    if retry_judge:
        violations_1 = result["violations"]
        pipeline._write_verdict_violations(spec_name, violations_1)
        # ── 轮内重裁决记账（add-verify-lane-throughput 3.1/3.2）──
        # 此路径直接 run_planner 不经 _judge_dispatch_gate，轮内计数在此记账：
        # 全为可补类型（evidence 缺失/截断）→ 证据扩充（每轮 1 次，不计重派）；
        # 否则记真实派发（轮内达阈值即由 gate 在下次派发前停派+升级）。
        retry_kind = pipeline._judge_charge_verdict_retry(spec_name, violations_1)
        pipeline._context.logger.warning(
            "pm_engine",
            f"裁决证据分类校验未通过 '{spec_name}'（{len(violations_1)} 项，"
            f"记账={retry_kind}），重试 judge 一次："
            f"{[v['scenario_id'] for v in violations_1]}",
        )
        try:
            re_judge = pipeline._pm.agent_runner.run_planner(spec_name, "judge")
        except Exception as e:
            # dispatch_exception：run_planner 抛异常（re_judge=None）→ 立即早退。
            # 禁止继续执行 load_report 复读第一轮违规的旧 report.json（现路径
            # 会据此打出「重试后仍不合规」假 ERROR）；是否写 blocked 由调用方
            # 按 cause 决定。
            pipeline._context.logger.warning(
                "pm_engine",
                f"裁决重试 judge 异常 '{spec_name}': {e}",
            )
            return {
                "ok": False,
                "cause": "dispatch_exception",
                "violations": violations_1,
                "dispatch_error": str(e),
            }
        if re_judge is not None and not re_judge.success:
            # ── 重试派发失败三分支（fix-verdict-retry-misattribution）──
            # frozen 门拦截：spec 已人工冻结 → 让位（不写 blocked、不发告警），
            # 语义化返回供调用方 INFO 留痕。判据与 runner.py 门共用导出常量。
            if (re_judge.error or "").startswith(FROZEN_TERMINATED_ERROR_PREFIX):
                pipeline._context.logger.info(
                    "pm_engine",
                    f"裁决重试 judge 派发被 frozen 门拦截 '{spec_name}'"
                    f"（人工已冻结，让位不写状态）: {re_judge.error}",
                )
                return {
                    "ok": False,
                    "cause": "dispatch_frozen",
                    "violations": violations_1,
                    "dispatch_error": re_judge.error,
                }
            # 取消旗标拦截：结构化字段判定（非字符串匹配，design D3）→ 同语义让位
            if getattr(re_judge, "cancelled", False):
                pipeline._context.logger.info(
                    "pm_engine",
                    f"裁决重试 judge 派发被取消旗标拦截 '{spec_name}'"
                    f"（run 已人工取消，让位不写状态）: {re_judge.error}",
                )
                return {
                    "ok": False,
                    "cause": "dispatch_cancelled",
                    "violations": violations_1,
                    "dispatch_error": re_judge.error,
                }
            # 其它派发失败（网关拒绝/预算闸门等）：携带原始 error，由调用方按
            # dispatch_failed 温和处置——不得冒充「二次违反证据契约」。
            pipeline._context.logger.warning(
                "pm_engine",
                f"裁决重试 judge 派发失败 '{spec_name}': {re_judge.error}",
            )
            return {
                "ok": False,
                "cause": "dispatch_failed",
                "violations": violations_1,
                "dispatch_error": re_judge.error,
            }
        report2 = load_report(pipeline._context.project_root, spec_name)
        if report2 is None:
            # 重试成功但 report.json 不可读 → report_missing（产物丢失，非违规）
            return {
                "ok": False,
                "cause": "report_missing",
                "violations": violations_1,
                "dispatch_error": "",
            }
        result2 = validate_report(report2)
        if result2["ok"]:
            # ── 归因分级门（重试轮同样执行，design D2 统一入口）──
            try:
                from core.verdict_check import (
                    validate_attribution_levels,
                    enforce_blank_screenshot_direction,
                    check_batch_attribution_dedup_scenario,
                    load_verdict_cache,
                    tag_cached_attributions,
                )

                validate_attribution_levels(report2)
                for sc in report2.get("scenarios") or []:
                    if not isinstance(sc, dict):
                        continue
                    new_cls = enforce_blank_screenshot_direction(sc)
                    if new_cls:
                        old_cls = sc.get("classification")
                        sc["classification"] = new_cls
                        sc["blank_direction_forced"] = True
                        pipeline._context.logger.info(
                            "pm_engine",
                            f"白屏方向约束（重试轮）'{spec_name}' 场景 "
                            f"{sc.get('scenario_id')}: classification "
                            f"'{old_cls}' → '{new_cls}'（blank_screenshot 标签强制 env 方向）",
                        )
                dedup = check_batch_attribution_dedup_scenario(report2)
                if not dedup["ok"]:
                    for v in dedup["violations"]:
                        pipeline._context.logger.error(
                            "pm_engine",
                            f"批量归因查重拒绝采纳（重试轮）'{spec_name}': " f"{v.get('reason')}",
                        )
                    # 统一收口：场景级回炉闭环
                    return pipeline._handle_scenario_requeue(spec_name, report2, dedup)
                cache = load_verdict_cache(pipeline._context.project_root, spec_name)
                tagged = tag_cached_attributions(report2, cache, spec_name)
                if tagged:
                    pipeline._context.logger.info(
                        "pm_engine",
                        f"跨轮缓存归因打标（重试轮）'{spec_name}': "
                        f"{len(tagged)} 个场景带 cached_from_previous_round 标",
                    )
            except Exception as e:
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"归因分级校验异常跳过（重试轮）'{spec_name}'"
                    f"（不阻断裁决）: {type(e).__name__}: {e}",
                )
            pipeline._clear_verdict_violations(spec_name)
            pipeline._clear_requeue_manifest(spec_name)
            pipeline._persist_verdict_cache(spec_name, report2)
            mapping2 = enforce_status_mapping(report2)
            try:
                save_report(pipeline._context.project_root, spec_name, report2)
            except OSError as e:
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"裁决映射重写写回失败 '{spec_name}': {e}",
                )
            for c in mapping2["corrected"]:
                pipeline._context.logger.info(
                    "pm_engine",
                    f"裁决重试后映射强制重写 '{spec_name}' 场景 "
                    f"{c['scenario_id']}: {c['from_status']} → failed",
                )
            return {"ok": True, "cause": "pass", "violations": [], "dispatch_error": ""}
        # 真·二次违规（重试确实发生）：violations 携带 validate_report 原始明细，
        # 由调用方按既有语义处置（blocked + verdict_evidence_invalid 告警）。
        pipeline._context.logger.error(
            "pm_engine",
            f"裁决重试后证据分类仍不合规 '{spec_name}'："
            f"{[v['scenario_id'] for v in result2['violations']]}",
        )
        return {
            "ok": False,
            "cause": "violations",
            "violations": result2["violations"],
            "dispatch_error": "",
        }

    # 无重试预算的首轮不合规：按 violations 处置（调用方若未显式指定
    # retry_judge，语义即「首轮已违规」）。
    return {
        "ok": False,
        "cause": "violations",
        "violations": result["violations"],
        "dispatch_error": "",
    }


# ── 失败历史侧车（fix-verdict-retry-misattribution D6）────────────────
# `.fenix/verify-progress/<spec>/fail_history.json`：每轮裁决采纳失败时原子
# 追加 {round, cause_type, failed_scenarios}；spec 进入 verified 终态或升级
# 闸门告警消费后清空。写盘失败静默降级（缺侧车 → 升级告警分型 unknown），
# 不阻断升级闸门。
_FAIL_HISTORY_FILENAME = "fail_history.json"


def _verdict_violations_evidence(pipeline, spec_name: str, violations: list) -> str:
    """格式化 verdict_evidence_invalid 告警 evidence：携带结构化 violations 明细。

    fix-verdict-retry-misattribution D5：每条 `scenario_id + reason`，超过 20 条
    截断并注明总数——人工无需读 report.json 即可定位违规形状。
    """
    shown = [v for v in (violations or []) if isinstance(v, dict)][:20]
    parts = [
        f"spec={spec_name}",
        f"report=spec/changes/{spec_name}/verification-report.md",
        f"violations_total={len(violations or [])}",
    ]
    for v in shown:
        sid = v.get("scenario_id") or v.get("id") or "?"
        reason = str(v.get("reason") or "?").strip()
        parts.append(f"violation[scenario_id={sid}; reason={reason}]")
    if len(violations or []) > 20:
        parts.append(f"violations_truncated=20/{len(violations)}")
    return "; ".join(parts)


# ── 批量归因查重拒绝 → 重合成闭环（fix-verdict-dedup-resynthesis D1/D2）──
# 2026-09-10 事故解剖（proposal）：查重门拒绝后框架「保持 testing 等重合成」
# 但**不存在重合成回路**（不 requeue、不落盘违规清单、重试 prompt 收不到
# 查重要求）→ spec 卡 testing 170 分钟撞 stuck 阈值全量重跑。本闭环：
# 落盘违规清单 → 派发轻量重合成 judge run → 回灌同一校验入口 → 连续 2 次
# 重合成仍被拒 → blocked + admin 升级（MUST NOT 无限重试）。
_RESYNTHESIS_DIRECTIVE_FILENAME = "dedup_resynthesis_directive.json"
# 重合成预算：连续 2 轮重合成产物仍被查重拒绝 → 升级人工（design D2）。
_RESYNTHESIS_MAX_ATTEMPTS = 2


def _write_verdict_violations(pipeline, spec_name: str, violations: list) -> None:
    """落盘裁决驳回清单（verdict-rejection-retry：judge 重试幂等陷阱修复）。

    fix-budget-counting-semantics 复盘：judge 首轮补齐 classification/evidence
    但漏 assertion_triage，重试 judge 读到已增强的 report 后判定「无需改写」
    再次跳过，校验必然复败 → blocked。将违规明细落盘，由 agent_runner 注入
    重试 prompt（见 _verdict_rejection_section），告知重试 judge 缺口所在。
    """
    try:
        path = pipeline._verdict_violations_path(spec_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(violations, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"裁决驳回清单写盘失败 '{spec_name}': {e}",
        )


def _clear_verdict_violations(pipeline, spec_name: str) -> None:
    try:
        pipeline._verdict_violations_path(spec_name).unlink(missing_ok=True)
    except OSError:
        pass


def _verdict_violations_path(pipeline, spec_name: str) -> Path:
    return (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "verdict_violations.json"
    )


def _resynthesis_directive_path(pipeline, spec_name: str) -> Path:
    return (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / _RESYNTHESIS_DIRECTIVE_FILENAME
    )


def _read_resynthesis_directive(pipeline, spec_name: str) -> dict:
    """读取重合成指令（缺失/损坏返回 {}，fail-open）。"""
    try:
        path = pipeline._resynthesis_directive_path(spec_name)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _clear_resynthesis_directive(pipeline, spec_name: str) -> None:
    """合规采纳后清除重合成指令（防下轮误注入）。写失败静默。"""
    try:
        pipeline._resynthesis_directive_path(spec_name).unlink(missing_ok=True)
    except OSError:
        pass


def _resynthesis_directive_scenarios(pipeline, report: dict, violations: list) -> list:
    """提取被拒场景的差异化素材（重合成指令输入）。

    对违规组内每个 scenario_id，从 report 取：分类、状态、
    first_failed_step 原文、失败步骤序号、断言 label 清单——judge 改写
    归因文本时必须引用本场景局部数据（MUST NOT 套用共享模板串）。
    """
    from core.verdict_check import _extract_step_number

    involved = set()
    for v in violations or []:
        if not isinstance(v, dict):
            continue
        for sid in v.get("scenario_ids") or []:
            if sid:
                involved.add(str(sid))
    rows = []
    for sc in report.get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "")
        if sid not in involved:
            continue
        evidence = sc.get("evidence") or {}
        ffs_text = ""
        if isinstance(evidence, dict):
            ffs = evidence.get("first_failed_step") or ""
            if isinstance(ffs, str):
                ffs_text = ffs
        triage = sc.get("assertion_triage") or []
        labels = []
        if isinstance(triage, list):
            for t in triage:
                if isinstance(t, dict):
                    assertion = str(t.get("assertion") or "").strip()
                    if assertion:
                        labels.append(assertion)
        rows.append(
            {
                "scenario_id": sid,
                "classification": str(sc.get("classification") or ""),
                "status": str(sc.get("status") or ""),
                "first_failed_step": ffs_text,
                "failed_step_number": _extract_step_number(ffs_text),
                "assertion_labels": labels,
            }
        )
    return rows


def _write_resynthesis_directive(
    pipeline,
    spec_name: str,
    report: dict,
    violations: list,
    rejection_round: int,
    resynthesis_attempts: int,
) -> None:
    """写重合成指令文件（fix-verdict-dedup-resynthesis D1）。

    内容：被拒场景清单（scenario_ids + reason）、逐场景现有归因文本与
    框架已掌握的场景局部数据（失败步骤序号 / 断言 label）作为差异化素材、
    拒绝计数（rejection_round / resynthesis_attempts，独立轻量计数落在
    verify-progress 目录，不膨胀 STATE.md）。写失败静默降级（只影响
    重合成 prompt 注入，不阻断闭环）。
    """
    try:
        payload = {
            "spec": spec_name,
            "rejection_round": rejection_round,
            "resynthesis_attempts": resynthesis_attempts,
            "violations": violations,
            "scenarios": pipeline._resynthesis_directive_scenarios(report, violations),
        }
        path = pipeline._resynthesis_directive_path(spec_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=".resynth.", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
            os.replace(tmp_path, path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"重合成指令写盘失败 '{spec_name}': {e}",
        )


def _escalate_dedup_resynthesis(
    pipeline, spec_name: str, rejection_round: int, violations: list
) -> dict:
    """重合成预算耗尽（连续 2 轮重合成仍被拒）→ blocked + admin 升级告警。

    error 携带多轮违规摘要；spec 置 blocked 后自动链路对 status 的改写被
    update_spec 剥离（人工接管），MUST NOT 无限重试重合成。
    """
    summary = "; ".join(str(v.get("reason") or "")[:160] for v in (violations or []))
    error = (
        f"批量归因查重连续 {rejection_round} 次拒绝采纳"
        f"（含 {_RESYNTHESIS_MAX_ATTEMPTS} 轮轻量重合成仍同文），"
        f"已 blocked 等待人工裁决（违规摘要: {summary}）"
    )
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "status": "blocked",
            "error": error,
        },
    )
    pipeline._context.escalation_notifier(
        spec_name=spec_name,
        signal_type="verdict_dedup_resynthesis_exhausted",
        severity="critical",
        description=(
            f"'{spec_name}' 批量归因查重连续拒绝（含 {_RESYNTHESIS_MAX_ATTEMPTS} "
            f"轮轻量重合成）已 blocked，等待人工裁决"
        ),
        evidence=(f"spec={spec_name}; rejections={rejection_round}; " f"违规摘要: {summary}"),
        recommended_action=("人工核查归因模板偷懒或级联豁免误判；修正归因后解除 blocked"),
    )
    return {
        "ok": False,
        "cause": "batch_attribution_dedup",
        "violations": violations,
        "dispatch_error": "",
    }


def _handle_attr_dedup_rejection(
    pipeline, spec_name: str, report: dict, dedup_violations: list
) -> dict:
    """批量归因查重拒绝统一收口（首轮 + 重试轮共用）。

    ``_verify_verdict_evidence`` 的查重拒绝处（首轮 + 重试轮）全部经此闭环：
      1. 落盘违规清单（``_write_verdict_violations``，重试 prompt 经
         ``_verdict_rejection_section`` 注入定向修复纪律）+ 写
         ``dedup_resynthesis_directive.json``（重合成指令：被拒场景清单 +
         逐场景现有归因 + 步骤序号/断言 label 差异化素材）；
      2. 派发轻量重合成 judge run（``run_planner(spec_name, "judge")``——
         复用既有 judge 重试通道，frozen 门/取消旗标/stale-result 防护/产物
         硬门全部免费继承），只重写被拒场景的归因文本字段，不重做调查/复现；
      3. 重合成产物回灌完整校验链（load_report → validate_report → 归因
         分级门 → 查重门，与既有路径同源、非旁路），合规按既有语义采纳
         （清 violations + 清 directive + 状态映射重写 + 裁决缓存）；
      4. 重合成产物仍被查重拒绝 → 连续拒绝计数递增（directive 文件
         resynthesis_attempts 字段），达预算上限（2 轮）→ blocked +
         admin 升级告警，MUST NOT 无限重试。

    Returns:
        {"ok", "cause", "violations", "dispatch_error"}（与
        ``_verify_verdict_evidence`` 同契约；cause=pass 时重合成已闭环
        采纳，其余 cause 由调用方按既有语义处置）。
    """
    from core.verdict_check import (
        validate_report,
        enforce_status_mapping,
        load_report,
        save_report,
    )

    prior = pipeline._read_resynthesis_directive(spec_name)
    prior_attempts = int(prior.get("resynthesis_attempts") or 0) if isinstance(prior, dict) else 0
    rejection_round = int(prior.get("rejection_round") or 0) if isinstance(prior, dict) else 0
    rejection_round += 1

    # 1) 违规清单落盘（verdict_violations.json 通道，与既有校验违规同源）
    violations_entries = [
        {
            "scenario_ids": [str(s) for s in (v.get("scenario_ids") or [])],
            "reason": str(v.get("reason") or ""),
        }
        for v in (dedup_violations or [])
    ]
    pipeline._write_verdict_violations(spec_name, violations_entries)

    # 预算上限（design D2：连续 2 次重合成仍被拒 → 升级人工，MUST NOT 无限重试）
    if prior_attempts >= _RESYNTHESIS_MAX_ATTEMPTS:
        pipeline._context.logger.error(
            "pm_engine",
            f"批量归因查重拒绝采纳（重合成预算耗尽）'{spec_name}'（第 "
            f"{rejection_round} 次）— 升级 blocked 等待人工裁决",
        )
        return pipeline._escalate_dedup_resynthesis(spec_name, rejection_round, violations_entries)

    # 2) 重合成指令落盘（含差异化素材与拒绝计数：本轮派发计数 = prior + 1）
    pipeline._write_resynthesis_directive(
        spec_name,
        report,
        violations_entries,
        rejection_round=rejection_round,
        resynthesis_attempts=prior_attempts + 1,
    )
    pipeline._context.logger.warning(
        "pm_engine",
        f"批量归因查重拒绝采纳 '{spec_name}'（第 {rejection_round} 次，"
        f"已重合成 {prior_attempts} 轮）— 派发轻量重合成 judge run"
        f"（只重写被拒场景归因字段，禁止复现/调查/改判定）",
    )

    # 3) 派发重合成 judge（复用 judge 通道；异常立即早退，禁止复读旧 report）
    # 轮内记账（code-review item 15dff451de8b，judge_gate.py 调用点规则）：此
    # 路径直接 run_planner 不经 gate，与 verdict-retry 路径同口径记账——查重
    # 反复拒绝时轮内/全局重裁决计数必须增长，否则绕过轮内 2 次与
    # judge_rerun_count 上限治理（仅剩 _RESYNTHESIS_MAX_ATTEMPTS 独立兜底）。
    pipeline._judge_charge_verdict_retry(spec_name, violations_entries)
    try:
        re_judge = pipeline._pm.agent_runner.run_planner(spec_name, "judge")
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"重合成 judge 异常 '{spec_name}': {e}",
        )
        return {
            "ok": False,
            "cause": "dispatch_exception",
            "violations": violations_entries,
            "dispatch_error": str(e),
        }
    if re_judge is not None and not re_judge.success:
        if (re_judge.error or "").startswith(FROZEN_TERMINATED_ERROR_PREFIX):
            pipeline._context.logger.info(
                "pm_engine",
                f"重合成 judge 派发被 frozen 门拦截 '{spec_name}'"
                f"（人工已冻结，让位不写状态）: {re_judge.error}",
            )
            return {
                "ok": False,
                "cause": "dispatch_frozen",
                "violations": violations_entries,
                "dispatch_error": re_judge.error,
            }
        if getattr(re_judge, "cancelled", False):
            pipeline._context.logger.info(
                "pm_engine",
                f"重合成 judge 派发被取消旗标拦截 '{spec_name}'"
                f"（run 已人工取消，让位不写状态）: {re_judge.error}",
            )
            return {
                "ok": False,
                "cause": "dispatch_cancelled",
                "violations": violations_entries,
                "dispatch_error": re_judge.error,
            }
        pipeline._context.logger.warning(
            "pm_engine",
            f"重合成 judge 派发失败 '{spec_name}': {re_judge.error}",
        )
        return {
            "ok": False,
            "cause": "dispatch_failed",
            "violations": violations_entries,
            "dispatch_error": re_judge.error,
        }

    # 4) 重合成产物回灌完整校验链（与 _verify_verdict_evidence 既有路径同源）
    report2 = load_report(pipeline._context.project_root, spec_name)
    if report2 is None:
        return {
            "ok": False,
            "cause": "report_missing",
            "violations": violations_entries,
            "dispatch_error": "",
        }
    result2 = validate_report(report2)
    if not result2["ok"]:
        # 重合成产物在分类/证据层仍不合规（非查重）→ 既有「二次违规」处置
        pipeline._context.logger.error(
            "pm_engine",
            f"重合成产物证据分类仍不合规 '{spec_name}'："
            f"{[v['scenario_id'] for v in result2['violations']]}",
        )
        return {
            "ok": False,
            "cause": "violations",
            "violations": result2["violations"],
            "dispatch_error": "",
        }
    # 归因分级门 + 查重门（同一入口位，非旁路）
    try:
        from core.verdict_check import (
            validate_attribution_levels,
            enforce_blank_screenshot_direction,
            check_batch_attribution_dedup_scenario,
            load_verdict_cache,
            tag_cached_attributions,
        )

        validate_attribution_levels(report2)
        for sc in report2.get("scenarios") or []:
            if not isinstance(sc, dict):
                continue
            new_cls = enforce_blank_screenshot_direction(sc)
            if new_cls:
                old_cls = sc.get("classification")
                sc["classification"] = new_cls
                sc["blank_direction_forced"] = True
                pipeline._context.logger.info(
                    "pm_engine",
                    f"白屏方向约束（重合成）'{spec_name}' 场景 "
                    f"{sc.get('scenario_id')}: classification "
                    f"'{old_cls}' → '{new_cls}'（blank_screenshot 标签强制 env 方向）",
                )
        dedup2 = check_batch_attribution_dedup_scenario(report2)
        if not dedup2["ok"]:
            for v in dedup2["violations"]:
                pipeline._context.logger.error(
                    "pm_engine",
                    f"批量归因查重拒绝采纳（重合成轮）'{spec_name}': " f"{v.get('reason')}",
                )
            # 重合成产物再拒 → 递归进入下一轮场景级回炉（或达上限升级）
            return pipeline._handle_scenario_requeue(spec_name, report2, dedup2)
        cache = load_verdict_cache(pipeline._context.project_root, spec_name)
        tagged = tag_cached_attributions(report2, cache, spec_name)
        if tagged:
            pipeline._context.logger.info(
                "pm_engine",
                f"跨轮缓存归因打标（重合成）'{spec_name}': "
                f"{len(tagged)} 个场景带 cached_from_previous_round 标",
            )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"归因分级校验异常跳过（重合成）'{spec_name}'"
            f"（不阻断裁决）: {type(e).__name__}: {e}",
        )

    # 5) 合规采纳：清 violations + 清 directive + 清回炉清单 + 状态映射
    #    重写 + 裁决缓存
    pipeline._clear_verdict_violations(spec_name)
    pipeline._clear_resynthesis_directive(spec_name)
    pipeline._clear_requeue_manifest(spec_name)
    pipeline._persist_verdict_cache(spec_name, report2)
    mapping2 = enforce_status_mapping(report2)
    try:
        save_report(pipeline._context.project_root, spec_name, report2)
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"裁决映射重写写回失败 '{spec_name}': {e}",
        )
    for c in mapping2["corrected"]:
        pipeline._context.logger.info(
            "pm_engine",
            f"重合成采纳后映射强制重写 '{spec_name}' 场景 "
            f"{c['scenario_id']}: {c['from_status']} → failed",
        )
    pipeline._context.logger.warning(
        "pm_engine",
        f"重合成产物合规 '{spec_name}' — 已按既有语义采纳推进",
    )
    return {"ok": True, "cause": "pass", "violations": [], "dispatch_error": ""}


def _handle_scenario_requeue(pipeline, spec_name: str, report: dict, dedup: dict) -> dict:
    """场景级归因查重拒绝统一收口（add-judge-incremental-attribution 2.2 / D2-D3）。

    ``_verify_verdict_evidence`` 的查重拒绝处（首轮 + 重试轮 + 重合成轮）全部
    经此闭环。与 ``_handle_attr_dedup_rejection``（整批重合成）同构，但判定
    粒度降为场景（D2）：命中重复的归因置 ``requeue``，非重复置 ``accept``
    保留——MUST NOT 因子集重复废弃整轮已写盘归因。

    流程：
      1. 逐场景条目落盘（judge_attribution.json：id/attribution/status
         accept|requeue/timestamp）+ 回炉清单（requeue_manifest.json：
         requeue 子集清单）——已 accept 场景归因保留复用（design D2）；
      2. 回炉子集 = 全量（100% 重复，模板化硬编码）→ 记录全量回炉语境，
         escalation 告警沿既有预算路径照发（design D3：查重防御不弱化）；
      3. 部分重复 → 静默回炉子集：委托 ``_handle_attr_dedup_rejection``
         落盘违规清单 + 重合成指令（只含 requeue 子集差异化素材）→ 派发
         轻量重合成 judge run（只重做 requeue 子集）→ 回灌完整校验链；
         仍重复 → 预算内递归，达上限 blocked + admin 升级（MUST NOT 无限重试）。

    Returns:
        {"ok", "cause", "violations", "dispatch_error"}（与
        ``_verify_verdict_evidence`` 同契约）。
    """
    from core.verify_engine.judge_files import (
        save_attribution,
        build_requeue_manifest,
        ATTRIBUTION_STATUS_ACCEPT,
        ATTRIBUTION_STATUS_REQUEUE,
    )
    from core.verdict_check import scenario_attribution_summary

    requeue_ids = [str(s) for s in (dedup.get("requeue_ids") or [])]
    accept_ids = [str(s) for s in (dedup.get("accept_ids") or [])]
    counts = dedup.get("counts") or {}
    violations_entries = [
        {
            "scenario_ids": [str(s) for s in (v.get("scenario_ids") or [])],
            "reason": str(v.get("reason") or ""),
        }
        for v in (dedup.get("violations") or [])
    ]

    # 1) 逐场景条目落盘：从 report 非 PASS 场景提取归因摘要，按查重结果
    #    置 accept/requeue（写失败静默降级——judge_attribution.json 是
    #    审计/回炉状态文件，不阻断既有重合成闭环）。
    try:
        entries = []
        requeue_set = set(requeue_ids)
        for sc in report.get("scenarios") or []:
            if not isinstance(sc, dict):
                continue
            if sc.get("status") in ("pass", "passed"):
                continue
            sid = str(sc.get("scenario_id") or sc.get("id") or "")
            if not sid:
                continue
            entries.append(
                {
                    "id": sid,
                    "attribution": scenario_attribution_summary(sc),
                    "status": (
                        ATTRIBUTION_STATUS_REQUEUE
                        if sid in requeue_set
                        else ATTRIBUTION_STATUS_ACCEPT
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        if entries:
            save_attribution(pipeline._context.project_root, spec_name, entries)
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"judge_attribution.json 逐场景条目落盘失败 '{spec_name}'"
            f"（不阻断回炉闭环）: {type(e).__name__}: {e}",
        )

    # 2) 回炉清单落盘（requeue 子集驱动下轮 judge 只重做该子集）
    prior = pipeline._read_resynthesis_directive(spec_name)
    rejection_round = int(prior.get("rejection_round") or 0) if isinstance(prior, dict) else 0
    try:
        build_requeue_manifest(
            pipeline._context.project_root,
            spec_name,
            rejection_round=rejection_round + 1,
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"回炉清单落盘失败 '{spec_name}'（不阻断回炉闭环）: " f"{type(e).__name__}: {e}",
        )

    # 3) 全量重复（回炉子集 = 全量，模板化硬编码）→ 记录全量回炉语境，
    #    escalation 沿既有预算路径照发（design D3，防御语义不弱化；与
    #    整批拒绝 escalation 同源，预算耗尽时触发 _escalate_dedup_resynthesis）。
    is_full = (
        counts.get("total")
        and counts.get("requeue")
        and counts.get("requeue") >= counts.get("total")
    )
    if is_full:
        pipeline._context.logger.error(
            "pm_engine",
            f"批量归因查重拒绝采纳 '{spec_name}'（第 {rejection_round + 1} 次，"
            f"回炉子集=全量 {counts.get('requeue')}/{counts.get('total')} "
            f"100% 重复，模板化硬编码形态）— escalation 沿既有预算路径照发，"
            f"不静默回炉",
        )
    else:
        pipeline._context.logger.warning(
            "pm_engine",
            f"批量归因查重拒绝采纳 '{spec_name}'（第 {rejection_round + 1} 次，"
            f"回炉子集 {counts.get('requeue')}/{counts.get('total')}）— "
            f"已 accept 场景归因保留复用，派发轻量重合成只重做 requeue 子集",
        )

    # 4) 委托既有重合成闭环（违规清单 + directive + 重合成 judge + 回灌
    #    校验 + 预算升级全部免费继承；重合成轮再拒经场景级递归回此方法）
    return pipeline._handle_attr_dedup_rejection(spec_name, report, violations_entries)


def _clear_requeue_manifest(pipeline, spec_name: str) -> None:
    """合规采纳后清除回炉清单（add-judge-incremental-attribution 2.2）。

    场景级回炉闭环完成（整轮查重校验通过）后清理，防下轮误注入；写失败
    静默（manifest 缺失只导致下轮零注入，不影响裁决正确性）。
    """
    try:
        from core.verify_engine.judge_files import clear_requeue_manifest

        clear_requeue_manifest(pipeline._context.project_root, spec_name)
    except OSError:
        pass


def _record_verdict_adoption(pipeline, spec_name: str, status: str, report=None) -> None:
    """裁决采纳后落盘 verdict 稳定性轮次 + STATE.md 增量时间线记账（R1/R3）。

    report 为 None 时按空失败集记录；成功时同步 STATE.md 的
    judge_rerun_count 镜像与本次验证链 token 增量（token 源复用
    verify_report._sum_verify_chain_tokens / tokens.json）。
    """
    from core.verify_report import (
        record_verdict_round,
        verdict_failed_ids,
        _sum_verify_chain_tokens,
    )

    failed_ids = verdict_failed_ids(report) if isinstance(report, dict) else []
    record_verdict_round(pipeline._context.project_root, spec_name, status, failed_ids)
    # STATE.md 增量时间线：本次 token 增量（累计 - 上次基线）
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    prev_raw = entry.get("_judge_token_baseline")
    try:
        prev = json.loads(prev_raw) if prev_raw else None
    except (TypeError, ValueError):
        # fix-deferred-findings 健壮性：坏 baseline 不再静默 fallback——
        # 保留 fallback 行为（prev=None，差量按当前累计全额记账），补告警。
        pipeline._context.logger.warning(
            "pm_engine",
            f"'{spec_name}' _judge_token_baseline 非合法 JSON（{prev_raw!r}），"
            "回退按当前累计全额记账",
        )
        prev = None
    cur = _sum_verify_chain_tokens(pipeline._context.project_root, spec_name)
    if cur:
        delta = {
            "input": max(0, cur["input"] - int((prev or {}).get("input", 0) or 0)),
            "output": max(0, cur["output"] - int((prev or {}).get("output", 0) or 0)),
        }
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "_judge_token_delta": json.dumps(delta, ensure_ascii=False),
                "_judge_token_baseline": json.dumps(cur, ensure_ascii=False),
            },
        )
    # verified 落定 = judge 重跑窗口关闭：judge_rerun_count 归零并解除
    # hard cap 冻结标记（与 _verify_fail_rounds 的清零点对齐，D1 同语义）；
    # 打回轮（bug-found）不清零——失败链中计数跨轮累计直至上限。
    if status == "verified":
        from core.state_machine import SCENARIO_REPAIR_EXHAUSTED_FIELD

        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "_judge_rerun_count": 0,
                "_judge_cap_frozen": False,
                # fix-recovery-path-blockers D4：场景原地修复预算耗尽轮次与
                # _judge_rerun_count 同生命周期——verified 落定清零，使成功
                # 后的新一轮验证重新获得「首次耗尽排程重验」的完整体验。
                SCENARIO_REPAIR_EXHAUSTED_FIELD: 0,
            },
        )


def _def_view(sc) -> dict:
    """场景定义视图归一：TestScenario（to_dict）与 dict 两形态统一为 dict。

    与 pipeline._parallel_plan_scenario_def 同口径（此处鸭子类型内联实现，
    避免模块级回引 pipeline 造成循环导入）。
    """
    if isinstance(sc, dict):
        return sc
    try:
        return sc.to_dict()
    except Exception:  # noqa: BLE001 — 异常形态返回空视图（fail-closed）
        return {}


def _round_definition_fingerprints(pipeline, spec_name: str) -> dict:
    """本轮定义指纹表（add-verify-lane-throughput 4.1 写读两侧同源）。

    写侧唯一可靠的定义源是本轮**冻结场景文件**：引擎判定 dict 只携带
    scenario_id/description/kind，steps/assertions 已不可考，直接对判定 dict
    取定义指纹会与读侧（prune 从同一文件 load 的 TestScenario.to_dict 投影）
    键集失配、四元组永不匹配、裁剪恒失效。重放同一冻结文件 ⇒ 两侧同形。

    重放失败返回空表（fail-closed：PASS 条目无 dfp 不入缓存，只损失效率
    不损正确性——缓存缺失只导致下轮全量重跑）。
    """
    from core.verify_engine.scenarios import load_scenarios
    from core.verdict_check import scenario_definition_fingerprint

    path = (
        Path(pipeline._context.project_root)
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "test_scenarios.json"
    )
    try:
        scenarios = load_scenarios(path)
    except Exception:  # noqa: BLE001
        return {}
    by_sid: dict = {}
    for i, sc in enumerate(scenarios or []):
        if sc is None:
            continue
        d = _def_view(sc)
        if not d:
            continue
        sid = str(d.get("scenario_id") or d.get("id") or f"#{i}")
        by_sid[sid] = scenario_definition_fingerprint(d)
    return by_sid


def _persist_verdict_cache(pipeline, spec_name: str, report: dict) -> None:
    """采纳成功后持久化跨轮裁决缓存（judge 效率治理 E，2026-09-06）。

    每个 non-PASS 已裁决场景记 {fingerprint, classification, evidence,
    assertion_triage}；下轮派发 judge 前由 prompt_builder 按指纹命中注入，
    命中场景免复现。

    add-verify-lane-throughput 4.1（design 决策 6）：PASS 场景同样入缓存
    （写侧此前显式跳过 pass——读侧「通过场景采信缓存」无数据可采信），
    条目补齐缓存键四元组分量（definition_fingerprint / build_fingerprint /
    verify_config_fingerprint，写入时计算）；non-PASS 条目一并补齐分量供
    后续消费。每轮整体重写（场景消失/变化自然出清）；分量计算失败落 ""，
    消费侧校验对 "" 一律不采信（fail-closed）；写盘失败静默（fail-open，
    缓存缺失只导致下轮全量重跑，不影响正确性）。
    """
    from core.verdict_check import (
        compute_build_fingerprint,
        compute_verify_config_fingerprint,
        scenario_fingerprint,
        save_verdict_cache,
    )

    project_root = pipeline._context.project_root
    build_fp = compute_build_fingerprint(project_root)
    config_fp = compute_verify_config_fingerprint(project_root)
    # 定义指纹从冻结场景文件重放（写读同源），不从判定 dict 取——判定 dict
    # 缺 steps/assertions 等定义键，投影与读侧失配（见 _round_definition_fingerprints）
    dfp_by_sid = _round_definition_fingerprints(pipeline, spec_name)
    cache = {}
    for sc in report.get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("scenario_id"))
        if sc.get("status") in ("pass", "passed"):
            # PASS 条目：无需 classification/evidence，采信判据只看四元组
            dfp = dfp_by_sid.get(sid, "")
            if not dfp:
                continue
            cache[sid] = {
                "status": "pass",
                "definition_fingerprint": dfp,
                "build_fingerprint": build_fp,
                "verify_config_fingerprint": config_fp,
            }
            continue
        cls = sc.get("classification")
        if not cls:
            continue  # 未裁决条目不入缓存
        fp = scenario_fingerprint(sc)
        if not fp:
            continue
        cache[sid] = {
            "fingerprint": fp,
            "classification": cls,
            "evidence": sc.get("evidence"),
            "assertion_triage": sc.get("assertion_triage"),
            "definition_fingerprint": dfp_by_sid.get(sid, ""),
            "build_fingerprint": build_fp,
            "verify_config_fingerprint": config_fp,
        }
    save_verdict_cache(project_root, spec_name, cache)
    if cache:
        pipeline._context.logger.info(
            "pm_engine",
            f"跨轮裁决缓存已更新 '{spec_name}': {len(cache)} 个场景结论入缓存"
            f"（四元组分量 build={'✓' if build_fp else '✗'}/"
            f"config={'✓' if config_fp else '✗'}）",
        )


def _verified_verdict_persisted(pipeline, spec_name: str) -> bool:
    """该 spec 是否已落盘 verified 且场景集未变（verified 门判据，R2）。

    数据源 = ``.fenix/verify-progress/<spec>/verdict_stability.json``
    （框架自有裁决持久化，**不被主树共享 .fenix-run-result.json 的
    implementer status=success 残留污染**——共享文件读侧会把残留当验证
    裁决，verified 门必须依赖自有缓存而非共享文件）：

    最近一轮裁决为 verified 且当前 spec 戳（spec.md+scenarios.json 哈希）
    与落盘戳一致（场景集未变）→ True。
    """
    from core.verify_report import (
        read_verdict_stability,
        compute_spec_stamp,
    )

    data = read_verdict_stability(pipeline._context.project_root, spec_name)
    if not isinstance(data, dict):
        return False
    rounds = data.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return False
    latest = rounds[-1]
    if not isinstance(latest, dict) or latest.get("status") != "verified":
        return False
    current_stamp = compute_spec_stamp(pipeline._context.project_root, spec_name)
    if not current_stamp:
        return False
    return current_stamp == data.get("stamp")


def _verified_gate_refuses(pipeline, spec_name: str, target: str) -> bool:
    """verified 一次性放行门：已 verified 且场景集未变 → 拒绝降级为 target。

    在裁决应用出口（bug-found 打回 / blocked 升级前）调用。返回 True =
    已拒绝（调用方应 return，不推进降级迁移）；返回 False = 无 verified
    缓存或场景集已变，正常流程。
    """
    if not pipeline._verified_verdict_persisted(spec_name):
        return False
    pipeline._context.logger.warning(
        "pm_engine",
        f"verified 放行门: '{spec_name}' 已 verified 且场景集未变，"
        f"拒绝被覆盖为 {target}（judge-rerun-stability R2，一次性放行）",
    )
    return True
