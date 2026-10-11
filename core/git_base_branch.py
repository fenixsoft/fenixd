"""core.git_base_branch — 共享基线分支解析器（evo-fix-resume-base-branch-portability D1）。

框架所有「分支相对基线的未合并提交数」类判定的基线来源单点。解析顺序：

1. ``git symbolic-ref --short refs/remotes/origin/HEAD``（``origin/<branch>``
   形态，去前缀取本地分支名并 ``rev-parse --verify`` 校验本地存在，缺失则
   落入下述候选，兼容含 ``/`` 的分支名）；
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
- 探测**成功**的结果按 ``str(project_root)`` 进程内缓存（探测一次）；
  测试可经 :func:`reset_cache` 显式清空。落到 fallback 的失败结果
  **不写缓存**：瞬时故障（git 暂不可用/超时/IO 抖动）在下一次闸门
  判定时重新探测自愈，不会把错误基线钉死到进程生命周期。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# 全部探测失败时的回退常量（与 fenixd.PRESERVE_AHEAD_BASE_BRANCH 同值）。
FALLBACK_BASE_BRANCH = "main"
# git 子进程统一超时（秒）。
DEFAULT_TIMEOUT_SECONDS = 15.0

# 进程内缓存（仅存探测成功的结果；reset_cache() 供测试清空）。
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
        探测成功的结果按 ``str(project_root)`` 缓存；回退 ``fallback``
        的失败结果不缓存，下次调用重新探测（瞬时故障可自愈）。
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
        # origin/HEAD 只保证符号引用可解析，不保证去前缀后的分支在本地
        # 可解析（remote 默认分支改名后未建本地分支、单分支 fetch 配置等
        # 环境下 refs/heads/<name> 缺失）：与下方 main/master 候选同法
        # rev-parse --verify 校验本地存在，失败继续走候选与 fallback——
        # 调用方拿裸分支名拼 rev-list，DWIM 解析不到 refs/remotes/origin/
        # <name>，返回本地不存在的基线即 potplayer-base 同型事故。
        if name and _git_output(
            project_root, ["rev-parse", "--verify", "--quiet", name], timeout,
        ) is not None:
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
        # 全部探测失败（git 暂不可用/超时/IO 抖动等瞬时故障）：仅本次回退
        # fallback，MUST NOT 写缓存——否则一次启动期抖动即把错误基线钉死
        # 到进程生命周期（重启前无法自愈，potplayer-base 同类事故的隐蔽
        # 变体）。失败期间每次闸门判定重探：快失败路径（非 git 目录/
        # 非零退出/OSError）毫秒级零成本，仅 git 真挂起时最坏 3×timeout；
        # 调用方均为逐次闸门/恢复判定、无轮询热路径压力（见模块
        # docstring），不值得为此引入负缓存退避。
        return fallback
    _cache[key] = branch
    return branch
