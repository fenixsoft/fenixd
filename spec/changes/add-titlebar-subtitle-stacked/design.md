# Design: add-titlebar-subtitle-stacked

## Context

PageTitleBar 现有 subtitle 槽为行内形态（`BackArrow + TitleNode + SubtitleNode` 同一 baseline flex 行，`columnGap: 10`，两壳位同构排布）；v1/v2 详情页经该槽渲染中文标题后呈「标题同行右侧」灰字，与用户「英文标题下方」诉求不符（2026-11-06 用户裁决修成下方堆叠）。行内形态不增栏高，堆叠形态会增——标题栏高度是既有偏移常数族的锚（settings/help 56/60、command-center 126/130、pageChrome 屏幕偏移族），增栏即触发同步面。

## Goals

1. 组件支持声明式堆叠形态；两详情页切换声明，branch 一并下移。
2. 未声明面零变化；偏移常数按实际渲染回校，守卫测试防回潮。

## Decisions

- **D1 声明式切换**：`PageTitleBar` 新增布尔声明（如 `subtitleBelow`，命名实现期定），`true` 时 SubtitleNode 从标题行内移出、渲染为标题行下独立行（标题行 flex 行保持，副标题行 `fontSize: 12 / tertiary / 左对齐标题首字`）；缺省 false 行内形态不变——形态切换权在页面声明，组件不全局翻转（v2 branch 先例与其余消费面不被动迁）。
- **D2 两壳位同构**：行壳位与顶栏槽两形态同构排布纪律延续——堆叠行在两壳位行为一致（sticky 栏内自然增高）；embed 档同规则。
- **D3 偏移回校以实测为准**：不预写常数目标值——实现时以浏览器实测新栏高回校命中常数（56/60 族 / pageChrome 屏幕偏移族中与两详情页相关者），pageTitleBar / pageChrome / embedMount 守卫测试同步钉死；未命中的常数不动（避免全族误改——titlebar 同步面纪律「5 常量 4 测试」以实际同步面为准）。
- **D4 移动端零改动**：`!isMobile` 判据在页级声明处既有承担，堆叠形态仅桌面生效路径，移动端三态（不渲染）不变。

## Risks

- **栏高增加引发页内遮挡/错位**：缓解 = D3 实测回校 + 守卫测试；两详情页页签 sticky、目录 sticky 等命中面在任务中逐页盘点。
- **富标题换行交互**：堆叠后标题行仍 `flexWrap: wrap`（mobile-detail-header-density 契约），副标题独立行不受富标题换行影响；390px 视口回归由既有移动端测试兜底。
