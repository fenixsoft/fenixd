## Deliverables

```yaml
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: tests/test_verify_parallel_override_reset.py
  kind: new
```

## 1. 写侧契约归位

- [ ] 1.1 core/dashboard/data/admin_actions.py：_RETRY_COUNTER_RESETS 中 _verify_parallel_override 由 False 改 None（:1573），与 unfreeze_spec 的 None 复位语义对齐；修正 :1560-1567 失实注释；核对消费点 reset_verification（:1758-1770）与 _exec_continue_auto_fix（:2014-2031）取值路径。

## 2. 解析侧归一与读端留痕

- [ ] 2.1 core/state_machine.py：parse 侧为 _verify_parallel_override 登记 int|None 归一（int 先例区 :538-558 / null 清单 :602-638），布尔与字符串形状写入前拒绝并告警或归 None；覆盖存量 STATE.md 首读清洗。
- [ ] 2.2 core/pm_engine/verification/pipeline.py：读端解析失败分支（:2108-2118）告警补 repr 值形状与字段来源；不做布尔→并行度映射。

## 3. 测试

- [ ] 3.1 tests/test_verify_parallel_override_reset.py（新建）：reset_verification/continue_auto_fix 后字段为 null 且 STATE.md 往返读回 null；'False'/'true' 等形状写入被拒/归 None；读端告警含 repr；既有 tests/test_verify_parallel_backoff.py 零回退。