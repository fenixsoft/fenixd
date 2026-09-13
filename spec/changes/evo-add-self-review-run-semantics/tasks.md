## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_run_semantics.py
  kind: new
```

## 1. 业务失败标记清单

- [x] 1.1 在 core/self_review.py 定义 `_BUSINESS_FAIL_PATTERNS` 常量清单（SPEC 内容缺失 / 无法实现 / 预算耗尽 / 零交付 / 零产出 等归一化短语），design D1 固化

## 2. 分类逻辑

- [x] 2.1 `_classify_run` 的 `t == 'result'` 分支增加业务失败解析：result 文本命中标记 → 返回 (`failed`, 标记摘要)；未命中 → succeeded
- [x] 2.2 结构性信号兜底：同 run 事件序列含 budget-exhausted / spec_content_missing 类信号且 result 未命中标记时，按失败统计（detail 附信号凭据）
- [x] 2.3 失败样本输出带 run_id + 命中标记/信号摘要（可追溯）

## 3. 测试

- [x] 3.1 tests/test_self_review_run_semantics.py：盲派 result-run 判 failed；真实成功 result-run 判 succeeded；标记/信号双源兜底；样本输出含依据
