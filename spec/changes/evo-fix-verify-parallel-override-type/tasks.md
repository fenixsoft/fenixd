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
- path: tests/test_characterization_verification.py
  kind: modify
```

## 1. 写侧契约归位

- [ ] 1.1 core/dashboard/data/admin_actions.py：_RETRY_COUNTER_RESETS 中 _verify_parallel_override 由 False 改 None（:1573），与 unfreeze_spec 的 None 复位语义对齐；修正 :1560-1567 失实注释；核对消费点 reset_verification（:1758-1770）与 _exec_continue_auto_fix（:2014-2031）取值路径。

## 2. 解析侧归一与读端留痕

- [ ] 2.1 core/state_machine.py：（a）写入侧 update_spec/_apply_updates_entry（:1373-1435）为 _verify_parallel_override 加单字段形状守卫——布尔或字符串形状（'False'/'true' 等）拒绝并告警或归 None，不静默序列化进 STATE.md；（b）parse 侧登记 int|None 归一（int 先例区 :538-558，null 兼容），覆盖存量 STATE.md 'False' 首读清洗。
- [ ] 2.2 core/pm_engine/verification/pipeline.py：读端解析失败分支（:2108-2118）告警现网已含 repr（:2114 `{_parallel_override!r}`）——保持不退化并补字段来源（值取自 spec attrs）；不做布尔→并行度映射。

## 3. 测试

- [ ] 3.1 tests/test_verify_parallel_override_reset.py（新建）：reset_verification/continue_auto_fix 后字段为 null 且 STATE.md 往返读回 null；'False'/'true' 等形状写入被拒/归 None；读端告警含 repr；既有 tests/test_verify_parallel_backoff.py 零回退。
- [ ] 3.2 tests/test_characterization_verification.py：parse 归一使往返读值由 `"2"` 变 `2`，同步更新 :177 断言（`== "2"` → `== 2`）， characterization 不静默留红。