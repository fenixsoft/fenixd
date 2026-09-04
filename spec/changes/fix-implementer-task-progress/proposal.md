# Fix Implementer Task Progress

## Why

Dashboard 任务进度对基于 Claude Tasks 工具的 implementer run 完全不可见：tasks.md 永远 0/N。

实测根因链（以 add-dashboard-incremental-data run 为例，从 run 产物查证）：

1. **implementer 归并任务粒度**：prompt 第 2 步「identify the next unchecked task」未约束任务粒度，agent 把 tasks.md 的 27 条任务归并为 6 个分组级 TaskCreate（subject 如 `Implement watcher incremental broadcast + directory signature skip`），不含 tasks.md 编号。
2. **`parse_run_task_done` 的 `done_ids` 提取依赖 `_TASK_ID_RE`**（subject 内嵌 `Task 1.1` 编号）——归并后的 subject 匹配为空 → 两条消费路径全部空转：
   - dashboard 侧写叠加（data.py `parse_tasks` live 叠加）→ 快照 0 勾选；
   - 写侧回写（engine.py `_sync_task_progress`，`done_ids` 为空直接跳过，`dispatch.py:721`）→ tasks.md 永不落盘。
3. **无兜底**：run 层实际完成度（TaskUpdate completed 数）已存在 harness 事件中，但没有任何层把它展示出来。

影响：用户无法在 Dashboard 分辨「spec 卡死」与「在正常实现但进度不可见」，代价是误判重派烧 token（与交付物守卫误判同类事故）。

## What Changes

1. **提示词契约化（根治）**：`prompt_builder.py` implementer 分支增加「任务编号契约」强制段——
   - TaskCreate 的 subject 必须以 `Task <tasks.md id>: <desc>` 开头（id 直接取自 tasks.md 的分组号.任务号，如 `Task 1.2: <描述>`），禁止归并多个 tasks.md 任务为一个 TaskCreate；
   - 一个 tasks.md 任务只对应一个 TaskCreate，完成立即 `TaskUpdate completed`（不许攒批）；
   - 保留收尾勾选（第 6 步）并强化为「逐项核对勾选 tasks.md 与已完成任务一一对应」。
2. **回写兜底增强**：`_sync_task_progress` 在 `done_ids` 为空时不再直接跳过——用 `flat_done`（harness 创建序完成下标）回退：按创建序勾选 tasks.md 中前 N 个未完成项；有 `done_ids` 时优先精确对齐。
3. **run 层进度可见性（兜底显示）**：`spec_summary` 新增 `run_progress: {done, total}`（从最新 impl run 解析 TaskUpdate completed/created，不依赖 tasks.md 编号）；Dashboard 任务进度列展示「tasks.md 快照 与 run 实时 叠加」的并集语义，任意数据源失效都能看到推进。

## Capabilities

### New Capabilities
- `implementer-task-protocol`: implementer 提示词任务编号契约——subject 带 tasks.md id、逐任务粒度、完成即汇报
- `task-progress-writeback`: 写侧回写兜底——done_ids 空时 flat_done 回退，收尾把完成状态同步进主树 tasks.md
- `run-progress-observability`: dashboard run 层实时进度字段与展示——不依赖 tasks.md 编号的推进可见性

### Modified Capabilities
- 无（`_sync_task_progress` 属实现层行为扩展，不改既有 API 契约）

## Impact

- **代码**：`core/agent_runner/prompt_builder.py`（提示词）、`core/pm_engine/engine.py`（`_sync_task_progress` 兜底）、`core/dashboard/data.py`（`spec_summary` 增加 `run_progress` 字段）
- **构建产物**：`core/dashboard/static/v3/dist/` 需重建并提交（任务进度列表/详情展示扩展）
- **行为影响**：提示词修改影响**所有后续 implementer run**（当前进行中的 run 用旧提示词不受扰动）；回写兜底只增不减，`done_ids` 精确对齐路径行为不变
- **依赖**：无新增（D2 保持）