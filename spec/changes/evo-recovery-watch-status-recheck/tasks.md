# Tasks: recovery-watch-status-recheck

## Deliverables

```yaml
- path: core/pm_engine/recovery.py
  kind: modify
- path: tests/test_recovery_watch_status_recheck.py
  kind: new
```

## 1. 升级前 status 复查

- [ ] 1.1 core/pm_engine/recovery.py：dispatch_stalled 升级前（约 218 行）二次复查 read_one 当前 status——已偏离（blocked/implementing/testing 等非 ready 态）即顺延本次判定（保留观察项、推进 due），不升级
- [ ] 1.2 顺延对齐 transition_defer 范式：复用 _transition_defer_due 机制，避免「顺延后仍卡死再升级」无限循环
- [ ] 1.3 恢复推进判定补 blocked：blocked（有独立 blocked_stuck 通道）纳入 passed 判定，不重复升级 dispatch_stalled
- [ ] 1.4 二次复查读失败/异常 → 保守升级（不因本机制漏报真滞留）

## 2. 测试

- [ ] 2.1 tests/test_recovery_watch_status_recheck.py：复查时已 blocked → 不升级 dispatch_stalled（复现 16:33 事故）
- [ ] 2.2 复查时已 implementing → 顺延不升级
- [ ] 2.3 确为 ready 滞留 → 仍升级（回归 3fad3350 语义）
- [ ] 2.4 二次复查读失败 → 保守升级