# 审查/修复车道输出纪律

<!-- knowledge: capability=review-lane-output-discipline rev=1
     sources=spec/changes/evo-add-review-lane-text-turn-convergence -->

code-review 与 code-fix 车道提示词模板的逐轮叙述性输出约束：压降纯文本轮（无工具调用的模型回复轮）占比，是文本轮膨胀响应机制在这两条车道的提示词层落点。检测观测面见 [self-review-midflight-signals](../self-evolution/self-review-midflight-signals.md)，planner-plan 车道的同形态纪律见 [planner-plan-output-discipline](planner-plan-output-discipline.md)。

## 规则

- **两模板均含「输出纪律」节**：形态对齐 planner-plan 已验证形态——逐轮以工具调用承载工作、结论与发现先行、压缩叙述性过渡输出。约束为提示词级语义软约束，不含任何数字长度上限（数字上限会被模型字面执行成硬截断，见 [agent-prompt-authoring](agent-prompt-authoring.md)）。
- **code-review 语境条目**：同一文件多个发现按去重口径合并陈述后一次输出（避免逐发现一轮回声）；合并只影响陈述顺序，分片直写落盘的行结构与落盘时机不变；既有审查维度、输出契约与「回复只报统计」收尾约束原样保留。
- **code-fix 语境条目**：修改说明随工具调用提交，不以纯文本轮复述 diff；既有「输出纪律」节对齐到 planner-plan 形态并与「动作直接执行/收尾只报统计」条款去重合并，MUST NOT 同标题双节；条目处置契约、验证协议与边界条款原样保留。
- **任务语义与产物契约不变**：纪律节不改变两车道的任务语义与产物契约（分片直写落盘、manifest 口径原样）；模板经 prompt_builder 既有装载点生效，装载代码零改动。
- **止损判据**：观察窗由自省车道按既有离群检测复看，某车道连续 3 轮迭代纯文本轮占比无压降，即转模型版本对照处置（沿用 planner-plan 输出纪律的止损规则），不在提示词层继续迭代；对照基线由观察条目登记跟踪。

## 代码锚点

- 主实现：`agents/code-review.md`、`agents/code-fix.md`（「输出纪律（逐轮叙述性输出约束）」节）
- 装载机制：`core/agent_runner/prompt_builder.py`（模板整读装载，条款随模板整体生效）

## 溯源

- 2026-11-27 evo-add-review-lane-text-turn-convergence（spec/changes/evo-add-review-lane-text-turn-convergence/） — 新建本能力：输出纪律形态扩展到 code-review（新增纪律节）与 code-fix（既有 2026-09-23 节对齐升级到 planner-plan 已验证形态并去重合并，非从无到有——既有节生效期间该车道仍 4 次离群命中）；登记对照基线与止损判据（动因：纯文本轮离群维两车道多窗命中——code-review 50.47%/58.23%/50.48%、code-fix 56.45%/51.28%/60.16%/57.55%，轮数>100 且占比>50%）
