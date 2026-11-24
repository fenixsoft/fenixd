// themePreference.ts — 主题偏好状态机（dashboard-dark-theme 1.2 / design.md D3）。
//
// 纯逻辑零 react / antd import：node --test type-stripping 直载
// （tests/themePreference.test.mjs、tests/themeChannel.test.mjs）；React 侧
// hook（useThemeScheme / useDshPalette）在 utils/themeHooks.ts 薄封装。
//
// 偏好三档 `system | light | dark`，持久化 localStorage 键 `fenix.theme`
// （沿用 v1 键名，写入值域即三档字符串）；缺省（无键/非法值）= `system`，
// 跟随 `prefers-color-scheme` 并监听其变化实时切换（监听器经
// rearmMedia 对称挂载/卸载，React 生命周期由 initThemePreference 返回的
// disposer 承担清理）。
//
// **嵌入态宿主优先**（design.md D4）：embed=1 时不读取也不写入 localStorage
// （不污染独立偏好）；档位来源 = 挂载 URL `theme` 参数（embedMount.ts 解析）
// + 运行期 host→iframe postMessage（themeChannel.ts 校验后调 applyHostTheme）。
//
// **与首帧防闪烁内联脚本同构**（design.md D3，config/config.ts headScripts）：
// 内联脚本按同一套规则解析（localStorage 偏好 + embed theme 参数 +
// prefers-color-scheme → 首帧前写 data-fenix-theme），两处注释互指——改本
// 文件解析规则 MUST 同步 config.ts 内联脚本（及其直载测试的三输入组合断言）。
//
// 应用方式：`document.documentElement` 挂 `data-fenix-theme="dark|light"`
// （global.less CSS 变量双档切换的驱动属性）+ React 根 ConfigProvider 切
// ThemeConfig（app.tsx 经 utils/themeHooks 的 useThemeScheme 订阅）。

// .ts 扩展名导入（shared.ts 先例）：node --test type-stripping 直载兼容，
// umi/webpack 构建同样支持。
import { embedThemeParam, isEmbedMode } from './embedMount.ts';
import type { ThemeScheme } from '../theme.ts';

export type ThemePreference = 'system' | 'light' | 'dark';

export { type ThemeScheme };

/** localStorage 键（v1 主题切换沿用键名；值域即三档字符串）。 */
export const THEME_STORAGE_KEY = 'fenix.theme';

/** 测试注血形态（生产零调用）：node 环境无 localStorage / matchMedia。 */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}
export interface MediaQueryListLike {
  matches: boolean;
  addEventListener(type: 'change', listener: () => void): void;
  removeEventListener(type: 'change', listener: () => void): void;
}

let storageOverride: StorageLike | null = null;
let matchMediaOverride: ((query: string) => MediaQueryListLike | null) | null = null;

function storage(): StorageLike | null {
  if (storageOverride) return storageOverride;
  try {
    const s = (globalThis as { localStorage?: StorageLike }).localStorage;
    return s ?? null;
  } catch {
    return null;
  }
}

function mediaQuery(): MediaQueryListLike | null {
  try {
    if (matchMediaOverride) return matchMediaOverride('(prefers-color-scheme: dark)');
    const mm = (globalThis as {
      matchMedia?: (query: string) => MediaQueryListLike;
    }).matchMedia;
    return typeof mm === 'function' ? mm('(prefers-color-scheme: dark)') : null;
  } catch {
    return null;
  }
}

/** 非法值归一：缺省（无键/null/undefined/白名单外字符串）一律回退 `system`。 */
export function normalizePreference(raw: string | null | undefined): ThemePreference {
  return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system';
}

/** effective scheme 解析（design.md D3）：system 档跟 prefers-color-scheme。 */
export function resolveScheme(preference: ThemePreference): ThemeScheme {
  if (preference === 'dark') return 'dark';
  if (preference === 'light') return 'light';
  return mediaQuery()?.matches === true ? 'dark' : 'light';
}

// ── 模块级状态（单一事实源；hook 经 subscribeScheme/getCurrentScheme 订阅）──

let currentPreference: ThemePreference = 'system';
let currentScheme: ThemeScheme = 'light';
/** 嵌入态宿主注入档（URL theme 参数 / postMessage）；非嵌入恒 null。 */
let hostScheme: ThemeScheme | null = null;
let embedMode = false;
let media: MediaQueryListLike | null = null;
let mediaHandler: (() => void) | null = null;
const listeners = new Set<() => void>();

/** 当前是否嵌入态（主题通道视角；embedMount.isEmbedMode 的模块内镜像）。 */
export function isEmbedTheme(): boolean {
  return embedMode;
}

/** 当前 effective scheme（React 经 useSyncExternalStore 订阅取值）。 */
export function getCurrentScheme(): ThemeScheme {
  return currentScheme;
}

export function subscribeScheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 读独立偏好。宿主档生效时（嵌入 + URL 参数/postMessage 注入）不读
 * localStorage——宿主优先且不污染独立偏好（dashboard-dark-theme「独立偏好
 * 不被污染」Scenario）。嵌入但宿主未注入档（embed-mount spec「缺省与非法值
 * 回退」）按独立主题逻辑执行：照常读 localStorage。 */
export function readThemePreference(): ThemePreference {
  if (embedMode && hostScheme) return 'system';
  let raw: string | null = null;
  try {
    raw = storage()?.getItem(THEME_STORAGE_KEY) ?? null;
  } catch {
    raw = null;
  }
  return normalizePreference(raw);
}

/** 文档根应用：global.less `[data-fenix-theme]` 变量档切换的驱动属性。 */
export function applySchemeToDocument(scheme: ThemeScheme): void {
  try {
    (globalThis as unknown as { document?: Document }).document?.documentElement.setAttribute(
      'data-fenix-theme',
      scheme,
    );
  } catch {
    // node/SSR 无 document：静默跳过（应用层由 ConfigProvider 单独驱动）
  }
}

function notify(): void {
  for (const listener of listeners) listener();
}

/** system 档媒体查询监听对称挂载/卸载（need=false 即拆，防监听泄漏）。
 * 宿主档生效时系统外观不参与解析（宿主优先），监听一并拆除。 */
function rearmMedia(): void {
  const need = !(embedMode && hostScheme) && currentPreference === 'system';
  if (need && mediaHandler === null) {
    const mq = mediaQuery();
    if (mq) {
      media = mq;
      mediaHandler = () => refresh({ rearmMedia: false });
      try {
        mq.addEventListener('change', mediaHandler);
      } catch {
        media = null;
        mediaHandler = null;
      }
    }
  } else if (!need && mediaHandler !== null) {
    try {
      media?.removeEventListener('change', mediaHandler);
    } catch {
      // 旧宿主无 removeEventListener：拆绑失败与未挂等价
    }
    media = null;
    mediaHandler = null;
  }
}

function refresh(options: { rearmMedia: boolean }): void {
  if (options.rearmMedia) rearmMedia();
  // 宿主档优先级（design.md D4）：嵌入 + 宿主注入（URL/postMessage）> 独立偏好
  const scheme: ThemeScheme =
    embedMode && hostScheme ? hostScheme : resolveScheme(currentPreference);
  currentScheme = scheme;
  applySchemeToDocument(scheme);
  notify();
}

/** 用户动作（ThemePanel 三档选择）：即时生效 + 持久化；嵌入态不可写（静默
 * 忽略——宿主优先且不污染独立偏好，v3-settings-page「嵌入态锁定」同规）。 */
export function setThemePreference(preference: ThemePreference): void {
  if (embedMode) return;
  if (preference !== 'system' && preference !== 'light' && preference !== 'dark') return;
  try {
    storage()?.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // 隐私模式等写失败：会话内即时生效仍成立，持久化降级
  }
  currentPreference = preference;
  refresh({ rearmMedia: true });
}

/** 嵌入态宿主档应用（themeChannel.ts 校验后调用；值域再校验防御双层）。
 * 独立访问恒 false（宿主通道不生效）；成功返回 true 供通道侧测试断言。 */
export function applyHostTheme(scheme: string): boolean {
  if (scheme !== 'dark' && scheme !== 'light') return false;
  if (!embedMode) return false;
  hostScheme = scheme;
  refresh({ rearmMedia: false });
  return true;
}

/** 启动（app.tsx 根组件挂载期调用一次）：判定嵌入态 → 取宿主初始档（URL
 * theme 参数，embedMount 解析）→ 读独立偏好 → 首次解析应用。返回 disposer
 * （React useEffect cleanup：拆媒体监听、清订阅、复位嵌入态）。 */
export function initThemePreference(): () => void {
  embedMode = isEmbedMode();
  hostScheme = embedMode ? embedThemeParam() ?? null : null;
  currentPreference = readThemePreference();
  refresh({ rearmMedia: true });
  return disposeThemePreference;
}

/** 生命周期清理（initThemePreference 返回值）：matchMedia 监听对称卸载。 */
export function disposeThemePreference(): void {
  if (mediaHandler !== null) {
    try {
      media?.removeEventListener('change', mediaHandler);
    } catch {
      // 同 rearmMedia 拆绑兜底
    }
  }
  media = null;
  mediaHandler = null;
  listeners.clear();
  embedMode = false;
  hostScheme = null;
  currentPreference = 'system';
  currentScheme = 'light';
}

/** 测试注入口（生产零调用）：注入 storage / matchMedia 覆盖并复位模块态。
 * 传 null 恢复读 globalThis。注血须先于 initThemePreference() 调用。 */
export function _setThemeEnvForTest(
  env: {
    storage?: StorageLike | null;
    matchMedia?: ((query: string) => MediaQueryListLike | null) | null;
  } | null,
): void {
  storageOverride = env?.storage ?? null;
  matchMediaOverride = env?.matchMedia ?? null;
  disposeThemePreference();
}
