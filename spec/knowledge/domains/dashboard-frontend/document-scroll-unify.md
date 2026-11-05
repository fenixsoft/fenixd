# 帮助/设置页文档级滚动统一

<!-- knowledge: capability=document-scroll-unify rev=1
     sources=spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md -->

dashboard 前端帮助页与设置页的纵向滚动形态口径：全页文档级滚动 + 页内导航列 sticky 钉住，与概览/项目/运维记录同构。

## 规则

- **文档级滚动**：帮助页与设置页的页面纵向滚动统一走文档级——滚动条跨标题区域，同 overview/projects/activities 口径；桌面、移动、embed 三模式同构，不做分模式分叉。
- **无定高形态**：两页不持 `HELP_FRAME_OFFSET` / `SETTINGS_FRAME_OFFSET` 定高偏移常数，结构中无 `calc(100vh - 偏移)` 卡体定高链，正文卡体与右栏不设 `overflowY: auto` 内滚。定高自滚形态在全站的存续面仅项目详情页框与指挥中心两类（见 `page-container-chrome` 的定高贴底豁免与 `unified-page-title-bar` 的定高偏移口径）。
- **目录/菜单 sticky 钉住**：帮助页文档目录列与设置页左菜单列本体不随页面滚走——列外壳撑满列高（右缘分隔线全长），本体 `position: sticky` 钉在固定带下缘：standalone 为顶栏（56px）下缘、embed 为行壳位毛玻璃固定标题带（60px）下缘，按 `isEmbedMode()` 分档，常数 `HELP_TOC_STICKY_TOP` / `SETTINGS_MENU_STICKY_TOP`（standalone 56 / embed 60）。两常数为纯定位用途（钉视口坐标），不得挪作卡体定高扣减。钉住预算 `maxHeight: calc(100vh - 偏移 - 16px)`，长目录/长菜单超出视口时列本体自滚兜底——这是两页唯一的页内 overflowY；列顶带 16px 呼吸空间随本体钉位保持（钉住态不消失）。设置页左菜单不使用 `height: '100%'` 撑满形态。
- **内容区右留白回归单源**：两页内容区与他页一致走 `paddingInlinePageContainerContent`（15px）右留白，无贴缘外扩（无负边距抵扣，帮助页包裹卡无 `marginInlineEnd` 负值）；文档滚动条天然贴视口右缘。
- **守卫锁定**：`tests/helpPageScroll.test.mjs` 与 `tests/pageChrome.test.mjs` 锁定新形态——无 `*_FRAME_OFFSET` 常数、无 `height: calc(100vh …)` 高度链、正文/右栏无 `overflowY`、贴缘负边距不回潮、目录/菜单 sticky 钉住接线与双档偏移值（56/60）锁定。

## 关键行为

- 实拍基线（playwright，1440×900）：两页文档 `scrollHeight` > 视口高度、文档滚；设置页滚至页底卡体贴视口底（docEndGap=0）、右栏 `overflowY` visible；两页滚至页底时菜单/目录钉在视口 y=56（紧贴固定顶栏下缘）、分隔线全长；两页无横向溢出。

## 溯源

- 2026-11-05 settings-help-document-scroll-unify（spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md） — 新建本页：帮助/设置页滚动统一为文档级（定高内滚形态消失）、目录/菜单 sticky 钉住常数族（56/60 双档纯定位）、贴缘负边距不存续与守卫测试反转锁定新形态
