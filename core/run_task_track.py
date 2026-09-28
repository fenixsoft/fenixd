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

import fnmatch
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


def parse_unattainable(data: dict) -> "tuple[set, list]":
    """解析结果文件顶层 ``unattainable`` 申报（诚实退出机制，2026-09-16）。

    ``unattainable`` 是结果文件（``.fenix-run-result.json``）顶层可选数组，
    实现者用它申报「已完成全部可做工作、但某任务客观上无法由 agent 完成」
    （如 7.3 人工运维门控：需用户亲手 touch 重启文件，agent 执行会自杀式
    SIGTERM 杀本 run）。语义与 ``findings`` 不同——``findings`` 是「待裁决
    争议」，本字段是**机械可读的豁免清单**，供三处消费（同一口径，禁止第二套
    判定）：

    1. 产物硬门（``result_gate._check_impl_result_artifact``）：从「未勾硬
       缺口」与 TaskUpdate 覆盖义务里扣除；partial 申报一致性判据里计入
       「已申报集合」（否则申报了 unattainable 的任务会被算成未申报缺口）；
    2. **收敛路径**（``dispatch._honest_exit_gap`` / ``engine._partial_attribution``
       / ``engine._task_completion_blocker``，共用 ``gap_from_result``）：partial
       收工且缺口全部 ⊆ 申报 → 不判失败重派，按成功收口（人工无法代做的任务重派
       N 轮只会重复同一终局，2026-09-16 fix-dashboard-read-path-performance
       实测烧穿预算）。缺口口径 MUST 取结果文件（``unfinished`` 或
       ``completed_tasks`` 反推），MUST NOT 读主树 tasks.md 勾选——主树 ``[x]``
       只在成功/merge-back 路径回写，partial 收敛走不到该路径，读它会把已完成
       任务也算成缺口形成读侧自锁（fix-robustness-edge-cases 事故 2026-09-17）；
    3. verified→done 门禁（``engine._task_completion_blocker``）：缺口全部已
       申报 → 放行到 done 并写人工待办告警。

    每项形如 ``{"task": "7.3", "reason": "<为何无法完成>", "evidence": "<依据>"}``。

    Returns:
        (ids, invalid)：``ids`` 为合法任务 id 集合（去重，忽略非法项）；
        ``invalid`` 为非法项（非 dict / task 非合法 id / 缺 reason）——调用方
        MUST 对非空 ``invalid`` 判失败（防伪造豁免绕过缺口判据）。
    """
    raw = (data or {}).get("unattainable")
    if raw is None:
        return set(), []
    if not isinstance(raw, list):
        return set(), [raw]
    ids: set = set()
    invalid: list = []
    for item in raw:
        if not isinstance(item, dict):
            invalid.append(item)
            continue
        tid = item.get("task")
        reason = item.get("reason")
        if not is_task_id(tid) or not (isinstance(reason, str) and reason.strip()):
            invalid.append(item)
            continue
        ids.add(tid)
    return ids, invalid


# parse_run_task_done 的 memo 缓存：run 文件 O_APPEND 只增，mtime/size 不变即命中。
# 上限 64 项，超出整体清空，防止 append-only 文件每次追加换键导致无界增长。
_RUN_TASK_CACHE: dict = {}


def tasks_md_path(project_root, spec_name) -> Path:
    """tasks.md 规格内路径单点：``<root>/spec/changes/<spec>/tasks.md``。

    判据读取（``parse_tasks_md``）与失败文案里的路径显示都从这里取，禁止
    各自手拼同一相对路径——否则路径变更时判据正确跟随、文案仍指向旧位置，
    失败归因失真（code-review item 52e0dac160b4）。
    """
    return Path(project_root) / "spec" / "changes" / spec_name / "tasks.md"


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
    tasks_path = tasks_md_path(project_root, spec_name)
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


def gap_from_result(data, project_root, spec_name) -> "list[str]":
    """partial 收工的**真实缺口 id 清单**（诚实退出三处消费的统一口径）。

    fix-robustness-edge-cases 事故（2026-09-17）：诚实退出的三处消费
    （``dispatch._honest_exit_gap`` / ``engine._partial_attribution`` /
    ``engine._task_completion_blocker``）在缺少 ``unfinished`` 时一律回退
    **主树** ``tasks.md`` 的勾选状态。但主树的 ``[x]`` 由
    ``_sync_task_progress`` 在成功 / merge-back 路径回写，而 partial 收敛恰
    恰走不到那条路径——于是「未收敛 → 主树全未勾 → 缺口含全部已完成任务 →
    永远收敛不了」构成读侧自锁，同一轮如实申报的 unattainable 缺口被算成
    「已完成 14 项也未完成」，spec 每轮重派烧 ~$18 且第一轮成果整支丢弃。

    优先级（与产物硬门口径同源，禁止再读主树勾选）：
    1. ``unfinished`` 非空列表 → 直接采信（实现者显式申报的未完成）；
    2. 否则以 ``completed_tasks`` 反推：``全部数字任务 id − completed_tasks``
       ——``completed_tasks`` 由产物硬门 ``_check_partial_consistency`` 强制与
       **worktree** ``tasks.md`` 勾选逐条一致，故与结果门同源、不受主树回写
       状态影响；
    3. 两者皆缺（非 partial / 畸形结果）→ 空列表（调用方按既有 fail-closed
       语义处置，不在此处臆造缺口）。

    Returns:
        缺口 id 清单（文档顺序）；无缺口或无法判定 → 空列表。
    """
    unfinished = (data or {}).get("unfinished")
    if isinstance(unfinished, list) and unfinished:
        return [str(t) for t in unfinished]
    completed = (data or {}).get("completed_tasks")
    if isinstance(completed, list):
        all_ids, _checked = parse_tasks_md(project_root, spec_name)
        done = {str(t) for t in completed}
        return [t for t in all_ids if t not in done]
    return []


def honest_exit_convergence_gap(data, project_root, spec_name) -> "list[str]":
    """诚实退出收敛判定**单点实现**（fix-redispatch-loop-governance D1/D2b/D4）。

    收敛成立 ⟺ ``impl_status == "partial"``（调用方判定）且
    ``缺口 := gap_from_result(...)`` 非空 且 缺口每一项都 ∈ ``unattainable`` 申报
    且 ``parse_unattainable`` 无非法项（D2b fail-closed——非法申报不得部分采信，
    否则「只卡第一次」降级放行后存在洗白窗口）。

    Returns:
        收敛成立 → 缺口 id 清单（供日志/留痕/人工待办告警）；不收敛 → 空列表。
        调用方 MUST 以「返回非空」为收敛成立判据，与结果文件是否声明 partial
        正交（partial 状态由调用方在调用本函数前判定）。

    fix-robustness-edge-cases 事故（2026-09-17）：缺口口径 MUST 取结果文件
    （``gap_from_result``：``unfinished`` 优先，否则 ``全部任务 − completed_tasks``），
    MUST NOT 回退主树 tasks.md 勾选——主树 ``[x]`` 只在成功/merge-back 路径回写，
    partial 收敛走不到该路径，读它会把已完成任务也算成缺口形成读侧自锁。

    消费点（同一判据，禁止第二套推导）：
    - ``dispatch.rollback._honest_exit_gap``（full/fast-track 两车道共用）；
    - ``engine._task_completion_blocker``（verified→done 门禁诚实退出分支）；
    - ``agent_runner`` 成果继承 keep 判定（partial 且**不**收敛 → 保留 worktree）。
    """
    unattainable_ids, invalid = parse_unattainable(data or {})
    if invalid:
        return []  # D2b：非法申报 fail-closed，不收敛
    if not unattainable_ids:
        return []  # 无申报 → 不收敛（缺口中每一项都须有申报覆盖）
    gap = gap_from_result(data or {}, project_root, spec_name)
    if not gap:
        # 缺口为空而 status=partial 属申报不自洽（产物硬门 _check_partial_consistency
        # 会拦）；此处不重复判定，但 MUST NOT 把「无缺口」当收敛放过。
        return []
    if all(t in unattainable_ids for t in gap):
        return list(gap)
    return []


def find_impl_run_file(project_root, spec_name, files=None) -> Path | None:
    """最新一次 impl-<spec>-*.jsonl 运行产物，或 None。

    运行中 STATE.md 的 implementer_run 字段为空，不能用它定位；
    按 mtime 取最新与 worktree 选择（find_implementer_worktree）一致。
    files: 调用方预扫描文件集（dashboard 侧 _runs_by_spec_sigs 分组结果）；
        提供时按同名 glob 语义（fnmatch ``impl-<spec>-*.jsonl``、仅活跃目录）
        从中过滤，避免每 spec 重新 glob 整个 runs 目录（fix-dashboard-read-path-
        performance D2：摘要读路径目录 glob 次数为常数）。缺省 None 走 glob。
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return None
    candidates = []
    pattern = f"impl-{spec_name}-*.jsonl"
    try:
        if files is None:
            for p in runs_dir.glob(pattern):
                try:
                    candidates.append((p.stat().st_mtime, p))
                except OSError:
                    pass
        else:
            for p in files:
                if p.parent.name == "archive":
                    continue  # 只认活跃目录（与 glob 路径一致）
                if not fnmatch.fnmatch(p.name, pattern):
                    continue
                try:
                    candidates.append((p.stat().st_mtime, p))
                except OSError:
                    pass
    except OSError:
        return None
    # 精确归属守卫（范式见 recovery.py）：spec 名互为前缀（fix-x vs fix-x-y）
    # 时 fnmatch/glob 命中不得直接认定——fix-x 不得取到 fix-x-y 的最新产物。
    # 函数内 import（与 recovery.py 同款）：run_task_track 被 agent_runner
    # 初始化路径（result_gate）反向引用，模块级 import 会造成循环导入。
    from core.agent_runner.run_files import run_spec_part
    candidates = [(m, p) for m, p in candidates if run_spec_part(p.stem) == spec_name]
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
        return {"done_ids": set(), "created_count": 0, "flat_done": set(), "in_progress_ids": []}
    cached = _RUN_TASK_CACHE.get(key)
    if cached is not None:
        return cached

    # Task 事件解析循环收敛到 _scan_task_create_update 单点（含 last_update_status），
    # 禁止在此再造第二套循环。其 OSError 容错返回空三元组 → 空结果继续（与原
    # 「读失败返回空 dict」语义一致，仅多缓存一次空结果；键含 mtime/size，
    # run 文件后续追加自然换键重解析）。
    created_ordered, completed_idx, last_update_status = _scan_task_create_update(run_file)

    created_count = len(created_ordered)
    done_ids = set()
    for idx in completed_idx:
        if 0 <= idx < created_count and created_ordered[idx]:
            done_ids.add(created_ordered[idx])
    flat_done = {i for i in completed_idx if 0 <= i < created_count}

    # 进行中任务（run-progress-current）：最近一次 TaskUpdate 仍为 in_progress
    # 且未 completed 的创建序下标 → 展示用 id（subject 无编号时回退 "#创建序"）
    in_progress_idx = {
        idx
        for idx, s in last_update_status.items()
        if s == "in_progress" and 0 <= idx < created_count
    } - completed_idx
    in_progress_ids = [
        created_ordered[idx] if created_ordered[idx] else f"#{idx + 1}"
        for idx in sorted(in_progress_idx)
    ]

    result = {
        "done_ids": done_ids,
        "created_count": created_count,
        "flat_done": flat_done,
        "in_progress_ids": in_progress_ids,
    }
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


def _scan_run_events(run_file: Path) -> "tuple[list, set, dict, str | None, bool]":
    """单遍扫描 run 产物：Task 记账 + init ``session_id`` + 异常终态标记。

    解析循环单点实现（原 _scan_task_create_update 的循环收口于此并扩展两路
    结论）：一次文件 IO 同时产出 TaskCreate/TaskUpdate 记账、首个 init 事件的
    ``session_id`` 与 ``type=="error"`` 终态行标记，供 parse_run_task_done /
    parse_run_task_done_cumulative 及下方三个扫描器投影消费——
    parse_run_task_done_cumulative 此前对同一文件先后调 _run_session_id /
    _scan_task_create_update / _run_ended_abnormally 三次全量重读（run 产物
    只增，大 spec 家族文件可达数 MB，result_gate 每轮实现收工都要跑一遍）。
    禁止再造第二套循环（理由见 _scan_task_create_update）。

    Returns:
        (created_ordered, completed_idx, last_update_status, session_id,
         ended_abnormally)：
        - created_ordered: 按出现序的 tasks.md id（subject 无编号记 None）；
        - completed_idx: TaskUpdate ``status=completed`` 的 ``taskId - 1`` 集合；
        - last_update_status: ``taskId - 1`` → 最近一次 TaskUpdate status；
        - session_id: 首个 init 事件的 ``session_id``（首个 init 即定格：无值/
          缺失 → None、不再看后续 init；无 init 事件 → None）；
        - ended_abnormally: 任一行 ``type=="error"`` 即 True（先做 ``"error"``
          字面子串快筛再解析——type 值为 "error" 时行内必有该字面，快筛不漏）。
    OSError → (空三元组, None, False)（容错：任何损坏都不抛异常）。
    """
    created_ordered: list = []
    completed_idx: set = set()
    last_update_status: dict = {}  # taskId-1 → 最近一次 TaskUpdate status
    session_id: "str | None" = None
    init_seen = False
    ended_abnormally = False
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                # error 终态快筛（原 _run_ended_abnormally）：先查子串再解析
                may_error = '"error"' in raw
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                etype = entry.get("type")
                if may_error and etype == "error":
                    ended_abnormally = True
                if etype == "system" and entry.get("subtype") == "init" and not init_seen:
                    init_seen = True  # 首个 init 定格（空/缺失 session_id → None）
                    sid = entry.get("session_id")
                    session_id = str(sid) if sid else None
                if etype != "assistant":
                    continue
                msg = entry.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, list):
                    continue
                for c in content:
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
        return [], set(), {}, None, False
    return created_ordered, completed_idx, last_update_status, session_id, ended_abnormally


def _run_session_id(run_file: Path) -> "str | None":
    """读 run 产物 init 事件的 ``session_id``（Task 计数器 taskId 的归属会话）。

    Task 工具的 ``taskId`` 是**会话级**计数（每个新会话从 1 起）。``--resume``
    续做共享同一 ``session_id``、taskId 连续；而 daemon 因超时/瞬断/跨 provider
    **新建会话**重派时 ``session_id`` 变化、taskId 复位。故跨轮累积 Task 记录
    MUST 按 ``session_id`` 分族——按派发 epoch 分族会把不同会话的独立 taskId
    序错误拼成一条全局序，导致映射错位（2026-09-16 refactor-verification-module
    事故：a1-r1 的 2 个 create 把 a1-r2 的 15 个 create 整体后移，使 a1-r2 真实
    完成的 4.7/4.8 被映射到 4.5/4.6）。

    无 init 事件 / 无 session_id → ``None``（调用方回退 epoch 家族）。
    循环实体已收口于 _scan_run_events，本函数为其 session_id 投影。
    """
    return _scan_run_events(run_file)[3]


def _run_ended_abnormally(run_file: Path) -> bool:
    """run 产物是否以异常终态收尾（超时/kill/非 0 退出写入 ``type=="error"``）。

    正常收尾为 ``result`` / ``superseded`` 事件，无 ``error`` 行；``append_run_error``
    只在超时/信号杀/非 0 退出时追加 ``type=="error"`` 终态行。被硬超时或信号
    杀死的 run，其 Task 记账**被截断**——「建了 Task 但没来得及 TaskUpdate」
    不构成实现者漏做的证据，故其 ``TaskCreate`` 不产生完成度义务（2026-09-16
    refactor-verification-module 事故：a1-r2 撞 18600s 上限被杀，4.9/4.10/4.11
    只创建未完成，后续轮次从不使用 Task 工具 → 硬门永久拒绝、原地重试死循环）。

    完成记录（``done_ids``）仍取全部 run——已 ``completed`` 是正向证据，不受
    创建轮死法影响；只对「缺失」这一负向结论要求来源可信。

    循环实体已收口于 _scan_run_events，本函数为其异常终态投影。
    """
    return _scan_run_events(run_file)[4]


def _scan_task_create_update(run_file: Path) -> "tuple[list, set, dict]":
    """扫描单 run 产物的 TaskCreate/TaskUpdate 调用（解析循环单点实现）。

    parse_run_task_done 与 parse_run_task_done_cumulative 均消费本扫描结果，
    禁止再造第二套循环——两套解析一旦漂移（TaskUpdate 输入形态、status 取值
    变化只改一侧），会产出矛盾结论（同模块 docstring 的正则收口理由）。

    Returns:
        (created_ordered, completed_idx, last_update_status)：
        - created_ordered: 按出现序的 tasks.md id（subject 无编号记 None）；
        - completed_idx: TaskUpdate ``status=completed`` 的 ``taskId - 1`` 集合；
        - last_update_status: ``taskId - 1`` → 最近一次 TaskUpdate status。
    OSError → 空三元组（容错：任何损坏都不抛异常）。

    循环实体已收口于 _scan_run_events（含 init session_id / error 终态两路
    扩展结论），本函数返回其 Task 记账投影（签名与语义不变）。
    """
    return _scan_run_events(run_file)[:3]


def parse_run_task_done_cumulative(project_root, spec_name) -> dict:
    """跨轮累积 impl run 的 Task 跟踪状态（D4 交叉核对的正确数据源）。

    修复 2026-09-15 事故：原门只读 mtime 最新**单个** run 的 ``done_ids``，在
    「已完工 worktree 复用做修复轮」时必然误拦——修复轮只改文档、不调
    TaskCreate，``done_ids`` 为空，而门要求覆盖**全部**已勾选任务。

    2026-09-16 事故再修（本函数分族键与义务来源）：

    1. **按 ``session_id`` 分族**（非派发 epoch）：Task 工具的 ``taskId`` 是
       **会话级**计数——``--resume`` 续做共享同一 session、taskId 连续；而
       daemon 因超时/瞬断/跨 provider **新建会话**重派时 session 变化、taskId
       复位。同一 epoch 家族内可有多个 session（实测 a1=fa4d5106 /
       a1-r1=a8e7fbde / a1-r2=327244a4…），若把家族的 create 首尾拼接成一条
       全局序，后一 session 的 ``taskId-1`` 会被前一 session 的 create 顶偏，
       造成映射错位（a1-r1 的 2 个 create 把 a1-r2 的 15 个 create 后移 →
       a1-r2 真实完成的 4.7/4.8 被误映射为 4.5/4.6）。分族内维护累积创建序，
       ``TaskUpdate`` 的 ``taskId`` 作族内索引；跨族取 ``done_ids`` 并集。
       无 ``session_id``（无 init 事件）时回退 epoch 家族键。
    2. **``tracked_ids`` 只收正常收尾 run 的创建**：被超时/信号杀死的 run
       （``type=="error"`` 终态）Task 记账被截断，「建了 Task 未 TaskUpdate」
       不是漏做证据。此类 run 的 ``TaskCreate`` MUST NOT 产生完成度义务，
       否则该任务永久无法满足（agent 无从知道要补 TaskUpdate，重试再多轮也
       被同一门拒回）。完成记录（``done_ids``）仍取全部 run——已 completed 是
       正向证据；只对「缺失」这一负向结论要求来源可信。

    Returns:
        {"done_ids": set[str],      # 各族中「已创建且已 completed」的 id 并集
         "tracked_ids": set[str],   # 正常收尾 run 中「出现过 TaskCreate」的 id 并集
         "created_count": int}      # 单族最大 TaskCreate 次数（展示用）
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    empty = {"done_ids": set(), "tracked_ids": set(), "created_count": 0}
    if not runs_dir.is_dir():
        return empty
    files: list = []
    try:
        # 函数内 import run_spec_part：模块级 import 会与 agent_runner 初始化
        # 路径（result_gate 反向引用本模块）构成循环导入（见 find_impl_run_file）
        from core.agent_runner.run_files import run_spec_part

        for p in runs_dir.glob(f"impl-{spec_name}-*.jsonl"):
            if run_spec_part(p.stem) != spec_name:
                continue  # 精确归属守卫（fix-x vs fix-x-y 前缀误命中全部排除）
            try:
                files.append((p.stat().st_mtime, p))
            except OSError:
                pass
    except OSError:
        return empty
    files.sort()

    # 分族键：session_id 优先（taskId 计数器归属会话），无 init 事件回退 epoch。
    # 每文件单遍 _scan_run_events 同时产出分族键、Task 记账与异常终态标记并
    # 缓存到 scans 供族内消费——此前分族/族内两趟对同一文件先后调
    # _run_session_id / _scan_task_create_update / _run_ended_abnormally
    # 三次全量重读（读放大，见 _scan_run_events docstring）。
    families: dict = {}
    scans: dict = {}
    for _mt, p in files:
        creates, completed_idx, _last_status, sid, ended_abnormally = _scan_run_events(p)
        scans[p] = (creates, completed_idx, ended_abnormally)
        key = sid if sid is not None else f"epoch:{_run_epoch(p)}"
        families.setdefault(key, []).append(p)

    all_done: set = set()
    all_tracked: set = set()
    max_created = 0
    for _key, fam_files in families.items():
        created_ordered: list = []
        for p in fam_files:
            creates, completed_idx, ended_abnormally = scans[p]
            created_ordered.extend(creates)  # 该 run 创建并入族内全局序
            for idx in completed_idx:  # taskId 即族内全局序下标
                if 0 <= idx < len(created_ordered) and created_ordered[idx]:
                    all_done.add(created_ordered[idx])
            # 义务来源：仅正常收尾 run 的创建计入 tracked（异常终止 run 的
            # 记账被截断，不产生完成度义务）。
            if not ended_abnormally:
                for cid in creates:
                    if cid:
                        all_tracked.add(cid)
        max_created = max(max_created, len(created_ordered))
    return {"done_ids": all_done, "tracked_ids": all_tracked, "created_count": max_created}


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
                if (
                    isinstance(entry, dict)
                    and entry.get("type") == "system"
                    and entry.get("subtype") == "init"
                ):
                    tools = entry.get("tools")
                    if isinstance(tools, list):
                        return tools
                    return None
    except OSError:
        return None
    return None
