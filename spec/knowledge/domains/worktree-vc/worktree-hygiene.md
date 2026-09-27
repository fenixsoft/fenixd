<!-- knowledge: capability=worktree-hygiene rev=1 sources=spec/archive/2026-09-02-fix-fenix-token-waste -->

# worktree 卫生与复用

worktree 基础目录的启动期清扫：daemon 启动时清掉不属于本次会话活动集合的残留目录与分支，防止跨会话垃圾累积。

## 现行规则

- 启动清理孤儿 worktree：daemon 启动时扫描 worktree 基础目录，清理所有不属于本次会话活动集合的残留 worktree 目录与对应 git 分支，并执行 `git worktree prune`。
- 无残留不误删：worktree 基础目录为空或全部属于活动集合时，不删除任何目录，正常启动。
- 清理失败不阻塞启动：删除某个残留目录失败（如文件系统错误）时记录 WARNING，daemon 仍正常启动。

## 溯源

- 2026-09-02 fix-fenix-token-waste — 新增启动期孤儿 worktree 目录与对应分支清扫、`git worktree prune`，以及清理失败告警不阻塞 daemon 启动
