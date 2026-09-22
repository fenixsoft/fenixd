## ADDED Requirements

### Requirement: 所有 agent 提示词携带非交互契约段

框架在构建任意 agent 的派发提示词时，SHALL 追加一段「非交互契约」（non-interactive contract）文本，声明该 agent 以 headless、无人值守方式运行、无法与人类交互。该契约段 SHALL 对**所有** agent 类型生效，包括 implementer / verifier / fast-track / planner-plan / planner-judge / spec-review / administrator / dispute-judge / self-review / evolution / repair。契约段 SHALL 由提示词构建层统一注入，使得在 agent 类型白名单中新增类型时自动继承，无需逐个修改 `agents/*.md` 模板文件。

#### Scenario: 模板型 agent 的提示词含契约段

- **WHEN** 框架构建 implementer（或 verifier / fast-track / planner-plan / planner-judge / spec-review / administrator / dispute-judge）的派发提示词
- **THEN** 返回的提示词字符串包含非交互契约段

#### Scenario: 独立构建路径的 agent 提示词含契约段

- **WHEN** 框架构建 repair / self-review / evolution（不走 `agents/*.md` 模板、由各自独立构建函数产出）的派发提示词
- **THEN** 返回的提示词字符串同样包含非交互契约段

#### Scenario: 新增 agent 类型自动继承契约段

- **WHEN** 向 agent 类型白名单新增一个 agent 类型且其模板文件存在
- **THEN** 该类型的派发提示词无需额外改动即包含非交互契约段

### Requirement: 非交互契约段的关键语义

非交互契约段 SHALL 至少包含以下规范性语义，使 agent 不产生「请求人类确认后停止」的行为：

1. 声明该 agent 运行于无人值守的 headless（`claude -p`）环境，**不存在能够回复它的人类**；
2. 要求遇到计划或分叉时**直接执行**、不请求批准，难以撤销的操作按 SPEC/tasks 授权推进并在结果文件或处置记录中留痕；
3. 禁止为「等待人类回复」而结束回合；无法继续时按该 agent 自身契约的失败/中止出口（如 `partial` / `error` / 相应终态）收工；
4. 显式声明 Claude Code 系统提示词中的 `interactive agent` 与「难以撤销的操作先确认」等默认框架，在 Fenix run 中**不适用**。

#### Scenario: 契约段声明无人类可交互

- **WHEN** 检查任意 agent 提示词中的非交互契约段
- **THEN** 该段明确声明没有能够回复该 agent 的人类、且为无人值守运行

#### Scenario: 契约段禁止等待确认

- **WHEN** 检查任意 agent 提示词中的非交互契约段
- **THEN** 该段要求直接执行而不请求批准，并禁止为等待人类回复而结束回合

#### Scenario: 契约段覆盖系统提示词默认框架

- **WHEN** 检查任意 agent 提示词中的非交互契约段
- **THEN** 该段显式声明系统提示词的 `interactive agent` 与「确认优先」默认在 Fenix run 中不适用
