## Deliverables

```yaml
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: tests/test_dual_dispatch_and_freeze.py
  kind: modify
```

## 1. worktree 创建重名换名重试

- [x] 1.1 core/worktree_manager/lifecycle.py：create 的 worktree add -b 失败分支识别 stderr 含 already exists——以 timestamp 取 max(int(time.time()), 原值+1) 同步重建分支名与 worktree 路径就地重试，换名重试至多 2 次（总计至多 3 次创建尝试）；非重名失败不重试
- [x] 1.2 core/worktree_manager/lifecycle.py：换名重试全程持有创建锁并落含新旧分支名的 WARNING；重试耗尽仍失败时沿用 discard 锁、return None 现状语义，分支名末段保持纯数字

## 2. 测试

- [x] 2.1 tests/test_dual_dispatch_and_freeze.py：新增跨 agent_type（implementer 与 planner-plan）同秒 create 用例——按既有风格冻结时间戳使两车道同名（或 mock subprocess 使首个 worktree add -b 返回 already exists），断言后到者换名重试成功、新分支名末段纯数字、创建锁不泄漏；即 create 单次调用内自愈成功（返回非 None），无需调用方 sleep(5) 后重试
- [x] 2.2 tests/test_dual_dispatch_and_freeze.py：改写既有 test_failed_create_releases_own_lock（:123-143）——其「冻结时间戳 + 预建同名分支」正是换名重试的目标场景，实现后首次 create 会换名成功返回非 None，原 assertIsNone / 锁已释放断言必翻转。改法：预建 T、T+1、T+2 三个同名分支使重试耗尽，断言返回 None 且释放自己的锁；随后退出时间冻结再 create 一次，断言以真实新时间戳恢复成功（保留原「失败释放锁、重试可用」语义）
