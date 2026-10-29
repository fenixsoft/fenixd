"""stash_guard.py — G6 主树还原/autostash 治理（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 9 个方法，原样搬移为 mixin（方法体零改动）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from core.timelib import now_local  # noqa: E402
from core.worktree_manager import (  # noqa: E402
    AUTOSTASH_MSG_PREFIX,
)
from core.git_text import unquote_git_path  # noqa: E402


def _split_rename_sides(field: str) -> list:
    """按 C-quote 感知方式拆分 porcelain rename 行的 "old -> new" 载荷。

    porcelain v1 对 rename 两侧**各自独立** C-quote，且路径含空格即强制
    引号（wt-status 的 QUOTE_PATH_QUOTE_SP），故文件名自含「 -> 」时该侧
    恒带引号（如 ``R  "a -> b.txt" -> c.txt``）。朴素 ``split(" -> ")`` 会把
    引号内路径自含的「 -> 」一并切开成 3 段，逐段反转义产出错误路径，脏
    tracked 清单失真（code-review item f2804188bd68）。

    只把**引号外**的「 -> 」视为分隔符：引号内的字符原样归入当前侧
    （``\\"``/``\\\\`` 等转义序列成对跳过，不误判引号闭合），两侧各自保留
    引号形交由调用方 ``unquote_git_path`` 反转义。无引号载荷的切分结果
    与旧 ``split(" -> ")`` 逐字节一致（git ≥ 2.25 起含空格路径必带引号，
    无引号却含「 -> 」的载荷仅见于更老 git，彼时文本本身不可判定）。
    """
    sides: list = []
    buf: list = []
    in_quote = False
    i = 0
    n = len(field)
    while i < n:
        ch = field[i]
        if in_quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                # 转义序列两字符一并收入（\\" 不算闭合、\\\\ 不算转义起始）
                buf.append(field[i + 1])
                i += 2
                continue
            if ch == '"':
                in_quote = False
            i += 1
            continue
        if ch == '"':
            in_quote = True
            buf.append(ch)
            i += 1
            continue
        if field.startswith(" -> ", i):
            sides.append("".join(buf).strip())
            buf = []
            i += 4
            continue
        buf.append(ch)
        i += 1
    sides.append("".join(buf).strip())
    return sides


# ``git stash pop`` 成功输出中 Dropped 行的 sha 捕获（restore_after_merge 与
# reclaim 两侧防插队核对共用同一解析，code-review item 9cd4bd49ca8d）。
_DROPPED_STASH_RE = re.compile(r"Dropped refs/stash@\{\d+\} \(([0-9a-f]+)\)")


def _parse_dropped_stash_sha(pop_stdout: str | None) -> str:
    """从 ``git stash pop`` 成功输出解析 Dropped 行的被弹条目 sha。

    同 ``_rev_parse_stash_top`` 的收口方式：pop 后「被弹条目是否确为本方
    条目」的核对（restore_after_merge / _reclaim_stale_autostash_locked）
    共用同一解析与比对基准，不再一侧正则解析、一侧子串包含（子串法会被
    pop 输出其它行恰好含该 sha 十六进制串骗过、漏报误弹）。解析不到
    Dropped 行（输出形态变化）返回空串，调用方按「无法核对」跳过、不误报。
    """
    m = _DROPPED_STASH_RE.search(pop_stdout or "")
    return m.group(1) if m else ""


class G6StashGuardMixin:
    """G6 主树还原/autostash 治理（design D1 表 A G6）。"""


    def _list_dirty_tracked_files(self, status_stdout: str | None = None) -> list:
        """提取主树脏 tracked 文件清单（fix-mergeback-stashpop-silent-loss D3）。

        ensure_clean_tree 的 porcelain 脏判定提炼为共享 helper：porcelain v1
        每行 "XY " 前缀，X=索引状态、Y=工作区状态，第 3 个字符恒为分隔符空格
        ——脏判定看 [0]/[1] 任一非空格（历史版本误查 [2] 致 autostash 从未
        触发，2026-09-02 修）。untracked（'??'）不计入。命令失败返回空列表
        （调用方按「无重叠」处理，不阻塞流程）。

        路径反转义：porcelain 对含非 ASCII/特殊字符的路径默认输出 C-quoted
        转义形（如 "core/\346\226\207.tsx"），逐段经 `unquote_git_path`
        （core.git_text 反转义，与 mergeback 同源）还原为真实路径——消费方（mergeback WIP 闸门 /
        code-fix 批 WIP 重叠预检）拿真实路径比对求交，带引号转义形会永不命中。

        Args:
            status_stdout: 已取回的 ``git status --porcelain`` stdout，传入时
                跳过子进程调用直接解析（调用方自行保证其 rc==0，命令失败的
                情形由调用方按各自口径处置），供持锁临界区复用同一次查询
                结果、消除重复子进程开销（code-review item e4d825bb770e）。

        Returns: 排序后的脏 tracked 文件路径列表（rename 两侧都计入，已反转义）。
        """
        if status_stdout is None:
            try:
                result = subprocess.run(
                    ["git", "-C", str(self.project_root), "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
                return []
            if result.returncode != 0:
                return []
            status_stdout = result.stdout
        files: list = []
        for line in status_stdout.splitlines():
            if len(line) < 3 or line.startswith("?? "):
                continue
            path = line[3:].strip()
            if " -> " in path:
                # porcelain 对 rename 两侧各自 C-quote，按段逐个反转义；
                # 切分须 C-quote 感知——引号内路径自含「 -> 」不参与切分
                # （code-review item f2804188bd68），无引号载荷行为不变
                files.extend(
                    unquote_git_path(p) for p in _split_rename_sides(path)
                )
            else:
                files.append(unquote_git_path(path))
        return sorted(p for p in files if p)

    def ensure_clean_tree(self, prefix: str | None = None) -> bool:
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
                encoding="utf-8",
                errors="replace",
                timeout=30,
                # 仅本命令固化 C locale（对齐 queries.create_worktree_on_branch
                # 的 LC_ALL=C 手法）：下方依赖英文子串 "No local changes" 判定
                # 是否真正 stash 过，本地化 git（如 zh_CN 装了 translation）会把
                # 该串（git 内经 _() 包装可翻译）输出为译文、子串匹配落空 → 误判
                # 「已 stash」返回 True → mergeback finally 的 restore_after_merge
                # 把 stash 栈顶（可能是用户手工 stash 的无关条目）弹到刚合并完的
                # 主树上（_main_tree_lock 要防的 LIFO 错配）。C locale 无翻译
                # 目录，输出恒为英文。
                env={**os.environ, "LC_ALL": "C"},
            )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
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
          未消解 unmerged 条目；或复查枚举失败，无法证明已消解，同口径
          处置）——主树仍半合并，交人工处置（与 ``reclaim_stale_autostash``
          的复查口径一致）。
        - ``(False, [])``：pop 失败且非冲突类（如其它 git 错误），stash 保留；调用方按
          旧版 False 语义处理（主树可能仍半合并，需人工处置）。pop 前钉 sha
          超时/不可用同口径放弃本轮也返回此值——主树已合并完、仅本方条目
          滞留栈顶，交 reclaim_stale_autostash 巡检兜底。pop 输出含 CONFLICT
          但 UU 枚举失败（``_list_unmerged_files`` 返回 None，code-review
          item f636712de58a）也返回此值——无法证明冲突已消解，保守交人工。

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
        # 钉取复用 _rev_parse_stash_top（code-review item 17bbe8ea6021）：与下方
        # 栈顶复核共用同一子进程调用与容错，不再维护同型内联副本。
        pinned_sha = ""
        rev = self._rev_parse_stash_top()
        if rev is None:
            # git 超时/不可用：钉不住 sha = 无法证明栈顶未动，与下方复核阶段
            # 同口径放弃本轮绝不弹（条目保留交 reclaim_stale_autostash 巡检兜底）
            self.logger.warning(
                "worktree_manager",
                "Stash pop skipped, top-of-stack pin unavailable "
                "(git unavailable, stash preserved)",
            )
            return False, []
        if rev[0] == 0:
            pinned_sha = rev[1].strip()

        # pop 前复核栈顶仍为钉住条目（code-review item c6d22fdac25f，对齐
        # _reclaim_stale_autostash_locked 的防插队口径）：pop 弹的是栈顶而非
        # pinned_sha——_main_tree_lock 只串行化本进程，dashboard 侧独立
        # WorktreeManager（admin_actions 等以 logger=None 构造）或人工在此
        # 窗口 push 新条目时，不复核会把他人条目弹到刚合并完的主树上、自家
        # guard 条目反滞留栈顶（LIFO 错配）。
        guard = self._rev_parse_stash_top()
        if guard is None:
            # 复核不可用 = 无法证明栈顶未动：放弃本轮绝不弹（条目保留）
            self.logger.warning(
                "worktree_manager",
                "Stash pop skipped, top-of-stack guard unavailable "
                "(stash preserved)",
            )
            return False, []
        guard_rc, guard_out = guard
        if pinned_sha:
            if guard_rc != 0 or guard_out.strip() != pinned_sha:
                self.logger.error(
                    "worktree_manager",
                    f"Stash pop aborted: stash top moved since pin "
                    f"(expected {pinned_sha[:12] or 'n/a'}) — stash preserved, "
                    f"防跨进程插队误弹他人条目",
                )
                return False, []
        else:
            # pin 未取到（stashed=True 栈本应非空——多半已被跨进程移除）：
            # 复核不能整体跳过（code-review item 01775ad636dd），pop 前再核一次
            # 栈顶——此刻栈已非空说明 pin 后有新条目进入，无法证明栈顶是本方
            # 条目，按「栈顶已动」口径放弃本轮（条目保留交 reclaim_stale_autostash
            # 兜底）；栈仍为空则落到下方 pop 的 No stash entries 正常跳过路径。
            if guard_rc == 0:
                self.logger.error(
                    "worktree_manager",
                    f"Stash pop aborted: stack top present but pin unavailable "
                    f"(expected {pinned_sha[:12] or 'n/a'}) — stash preserved, "
                    f"防跨进程插队误弹他人条目",
                )
                return False, []

        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "stash", "pop"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                # 仅本命令固化 C locale（同 ensure_clean_tree 的 stash push）：
                # 下方依赖英文子串 "No stash entries"（无 stash 可恢复的正常跳过）
                # 与 "CONFLICT"（进入三态自愈）做判定，本地化 git 下判定翻转会
                # 破坏 guard finally 链的恢复语义。
                env={**os.environ, "LC_ALL": "C"},
            )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
            # 本方法常在 guard 的 finally 中执行，绝不能外抛（会吞掉业务原始
            # 异常并中断清理链）——按旧版非冲突失败语义降级，stash 条目保留
            self.logger.warning(
                "worktree_manager",
                f"Stash pop failed (non-conflict, stash preserved): {e}",
            )
            return False, []
        if result.returncode == 0:
            # pop 成功后核对被弹条目（对齐 reclaim 侧防插队口径，code-review
            # item e61e122c2d36）：上方复核与本次 pop 之间仍留跨进程窗口
            # （_main_tree_lock 只串行化本进程，dashboard 侧独立 WorktreeManager
            # 或人工 push 不受其约束），窗口内栈顶被插队时 pop 弹的是他人条目。
            # pop 输出含「Dropped refs/stash@{0} (<sha>)」，解析出的 sha 与
            # pinned_sha 不一致即误弹，记 ERROR 供人工按 sha 排查；解析不到
            # Dropped 行（输出形态变化）或 pin 为空时跳过核对不误报。仅补
            # 观测，不改变 pop 成功的返回语义（同 reclaim_stale_autostash）。
            # Dropped 行解析收口 _parse_dropped_stash_sha（code-review item
            # 9cd4bd49ca8d），与 reclaim 侧共用同一解析与比对逻辑。
            dropped_sha = _parse_dropped_stash_sha(result.stdout)
            if pinned_sha and dropped_sha and dropped_sha != pinned_sha:
                self.logger.error(
                    "worktree_manager",
                    f"Stash popped a concurrent entry after merge (expected "
                    f"{pinned_sha[:12]}, dropped {dropped_sha[:12]}); inspect "
                    f"main tree and stash reflog",
                )
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
        if conflict_files is None:
            # UU 枚举失败（code-review item f636712de58a）：空列表与枚举失败
            # 不可再混淆——无法证明冲突已自行消解，按半合并保守处置交人工
            # （stash 条目保留），不谎报「主树回到可写状态」
            self.logger.error(
                "worktree_manager",
                f"Stash pop conflict reported but UU enumeration failed; "
                f"stash preserved: {output.strip()}",
            )
            return False, []
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
            if residual is None:
                # 复查枚举失败（同 item f636712de58a）：无法证明 UU 已消解，
                # 与「仍有残留」同口径按 False 交人工，不谎报主树可写
                self.logger.error(
                    "worktree_manager",
                    f"Stash pop conflict triage residual check failed "
                    f"(mode={mode}); unmerged state unverifiable, stash "
                    f"entry preserved (recover via: {recover_cmds})",
                )
                return False, conflict_files
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

    def _rev_parse_stash_top(self) -> tuple[int, str] | None:
        """「栈顶复核」共享 helper（code-review item f12db94635ff）：
        ``git rev-parse --verify stash@{0}``，供 restore_after_merge 的
        pinned / 未 pinned 两分支与 _reclaim_stale_autostash_locked 的
        sha 钉取/防插队/drop 前复核三处复用同一子进程调用与容错，分支
        各自只留 returncode 判定方向与文案。

        Returns: ``(rc, stdout)``；git 超时/不可用返回 None（调用方按
        「guard 不可用」口径放弃本轮绝不弹）。本调用链位于 guard 的
        finally 中，异常在此吸收、绝不外抛（对齐 restore_after_merge
        的容错契约）。
        """
        try:
            rev = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse",
                 "--verify", "stash@{0}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
            return None
        return rev.returncode, rev.stdout

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
            except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
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
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
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
            try:
                st = subprocess.run(
                    ["git", "-C", str(self.project_root), "add", "--", f],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
                # 本调用链常在 guard 的 finally 中执行，绝不能外抛（会吞掉已
                # 成功的 merge 结果并中断清理链）——超时/不可用按态 1 失败处置
                # 进态 2（与 returncode!=0 同路径）
                self.logger.warning(
                    "worktree_manager",
                    f"State-1 git add failed for '{f}': {e} — falling to state 2",
                )
                remaining.append(f)
                continue
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
        checkout_failed: list = []
        for f in remaining:
            try:
                co = subprocess.run(
                    ["git", "-C", str(self.project_root), "checkout", "--theirs", "--", f],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
                # 本调用链常在 guard 的 finally 中执行，绝不能外抛（会吞掉已
                # 成功的 merge 结果并中断清理链）——超时/不可用记 warning 后
                # continue 处理其余文件（全部尝试完再统一转态 3，见下方归因）：
                # stash 版仍在 index stage 3 + 工作区冲突标记，不丢数据。
                self.logger.warning(
                    "worktree_manager",
                    f"State-2 checkout --theirs failed for '{f}' ({e}) — "
                    f"stash content preserved in worktree/index",
                )
                checkout_failed.append(f)
                continue
            if co.returncode != 0:
                # --theirs 失败（罕见：路径仍 UU）：stash 版在 index stage 3 +
                # 工作区冲突标记仍保留两侧，不丢数据；记 warning 继续其余文件
                self.logger.warning(
                    "worktree_manager",
                    f"State-2 checkout --theirs failed for '{f}' "
                    f"({co.stderr.strip()}) — stash content preserved in "
                    f"worktree/index",
                )
                checkout_failed.append(f)
        if checkout_failed:
            # 全部 remaining 均已尝试落盘后才统一转态 3（code-review item
            # 4b3b7dde58ce：此前首个失败即返回，其余文件不再尝试取回 stash 版，
            # 自愈覆盖面静默缩水）。任一失败即放弃本次恢复 commit——对仍 UU 的
            # 路径 git add 会把冲突标记内容入库、洗白半合并状态骗过调用方的
            # 残留复查；失败文件 stash 版仍在 index stage 3 + 工作区冲突标记，
            # 条目保留，调用方尾部残留复查对 UU 残留按 False 交人工。
            return 3, (
                "state-2 checkout --theirs failed for: "
                + ", ".join(f"'{f}'" for f in checkout_failed)
            )
        try:
            add = subprocess.run(
                ["git", "-C", str(self.project_root), "add", "--", *conflict_files],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
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
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if cmt.returncode != 0:
                raise RuntimeError(
                    f"git commit --only failed: "
                    f"{(cmt.stderr or cmt.stdout).strip()}"
                )
            return 2, f"recovery commit: {cmt.stdout.splitlines()[0] if cmt.stdout else ''}"
        except (subprocess.TimeoutExpired, RuntimeError, OSError, UnicodeDecodeError) as exc:
            # ── 态 3 兜底：stash 版内容已在工作区（--theirs 落盘），显式登记
            # disposition，绝不静默丢弃（条目保留、信号照发）。OSError 同归
            # 态 3（code-review item 6234a624bb5d）：subprocess.run 自身的
            # spawn 失败（临时性 fork 失败、EMFILE、磁盘满等）原先会穿出本
            # 方法、违反 restore_after_merge「绝不能外抛」契约——与上方态 1
            # add / 态 2 checkout 的 (TimeoutExpired, OSError) 容错口径对齐。
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
          - 主树 tracked 脏说明用户正在工作，不抢（untracked 文件不计入，
            同 ensure_clean_tree 的 tracked-only 口径）；
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

        与 merge-back 的互斥（code-review item 5ed4e6352f2f）：本方法的
        「栈顶探测→pop→drop」序列全程在 ``_main_tree_lock`` 内执行，与
        ``merge_back_from_branch`` 的 stash→merge→pop 临界区互斥。引擎层
        ``reclaim_stale_autostash_if_idle`` 的 ``_active_runs > 0`` 空闲预检是
        非原子的先验判断：巡检的多次 subprocess 秒级窗口内仍可能有新 run
        启动并 ``ensure_clean_tree`` 压栈，仅靠「栈顶 sha 未变」复核无法区分
        「滞留旧条目」与「刚被 merge-back 压入的条目」，可能把后者当滞留条目
        弹出恢复到干净主树、令 ``restore_after_merge`` 落空（LIFO 错配）。
        锁为非重入 ``threading.Lock``：本调用链（fenixd 主循环 →
        engine.reclaim_stale_autostash_if_idle → 本方法）进入时不持有该锁，
        临界区内也不调用会再次取锁的函数（不调 ``ensure_clean_tree`` /
        ``merge_back_from_branch``）。以非阻塞 acquire 参与互斥：锁被占用
        （merge-back 进行中）时本轮直接放弃、条目保留交下轮巡检——与
        「主树脏不抢」同一退化语义，也不阻塞调用方主循环。
        """
        if not self._main_tree_lock.acquire(blocking=False):
            self.logger.info(
                "worktree_manager",
                "Stale autostash reclaim skipped (main tree lock busy: "
                "merge-back in progress)",
            )
            return False
        try:
            return self._reclaim_stale_autostash_locked()
        finally:
            self._main_tree_lock.release()

    def _reclaim_stale_autostash_locked(self) -> bool:
        """reclaim_stale_autostash 的实现体，调用方必须已持有 _main_tree_lock
        （口径同 mergeback._merge_back_from_branch_locked）。

        与进程内 merge-back 临界区互斥后，「栈顶 sha 未变」双复核仍保留：
        锁只串行化本进程（dashboard 侧跨进程 merge-back 不共享内存锁），
        sha 核对继续防跨进程插队误弹。
        """
        try:
            status = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
            # git 超时/不可用：本轮放弃回收（条目保留交下轮巡检），不让异常穿出
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaim skipped (git unavailable): {e}",
            )
            return False
        # 干净判定复用 _list_dirty_tracked_files 的 tracked-only 口径（与
        # ensure_clean_tree 一致）：本模块的 autostash 只 stash tracked 修改，
        # 存在普通 untracked 文件不应让巡检无限期跳过回收；status 命令失败
        # （rc!=0）仍按「脏」保守放弃本轮。脏判定复用上方已取回的 status
        # 输出，不在持锁临界区内重复起同一子进程（code-review item
        # e4d825bb770e；mergeback.py 把「逐路径起子进程线性放大持锁时长」
        # 列为设计关注点）。
        if status.returncode != 0 or self._list_dirty_tracked_files(
            status_stdout=status.stdout
        ):
            return False
        try:
            lst = subprocess.run(
                ["git", "-C", str(self.project_root), "stash", "list", "-n", "1"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaim skipped (git unavailable): {e}",
            )
            return False
        # 格式：stash@{0}: On <branch>: fenix: pre-dispatch autostash
        top = lst.stdout.strip() if lst.returncode == 0 else ""
        if AUTOSTASH_MSG_PREFIX not in top:
            return False
        rev = self._rev_parse_stash_top()
        if rev is None:
            # git 超时/不可用：本轮放弃回收（条目保留交下轮巡检），不让异常穿出
            self.logger.warning(
                "worktree_manager",
                "Stale autostash reclaim skipped (git unavailable)",
            )
            return False
        rev_rc, rev_out = rev
        # sha_before 即时取自当前栈顶（stash list 已确认栈顶带 AUTOSTASH 前缀），
        # 钉取与 pop 之间无任何语句，不再紧邻二次复核（code-review item
        # fd53642a6ddc：紧邻复核无插队窗口、防护空转，白付一次持锁临界区内的
        # 子进程开销）；实际防线是下方 TOCTOU 干净重查、pop 输出 sha 核对与
        # drop 前的 sha 复核。
        sha_before = rev_out.strip() if rev_rc == 0 else ""
        if rev_rc != 0:
            # 栈非空（stash list 有前缀条目）却核不出栈顶 sha——git 异常态，
            # 钉不住目标条目即无法防误弹：保守放弃本轮，条目保留交下轮巡检
            # （原紧邻复核对同型失败的同口径放弃，改由首次钉取直接判定）。
            self.logger.error(
                "worktree_manager",
                "Stale autostash reclaim aborted: top-of-stack sha "
                "unavailable, skip this round to avoid mis-pop",
            )
            return False
        # TOCTOU 复核（code-review item 9a1a53693bb4）：上方干净判定与 pop 之间
        # 还隔着 stash list / rev-parse 等多个子进程，窗口内用户（或
        # dashboard 侧进程）可能向主树落盘新改动——若与 autostash 条目触碰同一
        # 文件，pop 冲突后 _heal_unmerged_files 的 checkout -f 会把窗口内写入的
        # 未提交修改一并丢弃。pop 前重查一次 tracked 干净态（口径同函数开头：
        # rc!=0 按「脏」保守放弃；开销为一次子进程，同 _discard_identical_local
        # _changes 的丢弃前二次校验模式），脏则放弃本轮，条目保留交下轮巡检。
        try:
            recheck = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash reclaim skipped (git unavailable): {e}",
            )
            return False
        if recheck.returncode != 0 or self._list_dirty_tracked_files(
            status_stdout=recheck.stdout
        ):
            self.logger.warning(
                "worktree_manager",
                "Stale autostash reclaim aborted: main tree turned dirty "
                "between clean check and pop (TOCTOU recheck), skip this "
                "round and preserve the stash entry",
            )
            return False
        try:
            # 仅本命令固化 C locale（对齐上方 ensure_clean_tree/restore_after_merge
            # 的 LC_ALL=C 手法）：下方依赖英文子串 "CONFLICT" 判定是否进入 UU 自愈，
            # 本地化 git（如 zh_CN 装了 translation）会把冲突输出翻译为译文、子串
            # 匹配落空 → pop 冲突被当成非冲突失败处理，主树滞留半合并 UU 状态且
            # stash 条目不 drop，巡检每轮因主树脏而放弃。C locale 无翻译目录，
            # 输出恒为英文。
            pop = subprocess.run(
                ["git", "-C", str(self.project_root), "stash", "pop", "stash@{0}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                env={**os.environ, "LC_ALL": "C"},
            )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
            # git 超时/不可用：与非冲突失败同语义，stash 条目保留交下轮巡检
            self.logger.warning(
                "worktree_manager",
                f"Stale autostash pop failed (entry preserved): {e}",
            )
            return False
        if pop.returncode == 0:
            # pop 输出含「Dropped refs/stash@{0} (<sha>)」：核对被弹条目确为
            # sha_before，不一致说明复核后仍发生并发插队造成误弹，记 ERROR
            # 供人工按 sha 排查。解析收口 _parse_dropped_stash_sha（code-review
            # item 9cd4bd49ca8d，对齐 restore_after_merge 口径）：子串包含会被
            # pop 输出其它行（如被恢复文件路径）恰好含该 sha 十六进制串骗过、
            # 漏报误弹；解析不到 Dropped 行时跳过核对不误报。
            dropped_sha = _parse_dropped_stash_sha(pop.stdout)
            if sha_before and dropped_sha and dropped_sha != sha_before:
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
            if conflict_files is None:
                # UU 枚举失败（code-review item f636712de58a）：拿不到名单，
                # 跳过 heal，交下方残留复查兜底（复查再失败则条目保留不 drop）
                self.logger.warning(
                    "worktree_manager",
                    "Stale autostash pop conflict UU enumeration failed; "
                    "skip self-heal and fall through to residual recheck",
                )
                conflict_files = []
            if conflict_files:
                # 自愈语义是统一回退 HEAD 版本：下列文件上的 stash/冲突态改动
                # 全部丢弃（并非「保留 merge 结果」），此处明示丢弃面。
                self.logger.warning(
                    "worktree_manager",
                    "Autostash pop conflict self-heal discards local changes "
                    f"on: {', '.join(conflict_files)}",
                )
                self._heal_unmerged_files(conflict_files)
            residual = self._list_unmerged_files()
            if residual is None:
                # 残留复查枚举失败（同 item f636712de58a）：无法证明自愈完成，
                # 条目保留交下轮巡检/人工，绝不 drop
                self.logger.error(
                    "worktree_manager",
                    "Stale autostash pop conflict heal unverifiable (UU "
                    "enumeration failed); stash entry preserved "
                    "(recover via git stash show)",
                )
                return False
            if residual:
                # 自愈未完成（checkout 超时等）：条目保留交人工，绝不 drop
                self.logger.error(
                    "worktree_manager",
                    f"Stale autostash pop conflict heal incomplete; unmerged "
                    f"files remain, stash entry preserved "
                    f"(recover via git stash show)",
                )
                return False
            drop_sha = ""
            # 保留归因取证位预置（code-review item 792321ce0d47）：cur/dropped
            # 仅在 sha_before 非空时才被赋值，下方 else 分支按情形归因须可安全
            # 读取（空基准 sha 时未复核未 drop，不属任何已尝试情形）。
            cur = None
            dropped = None
            if sha_before:
                # git 超时/不可用返回 None：核不了 sha，按「栈顶已动」降级（不 drop）
                cur = self._rev_parse_stash_top()
                if (
                    cur is not None
                    and cur[0] == 0
                    and cur[1].strip() == sha_before
                ):
                    try:
                        dropped = subprocess.run(
                            ["git", "-C", str(self.project_root), "stash", "drop", "stash@{0}"],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=30,
                        )
                    except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
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
                # 保留归因按情形区分（code-review item 792321ce0d47）：「top
                # entry moved」只在栈顶 sha 确已变化一种情形下属实——git 故障
                # （复核不可用）与 drop 命令自身失败如实分开记，避免基础设施
                # 故障被误述成并发插队、误导人工按 sha 去排查不存在的插入条目；
                # 无基准 sha（pop 前就没核到）时未尝试 drop，单独归因。
                if not sha_before:
                    preserved_because = (
                        "pre-pop top sha unavailable; drop not attempted"
                    )
                elif cur is not None and cur[0] == 0 and cur[1].strip() != sha_before:
                    # 栈顶确被并发条目改动（code-review item 10eb7d162811）：
                    # drop 因 sha 守卫短路根本未尝试，dropped 恒 None——归因
                    # 先判插队再按 dropped 取值区分命令故障，避免把并发插队
                    # 误述成 stash drop failed（原尾部 else 分支在此归因序下
                    # 恒不可达：dropped.returncode==0 时必已置 drop_sha 走上方）。
                    preserved_because = "top entry moved"
                elif cur is None or cur[0] != 0:
                    preserved_because = (
                        "stash top recheck unavailable (git fault)"
                    )
                elif dropped is None or dropped.returncode != 0:
                    preserved_because = "stash drop failed"
                else:
                    preserved_because = "top entry moved"
                self.logger.warning(
                    "worktree_manager",
                    f"Stale autostash pop conflicted with merged "
                    f"implementation; healed UU files {conflict_files}, "
                    f"stash entry preserved ({preserved_because}, recover via "
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
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if reset.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Self-heal index rollback failed: "
                    f"{(reset.stderr or reset.stdout).strip()}",
                )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Self-heal index rollback failed: {e}",
            )

    def _untrack_index_paths(self, paths: list, commit_msg: str, log_ctx: str) -> bool:
        """把 paths 移出索引并作为独立提交落盘（untrack/purge 共享自愈骨架）。

        封装两入口的共同流程：``git rm -f --cached`` 循环 → ``diff --cached``
        名单反转义 + staged 子集守卫 → 裸 ``git commit`` → 失败时
        ``_reset_index_paths`` 回滚。check-ignore 校验与路径枚举属各自差异段，
        留在入口完成（_untrack_ignored_local_changes 的「全须忽略」前置校验 /
        _purge_ignored_brought_in 的 victims 枚举）。

        回滚集合语义取 purge 侧 processed 口径（code-review item
        f5b05c836fd7）：只回滚已成功 rm --cached 的路径，rm 中途失败同样回滚
        本次已移出的索引态，任何中止分支均不残留 staged 删除。

        Args:
            paths: 要移出索引的路径（真实路径，反转义由调用方负责）。
            commit_msg: 裸 commit 的提交说明（两入口文案不同：merge 前/后）。
            log_ctx: 日志前缀（"Self-heal (untrack)" / "Purge ignored
                brought-in"），保持两入口日志可区分归因。

        Returns: True 表示已全部移出并提交。
        """
        processed: list = []  # 已成功 rm --cached 的路径（中途失败按此回滚索引态）
        try:
            for path in paths:
                rm = subprocess.run(
                    ["git", "-C", str(self.project_root), "rm", "-f", "--cached", "--", path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if rm.returncode != 0:
                    # rm 失败（如 index.lock 争用）：路径仍 tracked，继续的话
                    # staged 子集校验是单向的（只要求子集、不强求路径入暂存集）、
                    # 裸 commit 会把该路径照常入库，本自愈对该路径静默失效
                    # （untrack 撞 DRY 拒绝 / purge 撞车循环原样重启）——先回滚
                    # 本次已移出的索引态再放弃（不残留 staged 删除），WARNING
                    # 留观测。
                    self.logger.warning(
                        "worktree_manager",
                        f"{log_ctx}: git rm --cached failed for "
                        f"'{path}': {(rm.stderr or rm.stdout).strip()} — reverting "
                        f"index, aborting",
                    )
                    self._reset_index_paths(processed)
                    return False
                processed.append(path)
            # 路径作用域守卫：裸 commit 会把 index 里其它 staged 条目连带入库，
            # 校验暂存集不含本次 rm --cached 路径之外的外来条目，有则放弃自愈
            # （先回滚本次已 rm 的索引态再返回，不残留 staged 删除）。
            # 只做子集校验、不强求自愈路径必须出现在暂存集（其入暂存已由上方
            # rm --cached 的返回码保证），避免对暂存态探测过严而误杀正常自愈。
            # staged 名单须反转义：diff --cached 对非 ASCII 路径默认输出
            # C-quoted 转义形，不反转义会把该类路径误判为「暂存集越界」。
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
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            staged_set = {
                unquote_git_path(ln) for ln in staged.stdout.splitlines()
            }
            if staged.returncode != 0:
                # 命令本身失败（index.lock 争用、git 不可用等）：暂存集内容不可信，
                # 按「diff --cached failed」归因，勿冒充「越界暂存条目」误导排障
                # （code-review item 8af338d766c3）
                self.logger.warning(
                    "worktree_manager",
                    f"{log_ctx} aborted: git diff --cached failed: "
                    f"{(staged.stderr or staged.stdout).strip()}",
                )
                self._reset_index_paths(processed)
                return False
            if not staged_set <= set(paths):
                self.logger.warning(
                    "worktree_manager",
                    f"{log_ctx} aborted: index has staged entries "
                    f"beyond processed paths: {sorted(staged_set - set(paths))}",
                )
                self._reset_index_paths(processed)
                return False
            commit = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "commit",
                    "-m",
                    commit_msg,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if commit.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"{log_ctx}: commit failed: "
                    f"{(commit.stderr or commit.stdout).strip()}",
                )
                self._reset_index_paths(processed)
                return False
            return True
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
            self._reset_index_paths(processed)
            self.logger.warning("worktree_manager", f"{log_ctx} failed: {e}")
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
        rm/staged 子集守卫/commit/回滚骨架共享自 ``_untrack_index_paths``
        （code-review item f5b05c836fd7），本入口只保留「全须忽略」前置校验
        与自身日志文案。

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
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if chk.returncode not in (0, 1):
                    # check-ignore 退出码 0=有忽略命中、1=全部未命中，其余为
                    # 命令 fatal（index.lock 争用、git 不可用等），忽略态不可
                    # 判定：按「check-ignore 命令失败」单独归因记日志，勿冒充
                    # 「路径未被忽略——非运行时草稿」把排障引向路径校验方向
                    # （对照 _untrack_index_paths 的 diff --cached 失败分支与
                    # purge 侧 check-ignore 批量口径，code-review item
                    # 8af338d766c3 / 2d526a1254d6）。
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (untrack) aborted: git check-ignore failed "
                        f"for '{path}': {(chk.stderr or chk.stdout).strip()}",
                    )
                    return False
                if chk.returncode == 1:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (untrack) aborted: '{path}' is not gitignored "
                        f"— not a runtime draft",
                    )
                    return False
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
            return False
        ok = self._untrack_index_paths(
            paths,
            "[fenix] fix: merge 前移出被误提交的 ignored 运行时草稿",
            "Self-heal (untrack)",
        )
        if ok:
            self.logger.info(
                "worktree_manager",
                f"Self-heal (untrack): moved ignored tracked drafts out of index: "
                f"{', '.join(paths)}",
            )
        return ok

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
        branch_contents = {}
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
                        f"branch content — possible real local work "
                        f"(byte-level compare; a mismatch may also be eol "
                        f"normalization only, e.g. core.autocrlf or "
                        f".gitattributes eol rules)",
                    )
                    return False
                identical.append(path)
                branch_contents[path] = show.stdout
            backup_root = self.project_root / ".fenix" / "merge-backup"
            base_name = f"identical-{int(time.time())}"
            backup = backup_root / base_name
            # 同名冲突处理（对齐 mergeback._backup_untracked_spec_files 的
            # code-review item e27367b20119 口径）：_main_tree_lock 只串行化本
            # 进程，跨进程（dashboard 手工 merge-back 与 daemon）撞同一秒时目录
            # 同名静默复用，shutil.copy2 到已存在 dst 会覆盖抹掉既有备份——目标
            # 已存在时追加微秒后缀，极端情况仍冲突再用递增序号兜底。
            if backup.exists():
                ms = now_local().strftime("%f")  # SPEC-B 批④收拢（微秒唯一性后缀）
                backup = backup_root / f"{base_name}-{ms}"
                n = 1
                while backup.exists():
                    backup = backup_root / f"{base_name}-{ms}-{n}"
                    n += 1
            for path in identical:
                dest = backup / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.project_root / path, dest)
            # TOCTOU 复核（code-review item 4cfadd9162b5）：字节比对与 checkout
            # 之间无原子性，跨进程（_main_tree_lock 只串行化本进程）可能在比对
            # 通过后改写文件——备份后对每路径重读二次校验，不一致即放弃自愈
            # （不执行 checkout，把裁决交回失败路径，备份已留存可人工找回）。
            for path in identical:
                if (self.project_root / path).read_bytes() != branch_contents[path]:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal (identical) aborted: '{path}' changed after "
                        f"compare — possible real local work",
                    )
                    return False
            co = subprocess.run(
                ["git", "-C", str(self.project_root), "checkout", "HEAD", "--", *identical],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if co.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Self-heal (identical): git checkout failed: "
                    f"{(co.stderr or co.stdout).strip()}",
                )
                return False
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
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
        （工作区副本保留），无此类路径时零开销跳过。rm/staged 子集守卫/commit/
        回滚骨架共享自 ``_untrack_index_paths``（code-review item
        f5b05c836fd7），本入口只保留 victims 枚举与自身日志文案。
        """
        # victims 供枚举段异常时兜底回滚；rm 段的回滚口径见 _untrack_index_paths
        # 的 processed（只回滚已成功 rm --cached 的路径）。
        victims: list = []
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
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if diff.returncode != 0:
                # 命令失败（index.lock 争用、git 不可用、old_head 失效等）与
                # 「无新增路径」不可混同（code-review item a14b215ba4d4）：
                # 本自愈承担防撞车循环复发的职责，枚举失败被静默吞掉后被
                # ignore 草稿保持 tracked、下一轮脏修改重致撞车循环复发，
                # 日志却无任何 purge 痕迹可排障——记 warning 对齐同文件其余
                # 失败路径（_untrack_index_paths 各中止分支）的日志口径。
                self.logger.warning(
                    "worktree_manager",
                    f"Purge ignored brought-in: diff enumeration failed: "
                    f"{(diff.stderr or diff.stdout).strip()}",
                )
                return
            if not diff.stdout.strip():
                return
            # 路径反转义（同 _list_dirty_tracked_files 口径）：diff --name-only
            # 对非 ASCII/特殊字符路径默认输出 C-quoted 转义形，不反转义则下方
            # ls-files/check-ignore/rm --cached 的 pathspec 永不命中，purge
            # 对该类文件静默跳过。
            cands = [
                unquote_git_path(ln.strip())
                for ln in diff.stdout.splitlines()
                if ln.strip()
            ]
            # 批量口径（item 2eecaa4ef78d，对照 mergeback._backup_untracked_spec_files
            # 的 d307bc3bd39e）：本方法在 merge 成功后的 _post_merge_finalize 内执行
            # （调用链仍持有 _main_tree_lock），逐路径起 ls-files --error-unmatch 与
            # check-ignore 子进程会随新增路径线性放大主树全局合并锁持锁时长。tracked
            # 判定收敛为单条 ``ls-files -z -- :(literal)<全部候选>``（:(literal) 禁
            # pathspec glob、-z 免 core.quotePath 转义），输出集合即 tracked 集，
            # 不在集合中与逐路径 --error-unmatch 非 0 等价（已不在索引/不存在）。
            ls = subprocess.run(
                ["git", "-C", str(self.project_root), "ls-files", "-z", "--"]
                + [f":(literal){rel}" for rel in cands],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if ls.returncode != 0:
                # 逐路径版失败语义是「该路径跳过不 purge」；批量无法区分哪些候选
                # 在索引中，等价整体放弃（victims 留空），并按 diff 枚举失败同款
                # 口径（item a14b215ba4d4）记 warning 不静默吞掉。
                self.logger.warning(
                    "worktree_manager",
                    f"Purge ignored brought-in: tracked set enumeration failed: "
                    f"{(ls.stderr or ls.stdout).strip()}",
                )
                return
            tracked = {p for p in ls.stdout.split("\0") if p}
            cands = [rel for rel in cands if rel in tracked]
            if not cands:
                return
            # check-ignore 批量判定（单条 ``--stdin``，对照 mergeback
            # ._rehearsed_paths_all_ignored_du 的 2bde1727f26c 批量口径）：必须
            # 保留 --no-index——候选刚随 merge 进入索引，缺它则 tracked 路径永不
            # 判忽略；-z 下输入输出均 NUL 分隔（免路径歧义与 quotePath 转义），
            # 「出现在输出即被忽略」与逐路径 -q 退出码语义等价（! 否定规则的
            # 未命中路径同样不进输出）。
            chk = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "check-ignore",
                    "--no-index",
                    "-z",
                    "--stdin",
                ],
                input="\0".join(cands),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if chk.returncode not in (0, 1):
                # 0=有忽略命中、1=全部未命中均为有效裁决；其余退出码才是命令
                # 失败，无法判定哪些被忽略——同上整体放弃并记 warning。
                self.logger.warning(
                    "worktree_manager",
                    f"Purge ignored brought-in: ignore check failed: "
                    f"{(chk.stderr or chk.stdout).strip()}",
                )
                return
            ignored = {ln for ln in chk.stdout.split("\0") if ln}
            victims = [rel for rel in cands if rel in ignored]
            if not victims:
                return
            if self._untrack_index_paths(
                victims,
                "[fenix] fix: merge 后移出随分支带回的 ignored 运行时草稿",
                "Purge ignored brought-in",
            ):
                self.logger.info(
                    "worktree_manager",
                    f"Purged ignored drafts brought in by merge: {', '.join(victims)}",
                )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError) as e:
            self._reset_index_paths(victims)
            self.logger.warning("worktree_manager", f"Purge ignored brought-in failed: {e}")

    def _abort_pending_merge_best_effort(self) -> None:
        """就地尽力执行一次 ``git merge --abort``，自身异常一律吸收。

        供 _resolve_ignored_modify_delete_conflicts 各**已产生变更后**的失败
        出口共用（code-review item c5248bd14a6e）：rm / check-ignore / commit
        失败，或子进程 TimeoutExpired、OSError（含解码异常）中途抛出时，索引
        可能已滞留部分 DU 路径的 staged 删除、其余路径仍 UU、MERGE_HEAD 未消
        ——各变更后失败出口统一就地 abort，不把半合并态留给调用方兜底（口径
        同 code-review item af9f0b134011）；纯校验失败的早期 return（status
        采集失败、非 DU 冲突、无 DU 路径）不经此处，保持合并态原样交调用方
        采集冲突路径后统一 abort。abort 幂等，调用方兜底重复 abort
        无害；无挂起 merge 时 abort 以非 0 退出被静默忽略。abort 自身再失败
        （git 卡死/不可用）不掩盖原始失败原因，交调用方既有失败路径处置。
        """
        try:
            subprocess.run(
                ["git", "-C", str(self.project_root), "merge", "--abort"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
            pass

    def _resolve_ignored_modify_delete_conflicts(self) -> bool:
        """在 merge 冲突挂起状态下自愈 modify/delete 冲突（仅限被忽略的路径）。

        场景：run-result 类运行时草稿在移出版本控制前派生的旧分支上被改动，
        与主树侧的删除相撞（DU：主树删除、分支修改）。被忽略的草稿不是交付物，
        不应让 merge-back 死锁。

        步骤：存在 DU 冲突且**无其它类型冲突**时，先逐个 ``git rm -f --cached``
        采纳删除（工作区副本保留，供运行时继续使用）——此刻路径已 untracked，
        ``check-ignore`` 判定才可靠（unmerged 条目会被视为 tracked 而误报）；
        再校验全部路径确被 .gitignore 忽略。失败出口分两类：仅**已产生本函数
        自身变更（rm --cached 之后）**的出口——rm / check-ignore / commit
        失败或子进程超时、不可用——经 ``_abort_pending_merge_best_effort``
        就地 ``merge --abort``（code-review item c5248bd14a6e）回到调用方原有
        失败路径（分支内容仍可从分支提交找回，不丢数据；abort 幂等，调用方
        兜底重复 abort 无害）；纯校验失败的早期 return（status 采集失败、存在
        非 DU 的其它类型冲突、无 DU 路径）保持合并态原样交由调用方采集冲突
        路径后统一 abort——此处提前 abort 会让调用方的冲突分类采空。全部
        通过则 ``git commit --no-edit`` 完成 merge。

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
                encoding="utf-8",
                errors="replace",
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
                    # 反转义口径对齐 _list_dirty_tracked_files（code-review item
                    # b9381c0972e3）：quotePath=false 只豁免高位字节，路径含双引号/
                    # 反斜杠/控制字符时输出仍是 C-quote 转义形，直接拼入下方
                    # git rm --cached 与 check-ignore 的 pathspec 永不命中；
                    # unquote_git_path 对无引号行原样返回（幂等），保留
                    # quotePath=false 以减少转义面
                    du_paths.append(unquote_git_path(line[3:].strip()))
            if not du_paths:
                return False
            for path in du_paths:
                rm = subprocess.run(
                    ["git", "-C", str(self.project_root), "rm", "-f", "--cached", "--", path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if rm.returncode != 0:
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal: git rm --cached failed for '{path}': "
                        f"{(rm.stderr or rm.stdout).strip()}",
                    )
                    # 与下方 check-ignore 失败分支同口径就地 abort（code-review
                    # item af9f0b134011）：此刻索引已滞留部分 DU 路径的 staged
                    # 删除、其余路径仍 UU、MERGE_HEAD 未消，不能把半合并态留给
                    # 调用方兜底；abort 幂等，调用方重复 abort 无害。
                    self._abort_pending_merge_best_effort()
                    return False
            for path in du_paths:
                chk = subprocess.run(
                    ["git", "-C", str(self.project_root), "check-ignore", "-q", "--", path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if chk.returncode not in (0, 1):
                    # check-ignore 退出码 0=有忽略命中、1=全部未命中，其余为
                    # 命令 fatal（index.lock 争用、git 不可用等），忽略态不可
                    # 判定：按「check-ignore 命令失败」单独归因记日志，勿冒充
                    # 「路径未被忽略——非运行时草稿」把排障引向路径校验方向
                    # （对照 _untrack_index_paths 的 diff --cached 失败分支，
                    # code-review item 8af338d766c3 / 2d526a1254d6）。同口径
                    # 就地 abort：上方 rm 段可能已滞留部分 DU 路径的 staged
                    # 删除，不把半合并态留给调用方兜底。
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal aborted: git check-ignore failed for "
                        f"'{path}': {(chk.stderr or chk.stdout).strip()}",
                    )
                    self._abort_pending_merge_best_effort()
                    return False
                if chk.returncode == 1:
                    # 未被忽略 → 疑似真实交付物冲突，不自愈，交回 abort 路径
                    self.logger.warning(
                        "worktree_manager",
                        f"Self-heal aborted: conflicted path '{path}' is not "
                        f"gitignored — not a runtime draft",
                    )
                    self._abort_pending_merge_best_effort()
                    return False
            commit = subprocess.run(
                ["git", "-C", str(self.project_root), "commit", "--no-edit"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if commit.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Self-heal: merge commit failed: "
                    f"{(commit.stderr or commit.stdout).strip()}",
                )
                # 与上方 rm / check-ignore 失败分支同口径：此刻全部 DU 路径已
                # staged 删除、MERGE_HEAD 未消，commit 失败同样不把半合并态
                # 留给调用方兜底（code-review item c5248bd14a6e）。
                self._abort_pending_merge_best_effort()
                return False
            return True
        except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
            # TimeoutExpired / OSError（含解码异常）可能发生在 rm / check-ignore
            # 循环中途（git 卡死超时的场景恰易出现在这里）：与上方各失败分支
            # 同口径先尽力就地 abort，不把同类半合并态滞留给调用方
            # （code-review item c5248bd14a6e）。
            self._abort_pending_merge_best_effort()
            return False
