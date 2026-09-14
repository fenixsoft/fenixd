# Tasks: fix-run-cancel-retry-flag-miss

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_run_cancel.py
  kind: modify
```

## 1. 归一化对齐修复

- [x] 1.1 `core/agent_runner/runner.py`：`_normalize_run_id` 改为剥离尾部连续多组 `-a<N>`/`-r<N>` 后缀（`(?:-a\d+|-r\d+)+$`）；`_cancel_is_requested` 判定前对入参做同一归一化，使 cancel_run 登记键、轮询环键、attempt 顶键三者收敛
- [x] 1.2 `tests/test_run_cancel.py` 新增用例：①`-a1-r1` 重试轮——登记 base 键后轮询环命中并终止（复现 2026-09-08 事故路径）；②attempt 顶命中阻断后续 attempt 派发；③回归：无后缀与纯 `-a<N>` 输入行为不变；④`-r<N>`/`-a<N>` 混合多组剥离幂等
