"""core.dashboard.data.artifacts — 验证产物解析（artifacts 组）。

refactor-dashboard-data-module D3 分组：本模块承载验证产物职责域。
verify-progress / 验证报告 / 测试场景 / 截图 / 裁决与 bug 解析。
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# ── 验证产物（容错解析） ──────────────────────────────────────────


# fix-deferred-findings CYC-1：parse_verify_progress 已迁入中性模块
# core.signals（pm_engine 侧消费点不再反向 import dashboard.data），
# 此处 re-export 保住既有门面导入路径。
from core.timelib import from_epoch
from core.signals import parse_verify_progress  # noqa: E402,F401


def parse_report(project_root, spec_name) -> dict:
    """解析 .fenix/verify-progress/<spec>/report.json（逐场景断言结果）。"""
    rp = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "report.json"
    if not rp.exists():
        return {"exists": False}
    try:
        data = json.loads(rp.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"exists": True, "error": "corrupt"}
        # 哨兵键不可被 report.json 自带同名字段覆盖：error 哨兵被 parse_bugs/
        # parse_filtered_failures/timeline/spec_detail 当 corrupt 判据消费
        data.pop("exists", None)
        data.pop("error", None)
        return {"exists": True, **data}
    except (json.JSONDecodeError, OSError, TypeError, UnicodeDecodeError):
        return {"exists": True, "error": "corrupt"}


def parse_run_result_scenarios(project_root, spec_name) -> list:
    """读取裁决 .fenix-run-result.json 中的场景明细（report.json 缺失/无场景时兜底）。

    合成报告（verify_report.py 兜底）场景下 report.json 可能不存在，而逐场景明细
    只存在于 .fenix-run-result.json（verify-progress 优先，项目根回退且需 spec 匹配）。
    full 模式 tester 结果场景在顶层 ``scenarios``；fast-track 结果（fast_track_result.py
    schema）嵌套在 ``verification.scenarios``——顶层缺失时回退读嵌套键，否则
    fast-track spec 的 Dashboard「场景结果」页签恒空（数据在专属副本里并不缺）。
    返回场景 dict 列表（已归一化截图字段），不可得返回 []。
    """
    # 候选读取（verify-progress 优先，项目根共享文件需 spec 匹配，损坏/非对象
    # fail-closed）复用 _load_run_result 单点封装，避免两处读取口径漂移
    data = _load_run_result(project_root, spec_name)
    if data is None:
        return []
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        # fast-track 格式回退：场景嵌套在 verification.scenarios
        ver = data.get("verification")
        scenarios = ver.get("scenarios") if isinstance(ver, dict) else None
    if not isinstance(scenarios, list) or not scenarios:
        return []
    out = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        norm = dict(sc)
        shots = sc.get("screenshots")
        if not isinstance(shots, list):
            shots = []
        norm["screenshots"] = [
            os.path.basename(s)
            for s in shots
            if isinstance(s, str) and s.strip()
        ]
        out.append(norm)
    # 场景结果缺 kind（契约补 kind 前的存量 run-result）时按 scenario_id
    # 从出题定义 test_scenarios.json 映射补齐；定义同样缺 kind 的旧 spec
    # 维持缺失（前端按缺省 web 渲染）。fail-open：读取异常不影响主数据。
    if any(not sc.get("kind") for sc in out):
        kind_by_id = {}
        try:
            ts_path = (
                Path(project_root)
                / ".fenix"
                / "verify-progress"
                / spec_name
                / "test_scenarios.json"
            )
            ts_data = json.loads(ts_path.read_text(encoding="utf-8"))
            ts_scenarios = ts_data.get("scenarios") if isinstance(ts_data, dict) else ts_data
            if isinstance(ts_scenarios, list):
                kind_by_id = {
                    str(sid): s.get("kind")
                    for s in ts_scenarios
                    if isinstance(s, dict)
                    and s.get("kind")
                    # 仅真值 ID 入表：id 与 scenario_id 皆缺时不再折算成
                    # 字面量 "None" 键，避免与缺 ID 的场景条目互相误配
                    and (sid := s.get("id") or s.get("scenario_id"))
                }
        except (json.JSONDecodeError, OSError, AttributeError, UnicodeDecodeError):
            kind_by_id = {}
        if kind_by_id:
            for sc in out:
                # 查询侧同样要求 scenario_id 为真值，防止命中 "None" 字面键
                if not sc.get("kind") and sc.get("scenario_id"):
                    k = kind_by_id.get(str(sc["scenario_id"]))
                    if k:
                        sc["kind"] = k
    return out


def list_screenshots(project_root, spec_name) -> list:
    """列出 .fenix/verify-progress/<spec>/screenshots/ 下的截图文件。"""
    ss_dir = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "screenshots"
    if not ss_dir.is_dir():
        return []
    out = []
    try:
        for p in sorted(ss_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                # 单文件容错：并发写/清理间隙下单文件不可 stat 只跳过该文件，
                # 不中断整表（原先整表落入外层 except 静默截断且无降级标记）
                try:
                    st = p.stat()
                except OSError:
                    continue
                out.append(
                    {
                        "file": p.name,
                        "size": st.st_size,
                        "mtime": from_epoch(st.st_mtime).isoformat(),  # SPEC-B 批④收拢
                    }
                )
    except OSError:
        pass
    return out


def _fold_summary(summary: dict, key: str, val: str) -> dict:
    """把表格/行内的计数键值折进汇总字典；非计数键忽略。

    键名先剥离括号别名（如「通过 (PASS)」「产品缺陷 (BUG)」，v3 验证报告方言）
    再匹配；全角/半角括号均支持。
    """
    if val.lower() in ("n/a", "-", "--", "—"):
        return summary
    k = key.lower()
    k = re.sub(r"[（(][^（）)]*[）)]", "", k)
    k = k.replace(" ", "").replace("数", "")
    if k in ("产品bug", "产品", "bug", "产品缺陷", "缺陷"):
        summary["product_bugs"] = val
    elif k in ("环境问题", "环境"):
        summary["env_issues"] = val
    elif k in ("通过", "passed", "通过数"):
        summary["passed"] = val
    elif k in ("失败", "failed", "失败数"):
        summary["failed"] = val
    elif k in ("错误", "error", "errors", "错误数"):
        summary["errors"] = val
    return summary


def _load_run_result(project_root, spec_name) -> dict | None:
    """读取裁决 .fenix-run-result.json（两路候选，不可得返回 None）。

    专属副本（.fenix/verify-progress/<spec>/.fenix-run-result.json）优先；
    项目根 .fenix/.fenix-run-result.json 为共享文件，须显式携带与当前 spec
    一致的 spec 字段，缺失或不符均视为其它 spec 残留忽略（fail-closed）。
    损坏/非对象同样返回 None（fail-closed）。
    """
    candidates = [
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / ".fenix-run-result.json",
        Path(project_root) / ".fenix" / ".fenix-run-result.json",
    ]
    for idx, path in enumerate(candidates):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        # 共享候选必须显式携带匹配的 spec 字段：缺字段（旧格式/写侧异常）时
        # 无法证明归属，直接放弃该候选（当前处拿不到场景 ID 集做归属推断，
        # 不为弱校验重排调用方签名），避免他 spec 残留被误合成进当前 spec 详情页
        if idx == 1 and data.get("spec") != spec_name:
            continue
        return data
    return None


def _run_result_verdict_and_bugs(data: dict) -> tuple:
    """从 run-result dict 提取（裁决值, bugs 清单）；无合法裁决返回 ("", [])。

    fast-track：裁决嵌套在 verification.verdict、bugs 在 verification.bugs
    （fast_track_result.py 契约）；full 模式：顶层 status 即裁决值、顶层 bugs
    （agents/verifier.md schema）。verdict 非法取值一律 fail-closed 拒收。
    """
    ver = data.get("verification")
    if isinstance(ver, dict) and ver.get("verdict") in ("verified", "bug-found"):
        bugs = ver.get("bugs")
        return ver["verdict"], bugs if isinstance(bugs, list) else []
    if data.get("status") in ("verified", "bug-found"):
        bugs = data.get("bugs")
        return data["status"], bugs if isinstance(bugs, list) else []
    return "", []


def _verdict_from_run_result(project_root, spec_name) -> dict:
    """从 .fenix-run-result.json 的裁决段合成 verdict（verification-report.md 缺失时兜底）。

    fast-track 单 agent 全包不产 verification-report.md，裁决结论只存在于
    .fenix-run-result.json 的 verification 段（fast_track_result.py 契约）；
    full 模式 md 缺失时结果文件顶层 status 也可能是裁决值。缺失/非法一律
    fail-closed 返回 exists: False（维持空态，不伪造结论）。

    summary 类型契约：本合成路径三桶计数为 int（含 0）、product_bugs=len(bugs)、
    env_issues 恒 None；与 md 解析路径（parse_verdict）的 str/None 形态不同源
    （同键跨路径 str|int|None 三态，消费方须容忍，详见 parse_verdict docstring）。
    """
    data = _load_run_result(project_root, spec_name)
    if data is not None:
        verdict_value, _bugs = _run_result_verdict_and_bugs(data)
        if verdict_value:
            scenarios = (
                data.get("verification", {}).get("scenarios")
                if isinstance(data.get("verification"), dict)
                else None
            )
            if not isinstance(scenarios, list):
                scenarios = data.get("scenarios")
            summary = {
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "product_bugs": len(_bugs),
                "env_issues": None,
            }
            if isinstance(scenarios, list):
                for sc in scenarios:
                    status = sc.get("status") if isinstance(sc, dict) else None
                    if status in ("pass", "passed"):
                        summary["passed"] += 1
                    elif status in ("fail", "failed"):
                        summary["failed"] += 1
                    elif status == "error":
                        summary["errors"] += 1
                    # warning/exempt 豁免类不入三桶（与裁决链豁免语义一致）
            return {
                "exists": True,
                "status": (
                    "✅ 验证通过（verified）"
                    if verdict_value == "verified"
                    else "❌ 未通过（Bug Found）"
                ),
                "status_detail": f"裁决: {verdict_value}",
                "conclusion": "",
                "summary": summary,
            }
    return {"exists": False, "status": "", "status_detail": "", "conclusion": "", "summary": {}}


def parse_verdict(project_root, spec_name) -> dict:
    """解析 verification-report.md 的验证结论，供 Dashboard 直接展示。

    返回: {"exists", "status", "status_detail", "conclusion", "summary"}
    - status: 结论标题（如 "环境不可达，无法验证" / "❌ 未通过（Bug Found）"）
    - status_detail: **状态:** 行（如 "环境问题 — Dashboard 服务未启动"）
    - conclusion: 结论段落（人类可读，避免用户只看 "0通过, 31失败"）
    - summary: {"passed","failed","errors","product_bugs","env_issues"} 尽力解析。
      类型契约（随产物路径漂移，消费方须按 str|int|None 三态容忍）：
      md 解析路径各值为 str（正则捕获组原样，如 "10"）或 None（未解析到，
      语义=「未知/不展示」，勿与 0 混做算术或严格相等）；run-result 合成路径
      （_verdict_from_run_result）为 int（含 0 计数），env_issues 恒 None。
      前端（detail.tsx verdictTone/VerdictPanel）以 parseInt + 模板串插值渲染，
      对 str/int 均兼容，仅以 != null 判「是否展示」；两路径形态分别被
      test_verify_report_gate / test_dashboard_data 断言钉死，勿单侧归一。

    md 文件缺失时回退 .fenix-run-result.json 的裁决段（_verdict_from_run_result）：
    fast-track 模式不产 verification-report.md，原先 verdict.exists 恒 False，
    列表「验证」列 Popover 与详情页 VerdictPanel 对 fast-track spec 恒隐。
    """
    path = Path(project_root) / "spec" / "changes" / spec_name / "verification-report.md"
    if not path.exists():
        return _verdict_from_run_result(project_root, spec_name)
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        # 读取/解码失败（权限抖动、编码异常、并发截断窗口）与「md 缺失」共用
        # 同一兜底（code-review item 409a469e4156）：置空串照常解析会返回
        # exists=True 且 status/summary 全空的结论（前端空面板），而 run-result
        # 里明明有可用裁决数据——读失败的降级方向不能比缺失更差。
        return _verdict_from_run_result(project_root, spec_name)

    summary = {
        "passed": None,
        "failed": None,
        "errors": None,
        "product_bugs": None,
        "env_issues": None,
    }
    status = ""
    status_detail = ""
    conclusion = ""
    conclusion_mode = False

    for raw in content.split("\n"):
        s = raw.strip()
        # 结论标题：## 结论[: 内联] / ## 结论摘要 / ## 判定结论[: 内联]。
        # 收紧为「结论(摘要)?」后仅接受冒号内联或行尾：尾随无冒号文本的变体
        # 标题（如「结论与建议」「结论说明」）不命中，避免尾文本被误并入
        # status 且后续正文被持续折进 conclusion
        m = re.match(r"^#{2,4}\s*(?:判定)?结论(摘要)?\s*(?:[：:]\s*(.*))?$", s)
        if m:
            status = (m.group(2) or "").strip() or status
            conclusion_mode = True
            continue
        if conclusion_mode:
            if re.match(r"^#{2,4}\s+", s):
                conclusion_mode = False
            elif s.startswith("**状态"):
                # 权威写侧「**状态：detail**」由前缀/行尾两分支清洗干净；
                # 非规范变体「**状态:** detail」（粗体在冒号前闭合）会残留
                # 行中部「**」，strip 前再补一次行首粗体闭合符清洗
                status_detail = re.sub(
                    r"^\*+\s*", "", re.sub(r"^.*?状态\s*[：:]\s*|\*\*\s*$", "", s)
                ).strip()
            elif s.startswith(("|", "---", "-", "**", ">")):
                pass
            elif s:
                # 行间用 \n 衔接、空行落为段落分隔（\n\n），保住 markdown 段落结构供前端渲染
                conclusion += ("\n" if conclusion else "") + s
            elif conclusion:
                conclusion += "\n"
        # 备选状态：**验证结果**：❌ 未通过（Bug Found）
        m2 = re.match(r"^\*\*\s*验证结果\s*\*\*\s*[：:]\s*(.+)$", s)
        if m2 and not status:
            status = m2.group(1).strip()
        # 表格行：| 通过 | 0 |
        m3 = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", s)
        if m3:
            summary = _fold_summary(summary, m3.group(1), m3.group(2).strip())
            continue
        # 行内计数：通过：0
        m4 = re.match(r"^([^|#]{1,12})\s*[：:]\s*([\dN/A\-＋+]+)\s*$", s)
        if m4:
            summary = _fold_summary(summary, m4.group(1), m4.group(2).strip())

    # 兜底：全文搜索计数（处理 "通过：0 | 失败：0 | 错误：10" 行内连写）
    if any(v is None for v in summary.values()):
        for pat, field in [
            # 否定环视排除「未通过」「不通过」前缀，避免兜底把失败计数误计为 passed
            (r"(?<![未不])通过", "passed"),
            ("失败", "failed"),
            ("错误", "errors"),
            (r"产品\s*Bug", "product_bugs"),
            ("环境问题", "env_issues"),
        ]:
            if summary[field] is not None:
                continue
            # f-string 拼接：% 格式化与正则里的 % 字面量混用会在词表演进时抛 ValueError
            mm = re.search(rf"{pat}\s*[：:]\s*([\dN/A\-＋+]+)", content, re.I)
            if mm and mm.group(1).strip().lower() not in ("n/a", "-", "--"):
                summary[field] = mm.group(1).strip()

    return {
        "exists": True,
        "status": status,
        "status_detail": status_detail,
        "conclusion": conclusion.strip()[:600],
        "summary": summary,
    }


def parse_bugs(project_root, spec_name) -> list:
    """聚合 bug 列表：来自 report.json 的失败/错误场景。

    返回: [{"source": "report", "severity", "scenario_ids", "assertion_type",
            "description", "evidence", "screenshots"}]

    bug 只从结构化的 report.json 提取（每条失败/错误场景 + 失败断言 + 截图）。
    不再从 verification-report.md 逐行正则猜测——Markdown 是人读文档，逐行抓
    「bug/缺陷/失败」关键词会把「环境失败」「被修复缺陷的背景描述」「通过型报告」
    误判为产品缺陷（add-parallelism、fix-worktree-agent-cwd、fix-add-parallelism 等
    均因此产生过大量虚假 bug）。

    状态枚举对齐写入侧（裁决后失败场景不再消失）：引擎写 "fail"（engine.py
    _determine_scenario_status），裁决链 enforce_status_mapping（verdict_check.py）
    与裁决 Agent 自写报告产 "failed"——两族取值都算失败场景；warning 保持不记
    Bug（合规报告禁止 product-bug 挂 warning，会被强制 failed）。
    分类过滤（add-verdict-evidence-taxonomy）：test-defect/flaky/env 归类 =
    非产品缺陷，不进 Bug 列表（与报告「产品 Bug」计数同语义）；product-bug、
    旧格式无分类（向后兼容）及未知取值（fail-open）照常收录。

    回退（第五读侧缺口）：report.json 缺失/损坏时从 .fenix-run-result.json 的
    bugs 清单收录（fast-track 嵌套 verification.bugs，full 模式 verifier 顶层
    bugs；裁决段由 _run_result_verdict_and_bugs 单点解析）——fast-track 不产
    report.json，原先详情页 Bug 列表对其恒空（source 标记 "run-result"）。
    条目统一携带 scenario/assertion 兼容字段（前端 dashboard.ts 类型为单数
    bug.scenario / bug.assertion，后端原先只给 scenario_ids/assertion_type，
    「关联场景」「断言类型」两行因此从未渲染过）。
    """
    from core.verdict_check import VERDICT_CLASSES

    non_product_classes = tuple(c for c in VERDICT_CLASSES if c != "product-bug")
    bugs = []
    report = parse_report(project_root, spec_name)
    if not report.get("exists") or report.get("error"):
        # report.json 缺失/损坏：run-result bugs 清单回退（fail-closed 无数据返回 []）
        data = _load_run_result(project_root, spec_name)
        if data is None:
            return bugs
        _verdict, rt_bugs = _run_result_verdict_and_bugs(data)
        # severity 归一：fast-track.md 模板是 critical|major|minor，verifier 自由
        # 产出实测漂移为 high|medium|low（agents/verifier.md 步骤 8 未定义条目
        # schema）——读取端统一映射到前端三档色系，未知值原样透传由前端兜底。
        severity_map = {
            "critical": "critical",
            "high": "major",
            "major": "major",
            "medium": "major",
            "minor": "minor",
            "low": "minor",
        }
        for bug in rt_bugs:
            if not isinstance(bug, dict):
                continue
            ev = bug.get("evidence")
            if isinstance(ev, dict):
                ev = json.dumps(ev, ensure_ascii=False)
            elif not isinstance(ev, str):
                ev = ""
            scenario_ids = bug.get("scenario_ids")
            if not isinstance(scenario_ids, list):
                scenario_ids = []
            assertion_type = bug.get("assertion_type") or ""
            raw_severity = bug.get("severity") or ""
            bugs.append(
                {
                    "source": "run-result",
                    "severity": severity_map.get(raw_severity, raw_severity) or "major",
                    "scenario_ids": scenario_ids,
                    "assertion_type": assertion_type,
                    "description": bug.get("description") or bug.get("title") or "",
                    "evidence": ev or (bug.get("root_cause") or ""),
                    "root_cause": bug.get("root_cause") or "",
                    "classification": None,
                    "status_corrected": False,
                    "screenshots": [],
                    # verifier 自由 schema 透传（id/title/location），fast-track 无则缺省
                    "id": bug.get("id") or "",
                    "title": bug.get("title") or "",
                    "location": bug.get("location") or "",
                    # 前端卡片渲染兼容字段（bug.scenario / bug.assertion）
                    "scenario": ", ".join(str(s) for s in scenario_ids),
                    "assertion": assertion_type,
                }
            )
        return bugs
    scenarios = report.get("scenarios")
    # scenarios 为非可迭代标量（部分写入/手改）时按空处理，对齐 parse_run_result_scenarios 防护口径
    if not isinstance(scenarios, list):
        scenarios = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status not in ("fail", "failed", "error"):
            continue
        classification = sc.get("classification")
        if classification in non_product_classes:
            continue
        # assertion_results 为 null（部分写入/手改）时按空处理，对齐同函数 scenarios/screenshots 防护口径
        assertion_results = sc.get("assertion_results")
        if not isinstance(assertion_results, list):
            assertion_results = []
        failed_assertions = [
            a
            for a in assertion_results
            if isinstance(a, dict) and not a.get("pass", True)
        ]
        # 截图路径归一化为文件名：report.json 存的是服务器本地绝对路径，
        # 前端需拼 /screenshots/<project>/<spec>/<file>，只取 basename
        shots = sc.get("screenshots")
        if not isinstance(shots, list):
            shots = []
        screenshots = [
            os.path.basename(s)
            for s in shots
            if isinstance(s, str) and s.strip()
        ]
        # 裁决分类与证据（add-verdict-evidence-taxonomy 3.1）：从场景条目摘取；
        # 旧格式 report.json 无 classification/evidence 字段时为空/缺省，向后兼容。
        # 断言级证据优先（message/detail/actual，沿用分类化改造前的既有展示口径）；
        # 场景级结构化 evidence（judge 增强产出）仅在断言证据全空时兜底，
        # 保证旧数据/断言结果为空的失败场景仍有证据可见。
        # 与 parse_filtered_failures 的 evidence_summary 链（first_failed_step →
        # failed_assertions 首项 actual）口径不同：那边无断言级逐条字段，
        # 只从场景结构化 evidence 摘要。
        sc_evidence = sc.get("evidence")
        if isinstance(sc_evidence, dict):
            sc_evidence = json.dumps(sc_evidence, ensure_ascii=False)
        elif not isinstance(sc_evidence, str):
            sc_evidence = ""
        for a in failed_assertions or [{}]:
            bugs.append(
                {
                    "source": "report",
                    "severity": "major" if status in ("fail", "failed") else "critical",
                    "scenario_ids": [sc.get("scenario_id", "?")],
                    "assertion_type": a.get("type", "step"),
                    "description": sc.get("description", "未命名场景"),
                    "evidence": (a.get("message") or a.get("detail") or a.get("actual") or "")
                    or sc_evidence,
                    "classification": classification,
                    "status_corrected": sc.get("status_corrected", False),
                    "screenshots": screenshots,
                    "scenario_status": status,
                    # 前端卡片渲染兼容字段（bug.scenario / bug.assertion，类型单复数漂移）
                    "scenario": str(sc.get("scenario_id", "?")),
                    "assertion": a.get("type", "step"),
                }
            )
    return bugs


def parse_filtered_failures(project_root, spec_name) -> list:
    """提取被分类过滤（非 product-bug）的失败/错误场景摘要（fix-verify-verdict-visibility）。

    返回: [{"scenario_id", "classification", "evidence_summary", "screenshots",
            "status_corrected", "status"}]

    与 parse_bugs 互为互补面（同一过滤语义的互补侧）：bugs 收录 product-bug 与
    旧格式无分类（fail-open）；filtered_failures 仅收录 test-defect/flaky/env 分类
    的失败/错误场景——二者过滤条件互斥，不双计。旧格式 report.json 无
    classification 字段 → 不产生条目（fail-open 语义，向后兼容）。

    evidence_summary 回退链（对齐设计 Decision 3）：evidence.first_failed_step
    （裁决 Agent 产出的人类可读理由）→ evidence.failed_assertions 首项 actual →
    空串；缺字段不抛错。
    """
    from core.verdict_check import VERDICT_CLASSES

    non_product_classes = tuple(c for c in VERDICT_CLASSES if c != "product-bug")
    out = []
    report = parse_report(project_root, spec_name)
    if not report.get("exists") or report.get("error"):
        return out
    scenarios = report.get("scenarios")
    # scenarios 为非可迭代标量（部分写入/手改）时按空处理，对齐 parse_run_result_scenarios 防护口径
    if not isinstance(scenarios, list):
        scenarios = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        status = sc.get("status")
        if status not in ("fail", "failed", "error"):
            continue
        classification = sc.get("classification")
        if classification not in non_product_classes:
            continue
        # evidence 摘要：first_failed_step → failed_assertions 首项 actual → 空串
        evidence_summary = ""
        sc_evidence = sc.get("evidence")
        if isinstance(sc_evidence, dict):
            ffs = sc_evidence.get("first_failed_step")
            if isinstance(ffs, str) and ffs.strip():
                evidence_summary = ffs
            else:
                failed_assertions = sc_evidence.get("failed_assertions")
                if isinstance(failed_assertions, list) and failed_assertions:
                    first = failed_assertions[0]
                    if isinstance(first, dict):
                        actual = first.get("actual")
                        if isinstance(actual, str) and actual.strip():
                            evidence_summary = actual
        # 截图路径归一化为文件名（与 parse_bugs 同一口径，前端拼 /screenshots/ 路由）
        shots = sc.get("screenshots")
        if not isinstance(shots, list):
            shots = []
        screenshots = [
            os.path.basename(s)
            for s in shots
            if isinstance(s, str) and s.strip()
        ]
        out.append(
            {
                "scenario_id": sc.get("scenario_id", "?"),
                "classification": classification,
                "evidence_summary": evidence_summary,
                "screenshots": screenshots,
                "status_corrected": sc.get("status_corrected", False),
                "status": status,
            }
        )
    return out
