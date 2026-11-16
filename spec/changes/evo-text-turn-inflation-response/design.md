# Design: text-turn-inflation-response

## 背景锚点

- 用量链路：逐消息累计网关全零 core/agent_runner/runner.py:7329-7344；真实用量在 last_result :7374-7377；run_metrics 落盘点 :8244-8247。
- 纯文本轮判定口径：core/self_review.py:1018-1019/:1270-1291。
- 提示词装配：单文件模板独立加载 core/agent_runner/prompt_builder.py:30/:56-75/:466-474——模板间无共享片段，「共享提示词片段」假说被装配机制否定，共享层只剩模型行为本身，model/provider 对照试验归积压草稿的报告面。
- 简洁性条款先例：agents/planner-judge.md:88。
- 草稿边界：drafts/4b51f67105a7 非目标明文让出响应端（不自动改提示词/provider 路由）。

## 方案

1. 回填只在终态 metrics 落盘点做一次性读取 last_result 用量；全零判定=逐消息累计 input/output 均 0；回填字段加来源标注（如 usage_source=final_result）与正常逐消息累计区分。
2. planner-plan 条款最小化：一条输出纪律约束（逐轮输出以结论+证据为先、不重复叙述既有信息），照抄 planner-judge 先例的尺度，不改模板结构。

## 风险

- 回填与逐消息累计语义混用——来源标注+消费侧按标注过滤。
- 条款过强压缩有效推理叙述——先例尺度照抄，压降效果靠草稿报告面的对照观测回收，不做自动路由切换。