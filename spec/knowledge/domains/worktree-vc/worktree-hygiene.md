<!-- knowledge: capability=worktree-hygiene rev=2 sources=spec/archive/2026-09-02-fix-fenix-token-waste,spec/changes/fix-fasttrack-freeze-branch-preservation -->

# worktree 卫生与复用

worktree 基础目录的启动期清扫：daemon 启动时清掉不属于本次会话活动集合的残留目录与分支，防止跨会话垃圾累积。

## 现行规则

- 启动清理孤儿 worktree：daemon 启动时扫描 worktree 基础目录，清理所有不属于本次会话活动集合的残留 worktree 目录与对应 git 分支，并执行 `git worktree prune`。
- 无残留不误删：worktree 基础目录为空或全部属于活动集合时，不删除任何目录，正常启动。
- 清理失败不阻塞启动：删除某个残留目录失败（如文件系统错误）时记录 WARNING，daemon 仍正常启动。
- 冻结保全现场豁免（fix-fasttrack-freeze-branch-preservation R3）：STATE 在册 `frozen=True` 且 `_frozen_hold: True` 的 spec，孤儿清扫对其目录整目录跳过（worktree remove 与分支处置一并保留，WARNING 留痕）；legacy 宽限期兜底回收（`_reclaim_expired_legacy` → `_physically_reclaim_legacy` 的无保护 `branch -D`，single-app 事故实际删除者）在出册（pop）**前**同样查守卫——命中跳过且记录保持在册（出册后跳过=记录永久丢失、目录失去豁免反被孤儿清扫拾取）。豁免随人工解冻清 `_frozen_hold` 自然解除。

## 溯源

- 2026-09-02 fix-fenix-token-waste（spec/archive/2026-09-02-fix-fenix-token-waste） — 新增启动期孤儿 worktree 目录与对应分支清扫、`git worktree prune`，以及清理失败告警不阻塞 daemon 启动
- 2026-11-09 fix-fasttrack-freeze-branch-preservation（spec/changes/fix-fasttrack-freeze-branch-preservation） — 新增冻结保全现场守卫：孤儿清扫目录级豁免 + legacy 兜底回收出册前豁免，STATE 单次快照零新增锁序；守卫正匹配（STATE 不可解析不触发豁免，分支侧另有 `_branch_protected_by_state` 保守保留兜底）
