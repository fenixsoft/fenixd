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

- [ ] 1.1 排程重验写入点（escalation.py `_schedule_scenario_repair_reverify`，由 pipeline.py 首次耗尽分支调用；不是 `_escalate_scenario_repair_exhausted`）：`_reverify_pending`/`_reverify_reason` 与既有 `_dispatch_backoff_until` 同一原子写落盘；截止单源复用 `_dispatch_backoff_until`，MUST NOT 另立第二截止字段；清零接线三处——重验执行落定（verified/bug-found）、人工解冻（unfreeze_spec 清零集）、恢复路径拾起时——清零集同步含仍未来的 `_dispatch_backoff_until` 残留
- [ ] 1.2 单测（tests/test_scheduled_reverify_restart.py 新建）：排程后 STATE 含 `_reverify_pending`/`_reverify_reason` 且 `_dispatch_backoff_until` 同写；解冻/重验落定后三字段清零

## 2. 恢复路径识别排程等待态

- [ ] 2.1 恢复路径（state_machine.py 全扫恢复 TESTING 分支，"Recovered from interrupted state" 重置 implemented 处）：孤儿态判定前置检查排程等待——以 `_reverify_pending` 标记为门（MUST NOT 裸读 `_dispatch_backoff_until`：锁冲突/instant-fail/env 阻塞退避共用该字段，裸读会误豁免非排程等待）；未到期 → 保持 testing 跳过重置（INFO 留痕）；已到期 → 保持 testing 并清排程标记，由既有 `event_bus._recover_testing` 周期扫描拾起（无须恢复路径自行派发）；无排程标记 → 既有恢复行为逐位不变
- [ ] 2.2 单测：①testing + 未到期排程 + 无在飞 run → 恢复不重置、字段保留；②testing + 已到期排程 → 恢复不重置、标记清除、周期扫描可拾起；③testing 无排程无在飞 → 既有重置行为不变；④排程字段存在但 spec 非 testing → 不影响其他状态机转换；⑤testing + 非排程退避等待（如锁冲突 backoff）无在飞 → 既有重置行为不变（标记为门的回归证明）

## 3. 回归

- [ ] 3.1 既有恢复路径/autorecovery 相关用例全绿（孤儿态重置、resume 续做语义不回归）
- [ ] 3.2 既有排程重验（escalation）相关用例全绿（排程触发条件与预算语义不变）
