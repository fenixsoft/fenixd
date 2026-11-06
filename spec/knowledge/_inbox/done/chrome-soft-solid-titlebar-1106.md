# 布局 chrome 底色 soft 染色统一（标题栏玻璃保留、菜单实底）

2026-11-06 用户指令两段（第二段更正第一段）：「菜单、标题栏、Fenix Harness 标题的
背景颜色都改为 rgb(249, 250, 251)，整个标题栏的下边框线要保持可见，颜色与菜单栏的
右边框保持一致」；随后更正「**标题栏只是改变颜色，要保留毛玻璃效果**」。

## 生效规则（待蒸馏进 dashboard-frontend 域）

1. **standalone 顶栏玻璃换 soft 染色**（形态不变）：布局 token（`theme.ts
   dshLayoutToken`）`header.colorBgHeader = DSH_HEADER_GLASS`（rgba(249,250,251,0.4)，
   pro-layout fixedHeader 缺省白染 0.4 档只换 rgb 通道）、`header.colorBgScrollHeader
   = DSH_HEADER_GLASS_SCROLL`（rgba(249,250,251,0.8)，滚动态 `-fixed-header-scroll`
   换底档，漏配即滚动态回白染色）。blur 由 pro-layout 顶栏样式内置
   （blur(8px)+-webkit- 前缀），无需另配。Fenix Harness 品牌区随顶栏同底
   （GlobalHeader transparent）。
2. **embed 档行壳位玻璃底换 soft 染色**（推翻「退役毛玻璃」误改，形态不变）：
   `DSH_BG_SOFT_GLASS`（rgba(249,250,251,0.6)）+ backdrop blur(8px) + sticky 保留，
   仅 rgb 通道随 `DSH_BG_SOFT` 单源。**毛玻璃生效前提=底必须半透明，回实底即
   静默失效**——2026-11-06 当日曾误改实底并删 blur（死代码判定），用户更正后
   恢复；pageTitleBar 守卫测试钉三值通道一致（SOFT/GLASS/HEADER_GLASS 族）+
   透明度必须 <1。
3. **菜单（侧栏）走 soft 实底**：`sider.colorMenuBackground = DSH_BG_SOFT`
   （#f9fafb ≡ rgb(249,250,251)），pro-layout 缺省侧栏底 = antd lightSiderBg =
   colorBgContainer 白被覆盖；同键兼作侧栏 Menu itemBg/subMenuItemBg，菜单行与
   侧栏平涂一体。移动端行壳位档（48px 随流）无毛玻璃形态，同走 soft 实底。
4. **边框一致性口径**：标题栏下边框（pro-layout header borderBlockEnd）、侧栏右边框
   （`.ant-layout-sider-children` borderInlineEnd）、行壳位底缘细线三处同取
   `colorSplit = DSH_SPLIT`（rgba(0,0,0,0.08)），「标题栏下边框与菜单右边框一致
   可见」由同取单源成立，勿局部覆写。

## 溯源

- 落地面：`core/dashboard/static/src/theme.ts`（dshLayoutToken header/sider 块 +
  DSH_HEADER_GLASS/_SCROLL 新常量）、`src/components/PageTitleBar.tsx`（行壳位
  双档配色 embed 玻璃/移动实底）、`tests/pageTitleBar.test.mjs`（守卫改钉）。
- playwright 实拍（8787 直连，2026-11-06）：standalone 顶栏 computed
  bg=rgba(249,250,251,0.4)+blur(8px)、侧栏 rgb(249,250,251) 实底、两边框
  1px rgba(0,0,0,0.08)；embed 行壳位 rgba(249,250,251,0.6)+blur+sticky top=0；
  控制台零错误。截图 `.history/standalone-chrome-soft-1106.png`（实底误改版）、
  `.history/embed-row-glass-soft-1106.png`（更正后）。
- 知识页待改写对象：`unified-page-title-bar.md`「embed 档毛玻璃固定标题带」规则段
  玻璃染色表述（rgba 通道换 soft 染色）、`ui-theme.md` 若登记 chrome 底色则同步。
