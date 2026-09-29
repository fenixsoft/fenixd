<!-- knowledge: capability=agent-noninteractive-contract rev=1 sources=spec/archive/2026-09-22-fix-agent-noninteractive-contract -->

# Agent 非交互运行契约

所有 agent 派发提示词统一携带的「非交互契约」段：声明 headless 无人值守语义，抑制「请求人类确认后停止」的行为。

## 现行规则

- 全类型统一注入：框架构建任意 agent 的派发提示词时，由提示词构建层统一追加非交互契约段，对全部 agent 类型生效（implementer / verifier / fast-track / planner-plan / planner-judge / spec-review / administrator / dispute-judge / self-review / evolution / repair，含不走 `agents/*.md` 模板的独立构建路径）。向类型白名单新增类型时自动继承，无需逐个修改模板文件。
- 契约段规范性语义（四条，缺一不可）：
  1. 声明该 agent 运行于无人值守的 headless（`claude -p`）环境，不存在能够回复它的人类；
  2. 遇计划或分叉直接执行、不请求批准；难以撤销的操作按 SPEC/tasks 授权推进，并在结果文件或处置记录中留痕；
  3. 禁止为「等待人类回复」而结束回合；无法继续时按该 agent 自身契约的失败/中止出口（如 `partial` / `error` / 相应终态）收工；
  4. 显式声明 Claude Code 系统提示词中的 `interactive agent` 与「难以撤销的操作先确认」等默认框架在 Fenix run 中不适用。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：agent 以 -p 非交互模式运行，结果经结构化输出与结果文件回读，不依赖交互式会话语义
- [2026-09-22 fix-agent-noninteractive-contract](spec/archive/2026-09-22-fix-agent-noninteractive-contract/) — 固化契约段构建层统一注入、全类型覆盖与四条关键语义
