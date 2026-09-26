## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_worktree_acquire_backoff.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/agent_runner/runner.py：_prepare_worktree 把「sleep(5) 一次即放弃」改为短退避循环（30s/60s/120s）——worktree_manager.create 返回 None 且原因为同 spec:agent_type 锁活跃时等待重试，重试耗尽才返回既有 gave up 错误；锁释放后立即取得
- [ ] 1.2 core/agent_runner/runner.py：让路原因区分——frozen、_cancelled_hold、status 迁出预期态保持立即放弃不进退避（人工接管语义不可自动穿越），可在 _prepare_worktree 分探针实现、不改 _should_give_up_before_retry 既有语义
- [ ] 1.3 core/pm_engine/engine.py：新验证流程降级分支（2418-2424 附近）加累计计数器，WARNING 附「第 N 次降级」

## 2. 测试

- [ ] 2.1 tests/test_worktree_acquire_backoff.py：覆盖四类场景——退避期内锁释放后取得 worktree、重试耗尽仍锁活跃返回 gave up、frozen 立即让位不等待、降级 WARNING 计数递增
- [ ] 2.2 回归既有 worktree 命名冲突换名重试与验证管线测试，确认「already exists」签名与 full 车道行为不变