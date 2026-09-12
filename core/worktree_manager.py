"""
worktree_manager.py — Git worktree lifecycle management.

Creates, tracks, and cleans up isolated git worktrees for Agent runs.
Ensures parallel Agents don't conflict.
"""

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

# 历史导入路径兼容（verify-process-lifecycle D4：判定上移至 core.proc_utils，
# 避免 v2_dev_server 等模块 import 本模块造成循环依赖）。
_is_claude_process = is_claude_process

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

# dashboard 静态根（相对项目根）：构建产物目录（dist/、v3/dist/ 等层级变体）
# 都在其下。产物冲突判定按目录层次容错——写死单一路径前缀会在主树重命名产物
# 目录（如 v3/dist→dist，add-dashboard-incremental-data 事故）后，把冲突
# rename 双胞胎的旧路径误判为语义冲突，自愈静默跳过。
DASHBOARD_STATIC_ROOT = "core/dashboard/static/"

# ── worktree 可用性三态（interrupt-recovery-preserve D5）────────────────────
# is_available 的返回值：以 git 为真相（git worktree list + rev-parse --verify），
# 不信任内存表（daemon 重启即失）。recovery 保留判定、resume 派发、复用认领
# 三条链路共用同一查询，禁止各链路自行拼装目录/分支判断。
WT_AVAILABLE = "available"      # 分支可解析 + 目录在场 + git worktree 注册有效 → 原地可用
WT_REBUILDABLE = "rebuildable"  # 分支可解析但目录缺失/未注册 → 可在既有分支上重建
WT_UNAVAILABLE = "unavailable"  # 分支不可解析（已并入/已清扫/typo）→ 不可用，调用方降级


def _is_build_artifact_path(path: str) -> bool:
    """构建产物路径判定：static 根下任一层级 dist 目录内的文件。"""
    if not path.startswith(DASHBOARD_STATIC_ROOT):
        return False
    parts = path[len(DASHBOARD_STATIC_ROOT):].split("/")
    return len(parts) >= 2 and "dist" in parts[:-1]


class MergeConflictInfo:
    """merge-back 返回值：兼容 ``(bool, str)`` 元组解包的结构化冲突分类。

    add-merge-back-repair-lane D1「git 层判定、调度层决策」：worktree_manager
    保持纯 git 操作层，merge-back 失败时在返回值里附带结构化冲突分类（冲突
    路径清单 + 是否仍有语义冲突），**是否进入 repair 通道由调度层决策**。

    既有调用方 ``success, err = merge_back_from_branch(...)`` 照常解包
    （``__iter__`` 按 ``(success, error)`` 顺序产出）；调度层可读取结构化
    字段（``conflict_paths`` / ``has_semantic_conflict``）判断是否派发
    repair agent。
    """

    __slots__ = (
        "success", "error", "conflict_paths",
        "self_heal_applicable", "self_heal_succeeded", "has_semantic_conflict",
        "rehearsed", "wip_overlap",
    )

    def __init__(self, success: bool, error: str,
                 conflict_paths: list | None = None,
                 self_heal_applicable: bool = False,
                 self_heal_succeeded: bool = False,
                 has_semantic_conflict: bool = False,
                 rehearsed: bool = False,
                 wip_overlap: list | None = None):
        self.success = bool(success)
        self.error = error
        self.conflict_paths = list(conflict_paths or [])
        self.self_heal_applicable = self_heal_applicable
        self.self_heal_succeeded = self_heal_succeeded
        self.has_semantic_conflict = has_semantic_conflict
        self.rehearsed = bool(rehearsed)
        # WIP 重叠预检（fix-mergeback-stashpop-silent-loss D3）：主树脏 tracked
        # 文件与分支改动文件的交集，空列表 = 无重叠。只预警不阻断。
        self.wip_overlap = list(wip_overlap or [])

    def __iter__(self):
        """兼容 (bool, str) 解包：既有调用方 ``success, err = ...`` 照常工作。"""
        yield self.success
        yield self.error

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        return (
            f"MergeConflictInfo(success={self.success}, error={self.error!r}, "
            f"conflict_paths={self.conflict_paths}, "
            f"self_heal={self.self_heal_applicable}/{self.self_heal_succeeded}, "
            f"semantic={self.has_semantic_conflict}, rehearsed={self.rehearsed}, "
            f"wip_overlap={self.wip_overlap})"
        )


class WorktreeManager:
    """
    Manage git worktree lifecycle for Agent isolation.

    Each Agent run gets its own worktree:
      - Implementer: .claude/worktrees/<spec>-<timestamp>/ on branch fenix/<spec>
      - Verifier:    .claude/worktrees/verify-<spec>-<timestamp>/ on branch fenix/verify-<spec>
    """

    # merge-tree 预演闸（add-merge-tree-rehearsal D4）：`git merge-tree --write-tree`
    # 需 git ≥ 2.38，进程内一次性探测（类级缓存，多实例共享，不重复探测/不刷屏）。
    _rehearsal_probe_done = False
    _rehearsal_supported = False

    def __init__(self, base_dir: Path, project_root: Path, logger, process_scanner=None):
        self.base_dir = Path(base_dir)
        self.project_root = Path(project_root)
        self.logger = logger
        self._active_worktrees: Set[str] = set()
        self._wt_branches: Dict[str, str] = {}  # wt_path -> branch name
        self._spec_locks: Set[str] = set()  # SPECs currently being worked on
        # 锁龄登记（双派发穿透原地修 2026-09-06）：key -> 拿锁时刻。run 流文件由
        # attempt 子进程启动后才创建，而锁在 create() 内即持有（worktree add + seed +
        # node_modules 供给实测可达十几秒）——「无进程且无流文件」无法区分 create
        # 构建中与孤儿死锁，陈锁判定按锁龄豁免构建窗口（见 _lock_young）。
        self._lock_since: Dict[str, float] = {}
        # 锁治理（D4）：进程表扫描函数，默认 pgrep 实现；测试可注入替身。
        # 签名 (spec_name) -> bool，表示进程表中是否存在指向该 spec worktree 的进程。
        self._process_scanner = process_scanner or self._pgrep_spec_process
        self._proc_scan_cache: Dict[str, tuple] = {}  # spec -> (expires_at, alive)
        # 恢复重派遗产（add-recovery-legacy-check D1）：死亡 run 的 worktree 与分支
        # 注册为 spec 的遗产，保留至「后继 run 成功 merge」或「宽限期超时」二者先到。
        # 内存态，不持久化（与锁同策略，daemon 重启后遗产按孤儿清扫兜底）。覆盖式
        # 更新：同一 spec 多次死亡只留最新一份（D5 避免遗产链膨胀）。
        # 结构：{spec_name: {"path": str, "branch": str, "registered_at": float,
        #                     "dirty": bool, "worktree_name": str}}
        self._legacy: Dict[str, dict] = {}
        # worktree 继承（fast-track 打回重派复用）：本轮 run 已认领的复用 worktree
        # （take 时从 _legacy 摘出，防 sweeper 宽限期误回收在用目录）。prompt 构建
        # 据此注入「继承说明」。结构：{spec_name: {"path": str, "branch": str}}
        self._active_reuse: Dict[str, dict] = {}
        # 主树 merge-clean guard 串行锁（fix-autostash-orphans）：stash→merge→pop
        # 是必须原子完成的段——并发 worker 若各自独立 stash/pop，会与共享的 stash
        # 栈发生 LIFO 错配（A 恢复出 B 刚 stash 的内容）。
        self._main_tree_lock = threading.Lock()
        # spec 锁原子化（fix-restart-dual-dispatch S2）：create 的 check-then-add
        # 必须原子完成——2026-09-03 事故中两个并发 create 都通过了入口检查，同秒
        # 同名分支 fatal 后失败路径 discard 掉了胜出者刚 add 的同一把锁，第二梯队
        # 换名重试成功 → 两个 claude 并行跑同一 spec。
        self._spec_lock_th = threading.Lock()
        # 最近一次 guard 段内 stash pop 冲突自愈丢弃的文件清单（dispatch 层读走
        # 做 admin 告警后失效）；guard 进入时清空。
        self.last_stash_pop_conflicts: list = []
        # 最近一次 pop 冲突自愈后 stash 条目去向（fix-mergeback-stashpop-silent-loss
        # D1/D2）：{"kept": bool, "sha": str}——kept=False 表示已被自动 drop（sha
        # 可 gc 前找回），kept=True 表示条目保留。dispatch 层读走并入告警文本。
        self.last_stash_entry_fate: dict = {"kept": True, "sha": ""}

    def create(self, spec_name: str, agent_type: str = "implementer") -> Optional[Path]:
        """
        Create a git worktree for an Agent run.

        Args:
            spec_name: The SPEC name (e.g., "add-user-login")
            agent_type: "implementer" or "verifier"

        Returns: Path to the worktree, or None on failure.
        """
        # Prevent duplicate worktrees for the same SPEC+agent_type
        #（fix-restart-dual-dispatch S2：check-then-add 原子化，见 __init__ 注释）
        lock_key = f"{spec_name}:{agent_type}"
        with self._spec_lock_th:
            if lock_key in self._spec_locks:
                self.logger.warning(
                    "worktree_manager",
                    f"Worktree already active for {lock_key}",
                )
                return None
            self._spec_locks.add(lock_key)
            self._lock_since[lock_key] = time.time()

        # worktree 继承（fast-track 打回重派 / fix-provider-transient-backoff D3：
        # transient 终态保留的全 agent_type 遗产）：优先认领上一轮保留的复用遗产，
        # 在同一目录同一分支上继续（继承已提交成果与未提交现场），不再从零新建。
        if agent_type in ("fast-track", "implementer", "planner-plan",
                          "planner-judge", "verifier"):
            reuse = self._take_reusable_worktree(spec_name)
            if reuse is not None:
                wt_path, branch = reuse
                self._active_worktrees.add(str(wt_path))
                self._wt_branches[str(wt_path)] = branch
                self.logger.info(
                    "worktree_manager",
                    f"Reusing inherited worktree for '{spec_name}': "
                    f"{wt_path} (branch {branch})",
                )
                return wt_path
            # 无可复用遗产 → 清除上一轮的认领痕迹（prompt 注入以实际为准）
            self._active_reuse.pop(spec_name, None)

        # Determine branch name — include timestamp to avoid collisions on re-verification
        timestamp = int(time.time())
        if agent_type == "verifier":
            branch = f"fenix/verify-{spec_name}-{timestamp}"
            prefix = "verify"
        else:
            branch = f"fenix/{spec_name}-{timestamp}"
            prefix = "impl"

        # Ensure unique worktree directory
        wt_name = f"{prefix}-{spec_name}-{timestamp}"
        wt_path = self.base_dir / wt_name

        self.base_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.logger.info(
                "worktree_manager",
                f"Creating worktree: {wt_path} on branch {branch}",
            )

            # Create worktree
            result = subprocess.run(
                [
                    "git", "-C", str(self.project_root),
                    "worktree", "add",
                    "-b", branch,
                    str(wt_path),
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                self.logger.error(
                    "worktree_manager",
                    f"Failed to create worktree: {result.stderr}",
                )
                with self._spec_lock_th:
                    self._spec_locks.discard(lock_key)
                return None

            self._active_worktrees.add(str(wt_path))
            self._wt_branches[str(wt_path)] = branch

            # Seed SPEC files for implementer and fast-track worktrees
            if agent_type in ("implementer", "fast-track"):
                self._seed_spec(spec_name, wt_path)

            # worktree 构建环境供给（deps_mode 双模式，best-effort 不阻塞派发）：
            # git 不携带 node_modules，实现者每轮手工安装是既有摩擦源（fast-track 复盘）
            try:
                from core.verify_contract import (
                    load_verify_contract, provision_worktree_node_modules,
                    read_config_deps_mode, resolve_deps_mode)
                contract = load_verify_contract(self.project_root)
                sub_dirs = sorted({(s.cwd or ".") for s in contract.prepare}) \
                    if contract else []
                if sub_dirs:
                    provision_worktree_node_modules(
                        wt_path, self.project_root, sub_dirs,
                        mode=resolve_deps_mode(
                            contract, read_config_deps_mode(self.project_root)),
                        logger=self.logger,
                    )
            except Exception as e:
                self.logger.warning(
                    "worktree_manager", f"worktree node_modules 供给跳过: {e}")

            self.logger.info("worktree_manager", f"Worktree created: {wt_path}")
            return wt_path

        except subprocess.TimeoutExpired:
            self.logger.error("worktree_manager", "Worktree creation timed out")
            with self._spec_lock_th:
                self._spec_locks.discard(lock_key)
            return None
        except Exception as e:
            self.logger.error("worktree_manager", f"Worktree creation error: {e}")
            with self._spec_lock_th:
                self._spec_locks.discard(lock_key)
            return None

    def has_active_lock(self, spec_name: str, agent_type: str = "implementer") -> bool:
        """查询该 spec+agent_type 是否有活跃的 worktree 锁（fix-restart-dual-dispatch）。

        供 dispatch 派发前与 agent_runner attempt 重试前判定「是否已有另一 run
        在跑」——锁活跃即并行风险，调用方应放弃派发/重试，而不是换名再造一个
        worktree 形成并行 run（2026-09-03 双派发事故的第二梯队成因）。
        """
        return f"{spec_name}:{agent_type}" in self._spec_locks

    def _seed_spec(self, spec_name: str, wt_path: Path):
        """Seed SPEC source files into a new worktree.

        If spec/changes/<spec>/ exists in the main worktree but not in the
        new worktree (the branch HEAD doesn't contain it), copy the directory
        into the worktree and commit it to the isolated branch.

        Failures are logged but never block — the implementer falls back to
        the main repository path.
        """
        try:
            main_spec_dir = self.project_root / "spec" / "changes" / spec_name
            wt_spec_dir = wt_path / "spec" / "changes" / spec_name

            if not main_spec_dir.is_dir():
                return
            if wt_spec_dir.is_dir():
                return

            self.logger.info(
                "worktree_manager",
                f"Seeding SPEC '{spec_name}' into worktree",
            )

            # Copy the entire SPEC directory
            wt_spec_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(main_spec_dir), str(wt_spec_dir))

            # Git add + commit in the worktree
            result = subprocess.run(
                ["git", "-C", str(wt_path), "add", "spec/changes/"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"git add failed during seeding: {result.stderr}",
                )
                return

            result = subprocess.run(
                [
                    "git", "-C", str(wt_path),
                    "commit", "-m", f"[fenix] spec: {spec_name}",
                ],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"git commit failed during seeding: {result.stderr}",
                )
                return

            self.logger.info(
                "worktree_manager",
                f"SPEC '{spec_name}' seeded and committed in worktree",
            )
        except Exception as e:
            self.logger.warning(
                "worktree_manager",
                f"SPEC seeding failed (non-fatal): {e}",
            )

    def ensure_spec_committed(self, spec_name: str) -> bool:
        """派发 implementer 前把 spec 目录提交进主树（fix-merge-back-deadlock 根因修复）。

        spec 目录（spec/changes/<spec>/）若在主树 untracked，而 worktree 分支里
        _seed_spec 已 commit 一份同名路径，merge-back 时 git 会拒绝「untracked working
        tree files would be overwritten by merge」。在派发前把 spec 提交进主树使其被跟踪，
        分支从新 HEAD 建即可直接包含 spec（_seed_spec 跳过），merge 变为干净三方合并。

        Returns: True 表示已提交或本已无改动（干净）；False 表示提交失败。
        """
        rel = f"spec/changes/{spec_name}"
        try:
            status = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain", "--", rel],
                capture_output=True, text=True, timeout=30,
            )
            if status.returncode != 0:
                return False
            if not status.stdout.strip():
                return True  # 本已 tracked + clean，无需提交

            add = subprocess.run(
                ["git", "-C", str(self.project_root), "add", "--", rel],
                capture_output=True, text=True, timeout=30,
            )
            if add.returncode != 0:
                return False

            commit = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "commit", "-m", f"[fenix] spec: {spec_name}"],
                capture_output=True, text=True, timeout=30,
            )
            if commit.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"SPEC commit failed: {commit.stderr.strip() or commit.stdout.strip()}",
                )
                return False
            self.logger.info("worktree_manager", f"Committed SPEC '{spec_name}' into main tree")
            return True
        except subprocess.TimeoutExpired:
            return False

    def _backup_untracked_spec_files(self, branch: str):
        """merge 前把与 implementer 分支新增路径冲突的主树 untracked 文件移到 .fenix/merge-backup/ 备份。

        泛化原 spec/changes 限定逻辑（fix-merge-untracked-guard）：

        1. `git diff --name-only --diff-filter=A HEAD...<branch>` 取分支**新增**文件路径集合
           —— untracked 冲突只会发生在新增路径上（修改既有 tracked 文件不与 untracked 冲突）。
        2. 对每条新增路径，判断主树中该路径上的文件是否为 untracked：
           `git ls-files --error-unmatch <path>` 失败（未被 index 跟踪）即视为 untracked。
        3. 将命中的文件移入 `.fenix/merge-backup/<epoch秒>/`（保持仓库相对路径结构）。

        检测范围不限于 spec/changes/，覆盖任意产物路径（如 core/dashboard/static/v2/）。
        集合为空、或交集为空时返回 None 且不创建备份目录（零开销跳过）。

        返回备份目录路径（无冲突文件时返回 None）。merge 成功后调用 _drop_backup
        决定备份去留；merge 失败调用 _restore_backup 移回（不丢数据）。
        """
        try:
            added = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "diff", "--name-only", "--diff-filter=A", f"HEAD...{branch}"],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return None
        if added.returncode != 0:
            return None
        added_paths = [ln.strip() for ln in added.stdout.splitlines() if ln.strip()]
        if not added_paths:
            return None

        # 逐路径判断：主树中存在该路径、且未被 index 跟踪（untracked）才纳入备份。
        rels = []
        for rel in added_paths:
            src = self.project_root / rel
            if not src.exists():
                continue
            ls = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "ls-files", "--error-unmatch", "--", rel],
                capture_output=True, text=True, timeout=30,
            )
            if ls.returncode != 0:  # 0 = tracked；非 0 = untracked（含 ignored 以外）
                rels.append(rel)

        if not rels:
            return None

        backup = self.project_root / ".fenix" / "merge-backup" / str(int(time.time()))
        for rel in rels:
            src = self.project_root / rel
            dst = backup / rel
            if not src.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            except OSError:
                continue
        return backup

    def _drop_backup(self, backup) -> None:
        """merge 成功后按字节一致性决定备份去留（fix-merge-untracked-guard D3）。

        - 备份中每个文件与 merge 后 HEAD 中同路径文件字节级一致 → 删除备份目录（现状语义）
        - 存在不一致文件 → 保留备份目录不删，写 logger.warning 列出不一致路径与备份位置，
          防止主树上的有价值改动被分支版本静默覆盖后丢失

        孤儿空父目录一并清理。
        """
        if backup is None:
            return
        if not backup.is_dir():
            return

        # 字节级比对：读文件 bytes 相等即可，无需 git 命令。
        inconsistent = []
        for p in list(backup.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(backup)
            head_file = self.project_root / rel
            try:
                if not head_file.exists():
                    inconsistent.append(str(rel))
                    continue
                with open(p, "rb") as src_f, open(head_file, "rb") as head_f:
                    if src_f.read() != head_f.read():
                        inconsistent.append(str(rel))
            except OSError:
                # 读取失败：保守视为不一致，保留备份由人工裁决
                inconsistent.append(str(rel))

        if inconsistent:
            self.logger.warning(
                "worktree_manager",
                f"merge-back 后主树副本与合入版本字节级不一致，保留备份不删除："
                f"backup='{backup}'，不一致路径={inconsistent}",
            )
            return  # 保留备份目录，供人工决策

        try:
            shutil.rmtree(str(backup))
            parent = backup.parent
            if parent.exists():
                parent.rmdir()  # 空父目录一并清理；非空时抛 OSError 忽略
        except OSError:
            pass

    def _restore_backup(self, backup) -> None:
        """merge 失败后把备份文件移回原位，并移除空备份目录（不丢数据，供下一轮重试）。"""
        if backup is None or not backup.is_dir():
            return
        for p in backup.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(backup)
            dst = self.project_root / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dst))
            except OSError:
                continue
        # 移回后清空并移除备份目录（含残留空父目录）
        try:
            shutil.rmtree(str(backup))
            parent = backup.parent
            if parent.exists():
                parent.rmdir()  # 空父目录一并清理；非空时抛 OSError 忽略
        except OSError:
            pass

    def cleanup(self, wt_path: Path, success: bool = True):
        """
        Clean up a worktree after an Agent run.

        Args:
            wt_path: Path to the worktree to clean up
            success: If True, retain the branch; if False, delete branch too
        """
        wt_str = str(wt_path)
        if wt_str not in self._active_worktrees:
            self.logger.warning("worktree_manager", f"Unknown worktree: {wt_path}")
            return

        # ── 恢复重派遗产（add-recovery-legacy-check D1）─────────────────────────
        # 失败的 implementer worktree 不直接销毁，而是注册为「遗产」保留：死亡 run 的
        # 半成品可被后继重派的 run 收编（design D4）。verifier / 成功路径照常清理。
        # 判定依据分支名前缀：implementer 分支 `fenix/<spec>-<ts>`，verifier 分支
        # `fenix/verify-<spec>-<ts>`。
        branch = self._wt_branches.get(wt_str)
        is_implementer = bool(branch) and not branch.startswith("fenix/verify-")

        try:
            self.logger.info(
                "worktree_manager",
                f"Cleaning up worktree: {wt_path} (success={success})",
            )

            if (not success) and is_implementer:
                # 死亡 implementer run：保留 worktree 与分支为遗产，仅释放锁 + 移出活动集。
                # 物理目录留给后继 run 只读参考，由 sweeper（宽限期超时）或 merge 成功
                # （consume_legacy）回收。注册发生在删除之前，避免指向已删路径。
                spec = self._spec_from_branch(branch)
                if spec:
                    self.register_legacy(spec, wt_path, branch)
                self._active_worktrees.discard(wt_str)
                self._wt_branches.pop(wt_str, None)
                return

            # Get branch name BEFORE removing worktree
            branch = None
            if not success:
                try:
                    br = subprocess.run(
                        ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "HEAD"],
                        capture_output=True, text=True, timeout=10,
                    )
                    if br.returncode == 0:
                        branch = br.stdout.strip()
                except Exception:
                    pass

            # 收工清扫：agent 已退出，先杀掉其残留测试子进程（dev-server 孤儿），
            # 否则目录删除后它们成为 cwd 失效的永生孤儿（曾致存活检测永久受骗）
            self._kill_worktree_strays(wt_path.name)

            # 硬删前置留档（fix-preserve-chain-first-round-gap D2）：删除前对
            # dirty worktree 做快照引用——不再只挂在 `git worktree remove`
            # 失败的 rmtree 兜底分支（排水强杀 --force 通常成功，旧路径
            # 系统性触发不了留档）；--force 成功路径同样留档。
            # 快照失败降级 WARNING，不阻断删除。
            self._snapshot_dirty_worktree(wt_path, self._wt_branches.get(wt_str))

            # Build command without empty strings
            cmd = [
                "git", "-C", str(self.project_root),
                "worktree", "remove", str(wt_path),
            ]
            if not success:
                cmd.append("--force")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Worktree remove warning: {result.stderr}",
                )
                # If git worktree remove fails, try manual directory removal
                # 快照已在上方完成（Task 3.3 幂等保证），rmtree 前不再重复留档。
                if wt_path.exists():
                    shutil.rmtree(str(wt_path), ignore_errors=True)
                    # Also prune the worktree reference
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "worktree", "prune"],
                        capture_output=True,
                        timeout=10,
                    )

            # On failure, delete the branch we captured earlier
            if not success and branch and branch != "HEAD":
                subprocess.run(
                    ["git", "-C", str(self.project_root), "branch", "-D", branch],
                    capture_output=True, timeout=10,
                )
                self.logger.info("worktree_manager", f"Deleted branch: {branch}")

            self._active_worktrees.discard(wt_str)
            self._wt_branches.pop(wt_str, None)

        except Exception as e:
            self.logger.error("worktree_manager", f"Cleanup error: {e}")
        finally:
            # Release the spec lock
            # Find and remove the matching lock key
            to_remove = [
                k for k in self._spec_locks
                if wt_str.endswith(k.split(":")[0])
                or k.split(":")[0] in wt_str
            ]
            for k in to_remove:
                self._spec_locks.discard(k)
                self._lock_since.pop(k, None)
            # 进程扫描缓存随之失效（下一次判定须重新扫描，防读到陈旧「存活」结果）
            for k in to_remove:
                self._proc_scan_cache.pop(self._lock_spec_name(k), None)
                # worktree 继承：认领痕迹随之清除（防止后续 prompt 误注入继承说明）
                self._active_reuse.pop(self._lock_spec_name(k), None)

    def _snapshot_dirty_worktree(self, wt_path: Path,
                                   branch: str | None = None) -> str:
        """cleanup rmtree fallback 前对 dirty worktree 做 stash create 快照留档。

        add-impl-terminal-nocommit-gate（D4）：用 ``git stash create``（引用式、
        不入 stash 栈）生成快照 commit SHA，记入日志（WARNING 级，含分支名）；
        后续争议裁决可通过 ``git stash store <sha>`` 将其转正进栈、或
        ``git fsck --unreachable | grep <sha>`` 追溯，消灭「现场毁灭后取证靠
        转录间接复原」的盲区。

        Returns: 快照 commit SHA（留档成功）或空字符串（跳过/失败）。
        """
        try:
            status = subprocess.run(
                ["git", "-C", str(wt_path), "status", "--porcelain"],
                capture_output=True, text=True, timeout=15,
            )
            if status.returncode != 0 or not status.stdout.strip():
                return ""  # 干净，无快照价值
            snap = subprocess.run(
                ["git", "-C", str(wt_path), "stash", "create",
                 f"fenix: pre-rmtree snapshot {branch or wt_path.name}"],
                capture_output=True, text=True, timeout=30,
            )
            if snap.returncode != 0 or not snap.stdout.strip():
                self.logger.warning(
                    "worktree_manager",
                    f"Pre-rmtree snapshot skipped for {wt_path}: "
                    f"{snap.stderr.strip() or 'empty stash create output'}",
                )
                return ""
            sha = snap.stdout.strip()
            self.logger.warning(
                "worktree_manager",
                f"Pre-rmtree snapshot saved for {wt_path} "
                f"(branch {branch or '?'}): commit {sha} — "
                f"recover via: git stash store {sha}",
            )
            return sha
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Pre-rmtree snapshot failed for {wt_path}: {e} — "
                f"cleanup proceeds",
            )
            return ""

    def cleanup_orphans(self, protected: set | None = None):
        """Clean up any remaining worktree directories on shutdown.

        Args:
            protected: 保护集（路径字符串集合）——被保全引用覆盖的 worktree
                （interrupt-recovery-preserve D6：`.fenix/interrupted_runs.json`
                在册项与保留分支对应的 worktree）在 shutdown 清理时跳过，
                防止「保全」与「清理」两条链路对同一 worktree 处置不一致。
                缺省空集，行为与旧版完全一致。

        清理协调（fix-preserve-chain-first-round-gap D2/D3）：任何删除 worktree
        目录的路径 MUST 在目录被物理删除前对该 worktree 执行
        ``_snapshot_dirty_worktree`` 留档——清理不留快照是最需要取证场景（排水
        强杀）里保全链系统性失效的另一半。快照失败降级 WARNING，不阻塞删除。
        """
        protected = {str(p) for p in (protected or set())}
        if not self.base_dir.exists():
            return

        for wt_dir in self.base_dir.iterdir():
            if wt_dir.is_dir() and str(wt_dir) in self._active_worktrees:
                if str(wt_dir) in protected:
                    self.logger.info(
                        "worktree_manager",
                        f"Skip orphan cleanup for {wt_dir} — protected by "
                        f"interrupted-runs preserve entry",
                    )
                    continue
                self.logger.info("worktree_manager", f"Cleaning up orphan: {wt_dir}")
                # 硬删前留档（D2）：git worktree remove --force 成功路径同样先
                # 留快照引用，消灭「先删后查」取证盲区；失败仅 WARNING 不阻塞。
                self._snapshot_dirty_worktree(
                    wt_dir, self._wt_branches.get(str(wt_dir)))
                try:
                    subprocess.run(
                        [
                            "git", "-C", str(self.project_root),
                            "worktree", "remove", str(wt_dir), "--force",
                        ],
                        capture_output=True,
                        timeout=30,
                    )
                except Exception:
                    shutil.rmtree(str(wt_dir), ignore_errors=True)

        # Prune stale worktree references
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
            timeout=10,
        )

        self._active_worktrees.clear()
        self._spec_locks.clear()
        self._lock_since.clear()
        self._proc_scan_cache.clear()

    def has_active_worktree(self, spec_name: str) -> bool:
        """Check if any worktree is active for the given SPEC.

        锁治理（improve-run-lifecycle-governance D4）：先以进程表校验在册锁——
        锁在册但扫描不到进程、且 run 流文件停止增长超过 STALE_LOCK_IDLE_SECONDS
        时判定为陈锁并回收（孤儿 attempt 已死，锁放行后续派发）；锁在册且进程
        存活（或流仍新鲜）则照常视为持锁。

        daemon 重启后内存锁丢失、但进程表仍存在指向该 spec worktree 的存活
        agent 进程时，同样返回 True（重建登记），防止创建第二个并发 worktree。
        """
        registered = any(spec_name in lock for lock in self._spec_locks)
        if not registered:
            # 无在册锁：以进程为真相兜底（daemon 重启 / 孤儿 resume 场景），
            # 命中时重建登记，使后续判定回到内存快路径。
            if self._spec_process_alive(spec_name):
                self._register_spec_locks(spec_name)
                self.logger.info(
                    "worktree_manager",
                    f"Rebuilt lock from process table for '{spec_name}' "
                    "(daemon restart with live child)",
                )
                return True
            return False

        # 在册锁：疑似陈锁时按「进程 + 流新鲜度」二次确认
        if self._spec_process_alive(spec_name):
            return True
        mtime = self._latest_stream_mtime(spec_name)
        if mtime is not None and (time.time() - mtime) <= STALE_LOCK_IDLE_SECONDS:
            return True  # 进程扫描未命中但流仍在增长：保守视为持锁
        # create 构建窗口豁免（双派发穿透原地修 2026-09-06）：流文件缺失时以锁龄
        # 二次确认——锁在 create() 拿到而 attempt 子进程与其流文件尚未产生（实测
        # 构建可达十几秒），年轻锁保守保留，防误释放后第二派穿透；超龄仍按陈锁
        # 回收，孤儿清理语义不变。
        if mtime is None and self._lock_young(spec_name):
            return True
        released = self._release_spec_locks(spec_name, "stale lock (no live process)")
        if released:
            self.logger.warning(
                "worktree_manager",
                f"Released stale lock(s) {released} for '{spec_name}' — "
                f"no live process and stream idle >{STALE_LOCK_IDLE_SECONDS}s",
            )
        return False

    # ── 锁治理（improve-run-lifecycle-governance D4）──────────────────────────

    def refresh_locks(self) -> list:
        """以真实进程表重建/校验在册锁，回收陈锁（daemon 启动首扫 + 周期调用）。

        对每个在册锁：
          - 进程表存在指向该 spec worktree 的进程 → 保留（孤儿 resume 存活的情形）
          - 无匹配进程且对应 run 流文件 mtime 距今超过 STALE_LOCK_IDLE_SECONDS
            （或根本没有流文件）→ 陈锁，释放放行后续派发
          - 无匹配进程但流仍在增长 → 保守保留（进程扫描可能受窗口/权限影响）

        Returns: 被回收的锁 key 列表（审计/测试用）。
        """
        released: list = []
        for lock_key in sorted(self._spec_locks):
            spec = self._lock_spec_name(lock_key)
            if self._spec_process_alive(spec):
                continue
            mtime = self._latest_stream_mtime(spec)
            if mtime is not None and (time.time() - mtime) <= STALE_LOCK_IDLE_SECONDS:
                continue
            if mtime is None and self._lock_young(spec):
                continue  # create 构建窗口豁免（同 has_active_worktree，防误回收年轻锁）
            # ── 恢复重派遗产（add-recovery-legacy-check D2）──
            # 陈锁释放的同一时刻：若该 spec 尚有未被清理的 implementer worktree（孤儿，
            # 如 daemon 重启后锁已失、但 worktree 目录仍在），注册为遗产兜底保留，
            # 避免被下方 cleanup_stale_worktrees 直接回收。实现死亡主路径在 cleanup()
            # 已注册，此处为补充（幂等：register_legacy 覆盖式更新）。
            self._maybe_register_legacy_for_stale_lock(spec)
            released.extend(self._release_spec_locks(
                spec, f"stale lock: no live process, stream idle "
                      f">{STALE_LOCK_IDLE_SECONDS}s"))
        if released:
            self.logger.warning(
                "worktree_manager",
                f"refresh_locks released stale lock(s): {released}",
            )
        return released

    # ── 恢复重派遗产（add-recovery-legacy-check D1/D5）────────────────────────
    # run 死亡（锁在 refresh_locks 释放）触发恢复重派时，把死亡 run 的 worktree 与
    # 分支注册为 spec 的「遗产」。遗产只做可见性与只读参考，框架不担保其内容正确性，
    # 收编/弃用决策权归后继 run 的 agent（design D4）。内存态、不持久化。

    def register_legacy(self, spec_name: str, worktree_path, branch: str) -> None:
        """登记某 spec 的死亡 run 遗产（worktree 路径 + 分支）。

        覆盖式更新（D5）：同一 spec 再次死亡时仅保留最新一份，旧遗产直接回收
        （避免遗产链膨胀）。daemon 重启后内存态丢失，遗产按孤儿清扫兜底回收。

        支持两种模式（守卫拒绝重派接入，add-project-description 事故治理）：
        - worktree 模式：worktree_path 非空 —— 死亡 run 的未提交半成品目录保留；
        - 仅分支模式：worktree_path 为 None/空 —— 守卫拒绝发生在成功收工清理之后，
          worktree 已物理删除，仅分支留存（完整已提交成果），path 记空串。

        Args:
            spec_name: 死亡 run 所属 SPEC。
            worktree_path: 死亡 run 的 worktree 绝对路径（Path 或 str）；
                仅分支模式传 None。
            branch: 死亡 run 的分支名（仅分支模式下为收编唯一线索，必填）。
        """
        if not spec_name or not branch:
            return
        wt_str = str(worktree_path) if worktree_path else ""
        # 覆盖式更新前先把旧遗产回收（D5：仅留最新一份）
        if spec_name in self._legacy:
            old = self._legacy[spec_name]
            self.logger.info(
                "worktree_manager",
                f"Replacing prior legacy for '{spec_name}' ({old.get('path')}) "
                f"— superseded by newer death",
            )
        self._legacy[spec_name] = {
            "path": wt_str,
            "branch": branch or "",
            "worktree_name": (wt_str.rstrip("/").split("/")[-1]
                              if wt_str else f"branch-only:{branch}"),
            "registered_at": time.time(),
            "dirty": bool(wt_str),  # worktree 模式待刷新脏快照；仅分支模式无脏文件
        }
        self.logger.warning(
            "worktree_manager",
            f"Registered legacy for '{spec_name}': "
            f"{'worktree=' + wt_str if wt_str else 'branch-only'} branch={branch}",
        )

    def get_legacy(self, spec_name: str) -> Optional[dict]:
        """返回某 spec 的遗产记录（copy），无则 None。

        调用方（agent_runner 的 prompt 构建）据此注入遗产上下文；返回副本避免
        外部直接改内部态。结构见 register_legacy。
        """
        rec = self._legacy.get(spec_name)
        if rec is None:
            return None
        return dict(rec)

    def consume_legacy(self, spec_name: str) -> Optional[dict]:
        """回收某 spec 的遗产（后继 run 成功 merge 时调用），返回被回收的记录。

        返回 None 表示该 spec 无在册遗产（幂等：重复调用安全）。回收时同步物理删除
        遗产 worktree 与分支（失败后保留的半成品不再需要），使清扫器不再对其豁免。
        物理删除失败仅记 WARNING，内存态遗产仍清除以放行后续逻辑。
        """
        rec = self._legacy.pop(spec_name, None)
        if rec is None:
            return None
        self._active_reuse.pop(spec_name, None)
        self.logger.info(
            "worktree_manager",
            f"Consumed legacy for '{spec_name}' (successor merged): {rec.get('path')}",
        )
        try:
            from pathlib import Path as _Path
            path = rec.get("path", "")
            branch = rec.get("branch", "")
            if path:
                wt = _Path(path)
                res = subprocess.run(
                    ["git", "-C", str(self.project_root), "worktree", "remove",
                     str(wt), "--force"],
                    capture_output=True, text=True, timeout=30,
                )
                if res.returncode != 0 and wt.exists():
                    shutil.rmtree(str(wt), ignore_errors=True)
            if branch and branch != "HEAD":
                subprocess.run(
                    ["git", "-C", str(self.project_root), "branch", "-D", branch],
                    capture_output=True, timeout=10,
                )
            subprocess.run(
                ["git", "-C", str(self.project_root), "worktree", "prune"],
                capture_output=True, timeout=10,
            )
        except Exception as e:
            self.logger.warning(
                "worktree_manager",
                f"Legacy consume physical reclaim failed for '{spec_name}': {e}",
            )
        return rec

    def has_legacy(self, spec_name: str) -> bool:
        """某 spec 是否有在册遗产（只读查询，prompt 注入 `无遗产不注入` 判定用）。"""
        return spec_name in self._legacy

    # ── worktree 继承（fast-track 打回重派复用）──────────────────────────────
    # 语义：fast-track run 失败/打回时保留 worktree 目录与分支（keep_for_reuse，
    # 复用遗产机制做宽限期回收与清扫豁免），下一轮派发 create() 优先认领同一
    # 目录同一分支继续工作——继承上一轮已提交成果与未提交现场，不再从零重做。

    def keep_for_reuse(self, spec_name: str, wt_path: Path,
                       agent_type: str = "") -> None:
        """保留 worktree 目录与分支，登记供下轮重派继承。

        底层复用 register_legacy（同一登记表：宽限期回收、清扫器豁免全继承），
        仅追加 ``reuse`` 标记供 create() 认领。与 cleanup(success=False) 的差异：
        不删除目录与分支、仅释放锁与活动集；dev-server 由调用方先行回收。

        fix-provider-transient-backoff（D3）：transient 终态失败同样走此路径
        （替代 cleanup(success=False)），agent_type 参数供日志区分来源
        （fast-track / implementer / transient 其他 agent_type）。
        """
        wt_str = str(wt_path)
        branch = (
            self._wt_branches.get(wt_str)
            or self._guess_branch_from_worktree(wt_path)
        )
        # 收工清扫：agent 已退出，杀掉残留测试子进程（目录保留，进程不留）
        self._kill_worktree_strays(wt_path.name)
        self.register_legacy(spec_name, wt_path, branch)
        rec = self._legacy.get(spec_name)
        if rec is not None:
            rec["reuse"] = True
        self._active_worktrees.discard(wt_str)
        self._wt_branches.pop(wt_str, None)
        self._active_reuse.pop(spec_name, None)
        # 释放 spec 锁（与 cleanup 的 finally 段同语义，按 spec 精确匹配）
        for k in [k for k in self._spec_locks if k.split(":")[0] == spec_name]:
            self._spec_locks.discard(k)
            self._lock_since.pop(k, None)
        self._proc_scan_cache.pop(spec_name, None)
        self.logger.info(
            "worktree_manager",
            f"Kept worktree for reuse: {wt_path} (branch {branch}, "
            f"spec '{spec_name}'" + (f", agent_type '{agent_type}'" if agent_type else "")
            + ")",
        )

    def get_reuse_record(self, spec_name: str) -> Optional[dict]:
        """返回本轮 run 已认领的复用 worktree 记录（prompt 注入用），无则 None。"""
        rec = self._active_reuse.get(spec_name)
        if rec:
            return dict(rec)
        rec = self._legacy.get(spec_name)
        if rec and rec.get("reuse"):
            return dict(rec)
        return None

    def mark_reused(self, spec_name: str, wt_path: Path, branch: str) -> None:
        """标记跨 attempt 复用的 worktree（未走 create 认领路径时补记，幂等）。"""
        self._active_reuse[spec_name] = {
            "path": str(wt_path), "branch": branch or "",
        }

    def _take_reusable_worktree(self, spec_name: str) -> Optional[tuple]:
        """认领该 spec 的复用遗产；有效返回 (wt_path, branch)，无效清理后返回 None。

        有效性：目录存在、仍是注册的 git worktree、分支仍可解析。认领即从
        _legacy 摘出（在用目录不再是「遗产」，防 sweeper 宽限期回收正在工作的
        worktree），转入 _active_reuse 供 prompt 注入与收尾清理。
        """
        rec = self._legacy.get(spec_name)
        if not rec or not rec.get("reuse"):
            return None
        path = rec.get("path") or ""
        branch = rec.get("branch") or ""
        wt = Path(path) if path else None
        # 有效性判定收敛到 is_available 单源（interrupt-recovery-preserve D5）：
        # 目录存在 + git worktree 注册有效 + 分支可解析。判定口径与 repair
        # 换壳（resolve_repair_site）、recovery 保留一致，任何链路不自行拼装。
        valid = False
        if wt is not None:
            try:
                valid = self.is_available(wt, branch) == WT_AVAILABLE
            except Exception:
                valid = False
        if not valid:
            self._legacy.pop(spec_name, None)
            self.logger.info(
                "worktree_manager",
                f"Reusable legacy for '{spec_name}' no longer valid "
                f"(path={path or 'none'}, branch={branch or 'none'}) — fresh create",
            )
            return None
        self._legacy.pop(spec_name, None)
        self._active_reuse[spec_name] = {"path": str(wt), "branch": branch}
        return wt, branch

    def _maybe_register_legacy_for_stale_lock(self, spec_name: str) -> None:
        """refresh_locks 释放陈锁时的遗产兜底注册（add-recovery-legacy-check D2）。

        若该 spec 已无在册锁、但有物理残留的 implementer worktree（孤儿目录），且
        该 worktree 当前未被活动集占用，则注册为遗产，避免被 cleanup_stale_worktrees
        直接回收（design D2「单点改动、无新增扫描」：复用 refresh_locks 的扫锁时机）。

        幂等：register_legacy 为覆盖式更新，已注册遗产不重复写。若该 spec 已在册
        遗产则跳过（不覆盖已有更早注册的遗产——更早注册的宽限期更短，应由其决定）。
        """
        if self.has_legacy(spec_name):
            return
        wt = self.find_implementer_worktree(spec_name)
        if wt is None:
            return
        if str(wt) in self._active_worktrees:
            return  # 仍在活动集：未被清理，非孤儿，正常派发中
        branch = self.get_branch_name(wt) or self._wt_branches.get(str(wt))
        if not branch:
            branch = self._guess_branch_from_worktree(wt)
        self.register_legacy(spec_name, wt, branch or "")

    def _guess_branch_from_worktree(self, wt_path) -> str:
        """从 worktree 目录 HEAD 取分支名（register_legacy 兜底用）。"""
        try:
            br = subprocess.run(
                ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            if br.returncode == 0:
                return br.stdout.strip()
        except Exception:
            pass
        return ""

    def _reclaim_expired_legacy(self, now: float | None = None) -> list:
        """宽限期兜底回收（add-recovery-legacy-check D2）：清扫器在扫孤儿前调用。

        对每条在册遗产，若注册时刻距今超过 LEGACY_GRACE_SECONDS（跟随孤儿清扫周期），
        视为无人收编而兜底回收：删除 worktree 目录 + 分支、记审计。返回被回收的
        spec 名列表（审计/测试用）。

        宽限期内（后继 run 尚在派发中）的遗产不动，交 merge 成功 / 重派逻辑处理。
        """
        if not self._legacy:
            return []
        now = time.time() if now is None else now
        expired = [
            spec for spec, rec in self._legacy.items()
            if now - rec.get("registered_at", 0) > LEGACY_GRACE_SECONDS
        ]
        reclaimed: list = []
        for spec in expired:
            rec = self._legacy.pop(spec, None)
            if rec is None:
                continue
            path = rec.get("path", "")
            branch = rec.get("branch", "")
            self.logger.warning(
                "worktree_manager",
                f"Legacy grace period expired for '{spec}' — sweeper reclaiming "
                f"worktree={path} branch={branch}",
            )
            try:
                from pathlib import Path as _Path
                wt = _Path(path)
                if path:
                    res = subprocess.run(
                        ["git", "-C", str(self.project_root), "worktree", "remove",
                         str(wt), "--force"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if res.returncode != 0:
                        shutil.rmtree(str(wt), ignore_errors=True)
                if branch and branch != "HEAD":
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "branch", "-D", branch],
                        capture_output=True, timeout=10,
                    )
            except Exception as e:
                self.logger.warning(
                    "worktree_manager",
                    f"Legacy sweeper reclaim failed for '{spec}': {e}",
                )
            reclaimed.append(spec)
        if reclaimed:
            subprocess.run(
                ["git", "-C", str(self.project_root), "worktree", "prune"],
                capture_output=True, timeout=10,
            )
        return reclaimed

    @staticmethod
    def _lock_spec_name(lock_key: str) -> str:
        """锁 key（``<spec>:<agent_type>``）→ spec 名。"""
        return lock_key.split(":")[0]

    def _register_spec_locks(self, spec_name: str) -> None:
        """按 spec 名重建两把锁（impl + verify），与 create() 的 key 形态一致。

        孤儿进程可能来自任一 agent 类型，进程表只能证明「该 spec 仍有活跃
        worktree」而无法可靠区分前缀，因此两把一起登记，宁可多拦不漏放。
        """
        self._spec_locks.add(f"{spec_name}:implementer")
        self._lock_since[f"{spec_name}:implementer"] = time.time()
        self._spec_locks.add(f"{spec_name}:verifier")
        self._lock_since[f"{spec_name}:verifier"] = time.time()

    def _release_spec_locks(self, spec_name: str, reason: str) -> list:
        """释放该 spec 的全部在册锁，返回被释放的 key（已不在册则返回空）。"""
        to_remove = [k for k in self._spec_locks if self._lock_spec_name(k) == spec_name]
        for k in to_remove:
            self._spec_locks.discard(k)
            self._lock_since.pop(k, None)
        return to_remove

    def _lock_young(self, spec_name: str) -> bool:
        """该 spec 任一在册锁的锁龄 < STALE_LOCK_IDLE_SECONDS（create 构建窗口豁免）。

        锁龄缺失（历史锁未登记时刻）按不年轻处理——豁免只对确定年轻的锁生效，
        失败方向保守（宁可走既有陈锁回收，不额外放行）。
        """
        now = time.time()
        for k in self._spec_locks:
            if self._lock_spec_name(k) != spec_name:
                continue
            since = self._lock_since.get(k)
            if since is not None and (now - since) < STALE_LOCK_IDLE_SECONDS:
                return True
        return False

    def _spec_process_alive(self, spec_name: str) -> bool:
        """进程表中是否存在指向该 spec worktree 的进程（带短缓存）。

        进程消失/出现以缓存窗口（PROCESS_SCAN_CACHE_SECONDS）为粒度生效，
        避免派发热路径上的 pgrep 风暴。
        """
        now = time.monotonic()
        cached = self._proc_scan_cache.get(spec_name)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            alive = bool(self._process_scanner(spec_name))
        except Exception as e:  # 扫描异常视为不可用：保守按无进程处理并记日志
            self.logger.warning(
                "worktree_manager",
                f"Process scan failed for '{spec_name}' (treated as absent): {e}",
            )
            alive = False
        self._proc_scan_cache[spec_name] = (
            now + PROCESS_SCAN_CACHE_SECONDS, alive)
        return alive

    def _pgrep_spec_process(self, spec_name: str) -> bool:
        """pgrep 匹配 cmdline 含 ``worktrees/{impl,verify}-<spec>-`` 的 agent 进程。

        匹配串锚定 worktree 目录字面量（<prefix>-<spec>-<ts>），不匹配裸 spec 名，
        防止把无关进程当成持锁者；命中后还须经 ``_is_claude_process`` 确认程序为
        claude——测试子进程（dev-server 等）的 cmdline 同样含路径，agent 退出后
        成为永生孤儿，按路径匹配会把锁永久骗走。pgrep 不可用/超时时返回 False
        （调用方以 run 流新鲜度做二次确认）。
        """
        for prefix in ("impl", "verify"):
            pattern = f"worktrees/{prefix}-{spec_name}-"
            try:
                res = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True, text=True, timeout=5,
                )
            except (subprocess.SubprocessError, OSError):
                return False
            if res.returncode == 0 and res.stdout.strip():
                if any(_is_claude_process(p) for p in res.stdout.split()):
                    return True
        return False

    def _latest_stream_mtime(self, spec_name: str) -> Optional[float]:
        """该 spec 全部 run 流文件（.fenix/runs/{impl,verify}-<spec>-*.jsonl）的最新 mtime。

        无任何流文件返回 None。
        """
        runs_dir = self.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return None
        newest: Optional[float] = None
        try:
            for prefix in ("impl", "verify"):
                for p in runs_dir.glob(f"{prefix}-{spec_name}-*.jsonl"):
                    try:
                        m = p.stat().st_mtime
                    except OSError:
                        continue
                    if newest is None or m > newest:
                        newest = m
        except OSError:
            return None
        return newest

    def _worktree_has_live_process(self, wt_name: str) -> bool:
        """进程表中是否存在引用该 worktree 目录的 agent 进程（启动清理用）。

        与 _pgrep_spec_process 不同：这里按完整 worktree 目录名匹配，不经过
        缓存（启动时一次性调用，结果必须实时）；命中后同样以 claude 进程
        为锚——仅剩 dev-server 孤儿的 worktree 应被判定为无主并进入清理。
        """
        pattern = f"worktrees/{wt_name}"
        try:
            res = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.SubprocessError, OSError):
            return False
        return res.returncode == 0 and any(
            _is_claude_process(p) for p in res.stdout.split()
        )

    def _kill_worktree_strays(self, wt_name: str) -> list:
        """杀掉 cmdline 或 cwd 引用该 worktree 的非 agent 残留进程，返回被杀 PID。

        agent 收工后其测试子进程（v2 dev-server 等）可能残留为 PPID=1 孤儿：
        cmdline 仍含 worktree 路径且永不退出，既让 worktree 目录删不干净，
        也曾借存活检测把派发锁永久骗走。claude agent 进程不在清扫范围
        （防误杀在跑的 attempt）。

        verify-process-lifecycle（D8 能力升级）：
        - cmdline 匹配外增加 ``/proc/<pid>/cwd`` readlink 归属匹配——覆盖 argv
          不含 worktree 路径的进程（如 agent 经 Bash 起的 ``npm run dev``，
          argv 是 shell 而 cwd 在 worktree 内）；
        - SIGTERM 后短等待（宽限期），无响应进程补 SIGKILL 兜底，不残留。
        """
        me = os.getpid()
        token = f"worktrees/{wt_name}"
        candidates: list = []
        try:
            for pid_str in os.listdir("/proc"):
                if not pid_str.isdigit():
                    continue
                pid = int(pid_str)
                if pid == me or _is_claude_process(pid_str):
                    continue
                proc_dir = Path("/proc") / pid_str
                # cmdline 匹配（既有判定）
                try:
                    argv = (proc_dir / "cmdline").read_bytes().split(b"\0")
                    argv_text = " ".join(
                        a.decode("utf-8", "replace") for a in argv if a)
                except OSError:
                    argv_text = ""
                # cwd readlink 归属匹配（覆盖 argv 无路径的 Bash 包装进程）
                try:
                    cwd = os.readlink(f"/proc/{pid_str}/cwd")
                except OSError:
                    cwd = ""
                if token in argv_text or token in cwd:
                    candidates.append(pid)
        except OSError:
            return []
        killed = []
        for pid in candidates:
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(pid)
            except OSError:
                continue
        if killed:
            # SIGTERM 宽限期（~2s）：仍存活者 SIGKILL 兜底（D8）
            deadline = time.time() + 2.0
            while time.time() < deadline:
                alive = [p for p in killed if self._pid_alive(p)]
                if not alive:
                    break
                time.sleep(0.2)
            for pid in killed:
                if self._pid_alive(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        continue
        if killed:
            self.logger.warning(
                "worktree_manager",
                f"Killed stray worktree processes for '{wt_name}': {killed}",
            )
        return killed

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """/proc 存活探针（kill 0）：进程存在即存活（僵尸差异可接受）。"""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _spec_from_worktree_name(wt_name: str) -> Optional[str]:
        """worktree 目录名（``{impl,verify}-<spec>-<ts>``）→ spec 名。

        spec 名自身可含连字符，因此取前缀之后、末段时间戳之前的部分；
        段数不足（非本框架产物）返回 None。
        """
        for prefix in ("impl", "verify"):
            if wt_name.startswith(f"{prefix}-"):
                rest = wt_name[len(prefix) + 1:]
                parts = rest.rsplit("-", 1)
                if len(parts) == 2 and parts[0] and parts[1].isdigit():
                    return parts[0]
        return None

    @staticmethod
    def _spec_from_branch(branch: str) -> Optional[str]:
        """分支名（``fenix/<spec>-<ts>`` / ``fenix/verify-<spec>-<ts>``）→ spec 名。

        实现 death 时据分支名回推 spec（cleanup 注册遗产用）。与 _spec_from_worktree_name
        对称：取 ``fenix/`` 之后、末段 ``-<ts>`` 之前的部分。verifier 分支含 ``verify-``
        前缀，去掉前缀后同样取到 spec。段数不足返回 None。
        """
        if not branch or not branch.startswith("fenix/"):
            return None
        rest = branch[len("fenix/"):]
        if rest.startswith("verify-"):
            rest = rest[len("verify-"):]
        parts = rest.rsplit("-", 1)
        if len(parts) == 2 and parts[0] and parts[1].isdigit():
            return parts[0]
        return None

    # ── 主树健康检查（fix-fenix-token-waste） ──────────────────────

    def _list_dirty_tracked_files(self) -> list:
        """提取主树脏 tracked 文件清单（fix-mergeback-stashpop-silent-loss D3）。

        ensure_clean_tree 的 porcelain 脏判定提炼为共享 helper：porcelain v1
        每行 "XY " 前缀，X=索引状态、Y=工作区状态，第 3 个字符恒为分隔符空格
        ——脏判定看 [0]/[1] 任一非空格（历史版本误查 [2] 致 autostash 从未
        触发，2026-09-02 修）。untracked（'??'）不计入。命令失败返回空列表
        （调用方按「无重叠」处理，不阻塞流程）。

        Returns: 排序后的脏 tracked 文件路径列表（rename 两侧都计入）。
        """
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        if result.returncode != 0:
            return []
        files: list = []
        for line in result.stdout.splitlines():
            if len(line) < 3 or line.startswith("?? "):
                continue
            if line[0] == " " and line[1] == " ":
                continue
            path = line[3:].strip()
            if " -> " in path:
                files.extend(p.strip() for p in path.split(" -> "))
            else:
                files.append(path)
        return sorted(p for p in files if p)

    def ensure_clean_tree(self) -> bool:
        """merge guard 段内确保主树 tracked 状态干净，保证 merge-back 可成功。

        仅 stash **tracked 修改**（`git stash push` 不带 -u）。返回 True 表示
        执行过 stash（guard 的 finally 会 restore_after_merge 恢复）；False
        表示主树 tracked 状态本来就干净。

        **不卷 untracked 文件**（fix-autostash-orphans）：untracked 与分支新增
        同路径的冲突由 merge 内部 `_backup_untracked_spec_files` 处理——不一致
        副本保留备份 + warning，一致副本清理；若也用 stash 卷走，merge 后 pop
        会用用户 untracked 副本覆盖刚合入的分支版本（或 pop 失败滞留）。
        历史版本的 --include-untracked 是 7 次改动滞留事故的放大器之一。

        重要：stash 排除 `spec/changes/`——该目录下未跟踪的 spec 文件
        （proposal/design/specs/tasks）是框架运行必需，一旦被卷进 stash，
        implementer 就找不到 SPEC 文件而空转（fix：曾因此烧掉 ~450 轮）。
        spec 文件应在创建时提交；此处排除作为兜底。
        """
        # 脏判定复用共享 helper（fix-mergeback-stashpop-silent-loss D3），
        # 判定语义与历史实现逐字节一致。
        dirty_tracked = bool(self._list_dirty_tracked_files())
        if not dirty_tracked:
            return False
        stash = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "push",
             "-m", AUTOSTASH_MSG_PREFIX,
             "--", ".", ":(exclude)spec/changes"],
            capture_output=True, text=True, timeout=30,
        )
        if stash.returncode != 0:
            self.logger.warning(
                "worktree_manager",
                f"Autostash failed (proceed with dirty tree): {stash.stderr.strip()}",
            )
            return False
        if "No local changes" in (stash.stdout + stash.stderr):
            # 唯一脏内容就是被排除的 spec/changes，实际未 stash
            return False
        self.logger.info("worktree_manager", "Autostashed tracked changes before merge")
        return True

    def restore_after_merge(self) -> tuple:
        """merge-back 成功后恢复 dispatch 前自动 stash 的主树改动。

        返回 ``(ok, conflict_files)``：

        - ``(True, [])``：pop 成功 / 无 stash 可恢复（与旧版返回 True 兼容）。
        - ``(True, [file, ...])``：pop 发生冲突但已完成自愈——主树回到干净可写状态，
          ``conflict_files`` 为被丢弃 stash 改动的文件清单（stash 条目保留，可
          ``git stash list`` / ``git stash show`` 找回）。
        - ``(False, [])``：pop 失败且非冲突类（如其它 git 错误），stash 保留；调用方按
          旧版 False 语义处理（主树可能仍半合并，需人工处置）。

        **自愈（fix-stashpop-deadlock）**：当 pop 返回非 0 且输出含 ``CONFLICT`` 时，
        主树会陷入 UU 半合并状态、index.lock 满，导致后续所有 git 写操作瘫痪。此时：
          1. 用 ``git ls-files -u`` 枚举全部 UU 未合并文件；
          2. 对每个 UU 文件 ``git checkout -f HEAD -- <file>``（``-f`` 因路径处于 unmerged
             状态，普通 checkout 会报 "path is unmerged"）——丢弃 stash 版本、保留已
             merge 进 HEAD 的实现（最不可丢失的产物）；
          3. ``git reset`` 清空 index 残留的 staged 冲突条目，主树恢复干净可写。
        stash 条目**不**自动 drop，被丢弃内容可由人工从 stash 中找回——除非
        自愈后核对确认条目零独有内容（fix-mergeback-stashpop-silent-loss D2）：
        对每个 UU 文件跑树级 ``git diff --quiet <sha> HEAD -- <file>``，全部一致
        说明 stash 版已被合并结果完全取代，条目永远等不到清理，按
        reclaim_stale_autostash（4f753ed）同款「sha 仍在栈顶才 drop」模式自动
        drop 并记 sha 日志；任一文件有差异则保留条目并给出逐文件找回命令。
        """
        # pop 前钉住栈顶 sha（fix-mergeback-stashpop-silent-loss D2）：guard 锁内
        # LIFO，此时栈顶即刚 push 的条目；drop 前以「sha 仍为栈顶」防并发插队。
        pinned_sha = ""
        rev = subprocess.run(
            ["git", "-C", str(self.project_root), "rev-parse", "--verify",
             "stash@{0}"],
            capture_output=True, text=True, timeout=30,
        )
        if rev.returncode == 0:
            pinned_sha = rev.stdout.strip()

        result = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "pop"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            self.logger.info("worktree_manager", "Stash popped after merge")
            return True, []

        output = (result.stderr or "") + (result.stdout or "")
        # 无 stash 可恢复（ensure_clean_tree 未 stash / 已被消费）：
        # 返回码非 0 但属正常情况，视为成功且无害（与旧版返回 True 兼容）。
        if "No stash entries" in output:
            self.logger.info("worktree_manager", "No stash to pop after merge")
            return True, []

        if "CONFLICT" not in output:
            # 非冲突类失败（其它 git 错误等）：保留旧版 False 语义，不自愈
            self.logger.warning(
                "worktree_manager",
                f"Stash pop failed (non-conflict, stash preserved): "
                f"{result.stderr.strip() or result.stdout.strip()}",
            )
            return False, []

        # ── pop 冲突：进入自愈（fix-stashpop-deadlock） ──
        conflict_files = self._list_unmerged_files()
        if conflict_files:
            self._heal_unmerged_files(conflict_files)
            # 被取代条目自动 drop 判定（fix-mergeback-stashpop-silent-loss D2）：
            # 树级 diff 逐一核对 stash 版是否已被合并后 HEAD 完全取代。
            if self._drop_superseded_stash_entry(pinned_sha, conflict_files):
                self.last_stash_entry_fate = {"kept": False, "sha": pinned_sha}
                self.logger.warning(
                    "worktree_manager",
                    f"Stash pop conflict self-healed; stash changes on "
                    f"{len(conflict_files)} file(s): {conflict_files} were fully "
                    f"subsumed by merge result — entry auto-dropped",
                )
            else:
                recover_cmds = " ".join(
                    f"git show {pinned_sha}:{f}" for f in conflict_files
                ) if pinned_sha else "git stash show"
                self.logger.warning(
                    "worktree_manager",
                    f"Stash pop conflict self-healed; discarded stash changes on "
                    f"{len(conflict_files)} file(s): {conflict_files} "
                    f"(stash preserved, recover via: {recover_cmds})",
                )
        else:
            # 输出含 CONFLICT 但已无 UU 条目（罕见：冲突已自行消解）——照常处理
            self.logger.warning(
                "worktree_manager",
                f"Stash pop conflict reported but no UU files found; "
                f"stash preserved: {output.strip()}",
            )
        return True, conflict_files

    def _drop_superseded_stash_entry(self, pinned_sha: str, conflict_files: list) -> bool:
        """pop 冲突自愈后判定 stash 条目是否已被合并结果完全取代（D2）。

        判据（树级 diff 而非文本比较，二进制/模式变更天然覆盖）：对每个 UU 文件
        ``git diff --quiet <sha> HEAD -- <file>``——stash 提交树即 stash 时刻工作区
        快照，HEAD 已含合并结果，退出码 0 即「stash 版被完全取代」。全部 0 → 零
        独有内容，drop 该条目；任一非 0 → 保留。

        drop 前核对 sha 仍在栈顶（reclaim_stale_autostash 同款防线，防并发新条目
        插队误删）；sha 未知/不在栈顶/drop 失败均保留条目并记跳过原因。

        Returns: True = 已 drop；False = 保留（差异 / sha 防线未通过）。
        """
        if not pinned_sha:
            self.logger.warning(
                "worktree_manager",
                "Superseded-stash check skipped: pop 前 sha 未知 — 条目保留",
            )
            return False
        superseded = True
        for f in conflict_files:
            try:
                d = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "diff", "--quiet", pinned_sha, "HEAD", "--", f],
                    capture_output=True, text=True, timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError):
                superseded = False
                break
            if d.returncode != 0:
                superseded = False
                break
        if not superseded:
            return False
        # sha 仍在栈顶才 drop（防并发 autostash 插队误删）
        cur = subprocess.run(
            ["git", "-C", str(self.project_root), "rev-parse", "--verify",
             "stash@{0}"],
            capture_output=True, text=True, timeout=30,
        )
        if cur.returncode != 0 or cur.stdout.strip() != pinned_sha:
            self.logger.warning(
                "worktree_manager",
                f"Superseded stash entry not dropped: stash@{{0}} 已变化 "
                f"(pinned={pinned_sha[:12]}) — 条目保留",
            )
            return False
        dropped = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "drop", "stash@{0}"],
            capture_output=True, text=True, timeout=30,
        )
        if dropped.returncode != 0:
            self.logger.warning(
                "worktree_manager",
                f"Superseded stash entry drop failed "
                f"(commit {pinned_sha[:12]}, recoverable until gc): "
                f"{dropped.stderr.strip()}",
            )
            return False
        self.logger.warning(
            "worktree_manager",
            f"Superseded stash entry auto-dropped (commit {pinned_sha[:12]}, "
            f"recoverable until gc) — stash 版已被合并结果完全取代",
        )
        return True

    def reclaim_stale_autostash(self) -> bool:
        """兜底回收滞留的 pre-dispatch autostash 条目（fix-autostash-orphans）。

        历史版本在派发前 stash、仅 merge-back 成功路径 pop——任何失败/重派/
        异常/daemon 重启出口都会把用户未提交改动永久滞留 stash 栈。guard 化
        （方案 1）后新条目不再滞留，本方法负责回收存量与各类历史遗留。

        仅在「主树干净」且「栈顶条目带 AUTOSTASH_MSG_PREFIX」时 pop 恢复：
          - 主树脏说明用户正在工作，不抢；
          - 人工手工 stash 的条目无此前缀，永不触碰。

        pop 冲突时沿用 restore_after_merge 的自愈策略（丢弃 stash 版本保 HEAD、
        清 UU 使主树可写）。自愈完成后 drop 该条目（fix-autostash-conflict-loop）：
        冲突方内容已按策略丢弃、非冲突方改动已落工作区，条目保留不再有恢复价值；
        而本巡检每 60s 跑一次，条目若滞留栈顶会被原样重试 → 每分钟一条 ERROR 的
        无限循环（2026-09-07 指纹 a6fd0e29 事故），daemon 重启无法清除（状态在
        git stash 栈）。drop 前核对 sha 仍在栈顶（防并发新 autostash 插队误删），
        sha 记入日志，gc 前可按 sha 找回。

        Returns: True 表示成功恢复了一个条目。
        """
        status = subprocess.run(
            ["git", "-C", str(self.project_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
        if status.returncode != 0 or status.stdout.strip():
            return False
        lst = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "list", "-n", "1"],
            capture_output=True, text=True, timeout=30,
        )
        # 格式：stash@{0}: On <branch>: fenix: pre-dispatch autostash
        top = lst.stdout.strip() if lst.returncode == 0 else ""
        if AUTOSTASH_MSG_PREFIX not in top:
            return False
        rev = subprocess.run(
            ["git", "-C", str(self.project_root), "rev-parse", "--verify",
             "stash@{0}"],
            capture_output=True, text=True, timeout=30,
        )
        sha_before = rev.stdout.strip() if rev.returncode == 0 else ""
        pop = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "pop"],
            capture_output=True, text=True, timeout=30,
        )
        if pop.returncode == 0:
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaimed onto clean main tree: {top}",
            )
            return True
        output = (pop.stderr or "") + (pop.stdout or "")
        if "CONFLICT" in output:
            conflict_files = self._list_unmerged_files()
            if conflict_files:
                self._heal_unmerged_files(conflict_files)
            if self._list_unmerged_files():
                # 自愈未完成（checkout 超时等）：条目保留交人工，绝不 drop
                self.logger.error(
                    "worktree_manager",
                    f"Stale autostash pop conflict heal incomplete; unmerged "
                    f"files remain, stash entry preserved "
                    f"(recover via git stash show)",
                )
                return False
            drop_sha = ""
            if sha_before:
                cur = subprocess.run(
                    ["git", "-C", str(self.project_root), "rev-parse",
                     "--verify", "stash@{0}"],
                    capture_output=True, text=True, timeout=30,
                )
                if cur.returncode == 0 and cur.stdout.strip() == sha_before:
                    dropped = subprocess.run(
                        ["git", "-C", str(self.project_root), "stash", "drop",
                         "stash@{0}"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if dropped.returncode == 0:
                        drop_sha = sha_before
            if drop_sha:
                self.logger.warning(
                    "worktree_manager",
                    f"Stale autostash pop conflicted with merged "
                    f"implementation; healed UU files {conflict_files}, entry "
                    f"dropped (commit {drop_sha}, recoverable until gc)",
                )
            else:
                self.logger.warning(
                    "worktree_manager",
                    f"Stale autostash pop conflicted with merged "
                    f"implementation; healed UU files {conflict_files}, "
                    f"stash entry preserved (top entry moved, recover via "
                    f"git stash show)",
                )
            return False
        self.logger.warning(
            "worktree_manager",
            f"Stale autostash pop failed (entry preserved): {output.strip()}",
        )
        return False

    def _list_unmerged_files(self) -> list:
        """枚举主树中全部 UU 未合并文件（merge 冲突 / stash pop 冲突残留）。

        ``git ls-files -u`` 对每个冲突文件输出 1~3 行（stage 1/2/3），行末为路径；
        去重后返回排序后的路径列表。命令失败返回空列表（不阻塞自愈）。
        """
        try:
            ls = subprocess.run(
                ["git", "-C", str(self.project_root), "ls-files", "-u"],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return []
        if ls.returncode != 0 or not ls.stdout.strip():
            return []
        paths: set = set()
        for line in ls.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # 行格式：<mode> <hash> <stage>\t<path>
            tab = line.split("\t", 1)
            if len(tab) == 2 and tab[1].strip():
                paths.add(tab[1].strip())
        return sorted(paths)

    def _collect_conflict_paths(self) -> list:
        """枚举主树 merge 冲突挂起态的冲突路径（自愈判定与 repair 分类共用）。

        add-merge-back-repair-lane D1：与 ``_resolve_build_artifact_conflicts``
        同一采集口径（``git status --porcelain`` 中 unmerged 状态码的路径，
        rename ``old -> new`` 双胞胎两侧都计入），确保「产物自愈已尝试仍失败」的
        冲突分类与实际自愈判定一致。非冲突态/命令失败返回空列表。
        """
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return []
        if res.returncode != 0:
            return []
        conflict_paths: list = []
        for line in res.stdout.splitlines():
            st = line[:2]
            if not ("U" in st or st in ("AA", "DD", "AU", "UA", "DU", "UD")):
                continue
            path = line[3:].strip()
            if " -> " in path:
                conflict_paths.extend(p.strip() for p in path.split(" -> "))
            else:
                conflict_paths.append(path)
        return [p for p in conflict_paths if p]

    def _heal_unmerged_files(self, conflict_files: list) -> None:
        """对 UU 文件执行自愈：丢弃 stash 版本、保留 merge 结果、清空 index。

        每个 UU 文件处于 unmerged 状态，普通 ``git checkout HEAD -- <file>`` 会报
        "path is unmerged"，因此用 ``-f`` 强制从 HEAD 还原（清空 stage 1/2/3、工作区
        覆盖为已 merge 的实现）。随后 ``git reset`` 兜底清空 index 中任何残留的 staged
        冲突条目，使主树回到干净可写状态。
        """
        for f in conflict_files:
            try:
                subprocess.run(
                    ["git", "-C", str(self.project_root), "checkout", "-f",
                     "HEAD", "--", f],
                    capture_output=True, text=True, timeout=30,
                )
            except subprocess.TimeoutExpired:
                self.logger.warning(
                    "worktree_manager",
                    f"checkout -f HEAD -- {f} timed out during self-heal",
                )
        # 清空 index 残留的 staged 冲突条目（mixed reset，不动工作区）
        try:
            subprocess.run(
                ["git", "-C", str(self.project_root), "reset"],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            self.logger.warning(
                "worktree_manager",
                "git reset timed out during stash-pop self-heal",
            )

    def cleanup_stale_worktrees(self):
        """启动时全量清理孤儿 worktree：删除所有不在活动集合的目录 + 对应分支 + prune。

        与 shutdown 的 cleanup_orphans 互补：后者清活动集合内残留，本方法清
        上次异常退出遗留的孤儿。失败记 WARNING，不阻塞 daemon 启动。

        锁治理（improve-run-lifecycle-governance D4）：daemon 重启后仍可能有
        孤儿 attempt 进程在某个 worktree 里继续干活，删除其目录会让进程当场
        失去工作区。凡进程表仍能扫到指向该目录的进程，跳过清理并把锁重建
        回内存（保守：宁可不清理，不可误删在用的 worktree）。

        恢复重派遗产（add-recovery-legacy-check D2）：在册遗产 worktree 在宽限期内
        豁免清理（清扫器跳过），直到后继 run 成功 merge（consume_legacy）或宽限期
        超时（_reclaim_expired_legacy 兜底回收）。先触发一次宽限期兜底回收，再扫
        孤儿——宽限期内的遗产保持不动，宽限期外的遗产在此被兜底清除。
        """
        # 宽限期兜底回收：超时遗产由 sweeper 在此清除并记审计（设计 D2）。
        self._reclaim_expired_legacy()
        if not self.base_dir.exists():
            return
        # 在册遗产 worktree 名集合（宽限期内豁免）；实时监控避免与 _reclaim 竞争。
        legacy_names = {
            rec.get("worktree_name") for rec in self._legacy.values()
        }
        for wt_dir in self.base_dir.iterdir():
            if not wt_dir.is_dir() or str(wt_dir) in self._active_worktrees:
                continue
            # 遗产豁免（add-recovery-legacy-check D2）：宽限期内不得清，留给后继 run 收编
            if wt_dir.name in legacy_names:
                self.logger.info(
                    "worktree_manager",
                    f"Skip stale worktree cleanup for '{wt_dir.name}' — "
                    f"registered as recovery legacy (grace period)",
                )
                continue
            if self._worktree_has_live_process(wt_dir.name):
                spec = self._spec_from_worktree_name(wt_dir.name)
                if spec:
                    self._register_spec_locks(spec)
                    self.logger.warning(
                        "worktree_manager",
                        f"Skip stale worktree cleanup for '{wt_dir.name}' — "
                        f"live process present, lock rebuilt for '{spec}'",
                    )
                    continue
            self.logger.info("worktree_manager", f"Cleaning up stale worktree: {wt_dir}")
            # 无 agent 存活才走到这里：一并清掉残留测试子进程（dev-server 孤儿），
            # 避免删目录后留下 cwd 失效的永生进程
            self._kill_worktree_strays(wt_dir.name)
            try:
                branch = None
                br = subprocess.run(
                    ["git", "-C", str(wt_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, timeout=10,
                )
                if br.returncode == 0:
                    branch = br.stdout.strip()
                res = subprocess.run(
                    ["git", "-C", str(self.project_root), "worktree", "remove",
                     str(wt_dir), "--force"],
                    capture_output=True, text=True, timeout=30,
                )
                if res.returncode != 0:
                    shutil.rmtree(str(wt_dir), ignore_errors=True)
                if branch and branch != "HEAD":
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "branch", "-D", branch],
                        capture_output=True, timeout=10,
                    )
            except Exception as e:
                self.logger.warning("worktree_manager", f"Stale worktree cleanup failed: {e}")
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True, timeout=10,
        )

    def get_branch_name(self, wt_path: Path) -> Optional[str]:
        """Return the branch name for an active worktree, or None if unknown."""
        return self._wt_branches.get(str(wt_path))

    def merge_back_from_branch(self, branch: str) -> MergeConflictInfo:
        """Merge a worktree branch into the main tree (project_root HEAD).

        与 merge_back(wt_path) 等价，但直接接受分支名。用于 worktree 已被清理、
        但分支仍保留的场景（implementer 成功路径）。

        主树干净由 guard 原子保证（fix-autostash-orphans）：锁内 stash→merge→pop
        同步段完成。不再依赖「派发前 stash + 成功路径才 pop」的长窗口配对——
        那种配对在任何失败/重派/异常/daemon 重启路径下都会把用户未提交改动
        滞留在 stash 栈（曾致 7 次改动"消失"事故）。段内 pop 弹到的必是刚 push
        的条目（锁串行 + LIFO），历史滞留条目由周期巡检兜底回收。

        预演闸（add-merge-tree-rehearsal D1）：真合并（stash/merge/abort 序列）
        之前先以 ``git merge-tree --write-tree`` 只读预演。语义冲突在主树零污染
        点被拦截——不 stash、不 merge、不 abort，直接返回带 ``rehearsed=True``
        标记的结构化冲突分类，调度层据此直通 repair 通道（spec 保持 in-flight、
        不经 fp 记账）；零冲突与纯产物/ignored-DU 冲突放行现行流程逐字节不变。

        Returns: ``MergeConflictInfo``——兼容 ``(bool, str)`` 解包
        （``success, err = merge_back_from_branch(...)``），额外携带冲突路径
        清单与语义冲突分类（add-merge-back-repair-lane D1，供调度层决定是否
        进入 repair 通道）。
        """
        if not branch:
            return MergeConflictInfo(False, "Empty branch name")

        with self._main_tree_lock:
            # 预演闸（add-merge-tree-rehearsal D1/D2）：guard 锁内、stash 之前只读
            # 预演。语义冲突 → 直接返回 rehearsed 标记（主树零污染，调度层直通
            # repair）；None = 放行（零冲突或产物/ignored-DU 冲突）→ 走现行流程。
            rehearsed_info = self._rehearse_merge_from_branch(branch)
            if rehearsed_info is not None:
                return rehearsed_info

            self.last_stash_pop_conflicts = []
            self.last_stash_entry_fate = {"kept": True, "sha": ""}
            # WIP 重叠预检（fix-mergeback-stashpop-silent-loss D3）：预演闸放行后、
            # stash 之前，检测「分支改动文件 ∩ 主树脏 tracked 文件」。只读、不阻断
            # ——重叠仅是预警（不同 hunk 可自动合并），清单挂到返回的
            # MergeConflictInfo.wip_overlap 供 dispatch 并入告警文本。
            wip_overlap = self._detect_wip_overlap(branch)

            stashed = self.ensure_clean_tree()
            try:
                info = self._merge_back_from_branch_locked(branch)
                info.wip_overlap = wip_overlap
                return info
            finally:
                if stashed:
                    _ok, conflict_files = self.restore_after_merge()
                    if conflict_files:
                        self.last_stash_pop_conflicts = list(conflict_files)

    def _detect_wip_overlap(self, branch: str) -> list:
        """merge-back 前 WIP 重叠预检（fix-mergeback-stashpop-silent-loss D3）。

        计算主树脏 tracked 文件与 ``merge-base..branch`` 分支改动文件的交集。
        非空 → 记 WARNING（含重叠清单），返回清单供挂到 MergeConflictInfo；
        空/命令失败 → 返回空列表、零行为变化。只读不阻断：不 stash、不改状态。

        Returns: 排序后的重叠文件路径列表（无重叠为空列表）。
        """
        try:
            dirty = self._list_dirty_tracked_files()
            if not dirty:
                return []
            mb = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "merge-base", "HEAD", branch],
                capture_output=True, text=True, timeout=30,
            )
            if mb.returncode != 0 or not mb.stdout.strip():
                return []
            diff = subprocess.run(
                ["git", "-C", str(self.project_root), "diff", "--name-only",
                 mb.stdout.strip(), branch],
                capture_output=True, text=True, timeout=30,
            )
            if diff.returncode != 0:
                return []
            branch_files = {ln.strip() for ln in diff.stdout.splitlines() if ln.strip()}
            overlap = sorted(set(dirty) & branch_files)
            if overlap:
                self.logger.warning(
                    "worktree_manager",
                    f"WIP overlap precheck before merge-back of '{branch}': "
                    f"{len(overlap)} dirty tracked file(s) also changed on branch "
                    f"— {overlap} (warning only, merge proceeds)",
                )
            return overlap
        except (subprocess.TimeoutExpired, OSError):
            return []

    # ── merge-tree 预演闸（add-merge-tree-rehearsal D1/D4）───────────────────
    # 真合并前以 `git merge-tree --write-tree` 只读预演（不触碰主树索引与工作区），
    # 语义冲突在主树零污染点被拦截并直通 repair；零冲突/产物/ignored-DU 放行现行
    # 流程。git ≥ 2.38 可用性一次性探测（类级缓存），不支持整体回退现行行为。

    def _merge_tree_supported(self) -> bool:
        """``git merge-tree --write-tree`` 可用性一次性探测（进程内缓存）。

        以空参试探：git ≥ 2.38 支持该选项（输出 usage）；旧版把未知选项报为
        ``unknown option``。探测结果类级缓存（多实例共享、进程一生只探一次），
        不支持时记一次性 WARNING（不刷屏），预演闸永久跳过。
        """
        if not WorktreeManager._rehearsal_probe_done:
            try:
                res = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "merge-tree", "--write-tree"],
                    capture_output=True, text=True, timeout=30,
                )
                WorktreeManager._rehearsal_supported = (
                    "unknown option" not in res.stderr
                )
            except (subprocess.SubprocessError, OSError):
                WorktreeManager._rehearsal_supported = False
            WorktreeManager._rehearsal_probe_done = True
            if not WorktreeManager._rehearsal_supported:
                self.logger.warning(
                    "worktree_manager",
                    "git merge-tree --write-tree 不可用（需 git ≥ 2.38）— "
                    "merge 预演闸跳过，行为回退现行",
                )
        return WorktreeManager._rehearsal_supported

    def _rehearse_merge_from_branch(self, branch: str) -> Optional[MergeConflictInfo]:
        """真合并前只读预演（add-merge-tree-rehearsal D1/D2/D4）。

        在 ``_main_tree_lock`` 内、stash 之前调用。以 ``git merge-tree --write-tree
        --name-only HEAD <branch>`` 预演分支并入主树的结果：

        - 返回 ``None``：放行——零冲突，或预演检出冲突全部为构建产物/被 .gitignore
          忽略的 DU 运行时草稿（这两类在现行真合并里由既有产物/ignored 自愈收口，
          行为不变）；
        - 返回 ``MergeConflictInfo``（``rehearsed=True``）：预演检出语义冲突，主树
          未被 stash/merge/abort 触碰，调度层据此直通 repair 通道。

        git 不支持 merge-tree、或预演命令失败/超时时同样返回 ``None``（保守：
        宁可行现行行为，不因预演故障误拦合并）。预演自身不修改主树与分支的任何
        状态（merge-tree 只读、不触索引与工作区）。
        """
        if not self._merge_tree_supported():
            return None
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "merge-tree", "--write-tree", "--name-only",
                 "HEAD", branch],
                capture_output=True, text=True, timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if res.returncode == 0:
            # 零冲突：放行现行真合并流程（逐字节不变）
            return None
        conflict_paths = self._parse_merge_tree_conflict_paths(res.stdout)
        if not conflict_paths:
            return None
        # 分类复用既有产物前缀判定（与 abort 后分类口径一致）：非产物路径
        # 全部为被忽略的 DU 运行时草稿时才放行，其余视为语义冲突直通 repair。
        non_artifact = [p for p in conflict_paths if not _is_build_artifact_path(p)]
        if not non_artifact:
            return None
        if all(self._rehearsed_path_is_ignored_du(p) for p in non_artifact):
            return None
        # 语义冲突：主树零污染直通 repair。冲突清单只保留语义路径（与 abort 后
        # 分类一致——产物路径由框架自愈负责，不污染 repair agent 的冲突上下文）。
        self.logger.info(
            "worktree_manager",
            f"Merge rehearsal detected semantic conflicts for branch '{branch}': "
            f"{len(non_artifact)} path(s) {non_artifact} (total {len(conflict_paths)})"
            f" — direct to repair lane, main tree untouched",
        )
        return MergeConflictInfo(
            False,
            f"Semantic merge conflicts detected by pre-merge rehearsal "
            f"({len(non_artifact)} path(s))",
            conflict_paths=non_artifact,
            self_heal_applicable=False,
            has_semantic_conflict=True,
            rehearsed=True,
        )

    def _parse_merge_tree_conflict_paths(self, stdout: str) -> list:
        """解析 ``merge-tree --write-tree --name-only`` 输出中的冲突路径清单。

        冲突时输出结构：首行为结果 tree oid，其后冲突路径每行一个，空行后为
        信息行（Auto-merging / CONFLICT ...）。rename 双胞胎的 base 旧路径与
        两侧新路径都会列出——与 ``_collect_conflict_paths``（git status --porcelain
        的 rename ``old -> new`` 双胞胎两侧都计入）口径一致。
        """
        paths: list = []
        for line in stdout.splitlines()[1:]:
            if not line.strip():
                break
            if line.startswith("CONFLICT"):
                break
            paths.append(line.strip())
        return [p for p in paths if p]

    def _rehearsed_path_is_ignored_du(self, path: str) -> bool:
        """预演分类：非产物冲突路径是否为「被 .gitignore 忽略的运行时草稿」。

        与 abort 后 ``_resolve_ignored_modify_delete_conflicts``（仅处理 DU——
        主树删除、分支修改）口径一致：主树已删除该路径时它在 HEAD 索引中不
        存在，``git check-ignore`` 判定可靠；反向（分支删除、主树修改）路径仍
        tracked → check-ignore 返回非零 → 判为语义冲突直通，真合并中该自愈
        （仅接受 DU 状态码）同样不适用。命令失败保守返回 False。
        """
        try:
            chk = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "check-ignore", "-q", "--", path],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        return chk.returncode == 0

    def _merge_back_from_branch_locked(self, branch: str) -> MergeConflictInfo:
        """merge_back_from_branch 的实现体，调用方必须已持有 _main_tree_lock。

        Returns: ``MergeConflictInfo``——兼容 ``(bool, str)`` 解包，额外携带
        冲突路径清单与语义冲突分类（add-merge-back-repair-lane D1，供调度层
        决定是否进入 repair 通道）。
        """
        try:
            # Idempotency check: is branch already an ancestor of HEAD?
            ancestor = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "merge-base", "--is-ancestor", branch, "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            if ancestor.returncode == 0:
                self.logger.info(
                    "worktree_manager",
                    f"Branch '{branch}' already merged — skipping merge-back",
                )
                return MergeConflictInfo(True, "already merged")

            # WIP 塌缩（add-impl-wip-checkpoint D4）：merge-back 前把分支上的
            # ``fenix(wip):`` 前缀提交塌缩为单提交——主树历史零 WIP 污染。
            # 无 WIP 提交时零动作（常规成功路径逐字节现行行为）；失败仅
            # WARNING 降级，merge-back 以未塌缩分支继续（D6）。塌缩是分支
            # 引用级 soft-reset 语义操作，文件内容逐字节不变。
            collapse_wip_commits(self.project_root, branch, self.logger)

            # merge 前按 implementer 分支新增路径，把主树中冲突的 untracked 文件移开
            # （Layer 2 兜底，fix-merge-untracked-guard 泛化）：即使 spec 未被
            # ensure_spec_committed 提交、或产物路径有污染，也不让 merge 因 untracked 冲突死锁。
            backup = self._backup_untracked_spec_files(branch)
            head_before = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()

            # Merge with --no-ff to preserve worktree history
            result = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "merge", "--no-ff", branch,
                 "-m", f"[fenix] merge implementer branch {branch}"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                error = (result.stderr.strip() or result.stdout.strip()
                         or f"exit code {result.returncode}")
                # DRY 自愈（fix-merge-dirty-ignored-draft）：主树被 ignore 的 tracked
                # 运行时草稿带未提交修改、而 merge 需写该路径时，git 直接拒绝且不进入
                # 冲突态（_resolve_ignored_modify_delete_conflicts 覆盖不到）。移出后重试。
                blockers = self._parse_merge_blockers(error)
                if blockers and self._untrack_ignored_local_changes(blockers):
                    result = subprocess.run(
                        ["git", "-C", str(self.project_root),
                         "merge", "--no-ff", branch,
                         "-m", f"[fenix] merge implementer branch {branch}"],
                        capture_output=True, text=True, timeout=120,
                    )
                elif blockers and self._discard_identical_local_changes(blockers, branch):
                    result = subprocess.run(
                        ["git", "-C", str(self.project_root),
                         "merge", "--no-ff", branch,
                         "-m", f"[fenix] merge implementer branch {branch}"],
                        capture_output=True, text=True, timeout=120,
                    )
            if result.returncode == 0:
                self._drop_backup(backup)
                # merge 成功后把随分支带回 tracked 的 ignored 草稿移出（防撞车循环重启）
                if head_before:
                    self._purge_ignored_brought_in(head_before)
                # dist 冲突根治 B：触碰 static src 的 merge 从合并后 src 重建 dist
                self._rebuild_dist_after_merge()
                self.logger.info(
                    "worktree_manager",
                    f"Merged branch '{branch}' into main tree",
                )
                return MergeConflictInfo(True, "")

            error = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            self.logger.error(
                "worktree_manager",
                f"Merge failed for branch '{branch}': {error}",
            )
            # 构建产物冲突自愈（add-v3-spec-quick-switch / add-project-description
            # 事故治理）：实现分支各自重建 dist，内容哈希文件名跨分支必然
            # rename/delete 打架——这不是语义冲突。全部冲突路径位于构建产物目录时，
            # dist 整目录对齐实现分支版本（含本 spec 功能构建）并完成 merge；
            # dist 与合并后 src 的最终一致性由后续"merge 后从 src 重建"刷新。
            # 先于 ignored-DU 自愈跑：其判定为只读收集、解决精确（含产物 DU），
            # 而 ignored 自愈会先 rm --cached 改变冲突态、校验失败时 abort 整个
            # merge——若它先行，产物 DU 场景轮不到本自愈（add-dashboard-
            # incremental-data 目录重命名事故根因之二）。
            if self._resolve_build_artifact_conflicts(branch):
                self._drop_backup(backup)
                # dist 冲突根治 B：自愈 merge 同样从合并后 src 重建收口
                self._rebuild_dist_after_merge()
                self.logger.info(
                    "worktree_manager",
                    f"Merge conflict self-healed (build artifacts aligned to "
                    f"branch) for branch '{branch}'",
                )
                return MergeConflictInfo(
                    True, "", self_heal_applicable=True, self_heal_succeeded=True,
                )
            # merge 冲突自愈（fix-merge-modify-delete-ignored）：modify/delete 冲突
            # 且全部冲突路径都是 .gitignore 忽略的运行时草稿时，采纳主树侧的删除。
            # 场景：run-result 类草稿在移出版本控制前派生的旧分支上被改动，与主树的
            # 删除相撞——被忽略的草稿不是交付物，不应让 merge-back 死锁。
            if self._resolve_ignored_modify_delete_conflicts():
                self._drop_backup(backup)
                # dist 冲突根治 B：该路径同样可能并入 static src 变更
                self._rebuild_dist_after_merge()
                self.logger.info(
                    "worktree_manager",
                    f"Merge conflict self-healed (modify/delete on ignored files) "
                    f"for branch '{branch}'",
                )
                return MergeConflictInfo(
                    True, "", self_heal_applicable=True, self_heal_succeeded=True,
                )
            # ── 语义冲突分类收集（add-merge-back-repair-lane D1）────────────
            # 两级自愈均不适用（冲突含非产物语义文件）时，在 abort **之前**采集
            # unmerged 冲突路径清单，并判定是否仍含语义冲突。返回的
            # MergeConflictInfo 携带结构化分类，供调度层决定是否进入 repair 通道；
            # 主树 abort 后保持干净（merge --abort 本身幂等，重复 abort 无害）。
            conflict_paths = self._collect_conflict_paths()
            self_heal_applicable = bool(conflict_paths) and all(
                _is_build_artifact_path(p) for p in conflict_paths
            )
            has_semantic_conflict = any(
                not _is_build_artifact_path(p) for p in conflict_paths
            )
            if conflict_paths:
                self.logger.warning(
                    "worktree_manager",
                    f"Merge conflict not self-healable for branch '{branch}': "
                    f"{len(conflict_paths)} path(s), "
                    f"semantic={has_semantic_conflict} — collecting for repair decision",
                )
            # Abort the merge so main tree is left clean for retry
            subprocess.run(
                ["git", "-C", str(self.project_root), "merge", "--abort"],
                capture_output=True, text=True, timeout=30,
            )
            # 恢复被移开的 untracked 文件（不丢数据，供下一轮重试）
            self._restore_backup(backup)
            return MergeConflictInfo(
                False, error,
                conflict_paths=conflict_paths,
                self_heal_applicable=self_heal_applicable,
                has_semantic_conflict=has_semantic_conflict,
            )

        except subprocess.TimeoutExpired:
            return MergeConflictInfo(False, "git merge timed out after 120s")
        except Exception as e:
            return MergeConflictInfo(False, str(e))

    def _resolve_build_artifact_conflicts(self, branch: str) -> bool:
        """merge 冲突自愈：产物冲突无条件对齐 HEAD，语义冲突只看非产物路径。

        dist 冲突根治 A（2026-09-04 task-track 混合冲突连坐治理）。仅分支模式
        调用（merge 冲突态中）。判定与解决：
        1. ``git status --porcelain`` 收集 unmerged 条目（rename 形如
           ``old -> new`` 两侧路径都计入）；
        2. 无产物冲突路径 → False（纯语义冲突，交回调用方语义路径）；
        3. 产物路径**无条件对齐 HEAD**：HEAD 存在 → checkout HEAD -- p；
           HEAD 已删 → git rm。不再区分对齐分支版/主树版——merge 时 dist 永远
           以主树为准，分支重建的最终一致性由 merge 后 ``_rebuild_dist_after_merge``
           从合并后 src 确定性重建（dist 只是 src 的投影）；
        4. 收口：分支侧**干净 add** 的产物（非冲突新增，如新 hash chunk）一律
           移除，不复活旧构建物（原「布局被主树移动」场景的 stray 收口无条件化）；
        5. 全部冲突均为产物 → commit 完成 merge，return True；仍有语义冲突 →
           return False（**不 abort**——调用方语义路径统一 abort 并分类，
           此时收集到的冲突清单只含语义文件，失败指纹不再被 dist 噪声污染）。

        Returns: True 表示自愈完成且 merge 已提交。
        """
        if not branch:
            return False
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
            if res.returncode != 0:
                return False

            def _collect_unmerged(status_text: str) -> list:
                paths: list = []
                for line in status_text.splitlines():
                    st = line[:2]
                    if not ("U" in st or st in ("AA", "DD", "AU", "UA", "DU", "UD")):
                        continue
                    path = line[3:].strip()
                    if " -> " in path:
                        paths.extend(p.strip() for p in path.split(" -> "))
                    else:
                        paths.append(path)
                return [p for p in paths if p]

            conflict_paths = _collect_unmerged(res.stdout)
            if not conflict_paths:
                return False
            artifact_paths = [
                p for p in conflict_paths if _is_build_artifact_path(p)]
            if not artifact_paths:
                return False

            # 产物路径无条件对齐 HEAD（HEAD 存在→取 HEAD 版；HEAD 已删→删除）
            head_artifacts = self._artifact_paths("HEAD")
            for p in artifact_paths:
                if p in head_artifacts:
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "checkout",
                         "HEAD", "--", p],
                        capture_output=True, text=True, timeout=60,
                    )
                else:
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "rm", "-f",
                         "--ignore-unmatch", "--", p],
                        capture_output=True, text=True, timeout=30,
                    )
            # 收口：分支侧干净 add 的产物（非冲突新增）不复活——staged 产物中
            # HEAD 没有的一律移除（含旧路径双胞胎、对方重命名后的旧 hash chunk）
            staged = subprocess.run(
                ["git", "-C", str(self.project_root), "diff", "--cached",
                 "--name-only", "--diff-filter=A", "--",
                 DASHBOARD_STATIC_ROOT],
                capture_output=True, text=True, timeout=30,
            )
            if staged.returncode == 0:
                strays = [
                    line for line in staged.stdout.splitlines()
                    if _is_build_artifact_path(line)
                    and line not in head_artifacts
                ]
                for p in strays:
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "rm", "-q",
                         "-f", "--", p],
                        capture_output=True, text=True, timeout=30,
                    )
            # 剩余冲突：非产物路径仍冲突 → 语义冲突，交回调用方（不 abort）
            res2 = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
            remaining = _collect_unmerged(res2.stdout) if res2.returncode == 0 else []
            if remaining:
                self.logger.warning(
                    "worktree_manager",
                    f"Build-artifact conflicts aligned to HEAD "
                    f"({len(artifact_paths)} paths); semantic conflicts remain: "
                    f"{remaining[:5]}",
                )
                return False
            # 完成原 merge
            commit = subprocess.run(
                ["git", "-C", str(self.project_root), "commit", "--no-edit"],
                capture_output=True, text=True, timeout=60,
            )
            if commit.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Build-artifact self-heal commit failed: "
                    f"{(commit.stderr or '').strip()[:200]}",
                )
                subprocess.run(
                    ["git", "-C", str(self.project_root), "merge", "--abort"],
                    capture_output=True, text=True, timeout=30,
                )
                return False
            self.logger.warning(
                "worktree_manager",
                f"Build-artifact conflicts aligned to HEAD "
                f"({len(artifact_paths)} paths) — dist rebuilt from merged src "
                f"afterwards to restore cross-spec consistency",
            )
            return True
        except (subprocess.SubprocessError, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Build-artifact self-heal error: {e}",
            )
            try:
                subprocess.run(
                    ["git", "-C", str(self.project_root), "merge", "--abort"],
                    capture_output=True, text=True, timeout=30,
                )
            except Exception:
                pass
            return False

    def _run_dist_build(self) -> bool:
        """执行主树构建（.fenix/verify.yaml prepare 驱动，回退 npm run build）。

        构建什么从 verify.yaml 的 prepare 段读取——不预设目标为 nodejs 项目，
        步骤自带 cwd、每步受 PREPARE_STEP_TIMEOUT 约束；契约缺失时回退历史
        行为（DASHBOARD_STATIC_ROOT 下 npm run build）；契约存在但未声明
        prepare 视为「无构建步骤」，直接成功。
        供 merge 后确定性重建使用；测试通过 patch 本方法模拟构建产物/失败。
        """
        from core.verify_contract import (
            ensure_main_tree_deps, load_verify_contract, read_config_deps_mode,
            resolve_deps_mode, run_prepare_steps)
        contract = load_verify_contract(self.project_root, self.logger)
        if contract is not None:
            if not contract.prepare:
                return True
            # add-main-tree-deps-provision：merge 后主树重建 dist 与验证同样
            # 可能缺 node_modules（主树只被 merge-back 写入、无人手工安装），
            # prepare 前按 cwd 集合预装依赖（mode 无 pm 配置通道，走
            # read_config_deps_mode + resolve_deps_mode 同源解析）。
            ensure_main_tree_deps(
                self.project_root,
                sorted({(s.cwd or ".") for s in contract.prepare}),
                mode=resolve_deps_mode(
                    contract, read_config_deps_mode(self.project_root)),
                logger=self.logger,
            )
            err = run_prepare_steps(contract, self.project_root)
            if err:
                self.logger.warning(
                    "worktree_manager",
                    f"dist rebuild prepare 失败: {err}",
                )
                return False
            return True
        static_dir = self.project_root / DASHBOARD_STATIC_ROOT
        if not (static_dir / "package.json").exists():
            self.logger.warning(
                "worktree_manager",
                f"dist rebuild skipped: no package.json under {DASHBOARD_STATIC_ROOT}",
            )
            return False
        try:
            r = subprocess.run(
                ["npm", "run", "build"], cwd=str(static_dir),
                capture_output=True, text=True, timeout=600,
            )
            return r.returncode == 0
        except (subprocess.SubprocessError, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"dist build invocation failed: {e}",
            )
            return False

    def _rebuild_dist_after_merge(self) -> None:
        """merge 后从合并后 src 确定性重建主树产物（dist 冲突根治 B）。

        dist 已不入库（2026-09-04 决策）：本方法只负责刷新主树工作区产物，
        供常驻 dashboard（实时读盘）立即呈现合并后 UI。git 侧语义：dist 被
        ignore，重建产物不再 amend 进提交（git add 无可暂存）；历史分支仍
        携带跟踪版 dist 时，产物冲突无条件对齐 HEAD（=删除），merge 后重建
        即恢复工作区版。构建内容从 .fenix/verify.yaml prepare 读取（契约
        驱动，见 _run_dist_build）。
        仅当 merge 提交（HEAD^1..HEAD）触碰 static 根下非产物路径时重建。
        失败时保留现有工作区产物并告警——不回滚 merge、不抛异常（merge
        本身的成功语义不被重建失败否定）。
        """
        try:
            diff = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "diff", "--name-only", "HEAD^1", "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            if diff.returncode != 0:
                return
            changed = [l.strip() for l in diff.stdout.splitlines() if l.strip()]
            src_touched = any(
                p.startswith(DASHBOARD_STATIC_ROOT)
                and not _is_build_artifact_path(p)
                for p in changed
            )
            if not src_touched:
                return
            if not self._run_dist_build():
                self.logger.error(
                    "worktree_manager",
                    "dist rebuild failed after merge — keeping committed dist "
                    "(may lag merged src); run `npm run build` in "
                    f"{DASHBOARD_STATIC_ROOT} manually",
                )
                return
            subprocess.run(
                ["git", "-C", str(self.project_root), "add", "-A", "--",
                 DASHBOARD_STATIC_ROOT],
                capture_output=True, text=True, timeout=60,
            )
            staged = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain",
                 "--", DASHBOARD_STATIC_ROOT],
                capture_output=True, text=True, timeout=30,
            )
            if not staged.stdout.strip():
                return  # 重建结果与提交版一致，无需 amend
            amend = subprocess.run(
                ["git", "-C", str(self.project_root), "commit", "--amend",
                 "--no-edit"],
                capture_output=True, text=True, timeout=60,
            )
            if amend.returncode != 0:
                # 恢复干净：unstage + dist 回到提交版，不让脏树阻塞后续 merge
                subprocess.run(
                    ["git", "-C", str(self.project_root), "reset", "-q"],
                    capture_output=True, text=True, timeout=30,
                )
                subprocess.run(
                    ["git", "-C", str(self.project_root), "checkout", "HEAD",
                     "--", DASHBOARD_STATIC_ROOT],
                    capture_output=True, text=True, timeout=60,
                )
                self.logger.error(
                    "worktree_manager",
                    f"dist rebuild amend failed: "
                    f"{(amend.stderr or '').strip()[:200]}",
                )
                return
            self.logger.info(
                "worktree_manager",
                "dist rebuilt from merged src（不入库；常驻 dashboard 读盘即最新）",
            )
        except (subprocess.SubprocessError, OSError) as e:
            self.logger.error(
                "worktree_manager",
                f"dist rebuild after merge failed unexpectedly: {e}",
            )

    def _artifact_paths(self, rev: str) -> set:
        """列出 <rev> 中 static 根下全部构建产物路径（按目录层次容错判定）。"""
        ls = subprocess.run(
            ["git", "-C", str(self.project_root), "ls-tree", "-r",
             "--name-only", rev, DASHBOARD_STATIC_ROOT],
            capture_output=True, text=True, timeout=30,
        )
        if ls.returncode != 0:
            return set()
        return {line for line in ls.stdout.splitlines()
                if _is_build_artifact_path(line)}

    def _parse_merge_blockers(self, error: str) -> list:
        """从 git 的 'local changes would be overwritten by merge' 错误中解析路径。

        错误形如::

            error: Your local changes to the following files would be overwritten by merge:
            \t<path1>
            \t<path2>
            Please commit your changes or stash them before you merge.

        无法解析或不含该错误时返回空列表。
        """
        marker = "would be overwritten by merge:"
        idx = error.find(marker)
        if idx == -1:
            return []
        paths = []
        for line in error[idx + len(marker):].splitlines():
            if not line.strip():
                if paths:
                    break  # 空行＝路径段结束
                continue
            text = line.strip().lstrip("\t").strip()
            if not text or text.startswith(("Please commit", "Aborting", "error:", "Merge with")):
                break
            paths.append(text)
        return paths

    def _untrack_ignored_local_changes(self, paths: list) -> bool:
        """把 merge 需写路径上「被 ignore 的 tracked 本地修改」移出索引并提交。

        场景：implementer 从草稿尚被 tracked 的旧 base 派生分支，把
        .fenix-run-result.json 等运行时草稿提交回来；此后主树 daemon 每轮更新草稿
        留下未提交修改 → merge 需写该路径时被 DRY 检查拒绝
        （add-v3-spec-detail-page 熔断 fp=8acc38c71d41）。被 ignore 的运行时草稿
        不是交付物，不应让 merge-back 死锁。

        用 ``check-ignore --no-index`` 校验：tracked 文件的普通 check-ignore 恒为
        非忽略（误报），--no-index 只按 ignore 规则判定。
        全部路径均被 ignore 才执行（任一未忽略 → 可能是真实交付物，返回 False
        交回原有失败路径）；移出后作为独立提交落盘，随后可重试 merge。

        Returns: True 表示已全部移出并提交，可重试 merge。
        """
        if not paths:
            return False
        try:
            for path in paths:
                chk = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "check-ignore", "--no-index", "-q", "--", path],
                    capture_output=True, text=True, timeout=30,
                )
                if chk.returncode != 0:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (untrack) aborted: '{path}' is not gitignored "
                        f"— not a runtime draft",
                    )
                    return False
            for path in paths:
                rm = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "rm", "-f", "--cached", "--", path],
                    capture_output=True, text=True, timeout=30,
                )
                if rm.returncode != 0:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (untrack): git rm --cached failed for "
                        f"'{path}': {(rm.stderr or rm.stdout).strip()}",
                    )
                    return False
            commit = subprocess.run(
                ["git", "-C", str(self.project_root), "commit",
                 "-m", "[fenix] fix: merge 前移出被误提交的 ignored 运行时草稿"],
                capture_output=True, text=True, timeout=60,
            )
            if commit.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Self-heal (untrack): commit failed: "
                    f"{(commit.stderr or commit.stdout).strip()}",
                )
                return False
            self.logger.info(
                "worktree_manager",
                f"Self-heal (untrack): moved ignored tracked drafts out of index: "
                f"{', '.join(paths)}",
            )
            return True
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _discard_identical_local_changes(self, paths: list, branch: str) -> bool:
        """把「主树未提交修改与分支内容字节级相同」的 tracked 冲突路径恢复干净。

        第四次 merge-back 死锁变体（add-fast-track-mode fp=e7111ce3fea4，
        2026-09-02）：主树遗留一份与 implementer 分支完全相同的已跟踪文件未提交
        修改（实现副本污染），merge 需写该路径被 git 直接拒绝；而
        _untrack_ignored_local_changes 只覆盖 ignored 草稿，真实 tracked 文件
        走不到。内容与分支一致时丢弃主树副本零损失——同一内容随后经 merge
        从分支回到主树。

        保守策略：任一路径缺失、无法读取或内容与分支不一致，则不动任何文件
        返回 False（可能是真实本地工作，交回失败路径人工裁决）。全部一致时
        先备份到 .fenix/merge-backup/identical-<ts>/（不自动恢复：内容可从
        分支取回，备份仅供审计），再 git checkout HEAD -- 恢复。

        Returns: True 表示已全部恢复干净，可重试 merge。
        """
        if not paths:
            return False
        identical = []
        try:
            for path in paths:
                wt_file = self.project_root / path
                if not wt_file.is_file():
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (identical) aborted: '{path}' missing in "
                        f"main tree",
                    )
                    return False
                show = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "show", f"{branch}:{path}"],
                    capture_output=True, timeout=30,
                )
                if show.returncode != 0:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (identical) aborted: '{path}' not readable "
                        f"on branch '{branch}'",
                    )
                    return False
                if wt_file.read_bytes() != show.stdout:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (identical) aborted: '{path}' differs from "
                        f"branch content — possible real local work",
                    )
                    return False
                identical.append(path)
            backup = (self.project_root / ".fenix" / "merge-backup"
                      / f"identical-{int(time.time())}")
            for path in identical:
                dest = backup / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.project_root / path, dest)
            co = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "checkout", "HEAD", "--", *identical],
                capture_output=True, text=True, timeout=30,
            )
            if co.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Self-heal (identical): git checkout failed: "
                    f"{(co.stderr or co.stdout).strip()}",
                )
                return False
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Self-heal (identical) failed: {e}",
            )
            return False
        self.logger.info(
            "worktree_manager",
            f"Self-heal (identical): discarded main-tree copies identical to "
            f"branch '{branch}' (backed up to {backup}): {', '.join(identical)}",
        )
        return True

    def _purge_ignored_brought_in(self, old_head: str) -> None:
        """merge 成功后把被 ignore 却随分支带回 tracked 的路径移出索引。

        与 _untrack_ignored_local_changes 同一根因的另一半：主树草稿干净时 merge
        不会被 DRY 拒绝，但分支提交的草稿会随 merge 进入主树索引——主树重新变回
        tracked，daemon 下一轮更新草稿又留下脏修改，撞车循环重启。merge 完成后
        对本次 merge 新增（--diff-filter=A）且被 ignore 的路径补一次移出
        （工作区副本保留），无此类路径时零开销跳过。
        """
        try:
            diff = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "diff", "--name-only", "--diff-filter=A", f"{old_head}..HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            if diff.returncode != 0 or not diff.stdout.strip():
                return
            victims = []
            for rel in [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]:
                ls = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "ls-files", "--error-unmatch", "--", rel],
                    capture_output=True, text=True, timeout=30,
                )
                if ls.returncode != 0:
                    continue  # 已不在索引（或不存在）
                chk = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "check-ignore", "--no-index", "-q", "--", rel],
                    capture_output=True, text=True, timeout=30,
                )
                if chk.returncode == 0:
                    victims.append(rel)
            if not victims:
                return
            for rel in victims:
                subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "rm", "-f", "--cached", "--", rel],
                    capture_output=True, text=True, timeout=30,
                )
            commit = subprocess.run(
                ["git", "-C", str(self.project_root), "commit",
                 "-m", "[fenix] fix: merge 后移出随分支带回的 ignored 运行时草稿"],
                capture_output=True, text=True, timeout=60,
            )
            if commit.returncode == 0:
                self.logger.info(
                    "worktree_manager",
                    f"Purged ignored drafts brought in by merge: {', '.join(victims)}",
                )
            else:
                self.logger.warning(
                    "worktree_manager",
                    f"Purge commit failed: {(commit.stderr or commit.stdout).strip()}",
                )
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning("worktree_manager", f"Purge ignored brought-in failed: {e}")

    def _resolve_ignored_modify_delete_conflicts(self) -> bool:
        """在 merge 冲突挂起状态下自愈 modify/delete 冲突（仅限被忽略的路径）。

        场景：run-result 类运行时草稿在移出版本控制前派生的旧分支上被改动，
        与主树侧的删除相撞（DU：主树删除、分支修改）。被忽略的草稿不是交付物，
        不应让 merge-back 死锁。

        步骤：存在 DU 冲突且**无其它类型冲突**时，先逐个 ``git rm -f --cached``
        采纳删除（工作区副本保留，供运行时继续使用）——此刻路径已 untracked，
        ``check-ignore`` 判定才可靠（unmerged 条目会被视为 tracked 而误报）；
        再校验全部路径确被 .gitignore 忽略，任何一条不满足则 ``merge --abort``
        回到调用方原有失败路径（分支内容仍可从分支提交找回，不丢数据）；
        全部通过则 ``git commit --no-edit`` 完成 merge。

        Returns: True 表示冲突已全部解决且 merge 已提交。
        """
        try:
            status = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30,
            )
            if status.returncode != 0:
                return False
            du_paths = []
            # 精确的 unmerged 状态码集合：两位均非空格才是冲突
            # （"A "/“M ”等已暂存条目不能误判，否则 merge 中正常并入的新文件会中断自愈）
            unmerged_codes = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
            for line in status.stdout.splitlines():
                xy = line[:2]
                if xy in unmerged_codes:
                    # 只处理 DU（主树删除、分支修改）
                    if xy != "DU":
                        return False
                    du_paths.append(line[3:].strip())
            if not du_paths:
                return False
            for path in du_paths:
                rm = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "rm", "-f", "--cached", "--", path],
                    capture_output=True, text=True, timeout=30,
                )
                if rm.returncode != 0:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal: git rm --cached failed for '{path}': "
                        f"{(rm.stderr or rm.stdout).strip()}",
                    )
                    return False
            for path in du_paths:
                chk = subprocess.run(
                    ["git", "-C", str(self.project_root),
                     "check-ignore", "-q", "--", path],
                    capture_output=True, text=True, timeout=30,
                )
                if chk.returncode != 0:
                    # 未被忽略 → 疑似真实交付物冲突，不自愈，交回 abort 路径
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal aborted: conflicted path '{path}' is not "
                        f"gitignored — not a runtime draft",
                    )
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "merge", "--abort"],
                        capture_output=True, text=True, timeout=30,
                    )
                    return False
            commit = subprocess.run(
                ["git", "-C", str(self.project_root), "commit", "--no-edit"],
                capture_output=True, text=True, timeout=60,
            )
            if commit.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Self-heal: merge commit failed: "
                    f"{(commit.stderr or commit.stdout).strip()}",
                )
                return False
            return True
        except (subprocess.TimeoutExpired, OSError):
            return False

    def merge_back(self, wt_path: Path) -> MergeConflictInfo:
        """Merge the worktree's branch into the main tree (project_root HEAD).

        Uses `git merge --no-ff` to preserve history. Idempotent: if the branch
        is already an ancestor of HEAD, skips and reports success.

        Returns: ``MergeConflictInfo``（兼容 ``(bool, str)`` 解包）。
        """
        wt_str = str(wt_path)
        branch = self._wt_branches.get(wt_str)
        if not branch:
            return MergeConflictInfo(
                False, f"Unknown worktree (no branch recorded): {wt_path}")
        return self.merge_back_from_branch(branch)

    def find_implementer_worktree(self, spec_name: str) -> Optional[Path]:
        """Find the most recent active implementer worktree for a SPEC.

        Looks for directories matching impl-<spec>-* in the base dir.
        Returns the path of the newest one (by mtime), or None if none found.
        """
        if not self.base_dir.is_dir():
            return None
        candidates = []
        prefix = f"impl-{spec_name}-"
        for d in self.base_dir.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                try:
                    candidates.append((d.stat().st_mtime, d))
                except OSError:
                    pass
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    def file_exists_on_branch(self, branch: str, rel_path: str) -> bool:
        """校验某相对路径在分支 HEAD 提交中是否存在（交付物守卫校验基准）。

        实现 run 收工时 worktree 已被清理，唯一留存的交付物是分支提交。
        用 ``git cat-file -e <branch>:<rel_path>`` 做 O(1) 存在性检查——
        纯文件系统/对象库探测，不触发 LLM / 测试 / 网络。

        Args:
            branch: 实现分支名（AgentRunResult.branch）
            rel_path: 相对项目根的交付路径（如 ``core/foo.py``）

        Returns:
            True 表示分支 HEAD 包含该路径（blob 文件，或非空 tree 目录）。
            分支为空 / 不存在 / 路径不存在时返回 False。
        """
        if not branch or not rel_path:
            return False
        try:
            # -e 仅判断对象可达（blob/tree/symlink），不输出内容，零成本。
            result = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "cat-file", "-e", f"{branch}:{rel_path}"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return False
            kind = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "cat-file", "-t", f"{branch}:{rel_path}"],
                capture_output=True, text=True, timeout=30,
            )
            if kind.returncode != 0:
                return False
            # blob（文件）= 落地交付物；tree（目录）同样算落地——git 不追踪空目录，
            # path 为 tree 必然内含文件（如构建产物 dist/ 整目录声明）。
            # 曾为 blob-only：目录声明成为不可满足契约 → 收工守卫确定性缺件 →
            # 打回循环烧预算至 blocked（remove-auto-run-cleanup 死锁事故 2026-09-03）。
            # symlink 等其余类型不算。
            return kind.stdout.strip() in ("blob", "tree")
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    # ── worktree 可用性单源（interrupt-recovery-preserve D5）────────────────
    # recovery 保留判定、resume 派发、复用认领（fast-track 继承、repair 换壳）
    # 三条链路共用 is_available，禁止各链路自行拼装目录/分支判断。以 git 为
    # 真相（git worktree list + rev-parse --verify），不信任内存表
    # （_active_worktrees/_wt_branches，daemon 重启即失）。

    def is_available(self, wt_path=None, branch=None) -> str:
        """worktree 可用性三态单源查询（interrupt-recovery-preserve D5）。

        三态：
          - ``WT_AVAILABLE``（available）：分支可解析 + worktree 目录在场 +
            ``git worktree list`` 注册有效 → 原地可用，resume/reuse 直接进入；
          - ``WT_REBUILDABLE``（rebuildable）：分支可解析但无有效 worktree
            目录/注册（目录被外部删除、或从未在该分支建过 worktree）→ 可在
            既有分支上重建（checkout 而非 ``-b`` 新建）；
          - ``WT_UNAVAILABLE``（unavailable）：分支不可解析（已并入主树/已
            清扫/typo 分支名）→ 不可用，调用方降级到清空重建。

        Args:
            wt_path: 候选 worktree 路径（Path/str，可选）。提供时与 git 注册
                结果核对：与注册不符的残留目录不视为可用（以 git 为准）。
            branch: 分支名（可选）。缺省时尝试从 wt_path 的 HEAD 解析分支。

        Returns: 三态字符串之一（WT_* 常量）。
        """
        if not branch:
            if wt_path is not None:
                branch = self._guess_branch_from_worktree(wt_path)
            if not branch:
                branch = self._wt_branches.get(str(wt_path)) if wt_path is not None else None
            if not branch:
                return WT_UNAVAILABLE
        if not self.branch_exists(branch):
            return WT_UNAVAILABLE
        registered = self.find_worktree_path(branch)
        if wt_path is not None:
            # 显式候选路径：以其自身目录存在性为「原地可用」判据——防止对
            # 已删目录盲派发（fix-resume-stale-worktree 同源缺口）。目录残留
            # 但非本分支 git 注册 worktree 时同样不可原地使用（以 git 为准）。
            candidate = Path(wt_path)
            if not candidate.is_dir():
                return WT_REBUILDABLE  # 分支在 → 可从分支重建
            if registered is not None and str(Path(registered)) == str(candidate):
                return WT_AVAILABLE
            return WT_REBUILDABLE
        # 未给候选路径：以 git 注册为真相
        if registered is None or not Path(registered).is_dir():
            # 分支可解析但 git 无有效注册 worktree：目录即使残留也不可用，
            # 应从分支重建载体。
            return WT_REBUILDABLE
        return WT_AVAILABLE

    # ── repair 通道：分支载体解析（add-merge-back-repair-lane D3）────────────
    # repair 以「git 事实」为判定基准（git worktree list + 分支解析），不信任
    # 内存表（daemon 重启即失）。三态：
    #   (a) 原 worktree 在 → 原地进入（保留 node_modules/构建缓存）
    #   (b) worktree 清但分支在 → 在分支上新建 worktree（checkout 既有分支）
    #   (c) 分支不在 → 回退 fallback（调度层决议，本层返回 None）

    def create_worktree_on_branch(self, spec_name: str, branch: str) -> Optional[Path]:
        """在既有分支上创建 worktree（checkout 而非 ``-b`` 新建），供 repair 换壳。

        worktree 目录名 ``repair-<spec>-<ts>``（区别于 impl-/verify- 前缀，
        Dashboard/runs 检索据此辨识）。仅登记活动集与分支映射，不 seed spec
        文件（分支已含实现历史，spec 文档已在其中）。

        Returns: worktree 路径，失败（分支不存在/该分支已有 worktree/git
        错误/异常）返回 None。
        """
        if not branch:
            return None
        timestamp = int(time.time())
        wt_name = f"repair-{spec_name}-{timestamp}"
        wt_path = self.base_dir / wt_name
        try:
            # 分支必须存在（rev-parse --verify 精确校验，防 typo 分支名）
            verify = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "rev-parse", "--verify", branch],
                capture_output=True, text=True, timeout=10,
            )
            if verify.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"create_worktree_on_branch: branch '{branch}' not found — "
                    f"cannot re-shell repair site for '{spec_name}'",
                )
                return None
            # 清理陈注册（interrupt-recovery-preserve D5）：目录被外部删除但
            # worktree 注册仍在时，git 会拒绝「该分支已 checkout」。prune 只
            # 移除目录已消失的注册，安全幂等；失败不阻塞（create 自会报错）。
            try:
                subprocess.run(
                    ["git", "-C", str(self.project_root), "worktree", "prune"],
                    capture_output=True, text=True, timeout=10,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
            result = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "worktree", "add", str(wt_path), branch],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self.logger.error(
                    "worktree_manager",
                    f"Failed to create worktree on branch '{branch}': {result.stderr}",
                )
                return None
            self._active_worktrees.add(str(wt_path))
            self._wt_branches[str(wt_path)] = branch
            self.logger.info(
                "worktree_manager",
                f"Worktree re-shelled on existing branch '{branch}': {wt_path}",
            )
            return wt_path
        except subprocess.TimeoutExpired:
            self.logger.error("worktree_manager", "Worktree-on-branch creation timed out")
            return None
        except Exception as e:
            self.logger.error("worktree_manager", f"Worktree-on-branch creation error: {e}")
            return None

    def find_worktree_path(self, branch: str) -> Optional[Path]:
        """按分支解析 worktree 路径（``git worktree list --porcelain`` 为准）。

        add-merge-back-repair-lane D3：以 git 事实为判定基准，不信任内存
        ``_active_worktrees``（daemon 重启即失）。同一分支 git 只允许一个
        worktree（``worktree add <path> <branch>`` 对已 checkout 分支会拒绝），
        故首个匹配即唯一。

        Returns: worktree 绝对路径，无匹配/命令失败返回 None。
        """
        if not branch:
            return None
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "worktree", "list", "--porcelain"],
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            return None
        if res.returncode != 0:
            return None
        current_path: Optional[str] = None
        for line in res.stdout.splitlines():
            if line.startswith("worktree "):
                current_path = line[len("worktree "):].strip()
            elif line.startswith("branch "):
                listed_branch = line[len("branch "):].strip()
                # porcelain 格式：branch refs/heads/<name>；HEAD <sha> 行只是
                # 头部提交指针，不是 detached 判定——detached worktree 缺失
                # branch 行（该 section 不会匹配具名分支，下个 worktree 行覆盖）
                if listed_branch == f"refs/heads/{branch}" and current_path:
                    return Path(current_path)
        return None

    def find_worktree_by_spec(self, spec_name: str) -> Optional[tuple]:
        """按 spec 名反查在册 worktree 与其分支（fix-preserve-chain-first-round-gap D1）。

        保全（``_preserve_interrupted_runs``）与恢复保留判定
        （``_recovery_preserve_spec``）在 STATE ``branch`` 缺失（首轮在飞
        run 未到终态）时的回落源：以 ``git worktree list --porcelain`` 为
        真相，不信任 ``_active_worktrees`` / ``_wt_branches`` 内存表（daemon
        重启即失，不足以支撑 boot 路径）。

        - 按 worktree 目录命名约定（``impl-<spec>-<ts>`` / ``verify-<spec>-<ts>``
          / ``repair-<spec>-<ts>``，见 create/create_worktree_on_branch）以
          **完整 spec 名 + 分隔符边界**匹配（解析命名得完整 spec 名再精确比较，
          禁止子串包含：spec 名互为前缀如 ``fix-x`` 与 ``fix-x-y`` 不误匹配）；
        - 歧义命中（同一 spec 存在多个在册 worktree）MUST NOT 静默取首个，
          返回 None 并 WARNING；
        - 候选经 ``is_available`` 三态单源校验：非 available/rebuildable
          不作保全与保留依据；
        - 命令超时/非零退出/异常降级 WARNING 返回 None，MUST NOT 阻塞停机路径。

        Returns: ``(wt_path, branch)`` 元组；无匹配/歧义/不可用/git 失败返回 None。
        """
        if not spec_name:
            return None
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "worktree", "list", "--porcelain"],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"find_worktree_by_spec('{spec_name}') 查询失败（降级不阻塞）: {e}",
            )
            return None
        if res.returncode != 0:
            self.logger.warning(
                "worktree_manager",
                f"find_worktree_by_spec('{spec_name}') git 非零退出（降级不阻塞）: "
                f"{res.stderr.strip()}",
            )
            return None

        # porcelain 渲染：`worktree <path>` 开新段，其后属行（HEAD/branch）属于
        # 该段；detached worktree 无 branch 行，取不到具名分支，不作保全依据。
        candidates: list = []  # (wt_path, branch) 具名精确匹配的候选
        current_path: Optional[str] = None
        for line in res.stdout.splitlines():
            if line.startswith("worktree "):
                current_path = line[len("worktree "):].strip()
                continue
            if line.startswith("branch ") and current_path:
                listed_branch = line[len("branch "):].strip()
                if listed_branch.startswith("refs/heads/"):
                    listed_branch = listed_branch[len("refs/heads/"):]
                if self._wt_name_matches_spec(Path(current_path).name, spec_name):
                    candidates.append((current_path, listed_branch))

        if not candidates:
            return None
        # is_available 三态单源校验：非 available/rebuildable 候选不作为依据
        valid: list = []
        for path, branch in candidates:
            state = self.is_available(path, branch)
            if state in (WT_AVAILABLE, WT_REBUILDABLE):
                valid.append((path, branch))
            else:
                self.logger.warning(
                    "worktree_manager",
                    f"find_worktree_by_spec('{spec_name}'): 候选 {path} "
                    f"(branch {branch}) 三态 {state}，不作保全/保留依据",
                )
        if len(valid) > 1:
            self.logger.warning(
                "worktree_manager",
                f"find_worktree_by_spec('{spec_name}'): 歧义命中 {len(valid)} 个 "
                f"在册 worktree（{[p for p, _ in valid]}）——不静默取首个，"
                f"按不可用处理",
            )
            return None
        if valid:
            return valid[0]
        return None

    @staticmethod
    def _wt_name_matches_spec(wt_name: str, spec_name: str) -> bool:
        """worktree 目录名是否精确对应 spec（``{impl,verify,repair}-<spec>-<ts>``）。

        从目录名解析出完整 spec 再与目标精确比较（分隔符边界锚定，禁止子串
        包含）：``impl-fix-x-1`` 对 spec ``fix-x`` 命中、对 ``fix`` 不命中。
        非本框架命名（前缀不识别/缺时间戳段）返回 False。
        """
        if not wt_name or not spec_name:
            return False
        for prefix in ("impl", "verify", "repair"):
            if wt_name.startswith(f"{prefix}-"):
                rest = wt_name[len(prefix) + 1:]
                parts = rest.rsplit("-", 1)
                if len(parts) == 2 and parts[0] and parts[1].isdigit():
                    return parts[0] == spec_name
                return False
        return False

    def branch_exists(self, branch: str) -> bool:
        """分支是否存在（``git rev-parse --verify``）。repair 三态判定基准。"""
        if not branch:
            return False
        try:
            verify = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "rev-parse", "--verify", branch],
                capture_output=True, text=True, timeout=10,
            )
            return verify.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def resolve_repair_site(self, spec_name: str, branch: str):
        """解析 repair/恢复续做 分支载体三态（共用 is_available 单源查询，D5）。

        与 resolve_resume_site 同源（repair 换壳 / recovery 保留 续做）：
        - WT_AVAILABLE → 原地（git 注册的 worktree，登记活动集供 cleanup/sweeper 豁免）
        - WT_REBUILDABLE → 在既有分支上重建 worktree（checkout，create_worktree_on_branch）
        - WT_UNAVAILABLE → (None, None)，调用方降级清空重建

        Returns:
            - ``(wt_path, branch)``：载体可用——wt_path 为原 worktree（原地）
              或换壳新建的 worktree；branch 为实现分支名。
            - ``(None, None)``：载体不可用，调度层全新重派。
            产物自愈可静态判断本方法不涉 — 是否进入 repair 由调度层决定。
        """
        if not branch:
            return None, None
        avail = self.is_available(branch=branch)
        if avail == WT_UNAVAILABLE:
            return None, None
        if avail == WT_AVAILABLE:
            existing = self.find_worktree_path(branch)
            if existing is not None:
                self._active_worktrees.add(str(existing))
                self._wt_branches[str(existing)] = branch
                return existing, branch
        # WT_REBUILDABLE（或 WT_AVAILABLE 但 find_worktree_path 意外返回 None）
        wt = self.create_worktree_on_branch(spec_name, branch)
        if wt is None:
            return None, None
        return wt, branch

    def resolve_resume_site(self, spec_name: str, branch: str):
        """恢复续做载体三态解析（interrupt-recovery-preserve D4/D5）。

        与 resolve_repair_site 同源（共用 is_available 单源查询），语义相同：
        - WT_AVAILABLE → 原地续做（保留 node_modules/构建缓存/--resume 会话）
        - WT_REBUILDABLE → 在既有分支上重建 worktree（checkout，不从零新建分支）
        - WT_UNAVAILABLE → (None, None)，调用方降级清空重建并 WARNING

        与 resolve_repair_site 的区分：命名恢复专用（可独立演进语义），当前
        行为等价。resume 续做在 dispatch 层通过 pre_wt_path 进入 _execute_agent，
        复用 implementer 的 prompt 构建与 claude --resume 断点续跑。
        """
        return self.resolve_repair_site(spec_name, branch)

    def claim_legacy_for_repair(self, spec_name: str) -> Optional[dict]:
        """repair 认领时摘出 _legacy 登记（add-merge-back-repair-lane D4）。

        与 fast-track ``_take_reusable_worktree`` 同款 take 动作：认领即从
        ``_legacy`` 登记表摘出，sweeper 宽限期超时后不再回收该现场（遗产豁免
        只在登记期内生效）。物理回收（目录/分支）由 repair 链收尾决定——
        成功路径 consume_legacy，fallback 由调度层按既有清扫策略处理。

        Returns: 被摘出的遗产记录 dict（结构同 register_legacy），无则 None。
        """
        rec = self._legacy.pop(spec_name, None)
        if rec:
            self.logger.info(
                "worktree_manager",
                f"Repair claimed legacy for '{spec_name}': "
                f"worktree={rec.get('path')} branch={rec.get('branch')}",
            )
        return rec
