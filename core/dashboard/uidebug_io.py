"""uidebug_io.py — fenix-ui-debug 调试会话（session）落盘与校验单源。

fenix-ui-debug skill 让 agent 把「任意 http(s) URL 的页面」接入 dashboard
的批注框架：目标页经反向代理路由 ``GET /uidebug/<project>/<session>/~/<path>``
搬到 dashboard 同源下注入批注器，批注经 ``POST /api/uidebug/<project>/<session>/feedback``
落盘复用 :mod:`core.dashboard.prototype_io` 的 ``append_feedback``；批注环
的回收侧（列表 / 删除 / 重编辑）见本模块下方「批注管理」段。

会话描述文件落在 ``<project>/.fenix/ui-debug/<session>/session.json``：
``{"target": "http(s)://host[:port][/base]", "session": ..., "created": ...}``。
``.fenix/*`` 已被 .gitignore 整体覆盖，调试会话不入库。

安全边界（与 dashboard 既有信任姿态一致）：代理只访问会话里注册的
``target`` 源——session.json 只能由本机磁盘上的 skill 脚本/skill 流程写入，
HTTP 通道不提供「注册任意 URL」的入口，因此不构成开放代理；scheme 白名单
http/https 在本模块 :func:`normalize_target` 单点收敛。
"""

from __future__ import annotations

import json
import secrets
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

UI_DEBUG_DIR_NAME = "ui-debug"
SESSION_FILE_NAME = "session.json"

# 会话目录里 feedback.json 与派生名不设静态通道（与原型目录不同：本目录
# 本就没有静态伺服，唯一出口是反馈 POST；此常量仅为语义对齐预留）。
FEEDBACK_FILE_NAME = "feedback.json"


def session_segment_safe(raw: str) -> bool:
    """session 段安全校验：复用 spec_segment_safe 同一口径（单段、无穿越组件）。"""
    # 延迟导入避免模块加载顺序耦合；spec_segment_safe 是无依赖纯函数
    from core.dashboard.prototype_io import spec_segment_safe

    return spec_segment_safe(raw)


def session_dir(project_path: Path, session: str) -> Path:
    """会话目录：``<project>/.fenix/ui-debug/<session>/``。"""
    return Path(project_path) / ".fenix" / UI_DEBUG_DIR_NAME / session


def normalize_target(raw: str) -> str | None:
    """校验并规范化目标 URL，非法返回 None。

    - scheme 白名单 http/https（file://、ftp://、ws:// 等一律拒绝——代理
      通道只为「浏览器可打开的页面」服务）；
    - 必须含 host（netloc），fragment 丢弃（不影响上游寻址）；
    - 返回形态去掉尾部「/」（空路径保持空），供代理拼接子路径使用；
    - 路径含「.」「..」组件一律拒绝（点段会语义逃出 base 前缀，上游按
      原样路径请求时不存在可信的「留在 base 内」保证）。
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parts = urllib.parse.urlsplit(raw.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    if not parts.netloc:
        return None
    path = parts.path.rstrip("/")
    if any(s in (".", "..") for s in path.replace("\\", "/").split("/")):
        return None
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def normalize_entry(raw: str) -> str | None:
    """校验并规范化入口子路径（相对形态），非法返回 None。

    空/None 合法（入口=代理根）；拒绝绝对段、「.」「..」组件、反斜杠、
    NUL（与 spec_segment_safe 同一威胁模型——entry 会拼进代理子路径，
    虽然 build_upstream_url 不落盘无穿越面，但禁止其逃出 target base
    路径前缀的语义必须在此收敛）。
    """
    if raw is None or raw == "":
        return ""
    if not isinstance(raw, str) or "\x00" in raw:
        return None
    norm = raw.replace("\\", "/").strip("/")
    if not norm:
        return ""
    segs = norm.split("/")
    if any(s in (".", "..") or not s for s in segs):
        return None
    return "/".join(segs)


def normalize_entry_query(raw: str | None) -> str | None:
    """校验并规范化入口 query 串（不带前导「?」），非法返回 None。

    用途：登录型页面的 token URL（``?token=...``）——query 里的鉴权参数
    必须随入口一起进代理通道。``proto_round`` 是 fenix 迭代参数，从此处
    剥离（轮次由 wrapper/代理注入侧单点管理，不允许会话文件携带）。
    """
    if raw is None or raw == "":
        return ""
    if not isinstance(raw, str) or "\x00" in raw or len(raw) > 2048:
        return None
    q = raw.lstrip("?")
    try:
        pairs = urllib.parse.parse_qsl(q, keep_blank_values=True)
    except ValueError:
        return None
    kept = [(k, v) for k, v in pairs if k != "proto_round"]
    return urllib.parse.urlencode(kept)


def split_target_url(raw: str) -> tuple[str, str, str] | None:
    """把用户给的完整 URL 拆成（target base, 入口文档相对路径, 入口 query）。

    约定「末段 = 入口文档」：``http://h:3000/app/page2`` → target
    ``http://h:3000/app``、entry ``page2``；``http://h:3000/`` 与
    ``http://h:3000`` → target=origin、entry 空。query 不丢弃而是保留为
    入口 query（token URL 登录场景：``?token=...`` 是鉴权入口的一部分，
    固化进会话才能让代理通道完成登录）；``proto_round`` 从 query 剥离。
    拆分失败（非法 scheme/netloc/entry/query）返回 None。
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parts = urllib.parse.urlsplit(raw.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    stripped = parts.path.strip("/")
    if "/" in stripped:
        # 末段为入口文档；base 路径保留前段（可能为空 → origin 根）
        head, _, entry_raw = stripped.rpartition("/")
        base_path = "/" + head if head else ""
    else:
        base_path = ""
        entry_raw = stripped
    entry = normalize_entry(entry_raw)
    if entry is None:
        return None
    entry_query = normalize_entry_query(parts.query)
    if entry_query is None:
        return None
    target = urllib.parse.urlunsplit((parts.scheme, parts.netloc, base_path, "", ""))
    normalized = normalize_target(target)
    if normalized is None:
        return None
    return normalized, entry, entry_query


def write_session(project_path: Path, session: str, target: str,
                  entry: str = "", entry_query: str = "") -> Path:
    """写入/更新会话文件，返回 session.json 路径。调用方保证 session 段已过校验。

    entry 为入口文档相对路径、entry_query 为入口 query 串（normalize_entry
    /normalize_entry_query 合法形态）；同名会话重跑直接覆盖 session.json
    （重指 target 是「传入一个新 URL」的正常路径）。
    """
    normalized = normalize_target(target)
    if normalized is None:
        raise ValueError(f"invalid target URL: {target!r}")
    normalized_entry = normalize_entry(entry)
    if normalized_entry is None:
        raise ValueError(f"invalid entry path: {entry!r}")
    normalized_query = normalize_entry_query(entry_query)
    if normalized_query is None:
        raise ValueError(f"invalid entry query: {entry_query!r}")
    d = session_dir(project_path, session)
    d.mkdir(parents=True, exist_ok=True)
    path = d / SESSION_FILE_NAME
    doc = {
        "target": normalized,
        "entry": normalized_entry,
        "entry_query": normalized_query,
        "session": session,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def load_session(project_path: Path, session: str) -> dict | None:
    """读取会话，返回 {"target": 规范化 URL, "entry": 相对路径}；缺失/损坏/非法一律 None。

    路由侧对 None 与「会话不存在」同语义回 404（不区分文件损坏细节，
    不把磁盘状态透给 HTTP 客户端）。旧版会话文件无 entry 字段 → 兜空串。
    """
    path = session_dir(project_path, session) / SESSION_FILE_NAME
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    target = normalize_target(doc.get("target"))
    if target is None:
        return None
    entry = normalize_entry(doc.get("entry"))
    if entry is None:
        entry = ""
    entry_query = normalize_entry_query(doc.get("entry_query"))
    if entry_query is None:
        entry_query = ""
    return {"target": target, "entry": entry, "entry_query": entry_query}


# ── 批注管理（删除/重编辑）────────────────────────────────────────────
# 批注环不止「追加」：用户在浏览器里提错/想改口径时，须能按条删除与重写。
# 单条批注由此获得稳定 ``id``（追加时由路由侧补发），GET 列表对历史无 id
# 条目惰性补发（迁移即落盘），删除/更新按 id 寻址。读写复用 prototype_io
# 的两级锁与损坏隔离口径，形态（裸 list / {"feedback":[...]} dict）保留。


def new_feedback_id() -> str:
    """单条批注的稳定 id：毫秒时间戳 + 6 位随机尾巴，删除/重编辑按它寻址。"""
    return "fb-{}-{}".format(int(time.time() * 1000), secrets.token_hex(3))


def _mutate_feedback(proto_dir: Path, mutate) -> tuple[str, str | None]:
    """feedback.json 锁内读-改-写：``mutate(entries)`` 就地变更，保形态回写。

    ``mutate`` 返回 True 表示确有变更（才落盘）；返回 False 视为未命中
    （文件缺失或目标条目不存在），不动文件——唯一例外是损坏文件：即使
    未命中也先隔离 .bak 并把提示随 note 返回（GET 读侧零变更路径同样
    履行损坏隔离契约，见 :func:`load_feedback`）。返回 (result, note)：
    ``result`` ∈ {"ok", "missing"}；``note`` 为损坏隔离提示（无则 None）。
    文件形态不可并入（无 feedback 列表的 dict）拒绝 409；超总量上限拒绝
    507；写盘失败转 500——与 append_feedback 同一错误通道
    （FeedbackWriteRejected）。

    锁序与 append_feedback 一致：先跨进程 flock 再线程锁，否则两个模块
    的写方互不互斥。
    """
    from core.dashboard.prototype_io import (
        FEEDBACK_FILE_NAME,
        FEEDBACK_THREAD_LOCK,
        FeedbackWriteRejected,
        MAX_FEEDBACK_FILE_BYTES,
        feedback_file_lock,
        isolate_corrupt_feedback,
    )
    from core.fs_utils import atomic_write_text

    target = Path(proto_dir) / FEEDBACK_FILE_NAME
    with feedback_file_lock(target), FEEDBACK_THREAD_LOCK:
        if not target.is_file():
            return "missing", None
        entries: list = []
        doc: dict | None = None  # dict 形态整体保留（round 等同级字段不丢）
        corrupt = False
        isolate_reason = "无法解析（疑似损坏）"
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            # 形态分派与 append_feedback 同口径：裸 list / dict 含 feedback
            # 列表 / dict 无 feedback 列表（409 拒绝）/ 合法 JSON 标量与
            # 非法 JSON（隔离 .bak 后按空数组起步）
            if isinstance(existing, list):
                entries = existing
            elif isinstance(existing, dict) and isinstance(existing.get("feedback"), list):
                doc = existing
                entries = existing["feedback"]
            elif isinstance(existing, dict):
                raise FeedbackWriteRejected(
                    409, "feedback.json 是不含 feedback 列表的 JSON object，"
                         "拒绝修改；请先归档或手工合并该文件后重试")
            else:
                entries = []
                corrupt = True
                isolate_reason = "为合法 JSON 标量（既非列表也非对象形态）"
        except (OSError, ValueError, RecursionError):
            entries = []
            corrupt = True
        note: str | None = None
        if not mutate(entries):
            # 损坏文件即使 mutate 未命中（GET 读侧空变更 / 删除重编辑未
            # 命中）也要先隔离再返回：否则损坏会被误判为「零批注/未命中」
            # 且无提示，直到下一次成功写盘才隔离——与 append 口径不一致
            if corrupt:
                note = isolate_corrupt_feedback(target, isolate_reason)
            return "missing", note
        if doc is not None:
            doc["feedback"] = entries
            payload: dict | list = doc
        else:
            payload = entries
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if len(text.encode("utf-8")) > MAX_FEEDBACK_FILE_BYTES:
            raise FeedbackWriteRejected(
                507, f"feedback.json 超过 {MAX_FEEDBACK_FILE_BYTES}B 总量上限，"
                     "拒绝写入；请归档历史批注后重试")
        if corrupt:
            note = isolate_corrupt_feedback(target, isolate_reason)
        try:
            atomic_write_text(target, text)
        except OSError as exc:
            raise FeedbackWriteRejected(
                500, f"feedback.json 写入失败：{exc}") from exc
    return "ok", note


def load_feedback(proto_dir: Path) -> tuple[list, str | None]:
    """读批注列表并惰性补发 id（历史无 id 条目迁移即落盘）。

    返回 (entries, note)。文件缺失 → ([], None)（GET 不建目录不落盘）；
    损坏 → 隔离 .bak 后按空列表起步（与 append 口径一致，note 带提示）。
    """
    def assign(entries: list) -> bool:
        changed = False
        for entry in entries:
            if isinstance(entry, dict) and not entry.get("id"):
                entry["id"] = new_feedback_id()
                changed = True
        return changed

    result, note = _mutate_feedback(proto_dir, assign)
    from core.dashboard.prototype_io import FEEDBACK_FILE_NAME
    target = Path(proto_dir) / FEEDBACK_FILE_NAME
    # "missing" 有三义：文件真缺失（GET 静默空列表，note 为 None）；文件
    # 在但无需补 id（mutate 未变更）——文件就在磁盘上，必须照常读取，
    # 不得吞成空列表；损坏文件已隔离改名（note 带提示）——文件不在了，
    # 返回空列表但必须把 note 带出去（GET 响应转 warning），不得静默。
    if not target.is_file():
        return [], note
    # mutate 后重读成本远低于把 entries 快照穿出锁外：迁移路径文件刚由本
    # 函数回写，直接再读一次拿到带 id 的最终形态（也覆盖 dict 形态嵌套）
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return [], note
    if isinstance(existing, list):
        return existing, note
    if isinstance(existing, dict) and isinstance(existing.get("feedback"), list):
        return existing["feedback"], note
    return [], note


def update_feedback_text(proto_dir: Path, fb_id: str, text: str) -> dict | None:
    """按 id 重写批注文本（重编辑）；返回被改条目，未命中/文件缺失返回 None。

    只动 text 并补 ``edited`` 时间戳；anchor/round/element 等既有字段保持
    （批注锚点不因改文案而漂移）。
    """
    from datetime import datetime as _dt, timezone as _tz

    found: dict | None = None

    def rewrite(entries: list) -> bool:
        nonlocal found
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == fb_id:
                entry["text"] = text
                entry["edited"] = _dt.now(_tz.utc).isoformat(timespec="seconds")
                found = entry
                return True
        return False

    _mutate_feedback(proto_dir, rewrite)
    return found


def delete_feedback(proto_dir: Path, fb_id: str) -> bool:
    """按 id 删除单条批注；删除成功返回 True，未命中/文件缺失返回 False。"""
    def drop(entries: list) -> bool:
        for i, entry in enumerate(entries):
            if isinstance(entry, dict) and entry.get("id") == fb_id:
                del entries[i]
                return True
        return False

    result, _note = _mutate_feedback(proto_dir, drop)
    return result == "ok"
