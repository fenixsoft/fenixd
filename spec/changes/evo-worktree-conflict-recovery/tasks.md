# 任务

## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: tests/test_worktree_recovery.py
  kind: new
```

## 1. worktree 锁记录磁盘化（run_id/pid/created_at）

- [ ] 1.1 core/worktree_manager.py：_spec_locks 增加磁盘 sidecar 持久化；锁获取时写入 run_id/pid/created_at，释放时清除。

## 2. 锁归属诊断与残留清理重试

- [ ] 2.1 core/worktree_manager.py：创建失败时按 pid/转录存在性判定活动 vs 残留；残留则 git worktree remove 后重试一次；写单元测试覆盖「残留自动清理重试」「活动 run 不重试」。

## 3. 降级诊断化（reason 字段 + WARNING 日志）

- [ ] 3.1 core/pm_engine/verification.py：降级分支统一携带 reason（parallel-run/stale-recovery-failed/env-failure），WARNING 级别输出；dashboard 展示原因。

## 4. 回归测试（冲突→恢复路径）

- [ ] 4.1 tests/test_worktree_recovery.py：重放 add-web-ui 08:46 冲突场景：残留锁可清理重试不降级；活动锁降级带 reason。
