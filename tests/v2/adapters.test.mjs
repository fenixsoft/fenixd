import { test } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { Adapters } = require('../../core/dashboard/static/v2/adapters.js');
const fx = JSON.parse(readFileSync(new URL('./fixtures/api-samples.json', import.meta.url)));

// ─── SPEC_LIFECYCLE ──────────────────────────────────────
test('SPEC_LIFECYCLE: 行为规格 §2 枚举顺序', () => {
  const expected = [
    'drafted', 'ready', 'implementing', 'bug-found', 'implemented',
    'testing', 'verified', 'done', 'pushed', 'blocked',
  ];
  assert.deepEqual(Adapters.SPEC_LIFECYCLE, expected);
});

// ─── adaptSpecs ──────────────────────────────────────────
test('adaptSpecs: 生命周期排序(非 fix 顶层行按 SPEC_LIFECYCLE 序)', () => {
  const rows = Adapters.adaptSpecs(fx.specs.specs);
  const nonFixTop = rows.filter(r => !r.isFixChild);
  const idx = s => {
    const i = Adapters.SPEC_LIFECYCLE.indexOf(s);
    return i >= 0 ? i : 99;
  };
  const statusSeq = nonFixTop.map(r => idx(r.status));
  // 非 fix 顶层行的状态序应单调不减
  for (let i = 1; i < statusSeq.length; i++) {
    assert.ok(
      statusSeq[i] >= statusSeq[i - 1],
      `排序违反: ${nonFixTop[i - 1].status}(${statusSeq[i - 1]}) > ${nonFixTop[i].status}(${statusSeq[i]})`,
    );
  }
});

test('adaptSpecs: fix- 前缀构建 children 树', () => {
  const rows = Adapters.adaptSpecs(fx.specs.specs);
  // 找一个有 children 的父行
  const parent = rows.find(r => r.children && r.children.length > 0);
  assert.ok(parent, '存在带 children 的父行');
  for (const c of parent.children) {
    assert.equal(c.isFixChild, true, '子行标记 isFixChild=true');
    assert.ok(c.name.startsWith('fix-'), '子行名以 fix- 开头');
  }
});

test('adaptSpecs: 多层 fix 树(deep > 1)', () => {
  // fixture 中有 fix-fix-* 挂在 fix-* 下
  const rows = Adapters.adaptSpecs(fx.specs.specs);
  const hasDeep = rows.some(r =>
    r.children && r.children.some(c => c.children && c.children.length > 0),
  );
  if (fx.specs.specs.some(s => s.name.match(/^fix-fix-/))) {
    assert.ok(hasDeep, '存在深度 ≥2 的 fix 树');
  }
});

test('adaptSpecs: 父行聚合子任务进度', () => {
  const rows = Adapters.adaptSpecs(fx.specs.specs);
  const parent = rows.find(r => r.children && r.children.length > 0);
  assert.ok(parent);
  // 父行 task_done/task_total 应等于子行之和
  const sumDone = parent.children.reduce((a, c) => a + (c.task_done || 0), 0);
  const sumTotal = parent.children.reduce((a, c) => a + (c.task_total || 0), 0);
  assert.equal(parent.task_done, sumDone, '父行 task_done = 子行之和');
  assert.equal(parent.task_total, sumTotal, '父行 task_total = 子行之和');
});

test('adaptSpecs: 数字字段数字化(防字符串)', () => {
  const rows = Adapters.adaptSpecs(fx.specs.specs);
  for (const r of rows) {
    assert.equal(typeof r.task_done, 'number', `${r.name}.task_done should be number`);
    assert.equal(typeof r.task_total, 'number', `${r.name}.task_total should be number`);
    assert.equal(typeof r.verify_done, 'number', `${r.name}.verify_done should be number`);
    assert.equal(typeof r.verify_total, 'number', `${r.name}.verify_total should be number`);
  }
});

// ─── adaptOverview ───────────────────────────────────────
test('adaptOverview: totals 所有字段数字化', () => {
  const s = Adapters.adaptOverview(fx.overview);
  for (const k of Object.keys(s)) {
    assert.equal(typeof s[k], 'number', `overview.${k} should be number`);
  }
});

test('adaptOverview: NaN/空值回退为 0', () => {
  const s = Adapters.adaptOverview({ spec_count: '', task_done: undefined, task_total: 'abc' });
  assert.equal(s.spec_count, 0);
  assert.equal(s.task_done, 0);
  assert.equal(s.task_total, 0);
});

// ─── adaptProjects ──────────────────────────────────────
test('adaptProjects: 数字字段归一化', () => {
  const rows = Adapters.adaptProjects(fx.overview.projects);
  assert.ok(Array.isArray(rows));
  for (const r of rows) {
    assert.equal(typeof r.spec_count, 'number', `${r.name}.spec_count should be number`);
    assert.equal(typeof r.task_done, 'number', `${r.name}.task_done should be number`);
    assert.equal(typeof r.task_total, 'number', `${r.name}.task_total should be number`);
    assert.equal(typeof r.problems, 'number', `${r.name}.problems should be number`);
    assert.equal(typeof r.active_runs, 'number', `${r.name}.active_runs should be number`);
    assert.equal(typeof r.scenario_count, 'number', `${r.name}.scenario_count should be number`);
  }
});

// ─── adaptAlerts ─────────────────────────────────────────
test('adaptAlerts: 返回数组且保留核心字段', () => {
  const rows = Adapters.adaptAlerts(fx.alerts.alerts);
  assert.ok(Array.isArray(rows));
  for (const r of rows) {
    assert.ok(r.id, 'alert has id');
    assert.ok(r.severity, 'alert has severity');
    assert.ok('handled' in r, 'alert has handled');
  }
});

// ─── adaptActivities ─────────────────────────────────────
test('adaptActivities: 返回数组且保留核心字段', () => {
  const rows = Adapters.adaptActivities(fx.admin_activities.projects[0].activities);
  assert.ok(Array.isArray(rows));
  for (const r of rows) {
    assert.ok(r.id, 'activity has id');
    assert.ok(r.kind || r.signal_type, 'activity has kind or signal_type');
    assert.ok('handled' in r, 'activity has handled');
  }
});

// ─── adaptConfig ─────────────────────────────────────────
test('adaptConfig: llm 正常透传', () => {
  const cfg = Adapters.adaptConfig(fx.config);
  assert.ok(cfg.llm);
  assert.ok(Array.isArray(cfg.llm.providers));
  assert.ok(cfg.llm.providers.length > 0);
});

test('adaptConfig: llm 缺失时兜底空结构(behavior.md §6)', () => {
  const cfg = Adapters.adaptConfig({});
  assert.deepEqual(cfg.llm, { providers: [] });
});

test('adaptConfig: llm 有键但无 providers 时兜底', () => {
  const cfg = Adapters.adaptConfig({ llm: {} });
  assert.deepEqual(cfg.llm, { providers: [] });
});

test('adaptConfig: agents 缺失时兜底', () => {
  const cfg = Adapters.adaptConfig({});
  assert.ok(cfg.agents);
  assert.ok(cfg.gates);
});

// ─── buildConfigPayload ──────────────────────────────────
test('buildConfigPayload: 空表单回退快照值', () => {
  const payload = Adapters.buildConfigPayload(
    { max_concurrent: '' },
    { agents: { max_concurrent: 3 } },
    { max_concurrent: 2 },
  );
  assert.equal(payload.agents.max_concurrent, 3);
});

test('buildConfigPayload: 快照为空时回退默认值', () => {
  const payload = Adapters.buildConfigPayload(
    { max_turns: NaN },
    null,
    { max_turns: 300 },
  );
  assert.equal(payload.agents.max_turns, 300);
});

test('buildConfigPayload: 正常值不回退', () => {
  const payload = Adapters.buildConfigPayload(
    { max_concurrent: 5, run_timeout_seconds: 1800 },
    { agents: { max_concurrent: 3 } },
    { max_concurrent: 2 },
  );
  assert.equal(payload.agents.max_concurrent, 5);
  assert.equal(payload.agents.run_timeout_seconds, 1800);
});

test('buildConfigPayload: llm providers 透传', () => {
  const payload = Adapters.buildConfigPayload(
    { providers: [{ name: 'test', baseurl: 'http://x', apikey: 'k', model: 'm' }] },
    {},
    {},
  );
  assert.ok(payload.llm);
  assert.ok(Array.isArray(payload.llm.providers));
  assert.equal(payload.llm.providers[0].name, 'test');
});

test('buildConfigPayload: gates.approve_mode 透传(form 顶层)', () => {
  const payload = Adapters.buildConfigPayload(
    { approve_mode: 'auto' },
    {},
    {},
  );
  assert.equal(payload.gates.approve_mode, 'auto');
});

test('buildConfigPayload: gates.approve_mode 从 snapshot 回退', () => {
  const payload = Adapters.buildConfigPayload(
    {},
    { gates: { approve_mode: 'auto' } },
    {},
  );
  assert.equal(payload.gates.approve_mode, 'auto');
});

// ─── validateChain ───────────────────────────────────────
test('validateChain: 完整链返回 true', () => {
  const result = Adapters.validateChain(
    [{ provider: 'p1', model: 'm1' }],
    [{ name: 'p1', model: 'default-model' }],
  );
  assert.equal(result, true);
});

test('validateChain: 空链返回错误文案', () => {
  const result = Adapters.validateChain([], []);
  assert.equal(typeof result, 'string');
  assert.ok(result.length > 0);
});

test('validateChain: 链中 model 为空但 provider 有默认模型时通过', () => {
  const result = Adapters.validateChain(
    [{ provider: 'p1', model: '' }],
    [{ name: 'p1', model: 'provider-default' }],
  );
  assert.equal(result, true);
});

test('validateChain: 链中 model 为空且 provider 无默认模型时失败', () => {
  const result = Adapters.validateChain(
    [{ provider: 'p1', model: '' }],
    [{ name: 'p1' }],
  );
  assert.equal(typeof result, 'string');
});

// ─── adaptSpecDetail ─────────────────────────────────────
test('adaptSpecDetail: verdict.summary 计数数字化(防 "0" 字符串)', () => {
  // 使用真实 fixture 验证; 额外构造一个 string 计数的模拟
  const raw = {
    name: 'test', status: 'done', priority: 1, created: '2026-01-01', updated: '2026-01-02',
    project: 'fenixd', branch: 'fenix/test', implementer_run: 'impl-1', tester_run: null,
    depends_on: null, error: null,
    tasks: [], verify_progress: { exists: true, total: 3, done: 2, current: '', step: null, error: null },
    report: { exists: true, error: null, timestamp: '', summary: { total: 3, passed: 2, warnings: 0, failed: 1, errors: 0 } },
    scenarios: [], bugs: [], screenshots: [], runs: [],
    verdict: { exists: true, status: '结论', status_detail: '详情', conclusion: '结论',
               summary: { passed: '0', failed: '2', errors: '10', product_bugs: '1', env_issues: null } },
    timeline: [],
  };
  const d = Adapters.adaptSpecDetail(raw);
  assert.equal(typeof d.verdict.summary.passed, 'number');
  assert.equal(typeof d.verdict.summary.failed, 'number');
  assert.equal(typeof d.verdict.summary.errors, 'number');
  assert.equal(typeof d.verdict.summary.product_bugs, 'number');
  assert.equal(d.verdict.summary.passed, 0);
  assert.equal(d.verdict.summary.failed, 2);
  assert.equal(d.verdict.summary.env_issues, null);
});
