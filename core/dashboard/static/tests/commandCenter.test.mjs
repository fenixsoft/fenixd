// commandCenter.test.mjs — 指挥中心纯助手单元测试（add-command-center 4.5）。
// 覆盖 specs「验收与红线」要求的纯函数：sparkline 14 日分桶、null 指标
// 格式化（null→「—」、0 保留）、车道状态→徽标映射、choices 选项 destructive
// 判定。零依赖，node 原生 type-stripping 加载 .ts。
// 运行：cd core/dashboard/static && node --test tests/commandCenter.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  fmtMetric,
  fmtRate,
  fmtUsd,
  fmtTokens,
  fmtDurationSeconds,
  fmtShortTs,
  laneBadge,
  outcomeBadge,
  severityBadge,
  sparklineHeights,
  isDestructiveChoice,
  columnLabel,
  laneLabel,
} from '../src/pages/command-center/shared.ts';

// ── null 指标格式化（null→「—」、0 保留） ────────────────────────────────

test('fmtMetric：null/undefined → 「—」（分母零口径语义，禁显 0）', () => {
  assert.equal(fmtMetric(null), '—');
  assert.equal(fmtMetric(undefined), '—');
});

test('fmtMetric：0 保留为「0」非占位符（真实零与不可得语义不同）', () => {
  assert.equal(fmtMetric(0), '0');
  assert.equal(fmtMetric(7), '7');
});

test('fmtRate：null → 「—」；0 → 0.0%；比率按百分比一位小数', () => {
  assert.equal(fmtRate(null), '—');
  assert.equal(fmtRate(undefined), '—');
  assert.equal(fmtRate(0), '0.0%');
  assert.equal(fmtRate(0.8), '80.0%');
  assert.equal(fmtRate(1), '100.0%');
  assert.equal(fmtRate(1 / 3), '33.3%');
});

test('fmtUsd：null → 「—」；0 → $0.00（真实零成本保留）', () => {
  assert.equal(fmtUsd(null), '—');
  assert.equal(fmtUsd(0), '$0.00');
  assert.equal(fmtUsd(5), '$5.00');
  assert.equal(fmtUsd(1.2), '$1.20');
  assert.equal(fmtUsd(1234.5), '$1,234.50');
});

test('fmtTokens：null → 「—」；0 保留；千分位分隔', () => {
  assert.equal(fmtTokens(null), '—');
  assert.equal(fmtTokens(0), '0');
  assert.equal(fmtTokens(1000000), '1,000,000');
});

test('fmtDurationSeconds：null → 「—」；秒/分/时紧凑格式', () => {
  assert.equal(fmtDurationSeconds(null), '—');
  assert.equal(fmtDurationSeconds(0), '0s');
  assert.equal(fmtDurationSeconds(45), '45s');
  assert.equal(fmtDurationSeconds(90), '1m30s');
  assert.equal(fmtDurationSeconds(3600), '1h');
  assert.equal(fmtDurationSeconds(3720), '1h2m');
});

test('fmtShortTs：null → 「—」；无效串原样回退不抛错', () => {
  assert.equal(fmtShortTs(null), '—');
  assert.equal(fmtShortTs(''), '—');
  assert.equal(fmtShortTs('not-a-ts'), 'not-a-ts');
  const out = fmtShortTs('2026-10-25T12:00:00+00:00');
  assert.match(out, /^\d{2}-\d{2} \d{2}:\d{2}$/);
});

// ── 车道状态 → 徽标映射 ──────────────────────────────────────────────────

test('laneBadge：working → 绿「运行中」；idle → 灰「空闲」', () => {
  assert.deepEqual(laneBadge('working'), { text: '运行中', color: '#52c41a' });
  assert.deepEqual(laneBadge('idle'), { text: '空闲', color: '#5b708c' });
});

test('laneBadge：未知状态回退「空闲」（非 working 即 idle 口径）', () => {
  assert.equal(laneBadge('').text, '空闲');
});

test('outcomeBadge：classify_run 口径中文标签；未知/空值原样透出不丢信息', () => {
  assert.deepEqual(outcomeBadge('done'), { text: '成功', color: '#52c41a' });
  assert.deepEqual(outcomeBadge('error'), { text: '失败', color: '#ff4d4f' });
  assert.equal(outcomeBadge('interrupted').text, '已中断');
  assert.equal(outcomeBadge('superseded').text, '已取代');
  assert.equal(outcomeBadge('gate-blocked').text, '门禁拦截');
  assert.equal(outcomeBadge('weird-status').text, 'weird-status');
  assert.equal(outcomeBadge(null).text, '—');
});

test('severityBadge：critical/major/minor 徽标；未知原样透出', () => {
  assert.deepEqual(severityBadge('critical'), { text: '严重', color: '#ff4d4f' });
  assert.deepEqual(severityBadge('major'), { text: '重要', color: '#fa8c16' });
  assert.deepEqual(severityBadge('minor'), { text: '次要', color: '#40a9ff' });
  assert.equal(severityBadge('other').text, 'other');
  assert.equal(severityBadge(null).text, '未知');
});

// ── sparkline 14 日分桶 ──────────────────────────────────────────────────

test('sparklineHeights：14 日计数按最大值归一（旧→新序保持）', () => {
  const heights = sparklineHeights([0, 2, 1, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 8]);
  assert.equal(heights.length, 14);
  assert.equal(heights[13], 100); // 峰值日满高
  assert.equal(heights[3], 50); // 4/8 半高
  assert.equal(heights[1], 25); // 2/8 四分之一高
  assert.equal(heights[0], 0); // 零计数零高度
});

test('sparklineHeights：全零活动 → 全零高度（不除零）', () => {
  assert.deepEqual(sparklineHeights([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
  ]);
});

test('sparklineHeights：负数/非有限输入按 0 计（脏形态设防）', () => {
  const heights = sparklineHeights([-3, NaN, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 10]);
  assert.equal(heights[0], 0);
  assert.equal(heights[1], 0);
  assert.equal(heights[2], 50);
  assert.equal(heights[13], 100);
});

// ── choices 选项 destructive 判定 ────────────────────────────────────────

test('isDestructiveChoice：注册表 destructive:true 单源判定', () => {
  assert.equal(isDestructiveChoice({ id: 'retry', destructive: true }), true);
  assert.equal(isDestructiveChoice({ id: 'retry', destructive: false }), false);
});

test('isDestructiveChoice：历史快照缺字段按已知不可逆 id 回退', () => {
  // abandon 为已知不可逆选项（快照缺失 destructive 字段的历史告警）
  assert.equal(isDestructiveChoice({ id: 'abandon' }), true);
  assert.equal(isDestructiveChoice({ id: 'skip_review_gate' }), true);
  assert.equal(isDestructiveChoice({ id: 'delete_untracked_stray' }), true);
  // 普通选项缺字段 → 非破坏性
  assert.equal(isDestructiveChoice({ id: 'retry' }), false);
  assert.equal(isDestructiveChoice({ id: 'ack_self_heal', destructive: undefined }), false);
});

test('isDestructiveChoice：空输入安全返回 false', () => {
  assert.equal(isDestructiveChoice(null), false);
  assert.equal(isDestructiveChoice(undefined), false);
});

// ── 标签映射 ─────────────────────────────────────────────────────────────

test('columnLabel：五列中文标签；未知 key 原样透出', () => {
  assert.equal(columnLabel('drafted'), '需求评审');
  assert.equal(columnLabel('ready'), '待实现');
  assert.equal(columnLabel('implementing'), '实现中');
  assert.equal(columnLabel('verifying'), '验证中');
  assert.equal(columnLabel('pushed'), '已推送');
  assert.equal(columnLabel('other'), 'other');
});

test('laneLabel：花名册 lane 中文标签；未登记 lane 原样透出（「其他」分区）', () => {
  assert.equal(laneLabel('planner'), '需求规划');
  assert.equal(laneLabel('implementer'), '实现');
  assert.equal(laneLabel('judge'), '裁决');
  assert.equal(laneLabel('verifier'), 'verifier');
});
