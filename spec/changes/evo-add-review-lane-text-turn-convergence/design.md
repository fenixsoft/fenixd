# 设计：审查车道纯文本轮输出纪律收敛

## 改动面

- agents/code-review.md（约 15921 字节，现无输出纪律节）：文件内新增「输出纪律」节。
- agents/code-fix.md（约 16494 字节，同上）：同形态新增节。
- 不改 core/agent_runner/prompt_builder.py：两模板已经由其 :56-75 装载（车道映射 :67/:59），模板改动即生效。

## 形态参照

agents/planner-plan.md:151-153 一带已落地的「输出纪律（逐轮叙述性输出约束）」节：结论+证据先行、不重复叙述、逐轮以工具调用承载工作。code-review 车道补审查语境的特有条目：同一文件多个发现按去重口径合并陈述后一次输出（避免逐发现一轮回声）；code-fix 车道补修复语境：修改说明随工具调用提交，不以纯文本轮复述 diff。

## 风险与约束

- agent-prompt-authoring 知识页明文禁止在提示词中引入数字上限——纪律条目全部为定性表述。
- 审查批次的发现去重口径须与分片直写落盘契约相容（只合并同文件同主题发现的陈述顺序，不改 {file, findings} 行结构与落盘时机）。
- code-fix 车道本窗已首窗命中（56.45%/51.28%），无第二窗等待必要，随本 spec 一并落地。

## 止损判据

沿用 spec/knowledge/domains/agent-runtime/planner-plan-output-discipline.md:15：连续 3 轮迭代（观察窗）占比无压降，转模型版本对照处置。对照基线（本 run 2.1 任务产出）预置数据面事实：code-review 车道档案全量 94/94 为 glm-5.3-flash，车道内无模型方差，模型对照只能以 code-fix 车道 3 例 deepseek（9.1%-41%）作旁证。