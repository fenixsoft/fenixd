// localePreference.ts — 语言偏好状态机（add-framework-i18n-zh-en 1.3 / design D2）。
//
// 纯逻辑零 react / umi import：node --test type-stripping 直载
// （tests/localePreference.test.mjs）；umi 侧接线（setLocale 应用）经
// registerLocaleApplier 注血由 app.tsx bootstrap 注册
// （(target) => setLocale(target, false)，不刷新页面）。
//
// 偏好三档 `system | zh-CN | en-US`，持久化 localStorage 键 `fenix.locale`
// （值域即三档字符串）；缺省（无键/非法值）= `system`，跟随浏览器语言并经
// 归一映射落受支持档（zh 系→zh-CN、en 系→en-US、其余→zh-CN）。// 浏览器语言运行期热变化不实时跟随（跟随档在解析时刻取值——design
// Non-Goals 与主题 matchMedia 监听不同，接受该简化）。
//
// **与首帧防闪烁内联脚本同构**（design D2，config/config.ts
// FIRST_FRAME_LOCALE_SCRIPT）：内联脚本按同一套规则解析——显式档写 umi 内建
// `umi_locale` 键；`system` 档先清 `umi_locale`（清键走浏览器判定）再按
// navigator 归一落键。**归一的根因**：umi baseNavigator 只对
// navigator.language 原样匹配（en-GB/ja 等值域外 locale 不在目录列表，
// getIntl 对未知 locale warning 后回退 default zh-CN messages——英文浏览器
// 会错落中文），必须先归一成受支持档再落键。两处注释互指——改本文件解析
// 规则 MUST 同步 config.ts 内联脚本（及其直载测试的三输入组合断言）。
//
// 应用方式：生效值经 umi `setLocale(target, false)`（不刷新页面）——locale
// 插件内部写 `umi_locale` + setIntl + LANG_CHANGE_EVENT（@@intl model 更新，
// useIntl 消费者全树重渲染，切换即时生效）。

// 嵌入形态判定与宿主初始语言档（i18n 宿主跟随轮）。embedMount 同为纯逻辑
// 零 react 依赖（themePreference.ts:28 先例），node 直载测试链可解析。
import { embedLocaleParam, isEmbedMode } from './embedMount.ts';

export type LocalePreference = 'system' | 'zh-CN' | 'en-US';
export type ResolvedLocale = 'zh-CN' | 'en-US';

/** 本品偏好键（fenix 自有三档单源，design D2）。 */
export const LOCALE_STORAGE_KEY = 'fenix.locale';
/** umi locale 插件内建持久化键（setLocale 写 / getLocale 读 / baseNavigator 缺省读）。 */
export const UMI_LOCALE_STORAGE_KEY = 'umi_locale';

/** 测试注血形态（生产零调用）：node 环境无 localStorage / navigator。 */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

let storageOverride: StorageLike | null = null;
let languagesOverride: (() => readonly string[]) | null = null;
let applierOverride: ((target: ResolvedLocale) => void) | null = null;

function storage(): StorageLike | null {
  if (storageOverride) return storageOverride;
  try {
    const s = (globalThis as { localStorage?: StorageLike }).localStorage;
    return s ?? null;
  } catch {
    return null;
  }
}

function navigatorLanguages(): readonly string[] {
  if (languagesOverride) return languagesOverride();
  try {
    const nav = (globalThis as { navigator?: { languages?: readonly string[]; language?: string } })
      .navigator;
    if (nav?.languages?.length) return nav.languages;
    if (nav?.language) return [nav.language];
    return [];
  } catch {
    return [];
  }
}

/** 档位已应用广播事件名：rootContainer（ThemeRoot）位处 umi locale 插件
 * i18nProvider 外层（renderer 合成序 rootContainer 最外、插件 provider 恒在
 * 内层），订阅不到插件内层的 LANG_CHANGE_EVENT——applyLocale 经本 window
 * 事件广播「档位已应用」，ThemeRoot 借此同步 antd ConfigProvider locale 与
 * dayjs locale（消息面文案由内层 provider 自订阅 LANG_CHANGE_EVENT 更新
 * context 值传播，不经本事件）。 */
export const LOCALE_APPLIED_EVENT = 'fenix-locale-applied';

function applyLocale(target: ResolvedLocale): void {
  if (applierOverride) applierOverride(target);
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new CustomEvent(LOCALE_APPLIED_EVENT));
  }
}

/** 非法值归一：缺省（无键/null/undefined/白名单外字符串）一律回退 `system`。 */
export function normalizePreference(raw: string | null | undefined): LocalePreference {
  return raw === 'zh-CN' || raw === 'en-US' || raw === 'system' ? raw : 'system';
}

/** 浏览器语言归一映射（design D2）：zh 系→zh-CN、en 系→en-US、其余→zh-CN。
 * 逐语言取第一个命中前缀（navigator.languages 优先序即用户偏好序）。 */
export function resolveBrowserLocale(
  languages: readonly string[] | null | undefined,
): ResolvedLocale {
  for (const lang of languages ?? []) {
    if (/^zh/i.test(lang)) return 'zh-CN';
    if (/^en/i.test(lang)) return 'en-US';
  }
  return 'zh-CN';
}

/** 偏好档 → 生效档：嵌入态宿主档优先（i18n 宿主跟随轮：宿主显式语言覆盖
 * 本地偏好，不污染 fenix.locale/umi_locale 独立存储——themePreference
 * hostScheme 同构语义）；宿主未广播（bridge 不支持/未就绪）时回退既有链：
 * 显式档直落；`system` 档按当前浏览器语言归一。 */
export function resolveTarget(preference: LocalePreference): ResolvedLocale {
  if (hostLocale !== null) return hostLocale;
  if (preference === 'en-US') return 'en-US';
  if (preference === 'zh-CN') return 'zh-CN';
  return resolveBrowserLocale(navigatorLanguages());
}

/** 读独立偏好（缺省/非法值回退 system）。 */
export function readLocalePreference(): LocalePreference {
  let raw: string | null = null;
  try {
    raw = storage()?.getItem(LOCALE_STORAGE_KEY) ?? null;
  } catch {
    raw = null;
  }
  return normalizePreference(raw);
}

// ── 模块级状态（单一事实源；渲染期取值走 getter，与 themePreference 同构）──

let currentPreference: LocalePreference = 'system';
let currentTarget: ResolvedLocale = 'zh-CN';

// 嵌入态宿主档（i18n 宿主跟随轮）：null=宿主未注入（本地偏好链生效）；
// 非空=宿主显式语言（URL locale 参数 / localeChannel 广播写入）。仅嵌入态
// 可写（applyHostLocale 值域+形态双层校验），独立访问恒 null。
let hostLocale: ResolvedLocale | null = null;
let embedMode = false;

/** 当前偏好档（模块态单一事实源，LocalePanel 渲染期直取）。MUST NOT 用
 * readLocalePreference() 做渲染期取值——它每次直读 localStorage，隐私模式
 * 等 setItem 抛错场景下模块态已切新档而存储仍是旧值（ThemePanel 注释同款
 * 纪律）。 */
export function getCurrentPreference(): LocalePreference {
  return currentPreference;
}

/** 当前生效档（resolveTarget 的模块态镜像，请求层 Accept-Language 映射取值）。 */
export function getCurrentLocaleTarget(): ResolvedLocale {
  return currentTarget;
}

/** umi setLocale 应用接线（app.tsx bootstrap 注册，生产零散点）：
 * (target) => setLocale(target, false)——不刷新页面即时生效。 */
export function registerLocaleApplier(
  applier: ((target: ResolvedLocale) => void) | null,
): void {
  applierOverride = applier;
}

/** 用户动作（LocalePanel 三档选择）：写 fenix.locale 持久化 + 即时生效。
 * `system` 档先清 umi 内建显式键（清键走浏览器判定，防闪烁脚本同构），
 * 再按浏览器归一档应用；显式档直接应用（umi setLocale 写 umi_locale）。 */
export function setLocalePreference(preference: LocalePreference): void {
  if (preference !== 'zh-CN' && preference !== 'en-US' && preference !== 'system') return;
  try {
    storage()?.setItem(LOCALE_STORAGE_KEY, preference);
  } catch {
    // 隐私模式等写失败：会话内即时生效仍成立，持久化降级
  }
  currentPreference = preference;
  if (preference === 'system') {
    try {
      storage()?.removeItem(UMI_LOCALE_STORAGE_KEY);
    } catch {
      // 清键失败与未清等价（键值随后被 apply 覆盖为归一档）
    }
  }
  const target = resolveTarget(preference);
  currentTarget = target;
  applyLocale(target);
}

/** 启动（app.tsx 根组件挂载期调用一次）：读偏好 → 解析生效档 → 幂等应用
 * （防闪烁脚本首帧前已写 umi_locale；umi setLocale 内部 getLocale()!==lang
 * 才动作，重复应用零副作用）。嵌入态先取宿主初始档（URL locale 参数，
 * embedMount 解析；i18n 宿主跟随轮）再解析应用。 */
export function initLocalePreference(): void {
  embedMode = isEmbedMode();
  hostLocale = embedMode ? embedLocaleParam() ?? null : null;
  currentPreference = readLocalePreference();
  currentTarget = resolveTarget(currentPreference);
  applyLocale(currentTarget);
}

/** 嵌入态宿主档应用（localeChannel.ts 校验后调用；值域再校验防御双层，
 * themePreference.applyHostTheme 同构）。独立访问恒 false（宿主通道不生效）；
 * 成功重解析生效档并即时应用（运行期宿主切语言实时跟随），返回 true 供
 * 通道侧测试断言。 */
export function applyHostLocale(locale: string): boolean {
  if (locale !== 'zh-CN' && locale !== 'en-US') return false;
  if (!embedMode) return false;
  hostLocale = locale;
  currentTarget = resolveTarget(currentPreference);
  applyLocale(currentTarget);
  return true;
}

/** 请求层 Accept-Language 取值（services/dashboard.ts 统一 fetch 封装消费，
 * add-framework-i18n-zh-en 6.1）：读 umi 生效档——`umi_locale` 键（umi
 * setLocale / 防闪烁脚本写）优先，缺省按偏好+浏览器归一——映射白名单前缀
 * （zh-CN→zh / en-US→en）。零 umi import（dashboard.ts 被 node 直载测试
 * 引用，'@umijs/max' 虚拟模块在 node 下不可解析，本函数即 umi getLocale 的
 * node 安全镜像）。 */
export function currentAcceptLanguage(): 'zh' | 'en' {
  let lang: string | null = null;
  try {
    lang = storage()?.getItem(UMI_LOCALE_STORAGE_KEY) ?? null;
  } catch {
    lang = null;
  }
  if (lang !== 'en-US' && lang !== 'zh-CN') lang = resolveTarget(readLocalePreference());
  return lang === 'en-US' ? 'en' : 'zh';
}

/** 测试注入口（生产零调用）：注入 storage / navigator / applier 覆盖并复位
 * 模块态。传 null 恢复读 globalThis。注血须先于 initLocalePreference() 调用。 */
export function _setLocaleEnvForTest(
  env: {
    storage?: StorageLike | null;
    languages?: (() => readonly string[]) | null;
    applier?: ((target: ResolvedLocale) => void) | null;
  } | null,
): void {
  storageOverride = env?.storage ?? null;
  languagesOverride = env?.languages ?? null;
  applierOverride = env?.applier ?? null;
  currentPreference = 'system';
  currentTarget = 'zh-CN';
  hostLocale = null;
  embedMode = false;
}
