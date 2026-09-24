"""legacy.py — core.pm_engine.verification.legacy：legacy 验证回退（refactor-verification-module D2）。

从 VerificationPipeline 摘出的降级方案入口 `_run_legacy_verification`：使用旧版
单体 Verifier Agent 的三阶段验证回退。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path
from core.state_machine import ENV_BLOCK_ROUNDS_FIELD, VERIFY_INFRA_ROUNDS_FIELD


def _run_legacy_verification(pipeline, spec_name: str):
    """降级方案：使用旧版单体 Verifier Agent。"""
    # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）：入口状态
    # 非 testing → DEBUG 丢弃（注明当前状态），不执行任何迁移/回退/重派。
    _entry_status = (pipeline._context.state_machine.read_one(spec_name) or {}).get("status", "")
    if _entry_status != "testing":
        pipeline._context.logger.debug(
            "pm_engine",
            f"Verify result discarded for '{spec_name}': spec is "
            f"'{_entry_status}', not testing at legacy pipeline entry — dropped",
        )
        return

    result = pipeline._pm.agent_runner.run_verifier(spec_name)

    # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
    # 熔断期 verifier 派发失败属「provider 故障」，不是真实验证失败：
    # 不得 transition bug-found / 调用 _on_spec_bug_found（否则会派生伪 fix
    # 级联，与 implementer 路径的 fix-fix-stashpop-deadlock 同理）。保持 spec
    # 在 implemented（由 full_scan recovery 兜底重排），写入 error 供 dashboard 可见。
    # 判定用 `is True`（修复验证轮 BUG：MagicMock 替身自动生成 truthy 属性，
    # 裸布尔会把非冻结替身结果误判为冻结终止）；生产结果 frozen_terminated
    # 为显式 bool。
    if getattr(result, "frozen_terminated", False) is True:
        # ── 冻结终止 hold-state（add-freeze-stop-inflight-agents 3.4）──
        # verifier run 因 spec 冻结被终止：独立保持分支，在 cancelled 分支
        # 之前（spec 级 > run 级）。写 _frozen_hold 标记 + error、保持原
        # status（testing/blocked），不复用取消的 _cancelled_hold 路径。
        v_err = result.error or ""
        frozen_err = (
            f"verifier run 因 spec 冻结被终止（进度已保全，解冻后续做）"
            f"{': ' + v_err if v_err else ''}"
        )
        pipeline._context.state_machine.mark_frozen_hold(
            spec_name, frozen_err)
        pipeline._context.logger.warning(
            "pm_engine",
            f"Verifier run 因 spec 冻结被终止 — hold-state '{spec_name}' "
            f"(保持原状): {frozen_err}",
        )
        return
    if getattr(result, "cancelled", False):
        # ── 人工取消 hold-state（add-run-cancel D4，legacy verifier）──
        # verifier run 被取消：spec 保持 testing 原状，只写 error，
        # 不流转 bug-found、不入队重派。
        v_err = result.error or ""
        cancelled_err = f"run 被人工取消：{v_err}" if v_err else "run 被人工取消"
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "error": cancelled_err,
                # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                "_cancelled_hold": True,
            },
        )
        pipeline._context.logger.warning(
            "pm_engine",
            f"Verifier run 被人工取消 — hold-state '{spec_name}' "
            f"(保持 testing): {cancelled_err}",
        )
        return
    if pipeline._verifier_error_is_infra(result.error):
        # 基础设施类失败（熔断/链耗尽/网关切换类错误）＝「验证没能发生」，
        # 不是「验证发现了缺陷」：保持当前状态不流转 bug-found、不派生 fix
        # （2026-08-28 chain_exhausted 误产空壳 fix 实证），由 full_scan
        # recovery 兜底重排；冷却到期后下一次扫描即恢复验证。
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "error": result.error,
            },
        )
        # evo-infra-failure-budget-exempt R2：legacy provider 熔断门是
        # 归因入口前的既有 infra 判定点，必须同挂预算退款与记账（否则
        # provider infra 轮仍耗实现预算，与「基础设施失败不消耗实现预算」
        # 目标不符）。
        pipeline._record_infra_failure(
            spec_name,
            result.error,
            run_id=getattr(result, "run_id", "") or "",
        )
        pipeline._context.logger.warning(
            "pm_engine",
            f"Verifier infra failure — holding '{spec_name}' state, "
            f"no bug-found: {result.error}",
        )
        return

    if result.success:
        # 环境性失联门禁（legacy 路径同样生效）：旧版 verifier 若在 report.json
        # 中标记了 blocked-env 且全批环境性失联，则同样判定 inconclusive 重派，
        # 不判 bug-found（防假阴性派生 fix 家族）。
        report = pipeline._read_verify_report(spec_name)
        if pipeline._handle_env_blocked_inconclusive(spec_name, report):
            return
        # evo-verifier-result-single-source R1（legacy 同门）：结果文件
        # 读取统一走 _read_verdict 入口——verify-progress/<spec>/
        # .fenix-run-result.json 优先（旧版 verifier 的确定性产物路径），
        # 回退主树共享 .fenix/.fenix-run-result.json 且须先过 role/spec 戳
        # 校验：role≠verifier/缺 role 的主树共享文件一律不采信（implementer
        # 残留 status=success/error / 旧格式遗留），修复 _verifier_result_is_stale
        # 的 run_id fail-open（run_id 不匹配 ``-\d{10,}-a\d+$`` 时旧行为
        # 不判陈旧，残留仍落 blocked 分支——add-web-ui 误判链实证）。
        verifier_result = pipeline._read_verdict(spec_name)
        verifier_status = verifier_result.status if verifier_result.ok else None
        # 陈旧/归属护栏所需路径（与 _read_verdict 同源解析：primary
        # 优先，缺失回退共享文件——_verifier_result_is_stale 据此检测
        # mtime 陈旧/spec 戳不符）。fix-deferred-findings 整洁类：路径解析
        # 经 _verify_progress_result_paths 收敛（与 report_gate 同源）。
        from core.pm_engine.verification.report_gate import _verify_progress_result_paths

        primary, fallback = _verify_progress_result_paths(pipeline, spec_name)
        run_result_path = primary if primary.exists() else fallback
        # fix-verdict-read-failclosed D5（legacy 同门）：旧版 verifier 结果不可读
        # （缺失/非法 JSON/白名单外）→ blocked + critical 告警，绝不晋级
        # verified。legacy 是降级通道（三阶段两连败才进），结果不可读说明结构性
        # 异常而非偶发——自动重派整轮 verifier 只会烧钱，交人工。例外：status 白
        # 名单外（如 implementer 共享残留的 "success"）文件本身可读，须先走既有
        # 陈旧/归属护栏（foreign-spec 残留 → re-dispatch）再决定 blocked。
        if not verifier_result.ok:
            if verifier_result.reason in ("foreign-role", "foreign-stamp"):
                # _read_verdict 已定性：主树共享文件 role≠verifier/缺 role
                # （implementer 残留 status=success 等）或 spec 戳不符——
                # 文件可读但归属不明，一律不采信为验证裁决，走 stale/foreign
                # 护栏 re-dispatch 不 blocked（修复 _verifier_result_is_stale
                # 的 run_id fail-open：run_id 不匹配 -\d{10,}-a\d+$ 时旧行为
                # 不判陈旧，残留 status=success 仍落 blocked——add-web-ui
                # 误判链实证）。已 verified 且场景集未变时放行门继续拒绝
                # 覆盖（裁决仍以 verdict_stability.json 为准）。
                if pipeline._verified_gate_refuses(spec_name, "implemented"):
                    return
                pipeline._context.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "implemented",
                        "tester_run": None,
                        "error": (
                            "stale/foreign verifier result replayed"
                            " — re-dispatching fresh verify"
                        ),
                    },
                )
                # evo-infra-failure-budget-exempt R2：与 unknown-status stale /
                # 主 stale 护栏同结局路径对齐，「读错文件」属 infra，同挂预算
                # 退款与记账（否则本路径白耗实现预算且无 infra 记账可观测）。
                pipeline._record_infra_failure(
                    spec_name,
                    "stale/foreign verifier result replayed",
                    run_id=getattr(result, "run_id", "") or "",
                )
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"Stale/foreign verifier result for '{spec_name}'"
                    f"（reason={verifier_result.reason}）— "
                    f"re-dispatching fresh verification",
                )
                return
            if verifier_result.reason == "unknown-status":
                # 白名单外 status：文件可读，可能是共享文件中的其它 spec 残留
                # 或 implementer 残留——走既有陈旧/归属护栏（检测 spec stamp
                # 不符 / mtime 陈旧），foreign → re-dispatch 不 blocked。
                if pipeline._verifier_result_is_stale(result, run_result_path, spec_name):
                    pipeline._context.state_machine.update_spec(
                        spec_name,
                        {
                            "status": "implemented",
                            "tester_run": None,
                            "error": (
                                "stale/foreign verifier result replayed"
                                " — re-dispatching fresh verify"
                            ),
                        },
                    )
                    # evo-infra-failure-budget-exempt R2：结果文件「读错文件」
                    # （陈旧/异 spec 归属）属 infra，沿用既有 re-dispatch，
                    # 同挂预算退款与记账。
                    pipeline._record_infra_failure(
                        spec_name,
                        "stale/foreign verifier result replayed",
                        run_id=getattr(result, "run_id", "") or "",
                    )
                    pipeline._context.logger.warning(
                        "pm_engine",
                        f"Stale/foreign verifier result for '{spec_name}' — "
                        f"re-dispatching fresh verification",
                    )
                    return
                # 文件属当前 spec 且 mtime 新鲜，但 status 白名单外 → blocked
                # ── verified 一次性放行门（judge-rerun-stability R2）──
                # 「legacy unknown-status 不得改判」：已 verified 且场景集
                # 未变时，白名单外 status（implementer 残留 success 等）不
                # 得把 verified 覆盖为 blocked——verified 门读自有
                # verdict_stability.json（已 verified），共享文件 status 残留
                # 只是污染不是裁决，放行门继续拒绝降级。
                if pipeline._verified_gate_refuses(spec_name, "blocked"):
                    return
                pipeline._context.logger.error(
                    "pm_engine",
                    f"Verifier (legacy) status 白名单外 '{spec_name}' — "
                    f"阻断为 blocked（reason={verifier_result.reason}）: "
                    f"{verifier_result.detail}",
                )
                pipeline._context.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "blocked",
                        "tester_run": result.run_id,
                        "error": (
                            f"Verifier (legacy) 结果文件 status 白名单外"
                            f"（reason={verifier_result.reason}）："
                            f"{verifier_result.detail}"
                        ),
                    },
                )
                pipeline._context.escalation_notifier(
                    spec_name=spec_name,
                    signal_type="verdict_result_unreadable",
                    severity="critical",
                    description=(
                        f"'{spec_name}' legacy 验证裁决结果 status "
                        f"白名单外，已 blocked 等待人工裁决"
                        f"（reason={verifier_result.reason}）"
                    ),
                    evidence=(
                        f"spec={spec_name}; result_file={run_result_path}; "
                        f"parse_error={verifier_result.detail}"
                    ),
                    recommended_action=(
                        "检查旧版 verifier 结果文件 status 是否在 "
                        "verified/bug-found/plan-ready/scenario-repaired "
                        "白名单内；修复后人工重置验证"
                    ),
                )
                return
            # 缺失 / 非法 JSON → D5 直接 blocked（不可读属结构性异常，
            # 自动重派整轮 verifier 只会烧钱，交人工）。
            pipeline._context.logger.error(
                "pm_engine",
                f"Verifier (legacy) 结果不可读 '{spec_name}' — 阻断为 blocked"
                f"（reason={verifier_result.reason}）: "
                f"{verifier_result.detail}",
            )
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "status": "blocked",
                    "tester_run": result.run_id,
                    "error": (
                        f"Verifier (legacy) 结果文件不可读（reason="
                        f"{verifier_result.reason}）：{verifier_result.detail}"
                    ),
                },
            )
            pipeline._context.escalation_notifier(
                spec_name=spec_name,
                signal_type="verdict_result_unreadable",
                severity="critical",
                description=(
                    f"'{spec_name}' legacy 验证裁决结果文件不可读，已 blocked "
                    f"等待人工裁决（reason={verifier_result.reason}）"
                ),
                evidence=(
                    f"spec={spec_name}; result_file={run_result_path}; "
                    f"parse_error={verifier_result.detail}"
                ),
                recommended_action=(
                    "检查旧版 verifier 是否以合法 JSON 写入结果文件；修复后" "人工重置验证"
                ),
            )
            return
        # 结果文件新鲜度/归属护栏：共享单文件会被任何 spec 的后续运行覆写，
        # 陈旧或异 spec 的判定重放到当前轮次 = 假 bug-found / 假 verified
        # （2026-08-28 improve-failover-model-mapping-ui 09:41 旧判定 12:21 重放实证）。
        if pipeline._verifier_result_is_stale(result, run_result_path, spec_name):
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "status": "implemented",
                    "tester_run": None,
                    "error": "stale/foreign verifier result replayed — re-dispatching fresh verify",
                },
            )
            # evo-infra-failure-budget-exempt R2：陈旧/异 spec 归属结果文件
            # 属 infra（沿用既有 re-dispatch），同挂预算退款与记账。
            pipeline._record_infra_failure(
                spec_name,
                "stale/foreign verifier result replayed",
                run_id=getattr(result, "run_id", "") or "",
            )
            pipeline._context.logger.warning(
                "pm_engine",
                f"Stale/foreign verifier result for '{spec_name}' — "
                f"re-dispatching fresh verification",
            )
            return
        if verifier_status == "bug-found":
            # 验证报告产物闸门（add-verify-report-gate，legacy 路径同闸门）
            report_blocker = pipeline._ensure_verification_report(spec_name)
            if report_blocker:
                pipeline._context.state_machine.update_spec(
                    spec_name,
                    {
                        "error": report_blocker,
                    },
                )
                pipeline._context.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止推进 bug-found — {report_blocker}",
                )
                return

            # verified 洗白门禁（help-center 0/15 verified 事故防线）：
            # 0 通过或 env 失败不得放行，升级 admin 处置
            if not pipeline._env_whitewash_gate(spec_name):
                return
            # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
            # 结果应用前 spec 已非 testing（stale-result 防护拨回 implemented /
            # 并发新 attempt 已接管 / 其它状态漂移）→ DEBUG 丢弃，不走失败迁移
            # 与 fallback 重派（拆除旧 reconcile：implemented→testing→bug-found
            # 回放 + 重复派发整轮 verifier）。正常路径 spec 恒为 testing。
            _cur = (pipeline._context.state_machine.read_one(spec_name) or {}).get("status", "")
            if _cur != "testing":
                pipeline._context.logger.debug(
                    "pm_engine",
                    f"Stale/foreign verify result discarded for '{spec_name}' "
                    f"(run {result.run_id}, current state '{_cur}', result "
                    f"bug-found) — spec no longer in testing, result dropped",
                )
                return

            # ── 归因分级门禁（legacy 路径同门禁，add-verdict-credibility-gate / D2）──
            if pipeline._speculative_bug_found_gate(spec_name):
                return
            # ── verified 一次性放行门（judge-rerun-stability R2）──
            # 已 verified 且场景集未变 → 拒绝降级为 bug-found（legacy 路径
            # 同门禁；复用自有 verdict_stability.json 而非共享 .fenix-run-
            # result.json——后者会被 implementer status=success 残留污染，
            # 读它会错误判为「非 verified」而漏拦）。
            if pipeline._verified_gate_refuses(spec_name, "bug-found"):
                return
            # ── 统一失败归因入口（legacy 同门，evo-infra-failure-budget-exempt R1/R3）──
            # MUST 在 bug-found transition 之前（code-review item 12bd5b177792）：
            # enrich_failure_class 比上游早期 infra 门多匹配 worktree/merge
            # conflict/tree dirty 标记，verifier error 含这些文本时判 infra——
            # 若先流转 bug-found 再归因，infra 分支「不流转 bug-found」即失效
            # （spec 停在 bug-found 却不派生 fix，状态回退只能靠 recovery 兜底）。
            failure_class = pipeline.enrich_failure_class(
                spec_name,
                error_text=getattr(result, "error", "") or "",
            )
            if failure_class == "infra":
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"归因入口判 infra（legacy）：'{spec_name}' 按 infra 记账，"
                    f"不流转 bug-found、不派生 fix",
                )
                pipeline._record_infra_failure(
                    spec_name,
                    "infra at attribution entry (legacy)",
                    run_id=getattr(result, "run_id", "") or "",
                )
                return
            pipeline._context.state_machine.transition(
                spec_name, "bug-found",
                trigger_run_id=result.run_id, agent_type="tester", channel="auto",
            )
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": result.run_id,
                    "error": "Verification found bugs — see verification report",
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：bug-found 属健康轮，
                    # 降档并行度同轮复位（legacy 路径同语义）。
                    "_verify_parallel_override": None,
                },
            )
            # 裁决采纳后落盘 verdict 稳定性轮次（judge-rerun-stability R1）
            pipeline._record_verdict_adoption(spec_name, "bug-found", report)
            pipeline._context.logger.warning(
                "pm_engine",
                f"Verifier (legacy) found bugs in '{spec_name}'",
            )
            # ── 守卫二：spawn 抑制（fix-repair-lane-dedup / design 守卫二）──
            if pipeline._context.is_fix_spec(spec_name):
                cur = (pipeline._context.state_machine.read_one(spec_name) or {}).get("status", "")
                if cur in ("ready", "implementing"):
                    pipeline._context.logger.info(
                        "pm_engine",
                        f"守卫二：'{spec_name}' 为 fix spec 且自身 {cur}"
                        f"（重实现在飞）——跳过派生子 fix（legacy 路径）",
                    )
                    pipeline._context.state_machine.update_spec(
                        spec_name,
                        {
                            "error": "修复由在飞重实现承载，跳过派生子 fix",
                        },
                    )
                    return
            # 到达 bug-found 归因（全部门禁已过、非 infra，归因已前置到
            # transition 之前）＝ product 类——
            # unknown 按 product 保守处置，台账 failure_class 记 product。
            pipeline._context.on_spec_bug_found(
                spec_name,
                failure_class="product",
                run_id=getattr(result, "run_id", "") or "",
            )
        else:
            # D6: legacy 路径同样前置进度核对：done>=total 才晋级
            vblocker = pipeline._check_verification_gate(spec_name)
            if vblocker:
                pipeline._context.state_machine.update_spec(
                    spec_name,
                    {
                        "tester_run": result.run_id,
                        "error": vblocker,
                    },
                )
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"验证未完成 (legacy) '{spec_name}'，阻止晋级 verified: {vblocker}",
                )
                return
            # 验证报告产物闸门（add-verify-report-gate，legacy 路径同闸门）
            report_blocker = pipeline._ensure_verification_report(spec_name)
            if report_blocker:
                pipeline._context.state_machine.update_spec(
                    spec_name,
                    {
                        "tester_run": result.run_id,
                        "error": report_blocker,
                    },
                )
                pipeline._context.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止晋级 verified — {report_blocker}",
                )
                return

            # verified 洗白门禁（help-center 0/15 verified 事故防线）：
            # 0 通过或 env 失败不得放行，升级 admin 处置
            if not pipeline._env_whitewash_gate(spec_name):
                return
            # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
            # 结果应用前 spec 已非 testing → DEBUG 丢弃，不走迁移与 fallback
            # 重派（拆除旧 reconcile：implemented→testing→verified 回放 +
            # 重派整轮 verifier）。02:13 事故即此路径：拨回 implemented 后在飞
            # 旧 judge 完成，结果被丢弃而非回退重派。
            _cur = (pipeline._context.state_machine.read_one(spec_name) or {}).get("status", "")
            if _cur != "testing":
                pipeline._context.logger.debug(
                    "pm_engine",
                    f"Stale/foreign verify result discarded for '{spec_name}' "
                    f"(run {result.run_id}, current state '{_cur}', result "
                    f"verified) — spec no longer in testing, result dropped",
                )
                return

            pipeline._context.state_machine.transition(
                spec_name, "verified",
                trigger_run_id=result.run_id, agent_type="tester", channel="auto",
            )
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": result.run_id,
                    "error": None,
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：verified 属健康轮，
                    # 降档并行度同轮复位（legacy 路径同语义）。
                    "_verify_parallel_override": None,
                    # add-fail-counter-budget D1：PASS 唯一归零点（legacy 路径同语义）。
                    "_verify_fail_rounds": 0,
                    # evo-infra-failure-budget-exempt R3：_verify_infra_rounds
                    # 与 _verify_fail_rounds 同清零点（legacy 路径同语义）。
                    VERIFY_INFRA_ROUNDS_FIELD: 0,
                    # fix-daemon-lifecycle-races D3：验证自然通过清零点（legacy 同语义）。
                    "_verify_redo_count": 0,
                    # add-blocked-reverify-lane D3：env 阻塞轮次清零点（legacy 同语义）。
                    ENV_BLOCK_ROUNDS_FIELD: 0,
                },
            )
            # 裁决采纳后落盘 verdict 稳定性轮次（judge-rerun-stability R1）
            pipeline._record_verdict_adoption(spec_name, "verified", report)
            # 失败历史侧车随 verified 终态清空（legacy 同语义，
            # fix-verdict-retry-misattribution D6）
            pipeline._clear_fail_history(spec_name)
            pipeline._context.on_spec_verified(spec_name)
    else:
        # ── verified 一次性放行门（judge-rerun-stability R2）──
        # verifier agent 进程失败的降级同样不得覆盖已 verified 结论。
        if pipeline._verified_gate_refuses(spec_name, "bug-found"):
            return
        # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
        # 进程失败分支与上两个分支（bug-found/verified）同款复核：入口
        # testing 判据之后 run_verifier 期间状态已漂移（拨回 implemented/
        # 并发接管）→ DEBUG 丢弃陈旧失败结果，不 transition bug-found、
        # 不覆盖 error/tester_run。
        _cur = (pipeline._context.state_machine.read_one(spec_name) or {}).get("status", "")
        if _cur != "testing":
            pipeline._context.logger.debug(
                "pm_engine",
                f"Stale/foreign verify result discarded for '{spec_name}' "
                f"(run {result.run_id}, current state '{_cur}', result "
                f"process-failure) — spec no longer in testing, result dropped",
            )
            return
        pipeline._context.state_machine.transition(
            spec_name, "bug-found",
            trigger_run_id=result.run_id, agent_type="tester", channel="auto",
        )
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "tester_run": result.run_id,
                "error": f"Verifier agent failed: {result.error}",
            },
        )
