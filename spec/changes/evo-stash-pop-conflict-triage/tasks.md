# Tasks: stash-pop-conflict-triage

## Deliverables

```yaml
- path: core/worktree_manager/stash_guard.py
  kind: modify
- path: tests/test_stash_pop_conflict_triage.py
  kind: new
- path: tests/test_worktree_stray_and_identical.py
  kind: modify
- path: tests/test_worktree_merge_guard.py
  kind: modify
```

> 后两项为同变更内回归对齐（design R1）：本 SPEC 改写「UU 冲突文件以分支版落地」既有口径，
> 相关断言必须同步改为新口径，不得删断言或放宽判定。

## 1. stash pop 冲突三态重试

- [ ] 1.1 core/worktree_manager/stash_guard.py：pop 冲突分支（:178-215）改三态口径——态 1
      对每个 UU 文件做三方重试（ours=`HEAD:<f>`、base=`stash@{0}^1:<f>`、theirs=
      `stash@{0}:<f>`，`git merge-file`），无冲突写回工作区；态 1 失败 MUST NOT 视为异常，
      直接进态 2；任何路径都不得用 `checkout -f HEAD` 静默丢弃 stash 版
- [ ] 1.2 core/worktree_manager/stash_guard.py：态 2 逐文件以 `git checkout --theirs -- <path>`
      取回 stash 版内容落工作区（**MUST NOT** 依赖工作区冲突标记文本——二进制/非 UTF-8 文件
      pop 后工作区为 merge 结果、无标记），再 `git add -- <paths>` +
      `git commit --only -m "<spec 名> stash pop 恢复（stash <sha>）" -- <paths>`
      **只把本次冲突路径入库**（路径作用域：不改动其它路径内容，不吞并 index 中其余 staged
      条目——见 design D2）
- [ ] 1.3 core/worktree_manager/stash_guard.py：态 3 兜底——态 2 落盘或入库任一步失败时至少
      保证 stash 版内容落回工作区（双版本保留）并显式登记 disposition，绝不静默丢弃；
      stash 条目保留与 stash_pop_conflict 信号行为保持；`last_stash_entry_fate` 结构
      （lifecycle.py:97）与 `_drop_superseded_stash_entry` 判据不变
- [ ] 1.4 core/worktree_manager/stash_guard.py：冲突处置路径写结构化日志（文件清单/处置方式
      （态 1/2/3）/stash sha），供 stash_pop_conflict 信号 evidence 携带

## 2. 测试

- [ ] 2.1 tests/test_stash_pop_conflict_triage.py：纯文本同 hunk 冲突 → 态 2 恢复 commit 落盘，
      stash 版内容（如 `LOCAL\n`）在恢复提交中可见；stash 条目保留（`git stash list` 命中）；
      不出现「静默丢弃」
- [ ] 2.2 tests/test_stash_pop_conflict_triage.py：**二进制冲突**（如 `d.bin`）→ 态 2 经
      `--theirs` 取回 stash 版字节内容，恢复 commit 中该文件与 stash 版字节级一致（回归
      「读工作区标记失败」这一取证盲区）
- [ ] 2.3 tests/test_stash_pop_conflict_triage.py：**路径作用域**——调用前在 index 中预置另一个
      staged 修改（`git add -- other.ts`），态 2 恢复 commit 后该条目仍在 index、内容未被吞并，
      且主树 porcelain 非空属预期
- [ ] 2.4 tests/test_stash_pop_conflict_triage.py：兜底路径——态 2 的 `git commit` 注入失败
      （monkeypatch subprocess 返回非 0）时，stash 版内容仍在工作区且 disposition 已登记，
      无静默丢弃
- [ ] 2.5 tests/test_worktree_stray_and_identical.py：`test_divergent_copy_unblocks_via_stash_selfheal`
      （:229）与 `test_mixed_blockers_branch_wins_conflicted_file_recorded`（:254）改为新口径断言
      ——`last_stash_pop_conflicts` 仍为冲突文件清单，冲突文件在工作区含双方内容（stash 版
      `LOCAL\n` 可见），不再断言「分支版胜出」
- [ ] 2.6 tests/test_worktree_merge_guard.py：
      `TestDropSupersededStashEntry::test_restore_conflict_preserves_entry_and_logs_recover_cmd`
      改为「恢复 commit 路径」口径——条目保留与找回命令日志断言不变；工作区/HEAD 断言按态 2
      结果更新（冲突文件内容含双方、主树 porcelain 允许非空）；条目自动 drop 判定语义
      （零独有内容才 drop）不被破坏
