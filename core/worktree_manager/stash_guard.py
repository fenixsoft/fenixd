"""stash_guard.py — G6 主树还原/autostash 治理（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 9 个方法，原样搬移为 mixin（方法体零改动）。
"""

from __future__ import annotations

import shutil
import subprocess
import time

from core.worktree_manager import (  # noqa: E402
    AUTOSTASH_MSG_PREFIX,
)


class G6StashGuardMixin:
    """G6 主树还原/autostash 治理（design D1 表 A G6）。"""


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
                capture_output=True,
                text=True,
                timeout=30,
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
            [
                "git",
                "-C",
                str(self.project_root),
                "stash",
                "push",
                "-m",
                AUTOSTASH_MSG_PREFIX,
                "--",
                ".",
                ":(exclude)spec/changes",
            ],
            capture_output=True,
            text=True,
            timeout=30,
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
            ["git", "-C", str(self.project_root), "rev-parse", "--verify", "stash@{0}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if rev.returncode == 0:
            pinned_sha = rev.stdout.strip()

        result = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "pop"],
            capture_output=True,
            text=True,
            timeout=30,
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
                recover_cmds = (
                    " ".join(f"git show {pinned_sha}:{f}" for f in conflict_files)
                    if pinned_sha
                    else "git stash show"
                )
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
                    [
                        "git",
                        "-C",
                        str(self.project_root),
                        "diff",
                        "--quiet",
                        pinned_sha,
                        "HEAD",
                        "--",
                        f,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
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
            ["git", "-C", str(self.project_root), "rev-parse", "--verify", "stash@{0}"],
            capture_output=True,
            text=True,
            timeout=30,
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
            capture_output=True,
            text=True,
            timeout=30,
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
            capture_output=True,
            text=True,
            timeout=30,
        )
        if status.returncode != 0 or status.stdout.strip():
            return False
        lst = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "list", "-n", "1"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # 格式：stash@{0}: On <branch>: fenix: pre-dispatch autostash
        top = lst.stdout.strip() if lst.returncode == 0 else ""
        if AUTOSTASH_MSG_PREFIX not in top:
            return False
        rev = subprocess.run(
            ["git", "-C", str(self.project_root), "rev-parse", "--verify", "stash@{0}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        sha_before = rev.stdout.strip() if rev.returncode == 0 else ""
        pop = subprocess.run(
            ["git", "-C", str(self.project_root), "stash", "pop"],
            capture_output=True,
            text=True,
            timeout=30,
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
                    ["git", "-C", str(self.project_root), "rev-parse", "--verify", "stash@{0}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if cur.returncode == 0 and cur.stdout.strip() == sha_before:
                    dropped = subprocess.run(
                        ["git", "-C", str(self.project_root), "stash", "drop", "stash@{0}"],
                        capture_output=True,
                        text=True,
                        timeout=30,
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
                    [
                        "git",
                        "-C",
                        str(self.project_root),
                        "check-ignore",
                        "--no-index",
                        "-q",
                        "--",
                        path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
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
                    ["git", "-C", str(self.project_root), "rm", "-f", "--cached", "--", path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if rm.returncode != 0:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (untrack): git rm --cached failed for "
                        f"'{path}': {(rm.stderr or rm.stdout).strip()}",
                    )
                    return False
            commit = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "commit",
                    "-m",
                    "[fenix] fix: merge 前移出被误提交的 ignored 运行时草稿",
                ],
                capture_output=True,
                text=True,
                timeout=60,
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
                        f"Self-heal (identical) aborted: '{path}' missing in " f"main tree",
                    )
                    return False
                show = subprocess.run(
                    ["git", "-C", str(self.project_root), "show", f"{branch}:{path}"],
                    capture_output=True,
                    timeout=30,
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
            backup = self.project_root / ".fenix" / "merge-backup" / f"identical-{int(time.time())}"
            for path in identical:
                dest = backup / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.project_root / path, dest)
            co = subprocess.run(
                ["git", "-C", str(self.project_root), "checkout", "HEAD", "--", *identical],
                capture_output=True,
                text=True,
                timeout=30,
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
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "diff",
                    "--name-only",
                    "--diff-filter=A",
                    f"{old_head}..HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if diff.returncode != 0 or not diff.stdout.strip():
                return
            victims = []
            for rel in [ln.strip() for ln in diff.stdout.splitlines() if ln.strip()]:
                ls = subprocess.run(
                    ["git", "-C", str(self.project_root), "ls-files", "--error-unmatch", "--", rel],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if ls.returncode != 0:
                    continue  # 已不在索引（或不存在）
                chk = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.project_root),
                        "check-ignore",
                        "--no-index",
                        "-q",
                        "--",
                        rel,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if chk.returncode == 0:
                    victims.append(rel)
            if not victims:
                return
            for rel in victims:
                subprocess.run(
                    ["git", "-C", str(self.project_root), "rm", "-f", "--cached", "--", rel],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            commit = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "commit",
                    "-m",
                    "[fenix] fix: merge 后移出随分支带回的 ignored 运行时草稿",
                ],
                capture_output=True,
                text=True,
                timeout=60,
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
                capture_output=True,
                text=True,
                timeout=30,
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
                    ["git", "-C", str(self.project_root), "rm", "-f", "--cached", "--", path],
                    capture_output=True,
                    text=True,
                    timeout=30,
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
                    ["git", "-C", str(self.project_root), "check-ignore", "-q", "--", path],
                    capture_output=True,
                    text=True,
                    timeout=30,
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
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    return False
            commit = subprocess.run(
                ["git", "-C", str(self.project_root), "commit", "--no-edit"],
                capture_output=True,
                text=True,
                timeout=60,
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
