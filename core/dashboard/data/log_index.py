"""core.dashboard.data.log_index — fenixd 日志块偏移索引（log_index 组）。

refactor-dashboard-data-module D3 分组：本模块承载日志索引/事件记录职责域。
dashboard-log-offset-index D5：尾部读取窗口 + 块偏移二分定位。
"""

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── fenixd 日志块偏移索引（dashboard-log-offset-index D5） ─────

# 每 64KB 一块；查询窗口只读尾部 ≤1MB（16 块），不再全量扫描日志文件。
LOG_INDEX_BLOCK = 64 * 1024
LOG_INDEX_TAIL_WINDOW = 1 * 1024 * 1024
# created 锚定读取窗口上限（与尾窗同量级）：锚点/文件头到文件尾跨度超上限时
# 只读上限处并以 .truncated 标注截断，单请求内存不随日志体积无界增长。
LOG_INDEX_ANCHOR_WINDOW = 1 * 1024 * 1024
# 锚定窗口超长行跳过阈值（字节；improve-spec-topology-pipeline-view 1.5）：
# 窗口读取遇长度超过它的行（实测样本：admin_monitor 信号单行 6.6MB）以 seek
# 越过该行字节区间继续读后续行——超长行内容不读入内存，单请求读取字节数有
# 界（阈值常量 + 窗口上限双重约束）。写侧已加 LOG_EVENT_MAX_BYTES 封顶，
# 存量巨型行只求读侧跳过（设计 D2：扩大窗口上限会让内存无界化，否决）。
LOG_LINE_SKIP_THRESHOLD = 128 * 1024
# 进程内重建计数（测试断言用：追加热更新 0 次重建、损坏容错恰好 1 次）。
_LOG_INDEX_REBUILDS = {"count": 0}


def _log_index_path(proot: Path, log_name: str = "fenixd.log") -> Path:
    """日志块偏移索引路径：.fenix/logs/.idx/<log_name>.offsets.json。

    按日志文件名派生（get_recent_events 会命中多个 fenixd*.log），
    避免多文件共用同一份索引导致 size/offsets 互相覆盖串用。
    """
    return proot / ".fenix" / "logs" / ".idx" / f"{log_name}.offsets.json"


def _next_line_start(f, start: int, size: int) -> int:
    """从 start 起按 64KB 分段向后读，返回首个换行之后的下一行首偏移。

    供块边界采样落进超长行（单行 > 64KB 采样窗）时定位真实行首；
    EOF 仍无换行（超长行直达文件尾）返回 -1。
    """
    pos = start
    while pos < size:
        f.seek(pos)
        chunk = f.read(LOG_INDEX_BLOCK)
        if not chunk:
            break
        nl = chunk.find(b"\n")
        if nl != -1:
            return pos + nl + 1
        pos += LOG_INDEX_BLOCK
    return -1


def _boundary_at_line_start(f, boundary: int) -> bool:
    """判采样边界是否恰为行首（boundary==0，或前一字节为换行）。

    对齐 _update_log_block_index 接缝特判的判法：某行恰好结束于块边界整数倍时
    boundary 即下一行行首，常规采样 chunk 首字节就是该行内容，find 命中的是它
    自己的换行，boundary+nl+1 会指到再下一行——该行本身没进索引（读窗锚定该
    块时丢一条完整行）。供 _build_log_block_index 与 _update_log_block_index
    共用，避免两处判法漂移。
    """
    if boundary == 0:
        return True
    f.seek(boundary - 1)
    return f.read(1) == b"\n"


def _sample_block_boundary(
    f,
    boundary: int,
    size: int,
    offsets: list,
    pending_start: int,
    old_size: "int | None" = None,
) -> int:
    """对单个块边界采样，把应入索引的偏移 append 进 offsets，返回新 pending_start。

    _build_log_block_index 与 _update_log_block_index 共用的采样主循环体（原为
    两份仅靠注释人工同步的拷贝，单侧改动即判法漂移）：pending_start 续读缓存
    命中（boundary 落进已定位的超长行）时直接复用其下一行首且缓存保持不重置；
    采样窗内无换行 → 单行超过 64KB，续读取真实行首，EOF 仍无换行 → 沿用前一
    偏移；boundary 恰为行首时直接以 boundary 入索引，避免把该行整条踢出索引。
    old_size 非 None（_update 热更新路径）时额外特判接缝块 boundary == old_size：
    回扫一字节确认行首后才直接入索引——新增首块起点恰为旧 size（JSONL 行边界）
    时直接指到 boundary，避免 seek-forward 把新增首行整行跳过；上一轮写入若因
    进程中断留下无换行半行，old_size 落在行中而非行首，沿用常规 seek-forward
    路径定位真实行首。
    """
    if pending_start != -1 and boundary < pending_start:
        offsets.append(pending_start)
        return pending_start
    pending_start = -1
    if old_size is not None and boundary == old_size:
        at_line_start = boundary == 0
        if not at_line_start:
            f.seek(boundary - 1)
            at_line_start = f.read(1) == b"\n"
        if at_line_start:
            # old_size==0 的空日志退化索引 offsets=[0] 增长后 boundary=0 命中此处，
            # 该偏移已在首项，重复 append 产生 [0,0] 冗余项（单调校验 a<=b 放行、
            # 读窗 bi=0/1 等值，仅索引膨胀）——与 offsets[-1] 去重后跳过。
            if not offsets or offsets[-1] != boundary:
                offsets.append(boundary)
            return pending_start
    f.seek(boundary)
    chunk = f.read(LOG_INDEX_BLOCK)
    nl = chunk.find(b"\n")
    if nl == -1:
        # 采样窗内无换行 → 单行超过 64KB（如整段错误转储），boundary 落在大行
        # 中间。不可把行中偏移当行首入索引（违背「块内首行偏移」不变量：读窗
        # 首行为残缺 JSON 被静默丢弃、_first_ts 探测失败退化全文件读），续读取
        # 真实行首；EOF 仍无换行（超长行直达文件尾、无后续行首）→ 沿用前一
        # 偏移，读窗自行首覆盖至 EOF。
        next_start = _next_line_start(f, boundary + LOG_INDEX_BLOCK, size)
        if next_start != -1:
            offsets.append(next_start)
            return next_start
        offsets.append(offsets[-1])
        return pending_start
    # boundary 恰为行首（上一行换行是前一字节）时，nl 命中的是这一行自己的
    # 换行，boundary+nl+1 指到再下一行——该行被整条踢出索引，读窗锚定该块
    # 即丢一条完整行；判行首后直接以 boundary 入索引（判法见
    # _boundary_at_line_start）。
    if _boundary_at_line_start(f, boundary):
        offsets.append(boundary)
    else:
        offsets.append(boundary + nl + 1)
    return pending_start


def _build_log_block_index(log_path: Path, size: int) -> "dict | None":
    """全量扫描日志一次，构建 {size, offsets}；构建失败返回 None。

    offsets[i] = 第 i 个 64KB 块内首行字节偏移；读取窗口定位到块 i 后从该偏移
    起读即可获得完整行（落在块边界中间的行被包含进下一块起点）。单行超过
    64KB 采样窗（超长行跨块）时，该行覆盖的各块统一指向行后的下一行首，
    不把行中偏移当行首入索引。
    """
    offsets = [0]
    # 超长行续读缓存：-1 表示当前不在超长行内；采样判法统一走
    # _sample_block_boundary（与 _update_log_block_index 共用同一份主循环体）。
    pending_start = -1
    try:
        with log_path.open("rb") as f:
            nblocks = size // LOG_INDEX_BLOCK
            for i in range(1, nblocks + 1):
                boundary = i * LOG_INDEX_BLOCK
                if boundary >= size:
                    break
                pending_start = _sample_block_boundary(
                    f, boundary, size, offsets, pending_start
                )
    except OSError:
        # 不可返回 {size: size, offsets: [0]} 的不一致索引：一旦被 _load_log_index
        # 落盘复用，size 持平的后续查询在 _read_log_tail_window 被钳位到块 0 退化成
        # 全文件读；文件继续增长时 _update_log_block_index 从 [0] 起追加新块，列表
        # 位置与块号错位，钳位起点跳到靠后块、1MB 尾窗静默缩窄。返回 None 让调用方
        # 本次以退化索引全量读兜底但不落盘，下次调用重新全量重建。
        return None
    # 末块采样可能落进文件最后一行且换行恰为文件末字节 → offsets[-1] == size（越
    # 界，非行首）。不可钳到 size-1：那指向行尾 \n 本身而非行首，_first_ts 只读到
    # 空行必解析失败，二分探测退化为 _read(0) 全文件读取。改为弹出末条：尾部区域
    # 由前一偏移读至 EOF 自然覆盖（末行起点本就不在末块采样范围内）。while 而
    # 非 if：超长行续读复用可在换行为文件末字节时落多条 == size 的尾随项。
    while len(offsets) > 1 and offsets[-1] >= size:
        offsets.pop()
    return {"size": size, "offsets": offsets}


def _write_log_index(proot: Path, idx: dict, log_name: str = "fenixd.log"):
    """索引落盘（.idx/ + 原子 rename），失败静默（查询不阻断）。"""
    idx_path = _log_index_path(proot, log_name)
    try:
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        # 唯一临时名（mkstemp，同 config_admin 原子写回先例）：dashboard 为多线程
        # HTTP 服务，并发查询同一日志会同时落盘索引；固定 .tmp 名下两路写入交错
        # 会把半个 JSON 经 os.replace 换成正式索引，下次读取触发校验失败全量重建，
        # 打破「追加热更新 0 次重建」热路径。
        fd, tmp_name = tempfile.mkstemp(
            dir=str(idx_path.parent), prefix=f".{log_name}.offsets.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(idx, ensure_ascii=False))
                # replace 前 flush+fsync（对齐 config_admin 原子写惯例，
                # code-review item d67bb2df8b7e）：掉电时半截 JSON 不被换入
                # 正式索引。索引属可再生缓存（校验失败走全量重建自愈），
                # fsync 只是每次落盘的廉价元数据开销，仍以不换入半截数据为先。
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, str(idx_path))
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
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
        if fresh is None:
            # 构建失败保留旧索引：size 已大于实际文件，下次调用仍会走整体重建
            return idx
        _LOG_INDEX_REBUILDS["count"] += 1
        return fresh
    if size <= old_size:
        return idx
    offsets = list(idx.get("offsets", [0]))
    old_blocks = old_size // LOG_INDEX_BLOCK
    pending_start = -1  # 超长行续读缓存（同 _build_log_block_index，共用采样体）
    try:
        with log_path.open("rb") as f:
            nblocks = size // LOG_INDEX_BLOCK
            for i in range(old_blocks, nblocks + 1):
                boundary = i * LOG_INDEX_BLOCK
                if boundary >= size:
                    break
                if boundary < old_size:
                    continue  # 旧块已覆盖
                pending_start = _sample_block_boundary(
                    f, boundary, size, offsets, pending_start, old_size
                )
    except OSError:
        return idx
    # 同 _build_log_block_index：末条采样可能越过 EOF（boundary+nl+1 == size，非
    # 行首），弹出保住「块首行偏移」不变量，否则 _first_ts 探测必失败回退全文件读取。
    # while 而非 if：超长行续读复用可在换行为文件末字节时落多条 == size 的尾随项。
    while len(offsets) > 1 and offsets[-1] >= size:
        offsets.pop()
    return {"size": size, "offsets": offsets}


def _is_valid_log_index(data: object) -> bool:
    """校验落盘索引结构：size 为非 bool 的非负 int、offsets 非空、元素为不超过
    size 的非负 int 且单调不减、长度不越过「块数 + 1」上界。

    仅查容器类型会放行「结构合法的损坏索引」（手工改动/部分写入恰逢 size 一致），
    错位偏移使读窗错位、事件静默丢失且不触发重建自愈；不满足按损坏处理，
    由调用方走重建分支（code-review item fc3f9b53c8e4）。

    size 排除 bool（isinstance(True, int) 为真，否则 {"size": true} 可通过校验，
    热更新拿它当 old_size 参与块号算术）；元素补 o <= size 上界（合法索引各项
    均 ≤ size，越界项使 _read_log_tail_window seek 到 EOF 静默读空）。长度只查
    上界 len(offsets) <= size//LOG_INDEX_BLOCK + 1（每个采样边界至多入一条 +
    首偏移 0，_build/_update 两路皆然，超出即列表位置与块号错位的损坏）；
    不查下界：超长行续读偏移 == size 的尾随项会被逐一弹出（两路构建末尾的
    while pop），合法索引可远短于块数（如单行贯穿尾部各块的整段错误转储），
    按「≥ 块数」校验会对合法索引永久误判损坏、每次查询退化全量重建。
    """
    if not isinstance(data, dict):
        return False
    size = data.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return False
    offsets = data.get("offsets")
    if not isinstance(offsets, list) or not offsets:
        return False
    if any(
        not isinstance(o, int) or isinstance(o, bool) or o < 0 or o > size
        for o in offsets
    ):
        return False
    if len(offsets) > size // LOG_INDEX_BLOCK + 1:
        return False
    return all(a <= b for a, b in zip(offsets, offsets[1:]))


def _load_log_index(proot: Path, log_path: Path) -> dict:
    """读取/重建日志块偏移索引，返回 {"size", "offsets"}。

    缺失、结构损坏（offsets 元素/单调性不合法）或日志文件 size 不匹配（轮转/
    截断）→ 重建一次（≤1 次全量扫描）并继续；匹配则热更新（追加场景 0 次重建）。
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
            if _is_valid_log_index(data):
                idx = data
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        idx = None
    if idx is None or idx.get("size", 0) > size:
        # 索引缺失 / 损坏 / 日志被截断（size 缩小）→ 重建一次
        _LOG_INDEX_REBUILDS["count"] += 1
        idx = _build_log_block_index(log_path, size)
        if idx is None:
            # 构建失败：本次以单块退化索引全量读兜底，但不落盘持久化，
            # 让下次调用重新全量重建（避免不一致索引被长期复用）
            return {"size": size, "offsets": [0]}
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
        # timestamp 非字符串（手改日志/异常写入方/损坏行恰为合法 JSON）时与 str
        # 比较会抛 TypeError 穿透 get_recent_events 的异常捕获成端点 500；非 str
        # 按无时间戳处理（同缺失 timestamp 一致被 cutoff 过滤）。
        ts = entry.get("timestamp")
        if cutoff and (not isinstance(ts, str) or ts < cutoff):
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


class _LogWindow(bytes):
    """带截断标注的日志窗口 bytes（_read_log_window_from 返回形态）。

    内容语义与普通 bytes 完全一致（decode/切片/相等比较不受影响，未截断路径
    返回值与无上限时期逐字节相等，既有调用方零改动兼容）；truncated=True
    表示窗口被 LOG_INDEX_ANCHOR_WINDOW 截断，上限外的日志内容不在返回值中。
    """

    truncated: bool

    def __new__(cls, data: bytes, truncated: bool = False) -> "_LogWindow":
        self = super().__new__(cls, data)
        self.truncated = truncated
        return self


def _skip_leading_giant_lines(f, start: int, size: int) -> int:
    """窗口起点落在超长行上时向后跳过连续超长行，返回新窗口起点。

    锚定窗口被超长行整体占据时（实测样本：首行 6.6MB 巨型行，1MB 窗口全部
    落在其内部），跳过该行后窗口才能覆盖其后可解析事件——超长行本身无信息
    价值（写侧已封顶，存量巨型行只求跳过，设计 D2）。起点为常规行（长度
    ≤ LOG_LINE_SKIP_THRESHOLD）时原样返回，常规日志窗口行为不变。
    """
    pos = start
    while pos < size:
        f.seek(pos)
        scanned = 0
        found_nl = False
        while True:
            read_len = min(LOG_INDEX_BLOCK, size - (pos + scanned))
            chunk = f.read(read_len) if read_len > 0 else b""
            if not chunk:
                break  # EOF：行直达文件尾
            nl = chunk.find(b"\n")
            if nl != -1:
                scanned += nl  # scanned = 行长（\n 前字节数）
                found_nl = True
                break
            scanned += len(chunk)
            if scanned >= LOG_LINE_SKIP_THRESHOLD:
                break
        giant = found_nl and scanned > LOG_LINE_SKIP_THRESHOLD
        if not found_nl:
            giant = scanned >= LOG_LINE_SKIP_THRESHOLD
        if not giant:
            return pos
        if found_nl:
            pos = pos + scanned + 1  # 超长行行尾 \n 的下一行首（连续超长行继续跳）
        else:
            # 阈值内无行界且未达 EOF：从已扫位置续读定位超长行尾
            nxt = _next_line_start(f, pos + scanned, size)
            if nxt == -1:
                return size  # 超长行直达 EOF：窗口退化为空
            pos = nxt
    return pos


def _read_lines_bounded(f, start: int, end: int) -> bytes:
    """逐行读取 [start, end)，超长行以 seek 越过（improve-spec-topology-pipeline-view 1.5）。

    行长度 > LOG_LINE_SKIP_THRESHOLD 的行（存量巨型行，如 admin_monitor 单行
    6.6MB）内容不读入内存——仅以 ≤ LOG_INDEX_BLOCK 探测窗扫描行界定位行尾，
    随后 seek 越过整行字节区间继续读后续行；常规行照常读入。单请求读取字节
    数有界（阈值常量 + 窗口上限双重约束），不出现一次性读入超长行全文的内存
    峰值。窗口末端截在行中间的残行语义与整读实现一致（由调用方逐行
    json.loads 失败跳过）。
    """
    parts: list = []
    pos = start
    line_start = start
    while pos < end:
        f.seek(pos)
        chunk = f.read(min(LOG_INDEX_BLOCK, end - pos))
        if not chunk:
            break
        nl = chunk.find(b"\n")
        if nl != -1:
            line_len = pos + nl - line_start
            if line_len <= LOG_LINE_SKIP_THRESHOLD:
                f.seek(line_start)
                parts.append(f.read(line_len + 1))  # 含行尾 \n，保持逐行切分形态
            # 超长行：整行字节区间跳过（不 append），继续下一行
            line_start = pos + nl + 1
            pos = line_start
        else:
            # 本探测窗内无行界：窗口末端残行（≤ 阈值）照读；否则属超长行
            # 中段，seek 越过 [line_start, end) 剩余区间
            if end - line_start <= LOG_LINE_SKIP_THRESHOLD:
                f.seek(line_start)
                parts.append(f.read(end - line_start))
            pos = end
    return b"".join(parts)


def _read_log_window_from(proot: Path, log_path: Path, start_ts: str) -> bytes:
    """从时间戳 start_ts 对应位置读取窗口（块偏移索引二分定位起点）。

    spec 时间轴的读取窗口：尾部 1MB 尾窗对跨窗口存活的长周期 spec 会静默截断
    早期事件（fenixd.log 无轮转持续增长后，早于尾窗的派发/报错/重派全部丢失）。
    改为按 spec created 锚定：日志 append-only 且时间戳单调，二分最后一个
    首行时间戳 < start_ts 的块，从该块读至窗口上限处（锚点前的残留行由调用方
    spec 名过滤兜底，属无害冗余）。start_ts 为空 → 从文件头读取（正确性优先，
    仅低频 REST 详情页触达）；块首行探测失败 → 保守回退从文件头读取。

    窗口上限 LOG_INDEX_ANCHOR_WINDOW（与尾窗同量级）：无上限时单请求内存随
    日志体积无界增长，锚点/文件头到文件尾跨度超上限只读上限处（保留锚点侧
    早期事件），超出部分按截断语义丢弃并以返回值 .truncated 标注（未截断为
    False）；上限外截在行中间的残行由调用方逐行 json.loads 失败跳过，与
    _read_log_tail_window 的尾窗截断同口径。
    """
    idx = _load_log_index(proot, log_path)
    size = idx.get("size", 0)
    offsets = idx.get("offsets", [0]) or [0]
    if size == 0:
        return _LogWindow(b"")

    def _read(start: int) -> "_LogWindow":
        # 窗口上限：起点到文件尾跨度无界时只读上限处，单请求内存不随日志体积
        # 线性放大；是否截断经 .truncated 携带给调用方。行切分经
        # _read_lines_bounded：超长行以 seek 越过（不整读入内存）；起点被超长
        # 行占据时先经 _skip_leading_giant_lines 跳过（否则 1MB 窗口整体落在
        # 巨型行内部，锚点后事件全部丢失）。常规日志两道防御均不触发，起点/
        # 终点/截断标记与整读实现逐字节一致。
        try:
            with log_path.open("rb") as f:
                start = _skip_leading_giant_lines(f, start, size)
                end = min(size, start + LOG_INDEX_ANCHOR_WINDOW)
                return _LogWindow(_read_lines_bounded(f, start, end), truncated=end < size)
        except OSError:
            return _LogWindow(b"")

    if not start_ts:
        return _read(0)
    target = _norm_utc_iso(start_ts)

    def _first_ts(offset: int) -> "str | None":
        try:
            with log_path.open("rb") as f:
                f.seek(offset)
                chunk = f.read(LOG_INDEX_BLOCK)
                if chunk.find(b"\n") == -1:
                    # 块字节内无行界（超长行征兆，实测样本首行 6.6MB）：探测
                    # 窗整体落在巨型行内部，整块解析必失败 → 自块起点向后越过
                    # 超长行、从下一行界（向后扫描到的首个 \n）之后探测（同
                    # _next_line_start 续读法），替代整体放弃回退文件头——
                    # 否则锚点后可解析事件全部丢失（实测 transitions=0 事故）。
                    # 巨型行直达 EOF（无后续行界）→ None，沿用保守回退。
                    next_start = _next_line_start(f, offset + LOG_INDEX_BLOCK, size)
                    if next_start == -1:
                        return None
                    f.seek(next_start)
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


# 公开访问面（code-review item 2546f200e430）：timeline.py 跨组引用改用公开名
# （不跨组消费下划线私有名），与 _read_log_window_from 同一函数对象单源绑定。
read_log_window_from = _read_log_window_from


def get_recent_events(project_root, minutes=10, limit=30) -> list:
    """读取最近 N 分钟的 fenixd 结构化日志事件。

    dashboard-log-offset-index D5：只读日志尾部 ≤1MB 窗口（块偏移索引定位），
    不再全量扫描日志文件；窗口外（早于尾部 1MB）的事件按截断语义不追溯。
    """
    logs_dir = Path(project_root) / ".fenix" / "logs"
    if not logs_dir.is_dir():
        return []
    # 轮转备份名是 fenixd.log.1/.2（FlockRotatingFileHandler 标准命名，不以
    # .log 结尾），fenixd*.log 匹配不到，轮转后近期事件会静默丢失；改用
    # fenixd.log* 并排除伴随锁文件 fenixd.log.lock（core/logger.py，无日志内容）。
    log_files = sorted(
        (p for p in logs_dir.glob("fenixd.log*") if not p.name.endswith(".lock")),
        reverse=True,
    )
    # cutoff 归一为 ...Z 形态再与日志时间戳（统一 ...Z 落盘）做字典序比较
    cutoff = _norm_utc_iso(
        (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    )
    events = []
    # reverse 字典序下当前文件 fenixd.log 恒排最后（备份名是其前缀延长），
    # 取末 2 个 = 最近一个轮转备份 + 当前文件，且当前文件最后处理，
    # events[-limit:] 优先保留当前文件的新事件。
    for lf in log_files[-2:]:
        try:
            events.extend(_iter_tail_log_entries(proot=Path(project_root), lf=lf, cutoff=cutoff))
        except (OSError, UnicodeDecodeError):
            continue
    if limit <= 0:
        # limit=0 语义为「不返回事件」；events[-0:] 会退化为 events[0:] 返回全量
        return []
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
            # default=str 兜底：context 含 Path/datetime 等不可序列化对象时
            # 序列化为字符串而非抛 TypeError 穿透（写日志失败静默降级的承诺）
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    # ValueError 族覆盖 UnicodeEncodeError：context/message 含 lone surrogate 时
    # ensure_ascii=False 产物在 utf-8 落盘编码阶段抛的是编码错误而非 OSError
    except (OSError, ValueError):
        pass
