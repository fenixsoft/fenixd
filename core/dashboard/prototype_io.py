"""prototype_io.py — fenix-prototype 原型伺服的批注落盘单源。

fenix-prototype skill 原 ``serve_prototype.py`` 独立 HTTP 服务器退役后
（add-proto-dashboard-serving），原型静态伺服与批注落盘改由 dashboard
常驻进程承载：``GET /proto/...`` 静态服务在 static_routes，批注 HTTP 出口
为 ``POST /api/proto/<project>/<spec>/feedback``，落盘即本模块
``append_feedback`` 的唯一调用方。

写入语义与退役服务器逐条对齐（spec/knowledge 1.3
prototype-annotation-loop 的稳健性要求）：

- 读-改-写持线程锁 + 跨进程 flock（伴生 ``.lock`` 文件）串行，并发 POST
  不丢批注；目标文件经 tmp 原子 replace 换名，锁落在伴生文件而非目标本身；
- 既有 list 形态与 ``{"feedback": [...]}`` dict 形态（annotator.js 本地导出）
  均保留结构追加，round 等同级字段不丢；
- 原文件损坏/不可读：改名隔离为 ``.bak``（带时间戳 + 进程/线程唯一后缀），
  隔离提示随响应 ``warning`` 字段回流，不静默覆盖丢历史；
- dict 但无 feedback 列表的 JSON object（手工整理形态）拒绝写入（409），
  不按空数组起步整体覆盖；
- 总量上限 8MB（``MAX_FEEDBACK_FILE_BYTES``）超限拒绝（507），防无界增长。

与退役服务器的刻意差异：请求体大小不再走本模块——dashboard H0 底座
``_read_json_body`` 统一按 ``MAX_POST_BODY``（256KB）收口，单条批注远小于
该上限；``spec_segment_safe`` 是截图路由同口径的路径段安全校验单源。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from pathlib import Path

from core.fs_utils import flock_exclusive, flock_release

FEEDBACK_FILE_NAME = "feedback.json"
MAX_FEEDBACK_FILE_BYTES = 8 << 20  # 8MB：feedback.json 总量上限，超限拒绝写入

# /proto/ 静态通道的后缀白名单（static_routes._serve_prototype 消费）：
# 原型单文件 HTML 及其合法伴生资源（样式/脚本/图片/字体/数据）。清单外
# 后缀一律 404——原型目录不该出现可执行/源码/密钥类文件，即便被手工放
# 进来也不经本通道外泄（语义同截图路由的 ALLOWED_IMAGE_EXT）。
PROTOTYPE_FILE_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}

# 跨请求共享的批注写入锁：dashboard 每 连接 新建 handler 实例，实例级锁
# 没有跨连接互斥；保留独立服务器的全局线程锁 + 跨进程 flock 两级串行
# （跨进程级在本模块导出，手工/脚本写方也可复用同锁避免互踩）。
_FEEDBACK_LOCK = threading.Lock()


class FeedbackWriteRejected(Exception):
    """批注写入被拒绝（status = 建议回给客户端的 HTTP 状态码）。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def spec_segment_safe(raw: str) -> bool:
    """URL 解码后的单段路径安全校验（与 _serve_screenshot 同口径单源）。

    拒绝空段 / 「.」「..」组件 / 解码后还原出的「..」组件 / 绝对路径段 /
    NUL 字节（%00 解码产物会让 Path.resolve 抛 ValueError 穿透为 500）。
    """
    norm = raw.replace("\\", "/")
    return (
        bool(norm)
        and norm not in (".", "..")
        and ".." not in norm.split("/")
        and not norm.startswith("/")
        and "\x00" not in raw
    )


@contextlib.contextmanager
def feedback_file_lock(target: Path):
    """feedback.json 读改写的跨进程互斥：独占 flock 伴生锁文件 ``<名>.lock``。

    锁落在伴生文件而非 feedback.json 本身：目标文件经 tmp 原子 replace 换名，
    inode 随每次写入变化，锁旧 inode 保护不了新文件。平台分发收敛至
    core/platform 单点（无 fcntl 的 Windows 分支属 SPEC-2 pal 后端职责）；
    锁文件创建/加锁失败时降级为仅进程内互斥（历史行为），不让写入崩溃。
    """
    lock_path = target.with_name(target.name + ".lock")
    fd: int | None = None
    try:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
            flock_exclusive(fd)
        except OSError as exc:
            print(f"feedback-lock-unavailable: 跨进程锁不可用（{exc}），"
                  "降级为仅进程内互斥", file=sys.stderr)
            yield
            return
        try:
            yield
        finally:
            flock_release(fd)
    finally:
        if fd is not None:
            os.close(fd)


def _isolate_corrupt_feedback(target: Path) -> str | None:
    """把损坏/不可读的 feedback.json 改名隔离为 .bak，返回客户端提示。

    隔离动作本身失败不阻塞新批注写入：降级为 stderr 提示并返回 None。
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # 隔离名带进程/线程唯一标识：时间戳秒级粒度内两次隔离也不重名覆盖
    backup = target.with_name(
        f"{target.name}.corrupt-{stamp}."
        f"{os.getpid()}.{threading.get_ident()}.bak")
    try:
        target.replace(backup)
    except OSError as exc:
        print(f"feedback-corrupt-isolate-failed: 无法隔离损坏的 "
              f"{target.name}（{exc}），原内容将被新批注数组覆盖",
              file=sys.stderr)
        return None
    return (f"原 {FEEDBACK_FILE_NAME} 无法解析（疑似损坏），"
            f"已隔离为 {backup.name}；请手工检查恢复其中的历史批注")


def append_feedback(proto_dir: Path, annotation: dict) -> tuple[Path, str | None]:
    """追加一条批注进 ``<proto_dir>/feedback.json``（锁内读改写，保留结构）。

    返回 (落盘路径, 非致命提示)；提示非 None 时随响应告知客户端（如原文件
    损坏已被隔离为 .bak）。结构不可并入 / 超总量上限 / 写盘失败抛
    FeedbackWriteRejected，status 字段为建议 HTTP 状态码。
    """
    target = proto_dir / FEEDBACK_FILE_NAME
    # 入口校验单源（HTTP 层不重复）：批注必须是含非空 anchor/text 的 object，
    # 与退役独立服务器的 400 语义一致
    if not isinstance(annotation, dict):
        raise FeedbackWriteRejected(400, "批注必须是 JSON object")
    if not isinstance(annotation.get("anchor"), str) \
            or not annotation["anchor"].strip() \
            or not isinstance(annotation.get("text"), str) \
            or not annotation["text"].strip():
        raise FeedbackWriteRejected(400, "批注必须包含非空 anchor 与 text 字段")
    # 先取跨进程文件锁再取线程锁：读-改-写必须在进程间也串行（手工编辑、
    # 并行脚本写方），否则后写覆盖前写丢批注
    with feedback_file_lock(target), _FEEDBACK_LOCK:
        entries: list = []
        doc: dict | None = None  # dict 形态（如 annotator.js 本地导出）整体保留
        corrupt = False  # 原文件损坏/不可读：覆盖前先改名隔离，防丢可恢复历史
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    entries = existing
                elif isinstance(existing, dict) and isinstance(existing.get("feedback"), list):
                    doc = existing
                    entries = existing["feedback"]
                elif isinstance(existing, dict):
                    # dict 但无 feedback 列表（手工整理等其他合法 JSON object）：
                    # 无法安全并入，拒绝写入而非按空数组起步整体覆盖丢历史。
                    raise FeedbackWriteRejected(
                        409, "feedback.json 是不含 feedback 列表的 JSON object，"
                             "拒绝追加；请先归档或手工合并该文件后重试")
            except (OSError, ValueError):
                # 非法 JSON（ValueError）或读取失败（OSError）：文件里可能
                # 仍有手工可恢复的批注历史，不能当空文件整体覆盖——标记待
                # 隔离，写入前先改名 .bak（见 _isolate_corrupt_feedback）。
                entries = []
                corrupt = True
        entries.append(annotation)
        if doc is not None:
            # dict 形态保留原结构整体回写，round 等同级字段不丢
            doc["feedback"] = entries
            payload: dict | list = doc
        else:
            payload = entries  # 裸 list 形态按现有逻辑回写数组
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if len(text.encode("utf-8")) > MAX_FEEDBACK_FILE_BYTES:
            # 文件无界增长会占满磁盘：超总量上限拒绝写入，提示归档
            raise FeedbackWriteRejected(
                507, f"feedback.json 超过 {MAX_FEEDBACK_FILE_BYTES}B 总量上限，"
                     "拒绝写入；请归档历史批注后重试")
        note: str | None = None
        if corrupt:
            # 放在所有拒绝路径之后：仅在实际即将覆盖原文件时才动它
            note = _isolate_corrupt_feedback(target)
        # tmp 文件名带进程/线程唯一后缀：并发写各用各的 tmp，避免内容交错
        tmp = target.with_name(
            f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(target)
        except OSError as exc:
            # 写盘失败（磁盘满/目录只读/目标被占用等）：尽力清理残留 tmp
            # 后转 FeedbackWriteRejected，交调用方走结构化错误通道回包。
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise FeedbackWriteRejected(
                500, f"feedback.json 写入失败：{exc}") from exc
    return target, note
