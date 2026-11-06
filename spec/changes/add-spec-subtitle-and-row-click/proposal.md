## Why

add-spec-chinese-title 已让两处列表名称列显示中文标题，但 SPEC 详情页标题栏仍只有英文名（进入详情后中文语境辨识收益丢失）；同时 v1 列表页只有名称文字可点进详情，行内其余区域点击无响应——overview 项目表格（ProjectTable `onRow` 整行点击进项目）已验证整行点击的交互收益，SPEC 列表应对齐同款交互。

## What Changes

- **v1 详情标题栏中文副标题**（新增）：`pages/projects/detail.tsx` 的 PageTitleBar 增用 subtitle 槽渲染中文标题（数据源：详情 API `title` 字段，详情页 quick-switch 已拉取的 specList 可兜底查表）；移动端维持既有 subtitle 移动端隐藏规则。
- **v2 详情标题栏中文副标题**（新增）：`pages/v2/specDetail.tsx` 的 PageTitleBar subtitle 槽与既有 branch 组合渲染（`中文标题 · branch`，branch 缺失时只显示中文标题）；移动端维持既有隐藏规则。
- **v1 列表整行点击进详情**（新增）：`pages/projects/list.tsx` 的 `onRow` 增加整行 onClick 导航（镜像 overview ProjectTable 范式：cursor pointer + history.push）；展开钮、操作列（⋯ 菜单、状态按钮）等交互单元格 stopPropagation 守卫，名称 Why 悬浮提示、fix-* 展开、行内既有交互不受影响。

**非目标**：v2 SPEC 表格（projectDetail）不加整行点击（该表操作列密集，本轮不动）；快速切换下拉、PageTitleBar 组件本身不改（subtitle 槽既有能力直接消费）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `dashboard-spec-table`（最后形态见 `spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear/specs/dashboard-spec-table/spec.md`，其后历经多轮修订）：新增「整行点击进详情」需求。
- `unified-page-title-bar`（活跃能力，标题栏声明-注册-插槽桥接单源）：新增「SPEC 详情标题栏中文副标题」消费面声明（v1 detail / v2 specDetail 两页）。

## Impact

- **代码面**：纯前端三文件（`projects/detail.tsx`、`v2/specDetail.tsx`、`projects/list.tsx`）+ `services/dashboard.ts`（`SpecDetail` 类型补 `title` 字段）+ 前端测试；无后端改动（title 字段 API 已透传，详情接口已验证返回）。
- **兼容面**：subtitle 移动端隐藏、展开行、操作列菜单、名称链接、Why 悬浮等既有交互零回归；无 title 的 SPEC 详情副标题不渲染（缺失容错，与列表规则一致）。
