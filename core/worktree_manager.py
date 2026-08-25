"""
worktree_manager.py — Git worktree lifecycle management.

Creates, tracks, and cleans up isolated git worktrees for Agent runs.
Ensures parallel Agents don't conflict.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Set, Dict


class WorktreeManager:
    """
    Manage git worktree lifecycle for Agent isolation.

    Each Agent run gets its own worktree:
      - Implementer: .claude/worktrees/<spec>-<timestamp>/ on branch fenix/<spec>
      - Verifier:    .claude/worktrees/verify-<spec>-<timestamp>/ on branch fenix/verify-<spec>
    """

    def __init__(self, base_dir: Path, project_root: Path, logger):
        self.base_dir = Path(base_dir)
        self.project_root = Path(project_root)
        self.logger = logger
        self._active_worktrees: Set[str] = set()
        self._wt_branches: Dict[str, str] = {}  # wt_path -> branch name
        self._spec_locks: Set[str] = set()  # SPECs currently being worked on

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

        try:
            self.logger.info(
                "worktree_manager",
                f"Cleaning up worktree: {wt_path} (success={success})",
            )

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

    def has_active_worktree(self, spec_name: str) -> bool:
        """Check if any worktree is active for the given SPEC."""
        return any(spec_name in lock for lock in self._spec_locks)

    # ── 主树健康检查（fix-fenix-token-waste） ──────────────────────

    def ensure_clean_tree(self) -> bool:
        """dispatch 前确保主树干净，保证 merge-back 可成功。

        若主树存在未提交改动（含未跟踪文件），自动 `git stash push
        --include-untracked`。返回 True 表示执行过 stash（merge 成功后需
        restore_after_merge 恢复）；False 表示主树本来就干净。

        重要：stash 排除 `openspec/changes/`——该目录下未跟踪的 spec 文件
        （proposal/design/specs/tasks）是框架运行必需，一旦被卷进 stash，
        implementer 就找不到 SPEC 文件而空转（fix：曾因此烧掉 ~450 轮）。
        spec 文件应在创建时提交；此处排除作为兜底。
        """
        result = subprocess.run(
            ["git", "-C", str(self.project_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        stash = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "push", "--include-untracked",
             "-m", "fenix: pre-dispatch autostash",
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
        self.logger.info("worktree_manager", "Autostashed dirty main tree before dispatch")
        return True

    def restore_after_merge(self) -> bool:
        """merge-back 成功后恢复 dispatch 前自动 stash 的主树改动。

        Returns: True 恢复成功；False pop 冲突（stash 条目保留，可 git stash list 找回）。
        """
        result = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "pop"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            self.logger.info("worktree_manager", "Stash popped after merge")
            return True
        self.logger.warning(
            "worktree_manager",
            f"Stash pop failed (stash preserved): "
            f"{result.stderr.strip() or result.stdout.strip()}",
        )
        return False

    def cleanup_stale_worktrees(self):
        """启动时全量清理孤儿 worktree：删除所有不在活动集合的目录 + 对应分支 + prune。

        与 shutdown 的 cleanup_orphans 互补：后者清活动集合内残留，本方法清
        上次异常退出遗留的孤儿。失败记 WARNING，不阻塞 daemon 启动。
        """
        if not self.base_dir.exists():
            return
        for wt_dir in self.base_dir.iterdir():
            if not wt_dir.is_dir() or str(wt_dir) in self._active_worktrees:
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

        Returns: (success: bool, error_message: str)
        """
        if not branch:
            return False, "Empty branch name"

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

            # Merge with --no-ff to preserve worktree history
            result = subprocess.run(
                ["git", "-C", str(self.project_root),
                 "merge", "--no-ff", branch,
                 "-m", f"[fenix] merge implementer branch {branch}"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
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
            # Abort the merge so main tree is left clean for retry
            subprocess.run(
                ["git", "-C", str(self.project_root), "merge", "--abort"],
                capture_output=True, text=True, timeout=30,
            )
            return False, error

        except subprocess.TimeoutExpired:
            return False, "git merge timed out after 120s"
        except Exception as e:
            return False, str(e)

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
