# Run 层实时进度观测
<!-- knowledge: capability=run-progress-observability rev=1
     sources=spec/archive/2026-09-09-fix-implementer-task-progress -->

从 impl run 产物读出实时任务完成度，与 tasks.md 快照并行展示，任一数据源失效都不呈现静止的 0/N。

## 规则

- **run 层实时进度字段**：`spec_summary` 返回 `run_progress: {"done": int, "total": int}`——从最新 impl run 产物以 `parse_run_task_done` 解析（`done` = TaskUpdate completed 的 taskId 去重数，`total` = `created_count`），不依赖 TaskCreate subject 是否内嵌 tasks.md 编号；无 run 或无法解析时为 `{"done": 0, "total": 0}`（字段存在、不报错）。
- **Dashboard 并行展示**：任务进度以「tasks.md 快照 与 run 实时 并行」呈现，`tasks.md done/total` 为主刻度。当 `run_progress.done > 快照 done` 时，进度区叠加 run 完成线索（如「run 2/6 已汇报」）；当 `run_progress.done <= 快照 done`（快照已覆盖）时仅显示快照刻度，不叠加 run 线索。

## 溯源

- 2026-09-09 2026-09-09-fix-implementer-task-progress — 新增 `run_progress` 实时进度字段与「快照主刻度 + run 完成线索」并行展示，解决 TaskCreate 归并无编号时进度全盲。
