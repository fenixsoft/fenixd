<!-- knowledge: capability=implementer-task-protocol rev=2 sources=spec/archive/2026-09-09-fix-implementer-task-progress,spec/archive/2026-09-19-fix-impl-tasks-completion-gate -->

# 实现者任务协议与进度登记

implementer 按 tasks.md 逐任务实现并以结果文件登记进度的协议契约：进度事实以 `tasks.md` 勾选与 `completed_tasks` 清单为载体，任务粒度契约按派发路由实际工具能力条件生效。

## 现行规则

- 进度契约载体（必选，无条件生效）：`.fenix-run-result.json` 顶层携带 `completed_tasks` 数组（已完成任务的 tasks.md id，如 `["1.1", "2.3"]`）与可选 `unfinished` 数组（未完成任务 id）。清单与 `tasks.md` 勾选状态一一对应：每个 `- [x]` 数字任务在 `completed_tasks` 中恰出现一次；以 `status: "partial"` 收工时每个 `- [ ]` 数字任务在 `unfinished` 中恰出现一次。禁止把多条 tasks.md 任务归并为一个条目，禁止把分组标题当任务登记。
- 任务粒度契约（条件生效）：当且仅当派发路由的 `init.tools` 暴露 `TaskCreate` 时，契约段同时要求——每条 tasks.md 任务只对应一个 TaskCreate，subject 以 `Task <tasks.md id>: <标题>` 开头（id 为「分组号.任务号」）；完成瞬间对同一 taskId 发 `TaskUpdate status=completed`，不攒批。`init.tools` 不含 `TaskCreate` 时，提示词不得要求 TaskCreate/TaskUpdate，并显式声明进度以 `completed_tasks` 清单为准。
- 收尾一致性：实现完成收尾时，`tasks.md` 中每条已完成任务的 `- [ ]` 被勾为 `- [x]`，勾选集合与 `completed_tasks` 完全相等（该对账由 `impl-tasks-completion-gate` 硬门强制）。
- 注入点：契约段同时注入 `implementer`（full）与 `fast-track` 两个 prompt 构建分支，两分支契约内容同源生成、逐字一致。

## 溯源

- 史前复原（早于 2026-09-09） — 基线形态：implementer 按 tasks.md 逐任务实现、完成即勾选，并按交付物声明收口；tasks.md 勾选是任务完成的事实记录
- 2026-09-09 2026-09-09-fix-implementer-task-progress（spec/archive/2026-09-09-fix-implementer-task-progress） — 确立 TaskCreate 任务编号契约（subject 前缀、逐任务完成汇报）与 full/fast-track 双分支注入
- 2026-09-19 2026-09-19-fix-impl-tasks-completion-gate（spec/archive/2026-09-19-fix-impl-tasks-completion-gate） — 契约载体改为 `completed_tasks`/`unfinished` 结果文件清单（与工具可用性解耦），TaskCreate 契约降为条件生效
