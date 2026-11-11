// embedBridge 单测（add-dsh-new-session-button）：embed 态 iframe → dsh 宿主
// postMessage 桥。形态沿用 embedMount.test.mjs 先例：node 原生 type-stripping
// 直载 .ts 源码 + `_setEmbedSearchParamsForTest()` 注血（注血清惰性缓存，
// 先注血后调用）。window 以最小桩注入 globalThis（location.origin / parent /
// postMessage 间谍），测试后摘除——「非 embed 短路」用例不设 window，函数若
// 越过 embed 门禁触碰 window 会 ReferenceError，天然覆盖误调面。
// 运行：cd core/dashboard/static && node --test tests/embedBridge.test.mjs
import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  HOST_NEW_SESSION_KIND,
  requestHostNewSession,
} from '../src/utils/embedBridge.ts';
import { _setEmbedSearchParamsForTest } from '../src/utils/embedMount.ts';

beforeEach(() => {
  delete globalThis.window;
  _setEmbedSearchParamsForTest(null);
});

afterEach(() => {
  delete globalThis.window;
  _setEmbedSearchParamsForTest(null);
});

/**
 * 最小 window 桩。hasHost=false → parent 指回自身（无宿主形态）；hasHost=true
 * → parent 为带 postMessage 间谍的宿主对象，记录 (message, targetOrigin)。
 */
function stubWindow(hasHost) {
  const sent = [];
  const win = {
    location: { origin: 'http://127.0.0.1:3080' },
  };
  if (hasHost) {
    win.parent = {
      postMessage: (message, targetOrigin) => {
        sent.push({ message, targetOrigin });
      },
    };
  } else {
    win.parent = win;
  }
  globalThis.window = win;
  return sent;
}

// ════ kind 常量（双仓镜像钉值：桥插件 src/client/index.ts HOST_NEW_SESSION_KIND 同字面量） ════

test('HOST_NEW_SESSION_KIND 钉值 fenix-dashboard:new-session', () => {
  assert.equal(HOST_NEW_SESSION_KIND, 'fenix-dashboard:new-session');
});

// ════ 门禁：非 embed / 无宿主 ════

test('非 embed（缺省无 location）：返回 false 且不触碰 window（未设 window 桩）', () => {
  // globalThis.window 未注入：若函数越过 embed 门禁引用 window 会抛
  // ReferenceError，本断言同时覆盖「不误发消息」与「不依赖 window」。
  assert.equal(requestHostNewSession('fenixd'), false);
});

test('embed=1 但无宿主（parent === window）：返回 false 且零 side-effect', () => {
  stubWindow(false);
  _setEmbedSearchParamsForTest('?embed=1&apiBase=/fenix-dashboard/');
  assert.equal(requestHostNewSession('fenixd'), false);
});

// ════ embed + 宿主：postMessage 载荷形状 ════

test('embed=1 + 宿主：发出 {kind, project}（无 prompt 键），targetOrigin 取本页 origin', () => {
  const sent = stubWindow(true);
  _setEmbedSearchParamsForTest('?embed=1&apiBase=/fenix-dashboard/');
  assert.equal(requestHostNewSession('fenixd'), true);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].message, { kind: HOST_NEW_SESSION_KIND, project: 'fenixd' });
  // 最小载荷：无 prompt 时不得出现 prompt:undefined 键（宿主形状校验口径）。
  assert.deepEqual(Object.keys(sent[0].message), ['kind', 'project']);
  assert.equal(sent[0].targetOrigin, 'http://127.0.0.1:3080');
});

test('携带 prompt：载荷 {kind, project, prompt}，原样透传前缀文本', () => {
  const sent = stubWindow(true);
  _setEmbedSearchParamsForTest('?embed=1&apiBase=/fenix-dashboard/');
  assert.equal(requestHostNewSession('fenixd', '对于 add-foo SPEC：'), true);
  assert.deepEqual(sent[0].message, {
    kind: HOST_NEW_SESSION_KIND,
    project: 'fenixd',
    prompt: '对于 add-foo SPEC：',
  });
  assert.deepEqual(Object.keys(sent[0].message), ['kind', 'project', 'prompt']);
});
