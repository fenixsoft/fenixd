# merge-back 能力规格：stash-pop-conflict-triage

## 概述

merge-back 自愈链中「stash pop 冲突」的处置从「丢弃 stash 版」升级为三态重试
（双版本落盘 → 路径作用域恢复 commit → 兜底保留登记），保证主树未提交改动永不因自愈
静默丢失。

## 现状与缺口

- `git stash pop` 本身是三方合并：非冲突文件与**无冲突 hunk 已自动落回工作区**（实测复现，
  见 design D0）；真正丢失的是 **UU 冲突文件**的 stash 版——现 `_heal_unmerged_files`
  （core/worktree_manager/dist_conflicts.py:473）对每个 UU 文件执行 `checkout -f HEAD -- <f>`，
  用 merge 结果覆盖工作区、丢弃 stash 侧内容（stash_guard.py:181 调用）；
- 交付物丢失后依赖 admin 手工找回（978f9f65 实证），窗口内同类 4+ 起。

## 规格

### 三态重试

对每个 UU 冲突文件按序尝试：

1. 态 1 双版本落盘：三方重试（ours = 已合入 HEAD 版，base = `stash@{0}^1` 版，theirs =
   `stash@{0}` 版），无冲突则写回工作区（两侧改动都保留）；失败（含纯文本同 hunk 冲突）
   **MUST NOT** 视为异常，直接进态 2；
2. 态 2 恢复 commit（路径作用域 MUST）：逐文件 `git checkout --theirs -- <path>` 取回 stash 版
   内容落工作区（**MUST NOT** 依赖工作区冲突标记文本——二进制/非 UTF-8 文件 pop 后工作区为
   merge 结果、无标记），再 `git add -- <paths>` + `git commit --only -- <paths>` **只把本次冲突
   路径**入库（保留 index 中其余 staged 条目、不改动其它路径内容）；
3. 态 3 兜底：态 2 落盘或入库任一步失败时，至少保证 stash 版内容落回工作区并显式登记
   disposition。

- 任一态不得静默丢弃 stash 内容；stash 条目保留、stash_pop_conflict 信号与唤起 admin 行为保持；
- `last_stash_entry_fate` 结构与 `_drop_superseded_stash_entry` 判据不变。

### 可观测性

- 冲突处置路径写结构化日志（文件清单 / 处置方式（态 1/2/3） / stash sha），dashboard 与
  自省可见。

## 边界

- 不改变 WIP 重叠闸门 auto/block 策略与 stash 时机；
- 不改变 stash_pop_conflict 信号契约与 dispatch 层告警文案生成；
- 既有「冲突文件以分支版落地 / pop 后主树干净」断言（tests/test_worktree_stray_and_identical.py、
  tests/test_worktree_merge_guard.py）属本 SPEC 改写口径的回归面，须在同变更内同步更新
  （见 design R1）。
