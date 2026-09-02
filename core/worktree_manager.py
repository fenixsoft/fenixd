"""
worktree_manager.py — Git worktree lifecycle management.

Creates, tracks, and cleans up isolated git worktrees for Agent runs.
Ensures parallel Agents don't conflict.
"""

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Set, Dict

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


class WorktreeManager:
    """
    Manage git worktree lifecycle for Agent isolation.

    Each Agent run gets its own worktree:
      - Implementer: .claude/worktrees/<spec>-<timestamp>/ on branch fenix/<spec>
      - Verifier:    .claude/worktrees/verify-<spec>-<timestamp>/ on branch fenix/verify-<spec>
    """

    def __init__(self, base_dir: Path, project_root: Path, logger, process_scanner=None):
        self.base_dir = Path(base_dir)
        self.project_root = Path(project_root)
        self.logger = logger
        self._active_worktrees: Set[str] = set()
        self._wt_branches: Dict[str, str] = {}  # wt_path -> branch name
        self._spec_locks: Set[str] = set()  # SPECs currently being worked on
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
        # 主树 merge-clean guard 串行锁（fix-autostash-orphans）：stash→merge→pop
        # 是必须原子完成的段——并发 worker 若各自独立 stash/pop，会与共享的 stash
        # 栈发生 LIFO 错配（A 恢复出 B 刚 stash 的内容）。
        self._main_tree_lock = threading.Lock()
        # 最近一次 guard 段内 stash pop 冲突自愈丢弃的文件清单（dispatch 层读走
        # 做 admin 告警后失效）；guard 进入时清空。
        self.last_stash_pop_conflicts: list = []

    def create(self, spec_name: str, agent_type: str = "implementer") -> Optional[Path]:
        """
        Create a git worktree for an Agent run.

        Args:
            spec_name: The SPEC name (e.g., "add-user-login")
            agent_type: "implementer" or "verifier"

        Returns: Path to the worktree, or None on failure.
        """
        # Prevent duplicate worktrees for the same SPEC+agent_type
        lock_key = f"{spec_name}:{agent_type}"
        if lock_key in self._spec_locks:
            self.logger.warning(
                "worktree_manager",
                f"Worktree already active for {lock_key}",
            )
            return None

        self._spec_locks.add(lock_key)

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
                self._spec_locks.discard(lock_key)
                return None

            self._active_worktrees.add(str(wt_path))
            self._wt_branches[str(wt_path)] = branch

            # Seed SPEC files for implementer worktrees
            if agent_type == "implementer":
                self._seed_spec(spec_name, wt_path)

            self.logger.info("worktree_manager", f"Worktree created: {wt_path}")
            return wt_path

        except subprocess.TimeoutExpired:
            self.logger.error("worktree_manager", "Worktree creation timed out")
            self._spec_locks.discard(lock_key)
            return None
        except Exception as e:
            self.logger.error("worktree_manager", f"Worktree creation error: {e}")
            self._spec_locks.discard(lock_key)
            return None

    def _seed_spec(self, spec_name: str, wt_path: Path):
        """Seed SPEC source files into a new worktree.

        If openspec/changes/<spec>/ exists in the main worktree but not in the
        new worktree (the branch HEAD doesn't contain it), copy the directory
        into the worktree and commit it to the isolated branch.

        Failures are logged but never block — the implementer falls back to
        the main repository path.
        """
        try:
            main_spec_dir = self.project_root / "openspec" / "changes" / spec_name
            wt_spec_dir = wt_path / "openspec" / "changes" / spec_name

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
                ["git", "-C", str(wt_path), "add", "openspec/changes/"],
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

        spec 目录（openspec/changes/<spec>/）若在主树 untracked，而 worktree 分支里
        _seed_spec 已 commit 一份同名路径，merge-back 时 git 会拒绝「untracked working
        tree files would be overwritten by merge」。在派发前把 spec 提交进主树使其被跟踪，
        分支从新 HEAD 建即可直接包含 spec（_seed_spec 跳过），merge 变为干净三方合并。

        Returns: True 表示已提交或本已无改动（干净）；False 表示提交失败。
        """
        rel = f"openspec/changes/{spec_name}"
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

        泛化原 openspec/changes 限定逻辑（fix-merge-untracked-guard）：

        1. `git diff --name-only --diff-filter=A HEAD...<branch>` 取分支**新增**文件路径集合
           —— untracked 冲突只会发生在新增路径上（修改既有 tracked 文件不与 untracked 冲突）。
        2. 对每条新增路径，判断主树中该路径上的文件是否为 untracked：
           `git ls-files --error-unmatch <path>` 失败（未被 index 跟踪）即视为 untracked。
        3. 将命中的文件移入 `.fenix/merge-backup/<epoch秒>/`（保持仓库相对路径结构）。

        检测范围不限于 openspec/changes/，覆盖任意产物路径（如 core/dashboard/static/v2/）。
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
            # 进程扫描缓存随之失效（下一次判定须重新扫描，防读到陈旧「存活」结果）
            for k in to_remove:
                self._proc_scan_cache.pop(self._lock_spec_name(k), None)

    def cleanup_orphans(self):
        """Clean up any remaining worktree directories on shutdown."""
        if not self.base_dir.exists():
            return

        for wt_dir in self.base_dir.iterdir():
            if wt_dir.is_dir() and str(wt_dir) in self._active_worktrees:
                self.logger.info("worktree_manager", f"Cleaning up orphan: {wt_dir}")
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

        Args:
            spec_name: 死亡 run 所属 SPEC。
            worktree_path: 死亡 run 的 worktree 绝对路径（Path 或 str）。
            branch: 死亡 run 的 worktree 分支名。
        """
        if not spec_name or not worktree_path:
            return
        wt_str = str(worktree_path)
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
            "worktree_name": wt_str.rstrip("/").split("/")[-1],
            "registered_at": time.time(),
            "dirty": True,  # 注入时现场重采 git status，先标记脏待刷新
        }
        self.logger.warning(
            "worktree_manager",
            f"Registered legacy for '{spec_name}': worktree={wt_str} branch={branch}",
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
        self._spec_locks.add(f"{spec_name}:verifier")

    def _release_spec_locks(self, spec_name: str, reason: str) -> list:
        """释放该 spec 的全部在册锁，返回被释放的 key（已不在册则返回空）。"""
        to_remove = [k for k in self._spec_locks if self._lock_spec_name(k) == spec_name]
        for k in to_remove:
            self._spec_locks.discard(k)
        return to_remove

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
        """pgrep 匹配 cmdline 含 ``worktrees/{impl,verify}-<spec>-`` 的进程。

        匹配串锚定 worktree 目录字面量（<prefix>-<spec>-<ts>），不匹配裸 spec 名，
        防止把无关进程当成持锁者。pgrep 不可用/超时时返回 False（调用方以
        run 流新鲜度做二次确认）。
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
        """进程表中是否存在 cmdline 引用该 worktree 目录的进程（启动清理用）。

        与 _pgrep_spec_process 不同：这里按完整 worktree 目录名匹配，不经过
        缓存（启动时一次性调用，结果必须实时）。
        """
        pattern = f"worktrees/{wt_name}"
        try:
            res = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True, text=True, timeout=5,
            )
            return res.returncode == 0 and res.stdout.strip() != ""
        except (subprocess.SubprocessError, OSError):
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

        重要：stash 排除 `openspec/changes/`——该目录下未跟踪的 spec 文件
        （proposal/design/specs/tasks）是框架运行必需，一旦被卷进 stash，
        implementer 就找不到 SPEC 文件而空转（fix：曾因此烧掉 ~450 轮）。
        spec 文件应在创建时提交；此处排除作为兜底。
        """
        result = subprocess.run(
            ["git", "-C", str(self.project_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
        # 只关心 tracked 修改（XY 状态里 X/Y 非 ' '/'?'）；untracked（'? '）由
        # merge 内部 backup 机制处理。openspec/changes 的脏文件被跟踪时也计入。
        dirty_tracked = any(
            not line.startswith("?? ") and line[2:3] != " "
            for line in result.stdout.splitlines()
        ) if result.returncode == 0 else False
        if not dirty_tracked:
            return False
        stash = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "push",
             "-m", AUTOSTASH_MSG_PREFIX,
             "--", ".", ":(exclude)openspec/changes"],
            capture_output=True, text=True, timeout=30,
        )
        if stash.returncode != 0:
            self.logger.warning(
                "worktree_manager",
                f"Autostash failed (proceed with dirty tree): {stash.stderr.strip()}",
            )
            return False
        if "No local changes" in (stash.stdout + stash.stderr):
            # 唯一脏内容就是被排除的 openspec/changes，实际未 stash
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
        stash 条目**不**自动 drop，被丢弃内容可由人工从 stash 中找回。
        """
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
            self.logger.warning(
                "worktree_manager",
                f"Stash pop conflict self-healed; discarded stash changes on "
                f"{len(conflict_files)} file(s): {conflict_files} "
                f"(stash preserved, recover via git stash show)",
            )
        else:
            # 输出含 CONFLICT 但已无 UU 条目（罕见：冲突已自行消解）——照常处理
            self.logger.warning(
                "worktree_manager",
                f"Stash pop conflict reported but no UU files found; "
                f"stash preserved: {output.strip()}",
            )
        return True, conflict_files

    def reclaim_stale_autostash(self) -> bool:
        """兜底回收滞留的 pre-dispatch autostash 条目（fix-autostash-orphans）。

        历史版本在派发前 stash、仅 merge-back 成功路径 pop——任何失败/重派/
        异常/daemon 重启出口都会把用户未提交改动永久滞留 stash 栈。guard 化
        （方案 1）后新条目不再滞留，本方法负责回收存量与各类历史遗留。

        仅在「主树干净」且「栈顶条目带 AUTOSTASH_MSG_PREFIX」时 pop 恢复：
          - 主树脏说明用户正在工作，不抢；
          - 人工手工 stash 的条目无此前缀，永不触碰。

        pop 冲突时沿用 restore_after_merge 的自愈策略（丢弃 stash 版本保 HEAD、
        清 UU 使主树可写），stash 条目由 git 保留（pop 冲突不删条目）。

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
            self.logger.error(
                "worktree_manager",
                f"Stale autostash pop conflicted with merged implementation; "
                f"healed UU files {conflict_files}, stash entry preserved "
                f"(recover via git stash show)",
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

    def merge_back_from_branch(self, branch: str) -> tuple:
        """Merge a worktree branch into the main tree (project_root HEAD).

        与 merge_back(wt_path) 等价，但直接接受分支名。用于 worktree 已被清理、
        但分支仍保留的场景（implementer 成功路径）。

        主树干净由 guard 原子保证（fix-autostash-orphans）：锁内 stash→merge→pop
        同步段完成。不再依赖「派发前 stash + 成功路径才 pop」的长窗口配对——
        那种配对在任何失败/重派/异常/daemon 重启路径下都会把用户未提交改动
        滞留在 stash 栈（曾致 7 次改动"消失"事故）。段内 pop 弹到的必是刚 push
        的条目（锁串行 + LIFO），历史滞留条目由周期巡检兜底回收。

        Returns: (success: bool, error_message: str)
        """
        if not branch:
            return False, "Empty branch name"

        with self._main_tree_lock:
            self.last_stash_pop_conflicts = []
            stashed = self.ensure_clean_tree()
            try:
                return self._merge_back_from_branch_locked(branch)
            finally:
                if stashed:
                    _ok, conflict_files = self.restore_after_merge()
                    if conflict_files:
                        self.last_stash_pop_conflicts = list(conflict_files)

    def _merge_back_from_branch_locked(self, branch: str) -> tuple:
        """merge_back_from_branch 的实现体，调用方必须已持有 _main_tree_lock。"""
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
                return True, "already merged"

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
            if result.returncode == 0:
                self._drop_backup(backup)
                # merge 成功后把随分支带回 tracked 的 ignored 草稿移出（防撞车循环重启）
                if head_before:
                    self._purge_ignored_brought_in(head_before)
                self.logger.info(
                    "worktree_manager",
                    f"Merged branch '{branch}' into main tree",
                )
                return True, ""

            error = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            self.logger.error(
                "worktree_manager",
                f"Merge failed for branch '{branch}': {error}",
            )
            # merge 冲突自愈（fix-merge-modify-delete-ignored）：modify/delete 冲突
            # 且全部冲突路径都是 .gitignore 忽略的运行时草稿时，采纳主树侧的删除。
            # 场景：run-result 类草稿在移出版本控制前派生的旧分支上被改动，与主树的
            # 删除相撞——被忽略的草稿不是交付物，不应让 merge-back 死锁。
            if self._resolve_ignored_modify_delete_conflicts():
                self._drop_backup(backup)
                self.logger.info(
                    "worktree_manager",
                    f"Merge conflict self-healed (modify/delete on ignored files) "
                    f"for branch '{branch}'",
                )
                return True, ""
            # Abort the merge so main tree is left clean for retry
            subprocess.run(
                ["git", "-C", str(self.project_root), "merge", "--abort"],
                capture_output=True, text=True, timeout=30,
            )
            # 恢复被移开的 untracked 文件（不丢数据，供下一轮重试）
            self._restore_backup(backup)
            return False, error

        except subprocess.TimeoutExpired:
            return False, "git merge timed out after 120s"
        except Exception as e:
            return False, str(e)

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

    def merge_back(self, wt_path: Path) -> tuple:
        """Merge the worktree's branch into the main tree (project_root HEAD).

        Uses `git merge --no-ff` to preserve history. Idempotent: if the branch
        is already an ancestor of HEAD, skips and reports success.

        Returns: (success: bool, error_message: str)
        """
        wt_str = str(wt_path)
        branch = self._wt_branches.get(wt_str)
        if not branch:
            return False, f"Unknown worktree (no branch recorded): {wt_path}"
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
            True 表示分支 HEAD 包含该路径（blob 或 tree 均可，blob 才算真正落地）。
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
            # 必须是 blob（文件），tree（目录）不算落地交付物。
            kind = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "cat-file", "-t", f"{branch}:{rel_path}"],
                capture_output=True, text=True, timeout=30,
            )
            return kind.returncode == 0 and kind.stdout.strip() == "blob"
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False
