# 能力：code-fix-artifact-stop-loss

## R1 结构化失败类别透出

产物硬门零产物失败时，CodeFixResult 信封（core/agent_runner/maintenance_runs.py）携带 failure_category="artifact_missing"；既有 conn_error 字段语义不变，其余失败类别不新增。

## R2 同指纹零产物止损

code-fix 链循环（core/code_fix.py）在收到 failure_category="artifact_missing" 的 run 失败时：

- 按批次指纹累计连败次数；
- 连败 ≥2 即停止该指纹的继续重派：标记跳过、经既有告警/日志通道留痕（含指纹、连败次数、最后失败 run id），链内其余指纹不受影响；
- 单次失败仍走既有 chain_skipped 瞬态重试，行为不变；
- 非 artifact_missing 失败不计入该计数，与 add-codefix-parse-error-breaker 的 parse-error anomaly_streak 计数域互不干扰。

## R3 派发契约测试

- 断言 agents/code-fix.md 含同步派发契约关键条款（「回合结束 = run 终止」「run_in_background: false」「禁止后台派发后结束回合等待通知」），防模板漂移。
- 断言止损状态机：1 次 artifact_missing 不触发、2 次触发、其他类别不计数、触发后该指纹跳过且留痕。