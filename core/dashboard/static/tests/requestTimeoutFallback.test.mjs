// request() per-call 超时 fallback 契约测试（code-fix 00bd36bda 回归锚）。
// 该批次引入 MIN_REQUEST_TIMEOUT_MS 下界钳制时把「未传 timeoutMs」的
// fallback 从 REQUEST_TIMEOUT_MS 误写成 MIN_REQUEST_TIMEOUT_MS，全站
// 默认超时塌缩到 1s（SPEC 列表 0.4~0.7s 常规延迟频撞「请求超时（>1s）」）。
// 本文件钉死：未传参 → 30s 全局窗口；显式传小值 → 钳到 1s 下界。
// mock globalThis.fetch 挂起并监听 abort signal，node 原生 type-stripping
// 直加载 ../src/services/dashboard.ts。
// 运行：cd core/dashboard/static && node --test tests/requestTimeoutFallback.test.mjs
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { getSpecs, getCodeReviewProgress, _clearEtagCache } from '../src/services/dashboard.ts';

// 挂起的 fetch：永不 resolve，仅透传 abort 事件（真实后端挂起形态）
function hangingFetch(url, init) {
  return new Promise((_resolve, reject) => {
    const signal = init?.signal;
    if (signal) {
      if (signal.aborted) return reject(abortError(signal.reason));
      signal.addEventListener('abort', () => reject(abortError(signal.reason)));
    }
  });
}

function abortError(reason) {
  if (reason instanceof Error) return reason;
  const e = new Error('The operation was aborted');
  Object.defineProperty(e, 'name', { value: 'AbortError' });
  return e;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

beforeEach(() => {
  globalThis.fetch = hangingFetch;
  _clearEtagCache();
});

test('未传 per-call 超时：1.2s 后不应 settle（fallback 须为 30s 全局窗口而非 1s 下界）', async () => {
  const p = getSpecs('fenixd');
  let outcome;
  const probe = p.then(
    () => (outcome = 'resolved'),
    () => (outcome = 'rejected'),
  );
  await Promise.race([probe, sleep(1200)]);
  assert.equal(outcome, undefined, '1.2s 时请求不应 settle（bug 下已在 1s 超时 reject「请求超时（>1s）」）');
});

test('显式传小值超时：下界钳制后 1.2s 内应已 abort（1s 下界语义不因 fallback 修复丢失）', async () => {
  let outcome;
  const probe = getCodeReviewProgress('fenixd', 100).then(
    () => (outcome = 'resolved'),
    (e) => (outcome = e?.message ?? 'rejected'),
  );
  await Promise.race([probe, sleep(1200)]);
  assert.match(String(outcome), /^请求超时/, 'timeoutMs:100 应被钳到 1s 下界并在 1.2s 内以超时 reject');
});
