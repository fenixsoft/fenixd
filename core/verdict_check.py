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

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

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
    if isinstance(shots, list) and any(
        isinstance(s, str) and s.strip() for s in shots
    ):
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
        failed_count = sum(
            1 for a in ars
            if isinstance(a, dict) and not a.get("pass", True)
        )
    if failed_count and len(triage) < failed_count:
        return (
            f"assertion_triage 仅 {len(triage)} 条，少于失败断言数 {failed_count}"
            f"（MUST 逐条归类全部失败断言）"
        )
    return None


def has_product_bug_assertion(scenario: dict) -> bool:
    """场景的失败断言中是否存在归类 product-bug 的条目（D3：阻止场景级豁免）。"""
    return any(
        t.get("classification") == "product-bug" for t in triage_entries(scenario)
    )


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
        return {"ok": False, "violations": [
            {"scenario_id": None, "status": None,
             "reason": "report.json 非对象"},
        ], "classified": []}

    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        # 无场景条目：视为无待校验对象，合规（不阻塞 verified 路径）
        return {"ok": True, "violations": [], "classified": []}

    violations: List[dict] = []
    classified: List[str] = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if not _is_non_pass(status):
            continue
        sid = sc.get("scenario_id") or sc.get("id") or "?"
        classification = sc.get("classification")
        evidence = sc.get("evidence")

        if classification not in VERDICT_CLASSES:
            violations.append({
                "scenario_id": sid,
                "status": status,
                "reason": "classification 缺失或取值非法",
            })
            continue
        if not _evidence_present(evidence):
            violations.append({
                "scenario_id": sid,
                "status": status,
                "reason": "evidence 为空",
            })
            continue
        # 逐断言归因（add-interaction-contract-and-per-assert-triage D3）：
        # 每个 scenario 至多一条 violation（保持「一场景一违规」语义，便于重试定位）
        triage_reason = triage_violation(sc)
        if triage_reason:
            violations.append({
                "scenario_id": sid,
                "status": status,
                "reason": triage_reason,
            })
            continue
        classified.append(sid)

    return {"ok": len(violations) == 0, "violations": violations,
            "classified": classified}


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
            corrected.append({
                "scenario_id": sc.get("scenario_id") or sc.get("id") or "?",
                "from_status": from_status,
                "to_status": "failed",
                "classification": offending,
            })
            continue
        if classification in FORCE_FAILED_CLASSES and status != "failed":
            from_status = status
            sc["status"] = "failed"
            sc["status_corrected"] = True  # 报告标注「已修正」
            corrected.append({
                "scenario_id": sc.get("scenario_id") or sc.get("id") or "?",
                "from_status": from_status,
                "to_status": "failed",
                "classification": classification,
            })
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
            rows.append({
                "scenario_id": sid,
                "assertion": str(t.get("assertion") or "-"),
                "classification": cls,
                "evidence": str(evidence or "-"),
                "reason": str(t.get("reason") or EXEMPTION_REASON.get(cls, "-")),
            })
    return rows


# ── fast-track 统一结果文件硬校验（add-fast-track-mode / D6）────────────
# 三要素：
#   ① 报告结构完整（场景/结果/判定字段齐全）
#   ② 场景全量执行（设计集与执行集一致，无静默遗漏；豁免走既有豁免规则）
#   ③ 逐场景证据存在性（非 PASS 场景带分类与证据）
# agent 文本宣称不作为通过依据——框架只信可校验的输出（与完整模式 verifier
# 的判定信任模型一致，design D6）。


def _scenario_evidence_ok(sc: dict) -> bool:
    """逐场景证据存在性：非 PASS 场景 MUST 带 classification 与 evidence。

    与 fast_track_result 的 SCENARIO_STATUSES 对齐：status ∈
    {pass, fail, error, warning, exempt}；非 PASS 集合 {fail, error, warning}
    复用本模块 NON_PASS_STATUSES 判定。exempt 场景单独走豁免合法性检查
    （_exempt_classification_ok），不在此要求 evidence（豁免＝不必提交证据）。
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


_FAST_TRACK_SCENARIO_STATUSES = ("pass", "fail", "error", "warning", "exempt")

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
        if not _scenario_evidence_ok(sc):
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
        missing = [
            str(d) for d in designed_ids
            if str(d) and str(d) not in executed_ids
        ]
        if missing:
            violations.append(
                "场景静默遗漏：" + "、".join(missing)
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
    path = (
        Path(project_root) / ".fenix" / "verify-progress"
        / spec_name / "report.json"
    )
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
    path = (
        Path(project_root) / ".fenix" / "verify-progress"
        / spec_name / "report.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=".report.", suffix=".json.tmp")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.flush()
        import os
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
