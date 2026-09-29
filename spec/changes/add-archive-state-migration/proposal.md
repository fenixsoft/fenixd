## Why

`.fenix/STATE.md` 条目只增不减：daemon 自动归档、Dashboard 界面归档、`/fenix-archive` skill 三条归档路径都只把 `spec/changes/<name>/` 目录移入 `spec/archive/`，STATE.md 条目原样保留（fenixd 本机已达 354 条 / 12,789 行 / ~460KB）。每次状态流转与预算计数自增都是全量重写整个文件（flock 内 serialize + fsync），写放大随条目数线性恶化；调度扫描、自省等全量读者也随之变慢。需要让归档真正把条目迁出 STATE.md，同时保留「已归档」视图的可见性（条目移入归档清单，不删除）。

## What Changes

- 新增归档清单文件 `.fenix/STATE.archive.md`（格式与 STATE.md 相同：`### <name>` + 字段行），作为已迁出条目的唯一居所；迁出时在条目上追加 `archived_at`（迁出时刻 UTC ISO）与 `archived_by`（迁出路径：auto/ui/cli/backfill）。
- `core/state_machine.py` 新增迁出原语：在既有 flock 锁内原子完成「从 STATE.md 移除条目 + 追加写入归档清单」两步（清单写入失败时条目留在 STATE.md，保证不丢）。
- 三条归档路径统一收口：归档成功（目录已移入 archive/）后自动迁出 STATE.md 条目——
  - daemon 自动归档 `auto_archive_check`（每条归档成功后迁出）；
  - Dashboard 界面归档 API `archive_spec`（`POST /api/spec-archive`）；
  - `/fenix-archive` skill `bin/fenix_archive.py`。
- 幂等存量回填：daemon 周期任务对「STATE.md 有条目但活跃目录已不存在」（即既有 `is_spec_archived` 判据）的条目批量迁出，使存量已归档 SPEC（fenixd 现约 300+ 条）自动完成迁移；回填可安全重复执行。
- 读侧双源口径：
  - `is_spec_archived` 改为「活跃目录不存在 且（活跃 STATE.md 或归档清单 有该条目）」，已迁出条目仍判为已归档；
  - SPEC 列表（`/api/specs`）合并归档清单条目，「已归档」视图继续可见、可打开详情（`resolve_spec_dir` 归档回退既有能力不变）；
  - **统计口径只算活跃**：Overview/摘要统计（spec_count、task_done/task_total 等）仅基于活跃 STATE.md 条目，已迁出条目不再计入（数字缩为活跃范围，属预期行为变化）；
  - evo 撞名检查（`evolution.py` 候选名去重）改为活跃 + 清单双源，防止已迁出 SPEC 名被新 evo SPEC 重复占用后归档目录命中歧义。
- 软删除（`soft_delete_spec`）兼容清单：对条目已迁出的 SPEC，软删除同步清除清单条目与归档目录，`found` 判定含清单。
- **BREAKING**：Overview/摘要统计不再包含已迁出的已归档 SPEC（spec_count、task_total 等数值将下降）。

## Capabilities

### New Capabilities

- `archive-state-relocation`: STATE.md 条目迁出机制——归档清单文件格式、迁出原语（锁内原子两步）、三条归档路径的迁出收口、幂等存量回填、archived_at/archived_by 溯源字段。

### Modified Capabilities

- `dashboard-spec-archive`: 「归档操作后端语义」要求变化——归档成功后 STATE.md 条目迁出清单而非原样保留；「列表归档判定以目录存在性为准」扩展为目录存在性 + 双源条目合取。
- `auto-spec-archive`: 「daemon 周期检查并执行自动归档」追加迁出动作——每条归档成功后同步迁出 STATE.md 条目。
- `spec-archive`: 「原生 change 归档命令」与「fenix-archive skill」要求变化——`bin/fenix_archive.py` 归档成功后迁出 STATE.md 条目。
- `dashboard-spec-table`: SPEC 列表数据源变化——`/api/specs` 合并归档清单条目，「已归档」视图对已迁出条目仍可见、可进详情。

## Impact

- `core/state_machine.py`：迁出原语（锁内两步写）。
- `core/dashboard/data/spec_archive.py`：`archive_spec` / `auto_archive_check` / `is_spec_archived` / `soft_delete_spec` 迁出与双源改造；存量回填函数。
- `core/dashboard/data/state.py`（或同级 data 模块）：归档清单解析（复用 STATE.md 同格式解析）。
- `core/dashboard/routes/spec_routes.py`：`/api/specs` 列表合并清单条目；归档 API 透传迁出结果。
- `core/evolution.py`：候选名去重双源口径。
- `bin/fenix_archive.py`：skill 归档后迁出。
- 前端 `pages/projects`（如需）：「已归档」视图对迁出条目的既有渲染复用，预计零改或最小改（服务端合并后前端无感知）。
- 配置：**无新增配置键**（复用既有 `auto_archive_threshold`），无需 Dashboard 设置页改动。
- 回归面：pm_engine 调度扫描（活跃口径不变）、self_review、dashboard watcher/SummaryIndex（活跃口径不变）；统计数字下降属预期。
