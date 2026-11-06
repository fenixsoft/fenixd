// SPEC 列表整行点击测试（add-spec-subtitle-and-row-click 任务 2.1/3.2）。
// 零依赖 node:test（同 specTitleSubtitle.test.mjs 习语：纯逻辑直测 + 源码
// 扫描钉 JSX 接线；渲染行为由 npm run build 与浏览器冒烟覆盖）。
//
// 覆盖：
// - specDetailPath 编码口径（#/?/% 截断防护，与 index.tsx 路由表同形）；
// - rowClickHitsExpandIcon 守卫语义（命中/不命中/target 缺失容错不吞导航）；
// - list.tsx 整行点击接线：守卫接入 + history.push + 整行 cursor pointer +
//   既有选中行底色 style 逻辑不变（PRIORITY_TERMINAL 分支合并进 style）；
// - 四类守卫钉死：展开钮（守卫单源选择器）、操作列（stopPropagation 单元格
//   守卫与菜单 domEvent 阻断）、展开行内容（行外渲染不在 onRow 命中面）、
//   名称链接（自有 onClick 保留不拦截、与行导航同源路径）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  ROW_EXPAND_ICON_SELECTOR,
  rowClickHitsExpandIcon,
  specDetailPath,
} from '../src/pages/projects/specRowClick.ts';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readSrc = (rel) => readFileSync(join(STATIC_ROOT, rel), 'utf-8');

// ── 纯逻辑直测 ───────────────────────────────────────────────────────

test('specDetailPath：项目名/SPEC 名经 encodeURIComponent（#/?/% 截断防护）', () => {
  assert.equal(specDetailPath('p1', 'add-foo'), '/projects/p1/add-foo');
  assert.equal(specDetailPath('a#b', 'c?d'), '/projects/a%23b/c%3Fd');
  assert.equal(specDetailPath('a/b', 'c%d'), '/projects/a%2Fb/c%25d');
});

test('rowClickHitsExpandIcon：展开钮命中返回 true（closest 冒泡链判定）', () => {
  const hit = { closest: (sel) => (sel === ROW_EXPAND_ICON_SELECTOR ? { tagName: 'BUTTON' } : null) };
  assert.equal(rowClickHitsExpandIcon({ target: hit }), true);
});

test('rowClickHitsExpandIcon：普通单元格目标不命中（行导航照常）', () => {
  assert.equal(rowClickHitsExpandIcon({ target: { closest: () => null } }), false);
});

test('rowClickHitsExpandIcon：target 缺失/非元素容错不吞导航', () => {
  assert.equal(rowClickHitsExpandIcon({ target: null }), false);
  assert.equal(rowClickHitsExpandIcon({}), false);
});

// ── list.tsx 整行点击接线源码扫描 ────────────────────────────────────

const listSrc = readSrc('src/pages/projects/list.tsx');

const onRowBlock = () => {
  const start = listSrc.indexOf('onRow={(record)');
  return listSrc.slice(start, listSrc.indexOf('})}', start) + 3);
};

test('onRow 整行点击接线：守卫 + history.push + 整行 cursor pointer', () => {
  const block = onRowBlock();
  assert.ok(block.includes('onClick: (e)'), 'onRow 应声明整行 onClick');
  assert.ok(block.includes('rowClickHitsExpandIcon(e)'), 'onClick 应接入展开钮守卫单源');
  assert.ok(block.includes('history.push(specDetailPath(project, record.name))'), '行导航应走路径单源');
  assert.ok(block.includes("cursor: 'pointer'"), '整行应为 pointer 光标形态');
});

test('既有选中行底色 style 逻辑不变（PRIORITY_TERMINAL 分支合并进 style）', () => {
  const block = onRowBlock();
  assert.ok(block.includes("PRIORITY_TERMINAL.has(record.status || '')"), '终态分支判据应保留');
  assert.ok(block.includes('backgroundColor: DSH_INTERACTIVE_ACTIVE'), '选中行底色 token 应保留');
});

test('list.tsx 应从守卫单源导入（guard/path 不在页面内散写）', () => {
  assert.ok(
    listSrc.includes("import { rowClickHitsExpandIcon, specDetailPath } from './specRowClick';"),
    '应从 specRowClick 单源导入',
  );
});

// ── 四类守卫钉死 ─────────────────────────────────────────────────────

test('守卫一 展开钮：单源选择器锚在 specRowClick（树展开与 error 展开共用）', () => {
  const svc = readSrc('src/pages/projects/specRowClick.ts');
  assert.ok(svc.includes('.ant-table-row-expand-icon'), 'antd 展开图标类锚应在守卫单源定义');
});

test('守卫二 操作列：交互单元格 stopPropagation 守卫在场（零改动命中）', () => {
  const a0 = listSrc.indexOf("key: 'actions'");
  const actions = listSrc.slice(a0, listSrc.indexOf('  ];', a0));
  assert.ok(actions.includes('e.stopPropagation()'), '操作列单元格应有 stopPropagation 守卫');
  assert.ok(actions.includes('domEvent.stopPropagation()'), '菜单项 domEvent 亦应阻断冒泡');
});

test('守卫三 展开行内容：expandedRowRender 在场（行外渲染不在 onRow 命中面）', () => {
  assert.ok(
    listSrc.includes('expandedRowRender:'),
    'error 信息展开行应保留——antd 渲染于行外 ant-table-expanded-row，不命中 onRow',
  );
});

test('守卫四 名称链接：自有 onClick 保留、与行导航同源路径、无拦截', () => {
  const cellStart = listSrc.indexOf('function SpecNameCell(');
  const cell = listSrc.slice(cellStart, listSrc.indexOf('// ── 验证列悬浮提示'));
  assert.ok(cell.includes('onClick={handleClick}'), '名称链接自有跳转应保留（不额外拦截，同目标连跳无害）');
  assert.ok(cell.includes('specDetailPath(project, record.name)'), '名称跳转应与行导航同走路径单源');
});
