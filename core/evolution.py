"""
evolution.py — 框架自进化链路（add-framework-self-evolution spec）。

把 `.fenix/todo.md`（每日自省产物）下游补齐：跨项目扫描就绪 → 分析 run →
逐条独立回源复核 → 草稿生成与同源 lint → 接受（人工/自动）/拒绝。

模块职责边界（design D5）：**agent 只产出内容，落盘/校验/注册一律由本模块
及调用方的确定性代码完成**。本模块提供：

- 条目身份键（2.1）与 ``.fenix/evolution/items.jsonl`` 原子读写（2.2）
- 水位 ``.fenix/evolution/state.json`` 读写（2.3）
- 就绪扫描（2.4）与 todo.md 条目解析 / 增量筛选（2.5 / 2.6）
- 草稿落盘 / 同源 lint / 落地单条（3.1-3.3）、SPEC 名冲突消解（3.4）、
  接受 / 拒绝 / 自动接受（3.5-3.7）、契约产物解析（3.8）

硬约束：本模块 MUST NOT 创建 spec/changes 条目或注册 STATE.md 条目——
接受路径是唯一例外，且必须「先提交后注册」（design D6）。
"""

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_logger = logging.getLogger("fenixd.evolution")

# ── 结构与常量 ──────────────────────────────────────────────────────

# todo.md 小节枚举（与 core/self_review.py 渲染的三小节一一对应）
TODO_SECTIONS = ("浪费", "失误", "可改进")

# todo.md 结构标题正则：## YYYY-MM-DD 日期节 / ### 小节 / - **标题** 条目
_TODO_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
_TODO_SECTION_RE = re.compile(r"^### (.+?)\s*$")
_TODO_ENTRY_RE = re.compile(r"^-\s+\*\*(.+?)\*\*\s*$")

# 空小节占位（core/self_review.py 写入），解析时跳过
_EMPTY_MARKER = "（当日无）"

# 处理标记行（自进化回写）：写在条目标题行正下方的一行人可读记录——
#   - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
# 「— 不需要」的条目只写前三段（无处理/删除段）。带该行的条目视为已处理：
# 解析时整条跳过，且分析 run 拿到的 todo 文本里也不含它们（避免重复处理）。
TODO_MARKER_KEY = "自进化"
_TODO_MARKER_RE = re.compile(r"^ {2,}-\s*" + TODO_MARKER_KEY + "：")
_TODO_MARKER_INDENT = "  - "

# 条目四字段标签（与 core/self_review.py:_render_entry_lines 的渲染标签对齐）
_FIELD_LABELS = (
    ("影响", "impact"),
    ("证据", "evidence"),
    ("调查评估", "analysis"),
    ("建议", "suggestion"),
)
_FIELD_RE = re.compile(r"^ {2,}-\s+([^：]+)：(.*)$")

# SPEC 名 / capability 合法性（fenix-new 同源正则）
_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# .spec.yaml 模板（内容 schema/created/mode 三行）
SPEC_YAML_TEMPLATE = "schema: spec-driven\ncreated: {created}\nmode: full\n"

# 条目保留策略常量（保留最近 N 天 ∪ 最近 M 条，取较多数者）
# 超出并集部分硬删（由 daemon 周期执行）
ITEM_RETENTION_DAYS = 7  # 保留创建时间在最近 7 天内的条目
ITEM_RETENTION_MIN = 100  # 保留按创建时间倒序的前 100 条


# ── 任务 2.1：条目身份键 ─────────────────────────────────────────────


def item_id(project: str, date_section: str, section: str, title: str) -> str:
    """条目身份键：``sha1(project|date_section|section|title)[:12]``。

    纯函数、无 IO、与条目在文件中的顺序与行号无关；跨环境（机器/时区/运行
    序）可复算（design D4 去重权威 = items.jsonl 的 id 集合）。
    """
    digest = hashlib.sha1(
        f"{project}\x1f{date_section}\x1f{section}\x1f{title}".encode("utf-8")
    ).hexdigest()
    return digest[:12]


# ── 原子读写原语（与 StateMachine.write_all 同范式）────────────────


def _atomic_write(path: Path, content: str) -> None:
    """tempfile + fsync + os.replace 原子替换（StateMachine._write_all_locked 同式）。

    目录不存在时自动创建。写坏（中间被替换的文件内容）在系统层面不可能出现：
    rename 前文件不完整，rename 后旧内容消失。
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _with_lock(path: Path, fn):
    """在 path 同目录的 ``.<name>.lock`` 文件上加 flock 互斥后执行 fn。

    调用方（daemon 主线程 / dashboard server 线程）可能同时写同一存储；
    flock 提供跨进程与跨线程互斥（与 StateMachine.write_all 同范式）。
    MUST NOT 在 fn 内再次加同一把锁（同进程二次 flock 自阻塞）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


# ── 任务 2.2：items.jsonl 读写 ──────────────────────────────────────


def evolution_dir(project_root) -> Path:
    """框架侧自进化暂存区根目录（gitignored，非交付物）。"""
    root = Path(project_root)
    return root / ".fenix" / "evolution"


def items_path(project_root) -> Path:
    return evolution_dir(project_root) / "items.jsonl"


def _parse_items_text(text: str) -> Dict[str, dict]:
    """解析 items.jsonl 文本为 ``{id: record}``（read_items / _read_items_unlocked 共用）。

    纯解析、无 IO 无锁（锁语义由各自外层读取函数表达）；单行 JSON 损坏记
    WARNING 后跳过，非 dict / 缺 id 字段的行跳过。锁内/锁外两条读取路径的
    解析口径由此唯一定义，避免两份实现改一漏一。
    """
    out: Dict[str, dict] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            _logger.warning("evolution: items.jsonl 第 %s 行 JSON 损坏已跳过: %s", lineno, e)
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            continue
        out[rec["id"]] = rec
    return out


def read_items(project_root) -> Dict[str, dict]:
    """读取 ``.fenix/evolution/items.jsonl``，按 id 建索引返回 dict。

    文件不存在按空集合处理；单行 JSON 损坏记 WARNING 后跳过（MUST NOT 让
    整个读取失败——dashboard 列表端点依赖此容错）。TODO 2.2。
    """
    path = items_path(project_root)
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning("evolution: 读取 items.jsonl 失败: %s", e)
        return {}
    return _parse_items_text(text)


def write_items(project_root, records: Iterable[dict]) -> None:
    """全量写回 items.jsonl（读-改-写 + flock + 原子替换展开见 upsert_items）。

    每条一行 JSON；records MUST 是可迭代的记录（逐条为含 id 字段的 dict），
    MUST NOT 传 id→记录 dict——实现直接遍历 records，传 dict 会把键字符串
    当记录全部丢弃、全量写回空文件（既有条目全部丢失）。同一 id 只保留
    一条（后写覆盖先写）。
    """
    # code-review item 0f1a54886379：把 docstring 契约变成运行期保证——
    # 误传 id→记录 dict 时快速失败（TypeError），不留「静默清空全量条目、
    # 既有条目全部丢失」的无告警数据丢失通道。
    if isinstance(records, dict):
        raise TypeError(
            "write_items 期望记录的可迭代对象（逐条为含 id 字段的 dict），"
            "不应传 id→记录 dict；如需全量写回请传 records.values()"
        )
    recs: Dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            continue
        recs[rec["id"]] = rec
    content = "".join(json.dumps(recs[k], ensure_ascii=False) + "\n" for k in sorted(recs))

    path = items_path(project_root)

    def _do() -> None:
        _atomic_write(path, content)

    _with_lock(path, _do)


def upsert_item(project_root, record: dict) -> None:
    """写回单条条目记录（读-改-写，锁内原子；同 id 更新而非追加）。

    design「daemon 与 Dashboard 同时写同一存储」缓解：flock + tempfile +
    rename 原子替换，单条更新粒度小、无长事务。MUST NOT 在锁内二次加锁。
    """
    rec = dict(record)
    path = items_path(project_root)

    def _do() -> None:
        current = _read_items_unlocked(path)
        current[rec["id"]] = rec
        content = "".join(
            json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)
        )
        _atomic_write(path, content)

    _with_lock(path, _do)


def known_ids(project_root) -> set:
    """items.jsonl 全量 id 集合（去重权威，design D4）。"""
    return set(read_items(project_root).keys())


def _read_items_unlocked(path: Path) -> Dict[str, dict]:
    """锁内使用的 items.jsonl 读取（等价 read_items 但路径直传、不加锁）。

    行级解析与 read_items 共用 _parse_items_text（锁内/锁外读取口径不分叉），
    锁语义仍由调用方的外层 _with_lock 表达——本函数 MUST NOT 加锁。
    """
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return _parse_items_text(text)


# ── 任务 2.3：水位 state.json 读写 ──────────────────────────────────


def watermarks_path(project_root) -> Path:
    return evolution_dir(project_root) / "state.json"


def read_watermarks(project_root) -> Dict[str, dict]:
    """读取水位 ``state.json``：``{project: {last_analyzed_at, last_run_id}}``。

    读取时字段缺失/非法按「从未分析」处理（返回空 dict / 跳过该键），
    不抛异常。2.3。
    """
    path = watermarks_path(project_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, dict] = {}
    for proj, wm in data.items():
        if not isinstance(wm, dict):
            continue
        last_at = wm.get("last_analyzed_at")
        if not isinstance(last_at, str) or not last_at:
            continue
        out[proj] = {
            "last_analyzed_at": last_at,
            "last_run_id": (
                wm.get("last_run_id") if isinstance(wm.get("last_run_id"), str) else ""
            ),
        }
    return out


def write_watermarks(project_root, data: Dict[str, dict]) -> None:
    """全量写回水位 state.json（flock + 原子替换）。"""
    path = watermarks_path(project_root)
    cleaned: Dict[str, dict] = {}
    for proj, wm in data.items():
        if not isinstance(wm, dict):
            continue
        last_at = wm.get("last_analyzed_at")
        if not isinstance(last_at, str) or not last_at:
            continue
        cleaned[proj] = {
            "last_analyzed_at": last_at,
            "last_run_id": (
                wm.get("last_run_id") if isinstance(wm.get("last_run_id"), str) else ""
            ),
        }
    content = json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n"

    def _do() -> None:
        _atomic_write(path, content)

    _with_lock(path, _do)


def advance_watermark(project_root, project: str, snapshot_at: str, run_id: str) -> None:
    """推进某项目水位（仅分析 run 成功落地后调用；2.3）。

    snapshot_at MUST 由调用方传入本轮 run 启动时捕获的快照时刻
    （MUST NOT 落地时取 now()——避免漏掉 run 执行期间新写入的条目）。
    锁内读-改-写 + 原子替换。
    """
    path = watermarks_path(project_root)

    def _do() -> None:
        current: Dict[str, dict] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                for proj, wm in loaded.items():
                    if isinstance(wm, dict) and isinstance(wm.get("last_analyzed_at"), str):
                        current[proj] = wm
        current[project] = {
            "last_analyzed_at": snapshot_at,
            "last_run_id": run_id,
        }
        content = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(path, content)

    _with_lock(path, _do)


def _parse_iso(value: str) -> Optional[datetime]:
    """ISO8601 时间解析为时区感知 UTC；失败返回 None（按未就绪/从未分析处理）。

    naive（无时区）输入视为本地时间（self_review 写 ``datetime.now().isoformat()``
    即本地 naive），统一 astimezone 到 UTC，保证与水位（UTC aware）可比。
    结尾 ``Z`` 后缀与 code_review._iso_to_local_dt 同口径先归一 ``+00:00``
    （Python 3.10 的 fromisoformat 不认 Z，code-review item 8f824069987d）。
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(timezone.utc)


# ── 任务 2.4：就绪扫描 ──────────────────────────────────────────────


def _path_access_error(p: Path) -> Optional[OSError]:
    """区分「不存在」与「不可访问」的 stat 探测（code-review item 5512a028b1d1）。

    ``Path.is_file()`` 把权限不足等 OSError 一并吞成 False，「确实不存在」
    （正常不就绪）与「不可访问」（需留痕）无法区分。返回：``None`` = 不存在
    （含父级非目录）或可正常 stat（后者由调用方用 ``is_file()`` 终判非常规
    文件）；非 ``None`` = 访问被拒/IO 异常的原始 OSError（调用方留痕）。
    """
    try:
        p.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as e:
        return e
    return None


def scan_ready_projects(registry_projects, project_root) -> List[dict]:
    """按 registry 项目逐判定就绪，返回就绪项目 [{name, path, todo_md}]。

    就绪判定（spec「自进化触发与就绪扫描」）：
    - ``<proj>/.fenix/self_review_state.json`` 缺失 → 不就绪；
    - ``last_run_at`` 不可解析 → 不就绪（记 DEBUG/INFO，MUST NOT 告警）；
    - ``last_run_at`` 不晚于该项目水位 ``last_analyzed_at`` → 不就绪
      （无水位记录视为从未分析：last_run_at 存在即就绪）；
    - ``<proj>/.fenix/todo.md`` 不存在或去空白后为空 → 不就绪；
    - 其余 → 就绪。

    registry 读取失败 MUST 抛给调用方（检查点统一捕获）。项目内文件「确实
    不存在」按不就绪跳过；「不可访问」（权限/IO 等 OSError 且非不存在类）
    MUST 记 WARNING 留痕后按不就绪跳过——不在本函数静默吞掉，也不因单项目
    IO 异常中断整轮扫描（code-review item 5512a028b1d1 将原「不可访问 MUST
    抛出」契约收窄为留痕）。就绪项目 MUST 携带 todo_md 全文（同轮一个 claude
    进程拿到多份 todo.md）。
    """
    watermarks = read_watermarks(project_root)
    ready: List[dict] = []
    for proj in registry_projects or []:
        if not isinstance(proj, dict):
            continue
        path = proj.get("path")
        name = proj.get("name") or (Path(path).name if path else "")
        if not path:
            continue
        proot = Path(path)

        state_file = proot / ".fenix" / "self_review_state.json"
        acc_err = _path_access_error(state_file)
        if acc_err is not None:
            # code-review item 5512a028b1d1：不可访问（权限/IO）MUST 留痕，
            # 不静默吞成「不存在」；按不就绪跳过、不向调用方抛出——单项目
            # IO 异常不中断整轮扫描。
            _logger.warning(
                "evolution: 项目 %s 的 self_review_state.json 不可访问，按不就绪跳过: %s",
                name,
                acc_err,
            )
            continue
        if not state_file.is_file():
            _logger.debug("evolution: 项目 %s 无 self_review_state.json，不就绪", name)
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            _logger.info(
                "evolution: 项目 %s 的 self_review_state.json 不可读（不就绪）: %s", name, e
            )
            continue
        if not isinstance(state, dict):
            continue
        last_run_at = _parse_iso(state.get("last_run_at"))
        if last_run_at is None:
            _logger.debug("evolution: 项目 %s 的 last_run_at 缺失或不可解析，不就绪", name)
            continue

        wm = watermarks.get(name)
        if wm:
            last_analyzed = _parse_iso(wm.get("last_analyzed_at"))
            if last_analyzed is not None and last_run_at <= last_analyzed:
                _logger.debug("evolution: 项目 %s 的 last_run_at 不晚于水位，不就绪", name)
                continue

        todo = proot / ".fenix" / "todo.md"
        acc_err = _path_access_error(todo)
        if acc_err is not None:
            _logger.warning(
                "evolution: 项目 %s 的 todo.md 不可访问，按不就绪跳过: %s", name, acc_err
            )
            continue
        if not todo.is_file():
            _logger.debug("evolution: 项目 %s 无 todo.md，不就绪", name)
            continue
        try:
            todo_text = todo.read_text(encoding="utf-8")
        except OSError as e:
            _logger.info("evolution: 项目 %s 的 todo.md 不可读（不就绪）: %s", name, e)
            continue
        if not todo_text.strip():
            _logger.debug("evolution: 项目 %s 的 todo.md 为空，不就绪", name)
            continue
        # 剥离已处理条目（带处理标记）：分析 run 的输入不含它们，避免重复处理；
        # 剥完一条不剩则本项目不就绪，直接省掉整轮分析
        usable_text = strip_processed_entries(todo_text)
        if not parse_todo_entries(usable_text):
            _logger.debug("evolution: 项目 %s 无未处理的 todo 条目（全部已标记），不就绪", name)
            continue
        ready.append({"name": name, "path": str(proot), "todo_md": usable_text})
    return ready


# ── 任务 2.5：todo.md 条目解析 ──────────────────────────────────────


def parse_todo_entries(text: str) -> List[dict]:
    """解析 todo.md 为条目列表（2.5）。

    结构：``## YYYY-MM-DD`` 切日期节 → ``### 浪费|失误|可改进`` 切小节 →
    ``- **<标题>**`` 起一条并收集其后的 ``  - 影响：…`` 等四字段嵌套行
    （与 core/self_review.py:_render_entry_lines 的渲染格式对齐）。

    - ``- （当日无）`` 占位与无法归类的行 MUST 跳过且不使解析失败；
    - 小节名不在三值枚举内的条目 MUST 跳过并记一次 WARNING（每节一次）。

    Returns: [{date_section, section, title, impact, evidence, analysis,
    suggestion}]（无 project，由调用方注入）。
    """
    entries: List[dict] = []
    date_section = ""
    current_section = ""
    current_entry: Optional[dict] = None
    current_fields: Dict[str, str] = {}
    _section_warned: set = set()

    def _flush_entry() -> None:
        nonlocal current_entry, current_fields
        if current_entry is not None:
            # 小节名不在三值枚举内的条目 MUST 跳过（含未知小节置空的条目）；
            # 带处理标记的条目（已被自进化处理过）同样 MUST 跳过，避免重复处理
            if (
                current_entry.get("section") in TODO_SECTIONS
                and current_entry.get("title")
                and not current_entry.get("_processed")
            ):
                current_entry.update(current_fields)
                entries.append(current_entry)
        current_entry = None
        current_fields = {}

    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue

        m = _TODO_DATE_RE.match(raw_line)
        if m:
            _flush_entry()
            date_section = m.group(1)
            current_section = ""
            continue

        m = _TODO_SECTION_RE.match(raw_line)
        if m:
            _flush_entry()
            section_name = m.group(1).strip()
            if section_name not in TODO_SECTIONS:
                if section_name not in _section_warned:
                    _logger.warning(
                        "evolution: todo.md 小节 %r 不在三值枚举 %s 内，" "其下条目跳过",
                        section_name,
                        list(TODO_SECTIONS),
                    )
                    _section_warned.add(section_name)
                current_section = ""
            else:
                current_section = section_name
            continue

        # 条目标题行：- **<标题>**
        m = _TODO_ENTRY_RE.match(raw_line)
        if m:
            _flush_entry()
            current_entry = {
                "date_section": date_section,
                "section": current_section,
                "title": m.group(1).strip(),
            }
            current_fields = {}
            continue

        # 空小节占位：- （当日无）
        stripped = raw_line.strip()
        if stripped.startswith("-") and _EMPTY_MARKER in stripped:
            continue

        if current_entry is None:
            # 无法归类（可能在条目块外）→ 跳过
            continue

        # 处理标记行：仅在其紧跟条目标题行（该条目尚未收集任何字段）时才
        # 生效——整条标记为已处理（flush 时丢弃）；孤立标记行（其标题行已被
        # 手工删除/改写后残留）只告警并跳过自身，不连坐当前条目
        if _TODO_MARKER_RE.match(raw_line):
            if not current_fields:
                current_entry["_processed"] = True
            else:
                _logger.warning(
                    "evolution: todo.md 孤立处理标记行（未紧跟条目标题行），已忽略: %s",
                    stripped,
                )
            continue

        # 四字段嵌套行：  - 影响：…
        m = _FIELD_RE.match(raw_line)
        if m and m.group(1).strip() in {label for label, _k in _FIELD_LABELS}:
            label = m.group(1).strip()
            key = dict(_FIELD_LABELS).get(label)
            if key:
                if key in current_fields:
                    current_fields[key] += f"\n{m.group(2).strip()}"
                else:
                    current_fields[key] = m.group(2).strip()
            continue

        # 其它带缩进行：当前字段续行（多行值场景），无字段则跳过
        if raw_line.startswith((" ", "\t")) and current_fields:
            last_key = list(current_fields.keys())[-1]
            if stripped and not stripped.startswith("-"):
                current_fields[last_key] += f"\n{stripped}"
            elif stripped:
                # 以「-」开头的续行（字段下的二级列表项、未知标签行等）不并入
                # 字段值：并入会把未知标签/嵌套标题文本混进上一字段的值，污染
                # 四字段结构化契约（规范写入方字段值恒为单行）。此处取「丢弃 +
                # 留痕」而非静默吞掉；用 DEBUG 而非 WARNING——本函数在就绪巡
                # 检热路径上被高频调用，告警级别会刷屏。
                _logger.debug(
                    "evolution: todo.md 字段续行以「-」开头，未并入字段 %s（丢弃）: %s",
                    last_key,
                    stripped,
                )
            continue

    _flush_entry()
    return entries


# ── todo.md 处理标记（回写与跳过）────────────────────────────────────
#
# 条目被自进化处理过（分析 run 落地、或用户接受/拒绝/删除）后，在其标题行正
# 下方写入一行标记。标记同时是「已处理」的权威信号：解析跳过它、分析 run 的
# 输入文本里也剥离它，从而避免同一 todo 条目被反复分析。


def _verdict_segment(verdict: dict) -> str:
    """AI 结论三段式（措辞与前端 verdictSummary 一致）。"""

    def _tri(value, yes: str, partial: str, no: str) -> str:
        return yes if value == "yes" else partial if value == "partial" else no

    return " / ".join(
        [
            "问题" + _tri(verdict.get("problem_exists"), "成立", "部分成立", "不成立"),
            "建议" + _tri(verdict.get("suggestion_sound"), "合理", "部分合理", "不合理"),
            "✓ 值得立项" if verdict.get("worth_spec") else "— 不需要",
        ]
    )


def _disposition_from_status(status) -> str:
    """条目状态 → 人类处理意见文案。"""
    if status in ("accepted", "auto_accepted"):
        return "接受"
    if status == "rejected":
        return "拒绝"
    return "待处理"


def render_todo_marker(item: dict, disposition: Optional[str] = None, deleted: bool = False) -> str:
    """生成标记行（含缩进）。不需要立项的条目只有 AI 结论，无处理/删除段。"""
    verdict = item.get("verdict") if isinstance(item.get("verdict"), dict) else {}
    line = f"{TODO_MARKER_KEY}：{_verdict_segment(verdict)}"
    if verdict.get("worth_spec"):
        line += f" · 处理：{disposition or '待处理'}" f" · 删除：{'是' if deleted else '否'}"
    return _TODO_MARKER_INDENT + line


def apply_marker_to_lines(lines: List[str], item: dict, marker: str):
    """在 lines 里定位该条目并写入/更新标记行；找不到返回 None（不改动）。

    定位口径与 item_id 同源：``## <date_section>`` → ``### <section>`` →
    ``- **<title>**``，三者缺一不可。已有标记行则原地替换（幂等），否则插到
    标题行正下方。
    """
    date_section = str(item.get("date_section") or "")
    section = str(item.get("section") or "")
    title = str(item.get("title") or "")
    if not (date_section and section and title):
        return None
    in_date = False
    in_section = False
    for i, line in enumerate(lines):
        m = _TODO_DATE_RE.match(line)
        if m:
            in_date = m.group(1) == date_section
            in_section = False
            continue
        m = _TODO_SECTION_RE.match(line)
        if m:
            in_section = in_date and m.group(1).strip() == section
            continue
        if not (in_date and in_section):
            continue
        m = _TODO_ENTRY_RE.match(line)
        if not m or m.group(1).strip() != title:
            continue
        out = list(lines)
        if i + 1 < len(out) and _TODO_MARKER_RE.match(out[i + 1]):
            out[i + 1] = marker
        else:
            out.insert(i + 1, marker)
        return out
    return None


def strip_processed_entries(text: str) -> str:
    """剥离带处理标记的条目整块（标题 + 其缩进行），供分析 run 的输入使用。

    处理标记行仅在其紧跟条目标题行（标题行的下一行，其间空白行忽略）时才
    生效：此时整块视为已处理并剥离。孤立标记行（其标题行已被手工删除/改写
    后残留）不连坐所在块，仅剔除标记行本身并记 WARNING。
    """
    out: List[str] = []
    block: List[str] = []

    def _flush() -> None:
        # 块首标题行（block[0]）之后的第一个非空白行是否为处理标记行
        marked = False
        for l in block[1:]:
            if not l.strip():
                continue
            marked = bool(_TODO_MARKER_RE.match(l))
            break
        if not marked:
            out.extend(block)
        block.clear()

    for line in text.splitlines():
        if _TODO_DATE_RE.match(line) or _TODO_SECTION_RE.match(line) or _TODO_ENTRY_RE.match(line):
            _flush()
            if _TODO_ENTRY_RE.match(line):
                block.append(line)
            else:
                out.append(line)
            continue
        if _TODO_MARKER_RE.match(line):
            # 标记行仅紧跟标题行（其间只夹空白行）才生效；孤立标记行不连坐
            # 所在块，仅剔除标记行本身
            if block and all(not l.strip() for l in block[1:]):
                block.append(line)
            else:
                _logger.warning(
                    "evolution: todo.md 孤立处理标记行（未紧跟条目标题行），已剔除: %s",
                    line.strip(),
                )
            continue
        if block:
            block.append(line)
        else:
            out.append(line)
    _flush()
    return "\n".join(out) + "\n"


def _resolve_project_path_by_name(project_name: str) -> Optional[Path]:
    """项目名 → 项目根路径（经 dashboard registry 解析，best effort）。

    解析失败（未注册、registry 不可用）返回 None——调用方按「跳过回写」处理，
    MUST NOT 因此影响分析/接受/删除主流程。懒导入避免 core.evolution 与
    core.dashboard 的模块级循环依赖。
    """
    if not project_name:
        return None
    try:
        from core.dashboard.registry import Registry

        for proj in Registry().discover() or []:
            if not isinstance(proj, dict):
                continue
            if (proj.get("name") or "") != project_name:
                continue
            path = proj.get("path")
            return Path(path) if path else None
    except Exception as e:  # noqa: BLE001 —— 解析失败不影响主流程
        _logger.debug("evolution: 项目 %s 路径解析失败: %s", project_name, e)
    return None


def clear_todo(project_path) -> dict:
    """把项目 ``.fenix/todo.md`` 截断为空（自省内容清理，保留文件本体）。

    截断而非删除：todo.md 被各项目 git 追踪，删除会在工作区显示为 deletion
    且要等下一轮自省才重建；空文件对 ``parse_todo_entries`` 等价于无条目，
    diff 也更干净。MUST NOT 触碰 ``.fenix/evolution/`` 下的 items.jsonl /
    草稿 / 水位——清空范围仅限 todo.md 这一个上游输入。

    - 项目无 ``.fenix/`` 目录或 todo.md 本就不存在 → ``existed: False``
      且不创建任何目录（MUST NOT 替无 todo 的项目凭空 mkdir）；
    - todo.md 不可访问（权限/IO 等 OSError 且非不存在类）→ ``ok: False``
      并写 WARNING 留痕（与 ``scan_ready_projects`` 同口径，不静默报成功）；
    - 与每日自省追加（``self_review._append_todo``）及自进化标记回写
      （``write_todo_marker``）共用同一把 flock，避免读-改-写交错；
    - 失败收敛进返回值，MUST NOT 抛异常（调用方为 dashboard 端点，
      多项目逐个清理时单个失败不应中断其余）。

    Returns: ``{ok, path, existed, error}``。
    """
    todo = Path(project_path) / ".fenix" / "todo.md"
    outcome: Dict[str, Any] = {
        "ok": False,
        "path": str(todo),
        "existed": False,
        "error": None,
    }
    # code-review item 893d537894b2：裸 is_file() 把 EACCES 等 OSError 吞成
    # False、按「无 todo.md 无需清理」误报成功；与 scan_ready_projects 同口径
    # 用 _path_access_error 三态探测，不可访问时 ok=False 并留痕。
    acc_err = _path_access_error(todo)
    if acc_err is not None:
        outcome["error"] = f"todo.md 不可访问: {acc_err}"
        _logger.warning("evolution: todo.md 不可访问，跳过清理 %s: %s", todo, acc_err)
        return outcome
    if not todo.is_file():
        # 非错误：无 todo.md 的项目本就无需清理
        outcome["ok"] = True
        return outcome
    outcome["existed"] = True

    def _do() -> None:
        _atomic_write(todo, "")
        outcome["ok"] = True

    try:
        _with_lock(todo, _do)
    except Exception as e:  # noqa: BLE001 —— 单个项目失败不穿透
        outcome["error"] = str(e)
        _logger.warning("evolution: 清空 todo.md 失败 %s: %s", todo, e)
    return outcome


def write_todo_marker(
    item: dict, disposition: Optional[str] = None, deleted: bool = False, project_path=None
) -> bool:
    """把该条目的处理标记写入其项目 ``.fenix/todo.md``。

    幂等：已有标记行则原地更新，不追加第二行。定位不到条目（用户改过标题 /
    删过条目）、项目路径解析失败、todo.md 不可读一律返回 False 并记 WARNING，
    MUST NOT 抛异常——回写是附带的记录动作，失败不得影响分析/处置主流程。
    """
    proot = (
        Path(project_path)
        if project_path
        else _resolve_project_path_by_name(str(item.get("project") or ""))
    )
    if proot is None:
        _logger.warning("evolution: 条目标记回写跳过——项目路径未解析: %s", item.get("project"))
        return False
    todo = Path(proot) / ".fenix" / "todo.md"
    marker = render_todo_marker(item, disposition, deleted)
    outcome = {"ok": False}

    def _do() -> None:
        try:
            text = todo.read_text(encoding="utf-8")
        except OSError as e:
            _logger.warning("evolution: todo.md 不可读，标记回写跳过: %s", e)
            return
        lines = apply_marker_to_lines(text.splitlines(), item, marker)
        if lines is None:
            _logger.warning(
                "evolution: todo.md 中未找到条目 %r（%s/%s），" "标记回写跳过",
                item.get("title"),
                item.get("date_section"),
                item.get("section"),
            )
            return
        _atomic_write(todo, "\n".join(lines) + "\n")
        outcome["ok"] = True

    try:
        _with_lock(todo, _do)
    except Exception as e:  # noqa: BLE001 —— 回写失败不穿透
        _logger.warning("evolution: 标记回写异常（已跳过）: %s", e)
    return outcome["ok"]


# ── 任务 2.6：增量筛选 ──────────────────────────────────────────────


def select_pending_entries(entries, known_ids_: set, limit: int) -> List[dict]:
    """过滤已入库条目后按 limit 截断，保持 todo.md 原始顺序（2.6）。

    - 过滤掉 ``known_ids``（items.jsonl 全量 id）中已存在的条目；
    - 同一条目在同一批内 MUST NOT 重复（按 id 去重）；
    - 截断后的未被处理条目 id 未入库，下一轮自然被再次选中（design D4）。
    """
    limit = max(0, int(limit))
    if limit == 0:
        return []
    out: List[dict] = []
    seen: set = set()
    for entry in entries:
        if len(out) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        project = entry.get("project", "")
        date_section = entry.get("date_section", "")
        section = entry.get("section", "")
        title = entry.get("title", "")
        if not (project and date_section and section and title):
            continue
        eid = item_id(project, date_section, section, title)
        if eid in known_ids_ or eid in seen:
            continue
        seen.add(eid)
        out.append({**entry, "id": eid})
    return out


# ── 任务 3.1：草稿落盘 ──────────────────────────────────────────────


def draft_dir(project_root, item_id_: str) -> Path:
    """单条目草稿根目录（gitignored 暂存区，design D2）。"""
    return evolution_dir(project_root) / "drafts" / item_id_


def materialize_draft(item: dict, project_root) -> Tuple[Optional[Path], str]:
    """把 agent 给出的 ``spec`` 全套文本落盘到 ``.fenix/evolution/drafts/<id>/``。

    落盘前 MUST 完整校验：``spec`` 缺任一必备文档（proposal_md / design_md /
    spec_md / tasks_md）、``capability`` / ``name`` 非法（``^[a-z0-9][a-z0-9-]*$``）
    → 返回 ``(None, 原因)`` 且 MUST NOT 半写文件。校验全部通过后才依次写
    ``proposal.md`` / ``specs/<capability>/spec.md`` / ``design.md`` /
    ``tasks.md`` / ``.spec.yaml``（``schema: spec-driven`` + ``created:
    <YYYY-MM-DD>`` + ``mode: full``）。

    Returns: ``(draft_dir, "")`` 成功；``(None, 原因)`` 失败。3.1
    """
    spec = item.get("spec") if isinstance(item, dict) else None
    if not isinstance(spec, dict):
        return None, "条目缺 spec 内容（worth_spec 为真时必填）"
    name = spec.get("name")
    capability = spec.get("capability")
    if not isinstance(name, str) or not _KEBAB_RE.match(name):
        return None, f"spec.name 非法（应满足 {_KEBAB_RE.pattern}）: {name!r}"
    if not isinstance(capability, str) or not _KEBAB_RE.match(capability):
        return None, (f"spec.capability 非法（应满足 {_KEBAB_RE.pattern}）: {capability!r}")
    missing = [
        doc
        for doc in ("proposal_md", "design_md", "spec_md", "tasks_md")
        if not isinstance(spec.get(doc), str) or not spec.get(doc)
    ]
    if missing:
        return None, f"spec 内容缺必备文档: {', '.join(missing)}"

    eid = item.get("id") or item_id(
        str(item.get("project", "")),
        str(item.get("date_section", "")),
        str(item.get("section", "")),
        str(item.get("title", "")),
    )
    eid = str(eid or "")
    # 路径越界校验（code-review item 79a8a0a141f5，与 reject_item/delete_item
    # 同款防护）：eid 来自 agent 产出 JSON（read_contract 只校验 id 为字符串，
    # 不校验内容），可携带
    # ``..`` 或路径分隔符——直接拼草稿路径可写出 drafts 基目录。越界拒绝落盘
    # （调用方置 draft_failed）。
    d = _safe_draft_dir(project_root, eid)
    if d is None:
        return None, f"条目 id 非法（草稿路径越界风险）: {eid!r}"
    try:
        d.mkdir(parents=True, exist_ok=True)
        spec_sub = d / "specs" / capability
        spec_sub.mkdir(parents=True, exist_ok=True)
        (d / "proposal.md").write_text(spec["proposal_md"], encoding="utf-8")
        (spec_sub / "spec.md").write_text(spec["spec_md"], encoding="utf-8")
        (d / "design.md").write_text(spec["design_md"], encoding="utf-8")
        (d / "tasks.md").write_text(spec["tasks_md"], encoding="utf-8")
        (d / ".spec.yaml").write_text(
            SPEC_YAML_TEMPLATE.format(created=datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            encoding="utf-8",
        )
    except OSError as e:
        shutil.rmtree(d, ignore_errors=True)
        return None, f"草稿落盘失败: {e}"
    return d, ""


def _spec_summary(spec: dict) -> str:
    """agent 原始 spec 内容摘要（供 draft_failed 条目记录，3.3）。"""
    if not isinstance(spec, dict):
        return ""
    return json.dumps(
        {
            "name": spec.get("name"),
            "capability": spec.get("capability"),
            "proposal_len": len(str(spec.get("proposal_md") or "")),
            "spec_len": len(str(spec.get("spec_md") or "")),
            "design_len": len(str(spec.get("design_md") or "")),
            "tasks_len": len(str(spec.get("tasks_md") or "")),
        },
        ensure_ascii=False,
    )


# ── 任务 3.2：同源 lint 预检 ────────────────────────────────────────


def lint_draft(draft_dir_: Path, project_root) -> List[str]:
    """对草稿目录执行与 daemon 晋升同源的 lint 预检（3.2）。

    ``sys.path`` 指向项目 ``.fenix/`` 后调用 ``core.deliverables.lint_declared``
    与 ``core.deliverables.lint_tasks_parseable``（与 fenixd.py 启动时同款
    sys.path 注入），返回合并后的 violation 清单。MUST NOT 自实现第二套声明
    解析。lint 自身故障 fail-open（记 WARNING 返回空清单，不阻塞）。

    注入的实际解析范围（如实标注）：常驻进程（daemon）中顶层包 ``core`` 早已
    进 ``sys.modules``，``from core.deliverables import ...`` 的子模块解析走已
    缓存 core 包的 ``__path__``（daemon 自身安装根），插入 ``sys.path[0]`` 并
    不改变解析目标；注入只在 core 尚未导入的裸进程（独立 CLI/测试）生效。
    两种形态下 lint 结果一致；注入项在 lint 结束后恢复，不长期驻留 sys.path。
    """
    proot = Path(project_root)
    fenix_dir = str(proot / ".fenix")
    injected = fenix_dir not in sys.path
    if injected:
        sys.path.insert(0, fenix_dir)
    try:
        from core.deliverables import lint_declared, lint_tasks_parseable

        violations: List[str] = []
        for fn in (lint_declared, lint_tasks_parseable):
            try:
                violations.extend(fn(draft_dir_, proot) or [])
            except Exception as e:
                _logger.warning("evolution: 草稿 lint 异常（非阻塞放行）: %s", e)
        return violations
    except ImportError as e:
        _logger.warning(
            "evolution: 草稿 lint 模块导入失败（fail-open 返回空清单）: %s", e
        )
        return []
    finally:
        if injected:
            sys.path.remove(fenix_dir)


# ── 任务 3.3：落地单条复核结果 ─────────────────────────────────────


def ingest_item(item: dict, project_root) -> str:
    """落地单条复核结果到 items.jsonl，返回条目状态（3.3）。

    - ``verdict.worth_spec`` 非真 → 入库置 ``analyzed``（不建草稿目录）；
    - 为真 → 落盘 → lint → 有 violation/内容缺失则删除草稿目录、置
      ``draft_failed`` 并记录 violation 原文与 spec 摘要；通过置 ``pending``。

    写入条目 MUST 保留 todo.md 原文四字段（impact/evidence/analysis/suggestion）。

    标记回写 MUST NOT 显式传 project_path（code-review item 8e29b50298c7）：
    write_todo_marker 按条目 project 名经 registry 解析源项目 todo.md；钉死框架
    根会使多项目部署下非框架项目条目的标记在框架 todo.md 里落空（或误标同名条目）。
    """
    verdict = item.get("verdict") if isinstance(item, dict) else None
    worth_spec = bool(isinstance(verdict, dict) and verdict.get("worth_spec"))
    title = str(item.get("title", ""))
    eid = item.get("id") or item_id(
        str(item.get("project", "")),
        str(item.get("date_section", "")),
        str(item.get("section", "")),
        title,
    )

    base = {
        "id": eid,
        "project": str(item.get("project", "")),
        "date_section": str(item.get("date_section", "")),
        "section": str(item.get("section", "")),
        "title": title,
        "impact": str(item.get("impact") or ""),
        "evidence": str(item.get("evidence") or ""),
        "analysis": str(item.get("analysis") or ""),
        "suggestion": str(item.get("suggestion") or ""),
        "verdict": verdict,
        "analysis_md": item.get("analysis_md") or "",
        "spec": item.get("spec") if isinstance(item.get("spec"), dict) else None,
        "spec_summary": _spec_summary(
            item.get("spec") if isinstance(item.get("spec"), dict) else None
        ),
        "degraded": item.get("degraded"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decided_at": None,
        "decided_by": None,
        "spec_name": None,
        "violations": None,
        "draft_failed_reason": None,
    }

    if not worth_spec:
        base["status"] = "analyzed"
        upsert_item(project_root, base)
        write_todo_marker(base)
        return "analyzed"

    d, reason = materialize_draft(base, project_root)
    if d is None:
        base["status"] = "draft_failed"
        base["draft_failed_reason"] = reason
        _logger.warning("evolution: 条目 %s 草稿落盘失败: %s", eid, reason)
        upsert_item(project_root, base)
        write_todo_marker(base)
        return "draft_failed"

    violations = lint_draft(d, project_root)
    if violations:
        shutil.rmtree(d, ignore_errors=True)
        base["status"] = "draft_failed"
        base["violations"] = violations
        base["draft_failed_reason"] = "；".join(violations)
        _logger.warning(
            "evolution: 条目 %s 草稿 lint 未通过（已删除草稿）: %s",
            eid,
            base["draft_failed_reason"],
        )
        upsert_item(project_root, base)
        write_todo_marker(base)
        return "draft_failed"

    base["status"] = "pending"
    upsert_item(project_root, base)
    write_todo_marker(base)
    return "pending"


# ── 任务 3.4：SPEC 名生成与冲突消解 ────────────────────────────────


def resolve_spec_name(name: str, item_id_: str, project_root, state_machine) -> Optional[str]:
    """生成并消解接受路径的 SPEC 名（3.4）。

    基名 ``evo-<name>``；与 ``spec/changes/<candidate>``、STATE.md 既有条目名、
    ``spec/archive/`` 既有归档（归档名以 ``-<candidate>`` 结尾，或按
    ``_archive_name_candidates`` 归一化候选集与 candidate 全等比较命中）任一
    冲突时追加 ``-<item_id 前 6 位>`` 并重新校验全部三处；仍冲突返回 None
    （调用方置 draft_failed 并告警）。
    ``name`` 非法（非 kebab-case）直接返回 None。
    """
    if not isinstance(name, str) or not _KEBAB_RE.match(name):
        return None
    proot = Path(project_root)

    def _conflicted(candidate: str) -> bool:
        if (proot / "spec" / "changes" / candidate).is_dir():
            return True
        try:
            if state_machine is not None and candidate in state_machine.read_all():
                return True
        except Exception as e:
            # STATE 读取故障保守判冲突（fail-closed，code-review item
            # bc6af1b9fe13）：视为已占用，走加后缀重试 / 返回 None 立项失败的
            # 路径，而非放行后 add_spec 覆盖既有同名 STATE 条目的状态。
            _logger.warning("evolution: 读取 STATE 判定重名失败，保守按冲突处理: %s", e)
            return True
        # 归档清单并入撞名检查（add-archive-state-migration 3.3）：条目已迁出
        # 的 SPEC 名同样不可复用——复用会与 spec/archive/ 下既有归档目录产生
        # 归属歧义（resolve_spec_dir 归档回退按名解析）。
        try:
            from core.dashboard.data.state import parse_archived_state

            if candidate in parse_archived_state(proot):
                return True
        except Exception as e:
            _logger.warning("evolution: 读取归档清单判定重名失败: %s", e)
        arch_root = proot / "spec" / "archive"
        if arch_root.is_dir():
            try:
                for archived in arch_root.iterdir():
                    if not archived.is_dir():
                        continue
                    # 归档名以 ``-<candidate>`` 结尾（如 ``add-<name>`` 前缀
                    # 形态）或其归一化候选集含 candidate（覆盖
                    # ``YYYY-MM-DD-<name>-<n>`` / ``<name>-<epoch>`` 形态，
                    # 见 code-review item c99fdc8e6c0c）均判冲突。
                    if (archived.name.endswith("-" + candidate)
                            or candidate in _archive_name_candidates(
                                archived.name)):
                        return True
            except OSError:
                pass
        return False

    candidate = f"evo-{name}"
    if _conflicted(candidate):
        candidate = f"evo-{name}-{str(item_id_)[:6]}"
        if _conflicted(candidate):
            return None
    return candidate


# ── 任务 3.5：接受路径 ─────────────────────────────────────────────


def _git_commit(project_root, spec_name: str) -> Tuple[bool, str]:
    """仅 add 目标 spec 目录后路径限定提交（MUST NOT ``git add -A`` / ``git add .``）。

    commit 同样以 ``spec/changes/<name>`` 为 pathspec，确保索引中残留的
    其他暂存内容不会被裹挟进本条提交。

    Returns: ``(ok, error)``；ok=False 时调用方负责清理未跟踪副本。
    """
    git = ["git", "-C", str(project_root)]
    try:
        add = subprocess.run(
            git + ["add", "--", f"spec/changes/{spec_name}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git add 失败: {e}"
    if add.returncode != 0:
        return False, f"git add 失败: {add.stderr.strip()[:300]}"
    try:
        commit = subprocess.run(
            git + ["commit", "-m", f"[fenix] spec: {spec_name}", "--", f"spec/changes/{spec_name}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git commit 失败: {e}"
    if commit.returncode != 0:
        return False, f"git commit 失败: {commit.stderr.strip()[:300]}"
    return True, ""


def _git_remove_committed_dir(project_root, rel_path: str) -> Tuple[bool, str]:
    """rm 已提交的目录副本并路径限定提交（注册失败回滚专用）。

    ``git rm -r`` + 仅含该路径的 commit（MUST NOT ``git add -A``／裹挟索引中
    其他暂存内容）。任一步失败返回 ``(False, 错误)``，由调用方降级为告警
    说明残留目录，MUST NOT 让清理失败掩盖注册失败本身。
    """
    git = ["git", "-C", str(project_root)]
    try:
        rm = subprocess.run(
            git + ["rm", "-r", "-q", "--", rel_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git rm 失败: {e}"
    if rm.returncode != 0:
        return False, f"git rm 失败: {rm.stderr.strip()[:300]}"
    try:
        commit = subprocess.run(
            git + ["commit", "-m", f"[fenix] spec: remove {rel_path}", "--", rel_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git commit 失败: {e}"
    if commit.returncode != 0:
        return False, f"git commit 失败: {commit.stderr.strip()[:300]}"
    return True, ""


def _write_admin_warning(project_root, message: str) -> None:
    """写一条 admin WARNING 告警（AdminStore escalation，major 级）。

    写失败静默降级（观测增强，不阻断接受/拒绝主流程）。
    """
    try:
        from core.admin_store import AdminStore, ESCALATION

        store = AdminStore(project_root, logger=_logger)
        store.append(
            {
                "kind": ESCALATION,
                "severity": "major",
                "signal_type": "self-evolution",
                "spec": None,
                "description": message,
                # 本函数仅收到 message（接受失败的因果文本），故 evidence 以
                # 告警正文为据；recommended_action 按调用方语境（accept_failed
                # 台账 + spec/changes 残留目录）给出人工跟进口径，
                # 与 self_review.py 等其他 escalation 写入点形态对齐。
                "evidence": message,
                "recommended_action": (
                    "人工核对自进化台账对应条目的 accept_failed 原因与 "
                    "spec/changes 残留目录，按告警正文的后续处理说明"
                    "（后缀重试/清理残留）跟进或人工接手"
                ),
            }
        )
    except Exception as e:
        _logger.warning("evolution: admin 告警写入失败（降级）: %s", e)


def next_spec_run_at(run_at, now=None) -> Optional[str]:
    """每日执行时刻 → 下一次到期的 UTC ISO8601（``self_evolution.spec_run_at``）。

    ``run_at`` 为 ``"HH:mm"``（按**本地时区**解释，与 ``admin.self_review.run_at``
    同一口径），返回该时刻下一次到达的 UTC ISO——STATE.md 的 ``start_after`` 全链
    UTC，转换在此一次完成，消费方（``start_after_pending``）不做时区判断。

    规则：取本地当日该时刻；已过或恰好等于 now 则取次日。``run_at`` 为
    None/非法（非字符串、格式不符、越界）返回 None = 不设门（立项后立即执行），
    脏值 fail-open 与 ``start_after_pending`` 的容错同型。合法性判定复用
    ``ConfigLoader.is_valid_hhmm``——HH:mm 规则不在本模块另立一份。
    """
    from core.config import ConfigLoader  # 局部导入：避免 core.config ↔ 本模块的导入顺序耦合

    if not ConfigLoader.is_valid_hhmm(run_at):
        return None
    hh, mm = (int(x) for x in run_at.split(":"))
    # naive 视为本地时间（datetime.astimezone 的既有语义），aware 则换算到本地：
    # 两种情况下一行收敛，调用方传 UTC 或本地 now 都得到同一结果
    now_local = (now if now is not None else datetime.now()).astimezone()
    target = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now_local:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc).isoformat()


def accept_item(
    item_id_: str,
    project_root,
    state_machine,
    decided_by: str = "manual",
    start_after: Optional[str] = None,
) -> dict:
    """接受路径（人工同意与自动接受共用实现，design D6；3.5）。

    顺序固定：前置状态校验 → resolve_spec_name → 复制到 spec/changes →
    仅 add 该目录并提交 → add_spec(drafted, priority=5[, start_after]) →
    删暂存草稿 → 标 accepted/auto_accepted。校验到写回全程持 items.jsonl
    同一把 flock（compare-and-set，code-review item fba717748316）：daemon
    自动接受与 dashboard 人工同意并发时只有先到者通过 pending 校验并立项，
    后到者锁内重读即见最终状态、按幂等语义返回现状。失败分支：
    - 目标名已存在且非本条目此前失败残留（冲突检查后窗口期被外部参与者
      创建）→ 不删不动、保留暂存草稿、置 accept_failed + 告警，重试经
      resolve_spec_name 换后缀名立项；
    - 提交失败 → 删除 spec/changes 副本（避免主树未跟踪文件）、保留暂存
      草稿、置 accept_failed + 告警；
    - 注册失败 → 清理已提交的 spec/changes 副本（git rm + 路径限定提交，
      使重试可复用原名；清理失败则保留副本并在告警中说明残留与重试
      后缀策略）、保留暂存草稿、置 accept_failed + 告警。

    ``start_after``：UTC ISO8601，非空则写进新 SPEC 的 STATE 条目，dispatch
    在到点前静默跳过（定时拾取，add-spec-scheduling-controls D2）；None 表示
    立项后立即进入调度（缺省，原行为）。调用方负责把 ``spec_run_at`` 配置经
    ``next_spec_run_at`` 换算成本参数。

    Returns: ``{"ok", "status", "spec_name", "error"}``；非 pending /
    accept_failed 状态幂等返回现状（不重复提交或注册）。
    """
    now = datetime.now(timezone.utc).isoformat()
    path = items_path(project_root)

    def _persist(rec: dict) -> None:
        # 锁内单条写回：与 upsert_item 的锁内主体同型（读-改-写 + 原子替换），
        # 但 MUST NOT 再走 upsert_item/read_items——同进程对同一把
        # ``.items.jsonl.lock`` 二次 flock 会自阻塞（见 _with_lock）。
        current = _read_items_unlocked(path)
        current[rec["id"]] = rec
        _atomic_write(
            path,
            "".join(json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)),
        )

    def _do() -> dict:
        # [fenix-ignore:17b84b130a08] 整体持锁（含 copytree 与 git 子进程）是
        # compare-and-set 的既定取舍（见下注释）：拆锁会让并发接受者看到中间态；
        # git 子进程已有 timeout=60 兜底、失败路径均有告警留痕，收敛锁窗的收益
        # 不抵拆 CAS 结构的风险。
        # 「状态校验 → 复制/提交/注册 → 写回」整体持 items.jsonl flock 构成
        # compare-and-set（code-review item fba717748316）：daemon 自动接受与
        # dashboard 人工同意并发时，后到者在锁内重读必见先到者写回的最终状态，
        # 走幂等分支返回现状，不再各自立项出两份 spec 目录与两次 STATE 注册。
        items = _read_items_unlocked(path)
        rec = items.get(item_id_)
        if rec is None:
            return {"ok": False, "status": None, "spec_name": None, "error": f"条目不存在: {item_id_}"}
        if rec.get("status") not in ("pending", "accept_failed"):
            # 其它状态幂等返回现状（accepted/auto_accepted/rejected/analyzed/
            # draft_failed 均不重复提交或注册）
            return {
                "ok": True,
                "status": rec.get("status"),
                "spec_name": rec.get("spec_name"),
                "error": None,
            }

        spec = rec.get("spec") if isinstance(rec.get("spec"), dict) else None
        if spec is None:
            rec["status"] = "draft_failed"
            rec["draft_failed_reason"] = "条目无 spec 内容，无法接受"
            _persist(rec)
            return {
                "ok": False,
                "status": "draft_failed",
                "spec_name": None,
                "error": rec["draft_failed_reason"],
            }
        name = resolve_spec_name(spec.get("name"), item_id_, project_root, state_machine)
        if name is None:
            rec["status"] = "draft_failed"
            rec["draft_failed_reason"] = "SPEC 名无法消解冲突"
            _persist(rec)
            _write_admin_warning(project_root, f"自进化条目 {item_id_} 接受失败：SPEC 名冲突无法消解")
            return {
                "ok": False,
                "status": "draft_failed",
                "spec_name": None,
                "error": rec["draft_failed_reason"],
            }

        # 路径越界校验（code-review item 79a8a0a141f5）：eid 可携 ``..``/分隔符
        # （agent 产出 JSON 未校验 id），拼路径可越出 drafts 基目录——成功后
        # ``shutil.rmtree(src)`` 会删任意目录。与 reject_item/delete_item 同款
        # _safe_draft_dir 防护，越界置 accept_failed 并告警。
        src = _safe_draft_dir(project_root, str(item_id_ or ""))
        if src is None:
            rec["status"] = "accept_failed"
            rec["draft_failed_reason"] = "草稿目录路径非法或越界"
            _persist(rec)
            _write_admin_warning(project_root, f"自进化条目 {item_id_} 接受失败：草稿目录路径非法或越界")
            return {
                "ok": False,
                "status": "accept_failed",
                "spec_name": None,
                "error": rec["draft_failed_reason"],
            }
        dest = Path(project_root) / "spec" / "changes" / name
        if dest.exists():
            # code-review item 41d71f597331：resolve_spec_name 的冲突检查与本点
            # 之间无锁覆盖 items.jsonl 之外的外部写入者（人工 fenix-new 立项等），
            # MUST NOT 无条件 rmtree——窗口内他方新建的同名目录会被整体删除，再被
            # 本条目草稿顶替，两个不同来源的逻辑 spec 混淆。仅当目录确为本条目
            # 此前失败残留（rec 记录的 spec_name 即本名；草稿/副本内容不含 id，
            # 记录级归属是唯一可靠信号）时才清理后按原名重试；其余一律置
            # accept_failed + 告警，不删不动，重试经 resolve_spec_name 换后缀名。
            if rec.get("spec_name") != name:
                rec["status"] = "accept_failed"
                rec["draft_failed_reason"] = (
                    f"spec/changes/{name} 已存在且非本条目残留（名字被占用）"
                )
                _persist(rec)
                _write_admin_warning(
                    project_root,
                    f"自进化条目 {item_id_} 接受失败：spec/changes/{name} 已存在且查非"
                    "本条目此前残留（疑似冲突检查窗口期被外部立项占用），本条目未做"
                    f"任何改动；重试将改用 -{str(item_id_)[:6]} 后缀名立项",
                )
                return {
                    "ok": False,
                    "status": "accept_failed",
                    "spec_name": None,
                    "error": rec["draft_failed_reason"],
                }
            # 本条目此前失败残留：清掉再复制（重试复用原名），防残留污染
            shutil.rmtree(dest, ignore_errors=True)
        try:
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                rec["status"] = "accept_failed"
                rec["draft_failed_reason"] = "暂存草稿目录缺失"
                _persist(rec)
                _write_admin_warning(project_root, f"自进化条目 {item_id_} 接受失败：暂存草稿目录缺失")
                return {
                    "ok": False,
                    "status": "accept_failed",
                    "spec_name": None,
                    "error": rec["draft_failed_reason"],
                }
        except OSError as e:
            # 复制失败：清理半写副本（对齐下方提交失败分支的清理纪律），
            # 否则残留目录永久占用原名，重试被迫换后缀立项
            shutil.rmtree(dest, ignore_errors=True)
            rec["status"] = "accept_failed"
            rec["draft_failed_reason"] = f"草稿复制失败: {e}"
            _persist(rec)
            _write_admin_warning(project_root, f"自进化条目 {item_id_} 接受失败：{e}")
            return {
                "ok": False,
                "status": "accept_failed",
                "spec_name": None,
                "error": rec["draft_failed_reason"],
            }

        ok, err = _git_commit(project_root, name)
        if not ok:
            # 提交失败：删除副本（主树无未跟踪文件），保留暂存草稿可重试
            shutil.rmtree(dest, ignore_errors=True)
            rec["status"] = "accept_failed"
            rec["draft_failed_reason"] = err
            _persist(rec)
            _write_admin_warning(project_root, f"自进化条目 {item_id_} 接受失败（提交失败）: {err}")
            return {"ok": False, "status": "accept_failed", "spec_name": name, "error": err}

        # 提交成功 → 注册；start_after 非空 = 定时拾取（到点前 dispatch 门控跳过），
        # 为空则 drafted 立即进入调度（原行为）。
        # 哨兵字符串 "manual"（add-spec-manual-activation D5，evo 同意立项的「手工
        # 激活」档）原样落入 entry：MUST NOT 在此引入 parse_utc 时间换算——哨兵
        # 不是时间，经 start_after_pending 显式判等后即「永不到期、待人工激活」。
        registered = False
        entry = {"status": "drafted", "priority": 5}
        if start_after:
            entry["start_after"] = start_after
        try:
            if state_machine is not None:
                registered = state_machine.add_spec(name, entry)
            else:
                registered = True  # state_machine 缺失（如纯路径测试）视为注册成功
        except Exception as e:
            _logger.warning("evolution: 条目 %s 注册 %s 失败: %s", item_id_, name, e)
            registered = False
            err = str(e)

        if not registered:
            # 注册失败：清理已提交的 spec/changes/<name> 副本（code-review item
            # 9d550ea7ac1c）——否则重试时 resolve_spec_name 判该名冲突换后缀
            # 立项，主树留下两份同一逻辑 spec 的目录、前一份成无主残留。清理
            # 失败（git 状态不确定）不掩盖注册失败本身，降级为在告警中说明
            # 残留目录与重试后缀策略。
            rel_dir = f"spec/changes/{name}"
            cleaned, clean_err = _git_remove_committed_dir(project_root, rel_dir)
            rec["status"] = "accept_failed"
            rec["draft_failed_reason"] = err or "STATE 注册失败"
            rec["spec_name"] = name
            _persist(rec)
            if cleaned:
                residue_note = f"已清理 {rel_dir} 副本，重试可复用原名"
            else:
                residue_note = (
                    f"{rel_dir} 副本残留未清理: {clean_err}；重试将改用"
                    f" -{str(item_id_)[:6]} 后缀立项，残留目录需人工处理"
                )
            _write_admin_warning(
                project_root,
                f"自进化条目 {item_id_} 接受失败（注册失败）: "
                f"{rec['draft_failed_reason']}（{residue_note}）",
            )
            return {
                "ok": False,
                "status": "accept_failed",
                "spec_name": name,
                "error": rec["draft_failed_reason"],
            }

        # 注册成功 → 删暂存草稿 + 更新状态
        shutil.rmtree(src, ignore_errors=True)
        rec["status"] = "auto_accepted" if decided_by == "auto" else "accepted"
        rec["decided_by"] = decided_by
        rec["decided_at"] = now
        rec["spec_name"] = name
        _persist(rec)
        write_todo_marker(rec, disposition=_disposition_from_status(rec["status"]))
        return {"ok": True, "status": rec["status"], "spec_name": name, "error": None}

    return _with_lock(path, _do)


# ── 任务 3.6：拒绝路径 ─────────────────────────────────────────────


def _safe_draft_dir(project_root, item_id_: str) -> Optional[Path]:
    """解析草稿目录并校验其位于 drafts 基目录之内（符号链接越界拒绝）。

    item_id 含路径分隔符或 ``..``，或 resolve() 后不在 drafts 基目录内 →
    返回 None（调用方报错且不删除任何文件）。3.6
    """
    if (
        not item_id_
        or item_id_ in (".", "..")
        or "/" in item_id_
        or "\\" in item_id_
        or "\x00" in item_id_
    ):
        return None
    base = (evolution_dir(project_root) / "drafts").resolve()
    candidate = (base / item_id_).resolve()
    if not candidate.is_relative_to(base):
        return None
    return candidate


def reject_item(item_id_: str, project_root) -> dict:
    """拒绝路径（3.6）：删除该条目草稿目录并置 ``rejected``。

    仅 ``pending`` / ``draft_failed`` / ``accept_failed`` 可拒绝；
    ``accepted`` / ``auto_accepted`` / ``rejected`` 返回错误且不改动任何
    文件。删除前经 ``_safe_draft_dir`` 校验路径（符号链接解析后越界拒绝）。

    「状态校验 → 删草稿目录 → 写回」整体持 items.jsonl 同一把 flock 构成
    compare-and-set（与 ``accept_item`` 同范式，code-review item
    7d60d7df0370）：拒绝与 daemon 自动接受并发时，后到者在锁内重读必见
    先到者写回的最终状态、按幂等语义报错返回现状，不再以锁外读取的旧
    记录无条件覆盖——避免出现台账 ``rejected`` 而 STATE 仍挂 drafted SPEC
    且目录已提交的两存储矛盾。
    """
    now = datetime.now(timezone.utc).isoformat()
    path = items_path(project_root)

    def _do() -> dict:
        items = _read_items_unlocked(path)
        rec = items.get(item_id_)
        if rec is None:
            return {"ok": False, "status": None, "error": f"条目不存在: {item_id_}"}
        status = rec.get("status")
        if status not in ("pending", "draft_failed", "accept_failed"):
            # 并发自动接受/拒绝先到并已写回最终状态：锁内重读即见，报错
            # 返回现状（幂等），MUST NOT 用锁外旧记录覆盖
            return {
                "ok": False,
                "status": status,
                "error": f"状态 {status} 不可拒绝（已决定条目不可拒绝）",
            }

        target = _safe_draft_dir(project_root, item_id_)
        if target is None:
            return {"ok": False, "status": status, "error": "草稿目录路径非法或越界，拒绝删除"}
        if target.is_dir():
            try:
                # 越界/符号链接校验已由 _safe_draft_dir 完成（resolve +
                # is_relative_to，两次 resolve 间无文件系统变更），不再重复
                # 判定（code-review item 1c78b6735e1c）
                shutil.rmtree(target)
            except OSError as e:
                return {"ok": False, "status": status, "error": f"草稿删除失败: {e}"}

        rec["status"] = "rejected"
        rec["decided_at"] = now
        # 锁内单条写回：与 accept_item._persist 同型（读-改-写 + 原子替换），
        # MUST NOT 再走 upsert_item/read_items——同进程对同一把
        # ``.items.jsonl.lock`` 二次 flock 会自阻塞（见 _with_lock）。
        current = _read_items_unlocked(path)
        current[rec["id"]] = rec
        _atomic_write(
            path,
            "".join(json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)),
        )
        write_todo_marker(rec, disposition="拒绝")
        return {"ok": True, "status": "rejected", "error": None}

    return _with_lock(path, _do)


def delete_item(item_id_: str, project_root) -> dict:
    """删除路径：把条目记录移出 ``items.jsonl`` 并清理其草稿目录（硬删）。

    语义（用户确认）：
    - **任意状态均可删**（不设状态门，`accepted` / `auto_accepted` 亦允许）；
    - **硬删**：记录从 items.jsonl 移除，不写墓碑。已知后果——该 id 不再出现在
      ``known_ids()`` 中，todo.md 里同名记录会在下一轮分析 run 重新入库；
      前端确认弹窗须向用户明示此后果。
    - 草稿目录存在则一并删除（路径经 ``_safe_draft_dir`` 校验；符号链接越界
      拒绝并保持记录不动），避免留下无主目录。

    读-改-写在同一把 flock 内完成（与 ``upsert_item`` 同范式），避免与 daemon
    侧写入交错。返回 ``{"ok", "status", "error"}``；``status`` 为删除前状态。
    """
    path = items_path(project_root)
    outcome: Dict[str, Any] = {}

    def _do() -> None:
        current = _read_items_unlocked(path)
        rec = current.get(item_id_)
        if rec is None:
            outcome.update({"ok": False, "status": None, "error": f"条目不存在: {item_id_}"})
            return
        status = rec.get("status")

        target = _safe_draft_dir(project_root, item_id_)
        if target is None:
            outcome.update(
                {"ok": False, "status": status, "error": "草稿目录路径非法或越界，拒绝删除"}
            )
            return
        if target.is_dir():
            try:
                # 越界/符号链接校验已由 _safe_draft_dir 完成，不再重复判定
                # （code-review item 1c78b6735e1c）
                shutil.rmtree(target)
            except OSError as e:
                outcome.update({"ok": False, "status": status, "error": f"草稿删除失败: {e}"})
                return

        current.pop(item_id_, None)
        content = "".join(
            json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)
        )
        _atomic_write(path, content)
        # 删除成功后回写标记（保留删除前的处理意见 + 删除：是）；回写失败不影响删除
        write_todo_marker(rec, disposition=_disposition_from_status(status), deleted=True)
        outcome.update({"ok": True, "status": status, "error": None})

    try:
        _with_lock(path, _do)
    except Exception as e:  # noqa: BLE001 —— 存储异常收敛为错误对象，不抛穿
        return {"ok": False, "status": None, "error": f"条目删除失败: {e}"}
    return outcome


# ── 条目保留与自动清理（evo-item-retention-doc-tracking D1-D3）─────


def prune_items(project_root, now: Optional[datetime] = None) -> dict:
    """按保留策略清理 items.jsonl：保留最近 N 天 ∪ 最近 M 条并集，其余硬删。

    保留判据（design D1）：删除条件为「不在最近 ITEM_RETENTION_DAYS 天窗口
    内」AND「不在按创建时间倒序的前 ITEM_RETENTION_MIN 名内」——保留两者
    并集（数量较多者）。排序键 ``(created_at or "", id)`` 倒序，``id`` 作
    确定性兜底（等时条目在多次运行间稳定）。创建时间缺失或无法解析 MUST 判
    为保留（fail-open，D3：年龄不可知不得误删新条目）。清理不设状态门：未决
    条目（pending/analyzed 等）同样受保留策略约束。

    删除复用既有 ``delete_item``（D2：记录移出 items.jsonl + 草稿目录删除含
    越界校验 + todo.md 标记幂等回写，读-改-写在 flock 内），逐条 try/except
    ——单条异常计入 failed 不中断其余（spec「单条删除失败不中断其余清理」）。

    计数口径：``delete_item`` 以返回值（非异常）表达预期失败——ok=False（条目
    已被并发删除 / 草稿路径越界 / 草稿删除 OSError）时该记录 MUST NOT 计入
    deleted，MUST 计入 failed 与 details，且 MUST NOT 从 kept 中移除（记录
    仍在 items.jsonl；kept = total - deleted 天然满足）。

    Returns: ``{"total", "kept", "deleted", "failed", "details"}``。无受害者
    时 MUST 直接返回、不触发任何写。``now`` 为时区感知 datetime，缺省
    ``datetime.now(timezone.utc)``。
    """
    items = read_items(project_root)
    if not items:
        return {"total": 0, "kept": 0, "deleted": 0, "failed": 0, "details": []}
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ITEM_RETENTION_DAYS)

    # 确定性次序：创建时间倒序 + id 兜底
    ordered = sorted(
        items.values(),
        key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or "")),
        reverse=True,
    )

    # 保留集 = 前 ITEM_RETENTION_MIN 名 ∪ 最近 ITEM_RETENTION_DAYS 天 ∪
    # 创建时间缺失/非法（年龄不可知 → 保留侧）
    keep_ids = {r["id"] for r in ordered[:ITEM_RETENTION_MIN]}
    for r in ordered:
        if r["id"] in keep_ids:
            continue
        created = _parse_iso(r.get("created_at"))
        if created is None or created >= cutoff:
            keep_ids.add(r["id"])

    victims = [r for r in ordered if r["id"] not in keep_ids]
    if not victims:
        return {"total": len(items), "kept": len(items), "deleted": 0, "failed": 0, "details": []}

    deleted = 0
    failed = 0
    details: List[dict] = []
    for rec in victims:
        eid = rec.get("id")
        try:
            result = delete_item(eid, project_root)
        except Exception as e:  # noqa: BLE001 —— 单条异常不中断其余清理
            failed += 1
            details.append({"id": eid, "ok": False, "error": str(e)})
            continue
        if result.get("ok"):
            deleted += 1
        else:
            # 预期失败（并发删除/越界/OSError）：记录仍在 items.jsonl
            failed += 1
            details.append(
                {
                    "id": eid,
                    "ok": False,
                    "status": result.get("status"),
                    "error": result.get("error"),
                }
            )
    return {
        "total": len(items),
        "kept": len(items) - deleted,
        "deleted": deleted,
        "failed": failed,
        "details": details,
    }


# ── SPEC 位置解析（evo-item-retention-doc-tracking D5）────────────────

# 日期前缀正则：YYYY-MM-DD-<name>
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
# 数字后缀正则：<name>-<digits>
_NUM_SUFFIX_RE = re.compile(r"-\d+$")


def _archive_name_candidates(dirname: str) -> List[str]:
    """对归档目录名生成全部归一化候选集（含原样）。

    覆盖三类归档命名：
    - ``YYYY-MM-DD-<name>``（标准归档，剥前缀）
    - ``YYYY-MM-DD-<name>-<n>``（冲突后缀，剥前缀+剥后缀）
    - ``<name>-<epoch>``（非标准形态，剥后缀）
    归一化 = 依次剥掉可选日期前缀与可选数字后缀后的若干候选形态（含原样），
    供全等比较。
    """
    candidates = {dirname}
    stripped_prefix = _DATE_PREFIX_RE.sub("", dirname, count=1)
    if stripped_prefix != dirname:
        candidates.add(stripped_prefix)
    stripped_suffix = _NUM_SUFFIX_RE.sub("", dirname, count=1)
    if stripped_suffix != dirname:
        candidates.add(stripped_suffix)
    stripped_both = _DATE_PREFIX_RE.sub("", _NUM_SUFFIX_RE.sub("", dirname, count=1), count=1)
    if stripped_both != dirname:
        candidates.add(stripped_both)
    return list(candidates)


def resolve_accepted_spec_dir(project_root, spec_name: str) -> Optional[Path]:
    """以条目记录中 ``spec_name`` 为权威名解析 SPEC 当前位置（D5）。

    1. ``spec_name`` 不满足 ``_KEBAB_RE``（含 ``..``/``/`` 穿越）→ 返回
       ``None``；
    2. ``spec/changes/<spec_name>/`` 是目录 → 返回（活跃优先）；
    3. 否则遍历 ``spec/archive/``，对每个目录名生成归一化候选集并判定
       ``spec_name`` **全等**比较，命中多个取 ``sorted()[-1]``；
    4. 无命中返回 ``None``。

    **MUST NOT 使用前缀匹配**：本仓库存在互为前缀的 spec 名
    （``evo-add-fast-track-scale-precheck`` 与
    ``evo-add-fast-track-scale-precheck-4afdbe``），前缀匹配会把后者的
    目录误归属给前者。

    不改动既有 ``resolve_spec_dir`` 语义：该函数按设计排除无日期前缀的
    软删除命名（服务于 STATE.md 无条目的场景），与本函数的 ``spec_name``
    权威入口前提不同。
    """
    if not isinstance(spec_name, str) or not _KEBAB_RE.match(spec_name):
        return None
    proot = Path(project_root)

    # 2. 活跃目录优先
    active = proot / "spec" / "changes" / spec_name
    if active.is_dir():
        return active

    # 3. spec/archive/ 遍历（全等比较，多个取 sorted 最后）
    archive_root = proot / "spec" / "archive"
    if not archive_root.is_dir():
        return None
    # 目录名与 spec_name 全等的候选优先：合法 spec 名本身允许数字结尾，
    # 归档名剥数字后缀可能把独立 spec（如 ``evo-foo`` 与 ``evo-foo-2`` 并存）
    # 误判命中，sorted 兜底会解析到错误目录。
    exact = archive_root / spec_name
    if exact.is_dir():
        return exact
    hits: List[Path] = []
    try:
        for child in archive_root.iterdir():
            if not child.is_dir():
                continue
            candidates = _archive_name_candidates(child.name)
            if spec_name in candidates:
                hits.append(child)
    except OSError:
        return None
    if not hits:
        return None
    # 归一化命中多个取 sorted()[-1]（目录名字典序）
    return sorted(hits)[-1]


# ── 任务 3.7：自动接受 ─────────────────────────────────────────────


def auto_accept_pending(project_root, state_machine, spec_run_at=None) -> dict:
    """对全部 ``pending`` 条目逐个走接受路径（``decided_by="auto"``，3.7）。

    逐条独立捕获异常：单条失败置 ``accept_failed`` 并写告警，不影响其余。
    MUST NOT 触碰 ``analyzed`` / ``draft_failed`` / 已决定条目。

    ``spec_run_at``：``self_evolution.spec_run_at`` 配置原值（"HH:mm" 或 None），
    经 ``next_spec_run_at`` 换算为 UTC ISO 的 ``start_after``。同一批条目共用
    一次换算结果——它们是同一次巡检同时立项的，排到同一时刻才对得上「每日该
    时刻执行」的语义。None = 立项后立即执行。

    Returns: 汇总 ``{"total", "accepted", "failed", "details"}``。
    """
    items = read_items(project_root)
    pending = [rec for rec in items.values() if rec.get("status") == "pending"]
    start_after = next_spec_run_at(spec_run_at)
    summary = {"total": len(pending), "accepted": 0, "failed": 0, "details": []}
    for rec in pending:
        try:
            result = accept_item(
                rec["id"], project_root, state_machine, decided_by="auto", start_after=start_after
            )
        except Exception as e:
            _logger.error("evolution: 自动接受条目 %s 异常: %s", rec["id"], e)
            _write_admin_warning(project_root, f"自进化条目 {rec['id']} 自动接受异常: {e}")
            summary["failed"] += 1
            summary["details"].append({"id": rec["id"], "ok": False, "error": str(e)})
            continue
        if result.get("ok"):
            summary["accepted"] += 1
        else:
            summary["failed"] += 1
        summary["details"].append(
            {
                "id": rec["id"],
                "ok": result.get("ok"),
                "status": result.get("status"),
                "spec_name": result.get("spec_name"),
                "error": result.get("error"),
            }
        )
    return summary


# ── 任务 3.8：契约产物解析 ─────────────────────────────────────────


class ContractError(ValueError):
    """分析 run 契约产物不合法（调用方判整轮失败，3.8）。"""


def read_contract(path) -> Dict[str, Any]:
    """解析分析 run 契约产物 JSON（3.8）。

    任一不满足 MUST 抛 ``ContractError`` 判整轮失败（不产生任何条目）：
    - 文件存在（缺失报「产物文件未写出」）且 JSON 可解析（非法报
      「产物 JSON 不可解析」，两者可判别归因）；
    - JSON 可解析且为 dict；
    - 含 ``items`` 数组；
    - 每条含 ``project`` / ``date_section`` / ``title`` / ``verdict``(dict)
      且 ``section`` ∈ {浪费, 失误, 可改进}；
    - ``id`` 若提供必须为字符串（缺失回落 ``item_id`` 复算）。非字符串真值
      id 直达 ``upsert_item`` 会使 ``sorted()`` 混排 str/int 键抛 TypeError，
      该条目每轮复现同一异常成永久阻塞（code-review item a29d89428f7f），
      故在契约层整轮拒绝。

    解析成功后由调用方删除产物文件。返回 {"run_id", "degraded", "items"}。
    """
    # 失败归因分级（evo-add-evolution-product-salvage）：「产物文件未写出」
    # 与「产物 JSON 不可解析」拆成两个可判别的 ContractError 文案——告警与
    # 日志可直接判别失败面（前者是子代理从未写出/被清理，后者是半写截断
    # 或内容损坏，处置不同）。
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ContractError(f"产物文件未写出: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ContractError(f"产物 JSON 不可解析: {e}") from e
    if not isinstance(data, dict):
        raise ContractError("产物顶层不是对象")
    items = data.get("items")
    if not isinstance(items, list):
        raise ContractError("产物缺 items 数组")
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContractError(f"items[{idx}] 不是对象")
        for field in ("project", "date_section", "title"):
            if not isinstance(item.get(field), str) or not item.get(field):
                raise ContractError(f"items[{idx}] 缺必填字段 {field}")
        if item.get("section") not in TODO_SECTIONS:
            raise ContractError(f"items[{idx}].section 不在三值枚举内: {item.get('section')!r}")
        verdict = item.get("verdict")
        if not isinstance(verdict, dict):
            raise ContractError(f"items[{idx}] 缺 verdict 对象")
        if "worth_spec" not in verdict or not isinstance(verdict.get("worth_spec"), bool):
            raise ContractError(f"items[{idx}].verdict.worth_spec 非法")
        # code-review item a29d89428f7f：缺失/空串回落 item_id 复算；非字符串
        # 真值 id（如数字）会在 upsert_item 锁内 sorted() 混排 str/int 键抛
        # TypeError，条目永久落不了库（调用方逐条跳过 → 每轮重试同一异常）。
        raw_id = item.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            raise ContractError(f"items[{idx}].id 非字符串: {raw_id!r}")
    return {
        "run_id": data.get("run_id"),
        "degraded": data.get("degraded"),
        "items": items,
    }
