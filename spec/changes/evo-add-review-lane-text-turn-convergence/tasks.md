## Deliverables

```yaml
- path: agents/code-review.md
  kind: modify
- path: agents/code-fix.md
  kind: modify
```

## 1. 输出纪律落地

- [ ] 1.1 agents/code-review.md：新增「输出纪律」节，形态参照 agents/planner-plan.md 已落地的输出纪律节（结论与发现先行、证据随行）：要求逐轮以工具调用承载工作、压缩叙述性过渡语、同一文件的多个发现按去重口径合并陈述后一次输出；不得引入任何数字上限（守 spec/knowledge/domains/agent-runtime/agent-prompt-authoring.md 规则），改动后该模板经 core/agent_runner/prompt_builder.py 既有装载点生效、无需改装载代码。
- [ ] 1.2 agents/code-fix.md：同形态新增「输出纪律」节（code-fix 车道本窗已首窗命中 56.5%/51.3%，无需等待第二窗，直接随本 spec 一并落地）。

## 2. 对照基线与观察交接

- [ ] 2.1 从 .fenix/runs/archive/ 终态行聚合 code-review 与 code-fix 两车道近窗 run 的 turns/text_turns/model 字段，将对照基线数值（含 code-review 车道 94/94 全 glm-5.3-flash、车道内无模型方差，对照仅 code-fix 3 例 deepseek 可作旁证的事实）写入本规格目录的进度注记与提交说明。
- [ ] 2.2 在 .fenix/todo.md 登记后续窗观察条目：按 spec/knowledge/domains/agent-runtime/planner-plan-output-discipline.md:15 止损判据（连续 3 轮迭代占比无压降）转模型版本对照处置，由自省车道跟进。