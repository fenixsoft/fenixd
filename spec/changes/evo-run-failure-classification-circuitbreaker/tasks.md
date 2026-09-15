## Deliverables

```yaml
- path: core/pm_engine/spec_review.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/config.py
  kind: modify
- path: tests/test_review_circuit_breaker.py
  kind: new
```

## 1. 失败分类

- [ ] 1.1 core/pm_engine/spec_review.py：新增 _classify_failure(reason, exit_code) → artifact|infra|content（artifact 复用 run-failure-artifact-first 产物判定；infra 指纹 403/402/429/quota/budget/余额/rate limit/CLI 进程级崩溃）
- [ ] 1.2 _handle_review_failure 按分类落点：content → 既有重试；infra → 熔断计数 + 升级告警；artifact → 直接消费（不重试）

## 2. 熔断与冷却

- [ ] 2.1 core/pm_engine/engine.py：链路级熔断器（threshold=3、cooldown=30min、持久化 .fenix/admin_infra_breaker.json）；熔断窗口内派发入口短路
- [ ] 2.2 core/config.py：admin.run_infra_breaker.{threshold, cooldown_minutes}（默认 3/30）
- [ ] 2.3 冷却到期自动恢复，恢复后首次成功清零计数；daemon 重启后熔断状态从持久化文件恢复

## 3. ADMIN 信号接入

- [ ] 3.1 core/admin_monitor.py：登记 run_infra_failure（critical）至 SIGNAL_SEVERITY/SIGNAL_RECOMMENDATION；熔断触发/恢复各落一条升级记录，evidence 含链路/指纹/次数/时间窗

## 4. 测试

- [ ] 4.1 tests/test_review_circuit_breaker.py：连续 3 次 infra → 熔断（不再派发、恰好 1 条 critical）；冷却后自动恢复重试
- [ ] 4.2 内容失败维持重试语义；artifact 失败不重试（联动 run-failure-artifact-first 测试）
- [ ] 4.3 熔断状态 daemon 重启后恢复（持久化读回）