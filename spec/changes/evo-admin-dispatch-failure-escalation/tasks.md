## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_agent_prompt_files.py
  kind: modify
- path: tests/test_admin_dispatch_escalation.py
  kind: new
```

## 1. 派发失败专用升级

- [ ] 1.1 core/admin_monitor.py：_invoke_administrator except 分流——编程错误（TypeError/AttributeError/NameError/ValueError）→ signal_type=admin_dispatch_programming_error critical 记录（evidence 含异常类型/消息/traceback 最深处调用点/原信号）；写入前 unhandled_for(spec, admin_dispatch_programming_error) 去重（同 _escalate_reset_programming_error 模式，重试失败改 bump 既有记录）；其余异常维持原 signal_type 升级记录（同样带 next_retry_at，参与重试）。ValueError 子类（JSONDecodeError/UnicodeDecodeError 等数据类异常）会被归为编程错误——保守可见方向，evidence 保留完整异常消息供甄别
- [ ] 1.2 SIGNAL_SEVERITY / SIGNAL_RECOMMENDATION 登记 admin_dispatch_programming_error（critical；代码缺陷须工程侧定位，勿派子 fix 重跑）
- [ ] 1.3 重试语义：两条分流路径升级记录均带 next_retry_at（now + escalation_cooldown_minutes）与 retry_count=0；新增 _retry_due_dispatch_failures() 挂 run_once（_force_escalate_stalled 后、_run_alert_lifecycle 前），扫描到期未处理记录直接调 _invoke_administrator（带 _dispatch_retry_id 重建原信号），MUST NOT 经 _handle_signal（节流吞重试）、frozen spec 跳过；仍失败 bump 既有记录 retry_count（上限 1）不追加；manual 派发（signal_rec=None）不重试；重试或后续派发成功 → 标记该 spec 派发失败升级记录 handled（resolve_note=「后续派发成功」），不扩 alert_lifecycle 闭环枚举

## 2. 序列化防回退（版本化）

- [ ] 2.1 core/agent_runner/prompt_builder.py：确认 {evidence}/{recommendation} 统一走 _str_field（现有工作树改动，纳入提交）
- [ ] 2.2 tests/test_agent_prompt_files.py：evidence dict → 提示词正常构建、不抛 replace 错误（现有单测纳入 + 补派发链用例）

## 3. 测试

- [ ] 3.1 tests/test_admin_dispatch_escalation.py：TypeError 注入 → 恰好 1 条 admin_dispatch_programming_error critical 升级记录（含异常类型/调用点）；OSError 注入 → 不归类编程错误
- [ ] 3.2 冷却后重试一次（节流不吞、frozen 跳过）；仍失败 retry_count=1 保持升级；恢复后重试/后续派发成功 → 既有升级记录被闭环（handled，resolve_note=「后续派发成功」），无残留 critical
- [ ] 3.3 回放 2026-09-14 stash_pop_conflict dict evidence → 专用升级记录（admin_dispatch_programming_error critical，含异常类型/调用点）；admin 活动视图按 signal_type 标签可归类查看（core/dashboard/data.py:3256 已导出 signal_type，activities/index.tsx:148 signalTag 渲染）