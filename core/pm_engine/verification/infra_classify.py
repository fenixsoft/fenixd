"""core.pm_engine.verification.infra_classify — infra 失败归因/历史/回拨组（refactor-verification-module D2）。

从 VerificationPipeline 摘出 infra 判定（infra 指标/降级标记）、失败历史
（per-spec fail_history.json 读写清理）、归一化签名、场景分类分布、
失败场景 ID 提取、同因失败哨、infra 回拨入口。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import hashlib as _hash
import json
import re
from pathlib import Path

from core.admin_store import AdminStore, DISPOSITION, SIGNAL
from core.fs_utils import atomic_write_text

# 冻结标记字段单源（code-review item 101a0ed85064）：与 branch_guard /
# state_machine 同引 FROZEN_FIELD 常量，字面量在常量演进时会静默失配。
from core.state_machine import FROZEN_FIELD

# code-review item f882b509b227：provider 熔断判定文案与生产源（provider_circuit）
# 共用同一导出常量（同 pipeline.py item 17e5cb41806e 惯例，防措辞漂移静默失配）。
from core.agent_runner.provider_circuit import PROVIDER_CIRCUIT_ERROR_MARKER

# code-review item e23d6ef56ed8：场景分类白名单与裁决证据分类共享同一导出常量
# （core.verdict_check），防分类枚举增删时本处字面量静默漏改。
from core.verdict_check import VERDICT_CLASSES

from core.pm_engine.verification.branch_guard import resolve_env_blocked_reset_path

# 回拨审计留痕信号类型（幂等键前缀，admin_store DISPOSITION 按 reclassify_key 去重）
RECLASSIFY_SIGNAL_TYPE = "infra_reclassify"

# per-spec fail_history.json 文件名
_FAIL_HISTORY_FILENAME = "fail_history.json"

# 全场景同因失败熔断阈值：连续 N 轮同因 → blocked（判定与信号文案单源引用，
# code-review item 84ff70bd0fa9；同族冻结阈值 ENV_BLOCK_FREEZE_THRESHOLD 在
# core.state_machine）
_UNIFORM_SAME_CAUSE_BLOCK_THRESHOLD = 3

# 全场景同因失败哨的单轮最小失败场景数：0 passed 轮须失败场景数达该值才进入
# 同因签名比对（1-2 个失败样本过少，签名一致易属巧合，不足以立「全场景同因」
# 疑点，按小失败轮回落连续计数）。与 _UNIFORM_SAME_CAUSE_BLOCK_THRESHOLD
# （连续同因熔断轮数）数值相同但语义不同——前者约束单轮失败场景规模，后者
# 约束跨轮连续次数，调参时各自独立、无联动。
_UNIFORM_MIN_FAIL_TOTAL = 3


def _verifier_error_is_infra(pipeline, error_text: str) -> bool:
    """verifier 失败是否属基础设施类（不得流转 bug-found）。

    覆盖：provider 熔断抑制、failover 链耗尽（chain exhausted）、
    classify_switch_error 可识别的切换类错误（unrecognized_model/5xx/网络/
    429 限流——add-code-review-concurrency-and-429-resilience 将限流纳入
    切换类后，验证失败的 infra 归因随之覆盖 429，「验证没能发生」语义，
    属预期外溢，断言用例固化于 tests/test_provider_circuit.py）。
    此类失败说明「验证没能发生」，不是「验证发现了缺陷」。
    """
    if not error_text:
        return False
    # "chain exhausted" 生产源为 core/agent_runner/runner.py 熔断文案（该侧暂无导出常量，保留字面量）。
    if PROVIDER_CIRCUIT_ERROR_MARKER in error_text or "chain exhausted" in error_text:
        return True
    try:
        # 门面直引豁免（code-review item 9fad470a0abe）：PipelineContext 的
        # agent_runner 车道目前仅承载 _execute_agent（fastlane 轻量修复派发），
        # 未承载 classify_switch_error 委托成员；此处沿用
        # _schedule_scenario_repair_reverify / _scenario_defect_reroute_gate 的
        # 「经 pipeline._pm 门面回引（design D3 规则 3）」同款显式豁免——车道
        # 后续补充该委托成员时应同步改经 context 触达。严格 is True：分类器
        # 返回非布尔（如测试桩）时按非基础设施处理。
        return pipeline._pm.agent_runner.classify_switch_error(error_text) is True
    except Exception:
        return False


# ── evo-infra-failure-budget-exempt R1：统一失败归因接口 ───────────

# infra 降级触发 error 文本标记（enrich_failure_class 判定）。R1 有意收窄为
# worktree / merge conflict / tree dirty 三项——仅命中本清单才判 infra；
# worktree 为子串宽匹配（覆盖 git worktree add / worktree lock 等具体形态）。
_INFRA_DEGRADE_MARKERS = (
    "worktree",
    "merge conflict",
    "tree dirty",
)


def enrich_failure_class(
    pipeline, spec_name: str, error_text: str = "", result=None, result_path: Path | None = None
) -> str:
    """统一失败归因接口：返回 ``infra`` | ``unknown``（unknown 由调用方按
    product 保守处置；evo-infra-failure-budget-exempt R1）。

    复用 ``_verifier_error_is_infra`` 的 bool 判定（MUST 保持签名不变），
    在其上扩展三态分类。**兼容性**：legacy 路径 verification.py:3283 与
    engine.py:2613 委托均按 bool 消费 ``_verifier_error_is_infra``，三态
    分类另立本函数——禁止原地改签名（否则 ``if _verifier_error_is_infra(pipeline, ...)``
    在字符串返回值下永远 truthy，legacy infra 门全线失效）。

    覆盖（验证实现以各条目为独立生效分支）：

    - provider 熔断 / 链耗尽 / 网关切换：``_verifier_error_is_infra(error_text)`` → infra。
    - 陈旧 / 异 spec 归属结果文件（复用 ``_verifier_result_is_stale``）：传入
      ``result`` + ``result_path`` → infra；result_path 未给或判定异常时跳过。
    - worktree 冲突 / 降级触发本身：error_text 含 ``_INFRA_DEGRADE_MARKERS``
      任一子串 → infra。
    - prepare/serve env blocked：不经过本归因入口（env 分支早退），其 infra
      记账由 ``_escalate_env_blocked`` 挂钩点直接处理。

    **明确排除**：结果文件缺失 / 非法 JSON 的 unreadable（fix-verdict-read-failclosed
    D4/D5）维持 fail-closed（blocked + critical），不在本分类器问题域内。

    **unknown 处置（保守原则）**：无清单命中、无法归类 → 返回 ``unknown``
    按 product 保守处置——不豁免预算、照常累计 ``_verify_fail_rounds``；
    宁可少豁免，不可误豁免（误豁免会绕过预算闸门并掩盖真实失败计数）。
    """
    # ── Provider 熔断 / 链耗尽 / 网关切换（已有 bool 通道，签名不变）──
    if _verifier_error_is_infra(pipeline, error_text):
        return "infra"

    # ── 陈旧 / 异 spec 归属结果文件（复用 _verifier_result_is_stale）──
    if result is not None and result_path is not None:
        try:
            if pipeline._verifier_result_is_stale(result, result_path, spec_name):
                return "infra"
        except Exception:
            # 判定异常保守放行（unknown → product 保守处置），不误豁免
            pass

    # ── worktree 冲突 / 降级触发本身（收窄：仅命中 infra 清单才判 infra）──
    err_lower = str(error_text).lower() if error_text else ""
    if any(marker in err_lower for marker in _INFRA_DEGRADE_MARKERS):
        return "infra"

    # unknown → product 保守处置（不豁免、照常累计 fail_rounds）
    return "unknown"


# ── evo-add-verifier-infra-death-triage R1：进程级死亡判定 ─────────

# 进程级死亡的秒挂判定阈值（秒）。存活口径取终局结果 duration_seconds——
# run 级总存活、全部 attempt 存活的严格上界：上界低于阈值即全部 attempt
# 均为秒挂，无需 attempt 级明细回填（runner 侧 attempt 级 `_record_instant_fail`
# 侧账仅辅助标注，不参与本判定）。与 runner 侧 cli-retry-backoff 的 attempt
# 级秒挂阈值同量级，数值独立维护、互不联动。
VERIFIER_DEATH_SURVIVAL_THRESHOLD_SECONDS = 60.0

# 启动期错误指纹标记（仅台账辅助标注用，MUST NOT 作为死亡命中条件——
# 形态级词表天然追不上新错误，分流主判据是进程级死亡特征本身）。
_DEATH_FINGERPRINT_MARKERS = (
    "enoent",
    "no such file",
    "file not found",
    "permission denied",
    "fork/exec",
    "spawn ",
)


def is_verifier_process_death(result) -> bool:
    """终局失败结果是否命中进程级死亡特征（evo-add-verifier-infra-death-triage R1）。

    判据（任一命中即死亡；MUST 在 ``enrich_failure_class`` 归因链上游消费，
    命中即不判 bug-found、走 infra 台账限次重派/超限暂挂）：

    - 终局结果 assistant 轮数为 0（``turns_used == 0``，runner 侧
      ``_exhausted_result`` 已回填真实累计轮数）；
    - 全部 attempt 存活低于秒挂判定阈值（终局结果 ``duration_seconds``——
      run 级总存活上界——低于 ``VERIFIER_DEATH_SURVIVAL_THRESHOLD_SECONDS``）。

    **保守缺省**：``turns_used``/``duration_seconds`` 缺失（``None``/属性不存在）
    或脏值（非数值）按「口径未知」处理——该项不命中，回落既有归因链按 product
    保守处置。宁可少分流，不可把口径未知的结果误判为死亡（误分流会绕过
    bug-found 出口）。非对象（None）恒不命中。
    """
    if result is None:
        return False
    # None（构造点未回填/替身缺属性）≠ 0（真实零轮）：未知口径不命中
    turns = getattr(result, "turns_used", None)
    if turns is not None:
        try:
            if int(turns) == 0:
                return True
        except (TypeError, ValueError):
            pass
    duration = getattr(result, "duration_seconds", None)
    if duration is not None:
        try:
            if float(duration) < VERIFIER_DEATH_SURVIVAL_THRESHOLD_SECONDS:
                return True
        except (TypeError, ValueError):
            pass
    return False


def annotate_death_fingerprint(error_text: str) -> str:
    """启动期错误指纹辅助标注（仅写入台账留痕，MUST NOT 作为命中条件）。

    返回标注串（``startup-error-fingerprint:<marker>`` / 无命中
    ``process-death:no-fingerprint``），由调用方拼入 infra 记账 reason 与
    暂挂 evidence，供事后排障追溯；词表追不上新错误形态是设计前提，
    标注缺失不影响分流判定本身。
    """
    text = str(error_text or "").lower()
    for marker in _DEATH_FINGERPRINT_MARKERS:
        if marker in text:
            return f"startup-error-fingerprint:{marker}"
    return "process-death:no-fingerprint"


# ── evo-verify-infra-retry-lane：infra-retry 车道判定与限次 ─────────

# infra-retry 廉价重派预算缺省值（design D2）：与 ENV_BLOCK_FREEZE_THRESHOLD=2
# 同量级，防预检失败被无限重试烧预算。语义=同一 spec 连续 prepare/可达性短路
# 失败最多廉价重派 N 次（专用计数 1..N 落「重派」决议），第 N+1 次短路失败
# 恢复既有全价升级。最坏多烧 N 次短路轮（0 场景执行成本），远低于一次全价
# 升级（admin run + 冻结轮）。
INFRA_RETRY_MAX_DEFAULT = 2


def _read_infra_retry_max(pipeline) -> int:
    """infra-retry 重派预算读取（``verify_engine.infra_retry_max``，缺省 2）。

    None 显式判空回退缺省、非数字回退缺省（口径对齐 escalation._read_int_config
    同款防御）；非正值非法，同样回退缺省（0/负值会使「重派」决议不可达）。
    """
    try:
        value = pipeline._context.config_reader(
            "verify_engine.infra_retry_max", INFRA_RETRY_MAX_DEFAULT
        )
        if value is None:
            return INFRA_RETRY_MAX_DEFAULT
        n = int(value)
    except (TypeError, ValueError):
        return INFRA_RETRY_MAX_DEFAULT
    return n if n > 0 else INFRA_RETRY_MAX_DEFAULT


def resolve_infra_retry_decision(pipeline, spec_name: str) -> str:
    """infra-retry 限次决议：专用连续重派计数 +1 后与预算比较（design D2）。

    专用计数（``_verify_infra_retry_streak``）与既有 ``_verify_infra_rounds``
    （纯观测）严格分离——后者被 ``_escalate_env_blocked`` 既有挂钩点在每个
    全价 env 阻塞轮递增，历史轮会吃掉重试预算、使「缺省 2 次」承诺不可达；
    本计数清零点=验证 PASS（对齐 _verify_fail_rounds 唯一归零点）+
    unfreeze_spec 清零清单。两本账互不递增对方的判定。

    Returns:
        "redispatch"：未超预算，廉价重派（不计 env 冻结轮、不呼叫 admin）；
        "escalate"：达预算，恢复既有全价升级。计数失败时保守返回 "escalate"
        （决议不可得时不无限重试）。
    """
    try:
        streak = pipeline._context.state_machine.bump_verify_infra_retry_streak(
            spec_name, +1
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"infra-retry 专用计数失败（保守走全价升级）'{spec_name}': "
            f"{type(e).__name__}: {e}",
        )
        return "escalate"
    max_retry = _read_infra_retry_max(pipeline)
    if streak <= max_retry:
        return "redispatch"
    return "escalate"


# ── evo-infra-failure-budget-exempt R2：infra 失败统一记账 ─────────


def _record_infra_failure(
    pipeline, spec_name: str, reason: str, run_id: str = "", ledger_run_id: str = "",
    retry_gate: bool = False,
) -> str | None:
    """infra 失败统一记账（evo-infra-failure-budget-exempt R2/R3）。

    在 infra 判定命中时调用：预算事后补偿（delegate budget.py
    ``_exempt_infra_run_budget``，幂等）+ _verify_infra_rounds +
    失败历史台账 failure_class=infra（回拨参考）。

    幂等锚点=当前实现 run id（``implementer_run``，由调用方经 ``run_id``
    传入或缺失时内部读取）；同一实现 run 的多次 infra 判定仅首次退款，
    后续只补计数与台账（预算侧独立记账由 budget.py 保证）。``run_id``
    MUST 只传实现 run id——verifier/judge 等 attempt run id 会使每个
    attempt 锚点各异、按实现 run 的幂等去重失效（同一实现 run 多退，
    code-review item 87cfffac1d3c）；verifier 侧事件标识经
    ``ledger_run_id`` 传入，仅落到失败台账的 run_id 字段（观测用），
    不参与退款锚点，缺省回退退款锚点。

    evo-verify-infra-retry-lane D6：``retry_gate=True``（仅
    ``_escalate_env_blocked`` 的 prepare/可达性 fail-fast 入口传入）时在记账
    之外先咨询 infra-retry 限次决议（``resolve_infra_retry_decision``，专用
    计数 +1）。记账照常执行（``_verify_infra_rounds`` 观测账两车道照常递增、
    归零点不变），两分支共用本调用作为唯一入账点——调用方 MUST NOT 在
    "escalate" 决议后二次调用本函数（观测账/退款会双计）。

    Returns:
        ``retry_gate=False`` 恒 ``None``（既有调用方零感知）；
        ``retry_gate=True`` 返回 "redispatch"（未达预算，调用方走旁路）或
        "escalate"（达预算，调用方落穿既有全价路径）。决议/记账异常时保守
        返回 "escalate"。本身异常不得抛穿调用方（记账属侧车，不阻断主流程）。
    """
    decision: str | None = None
    try:
        # ── infra-retry 限次决议先行（retry_gate 车道；D6 决策单点）──
        if retry_gate:
            decision = resolve_infra_retry_decision(pipeline, spec_name)
        # ── 幂等锚点：优先取给入 run_id，否则回读当前实现 run ──
        refund_key = run_id
        if not refund_key:
            entry0 = pipeline._context.state_machine.read_one(spec_name) or {}
            refund_key = str(entry0.get("implementer_run") or "")
        if not refund_key:
            # 空锚点（run_id 未传且 STATE 条目 implementer_run 为空）：budget 侧
            # 契约「无锚点仍退款（调用方保证单轮单次）」，退款幂等完全由调用方
            # 纪律保证且台账 run_id 失去定位键，留 warning 排查线索
            # （code-review item f2b25a17959d）。
            pipeline._context.logger.warning(
                "pm_engine",
                f"infra 退款无幂等锚点（refund_key 为空，单轮单次依赖调用方保证，"
                f"台账 run_id 定位键缺失）'{spec_name}': reason={reason}",
            )
        # 失败台账 run_id：事件标识（如 verifier attempt run），缺省回退退款锚点
        ledger_key = ledger_run_id or refund_key

        # ── 预算事后补偿（退款 + _infra_failure_count，幂等）──
        # 核心实现收敛在 budget.py（对齐 _exempt_dead_run_budget），
        # 对账豁免（_budget_reconcile_has_exemption）同侧维护。
        try:
            pipeline._context.exempt_infra_run_budget(spec_name, reason, refund_key=refund_key)
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"infra 预算退款失败（不阻断下游记账）'{spec_name}': "
                f"refund_key={refund_key}: {e}",
            )

        # ── _verify_infra_rounds 轮次记账（纯观测，不参与冻结判定）──
        # 局部容错：失败时 rounds 取 None，不阻断下游台账写入（与上/下记账步骤同构）
        try:
            rounds = pipeline._context.state_machine.bump_verify_infra_rounds(spec_name, +1)
        except Exception as e:
            rounds = None
            pipeline._context.logger.warning(
                "pm_engine",
                f"_verify_infra_rounds 记账失败（不阻断下游记账）'{spec_name}': "
                f"{type(e).__name__}: {e}",
            )

        # ── 失败历史台账 failure_class=infra（R3 回拨参考）──
        # 记录点在统一归因入口：infra 轮不进 bug-found 分支，
        # 仅在 _append_fail_history 扩展会致台账永远无 infra 轮，
        # 验收「台账含 2 条 infra 轮」与 design R3 落空。
        try:
            _append_fail_history(
                pipeline,
                spec_name,
                "infra",
                [],
                failure_class="infra",
                run_id=ledger_key,
            )
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"infra 失败台账写入失败（不阻断下游记账）'{spec_name}': "
                f"refund_key={refund_key}: {type(e).__name__}: {e}",
            )

        pipeline._context.logger.info(
            "pm_engine",
            f"infra 记账完成 '{spec_name}': _verify_infra_rounds={rounds}"
            + (f", infra_retry_decision={decision}" if retry_gate else ""),
        )
        return decision
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"infra 记账异常（不阻断主流程）'{spec_name}': {e}",
        )
        # retry_gate 车道决议不可得（记账/决议中途异常）：保守按「达预算」
        # 处置，调用方落穿既有全价升级，不无限廉价重试
        return "escalate" if retry_gate else None


def _reset_uniform_fail_streak(pipeline, spec_name: str) -> None:
    """同因失败哨连续计数回落：本轮已确定非「全场景同因失败」时归零。

    docstring/推荐动作承诺的「连续 _UNIFORM_SAME_CAUSE_BLOCK_THRESHOLD（3）
    轮同因」按连续轮次熔断——通过轮或
    混合失败轮若不回落，_uniform_fail_attempts 按生命周期累计，非连续的
    偶发同因失败也会误触发 blocked。仅计数非零时才落一次 update_spec
    （常态验证轮零额外写）；回落失败不阻断本轮判定。
    """
    try:
        spec = pipeline._context.state_machine.read_one(spec_name) or {}
        if not int(spec.get("_uniform_fail_attempts", 0) or 0):
            return
        pipeline._context.state_machine.update_spec(
            spec_name, {"_uniform_fail_attempts": 0}
        )
    except (TypeError, ValueError):
        return
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"_uniform_fail_attempts 回落失败（不阻断判定）'{spec_name}': "
            f"{type(e).__name__}: {e}",
        )


def _detect_uniform_verify_failure(pipeline, spec_name: str, report: dict) -> bool:
    """全场景同因失败哨：pass=0 且全部失败场景（fail/error）错误签名一致 → 疑环境/场景问题。

    呼叫 admin 介入判断（verify_uniform_failure 信号，major）；不判
    bug-found、不派生 fix。连续同因达 _UNIFORM_SAME_CAUSE_BLOCK_THRESHOLD
    （3）轮 → blocked 交人工。
    Returns: True 表示本轮已按同因失败处理（调用方跳过后续判定）。
    """
    summary = report.get("summary") or {}
    try:
        passed = int(summary.get("passed", 0) or 0)
        # failed 与 errors 分开计数（与 fastlane 子集重验同源口径），失败轮合计看两者
        failed = int(summary.get("failed", 0) or 0)
        errors = int(summary.get("errors", 0) or 0)
        total = int(summary.get("total", 0) or 0)
    except (TypeError, ValueError):
        # summary 数值字段脏值=本轮不可判定：与函数内其余非同因分支一致回落
        # 连续计数，避免脏报告轮夹在中间时前后同因失败跨轮累计到熔断阈值
        # （code-review item 86a1aee32a50）。
        _reset_uniform_fail_streak(pipeline, spec_name)
        return False
    fail_total = failed + errors
    if passed != 0:
        # 本轮存在通过场景 → 非「全场景同因失败」轮，连续计数回落为 0
        _reset_uniform_fail_streak(pipeline, spec_name)
        return False
    if fail_total < _UNIFORM_MIN_FAIL_TOTAL:
        # 0 passed 但失败不足 _UNIFORM_MIN_FAIL_TOTAL 的小失败轮：非「全场景
        # 同因失败」轮，同样回落连续计数（与 passed>0 / 混合签名轮处置一致，
        # 兑现信号文案与 docstring「连续 _UNIFORM_SAME_CAUSE_BLOCK_THRESHOLD
        # 轮同因」的『连续』口径）
        _reset_uniform_fail_streak(pipeline, spec_name)
        return False
    # 仅失败态场景纳入哨（fail/failed/error，与 summary 的 failed+errors 同口径），
    # warning/blocked-env 不混入；纯 error 轮也要覆盖
    failed_scns = [
        s
        for s in (report.get("scenarios") or [])
        if isinstance(s, dict) and s.get("status") in ("fail", "failed", "error")
    ]
    if len(failed_scns) < fail_total:
        # 报告口径不一致，不哨：本轮未确立同因失败，连续计数同样回落
        # （与 passed>0 / fail_total<_UNIFORM_MIN_FAIL_TOTAL / 混合签名轮处置一致）
        _reset_uniform_fail_streak(pipeline, spec_name)
        return False
    sigs: set[str] = set()
    for s in failed_scns:
        sig = ""
        for a in s.get("assertion_results") or []:
            # 非 dict 条目（脏 report.json）跳过，与场景级 isinstance 过滤同口径
            if isinstance(a, dict) and a.get("pass") is False:
                sig = str(a.get("error") or "")
                break
        if not sig:
            for st in s.get("step_results") or []:
                if isinstance(st, dict) and st.get("success") is False:
                    sig = str(st.get("error") or st.get("detail") or "")
                    break
        sigs.add(_normalize_fail_signature(sig)[:120])
    if len(sigs) != 1:
        # 失败签名不一致（混合失败轮）：非同因失败轮，连续计数回落为 0
        _reset_uniform_fail_streak(pipeline, spec_name)
        return False
    signature = next(iter(sigs))
    if not signature:
        # 全部失败场景均无可提取错误文本：空签名只是「无因可查」，
        # 不证明全场景同因，按报告不完整处理，走常规升级通道。
        # 本轮未确立同因，连续计数同样回落（与其他非同因分支一致）。
        _reset_uniform_fail_streak(pipeline, spec_name)
        return False
    spec = pipeline._context.state_machine.read_one(spec_name) or {}
    try:
        attempts = int(spec.get("_uniform_fail_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    note = (
        f'全场景同因失败（{fail_total}/{total}，签名一致: "{signature[:60]}"）'
        f"——疑似环境或场景问题，已呼叫 admin 介入判断（第 {attempts} 次）"
    )
    store = AdminStore(pipeline._context.project_root, pipeline._context.logger)
    try:
        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": "verify_uniform_failure",
                "spec": spec_name,
                "severity": "major",
                "description": note,
                "evidence": f"signature={signature[:120]}; failed={fail_total}",
                "recommended_action": (
                    "判断失败类别：环境问题（实例/端口/构建）→ 修复后把 spec 拨回 "
                    "implemented 重验；场景/plan 问题 → 修正或重写场景；确认真实 "
                    f"缺陷 → 人工处置。连续 {_UNIFORM_SAME_CAUSE_BLOCK_THRESHOLD} "
                    "轮同因将自动 blocked。"
                ),
            }
        )
        # code-review item 551c66ae82db：文件损坏留底被下限保护拒写时 append
        # 返回 None（core/admin_store.py append 契约，item 2570ca391771：记录
        # 未落盘，按未落地处理）——未达阈值轮该 SIGNAL 是 Administrator 的
        # 唯一通知面，拒写后实际收不到信号，不得落进下方成功路径日志误导
        # 排查（与 family._signal_family_explosion 判空口径一致，item
        # 17c3e99da9b7 / ae509e1816f3）。
        if rec is None:
            pipeline._context.logger.warning(
                "pm_engine",
                f"verify_uniform_failure 信号未落盘（store 拒写，按未落地处理）: "
                f"'{spec_name}' 第 {attempts} 次呼叫 admin 未送达",
            )
    except Exception as e:
        pipeline._context.logger.error("pm_engine", f"verify_uniform_failure 信号写入失败: {e}")
    if attempts >= _UNIFORM_SAME_CAUSE_BLOCK_THRESHOLD:
        # code-fix 09da400d938c：阈值轮「blocked 交人工」（docstring 语义）收敛到
        # freeze_for_human 单一入口，与 judge_gate._judge_hard_cap_freeze
        # （code-fix 0eda9bae5886）同款硬化——原先裸 update_spec 置 blocked 无
        # frozen 结构化标记，blocked_stuck 看门狗三选一豁免（frozen 字段 /
        # 'frozen:' 前缀 / '用户指令' 子串）全不命中，「交人工」实际会被自动派
        # admin run。自动呼叫 admin 不依赖该裸写：上方 verify_uniform_failure
        # SIGNAL 属 STORED_SIGNAL_TYPES，由 _detect_family_explosion 按记录摄取
        # 即唤起 Administrator（含本轮，带专属三分支处置指引）；本入口则保证
        # frozen 与人工升级告警成对落盘。tester_run 清空与 attempts 计数经
        # extra_updates 并入同一原子写（error/status/frozen 三键由入口自管）。
        pipeline._context.state_machine.freeze_for_human(
            spec_name,
            error=note,
            signal_type="verify_uniform_failure",
            severity="major",
            description=note,
            evidence=f"signature={signature[:120]}; failed={fail_total}",
            recommended_action=(
                "判断失败类别：环境问题（实例/端口/构建）→ 修复后把 spec 拨回 "
                "implemented 重验；场景/plan 问题 → 修正或重写场景；确认真实 "
                f"缺陷 → 人工处置。已连续 {_UNIFORM_SAME_CAUSE_BLOCK_THRESHOLD} "
                "轮同因，spec 已冻结等待人工。"
            ),
            alert_callback=pipeline._context.escalation_notifier,
            extra_updates={
                "_uniform_fail_attempts": attempts,
                "tester_run": None,
            },
        )
    else:
        # 未达阈值：仅落 error 文案与连续计数，不改状态（继续按轮呼叫 admin）。
        pipeline._context.state_machine.update_spec(
            spec_name,
            {"error": note, "_uniform_fail_attempts": attempts},
        )
    pipeline._context.logger.warning("pm_engine", f"全场景同因失败哨触发 '{spec_name}': {note}")
    return True


def _fail_history_path(pipeline, spec_name: str) -> Path:
    return (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / _FAIL_HISTORY_FILENAME
    )


def _read_fail_history(pipeline, spec_name: str) -> list:
    """读取失败历史侧车；缺失/损坏返回 []（升级告警据此标注 unknown）。"""
    try:
        path = _fail_history_path(pipeline, spec_name)
        if not path.exists():
            return []
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            return []
        return [r for r in loaded if isinstance(r, dict)]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []


def _append_fail_history(
    pipeline,
    spec_name: str,
    cause_type: str,
    failed_scenarios: list,
    failure_class: str = "",
    run_id: str = "",
) -> None:
    """原子追加一轮失败记录 {round, cause_type, failed_scenarios, failure_class, run_id}。

    ``cause_type`` ∈ evidence-invalid（证据校验不合规） / real-bugs（真缺陷）
    / infra（基础设施失败，evo-infra-failure-budget-exempt R3）。

    ``failure_class`` ∈ infra / product / unknown（三态归因；缺省补 unknown）。
    **记录点须在统一归因入口**：infra 轮不进入 bug-found 分支，其台账条目由
    ``_record_infra_failure`` 在归因入口判定处写入——仅在 family.py:488 扩展
    则台账永远不含 infra 轮，验收「台账含 2 条 infra 轮」与 design R3 落空。

    ``run_id``：本轮验证 run id（回拨参考台账按 run 定位）。

    写盘失败（含读损坏）静默降级：仅 warning 留痕，不阻断调用方流程。
    """
    try:
        path = _fail_history_path(pipeline, spec_name)
        rounds = _read_fail_history(pipeline, spec_name)
        # 条目 round 脏值（读损坏非数值字符串）按 0 计容错（口径对齐文件内
        # 既有 try/except (TypeError, ValueError) 写法）——兑现 docstring
        # 「含读损坏静默降级」承诺，单条脏数据不炸穿调用方验证判定。
        next_round = 0
        for r in rounds:
            try:
                next_round = max(next_round, int(r.get("round", 0) or 0))
            except (TypeError, ValueError):
                continue
        next_round += 1
        # [fenix-ignore:e2c24507d8e4] 单写者核实成立：三处生产写入均在 daemon 单进程同轮验证结果消费路径（infra 记账/裁决证据拒收/bug-found 每轮互斥只走其一），同 spec 事件处理由 _handling_events + _dispatch_guard_lock 单飞去重，无跨进程写者（dashboard/admin 仅触达 reclassify，不写 fail_history）——read-modify-write 无并发覆写窗口。
        rounds.append(
            {
                "round": next_round,
                "cause_type": cause_type,
                "failed_scenarios": [str(s) for s in (failed_scenarios or [])],
                "failure_class": failure_class or "unknown",
                "run_id": run_id or "",
            }
        )
        # 原子写收口共享助手 core.fs_utils.atomic_write_text（code-review
        # item 8668d3068858）：mkstemp 唯一临时名 + fsync + 目录 fsync 纪律
        # 单点维护，替代本处手写第四套 mkstemp 实现（原实现只 flush 不
        # fsync，掉电可丢已 replace 的台账尾部）；父目录创建由助手内部完成。
        # inherit_existing_mode=True：既有台账文件权限原样继承不被静默放宽
        # （对齐 verify_report 口径）；序列化文本与原 json.dump 参数逐字等价。
        atomic_write_text(
            path,
            json.dumps(rounds, ensure_ascii=False, indent=2),
            inherit_existing_mode=True,
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"fail_history 写回失败 '{spec_name}'（静默降级）: {e}",
        )


def _clear_fail_history(pipeline, spec_name: str) -> None:
    """清空失败历史侧车（verified 终态 / 升级告警消费后）。"""
    try:
        path = _fail_history_path(pipeline, spec_name)
        if path.exists():
            path.unlink()
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"fail_history 清理失败 '{spec_name}'（静默降级）: {e}",
        )


def _scenario_classification_distribution(pipeline, spec_name: str) -> dict:
    """读 report.json 场景 classification 分布（改道门判定依据）。

    Returns:
        dict：{'total': n, 'failed_ids': [...], 'counts': {分类: 数},
               'product_bug': int, 'all_scenario_defects': bool,
               'unclassified': int}——任意读取/解析异常返回空统计
        （total=0，改道判定自然不触发，保守不改道）。
    """
    from collections import Counter

    dist = {
        "total": 0,
        "failed_ids": [],
        "counts": {},
        "product_bug": 0,
        "all_scenario_defects": False,
        "unclassified": 0,
    }
    report = pipeline._read_verify_report(spec_name)
    if not isinstance(report, dict):
        return dist
    scenarios = report.get("scenarios") or []
    if not isinstance(scenarios, list):
        return dist
    failed: list = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        if sc.get("status") in ("pass", "passed"):
            continue
        sid = sc.get("scenario_id") or sc.get("id") or "?"
        # 非 str（脏数据可为 list/dict 等不可哈希值）归一为 None，走 unclassified
        # 口径，避免下方 Counter 构造抛 TypeError: unhashable type
        raw_cls = sc.get("classification")
        failed.append((str(sid), raw_cls if isinstance(raw_cls, str) else None))
    if not failed:
        return dist
    counts = Counter(cls for _sid, cls in failed)
    product_bug = int(counts.get("product-bug", 0) or 0)
    unclassified = sum(
        1
        for _sid, cls in failed
        if not isinstance(cls, str) or cls not in VERDICT_CLASSES
    )
    # 全场景缺陷判定：全部失败场景均为显式 test-defect/flaky 且 product-bug=0
    # （未显式分类 / 含 env / 含产品缺陷 → False，保守不改道）。
    all_scenario_defects = (
        len(failed) > 0
        and product_bug == 0
        and unclassified == 0
        and all(cls in ("test-defect", "flaky") for _sid, cls in failed)
    )
    return {
        "total": len(failed),
        "failed_ids": [sid for sid, _cls in failed],
        "counts": dict(counts),
        "product_bug": product_bug,
        "unclassified": unclassified,
        "all_scenario_defects": all_scenario_defects,
    }


def _failed_scenario_ids(pipeline, spec_name: str) -> list:
    """从当前 report.json 提取非 PASS 场景 id 列表（失败轮 failed_scenarios）。

    读取器与 _scenario_classification_distribution 同源（统一经
    pipeline._read_verify_report）：读取失败/非 dict 报告时该函数降级
    返回 {}，在此自然归约为空清单（缺报告 ⇒ 无失败场景），返回约定不变。
    """
    report = pipeline._read_verify_report(spec_name)
    if not isinstance(report, dict):
        return []
    ids = []
    for sc in report.get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        if sc.get("status") not in ("pass", "passed"):
            sid = sc.get("scenario_id") or sc.get("id")
            if sid:
                ids.append(str(sid))
    return ids


# ── 场景缺陷改道门（add-scenario-defect-triage-gate D1/D2/D3）────────


def _normalize_fail_signature(text: str) -> str:
    """归一化失败签名：数字→N、去引号、折叠空白，便于同因比较。"""
    t = re.sub(r"\d+", "N", text or "")
    t = re.sub(r"['\"`]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _read_fail_rounds(entry: dict) -> int:
    """容错读取 ``_verify_fail_rounds``（reclassify_infra_rounds 三处共用）。

    缺失/脏值（非数值字符串）按 0 计，口径对齐文件内既有
    try/except (TypeError, ValueError) 写法。
    """
    try:
        return int(entry.get("_verify_fail_rounds", 0) or 0)
    except (TypeError, ValueError):
        return 0


def reclassify_infra_rounds(
    project_root,
    state_machine,
    logger,
    spec_name: str,
    n: int,
    audit_reason: str,
    actor: str = "admin",
) -> dict:
    """从 ``_verify_fail_rounds`` 减回实为 infra 却误计入的历史轮次（evo-infra-failure-budget-exempt R3）。

    admin 声明「实为 infra 的历史轮次」后执行：原子改写
    ``_verify_fail_rounds = max(0, 当前值 - n)`` + 解冻 + 审计留痕。

    **幂等**（admin_store DISPOSITION 记录按 reclassify_key 去重，重复回拨
    不二次扣减）：同一 ``(spec, n, audit_reason)`` 组合只应用一次。

    **回拨方向**（只做减法）：product→infra 方向（实为 infra 却计入
    fail_rounds）；env→product-bug 属相反方向（补计），不在此入口。

    Args:
        project_root: 主树根目录（git 合并判定 + AdminStore 路径）。
        state_machine: StateMachine 实例（读写 STATE.md）。
        logger: Logger 实例。
        spec_name: 目标 spec 名称。
        n: 减回轮次（>0，取 max(0, current-n)）。
        audit_reason: 人工审核原因文本（审计留痕，入 admin_store DISPOSITION）。
        actor: 回拨发起者标识（"admin" / "dashboard" / "cli"）。

    Returns:
        dict：{ok, fail_rounds, status, applied}。
        ok=True 表示已应用；applied=实际减回轮次（受 current 上限约束）；
        ok=False 时 fail_rounds 为当前值（未变化），由调用方按需展示 reason。
    """
    if n <= 0:
        # 早退分支同样补 status（code-review item 9ef7cac1f57a）：对齐
        # docstring 返回契约 {ok, fail_rounds, status, applied}，避免按键
        # 直取的调用方 KeyError。
        entry = state_machine.read_one(spec_name) or {}
        return {
            "ok": False,
            "reason": "n must be > 0",
            "fail_rounds": _read_fail_rounds(entry),
            "status": entry.get("status", ""),
            "applied": 0,
        }

    # ── 幂等：按 reclassify_key 去重 ──
    reclassify_key = _hash.sha256(
        f"{spec_name}|{n}|{audit_reason}".encode("utf-8", "replace")
    ).hexdigest()[:16]

    store = AdminStore(project_root, logger)
    try:
        existing = store.read_records()
    except Exception as e:
        # 读失败保守按「未应用」继续（不新增失败返回形态，调用方解构不变），
        # 但留 warning 排查线索：若此处读失败而后续 append 成功，重试同键会因
        # 幂等键查不到而二次扣减（code-review item 811ef69c8cf1）。
        existing = []
        if logger is not None:
            logger.warning(
                "pm_engine",
                f"infra 回拨幂等检查读 admin_store 失败（按未应用继续，幂等保证"
                f"退化）'{spec_name}': reclassify_key={reclassify_key}: "
                f"{type(e).__name__}: {e}",
            )
    # 归档侧兜底（code-review item cae980a7ffe1）：活跃池写回时自动裁剪到
    # MAX_RECORDS=150、被裁记录移入归档（read_records 不合并归档）——daemon
    # 长跑积累超 150 条后，早期回拨的幂等键被裁出活跃查重窗口，同键重复提交
    # 会二次扣减 _verify_fail_rounds。查重合并 read_archive()（归档侧
    # MAX_ARCHIVE_RECORDS=2000，覆盖裁剪逃逸），恢复 docstring「重复回拨不
    # 二次扣减」承诺；归档读自身软失败（缺失/不可读返回空列表），此处异常
    # 兜底与上方活跃读失败降级同口径。
    try:
        archived = store.read_archive()
    except Exception as e:
        archived = []
        if logger is not None:
            logger.warning(
                "pm_engine",
                f"infra 回拨幂等检查读 admin_store 归档失败（按无归档继续，幂等保证"
                f"退化）'{spec_name}': reclassify_key={reclassify_key}: "
                f"{type(e).__name__}: {e}",
            )
    already_applied = any(
        rec.get("kind") == DISPOSITION
        and rec.get("signal_type") == RECLASSIFY_SIGNAL_TYPE
        and rec.get("spec") == spec_name
        and rec.get("reclassify_key") == reclassify_key
        for rec in existing + archived
    )
    if already_applied:
        entry = state_machine.read_one(spec_name) or {}
        return {
            "ok": True,
            "applied": 0,
            "fail_rounds": _read_fail_rounds(entry),
            "status": entry.get("status", ""),
            "note": "already applied (idempotent)",
        }

    # ── 读当前值 ──
    entry = state_machine.read_one(spec_name) or {}
    current = _read_fail_rounds(entry)
    applied = min(n, current)
    new_fail_rounds = current - applied

    # ── 目标状态判定（复用 resolve_env_blocked_reset_path 语义）──
    if entry.get("status") == "blocked" and not entry.get(FROZEN_FIELD):
        reset_path = resolve_env_blocked_reset_path(entry, project_root)
        # reset_path 原样采用（code-review item 800e1f308b9a）：None = 无合法
        # 复位转换——预检只排除了 frozen 结构化标记，而「人工冻结」是 frozen
        # 标记与 error 文本 FREEZE_ERROR_PREFIX 前缀的双判据（任一命中即人工
        # 冻结），error 前缀形态下 resolve 返回 None。此前 `or "ready"` 兜底
        # 会把该形态自动拨回 ready 重实现通道，违背 branch_guard /
        # _escalate_env_blocked「人工处置是唯一出路」的门禁契约（branch_guard
        # docstring：调用方不应触发任何复位转换）。None 时保持 status 不变、
        # 仅扣减 fail_rounds，人工冻结形态原样留待人工处置。
        target_status = reset_path
    else:
        target_status = None

    # ── 审计留痕（admin_store DISPOSITION，幂等由 reclassify_key 去重）──
    # 先落幂等键再扣减：append 拒写（文件损坏留底被下限保护，返回 None，
    # 见 core/admin_store.py append 契约 item 2570ca391771）时幂等键未落盘，
    # 直接返回失败、不执行扣减——否则重试在 already_applied 检查中找不到
    # 键会二次扣减，超出 admin 声明的 n 轮上限（code-review item
    # b0d51bd553d4）；append 抛异常（如 OSError）时状态尚未被改动，调用方
    # 重试会重新走完整流程且只扣一次。若先扣减后写审计，append 失败时幂等
    # 键未落盘，重试同样会二次扣减。反向窗口（append 成功后扣减失败）由
    # already_applied 幂等短路兜底——fail_rounds 保持偏高（预算偏紧，不放大
    # 重试预算）。
    rec = store.append(
        {
            "kind": DISPOSITION,
            "signal_type": RECLASSIFY_SIGNAL_TYPE,
            "spec": spec_name,
            "severity": "major",
            "description": f"infra 回拨 {applied} 轮（{audit_reason[:300]}）",
            "action_taken": (
                f"_verify_fail_rounds: {current}→{new_fail_rounds}（减 {applied}），"
                f"status → {target_status or 'unchanged'}"
            ),
            "result": "resolved",
            "recommended_action": "",
            "summary": f"reclassify {applied} infra rounds, actor={actor}",
            "admin_run_id": f"reclassify:{reclassify_key}",
            "reclassify_key": reclassify_key,
        }
    )
    if rec is None:
        # 拒写分支同样补 status（code-review item 1e4a2eab58b4）：对齐 docstring
        # 返回契约 {ok, fail_rounds, status, applied}，避免按键直取的调用方
        # KeyError（与 n<=0 早退分支同惯例）。
        return {
            "ok": False,
            "reason": "audit append rejected",
            "fail_rounds": current,
            "status": entry.get("status", ""),
            "applied": 0,
        }

    # ── 原子写入 ──
    updates = {"_verify_fail_rounds": new_fail_rounds}
    if target_status is not None:
        # unfreeze_spec 清零相关计数器 + 恢复 status
        state_machine.unfreeze_spec(spec_name, status=target_status)
    state_machine.update_spec(spec_name, updates)
    if logger is not None:
        logger.warning(
            "pm_engine",
            f"infra 回拨: '{spec_name}' _verify_fail_rounds {current}→{new_fail_rounds}"
            f"（减回 {applied} 轮，audit={audit_reason[:120]}）",
        )

    return {
        "ok": True,
        "fail_rounds": new_fail_rounds,
        "status": (state_machine.read_one(spec_name) or {}).get("status", ""),
        "applied": applied,
    }
