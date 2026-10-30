## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_archive_stats.py
  kind: modify
```

## 1. 收集面去重

- [ ] 1.1 core/self_review.py：_collect_run_files（:547-567）两处 glob 结果统一过滤 .dsh-events 后缀（对齐 liveness._is_dsh_events_dump 同判式），伴随流不产伪 run_id、不入 stale 桶

## 2. 测试

- [ ] 2.1 tests/test_self_review_archive_stats.py：TestCollectRunFilesUnion 新增用例——同 run 主文件+伴随流并存时计 1 次、伴随流不入 stale 桶
- [ ] 2.2 tests/test_self_review_archive_stats.py：断言过滤不误伤——正常命名 run 的统计行为与既有用例一致