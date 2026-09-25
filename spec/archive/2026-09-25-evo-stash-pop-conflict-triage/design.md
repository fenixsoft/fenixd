# design: stash-pop-conflict-triage

## D0 现状口径（实测，2026-09-21 复现）

`git stash pop` 本身就是一次三方合并（base = stash 父提交、ours = 当前 HEAD 工作区、
theirs = stash 版）：

- 非冲突文件与**无冲突 hunk 已自动落回工作区**（复现：主树 `g.ts` 独有改动在 pop 后
  取回 stash 版并进 index，`f.ts` 两侧同 hunk 改则 `UU`）；
- 真正丢失的是 **UU 冲突文件的 stash 版**：现 `_heal_unmerged_files`
  （core/worktree_manager/dist_conflicts.py:473）对每个 UU 文件执行
  `git checkout -f HEAD -- <f>`，即用 merge 结果覆盖工作区、丢弃 stash 侧内容
  （stash_guard.py:181 调用）。

因此本 SPEC 的修复面是「UU 冲突文件的处置」，不是「pop 完全不合并」。

## D1 三态重试

- 位置：core/worktree_manager/stash_guard.py `restore_after_merge` 的 pop 冲突分支
  （stash_guard.py:178-215）。自愈口径由「`checkout -f HEAD` 覆盖」改为下述三态。
- 态 1 双版本落盘：对每个 UU 冲突文件做三方重试（ours = 已合入 HEAD 版，base =
  `stash@{0}^1` 版，theirs = `stash@{0}` 版，`git merge-file`），无冲突则写回工作区
  （两侧改动都保留）；不可行进入态 2。
  **实测注记**：pop 已做过同样的三方合并，纯文本两侧同 hunk 改时态 1 与现状结果相同
  （仍留标记）。态 1 的收益在「pop 因索引/二进制/CRLF 等边缘原因未自动合并」的场景，
  故态 1 失败 **MUST NOT** 视为异常，直接进态 2。
- 态 2 恢复 commit（路径作用域，MUST）：
  1. 把 stash 版内容落到工作区——**逐文件从 stash 条目的 stage 3 取回**
     （`git checkout --theirs -- <path>`），**MUST NOT** 读工作区的冲突标记：二进制／
     非 UTF-8 文件 pop 时工作区被 merge 结果整体覆盖、根本无标记（复现：`d.bin` pop 后
     `cat -v` = `BRANCH1^@SEG^@TAIL`；`git checkout --theirs -- d.bin` 可原样取回
     `LOCAL1^@SEG^@TAIL`）；
  2. **只把本次冲突路径**入库：`git add -- <paths>` +
     `git commit --only -m "<spec 名> stash pop 恢复（stash <sha>）" -- <paths>`
     （实测 `--only -- <paths>` 保留 index 中其余 staged 条目不变）。
- 态 3 兜底：态 2 的落盘/入库任一步失败（写盘失败、commit 失败、磁盘满等）时，**至少**
  保证 stash 版内容落回工作区（冲突标记或双版本形式保留两侧），并显式登记 disposition；
  条目保留、信号照发。**绝不静默丢弃**。
- 信号：三态均保留 stash_pop_conflict 信号与 stash 条目保留语义。

## D2 路径作用域不变量（MUST）

`merge_back_from_branch` 在 `_main_tree_lock` 内调用 `restore_after_merge()`
（mergeback.py:103-111），返回后才释放锁，且主树工作区随后被要求「干净可写」
（`git status --porcelain` 检查）。因此三态的写盘与入库 **MUST** 限定在本次
`conflict_files`（`_list_unmerged_files()` 口径）内：其它路径的文件内容与 index 条目
一律不动；`git reset` 兜底仅在无 UU 残留后执行（与现状一致）。

## D3 条目去向与告警语义

- 「入恢复 commit」与「条目保留」并存时按**条目仍保留**记账，不改
  `last_stash_entry_fate`（lifecycle.py:97）结构；`_drop_superseded_stash_entry`
  （stash_guard.py:217）的「零独有内容才 drop、sha 仍在栈顶才 drop」判据保持不变。
- 告警文案由 dispatch 层（core/pm_engine/dispatch/rollback.py:192
  `_report_stash_pop_conflict`）按 `last_stash_entry_fate` 生成，随去向自动变化，
  **不在本 SPEC 改动范围内**。

## D4 可观测性

- 处置结果写结构化日志（文件清单 / 处置方式（态 1/2/3）/ stash sha），供
  stash_pop_conflict 信号 evidence 携带，dashboard 与自省可见。

## R1 回归面（既有断言须同变更内同步更新）

本 SPEC 改写既有「冲突文件以分支版落地」口径，下列既有断言会变红——**MUST** 在同一
变更内改为新口径断言（而非放宽或删除）：

- `tests/test_worktree_stray_and_identical.py:229` / `:254`：断言冲突文件
  `== "NEW\n" / "BRANCH\n"`（分支版胜出）且 `last_stash_pop_conflicts == [...]`；
- `tests/test_worktree_merge_guard.py` 的
  `TestDropSupersededStashEntry::test_restore_conflict_preserves_entry_and_logs_recover_cmd`：
  断言冲突文件 `== "MERGED\n"` 且主树 porcelain 为空（态 2 恢复 commit 会同时命中
  「标记文本比对」与「工作区干净」两条）；
- `tests/test_reclaim_stale_autostash.py` 的
  `TestReclaimStaleAutostash::test_conflicted_reclaim_drops_entry_after_heal`：冲突条目
  drop 的前置条件「主树干净」在态 2 下仍成立（恢复 commit 后工作区干净），预期无需改；
  若实现改动该判定，**MUST** 同步该测试。

## Non-Goals

- 不修改 WIP 重叠闸门 auto/block 策略与 stash 时机。
- 不改变 stash_pop_conflict 信号契约与 dispatch 层告警文案生成。
- Dashboard 表单键回归断言与 merge-back 前冲突提示另议（不在本 SPEC 范围）。
