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
- path: fenixd.py
  kind: modify
- path: tests/test_unfreeze_retry_counter_reset.py
  kind: new
```

## 1. 清零集补键

- [x] 1.1 core/state_machine.py：unfreeze_spec（:2761 起，updates 清零集）补 _retry_count 置 0，解冻后首轮失败计数从 1 起算
- [x] 1.2 core/dashboard/data/admin_actions.py：_RETRY_COUNTER_RESETS（:1745 注释块起）补 _retry_count: 0（对齐 :926/:1021 同键复位先例）

## 2. 冻结文案与人工重推记账

- [x] 2.1 core/pm_engine/dispatch/queue.py 与 core/pm_engine/dispatch/fast_track.py：冻结文案硬编码点共 5 处（queue.py:2744/3381、fast_track.py:1348/1591/2542，权威定位 grep `{max_r}/{max_r}`，各站点 retries 变量已在手）中的已试次数改取真实计数器值，越限形态如实显示并注明
- [x] 2.2 core/pm_engine/engine.py：approve_push（:3752）人工重推计入 push 重试计数时标注 manual 来源——approve_push 有两条入口链（自动：engine.py:4306 `_auto_approve`；人工：dashboard `request_spec_approve_push` 文件信号，信号体已带 `source: "dashboard"` 字段），以 source 参数透传区分（自动链标 auto、信号链标 manual）；计数达上限后同 spec 重复 push_failed 信号去重，不重复触发 daemon_errors 升级

## 3. 测试

- [x] 3.1 tests/test_unfreeze_retry_counter_reset.py：覆盖「3/3 冻结→解冻→首轮失败计数 1/3 不冻结」「两处复位键集合含 _retry_count」「越限冻结文案计数与日志一致」「人工重推达上限后信号去重」四场景