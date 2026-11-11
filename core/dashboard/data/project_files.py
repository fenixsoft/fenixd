"""project_files.py — 项目文件浏览数据模块（add-project-home-tab）。

项目首页页签三通道（目录列表 / 文件内容 / 文件下载）的数据逻辑单源：
- 文件集合：``git ls-files --cached --others --exclude-standard``（cwd=项目根）
  全集 + ``.git/index`` mtime 进程内缓存（30s TTL 兜底），天然排除
  gitignored（node_modules / dist / .fenix）与 ``.git``；
- 忽略项通道（2026-11-11 增强）：``git ls-files --others --ignored
  --exclude-standard --directory``（全忽略目录折叠为 ``dir/`` 单条，sub-second）
  + 30s TTL 进程内缓存，为目录列表补 ``hidden`` 条目（灰色字体呈现）；
  ``.git`` 不在此通道输出；
- 目录条目：在集合上做前缀分组构建（目录条目 = 集合内存在该前缀下文件的
  去重目录名），目录先行、名称不分大小写升序；忽略项子项按同名归并
  （全忽略目录为目录条目、忽略文件为文件条目，标 ``hidden: true``）；
- git 属性：每条目单飞 ``git log -1``（目录条目传目录路径，git 自动取目录
  下最近提交；忽略项路径无提交 → null）；整仓最近提交与分支名仅根目录查询附带；
- 内容通道：256 KiB 截断、前 8 KiB 含 NUL 判二进制、README 判定链。

安全约束：``resolve_relative`` 是全部通道共用的 containment 单点
（URL 解码后的 relpath → resolve → is_relative_to 校验），越界/绝对路径/
``..`` / ``.git`` 内路径一律抛 ``PathEscape``，由路由层转 400 泛化文案。
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger("fenixd.dashboard.data.project_files")

# 目录条目数上限（design D3）：超出截断，响应附 truncated_count
MAX_DIR_ENTRIES = 200
# 文本内容截断上限（bytes，design D2）
CONTENT_LIMIT_BYTES = 256 * 1024
# 二进制判定窗口：前 8 KiB 含 NUL 字节 → binary（design D4）
BINARY_SNIFF_BYTES = 8192
# 子进程超时（秒）：ls-files 在大仓也是亚秒级，15s 已是极宽上界
_GIT_TIMEOUT_SECONDS = 15

# 下载分块大小（design D4）
DOWNLOAD_CHUNK_BYTES = 64 * 1024

# 图片内联通道（project-home-tab 增强 2026-11-10）：扩展名 → Content-Type
# 白名单。raw 通道（_api_project_files_raw）仅服务此集合，供前端 <img>
# 直显；svg 因可内嵌 <script> 由路由层追加 CSP sandbox 防线。
IMAGE_INLINE_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
}


def image_content_type(abs_path: Path) -> str | None:
    """按扩展名（不分大小写）返回图片 Content-Type；非白名单返回 None。"""
    return IMAGE_INLINE_TYPES.get(abs_path.suffix.lower())


class PathEscape(Exception):
    """路径越界（绝对路径 / ``..`` / symlink 逃逸 / ``.git`` 内路径）。

    路由层捕获后统一回 400 泛化文案（响应体不含内部路径细节）。
    """


# ── git 子进程底座 ────────────────────────────────────────────────────

def _git_run(root: Path, args: list[str]) -> subprocess.CompletedProcess:
    """在项目根执行只读 git 命令（显式 UTF-8 解码，同 architecture_routes
    ``_repo_head`` 先例：text=True 缺省按 locale 解码，LC_ALL=C 环境下非
    ASCII 提交信息会 UnicodeDecodeError）。"""
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_TIMEOUT_SECONDS,
    )


def _inside_work_tree(root: Path) -> bool:
    """``git rev-parse --is-inside-work-tree`` 复核（任务 1.1）：命令失败
    / 空输出歧义时区分「非 git 目录」与「git 仓但集合查询异常」。"""
    try:
        proc = _git_run(root, ["rev-parse", "--is-inside-work-tree"])
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and (proc.stdout or "").strip() == "true"


# ── 文件集合单源（任务 1.1）──────────────────────────────────────────

# 进程内缓存：{root_str: (index_mtime | None, cached_at, files)}。
# `.git/index` mtime 变化即失效（提交/暂存必翻 mtime），mtime 缺席（空仓
# 无 index、裸布局异常）时靠 TTL 窗口兜底。ThreadingHTTPServer 多工作线程
# 并发读，最坏竞态是多算一次子进程（写覆盖为等值集合），无正确性风险。
_LS_FILES_CACHE_TTL = 30.0
_LS_FILES_CACHE: dict[str, tuple[float | None, float, list[str]]] = {}
_LS_FILES_CACHE_LOCK = threading.Lock()


def _index_mtime(root: Path) -> float | None:
    try:
        return (root / ".git" / "index").stat().st_mtime
    except OSError:
        return None


def visible_files(root: Path) -> list[str] | None:
    """git 可见文件集合全集（仓库根相对路径列表）。

    非 git 目录（git 命令不可用 / 不在工作树内）返回 ``None``——调用方
    据此置 ``non_git`` 标记。空仓（init 无提交）返回空列表而非 None：
    ``ls-files`` 正常成功、``--others`` 仍可列出未跟踪文件，属 git 项目。
    """
    key = str(root)
    mtime = _index_mtime(root)
    now = time.monotonic()
    with _LS_FILES_CACHE_LOCK:
        hit = _LS_FILES_CACHE.get(key)
        if hit is not None:
            cached_mtime, cached_at, cached_files = hit
            fresh = now - cached_at < _LS_FILES_CACHE_TTL
            same_rev = mtime is not None and cached_mtime == mtime
            both_stale = mtime is None and cached_mtime is None
            if fresh and (same_rev or both_stale):
                return cached_files

    try:
        proc = _git_run(
            root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        )
    except (OSError, subprocess.SubprocessError):
        proc = None
    if proc is None or proc.returncode != 0:
        # 空输出/失败歧义复核（任务 1.1）：仍在工作树内视为 git 仓（暂无
        # 可见文件），复核失败判非 git
        return [] if _inside_work_tree(root) else None

    # -z：NUL 分隔的原始路径（不分行）——缺省按行输出会对非 ASCII 路径启用
    # core.quotePath 八进制引号形态（"\350\257\264.md"），集合整体失真
    files = [line for line in (proc.stdout or "").split("\x00") if line]
    with _LS_FILES_CACHE_LOCK:
        _LS_FILES_CACHE[key] = (mtime, time.monotonic(), files)
    return files


# ── 忽略项通道（2026-11-11 增强：目录列表 hidden 条目）───────────────

# 忽略项缓存 TTL（秒）：.gitignore 变化与新增未跟踪文件不挪 .git/index
# mtime，mtime 失效判据对此通道无效，退化为纯 TTL（30s 内的滞后对浏览
# 视图无害，与 visible_files 同量级）。
_IGNORED_CACHE_TTL = 30.0
_IGNORED_CACHE: dict[str, tuple[float, list[str]]] = {}
_IGNORED_CACHE_LOCK = threading.Lock()


def ignored_entries(root: Path) -> list[str] | None:
    """git 忽略项全集（仓库根相对路径；``--directory`` 折叠形态）。

    ``git ls-files --others --ignored --exclude-standard --directory``：
    全忽略目录折叠为 ``dir/`` 单条（尾斜杠标记）、忽略文件按实际路径逐条
    输出；``.git`` 永不出现。非 git 目录或命令失败返回 ``None``——调用方
    据此跳过 hidden 合并（主列表不受影响，忽略项是增强非依赖）。
    """
    key = str(root)
    now = time.monotonic()
    with _IGNORED_CACHE_LOCK:
        hit = _IGNORED_CACHE.get(key)
        if hit is not None and now - hit[0] < _IGNORED_CACHE_TTL:
            return hit[1]

    try:
        proc = _git_run(
            root,
            ["ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory"],
        )
    except (OSError, subprocess.SubprocessError):
        proc = None
    if proc is None or proc.returncode != 0:
        return None
    # -z 同 visible_files：禁用 core.quotePath 八进制引号形态
    entries = [line for line in (proc.stdout or "").split("\x00") if line]
    with _IGNORED_CACHE_LOCK:
        _IGNORED_CACHE[key] = (time.monotonic(), entries)
    return entries


def ignored_children(entries: list[str], rel_dir: str) -> list[str]:
    """在忽略项全集上提取 rel_dir 直接子项名（纯函数，可独立单测）。

    返回名字列表：全忽略目录带尾斜杠（``node_modules/``）、忽略文件为裸名。
    去重 + 名称不分大小写升序。根目录（rel_dir 空串）取全集首段。
    """
    prefix = f"{rel_dir}/" if rel_dir else ""
    children: set[str] = set()
    for entry in entries:
        if prefix:
            if not entry.startswith(prefix):
                continue
            rest = entry[len(prefix):]
        else:
            rest = entry
        if not rest:
            continue
        slash = rest.find("/")
        if slash >= 0:
            children.add(rest[:slash] + "/")
        else:
            children.add(rest)
    return sorted(children, key=str.lower)


def ignored_entries_scoped(root: Path, rel_dir: str) -> list[str] | None:
    """纯忽略目录的下一层扫描（2026-11-11）。

    根级流经 ``--directory`` 折叠后，被整目录忽略的深层内容不可见
    （如 ``node_modules/`` 折叠后拿不到 ``pkg/``）——导航进入这类目录时按
    目录 scope（pathspec ``<rel_dir>/*``）再扫一层。注意 scope 扫描不能带
    ``--directory``：git 对整体忽略的目录恒折叠为 ``dir/`` 单条，pathspec
    指到目录内部也无效；去掉该旗标后输出递归文件明细，交
    ``ignored_children`` 取直接子项（深层目录自然归并为 ``child/``）。
    输出为仓库根相对路径。同 ``ignored_entries`` 走纯 TTL 缓存（键带
    rel_dir）；失败返回 None 静默跳过。
    """
    key = f"{root}::{rel_dir}"
    now = time.monotonic()
    with _IGNORED_CACHE_LOCK:
        hit = _IGNORED_CACHE.get(key)
        if hit is not None and now - hit[0] < _IGNORED_CACHE_TTL:
            return hit[1]

    try:
        proc = _git_run(
            root,
            ["ls-files", "-z", "--others", "--ignored", "--exclude-standard",
             "--", f"{rel_dir}/*"],
        )
    except (OSError, subprocess.SubprocessError):
        proc = None
    if proc is None or proc.returncode != 0:
        return None
    entries = [line for line in (proc.stdout or "").split("\x00") if line]
    with _IGNORED_CACHE_LOCK:
        _IGNORED_CACHE[key] = (time.monotonic(), entries)
    return entries


# ── 路径安全（任务 1.2）──────────────────────────────────────────────

def resolve_relative(root: Path, relpath: str) -> Path:
    """containment 单点：relpath（HTTP 层 parse_qs 已完成 URL 解码——路由
    表下发的 query 值是解码后形态，此处 MUST NOT 二次 unquote，否则文件名
    真含 ``%2F`` 的合法场景被误拆）解析为项目根内的绝对路径。

    - 绝对路径（POSIX ``/`` 或 Windows 盘符形态）直接拒绝；
    - ``Path.resolve()`` 消化 ``..`` 与 symlink 后仍须位于项目根内
      （is_relative_to），越界抛 ``PathEscape``；
    - ``.git`` 全链路排除：解析后落在 ``<root>/.git`` 内（含 ``.git`` 本身，
      worktree 布局下它是文件同样命中相等分支）抛 ``PathEscape``。
    """
    if not relpath:
        return root.resolve()
    if relpath.startswith("/") or relpath.startswith("\\"):
        raise PathEscape("absolute path")
    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / relpath).resolve()
    except OSError as exc:
        raise PathEscape(f"unresolvable path: {type(exc).__name__}") from exc
    if not candidate.is_relative_to(resolved_root):
        raise PathEscape("escapes project root")
    git_dir = resolved_root / ".git"
    if candidate == git_dir or git_dir in candidate.parents:
        raise PathEscape(".git path")
    return candidate


def is_known_path(files: list[str], rel_dir: str) -> bool:
    """list 通道集合校验（任务 1.2 双保险）：rel_dir 必须是集合内的文件
    或某条目路径的前缀目录。根目录（空串）恒真。"""
    if rel_dir == "":
        return True
    prefix = rel_dir + "/"
    return any(f == rel_dir or f.startswith(prefix) for f in files)


# ── 目录条目构建（任务 1.1）──────────────────────────────────────────

def build_entries(
    files: list[str], rel_dir: str, hidden_names: list[str] | None = None
) -> tuple[list[dict], int]:
    """在文件集合上做前缀分组，构建目录条目列表。

    目录条目 = 集合内存在该前缀下文件的去重首段目录名；目录先行、同类型
    名称不分大小写升序。``hidden_names``（ignored_children 产物，目录带
    尾斜杠）按名归并进同序：同名已可见（部分忽略的混合目录等）以可见
    为准不标 hidden；纯忽略目录/文件为 ``hidden: true`` 条目。超出
    ``MAX_DIR_ENTRIES`` 截断（目录优先列），返回 ``(entries, truncated_count)``。
    """
    prefix = f"{rel_dir}/" if rel_dir else ""
    dir_names: set[str] = set()
    file_names: list[str] = []
    for f in files:
        if prefix:
            if not f.startswith(prefix):
                continue
            rest = f[len(prefix):]
        else:
            rest = f
        if not rest:
            continue
        slash = rest.find("/")
        if slash >= 0:
            dir_names.add(rest[:slash])
        else:
            file_names.append(rest)

    # 忽略项归并（2026-11-11 增强）：同名可见优先（混合目录不标灰），纯
    # 忽略项补入对应类目。
    hidden_set: set[str] = set()
    for name in hidden_names or []:
        is_dir = name.endswith("/")
        plain = name[:-1] if is_dir else name
        if plain in dir_names or plain in file_names:
            continue  # 同名可见（混合内容目录）：保持可见形态，不标 hidden
        if is_dir:
            dir_names.add(plain)
        else:
            file_names.append(plain)
        hidden_set.add(plain)

    dirs_sorted = sorted(dir_names, key=str.lower)
    files_sorted = sorted(file_names, key=str.lower)
    ordered = dirs_sorted + files_sorted
    total = len(ordered)
    truncated = max(0, total - MAX_DIR_ENTRIES)
    if truncated:
        ordered = ordered[:MAX_DIR_ENTRIES]
    dir_boundary = len(dirs_sorted)
    entries = [
        {
            "name": name,
            "dir": i < dir_boundary,
            "hidden": name in hidden_set,
            "last_commit": None,
        }
        for i, name in enumerate(ordered)
    ]
    return entries, truncated


# ── git 属性（任务 1.3）──────────────────────────────────────────────

# git log --format 的 \x1f（Unit Separator）字段分隔符
_US = "\x1f"


def _run_git_log(root: Path, fmt: str, path: str | None = None) -> str | None:
    """``git log -1 --format=<fmt>``（path 在场时以 ``-- <path>`` 限定
    pathspec；整仓查询（latest_commit）不带 path——``-- HEAD`` 会把 HEAD
    当 pathspec 致查询恒空）。"""
    args = ["log", "-1", f"--format={fmt}"]
    if path is not None:
        args += ["--", path]
    try:
        proc = _git_run(root, args)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    line = (proc.stdout or "").strip()
    return line or None


def entry_commit(root: Path, rel_path: str) -> dict | None:
    """单条目最近提交（任务 1.3 单飞 ``git log -1``；目录条目传目录路径，
    git 自动取该目录下最近一次提交）。无提交历史/命令失败 → None。"""
    line = _run_git_log(root, f"%h{_US}%s{_US}%aI", rel_path)
    if line is None:
        return None
    parts = line.split(_US, 2)
    if len(parts) < 3:
        return None
    return {"hash": parts[0], "message": parts[1], "time": parts[2]}


def latest_commit(root: Path) -> dict | None:
    """整仓最近一次提交（任务 1.3，仅根目录查询附带）。"""
    line = _run_git_log(root, f"%an{_US}%h{_US}%aI")
    if line is None:
        return None
    parts = line.split(_US, 2)
    if len(parts) < 3:
        return None
    return {"author": parts[0], "hash": parts[1], "time": parts[2]}


def branch_name(root: Path) -> str | None:
    """当前分支名（任务 1.3）：``git rev-parse --abbrev-ref HEAD``；
    detached HEAD（输出字面 ``HEAD``）回退短 hash。空仓（无 HEAD）→ None。"""
    try:
        proc = _git_run(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    name = (proc.stdout or "").strip()
    if name != "HEAD":
        return name or None
    try:
        short = _git_run(root, ["rev-parse", "--short", "HEAD"])
    except (OSError, subprocess.SubprocessError):
        return None
    if short.returncode != 0:
        return None
    return (short.stdout or "").strip() or None


# ── 内容通道与 README（任务 1.4）─────────────────────────────────────

def readme_name(files: list[str]) -> str | None:
    """README 判定链（任务 1.4）：README.md → readme.md，按 git 可见集合
    判定（与列表边界一致——gitignored README 不在列表也不渲染盒）。
    仅根目录查询时由调用方附带。"""
    for cand in ("README.md", "readme.md"):
        if cand in files:
            return cand
    return None


def file_content(abs_path: Path) -> dict:
    """内容通道（任务 1.4）：文本读至 256 KiB 截断（truncated 标记 +
    行数/字节数）；二进制（前 8 KiB 含 NUL）置 ``binary=true`` 不带 content。

    调用方（路由层）已保证 abs_path 存在且为文件；读取竞态（并发删除）
    的 OSError 上抛由路由层转 404。bytes 字段恒为 stat 实值（截断时也是
    文件总字节数，前端「N 行 · x KB」按实值展示）。
    """
    size = abs_path.stat().st_size
    with abs_path.open("rb") as f:
        head = f.read(BINARY_SNIFF_BYTES)
    if b"\x00" in head:
        return {
            "content": None, "lines": 0, "bytes": size,
            "truncated": False, "binary": True,
        }
    with abs_path.open("rb") as f:
        raw = f.read(CONTENT_LIMIT_BYTES + 1)
    truncated = len(raw) > CONTENT_LIMIT_BYTES
    if truncated:
        raw = raw[:CONTENT_LIMIT_BYTES]
    text = raw.decode("utf-8", errors="replace")
    return {
        "content": text,
        "lines": len(text.splitlines()),
        "bytes": size,
        "truncated": truncated,
        "binary": False,
    }


# ── list 通道组装 ─────────────────────────────────────────────────────

def list_directory(root: Path, rel_dir: str) -> dict:
    """目录列表响应体（design D2 契约）：``{branch, latest, entries,
    readme, non_git}``（+ 可选 ``truncated_count``）。

    非 git 项目：``non_git=true``、entries 空、branch/latest/readme 全
    null。latest/readme 仅根目录查询（rel_dir 为空串）附带。文件条目附
    ``bytes``（os.stat 实际大小；目录/读取失败为 None——目录尺寸需递归
    汇总，前端以「目录」文案呈现，不做伪尺寸）。每条目附 ``hidden``
    （2026-11-11 增强）：纯忽略目录/文件为 true（前端灰色字体），同名
    可见条目恒 false；忽略项通道失败时静默跳过合并（主列表不受影响）。
    """
    files = visible_files(root)
    if files is None:
        return {
            "branch": None, "latest": None, "entries": [],
            "readme": None, "non_git": True,
        }
    is_root = rel_dir == ""
    ignored = ignored_entries(root)
    hidden_children = ignored_children(ignored, rel_dir) if ignored is not None else []
    if not hidden_children and rel_dir and not any(
        f.startswith(f"{rel_dir}/") for f in files
    ):
        # 纯忽略目录（不在可见集合）：根级流已折叠拿不到深层子项，
        # 按目录 scope 再扫一层（2026-11-11）
        scoped = ignored_entries_scoped(root, rel_dir)
        if scoped is not None:
            hidden_children = ignored_children(scoped, rel_dir)
    entries, truncated = build_entries(files, rel_dir, hidden_children)
    for entry in entries:
        entry["last_commit"] = entry_commit(
            root, f"{rel_dir}/{entry['name']}" if rel_dir else entry["name"]
        )
        if entry["dir"]:
            entry["bytes"] = None
        else:
            abs_path = root / rel_dir / entry["name"] if rel_dir else root / entry["name"]
            try:
                entry["bytes"] = abs_path.stat().st_size
            except OSError:
                entry["bytes"] = None
    payload: dict = {
        "branch": branch_name(root),
        "latest": latest_commit(root) if is_root else None,
        "entries": entries,
        "readme": readme_name(files) if is_root else None,
        "non_git": False,
    }
    if truncated:
        payload["truncated_count"] = truncated
    return payload
