// fmtEvidence 单元测试（零依赖，node 原生 type-stripping 加载 .ts）。
// 运行：cd core/dashboard/static && node --test tests/evidence.test.mjs
//
// 回归 fix-alert-evidence-render-crash：告警 evidence 后端契约是字符串，
// 但历史记录里出现过 dict（stash_pop_conflict 直发结构化证据），React 直接
// 渲染对象 → 首页整页白屏 "Objects are not valid as a React child"。
// 渲染层兜底保证任何形状都产出可渲染字符串。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtEvidence } from '../src/utils/evidence.ts';

test('字符串原样返回', () => {
  assert.equal(fmtEvidence('纯文本证据'), '纯文本证据');
});

test('undefined/null/空串返回空串（调用方按假值隐藏）', () => {
  assert.equal(fmtEvidence(undefined), '');
  assert.equal(fmtEvidence(null), '');
  assert.equal(fmtEvidence(''), '');
});

test('dict 序列化为可读 JSON 串（不再抛 Objects are not valid as a React child）', () => {
  const out = fmtEvidence({ conflict_files: ['core/a.py'], stash_kept: false });
  assert.equal(typeof out, 'string');
  assert.ok(out.includes('core/a.py'));
  assert.ok(out.includes('stash_kept'));
});

test('数组序列化为 JSON 串', () => {
  assert.equal(fmtEvidence(['a', 'b']), '["a","b"]');
});

test('数字与布尔转字符串', () => {
  assert.equal(fmtEvidence(0), '0');
  assert.equal(fmtEvidence(42), '42');
  assert.equal(fmtEvidence(true), 'true');
});

test('循环引用对象不抛异常，降级为 String()', () => {
  const cyc = {};
  cyc.self = cyc;
  const out = fmtEvidence(cyc);
  assert.equal(typeof out, 'string');
  assert.ok(out.length > 0);
});
