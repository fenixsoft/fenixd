# Tasks: add-codefix-parse-error-breaker

## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_targeted_retry.py
  kind: modify
```

## 1. 熔断判据与计数

- [ ] 1.1 在 `core/code_fix.py` 新增模块常量 `REGRESSION_ANOMALY_BREAKER_THRESHOLD = 2` 与判据函数 `_is_regression_anomaly(reg, fail_items) -> bool`（`status == "parse_error"`，或 `status == "failed"` 且 `fail_items` 为空；真实测试失败返回 False）
- [ ] 1.2 在批收尾定向重试循环（首轮回归失败进入 `for attempt in range(1, retry_max + 1)` 的块）维护同批连续异常计数 `anomaly_streak`：每轮回归非 passed 且判据命中时 +1，判据未命中（有明细的真实失败）时清零，回归 passed 天然离开循环
- [ ] 1.3 定向轮回归结果处（既有 `if reg.status == "passed": break` 的对偶位置）与首轮计数同口径更新计数，确保首轮与每个定向轮的回归都进计数窗口

## 2. 熔断短路收口

- [ ] 2.1 计数达到阈值时置熔断标志并记 WARNING 日志（含触发判据：各轮回归 status 与明细形态），不再派发下一轮定向 run，直接以等价 `exhausted` 状态进入既有现场即弃收口块
- [ ] 2.2 收口 reason 按熔断标志分流：`record_failed_batch` 与进度 `write_progress` 的 reason 在熔断时取 `regression_parse_error_breaker`，轮数耗尽路径保持 `regression_failed_twice` 逐字不变
- [ ] 2.3 收口告警保持既有 `write_regression_failed_alert` 单一调用点复用（熔断与轮数耗尽不重复告警），`retry_rounds` 参数按实际执行轮数传入；grep 确认消费侧对 `fix-failed.json` 批次 reason 无 `regression_failed_twice` 全等匹配依赖（有则同步兼容新名）

## 3. 测试

- [ ] 3.1 在 `tests/test_codefix_targeted_retry.py` 新增熔断用例：连续 2 轮 parse_error（或空明细 failed）→ 第 3 轮定向 run 不派发、现场即弃收口、档案 reason 为 `regression_parse_error_breaker`、告警恰好一次
- [ ] 3.2 新增真实失败不熔断用例：第 1 轮 parse_error + 第 2 轮有明细 failed → 计数清零、循环走满既有轮数、收口 reason 仍为 `regression_failed_twice`
- [ ] 3.3 新增回归通过重置用例：任一轮回归 passed → 正常合回核销路径与现状逐字一致，熔断零参与
