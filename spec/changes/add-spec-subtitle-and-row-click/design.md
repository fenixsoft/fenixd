# Design: add-spec-subtitle-and-row-click

## Context

add-spec-chinese-title 已落地：`.spec.yaml` `title` 字段全量回填、`/api/specs` 与 `/api/specs/<spec>` 均透传 `title`（详情接口已实测返回）、两处列表名称列渲染副标题。本次为展示面与交互的两个增量：详情标题栏副标题（v1/v2 两页）+ v1 列表整行点击。

既有可复用基建：
- PageTitleBar `subtitle` 声明槽（`SubtitleNode` 12px tertiary，`!isMobile` 隐藏）；v2 specDetail 已用它显示 branch。
- overview `ProjectTable.tsx:569` 的 `onRow` 整行点击范式（onClick + cursor pointer）。
- v1 列表现有 `onRow`（仅选中行底色 style，无 onClick）——增补 onClick 不冲突。
- v1 详情页已拉取 specList（quick-switch 数据源），可按名查 title 兜底。

## Goals

1. 详情页标题栏英文标题下方显示中文标题（v1 新增 subtitle；v2 与 branch 组合）。
2. v1 列表整行点击进详情，行内既有交互零回归。

## Decisions

- **D1 数据源**：详情响应 `title` 字段（后端已透传，无需后端改动）；`SpecDetail` TS 类型补 `title?: string | null`。v1 详情经 `detail?.title` 取值（specList 查表仅作实现期兜底备选，不写死两源合并逻辑）。
- **D2 副标题组合形态**：v2 subtitle 节点为 `中文标题 · branch`（branch 空只显中文标题，title 空维持现状 branch 单独显示，双空不渲染）；v1 直接 `subtitle={detail?.title || undefined}`。分隔符用中点「·」两侧带空格，视觉对齐既有 tertiary 12px。
- **D3 行点击守卫**：`onRow.onClick` 内经事件目标判定守卫——`event.target.closest('.ant-table-row-expand-icon')`（展开钮）与操作列容器（`[data-spec-row-actions]` 或 closest 按钮/`.ant-dropdown-menu`）命中即 return，不导航；名称链接自有 href 跳转与行导航同目标，不额外拦截（双触发同路由无害）；展开行内容（expandedRowRender 渲染于行外 `ant-table-expanded-row`）天然不在 onRow 命中面。cursor pointer 整行生效。
- **D4 不加 v2 表格行点击**：v2 SPEC 表操作列密集（删除等危险操作），误触代价高，本轮不动（proposal 非目标）。

## Risks

- **行点击与展开/操作误触**：缓解 = D3 目标判定守卫 + Scenario 钉死四类交互；前端测试覆盖展开钮/操作列不导航。
- **副标题遮挡**：标题栏高度既有偏移常数族（pageChrome offset）不因 subtitle 变化（subtitle 在槽内渲染，与 v2 branch 先例同位），无新偏移风险。
