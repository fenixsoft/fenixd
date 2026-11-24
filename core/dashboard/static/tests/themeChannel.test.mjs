// 嵌入态主题 postMessage 通道测试（dashboard-dark-theme 2.2）。
// node 直载 .ts 源码 + 注血：embedMount._setEmbedSearchParamsForTest 定嵌入态、
// 伪 window 捕获 message 监听器、themePreference._setThemeEnvForTest 注血
// storage/matchMedia——合法切换、非法值忽略、非 parent 来源忽略逐项断言。
// 运行：cd core/dashboard/static && node --test tests/themeChannel.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { _setEmbedSearchParamsForTest } from '../src/utils/embedMount.ts';
import { THEME_MESSAGE_KIND, isValidThemeMessage, startThemeChannel } from '../src/utils/themeChannel.ts';

// ── 注血环境 ──────────────────────────────────────────────────────────

let handlers;      // 伪 window 已挂的 message 监听器集合
let removed;       // 已拆监听器集合
let store;         // localStorage 注血
let mediaDark;
let docAttrs;

beforeEach(async () => {
  handlers = new Set();
  removed = new Set();
  store = new Map();
  mediaDark = false;
  docAttrs = new Map();
  globalThis.document = {
    documentElement: { setAttribute: (k, v) => docAttrs.set(k, v) },
  };
  const { _setThemeEnvForTest } = await import('../src/utils/themePreference.ts');
  _setThemeEnvForTest({
    storage: {
      getItem: (k) => store.get(k) ?? null,
      setItem: (k, v) => store.set(k, v),
    },
    matchMedia: () => ({ matches: mediaDark, addEventListener() {}, removeEventListener() {} }),
  });
  globalThis.window = {
    parent: { marker: 'parent-window' },
    addEventListener: (type, listener) => {
      if (type === 'message') handlers.add(listener);
    },
    removeEventListener: (type, listener) => {
      if (type === 'message') {
        handlers.delete(listener);
        removed.add(listener);
      }
    },
  };
  _setEmbedSearchParamsForTest(null);
});

// 启动通道 + 主题状态机（嵌入态）；返回发送伪造消息的助手。
async function startEmbedded(search = '?embed=1') {
  const { initThemePreference } = await import('../src/utils/themePreference.ts');
  _setEmbedSearchParamsForTest(search);
  initThemePreference();
  const dispose = startThemeChannel();
  const send = (data, source = globalThis.window.parent) =>
    [...handlers].forEach((h) => h({ data, source }));
  return { dispose, send };
}

test('kind 常量：fenix-dashboard:theme（双仓镜像值，桥接侧字面量须逐字节一致）', () => {
  assert.equal(THEME_MESSAGE_KIND, 'fenix-dashboard:theme');
});

test('独立访问零监听：startThemeChannel 即返 noop，window 不挂 message', () => {
  _setEmbedSearchParamsForTest(null); // 非 embed
  const dispose = startThemeChannel();
  assert.equal(handlers.size, 0, '独立访问 MUST NOT 挂监听');
  dispose(); // noop 可安全调用
});

test('合法切换：宿主消息 {kind, theme} 即时生效，无需刷新', async () => {
  const { send } = await startEmbedded();
  assert.equal(docAttrs.get('data-fenix-theme'), 'light'); // 初始独立逻辑=浅色
  send({ kind: THEME_MESSAGE_KIND, theme: 'dark' });
  const { getCurrentScheme } = await import('../src/utils/themePreference.ts');
  assert.equal(getCurrentScheme(), 'dark');
  assert.equal(docAttrs.get('data-fenix-theme'), 'dark');
  send({ kind: THEME_MESSAGE_KIND, theme: 'light' });
  assert.equal(getCurrentScheme(), 'light');
});

test('宿主档不写 localStorage：切换后独立偏好零污染', async () => {
  const { send } = await startEmbedded('?embed=1&theme=light');
  send({ kind: THEME_MESSAGE_KIND, theme: 'dark' });
  assert.equal(store.has('fenix.theme'), false, '嵌入态 MUST NOT 写 localStorage');
});

test('非法值忽略：theme=purple 消息被忽略且控制台无错误（静默）', async () => {
  const { send } = await startEmbedded('?embed=1&theme=light');
  const { getCurrentScheme } = await import('../src/utils/themePreference.ts');
  send({ kind: THEME_MESSAGE_KIND, theme: 'purple' });
  assert.equal(getCurrentScheme(), 'light', '值域外消息不改档');
  send({ kind: THEME_MESSAGE_KIND, theme: null });
  assert.equal(getCurrentScheme(), 'light');
  send({ kind: 'fenix-dashboard:other', theme: 'dark' });
  assert.equal(getCurrentScheme(), 'light', 'kind 白名单外消息不改档');
  send('fenix-dashboard:theme'); // 非 object 载荷
  assert.equal(getCurrentScheme(), 'light');
  send(null);
  assert.equal(getCurrentScheme(), 'light');
});

test('非 parent 来源忽略：同页其它 iframe/窗口伪造的消息不生效', async () => {
  const { send } = await startEmbedded('?embed=1&theme=light');
  const { getCurrentScheme } = await import('../src/utils/themePreference.ts');
  const fakeSource = { marker: 'sibling-iframe' };
  send({ kind: THEME_MESSAGE_KIND, theme: 'dark' }, fakeSource);
  assert.equal(getCurrentScheme(), 'light', '来源非 window.parent 的消息 MUST 被忽略');
  send({ kind: THEME_MESSAGE_KIND, theme: 'dark' }, null);
  assert.equal(getCurrentScheme(), 'light');
});

test('isValidThemeMessage：合法形状判定与白名单边界', () => {
  assert.equal(isValidThemeMessage({ kind: THEME_MESSAGE_KIND, theme: 'dark' }), true);
  assert.equal(isValidThemeMessage({ kind: THEME_MESSAGE_KIND, theme: 'light' }), true);
  assert.equal(isValidThemeMessage({ kind: THEME_MESSAGE_KIND, theme: 'purple' }), false);
  assert.equal(isValidThemeMessage({ kind: 'other', theme: 'dark' }), false);
  assert.equal(isValidThemeMessage({}), false);
  assert.equal(isValidThemeMessage(null), false);
  assert.equal(isValidThemeMessage('dark'), false);
});

test('disposer 拆监听：卸载后消息不再生效（React 生命周期对称清理）', async () => {
  const { dispose, send } = await startEmbedded();
  assert.equal(handlers.size, 1);
  dispose();
  assert.equal(removed.size, 1, 'disposer 须拆除监听器');
  send({ kind: THEME_MESSAGE_KIND, theme: 'dark' });
  const { getCurrentScheme } = await import('../src/utils/themePreference.ts');
  assert.equal(getCurrentScheme(), 'light', '拆监听后消息不再生效');
});
