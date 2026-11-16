## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_window_attribution.py
  kind: new
```

## 1. 归属判据改造

- [ ] 1.1 core/self_review.py：_bounded_per_run_scan 的窗口归属判据从 run 起点时刻（run_id 内嵌 epoch、缺省 mtime 回退）改为已终态 run 的终态事件时刻（run jsonl 文件 mtime），终态落在 [window_start, window_end] 即归本窗；第 2 节 runs 统计与第 6 节逐 run api-stall 行共用该扫描面、单点生效
- [ ] 1.2 core/self_review.py：聚合时刻仍在飞（无终态产物）的 run 不列终态统计；起点晚于 window_start 的在飞 run 维持既有「在跑」口径，起点早于锚点且仍在飞的 run 待终态落入后续窗按终态归窗补列，任一已终态 run 恰归一窗不重计
- [ ] 1.3 core/self_review.py：以档案夹具 code-review-1794585799 口径自检回归（起点早锚点 0.776 秒、终态 2026-11-13T19:13:58Z 在窗内、30 次停滞/2847.1 秒应补列归窗），并确认既有窗口类测试与新判据对齐（锁定旧起点判据的断言一并修正）

## 2. 测试

- [ ] 2.1 tests/test_self_review_window_attribution.py：覆盖起点早于 window_start 但终态在窗内的 run 计入本窗聚合（第 2 节与第 6 节口径）
- [ ] 2.2 tests/test_self_review_window_attribution.py：覆盖聚合时仍在飞不列终态、终态落入后续窗按终态补列且前窗不回溯重计
- [ ] 2.3 tests/test_self_review_window_attribution.py：覆盖亚秒缝隙回归形态（run_id 内嵌起点早锚点不足 1 秒）不再被起点判据排除