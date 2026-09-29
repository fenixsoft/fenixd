"""core.dashboard.data.tasks — 任务解析与进度叠加（tasks 组）。

refactor-dashboard-data-module D3 分组：本模块承载 tasks 职责域。
tasks.md 解析、run 记录实时叠加、implementer worktree 查找。
兼容别名块 _parse_run_task_done/_find_impl_run_file 一并迁移。
"""

import re
import time
from pathlib import Path

# 跨层引用（D4：叶子→中层/中枢；run_task_track 为仅依赖标准库的中性底层
# 模块，顶层 import 不成环）
from core.run_task_track import find_impl_run_file, parse_run_task_done
# 该行导入同时即本模块对外的同名再导出，其余位置不重复 import。


def find_implementer_worktree(project_root, spec_name):
    """Find the newest implementer worktree for a SPEC, or None."""
    wt_dir = Path(project_root) / ".claude" / "worktrees"
    if not wt_dir.is_dir():
        return None
    prefix = f"impl-{spec_name}-"
    candidates = []
    try:
        wt_entries = list(wt_dir.iterdir())
    except OSError:
        # 遍历失败（权限不足/目录并发删除等）按无候选处理，不放大为
        # parse_tasks → 摘要组装 → HTTP 链路 500（与 spec_docs.resolve_spec_dir
        # 对 iterdir 的 OSError 兜底同口径）
        wt_entries = []
    for d in wt_entries:
        if d.is_dir() and d.name.startswith(prefix):
            # 归属精确化（与 worktree_manager.queries.find_implementer_worktree
            # 同口径）：前缀后的余段 MUST 为纯数字时间戳（创建端恒为
            # int(time.time())）。spec 名互为前缀（如 login vs login-page）时，
            # 他 spec 的 impl-login-page-<ts> 裸 startswith 会误入选并按 mtime
            # 参与排序，恰好含同名 spec 目录时读错 tasks.md——非纯数字余段
            # 直接排除。
            if not d.name[len(prefix):].isdigit():
                continue
            try:
                candidates.append((d.stat().st_mtime, d))
            except OSError:
                pass
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


# ── 实时任务完成状态叠加（run 记录 → tasks.md） ───────────────────
#
# 背景：implementer Agent 用 Claude 会话内 TaskCreate/TaskUpdate 工具实时汇报
# 任务完成（见 .fenix/runs/impl-<spec>-*.jsonl 的 assistant tool_use），从不编辑
# tasks.md，导致 Dashboard 任务进度永远 0/N。这里从最新 impl run 产物解析实时
# 完成状态，叠加到 tasks.md 快照上（逐任务并集），使 Dashboard 实时反映进度。
#
# fix-impl-tasks-completion-gate D3：parse_run_task_done 与 find_impl_run_file
# 的解析核心已下沉到中性模块 core/run_task_track.py（供 runner 产物硬门与
# engine 门禁共用，避免 dashboard 消费层被 agent_runner 反向 import）；此处
# 保留同名再导出：公开名经顶部 import 直接可用（引擎侧 pm_engine/engine.py
# 的任务回写与缺口比对即消费 core.dashboard.data 门面再导出），下划线别名
# _parse_run_task_done/_find_impl_run_file 供历史调用点（本模块 parse_tasks
# 叠加路径、tests 旧引用）零改动仍可用。

# 向后兼容别名：旧调用点（tests / 历史引用）仍可用下划线前缀名。
_parse_run_task_done = parse_run_task_done
_find_impl_run_file = find_impl_run_file


# 实时叠加生效的生命周期状态（含实现完成后的验证期）。ready/drafted 不叠加，
# 避免重试过渡期旧 run 的完成数误导。
_LIVE_OVERLAY_STATUSES = {"implementing", "implemented", "testing", "bug-found"}


def _should_overlay(spec_status: str, has_uncompleted: bool) -> bool:
    """是否需要用 run 记录实时完成状态叠加 tasks.md 快照。"""
    if spec_status in _LIVE_OVERLAY_STATUSES:
        return True
    # done/pushed：仅当 tasks.md 仍有未勾选任务时叠加（覆盖实现者从不勾 tasks.md 的现状）
    return spec_status in ("done", "pushed") and has_uncompleted


def parse_tasks(project_root, spec_name, spec_status: str = "", *, live: bool = True, files=None) -> list:
    """解析 tasks.md 为分组任务结构：[{title, tasks:[{id,desc,done}], done, total}]。

    For implementing SPECs, reads from the active implementer worktree first.
    live=True 时按 _should_overlay 叠加最新 impl run 的实时完成状态（并集）。
    files: 预扫描 run 文件集（fix-dashboard-read-path-performance D2），透传
        给叠加用 find_impl_run_file，避免每 spec 重新 glob runs 目录。
    """
    # 跨组引用经门面延迟解析（D4：叶子组引用中层 spec_docs 的 resolve_spec_dir）
    import core.dashboard.data as _facade

    # 活跃优先、归档回退（fix-archived-spec-doc-readback D3）；归档 SPEC 的
    # tasks.md 从归档目录读取，详情页任务卡片不再空白
    spec_dir = _facade.resolve_spec_dir(project_root, spec_name)
    tasks_path = (spec_dir or Path(project_root) / "spec" / "changes" / spec_name) / "tasks.md"
    if spec_status == "implementing":
        wt = find_implementer_worktree(project_root, spec_name)
        if wt:
            wt_tasks = wt / "spec" / "changes" / spec_name / "tasks.md"
            if wt_tasks.exists():
                tasks_path = wt_tasks
    if not tasks_path.exists():
        return []
    groups = []
    current_group = None
    try:
        for line in tasks_path.read_text(encoding="utf-8").split("\n"):
            # 分组标题（点号可选双历史格式：`## 1. 标题` / `## 1 标题`）。
            # 与 bin/fenix_process.py:parse_tasks、core/deliverables.py:
            # lint_tasks_parseable 同源正则（task-track D1），三处必须一致。
            m = re.match(r"^##\s+\d+\.?\s+(.+)$", line)
            if m:
                current_group = {"title": m.group(1), "tasks": [], "done": 0, "total": 0}
                groups.append(current_group)
                continue
            m = re.match(r"^- \[(x| )\] (\d+\.\d+) (.+)$", line)
            if m and current_group is not None:
                is_done = m.group(1) == "x"
                current_group["tasks"].append(
                    {
                        "done": is_done,
                        "id": m.group(2),
                        "desc": m.group(3).strip(),
                    }
                )
                if is_done:
                    current_group["done"] += 1
                current_group["total"] += 1
    except (OSError, UnicodeDecodeError):
        pass
    if not groups:
        return groups
    # 实时叠加：最新 impl run 的 TaskUpdate 完成状态与 tasks.md 勾选取并集。
    # 主路径按 tasks.md id 精确对齐；subject 无 id（未来 harness 变体）时回退扁平下标。
    if live and _should_overlay(
        spec_status, any(not t["done"] for g in groups for t in g["tasks"])
    ):
        run_file = _find_impl_run_file(project_root, spec_name, files=files)
        if run_file is not None:
            rd = _parse_run_task_done(run_file)
            overlaid = False
            if rd["done_ids"]:
                by_id = {t["id"]: t for g in groups for t in g["tasks"]}
                for tid in rd["done_ids"]:
                    t = by_id.get(tid)
                    if t is not None:
                        t["done"] = True
                        overlaid = True
            elif rd["flat_done"]:
                flat = [t for g in groups for t in g["tasks"]]
                bound = min(rd["created_count"], len(flat))
                for i in rd["flat_done"]:
                    if 0 <= i < bound:
                        flat[i]["done"] = True
                        overlaid = True
            if overlaid:
                # 重算分组计数（前端分组头依赖 g.done / g.total）
                for g in groups:
                    g["done"] = sum(1 for t in g["tasks"] if t["done"])
                    g["total"] = len(g["tasks"])
    return groups


def task_progress(project_root, spec_name, spec_status: str = "", files=None):
    """返回 (done, total)，无任务时为 (0, 0)。files 透传 parse_tasks（预扫描 run 文件集）。"""
    groups = parse_tasks(project_root, spec_name, spec_status, files=files)
    done = sum(g["done"] for g in groups)
    total = sum(g["total"] for g in groups)
    return done, total


def tasks_note(project_root, spec_name, spec_status: str = ""):
    """tasks.md 空解析显式提示（task-track R3）。

    tasks.md 存在但 ``parse_tasks`` 返回空列表 → 返回提示文本（前端据此在
    任务清单 Card 显示 warning 空态，与「无 tasks.md 文件」的 secondary
    空态可区分）；否则返回 ``None``。与 ``tasks`` 字段共用同一次解析语义
    （implementing 状态同样优先读 worktree 内的 tasks.md）。
    """
    # 跨组引用经门面延迟解析（D4）
    import core.dashboard.data as _facade

    spec_dir = _facade.resolve_spec_dir(project_root, spec_name)
    tasks_path = (spec_dir or Path(project_root) / "spec" / "changes" / spec_name) / "tasks.md"
    if not tasks_path.exists():
        return None
    if parse_tasks(project_root, spec_name, spec_status):
        return None
    return "tasks.md 存在但未解析出任务分组（分组格式不匹配或文件为空）"


def run_task_progress(project_root, spec_name, files=None) -> dict:
    """最新 impl run 的 harness 任务完成度（run-progress-observability D3）。

    从最新 impl run 产物用 parse_run_task_done 解析：done = TaskUpdate completed
    的 taskId 去重数（flat_done），total = created_count，current = 进行中任务
    id 列表（in_progress 且未 completed，run-progress-current；run 已终态时
    恒空——终态 run 没有「进行中」，残留状态不得外显）。**不依赖 TaskCreate
    subject 是否内嵌 tasks.md 编号**——这正是它作为 tasks.md 快照失效时兜底
    展示的资本。无 run / 解析失败为 {"done": 0, "total": 0, "current": []}。
    files: 预扫描 run 文件集（fix-dashboard-read-path-performance D2），透传
        给 find_impl_run_file，避免每 spec 重新 glob runs 目录。
    """
    run_file = find_impl_run_file(project_root, spec_name, files=files)
    if run_file is None:
        return {"done": 0, "total": 0, "current": []}
    rd = parse_run_task_done(run_file)
    # run-progress-current 终态闸门：终态 run（result/interrupted/cancelled/error）
    # 没有「进行中」任务。current 是实时线索，仅对仍在产事件的 run 有意义；
    # 被杀/清扫补写终态的 run 残留 in_progress 状态不得外显（pushed spec 显示
    # 「进行中 1.2」事故：清扫追加终态行抬高 mtime 使 find_impl_run_file 选中
    # 僵尸文件，残留 in_progress 外显到已推送 SPEC）。
    current = list(rd.get("in_progress_ids") or [])
    # 跨组引用（runs 组的 classify_run/read_run_lines）经门面解析（D4）。
    # read_run_lines 是 runs 组公开访问面（runs.py read_run_lines = _read_run_lines
    # 单源绑定），不跨组消费下划线私有名（code-review item 09c363a0b1b9）
    import core.dashboard.data as _facade

    if current and _facade.classify_run(_facade.read_run_lines(run_file, max_lines=3)) not in (
        "running",
        "empty",
    ):
        current = []
    return {
        "done": len(rd.get("flat_done") or set()),
        "total": int(rd.get("created_count") or 0),
        "current": current,
    }
