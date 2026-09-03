# worktree-hygiene Spec

## ADDED Requirements

### Requirement: 启动清理孤儿 worktree
Fenixd SHALL 在启动时扫描 worktree 基础目录，清理所有不属于本次会话活动集合的残留 worktree 目录与对应 git 分支，并执行 `git worktree prune`。清理失败 SHALL 记录 WARNING 但不阻塞 daemon 启动。

#### Scenario: 启动清理残留 worktree
- **WHEN** daemon 启动且 worktree 基础目录存在不属于活动集合的残留目录
- **THEN** 残留目录被删除、对应分支被删除、`git worktree prune` 执行

#### Scenario: 无残留时不误删
- **WHEN** worktree 基础目录为空或全部属于活动集合
- **THEN** 不删除任何目录，正常启动

#### Scenario: 清理失败不阻塞启动
- **WHEN** 删除某个残留目录失败（如文件系统错误）
- **THEN** Fenixd 记录 WARNING，daemon 仍正常启动
