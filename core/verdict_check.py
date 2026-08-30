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

# 非 PASS 状态（这些场景 MUST 带 classification + evidence）
NON_PASS_STATUSES = ("fail", "failed", "error", "warning")

# classification → 强制状态映射（design D3）
# product-bug / test-defect MUST → failed；flaky / env 允许 warning（不强制）。
FORCE_FAILED_CLASSES = ("product-bug", "test-defect")


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
        classified.append(sid)

    return {"ok": len(violations) == 0, "violations": violations,
            "classified": classified}


def enforce_status_mapping(report: dict) -> dict:
    """按分类-状态映射表强制重写场景 status（design D3）。

    规则：
      - classification ∈ {product-bug, test-defect} 但 status != failed
        → 强制 status=failed，并标记该条目为「已修正」（供报告标注，
        防止 LLM 输出漂移悬置产品缺陷）。
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
