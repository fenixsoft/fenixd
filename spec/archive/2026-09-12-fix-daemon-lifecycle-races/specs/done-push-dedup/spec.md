# done-push-dedup

## ADDED Requirements

### Requirement: 自动审批链路单飞

`approve_push` MUST 在实例级互斥锁内执行完整 check-then-act：acquire → 重读 spec status → 非 done 幂等跳过（返回 True）→ git push → transition(pushed) → release。并发第二个执行流 MUST 在锁上排队，进入后见 pushed 即幂等跳过，不重复执行 git push、不产生重复 project log、不触发 pushed→pushed ERROR。

#### Scenario: 双路径并发仅一次 push

- **WHEN** verify 成功后同步直调 `_on_spec_done`（engine.py:363 路径）与 event_bus spec_done 事件并发进入 `_auto_approve` → `approve_push`
- **THEN** 仅第一个流执行 git push 与 done→pushed 迁移；第二个流排队后幂等跳过，日志无「Invalid transition: pushed → pushed」

#### Scenario: 串行化不同 spec 的 push

- **WHEN** 两个不同 spec 的 approve_push 并发到达
- **THEN** 二者串行执行（全局锁），git push main 无并发竞态
