# Design: add-v3-activities-page

## Context

- v1 运维记录页（`static/app.js` renderActivities ~484-560 行 + activityCard）基于 `GET /api/admin-activities`：跨项目返回 `{projects: [{name, activities[]}]}`，单项目返回 `{project, activities[]}`；未处理升级置顶高亮；页签状态为模块级变量跨刷新保持。
- v3 `/activities` 为占位页；`App.useApp()` message 体系、SSE 封装模式已在 overview/spec 列表页落地。

## Goals / Non-Goals

- Goals：v3 完整迁移 v1 运维记录功能（聚合视图、页签、置顶高亮、空态）。
- Non-Goals：不改动 `/api/admin-activities` 后端；不实现记录的再处置操作入口（处置动作属于告警横幅与后续 spec）；不做分页（v1 也是全量拉取）。

## Decisions

- **D1 数据封装**：`src/services/dashboard.ts` 新增 `getAdminActivities(project?: string)`。
- **D2 页签实现**：antd `Tabs`（items 动态生成，label 带 `Badge count`）；选中态放组件 state，SSE `alerts`/`refresh` 事件触发静默重拉时保持选中。URL 不做持久化（v1 亦为内存态），但项目消失回退"全部"的逻辑必须实现。
- **D3 记录卡片**：antd `Timeline` + `Card`/`List.Item` 组合；未处理升级（对照 v1 activityCard 的未处理判定字段）置顶并以 danger/warning 色 Tag 高亮；每条展示项目、时间、摘要/结果字段。具体字段映射以 `/api/admin-activities` 实际响应为准，实现时先打印响应结构再对齐 v1 activityCard 的取值。
- **D4 空态**：antd `Empty`，文案"暂无运维记录"。

## Risks / Trade-offs

- admin-activities 响应字段在 v1 是隐式契约（前端直取），实现时须以真实响应为准做字段映射，不凭猜测。
- 全量拉取在记录数极大时页面变长：与 v1 一致，不在本 spec 解决。

## Migration Plan

services 封装 → 页面骨架（页签+分组）→ 记录卡片（置顶高亮）→ 空态与刷新保持 → 浏览器走查 Scenario。

## Open Questions

- 无。
