# 能力规格：arbiter-infra-failure-reset

## 需求

- **R1 失败分级**：`_on_run_failed` 依 `classify_lane_failure` 将 run 失败分为 infra（0 rounds 或环境指纹命中：MISSING_CREDENTIAL / No such file or directory / skipping profile bundle / exit=1 且 rounds=0）与 judgment（其余）；预算耗尽恒判 judgment。
- **R2 infra 通道**：infra 失败走独立计数 `_infra_failure_counts`（上限 `arbiter.max_consecutive_infra_failures`，缺省=既有连败上限），写台账 kind=infra-failed（action 注明待健康复位），不加 `_deadmanned`、不升级人工 alert（WARNING 日志 + 一次性车道环境告警）。
- **R3 复位**：健康探针成功（启动/周期/派发前置任一路径）即清全部 infra 计数并留痕；judgment 连败计数与 dead-man 永久语义不受影响、无复位。
- **R4 兼容**：新 kind=infra-failed 对台账读侧（dead-man 持久读、回扫排除、配额判定）完全透明；台账 append-only 与跨重启读纪律不破坏。

## 场景

- **S1** 0 rounds + MISSING_CREDENTIAL 失败连续 ≥ 上限 → 台账全为 infra-failed、`_deadmanned` 为空、无人工升级 alert；同签名下次触发仍可再试。
- **S2** 有 API 往返的失败连续 ≥ `max_consecutive_failures` → 现行 dead-man 永久升级（回归不变）。
- **S3** run 预算耗尽 → 判 judgment 走 dead-man，不误判 infra。
- **S4** infra 停机后探针转 healthy → infra 计数清零、日志「车道健康复位」，同签名恢复自主处置。
- **S5** 历史台账含 infra-failed 行 → dead-man 判定、回扫排除行为与无该行时完全一致。

## Deliverables

- path: core/pm_engine/arbiter.py
  kind: modify
- path: core/agent_runner/lane_preflight.py
  kind: new
- path: tests/test_arbiter_lane_resilience.py
  kind: new
