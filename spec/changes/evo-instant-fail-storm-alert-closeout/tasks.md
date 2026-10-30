## Deliverables

```yaml
- path: core/alert_lifecycle.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: tests/test_alert_lifecycle.py
  kind: modify
```

## 1. 注册表登记与写入点埋点

- [ ] 1.1 core/alert_lifecycle.py：_SIGNAL_CONDITIONS（:112-125）登记 instant_fail_storm→CONDITION_SPEC_DELIVERED_ADJUDICATED（terminal-only：仅 pushed/done/archived 收口），:394-412 收口注记按 signal_type 中性泛化
- [ ] 1.2 core/agent_runner/runner.py：_alert_instant_fail_storm（:8394-8413）写入点对 entry 调 attach_trigger（:144-154）埋点
- [ ] 1.3 core/alert_lifecycle.py：存量无 trigger 悬置告警（87f72c680499）的一次性收口路径（backfill 映射或人工 handled，留痕），不误伤在途合理待处理 escalation

## 2. 龄期盘点与死亡取证

- [ ] 2.1 core/self_review.py：每日未处理 escalation 明细（:2200-2236）加登记龄期计算，超 24 小时未处理标注提醒（与 admin_monitor 节流兼容、同日幂等）
- [ ] 2.2 core/agent_runner/runner.py：_record_instant_fail（:8320-8376）秒挂死亡路径留存子进程启动 stderr 尾部与 worktree 状态快照（有界）

## 3. 测试

- [ ] 3.1 tests/test_alert_lifecycle.py：instant_fail_storm 告警在 spec pushed/done 后自动 resolved（留痕不删）、冷却中非终态不提前收口（负例回归锚）、存量无 trigger 条目按所选路径收口且不误伤在途条目