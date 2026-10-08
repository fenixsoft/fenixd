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

- [ ] 1.1 core/code_fix.py：`_is_regression_anomaly()`（约 :1048-1060）把「status=timeout 且无可用失败用例明细」补入异常判定，使 timeout 零失败面进入 anomaly 分档（reg_form=anomaly、跨链重派预算 1、一次性降档告警自动生效，重派侧零改动——归档处 reg_form 正由该函数计算，core/code_fix.py:5771-5777）；同步更新四处枚举注释防漂移：:92-94（ANOMALY_FAIL_RETRY_MAX 注释）、:100-102（REG_FORM 合法值注释）、:1040-1044（阈值注释）、:1048-1057（函数 docstring），枚举由「parse_error 或 failed 无明细」扩为「parse_error、failed 无明细、timeout 无明细」
- [ ] 1.2 core/code_fix.py：批 worker 异常短路判断对 timeout 零失败面首记即收口——**两个计数点都接判断**：①定向轮计数点（约 :5667-5671，阈值常量 REGRESSION_ANOMALY_BREAKER_THRESHOLD=2 于 :1045）对 timeout 形态取阈值 1；②首轮全量回归计数点（约 :5575-5583）计数后加同款短路判断——该处现无判断，且 :5573-5574 注释「阈值 ≥ 2 下首轮单次计数不可能达阈值，无需在此短路」在 timeout 阈值=1 后失效，须同步更新；否则首轮全量回归即 timeout 零失败面（10-08 批 1 实际形态）时仍会先派 1 个定向 run 并再烧一轮 1800s 全量回归才熔断，违背「首记即收口」。timeout 形态触发时须显式置 breaker_triggered/exhausted 再 break（Python for-else 语义：break 跳过 else 分支，exhausted 不会自动置位，收口块依赖它）；parse_error/failed 形态阈值维持 2 不变
- [ ] 1.3 core/code_fix.py：`_ingest_failure_round()`（约 :1017-1037）透传回归快照 long_tests（字段缺失容错），`write_fix_reg_failures()`（约 :846）把 long_tests（用例名+耗时；缺失时次选 junit.xml.log 尾段）并入明细档新增可选键，worktree 清理前落盘；定向重试读 items/fallback_full 的既有消费方不受影响

## 2. 测试

- [ ] 2.1 tests/test_codefix_anomaly_redispatch_budget.py：覆盖 timeout-无明细判 anomaly、timeout 首记即收口（当轮终止、不再第二轮）、parse_error/failed 阈值仍为 2 不回归、reg_form 分档与一次性降档告警不回归
- [ ] 2.2 tests/test_code_fix.py：覆盖明细档含 long_tests 键（用例名+耗时）、快照无 long_tests 时回退现形态不报错、定向重试消费路径不受新增可选键影响