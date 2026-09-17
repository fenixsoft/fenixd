## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_admin.py
  kind: modify
```

## 1. 落地校验

- [ ] 1.1 core/admin_monitor.py：_RUN_PREFIXES 从真源 core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES 导入或补全 repair-，_spec_from_run_id 对 repair- 前缀正确还原 spec 名
- [ ] 1.2 core/admin_monitor.py：_has_recent_spec_run 覆盖 repair- 前缀 run 文件活跃度（mtime 在 ORPHANED_RUN_GRACE_SECONDS 内即非孤儿），spec_is_undriven 三条件①不再对 repair 活跃期恒真
- [ ] 1.3 core/agent_runner/runner.py：run_administrator 非零退出时错误上下文补 CLI stderr 摘录（截断）+ 退出码 + run 末 3 事件时间戳，供告警与日志定位
- [ ] 1.4 core/admin_monitor.py：告警 description/注释区分 orphaned_state 的 signal / disposition pending / disposition failed 生命周期阶段，确认窗口查重覆盖同信号重复

## 2. 测试

- [ ] 2.1 tests/test_admin.py：新增用例——repair- 前缀 run 活跃时 spec_is_undriven 返回 False（误报回归）；不活跃时仍 True
- [ ] 2.2 tests/test_admin.py：新增用例——_spec_from_run_id 覆盖 repair-/impl-/verify-/planner-plan-/planner-judge-/spec-review-/admin- 全前缀
- [ ] 2.3 tests/test_agent_runner.py：新增用例——run_administrator 退出非 0 时 error 含 stderr 摘录与退出码