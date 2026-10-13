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

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core import fs_utils
from core import timelib
from core.fs_utils import with_file_lock as _with_lock  # 锁原语公共归属 fs_utils（item 1a8a9328767b），别名保留内部调用面
# todo.md 结构契约单源（code-review item 8455037f0c1f）：日期/小节标题正则、
# 空小节占位、条目四字段标签统一从 core/todo_format.py 别名导入，本模块
# （解析方）与 core/self_review.py（写入方）同源引用，MUST NOT 另立同值副本。
from core.todo_format import (
    EMPTY_MARKER as _EMPTY_MARKER,
    FIELD_LABELS as _FIELD_LABELS,
    TODO_DATE_RE as _TODO_DATE_RE,
    TODO_SECTION_RE as _TODO_SECTION_RE,
)

_logger = logging.getLogger("fenixd.evolution")

# ── 结构与常量 ──────────────────────────────────────────────────────

# todo.md 小节枚举（与 core/self_review.py 渲染的三小节一一对应）
TODO_SECTIONS = ("浪费", "失误", "可改进")

# 未知小节 WARNING 去重集（进程生命周期每节一次，code-review item
# 437681e0e485）：parse_todo_entries 在就绪巡检热路径上被高频调用，函数局部
# 去重每次调用重建，todo.md 持续存在非法小节时会周期性刷屏；对齐
# core/config.py:_UNKNOWN_AGENT_MODEL_KEYS_WARNED 的模块级生命周期去重范式。
_UNKNOWN_TODO_SECTIONS_WARNED: set = set()

# 孤立处理标记行 WARNING 去重集（进程生命周期每行文本一次，code-review item
# e113b2af9b63）：parse_todo_entries / strip_processed_entries 同在就绪巡检
# 热路径上被高频调用，todo.md 残留孤立标记行时会周期性刷屏；对齐上方
# _UNKNOWN_TODO_SECTIONS_WARNED 的模块级生命周期去重范式。
_ORPHAN_TODO_MARKERS_WARNED: set = set()

# todo.md 结构标题正则：- **标题** 条目（本模块独有；日期/小节正则与空小节
# 占位单源自 core/todo_format.py，经顶部别名导入——code-review item
# 8455037f0c1f，MUST NOT 在本模块另立同值副本）
_TODO_ENTRY_RE = re.compile(r"^-\s+\*\*(.+?)\*\*\s*$")

# 处理标记行（自进化回写）：写在条目标题行正下方的一行人可读记录——
#   - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否
# 「— 不需要」的条目只写前三段（无处理/删除段）。带该行的条目视为已处理：
# 解析时整条跳过，且分析 run 拿到的 todo 文本里也不含它们（避免重复处理）。
TODO_MARKER_KEY = "自进化"
_TODO_MARKER_RE = re.compile(r"^ {2,}-\s*" + TODO_MARKER_KEY + "：")
_TODO_MARKER_INDENT = "  - "

# 条目四字段标签单源自 core/todo_format.py（顶部别名导入 _FIELD_LABELS，与
# core/self_review.py:_render_entry_lines 的渲染标签同源——code-review item
# 8455037f0c1f）。
# 标签集合/映射的模块级预计算（code-review item 31af97a4ec41）：
# parse_todo_entries 在就绪巡检热路径上逐条候选字段行引用，_FIELD_LABELS 是
# 模块级不可变常量，循环内重复推导集合/构建字典纯属浪费。
_FIELD_LABEL_SET = frozenset(label for label, _k in _FIELD_LABELS)
_FIELD_LABEL_MAP = dict(_FIELD_LABELS)
_FIELD_RE = re.compile(r"^ {2,}-\s+([^：]+)：(.*)$")

# SPEC 名 / capability 合法性（fenix-new 同源正则）。结尾锚用 \Z 而非 $：
# Python 的 $ 亦匹配串尾换行符之前，$ 会放行带尾部换行的 name/capability
# （agent 产出 JSON 携带 \n），进而以带换行的目录名落盘、以 ``evo-<name>\n``
# 注册进 STATE（code-review item bd2227732d7e）。
_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")

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
        # errors="replace"：坏 UTF-8 字节降级为替换符、由逐行 JSON 解析自然
        # 兜底，否则 UnicodeDecodeError 会从全部读写路径穿透（365a1932a94c）
        text = path.read_text(encoding="utf-8", errors="replace")
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

    path = items_path(project_root)

    def _do() -> None:
        # 序列化口径（id 升序排序键、json.dumps 参数、逐条一行加换行）收口到
        # _write_items_unlocked 单点定义，不再内联重复——否则改落盘格式需两处
        # 同步，漏改其一即锁内/锁外写出口径分叉；本函数不加锁，锁语义仍由
        # 外层 _with_lock 表达。
        _write_items_unlocked(path, recs)

    _with_lock(path, _do)


def upsert_item(project_root, record: dict) -> None:
    """写回单条条目记录（读-改-写，锁内原子；同 id 更新而非追加）。

    design「daemon 与 Dashboard 同时写同一存储」缓解：flock + tempfile +
    rename 原子替换，单条更新粒度小、无长事务。MUST NOT 在锁内二次加锁。
    """
    rec = dict(record)
    # code-review item a820db66d8fa：入参契约快速失败（与 write_items 同风格）
    # ——记录缺字符串 id 时以裸 KeyError 从 _with_lock 穿透给调用方，难定位。
    if not isinstance(rec.get("id"), str):
        raise TypeError("upsert_item 期望含字符串 id 字段的单条记录，记录缺 id 无法定位写回键")
    path = items_path(project_root)

    def _do() -> None:
        current = _read_items_unlocked(path)
        current[rec["id"]] = rec
        _write_items_unlocked(path, current)

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
        # errors="replace"：与 read_items 同参（365a1932a94c），坏 UTF-8 字节
        # 降级为替换符、由 _parse_items_text 逐行 JSON 解析自然兜底——否则
        # UnicodeDecodeError 会从 accept_item/reject_item/delete_item/upsert_item
        # 的锁内路径穿透（非 OSError、不在捕获列表内），与「单行 JSON 损坏
        # 记 WARNING 后跳过」的容错口径不一致。
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return _parse_items_text(text)


def _write_items_unlocked(path: Path, records: Dict[str, dict]) -> None:
    """锁内使用的 items.jsonl 全量写回（读-改-写的写侧收口，与
    _read_items_unlocked 同范式；code-review item 8aa4ff6154be）。

    序列化口径（id 升序排序键、json.dumps 参数、逐条一行 + 换行）与
    write_items/upsert_item 现状逐字一致，MUST NOT 改变落盘格式；锁语义仍由
    调用方的外层 _with_lock 表达——本函数 MUST NOT 加锁。已在锁内的路径
    （upsert_item/accept_item._persist/reject_item/delete_item）MUST NOT 直接
    走 upsert_item/read_items 写回：同进程对同一把 ``.items.jsonl.lock`` 二次
    flock 会自阻塞（见 _with_lock），统一收口到本函数后序列化口径单点化，
    改口径不再四处同步。
    """
    content = "".join(json.dumps(records[k], ensure_ascii=False) + "\n" for k in sorted(records))
    fs_utils.atomic_write_text(path, content)


# ── 任务 2.3：水位 state.json 读写 ──────────────────────────────────


def watermarks_path(project_root) -> Path:
    return evolution_dir(project_root) / "state.json"


def _normalize_watermarks(data: Any) -> Dict[str, dict]:
    """水位字段校验/归一化单点收口，``read_watermarks`` / ``write_watermarks``
    共用同一口径（读写往返数据不得分叉，item bd65361dc103）。

    逐项目校验：``wm`` 非 dict 跳过、``last_analyzed_at`` 须非空字符串、
    ``last_run_id`` 非字符串兜底空串；顶层非 dict 返回空 dict。
    """
    out: Dict[str, dict] = {}
    if not isinstance(data, dict):
        return out
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
    return _normalize_watermarks(data)


def write_watermarks(project_root, data: Dict[str, dict]) -> None:
    """全量写回水位 state.json（flock + 原子替换）。"""
    path = watermarks_path(project_root)
    cleaned = _normalize_watermarks(data)
    content = json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n"

    def _do() -> None:
        fs_utils.atomic_write_text(path, content)

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
        fs_utils.atomic_write_text(path, content)

    _with_lock(path, _do)


def _parse_iso(value: str) -> Optional[datetime]:
    """ISO8601 时间解析为时区感知 UTC；失败返回 None（按未就绪/从未分析处理）。

    解析内核收拢至 timelib.parse_ts（add-timelib-consolidation-layer 3.5）：
    naive（无时区）输入按本地时区解读（timelib 唯一策略；原「附本地 tzinfo
    再转 UTC」内联实现删除，语义不变——self_review 写
    ``datetime.now().isoformat()`` 即本地 naive），统一折算 UTC，保证与
    水位（UTC aware）可比。结尾 ``Z`` 后缀同口径归一（Python 3.10 的
    fromisoformat 不认 Z，code-review item 8f824069987d）。
    """
    dt = timelib.parse_ts(value)
    if dt is None:
        return None
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
    抛出」契约收窄为留痕）。就绪项目 MUST 携带剥离已处理条目后的 todo.md 可
    用文本（usable_text，不含已处理条目；同轮一个 claude 进程拿到多份
    todo.md）。
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
            # errors="replace"：坏 UTF-8 字节降级为替换符、由 json.loads 自然判
            # 失败走下方 INFO 跳过分支——UnicodeDecodeError 非 OSError、不在捕获
            # 列表内，裸穿透会中断整轮扫描（与 items.jsonl/todo.md 同口径，
            # code-review 365a1932a94c）
            state = json.loads(state_file.read_text(encoding="utf-8", errors="replace"))
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
            # errors="replace"：坏字节降级为替换符、由条目解析自然兜底，否则
            # UnicodeDecodeError 会穿透 OSError 捕获掀翻整轮就绪扫描
            # （code-review 365a1932a94c）
            todo_text = todo.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            _logger.info("evolution: 项目 %s 的 todo.md 不可读（不就绪）: %s", name, e)
            continue
        if not todo_text.strip():
            _logger.debug("evolution: 项目 %s 的 todo.md 为空，不就绪", name)
            continue
        # 剥离已处理条目（带处理标记）：分析 run 的输入不含它们，避免重复处理；
        # 剥完一条不剩则本项目不就绪，直接省掉整轮分析
        usable_text = strip_processed_entries(todo_text)
        # [fenix-ignore:ceeb35073a06] 此解析兼任「全部已标记则不就绪」非空门控；编排层（fenixd.py）确会二次解析同一文本，但复用需跨模块改 ready 项契约形状（todo_entries 键），单次小文件解析开销不值该扰动
        if not parse_todo_entries(usable_text):
            _logger.debug("evolution: 项目 %s 无未处理的 todo 条目（全部已标记），不就绪", name)
            continue
        ready.append({"name": name, "path": str(proot), "todo_md": usable_text})
    return ready


# ── 任务 2.5：todo.md 条目解析 ──────────────────────────────────────


def _warn_orphan_todo_marker_once(message: str, line_text: str) -> None:
    """孤立处理标记行告警（按行文本进程生命周期去重，热路径防刷屏）。"""
    if line_text in _ORPHAN_TODO_MARKERS_WARNED:
        return
    _ORPHAN_TODO_MARKERS_WARNED.add(line_text)
    _logger.warning(message, line_text)


def parse_todo_entries(text: str) -> List[dict]:
    """解析 todo.md 为条目列表（2.5）。

    结构：``## YYYY-MM-DD`` 切日期节 → ``### 浪费|失误|可改进`` 切小节 →
    ``- **<标题>**`` 起一条并收集其后的 ``  - 影响：…`` 等四字段嵌套行
    （与 core/self_review.py:_render_entry_lines 的渲染格式对齐）。

    - ``- （当日无）`` 占位与无法归类的行 MUST 跳过且不使解析失败；
    - 小节名不在三值枚举内的条目 MUST 跳过并记一次 WARNING（进程生命周期
      内每节一次，见 _UNKNOWN_TODO_SECTIONS_WARNED）。

    Returns: [{date_section, section, title, impact, evidence, analysis,
    suggestion}]（无 project，由调用方注入）。
    """
    entries: List[dict] = []
    date_section = ""
    current_section = ""
    current_entry: Optional[dict] = None
    current_fields: Dict[str, str] = {}

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
                if section_name not in _UNKNOWN_TODO_SECTIONS_WARNED:
                    _logger.warning(
                        "evolution: todo.md 小节 %r 不在三值枚举 %s 内，" "其下条目跳过",
                        section_name,
                        list(TODO_SECTIONS),
                    )
                    _UNKNOWN_TODO_SECTIONS_WARNED.add(section_name)
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

        # 处理标记行：仅在其紧跟条目标题行（该条目尚未收集任何字段）时才
        # 生效——整条标记为已处理（flush 时丢弃）；孤立标记行（其标题行已被
        # 手工删除/改写后残留，含当前无任何条目块的形态）只告警并跳过自身，
        # 不连坐其它条目。告警判断先于 current_entry 空判：条目块外的孤立
        # 标记行同样留痕，与 strip_processed_entries 的告警口径对齐
        # （code-review item faa0eae85057）。
        if _TODO_MARKER_RE.match(raw_line):
            if current_entry is not None and not current_fields:
                current_entry["_processed"] = True
            else:
                _warn_orphan_todo_marker_once(
                    "evolution: todo.md 孤立处理标记行（未紧跟条目标题行），已忽略: %s",
                    stripped,
                )
            continue

        if current_entry is None:
            # 无法归类（可能在条目块外）→ 跳过
            continue

        # 四字段嵌套行：  - 影响：…
        m = _FIELD_RE.match(raw_line)
        if m and m.group(1).strip() in _FIELD_LABEL_SET:
            label = m.group(1).strip()
            key = _FIELD_LABEL_MAP.get(label)
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
        # 既有标记定位与 strip_processed_entries/parse_todo_entries 同口径：
        # 标题行与标记行之间夹的空白行忽略（跳到第一个非空白行再匹配）——
        # 只看紧邻物理行会匹配不到隔空白行的旧标记，每次写入都再插一行新
        # 标记、旧标记沦为孤立标记行，违反上方「原地替换（幂等）」承诺。
        j = i + 1
        while j < len(out) and not out[j].strip():
            j += 1
        if j < len(out) and _TODO_MARKER_RE.match(out[j]):
            out[j] = marker
        else:
            out.insert(i + 1, marker)
        return out
    return None


def _ignorable_before_marker(line: str) -> bool:
    """标记行「紧跟标题行」判定中可忽略的行：空白行与未知标签行。

    与 parse_todo_entries 的 current_fields 收集口径对齐（code-review item
    066161cd80de）：parse 侧未知标签行（_FIELD_RE 命中但标签不在四字段
    集合）不写入 current_fields，其后紧跟的标记行仍判已处理（整条丢弃）；
    strip 侧若把该行当实体行则判孤立、只剔标记整块保留——同一文件形态下
    两侧结论相反，条目继续留在分析输入中被重复分析，apply_marker_to_lines
    原地插新标记后旧标记沦为孤立告警源。四字段行之外，这类行在两侧都不算
    「已收集字段」。
    """
    if not line.strip():
        return True
    fm = _FIELD_RE.match(line)
    return bool(fm and fm.group(1).strip() not in _FIELD_LABEL_SET)


def strip_processed_entries(text: str) -> str:
    """剥离带处理标记的条目整块（标题 + 其缩进行），供分析 run 的输入使用。

    处理标记行仅在其紧跟条目标题行（其间空白行与未知标签行忽略，四字段行
    挡下判定，与 parse_todo_entries 的字段收集口径一致）时才生效：此时整块
    视为已处理并剥离。孤立标记行（其标题行已被手工删除/改写后残留）不连坐
    所在块，仅剔除标记行本身并记 WARNING。
    """
    out: List[str] = []
    block: List[str] = []

    def _flush() -> None:
        # 块首标题行（block[0]）之后按序扫描：遇到处理标记行即整块已处理；
        # 遇到四字段行（非可忽略行）则标记不生效；空白行/未知标签行不阻断
        # 判定（code-review item 066161cd80de，见 _ignorable_before_marker）
        marked = False
        for l in block[1:]:
            if _TODO_MARKER_RE.match(l):
                marked = True
                break
            if not _ignorable_before_marker(l):
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
            # 标记行仅紧跟标题行（其间只夹空白行/未知标签行/既有标记行，与
            # _flush 及 parse_todo_entries 口径一致）才生效；孤立标记行不
            # 连坐所在块，仅剔除标记行本身
            if block and all(
                _TODO_MARKER_RE.match(l) or _ignorable_before_marker(l) for l in block[1:]
            ):
                block.append(line)
            else:
                _warn_orphan_todo_marker_once(
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
        fs_utils.atomic_write_text(todo, "")
        outcome["ok"] = True

    try:
        _with_lock(todo, _do)
    except Exception as e:  # noqa: BLE001 —— 单个项目失败不穿透
        outcome["error"] = str(e)
        _logger.warning("evolution: 清空 todo.md 失败 %s: %s", todo, e)
    return outcome


def write_todo_marker(
    item: dict,
    disposition: Optional[str] = None,
    deleted: bool = False,
    project_path=None,
    commit: bool = True,
) -> bool:
    """把该条目的处理标记写入其项目 ``.fenix/todo.md``。

    幂等：已有标记行则原地更新，不追加第二行。定位不到条目（用户改过标题 /
    删过条目）、项目路径解析失败、todo.md 不可读一律返回 False 并记 WARNING，
    MUST NOT 抛异常——回写是附带的记录动作，失败不得影响分析/处置主流程。

    写入成功后对 tracked 的 todo.md 就地 git add + commit + push（ADR-060
    即时提交原则：tracked 文件的未提交改动滞留主树会触发滞留盘点 major 告警
    并消耗 admin 车道代提交）。``commit=False`` 关闭逐条提交——ingest_item
    批量路径传 False，由编排层批末按项目调用 ``commit_todo_marker`` 合并提交。
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
            # errors="replace"：坏字节降级为替换符，避免 UnicodeDecodeError
            # 穿透（回写失败不得影响主流程，code-review 365a1932a94c）
            text = todo.read_text(encoding="utf-8", errors="replace")
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
        fs_utils.atomic_write_text(todo, "\n".join(lines) + "\n")
        outcome["ok"] = True

    try:
        _with_lock(todo, _do)
    except Exception as e:  # noqa: BLE001 —— 回写失败不穿透
        _logger.warning("evolution: 标记回写异常（已跳过）: %s", e)
    if outcome["ok"] and commit:
        # 提交动作在 todo.md 的 flock 释放后执行：git 子命令不得放入锁内，
        # 避免拉长持锁窗口阻塞 code_fix / self_review 的并发追加。
        commit_todo_marker(project_path=proot)
    return outcome["ok"]


def _git_c_env() -> dict:
    """git 子进程环境：合并 ``os.environ`` 并强制 ``LC_ALL=C``。

    消除 ``_commit_todo_marker`` 良性无变更文案（``nothing to commit`` /
    ``nothing added to commit``）匹配对运行环境本地化的依赖（本地化 git
    环境下输出翻译文案，良性无变更被误记 WARNING；code-review item
    9a333cd43cd0，与 ``deliverables._git_c_env`` 同源手法）。合并而非整体
    替换，保留调用方的 PATH 等既有环境。
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    return env


def _commit_todo_marker(
    proot,
    message_suffix: Optional[str] = None,
    subject: Optional[str] = None,
) -> bool:
    """对项目 ``.fenix/todo.md`` 的标记改动就地 add + commit + push（ADR-060）。

    命令形态与 ``self_review._commit_todo`` 一致（``git add -- .fenix/todo.md``
    与同样带 pathspec 限定的 ``git commit -- .fenix/todo.md``）：commit 不带
    pathspec 会把索引里并发暂存的其他内容（merge-back、交付物守卫等自动化
    产物）卷进本提交并随 push 外泄。git 子命令各 30s 超时。

    ``message_suffix``：非空时作为提交消息正文附在固定主题行之后（空行分隔，
    主题行保持不变）——批末合并提交用其携带本批条目 id 明细（design D3），
    使合并提交的 git 历史仍可对账到逐条条目。

    ``subject``：非空时替换缺省主题行（``[fenix] todo: <来源摘要>`` 形态）——
    knowledge_backfill 的 todo.md 写后就地提交（append/upsert）经延迟导入
    复用本助手但需要自己的主题行（同族先例 _commit_todo 的
    ``[fenix] daily self-review``）；缺省 None 维持 evolution 标记回写主题行
    （向后兼容，既有调用方零改动）。

    - todo.md 未被 git 跟踪（含 ls-files 非零退出——目录非 git 仓库）→ 跳过
      提交，行为与不提交时一致，不报错；
    - push 失败降级 WARNING 不重试（commit 已产生，与 _commit_todo 同策略）；
    - 提交失败（含 index.lock 竞争）降级为日志留痕，不抛错、不回滚已写入
      内容、不做自动重试（下一次写入自然再试）。返回是否完成 commit。
    """
    proot = Path(proot)
    todo_rel = ".fenix/todo.md"
    git = ["git", "-C", str(proot)]
    try:
        ls = subprocess.run(
            git + ["ls-files", "--", todo_rel],
            capture_output=True,
            text=True,
            timeout=30,
            env=_git_c_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _logger.warning("evolution: todo.md git ls-files 失败，跳过提交: %s", e)
        return False
    if ls.returncode != 0 or not ls.stdout.strip():
        # 未 tracked / 非 git 仓库：按现状不提交，debug 留痕即可（不报错）
        _logger.debug(
            "evolution: todo.md 未被 git 跟踪，跳过提交 %s: %s",
            proot,
            ls.stderr.strip()[:120],
        )
        return False
    try:
        add = subprocess.run(
            git + ["add", "--", todo_rel],
            capture_output=True,
            text=True,
            timeout=30,
            env=_git_c_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _logger.warning("evolution: todo.md git add 失败（跳过提交）: %s", e)
        return False
    if add.returncode != 0:
        _logger.warning(
            "evolution: todo.md git add 失败（跳过提交，写入不回滚）: %s",
            add.stderr.strip()[:200],
        )
        return False
    msg = (
        subject
        if subject
        else f"[fenix] evolution: 自进化标记回写 {timelib.now_local().strftime('%Y-%m-%d')}"
    )
    if message_suffix:
        msg = f"{msg}\n\n{message_suffix}"
    try:
        commit = subprocess.run(
            git + ["commit", "-m", msg, "--", todo_rel],
            capture_output=True,
            text=True,
            timeout=30,
            env=_git_c_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _logger.warning("evolution: todo.md git commit 失败: %s", e)
        return False
    if commit.returncode != 0:
        output = f"{commit.stdout.strip()}\n{commit.stderr.strip()}".strip()
        # 良性无变更两形态：「nothing to commit, working tree clean」（树干净）
        # 与「nothing added to commit but untracked files present」（树上有
        # 未跟踪文件但本 pathspec 无变更）——后者才是批末合并提交的常态
        # （items.jsonl 等 gitignored 外文件在场）。
        if "nothing to commit" in output or "nothing added to commit" in output:
            _logger.info("evolution: todo.md 提交无变更: %s", output[:200])
        else:
            _logger.warning(
                "evolution: todo.md git commit 失败（降级留痕，写入不回滚）: %s",
                output[:200],
            )
        return False
    try:
        push = subprocess.run(
            git + ["push"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_git_c_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _logger.warning("evolution: todo.md git push 失败（降级 WARNING，commit 已产生）: %s", e)
        return True
    if push.returncode != 0:
        _logger.warning(
            "evolution: todo.md git push 失败（降级 WARNING，commit 已产生）: %s",
            push.stderr.strip()[:200],
        )
    return True


def commit_todo_marker(
    project_path=None,
    project_name=None,
    message_suffix=None,
    subject=None,
) -> bool:
    """按项目触发一次 todo.md 标记合并提交（编排层批末入口）。

    ingest_item 批量路径的标记回写不逐条 commit（避免提交风暴），由编排层在
    一轮 ingest 循环结束后对本轮涉及的每个项目各调用一次本函数合并提交；
    自动接受批路径（``auto_accept_pending``）逐条 defer 后同样经本入口对本
    批涉及的每个源项目各合并提交一次，``message_suffix`` 携带该项目本批条目
    id 明细。仅 dashboard
    手动单条接受与单点写路径（reject / delete）经 ``write_todo_marker`` 的
    缺省提交开关即时提交，不走本入口。

    ``subject``：非空时替换缺省主题行（透传 ``_commit_todo_marker``，供
    knowledge_backfill 写后就地提交复用）；缺省维持 evolution 标记回写
    主题行。

    ``project_path`` 与 ``project_name`` 均未提供、或名称经 registry 解析
    失败时返回 False。提交失败降级日志，不向调用方抛错。
    """
    if project_path is not None:
        proot = Path(project_path)
    else:
        proot = _resolve_project_path_by_name(str(project_name or ""))
    if proot is None:
        _logger.warning("evolution: todo.md 批量提交跳过——项目路径未解析: %s", project_name)
        return False
    try:
        return _commit_todo_marker(proot, message_suffix=message_suffix, subject=subject)
    except Exception as e:  # noqa: BLE001 —— 提交失败不向调用方抛错
        _logger.warning("evolution: todo.md 提交异常（已跳过，写入不回滚）: %s", e)
        return False


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
    spec_md / tasks_md）、``capability`` / ``name`` 非法（``^[a-z0-9][a-z0-9-]*\Z``）
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
        # code-review item 85e167859717：已存在的草稿目录先整体删除重建——
        # 上次写入中途被杀等留下的旧 capability 子目录或杂散文件若混存，
        # accept 的 copytree 会原样带入 spec/changes 污染立项产物。
        if d.is_dir():
            shutil.rmtree(d)
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
    except (OSError, UnicodeEncodeError) as e:
        # UnicodeEncodeError 非 OSError：spec 文本来自 agent 产出 JSON，可含
        # \ud800 类孤立代理转义，write_text 编码时抛出——裸穿透会跳过清理
        # 分支残留半写草稿，条目无标记下轮重试同一异常（a1e2bb031dae）
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
    解析。

    两级失败语义（code-review item 2beb5528e1b9 收拢后口径）：lint 函数
    自身故障（lint_declared / lint_tasks_parseable 内部异常）fail-open——
    记 WARNING 跳过该函数，不阻塞；``core.deliverables`` 导入失败（框架
    安装残缺 / sys.path 错，确定性环境故障而非 lint 抖动）显式上抛——
    门禁静默放行会让带缺陷草稿照常立项，代价是一轮完整 run 后才在晋升/
    守卫暴露。本函数是唯一实现（code_review._lint_draft 薄委托至此），
    单点演进防再漂移。

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
    finally:
        if injected:
            # code-review item 14a703dcb5c9：常驻进程两个线程并发进入本函数时
            # 可能同时判 injected=True 各插一次，先收尾者 remove 后，后收尾者的
            # remove 会因条目已不在 sys.path 抛 ValueError 穿透 ingest_item。
            # 防御式移除（尽力移除、缺席不报错）而非模块级锁：注入唯一生效的
            # 裸进程形态单线程无竞态，daemon 内注入本就无解析效果（见函数
            # docstring），不值得为竞态再引入全局锁。
            try:
                sys.path.remove(fenix_dir)
            except ValueError:
                pass


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

    标记回写传 ``commit=False`` 关闭逐条提交（evo-add-todo-marker-commit-on-write）：
    一轮批量落多条目时逐条 commit 会退化为提交风暴，由编排层（maintenance_runs
    一轮 ingest 循环结束后）对本轮涉及的项目集合按项目各触发一次合并提交。
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
        "worth_gate_reason": None,
    }

    if not worth_spec:
        base["status"] = "analyzed"
        upsert_item(project_root, base)
        write_todo_marker(base, commit=False)
        return "analyzed"

    # ── 立项价值闸门（2026-10-11 判定收紧，用户定调 A+B）──────────────
    # B1 verdict 一致性：worth_spec=true 的必要条件 = problem_exists=yes
    # 且 suggestion_sound=yes。分析侧提示词（agents/evolution.md）同款收紧
    # （A 层）；此处机械校验防提示词漂移——partial 组合（问题/建议只部分
    # 成立）2026-10-04~10 一周 50 条自动接受里占 80%，事后实证含负价值
    # 样本（anomaly-redispatch-budget 熔断放大）与方案和用户意图相反
    # 样本（severity-batch-gate 被迫缺省翻转）。字段缺失按 partial 同拦
    #（fail-closed）。拦截置 analyzed（非 draft_failed——这是设计内过滤
    # 而非故障），记 worth_gate_reason 供前端/日志呈现。
    v = verdict if isinstance(verdict, dict) else {}
    if v.get("problem_exists") != "yes" or v.get("suggestion_sound") != "yes":
        base["status"] = "analyzed"
        base["worth_gate_reason"] = (
            "verdict 闸门：worth_spec=true 要求 problem_exists=yes 且 "
            "suggestion_sound=yes（双 yes），实得 "
            f"problem_exists={v.get('problem_exists')!r} / "
            f"suggestion_sound={v.get('suggestion_sound')!r}——问题或建议"
            "只部分成立的不自动立项"
        )
        _logger.info(
            "evolution: 条目 %s 被立项价值闸门拦下（verdict 非双 yes）: %s",
            eid, base["worth_gate_reason"],
        )
        upsert_item(project_root, base)
        write_todo_marker(base, commit=False)
        return "analyzed"

    # B2 同名在途：spec/changes/evo-<name>/ 已存在 → 同一问题域重复立项
    # （曾以 -<6hex> 后缀照样立项，一周内散件族 8 个、codefix 族 10 个）
    # → analyzed 记原因。归档同名不挡（修复无效场景重新立项合法）；
    # STATE 在途同名由接受路径 resolve_spec_name 既有防御兜底。
    spec_obj = item.get("spec") if isinstance(item.get("spec"), dict) else {}
    spec_name = str(spec_obj.get("name") or "")
    if _KEBAB_RE.match(spec_name):
        inflight = f"evo-{spec_name}"
        if (Path(project_root) / "spec" / "changes" / inflight).is_dir():
            base["status"] = "analyzed"
            base["worth_gate_reason"] = (
                f"同名 SPEC 在途：spec/changes/{inflight} 已存在——"
                "同主题重复立项被闸门拦下，先观察在途 SPEC 的效果"
            )
            _logger.info(
                "evolution: 条目 %s 被同名在途闸门拦下: spec/changes/%s",
                eid, inflight,
            )
            upsert_item(project_root, base)
            write_todo_marker(base, commit=False)
            return "analyzed"

    d, reason = materialize_draft(base, project_root)
    if d is None:
        base["status"] = "draft_failed"
        base["draft_failed_reason"] = reason
        _logger.warning("evolution: 条目 %s 草稿落盘失败: %s", eid, reason)
        upsert_item(project_root, base)
        write_todo_marker(base, commit=False)
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
        write_todo_marker(base, commit=False)
        return "draft_failed"

    base["status"] = "pending"
    upsert_item(project_root, base)
    # pending 是 ingest_item 批量路径的第 4 处回写：同传 commit=False，
    # 由编排层批末 commit_todo_marker 合并提交（避免逐条提交风暴）
    write_todo_marker(base, commit=False)
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
            # 归档台账读取故障与上方 STATE 读取、下方 spec/archive 目录遍历
            # 同口径保守判冲突（fail-closed，code-review item f2d40aa919ee）：
            # 对仅在台账中登记、目录名归一化候选集不命中的形态，瞬时故障静默
            # 放行会放过撞名候选，立项后产生归属歧义。
            _logger.warning("evolution: 读取归档清单判定重名失败，保守按冲突处理: %s", e)
            return True
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
            except OSError as e:
                # 归档目录遍历失败与上方 STATE 读取失败同口径保守判冲突
                # （fail-closed，code-review item f02edb677a23）：瞬时 IO 故障
                # 静默放行会放过与既有归档撞名的候选名，立项后产生归属歧义。
                _logger.warning("evolution: 遍历 spec/archive 判定重名失败，保守按冲突处理: %s", e)
                return True
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

    本函数是唯一实现（code_review._git_commit 薄委托至此，code-review item
    2beb5528e1b9），单点演进防再漂移。

    Returns: ``(ok, error)``；ok=False 时调用方负责清理未跟踪副本（含
    撤回 pathspec 暂存项——error 前缀区分 ``git add 失败`` / ``git commit
    失败`` 阶段，调用方可据此判断脏索引形态）。
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
    now_local = (now if now is not None else timelib.now_local()).astimezone()  # SPEC-B 批④收拢
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
    defer_commit: bool = False,
) -> dict:
    """接受路径（人工同意与自动接受共用实现，design D6；3.5）。

    ``defer_commit``：置真时接受成功的标记回写不触发 git 提交（
    ``write_todo_marker`` 以 ``commit=False`` 落写），由批循环消费方在批末
    对本项目调 ``commit_todo_marker`` 合并提交一次（evo-evolution-accept-
    marker-batching design D2，当前唯一消费方 ``auto_accept_pending``）；
    缺省 False 保持「写后即提交」（dashboard 手动单条路径语义不变）。

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
    marker_item: Dict[str, Any] = {}

    def _persist(rec: dict) -> None:
        # 锁内单条写回收口到 _write_items_unlocked；MUST NOT 再走
        # upsert_item/read_items——锁内二次 flock 自阻塞（见 helper 说明）。
        current = _read_items_unlocked(path)
        current[rec["id"]] = rec
        _write_items_unlocked(path, current)

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
            # 此前清理失败的残留（显式 residue 标记）时才清理后按原名重试；其余
            # 一律置 accept_failed + 告警，不删不动，重试经 resolve_spec_name 换
            # 后缀名。spec_name 判等不构成残留证据（code-review item
            # afe111a45d02）：注册失败分支无论清理成败都持久化 spec_name，清理
            # 成功后磁盘已无残留，窗口内外部新建的同名目录会被误判为本条目残留
            # 而整体删除（未提交内容不可恢复）。
            if rec.get("spec_name") != name or not rec.get("residue"):
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
            # code-review item 397de4b415ba：add 已写入索引而 commit 失败
            # （hook 拒绝 / index.lock 竞争 / 缺 identity 等）时，先撤回
            # pathspec 暂存项再删工作树副本，避免留下「索引暂存新文件 +
            # 工作树已删」的脏索引阻塞/污染后续 merge-back（与
            # code_review.generate_fix_spec 的提交失败分支同款）。add 阶段
            # 失败时索引也可能已部分暂存，故无条件 reset（幂等）；撤回失败
            # 只留痕，不掩盖提交失败本因。
            try:
                undo = subprocess.run(
                    [
                        "git", "-C", str(project_root),
                        "reset", "-q", "--", f"spec/changes/{name}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if undo.returncode != 0:
                    _logger.warning(
                        "evolution: 撤回暂存 spec/changes/%s 失败（退出码 %s）: %s",
                        name,
                        undo.returncode,
                        (undo.stderr or "").strip()[:200],
                    )
            except (OSError, subprocess.TimeoutExpired) as e:
                _logger.warning("evolution: 撤回暂存 spec/changes/%s 失败: %s", name, e)
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
            # 残留归属显式化（code-review item afe111a45d02）：仅清理失败（副本
            # 可能仍在盘上、git 状态不确定）才置 residue 标记，供重试时
            # dest.exists() 分支判定归属；清理成功即复位（磁盘已无残留）。
            if cleaned:
                rec.pop("residue", None)
            else:
                rec["residue"] = True
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
        rec.pop("residue", None)  # 立项成功复位残留标记（code-review item afe111a45d02）
        _persist(rec)
        marker_item.update(rec)
        return {"ok": True, "status": rec["status"], "spec_name": name, "error": None}

    outcome = _with_lock(path, _do)
    # 标记回写移到 items.jsonl 锁释放之后（code-review item c3bd82b14eed，与
    # reject_item/delete_item 同纪律）：compare-and-set 的状态写回已在锁内完成，
    # todo.md 写入与 git 提交子进程不参与 CAS，放锁内只会无谓拉长持锁窗口
    # （与 write_todo_marker 自身「git 子命令不得放入锁内」的纪律一致）。
    if outcome.get("ok") and marker_item:
        try:
            write_todo_marker(
                marker_item,
                disposition=_disposition_from_status(outcome["status"]),
                commit=not defer_commit,
            )
        except Exception as e:  # noqa: BLE001 —— 回写失败不影响已成功的接受
            _logger.warning("evolution: 标记回写异常（已跳过）: %s", e)
    return outcome


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
    marker_item: Dict[str, Any] = {}

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
        # 锁内单条写回收口到 _write_items_unlocked（MUST NOT 再走
        # upsert_item/read_items，理由见 helper 说明）；直接复用 _do 开头
        # 读取的 items dict——持锁期间合作写者均被 flock 排除，锁内重读
        # 必然返回同一内容，纯属重复 IO（code-review item 05ecd61b5e37）。
        items[rec["id"]] = rec
        _write_items_unlocked(path, items)
        marker_item.update(rec)
        return {"ok": True, "status": "rejected", "error": None}

    outcome = _with_lock(path, _do)
    # 标记回写移到 items.jsonl 锁释放之后（code-review item c3bd82b14eed）：
    # compare-and-set 的状态写回已在锁内完成，todo.md 写入与 git 提交子进程
    # 不参与 CAS，放锁内只会无谓拉长持锁窗口（与 write_todo_marker 自身
    # 「git 子命令不得放入锁内」的纪律一致）。
    if outcome.get("ok") and marker_item:
        try:
            write_todo_marker(marker_item, disposition="拒绝")
        except Exception as e:  # noqa: BLE001 —— 回写失败不影响已成功的拒绝
            _logger.warning("evolution: 标记回写异常（已跳过）: %s", e)
    return outcome


def delete_item(item_id_: str, project_root, defer_commit: bool = False) -> dict:
    """删除路径：把条目记录移出 ``items.jsonl`` 并清理其草稿目录（硬删）。

    语义（用户确认）：
    - **任意状态均可删**（不设状态门，`accepted` / `auto_accepted` 亦允许）；
    - **硬删**：记录从 items.jsonl 移除，不写墓碑。已知后果——该 id 不再出现在
      ``known_ids()`` 中，todo.md 里同名记录会在下一轮分析 run 重新入库；
      前端确认弹窗须向用户明示此后果。
    - 草稿目录存在则一并删除（路径经 ``_safe_draft_dir`` 校验；符号链接越界
      拒绝并保持记录不动），避免留下无主目录。

    ``defer_commit``：置真时删除成功的标记回写不触发 git 提交（
    ``write_todo_marker`` 以 ``commit=False`` 落写），由批循环消费方在批末
    按项目调 ``commit_todo_marker`` 合并提交（当前唯一消费方 ``prune_items``，
    code-review item 15c9a7b72fbe）；缺省 False 保持「写后即提交」（dashboard
    手动单条删除路径语义不变）。

    读-改-写在同一把 flock 内完成（与 ``upsert_item`` 同范式），避免与 daemon
    侧写入交错。返回 ``{"ok", "status", "error"}``；``status`` 为删除前状态。
    """
    path = items_path(project_root)
    outcome: Dict[str, Any] = {}
    marker_item: Dict[str, Any] = {}

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
        _write_items_unlocked(path, current)
        marker_item.update(rec)
        outcome.update({"ok": True, "status": status, "error": None})

    try:
        _with_lock(path, _do)
    except Exception as e:  # noqa: BLE001 —— 存储异常收敛为错误对象，不抛穿
        return {"ok": False, "status": None, "error": f"条目删除失败: {e}"}
    # 删除成功后回写标记（保留删除前的处理意见 + 删除：是）；回写失败不影响
    # 删除。移到 items.jsonl 锁释放之后（code-review item c3bd82b14eed）：
    # todo.md 写入与 git 提交子进程不参与 compare-and-set，放锁内只会无谓
    # 拉长持锁窗口。
    if outcome.get("ok") and marker_item:
        try:
            write_todo_marker(
                marker_item,
                disposition=_disposition_from_status(outcome["status"]),
                deleted=True,
                commit=not defer_commit,
            )
        except Exception as e:  # noqa: BLE001 —— 回写失败不影响已成功的删除
            _logger.warning("evolution: 标记回写异常（已跳过）: %s", e)
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
    逐条以 ``defer_commit=True`` 关闭标记回写的即时提交，批末对本批删出的
    每个项目各调一次 ``commit_todo_marker`` 合并提交（``message_suffix`` 携带
    被清理条目明细）——与 ``auto_accept_pending`` 的批处理纪律对齐，避免
    首次清理历史积压时逐条 ls-files + add + commit + push 的提交风暴与单条
    push 失败的重复尝试（code-review item 15c9a7b72fbe）。

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
    # 生产者-scoped 收集：本循环真正删出的条目 id 按其项目名分组，供批末
    # 合并提交的 message_suffix 明细（与 auto_accept_pending 同纪律）。标记
    # 回写项目由 delete_item 内部按 rec["project"] 经 registry 解析，批末
    # 提交按同名项目收口，与写入口径对称。
    deleted_by_project: Dict[str, List[str]] = {}
    for rec in victims:
        eid = rec.get("id")
        try:
            result = delete_item(eid, project_root, defer_commit=True)
        except Exception as e:  # noqa: BLE001 —— 单条异常不中断其余清理
            failed += 1
            details.append({"id": eid, "ok": False, "error": str(e)})
            continue
        if result.get("ok"):
            deleted += 1
            project_name = str(rec.get("project") or "")
            if project_name:
                deleted_by_project.setdefault(project_name, []).append(str(eid))
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
    # 批末合并提交：每个涉及项目各一次（无变更时 _commit_todo_marker 按
    # 「nothing to commit」info 收敛，不告警）
    for project_name, ids in sorted(deleted_by_project.items()):
        detail = "\n".join(f"- {eid}" for eid in ids)
        commit_todo_marker(
            project_name=project_name,
            message_suffix=f"保留策略清理条目（{len(ids)} 条）:\n{detail}",
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

    批末合并提交（evo-evolution-accept-marker-batching design D1/D3）：逐条
    接受以 ``defer_commit=True`` 关闭标记回写的即时提交。标记回写由
    ``write_todo_marker`` 按条目 project 字段经 registry 解析落到各源项目的
    ``.fenix/todo.md``，循环结束后对本批涉及的每个源项目各调一次
    ``commit_todo_marker``（``project_name=``）合并提交，消息附该项目本批
    接受条目的 id 明细——与 ``prune_items`` 同纪律，MUST NOT 钉死框架根
    ``project_path``（多项目部署下源项目标记改动会滞留未提交，框架根若恰有
    滞留改动反被卷进内容与消息不符的提交）。生产者-scoped 收集（只合并本循
    环自己的写入），不做文件级时间窗去抖——
    ``.fenix/todo.md`` 另有 self_review 生产者，时间窗会把对方滞留改动卷进
    错误消息的提交。

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
    accepted_by_project: Dict[str, List[str]] = {}
    for rec in pending:
        try:
            result = accept_item(
                rec["id"],
                project_root,
                state_machine,
                decided_by="auto",
                start_after=start_after,
                defer_commit=True,
            )
        except Exception as e:
            _logger.error("evolution: 自动接受条目 %s 异常: %s", rec["id"], e)
            _write_admin_warning(project_root, f"自进化条目 {rec['id']} 自动接受异常: {e}")
            summary["failed"] += 1
            summary["details"].append({"id": rec["id"], "ok": False, "error": str(e)})
            continue
        if result.get("ok"):
            summary["accepted"] += 1
            # 只有本循环内真正走完立项成功分支的条目写了标记（幂等返回的
            # 现状条目不写），明细只收这些 id。标记回写按条目 project 字段
            # 经 registry 解析，批末提交按同名项目收口，与写入口径对称
            if result.get("status") == "auto_accepted":
                project_name = str(rec.get("project") or "")
                if project_name:
                    accepted_by_project.setdefault(project_name, []).append(rec["id"])
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
    # 批末合并提交：每个涉及项目各一次（与 prune_items 同纪律；无变更时
    # _commit_todo_marker 按「nothing to commit」info 收敛，不告警）
    for project_name, ids in sorted(accepted_by_project.items()):
        detail = "\n".join(f"- {eid}" for eid in ids)
        commit_todo_marker(
            project_name=project_name,
            message_suffix=f"接受条目（{len(ids)} 条）:\n{detail}",
        )
    return summary


# ── 任务 3.8：契约产物解析 ─────────────────────────────────────────


class ContractError(ValueError):
    """分析 run 契约产物不合法（调用方判整轮失败，3.8）。"""


def read_contract(path, lenient: bool = False) -> Dict[str, Any]:
    """解析分析 run 契约产物 JSON（3.8）。

    任一不满足 MUST 抛 ``ContractError`` 判整轮失败（不产生任何条目）：
    - 文件存在（缺失报「产物文件未写出」）且以 UTF-8 可解码（坏字节报
      「产物文件非 UTF-8 编码」）且 JSON 可解析（非法报「产物 JSON 不可解析」，
      三者可判别归因）；
    - JSON 可解析且为 dict；
    - 含 ``items`` 数组；
    - 每条含 ``project`` / ``date_section`` / ``title`` / ``verdict``(dict)
      且 ``section`` ∈ {浪费, 失误, 可改进}；
    - ``id`` 若提供必须为字符串（缺失回落 ``item_id`` 复算）。非字符串真值
      id 直达 ``upsert_item`` 会使 ``sorted()`` 混排 str/int 键抛 TypeError，
      该条目每轮复现同一异常成永久阻塞（code-review item a29d89428f7f），
      故在契约层整轮拒绝。

    单条目契约错误（上面后三条）默认（``lenient=False``）保持整份拒绝，
    既有调用方行为不变；``lenient=True``（evo-add-evolution-contract-
    partial-accept 1.1，仅 evolution 落库链路启用）改为收集该条错误并跳过、
    合法条目照常通过——拒绝粒度从「整份」细化到「单条」，与输入侧
    todo.md 未知小节「跳过+WARNING」宽口径对齐。文件级错误与「全部条目
    非法」（模型大面积跑偏，D3）仍整体抛 ContractError。

    解析成功后由调用方删除产物文件。返回 {"run_id", "degraded", "items",
    "errors"}：``items`` 为通过校验的条目；``errors`` 为
    ``[{"index", "message"}]`` 逐条错误记录（严格口径恒为空列表）。
    """
    # 失败归因分级（evo-add-evolution-product-salvage）：「产物文件未写出」
    # 与「产物 JSON 不可解析」拆成两个可判别的 ContractError 文案——告警与
    # 日志可直接判别失败面（前者是子代理从未写出/被清理，后者是半写截断
    # 或内容损坏，处置不同）。
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ContractError(f"产物文件未写出: {e}") from e
    except UnicodeDecodeError as e:
        # 坏 UTF-8 字节（如子代理以非 UTF-8 编码写出产物）既非 OSError 也非
        # JSONDecodeError，裸穿透会击穿「任一不满足 MUST 抛 ContractError」的
        # 契约；单列第三条文案，与「未写出 / JSON 语法坏」可判别归因（处置不同）。
        raise ContractError(f"产物文件非 UTF-8 编码（含坏字节）: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ContractError(f"产物 JSON 不可解析: {e}") from e
    if not isinstance(data, dict):
        raise ContractError("产物顶层不是对象")
    items = data.get("items")
    if not isinstance(items, list):
        raise ContractError("产物缺 items 数组")

    def _validate_item(item, idx: int):
        """单条目契约校验：通过返回 None，否则返回可归因错误文案。"""
        if not isinstance(item, dict):
            return f"items[{idx}] 不是对象"
        for field in ("project", "date_section", "title"):
            if not isinstance(item.get(field), str) or not item.get(field):
                return f"items[{idx}] 缺必填字段 {field}"
        if item.get("section") not in TODO_SECTIONS:
            return f"items[{idx}].section 不在三值枚举内: {item.get('section')!r}"
        verdict = item.get("verdict")
        if not isinstance(verdict, dict):
            return f"items[{idx}] 缺 verdict 对象"
        if "worth_spec" not in verdict or not isinstance(verdict.get("worth_spec"), bool):
            return f"items[{idx}].verdict.worth_spec 非法"
        # code-review item a29d89428f7f：缺失/空串回落 item_id 复算；非字符串
        # 真值 id（如数字）会在 upsert_item 锁内 sorted() 混排 str/int 键抛
        # TypeError，条目永久落不了库（调用方逐条跳过 → 每轮重试同一异常）。
        raw_id = item.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            return f"items[{idx}].id 非字符串: {raw_id!r}"
        return None

    valid_items: list = []
    item_errors: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        msg = _validate_item(item, idx)
        if msg is None:
            valid_items.append(item)
        elif lenient:
            # 宽口径：单条非法只牺牲该条，错误清单随返回值上交落库侧归因。
            item_errors.append({"index": idx, "message": msg})
        else:
            raise ContractError(msg)

    if lenient and items and not valid_items:
        # D3 全非法仍 fail-closed：单条跳过的宽口径不适用于「模型大面积
        # 跑偏」，防坏数据入库的原始动机保留，整份拒绝。
        raise ContractError(
            f"产物全部 {len(items)} 条条目契约非法，整份拒绝"
            f"（首条: {item_errors[0]['message']}）"
        )

    return {
        "run_id": data.get("run_id"),
        "degraded": data.get("degraded"),
        "items": valid_items,
        "errors": item_errors,
    }
