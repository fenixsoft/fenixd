"""legacy.py — core.pm_engine.verification.legacy：legacy 验证回退（refactor-verification-module D2）。

从 VerificationPipeline 摘出的降级方案入口 `_run_legacy_verification`：使用旧版
单体 Verifier Agent 的三阶段验证回退。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import re
import time
from datetime import datetime, timezone
from pathlib import Path

# verified 收口清零/复位字段集单源（code-review item e143213f2b45）：
# fastlane.VERIFIED_RESET_FIELDS 收编 state_machine 与 fastlane 两侧字段，
# 与主路径 pipeline._apply_verified 同引一张表，字段演进只改该表。
from core.pm_engine.verification.fastlane import VERIFIED_RESET_FIELDS
# evo-add-verifier-infra-death-triage：进程级死亡判定与指纹标注（同包兄弟
# 模块直引——infra_classify 不回引 legacy，无环；不经 pipeline 门面注册表，
# 判定是纯函数、无 pipeline 状态依赖）。
from core.pm_engine.verification.infra_classify import (
    VERIFIER_DEATH_SURVIVAL_THRESHOLD_SECONDS,
    annotate_death_fingerprint,
    is_verifier_process_death,
)

# 本轮 verify 派发时刻解析口径（fix-verify-verdict-run-attribution D4）：
# run/attempt id 形如 ``<run>-<epoch>-a<n>[-r<m>]``，内嵌 epoch 即本轮
# attempt 启动时刻（≈ 派发时刻），与 report_gate._verifier_result_is_stale
# 的 ``-(\d{10,})-a\d+$`` 既有口径同源。
_RUN_ID_EPOCH_PATTERN = re.compile(r"-(\d{10,})-a\d+$")


def _discard_if_not_testing(pipeline, spec_name, result, label):
    """在飞 verify 结果应用前状态复核的单一收敛点（code-review 05d216e0182d）。

    _residue_fail_closed 与 legacy 的 bug-found/verified/process-failure
    三个应用分支共用同一判据：结果应用前 spec 已非 testing（终态已收敛 /
    stale-result 防护拨回 implemented / 并发新 attempt 已接管）→ DEBUG 丢弃
    并返回 True；仍在 testing → 返回 False 继续应用。状态判据与 DEBUG 文案
    单点维护，防多处演进漏改其一造成行为漂移（与 _residue_fail_closed
    的收敛思路一致）。

    前史（fix-verify-late-result-terminal-clobber D1 / fix-daemon-lifecycle-
    races D6）：在飞 run 可长达数十分钟，入口判据只保证「派发时是 testing」，
    不能替代应用时二次复核。2026-09-24 事故实证：机械车道已把 SPEC 推到
    pushed 终态，在飞 LLM verifier 42 分钟后完成，结果文件被判 stale 后仍
    直接覆写 implemented，触发终态回退 + 冗余全量重验。

    ``label``：DEBUG 丢弃消息中的结果标签，由调用点自定、不在此穷举担保
    （新增调用点自带新标签即可，避免枚举清单随调用点演进漂移——cancelled/
    infra 等标签曾漏出早期枚举）；排查 DEBUG 丢弃文案时以各调用点实参为准，
    现有点位含 foreign-role/unknown-status+stale/stale/bug-found/verified/
    process-failure/cancelled/infra/plan-ready/scenario-repaired/
    unknown-status/unreadable。
    """
    _cur = (pipeline._context.state_machine.read_one(spec_name) or {}).get("status", "")
    if _cur != "testing":
        pipeline._context.logger.debug(
            "pm_engine",
            f"Stale/foreign verify result discarded for '{spec_name}' "
            f"(run {getattr(result, 'run_id', '') or ''}, current state '{_cur}', result "
            f"{label}) — spec no longer in testing, result dropped",
        )
        return True
    return False


def _archive_stale_verdict_file(result_path: Path, logger) -> str:
    """stale/foreign 残留裁决文件归档备份（fix-verify-verdict-run-attribution D2 分支③）。

    消费守卫判「陈旧 mtime / 异 spec 戳 / 异归属残留」时先归档为
    ``<原文件名>.stale-<UTC ISO 时间戳>``（保留法证现场），再走 fail-closed。
    归档失败仅 WARNING——fail-closed 处置不因归档失败而中断（残留内容本就
    不作为本轮裁决采信，归档只为留痕）。

    返回归档后路径；无可归档文件或归档失败返回空字符串。
    """
    if not result_path.exists():
        return ""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_path = result_path.with_name(f"{result_path.name}.stale-{ts}")
    try:
        result_path.rename(archive_path)
    except OSError as e:
        logger.warning(
            "pm_engine",
            f"stale/foreign verdict 归档失败（继续 fail-closed 处置）: "
            f"path={result_path}, err={e}",
        )
        return ""
    logger.warning(
        "pm_engine",
        f"stale/foreign verdict 已归档备份（本轮不采信、不重派）: "
        f"{result_path} → {archive_path}",
    )
    return str(archive_path)


def _verify_dispatch_epoch(result) -> float:
    """解析本轮 verify 派发时刻（UTC epoch 秒，fix-verify-verdict-run-attribution D4）。

    优先从 ``result.run_id`` 内嵌 epoch 解析（``-(\d{10,})-a\d+$`` 口径，
    与 report_gate._verifier_result_is_stale 同源）；解析失败回退本轮 run
    流启动时刻（完成时刻 - result.duration_seconds，即本轮 verify run 流
    的起算点）；时长亦不可得时回退当前时刻（mtime < now 恒不成立 → 不
    保全——回退链全断时按「无新鲜 report」口径走照常 fail-closed）。
    """
    raw_run_id = getattr(result, "run_id", "") or ""
    try:
        m = _RUN_ID_EPOCH_PATTERN.search(raw_run_id)
        if m:
            return float(int(m.group(1)))
    except (TypeError, ValueError):
        pass
    try:
        duration = float(getattr(result, "duration_seconds", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return time.time() - duration


def _preserve_verify_report(pipeline, spec_name: str, result) -> str:
    """fail-closed 丢弃前保全本轮验证成果 report.json（fix-verify-verdict-run-attribution D4）。

    消费守卫判「残留 / 本轮未产出裁决」、丢弃当轮成果进入 fail-closed 前
    调用：report.json 存在且 mtime（stat UTC 口径）≥ 本轮 verify 派发时刻
    （``_verify_dispatch_epoch``：run_id 内嵌 epoch 优先，回退本轮 run 流
    启动时刻）→ 重命名保全为 ``report-<run_id>.json`` + WARNING（杜绝静默
    扔验证成果，add-command-center 2026-10-26 事故：39 分钟真实验证的
    report 因 verdict 断链被整体作废）；不满足（无 report / 陈旧 report）
    则跳过保全照常 fail-closed。升级告警文案附保全路径由调用方
    （``_residue_fail_closed`` → ``_block_legacy_verdict``）承载。

    返回保全后路径；未触发保全返回空字符串。
    """
    from core.pm_engine.verification.report_gate import verify_progress_dir

    report_path = verify_progress_dir(pipeline, spec_name) / "report.json"
    if not report_path.exists():
        return ""
    try:
        # stat 的 st_mtime 即 UTC epoch 秒（D5：与派发时刻同口径对齐比较，
        # 无 naive/aware 混比）。
        report_mtime = report_path.stat().st_mtime
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"验证成果保全跳过（report mtime 不可得）'{spec_name}': {e}",
        )
        return ""
    if report_mtime < _verify_dispatch_epoch(result):
        return ""
    raw_run_id = getattr(result, "run_id", "") or ""
    from core.verify_engine.path_safety import safe_component

    safe_run_id = safe_component(raw_run_id) or f"unknown-{int(time.time())}"
    preserved_path = report_path.with_name(f"report-{safe_run_id}.json")
    try:
        report_path.rename(preserved_path)
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"验证成果保全失败（继续 fail-closed 处置）'{spec_name}': "
            f"path={report_path}, err={e}",
        )
        return ""
    pipeline._context.logger.warning(
        "pm_engine",
        f"本轮验证成果保全（fail-closed 丢弃前）'{spec_name}': "
        f"{report_path} → {preserved_path}",
    )
    return str(preserved_path)


def _residue_fail_closed(
    pipeline, spec_name, result, run_result_path, verifier_result,
    label, archive=True,
):
    """残留 / 本轮未产出裁决消费处置单点（fix-verify-verdict-run-attribution D2/D4）。

    取代旧 stale/foreign re-dispatch 语义（code-review 842cfc9b4447 的
    ``_redispatch_fresh_verify`` 已随本改向移除）：跨 run 残留或预写戳原样
    不再被归因为「他人结果重放」、不再自动整轮重派——该归因是
    add-command-center（2026-10-26）两轮 39 分钟真实验证被整体作废的直接
    根因。新语义四步：

    1. 状态复核（在飞结果判据，收敛于 ``_discard_if_not_testing``）；
    2. verified 一次性放行门（judge-rerun-stability R2：已 verified 且场景
       集未变时，残留不构成把 verified 降级为 blocked 的裁决——放行门拒绝）；
    3. 归档残留裁决文件（``.stale-<ts>``，保留法证现场；预写戳原样形态
       archive=False 跳过——预写戳是本轮自己的产物，非跨 run 残留）；
    4. 保全本轮 report.json（``report-<run_id>.json``）后 blocked fail-closed
       + critical 告警，文案「本轮未产出机器可读裁决」、附保全路径。

    ``label``：DEBUG 丢弃消息中的结果标签（not-produced/foreign-role/
    foreign-stamp/unknown-status+stale/stale）。
    """
    # ── 在飞 verify 结果状态判据（fix-verify-late-result-terminal-clobber D1）──
    if _discard_if_not_testing(pipeline, spec_name, result, label):
        return
    # ── verified 一次性放行门（judge-rerun-stability R2）──
    # 已 verified 且场景集未变时，残留/预写戳不构成裁决，不得把 verified
    # 覆盖为 blocked（放行门读自有 verdict_stability.json）。
    if pipeline._verified_gate_refuses(spec_name, "blocked"):
        return
    if archive:
        _archive_stale_verdict_file(run_result_path, pipeline._context.logger)
    preserved = _preserve_verify_report(pipeline, spec_name, result)
    _block_legacy_verdict(
        pipeline, spec_name, result, run_result_path, verifier_result,
        reason_label="本轮未产出机器可读裁决",
        recommended_action=(
            "检查 verifier/judge 为何未写出裁决文件"
            "（跨 run 残留已归档 .stale-* 备份）；人工排查后重置验证重派"
        ),
        preserve_path=preserved,
    )


def _block_legacy_verdict(
    pipeline, spec_name, result, run_result_path, verifier_result,
    reason_label, recommended_action, preserve_path="",
):
    """unknown-status / unreadable / 残留未产出裁决 分支的 blocked 结局收敛单点
    （code-review 493154d23013；fix-verify-verdict-run-attribution 扩接入）。

    各分支除 reason 文案与推荐动作外完全同构：logger.error →
    update_spec(status=blocked) → escalation_notifier(
    verdict_result_unreadable/critical)。状态判据与 error 文案单点维护，
    防多处演进漏改其一造成行为漂移（与 _discard_if_not_testing/
    _residue_fail_closed 收敛动机一致）。

    ``reason_label``：分支差异文案（「status 白名单外」/「结果不可读」/
    「本轮未产出机器可读裁决」），嵌入日志/ error / 告警描述；
    ``recommended_action``：推荐动作原文。``preserve_path``：非空时为
    D4 成果保全路径（fail-closed 丢弃前已重命名保全的 report-<run_id>.json），
    附入升级告警描述与 evidence（人工可回查被保全的当轮验证成果）。
    """
    pipeline._context.logger.error(
        "pm_engine",
        f"Verifier (legacy) {reason_label} '{spec_name}' — 阻断为 blocked"
        f"（reason={verifier_result.reason}）: "
        f"{verifier_result.detail}",
    )
    # ── 直写 update_spec 而非 transition（code-review db38086cb54a）──
    # testing→blocked 不在 VALID_TRANSITIONS（TESTING 仅放行
    # verified/bug-found），transition 会确定性拒绝——若按「被拒保留原状」
    # 口径消费返回值，D5 fail-closed 阻断将永久失效（不可读/白名单外结果
    # 永远无人 blocked）。主路径同场景（pipeline.py 裁决不可读分支）同为
    # 读侧复核收敛 TOCTOU 后 update_spec 直写 blocked，与本收口点同款；
    # 与 bug-found/verified 分支的 transition 口径差异即在此——那两处目标
    # 是 TESTING 的合法出边。
    # 返回值核对（code-review item 33abefe13a94，与 dispatch/rollback.py
    # item 90b4004274a9 口径一致）：False = 条目缺失/原子写失败，blocked
    # 未落盘、spec 仍停留原状态——跳过下方「已 blocked 等待人工裁决」
    # critical 告警（人工会被引向不存在的 blocked 现场），改记 WARNING
    # 如实留痕。
    if not pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "status": "blocked",
            "tester_run": result.run_id,
            "error": (
                f"Verifier (legacy) 结果文件{reason_label}"
                f"（reason={verifier_result.reason}）："
                f"{verifier_result.detail}"
            ),
        },
    ):
        pipeline._context.logger.warning(
            "pm_engine",
            f"legacy blocked 落盘失败：update_spec 返回 False（条目缺失/"
            f"原子写失败）'{spec_name}' — 状态未变更，跳过 critical 升级告警",
        )
        return
    # 升级通道自身失败不得抛穿裁决流程（code-review item c0d75398fc9a，与
    # escalation.py 7e0509f14fdd 包裹模式同款）：上方 blocked 已落盘为
    # fail-closed 终态，notifier 异常若沿 engine except e2 上抛会被
    # _rollback_failed_dispatch 洗回 implemented——把结构性异常的人工处置
    # 窗口覆写成自动重试通道。WARNING 留痕不改变本轮收口结论。
    try:
        pipeline._context.escalation_notifier(
            spec_name=spec_name,
            signal_type="verdict_result_unreadable",
            severity="critical",
            description=(
                f"'{spec_name}' legacy 验证裁决结果文件{reason_label}，已 blocked "
                f"等待人工裁决（reason={verifier_result.reason}）"
                + (f"；{preserve_path}" if preserve_path else "")
            ),
            evidence=(
                f"spec={spec_name}; result_file={run_result_path}; "
                f"parse_error={verifier_result.detail}"
                + (f"; preserved_report={preserve_path}" if preserve_path else "")
            ),
            recommended_action=recommended_action,
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"legacy blocked 升级告警发送失败（非阻塞，blocked 处置已落盘）"
            f"'{spec_name}': {type(e).__name__}: {e}",
        )


def _run_legacy_verification(pipeline, spec_name: str):
    """降级方案：使用旧版单体 Verifier Agent。"""
    # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）：入口状态
    # 非 testing → DEBUG 丢弃（注明当前状态），不执行任何迁移/回退/重派。
    # 判据与 DEBUG 文案单点收敛于 pipeline._check_entry_status（code-review
    # 5811442b6209），与本文件 _discard_if_not_testing 同防两处演进漂移。
    if not pipeline._check_entry_status(spec_name):
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
    if getattr(result, "cancelled", False) is True:
        # ── 人工取消 hold-state（add-run-cancel D4，legacy verifier）──
        # verifier run 被取消：spec 保持 testing 原状，只写 error，
        # 不流转 bug-found、不入队重派。
        v_err = result.error or ""
        cancelled_err = f"run 被人工取消：{v_err}" if v_err else "run 被人工取消"
        # ── 在飞 verify 结果状态判据（与本文件其余写点对齐）──
        # run 被取消期间 spec 可能已被并发 attempt 推进到终态或拨回
        # implemented：直接写会把「run 被人工取消」覆写到漂移后状态的 error、
        # 并在非 testing 的 spec 上留下 _cancelled_hold 持久标记，干扰后续
        # cancel-holdstate recovery 判定。判据单点收敛于 _discard_if_not_testing。
        if _discard_if_not_testing(pipeline, spec_name, result, "cancelled"):
            return
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
    # code-review item 695c4c18d3eb：infra 门仅作用于失败终态——生产契约
    # success ⇒ error 恒空（runner 三处 success=True 构造点均不传 error、
    # 缺省 None 且全仓无结果对象 .error 事后赋值），本门对成功终态不触发；
    # 加 not success 前置把「裁决消费优先」钉进控制流：成功终态即使未来
    # 演进出非空 error 文本，也先走下方 result.success 裁决分支消费产出，
    # 不被本门整轮丢弃、spec 不致挂 error 原地等待 recovery。
    if not result.success and pipeline._verifier_error_is_infra(result.error):
        # 基础设施类失败（熔断/链耗尽/网关切换类错误）＝「验证没能发生」，
        # 不是「验证发现了缺陷」：保持当前状态不流转 bug-found、不派生 fix
        # （2026-08-28 chain_exhausted 误产空壳 fix 实证），由 full_scan
        # recovery 兜底重排；冷却到期后下一次扫描即恢复验证。
        # ── 在飞 verify 结果状态判据（与 bug-found/verified/process-failure
        # 分支同款，判据收敛于 _discard_if_not_testing，05d216e0182d）──
        # 结果应用前 spec 已非 testing → DEBUG 丢弃：不覆写 error、不记
        # infra 账（终态 SPEC 记 infra 是噪音且附带预算豁免对终态无意义）。
        if _discard_if_not_testing(pipeline, spec_name, result, "infra"):
            return
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
            # 退款锚点回退 implementer_run（不传 run_id）；attempt run id
            # 只作台账事件标识（attempt run id 不作预算退款锚点）。
            ledger_run_id=getattr(result, "run_id", "") or "",
        )
        pipeline._context.logger.warning(
            "pm_engine",
            f"Verifier infra failure — holding '{spec_name}' state, "
            f"no bug-found: {result.error}",
        )
        return

    if result.success:
        # evo-verifier-result-single-source R1（legacy 同门）：结果文件
        # 读取统一走 _read_verdict 入口——verify-progress/<spec>/
        # .fenix-run-result.json 优先（旧版 verifier 的确定性产物路径），
        # 回退主树共享 .fenix/.fenix-run-result.json 且须先过 role/spec 戳
        # 校验：role≠verifier/缺 role 的主树共享文件一律不采信（implementer
        # 残留 status=success/error / 旧格式遗留），修复 _verifier_result_is_stale
        # 的 run_id fail-open（run_id 不匹配 ``-\d{10,}-a\d+$`` 时旧行为
        # 不判陈旧，残留仍落 blocked 分支——add-web-ui 误判链实证）。
        # 陈旧/归属护栏所需路径（与 _read_verdict 同源解析：primary
        # 优先，缺失回退共享文件——_verifier_result_is_stale 据此检测
        # mtime 陈旧/spec 戳不符）。fix-deferred-findings 整洁类：路径解析
        # 经公开别名 verify_progress_result_paths 收敛（与 report_gate 同源）。
        # code-review item f8ad8f7cd7ae：解析 MUST 前置到 _read_verdict 之前
        # 只做一次——原顺序（先读裁决、后 primary.exists() 重新解析）两次
        # 解析之间 primary 出现/消失时，护栏与 blocked evidence 的
        # result_file 会与实际裁决来源错位（护栏判错对象、人工排障被
        # evidence 误导）。彻底消除残余观测窗须 _read_verdict 回传实际
        # 采信来源路径（涉及 report_gate.py，本条目文件边界外），此处按
        # 建议前置收敛，护栏/evidence 与裁决读取共用同一观测序。
        # code-review item 7e0a1ea1daf5：跨模块消费改走公开别名，不再
        # import 私有符号（公开别名见 report_gate.py）。
        from core.pm_engine.verification.report_gate import (
            verify_progress_result_paths,
        )

        primary, fallback = verify_progress_result_paths(pipeline, spec_name)
        run_result_path = primary if primary.exists() else fallback
        verifier_result = pipeline._read_verdict(spec_name)
        verifier_status = verifier_result.status if verifier_result.ok else None
        # code-review item 06a41cc7dc03：陈旧/归属护栏前置到 report.json 消费
        # 之前（先护栏后消费）——原顺序先读 report.json 并消费环境失联判定
        # （inconclusive 重派/计数），stale 护栏后置；裁决来源是共享回退文件
        # 且报告产物相对陈旧时，环境失联处置会基于旧报告先行作出。布尔只
        # 计算一次，下方 env 消费门与原护栏位两处复用：护栏语义与处置
        # （stale → 单次 re-dispatch）不重复执行也不被跳过。
        verifier_result_stale = pipeline._verifier_result_is_stale(
            result, run_result_path, spec_name
        )
        # code-review item f8ede80248e3：report 读取提为无条件（读取廉价且
        # 幂等，失败恒返回 {} 哨兵）——下方 bug-found/verified 分支无条件
        # 消费 report，原先依赖「stale 结果必在下方 stale 处置提前 return」
        # 的隐式控制流不变量，读取前置后该不变量不再被隐式依赖。
        # [fenix-ignore:f6c112fcb5a5] _read_verify_report 失败恒返回 {} 哨兵（report_gate 契约，绝不为 None），report.get 无 AttributeError 风险
        report = pipeline._read_verify_report(spec_name)
        # 环境性失联门禁（legacy 路径同样生效）：旧版 verifier 若在 report.json
        # 中标记了 blocked-env 且全批环境性失联，则同样判定 inconclusive 重派，
        # 不判 bug-found（防假阴性派生 fix 家族）。stale 命中时跳过本消费
        # （不计数、不按 inconclusive 重派），交由下方既有 stale 处置路径。
        if not verifier_result_stale:
            if pipeline._handle_env_blocked_inconclusive(spec_name, report):
                return
        # fix-verdict-read-failclosed D5（legacy 同门）：旧版 verifier 结果不可读
        # （缺失/非法 JSON/白名单外）→ blocked + critical 告警，绝不晋级
        # verified。legacy 是降级通道（三阶段两连败才进），结果不可读说明结构性
        # 异常而非偶发——自动重派整轮 verifier 只会烧钱，交人工。例外：status 白
        # 名单外（如 implementer 共享残留的 "success"）文件本身可读，须先走既有
        # 陈旧/归属护栏（foreign-spec 残留 → re-dispatch）再决定 blocked。
        if not verifier_result.ok:
            if verifier_result.reason == "not-produced":
                # fix-verify-verdict-run-attribution D2 分支②：文件仍为本次
                # 派发预写戳原样（role=verifier、status=dispatched）——本轮
                # 未产出裁决。走既有 fail-closed（blocked + critical 告警，
                # 文案「本轮未产出机器可读裁决」），不引用任何残留内容作为
                # 裁决；丢弃当轮成果前按 D4 保全 report.json（archive=False：
                # 预写戳是本轮派发自己的产物，非跨 run 残留，不作 .stale 归档）。
                _residue_fail_closed(
                    pipeline, spec_name, result, run_result_path, verifier_result,
                    "not-produced", archive=False,
                )
                return
            if verifier_result.reason in ("foreign-role", "foreign-stamp"):
                # _read_verdict 已定性：主树共享文件 role≠verifier/缺 role
                # （implementer 残留 status=success 等）或 spec 戳不符——
                # 文件可读但归属不明，一律不采信为验证裁决。
                # fix-verify-verdict-run-attribution D2 分支③：异归属残留
                # 先归档 .stale-<ts> 再 fail-closed（blocked + critical 告警），
                # MUST NOT 沿用「stale/foreign 重放」语义把当轮 verify 成果
                # 判为他人重放、不再自动整轮重派（re-dispatch 处置已移除）。
                _residue_fail_closed(
                    pipeline, spec_name, result, run_result_path, verifier_result,
                    verifier_result.reason, archive=True,
                )
                return
            if verifier_result.reason == "unknown-status":
                # 白名单外 status：文件可读，可能是共享文件中的其它 spec 残留
                # 或 implementer 残留——先走既有陈旧/归属护栏（检测 spec stamp
                # 不符 / mtime 陈旧）。
                # code-review item eb06c288c3c7：复用上方 :330 前置计算的同一
                # 布尔（单一观测口径，与 :431-433 声明一致），不重复观测。
                if verifier_result_stale:
                    # stale 命中 → D2 分支③：归档残留 + 保全成果 + fail-closed
                    # （不再 re-dispatch，语义见 _residue_fail_closed）。
                    _residue_fail_closed(
                        pipeline, spec_name, result, run_result_path, verifier_result,
                        "unknown-status+stale", archive=True,
                    )
                    return
                # 文件属当前 spec 且 mtime 新鲜，但 status 白名单外 → blocked
                # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
                # run_verifier 期间状态可能已漂移（stale-result 拨回 implemented /
                # 人工复位 / 冻结接管）→ DEBUG 丢弃，不覆写较新状态（与
                # bug-found/verified/process-failure 分支同款复核，判据单点
                # 收敛于 _discard_if_not_testing）。
                if _discard_if_not_testing(pipeline, spec_name, result, "unknown-status"):
                    return
                # ── verified 一次性放行门（judge-rerun-stability R2）──
                # 「legacy unknown-status 不得改判」：已 verified 且场景集
                # 未变时，白名单外 status（implementer 残留 success 等）不
                # 得把 verified 覆盖为 blocked——verified 门读自有
                # verdict_stability.json（已 verified），共享文件 status 残留
                # 只是污染不是裁决，放行门继续拒绝降级。
                if pipeline._verified_gate_refuses(spec_name, "blocked"):
                    return
                _block_legacy_verdict(
                    pipeline, spec_name, result, run_result_path, verifier_result,
                    reason_label="status 白名单外",
                    recommended_action=(
                        "检查旧版 verifier 结果文件 status 是否在 "
                        "verified/bug-found/plan-ready/scenario-repaired "
                        "白名单内；修复后人工重置验证"
                    ),
                )
                return
            # 缺失 / 非法 JSON → D5 直接 blocked（不可读属结构性异常，
            # 自动重派整轮 verifier 只会烧钱，交人工）。
            # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
            # run_verifier 期间状态可能已漂移（stale-result 拨回 implemented /
            # 人工复位 / 冻结接管）→ DEBUG 丢弃，不覆写较新状态（与
            # bug-found/verified/process-failure 分支同款复核，判据单点
            # 收敛于 _discard_if_not_testing）。
            if _discard_if_not_testing(pipeline, spec_name, result, "unreadable"):
                return
            # ── verified 一次性放行门（judge-rerun-stability R2）──
            # 已 verified 且场景集未变时，结果不可读不得把 verified 覆盖为
            # blocked（与 unknown-status 分支 243 行同理由：verified 门读
            # 自有 verdict_stability.json，裁决以稳定性缓存为准）。
            if pipeline._verified_gate_refuses(spec_name, "blocked"):
                return
            _block_legacy_verdict(
                pipeline, spec_name, result, run_result_path, verifier_result,
                reason_label="结果不可读",
                recommended_action=(
                    "检查旧版 verifier 是否以合法 JSON 写入结果文件；修复后人工重置验证"
                ),
            )
            return
        # 结果文件新鲜度/归属护栏：共享单文件会被任何 spec 的后续运行覆写，
        # 陈旧或异 spec 的判定重放到当前轮次 = 假 bug-found / 假 verified
        # （2026-08-28 improve-failover-model-mapping-ui 09:41 旧判定 12:21 重放实证）。
        # 判定已在 report.json 消费之前前置计算（code-review item
        # 06a41cc7dc03），此处复用同一布尔，不重复观测。
        if verifier_result_stale:
            # fix-verify-verdict-run-attribution D2 分支③：陈旧/异归属残留
            # 先归档 .stale-<ts> + 保全本轮成果，再 fail-closed（blocked +
            # critical 告警「本轮未产出机器可读裁决」）——不再 re-dispatch
            # 整轮重派（处置单点见 _residue_fail_closed）。
            _residue_fail_closed(
                pipeline, spec_name, result, run_result_path, verifier_result,
                "stale", archive=True,
            )
            return
        if verifier_status == "bug-found":
            # ── 在飞 verify 结果状态判据·闸门写点前置复核（code-review
            # 12f6974d3d88）──
            # 复核前移到各闸门写点之前（与 unknown-status/unreadable 分支同
            # 序）：run_verifier 期间 spec 已漂移出 testing 时，报告闸门/洗白
            # 门阻断路径的 update_spec 不得覆写 error/tester_run（正是
            # process-failure 分支注释承认的 error 覆写抹掉 frozen 标记性
            # error 的事故同款风险）。transition 前仍保留同款复核收敛 TOCTOU
            # 窗口。
            if _discard_if_not_testing(pipeline, spec_name, result, "bug-found"):
                return
            # 验证报告产物闸门（add-verify-report-gate，legacy 路径同闸门）
            report_blocker = pipeline._ensure_verification_report(spec_name)
            if report_blocker:
                pipeline._context.state_machine.update_spec(
                    spec_name,
                    {
                        # 对齐 verified 分支同构闸门阻断（460-466）：写 tester_run
                        # 供 dashboard/审计在报告闸门阻断时仍可见触发本轮的 run
                        # （code-review item a0eff51179fd）。
                        "tester_run": result.run_id,
                        "error": report_blocker,
                    },
                )
                pipeline._context.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止推进 bug-found — {report_blocker}",
                )
                return

            # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
            # 结果应用前 spec 已非 testing（stale-result 防护拨回 implemented /
            # 并发新 attempt 已接管 / 其它状态漂移）→ DEBUG 丢弃，不走失败迁移
            # 与 fallback 重派（拆除旧 reconcile：implemented→testing→bug-found
            # 回放 + 重复派发整轮 verifier）。正常路径 spec 恒为 testing。
            # 判据与文案单点收敛于 _discard_if_not_testing（05d216e0182d）。
            if _discard_if_not_testing(pipeline, spec_name, result, "bug-found"):
                return

            # ── 归因分级门禁（legacy 路径同门禁，add-verdict-credibility-gate / D2）──
            if pipeline._speculative_bug_found_gate(spec_name):
                return
            # ── judge 自述环境问题守卫（2026-08-28 伪 fix 级联事故防线，
            # 与主路径 pipeline._apply_bug_found 同序：speculative 门之后）──
            # judge 自己把全部 bug 根因描述为环境/基础设施问题时，属「验证没
            # 能发生」而非「验证发现了缺陷」，不得流转 bug-found 派生伪 fix
            # 级联。读的正是 legacy verifier 同样落盘的 verify-progress/<spec>/
            # .fenix-run-result.json primary 产物（见本文件上方 _read_verdict
            # 注释），经门面转发注册表（__getattr__ partial）复用 escalation
            # 实现，与既有 pipeline._handle_env_blocked_inconclusive 同一接入
            # 惯例；命中即按 inconclusive 处置（回 implemented 重验/超限升级）。
            if pipeline._judge_bugs_declare_env(spec_name) and pipeline._handle_judge_env_declared(
                spec_name
            ):
                return
            # ── 场景缺陷改道门豁免（有意缺位，记录豁免理由）──
            # 主路径 bug-found 的 _scenario_defect_reroute_gate（纯场景缺陷
            # 定向重派 judge 走 scenario-repaired 原地修复通道）在 legacy 车
            # 道维持豁免：legacy 降级车道无 scenario-repaired 重入通道（见下
            # 方 else 分支注释——plan-ready/scenario-repaired 裁决只能保持
            # testing 由 full_scan recovery 兜底重验），改道重派动作无处落地。
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
                    # 退款锚点回退 implementer_run（不传 run_id）；attempt
                    # run id 只作台账事件标识（attempt run id 不作预算退款锚点）。
                    ledger_run_id=getattr(result, "run_id", "") or "",
                )
                return
            # ── 守卫二：spawn 抑制（fix-repair-lane-dedup / design 守卫二）──
            # 被验对象为 fix spec 且自身 ready/implementing（重实现在飞）时
            # 修复由在飞重实现承载。MUST 在 bug-found transition 之前：命中即
            # 不流转、直接 return（若先流转再抑制，spec 已迁入 bug-found，
            # 状态与「由在飞重实现承载」语义不一致）。
            # 与主路径的决策差异（code-review item f18ca78e5203）：主路径
            # _apply_bug_found 已按 e1d3410c1e73 将本守卫整段移除（transition
            # 返回 True 后状态只可能 testing/bug-found，ready/implementing
            # 结构性不可达）；legacy 此处读的是 transition 前状态，该论证不
            # 直接迁移，防御性判据保留成本为零，故不同步移除、仅收敛其写点
            # 复核（见下）。
            if pipeline._context.is_fix_spec(spec_name):
                cur = (pipeline._context.state_machine.read_one(spec_name) or {}).get("status", "")
                if cur in ("ready", "implementing"):
                    pipeline._context.logger.info(
                        "pm_engine",
                        f"守卫二：'{spec_name}' 为 fix spec 且自身 {cur}"
                        f"（重实现在飞）——跳过派生子 fix（legacy 路径）",
                    )
                    # cur 读取与本 update_spec 之间存在 TOCTOU 窗口：窗口内
                    # spec 被并发拨回/冻结时，本次 error 覆写会抹掉冻结标记性
                    # error（本文件多处注释承认的同款事故风险）→ 与其余写点
                    # 同款，复核收敛于 _discard_if_not_testing（code-review
                    # item f18ca78e5203——此前全文件唯一未复核写点）。
                    if _discard_if_not_testing(pipeline, spec_name, result, "bug-found"):
                        return
                    pipeline._context.state_machine.update_spec(
                        spec_name,
                        {
                            "error": "修复由在飞重实现承载，跳过派生子 fix",
                        },
                    )
                    return
            # fix-env-exemption-exit-reachability D3（legacy 同语义，code-review
            # item 5ab0a792d828）：守卫链全过、即将按 bug-found 路由 → 清除
            # inconclusive 重验旗标恢复 judge 生命周期正计。legacy 车道入口
            # _handle_env_blocked_inconclusive 置位的旗标此前在本分支无清除点，
            # 后续轮 judge 派发持续分流 _judge_inconclusive_dispatches 独立
            # 计数器、_judge_rerun_count 生命周期账不累计。与主路径
            # _apply_bug_found 入口清除点同序；存在才写盘、写失败仅 WARNING，
            # 收口见 escalation._clear_inconclusive_reverify_flag。
            pipeline._clear_inconclusive_reverify_flag(spec_name)
            # transition 返回值校验（与 spec_review.py consume_review_result 同款）：
            # 前置守卫链与 transition 之间存在 TOCTOU 窗口，窗口内 spec 被
            # 人工冻结/并发接管致非法转移被拒时，保留原状——不覆写 error/
            # tester_run、不派生 fix（伪 fix 级联防护）。
            accepted = pipeline._context.state_machine.transition(
                spec_name, "bug-found",
                trigger_run_id=result.run_id, agent_type="tester", channel="auto",
            )
            if not accepted:
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"bug-found transition 被拒（转移非法，疑似冻结/并发接管）"
                    f"'{spec_name}' — 保留原状，不覆写字段、不派生 fix",
                )
                return
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
            # 本轮场景集变更小节追加到验证报告（spec 需求 2.3，与主路径
            # _apply_bug_found 及本文件 verified 分支同语义；code-review
            # item 2bd89b74e952——bug-found 分支两车道报告产物对称，
            # 同一 spec 走降级车道不再缺该小节）。
            pipeline._render_scenario_change_section_to_report(spec_name)
            pipeline._context.logger.warning(
                "pm_engine",
                f"Verifier (legacy) found bugs in '{spec_name}'",
            )
            # 到达 bug-found 归因（全部门禁已过、非 infra，归因已前置到
            # transition 之前）＝ product 类——
            # unknown 按 product 保守处置，台账 failure_class 记 product。
            pipeline._context.on_spec_bug_found(
                spec_name,
                failure_class="product",
                run_id=getattr(result, "run_id", "") or "",
            )
        elif verifier_status == "verified":
            # code-review 06ca08e65666：仅 verified 裁决落入成功晋级分支；
            # plan-ready/scenario-repaired 落入下方「验证未完成」分支，
            # MUST NOT 按通过收口。
            # ── 在飞 verify 结果状态判据·闸门写点前置复核（code-review
            # 12f6974d3d88）──
            # 复核前移到各闸门写点之前（与 unknown-status/unreadable 分支同
            # 序）：run_verifier 期间 spec 已漂移出 testing 时，进度核对/报告
            # 闸门阻断路径的 update_spec 不得覆写 error/tester_run（error 覆写
            # 曾抹掉 frozen 标记性 error 的事故同款风险）。transition 前仍保留
            # 同款复核收敛 TOCTOU 窗口。
            if _discard_if_not_testing(pipeline, spec_name, result, "verified"):
                return
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

            # 裁决 env 豁免握手（code-review item 9c0a88e8a705，与主路径
            # _apply_verified 同一道拦截点）：级二命中（裁决后失败全部为
            # 环境性）时 MUST NOT 落 verified——无 admin 放行处置记录转
            # inconclusive 重验（命中即 return，本轮不再到达洗白门禁，
            # 同一轮两道裁决后防线不叠加动作）；查得放行记录保留处置回链
            # 后放行；级二不命中零改动直通。legacy 分支此前缺此防线，
            # 环境性全败可经 legacy 车道自我批准落 verified。
            # ocr join 门禁不在此复刻：该门禁约束 impl-ocr 并行车道的
            # join（defer → 车道回调唤醒重评），legacy 车道为降级兼容
            # 路径、不消费并行车道产物，无 join 可等——豁免。
            if pipeline._handle_env_exemption_handshake(spec_name, report):
                return

            # verified 洗白门禁（help-center 0/15 verified 事故防线）：
            # 0 通过或 env 失败不得放行，升级 admin 处置
            if not pipeline._env_whitewash_gate(spec_name):
                return
            # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
            # 结果应用前 spec 已非 testing → DEBUG 丢弃，不走迁移与 fallback
            # 重派（拆除旧 reconcile：implemented→testing→verified 回放 +
            # 重派整轮 verifier）。02:13 事故即此路径：拨回 implemented 后在飞
            # 旧 judge 完成，结果被丢弃而非回退重派。判据与文案单点收敛于
            # _discard_if_not_testing（05d216e0182d）。
            if _discard_if_not_testing(pipeline, spec_name, result, "verified"):
                return

            # fix-env-exemption-exit-reachability D3（legacy 同语义，code-review
            # item 5ab0a792d828）：verified 放行 = judge 申报结论非全 env 之一 →
            # 清除 inconclusive 重验旗标恢复 judge 生命周期正计（legacy 车道入口
            # 置位的旗标此前在本分支无清除点，judge 派发持续分流
            # _judge_inconclusive_dispatches 独立计数器、_judge_rerun_count 不
            # 累计）。与主路径 _apply_verified 清除点同序——同在 env 豁免握手
            # 之后（级二命中握手提前 return，旗标保留到人工处置）；存在才写盘、
            # 写失败仅 WARNING，收口见 escalation._clear_inconclusive_reverify_flag。
            pipeline._clear_inconclusive_reverify_flag(spec_name)
            # transition 返回值校验（与 spec_review.py consume_review_result 同款）：
            # 前置守卫链与 transition 之间存在 TOCTOU 窗口（进度核对/报告闸门/
            # 洗白门禁多次读文件），窗口内 spec 被人工冻结/并发接管致非法转移
            # 被拒时，保留原状——不覆写字段、不推进采纳/收尾链。
            accepted = pipeline._context.state_machine.transition(
                spec_name, "verified",
                trigger_run_id=result.run_id, agent_type="tester", channel="auto",
            )
            if not accepted:
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"verified transition 被拒（转移非法，疑似冻结/并发接管）"
                    f"'{spec_name}' — 保留原状，不覆写字段、不推进收尾",
                )
                return
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": result.run_id,
                    "error": None,
                    # verified 收口清零/复位字段集单源（code-review item
                    # e143213f2b45，fastlane.VERIFIED_RESET_FIELDS）：含
                    # inconclusive/fail/infra/redo/env-block/infra-retry
                    # 计数、降档并行度复位、豁免与修订旗标、fastlane 连败
                    # 计数（bfe2b17dcfe2/efbdab0801f3）；与主路径
                    # _apply_verified 同引一张表，字段演进只改该表
                    # （legacy 车道清零语义同表同点）。
                    **VERIFIED_RESET_FIELDS,
                },
            )
            # 裁决采纳后落盘 verdict 稳定性轮次（judge-rerun-stability R1）
            pipeline._record_verdict_adoption(spec_name, "verified", report)
            # 失败历史侧车随 verified 终态清空（legacy 同语义，
            # fix-verdict-retry-misattribution D6）
            pipeline._clear_fail_history(spec_name)
            # 本轮场景集变更小节追加到验证报告（spec 需求 2.3，legacy 同语义）
            pipeline._render_scenario_change_section_to_report(spec_name)
            pipeline._context.on_spec_verified(spec_name)
        else:
            # code-review 06ca08e65666：plan-ready / scenario-repaired（及其它
            # 非 verified 的合法裁决）＝验证未完成，不按通过收口。plan-ready＝
            # 场景已（重）生成、执行阶段尚未真实跑过；scenario-repaired＝场景
            # 刚被原地修复、修复场景尚未真实重跑通过——新车道对二者有专门的
            # 重入通道（pipeline.py 改道重派 judge、escalation.py 原地修复
            # 重入），legacy 降级车道无对应通道：与「验证未完成」阻断路径
            # 同构，保持 testing 留 error、由 full_scan recovery 兜底重排
            # 重验，MUST NOT 落入 verified 成功晋级分支（否则修复场景未
            # 验证通过即假 verified 收口——done>=total 且通过数>0 时
            # _check_verification_gate 与 _env_whitewash_gate 均拦不住）。
            if _discard_if_not_testing(pipeline, spec_name, result, verifier_status):
                return
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "tester_run": result.run_id,
                    "error": (
                        f"验证未完成 (legacy)：裁决 status={verifier_status}"
                        f"（场景生成/场景修复裁决不按通过收口），保持 testing 待重验"
                    ),
                },
            )
            pipeline._context.logger.warning(
                "pm_engine",
                f"验证未完成 (legacy) '{spec_name}'：plan-ready/scenario-repaired "
                f"裁决不按通过收口（status={verifier_status}），保持 testing 待重验",
            )
    else:
        # ── 在飞 verify 结果状态判据（fix-daemon-lifecycle-races D6）──
        # 进程失败分支与上两个分支（bug-found/verified）同款复核：入口
        # testing 判据之后 run_verifier 期间状态已漂移（拨回 implemented/
        # 并发接管）→ DEBUG 丢弃陈旧失败结果，不 transition bug-found、
        # 不覆盖 error/tester_run。判据与文案单点收敛于
        # _discard_if_not_testing（05d216e0182d）。复核先行、verified 放行门
        # 在后，与其余三分支（bug-found/verified/unknown-status/unreadable）
        # 同构（code-review item 60077ba8eaae；命中时均 return，终局等价）。
        if _discard_if_not_testing(pipeline, spec_name, result, "process-failure"):
            return
        # ── verified 一次性放行门（judge-rerun-stability R2）──
        # verifier agent 进程失败的降级同样不得覆盖已 verified 结论。
        if pipeline._verified_gate_refuses(spec_name, "bug-found"):
            return
        # ── 进程级死亡分流（evo-add-verifier-infra-death-triage 2.2，归因链上游）──
        # verifier run 终局失败且满足进程级死亡特征（终局 assistant 轮数为 0，
        # 或全部 attempt 存活低于秒挂判定阈值——存活口径取终局结果
        # duration_seconds，run 级总存活上界）＝「验证没能发生」而非「验证
        # 发现了缺陷」（2026-10-14 add-harness-brand-projection 实证：dsh 补丁
        # ENOENT 秒死 3+3 试全灭，词表不命中 → unknown → 按 product 保守处置
        # → bug-found → 原地打回，烧掉一轮 9.8 万 token 零产出复核 run）。
        # MUST 在 enrich_failure_class 归因之前消费：死亡命中走「infra 台账
        # 限次廉价重派 / 超限 freeze_for_human 暂挂」两出口，两路均不 transition
        # bug-found、不消耗实现尝试预算（与 engine 双路径异常守卫同一精神——
        # 该守卫只覆盖抛异常路径，legacy 内部消费失败不抛异常，本分流补齐）。
        # 错误指纹（ENOENT/启动期即退）仅作台账辅助标注，不作命中条件。
        if is_verifier_process_death(result):
            _death_err = getattr(result, "error", "") or ""
            _fingerprint = annotate_death_fingerprint(_death_err)
            _death_reason = (
                f"verifier 进程级死亡（turns_used=0 或存活<"
                f"{VERIFIER_DEATH_SURVIVAL_THRESHOLD_SECONDS:.0f}s，"
                f"指纹={_fingerprint}）: {_death_err[:200]}"
            )
            # ── infra 记账单点入账（retry_gate=True 兼任限次决议）──
            # 记账（预算退款 + _verify_infra_rounds 观测账 + 失败台账）与
            # resolve_infra_retry_decision 专用计数 +1 在同一调用完成；
            # "escalate" 决议后 MUST NOT 二次调用（观测账/退款双计，
            # infra_classify._record_infra_failure docstring 契约）。台账
            # （_verify_infra_retry_streak）清零点与验证 PASS + unfreeze_spec
            # 清单同点，不新增平行台账。
            _decision = pipeline._record_infra_failure(
                spec_name,
                _death_reason,
                retry_gate=True,
                # 退款锚点回退 implementer_run（不传 run_id）；attempt run id
                # 只作台账事件标识（attempt run id 不作预算退款锚点）。
                ledger_run_id=getattr(result, "run_id", "") or "",
            )
            if _decision == "redispatch":
                # ── 限次内廉价重派：不计 env 冻结轮、不呼叫 admin、不流转
                # bug-found。spec 保持 testing，经既有 verifier 派发入口重新
                # 入队（对齐 pipeline 可达性 fail-fast 车道 D5 同款机械路径；
                # 接线缺失或派发异常 fail-open 回落 context 直接 enqueue）。
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"进程级死亡分流命中（infra-retry 限内）'{spec_name}'："
                    f"不判 bug-found、不计 env 冻结轮，廉价重派验证 — "
                    f"{_death_reason}",
                )
                _schedule = getattr(
                    pipeline._context, "schedule_infra_retry_redispatch", None
                )
                try:
                    if _schedule is not None:
                        _schedule(spec_name)
                    else:
                        pipeline._context.enqueue(spec_name, "verifier")
                except Exception as exc:
                    pipeline._context.logger.error(
                        "pm_engine",
                        f"进程级死亡重派触发失败，回落直接入队 '{spec_name}': {exc}",
                    )
                    try:
                        pipeline._context.enqueue(spec_name, "verifier")
                    except Exception as exc2:
                        pipeline._context.logger.error(
                            "pm_engine",
                            f"进程级死亡重派入队失败（保持 testing 由 recovery "
                            f"兜底重排）'{spec_name}': {exc2}",
                        )
                return
            # ── 超限：freeze_for_human 验证暂挂（blocked+frozen+admin 信号，
            # 对齐 _escalate_env_blocked 既有升级形态），不 transition bug-found、
            # 不原地打回。保留 reclassify_infra_rounds / unfreeze_spec 人工
            # 回拨兜底（解冻清零清单含 _verify_infra_retry_streak）。
            _freeze_note = (
                f"verifier 进程级基础设施死亡连续达重派上限（{_death_reason}）"
                f"— 已冻结验证转人工，未判 bug-found、未消耗实现预算"
            )
            pipeline._context.logger.error(
                "pm_engine",
                f"进程级死亡分流超限 '{spec_name}'：freeze_for_human 暂挂验证"
                f"（不 transition bug-found）— {_death_reason}",
            )
            pipeline._context.state_machine.freeze_for_human(
                spec_name,
                error=_freeze_note,
                signal_type="verifier_infra_death",
                severity="critical",
                description=_freeze_note,
                evidence=(
                    f"spec={spec_name}; run={getattr(result, 'run_id', '') or ''}; "
                    f"turns_used={getattr(result, 'turns_used', None)}; "
                    f"duration_seconds={getattr(result, 'duration_seconds', None)}; "
                    f"fingerprint={_fingerprint}; error={_death_err[:200]}"
                ),
                recommended_action=(
                    "验证 agent 启动期即死（0 轮/秒挂），非产品缺陷：检查 runner/"
                    "网关/CLI 环境（补丁文件缺失、二进制不可达、额度耗尽等）修复后 "
                    "unfreeze_spec 清零重试（解冻即清零 infra 重派计数）；确认为"
                    "实现问题时人工拨回 implemented 重实现"
                ),
                alert_callback=pipeline._context.escalation_notifier,
                extra_updates={
                    # 死亡 run 已终局：清 tester_run 防在飞判定误认（对齐
                    # _detect_uniform_verify_failure 冻结同款收口）。
                    "tester_run": None,
                },
            )
            return
        # ── 统一失败归因入口（code-review 0d478d8f37ce，与 verdict bug-found
        # 分支对齐）──
        # 进程失败分支上游只经过早期 infra 门（_verifier_error_is_infra：熔断/
        # 链耗尽/切换类），该门不匹配 worktree/merge conflict/tree dirty 标记；
        # enrich_failure_class 比早期门多匹配这三类标记——error 含这些文本时
        # 若直接流转 bug-found 即重演「先流转再归因」失效（spec 停在 bug-found
        # 却不派生 fix，状态回退只能靠 recovery 兜底）。MUST 在 bug-found
        # transition 之前：infra 命中按 infra 记账退款并保持原状态。
        failure_class = pipeline.enrich_failure_class(
            spec_name,
            error_text=getattr(result, "error", "") or "",
        )
        if failure_class == "infra":
            pipeline._context.logger.warning(
                "pm_engine",
                f"归因入口判 infra（legacy 进程失败）：'{spec_name}' 按 infra 记账，"
                f"不流转 bug-found、不派生 fix",
            )
            pipeline._record_infra_failure(
                spec_name,
                "infra at attribution entry (legacy process-failure)",
                # 退款锚点回退 implementer_run（不传 run_id）；attempt
                # run id 只作台账事件标识（attempt run id 不作预算退款锚点）。
                ledger_run_id=getattr(result, "run_id", "") or "",
            )
            return
        # transition 返回值校验（与 bug-found/verified 分支同款）：前置守卫链
        # 与 transition 之间存在 TOCTOU 窗口，窗口内 spec 被人工冻结/并发接管
        # 致非法转移被拒时，保留原状——不覆写 error/tester_run（error 覆写曾
        # 发生抹掉 frozen 标记性 error 的事故）。
        accepted = pipeline._context.state_machine.transition(
            spec_name, "bug-found",
            trigger_run_id=result.run_id, agent_type="tester", channel="auto",
        )
        if not accepted:
            pipeline._context.logger.warning(
                "pm_engine",
                f"bug-found transition 被拒（转移非法，疑似冻结/并发接管）"
                f"'{spec_name}' — 保留原状，不覆写字段",
            )
            return
        # [fenix-ignore:25628c32f523] 失败台账非失明：bug-found 采纳后与 fix 派生同理依赖 recovery 兜底——event_bus full_scan 对滞留 bug-found 态 re-trigger spec_bug_found（无时间门槛）→ _do_spec_bug_found 同一调用内 bump _verify_fail_rounds 并 _append_fail_history（failure_class=product，family.py :780-786，升级分型读账晚于该追加），derive/cap/子 fix 守卫对两条 bug-found 入口对称生效，回拨参考台账含本轮。
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "tester_run": result.run_id,
                "error": f"Verifier agent failed: {result.error or ''}",
                # code-review item f7a38d6f8f25：进程失败属「验证没能发生」，
                # inconclusive 暂停语义不应跨迁移残留——escalation 的
                # inconclusive 重派先写非零 _inconclusive_attempts 再派
                # verifier（escalation 写点），若该在飞 run 进程失败走到本
                # 分支，残留计数会令 event_bus 两个自动重验恢复出口
                # （_inconclusive_paused）按「暂停自动重验、等待人工处置」
                # 跳过。与同目标 verdict bug-found 分支（上方 :584-587）及
                # 主路径采纳点同款复位。
                "_inconclusive_attempts": 0,
                # add-verify-parallel-backoff / design D2：bug-found 属健康轮，
                # 降档并行度同轮复位（legacy 路径同语义）。
                "_verify_parallel_override": None,
            },
        )
        # fix 派生有意依赖 recovery 兜底，非遗漏（code-review 90e23fbbec42）：
        # 此处不调用 on_spec_bug_found——event_bus full_scan 对滞留 bug-found
        # 态 re-trigger spec_bug_found（core/event_bus.py 339-341），经
        # _do_spec_bug_found 统一派生 fix；在此补调会重复派发。
