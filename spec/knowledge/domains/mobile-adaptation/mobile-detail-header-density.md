# 详情页头部密度

<!-- knowledge: capability=mobile-detail-header-density rev=2
     sources=spec/archive/2026-09-13-fix-mobile-touch-disclosure,spec/changes/unified-page-title-bar -->

spec 详情页富标题组合在移动端行壳位标题栏内的层级压缩契约：窄屏顶栏仅纯品牌、富标题渲染在内容区首行标题栏并允许换行，无横向溢出。

## 规则

- **移动端顶栏纯品牌**：<768px 视口下顶栏仅渲染品牌，不承载页面标题与过滤项；顶栏全宽度无面包屑（面包屑已全局退役，位置指示职责由统一标题栏的页面标题承担）。
- **富标题行壳位换行**：spec 详情页富标题组合（SPEC 名 + 模式 Tag + 状态 Tag + 快速切换下拉）渲染在统一标题栏控件（unified-page-title-bar）的行壳位（<768px 视口下内容区首行标题栏），组合允许换行（`wrap`）；长名称 SPEC 在 390px 视口下自然换行，页面 `scrollWidth` 不超过视口宽度，无横向溢出，切换下拉保持在 SPEC 名旁。桌面端内容不溢出时 flex-wrap 无视觉差异。

## 溯源

- 2026-09-13 fix-mobile-touch-disclosure（spec/archive/2026-09-13-fix-mobile-touch-disclosure） — 建立顶栏全局面包屑移动端隐藏（`global-header-crumb` 锚点）与详情标题 Space `wrap` 防溢出契约
- 2026-11-04 unified-page-title-bar（spec/changes/unified-page-title-bar/） — 已随面包屑全局退役废除「<768 隐藏 / ≥768 显示」宽度分档条款（顶栏无面包屑成为全宽度常量事实）；标题 Tag 行载体从 PageContainer `headerCfg` title 的 Space 容器迁移到统一标题栏行壳位（wrap 语义不变、载体改写）
