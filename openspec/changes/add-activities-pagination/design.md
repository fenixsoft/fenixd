# 设计 — 运维记录页容量控制与结构简化

## Context

v3 运维记录页（`core/dashboard/static/src/pages/activities/index.tsx`）当前按项目页签组织：「全部」+ 每项目页签，均带条数 Badge；记录以 Timeline 全量一次渲染，无分页；人工告警面板（AlertPanel）嵌在项目页签内靠 Radio 切换，已解决告警默认折叠。数据源 `/api/admin-activities`（跨项目聚合，响应 `projects[].activities`）与 `/api/alerts`（聚合带 `project` 字段）由 `core/dashboard/server.py` 提供；存储层 `core/admin_store.py` 已有 150 条/项目硬上限（`MAX_RECORDS`），数据体量有界（实测主项目 150 条 / 288KB）。

## Goals / Non-Goals

**Goals:**

- 运维事件 Timeline 分页：每页 15 条，首屏仅渲染最新 15 条，翻页时渲染其余
- 取消项目页签与条数 Badge，改为全局一份「自动运维 / 人工告警」Radio 切换
- 人工告警合并为全局视图，「已解决」Collapse 默认展开
- 保持既有语义：未处理升级置顶高亮、「标记已处理」乐观更新、SSE 实时刷新

**Non-Goals:**

- 后端接口变更（`/api/admin-activities`、`/api/alerts` 响应结构不动）
- 存储层留存策略调整（150 条上限、signal/disposition 共享池不在本次范围）
- 单项目过滤视图（页签取消后如有需要另行立项）
- AdminRunModal「查看处置过程」行为不变

## Decisions

**D1 前端分页，不做后端分页** — 存储层已有 150 条/项目硬上限，全量拉取的传输与内存成本有界；「翻页时再渲染」的诉求是懒渲染 DOM 而非减少传输。后端分页需为跨项目聚合引入全局排序 + limit/offset 参数，接口复杂度不成比例。备选（后端分页）被否：单页数据 ≤150×N 条，收益为零而改动面横跨 server.py/data.py。

**D2 跨项目合并与排序在前端做** — 展平 `data.projects[].activities` 为单数组，排序规则：`handled === false` 置顶优先，组内按 `created` 倒序（与后端 `get_admin_activities` 的 per-project 排序语义一致，提升为全局）。每页 15 条用 `PAGE_SIZE = 15` 常量 + antd `Pagination` + 数组 `slice(current-1)*15, current*15)` 实现分页渲染；antd Timeline 无内置分页，外挂 Pagination 是最小改动。

**D3 viewModes 简化为单一 viewMode** — 现状 `Record<project, ViewMode>`（per-project Radio）改为单值 state；AlertPanel 去掉 `project` 过滤参数（`visible` 谓词删除），直接渲染全部项目告警；`markAlertHandled(a.project, a.id)` 调用不变（聚合数据已带 `project` 字段）。

**D4 已解决 Collapse 用非受控 `defaultActiveKey=['resolved']`** — 默认展开且允许用户手动收起；SSE 重渲染走 React reconciliation 不会重置非受控状态，只有视图切换导致的 remount 会回到默认展开（符合"默认展开"语义）。备选（受控 expandedKeys）被否：无额外状态需求。

**D5 SSE 刷新保持当前页码** — 刷新重拉数据后保留 `current` 页；若新数据总页数小于当前页则回退第 1 页。避免用户阅读历史记录时被刷新拉回顶部。

**D6 dist 重建并提交** — v3 UI 验证读主树 `:8787/v3/dist/`（静态实时读盘），实现分支必须重建 `core/dashboard/static/dist/` 并随代码提交，否则验证全量假阴性。

## Risks / Trade-offs

- [全局置顶穿插：多项目未处理记录混排在全局顶部，失去项目内聚] → 语义本就应"需人工决策的最显眼"，且卡片保留项目 Tag 可辨来源；如后续需要项目维度再立项。
- [翻页后 SSE 刷新导致当前页内容偏移] → D5 保页码 + 页码越界回退第 1 页兜底。
- [AlertPanel 全局化后告警量大时列表过长] → 未处理告警受 critical/major 准入降噪（`HUMAN_SEVERITIES`），量级有界；本次不加分页，超量再议。
- [SpecDocModal 内 admin-invoke-dialog 依赖 getAdminActivities(project, spec)] → 服务端与该组件均不在改动面内，仅回归确认。

## Migration Plan

纯前端单页改动，无数据迁移。实现分支完成 → 重建 dist 并提交 → merge-back 后主树验证 `:8787/v3/dist/#/activities`。回滚 = revert 单提交。

## Open Questions

（无 — 布局方案与执行模式已与用户确认：全局 Radio 切换 + fast-track）
