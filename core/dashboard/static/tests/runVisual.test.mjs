// runVisual 纯函数等价性测试（add-spec-topology-bigscreen 3.2）。
// 形态沿用 embedMount.test.mjs 先例：node 原生 type-stripping 直载 .ts 源码。
// 钉住 SpecTimeline.tsx 等价迁移（任务 3.1）前后的渲染口径：
// - 状态语义色 runDotColor 全分支（error/gate-blocked 红、interrupted/cancelled
//   橙、stale 灰、running/empty 蓝、done 等其余绿兜底）；
// - 前缀 → 角色标签全表（RUN_ID_PREFIX_LABEL 每条 + 顺序敏感性：impl-ocr- 先于
//   impl- 命中、多段前缀不被首段吞并）；
// - agent_type 优先级（非泛型命中 AGENT_LABEL 优先于 run_id 前缀；泛型 'agent'
//   视同缺失回落前缀判别；全未中落「未知 Agent」）。
// 运行：cd core/dashboard/static && node --test tests/runVisual.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  AGENT_LABEL,
  RUN_ID_PREFIX_LABEL,
  STATUS_HEX,
  agentLabel,
  formatUsd,
  reasonTone,
  runDotColor,
} from '../src/utils/runVisual.ts';

// ── 状态 → 语义色全分支（与迁移前 SpecTimeline if/else 链逐分支等价） ──

test('runDotColor 全分支：失败红', () => {
  assert.equal(runDotColor('error'), 'red');
  assert.equal(runDotColor('gate-blocked'), 'red');
});

test('runDotColor 全分支：中止橙', () => {
  assert.equal(runDotColor('interrupted'), 'orange');
  assert.equal(runDotColor('cancelled'), 'orange');
});

test('runDotColor 全分支：弃置/断尾灰', () => {
  assert.equal(runDotColor('stale'), 'gray');
});

test('runDotColor 全分支：在飞蓝（running/empty）', () => {
  assert.equal(runDotColor('running'), 'blue');
  assert.equal(runDotColor('empty'), 'blue');
});

test('runDotColor 全分支：成功终态与未知状态绿兜底', () => {
  assert.equal(runDotColor('done'), 'green');
  assert.equal(runDotColor(''), 'green');
  assert.equal(runDotColor('never-seen-status'), 'green');
  // null/undefined 入参按缺失处理（SpecTimeline 侧 `item.status || ''` 同口径）
  assert.equal(runDotColor(undefined), 'green');
});

test('STATUS_HEX 与语义色值域一一对应（大屏 SVG 投影）', () => {
  for (const tone of ['red', 'orange', 'gray', 'blue', 'green']) {
    assert.match(STATUS_HEX[tone], /^#[0-9a-f]{6}$/i);
  }
  assert.equal(STATUS_HEX.red, '#ff4d4f');
  assert.equal(STATUS_HEX.green, '#52c41a');
});

// ── 前缀 → 角色标签全表（RUN_ID_PREFIX_LABEL 逐条，完整前缀匹配语义） ──

test('run_id 前缀全表：每条前缀命中其标签', () => {
  for (const [prefix, label] of RUN_ID_PREFIX_LABEL) {
    assert.equal(agentLabel({ run_id: `${prefix}demo-1772000000` }), label);
  }
});

test('前缀顺序敏感性：多段前缀不被首段吞并', () => {
  // impl-ocr- 必须先于 impl- 命中（长的排前面，首个命中即止）
  assert.equal(agentLabel({ run_id: 'impl-ocr-lane-1772000000' }), '代码审查 Agent');
  assert.notEqual(agentLabel({ run_id: 'impl-ocr-lane-1772000000' }), '开发 Agent');
  // planner-plan- / planner-judge- 不被 planner- 首段吞并
  assert.equal(agentLabel({ run_id: 'planner-plan-demo-1772000000' }), '生成场景 Agent');
  assert.equal(agentLabel({ run_id: 'planner-judge-demo-1772000000' }), '判定结果 Agent');
  // spec-review- 不被不存在的 'spec-' 或泛型兜底吞并
  assert.equal(agentLabel({ run_id: 'spec-review-add-foo-1772000000' }), '需求评审 Agent');
  assert.equal(agentLabel({ run_id: 'dispute-judge-add-foo-1772000000' }), '争议裁决 Agent');
});

// ── agent_type 优先级（AGENT_LABEL 表直命中 > run_id 前缀 > 未知兜底） ──

test('agent_type 非泛型优先命中 AGENT_LABEL', () => {
  assert.equal(AGENT_LABEL.implementer, '开发 Agent');
  // agent_type 命中时 run_id 前缀不参与（即便前缀指向不同角色）
  assert.equal(
    agentLabel({ agent_type: 'verifier', run_id: 'impl-demo-1772000000' }),
    '验证 Agent',
  );
  for (const [t, label] of Object.entries(AGENT_LABEL)) {
    assert.equal(agentLabel({ agent_type: t, run_id: '' }), label);
  }
});

test('泛型 agent 视同缺失，回落 run_id 前缀判别', () => {
  assert.equal(agentLabel({ agent_type: 'agent', run_id: 'repair-demo-1772000000' }), '修复 Agent');
  assert.equal(agentLabel({ agent_type: '', run_id: 'admin-demo-1772000000' }), '运维 Agent');
  assert.equal(agentLabel({ run_id: 'impl-demo-1772000000' }), '开发 Agent');
});

test('全未中落「未知 Agent」兜底', () => {
  assert.equal(agentLabel({}), '未知 Agent');
  assert.equal(agentLabel({ agent_type: 'agent', run_id: 'mystery-1772000000' }), '未知 Agent');
  assert.equal(agentLabel({ agent_type: 'ghost', run_id: 'ghost-x' }), '未知 Agent');
});

// ── reasonTone 全分支（终态原因语气 + 前缀） ──

test('reasonTone 全分支', () => {
  assert.deepEqual(reasonTone('gate-blocked'), { tone: 'danger', prefix: '门禁拒绝：' });
  assert.deepEqual(reasonTone('error'), { tone: 'danger', prefix: '失败原因：' });
  assert.deepEqual(reasonTone('superseded'), { tone: 'secondary', prefix: '原地重试：' });
  assert.deepEqual(reasonTone('interrupted'), { tone: 'warning', prefix: '中止原因：' });
  assert.deepEqual(reasonTone('cancelled'), { tone: 'warning', prefix: '中止原因：' });
  // 未知状态落 warning/中止原因（与迁移前行为一致）
  assert.deepEqual(reasonTone('done'), { tone: 'warning', prefix: '中止原因：' });
});

// ── formatUsd 金额格式化（detail 页共享单源） ──

test('formatUsd 小额三位小数、其余两位', () => {
  assert.equal(formatUsd(0.004), '$0.004');
  assert.equal(formatUsd(0.009), '$0.009');
  assert.equal(formatUsd(0.01), '$0.01');
  assert.equal(formatUsd(1.5), '$1.50');
  assert.equal(formatUsd(0), '$0.00');
});
