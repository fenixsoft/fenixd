// 嵌入挂载启动参数单点测试（add-dashboard-embed-mode 3.1/3.2/3.3）。
// 形态沿用 etagCache.test.mjs 先例：node 原生 type-stripping 直载 .ts 源码 +
// mock globalThis.fetch。前缀化场景以「先注血（globalThis.location / 测试注入口）
// 后动态 import」覆盖 import 期求值的 STREAM_URL（模块缓存经 query specifier
// 绕开，得到全新模块实例）。
// 运行：cd core/dashboard/static && node --test tests/embedMount.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  withApiBase,
  isEmbedMode,
  _setEmbedSearchParamsForTest,
} from '../src/utils/embedMount.ts';
import {
  getOverview,
  getAlerts,
  clearAllAlerts,
  architectureDiagramUrl,
  _clearEtagCache,
  STREAM_URL as STREAM_URL_DEFAULT,
} from '../src/services/dashboard.ts';

// ── fetch mock：记录每次调用 URL，按脚本队列回放响应（etagCache.test.mjs 同款）──

let calls = [];
let responses = [];

function mockFetch(url) {
  calls.push({ url });
  const spec = responses.length > 1 ? responses.shift() : responses[0];
  if (!spec) throw new Error('mock fetch: 响应队列已空');
  if (spec.fail) return Promise.reject(spec.fail);
  return Promise.resolve({
    ok: spec.status >= 200 && spec.status < 300,
    status: spec.status,
    headers: { get: () => null },
    text: async () => spec.body ?? '',
  });
}

beforeEach(() => {
  calls = [];
  responses = [{ status: 200, body: '{"ok":true}' }];
  globalThis.fetch = mockFetch;
  _clearEtagCache();
  _setEmbedSearchParamsForTest(null);
});

// ════ 3.1 参数解析与拼接 ════

test('withApiBase：apiBase 缺省恒等返回（逐字节不变）', () => {
  _setEmbedSearchParamsForTest(null); // 无 location（node 缺省）= 无参数启动
  assert.equal(withApiBase('/api/overview'), '/api/overview');
  assert.equal(withApiBase('/api/stream'), '/api/stream');
  assert.equal(withApiBase('api/rel'), 'api/rel');
  assert.equal(withApiBase(''), '');
});

test('withApiBase：前缀拼接 + 尾部多斜杠归一', () => {
  _setEmbedSearchParamsForTest('?apiBase=/fenix-dashboard');
  assert.equal(withApiBase('/api/stream'), '/fenix-dashboard/api/stream');
  assert.equal(withApiBase('/api/architecture/diagram?p=1'), '/fenix-dashboard/api/architecture/diagram?p=1');
  // base 尾部斜杠归一：不产生双斜杠
  _setEmbedSearchParamsForTest('?apiBase=/fenix-dashboard/');
  assert.equal(withApiBase('/api/stream'), '/fenix-dashboard/api/stream');
  _setEmbedSearchParamsForTest('?apiBase=/fenix-dashboard//');
  assert.equal(withApiBase('/api/stream'), '/fenix-dashboard/api/stream');
  // 仅 '/' 的 base 归一后为空 = 恒等
  _setEmbedSearchParamsForTest('?apiBase=/');
  assert.equal(withApiBase('/api/stream'), '/api/stream');
  // path 缺头斜杠时补齐
  _setEmbedSearchParamsForTest('?apiBase=/fenix-dashboard');
  assert.equal(withApiBase('api/x'), '/fenix-dashboard/api/x');
});

test('isEmbedMode：embed=1 判定嵌入，缺省/embed=0 为独立访问', () => {
  _setEmbedSearchParamsForTest(null);
  assert.equal(isEmbedMode(), false);
  _setEmbedSearchParamsForTest('?embed=1');
  assert.equal(isEmbedMode(), true);
  _setEmbedSearchParamsForTest('?embed=0');
  assert.equal(isEmbedMode(), false);
  _setEmbedSearchParamsForTest('?embed=true'); // 仅字面 '1' 生效
  assert.equal(isEmbedMode(), false);
});

test('两参数组合互不干扰：embed 只管壳层、apiBase 只管前缀', () => {
  _setEmbedSearchParamsForTest('?embed=1&apiBase=/fenix-dashboard');
  assert.equal(isEmbedMode(), true);
  assert.equal(withApiBase('/api/overview'), '/fenix-dashboard/api/overview');
  // 只有 apiBase：不进嵌入形态
  _setEmbedSearchParamsForTest('?apiBase=/fenix-dashboard');
  assert.equal(isEmbedMode(), false);
  assert.equal(withApiBase('/api/overview'), '/fenix-dashboard/api/overview');
  // 只有 embed：无前缀
  _setEmbedSearchParamsForTest('?embed=1');
  assert.equal(isEmbedMode(), true);
  assert.equal(withApiBase('/api/overview'), '/api/overview');
});

test('注血可复位：null 恢复读 location（node 无 location = 缺省）', () => {
  _setEmbedSearchParamsForTest('?apiBase=/p&embed=1');
  assert.equal(withApiBase('/api/x'), '/p/api/x');
  assert.equal(isEmbedMode(), true);
  _setEmbedSearchParamsForTest(null);
  assert.equal(withApiBase('/api/x'), '/api/x');
  assert.equal(isEmbedMode(), false);
});

// ════ 3.2 缺省行为逐字节回归（无参数启动 = 现状） ════

test('缺省：封装调用产出与改造前逐字节一致的根相对 URL', async () => {
  await getOverview();
  assert.equal(calls[0].url, '/api/overview');
  await getAlerts();
  assert.equal(calls[1].url, '/api/alerts');
  await clearAllAlerts(); // POST 同样无前缀
  assert.equal(calls[2].url, '/api/alerts/clear');
});

test('缺省：STREAM_URL 恒为 /api/stream', () => {
  assert.equal(STREAM_URL_DEFAULT, '/api/stream');
});

test('缺省：architectureDiagramUrl 产出根相对 iframe src（含 present=1）', () => {
  assert.equal(
    architectureDiagramUrl('demo'),
    '/api/architecture/diagram?project=demo&present=1',
  );
});

// ════ 3.3 前缀化回归（先注血后动态 import，query specifier 取全新实例） ════

test('apiBase=/fenix-dashboard：STREAM_URL 与封装调用全部带前缀', async () => {
  // 先注血（生产读取路径：globalThis.location.search），再动态 import——
  // import 期求值的 STREAM_URL 才能拿到前缀。
  globalThis.location = { search: '?embed=1&apiBase=/fenix-dashboard' };
  _setEmbedSearchParamsForTest(null); // 清空惰性缓存，强制以新 location 重新解析
  try {
    const fresh = await import('../src/services/dashboard.ts?embed-prefixed');
    assert.equal(fresh.STREAM_URL, '/fenix-dashboard/api/stream');

    responses = [{ status: 200, body: '{"ok":true}' }];
    calls = [];
    await fresh.getOverview();
    assert.equal(calls[0].url, '/fenix-dashboard/api/overview');
    calls = [];
    await fresh.getAlerts();
    assert.equal(calls[0].url, '/fenix-dashboard/api/alerts');

    // 服务层构造的下发 URL（iframe src，不经 fetch）同单点前缀化
    assert.equal(
      fresh.architectureDiagramUrl('demo'),
      '/fenix-dashboard/api/architecture/diagram?project=demo&present=1',
    );

    // 前缀下 isEmbedMode 同一解析源：embed=1 与 apiBase 组合互不干扰
    const mount = await import('../src/utils/embedMount.ts');
    assert.equal(mount.isEmbedMode(), true);
  } finally {
    _setEmbedSearchParamsForTest(null);
    delete globalThis.location;
  }
});

test('ClaudeOutputPane 引用单源：无硬编码流端点，EventSource 走 STREAM_URL', async () => {
  const paneSource = await readFile(
    new URL('../src/components/claude-msg/ClaudeOutputPane.tsx', import.meta.url),
    'utf8',
  );
  assert.ok(!paneSource.includes('/api/stream'), '不得再出现硬编码流端点字面量');
  assert.ok(paneSource.includes('new EventSource(STREAM_URL)'), 'EventSource 须经 services 单源');
});
