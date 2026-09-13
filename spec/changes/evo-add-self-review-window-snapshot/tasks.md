## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_window_snapshot.py
  kind: new
```

## 1. 快照化

- [ ] 1.1 `_in_window` 增加 `window_end: Optional[datetime] = None` 参数，缺省为实时 now（兼容既有调用方）
- [ ] 1.2 `collect_runs_stats` 与 `collect_log_errors` 入口取一次固定 `window_end = datetime.now()` 并贯穿全部判定

## 2. 测试

- [ ] 2.1 tests/test_self_review_window_snapshot.py：构造窗口边界 run（恰在快照前/后创建），断言归属与聚合启动时刻一致
- [ ] 2.2 回归：聚合耗时场景下边界不漂移（mock now 两次调用返回不同值断言不受影响）
