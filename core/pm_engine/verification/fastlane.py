"""fastlane.py — bug-found 小缺陷轻量通道（add-pipeline-throughput-governance 4.x）。

三条件判定（minor-defect-fastlane spec，design D4）：

  ① 本轮失败场景数 = 1；
  ② judge 归因的修复影响面 ≤ 3 文件（从 ``judge_attribution.json`` 的
     attribution 摘要提取仓库相对路径；清单不可读按「不满足」保守回落整轮
     ——与条件③的 fail-open 方向相反：fastlane 是优化通道，证据缺失宁可
     整轮也不误入）；
  ③ 无 judge 争议/裁决标记——判据从 judge/实现/验证结果文件
     ``.fenix-run-result.json``
     的 findings 中 dispute/adjudication 类条目读取（读取先例
     ``branch_guard._disputed_deliverables`` 对 ``deliverable-dispute`` 的解析）；
     信号机制缺失或无条目时按「无争议」fail-open 并在判定记录留痕。

三条件全满足 → 生成 code-fix 轻量修复任务（``agents/code-fix.md`` 车道，主树
直接修复）+ 子集重验（失败场景 ∪ ``depends_on`` 前置链（递归）∪ 以失败场景
为前置的下游场景（递归），未实跑场景沿用上一轮原判定并标注来源）；任一条件
不满足 → 既有 bug-found→fix SPEC 整轮路径原样。fastlane 修复失败计入该 spec
既有验证轮预算（``_verify_fail_rounds`` 与整轮失败同账）；同一验证轮连续
2 次 fastlane 修复后仍失败强制回落整轮（STATE 字段 ``_fastlane_fail_streak``）。
修复 diff 不豁免既有 code-review/交付物门禁（轻量 run 走同一 ``_execute_agent``
收口链路，门禁照常）。

子集重验独立可用（不依赖 verdict 缓存能力合入：直接以子集场景集作为本轮
执行集构造引擎执行，绕过缓存逻辑）。
"""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path

# fastlane 触发阈值：judge 归因修复影响面文件数上限（minor-defect-fastlane 条件②）
FASTLANE_MAX_AFFECTED_FILES = 3
# 同一验证轮连续 fastlane 修复失败回落阈值（minor-defect-fastlane 条款：
# 连续 2 次失败强制回落整轮 fix SPEC 路径，防轻量通道打转）
FASTLANE_MAX_CONSECUTIVE_FAILURES = 2
# STATE 字段：连续 fastlane 失败计数（`_` 前缀随 STATE 往返持久化）
FASTLANE_STREAK_FIELD = "_fastlane_fail_streak"
# findings 中视为「judge 争议/裁决」的条目 type 关键词（不区分大小写子串匹配）
DISPUTED_FINDING_KEYWORDS = ("dispute", "adjudication")

# 仓库相对路径形态（judge 归因文本中的影响面文件）：
# 目录前缀形态（core/…、tests/…、bin/…）或带可识别扩展名的文件名。
_AFFECTED_PATH_RE = re.compile(
    r"\b(?:core|bin|docs|tests|agents|scripts|src|fenixd)[\w\-./]*\.[A-Za-z0-9]+"
    r"|\b[A-Za-z0-9_\-]+\.(?:py|md|ya?ml|json|toml|ts|tsx|js|jsx|vue|html|css|scss|svelte)\b"
)


def fastlane_decision_path(project_root, spec_name: str) -> Path:
    """判定记录落盘路径：``.fenix/verify-progress/<spec>/fastlane_decision.json``。"""
    return (
        Path(project_root) / ".fenix" / "verify-progress" / spec_name
        / "fastlane_decision.json"
    )


def disputed_findings(result) -> list:
    """结果 dict findings 中 dispute/adjudication 类条目（保序）。

    先例 ``branch_guard._disputed_deliverables``：findings 由 LLM/agent 产出，
    元素非 dict 时忽略（不抛穿）；顶层非 dict（如旧格式落盘的裸 findings
    数组）同样按无条目处理。type 字段子串匹配 dispute/adjudication
    （覆盖 deliverable-dispute / pending-interaction-adjudication 等变体）。
    """
    if not isinstance(result, dict):
        return []
    out: list = []
    for f in (result or {}).get("findings") or []:
        if not isinstance(f, dict):
            continue
        ftype = str(f.get("type") or "").strip().lower()
        if any(kw in ftype for kw in DISPUTED_FINDING_KEYWORDS):
            out.append(f)
    return out


def has_dispute_signal(pipeline, spec_name: str) -> tuple:
    """条件③：judge/实现/验证结果文件 findings 是否含争议条目。

    读取先例 ``branch_guard._disputed_deliverables``：从 run 结果文件的
    findings 读 dispute/adjudication 类条目。信号机制缺失（结果文件不存在/
    不可读/无 findings）按「无争议」fail-open，返回 ``(False, 留痕)``
    ——留痕供判定记录说明证据来源与缺失方向。

    Returns:
        (has_dispute, evidence)：has_dispute=True 表示存在争议条目（不走
        fastlane）；evidence 为判定依据的简短描述。
    """
    root = pipeline._context.project_root
    # 结果文件候选（按具体度降序，首个存在且可读者生效）：
    # 1. judge 结果文件 .fenix/verify-progress/<spec>/.fenix-run-result.json
    #    （本轮裁决落点，与 escalation._judge_bugs_declare_env 的 primary
    #    同源；路径自带 spec 隔离，免跨 spec 戳校验）——置前：fastlane 评估
    #    发生在 judge 之后，共享根文件此时多为实现/验证轮残留，先查最具体
    #    落点才不漏 judge 侧 dispute/adjudication 条目；
    # 2. 项目根共享 .fenix/.fenix-run-result.json（跨 spec 单例，实现/验证
    #    agent 收尾契约的唯一落点）；
    # 3. spec-review 副本。
    shared_root_result = Path(root) / ".fenix" / ".fenix-run-result.json"
    candidates = [
        (
            Path(root) / ".fenix" / "verify-progress" / spec_name
            / ".fenix-run-result.json"
        ),
        shared_root_result,
        Path(root) / ".fenix" / "spec-review" / spec_name / ".fenix-run-result.json",
    ]
    unreadable: list = []
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # 不可读 fail-open（按无争议），留痕于 evidence（不可读≠缺失）
            unreadable.append(path)
            continue
        # 跨 spec 归属校验：共享文件残留的可能是其它 spec 实现轮的结果——
        # spec 戳为非空字符串且与当前 spec 不符时不据此判定（既防误挡本
        # spec，也防本 spec 争议被其它 spec 后写覆写后误放行），回落检查
        # 下一候选。口径对齐 dashboard.data.artifacts._load_run_result：
        # 缺 spec 戳的旧格式文件仍采信；spec 专属副本路径自带隔离，不校验。
        if path == shared_root_result and isinstance(data, dict):
            stamp = data.get("spec")
            if isinstance(stamp, str) and stamp and stamp != spec_name:
                continue
        hits = disputed_findings(data)
        if hits:
            types = sorted({str(h.get("type")) for h in hits})
            return True, f"{path.name} findings 含争议条目: {types}"
        return False, f"{path.name} findings 无 dispute/adjudication 条目（fail-open 无争议）"
    if unreadable:
        # 存在但损坏/不可读：留痕区分于「缺失」，避免审计者朝文件缺失方向排障
        return False, (
            "结果文件不可读（按无争议 fail-open）: "
            + ", ".join(str(p) for p in unreadable)
        )
    return False, "结果文件缺失（信号机制缺失按无争议 fail-open）"


def extract_affected_files(attribution_text) -> list:
    """从 judge 归因文本提取影响面文件清单（repo 相对路径，去重保序）。"""
    if not attribution_text or not isinstance(attribution_text, str):
        return []
    seen: list = []
    for m in _AFFECTED_PATH_RE.findall(attribution_text):
        if m not in seen:
            seen.append(m)
    return seen


def judge_affected_files(pipeline, spec_name: str) -> tuple:
    """条件②：judge 归因的修复影响面文件清单。

    从 ``.fenix/verify-progress/<spec>/judge_attribution.json`` 逐条目
    attribution 摘要提取仓库路径并集。

    Returns:
        (files|None, evidence)：files=None 表示归因产物不可读（按「不满足」
        保守回落整轮——证据缺失不误入优化通道）；files 为空列表时同样按
        「不满足」处理（无归因＝影响面不可判定）。
    """
    path = (
        Path(pipeline._context.project_root) / ".fenix" / "verify-progress"
        / spec_name / "judge_attribution.json"
    )
    if not path.exists():
        return None, f"judge_attribution.json 缺失: {path.name}（影响面不可判定，保守回落）"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None, "judge_attribution.json 不可读（影响面不可判定，保守回落）"
    if not isinstance(entries, list):
        return None, "judge_attribution.json 结构非法（影响面不可判定，保守回落）"
    files: list = []
    for e in entries:
        if isinstance(e, dict):
            text = str(e.get("attribution") or "")
        else:
            text = str(e or "")
        for f in extract_affected_files(text):
            if f not in files:
                files.append(f)
    return files, f"judge_attribution 提取影响面 {len(files)} 文件: {files}"


def _scenario_view(s):
    """统一场景条目视图：``(id, depends_on, raw)``。

    兼容两种形态——``load_scenarios`` 返回的 ``TestScenario`` 对象（属性
    ``id``/``depends_on``，``to_dict()`` 序列化）与纯 dict（键
    ``scenario_id``/``id``/``depends_on``）。非识别形态返回 ``("", [], None)``
    由调用方忽略（不抛穿）。
    """
    if isinstance(s, dict):
        return (
            str(s.get("scenario_id") or s.get("id") or ""),
            list(s.get("depends_on") or []),
            s,
        )
    sid = str(getattr(s, "id", "") or "")
    return sid, list(getattr(s, "depends_on", None) or []), s


def subset_scenario_ids(scenarios, failed_id: str) -> list:
    """子集重验场景集：失败场景 ∪ depends_on 前置链（递归）∪ 下游场景（递归）。

    下游纳入防修复波及依赖方而漏验：以失败场景（或其前置）为 ``depends_on``
    前置的场景全部并入（不动点迭代）。scenarios 为场景列表（``TestScenario``
    对象或场景 dict，见 core/verify_engine/scenarios.py 契约）。
    """
    by_id: dict = {}
    for s in scenarios or []:
        sid, _deps, _raw = _scenario_view(s)
        if sid:
            by_id[sid] = s
    if failed_id not in by_id:
        # 失败场景不在场景集（定义漂移）：退化为仅失败场景本身
        return [failed_id]
    subset = {failed_id}
    # 前置链（递归上溯）
    stack = [failed_id]
    while stack:
        cur = stack.pop()
        _sid, deps, _raw = _scenario_view(by_id.get(cur))
        for dep in deps:
            dep = str(dep)
            if dep and dep not in subset:
                subset.add(dep)
                stack.append(dep)
    # 下游（递归下探，不动点）
    changed = True
    while changed:
        changed = False
        for sid, s in by_id.items():
            if sid in subset:
                continue
            _sid, deps, _raw = _scenario_view(s)
            if {str(d) for d in deps} & subset:
                subset.add(sid)
                changed = True
    return [sid for sid in by_id if sid in subset]


def merge_subset_report(prev_report, subset_report) -> dict:
    """合并子集重验报告与上一轮报告：未实跑场景沿用上一轮原判定并标注来源。

    重验报告 MUST 含全量场景判定（minor-defect-fashlane spec 子集重验条款）：
    实跑场景取子集报告最新判定；其余场景全量回填上一轮原判定（pass 沿用
    通过结论，warning/blocked-env 等原样保留 classification 等侧车消费字段）
    并附 ``source: "carried-over: fastlane subset reverify"`` 标注——非 pass
    场景若丢弃，合并报告 total 缩水、warning streak 侧车按「不在本轮场景集」
    剪枝清零，triage 连续计数被收敛静默打断。
    """
    merged = copy.deepcopy(subset_report) or {}
    executed_ids = {
        str(sc.get("scenario_id") or sc.get("id") or "")
        for sc in (subset_report or {}).get("scenarios") or []
        if isinstance(sc, dict)
    }
    carried = []
    for sc in (prev_report or {}).get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("scenario_id") or sc.get("id") or "")
        if not sid or sid in executed_ids:
            continue
        # 未实跑场景全量回填（不只 pass）：warning 等非 pass 场景若丢弃，
        # 合并报告 total 缩水（少于冻结场景集），warning streak 侧车按
        # 「不在本轮场景集」剪枝清零——triage 连续计数被静默打断。
        entry = copy.deepcopy(sc)
        if sc.get("status") in ("pass", "passed"):
            entry["source"] = "carried-over: fastlane subset reverify（沿用上一轮通过结论）"
        else:
            entry["source"] = (
                "carried-over: fastlane subset reverify（未实跑，沿用上一轮原判定）"
            )
        carried.append(entry)
    # 场景列表取 merged 自身的 deepcopy 副本，避免与原 subset_report 共享条目引用
    merged["scenarios"] = list(merged.get("scenarios") or []) + carried
    # summary 重算（全部场景判定齐备）——口径对齐
    # pipeline._merge_cached_scenario_results（warnings/blocked_env 恒在场，
    # blocked-env 并入 warnings，下游按 key 直读不 KeyError/误读）
    passed = failed = errors = warnings = blocked_env = 0
    for sc in merged["scenarios"]:
        st = sc.get("status")
        if st in ("pass", "passed"):
            passed += 1
        elif st == "warning":
            warnings += 1
        elif st in ("fail", "failed"):
            failed += 1
        elif st == "error":
            errors += 1
        elif st == "blocked-env":
            blocked_env += 1
    warnings += blocked_env  # blocked-env 并入 warnings（同 _merge_cached_scenario_results 口径）
    merged["summary"] = {
        "total": len(merged["scenarios"]),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "warnings": warnings,
        "blocked_env": blocked_env,
        "carried_over": len(carried),
    }
    return merged


def record_decision(pipeline, spec_name: str, decision: dict) -> None:
    """判定过程与所选路径落盘（可追溯为何走/不走 fastlane）+ 日志留痕。

    落盘失败只记 warning（判定记录是审计面，不阻断验证主流程）。
    """
    path = fastlane_decision_path(pipeline._context.project_root, spec_name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(decision)
        payload["spec"] = spec_name
        payload["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine", f"fastlane 判定记录落盘失败 '{spec_name}'（不阻断）: {e}"
        )
    pipeline._context.logger.info(
        "pm_engine",
        f"fastlane 判定 '{spec_name}': path={decision.get('path')} "
        f"eligible={decision.get('eligible')} reasons={decision.get('reasons')}",
    )


def evaluate_fastlane(pipeline, spec_name: str, report=None) -> dict:
    """fastlane 三条件判定（minor-defect-fastlane spec 判定阈值条款）。

    评估 ①失败场景数=1 ②影响面≤3 文件 ③无争议，全程条件细节随判定落盘
    （record_decision），所选路径可追溯。不产生任何状态变更。

    Returns:
        {"eligible", "path", "failed_id", "subset_ids", "affected_files",
         "conditions": {...}, "reasons": [...]}
    """
    ctx = pipeline._context
    reasons: list = []
    conditions: dict = {}

    # ① 失败场景数 = 1
    failed_ids = pipeline._failed_scenario_ids(spec_name)
    single_ok = len(failed_ids) == 1
    failed_id = failed_ids[0] if single_ok else None
    conditions["single_failure"] = {
        "ok": single_ok,
        "failed_scenarios": failed_ids,
    }
    if not single_ok:
        reasons.append(f"条件①不满足：失败场景数 {len(failed_ids)} ≠ 1")

    # ② judge 影响面 ≤ FASTLANE_MAX_AFFECTED_FILES（不可读按不满足，保守回落）
    files, evidence2 = judge_affected_files(pipeline, spec_name)
    files_ok = files is not None and 0 < len(files) <= FASTLANE_MAX_AFFECTED_FILES
    conditions["affected_files"] = {
        "ok": files_ok,
        "files": files,
        "evidence": evidence2,
    }
    if not files_ok:
        reasons.append(
            f"条件②不满足：影响面 {len(files) if files is not None else '不可判定'} "
            f"文件（阈值 ≤{FASTLANE_MAX_AFFECTED_FILES}）—— {evidence2}"
        )

    # ③ 无争议（信号缺失按无争议 fail-open，留痕）
    has_dispute, evidence3 = has_dispute_signal(pipeline, spec_name)
    conditions["no_dispute"] = {"ok": not has_dispute, "evidence": evidence3}
    if has_dispute:
        reasons.append(f"条件③不满足：{evidence3}")

    eligible = single_ok and files_ok and not has_dispute

    # 子集场景集（失败场景 ∪ 前置链 ∪ 下游）——条件①不满足时为空
    subset_ids: list = []
    if failed_id:
        try:
            from core.verify_engine.scenarios import load_scenarios

            scenarios_path = (
                Path(ctx.project_root) / ".fenix" / "verify-progress" / spec_name
                / "test_scenarios.json"
            )
            scenarios = load_scenarios(scenarios_path) if scenarios_path.exists() else []
            subset_ids = subset_scenario_ids(scenarios, failed_id)
        except Exception as e:  # 场景定义不可读：退化为仅失败场景
            ctx.logger.warning(
                "pm_engine",
                f"fastlane 子集计算退化 '{spec_name}'（仅失败场景）: {e!r}",
            )
            subset_ids = [failed_id]

    decision = {
        "eligible": eligible,
        "path": "fastlane" if eligible else "full-round",
        "failed_id": failed_id,
        "subset_ids": subset_ids,
        "affected_files": files or [],
        "conditions": conditions,
        "reasons": reasons or ["三条件全满足"],
    }
    record_decision(pipeline, spec_name, decision)
    return decision


def subset_reverify(pipeline, spec_name: str, subset_ids: list) -> dict:
    """子集重验：以子集场景集作为本轮执行集执行（独立可用，绕过缓存逻辑）。

    从既有场景文件过滤出子集写 ``test_scenarios.fastlane.json`` 后复用既有
    stage2 引擎执行段（``_execute_stage2``：可达性自愈 + 引擎执行），返回
    ``{"ok", "report", "reason"}``。ok=True 表示子集全部通过。
    """
    from core.verify_engine.scenarios import load_scenarios

    ctx = pipeline._context
    verify_dir = Path(ctx.project_root) / ".fenix" / "verify-progress" / spec_name
    scenarios_path = verify_dir / "test_scenarios.json"
    if not scenarios_path.exists():
        return {"ok": False, "report": None, "reason": "场景文件缺失，子集重验无法执行"}
    try:
        scenarios = load_scenarios(scenarios_path)
    except ValueError as e:
        return {"ok": False, "report": None, "reason": f"场景文件验收失败: {e}"}

    want = {str(s) for s in subset_ids or []}
    subset = [s for s in scenarios if _scenario_view(s)[0] in want]
    if not subset:
        return {"ok": False, "report": None, "reason": "子集场景为空（id 不在场景集）"}

    # TestScenario 对象走 to_dict() 序列化（load_scenarios 契约），dict 原样
    subset_payload = [
        s.to_dict() if hasattr(s, "to_dict") else s for s in subset
    ]
    subset_path = verify_dir / "test_scenarios.fastlane.json"
    try:
        subset_path.write_text(
            json.dumps(subset_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        # 写盘失败（磁盘满/权限等）按 fastlane 失败回落整轮，维持返回值契约
        return {"ok": False, "report": None, "reason": f"子集场景文件写盘失败: {e}"}
    env_error, report, _app_reachable, _reach_note, aborted = pipeline._execute_stage2(
        spec_name, verify_dir, subset_path, skip_prune=True
    )
    if aborted:
        return {"ok": False, "report": None, "reason": "应用不可达 fail-fast（子集重验中止）"}
    if env_error is not None:
        return {"ok": False, "report": None, "reason": f"环境错误: {env_error}"}
    if not isinstance(report, dict):
        return {"ok": False, "report": None, "reason": "子集重验报告不可读"}
    # 残缺报告守卫：summary 缺失或计数非法时 remaining 恒为 0，会把未经验证
    # （甚至零场景实跑）的报告误判为通过后收敛 verified（绕开失败归因管道），
    # 按重验失败回落整轮（与既有子集重验失败分支同构）。
    summary = report.get("summary")
    if not isinstance(summary, dict) or not all(
        isinstance(summary.get(k), int) and not isinstance(summary.get(k), bool)
        for k in ("passed", "failed", "errors")
    ):
        return {
            "ok": False,
            "report": None,
            "reason": "子集重验报告缺 summary 或计数非法",
        }
    # 场景覆盖核对：引擎对子集文件每个场景（含异常路径）都产出一条结果，
    # 报告实跑 id 集 MUST 覆盖写入子集文件的场景集且非空，否则按重验失败
    # 回落整轮。
    executed = {
        str(sc.get("scenario_id") or sc.get("id") or "")
        for sc in report.get("scenarios") or []
        if isinstance(sc, dict)
    }
    run_ids = {
        sid for sid, _deps, _raw in (_scenario_view(s) for s in subset) if sid
    }
    if not executed or not run_ids.issubset(executed):
        return {
            "ok": False,
            "report": None,
            "reason": "子集重验报告场景覆盖不全",
        }
    remaining = int(summary.get("failed", 0) or 0) + int(summary.get("errors", 0) or 0)
    return {
        "ok": remaining == 0,
        "report": report,
        "reason": (
            f"子集重验通过（{summary.get('passed', 0)} 场景）"
            if remaining == 0
            else f"子集重验仍有 {remaining} 个非 PASS"
        ),
    }


def dispatch_minor_defect_fastlane(pipeline, spec_name: str, decision: dict) -> dict:
    """fastlane 承接：code-fix 轻量修复任务 → 子集重验 → 收敛/回落。

    Returns:
        {"dispatched": bool, "converged": bool, "reason": str}
        dispatched=True 表示本轮已由 fastlane 承接（调用方 MUST NOT 再走
        bug-found→fix SPEC 整轮派生）；False 表示承接失败/被熔断，调用方
        沿既有整轮路径继续。

    轮次语义：每次 fastlane 修复失败递增 STATE ``_fastlane_fail_streak`` 与
    ``_verify_fail_rounds``（计入既有验证轮预算）；连续
    FASTLANE_MAX_CONSECUTIVE_FAILURES 次失败强制回落整轮（不再发起 fastlane）。
    子集重验通过收敛走 ``_apply_verified``（与整轮 verified 同一收口：门禁
    不豁免），收敛即清零 streak。
    """
    ctx = pipeline._context
    sm = ctx.state_machine

    def _bump_fail_streak(reason: str) -> dict:
        # 锁内原子递增（_bump_counter 同范式的多字段原语）：锁外快照读改写
        # 会与其它对同字段的写者（验证失败记账、admin infra 回拨）互相覆盖
        # 丢增量。
        final = sm.bump_counters(spec_name, {
            FASTLANE_STREAK_FIELD: 1,
            # fastlane 修复失败计入既有验证轮预算（与整轮失败同账）
            "_verify_fail_rounds": 1,
        })
        streak = final.get(FASTLANE_STREAK_FIELD, 0)
        outcome = {
            "dispatched": False,
            "converged": False,
            "reason": reason,
            "streak": streak,
        }
        record_decision(pipeline, spec_name, {
            "eligible": True,
            "path": "full-round",
            "stage": "dispatch-failed",
            "reason": reason,
            "streak": streak,
            "decision_of": decision.get("failed_id"),
        })
        return outcome

    # 连续失败熔断：强制回落整轮（防轻量通道打转）
    entry = sm.read_one(spec_name) or {}
    try:
        streak = int(entry.get(FASTLANE_STREAK_FIELD, 0) or 0)
    except (TypeError, ValueError):
        streak = 0
    if streak >= FASTLANE_MAX_CONSECUTIVE_FAILURES:
        outcome = {
            "dispatched": False,
            "converged": False,
            "reason": (
                f"连续 {streak} 次 fastlane 修复失败，强制回落整轮 fix SPEC 路径"
                f"（已消耗修复轮次计入预算）"
            ),
            "streak": streak,
        }
        record_decision(pipeline, spec_name, {
            "eligible": True,
            "path": "full-round",
            "stage": "streak-circuit-break",
            "reason": outcome["reason"],
            "streak": streak,
        })
        return outcome

    # ① code-fix 轻量修复任务（agents/code-fix.md 车道，主树直接修复）
    failed_id = str(decision.get("failed_id") or "")
    run_id = f"code-fix-fastlane-{spec_name}-{int(time.time())}"
    ctx.logger.info(
        "pm_engine",
        f"fastlane 承接 '{spec_name}': 派发 code-fix 轻量修复 run {run_id}"
        f"（失败场景={failed_id}，影响面={decision.get('affected_files')}）",
    )
    try:
        fix_result = ctx.agent_runner._execute_agent(spec_name, "code-fix", run_id)
    except AttributeError as e:
        # 接线故障（context 未绑定 agent_runner，如桩 context 漏成员）≠ 真实
        # 修复失败：每次 eligible 必然复现、白耗验证轮预算（连续 2 次即熔断
        # 车道），ERROR 级醒目留痕以便与真实修复失败区分排障。
        ctx.logger.error(
            "pm_engine",
            f"fastlane 接线故障 '{spec_name}': ctx.agent_runner 不可用（{e!r}）"
            "——车道无法派发 code-fix，请检查 PipelineContext.agent_runner 绑定",
        )
        return _bump_fail_streak(f"code-fix 轻量修复派发异常: {e!r}（回落整轮）")
    except Exception as e:
        return _bump_fail_streak(f"code-fix 轻量修复派发异常: {e!r}（回落整轮）")
    if not getattr(fix_result, "success", False):
        return _bump_fail_streak(
            f"code-fix 轻量修复失败: {getattr(fix_result, 'error', '')!r}（回落整轮）"
        )

    # ② 子集重验（失败场景 ∪ 前置链 ∪ 下游）
    subset_ids = [str(s) for s in decision.get("subset_ids") or [failed_id] if s]
    # 上一轮全量报告 MUST 在子集重验执行前读取：引擎经 _execute_stage2 会把
    # 仅含子集场景的报告覆写规范路径 report.json（engine._save_report），收敛
    # 时才读会把刚覆写的子集报告误当「上一轮」，carried-over 逻辑永无输入。
    from core.verdict_check import load_report, save_report

    prev_report = load_report(ctx.project_root, spec_name)
    reverify = subset_reverify(pipeline, spec_name, subset_ids)
    if not reverify.get("ok"):
        # 回落整轮前回写上一轮全量报告：子集重验经 _execute_stage2 已把仅含
        # 子集场景的报告覆写规范 report.json，不回写则时间轴与报告消费方读到
        # 失真的 total/passed/failed 直到下一次全量验证（与成功路径 merged
        # 落盘对称）。prev_report 为 None（本就无报告/不可读）按无报告语义
        # 跳过写盘；回写失败不阻断回落记账（整轮验证随后会重写报告）。
        if prev_report is not None:
            try:
                save_report(ctx.project_root, spec_name, prev_report)
            except OSError as e:
                ctx.logger.warning(
                    "pm_engine",
                    f"fastlane 失败回落回写上一轮报告失败 '{spec_name}': {e!r}",
                )
        return _bump_fail_streak(f"fastlane 子集重验未收敛: {reverify.get('reason')}")

    # ③ 收敛：合并报告（未实跑场景沿用上一轮通过结论并标注来源）后先落盘
    #    全量报告（引擎只写子集报告，不回写则 report.json 丢失全部未重验场景
    #    判定）再走既有 verified 收口（_apply_verified 与整轮同一门禁链，修复
    #    diff 不豁免门禁）；落盘失败抛穿由调用点回落整轮，不以残缺报告收敛。
    from types import SimpleNamespace

    merged = merge_subset_report(prev_report, reverify.get("report"))
    merged["fastlane"] = {
        "subset_ids": subset_ids,
        "fix_run_id": run_id,
        "note": "fastlane 子集重验收敛：实跑子集见 scenarios 其余沿用上一轮原判定",
    }
    save_report(ctx.project_root, spec_name, merged)
    sm.update_spec(spec_name, {FASTLANE_STREAK_FIELD: 0})
    # 状态机合法性：bug-found 状态下复用 _apply_verified 的 transition 到
    # verified 是非法转换（VALID_TRANSITIONS：BUG_FOUND 仅允许
    # [IMPLEMENTING, IMPLEMENTED]，转换被拒返回 False 而 _apply_verified 不
    # 检查返回值仍执行 verified 侧副作用——spec 滞留 bug-found 与全绿报告
    # 不一致，收敛落空且后续 full_scan 按 bug-found 再派生整轮 fix）。先走
    # 合法链 bug-found→implemented→testing（与 fix SPEC 整轮生命周期同构：
    # fix 完成 → 重新验证），再复用 _apply_verified 收口（内部
    # testing→verified + 门禁）。transition 返回 False（冻结剥离/非法）不得
    # 假收敛，回落整轮并留痕。
    for _hop in ("implemented", "testing"):
        if not sm.transition(
            spec_name, _hop,
            trigger_run_id=run_id, agent_type="code-fix", channel="auto",
        ):
            return _bump_fail_streak(
                f"fastlane 收敛状态转换 '{spec_name}'→{_hop} 失败（非法/冻结），回落整轮"
            )
    pipeline._apply_verified(
        spec_name, SimpleNamespace(run_id=run_id), merged
    )
    record_decision(pipeline, spec_name, {
        "eligible": True,
        "path": "fastlane-converged",
        "stage": "converged",
        "reason": f"fastlane 修复 + 子集重验通过收敛（subset={subset_ids}）",
        "fix_run_id": run_id,
        "subset_ids": subset_ids,
    })
    return {
        "dispatched": True,
        "converged": True,
        "reason": f"fastlane 收敛（fix run={run_id}，子集={subset_ids}）",
    }
