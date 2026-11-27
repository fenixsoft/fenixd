## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_window_attribution.py
  kind: new
```

## 1. 归窗键改造

- [x] 1.1 core/self_review.py：新增终态归属时刻辅助（从档案末段最后一条 run_metrics 行读 duration_s，与 run_id 内嵌起点相加得终态时刻；无 run_metrics 行或解析失败回退起点时刻并可回退 mtime，留 debug 级降级痕迹）
- [x] 1.2 core/self_review.py：_iter_window_runs（约 :1099-1101）与 _bounded_per_run_scan（约 :1678-1680）两处归属键统一改走该辅助，保持 [window_start, window_end] 闭区间谓词与 attempt 后缀 run id、mtime 回退兼容；_iter_window_runs 侧新增的每候选 run（含窗外排除者）一次末段有界读取不超出既有 _bounded_per_run_scan 末段预算
- [x] 1.3 core/self_review.py：在飞 run 回退起点后仍入 running 桶；同一 run 终态后只入终态所在窗禁止双计；回归确认 collect_runs_stats、collect_failed_run_samples、_collect_api_stall_aggregates、_collect_midflight_scans、_collect_metrics_outliers 五个下游口径一致

## 2. 测试

- [x] 2.1 tests/test_self_review_window_attribution.py：跨缝 run 用例（起点早于窗口起点亚秒级、终态深入窗内 → 停滞聚合与 runs 统计两节均计入本窗），fixture 形态参照 tests/test_api_stall_signal_grading.py 的 _write_run/_stall_events
- [x] 2.2 tests/test_self_review_window_attribution.py：在飞 run（无 run_metrics 行）回退起点入 running 桶、缺 duration_s 回退起点留降级痕迹、跨窗终态单次入账、attempt 后缀 run id 兼容四个边界用例
- [x] 2.3 回归确认 tests/test_api_stall_signal_grading.py 与 tests/test_self_review_window_snapshot.py 存量窗口用例零失败
