## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: tests/test_stale_code_selfheal.py
  kind: modify
```

## 1. stale_code 告警窗口去重

- [ ] 1.1 fenixd.py：_update_stale_code_state 告警写入块前置 AdminStore.latest_signal(None, "stale_code", 60) 判定——60 分钟窗口内已有同信号记录则跳过写入降级为日志；窗口常量取模块级常量风格（对齐 admin_monitor 的 DAEMON_ERROR_RESTART_COOLDOWN_MINUTES），不新增配置面
- [ ] 1.2 fenixd.py：保持假→真边沿触发与写入即 mark_handled 语义不变，超窗新周期照常成条

## 2. 测试

- [ ] 2.1 tests/test_stale_code_selfheal.py：新增窗口去重用例——存储已有 60 分钟内 stale_code 记录时再次检测命中不新增条目、超窗或空存储时照常写入（既有首报断言保持通过）
