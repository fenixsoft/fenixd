# remove-auto-run-cleanup

## Why

2026-09-03 发生第二起 runs 删空事故：4 个调试脚本泄漏的孤儿 dashboard 实例（8-25/8-29 启动，跑 8 月底旧码：`RUNS_KEEP=20` 且直接 unlink 无归档）注册着真实项目，任何一次 API 轮询触发 `project_summary → cleanup_runs` 即对 `.fenix/runs/` 执行"保留 20 直接删除"。add-done-duration-persist 等 9-3 14:41 前的全部 run 产物被滚动删除、时间轴永久丢失、无法恢复。

自动清理的破坏性在多实例/旧码并存的现实下无法兜底（删除动作发生在任意持有旧码的进程里，新码的归档机制拦不住）。取保留策略：**runs 顶层产物只增不减，归档的唯一入口是该 spec 被归档**——把数据生命周期绑定到 SPEC 生命周期，消灭"匿名进程按数量裁剪生产数据"这一整类风险。

## What Changes

- **移除自动清理链路**：删除 `cleanup_runs`（含 60s 节流、active_ids 保护集、runs.keep 配置读取）及其唯一生产调用点（`project_summary` 内）；删除 `clean_old_runs`（按数量裁剪语义）与 `RUNS_KEEP` 常量及所有转导/未用 import。
- **归档唯一入口 = spec 归档**：`bin/fenix_archive.py` 的 `archive_change()` 在 change 目录移动成功后，新增动作——把 `.fenix/runs/` 顶层中属于该 spec 的 run 产物移入 `.fenix/runs/archive/`（不删除任何文件）。
- **run_id→spec 推断单一实现**：把 `_run_spec_part` 从 `core/dashboard/data.py` 迁至 `core/agent_runner/run_files.py`（供归档脚本与 dashboard 共用，保持 agent_runner 不依赖 dashboard 的分层方向），data.py 改为 import。
- **runs.keep 配置项同步下线**：设置页「其他」分类的「运行产物保留数量」输入项删除（MiscSettingsPanel.tsx + dashboard.ts 服务层），后端 config 溯源映射同步清理；重建 dist 并提交。
- 时间轴/运行记录回读零变化：`get_runs(include_archive=True)` 已读 archive/，产物移入归档后 spec 详情页时间轴照常展示。

## Capabilities

### New Capabilities
- `run-artifact-retention`: run 产物保留策略——顶层产物只增不减，归档唯一入口是所属 SPEC 被归档，禁止按数量/时间的自动清理

### Modified Capabilities

## Impact

- `core/dashboard/data.py`：删除 `cleanup_runs`、`_CLEANUP_RUNS_*` 节流常量、`RUNS_KEEP`、`project_summary` 内调用、runs.keep 溯源映射（~2377/~2416）；`_run_spec_part` 迁出后改为 `from core.agent_runner.run_files import run_spec_part`。
- `core/agent_runner/run_files.py`：删除 `clean_old_runs`/`RUNS_KEEP`，新增 `run_spec_part(run_id)`（自 data.py 迁入）与 `archive_spec_runs(runs_dir, spec_name)`。
- `core/agent_runner/__init__.py` / `runner.py`：导出与门面转导同步（clean_old_runs 移除、新函数加入）。
- `core/agent_runner/liveness.py`：删除未使用的 `clean_old_runs`/`RUNS_KEEP` import（仅 import 未调用）。
- `bin/fenix_archive.py`：`archive_change()` 挂钩 run 归档动作（sys.path 注入 project_root 后复用 run_files 实现；归档动作失败仅告警不阻断 change 归档）。
- `core/dashboard/static/src/pages/settings/components/MiscSettingsPanel.tsx` + `static/src/services/dashboard.ts`：runs.keep 输入项与服务层注释/类型同步删除；dist 重建提交（漏重建=UI 验证全量假阴性）。
- `tests/`：删除 cleanup_runs/clean_old_runs 相关用例（test_dashboard_index.py 等），新增 archive_spec_runs 与归档挂钩用例。
- 受影响 spec：add-run-archive（archive/ 内历史 spec，行为由本 spec 接管）；add-done-duration-persist 的回退求和路径（`spec_summary` 对无 total_duration 字段的 done spec 仍从 run 产物求和——run 产物现在永不自动淘汰，回退路径可靠性提升，无需改动）。
