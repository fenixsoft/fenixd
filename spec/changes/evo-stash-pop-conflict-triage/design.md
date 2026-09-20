# design: stash-pop-conflict-triage

## D1 三态重试

- 位置：core/worktree_manager/stash_guard.py pop 冲突分支。
- 态 1 merge：逐冲突文件尝试将 stash 版并入 merge 后工作区（不同 hunk 自动合并），可行则写回工作区；不可行进入态 2。
- 态 2 恢复 commit：将 stash 版内容落盘并以冲突标记（<<<<<<< / ======= / >>>>>>>）保留双方，git add + commit（message 含 spec 名与 stash sha）留审计，登记 disposition。
- 态 3 兜底：保留冲突标记文件 + 显式登记 disposition（与现状差异仅在「登记」显式化与日志结构化）。
- 信号：三态均保留 stash_pop_conflict 信号与 stash 条目保留语义（破坏性最小）。

## D2 可观测性

- 处置结果写结构化日志（文件清单 / 处置方式 / stash sha），供 stash_pop_conflict 信号 evidence 携带，dashboard 与自省可见。

## Non-Goals

- 不修改 WIP 重叠闸门 auto/block 策略与 stash 时机。
- 不改变 stash_pop_conflict 信号契约。
- Dashboard 表单键回归断言与 merge-back 前冲突提示另议（不在本 SPEC 范围）。