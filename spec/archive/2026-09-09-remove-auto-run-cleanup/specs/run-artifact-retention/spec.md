# run-artifact-retention 规格

## ADDED Requirements

### Requirement: 顶层产物只增不减

`.fenix/runs/` 顶层目录中的 `*.jsonl` 运行产物文件不得被任何代码按数量、时间或阈值自动删除或移动。文件从顶层消失的唯一合法途径是：所属 SPEC 被归档时移入 `.fenix/runs/archive/`。

#### Scenario: dashboard 聚合请求不触发任何产物清理

- **WHEN** 对 dashboard 发起任意次数、任意端口的 `/api/projects`、overview、spec 详情等聚合/列表请求
- **THEN** `.fenix/runs/` 顶层文件集合（文件名+数量）在请求前后完全不变
- **THEN** 无论目录中存在多少个 `.jsonl` 文件（远超历史 keep 阈值 50 亦然），不发生任何删除或移动

#### Scenario: 哨兵文件存活验证

- **WHEN** 在 `.fenix/runs/` 放置 mtime 早于现有产物的哨兵 `*.jsonl` 文件后，触发 dashboard 全部已知聚合 API
- **THEN** 哨兵文件全部存活

### Requirement: 归档唯一入口是 SPEC 归档

SPEC 归档动作（`bin/fenix_archive.py` 的 `archive_change()`）在 change 目录移动成功后，必须把 `.fenix/runs/` 顶层中属于该 spec 的产物移入 `.fenix/runs/archive/`。

#### Scenario: 归档 spec 联动归档其 run 产物

- **GIVEN** `spec/changes/<spec>` 存在，且 `.fenix/runs/` 顶层存在 `impl-<spec>-<ts>-a1.jsonl`、`planner-plan-<spec>-<ts>-a1.jsonl`、`admin-<spec>-<ts>.jsonl` 与一个不属于该 spec 的 `impl-<other>-<ts>-a1.jsonl`
- **WHEN** 执行 `python3 .fenix/bin/fenix_archive.py <spec>`
- **THEN** 三个属于 `<spec>` 的产物出现在 `.fenix/runs/archive/`，顶层不再有这三个文件
- **THEN** `impl-<other>-*.jsonl` 仍在顶层，未被移动
- **THEN** change 目录被移至 `spec/archive/YYYY-MM-DD-<spec>`（原行为不变）

#### Scenario: run 归档失败不阻断 change 归档

- **GIVEN** `.fenix/runs/` 不可写（如目录权限只读）
- **WHEN** 执行归档 `<spec>`
- **THEN** change 目录归档仍然成功（返回 `ok: true`）
- **THEN** 返回 JSON 含告警字段（`runs_archive_warning`），进程退出码为 0

### Requirement: 归档产物可回读

产物移入 archive 后，spec 详情页时间轴与运行记录仍可展示（数据源 `get_runs(include_archive=True)` 已覆盖 archive 目录）。

#### Scenario: 时间轴数据在归档后仍可读

- **GIVEN** 某 spec 的 run 产物已被归档动作移入 `.fenix/runs/archive/`
- **WHEN** 请求该 spec 的详情/时间轴数据
- **THEN** 归档产物中的 run 事件仍出现在时间轴数据中

### Requirement: 自动清理代码与配置下线

按数量裁剪的清理代码（`cleanup_runs`、`clean_old_runs`、`RUNS_KEEP` 及其转导/import）必须从生产代码中删除；`runs.keep` 配置项及其设置页 UI（「运行产物保留数量」输入项）必须同步移除，不得留下无消费方的死配置项。

#### Scenario: 全库无自动清理引用残留

- **WHEN** 全库搜索 `clean_old_runs`、`RUNS_KEEP`、`cleanup_runs`（排除 `.claude/worktrees/`、`spec/archive/` 历史文档、`node_modules/`、`dist/`、`__pycache__/`）
- **THEN** 生产代码（core/、bin/、fenixd.py）与测试代码零命中

#### Scenario: 设置页不再出现保留数量输入项

- **WHEN** 打开 dashboard 设置页「其他」分类
- **THEN** 不存在「运行产物保留数量（runs.keep）」输入项，页面无渲染错误
