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

# ── 标准库与依赖导入（D3 patch 缝隙：subprocess/time 必须暴露在包命名空间） ──

import os
import shutil
import signal
import subprocess
import threading
import time

from pathlib import Path
from typing import Optional, Set, Dict

from core.proc_utils import is_claude_process
from core.wip_checkpoint import collapse_wip_commits
from core.agent_runner.run_files import run_spec_part
from core.worktree_manager.artifact_paths import ArtifactPathMatcher

# 历史导入路径兼容（verify-process-lifecycle D4：判定上移至 core.proc_utils，
# 避免 v2_dev_server 等模块 import 本模块造成循环依赖）。
_is_claude_process = is_claude_process

# ── 常量定义（design D1：8 常量，门面 re-export） ─────────────────────────────

# ── 锁治理（improve-run-lifecycle-governance D4）─────────────────────────────
# 锁是内存集合 _spec_locks，daemon 重启即丢失；同时 attempt/resume 的孤儿子进程
# 却可能在进程表中继续存活。两类场景都以「真实进程表」为唯一真相：
#   - 在册锁扫描不到匹配进程、且对应 run 流文件停止增长超过该窗口 → 陈锁，回收
#   - 无在册锁但进程表存在指向该 spec worktree 的存活进程 → 视为仍持锁
STALE_LOCK_IDLE_SECONDS = 120
# 恢复重派遗产宽限期（add-recovery-legacy-check D2）：跟随孤儿清扫周期的同族常量，
# 不引入独立定时器。遗产注册后若后继 run 迟迟未 merge（如全链冷却），宽限期超时由
# 清扫器兜底回收。与 STALE_LOCK_IDLE_SECONDS 同族，语义上即「孤儿清扫一轮能扫到的
# 最大陈态窗口」，遗产在此窗口内保留、超时即视为无人收编而回收。
LEGACY_GRACE_SECONDS = STALE_LOCK_IDLE_SECONDS
# has_active_worktree 在派发热路径被高频调用，pgrep 每次数十毫秒；对同一 spec
# 的进程表扫描做短缓存，避免派发风暴。缓存窗口内的进程消失/出现误差可接受。
PROCESS_SCAN_CACHE_SECONDS = 5.0
# pre-dispatch autostash 条目的消息前缀（fix-autostash-orphans）：周期巡检按此
# 识别「框架自己 stash 的条目」——人工手工 stash 的条目不带此前缀，永不自动回收。
AUTOSTASH_MSG_PREFIX = "fenix: pre-dispatch autostash"
# merge-back 前 WIP 重叠闸门收纳条目的消息前缀（evo-merge-back-wip-overlap-gate
# D1）：MUST NOT 包含 AUTOSTASH_MSG_PREFIX 子串——reclaim_stale_autostash 以
# 子串匹配栈顶并 pop（stash_guard.py），复用同前缀会让「故意保留待人工找回」的
# 闸门条目被 60s 巡检抢走并沿用丢弃策略，去向记录随即失真。
WIP_GATE_STASH_PREFIX = "fenix: wip-overlap gate stash"

# dashboard 静态根（相对项目根）：构建产物目录（dist/、v3/dist/ 等层级变体）
# 都在其下。产物冲突判定按目录层次容错——写死单一路径前缀会在主树重命名产物
# 目录（如 v3/dist→dist，add-dashboard-incremental-data 事故）后，把冲突
# rename 双胞胎的旧路径误判为语义冲突，自愈静默跳过。
DASHBOARD_STATIC_ROOT = "core/dashboard/static/"

# ── worktree 可用性三态（interrupt-recovery-preserve D5）────────────────────
# is_available 的返回值：以 git 为真相（git worktree list + rev-parse --verify），
# 不信任内存表（daemon 重启即失）。recovery 保留判定、resume 派发、复用认领
# 三条链路共用同一查询，禁止各链路自行拼装目录/分支判断。
WT_AVAILABLE = "available"  # 分支可解析 + 目录在场 + git worktree 注册有效 → 原地可用
WT_REBUILDABLE = "rebuildable"  # 分支可解析但目录缺失/未注册 → 可在既有分支上重建
WT_UNAVAILABLE = "unavailable"  # 分支不可解析（已并入/已清扫/typo）→ 不可用，调用方降级


def _is_build_artifact_path(path: str) -> bool:
    """构建产物路径判定：static 根下任一层级 dist 目录内的文件。

    「默认判定」别名（evo-merge-back-wip-artifact-scope D1）：判定语义从全局
    常量改为实例状态（``ArtifactPathMatcher``，见 `core/worktree_manager/
    artifact_paths.py`），本函数委托默认实例的判定，签名与返回值语义逐字节
    不变——既有引用（`tests/test_characterization_giant_classes.py` 等）零改动。
    """
    return ArtifactPathMatcher().is_artifact(path)


# ── 数据类（design D1：types.py 原样保留，此处 re-export） ──────────────────

from core.worktree_manager.types import MergeConflictInfo  # noqa: E402


# ── 子模块 mixins（refactor-giant-classes 逐组摘出；常量已在上方定义，
#    子模块经本包命名空间解析常量，无循环） ─────────────────────────────────

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
      - Implementer: .claude/worktrees/<spec>-<timestamp>/ on branch fenix/<spec>
      - Verifier:    .claude/worktrees/verify-<spec>-<timestamp>/ on branch fenix/verify-<spec>

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
    # 前缀硬编码 "fenix/" 与分支创建端同源（create() :223/:226），不读配置——
    # worktree.implement_branch_prefix 仅 engine._resolve_push_branch 读取、
    # 非创建端事实源（design D1「前缀来源」，非 fenix 配置下按配置枚举会
    # 扫空命名空间、豁免静默失效）。
    PENDING_MERGE_BRANCH_PREFIX = "fenix/"
