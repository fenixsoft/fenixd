"""verdict_check.py — 裁决证据分类校验器（add-verdict-evidence-taxonomy）。

设计依据：design.md D1-D5。

裁决链：验证引擎产出 report.json（逐场景 status / assertion_results / screenshots）
→ planner-judge 读取并**增强** report.json（每个非 PASS 场景补 classification 与
evidence，逻辑见 agent_runner.py 的 planner-judge prompt）→ pm_engine 裁决采纳处
消费。

本模块是独立于裁决的纯 Python 校验器（与 scenario-freeze 同型），输入增强后的
report.json，校验：
  - 字段齐全性：每个非 PASS 场景 MUST 含 classification 与 evidence
  - 取值合法性：classification ∈ {product-bug, test-defect, flaky, env}
  - 分类-状态映射：product-bug / test-defect MUST 映射为 failed；flaky / env MAY
    映射为 warning；禁止 product-bug 映射为 warning（D3）
  - 逐断言归因（add-interaction-contract-and-per-assert-triage D3）：每个非 PASS
    场景 MUST 含 assertion_triage 数组，对其每条失败断言单独归类（四分类）并附
    证据；场景级豁免（不记产品 Bug）仅当全部失败断言均非 product-bug 时成立

不合规由调用方（pm_engine 采纳处）走既有裁决重试一次；二次失败 → blocked-env +
告警（与 verify-report-gate 的阻断语义一致）。

向后兼容：report.json 无 classification/evidence 字段（旧格式）时，validate_report
返回 ok=False 且每条非 PASS 场景都标 violation（驱动重试补全），不静默放行。
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from core.fast_track_result import SCENARIO_STATUSES

# 四分类取值（design D1）
VERDICT_CLASSES = ("product-bug", "test-defect", "flaky", "env")

# 非 PASS 状态（这些场景 MUST 带 classification + evidence + assertion_triage）
NON_PASS_STATUSES = ("fail", "failed", "error", "warning")

# classification → 强制状态映射（design D3）
# product-bug / test-defect MUST → failed；flaky / env 允许 warning（不强制）。
FORCE_FAILED_CLASSES = ("product-bug", "test-defect")

# 场景级豁免（warning / 不记产品 Bug）的豁免理由文案（报告豁免清单用）
EXEMPTION_REASON = {
    "test-defect": "测试用例自身缺陷（非产品缺陷）",
    "flaky": "不稳定复现（非产品缺陷）",
    "env": "环境因素（非产品缺陷）",
}

# ── 非驱动视觉状态（fix-visual-baseline-settle D4）──────────────────
# baseline_deferred（基线固化前置条件未满足，本轮不固化不比对）与
# baseline_rejected（健全性判定拒绝固化）属「本轮无法/拒绝对比」语义，与
# env/flaky 同属不构成打回依据：
#   - 引擎侧 determine_scenario_status 已保证此类视觉状态不使场景降档
#     （baseline_deferred 不落 warning/failed，场景按 DOM 断言正常判档）；
#   - 既有豁免通道（_EXEMPT_ALLOWED_CLASSES / is_scenario_exemptible）对其
#     放行——此类场景要么 status=pass 无需分类，要么按 DOM 断言单独归因。
NON_DRIVING_VISUAL_STATUSES = ("baseline_deferred", "baseline_rejected")


def has_only_non_driving_visual_indicators(scenario: dict) -> bool:
    """场景的失败信号是否仅来自非驱动视觉状态（无 DOM/步骤失败）。

    Returns:
        True 表示：全部 DOM 断言通过、无步骤失败，且 visual_results 中存在
        baseline_deferred/baseline_rejected（不含 diff_detected/warning 类
        驱动视觉结论）——judge 不得将其计入 bug-found 打回依据（同 flaky/env
        待遇）；场景整体 status 应判 pass，无需分类与归因。
    """
    if not isinstance(scenario, dict):
        return False
    for a in scenario.get("assertion_results") or []:
        if isinstance(a, dict) and not a.get("pass", True):
            return False
    for s in scenario.get("step_results") or []:
        if isinstance(s, dict) and not s.get("success", True):
            return False
    visual = scenario.get("visual_results")
    if not isinstance(visual, list) or not visual:
        return False
    for v in visual:
        if not isinstance(v, dict):
            continue
        if v.get("status") in ("diff_detected", "warning"):
            return False  # 存在驱动视觉结论，非「仅非驱动」
    return any(
        isinstance(v, dict) and v.get("status") in NON_DRIVING_VISUAL_STATUSES for v in visual
    )


def _is_non_pass(status: Optional[str]) -> bool:
    if not status:
        return False
    return status in NON_PASS_STATUSES


def _evidence_present(evidence: Any) -> bool:
    """判断 evidence 是否非空（满足「至少一个证据维度」）。

    证据至少含：失败断言列表（failed_assertions 非空）/ 截图路径
    （screenshots 非空）/ 首个失败步骤（first_failed_step 非空字符串）。
    兼容历史字段（assertion_results / assertion 列表）便于旧夹具过渡。
    """
    if not isinstance(evidence, dict):
        return False
    # 失败断言列表：优先 failed_assertions，兼容 assertion_results / assertion
    for key in ("failed_assertions", "assertion_results", "assertion"):
        val = evidence.get(key)
        if isinstance(val, list) and val:
            return True
    # 截图路径
    shots = evidence.get("screenshots")
    if isinstance(shots, list) and any(isinstance(s, str) and s.strip() for s in shots):
        return True
    # 首个失败步骤（字符串）
    ffs = evidence.get("first_failed_step")
    if isinstance(ffs, str) and ffs.strip():
        return True
    return False


def _evidence_value_present(evidence: Any) -> bool:
    """assertion_triage 条目的 evidence 是否非空（字符串非空白 / dict 非空）。"""
    if isinstance(evidence, str):
        return bool(evidence.strip())
    if isinstance(evidence, dict):
        return bool(evidence)
    if isinstance(evidence, list):
        return bool(evidence)
    return False


def triage_entries(scenario: dict) -> List[dict]:
    """场景的 assertion_triage 数组（缺失/非法时返回空表）。"""
    triage = scenario.get("assertion_triage") if isinstance(scenario, dict) else None
    if not isinstance(triage, list):
        return []
    return [t for t in triage if isinstance(t, dict)]


def is_expandable_evidence_violation(reason: str) -> bool:
    """判断 judge 违规是否属「可补证据」类型（add-verify-lane-throughput 3.2）。

    可补 = evidence 缺失/截断类（validate_report 产出的 reason 以 "evidence"
    开头，如 "evidence 为空"）——补证后局部重判即可修复；
    不可补 = classification 非法（"classification 缺失或取值非法"）、逐断言
    归因违规（"assertion_triage …"）、report 结构损坏（"report.json 非对象"）
    等，须按真实重裁决记账。

    前缀判定保持与 validate_report reason 词表解耦：词表新增 evidence 类
    reason（如截断）自动纳入可补集，无需改本函数。
    """
    return isinstance(reason, str) and reason.startswith("evidence")


def triage_violation(scenario: dict) -> Optional[str]:
    """逐断言归因合规性检查（add-interaction-contract-and-per-assert-triage D3）。

    非 PASS 场景 MUST 含 assertion_triage，对每条失败断言单独归类（四分类）并附
    非空证据。合规返回 None；不合规返回首个违规原因文案。

    规则：
      - assertion_triage 缺失/为空 → 违规（未逐条归因）
      - 条目缺 assertion 内容 / classification 非法 / evidence 为空 → 违规
      - 条目数少于失败断言数 → 违规（漏条目，整体豁免会吞掉漏归因的断言）
    """
    if not isinstance(scenario, dict):
        return None
    status = scenario.get("status")
    if not _is_non_pass(status):
        return None

    triage = triage_entries(scenario)
    if not triage:
        return "assertion_triage 缺失或为空（failed 场景 MUST 逐条归类失败断言）"

    for i, entry in enumerate(triage, 1):
        assertion = entry.get("assertion")
        if not (isinstance(assertion, str) and assertion.strip()):
            return f"assertion_triage 第 {i} 条缺 assertion 内容"
        if entry.get("classification") not in VERDICT_CLASSES:
            return f"assertion_triage 第 {i} 条 classification 缺失或取值非法"
        if not _evidence_value_present(entry.get("evidence")):
            return f"assertion_triage 第 {i} 条 evidence 为空"

    # 漏条目检测：失败断言数多于归因条数 → 有断言未被单独归类
    failed_count = 0
    ars = scenario.get("assertion_results")
    if isinstance(ars, list):
        failed_count = sum(1 for a in ars if isinstance(a, dict) and not a.get("pass", True))
    if failed_count and len(triage) < failed_count:
        return (
            f"assertion_triage 仅 {len(triage)} 条，少于失败断言数 {failed_count}"
            f"（MUST 逐条归类全部失败断言）"
        )
    return None


def has_product_bug_assertion(scenario: dict) -> bool:
    """场景的失败断言中是否存在归类 product-bug 的条目（D3：阻止场景级豁免）。"""
    return any(t.get("classification") == "product-bug" for t in triage_entries(scenario))


def is_scenario_exemptible(scenario: dict) -> bool:
    """场景级豁免（不记产品 Bug）是否成立（D3）。

    仅当该场景全部失败断言均被单独归类为非 product-bug（且逐断言归因合规）时
    成立；含任一 product-bug 断言 → 不得豁免。
    """
    if not _is_non_pass(scenario.get("status")):
        return False
    if triage_violation(scenario) is not None:
        return False
    return not has_product_bug_assertion(scenario)


def whitewash_violations(scenarios: list, verdict: str) -> List[str]:
    """verified 洗白不变量（help-center 0/15 verified 事故的防线）。

    - 0 通过 + 有失败 → 不得 verified（无论失败分类为何——合成报告
      「0/15 通过（全部场景通过）」式的自相矛盾再也不能合法存在）；
    - 任一失败分类为 env → 不得 verified（env 问题须升级 admin 处置，
      不得当作豁免理由放行——「遇到 env 就不测试了」被本检查封死）；
    - 场景表存在非对象条目（损坏场景表）→ 不得 verified（fail-closed，
      零有效场景的损坏报告不得静默放行）。

    仅约束 verdict=verified；bug-found 不受限。Returns: 违规说明列表（空=放行）。
    """
    if verdict != "verified" or not isinstance(scenarios, list) or not scenarios:
        return []
    total = len(scenarios)
    passed = 0
    env_failed: List[str] = []
    has_failed = False
    invalid_idx: List[str] = []
    for idx, sc in enumerate(scenarios, 1):
        if not isinstance(sc, dict):
            # 非 dict 条目属结构损坏：fail-closed 不静默跳过（与
            # validate_fast_track_result「场景 #N 非对象」同口径），否则
            # 全垃圾场景表会绕过本不变量在零有效场景上放行 verified
            invalid_idx.append(f"#{idx}")
            continue
        sid = str(sc.get("scenario_id") or "?")
        # 双词表对齐（item 229075ac0732）：与本模块其余函数同口径——"passed"
        # 亦为通过态（下游 verdict_evidence/pipeline 均按双词表防御），否则
        # 全过报告会被误判 0 通过而错误阻断合法 verified 裁决。
        if sc.get("status") in ("pass", "passed"):
            passed += 1
        else:
            has_failed = True
            if sc.get("classification") == "env":
                env_failed.append(sid)
    violations: List[str] = []
    if invalid_idx:
        violations.append(
            f"{len(invalid_idx)}/{total} 场景条目非对象（损坏场景表）不得判 verified: "
            + "、".join(invalid_idx[:8])
        )
    if has_failed and passed == 0:
        violations.append(f"0/{total} 场景通过（全部失败）不得判 verified")
    if env_failed:
        violations.append(
            "env 失败场景不得判 verified（须升级 admin 处置）: " + "、".join(env_failed[:8])
        )
    return violations


def validate_report(report: dict) -> dict:
    """校验增强后的 report.json 分类与证据合规。

    Args:
        report: parse_report / json.loads(report.json) 解析出的 dict。

    Returns:
        {"ok": bool,
         "violations": [{"scenario_id", "status", "reason"}],
         "classified": [scenario_id...]}  # 合规的非 PASS 场景 id 列表
    """
    if not isinstance(report, dict):
        return {
            "ok": False,
            "violations": [
                {"scenario_id": None, "status": None, "reason": "report.json 非对象"},
            ],
            "classified": [],
        }

    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        # 无场景条目：视为无待校验对象，合规（不阻塞 verified 路径）
        return {"ok": True, "violations": [], "classified": []}

    violations: List[dict] = []
    classified: List[str] = []
    for idx, sc in enumerate(scenarios, 1):
        if not isinstance(sc, dict):
            # 非 dict 条目属结构损坏：记 violation（fail-closed，不静默放行；
            # 与 validate_fast_track_result「场景 #N 非对象」同口径）
            violations.append(
                {
                    "scenario_id": f"#{idx}",
                    "status": None,
                    "reason": f"场景 #{idx} 非对象",
                }
            )
            continue
        status = sc.get("status")
        if not _is_non_pass(status):
            continue
        sid = sc.get("scenario_id") or sc.get("id") or "?"
        classification = sc.get("classification")
        evidence = sc.get("evidence")

        if classification not in VERDICT_CLASSES:
            violations.append(
                {
                    "scenario_id": sid,
                    "status": status,
                    "reason": "classification 缺失或取值非法",
                }
            )
            continue
        if not _evidence_present(evidence):
            violations.append(
                {
                    "scenario_id": sid,
                    "status": status,
                    "reason": "evidence 为空",
                }
            )
            continue
        # 逐断言归因（add-interaction-contract-and-per-assert-triage D3）：
        # 每个 scenario 至多一条 violation（保持「一场景一违规」语义，便于重试定位）
        triage_reason = triage_violation(sc)
        if triage_reason:
            violations.append(
                {
                    "scenario_id": sid,
                    "status": status,
                    "reason": triage_reason,
                }
            )
            continue
        classified.append(sid)

    return {"ok": len(violations) == 0, "violations": violations, "classified": classified}


def enforce_status_mapping(report: dict) -> dict:
    """按分类-状态映射表强制重写场景 status（design D3）。

    规则：
      - classification ∈ {product-bug, test-defect} 但 status != failed
        → 强制 status=failed，并标记该条目为「已修正」（供报告标注，
        防止 LLM 输出漂移悬置产品缺陷）。
      - 逐断言归因（add-interaction-contract-and-per-assert-triage D3）：
        assertion_triage 中任一断言归类 ∈ {product-bug, test-defect} 但场景
        status != failed → 强制 failed（单条 product-bug 断言阻止场景级豁免）。
      - 其余（flaky / env 允许 warning，或已是 failed）→ 不动。

    返回：
        {"report": <原地增强后的 dict>,
         "corrected": [{"scenario_id", "from_status", "to_status",
                        "classification"}]}  # 被强制改写的条目
    注意：原地修改入参 report（与 verify_report.render 同约定，便于调用方直接
    写回文件）。
    """
    corrected: List[dict] = []
    if not isinstance(report, dict):
        return {"report": report, "corrected": corrected}
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return {"report": report, "corrected": corrected}

    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        classification = sc.get("classification")
        status = sc.get("status")
        # 逐断言归因优先：失败断言级 product-bug/test-defect 强制 failed
        offending = None
        for t in triage_entries(sc):
            t_cls = t.get("classification")
            if t_cls in FORCE_FAILED_CLASSES:
                offending = t_cls
                break
        if offending is not None and status != "failed":
            from_status = status
            sc["status"] = "failed"
            sc["status_corrected"] = True
            sc["exempt_blocked_by_assertion"] = True  # 豁免被单断言阻断的留痕
            corrected.append(
                {
                    "scenario_id": sc.get("scenario_id") or sc.get("id") or "?",
                    "from_status": from_status,
                    "to_status": "failed",
                    "classification": offending,
                }
            )
            continue
        if classification in FORCE_FAILED_CLASSES and status != "failed":
            from_status = status
            sc["status"] = "failed"
            sc["status_corrected"] = True  # 报告标注「已修正」
            corrected.append(
                {
                    "scenario_id": sc.get("scenario_id") or sc.get("id") or "?",
                    "from_status": from_status,
                    "to_status": "failed",
                    "classification": classification,
                }
            )
    return {"report": report, "corrected": corrected}


def exempted_assertions(report: dict) -> List[dict]:
    """收集被豁免的失败断言（add-interaction-contract-and-per-assert-triage D4）。

    豁免 = 断言失败但不记产品 Bug：非 PASS 场景的 assertion_triage 中归类为
    test-defect / flaky / env 的条目（product-bug 条目进「真实产品 Bug」，不豁免）。

    Returns:
        [{"scenario_id", "assertion", "classification", "evidence", "reason"}]，
        供报告渲染「断言级豁免清单」。旧报告无 assertion_triage 时返回空表。
    """
    rows: List[dict] = []
    if not isinstance(report, dict):
        return rows
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return rows
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "-")
        for t in triage_entries(sc):
            cls = t.get("classification")
            if cls == "product-bug":
                continue  # 产品缺陷不被豁免
            if cls not in VERDICT_CLASSES:
                continue
            evidence = t.get("evidence")
            if isinstance(evidence, (dict, list)):
                evidence = json.dumps(evidence, ensure_ascii=False)
            rows.append(
                {
                    "scenario_id": sid,
                    "assertion": str(t.get("assertion") or "-"),
                    "classification": cls,
                    "evidence": str(evidence or "-"),
                    "reason": str(t.get("reason") or EXEMPTION_REASON.get(cls, "-")),
                }
            )
    return rows


# ── 归因分级（add-verdict-credibility-gate / spec: verdict-attribution-evidence-gate）──
# 框架侧机械计算归因级别（design D2）：judge 只产出归因文本与证据引用，
# 级别由框架算出（不依赖 judge 自律与多模态能力）。
ATTRIBUTION_LEVEL_EVIDENCE_BACKED = "evidence-backed"
ATTRIBUTION_LEVEL_SPECULATIVE = "speculative"
ATTRIBUTION_LEVEL_PENDING_VISUAL = "pending-visual"
ATTRIBUTION_LEVELS = (
    ATTRIBUTION_LEVEL_EVIDENCE_BACKED,
    ATTRIBUTION_LEVEL_SPECULATIVE,
    ATTRIBUTION_LEVEL_PENDING_VISUAL,
)

# 视觉类断言关键词（用于 pending-visual 判定）
_VISUAL_ASSERTION_KEYWORDS = (
    "render",
    "style",
    "layout",
    "visual",
    "screenshot",
    "css",
    "screenshot_mismatch",
    "pixel",
    "image",
    "visible",
    "display",
    "color",
    "font",
    "border",
    "background",
)


def _scenario_has_substantive_evidence(scenario: dict) -> bool:
    """判断场景是否有「实质性证据」支撑归因（非空 evidence 构成）。

    实质性证据 = 非空截图列表 / 有算法标签 / 有 first_failed_step /
    有 failed_assertions / 有 first_frame_ok 结构化字段。

    evidence 形状防御（code-review item 803f6a23f662）：judge 产出非 dict
    （非空字符串等 truthy 形态）时按空 evidence 处理、保守降级 speculative
    路径，MUST NOT 抛 AttributeError——异常会被 escalation 门禁的
    「异常不阻断」分支吞掉，本应被抑制的 speculative 打回信号就此放行。
    """
    evidence = scenario.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    screenshots = evidence.get("screenshots") or scenario.get("screenshots") or []
    if isinstance(screenshots, list) and any(isinstance(s, str) and s.strip() for s in screenshots):
        return True
    # screenshot_labels 非 dict 按空处理（与 compute_attribution_level 的
    # item 6151f22ae34d 防御同口径：非 dict 真值在此被当「有算法标签」
    # 会把纯推测归因抬升为 evidence-backed，旁路 speculative 抑制门）。
    labels = scenario.get("screenshot_labels") or {}
    if not isinstance(labels, dict):
        labels = {}
    if labels:
        return True
    for key in ("first_failed_step", "first_frame_ok"):
        val = evidence.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, bool):
            return True
    if _scenario_has_failed_assertion_evidence(scenario):
        return True
    return False


def _scenario_has_failed_assertion_evidence(scenario: dict) -> bool:
    """场景是否有失败断言归因（assertion_triage 带非空 evidence）。"""
    triage = scenario.get("assertion_triage") or []
    if not isinstance(triage, list):
        return False
    for t in triage:
        if not isinstance(t, dict):
            continue
        ev = t.get("evidence")
        if isinstance(ev, str) and ev.strip():
            return True
        if isinstance(ev, dict) and ev:
            return True
    return False


def _is_product_bug_classification(classification: str) -> bool:
    """当前仅 product-bug 分类参与 pending-visual 判定（业务约束，
    非泛化的「是否涉及视觉现象」判定：test-defect/flaky/env 等一律 False）。"""
    return classification in ("product-bug",)


def _has_visual_assertions(scenario: dict) -> bool:
    """场景的失败断言是否涉及视觉现象。"""
    triage = scenario.get("assertion_triage") or []
    if isinstance(triage, list):
        for t in triage:
            if not isinstance(t, dict):
                continue
            assertion_text = str(t.get("assertion") or "").lower()
            evidence_text = str(t.get("evidence") or "").lower()
            for kw in _VISUAL_ASSERTION_KEYWORDS:
                if kw in assertion_text or kw in evidence_text:
                    return True
    ars = scenario.get("assertion_results") or []
    if isinstance(ars, list):
        for a in ars:
            if not isinstance(a, dict):
                continue
            if not a.get("pass", True):
                atype = str(a.get("type") or "").lower()
                if any(kw in atype for kw in _VISUAL_ASSERTION_KEYWORDS):
                    return True
    return False


def compute_attribution_level(scenario: dict) -> str:
    """框架侧机械计算归因级别（design D2 / Task 2.1）。

    输入：增强后的 scenario dict（含 classification / evidence /
    assertion_triage / screenshot_labels / screenshots）。

    规则（与 judge 模型能力无关，只读证据构成）：
      - evidence-backed：归因引用了结构化证据（失败断言文本、算法标签、
        结构化字段如 first_frame_ok/blank_screenshot）且与证据不矛盾
      - speculative：归因仅为推理链推测（无截图、无算法标签、无结构化字段支撑）
      - pending-visual：归因涉及视觉现象（渲染/样式/布局类断言）但既无截图
        佐证也无算法标签

    Returns:
        归因级别字符串（ATTRIBUTION_LEVELS 之一）
    """
    classification = scenario.get("classification")
    if classification in (None, "pass"):
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED  # pass 场景不需要归因

    # screenshot_labels 非 dict 按空处理（code-review item 6151f22ae34d，与
    # evidence 同款防御：非 dict 真值 .get 抛 AttributeError 会被门禁
    # 「异常不阻断」吞掉而旁路归因分级）。
    labels = scenario.get("screenshot_labels") or {}
    if not isinstance(labels, dict):
        labels = {}
    has_blank = labels.get("blank_screenshot", False)
    has_low_contrast = labels.get("low_contrast", False)
    has_labels = bool(labels)

    # 截图健全性标签是最强证据：白屏/低对比度均有算法标签佐证
    if has_blank or has_low_contrast:
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    # 有真实截图 + 有失败断言归因 → evidence-backed（视觉断言有截图佐证）
    # evidence 非 dict 按空处理（code-review item 803f6a23f662，与
    # _scenario_has_substantive_evidence 同款防御：非 dict 真值 .get 抛
    # AttributeError 会被门禁「异常不阻断」吞掉而旁路归因分级）。
    screenshots = scenario.get("screenshots") or []
    evidence = scenario.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    ev_screenshots = evidence.get("screenshots") or []
    has_real_screenshots = (
        isinstance(screenshots, list) and any(isinstance(s, str) and s.strip() for s in screenshots)
    ) or (
        isinstance(ev_screenshots, list)
        and any(isinstance(s, str) and s.strip() for s in ev_screenshots)
    )

    # 有算法标签 + 有失败断言归因 → evidence-backed
    if has_labels and _scenario_has_failed_assertion_evidence(scenario):
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    if has_real_screenshots and _scenario_has_failed_assertion_evidence(scenario):
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    # 归因涉及视觉现象但无截图/标签佐证 → pending-visual。只有有截图/有标签
    # 两路 evidence-backed 检测排在它之前（有截图时视觉断言可被证据支撑 →
    # evidence-backed）。有意设计（code-review item 78678bf1fa56）：它排在
    # first_failed_step+归因证据的通用 evidence-backed 检测之前——文字级归因
    # 证据不解除视觉类场景的 pending-visual，视觉断言仍待截图佐证
    # （tests/test_verdict_credibility_gate.py s7 钉死该顺序；下游
    # should_suppress_bug_found 对两级别同待遇）。
    if _is_product_bug_classification(classification):
        if _has_visual_assertions(scenario):
            return ATTRIBUTION_LEVEL_PENDING_VISUAL

    # 有 first_failed_step + 失败断言归因 → evidence-backed（视觉类场景已在
    # 上方先行判 pending-visual，不会走到这里）
    first_failed_step = evidence.get("first_failed_step") or ""
    if isinstance(first_failed_step, str) and first_failed_step.strip():
        if _scenario_has_failed_assertion_evidence(scenario):
            return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    # first_frame_ok=False 且分类为 env → evidence-backed（引擎结构化字段佐证）
    first_frame_ok = evidence.get("first_frame_ok")
    if first_frame_ok is False and classification == "env":
        return ATTRIBUTION_LEVEL_EVIDENCE_BACKED

    # 有其他证据但无法支撑分类 → 降级
    has_evidence = _scenario_has_substantive_evidence(scenario)
    if not has_evidence:
        return ATTRIBUTION_LEVEL_SPECULATIVE

    # 有失败断言归因但无截图/标签佐证 → 判断是否涉及视觉
    if _has_visual_assertions(scenario):
        return ATTRIBUTION_LEVEL_PENDING_VISUAL

    # 有 first_failed_step 但无失败断言归因 → 纯推理链 → speculative
    if isinstance(first_failed_step, str) and first_failed_step.strip():
        if not _scenario_has_failed_assertion_evidence(scenario):
            return ATTRIBUTION_LEVEL_SPECULATIVE

    return ATTRIBUTION_LEVEL_EVIDENCE_BACKED


def validate_attribution_levels(report: dict) -> dict:
    """校验并写入 report.json 全部场景的 attribution_level（设计 D2 / Task 2.1）。

    在 report 落盘/打回上下文组装前调用（与 validate_report 同入口位）。
    原地修改每个非 PASS 场景的 attribution_level 字段。

    注：本函数无失败路径——只做归因级别的机械计算与原地写入，不产生
    校验失败信号；``ok`` 恒为 True、``violations`` 恒为空列表，返回结构
    仅为兼容既有调用签名（code-review item 90330728c61a）。真正的失败
    判定由下游 should_suppress_bug_found / check_batch_attribution_dedup
    等函数承担。

    Returns:
        {"ok": bool, "violations": [str, ...]}
    """
    if not isinstance(report, dict):
        return {"ok": True, "violations": []}
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return {"ok": True, "violations": []}
    violations = []  # 恒空：仅写入 attribution_level，无校验失败路径
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        sc["attribution_level"] = compute_attribution_level(sc)
    return {"ok": True, "violations": violations}


def enforce_blank_screenshot_direction(scenario: dict) -> Optional[str]:
    """白屏方向约束（Task 2.3）：evidence 含 blank_screenshot: true 时归因
    必须引用该标签且限定 env 方向，不得归因于数据层或产品逻辑。

    框架强制改写：classification 不是 env → 改为 env（白屏有算法标签佐证，
    attribution_level 由 compute_attribution_level 判为 evidence-backed）。

    Returns:
        新的 classification（需要改写时）或 None（不需改写）。
    """
    # screenshot_labels 非 dict 按空处理（code-review item acc304e9e5c4，与
    # compute_attribution_level 同款防御：非 dict 真值 .get 抛 AttributeError
    # 会被门禁「异常不阻断」吞掉而旁路白屏方向强制改写）。
    labels = scenario.get("screenshot_labels") or {}
    if not isinstance(labels, dict):
        labels = {}
    if not labels.get("blank_screenshot", False):
        return None
    classification = scenario.get("classification") or ""
    if classification == "env":
        return None
    return "env"


def should_suppress_bug_found(report: dict) -> bool:
    """打回依据全部为 speculative 时抑制 bug-found 打回（Task 2.2）。

    当全部「驱动打回的场景」（classification ∈ product-bug/test-defect，
    即会作为 bug 依据打回 implementer 的场景）的 attribution_level 均为
    speculative（无任何 evidence-backed / pending-visual）时，返回 True——
    应抑制 bug-found 打回：转重验一次或写 error「归因证据不足待人工复核」，
    不得带推测信号打回 implementer。

    非驱动场景（env/flaky/warning 等排除类）不参与判定——它们不构成打回依据。
    """
    if not isinstance(report, dict):
        return False
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return False
    driver_count = 0
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        classification = sc.get("classification")
        if classification not in FORCE_FAILED_CLASSES:
            continue  # 非驱动场景（env/flaky 等）不参与打回判定
        driver_count += 1
        level = sc.get("attribution_level") or ATTRIBUTION_LEVEL_SPECULATIVE
        if level in (ATTRIBUTION_LEVEL_EVIDENCE_BACKED, ATTRIBUTION_LEVEL_PENDING_VISUAL):
            return False  # 至少一个驱动场景证据充分/待定，不抑制
    # 无驱动场景（全部 env/flaky 或全 PASS）→ 不存在 bug-found 打回依据
    return driver_count > 0


# ── 批量归因查重归一化细分 + 级联豁免（fix-verdict-dedup-resynthesis D3）──
# 16:39 事故解剖：judge 用脚本批量生成归因时 ``error[:120]`` 截断 + 共享模板串
# 使 5 个单根因级联场景完全坍缩——但它们的失败步骤序号/断言清单各异，归因高度
# 相似本是合法形态（前置步骤失败 → 后续场景级联失败），门的「逐字相同=偷懒」
# 假设对它失配。归一化细分：
#   - ``first_failed_step`` 拆「步骤序号 / 描述体」：步骤序号单独进指纹；
#     描述体哈希化（保持熵的同时避免整段原文撑爆指纹与 reason 摘录）；
#   - 级联豁免：组内 classification 相同、描述体（去步骤序号）两两前缀重合
#     ≥80%、但步骤序号集合或断言清单逐场景存在差异 → 该组不计违规；
#   - 纯模板偷懒（连步骤引用都逐字复制、断言也相同）→ 仍拒绝。

_CASCADE_ROOT_PREFIX_SIMILARITY = 0.8


def _extract_step_number(ffs_text) -> str:
    """从 first_failed_step 提取「步骤N」/「step N」前缀序号（无则空串）。

    级联豁免/指纹细分用：步骤序号是区分「共享根因的合法级联」与「连步骤
    引用都复制的模板偷懒」的关键场景局部数据。
    """
    if not isinstance(ffs_text, str):
        return ""
    m = re.search(r"(?:步骤|step)\s*(\d+)", ffs_text, flags=re.IGNORECASE)
    return m.group(1) if m else ""


def _first_failed_step_desc(ffs_text) -> str:
    """去除步骤序号前缀后的描述体（级联根因前缀重合比较用原文）。"""
    if not isinstance(ffs_text, str):
        return ""
    return re.sub(
        r"^\s*(?:步骤|step)\s*\d+\s*[:：]?\s*",
        "",
        ffs_text,
        flags=re.IGNORECASE,
    ).strip()


def _normalize_whitespace(text) -> str:
    """空白折叠 + strip（归一化比较的统一前置）。"""
    return re.sub(r"\s+", " ", (text or "")).strip()


def _prefix_similarity(a, b) -> float:
    """两串空白折叠后的公共前缀重合度：LCP 长度 / min(两长)。

    双空视为 1.0（同为缺失）；单空视为 0.0（无共享根因可言）。
    """
    a = _normalize_whitespace(a)
    b = _normalize_whitespace(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    lcp = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        lcp += 1
    return lcp / min(len(a), len(b))


def scenario_attribution_summary(sc: dict) -> str:
    """场景归因摘要（judge_attribution.json 条目 attribution 字段）。

    提取 classification + first_failed_step 关键片段 + 首条失败断言 label，
    拼接为 ≤200 字摘要，供逐场景条目落盘与场景级查重判定审计。字段缺失时
    返回空串（调用方按缺归因处理）。
    """
    parts = []
    cls = sc.get("classification")
    if isinstance(cls, str) and cls:
        parts.append(f"classification={cls}")
    evidence = sc.get("evidence")
    if isinstance(evidence, dict):
        ffs = evidence.get("first_failed_step")
        if isinstance(ffs, str) and ffs.strip():
            ffs_short = _normalize_whitespace(ffs)
            if len(ffs_short) > 80:
                ffs_short = ffs_short[:80] + "…"
            parts.append(f"first_failed_step={ffs_short}")
    triage = sc.get("assertion_triage")
    if isinstance(triage, list):
        for t in triage:
            if not isinstance(t, dict):
                continue
            assertion = str(t.get("assertion") or "").strip()
            if assertion:
                assertion_short = _normalize_whitespace(assertion)
                if len(assertion_short) > 60:
                    assertion_short = assertion_short[:60] + "…"
                parts.append(f"assertion={assertion_short}")
                break
    summary = "；".join(parts)
    if len(summary) > 200:
        summary = summary[:200] + "…"
    return summary


def _scenario_attribution_signature(sc: dict) -> dict:
    """场景归因的结构化签名（级联豁免判定用，区别于归一化指纹）。

    字段：classification、ffs_step（失败步骤序号）、ffs_desc（去序号后的
    描述体原文）、triage_labels（断言 label 清单）。这些是级联豁免据以
    区分「共享根因 / 各自局部证据」的直接素材。
    """
    evidence = sc.get("evidence") or {}
    ffs_text = ""
    if isinstance(evidence, dict):
        ffs = evidence.get("first_failed_step") or ""
        if isinstance(ffs, str):
            ffs_text = ffs
    triage = sc.get("assertion_triage") or []
    labels: List[str] = []
    if isinstance(triage, list):
        for t in triage:
            if isinstance(t, dict):
                assertion = str(t.get("assertion") or "").strip()
                if assertion:
                    labels.append(assertion)
    return {
        "classification": str(sc.get("classification") or ""),
        "ffs_step": _extract_step_number(ffs_text),
        "ffs_desc": _first_failed_step_desc(ffs_text),
        "triage_labels": sorted(labels),
    }


def _cascade_root_exemption(signatures: List[dict]) -> bool:
    """级联豁免判定（fix-verdict-dedup-resynthesis D3 / Task 1.2）。

    全部成立才豁免（返回 True = 该组不计违规）：
      1. 组内 classification 相同（豁免只对同分类生效）；
      2. 描述体（去步骤序号前缀）两两前缀重合 ≥ 80%（共享同一根因模板）；
      3. 步骤序号集合**或**断言 label 清单逐场景存在差异（不是逐字复制）。

    纯模板偷懒（连步骤引用都复制、断言也相同）→ 不豁免，仍拒绝。
    """
    if not signatures or len(signatures) < 2:
        return False
    classes = {s["classification"] for s in signatures}
    if len(classes) != 1:
        return False
    descs = [s["ffs_desc"] for s in signatures]
    for i in range(len(descs)):
        for j in range(i + 1, len(descs)):
            if _prefix_similarity(descs[i], descs[j]) < _CASCADE_ROOT_PREFIX_SIMILARITY:
                return False
    steps = {s["ffs_step"] for s in signatures}
    triage_sets = {",".join(s["triage_labels"]) for s in signatures}
    if len(steps) == 1 and len(triage_sets) == 1:
        return False  # 无任何场景局部差异 → 纯同文模板偷懒，不豁免
    return True


def _normalize_attribution(sc: dict) -> str:
    """归一化场景归因文本（strip + 空白折叠 + ffs 描述体哈希化）。

    fix-verdict-dedup-resynthesis 扩展：``first_failed_step`` 拆「步骤序号 /
    描述体」两步——步骤序号单独进指纹，描述体插哈希取前 32 位（保持熵的
    同时避免整段原文撑爆指纹）；断言 triage 的 assertion label 与 evidence
    保持原文进指纹（逐场景本就不同，保留即可区分）。
    """
    parts = []
    classification = sc.get("classification") or ""
    parts.append(f"cls={classification}")
    evidence = sc.get("evidence") or {}
    if isinstance(evidence, dict):
        ffs = evidence.get("first_failed_step") or ""
        if isinstance(ffs, str) and ffs.strip():
            step = _extract_step_number(ffs)
            desc = _first_failed_step_desc(ffs)
            desc_digest = hashlib.sha256(_normalize_whitespace(desc).encode("utf-8")).hexdigest()[
                :32
            ]
            parts.append(f"step={step}:desc={desc_digest}")
    triage = sc.get("assertion_triage") or []
    if isinstance(triage, list):
        for t in triage:
            if isinstance(t, dict):
                assertion = str(t.get("assertion") or "").strip()
                cls = str(t.get("classification") or "").strip()
                ev = t.get("evidence")
                if isinstance(ev, str):
                    ev = ev.strip()
                else:
                    ev = str(ev or "").strip()
                parts.append(f"a={assertion}:c={cls}:e={ev}")
    normalized = " ".join(parts)
    return re.sub(r"\s+", " ", normalized).strip()


def check_batch_attribution_dedup(report: dict) -> dict:
    """报告落盘前批量归因查重（Task 3.2 / D4；fix-verdict-dedup-resynthesis）。

    对全部非 PASS 场景归因归一化（strip + 空白折叠 + ffs 描述体哈希化）：
    ≥3 个场景逐字相同 → 拒绝采纳（返回 violations），要求逐场景归因后重合成。

    归一化细分 + 级联豁免（fix-verdict-dedup-resynthesis D3）：
    - 步骤序号进指纹——16:39 事故 5 个级联场景因 error[:120] 截断同文而误拒，
      但它们各自失败步骤/断言不同，是单根因级联失败的合法形态；
    - 级联豁免：同 classification、描述体（去步骤序号）两两前缀重合 ≥80%、
      但步骤序号集合或断言清单逐场景不同 → 该组不计违规（合法级联）；
    - 纯模板偷懒（连步骤引用都逐字复制）→ 仍拒绝。

    Returns:
        {"ok": bool, "violations": [{"scenario_ids": [...], "reason": str}]}
    """
    return _batch_attribution_dedup_common(report, scenario_level=False)


def check_batch_attribution_dedup_scenario(report: dict) -> dict:
    """批量归因查重场景级判定（add-judge-incremental-attribution 2.1 / D2）。

    与 ``check_batch_attribution_dedup`` 同源归一化与级联豁免，但判定粒度
    从整批降为场景：命中重复（≥3 场景归一化后逐字相同且非级联豁免）的
    场景归因置 ``requeue``（待回炉），其余非重复场景置 ``accept``（保留
    复用）——**MUST NOT 因子集重复废弃整轮已写盘归因**。

    Returns:
        {"ok": bool, "violations": [{"scenario_ids": [...], "reason": str}],
         "requeue_ids": [str],      # 命中重复、待回炉的场景 id
         "accept_ids": [str],       # 非重复、保留复用的场景 id
         "counts": {"total": int, "requeue": int, "accept": int}}
    """
    return _batch_attribution_dedup_common(report, scenario_level=True)


def _batch_attribution_dedup_common(report: dict, scenario_level: bool) -> dict:
    """批量归因查重的公共实现（整批 / 场景级两态共享）。

    scenario_level=False → 沿袭整批判定（仅返回 violations，拒绝由调用方
    按整批语义处置）；scenario_level=True → 追加 requeue_ids / accept_ids
    场景级粒度（调用方按设计 D2 驱动子集回炉）。

    退化输入（report 非 dict / scenarios 非列表）的早退分支同样保持与
    docstring 承诺一致的返回形状（场景级补齐空 requeue_ids / accept_ids /
    counts），避免调用方按下标访问时 KeyError。
    """
    extra: dict = {}
    if scenario_level:
        extra = {
            "requeue_ids": [],
            "accept_ids": [],
            "counts": {"total": 0, "requeue": 0, "accept": 0},
        }
    if not isinstance(report, dict):
        return {"ok": True, "violations": [], **extra}
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return {"ok": True, "violations": [], **extra}

    groups: dict[str, dict] = {}
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "?")
        norm = _normalize_attribution(sc)
        if not norm:
            continue
        grp = groups.setdefault(norm, {"scenario_ids": [], "signatures": []})
        grp["scenario_ids"].append(sid)
        grp["signatures"].append(_scenario_attribution_signature(sc))

    violations = []
    requeue_ids: List[str] = []
    accept_ids: List[str] = []
    for norm_text, grp in groups.items():
        sids = grp["scenario_ids"]
        if len(sids) < 3:
            accept_ids.extend(sids)
            continue
        if _cascade_root_exemption(grp["signatures"]):
            # 级联豁免：真共享根因但场景局部证据各异 → 合法，不计违规
            accept_ids.extend(sids)
            continue
        violations.append(
            {
                "scenario_ids": sids,
                "reason": (
                    f"{len(sids)} 个场景归因文本完全相同"
                    f"（归一化后逐字相同），疑似批量套用硬编码归因："
                    f"涉及场景 {', '.join(sids)}；"
                    f"重复文本=[{norm_text[:200]}]"
                ),
            }
        )
        if scenario_level:
            requeue_ids.extend(sids)

    if not scenario_level:
        return {"ok": len(violations) == 0, "violations": violations}

    # 场景级：全部参与判定的 id（含无归因文本场景——无归因不参与查重，视为保留）
    participating = set(accept_ids) | set(requeue_ids)
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        if sc.get("status") in ("pass", "passed"):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "?")
        if sid not in participating:
            accept_ids.append(sid)  # 无归因文本：不参与查重，保留
    counts = {
        "total": len(accept_ids) + len(requeue_ids),
        "requeue": len(requeue_ids),
        "accept": len(accept_ids),
    }
    return {
        "ok": len(requeue_ids) == 0,
        "violations": violations,
        "requeue_ids": requeue_ids,
        "accept_ids": accept_ids,
        "counts": counts,
    }


def tag_cached_attributions(report: dict, cache: dict, spec_name: str = "") -> list:
    """跨轮缓存归因打标（Task 3.1 / D3）。

    在 _verify_verdict_evidence 写回 report 前调用：对 verdict_cache 指纹
    命中的场景打 cached_from_previous_round: true + 来源轮次；纯缓存归因
    （无本轮新增 evidence-backed 证据）按 speculative 口径参与门禁。

    原地修改 report 的场景 dict。返回被打标的场景 id 列表。
    """
    if not isinstance(report, dict) or not isinstance(cache, dict):
        return []
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return []
    tagged_ids = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status in ("pass", "passed"):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "")
        entry = cache.get(sid)
        if not isinstance(entry, dict):
            continue
        fp = entry.get("fingerprint") or ""
        if not fp or fp != scenario_fingerprint(sc):
            continue
        sc["cached_from_previous_round"] = True
        cached_round = entry.get("source_round") or ""
        if cached_round:
            sc["cached_source_round"] = cached_round
        # 纯缓存归因（无本轮新增 evidence-backed 证据）→ 按 speculative 口径
        level = sc.get("attribution_level") or ATTRIBUTION_LEVEL_EVIDENCE_BACKED
        # screenshot_labels 非 dict 按空处理（code-review item 6151f22ae34d，
        # 与 compute_attribution_level 同款防御，防 AttributeError 被门禁吞掉）。
        labels = sc.get("screenshot_labels") or {}
        if not isinstance(labels, dict):
            labels = {}
        # evidence 非 dict 按空处理（与 _scenario_has_substantive_evidence /
        # compute_attribution_level 的 item 803f6a23f662 防御同口径：非 dict
        # 真值 .get 抛 AttributeError 会被门禁「异常不阻断」吞掉，跨轮缓存
        # 打标与纯缓存归因降级 speculative 整段被跳过）。
        evidence = sc.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        ev_screenshots = evidence.get("screenshots") or []
        has_real_screenshots = isinstance(ev_screenshots, list) and any(
            isinstance(s, str) and s.strip() for s in ev_screenshots
        )
        has_relevant_labels = labels.get("blank_screenshot") or labels.get("low_contrast")
        if not (has_real_screenshots or has_relevant_labels):
            # 纯缓存归因 → 降级 speculative（无论原级别：设计 D3
            # 规定纯缓存归因按 speculative 口径参与 2.2 门禁，
            # 防止跨轮缓存归因逃逸推测级抑制）
            if level != ATTRIBUTION_LEVEL_SPECULATIVE:
                sc["attribution_level"] = ATTRIBUTION_LEVEL_SPECULATIVE
                sc["cached_override_level"] = True
        tagged_ids.append(sid)
    return tagged_ids


# ── fast-track 统一结果文件硬校验（add-fast-track-mode / D6）────────────
# 三要素：
#   ① 报告结构完整（场景/结果/判定字段齐全）
#   ② 场景全量执行（设计集与执行集一致，无静默遗漏；豁免走既有豁免规则）
#   ③ 逐场景证据存在性（非 PASS 场景带分类与证据）
# agent 文本宣称不作为通过依据——框架只信可校验的输出（与完整模式 verifier
# 的判定信任模型一致，design D6）。


def _scenario_evidence_ok(sc: dict) -> bool:
    """逐场景证据存在性：非 PASS 场景 MUST 带 classification 与 evidence。

    与 fast_track_result 的 SCENARIO_STATUSES 对齐，并按本模块双词表口径
    补齐 passed/failed（见 _FAST_TRACK_SCENARIO_STATUSES）；非 PASS 集合
    {fail, failed, error, warning} 复用本模块 NON_PASS_STATUSES 判定。
    exempt 场景单独走豁免合法性检查（_exempt_classification_ok），不在此
    要求 evidence（豁免＝不必提交证据）。
    """
    if not isinstance(sc, dict):
        return False
    status = sc.get("status")
    if status not in _FAST_TRACK_SCENARIO_STATUSES:
        return False
    if status in NON_PASS_STATUSES:
        if sc.get("classification") not in VERDICT_CLASSES:
            return False
        return _evidence_present(sc.get("evidence"))
    return True


# 单点定义承诺（fast_track_result docstring）：复用 core.fast_track_result.SCENARIO_STATUSES，
# 避免与解析器两处词表漂移。在此之上补齐 pass/passed 与 fail/failed 双词表
# （item 244fa0af2fba）：本模块 whitewash_violations / validate_attribution_levels
# 与 NON_PASS_STATUSES 均按双词表防御，agent 写出 "passed"/"failed" 时
# 不得被判为非法状态（否则全过报告会被误报「证据缺失」）。
_FAST_TRACK_SCENARIO_STATUSES = tuple(
    dict.fromkeys(SCENARIO_STATUSES + ("passed", "failed"))
)

# 豁免合法性：exempt 场景的分类 MUST 为非 product-bug（豁免逃逸检查，D6）
_EXEMPT_ALLOWED_CLASSES = ("test-defect", "flaky", "env")


def _exempt_classification_ok(sc: dict) -> bool:
    """豁免合法性：status=exempt 的场景分类必须非 product-bug。"""
    if sc.get("status") != "exempt":
        return True
    return sc.get("classification") in _EXEMPT_ALLOWED_CLASSES


def validate_fast_track_result(result: dict, designed_ids: Optional[list] = None) -> dict:
    """确定性校验 fast-track 统一结果文件的三要素（add-fast-track-mode D6）。

    Args:
        result: 解析后的 .fenix-run-result.json dict（含 verification 段）。
        designed_ids: 设计场景 ID 集合（来自 test_scenarios.json，或 fast-track
            结果自带验证段的场景 ID）。None/空时跳过「全量执行」比对（无设计集
            可比对时无法证明静默遗漏，仅做结构与证据校验）。

    Returns:
        {"ok": bool, "violations": [str, ...]}
        - 结构非法（缺 verification / 缺 scenarios / verdict 非法）→ 单条 violation
          （fail-closed，不静默通过）
        - 场景全量执行：每个设计 ID 必须在执行集中出现；缺失 → violation 列出
        - 逐场景证据：每个非 PASS 场景缺分类/证据 → violation 列出
        - 豁免逃逸：status=exempt 且分类 product-bug → violation（视为 bug 未修复）
    """
    violations: list = []
    if not isinstance(result, dict):
        return {"ok": False, "violations": ["fast-track 结果文件非对象"]}
    verification = result.get("verification")
    if not isinstance(verification, dict):
        return {"ok": False, "violations": ["fast-track 结果文件缺 verification 段"]}
    scenarios = verification.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return {"ok": False, "violations": ["fast-track 结果文件 scenarios 缺失或为空"]}
    verdict = verification.get("verdict")
    if verdict not in ("verified", "bug-found"):
        return {"ok": False, "violations": [f"fast-track 结果文件 verdict 非法: {verdict!r}"]}

    for idx, sc in enumerate(scenarios):
        if not isinstance(sc, dict):
            violations.append(f"场景 #{idx + 1} 非对象")
            continue
        sid = sc.get("scenario_id") or f"#{idx + 1}"
        if sc.get("status") not in _FAST_TRACK_SCENARIO_STATUSES:
            violations.append(
                f"场景 {sid} status 非法: {sc.get('status')!r}"
                f"（合法取值: {'、'.join(_FAST_TRACK_SCENARIO_STATUSES)}）"
            )
        elif not _scenario_evidence_ok(sc):
            violations.append(
                f"场景 {sid} 证据缺失：非 PASS 场景 MUST 带合法 classification 与 evidence"
            )
        if not _exempt_classification_ok(sc):
            violations.append(
                f"场景 {sid} 豁免逃逸：status=exempt 但分类为 product-bug"
                "（豁免不得掩盖产品缺陷，视为 bug 未修复）"
            )

    # 场景全量执行：设计集与执行集一致，无静默遗漏
    executed_ids = {
        str(sc.get("scenario_id"))
        for sc in scenarios
        if isinstance(sc, dict) and sc.get("scenario_id")
    }
    if designed_ids:
        missing = [str(d) for d in designed_ids if str(d) and str(d) not in executed_ids]
        if missing:
            violations.append(
                "场景静默遗漏："
                + "、".join(missing)
                + "（设计集存在但执行集缺失，框架校验不通过）。"
                "修复处方（二选一，禁止只改一边）："
                "① 在 .fenix-run-result.json 的 verification.scenarios 中补齐上述"
                "缺失场景条目，scenario_id 必须与 test_scenarios.json 的 id 逐字一致"
                "（执行集允许是设计集超集，可附加单元测试类场景）；"
                "② 若裁决时确属应合并/改名场景，同步重写 test_scenarios.json 使"
                "设计集与执行集一致"
            )

    return {"ok": len(violations) == 0, "violations": violations}


def load_report(project_root, spec_name) -> Optional[dict]:
    """读取 .fenix/verify-progress/<spec>/report.json；不可用返回 None。"""
    path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_report(project_root, spec_name, report: dict) -> None:
    """原子写回增强后的 report.json（temp + rename，与既有产物写回同约定）。"""
    import tempfile

    path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".report.", suffix=".json.tmp")
    import os

    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.flush()
        os.replace(tmp_path, path)
    except (OSError, TypeError, ValueError):
        # json.dump 对不可序列化对象抛 TypeError/ValueError，同样须清理半成品
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── 跨轮裁决缓存（judge 效率治理 2026-09-06）──────────────────────────
# 裁决耗时 ≈ 输出 tokens 量（实测 12 个 judge run 恒定 ~1300-2200 tok/min）。
# 重验轮的失败场景与上轮高度重叠（冻结场景集未变 + 失败复现一致），按断言
# 指纹命中即可沿用上轮结论，judge 免复现——写侧在裁决采纳处（verification
# _persist_verdict_cache），读侧在 judge 派发前（prompt_builder 注入段）。

VERDICT_CACHE_FILENAME = "verdict_cache.json"


def _verdict_cache_path(project_root, spec_name) -> Path:
    return Path(project_root) / ".fenix" / "verify-progress" / spec_name / VERDICT_CACHE_FILENAME


def scenario_fingerprint(scenario: dict) -> str:
    """非 PASS 场景的断言指纹：scenario_id + status + 失败断言内容稳定 hash。

    取引擎侧 ``assertion_results`` 的失败条目（judge 增强前的原始执行产物，
    跨轮稳定），不取 evidence/assertion_triage（judge 产物，轮间会重写）。
    指纹一致 ⇒ 冻结场景与失败复现均未变，上轮结论可沿用。

    异常/缺字段返回空串（调用方按未命中处理，fail-open）。
    """
    import hashlib as _hashlib

    try:
        failed = [
            {
                k: a.get(k)
                for k in ("type", "layer", "expected", "actual", "selector")
                if a.get(k) is not None
            }
            for a in (scenario.get("assertion_results") or [])
            if isinstance(a, dict) and not a.get("pass", True)
        ]
        payload = json.dumps(
            {
                "sid": scenario.get("scenario_id"),
                "status": scenario.get("status"),
                "failed": failed,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return _hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    except (TypeError, ValueError, AttributeError):
        return ""


def load_verdict_cache(project_root, spec_name) -> dict:
    """读取跨轮裁决缓存；缺失/损坏返回 {}（fail-open）。"""
    p = _verdict_cache_path(project_root, spec_name)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_verdict_cache(project_root, spec_name, cache: dict) -> None:
    """原子写跨轮裁决缓存（每轮采纳后整体重写，消失/变化的场景自然出清）。

    写失败静默——缓存缺失只导致下轮全量重裁，不影响正确性。

    add-verify-lane-throughput 4.1：写入时自动注入顶层 ``_meta`` 特殊键
    （当前含 ``head_at_write`` = 写入时 git HEAD，修复轮 diff 失效判据的
    基准点）。``_meta`` 非场景条目，读侧消费方按 scenario_id 取条目不会
    误命中。
    """
    p = _verdict_cache_path(project_root, spec_name)
    payload = dict(cache) if isinstance(cache, dict) else {}
    if "_meta" not in payload:
        payload["_meta"] = {"head_at_write": compute_head_at_write(project_root)}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


# ── verdict 缓存键四元组（add-verify-lane-throughput 4.1，design 决策 6）──
# 采信判据 =（场景 id, 场景内容指纹, 被测构建指纹, 验证配置指纹）全等。
# 存疑即 fail-closed：任一分量缺失/不匹配 → 不采信缓存、照跑。


# 场景定义指纹的**白名单键**：只取定义性字段参与指纹。不采用「排除易变键」
# 的黑名单口径——写侧条目来自 report 场景 dict（键名 scenario_id、含执行
# 富集），读侧来自冻结文件 TestScenario.to_dict()（键名 id、归一形状），两侧
# 键集天然不同，黑名单无法归一；白名单（id 与 scenario_id 并收）保证同一
# 场景两侧投影一致。status/evidence/assertion_triage/classification/
# cached_source/attribution_level/assertion_results 等易变键天然不在白名单。
_SCENARIO_DEFINITION_KEYS = (
    "id",
    "scenario_id",
    "name",
    "description",
    "kind",
    "steps",
    "assertions",
    "depends_on",
    "visual_baseline",
    "external_net_errors_ok",
)

# 场景出处标注正则（description 末尾「文件:行号」形态，agents/planner-plan.md
# 出题规范）；文件扩展名覆盖被测应用常见源码/配置类型。
_SCENARIO_SOURCE_FILE_RE = re.compile(
    r"([\w./\\-]+\.(?:py|ts|tsx|js|jsx|mjs|vue|go|java|rb|php|sh|ya?ml|json|html|css|md)):(\d+)"
)

# 被测构建指纹的依赖/构建清单候选（取项目根现存文件集，不存在者跳过）。
_BUILD_MANIFEST_CANDIDATES = (
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
)

# 验证配置文件路径（验证配置指纹数据源）。
_VERIFY_CONFIG_RELATIVE_PATH = ".fenix/verify.yaml"


def scenario_definition_fingerprint(scenario: dict) -> str:
    """场景定义内容指纹（缓存键分量②）：定义白名单键投影后稳定 hash。

    与 :func:`scenario_fingerprint`（非 PASS 断言指纹，判定失败复现）互补：
    本指纹判定「场景定义本身是否变化」——定义变 ⇒ 上轮结论作废（失效条件①）。
    白名单口径保证写侧（report 场景 dict）与读侧（TestScenario.to_dict()）
    两侧投影一致；易变键（status/evidence/assertion_triage 等）不在白名单，
    天然不影响指纹。异常/空载荷返回空串（fail-closed，按不可采信处理）。
    """
    import hashlib as _hashlib

    try:
        payload = json.dumps(
            {k: scenario.get(k) for k in _SCENARIO_DEFINITION_KEYS},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return _hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    except (TypeError, ValueError, AttributeError):
        return ""


def _stable_file_hash(path: Path) -> str:
    """单文件内容 sha256；读取失败返回 ""（该文件视作缺席）。"""
    import hashlib as _hashlib

    try:
        return _hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def compute_build_fingerprint(project_root) -> str:
    """被测构建指纹（缓存键分量③）：依赖/构建清单文件集内容哈希。

    取项目根 ``_BUILD_MANIFEST_CANDIDATES`` 中现存文件的 (相对路径, 内容
    hash) 集合稳定哈希。**不取 git HEAD**：修复通常不改依赖清单，以文件集
    为准可避免无关提交击穿缓存；「修复 diff 触碰场景出处文件」的文件级失效
    由 4.2 消费侧以 head_at_write 基准另行判定，二者正交。

    项目根无任何清单 → 返回 ""（fail-closed：无法刻画被测构建则不采信）。
    """
    import hashlib as _hashlib

    root = Path(project_root)
    parts = []
    for name in _BUILD_MANIFEST_CANDIDATES:
        f = root / name
        if not f.is_file():
            continue
        h = _stable_file_hash(f)
        if h:
            parts.append(f"{name}:{h}")
    if not parts:
        return ""
    return _hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]


def compute_verify_config_fingerprint(project_root) -> str:
    """验证配置指纹（缓存键分量④）：``.fenix/verify.yaml`` 内容哈希。

    配置缺失/读取失败 → ""（fail-closed：无法确认验证配置未变则不采信）。
    """
    f = Path(project_root) / _VERIFY_CONFIG_RELATIVE_PATH
    return _stable_file_hash(f)


def compute_head_at_write(project_root) -> str:
    """当前 git HEAD（写侧 ``_meta.head_at_write``）；失败返回 ""（fail-open）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def extract_scenario_source_files(description) -> Set[str]:
    """从场景 description 提取出处关联文件集（失效条件②的交集判据数据源）。

    出处标注形态 = ``文件路径:行号``（planner-plan 出题规范）。提取失败/无
    标注 → 空集（消费侧空集 ⇒ 交集必空 ⇒ 该场景按「出处未关联」处理，
    是否采信由调用方 fail-closed 策略决定）。
    """
    if not isinstance(description, str):
        return set()
    files = set()
    for m in _SCENARIO_SOURCE_FILE_RE.finditer(description):
        f = m.group(1)
        while f.startswith("./"):
            f = f[2:]  # 仅剥 ./ 前缀（lstrip 会误伤 ../ 相对段）
        if f:
            files.add(f)
    return files


def verdict_cache_entry_valid(
    entry: Any,
    scenario: dict,
    build_fingerprint: str,
    verify_config_fingerprint: str,
) -> bool:
    """缓存条目四元组采信校验（add-verify-lane-throughput 4.1）。

    全部成立才可采信：
      - 条目为对象且含定义指纹；
      - 被测构建指纹/验证配置指纹非空且与条目记载一致；
      - 场景定义指纹与当前场景一致（定义未变）。

    任一不成立（含分量缺失）→ False（fail-closed：存疑即照跑）。
    """
    if not isinstance(entry, dict):
        return False
    if not build_fingerprint or not verify_config_fingerprint:
        return False
    if entry.get("build_fingerprint") != build_fingerprint:
        return False
    if entry.get("verify_config_fingerprint") != verify_config_fingerprint:
        return False
    if not scenario:
        return False
    dfp = scenario_definition_fingerprint(scenario)
    if not dfp or entry.get("definition_fingerprint") != dfp:
        return False
    return True
