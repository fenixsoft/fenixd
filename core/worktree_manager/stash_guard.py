"""stash_guard.py — G6 主树还原/autostash 治理（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 9 个方法，原样搬移为 mixin（方法体零改动）。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from core.worktree_manager import (  # noqa: E402
    AUTOSTASH_MSG_PREFIX,
)
from core.worktree_manager.mergeback import _unquote_git_path  # noqa: E402


class G6StashGuardMixin:
    """G6 主树还原/autostash 治理（design D1 表 A G6）。"""


    def _list_dirty_tracked_files(self) -> list:
        """提取主树脏 tracked 文件清单（fix-mergeback-stashpop-silent-loss D3）。

        ensure_clean_tree 的 porcelain 脏判定提炼为共享 helper：porcelain v1
        每行 "XY " 前缀，X=索引状态、Y=工作区状态，第 3 个字符恒为分隔符空格
        ——脏判定看 [0]/[1] 任一非空格（历史版本误查 [2] 致 autostash 从未
        触发，2026-09-02 修）。untracked（'??'）不计入。命令失败返回空列表
        （调用方按「无重叠」处理，不阻塞流程）。

        路径反转义：porcelain 对含非 ASCII/特殊字符的路径默认输出 C-quoted
        转义形（如 "core/\346\226\207.tsx"），逐段经 `_unquote_git_path`
        （mergeback 同源反转义）还原为真实路径——消费方（mergeback WIP 闸门 /
        code-fix 批 WIP 重叠预检）拿真实路径比对求交，带引号转义形会永不命中。

        Returns: 排序后的脏 tracked 文件路径列表（rename 两侧都计入，已反转义）。
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
                # porcelain 对 rename 两侧各自 C-quote，按段逐个反转义
                files.extend(
                    _unquote_git_path(p.strip()) for p in path.split(" -> ")
                )
            else:
                files.append(_unquote_git_path(path))
        return sorted(p for p in files if p)

    def ensure_clean_tree(self, prefix: str = None) -> bool:
        """merge guard 段内确保主树 tracked 状态干净，保证 merge-back 可成功。

        仅 stash **tracked 修改**（`git stash push` 不带 -u）。返回 True 表示
        执行过 stash（guard 的 finally 会 restore_after_merge 恢复）；False
        表示主树 tracked 状态本来就干净。

        ``prefix``：stash 条目前缀。缺省 None = ``AUTOSTASH_MSG_PREFIX``（既有
        语义）；merge-back 前 WIP 重叠闸门收纳路径传入 ``WIP_GATE_STASH_PREFIX``
        （evo-merge-back-wip-overlap-gate D1 前缀隔离：reclaim_stale_autostash 只
        按 AUTOSTASH_MSG_PREFIX 子串回收栈顶条目，复用同前缀会让故意保留待人工
        找回的闸门条目被 60s 巡检抢走并沿用丢弃策略，去向记录随即失真）。

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
        try:
            stash = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "stash",
                    "push",
                    "-m",
                    prefix or AUTOSTASH_MSG_PREFIX,
                    "--",
                    ".",
                    ":(exclude)spec/changes",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            # git 超时/不可用：按「未 stash」降级（与 returncode!=0 同路径），
            # guard 以 stashed=False 跳过 finally 的 restore，不让异常穿出
            self.logger.warning(
                "worktree_manager",
                f"Autostash failed (proceed with dirty tree): {e}",
            )
            return False
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
        - ``(True, [file, ...])``：pop 发生冲突但已完成三态自愈——主树回到
          可写状态，``conflict_files`` 为 UU 冲突文件清单（stash 条目保留，
          stash 版内容已按态 1/2/3 落回工作区或恢复 commit，见
          ``_triage_stash_pop_conflicts``）。
        - ``(False, [file, ...])``：三态自愈后复查 ``git ls-files -u`` 仍有 UU
          残留（如态 2 checkout --theirs 失败的态 3 分支只登记 disposition、
          未消解 unmerged 条目）——主树仍半合并，交人工处置（与
          ``reclaim_stale_autostash`` 的复查口径一致）。
        - ``(False, [])``：pop 失败且非冲突类（如其它 git 错误），stash 保留；调用方按
          旧版 False 语义处理（主树可能仍半合并，需人工处置）。

        **三态自愈（evo-stash-pop-conflict-triage D1/D2）**：当 pop 返回非 0 且输出
        含 ``CONFLICT`` 时，主树会陷入 UU 半合并状态、index.lock 满，导致后续所有
        git 写操作瘫痪。此时对每个 UU 冲突文件按序尝试：
          1. ``git ls-files -u`` 枚举全部 UU 未合并文件；
          2. 三态重试（``_triage_stash_pop_conflicts``）——态 1 三方重试
             （ours=``HEAD:<f>``、base=``stash@{0}^1:<f>``、theirs=``stash@{0}:<f>``，
             ``git merge-file``）无冲突写回工作区（两侧改动都保留）；态 1 失败
             MUST NOT 视为异常，直接进态 2；态 2 逐文件 ``git checkout --theirs``
             取回 stash 版内容落工作区（MUST NOT 读工作区冲突标记——二进制/非
             UTF-8 文件工作区为 merge 结果、无标记），``git add -- <paths>`` +
             ``git commit --only`` 只把本次冲突路径入库留审计；态 2 任一步失败进
             态 3 兜底——stash 版内容至少落工作区并显式登记 disposition；
          3. **任何路径都不再 ``checkout -f HEAD`` 静默丢弃 stash 版**；stash 条目
             一律保留（不因恢复 commit 触发「零独有内容」自动 drop，见 D3），
             找回命令仍可 ``git show <sha>:<file>``。
        """
        # pop 前钉住栈顶 sha（fix-mergeback-stashpop-silent-loss D2）：guard 锁内
        # LIFO，此时栈顶即刚 push 的条目；drop 前以「sha 仍为栈顶」防并发插队。
        pinned_sha = ""
        try:
            rev = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "--verify", "stash@{0}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            # git 超时/不可用：钉不住 sha，按空 sha 继续（后续 pop 自行降级）
            rev = None
        if rev is not None and rev.returncode == 0:
            pinned_sha = rev.stdout.strip()

        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "stash", "pop"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            # 本方法常在 guard 的 finally 中执行，绝不能外抛（会吞掉业务原始
            # 异常并中断清理链）——按旧版非冲突失败语义降级，stash 条目保留
            self.logger.warning(
                "worktree_manager",
                f"Stash pop failed (non-conflict, stash preserved): {e}",
            )
            return False, []
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

        # ── pop 冲突：进入三态重试（evo-stash-pop-conflict-triage D1/D2） ──
        conflict_files = self._list_unmerged_files()
        if conflict_files:
            # 三态重试：态 1 三方合并 → 态 2 恢复 commit → 态 3 兜底。
            # 自愈口径由「checkout -f HEAD 覆盖丢弃 stash 版」改为下述三态，
            # 任何路径都不得静默丢弃 stash 版内容。
            mode, triage_note = self._triage_stash_pop_conflicts(
                pinned_sha, conflict_files
            )
            # D4 可观测性：结构化日志（处置方式（态 1/2/3）/stash sha/文件清单），
            # 供 stash_pop_conflict 信号 evidence 携带，dashboard 与自省可见。
            self.logger.warning(
                "worktree_manager",
                f"Stash pop conflict triage: mode={mode} "
                f"stash_sha={pinned_sha[:12] if pinned_sha else '-'} "
                f"files={conflict_files} note={triage_note}",
            )
            # 条目保留记账（D3）：内容已按三态落回工作区/恢复 commit，条目一律
            # 保留——不因恢复 commit 触发「零独有内容」自动 drop（恢复 commit
            # 后 HEAD 已含 stash 版、树级 diff 恒为空，drop 判据会误命中；
            # 且「被合并结果取代」与「被自愈恢复 commit 重新入库」是两回事，
            # 后者保留条目作审计）。stash_pop_conflict 信号行为保持不变。
            recover_cmds = (
                " ".join(f"git show {pinned_sha}:{f}" for f in conflict_files)
                if pinned_sha
                else "git stash show"
            )
            self.last_stash_entry_fate = {"kept": True, "sha": pinned_sha}
            self.logger.warning(
                "worktree_manager",
                f"Stash pop conflict triaged via mode {mode}; stash changes on "
                f"{len(conflict_files)} file(s): {conflict_files} recovered "
                f"(stash preserved, recover via: {recover_cmds})",
            )
            # 复查残留（对齐 reclaim_stale_autostash 口径）：态 2 checkout
            # --theirs 失败的态 3 分支只登记 disposition、未消解 unmerged
            # 条目——半合并 UU 残留会让后续 git 写操作持续失败，仍有残留时
            # 按 False 返回交人工，不再谎报「主树回到可写状态」。
            residual = self._list_unmerged_files()
            if residual:
                self.logger.error(
                    "worktree_manager",
                    f"Stash pop conflict triage incomplete (mode={mode}); "
                    f"unmerged files remain, stash entry preserved "
                    f"(recover via: {recover_cmds})",
                )
                return False, conflict_files
        else:
            # 输出含 CONFLICT 但已无 UU 条目（罕见：冲突已自行消解）——照常处理
            self.logger.warning(
                "worktree_manager",
                f"Stash pop conflict reported but no UU files found; "
                f"stash preserved: {output.strip()}",
            )
        return True, conflict_files

    def _try_merge_file_threeway(self, f: str, pinned_sha: str) -> bytes | None:
        """对单个 UU 冲突文件做三方重试（态 1），成功返回合并后字节内容。

        ours = ``HEAD:<f>``（已合入 HEAD 版）、base = ``<pinned_sha>^1:<f>``
        （stash 父提交版）、theirs = ``<pinned_sha>:<f>``（stash 版），经
        ``git merge-file`` 合并。三者任一提不出来（add/add、delete/modify、
        二进制不合并等）或合并仍冲突（rc!=0）返回 None —— 调用方进态 2，
        **MUST NOT** 视为异常（pop 已做过同样的三方合并，纯文本同 hunk 冲突
        时态 1 与现状结果相同；态 1 的收益在 pop 因索引/二进制/CRLF 等边缘
        原因未自动合并的场景）。
        """
        if not pinned_sha:
            # sha 未知：无法定位 stash 父/版 —— 态 1 不可行
            return None
        blobs = {}
        for key, ref in (
            ("ours", f"HEAD:{f}"),
            ("base", f"{pinned_sha}^1:{f}"),
            ("theirs", f"{pinned_sha}:{f}"),
        ):
            try:
                cat = subprocess.run(
                    ["git", "-C", str(self.project_root), "cat-file", "blob", ref],
                    capture_output=True,
                    timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError):
                return None
            if cat.returncode != 0:
                return None
            blobs[key] = cat.stdout
        # merge-file 需要文件路径输入，三方内容落临时文件。mkdtemp 纳入包裹：
        # 磁盘满/临时目录不可写等 OSError 同样按态 1 失败处置返回 None 进态 2
        # ——本调用链位于 guard finally 中，绝不外抛（见 restore_after_merge
        # 「绝不能外抛」注释）；独立 try 保证下方 finally 引用 tmp_dir 前已赋值。
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="fenix-triage-"))
        except OSError:
            return None
        try:
            tmp_paths = {}
            for key, content in blobs.items():
                p = tmp_dir / key
                p.write_bytes(content)
                tmp_paths[key] = p
            mf = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "merge-file",
                    "-p",
                    str(tmp_paths["ours"]),
                    str(tmp_paths["base"]),
                    str(tmp_paths["theirs"]),
                ],
                capture_output=True,
                timeout=30,
            )
            # rc=0 干净合并；rc=1 冲突；rc=2 错误（二进制等）——均进态 2
            if mf.returncode != 0:
                return None
            return mf.stdout
        except (subprocess.TimeoutExpired, OSError):
            return None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _triage_stash_pop_conflicts(self, pinned_sha: str, conflict_files: list) -> tuple:
        """pop 冲突 UU 文件三态重试（evo-stash-pop-conflict-triage D1/D2/D3）。

        对 ``conflict_files``（UU 冲突文件清单，见 ``_list_unmerged_files``）
        按序尝试，返回 ``(mode, note)``：

        - 态 1（mode=1）：对每个 UU 文件三方重试（``_try_merge_file_threeway``），
          无冲突则把合并结果（两侧改动都保留）写回工作区并 ``git add`` 消解
          unmerged 状态。态 1 失败 **MUST NOT** 视为异常，直接进态 2。
        - 态 2（mode=2）：逐文件 ``git checkout --theirs -- <f>`` 从 stash 条目
          的 stage 3 取回 stash 版内容落工作区 —— **MUST NOT** 读工作区冲突标记
          （二进制/非 UTF-8 文件 pop 后工作区被 merge 结果整体覆盖、无标记）；
          再 ``git add -- <paths>`` + ``git commit --only`` **只把本次冲突路径**
          入库留审计 —— 保留 index 中其余 staged 条目、不改动其它路径内容
          （D2 路径作用域）。
        - 态 3（mode=3）：态 2 落盘/入库任一步失败（写盘失败、commit 失败、
          磁盘满等）时，stash 版内容至少已落工作区（``--theirs`` 落盘/冲突标记
          保留两侧），显式登记 disposition 兜底 —— **绝不静默丢弃**，stash
          条目保留、stash_pop_conflict 信号照发。

        「零独有内容才 drop」判据已退役（原 ``_drop_superseded_stash_entry``，
        D3 后冲突条目一律保留，无生产调用方）：恢复 commit 后 HEAD 已含
        stash 版、树级 diff 恒为空，该判据会误命中「被合并结果取代」——而
        这里内容是被自愈重新入库，条目保留作审计（D3：入恢复 commit 与
        条目保留并存按保留记账）。
        """
        # ── 态 1：三方重试（ours=HEAD / base=stash 父 / theirs=stash） ──
        remaining: list = []
        for f in conflict_files:
            merged = self._try_merge_file_threeway(f, pinned_sha)
            if merged is None:
                remaining.append(f)
                continue
            try:
                (self.project_root / f).write_bytes(merged)
            except OSError as e:
                self.logger.warning(
                    "worktree_manager",
                    f"State-1 write-back failed for '{f}': {e} — falling to state 2",
                )
                remaining.append(f)
                continue
            st = subprocess.run(
                ["git", "-C", str(self.project_root), "add", "--", f],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if st.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"State-1 git add failed for '{f}': {st.stderr.strip()} "
                    f"— falling to state 2",
                )
                remaining.append(f)
                continue
            self.logger.info(
                "worktree_manager",
                f"State-1 three-way merge resolved '{f}' (both sides preserved)",
            )
        if not remaining:
            # 全部 UU 文件被态 1 干净合并——双版本内容已落工作区并消解 unmerged
            return 1, "state-1 three-way merge resolved all conflict files"

        # ── 态 2：取回 stash 版 + 路径作用域恢复 commit ──
        for f in remaining:
            co = subprocess.run(
                ["git", "-C", str(self.project_root), "checkout", "--theirs", "--", f],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if co.returncode != 0:
                # --theirs 失败（罕见：路径仍 UU）：stash 版在 index stage 3 +
                # 工作区冲突标记仍保留两侧，不丢数据；放弃本次 commit 走态 3
                self.logger.warning(
                    "worktree_manager",
                    f"State-2 checkout --theirs failed for '{f}' "
                    f"({co.stderr.strip()}) — stash content preserved in "
                    f"worktree/index, falling to state-3 disposition",
                )
                return 3, f"state-2 checkout --theirs failed for '{f}'"
        try:
            add = subprocess.run(
                ["git", "-C", str(self.project_root), "add", "--", *conflict_files],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if add.returncode != 0:
                raise RuntimeError(f"git add failed: {add.stderr.strip()}")
            # 只把本次冲突路径入库（--only 保留 index 中其余 staged 条目），
            # 提交信息含 stash sha 供审计（设计模板「<spec 名> stash pop 恢复」，
            # 此处 restore_after_merge 无 spec 上下文，用通用前缀 + sha）。
            cmt = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "commit",
                    "--only",
                    "-m",
                    f"[fenix] stash pop 恢复（stash {pinned_sha or 'unknown'}）",
                    "--",
                    *conflict_files,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if cmt.returncode != 0:
                raise RuntimeError(
                    f"git commit --only failed: "
                    f"{(cmt.stderr or cmt.stdout).strip()}"
                )
            return 2, f"recovery commit: {cmt.stdout.splitlines()[0] if cmt.stdout else ''}"
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            # ── 态 3 兜底：stash 版内容已在工作区（--theirs 落盘），显式登记
            # disposition，绝不静默丢弃（条目保留、信号照发）
            self.logger.warning(
                "worktree_manager",
                f"State-2 recovery commit failed ({exc}); stash content "
                f"preserved in worktree — state-3 disposition recorded",
            )
            return 3, f"state-2 recovery commit failed: {exc}"

    def reclaim_stale_autostash(self) -> bool:
        """兜底回收滞留的 pre-dispatch autostash 条目（fix-autostash-orphans）。

        历史版本在派发前 stash、仅 merge-back 成功路径 pop——任何失败/重派/
        异常/daemon 重启出口都会把用户未提交改动永久滞留 stash 栈。guard 化
        （方案 1）后新条目不再滞留，本方法负责回收存量与各类历史遗留。

        仅在「主树干净」且「栈顶条目带 AUTOSTASH_MSG_PREFIX」时 pop 恢复：
          - 主树脏说明用户正在工作，不抢；
          - 人工手工 stash 的条目无此前缀，永不触碰。

        pop 冲突时按「丢弃 stash 版保 HEAD」的旧策略自愈（checkout -f HEAD 覆盖
        冲突文件、清 UU 使主树可写；与三态自愈刻意不同：本路径条目即将 drop，
        无需保留 stash 版内容）。自愈完成后 drop 该条目（fix-autostash-conflict-loop）：
        冲突方内容已按策略丢弃、非冲突方改动已落工作区，条目保留不再有恢复价值；
        而本巡检每 60s 跑一次，条目若滞留栈顶会被原样重试 → 每分钟一条 ERROR 的
        无限循环（2026-09-07 指纹 a6fd0e29 事故），daemon 重启无法清除（状态在
        git stash 栈）。drop 前核对 sha 仍在栈顶（防并发新 autostash 插队误删），
        sha 记入日志，gc 前可按 sha 找回。

        Returns: True 表示成功恢复了一个条目。
        """
        try:
            status = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            # git 超时/不可用：本轮放弃回收（条目保留交下轮巡检），不让异常穿出
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaim skipped (git unavailable): {e}",
            )
            return False
        if status.returncode != 0 or status.stdout.strip():
            return False
        try:
            lst = subprocess.run(
                ["git", "-C", str(self.project_root), "stash", "list", "-n", "1"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaim skipped (git unavailable): {e}",
            )
            return False
        # 格式：stash@{0}: On <branch>: fenix: pre-dispatch autostash
        top = lst.stdout.strip() if lst.returncode == 0 else ""
        if AUTOSTASH_MSG_PREFIX not in top:
            return False
        try:
            rev = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "--verify", "stash@{0}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaim skipped (git unavailable): {e}",
            )
            return False
        sha_before = rev.stdout.strip() if rev.returncode == 0 else ""
        # pop 前以 sha_before 复核栈顶：与 drop 侧「sha 仍在栈顶」防插队核对同
        # 口径；其间若有新条目插到栈顶（人工 stash push 等）则放弃本轮，绝不弹
        # 非目标条目。
        try:
            guard = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "--verify", "stash@{0}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            # 防插队复核失败（超时/不可用）无法证明栈顶未动：放弃本轮绝不弹
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaim skipped (git unavailable): {e}",
            )
            return False
        if guard.returncode != 0 or guard.stdout.strip() != sha_before:
            self.logger.error(
                "worktree_manager",
                f"Stale autostash reclaim aborted: stash top moved "
                f"(expected {sha_before or 'n/a'}), skip this round to avoid "
                f"mis-pop",
            )
            return False
        try:
            pop = subprocess.run(
                ["git", "-C", str(self.project_root), "stash", "pop", "stash@{0}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            # git 超时/不可用：与非冲突失败同语义，stash 条目保留交下轮巡检
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash pop failed (entry preserved): {e}",
            )
            return False
        if pop.returncode == 0:
            # pop 输出含「Dropped refs/stash@{0} (<sha>)」：核对被弹条目确为
            # sha_before，不一致说明复核后仍发生并发插队造成误弹，记 ERROR
            # 供人工按 sha 排查。
            if sha_before and sha_before not in (pop.stdout or ""):
                self.logger.error(
                    "worktree_manager",
                    f"Stale autostash reclaim mis-popped a concurrent entry "
                    f"(expected {sha_before}); inspect main tree and stash "
                    f"reflog",
                )
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaimed onto clean main tree: {top}",
            )
            return True
        output = (pop.stderr or "") + (pop.stdout or "")
        if "CONFLICT" in output:
            conflict_files = self._list_unmerged_files()
            if conflict_files:
                # 自愈语义是统一回退 HEAD 版本：下列文件上的 stash/冲突态改动
                # 全部丢弃（并非「保留 merge 结果」），此处明示丢弃面。
                self.logger.warning(
                    "worktree_manager",
                    "Autostash pop conflict self-heal discards local changes "
                    f"on: {', '.join(conflict_files)}",
                )
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
                try:
                    cur = subprocess.run(
                        ["git", "-C", str(self.project_root), "rev-parse", "--verify", "stash@{0}"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    # git 超时/不可用：核不了 sha，按「栈顶已动」降级（不 drop）
                    cur = None
                if (
                    cur is not None
                    and cur.returncode == 0
                    and cur.stdout.strip() == sha_before
                ):
                    try:
                        dropped = subprocess.run(
                            ["git", "-C", str(self.project_root), "stash", "drop", "stash@{0}"],
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                    except (subprocess.TimeoutExpired, OSError):
                        # git 超时/不可用：核不了 drop 结果，条目保留交下轮巡检
                        dropped = None
                    if dropped is not None and dropped.returncode == 0:
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

    def _reset_index_paths(self, paths: list) -> None:
        """把指定路径的索引态还原到 HEAD（自愈中止时回滚 rm --cached 残留）。

        ``git reset -- <paths>`` 只重置索引、不动工作区：撤销
        ``git rm -f --cached`` 留下的 staged 删除，使各中止分支返回前主树
        索引回到执行自愈前的状态（放弃自愈时不残留任何改动，交人工时
        主树状态未被污染）。只重置本次自愈已移出的路径，不触碰 index 中的
        外来 staged 条目（子集守卫本就不动它们）。尽力而为：回滚失败仅记
        warning，不掩盖调用方的原始失败原因。
        """
        if not paths:
            return
        try:
            reset = subprocess.run(
                ["git", "-C", str(self.project_root), "reset", "--", *paths],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if reset.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Self-heal index rollback failed: "
                    f"{(reset.stderr or reset.stdout).strip()}",
                )
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Self-heal index rollback failed: {e}",
            )

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
        healed: list = []  # 已执行 rm --cached 的路径（各中止分支按此回滚索引态）
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
                    self._reset_index_paths(healed)
                    return False
                healed.append(path)
            # 路径作用域守卫：裸 commit 会把 index 里其它 staged 条目连带入库，
            # 校验暂存集不含本次 rm --cached 路径之外的外来条目，有则放弃自愈
            # （先回滚本次已 rm 的索引态再返回，不残留 staged 删除）。
            # 只做子集校验、不强求自愈路径必须出现在暂存集（其入暂存已由上方
            # rm --cached 的返回码保证），避免对暂存态探测过严而误杀正常自愈。
            # （不能用 commit --only/-- <paths> 限定：路径已被 rm --cached 移出
            # index，pathspec 解析必 fatal rc=128，会永远打断本自愈。）
            staged = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "diff",
                    "--cached",
                    "--name-only",
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # 同款反转义（同 _purge_ignored_brought_in）：staged 名单要与 paths
            # （真实路径）做子集校验，diff 输出对非 ASCII 路径默认为 C-quoted
            # 转义形，不反转义会把该类路径误判为「暂存集越界」并放弃本次自愈。
            staged_set = {
                _unquote_git_path(ln) for ln in staged.stdout.splitlines()
            }
            if staged.returncode != 0 or not staged_set <= set(paths):
                self.logger.warning(
                    "worktree_manager",
                    f"Self-heal (untrack) aborted: index has staged entries "
                    f"beyond healed paths: {sorted(staged_set - set(paths))}",
                )
                self._reset_index_paths(healed)
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
                self._reset_index_paths(healed)
                return False
            self.logger.info(
                "worktree_manager",
                f"Self-heal (untrack): moved ignored tracked drafts out of index: "
                f"{', '.join(paths)}",
            )
            return True
        except (subprocess.TimeoutExpired, OSError):
            self._reset_index_paths(healed)
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
        victims: list = []  # 已执行 rm --cached 的路径（各中止分支按此回滚索引态）
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
            # 路径反转义（同 _list_dirty_tracked_files 口径）：diff --name-only
            # 对非 ASCII/特殊字符路径默认输出 C-quoted 转义形，不反转义则下方
            # ls-files/check-ignore/rm --cached 的 pathspec 永不命中，purge
            # 对该类文件静默跳过。
            for rel in [
                _unquote_git_path(ln.strip())
                for ln in diff.stdout.splitlines()
                if ln.strip()
            ]:
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
            # 路径作用域守卫（同 _untrack_ignored_local_changes）：裸 commit 会把
            # index 里其它 staged 条目连带入库，校验暂存集不含本次移出路径之外的
            # 外来条目，不过则回滚本次已移出的索引态再返回（不残留 staged 删除）。
            # 只做子集校验、不强求移出路径必须出现在暂存集（其入暂存
            # 已由上方 rm --cached 的返回码保证）。
            # （不能用 commit --only/-- <paths> 限定：路径已被 rm --cached 移出
            # index，pathspec 解析必 fatal rc=128。）
            staged = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "diff",
                    "--cached",
                    "--name-only",
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # 同款反转义：staged 名单要与 victims（已反转义为真实路径）做子集
            # 校验，带引号转义形会把非 ASCII 路径误判为「暂存集越界」并回滚
            # 本次 purge。
            staged_set = {
                _unquote_git_path(ln) for ln in staged.stdout.splitlines()
            }
            if staged.returncode != 0 or not staged_set <= set(victims):
                self.logger.warning(
                    "worktree_manager",
                    f"Purge skipped: index has staged entries beyond purged "
                    f"paths: {sorted(staged_set - set(victims))}",
                )
                self._reset_index_paths(victims)
                return
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
                self._reset_index_paths(victims)
        except (subprocess.TimeoutExpired, OSError) as e:
            self._reset_index_paths(victims)
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
            # -c core.quotePath=false（code-review item 4ce10509fde4）：非 ASCII
            # DU 冲突路径保持原样输出，否则 porcelain 的 C 转义引号形会被原样
            # 拼入下方 git rm --cached 与 check-ignore 的 pathspec（永不命中）
            # → git rm 返回非 0 → 自愈恒失败回退 merge --abort。与
            # _collect_conflict_paths / _list_unmerged_files 的采集点同口径。
            status = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "-c",
                    "core.quotePath=false",
                    "status",
                    "--porcelain",
                ],
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
