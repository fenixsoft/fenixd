"""core.dashboard.data.signature — GET 读端点数据源签名（条件请求通道）。

add-dashboard-paging-and-etag 1.1：ETag = 数据源签名哈希（design D1）——
对响应实际依赖的数据源做 ``(mtime_ns, size)`` 签名组合哈希，签名计算只
stat 不读文件内容，成本显著低于响应体序列化。

失效键纪律（与 ``_config_file_sig`` / ``SummaryIndex`` 同款）：stat 每次
现算——把 stat 本身跨请求 memo 化（仅以 path 为键）会在「写后立刻读」窗口
吐出陈旧签名，造成 spec 明令禁止的假 304。因此本模块的 memo 只做两类
**安全**缓存：

1. ``file_sig`` 的可选 memo：单次签名计算内的路径去重（同一轮里重复引用
   的路径只 stat 一次），缓存随本轮计算即弃；
2. ``combine`` 的树哈希 memo：键即完整签名集的 repr（部件内已含路径）——
   命中校验本身仍需全量 stat，memo 只省去对同一签名集的重复哈希，有界
   （LRU 式清空）。
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

# ── 树哈希 memo（键即完整签名集的 repr，安全缓存见模块 docstring） ──

_HASH_MEMO_CAP = 512
_HASH_MEMO: dict = {}
_HASH_MEMO_LOCK = threading.Lock()


def file_sig(path, memo: dict | None = None) -> tuple | None:
    """文件签名 ``(mtime_ns, size)``；缺失/不可 stat 返回 None。

    memo（可选）：**单次签名计算内**的去重缓存，键含 path——同一轮里同一路径
    （如目录树与显式源重叠）只 stat 一次。跨请求复用必须走「以签名为键」的
    缓存模式（SummaryIndex 同款），本函数不做跨请求 memo（假 304 禁令，
    见模块 docstring）。
    """
    key = str(path)
    if memo is not None and key in memo:
        return memo[key]
    try:
        st = os.stat(path)
    except OSError:
        sig = None
    else:
        sig = (st.st_mtime_ns, st.st_size)
    if memo is not None:
        memo[key] = sig
    return sig


def tree_sigs(root, memo: dict | None = None, skip_dirs: frozenset = frozenset()) -> tuple:
    """目录树内全部文件的签名集 ``((相对路径, mtime_ns, size), ...)``，按相对路径排序。

    根缺失/不可读返回空元组（缺位本身参与哈希：目录出现/消失即翻签名）。
    只 stat 不读内容；符号链接不入集（conservative，宁多勿漏的对偶面：
    少入签名只会造成多余的 200，不会造成假 304）。

    skip_dirs：按目录名跳过的子树（任意深度）。用于排除**读路径派生缓存**
    （如 log_index 的 ``.idx/`` offsets 文件——它在首次时间轴读取时由服务端
    自身物化，不是时间轴数据源；不排除会让详情 ETag 在首个请求后必然翻转
    一次，纯 200 浪费）。
    """
    root = Path(root)
    out: list = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in skip_dirs:
                                stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            sig = file_sig(entry.path, memo)
                            if sig is not None:
                                out.append(
                                    (str(Path(entry.path).relative_to(root)), sig[0], sig[1])
                                )
                    except OSError:
                        continue
        except OSError:
            continue
    out.sort()
    return tuple(out)


def _combine_uncached(parts) -> str:
    h = hashlib.sha256()
    h.update(repr(list(parts)).encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def combine(parts) -> str:
    """把签名部件（str/int/tuple/None 的稳定嵌套结构）组合为 sha256 十六进制串。

    树哈希结果 memo：键即完整部件集的 repr（部件内已含路径）——命中校验
    本身仍需上游全量 stat，memo 只省重复哈希；超界整体清空（有界，量级 KB）。
    """
    key = repr(list(parts))
    with _HASH_MEMO_LOCK:
        cached = _HASH_MEMO.get(key)
        if cached is not None:
            return cached
    digest = _combine_uncached(parts)
    with _HASH_MEMO_LOCK:
        if len(_HASH_MEMO) > _HASH_MEMO_CAP:
            _HASH_MEMO.clear()
        _HASH_MEMO[key] = digest
    return digest


def data_signature(proot, sources) -> str:
    """单项目数据源组合签名。

    Args:
        proot: 项目根（用于把源路径归一为相对路径参与哈希，非根下的源按
            绝对路径参与）。
        sources: 文件/目录路径序列。目录源取整树文件签名集（含子目录），
            文件源取单文件签名；缺失源记 None 哨兵（出现/消失即翻签名）。
    """
    root = Path(proot)
    memo: dict = {}
    parts = []
    for src in sources:
        p = Path(src)
        try:
            rel = str(p.relative_to(root))
        except ValueError:
            rel = str(p)
        if p.is_dir():
            parts.append((rel, tree_sigs(p, memo)))
        else:
            parts.append((rel, file_sig(p, memo)))
    return combine(parts)


def project_signature(proot) -> str:
    """项目级读路径共依赖源的基础签名（宁多勿漏）。

    覆盖 STATE.md、归档清单、spec/changes 树、runs 树（tree_sigs 递归含
    archive/）、项目级与用户级 config.yaml（预算解析兜底依赖）。
    """
    import core.dashboard.data as _facade

    proot = Path(proot)
    return data_signature(
        proot,
        [
            proot / ".fenix" / "STATE.md",
            proot / ".fenix" / "STATE.archive.md",
            proot / "spec" / "changes",
            proot / ".fenix" / "runs",
            proot / ".fenix" / "config.yaml",
            _facade.USER_CONFIG_PATH,
        ],
    )


def admin_alerts_signature(proot) -> str:
    """项目 admin_alerts.json 签名（/api/alerts、/api/admin-activities 数据源）。"""
    proot = Path(proot)
    return data_signature(proot, [proot / ".fenix" / "admin_alerts.json"])


def admin_alerts_archive_signature(proot) -> str:
    """项目 admin_alerts_archive.jsonl 签名（/api/admin-activities?archived=1 数据源）。"""
    proot = Path(proot)
    return data_signature(proot, [proot / ".fenix" / "admin_alerts_archive.jsonl"])


def config_signature(project_root=None) -> str:
    """config 读端点签名：用户级 config.yaml（+ 项目级，?project= 变体时）。"""
    import core.dashboard.data as _facade

    sources = [_facade.USER_CONFIG_PATH]
    if project_root is not None:
        proot = Path(project_root)
        sources.append(proot / ".fenix" / "config.yaml")
    return data_signature(proot if project_root is not None else Path.home(), sources)


def spec_detail_signature(proot, spec: str) -> str:
    """/api/specs/<spec> 详情签名（spec spec 基线表 + 宁多勿漏）。

    覆盖：STATE.md（条目）、本 spec 目录树（docs/specs/verification-report/
    .spec.yaml）、verify-progress 本 spec 产物（report.json/scenarios/
    screenshots/quality-gates/code-review）与 <spec>.json、共享
    .fenix-run-result.json（run-result 兜底读取的两路候选之一）、admin_alerts
    （时间轴 admin 事件）、.fenix/logs 树（时间轴日志源）、本 spec 命名的
    runs 产物（含归档；仅本 spec——他 spec 的新 run 不翻转本详情）、归档目录
    中本 spec 的副本树（resolve_spec_dir 归档回退）、两级 config（时间轴
    billing 配置依赖）。
    """
    from .summary import _runs_by_spec_sigs

    proot = Path(proot)
    sources = [
        proot / ".fenix" / "STATE.md",
        proot / "spec" / "changes" / spec,
        proot / ".fenix" / "verify-progress" / f"{spec}.json",
        proot / ".fenix" / "verify-progress" / spec,
        proot / ".fenix" / ".fenix-run-result.json",
        proot / ".fenix" / "admin_alerts.json",
        proot / ".fenix" / "config.yaml",
    ]
    parts = [
        data_signature(proot, sources),
        # logs 树单独签名并排除 .idx 派生缓存（log_index 读时物化的 offsets
        # 文件，非时间轴数据源——见 tree_sigs skip_dirs 注记）
        ("logs", tree_sigs(proot / ".fenix" / "logs", skip_dirs=frozenset({".idx"}))),
    ]
    # 本 spec 命名的 run 产物（含 archive/，_runs_by_spec_sigs 一并扫描）
    runs = _runs_by_spec_sigs(proot).get(spec) or {}
    parts.append(sorted((str(p), s[0], s[1]) for p, s in runs.items()))
    # 归档目录回退（resolve_spec_dir 同口径：目录名 == spec 或 spec- 前缀）
    arc = []
    try:
        for d in (proot / "spec" / "archive").iterdir():
            if d.is_dir() and (d.name == spec or d.name.startswith(f"{spec}-")):
                arc.append((d.name, tree_sigs(d)))
    except OSError:
        pass
    parts.append(sorted(arc, key=lambda x: x[0]))
    return combine(parts)


def data_signature_all(project_roots) -> str:
    """多项目组合签名（跨项目聚合响应的基础哈希输入）。

    每项目取 project_signature；项目根清单本身（顺序 + 集合）参与哈希——
    项目增删/路径变化即翻签名。
    """
    parts = []
    for proot in project_roots:
        parts.append((str(proot), project_signature(proot)))
    return combine(parts)


def registry_signature(registry) -> str:
    """registry 配置源签名（项目清单参与聚合端点的响应形状）。"""
    path = getattr(registry, "config_path", None)
    sig = file_sig(path) if path is not None else None
    return combine(("registry", str(path), sig))
