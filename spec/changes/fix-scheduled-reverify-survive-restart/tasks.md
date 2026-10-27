## Deliverables

```yaml
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: tests/test_scheduled_reverify_restart.py
  kind: new
```

## 1. 排程状态持久化

- [ ] 1.1 排程重验写入点（escalation.py `_escalate_scenario_repair_exhausted` 一带）：排程时刻与来源信号写 STATE 结构化字段 `_reverify_scheduled_at`/`_reverify_reason`（与排程动作同一原子写）；清零接线三处——重验执行落定（verified/bug-found）、人工解冻（unfreeze_spec 清零集）、恢复路径触发重验时
- [ ] 1.2 单测（tests/test_scheduled_reverify_restart.py 新建）：排程后 STATE 含结构化字段；解冻/重验落定后字段清零

## 2. 恢复路径识别排程等待态

- [ ] 2.1 恢复路径（"Recovered from interrupted state" 产生点，grep 定位实现处）：孤儿态判定前置检查排程字段——未到期 → 保持 testing 跳过重置（INFO 留痕）；已到期 → 触发重验并同写清排程字段（在飞互斥既有守卫兜底幂等）；无排程 → 既有恢复行为逐位不变
- [ ] 2.2 单测：①testing + 未到期排程 + 无在飞 run → 恢复不重置、字段保留；②testing + 已到期排程 → 恢复触发重验且字段清除；③testing 无排程无在飞 → 既有重置行为不变；④排程字段存在但 spec 非 testing → 不影响其他状态机转换

## 3. 回归

- [ ] 3.1 既有恢复路径/autorecovery 相关用例全绿（孤儿态重置、resume 续做语义不回归）
- [ ] 3.2 既有排程重验（escalation）相关用例全绿（排程触发条件与预算语义不变）
