## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: agents/planner-plan.md
  kind: modify
- path: tests/test_run_metrics_usage_backfill.py
  kind: new
```

## 1. 用量回填

- [ ] 1.1 core/agent_runner/runner.py：终态 run_metrics 落盘点（:8244-8247 一带）——逐消息累计用量全零时从 last_result 真实用量回填计量字段并标注来源；逐消息累计非零时不覆盖；last_result 无用量时字段保持零且不异常。

## 2. planner-plan 输出纪律

- [ ] 2.1 agents/planner-plan.md：增加输出纪律/简洁性条款（形态仿 agents/planner-judge.md:88），仅约束叙述性输出形态，不改动交付要求与其余段落。

## 3. 测试

- [ ] 3.1 tests/test_run_metrics_usage_backfill.py：覆盖①逐消息全零+last_result 有用量→回填+来源标注；②逐消息非零→不覆盖；③last_result 无用量→字段保持零不异常。