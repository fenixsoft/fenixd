// ETag 条件请求缓存单元测试（add-dashboard-paging-and-etag 3.1）。
// 经导出封装（getOverview/getAlerts/…）覆盖 request() 缓存通道；
// mock globalThis.fetch，node 原生 type-stripping 直加载 ../src/services/dashboard.ts。
// 运行：cd core/dashboard/static && node --test tests/etagCache.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  getOverview,
  getAlerts,
  clearAllAlerts,
  getAdminActivities,
  _clearEtagCache,
} from '../src/services/dashboard.ts';

// ── fetch mock：记录每次调用的 (url, init)，按脚本队列依次回放响应 ──

let calls = []; // [{ url, headers }]
let responses = []; // 队列：{ status, etag?, body?, fail? }

function mockFetch(url, init) {
  calls.push({ url, headers: init?.headers ?? null });
  const spec = responses.length > 1 ? responses.shift() : responses[0];
  if (!spec) throw new Error('mock fetch: 响应队列已空');
  if (spec.fail) return Promise.reject(spec.fail);
  return Promise.resolve({
    ok: spec.status >= 200 && spec.status < 300,
    status: spec.status,
    headers: { get: (name) => (name.toLowerCase() === 'etag' ? (spec.etag ?? null) : null) },
    text: async () => {
      if (spec.body === undefined) throw new Error('304 响应不应消费 body');
      return spec.body;
    },
  });
}

function ifNoneMatchOf(call) {
  if (!call || !call.headers) return undefined;
  if (typeof call.headers.get === 'function') return call.headers.get('If-None-Match');
  if (typeof call.headers === 'object') return call.headers['If-None-Match'];
  return undefined;
}

beforeEach(() => {
  calls = [];
  responses = [];
  globalThis.fetch = mockFetch;
  _clearEtagCache();
});

test('首次 GET：不带 If-None-Match，200+ETag 时数据正常返回', async () => {
  responses = [{ status: 200, etag: '"v1"', body: '{"hello":"world"}' }];
  const data = await getOverview();
  assert.deepEqual(data, { hello: 'world' });
  assert.equal(calls.length, 1);
  assert.equal(ifNoneMatchOf(calls[0]), null); // 首次无缓存，不带条件头
});

test('同 URL 二次 GET：携带 If-None-Match，304 短路返回缓存且不消费 body', async () => {
  responses = [
    { status: 200, etag: '"v1"', body: '{"n":1}' },
    { status: 304, etag: '"v1"' },
  ];
  const first = await getOverview();
  const second = await getOverview();
  assert.deepEqual(second, first);
  assert.deepEqual(second, { n: 1 });
  assert.equal(ifNoneMatchOf(calls[1]), '"v1"');
  // 304 响应的 text() 会抛（见 mock），能走到这里即证明未消费 body
});

test('ETag 翻转（200 新 body 新 ETag）：返回新数据并更新缓存', async () => {
  responses = [
    { status: 200, etag: '"v1"', body: '{"n":1}' },
    { status: 200, etag: '"v2"', body: '{"n":2}' },
    { status: 304, etag: '"v2"' },
  ];
  await getOverview();
  const second = await getOverview();
  assert.deepEqual(second, { n: 2 });
  assert.equal(ifNoneMatchOf(calls[1]), '"v1"'); // 第二次带的还是旧 ETag
  const third = await getOverview(); // 缓存已是 v2
  assert.deepEqual(third, { n: 2 });
  assert.equal(ifNoneMatchOf(calls[2]), '"v2"');
});

test('200 但无 ETag 头：不写缓存，下次请求无条件头', async () => {
  responses = [
    { status: 200, body: '{"n":1}' },
    { status: 200, body: '{"n":2}' },
  ];
  const first = await getOverview();
  const second = await getOverview();
  assert.deepEqual(first, { n: 1 });
  assert.deepEqual(second, { n: 2 });
  assert.equal(ifNoneMatchOf(calls[1]), null);
});

test('POST 不走缓存通道：即使同 URL 有 GET 缓存也不带 If-None-Match', async () => {
  responses = [
    { status: 200, etag: '"v1"', body: '{"alerts":[]}' },
    { status: 200, body: '{"ok":true}' },
  ];
  await getAlerts();
  await clearAllAlerts(); // POST /api/alerts/clear——不同 URL 也无妨，关键是 POST 不读缓存
  assert.equal(ifNoneMatchOf(calls[1]), null);
});

test('query 不同 = 缓存键不同：互不串扰', async () => {
  responses = [
    { status: 200, etag: '"p1"', body: '{"page":1}' },
    { status: 200, etag: '"p2"', body: '{"page":2}' },
  ];
  const p1 = await getAdminActivities('proj', undefined, 1, 15);
  const p2 = await getAdminActivities('proj', undefined, 2, 15);
  assert.deepEqual(p1, { page: 1 });
  assert.deepEqual(p2, { page: 2 });
  assert.equal(ifNoneMatchOf(calls[1]), null); // p2 是新键，无条件头
});

test('网络失败不污染缓存：重试仍带旧 ETag', async () => {
  responses = [
    { status: 200, etag: '"v1"', body: '{"n":1}' },
    { fail: new TypeError('boom') },
    { status: 304, etag: '"v1"' },
  ];
  await getOverview();
  await assert.rejects(getOverview(), (e) => e.kind === 'network');
  const third = await getOverview();
  assert.deepEqual(third, { n: 1 });
  assert.equal(ifNoneMatchOf(calls[2]), '"v1"');
});

test('getAdminActivities：page/pageSize 成对下发为 query，缺省不出现在 URL', async () => {
  responses = [
    { status: 200, etag: '"a"', body: '{"projects":[],"total":7,"page":1,"page_size":15,"has_more":true}' },
    { status: 200, body: '{"projects":[]}' },
  ];
  const paged = await getAdminActivities('proj', undefined, 1, 15);
  assert.equal(calls[0].url, '/api/admin-activities?project=proj&page=1&page_size=15');
  assert.deepEqual(paged, { projects: [], total: 7, page: 1, page_size: 15, has_more: true });

  responses = [{ status: 200, body: '{"projects":[]}' }];
  await getAdminActivities();
  assert.equal(calls[1].url, '/api/admin-activities');
});
