"""core.git_base_branch — 共享基线分支解析器（evo-fix-resume-base-branch-portability D1）。

框架所有「分支相对基线的未合并提交数」类判定的基线来源单点。解析顺序：

1. ``git symbolic-ref --short refs/remotes/origin/HEAD``（``origin/<branch>``
   形态，去前缀取本地分支名，兼容含 ``/`` 的分支名）；
2. 本地存在 ``main``（``git rev-parse --verify --quiet main``，退出码判定）；
3. 本地存在 ``master``（同法）；
4. 回退常量 ``"main"``（与既有 PRESERVE_AHEAD_BASE_BRANCH 一致）。

决策来源（design Context / tasks 1.1）：fenixd.py ``_preserve_base_branch``
（code-review item ec528621b2ec）已示范 origin/HEAD 符号引用探测，但其无
remote 时回退常量，对本仓库形态（master 主干、无 main、无 remote）依然失效；
2026-10-02 potplayer-base 事故中 state_machine/worktree_manager 等 core 闸门
硬编码 ``main..<branch>``，rev-list 恒 128 退出，已提交的 WIP 检查点被判
「三处锚点均不可得」清空重建，25 分钟在途工作灭失。本模块即上述口径的单点
收敛：core 侧闸门（state_machine / worktree_manager.queries / agent_runner）
MUST 经此处取基线，MUST NOT 各自硬编码或反向 import fenixd（会成环）。

契约（design D2/D3）：

- 吞掉 TimeoutExpired/OSError/ValueError 回退常量，**不向调用方抛异常、
  无 None 返回语义**；调用点的 fail-closed/fail-open 由替换后的 git 查询
  （rev-list 等）自身维持，本模块不改变任何闸门方向。
- 子进程统一带 timeout（缺省 15s，与 PRESERVE_AHEAD_COUNT_TIMEOUT_SECONDS
  口径一致）；恢复路径为启动一次性调用，无热路径压力。
- 结果按 ``str(project_root)`` 进程内缓存（探测一次）；测试可经
  :func:`reset_cache` 显式清空。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# 全部探测失败时的回退常量（与 fenixd.PRESERVE_AHEAD_BASE_BRANCH 同值）。
FALLBACK_BASE_BRANCH = "main"
# git 子进程统一超时（秒）。
DEFAULT_TIMEOUT_SECONDS = 15.0

# 进程内缓存（按 project_root 探测一次；reset_cache() 供测试清空）。
_cache: dict = {}


def reset_cache() -> None:
    """清空进程内缓存（测试隔离用；生产路径无需调用）。"""
    _cache.clear()


def _git_output(project_root, args: list, timeout: float) -> str | None:
    """跑一次只读 git 查询，成功返回 stdout 剥边，失败/超时返回 None。"""
    try:
        res = subprocess.run(
            ["git", "-C", str(project_root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if res.returncode != 0:
        return None
    return (res.stdout or "").strip()


def resolve_base_branch(
    project_root, timeout: float = DEFAULT_TIMEOUT_SECONDS,
    fallback: str = FALLBACK_BASE_BRANCH,
) -> str:
    """解析仓库基线分支；全部探测失败回退 ``fallback``（缺省 "main"）。

    Args:
        project_root: 仓库根目录（Path 或 str）。
        timeout: 单条 git 子进程超时（秒）。
        fallback: 全部探测失败（非 git 目录/超时/OSError）时的回退常量。
            调用方有自有兜底常量时传入（如 fenixd 的
            PRESERVE_AHEAD_BASE_BRANCH），缺省与全局口径一致。

    Returns:
        基线分支名（恒为非空 str，无 None 语义——见模块 docstring 契约）。
    """
    key = str(project_root)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    branch: str | None = None
    # 1) origin/HEAD 符号引用优先（与远端默认分支一致；fenixd
    #    _preserve_base_branch 同口径）。
    ref = _git_output(
        project_root,
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        timeout,
    )
    if ref and ref.startswith("origin/"):
        name = ref[len("origin/"):].strip()
        if name:
            branch = name
    # 2)/3) 本地 main → master（--verify --quiet 退出码判定，一次子进程）。
    if branch is None:
        for cand in ("main", "master"):
            if _git_output(
                project_root, ["rev-parse", "--verify", "--quiet", cand], timeout,
            ) is not None:
                branch = cand
                break
    if branch is None:
        branch = fallback
    _cache[key] = branch
    return branch
