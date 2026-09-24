## Deliverables

```yaml
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: tests/test_dual_dispatch_and_freeze.py
  kind: modify
```

## 1. worktree 创建重名换名重试

- [ ] 1.1 core/worktree_manager/lifecycle.py：create 的 worktree add -b 失败分支识别 stderr 含 already exists——以 timestamp 取 max(int(time.time()), 原值+1) 同步重建分支名与 worktree 路径就地重试，有界 2-3 次；非重名失败不重试
- [ ] 1.2 core/worktree_manager/lifecycle.py：换名重试全程持有创建锁并落含新旧分支名的 WARNING；重试耗尽仍失败时沿用 discard 锁、return None 现状语义，分支名末段保持纯数字

## 2. 测试

- [ ] 2.1 tests/test_dual_dispatch_and_freeze.py：新增跨 agent_type（implementer 与 planner-plan）同秒 create 用例——mock subprocess 使首个 worktree add -b 成功、次个返回 already exists，断言换名重试成功、新分支名末段纯数字、创建锁不泄漏、未触发 runner 层 sleep(5) 重试
