## Deliverables

```yaml
- path: agents/self-review.md
  kind: modify
- path: tests/test_self_review_timeseries_discipline.py
  kind: new
```

## 1. 纪律条款落位

- [ ] 1.1 agents/self-review.md：在「含调查评估」清单既有「归因证据边界」条款（:24）后插入新编号项「时序聚合断言回源」，原第 4 项「组织顺序」编号顺延为第 5 项（对齐前序 SPEC evo-self-review-evidence-bound-attribution 验证时的编号顺延处理）：连续/上行/回落/钉值/下界/合计类断言逐项回源当晚原始汇总行（run_metrics/延迟汇总行）或档案重算后方可落笔，断言句同附每晚原始数字与口径（整晚总量 vs 单车道分量）；转引前轮条目数字必须重新回源；无法回源时降级定性或标注未核实。
- [ ] 1.2 链路回归确认（只跑测试，不改代码）：运行既有自省 prompt 契约用例（tests/test_agent_noninteractive_contract.py 的 self_review prompt 契约、tests/test_daily_self_review.py 模板渲染相关用例），确认模板扩写不破坏 prompt 组装与渲染。

## 2. 契约测试

- [ ] 2.1 tests/test_self_review_timeseries_discipline.py：对 agents/self-review.md 原文断言两类纪律的逐字标题子串同时存在——「归因证据边界」（既有条款标题，agents/self-review.md:24 行首粗体）与「时序聚合断言回源」（新增条款标题，与任务 1.1 同名）。关键词 MUST 按模板原文逐字取自条款标题（MUST NOT 用「证据边界归因」等语序变体或缩略「时序聚合回源」，防关键词与模板不一致造成误报/漏报），防模板改写静默丢失任一条款。
