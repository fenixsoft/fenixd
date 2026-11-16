## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/dispatch/fast_track.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_unfreeze_retry_counter_reset.py
  kind: new
```

## 1. 清零集补键

- [ ] 1.1 core/state_machine.py：unfreeze_spec（约 :2543-2790）清零集补 _retry_count 置 0，解冻后首轮失败计数从 1 起算
- [ ] 1.2 core/dashboard/data/admin_actions.py：_RETRY_COUNTER_RESETS（约 :1745-1781）补 _retry_count: 0（对齐 :935/:1025 同键复位先例）

## 2. 冻结文案与人工重推记账

- [ ] 2.1 core/pm_engine/dispatch/queue.py 与 core/pm_engine/dispatch/fast_track.py：冻结文案（约 queue.py:2600/3150、fast_track.py:1291/2385）中的已试次数改取真实计数器值，越限形态如实显示并注明
- [ ] 2.2 core/pm_engine/engine.py：approve_push（约 :3387）人工重推计入 push 重试计数时标注 manual 来源；计数达上限后同 spec 重复 push_failed 信号去重，不重复触发 daemon_errors 升级

## 3. 测试

- [ ] 3.1 tests/test_unfreeze_retry_counter_reset.py：覆盖「3/3 冻结→解冻→首轮失败计数 1/3 不冻结」「两处复位键集合含 _retry_count」「越限冻结文案计数与日志一致」「人工重推达上限后信号去重」四场景