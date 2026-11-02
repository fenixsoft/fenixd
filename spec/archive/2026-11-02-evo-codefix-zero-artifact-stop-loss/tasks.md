## Deliverables

```yaml
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_zero_artifact_breaker.py
  kind: new
- path: agents/code-fix.md
  kind: reference
```

> 定位约定：主干并发演进使行号快速漂移，以下任务一律以符号定位（起草时快照行号已弃用）。

## 1. 失败类别透出

- [x] 1.1 core/agent_runner/maintenance_runs.py：run_code_fix 收尾「产物硬门」块（_check_code_fix_artifact 调用点）判定零产物失败时在 CodeFixResult 信封置 failure_category="artifact_missing"（类定义 core/agent_runner/result_gate.py，新增字段带缺省值、既有各构造点零触碰），conn_error 既有语义不变
- [x] 1.2 core/code_fix.py：CodeFixChain._run_batch_inner 首轮 run 失败收尾块读取 failure_category，对同批次指纹累计 artifact_missing 连败计数（daemon 进程内跨链）

## 2. 同指纹止损

- [x] 2.1 core/code_fix.py：artifact_missing 连败 ≥2 即停止该指纹重派——指纹加入进程内止损跳过集（MUST NOT 复用 chain_skipped：其新链启动即重置，承载不了跨链止损），经既有告警/日志通道留痕（指纹、连败次数、最后失败 run id）；单次失败仍走既有 chain_skipped 瞬态重试
- [x] 2.2 core/code_fix.py：止损跳过集纳入选批排除并集（失败档案 ∪ chain_skipped ∪ 止损跳过集），触发后同指纹下一链不再入选；daemon 重启清零、残余面由既有 fail_count 预算兜底
- [x] 2.3 核对与已归档 add-codefix-parse-error-breaker 的回归异常熔断（_is_regression_anomaly/_anomaly_breaker_threshold，位于回归失败后的定向重试循环内）计数域互不干扰：仅首轮 run 失败计数，非 artifact_missing 失败与定向重试轮 run 失败（regression_retry_run_failed）不计数

## 3. 契约测试

- [x] 3.1 tests/test_codefix_zero_artifact_breaker.py：覆盖信封类别透出、1 次不触发/2 次触发/其他类别不计数的止损状态机、触发后跳过与留痕
- [x] 3.2 tests/test_codefix_zero_artifact_breaker.py：按字面子串断言 agents/code-fix.md 含「回合结束 = run 终止」「run_in_background: false」「MUST NOT 以「等待完成通知」」同步派发契约条款（参照 tests/test_prompt_lane_efficiency_sections.py「长任务前台等待」段先例），防模板漂移
