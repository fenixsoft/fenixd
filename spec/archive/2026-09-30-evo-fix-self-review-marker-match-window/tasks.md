## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_result_based_classification.py
  kind: modify
```

## 1. marker 匹配窗口收敛

- [x] 1.1 core/self_review.py：_business_fail_marker 把 _BUSINESS_FAIL_PATTERNS 匹配限定在 result 文本前 100 字符窗口内（引入模块级常量），词表、返回值形态与 _classify_run 结构不变
- [x] 1.2 core/self_review.py：_signal_evidence 函数本体与 _scan_run_signals 只补 detail 语义均不变；护栏调用点收窄为 lines[:-1]（排除 result 终态正文，09-24 实拍误判第二源 companion 修复——_BUSINESS_FAIL_SIGNALS 与 marker 词表共享「预算耗尽」词形），事件行兜底通道保持（test_signal_fallback_when_no_marker 通过）。（任务文本修订 2026-09-24 code-review，与实现对齐）

## 2. 测试

- [x] 2.1 tests/test_self_review_result_based_classification.py：新增回归——result 终态 is_error=False 且 subtype=success、「预算耗尽」仅出现在摘要中段（实拍句「预算耗尽发一次性 warning」形态）时计 succeeded 且不入失败样本
- [x] 2.2 tests/test_self_review_result_based_classification.py：与既有「开头声明形态仍判 failed」用例成对锁边界，并确认既有全部 marker 夹具（test_self_review_run_semantics.py、test_self_review_result_based_classification.py、test_self_review_archive_stats.py）与 test_signal_fallback_when_no_marker 兜底语义在窗口收敛后保持通过
