# 详情页头部密度

<!-- knowledge: capability=mobile-detail-header-density rev=3
     sources=spec/archive/2026-09-13-fix-mobile-touch-disclosure,spec/changes/unified-page-title-bar,spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md -->

spec 详情页富标题组合在移动端顶栏内的密度裁剪契约：窄屏顶栏承载页面标题与过滤项，富标题移动端只显英文标题，无横向溢出。

## 规则

- **移动端顶栏承载标题与过滤项**：<768px 视口下页面标题与汉堡、logo 同条渲染在 ProLayout 顶栏，页级过滤控件经 filters 槽位落顶栏右侧；顶栏全宽度无面包屑（面包屑已全局退役，位置指示职责由页面标题承担）。壳位分流与顶栏形态由统一标题栏控件单源承载（unified-page-title-bar），移动端内容区不铺任何标题带。
- **富标题移动端只显英文标题**：spec 详情页富标题组合（SPEC 名 + 模式/状态 Tag + 快速切换下拉）移动端仅渲染英文标题——右簇（模式/状态胶囊与状态转移、v1 快速切换下拉）与中文标题下方行均不渲染（页级 gate），返回箭头移动端隐藏；完整两列结构与中文标题下方行堆叠契约仅桌面视口生效（见 unified-page-title-bar）。

## 溯源

- 2026-09-13 fix-mobile-touch-disclosure（spec/archive/2026-09-13-fix-mobile-touch-disclosure） — 建立顶栏全局面包屑移动端隐藏（`global-header-crumb` 锚点）与详情标题 Space `wrap` 防溢出契约
- 2026-11-04 unified-page-title-bar（spec/changes/unified-page-title-bar/） — 已随面包屑全局退役废除「<768 隐藏 / ≥768 显示」宽度分档条款（顶栏无面包屑成为全宽度常量事实）；标题 Tag 行载体从 PageContainer `headerCfg` title 的 Space 容器迁移到统一标题栏行壳位（wrap 语义不变、载体改写）
- 2026-11-07 mobile-ui-fixes-1107（spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md） — 对齐统一标题栏现行契约改写：移动端顶栏承载标题与过滤项、富标题载体为 ProLayout 顶栏（旧「顶栏纯品牌不承载过滤项」「富标题内容区首行行壳位换行」表述随 2026-11-06 行壳位收敛 embed 单档废除）
