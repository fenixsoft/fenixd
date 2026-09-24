"""core.dashboard.data.log_index — fenixd 日志块偏移索引（log_index 组）。

refactor-dashboard-data-module D3 分组：本模块承载日志索引/事件记录职责域。
dashboard-log-offset-index D5：尾部读取窗口 + 块偏移二分定位。
"""

import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── fenixd 日志块偏移索引（dashboard-log-offset-index D5） ─────

# 每 64KB 一块；查询窗口只读尾部 ≤1MB（16 块），不再全量扫描日志文件。
LOG_INDEX_BLOCK = 64 * 1024
LOG_INDEX_TAIL_WINDOW = 1 * 1024 * 1024
# 进程内重建计数（测试断言用：追加热更新 0 次重建、损坏容错恰好 1 次）。
_LOG_INDEX_REBUILDS = {"count": 0}


def _log_index_path(proot: Path, log_name: str = "fenixd.log") -> Path:
    """日志块偏移索引路径：.fenix/logs/.idx/<log_name>.offsets.json。

    按日志文件名派生（get_recent_events 会命中多个 fenixd*.log），
    避免多文件共用同一份索引导致 size/offsets 互相覆盖串用。
    """
    return proot / ".fenix" / "logs" / ".idx" / f"{log_name}.offsets.json"


def _build_log_block_index(log_path: Path, size: int) -> dict:
    """全量扫描日志一次，构建 {size, offsets}。

    offsets[i] = 第 i 个 64KB 块内首行字节偏移；读取窗口定位到块 i 后从该偏移
    起读即可获得完整行（落在块边界中间的行被包含进下一块起点）。
    """
    offsets = [0]
    try:
        with log_path.open("rb") as f:
            nblocks = size // LOG_INDEX_BLOCK
            for i in range(1, nblocks + 1):
                boundary = i * LOG_INDEX_BLOCK
                if boundary >= size:
                    break
                f.seek(boundary)
                chunk = f.read(LOG_INDEX_BLOCK)
                nl = chunk.find(b"\n")
                if nl == -1:
                    offsets.append(boundary)
                else:
                    offsets.append(boundary + nl + 1)
    except OSError:
        return {"size": size, "offsets": [0]}
    # 末块采样可能落进文件最后一行且换行恰为文件末字节 → offsets[-1] == size（越
    # 界，非行首）。不可钳到 size-1：那指向行尾 \n 本身而非行首，_first_ts 只读到
    # 空行必解析失败，二分探测退化为 _read(0) 全文件读取。改为弹出末条：尾部区域
    # 由前一偏移读至 EOF 自然覆盖（末行起点本就不在末块采样范围内）。
    if len(offsets) > 1 and offsets[-1] >= size:
        offsets.pop()
    return {"size": size, "offsets": offsets}


def _write_log_index(proot: Path, idx: dict, log_name: str = "fenixd.log"):
    """索引落盘（.idx/ + 原子 rename），失败静默（查询不阻断）。"""
    idx_path = _log_index_path(proot, log_name)
    try:
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = idx_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(idx_path))
    except OSError:
        pass


def _update_log_block_index(log_path: Path, size: int, idx: dict) -> dict:
    """追加热更新：仅补扫 size 增长的新块，不重建旧块。返回新索引。

    日志只增（O_APPEND / RotatingFileHandler 追加），旧块偏移保持不变；
    size 缩小（轮转/截断）时整体重建。
    """
    old_size = idx.get("size", 0)
    if size < old_size:
        fresh = _build_log_block_index(log_path, size)
        _LOG_INDEX_REBUILDS["count"] += 1
        return fresh
    if size <= old_size:
        return idx
    offsets = list(idx.get("offsets", [0]))
    old_blocks = old_size // LOG_INDEX_BLOCK
    try:
        with log_path.open("rb") as f:
            nblocks = size // LOG_INDEX_BLOCK
            for i in range(old_blocks, nblocks + 1):
                boundary = i * LOG_INDEX_BLOCK
                if boundary >= size:
                    break
                if boundary < old_size:
                    continue  # 旧块已覆盖
                # 新增首块起点恰为旧 size（JSONL 行边界）：直接指到 boundary，
                # 避免 seek-forward 把新增首行整行跳过。
                if boundary == old_size:
                    offsets.append(boundary)
                    continue
                f.seek(boundary)
                chunk = f.read(LOG_INDEX_BLOCK)
                nl = chunk.find(b"\n")
                if nl == -1:
                    offsets.append(boundary)
                else:
                    offsets.append(boundary + nl + 1)
    except OSError:
        return idx
    # 同 _build_log_block_index：末条采样可能越过 EOF（boundary+nl+1 == size，非
    # 行首），弹出保住「块首行偏移」不变量，否则 _first_ts 探测必失败回退全文件读取。
    if len(offsets) > 1 and offsets[-1] >= size:
        offsets.pop()
    return {"size": size, "offsets": offsets}


def _load_log_index(proot: Path, log_path: Path) -> dict:
    """读取/重建日志块偏移索引，返回 {"size", "offsets"}。

    缺失或日志文件 size 不匹配（轮转/截断）→ 重建一次（≤1 次全量扫描）并继续；
    匹配则热更新（追加场景 0 次重建）。
    """
    try:
        size = log_path.stat().st_size
    except OSError:
        return {"size": 0, "offsets": [0]}
    idx_path = _log_index_path(proot, log_path.name)
    idx = None
    try:
        if idx_path.exists():
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            if (
                isinstance(data, dict)
                and isinstance(data.get("offsets"), list)
                and isinstance(data.get("size"), int)
            ):
                idx = data
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        idx = None
    if idx is None or idx.get("size", 0) > size:
        # 索引缺失 / 损坏 / 日志被截断（size 缩小）→ 重建一次
        _LOG_INDEX_REBUILDS["count"] += 1
        idx = _build_log_block_index(log_path, size)
        _write_log_index(proot, idx, log_path.name)
        return idx
    # size 相等 → 直接返回；size 增长（append-only）→ 热更新补扫，不重建
    fresh = _update_log_block_index(log_path, size, idx)
    if fresh.get("size") != idx.get("size") or fresh is not idx:
        _write_log_index(proot, fresh, log_path.name)
    return fresh


def _read_log_tail_window(proot: Path, log_path: Path, max_bytes=LOG_INDEX_TAIL_WINDOW) -> bytes:
    """读日志尾部窗口（≤ max_bytes，对齐到块边界保证完整行）。"""
    idx = _load_log_index(proot, log_path)
    size = idx.get("size", 0)
    if size == 0:
        return b""
    offsets = idx.get("offsets", [0]) or [0]
    target = max(0, size - max_bytes)
    bi = min(target // LOG_INDEX_BLOCK, len(offsets) - 1)
    start = offsets[bi] if bi >= 0 else 0
    start = max(0, min(start, size))
    try:
        with log_path.open("rb") as f:
            f.seek(start)
            return f.read(size - start)
    except OSError:
        return b""


def _iter_tail_log_entries(proot: Path, lf: Path, cutoff: str = "") -> list:
    """从日志尾部窗口逐行解析 JSON 条目（跳过非 JSON/空行）。"""
    raw = _read_log_tail_window(proot, lf)
    out = []
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if cutoff and entry.get("timestamp", "") < cutoff:
            continue
        out.append(entry)
    return out


def _norm_utc_iso(ts: str) -> str:
    """时间戳归一为 ...Z 形态（+00:00 → Z），供同格式字典序比较。

    日志时间戳统一 UTC 以 "...Z" 落盘（core/logger.py），STATE.md 的 created 是
    "...+00:00" 形态；同构 ISO 字符串字典序即时间序（微秒位数差异的偏差远小于
    块粒度，不影响定位）。
    """
    return ts.replace("+00:00", "Z")


def _read_log_window_from(proot: Path, log_path: Path, start_ts: str) -> bytes:
    """从时间戳 start_ts 对应位置读到文件尾（块偏移索引二分定位起点）。

    spec 时间轴的读取窗口：尾部 1MB 尾窗对跨窗口存活的长周期 spec 会静默截断
    早期事件（fenixd.log 无轮转持续增长后，早于尾窗的派发/报错/重派全部丢失）。
    改为按 spec created 锚定：日志 append-only 且时间戳单调，二分最后一个
    首行时间戳 < start_ts 的块，从该块读至文件尾（锚点前的残留行由调用方
    spec 名过滤兜底，属无害冗余）。start_ts 为空 → 全文件读取（正确性优先，
    仅低频 REST 详情页触达）；块首行探测失败 → 保守回退全文件。
    """
    idx = _load_log_index(proot, log_path)
    size = idx.get("size", 0)
    offsets = idx.get("offsets", [0]) or [0]
    if size == 0:
        return b""

    def _read(start: int) -> bytes:
        try:
            with log_path.open("rb") as f:
                f.seek(start)
                return f.read(size - start)
        except OSError:
            return b""

    if not start_ts:
        return _read(0)
    target = _norm_utc_iso(start_ts)

    def _first_ts(offset: int) -> "str | None":
        try:
            with log_path.open("rb") as f:
                f.seek(offset)
                chunk = f.read(LOG_INDEX_BLOCK)
            line = chunk.split(b"\n", 1)[0].decode("utf-8", errors="replace")
            return _norm_utc_iso(json.loads(line).get("timestamp", "")) or None
        except (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError, AttributeError):
            return None

    ts0 = _first_ts(offsets[0])
    if ts0 is None or ts0 >= target:
        return _read(0)
    lo, hi = 0, len(offsets) - 1
    # 不变量：块 lo 的首行 ts < target；收敛到满足条件的最大块
    while lo < hi:
        mid = (lo + hi + 1) // 2
        ts_mid = _first_ts(offsets[mid])
        if ts_mid is None:
            return _read(0)
        if ts_mid < target:
            lo = mid
        else:
            hi = mid - 1
    return _read(offsets[lo])


def get_recent_events(project_root, minutes=10, limit=30) -> list:
    """读取最近 N 分钟的 fenixd 结构化日志事件。

    dashboard-log-offset-index D5：只读日志尾部 ≤1MB 窗口（块偏移索引定位），
    不再全量扫描日志文件；窗口外（早于尾部 1MB）的事件按截断语义不追溯。
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    if not logs_dir.is_dir():
        return []
    log_files = sorted(logs_dir.glob("fenixd*.log"), reverse=True)
    # cutoff 归一为 ...Z 形态再与日志时间戳（统一 ...Z 落盘）做字典序比较
    cutoff = _norm_utc_iso(
        (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    )
    events = []
    for lf in log_files[:2]:
        try:
            events.extend(_iter_tail_log_entries(proot=Path(project_root), lf=lf, cutoff=cutoff))
        except (OSError, UnicodeDecodeError):
            continue
    return events[-limit:]


def record_project_event(
    project_root, component: str, message: str, level: str = "INFO", context: dict | None = None
) -> None:
    """向项目事件日志追加一条结构化 JSON 事件（dashboard 操作的活动记录）。

    与 daemon 的 Logger（core/logger.py) 同构：JSON 行写入 `.fenix/logs/fenixd.log`，
    供 `get_recent_events`（活动页）读取展示。服务器进程与 daemon 进程分开部署，
    无法共享 Logger 实例，故按同一文件格式直接追加；daemon 与 dashboard 文件句柄
    O_APPEND 追加互不覆盖（RotatingFileHandler 轮转时按文件名匹配新文件）。
    写日志失败（目录不可写等）静默忽略——活动事件属可观测性增强，不阻断业务操作。

    Args:
        project_root: 项目根目录
        component: 事件组件名（如 dashboard / fenixd）
        message: 事件内容（含 from/to 等归档动作描述）
        level: 日志级别（INFO 默认）
        context: 附加结构化上下文（可选，落为 JSON context 字段）
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            # 全库时间戳统一 ``...Z`` 后缀（code-review item 7dc23d5ac2a6）：
            # isoformat() 自带 +00:00，再拼 "Z" 是非法 ISO-8601（+00:00Z），
            # 与 daemon（core/logger.py 的 .replace 同款写法）混排同秒内字典序
            # 错序、前端 Invalid Date。
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": level,
            "component": component,
            "message": message,
        }
        if context:
            entry["context"] = context
        with (logs_dir / "fenixd.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except (OSError, UnicodeDecodeError):
        pass
