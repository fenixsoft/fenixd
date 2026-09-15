## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_agent_prompt_files.py
  kind: modify
- path: tests/test_admin_dispatch_escalation.py
  kind: new
```

## 1. 派发失败专用升级

- [ ] 1.1 core/admin_monitor.py：_invoke_administrator except 分流——编程错误（TypeError/AttributeError/NameError/ValueError）→ signal_type=admin_dispatch_programming_error critical 记录（evidence 含异常类型/消息/traceback 最深处调用点/原信号），其余异常维持原行为
- [ ] 1.2 SIGNAL_SEVERITY / SIGNAL_RECOMMENDATION 登记 admin_dispatch_programming_error（critical；代码缺陷须工程侧定位，勿派子 fix 重跑）
- [ ] 1.3 重试语义：升级记录带 next_retry_at，到期重试一次原信号；仍失败保持升级（retry_count 上限 1）

## 2. 序列化防回退（版本化）

- [ ] 2.1 core/agent_runner/prompt_builder.py：确认 {evidence}/{recommendation} 统一走 _str_field（现有工作树改动，纳入提交）
- [ ] 2.2 tests/test_agent_prompt_files.py：evidence dict → 提示词正常构建、不抛 replace 错误（现有单测纳入 + 补派发链用例）

## 3. 测试

- [ ] 3.1 tests/test_admin_dispatch_escalation.py：TypeError 注入 → 恰好 1 条 admin_dispatch_programming_error critical 升级记录（含异常类型/调用点）；OSError 注入 → 不归类编程错误
- [ ] 3.2 冷却后重试一次、仍失败保持升级；恢复后原信号正常派发
- [ ] 3.3 回放 2026-09-14 stash_pop_conflict dict evidence → 专用升级记录 + 归类统计可查