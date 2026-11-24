// themeChannel.ts — 嵌入态主题 postMessage 通道（dashboard-dark-theme 2.2 /
// design.md D4 实时层）。
//
// host→iframe 单向广播：消息形状 `{ kind:'fenix-dashboard:theme',
// theme:'dark'|'light' }`。kind 命名空间沿用既有 iframe 集成消息
// `fenix-dashboard:*`（embedBridge.ts HOST_NEW_SESSION_KIND =
// 'fenix-dashboard:new-session' 先例）；按双仓镜像值纪律，桥接侧
// （dsh-plugins fenix-dsh-dashboard-bridge，独立立项 add-bridge-theme-channel）
// 常量字面量 MUST 与 THEME_MESSAGE_KIND 逐字节一致。
//
// iframe 侧三层校验（Risks「postMessage 伪造」处方，任一不满足静默忽略、
 // 不报错）：event.source === window.parent + kind 白名单 + theme 值域。
// 校验通过交 utils/themePreference.applyHostTheme 应用宿主档（嵌入态才生效，
 // 不读写 localStorage——宿主优先且不污染独立偏好）。
//
// 独立访问零监听（startThemeChannel 即返 noop disposer）；监听器经返回的
 // disposer 随 React 生命周期对称清理。

import { applyHostTheme } from './themePreference.ts';
import { isEmbedMode } from './embedMount.ts';

/** 主题广播消息 kind（双仓镜像值：桥接侧字面量与本值逐字节一致）。 */
export const THEME_MESSAGE_KIND = 'fenix-dashboard:theme';

export interface ThemeMessage {
  kind: typeof THEME_MESSAGE_KIND;
  theme: 'dark' | 'light';
}

/** kind 白名单 + theme 值域校验（kind 不符或 theme 出域即 false）。 */
export function isValidThemeMessage(data: unknown): data is ThemeMessage {
  if (typeof data !== 'object' || data === null) return false;
  const d = data as { kind?: unknown; theme?: unknown };
  return d.kind === THEME_MESSAGE_KIND && (d.theme === 'dark' || d.theme === 'light');
}

/** 事件校验（source 层）：非父窗口来源（同页 iframe 嵌套、其它窗口伪造）
 * 一律忽略。window.parent 缺失（顶层文档）时 source 不可能等于它，天然拒绝。 */
function isFromParentWindow(event: MessageEvent): boolean {
  return event.source === (globalThis as unknown as { window?: Window }).window?.parent;
}

/** 启动宿主主题监听：embed=1 时挂 window message 监听（校验链见上），返回
 * disposer（拆监听）；独立访问 / 非 DOM 环境（node 测试直载）不监听，返回
 * noop。注：嵌入态与否以启动时刻 embedMount 判定为准（文档生命周期常量，
 * 与 PageTitleBar 壳位判定同口径）。 */
export function startThemeChannel(): () => void {
  const w = globalThis as unknown as {
    window?: {
      addEventListener?: (type: 'message', listener: (event: MessageEvent) => void) => void;
      removeEventListener?: (type: 'message', listener: (event: MessageEvent) => void) => void;
    };
  };
  if (!isEmbedMode() || typeof w.window?.addEventListener !== 'function') {
    return () => {};
  }
  const handler = (event: MessageEvent): void => {
    if (!isFromParentWindow(event)) return;
    if (!isValidThemeMessage(event.data)) return;
    applyHostTheme(event.data.theme);
  };
  w.window!.addEventListener('message', handler);
  return () => {
    w.window?.removeEventListener?.('message', handler);
  };
}
