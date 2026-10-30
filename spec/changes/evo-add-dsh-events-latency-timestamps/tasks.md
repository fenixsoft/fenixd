## Deliverables

```yaml
- path: core/agent_runner/harness/dsh_adapter.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_dsh_projection.py
  kind: modify
- path: tests/test_run_latency_stats.py
  kind: modify
```

## 1. 投影层时间戳

- [ ] 1.1 core/agent_runner/harness/dsh_adapter.py：DshEventProjector.ingest/_project（:283/:339）为投影产出事件统一打到达时刻 timestamp，使 latency_samples_from_events（latency.py:132）对 dsh 事件出样本
- [ ] 1.2 core/agent_runner/runner.py：失明 WARNING 发射点（:7032-7045）按（harness,事件形态）进程级一次性去重，文案改为如实描述时间戳缺失根因

## 2. 测试

- [ ] 2.1 tests/test_dsh_projection.py：断言投影产出的 assistant/user 事件携带 timestamp 字段
- [ ] 2.2 tests/test_run_latency_stats.py：dsh 事件流夹具经配对函数产出 >0 延迟样本（rounds/stalls 与夹具注入间隔一致）