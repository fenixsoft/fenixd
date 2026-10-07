## Deliverables

```yaml
- path: core/wip_checkpoint.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/QualityTab.tsx
  kind: modify
- path: tests/test_impl_wip_checkpoint.py
  kind: modify
- path: tests/test_run_cancel.py
  kind: modify
```

## 1. 取消路径现场保全

- [ ] 1.1 core/wip_checkpoint.py：锚点常量区新增 ANCHOR_CANCEL（"cancel"），沿用既有锚点体系
- [ ] 1.2 core/agent_runner/runner.py：取消旗标命中确认处（worktree 在手）调用既有 _wip_checkpoint_commit_safe 补 WIP checkpoint（锚点 cancel），失败仅 WARNING 降级、绝不阻断取消收口；attempt 间隙（无 worktree）跳过；RunCancelledError 收口分支兜底
- [ ] 1.3 core/agent_runner/runner.py：修正取消审计告警 recommended_action 文案——如实描述「失败 implementer worktree 将登记为 legacy 保留（宽限期后回收），未提交改动不进入分支提交」，替换与 register_legacy 语义不符的「将随 cleanup(success=False) 丢弃」

## 2. dashboard 取消确认

- [ ] 2.1 core/dashboard/static/src/pages/projects/components/QualityTab.tsx：「取消」按钮补确认弹窗（danger 标识，复用同文件 Modal.confirm 既有先例），确认后才调 cancelRun；错误处理沿用 ApiError.code 稳定错误码分支

## 3. 测试

- [ ] 3.1 tests/test_impl_wip_checkpoint.py：覆盖取消锚点 checkpoint 写入、失败 WARNING 降级不阻断取消收口、attempt 间隙跳过
- [ ] 3.2 tests/test_run_cancel.py：覆盖取消收口前已产 checkpoint 的集成用例与取消审计文案断言