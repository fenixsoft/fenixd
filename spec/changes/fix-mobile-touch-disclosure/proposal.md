## Why

playwright 390×844 实测发现三类移动端体验问题：小字链接触控目标普遍 <44px（WCAG 2.5.8 AA 最低 24×24，iOS HIG 44pt）；spec 详情页头部「顶栏全局面包屑 + 返回箭头+标题 + Tag 行」三层堆叠，面包屑在窄屏与返回箭头语义重复；运维记录单卡 markdown 全文展开致整页高达 8646px，移动端滚不到底。另 SPEC 列表卡片已完成态存在「进度条 + 10/10 + 100%」三重表达冗余。

## What Changes

- 触控目标：`global.less` 定义 `.touch-expand` 工具类（padding 8px 扩大命中区 + 负 margin 完全抵消视觉，命中区 ≥32px ≥ WCAG AA），落地四处——SPEC 列表卡片「更多」、概览项目卡「进入/更多」、spec 详情「文档」链接、运维记录「查看处置过程」按钮。
- SPEC 列表卡片进度表达：已完成态右侧显示「已完成」替代重复的「100%」数字（`list.tsx` SpecCardList，仅移动端卡片分支）。
- detail 顶部压缩：顶栏全局面包屑（app.tsx HeaderCrumb）移动端隐藏；headerCfg title 的 Space 加 `wrap` 防 Tag 行窄屏溢出。
- 运维记录渐进披露：仅移动端且摘要 >300 字符时，summary 正文折叠（maxHeight + 渐隐 mask + 「展开全文/收起」按钮）；失败原因/处置/建议等操作安全信息一律不折叠；顺手为 Timeline items 补 `key`（防 SSE 重渲展开态串卡）。

## Capabilities

### New Capabilities

- `mobile-touch-targets`: 移动端小字链接触控目标扩展工具类及其四处落地；含 SpecCardList 已完成态进度单一表达。
- `mobile-detail-header-density`: spec 详情页头部的移动端密度——顶栏面包屑隐藏、标题 Tag 行换行。
- `mobile-activities-disclosure`: 运维记录卡片的移动端渐进披露——长摘要折叠展开、安全信息不折叠、SSE 刷新不串卡。

### Modified Capabilities

（无）

## Impact

- 受影响文件：`core/dashboard/static/src/global.less`（工具类 + 面包屑隐藏规则）、`app.tsx`（HeaderCrumb 加 className）、`pages/projects/detail.tsx`（Space wrap + 「文档」链接类名）、`pages/projects/list.tsx`（「更多」类名 + 进度表达）、`pages/overview/components/ProjectCards.tsx`（「进入/更多」类名）、`pages/activities/index.tsx`（isMobile 透传 + 折叠 + key）。
- PC 端（≥768px）：`.touch-expand` 规则与面包屑隐藏均限定移动作用域；activities 折叠条件含 `isMobile`，桌面恒不折叠；SpecCardList 整体仅存在于 isMobile 分支。
- 无 API / 数据 / 依赖变更。
