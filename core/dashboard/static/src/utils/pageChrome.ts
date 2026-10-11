// pageChrome.ts — 项目详情页「页面 chrome」占用高度共享常数
// （code-review item b2787f6789a9：原 SessionPanel / ArchitectureTab 各持一份
// 硬编码副本，顶栏/页头/Tabs 尺寸调整时两处须同步，漏改一侧即单侧纵向溢出）。
// 推导：桌面 222 = 布局顶栏 56 + 页头 72 + Tabs 导航 46 + Tabs 内容上边距 16
// + 底部 32（375~1920 宽 / 700~1440 高实测恒定）；移动端 234 按 390×844 实测校准。

/** 桌面端偏移：配合 calc(100vh - Npx) 给分面视口填充高度 */
export const PAGE_CHROME_OFFSET_DESKTOP = 222;

/** 移动端偏移：配合 calc(100dvh - Npx) 使用（dvh 随浏览器工具栏收展） */
export const PAGE_CHROME_OFFSET_MOBILE = 234;
