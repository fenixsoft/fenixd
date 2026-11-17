## Deliverables

```yaml
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: tests/test_quota_reset_dispatch_freeze.py
  kind: new
```

## 1. 重置时间解析与冻结

- [x] 1.1 core/agent_runner/provider_circuit.py：RATE_LIMIT 失败分支解析报文内重置时间戳，provider 冷却到期取 max(既有固定冷却, 重置时刻)，解析失败回退固定冷却

## 2. 冻结期派发消费

- [x] 2.1 core/agent_runner/runner.py 与 core/pm_engine/dispatch/queue.py：候选链无可用候选（全链冻结）时派发廉价失败（不计失败重试与预算计数；链上存在可用候选时维持既有链前进），经 infra breaker 通道维护单条汇总告警（扩展 link 维度；link 为运行时字符串键，core/pm_engine/infra_breaker.py 预期零改动，若实现需新增 link 命名常量须同批补列交付物），冻结解除后告警按既有生命周期收口（挂闸门查询处到期翻转）

## 3. 测试

- [x] 3.1 tests/test_quota_reset_dispatch_freeze.py：覆盖「重置时刻冻结生效且期内零真实派发」「冻结期派发廉价失败且汇总告警单条」「重置早于固定冷却时按固定时长」「解析失败回退现状」四场景