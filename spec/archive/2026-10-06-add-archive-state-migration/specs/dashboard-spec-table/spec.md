## ADDED Requirements

### Requirement: 列表合并归档清单条目

spec 列表 API（`GET /api/specs`）SHALL 在活跃 STATE.md 条目之外，合并归档清单 `.fenix/STATE.archive.md` 中的条目（并集，同名单侧重复时活跃侧优先），使条目已迁出的已归档 SPEC 继续出现在列表中且 archived=true。清单条目 SHALL 透迁出前的既有字段（status、created、updated、优先级等）与 `archived_at`/`archived_by` 溯源字段；前端「已归档」视图对这些行的渲染 SHALL 复用既有展示（状态、任务进度、文档按钮等），文档与任务进度经既有归档目录回退读取。默认「未归档」视图 SHALL NOT 出现清单条目；概览统计口径不受本合并影响（统计只算活跃）。

#### Scenario: 已迁出 SPEC 仍在已归档视图可见

- **WHEN** 某 SPEC 条目已迁出清单，用户切换到「已归档」视图
- **THEN** 该 SPEC 行正常显示（状态、进度与迁出前一致），可点击进入详情并查看文档

#### Scenario: 未归档视图不含清单条目

- **WHEN** 用户停留在默认「未归档」视图
- **THEN** 列表仅含活跃未归档 SPEC，无清单条目

#### Scenario: 双源同名单不重复

- **WHEN** 迁出失败导致某 SPEC 条目同时存在于活跃 STATE.md 与清单（回填未跑的中间态）
- **THEN** 列表该名称只出现一行（活跃侧字段优先），无重复行
