# embed 行壳位复刻顶栏毛玻璃（unified-page-title-bar 形态随迁）

2026-11-05 用户指令：dsh web 面板桥 iframe 内的 dashboard 固定标题带
（PageTitleBar 行壳位 embed 档）由实底升格毛玻璃——半透明玻璃底
DSH_BG_SOFT_GLASS（theme.ts 新常量，DSH_BG_SOFT 60% 透明形态，守卫测试
钉两值通道一致+透明度必须保留）+ backdrop-filter blur(8px)（standalone
ProLayout fixedHeader 同值，附 -webkit- 前缀兜底旧移动端 webview）。
内容滚过标题带时透出模糊内容，观感对齐 standalone 顶栏。

要点：

- 移动端档（48px 白底随流）不变；sticky 占位语义不变（只加视觉）。
- 毛玻璃生效前提=底必须半透明：任何后续把 background 改回实底的改动
  会静默失效（无报错）。
- 页面级标签带（dashboard-frontend 域 unified-page-title-bar /
  page-container-chrome 族）形态描述如有「embed 档 soft 实底」表述须随迁。

## 建议折叠去向

- dashboard-frontend 域 unified-page-title-bar 相关能力页（或
  page-container-chrome）：embed 档形态句随迁（60px 玻璃底+blur）。

## 溯源

- 2026-11-05 用户指令（会话内交付），fenixd core/dashboard/static
  PageTitleBar.tsx / theme.ts / pageTitleBar.test.mjs 三文件。
