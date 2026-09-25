"""code_fix — 自动修复编排车道（add-code-review-auto-fix design D2-D8）。

把代码审查台账（`.fenix/code-review/items.jsonl`）的 `open` 条目按
`admin.code_review_fix.batch_size`（缺省 20）分批，每批派一次 `code-fix`
agent run 在独立 worktree 内修复并提交；框架在该 worktree 上跑全量回归，
通过才 `merge_back` 主树并把该批条目置 `resolved`（`mark_resolved`），
随后自驱动再投递 `checkpoint()` 处理下一批，直至无 `open` 条目。

两路激活（D4）：审查 run 收尾（`run_code_review` 的 inserted>0 时经
`runner._code_fix_orchestrator`）+ 30 分钟 full scan 兜底
（`event_bus._run_full_scan_body` 末尾经 `code_fix_orchestrator`）。
两路汇入同一入口 `CodeFixOrchestrator.checkpoint()`，幂等守卫链保证
同一时刻至多一个 code-fix run。

调度解耦不变量（decouple-codefix-review-lanes Requirement 1）：批派发与
链推进的判据集合**不含**「周期审查 run 在飞」——checkpoint 守卫链
（enabled/单飞/无 open 条目/WIP 预检/回归契约）没有审查在飞否决或等待
条件（09-24 取证定案，证据见
`docs/help/codefix-review-lane-decoupling.md`）；与审查的真实资源冲突点
（回归主机级套件锁）由既有锁自然串行。链自驱动推进语义对所有批收尾路径
成立，含延迟批（defer）合回路径——批收尾 wip_gate_blocked 走
`_defer_merge_back` 返回 `consumed` 照常 `_resubmit`；延迟台账合回成功在
`checkpoint` 内联核销后同一次调用继续选批投递（等价 `success` 收尾推进）。

契约要点（design「契约要点」节，实现者必读）：
- **绝不空集合回**：批内零有效产物行或零有效修复（产物行全 skipped /
  worktree 分支相对建树点无提交）→ MUST NOT 合回、MUST NOT 置 resolved
  （`merge_back` 对「分支已是 HEAD 祖先」返回成功，无守卫会把全 skipped
  的批白洗成 resolved）。
- **resolved 只能由合回成功驱动**；skipped 条目保持 open。
- **批失败自愈（add-code-fix-batch-failure-selfheal）**：批收尾三态
  `success`/`consumed`/`halt`——`success` 与 `consumed`（条目已离开可选池）
  均自驱动推进下一批，仅 `halt`（环境性失败）终止链。确定性失败（两次回归
  均失败/合回冲突）现场即弃：branch/tip_sha 入 `.fenix/code-review/
  fix-failed.json` 失败档案（记录带 `fail_count` 自动重试预算）后清理
  worktree 释放锁；新链启动自动释放 `fail_count < FAIL_RETRY_MAX` 的记录
  （打标墓碑不删除，fail_count 跨链续增，下轮自动重试），达上限永久跳过
  并一次性告警 + todo.md 登记待人工。
  瞬态失败（agent run 失败/重试 run 失败/零有效修复）只进进度快照
  `chain_skipped`（链内跳过，新链启动重置），不烧跨轮重试预算。
"""

import calendar
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from core.code_review import (  # noqa: F401
    _atomic_write,
    _now_iso,
    _read_items_unlocked,
    _with_lock,
    fingerprint,
    items_path,
    mark_ignored,
    mark_resolved,
    read_items,
)
from core.config import ConfigLoader
from core.verify_contract import load_verify_contract

# 进度快照（单文件覆盖式，与 .fenix/regression/last-run.json 同型，D8）
FIX_PROGRESS_REL = ".fenix/code-review/fix-progress.json"
# 失败批档案（确定性失败：两次回归均失败/合回冲突；带 fail_count 自动重试
# 预算，新链启动自动释放预算内记录——add-code-fix-batch-failure-selfheal D3）
FIX_FAILED_REL = ".fenix/code-review/fix-failed.json"
# 延迟合回台账（fix-codefix-wipgate-defer D2）：wip_gate_blocked 批的现场
# 保留记录。独立文件、独立生命周期——失败档案烧预算期待重跑，defer 队列零
# 预算期待原地合回，混写会让释放逻辑误伤 defer 条目。
DEFERRED_REL = ".fenix/code-review/fix-deferred.json"

# 失败档案自动重试预算上限（selfheal D3）：同条目集 fail_count 递增至本值的
# 那次入档发一次性 warning 告警并登记 todo 待人工项，此后不再自动重试。
# 模块常量、不新增配置键（预算语义无需按项目调节）。
FAIL_RETRY_MAX = 3

# 延迟批预算双门（fix-codefix-wipgate-defer D6，先到为准）：first_deferred_at
# 起超过 90 分钟，或链边界重试仍被阻断使 defer_count 递增达 6。时间门兜住
# 「链停摆很久后才恢复」的陈旧 defer；次数门兜住「主树反复变脏」的抖动。
DEFER_BUDGET_SECONDS = 90 * 60
DEFER_RETRY_MAX = 6

# LLM 拒绝出口（2026-09-23）：产物行 skipped 且显式标注这些 skip_reason 的
# 条目置台账终态 ignored（mark_ignored），不再跨链重修。其余 skipped（无标注
# 缺省 / unfixable / needs_human）维持既有语义（open + 链内跳过，跨链可重试）
# ——缺省保守：必须显式声明「误报/不值得修」才走硬出口，防 LLM 轻率清账。
IGNORE_ELIGIBLE_SKIP_REASONS = {"false_positive", "not_worth_fixing"}

# 进度缺省态（读侧缺文件/损坏时返回，MUST NOT 抛异常）
FIX_PROGRESS_DEFAULT = {
    "running": False,
    "phase": "idle",
    "total": 0,
    "done": 0,
    "current": "",
    "batch_no": 0,
    "reason": "",
    "activation_id": "",
    # 手动授权旗标（随链身份持久化）：True 表示本链由手动触发授权，自驱动
    # 再投递（_resubmit → checkpoint 无 override）凭它越过 enabled 总开关。
    # 仅在链 live（running=true）时被消费；终态（idle/blocked/failed）清除。
    "manual_authorized": False,
    # 批上下文（add-code-fix-item-level-progress D2）：本批 worktree 绝对路径
    # /run_id/批条目数。编排器在建树成功后、agent run 启动前写入（run_id 预
    # 生成并经 run_code_fix 既有 run_id 形参传入）；批收尾清除。白名单合并
    # 语义要求新键 MUST 进本缺省集（缺省 null），否则读侧不可见、且会被下
    # 一次合并写剥离（先例：manual_authorized）。
    "worktree": None,
    "run_id": None,
    "batch_total": None,
    # 条级进度合成字段（D1，读侧实时派生）：read_progress 每次读时经
    # read_fix_out 现算，write_progress 会剥离、不落盘（避免陈旧快照被合并
    # 写持久化成误导性数字）。null 三态语义见 _synthesize_item_progress。
    "item_done": None,
    "current_item": None,
    # 启动阶段合成字段（add-code-fix-startup-stage-visibility D1，读侧实时
    # 派生）：批处于 fixing/retrying 且 out 零有效行时，读 run 转录末行事件
    # 类型推断 agent 启动阶段。同一剥离纪律（write_progress 不落盘）——合
    # 成快照经合并写持久化会在批收尾后残留陈旧阶段文案。null 三态语义见
    # _synthesize_startup_stage。
    "startup_stage": None,
    # 链内跳过集（add-code-fix-batch-selfheal）：本链因瞬态失败（agent run
    # 失败/重试 run 失败/零有效修复）被跳过的条目 id。select_batch 排除口径
    # = 失败档案并集 ∪ 本字段；新链启动（activation_id 更替）时重置为空。
    "chain_skipped": [],
}

# phase 合法值（spec code-fix-progress）
FIX_PHASES = (
    "idle",
    "selecting",
    "fixing",
    "regressing",
    "retrying",
    "merging",
    "blocked",
    "failed",
)


def _progress_path(project_root) -> Path:
    return Path(project_root) / FIX_PROGRESS_REL


def _failed_path(project_root) -> Path:
    return Path(project_root) / FIX_FAILED_REL


def _atomic_write(path: Path, content: str) -> None:
    """临时文件 + os.replace 原子写（对齐 core.code_review._atomic_write）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def read_progress(project_root) -> dict:
    """读取进度快照；缺失/损坏返回缺省态（不抛异常，spec code-fix-progress）。

    返回 dict 的字段集与 FIX_PROGRESS_DEFAULT 一致（缺字段补齐），调用方
    可安全取键。

    条级进度（add-code-fix-item-level-progress）：``running=true`` 且批上下
    文在场时，经 ``read_fix_out`` 实时合成 ``item_done``/``current_item``
    （见 ``_synthesize_item_progress``）；其余场景两键为 null。

    启动阶段（add-code-fix-startup-stage-visibility）：在条级合成之后、
    复用其已读出的 out 行集合激活域互补合成 ``startup_stage``（out 有行时
    短路 null，不重复 IO）。
    """
    out = dict(FIX_PROGRESS_DEFAULT)
    # 可变缺省字段显式拷贝（code-review item d8f3e5cef688）：chain_skipped 是
    # list，浅拷贝会让所有缺省态调用方共享同一对象——未来任何一处就地 append
    # 都会污染进程级缺省态，使链内跳过集跨链/跨项目泄漏。每次读返回新列表。
    out["chain_skipped"] = list(FIX_PROGRESS_DEFAULT["chain_skipped"])
    try:
        raw = _progress_path(project_root).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        rows = _synthesize_item_progress(project_root, out)
        _synthesize_startup_stage(project_root, out, rows)
        return out
    if isinstance(data, dict):
        for k in FIX_PROGRESS_DEFAULT:
            if k in data:
                out[k] = data[k]
    rows = _synthesize_item_progress(project_root, out)
    _synthesize_startup_stage(project_root, out, rows)
    return out


def write_progress(project_root, **fields) -> dict:
    """合并式原子写进度（读-改-写：未传字段保留现值，缺省态兜底）。

    幂等安全：进度文件不存在时从缺省态起改。返回写盘后的完整进度。
    """
    current = read_progress(project_root)
    # 条级合成字段是读侧实时派生值，MUST NOT 落盘：合并基线来自
    # read_progress（已含现算结果），剥离后交由后续读侧重算，避免陈旧快照
    # 被合并写持久化成误导性数字（add-code-fix-item-level-progress D1）。
    current.pop("item_done", None)
    current.pop("current_item", None)
    # 启动阶段同纪律（add-code-fix-startup-stage-visibility D1）：批收尾后
    # 进度文件若残留陈旧阶段文案，前端会在非准备期误渲染。
    current.pop("startup_stage", None)
    current.update(fields)
    _atomic_write(
        _progress_path(project_root),
        json.dumps(current, ensure_ascii=False, indent=2),
    )
    return current


def _preset_run_id(runner, exclude=()) -> str:
    """预生成 code-fix run_id（与 run_code_fix 缺省生成同口径，task 2.1）。

    编排器在建树成功后、投递 run 前调用：只有预生成才能在 run 启动**前**
    把 run_id 写进进度文件（run 在飞期间读侧即可据此定位 out 文件）；随后
    经 ``run_code_fix(..., run_id=...)`` 传入，run 内部不再自行生成。
    保持 ``code-fix-`` 前缀并按 ``_unique_code_fix_run_id`` 同口径去重（对
    ``_running_agents`` 在飞集 + 主树 out 残留退避）——``_code_fix_running``
    在途判据依赖该前缀。``exclude`` 为本批已 issued 的 run_id 禁用集（重试
    轮传入首轮 run_id：重试产物落同一 worktree，主树残留判据覆盖不到，同
    秒撞名会复用首轮 out 文件、破坏「重试独立文件并集」口径）。函数级
    import 规避装载环（maintenance_runs 属 agent_runner 侧，不反向依赖本
    模块）。
    """
    from core.agent_runner.maintenance_runs import _unique_code_fix_run_id

    return _unique_code_fix_run_id(runner, exclude=exclude)


def _synthesize_item_progress(project_root, progress: dict) -> None:
    """条级进度实时合成（add-code-fix-item-level-progress D1/D3/D4）。

    D5 实证结论（task 1.1；观察方法：最小夹具批 2 条 item，stub `_run_claude`
    模拟 agent 逐条 append+flush 驱动真实 `run_code_fix`，在 run 期间与收尾
    后分别探测 `<worktree>/.fenix/code-review/fix-out-<run_id>.jsonl` 的存在
    性与行数）：
    - out 目录由 `run_code_fix` 在 run 启动时即创建（maintenance_runs
      `out_path.parent.mkdir`），先于 agent 首条处置；
    - agent 逐条追加的每一行在 run 在飞期间即可被 `read_fix_out` 读到
      （实证 mid-run 探测可见行数 1→2 逐条递增）；
    - run 收尾返回后、worktree cleanup 之前文件完整在场。
    故「run 在飞期间实时合成」的路径假设成立；worktree cleanup 后读不到
    out 属预期（批已收尾、批上下文已清，条级字段让位）。

    容错语义（D4 null 三态）：`running != true`、批上下文缺失、out 缺失/
    零有效行、`read_fix_out` 任何异常 → `item_done`/`current_item` 均置
    null（MUST NOT 500、MUST NOT 回退 0/空对象等可被误读的值）。函数无条
    件先置 null 再尝试计算，保证每次 read_progress 输出都携带两键。

    返回本次读出的有效行集合（可能为空）：``read_progress`` 把它转交
    ``_synthesize_startup_stage`` 复用激活域判定（out 有行时后者短路
    null），不重复 IO。
    """
    progress["item_done"] = None
    progress["current_item"] = None
    if progress.get("running") is not True:
        return []
    worktree = progress.get("worktree")
    run_id = progress.get("run_id")
    if not worktree or not run_id:
        return []
    try:
        rows = read_fix_out(worktree, run_id)
    except Exception:  # noqa: BLE001 — 读产物任何异常都兜底为明细不可得
        return []
    if not rows:
        return []
    # item_done：有效行按 item_id 去重（同条目重复追加只计一次，取末次）
    latest: dict = {}
    for row in rows:
        latest[row.get("item_id")] = row
    progress["item_done"] = len(latest)
    # current_item：最近一条有效结果行（D3：title/line 以台账回查补全——
    # 台账是唯一持久化且字段齐全的清单源；匹配失败或台账读异常降级为仅含
    # out 行自带字段 item_id/status/file）。
    last = rows[-1]
    current: dict = {
        "item_id": last.get("item_id"),
        "status": last.get("status"),
        "file": last.get("file"),
    }
    try:
        rec = read_items(project_root).get(last.get("item_id"))
    except Exception:  # noqa: BLE001 — 台账读异常降级，不影响条级计数
        rec = None
    if isinstance(rec, dict):
        current["title"] = rec.get("title")
        if rec.get("line") is not None:
            current["line"] = rec.get("line")
    progress["current_item"] = current
    return rows


# ── 启动阶段推断（add-code-fix-startup-stage-visibility）──────────────

# 转录尾部截读窗口（字节）：流转录可达 MB 级（实测 p90 行 7KB、max 150KB），
# MUST NOT 全量 read_text；取 64KB 是「末行完整在场」与 IO 有界性的折衷——
# 4KB 窗口会把约 16% 的 assistant 行截断成不可解析片段（fail-open null、
# 准备段空白，恰好违背本特性目的），64KB 下截断率 <0.1%，残余退化接受。
_TRANSCRIPT_TAIL_BYTES = 64 * 1024

# 初始化类 system 子类型（D2 词表，实测校准 2026-09-24：system 子类型不止
# 初始化类，还含子代理/后台任务遥测，按 type 整类归「会话初始化中」会在
# 启动窗口误标，故按 subtype 拆分）。
_STARTUP_INIT_SUBTYPES = {"init", "hook_started", "hook_response"}


def _last_transcript_line(path: Path) -> str:
    """尾部截读转录末行（只读末 ``_TRANSCRIPT_TAIL_BYTES`` 字节）。

    末行超出窗口时只能拿到截断片段——解析失败由调用方按「读不到就 null」
    容错（D3），MUST NOT 为补全末行扩大到全量读。
    """
    size = path.stat().st_size
    if size <= 0:
        return ""
    with path.open("rb") as fh:
        fh.seek(max(0, size - _TRANSCRIPT_TAIL_BYTES), os.SEEK_SET)
        chunk = fh.read(_TRANSCRIPT_TAIL_BYTES).decode("utf-8", errors="replace")
    stripped = chunk.rstrip("\n")
    if not stripped:
        return ""
    idx = stripped.rfind("\n")
    return (stripped[idx + 1:] if idx >= 0 else stripped).strip()


def _map_startup_stage(last_line: str) -> str:
    """末行事件 → 阶段短语（D2 映射表）；不可解析返回空串（调用方置 null）。"""
    try:
        event = json.loads(last_line)
    except ValueError:
        return ""
    if not isinstance(event, dict):
        return ""
    etype = event.get("type")
    if etype == "system":
        if str(event.get("subtype") or "") in _STARTUP_INIT_SUBTYPES:
            return "会话初始化中"
        return "agent 启动处理中"
    if etype == "assistant":
        blocks = (event.get("message") or {}).get("content") or []
        if isinstance(blocks, dict):  # 非 list 形态防御（归一为单元素表）
            blocks = [blocks]
        tool_name = ""
        has_text = False
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                # 同事件同时含 text/thinking 与 tool_use 时以动作计（正在做事
                # 比仍在分析对用户更有信息量）
                tool_name = str(block.get("name") or "")
                break
            if btype in ("text", "thinking"):
                has_text = True
        if tool_name:
            return f"正在执行 {tool_name}"
        if has_text:
            return "模型分析分组中"
    # user / stderr / result / 未知形态 → 统一「处理中」（D2 末行兜底行）
    return "agent 启动处理中"


def _transcript_waited_minutes(path: Path):
    """已等待分钟数 = 当前时间 − 转录文件 birth time；取不到 birth 返回 None。

    转录为懒创建（首条流事件经 append_run_line 才建文件），birth = 首事件
    到达时刻、非 spawn 时刻，waited 轻度低估（D2 接受）。部分文件系统 stat
    无 birth（Linux ext4 无 st_birthtime）→ None，前端只显示阶段短语。
    """
    st = os.stat(path)
    birth = getattr(st, "st_birthtime", None)
    if not isinstance(birth, (int, float)) or birth <= 0:
        return None
    return max(0, int((time.time() - birth) // 60))


def _synthesize_startup_stage(project_root, progress: dict, out_rows) -> None:
    """启动阶段实时合成（add-code-fix-startup-stage-visibility D1-D3）。

    激活条件（与 ``_synthesize_item_progress`` 激活域互补）：``running=true``
    且 ``phase ∈ {fixing, retrying}`` 且 ``out_rows`` 零有效行——out 有行即
    首条处置已落盘，条级计数接管，本字段短路 null（spec「处置开始后收敛」）。

    字段形态：``null | {"stage": str, "waited_minutes": int|null}``（恒带
    键）；文件缺失 → 「等待 agent 进程启动」（waited null）；末行不可解析
    → null（MUST NOT 伪造阶段文案）。

    容错硬要求（D3 fail-open）：文件缺失 / 读取异常 / 末行非 JSON / 无
    type 键 → 置 null，任何分支不得抛异常中断 ``read_progress``（读侧
    MUST NOT 500 既有口径）。函数无条件先置 null 再计算。
    """
    progress["startup_stage"] = None
    if progress.get("running") is not True:
        return
    if progress.get("phase") not in ("fixing", "retrying"):
        return
    if out_rows:
        return
    run_id = progress.get("run_id")
    if not run_id:
        return
    try:
        path = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
        if not path.is_file():
            progress["startup_stage"] = {
                "stage": "等待 agent 进程启动",
                "waited_minutes": None,
            }
            return
        stage = _map_startup_stage(_last_transcript_line(path))
        if not stage:
            return
        progress["startup_stage"] = {
            "stage": stage,
            "waited_minutes": _transcript_waited_minutes(path),
        }
    except Exception:  # noqa: BLE001 — 启动阶段推断是尽力而为语义，不炸主流程
        progress["startup_stage"] = None


# ── 失败批保留集合（5.7 / D6）──────────────────────────────────────────


def load_failed_batches(project_root) -> list:
    """读取失败批保留集合；文件不存在/损坏视为空集（不阻塞车道）。"""
    try:
        raw = _failed_path(project_root).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return [rec for rec in data if isinstance(rec, dict)]
    return []


def _failed_item_ids(project_root) -> set:
    """失败保留集合中**在档**记录的全部 item_id 并集（select_batch 排除源）。

    已释放的墓碑记录（``released=true``，见 ``release_retryable_failed_batches``）
    不参与排除——释放即条目重回可选池（下轮自动重试）；``fail_count`` 预算由
    墓碑保留，供同条目集跨链再次失败时递增（达上限永久跳过的判据）。
    """
    ids: set = set()
    for rec in load_failed_batches(project_root):
        if rec.get("released"):
            continue
        for iid in rec.get("item_ids") or []:
            if isinstance(iid, str):
                ids.add(iid)
    return ids


def record_failed_batch(
    project_root, item_ids, worktree, reason="", branch="", tip_sha=""
) -> None:
    """把确定性失败批落盘到 fix-failed.json（原子写；同条目集复用记录）。

    自动重试预算语义（add-code-fix-batch-failure-selfheal D3/D4）：记录带
    ``fail_count``——首记 1；同条目集（item_id 集合相同）再次入档时复用既有
    记录递增并刷新 ``reason``/``branch``/``tip_sha``/``failed_at``（不追加
    重复记录）。新链启动经 ``release_retryable_failed_batches`` 自动释放
    ``fail_count < FAIL_RETRY_MAX`` 的记录（打标墓碑、预算保留，下轮自动
    重试）；同条目集此后再次失败即复燃墓碑并续增——``fail_count`` 递增至
    ``FAIL_RETRY_MAX`` 的那次入档发一条一次性 warning 告警并在 todo.md 登记
    待人工项，此后永久跳过、不再重试/告警。

    ``reason``/``branch``/``tip_sha`` 为可选关键字参数（缺省空串，兼容既有
    调用点）；``branch``/``tip_sha`` 是现场即弃后修复提交的 git 追溯线索。
    ``worktree`` 形参仅为兼容既有调用点保留，MUST NOT 落盘（现场即弃后该
    路径写入几秒即失效且无读者，追溯以 branch/tip_sha 为准，code-review
    item a0e268c1f1c1），记录中恒为 null。
    """
    records = load_failed_batches(project_root)
    key = {str(i) for i in item_ids}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    target = None
    for rec in records:
        if {str(i) for i in rec.get("item_ids") or []} == key:
            target = rec
            break
    if target is not None:
        target["fail_count"] = int(target.get("fail_count") or 0) + 1
        # 墓碑复燃（code-review item 931df4af59cc）：预算内释放只打标不删除，
        # 同条目集再次入档即清标回到在档排除态、fail_count 跨链续增——否则
        # 墓碑留存会让本递增分支不可达，每链都重新以 fail_count=1 建档，
        # 达上限告警/todo/永久跳过永不发生（确定性失败批无限重试）。
        target.pop("released", None)
        target.pop("released_at", None)
    else:
        target = {"item_ids": list(item_ids), "fail_count": 1}
        records.append(target)
    target["worktree"] = None
    target["reason"] = reason
    target["branch"] = branch
    target["tip_sha"] = tip_sha
    target["failed_at"] = now
    _atomic_write(
        _failed_path(project_root),
        json.dumps(records, ensure_ascii=False, indent=2),
    )
    if target["fail_count"] == FAIL_RETRY_MAX:
        # 递增至预算上限的「那次入档」才告警 + 登记 todo（一次性，D4）；
        # 预算内入档可自动重试，不产生人工项。
        _write_retry_exhausted_alert(project_root, item_ids, reason, branch, tip_sha)
        _append_todo_entry(project_root, item_ids, reason, branch, tip_sha)


def release_retryable_failed_batches(project_root) -> int:
    """释放 ``fail_count < FAIL_RETRY_MAX`` 的失败档案记录（selfheal D3）。

    新链启动时调用（等效原人工 ``release_failed_batch`` 的预算内自动化）：
    预算内条目回到可选池实现下轮自动重试；``fail_count >= FAIL_RETRY_MAX``
    的记录保持跳过（达上限永久跳过）。返回释放的记录条数（供日志/进度文案）。

    释放是**打标墓碑**而非删除（code-review item 931df4af59cc）：置
    ``released=true`` + ``released_at``，``fail_count`` 原样保留。删除式释放
    会让预算永不累积——同链内 select_batch 排除在档条目、递增分支无从触发；
    链末释放又把记录整体删掉，下次失败重新以 1 建档，``fail_count`` 恒为 1，
    达上限的一次性告警/todo 登记/永久跳过全部不可达（确定性失败批每链无限
    重试，每轮烧一次 agent run + 两次全量回归）。墓碑不参与选批排除
    （``_failed_item_ids`` 跳过 released 记录）；同条目集再次入档时
    ``record_failed_batch`` 清标复燃并递增。幂等：已释放记录跳过不重刷时间戳。
    """
    records = load_failed_batches(project_root)
    released = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for rec in records:
        if rec.get("released") or int(rec.get("fail_count") or 1) >= FAIL_RETRY_MAX:
            continue
        rec["released"] = True
        rec["released_at"] = now
        released += 1
    if released:
        _atomic_write(
            _failed_path(project_root),
            json.dumps(records, ensure_ascii=False, indent=2),
        )
    return released


def release_failed_batch(project_root, item_ids) -> int:
    """人工清理后解除失败保留（从 fix-failed.json 移除命中的 item_id）。

    返回解除的记录条数（供人工/审计确认；未命中返回 0）。
    """
    target = set(item_ids)
    if not target:
        return 0
    records = load_failed_batches(project_root)
    kept = []
    released = 0
    for rec in records:
        ids = [i for i in rec.get("item_ids") or [] if i not in target]
        if len(ids) == len(rec.get("item_ids") or []):
            kept.append(rec)  # 无交集，原样保留
        elif ids:
            rec["item_ids"] = ids
            kept.append(rec)  # 部分解除，保留余量
        else:
            released += 1  # 整批解除
    _atomic_write(
        _failed_path(project_root),
        json.dumps(kept, ensure_ascii=False, indent=2),
    )
    return released


# ── 延迟合回台账（fix-codefix-wipgate-defer 1.2/D2）──────────────────
# 与失败档案对齐的惯例：同目录、_atomic_write 原子写、同条目集幂等复用、
# 读侧对缺失/损坏 fail-open（无 .lock 文件，勿发明锁文件）。


def _deferred_path(project_root) -> Path:
    return Path(project_root) / DEFERRED_REL


def load_deferred_batches(project_root) -> list:
    """读取延迟合回台账；文件不存在/损坏视为空集（不阻塞车道）。"""
    try:
        raw = _deferred_path(project_root).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return [rec for rec in data if isinstance(rec, dict)]
    return []


def _save_deferred_batches(project_root, entries: list) -> None:
    _atomic_write(
        _deferred_path(project_root),
        json.dumps(entries, ensure_ascii=False, indent=2),
    )


def record_deferred_batch(
    project_root, item_ids, fixed_ids, worktree,
    branch="", tip_sha="", last_overlap=None,
) -> dict:
    """把被主树 WIP 挡住合回的批记入 fix-deferred.json（原子写；幂等复用）。

    零预算语义（D2）：不入失败档案、不烧 ``fail_count``。条目八字段：
    ``worktree``/``branch``/``tip_sha``/``item_ids``/``fixed_ids``/
    ``defer_count``/``first_deferred_at``（UTC ISO8601）/``last_overlap``。
    ``fixed_ids`` 是批产物行 ``status=="fixed"`` 的核销集合——缺它则重试方
    无从区分 fixed 与 skipped，全批核销会把 skipped 白洗成 resolved。

    首记 ``defer_count=1``（批收尾那次被阻断的 merge_back 即一次实际尝试）；
    链边界重试仍被阻断时由重试方递增（2.3：仅实际尝试才 +1）。同条目集
    幂等复用条目：刷新现场字段、保留 ``first_deferred_at``/``defer_count``
    （预算时间门不因复写漂移）。返回写盘后的条目。
    """
    entries = load_deferred_batches(project_root)
    key = {str(i) for i in item_ids}
    target = None
    for rec in entries:
        if {str(i) for i in rec.get("item_ids") or []} == key:
            target = rec
            break
    if target is None:
        target = {
            "item_ids": [str(i) for i in item_ids],
            "defer_count": 1,
            "first_deferred_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
        }
        entries.append(target)
    target["worktree"] = str(worktree)
    target["branch"] = branch
    target["tip_sha"] = tip_sha
    target["fixed_ids"] = [str(i) for i in fixed_ids]
    target["last_overlap"] = [str(f) for f in (last_overlap or [])]
    _save_deferred_batches(project_root, entries)
    return target


def _patch_deferred_entry(project_root, item_ids, **fields) -> None:
    """按条目集定位并原位更新台账字段（defer_count 递增等），原子写。"""
    entries = load_deferred_batches(project_root)
    key = {str(i) for i in item_ids}
    hit = False
    for rec in entries:
        if {str(i) for i in rec.get("item_ids") or []} == key:
            rec.update(fields)
            hit = True
    if hit:
        _save_deferred_batches(project_root, entries)


def _remove_deferred_batch(project_root, item_ids) -> None:
    """从台账移除命中的条目（按 item_ids 集合整条匹配；无命中静默返回）。"""
    entries = load_deferred_batches(project_root)
    key = {str(i) for i in item_ids}
    kept = [
        rec
        for rec in entries
        if {str(i) for i in rec.get("item_ids") or []} != key
    ]
    if len(kept) != len(entries):
        _save_deferred_batches(project_root, kept)


def _deferred_item_ids(project_root) -> set:
    """台账全部 item_id 并集（select_batch 排除源之一，D4 配套约束）。

    defer 条目在合回成功前始终是 open 状态且不在失败档案——不并入排除集则
    下一边界 earliest-first 立即重选同批、重跑 agent，defer 核心收益归零。
    """
    ids: set = set()
    for rec in load_deferred_batches(project_root):
        for iid in rec.get("item_ids") or []:
            if isinstance(iid, str):
                ids.add(iid)
    return ids


def _deferred_entry_alive(entry) -> bool:
    """台账条目的磁盘真相（D5 再认领判据）：worktree 目录在且记录的 tip_sha
    仍可经该 worktree HEAD 解析（分支被删/目录被清/漂移均判死）。

    空 tip_sha（登记时 ``_worktree_head`` 瞬时失败所致）不直接判死：现场
    补解析 HEAD，能解析即视为存活（merge_back 不依赖记账的 tip_sha），
    否则带修复提交的存活 worktree 会被误判死移出台账且无人清理。
    """
    wt = Path(str(entry.get("worktree") or ""))
    tip_sha = str(entry.get("tip_sha") or "")
    if not wt.name or not wt.exists():
        return False
    if not tip_sha:
        return bool(_worktree_head(wt))
    return _worktree_head(wt) == tip_sha


def reclaim_deferred_batches(project_root) -> int:
    """新链启动再认领（D5/4.1）：台账核对磁盘，死条目移出，返回移除条数。

    存活（worktree 目录在且 tip_sha 可解析）→ 原样保留（``defer_count``/
    ``first_deferred_at`` 不重置，链边界重试照常覆盖）；丢失 → 清出台账 +
    由调用方记 warning（条目未核销，天然仍在 open 池，无需回写）。
    """
    entries = load_deferred_batches(project_root)
    kept = [rec for rec in entries if _deferred_entry_alive(rec)]
    dropped = len(entries) - len(kept)
    if dropped:
        _save_deferred_batches(project_root, kept)
    return dropped


def _defer_time_budget_exhausted(entry) -> bool:
    """时间门：first_deferred_at 距今超 DEFER_BUDGET_SECONDS（解析失败按未超时）。

    超时判定只看 ``first_deferred_at``，不受重试影响（2.3）。
    """
    ts = str(entry.get("first_deferred_at") or "")
    if not ts:
        return False
    try:
        start = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return False
    return (time.time() - start) > DEFER_BUDGET_SECONDS


def _has_expired_archive(project_root, item_ids) -> bool:
    """失败档案是否已有同条目集的 wip_gate_blocked_expired 记录（3.2 告警去重指纹）。

    MUST 在 ``record_failed_batch`` 之前调用——入档后同集合记录即在场，
    先查后记才能区分「首次降级」与「同指纹二次降级」。
    """
    key = {str(i) for i in item_ids}
    for rec in load_failed_batches(project_root):
        if (
            rec.get("reason") == "wip_gate_blocked_expired"
            and {str(i) for i in rec.get("item_ids") or []} == key
        ):
            return True
    return False


def _fmt_overlap(overlap) -> str:
    """交集文件清单 → 人类可读片段（进度文案/告警正文复用，超长截断）。"""
    files = [str(f) for f in (overlap or []) if str(f)]
    if not files:
        return "（交集清单缺失）"
    shown = ", ".join(files[:8])
    if len(files) > 8:
        shown += f" 等 {len(files)} 个文件"
    return shown


def _append_todo_entry(project_root, item_ids, reason="", branch="", tip_sha="") -> None:
    """达重试上限的失败批在 .fenix/todo.md 追加待人工排查项（一次性，D4）。

    现场即弃语义下 worktree 已清理，指引按 ``branch``/``tip_sha`` 追溯
    （丢弃的修复提交可经 git reflog 找回）；MUST NOT 再引用 worktree 路径。
    """
    todo_path = Path(project_root) / ".fenix" / "todo.md"
    ids_txt = ", ".join(str(i) for i in item_ids)
    entry = (
        "\n## [code-fix] 失败批已达自动重试上限，待人工排查"
        "（add-code-fix-batch-failure-selfheal）\n\n"
        f"- 记录时间：{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"- 失败原因：{reason or 'unknown'}（自动重试 {FAIL_RETRY_MAX} 轮均失败，"
        "已停止自动重派）\n"
        f"- 追溯线索：branch=`{branch}`、tip_sha=`{tip_sha}`（worktree 已清理，"
        "丢弃的修复提交可经 git reflog 按 tip_sha 找回）\n"
        f"- 被跳过的条目集合（保持 open）：{ids_txt}\n"
        "- 解除跳过（人工确认处置后）：\n"
        "  `python3 -c \"from core.code_fix import release_failed_batch; "
        "release_failed_batch('<project_root>', ['<item_id>', ...])\"`\n"
    )
    try:
        todo_path.parent.mkdir(parents=True, exist_ok=True)
        with todo_path.open("a", encoding="utf-8") as fh:
            fh.write(entry)
    except OSError:
        # todo 登记失败不阻断失败批落盘（fix-failed.json 才是跳过判据）
        pass


# ── 选批（5.2）────────────────────────────────────────────────────────


def select_batch(project_root, batch_size: int, exclude_ids=None) -> list:
    """从台账选下一批：open 条目按 first_seen_at 升序（缺失回退 item_id
    稳定排序）取前 batch_size 条。

    排除口径 = 失败档案条目并集 ∪ ``exclude_ids``（add-code-fix-batch-
    selfheal：链内跳过集 chain_skipped，瞬态失败条目本链不再选批；缺省
    None 向后兼容，既有调用点零改动）。

    返回条目 record 列表（含 item_id/file/line/severity/category/title/
    description/suggestion 等 prompt 注入字段）。
    """
    try:
        items = read_items(project_root)
    except Exception:  # noqa: BLE001 — 台账读失败按无条目处理（fail-closed）
        return []
    excluded = _failed_item_ids(project_root) | set(exclude_ids or ())
    open_items = [
        rec
        for rec in items.values()
        if isinstance(rec, dict)
        and rec.get("status") == "open"
        and rec.get("item_id") not in excluded
    ]
    open_items.sort(
        key=lambda rec: (
            str(rec.get("first_seen_at") or ""),
            str(rec.get("item_id") or ""),
        )
    )
    n = int(batch_size) if isinstance(batch_size, int) and batch_size > 0 else 20
    return open_items[:n]


def count_open_items(project_root) -> int:
    """台账当前 open 条目总数（进度 total 的快照源，含被失败集合排除者）。"""
    try:
        items = read_items(project_root)
    except Exception:  # noqa: BLE001
        return 0
    return sum(
        1
        for rec in items.values()
        if isinstance(rec, dict) and rec.get("status") == "open"
    )


# ── 回归快照→台账 findings 转换与复发重开（add-regression-auto-fix 1.1/1.2）──
#
# 消费端（fenixd._check_regression_fix_requests）把最近一次回归快照
# （core/regression.py 单快照 .fenix/regression/last-run.json）的问题列表
# 转换为 code-fix 台账条目（upsert_findings，category 以 ``regression-`` 为
# 前缀隔离标识）。纯函数化便于单测，不触碰既有批派/验证/合并路径。

# 回归来源条目的 category 前缀（重开语义的唯一作用域标识）
REGRESSION_CATEGORY_PREFIX = "regression-"

# 整体超时条目的 file 锚点（design D4）：upsert_findings 跳过无 file 的发现，
# 而整体超时无逐用例定位；超时处置的真实入口恰是回归硬超时的声明落点
# verify.yaml（先查套件性能，确属超时配置不合理才调声明），以真实存在文件
# 为锚点而非伪造用例路径。
REGRESSION_TIMEOUT_FILE = ".fenix/verify.yaml"

# description 内动态文本（失败 message / 超时 reason / 输出摘要）截断上限
_REGRESSION_EXCERPT_LIMIT = 500


def _regression_excerpt(value, limit: int = _REGRESSION_EXCERPT_LIMIT) -> str:
    """动态文本截断（None 安全）：超限截断加省略号，保持纯函数可单测。"""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _regression_time_text(value) -> str:
    """耗时展示文本：整数耗时不带小数（42.0 → "42s"，42.3 → "42.3s"）。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "未知"
    if num.is_integer():
        return f"{int(num)}s"
    return f"{round(num, 2)}s"


# suggestion 按类目固化文案（单源，spec「长耗时修复语义固化」Requirement）：
# long 类 MUST 含「不改变测试通过结果」前提与优化手段建议——文案随批派
# 注入修复 Agent，是该约束的唯一落点。
REGRESSION_SUGGESTIONS = {
    "regression-failure": (
        "定位该用例失败原因并修复：优先修被测实现，确属测试代码缺陷（断言过期、"
        "夹具失效等）可修测试本身；MUST NOT 以删除/跳过用例的方式掩盖失败。"
    ),
    "regression-error": (
        "定位该用例报错原因并修复：优先修被测实现，确属测试代码缺陷（导入错误、"
        "夹具失效等）可修测试本身；MUST NOT 以删除/跳过用例的方式掩盖错误。"
    ),
    "regression-long-test": (
        "以不改变测试通过结果为前提优化该用例耗时：允许优化被测实现或测试代码"
        "本身（去冗余 sleep、修慢 fixture、并发化等）；MUST NOT 使原测试由通过"
        "变为失败（批验证回归重跑会复核）。"
    ),
}

# 整体超时条目 suggestion（design D4 风险对冲：防修复 Agent 误读为「改配置
# 了事」——先查套件性能，确属超时配置不合理才调声明）
_REGRESSION_TIMEOUT_SUGGESTION = (
    "整体超时处置指引：先排查套件性能问题（慢用例/慢 fixture/可并发化/串行"
    "浪费），按 failure/long-test 思路修复慢的根源；确属回归硬超时声明不合理"
    "（套件本就长于 timeout_seconds 且无性能问题）才调整 .fenix/verify.yaml "
    "的 regression timeout_seconds；MUST NOT 以单纯放宽超时掩盖性能退化。"
)


def convert_regression_snapshot_to_findings(snapshot, output_excerpt: str = "") -> list:
    """回归快照 → code-fix 台账 findings 列表（纯函数，add-regression-auto-fix 1.1）。

    映射固化（spec「daemon 消费信号并转换为台账条目」Requirement）：
    - failures 逐条：kind=failure → category ``regression-failure``；
      kind=error → ``regression-error``；severity 均为 high；title 取用例名；
      description 携带分类、耗时与失败 message（截断 500 字）。
    - long_tests 逐条：category ``regression-long-test``、severity medium。
    - status=timeout：追加单条 ``regression-timeout``（severity high，file 固定
      ``.fenix/verify.yaml``，title「回归整体超时」），description 携带 reason 与
      输出摘要（``output_excerpt`` 由消费端预读快照 output 字段指向的日志文件
      尾部传入，读取失败置空；函数内截断 500 字）。

    输入容错：snapshot 缺失/非 dict/字段缺失不抛异常，返回空列表（消费端
    以当下快照为准，转换零条目时仍可继续走 checkpoint 既有守卫）。
    """
    findings: list = []
    if not isinstance(snapshot, dict):
        return findings

    failures = snapshot.get("failures")
    if isinstance(failures, list):
        for item in failures:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "failure")
            category = (
                f"{REGRESSION_CATEGORY_PREFIX}error"
                if kind == "error"
                else f"{REGRESSION_CATEGORY_PREFIX}failure"
            )
            name = str(item.get("name") or "").strip() or "unnamed"
            desc = (
                f"回归失败用例（{category}），耗时 {_regression_time_text(item.get('time'))}；"
                f"信息：{_regression_excerpt(item.get('message'))}"
            )
            findings.append({
                "file": str(item.get("file") or ""),
                "line": item.get("line"),
                "severity": "high",
                "category": category,
                "title": name,
                "description": desc,
                "suggestion": REGRESSION_SUGGESTIONS.get(
                    category, REGRESSION_SUGGESTIONS["regression-failure"]
                ),
                "evidence": "",
            })

    long_tests = snapshot.get("long_tests")
    if isinstance(long_tests, list):
        for item in long_tests:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip() or "unnamed"
            time_text = _regression_time_text(item.get("time"))
            findings.append({
                "file": str(item.get("file") or ""),
                "line": item.get("line"),
                "severity": "medium",
                "category": f"{REGRESSION_CATEGORY_PREFIX}long-test",
                "title": name,
                "description": (
                    f"长耗时用例（{REGRESSION_CATEGORY_PREFIX}long-test），"
                    f"耗时 {time_text}，超出回归长耗时阈值"
                ),
                "suggestion": REGRESSION_SUGGESTIONS["regression-long-test"],
                "evidence": "",
            })

    if str(snapshot.get("status") or "") == "timeout":
        desc = (
            "回归整体超时（未完成，无逐用例定位）；原因："
            + (_regression_excerpt(snapshot.get("reason")) or "未提供")
        )
        excerpt = _regression_excerpt(output_excerpt)
        if excerpt:
            desc += f"；输出摘要：{excerpt}"
        findings.append({
            "file": REGRESSION_TIMEOUT_FILE,
            "line": 1,
            "severity": "high",
            "category": f"{REGRESSION_CATEGORY_PREFIX}timeout",
            "title": "回归整体超时",
            "description": desc,
            "suggestion": _REGRESSION_TIMEOUT_SUGGESTION,
            "evidence": "",
        })

    return findings


def regression_findings_fingerprints(findings: list) -> set:
    """转换产物的指纹集合（重开语义的 live 集合；无 file/title 的条目跳过，
    与 upsert_findings 的关键字段硬规则同口径）。"""
    out: set = set()
    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        file_ = str(finding.get("file") or "")
        title = str(finding.get("title") or "")
        category = str(finding.get("category") or "")
        if not file_ or not title:
            continue
        out.add(fingerprint(file_, category, title))
    return out


def reopen_regression_items(project_root, live_fps) -> int:
    """重开复发的回归条目（add-regression-auto-fix 1.2）。

    仅 category 以 ``regression-`` 为前缀、fingerprint 命中 ``live_fps``
    （本次快照问题集指纹）且 status 非 open 的条目：status 重开为 open 并
    刷新 first_seen_at——保证同问题复发可再次触发修复（否则链会以
    no_open_items 拒绝、按钮一次性失效）。

    非 ``regression-`` 前缀条目（code-review 来源）零触碰，即使 file/title
    恰好同名（fingerprint 只在回归前缀子集内比对）。

    读-改-写 + flock 与台账写同锁（``_with_lock``；锁内 MUST NOT 再次加
    同一把锁）。Returns: 重开条目数。
    """
    fps = {fp for fp in (live_fps or ()) if isinstance(fp, str) and fp}
    if not fps:
        return 0
    now = _now_iso()
    path = items_path(project_root)
    reopened = 0

    def _do() -> None:
        nonlocal reopened
        current = _read_items_unlocked(path)
        changed = False
        for rec in current.values():
            if not str(rec.get("category") or "").startswith(REGRESSION_CATEGORY_PREFIX):
                continue
            if rec.get("status") == "open":
                continue
            if rec.get("fingerprint") not in fps:
                continue
            rec["status"] = "open"
            rec["first_seen_at"] = now
            rec["last_seen_at"] = now
            reopened += 1
            changed = True
        if changed:
            content = "".join(
                json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)
            )
            _atomic_write(path, content)

    _with_lock(path, _do)
    return reopened


# ── 产物解析（编排侧读 out 文件；与 run_code_fix 的写入口径一致）────────


def read_fix_out(worktree, run_id: str) -> list:
    """读取 code-fix run 的增量产物 ``fix-out-<run_id>.jsonl``。

    每行一个条目处置结果（``{item_id, status, file}``）。损坏行跳过；
    文件缺失返回空列表（run 失败路径由 CodeFixResult.success 承载）。
    """
    path = Path(worktree) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
    rows: list = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("item_id"):
            rows.append(rec)
    return rows


def _split_fix_rows(rows: list) -> tuple:
    """批收尾产物行分区（纯函数，LLM 拒绝出口 2026-09-23）。

    返回 ``(fixed_ids, skip_reasons)``：

    - ``fixed_ids``：``status == "fixed"`` 的条目 id（保序去重）——合回后
      经 ``mark_resolved`` 核销；
    - ``skip_reasons``：``item_id → skip_reason``，仅收录 ``status ==
      "skipped"`` 且 skip_reason ∈ ``IGNORE_ELIGIBLE_SKIP_REASONS``（判误报/
      不值得修，批收尾经 ``mark_ignored`` 置终态）。同条目多行时**后行覆盖
      前行**（并集口径下重试轮的判定更新生效）；但最终态为 fixed 的条目
      MUST NOT 出现在 skip_reasons——「首轮 skipped 判误报、重试轮 fixed」
      以 fixed 为准（不降级）。
    """
    fixed_ids = [r.get("item_id") for r in rows if r.get("status") == "fixed"]
    fixed_ids = list(dict.fromkeys(fixed_ids))
    fixed_set = set(fixed_ids)
    skip_reasons = {
        r.get("item_id"): r.get("skip_reason")
        for r in rows
        if r.get("status") == "skipped"
        and r.get("skip_reason") in IGNORE_ELIGIBLE_SKIP_REASONS
        and r.get("item_id") not in fixed_set
    }
    return fixed_ids, skip_reasons


def _worktree_commit_count(worktree, created_sha: str) -> int:
    """worktree 分支相对建树点的提交数（零有效修复守卫的 git 侧判据，5.8）。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "rev-list", "--count", f"{created_sha}..HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return int(out.stdout.strip() or "0")
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _worktree_head(worktree) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _worktree_branch(worktree) -> str:
    """worktree 分支名（失败档案的追溯线索之一，selfheal D2；异常返回空串）。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ── 回归契约缺失信号（5.5 / D5，分流口径对齐 regression_routes 既有区分）──


def _evidence_project(evidence: str) -> str:
    """从 evidence 串（``项目名=<name>; ...``）按字段解析项目名，全等比较用。

    与 regression_routes/settings_routes 的同名 helper 同口径：evidence 的
    生产点格式不一（dashboard 侧可能只有裸 ``项目名=<name>`` 无尾随分隔符），
    不能靠带分隔符的子串匹配；项目名互为前缀时（``web`` 与 ``webapp``）
    也不得互撞（code-review item 29958284895a）。
    """
    for seg in (evidence or "").split(";"):
        seg = seg.strip()
        if seg.startswith("项目名="):
            return seg[len("项目名="):].strip()
    return ""


def _signal_inflight(store, signal_type: str, project_name: str) -> bool:
    """同项目同类型、未摄取未处置的在途信号已存在 → 不重复写。"""
    from core.admin_store import SIGNAL

    for rec in store.read_all():
        if rec.get("kind") != SIGNAL or rec.get("signal_type") != signal_type:
            continue
        if rec.get("handled") or rec.get("escalated"):
            continue
        # 项目名按字段全等比较而非裸子串：``项目名=web`` 不得命中
        # ``项目名=webapp``（前缀关系项目名互判在途 → 新信号被静默跳写）。
        if _evidence_project(str(rec.get("evidence") or "")) == project_name:
            return True
    return False


def write_regression_signal(project_root, signal_type: str, logger=None) -> None:
    """写回归契约缺失信号（AdminStore kind=SIGNAL 通道，fail-closed 附属动作）。

    分流口径（MUST 对齐 core/dashboard/routes/regression_routes.py:195-236
    与 core/admin_monitor.py:214-216 的既有区分，用错信号会令 administrator
    重写一份有效且在服务的 prepare/serve/ready）：
    - ``verify_contract_missing``：契约整体缺失 → 起草**完整**契约；
    - ``verify_regression_missing``：契约有效仅缺 regression 段 → **仅补段**。
    payload 形态对齐既有 `_api_regression_autodraft_post` 写入（含
    signal_type/spec/severity:"major"/description/evidence/recommended_action），
    evidence 携带 ``项目名=`` 供 admin_monitor 摄取（无 spec 信号）。
    """
    from core.admin_store import AdminStore, SIGNAL

    project_name = Path(project_root).name
    store = AdminStore(project_root, logger=None)
    if _signal_inflight(store, signal_type, project_name):
        return
    if signal_type == "verify_contract_missing":
        description = "code-fix 车道 fail-closed：verify.yaml 契约整体缺失，请 Administrator 起草完整契约（含 regression 段）"
        recommended = (
            "Administrator 按 agents/administrator.md 的契约起草手册生成完整 "
            ".fenix/verify.yaml（有测试体系时一并生成 regression 段）并自证落位；"
            "完成后下一轮 full scan 自动续做自动修复。"
        )
    else:
        description = "code-fix 车道 fail-closed：verify.yaml 缺 regression 段，请 Administrator 仅补该段"
        recommended = (
            "Administrator 仅补 regression 段（MUST NOT 动 prepare/serve/ready 与"
            "其它顶层键），自证落位后 git 提交；完成后下一轮 full scan 自动续做自动修复。"
        )
    store.append(
        {
            "kind": SIGNAL,
            "signal_type": signal_type,
            "spec": None,
            "severity": "major",
            "description": description,
            "evidence": (
                f"项目名={project_name}; code-fix 车道在派批前经 "
                f"load_verify_contract 检测到 {signal_type}，本批 fail-closed 未合回"
            ),
            "source": "code-fix-lane",
            "recommended_action": recommended,
        }
    )
    if logger is not None:
        try:
            logger.warning("code-fix", f"已写回归契约缺失信号: {signal_type}")
        except Exception:  # noqa: BLE001 — 日志失败不影响信号落盘
            pass


def write_regression_failed_alert(
    project_root, item_ids, worktree, failures_summary: str,
    branch="", tip_sha="",
) -> None:
    """回归两次均失败丢弃批时写失败告警（selfheal：已跳过，下轮自动重试）。

    ``worktree`` 形参保留兼容既有签名，但现场即弃后 worktree 已清理，
    evidence 改以 ``branch``/``tip_sha`` 作为追溯线索（git reflog 可找回）。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_regression_failed",
            "spec": None,
            "severity": "warning",
            "description": (
                "code-fix 批两次全量回归均未通过，已跳过（未合回、条目保持 open，"
                "worktree 已清理，下轮自动重试）"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
                f"tip_sha={tip_sha or 'unknown'}; "
                f"item_ids={', '.join(str(i) for i in item_ids)}; "
                f"失败用例摘要: {failures_summary[:2000]}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "已跳过，下轮自动重试（达重试上限后需人工介入）；丢弃的修复提交"
                "可按 branch/tip_sha 经 git reflog 追溯"
            ),
        }
    )


def _write_retry_exhausted_alert(project_root, item_ids, reason, branch, tip_sha) -> None:
    """失败档案条目集 fail_count 达 FAIL_RETRY_MAX 时的一次性 warning 告警（D4）。

    点名录条目集与历次失败原因；此后该记录不再被释放、不再触发新告警。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_retry_budget_exhausted",
            "spec": None,
            "severity": "warning",
            "description": (
                f"code-fix 失败批自动重试已达上限（{FAIL_RETRY_MAX} 轮），"
                "停止自动重派，待人工排查"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
                f"tip_sha={tip_sha or 'unknown'}; "
                f"item_ids={', '.join(str(i) for i in item_ids)}; "
                f"失败原因: {reason or 'unknown'}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "按 branch/tip_sha 经 git reflog 追溯丢弃的修复提交，人工排查后"
                "调用 core.code_fix.release_failed_batch 解除该批条目的跳过"
            ),
        }
    )


def _write_defer_info_alert(project_root, item_ids, overlap, branch="") -> None:
    """首次进入 defer 路径的 info 提示（fix-codefix-wipgate-defer 1.3）。

    正文含 last_overlap 交集文件清单；处置话术复用 mergeback.py 升级出口
    （「提交（git add/commit）或 stash（git stash push）主树这些改动」）。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_wip_gate_deferred",
            "spec": None,
            "severity": "info",
            "description": (
                "code-fix 批合回被主树未提交改动挡住（WIP overlap 预检阻断），"
                "批已保留（worktree 与分支未动、不烧失败预算），主树清理后链"
                "边界自动合回核销"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
                f"item_ids={', '.join(str(i) for i in item_ids)}; "
                f"重叠文件: {_fmt_overlap(overlap)}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "提交（git add/commit）或 stash（git stash push）主树这些改动后，"
                "无需人工重派——链边界（选批前/收敛出口）自动重试合回"
            ),
        }
    )


def _write_defer_expired_alert(
    project_root, item_ids, overlap, branch="", tip_sha=""
) -> None:
    """延迟批预算耗尽降级的一次性 warning 告警（D6/3.2）。

    一次性语义按条目集指纹（调用方以 ``_has_expired_archive`` 先查后记——
    同 fix-failed「递增至上限那次发一次性 warning」先例）。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_wip_gate_defer_expired",
            "spec": None,
            "severity": "warning",
            "description": (
                f"code-fix 延迟批合回超预算（90 分钟或 {DEFER_RETRY_MAX} 次重试"
                "仍被主树未提交改动挡住），已降级入失败档案，待人工处置主树"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
                f"tip_sha={tip_sha or 'unknown'}; "
                f"item_ids={', '.join(str(i) for i in item_ids)}; "
                f"重叠文件: {_fmt_overlap(overlap)}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "提交（git add/commit）或 stash（git stash push）主树这些改动；"
                "该批修复提交可按 branch/tip_sha 经 git reflog 追溯，人工排查后"
                "调用 core.code_fix.release_failed_batch 解除该批条目的跳过"
            ),
        }
    )


def _main_tree_dirty_files(project_root) -> list:
    """主树脏 tracked 文件清单（evo-add-codefix-batch-wip-precheck 1.1）。

    复用 ``G6StashGuardMixin._list_dirty_tracked_files`` 的提取口径（porcelain
    脏判定 / rename 两侧计入 / untracked 不计 / 命令失败返回空表按「无重叠」
    处理，不阻塞选批）。函数级 import 规避装载环（worktree_manager 包装载
    较重且与车道装配顺序无耦合，``_preset_run_id`` 同纪律）。
    """
    from core.worktree_manager.stash_guard import G6StashGuardMixin

    class _Probe(G6StashGuardMixin):
        """仅承载 project_root 的探针壳（完整 WorktreeManager 装配是死重）。"""

        def __init__(self, project_root):
            self.project_root = Path(project_root)

    return _Probe(project_root)._list_dirty_tracked_files()


# ── 编排器（5.3-5.8）──────────────────────────────────────────────────


class CodeFixOrchestrator:
    """自动修复编排器：单一入口 ``checkpoint()``（两路激活共用，D4）。

    守卫链（任一命中即不投递）：``enabled`` → ``already_running`` →
    ``no_open_items`` → 回归契约（fail-closed）→ 投递批 worker。

    单飞：``_in_flight`` + ``threading.Lock`` 保证两路并发至多一次投递；
    批 worker 收尾复位单飞并经 executor 再投递 checkpoint 推进下一批。
    """

    def __init__(self, agent_runner, project_root, config=None, logger=None, executor=None):
        self._agent_runner = agent_runner
        self.project_root = Path(project_root)
        self._config = config
        self._logger = logger
        self._executor = executor
        self._lock = threading.Lock()
        self._in_flight = False

    # -- 基础 ------------------------------------------------------------

    def _log(self, level: str, msg: str) -> None:
        if self._logger is None:
            return
        try:
            getattr(self._logger, level)("code-fix", msg)
        except Exception:  # noqa: BLE001 — 日志失败不影响编排
            pass

    def _get_root_config(self) -> dict:
        """解析**根形态** config（dict / callable / None→runner 运行时配置）。

        `_get_config` 与选批前 WIP 预检（``worktree.build_artifact_paths`` /
        ``worktree.has_build_artifacts``，evo-add-codefix-batch-wip-precheck
        1.1）共用的单一解析点：产物豁免口径与开关读取 MUST 同源，否则 daemon
        装配形态（config=None）下豁免静默退化。
        """
        raw = self._config
        if callable(raw):
            raw = raw()
        if raw is None:
            # daemon 装配形态（fenixd.py 传 config=None）：读 **根** config。
            # `ConfigLoader.get_code_review_fix_config` 的契约是根形态（内部
            # `config.get("admin")`），而 `runner._get_config("admin.code_review_fix")`
            # 按嵌套键路径返回的是**子段**——直接把子段交给读取器会被判定「段缺失」
            # 而恒返回缺省 disabled，令设置页开关在唯一的生产路径上静默失效
            # （两路激活都经 checkpoint，整条自动修复车道不生效）。
            # 直接取 runner.config（与 runner._get_config 同源对象，热更新同样生效）。
            runner = self._agent_runner
            root = getattr(runner, "config", None)
            if isinstance(root, dict):
                return root
            # 退化：runner 无根 config 属性（测试替身）时，把子段回包成根形态
            try:
                seg = runner._get_config("admin.code_review_fix", {})
            except Exception:  # noqa: BLE001 — 测试 fake runner 可能无此方法
                seg = {}
            return {"admin": {"code_review_fix": seg}} if isinstance(seg, dict) else {}
        return raw or {}

    def _get_config(self) -> dict:
        """解析 admin.code_review_fix 生效值（根形态 → 段读取器）。"""
        return ConfigLoader.get_code_review_fix_config(self._get_root_config())

    def _code_fix_running(self) -> bool:
        """在途判据：编排器单飞标记或 runner 侧存在 code-fix- 前缀 run。"""
        if self._in_flight:
            return True
        running = getattr(self._agent_runner, "_running_agents", None) or {}
        return any(str(rid).startswith("code-fix-") for rid in running)

    def _wip_overlap_at_select(self, batch) -> list:
        """选批前 WIP 重叠预检（evo-add-codefix-batch-wip-precheck 1.1）。

        主树脏 tracked 文件 × 候选批条目 file（台账条目为仓库相对路径，
        items.jsonl 实证）求交；交集经产物判别过滤——ArtifactPathMatcher 以
        与 WorktreeManager 同配置源构造（normalize_artifact_patterns(
        build_artifact_paths) + has_build_artifacts 三态，先例
        core/worktree_manager/lifecycle.py:127）。dist 类产物路径不计入命中：
        merge-time 闸门（_wip_overlap_gate D3b）豁免纯产物重叠，预检若不同
        口径即「预检拦、merge-time 放行」倒退；MUST NOT 硬编码 dist 前缀、
        MUST NOT 无参默认构造——空 patterns 判定恒假是「未裁决」保守侧（此
        时 merge-time 闸门同样按语义重叠处置），与 merge-time 同语义不算豁免。

        Returns: 语义（非产物）重叠文件排序列表；无重叠为空列表。
        """
        candidates = {rec.get("file") for rec in batch if rec.get("file")}
        if not candidates:
            return []
        dirty = _main_tree_dirty_files(self.project_root)
        if not dirty:
            return []
        overlap = sorted(candidates & set(dirty))
        if not overlap:
            return []
        from core.worktree_manager.artifact_paths import (
            ArtifactPathMatcher,
            normalize_artifact_patterns,
        )

        root_cfg = self._get_root_config()
        return ArtifactPathMatcher(
            normalize_artifact_patterns(
                ConfigLoader.get(root_cfg, "worktree.build_artifact_paths", None)
            ),
            has_build_artifacts=ConfigLoader.get(
                root_cfg, "worktree.has_build_artifacts", None
            ),
        ).non_artifacts_in(overlap)

    # -- 检查点（单一入口）--------------------------------------------------

    def checkpoint(self, override_enabled: bool = False) -> dict:
        """激活检查点：守卫链判定，通过则投递一批（返回 ``{triggered, reason}``）。

        两路激活（审查收尾 / full scan）与批 worker 的自驱动再投递共用本入口；
        幂等（开关关闭 / 已在跑 / 无 open 条目 / 回归契约缺失均不投递）。

        ``override_enabled``（add-code-fix-manual-trigger）：手动触发即临时授权
        ——为 True 时跳过 ``enabled`` 守卫（唯一调用方是 daemon 手动信号消费
        函数 ``fenixd._check_code_fix_requests``），其余守卫（单飞 already_running
        / 无 open 条目 / 失败保留 / 回归契约 fail-closed）原样生效。缺省 False。

        手动授权语义（2026-09-22 事故修复）：授权的是**整条链**而非一批。手动
        投递时把 ``manual_authorized=true`` 写进进度快照（随链身份持久化），
        批收尾后 ``_resubmit`` 的 checkpoint（无 override）凭「链 live 且旗标
        为真」越过 enabled 总开关，自驱动跑完剩余 open 条目；终态（idle /
        blocked / failed）清除旗标——收尾链的授权不外溢到新链。仅当 live 链
        撞上 disabled（开关被中途关闭）时落终态进度（phase=blocked /
        reason=disabled），MUST NOT 静默冻结在 running=true。

        进度链身份（D8）：读到 ``running=true`` 且 activation_id 未变 → 视为
        同一激活链，MUST NOT 重算 total（否则每批收尾再投递会把 total 重置为
        已缩小的 open 数，前端出现「已处理 0/40」倒退）。

        批失败自愈（add-code-fix-batch-selfheal）：链身份判定前移到选批之前
        ——新链启动（非同一 activation_id）先释放预算内失败档案
        （``release_retryable_failed_batches``，等效人工 release 的自动化）
        并重置 ``chain_skipped``，再选批；否则上一链以全跳过收敛后，下一
        checkpoint 会因 open 条目全被排除而恒走「选批为空」早退，永远到不了
        新链分支，车道锁死（自愈失效）。选批排除口径 = 失败档案 ∪
        ``chain_skipped``；「选批为空」是 consumed 链的正常收敛出口，文案按
        排除来源区分（D5），不误报为故障。
        """
        with self._lock:
            cfg = self._get_config()
            # 链上授权旗标：只有 live 链（running=true）的旗标被消费，
            # 收尾链残留的旗标不外溢到新链。
            prev_chain = read_progress(self.project_root)
            chain_authorized = bool(prev_chain.get("running")) and bool(
                prev_chain.get("manual_authorized")
            )
            if not cfg.get("enabled") and not override_enabled and not chain_authorized:
                # 开关关闭且无授权 = 不投递；但 live 链撞上 disabled（开关被
                # 中途关闭）必须落终态进度——静默早退会让前端永久停在陈旧的
                # 「进行中」快照上（2026-09-22「合回主树中」冻结事故缺陷面）。
                if prev_chain.get("running"):
                    if self._code_fix_running():
                        # 批在飞（code-review item 1421fde483a3）：不落终态——
                        # 此处写 blocked 会把在飞批刚置的 running=true 快照连同
                        # 批上下文（worktree/run_id）一并抹成「已终止」，而批
                        # worker 不感知开关，照常回归、合回主树再写 merging
                        # 进度，终止语义与真实在飞状态互相矛盾。改为仅追加
                        # reason=disabled 的提示性 current（合并写保留 running
                        # 与批上下文），终态改写留给批收尾后的下一次 checkpoint
                        # （自驱动 _resubmit 或下一轮 full scan）。
                        write_progress(
                            self.project_root,
                            reason="disabled",
                            current="自动修复总开关已关闭，本批收尾后终止链（不再投递后续批次）",
                        )
                    else:
                        write_progress(
                            self.project_root,
                            running=False,
                            phase="blocked",
                            reason="disabled",
                            current="自动修复总开关已关闭，链终止（可重新触发）",
                            worktree=None,
                            run_id=None,
                            batch_total=None,
                            manual_authorized=False,
                            chain_skipped=[],
                        )
                return {"triggered": False, "reason": "disabled"}
            if self._code_fix_running():
                return {"triggered": False, "reason": "already_running"}

            root = self.project_root
            # 延迟批链边界重试（fix-codefix-wipgate-defer D4/2.2）：单一调用点
            # 挂在既有节拍上，同时覆盖两个重试时机——「count_open_items==0 收敛
            # 早退之前」与「选批之前」（两判定都在其后，重试结果即时反映进 open
            # 计数与可选池）；台账空时零开销早退。位置在 already_running 守卫
            # 之后：批在飞时上方恒 already_running 早退，重试不与在飞批的建树/
            # 合回交叠；本调用仍在既有 ``self._lock`` 段内（不重入 checkpoint，
            # 无死锁面）。返回（本轮核销条数, 结果文案）：核销数并入下方链身份
            # 的 done（防 dispatch 写进度用陈旧 done 覆写），文案供两个收敛
            # 早退出口透传（D7）。
            deferred_done, deferred_msg = self._process_deferred_merges()
            total_open = count_open_items(root)
            if total_open == 0:
                # 链收尾（无 open 条目）：进度落 running=false（若曾有链）；
                # 链上状态（授权旗标/链内跳过集）随链终止一并清除。本轮刚有
                # 延迟批核销时 current 携带其结果文案（spec：进度显示「延迟批
                # 合回成功（核销 N 条）」），无延迟批时保持空串原语义。
                if _progress_path(root).exists():
                    write_progress(
                        root,
                        running=False,
                        phase="idle",
                        current=deferred_msg,
                        reason="",
                        worktree=None,
                        run_id=None,
                        batch_total=None,
                        manual_authorized=False,
                        chain_skipped=[],
                    )
                return {"triggered": False, "reason": "no_open_items"}

            # 进度链身份（D8）：同链沿用 activation_id，新链重算。判定
            # 前移到选批之前（selfheal）：新链启动先释放预算内失败档案并重置
            # chain_skipped——放在选批之后会让「上一链全跳过收敛」后的下一
            # checkpoint 恒走选批为空早退，新链分支不可达（车道锁死）。
            # （复用守卫段已读的 prev_chain——读取后中间可能经
            # _process_deferred_merges 写入 done/current/phase/reason，仅 done
            # 已按 deferred_done 补偿，其余被依赖字段重试路径不触碰，新增对
            # prev 其他字段的依赖须复核）
            prev = prev_chain
            if prev.get("running") and prev.get("activation_id"):
                activation_id = prev["activation_id"]
                # 本轮链边界重试刚核销的延迟批条目并入 done（prev 读点在重试
                # 之前，陈旧 done 若直传 dispatch 写点会覆掉重试的累加）。
                done = (prev.get("done") or 0) + deferred_done
                # 分母活口径（2026-09-25 用户事故）：total 曾沿用链起点定格
                # 快照——链在飞期间新审查轮追加的 open 条目会被本链继续处置
                # （select_batch 全 open 池选取），但分母不涨，done 追平定格
                # total 后前端恒 100%。改为 done+open：核销转移（done+1 且
                # open-1）不变分母，新 arrivals 推高、外部核销缩小；
                # deferred_done 已并入 done 且对应条目已离开 open 池
                # （total_open 统计在合并之后），口径自洽不双计。
                total = done + total_open
                batch_no = prev.get("batch_no") or 0
                chain_skipped = list(prev.get("chain_skipped") or [])
            else:
                activation_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
                total = total_open
                done = 0
                batch_no = 0
                # 新链启动：预算内失败档案自动释放（下轮自动重试，等效原人工
                # release_failed_batch）；链内跳过集随链身份更替重置为空。
                chain_skipped = []
                released = release_retryable_failed_batches(root)
                if released:
                    self._log(
                        "info",
                        f"code-fix 新链启动：释放 {released} 条预算内失败档案"
                        "（下轮自动重试）",
                    )
                # 换链/重启再认领（fix-codefix-wipgate-defer D5/4.1）：台账核对
                # 磁盘——worktree 目录仍在且 tip_sha 可解析的条目原样保留
                # （defer_count/first_deferred_at 不重置，链边界重试照常覆盖）；
                # 丢失条目清出台账（条目未核销，天然仍在 open 池，无需回写）。
                dropped = reclaim_deferred_batches(root)
                if dropped:
                    self._log(
                        "warning",
                        f"code-fix 新链启动：{dropped} 条延迟批 worktree 已丢失，"
                        "清出台账（条目保持 open，可被重新选批）",
                    )
            # 选批排除并集（D4 配套约束）：失败档案 ∪ chain_skipped ∪ 延迟台账
            # item_ids——defer 条目在合回成功前始终是 open 且不在失败档案，不
            # 排除则下一边界 earliest-first 立即重选同批、重跑 agent。
            batch = select_batch(
                root,
                cfg.get("batch_size", 20),
                exclude_ids=set(chain_skipped) | _deferred_item_ids(root),
            )
            if not batch:
                # open 条目全被排除（失败档案 ∪ chain_skipped）→ consumed 链的
                # 正常收敛出口（selfheal D5），MUST NOT 误报为故障；进度刷新为
                # 终态防前端停在陈旧的「修复中」快照，文案按排除来源区分：
                # 链内跳过/预算内档案=下轮自动重试，仅达上限档案保留人工指引
                # （reason 亦区分：failed_batch_retained=自愈等待 vs
                # failed_batch_maxed=需人工，供前端分级渲染）。
                prev_snapshot = read_progress(root)
                if prev_snapshot.get("running") or prev_snapshot.get("phase") in (
                    "failed",
                    "blocked",
                ):
                    maxed = any(
                        int(rec.get("fail_count") or 1) >= FAIL_RETRY_MAX
                        for rec in load_failed_batches(root)
                    )
                    if deferred_msg:
                        # 延迟批仍在场（本轮重试刚尝试过、仍被阻断）：收敛文案
                        # 以 defer 语义为主（D7），reason 同步 wip_gate_blocked
                        # 供前端透传；跳过/达上限信息保留后半句。
                        current = deferred_msg + (
                            "；含已达自动重试上限条目，需人工排查"
                            if maxed
                            else "；其余跳过条目下轮自动重试"
                        )
                        reason = "wip_gate_blocked"
                    elif maxed:
                        current = (
                            "open 条目均已跳过（含已达自动重试上限的条目，需人工排查）；"
                            "其余条目下轮自动重试"
                        )
                        # 含达上限条目=需人工，与纯自愈等待（failed_batch_retained）
                        # reason 区分：前端按 reason 渲染中性等待态 vs 红色需人工态
                        # （reason 漂移时前端按需人工回退，宁严勿松）。
                        reason = "failed_batch_maxed"
                    else:
                        current = "open 条目均已跳过（链内跳过/预算内失败），下轮自动重试"
                        reason = "failed_batch_retained"
                    write_progress(
                        root,
                        running=False,
                        phase="blocked",
                        reason=reason,
                        current=current,
                        worktree=None,
                        run_id=None,
                        batch_total=None,
                        manual_authorized=False,
                        chain_skipped=chain_skipped,
                    )
                return {"triggered": False, "reason": "no_open_items"}

            # 选批前 WIP 重叠预检（evo-add-codefix-batch-wip-precheck 1.1）：
            # select_batch 之后、契约守卫与批投递之前——主树脏 tracked 文件
            # 与候选批条目 file 重叠时整批推迟，把冲突消在 agent run 与回归
            # 之前（merge-time 闸门只兜 agent 实际改动超出台账 file 的残余）。
            wip_overlap = self._wip_overlap_at_select(batch)
            if wip_overlap:
                # 推迟出口（1.2/1.3）：不置单飞、不投递批 worker、不耗实现
                # 预算，台账条目保持 open，下轮节拍自然重查；不投递即无自驱动
                # 再投递，重查只随外部节拍发生（无空转面）。进度写点无条件写
                # （MUST NOT 照抄「选批为空」出口的 live 链条件——无链状态下
                # WIP 冲突不可观测，违反「推迟可观测」Requirement），字段形态
                # 纳入既有 blocked 分流文案体系（reason 前端直接透传，无需
                # 前端改动）。
                current = (
                    "选批预检：主树未提交改动与候选批重叠，整批推迟"
                    f"（提交或 stash 主树这些改动后自动恢复）："
                    f"{_fmt_overlap(wip_overlap)}"
                )
                self._log(
                    "info",
                    "code-fix 选批预检命中 WIP 重叠，整批推迟："
                    f"{_fmt_overlap(wip_overlap)}",
                )
                write_progress(
                    root,
                    running=False,
                    phase="blocked",
                    reason="wip_overlap_at_select",
                    current=current,
                    worktree=None,
                    run_id=None,
                    batch_total=None,
                    manual_authorized=False,
                    chain_skipped=chain_skipped,
                )
                return {"triggered": False, "reason": "wip_overlap_at_select"}
            batch_no += 1

            # 回归契约守卫（D5 fail-closed）：契约缺失/缺段 → 发信号、不派批
            contract = load_verify_contract(root, logger=self._logger)
            if contract is None:
                write_regression_signal(root, "verify_contract_missing", logger=self._logger)
                write_progress(
                    root,
                    running=False,
                    phase="blocked",
                    reason="regression_contract_missing",
                    current="等待 verify.yaml 契约起草完成",
                    activation_id=activation_id,
                    total=total,
                    done=done,
                    worktree=None,
                    run_id=None,
                    batch_total=None,
                    manual_authorized=False,
                    chain_skipped=chain_skipped,
                )
                return {"triggered": False, "reason": "regression_contract_missing"}
            if contract.regression is None:
                write_regression_signal(root, "verify_regression_missing", logger=self._logger)
                write_progress(
                    root,
                    running=False,
                    phase="blocked",
                    reason="regression_section_missing",
                    current="等待 verify.yaml regression 段补写完成",
                    activation_id=activation_id,
                    total=total,
                    done=done,
                    worktree=None,
                    run_id=None,
                    batch_total=None,
                    manual_authorized=False,
                    chain_skipped=chain_skipped,
                )
                return {"triggered": False, "reason": "regression_section_missing"}

            # 投递：置单飞 → 写运行中进度 → 批 worker（经 executor 或同步）。
            # 异常安全（ocr 收尾审查）：置位后任一步（进度盘写 / executor.submit）
            # 抛出时必须复位单飞，否则后续 checkpoint 恒 already_running，车道死锁。
            self._in_flight = True
            try:
                item_ids = [rec.get("item_id") for rec in batch]
                write_progress(
                    root,
                    running=True,
                    phase="selecting",
                    activation_id=activation_id,
                    total=total,
                    done=done,
                    batch_no=batch_no,
                    current=f"第 {batch_no} 批启动（{len(batch)}/{total} 条）",
                    reason="",
                    # 批上下文防御性归零（D2）：上一批收尾写点已清三键，此处
                    # 显式置 null 保证「切批 selecting 写时批上下文必为 null」
                    # （含保留 worktree 的失败批防陈旧索引）；新批上下文在建
                    # 树成功后的 fixing 写点才落。
                    worktree=None,
                    run_id=None,
                    batch_total=None,
                    # 手动授权随链持久化：本批由 override 投出，或延续 live
                    # 链已有的授权（batch 间 phase 改写不得丢失旗标）。
                    manual_authorized=bool(override_enabled) or chain_authorized,
                    # 链内跳过集：同链沿用（merge 语义下显式透传防剥落），新链
                    # 已在上分支重置为空——写入 [] 覆盖上一链残留。
                    chain_skipped=chain_skipped,
                )
                ctx = {
                    "activation_id": activation_id,
                    "total": total,
                    "done": done,
                    "batch_no": batch_no,
                    "items": batch,
                    "item_ids": item_ids,
                    "regression_spec": contract.regression,
                }
            except Exception as exc:
                self._in_flight = False
                self._log("error", f"code-fix 投递前置异常（已复位单飞）: {exc}")
                return {"triggered": False, "reason": "dispatch_prepare_error"}
        # 锁外投递（worker 内会再进 checkpoint，锁内 submit 会死锁）
        try:
            self._dispatch(ctx)
        except Exception as exc:
            # 同步模式下批 worker 自身已兜底（_run_batch 的 try/finally），
            # 走到这里的是 submit 被拒（解释器关闭）等投递层异常。
            self._in_flight = False
            self._log("error", f"code-fix 投递异常（已复位单飞）: {exc}")
            return {"triggered": False, "reason": "dispatch_error"}
        return {"triggered": True, "reason": "dispatched"}

    def _dispatch(self, ctx: dict) -> None:
        if self._executor is not None:
            self._executor.submit(self._run_batch, ctx)
        else:
            # 无 executor（测试/禁用态）：同步执行，保证 checkpoint 语义可断言
            self._run_batch(ctx)

    def _resubmit(self) -> None:
        """批收尾后的自驱动再投递（D4：经 executor 而非递归直调，避免嵌套）。"""
        if self._executor is not None:
            self._executor.submit(self.checkpoint)
        else:
            self.checkpoint()

    # -- 批 worker（5.4/5.6/5.8）-------------------------------------------

    def _finish(self, phase: str, reason: str = "", **fields) -> None:
        """halt 收尾（链终止）：复位单飞 + 刷新进度（running 由下次 checkpoint 收尾）。

        仅环境性失败路径使用（worktree_manager_missing / worktree_create_failed /
        批 worker 异常，selfheal D1）：链终止、不自驱动，授权旗标一并清除；
        批上下文三键同步清除——不清则读侧会带着陈旧 worktree/run_id 继续合成
        条级字段（D2 防陈旧索引）。consumed 失败收尾走 ``_consumed_progress``
        （链继续，不请旗标）。
        """
        self._in_flight = False
        write_progress(
            self.project_root,
            phase=phase,
            reason=reason,
            worktree=None,
            run_id=None,
            batch_total=None,
            manual_authorized=False,
            **fields,
        )

    def _consumed_progress(self, current: str, reason: str = "", chain_skip_ids=None) -> None:
        """consumed 失败收尾（selfheal D6）：链内跳过 + 非终态进度，链继续。

        与 ``_finish``（halt 终态）相对：不复位 running、不清 manual_authorized
        （链上授权随自驱动继续生效）；``chain_skip_ids`` 非 None 时把该批条目
        并入进度快照 ``chain_skipped``（原子写合并语义，本链 select_batch 不再
        选中，新链启动时重置）；批上下文三键同步清除（worktree 已 cleanup，
        D2 防陈旧索引）。
        """
        self._in_flight = False
        fields = {}
        if chain_skip_ids is not None:
            prev_ids = read_progress(self.project_root).get("chain_skipped") or []
            fields["chain_skipped"] = list(
                dict.fromkeys(
                    [str(i) for i in prev_ids] + [str(i) for i in chain_skip_ids]
                )
            )
        write_progress(
            self.project_root,
            phase="fixing",
            reason=reason,
            current=current,
            worktree=None,
            run_id=None,
            batch_total=None,
            **fields,
        )

    # -- 延迟合回（fix-codefix-wipgate-defer D4/D6）-------------------------

    def _process_deferred_merges(self):
        """链边界重试延迟批合回：遍历台账逐条对保留 worktree 重跑 merge_back。

        不重跑 agent（产物已提交在分支上，只差合回）；不新增线程/定时器，
        挂在既有链节拍上（调用点见 checkpoint：选批之前 ∪ 收敛早退之前）。
        逐条 try/except 兜底（同 ``_safe_cleanup`` 哲学：单条异常记 warning
        后继续下一条，不炸链节拍）。

        Returns: ``(deferred_done, deferred_msg)``——本轮累计核销条数（供调用
        方并入链 done）与末条结果文案（供收敛早退出口透传，D7）；台账空时
        ``(0, "")``（零开销早退）。
        """
        root = self.project_root
        entries = load_deferred_batches(root)
        if not entries:
            return 0, ""
        wm = getattr(self._agent_runner, "worktree_manager", None)
        if wm is None:
            return 0, ""
        done_hits = 0
        last_msg = ""
        for entry in entries:
            try:
                hit, msg = self._retry_one_deferred(wm, entry)
            except Exception as e:  # noqa: BLE001 — 单条重试异常不炸链节拍
                self._log(
                    "warning",
                    f"code-fix 延迟批重试异常（branch="
                    f"{entry.get('branch')}）: {e}",
                )
                continue
            done_hits += hit
            if msg:
                last_msg = msg
        return done_hits, last_msg

    def _retry_one_deferred(self, wm, entry) -> tuple:
        """单条延迟批重试，结果四分派（D4/2.1）。返回 ``(核销数, 结果文案)``。"""
        root = self.project_root
        item_ids = [str(i) for i in entry.get("item_ids") or []]
        fixed_ids = [str(i) for i in entry.get("fixed_ids") or []]
        wt = Path(str(entry.get("worktree") or ""))
        branch = str(entry.get("branch") or "")
        tip_sha = str(entry.get("tip_sha") or "")
        overlap = list(entry.get("last_overlap") or [])

        # 磁盘真相对账：worktree 已丢失（手删/sweeper 回收）→ 条目回收 +
        # warning；条目未核销天然仍在 open 池，无需回写（D5 同款判据）。
        # 判死移出台账的同时回收仍在 _active_worktrees 在册的 worktree
        # （sweeper 扫孤儿跳过在册目录）：不清理则带修复提交的目录成孤儿，
        # 永无人合回也永无人回收；目录已不在磁盘时跳过（只省噪音日志）。
        if not _deferred_entry_alive(entry):
            if wt.name and wt.exists():
                _safe_cleanup(wm, wt, success=False, logger=self._logger)
            _remove_deferred_batch(root, item_ids)
            self._log(
                "warning",
                f"code-fix 延迟批 worktree 已丢失，条目移出台账"
                f"（条目保持 open，可被重新选批）: {wt}",
            )
            return 0, ""

        # 预算时间门（D6/3.1，先到为准）：超时即降级，不再尝试 merge_back。
        if _defer_time_budget_exhausted(entry):
            self._downgrade_deferred(wm, entry, item_ids, wt, branch, tip_sha, overlap)
            return 0, f"延迟批合回超预算已入失败档案（branch={branch}）"

        merge_info = wm.merge_back(wt)
        if getattr(merge_info, "success", False):
            # 成功 → 核销 fixed_ids 中仍 open 的子集。defer 窗口内被人工置
            # 终态的条目跳过：mark_resolved 对命中 id 无条件置 resolved、无
            # 终态保护，核销方 MUST 先以 read_items 过滤（不能依赖其幂等）。
            hit = 0
            if fixed_ids:
                try:
                    items = read_items(root)
                except Exception:  # noqa: BLE001 — 台账读失败按空集（不核销）
                    items = {}
                still_open = [
                    i for i in fixed_ids
                    if (items.get(i) or {}).get("status") == "open"
                ]
                if still_open:
                    hit = mark_resolved(root, still_open)
            _safe_cleanup(wm, wt, success=True, logger=self._logger)
            _remove_deferred_batch(root, item_ids)
            prog = read_progress(root)
            write_progress(
                root,
                done=(prog.get("done") or 0) + hit,
                reason="",
                current=f"延迟批合回成功（核销 {hit} 条）",
            )
            self._log(
                "info",
                f"code-fix 延迟批合回成功：核销 {hit}/{len(item_ids)} 条"
                f"（branch={branch}）",
            )
            return hit, f"延迟批合回成功（核销 {hit} 条）"

        if bool(getattr(merge_info, "wip_gate_blocked", False)):
            # 仍被阻断：本次确有实际 merge_back 尝试 → defer_count +1（2.3）；
            # first_deferred_at 不动（超时判定只看它）；达次数门降级，否则
            # 台账原样保留等下一边界。
            defer_count = int(entry.get("defer_count") or 0) + 1
            _patch_deferred_entry(root, item_ids, defer_count=defer_count)
            if defer_count >= DEFER_RETRY_MAX:
                self._downgrade_deferred(
                    wm, entry, item_ids, wt, branch, tip_sha, overlap
                )
                return 0, f"延迟批合回超预算已入失败档案（branch={branch}）"
            msg = (
                f"延迟批合回待重试（主树未提交改动：{_fmt_overlap(overlap)}）"
                "— 已保留，主树清理后自动合回"
            )
            write_progress(root, phase="merging", reason="wip_gate_blocked", current=msg)
            return 0, msg

        # 失败且非 wip_gate_blocked（主树 WIP 已被提交后的内容真冲突经预演
        # 闸、或其他 git 失败）→ 按真冲突同语义降级入失败档案（烧预算），
        # worktree 走既有失败收尾，台账移除。
        # 失败档案只收未终态条目（code-review item c94a1770a477，与主路径
        # pending_ids / 65f65b784f2a 核销前过滤同口径）：defer 窗口内被人工
        # 置终态的条目不随批入档。
        try:
            ledger = read_items(root)
        except Exception:  # noqa: BLE001 — 台账读失败按空集（不入档）
            ledger = {}
        open_ids = [
            i for i in item_ids
            if (ledger.get(i) or {}).get("status") == "open"
        ]
        if open_ids:
            record_failed_batch(
                root, open_ids, wt,
                reason="merge_back_conflict", branch=branch, tip_sha=tip_sha,
            )
        _safe_cleanup(wm, wt, success=False, logger=self._logger)
        _remove_deferred_batch(root, item_ids)
        self._log(
            "error",
            f"code-fix 延迟批合回落真冲突，已入失败档案"
            f"（branch={branch}, tip_sha={tip_sha}）",
        )
        return 0, ""

    def _downgrade_deferred(
        self, wm, entry, item_ids, wt: Path, branch, tip_sha, overlap
    ) -> None:
        """预算双门耗尽降级（D6/3.1）：入失败档案 + 遗产收尾 + 台账移除。

        ``record_failed_batch(reason="wip_gate_blocked_expired")`` 走既有预算
        体系（FAIL_RETRY_MAX 之后是既有 blocked 出口）；``cleanup(success=False)``
        走 implementer 遗产分支，目录由 sweeper 宽限兜底回收。告警一次性按
        条目集指纹（3.2：先查后记，见 ``_has_expired_archive``）。
        """
        root = self.project_root
        # 失败档案只收未终态条目（code-review item c94a1770a477，与主路径
        # pending_ids / 65f65b784f2a 核销前过滤同口径）：defer 窗口内被人工
        # 置终态的条目不随批入档、不进一次性告警名录。
        try:
            ledger = read_items(root)
        except Exception:  # noqa: BLE001 — 台账读失败按空集（不入档）
            ledger = {}
        open_ids = [
            i for i in item_ids
            if (ledger.get(i) or {}).get("status") == "open"
        ]
        first_expire = bool(open_ids) and not _has_expired_archive(root, open_ids)
        if open_ids:
            record_failed_batch(
                root, open_ids, wt,
                reason="wip_gate_blocked_expired", branch=branch, tip_sha=tip_sha,
            )
        _safe_cleanup(wm, wt, success=False, logger=self._logger)
        _remove_deferred_batch(root, item_ids)
        if first_expire:
            _write_defer_expired_alert(root, open_ids, overlap, branch, tip_sha)
        write_progress(
            root,
            reason="wip_gate_blocked_expired",
            current=f"延迟批合回超预算已入失败档案（branch={branch}）",
        )
        self._log(
            "warning",
            f"code-fix 延迟批合回超预算（90 分钟或 {DEFER_RETRY_MAX} 次重试），"
            f"降级入失败档案: branch={branch}",
        )

    def _defer_merge_back(
        self, wm, wt: Path, ctx: dict, merge_info, fixed_ids: list, pending_ids: list
    ) -> str:
        """批收尾 wip_gate_blocked 收尾（defer 路径，D1/D3）：保留现场 + 记
        台账 + 放锁 + 首次 info 告警。返回 "consumed"（链继续后续批）。

        保留：worktree 目录/分支/``_active_worktrees`` 在册（sweeper 扫孤儿
        跳过在册目录；重试收尾 ``wm.cleanup`` 语义不变）。放锁 MUST：``create()``
        对同键命中即返回 None、批 worker 对 None 走 halt 终止链——不放锁则
        defer 后下一批建树必败，整条车道在主树脏期间死锁（比现状更糟）。
        """
        root = self.project_root
        batch_no = ctx["batch_no"]
        overlap = list(getattr(merge_info, "wip_overlap", []) or [])
        tip_sha = _worktree_head(wt)
        branch = _worktree_branch(wt)
        # 台账先落（磁盘真相源），随后放锁/告警/进度。
        record_deferred_batch(
            root, pending_ids, fixed_ids, wt,
            branch=branch, tip_sha=tip_sha, last_overlap=overlap,
        )
        try:
            wm.release_spec_lock("code-review-fix", "code-fix")
        except Exception as e:  # noqa: BLE001 — 放锁失败不影响 defer 记账，
            # 但车道可能死锁，必须留痕供排查。
            self._log("warning", f"code-fix defer 放锁异常（车道可能死锁）: {e}")
        # 首次 defer 即发 info 提示（1.3）：含交集文件清单与人工处置话术。
        _write_defer_info_alert(root, pending_ids, overlap, branch=branch)
        write_progress(
            root,
            phase="merging",
            reason="wip_gate_blocked",
            current=(
                f"第 {batch_no} 批合回待重试（主树未提交改动："
                f"{_fmt_overlap(overlap)}）— 已保留，主树清理后自动合回"
            ),
            # 批上下文三键清除：agent run 已结束，保留现场由台账承载（防读
            # 侧按陈旧 run_id 合成条级进度，D2 同款防陈旧索引）。
            worktree=None,
            run_id=None,
            batch_total=None,
        )
        self._log(
            "warning",
            f"code-fix 第 {batch_no} 批合回被主树未提交改动挡住"
            f"（重叠 {_fmt_overlap(overlap)}），批保留待自动合回"
            f"（不烧失败预算）: branch={branch}",
        )
        return "consumed"

    def _run_batch(self, ctx: dict) -> None:
        batch_no = ctx["batch_no"]
        outcome = "halt"
        try:
            outcome = self._run_batch_inner(ctx)
        except Exception as e:  # noqa: BLE001 — 批异常兜底：不炸线程池/不挂死单飞
            self._log("error", f"批 worker 异常（第 {batch_no} 批）: {e}")
            self._finish("failed", reason=f"batch_worker_error: {e}")
            outcome = "halt"
        finally:
            self._in_flight = False
        # 自驱动链（selfheal D1/D4）：success 与 consumed 均推进下一批——
        # consumed 批的条目已全部离开可选池（失败档案 ∪ chain_skipped），
        # 可选池严格单调缩小，再投递循环必然收敛；原「失败即终止」的无限
        # 递归/空转顾虑只对「条目未离开可选池的失败」（halt：如
        # worktree_create_failed 每轮复现同批）成立，halt 保持终止链、条目
        # 保持 open，由下一轮 full scan 兜底重试。
        if outcome in ("success", "consumed"):
            self._resubmit()

    def _run_batch_inner(self, ctx: dict) -> str:
        """执行一批；返回三态收尾（selfheal D1）。

        ``"success"`` 批成功合回并核销；``"consumed"`` 该批条目已全部离开
        可选池（可推进下一批）；``"halt"`` 环境性失败（链终止，条目保持 open）。
        """
        root = self.project_root
        runner = self._agent_runner
        batch_no = ctx["batch_no"]
        items = ctx["items"]
        total = ctx["total"]

        # 建树（5.4）：create() 返回 None 即收尾——不派 run、不合回、条目保持
        # open、复位单飞，进度 failed（halt：下一轮 full scan 重试）。
        wm = getattr(runner, "worktree_manager", None)
        if wm is None:
            self._finish("failed", reason="worktree_manager_missing")
            return "halt"
        wt = wm.create(spec_name="code-review-fix", agent_type="code-fix")
        if wt is None:
            self._log("warning", "code-fix: worktree 创建失败（锁占用或 git 失败）")
            self._finish("failed", reason="worktree_create_failed")
            return "halt"
        wt = Path(wt)
        # 批上下文落盘（task 2.1）：phase="fixing" 写点整体后移至建树成功
        # 之后、agent run 启动之前——原写点位于建树前，彼时 worktree/run_id
        # 均不存在。run_id 由编排器预生成（_preset_run_id，code-fix- 前缀 +
        # 同口径去重）并经 run_code_fix 既有 run_id 形参传入（缺省在其内部
        # 生成、run 返回前编排器无从得知），保证 run 在飞期间进度文件已可
        # 解析（读侧定位 out 文件实时合成条级进度）。
        # 三条前置语句（code-review item cc79d58138f1）：_preset_run_id /
        # write_progress（_atomic_write 盘写）/ _worktree_head 均可能抛异常
        # （OSError/ImportError 等），MUST 位于 try 内——否则异常绕过
        # _safe_cleanup，create() 已登记的 code-review-fix:code-fix spec 锁
        # 永久滞留（后续 create() 恒 None，车道死锁）。
        try:
            run_id = _preset_run_id(runner)
            write_progress(
                root,
                phase="fixing",
                current=f"第 {batch_no} 批修复中（{len(items)}/{total} 条）",
                worktree=str(wt),
                run_id=run_id,
                batch_total=len(items),
            )
            created_sha = _worktree_head(wt)
            return self._run_batch_created(wm, wt, created_sha, ctx, run_id=run_id)
        except Exception:
            # 未预期异常兜底（ocr 收尾审查）：create() 已登记 code-review-fix:code-fix
            # spec 锁，仅 cleanup() 释放——漏掉则下一批 create() 恒 None（车道死锁）。
            # 枚举失败分支各自已按语义 cleanup，不经此路径。
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            raise

    def _run_batch_created(self, wm, wt: Path, created_sha, ctx: dict, run_id: str) -> str:
        """执行已建树批次的主体（首次/重试 run、回归、守卫、合回核销清理）。

        返回三态收尾（selfheal D1，语义见 ``_run_batch_inner``）。由
        _run_batch_inner 在建树成功后调用；未预期异常在本层被兜底 cleanup 后
        原样上抛（_run_batch 收口）。``run_id`` 为编排器预生成的首轮 run 标识
        （进度文件已携带同值）。
        """
        root = self.project_root
        runner = self._agent_runner
        batch_no = ctx["batch_no"]
        items = ctx["items"]
        item_ids = ctx["item_ids"]
        total = ctx["total"]
        done = ctx["done"]
        reg_spec = ctx["regression_spec"]

        # 第一次修复 run（run_id 预生成传入，与进度文件 run_id 一致）
        result = runner.run_code_fix(wt, items, run_id=run_id)
        if not result.success:
            self._log("error", f"code-fix run 失败（run {result.run_id}）: {result.error}")
            # agent run 失败（瞬态，selfheal D3）：不合回不核销；条目入
            # chain_skipped（链内跳过，不烧跨轮预算）；清理 worktree 释放
            # spec 锁（否则下一批 create() 恒 None，车道死锁）；consumed：
            # 链继续推进下一批。
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            self._consumed_progress(
                current=f"第 {batch_no} 批失败已跳过（run 失败）— 继续后续批次",
                reason=f"agent_run_failed: {result.error}"[:500],
                chain_skip_ids=item_ids,
            )
            return "consumed"

        # 第一次全量回归（执行根=worktree、锁根=主树，D10）
        retry_run_id: str | None = None
        write_progress(
            root,
            phase="regressing",
            current=f"第 {batch_no} 批全量回归中（{len(items)}/{total} 条）",
        )
        reg = runner.run_regression(
            reg_spec, reason="code-fix", project_root=wt, lock_root=root
        )
        if reg.status != "passed":
            # 5.6：同一 worktree 内重试一次（prompt 注入失败用例摘要）
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批首次回归未通过（{reg.status}），重试一次",
            )
            summary = _failure_summary(reg)
            # 重试轮 run_id 变更（task 2.2）：新预生成并刷新进度（worktree/
            # batch_total 不变），保证重试 run 在飞期间读侧解析的是当前轮
            # out 文件（fix-out-<retry_run_id>.jsonl），而非首轮残留。exclude
            # 排除首轮 run_id（同 worktree 内主树残留判据覆盖不到，同秒撞名
            # 会复用首轮 out 文件）。
            retry_run_id = _preset_run_id(runner, exclude=(run_id,))
            write_progress(
                root,
                phase="retrying",
                current=f"第 {batch_no} 批回归失败重试中（{len(items)}/{total} 条）",
                run_id=retry_run_id,
            )
            retry_result = runner.run_code_fix(
                wt, items, failure_summary=summary, run_id=retry_run_id
            )
            if not retry_result.success:
                self._log(
                    "error",
                    f"code-fix 重试 run 失败（run {retry_result.run_id}）: {retry_result.error}",
                )
                # run 失败（第二次回归根本没跑）≠「两次回归均失败」：不入失败
                # 档案（不烧跨轮预算），与首次 run 失败同语义——条目入
                # chain_skipped；清理 worktree 释放 spec 锁（否则
                # code-review-fix:code-fix 被永久持有，下一批 create() 恒返回
                # None，车道首批后即死）；consumed：链继续。
                _safe_cleanup(wm, wt, success=False, logger=self._logger)
                self._consumed_progress(
                    current=f"第 {batch_no} 批失败已跳过（重试 run 失败）— 继续后续批次",
                    reason=f"regression_retry_run_failed: {retry_result.error}"[:500],
                    chain_skip_ids=item_ids,
                )
                return "consumed"
            retry_run_id = retry_result.run_id
            reg = runner.run_regression(
                reg_spec, reason="code-fix", project_root=wt, lock_root=root
            )
            if reg.status != "passed":
                # 两次均失败 → 现场即弃（selfheal D2）：cleanup **前**把
                # branch/tip_sha 连同 reason 写入失败档案（fail_count 预算），
                # 随后清理 worktree 释放锁——不再保留现场待人工（锁死车道），
                # 丢弃的修复提交由下轮重试重新生成，tip_sha 留作 reflog 追溯。
                # consumed：条目已入档案（离开可选池），链继续推进下一批。
                self._log(
                    "error",
                    f"code-fix 第 {batch_no} 批两次回归均未通过，现场即弃"
                    f"（branch/tip_sha 入档案，worktree 清理: {wt}）",
                )
                summary2 = _failure_summary(reg)
                tip_sha = _worktree_head(wt)
                branch = _worktree_branch(wt)
                record_failed_batch(
                    root, item_ids, wt,
                    reason="regression_failed_twice", branch=branch, tip_sha=tip_sha,
                )
                write_regression_failed_alert(
                    root, item_ids, wt, summary2, branch=branch, tip_sha=tip_sha
                )
                _safe_cleanup(wm, wt, success=False, logger=self._logger)
                self._consumed_progress(
                    current=f"第 {batch_no} 批失败已跳过（两次回归未通过）— 继续后续批次",
                    reason=f"regression_failed_twice: {reg.status}",
                )
                return "consumed"

        # 5.8 零有效修复守卫（合回之前）：产物行至少一条 fixed 且分支相对
        # 建树点有提交。merge_back 对「分支已是 HEAD 祖先」返回成功——无此
        # 守卫，全 skipped 的批会以「零改动合并成功 + 回归必过」白洗 resolved。
        rows = read_fix_out(wt, result.run_id)
        if retry_run_id:
            # 重试轮产物是独立文件（fix-out-<retry_run_id>.jsonl）：两轮改动都落在
            # 同一 worktree、随同一次合回进主树，故核销按**并集**口径；只读首次
            # run 会漏掉「重试才修复」的条目（已合回却仍留 open，被反复重派）。
            rows.extend(read_fix_out(wt, retry_run_id))
        # LLM 拒绝出口（2026-09-23）：skipped 且显式标注可忽略原因的条目在
        # 批收尾即置 ignored 终态（不等合回——ignored 与代码变更无关），从
        # 本批后续的失败档案/chain_skipped 集合中排除（已终态，MUST NOT 随批
        # 作废被重试重做）。分区口径见 _split_fix_rows。
        fixed_ids, skip_reasons = _split_fix_rows(rows)
        ignore_ids = list(dict.fromkeys(skip_reasons))
        ignored = mark_ignored(root, ignore_ids, reasons=skip_reasons) if ignore_ids else 0
        ignore_set = set(ignore_ids)
        pending_ids = [iid for iid in item_ids if iid not in ignore_set]
        commits = _worktree_commit_count(wt, created_sha) if created_sha else 0
        if not fixed_ids or commits <= 0:
            if not pending_ids:
                # 全批 skipped 均为可忽略原因：条目已尽置 ignored（终态）、
                # 无代码改动可合回——批按完成收尾（非失败，不烧重试预算）。
                _safe_cleanup(wm, wt, success=True, logger=self._logger)
                self._consumed_progress(
                    current=(
                        f"第 {batch_no} 批完成（误报/不值得修 {ignored} 条已忽略，"
                        f"无需合回）— 继续后续批次"
                    ),
                    reason="",
                )
                return "consumed"
            # 零有效修复拒合回（selfheal：链内跳过而非终止链）——零产物批按
            # halt 终止链，因选批 earliest-first 会永久堵在队列头，违背「单批
            # 失败不堵塞车道」目标；条目入 chain_skipped 随下一链重试（已置
            # ignored 的条目除外——已终态不重试）。
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批零有效修复（fixed={len(fixed_ids)}, "
                f"commits={commits}, ignored={ignored}），拒合回",
            )
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            self._consumed_progress(
                current=f"第 {batch_no} 批失败已跳过（无有效修复）— 继续后续批次",
                reason="no_effective_fix",
                chain_skip_ids=pending_ids,
            )
            return "consumed"

        # 合回（既有 merge-back 闸门不绕过）→ 核销 fixed 条目 → 清理 worktree
        write_progress(
            root,
            phase="merging",
            current=f"第 {batch_no} 批合回中（{len(items)}/{total} 条）",
        )
        merge_info = wm.merge_back(wt)
        if not getattr(merge_info, "success", False):
            # 合回失败分类（fix-codefix-wipgate-defer D1）：先读
            # wip_gate_blocked 标志分派（不解析 error 字符串——脆弱；getattr
            # 缺省 False 对旧类型对象容错）。True=主树 WIP overlap 预检阻断，
            # 可等待自愈的暂态，走 defer 路径零预算；False=真冲突，既有
            # 「现场即弃」语义逐字保留。
            if bool(getattr(merge_info, "wip_gate_blocked", False)):
                return self._defer_merge_back(
                    wm, wt, ctx, merge_info,
                    fixed_ids=fixed_ids, pending_ids=pending_ids,
                )
            # 合回冲突 → 现场即弃（selfheal D2）：cleanup 前把 branch/tip_sha
            # 写入失败档案（fail_count 预算），随后清理 worktree 释放锁——
            # 不再保留现场待人工（原语义锁死车道至 daemon 重启）。consumed：
            # 条目已入档案，链继续。
            self._log("error", f"code-fix 第 {batch_no} 批合回冲突，现场即弃（branch/tip_sha 入档案）")
            tip_sha = _worktree_head(wt)
            branch = _worktree_branch(wt)
            # 失败档案只收未终态条目（已置 ignored 的不随批作废重试）
            record_failed_batch(
                root, pending_ids, wt,
                reason="merge_back_conflict", branch=branch, tip_sha=tip_sha,
            )
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            self._consumed_progress(
                current=f"第 {batch_no} 批失败已跳过（合回冲突）— 继续后续批次",
                reason="merge_back_conflict",
            )
            return "consumed"
        # 核销前过滤（code-review item 65f65b784f2a，与 defer 路径同口径）：
        # mark_resolved 对命中 id 无条件置 resolved、无终态保护，核销方 MUST
        # 先以 read_items 过滤——选批到合回之间被并发置 in_spec/ignored 的条目
        # 跳过（不丢 spec_name 归属），agent 产物带出的批外 id 不核销不计进度。
        try:
            ledger = read_items(root)
        except Exception:  # noqa: BLE001 — 台账读失败按空集（不核销）
            ledger = {}
        batch_set = set(item_ids)
        still_open = [
            i for i in fixed_ids
            if i in batch_set and (ledger.get(i) or {}).get("status") == "open"
        ]
        hit = mark_resolved(root, still_open) if still_open else 0
        _safe_cleanup(wm, wt, success=True, logger=self._logger)
        new_done = done + hit
        write_progress(
            root,
            phase="merging",
            done=new_done,
            current=f"第 {batch_no} 批完成（已核销 {hit} 条，累计 {new_done}/{total}）",
            reason="",
            # 批收尾清除批上下文（D2）：worktree 已 cleanup、out 随之不可达，
            # 条级字段让位给批级进度（spec「批收尾后条级字段让位」）。
            worktree=None,
            run_id=None,
            batch_total=None,
        )
        self._log(
            "info",
            f"code-fix 第 {batch_no} 批合回成功：resolved {hit}/{len(items)} 条"
            + (f"（另 ignored {ignored} 条）" if ignored else ""),
        )
        return "success"


def _safe_cleanup(wm, wt, success: bool, logger=None) -> None:
    """cleanup 包裹：异常只记日志不炸批 worker（锁泄漏比异常更糟，宁可多试）。"""
    try:
        wm.cleanup(wt, success=success)
    except Exception as e:  # noqa: BLE001
        if logger is not None:
            try:
                logger.warning("code-fix", f"worktree cleanup 失败（{wt}）: {e}")
            except Exception:  # noqa: BLE001 — 日志失败不影响批收尾
                pass


def _failure_summary(reg) -> str:
    """从回归快照提取失败用例摘要（重试 prompt 注入用，截断防爆炸）。"""
    snap = getattr(reg, "snapshot", None) or {}
    failures = snap.get("failures") or []
    lines = []
    for f in failures[:20]:
        if isinstance(f, dict):
            lines.append(
                f"- {f.get('classname', '')}::{f.get('name', '')}: "
                f"{str(f.get('message', ''))[:200]}"
            )
        else:
            lines.append(f"- {str(f)[:200]}")
    head = f"status={getattr(reg, 'status', 'failed')}"
    if not lines:
        return head + "（无失败用例明细）"
    return head + "\n" + "\n".join(lines)
