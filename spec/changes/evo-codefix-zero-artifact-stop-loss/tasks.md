## Deliverables

```yaml
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_zero_artifact_breaker.py
  kind: new
- path: agents/code-fix.md
  kind: reference
```

## 1. 失败类别透出

- [ ] 1.1 core/agent_runner/maintenance_runs.py：_check_code_fix_artifact 硬门零产物失败时在 CodeFixResult 信封置 failure_category="artifact_missing"（:3172-3183 拦截点、:3226-3230 信封），既有 conn_error 语义不变
- [ ] 1.2 core/code_fix.py：首轮 run 失败收尾块（:6413-6447）读取 failure_category，对同批次指纹累计 artifact_missing 连败计数

## 2. 同指纹止损

- [ ] 2.1 core/code_fix.py：artifact_missing 连败 ≥2 即停止该指纹重派，标记跳过并经既有告警/日志通道留痕（指纹、连败次数、最后失败 run id）；单次失败仍走既有 chain_skipped 瞬态重试
- [ ] 2.2 核对与 add-codefix-parse-error-breaker 的 parse-error anomaly_streak（:6499-6510）计数域互不干扰，非 artifact_missing 失败不计入

## 3. 契约测试

- [ ] 3.1 tests/test_codefix_zero_artifact_breaker.py：覆盖信封类别透出、1 次不触发/2 次触发/其他类别不计数的止损状态机、触发后跳过与留痕
- [ ] 3.2 tests/test_codefix_zero_artifact_breaker.py：断言 agents/code-fix.md 含「回合结束 = run 终止」「run_in_background: false」同步派发契约条款（参照 tests/test_prompt_lane_efficiency_sections.py:73-81 先例），防模板漂移