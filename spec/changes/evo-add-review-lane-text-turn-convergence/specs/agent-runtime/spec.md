# agent-runtime Specification

## ADDED Requirements

### Requirement: review-output-discipline（审查车道输出纪律）

code-review 与 code-fix 车道的 run 提示词模板 SHALL 含输出纪律约束：要求模型逐轮以工具调用承载工作、结论与发现先行、压缩叙述性过渡输出、同文件多发现合并陈述，使无工具调用的纯文本回复轮占比向离群线（轮数>100 且占比>50%）以下压降。

该约束 SHALL 为提示词级语义软约束，不含任何数字长度上限；SHALL NOT 改变两车道的任务语义与产物契约（分片直写落盘、manifest 口径不变）；模板经 core/agent_runner/prompt_builder.py 既有装载点生效，装载代码 SHALL NOT 改动。

#### Scenario: code-review 模板新增输出纪律节

- **WHEN** 加载 agents/code-review.md 提示词模板
- **THEN** 模板含「输出纪律」节，形态与 agents/planner-plan.md 已落地节一致（结论+证据先行、逐轮以工具调用承载工作），且既有的审查维度、输出契约与「回复只报统计」收尾约束原样保留

#### Scenario: code-fix 模板对齐既有输出纪律节

- **WHEN** 加载 agents/code-fix.md 提示词模板
- **THEN** 既有「输出纪律」节（原 :135）被对齐到 planner-plan 形态且去重合并，模板原有的条目处置契约、验证协议与边界条款原样保留

#### Scenario: 后续观察窗无压降触发止损

- **WHEN** 后续观察窗由自省车道按 midflight-outlier-screening 既有检测复看，两车道连续 3 轮迭代纯文本轮占比无压降
- **THEN** 按 planner-plan-output-discipline.md 止损判据转模型版本对照处置（观察条目登记于 .fenix/todo.md，不属本能力实现面）
