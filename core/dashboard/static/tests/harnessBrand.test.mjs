// harnessBrandLogic 纯逻辑单测（add-harness-brand-projection 4.1）。
// 零依赖，node 原生 type-stripping 直载 .ts 源——需 Node ≥22.18（下限同记于
// package.json engines.node）。运行：cd core/dashboard/static && node --test
// tests/harnessBrand.test.mjs
//
// 覆盖品牌回退链三分支（spec「回退链」Requirement；2026-10-29 用户定稿：
// 缺省分支 claude → 中性「AI Assistant」，run meta 无 harness 不再冒充
// Claude 品牌——context 缺省值（SessionPanel 等 claude 专用车道）不受影响，
// 仍为 Claude）：
// 1. 缺省 = 中性（run meta 无 harness 字段/空值 → kind:'default'，装配层
//    映射中性品牌）；
// 2. dsh 映射（注册表命中，组件装配为 DshLogo 鲸鱼图标）；
// 3. 未知值回退首字母徽标（不抛错白屏）。
//
// 注：React 装配层（HarnessBrand.tsx 的 context/Provider/组件映射、MessageItem
// 渲染）为 .tsx——node 原生 loader 不识别该扩展名，由 `npm run build`（tsc/babel
// 编译 + 类型检查）与视觉冒烟验证；本文件锁定装配层消费的判定逻辑单点。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_BRAND_NAME, resolveHarness } from '../src/components/claude-msg/harnessBrandLogic.ts';

// ── 分支 1：缺省 = 中性（AI Assistant） ─────────────────────────────────

test('缺省：harness 字段缺失（undefined）→ default 中性分支（不冒充 Claude）', () => {
  assert.deepEqual(resolveHarness(undefined), { kind: 'default' });
});

test('缺省：harness 字段为 null → default 中性分支', () => {
  assert.deepEqual(resolveHarness(null), { kind: 'default' });
});

test('缺省：harness 字段为空串/纯空白 → default 中性分支', () => {
  assert.deepEqual(resolveHarness(''), { kind: 'default' });
  assert.deepEqual(resolveHarness('   '), { kind: 'default' });
});

test('context 缺省品牌名常量保持 Claude（SessionPanel 等 claude 专用车道未注入 Provider 即现状）', () => {
  assert.equal(DEFAULT_BRAND_NAME, 'Claude');
});

// ── 分支 2：dsh 注册映射 ────────────────────────────────────────────────

test('dsh 映射：注册表命中 → registered/dsh（组件装配为 DshLogo 鲸鱼图标）', () => {
  assert.deepEqual(resolveHarness('dsh'), { kind: 'registered', name: 'dsh' });
});

test('claude 值同属注册表命中（显示 Claude 品牌与 ClaudeLogo，与现状一致）', () => {
  assert.deepEqual(resolveHarness('claude'), { kind: 'registered', name: 'claude' });
});

test('注册表命中判定大小写归一（DSH → registered/dsh）', () => {
  assert.deepEqual(resolveHarness('DSH'), { kind: 'registered', name: 'dsh' });
  assert.deepEqual(resolveHarness(' Dsh '), { kind: 'registered', name: 'dsh' });
});

// ── 分支 3：未知值回退首字母徽标 ────────────────────────────────────────

test('未知值 pi → fallback 徽标：标签 pi、首字母 P（spec「未知 harness 回退徽标」Scenario）', () => {
  assert.deepEqual(resolveHarness('pi'), { kind: 'fallback', name: 'pi', letter: 'P' });
});

test('未知值首字母大写化且保留原标签值', () => {
  assert.deepEqual(resolveHarness('codex'), { kind: 'fallback', name: 'codex', letter: 'C' });
  assert.deepEqual(resolveHarness('Pi'), { kind: 'fallback', name: 'Pi', letter: 'P' });
});

test('未知值不抛错（回退链 MUST NOT 抛错白屏）', () => {
  assert.doesNotThrow(() => resolveHarness(''));
  assert.doesNotThrow(() => resolveHarness('未知 harness'));
  assert.doesNotThrow(() => resolveHarness(null));
});
