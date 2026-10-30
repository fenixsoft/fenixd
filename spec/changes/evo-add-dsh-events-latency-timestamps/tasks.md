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
- [ ] 1.2 core/agent_runner/runner.py：失明 WARNING 发射点（:7047-7055）按（harness,事件形态）实例级一次性去重（AgentRunner 实例属性，见 design；MUST NOT 模块级集合——会 primed 掉同进程后续用例），文案改为如实描述时间戳缺失根因且保留「失明」标记与 extra 键 latency_rounds=0/turn_count/run_id（tests/test_run_latency_stats.py:354-405 锁定）

## 2. 测试

- [ ] 2.1 tests/test_dsh_projection.py：断言投影产出的 assistant/user 事件携带 timestamp 字段
- [ ] 2.2 tests/test_run_latency_stats.py：dsh 事件流夹具经配对函数产出 >0 延迟样本（rounds/stalls 与夹具注入间隔一致）
- [ ] 2.3 tests/test_run_latency_stats.py：对账既有失明两用例（:354 blind 断言 ≥1 条 WARNING / :387 vacuum 断言 ==0）与新去重+文案契约——去重状态为实例级时每用例新建 runner 天然隔离、文案锚点保留则断言零改动；若实现偏离该约定则同步更新两用例并在 PR 描述留痕