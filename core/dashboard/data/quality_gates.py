"""core.dashboard.data.quality_gates — 质量门禁读侧合成（add-quality-gates-visibility）。

契约源：spec/changes/add-quality-gates-visibility/specs/quality-gates-progress/spec.md。

- 落盘面（run 内自查 3 项）：implementer 收尾检查渐进写 worktree 内
  ``.fenix/verify-progress/<spec>/quality-gates.json``（顶层 ``{"gates": {...},
  "updated_at": ...}``），run 结束随既有 verify-progress 目录拷回机制落主树。
- 读侧面（本模块）：把 run 内 3 项 + 框架守卫 2 项（result-artifact-gate 按 run
  终态、deliverable-guard 按 STATE 状态，读侧合成不落盘）+ ocr 异步车道产物
  ``code-review.json``（三态 + 指纹校验）合成为统一 6 道门禁状态列表。

fail-open 契约：任何缺失/损坏不抛异常、不产生 error 字段（与 parse_verify_progress
容错语义一致）；历史 spec / 缺数据项显示 unknown 或 pending，不阻塞任何消费方。
键名在本模块逐字固化（历史 impl-code-review-gate 键名漂移事故教训）。
"""

import json
import subprocess
from pathlib import Path

# ── 契约常量（键名固化，禁止同义改写） ─────────────────────────────

# run 内自查 3 项——quality-gates.json 落盘契约的 gate-id 全集与顺序。
# code-review（ocr 代码审查）不在落盘契约之内：实现者 MUST NOT 写该键
# （写了也被读侧忽略），该门由 ocr 异步车道产物读侧合成。
RUN_GATE_IDS = ("full-suite", "frontend-build", "interaction-contract")

# 落盘 status 四值枚举
GATE_STATUSES = ("passed", "failed", "running", "skipped")

# 统一 6 道门禁的契约顺序（详情页勾选列表与进度条按此渲染）
GATE_ORDER = (
    "full-suite",
    "frontend-build",
    "code-review",
    "interaction-contract",
    "result-artifact-gate",
    "deliverable-guard",
)

# 固定中文文案（契约固化，前端不自行翻译）
GATE_DESCS = {
    "full-suite": "全量回归测试",
    "frontend-build": "前端构建与类型检查",
    "code-review": "ocr 代码审查与处置",
    "interaction-contract": "交互契约自查",
    "result-artifact-gate": "结果文件产物硬门",
    "deliverable-guard": "交付物守卫与格式复检",
}

# 交付物守卫 blocked 归因关键词（子串匹配词表；实现时若实际 blocked 归因
# 措辞超出词表，按实际文案扩充并同步测试注入样本）
DELIVERABLE_BLOCKED_KEYWORDS = ("交付物", "deliverable", "dispute", "格式复检")

# STATE 状态进入该集合 → 框架守卫 2 项（result-artifact-gate / deliverable-guard）
# 合成 passed（run 已过产物硬门进入 implemented 及之后状态）
_FRAMEWORK_PASSED_STATUSES = ("implemented", "testing", "verified", "done", "pushed")

# ocr 车道产物（与 quality-gates.json 同目录，车道写、本模块只读）
_LANE_PRODUCT_NAME = "code-review.json"
_GATES_FILE_NAME = "quality-gates.json"


def _int_or_none(v):
    """宽松整数读值：bool 不算 int（防 True 计数）。"""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# ── 双位置候选读取（worktree 优先、主树兜底） ───────────────────────


def _verify_progress_candidates(project_root, spec_name, spec_status: str, filename: str) -> list:
    """按读取策略返回候选路径（implementing 且 worktree 存在时 worktree 优先）。

    「优先」含回退分支：worktree 内无该文件时回退读主树版本（fast-track 等
    持主树 verify-progress 写授权的车道可能直落主树），双位置兜底才不致
    implementing 态漏读。复用 tasks.py 的 worktree 优先先例（D8：经门面解析）。
    """
    cands = []
    if spec_status == "implementing":
        import core.dashboard.data as _facade

        wt = _facade.find_implementer_worktree(project_root, spec_name)
        if wt:
            cands.append(
                Path(wt) / ".fenix" / "verify-progress" / spec_name / filename
            )
    cands.append(
        Path(project_root) / ".fenix" / "verify-progress" / spec_name / filename
    )
    return cands


def _read_json_candidate(candidates: list) -> tuple:
    """读首个存在的候选文件，返回 (数据|None, exists)。

    exists = 文件是否可见（损坏文件同样可见——UI 据此区分「无记录」与「有但坏」）；
    读取/解析失败 data=None，不抛异常。
    """
    for p in candidates:
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        try:
            return json.loads(p.read_text(encoding="utf-8")), True
        except (OSError, ValueError, UnicodeDecodeError):
            return None, True
    return None, False


# ── ocr 车道产物指纹 ───────────────────────────────────────────────


def current_lane_fingerprint(project_root, entry=None) -> "dict | None":
    """当前 spec 的 ``(branch, merge_base, head_commit)`` 三元组指纹。

    branch 取 STATE 条目的 branch 字段；head_commit 为该分支当前指向；
    merge_base 相对主基线分支（main，回退 master）。任一环节不可计算
    （无 branch / 非 git 仓库 / 分支不存在）返回 None——读侧跳过指纹校验
    （fail-open），MUST NOT 因指纹能力缺失隐藏真实产物。
    """
    branch = str((entry or {}).get("branch") or "").strip()
    if not branch:
        return None

    def _git(*args) -> str:
        try:
            out = subprocess.run(
                ["git", "-C", str(project_root), *args],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""

    head = _git("rev-parse", "--verify", branch)
    if not head:
        return None
    merge_base = ""
    for base_ref in ("main", "master"):
        merge_base = _git("merge-base", branch, base_ref)
        if merge_base:
            break
    return {"branch": branch, "merge_base": merge_base, "head_commit": head}


def _lane_fingerprint_ok(product: dict, expected) -> bool:
    """产物指纹是否可采信。

    - 当前指纹不可计算（expected None）→ fail-open 采信；
    - 产物缺 branch/head_commit（未绑定指纹的产物）→ 不采信（车道契约保证
      指纹在场，缺失即形态异常）；
    - 指纹与当前不符（修复轮 head 前移等）→ 不采信 stale 报告。
    """
    if not isinstance(expected, dict):
        return True
    p_branch = str(product.get("branch") or "").strip()
    p_head = str(product.get("head_commit") or "").strip()
    if not p_branch or not p_head:
        return False
    if p_branch != expected.get("branch") or p_head != expected.get("head_commit"):
        return False
    p_mb = str(product.get("merge_base") or "").strip()
    if expected.get("merge_base") and p_mb and p_mb != expected["merge_base"]:
        return False
    return True


def _load_lane_product(project_root, spec_name, spec_status: str, entry: dict):
    """读 ocr 车道产物（worktree 优先、主树兜底 + 指纹校验）。

    返回可采信的产物 dict；不可见 / 损坏 / 指纹陈旧一律 None（按不可见处理）。
    """
    data, exists = _read_json_candidate(
        _verify_progress_candidates(project_root, spec_name, spec_status, _LANE_PRODUCT_NAME)
    )
    if not exists or not isinstance(data, dict):
        return None
    if not _lane_fingerprint_ok(data, current_lane_fingerprint(project_root, entry)):
        return None
    return data


# ── 分门合成 ───────────────────────────────────────────────────────


def _run_gate_detail(raw: dict, gid: str) -> str:
    """run 内项的辅助文案：full-suite 附计数，其余取 reason/detail。"""
    reason = str(raw.get("reason") or raw.get("detail") or "").strip()
    if gid == "full-suite":
        p, f = _int_or_none(raw.get("passed")), _int_or_none(raw.get("failed"))
        if p is not None or f is not None:
            counts = f"通过 {p if p is not None else '?'}，失败 {f if f is not None else '?'}"
            return f"{counts}（{reason}）" if reason else counts
    return reason


def _run_gate_status(raw, gid: str, source_ok: bool = True) -> tuple:
    """run 内 3 项单门状态：契约外键忽略由调用方保证，此处只判单门。

    source_ok=False（文件缺失/损坏，落盘数据源整体不可读）→ unknown；
    文件可读但该 gate-id 未写入（渐进落盘中间态）→ pending。
    """
    if not source_ok:
        return ("unknown", "")
    if raw is None:
        return ("pending", "")
    if not isinstance(raw, dict):
        return ("unknown", "")
    status = raw.get("status")
    if status not in GATE_STATUSES:
        # 枚举外 status（同义改写/笔误）→ unknown 容错渲染，不崩
        return ("unknown", "")
    detail = _run_gate_detail(raw, gid)
    if status == "skipped" and not detail:
        # 契约：skipped MUST 附非空 reason；缺 reason 按 unknown 容错
        return ("unknown", "")
    return (status, detail)


# 框架侧回归产物（.fenix/regression/last-run.json）status → 门状态映射
# （add-impl-selfcheck-model-probe 3.2）。映射外状态（parse_error 等）视为
# 本源异常 → fail-open 逐级回落，MUST NOT 硬译成 unknown。
_FULL_SUITE_PRODUCT_STATUS = {
    "passed": "passed",
    "failed": "failed",
    "timeout": "failed",
    "skipped": "skipped",
    "running": "running",
}


def _full_suite_product_status(project_root) -> tuple:
    """full-suite 门的框架侧产物源：``.fenix/regression/last-run.json``。

    可见性按分支指纹校验（add-impl-selfcheck-model-probe 3.2）：快照带
    ``repo_fingerprint`` 且与当前仓库指纹 (branch, merge_base, head_commit)
    完全一致才可见——存量快照无指纹字段或指纹陈旧（HEAD / merge-base 已
    移动，产物对应旧代码）按不可见。产物缺失 / 损坏 / 当前指纹采集失败 /
    状态映射外 → ``(None, "")`` 表示本源不可用，调用方 fail-open 逐级回落。
    """
    import core.regression as _reg

    data = _reg.read_result(project_root)
    status_raw = data.get("status") if isinstance(data, dict) else None
    if status_raw not in ("passed", "failed", "timeout", "skipped", "running"):
        # never_run / parse_error / 状态映射外 → 本源不可用
        return None, ""
    stamp = data.get("repo_fingerprint")
    if not isinstance(stamp, dict):
        return None, ""  # 存量快照无指纹字段 → 不可见（按 3.2 契约）
    current = _reg.current_repo_fingerprint(project_root)
    if current is None:
        return None, ""  # 当前指纹采集失败 → 新鲜度不可验证 → 不可见
    if (stamp.get("branch"), stamp.get("merge_base"), stamp.get("head_commit")) != (
            current.get("branch"), current.get("merge_base"),
            current.get("head_commit")):
        return None, ""  # 指纹陈旧：产物对应旧 HEAD / merge-base
    status = _FULL_SUITE_PRODUCT_STATUS[status_raw]
    parts = ["框架侧回归产物 .fenix/regression/last-run.json（分支指纹匹配）"]
    p, f = _int_or_none(data.get("passed")), _int_or_none(data.get("failed"))
    if p is not None or f is not None:
        parts.append(f"通过 {p if p is not None else '?'}，失败 {f if f is not None else '?'}")
    if status_raw == "skipped":
        reason = str(data.get("reason") or "").strip()
        if reason:
            parts.append(reason)
    return status, "，".join(parts)


def _full_suite_status(project_root, raw, source_ok: bool = True) -> tuple:
    """full-suite 单门合成，数据源优先级：框架产物 > run 自查值 > pending。

    add-impl-selfcheck-model-probe 3.2：全量回归由验证链执行后，run 内默认
    不写 full-suite 键（3.1 降级措辞）——读侧以框架侧回归产物为首选数据源
    （分支指纹校验新鲜度，结论不一致取产物）；产物不可见时回落 run 内自查
    值（``_run_gate_status`` 既有语义逐字节不变）；双源皆无 → pending。
    任一来源异常 fail-open 逐级回落；键名全集与状态枚举零变化；源缺失
    （缺项/存量无指纹）MUST NOT 产生 unknown——「没跑」如实呈现为 pending。
    """
    status, detail = _full_suite_product_status(project_root)
    if status is not None:
        return status, detail
    return _run_gate_status(raw, "full-suite", source_ok=source_ok)


def _code_review_status(project_root, spec_name, spec_status: str, entry: dict) -> tuple:
    """ocr 门：按 ocr 异步车道产物三态合成（与车道降级不阻塞语义一致）。

    在飞/产物 running → running；completed → passed（detail 附 findings 与
    处置计数摘要）；unavailable → skipped（detail 附 reason，计入 done——已了结
    而非未做）；产物不可见（含损坏/指纹陈旧）→ pending。
    """
    product = _load_lane_product(project_root, spec_name, spec_status, entry)
    if product is None:
        return ("pending", "")
    status = product.get("status")
    if status == "running":
        return ("running", "ocr 并行审查进行中")
    if status == "completed":
        findings = product.get("findings")
        dispositions = product.get("dispositions")
        parts = []
        if isinstance(findings, list):
            parts.append(f"发现 {len(findings)} 条")
        if isinstance(dispositions, list):
            parts.append(f"处置 {len(dispositions)} 条")
        detail = "审查完成：" + "、".join(parts) if parts else "审查完成"
        return ("passed", detail)
    if status == "unavailable":
        reason = str(product.get("reason") or "").strip()
        return ("skipped", reason or "ocr 审查环境不可用")
    # 白名单外 status → unknown 容错
    return ("unknown", "")


def _latest_impl_run(runs: list):
    """最新 impl run（get_runs 已按 mtime 降序；fast-track 同为 implementer 前缀）。"""
    for r in runs or []:
        if isinstance(r, dict) and r.get("agent_type") == "implementer":
            return r
    return None


def _gate_blocked_reason(project_root, run_id: str) -> str:
    """gate-blocked 终态事件的截断归因原文（写侧已截断，读侧原样透出）。"""
    try:
        import core.dashboard.data as _facade

        path = _facade._resolve_run_file(project_root, run_id)
        lines = _facade._read_run_lines(path, max_lines=5)
    except Exception:  # noqa: BLE001 —— fail-open：读不到归因留空
        return ""
    for e in reversed(lines or []):
        if isinstance(e, dict) and e.get("type") == "gate-blocked":
            return str(e.get("error") or e.get("reason") or "").strip()
    return ""


def _result_artifact_gate_status(entry: dict, runs: list, project_root) -> tuple:
    """结果文件产物硬门：权威判定在 run 终态（读侧合成，不落盘）。"""
    st = entry.get("status")
    if st in _FRAMEWORK_PASSED_STATUSES:
        return ("passed", "实现 run 已过结果文件产物硬门")
    impl_run = _latest_impl_run(runs)
    if impl_run is not None and impl_run.get("status") == "gate-blocked":
        reason = _gate_blocked_reason(project_root, str(impl_run.get("run_id") or ""))
        return ("failed", reason or "实现 run 被产物硬门打回")
    if st == "implementing":
        return ("pending", "实现 run 在飞，收尾门禁未了结")
    return ("unknown", "")


def _deliverable_guard_status(entry: dict) -> tuple:
    """交付物守卫与格式复检：权威判定在 STATE 状态（读侧合成，不落盘）。"""
    st = entry.get("status")
    if st in _FRAMEWORK_PASSED_STATUSES:
        return ("passed", "交付物声明对账与格式复检已过")
    if st == "blocked":
        err = str(entry.get("error") or "").strip()
        if err and any(k in err for k in DELIVERABLE_BLOCKED_KEYWORDS):
            return ("failed", err)
        # blocked 但归因未命中交付物词表（预算/env 等）→ 非本门失败，pending
        return ("pending", "SPEC blocked（非交付物归因）")
    if st == "implementing":
        return ("pending", "实现 run 在飞，收尾门禁未了结")
    return ("unknown", "")


def _gates_current(items: list) -> str:
    """当前进展文案：running 优先，其次 failed 归因；全了结为空串。"""
    for it in items:
        if it["status"] == "running":
            return f"{it['desc']}：进行中"
    for it in items:
        if it["status"] == "failed":
            extra = f"（{it['detail']}）" if it["detail"] else ""
            return f"{it['desc']}：未通过{extra}"
    return ""


def parse_quality_gates(project_root, spec_name: str, entry=None, runs=None) -> dict:
    """门禁状态解析合成（fail-open）：输入 spec 名，输出统一 6 道门列表。

    返回 ``{exists, done, total, current, items: [{id, desc, status, detail}]}``：

    - exists：quality-gates.json 是否可见（worktree 优先/主树兜底；损坏文件
      同样可见——UI 区分「无记录」与「有但坏」）；
    - items 恒 6 道、顺序同 GATE_ORDER；run 内 3 项取落盘文件，code-review 取
      ocr 车道产物，框架 2 项按 run 终态/STATE 合成；
    - done = passed + skipped 数（skipped 表示该门已了结），total = 6；
    - runs：调用方预扫描的 run 记录列表（spec_summary 传入避免重复扫描）；
      缺省时自行扫描（详情页路径）。
    """
    entry = entry or {}
    spec_status = str(entry.get("status") or "")
    file_data, exists = _read_json_candidate(
        _verify_progress_candidates(project_root, spec_name, spec_status, _GATES_FILE_NAME)
    )
    file_gates = {}
    parsed = isinstance(file_data, dict)
    if parsed:
        gates_raw = file_data.get("gates")
        if isinstance(gates_raw, dict):
            file_gates = gates_raw
    if runs is None:
        import core.dashboard.data as _facade

        runs = _facade.get_runs(project_root, spec_name, include_archive=True)
    items = []
    for gid in GATE_ORDER:
        if gid in RUN_GATE_IDS:
            # 契约外 gate-id（含实现者误写的 code-review 键）天然不在
            # RUN_GATE_IDS 遍历面内 → 忽略，不污染合成。
            # full-suite 走双源优先级合成（add-impl-selfcheck-model-probe 3.2），
            # 其余 run 内项维持 _run_gate_status 单源语义。
            if gid == "full-suite":
                status, detail = _full_suite_status(
                    project_root, file_gates.get(gid), source_ok=parsed)
            else:
                status, detail = _run_gate_status(
                    file_gates.get(gid), gid, source_ok=parsed)
        elif gid == "code-review":
            status, detail = _code_review_status(project_root, spec_name, spec_status, entry)
        elif gid == "result-artifact-gate":
            status, detail = _result_artifact_gate_status(entry, runs, project_root)
        else:
            status, detail = _deliverable_guard_status(entry)
        items.append({"id": gid, "desc": GATE_DESCS[gid], "status": status, "detail": detail})
    done = sum(1 for it in items if it["status"] in ("passed", "skipped"))
    return {
        "exists": exists,
        "done": done,
        "total": len(GATE_ORDER),
        "current": _gates_current(items),
        "items": items,
    }
