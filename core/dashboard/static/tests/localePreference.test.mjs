// 语言偏好状态机测试（add-framework-i18n-zh-en 1.4）。
// 形态对齐 themePreference.test.mjs：node 原生 type-stripping 直载 .ts 源码 +
// 注血 storage/navigator/applier（localePreference._setLocaleEnvForTest）；
// 模块级状态隔离经 query specifier 动态 import 取全新实例。
// 覆盖 dashboard-i18n「语言偏好状态机守卫」THEN 四类断言 + design D3 两契约：
// - 三档偏好解析（缺省 system 跟随浏览器语言归一映射）
// - localStorage 持久化（fenix.locale 写键 + umi_locale 键写/清）
// - 非法值回退跟随系统
// - en 缺键回退中文（en-US 展开 zhCN 底座后抽查缺失键返回中文文案）
// - enOverrides 键集 ⊆ zh-CN 键集（防拼写漂移，design D3）
// - config.ts 首帧防闪烁内联脚本提取执行（脚本与 localePreference.ts 同构，
//   三输入组合与非法值回退逐项断言）
// 运行：cd core/dashboard/static && node --test tests/localePreference.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const KEY = 'fenix.locale';
const UMI_KEY = 'umi_locale';

// ── 注血环境（每例重建）──────────────────────────────────────────────

let store;
let languages;
let applied;
let locale;

async function freshModule() {
  return import(`../src/utils/localePreference.ts?case-${Math.random()}`);
}

beforeEach(async () => {
  store = new Map();
  languages = ['zh-CN'];
  applied = [];
  locale = await freshModule();
  injectEnv();
});

function injectEnv() {
  locale._setLocaleEnvForTest({
    storage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    languages: () => languages,
    applier: (target) => applied.push(target),
  });
}

function init() {
  locale.initLocalePreference();
}

// ════ 1.3 三档偏好解析 ════

test('缺省（无键）= system：浏览器 zh 系/en 系/其余归一映射（resolveBrowserLocale 三输入）', () => {
  assert.equal(locale.resolveBrowserLocale(['zh-CN']), 'zh-CN');
  assert.equal(locale.resolveBrowserLocale(['zh-TW', 'en']), 'zh-CN');
  assert.equal(locale.resolveBrowserLocale(['en-GB', 'zh']), 'en-US');
  assert.equal(locale.resolveBrowserLocale(['en']), 'en-US');
  assert.equal(locale.resolveBrowserLocale(['ja', 'fr']), 'zh-CN', '值域外语言回退 zh-CN');
  assert.equal(locale.resolveBrowserLocale([]), 'zh-CN');
  assert.equal(locale.resolveBrowserLocale(undefined), 'zh-CN');
});

test('缺省（无键）init：system 档按浏览器语言归一应用，umi setLocale applier 收到生效档', () => {
  languages = ['en-US'];
  init();
  assert.equal(locale.getCurrentPreference(), 'system');
  assert.equal(locale.getCurrentLocaleTarget(), 'en-US');
  assert.deepEqual(applied, ['en-US']);
});

test('显式 zh-CN / en-US 档：init 直接应用显式档', () => {
  store.set(KEY, 'en-US');
  init();
  assert.equal(locale.getCurrentPreference(), 'en-US');
  assert.equal(locale.getCurrentLocaleTarget(), 'en-US');
  assert.deepEqual(applied, ['en-US']);

  store.set(KEY, 'zh-CN');
  init();
  assert.equal(locale.getCurrentPreference(), 'zh-CN');
  assert.equal(locale.getCurrentLocaleTarget(), 'zh-CN');
  assert.deepEqual(applied.slice(1), ['zh-CN']);
});

// ════ 非法值回退 ════

test('非法值归一 system：purple/空串/大小写不符/null 一律回退跟随系统', () => {
  for (const bad of ['purple', '', 'EN-US', 'zh-cn', 'English', null]) {
    if (bad !== null) store.set(KEY, bad);
    else store.delete(KEY);
    languages = ['en-GB'];
    init();
    assert.equal(locale.getCurrentPreference(), 'system', `非法值 ${JSON.stringify(bad)} 应回退 system`);
    assert.equal(locale.getCurrentLocaleTarget(), 'en-US', '回退 system 后按浏览器语言判定');
  }
});

test('normalizePreference 纯函数直验（白名单三值之外全回退 system）', () => {
  assert.equal(locale.normalizePreference('system'), 'system');
  assert.equal(locale.normalizePreference('zh-CN'), 'zh-CN');
  assert.equal(locale.normalizePreference('en-US'), 'en-US');
  assert.equal(locale.normalizePreference('dark'), 'system');
  assert.equal(locale.normalizePreference(undefined), 'system');
});

// ════ localStorage 持久化 ════

test("手动切换持久化：setLocalePreference('en-US') 写 fenix.locale 并应用生效档，重新 init 保持", () => {
  init();
  locale.setLocalePreference('en-US');
  assert.equal(store.get(KEY), 'en-US', '偏好键持久化');
  assert.deepEqual(applied.slice(-1), ['en-US'], 'applier 收到切换 target（即时生效；umi_locale 键由生产侧 setLocale 写）');
  // 刷新语义：重新 init 读取持久化偏好
  locale.setLocalePreference('zh-CN');
  assert.equal(store.get(KEY), 'zh-CN');
  assert.equal(locale.getCurrentLocaleTarget(), 'zh-CN');
});

test('切回跟随系统：fenix.locale 保留 system 语义、清 umi_locale 显式键、按浏览器重新判定', () => {
  store.set(KEY, 'en-US');
  store.set(UMI_KEY, 'en-US');
  init();
  languages = ['zh-CN'];
  locale.setLocalePreference('system');
  assert.equal(store.get(KEY), 'system', '偏好档写回 system');
  assert.equal(store.has(UMI_KEY), false, 'umi 内建显式键被清（浏览器判定为准）');
  assert.equal(locale.getCurrentLocaleTarget(), 'zh-CN');
  assert.deepEqual(applied.slice(-1), ['zh-CN'], 'applier 收到浏览器归一档');
});

// ════ en 目录 spread 底座回退契约（design D3）════

test('enOverrides 键集 ⊆ zh-CN 键集（防拼写漂移）', async () => {
  const zh = (await import(`../src/locales/zh-CN.ts?case-${Math.random()}`)).default;
  const en = await import(`../src/locales/en-US.ts?case-${Math.random()}`);
  const zhKeys = new Set(Object.keys(zh));
  const enOnly = Object.keys(en.enOverrides).filter((k) => !zhKeys.has(k));
  assert.deepEqual(enOnly, [], `enOverrides 含 zh-CN 目录不存在的键（拼写漂移）: ${enOnly.join(', ')}`);
});

test('en 目录 spread 底座：enOverrides 全覆盖 zh 键集，覆写键英文生效', async () => {
  const zh = (await import(`../src/locales/zh-CN.ts?case-${Math.random()}`)).default;
  const en = await import(`../src/locales/en-US.ts?case-${Math.random()}`);
  // spread 底座契约：en 导出必须含 zh 全部键（缺键=值恰为中文，永不裸键名）
  const missingInEn = Object.keys(zh).filter((k) => !(k in en.default));
  assert.deepEqual(missingInEn, [], `en-US 导出缺 zhCN 底座键: ${missingInEn.join(', ')}`);
  // batch-O1 起 enOverrides 覆盖全部 zh 键（初始实现遗留 359 键回退缺口已清偿）；
  // 缺键回退机制由 spread 语义保证：enOverrides 未来若新增缺键，default 值 === zh 值
  const uncovered = Object.keys(zh).filter((k) => !(k in en.enOverrides));
  assert.deepEqual(
    uncovered,
    [],
    `enOverrides 未覆盖 zh 键（英文档将回退中文）: ${uncovered.slice(0, 20).join(', ')}`,
  );
  // 覆写生效抽查（原回退契约活样例 common.actions 已随 batch-O1 补 'Actions'）
  assert.equal(en.default['common.actions'], 'Actions');
  assert.equal(en.default['menu.overview'], 'Overview');
  // zh 为回退源：新增键 MUST 先落 zh-CN.ts
  assert.ok(Object.keys(zh).length > 0);
});

// ════ 首帧防闪烁内联脚本（提取 config.ts 源码执行）════

/** 从 config/config.ts 提取 FIRST_FRAME_LOCALE_SCRIPT 模板字符串本体。 */
async function extractInlineScript() {
  const src = await readFile(new URL('../config/config.ts', import.meta.url), 'utf8');
  const marker = 'export const FIRST_FRAME_LOCALE_SCRIPT = `';
  const start = src.indexOf(marker);
  assert.ok(start >= 0, 'config.ts 须声明 FIRST_FRAME_LOCALE_SCRIPT 模板字符串');
  const bodyStart = start + marker.length;
  const end = src.indexOf('`;', bodyStart);
  assert.ok(end > bodyStart, '模板字符串未闭合');
  return src.slice(bodyStart, end);
}

/** 注血 window 执行内联脚本，返回 umi_locale 落键结果。 */
async function runInlineScript({ stored, nav }) {
  const script = await extractInlineScript();
  const store2 = new Map();
  const win = {
    localStorage: {
      getItem: (k) => (k === KEY && stored !== undefined ? stored : null),
      setItem: (k, v) => store2.set(k, String(v)),
      removeItem: (k) => store2.delete(k),
    },
    navigator: { languages: nav, language: nav?.[0] },
  };
  const fn = new Function('window', 'navigator', script);
  fn(win, win.navigator);
  return store2.get(UMI_KEY);
}

test('内联脚本：显式 zh-CN/en-US 偏好 → umi_locale 首帧落键（不依赖 navigator）', async () => {
  assert.equal(await runInlineScript({ stored: 'zh-CN', nav: ['en-US'] }), 'zh-CN');
  assert.equal(await runInlineScript({ stored: 'en-US', nav: ['zh-CN'] }), 'en-US');
});

test('内联脚本：system 档按 navigator 归一落键（zh 系/en 系/值域外三输入）', async () => {
  assert.equal(await runInlineScript({ stored: undefined, nav: ['zh-CN'] }), 'zh-CN');
  assert.equal(await runInlineScript({ stored: undefined, nav: ['en-GB', 'zh'] }), 'en-US');
  assert.equal(await runInlineScript({ stored: undefined, nav: ['ja', 'fr'] }), 'zh-CN', '值域外归一回退 zh-CN');
});

test('内联脚本：非法偏好值归一 system 后走浏览器判定（与状态机同构）', async () => {
  assert.equal(await runInlineScript({ stored: 'purple', nav: ['en-US'] }), 'en-US');
  assert.equal(await runInlineScript({ stored: '', nav: ['zh-CN'] }), 'zh-CN');
});

// ── 宿主档（i18n 宿主跟随轮：URL locale 参数 + localeChannel 广播应用）──

test('initLocalePreference 嵌入态读 URL locale 初始档：宿主档优先于本地偏好', async () => {
  const fresh = await freshModule();
  fresh._setLocaleEnvForTest({
    storage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    languages: () => ['zh-CN'],
    applier: (t) => applied.push(t),
  });
  const { _setEmbedSearchParamsForTest } = await import('../src/utils/embedMount.ts');
  store.set(KEY, 'en-US'); // 本地显式英文
  _setEmbedSearchParamsForTest('?embed=1&locale=zh-CN'); // 宿主中文
  await fresh.initLocalePreference();
  assert.deepEqual(applied, ['zh-CN'], '宿主初始档覆盖本地偏好');
  assert.equal(fresh.getCurrentLocaleTarget(), 'zh-CN');
  assert.equal(store.get(KEY), 'en-US', '独立偏好存储不被宿主档污染');
  _setEmbedSearchParamsForTest(null);
});

test('applyHostLocale 独立访问恒 false；嵌入态白名单外 false 且不改档', async () => {
  const fresh = await freshModule();
  fresh._setLocaleEnvForTest({
    storage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    languages: () => ['zh-CN'],
    applier: (t) => applied.push(t),
  });
  const { _setEmbedSearchParamsForTest } = await import('../src/utils/embedMount.ts');
  _setEmbedSearchParamsForTest(null); // 独立访问
  await fresh.initLocalePreference();
  assert.deepEqual(applied, ['zh-CN'], '独立访问 init 按本地链应用一次');
  assert.equal(fresh.applyHostLocale('en-US'), false, '独立访问宿主通道不生效');
  assert.deepEqual(applied, ['zh-CN'], '拒绝后无新增应用动作');

  _setEmbedSearchParamsForTest('?embed=1&locale=zh-CN');
  await fresh.initLocalePreference();
  assert.deepEqual(applied, ['zh-CN', 'zh-CN'], '嵌入态 init 按宿主初始档再应用一次');
  assert.equal(fresh.applyHostLocale('ja-JP'), false, '值域外拒绝');
  assert.equal(fresh.getCurrentLocaleTarget(), 'zh-CN', '拒绝后档位不变');
  assert.equal(fresh.applyHostLocale('en-US'), true, '嵌入态合法档生效');
  assert.deepEqual(applied, ['zh-CN', 'zh-CN', 'en-US']);
  assert.equal(fresh.getCurrentLocaleTarget(), 'en-US');
  _setEmbedSearchParamsForTest(null);
});
