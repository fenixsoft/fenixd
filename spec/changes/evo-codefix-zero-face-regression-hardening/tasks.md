## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_codefix_anomaly_redispatch_budget.py
  kind: modify
- path: tests/test_code_fix.py
  kind: modify
```

## 1. 判据与收口

- [ ] 1.1 core/code_fix.py：`_is_regression_anomaly()`（约 :1048-1060）把「status=timeout 且无可用失败用例明细」补入异常判定，使 timeout 零失败面进入 anomaly 分档（reg_form=anomaly、跨链重派预算 1、一次性降档告警自动生效，重派侧零改动）
- [ ] 1.2 core/code_fix.py：批 worker 异常短路判断（约 :5671，阈值常量 REGRESSION_ANOMALY_BREAKER_THRESHOLD=2 于 :1045）对 timeout 零失败面首记即收口——当轮提前终止本批定向重试、不再等连续 2 次计数；parse_error/failed 形态阈值维持 2 不变
- [ ] 1.3 core/code_fix.py：`_ingest_failure_round()`（约 :1017-1037）透传回归快照 long_tests（字段缺失容错），`write_fix_reg_failures()`（约 :846）把 long_tests（用例名+耗时；缺失时次选 junit.xml.log 尾段）并入明细档新增可选键，worktree 清理前落盘；定向重试读 items/fallback_full 的既有消费方不受影响

## 2. 测试

- [ ] 2.1 tests/test_codefix_anomaly_redispatch_budget.py：覆盖 timeout-无明细判 anomaly、timeout 首记即收口（当轮终止、不再第二轮）、parse_error/failed 阈值仍为 2 不回归、reg_form 分档与一次性降档告警不回归
- [ ] 2.2 tests/test_code_fix.py：覆盖明细档含 long_tests 键（用例名+耗时）、快照无 long_tests 时回退现形态不报错、定向重试消费路径不受新增可选键影响