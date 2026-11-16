# Proposal: unified-page-title-bar

## Why

各菜单页标题（跨项目概览、设置、运维、指挥中心等）目前以 PageContainer 页头形态占据内容区一块面积，顶栏右侧却被全局面包屑占据——信息密度倒挂：位置信息与标题重复，而真正的过滤控件散落在各页页头 extra / 页签 extra 两处形态里。标题上移顶栏后内容区首屏直接见数据（数据墨水优先），过滤项获得全站一致的右上角落位。

## What Changes

- 新增**统一标题栏控件**（含标题 / 副标题 / 返回箭头 / 过滤项四类槽位），全站 8 个常规页（概览、项目列表、SPEC 详情、设置、运维、处置链、指挥中心、帮助）统一声明，禁止逐页自画同类 div。
- standalone（独立访问，≥768px）壳位：标题（18px/700）+ 副标题（12px 三级灰随迁）渲染进顶部标题栏 Fenix Harness 品牌之后；过滤项渲染到顶栏右上角；**内容区取消标题栏**（PageContainer 页头全部摘除）。
- 顶栏右侧现有全局面包屑（`HeaderCrumb`）**移除**（用户裁决：位置信息由标题本身表达，避免右上角拥挤）。
- embed（dsh web 面板桥 `embed=1`）壳位：顶栏不存在，统一控件**自动渲染为内容区首行标题栏**（48px，同一控件同构排布），承载标题与过滤项——dsh 侧零改造。
- 定高页偏移常数回校：settings `SETTINGS_FRAME_OFFSET` / help `HELP_FRAME_OFFSET` / `pageChrome.ts` 口径 / 指挥中心 `SCREEN_CHROME_OFFSET` 族随页头消失同步回校（改页头内边距必须回校为既有纪律）。
- 移动端（<768px）降级：顶栏不承载标题（维持纯 brand），统一控件整体渲染在内容区首行（与 embed 同款载体），富标题节点换行语义保持、不横向溢出。
- 豁免面：SPEC 协作拓扑大屏（`layout:false` 脱壳页）无壳层，不适用本控件。

## Capabilities

### New Capabilities

- `unified-page-title-bar`: 全站统一内容标题栏控件——双壳位（顶栏承载 / 内容区首行承载）、标题+副标题随迁+过滤项右上落位、面包屑退役、PageContainer 页头退役、定高偏移回校、移动端壳位降级。**界面以 prototype/ 为 UI 真相源**（specs/unified-page-title-bar/prototype/ 已批准入库，落位与原型绑定契约 `specs/<spec>/prototype/` 约定一致）。

### Modified Capabilities

- `dashboard-embed-mount`（spec/archive/2026-10-30-add-dashboard-embed-mode）: embed=1 语义从「隐藏壳层、页面自身内容头/面包屑保留」改为「隐藏壳层 + 统一标题行内嵌内容区首行」——PageContainer 页头保留条款随本变更退役。
- `mobile-detail-header-density`（spec/archive/2026-09-13-fix-mobile-touch-disclosure）: 「≥768px 视口面包屑 SHALL 正常显示」条款随面包屑全局移除退役；「详情页标题 Tag 行窄屏换行」条款的载体从 PageContainer 页头迁移到统一标题栏内容区首行壳位（语义不变、载体改写）。

## Impact

- **前端**：`core/dashboard/static/` —— `src/app.tsx`（布局配置：顶栏插槽改造 + HeaderCrumb 退役）、新组件 `src/components/PageTitleBar.tsx`、8 个页面容器摘除 PageContainer 页头、`src/pages/settings/index.tsx` / `src/pages/help/index.tsx` 定高偏移、`src/utils/pageChrome.ts` 偏移口径、`src/pages/command-center/index.tsx` Tabs extra 迁移、`src/global.less` 页头相关覆盖规则清理。
- **测试**：`tests/pageChrome.test.mjs`、`tests/embedMount.test.mjs` 既有断言更新；新增统一控件测试。
- **不受影响**：dashboard 后端 API 零改动；dsh web（dsh-plugins 仓）零改动（embed 契约由查询参数承载，参数语义不变）；ProLayout 侧栏/菜单、路由配置不变。
- **设计宪法**：不偏离 DESIGN.md——页面标题 18px/700、字号阶、配色单源、静态渲染红线全部沿用；标题载体从内容区迁顶栏属于现状变化，宪法对照在设计文档声明。
