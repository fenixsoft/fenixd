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
- [ ] 1.3 core/self_review.py：`_scan_run_signals` 兜底仅保留给 error 终态或无 result 终态，且**只补 detail 归因、不改写 category**——落点为 `collect_failed_run_samples` 中 `category == "failed"` 的样本（detail 为空时拼 `signal=<词>`）；`collect_runs_stats` 因无 detail 通道**不追加扫描**，`running`/`dropped`/`timeout`/`instant_hang` 分类 MUST 保持不变（禁止「非 succeeded 分支一律 `if sig: category = "failed"`」写法）
- [ ] 1.4 core/self_review.py：`_classify_run` result 分支的 `_signal_evidence`（终态邻近 3 行）MUST 保留不移除；在 `collect_runs_stats`/`collect_failed_run_samples` 处补注释写明判定口径（以 `_classify_run` 的 result 分支为准、不引入成功语义白名单）与接受项边界（终态邻近 3 行之外的主题词不再翻转分类）

## 2. 测试

- [ ] 2.1 tests/test_self_review_result_based_classification.py：夹具「成功 result + 正文含预算耗尽/impl_budget_exhausted/spec_content_missing」→ 断言 succeeded 且不入失败样本（复现 2026-09-17 5/7 误报场景）
- [ ] 2.2 tests/test_self_review_result_based_classification.py：夹具「error 终态 + 信号词」→ 断言 failed(signal=...)；「无 result 终态 + 信号词」→ 断言兜底归因生效
- [ ] 2.3 tests/test_self_review_result_based_classification.py：夹具「result 文本命中业务失败标记」→ 断言 failed(marker=...) 维持（回归既有语义）
- [ ] 2.4 全量回归：tests/test_daily_self_review.py、tests/test_self_review_run_semantics.py 与 tests/test_self_review_window_snapshot.py 全绿（已实测：仅关闭聚合层全文件扫描时三文件 88 passed，既有断言不依赖被删分支），样本/统计输出契约不变
- [ ] 2.5 tests/test_self_review_result_based_classification.py：夹具「result 终态 + 信号词仅出现在终态邻近 3 行之外」→ 断言 succeeded 且不入失败样本；夹具「无 result 终态（running/dropped）+ 信号词」→ 断言 category 桶位不变、`stats["failed"]` 不因该 run 增加