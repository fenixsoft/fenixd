"""core.pm_engine.verification.escalation — env 阻塞升级/告警/防御（refactor-verification-module D2）。

从 VerificationPipeline 摘出的 env 阻塞级升级通道、conclusive 处理、洗白门禁、
告警 streak 维护、陈旧三线告警、场景缺陷改道、judge env 声明、投机 bug 门禁。
纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# add-blocked-reverify-lane D3：env 阻塞轮次计数字段
from core.state_machine import (
    ENV_BLOCK_ROUNDS_FIELD,
    # env 阻塞冻结阈值单点定义在 core.state_machine（与 ENV_BLOCK_ROUNDS_FIELD
    # 同源，防阈值语义漂移）
    ENV_BLOCK_FREEZE_THRESHOLD,
    # 冻结标记字段单源（code-review item f7dc3c016004）：与 branch_guard /
    # infra_classify 同引常量，字面量在字段演进时会静默写错键致冻结标记丢失
    FROZEN_FIELD,
    FREEZE_ERROR_PREFIX,
    # judge-scenario-repair：judge 原地场景修复预算单点定义在 core.state_machine
    # （与 pipeline.py 同源，防两侧调参漂移）
    _SCENARIO_REPAIR_MAX_ROUNDS,
)

# tmp+replace 原子写助手（core/fs_utils 单点实现；code-review 45390e0eb835：
# 此前引 scenario_gate 同名助手，全仓存在两套同名不同行为的 tmp+replace
# 原子写，持久性/权限语义随导入路径漂移——收敛到 fs_utils 单点实现）：
# 本模块会被回读的状态侧车 JSON 落盘点（triage_recheck 追加与剪枝 /
# scenario_reroute_stoploss / scenario_reroute_directive）统一原子写——裸写
# 中途被杀会留截断文件，已积累的复核清单/止损留存静默丢失
# （code-review ef9941a3a42b）。
from core.fs_utils import atomic_write_text
from core.timelib import parse_ts

# fix-recovery-path-blockers D3：预算耗尽重验延时常量（30 分钟，
# 与 schedule.poll_interval_minutes 缺省对齐）。定时器管准点、周期扫描管兜底
# ——daemon 重启后定时器丢失，靠 `_dispatch_backoff_until` 兜底
# （spec_is_undriven 条件③ 在退避窗内为真、探测器静默；到期后
# event_bus._recover_testing 周期扫描拾取，最坏延迟 = 一个 poll_interval）。
# MUST NOT 误引 `check_scheduling_deadlines`——它只覆盖 drafted/ready 拾取，
# testing 态不在其覆盖范围。
# 注：env 阻塞 inconclusive 升级路径写 `_dispatch_backoff_until` 的退避窗
# （本文件 4 处）复用同一时长——共用「30 分钟 / poll_interval 对齐」语义，
# 调参在此一处生效。
_SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS = 1800

# 重验定时器排程互斥锁：判重（check）与占位（act）须同锁原子完成——并发
# 进入排程路径时先占位成功者才建定时器，杜绝同 spec 双 Timer（仿 backoff.py
# `_schedule_instant_fail_recovery` 的锁内排程模式）。模块级锁：`_reverify_timers`
# 集合 per-pipeline lazy 挂载，锁若随集合 lazy 创建则锁自身初始化仍有竞态。
_REVERIFY_TIMERS_LOCK = threading.Lock()


def _read_int_config(pipeline, key: str, default: int) -> int:
    """读取整数配置并防御性转换（code-review f65f6eeec868）。

    原 `int(config_reader(...) or N)` 模式：yaml 误配非数字串时 int() 抛
    ValueError 沿裁决路径上抛；且 `or N` 把合法的 0 归一为缺省，无法用 0
    关闭自动重验。此处与 _handle_*_inconclusive 的 attempts 解析同款防御：
    None 显式判空回退缺省、非数字回退缺省、0 原样透传。
    """
    try:
        value = pipeline._context.config_reader(key, default)
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _summary_count(pipeline, spec_name: str, summary: dict, field: str) -> int:
    """读取 report.json summary 计数并防御性转换（code-review db671dba96d3）。

    原裸 `int(summary.get(field, 0) or 0)` 模式：计数被写坏为非数字串
    （外部编辑/半截写残留）时 int() 抛 ValueError 沿
    _handle_env_blocked_inconclusive / _handle_verdict_env_exemption_inconclusive
    逃出到 pipeline 裁决路径，本轮 verdict 处置中断。比照同文件记账字段
    兜底口径（_inconclusive_attempts / ENV_BLOCK_ROUNDS_FIELD /
    _credibility_gate_attempts）：脏值回退 0 并记 WARNING，不让记账字段
    脏值瘫痪升级通道。
    """
    try:
        return int(summary.get(field, 0) or 0)
    except (TypeError, ValueError):
        pipeline._context.logger.warning(
            "pm_engine",
            f"'{spec_name}' report summary.{field} 字段脏值（非数字），"
            f"已按 0 兜底继续本轮判定",
        )
        return 0


def _escalate_threshold_note(
    attempts: int, max_attempts: int, escalate_attempts: int
) -> str:
    """按实际命中的升级条件生成阈值文案（code-review 974c5b39ad17）。

    升级分支条件是 ``attempts >= escalate_attempts or attempts >= max_attempts``：
    缺省（max_attempts=3、escalate_attempts=4）下第 3 轮即经重验上限升级，
    文案若固定写「已达升级阈值 4」会虚报重验轮数，干扰人工对重验预算的
    判断。三处 inconclusive 升级处理器共用本构造点，避免分支文案各自漂移。
    """
    if attempts >= max_attempts:
        return f"已达重验上限 {max_attempts}"
    return f"已达升级阈值 {escalate_attempts}"


# 升级停车 error 文案的稳定特征子串（fix-env-exemption-exit-reachability 4.5）：
# reset_verification 前置状态门按此识别本能力域停车形态（implemented +
# _inconclusive_attempts>0 + 本特征命中），escalation 写侧与 admin_actions 读侧
# 共用同一常量防文案漂移。刻意不含 FREEZE_ERROR_PREFIX——本设计是「暂停自动
# 重验等人工裁决」而非结构化冻结，人工经 choices 一键处置，不走 unfreeze 通道。
INCONCLUSIVE_PARKING_ERROR_MARKER = "等待人工豁免或修环境裁决"


def _inconclusive_fail_signature(pipeline, spec_name: str, report: dict) -> str:
    """本轮 inconclusive 失败签名摘要（fix-env-exemption-exit-reachability 1.2/2.2）。

    从 report.json 场景表现算（MUST NOT 以 fail_history.json 为基准——其条目
    仅存场景 id 集且仅在归因失败轮追加、inconclusive 轮不落台账）。单场景
    片段推导收拢至 ``state_machine.scenario_fail_signature`` 单源
    （evo-fix-env-exemption-gate-conflict-…：豁免键的签名口径与本摘要一致，
    grant 时落库、校验时重算共用同一推导，防双处漂移）：

      - 非 pass 场景：首失败断言 ``type + 归一化 actual`` 摘要（数字→N、
        去引号、折叠空白）；failed_assertions 缺失时兼容
        assertion_results / assertion 历史字段（verdict_check 同款兼容序），
        仍无则回退「场景级 classification + first_failed_step」；
      - blocked-env 场景（从未执行、无失败断言）：签名退化为
        ``<sid>:blocked-env``，签名整体附 blocked 计数——足以表达「环境未变化」。

    片段排序后拼接（场景序跨轮可能被 planner 重排，排序保证可比）；无失败
    场景（report 不可得/空）返回空串——调用方按「本轮签名未知」处理，不参与
    一致性判定。签名同时用于 SIGNAL/告警 evidence 组装（供人工核对）与
    STATE ``_last_inconclusive_signature`` 跨轮比较基准回写。
    """
    from core.state_machine import scenario_fail_signature

    fragments: list = []
    blocked_count = 0
    for sc in (report or {}).get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        if sc.get("status") in ("pass", "passed"):
            continue
        if sc.get("status") == "blocked-env":
            blocked_count += 1
        fragments.append(scenario_fail_signature(sc))
    if not fragments:
        return ""
    fragments.sort()
    head_note = f"blocked={blocked_count}" if blocked_count else ""
    return ";".join(fragments) + (f"|{head_note}" if head_note else "")


def _load_frozen_scenario_hashes(project_root, spec_name: str) -> dict:
    """读冻结场景定义文件算 ``{场景 id: 定义 hash}``（本 SPEC 1.4 失效锚点）。

    实现单源在 ``core.state_machine.load_frozen_scenario_hashes``（grant 写入
    与双门校验同引同一读取口径，防「写入 A 校验 B」的副本漂移）。
    """
    from core.state_machine import load_frozen_scenario_hashes

    return load_frozen_scenario_hashes(project_root, spec_name)


def _env_exemption_matches(pipeline, spec_name: str, report: dict, entry: dict,
                           hashes: dict) -> list:
    """逐个非 pass 场景查有效 STATE 豁免，返回全部命中豁免清单。

    ``_env_exemptions_cover`` 与握手豁免回链共用的判定内核
    （code-review 9fc208d8395a：覆盖判定与回链组装走同一循环，防两处
    谓词漂移）：调用前提级二已命中（报告失败全部被裁决 env）——任一非
    pass 场景未命中有效豁免（场景 id+归一化失败签名+定义 hash+时效，
    ``state_machine.find_env_exemption`` 同一纯函数；含 STATE 读失败=
    无豁免，fail-closed）即未全覆盖 → 返回空清单；全部命中 → 按场景序
    返回命中豁免对象（含 granted_at / scenario_id / disposition_id，
    供回链与日志组装）。
    """
    from core.state_machine import find_env_exemption, scenario_fail_signature_body

    scenarios = (report or {}).get("scenarios") or []
    if not scenarios:
        return []
    matches: list = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            return []
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "?")
        ex = find_env_exemption(
            entry, sid, scenario_fail_signature_body(sc),
            current_hash=str(hashes.get(sid) or ""),
        )
        if ex is None:
            return []
        matches.append(ex)
    return matches


def _env_exemptions_cover(pipeline, spec_name: str, report: dict, entry: dict,
                          hashes: dict) -> bool:
    """本轮全部 env 失败场景是否都有有效 STATE 豁免命中（双门同源判定）。

    调用前提：级二已命中（报告失败全部被裁决 env）。判定内核收拢至
    ``_env_exemption_matches``——全部命中且至少一个豁免对象即覆盖，
    任一未命中（fail-closed）→ 不覆盖。
    """
    return bool(_env_exemption_matches(
        pipeline, spec_name, report, entry, hashes
    ))


def _escalate_inconclusive_parking(
    pipeline,
    spec_name: str,
    attempts: int,
    blocked_env: int,
    report: dict,
    signature: str,
    threshold_note: str,
    env_note: str = "",
    signal_description: str | None = None,
) -> None:
    """inconclusive 升级停车共用收口（fix-env-exemption-exit-reachability 1.1/2.1）。

    级二首次命中与级一（签名一致提前升级 / 计数到顶）的升级停车走同一条
    通道，避免三处各自漂移：

      1. 写 inconclusive_loop SIGNAL（kind=SIGNAL，Administrator 通道，保住
         ``latest_resolved_disposition(spec, "inconclusive_loop")`` 放行查询
         锚点），evidence 附本轮失败签名摘要与 attempts 当前值；
      2. 经 ``escalation_notifier`` 发带 choices 的人工告警（severity=major，
         choices 由注册表按 signal_type 自动附加）——SIGNAL 与 ESCALATION
         双通道并存：Administrator 可自动核查环境，人工可一键豁免；
      3. spec 停 implemented、tester_run 清空、error 写等待人工裁决文案
         （不用 FREEZE_ERROR_PREFIX——本设计是暂停自动重验等裁决而非结构化
         冻结，人工经 choices 解锁，不走 unfreeze 通道）、
         ``_dispatch_backoff_until`` 置退避防 orphaned_state 误报；
      4. 置 ``_in_inconclusive_reverify`` 旗标（judge 预算隔离，design D3）、
         回写 ``_last_inconclusive_signature``（下一轮比较基准）。

    升级后停止自动重验（MUST NOT enqueue verifier）——人工处置是唯一出路。
    SIGNAL 写失败静默降级（error 字段已承载人工可见信息）；告警失败仅
    WARNING 留痕（升级通道自身失败不得抛穿裁决流程）。
    """
    env_note = f"，{env_note}" if env_note else ""
    human_description = (
        f"'{spec_name}' 连续 {attempts} 轮验证失败均被裁决归类 env"
        f"（{threshold_note}{env_note}），judge 已裁决全部失败归环境、"
        f"等待人工豁免或修环境——自动重验已停止"
    )
    pipeline._write_inconclusive_loop_signal(
        spec_name,
        attempts,
        blocked_env,
        report or {},
        description=signal_description,
        threshold_note=threshold_note,
        signature=signature,
    )
    try:
        pipeline._context.escalation_notifier(
            spec_name=spec_name,
            signal_type="inconclusive_loop",
            severity="major",
            description=human_description,
            evidence=(
                f"spec={spec_name}; 连续轮数={attempts}; "
                f"末轮blocked_env数={blocked_env}; "
                f"签名摘要={signature or '无'}"
            ),
            recommended_action=(
                "人工裁决三选一：① 确认失败确属环境且不可修复 → 授予 env 豁免"
                "（grant_env_exemption：落放行记录并重置重验，下轮 verified 合法"
                "生效带豁免回链）；② 已修复环境 → manual_fixed_reverify 重置重验；"
                "③ 放弃该 spec → abandon。Administrator 可按 SIGNAL 同步核查环境"
            ),
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"inconclusive 升级人工告警失败 '{spec_name}'（非阻塞）: "
            f"{type(e).__name__}: {e}",
        )
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "status": "implemented",
            "tester_run": None,
            "error": (
                f"连续 {attempts} 轮验证失败均被裁决归类 env"
                f"（{threshold_note}{env_note}），无 admin 放行处置记录 — "
                f"{INCONCLUSIVE_PARKING_ERROR_MARKER}"
                f"（choices：grant_env_exemption / manual_fixed_reverify / "
                f"abandon）；自动重验已停止"
            ),
            "_inconclusive_attempts": attempts,
            "_last_inconclusive_signature": signature or "",
            "_in_inconclusive_reverify": True,
            "_dispatch_backoff_until": (
                int(datetime.now(timezone.utc).timestamp())
                + _SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS
            ),
        },
    )
    pipeline._context.logger.error(
        "pm_engine",
        f"'{spec_name}' 连续 {attempts} 轮验证失败均被裁决归类 env"
        f"（{threshold_note}{env_note}）— SIGNAL + 人工告警已发，"
        f"暂停自动重验等待人工豁免或修环境裁决",
    )


def _clear_inconclusive_reverify_flag(pipeline, spec_name: str) -> None:
    """清除 inconclusive 重验旗标，恢复 judge 生命周期正计（3.2 单一收口）。

    judge 申报结论非全 env（bug-found 路由 / verified 放行 / scenario-repaired
    重入决策点）时调用——正常路由的 judge 消耗照旧计入 ``_judge_rerun_count``
    生命周期账。旗标为真才写盘（避免每轮无谓写盘，与 _verify_parallel_override
    存在才清同款）；写失败仅 WARNING——旗标滞留的兜底由 verified 落定清零点
    与 ``_judge_inconclusive_dispatches`` 独立上限承担。
    """
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    flag = str(entry.get("_in_inconclusive_reverify") or "").strip().lower()
    if flag not in ("true", "1"):
        return
    try:
        pipeline._context.state_machine.update_spec(
            spec_name, {"_in_inconclusive_reverify": False}
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"inconclusive 重验旗标清除失败 '{spec_name}'（不阻断路由）: "
            f"{type(e).__name__}: {e}",
        )


# [fenix-ignore:d5f83f2038f4] 三处 inconclusive 升级停车均已共用
# _escalate_inconclusive_parking 收口（922e79f7a511 停止分支合并；judge
# 自述形态经 5a9cdf9b2dac 并入），残留分歧仅在各自非升级分支：重验文案、
# env 阻塞形态的并行降档与签名基准（judge 自述形态无 blocked-env 签名，
# 按空串回写）——参数化抽取风险大于收益，暂不共享实现
def _handle_env_blocked_inconclusive(pipeline, spec_name: str, report: dict) -> bool:
    """环境性失联门禁：全批 blocked-env → inconclusive → 保持 testing 重派新 attempt。

    inconclusive 判据（design D2）：summary.blocked_env > 0 且有效失败
    （failed + errors）为 0，即该轮原始失败全部为 blocked-env。

    处理：spec 回 implemented（verifier 派发门禁要求）→ 排队重验新 attempt；
    **不向 admin store 发 repeated_failures 信号**——本方法不产生 error 终态
    run 产物，repeated_failures 检测天然不累积（连续 inconclusive 不唤醒
    Administrator，对应 spec Scenario）。

    重验上限缺省 2（verify_engine.inconclusive_max_attempts 可调，
    fix-env-exemption-exit-reachability 2.1：3→2——级一面向瞬时环境抖动，
    同签名复现即无新信息，长烧无收益；缺省值与同键全部读取点同步）。
    连续超限后升级停车（``_escalate_inconclusive_parking``：SIGNAL + 人工
    告警 + 停止自动重验，code-review 922e79f7a511 停止收口与升级合并语义
    不变）。

    提前升级（2.1/2.2）：本轮失败签名（``_inconclusive_fail_signature``）
    与 STATE 上一轮摘要（``_last_inconclusive_signature``，上一轮 inconclusive
    处置点回写）完全一致 → 视为「环境未变化、重验必复现」，不等计数到顶
    直接升级停车。基准缺失/不可解析（首轮、人工重置后）按「上一轮签名
    未知」处理——不提前升级，保守走计数上限（防首轮误停）。

    Returns:
        True 表示本轮已按 inconclusive 处理（调用方跳过 bug-found/verified
        判定）；False 表示无环境性失联，按既有判定继续。
    """
    summary = report.get("summary") or {}
    blocked_env = _summary_count(pipeline, spec_name, summary, "blocked_env")
    failed = _summary_count(pipeline, spec_name, summary, "failed")
    errors = _summary_count(pipeline, spec_name, summary, "errors")
    spec = pipeline._context.state_machine.read_one(spec_name) or {}
    if blocked_env <= 0 or (failed + errors) > 0:
        # add-verify-parallel-backoff / design D2：非 inconclusive 判定即
        # 健康轮（出现真实 verdict），复位降档并行度——存在才清，避免每轮
        # 无谓写盘（与 _inconclusive_attempts 同生命周期：链条断即复位）。
        if "_verify_parallel_override" in spec:
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "_verify_parallel_override": None,
                },
            )
        return False

    try:
        attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    max_attempts = _read_int_config(
        pipeline, "verify_engine.inconclusive_max_attempts", 2
    )
    escalate_attempts = _read_int_config(
        pipeline, "verify_engine.inconclusive_escalate_attempts", 4
    )
    signature = _inconclusive_fail_signature(pipeline, spec_name, report)

    # ── 签名一致提前升级（fix-env-exemption-exit-reachability 2.1/2.2）──
    # 比较基准 = 上一轮 inconclusive 处置点回写 STATE 的
    # _last_inconclusive_signature（与 _inconclusive_attempts 同生命周期，
    # 人工重置清零后自然失效）。两侧非空且完全一致才判「环境未变化」；
    # 任一侧为空（首轮/重置后/report 不可得）按签名未知处理，保守走计数
    # 上限，不制造新的停止点。
    prev_signature = str(spec.get("_last_inconclusive_signature") or "").strip()
    if prev_signature and signature and prev_signature == signature:
        pipeline._context.logger.warning(
            "pm_engine",
            f"'{spec_name}' 本轮 {blocked_env} 个失败场景全部为 blocked-env，"
            f"失败签名与上一轮完全一致（环境未变化，重验必复现）— "
            f"跳过剩余重验，直接升级停车",
        )
        _escalate_inconclusive_parking(
            pipeline,
            spec_name,
            attempts,
            blocked_env,
            report,
            signature,
            threshold_note="重验失败签名与上一轮完全一致（环境未变化）",
            signal_description=(
                f"'{spec_name}' 连续 {attempts} 轮验证全部为 blocked-env"
                f"（环境性失联）且失败签名与上一轮完全一致——环境未变化、"
                f"重验必复现，请人工修复环境或授予豁免"
            ),
        )
        return True

    # ── B7 升级通道（add-verdict-credibility-gate / design D6）──
    # 达升级阈值（缺省 4）或达重验上限（attempts >= max_attempts，缺省 2，
    # 停止收口与升级合并，code-review 922e79f7a511）：升级停车（SIGNAL +
    # 人工告警）。三层既有检测口径（repeated_failures / stuck / blocked_stuck）
    # 均实证错过该故障形态，不可依赖它们。写入后停止自动重验：计数不清零
    # 则 recovery（B6）保持跳过，人工处置是唯一出路。
    if attempts >= escalate_attempts or attempts >= max_attempts:
        _escalate_inconclusive_parking(
            pipeline,
            spec_name,
            attempts,
            blocked_env,
            report,
            signature,
            threshold_note=_escalate_threshold_note(
                attempts, max_attempts, escalate_attempts
            ),
        )
        return True

    if attempts < max_attempts:
        pipeline._context.logger.warning(
            "pm_engine",
            f"'{spec_name}' 本轮 {blocked_env} 个失败场景全部为 blocked-env"
            f"（环境性失联），verdict=inconclusive，第 {attempts}/{max_attempts} 次重验",
        )
        updates = {
            "status": "implemented",
            "tester_run": None,
            "error": (
                f"环境性失联：{blocked_env} 个失败场景均 blocked-env，"
                f"第 {attempts}/{max_attempts} 次重验（inconclusive 不判 fail）"
            ),
            "_inconclusive_attempts": attempts,
            # 2.2：回写本轮签名摘要——下一轮 inconclusive 处置点的比较基准
            # （与 _inconclusive_attempts 同生命周期，人工重置清零后失效）。
            "_last_inconclusive_signature": signature,
            # 预算隔离（design D3）：本重验轮若触发 judge 派发，计入独立
            # 计数器而非 _judge_rerun_count 生命周期账。
            "_in_inconclusive_reverify": True,
        }
        # add-verify-parallel-backoff / design D1：连续 blocked-env 重验按
        # attempt 递减有效并行度——attempts≥2 起降档（配置值逐轮减半向下
        # 取整、下限 1），首轮不降档（白屏证据尚不存在，降档会冤枉健康
        # 环境）。下一轮 VerifyEngine 构造时读取覆盖 max_parallel。
        if attempts >= 2:
            base = _read_int_config(pipeline, "verify_engine.max_parallel", 5)
            updates["_verify_parallel_override"] = max(1, base >> (attempts - 1))
        pipeline._context.state_machine.update_spec(spec_name, updates)
        pipeline._context.enqueue(spec_name, "verifier")
        return True

    # 显式兜底：升级分支已覆盖 attempts >= max_attempts，到达此处条件恒真
    # ——恒按 inconclusive 处理、恒返回 True。显式写出避免隐式 None 出口
    # 被调用方按真值消费时静默传播。
    return True


def _env_whitewash_gate(pipeline, spec_name: str) -> bool:
    """verified 推进前的洗白不变量门禁（help-center 0/15 verified 事故防线）。

    verdict=verified 但 0 通过或存在 env 分类失败 → 阻断推进并升级：
    阻塞 spec → 自动呼叫 Administrator 处置环境 → 连续
    ENV_BLOCK_FREEZE_THRESHOLD 轮仍 env → 结构化冻结转人工。
    Returns: True=放行推进 verified；False=已升级处置（调用方直接 return）。

    evo-fix-env-exemption-gate-conflict-…（1.2/1.3）：env 项违规先查 spec 级
    STATE 豁免（与升级握手同一纯函数 ``find_env_exemption``，同源消除
    「握手认可、门禁拒绝」矛盾）；命中有效豁免的 env 场景不计入违规。
    豁免有效命中轮（仅剩 0-pass 等非 env 违规）升级时标记
    ``exemption_effective``——不计入 ENV_BLOCK_FREEZE_THRESHOLD（豁免认可
    不得仍滑向冻结；TTL 过期或场景变更失效后恢复计数，冻结兜底保留）。
    """
    from core.state_machine import parse_env_exemptions
    from core.verdict_check import load_report, whitewash_violations

    scenarios = []
    report = load_report(pipeline._context.project_root, spec_name)
    if report:
        scenarios = report.get("scenarios") or []
    if not scenarios:
        # report.json 缺位时回退结果文件场景（fast-track 等价路径）；
        # 读取异常一律视为无数据（门禁不制造新的失败模式）
        try:
            ft = pipeline._context.read_implementer_result(spec_name) or {}
            # fix-impl-tasks-completion-gate D6：partial 是「诚实申报未完成」
            # 的合法终态——其 verification 段是未完成形态，不得当作 verified
            # 洗白门禁的场景证据采信（partial 轮不会走到 verified 推进，此处
            # 为 fail-safe 兜底：按无数据处理，交既有闸门拦截）。
            if ft.get("status") == "partial":
                scenarios = []
            else:
                verification = ft.get("verification")
                if isinstance(verification, dict):
                    scenarios = verification.get("scenarios") or []
        except Exception:
            scenarios = []
    if not scenarios:
        return True  # 无场景数据不拦（保守放行，交既有闸门兜底）
    # 双门同源豁免上下文：STATE 豁免清单 + 当前冻结场景定义 hash（读失败=
    # 无失效证据，与 env_exemption_active 口径一致）
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    exemptions = parse_env_exemptions(entry)
    hashes = _load_frozen_scenario_hashes(
        pipeline._context.project_root, spec_name
    ) if exemptions else {}
    violations = whitewash_violations(
        scenarios, "verified",
        env_exemptions=exemptions, scenario_hashes=hashes,
    )
    if not violations:
        return True
    # 豁免有效判别：无豁免视角下 env 违规存在、豁免视角被摘除 → 豁免生效轮
    exemption_effective = False
    if exemptions:
        raw_violations = whitewash_violations(scenarios, "verified")
        exemption_effective = len(violations) < len(raw_violations)
    pipeline._context.logger.warning(
        "pm_engine",
        f"verified 洗白门禁拦截 '{spec_name}': {'；'.join(violations)}",
    )
    pipeline._escalate_env_blocked(
        spec_name, violations, exemption_effective=exemption_effective
    )
    return False


def _escalate_env_blocked(
    pipeline, spec_name: str, violations: list, title: str = "验证环境阻塞",
    exemption_effective: bool = False, infra_retry: bool = False,
) -> str | None:
    """阻塞升级通道：阻塞 spec → 自动呼叫 Administrator → 达阈值冻结转人工。

    help-center 事故语义（0/15 verified 被全量 env 豁免后推成 pushed）：
    env 失败绝不放行。首轮阻塞并自动呼叫 Administrator（依赖安装/服务
    重启/端口清理在其权限内），处置完成走既有重验证；连续 2 轮仍阻塞 →
    frozen 结构化冻结 + 人工升级告警——admin 权限也无法处理时唯一出口是
    人工介入。title 区分升级类别（验证环境阻塞 / 场景计划争议）。

    evo-fix-env-exemption-gate-conflict-…（2.2）：``exemption_effective=True``
    为豁免有效命中轮（洗白门禁判定）——阻塞轮**不计入**
    ENV_BLOCK_FREEZE_THRESHOLD（不递增、不冻结：豁免认可不得仍滑向冻结；
    TTL 过期或场景定义变更失效后恢复计数，冻结兜底保留）。

    evo-verify-infra-retry-lane D6：``infra_retry=True``（全仓唯一传点=
    pipeline 可达性 fail-fast 短路）为 prepare/可达性短路轮的 infra-retry
    车道标记——决策点**单点收敛在本函数入口**：先经
    ``_record_infra_failure(retry_gate=True)`` 咨询 infra_classify 限次决议，
    - 未达预算 → 旁路早退返回 ``"redispatch"``：不递增 _env_block_rounds、
      不写 blocked/status/error、不呼叫 admin（下方 request_admin_invoke /
      escalation_notifier 写点全不经过）、不落 verify_env_blocked 信号；
      调用点据返回值经既有 verifier 派发入口廉价重派（D5）。
    - 达预算 → 落穿既有全价路径（计冻结轮、按 ENV_BLOCK_FREEZE_THRESHOLD
      升级）；入账已在 retry_gate 调用完成，不再二次记账。
    调用点 MUST NOT 绕开本函数另起入账路径（双决策点双重入账、口径漂移）。

    冻结转人工（fix-frozen-scenario-orphan-reservoir D5）：告警描述追加
    上轮 planner run 实际成本（tokens/费用/时长）作为「删除冻结集重新出题」
    的裁决参考。

    Returns: "redispatch"（infra-retry 未达预算，已旁路收口）| None（既有
    全价路径已处置完毕，含 infra_retry=True 落穿全价的轮）。
    """
    try:
        # 函数入口归一：violations 不可为 None（code-review 671b6c3c2e48），
        # 否则 262/265 行 violations[:3] 抛 TypeError 被下方函数级 except
        # 吞掉，阻塞/告警/呼叫全部静默跳过。
        violations = list(violations or [])
        spec = pipeline._context.state_machine.read_one(spec_name) or {}
        # ── evo-infra-failure-budget-exempt R2：env 阻塞属 infra ──
        # prepare/serve 失败（构建命令退出、端口不可达、自动启动失败）走
        # _escalate_env_blocked → blocked + admin（阈值 2 轮冻结转人工）；
        # infra 归类**只在其上补预算退款与 _verify_infra_rounds 记账**，
        # MUST 保持 env 通道 blocked 语义——「env 失败绝不放行」是既有刻意设计。
        # 归类挂钩点在 env 判定处（env 分支早退，归因入口不可达）。
        # evo-verify-infra-retry-lane D6：infra_retry=True 时本调用兼任车道
        # 决议（retry_gate，返回 "redispatch"/"escalate"）；False 时返回
        # None、行为与既有挂钩点逐位一致。
        infra_retry_decision: str | None = None
        try:
            infra_retry_decision = pipeline._record_infra_failure(
                spec_name,
                f"env blocked: {'; '.join(str(v) for v in (violations or [])[:3])}",
                retry_gate=infra_retry,
            )
        except Exception:
            # 记账侧车失败：infra-retry 车道保守按「达预算」走全价升级
            if infra_retry:
                infra_retry_decision = "escalate"
        if infra_retry and infra_retry_decision == "redispatch":
            # ── infra-retry 旁路（D6）：不计 env 冻结轮、不写 blocked/status、
            # 不呼叫 admin、不落 verify_env_blocked 信号——函数在此返回，
            # 下方全部全价写点（blocked 落盘 / request_admin_invoke /
            # escalation_notifier）均不经过。重派机械路径由调用点触发（D5：
            # 经既有 verifier 派发入口重新入队，不绕派发队列直调）。
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' {title}命中 infra-retry 廉价重试车道：不计 env "
                f"冻结轮、不呼叫 admin，直接重派验证（超预算后恢复全价升级）",
            )
            return "redispatch"
        if exemption_effective:
            # 豁免有效命中轮：轮次保持当前值（不递增），永不冻结
            try:
                rounds = int(spec.get(ENV_BLOCK_ROUNDS_FIELD) or 0)
            except (TypeError, ValueError):
                rounds = 0
            frozen = False
        else:
            try:
                rounds = int(spec.get(ENV_BLOCK_ROUNDS_FIELD) or 0) + 1
            except (TypeError, ValueError):
                # 字段被外部工具写坏为非数字串时，int() 抛 ValueError 会被函数级
                # except 吞成一条 WARNING，其后的阻塞落盘、admin 自动呼叫、人工
                # 告警全部静默跳过——比照 _inconclusive_attempts 同款防御，
                # 脏值按首轮阻塞处置，不让记账字段脏值瘫痪升级通道。
                rounds = 1
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' {ENV_BLOCK_ROUNDS_FIELD} 字段脏值（非数字），"
                    f"已按首轮阻塞兜底",
                )
            frozen = rounds >= ENV_BLOCK_FREEZE_THRESHOLD  # 阈值：连续 2 轮阻塞 → 冻结转人工
        # blocked 落盘前的非关键计算单独容错（code-review ad6e029c0827）：
        # 成本查询含 planner run 产物磁盘 IO，一旦抛异常会被函数级 except
        # 吞成一条 WARNING，其后的 update_spec blocked 落盘被跳过——整轮
        # 升级静默降级（ENV_BLOCK_ROUNDS_FIELD 不递增、spec 不写 blocked、
        # admin 不被呼叫）。失败按无成本参考降级，保证 blocked 落盘不被
        # 非关键异常跳过。
        try:
            planner_cost = pipeline._last_planner_run_cost(spec_name) if frozen else ""
        except Exception as e:
            planner_cost = ""
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' planner run 成本查询失败（降级为无成本参考）: {e}",
            )
        # 纯文本前缀（code-review 9249ef7f583b：emoji 装饰符在终端/日志通道
        # 渲染不一，且与同文件升级文案纯文本风格不一致）
        cost_note = f"\n\n> [成本参考] 重新出题成本：{planner_cost}" if planner_cost else ""
        exemption_note = (
            "env 豁免有效命中（豁免期内不累计冻结轮次，TTL 过期或场景变更后恢复计数）— "
            if exemption_effective
            else ""
        )
        # violations 拼接统一 str(v) 归一（code-review ad6e029c0827，对齐上方
        # _record_infra_failure 调用与函数入口归一注释的口径）：非 str 元素
        # 不再抛 TypeError 击穿函数级 except 跳过 blocked 落盘。
        error_msg = (
            f"{FREEZE_ERROR_PREFIX}{title}连续 {rounds} 轮，"
            f"admin 处置未奏效，转人工 — {'；'.join(str(v) for v in violations[:3])}"
            f"{cost_note}"
            if frozen
            else f"{exemption_note}{title}（第 {rounds} 轮）："
            f"{'；'.join(str(v) for v in violations[:3])}"
        )
        entry = {
            "status": "blocked",
            "error": error_msg,
            ENV_BLOCK_ROUNDS_FIELD: rounds,
        }
        if frozen:
            entry[FROZEN_FIELD] = True
        pipeline._context.state_machine.update_spec(spec_name, entry)
        if frozen:
            pipeline._context.logger.error(
                "pm_engine",
                f"'{spec_name}' {title}连续 {rounds} 轮，已冻结转人工",
            )
        else:
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' {title}第 {rounds} 轮，自动呼叫 Administrator 处置",
            )
        # 自动呼叫 Administrator：与 Dashboard 手动 invoke 同一信号通道
        # （.fenix/admin_invoke_request.json，daemon 主循环拾取派发）。
        # underlying_signal_type 直传（fix-escalation-autoinvoke-passthrough）：
        # 本路径升级记录 severity=warning（frozen 时 critical）在
        # _send_human_escalation_alert 落库即按降噪分级标 handled，消费侧
        # 基于未处置记录的反查对此不可见——复位透传必须由呼叫方自带。
        # fix-deferred-findings CYC-1：中性模块（不再反向 import dashboard.data）
        try:
            from core.signals import request_admin_invoke

            inv = request_admin_invoke(
                pipeline._context.project_root,
                spec_name,
                (
                    f"{title}自动升级（verified 洗白门禁/场景冻结复用）："
                    f"{error_msg[:300]}{'...' if len(error_msg) > 300 else ''}。"
                    "请诊断并处置——处置范围仅限环境修复（依赖安装、被测服务"
                    "/dashboard 重启、端口占用清理、验证产物重建、裁决场景集"
                    "变更）。环境问题不是产品缺陷：不要打回实现分支、不要修改"
                    "产品代码，不要手动 reset spec 状态。处置完成后，框架将自动"
                    "判定复位路径并触发重验证。"
                ),
                underlying_signal_type="verify_env_blocked",
            )
            if isinstance(inv, dict) and inv.get("conflict"):
                pipeline._context.logger.info(
                    "pm_engine",
                    f"'{spec_name}' 已有进行中的 Admin 处置，跳过重复呼叫",
                )
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' admin 自动呼叫失败（不阻塞升级）: {e}",
            )
        try:
            pipeline._context.escalation_notifier(
                spec_name=spec_name,
                signal_type="verify_env_blocked",
                severity="critical" if frozen else "warning",
                description=error_msg[:300] + ("..." if len(error_msg) > 300 else ""),
                evidence=(
                    f"spec={spec_name}; " f"report=spec/changes/{spec_name}/verification-report.md"
                ),
                recommended_action=(
                    # add-blocked-reverify-lane D2：处置收尾框架自动复位——
                    # admin 无需手动 reset spec 状态（手动 StateMachine 旁路
                    # 写法失去必要性）。未冻结：等待框架自动重验；已冻结：
                    # 人工检查环境后 unfreeze 清零重试（解冻即清零 rounds）。
                    "无需手动 reset spec 状态：处置完成并写入 result 后，框架"
                    "自动判定复位路径（实现分支已合并→直接重验 testing；"
                    "否则→ready 重实现）"
                    + (
                        f"；已冻结转人工：请检查环境（依赖/服务/端口）后"
                        f"unfreeze_spec 清零重试"
                        + (
                            f"；删除冻结集重新出题将重付出题成本"
                            + (f"（{planner_cost}）" if planner_cost else "")
                            if frozen
                            else ""
                        )
                        if frozen
                        else ""
                    )
                ),
            )
        except Exception as e:
            pipeline._context.logger.warning("pm_engine", f"env 阻塞人工告警失败: {e}")
    except Exception as e:
        # 升级通道自身失败不得抛穿裁决流程
        pipeline._context.logger.warning("pm_engine", f"env 升级通道异常 '{spec_name}': {e}")


def _update_warning_streaks(pipeline, spec_name: str) -> list:
    """更新 warning 连续悬置计数侧车（design D4 / D5）。

    采纳 report.json 后调用：扫描非 PASS 场景——
      - status == warning 且 classification ∈ {flaky, env} 的场景：连续计数 +1；
      - status 为 pass/failed（含被强制重写的 failed）或 classification 为
        product-bug/test-defect 的场景：计数清零；
      - 其余（warning 且 classification 缺失/未知值、blocked-env 等）：既不
        计数也不清零，保持原 streak（未知保守处理口径与
        _verdict_env_exemption_level2 一致，code-review 722c909338ce）。

    返回本轮回填后「连续计数 >= 2 且尚未列入优先复核清单」的候选列表
    [(scenario_id, 连续轮数), ...]（调用方据此发告警，文案轮次取实际连续
    轮数——补发场景已 > 2，固定写 2 会误导人工对悬置时长的判断）。
    触发不取精确相等、以
    triage_recheck.json 已含该 id 去重（code-review ef96ee9d0506）：streak
    侧车先落盘、告警由调用方在后执行，进程在两步之间中断后下轮计数已过 2
    仍可补发，且已告警场景不重复升级。侧车文件：
    ``.fenix/verify-progress/<spec>/warning_streaks.json``，
    结构 {scenario_id: 连续轮数}。
    """
    from core.verdict_check import load_report

    streaks_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "warning_streaks.json"
    )
    streaks = {}
    if streaks_path.exists():
        try:
            loaded = json.loads(streaks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 仅整个文件不可解析（JSONDecodeError/OSError）才整体置空
            loaded = None
        if isinstance(loaded, dict):
            # 逐条转换并跳过不可解析条目（code-review 9d6ee3c303a6）：单条
            # 脏值只丢弃自身，不清空其余场景的连续悬置计数——否则 except
            # 整体重置会把 >=2 轮的 triage 升级推迟甚至漏发。
            for k, v in loaded.items():
                if not isinstance(k, str):
                    continue
                try:
                    streaks[k] = int(v)
                except (TypeError, ValueError):
                    continue

    report = load_report(pipeline._context.project_root, spec_name)
    if report is None:
        return []
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return []

    triage_candidates = []
    # 本轮场景 id 集 / pass 集合（供 triage_recheck.json 剪枝，见函数尾部）
    current_ids = set()
    passed_ids = set()
    # 已列入优先复核清单的场景 id（code-review ef96ee9d0506）：升级触发条件
    # 放宽为 >= 2 后以此去重——streak 侧车先落盘、triage 告警由调用方在后
    # 执行，进程在两步之间中断时下轮计数涨到 3 后「== 2」永不命中，「连续
    # 2 轮 warning 需人工甄别」的升级语义被静默吞掉；放宽后下轮可补发，且
    # 已入清单者不重复告警。
    recheck_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "triage_recheck.json"
    )
    already_recheck: set = set()
    if recheck_path.exists():
        try:
            data = json.loads(recheck_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, list):
            already_recheck = {sid for sid in data if isinstance(sid, str)}
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = sc.get("scenario_id") or sc.get("id")
        if not sid:
            continue
        current_ids.add(sid)
        # 双词表口径对齐 verdict_check（agent 写报告时 status 合法形态含 passed）
        if sc.get("status") in ("pass", "passed"):
            passed_ids.add(sid)
        status = sc.get("status")
        classification = sc.get("classification")
        # 仅 flaky/env 的 warning 计入连续悬置；product-bug/test-defect 已强制
        # failed（D3），不悬置；pass/failed 及显式 product-bug/test-defect
        # 归类清零（D4）。classification 缺失/未知值的 warning 场景既不计数
        # 也不清零、保持原 streak（code-review 722c909338ce：与
        # _verdict_env_exemption_level2「triage 与 classification 皆缺按未知
        # 保守处理」同口径——报告字段缺失不得把连续悬置的升级信号反复清零
        # 而永不触发）。
        if status == "warning" and classification in ("flaky", "env"):
            streaks[sid] = streaks.get(sid, 0) + 1
            if streaks[sid] >= 2 and sid not in already_recheck:
                triage_candidates.append((sid, streaks[sid]))
        elif status in ("pass", "passed", "failed") or classification in (
            "product-bug",
            "test-defect",
        ):
            streaks[sid] = 0
        # 其余（warning + 未知归类、blocked-env 等）：保持原 streak，不动

    # 陈旧 id 剪枝：不在本轮场景集中的 id（planner 重排出题被替换）连同
    # 残留计数一并移除——否则残留 streak 会让新集复用旧 id 时立即凑满
    # 升级阈值（>= 2）误发 triage 升级，侧车文件也会无界增长
    # （与下方 triage_recheck.json 的剪枝同法）。
    for stale_id in set(streaks) - current_ids:
        del streaks[stale_id]

    # 写回侧车（原子写统一走共用助手 atomic_write_text，与模块头声明及本
    # 文件其余侧车落盘点一致，code-review d38282cb353a——不再手写 mkstemp
    # 第二套实现；助手内建失败清理残留临时文件）
    try:
        streaks_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            streaks_path, json.dumps(streaks, ensure_ascii=False, indent=2)
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"warning_streaks 写回失败 '{spec_name}': {e}",
        )

    # 优先复核清单剪枝：triage_recheck.json 只在 _warning_stale_triage_alert
    # 追加、无清除逻辑，已收敛（本轮 pass）或已不在当前场景集（随重排出题
    # 被替换）的 id 会永久滞留并被 planner prompt 每轮反复注入过期情报。
    # 此处按本轮 report 场景状态剪枝；report 不可得（上方提前 return）或
    # 文件缺失/损坏时不动作——损坏文件由 alert 写入路径的坏文件容错自愈。
    # （recheck_path 已在上方读取 already_recheck 时定义。）
    if recheck_path.exists():
        try:
            data = json.loads(recheck_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, list) and data:
            pruned = [
                sid
                for sid in data
                if not (
                    isinstance(sid, str)
                    and (sid not in current_ids or sid in passed_ids)
                )
            ]
            if len(pruned) != len(data):  # 无变化不写盘（避免每轮无谓写）
                try:
                    # 原子写（共用 fs_utils.atomic_write_text 助手）：剪枝
                    # 结果会被回读，裸写中途被杀留截断文件丢已积累复核清单。
                    atomic_write_text(
                        recheck_path,
                        json.dumps(pruned, ensure_ascii=False, indent=2),
                    )
                except OSError as e:
                    pipeline._context.logger.warning(
                        "pm_engine",
                        f"triage_recheck 剪枝写盘失败 '{spec_name}': {e}",
                    )
    return triage_candidates


def _warning_stale_triage_alert(pipeline, spec_name: str, scenario_ids: list) -> None:
    """warning 连续悬置场景的 triage 升级告警（design D4 / D5）。

    scenario_ids 为 _update_warning_streaks 返回的候选列表
    [(scenario_id, 连续轮数), ...]：告警文案轮次取实际 streak、缺值回退 2
    （code-review 77a49621cfd3——补发场景实际连续轮数已 > 2，固定写 2 与
    事实不符）。

    signal_type=warning_stale_triage，含 spec/场景/轮次/最近证据摘要；
    同时把场景写入下一轮 planner prompt 的「优先复核」注入（与 scenario-freeze
    的基准集注入同一接入点——复用 _scenario_freeze_section 机制：把 triage 场景
    落盘到 verify-progress/<spec>/triage_recheck.json，planner prompt 读取后注入）。
    """
    from core.verdict_check import load_report

    streak_by_sid = {sid: streak for sid, streak in scenario_ids}
    sids = list(streak_by_sid)
    # 证据摘要：从该场景的 evidence.failed_assertions / first_failed_step 摘取
    evidence_lines = []
    report = load_report(pipeline._context.project_root, spec_name)
    if isinstance(report, dict):
        for sc in report.get("scenarios", []) or []:
            if not isinstance(sc, dict):
                continue
            sid = str(sc.get("scenario_id") or sc.get("id") or "")
            if sid not in sids:
                continue
            ev = sc.get("evidence") if isinstance(sc.get("evidence"), dict) else {}
            ffs = ev.get("first_failed_step") or ""
            fa = ev.get("failed_assertions") or []
            fa_summary = (
                "; ".join(
                    f"{a.get('type','?')}({a.get('selector','')})"
                    for a in fa
                    if isinstance(a, dict)
                )
                if isinstance(fa, list)
                else ""
            )
            evidence_lines.append(
                f"场景 {sid}（classification={sc.get('classification')}, "
                f"连续 {streak_by_sid.get(sid, 2)} 轮 warning）：{ffs}"
                + (f"；失败断言：{fa_summary}" if fa_summary else "")
            )
    streak_detail = "、".join(
        f"{sid}（连续 {streak_by_sid.get(sid, 2)} 轮）" for sid in sids
    )
    evidence = "\n".join(evidence_lines) or f"连续 warning 场景：{streak_detail}"

    # 升级通道自身失败不得抛穿裁决流程（与同文件其他升级路径对齐，
    # code-review item 7e0509f14fdd）：notifier 抛异常不得连带丢掉
    # triage_recheck.json 优先复核清单落盘。
    try:
        pipeline._context.escalation_notifier(
            spec_name=spec_name,
            signal_type="warning_stale_triage",
            severity="critical",
            description=(
                f"'{spec_name}' 以下场景连续多轮均为 warning，"
                f"需人工 triage 甄别是否真缺陷被悬置：{streak_detail}"
            ),
            evidence=evidence,
            recommended_action=(
                f"人工复核 {', '.join(sids)} 的真实根因；下一轮验证已将其"
                f"列入优先复核清单（triage_recheck.json）"
            ),
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"triage 升级告警失败 '{spec_name}'（非阻塞）: {type(e).__name__}: {e}",
        )
    # 下一轮 planner prompt 优先复核注入（design D5）：落盘 triage_recheck.json
    recheck_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "triage_recheck.json"
    )
    try:
        recheck_path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if recheck_path.exists():
            try:
                data = json.loads(recheck_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    existing = data
            except (json.JSONDecodeError, OSError):
                existing = []
        merged = list(dict.fromkeys(existing + sids))
        # 原子写（共用 fs_utils.atomic_write_text 助手）：优先复核清单会被
        # planner prompt 回读，裸写中途被杀留截断文件会静默丢失已积累清单。
        atomic_write_text(
            recheck_path,
            json.dumps(merged, ensure_ascii=False, indent=2),
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"triage_recheck 写盘失败 '{spec_name}': {e}",
        )


def _scenario_reroute_stoploss_path(pipeline, spec_name: str) -> Path:
    """跨轮失败集留存路径（与 scenario_reroute_directive / triage_recheck 同级）。"""
    return (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "scenario_reroute_stoploss.json"
    )


def _read_scenario_reroute_stoploss(pipeline, spec_name: str) -> dict | None:
    """读改道前失败集留存（scenario-defect-reroute-stoploss 2.2）。

    缺失/损坏/结构不符 → None（视为无留存，保守放行不误停）。结构校验：
    顶层 dict、round 可转 int、failed_ids 为非空 list——任一项不满足即按
    「无留存」处理，MUST NOT 因本机制制造新的停止点。
    """
    path = _scenario_reroute_stoploss_path(pipeline, spec_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        round_ = int(data.get("round"))
        failed_ids = data.get("failed_ids")
        if not isinstance(failed_ids, list) or not failed_ids:
            return None
        failed_ids = [str(s) for s in failed_ids]
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None
    return {"round": round_, "failed_ids": failed_ids}


def _write_scenario_reroute_stoploss(
    pipeline, spec_name: str, round_: int, failed_ids: list
) -> None:
    """写当前失败集留存（覆盖；含写入轮次）；写失败仅告警，不阻断改道。"""
    path = _scenario_reroute_stoploss_path(pipeline, spec_name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写（共用 fs_utils.atomic_write_text 助手）：改道止损留存会被
        # 回读，裸写中途被杀留截断文件会让失败集留存静默丢失。
        atomic_write_text(
            path,
            json.dumps(
                {
                    "round": round_,
                    "failed_ids": [str(s) for s in failed_ids],
                    "written_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"scenario_reroute_stoploss 写盘失败 '{spec_name}'（不阻断改道）: {e}",
        )


def _scenario_defect_reroute_gate(
    pipeline, spec_name: str, _repair_depth: int, judge_result
) -> bool:
    """bug-found 申报打回 implementer 前的分类改道门。

    judge 申报 bug-found 后、打回 implementer 前插入（D1：框架侧机械判定，
    零 token）。report.json 非 PASS 场景全部显式 test-defect/flaky 且
    product-bug=0 → **拒绝打回 implementer**，定向重派 judge 一次（D2）：
    注入改道指令段，责令按原地修复协议申报 scenario-repaired；改道后
    scenario-repaired 沿用既有通道（冻结 diff 记账→重入阶段2/3）。

    预算（D2/D3）：改道重派计入 ``_SCENARIO_REPAIR_MAX_ROUNDS``，与
    scenario-repaired 重入共用 ``_repair_depth`` 计数（防两通道叠加无限重入）。
    预算耗尽仍 bug-found 且 product-bug=0 → 停止重派，升级人工
    （``_send_human_escalation_alert``，附失败清单/classification 分布/
    judge 申报记录），spec 保持 testing。改道路径不触碰 impl_run_budget。

    Returns:
        True 表示已按改道处置（调用方直接 return）；False 表示走现行
        bug-found 路由（打回 implementer）。
    """
    dist = pipeline._scenario_classification_distribution(spec_name)
    if not dist["all_scenario_defects"]:
        pipeline._context.logger.info(
            "pm_engine",
            f"改道门不放行 '{spec_name}'（失败 "
            f"{dist['total']} 个，product-bug={dist['product_bug']}，"
            f"未分类 {dist['unclassified']}）— 走现行 bug-found 路由",
        )
        return False

    # 判定分布记日志留痕（3.1）
    pipeline._context.logger.warning(
        "pm_engine",
        f"场景缺陷改道门触发 '{spec_name}'：失败 {dist['total']} 个全部显式"
        f"test-defect/flaky（分布 {dist['counts']}），product-bug=0 ——"
        f"拒绝打回 implementer，改道重派 judge（深度 {_repair_depth}）",
    )

    if _repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS:
        return pipeline._escalate_scenario_defect_reroute(spec_name, dist, _repair_depth)

    # ── 改道止损（scenario-defect-reroute-stoploss）──
    # 改道重入轮（_repair_depth >= 1 且留存轮次与 _repair_depth - 1 匹配）的门
    # 触发入口，对比重跑失败场景集与改道前失败集：改道前失败集 ⊆ 重跑失败集
    # （含相等，无任一场景被修复）→ 判「改道无效」，立即 _escalate_scenario_
    # defect_reroute 提前止损升级人工（信号 scenario_defect_reroute_stoploss），
    # 不再重派 judge、不消耗剩余改道预算；有场景被修复 → 覆盖留存后继续既有
    # 预算通道。链首触发（_repair_depth == 0）只写留存不判定（防上一链条陈旧
    # 留存误停）。读取点 MUST 是改道重入轮的门触发入口——重入重跑已产新
    # report.json；MUST NOT 在同一次门调用内「重派 judge 前读」，那时 report.json
    # 仍是改道前的旧产物，读到的必然是同批（假止损）。
    prev_record = _read_scenario_reroute_stoploss(pipeline, spec_name)
    if (
        _repair_depth >= 1
        and prev_record is not None
        and prev_record["round"] == _repair_depth - 1
        and prev_record["failed_ids"]
        and set(prev_record["failed_ids"]) <= set(dist["failed_ids"])
    ):
        pipeline._context.logger.warning(
            "pm_engine",
            f"场景缺陷改道重入轮 '{spec_name}'（深度 {_repair_depth}）重跑失败集"
            f"与改道前同批（{len(prev_record['failed_ids'])} 个失败场景无一被"
            f"修复）— 判改道无效，提前止损升级人工，不再消耗剩余改道预算",
        )
        return pipeline._escalate_scenario_defect_reroute(
            spec_name,
            dist,
            _repair_depth,
            stoploss=True,
            prev_failed_ids=prev_record["failed_ids"],
        )

    # 写当前失败集留存（覆盖改道前，含写入轮次；写失败仅告警，不阻断改道）
    _write_scenario_reroute_stoploss(pipeline, spec_name, _repair_depth, dist["failed_ids"])

    # 写改道指令文件（prompt_builder _scenario_reroute_directive_section 读取）
    directive_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "scenario_reroute_directive.json"
    )
    try:
        directive_path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写（共用 fs_utils.atomic_write_text 助手）：改道指令会被
        # prompt_builder 回读，裸写中途被杀留截断文件会让指令静默丢失。
        atomic_write_text(
            directive_path,
            json.dumps(dist, ensure_ascii=False, indent=2),
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"改道指令文件写失败 '{spec_name}'（仍重派 judge）: {e}",
        )

    # 改道重派 judge：经 pipeline._pm 门面回引（design D3 规则 3）——
    # context 的 agent_runner 车道仅包装 _execute_agent（fastlane 轻量修复
    # 派发），未承载 run_planner 委托成员，故此处为车道外的显式豁免，
    # MUST NOT 从 _context 取；agent_runner 接线方式变化时须与
    # _schedule_scenario_repair_reverify 的门面回引豁免双处同步。
    try:
        # 轮内重裁决记账（与 pipeline.py 裁决不可读重派、verdict_evidence
        # 违规重派两条绕 gate 路径同口径）：本路径直接 run_planner 不经
        # _judge_dispatch_gate，若不记账可绕过轮内 2 次与全局 5 次重裁决
        # 阈值。空 violations 必然落入 "real" 分支（记轮内 +1 与生命周期
        # _judge_real_dispatches，并刷新判定上下文键）。
        # 记账含 STATE 读写磁盘 IO，MUST 与 run_planner 同处本 try 作用域
        # （code-review f9c6dda068a8）：此前记账在 try 外，一旦抛异常（磁盘
        # 满/权限等）下方 finally 的指令文件清理不会执行——残留
        # scenario_reroute_directive.json 会被 prompt_builder 只判存在即注入
        # 「MUST 申报 scenario-repaired」定向指令，把同 spec 后续任意正常
        # judge 派发劫持为改道轮；异常还会沿调用方上抛中断本轮裁决。移入后
        # 由既有 except 兜底（保持 testing + finally 清理指令文件）。
        pipeline._judge_charge_verdict_retry(spec_name, [])
        reroute_judge = pipeline._pm.agent_runner.run_planner(spec_name, "judge")
    except Exception as e:
        pipeline._context.logger.error(
            "pm_engine",
            f"改道重派 judge 异常 '{spec_name}'（保持 testing）: " f"{type(e).__name__}: {e}",
        )
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "error": f"场景缺陷改道重派 judge 异常（保持 testing）：{e}",
            },
        )
        return True
    finally:
        try:
            directive_path.unlink()
        except OSError:
            pass

    if not reroute_judge.success:
        # 改道重派失败：取消/派发故障。保持 testing，不升级人工
        # （与裁决重试派发失败同型，温和处置留 error）。
        # ── 冻结终止让位（与 pipeline.py judge 失败让位分支同口径，
        # frozen 判定在 cancelled 之前：spec 级 > run 级）──
        # judge run 因 spec 冻结被终止 = 人工已接管：零写入提前返回
        # （不写 error、不升级人工），INFO 留痕供日志对账。判定用
        # `is True`（同 pipeline.py：防 MagicMock 替身自动生成 truthy
        # 属性误判；生产结果 frozen_terminated 为显式 bool）。
        if getattr(reroute_judge, "frozen_terminated", False) is True:
            pipeline._context.logger.info(
                "pm_engine",
                f"改道重派 judge 因 spec 冻结被终止 '{spec_name}' — "
                f"人工已接管，零写入让位（保持原状）",
            )
            return True
        if getattr(reroute_judge, "cancelled", False) is True:
            # 人工取消 hold-state（与 pipeline.py _dispatch_judge_or_reuse 的
            # cancelled 分支同口径，code-review 9affa1c31b7c）：写 error +
            # _cancelled_hold 持久标记（fix-cancel-holdstate-recovery D1），
            # 保持 testing。恢复链路按取消保持跳过（recover_interrupted D3 /
            # _ready_hold_blocks），人工「随根因修复一并重派」的决策不被重启
            # 恢复静默覆盖；此前本车道零写入，取消事实在 dashboard/
            # 排障侧不可见（cancelled_hold 渲染判据读不到）。
            cancelled_err = (
                f"run 被人工取消：{reroute_judge.error}"
                if reroute_judge.error
                else "run 被人工取消"
            )
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "error": cancelled_err,
                    "_cancelled_hold": True,
                },
            )
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道重派 judge 被取消 '{spec_name}' — hold-state"
                f"（保持 testing）: {cancelled_err}",
            )
        else:
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道重派 judge 派发失败 '{spec_name}' — 保持 testing，"
                f"留 error 待下轮重验: {reroute_judge.error}",
            )
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "error": f"改道重派 judge 派发失败（保持 testing）：" f"{reroute_judge.error}",
                },
            )
        return True

    # 重派结果判定（evo-verifier-result-single-source R1：统一走
    # _read_verdict 入口，主树共享回退须过 role/spec 戳校验）
    reroute_read = pipeline._read_verdict(spec_name)
    if reroute_read.ok and reroute_read.status == "scenario-repaired":
        # 改道后 scenario-repaired：沿用既有通道（冻结 diff 记账 → 重入）
        try:
            freeze_result = pipeline._apply_scenario_freeze(spec_name)
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道后场景冻结记账跳过 '{spec_name}'（异常不阻断）: {e}",
            )
            freeze_result = None
        if isinstance(freeze_result, dict) and freeze_result.get("aborted"):
            # ── 空集显式兜底（evo-planner-scenario-schema-alignment 3.7）──
            # 改道重入路径与 judge 重入同语义：修复后场景集为空 → 拒绝
            # 本次重入、保持原状并留痕，MUST NOT 以空集/未过滤文件进入阶段2。
            reject_detail = "、".join(freeze_result.get("rejected") or [])[:400]
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "error": (
                        f"改道重派 judge 修复后场景集为空（写前预校验整批拒绝，"
                        f"共 {freeze_result.get('total', 0)} 条）— 拒绝本次重入，"
                        f"保持 testing 待人工/下轮处置: {reject_detail}"
                    ),
                },
            )
            pipeline._context.logger.error(
                "pm_engine",
                f"改道重派后无合法场景 '{spec_name}' — 拒绝重入，0 场景不进入"
                f"阶段2: {reject_detail}",
            )
            return True
        pipeline._context.logger.info(
            "pm_engine",
            f"[改道] judge 原地修复采纳 '{spec_name}' — 重入执行"
            f"（第 {_repair_depth + 1}/{_SCENARIO_REPAIR_MAX_ROUNDS} 次修复）",
        )
        pipeline._run_three_stage_verification(spec_name, _repair_depth=_repair_depth + 1)
        return True

    if reroute_read.ok and reroute_read.status == "bug-found":
        # 改道后仍 bug-found：再读分布——
        # 若含 product-bug（judge 改判真产品缺陷）→ 正常打回 implementer 路由；
        # 若仍全场景缺陷且预算耗尽 → 升级人工。
        new_dist = pipeline._scenario_classification_distribution(spec_name)
        if new_dist["product_bug"] > 0 or not new_dist["all_scenario_defects"]:
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道后 judge 改判含产品缺陷 '{spec_name}'（product-bug="
                f"{new_dist['product_bug']}）— 走现行 bug-found 路由",
            )
            return False
        return pipeline._escalate_scenario_defect_reroute(spec_name, new_dist, _repair_depth + 1)

    # 结果不可读/其他状态：fail-closed 保守，保持 testing 等待下轮重验
    pipeline._context.logger.error(
        "pm_engine",
        f"改道重派结果不可读 '{spec_name}'（reason="
        f"{reroute_read.reason if reroute_read.ok is False else '?'}）— "
        f"保持 testing 等待下轮重验",
    )
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "error": "改道重派 judge 结果不可读（保持 testing，等待下轮重验）",
        },
    )
    return True


def _escalate_scenario_defect_reroute(
    pipeline,
    spec_name: str,
    dist: dict,
    _repair_depth: int,
    stoploss: bool = False,
    prev_failed_ids: list | None = None,
) -> bool:
    """改道收口升级人工：附失败清单/classification 分布/申报记录。

    stoploss=True（scenario-defect-reroute-stoploss 止损路径）：改道重入轮
    重跑失败集与改道前同批（改道前失败集 ⊆ 重跑失败集，无任一场景被修复）
    → 判改道无效，提前升级人工，不再消耗剩余改道预算；human-escalation-alert
    信号 scenario_defect_reroute_stoploss（severity major），附同批失败证据
    （failed_ids / 轮次 / classification 分布）。stoploss=False：既有预算耗尽
    路径（信号 scenario_defect_reroute_exhausted），行为不变。
    """
    if stoploss:
        prev_failed = [str(s) for s in (prev_failed_ids or [])]
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "error": (
                    f"场景缺陷改道重入轮重跑失败集与改道前同批（改道前 "
                    f"{len(prev_failed)} 个失败场景无一被修复）— 判改道无效，"
                    f"提前止损升级人工裁决，spec 保持 testing，不再消耗剩余"
                    f"改道预算"
                ),
            },
        )
        pipeline._context.logger.error(
            "pm_engine",
            f"场景缺陷改道同批失败止损 '{spec_name}'（深度 {_repair_depth}）— "
            f"改道前失败集 ⊆ 重跑失败集（无任一场景被修复），提前升级人工，"
            f"不再重派 judge",
        )
        # 升级通道自身失败不得抛穿裁决流程（与同文件其他升级路径对齐，
        # code-review item 7e0509f14fdd）：改道门是恒返回 True/False 的
        # 收口路径，notifier 抛异常会打断验证裁决。
        try:
            pipeline._context.escalation_notifier(
                spec_name=spec_name,
                signal_type="scenario_defect_reroute_stoploss",
                severity="major",
                description=(
                    f"'{spec_name}' 场景缺陷改道重入轮（深度 {_repair_depth}）重跑"
                    f"失败集与改道前同批：改道前 {len(prev_failed)} 个失败场景"
                    f"无一被修复（全部 test-defect/flaky、product-bug=0）— 判改道"
                    f"无效，提前止损升级人工裁决，不再消耗剩余改道预算。"
                ),
                evidence=(
                    f"spec={spec_name}; 留存轮次={_repair_depth - 1}; "
                    f"改道前 failed_ids={','.join(prev_failed)[:500]}; "
                    f"重跑 failed_ids={','.join(dist.get('failed_ids') or [])[:500]}; "
                    f"classification_distribution="
                    f"{json.dumps(dist.get('counts'), ensure_ascii=False)}"
                ),
                recommended_action=(
                    "检查失败场景文件（.fenix/verify-progress/"
                    f"{spec_name}/test_scenarios.json）与验证报告，人工裁决："
                    "① admin 场景修复通道修场景（schema 门内）；② 确认为真产品缺陷"
                    "则重置分类/直接打回 implementer；③ 场景集已过时则删除冻结集"
                    "批准重新出题。"
                ),
            )
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道止损升级告警失败 '{spec_name}'（非阻塞）: "
                f"{type(e).__name__}: {e}",
            )
        return True

    # 改道轮数按调用方传入的实际值描述（_repair_depth = 已执行改道次数）：
    # 链首改道后 bug-found 且 product-bug=0 时仅重派 1 次即走到这里，固定写
    # 上限轮数与事实不符会误导人工裁决；仅当实际轮数达到上限时才用
    # 「预算耗尽」措辞。
    budget_exhausted = _repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS
    escalate_head = (
        "场景缺陷改道预算耗尽" if budget_exhausted else "场景缺陷改道未达预算上限即升级"
    )
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "error": (
                f"{escalate_head}（实际改道 {_repair_depth} 轮），"
                f"仍为纯场景缺陷（product-bug=0）— 已升级人工裁决，spec 保持"
                f"testing，不再消耗实现轮预算"
            ),
        },
    )
    pipeline._context.logger.error(
        "pm_engine",
        f"{escalate_head} '{spec_name}'（实际改道 {_repair_depth} 轮）— "
        f"升级人工，不等打回 implementer 修场景",
    )
    try:
        pipeline._context.escalation_notifier(
            spec_name=spec_name,
            signal_type="scenario_defect_reroute_exhausted",
            severity="major",
            description=(
                f"'{spec_name}' 验证失败清单全部为场景缺陷（test-defect/flaky）"
                f"且 product-bug=0，改道重派 judge {_repair_depth} "
                f"轮后仍未原地修复完成——已停止重派，升级人工裁决。"
            ),
            evidence=(
                f"spec={spec_name}; classification_distribution="
                f"{json.dumps(dist.get('counts'), ensure_ascii=False)}; "
                f"failed_ids={','.join(dist.get('failed_ids') or [])[:500]}; "
                f"impl_run_budget 未消耗（改道路径不触碰实现预算）"
            ),
            recommended_action=(
                "检查失败场景文件（.fenix/verify-progress/"
                f"{spec_name}/test_scenarios.json）与验证报告，人工裁决："
                "① admin 场景修复通道修场景（schema 门内）；② 确认为真产品缺陷"
                "则重置分类/直接打回 implementer；③ 场景集已过时则删除冻结集批准"
                "重新出题。"
            ),
        )
    except Exception as e:
        # 升级通道自身失败不得抛穿裁决流程（与同文件其他升级路径对齐，
        # code-review item 7e0509f14fdd）
        pipeline._context.logger.warning(
            "pm_engine",
            f"改道预算耗尽升级告警失败 '{spec_name}'（非阻塞）: "
            f"{type(e).__name__}: {e}",
        )
    return True


def _handle_judge_env_declared(pipeline, spec_name: str) -> bool:
    """judge 自述环境问题时按 inconclusive 处理（不派生 fix）。

    与 _handle_env_blocked_inconclusive 同语义：回 implemented 重派新
    attempt，不 transition bug-found、不派生 fix spec；超限后暂停自动
    重验并暴露错误等待人工（无界重验会烧 token）。
    """
    spec = pipeline._context.state_machine.read_one(spec_name) or {}
    try:
        attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    max_attempts = _read_int_config(
        pipeline, "verify_engine.inconclusive_max_attempts", 2
    )
    escalate_attempts = _read_int_config(
        pipeline, "verify_engine.inconclusive_escalate_attempts", 4
    )
    note = (
        f"judge 判定 bug-found 但所有 bug 根因均自述为环境/基础设施问题"
        f"（伪失败，不派生 fix），第 {attempts}/{max_attempts} 次重验"
    )

    # ── B7 升级通道（design D6）──
    # 达升级阈值或达重验上限（attempts >= max_attempts，停止收口与升级
    # 合并，code-review 922e79f7a511）即升级停车——经共用收口
    # _escalate_inconclusive_parking（code-review 5a9cdf9b2dac：不再内联
    # 只写 SIGNAL 的第二套收口，与 _handle_env_blocked_inconclusive /
    # _handle_verdict_env_exemption_inconclusive 同族同通道：SIGNAL +
    # escalation_notifier 带 choices 人工告警 + _in_inconclusive_reverify
    # 旗标（judge 预算隔离）+ _last_inconclusive_signature 回写）。本形态
    # 失败集不来自 blocked-env 场景（judge 判 bug-found 但根因自述 env），
    # 无签名比较基准、按空串回写（下一轮按签名未知保守走计数上限）；
    # blocked_env 计 0，signal_description 沿用与本故障形态一致的措辞
    # （不引人工走向 blocked-env 探针方向，_write_inconclusive_loop_signal
    # description 覆盖语义同款）。
    if attempts >= escalate_attempts or attempts >= max_attempts:
        threshold_note = _escalate_threshold_note(
            attempts, max_attempts, escalate_attempts
        )
        _escalate_inconclusive_parking(
            pipeline,
            spec_name,
            attempts,
            0,
            {},
            signature="",
            threshold_note=threshold_note,
            env_note="judge 自述全部 bug 根因为环境/基础设施问题（伪失败）",
            signal_description=(
                f"'{spec_name}' 连续 {attempts} 轮验证均因环境/基础设施问题"
                f"未完成（judge 自述），{threshold_note}，"
                f"请 Administrator 核查验证环境"
            ),
        )
        return True

    if attempts < max_attempts:
        pipeline._context.logger.warning("pm_engine", f"'{spec_name}' {note}")
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "status": "implemented",
                "tester_run": None,
                "error": note,
                "_inconclusive_attempts": attempts,
                # 本形态无签名比较基准，显式按空串回写（与本函数升级分支注释
                # 声明一致，code-review de2568acfdf3）：两种 inconclusive 形态
                # 共用 _inconclusive_attempts 计数，不回写会残留 blocked-env 轮
                # 旧签名，下轮 blocked-env 同签名复现时被误判「环境未变化」
                # 提前升级停车（跨形态非相邻两轮的误配）。
                "_last_inconclusive_signature": "",
                # 预算隔离（design D3，与 _handle_env_blocked_inconclusive
                # 重验分支同语义）：本重验轮若触发 judge 派发，计入独立计数器
                # 而非 _judge_rerun_count 生命周期账。
                "_in_inconclusive_reverify": True,
            },
        )
        pipeline._context.enqueue(spec_name, "verifier")
        return True

    # 显式兜底：升级分支已覆盖 attempts >= max_attempts，到达此处条件恒真
    # ——恒按 inconclusive 处理、恒返回 True。显式写出避免隐式 None 出口
    # 被调用方按真值消费时静默传播。
    return True


def _judge_bugs_declare_env(pipeline, spec_name: str) -> bool:
    """judge 判 bug-found 但其自述根因全部为环境/基础设施问题时返回 True。

    2026-08-28 实证：planner 重新生成的场景用相对 URL "/dashboard"（无效
    URL）+ 幻觉 testid，12 个场景全部在导航步失败；judge 在结果文件中
    自述「这是一个环境问题，而非产品 Bug」，却把 status 标为 bug-found，
    pm_engine 据此派生伪 fix 级联。此处以 judge 自己的根因描述为准：
    所有 bug 均自述环境/基础设施问题时，按「验证没能发生」处理。

    采信前置（code-review fdd837807758）：结果文件直读 MUST 先过 spec 戳
    与 status 白名单两道护栏，防上一轮 implementer（status=success/error，
    不产 bugs 语义）或异 spec 残留的 bugs 字段被误采信、把真实 bug-found
    打回吞成 inconclusive。role 门不在前置内：primary 是 judge/verifier
    直写落点、常缺 role 戳（judge_gate 快道 D3 教训，
    report_gate._verifier_result_is_stale 对 primary 同款豁免 role 门）——
    「本产物确出自验证裁决车道」由 status=bug-found 白名单表达
    （implementer/planner 不产出该 status）。
    """
    # 路径解析与戳校验复用统一读取入口的实现（evo-verifier-result-single-
    # source R1；函数内 import 与 pipeline.py 同款先例，防模块环导入）。
    from core.pm_engine.verification.report_gate import (
        _verifier_stamp_gate,
        _verify_progress_result_paths,
    )

    primary, _shared = _verify_progress_result_paths(pipeline, spec_name)
    if not primary.exists():
        return False
    try:
        data = json.loads(primary.read_text(encoding="utf-8"))
    # UnicodeDecodeError（非 UTF-8 字节）与 JSON 语法错同属内容损坏：
    # fail-closed 按「无法采信」返回 False（与 report_gate 读取点口径对齐）。
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    # spec 戳不符 = 其它 spec 残留，不采信（规则唯一实现在
    # _verifier_stamp_gate；primary 只做 spec 戳、不做 role 门，见 docstring）
    ok, _reason = _verifier_stamp_gate(data, spec_name, require_verifier_role=False)
    if not ok:
        return False
    # 仅验证裁决车道申报的 bug-found 产物才采信 bugs 字段（implementer
    # success/error 残留、旧轮 verified/plan-ready 残留一律不采信）
    if data.get("status") != "bug-found":
        return False
    bugs = data.get("bugs")
    if not isinstance(bugs, list) or not bugs:
        return False

    def _declares_env(bug) -> bool:
        if not isinstance(bug, dict):
            return False
        text = f"{bug.get('root_cause', '')} {bug.get('description', '')}"
        return any(marker in text for marker in pipeline._context.env_infra_markers)

    return all(_declares_env(bug) for bug in bugs)


def _speculative_bug_found_gate(pipeline, spec_name: str) -> bool:
    """归因分级门禁（add-verdict-credibility-gate / design D2 / Task 2.2）。

    在 bug-found 打回决定前调用：读取 report.json（judge 已增强），框架侧
    机械计算 attribution_level，白屏方向约束强制改写分类，然后判断打回
    依据是否全部为推测级（speculative）——是则抑制 bug-found：
      - 门禁预算内（verify_engine.credibility_gate_max_retries，缺省 1）：
        回 implemented 转重验一次，不向 implementer 带推测信号打回；
      - 预算耗尽：blocked + 告警（attribution_evidence_insufficient），
        交人工复核。

    Returns:
        True 表示已按门禁处置（调用方应 return，不推进 bug-found）；
        False 表示归因有证据支撑（或门禁异常降级不阻断），按既有流程推进。
    """
    try:
        from core.verdict_check import (
            validate_attribution_levels,
            should_suppress_bug_found,
            enforce_blank_screenshot_direction,
            load_report as _load_gate_report,
        )

        gate_report = _load_gate_report(pipeline._context.project_root, spec_name)
        if gate_report is None:
            return False  # 无 report.json，门禁无对象可判，不阻断
        validate_attribution_levels(gate_report)
        for _sc in gate_report.get("scenarios") or []:
            if isinstance(_sc, dict):
                _new_cls = enforce_blank_screenshot_direction(_sc)
                if _new_cls:
                    _sc["classification"] = _new_cls
                    _sc["blank_direction_forced"] = True
        if not should_suppress_bug_found(gate_report):
            # 清空门禁计数：本轮未触发（有证据支撑的归因，不记入 speculative 统计）
            spec_data = pipeline._context.state_machine.read_one(spec_name) or {}
            if spec_data.get("_credibility_gate_attempts"):
                try:
                    pipeline._context.state_machine.update_spec(
                        spec_name,
                        {
                            "_credibility_gate_attempts": 0,
                        },
                    )
                except Exception:
                    pass
            return False

        max_retries = _read_int_config(
            pipeline, "verify_engine.credibility_gate_max_retries", 1
        )
        spec = pipeline._context.state_machine.read_one(spec_name) or {}
        try:
            gate_attempts = int(spec.get("_credibility_gate_attempts", 0) or 0)
        except (TypeError, ValueError):
            # 字段被外部工具写坏为非数字串时，int() 抛 ValueError 会被函数级
            # except 吞成「门禁校验异常跳过」return False，调用方继续
            # bug-found 打回——归因分级门禁整体失效。比照 _inconclusive_attempts
            # / ENV_BLOCK_ROUNDS_FIELD 同款防御：脏值回退 0，不让记账字段
            # 脏值瘫痪升级通道。
            gate_attempts = 0
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' _credibility_gate_attempts 字段脏值（非数字），"
                f"已按 0 兜底继续门禁判定",
            )
        if gate_attempts < max_retries:
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' 打回归因全部为 speculative（推测级），"
                f"抑制 bug-found——转重验一次"
                f"（第 {gate_attempts + 1}/{max_retries} 次）",
            )
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "status": "implemented",
                    "tester_run": None,
                    "error": (
                        f"归因证据不足待人工复核：全部驱动场景归因"
                        f"为推测级（speculative），已抑制 bug-found "
                        f"打回并重验一次（第 {gate_attempts + 1}/"
                        f"{max_retries} 次）"
                    ),
                    "_credibility_gate_attempts": gate_attempts + 1,
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：计数清零处同步清
                    # 降档并行度（_inconclusive_attempts 同生命周期）。
                    "_verify_parallel_override": None,
                },
            )
            pipeline._context.enqueue(spec_name, "verifier")
            return True

        # 重试预算已耗尽：阻断为 blocked + 告警（交人工复核）
        pipeline._context.logger.error(
            "pm_engine",
            f"'{spec_name}' 归因证据不足待人工复核：连续 "
            f"{gate_attempts} 次推测级归因，门禁预算耗尽，"
            f"阻断为 blocked",
        )
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "status": "blocked",
                "error": (
                    f"归因证据不足待人工复核：全部驱动场景归因"
                    f"连续 {gate_attempts} 次为推测级（speculative），"
                    f"门禁重试预算耗尽，已 blocked 等待人工裁决"
                ),
            },
        )
        # 升级通道自身失败不得抛穿裁决流程（与同文件 _escalate_scenario_defect_reroute
        # 的包裹模式对齐，code-review item fb3660678b0c）：blocked 处置已在上方
        # update_spec 落盘，notifier 抛异常若落入函数级 except 会被误记为
        # 「门禁校验异常跳过」并 return False，调用方据此继续 bug-found 打回，
        # 覆盖刚写入的 blocked 终态。
        try:
            pipeline._context.escalation_notifier(
                spec_name=spec_name,
                signal_type="attribution_evidence_insufficient",
                severity="major",
                description=(
                    f"'{spec_name}' 验证归因证据不足待人工复核："
                    f"连续 {gate_attempts} 次驱动场景归因均为推测级"
                    f"（speculative），门禁已 blocked 等待人工裁决"
                ),
                evidence=(
                    f"spec={spec_name}; max_retries={max_retries}; " f"连续推测轮数={gate_attempts}"
                ),
                recommended_action=(
                    "人工核验验证场景与失败断言：若为真·产品缺陷请"
                    "在 triage_violations.json 标注后重派 verify；"
                    "若为场景缺陷请退回 plan 修复场景"
                ),
            )
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"归因证据不足升级告警失败 '{spec_name}'（非阻塞，"
                f"blocked 处置已落盘、仅告警通道失败）: "
                f"{type(e).__name__}: {e}",
            )
        return True
    except Exception as e:
        # 门禁自身异常不阻断既有裁决（治理代码是附加治理，框架级门禁
        # 崩溃按「不阻断」退化——judge 正常裁决继续，避免附加治理代码
        # 成为新单点故障）
        pipeline._context.logger.warning(
            "pm_engine",
            f"门禁校验异常跳过（不阻断裁决）'{spec_name}': " f"{type(e).__name__}: {e}",
        )
        return False


def _write_inconclusive_loop_signal(
    pipeline,
    spec_name: str,
    attempts: int,
    blocked_env: int,
    report: dict,
    description: str | None = None,
    threshold_note: str | None = None,
    signature: str = "",
) -> bool:
    """向 admin store 写 inconclusive_loop SIGNAL（design D6 / Task 5.2）。

    连续 blocked-env 达升级阈值时调用：kind=SIGNAL，type=inconclusive_loop，
    附 spec 名、连续轮数、末轮 blocked_env 数、本轮失败签名摘要（1.1/2.2：
    供人工核对「环境是否变化」与放行裁决）、最近实例探针摘要。admin_monitor
    _detect_family_explosion 摄取后按既有 SIGNAL 通道唤起 Administrator。

    description 可覆盖缺省的 blocked-env 模板文案（code-review item
    782362a0983e）：judge 自述环境等非 blocked-env 形态的升级入口传入与
    故障形态一致的措辞，避免告警把人工排查引向 blocked-env 探针方向。

    threshold_note 为缺省模板中的阈值表述（code-review 974c5b39ad17）：
    调用方传 ``_escalate_threshold_note`` 产物，使「已达重验上限/已达升级
    阈值」与实际命中的升级条件一致；缺省回退通用表述。

    写失败静默降级（信号只是升级通道，spec 的 error 字段已承载人工可见信息），
    返回是否写入成功。
    """
    # 最近实例探针摘要：末轮 blocked-env 场景的 env_probe_detail 里取第一条
    probe_detail = ""
    for sc in report.get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        if sc.get("status") != "blocked-env":
            continue
        probe_detail = str(sc.get("env_probe_detail") or "").strip()
        if probe_detail:
            break
    # 截断上界与同文件 evidence 先例对齐（code-review item c5cb1544b937）：
    # env 探针输出（诊断命令输出/异常栈）可达 KB 级，无界拼入会使 admin
    # store 单条记录无界膨胀。
    if len(probe_detail) > 500:
        probe_detail = probe_detail[:500] + "..."
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(pipeline._context.project_root, pipeline._context.logger)
    try:
        store.append(
            {
                "kind": SIGNAL,
                "signal_type": "inconclusive_loop",
                "spec": spec_name,
                "severity": "major",
                "description": (
                    description
                    or (
                        f"'{spec_name}' 连续 {attempts} 轮验证全部为 blocked-env"
                        f"（环境性失联），{threshold_note or '已达升级阈值'}，"
                        f"请 Administrator 核查验证环境"
                    )
                ),
                "evidence": (
                    f"spec={spec_name}; 连续轮数={attempts}; "
                    f"末轮blocked_env数={blocked_env}; "
                    f"签名摘要={signature or '无'}; "
                    f"探针摘要={probe_detail or '无'}"
                ),
                "recommended_action": (
                    "验证环境核查清单：① 被测实例是否就绪（serve/start 命令与端口）；"
                    "② 资源与并行度（max_parallel 是否挤爆实例）；"
                    "③ mock+SSE 链路（mock_api 是否误拦推流、SSE 是否断流）；"
                    "④ 探针摘要（见 evidence）。恢复路径：人工处置后解冻 spec "
                    "（unfreeze）并清 `_inconclusive_attempts`，后续 blocked-env "
                    "轮次从 1 重新计数"
                ),
            }
        )
        return True
    except Exception as e:
        pipeline._context.logger.error(
            "pm_engine",
            f"inconclusive_loop 信号写入失败 '{spec_name}': {e}",
        )
        return False


def _verdict_env_exemption_level2(
    pipeline, spec_name: str, report: dict | None = None
) -> dict:
    """级二判定：judge 裁决后「失败全部为环境性」判据（design D4）。

    判定输入为裁决产物字段（report.json，judge 增强后的断言级 triage），
    不重算原始 summary，MUST NOT 用「豁免清单条数 == failed + blocked_env」
    等式（豁免清单是断言级行，条数与场景数不对齐——add-session-composer
    事故形态 7 条断言 ≠ 2 failed + 1 blocked_env）。

    判据：全部非 pass/passed 场景的失败断言中——
      - 无 product-bug / test-defect 条目（含之不命中，走既有 bug-found，
        env 部分照常留豁免记录）；
      - 且无 flaky / 未知归类条目（flaky 维持既有豁免放行不转重验；triage
        与 classification 皆缺的失败场景按未知保守处理，不命中）；
      - 且至少一条 env 归类——全绿轮无豁免对象，不命中（零改动直通）。
    blocked_env 形态场景天然视为环境性（与级一判据同语义）。场景缺
    assertion_triage 时回退场景级 classification。

    evo-fix-env-exemption-gate-conflict-…（2.3）：env 归因结论须附「送帧/
    解码」两段证据引用（``admin_actions.env_attribution_evidence_gate``）——
    声称帧管线类失败（提送帧/解码/相机等词汇）却只给一句现象描述的归因，
    降级为 inconclusive（落 non_env，级二不命中）：既不触发豁免握手也不触发
    升级语义，回归既有裁决车道。非媒体词汇的普通 env 归因不受此门约束。

    Returns:
        {"hit": bool, "env_entries": int, "blocked_env_scenarios": [sid],
         "non_env": [{"scenario", "classification", "source"}]}
    """
    from core.verdict_check import load_report, triage_entries

    # 归因证据门（admin_actions 单源）：惰性 import 防模块加载环。
    # [层次环锚点，code-review 375b09e1dc26] env_attribution_evidence_gate
    # 是纯判定函数 (classification, evidence_text) -> str（无状态无 IO）；
    # 本模块（验证引擎核心）与 core.dashboard.data.admin_actions（dashboard
    # 处置层）构成已知双向环——admin_actions 侧亦多处惰性 import 本包，
    # 函数级延迟 import 只是对加载序的规避而非解除环本身。验证引擎核心
    # 反向依赖处置层属层次倒置：函数若下沉到中性模块（如
    # core/verdict_check），两侧引用须同步迁移。
    from core.dashboard.data.admin_actions import env_attribution_evidence_gate

    if report is None:
        report = load_report(pipeline._context.project_root, spec_name)
    env_entries = 0
    blocked_env_scenarios: list = []
    non_env: list = []
    for sc in (report or {}).get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "?")
        if status == "blocked-env":
            # blocked-env 从未执行、无归因结论（infra 探针形态），不经证据门
            blocked_env_scenarios.append(sid)
            env_entries += 1
            continue
        triage = triage_entries(sc)
        if triage:
            for t in triage:
                cls = t.get("classification")
                # 证据门：媒体管线类 env 归因缺「送帧/解码」两段证据引用
                # → 降级 inconclusive（不触发 env 豁免/升级语义）
                gated = env_attribution_evidence_gate(
                    cls, str(t.get("evidence") or "")
                )
                if cls == "env" and gated != "env":
                    non_env.append(
                        {
                            "scenario": sid,
                            "classification": str(gated),
                            "source": "assertion",
                        }
                    )
                elif cls == "env":
                    env_entries += 1
                else:
                    non_env.append(
                        {
                            "scenario": sid,
                            "classification": str(cls),
                            "source": "assertion",
                        }
                    )
            continue
        cls = sc.get("classification")
        ev = sc.get("evidence")
        if isinstance(ev, dict):
            evidence_text = "；".join(
                str(v) for v in ev.values() if isinstance(v, (str, int, float))
            )
        else:
            evidence_text = str(ev or "")
        gated = env_attribution_evidence_gate(cls, evidence_text)
        if cls == "env" and gated != "env":
            non_env.append(
                {
                    "scenario": sid,
                    "classification": str(gated),
                    "source": "scenario",
                }
            )
        elif cls == "env":
            env_entries += 1
        else:
            non_env.append(
                {
                    "scenario": sid,
                    "classification": str(cls),
                    "source": "scenario",
                }
            )
    return {
        "hit": bool(blocked_env_scenarios or env_entries) and not non_env,
        "env_entries": env_entries,
        "blocked_env_scenarios": blocked_env_scenarios,
        "non_env": non_env,
    }


def _handle_verdict_env_exemption_inconclusive(
    pipeline, spec_name: str, report: dict, verdict: dict
) -> bool:
    """级二命中后的升级停车（fix-env-exemption-exit-reachability 1.1：首次命中即升级）。

    级二命中的前提是 judge 已对全部失败作出 env 终局裁决——重验只有在环境
    变化时才有新信息，而框架没有环境变化探测器，自动重验是纯预算焚烧
    （2026-10-03 事故：每轮重验因 report timestamp 翻新必烧 1 次 judge
    生命周期派发，人工出口前 judge_rerun_cap 先冻结）。故**首次命中即升级**，
    不再走「先自动重验 N 次」：

      1. 写 inconclusive_loop SIGNAL（signal_type 与既有 B7 一致，保住
         ``latest_resolved_disposition(spec, "inconclusive_loop")`` 放行查询
         锚点），evidence 附本轮失败签名摘要与 attempts 当前值；
      2. 经 ``escalation_notifier`` 发带 choices 的人工告警（severity=major，
         choices 由注册表按 signal_type 自动附加）；
      3. spec 停 implemented、tester_run 清空、error 写等待人工裁决文案
         （不用 FREEZE_ERROR_PREFIX 冻结前缀）、``_dispatch_backoff_until``
         置退避防 orphaned_state 误报；
      4. 置 ``_in_inconclusive_reverify`` 旗标（judge 预算隔离）并回写
         ``_last_inconclusive_signature``。

    **不 enqueue verifier 自动重验**——升级后停止自动重验，人工经 choices
    处置（grant_env_exemption / revise_scenario_reverify /
    manual_fixed_reverify / abandon）是唯一出路。恒返回 True（调用方不得再
    落 verified）。

    evo-fix-env-exemption-gate-conflict-…（2.2）：修订 re-entry 先于升级——
    入口先查 ``_scenario_revision_reverify_pending`` 旗标（场景修订执行器
    置位），在位则消费旗标并放行一次重验（``_scenario_revision_reentry``），
    给修订后的场景集一次收敛机会，本轮不升级停车。
    """
    # 修订 re-entry 先于升级（2.2）：旗标在位先重验，本函数不停车
    if pipeline._scenario_revision_reentry(spec_name):
        return True
    summary = (report or {}).get("summary") or {}
    blocked_env = _summary_count(pipeline, spec_name, summary, "blocked_env")
    spec = pipeline._context.state_machine.read_one(spec_name) or {}
    try:
        attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    env_note = (
        f"env 断言 {verdict.get('env_entries', 0)} 条、"
        f"blocked-env 场景 {len(verdict.get('blocked_env_scenarios') or [])} 个"
    )
    signature = _inconclusive_fail_signature(pipeline, spec_name, report)
    _escalate_inconclusive_parking(
        pipeline,
        spec_name,
        attempts,
        blocked_env,
        report or {},
        signature,
        threshold_note="级二豁免握手首次命中即升级（judge 已裁决全 env）",
        env_note=env_note,
        signal_description=(
            f"'{spec_name}' 连续 {attempts} 轮验证失败均被裁决归类 env"
            f"（{env_note}），豁免握手拦截、无 admin 放行处置记录 — "
            f"judge 已裁决全 env，等待人工豁免或修环境（自动重验已停止）"
        ),
    )
    return True


def _env_exempt_disposition_is_stale(
    pipeline, store, spec_name: str, disposition: dict
) -> bool:
    """放行处置记录时效校验（code-review 9fb05143a336）。

    ``latest_resolved_disposition`` 只按（spec, signal_type, result）取最近
    一条 resolved 记录，无时效约束——早先 episode 的放行可被后续与新环境
    问题无关的轮次无限复用。此处要求处置记录 created 晚于本 spec 最近一条
    inconclusive_loop SIGNAL 的 created（admin 放行总是晚于其要解除的那轮
    升级信号，故「不晚于最近信号」即陈旧放行）：

      - 本 spec 无 inconclusive_loop SIGNAL 记录（未达升级阈值 / 写入静默
        降级 / 存量记录被 MAX_RECORDS 清理）时取不到本轮信号时刻，无法证明
        陈旧——按可放行近似处理（近似锚点，在此说明）：比「永久卡死合法
        放行路径」风险更低；达升级阈值的轮次恒有信号，无限复用主通道已被
        本校验关闭；
      - 处置记录 created 不可解析时按陈旧处置（fail-closed 到重验，与握手
        守卫「绝不 fail-open 到 verified」同 philosophy）。

    Returns: True=陈旧放行（不得复用）；False=新鲜或无法证明陈旧。
    """
    from core.admin_store import SIGNAL

    def _parse_ts(value):
        try:
            # ISO 解析内核收拢至 timelib.parse_ts（add-timelib-consolidation-
            # layer 4.2）：naive 时间戳（人工修补/外部工具写入）**按本地时区
            # 解读**（timelib 唯一 naive 策略，定调 2026-09-30）——**推翻**
            # 旧注释「朴素→UTC 与 AdminStore 一致」：AdminStore 写侧
            # ``now(timezone.utc).isoformat()`` 恒为 aware，实际信号/处置记录
            # 不含 naive（4.2 核查留痕见 tests/test_timelib_pm_parse.py）。
            # 不可解析返回 None（fail-closed 到按陈旧处置重验）。
            return parse_ts(str(value or ""))
        except (ValueError, TypeError):
            return None

    try:
        latest_signal_dt = None
        for rec in store.read_all():
            if rec.get("kind") != SIGNAL:
                continue
            if rec.get("signal_type") != "inconclusive_loop":
                continue
            if rec.get("spec") != spec_name:
                continue
            # 统一按 _parse_ts 解析后取最近（code-review 4ed9b3c4a946）：
            # 字典序比较在混存朴素时间戳与 +00:00 后缀 ISO 串时由长度决定
            # 序关系，可能选错「最近一条」；_parse_ts 的 naive→本地归一
            # （timelib 唯一策略，4.2）使两类时间戳可比。不可解析的记录跳过
            # （不参与锚点选取）。
            rec_dt = _parse_ts(rec.get("created"))
            if rec_dt is not None and (
                latest_signal_dt is None or rec_dt > latest_signal_dt
            ):
                latest_signal_dt = rec_dt
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"豁免放行时效校验扫 inconclusive_loop SIGNAL 失败 '{spec_name}'"
            f"（按陈旧放行处置）: {e}",
        )
        return True

    if latest_signal_dt is None:
        return False
    disposition_dt = _parse_ts(disposition.get("created"))
    if disposition_dt is None:
        return True
    return disposition_dt <= latest_signal_dt


def _handle_env_exemption_handshake(
    pipeline, spec_name: str, report: dict | None = None
) -> bool:
    """裁决 env 豁免握手（verdict-env-exemption-handshake，judge 采纳尾段）。

    级二命中（裁决后失败全部为环境性，见 ``_verdict_env_exemption_level2``）
    时 MUST NOT 直接落 verified——豁免不得自我批准：

      0. **spec 级 STATE 豁免（本 SPEC 1.3 主放行通道，唯一生效源）**：
         本轮全部 env 失败场景命中有效豁免（场景 id+归一化失败签名+场景定义
         hash+时效，``_env_exemptions_cover`` 经 ``find_env_exemption`` 同一
         纯函数——与白化门禁同源，消除「握手认可、门禁拒绝」双门矛盾）→
         报告保留豁免回链后返回 False，放行走既有 verified 链。STATE 读失败
         =无豁免（fail-closed，绝不 fail-open 到 verified）。
      1. 无有效 STATE 豁免：查 AdminStore 该 SPEC 放行处置记录（kind=
         DISPOSITION，``latest_resolved_disposition`` 存量通道——切换后仅作
         审计镜像，存量放行不做数据回填，新裁决一律经 grant 重建 STATE 豁免）
         → 查无转 ``_handle_verdict_env_exemption_inconclusive`` 升级停车
         （fix-env-exemption-exit-reachability 1.1：**首次命中即升级**——
         SIGNAL + 带 choices 的人工告警、spec 停 implemented 等待人工豁免
         或修环境裁决、**不再自动重验**，人工经 choices 处置后重置重验），
         返回 True（调用方 MUST NOT 再落 verified）；
      2. 查得放行记录且其 created 晚于本 spec 最近一条 inconclusive_loop
         SIGNAL（时效校验，``_env_exempt_disposition_is_stale``，防早先
         episode 的陈旧放行被后续轮次复用）→ 报告保留处置回链后返回 False，
         放行走既有 verified 链（豁免清单作为依据合法生效）；陈旧放行按
         ① 同路径处置。

    级二不命中（无豁免 / 全绿 / 含 product-bug / test-defect / flaky 断言）
    返回 False 零改动直通——洗白门禁（``_env_whitewash_gate``，覆盖场景级
    classification=env 形态）与既有 verified 流转不受影响；全绿机械快道
    （0 失败 0 警告）无豁免对象，同样零改动直通。

    守卫读 store 异常时按「无放行记录」处置（fail-closed，绝不 fail-open
    到 verified）——既有 fail-open 守卫语义零变更。
    """
    from core.admin_store import AdminStore
    from core.state_machine import parse_env_exemptions
    from core.verdict_check import load_report, save_report

    verdict = _verdict_env_exemption_level2(pipeline, spec_name, report)
    if not verdict["hit"]:
        return False

    # ── 通道 0：spec 级 STATE 豁免（双门同源主放行）──────────────────
    sm_entry = pipeline._context.state_machine.read_one(spec_name) or {}
    state_exemptions = parse_env_exemptions(sm_entry)
    if state_exemptions:
        hashes = _load_frozen_scenario_hashes(
            pipeline._context.project_root, spec_name
        )
        rep0 = report if isinstance(report, dict) else load_report(
            pipeline._context.project_root, spec_name
        )
        # 覆盖判定与回链同源（code-review 9fc208d8395a）：命中清单由
        # _env_exemption_matches 一次算得，不再内联重跑逐场景豁免匹配。
        # 多豁免命中时回链顶层字段取首个命中（兼容既有回链形态），全部
        # 命中项列 matched_exemptions 供人工按回链核对完整放行依据。
        matched_list = _env_exemption_matches(
            pipeline, spec_name, rep0, sm_entry, hashes
        )
        if matched_list:
            matched = matched_list[0]
            backlink = {
                "anchor": "env_exemptions",
                "signal_type": "inconclusive_loop",
                "result": "resolved",
                "granted_at": matched.get("granted_at"),
                "scenario_id": matched.get("scenario_id"),
                "id": matched.get("disposition_id"),
                "action_taken": "grant_env_exemption",
                "matched_exemptions": [
                    {
                        "scenario_id": ex.get("scenario_id"),
                        "granted_at": ex.get("granted_at"),
                        "id": ex.get("disposition_id"),
                    }
                    for ex in matched_list
                ],
                "note": (
                    "env 豁免经 spec 级 STATE 豁免字段生效"
                    "（evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit："
                    "握手与白化门禁同源消费）；顶层字段为首项命中，"
                    "全部命中项见 matched_exemptions"
                ),
            }
            rep = rep0 if isinstance(rep0, dict) else {}
            backlink_note = "报告不可得，豁免回链未写入"
            if rep:
                rep["admin_disposition_backlink"] = backlink
                backlink_note = "报告已保留豁免回链"
                try:
                    save_report(pipeline._context.project_root, spec_name, rep)
                except OSError as e:
                    backlink_note = "报告豁免回链写回失败（未保留）"
                    pipeline._context.logger.warning(
                        "pm_engine",
                        f"豁免回链写回 report.json 失败 '{spec_name}'"
                        f"（不阻断放行）: {e}",
                    )
            pipeline._context.logger.warning(
                "pm_engine",
                f"env 豁免握手放行 '{spec_name}'：本轮全部 env 失败场景命中有效 "
                f"STATE 豁免（命中场景 "
                f"{'、'.join(str(ex.get('scenario_id')) for ex in matched_list)}，"
                f"granted_at={backlink.get('granted_at')}），{backlink_note}",
            )
            return False
        # STATE 豁免在场但未覆盖本轮（场景定义修订致 hash 失效 / TTL 过期 /
        # 失败签名漂移）：STATE 是唯一生效源，**不回退 disposition 存量通道**
        # ——grant 会同时落 disposition 审计镜像，若该镜像仍可独立放行，
        # 「场景变更即失效」被完全架空（回到本 SPEC 要消除的双门矛盾）。
        # 转升级停车（修订 re-entry 旗标在停车入口先于升级消费）。
        pipeline._context.logger.warning(
            "pm_engine",
            f"env 豁免握手拦截 '{spec_name}'：STATE 豁免在场但对本轮全部 env "
            f"失败场景未全部命中（场景定义修订/TTL 过期/签名漂移任一失效），"
            f"STATE 为唯一生效源不回退 disposition 存量通道 — 转升级停车",
        )
        rep_fail = rep0 if isinstance(rep0, dict) else (report or {})
        return _handle_verdict_env_exemption_inconclusive(
            pipeline, spec_name, rep_fail, verdict
        )

    store = AdminStore(pipeline._context.project_root, pipeline._context.logger)
    try:
        disposition = store.latest_resolved_disposition(spec_name, "inconclusive_loop")
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"豁免握手守卫读 AdminStore 失败 '{spec_name}'（按无放行记录处置）: {e}",
        )
        disposition = None

    disposition_stale = disposition is not None and _env_exempt_disposition_is_stale(
        pipeline, store, spec_name, disposition
    )
    if disposition is None or disposition_stale:
        if disposition_stale:
            pipeline._context.logger.warning(
                "pm_engine",
                f"env 豁免握手拦截 '{spec_name}'：查得的 admin 放行处置记录"
                f"（{disposition.get('created') or '时间未知'}）不晚于本轮 "
                f"inconclusive_loop 信号，属早先 episode 的陈旧放行，不复用 — "
                f"转 inconclusive 重验，不落 verified",
            )
        else:
            pipeline._context.logger.warning(
                "pm_engine",
                f"env 豁免握手拦截 '{spec_name}'：本轮验证失败全部被裁决归类 env"
                f"（env 断言 {verdict['env_entries']} 条、blocked-env 场景 "
                f"{len(verdict['blocked_env_scenarios'])} 个），无 admin 放行处置"
                f"记录 — 转 inconclusive 重验，不落 verified",
            )
        if report is None:
            report = load_report(pipeline._context.project_root, spec_name) or {}
        return _handle_verdict_env_exemption_inconclusive(
            pipeline, spec_name, report, verdict
        )

    # 放行记录存在：豁免合法生效 — 报告保留处置回链后放行走既有 verified 链
    backlink = {
        "anchor": "admin_disposition",
        "signal_type": disposition.get("signal_type"),
        "result": disposition.get("result"),
        "created": disposition.get("created"),
        "id": disposition.get("id"),
        "action_taken": (disposition.get("action_taken") or "")[:300],
        "note": "env 豁免经 admin 放行处置确认后生效（verdict-env-exemption-handshake）",
    }
    rep = report if isinstance(report, dict) else load_report(
        pipeline._context.project_root, spec_name
    )
    # 回链写入结果并入放行日志文案（code-review f8ec5838ce8c）：报告不可得
    # 或写回失败时不得声称「报告已保留处置回链」，避免人工在报告中找回链落空。
    if isinstance(rep, dict):
        rep["admin_disposition_backlink"] = backlink
        backlink_note = "报告已保留处置回链"
        try:
            save_report(pipeline._context.project_root, spec_name, rep)
        except OSError as e:
            backlink_note = "报告处置回链写回失败（未保留）"
            pipeline._context.logger.warning(
                "pm_engine",
                f"豁免处置回链写回 report.json 失败 '{spec_name}'（不阻断放行）: {e}",
            )
    else:
        backlink_note = "报告不可得，处置回链未写入"
    pipeline._context.logger.warning(
        "pm_engine",
        f"env 豁免握手放行 '{spec_name}'：查得 admin 放行处置记录"
        f"（{disposition.get('created') or '时间未知'}），豁免清单作为 verified "
        f"依据生效，{backlink_note}",
    )
    return False


def _schedule_scenario_repair_reverify(pipeline, spec_name: str) -> None:
    """首次预算耗尽后排程一次确定性重验（fix-recovery-path-blockers D3）。

    首次耗尽不再只写 error 干等——落一个显式、可观测的重验日程：
      1. 写 ``_dispatch_backoff_until``（deadline = now + 重验延时常量）：
         `spec_is_undriven` 条件 ③ 在退避窗内为真 → 15 分钟 orphaned_state
         阈值先到期也不会成条（把「有意等待」结构化表达给探测器）；
      2. 排程 ``threading.Timer``（daemon 线程）：到期回调入队 verifier +
         `_process_queue` 触发派发（等价 ``_recover_testing`` 的
         ``spec_implemented`` 语义——testing 态由 verifier 派发驱动）。

    幂等：同 spec 已排程则不再重复（``_reverify_timers`` per-spec 判重集合，
    仿 ``_schedule_instant_fail_recovery`` 的 ``_instant_fail_timers`` 模式）。
    重验计时器在 daemon 重启后丢失（进程内对象）——属于预期，兜底由
    ``_dispatch_backoff_until`` + ``event_bus._recover_testing`` 周期扫描承担；
    MUST NOT 依赖「定时器与周期扫描只触发其一」——两者可能同时到期，幂等由
    `_enqueue` 按 (spec, agent_type) 去重与 `_process_queue` 的
    `_dispatch_backoffed` 门（queue.py:228/312）保证只起一次 verifier run。

    Args:
        pipeline: VerificationPipeline 实例（经 `_context` 触达 state_machine/
                  enqueue/logger/pm_engine）。
        spec_name: 预算耗尽的 spec 名。
    """
    def _on_reverify_due(name: str = spec_name) -> None:
        """定时器到期回调：入队 verifier + 触发派发（幂等，多定时器并发安全）。"""
        # 清掉判重标记：允许未来再次进入排程路径（若再次耗尽走升级通道）。
        # 与排程路径同锁互斥——防回调 discard 与并发排程的判重/add 交错
        # 复活 check-then-act 竞态（锁内仅 set.discard，无 IO、无重入）。
        with _REVERIFY_TIMERS_LOCK:
            timers.discard(name)
        pipeline._context.logger.info(
            "pm_engine",
            f"重验日程到期，入队 verifier '{name}'（fix-recovery-path-blockers D3）",
        )
        try:
            pipeline._context.enqueue(name, "verifier")
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"重验日程到期入队异常 '{name}': {type(e).__name__}: {e}",
            )
            return
        # 触发派发：经 pipeline._pm 门面回引（design D3 规则 3）——_context
        # 无 pm_engine 成员，MUST NOT 从 _context 取。
        pm_engine = getattr(pipeline, "_pm", None)
        if pm_engine is not None:
            try:
                pm_engine._process_queue()
            except Exception as e:
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"重验日程到期 _process_queue 异常 '{name}': "
                    f"{type(e).__name__}: {e}",
                )

    # 幂等判重 + 占位（check-then-act 原子）：锁内一次性完成「判重 → 建定时器
    # → add 占位 → start」，先占位成功者才排程，杜绝并发同 spec 双 Timer
    # （仿 backoff.py `_schedule_instant_fail_recovery` 的锁内排程模式）。
    # 临界区仅内存操作 + Timer 创建/启动（轻量无 IO），无重入路径。
    with _REVERIFY_TIMERS_LOCK:
        timers = getattr(pipeline, "_reverify_timers", None)
        if timers is None:
            timers = set()
            pipeline._reverify_timers = timers
        if spec_name in timers:
            pipeline._context.logger.debug(
                "pm_engine",
                f"重验日程已存在，幂等跳过 '{spec_name}'（fix-recovery-path-blockers D3）",
            )
            return
        timer = threading.Timer(_SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS, _on_reverify_due)
        timer.daemon = True
        timers.add(spec_name)
        try:
            timer.start()
        except Exception as e:
            # code-review item 274b668bbaf0：start 失败（解释器关闭期 RuntimeError、
            # 线程资源耗尽等环境性原因）时回滚占位标记——否则标记只由定时器回调
            # 清除，定时器未启动即永不触发，同 spec 后续排程恒被上方幂等早退短路，
            # 本周期重验日程无法重建。仿 backoff.py _schedule_recovery_timer_locked
            # 的「摘除标记 + WARNING」回滚口径（item 488e916852e4）；异常不上抛，
            # 恢复依赖周期扫描兜底。
            timers.discard(spec_name)
            pipeline._context.logger.warning(
                "pm_engine",
                f"重验定时器启动失败，已回滚判重标记 '{spec_name}'"
                f"（待周期扫描兜底重验）: {type(e).__name__}: {e}",
            )
            return
    # 写 _dispatch_backoff_until：退避窗内 spec_is_undriven 条件③ 为真，
    # 探测器静默；到期后由定时器（主）+ 周期扫描（兜底）触发重验。
    # （锁外执行——状态机写盘属耗时 IO，MUST NOT 入临界区；写失败不阻断
    # 排程，此时定时器已占位启动、兜底语义不受影响。）
    deadline_epoch = int(time.time()) + _SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS
    try:
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "_dispatch_backoff_until": deadline_epoch,
            },
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"重验日程写 _dispatch_backoff_until 失败 '{spec_name}'"
            f"（不阻断排程）: {type(e).__name__}: {e}",
        )
    pipeline._context.logger.info(
        "pm_engine",
        f"'{spec_name}' 场景原地修复预算耗尽，已排程重验"
        f"（{_SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS}s 后重验）— "
        f"fix-recovery-path-blockers D3",
    )


def _escalate_scenario_repair_exhausted(pipeline, spec_name: str) -> None:
    """场景原地修复预算再次耗尽 → 升级人工裁决（fix-recovery-path-blockers D3）。

    首次耗尽已排程重验仍不收敛（``_scenario_repair_exhausted_rounds >= 1``）
    → 走既有升级通道呼叫人工：spec 保持 testing、不排程。signal_type 复用
    既有场景缺陷族 ``scenario_defect_reroute_exhausted``（语义同族：场景缺陷
    修复预算耗尽升级人工）。escalation 记录按 (spec, signal_type) 由
    ``unhandled_for`` 节流——同 spec 已存在未处理的同族升级则不重复告警。

    Args:
        pipeline: VerificationPipeline 实例（经 `_context.escalation_notifier`
                  升级人工）。
        spec_name: 再次耗尽的 spec 名。
    """
    pipeline._context.logger.error(
        "pm_engine",
        f"场景原地修复预算再次耗尽 '{spec_name}' — 升级人工，"
        f"不再排程重验（fix-recovery-path-blockers D3）",
    )
    try:
        pipeline._context.escalation_notifier(
            spec_name=spec_name,
            signal_type="scenario_defect_reroute_exhausted",
            severity="major",
            description=(
                f"'{spec_name}' 场景原地修复预算耗尽且重验后仍不收敛"
                f"（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮原地修复 + 1 次重验日程）"
                f"— 已停止重验，升级人工裁决，spec 保持 testing"
            ),
            evidence=(
                f"spec={spec_name}; scenario_repair_max_rounds="
                f"{_SCENARIO_REPAIR_MAX_ROUNDS}; "
                f"reverify_delay_seconds={_SCENARIO_REPAIR_REVERIFY_DELAY_SECONDS}"
            ),
            recommended_action=(
                "检查失败场景文件（.fenix/verify-progress/"
                f"{spec_name}/test_scenarios.json）与验证报告，人工裁决："
                "① admin 场景修复通道修场景（schema 门内）；② 确认为真产品缺陷"
                "则重置分类/直接打回 implementer；③ 场景集已过时则删除冻结集"
                "批准重新出题；④ 处置完成后若需重新自动重验可 unfreeze_spec"
                "（清零耗尽计数，重新获得首次排程重验体验）。"
            ),
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"场景修复预算耗尽升级告警失败 '{spec_name}'（非阻塞）: "
            f"{type(e).__name__}: {e}",
        )
