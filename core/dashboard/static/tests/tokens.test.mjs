// fmtInputTokens / fmtMillions 单元测试（零依赖，node 原生 type-stripping 加载 .ts）。
// 运行：cd core/dashboard/static && node --test tests/tokens.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtInputTokens, fmtMillions } from '../src/utils/tokens.ts';

test('输入 Token 主数值为缓存未命中量（总量 − 命中），命中率分母仍为含缓存的总量', () => {
  // 20M 输入、18.7M 命中 → 未命中 1.3M，命中率 93.5%
  assert.equal(
    fmtInputTokens({ tokens_in: 20_000_000, cache_read_input_tokens: 18_700_000 }),
    '1.3M（缓存命中 18.7M，命中率 93.5%）',
  );
});

test('分项为 null（历史 spec）不显示括号，主数值仍为输入总量', () => {
  assert.equal(fmtInputTokens({ tokens_in: 13_500_000, cache_read_input_tokens: null }), '13.5M');
});

test('tokens_in 为 0 时不显示括号', () => {
  assert.equal(fmtInputTokens({ tokens_in: 0, cache_read_input_tokens: 0 }), '0.0M');
});

test('缓存全命中时主数值为 0.0M，命中率 100%', () => {
  assert.equal(
    fmtInputTokens({ tokens_in: 5_000_000, cache_read_input_tokens: 5_000_000 }),
    '0.0M（缓存命中 5.0M，命中率 100.0%）',
  );
});

test('超 1000M 用 G 表示，未命中主数值不受影响', () => {
  assert.equal(
    fmtInputTokens({ tokens_in: 1_500_000_000, cache_read_input_tokens: 1_300_000_000 }),
    '200.0M（缓存命中 1.30G，命中率 86.7%）',
  );
});

test('fmtMillions：M 与 G 分界', () => {
  assert.equal(fmtMillions(0), '0.0M');
  assert.equal(fmtMillions(999_999_999), '1000.0M'); // 999.99…M 四舍五入显示，未过 G 门槛
  assert.equal(fmtMillions(1_000_000_000), '1.00G');
});
