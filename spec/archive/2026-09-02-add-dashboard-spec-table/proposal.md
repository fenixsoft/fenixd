# Proposal: Dashboard 项目 SPEC 列表 —— 表格化 + 创建时间排序 + 前端过滤

## Why

Dashboard 项目视图（`renderProject`）当前用 `.spec-row` div 平铺渲染 SPEC 列表：无表头说明各列含义、无创建时间展示、按服务端 (非pushed, priority) 排序而非创建时间、无任何过滤能力。用户在浏览大量 SPEC 时难以快速定位（按名称找、按状态筛）与理解各字段含义。希望：

1. 按 SPEC **创建时间排序**（新在前）。
2. 改为**带表头的表格**，说明每一列含义。
3. 提供**前端过滤**：按名称关键字搜索 + 按状态过滤。

## What Changes

- **数据层**：`core/dashboard/data.py::spec_summary` 暴露 `created` / `updated` 字段（`STATE.md` 条目中已有，当前 API 响应未包含），供前端排序与展示。
- **服务端排序**：`core/dashboard/server.py::_api_specs` 默认排序由「(非 pushed, priority)」改为「创建时间倒序（新在前）」，缺失 `created` 的 SPEC 排到最后。
- **前端表格化**：`core/dashboard/static/app.js::renderProject` 由 spec-row div 改为真正的 `<table>`，`<thead>` 表头逐列说明含义：状态 / 名称 / 优先级 / 创建时间 / 任务进度 / 验证进度 / 错误。
- **前端过滤**：项目视图新增过滤条——名称关键字输入框（大小写不敏感、包含匹配）+ 状态下拉框（全部状态 / 各状态）。过滤为纯前端，基于已排序数组过滤，保留排序顺序；过滤结果为空时展示「无匹配的 SPEC」。
- **刷新保持**：2 秒自动刷新时，过滤输入与选择状态保持不变（前端过滤状态在重渲染间持久化）。

## Capabilities

### New Capabilities

- `dashboard-spec-table`: 项目 SPEC 列表以带表头表格展示、按创建时间倒序、前端按名称关键字与状态过滤（过滤状态在自动刷新间保持）。

### Modified Capabilities

<!-- 现有 openspec/specs/ 与归档目录均无已定义能力，本次全部为新增。 -->

## Impact

- **代码**：
  - `core/dashboard/data.py`：`spec_summary` 增加 `created` / `updated`。
  - `core/dashboard/server.py`：`_api_specs` 排序改为创建时间倒序。
  - `core/dashboard/static/app.js`：`renderProject` 表格化 + 表头；新增过滤条（名称 + 状态）与前端过滤逻辑；过滤状态跨刷新保持。
  - `core/dashboard/static/style.css`：表格与过滤条样式（沿用现有设计语言，如 `.spec-row`、状态 pill、进度条）。
- **API**：`/api/specs` 响应项新增 `created` / `updated` 字段（向后兼容，新增字段不影响现有消费）。
- **测试**：`tests/test_core.py` 或前端行为验证：`spec_summary` 含 created；`/api/specs` 排序为创建时间倒序；浏览器验证表格渲染、表头、名称/状态过滤与刷新保持。
