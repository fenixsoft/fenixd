## Deliverables

```yaml
- path: agents/code-review.md
  kind: modify
- path: agents/code-fix.md
  kind: modify
```

## 1. 输出纪律落地

- [x] 1.1 agents/code-review.md：新增「输出纪律」节，形态参照 agents/planner-plan.md 已落地的输出纪律节（结论与发现先行、证据随行）：要求逐轮以工具调用承载工作、压缩叙述性过渡语、同一文件的多个发现按去重口径合并陈述后一次输出；不得引入任何数字上限（守 spec/knowledge/domains/agent-runtime/agent-prompt-authoring.md 规则），改动后该模板经 core/agent_runner/prompt_builder.py 既有装载点生效、无需改装载代码。既有的审查维度、输出契约与 :150「回复只报统计」收尾约束 MUST 原样保留。
- [ ] 1.2 agents/code-fix.md：**对齐既有节、不新建同名节**——该模板 :135 已于 2026-09-23（4a2454707）含「输出纪律」节（「动作直接执行 / 收尾只报一行统计」）。本次将该节对齐到 planner-plan 已验证形态（结论+证据先行、逐轮以工具调用承载工作），合并去重、保留原有条目处置契约与边界条款。落盘前置事实：既有节生效期间该车道仍 4 次离群命中（60.16%/56.45%/51.28%/57.55%，turns 均>100），故本次是「形态升级 + 归因修正」而非「从无到有」；无需等待第二窗，直接随本 spec 一并落地。

## 2. 对照基线与观察交接

- [ ] 2.1 从 .fenix/runs/archive/*.jsonl 的 `"type": "run_metrics"` 事件行（**不是**终态 result 行——终态行不含 turns/text_turns/model 字段，按终态行解析会得到全 null）聚合 code-review 与 code-fix 两车道近窗 run 的 turns/text_turns/model 字段，将对照基线数值（2026-11-27 实测：code-review 14 run 顶层全 glm-5.3-flash、code-review-1795536116 另含 deepseek-flash 子面，命中 3 个；code-fix 命中 4 个，2 例 deepseek-flash 8.95%/9.09% 可作旁证）写入本规格目录的进度注记与提交说明。
- [ ] 2.2 在 .fenix/todo.md 登记后续窗观察条目：按 spec/knowledge/domains/agent-runtime/planner-plan-output-discipline.md:15 止损判据（连续 3 轮迭代占比无压降）转模型版本对照处置，由自省车道跟进。