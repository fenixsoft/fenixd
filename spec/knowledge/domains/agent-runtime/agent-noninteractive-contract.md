<!-- knowledge: capability=agent-noninteractive-contract rev=2 sources=spec/archive/2026-09-22-fix-agent-noninteractive-contract,spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md -->

# Agent 非交互运行契约

所有 agent 派发提示词统一携带的「非交互契约」段：声明 headless 无人值守语义，抑制「请求人类确认后停止」的行为。

## 现行规则

- 全类型统一注入：框架构建任意 agent 的派发提示词时，由提示词构建层统一追加非交互契约段，对全部 agent 类型生效（implementer / verifier / fast-track / planner-plan / planner-judge / spec-review / administrator / dispute-judge / self-review / evolution / repair，含不走 `agents/*.md` 模板的独立构建路径）。向类型白名单新增类型时自动继承，无需逐个修改模板文件。
- 契约段规范性语义（四条，缺一不可）：
  1. 声明该 agent 运行于无人值守的 headless（`claude -p`）环境，不存在能够回复它的人类；
  2. 遇计划或分叉直接执行、不请求批准；难以撤销的操作按 SPEC/tasks 授权推进，并在结果文件或处置记录中留痕；
  3. 禁止为「等待人类回复」而结束回合；无法继续时按该 agent 自身契约的失败/中止出口（如 `partial` / `error` / 相应终态）收工；
  4. 显式声明 Claude Code 系统提示词中的 `interactive agent` 与「难以撤销的操作先确认」等默认框架在 Fenix run 中不适用。
- 生命周期语义（非交互环境的等待面）：`claude -p` 非交互模式下 turn 结束即主进程退出，「等待通知」「等待批次完成」在非交互模式不存在。Task/async 子代理必须同步回收（发起轮内拿结果）；批量场景走分片直写 + 读侧聚合，不走异步结果回收。
- 后台任务等待语义：daemon 一次性派发下后台 Bash 完成通知从不送达——按「等待通知」收工等价于启动即忘（turn 结束进程退出、后台子进程随之被杀），产物以 partial 占位诱发重派循环。涉及后台任务的 agent MUST 轮询文件产物（读输出文件确认完成或失败），不依赖任何完成通知。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：agent 以 -p 非交互模式运行，结果经结构化输出与结果文件回读，不依赖交互式会话语义
- 2026-09-22 fix-agent-noninteractive-contract（spec/archive/2026-09-22-fix-agent-noninteractive-contract） — 固化契约段构建层统一注入、全类型覆盖与四条关键语义
- 2026-11-04 memory-distill-agent-prompt-rules（spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md） — 折叠非交互模式生命周期语义（turn 结束即进程退出、async 子代理同步回收或分片直写+读侧聚合）与后台任务等待语义（完成通知从不送达，MUST 轮询文件产物）
