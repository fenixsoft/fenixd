# Run 产物保留策略
<!-- knowledge: capability=run-artifact-retention rev=1
     sources=spec/archive/2026-09-09-remove-auto-run-cleanup -->

run 产物的数据生命周期绑定 SPEC 生命周期：顶层产物只增不减，归档的唯一入口是所属 SPEC 被归档，杜绝匿名进程按数量裁剪生产数据。

## 规则

- **顶层产物只增不减**：`.fenix/runs/` 顶层的 `*.jsonl` 运行产物不得被任何代码按数量、时间或阈值自动删除或移动；文件从顶层消失的唯一合法途径是所属 SPEC 被归档时移入 `.fenix/runs/archive/`。任何 dashboard 聚合/列表请求（任意次数、任意端口）不得改变顶层文件集合。
- **归档唯一入口是 SPEC 归档**：SPEC 归档动作（`bin/fenix_archive.py` 的 `archive_change()`）在 change 目录移动成功后，把 `.fenix/runs/` 顶层属于该 spec 的产物移入 `.fenix/runs/archive/`；不属于该 spec 的产物不动。run 归档失败不阻断 change 归档（返回 `ok: true` + `runs_archive_warning`，退出码 0）。
- **归档产物可回读**：spec 详情页时间轴与运行记录的数据源 `get_runs(include_archive=True)` 覆盖 archive 目录，产物移入归档后照常展示。
- **自动清理链路全量下线**：按数量裁剪的清理代码（`cleanup_runs`、`clean_old_runs`、`RUNS_KEEP` 及其转导/import）从生产代码与测试代码中删除；`runs.keep` 配置项及设置页「运行产物保留数量」输入项同步移除，不留无消费方的死配置。

## 溯源

- 史前基线 — runs 产物按保留策略清理，转录与结果文件限期保留，防磁盘无限膨胀。
- 2026-09-09 2026-09-09-remove-auto-run-cleanup — 按数量保留的自动清理基线已随该归档废除；改立「顶层只增不减、归档唯一入口是 SPEC 归档」，并同步删除清理代码与 runs.keep 配置及设置页输入项。
