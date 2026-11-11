// 裁决自动执行徽标/倒计时测试（add-adjudication-auto-exec 5.3）。
// 零依赖 node:test（同 blockedPhase.test.mjs 习语：纯逻辑直测 + 源码扫描
// 钉 JSX 接线；渲染行为由 npm run build 与浏览器冒烟覆盖）。
//
// 覆盖：
// - autoExecBadge：executed=true → 「自动执行」独立徽标（cyan，与人工闭环
//   「已收口」绿标并存不混同）；absent/null/executed=false → null 不渲染；
// - autoExecCountdown：可逆档 + 明确推荐 + due_at 未满 → 逐段倒计时文案；
//   已满 → 「等待自动执行」（done=true）；非可逆档/推荐不明/已收口/已执行/
//   due_at 缺失或非法 → null；h/m/s 进位与零填充；
// - ChainPanel.tsx 接线：EscRow 内 autoExecBadge/autoExecCountdown 消费点
//   在场（徽标插在「已收口/待人工」终态标签之后，非静默混入）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { autoExecBadge, autoExecCountdown } from '../src/services/dashboard.ts';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readSrc = (rel) => readFileSync(join(STATIC_ROOT, rel), 'utf-8');

const proj = (over = {}) => ({
  executed: false,
  recommended_choice: null,
  risk_tier: null,
  skip_reason: null,
  anchor_at: null,
  due_at: null,
  ...over,
});

// ── autoExecBadge：独立徽标（非静默混入人工） ────────────────────────

test('executed=true → 「自动执行」徽标（cyan）', () => {
  const b = autoExecBadge({ auto_exec: proj({ executed: true }) });
  assert.ok(b, '应渲染徽标');
  assert.equal(b.label, '自动执行');
  assert.notEqual(b.color, 'green', '独立配色，不与人工已收口绿标混同');
});

test('auto_exec 缺席 / null / executed=false → null 不渲染', () => {
  assert.equal(autoExecBadge({}), null);
  assert.equal(autoExecBadge({ auto_exec: null }), null);
  assert.equal(autoExecBadge({ auto_exec: proj({ executed: false }) }), null);
  assert.equal(autoExecBadge(null), null);
  assert.equal(autoExecBadge(undefined), null);
});

// ── autoExecCountdown：倒计时展示逻辑 ────────────────────────────────

const DUE = '2026-11-11T12:00:00+00:00';

test('可逆档 + 明确推荐 + 窗未满 → mm:ss 倒计时（done=false）', () => {
  const esc = {
    handled: false,
    auto_exec: proj({
      recommended_choice: 'manual_fixed_reverify',
      risk_tier: 'reversible-experiment',
      due_at: DUE,
    }),
  };
  const c = autoExecCountdown(esc, new Date('2026-11-11T11:58:40+00:00'));
  assert.ok(c);
  assert.equal(c.done, false);
  assert.equal(c.text, '自动执行倒计时 01:20');
});

test('窗超 1 小时 → h:mm:ss 进位', () => {
  const esc = {
    handled: false,
    auto_exec: proj({
      recommended_choice: 'manual_fixed_reverify',
      risk_tier: 'reversible-experiment',
      due_at: DUE,
    }),
  };
  const c = autoExecCountdown(esc, new Date('2026-11-11T10:30:15+00:00'));
  assert.ok(c);
  assert.equal(c.text, '自动执行倒计时 1:29:45');
});

test('窗已满 → 「等待自动执行」（done=true，gold 档位判断依据）', () => {
  const esc = {
    handled: false,
    auto_exec: proj({
      recommended_choice: 'manual_fixed_reverify',
      risk_tier: 'reversible-experiment',
      due_at: DUE,
    }),
  };
  const c = autoExecCountdown(esc, new Date('2026-11-11T12:00:01+00:00'));
  assert.ok(c);
  assert.equal(c.done, true);
  assert.equal(c.text, '等待自动执行');
});

test('非可逆档（state-advance/terminal）→ null 不渲染倒计时', () => {
  const mk = (tier) => ({
    handled: false,
    auto_exec: proj({ recommended_choice: 'force_advance', risk_tier: tier, due_at: DUE }),
  });
  assert.equal(autoExecCountdown(mk('state-advance'), new Date('2026-11-11T11:00:00+00:00')), null);
  assert.equal(autoExecCountdown(mk('terminal'), new Date('2026-11-11T11:00:00+00:00')), null);
});

test('推荐不明确（recommended_choice 空）→ null', () => {
  const esc = {
    handled: false,
    auto_exec: proj({ risk_tier: 'reversible-experiment', skip_reason: '推荐歧义', due_at: DUE }),
  };
  assert.equal(autoExecCountdown(esc, new Date('2026-11-11T11:00:00+00:00')), null);
});

test('已收口（handled）或已执行（executed）→ null', () => {
  const base = {
    recommended_choice: 'manual_fixed_reverify',
    risk_tier: 'reversible-experiment',
    due_at: DUE,
  };
  assert.equal(
    autoExecCountdown({ handled: true, auto_exec: proj(base) }, new Date('2026-11-11T11:00:00+00:00')),
    null,
  );
  assert.equal(
    autoExecCountdown({ handled: false, auto_exec: proj({ ...base, executed: true }) }, new Date('2026-11-11T11:00:00+00:00')),
    null,
  );
});

test('due_at 缺失 / 非法 → null（不 NaN 渲染）', () => {
  const esc = {
    handled: false,
    auto_exec: proj({ recommended_choice: 'c', risk_tier: 'reversible-experiment' }),
  };
  assert.equal(autoExecCountdown(esc, new Date('2026-11-11T11:00:00+00:00')), null);
  const bad = {
    handled: false,
    auto_exec: proj({ recommended_choice: 'c', risk_tier: 'reversible-experiment', due_at: 'not-a-time' }),
  };
  assert.equal(autoExecCountdown(bad, new Date('2026-11-11T11:00:00+00:00')), null);
});

// ── ChainPanel.tsx 接线（源码扫描钉消费点） ──────────────────────────

const panel = readSrc('src/pages/activities/components/ChainPanel.tsx');

test('EscRow 接线：徽标与倒计时消费点在场且插于终态标签之后', () => {
  assert.ok(panel.includes('autoExecBadge(esc)'), 'EscRow 应调用 autoExecBadge');
  assert.ok(panel.includes('autoExecCountdown(esc)'), 'EscRow 应调用 autoExecCountdown');
  assert.ok(panel.includes('autoBadge.label'), '徽标 label 应渲染');
  assert.ok(panel.includes('countdown.text'), '倒计时文案应渲染');
  const handledIdx = panel.indexOf('color="green">已收口</Tag>');
  const badgeIdx = panel.indexOf('autoBadge.label');
  const countdownIdx = panel.indexOf('countdown.text');
  assert.ok(handledIdx > 0 && badgeIdx > handledIdx, '徽标须在「已收口/待人工」标签之后（独立并存）');
  assert.ok(countdownIdx > badgeIdx);
});

test('倒计时档位接线：done → gold、未满 → geekblue', () => {
  assert.ok(panel.includes("countdown.done ? 'gold' : 'geekblue'"), 'done/未满双色档位应接线');
});

test('QueueRow 与全量列表复用 EscRow（徽标贯通两视图，无平行实现）', () => {
  const escRowCount = (panel.match(/<EscRow /g) || []).length;
  assert.ok(escRowCount >= 2, `EscRow 至少两处消费（人工队列 + 全量），实测 ${escRowCount}`);
});
