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

# ── 运行记录（.fenix/runs/） ─────────────────────────────────────

# run 终态事件类型 → classify_run 状态映射。写侧唯一权威是
# core.agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES（result=自然完成,
# error=进程异常终止, interrupted=daemon 停机/启动终态补写, cancelled=人工取消），
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
    "superseded": "superseded",  # fix-retry-orphan-active-runs：原地重试弃置产物终态
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


def get_runs(project_root, spec_name: str | None = None,
             include_archive: bool = False) -> list:
    """列出项目的运行记录（.fenix/runs/*.jsonl）。

    spec_name 省略时返回全部；否则仅返回 run_id 包含该 spec 的记录。
    include_archive=True 时并入 runs/archive/ 的归档产物（同 run_id 以活跃
    副本优先），供时间轴/运行历史/耗时统计回看已归档的旧 run。
    每条: {run_id, agent_type, spec, status, started, file_size, events}
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return []
    out = []
    try:
        files = list(runs_dir.glob("*.jsonl"))
        if include_archive:
            archive_dir = runs_dir / "archive"
            if archive_dir.is_dir():
                seen = {p.stem for p in files}
                for p in archive_dir.glob("*.jsonl"):
                    if p.stem not in seen:
                        files.append(p)
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
        # 耗时：run_id 起始时间戳为 attempt 段前的 10 位 unix 秒（int(time.time())），
        # 文件 mtime 为终止。优先匹配 `-<ts>-a<n>`（含 attempt 后缀的真实格式），
        # 回退 `-<ts>`（旧格式无 attempt 后缀），再无则退化 mtime（现状兜底）。
        tm = re.search(r"-(\d{9,10})-a\d+$", run_id) or re.search(r"-(\d{9,10})$", run_id)
        start_ts = int(tm.group(1)) if tm else stat.st_mtime
        # started 优先取产物首行事件时间戳（真实启动时刻）：run_id 内嵌时间戳
        # 是首次派发时刻，多 attempt run 复用基座会显示同一时刻且 duration 虚增。
        # mtime 仍是结束时间（started 用派发/启动时刻而非结束时刻的语义不变）。
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
        lines = _read_run_lines(p, max_lines=3)
        status = classify_run(lines)
        # fix-retry-orphan-active-runs D3：stale 判定挂在 get_runs 的 status
        # 组装处（classify_run 保持纯函数不注入 mtime）。末行非终态且文件 mtime
        # 停更超过 _RUN_STALE_SECONDS → 判 stale（原地重试弃置尸体 / 进程被杀
        # 无终态断尾），stale 不进 _RUN_TERMINAL_STATUS_MAP（非事件类型）。
        if status in ("running", "empty") and (now - stat.st_mtime) > _RUN_STALE_SECONDS:
            status = "stale"
        out.append({
            "run_id": run_id,
            "agent_type": agent_type,
            "spec": spec_part,
            "status": status,
            "duration_seconds": duration_seconds,
            "started": started,
            "file_size": stat.st_size,
        })
    return out


def _read_run_lines(path: Path, max_lines: int = 3) -> list:
    """读取产物文件最后几行 JSON，逐行容错。

    逐行流式读取（deque 保留尾部），不用末尾字节窗口 seek：result/error
    终结事件行可能超长（result 携带完整结果数据，4KB+），字节窗口会把末行
    从字节中间截断、parse 失败后被包装成伪 stderr 事件排在真实末尾，
    classify_run 因此把已完成 run 误判为 running（overview 活跃 Agent 数
    虚高）。run 产物均为 MB 级以下小文件，全量逐行读开销可忽略。
    """
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
        return {"run_id": run_id, "exists": False, "status": "missing",
                "events": [], "total_events": 0, "error": None}
    events = []
    error = None
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for entry in _parse_run_lines(f):
                events.append(entry)
                if entry.get("type") == "error":
                    error = entry
    except OSError:
        return {"run_id": run_id, "exists": True, "status": "error",
                "events": [], "total_events": 0, "error": {"error": "unreadable"}}
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


def _run_tail_insights(run_file: Path, tail_bytes: int = 65536,
                       marker_scan_cap: int = 4 << 20) -> dict:
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
                    texts = [b.get("text", "") for b in c
                             if isinstance(b, dict) and b.get("type") == "text"]
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


def compute_run_cost(usage: "dict | None", model_used: str,
                     provider_used: str,
                     billing_table: "dict | None") -> "float | None":
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


def run_activity(project_root, spec_name, *, now: float | None = None) -> dict:
    """最新 impl run 的存活心跳（不依赖 TaskCreate/TaskUpdate 的实时兜底）。

    run_task_progress（fix-implementer-task-progress D3）依赖 run 产物中的
    TaskCreate/TaskUpdate 事件（parse_run_task_done）。但派发路由实际不暴露
    任务清单工具（2026-09-15 实测 308/308 impl+run 的 ``init.tools`` 不含
    TaskCreate），该信号在实现期间恒为 0/0/[]——任务进度列静止在 0/N，用户
    无法分辨「卡死」与「正在实现但细粒度进度不可用」。本函数改用与任务工具
    无关的线索：**产物文件是否仍在写**。

    - ``active``：最新 impl run 末行非终态（running/empty）且产物 mtime 未超
      ``_RUN_STALE_SECONDS``（复用 get_runs 的停更判据，两处同一阈值——已死
      断尾/弃置尸体不会外显为活跃）；
    - ``last_event_seconds_ago``：产物 mtime 距现在的秒数（无 run → None）。

    无 run / 解析失败 → ``{"active": False, "last_event_seconds_ago": None}``。
    纯读侧观测，不写入任何状态；``now`` 仅测试注入。
    """
    # D8/D4：find_impl_run_file 已迁至 tasks.py，经门面解析
    import core.dashboard.data as _facade
    run_file = _facade.find_impl_run_file(project_root, spec_name)
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
