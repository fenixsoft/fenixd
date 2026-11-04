// pageChrome.ts — 项目详情页「页面 chrome」占用高度共享常数
// （code-review item b2787f6789a9：原 SessionPanel / ArchitectureTab 各持一份
// 硬编码副本，顶栏/页头/Tabs 尺寸调整时两处须同步，漏改一侧即单侧纵向溢出）。
//
// unified-page-title-bar 2.5 回校：PageContainer 页头从详情页摘除（标题/
// 返回迁统一标题栏——standalone 进顶栏插槽，embed/mobile 为内容区首行壳位
// 48px），页头占位项随之从口径链移除，双档化对齐 embedMount 形态：
//
// - standalone：顶栏 56 + Tabs 导航 46 + Tabs 内容上边距 16 + 底部 32。
//   桌面 150；移动 198（顶栏同 56，页头项换行壳位 48，构成项替换与
//   直接构成两算法同值，390×844 旧站实测顶栏 56/旧页头 96 校准构成项）。
// - embed（embed=1，ProLayout 全局顶栏隐藏）：行壳位 48 + Tabs 46 + 16
//   + 32 = 142（桌面/移动同值——移动端 embed 同样隐藏顶栏）。
//
// 旧单档推导（页头在场）：桌面 222 = 顶栏 56 + 页头 72 + Tabs 导航 46
// + Tabs 内容上边距 16 + 底部 32；移动 234 按 390×844 实测校准
// （旧页头占位 84 记账）。旧值 222/234 见 git 历史。

import { isEmbedMode } from './embedMount.ts';

// [fenix-ignore:e6aef4e44ee9] 仓库内无共享布局 CSS 变量可派生（消费侧 SessionPanel/ArchitectureTab 均为 emotion 内联 calc 字符串插值），引入变量体系或视觉回归门改动面大于收益，推导口径已注释在文件头

/** 桌面端偏移：配合 calc(100vh - Npx) 给分面视口填充高度（embed 取行壳位档） */
export const PAGE_CHROME_OFFSET_DESKTOP = isEmbedMode() ? 142 : 150;

/** 移动端偏移：配合 calc(100dvh - Npx) 使用（dvh 随浏览器工具栏收展；embed 取行壳位档） */
export const PAGE_CHROME_OFFSET_MOBILE = isEmbedMode() ? 142 : 198;
