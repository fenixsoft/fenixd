// themeHooks.ts — 主题状态 React 薄封装（dashboard-dark-theme 1.4）。
//
// utils/themePreference.ts 保持纯逻辑零 react import（node 直载测试约束），
// hook 侧收敛在本文件：useThemeScheme 供 app.tsx 根 ConfigProvider 与需要
// 主题档重渲染的组件订阅；useDshPalette 直接给出按档调色板（theme.ts 单源
// dshPalette），组件深档适配统一消费（dashboard-dark-theme 4.2）。
import { useSyncExternalStore } from 'react';
import { getCurrentScheme, subscribeScheme } from './themePreference.ts';
import type { ThemeScheme } from '../theme.ts';
import { dshPalette } from '../theme.ts';
import type { DshPalette } from '../theme.ts';

/** 当前 effective scheme（themePreference 状态机解析；档位变化触发重渲染）。
 *  getServerSnapshot 同取 getCurrentScheme：node 侧 react-dom/server 渲染测试
 *  （specTimelineOriginRequest 等直载渲染用例）依赖服务端快照存在。 */
export function useThemeScheme(): ThemeScheme {
  return useSyncExternalStore(subscribeScheme, getCurrentScheme, getCurrentScheme);
}

/** 按档语义调色板（浅/深常量单源 theme.ts；切档经 useThemeScheme 重渲染取新档）。 */
export function useDshPalette(): DshPalette {
  return dshPalette(useThemeScheme());
}
