# Tasks: self-review-runs-archive-stats

## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_archive_stats.py
  kind: new
```

## 1. 归档并集统计

- [ ] 1.1 core/self_review.py collect_runs_stats：统计源改为「.fenix/runs/*.jsonl + .fenix/runs/archive/*.jsonl」并集（archive 目录不存在时忽略），复用 _run_start_ts/_in_window/_classify_run 按 run_id 内嵌开始时间戳统一判定窗口归属
- [ ] 1.2 core/self_review.py collect_runs_stats：归档目录只读遍历，同 run_id 当前目录优先去重；保持排除 `review-` 前缀（区别于 spec-review-/code-review-）、不触发写操作
- [ ] 1.3 core/self_review.py：输出 counts 键（total/succeeded/failed/instant_hang/timeout/dropped/running）与调用方契约不变
- [ ] 1.4 core/self_review.py collect_failed_run_samples：与 1.1/1.2 采用同一并集文件集合、同一窗口与去重口径（否则「失败计数含归档、失败样本不含」口径分裂；调用点 core/self_review.py:650-666）

## 2. 测试

- [ ] 2.1 tests/test_self_review_archive_stats.py：归档目录内窗口内完成 run 计入 total/succeeded（构造临时 runs+archive 目录传入）
- [ ] 2.2 tests/test_self_review_archive_stats.py：当前目录（在飞）与归档跨窗口 run 的窗口归属判定正确，同 run_id 去重生效
- [ ] 2.3 tests/test_self_review_archive_stats.py：归档目录内 `review-<date>` 产物被排除（归档侧 review- 前缀排除不回归）；archive 目录缺失时行为与现状一致（仅当前目录）
- [ ] 2.4 回归：tests/test_daily_self_review.py、tests/test_self_review_run_semantics.py、tests/test_self_review_result_based_classification.py、tests/test_self_review_window_snapshot.py 全绿（既有 collect_runs_stats 用例只造顶层目录，并集不得改变其结论）