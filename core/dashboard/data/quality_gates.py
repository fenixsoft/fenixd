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
import time
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

# pending/unknown 兜底归因文案（fix-quality-gates-flat-form-and-explainability
# 2.1，契约源 spec/changes/fix-quality-gates-flat-form-and-explainability/
# specs/quality-gates-explainability/spec.md）：六道门合成后对 status 为
# pending/unknown 且 detail 为空串的门项填充固定归因文案，UI 不再出现无解释的
# 未勾选项。已有非空 detail 原样保留（不覆盖），status 与 done 计数不变；
# 文案经既有前端 detail 透传链（gateDetailText）渲染，前端零改动。
PENDING_FALLBACK_DETAIL = "该门未了结（run 在飞或自查结果未落盘）"
UNKNOWN_FALLBACK_DETAIL = "门禁记录缺失或损坏"

# ocr 车道总开关关闭归因文案（fix-quality-gates-ocr-disabled-na）：设置关闭
# （verify.impl_code_review，用户级+项目级合并）后车道不再启动、code-review.json
# 永不产生，此前合成 pending 落兜底文案「该门未了结」归因错误——关闭时合成
# skipped（计入 done，与 unavailable 同口径），detail 固定归因设置。键名入
# 文案（契约固化，禁止同义改写）。
_OCR_DISABLED_BY_SETTING_REASON = "已在设置中关闭收尾代码质量审查（verify.impl_code_review）"

# STATE 状态进入该集合 → 框架守卫 2 项（result-artifact-gate / deliverable-guard）
# 合成 passed（run 已过产物硬门进入 implemented 及之后状态）
_FRAMEWORK_PASSED_STATUSES = ("implemented", "testing", "verified", "done", "pushed")

# ocr 车道产物（与 quality-gates.json 同目录，车道写、本模块只读）
_LANE_PRODUCT_NAME = "code-review.json"
_GATES_FILE_NAME = "quality-gates.json"

# full-suite 门终态豁免（fix-quality-gates-terminal-blindspot 2.1）：
# spec 进入终态后 main 持续前进，框架回归产物指纹必然陈旧不可见，且
# add-impl-selfcheck-model-probe 3.1 后实现者默认不写 full-suite 自查键
# ——终态 SPEC 该门恒 pending 语义错误（回归跟踪责任已移交主树）。
# 终态集合与 _FRAMEWORK_PASSED_STATUSES 有意不同：implemented/testing 仍在
# 流水线内（可能修复轮、回归重跑），显示实时状态；verified 起进入收尾。
# 键名/文案固化惯例，禁止同义改写。
_TERMINAL_EXEMPT_STATUSES = ("verified", "done", "pushed")
_TERMINAL_EXEMPT_REASON = "SPEC 已终态，全量回归跟踪移交主树"


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
    # 拦截形如选项的取值（code-review item a2dd5c66d44f）：branch 源自可手工
    # 编辑的 STATE 条目，以 - 开头会被 git 当 flag 解析（ref 命名规则本就
    # 禁止 - 开头，拦截零误伤）→ 与无 branch 同路 fail-open 返回 None
    if not branch or branch.startswith("-"):
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

    指纹字段形态兼容（add-timeline-ocr-lane-visibility 修复轮）：真实车道
    产物（run_impl_ocr 写侧）把指纹嵌套在 ``fingerprint`` 子对象，历史
    手工/测试产物平铺在顶层——嵌套形态此前被误判「未绑定指纹」恒不采信，
    completed 产物永远回落 pending，翻转回落语义在真实产物下不可达。

    merge-back 豁免（fix-quality-gates-terminal-blindspot 1.1）：当前指纹
    ``merge_base == head_commit``（均非空）即分支尖已是主基线祖先 = 分支已
    完整合入——merge-back 后 ``git merge-base <branch> main`` 构造性前移到
    分支尖自身，与产物记录的评审基线（merge-back 前的 merge-base）必然不
    等，此前被判 stale 致已 completed 审查恒 pending（结构性必现：任何成功
    push 的 spec 该门恒 pending）。此形态下产物 merge_base 是历史事实而非
    陈旧，跳过该项比对；豁免不覆盖 branch/head_commit（修复轮 head 前移的
    重审拒采信语义不变），分支未合入路径逐字节不变。
    """
    if not isinstance(expected, dict):
        return True
    fp = product.get("fingerprint")
    src = fp if isinstance(fp, dict) else product
    p_branch = str(src.get("branch") or "").strip()
    p_head = str(src.get("head_commit") or "").strip()
    if not p_branch or not p_head:
        return False
    if p_branch != expected.get("branch") or p_head != expected.get("head_commit"):
        return False
    cur_mb = str(expected.get("merge_base") or "").strip()
    cur_head = str(expected.get("head_commit") or "").strip()
    if cur_mb and cur_head and cur_mb == cur_head:
        return True  # merge-back 豁免：仅跳过 merge_base 比对，branch/head 已全等
    p_mb = str(src.get("merge_base") or "").strip()
    if expected.get("merge_base") and p_mb and p_mb != expected["merge_base"]:
        return False
    return True


# ocr 车道指纹短 TTL 缓存（code-review item f3efcd5eff76）：current_lane_fingerprint
# 每次调用 1 次 rev-parse + 至多 2 次 merge-base 子进程（各 15s 超时），而
# _load_lane_product 在 parse_quality_gates 内对每个 spec 各调一次——与下方
# full-suite 指纹（_FINGERPRINT_CACHE，共用其 TTL/容量常量）同型热路径，同款
# 模块级 memo：TTL 内 head 移动的门禁可见性延迟至多一个 TTL（同一既有假设）。
# 公共 current_lane_fingerprint 本身保持无缓存：测试与外部直接调用依赖
# 「merge 后重取即新值」语义（mergeback 用例同参重取断言）。
_LANE_FINGERPRINT_CACHE: dict = {}


def _cached_lane_fingerprint(project_root, entry):
    """``current_lane_fingerprint`` 的短 TTL memo，键 (project_root, branch)。"""
    branch = str((entry or {}).get("branch") or "").strip()
    if not branch:
        # 空 branch 原函数短路返回 None（不拉子进程），透传不占缓存
        return current_lane_fingerprint(project_root, entry)
    key = (str(project_root), branch)
    now = time.monotonic()
    hit = _LANE_FINGERPRINT_CACHE.get(key)
    if hit is not None and now - hit[0] < _FINGERPRINT_CACHE_TTL_SECONDS:
        return hit[1]
    fp = current_lane_fingerprint(project_root, entry)
    if len(_LANE_FINGERPRINT_CACHE) >= _FINGERPRINT_CACHE_MAX:
        _LANE_FINGERPRINT_CACHE.clear()
    _LANE_FINGERPRINT_CACHE[key] = (now, fp)
    return fp


def _load_lane_product(project_root, spec_name, spec_status: str, entry: dict):
    """读 ocr 车道产物（worktree 优先、主树兜底 + 指纹校验）。

    返回可采信的产物 dict；不可见 / 损坏 / 指纹陈旧一律 None（按不可见处理）。
    """
    data, exists = _read_json_candidate(
        _verify_progress_candidates(project_root, spec_name, spec_status, _LANE_PRODUCT_NAME)
    )
    if not exists or not isinstance(data, dict):
        return None
    if not _lane_fingerprint_ok(data, _cached_lane_fingerprint(project_root, entry)):
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


def _ocr_lane_inflight(runs: list) -> bool:
    """ocr 车道在飞判据（add-timeline-ocr-lane-visibility 任务 1.3）。

    runs（get_runs 产物）中存在 run_id 前缀 ``impl-ocr-`` 且无终态事件的
    run 即在飞：车道 jsonl 启动写 ``start``、收尾写 ``result``/``error``，
    无终态即 in-flight——与既有 no-terminal→running 判定同约定（读侧合成
    status 为 running/empty；stale 是 mtime 兜底的断尾弃置，非真实在飞，
    不计）。runs 缺省（None）不判在飞（fail-open 落回产物状态）。
    """
    for r in runs or []:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("run_id") or "")
        if rid.startswith("impl-ocr-") and r.get("status") in ("running", "empty"):
            return True
    return False


# 车道总开关读侧缓存（fix-quality-gates-ocr-disabled-na）：parse_quality_gates
# 热路径（每 spec 每次刷新各一次），resolve_config 是 O(YAML)——经
# summary._cached_config_value 公共流程（（用户级+项目级）config.yaml 双签名
# 键，写后自然失效），parse 只取 verify.impl_code_review 一个 bool。
_OCR_SWITCH_CACHE: dict = {}
_OCR_SWITCH_CACHE_MAX = 64


def _impl_ocr_enabled_cached(project_root) -> bool:
    """``verify.impl_code_review`` 有效开关（D8 经门面引用公共缓存流程）。"""
    import core.dashboard.data as _facade
    from core.config import ConfigLoader

    # 公开访问面（code-review item 20ad589a3bc4）：不跨组消费下划线私有名
    return _facade.cached_config_value(
        project_root, _OCR_SWITCH_CACHE, _OCR_SWITCH_CACHE_MAX,
        ConfigLoader.get_impl_code_review_enabled)


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


# 仓库指纹短 TTL 缓存（code-review item f10216997ee3）：current_repo_fingerprint
# 每次调用最多拉起 3 个 git 子进程（各 10s 超时），而 parse_quality_gates 在一次
# /api/specs 刷新内对每个 spec 各合成一次门禁（spec_detail 每请求两次 + SSE 重
# 推）——无缓存时热读路径每次请求拉起数十个 git 子进程。与 runs.py 的
# _RUN_META_CACHE 同款模块级 memo：TTL 内同 project_root 复用一次采集，代价是
# HEAD 恰在移动的边界场景下门禁可见性延迟至多一个 TTL（指纹新鲜度本就按
# 「刷新窗口内一致」语义消费）。
_FINGERPRINT_CACHE: dict = {}
_FINGERPRINT_CACHE_TTL_SECONDS = 5.0
_FINGERPRINT_CACHE_MAX = 64


def _cached_repo_fingerprint(project_root):
    """``current_repo_fingerprint`` 的短 TTL memo（见上方缓存说明）。"""
    key = str(project_root)
    now = time.monotonic()
    hit = _FINGERPRINT_CACHE.get(key)
    if hit is not None and now - hit[0] < _FINGERPRINT_CACHE_TTL_SECONDS:
        return hit[1]
    import core.regression as _reg

    fp = _reg.current_repo_fingerprint(project_root)
    if len(_FINGERPRINT_CACHE) >= _FINGERPRINT_CACHE_MAX:
        _FINGERPRINT_CACHE.clear()
    _FINGERPRINT_CACHE[key] = (now, fp)
    return fp


def _full_suite_product_status(project_root) -> tuple:
    """full-suite 门的框架侧产物源：``.fenix/regression/last-run.json``。

    可见性按分支指纹校验（add-impl-selfcheck-model-probe 3.2）：快照带
    ``repo_fingerprint`` 且与当前仓库指纹 (branch, merge_base, head_commit)
    完全一致才可见——存量快照无指纹字段或指纹陈旧（HEAD / merge-base 已
    移动，产物对应旧代码）按不可见。产物缺失 / 损坏 / 当前指纹采集失败 /
    状态映射外 → ``(None, "")`` 表示本源不可用，调用方 fail-open 逐级回落。
    """
    import core.regression as _reg

    # read_result 只捕 JSONDecodeError/OSError（regression.py:366），快照含
    # 无效 UTF-8 时 read_text 抛 UnicodeDecodeError 穿透（regression.py
    # :312-315 同源实证）——在此原地降级返回 (None, "")，兑现本模块
    # fail-open 契约（code-review item 55b059d3c256），走既有逐级回落。
    try:
        data = _reg.read_result(project_root)
    except Exception:
        return None, ""
    # 定向子集快照不可见（add-regression-issues-rerun 4.1，D6）：快照为
    # dict 且 run_scope == "issues" → 按本源不可见返回 (None, "")——否则
    # 「子集 passed」会把 full-suite 门洗成 passed（与空场景白洗通道同类
    # 洞）。判定置于 status 白名单之前（子集快照无论什么状态都不采信）；
    # 本源不可见沿用既有 fail-open 逐级回落（回落 run 自查值），MUST NOT
    # 抛异常。
    if isinstance(data, dict) and data.get("run_scope") == "issues":
        return None, ""
    status_raw = data.get("status") if isinstance(data, dict) else None
    if status_raw not in _FULL_SUITE_PRODUCT_STATUS:
        # never_run / parse_error / 状态映射外 → 本源不可用（成员判定直接
        # 对映射做——白名单字面量与键集双写会漂移，code-review item 75e44244301c）
        return None, ""
    stamp = data.get("repo_fingerprint")
    if not isinstance(stamp, dict):
        return None, ""  # 存量快照无指纹字段 → 不可见（按 3.2 契约）
    current = _cached_repo_fingerprint(project_root)
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


def _full_suite_status(
    project_root, raw, source_ok: bool = True, spec_status: str = ""
) -> tuple:
    """full-suite 单门合成，数据源优先级：终态豁免 > 框架产物 > run 自查值 > 既有回落。

    fix-quality-gates-terminal-blindspot 2.1：spec status ∈ 终态集合时短路
    返回 skipped（固定文案，计入 done）——终态显示语义确定性，优先级高于
    框架产物源，不随后续 main 推进/回归重跑摆动；非终态数据源优先级与
    逐字节行为不变。

    add-impl-selfcheck-model-probe 3.2：全量回归由验证链执行后，run 内默认
    不写 full-suite 键（3.1 降级措辞）——读侧以框架侧回归产物为首选数据源
    （分支指纹校验新鲜度，结论不一致取产物）；产物不可见时回落 run 内自查
    值（``_run_gate_status`` 既有语义逐字节不变：文件可读键缺 → pending，
    文件整体缺失/损坏 → unknown 既有语义，键名全集与状态枚举零变化）。
    产物侧的缺失/损坏/存量无指纹/指纹陈旧/状态映射外均 fail-open 逐级回落，
    不向落盘面注入新的失败终态。
    """
    if str(spec_status or "").strip() in _TERMINAL_EXEMPT_STATUSES:
        return ("skipped", _TERMINAL_EXEMPT_REASON)
    status, detail = _full_suite_product_status(project_root)
    if status is not None:
        return status, detail
    return _run_gate_status(raw, "full-suite", source_ok=source_ok)


def _code_review_status(
    project_root, spec_name, spec_status: str, entry: dict, runs: list | None = None
) -> tuple:
    """ocr 门：按 ocr 异步车道产物三态合成（与车道降级不阻塞语义一致）。

    车道总开关关闭（verify.impl_code_review，fix-quality-gates-ocr-disabled-na）
    → skipped（detail 归因设置，计入 done——设置性不适用而非未了结），优先级
    最高：关闭后车道不再启动、产物不再产生，在飞判据与三态合成整体跳过。
    车道在飞（活跃 impl-ocr run 无终态事件）/产物 running → running；
    completed → passed（detail 附 findings 与处置计数摘要）；unavailable →
    skipped（detail 附 reason，计入 done——已了结而非未做）；产物不可见
    （含损坏/指纹陈旧）→ pending。在飞判据优先于磁盘产物状态（重审轮
    head 前移后上一轮产物指纹陈旧，本就不可采信）。
    """
    if not _impl_ocr_enabled_cached(project_root):
        return ("skipped", _OCR_DISABLED_BY_SETTING_REASON)
    if _ocr_lane_inflight(runs):
        return ("running", "ocr 并行审查进行中")
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

        # runs 组公开访问面（runs.py resolve_run_file/read_run_lines 单源绑定），
        # 不跨组消费下划线私有名（code-review item 8a5f26099241）
        path = _facade.resolve_run_file(project_root, run_id)
        lines = _facade.read_run_lines(path, max_lines=5)
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


def _adopt_flat_form(file_data: dict) -> dict:
    """平铺形态容错判定（fix-quality-gates-flat-form-and-explainability 1.1，
    契约源 specs/quality-gates-form-tolerance/spec.md）。

    落盘契约的合法形态仍是嵌套 ``{"gates": {...}}``；历史事故中实现者把门
    条目直接平铺在顶层（漏了包裹层），读侧取 ``gates`` 落空后把已通过的门
    全部判 pending（结论丢失）。本函数仅在 ``gates`` 键缺失或非 dict 时由
    parse_quality_gates 调用，判定规则：

    - 候选门集 = 顶层所有「值为 dict 且 ``status`` ∈ GATE_STATUSES」的键
      （字符串型元数据键如 ``updated_at`` 非 dict，天然忽略）；
    - 候选门集非空，且顶层不存在「值为 dict 但 status 枚举外或缺 status」
      的键 → 采信，候选门集即 file_gates；
    - 存在任一枚举外 dict 值，或候选集为空 → 返回空 dict 不采信（宁可维持
      既有 pending/unknown 语义，不误读半个文件）。

    采信产物直接作为 file_gates 进入既有下游（契约外 gate-id 忽略、
    ``_run_gate_status`` 单门判定、full-suite 双源优先级），与嵌套路径
    逐字节一致。平铺为读侧兼容而非合法写法——写侧偏离契约的事实由
    result_gate 宽松对账告警（quality-gates-form-drift）让人工可见，
    落盘契约文本不变。
    """
    candidates = {}
    for key, value in file_data.items():
        if not isinstance(value, dict):
            continue  # 字符串型元数据键（updated_at 等）忽略
        if value.get("status") not in GATE_STATUSES:
            return {}  # status 枚举外或缺 status 的 dict 值 → 整体不采信
        candidates[key] = value
    return candidates


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
            # 嵌套形态（唯一合法写法，含空 gates dict）——平铺判定不参与，
            # 读侧行为与本变更前逐字节一致。
            file_gates = gates_raw
        else:
            # 平铺形态容错（fix-quality-gates-flat-form-and-explainability
            # 1.1）：gates 键缺失或非 dict 时尝试按顶层平铺采信；不采信时
            # 仍为空 dict，维持既有 pending/unknown 语义。损坏文件
            # （file_data=None）走不到此分支，unknown 语义不变。
            file_gates = _adopt_flat_form(file_data)
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
                    project_root, file_gates.get(gid), source_ok=parsed,
                    spec_status=spec_status)
            else:
                status, detail = _run_gate_status(
                    file_gates.get(gid), gid, source_ok=parsed)
        elif gid == "code-review":
            status, detail = _code_review_status(
                project_root, spec_name, spec_status, entry, runs
            )
        elif gid == "result-artifact-gate":
            status, detail = _result_artifact_gate_status(entry, runs, project_root)
        else:
            status, detail = _deliverable_guard_status(entry)
        items.append({"id": gid, "desc": GATE_DESCS[gid], "status": status, "detail": detail})
    done = sum(1 for it in items if it["status"] in ("passed", "skipped"))
    # pending/unknown 兜底归因文案（2.1）：组装后的单点后处理，只填空不覆盖
    # ——六道门来源不同（落盘/ocr 车道/框架守卫），收口在此保证语义一目了然，
    # 新增门来源时自动获得兜底；status 与 done 计数不变。
    for it in items:
        if it["status"] == "pending" and not it["detail"]:
            it["detail"] = PENDING_FALLBACK_DETAIL
        elif it["status"] == "unknown" and not it["detail"]:
            it["detail"] = UNKNOWN_FALLBACK_DETAIL
    return {
        "exists": exists,
        "done": done,
        "total": len(GATE_ORDER),
        "current": _gates_current(items),
        "items": items,
    }
