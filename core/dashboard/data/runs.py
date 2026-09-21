"""core.dashboard.data.runs — 运行记录（.fenix/runs/）（runs 组）。

refactor-dashboard-data-module D3 分组：本模块承载 run 记录/事件/成本职责域。
"""

import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# run 产物 agent 类型推断（原 data.py 顶层导入，随 runs 组迁移）
from core.agent_runner.run_files import infer_run_agent_type

# ── 结构化 run 指标日志索引（fix-observability-gaps 1.5 消费点）────────────
# run 收尾在 fenixd.log 写一条 metric_type=run_metrics 的结构化指标（runner.py
# _log_run_metrics），含 duration_seconds / cost_usd / terminal / provider。
# 读侧 duration 推算优先消费该指标（替代「由 run 文件 mtime 推算耗时」，
# spec「MUST NOT 仅依赖 mtime」）；无指标（旧日志/未触发）才回退 mtime。
# 索引按 (log_path, size) 键增量维护：日志 append-only，size 增长只补扫新增块；
# size 缩小（轮转）整体重建。进程内缓存，读侧高频重复调用零重扫。
_RUN_METRIC_INDEX: dict = {}
_RUN_METRIC_INDEX_KEY: tuple = None  # (str(log_path), size)


def _strip_run_attempt_suffix(run_id: str) -> str:
    """run 产物 stem → 基础 run_id（剥 -a<n>/ -r<n> attempt/瞬断重试后缀）。

    指标日志的 run_id 记基础 run_id（一次 run = 逻辑整体，含多 attempt），
    产物文件按 attempt 分文件（-a<n>）且瞬断原地重试有 -r<n> 子文件——
    消费侧把产物 stem 归一到基础 id 才能在指标索引中命中。
    """
    if not run_id:
        return run_id
    # 优先剥 -a<n>（attempt 后缀），再剥 -r<n>（原地重试子产物后缀）
    stripped = re.sub(r"-r\d+$", "", run_id)
    stripped = re.sub(r"-a\d+$", "", stripped)
    if stripped != run_id:
        # -r<n> 可能出现在 -a<n> 之后（-a1-r1）：剥完再剥一次 -r
        stripped = re.sub(r"-r\d+$", "", stripped)
    return stripped or run_id


def _load_run_metric_index(project_root: Path) -> dict:
    """增量维护 run 指标索引 {base_run_id: metric_dict}（进程内缓存）。

    metric_dict 取日志行的 context（含 duration_seconds/cost_usd/terminal/
    provider 等），run_id 为 context.run_id（基础 run id）。日志轮转
    （size 缩小）时整体重建，追加（size 增长）只补扫新增部分。
    """
    global _RUN_METRIC_INDEX, _RUN_METRIC_INDEX_KEY
    logs_dir = Path(project_root) / ".fenix" / "logs"
    log_path = logs_dir / "fenixd.log"
    try:
        size = log_path.stat().st_size
    except OSError:
        return {}
    key = (str(log_path), size)
    if key == _RUN_METRIC_INDEX_KEY:
        return _RUN_METRIC_INDEX
    # size 缩小（轮转）或首扫 → 清空重建
    if _RUN_METRIC_INDEX_KEY is None or _RUN_METRIC_INDEX_KEY[0] != str(log_path) \
            or size < _RUN_METRIC_INDEX_KEY[1]:
        _RUN_METRIC_INDEX = {}
        start = 0
    else:
        start = _RUN_METRIC_INDEX_KEY[1]
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            if start:
                f.seek(start)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                ctx = entry.get("context") or {}
                if not isinstance(ctx, dict) or ctx.get("metric_type") != "run_metrics":
                    continue
                rid = ctx.get("run_id")
                if rid:
                    _RUN_METRIC_INDEX[rid] = ctx
    except OSError:
        pass
    _RUN_METRIC_INDEX_KEY = key
    return _RUN_METRIC_INDEX


def _logged_run_duration(project_root: Path, run_file_stem: str,
                         engine: str = "") -> float | None:
    """从结构化指标读 run 耗时（替代 mtime 推算）。

    run_file_stem 为产物文件名（含 -a<n>/ -r<n>），归一化为基础 run_id 后
    在指标索引中查找；命中返回 duration_seconds（float），未命中 None。
    engine 预留字段：后续如需区分「哪个消费点」可传值；当前恒空。
    """
    if not project_root or not run_file_stem:
        return None
    base = _strip_run_attempt_suffix(run_file_stem)
    index = _load_run_metric_index(project_root)
    metric = index.get(base)
    if not metric:
        return None
    d = metric.get("duration_seconds")
    if d is None:
        return None
    try:
        return float(d)
    except (TypeError, ValueError):
        return None

# ── 运行记录（.fenix/runs/） ─────────────────────────────────────

# run 终态事件类型 → classify_run 状态映射。写侧唯一权威是
# core.agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES（result=自然完成,
# error=进程异常终止, interrupted=daemon 停机/启动终态补写, cancelled=人工取消,
# frozen-terminated=spec 冻结终止（add-freeze-stop-inflight-agents D2，
# 行来源：runner.py _run_claude finally 段在 join 后、与 cancelled 行同级
# 追加——读侧缺该映射会把已冻结终止的 run 永远判成 running）），
# 读侧缺类型会把已终结 run 永远判成 running（overview 活跃 Agent 数虚高事故：
# 11 个被杀 run 全部计入活跃，真实活跃仅 1）。测试锁两侧同步。
# fix-retry-orphan-active-runs 追加变体：运行期间原地重试换新 sub_run_id 弃置
# 旧产物文件（写侧补写 superseded 终态），interrupted 补写够不到（daemon 存活
# 期无停机），缺 superseded 映射会把弃置文件永远判成 running——2026-09-10
# 实测 23 活跃仅 2 真实，21 具尸体全数源于该形态。
_RUN_TERMINAL_STATUS_MAP = {
    "result": "done",
    "error": "error",
    "interrupted": "interrupted",
    "cancelled": "cancelled",
    "frozen-terminated": "frozen-terminated",
    "superseded": "superseded",  # fix-retry-orphan-active-runs：原地重试弃置产物终态
    # add-timeline-gate-failure-display D3：门禁因产物硬门失败终止本次 attempt 的
    # 终态（写侧 runner.py _append_gate_blocked，两侧同步义务见 liveness.py
    # RUN_TERMINAL_EVENT_TYPES）。superseded 是同一失败链的**中间弃置件**（紧随其后的
    # gate-blocked 才是收口终态），两者并存但语义不同——MUST NOT 把 superseded 当
    # gate-blocked 的替代，也不必把 superseded 从本映射移除（弃置文件仍需判终态，
    # 否则旧产物永远判 running）。
    "gate-blocked": "gate-blocked",
}

# 读侧 mtime 陈旧兜底阈值（fix-retry-orphan-active-runs D2）：末行非终态
# （running/empty）且产物 mtime 停更超过该秒数 → get_runs 判 stale（弃置/断尾，
# 读侧专属状态枚举，非事件类型，不写入任何产物文件）。退避档上限 120s + agent
# 单 turn（长构建/长测试）余量；live run 每 turn 写事件，30 分钟无写入必非在飞。
# 不做配置项（design D2：避免触发「新增配置必须带 Dashboard 界面」约束）。
_RUN_STALE_SECONDS = 1800


def classify_run(lines: list) -> str:
    """根据产物文件行判定运行终态：done / error / interrupted / cancelled /
    superseded / running / empty。

    runner「终态后置」不变量保证任一终态事件即文件最后一行（result/error 在
    收尾 join 后落盘，interrupted 由 daemon 停机/启动清扫追加，cancelled 由
    取消路径最后落盘，superseded 由原地重试弃置前补写），故只看末行即可判定。
    """
    if not lines:
        return "empty"
    last = lines[-1]
    if not isinstance(last, dict):
        return "running"
    return _RUN_TERMINAL_STATUS_MAP.get(last.get("type"), "running")


def _resolve_run_file(project_root, run_id: str) -> Path:
    """定位 run 产物：优先活跃目录，缺失时回读 archive/（add-run-archive）。"""
    proot = Path(project_root)
    live = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    if live.exists():
        return live
    return proot / ".fenix" / "runs" / "archive" / f"{run_id}.jsonl"


def _first_run_event_ts(path: Path) -> "str | None":
    """run 产物首个带 timestamp 事件的时间（真实启动时刻）。

    run_id 内嵌时间戳是**首次派发**时刻：多 attempt run（-a2+）复用同一
    run_id 基座只加后缀，按 run_id 解析会让所有 attempt 显示同一开始时刻、
    duration 虚增（含前序 attempt 寿命）。真实起点取产物首个带 timestamp 的
    事件：文件头部是无时间戳的 provider_marker/hook/system 事件（实测 10+ 行），
    故扫描前 200 行、命中即停；全部无样本返回 None（调用方回退 run_id 内嵌
    时间戳）。
    """
    try:
        with path.open("rb") as f:
            for _ in range(200):
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = ev.get("timestamp") if isinstance(ev, dict) else None
                # 跨组引用（timeline 组的 _parse_iso_ts）经门面延迟解析（D4）
                import core.dashboard.data as _facade

                if ts and _facade._parse_iso_ts(str(ts)) is not None:
                    return str(ts)
    except OSError:
        return None
    return None


# ── run 元数据 memo（fix-dashboard-read-path-performance D3） ──────────────
# run 元数据（status_raw/started/duration_seconds/file_size）按
# (path, mtime_ns, size) 缓存：append-only 产物未变即零读，跳过 _first_run_event_ts
# （扫描头 200 行 + json.loads）与尾读。读路径把 O(总量) 降为 O(变更量)。
# 与 _RUN_TASK_CACHE/_GLOBAL_BUDGET_CACHE 同模式（GIL 保护下的最优竞态：并发
# 双算无害）。缓存存 status_raw——stale 判定依赖当前时刻，每次按 now 重算。
_RUN_META_CACHE: dict = {}
_RUN_META_CACHE_MAX = 16384


def _run_meta_cached(p: Path, stat, now: float,
                     project_root: Path | None = None) -> dict:
    """计算/复用单条 run 元数据（status/started/duration_seconds/file_size）。

    命中（path, mtime_ns, size 全同）即返回缓存；未命中完整计算并写入缓存。
    耗时/开始时刻/状态推导逻辑与既有 get_runs 逐字等价（见各步注释），
    仅挪入本函数以便整体 memo。

    fix-observability-gaps 1.5（消费点）：project_root 非空时 duration_seconds
    **优先读结构化 run 指标**（runner 收尾写进 fenixd.log 的
    metric_type=run_metrics 行，含真实 duration_seconds），替代「由 run 文件
    mtime 推算耗时」（spec「MUST NOT 仅依赖 mtime」）；指标缺失（旧日志/
    未触发）回退 mtime 推算。project_root 省略（仅取 status 的调用方如
    _is_run_archivable）跳过指标查找，行为与现状一致。
    """
    key = (str(p), stat.st_mtime_ns, stat.st_size)
    cached = _RUN_META_CACHE.get(key)
    if cached is not None:
        status = cached["status_raw"]
        # fix-retry-orphan-active-runs D3：stale 判定按当前时刻每次重算
        if status in ("running", "empty") and (now - stat.st_mtime) > _RUN_STALE_SECONDS:
            status = "stale"
        return {
            "status": status,
            "started": cached["started"],
            "duration_seconds": cached["duration_seconds"],
            "file_size": cached["file_size"],
        }
    run_id = p.stem
    # 耗时：run_id 起始时间戳为 attempt 段前的 10 位 unix 秒（int(time.time())），
    # 文件 mtime 为终止。优先匹配 `-<ts>-a<n>`（含 attempt 后缀的真实格式），
    # 回退 `-<ts>`（旧格式无 attempt 后缀），再无则退化 mtime（现状兜底）。
    tm = re.search(r"-(\d{9,10})-a\d+$", run_id) or re.search(r"-(\d{9,10})$", run_id)
    start_ts = int(tm.group(1)) if tm else stat.st_mtime
    # started 优先取产物首行事件时间戳（真实启动时刻）：run_id 内嵌时间戳
    # 是首次派发时刻，多 attempt run（-a2+）复用同一 run_id 基座只加后缀，
    # 按 run_id 解析会让所有 attempt 显示同一开始时刻、duration 虚增
    # （含前序 attempt 寿命）。真实起点取产物首个带 timestamp 的事件：
    # 文件头部是无时间戳的 provider_marker/hook/system 事件（实测 10+ 行），
    # 故扫描前 200 行、命中即停；全部无样本返回 None（调用方回退 run_id 内嵌
    # 时间戳）。
    real_start = _first_run_event_ts(p)
    # 跨组引用（timeline 组的 _parse_iso_ts）经门面延迟解析（D4）
    import core.dashboard.data as _facade

    real_dt = _facade._parse_iso_ts(real_start) if real_start else None
    if real_dt is not None:
        started = real_dt.astimezone(timezone.utc).isoformat()
        duration_seconds = max(0, int(stat.st_mtime - real_dt.timestamp()))
    else:
        # started 用 run_id 解析出的开始时间戳，而非文件 mtime
        # （mtime 是运行 *结束* 时间）。duration_seconds = mtime - start_ts 已真实计算，
        # 若 started 仍取 mtime，则运行列表/时间轴会把每次运行显示为「在结束时刻才开始」，
        # 与真实耗时自相矛盾（耗时列为真实秒数而开始时间却是结束时刻）。
        started = datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat()
        duration_seconds = max(0, int(stat.st_mtime - start_ts))
    # fix-observability-gaps 1.5（消费点）：结构化指标优先——run 收尾落盘的
    # duration_seconds 为真实耗时（time.time()-start_time），替代 mtime 推算；
    # 命中即用、未命中维持 mtime 兜底（旧日志不丢）。
    if project_root is not None:
        logged = _logged_run_duration(Path(project_root), run_id)
        if logged is not None:
            duration_seconds = int(round(logged))
    status_raw = classify_run(_read_run_lines(p, max_lines=3))
    status = status_raw
    # fix-retry-orphan-active-runs D3：末行非终态且文件 mtime 停更超过
    # _RUN_STALE_SECONDS → 判 stale（原地重试弃置尸体 / 进程被杀无终态断尾），
    # stale 不进 _RUN_TERMINAL_STATUS_MAP（非事件类型）。
    if status in ("running", "empty") and (now - stat.st_mtime) > _RUN_STALE_SECONDS:
        status = "stale"
    meta = {
        "status_raw": status_raw,
        "status": status,
        "started": started,
        "duration_seconds": duration_seconds,
        "file_size": stat.st_size,
    }
    if len(_RUN_META_CACHE) > _RUN_META_CACHE_MAX:
        _RUN_META_CACHE.clear()
    _RUN_META_CACHE[key] = meta
    return meta


def get_runs(project_root, spec_name: str | None = None, include_archive: bool = False, files: list | None = None) -> list:
    """列出项目的运行记录（.fenix/runs/*.jsonl）。

    spec_name 省略时返回全部；否则仅返回 run_id 包含该 spec 的记录。
    include_archive=True 时并入 runs/archive/ 的归档产物（同 run_id 以活跃
    副本优先），供时间轴/运行历史/耗时统计回看已归档的旧 run。
    files: 调用方预扫描的产物路径集（如 SummaryIndex._runs_by_spec_sigs 的
        分组结果）；提供时跳过目录 glob（D2：目录 glob 次数降为常数）。
        与 glob 路径同样按 run_id 前缀过滤、同样以活跃副本优先去重。
    每条: {run_id, agent_type, spec, status, started, file_size, events}
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return []
    out = []
    if files is None:
        try:
            files = list(runs_dir.glob("*.jsonl"))
            if include_archive:
                archive_dir = runs_dir / "archive"
                if archive_dir.is_dir():
                    files.extend(archive_dir.glob("*.jsonl"))
        except OSError:
            return []
    else:
        files = list(files)
        if not include_archive:
            files = [p for p in files if p.parent.name != "archive"]
    # 同 run_id 以活跃副本优先去重（预选集可能同时含 live+archive 同名产物，
    # 与 glob 路径语义一致），再按 mtime 降序（latest_run 取 files[0]）。
    try:
        live, archived = [], []
        for p in files:
            (archived if p.parent.name == "archive" else live).append(p)
        seen = {p.stem for p in live}
        files = live + [p for p in archived if p.stem not in seen]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    now = time.time()
    for p in files:
        run_id = p.stem
        if spec_name and spec_name not in run_id:
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        # 从 run_id 推断 agent 类型与 spec（前缀表 = run_files 唯一真源；
        # 此前是本地漂移副本，漏了 spec-review-/dispute-judge- → 评审 Agent
        # 在时间线上退化为泛型 "agent"，且 spec 残留整个 run_id）。
        agent_type, spec_part = infer_run_agent_type(run_id)
        # 去掉 attempt 段（-a<n>，每个 attempt 追加的后缀），再剥末尾时间戳（-<ts>）。
        # 先剥 -a<n> 再剥时间戳，使 spec_part 不残留时间戳/尝试段。
        spec_part = re.sub(r"-a\d+$", "", spec_part)
        m = re.match(r"^(.*)-\d{9,10}$", spec_part)
        if m:
            spec_part = m.group(1)
        # 元数据（status/started/duration/file_size）按 (path, mtime_ns, size) memo
        # （fix-observability-gaps 1.5：project_root 传入使 duration 优先读结构化指标）
        meta = _run_meta_cached(p, stat, now, project_root=Path(project_root))
        out.append(
            {
                "run_id": run_id,
                "agent_type": agent_type,
                "spec": spec_part,
                "status": meta["status"],
                "duration_seconds": meta["duration_seconds"],
                "started": meta["started"],
                "file_size": meta["file_size"],
            }
        )
    return out


# 尾读字节窗口（fix-dashboard-read-path-performance D3）：取末 N 行先 seek 尾部
# 窗口读；窗口内完整行不足 max_lines（单行超窗 / 前导行残段被丢弃）时回退全量
# 逐行读。64KB 覆盖 result 终结事件行（4KB+）与常规产物尾部；单行超过窗口即回退。
_READ_RUN_TAIL_WINDOW = 64 * 1024


def _parse_tail_lines(lines: list, max_lines: int) -> list:
    """把文本行序列容错解析为事件，保留末 max_lines 条（空行跳过）。"""
    tail = deque(maxlen=max_lines)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            tail.append(json.loads(line))
        except json.JSONDecodeError:
            tail.append({"type": "stderr", "line": line})
    return list(tail)


def _read_run_lines_full(path: Path, max_lines: int) -> list:
    """全量逐行读取产物尾部（尾读回退分支，与旧实现语义一致）。"""
    tail = deque(maxlen=max_lines)
    try:
        with path.open("rb") as f:
            for raw in f:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    tail.append(json.loads(line))
                except json.JSONDecodeError:
                    tail.append({"type": "stderr", "line": line})
    except OSError:
        pass
    return list(tail)


def _read_run_lines(path: Path, max_lines: int = 3) -> list:
    """读取产物文件最后几行 JSON，逐行容错。

    优先从文件尾部按字节窗口 seek 读取（append-only 场景末 N 行远小于窗口，
    避免全量逐行读）；窗口内完整行不足 max_lines（单行超窗 / 前导行残段被
    丢弃）时回退全量逐行读。正确性约束不变：MUST NOT 从行的中间截断导致末行
    被误解析——result/error 终结事件行可能超长（result 携带完整结果数据，
    4KB+），若字节窗口把末行从中间截断、parse 失败后被包装成伪 stderr 事件
    排在真实末尾，classify_run 会把已完成 run 误判为 running（overview 活跃
    Agent 数虚高事故）。窗口首行是上一行的残段，必须丢弃而非解析。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= _READ_RUN_TAIL_WINDOW:
        return _read_run_lines_full(path, max_lines)
    try:
        with path.open("rb") as f:
            f.seek(-_READ_RUN_TAIL_WINDOW, 2)
            raw = f.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    # 首行是从字节窗口切入的残段（从上一行中间开始），丢弃
    parsed = _parse_tail_lines(text.split("\n")[1:], max_lines)
    if len(parsed) >= max_lines:
        return parsed
    # 窗口内完整行不足 max_lines（单行超窗等）→ 回退全量逐行读
    return _read_run_lines_full(path, max_lines)


def _parse_run_lines(lines) -> list:
    """逐行解析 JSONL 行序列为事件（容错：损坏行降级为 stderr 条目）。"""
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            entry = {"type": "stderr", "line": line}
        if not isinstance(entry, dict):
            entry = {"type": "stderr", "line": str(entry)}
        events.append(entry)
    return events


def get_run_events(project_root, run_id: str, tail: int = 300) -> dict:
    """读取单次运行产物流的尾部（前端只展示最近 N 条，全量拉取是浪费）。

    返回: {run_id, exists, status, events, total_events, error}
    events 为最后 tail 条逐行解析结果；status/error 仍由全文件判定
    （终态行 result/error 决定），total_events 为实际总事件数。
    """
    run_file = _resolve_run_file(project_root, run_id)
    if not run_file.exists():
        return {
            "run_id": run_id,
            "exists": False,
            "status": "missing",
            "events": [],
            "total_events": 0,
            "error": None,
        }
    events = []
    error = None
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for entry in _parse_run_lines(f):
                events.append(entry)
                if entry.get("type") == "error":
                    error = entry
    except OSError:
        return {
            "run_id": run_id,
            "exists": True,
            "status": "error",
            "events": [],
            "total_events": 0,
            "error": {"error": "unreadable"},
        }
    return {
        "run_id": run_id,
        "exists": True,
        "status": classify_run(events),
        "events": events[-tail:],
        "total_events": len(events),
        "error": error,
    }


def read_run_events_between(project_root, run_id: str, start_offset: int) -> list:
    """读取运行产物从 start_offset 字节到 EOF 的事件（增量推送用）。

    O_APPEND 只增写：按上次记录的字节偏移读取新增部分，避免整文件重读。
    跨扫描边界被截断的半个 JSON 行会降级为 stderr 条目（_parse_run_lines 容错）。
    """
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    try:
        with run_file.open("rb") as f:
            f.seek(start_offset)
            raw = f.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    return _parse_run_lines(text.splitlines())


# ── 聚合视图（供 Web API / 概览 / 详情） ──────────────────────────


def active_run_count(project_root) -> int:
    """统计处于 running / empty（可能正在增长）状态的运行数。"""
    return sum(1 for r in get_runs(project_root) if r["status"] in ("running", "empty"))


def _run_tail_insights(
    run_file: Path, tail_bytes: int = 65536, marker_scan_cap: int = 4 << 20
) -> dict:
    """读取 run 产物尾部：ClaudeCode 最后一条总结 + 实际驱动的 LLM + usage 四分项 + 终态原因。

    summary 优先取 result 事件的 result 字段（run 最终总结，markdown 文本，
    与 runner.py 提取产物口径一致）；无 result（运行中/中断）时回退最后一条
    assistant 文本。llm 取最后一个 provider_marker 事件（attempt 启动时写入，
    failover 切换产生多个，取最后 = 实际完成 run 的网关）。usage 取 result 事件
    的 usage 字段（add-model-billing-cost-display D2，成本本地计算数据源；
    result 是流终态必在尾窗内，无 result → None）。reason 取终态事件的人类
    可读原因（error 事件的 error 字段 / interrupted、cancelled 事件的 reason
    字段；终态后置不变量保证末行即终态，遍历顺序天然取末行生效），时间轴
    run 节点据此展示失败/中止原因，无终态或成功 run 为空串。只读文件尾部
    tail_bytes 字节避免时间轴加载全量扫描；seek 产生的截断首行直接丢弃。
    marker 可能落在 attempt 大量输出之外（尾窗扫不到），此时按 256KB 块
    向前回扫（上限 marker_scan_cap），仍无则留空。
    """
    try:
        size = run_file.stat().st_size
        with run_file.open("rb") as f:
            if size > tail_bytes:
                f.seek(-tail_bytes, 2)
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {"summary": "", "llm": "", "usage": None, "reason": ""}

    def parse_chunk(raw: str, skip_first: bool) -> tuple:
        lines = raw.split("\n")
        if skip_first:
            lines = lines[1:]
        result_text = last_asst = llm = ""
        usage = None
        reason = ""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            t = e.get("type")
            if t == "provider_marker":
                m, p = e.get("model"), e.get("provider")
                if m and p:
                    llm = f"{m}@{p}"
            elif t == "result":
                rt = e.get("result")
                if isinstance(rt, str) and rt.strip():
                    result_text = rt.strip()
                u = e.get("usage")
                if isinstance(u, dict) and u:
                    usage = u
            elif t == "assistant":
                c = e.get("content")
                if isinstance(c, str) and c.strip():
                    last_asst = c.strip()
                elif isinstance(c, list):
                    texts = [
                        b.get("text", "")
                        for b in c
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    joined = "\n".join(t for t in texts if t.strip())
                    if joined.strip():
                        last_asst = joined.strip()
            elif t in _RUN_TERMINAL_STATUS_MAP and t != "result":
                # 终态原因：error 事件原因在 error 字段，interrupted/cancelled
                # 在 reason 字段；末行终态后处理，天然取末行生效
                reason = str(e.get("error") or e.get("reason") or "").strip()
        return result_text or last_asst, llm, usage, reason

    summary, llm, usage, reason = parse_chunk(data, skip_first=size > tail_bytes)
    if not llm and size > tail_bytes:
        chunk = 262144
        floor = max(0, size - tail_bytes - marker_scan_cap)
        pos = size - tail_bytes
        with run_file.open("rb") as f:
            while pos > floor and not llm:
                start = max(floor, pos - chunk)
                f.seek(start)
                raw = f.read(pos - start).decode("utf-8", errors="replace")
                _, llm, _, _ = parse_chunk(raw, skip_first=start > 0)
                pos = start
    return {"summary": summary, "llm": llm, "usage": usage, "reason": reason}


def compute_run_cost(
    usage: "dict | None", model_used: str, provider_used: str, billing_table: "dict | None"
) -> "float | None":
    """按「provider 卡片开关 + 行 model 匹配」计算单 run 成本（design D2）。

    成本 = input/1M×输入价 + output/1M×输出价 + cache_read/1M×缓存读价
         + cache_creation/1M×缓存写价。
    usage 缺失、provider 卡片计费未开启、该卡片无匹配 model 价格行（或价格行
    字段残缺）→ 返回 None（unpriced，展示「成本不可用」，绝不回退网关回传金额）。
    匹配键以 run 产物 provider_marker 的实际网关与模型为准（failover 切换后
    成本归属仍精确）。

    Args:
        usage: run 产物 result 事件 usage 字段（dict 或 None）
        model_used: 实际驱动模型名（provider_marker 的 model）
        provider_used: 实际驱动网关名（provider_marker 的 provider）
        billing_table: per-provider 计价表 {provider_name: {enabled, prices}}
            （_load_billing_config 产物）或 None
    """
    if not isinstance(usage, dict):
        return None
    if not isinstance(billing_table, dict) or not model_used or not provider_used:
        return None
    card = billing_table.get(provider_used)
    if not isinstance(card, dict) or not card.get("enabled"):
        return None
    price_keys = {
        "input": ("input_tokens", "input_per_million"),
        "output": ("output_tokens", "output_per_million"),
        "cache_read": ("cache_read_input_tokens", "cache_read_per_million"),
        "cache_creation": ("cache_creation_input_tokens", "cache_creation_per_million"),
    }
    for row in card.get("prices") or []:
        if not isinstance(row, dict):
            continue
        if row.get("model") != model_used:
            continue
        try:
            total = 0.0
            for _part, (usage_key, price_key) in price_keys.items():
                price = row.get(price_key)
                if price is None:
                    return None
                tokens = int(usage.get(usage_key) or 0)
                total += tokens / 1_000_000.0 * float(price)
            return total
        except (TypeError, ValueError):
            return None
    return None


def _split_llm_marker(llm: str) -> tuple:
    """把 provider_marker 的 `model@provider` 串拆回 (model, provider)。

    无 @ 的残留串视为只有模型名（provider 置空 → 无法匹配价格，判不可计价）。
    """
    if not llm:
        return "", ""
    if "@" in llm:
        model, provider = llm.rsplit("@", 1)
        return model, provider
    return llm, ""


def run_activity(project_root, spec_name, *, now: float | None = None, files=None) -> dict:
    """最新 impl run 的存活心跳（不依赖 TaskCreate/TaskUpdate 的实时兜底）。

    run_task_progress（fix-implementer-task-progress D3）依赖 run 产物中的
    TaskCreate/TaskUpdate 事件（parse_run_task_done）。该信号虽在 2026-09-15
    经 ``CLAUDE_CODE_ENABLE_TODO_TOOLS=1`` 显式启用后恢复，但实现期间 agent
    未必立刻建 Task、且历史 run 仍可能无事件，信号可能滞后或缺失——任务进度
    列静止在 0/N 时用户无法分辨「卡死」与「正在实现但细粒度进度不可用」。
    本函数改用与任务工具无关的线索：**产物文件是否仍在写**。

    - ``active``：最新 impl run 末行非终态（running/empty）且产物 mtime 未超
      ``_RUN_STALE_SECONDS``（复用 get_runs 的停更判据，两处同一阈值——已死
      断尾/弃置尸体不会外显为活跃）；
    - ``last_event_seconds_ago``：产物 mtime 距现在的秒数（无 run → None）。

    无 run / 解析失败 → ``{"active": False, "last_event_seconds_ago": None}``。
    纯读侧观测，不写入任何状态；``now`` 仅测试注入。
    """
    # D8/D4：find_impl_run_file 已迁至 tasks.py，经门面解析
    import core.dashboard.data as _facade

    run_file = _facade.find_impl_run_file(project_root, spec_name, files=files)
    if run_file is None:
        return {"active": False, "last_event_seconds_ago": None}
    try:
        mtime = run_file.stat().st_mtime
    except OSError:
        return {"active": False, "last_event_seconds_ago": None}
    now = time.time() if now is None else now
    age = max(0, int(now - mtime))
    status = classify_run(_read_run_lines(run_file, max_lines=3))
    active = status in ("running", "empty") and age <= _RUN_STALE_SECONDS
    return {"active": active, "last_event_seconds_ago": age}


# ── runs 保留周期清理（fix-dashboard-read-path-performance D4） ────────────
# daemon 周期任务挂载点（fenixd.py 主循环，300s 节拍对齐 auto_archive_check）：
# 终态 run 移入归档 + 按 runs.keep 上限清理归档。
# 上限语义（5.1a）：runs.keep 约束的是**归档目录条目数**；活跃 runs 目录的
# 有界性由「终态即移出」保证。清理 MUST 记录日志（删除数量 + 文件名可追溯）、
# MUST NOT 静默大批量删除——缺省上限 50、归档实测 343 条目时首次执行会一次
# 删除约 293 个文件，属需可观测的破坏性动作，故每周期删除量设批次上限。
# 被删除的归档 run 会影响 spec_summary 耗时回退 / spec 时间轴 / 运行历史
# （data.py 原 2824/3416/3686、engine.py:621 的 done 时刻耗时快照）；终态 spec
# 有 STATE 固化 total_duration 不受影响，非终态 spec 的历史视图会缩水——
# proposal Non-Goals 只保证响应契约不变、内容会变，此取舍经 5.1b 确认接受。
_RETENTION_MOVE_PER_CYCLE_MAX = 100  # 每周期最多移入归档数（单轮 I/O 尖峰抑制）
_RETENTION_DELETE_PER_CYCLE_MAX = 100  # 每周期最多删除数（5.1a：分批清理）
_RETENTION_KEEP_DEFAULT = 50  # 缺省上限（与 Dashboard 设置页 runs.keep 缺省同源）
# 可归档状态：终态（result/error/interrupted/cancelled/superseded/gate-blocked）
# + stale 断尾尸体（末行非终态且 mtime 停更超 _RUN_STALE_SECONDS——进程被杀
# 无终态补写，不可复活，留活跃目录只会让有界性落空）。
# add-timeline-gate-failure-display D4：集合由 _RUN_TERMINAL_STATUS_MAP.values()
# 派生，新增 gate-blocked 映射后自动纳入，**零改代码**——但 MUST 有用例锁定
# （否则后人把本行改成硬编码清单时会静默漏掉新终态）。
_RETENTION_ARCHIVABLE_STATUSES = frozenset(_RUN_TERMINAL_STATUS_MAP.values()) | {"stale"}


def _resolve_runs_keep(proot: Path, config: dict | None = None) -> int:
    """解析 runs.keep 有效值（缺省 50；缺失/非法回退缺省，与设置页回显同源）。"""
    from core.config import ConfigLoader

    if config is None:
        config = ConfigLoader.resolve_config(proot)
    raw = ConfigLoader.get(config, "runs.keep", _RETENTION_KEEP_DEFAULT)
    try:
        keep = int(raw)
    except (TypeError, ValueError):
        keep = _RETENTION_KEEP_DEFAULT
    if keep < 1:
        keep = _RETENTION_KEEP_DEFAULT
    return keep


def _is_run_archivable(p: Path) -> bool:
    """判定 run 产物是否可归档（终态或 stale 断尾；running/empty 且停更未超时 → False）。

    状态判定复用 get_runs 的 memo（(path, mtime_ns, size)，含 stale 动态判定），
    周期清理不重复读文件。
    """
    try:
        stat = p.stat()
    except OSError:
        return False
    status = _run_meta_cached(p, stat, time.time())["status"]
    return status in _RETENTION_ARCHIVABLE_STATUSES


def _retention_log(logger, level: str, msg: str) -> None:
    """统一清理日志出口：logger 实例优先（fenixd Logger），缺省打印 stderr。"""
    if logger is not None:
        try:
            getattr(logger, level)("fenixd", msg)
        except Exception:
            pass
    else:
        import sys

        print(f"[fenixd] {msg}", file=sys.stderr)


def runs_retention_check(project_root, config: dict | None = None, logger=None) -> dict:
    """daemon 周期 runs 保留清理（fix-dashboard-read-path-performance D4）。

    两步（各自独立失败互不阻断，异常记日志不抛）：
    1. 终态（done/error/interrupted/cancelled/superseded/gate-blocked，及 stale
       断尾）run 从活跃 runs/ 移入 archive/——活跃目录有界性由「终态即移出」保证。
    2. 归档目录按 ``runs.keep`` 上限清理：超过上限时按 mtime 升序（最旧优先）
       删除直至 ≤ 上限；逐条记日志（文件名可追溯）、每周期删除量有批次上限
       （_RETENTION_DELETE_PER_CYCLE_MAX），不静默大批量删除（5.1a）。

    Args:
        project_root: 项目根目录
        config: 有效配置 dict（ConfigLoader.resolve_config 产物）；缺省 None
            时内部解析一次（独立调用/测试友好）。
        logger: Logger 实例（可选；缺省经 logging 模块 stderr 记录）

    Returns:
        {"moved": int, "deleted": int, "keep": int, "archive_total": int,
         "deleted_names": [str, ...], "error": str | None}
    """
    proot = Path(project_root)
    keep = _resolve_runs_keep(proot, config)
    runs_dir = proot / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return {
            "moved": 0,
            "deleted": 0,
            "keep": keep,
            "archive_total": 0,
            "deleted_names": [],
            "error": None,
        }

    # 1. 终态 run 移入归档
    moved = 0
    try:
        for p in runs_dir.glob("*.jsonl"):
            if moved >= _RETENTION_MOVE_PER_CYCLE_MAX:
                break
            if not _is_run_archivable(p):
                continue
            archive_dir = runs_dir / "archive"
            try:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / p.name
                if dest.exists():
                    p.unlink()  # 同 run_id 归档副本已存在：删顶层副本（内容同源）
                else:
                    p.replace(dest)
                moved += 1
                _retention_log(logger, "info", f"runs 保留: 终态 run 移入归档 {p.name}")
            except OSError as e:
                _retention_log(logger, "warning", f"runs 保留: 移入归档失败 {p.name}: {e}")
    except OSError as e:
        _retention_log(logger, "warning", f"runs 保留: 活跃目录扫描失败: {e}")

    # 2. 归档目录按 runs.keep 上限清理
    deleted = 0
    deleted_names: list = []
    archive_total = 0
    archive_dir = runs_dir / "archive"
    try:
        if archive_dir.is_dir():
            archive_files = sorted(
                (p for p in archive_dir.glob("*.jsonl")),
                key=lambda p: p.stat().st_mtime,
            )
            archive_total = len(archive_files)
            excess = archive_total - keep
            if excess > 0:
                victims = archive_files[: min(excess, _RETENTION_DELETE_PER_CYCLE_MAX)]
                for victim in victims:
                    try:
                        victim.unlink()
                        deleted += 1
                        deleted_names.append(victim.name)
                        _retention_log(
                            logger,
                            "warning",
                            f"runs 保留: 删除归档产物 {victim.name}（runs.keep={keep}）",
                        )
                    except OSError as e:
                        _retention_log(
                            logger, "warning", f"runs 保留: 删除失败 {victim.name}: {e}"
                        )
    except OSError as e:
        _retention_log(logger, "warning", f"runs 保留: 归档目录扫描失败: {e}")

    return {
        "moved": moved,
        "deleted": deleted,
        "keep": keep,
        "archive_total": archive_total,
        "deleted_names": deleted_names,
        "error": None,
    }
