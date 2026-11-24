// 主题偏好状态机测试（dashboard-dark-theme 1.2/1.3）。
// 形态沿用 embedMount.test.mjs 先例：node 原生 type-stripping 直载 .ts 源码 +
// 注血 storage/matchMedia（themePreference._setThemeEnvForTest）；模块级状态
// 隔离经 query specifier 动态 import 取全新实例。
// 另含两段契约测试：
// - config.ts 首帧防闪烁内联脚本提取执行（1.3：脚本与 themePreference.ts
//   同构，三输入组合与非法值回退逐项断言）；
// - theme.ts 深色档守卫（毛玻璃 soft 染色族深档通道一致 + alpha<1；浅色档
//   逐字节锚点=浅色零回退）。
// 运行：cd core/dashboard/static && node --test tests/themePreference.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const KEY = 'fenix.theme';

// ── 注血环境（每例重建）──────────────────────────────────────────────

let store;
let mediaDark;
let mediaListeners;
let docAttrs;
let theme;

async function freshModule() {
  return import(`../src/utils/themePreference.ts?case-${Math.random()}`);
}

beforeEach(async () => {
  store = new Map();
  mediaDark = false;
  mediaListeners = new Set();
  docAttrs = new Map();
  globalThis.document = {
    documentElement: {
      setAttribute: (k, v) => docAttrs.set(k, v),
      getAttribute: (k) => docAttrs.get(k) ?? null,
    },
  };
  theme = await freshModule();
  injectEnv();
});

function injectEnv() {
  theme._setThemeEnvForTest({
    storage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
    },
    matchMedia: () => ({
      matches: mediaDark,
      addEventListener: (_t, cb) => mediaListeners.add(cb),
      removeEventListener: (_t, cb) => mediaListeners.delete(cb),
    }),
  });
}

function init() {
  const dispose = theme.initThemePreference();
  return dispose;
}

// ════ 1.2 三档偏好读写与缺省解析 ════

test('缺省（无键）= system：系统浅色呈浅色、系统深色呈深色（跟随 prefers-color-scheme）', () => {
  mediaDark = false;
  init();
  assert.equal(theme.getCurrentScheme(), 'light');
  assert.equal(docAttrs.get('data-fenix-theme'), 'light');
  mediaDark = true;
  const dispose = init();
  assert.equal(theme.getCurrentScheme(), 'dark');
  assert.equal(docAttrs.get('data-fenix-theme'), 'dark');
  dispose();
});

test('非法值归一 system：purple/空串/大小写不符一律回退跟随系统', () => {
  for (const bad of ['purple', '', 'DARK', 'Light', null]) {
    if (bad !== null) store.set(KEY, bad);
    else store.delete(KEY);
    mediaDark = true;
    const dispose = init();
    assert.equal(theme.getCurrentScheme(), 'dark', `非法值 ${JSON.stringify(bad)} 应回退 system`);
    dispose();
  }
});

test('手动深色持久化：写入 fenix.theme=dark，刷新（重新 init）后仍为深色', () => {
  mediaDark = false;
  const dispose = init();
  theme.setThemePreference('dark');
  assert.equal(theme.getCurrentScheme(), 'dark');
  assert.equal(store.get(KEY), 'dark');
  dispose();
  // 模拟刷新：模块态复位 + 重新 init（mediaDark=false 挡住「跟随系统」解释）
  theme._setThemeEnvForTest(null);
  injectEnv();
  const dispose2 = init();
  assert.equal(theme.getCurrentScheme(), 'dark', '持久化偏好应压过系统浅色');
  dispose2();
});

test('手动浅色覆盖系统深色：fenix.theme=light 且不随系统外观变化', () => {
  mediaDark = true;
  const dispose = init();
  theme.setThemePreference('light');
  assert.equal(theme.getCurrentScheme(), 'light');
  assert.equal(store.get(KEY), 'light');
  // 系统切回浅色/深色都不再影响显式档
  mediaDark = false;
  for (const cb of mediaListeners) cb();
  assert.equal(theme.getCurrentScheme(), 'light', '显式档 MUST NOT 跟随系统翻转');
  dispose();
});

test('system 档实时切换：系统外观翻转经 matchMedia change 即时跟随', () => {
  mediaDark = false;
  init();
  assert.equal(theme.getCurrentScheme(), 'light');
  mediaDark = true;
  assert.ok(mediaListeners.size > 0, 'system 档应挂 matchMedia 监听');
  for (const cb of mediaListeners) cb();
  assert.equal(theme.getCurrentScheme(), 'dark');
  assert.equal(docAttrs.get('data-fenix-theme'), 'dark');
});

test('监听对称清理：显式档/ dispose 后 media 监听拆除（防泄漏）', () => {
  mediaDark = false;
  init();
  assert.ok(mediaListeners.size > 0);
  theme.setThemePreference('dark'); // 显式档：监听拆除
  assert.equal(mediaListeners.size, 0);
  store.delete(KEY); // 复位为缺省 system：重新 init 应重挂监听
  const dispose = init();
  assert.ok(mediaListeners.size > 0);
  dispose(); // 卸载清理
  assert.equal(mediaListeners.size, 0);
});

// ════ 1.2 文档根应用 ════

test('data-fenix-theme 随档位写入/更新 documentElement', () => {
  mediaDark = false;
  init();
  assert.equal(docAttrs.get('data-fenix-theme'), 'light');
  theme.setThemePreference('dark');
  assert.equal(docAttrs.get('data-fenix-theme'), 'dark');
});

// ════ 嵌入态（宿主优先，不污染独立偏好）════

test('嵌入 + theme=dark：宿主档生效且不读 localStorage（独立 dark 偏好不被采用）', async () => {
  const { _setEmbedSearchParamsForTest } = await import('../src/utils/embedMount.ts');
  _setEmbedSearchParamsForTest('?embed=1&apiBase=/p&theme=dark');
  try {
    store.set(KEY, 'light'); // 独立偏好 light：宿主档 dark 必须优先
    init();
    assert.equal(theme.getCurrentScheme(), 'dark');
    assert.equal(docAttrs.get('data-fenix-theme'), 'dark');
    assert.equal(theme.isEmbedTheme(), true);
  } finally {
    _setEmbedSearchParamsForTest(null);
  }
});

test('嵌入 + theme=light：呈现浅色且 localStorage 不被写入（独立偏好不被污染）', async () => {
  const { _setEmbedSearchParamsForTest } = await import('../src/utils/embedMount.ts');
  _setEmbedSearchParamsForTest('?embed=1&theme=light');
  try {
    mediaDark = true; // 系统深色：宿主浅色优先
    init();
    assert.equal(theme.getCurrentScheme(), 'light');
    theme.setThemePreference('dark'); // 嵌入态写入被忽略（不写 localStorage）
    assert.equal(store.has(KEY), false, '嵌入态 MUST NOT 写 localStorage');
    assert.equal(theme.getCurrentScheme(), 'light');
  } finally {
    _setEmbedSearchParamsForTest(null);
  }
});

test('嵌入无 theme 参数：回退独立主题逻辑（读 localStorage）——embed-mount 缺省语义', async () => {
  const { _setEmbedSearchParamsForTest } = await import('../src/utils/embedMount.ts');
  _setEmbedSearchParamsForTest('?embed=1&apiBase=/p');
  try {
    store.set(KEY, 'dark');
    mediaDark = false;
    init();
    assert.equal(theme.getCurrentScheme(), 'dark', '宿主未注入时应按独立逻辑解析');
  } finally {
    _setEmbedSearchParamsForTest(null);
  }
});

test('applyHostTheme：值域外/非嵌入拒绝；嵌入态合法值即时生效', async () => {
  const { _setEmbedSearchParamsForTest } = await import('../src/utils/embedMount.ts');
  mediaDark = false;
  const dispose = init();
  assert.equal(theme.applyHostTheme('dark'), false, '非嵌入态宿主通道不生效');
  assert.equal(theme.applyHostTheme('purple'), false, '值域白名单外拒绝');
  assert.equal(theme.getCurrentScheme(), 'light');
  _setEmbedSearchParamsForTest('?embed=1');
  try {
    theme._setThemeEnvForTest(null);
    injectEnv();
    init();
    assert.equal(theme.applyHostTheme('dark'), true);
    assert.equal(theme.getCurrentScheme(), 'dark');
    assert.equal(theme.applyHostTheme('purple'), false, '运行期值域校验');
    assert.equal(theme.getCurrentScheme(), 'dark', '非法消息不改档');
  } finally {
    _setEmbedSearchParamsForTest(null);
    dispose();
  }
});

// ════ 1.3 首帧防闪烁内联脚本（提取 config.ts 源码执行）════

/** 从 config/config.ts 提取 FIRST_FRAME_THEME_SCRIPT 模板字符串本体。 */
async function extractInlineScript() {
  const src = await readFile(new URL('../config/config.ts', import.meta.url), 'utf8');
  const marker = "export const FIRST_FRAME_THEME_SCRIPT = `";
  const start = src.indexOf(marker);
  assert.ok(start >= 0, 'config.ts 须声明 FIRST_FRAME_THEME_SCRIPT 模板字符串');
  const bodyStart = start + marker.length;
  const end = src.indexOf('`;', bodyStart);
  assert.ok(end > bodyStart, '模板字符串未闭合');
  return src.slice(bodyStart, end);
}

/** 注血 window/document 执行内联脚本，返回写入的 data-fenix-theme。 */
async function runInlineScript({ search = '', stored = undefined, systemDark = false, withMatchMedia = true }) {
  const script = await extractInlineScript();
  const attrs = new Map();
  const win = {
    location: { search },
    localStorage: {
      getItem: (k) => (k === KEY && stored !== undefined ? stored : null),
      setItem: () => {},
    },
    matchMedia: withMatchMedia
      ? (q) => ({ matches: q === '(prefers-color-scheme: dark)' ? systemDark : false, addEventListener() {}, removeEventListener() {} })
      : undefined,
  };
  const fn = new Function('window', 'document', script);
  fn(win, { documentElement: { setAttribute: (k, v) => attrs.set(k, v) } });
  return attrs.get('data-fenix-theme');
}

test('内联脚本：localStorage 深色偏好 → 首帧即深（不依赖系统外观）', async () => {
  assert.equal(await runInlineScript({ stored: 'dark', systemDark: false }), 'dark');
  assert.equal(await runInlineScript({ stored: 'dark', systemDark: true }), 'dark');
});

test('内联脚本：system 档（含缺省无键）跟随 prefers-color-scheme', async () => {
  assert.equal(await runInlineScript({ stored: undefined, systemDark: true }), 'dark');
  assert.equal(await runInlineScript({ stored: undefined, systemDark: false }), 'light');
  assert.equal(await runInlineScript({ stored: 'system', systemDark: true }), 'dark');
});

test('内联脚本：非法偏好值回退 system（跟随系统）', async () => {
  assert.equal(await runInlineScript({ stored: 'purple', systemDark: true }), 'dark');
  assert.equal(await runInlineScript({ stored: 'purple', systemDark: false }), 'light');
});

test('内联脚本：embed=1&theme=dark 首帧即深；theme=purple 回退独立逻辑', async () => {
  assert.equal(await runInlineScript({ search: '?embed=1&apiBase=/p&theme=dark', stored: 'light' }), 'dark');
  assert.equal(await runInlineScript({ search: '?embed=1&theme=light', stored: 'dark' }), 'light');
  // 非法值：宿主视为未注入 → 读 localStorage（独立逻辑）
  assert.equal(await runInlineScript({ search: '?embed=1&theme=purple', stored: 'dark' }), 'dark');
  assert.equal(await runInlineScript({ search: '?embed=1', stored: undefined, systemDark: true }), 'dark');
});

test('内联脚本：无 matchMedia（极端环境）system 档按浅色，行为与无脚本一致', async () => {
  assert.equal(await runInlineScript({ stored: undefined, withMatchMedia: false }), 'light');
});

// ════ theme.ts 深色档守卫（D2 表落值 + soft 染色族深档同源共改）════

test('theme.ts 深色档：D2 关键落值锚点（背景层/主文字/链接/错误/主色反转）', async () => {
  const t = await import('../src/theme.ts');
  assert.equal(t.DSH_BG_BASE_DARK, '#151517');
  assert.equal(t.DSH_BG_ELEVATED_DARK, '#232324');
  assert.equal(t.DSH_BG_SOFT_DARK, '#2c2c2e');
  assert.equal(t.DSH_BG_MODULE_DARK, '#353638');
  assert.equal(t.DSH_TEXT_DARK, '#f9fafb');
  assert.equal(t.DSH_TEXT_SECONDARY_DARK, '#cfd3d6');
  assert.equal(t.DSH_LINK_DARK, '#7aaaff');
  assert.equal(t.DSH_ERROR_DARK, '#f25a5a');
  assert.equal(t.DSH_PRIMARY_DARK, '#f9fafb', '黑主色→白主色反转');
  assert.equal(t.OV_HAIRLINE_DARK, '#2e2f31');
  assert.equal(t.MARKDOWN_CODE_BLOCK_DARK, '#1b1b1c');
});

test('theme.ts 深色档毛玻璃守卫：soft 染色族通道一致且 alpha<1（回实底即静默失效）', async () => {
  const t = await import('../src/theme.ts');
  const hexChannels = (hex) => {
    assert.match(hex, /^#[0-9a-f]{6}$/, `深档 soft 须为 hex：${hex}`);
    const n = hex.slice(1);
    return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16)];
  };
  const soft = hexChannels(t.DSH_BG_SOFT_DARK);
  const channels = (v) => {
    const m = v.match(/^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$/);
    assert.ok(m, `玻璃值须为 rgba() 形态：${v}`);
    return { rgb: [Number(m[1]), Number(m[2]), Number(m[3])], alpha: Number(m[4]) };
  };
  for (const glass of [t.DSH_BG_SOFT_GLASS_DARK, t.DSH_HEADER_GLASS_DARK, t.DSH_HEADER_GLASS_SCROLL_DARK]) {
    const c = channels(glass);
    assert.deepEqual(c.rgb, soft, `玻璃值 rgb 通道须与深档 DSH_BG_SOFT 一致：${glass}`);
    assert.ok(c.alpha < 1, `玻璃值须保留透明度（毛玻璃生效前提）：${glass}`);
  }
});

test('theme.ts 浅色档零回退：既有常量逐字节锚点（浅色为缺省渲染结果）', async () => {
  const t = await import('../src/theme.ts');
  assert.equal(t.DSH_PRIMARY, '#0f1115');
  assert.equal(t.DSH_TEXT, '#0f1115');
  assert.equal(t.DSH_BG_SOFT, '#f9fafb');
  assert.equal(t.DSH_BG_SOFT_GLASS, 'rgba(249, 250, 251, 0.6)');
  assert.equal(t.DSH_HEADER_GLASS, 'rgba(249, 250, 251, 0.4)');
  assert.equal(t.DSH_HEADER_GLASS_SCROLL, 'rgba(249, 250, 251, 0.8)');
  assert.equal(t.DSH_LINK, '#4176e6');
  assert.equal(t.DSH_MENU_SELECTED_BG, 'rgba(0, 0, 0, 0.04)');
  assert.equal(t.DSH_LIGHT.bgBase, '#ffffff');
  // 浅色缺省档：dshThemeConfig('light') 返回既有对象引用（行为与现状一致）
  const lightConfig = t.dshThemeConfig('light', null);
  assert.equal(lightConfig, t.dshAlignedTheme);
  // 深色档：algorithm 注入槽位在（app.tsx 传 theme.darkAlgorithm）
  assert.deepEqual(Object.keys(t.dshThemeConfig('dark', {})).sort(), ['algorithm', 'components', 'token']);
});
