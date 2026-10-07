## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix.py
  kind: modify
- path: tests/test_codefix_targeted_retry.py
  kind: modify
- path: tests/test_codefix_anomaly_redispatch_budget.py
  kind: new
```

## 1. 失败形态入档与预算分档

- [ ] 1.1 core/code_fix.py：record_failed_batch 与现场即弃收口块在失败批入档时记录回归终局形态 reg_form（anomaly=parse_error 或 failed 无明细；mapped=回归 fail_items 非空）及 reg_detail（anomaly_streak、重试收敛事实），fix-failed.json 增量键向后兼容（旧记录缺键按 mapped 处理）
- [ ] 1.2 core/code_fix.py：失败批自动重派判定按 reg_form 分档——新增异常形态预算常量（=1），anomaly 记录预算降为 1、耗尽后走既有 FAIL_RETRY_MAX 触顶「登记待人工+跳过条目」路径；mapped 保持 3；同条目集复燃沿用合档语义、reg_form 以最近一次失败为准。分档预算须同步作用于全部 fail_count 比较点：record_failed_batch hit_max（`== FAIL_RETRY_MAX`，:688）、release 释放判定（`>= FAIL_RETRY_MAX`，:1005）、条目预检/可选池过滤（:1265 一带）、延迟批收敛判定（:3589）；todo 登记与触顶告警文案的「{FAIL_RETRY_MAX} 轮」按生效预算动态呈现
- [ ] 1.3 core/code_fix.py：anomaly 形态触发降档/停派时复用 write_regression_failed_alert 通道发一次性告警（登记 branch、reg_form 与被跳过条目），不新增告警类型；一次性以失败档案记录告警标记（budget_alerted）判重实现——既有通道无指纹去重（:2316 直接 append，:5292 每次入档均发常规告警，类型不在 AdminStore 去重白名单）；既有单 run 熔断（add-codefix-parse-error-breaker）行为逐位不动

## 2. 测试

- [ ] 2.1 tests/test_codefix_anomaly_redispatch_budget.py：覆盖 anomaly 预算降为 1 并触顶登记待人工、mapped 保持 3、旧记录缺键兼容、复燃合档取最近形态、降档告警一次性
- [ ] 2.2 tests/test_code_fix.py 与 tests/test_codefix_targeted_retry.py：补 reg_form 入档用例与定向重试既有行为回归用例