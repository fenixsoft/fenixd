// blocked SPEC 处置相位三态渲染测试（add-blocked-repairing-display 任务 2.4）。
// 零依赖 node:test（同 specTitleSubtitle.test.mjs 习语：纯逻辑直测 + 源码扫描
// 钉 JSX 接线；渲染行为由 npm run build 与浏览器冒烟覆盖）。
//
// 覆盖：
// - blockedPhaseMeta 三态标签与 tone（repairing→修复中 info 蓝、queued→排队中
//   warning 橙）；
// - blocked_phase 缺席/null/非法值回退「阻塞」critical 红（现状行为不变）；
// - 非 blocked 状态渲染不受影响（相位在场也按 statusMeta 原样）；
// - STATUS_META 键域不变（不新增 repairing/queued 键，真实状态值域不变）；
// - list.tsx 两处消费点（桌面状态列 + 移动卡片）与 detail.tsx 两处（头部 +
//   切换下拉）接线，无平行实现。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { blockedPhaseMeta, statusMeta, STATUS_META } from '../src/services/dashboard.ts';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readSrc = (rel) => readFileSync(join(STATIC_ROOT, rel), 'utf-8');

// ── 三态标签与 tone ──────────────────────────────────────────────────

test('repairing → 「修复中」进行中蓝（info，非阻塞红）', () => {
  const m = blockedPhaseMeta({ status: 'blocked', blocked_phase: 'repairing' });
  assert.equal(m.label, '修复中');
  assert.equal(m.tone, 'info');
  assert.notEqual(m.tone, 'critical');
});

test('queued → 「排队中」等待橙（warning，非阻塞红）', () => {
  const m = blockedPhaseMeta({ status: 'blocked', blocked_phase: 'queued' });
  assert.equal(m.label, '排队中');
  assert.equal(m.tone, 'warning');
  assert.notEqual(m.tone, 'critical');
});

// ── 缺席/null/非法值回退阻塞（现状行为不变） ─────────────────────────

test('blocked_phase 为 null/undefined（字段缺席）→ 「阻塞」critical 原样', () => {
  for (const phase of [null, undefined]) {
    const m = blockedPhaseMeta({ status: 'blocked', blocked_phase: phase });
    assert.deepEqual(m, statusMeta('blocked'), `phase=${phase}`);
    assert.equal(m.label, '阻塞');
    assert.equal(m.tone, 'critical');
  }
  // 旧后端/缓存竞态：记录上根本没有该字段
  assert.deepEqual(blockedPhaseMeta({ status: 'blocked' }), statusMeta('blocked'));
});

test('blocked_phase 非法值（值域外字符串）→ 回退「阻塞」', () => {
  const m = blockedPhaseMeta({ status: 'blocked', blocked_phase: 'bogus' });
  assert.equal(m.label, '阻塞');
  assert.equal(m.tone, 'critical');
});

// ── 非 blocked 状态渲染不受影响 ──────────────────────────────────────

test('非 blocked 状态忽略相位，按 statusMeta 原样渲染', () => {
  assert.deepEqual(
    blockedPhaseMeta({ status: 'implementing', blocked_phase: 'repairing' }),
    statusMeta('implementing'),
  );
  assert.equal(
    blockedPhaseMeta({ status: 'done', blocked_phase: 'queued' }).label,
    '完成',
  );
  assert.equal(
    blockedPhaseMeta({ status: 'bug-found', blocked_phase: 'queued' }).label,
    '有Bug',
  );
});

test('record 缺席/空 defensively 兜底（详情 payload 未加载窗口）', () => {
  assert.deepEqual(blockedPhaseMeta(undefined), statusMeta(''));
  assert.deepEqual(blockedPhaseMeta(null), statusMeta(''));
  assert.equal(blockedPhaseMeta(null).label, '未知');
});

// ── STATUS_META 键域与 statusMeta 本体不变 ───────────────────────────

test('STATUS_META 不新增相位键（真实状态值域不变，blocked 仍 critical）', () => {
  assert.equal('repairing' in STATUS_META, false);
  assert.equal('queued' in STATUS_META, false);
  assert.deepEqual(STATUS_META.blocked, { label: '阻塞', tone: 'critical' });
  // statusMeta 本体不被相位污染（blocked 查询仍回阻塞）
  assert.deepEqual(statusMeta('blocked'), { label: '阻塞', tone: 'critical' });
});

// ── 接线：列表/详情四处共用单源，无平行实现 ──────────────────────────

const svcSrc = readSrc('src/services/dashboard.ts');

test('dashboard.ts：BLOCKED_PHASE_META 仅 repairing/queued 两键（回退统一走 statusMeta）', () => {
  const start = svcSrc.indexOf('const BLOCKED_PHASE_META');
  assert.ok(start > 0, '应有 BLOCKED_PHASE_META 相位映射单源');
  const block = svcSrc.slice(start, svcSrc.indexOf('};', start));
  assert.ok(block.includes("repairing: { label: '修复中', tone: 'info' }"), '修复中=info 蓝');
  assert.ok(block.includes("queued: { label: '排队中', tone: 'warning' }"), '排队中=warning 橙');
  assert.ok(!block.includes('critical'), '相位映射不得引入阻塞红（三态可区分契约）');
});

test('dashboard.ts：blockedPhaseMeta 导出且以 statusMeta 为回退单源', () => {
  assert.ok(svcSrc.includes('export function blockedPhaseMeta('), '应导出 blockedPhaseMeta');
  const start = svcSrc.indexOf('export function blockedPhaseMeta(');
  const body = svcSrc.slice(start, svcSrc.indexOf('\n}', start));
  assert.ok(body.includes('return statusMeta('), '回退路径 MUST 走 statusMeta 单源');
  assert.ok(body.includes("=== 'blocked'"), '相位覆盖 MUST 以 status=blocked 前置');
});

const listSrc = readSrc('src/pages/projects/list.tsx');

test('list.tsx：桌面状态列与移动卡片两处消费点均走 blockedPhaseMeta 单源', () => {
  const uses = [...listSrc.matchAll(/const m = blockedPhaseMeta\(record\)/g)].length;
  assert.equal(uses, 2, `两处状态标签（桌面列 + 移动卡片）应恰 2 处消费（实际 ${uses} 处）`);
  // 筛选/计数面（真实状态口径）不受影响：仍走 statusMeta
  assert.ok(
    listSrc.includes("LIST_STATUSES.map((k) => ({ key: k, label: statusMeta(k).label"),
    '状态计数页签应维持 statusMeta（真实状态值域）',
  );
  assert.ok(
    listSrc.includes("options={LIST_STATUSES.map((k) => ({ value: k, label: statusMeta(k).label }))}"),
    '筛选 Select 选项应维持 statusMeta（真实状态值域）',
  );
});

const detailSrc = readSrc('src/pages/projects/detail.tsx');

test('detail.tsx：头部状态标签与切换下拉均走 blockedPhaseMeta，无平行实现', () => {
  assert.ok(detailSrc.includes('const statusInfo = blockedPhaseMeta(detail);'), '头部标签应消费单源辅助');
  assert.ok(detailSrc.includes('const m = blockedPhaseMeta(s);'), '切换下拉应消费单源辅助');
  assert.ok(
    !detailSrc.includes('statusMeta('),
    '详情页不应残留平行实现（头部/下拉外不得再直调 statusMeta）',
  );
});
