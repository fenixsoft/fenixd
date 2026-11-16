# Design: text-turn-inflation-response

## 背景锚点

- 用量链路：逐消息累计仅 input/cache_read 两字段（无 output 载体）core/agent_runner/runner.py:7377-7418；真实用量在 last_result（result 事件 :7440-7441）；run_metrics 落盘收尾块=转录行 :8306-8344 + 同块日志侧行 :8357-8397（两 sink 同源）；usage_missing 注记 :8243-8277（击杀无 result 时落，与回填 no-op 自然互斥）。
- 纯文本轮判定口径：core/self_review.py:1018-1019/:1270-1291。
- 提示词装配：单文件模板独立加载 core/agent_runner/prompt_builder.py:30/:56-75/:466-492（`_load_agent_template` 整文件读入、无共享片段拼接）——「共享提示词片段」假说被装配机制否定，共享层只剩模型行为本身，model/provider 对照试验归报告面。
- 简洁性条款先例：agents/planner-judge.md:88（注意：该先例含 ≤300 字符数字上限，按 agent-prompt-authoring 知识页规则本 spec 不照抄数字上限，仅取「模板内落输出纪律条款」的形态与位置）。
- 草稿边界：drafts/4b51f67105a7 非目标明文让出响应端（不自动改提示词/provider 路由）；评审时点注记：该草稿队列已清空且未晋升 spec/changes、台账已剪除（留痕 .fenix/evolution/.build/emit_4d7b35560107.py），报告面承接载体暂不在案。

## 方案

1. 回填只在终态 metrics 落盘收尾块做一次性读取 last_result 用量；全零判定=逐消息累计 input/cache_read 均 0（累计侧无 output 载体）；回填字段=转录行既有计量键 input_tokens、cache_read_input_tokens（派生键 per_turn_input_tokens 由回填后 input 重算；context_peak_tokens 为逐轮峰值不可由 run 末聚合回填，保持原值不臆造）；来源标注 usage_source 键在转录行与日志侧行同落，消费侧按标注过滤。
2. planner-plan 条款最小化：一条输出纪律约束（逐轮输出以结论+证据为先、不重复叙述既有信息），语义约束形态、不引入数字上限（agent-prompt-authoring 规则 1：数字上限被模型字面执行成硬截断——先例的 ≤300 字符不照抄）；不改模板结构，仅在非契约段追加。

## 风险

- 回填与逐消息累计语义混用——来源标注+消费侧按标注过滤；全零判定保证单 run 内不混源（要么全零走回填、要么非零保持逐消息累计）。
- 条款过强压缩有效推理叙述——语义约束（结论+证据为先）不设数字上限，压降效果靠报告面对照观测回收，不做自动路由切换；提示词路线若连续 3 轮迭代无压降，按 agent-prompt-authoring 止损判据转架构处置（机械化/路由层），不在提示词层继续迭代。
- 承接载体时点注记：4b51f67105a7 评审时点已不在队列（drafts/ 空、未晋升 spec/changes、台账剪除，仅 .build emit 留痕）——「对照报告面」暂无在案承接载体，压降效果观测暂由档案级复核既有窗口承担，报告面后续另行立项承接；不影响本 spec 两交付成立。
