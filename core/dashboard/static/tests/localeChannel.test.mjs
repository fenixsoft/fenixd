// 嵌入态语言 postMessage 通道测试（i18n 宿主跟随轮）。
// 结构镜像 themeChannel.test.mjs（dashboard-dark-theme 2.2 同款处方）：
// node 直载 .ts 源码 + 注血：embedMount._setEmbedSearchParamsForTest 定嵌入态、
// 伪 window 捕获 message 监听器、localePreference._setLocaleEnvForTest 注血
// storage/applier——合法切换、非法值忽略、非 parent 来源忽略逐项断言。
// 运行：cd core/dashboard/static && node --test tests/localeChannel.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { _setEmbedSearchParamsForTest } from '../src/utils/embedMount.ts';
import { LOCALE_MESSAGE_KIND, isValidLocaleMessage, startLocaleChannel } from '../src/utils/localeChannel.ts';

// ── 注血环境 ──────────────────────────────────────────────────────────

let handlers;      // 伪 window 已挂的 message 监听器集合
let removed;       // 已拆监听器集合
let store;         // localStorage 注血
let applied;       // applier 捕获的生效档序列

beforeEach(async () => {
  handlers = new Set();
  removed = new Set();
  store = new Map();
  applied = [];
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
  const { _setLocaleEnvForTest } = await import('../src/utils/localePreference.ts');
  _setLocaleEnvForTest({
    storage: {
      getItem: (k) => store.get(k) ?? null,
      setItem: (k, v) => store.set(k, v),
      removeItem: (k) => store.delete(k),
    },
    applier: (target) => applied.push(target),
  });
  _setEmbedSearchParamsForTest(null);
});

// 启动通道 + 语言状态机（嵌入态）；返回发送伪造消息的助手。
async function startEmbedded(search = '?embed=1') {
  const { initLocalePreference } = await import('../src/utils/localePreference.ts');
  _setEmbedSearchParamsForTest(search);
  initLocalePreference();
  const dispose = startLocaleChannel();
  const send = (data, source = globalThis.window.parent) =>
    [...handlers].forEach((h) => h({ data, source }));
  return { dispose, send };
}

test('kind 常量：fenix-locale（双仓镜像值，桥接侧字面量须逐字节一致）', () => {
  assert.equal(LOCALE_MESSAGE_KIND, 'fenix-locale');
});

test('isValidLocaleMessage：合法形状 true，kind 不符/locale 出域/非对象 false', () => {
  assert.equal(isValidLocaleMessage({ kind: LOCALE_MESSAGE_KIND, locale: 'zh-CN' }), true);
  assert.equal(isValidLocaleMessage({ kind: LOCALE_MESSAGE_KIND, locale: 'en-US' }), true);
  assert.equal(isValidLocaleMessage({ kind: 'fenix-locale:other', locale: 'zh-CN' }), false);
  assert.equal(isValidLocaleMessage({ kind: LOCALE_MESSAGE_KIND, locale: 'ja-JP' }), false);
  assert.equal(isValidLocaleMessage({ kind: LOCALE_MESSAGE_KIND, locale: null }), false);
  assert.equal(isValidLocaleMessage(LOCALE_MESSAGE_KIND), false);
  assert.equal(isValidLocaleMessage(null), false);
});

test('独立访问零监听：startLocaleChannel 即返 noop，window 不挂 message', () => {
  _setEmbedSearchParamsForTest(null); // 非 embed
  const dispose = startLocaleChannel();
  assert.equal(handlers.size, 0, '独立访问 MUST NOT 挂监听');
  dispose(); // noop 可安全调用
});

test('合法切换：宿主消息 {kind, locale} 即时生效（zh-CN/en-US 双向），无需刷新', async () => {
  const { send } = await startEmbedded('?embed=1&locale=en-US');
  // 初始档来自 URL locale 参数（embedLocaleParam）
  assert.deepEqual(applied, ['en-US'], '初始注入档 en-US 已应用');
  send({ kind: LOCALE_MESSAGE_KIND, locale: 'zh-CN' });
  assert.deepEqual(applied, ['en-US', 'zh-CN']);
  send({ kind: LOCALE_MESSAGE_KIND, locale: 'en-US' });
  assert.deepEqual(applied, ['en-US', 'zh-CN', 'en-US']);
});

test('宿主档优先于本地偏好：fenix.locale=en-US 下宿主 zh-CN 仍生效且不写存储', async () => {
  store.set('fenix.locale', 'en-US'); // 本地显式英文偏好
  const { send } = await startEmbedded('?embed=1');
  assert.deepEqual(applied, ['en-US'], '宿主未注入时本地偏好生效');
  send({ kind: LOCALE_MESSAGE_KIND, locale: 'zh-CN' });
  assert.deepEqual(applied, ['en-US', 'zh-CN'], '宿主显式语言覆盖本地偏好');
  assert.equal(store.has('fenix.locale'), true, '本地偏好存储保留（不污染）');
  assert.equal(store.has('umi_locale'), false, '宿主档不写 umi 内建键');
});

test('非法值忽略：locale=ja-JP / kind 白名单外 / 非对象载荷（静默）', async () => {
  const { send } = await startEmbedded('?embed=1&locale=zh-CN');
  send({ kind: LOCALE_MESSAGE_KIND, locale: 'ja-JP' });
  send({ kind: 'fenix-locale:other', locale: 'en-US' });
  send('fenix-locale');
  send(null);
  assert.deepEqual(applied, ['zh-CN'], '值域外/白名单外消息不改档');
});

test('非 parent 来源忽略：同页其它 iframe/窗口伪造的消息不生效', async () => {
  const { send } = await startEmbedded('?embed=1&locale=zh-CN');
  const fakeSource = { marker: 'sibling-iframe' };
  send({ kind: LOCALE_MESSAGE_KIND, locale: 'en-US' }, fakeSource);
  assert.deepEqual(applied, ['zh-CN'], '来源非 window.parent 的消息 MUST 被忽略');
});

test('disposer 对称拆监听：dispose 后消息不再生效', async () => {
  const { dispose, send } = await startEmbedded('?embed=1&locale=zh-CN');
  const listener = [...handlers][0];
  dispose();
  assert.equal(handlers.size, 0);
  assert.equal(removed.has(listener), true, 'disposer 拆除已挂监听器');
  send({ kind: LOCALE_MESSAGE_KIND, locale: 'en-US' });
  assert.deepEqual(applied, ['zh-CN'], 'dispose 后消息不生效');
});
