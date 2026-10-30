## Deliverables

```yaml
- path: agents/self-review.md
  kind: modify
- path: tests/test_self_review_timeseries_discipline.py
  kind: new
```

## 1. 纪律条款落位

- [ ] 1.1 agents/self-review.md：在既有证据边界归因条款（:24 附近）后追加「时序聚合断言回源」条款：连续/上行/回落/钉值/下界/合计类断言逐项回源当晚原始汇总行（run_metrics/延迟汇总行）或档案重算后方可落笔，断言句同附每晚原始数字与口径（整晚总量 vs 单车道分量）；转引前轮条目数字必须重新回源；无法回源时降级定性或标注未核实。

## 2. 契约测试

- [ ] 2.1 tests/test_self_review_timeseries_discipline.py：断言 agents/self-review.md 同时含「证据边界归因」与「时序聚合回源」两类纪律的关键词（防模板改写静默丢失任一条款）。