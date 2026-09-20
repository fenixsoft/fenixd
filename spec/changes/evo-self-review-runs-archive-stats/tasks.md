# Tasks: self-review-runs-archive-stats

## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_archive_stats.py
  kind: new
```

## 1. 归档并集统计

- [ ] 1.1 core/self_review.py collect_runs_stats：统计源改为「.fenix/runs/*.jsonl + .fenix/runs/archive/*.jsonl」并集，复用 _run_start_ts/_in_window/_classify_run 按 run_id 内嵌开始时间戳统一判定窗口归属
- [ ] 1.2 core/self_review.py collect_runs_stats：归档目录只读遍历（目录不存在时忽略），同 run_id 当前目录优先去重；保持排除 review- 前缀、不触发写操作
- [ ] 1.3 core/self_review.py：输出 counts 键（total/succeeded/failed/instant_hang/timeout/dropped/running）与调用方契约不变

## 2. 测试

- [ ] 2.1 tests/test_self_review_archive_stats.py：归档目录内窗口内完成 run 计入 total/succeeded（构造临时 runs+archive 目录传入）
- [ ] 2.2 tests/test_self_review_archive_stats.py：当前目录（在飞）与归档跨窗口 run 的窗口归属判定正确，同 run_id 去重生效