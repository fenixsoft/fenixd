"""core.pm_engine.verification.infra_classify — infra 失败归因/历史/回拨组（refactor-verification-module D2）。

从 VerificationPipeline 摘出 infra 判定（infra 指标/降级标记）、失败历史
（per-spec fail_history.json 读写清理）、归一化签名、场景分类分布、
失败场景 ID 提取、同因失败哨、infra 回拨入口。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import hashlib as _hash
import json
import os
import re
import tempfile
from pathlib import Path

from core.admin_store import AdminStore, DISPOSITION
from core.pm_engine.verification.branch_guard import resolve_env_blocked_reset_path
from core.agent_runner.prompt_builder import planner_result_status_whitelist
from core.state_machine import INFRA_FAILURE_COUNT_FIELD, VERIFY_INFRA_ROUNDS_FIELD

# 回拨审计留痕信号类型（幂等键前缀，admin_store DISPOSITION 按 reclassify_key 去重）
RECLASSIFY_SIGNAL_TYPE = "infra_reclassify"

# per-spec fail_history.json 文件名
_FAIL_HISTORY_FILENAME = "fail_history.json"


def _verifier_error_is_infra(pipeline, error_text: str) -> bool:
    """verifier 失败是否属基础设施类（不得流转 bug-found）。

    覆盖：provider 熔断抑制、failover 链耗尽（chain exhausted）、
    classify_switch_error 可识别的切换类错误（unrecognized_model/5xx/网络）。
    此类失败说明「验证没能发生」，不是「验证发现了缺陷」。
    """
    if not error_text:
        return False
    if "provider circuit open" in error_text or "chain exhausted" in error_text:
        return True
    try:
        # 严格 is True：分类器返回非布尔（如测试桩）时按非基础设施处理
        return pipeline._pm.agent_runner.classify_switch_error(error_text) is True
    except Exception:
        return False


# ── evo-infra-failure-budget-exempt R1：统一失败归因接口 ───────────

# infra 降级触发 error 文本标记（enrich_failure_class 判定）。R1 有意收窄为
# worktree / merge conflict / tree dirty 六项——仅命中本清单才判 infra。
_INFRA_DEGRADE_MARKERS = (
    "worktree",
    "git worktree add",
    "worktree lock",
    "worktree already exists",
    "merge conflict",
    "tree dirty",
)


def enrich_failure_class(
    pipeline, spec_name: str, error_text: str = "", result=None, result_path: Path | None = None
) -> str:
    """统一失败归因接口：返回 ``infra`` | ``product`` | ``unknown``（evo-infra-failure-budget-exempt R1）。

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


# ── evo-infra-failure-budget-exempt R2：infra 失败统一记账 ─────────


def _record_infra_failure(pipeline, spec_name: str, reason: str, run_id: str = "") -> None:
    """infra 失败统一记账（evo-infra-failure-budget-exempt R2/R3）。

    在 infra 判定命中时调用：预算事后补偿（delegate budget.py
    ``_exempt_infra_run_budget``，幂等）+ _verify_infra_rounds +
    失败历史台账 failure_class=infra（回拨参考）。

    幂等锚点=当前实现 run id（``implementer_run``，由调用方经 ``run_id``
    传入或缺失时内部读取）；同一实现 run 的多次 infra 判定仅首次退款，
    后续只补计数与台账（预算侧独立记账由 budget.py 保证）。

    本身异常不得抛穿调用方（记账属侧车，不阻断主流程）。
    """
    try:
        # ── 幂等锚点：优先取给入 run_id，否则回读当前实现 run ──
        refund_key = run_id
        if not refund_key:
            entry0 = pipeline._context.state_machine.read_one(spec_name) or {}
            refund_key = str(entry0.get("implementer_run") or "")

        # ── 预算事后补偿（退款 + _infra_failure_count，幂等）──
        # 核心实现收敛在 budget.py（对齐 _exempt_dead_run_budget），
        # 对账豁免（_budget_reconcile_has_exemption）同侧维护。
        try:
            pipeline._context.exempt_infra_run_budget(spec_name, reason, refund_key=refund_key)
        except Exception:
            pass  # 预算侧车异常不阻断下游记账

        # ── _verify_infra_rounds 轮次记账（纯观测，不参与冻结判定）──
        rounds = pipeline._context.state_machine.bump_verify_infra_rounds(spec_name, +1)

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
                run_id=refund_key,
            )
        except Exception:
            pass

        pipeline._context.logger.info(
            "pm_engine",
            f"infra 记账完成 '{spec_name}': _verify_infra_rounds={rounds}",
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"infra 记账异常（不阻断主流程）'{spec_name}': {e}",
        )


def _detect_uniform_verify_failure(pipeline, spec_name: str, report: dict) -> bool:
    """全场景同因失败哨：pass=0 且全部失败场景（fail/error）错误签名一致 → 疑环境/场景问题。

    呼叫 admin 介入判断（verify_uniform_failure 信号，major）；不判
    bug-found、不派生 fix。连续 3 轮同因 → blocked 交人工。
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
        return False
    fail_total = failed + errors
    if passed != 0 or fail_total < 3:
        return False
    # 非 PASS 场景即纳入哨（fail/failed/error），纯 error 轮也要覆盖
    failed_scns = [
        s for s in (report.get("scenarios") or []) if s.get("status") not in ("pass", "passed")
    ]
    if len(failed_scns) < fail_total:
        return False  # 报告口径不一致，不哨
    sigs: set[str] = set()
    for s in failed_scns:
        sig = ""
        for a in s.get("assertion_results") or []:
            if a.get("pass") is False:
                sig = str(a.get("error") or "")
                break
        if not sig:
            for st in s.get("step_results") or []:
                if st.get("success") is False:
                    sig = str(st.get("error") or st.get("detail") or "")
                    break
        sigs.add(_normalize_fail_signature(sig)[:80])
    if len(sigs) != 1:
        return False
    signature = next(iter(sigs))
    spec = pipeline._context.state_machine.read_one(spec_name) or {}
    try:
        attempts = int(spec.get("_uniform_fail_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    note = (
        f'全场景同因失败（{fail_total}/{total}，签名一致: "{signature[:60]}"）'
        f"——疑似环境或场景问题，已呼叫 admin 介入判断（第 {attempts} 次）"
    )
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(pipeline._context.project_root, pipeline._context.logger)
    try:
        store.append(
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
                    "缺陷 → 人工处置。连续 3 轮同因将自动 blocked。"
                ),
            }
        )
    except Exception as e:
        pipeline._context.logger.error("pm_engine", f"verify_uniform_failure 信号写入失败: {e}")
    updates: dict = {
        "error": note,
        "_uniform_fail_attempts": attempts,
    }
    if attempts >= 3:
        updates["status"] = "blocked"
        updates["tester_run"] = None
    pipeline._context.state_machine.update_spec(spec_name, updates)
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
        next_round = max([int(r.get("round", 0) or 0) for r in rounds], default=0) + 1
        rounds.append(
            {
                "round": next_round,
                "cause_type": cause_type,
                "failed_scenarios": [str(s) for s in (failed_scenarios or [])],
                "failure_class": failure_class or "unknown",
                "run_id": run_id or "",
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=".fail_history.", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rounds, f, ensure_ascii=False, indent=2)
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
        failed.append((str(sid), sc.get("classification")))
    if not failed:
        return dist
    counts = Counter(cls for _sid, cls in failed)
    product_bug = int(counts.get("product-bug", 0) or 0)
    unclassified = sum(
        1
        for _sid, cls in failed
        if not isinstance(cls, str) or cls not in ("product-bug", "test-defect", "flaky", "env")
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
    """从当前 report.json 提取非 PASS 场景 id 列表（失败轮 failed_scenarios）。"""
    from core.verdict_check import load_report

    report = load_report(pipeline._context.project_root, spec_name)
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
        return {"ok": False, "reason": "n must be > 0", "fail_rounds": 0, "applied": 0}

    # ── 幂等：按 reclassify_key 去重 ──
    import hashlib as _hash

    reclassify_key = _hash.sha256(
        f"{spec_name}|{n}|{audit_reason}".encode("utf-8", "replace")
    ).hexdigest()[:16]

    from core.admin_store import AdminStore, DISPOSITION

    store = AdminStore(project_root, logger)
    try:
        existing = store._read_locked()
    except Exception:
        existing = []
    already_applied = any(
        rec.get("kind") == DISPOSITION
        and rec.get("signal_type") == RECLASSIFY_SIGNAL_TYPE
        and rec.get("spec") == spec_name
        and rec.get("reclassify_key") == reclassify_key
        for rec in existing
    )
    if already_applied:
        entry = state_machine.read_one(spec_name) or {}
        try:
            cur_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
        except (TypeError, ValueError):
            cur_rounds = 0
        return {
            "ok": True,
            "applied": 0,
            "fail_rounds": cur_rounds,
            "status": entry.get("status", ""),
            "note": "already applied (idempotent)",
        }

    # ── 读当前值 ──
    entry = state_machine.read_one(spec_name) or {}
    try:
        current = int(entry.get("_verify_fail_rounds", 0) or 0)
    except (TypeError, ValueError):
        current = 0
    applied = min(n, current)
    new_fail_rounds = current - applied

    # ── 目标状态判定（复用 resolve_env_blocked_reset_path 语义）──
    if entry.get("status") == "blocked" and not entry.get("frozen"):
        reset_path = resolve_env_blocked_reset_path(entry, project_root)
        target_status = reset_path or "ready"
    else:
        target_status = None

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

    # ── 审计留痕（admin_store DISPOSITION，幂等由 reclassify_key 去重）──
    store.append(
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

    return {
        "ok": True,
        "fail_rounds": new_fail_rounds,
        "status": (state_machine.read_one(spec_name) or {}).get("status", ""),
        "applied": applied,
    }
