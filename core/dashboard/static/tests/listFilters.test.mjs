// parseListFilters 单元测试（零依赖，node 原生 type-stripping 加载 .ts）。
// 运行：cd core/dashboard/static && node --test tests/listFilters.test.mjs
// add-spec-list-filter-stickiness 1.3：URL 查询参数 fail-safe 白名单解析。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseListFilters,
  LIST_STATUSES,
  LIST_TABS,
  LIST_TYPES,
} from '../src/pages/projects/listFilters.ts';

const sp = (s) => new URLSearchParams(s);

test('词表常量：状态 11 项、页签 4 项、类型 2 项', () => {
  assert.equal(LIST_STATUSES.length, 11);
  assert.deepEqual(
    [...LIST_STATUSES],
    ['drafted', 'ready', 'reviewing', 'implementing', 'implemented', 'testing',
      'verified', 'bug-found', 'blocked', 'done', 'pushed'],
  );
  assert.deepEqual([...LIST_TABS], ['dev', 'quality', 'regression', 'session']);
  assert.deepEqual([...LIST_TYPES], ['active', 'completed']);
});

test('合法全参解析：五参全部生效', () => {
  const f = parseListFilters(sp('?tab=quality&q=%E6%90%9C%E7%B4%A2&status=ready,blocked&type=active&archived=1'));
  assert.deepEqual(f, {
    tab: 'quality',
    q: '搜索',
    statusList: ['ready', 'blocked'],
    type: 'active',
    archivedOnly: true,
  });
});

test('空参 → 全默认（dev / 无关键词 / 全状态 / 全类型 / 未归档）', () => {
  assert.deepEqual(parseListFilters(sp('')), {
    tab: 'dev',
    q: '',
    statusList: [],
    type: '',
    archivedOnly: false,
  });
});

test('非法 tab / type 整体忽略回默认', () => {
  const f = parseListFilters(sp('?tab=hack&type=xxx&archived=1'));
  assert.equal(f.tab, 'dev');
  assert.equal(f.type, '');
  // 同参数串中的合法参数不受影响
  assert.equal(f.archivedOnly, true);
});

test('status 混合合法与非法枚举：非法逐个丢弃、合法保留', () => {
  const f = parseListFilters(sp('?status=not-a-status,ready,xxx,blocked'));
  assert.deepEqual(f.statusList, ['ready', 'blocked']);
});

test('status 全非法视为无参', () => {
  const f = parseListFilters(sp('?status=foo,bar'));
  assert.deepEqual(f.statusList, []);
});

test('status 重复枚举去重保序', () => {
  const f = parseListFilters(sp('?status=ready,blocked,ready'));
  assert.deepEqual(f.statusList, ['ready', 'blocked']);
});

test('archived 仅 1 为真，archived=9 / 其他值均为假', () => {
  assert.equal(parseListFilters(sp('?archived=1')).archivedOnly, true);
  assert.equal(parseListFilters(sp('?archived=9')).archivedOnly, false);
  assert.equal(parseListFilters(sp('?archived=true')).archivedOnly, false);
  assert.equal(parseListFilters(sp('?archived=0')).archivedOnly, false);
});

test('q 全空白（trim 后空串）视为无参', () => {
  const f = parseListFilters(sp('?q=%20%20%20'));
  assert.equal(f.q, '');
});

test('q 前后空白被 trim（回显与过滤口径一致）', () => {
  assert.equal(parseListFilters(sp('?q=%20api%20')).q, 'api');
});

test('spec 页签全部合法值均被接受', () => {
  for (const t of LIST_TABS) {
    assert.equal(parseListFilters(sp(`?tab=${t}`)).tab, t);
  }
});
