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

契约要点（design「契约要点」节，实现者必读）：
- **绝不空集合回**：批内零有效产物行或零有效修复（产物行全 skipped /
  worktree 分支相对建树点无提交）→ MUST NOT 合回、MUST NOT 置 resolved
  （`merge_back` 对「分支已是 HEAD 祖先」返回成功，无守卫会把全 skipped
  的批白洗成 resolved）。
- **resolved 只能由合回成功驱动**；skipped 条目保持 open。
- **失败批保留集合**：两次回归均失败的批 item_ids 落
  `.fenix/code-review/fix-failed.json`，`select_batch` 跳过（防重复派发）；
  不接 UI 且车道自身不释放 → MUST 同时在 `.fenix/todo.md` 登记待人工清理。
"""

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from core.code_review import mark_resolved, read_items
from core.config import ConfigLoader
from core.verify_contract import load_verify_contract

# 进度快照（单文件覆盖式，与 .fenix/regression/last-run.json 同型，D8）
FIX_PROGRESS_REL = ".fenix/code-review/fix-progress.json"
# 失败批保留集合（两次回归均失败，D6/D3：保留现场 + 条目跳过）
FIX_FAILED_REL = ".fenix/code-review/fix-failed.json"

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
    """
    out = dict(FIX_PROGRESS_DEFAULT)
    try:
        raw = _progress_path(project_root).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        _synthesize_item_progress(project_root, out)
        return out
    if isinstance(data, dict):
        for k in FIX_PROGRESS_DEFAULT:
            if k in data:
                out[k] = data[k]
    _synthesize_item_progress(project_root, out)
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
    """
    progress["item_done"] = None
    progress["current_item"] = None
    if progress.get("running") is not True:
        return
    worktree = progress.get("worktree")
    run_id = progress.get("run_id")
    if not worktree or not run_id:
        return
    try:
        rows = read_fix_out(worktree, run_id)
    except Exception:  # noqa: BLE001 — 读产物任何异常都兜底为明细不可得
        return
    if not rows:
        return
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
    """失败保留集合中的全部 item_id 并集（select_batch 的排除源）。"""
    ids: set = set()
    for rec in load_failed_batches(project_root):
        for iid in rec.get("item_ids") or []:
            if isinstance(iid, str):
                ids.add(iid)
    return ids


def record_failed_batch(project_root, item_ids, worktree) -> None:
    """把「两次回归均失败」的批落盘到 fix-failed.json（原子写，追加式）。

    同时在 `.fenix/todo.md` 登记待人工清理项：失败集合不接 UI 且车道自身
    不会释放，无人工项时该批条目会被永久跳过（tasks 5.7 硬约束）。
    """
    records = load_failed_batches(project_root)
    records.append(
        {
            "item_ids": list(item_ids),
            "worktree": str(worktree),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    _atomic_write(
        _failed_path(project_root),
        json.dumps(records, ensure_ascii=False, indent=2),
    )
    _append_todo_entry(project_root, item_ids, worktree)


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


def _append_todo_entry(project_root, item_ids, worktree) -> None:
    """在 .fenix/todo.md 追加待人工清理项（含 worktree 路径与解除用法）。"""
    todo_path = Path(project_root) / ".fenix" / "todo.md"
    ids_txt = ", ".join(str(i) for i in item_ids)
    entry = (
        "\n## [code-fix] 失败批待人工清理（add-code-review-auto-fix）\n\n"
        f"- 记录时间：{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"- 保留 worktree：`{worktree}`（两次全量回归均未通过，未合回；"
        "排查后可手工提取修复或直接删除该 worktree）\n"
        f"- 被跳过的条目集合（保持 open，车道不再自动重派）：{ids_txt}\n"
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


def select_batch(project_root, batch_size: int) -> list:
    """从台账选下一批：open 条目按 first_seen_at 升序（缺失回退 item_id
    稳定排序）取前 batch_size 条，排除失败保留集合中的条目（5.7 防重派）。

    返回条目 record 列表（含 item_id/file/line/severity/category/title/
    description/suggestion 等 prompt 注入字段）。
    """
    try:
        items = read_items(project_root)
    except Exception:  # noqa: BLE001 — 台账读失败按无条目处理（fail-closed）
        return []
    excluded = _failed_item_ids(project_root)
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


# ── 回归契约缺失信号（5.5 / D5，分流口径对齐 regression_routes 既有区分）──


def _signal_inflight(store, signal_type: str, project_name: str) -> bool:
    """同项目同类型、未摄取未处置的在途信号已存在 → 不重复写。"""
    from core.admin_store import SIGNAL

    for rec in store.read_all():
        if rec.get("kind") != SIGNAL or rec.get("signal_type") != signal_type:
            continue
        if rec.get("handled") or rec.get("escalated"):
            continue
        if f"项目名={project_name}" in str(rec.get("evidence") or ""):
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


def write_regression_failed_alert(project_root, item_ids, worktree, failures_summary: str) -> None:
    """回归两次均失败丢弃批时写失败告警（D6：major，附 worktree 路径与失败用例）。"""
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_regression_failed",
            "spec": None,
            "severity": "major",
            "description": (
                "code-fix 批两次全量回归均未通过，已丢弃（未合回、条目保持 open，"
                "worktree 保留待人工排查）"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; worktree={worktree}; "
                f"item_ids={', '.join(str(i) for i in item_ids)}; "
                f"失败用例摘要: {failures_summary[:2000]}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "人工排查保留 worktree 中的修复（可手工提取后走正常流程），处置完成后"
                "调用 core.code_fix.release_failed_batch 解除该批条目的跳过"
            ),
        }
    )


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

    def _get_config(self) -> dict:
        """解析 admin.code_review_fix 生效值（config 可为 dict / callable / None）。

        None 时从 agent_runner 的运行时配置读取（daemon 装配形态）。
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
                raw = root
            else:
                # 退化：runner 无根 config 属性（测试替身）时，把子段回包成根形态
                try:
                    seg = runner._get_config("admin.code_review_fix", {})
                except Exception:  # noqa: BLE001 — 测试 fake runner 可能无此方法
                    seg = {}
                raw = {"admin": {"code_review_fix": seg}} if isinstance(seg, dict) else {}
        return ConfigLoader.get_code_review_fix_config(raw or {})

    def _code_fix_running(self) -> bool:
        """在途判据：编排器单飞标记或 runner 侧存在 code-fix- 前缀 run。"""
        if self._in_flight:
            return True
        running = getattr(self._agent_runner, "_running_agents", None) or {}
        return any(str(rid).startswith("code-fix-") for rid in running)

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
                    )
                return {"triggered": False, "reason": "disabled"}
            if self._code_fix_running():
                return {"triggered": False, "reason": "already_running"}

            root = self.project_root
            total_open = count_open_items(root)
            if total_open == 0:
                # 链收尾（无 open 条目）：进度落 running=false（若曾有链）
                if _progress_path(root).exists():
                    write_progress(
                        root,
                        running=False,
                        phase="idle",
                        current="",
                        reason="",
                        worktree=None,
                        run_id=None,
                        batch_total=None,
                        manual_authorized=False,
                    )
                return {"triggered": False, "reason": "no_open_items"}

            batch = select_batch(root, cfg.get("batch_size", 20))
            if not batch:
                # open 条目全部被失败保留集合排除 → 静默空转（等待人工解除）。
                # 进度顺带刷新为终态（ocr 收尾审查）：链曾置 running=true，若维持
                # 旧快照，前端会停在「第 N 批修复中」的陈旧文案上。
                prev_snapshot = read_progress(root)
                if prev_snapshot.get("running") or prev_snapshot.get("phase") in (
                    "failed",
                    "blocked",
                ):
                    write_progress(
                        root,
                        running=False,
                        phase="blocked",
                        reason="failed_batch_retained",
                        current="open 条目均在失败保留集合中，待人工 release_failed_batch",
                        worktree=None,
                        run_id=None,
                        batch_total=None,
                        manual_authorized=False,
                    )
                return {"triggered": False, "reason": "no_open_items"}

            # 进度链身份：同链沿用 total/activation_id，新链重算
            # （复用守卫段已读的 prev_chain——中间无其他进度写者）
            prev = prev_chain
            if prev.get("running") and prev.get("activation_id"):
                activation_id = prev["activation_id"]
                total = prev.get("total") or total_open
                done = prev.get("done") or 0
                batch_no = prev.get("batch_no") or 0
            else:
                activation_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
                total = total_open
                done = 0
                batch_no = 0
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
        """批收尾：复位单飞 + 刷新进度（running 保持链语义，由下次 checkpoint 收尾）。

        链终止（失败批不再自驱动），授权旗标一并清除；批上下文三键同步
        清除——本函数是全部失败收尾的唯一出口且**不置 running=false**，
        不清则读侧会带着陈旧 worktree/run_id 继续合成条级字段（保留现场
        的失败批尤其如此，D2 防陈旧索引）。
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

    def _run_batch(self, ctx: dict) -> None:
        batch_no = ctx["batch_no"]
        ok = False
        try:
            ok = self._run_batch_inner(ctx)
        except Exception as e:  # noqa: BLE001 — 批异常兜底：不炸线程池/不挂死单飞
            self._log("error", f"批 worker 异常（第 {batch_no} 批）: {e}")
            self._finish("failed", reason=f"batch_worker_error: {e}")
        finally:
            self._in_flight = False
        # 自驱动链（D4）：仅成功批推进下一批；失败批终止链（条目保持 open，
        # 由下一轮 full scan 兜底重试）——失败即再投递会在同步模式下无限递归、
        # 在 executor 模式下无限空转（worktree_create_failed 每轮必复现）。
        if ok:
            self._resubmit()

    def _run_batch_inner(self, ctx: dict) -> bool:
        """执行一批；返回 True 表示批成功（可推进下一批），False 表示链终止。"""
        root = self.project_root
        runner = self._agent_runner
        batch_no = ctx["batch_no"]
        items = ctx["items"]
        item_ids = ctx["item_ids"]
        total = ctx["total"]
        done = ctx["done"]
        reg_spec = ctx["regression_spec"]

        # 建树（5.4）：create() 返回 None 即收尾——不派 run、不合回、条目保持
        # open、复位单飞，进度 failed（下一轮 full scan 重试）。
        wm = getattr(runner, "worktree_manager", None)
        if wm is None:
            self._finish("failed", reason="worktree_manager_missing")
            return False
        wt = wm.create(spec_name="code-review-fix", agent_type="code-fix")
        if wt is None:
            self._log("warning", "code-fix: worktree 创建失败（锁占用或 git 失败）")
            self._finish("failed", reason="worktree_create_failed")
            return False
        wt = Path(wt)
        # 批上下文落盘（task 2.1）：phase="fixing" 写点整体后移至建树成功
        # 之后、agent run 启动之前——原写点位于建树前，彼时 worktree/run_id
        # 均不存在。run_id 由编排器预生成（_preset_run_id，code-fix- 前缀 +
        # 同口径去重）并经 run_code_fix 既有 run_id 形参传入（缺省在其内部
        # 生成、run 返回前编排器无从得知），保证 run 在飞期间进度文件已可
        # 解析（读侧定位 out 文件实时合成条级进度）。
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
        try:
            return self._run_batch_created(wm, wt, created_sha, ctx, run_id=run_id)
        except Exception:
            # 未预期异常兜底（ocr 收尾审查）：create() 已登记 code-review-fix:code-fix
            # spec 锁，仅 cleanup() 释放——漏掉则下一批 create() 恒 None（车道死锁）。
            # 枚举失败分支各自已按语义 cleanup 或保留现场，不经此路径。
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            raise

    def _run_batch_created(self, wm, wt: Path, created_sha, ctx: dict, run_id: str) -> bool:
        """执行已建树批次的主体（首次/重试 run、回归、守卫、合回核销清理）。

        返回 True 表示批成功（可推进下一批）。由 _run_batch_inner 在建树成功后
        调用；未预期异常在本层被兜底 cleanup 后原样上抛（_run_batch 收口）。
        ``run_id`` 为编排器预生成的首轮 run 标识（进度文件已携带同值）。
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
            # agent run 失败：不合回不核销；清理 worktree 释放 spec 锁
            #（否则下一批 create() 恒 None，车道死锁），条目保持 open 待下轮重试
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            self._finish(
                "failed",
                reason=f"agent_run_failed: {result.error}"[:500],
                current=f"第 {batch_no} 批 run 失败",
            )
            return False

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
                # 保留集合，改走与首次 run 失败同一条语义——清理 worktree 释放
                # spec 锁（否则 code-review-fix:code-fix 被永久持有，下一批
                # create() 恒返回 None，车道首批后即死），条目保持 open 待下轮
                # full scan 重试。
                _safe_cleanup(wm, wt, success=False, logger=self._logger)
                self._finish(
                    "failed",
                    reason=f"regression_retry_run_failed: {retry_result.error}"[:500],
                    current=f"第 {batch_no} 批重试 run 失败",
                )
                return False
            retry_run_id = retry_result.run_id
            reg = runner.run_regression(
                reg_spec, reason="code-fix", project_root=wt, lock_root=root
            )
            if reg.status != "passed":
                # 两次均失败 → 丢弃该批：不合回、不置 resolved、条目保持
                # open、保留 worktree（MUST NOT cleanup）、写失败告警与保留集合
                self._log(
                    "error",
                    f"code-fix 第 {batch_no} 批两次回归均未通过，丢弃（worktree 保留: {wt}）",
                )
                summary2 = _failure_summary(reg)
                record_failed_batch(root, item_ids, wt)
                write_regression_failed_alert(root, item_ids, wt, summary2)
                self._finish(
                    "failed",
                    reason=f"regression_failed_twice: {reg.status}",
                    current=f"第 {batch_no} 批已丢弃（待人工）",
                )
                return False

        # 5.8 零有效修复守卫（合回之前）：产物行至少一条 fixed 且分支相对
        # 建树点有提交。merge_back 对「分支已是 HEAD 祖先」返回成功——无此
        # 守卫，全 skipped 的批会以「零改动合并成功 + 回归必过」白洗 resolved。
        rows = read_fix_out(wt, result.run_id)
        if retry_run_id:
            # 重试轮产物是独立文件（fix-out-<retry_run_id>.jsonl）：两轮改动都落在
            # 同一 worktree、随同一次合回进主树，故核销按**并集**口径；只读首次
            # run 会漏掉「重试才修复」的条目（已合回却仍留 open，被反复重派）。
            rows.extend(read_fix_out(wt, retry_run_id))
        fixed_ids = [
            r.get("item_id") for r in rows if r.get("status") == "fixed"
        ]
        fixed_ids = list(dict.fromkeys(fixed_ids))
        commits = _worktree_commit_count(wt, created_sha) if created_sha else 0
        if not fixed_ids or commits <= 0:
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批零有效修复（fixed={len(fixed_ids)}, "
                f"commits={commits}），拒合回",
            )
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            self._finish(
                "failed",
                reason="no_effective_fix",
                current=f"第 {batch_no} 批无有效修复，未合回",
            )
            return False

        # 合回（既有 merge-back 闸门不绕过）→ 核销 fixed 条目 → 清理 worktree
        write_progress(
            root,
            phase="merging",
            current=f"第 {batch_no} 批合回中（{len(items)}/{total} 条）",
        )
        merge_info = wm.merge_back(wt)
        if not getattr(merge_info, "success", False):
            self._log("error", f"code-fix 第 {batch_no} 批合回冲突，交人工")
            record_failed_batch(root, item_ids, wt)
            self._finish(
                "failed",
                reason="merge_back_conflict",
                current=f"第 {batch_no} 批合回冲突（待人工）",
            )
            return False
        hit = mark_resolved(root, fixed_ids)
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
            f"code-fix 第 {batch_no} 批合回成功：resolved {hit}/{len(items)} 条",
        )
        return True


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
