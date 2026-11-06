# 布局 chrome 底色染色

<!-- knowledge: capability=layout-chrome-tinting rev=1
     sources=spec/knowledge/_inbox/done/chrome-soft-solid-titlebar-1106.md -->

ProLayout 布局壳层（standalone 顶栏、侧栏菜单、边框细线）与标题带玻璃的底色染色口径：soft 档单源、毛玻璃形态保留、三处边框同源。

## 规则

- **soft 档单源**：布局 chrome 全部底色的 rgb 通道统一取 `DSH_BG_SOFT`（#f9fafb ≡ rgb(249,250,251)，`theme.ts` 单源）；玻璃形态值是它的透明派生档——标题栏行壳位 `DSH_BG_SOFT_GLASS`（60%）、顶栏 `DSH_HEADER_GLASS`（40%）、顶栏滚动态 `DSH_HEADER_GLASS_SCROLL`（80%）。守卫测试钉 soft 染色族各值 rgb 通道与 `DSH_BG_SOFT` 一致、各玻璃值透明度必须 <1——族内任一值改动须同源共改，改出族即守卫失败。
- **standalone 顶栏毛玻璃保留、只换染色**：`dshLayoutToken` header 配 `colorBgHeader: DSH_HEADER_GLASS` 与 `colorBgScrollHeader: DSH_HEADER_GLASS_SCROLL`——pro-layout fixedHeader 缺省白染毛玻璃（rgba(255,255,255,0.4/0.8) 双档）只换 rgb 通道、alpha 档位不变。blur 由 pro-layout 顶栏样式内置（blur(8px) + `-webkit-` 前缀），无需另配。**colorBgScrollHeader 必须随配**：fixedHeader 滚动超过 56px 时滚动态类名（`-fixed-header-scroll`）换底档，漏配即滚动态顶栏回白染色。Fenix Harness 品牌区随顶栏同底（GlobalHeader transparent）。
- **菜单（侧栏）soft 实底**：`dshLayoutToken` sider 配 `colorMenuBackground: DSH_BG_SOFT`，覆盖 pro-layout 缺省侧栏底（= antd lightSiderBg = colorBgContainer 白）；同键兼作侧栏 Menu 的 itemBg/subMenuItemBg——菜单行与侧栏容器平涂一体。
- **边框一致性口径**：顶栏下边框（pro-layout header borderBlockEnd）、侧栏右边框（`.ant-layout-sider-children` borderInlineEnd）、标题栏行壳位底缘细线三处同取 `colorSplit = DSH_SPLIT`（rgba(0,0,0,0.08)）；「顶栏下边框与菜单右边框一致可见」由同取单源成立，勿局部覆写。
- **毛玻璃半透明前提**：玻璃底改实底则 backdrop 模糊层静默失效（无运行时报错）——玻璃值必须保留透明度；行壳位玻璃带（60px sticky、blur 同值）的形态细节见 `unified-page-title-bar`。

## 溯源

- 2026-11-06 chrome-soft-solid-titlebar-1106（spec/knowledge/_inbox/done/chrome-soft-solid-titlebar-1106.md） — 新建本页：布局 chrome 底色统一 soft 染色——顶栏毛玻璃只换 rgb 通道双档（colorBgScrollHeader 必随配）、菜单侧栏 soft 实底平涂一体、三处边框同取 colorSplit、soft 染色族通道一致与透明度守卫
