# planner-plan 车道输出纪律

<!-- knowledge: capability=planner-plan-output-discipline rev=2
     sources=spec/changes/evo-text-turn-inflation-response,spec/changes/evo-add-review-lane-text-turn-convergence -->

planner-plan 提示词模板的逐轮叙述性输出约束：压降纯文本轮（无工具调用的模型回复轮）的叙述膨胀，是文本轮膨胀的提示词层响应手段。检测观测面见 [self-review-midflight-signals](../self-evolution/self-review-midflight-signals.md)。

## 规则

- agents/planner-plan.md 模板含「输出纪律」条款：逐轮输出以结论+证据为先——每轮先给结论/决策，再附支撑它的最小证据（文件:行号、命令输出关键行、场景 id），不重复叙述既有信息（上一轮已给出的分析、场景文件已承载的完整内容、任务书原文）。
- 过程性长文（完整文件回读、大段日志、逐条枚举）改为引用路径或关键行摘录，完整内容由落盘产物承担。
- 条款为语义约束形态，不含数字上限——数字上限会被模型字面执行成硬截断（见 [agent-prompt-authoring](agent-prompt-authoring.md)），同形态先例 planner-judge 模板的 ≤300 字符上限不照抄。
- 条款在模板非契约段追加，不改交付要求与其余段落（见 [agent-prompt-files](agent-prompt-files.md) 修改纪律）。
- 适用范围：planner-plan 车道模板含该条款；code-review 与 code-fix 车道模板另有各自语境的同形态输出纪律节（见 [review-lane-output-discipline](review-lane-output-discipline.md)）；其余车道模板（admin/arbiter 等）无。
- 压降验证靠观测对照，不做自动 provider 路由切换；提示词路线连续 3 轮迭代无压降即按 agent-prompt-authoring 止损判据转架构处置（机械化/provider 路由层），不在提示词层继续迭代。

## 代码锚点

- 主实现：agents/planner-plan.md（「输出纪律（逐轮叙述性输出约束）」段）
- 装载机制：core/agent_runner/prompt_builder.py（`_load_agent_template` 单文件整读、无共享片段拼接——条款随模板整体生效）
- 同形态先例：agents/planner-judge.md（简洁性条款）

## 溯源

- 2026-11-17 evo-text-turn-inflation-response（spec/changes/evo-text-turn-inflation-response/） — 新增本页：planner-plan 模板追加输出纪律条款（语义约束、不设数字上限），压缩逐轮叙述性输出以压降纯文本轮上下文膨胀
- 2026-11-27 evo-add-review-lane-text-turn-convergence（spec/changes/evo-add-review-lane-text-turn-convergence/） — 修订本页适用范围表述：同形态输出纪律扩展至 code-review/code-fix 两车道（各自语境条目独立成页），本页止损判据被两车道复用为对照处置出口
