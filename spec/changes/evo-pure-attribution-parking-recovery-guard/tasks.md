## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_pure_attribution_parking.py
  kind: new
```

## 1. 纯归因停泊态

- [x] 1.1 core/pm_engine/verification/pipeline.py：受理门拒收转纯归因分支置 _frozen_hold 停泊位并留痕停泊原因（替代停留无驱动 testing 态）
- [ ] 1.2 core/event_bus.py：orphaned_state 探测与 Recovery 恢复守卫增加停泊位检查——停泊态不发无驱动告警、不 re-triggering verify（停泊检查落 `spec_is_undriven` 共享判定单点，admin_monitor 与 `_recover_testing` 同源消费，勿两处各写）

## 2. 恢复重派防重放

- [ ] 2.1 core/event_bus.py：re-triggering verify 前检查「场景集+产物指纹未变且末轮归因含未修复 test-defect」，命中且该结论已复核重验至少一次则跳过执行沿用归因、不递增 judge rerun 计数；首次不沿用照常复核；「已复核重验至少一次」以跨轮持久 STATE 字段记账（bump_counters 同款、跨重启持久，进程内变量不满足）
- [ ] 2.2 core/state_machine.py：停泊退出锚点接线（人工处置/新修复 run 落地/场景集写回三处咽喉解除停泊）与沿用轮计数豁免；unfreeze 退出子路径补停泊豁免——停泊态（`_frozen_hold=True` 且 `frozen` 不在场）MUST NOT 走 `_resolve_preserved_branch` 保留分支续做，按普通解冻清理 + 重派退出

## 3. 测试

- [ ] 3.1 tests/test_pure_attribution_parking.py：拒收→停泊→无 orphaned 告警无 Recovery 重放、rerun 不变；三退出锚点解除停泊恢复正常驱动；防重放守卫命中沿用不递增、首次照常复核、指纹变化不命中照常重派