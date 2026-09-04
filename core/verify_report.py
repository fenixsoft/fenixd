"""verify_report.py — 验证报告产物闸门与共享合成器（add-verify-report-gate）。

保障 ``spec/changes/<spec>/verification-report.md`` 在验证裁决放行时
必然存在于磁盘：

  - 裁决 Agent 主动写入的报告优先——文件已存在时闸门直接放行，
    MUST NOT 覆盖或改写（含 mtime）。
  - 文件缺失时由框架从结构化数据（``.fenix/verify-progress/<spec>/report.json``
    与 ``.fenix-run-result.json``）确定性合成——纯本地渲染，零 LLM 成本，
    并发 human-escalation-alerts 告警使「Agent 未遵守 prompt 步骤 6」可见。
  - 结构化数据也不可用时 fail-closed：不写空报告、阻断状态推进。

合成格式与 ``core/dashboard/data.py`` 的 ``parse_verdict`` 兼容：
``## 结论：`` 标题行（内联 ✅/❌ 状态）、``**状态：...**`` 详情行、
``| 通过 | N |`` 形式的汇总表格、bug-found 时的「真实产品 Bug」章节。

单一实现（design D2）：闸门（pm_engine 裁决放行路径）是本模块的唯一新调用方，
下游（如修复任务注入）复用 ``synthesize_verification_report`` /
``ensure_verification_report``，禁止第二套渲染逻辑。
"""

import json
from datetime import datetime, timezone
from pathlib import Path

# 告警 signal_type（human-escalation-alerts 能力，.fenix/admin_alerts.json）
SIGNAL_MISSING = "verify_report_missing"

# 升级告警写入节流（分钟）：同 spec 同类信号冷却期内不重复落库，
# 防止多轮重验反复刷屏。与 admin.escalation_cooldown_minutes 同源。
_ALERT_COOLDOWN_MINUTES = 15


# ── 结构化数据读取 ────────────────────────────────────────────────

def _load_report_json(project_root, spec_name):
    """读取验证引擎 report.json；不可用返回 None（不抛出）。"""
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
    scenarios = data.get("scenarios")
    summary = data.get("summary")
    if not isinstance(scenarios, list) and not isinstance(summary, dict):
        return None
    return data


def _sum_verify_chain_tokens(project_root, spec_name):
    """从验证链 token 侧车求和本链（planner/judge）增量 token（add-cost-observability 2.2）。

    读取 ``.fenix/verify-progress/<spec>/tokens.json``，累加各 run 的 input/output。
    input 已含 cache_creation/cache_read（侧车写入时已计入）。文件缺失/不可解析返回 None。
    """
    if not project_root or not spec_name:
        return None
    path = (
        Path(project_root) / ".fenix" / "verify-progress"
        / spec_name / "tokens.json"
    )
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        return None
    total_in = 0
    total_out = 0
    for r in runs:
        if not isinstance(r, dict):
            continue
        try:
            total_in += int(r.get("input_tokens", 0) or 0)
        except (TypeError, ValueError):
            pass
        try:
            total_out += int(r.get("output_tokens", 0) or 0)
        except (TypeError, ValueError):
            pass
    return {"input": total_in, "output": total_out}


def _load_run_result(project_root, spec_name):
    """读取裁决 .fenix-run-result.json（verify-progress 优先，主树 .fenix/ 回退）。

    项目根为共享文件：携带的 spec 与当前 spec 不符时视为其它 spec 的残留忽略
    （与 pm_engine._read_planner_result 同语义）。
    """
    primary = (
        Path(project_root) / ".fenix" / "verify-progress"
        / spec_name / ".fenix-run-result.json"
    )
    fallback = Path(project_root) / ".fenix" / ".fenix-run-result.json"
    for path, stamped_expected in ((primary, False), (fallback, True)):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if stamped_expected:
            stamped = data.get("spec")
            if isinstance(stamped, str) and stamped and stamped != spec_name:
                continue
        if data.get("status") or data.get("bugs"):
            return data
    return None


# ── 渲染 ─────────────────────────────────────────────────────────

def _derive_status(run_result, report) -> str:
    """从结构化数据推导终局判定：'verified' 或 'bug-found'。"""
    if run_result:
        status = run_result.get("status")
        if status in ("verified", "bug-found"):
            return status
    if isinstance(report, dict):
        summary = report.get("summary") or {}
        try:
            if (int(summary.get("failed", 0) or 0)
                    + int(summary.get("errors", 0) or 0)) > 0:
                return "bug-found"
        except (TypeError, ValueError):
            pass
    return "verified"


def _summary_counts(report):
    """提取 (passed, failed, errors, total)，不可得字段为 None。"""
    summary = (report or {}).get("summary") or {}

    def _num(key):
        try:
            return int(summary.get(key, 0) or 0)
        except (TypeError, ValueError):
            return None

    return _num("passed"), _num("failed"), _num("errors"), _num("total")


def _failed_assertion_count(scenario) -> str:
    """场景失败断言数「x/y」，无断言数据返回 '-'。"""
    ars = scenario.get("assertion_results")
    if not isinstance(ars, list) or not ars:
        return "-"
    failed = sum(
        1 for a in ars
        if isinstance(a, dict) and not a.get("pass", True)
    )
    return f"{failed}/{len(ars)}"


def _render_evidence(evidence) -> list:
    """把 bug 证据渲染为 Markdown 行（dict/list/str 尽力展开）。"""
    lines = []
    if isinstance(evidence, dict):
        for key, val in evidence.items():
            if isinstance(val, (dict, list)):
                rendered = json.dumps(val, ensure_ascii=False)
            else:
                rendered = str(val)
            lines.append(f"  - {key}: {rendered}")
    elif isinstance(evidence, list):
        for item in evidence:
            rendered = (
                json.dumps(item, ensure_ascii=False)
                if isinstance(item, (dict, list)) else str(item)
            )
            lines.append(f"  - {rendered}")
    elif evidence is not None:
        lines.append(f"  - {evidence}")
    return lines


def _render_bugs_section(bugs, scenario_evidence=None) -> list:
    """「真实产品 Bug」章节：description / root_cause / evidence 逐条渲染。

    scenario_evidence: {scenario_id: evidence_dict}（来自 report.json 增强后的
    结构化证据，add-verdict-evidence-taxonomy）；命中时优先引用该证据，
    不重复渲染 judge 运行结果的稀疏证据（spec Scenario: 「引用该证据而非重复渲染」）。
    """
    scenario_evidence = scenario_evidence or {}
    lines = ["", "## 真实产品 Bug", ""]
    for i, bug in enumerate(bugs, 1):
        if not isinstance(bug, dict):
            continue
        severity = bug.get("severity") or "unspecified"
        assertion = bug.get("assertion_type") or "-"
        lines.append(f"### BUG-{i:02d}（severity={severity}）· {assertion}")
        lines.append("")
        scenario_ids = bug.get("scenario_ids")
        if isinstance(scenario_ids, list) and scenario_ids:
            lines.append("- 关联场景：" + "、".join(str(s) for s in scenario_ids))
        description = bug.get("description")
        if description:
            lines.append(f"- 描述：{description}")
        root_cause = bug.get("root_cause")
        if root_cause:
            lines.append(f"- 根因：{root_cause}")
        # 优先引用 report.json 的场景结构化证据（引用而非重复渲染）
        referenced = False
        for sid in scenario_ids or []:
            ev = scenario_evidence.get(sid)
            if isinstance(ev, dict):
                lines.append(f"- 证据（场景 {sid} 结构化证据，引用）：")
                lines.extend(_render_evidence(ev))
                referenced = True
                break
        if not referenced:
            ev_lines = _render_evidence(bug.get("evidence"))
            if ev_lines:
                lines.append("- 证据：")
                lines.extend(ev_lines)
        lines.append("")
    return lines


def _render_assertion_exempt_section(report) -> list:
    """「断言级豁免清单」小节（add-interaction-contract-and-per-assert-triage 2.3）。

    从 report.json 的 assertion_triage 汇总：逐条列出被豁免的失败断言（场景、
    断言内容、归类、证据、豁免理由），供人工快速复核豁免是否吞掉了真实缺陷。
    历史报告无 assertion_triage 字段时小节缺省（design D4，向后兼容）。
    """
    from core.verdict_check import exempted_assertions, triage_entries
    if not isinstance(report, dict):
        return []
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return []
    # 旧报告：全部场景均无 assertion_triage → 小节缺省（不渲染空壳）
    if not any(triage_entries(sc) for sc in scenarios
               if isinstance(sc, dict)):
        return []

    rows = exempted_assertions(report)
    lines = ["", "## 断言级豁免清单", ""]
    lines.append(
        "以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核"
        "豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。"
    )
    lines.append("")
    if not rows:
        lines.append("无非 product-bug 的被豁免失败断言。")
        lines.append("")
        return lines
    lines.append("| 场景 | 断言 | 归类 | 豁免理由 | 证据 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in rows:
        assertion = r["assertion"].replace("|", "\\|")
        evidence = r["evidence"].replace("|", "\\|")
        if len(evidence) > 160:
            evidence = evidence[:157] + "..."
        reason = r["reason"].replace("|", "\\|")
        lines.append(
            f"| {r['scenario_id']} | {assertion} | {r['classification']} "
            f"| {reason} | {evidence} |"
        )
    lines.append("")
    return lines


def _render_scenarios_table(report) -> list:
    scenarios = (report or {}).get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return []
    lines = ["", "## 场景结果", ""]
    lines.append("| 场景 | 状态 | 失败断言 | 分类 |")
    lines.append("| --- | --- | --- | --- |")
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "-")
        status = str(sc.get("status") or "-")
        # 采纳处强制重写的场景标注「已修正」(add-verdict-evidence-taxonomy D3)
        if sc.get("status_corrected"):
            status += "（已修正）"
        classification = str(sc.get("classification") or "-")
        lines.append(
            f"| {sid} | {status} | {_failed_assertion_count(sc)} | {classification} |"
        )
    lines.append("")
    return lines


def render_verification_report(spec_name, run_result, report, now=None,
                              project_root=None) -> str:
    """把结构化数据渲染为人读报告 Markdown。

    纯函数：不做 IO、不写文件，便于测试与下游复用。project_root 用于读取验证链
    token 侧车（add-cost-observability 2.2），缺失时跳过「本链增量 token」行。
    """
    status = _derive_status(run_result, report)
    passed, failed, errors, total = _summary_counts(report)
    bugs = []
    if run_result:
        raw_bugs = run_result.get("bugs")
        if isinstance(raw_bugs, list):
            bugs = [b for b in raw_bugs if isinstance(b, dict)]

    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"# 验证报告：{spec_name}", ""]
    lines.append(
        f"> ⚠️ 本报告由框架于 {ts} 自动合成"
        f"（裁决 Agent 未写报告，已由框架合成），"
        f"内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。"
    )
    lines.append("")

    # ── 结论标题（内联状态，parse_verdict 的 status 来源）──
    if status == "bug-found":
        head = "❌ 未通过（Bug Found）"
        count_note = f"{len(bugs)} 个真实产品 Bug"
    else:
        head = "✅ 通过（verified）"
        count_note = "全部场景通过"
    lines.append(f"## 结论：{head}")
    lines.append("")

    # ── 状态详情行（parse_verdict 的 status_detail 来源）──
    detail_parts = []
    if passed is not None and total is not None:
        detail_parts.append(f"{passed}/{total} 场景通过")
    if failed is not None:
        detail_parts.append(f"{failed} 失败")
    if errors is not None:
        detail_parts.append(f"{errors} 错误")
    detail = status + (
        " — " + "，".join(detail_parts) if detail_parts else ""
    ) + f"（{count_note}）"
    lines.append(f"**状态：{detail}**")
    lines.append("")

    # ── 结论正文（parse_verdict 的 conclusion 来源）──
    judge_summary = (run_result or {}).get("summary")
    if isinstance(judge_summary, str) and judge_summary.strip():
        lines.append(judge_summary.strip())
        lines.append("")

    # ── 汇总表格（parse_verdict 的 summary 来源）──
    lines.append("| 指标 | 数量 |")
    lines.append("| --- | --- |")
    # add-cost-observability（2.2）：本链增量 token 行（从 verify-progress 侧车求和）
    chain_tokens = _sum_verify_chain_tokens(project_root, spec_name)
    for label, val in (
        ("通过", passed if passed is not None else "N/A"),
        ("失败", failed if failed is not None else "N/A"),
        ("错误", errors if errors is not None else "N/A"),
        ("产品 Bug", len(bugs)),
        ("本链增量 Token（输入）", f"{chain_tokens['input'] / 1_000_000:.2f}M" if chain_tokens else "N/A"),
        ("本链增量 Token（输出）", f"{chain_tokens['output'] / 1_000_000:.2f}M" if chain_tokens else "N/A"),
    ):
        lines.append(f"| {label} | {val} |")
    lines.append("")

    # ── 真实产品 Bug（bug-found 时必备章节）──
    if status == "bug-found":
        if bugs:
            # 从 report.json 摘取每个场景的结构化证据，供 bug 章节引用（不重复渲染）
            scenario_evidence = {}
            for sc in (report or {}).get("scenarios", []) or []:
                if not isinstance(sc, dict):
                    continue
                sid = str(sc.get("scenario_id") or sc.get("id") or "")
                ev = sc.get("evidence")
                if sid and isinstance(ev, dict):
                    scenario_evidence[sid] = ev
            lines.extend(_render_bugs_section(bugs, scenario_evidence))
        else:
            lines.append("## 真实产品 Bug")
            lines.append("")
            lines.append(
                "> 判定为 bug-found 但结果文件未携带结构化 bug 列表，"
                "以下为 report.json 中的失败场景明细。"
            )
            lines.append("")

    # ── 场景明细 ──
    lines.extend(_render_scenarios_table(report))

    # ── 断言级豁免清单（add-interaction-contract-and-per-assert-triage 2.3）──
    lines.extend(_render_assertion_exempt_section(report))
    return "\n".join(lines).rstrip() + "\n"


# ── 合成与闸门 ────────────────────────────────────────────────────

def synthesize_verification_report(project_root, spec_name, now=None) -> dict:
    """从结构化数据合成 verification-report.md 并写入磁盘。

    返回 {"ok": True, "path": <str>}；结构化数据缺失/不可解析时返回
    {"ok": False, "error": <文案>}，且不写任何文件（不产出空报告）。
    """
    report = _load_report_json(project_root, spec_name)
    run_result = _load_run_result(project_root, spec_name)
    if report is None and run_result is None:
        return {
            "ok": False,
            "error": (
                f"验证报告缺失且无法合成：'{spec_name}' 的 report.json 与 "
                f".fenix-run-result.json 均缺失或不可解析"
            ),
        }

    content = render_verification_report(spec_name, run_result, report, now=now, project_root=project_root)
    out_path = (
        Path(project_root) / "spec" / "changes"
        / spec_name / "verification-report.md"
    )
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"验证报告写入失败: {e}"}
    return {"ok": True, "path": str(out_path)}


def _append_alert(project_root, spec_name, signal_type, severity,
                  description, evidence, logger=None) -> None:
    """落一条 human-escalation-alerts 告警（节流：同 spec 同类信号冷却期内不重复）。"""
    try:
        from .admin_store import AdminStore, ESCALATION
        store = AdminStore(project_root, logger)
        if store.latest_signal(spec_name, signal_type,
                               _ALERT_COOLDOWN_MINUTES) is not None:
            return
        store.append({
            "kind": ESCALATION,
            "signal_type": signal_type,
            "spec": spec_name,
            "severity": severity,
            "description": description,
            "evidence": evidence,
            "recommended_action": (
                "留意验证裁决 Agent 未遵守 prompt 步骤 6（写 verification-report.md）"
                "的劣化信号；合成报告内容以结构化 JSON 为准，无叙述性分析"
            ),
        })
    except Exception as e:  # 告警失败不阻断主流程（闸门结论已定）
        if logger is not None:
            logger.warning(
                "verify_report",
                f"验证报告闸门告警写入失败 '{spec_name}': {e}",
            )


def ensure_verification_report(project_root, spec_name, logger=None) -> dict:
    """验证报告产物闸门：裁决放行前调用。

    返回 {"ok": True, "action": "present"|"synthesized"} 表示放行；
    返回 {"ok": False, "error": <文案>} 表示 MUST 阻止状态推进（fail-closed）。
    """
    out_path = (
        Path(project_root) / "spec" / "changes"
        / spec_name / "verification-report.md"
    )
    if out_path.exists():
        # Agent 已写报告：原样保留，不覆盖、不改 mtime
        return {"ok": True, "action": "present"}

    result = synthesize_verification_report(project_root, spec_name)
    if result.get("ok"):
        # 2026-08-29 用户决策：合成兜底静默化——只记框架日志，不发人工升级告警
        if logger is not None:
            logger.warning(
                "verify_report",
                f"验证报告闸门：'{spec_name}' 报告缺失，已由框架合成",
            )
        return {"ok": True, "action": "synthesized"}

    error = result.get("error") or "验证报告缺失且无法合成"
    _append_alert(
        project_root, spec_name, SIGNAL_MISSING, "major",
        f"'{spec_name}' 验证报告缺失且无法合成——验证裁决放行被阻断，等待人工裁决",
        error,
        logger=logger,
    )
    if logger is not None:
        logger.error("verify_report", f"验证报告闸门阻断 '{spec_name}': {error}")
    return {"ok": False, "error": error}
