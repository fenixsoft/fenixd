## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/pm_engine/spec_review.py
  kind: modify
- path: core/pm_engine/infra_breaker.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_spec_review_infra_attribution.py
  kind: modify
- path: tests/test_spec_review_agent.py
  kind: modify
- path: tests/test_crossday_recurrence_fingerprint.py
  kind: modify
```

## 1. 归因留痕

- [x] 1.1 core/agent_runner/runner.py：run_spec_review 失败归因桥接（:1622-1638 附近）补 stderr_tail 透出（复用 core/agent_runner/maintenance_runs.py 的 _stderr_tail_summary 读异常 stderr_lines），与既有 api_error_status 并列；不改共享底座错误文本。
- [x] 1.2 core/agent_runner/result_gate.py：AgentRunResult（:132-156 附近）新增 stderr_tail 字段，形态对齐 api_error_status。
- [x] 1.3 core/pm_engine/spec_review.py：评审失败 ERROR 行（:433，含 :490 reason 处）追加 [api_error_status=… exit_code=… stderr_tail: …] 括注，形态对齐 code-fix 车道（maintenance_runs.py:2595-2599 的括注结构与 stderr_tail 位置）；键名用 api_error_status 而非 code-fix 的 api_timeout（评审车道无 salvage 语义，与 proposal「What Changes」#1 及 spec.md Scenario「ERROR 行含 api_error_status=429」断言一致）。result 为 None 的异常子路径（run_spec_review 抛异常，spec_review.py:429-430）无结构化字段可读，括注整体省略；括注验收以 result.success=False 主路径为对象。

## 2. 指纹归一化与熔断计数

- [x] 2.1 core/admin_monitor.py：_normalize_error_message（:598-611）新增窄化规则——仅对 spec_review 组件「评审 run 执行失败: <spec>: …」模板剥离 SPEC 名段，其他组件文字骨架不动（沿用 ：578 保守集原则）。
- [x] 2.2 core/pm_engine/spec_review.py：评审 run 成功收工路径接线 record_success("spec-review")，成功后清零连续 infra 失败计数。落点在 run_ok=True 的收工处（含 run 跑通但产物不合法、走 content 类重试的分支）——design D3「链路证明可用」语义：infra 层已跑通即清零，产物质量类失败不影响 infra 计数。
- [x] 2.3 core/pm_engine/infra_breaker.py：确认 record_success 清零语义在「冷却到期后首次派发成功」路径生效，熔断短路期间未实际派发的尝试不计入成功/失败，不足处补齐。

## 3. 测试

- [x] 3.1 tests/test_spec_review_infra_attribution.py：桥接透出 stderr_tail/api_error_status 断言；评审失败 ERROR 行含归因括注。
- [x] 3.2 tests/test_crossday_recurrence_fingerprint.py：剥离 SPEC 名后不同 SPEC 同型失败同指纹；其他组件骨架不受影响的反例。
- [x] 3.3 tests/test_spec_review_agent.py：评审成功后熔断计数清零、失败后窗口内连续计数递增；陈旧跨周计数不再误触熔断。