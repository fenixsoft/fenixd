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

- [x] 1.1 core/agent_runner/runner.py：终态 run_metrics 落盘收尾块——转录行（:8306-8344）与同块日志侧行（:8357-8397）两 sink 同源同值回填，MUST NOT 只回填一行。全零判定取逐消息累计的实际载体字段（total_input_tokens 与 total_cache_read_tokens 均 0，:7412-7413 仅累计此两字段、无 output 载体）；全零时从 last_result 的真实用量（result 事件 :7440-7441，usage 含 input/cache_read/output）回填转录行既有计量字段 input_tokens、cache_read_input_tokens，派生键 per_turn_input_tokens 由回填后 input 重算；context_peak_tokens 为逐轮峰值、run 末聚合不可回填，保持原值不臆造；两行均落 usage_source 来源标注键（与正常逐消息累计可区分）。逐消息累计非零时不覆盖；last_result 无 usage 时字段保持零且不异常（与 usage_missing 注记 :8243-8277 自然互斥：击杀无 result 时回填 no-op、注记照落）。

## 2. planner-plan 输出纪律

- [x] 2.1 agents/planner-plan.md：增加输出纪律条款——语义约束形态（逐轮输出以结论+证据为先、不重复叙述既有信息），MUST NOT 引入数字上限（agent-prompt-authoring 知识页规则：数字上限被模型字面执行成硬截断）；仅在非契约段追加（agent-prompt-files 修改纪律），不改动模板交付要求与其余段落。

## 3. 测试

- [x] 3.1 tests/test_run_metrics_usage_backfill.py：覆盖①逐消息全零+last_result 有用量→回填+来源标注+per_turn_input_tokens 由回填值重算；②逐消息非零→不覆盖；③last_result 无用量→字段保持零不异常；④转录行与日志侧行同源同值。
