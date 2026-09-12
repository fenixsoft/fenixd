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
from datetime import datetime, timezone
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

# 条目四字段标签（与 core/self_review.py:_render_entry_lines 的渲染标签对齐）
_FIELD_LABELS = (("影响", "impact"), ("证据", "evidence"),
                 ("调查评估", "analysis"), ("建议", "suggestion"))
_FIELD_RE = re.compile(r"^ {2,}-\s+([^：]+)：(.*)$")

# SPEC 名 / capability 合法性（fenix-new 同源正则）
_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# 条目状态枚举（items.jsonl 记录 status 字段取值）
ITEM_STATUSES = ("pending", "analyzed", "draft_failed", "accepted",
                 "auto_accepted", "rejected", "accept_failed")

# 草稿文档文件名（按 fenix-new 流程五件套）
DRAFT_FILES = ("proposal.md", "design.md", "tasks.md", ".spec.yaml")

# .spec.yaml 模板（内容 schema/created/mode 三行）
SPEC_YAML_TEMPLATE = "schema: spec-driven\ncreated: {created}\nmode: full\n"


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
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
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


def read_items(project_root) -> Dict[str, dict]:
    """读取 ``.fenix/evolution/items.jsonl``，按 id 建索引返回 dict。

    文件不存在按空集合处理；单行 JSON 损坏记 WARNING 后跳过（MUST NOT 让
    整个读取失败——dashboard 列表端点依赖此容错）。TODO 2.2。
    """
    path = items_path(project_root)
    out: Dict[str, dict] = {}
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning("evolution: 读取 items.jsonl 失败: %s", e)
        return out
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            _logger.warning(
                "evolution: items.jsonl 第 %s 行 JSON 损坏已跳过: %s", lineno, e)
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            continue
        out[rec["id"]] = rec
    return out


def write_items(project_root, records: Iterable[dict]) -> None:
    """全量写回 items.jsonl（读-改-写 + flock + 原子替换展开见 upsert_items）。

    每条一行 JSON；调用方传入的 records 为 id→记录 dict 或可迭代记录。
    同一 id MUST 只保留一条（dict 天然保证）。
    """
    recs: Dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            continue
        recs[rec["id"]] = rec
    content = "".join(
        json.dumps(recs[k], ensure_ascii=False) + "\n"
        for k in sorted(recs)
    )

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
            json.dumps(current[k], ensure_ascii=False) + "\n"
            for k in sorted(current)
        )
        _atomic_write(path, content)

    _with_lock(path, _do)


def known_ids(project_root) -> set:
    """items.jsonl 全量 id 集合（去重权威，design D4）。"""
    return set(read_items(project_root).keys())


def _read_items_unlocked(path: Path) -> Dict[str, dict]:
    """锁内使用的 items.jsonl 读取（等价 read_items 但路径直传、不加锁）。"""
    out: Dict[str, dict] = {}
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            _logger.warning(
                "evolution: items.jsonl 第 %s 行 JSON 损坏已跳过", lineno)
            continue
        if isinstance(rec, dict) and isinstance(rec.get("id"), str):
            out[rec["id"]] = rec
    return out


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
            "last_run_id": (wm.get("last_run_id")
                            if isinstance(wm.get("last_run_id"), str) else ""),
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
            "last_run_id": (wm.get("last_run_id") if isinstance(
                wm.get("last_run_id"), str) else ""),
        }
    content = json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n"

    def _do() -> None:
        _atomic_write(path, content)

    _with_lock(path, _do)


def advance_watermark(project_root, project: str,
                      snapshot_at: str, run_id: str) -> None:
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
                    if isinstance(wm, dict) and isinstance(
                            wm.get("last_analyzed_at"), str):
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
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(timezone.utc)


# ── 任务 2.4：就绪扫描 ──────────────────────────────────────────────

def scan_ready_projects(registry_projects, project_root) -> List[dict]:
    """按 registry 项目逐判定就绪，返回就绪项目 [{name, path, todo_md}]。

    就绪判定（spec「自进化触发与就绪扫描」）：
    - ``<proj>/.fenix/self_review_state.json`` 缺失 → 不就绪；
    - ``last_run_at`` 不可解析 → 不就绪（记 DEBUG/INFO，MUST NOT 告警）；
    - ``last_run_at`` 不晚于该项目水位 ``last_analyzed_at`` → 不就绪
      （无水位记录视为从未分析：last_run_at 存在即就绪）；
    - ``<proj>/.fenix/todo.md`` 不存在或去空白后为空 → 不就绪；
    - 其余 → 就绪。

    registry 读取失败/项目路径不可访问 MUST 抛给调用方（检查点统一捕获），
    不在本函数静默吞掉。就绪项目 MUST 携带 todo_md 全文（同轮一个 claude
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
        if not state_file.is_file():
            _logger.debug(
                "evolution: 项目 %s 无 self_review_state.json，不就绪", name)
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            _logger.info(
                "evolution: 项目 %s 的 self_review_state.json 不可读（不就绪）: %s",
                name, e)
            continue
        if not isinstance(state, dict):
            continue
        last_run_at = _parse_iso(state.get("last_run_at"))
        if last_run_at is None:
            _logger.debug(
                "evolution: 项目 %s 的 last_run_at 缺失或不可解析，不就绪", name)
            continue

        wm = watermarks.get(name)
        if wm:
            last_analyzed = _parse_iso(wm.get("last_analyzed_at"))
            if last_analyzed is not None and last_run_at <= last_analyzed:
                _logger.debug(
                    "evolution: 项目 %s 的 last_run_at 不晚于水位，不就绪", name)
                continue

        todo = proot / ".fenix" / "todo.md"
        if not todo.is_file():
            _logger.debug("evolution: 项目 %s 无 todo.md，不就绪", name)
            continue
        try:
            todo_text = todo.read_text(encoding="utf-8")
        except OSError as e:
            _logger.info(
                "evolution: 项目 %s 的 todo.md 不可读（不就绪）: %s", name, e)
            continue
        if not todo_text.strip():
            _logger.debug("evolution: 项目 %s 的 todo.md 为空，不就绪", name)
            continue
        ready.append({"name": name, "path": str(proot), "todo_md": todo_text})
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
            # 小节名不在三值枚举内的条目 MUST 跳过（含未知小节置空的条目）
            if current_entry.get("section") in TODO_SECTIONS \
                    and current_entry.get("title"):
                current_entry.update(current_fields)
                entries.append(current_entry)
        current_entry = None
        current_fields = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        line = raw_line

        m = _TODO_DATE_RE.match(line)
        if m:
            _flush_entry()
            date_section = m.group(1)
            current_section = ""
            continue

        m = _TODO_SECTION_RE.match(line)
        if m:
            _flush_entry()
            section_name = m.group(1).strip()
            if section_name not in TODO_SECTIONS:
                if section_name not in _section_warned:
                    _logger.warning(
                        "evolution: todo.md 小节 %r 不在三值枚举 %s 内，"
                        "其下条目跳过", section_name, list(TODO_SECTIONS))
                    _section_warned.add(section_name)
                current_section = ""
            else:
                current_section = section_name
            continue

        # 条目标题行：- **<标题>**
        m = _TODO_ENTRY_RE.match(line)
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
        stripped = line.strip()
        if stripped.startswith("-") and _EMPTY_MARKER in stripped:
            continue

        if current_entry is None:
            # 无法归类（可能在条目块外）→ 跳过
            continue

        # 四字段嵌套行：  - 影响：…
        m = _FIELD_RE.match(line)
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
        if line.startswith((" ", "\t")) and current_fields:
            last_key = list(current_fields.keys())[-1]
            if stripped and not stripped.startswith("-"):
                current_fields[last_key] += f"\n{stripped}"
            continue

    _flush_entry()
    return entries


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
        return None, (
            f"spec.capability 非法（应满足 {_KEBAB_RE.pattern}）: {capability!r}")
    missing = [doc for doc in ("proposal_md", "design_md", "spec_md", "tasks_md")
               if not isinstance(spec.get(doc), str) or not spec.get(doc)]
    if missing:
        return None, f"spec 内容缺必备文档: {', '.join(missing)}"

    eid = item.get("id") or item_id(
        str(item.get("project", "")), str(item.get("date_section", "")),
        str(item.get("section", "")), str(item.get("title", "")))
    d = draft_dir(project_root, eid)
    try:
        d.mkdir(parents=True, exist_ok=True)
        spec_sub = d / "specs" / capability
        spec_sub.mkdir(parents=True, exist_ok=True)
        (d / "proposal.md").write_text(spec["proposal_md"], encoding="utf-8")
        (spec_sub / "spec.md").write_text(spec["spec_md"], encoding="utf-8")
        (d / "design.md").write_text(spec["design_md"], encoding="utf-8")
        (d / "tasks.md").write_text(spec["tasks_md"], encoding="utf-8")
        (d / ".spec.yaml").write_text(
            SPEC_YAML_TEMPLATE.format(
                created=datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            encoding="utf-8")
    except OSError as e:
        shutil.rmtree(d, ignore_errors=True)
        return None, f"草稿落盘失败: {e}"
    return d, ""


def _spec_summary(spec: dict) -> str:
    """agent 原始 spec 内容摘要（供 draft_failed 条目记录，3.3）。"""
    if not isinstance(spec, dict):
        return ""
    return json.dumps({
        "name": spec.get("name"),
        "capability": spec.get("capability"),
        "proposal_len": len(str(spec.get("proposal_md") or "")),
        "spec_len": len(str(spec.get("spec_md") or "")),
        "design_len": len(str(spec.get("design_md") or "")),
        "tasks_len": len(str(spec.get("tasks_md") or "")),
    }, ensure_ascii=False)


# ── 任务 3.2：同源 lint 预检 ────────────────────────────────────────

def lint_draft(draft_dir_: Path, project_root) -> List[str]:
    """对草稿目录执行与 daemon 晋升同源的 lint 预检（3.2）。

    ``sys.path`` 指向项目 ``.fenix/`` 后调用 ``core.deliverables.lint_declared``
    与 ``core.deliverables.lint_tasks_parseable``（与 fenixd.py 启动时同款
    sys.path 注入），返回合并后的 violation 清单。MUST NOT 自实现第二套声明
    解析。lint 自身故障 fail-open（记 WARNING 返回空清单，不阻塞）。
    """
    proot = Path(project_root)
    fenix_dir = proot / ".fenix"
    if str(fenix_dir) not in sys.path:
        sys.path.insert(0, str(fenix_dir))
    from core.deliverables import lint_declared, lint_tasks_parseable

    violations: List[str] = []
    for fn in (lint_declared, lint_tasks_parseable):
        try:
            violations.extend(fn(draft_dir_, proot) or [])
        except Exception as e:
            _logger.warning("evolution: 草稿 lint 异常（非阻塞放行）: %s", e)
    return violations


# ── 任务 3.3：落地单条复核结果 ─────────────────────────────────────

def ingest_item(item: dict, project_root) -> str:
    """落地单条复核结果到 items.jsonl，返回条目状态（3.3）。

    - ``verdict.worth_spec`` 非真 → 入库置 ``analyzed``（不建草稿目录）；
    - 为真 → 落盘 → lint → 有 violation/内容缺失则删除草稿目录、置
      ``draft_failed`` 并记录 violation 原文与 spec 摘要；通过置 ``pending``。

    写入条目 MUST 保留 todo.md 原文四字段（impact/evidence/analysis/suggestion）。
    """
    verdict = item.get("verdict") if isinstance(item, dict) else None
    worth_spec = bool(isinstance(verdict, dict) and verdict.get("worth_spec"))
    title = str(item.get("title", ""))
    eid = item.get("id") or item_id(
        str(item.get("project", "")), str(item.get("date_section", "")),
        str(item.get("section", "")), title)

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
            item.get("spec") if isinstance(item.get("spec"), dict) else None),
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
        return "analyzed"

    d, reason = materialize_draft(base, project_root)
    if d is None:
        base["status"] = "draft_failed"
        base["draft_failed_reason"] = reason
        _logger.warning("evolution: 条目 %s 草稿落盘失败: %s", eid, reason)
        upsert_item(project_root, base)
        return "draft_failed"

    violations = lint_draft(d, project_root)
    if violations:
        shutil.rmtree(d, ignore_errors=True)
        base["status"] = "draft_failed"
        base["violations"] = violations
        base["draft_failed_reason"] = "；".join(violations)
        _logger.warning(
            "evolution: 条目 %s 草稿 lint 未通过（已删除草稿）: %s",
            eid, base["draft_failed_reason"])
        upsert_item(project_root, base)
        return "draft_failed"

    base["status"] = "pending"
    upsert_item(project_root, base)
    return "pending"


# ── 任务 3.4：SPEC 名生成与冲突消解 ────────────────────────────────

def resolve_spec_name(name: str, item_id_: str, project_root,
                      state_machine) -> Optional[str]:
    """生成并消解接受路径的 SPEC 名（3.4）。

    基名 ``evo-<name>``；与 ``spec/changes/<candidate>``、STATE.md 既有条目名、
    ``spec/archive/*-<candidate>``（名字 == candidate 或 endswith
    ``-<candidate>``）任一冲突时追加 ``-<item_id 前 6 位>`` 并重新校验全部
    三处；仍冲突返回 None（调用方置 draft_failed 并告警）。``name`` 非法
    （非 kebab-case）直接返回 None。
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
            _logger.warning("evolution: 读取 STATE 判定重名失败: %s", e)
        arch_root = proot / "spec" / "archive"
        if arch_root.is_dir():
            try:
                for archived in arch_root.iterdir():
                    if not archived.is_dir():
                        continue
                    if archived.name == candidate \
                            or archived.name.endswith(f"-{candidate}"):
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

def _git_commit(project_root, draft_copy: Path, spec_name: str) -> Tuple[bool, str]:
    """仅 add 目标 spec 目录后提交（MUST NOT ``git add -A`` / ``git add .``）。

    Returns: ``(ok, error)``；ok=False 时调用方负责清理未跟踪副本。
    """
    git = ["git", "-C", str(project_root)]
    try:
        add = subprocess.run(
            git + ["add", "--", f"spec/changes/{spec_name}"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git add 失败: {e}"
    if add.returncode != 0:
        return False, f"git add 失败: {add.stderr.strip()[:300]}"
    try:
        commit = subprocess.run(
            git + ["commit", "-m", f"[fenix] spec: {spec_name}"],
            capture_output=True, text=True, timeout=60)
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
        from core.admin_store import AdminStore
        store = AdminStore(project_root)
        store.append({
            "kind": "escalation",
            "severity": "major",
            "signal_type": "self-evolution",
            "spec": None,
            "description": message,
        })
    except Exception as e:
        _logger.warning("evolution: admin 告警写入失败（降级）: %s", e)


def accept_item(item_id_: str, project_root, state_machine,
                decided_by: str = "manual") -> dict:
    """接受路径（人工同意与自动接受共用实现，design D6；3.5）。

    顺序固定：前置状态校验 → resolve_spec_name → 复制到 spec/changes →
    仅 add 该目录并提交 → add_spec(drafted, priority=5) → 删暂存草稿 →
    标 accepted/auto_accepted。失败分支：
    - 提交失败 → 删除 spec/changes 副本（避免主树未跟踪文件）、保留暂存
      草稿、置 accept_failed + 告警；
    - 注册失败 → 保留暂存草稿、置 accept_failed + 告警。

    Returns: ``{"ok", "status", "spec_name", "error"}``；非 pending /
    accept_failed 状态幂等返回现状（不重复提交或注册）。
    """
    now = datetime.now(timezone.utc).isoformat()
    items = read_items(project_root)
    rec = items.get(item_id_)
    if rec is None:
        return {"ok": False, "status": None, "spec_name": None,
                "error": f"条目不存在: {item_id_}"}
    if rec.get("status") not in ("pending", "accept_failed"):
        # 其它状态幂等返回现状（accepted/auto_accepted/rejected/analyzed/
        # draft_failed 均不重复提交或注册）
        return {"ok": True, "status": rec.get("status"),
                "spec_name": rec.get("spec_name"), "error": None}

    spec = rec.get("spec") if isinstance(rec.get("spec"), dict) else None
    if spec is None:
        rec["status"] = "draft_failed"
        rec["draft_failed_reason"] = "条目无 spec 内容，无法接受"
        upsert_item(project_root, rec)
        return {"ok": False, "status": "draft_failed",
                "spec_name": None, "error": rec["draft_failed_reason"]}
    name = resolve_spec_name(spec.get("name"), item_id_, project_root,
                             state_machine)
    if name is None:
        rec["status"] = "draft_failed"
        rec["draft_failed_reason"] = "SPEC 名无法消解冲突"
        upsert_item(project_root, rec)
        _write_admin_warning(
            project_root,
            f"自进化条目 {item_id_} 接受失败：SPEC 名冲突无法消解")
        return {"ok": False, "status": "draft_failed",
                "spec_name": None, "error": rec["draft_failed_reason"]}

    src = draft_dir(project_root, item_id_)
    dest = Path(project_root) / "spec" / "changes" / name
    if dest.exists():
        # 同名目录已被他人/重试创建：清掉再复制，防残留污染
        shutil.rmtree(dest, ignore_errors=True)
    try:
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            rec["status"] = "accept_failed"
            rec["draft_failed_reason"] = "暂存草稿目录缺失"
            upsert_item(project_root, rec)
            _write_admin_warning(
                project_root,
                f"自进化条目 {item_id_} 接受失败：暂存草稿目录缺失")
            return {"ok": False, "status": "accept_failed",
                    "spec_name": None, "error": rec["draft_failed_reason"]}
    except OSError as e:
        rec["status"] = "accept_failed"
        rec["draft_failed_reason"] = f"草稿复制失败: {e}"
        upsert_item(project_root, rec)
        _write_admin_warning(
            project_root, f"自进化条目 {item_id_} 接受失败：{e}")
        return {"ok": False, "status": "accept_failed",
                "spec_name": None, "error": rec["draft_failed_reason"]}

    ok, err = _git_commit(project_root, dest, name)
    if not ok:
        # 提交失败：删除副本（主树无未跟踪文件），保留暂存草稿可重试
        shutil.rmtree(dest, ignore_errors=True)
        rec["status"] = "accept_failed"
        rec["draft_failed_reason"] = err
        upsert_item(project_root, rec)
        _write_admin_warning(project_root,
                             f"自进化条目 {item_id_} 接受失败（提交失败）: {err}")
        return {"ok": False, "status": "accept_failed",
                "spec_name": name, "error": err}

    # 提交成功 → 注册（MUST NOT 写 start_after，drafted 立即进入调度）
    registered = False
    try:
        if state_machine is not None:
            registered = state_machine.add_spec(
                name, {"status": "drafted", "priority": 5})
        else:
            registered = True  # state_machine 缺失（如纯路径测试）视为注册成功
    except Exception as e:
        _logger.warning(
            "evolution: 条目 %s 注册 %s 失败: %s", item_id_, name, e)
        registered = False
        err = str(e)

    if not registered:
        rec["status"] = "accept_failed"
        rec["draft_failed_reason"] = err or "STATE 注册失败"
        rec["spec_name"] = name
        upsert_item(project_root, rec)
        _write_admin_warning(
            project_root,
            f"自进化条目 {item_id_} 接受失败（注册失败）: {rec['draft_failed_reason']}")
        return {"ok": False, "status": "accept_failed",
                "spec_name": name, "error": rec["draft_failed_reason"]}

    # 注册成功 → 删暂存草稿 + 更新状态
    shutil.rmtree(src, ignore_errors=True)
    rec["status"] = "auto_accepted" if decided_by == "auto" else "accepted"
    rec["decided_by"] = decided_by
    rec["decided_at"] = now
    rec["spec_name"] = name
    upsert_item(project_root, rec)
    return {"ok": True, "status": rec["status"], "spec_name": name,
            "error": None}


# ── 任务 3.6：拒绝路径 ─────────────────────────────────────────────

def _safe_draft_dir(project_root, item_id_: str) -> Optional[Path]:
    """解析草稿目录并校验其位于 drafts 基目录之内（符号链接越界拒绝）。

    item_id 含路径分隔符或 ``..``，或 resolve() 后不在 drafts 基目录内 →
    返回 None（调用方报错且不删除任何文件）。3.6
    """
    if not item_id_ or item_id_ in (".", "..") \
            or "/" in item_id_ or "\\" in item_id_ or "\x00" in item_id_:
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
    """
    now = datetime.now(timezone.utc).isoformat()
    items = read_items(project_root)
    rec = items.get(item_id_)
    if rec is None:
        return {"ok": False, "status": None,
                "error": f"条目不存在: {item_id_}"}
    status = rec.get("status")
    if status not in ("pending", "draft_failed", "accept_failed"):
        return {"ok": False, "status": status,
                "error": f"状态 {status} 不可拒绝（已决定条目不可拒绝）"}

    target = _safe_draft_dir(project_root, item_id_)
    if target is None:
        return {"ok": False, "status": status,
                "error": "草稿目录路径非法或越界，拒绝删除"}
    if target.is_dir():
        try:
            # 符号链接解析后的越界判定：链接目标不在基目录内 → 拒绝删除
            resolved = target.resolve()
            base = (evolution_dir(project_root) / "drafts").resolve()
            if not resolved.is_relative_to(base):
                return {"ok": False, "status": status,
                        "error": "草稿目录符号链接越界，拒绝删除"}
            shutil.rmtree(target)
        except OSError as e:
            return {"ok": False, "status": status,
                    "error": f"草稿删除失败: {e}"}

    rec["status"] = "rejected"
    rec["decided_at"] = now
    upsert_item(project_root, rec)
    return {"ok": True, "status": "rejected", "error": None}


# ── 任务 3.7：自动接受 ─────────────────────────────────────────────

def auto_accept_pending(project_root, state_machine) -> dict:
    """对全部 ``pending`` 条目逐个走接受路径（``decided_by="auto"``，3.7）。

    逐条独立捕获异常：单条失败置 ``accept_failed`` 并写告警，不影响其余。
    MUST NOT 触碰 ``analyzed`` / ``draft_failed`` / 已决定条目。

    Returns: 汇总 ``{"total", "accepted", "failed", "details"}``。
    """
    items = read_items(project_root)
    pending = [rec for rec in items.values()
               if rec.get("status") == "pending"]
    summary = {"total": len(pending), "accepted": 0, "failed": 0,
               "details": []}
    for rec in pending:
        try:
            result = accept_item(rec["id"], project_root, state_machine,
                                 decided_by="auto")
        except Exception as e:
            _logger.error("evolution: 自动接受条目 %s 异常: %s", rec["id"], e)
            _write_admin_warning(
                project_root,
                f"自进化条目 {rec['id']} 自动接受异常: {e}")
            summary["failed"] += 1
            summary["details"].append(
                {"id": rec["id"], "ok": False, "error": str(e)})
            continue
        if result.get("ok"):
            summary["accepted"] += 1
        else:
            summary["failed"] += 1
        summary["details"].append({
            "id": rec["id"], "ok": result.get("ok"),
            "status": result.get("status"), "spec_name": result.get("spec_name"),
            "error": result.get("error"),
        })
    return summary


# ── 任务 3.8：契约产物解析 ─────────────────────────────────────────

class ContractError(ValueError):
    """分析 run 契约产物不合法（调用方判整轮失败，3.8）。"""


def read_contract(path) -> Dict[str, Any]:
    """解析分析 run 契约产物 JSON（3.8）。

    任一不满足 MUST 抛 ``ContractError`` 判整轮失败（不产生任何条目）：
    - JSON 可解析且为 dict；
    - 含 ``items`` 数组；
    - 每条含 ``project`` / ``date_section`` / ``title`` / ``verdict``(dict)
      且 ``section`` ∈ {浪费, 失误, 可改进}。

    解析成功后由调用方删除产物文件。返回 {"run_id", "degraded", "items"}。
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ContractError(f"产物 JSON 不可读/非法: {e}") from e
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
            raise ContractError(
                f"items[{idx}].section 不在三值枚举内: {item.get('section')!r}")
        verdict = item.get("verdict")
        if not isinstance(verdict, dict):
            raise ContractError(f"items[{idx}] 缺 verdict 对象")
        if "worth_spec" not in verdict or not isinstance(
                verdict.get("worth_spec"), bool):
            raise ContractError(f"items[{idx}].verdict.worth_spec 非法")
    return {
        "run_id": data.get("run_id"),
        "degraded": data.get("degraded"),
        "items": items,
    }