## Deliverables

```yaml
- path: core/pm_engine/spec_review.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_spec_concurrency_guard.py
  kind: new
```

## 1. 审核收尾回退守卫

- [ ] 1.1 core/pm_engine/spec_review.py：收口（consume_review_result，status=approved/repaired 回退前）重读 spec 当前 status；已 implementing → 不回退，仅 INFO 日志「评审收尾遇在飞实现 run，跳过回退」
- [ ] 1.2 幂等：当前 status 非 implementing 时走既有回退路径（行为不变）

## 2. 派发前在飞评审校验

- [ ] 2.1 core/pm_engine/engine.py _on_spec_ready：派发 implementer 前检查同 spec 是否存在在飞 spec-review/repair run（agent_runner 活动 run 表，非终态判定）
- [ ] 2.2 有在飞评审 → 顺延本次派发（INFO 日志附 run_id），待 review 收尾事件后经既有 spec_ready 重触发通道重判

## 3. 合并收尾 ready 态兜底

- [ ] 3.1 合并收尾推进 implemented 处（engine.py）：当前 status=ready 且合并分支匹配该 spec implementer_run 记录（实现分支 fenix/<spec>-<ts>）→ 自动补记 implementing（合法转移自 ready）后再推进 implemented
- [ ] 3.2 兜底限定：非实现合并（文档/管理操作）不触发；ready→implemented 直接推进一律禁止（保持转移表白名单语义）

## 4. 测试

- [ ] 4.1 tests/test_spec_concurrency_guard.py：覆盖回退守卫（implementing 时不回退）、派发顺延（在飞 reviewer 拦截 + 收尾后重判）、ready 态兜底（补记 implementing 后推进、无 Invalid transition）
- [ ] 4.2 回归：既有 test 套件（spec_review / dispatch / state_machine 相关）保持全绿