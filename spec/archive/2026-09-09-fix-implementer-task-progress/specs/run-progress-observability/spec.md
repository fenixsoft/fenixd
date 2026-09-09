## ADDED Requirements

### Requirement: run 层实时进度字段

`spec_summary` 返回新增字段 `run_progress: {"done": int, "total": int}`：
- 从最新 impl run 产物用 `parse_run_task_done` 解析（`done` = TaskUpdate completed 的 taskId 去重数，`total` = `created_count`）；
- 不依赖 TaskCreate subject 是否内嵌 tasks.md 编号；
- 无 run / 无法解析时为 `{"done": 0, "total": 0}`。

#### Scenario: 无编号 run 也能出进度
- **WHEN** 某 spec 最新 impl run 有 6 个 TaskCreate、1 个 completed（subject 无编号）
- **THEN** `/api/specs` 响应中该 spec 的 `run_progress` 为 `{"done":1,"total":6}`（而非全 0）

#### Scenario: 无 run 缺省
- **WHEN** spec 从无 impl run 记录
- **THEN** `run_progress` 为 `{"done":0,"total":0}`，响应字段存在且不报错

### Requirement: Dashboard 任务进度并行展示

任务进度展示为「tasks.md 快照 与 run 实时 并行」：`tasks.md done/total` 为主刻度；
当 `run_progress.done > 快照 done` 时，进度区叠加显示 run 完成线索（如 `run 1/6 已汇报`），
任一数据源失效都不再呈现静止的 0/N。

#### Scenario: 快照 0 但 run 推进仍可见
- **WHEN** tasks.md 快照 0/N、但 `run_progress={done:2,total:6}`，前端渲染任务进度区
- **THEN** 页面显示主刻度 0/N 且伴随 run 完成线索（含 2/6），不再是静止 0/N

#### Scenario: 快照与 run 一致时不重复打扰
- **WHEN** `run_progress.done <= 快照 done`（快照已覆盖 run 完成度）
- **THEN** 仅显示快照刻度，不叠加 run 线索