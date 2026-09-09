## ADDED Requirements

### Requirement: TaskCreate 任务编号契约

implementer prompt 强制任务粒度契约：每条 tasks.md 任务只能对应一个 TaskCreate；
TaskCreate 的 subject MUST 以 `Task <tasks.md id>: <标题>` 开头（id 为「分组号.任务号」，如 `Task 1.3: ...`）；
禁止把多条 tasks.md 任务归并为一个 TaskCreate，禁止把分组标题当任务创建。

full 与 fast-track 两个 implementer 分支均注入契约段。

#### Scenario: subject 前缀校验
- **WHEN** evaluate 一个新实现 run 的 TaskCreate 事件（构建装订 prompt 后派发一条测试指令）
- **THEN** prompt 文本包含 `Task ${tasks.md id}:` 字样契约段；任务书 id 与 subject 前缀一一对应

#### Scenario: 逐任务完成汇报
- **WHEN** implementer 完成一条 tasks.md 任务
- **THEN** 该任务的 TaskCreate 对应 taskId 立即收到 TaskUpdate status=completed（run 产物断言：completed 数量 == 已完成任务数，无攒批）

#### Scenario: 收尾勾选一致
- **WHEN** 实现完成，agent 收尾
- **THEN** tasks.md 中每条 while 已完成任务的 `- [ ]` 被改为 `- [x]`，勾选项与全部 TaskUpdate completed 的记录一一对应

### Requirement: 提示词注入点双分支

契约段同时注入 `agent_type == "implementer"`（full）与"fast-track"分支的 prompt 构建路径。

#### Scenario: 双分支覆盖
- **WHEN** 分别以 full 与 fast-track 模式构建 implementer prompt
- **THEN** 两个 prompt 文本都包含任务编号契约段（单测断言两分支）