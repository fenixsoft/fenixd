# Proposal: add-chain-quota-paging

## Why

运维页「签名配额与上升」面板（ChainPanel.tsx）当前全量渲染签名条目。签名条目只增不减——复位窗只清计数不删行（`escalation_chain.py` 仅 setdefault 创建、无条目清理），列表会随时间无限拉长，稀释「待人工优先排序」的注意力，也拖慢面板渲染。

## What Changes

- ChainPanel.tsx「签名配额与上升」段增加**前端分页**：每页 10 行，默认显示第 1 页（即前 10 行）。
- 条目 ≤10 时单页展示、不渲染翻页控件；>10 时页脚提供上一页/下一页与页码指示。
- 分页只作用于签名行列表渲染；标题徽标总数、配额上限联查（sigIdx）、链上结果标签等全量口径不变。
- 后端 `chain_overview` 数据契约不变（客户端分页）。

## Capabilities

- `chain-quota-paging`（新增）：链面板签名配额列表分页展示。

## Impact

- **改动面**：仅 `core/dashboard/static/src/pages/activities/components/ChainPanel.tsx` 前端渲染层。
- **不影响**：后端 `alert_routes.py` / `admin_alerts.py` 的 chain summary 契约、配额计数与复位逻辑、其他面板。
- 知识对齐：既有分页先例 `spec/archive/2026-10-07-add-dashboard-paging-and-etag`（API 层 page/page_size）与本需求的客户端分页互补；签名条目现状 13 条、无上界（知识页 escalation-chain.md「配额计数是状态不是台账事实」）。
