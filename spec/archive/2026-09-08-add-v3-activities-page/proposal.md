# Proposal: add-v3-activities-page

## Why

v3 dashboard「运维记录」菜单是占位页，Administrator 的跨项目处置记录在 v3 中不可见，用户仍需回退 v1 查看运维历史。将 v1 运维记录页功能迁移至 v3，完成 v3 全功能替换的又一块拼图。

## What Changes

- v3 新增 `/activities` 路由页面（替换占位组件），迁移 v1 运维记录页全部功能：
  - 跨项目聚合视图：页签（全部 + 各项目名，带条数徽标），"全部"按项目分段展示，单项目页签仅展示该项目记录；项目消失时页签回退"全部"。
  - 处置记录卡片：未处理升级置顶高亮、时间线式排版（每条含项目/结果摘要/时间等元信息）。
- 数据复用现有后端：`GET /api/admin-activities`（跨项目分组聚合）与 `GET /api/admin-activities?project=<name>`（单项目），**后端零改动**。
- 页面样式由实现方探索合适的 ant design 组件（Timeline / Card / Tabs / Badge / List 等），但须满足本文 spec 的行为 Scenario。

## Capabilities

### New Capabilities

- `v3-activities-page`: v3 运维记录页的跨项目聚合、页签切换、记录展示与置顶高亮语义。

## Impact

- **前端**：`core/dashboard/static/v3/src/pages/activities/`（替换占位页）、`src/services/dashboard.ts`（新增 admin-activities 封装）。
- **后端**：无改动。
