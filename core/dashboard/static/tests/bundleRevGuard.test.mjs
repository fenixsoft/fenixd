// X-Bundle-Rev 陈旧 bundle 自愈守卫单元测试。
// 服务端在所有 JSON 响应附 X-Bundle-Rev（dist/index.html 的 mtime_ns+size）；
// request() 首响应记录基线、后续响应比对，不一致即闩锁触发一次整页 reload——
// rebuild 后旧标签页不再以陈旧 JS 请求新数据（1s 超时塌缩事故族的自愈面）。
// 运行：cd core/dashboard/static && node --test tests/bundleRevGuard.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  getSpecs,
  _setBundleRev,
  _resetBundleRevGuard,
} from '../src/services/dashboard.ts';

function makeFetch(seq) {
  // 按脚本队列回放 {status, etag?, body?, rev?}
  return function mockFetch(url, init) {
    const spec = seq.length > 1 ? seq.shift() : seq[0];
    if (!spec) throw new Error('mock fetch: 响应队列已空');
    return Promise.resolve({
      ok: spec.status >= 200 && spec.status < 300,
      status: spec.status,
      headers: {
        get: (name) => {
          const n = name.toLowerCase();
          if (n === 'x-bundle-rev') return spec.rev ?? null;
          if (n === 'etag') return spec.etag ?? null;
          return null;
        },
      },
      text: async () => spec.body,
    });
  };
}

beforeEach(() => {
  _resetBundleRevGuard();
});

test('首响应带 rev：记录为基线，不触发 reload', async () => {
  globalThis.fetch = makeFetch([{ status: 200, body: '{"specs":[]}', rev: 'rev-A' }]);
  await getSpecs('fenixd');
  assert.equal(_setBundleRev.__state.baseline, 'rev-A');
  assert.equal(_setBundleRev.__state.armed, false);
});

test('后续响应 rev 变化：闩锁触发 reload（一次）', async () => {
  const reloads = [];
  _setBundleRev({ reload: (u) => reloads.push(u) });
  globalThis.fetch = makeFetch([
    { status: 200, body: '{"specs":[]}', rev: 'rev-A' },
    { status: 200, body: '{"specs":[]}', rev: 'rev-B' },
  ]);
  await getSpecs('fenixd');
  await getSpecs('fenixd');
  assert.equal(reloads.length, 1, 'rev 漂移应恰好触发一次 reload');
  assert.equal(_setBundleRev.__state.armed, true);
  // 闩锁后再次漂移不重复触发
  globalThis.fetch = makeFetch([{ status: 200, body: '{"specs":[]}', rev: 'rev-C' }]);
  await getSpecs('fenixd');
  assert.equal(reloads.length, 1, '闩锁后不得重复 reload');
});

test('响应无 rev 头：不比对不触发（旧行为零变化）', async () => {
  const reloads = [];
  _setBundleRev({ reload: (u) => reloads.push(u) });
  globalThis.fetch = makeFetch([
    { status: 200, body: '{"specs":[]}' },
    { status: 200, body: '{"specs":[]}' },
  ]);
  await getSpecs('fenixd');
  await getSpecs('fenixd');
  assert.equal(_setBundleRev.__state.baseline, null);
  assert.equal(reloads.length, 0);
});

test('304 短路路径同样参与 rev 比对', async () => {
  const reloads = [];
  _setBundleRev({ reload: (u) => reloads.push(u) });
  globalThis.fetch = makeFetch([
    { status: 200, body: '{"specs":[]}', rev: 'rev-A', etag: '"v1"' },
    { status: 304, rev: 'rev-B', etag: '"v1"' }, // 数据未变（304 命中缓存）但 bundle 已 rebuild
  ]);
  await getSpecs('fenixd'); // 基线 rev-A
  await getSpecs('fenixd'); // 304 + rev-B → 触发
  assert.equal(reloads.length, 1, '304 命中路径的 rev 漂移也应触发 reload');
});
