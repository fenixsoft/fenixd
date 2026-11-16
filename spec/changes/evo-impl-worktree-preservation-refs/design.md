# Design: impl-worktree-preservation-refs

## Context

现状：core/worktree_manager/lifecycle.py:1170 `_snapshot_dirty_worktree` 以 `git stash create` 生成快照 commit（不入栈、无引用），:1298-1305 打 WARNING 附「git stash store」人工指引；分支删除在 lifecycle.py:839-1012 与 stale_sweep.py:369-636。8/8 历史快照零转正，run4（client-ui-redesign）交付现零引用可达。

## Goals / Non-Goals

- Goals：快照 GC 可达（真引用）；指引可执行；引用按终态清理不悬挂。
- Non-Goals：不改 fast-track 冻结保全（在途 fix-fasttrack-freeze-branch-preservation 范围）；不改 worktree 清扫的触发条件与节奏；不做自动合回。

## Design

1. **快照写引用（lifecycle.py `_snapshot_dirty_worktree`）**：保留 stash create 产快照 commit 的方式，其后立即 `git update-ref refs/preservation/<run_id> <snapshot_sha>`（run_id 取 worktree 所属 run 标识）；WARNING 文案改为引用名指引。update-ref 失败时回退现状行为并升 WARNING 为 ERROR。
2. **引用命名空间**：refs/preservation/<run_id>，主 gitdir 共享，天然 GC 可达；不与 refs/stash、refs/heads 冲突。
3. **清理路径（stale_sweep.py）**：清扫在删除终态 impl 分支前校验 preservation 引用就位；spec 终态消费（merge-back 决策留痕）后的宽限期清扫删除对应引用。冻结在途（STATE 冻结条目存在）时跳过删除。
4. **可观测**：清扫日志引用 preservation 引用名，替代现指引；对既有 8 处历史悬空快照不追溯（fsck 期间对象仍在，人工可按需转正）。

## Risks / Trade-offs

- 引用堆积：由终态清理路径兜底；异常残留引用可在清扫时按 mtime/终态对账清理。
- run_id 冲突：run_id 含时间戳唯一；重扫时 update-ref 幂等覆盖。

## Migration

无数据迁移；新快照即写引用；历史悬空对象在 GC 窗口内仍可人工转正，不做自动追溯。