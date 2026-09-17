## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_result_based_classification.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/self_review.py：collect_runs_stats（:310-312）删除 succeeded 后全文件信号扫描降级分支——result 成功终态直接计为 succeeded，不再调用 _scan_run_signals 翻转分类
- [ ] 1.2 core/self_review.py：collect_failed_run_samples（:351-353）同步删除 succeeded 后全文件信号扫描分支，成功终态不入选失败样本
- [ ] 1.3 core/self_review.py：信号扫描兜底仅保留给 error 终态或无 result 终态（在非 succeeded 分支追加 _scan_run_signals 归因，真失败不丢）

## 2. 测试

- [ ] 2.1 tests/test_self_review_result_based_classification.py：夹具「成功 result + 正文含预算耗尽/impl_budget_exhausted/spec_content_missing」→ 断言 succeeded 且不入失败样本（复现 2026-09-17 5/7 误报场景）
- [ ] 2.2 tests/test_self_review_result_based_classification.py：夹具「error 终态 + 信号词」→ 断言 failed(signal=...)；「无 result 终态 + 信号词」→ 断言兜底归因生效
- [ ] 2.3 tests/test_self_review_result_based_classification.py：夹具「result 文本命中业务失败标记」→ 断言 failed(marker=...) 维持（回归既有语义）
- [ ] 2.4 全量回归：tests/test_daily_self_review.py 与 tests/test_self_review_run_semantics.py 通过，样本/统计输出契约不变