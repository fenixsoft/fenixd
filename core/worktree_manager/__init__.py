"""
worktree_manager — Git worktree lifecycle management.

拆分自原 `core/worktree_manager.py`（refactor-giant-classes D2），
原文件改为子包，本 `__init__.py` 同时承担**宿主**与**门面**两职：
- 宿主：`WorktreeManager` 类定义于此（组合 G1-G9 mixin，design D5 约定）；
- 门面：re-export 全部公开名（类、常量、函数），既有 import 路径不变。

同时暴露 `subprocess`、`time` 等模块级名到包命名空间，确保
`patch("core.worktree_manager.subprocess.run")` 等字符串路径 patch
（design D3）继续生效——调用点经包命名空间延迟解析。
"""

# ── 标准库与依赖导入（D3 patch 缝隙：必须暴露在包命名空间，供
#    `patch("core.worktree_manager.subprocess.run")` 等字符串路径 patch；
#    os/shutil/signal/threading 同为缝隙名，勿按未引用清理） ──

import os  # noqa: F401
import shutil  # noqa: F401
import signal  # noqa: F401
import subprocess  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401

from pathlib import Path

from core.proc_utils import is_claude_process
from core.wip_checkpoint import collapse_wip_commits
from core.agent_runner.run_files import run_spec_part
from core.worktree_manager.artifact_paths import ArtifactPathMatcher

# 历史导入路径兼容（verify-process-lifecycle D4：判定上移至 core.proc_utils，
# 避免 v2_dev_server 等模块 import 本模块造成循环依赖）。
_is_claude_process = is_claude_process

# ── 常量（design D1）：单源定义于 constants.py（code-review abf55539cf18：
#    子模块改从 constants 导入，消除「常量定义须先于子模块导入」的隐式顺序）；
#    此处 re-export 门面，既有 `from core.worktree_manager import X` 路径不变。

from core.worktree_manager.constants import (  # noqa: F401, E402
    AUTOSTASH_MSG_PREFIX,
    DASHBOARD_STATIC_ROOT,
    LEGACY_GRACE_SECONDS,
    PROCESS_SCAN_CACHE_SECONDS,
    STALE_LOCK_IDLE_SECONDS,
    WT_AVAILABLE,
    WT_REBUILDABLE,
    WT_UNAVAILABLE,
    WIP_GATE_STASH_PREFIX,
)


# ── 数据类（design D1：types.py 原样保留，此处 re-export） ──────────────────

from core.worktree_manager.types import MergeConflictInfo  # noqa: E402


# ── 子模块 mixins（refactor-giant-classes 逐组摘出）──────────────────────────
# 常量单源在 constants.py：子模块直接从 constants 导入，不再依赖「本包常量
# 定义先于子模块导入」的顺序——原注释声称「无循环」实为被定义顺序化解的
# 循环导入（code-review abf55539cf18）。子模块仍经本包命名空间解析的名
# （如上方 _is_claude_process 别名）必须在本块导入语句之前定义，这是仅存的
# 顺序约束，新增包级符号供子模块引用时须遵守。

from core.worktree_manager import dist_conflicts, legacy_registry, lifecycle, locks  # noqa: F401, E402
from core.worktree_manager import mergeback, queries, repair_site, stale_sweep, stash_guard  # noqa: F401, E402
from core.worktree_manager.dist_conflicts import G5DistConflictsMixin  # noqa: F401, E402
from core.worktree_manager.legacy_registry import G2LegacyRegistryMixin  # noqa: F401, E402
from core.worktree_manager.lifecycle import G1LifecycleMixin  # noqa: F401, E402
from core.worktree_manager.locks import G3LockMixin  # noqa: F401, E402
from core.worktree_manager.mergeback import G4MergebackMixin  # noqa: F401, E402
from core.worktree_manager.queries import G8QueryMixin  # noqa: F401, E402
from core.worktree_manager.repair_site import G9RepairSiteMixin  # noqa: F401, E402
from core.worktree_manager.stale_sweep import G7StaleSweepMixin  # noqa: F401, E402
from core.worktree_manager.stash_guard import G6StashGuardMixin  # noqa: F401, E402


class WorktreeManager(
    G4MergebackMixin,
    G5DistConflictsMixin,
    G6StashGuardMixin,
    G7StaleSweepMixin,
    G1LifecycleMixin,
    G2LegacyRegistryMixin,
    G3LockMixin,
    G8QueryMixin,
    G9RepairSiteMixin,
):
    """
    Manage git worktree lifecycle for Agent isolation.

    Each Agent run gets its own worktree:
      - Implementer: .claude/worktrees/impl-<spec>-<timestamp>/ on branch fenix/<spec>-<timestamp>
      - Verifier:    .claude/worktrees/verify-<spec>-<timestamp>/ on branch fenix/verify-<spec>-<timestamp>

    目录名前缀词表以 queries._WT_NAME_PREFIXES 为单源（impl/verify/repair/judge；
    code-review item 946ca55e8466：原文档命名滞后于 lifecycle.create 的 _names
    实际产出，按文档形态检索 worktree 目录会落空）。

    类为薄门面：全部方法按职责分布在各组 mixin（design D1 分组表），
    此处仅保留类级状态（design D3）与文档。
    """

    # merge-tree 预演闸（add-merge-tree-rehearsal D4）：`git merge-tree --write-tree`
    # 需 git ≥ 2.38，进程内一次性探测（类级缓存，多实例共享，不重复探测/不刷屏）。
    _rehearsal_probe_done = False
    _rehearsal_supported = False

    # ── 待合并分支信号（evo-recovery-watch-transition-guard D1）──────────────
    # recovery watch 判定 stale 前的过渡窗口豁免依据：「该 spec 存在未并入
    # main 的实现分支」= 过渡窗口内（implementer 成功收工 → merge-back 完成）。
    # 判据 = 归属该 spec 的实现分支存在未并入 main 的提交（rev-list > 0），
    # **不是**分支存在性——仓库 1014 条 fenix/* 历史分支中 933 条已并入 main，
    # 存在性判据会把已合并分支也算作待合并，永久抑制真实 stale 检出。
    # 前缀硬编码 "fenix/" 与分支创建端同源（lifecycle.G1LifecycleMixin.create
    # 内 _names 闭包的分支名拼装，code-review item ded13afb19bb：拆包后失效
    # 行号引用改方法级定位），不读配置——
    # worktree.implement_branch_prefix 仅 engine._resolve_push_branch 读取、
    # 非创建端事实源（design D1「前缀来源」，非 fenix 配置下按配置枚举会
    # 扫空命名空间、豁免静默失效）。
    PENDING_MERGE_BRANCH_PREFIX = "fenix/"
