# Spec Delta: implementer-task-protocol

## MODIFIED Requirements

### Requirement: TaskCreate 任务编号契约

实现者提示词 MUST 载明**可执行的**任务粒度与进度契约，且该契约 MUST 与派发路由实际具备的工具能力一致——MUST NOT 强制要求本路由不提供的工具。

**契约载体（必选，无条件生效）**：`.fenix-run-result.json` 顶层 MUST 携带 `completed_tasks` 数组（已完成任务的 tasks.md id，如 `["1.1", "2.3"]`）与可选的 `unfinished` 数组（未完成任务 id）。该清单 MUST 与 `tasks.md` 的勾选状态**一一对应**：每个 `- [x]` 数字任务在 `completed_tasks` 中恰出现一次，每个 `- [ ]` 数字任务（若以 `status: "partial"` 收工）在 `unfinished` 中恰出现一次。禁止把多条 tasks.md 任务归并为一个条目，禁止把分组标题当任务登记。

**工具可用时的附加契约（条件生效）**：当且仅当派发路由的 `init.tools` 暴露 `TaskCreate` 时，契约段 MUST 同时要求任务粒度映射——每条 tasks.md 任务只能对应一个 TaskCreate，其 subject MUST 以 `Task <tasks.md id>: <标题>` 开头（id 为「分组号.任务号」），完成瞬间 MUST 对同一 taskId 发 `TaskUpdate status=completed`，不得攒批。`init.tools` 不含 `TaskCreate` 时，提示词 MUST NOT 要求 TaskCreate/TaskUpdate，MUST 显式说明进度以 `completed_tasks` 清单为准。

**背景（实测依据）**：`.fenix/runs/` 全部 141 个 runner 派发的 run 中含真实 `TaskCreate`/`TaskUpdate` 调用的为 0，`init.tools` 含 `TaskCreate` 的仅 1 个且为非 runner 派发。故修复前该契约在每一个 run 上都被静默违反，属不可执行契约。

full 与 fast-track 两个实现分支均 MUST 注入契约段。

#### Scenario: 契约载体的覆盖

- **WHEN** 构建一个实现者 run 的 prompt（full 与 fast-track 两分支各一次）
- **THEN** 两个 prompt 文本都包含以 `completed_tasks` / `unfinished` 为进度载体的契约段（单测断言两分支）

#### Scenario: 工具可用时附加任务粒度契约

- **WHEN** 派发路由的 `init.tools` 含 `TaskCreate`
- **THEN** prompt 文本额外包含 `Task <tasks.md id>: ` 前缀契约段与 `TaskUpdate status=completed` 的即时汇报要求

#### Scenario: 工具不可用时不得要求 TaskCreate

- **WHEN** 派发路由的 `init.tools` 不含 `TaskCreate`
- **THEN** prompt 文本 MUST NOT 出现要求创建 TaskCreate 的强制语句，转而声明进度以 `completed_tasks` 清单为准

#### Scenario: 逐任务完成汇报与收尾勾选一致

- **WHEN** 实现完成、agent 收尾
- **THEN** `tasks.md` 中每条已完成任务的 `- [ ]` 被改为 `- [x]`，且 `.fenix-run-result.json` 的 `completed_tasks` 集合与全部 `- [x]` 数字任务 id 集合完全相等

#### Scenario: 未完成项如实登记

- **WHEN** agent 因预算或环境原因无法完成全部任务，以 `status: "partial"` 收工
- **THEN** 结果文件的 `unfinished` 数组恰列出全部未完成的数字任务 id，且这些任务在 `tasks.md` 中保持 `- [ ]`

### Requirement: 提示词注入点双分支

契约段 MUST 同时注入 `agent_type == "implementer"`（full）与 `agent_type == "fast-track"` 两个分支的 prompt 构建路径；两个分支的契约内容 MUST 同源生成（同一实现点产出），MUST NOT 各自维护一份文案。

#### Scenario: 双分支覆盖

- **WHEN** 分别以 full 与 fast-track 模式构建实现者 prompt
- **THEN** 两个 prompt 文本都包含完整的进度契约段（单测断言两分支）

#### Scenario: 收工自检契约同源

- **WHEN** 检查两个分支 prompt 中的收工自检段
- **THEN** 两段文本同源（由同一构造函数产出，内容逐字一致）
