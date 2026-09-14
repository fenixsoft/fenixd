# worktree 冲突恢复（worktree-conflict-recovery）

## 需求

### R1 锁归属诊断
- worktree 创建失败（lock 已存在）时，判定锁持有人状态：
  - 活跃 run（pid 存活且有对应 run 转录）→ 并发冲突，标记 downgrade reason=parallel-run；
  - 残留（run 已结束 / run_id 无对应转录 / daemon 重启后内存锁丢失但目录残留）→ 标记 stale，走 R2。
- worktree 活跃记录持久化 run_id、pid、created_at，供诊断读取。

### R2 残留清理重试
- 判定为残留时，安全清理（git worktree remove --force 或等价）后重试创建一次。
- 重试仍失败才允许降级，且降级日志附原因。

### R3 降级诊断化
- 降级到 legacy verifier 的日志升级为 WARNING 并携带 reason 字段（parallel-run | stale-recovery-failed | env-failure），dashboard 可见。

## 验收标准
- 残留冲突 → 自动清理 + 重试成功（不留降级）。
- 活动 run 冲突 → 降级日志含 reason=parallel-run 与活跃 run id。
- 单测覆盖锁归属判定与清理重试。