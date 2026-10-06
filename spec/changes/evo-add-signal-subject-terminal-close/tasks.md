## Deliverables

```yaml
- path: core/alert_lifecycle.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_alert_lifecycle.py
  kind: modify
- path: tests/test_stuck_signal_hygiene.py
  kind: modify
```

## 1. 判定端放宽 kind 门

- [ ] 1.1 core/alert_lifecycle.py：evaluate_alert（:328-329 附近）kind 门放宽——kind=signal 且其 trigger/登记条件属 spec 附着条件族（CONDITION_SPEC_TERMINAL_OR_UNBLOCKED 等）时，走既有主体终态判定（specs 状态表已入参），主体已终态或离开受阻态即判可收口；签名安静族（SELF_HEAL_SIGNAL_TYPES）语义不动。

## 2. 盘点通道与写回端

- [ ] 2.1 core/admin_monitor.py：_run_alert_lifecycle（L2213）通道一 pending 过滤（L2243）纳入未 handled 且属 spec 附着族的 kind=signal 记录（或新增并列通道），交判定端复用同一终态判定。
- [ ] 2.2 core/admin_store.py：写回端 auto_resolve（L680/:697）kind 门放宽到 escalation+signal（或比照 auto_self_heal L715 新增 signal 写回），handled_by 沿用既有 AUTO_RESOLVE_BY，收口注记附主体终态时刻。

## 3. 测试

- [ ] 3.1 tests/test_alert_lifecycle.py：kind=signal 且 spec 已 pushed/done → 可收口；spec 仍 blocked → 不收口；签名安静族与 kind=escalation 既有行为不回归。
- [ ] 3.2 tests/test_stuck_signal_hygiene.py：blocked_stuck 主体终态收口回归——spec 转 pushed 后下轮盘点标记 handled 并附终态时刻；_detect_stuck 既有三块（进程存活反证/status_hash 去重/处置后静默期）不回归。