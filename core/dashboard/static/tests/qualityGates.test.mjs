// 质量门禁渲染语义映射单元测试（add-quality-gates-visibility 任务 4.3 + 5.2）。
// 零依赖，node 原生 type-stripping 加载 .ts。
// 运行：cd core/dashboard/static && node --test tests/qualityGates.test.mjs
//
// 覆盖：
// - 4.3 状态→渲染语义映射：done 计数含 skipped、failed 归因展示、空态与不渲染
//   条件、未知 gate-id 容错不崩、ocr 车道三态映射呈现；
// - 5.2 gates 阶段渲染映射（phasePct/strokeColorFor/trailColorFor）+ impl/verify
//   渲染零回归断言。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  GATES_STROKE,
  gateChecked,
  gateCounted,
  gateDetailText,
  gateStrikeThrough,
  gateSuffix,
  gateTextColor,
  normalizeGateItems,
  ocrJoinNote,
  shouldRenderGatesCard,
} from '../src/pages/projects/qualityGates.ts';
import {
  GATES_TRAIL,
  phasePct,
  renderPercent,
  strokeColorFor,
  trailColorFor,
} from '../src/pages/projects/progressPhase.ts';

const gi = (status, extra = {}) => ({ id: 'full-suite', desc: '全量回归测试', status, ...extra });

// ── 4.3：done 计数含 skipped（gateCounted/gateChecked 同口径） ──────────

test('passed 与 skipped 计入完成度，其余三态不计入', () => {
  assert.equal(gateCounted(gi('passed')), true);
  assert.equal(gateCounted(gi('skipped')), true);
  assert.equal(gateCounted(gi('failed')), false);
  assert.equal(gateCounted(gi('running')), false);
  assert.equal(gateCounted(gi('pending')), false);
  assert.equal(gateCounted(gi('unknown')), false);
});

test('勾选视觉与计数同口径：skipped 勾选（已了结）但不加删除线', () => {
  assert.equal(gateChecked(gi('skipped')), true);
  assert.equal(gateStrikeThrough(gi('skipped')), false);
  assert.equal(gateChecked(gi('passed')), true);
  assert.equal(gateStrikeThrough(gi('passed')), true);
  assert.equal(gateChecked(gi('pending')), false);
});

// ── 4.3：failed 归因展示 ─────────────────────────────────────────────

test('failed 红色文字 + detail 归因辅助文案', () => {
  const item = gi('failed', { detail: '交付物声明对账缺件' });
  assert.equal(gateTextColor(item), '#cf1322');
  assert.equal(gateDetailText(item), '交付物声明对账缺件');
});

test('failed 无 detail 时辅助文案为空串（不渲染占位）', () => {
  assert.equal(gateDetailText(gi('failed')), '');
});

test('pending/unknown 灰色；passed 无着色；passed detail 透传为辅助文案', () => {
  assert.equal(gateTextColor(gi('pending')), '#999');
  assert.equal(gateTextColor(gi('unknown')), '#999');
  assert.equal(gateTextColor(gi('passed')), undefined);
  assert.equal(
    gateDetailText(gi('passed', { detail: '审查完成：发现 2 条、处置 2 条' })),
    '审查完成：发现 2 条、处置 2 条',
  );
  assert.equal(gateDetailText(gi('passed', { detail: '通过 214，失败 0' })), '通过 214，失败 0');
});

test('running 不渲染 detail（状态由「进行中」后缀承载，detail 为同义文案）', () => {
  assert.equal(gateDetailText(gi('running', { detail: 'ocr 并行审查进行中' })), '');
});

// ── 4.3：状态后缀标识 ────────────────────────────────────────────────

test('running「进行中」/ skipped「不适用」/ unknown「无记录」后缀', () => {
  assert.equal(gateSuffix(gi('running')), '（进行中）');
  assert.equal(gateSuffix(gi('skipped')), '（不适用）');
  assert.equal(gateSuffix(gi('unknown')), '（无记录）');
  assert.equal(gateSuffix(gi('passed')), '');
  assert.equal(gateSuffix(gi('failed')), '');
  assert.equal(gateSuffix(gi('pending')), '');
});

// ── 4.3：空态与不渲染条件 ────────────────────────────────────────────

test('drafted/ready 且 exists=false 不渲染 Card', () => {
  assert.equal(shouldRenderGatesCard('drafted', false), false);
  assert.equal(shouldRenderGatesCard('ready', false), false);
});

test('drafted 但文件已可见（fast-track 提前落盘）仍渲染', () => {
  assert.equal(shouldRenderGatesCard('drafted', true), true);
});

test('其余状态 exists=false 恒渲染（空态兜底）', () => {
  assert.equal(shouldRenderGatesCard('implementing', false), true);
  assert.equal(shouldRenderGatesCard('testing', false), true);
  assert.equal(shouldRenderGatesCard('verified', false), true);
  assert.equal(shouldRenderGatesCard(null, false), true);
});

// ── 4.3：未知 gate-id / 异常形状容错不崩 ─────────────────────────────

test('items 非数组（null/undefined/对象）归一为空数组', () => {
  assert.deepEqual(normalizeGateItems(null), []);
  assert.deepEqual(normalizeGateItems(undefined), []);
  assert.deepEqual(normalizeGateItems({}), []);
});

test('未知 gate-id 原样保留，缺 desc 回退 id，缺 status 回退 unknown', () => {
  const out = normalizeGateItems([{ id: 'my-gate' }]);
  assert.equal(out.length, 1);
  assert.equal(out[0].id, 'my-gate');
  assert.equal(out[0].desc, 'my-gate');
  assert.equal(out[0].status, 'unknown');
  assert.equal(gateSuffix(out[0]), '（无记录）');
});

test('项非对象被剔除、null 项不崩', () => {
  const out = normalizeGateItems([null, 'x', 42, gi('passed')]);
  assert.equal(out.length, 1);
  assert.equal(out[0].status, 'passed');
});

test('detail 非字符串（后端异常形状）归一为字符串', () => {
  const out = normalizeGateItems([{ id: 'a', desc: 'b', status: 'failed', detail: { k: 1 } }]);
  assert.equal(out[0].detail, '[object Object]');
});

// ── 4.3：ocr 车道三态映射呈现 ────────────────────────────────────────
// 车道产物 running/completed/unavailable 由后端合成为 code-review 门
// running/passed/skipped；前端按六态语义呈现：

test('ocr 在飞：合成 running → 「进行中」标识，不计入完成度', () => {
  const item = { id: 'code-review', desc: 'ocr 代码审查与处置', status: 'running' };
  assert.equal(gateSuffix(item), '（进行中）');
  assert.equal(gateCounted(item), false);
  assert.equal(gateChecked(item), false);
});

test('ocr completed：合成 passed → 勾选+删除线，发现/处置计数透传为辅助文案', () => {
  const item = {
    id: 'code-review',
    desc: 'ocr 代码审查与处置',
    status: 'passed',
    detail: '审查完成：发现 2 条、处置 2 条',
  };
  assert.equal(gateChecked(item), true);
  assert.equal(gateStrikeThrough(item), true);
  assert.equal(gateDetailText(item), '审查完成：发现 2 条、处置 2 条');
});

test('ocr unavailable：合成 skipped → 勾选+「不适用」，计入完成度（已了结而非未做）', () => {
  const item = {
    id: 'code-review',
    desc: 'ocr 代码审查与处置',
    status: 'skipped',
    detail: 'ocr 审查环境不可用',
  };
  assert.equal(gateChecked(item), true);
  assert.equal(gateSuffix(item), '（不适用）');
  assert.equal(gateCounted(item), true);
  assert.equal(gateStrikeThrough(item), false);
});

// ── 5.2：gates 阶段渲染映射 ──────────────────────────────────────────

test('gates 阶段 phasePct 用门禁完成度（gates_done/gates_total）', () => {
  assert.equal(
    phasePct({ progress_phase: 'gates', task_done: 0, task_total: 0, verify_done: 0, verify_total: 0, gates_done: 4, gates_total: 6 }),
    67,
  );
});

test('gates 阶段字段缺失回退 0/0 → 0%（不崩）', () => {
  assert.equal(
    phasePct({ progress_phase: 'gates', task_done: 3, task_total: 5, verify_done: 0, verify_total: 0 }),
    0,
  );
});

test('gates 阶段进度条门禁橙描边 + 淡橙底轨', () => {
  assert.equal(GATES_STROKE, '#fa8c16');
  assert.equal(strokeColorFor(false, false, true), '#fa8c16');
  assert.equal(trailColorFor(false, false, true), GATES_TRAIL);
  assert.equal(GATES_TRAIL, '#fff7e6');
});

test('gates 阶段门禁完成度计数文案含 skipped（4 + 2 skipped = 6/6）', () => {
  // 后端 done 含 skipped；前端 gates_done/gates_total 直读不二次加工
  const record = { progress_phase: 'gates', task_done: 9, task_total: 9, verify_done: 0, verify_total: 0, gates_done: 6, gates_total: 6 };
  assert.equal(phasePct(record), 100);
});

// ── ocr 收尾审查 finding#1 修补：renderPercent 具名函数（替代嵌套三元） ──

test('renderPercent：gates 分支走门禁完成度', () => {
  assert.equal(
    renderPercent({ progress_phase: 'gates', task_done: 9, task_total: 9, verify_done: 0, verify_total: 0, gates_done: 1, gates_total: 6 }, null),
    17,
  );
});

test('renderPercent：verify 分支 gen 出题进度封顶 100%', () => {
  const rec = { progress_phase: 'verify', task_done: 9, task_total: 9, verify_done: 0, verify_total: 0 };
  assert.equal(renderPercent(rec, { done: 3, total: 10 }), 30);
  assert.equal(renderPercent(rec, { done: 99, total: 10 }), 100);
  assert.equal(renderPercent(rec, null), 0);
});

test('renderPercent：impl 分支任务完成度', () => {
  assert.equal(
    renderPercent({ progress_phase: 'impl', task_done: 1, task_total: 4, verify_done: 5, verify_total: 5 }, null),
    25,
  );
});

// ── 5.2：impl/verify 渲染零回归断言 ──────────────────────────────────

test('impl 阶段 phasePct 用任务完成度（含 progress_phase 缺省回退）', () => {
  assert.equal(
    phasePct({ progress_phase: 'impl', task_done: 1, task_total: 4, verify_done: 0, verify_total: 0 }),
    25,
  );
  assert.equal(
    phasePct({ task_done: 2, task_total: 3, verify_done: 9, verify_total: 9 }),
    67,
  );
});

test('verify 阶段 phasePct 用验证完成度', () => {
  assert.equal(
    phasePct({ progress_phase: 'verify', task_done: 9, task_total: 9, verify_done: 1, verify_total: 2 }),
    50,
  );
});

test('配色零回归：impl 蓝、verify 绿、出题青优先', () => {
  assert.equal(strokeColorFor(false, false), '#1677ff');
  assert.equal(strokeColorFor(false, true), '#52c41a');
  assert.equal(strokeColorFor(true, true), '#13c2c2');
  assert.equal(strokeColorFor(true, false), '#13c2c2');
  assert.equal(trailColorFor(false, false), '#e6f4ff');
  assert.equal(trailColorFor(false, true), 'rgb(225, 236, 215)');
  assert.equal(trailColorFor(true, true), '#e6f4ff');
});

test('pct 边界：total=0 → 0%，四舍五入', () => {
  assert.equal(phasePct({ task_done: 0, task_total: 0, verify_done: 0, verify_total: 0 }), 0);
  assert.equal(phasePct({ task_done: 2, task_total: 3, verify_done: 0, verify_total: 0 }), 67);
});

// ── add-timeline-ocr-lane-visibility 任务 2.4：testing 停等注记纯函数 ──────

test('ocrJoinNote：running → 注记文案', () => {
  assert.equal(ocrJoinNote('running'), 'ocr 审查车道进行中，完成自动推进');
});

test('ocrJoinNote：pending/skipped/completed/unknown → null（前端零渲染）', () => {
  assert.equal(ocrJoinNote('pending'), null);
  assert.equal(ocrJoinNote('skipped'), null);
  assert.equal(ocrJoinNote('completed'), null);
  assert.equal(ocrJoinNote('unknown'), null);
});

test('ocrJoinNote：空串/缺失状态 → null（历史节点无注记）', () => {
  assert.equal(ocrJoinNote(''), null);
  assert.equal(ocrJoinNote(undefined), null);
});
