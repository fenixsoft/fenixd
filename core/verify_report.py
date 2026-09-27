"""verify_report.py — 验证报告产物闸门与共享合成器（add-verify-report-gate）。

保障 ``spec/changes/<spec>/verification-report.md`` 在验证裁决放行时
必然存在于磁盘：

  - 裁决 Agent 主动写入的报告优先——文件已存在且**与本轮裁决一致**时闸门直接
    放行，MUST NOT 覆盖或改写（含 mtime）。
  - 文件缺失时由框架从结构化数据（``.fenix/verify-progress/<spec>/report.json``
    与 ``.fenix-run-result.json``）确定性合成——纯本地渲染，零 LLM 成本。
    （judge 效率治理 2026-09-06：judge prompt 已删「写 md」步骤，合成由此
    转正为常规路径；裁决 Agent 主动写入仍优先兼容。）
  - 文件存在但属**上一轮残留**时重新合成覆盖——报告是「每轮裁决产物」，
    陈旧报告会让仪表盘与下游修复引用读到已失效的结论（见
    ``_report_is_superseded``）。
  - 结构化数据也不可用时 fail-closed：不写空报告、阻断状态推进，
    并发 human-escalation-alerts 告警（此时才代表真异常）。

合成格式与 ``core/dashboard/data.py`` 的 ``parse_verdict`` 兼容：
``## 结论：`` 标题行（内联 ✅/❌ 状态）、``**状态：...**`` 详情行、
``| 通过 | N |`` 形式的汇总表格、bug-found 时的「真实产品 Bug」章节。

单一实现（design D2）：闸门（pm_engine 裁决放行路径）是本模块的唯一新调用方，
下游（如修复任务注入）复用 ``synthesize_verification_report`` /
``ensure_verification_report``，禁止第二套渲染逻辑。
"""

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# 告警 signal_type（human-escalation-alerts 能力，.fenix/admin_alerts.json）
SIGNAL_MISSING = "verify_report_missing"

# 升级告警写入节流（分钟）：同 spec 同类信号冷却期内不重复落库，
# 防止多轮重验反复刷屏。独立固定值，不读取配置——与
# admin.escalation_cooldown_minutes（缺省 60 分钟）无关，两者数值也不同。
_ALERT_COOLDOWN_MINUTES = 15

# 合成报告携带的「合成源轮次指纹」标记：报告属哪一轮裁决的机器可读留痕。
# 人读行内标记，取值为无空格无标点的 token（见 current_round_fingerprint）。
_FINGERPRINT_MARKER = "合成源轮次指纹："
_FINGERPRINT_RE = re.compile(re.escape(_FINGERPRINT_MARKER) + r"([^\s，。）|]+)")

# 存量报告无指纹时的兜底判据：解析 md 声明的结论行与汇总计数（与
# dashboard.data.parse_verdict 同款语法，两处必须同源演进）。
_MD_CONCLUSION_RE = re.compile(r"^#{2,4}\s*(?:判定)?结论\s*(?:摘要)?\s*[：:]?\s*(.*)$", re.M)
_MD_COUNT_RE = re.compile(r"^\|\s*(通过|失败|错误)\s*\|\s*([^|]+?)\s*\|", re.M)

# 报告入库 git 子进程超时（秒）：照 core/archive_commit.py 惯例，探测最快、
# add 居中、commit 最慢（锁冲突等待窗口更长）。
_REPORT_PROBE_TIMEOUT = 30
_REPORT_ADD_TIMEOUT = 60
_REPORT_COMMIT_TIMEOUT = 120


def _atomic_write(path: Path, content: str) -> None:
    """mkstemp 唯一临时文件 + fsync + os.replace 原子写（code_review._atomic_write 同款）。

    固定 ``<name>.tmp`` 临时名在并发写同一目标时会互相截断：进程 A 完成 write_text
    后、进程 B 在同一 .tmp 上截断改写，随后任一方的 replace 都可能把截断内容落盘。
    唯一临时名保证并发写不可能产生截断产物——rename 前目标不变，rename 后内容完整。
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ── 结构化数据读取 ────────────────────────────────────────────────


def _load_report_json(project_root, spec_name):
    """读取验证引擎 report.json；不可用返回 None（不抛出）。"""
    path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
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
    path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "tokens.json"
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

    项目根为共享文件：仅采信 spec 戳**显式等于**当前 spec 的内容；无戳/缺戳
    视为不可归属（可能为其它 spec 残留或异常写入）一律忽略。
    """
    primary = (
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / ".fenix-run-result.json"
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
            # 无 spec 戳的共享文件不可归属本 spec（异常写入/其它 spec 残留），
            # 只有显式戳匹配才采信
            stamped = data.get("spec")
            if not (isinstance(stamped, str) and stamped == spec_name):
                continue
        if data.get("status") or data.get("bugs"):
            return data
    return None


def _load_degrade_context(project_root, spec_name):
    """读取降级上下文 .fenix/verify-progress/<spec>/degrade_context.json。

    add-planready-artifact-gate D3：pm_engine 阶段1 降级判定点落盘（reason/
    run_id/duration_seconds/cost_usd/degraded_at）；合成报告路径读取后注入
    降级标注（G3）。文件缺失/损坏 → 返回 None（零注入零渲染，正常报告不含
    该字段）。
    """
    path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "degrade_context.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("reason") and not data.get("run_id"):
        return None
    return data


def _persist_degrade_annotation(project_root, spec_name, annotation) -> None:
    """把降级标注注入 report.json 顶层并落盘（持久化，D3/D4）。

    降级合成报告必须随 report.json 持久化（非仅日志），后续读取报告（时间轴/
    报告页/CLI）能还原降级事实与代价。写入失败静默跳过（annotation 是纯观测量，
    不得阻断报告合成主流程）。
    """
    report_path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    try:
        data = {}
        if report_path.is_file():
            try:
                loaded = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                data = loaded
        data["degrade_annotation"] = annotation
        report_path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp 唯一临时文件原子写（_atomic_write）：进程中途崩溃不会留下
        # 截断的 report.json；固定 .tmp 名并发写会互相截断后 replace
        _atomic_write(report_path, json.dumps(data, ensure_ascii=False, indent=2))
    except (OSError, TypeError, ValueError):
        pass


# ── 渲染 ─────────────────────────────────────────────────────────


def _derive_status(run_result, report) -> str:
    """从结构化数据推导终局判定：'verified' 或 'bug-found'。"""
    if run_result:
        status = run_result.get("status")
        if status in ("verified", "bug-found"):
            return status
    if isinstance(report, dict):
        summary = report.get("summary")
        if isinstance(summary, dict):
            try:
                if (int(summary.get("failed", 0) or 0) + int(summary.get("errors", 0) or 0)) > 0:
                    return "bug-found"
            except (TypeError, ValueError):
                pass
            else:
                # 显式声明过 failed/errors 键且值非 0 已被上分支拦截 → 判定有据
                if "failed" in summary or "errors" in summary:
                    return "verified"
        # summary 缺失/非 dict/不可解析/未声明失败键时退化为按场景计数兜底：
        # 存在非 pass/passed 场景即 bug-found（与 _resolve_scenarios 的场景级
        # 数据源回退同向）
        for sc in _resolve_scenarios(report, run_result) or []:
            if isinstance(sc, dict) and str(sc.get("status") or "") not in ("pass", "passed"):
                return "bug-found"
    return "verified"


def _summary_counts(report):
    """提取 (passed, failed, errors, total)；缺键/空值/不可转换的字段为 None。"""
    summary = (report or {}).get("summary") or {}

    def _num(key):
        val = summary.get(key)
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    return _num("passed"), _num("failed"), _num("errors"), _num("total")


# ── 报告时效（陈旧报告识别）────────────────────────────────────────


def current_round_fingerprint(project_root, spec_name):
    """当前轮结构化数据的指纹（轮次身份）。无结构化数据时返回 None。

    report.json 的 ``timestamp`` 由验证引擎每轮重写，是轮次身份的第一来源；
    字段缺失时退化为文件 mtime（同样每轮重写即变化）。两路皆不可得返回 None
    ——此时无从判定新旧，闸门维持「既有报告不改动」的保守行为。
    """
    report_path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    run_result_path = (
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / ".fenix-run-result.json"
    )
    report = _load_report_json(project_root, spec_name)
    if isinstance(report, dict):
        ts = report.get("timestamp")
        if isinstance(ts, str) and ts.strip():
            return f"report.json@{ts.strip()}"
        try:
            return f"report.json@mtime{report_path.stat().st_mtime_ns}"
        except OSError:
            pass
    try:
        if run_result_path.is_file():
            return f"run-result@mtime{run_result_path.stat().st_mtime_ns}"
    except OSError:
        pass
    return None


def _report_fingerprint(content):
    """既有报告记录的合成源轮次指纹；Agent 手写/存量报告无标记时返回 None。"""
    m = _FINGERPRINT_RE.search(content or "")
    return m.group(1) if m else None


def _md_declared_verdict(content):
    """解析 md 自己声明的 (verdict, failed, errors)；解析不出为 None。

    与 ``core/dashboard/data.py`` 的 ``parse_verdict`` 同款语法：结论标题行
    「## 结论：…」+ 汇总表格行「| 失败 | N |」。Agent 自由叙述（无结论标题、
    无汇总表）→ 全部为 None，视作「不可判定」而非「矛盾」。
    """
    verdict = None
    m = _MD_CONCLUSION_RE.search(content or "")
    if m:
        head = m.group(1)
        # 顺序敏感：「未通过」含「通过」子串，必须先判不通
        if "未通过" in head or "❌" in head or "bug-found" in head:
            verdict = "bug-found"
        elif "通过" in head or "✅" in head or "verified" in head:
            verdict = "verified"
    counts = {}
    for label, raw in _MD_COUNT_RE.findall(content or ""):
        try:
            counts[label] = int(raw)
        except (TypeError, ValueError):
            continue
    return verdict, counts.get("失败"), counts.get("错误")


def _report_is_superseded(project_root, spec_name, content) -> bool:
    """既有报告是否为上一轮残留（须重新合成）。

    事故背景（2026-09-12 add-framework-self-evolution）：第 1 轮 bug-found 时
    闸门合成 ❌ 报告；打回后第 2 轮走「全绿快道」（跳过 judge、不产 md），闸门
    见文件已存在即放行 → spec 已 pushed 而报告仍是上一轮的 ❌。

    判据一（精确，框架合成报告）：报告携带的合成源轮次指纹 ≠ 当前轮指纹。
    判据二（兜底，存量 md 无指纹）：md 声明的裁决结论与当前结构化数据矛盾
    （状态不一致，或失败/错误计数不一致）。

    Agent 手写叙述、无结论行、或结论与本轮一致的报告一律维持原样——「Agent
    报告优先、不覆盖」的原策略不回归。
    """
    current = current_round_fingerprint(project_root, spec_name)
    declared_fp = _report_fingerprint(content)
    if current and declared_fp:
        return declared_fp != current

    run_result = _load_run_result(project_root, spec_name)
    report = _load_report_json(project_root, spec_name)
    if run_result is None and report is None:
        # 无结构化数据可比对：无法判残留，既有报告按 present 放行（有报告总
        # 比 fail-closed 阻断好；判 True 走重新合成也无数据可用、只会阻断）
        return False
    declared_verdict, declared_failed, declared_errors = _md_declared_verdict(content)
    if declared_verdict is None and declared_failed is None and declared_errors is None:
        return False  # 解析不出结论（Agent 自由叙述）→ 不判矛盾
    if declared_verdict is not None and declared_verdict != _derive_status(run_result, report):
        return True
    _passed, failed, errors, _total = _summary_counts(report)
    if declared_failed is not None and failed is not None and declared_failed != failed:
        return True
    if declared_errors is not None and errors is not None and declared_errors != errors:
        return True
    return False


def _failed_assertion_count(scenario) -> str:
    """场景失败断言数「x/y」，无断言数据返回 '-'。"""
    ars = scenario.get("assertion_results")
    if not isinstance(ars, list) or not ars:
        return "-"
    failed = sum(1 for a in ars if isinstance(a, dict) and not a.get("pass", True))
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
                if isinstance(item, (dict, list))
                else str(item)
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
        for sid in scenario_ids if isinstance(scenario_ids, list) else []:
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


def _md_cell(v, max_len=None) -> str:
    """Markdown 表格单元格统一转义口径：竖线与换行转义（可选超长截断）。

    场景结果表与断言级豁免清单共用：status/classification 等列源自裁决
    自由文本，含竖线时会撑破 Markdown 表格列，故所有插值列同口径转义；
    换行（\\r\\n/\\r/\\n）折叠为空格，保证单元格永不跨行。
    max_len 仅承载豁免清单证据列的既有截断行为（>160 截为 157+"..."），
    其余列不引入新截断。
    """
    text = (
        str(v)
        .replace("\r\n", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("|", "\\|")
    )
    if max_len is not None and len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


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
    if not any(triage_entries(sc) for sc in scenarios if isinstance(sc, dict)):
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
        assertion = _md_cell(r["assertion"])
        evidence = _md_cell(r["evidence"], max_len=160)
        reason = _md_cell(r["reason"])
        scenario_id = _md_cell(r["scenario_id"])
        classification = _md_cell(r["classification"])
        lines.append(
            f"| {scenario_id} | {assertion} | {classification} "
            f"| {reason} | {evidence} |"
        )
    lines.append("")
    return lines


def _render_scenarios_table(report) -> list:
    scenarios = (report or {}).get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return []
    lines = ["", "## 场景结果", ""]
    lines.append("| 场景 | 描述 | 状态 | 失败断言 | 分类 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = _md_cell(sc.get("scenario_id") or sc.get("id") or "-")
        desc = _md_cell(sc.get("description") or "-")
        status = _md_cell(sc.get("status") or "-")
        # 采纳处强制重写的场景标注「已修正」(add-verdict-evidence-taxonomy D3)
        if sc.get("status_corrected"):
            status += "（已修正）"
        classification = _md_cell(sc.get("classification") or "-")
        lines.append(
            f"| {sid} | {desc} | {status} | {_failed_assertion_count(sc)} | {classification} |"
        )
    lines.append("")
    return lines


def render_verification_report(
    spec_name,
    run_result,
    report,
    now=None,
    project_root=None,
    degrade_annotation=None,
    source_fingerprint=None,
) -> str:
    """把结构化数据渲染为人读报告 Markdown。

    纯函数：不做 IO、不写文件，便于测试与下游复用。project_root 用于读取验证链
    token 侧车（add-cost-observability 2.2），缺失时跳过「本链增量 token」行。

    add-planready-artifact-gate D4：degrade_annotation 为可选降级标注 dict
    （reason/run_id/duration_seconds/cost_usd/degraded_at，源自 degrade_context.json），
    存在时在报告头部追加「⚠️ 降级说明」引用块；缺省 None 时零渲染（正常报告
    不含该标注，与无降级时逐字节一致）。

    source_fingerprint：本轮结构化数据的轮次指纹（``current_round_fingerprint``），
    非空时写入头部「合成源轮次指纹：」标记，供闸门判定报告是否属上一轮。
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
    if isinstance(source_fingerprint, str) and source_fingerprint.strip():
        lines.append(
            f"> 报告时效标记（判定本报告是否属上一轮）："
            f"{_FINGERPRINT_MARKER}{source_fingerprint.strip()}"
        )
    lines.append("")

    # ── 降级说明引用块（add-planready-artifact-gate D4，G3 留痕）──
    # 新验证流程 planner 阶段失败降级 legacy verifier 时，合成报告须标注降级
    # 原因与被降级轮次代价（不再静默合成）。
    if isinstance(degrade_annotation, dict):
        reason = str(degrade_annotation.get("reason") or "未知原因")
        run_id = str(degrade_annotation.get("run_id") or "未知 run")
        duration_s = degrade_annotation.get("duration_seconds")
        cost_usd = degrade_annotation.get("cost_usd")
        if isinstance(duration_s, (int, float)):
            minutes = f"{float(duration_s) / 60:.1f}min"
        else:
            minutes = "时长未知"
        cost_part = ""
        if cost_usd is not None:
            try:
                cost_part = f"/${float(cost_usd):.2f}"
            except (TypeError, ValueError):
                cost_part = ""
        lines.append(
            f"> ⚠️ 降级说明：本报告由框架合成（新验证流程 planner 阶段失败："
            f"{reason}；被降级轮次 {run_id} 烧 {minutes}{cost_part}）"
        )
        lines.append("")

    # ── 结论标题（内联状态，parse_verdict 的 status 来源）──
    if status == "bug-found":
        head = "❌ 未通过（Bug Found）"
        count_note = f"{len(bugs)} 个真实产品 Bug"
    else:
        head = "✅ 通过（verified）"
        # count_note 须与状态详情行（detail_parts）一致：豁免失败（flaky/test-defect
        # 豁免场景合法保留失败计数而终局 verified）时再写「全部场景通过」会自相矛盾
        if (failed or 0) + (errors or 0) > 0:
            count_note = "其余失败场景已豁免（见分类列）"
        else:
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
    detail = (
        status + (" — " + "，".join(detail_parts) if detail_parts else "") + f"（{count_note}）"
    )
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
        (
            "本链增量 Token（输入）",
            f"{chain_tokens['input'] / 1_000_000:.2f}M" if chain_tokens else "N/A",
        ),
        (
            "本链增量 Token（输出）",
            f"{chain_tokens['output'] / 1_000_000:.2f}M" if chain_tokens else "N/A",
        ),
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


def _resolve_scenarios(report, run_result):
    """解析场景明细数据源（fix-verify-report-fasttrack-scenarios）。

    优先级：
      1. report.json 顶层 `scenarios` 非空列表 → 使用之（full 模式 tester 路径不变）
      2. 顶层缺失/为空/非法 → 回退 `.fenix-run-result.json` 的
         `verification.scenarios`（fast-track schema，`core/fast_track_result.py`）
      3. 两者皆不可得 → 返回 None（场景表留空，不阻断合成）

    数据读取在入口合成层完成、归一为场景列表返回；渲染层仍收纯参数（`.get` 链
    已按缺省容错，scene 无 classification/assertion_results 等字段时原样显示）。
    """
    report_scenarios = (report or {}).get("scenarios")
    if isinstance(report_scenarios, list) and report_scenarios:
        return report_scenarios
    verification = run_result.get("verification") if isinstance(run_result, dict) else None
    if isinstance(verification, dict):
        fast_scenarios = verification.get("scenarios")
        if isinstance(fast_scenarios, list) and fast_scenarios:
            return fast_scenarios
    return None


def synthesize_verification_report(project_root, spec_name, now=None) -> dict:
    """从结构化数据合成 verification-report.md 并写入磁盘。

    返回 {"ok": True, "path": <str>}；结构化数据缺失/不可解析时返回
    {"ok": False, "error": <文案>}，且不写任何文件（不产出空报告）。

    add-planready-artifact-gate D3：合成路径读取 degrade_context.json，存在时
    degrade_annotation 注入渲染 **并持久化到 report.json 顶层**（后续读取报告
    ——时间轴/报告页/CLI——能还原降级事实与代价，G3）。无 degrade_context.json
    时零注入零渲染（正常报告不含该字段）。
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

    # fast-track 场景数据源回退：report.json 顶层 scenarios 缺失/为空/非法时，
    # 归一 .fenix-run-result.json 的 verification.scenarios 注入 report 后传入
    # 渲染层（渲染函数保持纯函数无 IO、签名不变）。
    resolved_scenarios = _resolve_scenarios(report, run_result)
    if resolved_scenarios is not None:
        report = dict(report or {})
        report["scenarios"] = resolved_scenarios

    degrade_annotation = _load_degrade_context(project_root, spec_name)
    if degrade_annotation is not None:
        # 持久化到 report.json 顶层（design D3：随报告结构持久化，非仅日志）
        _persist_degrade_annotation(project_root, spec_name, degrade_annotation)
        if report is not None:
            report = dict(report)
        else:
            report = {}
        report["degrade_annotation"] = degrade_annotation

    content = render_verification_report(
        spec_name,
        run_result,
        report,
        now=now,
        project_root=project_root,
        degrade_annotation=degrade_annotation,
        source_fingerprint=current_round_fingerprint(project_root, spec_name),
    )
    out_path = Path(project_root) / "spec" / "changes" / spec_name / "verification-report.md"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp 唯一临时文件原子写（_atomic_write）：进程中途崩溃不会留下截断
        # 的 md；固定 .tmp 名并发合成会互相截断——截断残留的指纹仍等于本轮
        # 指纹，会被闸门以 present 放行，违背「放行时报告必然完整在盘」的本职
        _atomic_write(out_path, content)
    except OSError as e:
        return {"ok": False, "error": f"验证报告写入失败: {e}"}
    return {"ok": True, "path": str(out_path)}


def _append_alert(
    project_root, spec_name, signal_type, severity, description, evidence, logger=None
) -> None:
    """落一条 human-escalation-alerts 告警（节流：同 spec 同类信号冷却期内不重复）。"""
    try:
        from .admin_store import AdminStore, ESCALATION

        store = AdminStore(project_root, logger)
        if store.latest_signal(spec_name, signal_type, _ALERT_COOLDOWN_MINUTES) is not None:
            return
        store.append(
            {
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
            }
        )
    except Exception as e:  # 告警失败不阻断主流程（闸门结论已定）
        if logger is not None:
            logger.warning(
                "verify_report",
                f"验证报告闸门告警写入失败 '{spec_name}': {e}",
            )


def _commit_verification_report(project_root, spec_name, logger=None) -> None:
    """报告落盘即入库（evo-add-verification-report-commit-on-write）。

    对 ``spec/changes/<spec>/verification-report.md`` 做 pathspec 精确的
    git add + commit（add 与 commit 同 pathspec，--only 语义），使「落盘」
    与「入库」同步，不再依赖归档兜底；subprocess 惯例照 core/archive_commit.py。

    - pathspec 严格单文件：禁用 ``git add -A -- spec`` 整目录（会卷入其它
      spec 在途草案，engine.py 同款警示），也不吞索引中无关 staged 内容；
    - 失败语义：非 git 仓库（被管项目可能无 git）静默跳过；其余失败
      （git 不可用、index.lock 争用等）只落 WARNING（附 stderr 摘要），
      绝不影响验证主流程与报告写盘结果；
    - 幂等：报告已入库且内容无变化时静默跳过（探测式：add 后与 HEAD 逐字
      节比对，不解析 git 各版本漂移的 nothing-to-commit 文案）——闸门在同
      一 spec 多轮验证中反复进入（pipeline/legacy 四调用点），重复放行不
      得反复落 WARNING 制造告警噪声。
    """
    proot = Path(project_root)
    rel_path = f"spec/changes/{spec_name}/verification-report.md"

    def _warn(msg: str) -> None:
        if logger is not None:
            logger.warning("verify_report", f"验证报告入库失败 '{spec_name}': {msg}")

    try:
        # 非 git 仓库：入库机制不适用，静默跳过（每轮验证都进闸门，
        # 对无 git 的被管项目逐轮刷 WARNING 纯属噪声）
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_REPORT_PROBE_TIMEOUT,
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return
        add = subprocess.run(
            ["git", "add", "--", rel_path],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_REPORT_ADD_TIMEOUT,
        )
        if add.returncode != 0:
            _warn(f"git add 失败: {add.stderr.strip() or f'exit {add.returncode}'}")
            return
        # 幂等主判定：add 后暂存内容与 HEAD 一致（报告已入库且内容无变化）
        # 即静默跳过——用探测式判定而非解析 nothing-to-commit 文案：git 各
        # 版本文案漂移（"nothing to commit, working tree clean" 与
        # "nothing added to commit but untracked files present" 并存），
        # 单一文案匹配会在重复放行时误落 WARNING。
        unchanged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "HEAD", "--", rel_path],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_REPORT_PROBE_TIMEOUT,
        )
        if unchanged.returncode == 0:
            return
        commit = subprocess.run(
            [
                "git", "commit",
                "-m", f"[fenix] {spec_name}: verification-report 入库",
                "--", rel_path,
            ],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_REPORT_COMMIT_TIMEOUT,
        )
        if commit.returncode != 0:
            output = (commit.stdout + "\n" + commit.stderr).strip()
            if (
                "nothing to commit" in output
                or "nothing added to commit" in output
            ):
                return  # 探测到提交之间他人已入库同内容（并发窗口）：静默跳过
            _warn(f"git commit 失败: {output or f'exit {commit.returncode}'}")
    except (OSError, subprocess.TimeoutExpired) as e:
        _warn(f"git 入库异常: {e}")


def ensure_verification_report(project_root, spec_name, logger=None) -> dict:
    """验证报告产物闸门：裁决放行前调用。

    返回 {"ok": True, "action": "present"|"synthesized"|"resynthesized"} 表示放行；
    返回 {"ok": False, "error": <文案>} 表示 MUST 阻止状态推进（fail-closed）。

    放行时（含 present——Agent 已自写报告、框架未落盘）报告文件同步入库
    （``_commit_verification_report``，pathspec 精确）；git 失败只落 WARNING，
    不改变放行结论。本动作只做 git 入库，不触碰 spec_has_content 内容认可
    判定（verification-report.md 保持不计入名单）。

    action=resynthesized：既有报告属上一轮残留（``_report_is_superseded``），
    已用本轮结构化数据重新合成覆盖。既有报告在场但不可读（OSError/
    UnicodeDecodeError）或可读但为空白（0 字节/纯空白，如 agent 写报告
    截断后崩溃）时同样走重新合成——残缺报告不得以 present 放行。
    """
    out_path = Path(project_root) / "spec" / "changes" / spec_name / "verification-report.md"
    unreadable = False
    if out_path.exists():
        try:
            existing = out_path.read_text(encoding="utf-8")
            if not existing.strip():
                # 报告在场但为空白（0 字节/纯空白，如 agent 写报告工具截断后
                # 崩溃）：空串解析不出任何结论会被 _report_is_superseded 判
                # 「非残留」而 fail-open，与不可读同款改走重新合成兜底。
                unreadable = True
        except (OSError, UnicodeDecodeError):
            # 报告在场但读不出（权限/编码损坏）：空串解析不出任何结论会被
            # _report_is_superseded 判「非残留」而 fail-open，故改走重新合成，
            # 合成失败再 fail-closed 告警。
            existing = ""
            unreadable = True
        if not unreadable and not _report_is_superseded(project_root, spec_name, existing):
            # Agent 已写报告且与本轮裁决一致：原样保留，不覆盖、不改 mtime；
            # 文件既已在盘，落盘即入库（present 是验证 Agent 自写报告的主路径）
            _commit_verification_report(project_root, spec_name, logger)
            return {"ok": True, "action": "present"}
        result = synthesize_verification_report(project_root, spec_name)
        if result.get("ok"):
            if logger is not None:
                if unreadable:
                    logger.warning(
                        "verify_report",
                        f"验证报告闸门：'{spec_name}' 既有报告不可读或为空白"
                        f"（权限/编码损坏/截断），已重新合成覆盖",
                    )
                else:
                    logger.warning(
                        "verify_report",
                        f"验证报告闸门：'{spec_name}' 报告属上一轮残留"
                        f"（本轮裁决已变更），已重新合成覆盖",
                    )
            _commit_verification_report(project_root, spec_name, logger)
            return {"ok": True, "action": "resynthesized"}
        error = result.get("error") or "验证报告缺失且无法合成"
        if unreadable:
            # 与缺失路径同一 fail-closed 承诺：阻断推进并发升级告警
            _append_alert(
                project_root,
                spec_name,
                SIGNAL_MISSING,
                "major",
                (
                    f"'{spec_name}' 验证报告在场但不可读或为空白且无法合成——"
                    "验证裁决放行被阻断，等待人工裁决"
                ),
                error,
                logger=logger,
            )
        else:
            # 残留报告重合成失败同样 fail-closed：与缺失/不可读路径告警对齐，
            # 人工可见性一致（不阻断则只会放行上一轮陈旧结论）
            _append_alert(
                project_root,
                spec_name,
                SIGNAL_MISSING,
                "major",
                (
                    f"'{spec_name}' 验证报告属上一轮残留且重新合成失败——"
                    "验证裁决放行被阻断，等待人工裁决"
                ),
                error,
                logger=logger,
            )
        return {"ok": False, "error": error}

    result = synthesize_verification_report(project_root, spec_name)
    if result.get("ok"):
        # 2026-08-29 用户决策：合成兜底静默化——只记框架日志，不发人工升级告警
        if logger is not None:
            logger.warning(
                "verify_report",
                f"验证报告闸门：'{spec_name}' 报告缺失，已由框架合成",
            )
        _commit_verification_report(project_root, spec_name, logger)
        return {"ok": True, "action": "synthesized"}

    error = result.get("error") or "验证报告缺失且无法合成"
    _append_alert(
        project_root,
        spec_name,
        SIGNAL_MISSING,
        "major",
        f"'{spec_name}' 验证报告缺失且无法合成——验证裁决放行被阻断，等待人工裁决",
        error,
        logger=logger,
    )
    if logger is not None:
        logger.error("verify_report", f"验证报告闸门阻断 '{spec_name}': {error}")
    return {"ok": False, "error": error}


# ── verdict 稳定性缓存（judge-rerun-stability R1）────────────────────────
# 持久化最近两轮 verdict（status + 失败场景 id 集 + spec 戳 + report.json mtime），
# 供 judge 派发前置守卫判定：连续两轮 verdict 一致时复用上次结果，不重派 judge。
# 文件名为 verdict_stability.json，**不得复用 verdict_cache.json**（后者已被
# core/verdict_check.py 的场景级指纹缓存占用，同路径写入会互相覆盖并破坏
# prompt_builder 的场景指纹注入）。
#
# judge_rerun_count（单 spec judge 重跑计数）为 STATE.md 字段（_judge_rerun_count，
# 与 _verify_fail_rounds 正交），不在本文件重复记账——本文件只持久化 verdict 轮次。
#
# schema:
# {
#   "stamp": "<sha256(spec content)[:16]>",
#   "report_mtime_ns": <int>,
#   "rounds": [
#     {"status": "...", "failed_ids": [...], "at": "..."},
#     ...
#   ],
#   "updated_at": "..."
# }

VERDICT_STABILITY_FILENAME = "verdict_stability.json"
# 连续两轮一致的最小轮数要求（<=此值即视为可复用）
_STABILITY_MIN_ROUNDS = 2


def _verdict_stability_path(project_root, spec_name) -> Path:
    """verdict_stability.json 路径（verify-progress/<spec>/）。"""
    return (
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / VERDICT_STABILITY_FILENAME
    )


def compute_spec_stamp(project_root, spec_name) -> str | None:
    """spec 戳：spec 内容与场景集内容的 sha256 前 16 位（同 scenario_fingerprint 风格）。

    组成：
      - ``spec/changes/<spec>/specs/**/spec.md`` 全部内容（按路径排序，若有多个
        capability spec 文件则拼接后一次性哈希）；
      - ``.fenix/verify-progress/<spec>/scenarios.json`` 内容（场景集冻结文件，
        _apply_scenario_freeze 每轮重写）。

    两路全部不可读返回 None（调用方按「无法判定」保守不复用）；任一路可用
    即按可得内容哈希（部分可得）。场景集变更或 spec.md 修改即改变 spec 戳
    → 缓存失效重新验证。
    """
    import hashlib as _hashlib

    parts: list[bytes] = []

    # 1) spec.md 全部内容（多 capability 按路径排序保证确定性）
    changes_dir = Path(project_root) / "spec" / "changes" / spec_name
    spec_files = sorted(changes_dir.glob("specs/**/spec.md"))
    for p in spec_files:
        try:
            parts.append(p.read_bytes())
        except OSError:
            pass

    # 2) scenarios.json 内容
    scenarios_path = (
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / "scenarios.json"
    )
    try:
        parts.append(scenarios_path.read_bytes())
    except OSError:
        pass

    if not parts:
        return None
    digest = _hashlib.sha256(b"\x00".join(parts)).hexdigest()[:16]
    return digest


def report_mtime_ns(project_root, spec_name) -> int | None:
    """report.json mtime 纳秒；缺失返回 None（用于稳定性缓存判据）。"""
    report_path = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    try:
        return report_path.stat().st_mtime_ns
    except OSError:
        return None


def verdict_failed_ids(report) -> list:
    """从 report.json 提取失败场景 id 集（status 非 pass/passed），排序去重。

    返回排序后的列表（方便跨轮一致比较）；report 为 None 或无场景时返回 []。
    """
    scenarios = (report or {}).get("scenarios") or []
    ids: set = set()
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        st = str(sc.get("status") or "")
        if st not in ("pass", "passed"):
            sid = sc.get("scenario_id") or sc.get("id")
            if sid is not None:
                ids.add(str(sid))
    return sorted(ids)


def read_verdict_stability(project_root, spec_name) -> dict | None:
    """读取 verdict_stability.json；缺失/损坏返回 None（fail-open）。

    返回顶层 dict（含 stamp / report_mtime_ns / rounds / updated_at）。
    """
    p = _verdict_stability_path(project_root, spec_name)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_verdict_stability(project_root, spec_name, data) -> None:
    """原子写 verdict_stability.json（失败静默：缓存缺失只导致下轮重裁）。"""
    p = _verdict_stability_path(project_root, spec_name)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp 唯一临时文件原子写（_atomic_write）：固定 .tmp 名并发写会
        # 互相截断后 replace 出截断缓存
        _atomic_write(p, json.dumps(data, ensure_ascii=False, indent=1, default=str))
    except OSError:
        pass


def record_verdict_round(
    project_root,
    spec_name,
    status,
    failed_ids,
    stamp: str | None = None,
    report_mtime: int | None = None,
) -> dict:
    """追加一轮裁决到 verdict_stability.json（保留最近两轮）；返回更新后数据。

    stamp / report_mtime 为 None 时自动从当前状态推导。
    首轮写入 rounds=[round]；第二轮起保留最近两轮用于一致比较。
    """
    if stamp is None:
        stamp = compute_spec_stamp(project_root, spec_name)
    if report_mtime is None:
        report_mtime = report_mtime_ns(project_root, spec_name)

    now = datetime.now(timezone.utc).isoformat()
    current_round = {
        "status": status or "unknown",
        "failed_ids": list(failed_ids or []),
        "at": now,
    }

    data = read_verdict_stability(project_root, spec_name) or {}
    rounds = data.get("rounds") or []
    if not isinstance(rounds, list):
        rounds = []

    rounds.append(current_round)
    # 保留最近两轮（_STABILITY_MIN_ROUNDS），更早的轮次出清
    if len(rounds) > _STABILITY_MIN_ROUNDS:
        rounds = rounds[-_STABILITY_MIN_ROUNDS:]

    data["stamp"] = stamp
    data["report_mtime_ns"] = report_mtime
    data["rounds"] = rounds
    data["updated_at"] = now

    write_verdict_stability(project_root, spec_name, data)
    return data


def is_verdict_stable(project_root, spec_name) -> bool:
    """复用判据：spec 戳未变 && report.json mtime 未变 && 最近两轮 verdict 一致。

    无缓存/单轮/两轮不一致/任一关键输入不可得 → False（保守不复用）。
    符合复用条件时 judge 派发前置守卫可跳过 run_planner。
    """
    data = read_verdict_stability(project_root, spec_name)
    if data is None:
        return False

    # 两轮以上一致性检查
    rounds = data.get("rounds") or []
    if len(rounds) < _STABILITY_MIN_ROUNDS:
        return False

    last_two = rounds[-_STABILITY_MIN_ROUNDS:]
    prev = last_two[0]
    curr = last_two[1]
    if not isinstance(prev, dict) or not isinstance(curr, dict):
        return False

    # verdict 一致性（status + failed_ids）
    if prev.get("status") != curr.get("status"):
        return False
    prev_failed = prev.get("failed_ids")
    curr_failed = curr.get("failed_ids")
    # 脏值容错：failed_ids 损坏成非列表时与缓存损坏同判 → 保守不复用（False）
    if not isinstance(prev_failed, list) or not isinstance(curr_failed, list):
        return False
    if sorted(prev_failed) != sorted(curr_failed):
        return False

    # spec 戳未变
    current_stamp = compute_spec_stamp(project_root, spec_name)
    if current_stamp is None:
        return False
    if current_stamp != data.get("stamp"):
        return False

    # report.json mtime 未变
    current_mtime = report_mtime_ns(project_root, spec_name)
    if current_mtime is None:
        return False
    if current_mtime != data.get("report_mtime_ns"):
        return False

    return True
