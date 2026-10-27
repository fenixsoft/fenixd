## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: tests/test_unfreeze_judge_counter_reset.py
  kind: new
```

## 1. unfreeze 清零集补齐

- [ ] 1.1 `core/state_machine.py` unfreeze_spec 清零集（updates dict，与 `SCENARIO_REPAIR_EXHAUSTED_FIELD`/`LEGACY_DEGRADE_STREAK_FIELD` 同段）补入 `_judge_rerun_count = 0` 与 `_judge_cap_frozen = False`；字段键名与 `core/pm_engine/verification/judge_gate.py` `_judge_rerun_count`/`_judge_hard_cap_freeze` 读写键严格一致（优先复用/单点定义命名常量，禁裸串漂移）
- [ ] 1.2 单测（tests/test_unfreeze_judge_counter_reset.py 新建）：①`_judge_rerun_count=6`+`_judge_cap_frozen=True` 冻结条目解冻 → 两字段归零/清除且与既有清零字段同写落盘；②解冻后模拟 judge 派发门 delta=1 → count=1 不触发 hard cap；③存量条目缺两键 → 解冻等价补零无异常

## 2. 回归

- [ ] 2.1 既有 unfreeze/验证计数相关测试全绿（既有清零字段行为逐位不变）
- [ ] 2.2 核对 `state_machine.py:635-639` 注释与补齐后的实现一致（表述不需改动即自洽；如有出入以实现语义修正注释）
