## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_self_review_midflight.py
  kind: modify
```

## 1. 离群基线按条目归一与文本轮维度

- [ ] 1.1 core/self_review.py：_collect_metrics_outliers（约 :950-1057）对 MIDFLIGHT_BATCH_BASELINE_LANES（:785）车道的 cost_usd/duration_seconds 维改按台账条目数摊薄对比（run 值与组基线同口径换算，条目数缺失回退绝对口径），摘要行同时给摊薄前后数值；turns 维既有 P90 车道基线不动
- [ ] 1.2 core/self_review.py：新增纯文本轮占比离群维度（双条件：turns 超阈值且 text_turns 与 turns 之比超阈值，缺省 100 与 50%，常量收入 :771-785 常量区），取数用 context metrics 行原始值，实现注释写明 dashboard 索引同名字段后行胜出（core/dashboard/data/runs.py:96-104）的取数坑

## 2. run_metrics 补 model 字段

- [ ] 2.1 core/agent_runner/runner.py：context metrics 行打点（约 :6826-6862）与终态 _log_run_metrics（约 :8716，接通既有休眠形参 model）补写实际使用的模型标识，原样记录不做归一
- [ ] 2.2 core/self_review.py：第六节离群与摘要行在有 model 值时附带输出

## 3. 测试

- [ ] 3.1 tests/test_self_review_midflight.py：复刻两窗形态的批量 run（修 9 条、cost 3.401、521 秒、单条目组中位）摊薄后不标离群；摊薄显著超基线的 run 仍标离群；条目数缺失回退绝对口径
- [ ] 3.2 tests/test_self_review_midflight.py：纯文本轮双条件触发与不触发两侧用例（高轮数高占比触发、基线批 22 对 104 不触发、低轮数高占比不触发）；run_metrics 两行 model 字段落行断言