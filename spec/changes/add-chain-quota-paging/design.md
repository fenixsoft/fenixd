# Design: add-chain-quota-paging

## Context

「签名配额与上升」段位于 `core/dashboard/static/src/pages/activities/components/ChainPanel.tsx`（渲染段起点 :928，标题徽标 `{signatures.length}`，按 spec 分组 `buildQuotaGroups(signatures)` :739）。数据源为 `alert_routes.py` chain summary 端点 → `chain_overview`（`admin_alerts.py:368`）全量下发 `signatures` 数组（单项目与跨项目聚合两分支）。条目现状 13 条、只增不减（复位窗清计数不删行）。

## Goals

- 列表默认只显示前 10 行，超出部分经翻页访问；总量与联查口径不变。

## Decisions

- **D1 客户端分页，不扩后端契约**：量级小（十级、缓慢增长），服务端分页需同时改单项目/聚合两分支契约与 `summary` totals 语义（alert_routes.py 注记「两分支行级形状差异勿顺手拉平」），成本远超收益。
- **D2 分页对象 = 扁平签名行，页内再分组**：对 `signatures` 按每页 10 条切片，当前页切片经既有 `buildQuotaGroups` 按 spec 分组渲染；组头计数为当前页内聚合，逐行链上结果标签与配额上限联查不受影响。
- **D3 翻页控件**：页脚居中「上一页 / 第 x / N 页 / 下一页」紧凑文本按钮；首页禁用上一页、末页禁用下一页；条目 ≤10（N≤1）不渲染控件。页码用 `useState` 本地保存，数据集变化（切换项目筛选/刷新重挂载）时钳制到有效页界。
- **D4 全量口径不动**：标题徽标 `{signatures.length}` 仍显全量条目数；`sigIdx`（:685）继续用全量 signatures 构建，在办行/抽屉的配额上限联查与分页无关。
- **D5 设计宪法**：遵守仓库根 `DESIGN.md` 既有控件语言（文本按钮、间距、禁用态），无偏离条款。

## Risks

- 「按 spec 分组」跨页截断：当前页内组头计数只反映本页条目，可能被误读为全量——缓解：组头文案不加「共 N」总数语义，副标「按 spec 分组 · 待人工优先排序」保持不变。
- 移动端（isMobile 分支）新增 pager 占一行：用紧凑单行控件，行为与桌面一致。

## Migration

无数据迁移、无配置项。
