"""run_task_track.py — tasks.md 数字任务解析与 run 产物任务跟踪（中性模块）。

fix-impl-tasks-completion-gate D2/D3：把「tasks.md 数字任务勾选状态解析」
与「run 产物 TaskCreate/TaskUpdate 记录解析」（原 core/dashboard/data.py 的
parse_run_task_done）下沉到本中性模块，供三处共用：
- core/pm_engine/engine.py::_task_completion_blocker（verified→done 门禁）；
- core/agent_runner/runner.py 产物硬门（implementer/fast-track 完成度判据）；
- core/dashboard/data.py（dashboard 读侧，原处保留再导出，既有调用点零改动）。

口径（D2）：逐行匹配 ``^- \[(x| )\] (\d+\.\d+[a-z]?)``，x 记已勾选，
空格记未勾选；tasks.md 缺失或不含数字任务 → 视为「无缺口概念」，判据通过。
禁止在本文件之外再造第二套正则——两套正则一旦漂移，会产出「硬门放行、
门禁拦截」或反之的矛盾结论。

任务 id 语法为 ``<组号>.<任务号>[可选小写字母后缀]``（如 ``1.1``、``1.2b``、
``4.6b``）。字母后缀用于在既有编号后原地插入补充任务而不重排后续编号——
planner 实质会产出该形态（本仓 5 个在飞 spec 中 4 个含字母后缀 id），
只认 ``x.y`` 会把合法任务判为「非数字 id」，使实现者如实上报被硬门拒绝
（2026-09-15 事故：一轮完整成功的重构交付被误拦 + 误标 provider-transient）。
"""

import json
import re
from pathlib import Path

# tasks.md 数字任务勾选行的单一正则（D2）。engine._task_completion_blocker
# 既内联逻辑与本模块共用此映射，禁止两套实现。
# 字母后缀（[a-z]?）为任务 id 合法形态，见模块 docstring。
_TASK_CHECKBOX_RE = re.compile(r"^- \[(x| )\] (\d+\.\d+[a-z]?)")

# run 产物中 TaskCreate subject 内嵌 tasks.md id 的提取正则
# （自 core/dashboard/data.py 随 parse_run_task_done 一并下沉；与勾选行正则
# 同步接受字母后缀，参数 id 覆盖率比对依赖两处口径一致）。
_TASK_ID_RE = re.compile(r"Task\s+#?\s*(\d+\.\d+[a-z]?)")

# 任务 id 的**整体**形态（用于「某字符串是不是合法任务 id」的判定点：
# 产物硬门的 completed_tasks/unfinished 合法性、回写行的 id 提取、task-gap
# 文案的缺口 id 反解）。与 _TASK_CHECKBOX_RE / _TASK_ID_RE 同源同语法——
# 三处口径必须一致，否则「解析得出、判定判非法」的互斥结论会再次出现
# （2026-09-15 事故形态：勾选行正则截断出 "1.2"，整体判定又拒绝 "1.2b"）。
_TASK_ID_FULL_RE = re.compile(r"\d+\.\d+[a-z]?")


def is_task_id(value) -> bool:
    """value 是否为合法 tasks.md 任务 id（``x.y`` 或 ``x.y<小写字母>``）。

    非字符串（None/数字等）恒 False。判定口径与 parse_tasks_md 同源。
    """
    return isinstance(value, str) and _TASK_ID_FULL_RE.fullmatch(value) is not None

# parse_run_task_done 的 memo 缓存：run 文件 O_APPEND 只增，mtime/size 不变即命中。
# 上限 64 项，超出整体清空，防止 append-only 文件每次追加换键导致无界增长。
_RUN_TASK_CACHE: dict = {}


def parse_tasks_md(project_root, spec_name) -> "tuple[list, set]":
    """解析 tasks.md 数字任务的勾选状态（D2 单一实现点，中性模块）。

    逐行匹配 ``^- \[(x| )\] (\d+\.\d+[a-z]?)``：``[x]`` 记已勾选，``[ ]`` 记未勾选。

    Returns:
        (all_ids, checked_ids)：
        - all_ids: 按文档顺序的全部数字任务 id（形如 "1.1"、"1.2b"）；
        - checked_ids: 已勾选（``- [x]``）的 id 集合。
    文件缺失/不可读/不含任何数字任务 → ([]， set())——「无缺口概念」，
    调用方判据通过（与既有 _task_completion_blocker 语义一致）。
    """
    tasks_path = Path(project_root) / "spec" / "changes" / spec_name / "tasks.md"
    if not tasks_path.exists():
        return [], set()
    all_ids: list = []
    checked_ids: set = set()
    try:
        for line in tasks_path.read_text(encoding="utf-8").split("\n"):
            m = _TASK_CHECKBOX_RE.match(line)
            if m:
                tid = m.group(2)
                all_ids.append(tid)
                if m.group(1) == "x":
                    checked_ids.add(tid)
    except (OSError, UnicodeDecodeError):
        return [], set()
    return all_ids, checked_ids


def find_impl_run_file(project_root, spec_name) -> Path | None:
    """最新一次 impl-<spec>-*.jsonl 运行产物，或 None。

    运行中 STATE.md 的 implementer_run 字段为空，不能用它定位；
    按 mtime 取最新与 worktree 选择（find_implementer_worktree）一致。
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return None
    candidates = []
    try:
        for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                pass
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def parse_run_task_done(run_file: Path) -> dict:
    """解析 impl run 产物的 harness 任务完成状态（容错：任何损坏都不抛异常）。

    该函数为 dashboard 实时叠加与 pm_engine 写侧回写共用的解析核心，
    避免两套正则漂移。详见 _parse_run_task_done 历史语义说明。

    TaskCreate 的 input.subject 内嵌 tasks.md id（如 "Task 1.1: ..."）；
    TaskUpdate 的 taskId 为 1 基创建序（tool_result 形如 "Task #1 created ..."）。

    Returns:
        {"done_ids": set[str],   # 已完成且已创建的 tasks.md id（如 {"1.1","2.3"}）
         "created_count": int,    # TaskCreate 次数（flat 回退对齐上限）
         "flat_done": set[int],   # 已完成任务的创建序下标（0-based，flat 回退用）
         "in_progress_ids": list[str]}  # 进行中任务 id（run-progress-current）：
                    # 最近一次 TaskUpdate 仍为 in_progress 且未 completed；
                    # subject 无编号时回退 "#创建序"
    """
    try:
        st = run_file.stat()
        key = (str(run_file), st.st_mtime_ns, st.st_size)
    except OSError:
        return {"done_ids": set(), "created_count": 0, "flat_done": set(),
                "in_progress_ids": []}
    cached = _RUN_TASK_CACHE.get(key)
    if cached is not None:
        return cached

    created_ordered: list = []  # 按创建序的 subject 提取 tasks.md id（无 id 记 None）
    completed_idx: set = set()  # TaskUpdate completed 的 taskId - 1
    last_update_status: dict = {}  # taskId-1 → 最近一次 TaskUpdate status
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant":
                    continue
                for c in (entry.get("message") or {}).get("content") or []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    if c.get("name") == "TaskCreate":
                        m = _TASK_ID_RE.search(str((c.get("input") or {}).get("subject") or ""))
                        created_ordered.append(m.group(1) if m else None)
                    elif c.get("name") == "TaskUpdate":
                        inp = c.get("input") or {}
                        try:
                            n = int(str(inp.get("taskId")))  # 兼容 str/int
                        except (TypeError, ValueError):
                            continue
                        status = inp.get("status")
                        if status:
                            last_update_status[n - 1] = str(status)
                        if status == "completed":
                            completed_idx.add(n - 1)
    except OSError:
        return {"done_ids": set(), "created_count": 0, "flat_done": set(),
                "in_progress_ids": []}

    created_count = len(created_ordered)
    done_ids = set()
    for idx in completed_idx:
        if 0 <= idx < created_count and created_ordered[idx]:
            done_ids.add(created_ordered[idx])
    flat_done = {i for i in completed_idx if 0 <= i < created_count}

    # 进行中任务（run-progress-current）：最近一次 TaskUpdate 仍为 in_progress
    # 且未 completed 的创建序下标 → 展示用 id（subject 无编号时回退 "#创建序"）
    in_progress_idx = {
        idx for idx, s in last_update_status.items()
        if s == "in_progress" and 0 <= idx < created_count
    } - completed_idx
    in_progress_ids = [
        created_ordered[idx] if created_ordered[idx] else f"#{idx + 1}"
        for idx in sorted(in_progress_idx)
    ]

    result = {"done_ids": done_ids, "created_count": created_count, "flat_done": flat_done,
              "in_progress_ids": in_progress_ids}
    if len(_RUN_TASK_CACHE) > 64:
        _RUN_TASK_CACHE.clear()
    _RUN_TASK_CACHE[key] = result
    return result


# impl run 文件名中的派发 epoch（同一 dispatch 链的 a1/a2/a3、-rN 重试共享）。
# 例：impl-<spec>-1789476918-a1-r1.jsonl → "1789476918"。
_RUN_EPOCH_RE = re.compile(r"-(\d+)-a\d+(?:-r\d+)?\.jsonl$")


def _run_epoch(run_file: Path) -> str:
    """从 impl run 文件名提取派发 epoch（族键）；无 -aN 形态时以整名兜底。"""
    m = _RUN_EPOCH_RE.search(run_file.name)
    return m.group(1) if m else run_file.name


def _scan_task_create_update(run_file: Path) -> "tuple[list, set]":
    """扫描单 run 产物的 TaskCreate/TaskUpdate 调用（parse_run_task_done 的原料）。

    Returns:
        (created_ordered, completed_idx)：
        - created_ordered: 按出现序的 tasks.md id（subject 无编号记 None）；
        - completed_idx: TaskUpdate ``status=completed`` 的 ``taskId - 1`` 集合。
    """
    created_ordered: list = []
    completed_idx: set = set()
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant":
                    continue
                for c in (entry.get("message") or {}).get("content") or []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    if c.get("name") == "TaskCreate":
                        m = _TASK_ID_RE.search(str((c.get("input") or {}).get("subject") or ""))
                        created_ordered.append(m.group(1) if m else None)
                    elif c.get("name") == "TaskUpdate":
                        inp = c.get("input") or {}
                        try:
                            n = int(str(inp.get("taskId")))  # 兼容 str/int
                        except (TypeError, ValueError):
                            continue
                        if inp.get("status") == "completed":
                            completed_idx.add(n - 1)
    except OSError:
        return [], set()
    return created_ordered, completed_idx


def parse_run_task_done_cumulative(project_root, spec_name) -> dict:
    """跨轮累积 impl run 的 Task 跟踪状态（D4 交叉核对的正确数据源）。

    修复 2026-09-15 事故：原门只读 mtime 最新**单个** run 的 ``done_ids``，在
    「已完工 worktree 复用做修复轮」时必然误拦——修复轮只改文档、不调
    TaskCreate，``done_ids`` 为空，而门要求覆盖**全部**已勾选任务。

    两处修正：

    1. **跨轮累积**：Task 工具的 ``taskId`` 是**会话级全局序**（跨 resume
       连续递增），单 run 内按「本 run 创建序」映射会错位。按「派发 epoch
       家族」分族（同族含 a1/a2/a3 与 -rN 重试）：族内按 mtime 串起全部
       run，维护累积创建序列表，``TaskUpdate`` 的 ``taskId`` 作全局索引；
       跨族取 ``done_ids`` 并集（不同家族各自从 1 起序，不可混在一个序里）。
    2. **tracked_ids**：全部家族中「出现过 TaskCreate」的任务 id 并集——
       供调用方「只对确实声明过的任务要求完成」：planner 中途插入、实现者
       从未单独建 Task 的任务（如 ``1.2b``）不在此列，不应要求其 TaskUpdate。

    Returns:
        {"done_ids": set[str],      # 各家族中「已创建且已 completed」的 id 并集
         "tracked_ids": set[str],   # 各家族中「出现过 TaskCreate」的 id 并集
         "created_count": int}      # 单族最大 TaskCreate 次数（展示用）
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    empty = {"done_ids": set(), "tracked_ids": set(), "created_count": 0}
    if not runs_dir.is_dir():
        return empty
    files: list = []
    try:
        for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
            try:
                files.append((p.stat().st_mtime, p))
            except OSError:
                pass
    except OSError:
        return empty
    files.sort()

    families: dict = {}
    for _mt, p in files:
        families.setdefault(_run_epoch(p), []).append(p)

    all_done: set = set()
    all_tracked: set = set()
    max_created = 0
    for _ep, fam_files in families.items():
        created_ordered: list = []
        for p in fam_files:
            creates, completed_idx = _scan_task_create_update(p)
            created_ordered.extend(creates)  # 该 run 创建并入族内全局序
            for idx in completed_idx:        # taskId 即族内全局序下标
                if 0 <= idx < len(created_ordered) and created_ordered[idx]:
                    all_done.add(created_ordered[idx])
        for cid in created_ordered:
            if cid:
                all_tracked.add(cid)
        max_created = max(max_created, len(created_ordered))
    return {"done_ids": all_done, "tracked_ids": all_tracked,
            "created_count": max_created}


# 向后兼容别名：旧调用点（tests / 历史引用）仍可用下划线前缀名。
_parse_run_task_done = parse_run_task_done
_find_impl_run_file = find_impl_run_file


def read_init_tools(run_file) -> list | None:
    """读 run 产物 init 事件的 tools 数组（fix-impl-tasks-completion-gate D4 能力探测）。

    runner 产物硬门（TaskUpdate 交叉核对的条件化判定）与 prompt_builder（契约段
    条件生成）共用此中性实现——工具可用性由网关/环境决定、跨 run 稳定
    （141/141 runner 派发 run 实测无 TaskCreate），读历史 run 即可判定路由能力。

    Returns:
        tools 列表（可为空）；run 文件缺失 / 不可读 / 无 init 事件 /
        tools 非数组 → None（按「工具不可用」处理，fail-open）。
    """
    if run_file is None:
        return None
    try:
        with Path(run_file).open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (isinstance(entry, dict)
                        and entry.get("type") == "system"
                        and entry.get("subtype") == "init"):
                    tools = entry.get("tools")
                    if isinstance(tools, list):
                        return tools
                    return None
    except OSError:
        return None
    return None