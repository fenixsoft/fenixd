# 能力：review-output-discipline（审查车道输出纪律）

## 能力定义

code-review 与 code-fix 车道的 run 提示词模板包含输出纪律约束：要求模型逐轮以工具调用承载工作、结论与发现先行、压缩叙述性过渡输出、同文件多发现合并陈述，使无工具调用的纯文本回复轮占比显著低于离群线（轮数>100 且占比>50%）。

## 行为约定

- agents/code-review.md 与 agents/code-fix.md 各含一节「输出纪律」，形态与 agents/planner-plan.md 已落地节一致。
- 纪律约束为提示词级软约束，不含数字上限，不改变两车道的任务语义与产物契约（分片直写落盘、manifest 口径不变）。
- 模板经 core/agent_runner/prompt_builder.py 既有装载点生效，装载代码不改。

## 验收口径

- 两模板各含输出纪律节且与 planner-plan 先例形态一致。
- 后续观察窗由自省车道按 midflight-outlier-screening 既有检测复看两车道占比：连续 3 窗无压降按 planner-plan-output-discipline.md 止损判据转模型版本对照处置（观察条目登记于 .fenix/todo.md，不属本能力实现面）。